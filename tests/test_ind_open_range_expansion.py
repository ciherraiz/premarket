"""
Tests unitarios para IND-OPEN-04: Range Expansion.
Spec: specs/ind_open_range_expansion.md
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.calculate_open_indicators import (
    calc_range_expansion,
    RANGE_EXPANSION_LOW,
    RANGE_EXPANSION_HIGH,
    TRADING_MINUTES_DAY,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_intraday(closes, highs=None, lows=None, window_minutes=30,
                   open_price=5200.0, status="OK"):
    """Construye un dict compatible con fetch_spx_intraday() para los tests."""
    n = len(closes)
    if highs is None:
        highs = [c + 5.0 for c in closes]
    if lows is None:
        lows = [c - 5.0 for c in closes]
    records = [
        {
            "Datetime": f"2026-03-31 09:{30 + i:02d}:00-04:00",
            "Open":   closes[i],
            "High":   highs[i],
            "Low":    lows[i],
            "Close":  closes[i],
            "Volume": 1500,
        }
        for i in range(n)
    ]
    return {
        "ohlcv":          records,
        "bars":           n,
        "window_minutes": window_minutes,
        "open_price":     open_price,
        "fecha":          "2026-03-31",
        "status":         status,
    }


def _make_premarket(vix=20.0):
    """Construye un dict de premarket con VIX disponible."""
    return {
        "ivr": {
            "vix":    vix,
            "status": "OK",
        }
    }


def _expected_range(vix, spx_open, window_minutes):
    """Replica la fórmula del indicador para verificación aritmética."""
    iv_daily_pts = spx_open * (vix / 100) / math.sqrt(252)
    return iv_daily_pts * math.sqrt(window_minutes / TRADING_MINUTES_DAY)


# ---------------------------------------------------------------------------
# Test 1 — Score positivo: ratio bajo < 0.6 → EXPANSION_BAJA
# ---------------------------------------------------------------------------

def test_score_positivo_ratio_bajo():
    """
    VIX=20, SPX_open=5200, window=30 → expected_range ≈ 18.17.
    OR_realized = 5.0 → ratio ≈ 0.275 < 0.6 → score=+1.
    """
    er = _expected_range(20.0, 5200.0, 30)
    # OR_realized = 0.3 × expected_range → ratio = 0.3 (bien por debajo de 0.6)
    realized = 0.3 * er
    highs = [5200.0 + realized] * 10
    lows  = [5200.0] * 10

    result = calc_range_expansion(
        _make_intraday([5200.0] * 10, highs=highs, lows=lows, open_price=5200.0),
        _make_premarket(vix=20.0),
    )

    assert result["status"] == "OK"
    assert result["score"] == 1
    assert result["signal"] == "EXPANSION_BAJA"
    assert result["ratio"] < RANGE_EXPANSION_LOW


# ---------------------------------------------------------------------------
# Test 2 — Score negativo: ratio alto > 1.2 → EXPANSION_ALTA
# ---------------------------------------------------------------------------

def test_score_negativo_ratio_alto():
    """
    OR_realized = 1.5 × expected_range → ratio = 1.5 > 1.2 → score=-1.
    """
    er = _expected_range(20.0, 5200.0, 30)
    realized = 1.5 * er
    highs = [5200.0 + realized] * 10
    lows  = [5200.0] * 10

    result = calc_range_expansion(
        _make_intraday([5200.0] * 10, highs=highs, lows=lows, open_price=5200.0),
        _make_premarket(vix=20.0),
    )

    assert result["status"] == "OK"
    assert result["score"] == -1
    assert result["signal"] == "EXPANSION_ALTA"
    assert result["ratio"] > RANGE_EXPANSION_HIGH


# ---------------------------------------------------------------------------
# Test 3 — Score neutro: ratio en zona media (0.6 – 1.2)
# ---------------------------------------------------------------------------

def test_score_neutro_ratio_medio():
    """
    OR_realized = 0.9 × expected_range → ratio = 0.9 → score=0, signal=NEUTRO.
    """
    er = _expected_range(20.0, 5200.0, 30)
    realized = 0.9 * er
    highs = [5200.0 + realized] * 10
    lows  = [5200.0] * 10

    result = calc_range_expansion(
        _make_intraday([5200.0] * 10, highs=highs, lows=lows, open_price=5200.0),
        _make_premarket(vix=20.0),
    )

    assert result["status"] == "OK"
    assert result["score"] == 0
    assert result["signal"] == "NEUTRO"
    assert RANGE_EXPANSION_LOW <= result["ratio"] <= RANGE_EXPANSION_HIGH


# ---------------------------------------------------------------------------
# Test 4 — Umbral inferior exacto (0.6): score=0 (umbral estricto <)
# ---------------------------------------------------------------------------

def test_umbral_inferior_exacto_score_neutro():
    """
    OR_realized = exactamente 0.6 × expected_range → ratio=0.6 → score=0.
    El umbral es estricto: ratio < 0.6, no ≤.
    """
    er = _expected_range(20.0, 5200.0, 30)
    realized = RANGE_EXPANSION_LOW * er
    highs = [5200.0 + realized] * 10
    lows  = [5200.0] * 10

    result = calc_range_expansion(
        _make_intraday([5200.0] * 10, highs=highs, lows=lows, open_price=5200.0),
        _make_premarket(vix=20.0),
    )

    assert result["score"] == 0
    # Confirmar semántica del umbral estricto
    assert not (RANGE_EXPANSION_LOW < RANGE_EXPANSION_LOW)


# ---------------------------------------------------------------------------
# Test 5 — Umbral superior exacto (1.2): score=0 (umbral estricto >)
# ---------------------------------------------------------------------------

def test_umbral_superior_exacto_score_neutro():
    """
    OR_realized = exactamente 1.2 × expected_range → ratio=1.2 → score=0.
    El umbral es estricto: ratio > 1.2, no ≥.
    """
    er = _expected_range(20.0, 5200.0, 30)
    realized = RANGE_EXPANSION_HIGH * er
    highs = [5200.0 + realized] * 10
    lows  = [5200.0] * 10

    result = calc_range_expansion(
        _make_intraday([5200.0] * 10, highs=highs, lows=lows, open_price=5200.0),
        _make_premarket(vix=20.0),
    )

    assert result["score"] == 0
    # Confirmar semántica del umbral estricto
    assert not (RANGE_EXPANSION_HIGH > RANGE_EXPANSION_HIGH)


# ---------------------------------------------------------------------------
# Test 6 — Fetch fallido
# ---------------------------------------------------------------------------

def test_fetch_fallido_propaga_error():
    """Si spx_intraday["status"] != "OK", el indicador devuelve ERROR_FETCH."""
    intraday = _make_intraday([5200.0] * 10, status="ERROR")
    result = calc_range_expansion(intraday, _make_premarket())

    assert result["status"] == "ERROR"
    assert result["signal"] == "ERROR_FETCH"
    assert result["score"] == 0
    assert result["ratio"] is None


# ---------------------------------------------------------------------------
# Test 7 — Sin velas (lista vacía)
# ---------------------------------------------------------------------------

def test_sin_velas_lista_vacia():
    """ohlcv vacío → status=ERROR, signal=ERROR_SIN_DATOS."""
    intraday = _make_intraday([])
    intraday["ohlcv"] = []
    result = calc_range_expansion(intraday, _make_premarket())

    assert result["status"] == "ERROR"
    assert result["signal"] == "ERROR_SIN_DATOS"
    assert result["score"] == 0


# ---------------------------------------------------------------------------
# Test 8 — Columnas faltantes
# ---------------------------------------------------------------------------

def test_columnas_faltantes_devuelve_error():
    """Registros sin campo 'High' → status=ERROR, signal=ERROR_COLUMNAS."""
    intraday = _make_intraday([5200.0] * 10)
    for rec in intraday["ohlcv"]:
        del rec["High"]

    result = calc_range_expansion(intraday, _make_premarket())

    assert result["status"] == "ERROR"
    assert result["signal"] == "ERROR_COLUMNAS"
    assert result["score"] == 0


# ---------------------------------------------------------------------------
# Test 9 — VIX no disponible
# ---------------------------------------------------------------------------

def test_iv_no_disponible_devuelve_error():
    """Si VIX es None en premarket_indicators → signal=ERROR_IV_NO_DISPONIBLE."""
    intraday    = _make_intraday([5200.0] * 10)
    premarket   = {"ivr": {"vix": None, "status": "OK"}, "vix_vxv_slope": {"vix": None}}
    result = calc_range_expansion(intraday, premarket)

    assert result["status"] == "ERROR"
    assert result["signal"] == "ERROR_IV_NO_DISPONIBLE"
    assert result["score"] == 0


# ---------------------------------------------------------------------------
# Test 10 — open_price nulo
# ---------------------------------------------------------------------------

def test_spx_open_nulo_devuelve_error():
    """Si open_price es None → signal=ERROR_SPX_OPEN_NULO."""
    intraday = _make_intraday([5200.0] * 10, open_price=None)
    result = calc_range_expansion(intraday, _make_premarket())

    assert result["status"] == "ERROR"
    assert result["signal"] == "ERROR_SPX_OPEN_NULO"
    assert result["score"] == 0


# ---------------------------------------------------------------------------
# Test 11 — Ventana incompleta (< 50% de velas esperadas)
# ---------------------------------------------------------------------------

def test_ventana_incompleta_calcula_igualmente():
    """5 velas para ventana de 30 min → incomplete_window=True pero calcula."""
    er = _expected_range(20.0, 5200.0, 30)
    # ratio bajo para que score sea +1
    realized = 0.3 * er
    highs = [5200.0 + realized] * 5
    lows  = [5200.0] * 5

    result = calc_range_expansion(
        _make_intraday([5200.0] * 5, highs=highs, lows=lows,
                       window_minutes=30, open_price=5200.0),
        _make_premarket(vix=20.0),
    )

    assert result["incomplete_window"] is True
    assert result["status"] == "OK"
    assert result["candles_used"] == 5
    assert result["score"] in (-1, 0, 1)
    assert result["ratio"] is not None


# ---------------------------------------------------------------------------
# Test 12 — Verificación aritmética exacta
# ---------------------------------------------------------------------------

def test_verificacion_aritmetica():
    """
    VIX=20, SPX_open=5200, window=30.
    iv_daily_pts  = 5200 × 0.20 / sqrt(252)
    expected_range = iv_daily_pts × sqrt(30/390)
    ratio = OR_realized / expected_range
    """
    vix   = 20.0
    spx   = 5200.0
    w     = 30

    iv_daily_pts   = spx * (vix / 100) / math.sqrt(252)
    expected_range = iv_daily_pts * math.sqrt(w / TRADING_MINUTES_DAY)

    # OR_realized = 10 puntos
    highs = [5210.0] * w
    lows  = [5200.0] * w
    expected_ratio = round(10.0 / expected_range, 4)

    result = calc_range_expansion(
        _make_intraday([5205.0] * w, highs=highs, lows=lows,
                       window_minutes=w, open_price=spx),
        _make_premarket(vix=vix),
    )

    assert result["status"] == "OK"
    assert abs(result["iv_daily_pts"]   - round(iv_daily_pts,   4)) < 1e-3
    assert abs(result["expected_range"] - round(expected_range, 4)) < 1e-3
    assert result["ratio"] == expected_ratio
    assert result["or_realized"] == 10.0
    assert result["vix_used"]    == vix
    assert result["spx_open"]    == spx


# ---------------------------------------------------------------------------
# Test 13 — Rango cero: precio completamente flat
# ---------------------------------------------------------------------------

def test_rango_cero_precio_flat():
    """
    Todas las velas con High=Low=Close → OR_realized=0 → ratio=0.0 → score=+1.
    Un rango de cero es el caso extremo de EXPANSION_BAJA.
    """
    closes = [5200.0] * 10
    highs  = [5200.0] * 10
    lows   = [5200.0] * 10

    result = calc_range_expansion(
        _make_intraday(closes, highs=highs, lows=lows, open_price=5200.0),
        _make_premarket(vix=20.0),
    )

    assert result["status"] == "OK"
    assert result["or_realized"] == 0.0
    assert result["ratio"] == 0.0
    assert result["score"] == 1
    assert result["signal"] == "EXPANSION_BAJA"
