import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.calculate_indicators import calc_vix9d_vix_ratio


def _make(vix9d, vix):
    return {"vix9d": vix9d, "vix": vix, "fecha": "2026-03-28"}


def test_contango_pronunciado():
    result = calc_vix9d_vix_ratio(_make(13.5, 16.2))
    assert result["ratio"] == 0.8333
    assert result["score"] == 2
    assert result["signal"] == "CONTANGO_FUERTE"
    assert result["status"] == "OK"


def test_neutro():
    result = calc_vix9d_vix_ratio(_make(15.8, 16.2))
    assert result["ratio"] == 0.9753
    assert result["score"] == 0
    assert result["signal"] == "NEUTRO"
    assert result["status"] == "OK"


def test_tension_incipiente():
    # 16.53 / 16.2 = 1.0204 → zona TENSION (1.02 ≤ ratio < 1.05)
    # El spec usa 16.5/16.2=1.0185 que cae en NEUTRO: inconsistencia del spec.
    result = calc_vix9d_vix_ratio(_make(16.53, 16.2))
    assert result["ratio"] == 1.0204
    assert result["score"] == -1
    assert result["signal"] == "TENSION"
    assert result["status"] == "OK"


def test_backwardation():
    result = calc_vix9d_vix_ratio(_make(17.5, 16.2))
    assert result["ratio"] == 1.0802
    assert result["score"] == -2
    assert result["signal"] == "BACKWARDATION"
    assert result["status"] == "OK"


def test_vix_cero():
    result = calc_vix9d_vix_ratio(_make(15.0, 0))
    assert result["score"] == 0
    assert result["status"] == "ERROR"


def test_dato_ausente():
    result = calc_vix9d_vix_ratio(_make(None, 16.2))
    assert result["score"] == 0
    assert result["status"] == "MISSING_DATA"
