"""
Execution Gate — validación LLM antes de abrir posición.

Evalúa si el contexto (hora, P&L, alignment, ajustes intraday) es favorable
para ejecutar un trade detectado por la máquina de estados. La señal técnica
ya está confirmada; el gate juzga el CONTEXTO.

Conservador por defecto: si el JSON es inválido, retorna execute=False.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime

import anthropic

MODEL = "claude-haiku-4-5-20251001"

GATE_SYSTEM_PROMPT = """\
Eres un validador de ejecución para la estrategia Failed Breakdown en futuros /ES.

Se ha detectado una señal técnica válida (failed breakdown confirmado por la
máquina de estados). Tu trabajo es evaluar si el CONTEXTO es favorable para
ejecutar el trade, no si la señal técnica es correcta (eso ya está confirmado).

## Datos de la señal
- Nivel: {signal_level}
- Precio actual: {signal_price}
- Breakdown low: {breakdown_low}
- Dirección: {direction}
- Stop calculado: {stop_price} ({risk_pts:.1f} pts de riesgo)
- Targets: {targets}

## Contexto
- Hora actual (ET): {current_time}
- Hora cierre sesión: {session_end}:00 ET
- Minutos restantes: {minutes_remaining}
- Alignment semanal: {alignment}
- Trades hoy: {trades_count} ({trades_summary})
- P&L del día: {daily_pnl:+.1f} pts
- Actualizaciones intraday recientes: {recent_updates}
- Notas del plan: {plan_notes}

## Métricas de calidad de la señal técnica

Estas métricas describen CÓMO se produjo la confirmación. Úsalas para evaluar
la convicción real de la señal, no solo que ocurrió:

- Profundidad del breakdown: {breakdown_depth_pts} pts
  (óptimo: 4-8 pts; < 3 = posible ruido; 9-11 = trampa fuerte)
- Retests durante aceptación: {acceptance_pauses}
  (0 = aceptación limpia; 1 = aceptable; 2+ = indecisión)
- Precio máximo sobre nivel durante aceptación: {acceptance_max_above_level} pts
  (> 3 pts = convicción; < 2 pts = precio apenas superó el umbral)
- Velocidad de recuperación: {recovery_velocity_pts_min} pts/min
  (> 2.0 = recuperación agresiva; < 1.0 = anémica, posible trampa)
- Calidad horaria: {time_quality}
  (prime = 09:30-12:30 ET, óptimo; extended = 12:30-14:00, normal; late = 14:00+, cuidado)

## Criterios de evaluación

Factores que FAVORECEN ejecución:
- Más de 60 minutos de sesión restantes
- Alineado con sesgo semanal
- Sin trades perdedores previos hoy (o el primero del día)
- Sin actualizaciones intraday recientes que contradigan el trade
- Riesgo razonable (stop < 10 pts)
- Velocidad de recuperación >= 2.0 pts/min
- 0 retests durante aceptación (aceptación limpia)

Factores de RIESGO (no necesariamente descalificantes):
- Menos de 30 minutos para cierre (poco recorrido)
- Contra sesgo semanal (MISALIGNED)
- Día con 2+ trades perdedores (drawdown)
- Invalidación intraday reciente seguida de re-validación
- Riesgo alto (stop > 12 pts)
- Breakdown muy poco profundo (< 3 pts, posible ruido)
- Velocidad de recuperación < 1.0 pts/min (señal anémica)
- 2+ retests durante aceptación (indecisión en el nivel)
- Precio máximo < 2 pts sobre nivel (sin convicción real)
- time_quality = "late" (sesión avanzada, menos recorrido)

REGLA IMPORTANTE: si hay 2 o más factores de riesgo de calidad activos
simultáneamente (profundidad < 3, velocidad < 1.0, retests >= 2, max < 2 pts,
o time_quality = "late"), establece execute=false aunque el contexto temporal
sea favorable. La calidad de la señal importa tanto como el contexto.

## Decisión

Responde SOLO con JSON:

{{
  "execute": true/false,
  "reasoning": "explicación breve en español de por qué ejecutar o consultar",
  "risk_factors": ["factor1", "factor2"]
}}

- execute=true: la situación es claramente favorable, ejecutar sin consultar.
- execute=false: hay factores de riesgo relevantes, consultar al trader.

Sé conservador: en caso de duda, execute=false. Es mejor preguntar que perder.
"""


@dataclass
class GateDecision:
    """Resultado de la evaluación del Execution Gate."""

    execute: bool
    reasoning: str
    risk_factors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> GateDecision:
        return cls(
            execute=d.get("execute", False),
            reasoning=d.get("reasoning", ""),
            risk_factors=d.get("risk_factors", []),
        )


def evaluate_signal(
    signal_price: float,
    signal_level: float,
    breakdown_low: float,
    direction: str,
    stop_price: float,
    targets: list[float],
    plan_notes: str,
    alignment: str,
    trades_today: list,
    recent_adjustments: list,
    current_time_et: datetime,
    session_end_hour: int,
    breakdown_depth_pts: float = 0.0,
    acceptance_pauses: int = 0,
    acceptance_max_above_level: float = 0.0,
    recovery_velocity_pts_min: float = 0.0,
    time_quality: str = "prime",
) -> GateDecision:
    """
    Evalúa si el contexto es favorable para ejecutar un trade.

    Args:
        signal_price: precio actual del /ES
        signal_level: nivel clave donde se produjo el failed breakdown
        breakdown_low: mínimo alcanzado durante el breakdown
        direction: "LONG" o "SHORT"
        stop_price: stop calculado
        targets: lista de niveles objetivo
        plan_notes: notas del plan diario
        alignment: "ALIGNED", "NEUTRAL" o "MISALIGNED"
        trades_today: lista de Trade del día
        recent_adjustments: lista de PlanAdjustment recientes
        current_time_et: hora actual en ET
        session_end_hour: hora de cierre de sesión

    Returns:
        GateDecision con la evaluación del LLM.
    """
    risk_pts = abs(signal_price - stop_price)

    # Calcular minutos restantes
    session_end_time = current_time_et.replace(
        hour=session_end_hour, minute=0, second=0, microsecond=0,
    )
    minutes_remaining = max(
        0, int((session_end_time - current_time_et).total_seconds() / 60)
    )

    # Resumen de trades del día
    trades_count = len(trades_today)
    if trades_count == 0:
        trades_summary = "primer trade del día"
    else:
        losers = sum(1 for t in trades_today if (t.pnl_total_pts or 0) < 0)
        winners = sum(1 for t in trades_today if (t.pnl_total_pts or 0) > 0)
        trades_summary = f"{winners}W {losers}L"

    daily_pnl = sum(t.pnl_total_pts or 0 for t in trades_today)

    # Resumen de ajustes recientes
    if recent_adjustments:
        recent_updates = "; ".join(
            f"{a.adjustment_type}: {a.raw_reasoning[:60]}"
            for a in recent_adjustments[-3:]
            if a.adjustment_type != "NO_ACTION"
        ) or "ninguno relevante"
    else:
        recent_updates = "ninguno"

    system = GATE_SYSTEM_PROMPT.format(
        signal_level=signal_level,
        signal_price=signal_price,
        breakdown_low=breakdown_low,
        direction=direction,
        stop_price=stop_price,
        risk_pts=risk_pts,
        targets=targets,
        current_time=current_time_et.strftime("%H:%M"),
        session_end=session_end_hour,
        minutes_remaining=minutes_remaining,
        alignment=alignment,
        trades_count=trades_count,
        trades_summary=trades_summary,
        daily_pnl=daily_pnl,
        recent_updates=recent_updates,
        plan_notes=plan_notes or "sin notas",
        breakdown_depth_pts=breakdown_depth_pts,
        acceptance_pauses=acceptance_pauses,
        acceptance_max_above_level=acceptance_max_above_level,
        recovery_velocity_pts_min=recovery_velocity_pts_min,
        time_quality=time_quality,
    )

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=600,
        system=system,
        messages=[{"role": "user", "content": "Evalúa esta señal de trading para ejecución automática."}],
    )

    raw = response.content[0].text
    return _parse_gate_response(raw)


def _parse_gate_response(raw: str) -> GateDecision:
    """Parsea la respuesta JSON del LLM. Fallback conservador si falla."""
    try:
        # Limpiar posible markdown
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        data = json.loads(text)
        return GateDecision(
            execute=bool(data.get("execute", False)),
            reasoning=str(data.get("reasoning", "")),
            risk_factors=list(data.get("risk_factors", [])),
        )
    except (json.JSONDecodeError, KeyError, TypeError):
        return GateDecision(
            execute=False,
            reasoning=f"Error parseando respuesta del gate: {raw[:100]}",
            risk_factors=["json_parse_error"],
        )
