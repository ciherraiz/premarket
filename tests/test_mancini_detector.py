"""Tests para scripts/mancini/detector.py — Máquina de estados Failed Breakdown."""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from scripts.mancini.detector import (
    FailedBreakdownDetector,
    State,
    StateTransition,
    save_detectors,
    load_detectors,
    MIN_BREAK_PTS,
    MAX_BREAK_PTS,
    ACCEPTANCE_PTS,
    ACCEPTANCE_POLLS,
)


def make_detector(level=6781.0, side="lower") -> FailedBreakdownDetector:
    return FailedBreakdownDetector(level=level, side=side)


# ── Estado inicial ──────────────────────────────────────────────────

def test_initial_state():
    d = make_detector()
    assert d.state == State.WATCHING
    assert d.breakdown_low is None
    assert d.acceptance_count == 0


# ── WATCHING → BREAKDOWN ────────────────────────────────────────────

def test_watching_to_breakdown_min_depth():
    """Precio cae justo MIN_BREAK_PTS debajo del nivel → BREAKDOWN."""
    d = make_detector(level=6781)
    price = 6781 - MIN_BREAK_PTS  # 6779
    t = d.process_tick(price, "2026-04-10T14:00:00Z")
    assert t is not None
    assert t.to_state == State.BREAKDOWN
    assert d.state == State.BREAKDOWN
    assert d.breakdown_low == price


def test_watching_to_breakdown_max_depth():
    """Precio cae exactamente MAX_BREAK_PTS → todavía es BREAKDOWN."""
    d = make_detector(level=6781)
    price = 6781 - MAX_BREAK_PTS  # 6770
    t = d.process_tick(price, "2026-04-10T14:00:00Z")
    assert t is not None
    assert t.to_state == State.BREAKDOWN


def test_watching_stays_watching_too_shallow():
    """Precio cae menos de MIN_BREAK_PTS → sigue WATCHING."""
    d = make_detector(level=6781)
    price = 6781 - 1  # solo 1 pt, insuficiente
    t = d.process_tick(price, "2026-04-10T14:00:00Z")
    assert t is None
    assert d.state == State.WATCHING


def test_watching_stays_watching_price_above():
    """Precio por encima del nivel → sigue WATCHING."""
    d = make_detector(level=6781)
    t = d.process_tick(6790, "2026-04-10T14:00:00Z")
    assert t is None
    assert d.state == State.WATCHING


# ── BREAKDOWN → RECOVERY ────────────────────────────────────────────

def test_breakdown_to_recovery():
    """Precio recupera nivel + ACCEPTANCE_PTS → RECOVERY."""
    d = make_detector(level=6781)
    d.process_tick(6776, "2026-04-10T14:00:00Z")  # → BREAKDOWN
    assert d.state == State.BREAKDOWN

    price = 6781 + ACCEPTANCE_PTS  # 6782.5
    t = d.process_tick(price, "2026-04-10T14:01:00Z")
    assert t is not None
    assert t.to_state == State.RECOVERY
    assert d.state == State.RECOVERY
    assert d.acceptance_count == 1


def test_breakdown_tracks_low():
    """El detector rastrea el mínimo durante el breakdown."""
    d = make_detector(level=6781)
    d.process_tick(6778, "2026-04-10T14:00:00Z")  # → BREAKDOWN, low=6778
    assert d.breakdown_low == 6778

    d.process_tick(6775, "2026-04-10T14:01:00Z")  # más bajo
    assert d.breakdown_low == 6775

    d.process_tick(6777, "2026-04-10T14:02:00Z")  # sube pero sigue en breakdown
    assert d.breakdown_low == 6775  # no cambia


# ── BREAKDOWN → WATCHING (break demasiado profundo) ─────────────────

def test_breakdown_to_watching_too_deep():
    """Precio cae más de MAX_BREAK_PTS → vuelve a WATCHING."""
    d = make_detector(level=6781)
    d.process_tick(6776, "2026-04-10T14:00:00Z")  # → BREAKDOWN
    assert d.state == State.BREAKDOWN

    price = 6781 - MAX_BREAK_PTS - 1  # 6769, demasiado profundo
    t = d.process_tick(price, "2026-04-10T14:01:00Z")
    assert t is not None
    assert t.to_state == State.WATCHING
    assert d.state == State.WATCHING
    assert d.breakdown_low is None  # reseteado


# ── RECOVERY → SIGNAL ───────────────────────────────────────────────

def test_recovery_to_signal_after_acceptance_polls():
    """Precio se mantiene sobre nivel N polls → SIGNAL."""
    d = make_detector(level=6781)
    d.process_tick(6776, "2026-04-10T14:00:00Z")  # → BREAKDOWN

    # Recovery
    d.process_tick(6783, "2026-04-10T14:01:00Z")  # → RECOVERY (count=1)
    assert d.state == State.RECOVERY
    assert d.acceptance_count == 1

    # Polls de aceptación
    d.process_tick(6784, "2026-04-10T14:02:00Z")  # count=2
    assert d.state == State.RECOVERY
    assert d.acceptance_count == 2

    t = d.process_tick(6785, "2026-04-10T14:03:00Z")  # count=3 → SIGNAL
    assert t is not None
    assert t.to_state == State.SIGNAL
    assert d.state == State.SIGNAL
    assert d.signal_price == 6785
    assert d.breakdown_low == 6776


# ── RECOVERY → BREAKDOWN (recaída) ──────────────────────────────────

def test_recovery_to_breakdown_on_fall():
    """Si el precio vuelve a caer durante recovery → BREAKDOWN."""
    d = make_detector(level=6781)
    d.process_tick(6776, "2026-04-10T14:00:00Z")  # → BREAKDOWN
    d.process_tick(6783, "2026-04-10T14:01:00Z")  # → RECOVERY

    price = 6781 - MIN_BREAK_PTS - 1  # cae de nuevo
    t = d.process_tick(price, "2026-04-10T14:02:00Z")
    assert t is not None
    assert t.to_state == State.BREAKDOWN
    assert d.state == State.BREAKDOWN
    assert d.acceptance_count == 0  # reseteado


# ── Secuencia completa (escenario real) ─────────────────────────────

def test_full_failed_breakdown_sequence():
    """Simula secuencia completa: WATCHING → BREAKDOWN → RECOVERY → SIGNAL."""
    d = make_detector(level=6781)

    # Tick 1: precio se acerca pero no rompe
    assert d.process_tick(6782, "2026-04-10T14:00:00Z") is None
    assert d.state == State.WATCHING

    # Tick 2: breakdown (5 pts debajo)
    t = d.process_tick(6776, "2026-04-10T14:01:00Z")
    assert t.to_state == State.BREAKDOWN

    # Tick 3: sigue en breakdown, más bajo
    assert d.process_tick(6774, "2026-04-10T14:02:00Z") is None
    assert d.breakdown_low == 6774

    # Tick 4: empieza a subir pero no reclaim todavía
    assert d.process_tick(6780, "2026-04-10T14:03:00Z") is None
    assert d.state == State.BREAKDOWN

    # Tick 5: reclaim → RECOVERY
    t = d.process_tick(6783, "2026-04-10T14:04:00Z")
    assert t.to_state == State.RECOVERY

    # Ticks 6-7: mantiene sobre nivel → acumula aceptación
    assert d.process_tick(6784, "2026-04-10T14:05:00Z") is None
    assert d.acceptance_count == 2

    # Tick 8: tercer poll → SIGNAL
    t = d.process_tick(6785, "2026-04-10T14:06:00Z")
    assert t.to_state == State.SIGNAL
    assert d.signal_price == 6785
    assert d.breakdown_low == 6774


def test_full_sequence_with_false_recovery():
    """Breakdown → recovery parcial → recaída → segundo intento → SIGNAL."""
    d = make_detector(level=6781)

    # Breakdown
    d.process_tick(6776, "2026-04-10T14:00:00Z")
    assert d.state == State.BREAKDOWN

    # Primer intento de recovery
    d.process_tick(6783, "2026-04-10T14:01:00Z")
    assert d.state == State.RECOVERY

    # Recaída
    d.process_tick(6775, "2026-04-10T14:02:00Z")
    assert d.state == State.BREAKDOWN
    assert d.breakdown_low == 6775

    # Segundo recovery exitoso
    d.process_tick(6783, "2026-04-10T14:03:00Z")
    assert d.state == State.RECOVERY
    d.process_tick(6784, "2026-04-10T14:04:00Z")
    t = d.process_tick(6785, "2026-04-10T14:05:00Z")
    assert t.to_state == State.SIGNAL


# ── Estados terminales ──────────────────────────────────────────────

def test_signal_state_ignores_ticks():
    """Una vez en SIGNAL, process_tick no hace nada."""
    d = make_detector(level=6781)
    d.state = State.SIGNAL
    assert d.process_tick(6790, "2026-04-10T14:00:00Z") is None


def test_done_state_ignores_ticks():
    d = make_detector(level=6781)
    d.state = State.DONE
    assert d.process_tick(6750, "2026-04-10T14:00:00Z") is None


def test_expired_state_ignores_ticks():
    d = make_detector(level=6781)
    d.state = State.EXPIRED
    assert d.process_tick(6750, "2026-04-10T14:00:00Z") is None


def test_active_state_ignores_ticks():
    d = make_detector(level=6781)
    d.state = State.ACTIVE
    assert d.process_tick(6750, "2026-04-10T14:00:00Z") is None


# ── Métodos de control ──────────────────────────────────────────────

def test_mark_active():
    d = make_detector()
    d.state = State.SIGNAL
    d.mark_active()
    assert d.state == State.ACTIVE


def test_mark_done():
    d = make_detector()
    d.state = State.ACTIVE
    d.mark_done()
    assert d.state == State.DONE


def test_mark_expired():
    d = make_detector()
    d.mark_expired()
    assert d.state == State.EXPIRED


def test_reset():
    d = make_detector()
    d.state = State.SIGNAL
    d.breakdown_low = 6774
    d.acceptance_count = 3
    d.signal_price = 6785
    d.reset()
    assert d.state == State.WATCHING
    assert d.breakdown_low is None
    assert d.acceptance_count == 0
    assert d.signal_price is None


# ── Serialización ───────────────────────────────────────────────────

def test_to_dict_and_from_dict_roundtrip():
    d = make_detector(level=6781, side="lower")
    d.state = State.BREAKDOWN
    d.breakdown_low = 6776

    data = d.to_dict()
    restored = FailedBreakdownDetector.from_dict(data)
    assert restored.level == 6781
    assert restored.side == "lower"
    assert restored.state == State.BREAKDOWN
    assert restored.breakdown_low == 6776


def test_save_and_load_detectors(tmp_path):
    path = tmp_path / "state.json"
    d1 = make_detector(level=6809, side="upper")
    d2 = make_detector(level=6781, side="lower")
    d2.state = State.BREAKDOWN
    d2.breakdown_low = 6776

    save_detectors([d1, d2], path=path)
    assert path.exists()

    loaded = load_detectors(path=path)
    assert len(loaded) == 2
    assert loaded[0].level == 6809
    assert loaded[0].side == "upper"
    assert loaded[1].state == State.BREAKDOWN
    assert loaded[1].breakdown_low == 6776


def test_load_detectors_nonexistent(tmp_path):
    path = tmp_path / "nonexistent.json"
    assert load_detectors(path=path) == []


# ── Detector para nivel superior ────────────────────────────────────

def test_upper_level_failed_breakdown():
    """El patrón funciona igual para el nivel superior."""
    d = make_detector(level=6809, side="upper")

    # Precio cae debajo de 6809 (breakdown)
    t = d.process_tick(6804, "2026-04-10T14:00:00Z")
    assert t.to_state == State.BREAKDOWN

    # Recovery
    t = d.process_tick(6811, "2026-04-10T14:01:00Z")
    assert t.to_state == State.RECOVERY

    # Aceptación
    d.process_tick(6812, "2026-04-10T14:02:00Z")
    t = d.process_tick(6813, "2026-04-10T14:03:00Z")
    assert t.to_state == State.SIGNAL
