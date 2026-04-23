"""Tests para scripts/mancini/execution_gate.py — Execution Gate LLM."""

import json
import os
import sys
from datetime import datetime
from unittest.mock import patch, MagicMock
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from scripts.mancini.execution_gate import (
    evaluate_signal,
    _parse_gate_response,
    GateDecision,
)

ET = ZoneInfo("America/New_York")


# ── _parse_gate_response ─────────────────────────────────────────────

def test_parse_valid_execute_true():
    raw = json.dumps({
        "execute": True,
        "reasoning": "Condiciones favorables",
        "risk_factors": [],
    })
    decision = _parse_gate_response(raw)
    assert decision.execute is True
    assert decision.reasoning == "Condiciones favorables"
    assert decision.risk_factors == []


def test_parse_valid_execute_false():
    raw = json.dumps({
        "execute": False,
        "reasoning": "Poco tiempo restante",
        "risk_factors": ["menos de 30 min", "segundo trade perdedor"],
    })
    decision = _parse_gate_response(raw)
    assert decision.execute is False
    assert len(decision.risk_factors) == 2


def test_parse_with_markdown_wrapper():
    """Haiku puede envolver JSON en ```json ... ```."""
    raw = '```json\n{"execute": true, "reasoning": "ok", "risk_factors": []}\n```'
    decision = _parse_gate_response(raw)
    assert decision.execute is True


def test_parse_invalid_json_defaults_false():
    """JSON inválido → execute=False (conservador)."""
    decision = _parse_gate_response("no es json")
    assert decision.execute is False
    assert "json_parse_error" in decision.risk_factors


def test_parse_missing_execute_defaults_false():
    """Sin campo execute → False."""
    raw = json.dumps({"reasoning": "algo", "risk_factors": []})
    decision = _parse_gate_response(raw)
    assert decision.execute is False


# ── evaluate_signal (con mock de Anthropic) ──────────────────────────

@patch("scripts.mancini.execution_gate.anthropic")
def test_gate_approves_favorable(mock_anthropic):
    """Gate aprueba con condiciones favorables."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps({
        "execute": True,
        "reasoning": "Primer trade del día, 4h restantes, alineado",
        "risk_factors": [],
    }))]
    mock_anthropic.Anthropic.return_value.messages.create.return_value = mock_response

    decision = evaluate_signal(
        signal_price=6785,
        signal_level=6781,
        breakdown_low=6776,
        direction="LONG",
        stop_price=6772,
        targets=[6793, 6809],
        plan_notes="",
        alignment="ALIGNED",
        trades_today=[],
        recent_adjustments=[],
        current_time_et=datetime(2026, 4, 10, 10, 0, tzinfo=ET),
        session_end_hour=16,
    )
    assert decision.execute is True


@patch("scripts.mancini.execution_gate.anthropic")
def test_gate_rejects_late_session(mock_anthropic):
    """Gate rechaza con poco tiempo restante."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps({
        "execute": False,
        "reasoning": "Solo 20 minutos restantes",
        "risk_factors": ["menos de 30 min para cierre"],
    }))]
    mock_anthropic.Anthropic.return_value.messages.create.return_value = mock_response

    decision = evaluate_signal(
        signal_price=6785,
        signal_level=6781,
        breakdown_low=6776,
        direction="LONG",
        stop_price=6772,
        targets=[6793],
        plan_notes="",
        alignment="NEUTRAL",
        trades_today=[],
        recent_adjustments=[],
        current_time_et=datetime(2026, 4, 10, 15, 40, tzinfo=ET),
        session_end_hour=16,
    )
    assert decision.execute is False
    assert len(decision.risk_factors) > 0


@patch("scripts.mancini.execution_gate.anthropic")
def test_gate_rejects_after_losses(mock_anthropic):
    """Gate rechaza tras 2 trades perdedores."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps({
        "execute": False,
        "reasoning": "Día con drawdown, 2 trades perdedores",
        "risk_factors": ["2 trades perdedores"],
    }))]
    mock_anthropic.Anthropic.return_value.messages.create.return_value = mock_response

    # Simular 2 trades perdedores
    trade1 = MagicMock(pnl_total_pts=-8)
    trade2 = MagicMock(pnl_total_pts=-5)

    decision = evaluate_signal(
        signal_price=6785,
        signal_level=6781,
        breakdown_low=6776,
        direction="LONG",
        stop_price=6772,
        targets=[6793],
        plan_notes="",
        alignment="NEUTRAL",
        trades_today=[trade1, trade2],
        recent_adjustments=[],
        current_time_et=datetime(2026, 4, 10, 14, 0, tzinfo=ET),
        session_end_hour=16,
    )
    assert decision.execute is False


@patch("scripts.mancini.execution_gate.anthropic")
def test_gate_includes_risk_factors(mock_anthropic):
    """Respuesta incluye factores de riesgo."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps({
        "execute": False,
        "reasoning": "Riesgo alto y contra sesgo",
        "risk_factors": ["riesgo alto (14 pts)", "contra sesgo semanal"],
    }))]
    mock_anthropic.Anthropic.return_value.messages.create.return_value = mock_response

    decision = evaluate_signal(
        signal_price=6785,
        signal_level=6781,
        breakdown_low=6776,
        direction="LONG",
        stop_price=6771,
        targets=[6793],
        plan_notes="",
        alignment="MISALIGNED",
        trades_today=[],
        recent_adjustments=[],
        current_time_et=datetime(2026, 4, 10, 12, 0, tzinfo=ET),
        session_end_hour=16,
    )
    assert "riesgo alto (14 pts)" in decision.risk_factors
    assert "contra sesgo semanal" in decision.risk_factors


# ── GateDecision serialización ────────────────────────────────────────

def test_gate_decision_to_dict():
    d = GateDecision(execute=True, reasoning="ok", risk_factors=["a", "b"])
    assert d.to_dict() == {"execute": True, "reasoning": "ok", "risk_factors": ["a", "b"]}


def test_gate_decision_from_dict():
    d = GateDecision.from_dict({"execute": False, "reasoning": "no"})
    assert d.execute is False
    assert d.risk_factors == []


# ── Parámetros de calidad de señal ───────────────────────────────────

def _base_call(mock_anthropic, response_dict, **quality_kwargs):
    """Helper: llama evaluate_signal con valores base + quality kwargs."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps(response_dict))]
    mock_anthropic.Anthropic.return_value.messages.create.return_value = mock_response

    return evaluate_signal(
        signal_price=6785,
        signal_level=6781,
        breakdown_low=6776,
        direction="LONG",
        stop_price=6772,
        targets=[6793, 6809],
        plan_notes="",
        alignment="ALIGNED",
        trades_today=[],
        recent_adjustments=[],
        current_time_et=datetime(2026, 4, 10, 10, 0, tzinfo=ET),
        session_end_hour=16,
        **quality_kwargs,
    )


@patch("scripts.mancini.execution_gate.anthropic")
def test_gate_accepts_quality_params_without_error(mock_anthropic):
    """evaluate_signal acepta los nuevos parámetros sin lanzar excepción."""
    decision = _base_call(
        mock_anthropic,
        {"execute": True, "reasoning": "ok", "risk_factors": []},
        breakdown_depth_pts=6.0,
        acceptance_pauses=0,
        acceptance_max_above_level=5.0,
        recovery_velocity_pts_min=2.5,
        time_quality="prime",
    )
    assert decision.execute is True


@patch("scripts.mancini.execution_gate.anthropic")
def test_gate_default_quality_params_dont_break_call(mock_anthropic):
    """Llamada sin parámetros de calidad usa defaults y no falla."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps({
        "execute": True, "reasoning": "ok", "risk_factors": [],
    }))]
    mock_anthropic.Anthropic.return_value.messages.create.return_value = mock_response

    decision = evaluate_signal(
        signal_price=6785,
        signal_level=6781,
        breakdown_low=6776,
        direction="LONG",
        stop_price=6772,
        targets=[6793],
        plan_notes="",
        alignment="ALIGNED",
        trades_today=[],
        recent_adjustments=[],
        current_time_et=datetime(2026, 4, 10, 10, 0, tzinfo=ET),
        session_end_hour=16,
        # Sin parámetros de calidad → usan defaults
    )
    assert decision.execute is True


@patch("scripts.mancini.execution_gate.anthropic")
def test_gate_quality_metrics_appear_in_prompt(mock_anthropic):
    """Las métricas de calidad se incluyen en el system prompt enviado al LLM."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps({
        "execute": False,
        "reasoning": "velocidad baja y retests",
        "risk_factors": ["velocidad < 1.0 pts/min", "2 retests durante aceptación"],
    }))]
    mock_anthropic.Anthropic.return_value.messages.create.return_value = mock_response

    _base_call(
        mock_anthropic,
        {"execute": False, "reasoning": "x", "risk_factors": []},
        breakdown_depth_pts=2.5,
        acceptance_pauses=2,
        acceptance_max_above_level=1.8,
        recovery_velocity_pts_min=0.7,
        time_quality="late",
    )

    call_kwargs = mock_anthropic.Anthropic.return_value.messages.create.call_args
    system_prompt = call_kwargs.kwargs.get("system") or call_kwargs.args[0] if call_kwargs.args else ""
    if not system_prompt:
        system_prompt = call_kwargs[1].get("system", "")

    assert "2.5" in system_prompt      # breakdown_depth_pts
    assert "2" in system_prompt        # acceptance_pauses
    assert "1.8" in system_prompt      # acceptance_max_above_level
    assert "0.7" in system_prompt      # recovery_velocity_pts_min
    assert "late" in system_prompt     # time_quality


@patch("scripts.mancini.execution_gate.anthropic")
def test_gate_returns_quality_risk_factors_when_provided(mock_anthropic):
    """El gate devuelve factores de riesgo de calidad cuando el LLM los detecta."""
    decision = _base_call(
        mock_anthropic,
        {
            "execute": False,
            "reasoning": "señal anémica con múltiples retests",
            "risk_factors": ["velocidad < 1.0 pts/min", "2 retests durante aceptación"],
        },
        breakdown_depth_pts=2.0,
        acceptance_pauses=2,
        acceptance_max_above_level=1.6,
        recovery_velocity_pts_min=0.5,
        time_quality="extended",
    )
    assert decision.execute is False
    assert any("velocidad" in f for f in decision.risk_factors)
    assert any("retests" in f for f in decision.risk_factors)


@patch("scripts.mancini.execution_gate.anthropic")
def test_gate_time_quality_late_included_in_prompt(mock_anthropic):
    """time_quality='late' aparece en el prompt para que el LLM lo evalúe."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps({
        "execute": False,
        "reasoning": "sesión tardía",
        "risk_factors": ["time_quality=late"],
    }))]
    mock_anthropic.Anthropic.return_value.messages.create.return_value = mock_response

    _base_call(mock_anthropic, {}, time_quality="late")

    call_kwargs = mock_anthropic.Anthropic.return_value.messages.create.call_args
    system_prompt = call_kwargs.kwargs.get("system", "")
    assert "late" in system_prompt
