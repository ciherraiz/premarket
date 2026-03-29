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


if __name__ == "__main__":
    import json
    from pathlib import Path

    data = json.loads(Path("outputs/data.json").read_text())

    slope = calc_vix_vxv_slope(data)
    ratio = calc_vix9d_vix_ratio(data)
    ivr   = calc_ivr(data, data.get("vix_history", {}))

    d_score = slope["score"] + ratio["score"]
    v_score = ivr["score"]

    indicators = {
        "fecha":           data.get("fecha"),
        "vix_vxv_slope":   slope,
        "vix9d_vix_ratio": ratio,
        "ivr":             ivr,
        "d_score":         d_score,
        "v_score":         v_score,
    }

    Path("outputs/indicators.json").write_text(json.dumps(indicators, indent=2))
    print(f"[calc] slope={slope['signal']}({slope['score']})  "
          f"ratio={ratio['signal']}({ratio['score']})  "
          f"ivr={ivr['signal']}({ivr['score']})  "
          f"D={d_score}  V={v_score}")
