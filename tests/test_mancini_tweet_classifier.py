"""Tests para scripts/mancini/tweet_classifier.py — Clasificador intraday."""

import json
import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from scripts.mancini.config import DailyPlan, PlanAdjustment
from scripts.mancini.tweet_classifier import classify_tweet, _parse_classifier_response


@pytest.fixture
def sample_plan():
    return DailyPlan(
        fecha="2026-04-16",
        key_level_upper=6809,
        targets_upper=[6819, 6830],
        key_level_lower=6781,
        targets_lower=[6766],
    )


# ── Tests de _parse_classifier_response ──────────────────────────


def test_parse_invalidation():
    content = json.dumps({
        "adjustment_type": "INVALIDATION",
        "details": {"scope": "full", "condition": "below 6760", "invalidated_levels": [6781]},
        "reasoning": "Plan invalidado por rotura de soporte",
    })
    adj = _parse_classifier_response(content, "123", "plan invalidated", "2026-04-16T10:00:00")
    assert adj.adjustment_type == "INVALIDATION"
    assert adj.details["scope"] == "full"
    assert adj.tweet_id == "123"
    assert adj.tweet_text == "plan invalidated"


def test_parse_level_update():
    content = json.dumps({
        "adjustment_type": "LEVEL_UPDATE",
        "details": {"side": "lower", "old_level": 6781, "new_level": 6790, "reason": "buyers defending higher"},
        "reasoning": "Nivel lower ajustado de 6781 a 6790",
    })
    adj = _parse_classifier_response(content, "456", "buyers defending 6790", "2026-04-16T11:00:00")
    assert adj.adjustment_type == "LEVEL_UPDATE"
    assert adj.details["new_level"] == 6790


def test_parse_context_update():
    content = json.dumps({
        "adjustment_type": "CONTEXT_UPDATE",
        "details": {"context_type": "defense", "summary": "nice move, watching 6800", "implied_bias": None},
        "reasoning": "Info cualitativa sin cambio de niveles",
    })
    adj = _parse_classifier_response(content, "789", "nice move watching 6800", "2026-04-16T12:00:00")
    assert adj.adjustment_type == "CONTEXT_UPDATE"
    assert adj.details["context_type"] == "defense"


def test_parse_no_action():
    content = json.dumps({
        "adjustment_type": "NO_ACTION",
        "details": {},
        "reasoning": "Reply a follower, sin contenido de trading",
    })
    adj = _parse_classifier_response(content, "abc", "thanks for the follow!", "2026-04-16T13:00:00")
    assert adj.adjustment_type == "NO_ACTION"


def test_parse_invalid_json_returns_no_action():
    """Si Haiku devuelve JSON invalido, retorna NO_ACTION."""
    adj = _parse_classifier_response("not json at all", "err", "tweet", "2026-04-16T10:00:00")
    assert adj.adjustment_type == "NO_ACTION"
    assert "JSON invalido" in adj.raw_reasoning


def test_parse_target_update():
    content = json.dumps({
        "adjustment_type": "TARGET_UPDATE",
        "details": {"side": "upper", "new_targets": [6840, 6850], "replace": False},
        "reasoning": "Nuevos targets alcistas añadidos",
    })
    adj = _parse_classifier_response(content, "t1", "next targets 6840 6850", "2026-04-16T11:30:00")
    assert adj.adjustment_type == "TARGET_UPDATE"
    assert adj.details["new_targets"] == [6840, 6850]
    assert adj.details["replace"] is False


def test_parse_bias_shift():
    content = json.dumps({
        "adjustment_type": "BIAS_SHIFT",
        "details": {"old_bias": "bullish", "new_bias": "bearish", "trigger": "lost 6780"},
        "reasoning": "Cambio de sesgo a bajista",
    })
    adj = _parse_classifier_response(content, "b1", "flipped bearish", "2026-04-16T14:00:00")
    assert adj.adjustment_type == "BIAS_SHIFT"
    assert adj.details["new_bias"] == "bearish"


# ── Test de classify_tweet con mock de Anthropic ─────────────────


@patch("scripts.mancini.tweet_classifier.Anthropic")
def test_classify_tweet_calls_haiku(mock_anthropic_cls, sample_plan):
    """Verifica que classify_tweet llama a Haiku y parsea la respuesta."""
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps({
        "adjustment_type": "CONTEXT_UPDATE",
        "details": {"context_type": "general", "summary": "test", "implied_bias": None},
        "reasoning": "Tweet informativo",
    }))]
    mock_client.messages.create.return_value = mock_response

    adj = classify_tweet("some tweet", "id1", "2026-04-16T10:00:00", sample_plan)

    assert adj.adjustment_type == "CONTEXT_UPDATE"
    assert adj.tweet_id == "id1"
    mock_client.messages.create.assert_called_once()
    call_kwargs = mock_client.messages.create.call_args[1]
    assert "6809" in call_kwargs["system"]  # plan context included
    assert "6781" in call_kwargs["system"]
