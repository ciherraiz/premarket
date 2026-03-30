import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.calculate_indicators import calc_overnight_gap


def _make(es, spx_close):
    return (
        {"spx_prev_close": spx_close, "fecha": "2026-03-29"},
        {"es_premarket": es, "fecha": "2026-03-29"},
    )


def test_gap_alcista_moderado():
    spx, es = _make(5100.0, 5080.0)
    result = calc_overnight_gap(spx, es)
    assert result["gap_pct"] == 0.3937
    assert result["score"] == 1
    assert result["signal"] == "GAP_ALCISTA"
    assert result["status"] == "OK"


def test_gap_bajista_moderado():
    spx, es = _make(5060.0, 5080.0)
    result = calc_overnight_gap(spx, es)
    assert result["gap_pct"] == -0.3937
    assert result["score"] == -1
    assert result["signal"] == "GAP_BAJISTA"
    assert result["status"] == "OK"


def test_gap_plano():
    spx, es = _make(5081.0, 5080.0)
    result = calc_overnight_gap(spx, es)
    assert result["gap_pct"] == 0.0197
    assert result["score"] == 0
    assert result["signal"] == "PLANO"
    assert result["status"] == "OK"


def test_gap_alcista_grande():
    spx, es = _make(5130.0, 5080.0)
    result = calc_overnight_gap(spx, es)
    assert result["gap_pct"] == 0.9843
    assert result["score"] == 0
    assert result["signal"] == "GAP_ALCISTA_GRANDE"
    assert result["status"] == "OK"


def test_gap_bajista_grande():
    spx, es = _make(5000.0, 5080.0)
    result = calc_overnight_gap(spx, es)
    assert result["gap_pct"] == -1.5748
    assert result["score"] == 0
    assert result["signal"] == "GAP_BAJISTA_GRANDE"
    assert result["status"] == "OK"


def test_limite_exacto_mas_010():
    spx, es = _make(5085.08, 5080.0)
    result = calc_overnight_gap(spx, es)
    assert result["gap_pct"] == 0.1000
    assert result["score"] == 1
    assert result["signal"] == "GAP_ALCISTA"
    assert result["status"] == "OK"


def test_limite_exacto_mas_050():
    spx, es = _make(5105.40, 5080.0)
    result = calc_overnight_gap(spx, es)
    assert result["gap_pct"] == 0.5000
    assert result["score"] == 1
    assert result["signal"] == "GAP_ALCISTA"
    assert result["status"] == "OK"


def test_limite_exacto_menos_050():
    spx, es = _make(5054.60, 5080.0)
    result = calc_overnight_gap(spx, es)
    assert result["gap_pct"] == -0.5000
    assert result["score"] == -1
    assert result["signal"] == "GAP_BAJISTA"
    assert result["status"] == "OK"


def test_es_precio_none():
    spx, es = _make(None, 5080.0)
    result = calc_overnight_gap(spx, es)
    assert result["score"] == 0
    assert result["status"] == "MISSING_DATA"


def test_spx_cierre_none():
    spx, es = _make(5100.0, None)
    result = calc_overnight_gap(spx, es)
    assert result["score"] == 0
    assert result["status"] == "MISSING_DATA"


def test_es_precio_cero():
    spx, es = _make(0, 5080.0)
    result = calc_overnight_gap(spx, es)
    assert result["score"] == 0
    assert result["status"] == "ERROR"


def test_spx_cierre_cero():
    spx, es = _make(5100.0, 0)
    result = calc_overnight_gap(spx, es)
    assert result["score"] == 0
    assert result["status"] == "ERROR"
