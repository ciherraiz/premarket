"""
Gestión del ciclo de vida de trades para la estrategia Mancini.

Implementa las reglas de Mancini:
- Entry al confirmarse SIGNAL
- Stop debajo del breakdown low (máx 15 pts)
- Parcial 50% en Target 1, stop a breakeven
- Runner busca Target 2+ con riesgo cero
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
                   timestamp: str | None = None) -> Trade | None:
        """
        Abre un nuevo trade.

        Args:
            direction: "LONG" o "SHORT"
            entry_price: precio de entrada
            breakdown_low: mínimo alcanzado durante el breakdown
            targets: lista de niveles objetivo
            timestamp: ISO timestamp (auto si None)

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

        trade = Trade(
            id=str(uuid.uuid4()),
            direction=direction,
            entry_price=entry_price,
            entry_time=ts,
            stop_price=stop,
            targets=sorted_targets,
            breakdown_low=breakdown_low,
        )
        self.trades.append(trade)
        return trade

    def process_tick(self, price: float,
                     timestamp: str | None = None) -> list[dict]:
        """
        Procesa un tick para el trade activo.

        Returns:
            Lista de eventos generados (puede estar vacía).
            Cada evento: {"type": str, "trade_id": str, ...}
        """
        trade = self.active_trade()
        if trade is None:
            return []

        ts = timestamp or datetime.now(timezone.utc).isoformat()
        events = []

        if trade.direction == "LONG":
            events = self._process_long(trade, price, ts)
        else:
            events = self._process_short(trade, price, ts)

        return events

    def close_eod(self, price: float,
                  timestamp: str | None = None) -> dict | None:
        """Cierra el trade activo por fin de jornada (EOD)."""
        trade = self.active_trade()
        if trade is None:
            return None

        ts = timestamp or datetime.now(timezone.utc).isoformat()
        return self._close_trade(trade, price, ts, ExitReason.EOD)

    def _process_long(self, trade: Trade, price: float,
                      ts: str) -> list[dict]:
        events = []

        # Check stop
        effective_stop = trade.runner_stop if trade.status == TradeStatus.PARTIAL else trade.stop_price
        if price <= effective_stop:
            reason = ExitReason.RUNNER_STOP if trade.status == TradeStatus.PARTIAL else ExitReason.STOP
            events.append(self._close_trade(trade, price, ts, reason))
            return events

        # Check targets
        if trade.status == TradeStatus.OPEN and trade.targets:
            if price >= trade.targets[0]:
                if len(trade.targets) == 1:
                    events.append(self._close_trade(trade, price, ts, ExitReason.TARGET_1))
                else:
                    events.append(self._partial_exit(trade, price, ts))

        if trade.status == TradeStatus.PARTIAL and len(trade.targets) > 1:
            if price >= trade.targets[1]:
                events.append(self._close_trade(trade, price, ts, ExitReason.TARGET_2))

        return events

    def _process_short(self, trade: Trade, price: float,
                       ts: str) -> list[dict]:
        events = []

        # Check stop (para short, stop es ARRIBA)
        effective_stop = trade.runner_stop if trade.status == TradeStatus.PARTIAL else trade.stop_price
        if price >= effective_stop:
            reason = ExitReason.RUNNER_STOP if trade.status == TradeStatus.PARTIAL else ExitReason.STOP
            events.append(self._close_trade(trade, price, ts, reason))
            return events

        # Check targets (para short, targets descendentes: [6800, 6790])
        if trade.status == TradeStatus.OPEN and trade.targets:
            if price <= trade.targets[0]:
                if len(trade.targets) == 1:
                    events.append(self._close_trade(trade, price, ts, ExitReason.TARGET_1))
                else:
                    events.append(self._partial_exit(trade, price, ts))

        if trade.status == TradeStatus.PARTIAL and len(trade.targets) > 1:
            if price <= trade.targets[1]:
                events.append(self._close_trade(trade, price, ts, ExitReason.TARGET_2))

        return events

    def _partial_exit(self, trade: Trade, price: float, ts: str) -> dict:
        """Salida parcial en Target 1. Stop a breakeven."""
        trade.status = TradeStatus.PARTIAL
        trade.partial_exit_price = price
        trade.partial_exit_time = ts
        trade.runner_stop = trade.entry_price  # breakeven
        trade.pnl_partial_pts = round(
            abs(price - trade.entry_price), 2
        )
        return {
            "type": "PARTIAL_EXIT",
            "trade_id": trade.id,
            "price": price,
            "pnl_partial_pts": trade.pnl_partial_pts,
            "runner_stop": trade.runner_stop,
            "timestamp": ts,
        }

    def _close_trade(self, trade: Trade, price: float, ts: str,
                     reason: str) -> dict:
        """Cierra completamente el trade."""
        trade.status = TradeStatus.CLOSED
        trade.exit_price = price
        trade.exit_time = ts
        trade.exit_reason = reason

        if trade.direction == "LONG":
            raw_pnl = price - trade.entry_price
        else:
            raw_pnl = trade.entry_price - price

        if trade.pnl_partial_pts is not None:
            # Runner P&L: desde entry hasta exit (solo mitad de posición)
            trade.pnl_runner_pts = round(raw_pnl, 2)
            # Total: promedio de parcial + runner
            trade.pnl_total_pts = round(
                (trade.pnl_partial_pts + trade.pnl_runner_pts) / 2, 2
            )
        else:
            trade.pnl_runner_pts = None
            trade.pnl_total_pts = round(raw_pnl, 2)

        return {
            "type": "TRADE_CLOSED",
            "trade_id": trade.id,
            "price": price,
            "reason": reason,
            "pnl_total_pts": trade.pnl_total_pts,
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
