"""
Tests de integración para el pipeline completo con V-Score (IVR).
Usan mocks para evitar llamadas reales a yfinance.
"""
import io
import sys
import os
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.calculate_indicators import calc_vix_vxv_slope, calc_vix9d_vix_ratio, calc_ivr
from scripts.generate_scorecard import print_scorecard


# ---------------------------------------------------------------------------
# Fixtures reutilizables
# ---------------------------------------------------------------------------

GOOD_DATA = {
    "vix9d": 13.42,
    "vix": 16.05,
    "vxv": 18.30,
    "vvix": 88.12,
    "fecha": "2026-03-28",
    "status": "OK",
}

GOOD_HISTORY = {
    "vix_min_52w": 10.62,
    "vix_max_52w": 65.73,
    "dias_disponibles": 252,
    "fecha": "2026-03-27",
    "status": "OK",
}


def _build_indicators(data, history):
    slope = calc_vix_vxv_slope(data)
    ratio = calc_vix9d_vix_ratio(data)
    ivr   = calc_ivr(data, history)
    return {
        "fecha":           data.get("fecha"),
        "vix_vxv_slope":   slope,
        "vix9d_vix_ratio": ratio,
        "ivr":             ivr,
        "d_score":         slope["score"] + ratio["score"],
        "v_score":         ivr["score"],
    }


# ---------------------------------------------------------------------------
# Test 1: Pipeline completo OK
# ---------------------------------------------------------------------------

def test_pipeline_completo_ok():
    """d_score y v_score están presentes con tipos int."""
    indicators = _build_indicators(GOOD_DATA, GOOD_HISTORY)

    assert "d_score" in indicators
    assert "v_score" in indicators
    assert isinstance(indicators["d_score"], int)
    assert isinstance(indicators["v_score"], int)
    assert indicators["ivr"]["status"] == "OK"
    assert indicators["ivr"]["ivr"] is not None


# ---------------------------------------------------------------------------
# Test 2: IVR con historial insuficiente → v_score = 0
# ---------------------------------------------------------------------------

def test_ivr_historial_insuficiente():
    """fetch_vix_history devuelve INSUFFICIENT_DATA → v_score = 0."""
    insufficient_history = {
        "vix_min_52w": None,
        "vix_max_52w": None,
        "dias_disponibles": 30,
        "fecha": None,
        "status": "INSUFFICIENT_DATA",
    }
    indicators = _build_indicators(GOOD_DATA, insufficient_history)

    assert indicators["ivr"]["status"] == "INSUFFICIENT_DATA"
    assert indicators["ivr"]["score"] == 0
    assert indicators["v_score"] == 0


# ---------------------------------------------------------------------------
# Test 3: IVR con rango cero → ivr["status"] = "ERROR", v_score = 0
# ---------------------------------------------------------------------------

def test_ivr_rango_cero():
    """vix_min_52w == vix_max_52w → ivr.status=ERROR, v_score=0."""
    zero_range_history = {
        "vix_min_52w": 16.0,
        "vix_max_52w": 16.0,
        "dias_disponibles": 252,
        "fecha": "2026-03-27",
        "status": "OK",
    }
    indicators = _build_indicators(GOOD_DATA, zero_range_history)

    assert indicators["ivr"]["status"] == "ERROR"
    assert indicators["ivr"]["score"] == 0
    assert indicators["v_score"] == 0


# ---------------------------------------------------------------------------
# Test 4: Scorecard muestra D-Score y V-Score
# ---------------------------------------------------------------------------

def test_scorecard_muestra_d_score_y_v_score():
    """El output del scorecard contiene las cabeceras D-Score y V-Score."""
    indicators = _build_indicators(GOOD_DATA, GOOD_HISTORY)

    captured = io.StringIO()
    sys.stdout = captured
    try:
        print_scorecard(indicators)
    finally:
        sys.stdout = sys.__stdout__

    output = captured.getvalue()
    assert "D-Score" in output
    assert "V-Score" in output


# ---------------------------------------------------------------------------
# Test 5: fetch_vix_history falla → pipeline continúa, scorecard muestra error en IVR
# ---------------------------------------------------------------------------

def test_fetch_vix_history_falla_pipeline_continua():
    """Si fetch_vix_history devuelve ERROR, el pipeline no aborta y el scorecard
    muestra el estado de error en la línea de IVR."""
    error_history = {
        "vix_min_52w": None,
        "vix_max_52w": None,
        "dias_disponibles": 0,
        "fecha": None,
        "status": "ERROR",
    }
    # El pipeline no debe lanzar excepción
    indicators = _build_indicators(GOOD_DATA, error_history)

    assert indicators["ivr"]["status"] == "ERROR"
    assert indicators["ivr"]["score"] == 0

    # Scorecard se imprime sin excepción y muestra el estado de error
    captured = io.StringIO()
    sys.stdout = captured
    try:
        print_scorecard(indicators)
    finally:
        sys.stdout = sys.__stdout__

    output = captured.getvalue()
    assert "ERROR" in output
    assert "V-Score" in output
