"""
Cliente TastyTrade SDK para el pipeline pre-market.

Encapsula autenticación y acceso a datos de mercado via API REST y streaming
DXLink. Diseñado para ser llamado desde scripts Python autónomos (sin Claude).

Requiere en .env:
    TT_USERNAME = usuario de TastyTrade
    TT_PASSWORD = contraseña de TastyTrade

Dependencias: tastytrade>=9.0, python-dotenv>=1.0
"""

import asyncio
import os

from dotenv import load_dotenv
from tastytrade import DXLinkStreamer, Session
from tastytrade.dxfeed import Quote
from tastytrade.instruments import Future


class TastyTradeClient:
    """
    Gestiona la sesión y el acceso a datos de mercado de TastyTrade.

    Uso:
        client = TastyTradeClient()
        quote = client.get_future_quote('/ES')
    """

    def __init__(self):
        """
        Carga credenciales de .env e inicia sesión con TastyTrade.

        Raises:
            EnvironmentError: si TT_USERNAME o TT_PASSWORD no están en .env
            Exception: si la autenticación con TastyTrade falla
        """
        load_dotenv()
        username = os.getenv("TT_USERNAME")
        password = os.getenv("TT_PASSWORD")
        if not username or not password:
            raise EnvironmentError(
                "TT_USERNAME y TT_PASSWORD deben estar definidos en .env"
            )
        self.session = Session(username, password)

    def get_future_quote(self, symbol: str) -> dict:
        """
        Devuelve el precio actual del futuro front-month para el símbolo raíz.

        Obtiene el contrato activo front-month via API REST, luego recupera
        bid/ask via DXLink streaming (una sola lectura). El mark (bid+ask)/2
        es el precio principal en premarket cuando no hay trades activos.

        Args:
            symbol: símbolo raíz del futuro, ej. '/ES'

        Returns:
            {
                "symbol":  str,    # contrato resuelto, ej. "/ESM5:XCME"
                "last":    float,  # 0.0 (no se suscribe a Trade en premarket)
                "mark":    float,  # (bid + ask) / 2
                "bid":     float,
                "ask":     float,
                "status":  str,    # "OK" | "ERROR" | "MISSING_DATA"
            }
        """
        result = {
            "symbol": symbol,
            "last": 0.0,
            "mark": 0.0,
            "bid": 0.0,
            "ask": 0.0,
            "status": "MISSING_DATA",
        }

        try:
            # Resolver contrato front-month activo via REST
            streamer_symbol = asyncio.run(self._resolve_streamer_symbol(symbol))
            if not streamer_symbol:
                return result

            # Obtener quote (bid/ask) via DXLink streaming
            quote = asyncio.run(self._fetch_quote(streamer_symbol))

            bid = float(quote.bid_price or 0)
            ask = float(quote.ask_price or 0)
            mark = round((bid + ask) / 2, 2) if bid and ask else 0.0

            result.update({
                "symbol": streamer_symbol,
                "last": 0.0,  # Trade no disponible en premarket
                "mark": mark,
                "bid": bid,
                "ask": ask,
                "status": "OK",
            })

        except EnvironmentError:
            raise  # propagar para que fetch_es_quote() la capture
        except Exception:
            result["status"] = "ERROR"

        return result

    # ------------------------------------------------------------------
    # Métodos privados async
    # ------------------------------------------------------------------

    async def _resolve_streamer_symbol(self, product_code: str) -> str | None:
        """
        Obtiene el streamer_symbol del contrato front-month activo.
        Ej: '/ES' → '/ESM5:XCME'
        """
        futures = await Future.get(self.session, product_codes=[product_code])
        if not futures:
            return None

        # Front-month: active=True y active_month=True
        front = next(
            (f for f in futures if f.active and f.active_month),
            None,
        )
        if front is None:
            # Fallback: primer contrato activo si no hay active_month marcado
            front = next((f for f in futures if f.active), None)

        return front.streamer_symbol if front else None

    async def _fetch_quote(self, streamer_symbol: str) -> Quote:
        """
        Suscribe al símbolo en DXLink y devuelve la primera Quote recibida.
        Timeout de 10 segundos para evitar bloqueos.
        """
        async with DXLinkStreamer(self.session) as streamer:
            await streamer.subscribe(Quote, [streamer_symbol])
            quote = await asyncio.wait_for(
                streamer.get_event(Quote),
                timeout=10.0,
            )
            return quote
