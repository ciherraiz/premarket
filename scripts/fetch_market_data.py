import yfinance as yf
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

try:
    from tastytrade_client import TastyTradeClient
except ImportError:
    TastyTradeClient = None  # SDK no instalado o script ejecutado fuera de scripts/

# Número máximo de strikes a suscribir por vencimiento (duplicada de calculate_indicators)
GEX_MAX_STRIKES = 60


def fetch_vix_term_structure() -> dict:
    """
    Descarga VIX9D, VIX, VXV y VVIX de yfinance en una sola llamada.
    Devuelve el cierre más reciente disponible (últimos 5 días para cubrir festivos).
    """
    tickers = ["^VIX9D", "^VIX", "^VIX3M", "^VVIX"]
    key_map = {"^VIX9D": "vix9d", "^VIX": "vix", "^VIX3M": "vxv", "^VVIX": "vvix"}

    result = {k: None for k in key_map.values()}
    result["fecha"] = str(date.today())
    result["status"] = "OK"

    try:
        df = yf.download(tickers, period="5d", auto_adjust=True, progress=False)

        if df.empty:
            result["status"] = "MISSING_DATA"
            return result

        close = df["Close"]

        for ticker, key in key_map.items():
            col = ticker if ticker in close.columns else None
            if col is None:
                result["status"] = "MISSING_DATA"
                continue

            series = close[col].dropna()
            if series.empty:
                result["status"] = "MISSING_DATA"
                continue

            result[key] = round(float(series.iloc[-1]), 4)
            result["fecha"] = str(series.index[-1].date())

    except Exception:
        result["status"] = "ERROR"
        for k in key_map.values():
            result[k] = None

    return result


def fetch_vix_history() -> dict:
    """
    Descarga el historial diario de cierre del VIX del último año (≈ 252 días hábiles).
    Devuelve mínimo y máximo del periodo para calcular el IV Rank.
    """
    result = {
        "vix_min_52w": None,
        "vix_max_52w": None,
        "dias_disponibles": 0,
        "fecha": None,
        "status": "OK",
    }

    try:
        df = yf.download("^VIX", period="1y", auto_adjust=False, progress=False)

        if df.empty:
            result["status"] = "ERROR"
            return result

        close = df["Close"].dropna()

        if hasattr(close, "squeeze"):
            close = close.squeeze()

        dias = len(close)
        result["dias_disponibles"] = dias

        if dias < 50:
            result["status"] = "INSUFFICIENT_DATA"
            return result

        result["vix_min_52w"] = round(float(close.min()), 4)
        result["vix_max_52w"] = round(float(close.max()), 4)
        result["fecha"] = str(close.index[-1].date())

    except Exception:
        result["status"] = "ERROR"
        result["vix_min_52w"] = None
        result["vix_max_52w"] = None
        result["dias_disponibles"] = 0
        result["fecha"] = None

    return result


def fetch_spx_ohlcv(period_days: int = 35) -> dict:
    """
    Descarga el histórico OHLCV diario del SPX (^GSPC).
    Necesita al menos 30 barras para calcular el ATR Ratio (dos ventanas de 14 días).
    Se descargan 35 barras para tener margen ante festivos.

    Returns:
        {
            "ohlcv":   list[dict],  # registros con Open, High, Low, Close, Volume, Date
            "bars":    int,
            "fecha":   str,         # fecha del último bar, YYYY-MM-DD
            "status":  str,         # "OK" | "ERROR" | "INSUFFICIENT_DATA"
        }
    """
    result = {
        "ohlcv": None,
        "bars": 0,
        "fecha": None,
        "status": "OK",
    }

    try:
        df = yf.download("^GSPC", period=f"{period_days}d", auto_adjust=True, progress=False)

        if df.empty:
            result["status"] = "ERROR"
            return result

        # yfinance devuelve MultiIndex cuando se descarga un único ticker
        if isinstance(df.columns, __import__("pandas").MultiIndex):
            df.columns = df.columns.droplevel(1)
        df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()

        bars = len(df)
        result["bars"] = bars

        if bars < 30:
            result["status"] = "INSUFFICIENT_DATA"
            return result

        result["fecha"] = str(df.index[-1].date())
        records = []
        for idx, row in df.iterrows():
            records.append({
                "Date":   str(idx.date()),
                "Open":   round(float(row["Open"]), 2),
                "High":   round(float(row["High"]), 2),
                "Low":    round(float(row["Low"]), 2),
                "Close":  round(float(row["Close"]), 2),
                "Volume": int(row["Volume"]),
            })
        result["ohlcv"] = records

    except Exception:
        result["status"] = "ERROR"

    return result


def fetch_spx_intraday(window_minutes: int = 30) -> dict:
    """
    Descarga barras de 1 minuto del SPX (^GSPC) para la sesión actual.
    Filtra desde las 09:30 ET y devuelve las primeras window_minutes barras.

    Nota: yfinance aplica ~15 min de delay en datos intraday free-tier.
    Ejecutar este script window_minutes + 15 minutos después de la apertura.

    Returns:
        {
            "ohlcv":          list[dict],  # Datetime, Open, High, Low, Close, Volume
            "bars":           int,
            "window_minutes": int,
            "open_price":     float | None,  # Open de la primera barra (09:30 ET)
            "fecha":          str,
            "status":         str,   # "OK" | "ERROR" | "INSUFFICIENT_DATA"
        }
    """
    result = {
        "ohlcv": None,
        "bars": 0,
        "window_minutes": window_minutes,
        "open_price": None,
        "fecha": str(date.today()),
        "status": "OK",
    }

    try:
        df = yf.download("^GSPC", period="1d", interval="1m",
                         prepost=False, auto_adjust=True, progress=False)

        if df.empty:
            result["status"] = "INSUFFICIENT_DATA"
            return result

        # Normalizar MultiIndex de yfinance
        import pandas as pd
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()

        # Convertir índice a hora ET y filtrar desde 09:30
        et = ZoneInfo("America/New_York")
        df.index = df.index.tz_convert(et)
        open_time = time(9, 30)
        df = df[df.index.time >= open_time]

        # Validar que los datos son de hoy (no de una sesión anterior)
        today = date.today()
        df = df[df.index.date == today]

        # Tomar primeras window_minutes barras
        df = df.head(window_minutes)

        bars = len(df)
        result["bars"] = bars

        if bars == 0:
            result["status"] = "INSUFFICIENT_DATA"
            return result

        result["fecha"] = str(df.index[-1].date())

        records = []
        for idx, row in df.iterrows():
            records.append({
                "Datetime": str(idx),
                "Open":     round(float(row["Open"]), 2),
                "High":     round(float(row["High"]), 2),
                "Low":      round(float(row["Low"]), 2),
                "Close":    round(float(row["Close"]), 2),
                "Volume":   int(row["Volume"]),
            })
        result["ohlcv"] = records
        result["open_price"] = records[0]["Open"]

        if bars < window_minutes:
            result["status"] = "INSUFFICIENT_DATA"

    except Exception:
        result["status"] = "ERROR"

    return result


def fetch_es_prev_close() -> dict:
    """
    Descarga el cierre de la última sesión completada del futuro ES (ES=F) de yfinance.
    Excluye el día actual para garantizar que es un cierre definitivo, no intraday.
    Periodo de 5 días para cubrir festivos.
    """
    result = {
        "es_prev_close": None,
        "fecha": str(date.today()),
        "status": "OK",
    }

    try:
        df = yf.download("ES=F", period="5d", auto_adjust=True, progress=False)

        if df.empty:
            result["status"] = "MISSING_DATA"
            return result

        series = df["Close"].squeeze().dropna()
        if series.empty:
            result["status"] = "MISSING_DATA"
            return result

        # Excluir el día actual — solo cierres de sesiones completadas
        today = date.today()
        series = series[series.index.date < today]
        if series.empty:
            result["status"] = "MISSING_DATA"
            return result

        result["es_prev_close"] = round(float(series.iloc[-1]), 2)
        result["fecha"] = str(series.index[-1].date())

    except Exception:
        result["status"] = "ERROR"
        result["es_prev_close"] = None

    return result


def fetch_es_quote() -> dict:
    """
    Obtiene el precio actual del futuro /ES via SDK de TastyTrade.
    Usa mark (bid+ask)/2 como precio premarket, con fallback a last si > 0.
    Devuelve MISSING_DATA si las credenciales no están configuradas.
    """
    result = {
        "es_premarket": None,
        "fecha": str(date.today()),
        "status": "MISSING_DATA",
    }

    if TastyTradeClient is None:
        return result  # SDK no disponible

    try:
        client = TastyTradeClient()
        quote = client.get_future_quote("/ES")

        if quote["status"] != "OK":
            result["status"] = quote["status"]
            return result

        price = quote["last"] or quote["mark"]
        if not price or price == 0:
            result["status"] = "ERROR"
            return result

        result["es_premarket"] = round(float(price), 2)
        result["status"] = "OK"

    except EnvironmentError:
        result["status"] = "MISSING_DATA"  # credenciales no configuradas en .env
    except Exception:
        result["status"] = "ERROR"

    return result


def fetch_option_chain(
    symbol: str = "SPXW",
    days_ahead: int = 5,
    max_strikes: int = GEX_MAX_STRIKES,
    spot: float | None = None,
) -> dict:
    """
    Obtiene la cadena de opciones para hoy + los próximos days_ahead días naturales,
    limitada a max_strikes strikes ATM por vencimiento.

    Args:
        symbol:      símbolo de opciones (default "SPXW")
        days_ahead:  días naturales adicionales a hoy (default 5)
        max_strikes: strikes máximos por vencimiento, pasado a get_option_chain()
        spot:        precio de referencia para seleccionar strikes ATM

    Returns:
        {
            "contracts":   list[dict],
            "expiries":    list[str],
            "n_contracts": int,
            "max_strikes": int,
            "status":      str,   # "OK" | "ERROR" | "EMPTY_CHAIN"
        }
    """
    result = {
        "contracts":   [],
        "expiries":    [],
        "n_contracts": 0,
        "max_strikes": max_strikes,
        "status":      "EMPTY_CHAIN",
    }

    if TastyTradeClient is None:
        result["status"] = "MISSING_DATA"
        return result

    try:
        client = TastyTradeClient()
        today = date.today()
        all_contracts = []
        processed_expiries = []

        for i in range(days_ahead + 1):
            expiry_str = str(today + timedelta(days=i))
            contracts = client.get_option_chain(
                symbol,
                expiry=expiry_str,
                max_strikes=max_strikes,
                spot=spot,
            )
            if contracts:
                all_contracts.extend(contracts)
                processed_expiries.append(expiry_str)

        if not all_contracts:
            return result

        result["contracts"]   = all_contracts
        result["expiries"]    = processed_expiries
        result["n_contracts"] = len(all_contracts)
        result["status"]      = "OK"

    except EnvironmentError:
        result["status"] = "MISSING_DATA"
    except Exception:
        result["status"] = "ERROR"

    return result


if __name__ == "__main__":
    import json
    from pathlib import Path

    out = Path("outputs")
    out.mkdir(exist_ok=True)

    vix_data = fetch_vix_term_structure()
    vix_data["vix_history"] = fetch_vix_history()
    es_prev_data = fetch_es_prev_close()
    es_data = fetch_es_quote()
    spx_ohlcv_data = fetch_spx_ohlcv()

    # Extraer spot del último cierre del SPX para seleccionar strikes ATM
    spx_spot = None
    if spx_ohlcv_data.get("ohlcv"):
        spx_spot = spx_ohlcv_data["ohlcv"][-1]["Close"]

    chain_0dte  = fetch_option_chain(
        "SPXW", days_ahead=0, max_strikes=GEX_MAX_STRIKES, spot=spx_spot
    )
    chain_multi = fetch_option_chain(
        "SPXW", days_ahead=5, max_strikes=GEX_MAX_STRIKES, spot=spx_spot
    )

    data = {**vix_data, **es_prev_data, **es_data}
    data["spx_ohlcv"]          = spx_ohlcv_data
    data["spx_spot"]           = spx_spot
    data["option_chain_0dte"]  = chain_0dte
    data["option_chain_multi"] = chain_multi
    data["fecha"] = vix_data.get("fecha") or str(date.today())

    (out / "data.json").write_text(json.dumps(data, indent=2))
    print(f"[fetch] status={data['status']} fecha={data['fecha']} "
          f"vix_history={vix_data['vix_history']['status']} "
          f"spx_ohlcv={spx_ohlcv_data['status']}(bars={spx_ohlcv_data['bars']}) "
          f"chain_0dte={chain_0dte['status']}(n={chain_0dte['n_contracts']}) "
          f"chain_multi={chain_multi['status']}(n={chain_multi['n_contracts']})")
