import math
import pandas as pd

# ---------------------------------------------------------------------------
# Constantes configurables — Open Phase indicators
# ---------------------------------------------------------------------------

VWAP_THRESHOLD_PCT  = 0.10   # % mínimo de distancia al VWAP para señal direccional
VWAP_WINDOW_MINUTES = 30     # minutos esperados de ventana (para detección de incompletos)
VIX_DELTA_THRESHOLD = 0.5    # puntos VIX de diferencia para señal de volatilidad

RANGE_EXPANSION_LOW      = 0.6    # ratio < → EXPANSION_BAJA → score +1
RANGE_EXPANSION_HIGH     = 1.2    # ratio > → EXPANSION_ALTA → score -1
RANGE_EXP_WINDOW_MINUTES = 30     # ventana esperada (para detección de incompletos)
TRADING_MINUTES_DAY      = 390    # minutos de una jornada completa de trading

GAP_MIN_PCT      = 0.15   # % mínimo de gap para considerarlo significativo
GAP_MANTIENE_PCT = 25.0   # fill < 25 % → gap mantenido (momentum genuino)
GAP_NEUTRO_PCT   = 75.0   # fill >= 75 % → gap rellenado (señal neutralizada)


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


# ---------------------------------------------------------------------------
# IND-OPEN-04: Range Expansion
# ---------------------------------------------------------------------------

def calc_range_expansion(spx_intraday: dict, premarket_indicators: dict) -> dict:
    """
    Mide si el mercado ha consumido más o menos movimiento del que la IV predecía
    para la ventana post-open.

    ratio = OR_realized / expected_range
    OR_realized    = OR_high - OR_low  (puntos SPX)
    iv_daily_pts   = SPX_open × (VIX/100) / sqrt(252)
    expected_range = iv_daily_pts × sqrt(window_minutes / 390)

    Scoring:
        ratio < 0.6   → +1  EXPANSION_BAJA   (favorable para vender premium)
        0.6 ≤ ratio ≤ 1.2 →  0  NEUTRO
        ratio > 1.2   → -1  EXPANSION_ALTA   (alerta: mercado expandido)

    Input:
        spx_intraday        — dict de fetch_spx_intraday()
        premarket_indicators — sección "premarket" de indicators.json
    Output: dict con score (-1/0/+1), signal, ratio, or_realized, expected_range, status
    """
    base = {
        "or_high":           None,
        "or_low":            None,
        "or_realized":       None,
        "iv_daily_pts":      None,
        "expected_range":    None,
        "ratio":             None,
        "value":             None,
        "vix_used":          None,
        "spx_open":          None,
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

    required = {"High", "Low", "Close"}
    missing = required - set(df.columns)
    if missing:
        base["status"] = "ERROR"
        base["signal"] = "ERROR_COLUMNAS"
        return base

    window_minutes = spx_intraday.get("window_minutes", RANGE_EXP_WINDOW_MINUTES)
    n = len(df)
    base["candles_used"] = n

    if n < window_minutes * 0.5:
        base["incomplete_window"] = True

    # Leer VIX del premarket (fallback: vix_vxv_slope)
    vix = None
    ivr = (premarket_indicators or {}).get("ivr") or {}
    if ivr.get("vix") is not None:
        vix = ivr["vix"]
    else:
        slope = (premarket_indicators or {}).get("vix_vxv_slope") or {}
        vix = slope.get("vix")

    if vix is None:
        base["status"] = "ERROR"
        base["signal"] = "ERROR_IV_NO_DISPONIBLE"
        return base

    spx_open = spx_intraday.get("open_price")
    if spx_open is None:
        base["status"] = "ERROR"
        base["signal"] = "ERROR_SPX_OPEN_NULO"
        return base

    # Calcular OR realizado
    or_high = float(df["High"].max())
    or_low  = float(df["Low"].min())
    or_realized = or_high - or_low

    # Calcular rango esperado
    iv_daily_pts   = spx_open * (vix / 100) / math.sqrt(252)
    expected_range = iv_daily_pts * math.sqrt(window_minutes / TRADING_MINUTES_DAY)

    ratio = round(or_realized / expected_range, 4)

    base["or_high"]        = round(or_high, 2)
    base["or_low"]         = round(or_low, 2)
    base["or_realized"]    = round(or_realized, 2)
    base["iv_daily_pts"]   = round(iv_daily_pts, 4)
    base["expected_range"] = round(expected_range, 4)
    base["ratio"]          = ratio
    base["value"]          = ratio
    base["vix_used"]       = float(vix)
    base["spx_open"]       = float(spx_open)

    if ratio < RANGE_EXPANSION_LOW:
        base["score"]  = 1
        base["signal"] = "EXPANSION_BAJA"
    elif ratio > RANGE_EXPANSION_HIGH:
        base["score"]  = -1
        base["signal"] = "EXPANSION_ALTA"
    # else: score=0, signal="NEUTRO" (ya en base)

    return base


# ---------------------------------------------------------------------------
# IND-OPEN-05: Gap Behavior
# ---------------------------------------------------------------------------

def calc_gap_behavior(spx_intraday: dict, premarket_indicators: dict) -> dict:
    """
    Mide si el gap de apertura del SPX se está manteniendo o rellenando
    durante la ventana post-open.

    Fórmulas:
        gap_pts      = open_price - prev_close
        gap_pct      = gap_pts / prev_close * 100
        gap_fill_pct = (open_price - last_close) / gap_pts * 100

    Scoring (según dirección del gap):
        UP gap:   fill < 25 % → +2 GAP_ALCISTA_MANTENIDO
                  25 ≤ fill < 75 % → +1 GAP_ALCISTA_PARCIAL
                  fill >= 75 % → 0 GAP_ALCISTA_RELLENO
        DOWN gap: fill < 25 % → -2 GAP_BAJISTA_MANTENIDO
                  25 ≤ fill < 75 % → -1 GAP_BAJISTA_PARCIAL
                  fill >= 75 % → 0 GAP_BAJISTA_RELLENO
        |gap_pct| < 0.15 % → 0 GAP_INSIGNIFICANTE

    Dependencia inter-fase: requiere spx_prev_close en premarket_indicators.

    Input:
        spx_intraday        — dict de fetch_spx_intraday()
        premarket_indicators — sección "premarket" de indicators.json
    Output: dict con score, signal, gap_pct, gap_fill_pct, gap_direction, status
    """
    base = {
        "prev_close":    None,
        "open_price":    None,
        "last_close":    None,
        "gap_pct":       None,
        "gap_fill_pct":  None,
        "gap_direction": None,
        "value":         None,
        "candles_used":  0,
        "score":         0,
        "signal":        "NEUTRO",
        "status":        "OK",
        "fecha":         spx_intraday.get("fecha"),
    }

    # Validar prev_close (dependencia inter-fase)
    prev_close = (premarket_indicators or {}).get("spx_prev_close")
    if not prev_close:
        base["status"] = "ERROR"
        base["signal"] = "ERROR_PREV_CLOSE_NO_DISPONIBLE"
        return base

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

    open_price = spx_intraday.get("open_price")
    if open_price is None:
        base["status"] = "ERROR"
        base["signal"] = "ERROR_OPEN_PRICE_NULO"
        return base

    df = pd.DataFrame(records)
    if "Close" not in df.columns:
        base["status"] = "ERROR"
        base["signal"] = "ERROR_COLUMNAS"
        return base

    last_close = float(df["Close"].iloc[-1])
    n = len(df)
    base["candles_used"] = n
    base["prev_close"]   = float(prev_close)
    base["open_price"]   = float(open_price)
    base["last_close"]   = round(last_close, 2)

    # Calcular gap
    gap_pts = float(open_price) - float(prev_close)
    gap_pct = gap_pts / float(prev_close) * 100
    base["gap_pct"] = round(gap_pct, 4)
    base["value"]   = round(gap_pct, 4)

    # Gap insignificante → ruido
    if abs(gap_pct) < GAP_MIN_PCT:
        base["gap_direction"] = "NONE"
        base["signal"]        = "GAP_INSIGNIFICANTE"
        return base

    # Calcular relleno
    gap_fill_pct = (float(open_price) - last_close) / gap_pts * 100
    base["gap_fill_pct"] = round(gap_fill_pct, 4)

    if gap_pts > 0:
        base["gap_direction"] = "UP"
        if gap_fill_pct < GAP_MANTIENE_PCT:
            base["score"]  = 2
            base["signal"] = "GAP_ALCISTA_MANTENIDO"
        elif gap_fill_pct < GAP_NEUTRO_PCT:
            base["score"]  = 1
            base["signal"] = "GAP_ALCISTA_PARCIAL"
        else:
            base["score"]  = 0
            base["signal"] = "GAP_ALCISTA_RELLENO"
    else:
        base["gap_direction"] = "DOWN"
        if gap_fill_pct < GAP_MANTIENE_PCT:
            base["score"]  = -2
            base["signal"] = "GAP_BAJISTA_MANTENIDO"
        elif gap_fill_pct < GAP_NEUTRO_PCT:
            base["score"]  = -1
            base["signal"] = "GAP_BAJISTA_PARCIAL"
        else:
            base["score"]  = 0
            base["signal"] = "GAP_BAJISTA_RELLENO"

    return base
