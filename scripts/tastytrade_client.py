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
from datetime import date, timedelta

from dotenv import load_dotenv
from tastytrade import DXLinkStreamer, Session
from tastytrade.dxfeed import Greeks, Quote, Summary
from tastytrade.instruments import Future, NestedOptionChain


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

    def get_option_chain(
        self,
        symbol: str,
        expiry: str,
        max_strikes: int = 60,
        spot: float | None = None,
    ) -> list[dict]:
        """
        Devuelve la cadena de opciones para (symbol, expiry).

        Obtiene la estructura de strikes via NestedOptionChain (REST), selecciona
        los max_strikes más cercanos al spot y recupera Greeks + Summary via DXLink.

        Args:
            symbol:      ej. "SPXW"
            expiry:      fecha en formato "YYYY-MM-DD"
            max_strikes: número máximo de strikes a suscribir (default 60)
            spot:        precio de referencia para ordenar strikes por proximidad ATM

        Returns:
            lista de contratos [{strike, option_type, expiry, open_interest, gamma, iv}]
            Lista vacía si no hay datos para ese vencimiento.
        """
        try:
            return asyncio.run(
                self._fetch_option_chain_async(symbol, expiry, max_strikes, spot)
            )
        except EnvironmentError:
            raise
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Métodos privados async
    # ------------------------------------------------------------------

    async def _collect_events(self, streamer, event_class, symbols, timeout=30.0):
        """Recoge un evento por símbolo con timeout global."""
        collected = {}
        remaining = set(symbols)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout

        while remaining:
            time_left = deadline - loop.time()
            if time_left <= 0:
                break
            try:
                event = await asyncio.wait_for(
                    streamer.get_event(event_class),
                    timeout=min(5.0, time_left),
                )
                sym = event.event_symbol
                if sym in remaining:
                    collected[sym] = event
                    remaining.discard(sym)
            except asyncio.TimeoutError:
                break

        return collected

    async def _fetch_option_chain_async(
        self,
        symbol: str,
        expiry_str: str,
        max_strikes: int,
        spot: float | None,
    ) -> list[dict]:
        """Lógica async de get_option_chain."""
        target_date = date.fromisoformat(expiry_str)

        # 1. Obtener estructura de la cadena via REST
        chains = await NestedOptionChain.get(self.session, symbol)
        if not chains:
            return []

        chain = chains[0]

        # 2. Buscar el vencimiento objetivo
        expiration = next(
            (e for e in chain.expirations if e.expiration_date == target_date),
            None,
        )
        if expiration is None:
            return []

        # 3. Seleccionar strikes más cercanos al spot
        strikes = list(expiration.strikes)
        if spot and strikes:
            strikes.sort(key=lambda s: abs(float(s.strike_price) - spot))
        strikes = strikes[:max_strikes]

        if not strikes:
            return []

        # 4. Construir lista de (streamer_symbol, strike_price, option_type)
        contracts_meta = []
        all_syms = []
        for strike in strikes:
            sp = float(strike.strike_price)
            for sym, otype in [
                (strike.call_streamer_symbol, "C"),
                (strike.put_streamer_symbol, "P"),
            ]:
                if sym:
                    contracts_meta.append((sym, sp, otype))
                    all_syms.append(sym)

        if not all_syms:
            return []

        # 5. Suscribir a Greeks y Summary, recoger eventos
        async with DXLinkStreamer(self.session) as streamer:
            await streamer.subscribe(Greeks, all_syms)
            await streamer.subscribe(Summary, all_syms)
            greeks_by_sym = await self._collect_events(
                streamer, Greeks, all_syms, timeout=30.0
            )
            summary_by_sym = await self._collect_events(
                streamer, Summary, all_syms, timeout=30.0
            )

        # 6. Construir resultado
        result = []
        for streamer_sym, strike_price, option_type in contracts_meta:
            greek = greeks_by_sym.get(streamer_sym)
            summ = summary_by_sym.get(streamer_sym)

            gamma = None
            if greek is not None and greek.gamma is not None:
                g = float(greek.gamma)
                gamma = g if g > 0 else None

            iv = None
            if greek is not None and greek.volatility is not None:
                v = float(greek.volatility)
                iv = v if v > 0 else None

            oi = 0
            if summ is not None and summ.open_interest is not None:
                oi = int(summ.open_interest)

            result.append({
                "strike":        strike_price,
                "option_type":   option_type,
                "expiry":        expiry_str,
                "open_interest": oi,
                "gamma":         gamma,
                "iv":            iv,
            })

        return result

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
