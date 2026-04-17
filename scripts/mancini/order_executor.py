"""
OrderExecutor — wrapper TastyTrade SDK para órdenes en /ES.

Envía órdenes de mercado (entry/close) y stop-loss (GTC) a TastyTrade.
Por defecto opera en dry-run: el SDK valida la orden sin ejecutarla.

Requiere sesión autenticada de TastyTrade (Session + Account).
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from decimal import Decimal

from tastytrade import Account, Session
from tastytrade.instruments import Future
from tastytrade.order import (
    Leg,
    NewOrder,
    OrderAction,
    OrderTimeInForce,
    OrderType,
    InstrumentType,
)


@dataclass
class OrderResult:
    """Resultado de enviar una orden a TastyTrade."""

    success: bool
    order_id: str | None
    dry_run: bool
    details: dict
    error: str | None

    def to_dict(self) -> dict:
        return asdict(self)


class OrderExecutor:
    """Lanza órdenes en /ES via TastyTrade SDK."""

    def __init__(self, session: Session, account: Account,
                 dry_run: bool = True, contracts: int = 1):
        self.session = session
        self.account = account
        self.dry_run = dry_run
        self.contracts = contracts

    def place_entry(self, direction: str, symbol: str) -> OrderResult:
        """Lanza orden de mercado para entrar en /ES.

        Args:
            direction: "LONG" o "SHORT"
            symbol: símbolo completo, ej. "/ESM6:XCME"
        """
        action = OrderAction.BUY if direction == "LONG" else OrderAction.SELL
        leg = Leg(
            instrument_type=InstrumentType.FUTURE,
            symbol=symbol,
            action=action,
            quantity=self.contracts,
        )
        order = NewOrder(
            time_in_force=OrderTimeInForce.DAY,
            order_type=OrderType.MARKET,
            legs=[leg],
        )
        return self._submit(order)

    def place_stop(self, direction: str, symbol: str,
                   stop_price: float) -> OrderResult:
        """Lanza orden stop-loss GTC.

        Args:
            direction: "LONG" o "SHORT" (stop inverso)
            symbol: símbolo completo
            stop_price: precio de activación del stop
        """
        # Stop para LONG = Sell, para SHORT = Buy
        action = OrderAction.SELL if direction == "LONG" else OrderAction.BUY
        leg = Leg(
            instrument_type=InstrumentType.FUTURE,
            symbol=symbol,
            action=action,
            quantity=self.contracts,
        )
        order = NewOrder(
            time_in_force=OrderTimeInForce.GTC,
            order_type=OrderType.STOP,
            stop_trigger=Decimal(str(stop_price)),
            legs=[leg],
        )
        return self._submit(order)

    def update_stop(self, order_id: str, new_stop: float) -> OrderResult:
        """Modifica el stop-loss existente (ej. trailing stop).

        Args:
            order_id: ID de la orden stop a modificar
            new_stop: nuevo precio de activación
        """
        try:
            response = self.account.replace_order(
                self.session,
                order_id,
                stop_trigger=Decimal(str(new_stop)),
            )
            return OrderResult(
                success=True,
                order_id=order_id,
                dry_run=False,
                details={"replaced": True},
                error=None,
            )
        except Exception as e:
            return OrderResult(
                success=False,
                order_id=order_id,
                dry_run=False,
                details={},
                error=str(e),
            )

    def close_position(self, direction: str, symbol: str) -> OrderResult:
        """Cierra posición con orden de mercado.

        Args:
            direction: "LONG" o "SHORT" (cierre inverso)
            symbol: símbolo completo
        """
        action = OrderAction.SELL if direction == "LONG" else OrderAction.BUY
        leg = Leg(
            instrument_type=InstrumentType.FUTURE,
            symbol=symbol,
            action=action,
            quantity=self.contracts,
        )
        order = NewOrder(
            time_in_force=OrderTimeInForce.DAY,
            order_type=OrderType.MARKET,
            legs=[leg],
        )
        return self._submit(order)

    def cancel_order(self, order_id: str) -> OrderResult:
        """Cancela una orden pendiente (ej. stop-loss al cerrar runner manual).

        Args:
            order_id: ID de la orden a cancelar
        """
        try:
            self.account.delete_order(self.session, order_id)
            return OrderResult(
                success=True,
                order_id=order_id,
                dry_run=False,
                details={"cancelled": True},
                error=None,
            )
        except Exception as e:
            return OrderResult(
                success=False,
                order_id=order_id,
                dry_run=False,
                details={},
                error=str(e),
            )

    def _submit(self, order: NewOrder) -> OrderResult:
        """Envía orden al SDK. dry_run=True por defecto."""
        try:
            response = self.account.place_order(
                self.session, order, dry_run=self.dry_run
            )
            return OrderResult(
                success=True,
                order_id=getattr(response, "id", None) if not self.dry_run else None,
                dry_run=self.dry_run,
                details=response.model_dump() if hasattr(response, "model_dump") else {},
                error=None,
            )
        except Exception as e:
            return OrderResult(
                success=False,
                order_id=None,
                dry_run=self.dry_run,
                details={},
                error=str(e),
            )
