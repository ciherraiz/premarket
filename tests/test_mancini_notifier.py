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


def test_notify_plan_loaded_from_scan(mock_telegram):
    """Llamada desde scan (sin session params) → sin línea Monitor activo."""
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
    assert "Monitor activo" not in msg


def test_notify_plan_loaded_from_monitor(mock_telegram):
    """Llamada desde monitor (con session params) → línea Monitor activo dinámica."""
    plan = {
        "fecha": "2026-04-10",
        "key_level_upper": 6809,
        "targets_upper": [6819, 6830],
        "key_level_lower": 6781,
        "targets_lower": [6766],
        "chop_zone": None,
    }
    result = notifier.notify_plan_loaded(plan, session_start=7, session_end=16)
    assert result is True
    msg = mock_telegram.call_args[0][0]
    assert "Mancini Plan" in msg
    assert "Monitor activo 07:00" in msg
    assert "16:00 ET" in msg


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


def test_notify_plan_loaded_standby_context(mock_telegram):
    """Precio lejos del nivel muestra mensaje de standby."""
    plan = {
        "fecha": "2026-04-22",
        "key_level_upper": 7135,
        "targets_upper": [7153, 7165, 7180],
        "key_level_lower": 7120,
        "targets_lower": [],
        "chop_zone": None,
        "notes": "",
    }
    result = notifier.notify_plan_loaded(plan, price=7151.0)
    assert result is True
    msg = mock_telegram.call_args[0][0]
    assert "7151" in msg
    assert "standby" in msg.lower()
    assert "+31" in msg


def test_notify_plan_loaded_alert_zone_context(mock_telegram):
    """Precio cerca del nivel muestra mensaje de alerta."""
    plan = {
        "fecha": "2026-04-22",
        "key_level_upper": 7135,
        "targets_upper": [7153],
        "key_level_lower": 7120,
        "targets_lower": [],
        "chop_zone": None,
        "notes": "",
    }
    result = notifier.notify_plan_loaded(plan, price=7124.0)
    assert result is True
    msg = mock_telegram.call_args[0][0]
    assert "alerta" in msg.lower()
    assert "+4" in msg


def test_notify_plan_loaded_no_price_no_context_line(mock_telegram):
    """Sin precio no aparece línea de contexto."""
    plan = {
        "fecha": "2026-04-22",
        "key_level_upper": 7135,
        "targets_upper": [7153],
        "key_level_lower": 7120,
        "targets_lower": [],
        "chop_zone": None,
        "notes": "",
    }
    result = notifier.notify_plan_loaded(plan)
    assert result is True
    msg = mock_telegram.call_args[0][0]
    assert "standby" not in msg.lower()
    assert "alerta" not in msg.lower()


def test_notify_plan_loaded_notes_shown(mock_telegram):
    """Las notas aparecen en el mensaje cuando no están vacías."""
    plan = {
        "fecha": "2026-04-22",
        "key_level_upper": 7135,
        "targets_upper": [7153],
        "key_level_lower": 7120,
        "targets_lower": [],
        "chop_zone": None,
        "notes": "contexto importante del día",
    }
    result = notifier.notify_plan_loaded(plan)
    assert result is True
    msg = mock_telegram.call_args[0][0]
    assert "contexto importante" in msg


def test_notify_plan_loaded_no_notes_no_notes_line(mock_telegram):
    """Sin notas no aparece la línea de notas."""
    plan = {
        "fecha": "2026-04-22",
        "key_level_upper": 7135,
        "targets_upper": [7153],
        "key_level_lower": 7120,
        "targets_lower": [],
        "chop_zone": None,
        "notes": "",
    }
    result = notifier.notify_plan_loaded(plan)
    assert result is True
    msg = mock_telegram.call_args[0][0]
    assert "💬" not in msg


def test_notify_approaching_level(mock_telegram):
    """Alerta de zona de alerta incluye nivel y distancia."""
    result = notifier.notify_approaching_level(7120.0, 7124.0, 4.0)
    assert result is True
    msg = mock_telegram.call_args[0][0]
    assert "7120" in msg
    assert "7124" in msg
    assert "alerta" in msg.lower()


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


def test_notify_target_hit(mock_telegram):
    result = notifier.notify_target_hit({
        "target_index": 0, "target_price": 6793,
        "price": 6794, "new_stop": 6783, "old_stop": 6772,
    })
    assert result is True
    msg = mock_telegram.call_args[0][0]
    assert "Target 1" in msg
    assert "6793" in msg
    assert "6783" in msg


def test_notify_trade_closed(mock_telegram):
    result = notifier.notify_trade_closed(
        reason="STOP", entry=6783, exit_price=6771,
        pnl_total=-12.0,
    )
    assert result is True
    msg = mock_telegram.call_args[0][0]
    assert "Trade cerrado" in msg
    assert "STOP" in msg
    assert "12" in msg


def test_notify_gate_approved(mock_telegram):
    from scripts.mancini.execution_gate import GateDecision
    decision = GateDecision(execute=True, reasoning="Condiciones favorables")
    result = notifier.notify_gate_approved(decision, 6781, 6785, 6772, [6793], "ALIGNED")
    assert result is True
    msg = mock_telegram.call_args[0][0]
    assert "APROBADO" in msg
    assert "6781" in msg


def test_notify_trade_rejected(mock_telegram):
    from scripts.mancini.execution_gate import GateDecision
    decision = GateDecision(execute=False, reasoning="Riesgo alto", risk_factors=["riesgo"])
    result = notifier.notify_trade_rejected(decision)
    assert result is True
    msg = mock_telegram.call_args[0][0]
    assert "descartado" in msg


def test_notify_trade_rejected_none(mock_telegram):
    result = notifier.notify_trade_rejected(None)
    assert result is False


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
