"""
Tests Fase 3 — Nuevos cálculos: Charm Exposure, Delta Exposure, Pinning Zone.

Cubre:
  1. calc_charm_exposure — signo, total, pin zone, proyección intraday
  2. calc_delta_exposure — DEX acumulado, flip, walls, señal
  3. calc_pinning_zone   — confluencia GEX+charm, confianza
"""

import sys
import os
import math

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.calculate_indicators import (
    calc_charm_exposure,
    calc_delta_exposure,
    calc_pinning_zone,
    _SESSION_HOURS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SPOT  = 5500.0
FECHA = "2026-05-23"


def _make_contract(strike, otype, oi, gamma=0.0001, delta=None, iv=0.2, dte=0):
    return {
        "strike":        strike,
        "option_type":   otype,
        "open_interest": oi,
        "gamma":         gamma,
        "delta":         delta,
        "iv":            iv,
        "dte":           dte,
        "expiry":        "2026-05-23",
    }


def _chain(contracts, status="OK"):
    return {
        "contracts":   contracts,
        "expiries":    ["2026-05-23"],
        "n_contracts": len(contracts),
        "status":      status,
    }


# ---------------------------------------------------------------------------
# Tests: calc_charm_exposure
# ---------------------------------------------------------------------------

class TestCharmExposure:

    def _call_atm_chain(self):
        """Calls ATM con IV alta — charm alto."""
        return _chain([
            _make_contract(SPOT,       "C", 500, iv=0.15, dte=0),
            _make_contract(SPOT + 25,  "C", 300, iv=0.15, dte=0),
            _make_contract(SPOT - 25,  "P", 300, iv=0.15, dte=0),
        ])

    def _put_heavy_chain(self):
        """Puts con mucho OI — charm total negativo dominante."""
        return _chain([
            _make_contract(SPOT - 50, "P", 1000, iv=0.2, dte=0),
            _make_contract(SPOT,      "P", 1000, iv=0.2, dte=0),
            _make_contract(SPOT + 50, "C", 100,  iv=0.2, dte=0),
        ])

    def test_charm_exposure_returns_required_keys(self):
        result = calc_charm_exposure(self._call_atm_chain(), SPOT, FECHA)
        for key in ("charm_by_strike", "charm_total", "charm_signal",
                    "charm_narrative", "charm_pin_zone", "charm_pin_zone_conf",
                    "charm_intraday", "status", "fecha"):
            assert key in result, f"Falta clave: {key}"

    def test_charm_total_not_none_with_valid_chain(self):
        result = calc_charm_exposure(self._call_atm_chain(), SPOT, FECHA)
        assert result["status"] == "OK"
        assert result["charm_total"] is not None

    def test_charm_total_sign_coherent_with_signal(self):
        """Si charm_total > THRESHOLD → EXPANSIVO; si < -THRESHOLD → SUPRESIVO."""
        from scripts.calculate_indicators import CHARM_SIGNAL_THRESHOLD
        result = calc_charm_exposure(self._call_atm_chain(), SPOT, FECHA)
        total  = result["charm_total"]
        signal = result["charm_signal"]
        if total is not None:
            if total > CHARM_SIGNAL_THRESHOLD:
                assert signal == "EXPANSIVO"
            elif total < -CHARM_SIGNAL_THRESHOLD:
                assert signal == "SUPRESIVO"
            else:
                assert signal == "NEUTRO"

    def test_charm_pin_zone_within_atm_range(self):
        """charm_pin_zone debe estar dentro de ±50 pts del spot."""
        from scripts.calculate_indicators import CHARM_PIN_ATM_RANGE
        result = calc_charm_exposure(self._call_atm_chain(), SPOT, FECHA)
        pin = result["charm_pin_zone"]
        if pin is not None:
            assert abs(pin - SPOT) <= CHARM_PIN_ATM_RANGE

    def test_charm_intraday_has_session_entries(self):
        """charm_intraday debe tener una entrada por hora de sesión."""
        result = calc_charm_exposure(self._call_atm_chain(), SPOT, FECHA)
        assert len(result["charm_intraday"]) == len(_SESSION_HOURS)

    def test_charm_intraday_entry_structure(self):
        """Cada entrada de charm_intraday tiene hora, charm_delta y signal."""
        result = calc_charm_exposure(self._call_atm_chain(), SPOT, FECHA)
        for entry in result["charm_intraday"]:
            assert "hora"        in entry
            assert "charm_delta" in entry
            assert "signal"      in entry
            assert entry["signal"] in ("EXPANSIVO", "SUPRESIVO", "NEUTRO")

    def test_charm_status_missing_data_when_no_spot(self):
        result = calc_charm_exposure(self._call_atm_chain(), 0, FECHA)
        assert result["status"] == "MISSING_DATA"

    def test_charm_empty_chain_propagates_status(self):
        result = calc_charm_exposure(_chain([], status="EMPTY_CHAIN"), SPOT, FECHA)
        assert result["status"] == "EMPTY_CHAIN"

    def test_charm_no_iv_returns_no_iv_data(self):
        """Cadena con todos los IV=None → status NO_IV_DATA."""
        contracts = [
            _make_contract(SPOT, "C", 100, iv=None, dte=0),
            _make_contract(SPOT, "P", 100, iv=None, dte=0),
        ]
        result = calc_charm_exposure(_chain(contracts), SPOT, FECHA)
        assert result["status"] == "NO_IV_DATA"

    def test_charm_by_strike_keys_are_strings(self):
        result = calc_charm_exposure(self._call_atm_chain(), SPOT, FECHA)
        for k in result["charm_by_strike"]:
            assert isinstance(k, str)


# ---------------------------------------------------------------------------
# Tests: calc_delta_exposure
# ---------------------------------------------------------------------------

class TestDeltaExposure:

    def _call_heavy_chain(self):
        """Calls con delta positivo dominante."""
        return _chain([
            _make_contract(SPOT,       "C", 500, delta=0.5,  dte=0),
            _make_contract(SPOT + 50,  "C", 300, delta=0.3,  dte=0),
            _make_contract(SPOT - 50,  "P", 100, delta=-0.3, dte=0),
        ])

    def _put_heavy_chain(self):
        """Puts con delta negativo dominante."""
        return _chain([
            _make_contract(SPOT - 50, "P", 800, delta=-0.5, dte=0),
            _make_contract(SPOT,      "P", 500, delta=-0.4, dte=0),
            _make_contract(SPOT + 50, "C", 100, delta=0.3,  dte=0),
        ])

    def _flip_chain(self):
        """Cadena diseñada para que el DEX acumulado cruce el cero."""
        return _chain([
            _make_contract(5400, "P", 1000, delta=-0.6, dte=0),
            _make_contract(5450, "P", 200,  delta=-0.4, dte=0),
            _make_contract(5500, "C", 1500, delta=0.5,  dte=0),
            _make_contract(5550, "C", 500,  delta=0.3,  dte=0),
        ])

    def test_dex_returns_required_keys(self):
        result = calc_delta_exposure(self._call_heavy_chain(), SPOT, FECHA)
        for key in ("dex_by_strike", "dex_cumulative", "dex_total",
                    "dex_flip", "dex_positive_wall", "dex_negative_wall",
                    "dex_signal", "dex_narrative", "status", "fecha"):
            assert key in result, f"Falta clave: {key}"

    def test_dex_total_positive_call_heavy(self):
        """Con calls dominantes, DEX total debe ser positivo."""
        result = calc_delta_exposure(self._call_heavy_chain(), SPOT, FECHA)
        assert result["status"] == "OK"
        assert result["dex_total"] is not None
        assert result["dex_total"] > 0

    def test_dex_total_negative_put_heavy(self):
        """Con puts dominantes, DEX total debe ser negativo."""
        result = calc_delta_exposure(self._put_heavy_chain(), SPOT, FECHA)
        assert result["dex_total"] < 0

    def test_dex_signal_largo_when_positive(self):
        result = calc_delta_exposure(self._call_heavy_chain(), SPOT, FECHA)
        assert result["dex_signal"] == "DEALERS_LARGO_DELTA"

    def test_dex_signal_corto_when_negative(self):
        result = calc_delta_exposure(self._put_heavy_chain(), SPOT, FECHA)
        assert result["dex_signal"] == "DEALERS_CORTO_DELTA"

    def test_dex_flip_zero_crossing(self):
        """DEX flip debe estar en el strike donde el acumulado cruza cero."""
        result = calc_delta_exposure(self._flip_chain(), SPOT, FECHA)
        # Con puts dominantes bajos y calls dominantes altos, debe haber flip
        # Si hay flip, verificar que el DEX acumulado cambia de signo ahí
        flip = result["dex_flip"]
        if flip is not None:
            cum = result["dex_cumulative"]
            strikes_sorted = sorted(float(k) for k in cum)
            idx = strikes_sorted.index(float(flip))
            if idx > 0:
                prev_strike = str(int(strikes_sorted[idx - 1]))
                curr_strike = str(int(flip))
                prev_val = cum.get(prev_strike, 0)
                curr_val = cum.get(curr_strike, 0)
                # Los signos deben ser diferentes
                assert (prev_val >= 0) != (curr_val >= 0)

    def test_dex_cumulative_monotonic_count(self):
        """El DEX acumulado debe tener tantas entradas como strikes únicos."""
        result = calc_delta_exposure(self._call_heavy_chain(), SPOT, FECHA)
        assert len(result["dex_cumulative"]) == len(result["dex_by_strike"])

    def test_dex_status_missing_when_no_spot(self):
        result = calc_delta_exposure(self._call_heavy_chain(), 0, FECHA)
        assert result["status"] == "MISSING_DATA"

    def test_dex_no_delta_data(self):
        """Cadena sin campo delta → status NO_DELTA_DATA."""
        contracts = [
            _make_contract(SPOT, "C", 100, delta=None, dte=0),
        ]
        result = calc_delta_exposure(_chain(contracts), SPOT, FECHA)
        assert result["status"] == "NO_DELTA_DATA"


# ---------------------------------------------------------------------------
# Tests: calc_pinning_zone
# ---------------------------------------------------------------------------

class TestPinningZone:

    def _gex_result(self, call_wall=5550, put_wall=5450, gex_0dte=5.0):
        return {
            "call_wall": call_wall,
            "put_wall":  put_wall,
            "net_gex_by_dte": {"0dte": gex_0dte, "7dte": 8.0, "30dte": 10.0},
        }

    def _charm_result(self, charm_pin_zone=5500, charm_total=200_000):
        return {
            "charm_pin_zone":      charm_pin_zone,
            "charm_pin_zone_conf": "ALTA",
            "charm_total":         charm_total,
        }

    def test_pinning_zone_returns_required_keys(self):
        result = calc_pinning_zone(self._gex_result(), self._charm_result(), SPOT)
        for key in ("pinning_zone", "pinning_conf", "pinning_narrative"):
            assert key in result

    def test_pinning_zone_confluence_alta(self):
        """Cuando GEX wall y charm coinciden en el mismo strike → confianza ALTA."""
        # Charm pin zone == call_wall del GEX (mismo strike)
        result = calc_pinning_zone(
            self._gex_result(call_wall=5550),
            self._charm_result(charm_pin_zone=5550),
            SPOT,
        )
        assert result["pinning_conf"] == "ALTA"
        assert result["pinning_zone"] == 5550

    def test_pinning_zone_solo_charm_baja_or_media(self):
        """Solo Charm activo (GEX walls fuera de rango) → MEDIA o BAJA."""
        result = calc_pinning_zone(
            self._gex_result(call_wall=5800, put_wall=5200),  # walls lejos del spot
            self._charm_result(charm_pin_zone=SPOT),
            SPOT,
        )
        assert result["pinning_conf"] in ("MEDIA", "BAJA")

    def test_pinning_zone_ninguna_when_far(self):
        """Ni walls ni charm near spot → NINGUNA."""
        result = calc_pinning_zone(
            self._gex_result(call_wall=5800, put_wall=5200),
            {"charm_pin_zone": None, "charm_total": 0},
            SPOT,
        )
        assert result["pinning_conf"] == "NINGUNA"
        assert result["pinning_zone"] is None

    def test_pinning_zone_no_crash_with_empty_gex(self):
        """No debe fallar con gex_result vacío."""
        result = calc_pinning_zone({}, self._charm_result(), SPOT)
        assert "pinning_zone" in result

    def test_pinning_zone_no_crash_with_zero_spot(self):
        result = calc_pinning_zone(self._gex_result(), self._charm_result(), 0)
        assert result["pinning_zone"] is None
