import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.calculate_indicators import calc_vix_vxv_slope


def _make(vix, vxv):
    return {"vix": vix, "vxv": vxv, "fecha": "2026-03-29"}


def test_contango_fuerte():
    result = calc_vix_vxv_slope(_make(13.5, 18.2))
    assert result["ratio"] == 0.7418
    assert result["score"] == 2
    assert result["signal"] == "CONTANGO_FUERTE"
    assert result["status"] == "OK"


def test_contango_suave():
    # 15.5 / 18.2 = 0.8516 → zona CONTANGO_SUAVE (0.83 ≤ ratio < 0.90)
    result = calc_vix_vxv_slope(_make(15.5, 18.2))
    assert result["ratio"] == 0.8516
    assert result["score"] == 1
    assert result["signal"] == "CONTANGO_SUAVE"
    assert result["status"] == "OK"


def test_neutro():
    result = calc_vix_vxv_slope(_make(16.5, 18.2))
    assert result["ratio"] == 0.9066
    assert result["score"] == 0
    assert result["signal"] == "NEUTRO"
    assert result["status"] == "OK"


def test_tension():
    result = calc_vix_vxv_slope(_make(17.5, 18.2))
    assert result["ratio"] == 0.9615
    assert result["score"] == -1
    assert result["signal"] == "TENSION"
    assert result["status"] == "OK"


def test_backwardation():
    result = calc_vix_vxv_slope(_make(19.0, 18.2))
    assert result["ratio"] == 1.044
    assert result["score"] == -2
    assert result["signal"] == "BACKWARDATION"
    assert result["status"] == "OK"


def test_vxv_cero():
    result = calc_vix_vxv_slope(_make(16.0, 0))
    assert result["score"] == 0
    assert result["status"] == "ERROR"


def test_vix_ausente():
    result = calc_vix_vxv_slope(_make(None, 18.2))
    assert result["score"] == 0
    assert result["status"] == "MISSING_DATA"


def test_vxv_ausente():
    result = calc_vix_vxv_slope(_make(16.0, None))
    assert result["score"] == 0
    assert result["status"] == "MISSING_DATA"
