"""Tests para scripts/mancini/monitor.py — Monitor /ES con detectores y trades."""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from scripts.mancini.config import DailyPlan, save_plan, save_weekly
from scripts.mancini.detector import State, save_detectors, FailedBreakdownDetector
from scripts.mancini.trade_manager import TradeStatus
from scripts.mancini.monitor import ManciniMonitor, ET


@pytest.fixture
def plan_path(tmp_path):
    return tmp_path / "mancini_plan.json"


@pytest.fixture
def state_path(tmp_path):
    return tmp_path / "mancini_state.json"


@pytest.fixture
def sample_plan(plan_path):
    plan = DailyPlan(
        fecha="2026-04-10",
        key_level_upper=6809,
        targets_upper=[6819, 6830],
        key_level_lower=6781,
        targets_lower=[6766],
    )
    save_plan(plan, plan_path)
    return plan


@pytest.fixture
def weekly_path(tmp_path):
    return tmp_path / "mancini_weekly.json"


@pytest.fixture
def monitor(plan_path, state_path, weekly_path):
    """Monitor sin client (para tests sin TastyTrade)."""
    m = ManciniMonitor(client=None, plan_path=plan_path, state_path=state_path,
                       weekly_path=weekly_path)
    return m


# ── Mock notifier para todos los tests ──────────────────────────────

@pytest.fixture(autouse=True)
def mock_now_et():
    """Parchea _now_et para devolver 2026-04-10 (coincide con sample_plan.fecha)."""
    fake_now = datetime(2026, 4, 10, 9, 30, 0, tzinfo=ET)
    with patch("scripts.mancini.monitor._now_et", return_value=fake_now):
        yield fake_now


@pytest.fixture(autouse=True)
def mock_notifier():
    with patch("scripts.mancini.monitor.notifier") as mock:
        mock.notify_plan_loaded.return_value = True
        mock.notify_breakdown.return_value = True
        mock.notify_signal.return_value = True
        mock.notify_partial_exit.return_value = True
        mock.notify_trade_closed.return_value = True
        mock.notify_session_summary.return_value = True
        yield mock


@pytest.fixture(autouse=True)
def mock_logger():
    with patch("scripts.mancini.monitor.append_trade") as mock:
        yield mock


# ── load_state ──────────────────────────────────────────────────────

def test_load_state_creates_detectors(monitor, sample_plan):
    monitor.load_state()
    assert monitor.plan is not None
    assert monitor.plan.key_level_upper == 6809
    assert len(monitor.detectors) == 2
    assert monitor.detectors[0].level == 6809
    assert monitor.detectors[1].level == 6781


def test_load_state_no_plan(monitor):
    monitor.load_state()
    assert monitor.plan is None
    assert monitor.detectors == []


def test_load_state_restores_existing(monitor, sample_plan, state_path):
    # Pre-guardar detectores con estado
    detectors = [
        FailedBreakdownDetector(level=6809, side="upper", state=State.BREAKDOWN, breakdown_low=6804),
        FailedBreakdownDetector(level=6781, side="lower"),
    ]
    save_detectors(detectors, state_path)

    monitor.load_state()
    assert monitor.detectors[0].state == State.BREAKDOWN
    assert monitor.detectors[0].breakdown_low == 6804


# ── process_tick — secuencia completa ───────────────────────────────

def test_process_tick_no_event(monitor, sample_plan):
    """Precio fuera de rango de breakdown → sin eventos."""
    monitor.load_state()
    events = monitor.process_tick(6790, "2026-04-10T14:00:00Z")
    assert events == []


def test_process_tick_breakdown(monitor, sample_plan, mock_notifier):
    """Precio rompe nivel inferior → BREAKDOWN + alerta."""
    monitor.load_state()
    events = monitor.process_tick(6776, "2026-04-10T14:00:00Z")

    # Debe haber un evento de breakdown para el nivel 6781
    breakdown_events = [e for e in events if "BREAKDOWN" in e["type"]]
    assert len(breakdown_events) == 1
    assert breakdown_events[0]["level"] == 6781

    mock_notifier.notify_breakdown.assert_called_once()


def test_full_failed_breakdown_to_trade(monitor, sample_plan, mock_notifier):
    """Secuencia completa: breakdown → recovery → signal → trade abierto."""
    monitor.load_state()

    # Breakdown en nivel inferior (6781)
    monitor.process_tick(6776, "2026-04-10T14:00:00Z")
    assert monitor.detectors[1].state == State.BREAKDOWN

    # Recovery
    monitor.process_tick(6783, "2026-04-10T14:01:00Z")
    assert monitor.detectors[1].state == State.RECOVERY

    # Aceptacion (3 polls)
    monitor.process_tick(6784, "2026-04-10T14:02:00Z")
    events = monitor.process_tick(6785, "2026-04-10T14:03:00Z")

    # Debe haber signal + trade abierto
    signal_events = [e for e in events if "SIGNAL" in e["type"]]
    assert len(signal_events) == 1

    mock_notifier.notify_signal.assert_called_once()

    # Trade LONG con targets_upper (6819, 6830) — no targets_lower
    trade = monitor.trade_manager.active_trade()
    assert trade is not None
    assert trade.direction == "LONG"
    assert trade.targets == [6819, 6830]  # targets hacia arriba
    assert monitor.detectors[1].state == State.ACTIVE


def test_full_sequence_with_target(monitor, sample_plan, mock_notifier):
    """Secuencia completa hasta target 1 (parcial)."""
    monitor.load_state()

    # Breakdown → Recovery → Signal
    monitor.process_tick(6776, "2026-04-10T14:00:00Z")
    monitor.process_tick(6783, "2026-04-10T14:01:00Z")
    monitor.process_tick(6784, "2026-04-10T14:02:00Z")
    monitor.process_tick(6785, "2026-04-10T14:03:00Z")  # SIGNAL + trade LONG

    # Trade abierto LONG con targets [6819, 6830]
    trade = monitor.trade_manager.active_trade()
    assert trade is not None
    assert trade.targets == [6819, 6830]

    # Precio sube hacia Target 1 (6819)
    monitor.process_tick(6810, "2026-04-10T14:04:00Z")  # sin evento
    events = monitor.process_tick(6819, "2026-04-10T14:05:00Z")  # Target 1!

    partial_events = [e for e in events if e["type"] == "PARTIAL_EXIT"]
    assert len(partial_events) == 1
    assert partial_events[0]["pnl_partial_pts"] == 34  # 6819 - 6785

    # Trade ahora en PARTIAL con stop a breakeven
    trade = monitor.trade_manager.active_trade()
    assert trade.status == TradeStatus.PARTIAL
    assert trade.runner_stop == 6785  # breakeven


def test_state_persistence(monitor, sample_plan, state_path):
    """Estado se persiste correctamente tras process_tick."""
    monitor.load_state()
    monitor.process_tick(6776, "2026-04-10T14:00:00Z")
    monitor.save_state()

    assert state_path.exists()
    data = json.loads(state_path.read_text(encoding="utf-8"))
    detectors = data["detectors"]
    lower = [d for d in detectors if d["side"] == "lower"][0]
    assert lower["state"] == "BREAKDOWN"


def test_plan_update_detection(monitor, sample_plan, plan_path):
    """Monitor detecta cuando el plan cambia en disco."""
    monitor.load_state()
    old_targets = list(monitor.plan.targets_upper)

    # Simular que el scan de tweets actualizo el plan
    import time
    time.sleep(0.1)  # Asegurar mtime diferente
    updated_plan = DailyPlan(
        fecha="2026-04-10",
        key_level_upper=6809,
        targets_upper=[6819, 6830, 6846],
        key_level_lower=6781,
        targets_lower=[6766],
    )
    save_plan(updated_plan, plan_path)

    monitor._check_plan_updates()
    assert 6846 in monitor.plan.targets_upper


# ── close_session ───────────────────────────────────────────────────

def test_close_session_no_trades(monitor, sample_plan, mock_notifier):
    """Cierre de sesion sin trades → resumen con 0 trades."""
    monitor.load_state()
    monitor.close_session()

    mock_notifier.notify_session_summary.assert_called_once()
    call_args = mock_notifier.notify_session_summary.call_args[0]
    assert call_args[1] == 0  # trades_count
    assert call_args[2] == 0  # total_pnl


def test_close_session_expires_detectors(monitor, sample_plan):
    """Cierre de sesion expira detectores activos."""
    monitor.load_state()
    monitor.close_session()

    for d in monitor.detectors:
        assert d.state == State.EXPIRED


# ── Weekly alignment ──────────────────────────────────────────────────

def test_calc_weekly_bias_bullish(monitor, weekly_path):
    """Plan semanal con notes alcista → BULLISH."""
    weekly = DailyPlan(
        fecha="2026-04-14",
        key_level_upper=6817,
        targets_upper=[6903, 6950],
        key_level_lower=6793,
        targets_lower=[],
        notes="Sesgo: alcista. Bull flag breakout.",
    )
    save_weekly(weekly, weekly_path)
    monitor.weekly = weekly
    assert monitor.calc_weekly_bias() == "BULLISH"


def test_calc_weekly_bias_bearish(monitor, weekly_path):
    """Plan semanal bajista → BEARISH."""
    weekly = DailyPlan(
        fecha="2026-04-14",
        key_level_upper=6800,
        targets_upper=[],
        key_level_lower=6750,
        targets_lower=[6700, 6650],
        notes="Sesgo: bajista. Breakdown confirmado.",
    )
    save_weekly(weekly, weekly_path)
    monitor.weekly = weekly
    assert monitor.calc_weekly_bias() == "BEARISH"


def test_calc_weekly_bias_neutral_no_weekly(monitor):
    """Sin plan semanal → NEUTRAL."""
    assert monitor.calc_weekly_bias() == "NEUTRAL"


def test_calc_weekly_bias_fallback_targets(monitor):
    """Sin palabra clave pero targets solo alcistas → BULLISH."""
    monitor.weekly = DailyPlan(
        fecha="2026-04-14",
        key_level_upper=6817,
        targets_upper=[6903],
        key_level_lower=6793,
        targets_lower=[],
        notes="Plan para la semana.",
    )
    assert monitor.calc_weekly_bias() == "BULLISH"


def test_calc_alignment_aligned(monitor):
    """LONG con sesgo BULLISH → ALIGNED."""
    monitor.weekly = DailyPlan(
        fecha="2026-04-14", key_level_upper=6817, targets_upper=[6903],
        key_level_lower=6793, targets_lower=[],
        notes="Sesgo: alcista",
    )
    assert monitor.calc_alignment("LONG") == "ALIGNED"


def test_calc_alignment_misaligned(monitor):
    """SHORT con sesgo BULLISH → MISALIGNED."""
    monitor.weekly = DailyPlan(
        fecha="2026-04-14", key_level_upper=6817, targets_upper=[6903],
        key_level_lower=6793, targets_lower=[],
        notes="Sesgo: alcista",
    )
    assert monitor.calc_alignment("SHORT") == "MISALIGNED"


def test_calc_alignment_neutral(monitor):
    """Sin weekly → NEUTRAL."""
    assert monitor.calc_alignment("LONG") == "NEUTRAL"


def test_misaligned_trade_only_t1(monitor, sample_plan, mock_notifier, weekly_path):
    """Trade MISALIGNED solo tiene Target 1 (sin runner)."""
    # Weekly bajista → LONG será MISALIGNED
    weekly = DailyPlan(
        fecha="2026-04-14", key_level_upper=6800, targets_upper=[],
        key_level_lower=6750, targets_lower=[6700],
        notes="Sesgo: bajista",
    )
    save_weekly(weekly, weekly_path)
    monitor.load_state()

    # Secuencia: breakdown → recovery → signal
    monitor.process_tick(6776, "2026-04-10T14:00:00Z")
    monitor.process_tick(6783, "2026-04-10T14:01:00Z")
    monitor.process_tick(6784, "2026-04-10T14:02:00Z")
    monitor.process_tick(6785, "2026-04-10T14:03:00Z")

    trade = monitor.trade_manager.active_trade()
    assert trade is not None
    assert trade.alignment == "MISALIGNED"
    assert len(trade.targets) == 1  # Solo T1, sin runner


def test_aligned_trade_extended_targets(monitor, sample_plan, mock_notifier, weekly_path):
    """Trade ALIGNED enriquece targets con weekly."""
    # Weekly alcista con target 6950 (mayor que daily 6830)
    weekly = DailyPlan(
        fecha="2026-04-14", key_level_upper=6817,
        targets_upper=[6903, 6950],
        key_level_lower=6793, targets_lower=[],
        notes="Sesgo: alcista",
    )
    save_weekly(weekly, weekly_path)
    monitor.load_state()

    # Secuencia: breakdown → recovery → signal
    monitor.process_tick(6776, "2026-04-10T14:00:00Z")
    monitor.process_tick(6783, "2026-04-10T14:01:00Z")
    monitor.process_tick(6784, "2026-04-10T14:02:00Z")
    monitor.process_tick(6785, "2026-04-10T14:03:00Z")

    trade = monitor.trade_manager.active_trade()
    assert trade is not None
    assert trade.alignment == "ALIGNED"
    # Daily targets [6819, 6830] + weekly [6903] (primer target > 6830)
    assert 6903 in trade.targets
    assert trade.targets == [6819, 6830, 6903]


def test_alignment_in_notification(monitor, sample_plan, mock_notifier, weekly_path):
    """Notificación incluye alignment."""
    weekly = DailyPlan(
        fecha="2026-04-14", key_level_upper=6817, targets_upper=[6903],
        key_level_lower=6793, targets_lower=[],
        notes="Sesgo: alcista",
    )
    save_weekly(weekly, weekly_path)
    monitor.load_state()

    # Secuencia completa hasta SIGNAL
    monitor.process_tick(6776, "2026-04-10T14:00:00Z")
    monitor.process_tick(6783, "2026-04-10T14:01:00Z")
    monitor.process_tick(6784, "2026-04-10T14:02:00Z")
    monitor.process_tick(6785, "2026-04-10T14:03:00Z")

    # Verificar que notify_signal recibió alignment
    mock_notifier.notify_signal.assert_called_once()
    call_kwargs = mock_notifier.notify_signal.call_args
    assert call_kwargs.kwargs.get("alignment") == "ALIGNED" or \
           (len(call_kwargs.args) > 6 and call_kwargs.args[6] == "ALIGNED")


# ── Date validation ────────────────────────────────────────────────

def test_load_state_stale_plan_discarded(plan_path, state_path, weekly_path):
    """Plan con fecha distinta a hoy se descarta."""
    # Plan de ayer
    plan = DailyPlan(
        fecha="2026-04-09",
        key_level_upper=6809,
        targets_upper=[6819, 6830],
        key_level_lower=6781,
        targets_lower=[6766],
    )
    save_plan(plan, plan_path)

    # _now_et devuelve 2026-04-10 (mock_now_et fixture)
    m = ManciniMonitor(client=None, plan_path=plan_path, state_path=state_path,
                       weekly_path=weekly_path)
    m.load_state()
    assert m.plan is None
    assert m.detectors == []


def test_check_plan_updates_rejects_stale(monitor, sample_plan, plan_path):
    """_check_plan_updates descarta plan recargado con fecha incorrecta."""
    monitor.load_state()
    assert monitor.plan is not None  # Plan de hoy (2026-04-10)

    # Simular que alguien escribe un plan con fecha de ayer
    import time
    time.sleep(0.1)
    stale_plan = DailyPlan(
        fecha="2026-04-09",
        key_level_upper=6800,
        targets_upper=[6810],
        key_level_lower=6770,
        targets_lower=[6760],
    )
    save_plan(stale_plan, plan_path)

    monitor._check_plan_updates()
    # Debe mantener el plan original, no el stale
    assert monitor.plan.fecha == "2026-04-10"
