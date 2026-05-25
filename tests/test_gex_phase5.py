"""
Tests Fase 5 — Narrativa automática: price paths, texto Dealer Flow, scorecard.
"""

import sys
import os
import io
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.gex_narrative import calc_price_paths, build_dealer_flow_text
from scripts.generate_scorecard import print_scorecard


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SPOT  = 5500.0
FECHA = "2026-05-23"


def _gex(call_wall=5600, put_wall=5400, flip=5480, max_pain=5550, spot=SPOT):
    return {
        "net_gex_bn":    6.5,
        "net_gex_by_dte": {"0dte": 2.0, "7dte": 4.0, "30dte": 6.5},
        "signal_gex":    "LONG_GAMMA_FUERTE",
        "score_gex":     3,
        "score_flip":    2,
        "score_wall_proximity": 0,
        "signal_flip":   "SOBRE_FLIP",
        "signal_wall_proximity": "ENTRE_WALLS",
        "flip_level":    float(flip),
        "call_wall":     float(call_wall),
        "put_wall":      float(put_wall),
        "max_pain":      float(max_pain),
        "chop_zone_low":  float(flip) - 5,
        "chop_zone_high": float(flip),
        "spot":          spot,
        "regime_text":   "Dealers LONG gamma (fuerte)",
        "status":        "OK",
        "fecha":         FECHA,
    }


def _charm(pin_zone=5500, charm_total=150_000, signal="EXPANSIVO"):
    return {
        "charm_signal":    signal,
        "charm_total":     charm_total,
        "charm_pin_zone":  float(pin_zone),
        "charm_pin_zone_conf": "ALTA",
        "charm_narrative": "test narrative",
        "charm_intraday":  [
            {"hora": "09:30", "charm_delta": 120_000, "signal": "EXPANSIVO"},
            {"hora": "11:00", "charm_delta": 180_000, "signal": "EXPANSIVO"},
            {"hora": "13:00", "charm_delta": 95_000,  "signal": "EXPANSIVO"},
            {"hora": "15:00", "charm_delta": 40_000,  "signal": "NEUTRO"},
            {"hora": "15:30", "charm_delta": -80_000, "signal": "SUPRESIVO"},
        ],
        "status": "OK",
        "fecha":  FECHA,
    }


def _dex(dex_total=-2.5, dex_flip=5490, signal="DEALERS_CORTO_DELTA"):
    return {
        "dex_total":         dex_total,
        "dex_flip":          float(dex_flip),
        "dex_positive_wall": SPOT + 75,
        "dex_negative_wall": SPOT - 75,
        "dex_signal":        signal,
        "dex_narrative":     "test",
        "status":            "OK",
        "fecha":             FECHA,
    }


def _pin(pinning_zone=5500, conf="ALTA"):
    return {
        "pinning_zone":      float(pinning_zone),
        "pinning_conf":      conf,
        "pinning_narrative": f"{pinning_zone} — confluencia GEX Wall + Charm.",
    }


def _full_indicators():
    return {
        "fecha":          FECHA,
        "net_gex":        _gex(),
        "charm_exposure": _charm(),
        "delta_exposure": _dex(),
        "pinning_zone":   _pin(),
        "vix_vxv_slope":  {"score": 1, "signal": "BACKWARDATION", "status": "OK"},
        "vix9d_vix_ratio": {"score": 1, "signal": "RATIO_ALTO", "status": "OK"},
        "overnight_gap":  {"score": 0, "signal": "GAP_NEUTRO", "status": "OK",
                           "gap_pct": 0.0, "es_prev": 5490.0, "es_curr": 5500.0},
        "ivr":            {"score": 2, "signal": "IVR_ALTO", "vix": 18.5, "ivr": 65, "status": "OK"},
        "atr_ratio":      {"score": 1, "signal": "ATR_ALTO", "atr_ratio": 1.3, "status": "OK"},
        "d_score":        7,
        "v_score":        3,
    }


# ---------------------------------------------------------------------------
# Tests: calc_price_paths
# ---------------------------------------------------------------------------

class TestPricePaths:

    def test_price_paths_returns_required_keys(self):
        r = calc_price_paths(_gex(), _charm(), _dex(), SPOT)
        for key in ("path_alcista", "path_bajista", "key_decision", "key_decision_desc"):
            assert key in r

    def test_path_alcista_starts_with_spot(self):
        r = calc_price_paths(_gex(), _charm(), _dex(), SPOT)
        assert r["path_alcista"][0] == SPOT

    def test_path_bajista_starts_with_spot(self):
        r = calc_price_paths(_gex(), _charm(), _dex(), SPOT)
        assert r["path_bajista"][0] == SPOT

    def test_path_alcista_all_above_spot(self):
        r = calc_price_paths(_gex(), _charm(), _dex(), SPOT)
        for lvl in r["path_alcista"][1:]:
            assert lvl > SPOT, f"Nivel alcista {lvl} no está sobre spot {SPOT}"

    def test_path_bajista_all_below_spot(self):
        r = calc_price_paths(_gex(), _charm(), _dex(), SPOT)
        for lvl in r["path_bajista"][1:]:
            assert lvl < SPOT, f"Nivel bajista {lvl} no está bajo spot {SPOT}"

    def test_path_alcista_max_4_levels(self):
        """Path alcista tiene spot + hasta 3 niveles = 4 elementos max."""
        r = calc_price_paths(_gex(), _charm(), _dex(), SPOT)
        assert len(r["path_alcista"]) <= 4

    def test_path_bajista_max_4_levels(self):
        r = calc_price_paths(_gex(), _charm(), _dex(), SPOT)
        assert len(r["path_bajista"]) <= 4

    def test_key_decision_near_flip(self):
        """Si flip_level está cerca del spot, debe ser key_decision."""
        g = _gex(flip=SPOT - 20)   # flip muy cerca del spot
        r = calc_price_paths(g, _charm(), _dex(), SPOT)
        assert r["key_decision"] is not None

    def test_no_crash_with_empty_inputs(self):
        r = calc_price_paths({}, {}, {}, 0)
        assert r["path_alcista"] == []
        assert r["path_bajista"] == []

    def test_no_crash_with_none_levels(self):
        g = _gex()
        g["call_wall"] = None
        g["put_wall"]  = None
        g["flip_level"] = None
        r = calc_price_paths(g, _charm(), _dex(), SPOT)
        # No debe crashear
        assert "path_alcista" in r


# ---------------------------------------------------------------------------
# Tests: build_dealer_flow_text
# ---------------------------------------------------------------------------

class TestDealerFlowText:

    def test_text_returns_string(self):
        text = build_dealer_flow_text(_full_indicators())
        assert isinstance(text, str)
        assert len(text) > 100

    def test_text_contains_fecha(self):
        text = build_dealer_flow_text(_full_indicators())
        assert FECHA in text

    def test_text_contains_key_levels(self):
        text = build_dealer_flow_text(_full_indicators())
        # Flip, call wall y put wall deben aparecer
        assert "5480" in text or "Flip" in text
        assert "5600" in text or "Call" in text
        assert "5400" in text or "Put"  in text

    def test_text_contains_charm_signal(self):
        text = build_dealer_flow_text(_full_indicators())
        assert "EXPANSIVO" in text

    def test_text_contains_paths(self):
        text = build_dealer_flow_text(_full_indicators())
        assert "↑" in text or "↓" in text

    def test_text_no_crash_empty_indicators(self):
        text = build_dealer_flow_text({})
        assert isinstance(text, str)

    def test_text_contains_gex_regime(self):
        text = build_dealer_flow_text(_full_indicators())
        assert "LONG_GAMMA" in text or "GEX" in text


# ---------------------------------------------------------------------------
# Tests: generate_scorecard — sección Dealer Flow
# ---------------------------------------------------------------------------

class TestScorecardDealerFlow:

    def test_scorecard_includes_charm_row(self):
        """El scorecard debe mostrar la línea de Charm Exposure."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            print_scorecard(_full_indicators())
        output = buf.getvalue()
        assert "Charm" in output

    def test_scorecard_includes_dex_row(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            print_scorecard(_full_indicators())
        output = buf.getvalue()
        assert "Delta" in output or "DEX" in output

    def test_scorecard_includes_pinning_zone(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            print_scorecard(_full_indicators())
        output = buf.getvalue()
        assert "Pin" in output or "PIN" in output

    def test_scorecard_includes_price_paths(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            print_scorecard(_full_indicators())
        output = buf.getvalue()
        assert "↑" in output or "↓" in output

    def test_scorecard_no_crash_without_dealer_flow(self):
        """Scorecard funciona sin las secciones de Dealer Flow."""
        ind = _full_indicators()
        del ind["charm_exposure"]
        del ind["delta_exposure"]
        del ind["pinning_zone"]
        buf = io.StringIO()
        with redirect_stdout(buf):
            print_scorecard(ind)
        output = buf.getvalue()
        assert "D-Score" in output
