"""Tests para scripts/mancini/telegram_confirm.py — Confirmación interactiva."""

import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from scripts.mancini.telegram_confirm import ask_trader_confirmation


@pytest.fixture(autouse=True)
def mock_env():
    with patch.dict(os.environ, {
        "TELEGRAM_BOT_TOKEN": "test-token",
        "TELEGRAM_CHAT_ID": "12345",
    }):
        yield


# ── ask_trader_confirmation ──────────────────────────────────────────

@patch("scripts.mancini.telegram_confirm.httpx")
def test_confirmation_yes(mock_httpx):
    """Trader pulsa 'Ejecutar' → True."""
    # sendMessage response
    send_response = MagicMock()
    send_response.json.return_value = {"ok": True, "result": {"message_id": 42}}

    # getUpdates con callback exec_yes
    updates_response = MagicMock()
    updates_response.json.return_value = {
        "result": [{
            "update_id": 1,
            "callback_query": {
                "id": "cb-1",
                "message": {"message_id": 42},
                "data": "exec_yes",
            },
        }]
    }

    # answerCallbackQuery / editMessageText
    ack_response = MagicMock()
    ack_response.json.return_value = {"ok": True}

    # Configurar side_effects en orden de llamada
    mock_httpx.post.side_effect = [
        send_response,      # sendMessage
        updates_response,   # getUpdates
        ack_response,       # answerCallbackQuery
        ack_response,       # editMessageText
    ]

    result = ask_trader_confirmation(
        signal_info="📍 Nivel: 6781",
        risk_factors=["poco tiempo"],
        reasoning="Solo 20 min",
        timeout_seconds=5,
    )
    assert result is True


@patch("scripts.mancini.telegram_confirm.httpx")
def test_confirmation_no(mock_httpx):
    """Trader pulsa 'Descartar' → False."""
    send_response = MagicMock()
    send_response.json.return_value = {"ok": True, "result": {"message_id": 42}}

    updates_response = MagicMock()
    updates_response.json.return_value = {
        "result": [{
            "update_id": 1,
            "callback_query": {
                "id": "cb-1",
                "message": {"message_id": 42},
                "data": "exec_no",
            },
        }]
    }

    ack_response = MagicMock()
    ack_response.json.return_value = {"ok": True}

    mock_httpx.post.side_effect = [
        send_response, updates_response, ack_response, ack_response,
    ]

    result = ask_trader_confirmation(
        signal_info="test", risk_factors=[], reasoning="test",
        timeout_seconds=5,
    )
    assert result is False


@patch("scripts.mancini.telegram_confirm.time")
@patch("scripts.mancini.telegram_confirm.httpx")
def test_confirmation_timeout(mock_httpx, mock_time):
    """Sin respuesta dentro del timeout → None."""
    send_response = MagicMock()
    send_response.json.return_value = {"ok": True, "result": {"message_id": 42}}

    # getUpdates vacío
    empty_updates = MagicMock()
    empty_updates.json.return_value = {"result": []}

    edit_response = MagicMock()
    edit_response.json.return_value = {"ok": True}

    mock_httpx.post.side_effect = [
        send_response,    # sendMessage
        empty_updates,    # getUpdates (vacío)
        edit_response,    # editMessageText (timeout)
    ]

    # Simular que el tiempo ya pasó
    mock_time.time.side_effect = [0, 200, 200]  # deadline=120, now>deadline

    result = ask_trader_confirmation(
        signal_info="test", risk_factors=[], reasoning="test",
        timeout_seconds=120,
    )
    assert result is None


@patch("scripts.mancini.telegram_confirm.httpx")
def test_message_includes_risk_factors(mock_httpx):
    """Mensaje enviado incluye los factores de riesgo."""
    send_response = MagicMock()
    send_response.json.return_value = {"ok": True, "result": {"message_id": 42}}

    updates_response = MagicMock()
    updates_response.json.return_value = {
        "result": [{
            "update_id": 1,
            "callback_query": {
                "id": "cb-1",
                "message": {"message_id": 42},
                "data": "exec_yes",
            },
        }]
    }

    ack_response = MagicMock()

    mock_httpx.post.side_effect = [
        send_response, updates_response, ack_response, ack_response,
    ]

    ask_trader_confirmation(
        signal_info="📍 Nivel: 6781",
        risk_factors=["poco tiempo", "contra sesgo"],
        reasoning="Riesgo",
        timeout_seconds=5,
    )

    # Verificar que sendMessage incluyó los factores
    send_call = mock_httpx.post.call_args_list[0]
    sent_text = send_call.kwargs.get("json", send_call[1].get("json", {})).get("text", "")
    assert "poco tiempo" in sent_text
    assert "contra sesgo" in sent_text


def test_no_credentials_returns_none():
    """Sin credenciales Telegram → None."""
    with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""}):
        result = ask_trader_confirmation("test", [], "test")
        assert result is None
