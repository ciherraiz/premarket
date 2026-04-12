"""Tests para scripts/mancini/tweet_parser.py"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from scripts.mancini.tweet_parser import (
    parse_tweets_to_plan,
    parse_weekly_tweets,
    _build_user_message,
    _parse_response,
)


# ── _build_user_message ───────────────────────────────────────────────

def test_build_user_message_format():
    tweets = [
        {"text": "Plan today: 6809 reclaims", "created_at": "2026-04-10T09:00:00"},
        {"text": "Vol dead", "created_at": "2026-04-10T08:00:00"},
    ]
    msg = _build_user_message(tweets)
    assert "1." in msg
    assert "2." in msg
    assert "Plan today: 6809 reclaims" in msg
    assert "Vol dead" in msg
    assert "@AdamMancini4" in msg


def test_build_user_message_empty():
    msg = _build_user_message([])
    assert "@AdamMancini4" in msg


# ── _parse_response ───────────────────────────────────────────────────

def test_parse_response_full_plan():
    """Parsea respuesta JSON con plan completo."""
    response = json.dumps({
        "key_level_upper": 6809,
        "targets_upper": [6819, 6830],
        "key_level_lower": 6781,
        "targets_lower": [6766],
        "chop_zone": [6788, 6830],
        "notes": "Plan del día",
    })
    plan = _parse_response(response, "2026-04-10", ["tweet 1"])
    assert plan is not None
    assert plan.fecha == "2026-04-10"
    assert plan.key_level_upper == 6809
    assert plan.targets_upper == [6819, 6830]
    assert plan.key_level_lower == 6781
    assert plan.targets_lower == [6766]
    assert plan.chop_zone == (6788, 6830)
    assert plan.notes == "Plan del día"
    assert plan.raw_tweets == ["tweet 1"]


def test_parse_response_no_chop_zone():
    """chop_zone null → None."""
    response = json.dumps({
        "key_level_upper": 6809,
        "targets_upper": [6819],
        "key_level_lower": 6781,
        "targets_lower": [6766],
        "chop_zone": None,
        "notes": "",
    })
    plan = _parse_response(response, "2026-04-10", [])
    assert plan is not None
    assert plan.chop_zone is None


def test_parse_response_no_plan():
    """Niveles null → retorna None (no hay plan)."""
    response = json.dumps({
        "key_level_upper": None,
        "targets_upper": [],
        "key_level_lower": None,
        "targets_lower": [],
        "chop_zone": None,
        "notes": "0 volatilidad, sin plan hoy",
    })
    plan = _parse_response(response, "2026-04-10", [])
    assert plan is None


def test_parse_response_with_markdown_fences():
    """Limpia fences de markdown si Haiku los incluye."""
    response = '```json\n{"key_level_upper": 6809, "targets_upper": [6819], "key_level_lower": 6781, "targets_lower": [6766], "chop_zone": null, "notes": ""}\n```'
    plan = _parse_response(response, "2026-04-10", [])
    assert plan is not None
    assert plan.key_level_upper == 6809


def test_parse_response_invalid_json():
    """JSON inválido lanza ValueError."""
    with pytest.raises(ValueError, match="JSON inválido"):
        _parse_response("esto no es json", "2026-04-10", [])


def test_parse_response_raw_tweets_preserved():
    """raw_tweets se preservan correctamente."""
    response = json.dumps({
        "key_level_upper": 6809,
        "targets_upper": [6819],
        "key_level_lower": 6781,
        "targets_lower": [6766],
        "chop_zone": None,
        "notes": "",
    })
    tweets = ["tweet A", "tweet B"]
    plan = _parse_response(response, "2026-04-10", tweets)
    assert plan.raw_tweets == ["tweet A", "tweet B"]


# ── parse_tweets_to_plan (integración con mock) ──────────────────────

def test_parse_tweets_to_plan_calls_haiku(monkeypatch):
    """Verifica que llama a Anthropic con el modelo y prompt correcto."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-123")

    haiku_response = json.dumps({
        "key_level_upper": 6848,
        "targets_upper": [6882, 6900, 6922],
        "key_level_lower": 6809,
        "targets_lower": [6793],
        "chop_zone": [6848, 6872],
        "notes": "Bull flag 6848-6872",
    })

    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text=haiku_response)]

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_msg

    with patch("scripts.mancini.tweet_parser.Anthropic", return_value=mock_client):
        tweets = [
            {"text": "6848-6872=bull flag. Targets 6882, 6900, 6922",
             "created_at": "2026-04-10T09:30:00"},
        ]
        plan = parse_tweets_to_plan(tweets, "2026-04-10")

    assert plan is not None
    assert plan.key_level_upper == 6848
    assert plan.targets_upper == [6882, 6900, 6922]
    assert plan.chop_zone == (6848, 6872)

    # Verifica que se llamó con el modelo correcto
    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert "haiku" in call_kwargs["model"] or "claude" in call_kwargs["model"]
    assert call_kwargs["system"]  # system prompt no vacío


def test_parse_tweets_to_plan_no_api_key(monkeypatch):
    """Sin ANTHROPIC_API_KEY lanza RuntimeError."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        parse_tweets_to_plan([], "2026-04-10")


def test_parse_tweets_to_plan_no_plan_day(monkeypatch):
    """Día sin plan devuelve None."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-123")

    haiku_response = json.dumps({
        "key_level_upper": None,
        "targets_upper": [],
        "key_level_lower": None,
        "targets_lower": [],
        "chop_zone": None,
        "notes": "Vol muerta, sin plan",
    })

    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text=haiku_response)]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_msg

    with patch("scripts.mancini.tweet_parser.Anthropic", return_value=mock_client):
        plan = parse_tweets_to_plan(
            [{"text": "Vol dead, nothing to do", "created_at": "2026-04-10T10:00:00"}],
            "2026-04-10",
        )

    assert plan is None


# ── parse_weekly_tweets ───────────────────────────────────────────────

def test_parse_weekly_tweets_ok(monkeypatch):
    """Parsea Big Picture View correctamente."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-123")

    haiku_response = json.dumps({
        "key_level_upper": 6817,
        "targets_upper": [6903, 6950, 7068],
        "key_level_lower": 6793,
        "targets_lower": [],
        "chop_zone": None,
        "notes": "Sesgo: alcista. Bull flag breakout, +300 pts semana pasada.",
    })

    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text=haiku_response)]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_msg

    with patch("scripts.mancini.tweet_parser.Anthropic", return_value=mock_client):
        tweets = [{
            "text": "Big Picture View: Bulls want to hold 6817, 6793 lowest.",
            "created_at": "2026-04-11T14:00:00",
        }]
        plan = parse_weekly_tweets(tweets, "2026-04-14")

    assert plan is not None
    assert plan.fecha == "2026-04-14"
    assert plan.key_level_upper == 6817
    assert plan.key_level_lower == 6793
    assert plan.targets_upper == [6903, 6950, 7068]
    assert "alcista" in plan.notes.lower()

    # Verifica que usa el WEEKLY_SYSTEM_PROMPT
    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert "Big Picture" in call_kwargs["system"]


def test_parse_weekly_tweets_no_plan(monkeypatch):
    """Sin Big Picture claro devuelve None."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-123")

    haiku_response = json.dumps({
        "key_level_upper": None,
        "targets_upper": [],
        "key_level_lower": None,
        "targets_lower": [],
        "chop_zone": None,
        "notes": "No es un Big Picture View",
    })

    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text=haiku_response)]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_msg

    with patch("scripts.mancini.tweet_parser.Anthropic", return_value=mock_client):
        plan = parse_weekly_tweets(
            [{"text": "Random tweet", "created_at": "2026-04-11T10:00:00"}],
            "2026-04-14",
        )

    assert plan is None


def test_parse_weekly_tweets_no_api_key(monkeypatch):
    """Sin API key lanza RuntimeError."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        parse_weekly_tweets([], "2026-04-14")
