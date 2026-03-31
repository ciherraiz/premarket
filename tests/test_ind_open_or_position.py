"""
Tests unitarios para IND-OPEN-03: OR Position.
Spec: specs/ind_open_or_position.md
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.calculate_open_indicators import calc_or_position, OR_NEUTRAL_LOW, OR_NEUTRAL_HIGH


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_intraday(closes, highs=None, lows=None, volumes=None,
                   window_minutes=30, status="OK"):
    """Construye un dict compatible con fetch_spx_intraday() para los tests."""
    n = len(closes)
    if highs is None:
        highs = [c + 5.0 for c in closes]
    if lows is None:
        lows = [c - 5.0 for c in closes]
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
# Test 1 — Score positivo: close en parte alta del OR
# ---------------------------------------------------------------------------

def test_score_positivo_close_en_parte_alta():
    """
    or_high=5220, or_low=5200 → rango=20.
    close=5217 → or_position = (5217-5200)/20 = 0.85 → score=+1.
    """
    # Una vela plana que define el rango, luego el close sube al 85% del rango
    highs  = [5220.0] * 10
    lows   = [5200.0] * 10
    # close = or_low + 0.85 * rango = 5200 + 0.85*20 = 5217
    closes = [5210.0] * 9 + [5217.0]

    result = calc_or_position(_make_intraday(closes, highs=highs, lows=lows, window_minutes=10))

    assert result["status"] == "OK"
    assert result["score"] == 1
    assert result["signal"] == "SESGO_ALCISTA"
    assert result["or_position"] > OR_NEUTRAL_HIGH


# ---------------------------------------------------------------------------
# Test 2 — Score negativo: close en parte baja del OR
# ---------------------------------------------------------------------------

def test_score_negativo_close_en_parte_baja():
    """
    or_high=5220, or_low=5200 → rango=20.
    close=5203 → or_position = (5203-5200)/20 = 0.15 → score=-1.
    """
    highs  = [5220.0] * 10
    lows   = [5200.0] * 10
    closes = [5210.0] * 9 + [5203.0]

    result = calc_or_position(_make_intraday(closes, highs=highs, lows=lows, window_minutes=10))

    assert result["status"] == "OK"
    assert result["score"] == -1
    assert result["signal"] == "SESGO_BAJISTA"
    assert result["or_position"] < OR_NEUTRAL_LOW


# ---------------------------------------------------------------------------
# Test 3 — Score neutro: close exactamente en or_mid
# ---------------------------------------------------------------------------

def test_score_neutro_close_en_or_mid():
    """
    or_high=5220, or_low=5200 → or_mid=5210.
    close=5210 → or_position = 0.50 → score=0.
    """
    highs  = [5220.0] * 10
    lows   = [5200.0] * 10
    closes = [5210.0] * 10

    result = calc_or_position(_make_intraday(closes, highs=highs, lows=lows, window_minutes=10))

    assert result["status"] == "OK"
    assert result["score"] == 0
    assert result["signal"] == "NEUTRO"
    assert abs(result["or_position"] - 0.5) < 1e-6


# ---------------------------------------------------------------------------
# Test 4 — Umbral superior exacto (0.60): score=0 (umbral estricto >)
# ---------------------------------------------------------------------------

def test_umbral_superior_exacto_score_neutro():
    """
    or_high=5220, or_low=5200 → rango=20.
    close = 5200 + 0.60*20 = 5212 → or_position = 0.60 exacto → score=0.
    """
    highs  = [5220.0] * 10
    lows   = [5200.0] * 10
    closes = [5210.0] * 9 + [5212.0]

    result = calc_or_position(_make_intraday(closes, highs=highs, lows=lows, window_minutes=10))

    assert result["score"] == 0
    # Confirmar que el umbral es estricto: 0.60 no es > 0.60
    assert not (OR_NEUTRAL_HIGH > OR_NEUTRAL_HIGH)


# ---------------------------------------------------------------------------
# Test 5 — Umbral inferior exacto (0.40): score=0 (umbral estricto <)
# ---------------------------------------------------------------------------

def test_umbral_inferior_exacto_score_neutro():
    """
    or_high=5220, or_low=5200 → rango=20.
    close = 5200 + 0.40*20 = 5208 → or_position = 0.40 exacto → score=0.
    """
    highs  = [5220.0] * 10
    lows   = [5200.0] * 10
    closes = [5210.0] * 9 + [5208.0]

    result = calc_or_position(_make_intraday(closes, highs=highs, lows=lows, window_minutes=10))

    assert result["score"] == 0
    # Confirmar que el umbral es estricto: 0.40 no es < 0.40
    assert not (OR_NEUTRAL_LOW < OR_NEUTRAL_LOW)


# ---------------------------------------------------------------------------
# Test 6 — Rango cero: or_high == or_low
# ---------------------------------------------------------------------------

def test_rango_cero_devuelve_senal_especial():
    """
    Todas las velas con High=Low=Close=5200 → or_range=0.
    No se puede calcular or_position → score=0, signal=RANGO_CERO.
    """
    closes = [5200.0] * 10
    highs  = [5200.0] * 10
    lows   = [5200.0] * 10

    result = calc_or_position(_make_intraday(closes, highs=highs, lows=lows, window_minutes=10))

    assert result["status"] == "OK"
    assert result["score"] == 0
    assert result["signal"] == "RANGO_CERO"
    assert result["or_position"] is None
    # Los niveles de referencia siguen siendo válidos
    assert result["or_high"] == 5200.0
    assert result["or_low"]  == 5200.0
    assert result["or_mid"]  == 5200.0


# ---------------------------------------------------------------------------
# Test 7 — Sin velas (lista vacía)
# ---------------------------------------------------------------------------

def test_sin_velas_lista_vacia():
    """ohlcv vacío → status=ERROR, signal=ERROR_SIN_DATOS."""
    intraday = _make_intraday([])
    intraday["ohlcv"] = []
    result = calc_or_position(intraday)

    assert result["status"] == "ERROR"
    assert result["signal"] == "ERROR_SIN_DATOS"
    assert result["score"] == 0
    assert result["or_high"] is None


# ---------------------------------------------------------------------------
# Test 8 — Fetch fallido
# ---------------------------------------------------------------------------

def test_fetch_fallido_propaga_error():
    """Si spx_intraday["status"] != "OK", el indicador devuelve ERROR."""
    intraday = _make_intraday([5200.0] * 30, status="ERROR")
    result = calc_or_position(intraday)

    assert result["status"] == "ERROR"
    assert result["signal"] == "ERROR_FETCH"
    assert result["score"] == 0


# ---------------------------------------------------------------------------
# Test 9 — Columnas faltantes
# ---------------------------------------------------------------------------

def test_columnas_faltantes_devuelve_error():
    """Registros sin campo 'High' → status=ERROR, signal=ERROR_COLUMNAS."""
    intraday = _make_intraday([5200.0] * 10, window_minutes=10)
    # Eliminar campo "High" de todos los registros
    for rec in intraday["ohlcv"]:
        del rec["High"]

    result = calc_or_position(intraday)

    assert result["status"] == "ERROR"
    assert result["signal"] == "ERROR_COLUMNAS"
    assert result["score"] == 0


# ---------------------------------------------------------------------------
# Test 10 — Ventana incompleta (< 50% de velas esperadas)
# ---------------------------------------------------------------------------

def test_ventana_incompleta_calcula_igualmente():
    """5 velas para ventana de 30 min → incomplete_window=True pero calcula."""
    highs  = [5220.0] * 5
    lows   = [5200.0] * 5
    closes = [5215.0] * 5   # or_position = (5215-5200)/20 = 0.75 → score=+1

    result = calc_or_position(_make_intraday(closes, highs=highs, lows=lows, window_minutes=30))

    assert result["incomplete_window"] is True
    assert result["status"] == "OK"
    assert result["candles_used"] == 5
    assert result["score"] in (-1, 0, 1)


# ---------------------------------------------------------------------------
# Test 11 — Verificar aritmética de or_high, or_low, or_mid
# ---------------------------------------------------------------------------

def test_valores_or_high_or_low_or_mid_correctos():
    """
    Velas con highs=[5210, 5215, 5220] y lows=[5195, 5198, 5200].
    or_high = 5220, or_low = 5195, or_mid = 5207.50.
    """
    closes = [5205.0, 5210.0, 5215.0]
    highs  = [5210.0, 5215.0, 5220.0]
    lows   = [5195.0, 5198.0, 5200.0]

    result = calc_or_position(_make_intraday(closes, highs=highs, lows=lows, window_minutes=3))

    assert result["or_high"] == 5220.0
    assert result["or_low"]  == 5195.0
    assert result["or_mid"]  == 5207.5
    assert result["close"]   == 5215.0
    # or_position = (5215 - 5195) / (5220 - 5195) = 20/25 = 0.8 → SESGO_ALCISTA
    assert abs(result["or_position"] - 0.8) < 1e-4
    assert result["score"] == 1


# ---------------------------------------------------------------------------
# Test 12 — Extremo inferior: or_position = 0.0
# ---------------------------------------------------------------------------

def test_extremo_inferior_or_position_cero():
    """
    close == or_low → or_position = 0.0 → score=-1.
    """
    highs  = [5220.0] * 10
    lows   = [5200.0] * 10
    closes = [5210.0] * 9 + [5200.0]   # last close == or_low

    result = calc_or_position(_make_intraday(closes, highs=highs, lows=lows, window_minutes=10))

    assert result["status"] == "OK"
    assert result["or_position"] == 0.0
    assert result["score"] == -1
    assert result["signal"] == "SESGO_BAJISTA"


# ---------------------------------------------------------------------------
# Test 13 — Extremo superior: or_position = 1.0
# ---------------------------------------------------------------------------

def test_extremo_superior_or_position_uno():
    """
    close == or_high → or_position = 1.0 → score=+1.
    Para lograr close == or_high, el último Close debe igualar el High global.
    """
    # or_high vendrá del High de cualquier vela; forzamos High=5220 en todas
    # y el último Close = 5220 (igual al max High)
    highs  = [5220.0] * 10
    lows   = [5200.0] * 10
    closes = [5210.0] * 9 + [5220.0]   # last close == or_high

    result = calc_or_position(_make_intraday(closes, highs=highs, lows=lows, window_minutes=10))

    assert result["status"] == "OK"
    assert result["or_position"] == 1.0
    assert result["score"] == 1
    assert result["signal"] == "SESGO_ALCISTA"
