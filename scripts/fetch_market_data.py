import yfinance as yf
from datetime import date


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


if __name__ == "__main__":
    import json
    from pathlib import Path

    data = fetch_vix_term_structure()
    data["vix_history"] = fetch_vix_history()
    out = Path("outputs")
    out.mkdir(exist_ok=True)
    (out / "data.json").write_text(json.dumps(data, indent=2))
    print(f"[fetch] status={data['status']} fecha={data['fecha']} "
          f"vix_history={data['vix_history']['status']}")
