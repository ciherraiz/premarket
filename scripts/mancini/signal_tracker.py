"""
Ciclo de vida de señales Failed Breakdown — independiente de si se opera o no.

Una señal se crea al detectar el SIGNAL state, se resuelve cuando:
- confirmed:   precio alcanza el primer target (T1)
- invalidated: precio toca el stop antes de T1
- expired:     fin de sesión sin resolución
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _load_scores() -> tuple[Optional[int], Optional[int]]:
    """Lee d_score y v_score de outputs/indicators.json si existe."""
    try:
        path = Path("outputs/indicators.json")
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data.get("d_score"), data.get("v_score")
    except Exception:
        pass
    return None, None


@dataclass
class FailedBreakdownSignal:
    signal_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    detected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    level: float = 0.0
    direction: str = "LONG"

    # Métricas de calidad de la señal
    breakdown_depth_pts: float = 0.0
    acceptance_pauses: int = 0
    acceptance_max_above_level: float = 0.0
    recovery_velocity_pts_min: float = 0.0
    time_quality: str = "prime"

    # Contexto de indicadores
    alignment: str = "NEUTRAL"
    d_score: Optional[int] = None
    v_score: Optional[int] = None

    # Ciclo de vida
    status: str = "detected"   # detected | confirmed | invalidated | expired
    t1_price: Optional[float] = None
    stop_price: float = 0.0
    confirmed_at: Optional[str] = None
    invalidated_at: Optional[str] = None
    minutes_to_resolution: Optional[float] = None

    # Enlace a operación real
    trade_id: Optional[str] = None
    gate_execute: Optional[bool] = None
    gate_reasoning: str = ""

    def confirm(self, timestamp: str) -> None:
        self.status = "confirmed"
        self.confirmed_at = timestamp
        self._calc_minutes(timestamp)

    def invalidate(self, timestamp: str) -> None:
        self.status = "invalidated"
        self.invalidated_at = timestamp
        self._calc_minutes(timestamp)

    def expire(self, timestamp: str) -> None:
        self.status = "expired"
        self.invalidated_at = timestamp
        self._calc_minutes(timestamp)

    def _calc_minutes(self, timestamp: str) -> None:
        try:
            t0 = datetime.fromisoformat(self.detected_at)
            t1 = datetime.fromisoformat(timestamp)
            self.minutes_to_resolution = round((t1 - t0).total_seconds() / 60, 1)
        except Exception:
            pass

    def to_dict(self) -> dict:
        return {
            "signal_id": self.signal_id,
            "detected_at": self.detected_at,
            "level": self.level,
            "direction": self.direction,
            "breakdown_depth_pts": self.breakdown_depth_pts,
            "acceptance_pauses": self.acceptance_pauses,
            "acceptance_max_above_level": self.acceptance_max_above_level,
            "recovery_velocity_pts_min": self.recovery_velocity_pts_min,
            "time_quality": self.time_quality,
            "alignment": self.alignment,
            "d_score": self.d_score,
            "v_score": self.v_score,
            "status": self.status,
            "t1_price": self.t1_price,
            "stop_price": self.stop_price,
            "confirmed_at": self.confirmed_at,
            "invalidated_at": self.invalidated_at,
            "minutes_to_resolution": self.minutes_to_resolution,
            "trade_id": self.trade_id,
            "gate_execute": self.gate_execute,
            "gate_reasoning": self.gate_reasoning,
        }
