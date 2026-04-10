"""Tests para scripts/mancini/monitor.py — Monitor /ES con detectores y trades."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from scripts.mancini.config import DailyPlan, save_plan
from scripts.mancini.detector import State, save_detectors, FailedBreakdownDetector
from scripts.mancini.trade_manager import TradeStatus
from scripts.mancini.monitor import ManciniMonitor


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
def monitor(plan_path, state_path):
    """Monitor sin client (para tests sin TastyTrade)."""
    m = ManciniMonitor(client=None, plan_path=plan_path, state_path=state_path)
    return m


# ── Mock notifier para todos los tests ──────────────────────────────

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
