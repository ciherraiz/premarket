"""
Máquina de estados para detección de Failed Breakdown/Breakout.

Implementa el patrón de Mancini: ruptura convincente de un nivel clave (2-11 pts),
seguida de recuperación y aceptación del precio sobre ese nivel → señal de entrada.

Cada instancia de FailedBreakdownDetector vigila UN nivel clave.
El monitor crea dos instancias: una para el nivel superior y otra para el inferior.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

# ── Constantes configurables ────────────────────────────────────────
MIN_BREAK_PTS = 2        # Penetración mínima para break "convincente"
MAX_BREAK_PTS = 11       # Más allá = break real, no failed
ACCEPTANCE_PTS = 1.5     # Puntos sobre nivel para considerar "reclaim"
ACCEPTANCE_SECONDS = 120 # Segundos continuos sobre nivel para confirmar aceptación
MAX_ACCEPTANCE_PAUSES = 3 # Retests máximos durante aceptación; si se supera → WATCHING


def _elapsed_seconds(start: str, end: str) -> float:
    t0 = datetime.fromisoformat(start.replace("Z", "+00:00"))
    t1 = datetime.fromisoformat(end.replace("Z", "+00:00"))
    return (t1 - t0).total_seconds()

STATE_PATH = Path("outputs/mancini_state.json")


class State(str, Enum):
    WATCHING = "WATCHING"
    BREAKDOWN = "BREAKDOWN"
    RECOVERY = "RECOVERY"
    SIGNAL = "SIGNAL"
    ACTIVE = "ACTIVE"
    DONE = "DONE"
    EXPIRED = "EXPIRED"


@dataclass
class StateTransition:
    """Resultado de un cambio de estado en el detector."""
    from_state: State
    to_state: State
    level: float
    price: float
    timestamp: str
    details: dict = field(default_factory=dict)


@dataclass
class FailedBreakdownDetector:
    """
    Detecta el patrón Failed Breakdown para UN nivel clave.

    El patrón (para nivel inferior, señal LONG):
    1. WATCHING: precio se acerca al nivel
    2. BREAKDOWN: precio cae 2-11 pts por debajo del nivel
    3. RECOVERY: precio vuelve a subir por encima del nivel
    4. SIGNAL: precio se mantiene sobre el nivel N polls consecutivos
    """

    level: float
    side: str  # "upper" o "lower"
    state: State = State.WATCHING
    breakdown_low: float | None = None
    acceptance_since: str | None = None  # ISO timestamp inicio aceptación continua
    signal_price: float | None = None
    signal_timestamp: str | None = None
    acceptance_pauses: int = 0                # retests durante ventana de aceptación
    acceptance_max_price: float | None = None # precio máximo alcanzado en ventana

    def process_tick(self, price: float, timestamp: str) -> StateTransition | None:
        """
        Procesa un tick de precio y retorna StateTransition si hubo cambio de estado.

        Args:
            price: precio actual de /ES
            timestamp: ISO timestamp del tick

        Returns:
            StateTransition si hubo cambio, None si no.
        """
        if self.state in (State.DONE, State.EXPIRED, State.SIGNAL, State.ACTIVE):
            return None

        prev_state = self.state

        if self.state == State.WATCHING:
            return self._process_watching(price, timestamp, prev_state)
        elif self.state == State.BREAKDOWN:
            return self._process_breakdown(price, timestamp, prev_state)
        elif self.state == State.RECOVERY:
            return self._process_recovery(price, timestamp, prev_state)

        return None

    def _process_watching(self, price: float, timestamp: str,
                          prev_state: State) -> StateTransition | None:
        """Desde WATCHING: detecta si hay breakdown."""
        depth = self.level - price  # positivo si precio bajo nivel

        if MIN_BREAK_PTS <= depth <= MAX_BREAK_PTS:
            self.state = State.BREAKDOWN
            self.breakdown_low = price
            return StateTransition(
                from_state=prev_state,
                to_state=State.BREAKDOWN,
                level=self.level,
                price=price,
                timestamp=timestamp,
                details={"depth_pts": round(depth, 2)},
            )
        return None

    def _process_breakdown(self, price: float, timestamp: str,
                           prev_state: State) -> StateTransition | None:
        """Desde BREAKDOWN: detecta recovery o break real."""
        depth = self.level - price

        # Rastrear el mínimo del breakdown
        if self.breakdown_low is None or price < self.breakdown_low:
            self.breakdown_low = price

        # Break demasiado profundo → volver a WATCHING (no es failed breakdown)
        if depth > MAX_BREAK_PTS:
            self.state = State.WATCHING
            self.breakdown_low = None
            return StateTransition(
                from_state=prev_state,
                to_state=State.WATCHING,
                level=self.level,
                price=price,
                timestamp=timestamp,
                details={"reason": "break_too_deep", "depth_pts": round(depth, 2)},
            )

        # Recovery: precio sube por encima del nivel + acceptance pts
        if price >= self.level + ACCEPTANCE_PTS:
            self.state = State.RECOVERY
            self.acceptance_since = timestamp  # arranca el reloj
            self.acceptance_pauses = 0
            self.acceptance_max_price = price
            return StateTransition(
                from_state=prev_state,
                to_state=State.RECOVERY,
                level=self.level,
                price=price,
                timestamp=timestamp,
                details={"breakdown_low": self.breakdown_low},
            )

        return None

    def _process_recovery(self, price: float, timestamp: str,
                          prev_state: State) -> StateTransition | None:
        """Desde RECOVERY: confirma aceptación o detecta recaída."""
        # Si el precio vuelve a caer bajo el nivel → volver a BREAKDOWN
        if price < self.level - MIN_BREAK_PTS:
            self.state = State.BREAKDOWN
            self.acceptance_since = None
            self.acceptance_pauses = 0
            self.acceptance_max_price = None
            if self.breakdown_low is None or price < self.breakdown_low:
                self.breakdown_low = price
            return StateTransition(
                from_state=prev_state,
                to_state=State.BREAKDOWN,
                level=self.level,
                price=price,
                timestamp=timestamp,
                details={"reason": "failed_recovery"},
            )

        if price >= self.level + ACCEPTANCE_PTS:
            # Actualizar precio máximo alcanzado durante la aceptación
            if self.acceptance_max_price is None or price > self.acceptance_max_price:
                self.acceptance_max_price = price

            # Reiniciar reloj si se había pausado
            if self.acceptance_since is None:
                self.acceptance_since = timestamp

            elapsed = _elapsed_seconds(self.acceptance_since, timestamp)
            if elapsed >= ACCEPTANCE_SECONDS:
                # Calcular métricas de calidad de la señal
                depth_pts = round(self.level - (self.breakdown_low or self.level), 2)
                max_above = round((self.acceptance_max_price or price) - self.level, 2)
                velocity = round(max_above / (elapsed / 60), 2) if elapsed > 0 else 0.0

                self.state = State.SIGNAL
                self.signal_price = price
                self.signal_timestamp = timestamp
                return StateTransition(
                    from_state=prev_state,
                    to_state=State.SIGNAL,
                    level=self.level,
                    price=price,
                    timestamp=timestamp,
                    details={
                        "breakdown_low": self.breakdown_low,
                        "elapsed_seconds": round(elapsed, 1),
                        "breakdown_depth_pts": depth_pts,
                        "acceptance_pauses": self.acceptance_pauses,
                        "acceptance_max_above_level": max_above,
                        "recovery_velocity_pts_min": velocity,
                    },
                )
        else:
            # Entre el nivel y el umbral: pausar reloj y contar retest
            if self.acceptance_since is not None:
                self.acceptance_pauses += 1

                # Filtro duro: demasiados retests → señal inválida
                if self.acceptance_pauses >= MAX_ACCEPTANCE_PAUSES:
                    self.state = State.WATCHING
                    self.breakdown_low = None
                    self.acceptance_since = None
                    self.acceptance_pauses = 0
                    self.acceptance_max_price = None
                    return StateTransition(
                        from_state=prev_state,
                        to_state=State.WATCHING,
                        level=self.level,
                        price=price,
                        timestamp=timestamp,
                        details={
                            "reason": "excessive_retests",
                            "pauses": MAX_ACCEPTANCE_PAUSES,
                        },
                    )

            self.acceptance_since = None

        return None

    def mark_active(self) -> None:
        """Marca el detector como ACTIVE (trade abierto)."""
        self.state = State.ACTIVE

    def mark_done(self) -> None:
        """Marca el detector como DONE (trade cerrado)."""
        self.state = State.DONE

    def mark_expired(self) -> None:
        """Marca el detector como EXPIRED (fin de ventana)."""
        self.state = State.EXPIRED

    def reset(self) -> None:
        """Resetea el detector para un nuevo día/ciclo."""
        self.state = State.WATCHING
        self.breakdown_low = None
        self.acceptance_since = None
        self.signal_price = None
        self.signal_timestamp = None
        self.acceptance_pauses = 0
        self.acceptance_max_price = None

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "side": self.side,
            "state": self.state.value,
            "breakdown_low": self.breakdown_low,
            "acceptance_since": self.acceptance_since,
            "signal_price": self.signal_price,
            "signal_timestamp": self.signal_timestamp,
            "acceptance_pauses": self.acceptance_pauses,
            "acceptance_max_price": self.acceptance_max_price,
        }

    @classmethod
    def from_dict(cls, d: dict) -> FailedBreakdownDetector:
        return cls(
            level=d["level"],
            side=d["side"],
            state=State(d["state"]),
            breakdown_low=d.get("breakdown_low"),
            acceptance_since=d.get("acceptance_since"),
            signal_price=d.get("signal_price"),
            signal_timestamp=d.get("signal_timestamp"),
            acceptance_pauses=d.get("acceptance_pauses", 0),
            acceptance_max_price=d.get("acceptance_max_price"),
        )


def save_detectors(detectors: list[FailedBreakdownDetector],
                   path: Path = STATE_PATH) -> None:
    """Persiste el estado de los detectores en JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"detectors": [d.to_dict() for d in detectors]}
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_detectors(path: Path = STATE_PATH) -> list[FailedBreakdownDetector]:
    """Carga detectores desde JSON. Retorna lista vacía si no existe."""
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [FailedBreakdownDetector.from_dict(d) for d in data.get("detectors", [])]
