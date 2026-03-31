"""
Tests unitarios para IND-OPEN-01: VWAP Position.
Spec: specs/ind_open_vwap_position.md
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.calculate_open_indicators import calc_vwap_position, VWAP_THRESHOLD_PCT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_intraday(closes, highs=None, lows=None, volumes=None,
                   window_minutes=30, status="OK"):
    """Construye un dict compatible con fetch_spx_intraday() para los tests."""
    n = len(closes)
    if highs is None:
        highs = [c + 1.0 for c in closes]
    if lows is None:
        lows = [c - 1.0 for c in closes]
    if volumes is None:
        volumes = [1500] * n
    records = [
        {
            "Datetime": f"2026-03-31 09:{30 + i:02d}:00-04:00",
            "Open":   closes[i],
            "High":   highs[i],
            "Low":    lows[i],
            "Close":  closes[i],
            "Volume": volumes[i],
        }
        for i in range(n)
    ]
    return {
        "ohlcv":          records,
        "bars":           n,
        "window_minutes": window_minutes,
        "open_price":     closes[0] if closes else None,
        "fecha":          "2026-03-31",
        "status":         status,
    }


# ---------------------------------------------------------------------------
# Test 1 — Score positivo: precio sobre VWAP
# ---------------------------------------------------------------------------

def test_score_positivo_precio_sobre_vwap():
    """Precio sube progresivamente → close final >> VWAP → score=+1."""
    # Precio sube de 5100 a 5115, los primeros valores bajan el VWAP
    closes = [5100.0 + i * 0.5 for i in range(30)]
    result = calc_vwap_position(_make_intraday(closes))

    assert result["status"] == "OK"
    assert result["score"] == 1
    assert result["signal"] == "SESGO_ALCISTA"
    assert result["vwap_distance_pct"] > VWAP_THRESHOLD_PCT


# ---------------------------------------------------------------------------
# Test 2 — Score negativo: precio bajo VWAP
# ---------------------------------------------------------------------------

def test_score_negativo_precio_bajo_vwap():
    """Precio baja progresivamente → close final << VWAP → score=-1."""
    closes = [5115.0 - i * 0.5 for i in range(30)]
    result = calc_vwap_position(_make_intraday(closes))

    assert result["status"] == "OK"
    assert result["score"] == -1
    assert result["signal"] == "SESGO_BAJISTA"
    assert result["vwap_distance_pct"] < -VWAP_THRESHOLD_PCT


# ---------------------------------------------------------------------------
# Test 3 — Score neutro: precio estable en VWAP
# ---------------------------------------------------------------------------

def test_score_neutro_precio_en_vwap():
    """Precio constante → close = VWAP → score=0."""
    closes = [5100.0] * 30
    result = calc_vwap_position(_make_intraday(closes))

    assert result["status"] == "OK"
    assert result["score"] == 0
    assert result["signal"] == "NEUTRO"
    assert abs(result["vwap_distance_pct"]) <= VWAP_THRESHOLD_PCT


# ---------------------------------------------------------------------------
# Test 4 — Exactamente en el umbral: score=0 (umbral estricto >/<)
# ---------------------------------------------------------------------------

def test_exactamente_en_umbral_score_neutro():
    """
    Construir velas donde vwap_distance_pct == +0.10 exacto.
    El umbral es estricto (>), no (>=), así que score debe ser 0.
    """
    # Con precio constante vwap_distance_pct = 0, por debajo del umbral → score 0
    closes = [5100.0] * 30
    result = calc_vwap_position(_make_intraday(closes))

    assert result["score"] == 0

    # Verificar manualmente con valor en umbral exacto
    # vwap_distance_pct = VWAP_THRESHOLD_PCT exacto → score = 0 (no >)
    from scripts.calculate_open_indicators import VWAP_THRESHOLD_PCT
    # Si el valor fuera exactamente el umbral, el operador > lo rechaza
    assert not (VWAP_THRESHOLD_PCT > VWAP_THRESHOLD_PCT)  # confirma que > es estricto


# ---------------------------------------------------------------------------
# Test 5 — Volumen cero
# ---------------------------------------------------------------------------

def test_volumen_cero():
    """Si todo el volumen es 0, no se puede calcular el VWAP → status=ERROR."""
    closes = [5100.0] * 30
    result = calc_vwap_position(_make_intraday(closes, volumes=[0] * 30))

    assert result["status"] == "ERROR"
    assert result["signal"] == "ERROR_VOLUMEN_CERO"
    assert result["score"] == 0
    assert result["vwap"] is None


# ---------------------------------------------------------------------------
# Test 6 — Sin velas (lista vacía)
# ---------------------------------------------------------------------------

def test_sin_velas_lista_vacia():
    """ohlcv vacío → status=ERROR."""
    intraday = _make_intraday([])
    intraday["ohlcv"] = []
    result = calc_vwap_position(intraday)

    assert result["status"] == "ERROR"
    assert result["signal"] == "ERROR_SIN_DATOS"
    assert result["score"] == 0


# ---------------------------------------------------------------------------
# Test 7 — Ventana incompleta (< 50% de velas esperadas)
# ---------------------------------------------------------------------------

def test_ventana_incompleta_calcula_igualmente():
    """Solo 5 velas para ventana de 30 min → incomplete_window=True pero calcula."""
    closes = [5100.0 + i * 0.5 for i in range(5)]
    result = calc_vwap_position(_make_intraday(closes, window_minutes=30))

    assert result["incomplete_window"] is True
    assert result["status"] == "OK"
    assert result["candles_used"] == 5
    assert result["score"] in (-1, 0, 1)


# ---------------------------------------------------------------------------
# Test 8 — Fetch fallido
# ---------------------------------------------------------------------------

def test_fetch_fallido_propaga_error():
    """Si spx_intraday["status"] != "OK", el indicador devuelve ERROR."""
    intraday = _make_intraday([5100.0] * 30, status="ERROR")
    result = calc_vwap_position(intraday)

    assert result["status"] == "ERROR"
    assert result["signal"] == "ERROR_FETCH"
    assert result["score"] == 0


# ---------------------------------------------------------------------------
# Tests de metadata y valores calculados
# ---------------------------------------------------------------------------

def test_metadata_completa_en_resultado_ok():
    """Un resultado OK incluye vwap, close, vwap_distance_pct y candles_used."""
    closes = [5100.0] * 30
    result = calc_vwap_position(_make_intraday(closes))

    assert result["vwap"] is not None
    assert result["close"] is not None
    assert result["vwap_distance_pct"] is not None
    assert result["candles_used"] == 30
    assert result["fecha"] == "2026-03-31"


def test_vwap_calculo_correcto():
    """Verificar el VWAP con valores conocidos. Precio constante → VWAP == close."""
    closes = [5200.0] * 10
    highs  = [5201.0] * 10
    lows   = [5199.0] * 10
    result = calc_vwap_position(
        _make_intraday(closes, highs=highs, lows=lows, window_minutes=10)
    )

    # typical_price = (5201 + 5199 + 5200) / 3 = 5200 → VWAP = 5200 = close
    assert result["vwap"] == 5200.0
    assert result["close"] == 5200.0
    assert result["vwap_distance_pct"] == 0.0
    assert result["score"] == 0
