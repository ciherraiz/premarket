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
