import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from calculate_open_indicators import calc_vix_delta_open


def _make_vix_intraday(vix_open, vix_close, n_bars=30, window_minutes=30, status="OK"):
    """Construye un mock de fetch_vix_intraday con open y close controlados."""
    records = []
    for i in range(n_bars):
        close_i = round(vix_open + (vix_close - vix_open) * (i + 1) / n_bars, 2)
        records.append({
            "Datetime": f"2026-03-31 09:{30+i:02d}:00-04:00",
            "Open":  round(vix_open + (vix_close - vix_open) * i / n_bars, 2),
            "High":  round(close_i + 0.1, 2),
            "Low":   round(close_i - 0.1, 2),
            "Close": close_i,
        })
    if records:
        records[0]["Open"] = vix_open
    return {
        "ohlcv":          records if status == "OK" else None,
        "bars":           len(records),
        "window_minutes": window_minutes,
        "vix_open":       vix_open if records else None,
        "vix_close":      vix_close if records else None,
        "fecha":          "2026-03-31",
        "status":         status,
    }


# --- Tests de scoring ---

def test_vix_baja_mas_de_umbral():
    """VIX cae 0.70 puntos → IV comprimiéndose → score=+1"""
    result = calc_vix_delta_open(_make_vix_intraday(18.5, 17.8))
    assert result["vix_delta"] == -0.70
    assert result["score"] == 1
    assert result["signal"] == "IV_COMPRIMIENDO"
    assert result["status"] == "OK"


def test_vix_sube_mas_de_umbral():
    """VIX sube 0.80 puntos → IV expandiéndose → score=-1"""
    result = calc_vix_delta_open(_make_vix_intraday(17.0, 17.8))
    assert result["vix_delta"] == 0.80
    assert result["score"] == -1
    assert result["signal"] == "IV_EXPANDIENDO"
    assert result["status"] == "OK"


def test_movimiento_neutro():
    """VIX sube solo 0.30 puntos → dentro del umbral → score=0"""
    result = calc_vix_delta_open(_make_vix_intraday(17.0, 17.3))
    assert result["vix_delta"] == 0.30
    assert result["score"] == 0
    assert result["signal"] == "NEUTRO"


def test_umbral_exacto_negativo():
    """Exactamente -0.50 → umbral estricto → score=0, no IV_COMPRIMIENDO"""
    result = calc_vix_delta_open(_make_vix_intraday(18.0, 17.5))
    assert result["vix_delta"] == -0.50
    assert result["score"] == 0
    assert result["signal"] == "NEUTRO"


def test_umbral_exacto_positivo():
    """Exactamente +0.50 → umbral estricto → score=0, no IV_EXPANDIENDO"""
    result = calc_vix_delta_open(_make_vix_intraday(17.0, 17.5))
    assert result["vix_delta"] == 0.50
    assert result["score"] == 0
    assert result["signal"] == "NEUTRO"


def test_sin_velas_lista_vacia():
    """ohlcv vacío → ERROR_SIN_DATOS"""
    data = _make_vix_intraday(17.0, 17.5)
    data["ohlcv"] = []
    result = calc_vix_delta_open(data)
    assert result["status"] == "ERROR"
    assert result["signal"] == "ERROR_SIN_DATOS"
    assert result["score"] == 0


def test_fetch_fallido():
    """status=ERROR en el fetch → ERROR_FETCH"""
    result = calc_vix_delta_open(_make_vix_intraday(17.0, 17.5, status="ERROR"))
    assert result["status"] == "ERROR"
    assert result["signal"] == "ERROR_FETCH"
    assert result["score"] == 0


def test_ventana_incompleta():
    """5 velas para ventana de 30 → incomplete_window=True, calcula igualmente"""
    result = calc_vix_delta_open(_make_vix_intraday(18.5, 17.8, n_bars=5, window_minutes=30))
    assert result["incomplete_window"] is True
    assert result["status"] == "OK"
    assert result["score"] == 1
    assert result["signal"] == "IV_COMPRIMIENDO"


def test_vix_cae_mucho_evento():
    """VIX cae 2.50 puntos (evento de compresión) → score=+1"""
    result = calc_vix_delta_open(_make_vix_intraday(22.0, 19.5))
    assert result["vix_delta"] == -2.50
    assert result["score"] == 1
    assert result["signal"] == "IV_COMPRIMIENDO"


def test_vix_spike():
    """VIX sube 4.00 puntos (spike) → score=-1"""
    result = calc_vix_delta_open(_make_vix_intraday(17.0, 21.0))
    assert result["vix_delta"] == 4.00
    assert result["score"] == -1
    assert result["signal"] == "IV_EXPANDIENDO"


# --- Tests de campos del output ---

def test_campos_output_ok():
    """Verifica que todos los campos del output están presentes en caso OK"""
    result = calc_vix_delta_open(_make_vix_intraday(18.5, 17.8))
    assert "vix_open" in result
    assert "vix_close" in result
    assert "vix_delta" in result
    assert result["value"] == result["vix_delta"]   # alias
    assert "candles_used" in result
    assert "incomplete_window" in result
    assert result["fecha"] == "2026-03-31"
