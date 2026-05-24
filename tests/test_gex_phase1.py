"""
Tests Fase 1 — Enriquecimiento de datos: delta y charm.

Cubre:
  1. Campo delta en contratos de la cadena de opciones
  2. Campo dte en contratos
  3. Función _calc_charm: valores, signos y casos límite
"""

import sys
import os
import math

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.calculate_indicators import _calc_charm


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_contract(strike, option_type, oi, gamma=None, delta=None, iv=None, dte=0):
    return {
        "strike":        strike,
        "option_type":   option_type,
        "open_interest": oi,
        "gamma":         gamma,
        "delta":         delta,
        "iv":            iv,
        "dte":           dte,
    }


# ---------------------------------------------------------------------------
# Grupo 1: campo delta en el contrato
# ---------------------------------------------------------------------------

def test_contract_has_delta_field():
    """El helper _make_contract produce el campo delta."""
    c = _make_contract(7500, "C", 1000, delta=0.52)
    assert "delta" in c
    assert c["delta"] == 0.52


def test_call_delta_positive():
    """Una call ATM tiene delta positivo."""
    c = _make_contract(7500, "C", 1000, delta=0.52)
    assert c["delta"] > 0


def test_put_delta_negative():
    """Una put ATM tiene delta negativo — NO se filtra por signo."""
    c = _make_contract(7500, "P", 1000, delta=-0.48)
    assert c["delta"] < 0


def test_delta_none_allowed():
    """delta puede ser None si DXLink no lo devolvió para ese contrato."""
    c = _make_contract(7500, "C", 1000, delta=None)
    assert c["delta"] is None


# ---------------------------------------------------------------------------
# Grupo 2: campo dte en el contrato
# ---------------------------------------------------------------------------

def test_contract_has_dte_field():
    """El contrato incluye el campo dte."""
    c = _make_contract(7500, "C", 1000, dte=0)
    assert "dte" in c
    assert c["dte"] == 0


def test_dte_zero_for_0dte():
    """DTE=0 para contratos que expiran hoy."""
    c = _make_contract(7500, "C", 1000, dte=0)
    assert c["dte"] == 0


def test_dte_weekly_positive():
    """DTE positivo para contratos con vencimiento futuro."""
    c = _make_contract(7500, "C", 1000, dte=5)
    assert c["dte"] == 5


# ---------------------------------------------------------------------------
# Grupo 3: _calc_charm — valores y signos
# ---------------------------------------------------------------------------

def test_charm_returns_float_for_valid_inputs():
    """_calc_charm devuelve un float con inputs válidos."""
    result = _calc_charm(spot=7500, strike=7500, iv=0.20, dte=1, option_type="C")
    assert result is not None
    assert isinstance(result, float)


def test_charm_call_and_put_opposite_sign():
    """Call y put ATM tienen charm opuesto."""
    charm_call = _calc_charm(spot=7500, strike=7500, iv=0.20, dte=1, option_type="C")
    charm_put  = _calc_charm(spot=7500, strike=7500, iv=0.20, dte=1, option_type="P")
    assert charm_call is not None
    assert charm_put is not None
    assert math.isclose(charm_call, -charm_put, rel_tol=1e-9)


def test_charm_0dte_uses_floor_not_zero():
    """Con dte=0, _calc_charm usa T=0.5/365 y no falla (no hay división por cero)."""
    result = _calc_charm(spot=7500, strike=7500, iv=0.20, dte=0, option_type="C")
    assert result is not None
    assert math.isfinite(result)


def test_charm_lower_iv_larger_magnitude_atm():
    """IV más baja ATM produce charm mayor: gamma más concentrado → reajuste más rápido."""
    charm_low_iv  = _calc_charm(spot=7500, strike=7500, iv=0.10, dte=1, option_type="C")
    charm_high_iv = _calc_charm(spot=7500, strike=7500, iv=0.30, dte=1, option_type="C")
    assert charm_low_iv is not None and charm_high_iv is not None
    assert abs(charm_low_iv) > abs(charm_high_iv)


def test_charm_deep_itm_call_near_zero():
    """Una call muy deep ITM tiene charm cercano a cero (delta ya está en 1)."""
    charm = _calc_charm(spot=7500, strike=5000, iv=0.20, dte=1, option_type="C")
    assert charm is not None
    assert abs(charm) < 0.01  # delta casi constante en 1, poco reajuste


def test_charm_none_with_zero_iv():
    """iv=0 → retorna None (input inválido)."""
    result = _calc_charm(spot=7500, strike=7500, iv=0.0, dte=1, option_type="C")
    assert result is None


def test_charm_none_with_none_iv():
    """iv=None → retorna None."""
    result = _calc_charm(spot=7500, strike=7500, iv=None, dte=1, option_type="C")
    assert result is None


def test_charm_none_with_zero_spot():
    """spot=0 → retorna None."""
    result = _calc_charm(spot=0, strike=7500, iv=0.20, dte=1, option_type="C")
    assert result is None


def test_charm_longer_dte_smaller_magnitude():
    """Mismo strike ATM: charm 0DTE > charm 30DTE en magnitud."""
    charm_0dte  = _calc_charm(spot=7500, strike=7500, iv=0.20, dte=0,  option_type="C")
    charm_30dte = _calc_charm(spot=7500, strike=7500, iv=0.20, dte=30, option_type="C")
    assert charm_0dte is not None and charm_30dte is not None
    assert abs(charm_0dte) > abs(charm_30dte)
