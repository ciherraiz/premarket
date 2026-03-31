import pandas as pd

# ---------------------------------------------------------------------------
# Constantes configurables — Open Phase indicators
# ---------------------------------------------------------------------------

VWAP_THRESHOLD_PCT  = 0.10   # % mínimo de distancia al VWAP para señal direccional
VWAP_WINDOW_MINUTES = 30     # minutos esperados de ventana (para detección de incompletos)


# ---------------------------------------------------------------------------
# IND-OPEN-01: VWAP Position
# ---------------------------------------------------------------------------

def calc_vwap_position(spx_intraday: dict) -> dict:
    """
    Calcula la posición del precio del SPX respecto al VWAP de sesión.

    Input:  dict devuelto por fetch_spx_intraday()
    Output: dict con score (-1/0/+1), signal, vwap, close, vwap_distance_pct, status
    """
    base = {
        "vwap":              None,
        "close":             None,
        "vwap_distance_pct": None,
        "candles_used":      0,
        "incomplete_window": False,
        "score":             0,
        "signal":            "NEUTRO",
        "status":            "OK",
        "fecha":             spx_intraday.get("fecha"),
    }

    # Propagar error del fetch
    if spx_intraday.get("status") != "OK":
        base["status"] = "ERROR"
        base["signal"] = "ERROR_FETCH"
        return base

    records = spx_intraday.get("ohlcv") or []
    if not records:
        base["status"] = "ERROR"
        base["signal"] = "ERROR_SIN_DATOS"
        return base

    df = pd.DataFrame(records)

    required = {"High", "Low", "Close", "Volume"}
    missing = required - set(df.columns)
    if missing:
        base["status"] = "ERROR"
        base["signal"] = "ERROR_COLUMNAS"
        return base

    window_minutes = spx_intraday.get("window_minutes", VWAP_WINDOW_MINUTES)
    n = len(df)
    base["candles_used"] = n

    if n < window_minutes * 0.5:
        base["incomplete_window"] = True

    if df["Volume"].sum() == 0:
        base["status"] = "ERROR"
        base["signal"] = "ERROR_VOLUMEN_CERO"
        return base

    tp   = (df["High"] + df["Low"] + df["Close"]) / 3
    vwap = float((tp * df["Volume"]).sum() / df["Volume"].sum())
    close = float(df["Close"].iloc[-1])
    dist  = (close - vwap) / vwap * 100

    base["vwap"]              = round(vwap, 2)
    base["close"]             = round(close, 2)
    base["vwap_distance_pct"] = round(dist, 4)

    if dist > VWAP_THRESHOLD_PCT:
        base["score"]  = 1
        base["signal"] = "SESGO_ALCISTA"
    elif dist < -VWAP_THRESHOLD_PCT:
        base["score"]  = -1
        base["signal"] = "SESGO_BAJISTA"
    # else: score=0, signal="NEUTRO" (ya en base)

    return base
