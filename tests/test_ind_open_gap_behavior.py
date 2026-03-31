"""
Tests unitarios para IND-OPEN-05: Gap Behavior.
Spec: specs/ind_open_gap_behavior.md
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.calculate_open_indicators import (
    calc_gap_behavior,
    GAP_MIN_PCT,
    GAP_MANTIENE_PCT,
    GAP_NEUTRO_PCT,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_intraday(last_close, open_price=5020.0, window_minutes=30, status="OK"):
    """Construye un dict compatible con fetch_spx_intraday() para los tests.

    Genera una sola vela cuyo Close es `last_close`. Los campos High y Low
    son irrelevantes para este indicador (solo se usa Close y open_price).
    """
    records = [
        {
            "Datetime": "2026-03-31 09:30:00-04:00",
            "Open":   open_price,
            "High":   max(open_price, last_close) + 1.0,
            "Low":    min(open_price, last_close) - 1.0,
            "Close":  last_close,
            "Volume": 10000,
        }
    ]
    return {
        "ohlcv":          records,
        "bars":           1,
        "window_minutes": window_minutes,
        "open_price":     open_price,
        "fecha":          "2026-03-31",
        "status":         status,
    }


def _make_premarket(spx_prev_close=5000.0):
    """Construye un dict de premarket_indicators con spx_prev_close disponible."""
    return {"spx_prev_close": spx_prev_close}


# ---------------------------------------------------------------------------
# Test 1 — Gap alcista mantenido: fill = 10 % < 25 % → score = +2
# ---------------------------------------------------------------------------

def test_gap_alcista_mantenido():
    """
    prev_close=5000, open_price=5020, last_close=5018
    gap_pts = +20,  gap_pct = +0.4000 %
    gap_fill_pct = (5020 - 5018) / 20 × 100 = 10.0 %  →  < 25 % → score=+2
    """
    result = calc_gap_behavior(
        _make_intraday(last_close=5018.0, open_price=5020.0),
        _make_premarket(spx_prev_close=5000.0),
    )

    assert result["status"] == "OK"
    assert result["score"] == 2
    assert result["signal"] == "GAP_ALCISTA_MANTENIDO"
    assert result["gap_direction"] == "UP"
    assert abs(result["gap_pct"] - 0.4) < 1e-3
    assert abs(result["gap_fill_pct"] - 10.0) < 1e-3


# ---------------------------------------------------------------------------
# Test 2 — Gap alcista parcial: fill = 50 % → score = +1
# ---------------------------------------------------------------------------

def test_gap_alcista_parcial():
    """
    prev_close=5000, open_price=5020, last_close=5010
    gap_fill_pct = (5020 - 5010) / 20 × 100 = 50.0 %  →  25 ≤ 50 < 75 → score=+1
    """
    result = calc_gap_behavior(
        _make_intraday(last_close=5010.0, open_price=5020.0),
        _make_premarket(spx_prev_close=5000.0),
    )

    assert result["status"] == "OK"
    assert result["score"] == 1
    assert result["signal"] == "GAP_ALCISTA_PARCIAL"
    assert abs(result["gap_fill_pct"] - 50.0) < 1e-3


# ---------------------------------------------------------------------------
# Test 3 — Gap alcista rellenado: fill = 80 % ≥ 75 % → score = 0
# ---------------------------------------------------------------------------

def test_gap_alcista_relleno():
    """
    prev_close=5000, open_price=5020, last_close=5004
    gap_fill_pct = (5020 - 5004) / 20 × 100 = 80.0 %  →  ≥ 75 % → score=0
    """
    result = calc_gap_behavior(
        _make_intraday(last_close=5004.0, open_price=5020.0),
        _make_premarket(spx_prev_close=5000.0),
    )

    assert result["status"] == "OK"
    assert result["score"] == 0
    assert result["signal"] == "GAP_ALCISTA_RELLENO"
    assert result["gap_fill_pct"] >= GAP_NEUTRO_PCT


# ---------------------------------------------------------------------------
# Test 4 — Gap bajista mantenido: fill = 10 % < 25 % → score = -2
# ---------------------------------------------------------------------------

def test_gap_bajista_mantenido():
    """
    prev_close=5020, open_price=5000, last_close=5002
    gap_pts = -20,  gap_pct ≈ -0.3984 %
    gap_fill_pct = (5000 - 5002) / (-20) × 100 = 10.0 %  →  < 25 % → score=-2
    """
    result = calc_gap_behavior(
        _make_intraday(last_close=5002.0, open_price=5000.0),
        _make_premarket(spx_prev_close=5020.0),
    )

    assert result["status"] == "OK"
    assert result["score"] == -2
    assert result["signal"] == "GAP_BAJISTA_MANTENIDO"
    assert result["gap_direction"] == "DOWN"
    assert abs(result["gap_fill_pct"] - 10.0) < 1e-3


# ---------------------------------------------------------------------------
# Test 5 — Gap bajista parcial: fill = 50 % → score = -1
# ---------------------------------------------------------------------------

def test_gap_bajista_parcial():
    """
    prev_close=5020, open_price=5000, last_close=5010
    gap_fill_pct = (5000 - 5010) / (-20) × 100 = 50.0 %  →  25 ≤ 50 < 75 → score=-1
    """
    result = calc_gap_behavior(
        _make_intraday(last_close=5010.0, open_price=5000.0),
        _make_premarket(spx_prev_close=5020.0),
    )

    assert result["status"] == "OK"
    assert result["score"] == -1
    assert result["signal"] == "GAP_BAJISTA_PARCIAL"
    assert abs(result["gap_fill_pct"] - 50.0) < 1e-3


# ---------------------------------------------------------------------------
# Test 6 — Gap bajista rellenado: fill = 80 % ≥ 75 % → score = 0
# ---------------------------------------------------------------------------

def test_gap_bajista_relleno():
    """
    prev_close=5020, open_price=5000, last_close=5016
    gap_fill_pct = (5000 - 5016) / (-20) × 100 = 80.0 %  →  ≥ 75 % → score=0
    """
    result = calc_gap_behavior(
        _make_intraday(last_close=5016.0, open_price=5000.0),
        _make_premarket(spx_prev_close=5020.0),
    )

    assert result["status"] == "OK"
    assert result["score"] == 0
    assert result["signal"] == "GAP_BAJISTA_RELLENO"
    assert result["gap_fill_pct"] >= GAP_NEUTRO_PCT


# ---------------------------------------------------------------------------
# Test 7 — Gap insignificante: |gap_pct| < 0.15 % → GAP_INSIGNIFICANTE
# ---------------------------------------------------------------------------

def test_gap_insignificante_por_debajo_umbral():
    """
    prev_close=5000, open_price=5005 → gap_pct = 0.10 % < 0.15 %
    El indicador devuelve GAP_INSIGNIFICANTE sin calcular gap_fill_pct.
    """
    result = calc_gap_behavior(
        _make_intraday(last_close=5003.0, open_price=5005.0),
        _make_premarket(spx_prev_close=5000.0),
    )

    assert result["status"] == "OK"
    assert result["score"] == 0
    assert result["signal"] == "GAP_INSIGNIFICANTE"
    assert result["gap_direction"] == "NONE"
    assert result["gap_fill_pct"] is None
    assert abs(result["gap_pct"]) < GAP_MIN_PCT


# ---------------------------------------------------------------------------
# Test 8 — Umbral mínimo exacto: gap_pct = 0.15 % → gap significativo
# ---------------------------------------------------------------------------

def test_gap_exactamente_umbral_minimo():
    """
    El umbral es estricto: |gap_pct| < 0.15 % → ruido. Si gap_pct = 0.15 % exacto,
    el gap es significativo (no ruido) y debe producir un score ≠ 0.

    prev_close=5000, open_price=5000 × (1 + 0.0015) = 5007.50
    """
    prev_close  = 5000.0
    open_price  = round(prev_close * (1 + GAP_MIN_PCT / 100), 2)  # 5007.50

    result = calc_gap_behavior(
        _make_intraday(last_close=open_price, open_price=open_price),
        _make_premarket(spx_prev_close=prev_close),
    )

    # El gap es exactamente en el umbral: no es ruido (umbral estricto <)
    assert result["signal"] != "GAP_INSIGNIFICANTE"
    assert result["gap_direction"] == "UP"


# ---------------------------------------------------------------------------
# Test 9 — Umbral mantiene exacto: fill = 25.0 % → parcial (no mantenido)
# ---------------------------------------------------------------------------

def test_umbral_mantiene_exacto():
    """
    El umbral es estricto: gap_fill_pct < 25 % → mantenido.
    fill = 25.0 % exacto → parcial (no mantenido).

    prev_close=5000, open_price=5020, gap=20 pts
    Para fill=25 %: last_close = 5020 - 0.25 × 20 = 5015.0
    """
    result = calc_gap_behavior(
        _make_intraday(last_close=5015.0, open_price=5020.0),
        _make_premarket(spx_prev_close=5000.0),
    )

    assert result["status"] == "OK"
    assert result["score"] == 1
    assert result["signal"] == "GAP_ALCISTA_PARCIAL"
    assert abs(result["gap_fill_pct"] - 25.0) < 1e-3


# ---------------------------------------------------------------------------
# Test 10 — Umbral neutro exacto: fill = 75.0 % → rellenado (no parcial)
# ---------------------------------------------------------------------------

def test_umbral_neutro_exacto():
    """
    El umbral es estricto: gap_fill_pct < 75 % → parcial.
    fill = 75.0 % exacto → rellenado (no parcial).

    prev_close=5000, open_price=5020, gap=20 pts
    Para fill=75 %: last_close = 5020 - 0.75 × 20 = 5005.0
    """
    result = calc_gap_behavior(
        _make_intraday(last_close=5005.0, open_price=5020.0),
        _make_premarket(spx_prev_close=5000.0),
    )

    assert result["status"] == "OK"
    assert result["score"] == 0
    assert result["signal"] == "GAP_ALCISTA_RELLENO"
    assert abs(result["gap_fill_pct"] - 75.0) < 1e-3


# ---------------------------------------------------------------------------
# Test 11 — Error: spx_prev_close = None
# ---------------------------------------------------------------------------

def test_error_prev_close_none():
    """Si spx_prev_close es None, el indicador devuelve ERROR sin calcular."""
    result = calc_gap_behavior(
        _make_intraday(last_close=5018.0, open_price=5020.0),
        _make_premarket(spx_prev_close=None),
    )

    assert result["status"] == "ERROR"
    assert result["signal"] == "ERROR_PREV_CLOSE_NO_DISPONIBLE"
    assert result["score"] == 0
    assert result["gap_pct"] is None


# ---------------------------------------------------------------------------
# Test 12 — Error: spx_prev_close = 0
# ---------------------------------------------------------------------------

def test_error_prev_close_cero():
    """Si spx_prev_close es 0, el indicador devuelve ERROR (evita división por cero)."""
    result = calc_gap_behavior(
        _make_intraday(last_close=5018.0, open_price=5020.0),
        _make_premarket(spx_prev_close=0),
    )

    assert result["status"] == "ERROR"
    assert result["signal"] == "ERROR_PREV_CLOSE_NO_DISPONIBLE"
    assert result["score"] == 0


# ---------------------------------------------------------------------------
# Test 13 — Gap alcista sobrerrellenado: fill > 100 % → GAP_ALCISTA_RELLENO
# ---------------------------------------------------------------------------

def test_gap_alcista_sobrerellenado():
    """
    El precio cruzó prev_close hacia abajo: gap_fill_pct > 100 %.
    Debe seguir devolviendo GAP_ALCISTA_RELLENO (score=0), no un error.

    prev_close=5000, open_price=5020, last_close=4998
    gap_fill_pct = (5020 - 4998) / 20 × 100 = 110.0 %  →  ≥ 75 % → score=0
    """
    result = calc_gap_behavior(
        _make_intraday(last_close=4998.0, open_price=5020.0),
        _make_premarket(spx_prev_close=5000.0),
    )

    assert result["status"] == "OK"
    assert result["score"] == 0
    assert result["signal"] == "GAP_ALCISTA_RELLENO"
    assert result["gap_fill_pct"] > 100.0
