import math

# ---------------------------------------------------------------------------
# Constantes configurables Net GEX
# ---------------------------------------------------------------------------
GEX_UMBRAL_FUERTE      = 5.0   # billions — long gamma fuerte (calibrado con datos reales)
GEX_UMBRAL_NEGATIVO    = 5.0   # billions — short gamma fuerte (valor absoluto)
GEX_MAX_STRIKES        = 60    # strikes máximos por vencimiento (±30 ATM)
GEX_WALL_PROXIMITY_PTS = 20    # puntos SPX para considerar "cerca" de una wall (IND-08)

# ---------------------------------------------------------------------------
# Constantes configurables Charm
# ---------------------------------------------------------------------------
CHARM_RF               = 0.05  # tipo libre de riesgo anual para cálculo charm


# ---------------------------------------------------------------------------
# Utilidad: cálculo analítico de charm (B-S)
# ---------------------------------------------------------------------------

def _calc_charm(
    spot: float,
    strike: float,
    iv: float,
    dte: int,
    option_type: str,
    r: float = CHARM_RF,
) -> float | None:
    """
    Charm: tasa de cambio del delta por día calendario que pasa.

    Retorna delta/día desde la perspectiva del dealer que gestiona el hedge:
      Positivo → el dealer compra S a medida que pasa el tiempo (presión alcista)
      Negativo → el dealer vende S a medida que pasa el tiempo (presión bajista)

    Fórmula Black-Scholes estándar. Para 0DTE usa T = 0.5/365 (media sesión)
    como floor para evitar singularidad.

    Returns None si algún input no es válido.
    """
    if iv is None or iv <= 0 or spot <= 0 or strike <= 0:
        return None
    T = max(dte / 365.0, 0.5 / 365.0)
    sqrt_T = math.sqrt(T)
    try:
        d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * T) / (iv * sqrt_T)
        d2 = d1 - iv * sqrt_T
        n_prime_d1 = math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi)
        # charm en delta/año; escalamos a delta/día al final
        raw = n_prime_d1 * (2.0 * r * T - d2 * iv * sqrt_T) / (2.0 * iv * T * sqrt_T)
        charm_per_day = raw / 365.0
        # Puts tienen charm opuesto a calls (misma magnitud, distinto signo de hedging)
        return charm_per_day if option_type == "C" else -charm_per_day
    except (ValueError, ZeroDivisionError, OverflowError):
        return None


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


def calc_net_gex(
    chain_0dte:  dict,
    chain_30dte: dict,
    spot:        float,
    fecha:       str,
    chain_7dte:  dict | None = None,
    # Compatibilidad retroactiva — chain_multi es alias de chain_30dte
    chain_multi: dict | None = None,
) -> dict:
    """
    Calcula Net GEX, flip level, put/call wall y max pain.

    Args:
        chain_0dte:  fetch_option_chain(max_dte=0) — niveles intraday (flip, walls, max_pain)
        chain_30dte: fetch_option_chain(max_dte=30) — régimen GEX total (net_gex_bn)
        spot:        precio del SPX (float o None)
        fecha:       fecha del análisis "YYYY-MM-DD"
        chain_7dte:  fetch_option_chain(max_dte=7) — bucket semanal (opcional)
        chain_multi: alias retroactivo de chain_30dte (deprecated)
    """
    # Compatibilidad retroactiva
    if chain_30dte is None and chain_multi is not None:
        chain_30dte = chain_multi
    if chain_30dte is None:
        chain_30dte = {}

    base = {
        "net_gex_bn":        None,
        "net_gex_by_dte":    {"0dte": None, "7dte": None, "30dte": None},
        "score_gex":         0,
        "signal_gex":        None,
        "flip_level":        None,
        "score_flip":        0,
        "signal_flip":       "SIN_FLIP",
        "put_wall":               None,
        "call_wall":              None,
        "expected_range_pts":     None,
        "score_wall_proximity":   0,
        "signal_wall_proximity":  "SIN_WALLS",
        "max_pain":               None,
        "control_node":           None,
        "chop_zone_low":          None,
        "chop_zone_high":         None,
        "gex_by_strike":          {},
        "gex_pct_by_strike":      {},
        "regime_text":            "Régimen GEX no disponible",
        "spot":              spot,
        "n_strikes":         0,
        "n_expiries":        0,
        "status":            "OK",
        "fecha":             fecha,
    }

    try:
        # Validar cadena 30dte (fuente del régimen GEX)
        multi_status    = chain_30dte.get("status", "ERROR")
        multi_contracts = chain_30dte.get("contracts", [])

        if multi_status in ("EMPTY_CHAIN", "MISSING_DATA") or not multi_contracts:
            base["status"] = multi_status if multi_status != "OK" else "EMPTY_CHAIN"
            return base

        if multi_status == "ERROR":
            base["status"] = "ERROR"
            return base

        if spot is None or spot <= 0:
            base["status"] = "MISSING_DATA"
            return base

        # --- Net GEX total (cadena 30dte) ---
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
            gex  = gamma * oi * spot * spot / 1_000_000_000 * sign
            gex_all[strike] = gex_all.get(strike, 0.0) + gex

        if n_with_gamma == 0:
            base["status"] = "ERROR"
            return base

        net_gex_bn = sum(gex_all.values())
        base["net_gex_bn"] = round(net_gex_bn, 4)
        base["n_expiries"] = len(expiries_seen)

        # --- Net GEX por bucket DTE ---
        def _sum_gex_bucket(contracts: list) -> float | None:
            """Suma el GEX neto de una lista de contratos."""
            total = 0.0
            found = False
            for c in contracts:
                g = c.get("gamma")
                oi = int(c.get("open_interest") or 0)
                if not g or g <= 0:
                    continue
                sign = 1 if c["option_type"] == "C" else -1
                total += g * oi * spot * spot / 1_000_000_000 * sign
                found = True
            return round(total, 4) if found else None

        base["net_gex_by_dte"]["30dte"] = round(net_gex_bn, 4)

        _c0 = chain_0dte.get("contracts", [])
        if _c0:
            base["net_gex_by_dte"]["0dte"] = _sum_gex_bucket(_c0)

        if chain_7dte:
            _c7 = chain_7dte.get("contracts", [])
            if _c7:
                base["net_gex_by_dte"]["7dte"] = _sum_gex_bucket(_c7)

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
            gex  = gamma * oi * spot * spot / 1_000_000_000 * sign
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

            # Expected session range
            base["expected_range_pts"] = round(base["call_wall"] - base["put_wall"], 1)

            # IND-08 Wall Proximity — sesgo según distancia spot a walls principales
            if spot:
                dist_call = base["call_wall"] - spot
                dist_put  = spot - base["put_wall"]
                if dist_call <= GEX_WALL_PROXIMITY_PTS:
                    base["score_wall_proximity"]  = -2
                    base["signal_wall_proximity"] = "CERCA_CALL_WALL"
                elif dist_put <= GEX_WALL_PROXIMITY_PTS:
                    base["score_wall_proximity"]  = 2
                    base["signal_wall_proximity"] = "CERCA_PUT_WALL"
                else:
                    base["score_wall_proximity"]  = 0
                    base["signal_wall_proximity"] = "ENTRE_WALLS"

            # Flip Level (IND-04) + Chop Zone
            # Cruce por strike individual: primer strike positivo tras una secuencia negativa.
            # Equivale a la frontera visual entre barras negativas y positivas en el perfil GEX.
            strikes_sorted   = sorted(gex_0dte.keys())
            flip_level       = None
            chop_zone_low    = None
            prev_negative    = False
            for s in strikes_sorted:
                if gex_0dte[s] < 0:
                    prev_negative = True
                    chop_zone_low = s
                elif prev_negative and gex_0dte[s] >= 0:
                    flip_level = s
                    break

            base["flip_level"]     = flip_level
            base["chop_zone_low"]  = chop_zone_low if flip_level is not None else None
            base["chop_zone_high"] = flip_level
            if flip_level is None:
                base["score_flip"]  = 0
                base["signal_flip"] = "SIN_FLIP"
            elif spot > flip_level:
                base["score_flip"]  = 2
                base["signal_flip"] = "SOBRE_FLIP"
            else:
                base["score_flip"]  = -2
                base["signal_flip"] = "BAJO_FLIP"

            # Control Node — strike de mayor concentración de GEX negativo (solo short gamma)
            if net_gex_bn < 0:
                base["control_node"] = min(gex_0dte, key=gex_0dte.get)

            # GEX absoluto y relativo por strike (0DTE)
            base["gex_by_strike"] = {
                str(int(k)): round(v, 6) for k, v in gex_0dte.items()
            }
            max_abs = max(abs(v) for v in gex_0dte.values())
            if max_abs > 0:
                base["gex_pct_by_strike"] = {
                    str(int(k)): round(v / max_abs * 100, 1)
                    for k, v in gex_0dte.items()
                }

        # Regime text
        _flip_str = f" bajo {base['flip_level']:.0f}" if base.get("flip_level") is not None else ""
        _regime_map = {
            "LONG_GAMMA_FUERTE":  "Dealers LONG gamma (fuerte) — sesión contenida, rebotes comprados",
            "LONG_GAMMA_SUAVE":   "Dealers LONG gamma — tendencia a mean-reversion, movimientos limitados",
            "SHORT_GAMMA_SUAVE":  f"Dealers SHORT gamma{_flip_str} — rebotes débiles, sin cobertura",
            "SHORT_GAMMA_FUERTE": f"Dealers SHORT gamma (fuerte){_flip_str} — caídas se aceleran",
        }
        base["regime_text"] = _regime_map.get(base.get("signal_gex"), "Régimen GEX no disponible")

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
        base["status"]              = "ERROR"
        base["score_gex"]           = 0
        base["score_flip"]          = 0
        base["score_wall_proximity"] = 0

    return base


# ---------------------------------------------------------------------------
# Constantes Fase 3
# ---------------------------------------------------------------------------
CHARM_SIGNAL_THRESHOLD = 50_000   # deltas/hora — umbral EXPANSIVO/SUPRESIVO
DEX_SCALE = 1_000_000_000         # escala a billions igual que GEX
CHARM_PIN_ATM_RANGE = 50          # ±50 pts del spot para buscar pin zone

# Horas de sesión ET para proyección intraday (09:30 – 15:30 cada 30 min)
_SESSION_HOURS = [
    "09:30", "10:00", "10:30", "11:00", "11:30",
    "12:00", "12:30", "13:00", "13:30", "14:00",
    "14:30", "15:00", "15:30",
]
# Tiempo restante hasta 16:00 ET para cada hora (en años)
_HOURS_TO_CLOSE = {
    "09:30": 6.5, "10:00": 6.0, "10:30": 5.5, "11:00": 5.0, "11:30": 4.5,
    "12:00": 4.0, "12:30": 3.5, "13:00": 3.0, "13:30": 2.5, "14:00": 2.0,
    "14:30": 1.5, "15:00": 1.0, "15:30": 0.5,
}
_TRADING_HOURS_PER_YEAR = 252 * 6.5   # horas de trading por año


def calc_charm_exposure(chain_0dte: dict, spot: float, fecha: str) -> dict:
    """
    Calcula la exposición charm por strike y el flujo charm total esperado
    durante la sesión del día.

    El charm mide cuánto delta pierden/ganan los contratos por el paso del
    tiempo sin que el precio se mueva. Multiplicado por el OI, da el flujo
    de hedging mecánico de los dealers.

    Args:
        chain_0dte: cadena de opciones 0DTE con delta e iv por contrato
        spot:       precio spot del SPX
        fecha:      YYYY-MM-DD

    Returns:
        {
            "charm_by_strike":     dict[str, float],
            "charm_total":         float | None,
            "charm_signal":        "EXPANSIVO" | "SUPRESIVO" | "NEUTRO",
            "charm_narrative":     str,
            "charm_pin_zone":      float | None,
            "charm_pin_zone_conf": "ALTA" | "MEDIA" | "BAJA",
            "charm_intraday":      list[dict],
            "status":              str,
            "fecha":               str,
        }
    """
    base: dict = {
        "charm_by_strike":     {},
        "charm_total":         None,
        "charm_signal":        "NEUTRO",
        "charm_narrative":     "Charm balanceado — sin sesgo direccional por tiempo",
        "charm_pin_zone":      None,
        "charm_pin_zone_conf": "BAJA",
        "charm_intraday":      [],
        "status":              "OK",
        "fecha":               fecha,
    }

    if not spot or spot <= 0:
        base["status"] = "MISSING_DATA"
        return base

    contracts = chain_0dte.get("contracts", [])
    if not contracts:
        base["status"] = chain_0dte.get("status", "EMPTY_CHAIN")
        return base

    try:
        # --- Charm exposure por strike (momento actual: 0DTE = DTE 0) ---
        # _calc_charm recibe dte=0 → usa T = 0.5/365 internamente como floor

        charm_by_strike: dict[float, float] = {}

        for c in contracts:
            strike = float(c["strike"])
            otype  = c["option_type"]
            oi     = int(c.get("open_interest") or 0)
            iv     = c.get("iv")
            dte_c  = int(c.get("dte") or 0)

            charm_val = _calc_charm(spot, strike, iv, dte_c, otype)
            if charm_val is None:
                continue

            # charm_exposure: deltas que los dealers deben comprar/vender por día por decay
            # (sign ya incluido por _calc_charm: calls→positivo, puts→negativo)
            exposure = charm_val * oi * 100
            charm_by_strike[strike] = charm_by_strike.get(strike, 0.0) + exposure

        if not charm_by_strike:
            base["status"] = "NO_IV_DATA"
            return base

        charm_total = sum(charm_by_strike.values())
        base["charm_by_strike"] = {
            str(int(k)): round(v, 2) for k, v in charm_by_strike.items()
        }
        base["charm_total"] = round(charm_total, 2)

        # --- Signal y narrativa ---
        if charm_total > CHARM_SIGNAL_THRESHOLD:
            base["charm_signal"] = "EXPANSIVO"
            base["charm_narrative"] = (
                f"Dealers comprando ~{charm_total / 1000:.0f}K delta/hora "
                "por decay — soporte mecánico intraday"
            )
        elif charm_total < -CHARM_SIGNAL_THRESHOLD:
            base["charm_signal"] = "SUPRESIVO"
            base["charm_narrative"] = (
                f"Dealers vendiendo ~{abs(charm_total) / 1000:.0f}K delta/hora "
                "por decay — presión bajista mecánica"
            )
        # else: NEUTRO ya está en base

        # --- Charm Pin Zone ---
        atm_strikes = {
            k: v for k, v in charm_by_strike.items()
            if abs(k - spot) <= CHARM_PIN_ATM_RANGE
        }
        if atm_strikes:
            pin_strike = max(atm_strikes, key=lambda k: abs(atm_strikes[k]))
            base["charm_pin_zone"] = pin_strike
            if charm_total != 0:
                ratio = abs(charm_by_strike[pin_strike]) / abs(charm_total)
                base["charm_pin_zone_conf"] = (
                    "ALTA"  if ratio > 0.4 else
                    "MEDIA" if ratio > 0.2 else
                    "BAJA"
                )

        # --- Proyección intraday ---
        # Para cada hora calculamos un DTE fraccional: horas restantes / 6.5 días de trading
        intraday = []
        for hora, hours_left in _HOURS_TO_CLOSE.items():
            # Convertir horas restantes a "días equivalentes de trading" para _calc_charm
            # _calc_charm usa max(dte/365, 0.5/365) internamente
            dte_frac = hours_left / 6.5   # fracción de un día de trading
            charm_h = 0.0
            has_data = False
            for c in contracts:
                strike = float(c["strike"])
                otype  = c["option_type"]
                oi     = int(c.get("open_interest") or 0)
                iv     = c.get("iv")
                # Pasamos dte_frac como "dte" — _calc_charm lo divide por 365
                ch = _calc_charm(spot, strike, iv, dte_frac, otype)
                if ch is None:
                    continue
                charm_h += ch * oi * 100
                has_data = True
            if has_data:
                if charm_h > CHARM_SIGNAL_THRESHOLD:
                    sig_h = "EXPANSIVO"
                elif charm_h < -CHARM_SIGNAL_THRESHOLD:
                    sig_h = "SUPRESIVO"
                else:
                    sig_h = "NEUTRO"
                intraday.append({
                    "hora":        hora,
                    "charm_delta": round(charm_h, 2),
                    "signal":      sig_h,
                })
        base["charm_intraday"] = intraday

    except Exception:
        base["status"] = "ERROR"

    return base


def calc_delta_exposure(chain_0dte: dict, spot: float, fecha: str) -> dict:
    """
    Calcula el Delta Exposure (DEX) por strike.

    El DEX agrega el delta neto por strike, mostrando dónde los dealers
    están largos o cortos en delta. Complementa el GEX: el GEX dice cuánto
    reajustan los dealers cuando el precio se mueve; el DEX dice en qué
    dirección están posicionados ahora mismo.

    Args:
        chain_0dte: cadena 0DTE con campo delta por contrato
        spot:       precio spot del SPX
        fecha:      YYYY-MM-DD

    Returns:
        {
            "dex_by_strike":     dict[str, float],  # DEX por strike (billions)
            "dex_cumulative":    dict[str, float],  # DEX acumulado de menor a mayor strike
            "dex_total":         float | None,
            "dex_flip":          float | None,      # strike donde DEX cum cruza cero
            "dex_positive_wall": float | None,      # strike con DEX más positivo
            "dex_negative_wall": float | None,      # strike con DEX más negativo
            "dex_signal":        str | None,
            "dex_narrative":     str,
            "status":            str,
            "fecha":             str,
        }
    """
    base: dict = {
        "dex_by_strike":     {},
        "dex_cumulative":    {},
        "dex_total":         None,
        "dex_flip":          None,
        "dex_positive_wall": None,
        "dex_negative_wall": None,
        "dex_signal":        None,
        "dex_narrative":     "",
        "status":            "OK",
        "fecha":             fecha,
    }

    if not spot or spot <= 0:
        base["status"] = "MISSING_DATA"
        return base

    contracts = chain_0dte.get("contracts", [])
    if not contracts:
        base["status"] = chain_0dte.get("status", "EMPTY_CHAIN")
        return base

    try:
        dex_by_strike: dict[float, float] = {}
        n_with_delta = 0

        for c in contracts:
            strike = float(c["strike"])
            otype  = c["option_type"]
            oi     = int(c.get("open_interest") or 0)
            delta  = c.get("delta")

            if delta is None:
                continue
            n_with_delta += 1

            # Delta ya viene firmado (calls > 0, puts < 0).
            # Sumamos directamente: puts contribuyen delta negativo (bajista),
            # calls contribuyen delta positivo (alcista).
            # No se aplica sign(otype) porque el signo ya está en delta.
            dex = float(delta) * oi * 100 * spot / DEX_SCALE
            dex_by_strike[strike] = dex_by_strike.get(strike, 0.0) + dex

        if n_with_delta == 0:
            base["status"] = "NO_DELTA_DATA"
            return base

        # Serializar
        base["dex_by_strike"] = {
            str(int(k)): round(v, 6) for k, v in dex_by_strike.items()
        }
        dex_total = sum(dex_by_strike.values())
        base["dex_total"] = round(dex_total, 4)

        # DEX acumulado (de strike más bajo a más alto)
        strikes_sorted = sorted(dex_by_strike.keys())
        cumulative = 0.0
        cum_dict: dict[float, float] = {}
        for s in strikes_sorted:
            cumulative += dex_by_strike[s]
            cum_dict[s] = cumulative
        base["dex_cumulative"] = {
            str(int(k)): round(v, 6) for k, v in cum_dict.items()
        }

        # DEX Flip — primer strike donde DEX acumulado cruza cero
        dex_flip = None
        prev_sign = None
        for s in strikes_sorted:
            curr_sign = 1 if cum_dict[s] >= 0 else -1
            if prev_sign is not None and curr_sign != prev_sign:
                dex_flip = s
                break
            prev_sign = curr_sign
        base["dex_flip"] = dex_flip

        # Walls
        if dex_by_strike:
            base["dex_positive_wall"] = max(dex_by_strike, key=dex_by_strike.get)
            base["dex_negative_wall"] = min(dex_by_strike, key=dex_by_strike.get)

        # Signal y narrativa
        if dex_total >= 0:
            base["dex_signal"]    = "DEALERS_LARGO_DELTA"
            flip_str = f" sobre {dex_flip:.0f}" if dex_flip else ""
            base["dex_narrative"] = (
                f"Dealers netos largos delta — soporte si precio baja{flip_str}"
            )
        else:
            base["dex_signal"]    = "DEALERS_CORTO_DELTA"
            flip_str = f" sobre {dex_flip:.0f}" if dex_flip else ""
            base["dex_narrative"] = (
                f"Dealers netos cortos delta — resistencia adicional{flip_str}"
            )

    except Exception:
        base["status"] = "ERROR"

    return base


def calc_pinning_zone(gex_result: dict, charm_result: dict, spot: float) -> dict:
    """
    Identifica el strike con mayor probabilidad de actuar como imán del precio.

    Combina GEX walls y Charm Pin Zone. Un strike es candidato si:
    1. Es Put Wall o Call Wall (alto GEX) dentro de ±100 pts del spot
    2. Y/O es Charm Pin Zone (alto charm ATM) dentro de ±50 pts del spot

    Args:
        gex_result:   output de calc_net_gex
        charm_result: output de calc_charm_exposure
        spot:         precio spot del SPX

    Returns:
        {
            "pinning_zone":       float | None,
            "pinning_conf":       "ALTA" | "MEDIA" | "BAJA" | "NINGUNA",
            "pinning_narrative":  str,
        }
    """
    base: dict = {
        "pinning_zone":      None,
        "pinning_conf":      "NINGUNA",
        "pinning_narrative": "No hay confluencia suficiente para identificar zona de pin.",
    }

    if not spot or spot <= 0:
        return base

    candidates: list[dict] = []

    # Candidatos GEX (put_wall y call_wall dentro de ±100 pts)
    for wall_key in ("call_wall", "put_wall"):
        wall = gex_result.get(wall_key)
        if wall and abs(wall - spot) <= 100:
            gex_0 = (gex_result.get("net_gex_by_dte") or {}).get("0dte") or 0
            score = abs(gex_0) * 0.6
            candidates.append({"strike": wall, "score": score, "source": "GEX_WALL"})

    # Candidato Charm Pin Zone (dentro de ±50 pts)
    cp = charm_result.get("charm_pin_zone")
    if cp and abs(cp - spot) <= 50:
        charm_total = charm_result.get("charm_total") or 0
        charm_score = abs(charm_total) / 100_000
        candidates.append({"strike": cp, "score": charm_score, "source": "CHARM"})

    if not candidates:
        return base

    # Elegir candidato con mayor score; detectar confluencia
    best = max(candidates, key=lambda x: x["score"])
    sources = {c["source"] for c in candidates if c["strike"] == best["strike"]}

    has_gex   = "GEX_WALL" in sources
    has_charm = "CHARM"    in sources

    # Detectar si GEX_WALL y CHARM coinciden en el mismo strike
    gex_strikes   = {c["strike"] for c in candidates if c["source"] == "GEX_WALL"}
    charm_strikes = {c["strike"] for c in candidates if c["source"] == "CHARM"}
    confluence = bool(gex_strikes & charm_strikes)

    if confluence or (has_gex and has_charm):
        conf = "ALTA"
    elif best["score"] > 1.0:
        conf = "MEDIA"
    else:
        conf = "BAJA"

    base["pinning_zone"] = best["strike"]
    base["pinning_conf"] = conf

    if conf == "ALTA":
        base["pinning_narrative"] = (
            f"{best['strike']:.0f} — confluencia GEX Wall + Charm máximo ATM. "
            "Imán de precio probable."
        )
    elif best["source"] == "GEX_WALL":
        base["pinning_narrative"] = (
            f"{best['strike']:.0f} — GEX Wall dominante. "
            "Pin probable si el spot se acerca."
        )
    else:
        base["pinning_narrative"] = (
            f"{best['strike']:.0f} — Charm máximo ATM. "
            "Atracción mecánica por decay 0DTE."
        )

    return base


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    from pathlib import Path

    data = json.loads(Path("outputs/data.json").read_text())

    slope     = calc_vix_vxv_slope(data)
    ratio     = calc_vix9d_vix_ratio(data)
    ivr       = calc_ivr(data, data.get("vix_history", {}))
    gap       = calc_overnight_gap(data, data)
    atr_ratio = calc_atr_ratio(data.get("spx_ohlcv", {}))
    spx_spot = data.get("spx_spot")
    fecha    = data.get("fecha")

    net_gex   = calc_net_gex(
        chain_0dte=data.get("option_chain_0dte", {}),
        chain_30dte=data.get("option_chain_30dte") or data.get("option_chain_multi", {}),
        chain_7dte=data.get("option_chain_7dte"),
        spot=spx_spot,
        fecha=fecha,
    )
    charm  = calc_charm_exposure(data.get("option_chain_0dte", {}), spx_spot, fecha)
    dex    = calc_delta_exposure(data.get("option_chain_0dte", {}), spx_spot, fecha)
    pin    = calc_pinning_zone(net_gex, charm, spx_spot)

    d_score = (slope["score"] + ratio["score"] + gap["score"]
               + net_gex["score_gex"] + net_gex["score_flip"]
               + net_gex["score_wall_proximity"])
    v_score = ivr["score"] + atr_ratio["score"]

    indicators = {
        "fecha":           fecha,
        "vix_vxv_slope":   slope,
        "vix9d_vix_ratio": ratio,
        "ivr":             ivr,
        "overnight_gap":   gap,
        "atr_ratio":       atr_ratio,
        "net_gex":         net_gex,
        "charm_exposure":  charm,
        "delta_exposure":  dex,
        "pinning_zone":    pin,
        "d_score":         d_score,
        "v_score":         v_score,
    }

    Path("outputs/indicators.json").write_text(json.dumps(indicators, indent=2))
    print(f"[calc] slope={slope['signal']}({slope['score']})  "
          f"ratio={ratio['signal']}({ratio['score']})  "
          f"gap={gap['signal']}({gap['score']})  "
          f"gex={net_gex['signal_gex']}({net_gex['score_gex']})  "
          f"flip={net_gex['signal_flip']}({net_gex['score_flip']})  "
          f"wall={net_gex['signal_wall_proximity']}({net_gex['score_wall_proximity']})  "
          f"ivr={ivr['signal']}({ivr['score']})  "
          f"atr={atr_ratio['signal']}({atr_ratio['score']})  "
          f"charm={charm['charm_signal']}  dex={dex['dex_signal']}  "
          f"pin={pin['pinning_zone']}({pin['pinning_conf']})  "
          f"D={d_score}  V={v_score}")
