"""
Cliente TastyTrade SDK para el pipeline pre-market.

Encapsula autenticación y acceso a datos de mercado via API REST y streaming
DXLink. Diseñado para ser llamado desde scripts Python autónomos (sin Claude).

Requiere en .env:
    TT_SECRET  = provider/client secret OAuth de TastyTrade
    TT_REFRESH = refresh token del usuario

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
        Carga tokens OAuth de .env e inicia sesión con TastyTrade.

        Requiere en .env:
            TT_SECRET   = provider/client secret de TastyTrade
            TT_REFRESH  = refresh token del usuario

        Raises:
            EnvironmentError: si TT_SECRET o TT_REFRESH no están en .env
        """
        load_dotenv()
        secret = os.getenv("TT_SECRET")
        refresh = os.getenv("TT_REFRESH")
        if not secret or not refresh:
            raise EnvironmentError(
                "TT_SECRET y TT_REFRESH deben estar definidos en .env"
            )
        self.session = Session(provider_secret=secret, refresh_token=refresh)

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
            quote_data = asyncio.run(self._resolve_and_fetch(symbol))
            if quote_data is None:
                return result  # MISSING_DATA: no se encontró contrato activo
            result.update(quote_data)

        except EnvironmentError:
            raise  # propagar para que fetch_es_quote() la capture
        except Exception:
            result["status"] = "ERROR"

        return result

    # ------------------------------------------------------------------
    # Métodos privados async
    # ------------------------------------------------------------------

    async def _resolve_and_fetch(self, product_code: str) -> dict | None:
        """
        Resuelve el contrato front-month y obtiene bid/ask en un solo contexto async.
        Devuelve None si no hay contrato activo.
        """
        code = product_code.lstrip('/')
        futures = await Future.get(self.session, product_codes=[code])
        if not futures:
            return None

        front = next((f for f in futures if f.active and f.active_month), None)
        if front is None:
            front = next((f for f in futures if f.active), None)
        if front is None:
            return None

        streamer_symbol = front.streamer_symbol
        async with DXLinkStreamer(self.session) as streamer:
            await streamer.subscribe(Quote, [streamer_symbol])
            quote = await asyncio.wait_for(
                streamer.get_event(Quote),
                timeout=10.0,
            )

        bid  = float(quote.bid_price or 0)
        ask  = float(quote.ask_price or 0)
        mark = round((bid + ask) / 2, 2) if bid and ask else 0.0

        return {
            "symbol": streamer_symbol,
            "last":   0.0,
            "mark":   mark,
            "bid":    bid,
            "ask":    ask,
            "status": "OK",
        }
