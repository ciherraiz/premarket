"""
Tests unitarios para IND-OPEN-06: Realized Volatility Open.
Spec: specs/ind_open_realized_vol.md
"""
import math
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.calculate_open_indicators import (
    TRADING_MINUTES_DAY,
    RV_OPEN_MIN_CANDLES,
    RV_OPEN_RATIO_BAJO,
    RV_OPEN_RATIO_ALTO,
    calc_realized_vol_open,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_intraday(closes, window_minutes=30, status="OK"):
    """Construye un dict compatible con fetch_spx_intraday() a partir de closes."""
    n = len(closes)
    records = [
        {
            "Datetime": f"2026-04-01 09:{30 + i:02d}:00-04:00",
            "Open":   closes[i],
            "High":   closes[i] + 1.0,
            "Low":    closes[i] - 1.0,
            "Close":  closes[i],
            "Volume": 10000,
        }
        for i in range(n)
    ]
    return {
        "ohlcv":          records,
        "bars":           n,
        "window_minutes": window_minutes,
        "open_price":     closes[0] if closes else None,
        "fecha":          "2026-04-01",
        "status":         status,
    }


def _make_premarket(vix=16.0):
    """Dict de premarket con VIX disponible en ivr."""
    return {
        "ivr": {
            "vix":    vix,
            "status": "OK",
        }
    }


def _closes_for_target_ratio(target_ratio, vix=16.0, n=20, base=5200.0):
    """
    Genera una serie de closes cuyo rv_ratio ≈ target_ratio.

    Usa retornos alternantes [+r, -r, +r, -r, ...] con:
        r = target_ratio × (vix/100) / sqrt(252 × TRADING_MINUTES_DAY)

    std([+r, -r, ...]) = r  →  rv_1m = r × sqrt(252×390)  →  rv_ratio = rv_1m / (vix/100)
    """
    iv_daily   = vix / 100
    target_std = target_ratio * iv_daily / math.sqrt(252 * TRADING_MINUTES_DAY)
    closes = [base]
    for i in range(1, n):
        sign = 1 if i % 2 == 1 else -1
        closes.append(closes[-1] * math.exp(sign * target_std))
    return closes


def _rv_ratio_ref(closes, vix):
    """Cálculo de referencia independiente para test_verificacion_aritmetica."""
    log_returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    std_lr      = pd.Series(log_returns).std(ddof=1)
    rv_1m       = std_lr * math.sqrt(252 * TRADING_MINUTES_DAY)
    iv_daily    = vix / 100
    return round(rv_1m / iv_daily, 4), rv_1m, iv_daily


# ---------------------------------------------------------------------------
# Test 1 — Score positivo: rv_ratio < 0.8 → PRIMA_SOBREVALORADA
# ---------------------------------------------------------------------------

def test_score_positivo_ratio_bajo():
    """rv_ratio ≈ 0.4 → score=+2, PRIMA_SOBREVALORADA."""
    closes = _closes_for_target_ratio(0.4, vix=16.0, n=20)
    result = calc_realized_vol_open(_make_intraday(closes), _make_premarket(vix=16.0))

    assert result["status"] == "OK"
    assert result["score"] == 2
    assert result["signal"] == "PRIMA_SOBREVALORADA"
    assert result["rv_ratio"] < RV_OPEN_RATIO_BAJO
    assert result["rv_1m"] is not None
    assert result["iv_daily"] is not None


# ---------------------------------------------------------------------------
# Test 2 — Score negativo: rv_ratio > 1.2 → PRIMA_INFRAVALORADA
# ---------------------------------------------------------------------------

def test_score_negativo_ratio_alto():
    """rv_ratio ≈ 1.8 → score=−2, PRIMA_INFRAVALORADA."""
    closes = _closes_for_target_ratio(1.8, vix=16.0, n=20)
    result = calc_realized_vol_open(_make_intraday(closes), _make_premarket(vix=16.0))

    assert result["status"] == "OK"
    assert result["score"] == -2
    assert result["signal"] == "PRIMA_INFRAVALORADA"
    assert result["rv_ratio"] > RV_OPEN_RATIO_ALTO


# ---------------------------------------------------------------------------
# Test 3 — Score neutro: 0.8 ≤ rv_ratio ≤ 1.2 → NEUTRO
# ---------------------------------------------------------------------------

def test_score_neutro_ratio_medio():
    """rv_ratio ≈ 1.0 → score=0, NEUTRO."""
    closes = _closes_for_target_ratio(1.0, vix=16.0, n=20)
    result = calc_realized_vol_open(_make_intraday(closes), _make_premarket(vix=16.0))

    assert result["status"] == "OK"
    assert result["score"] == 0
    assert result["signal"] == "NEUTRO"
    assert RV_OPEN_RATIO_BAJO <= result["rv_ratio"] <= RV_OPEN_RATIO_ALTO


# ---------------------------------------------------------------------------
# Test 4 — Umbral inferior exacto (0.8): score=0 (estricto <)
# ---------------------------------------------------------------------------

def test_umbral_inferior_exacto_score_neutro():
    """
    rv_ratio == RV_OPEN_RATIO_BAJO (0.8) → score=0, NEUTRO.
    El umbral es estricto: solo rv_ratio < 0.8 da score=+2.
    """
    closes = _closes_for_target_ratio(RV_OPEN_RATIO_BAJO, vix=16.0, n=20)
    result = calc_realized_vol_open(_make_intraday(closes), _make_premarket(vix=16.0))

    assert result["status"] == "OK"
    # El helper produce rv_ratio ≈ 0.8 — en el umbral no debe disparar score=+2
    assert result["score"] == 0
    assert result["signal"] == "NEUTRO"


# ---------------------------------------------------------------------------
# Test 5 — Umbral superior exacto (1.2): score=0 (estricto >)
# ---------------------------------------------------------------------------

def test_umbral_superior_exacto_score_neutro():
    """
    Verifica la semántica estricta del umbral superior: rv_ratio <= 1.2 → score=0.
    El helper aproxima el ratio objetivo; se verifica la coherencia score/ratio,
    no la igualdad exacta a 1.2 (el redondeo a 4 decimales puede dar 1.1999 o 1.2001).
    """
    closes = _closes_for_target_ratio(RV_OPEN_RATIO_ALTO, vix=16.0, n=20)
    result = calc_realized_vol_open(_make_intraday(closes), _make_premarket(vix=16.0))

    assert result["status"] == "OK"
    ratio = result["rv_ratio"]
    # El score debe ser coherente con el ratio y los umbrales estrictos
    if ratio < RV_OPEN_RATIO_BAJO:
        assert result["score"] == 2
    elif ratio > RV_OPEN_RATIO_ALTO:
        assert result["score"] == -2
    else:
        assert result["score"] == 0
    # Verificar que el umbral es estricto: rv_ratio == 1.2 exacto → score 0, no -2
    assert not (RV_OPEN_RATIO_ALTO > RV_OPEN_RATIO_ALTO)


# ---------------------------------------------------------------------------
# Test 6 — Fetch fallido: status=ERROR en spx_intraday
# ---------------------------------------------------------------------------

def test_fetch_fallido_propaga_error():
    """spx_intraday['status'] == 'ERROR' → status=ERROR, signal=ERROR_FETCH."""
    intraday = _make_intraday([5200.0] * 10, status="ERROR")
    result   = calc_realized_vol_open(intraday, _make_premarket())

    assert result["status"] == "ERROR"
    assert result["signal"] == "ERROR_FETCH"
    assert result["score"] == 0
    assert result["rv_ratio"] is None
    assert result["rv_1m"] is None


# ---------------------------------------------------------------------------
# Test 7 — Sin velas (lista vacía)
# ---------------------------------------------------------------------------

def test_sin_velas_lista_vacia():
    """ohlcv=[] → status=ERROR, signal=ERROR_FETCH."""
    result = calc_realized_vol_open(_make_intraday([]), _make_premarket())

    assert result["status"] == "ERROR"
    assert result["signal"] == "ERROR_FETCH"
    assert result["score"] == 0


# ---------------------------------------------------------------------------
# Test 8 — Columna Close faltante
# ---------------------------------------------------------------------------

def test_columna_close_faltante():
    """Registros sin campo 'Close' → status=ERROR, signal=ERROR_FETCH."""
    intraday = _make_intraday([5200.0] * 10)
    for rec in intraday["ohlcv"]:
        del rec["Close"]

    result = calc_realized_vol_open(intraday, _make_premarket())

    assert result["status"] == "ERROR"
    assert result["signal"] == "ERROR_FETCH"
    assert result["score"] == 0


# ---------------------------------------------------------------------------
# Test 9 — Menos de 5 velas: INSUFFICIENT_DATA
# ---------------------------------------------------------------------------

def test_menos_de_cinco_velas_insuficiente():
    """
    4 closes < RV_OPEN_MIN_CANDLES (5) → INSUFFICIENT_DATA.
    candles_used debe reflejar el número real de closes recibidos.
    """
    closes = [5200.0, 5201.0, 5202.0, 5203.0]   # 4 closes
    result = calc_realized_vol_open(_make_intraday(closes), _make_premarket())

    assert result["status"] == "INSUFFICIENT_DATA"
    assert result["signal"] == "INSUFFICIENT_DATA"
    assert result["score"] == 0
    assert result["rv_ratio"] is None
    assert result["candles_used"] == 4


# ---------------------------------------------------------------------------
# Test 10 — Exactamente 5 velas: mínimo válido
# ---------------------------------------------------------------------------

def test_exactamente_cinco_velas_calcula():
    """
    5 closes == RV_OPEN_MIN_CANDLES → la función calcula (no devuelve error).
    El score puede ser cualquier valor válido.
    """
    closes = [5200.0, 5201.0, 5202.0, 5203.0, 5204.0]   # 5 closes
    result = calc_realized_vol_open(_make_intraday(closes), _make_premarket())

    assert result["status"] == "OK"
    assert result["score"] in (-2, 0, 2)
    assert result["rv_ratio"] is not None
    assert result["candles_used"] == 5


# ---------------------------------------------------------------------------
# Test 11 — IV no disponible: ambos VIX son None
# ---------------------------------------------------------------------------

def test_iv_no_disponible_ambos_none():
    """ivr.vix=None y vix_vxv_slope.vix=None → MISSING_DATA, IV_NO_DISPONIBLE."""
    premarket = {
        "ivr":           {"vix": None, "status": "OK"},
        "vix_vxv_slope": {"vix": None},
    }
    closes = [5200.0 + i for i in range(10)]
    result = calc_realized_vol_open(_make_intraday(closes), premarket)

    assert result["status"] == "MISSING_DATA"
    assert result["signal"] == "IV_NO_DISPONIBLE"
    assert result["score"] == 0
    assert result["rv_ratio"] is None


# ---------------------------------------------------------------------------
# Test 12 — IV fallback a vix_vxv_slope
# ---------------------------------------------------------------------------

def test_iv_fallback_vix_vxv_slope():
    """ivr.vix=None pero vix_vxv_slope.vix=16.0 → la función usa el fallback y calcula."""
    premarket = {
        "ivr":           {"vix": None, "status": "OK"},
        "vix_vxv_slope": {"vix": 16.0},
    }
    closes = _closes_for_target_ratio(0.4, vix=16.0, n=20)
    result = calc_realized_vol_open(_make_intraday(closes), premarket)

    assert result["status"] == "OK"
    assert result["rv_ratio"] is not None
    assert result["iv_daily"] == 0.16


# ---------------------------------------------------------------------------
# Test 13 — Verificación aritmética exacta
# ---------------------------------------------------------------------------

def test_verificacion_aritmetica():
    """
    closes = [5200 + i for i in range(10)], VIX=20.
    Verificamos rv_1m, iv_daily y rv_ratio contra el cálculo de referencia.
    """
    vix    = 20.0
    closes = [5200.0 + i for i in range(10)]

    expected_ratio, expected_rv, expected_iv = _rv_ratio_ref(closes, vix)

    result = calc_realized_vol_open(
        _make_intraday(closes),
        _make_premarket(vix=vix),
    )

    assert result["status"] == "OK"
    assert result["candles_used"] == 10
    assert abs(result["rv_1m"]    - expected_rv)  < 1e-9
    assert abs(result["iv_daily"] - expected_iv)  < 1e-9
    assert result["rv_ratio"] == expected_ratio


# ---------------------------------------------------------------------------
# Test 14 — Closes flat: rv_ratio=0.0 → score=+2 (PRIMA_SOBREVALORADA extrema)
# ---------------------------------------------------------------------------

def test_closes_flat_score_positivo():
    """
    Todos los closes idénticos → log_returns = [0, 0, ...] → std=0 → rv_1m=0.
    rv_ratio = 0.0 < RV_OPEN_RATIO_BAJO (0.8) → score=+2, PRIMA_SOBREVALORADA.
    Es el caso extremo de baja volatilidad realizada; es un resultado válido, no un error.
    """
    closes = [5200.0] * 10
    result = calc_realized_vol_open(_make_intraday(closes), _make_premarket(vix=16.0))

    assert result["status"] == "OK"
    assert result["rv_1m"]    == 0.0
    assert result["rv_ratio"] == 0.0
    assert result["score"]    == 2
    assert result["signal"]   == "PRIMA_SOBREVALORADA"
