import yfinance as yf
from datetime import date, datetime

try:
    from tastytrade_client import TastyTradeClient
except ImportError:
    TastyTradeClient = None  # SDK no instalado o script ejecutado fuera de scripts/


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


if __name__ == "__main__":
    import json
    from pathlib import Path

    out = Path("outputs")
    out.mkdir(exist_ok=True)

    vix_data = fetch_vix_term_structure()
    vix_data["vix_history"] = fetch_vix_history()
    es_prev_data = fetch_es_prev_close()
    es_data = fetch_es_quote()

    data = {**vix_data, **es_prev_data, **es_data}
    data["fecha"] = vix_data.get("fecha") or str(date.today())

    (out / "data.json").write_text(json.dumps(data, indent=2))
    print(f"[fetch] status={data['status']} fecha={data['fecha']} "
          f"vix_history={vix_data['vix_history']['status']}")
