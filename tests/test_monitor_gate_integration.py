"""Tests de integración: Execution Gate + Monitor + OrderExecutor."""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from scripts.mancini.config import DailyPlan, save_plan
from scripts.mancini.execution_gate import GateDecision
from scripts.mancini.monitor import ManciniMonitor, ET
from scripts.mancini.order_executor import OrderResult
from scripts.mancini.trade_manager import TradeStatus

TS_BASE = "2026-04-10T14:"


@pytest.fixture
def plan_path(tmp_path):
    return tmp_path / "plan.json"


@pytest.fixture
def state_path(tmp_path):
    return tmp_path / "state.json"


@pytest.fixture
def weekly_path(tmp_path):
    return tmp_path / "weekly.json"


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
def mock_executor():
    executor = MagicMock()
    executor.place_entry.return_value = OrderResult(
        success=True, order_id="entry-001", dry_run=True, details={}, error=None
    )
    executor.place_stop.return_value = OrderResult(
        success=True, order_id="stop-001", dry_run=True, details={}, error=None
    )
    executor.update_stop.return_value = OrderResult(
        success=True, order_id="stop-001", dry_run=False, details={}, error=None
    )
    return executor


@pytest.fixture(autouse=True)
def mock_now_et():
    fake_now = datetime(2026, 4, 10, 9, 30, 0, tzinfo=ET)
    with patch("scripts.mancini.monitor._now_et", return_value=fake_now):
        yield fake_now


@pytest.fixture(autouse=True)
def mock_notifier():
    with patch("scripts.mancini.monitor.notifier") as mock:
        for attr in ["notify_plan_loaded", "notify_breakdown", "notify_signal",
                      "notify_trade_closed", "notify_target_hit",
                      "notify_gate_approved", "notify_trade_rejected",
                      "notify_session_summary"]:
            getattr(mock, attr).return_value = True
        yield mock


@pytest.fixture(autouse=True)
def mock_loggers():
    with patch("scripts.mancini.monitor.append_trade"), \
         patch("scripts.mancini.monitor.append_gate_decision"):
        yield


def _trigger_signal(monitor):
    """Helper: dispara breakdown → recovery → signal en nivel inferior (6781)."""
    monitor.process_tick(6776, f"{TS_BASE}00:00Z")
    monitor.process_tick(6783, f"{TS_BASE}01:00Z")
    monitor.process_tick(6784, f"{TS_BASE}02:00Z")
    events = monitor.process_tick(6785, f"{TS_BASE}03:00Z")
    return events


# ── Gate approved → trade + orders ────────────────────────────────────

@patch("scripts.mancini.execution_gate.anthropic")
def test_signal_with_gate_approved(mock_anthropic, plan_path, state_path,
                                    weekly_path, sample_plan, mock_executor):
    """Gate aprueba → trade abierto + órdenes lanzadas."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps({
        "execute": True,
        "reasoning": "Primer trade, buenas condiciones",
        "risk_factors": [],
    }))]
    mock_anthropic.Anthropic.return_value.messages.create.return_value = mock_response

    monitor = ManciniMonitor(
        client=None, plan_path=plan_path, state_path=state_path,
        weekly_path=weekly_path, gate_enabled=True,
        order_executor=mock_executor, es_symbol="/ESM6:XCME",
    )
    monitor.load_state()

    _trigger_signal(monitor)

    trade = monitor.trade_manager.active_trade()
    assert trade is not None
    assert trade.execution_mode == "auto"
    assert trade.entry_order_id == "entry-001"
    assert trade.stop_order_id == "stop-001"

    mock_executor.place_entry.assert_called_once_with("LONG", "/ESM6:XCME")
    mock_executor.place_stop.assert_called_once()


# ── Gate rejected + trader confirms ──────────────────────────────────

@patch("scripts.mancini.telegram_confirm.ask_trader_confirmation", return_value=True)
@patch("scripts.mancini.execution_gate.anthropic")
def test_signal_gate_rejected_trader_confirms(mock_anthropic, mock_confirm,
                                               plan_path, state_path, weekly_path,
                                               sample_plan, mock_executor):
    """Gate rechaza, trader confirma via Telegram → trade abierto."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps({
        "execute": False,
        "reasoning": "Poco tiempo",
        "risk_factors": ["poco tiempo"],
    }))]
    mock_anthropic.Anthropic.return_value.messages.create.return_value = mock_response

    monitor = ManciniMonitor(
        client=None, plan_path=plan_path, state_path=state_path,
        weekly_path=weekly_path, gate_enabled=True,
        order_executor=mock_executor, es_symbol="/ESM6:XCME",
    )
    monitor.load_state()

    _trigger_signal(monitor)

    trade = monitor.trade_manager.active_trade()
    assert trade is not None
    assert trade.execution_mode == "manual_confirm"
    mock_confirm.assert_called_once()


# ── Gate rejected + trader declines ──────────────────────────────────

@patch("scripts.mancini.telegram_confirm.ask_trader_confirmation", return_value=False)
@patch("scripts.mancini.execution_gate.anthropic")
def test_signal_gate_rejected_trader_declines(mock_anthropic, mock_confirm,
                                               plan_path, state_path, weekly_path,
                                               sample_plan, mock_notifier):
    """Gate rechaza, trader dice no → trade descartado."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps({
        "execute": False,
        "reasoning": "Riesgo alto",
        "risk_factors": ["riesgo alto"],
    }))]
    mock_anthropic.Anthropic.return_value.messages.create.return_value = mock_response

    monitor = ManciniMonitor(
        client=None, plan_path=plan_path, state_path=state_path,
        weekly_path=weekly_path, gate_enabled=True,
    )
    monitor.load_state()

    _trigger_signal(monitor)

    assert monitor.trade_manager.active_trade() is None
    mock_notifier.notify_trade_rejected.assert_called_once()


# ── Gate rejected + timeout ──────────────────────────────────────────

@patch("scripts.mancini.telegram_confirm.ask_trader_confirmation", return_value=None)
@patch("scripts.mancini.execution_gate.anthropic")
def test_signal_gate_rejected_timeout(mock_anthropic, mock_confirm,
                                       plan_path, state_path, weekly_path,
                                       sample_plan, mock_notifier):
    """Gate rechaza, timeout → trade descartado."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps({
        "execute": False,
        "reasoning": "Duda",
        "risk_factors": [],
    }))]
    mock_anthropic.Anthropic.return_value.messages.create.return_value = mock_response

    monitor = ManciniMonitor(
        client=None, plan_path=plan_path, state_path=state_path,
        weekly_path=weekly_path, gate_enabled=True,
    )
    monitor.load_state()

    _trigger_signal(monitor)

    assert monitor.trade_manager.active_trade() is None


# ── Gate disabled → ejecución directa ────────────────────────────────

def test_signal_without_gate(plan_path, state_path, weekly_path,
                              sample_plan, mock_executor):
    """gate_enabled=False → ejecución directa sin consultar LLM."""
    monitor = ManciniMonitor(
        client=None, plan_path=plan_path, state_path=state_path,
        weekly_path=weekly_path, gate_enabled=False,
        order_executor=mock_executor, es_symbol="/ESM6:XCME",
    )
    monitor.load_state()

    _trigger_signal(monitor)

    trade = monitor.trade_manager.active_trade()
    assert trade is not None
    mock_executor.place_entry.assert_called_once()


# ── Sin executor → funciona como antes ────────────────────────────────

def test_no_executor_works_as_before(plan_path, state_path, weekly_path,
                                      sample_plan):
    """Sin OrderExecutor → comportamiento actual (solo tracking local)."""
    monitor = ManciniMonitor(
        client=None, plan_path=plan_path, state_path=state_path,
        weekly_path=weekly_path, gate_enabled=False,
    )
    monitor.load_state()

    _trigger_signal(monitor)

    trade = monitor.trade_manager.active_trade()
    assert trade is not None
    assert trade.entry_order_id is None
    assert trade.stop_order_id is None


# ── Trailing stop actualiza TastyTrade ────────────────────────────────

def test_trailing_stop_syncs_with_tastytrade(plan_path, state_path, weekly_path,
                                              sample_plan, mock_executor):
    """TARGET_HIT → update_stop en TastyTrade."""
    monitor = ManciniMonitor(
        client=None, plan_path=plan_path, state_path=state_path,
        weekly_path=weekly_path, gate_enabled=False,
        order_executor=mock_executor, es_symbol="/ESM6:XCME",
    )
    monitor.load_state()

    _trigger_signal(monitor)

    trade = monitor.trade_manager.active_trade()
    assert trade is not None
    assert trade.stop_order_id == "stop-001"

    # Precio sube a T1 (6819)
    events = monitor.process_tick(6819, f"{TS_BASE}04:00Z")
    target_events = [e for e in events if e["type"] == "TARGET_HIT"]
    assert len(target_events) == 1

    # update_stop llamado con breakeven
    mock_executor.update_stop.assert_called_once_with("stop-001", trade.entry_price)


# ── Runner sobrevive cierre de sesión ────────────────────────────────

def test_runner_survives_eod(plan_path, state_path, weekly_path,
                              sample_plan, mock_notifier):
    """Trade activo NO se cierra al finalizar sesión."""
    monitor = ManciniMonitor(
        client=None, plan_path=plan_path, state_path=state_path,
        weekly_path=weekly_path, gate_enabled=False,
    )
    monitor.load_state()

    _trigger_signal(monitor)
    trade = monitor.trade_manager.active_trade()
    assert trade is not None

    # Cerrar sesión
    monitor.close_session()

    # Trade sigue abierto
    assert monitor.trade_manager.active_trade() is not None
    assert trade.status == TradeStatus.OPEN
