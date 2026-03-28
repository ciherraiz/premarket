import yfinance as yf
from datetime import date


def fetch_vix_term_structure() -> dict:
    """
    Descarga VIX9D, VIX, VXV y VVIX de yfinance en una sola llamada.
    Devuelve el cierre más reciente disponible (últimos 5 días para cubrir festivos).
    """
    tickers = ["^VIX9D", "^VIX", "^VXV", "^VVIX"]
    key_map = {"^VIX9D": "vix9d", "^VIX": "vix", "^VXV": "vxv", "^VVIX": "vvix"}

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
