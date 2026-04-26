"""
Modelo de datos y persistencia para el plan diario de Mancini.

Define DailyPlan (niveles clave extraídos de tweets) y funciones
para leer/escribir outputs/mancini_plan.json.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

PLAN_PATH = Path("outputs/mancini_plan.json")
WEEKLY_PLAN_PATH = Path("outputs/mancini_weekly.json")
INTRADAY_STATE_PATH = Path("outputs/mancini_intraday.json")


@dataclass
class DailyPlan:
    """Plan diario extraído de los tweets de Mancini."""

    fecha: str  # YYYY-MM-DD
    key_level_upper: float | None
    targets_upper: list[float]
    key_level_lower: float | None
    targets_lower: list[float]
    raw_tweets: list[str] = field(default_factory=list)
    chop_zone: tuple[float, float] | None = None
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""
    is_stale: bool = False       # True si es plan de otro día usado como fallback provisional
    is_auto_levels: bool = False  # True si fue generado desde niveles técnicos autónomos

    def __post_init__(self):
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    def merge_update(self, new_targets_upper: list[float] | None = None,
                     new_targets_lower: list[float] | None = None,
                     new_tweet: str | None = None,
                     notes: str | None = None) -> None:
        """Incorpora actualizaciones intraday sin perder datos existentes."""
        if new_targets_upper:
            for t in new_targets_upper:
                if t not in self.targets_upper:
                    self.targets_upper.append(t)
            self.targets_upper.sort()
        if new_targets_lower:
            for t in new_targets_lower:
                if t not in self.targets_lower:
                    self.targets_lower.append(t)
            self.targets_lower.sort(reverse=True)
        if new_tweet and new_tweet not in self.raw_tweets:
            self.raw_tweets.append(new_tweet)
        if notes:
            self.notes = f"{self.notes}\n{notes}".strip() if self.notes else notes
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        d = asdict(self)
        if d["chop_zone"] is not None:
            d["chop_zone"] = list(d["chop_zone"])
        return d  # is_stale incluido para uso en notificaciones

    @classmethod
    def from_dict(cls, d: dict) -> DailyPlan:
        if d.get("chop_zone") is not None:
            d["chop_zone"] = tuple(d["chop_zone"])
        d.pop("session_mode", None)  # retrocompatibilidad con planes guardados anteriormente
        d.pop("is_stale", None)       # no leer del JSON — siempre False al cargar
        d.pop("is_auto_levels", None)  # ídem
        return cls(**d)


def save_plan(plan: DailyPlan, path: Path = PLAN_PATH) -> None:
    """Persiste el plan en JSON (is_stale no se guarda — es estado en memoria)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    d = plan.to_dict()
    d.pop("is_stale", None)
    d.pop("is_auto_levels", None)
    path.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")


def load_plan(path: Path = PLAN_PATH) -> DailyPlan | None:
    """Carga el plan desde JSON. Retorna None si no existe."""
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return DailyPlan.from_dict(data)


@dataclass
class PlanAdjustment:
    """Ajuste intraday emitido por el clasificador de tweets."""

    tweet_id: str
    tweet_text: str
    timestamp: str  # ISO timestamp del tweet
    adjustment_type: str  # INVALIDATION, LEVEL_UPDATE, TARGET_UPDATE, BIAS_SHIFT, CONTEXT_UPDATE, NO_ACTION
    details: dict = field(default_factory=dict)
    raw_reasoning: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> PlanAdjustment:
        return cls(**d)


@dataclass
class IntraDayState:
    """Estado del clasificador intraday: tweets procesados y ajustes emitidos."""

    processed_tweet_ids: set[str] = field(default_factory=set)
    adjustments: list[PlanAdjustment] = field(default_factory=list)
    last_check: str = ""
    fecha: str = ""  # YYYY-MM-DD — para detectar cambio de día y resetear

    def to_dict(self) -> dict:
        return {
            "fecha": self.fecha,
            "processed_tweet_ids": sorted(self.processed_tweet_ids),
            "adjustments": [a.to_dict() for a in self.adjustments],
            "last_check": self.last_check,
        }

    @classmethod
    def from_dict(cls, d: dict) -> IntraDayState:
        return cls(
            processed_tweet_ids=set(d.get("processed_tweet_ids", [])),
            adjustments=[PlanAdjustment.from_dict(a) for a in d.get("adjustments", [])],
            last_check=d.get("last_check", ""),
            fecha=d.get("fecha", ""),
        )


def save_intraday_state(state: IntraDayState, path: Path = INTRADAY_STATE_PATH) -> None:
    """Persiste el estado intraday en JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_dict(), indent=2, ensure_ascii=False),
                    encoding="utf-8")


def load_intraday_state(path: Path = INTRADAY_STATE_PATH) -> IntraDayState:
    """Carga el estado intraday desde JSON. Retorna estado vacío si no existe o es de otro día."""
    if not path.exists():
        return IntraDayState()
    data = json.loads(path.read_text(encoding="utf-8"))
    state = IntraDayState.from_dict(data)
    from datetime import date
    today = date.today().isoformat()
    if state.fecha and state.fecha != today:
        return IntraDayState()  # nuevo día → estado limpio
    return state


def save_weekly(plan: DailyPlan, path: Path = WEEKLY_PLAN_PATH) -> None:
    """Persiste el plan semanal en JSON."""
    save_plan(plan, path)


def load_weekly(path: Path = WEEKLY_PLAN_PATH) -> DailyPlan | None:
    """Carga el plan semanal desde JSON. Retorna None si no existe."""
    return load_plan(path)
