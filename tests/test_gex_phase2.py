"""
Tests Fase 2 — GEX parametrizado por DTE.

Cubre:
  1. fetch_option_chain: firma max_dte, campo dte en contratos
  2. calc_net_gex: nuevo parámetro chain_30dte, net_gex_by_dte, retrocompat chain_multi
"""

import sys
import os
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.calculate_indicators import calc_net_gex
import scripts.fetch_market_data as fmd


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_contract(strike, option_type, oi, gamma=0.0001, delta=None, iv=0.2, dte=0):
    return {
        "strike":        strike,
        "option_type":   option_type,
        "open_interest": oi,
        "gamma":         gamma,
        "delta":         delta,
        "iv":            iv,
        "dte":           dte,
        "expiry":        "2026-05-23",
    }


def _make_chain(contracts, status="OK"):
    return {
        "contracts":   contracts,
        "expiries":    list({c["expiry"] for c in contracts}),
        "n_contracts": len(contracts),
        "status":      status,
    }


def _simple_chain_0dte():
    """Cadena 0DTE con calls y puts equilibrados."""
    return _make_chain([
        _make_contract(5500, "C", 100, gamma=0.0002, dte=0),
        _make_contract(5500, "P", 100, gamma=0.0002, dte=0),
        _make_contract(5550, "C", 200, gamma=0.0001, dte=0),
        _make_contract(5450, "P", 200, gamma=0.0001, dte=0),
    ])


def _simple_chain_30dte():
    """Cadena 30DTE con GEX positivo dominante."""
    return _make_chain([
        _make_contract(5500, "C", 500, gamma=0.0002, dte=0),
        _make_contract(5500, "P", 200, gamma=0.0002, dte=0),
        _make_contract(5500, "C", 300, gamma=0.0001, dte=7),
        _make_contract(5500, "P", 100, gamma=0.0001, dte=7),
    ])


def _simple_chain_7dte():
    """Cadena 7DTE."""
    return _make_chain([
        _make_contract(5500, "C", 300, gamma=0.0001, dte=7),
        _make_contract(5500, "P", 100, gamma=0.0001, dte=7),
    ])


SPOT = 5500.0
FECHA = "2026-05-23"


# ---------------------------------------------------------------------------
# Tests: net_gex_by_dte presente en el output
# ---------------------------------------------------------------------------

class TestNetGexByDte:

    def test_net_gex_by_dte_fields_present(self):
        """El output de calc_net_gex tiene el subcampo net_gex_by_dte con las tres claves."""
        result = calc_net_gex(
            chain_0dte=_simple_chain_0dte(),
            chain_30dte=_simple_chain_30dte(),
            spot=SPOT,
            fecha=FECHA,
        )
        assert "net_gex_by_dte" in result
        nbd = result["net_gex_by_dte"]
        assert "0dte"  in nbd
        assert "7dte"  in nbd
        assert "30dte" in nbd

    def test_net_gex_30dte_equals_net_gex_bn(self):
        """net_gex_by_dte['30dte'] debe ser igual al net_gex_bn cuando la cadena es la misma."""
        result = calc_net_gex(
            chain_0dte=_simple_chain_0dte(),
            chain_30dte=_simple_chain_30dte(),
            spot=SPOT,
            fecha=FECHA,
        )
        assert result["net_gex_by_dte"]["30dte"] == result["net_gex_bn"]

    def test_net_gex_0dte_not_none_when_chain_provided(self):
        """net_gex_by_dte['0dte'] no es None cuando chain_0dte tiene contratos con gamma."""
        result = calc_net_gex(
            chain_0dte=_simple_chain_0dte(),
            chain_30dte=_simple_chain_30dte(),
            spot=SPOT,
            fecha=FECHA,
        )
        assert result["net_gex_by_dte"]["0dte"] is not None

    def test_net_gex_7dte_not_none_when_chain_provided(self):
        """net_gex_by_dte['7dte'] no es None cuando chain_7dte tiene contratos."""
        result = calc_net_gex(
            chain_0dte=_simple_chain_0dte(),
            chain_30dte=_simple_chain_30dte(),
            chain_7dte=_simple_chain_7dte(),
            spot=SPOT,
            fecha=FECHA,
        )
        assert result["net_gex_by_dte"]["7dte"] is not None

    def test_net_gex_7dte_none_when_no_chain(self):
        """net_gex_by_dte['7dte'] es None cuando chain_7dte no se pasa."""
        result = calc_net_gex(
            chain_0dte=_simple_chain_0dte(),
            chain_30dte=_simple_chain_30dte(),
            spot=SPOT,
            fecha=FECHA,
        )
        assert result["net_gex_by_dte"]["7dte"] is None

    def test_net_gex_by_dte_30dte_gt_0dte(self):
        """
        La cadena 30DTE tiene más OI que la 0DTE, por lo que el Net GEX 30DTE
        debería ser mayor en valor absoluto que el 0DTE.
        """
        result = calc_net_gex(
            chain_0dte=_simple_chain_0dte(),
            chain_30dte=_simple_chain_30dte(),
            spot=SPOT,
            fecha=FECHA,
        )
        gex_0  = abs(result["net_gex_by_dte"]["0dte"] or 0)
        gex_30 = abs(result["net_gex_by_dte"]["30dte"] or 0)
        assert gex_30 >= gex_0


# ---------------------------------------------------------------------------
# Tests: retrocompatibilidad chain_multi
# ---------------------------------------------------------------------------

class TestChainMultiRetrocompat:

    def test_chain_multi_alias_works(self):
        """chain_multi como kwarg retroactivo produce el mismo resultado que chain_30dte."""
        result_new = calc_net_gex(
            chain_0dte=_simple_chain_0dte(),
            chain_30dte=_simple_chain_30dte(),
            spot=SPOT,
            fecha=FECHA,
        )
        result_old = calc_net_gex(
            chain_0dte=_simple_chain_0dte(),
            chain_multi=_simple_chain_30dte(),
            chain_30dte=None,
            spot=SPOT,
            fecha=FECHA,
        )
        assert result_new["net_gex_bn"] == result_old["net_gex_bn"]
        assert result_new["status"]     == result_old["status"]


# ---------------------------------------------------------------------------
# Tests: campo dte en contratos (simulado)
# ---------------------------------------------------------------------------

class TestDteField:

    def test_contract_has_dte_field(self):
        """Cada contrato fabricado por _make_contract tiene campo dte."""
        c = _make_contract(5500, "C", 100, dte=7)
        assert "dte" in c
        assert c["dte"] == 7

    def test_fetch_chain_max_dte_filters_expiries(self):
        """
        fetch_option_chain con max_dte=0 solo llama get_option_chain
        para el vencimiento de hoy (una sola iteración).
        """
        mock_client_instance = MagicMock()
        mock_client_instance.get_option_chain.return_value = [
            _make_contract(5500, "C", 100, dte=0)
        ]
        mock_client_class = MagicMock(return_value=mock_client_instance)

        original = fmd.TastyTradeClient
        fmd.TastyTradeClient = mock_client_class
        try:
            fmd.fetch_option_chain("SPXW", max_dte=0, spot=5500.0)
        finally:
            fmd.TastyTradeClient = original

        # Con max_dte=0, solo se debe llamar get_option_chain 1 vez
        assert mock_client_instance.get_option_chain.call_count == 1

    def test_fetch_chain_7dte_calls_8_times(self):
        """
        fetch_option_chain con max_dte=7 llama get_option_chain
        para los 8 días naturales (0..7 inclusive).
        """
        mock_client_instance = MagicMock()
        mock_client_instance.get_option_chain.return_value = []
        mock_client_class = MagicMock(return_value=mock_client_instance)

        original = fmd.TastyTradeClient
        fmd.TastyTradeClient = mock_client_class
        try:
            fmd.fetch_option_chain("SPXW", max_dte=7, spot=5500.0)
        finally:
            fmd.TastyTradeClient = original

        assert mock_client_instance.get_option_chain.call_count == 8

    def test_fetch_chain_adds_dte_field(self):
        """
        fetch_option_chain añade campo dte a contratos que no lo traen del cliente.
        """
        contract_no_dte = {
            "strike": 5500, "option_type": "C",
            "open_interest": 100, "gamma": 0.0001,
        }

        mock_client_instance = MagicMock()
        mock_client_instance.get_option_chain.return_value = [contract_no_dte]
        mock_client_class = MagicMock(return_value=mock_client_instance)

        original = fmd.TastyTradeClient
        fmd.TastyTradeClient = mock_client_class
        try:
            result = fmd.fetch_option_chain("SPXW", max_dte=0, spot=5500.0)
        finally:
            fmd.TastyTradeClient = original

        assert result["status"] == "OK"
        assert "dte" in result["contracts"][0]
        assert result["contracts"][0]["dte"] == 0
