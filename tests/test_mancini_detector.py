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
    ACCEPTANCE_SECONDS,
    MAX_ACCEPTANCE_PAUSES,
)


def make_detector(level=6781.0, side="lower") -> FailedBreakdownDetector:
    return FailedBreakdownDetector(level=level, side=side)


# ── Estado inicial ──────────────────────────────────────────────────

def test_initial_state():
    d = make_detector()
    assert d.state == State.WATCHING
    assert d.breakdown_low is None
    assert d.acceptance_since is None


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
    """Precio recupera nivel + ACCEPTANCE_PTS → RECOVERY, arranca el reloj."""
    d = make_detector(level=6781)
    d.process_tick(6776, "2026-04-10T14:00:00Z")  # → BREAKDOWN
    assert d.state == State.BREAKDOWN

    price = 6781 + ACCEPTANCE_PTS  # 6782.5
    t = d.process_tick(price, "2026-04-10T14:01:00Z")
    assert t is not None
    assert t.to_state == State.RECOVERY
    assert d.state == State.RECOVERY
    assert d.acceptance_since == "2026-04-10T14:01:00Z"


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

def test_recovery_to_signal_after_acceptance_time():
    """Precio se mantiene sobre nivel >= ACCEPTANCE_SECONDS → SIGNAL."""
    d = make_detector(level=6781)
    d.process_tick(6776, "2026-04-10T14:00:00Z")  # → BREAKDOWN

    # Recovery: arranca reloj en T14:01:00
    d.process_tick(6783, "2026-04-10T14:01:00Z")  # → RECOVERY
    assert d.state == State.RECOVERY
    assert d.acceptance_since == "2026-04-10T14:01:00Z"

    # Elapsed = 60s < 120s → sigue en RECOVERY
    t = d.process_tick(6784, "2026-04-10T14:02:00Z")
    assert t is None
    assert d.state == State.RECOVERY

    # Elapsed = 150s >= 120s → SIGNAL
    t = d.process_tick(6785, "2026-04-10T14:03:30Z")
    assert t is not None
    assert t.to_state == State.SIGNAL
    assert d.state == State.SIGNAL
    assert d.signal_price == 6785
    assert d.breakdown_low == 6776


# ── Reloj de aceptación ─────────────────────────────────────────────

def test_recovery_clock_pauses_below_threshold():
    """Si el precio baja del umbral (pero sigue sobre el nivel) el reloj se pausa."""
    d = make_detector(level=6781)
    d.process_tick(6776, "2026-04-10T14:00:00Z")   # → BREAKDOWN
    d.process_tick(6783, "2026-04-10T14:01:00Z")   # → RECOVERY, reloj arranca
    assert d.acceptance_since == "2026-04-10T14:01:00Z"

    # Precio baja entre nivel y umbral → reloj se pausa
    d.process_tick(6781.0, "2026-04-10T14:02:00Z")
    assert d.state == State.RECOVERY
    assert d.acceptance_since is None

    # Precio sube de nuevo → reloj reinicia desde T14:03:00
    d.process_tick(6783, "2026-04-10T14:03:00Z")
    assert d.acceptance_since == "2026-04-10T14:03:00Z"


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
    assert d.acceptance_since is None  # reloj reseteado


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

    # Tick 5: reclaim → RECOVERY, arranca reloj en T14:04:00
    t = d.process_tick(6783, "2026-04-10T14:04:00Z")
    assert t.to_state == State.RECOVERY

    # Tick 6: elapsed = 60s < 120s → sigue en RECOVERY
    assert d.process_tick(6784, "2026-04-10T14:05:00Z") is None

    # Tick 7: elapsed = 150s >= 120s → SIGNAL
    t = d.process_tick(6785, "2026-04-10T14:06:30Z")
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

    # Segundo recovery exitoso — reloj arranca en T14:03:00
    d.process_tick(6783, "2026-04-10T14:03:00Z")
    assert d.state == State.RECOVERY
    d.process_tick(6784, "2026-04-10T14:04:00Z")  # elapsed = 60s
    t = d.process_tick(6785, "2026-04-10T14:05:30Z")  # elapsed = 150s → SIGNAL
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
    d.acceptance_since = "2026-04-10T14:01:00Z"
    d.signal_price = 6785
    d.reset()
    assert d.state == State.WATCHING
    assert d.breakdown_low is None
    assert d.acceptance_since is None
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

    # Recovery: reloj arranca en T14:01:00
    t = d.process_tick(6811, "2026-04-10T14:01:00Z")
    assert t.to_state == State.RECOVERY

    # elapsed = 60s < 120s → sigue RECOVERY
    d.process_tick(6812, "2026-04-10T14:02:00Z")
    assert d.state == State.RECOVERY

    # elapsed = 150s >= 120s → SIGNAL
    t = d.process_tick(6813, "2026-04-10T14:03:30Z")
    assert t.to_state == State.SIGNAL


# ── Métricas de calidad en SIGNAL details ──────────────────────────

def test_signal_includes_quality_metrics():
    """SIGNAL emitido contiene todas las métricas de calidad."""
    d = make_detector(level=6781)
    d.process_tick(6776, "2026-04-10T14:00:00Z")   # → BREAKDOWN (depth=5)
    d.process_tick(6783, "2026-04-10T14:01:00Z")   # → RECOVERY
    d.process_tick(6785, "2026-04-10T14:02:00Z")   # reloj corriendo, max sube a 6785
    t = d.process_tick(6784, "2026-04-10T14:03:30Z")  # elapsed=150s → SIGNAL
    assert t is not None
    assert t.to_state == State.SIGNAL
    assert "breakdown_depth_pts" in t.details
    assert "acceptance_pauses" in t.details
    assert "acceptance_max_above_level" in t.details
    assert "recovery_velocity_pts_min" in t.details


def test_signal_breakdown_depth_calculated():
    """breakdown_depth_pts = nivel - breakdown_low."""
    d = make_detector(level=6781)
    d.process_tick(6774, "2026-04-10T14:00:00Z")   # → BREAKDOWN, low=6774 (depth=7)
    d.process_tick(6783, "2026-04-10T14:01:00Z")   # → RECOVERY
    t = d.process_tick(6784, "2026-04-10T14:03:30Z")  # → SIGNAL
    assert t.details["breakdown_depth_pts"] == 7.0


def test_signal_max_above_level_tracked():
    """acceptance_max_above_level refleja el máximo alcanzado durante la aceptación."""
    d = make_detector(level=6781)
    d.process_tick(6776, "2026-04-10T14:00:00Z")   # → BREAKDOWN
    d.process_tick(6783, "2026-04-10T14:01:00Z")   # → RECOVERY, max=6783 (+2)
    d.process_tick(6788, "2026-04-10T14:02:00Z")   # max sube a 6788 (+7)
    d.process_tick(6784, "2026-04-10T14:02:30Z")   # baja pero max se mantiene
    t = d.process_tick(6784, "2026-04-10T14:03:30Z")  # → SIGNAL
    assert t is not None
    assert t.details["acceptance_max_above_level"] == 7.0


def test_signal_velocity_positive():
    """recovery_velocity_pts_min es positivo cuando hay convicción."""
    d = make_detector(level=6781)
    d.process_tick(6776, "2026-04-10T14:00:00Z")   # → BREAKDOWN
    d.process_tick(6786, "2026-04-10T14:01:00Z")   # → RECOVERY, max=6786 (+5)
    t = d.process_tick(6786, "2026-04-10T14:03:30Z")  # elapsed=150s → SIGNAL
    # velocity = 5 / (150/60) = 5 / 2.5 = 2.0 pts/min
    assert t is not None
    assert t.details["recovery_velocity_pts_min"] == 2.0


# ── Conteo de pausas (retests) ──────────────────────────────────────

def test_acceptance_pauses_increments_on_dip():
    """Precio cae bajo ACCEPTANCE_PTS durante RECOVERY → pauses sube a 1."""
    d = make_detector(level=6781)
    d.process_tick(6776, "2026-04-10T14:00:00Z")   # → BREAKDOWN
    d.process_tick(6783, "2026-04-10T14:01:00Z")   # → RECOVERY, reloj arranca

    # Precio cae entre nivel y umbral → pausa el reloj, pauses += 1
    d.process_tick(6781.5, "2026-04-10T14:01:30Z")
    assert d.acceptance_pauses == 1
    assert d.acceptance_since is None


def test_acceptance_pauses_multiple_dips():
    """Dos dips sucesivos acumulan 2 pausas."""
    d = make_detector(level=6781)
    d.process_tick(6776, "2026-04-10T14:00:00Z")
    d.process_tick(6783, "2026-04-10T14:01:00Z")   # → RECOVERY

    d.process_tick(6781.5, "2026-04-10T14:01:15Z")  # pausa 1
    assert d.acceptance_pauses == 1
    d.process_tick(6783, "2026-04-10T14:01:30Z")    # reloj reinicia
    d.process_tick(6781.5, "2026-04-10T14:01:45Z")  # pausa 2
    assert d.acceptance_pauses == 2


def test_acceptance_pauses_not_incremented_when_clock_already_paused():
    """Si el reloj ya estaba pausado, un nuevo tick bajo umbral no acumula pausa extra."""
    d = make_detector(level=6781)
    d.process_tick(6776, "2026-04-10T14:00:00Z")
    d.process_tick(6783, "2026-04-10T14:01:00Z")   # → RECOVERY

    d.process_tick(6781.5, "2026-04-10T14:01:15Z")  # pausa 1, reloj = None
    assert d.acceptance_pauses == 1
    d.process_tick(6781.5, "2026-04-10T14:01:30Z")  # reloj ya era None, no suma
    assert d.acceptance_pauses == 1


def test_acceptance_pauses_reset_on_failed_recovery():
    """Al volver a BREAKDOWN desde RECOVERY, acceptance_pauses se resetea."""
    d = make_detector(level=6781)
    d.process_tick(6776, "2026-04-10T14:00:00Z")
    d.process_tick(6783, "2026-04-10T14:01:00Z")   # → RECOVERY
    d.process_tick(6781.5, "2026-04-10T14:01:15Z")  # pausa 1
    assert d.acceptance_pauses == 1

    # Recaída a BREAKDOWN
    d.process_tick(6778, "2026-04-10T14:01:30Z")
    assert d.acceptance_pauses == 0


def test_two_pauses_still_emits_signal():
    """2 pausas son aceptables — el SIGNAL se emite correctamente."""
    d = make_detector(level=6781)
    d.process_tick(6776, "2026-04-10T14:00:00Z")
    d.process_tick(6783, "2026-04-10T14:01:00Z")   # → RECOVERY, reloj T01:00

    d.process_tick(6781.5, "2026-04-10T14:01:15Z")  # pausa 1, reloj para
    d.process_tick(6783, "2026-04-10T14:01:30Z")    # reloj reinicia T01:30
    d.process_tick(6781.5, "2026-04-10T14:01:45Z")  # pausa 2, reloj para
    d.process_tick(6783, "2026-04-10T14:02:00Z")    # reloj reinicia T02:00

    # 120s desde T02:00 → SIGNAL
    t = d.process_tick(6784, "2026-04-10T14:04:00Z")
    assert t is not None
    assert t.to_state == State.SIGNAL
    assert t.details["acceptance_pauses"] == 2


# ── Filtro duro: retests excesivos ──────────────────────────────────

def test_excessive_retests_resets_to_watching():
    """MAX_ACCEPTANCE_PAUSES retests durante RECOVERY → WATCHING, no SIGNAL."""
    d = make_detector(level=6781)
    d.process_tick(6776, "2026-04-10T14:00:00Z")
    d.process_tick(6783, "2026-04-10T14:01:00Z")   # → RECOVERY

    # Simular MAX_ACCEPTANCE_PAUSES ciclos dip/subida
    for i in range(MAX_ACCEPTANCE_PAUSES):
        ts_up   = f"2026-04-10T14:0{i+1}:00Z"
        ts_down = f"2026-04-10T14:0{i+1}:30Z"
        d.process_tick(6783, ts_up)    # reloj arranca/reinicia
        t = d.process_tick(6781.5, ts_down)  # pausa
        if t is not None:
            break

    assert t is not None
    assert t.to_state == State.WATCHING
    assert t.details["reason"] == "excessive_retests"
    assert d.state == State.WATCHING
    assert d.acceptance_pauses == 0
    assert d.breakdown_low is None


def test_excessive_retests_detector_can_restart():
    """Tras resetear por retests excesivos, el detector puede detectar un nuevo breakdown."""
    d = make_detector(level=6781)
    d.process_tick(6776, "2026-04-10T14:00:00Z")
    d.process_tick(6783, "2026-04-10T14:01:00Z")

    for i in range(MAX_ACCEPTANCE_PAUSES):
        d.process_tick(6783, f"2026-04-10T14:0{i+1}:00Z")
        t = d.process_tick(6781.5, f"2026-04-10T14:0{i+1}:30Z")
        if t is not None and t.to_state == State.WATCHING:
            break

    assert d.state == State.WATCHING

    # Nuevo breakdown después del reset
    t2 = d.process_tick(6774, "2026-04-10T14:10:00Z")
    assert t2 is not None
    assert t2.to_state == State.BREAKDOWN


# ── Persistencia con campos nuevos ─────────────────────────────────

def test_to_dict_includes_new_fields():
    """to_dict() serializa acceptance_pauses y acceptance_max_price."""
    d = make_detector(level=6781)
    d.acceptance_pauses = 2
    d.acceptance_max_price = 6788.5

    data = d.to_dict()
    assert data["acceptance_pauses"] == 2
    assert data["acceptance_max_price"] == 6788.5


def test_from_dict_with_missing_new_fields():
    """Diccionarios sin campos nuevos (estado antiguo) se deserializan con defaults."""
    old_data = {
        "level": 6781.0,
        "side": "lower",
        "state": "RECOVERY",
        "breakdown_low": 6776.0,
        "acceptance_since": "2026-04-10T14:01:00Z",
        "signal_price": None,
        "signal_timestamp": None,
        # Sin acceptance_pauses ni acceptance_max_price
    }
    d = FailedBreakdownDetector.from_dict(old_data)
    assert d.acceptance_pauses == 0
    assert d.acceptance_max_price is None


def test_roundtrip_with_new_fields(tmp_path):
    """Serialización completa (save/load) con campos nuevos."""
    d = make_detector(level=6781, side="lower")
    d.state = State.RECOVERY
    d.breakdown_low = 6776.0
    d.acceptance_since = "2026-04-10T14:01:00Z"
    d.acceptance_pauses = 1
    d.acceptance_max_price = 6785.0

    path = tmp_path / "state.json"
    save_detectors([d], path=path)
    loaded = load_detectors(path=path)

    assert loaded[0].acceptance_pauses == 1
    assert loaded[0].acceptance_max_price == 6785.0


def test_reset_clears_new_fields():
    """reset() limpia acceptance_pauses y acceptance_max_price."""
    d = make_detector()
    d.acceptance_pauses = 2
    d.acceptance_max_price = 6790.0
    d.reset()
    assert d.acceptance_pauses == 0
    assert d.acceptance_max_price is None
