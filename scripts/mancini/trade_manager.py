"""
Gestión del ciclo de vida de trades para la estrategia Mancini.

Implementa las reglas de Mancini:
- Entry al confirmarse SIGNAL
- Stop debajo del breakdown low (máx 15 pts)
- Trailing stop: un target por detrás
  - T1 alcanzado → stop a breakeven (entry_price)
  - T2 alcanzado → stop a T1
  - TN alcanzado → stop a T(N-1)
- Con 1 contrato: sin salida parcial, todo es runner
- Runner sobrevive overnight (sin cierre EOD automático)
- Máx 3 trades/día, objetivo 10-15 pts
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


# ── Constantes ──────────────────────────────────────────────────────
MAX_STOP_PTS = 15       # Stop máximo en puntos
STOP_BUFFER_PTS = 2     # Puntos adicionales bajo el breakdown low
MAX_TRADES_PER_DAY = 3  # Máximo de trades por jornada


class TradeStatus:
    OPEN = "OPEN"
    PARTIAL = "PARTIAL"
    CLOSED = "CLOSED"


class ExitReason:
    TARGET_1 = "TARGET_1"
    TARGET_2 = "TARGET_2"
    STOP = "STOP"
    RUNNER_STOP = "RUNNER_STOP"
    EOD = "EOD"
    MANUAL = "MANUAL"


@dataclass
class Trade:
    """Representa un trade completo con su ciclo de vida."""

    id: str
    direction: str  # "LONG" | "SHORT"
    entry_price: float
    entry_time: str
    stop_price: float
    targets: list[float]
    status: str = TradeStatus.OPEN
    partial_exit_price: float | None = None
    partial_exit_time: str | None = None
    runner_stop: float | None = None
    exit_price: float | None = None
    exit_time: str | None = None
    exit_reason: str | None = None
    pnl_partial_pts: float | None = None
    pnl_runner_pts: float | None = None
    pnl_total_pts: float | None = None
    breakdown_low: float | None = None
    alignment: str = ""  # "ALIGNED" | "NEUTRAL" | "MISALIGNED"
    # Trailing stop
    targets_hit: int = 0  # número de targets alcanzados
    mfe_pts: float = 0.0  # Maximum Favorable Excursion en puntos
    # Órdenes TastyTrade
    entry_order_id: str | None = None
    stop_order_id: str | None = None
    gate_decision: dict | None = None  # {execute, reasoning, risk_factors}
    execution_mode: str = ""  # "auto" | "manual_confirm" | "rejected"
    dry_run: bool = True  # True = órdenes dry-run, False = live

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Trade:
        return cls(**d)


@dataclass
class TradeManager:
    """Gestiona trades activos y aplica las reglas de Mancini."""

    trades: list[Trade] = field(default_factory=list)
    fecha: str = ""

    def trades_today(self) -> int:
        return len(self.trades)

    def can_open_trade(self) -> bool:
        return self.trades_today() < MAX_TRADES_PER_DAY

    def active_trade(self) -> Trade | None:
        """Retorna el trade abierto/parcial si existe."""
        for t in self.trades:
            if t.status in (TradeStatus.OPEN, TradeStatus.PARTIAL):
                return t
        return None

    def open_trade(self, direction: str, entry_price: float,
                   breakdown_low: float, targets: list[float],
                   timestamp: str | None = None,
                   alignment: str = "",
                   dry_run: bool = True) -> Trade | None:
        """
        Abre un nuevo trade.

        Args:
            direction: "LONG" o "SHORT"
            entry_price: precio de entrada
            breakdown_low: mínimo alcanzado durante el breakdown
            targets: lista de niveles objetivo
            timestamp: ISO timestamp (auto si None)
            alignment: "ALIGNED", "NEUTRAL" o "MISALIGNED"

        Returns:
            Trade creado, o None si no se puede abrir.
        """
        if not self.can_open_trade():
            return None
        if self.active_trade() is not None:
            return None

        ts = timestamp or datetime.now(timezone.utc).isoformat()
        stop = calc_stop(direction, entry_price, breakdown_low)

        # LONG: targets ascendentes (primero el más cercano arriba)
        # SHORT: targets descendentes (primero el más cercano abajo)
        sorted_targets = sorted(targets, reverse=(direction == "SHORT"))

        # MISALIGNED: solo Target 1 (trailing stop sin extended targets)
        if alignment == "MISALIGNED" and sorted_targets:
            sorted_targets = [sorted_targets[0]]

        trade = Trade(
            id=str(uuid.uuid4()),
            direction=direction,
            entry_price=entry_price,
            entry_time=ts,
            stop_price=stop,
            targets=sorted_targets,
            breakdown_low=breakdown_low,
            alignment=alignment,
            dry_run=dry_run,
        )
        self.trades.append(trade)
        return trade

    def process_tick(self, price: float,
                     timestamp: str | None = None) -> list[dict]:
        """
        Procesa un tick para el trade activo.

        Con 1 contrato: trailing stop sin salida parcial.
        - T1 → stop a breakeven (entry_price)
        - T2 → stop a T1
        - TN → stop a T(N-1)
        El trade se cierra solo cuando el stop se toca.

        Returns:
            Lista de eventos generados (puede estar vacía).
            Cada evento: {"type": str, "trade_id": str, ...}
        """
        trade = self.active_trade()
        if trade is None:
            return []

        ts = timestamp or datetime.now(timezone.utc).isoformat()
        events = []

        # Actualizar MFE
        pnl = (price - trade.entry_price if trade.direction == "LONG"
               else trade.entry_price - price)
        if pnl > trade.mfe_pts:
            trade.mfe_pts = round(pnl, 2)

        # Check stop
        if self._is_stop_hit(trade, price):
            reason = ExitReason.STOP
            events.append(self._close_trade(trade, price, ts, reason))
            return events

        # Check targets — trailing stop, NO cierre parcial
        events.extend(self._check_targets(trade, price, ts))

        return events

    def close_eod(self, price: float,
                  timestamp: str | None = None) -> dict | None:
        """Cierra el trade activo por fin de jornada (EOD).

        NOTA: Con la política de runners overnight, este método
        solo se usa para cierre manual, NO automático a las 16:00.
        """
        trade = self.active_trade()
        if trade is None:
            return None

        ts = timestamp or datetime.now(timezone.utc).isoformat()
        return self._close_trade(trade, price, ts, ExitReason.EOD)

    def close_manual(self, price: float,
                     timestamp: str | None = None) -> dict | None:
        """Cierra el trade activo manualmente (via Telegram)."""
        trade = self.active_trade()
        if trade is None:
            return None

        ts = timestamp or datetime.now(timezone.utc).isoformat()
        return self._close_trade(trade, price, ts, ExitReason.MANUAL)

    def _is_stop_hit(self, trade: Trade, price: float) -> bool:
        """Comprueba si el precio ha tocado el stop."""
        if trade.direction == "LONG":
            return price <= trade.stop_price
        else:
            return price >= trade.stop_price

    def _check_targets(self, trade: Trade, price: float,
                       ts: str) -> list[dict]:
        """Comprueba targets y aplica trailing stop.

        Con 1 contrato, NO hay salida parcial. Solo se mueve el stop.
        """
        events = []

        for i, target in enumerate(trade.targets):
            if trade.targets_hit >= i + 1:
                continue  # ya alcanzado

            target_hit = (
                (trade.direction == "LONG" and price >= target) or
                (trade.direction == "SHORT" and price <= target)
            )
            if not target_hit:
                break  # targets son secuenciales

            trade.targets_hit = i + 1

            # Trailing stop: un target por detrás
            if i == 0:
                new_stop = trade.entry_price  # breakeven
            else:
                new_stop = trade.targets[i - 1]  # target anterior

            old_stop = trade.stop_price
            trade.stop_price = new_stop

            events.append({
                "type": "TARGET_HIT",
                "trade_id": trade.id,
                "target_index": i,
                "target_price": target,
                "new_stop": new_stop,
                "old_stop": old_stop,
                "price": price,
                "timestamp": ts,
            })
            break  # un target por tick

        return events

    def _close_trade(self, trade: Trade, price: float, ts: str,
                     reason: str) -> dict:
        """Cierra completamente el trade (1 contrato, sin parcial)."""
        trade.status = TradeStatus.CLOSED
        trade.exit_price = price
        trade.exit_time = ts
        trade.exit_reason = reason

        if trade.direction == "LONG":
            raw_pnl = price - trade.entry_price
        else:
            raw_pnl = trade.entry_price - price

        trade.pnl_total_pts = round(raw_pnl, 2)

        return {
            "type": "TRADE_CLOSED",
            "trade_id": trade.id,
            "price": price,
            "reason": reason,
            "pnl_total_pts": trade.pnl_total_pts,
            "targets_hit": trade.targets_hit,
            "timestamp": ts,
        }

    def to_dict(self) -> dict:
        return {
            "fecha": self.fecha,
            "trades": [t.to_dict() for t in self.trades],
        }

    @classmethod
    def from_dict(cls, d: dict) -> TradeManager:
        tm = cls(fecha=d.get("fecha", ""))
        tm.trades = [Trade.from_dict(t) for t in d.get("trades", [])]
        return tm


def calc_stop(direction: str, entry_price: float,
              breakdown_low: float) -> float:
    """
    Calcula el stop-loss técnico.

    Para LONG: debajo del breakdown low, con buffer, máximo MAX_STOP_PTS.
    Para SHORT: encima del breakdown high, con buffer, máximo MAX_STOP_PTS.
    """
    if direction == "LONG":
        technical_stop = breakdown_low - STOP_BUFFER_PTS
        max_stop = entry_price - MAX_STOP_PTS
        return max(technical_stop, max_stop)
    else:
        technical_stop = breakdown_low + STOP_BUFFER_PTS
        max_stop = entry_price + MAX_STOP_PTS
        return min(technical_stop, max_stop)
