import pandas as pd

# ---------------------------------------------------------------------------
# Constantes configurables — Open Phase indicators
# ---------------------------------------------------------------------------

VWAP_THRESHOLD_PCT  = 0.10   # % mínimo de distancia al VWAP para señal direccional
VWAP_WINDOW_MINUTES = 30     # minutos esperados de ventana (para detección de incompletos)
VIX_DELTA_THRESHOLD = 0.5    # puntos VIX de diferencia para señal de volatilidad


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
    base["value"]             = round(dist, 4)   # alias para el scorecard combinado

    if dist > VWAP_THRESHOLD_PCT:
        base["score"]  = 1
        base["signal"] = "SESGO_ALCISTA"
    elif dist < -VWAP_THRESHOLD_PCT:
        base["score"]  = -1
        base["signal"] = "SESGO_BAJISTA"
    # else: score=0, signal="NEUTRO" (ya en base)

    return base


# ---------------------------------------------------------------------------
# IND-OPEN-02: VIX Delta Open
# ---------------------------------------------------------------------------

def calc_vix_delta_open(vix_intraday: dict) -> dict:
    """
    Mide cuánto se ha movido el VIX desde la apertura hasta el cierre de la ventana.

    Input:  dict devuelto por fetch_vix_intraday()
    Output: dict con score (-1/0/+1), signal, vix_open, vix_close, vix_delta, status
    """
    base = {
        "vix_open":          None,
        "vix_close":         None,
        "vix_delta":         None,
        "value":             None,
        "candles_used":      0,
        "incomplete_window": False,
        "score":             0,
        "signal":            "NEUTRO",
        "status":            "OK",
        "fecha":             vix_intraday.get("fecha"),
    }

    if vix_intraday.get("status") != "OK":
        base["status"] = "ERROR"
        base["signal"] = "ERROR_FETCH"
        return base

    records = vix_intraday.get("ohlcv") or []
    if not records:
        base["status"] = "ERROR"
        base["signal"] = "ERROR_SIN_DATOS"
        return base

    df = pd.DataFrame(records)

    required = {"Open", "Close"}
    if not required.issubset(df.columns):
        base["status"] = "ERROR"
        base["signal"] = "ERROR_COLUMNAS"
        return base

    window_minutes = vix_intraday.get("window_minutes", VWAP_WINDOW_MINUTES)
    n = len(df)
    base["candles_used"] = n

    if n < window_minutes * 0.5:
        base["incomplete_window"] = True

    vix_open  = float(df["Open"].iloc[0])
    vix_close = float(df["Close"].iloc[-1])
    delta     = round(vix_close - vix_open, 2)

    base["vix_open"]  = round(vix_open,  2)
    base["vix_close"] = round(vix_close, 2)
    base["vix_delta"] = delta
    base["value"]     = delta

    if delta < -VIX_DELTA_THRESHOLD:
        base["score"]  = 1
        base["signal"] = "IV_COMPRIMIENDO"
    elif delta > VIX_DELTA_THRESHOLD:
        base["score"]  = -1
        base["signal"] = "IV_EXPANDIENDO"

    return base
