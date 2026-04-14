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
        return d

    @classmethod
    def from_dict(cls, d: dict) -> DailyPlan:
        if d.get("chop_zone") is not None:
            d["chop_zone"] = tuple(d["chop_zone"])
        return cls(**d)


def save_plan(plan: DailyPlan, path: Path = PLAN_PATH) -> None:
    """Persiste el plan en JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan.to_dict(), indent=2, ensure_ascii=False),
                    encoding="utf-8")


def load_plan(path: Path = PLAN_PATH) -> DailyPlan | None:
    """Carga el plan desde JSON. Retorna None si no existe."""
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return DailyPlan.from_dict(data)


def save_weekly(plan: DailyPlan, path: Path = WEEKLY_PLAN_PATH) -> None:
    """Persiste el plan semanal en JSON."""
    save_plan(plan, path)


def load_weekly(path: Path = WEEKLY_PLAN_PATH) -> DailyPlan | None:
    """Carga el plan semanal desde JSON. Retorna None si no existe."""
    return load_plan(path)
    """Persiste el plan semanal (Big Picture View) en JSON."""
    save_plan(plan, path=path)


def load_weekly(path: Path = WEEKLY_PLAN_PATH) -> DailyPlan | None:
    """Carga el plan semanal. Retorna None si no existe."""
    return load_plan(path=path)
