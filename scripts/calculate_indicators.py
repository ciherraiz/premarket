# ---------------------------------------------------------------------------
# Constantes configurables Net GEX
# ---------------------------------------------------------------------------
GEX_UMBRAL_FUERTE   = 15.0   # billions — long gamma fuerte (SPX tiene OI masivo)
GEX_UMBRAL_NEGATIVO  = 5.0   # billions — short gamma fuerte (valor absoluto)
GEX_MAX_STRIKES      = 60    # strikes máximos por vencimiento (±30 ATM)


def calc_vix_vxv_slope(vix_current: dict) -> dict:
    """
    Calcula el ratio VIX/VXV y asigna un score direccional.

    Tabla de scoring:
        ratio < 0.83            → +2  CONTANGO_FUERTE
        0.83 ≤ ratio < 0.90     → +1  CONTANGO_SUAVE
        0.90 ≤ ratio < 0.96     →  0  NEUTRO
        0.96 ≤ ratio < 1.00     → -1  TENSION
        ratio ≥ 1.00            → -2  BACKWARDATION
    """
    base = {
        "vix": None,
        "vxv": None,
        "ratio": None,
        "score": 0,
        "signal": None,
        "status": "OK",
        "fecha": vix_current.get("fecha"),
    }

    try:
        vix = vix_current.get("vix")
        vxv = vix_current.get("vxv")

        if vix is None or vxv is None:
            base["status"] = "MISSING_DATA"
            return base

        base["vix"] = vix
        base["vxv"] = vxv

        if vxv == 0:
            base["status"] = "ERROR"
            return base

        ratio = round(vix / vxv, 4)
        base["ratio"] = ratio

        if ratio < 0.83:
            base["score"] = 2
            base["signal"] = "CONTANGO_FUERTE"
        elif ratio < 0.90:
            base["score"] = 1
            base["signal"] = "CONTANGO_SUAVE"
        elif ratio < 0.96:
            base["score"] = 0
            base["signal"] = "NEUTRO"
        elif ratio < 1.00:
            base["score"] = -1
            base["signal"] = "TENSION"
        else:
            base["score"] = -2
            base["signal"] = "BACKWARDATION"

    except Exception:
        base["status"] = "ERROR"
        base["score"] = 0

    return base


def calc_vix9d_vix_ratio(vix_current: dict) -> dict:
    """
    Calcula el ratio VIX9D/VIX y asigna un score direccional.

    Tabla de scoring:
        ratio < 0.88            → +2  CONTANGO_FUERTE
        0.88 ≤ ratio < 1.02     →  0  NEUTRO
        1.02 ≤ ratio < 1.05     → -1  TENSION
        ratio ≥ 1.05            → -2  BACKWARDATION
    """
    base = {
        "vix9d": None,
        "vix": None,
        "ratio": None,
        "score": 0,
        "signal": None,
        "status": "OK",
        "fecha": vix_current.get("fecha"),
    }

    try:
        vix9d = vix_current.get("vix9d")
        vix = vix_current.get("vix")

        if vix9d is None or vix is None:
            base["status"] = "MISSING_DATA"
            return base

        base["vix9d"] = vix9d
        base["vix"] = vix

        if vix == 0:
            base["status"] = "ERROR"
            return base

        ratio = round(vix9d / vix, 4)
        base["ratio"] = ratio

        if ratio < 0.88:
            base["score"] = 2
            base["signal"] = "CONTANGO_FUERTE"
        elif ratio < 1.02:
            base["score"] = 0
            base["signal"] = "NEUTRO"
        elif ratio < 1.05:
            base["score"] = -1
            base["signal"] = "TENSION"
        else:
            base["score"] = -2
            base["signal"] = "BACKWARDATION"

    except Exception:
        base["status"] = "ERROR"
        base["score"] = 0

    return base


def calc_ivr(vix_current: dict, vix_history: dict) -> dict:
    """
    Calcula el IV Rank (IVR) del VIX y asigna un score de volatilidad.

    Fórmula:
        IVR = (VIX_hoy - VIX_mínimo_52w) / (VIX_máximo_52w - VIX_mínimo_52w) × 100

    Tabla de scoring:
        IVR > 60%            → +3  PRIMA_ALTA
        40% ≤ IVR ≤ 60%     → +2  PRIMA_ELEVADA
        25% ≤ IVR < 40%     → +1  PRIMA_NORMAL
        15% ≤ IVR < 25%     →  0  PRIMA_BAJA
        IVR < 15%            → -2  PRIMA_MUY_BAJA
    """
    base = {
        "vix": None,
        "vix_min_52w": None,
        "vix_max_52w": None,
        "ivr": None,
        "score": 0,
        "signal": None,
        "status": "OK",
        "fecha": vix_current.get("fecha"),
    }

    try:
        # Validate history status
        history_status = vix_history.get("status", "ERROR")
        if history_status == "INSUFFICIENT_DATA":
            base["status"] = "INSUFFICIENT_DATA"
            return base
        if history_status != "OK":
            base["status"] = "ERROR"
            return base

        vix = vix_current.get("vix")
        if vix is None:
            base["status"] = "MISSING_DATA"
            return base

        vix_min = vix_history.get("vix_min_52w")
        vix_max = vix_history.get("vix_max_52w")

        if vix_min is None or vix_max is None:
            base["status"] = "ERROR"
            return base

        base["vix"] = vix
        base["vix_min_52w"] = vix_min
        base["vix_max_52w"] = vix_max

        rango = vix_max - vix_min
        if rango == 0:
            base["status"] = "ERROR"
            return base

        dias = vix_history.get("dias_disponibles", 0)
        if dias < 50:
            base["status"] = "INSUFFICIENT_DATA"
            return base

        ivr = round((vix - vix_min) / rango * 100, 2)
        base["ivr"] = ivr

        if ivr > 60:
            base["score"] = 3
            base["signal"] = "PRIMA_ALTA"
        elif ivr >= 40:
            base["score"] = 2
            base["signal"] = "PRIMA_ELEVADA"
        elif ivr > 25:
            base["score"] = 1
            base["signal"] = "PRIMA_NORMAL"
        elif ivr >= 15:
            base["score"] = 0
            base["signal"] = "PRIMA_BAJA"
        else:
            base["score"] = -2
            base["signal"] = "PRIMA_MUY_BAJA"

    except Exception:
        base["status"] = "ERROR"
        base["score"] = 0

    return base


def calc_overnight_gap(es_prev_data: dict, es_data: dict) -> dict:
    """
    Calcula el gap entre el precio premarket del ES y el cierre de la sesión anterior del ES.
    Compara futuros contra futuros para eliminar el basis con el SPX.

    Tabla de scoring:
        gap_pct > +0.50%                  →  0  GAP_ALCISTA_GRANDE  (relleno probable)
        +0.10% ≤ gap_pct ≤ +0.50%        → +1  GAP_ALCISTA
        -0.10% < gap_pct < +0.10%         →  0  PLANO
        -0.50% ≤ gap_pct ≤ -0.10%        → -1  GAP_BAJISTA
        gap_pct < -0.50%                  →  0  GAP_BAJISTA_GRANDE  (relleno probable)
    """
    base = {
        "es_premarket": None,
        "es_prev_close": None,
        "gap_points": None,
        "gap_pct": None,
        "score": 0,
        "signal": None,
        "status": "OK",
        "fecha": es_data.get("fecha") or es_prev_data.get("fecha"),
    }

    try:
        es = es_data.get("es_premarket")
        es_prev = es_prev_data.get("es_prev_close")

        if es is None:
            base["status"] = "MISSING_DATA"
            return base
        if es_prev is None:
            base["status"] = "MISSING_DATA"
            return base

        if es == 0:
            base["status"] = "ERROR"
            return base
        if es_prev == 0:
            base["status"] = "ERROR"
            return base

        base["es_premarket"] = es
        base["es_prev_close"] = es_prev

        gap_points = round(es - es_prev, 2)
        gap_pct = round((es - es_prev) / es_prev * 100, 4)
        base["gap_points"] = gap_points
        base["gap_pct"] = gap_pct

        if gap_pct > 0.50:
            base["score"] = 0
            base["signal"] = "GAP_ALCISTA_GRANDE"
        elif gap_pct >= 0.10:
            base["score"] = 1
            base["signal"] = "GAP_ALCISTA"
        elif gap_pct > -0.10:
            base["score"] = 0
            base["signal"] = "PLANO"
        elif gap_pct >= -0.50:
            base["score"] = -1
            base["signal"] = "GAP_BAJISTA"
        else:
            base["score"] = 0
            base["signal"] = "GAP_BAJISTA_GRANDE"

    except Exception:
        base["status"] = "ERROR"
        base["score"] = 0

    return base


def calc_atr_ratio(spx_ohlcv_data: dict) -> dict:
    """
    Calcula el ATR Ratio comparando la volatilidad realizada reciente del SPX
    con la del periodo anterior para detectar expansión/contracción de rango.

    ATR_actual = media(True Range, días -1 a -14)
    ATR_lag    = media(True Range, días -15 a -28)
    ATR_ratio  = ATR_actual / ATR_lag

    Tabla de scoring:
        ratio < 0.80            → +2  CONTRACCION_FUERTE
        0.80 ≤ ratio < 0.92     → +1  CONTRACCION_SUAVE
        0.92 ≤ ratio ≤ 1.08     →  0  NEUTRO
        1.08 < ratio ≤ 1.20     → -1  EXPANSION_SUAVE
        ratio > 1.20            → -2  EXPANSION_FUERTE
    """
    base = {
        "atr_actual": None,
        "atr_lag": None,
        "atr_ratio": None,
        "score": 0,
        "signal": None,
        "status": "OK",
        "fecha": None,
    }

    try:
        status = spx_ohlcv_data.get("status", "ERROR")
        if status == "INSUFFICIENT_DATA":
            base["status"] = "INSUFFICIENT_DATA"
            return base
        if status != "OK":
            base["status"] = "ERROR"
            return base

        records = spx_ohlcv_data.get("ohlcv")
        if not records or len(records) < 30:
            base["status"] = "INSUFFICIENT_DATA"
            return base

        base["fecha"] = spx_ohlcv_data.get("fecha")

        # Calcular True Range para cada barra (necesita close anterior)
        tr_list = []
        for i in range(1, len(records)):
            high  = records[i]["High"]
            low   = records[i]["Low"]
            prev_close = records[i - 1]["Close"]
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr_list.append(tr)

        # tr_list[-1] = TR del último día, tr_list[-14] = TR del día -14
        if len(tr_list) < 28:
            base["status"] = "INSUFFICIENT_DATA"
            return base

        atr_actual = sum(tr_list[-14:]) / 14
        atr_lag    = sum(tr_list[-28:-14]) / 14

        base["atr_actual"] = round(atr_actual, 4)
        base["atr_lag"]    = round(atr_lag, 4)

        if atr_lag == 0:
            base["status"] = "ERROR"
            return base

        ratio = round(atr_actual / atr_lag, 4)
        base["atr_ratio"] = ratio

        if ratio < 0.80:
            base["score"] = 2
            base["signal"] = "CONTRACCION_FUERTE"
        elif ratio < 0.92:
            base["score"] = 1
            base["signal"] = "CONTRACCION_SUAVE"
        elif ratio <= 1.08:
            base["score"] = 0
            base["signal"] = "NEUTRO"
        elif ratio <= 1.20:
            base["score"] = -1
            base["signal"] = "EXPANSION_SUAVE"
        else:
            base["score"] = -2
            base["signal"] = "EXPANSION_FUERTE"

    except Exception:
        base["status"] = "ERROR"
        base["score"] = 0

    return base


def calc_net_gex(chain_0dte: dict, chain_multi: dict, spot: float, fecha: str) -> dict:
    """
    Calcula Net GEX, flip level, put/call wall y max pain.

    Args:
        chain_0dte:  fetch_option_chain(days_ahead=0) — niveles intraday (flip, walls, max_pain)
        chain_multi: fetch_option_chain(days_ahead=5) — régimen GEX total (net_gex_bn)
        spot:        precio del SPX (float o None)
        fecha:       fecha del análisis "YYYY-MM-DD"
    """
    base = {
        "net_gex_bn":  None,
        "score_gex":   0,
        "signal_gex":  None,
        "flip_level":  None,
        "score_flip":  0,
        "signal_flip": "SIN_FLIP",
        "put_wall":    None,
        "call_wall":   None,
        "max_pain":    None,
        "spot":        spot,
        "n_strikes":   0,
        "n_expiries":  0,
        "status":      "OK",
        "fecha":       fecha,
    }

    try:
        # Validar cadena multi (fuente del régimen GEX)
        multi_status    = chain_multi.get("status", "ERROR")
        multi_contracts = chain_multi.get("contracts", [])

        if multi_status in ("EMPTY_CHAIN", "MISSING_DATA") or not multi_contracts:
            base["status"] = multi_status if multi_status != "OK" else "EMPTY_CHAIN"
            return base

        if multi_status == "ERROR":
            base["status"] = "ERROR"
            return base

        if spot is None or spot <= 0:
            base["status"] = "MISSING_DATA"
            return base

        # --- Net GEX total (cadena multi-día) ---
        gex_all       = {}
        n_with_gamma  = 0
        expiries_seen = set()

        for c in multi_contracts:
            strike = float(c["strike"])
            otype  = c["option_type"]
            oi     = int(c.get("open_interest") or 0)
            gamma  = c.get("gamma")
            expiries_seen.add(c.get("expiry", ""))

            if not gamma or gamma <= 0:
                continue
            n_with_gamma += 1

            sign = 1 if otype == "C" else -1
            gex  = gamma * oi * 100 * spot * spot / 1_000_000_000 * sign
            gex_all[strike] = gex_all.get(strike, 0.0) + gex

        if n_with_gamma == 0:
            base["status"] = "ERROR"
            return base

        net_gex_bn = sum(gex_all.values())
        base["net_gex_bn"] = round(net_gex_bn, 4)
        base["n_expiries"] = len(expiries_seen)

        # Score GEX (IND-03) — umbrales asimétricos calibrados al OI del SPX
        if net_gex_bn > GEX_UMBRAL_FUERTE:
            base["score_gex"]  = 3
            base["signal_gex"] = "LONG_GAMMA_FUERTE"
        elif net_gex_bn > 0:
            base["score_gex"]  = 1
            base["signal_gex"] = "LONG_GAMMA_SUAVE"
        elif net_gex_bn >= -GEX_UMBRAL_NEGATIVO:
            base["score_gex"]  = -1
            base["signal_gex"] = "SHORT_GAMMA_SUAVE"
        else:
            base["score_gex"]  = -3
            base["signal_gex"] = "SHORT_GAMMA_FUERTE"

        # --- Niveles intraday (cadena 0DTE) ---
        dte_contracts = chain_0dte.get("contracts", [])
        gex_0dte  = {}
        oi_calls  = {}
        oi_puts   = {}

        for c in dte_contracts:
            strike = float(c["strike"])
            otype  = c["option_type"]
            oi     = int(c.get("open_interest") or 0)
            gamma  = c.get("gamma")

            if not gamma or gamma <= 0:
                continue

            sign = 1 if otype == "C" else -1
            gex  = gamma * oi * 100 * spot * spot / 1_000_000_000 * sign
            gex_0dte[strike] = gex_0dte.get(strike, 0.0) + gex

            if otype == "C":
                oi_calls[strike] = oi_calls.get(strike, 0) + oi
            else:
                oi_puts[strike]  = oi_puts.get(strike, 0) + oi

        base["n_strikes"] = len(gex_0dte)

        if gex_0dte:
            # Put Wall / Call Wall
            base["put_wall"]  = min(gex_0dte, key=gex_0dte.get)
            base["call_wall"] = max(gex_0dte, key=gex_0dte.get)

            # Flip Level (IND-04)
            strikes_sorted   = sorted(gex_0dte.keys())
            cumsum           = 0.0
            started_negative = False
            flip_level       = None
            for s in strikes_sorted:
                cumsum += gex_0dte[s]
                if cumsum < 0:
                    started_negative = True
                if started_negative and cumsum >= 0:
                    flip_level = s
                    break

            base["flip_level"] = flip_level
            if flip_level is None:
                base["score_flip"]  = 0
                base["signal_flip"] = "SIN_FLIP"
            elif spot > flip_level:
                base["score_flip"]  = 2
                base["signal_flip"] = "SOBRE_FLIP"
            else:
                base["score_flip"]  = -2
                base["signal_flip"] = "BAJO_FLIP"

        # Max Pain (cadena 0DTE)
        all_pain_strikes = set(oi_calls) | set(oi_puts)
        if all_pain_strikes:
            min_pain        = None
            max_pain_strike = None
            for candidate in sorted(all_pain_strikes):
                pain = sum(
                    max(candidate - s, 0) * oi * 100
                    for s, oi in oi_puts.items()
                ) + sum(
                    max(s - candidate, 0) * oi * 100
                    for s, oi in oi_calls.items()
                )
                if min_pain is None or pain < min_pain:
                    min_pain        = pain
                    max_pain_strike = candidate
            base["max_pain"] = max_pain_strike

    except Exception:
        base["status"]     = "ERROR"
        base["score_gex"]  = 0
        base["score_flip"] = 0

    return base


if __name__ == "__main__":
    import json
    from pathlib import Path

    data = json.loads(Path("outputs/data.json").read_text())

    slope     = calc_vix_vxv_slope(data)
    ratio     = calc_vix9d_vix_ratio(data)
    ivr       = calc_ivr(data, data.get("vix_history", {}))
    gap       = calc_overnight_gap(data, data)
    atr_ratio = calc_atr_ratio(data.get("spx_ohlcv", {}))
    net_gex   = calc_net_gex(
        chain_0dte=data.get("option_chain_0dte", {}),
        chain_multi=data.get("option_chain_multi", {}),
        spot=data.get("spx_spot"),
        fecha=data.get("fecha"),
    )

    d_score = (slope["score"] + ratio["score"] + gap["score"]
               + net_gex["score_gex"] + net_gex["score_flip"])
    v_score = ivr["score"] + atr_ratio["score"]

    indicators = {
        "fecha":           data.get("fecha"),
        "vix_vxv_slope":   slope,
        "vix9d_vix_ratio": ratio,
        "ivr":             ivr,
        "overnight_gap":   gap,
        "atr_ratio":       atr_ratio,
        "net_gex":         net_gex,
        "d_score":         d_score,
        "v_score":         v_score,
    }

    Path("outputs/indicators.json").write_text(json.dumps(indicators, indent=2))
    print(f"[calc] slope={slope['signal']}({slope['score']})  "
          f"ratio={ratio['signal']}({ratio['score']})  "
          f"gap={gap['signal']}({gap['score']})  "
          f"gex={net_gex['signal_gex']}({net_gex['score_gex']})  "
          f"flip={net_gex['signal_flip']}({net_gex['score_flip']})  "
          f"ivr={ivr['signal']}({ivr['score']})  "
          f"atr={atr_ratio['signal']}({atr_ratio['score']})  "
          f"D={d_score}  V={v_score}")
