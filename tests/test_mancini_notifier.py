"""Tests para scripts/mancini/notifier.py — Alertas Telegram Mancini."""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from scripts.mancini import notifier


@pytest.fixture(autouse=True)
def mock_telegram():
    """Mock send_telegram para no hacer llamadas reales."""
    with patch.object(notifier, "send_telegram", return_value=True) as mock:
        yield mock


def test_notify_plan_loaded(mock_telegram):
    plan = {
        "fecha": "2026-04-10",
        "key_level_upper": 6809,
        "targets_upper": [6819, 6830],
        "key_level_lower": 6781,
        "targets_lower": [6766],
        "chop_zone": (6788, 6830),
    }
    result = notifier.notify_plan_loaded(plan)
    assert result is True
    mock_telegram.assert_called_once()
    msg = mock_telegram.call_args[0][0]
    assert "Mancini Plan" in msg
    assert "6809" in msg
    assert "6781" in msg
    assert "6819" in msg
    assert "Chop zone" in msg


def test_notify_plan_loaded_no_chop(mock_telegram):
    plan = {
        "fecha": "2026-04-10",
        "key_level_upper": 6809,
        "targets_upper": [6819],
        "key_level_lower": 6781,
        "targets_lower": [6766],
        "chop_zone": None,
    }
    result = notifier.notify_plan_loaded(plan)
    assert result is True
    msg = mock_telegram.call_args[0][0]
    assert "Chop zone" not in msg


def test_notify_breakdown(mock_telegram):
    result = notifier.notify_breakdown(6781, 6776, 5.0)
    assert result is True
    msg = mock_telegram.call_args[0][0]
    assert "Breakdown" in msg
    assert "6781" in msg
    assert "6776" in msg


def test_notify_signal(mock_telegram):
    result = notifier.notify_signal(
        level=6781, price=6783, entry=6783,
        stop=6772, targets=[6793, 6809],
        breakdown_low=6774,
    )
    assert result is True
    msg = mock_telegram.call_args[0][0]
    assert "FAILED BREAKDOWN" in msg
    assert "6783" in msg
    assert "6772" in msg
    assert "6793" in msg


def test_notify_partial_exit(mock_telegram):
    result = notifier.notify_partial_exit(6793, 10, 6783)
    assert result is True
    msg = mock_telegram.call_args[0][0]
    assert "Target 1" in msg
    assert "10" in msg
    assert "breakeven" in msg


def test_notify_trade_closed(mock_telegram):
    result = notifier.notify_trade_closed(
        reason="TARGET_2", entry=6783, exit_price=6809,
        pnl_total=18.0, pnl_partial=10, pnl_runner=26,
    )
    assert result is True
    msg = mock_telegram.call_args[0][0]
    assert "Trade cerrado" in msg
    assert "TARGET" in msg
    assert "18" in msg


def test_notify_trade_closed_stop(mock_telegram):
    result = notifier.notify_trade_closed(
        reason="STOP", entry=6783, exit_price=6771,
        pnl_total=-12.0,
    )
    assert result is True
    msg = mock_telegram.call_args[0][0]
    assert "STOP" in msg
    assert "12" in msg


def test_notify_session_summary(mock_telegram):
    result = notifier.notify_session_summary("2026-04-10", 2, 15.5)
    assert result is True
    msg = mock_telegram.call_args[0][0]
    assert "Resumen" in msg
    assert "2026\\-04\\-10" in msg
    assert "15" in msg


def test_notify_session_summary_negative(mock_telegram):
    result = notifier.notify_session_summary("2026-04-10", 1, -8.0)
    assert result is True
    msg = mock_telegram.call_args[0][0]
    assert "8" in msg


def test_notify_weekly_plan(mock_telegram):
    result = notifier.notify_weekly_plan({
        "fecha": "2026-04-14",
        "key_level_upper": 6817,
        "key_level_lower": 6793,
        "targets_upper": [6903, 6950, 7068],
        "notes": "Sesgo: alcista",
    })
    assert result is True
    msg = mock_telegram.call_args[0][0]
    assert "Big Picture" in msg
    assert "6817" in msg
    assert "6793" in msg
    assert "6903" in msg
    assert "alcista" in msg


def test_notify_weekly_plan_no_targets(mock_telegram):
    result = notifier.notify_weekly_plan({
        "fecha": "2026-04-14",
        "key_level_upper": 6817,
        "key_level_lower": 6793,
        "targets_upper": [],
        "notes": "",
    })
    assert result is True
    msg = mock_telegram.call_args[0][0]
    assert "Big Picture" in msg
