import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.calculate_indicators import calc_ivr


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_current(vix, fecha="2026-03-28"):
    return {"vix": vix, "fecha": fecha}


def _make_history(vix_min, vix_max, dias=252, status="OK"):
    return {
        "vix_min_52w": vix_min,
        "vix_max_52w": vix_max,
        "dias_disponibles": dias,
        "fecha": "2026-03-27",
        "status": status,
    }


# ---------------------------------------------------------------------------
# Tests de scoring normal (tabla de la spec)
# ---------------------------------------------------------------------------

def test_ivr_alto_prima_alta():
    """vix=28.0, min=10.0, max=35.0 → ivr=72.00, score=+3, signal=PRIMA_ALTA"""
    result = calc_ivr(_make_current(28.0), _make_history(10.0, 35.0))
    assert result["ivr"] == 72.00
    assert result["score"] == 3
    assert result["signal"] == "PRIMA_ALTA"
    assert result["status"] == "OK"


def test_ivr_elevado_prima_elevada():
    """vix=22.0, min=10.0, max=35.0 → ivr=48.00, score=+2, signal=PRIMA_ELEVADA"""
    result = calc_ivr(_make_current(22.0), _make_history(10.0, 35.0))
    assert result["ivr"] == 48.00
    assert result["score"] == 2
    assert result["signal"] == "PRIMA_ELEVADA"
    assert result["status"] == "OK"


def test_ivr_normal_prima_normal():
    """vix=18.5, min=10.0, max=35.0 → ivr=34.00, score=+1, signal=PRIMA_NORMAL"""
    result = calc_ivr(_make_current(18.5), _make_history(10.0, 35.0))
    assert result["ivr"] == 34.00
    assert result["score"] == 1
    assert result["signal"] == "PRIMA_NORMAL"
    assert result["status"] == "OK"


def test_ivr_bajo_prima_baja():
    """vix=14.0, min=10.0, max=35.0 → ivr=16.00, score=0, signal=PRIMA_BAJA"""
    result = calc_ivr(_make_current(14.0), _make_history(10.0, 35.0))
    assert result["ivr"] == 16.00
    assert result["score"] == 0
    assert result["signal"] == "PRIMA_BAJA"
    assert result["status"] == "OK"


def test_ivr_muy_bajo_prima_muy_baja():
    """vix=11.0, min=10.0, max=35.0 → ivr=4.00, score=-2, signal=PRIMA_MUY_BAJA"""
    result = calc_ivr(_make_current(11.0), _make_history(10.0, 35.0))
    assert result["ivr"] == 4.00
    assert result["score"] == -2
    assert result["signal"] == "PRIMA_MUY_BAJA"
    assert result["status"] == "OK"


# ---------------------------------------------------------------------------
# Tests de límites de scoring
# ---------------------------------------------------------------------------

def test_ivr_limite_60_prima_elevada():
    """vix=25.0, min=10.0, max=35.0 → ivr=60.00, score=+2, signal=PRIMA_ELEVADA"""
    result = calc_ivr(_make_current(25.0), _make_history(10.0, 35.0))
    assert result["ivr"] == 60.00
    assert result["score"] == 2
    assert result["signal"] == "PRIMA_ELEVADA"
    assert result["status"] == "OK"


def test_ivr_limite_40_prima_elevada():
    """vix=20.0, min=10.0, max=35.0 → ivr=40.00, score=+2, signal=PRIMA_ELEVADA"""
    result = calc_ivr(_make_current(20.0), _make_history(10.0, 35.0))
    assert result["ivr"] == 40.00
    assert result["score"] == 2
    assert result["signal"] == "PRIMA_ELEVADA"
    assert result["status"] == "OK"


def test_ivr_limite_25_prima_baja():
    """vix=16.25, min=10.0, max=35.0 → ivr=25.00, score=0, signal=PRIMA_BAJA"""
    result = calc_ivr(_make_current(16.25), _make_history(10.0, 35.0))
    assert result["ivr"] == 25.00
    assert result["score"] == 0
    assert result["signal"] == "PRIMA_BAJA"
    assert result["status"] == "OK"


def test_ivr_limite_15_prima_baja():
    """vix=13.75, min=10.0, max=35.0 → ivr=15.00, score=0, signal=PRIMA_BAJA"""
    result = calc_ivr(_make_current(13.75), _make_history(10.0, 35.0))
    assert result["ivr"] == 15.00
    assert result["score"] == 0
    assert result["signal"] == "PRIMA_BAJA"
    assert result["status"] == "OK"


# ---------------------------------------------------------------------------
# Tests de error
# ---------------------------------------------------------------------------

def test_rango_cero_max_igual_min():
    """vix_min == vix_max → score=0, status=ERROR"""
    result = calc_ivr(_make_current(16.0), _make_history(16.0, 16.0))
    assert result["score"] == 0
    assert result["status"] == "ERROR"


def test_historial_insuficiente():
    """historial con 30 días → score=0, status=INSUFFICIENT_DATA"""
    result = calc_ivr(_make_current(16.0), _make_history(10.0, 35.0, dias=30))
    assert result["score"] == 0
    assert result["status"] == "INSUFFICIENT_DATA"


def test_vix_actual_ausente():
    """vix=None → score=0, status=MISSING_DATA"""
    result = calc_ivr(_make_current(None), _make_history(10.0, 35.0))
    assert result["score"] == 0
    assert result["status"] == "MISSING_DATA"


def test_history_status_insufficient_data():
    """history.status=INSUFFICIENT_DATA propagado desde fetch → score=0, status=INSUFFICIENT_DATA"""
    history = _make_history(None, None, dias=30, status="INSUFFICIENT_DATA")
    result = calc_ivr(_make_current(16.0), history)
    assert result["score"] == 0
    assert result["status"] == "INSUFFICIENT_DATA"


def test_history_status_error():
    """history.status=ERROR propagado desde fetch → score=0, status=ERROR"""
    history = _make_history(None, None, dias=0, status="ERROR")
    result = calc_ivr(_make_current(16.0), history)
    assert result["score"] == 0
    assert result["status"] == "ERROR"
