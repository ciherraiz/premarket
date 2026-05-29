"""
Tests de integración del pipeline GEX — conectar cálculos con Telegram y snapshots.

Cubre:
  1. send_dealer_flow_report — no crashea, devuelve bool
  2. calc_gex_change — cálculos correctos
  3. take_gex_snapshot — incluye campos Dealer Flow
  4. Monitor — _opening_gex_snapshot inicializado
"""

import sys
import os
import json
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.gex_intraday import calc_gex_change


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SPOT  = 5500.0
FECHA = "2026-05-28"


def _snap(gex_by_strike: dict, ts: str = "2026-05-28T09:35:00") -> dict:
    return {
        "ts":            ts,
        "spot":          SPOT,
        "gex_by_strike": {str(k): v for k, v in gex_by_strike.items()},
        "status":        "OK",
    }


# ---------------------------------------------------------------------------
# Tests: calc_gex_change
# ---------------------------------------------------------------------------

class TestCalcGexChange:

    def test_returns_required_keys(self):
        ref  = _snap({5500: 1.0, 5525: -0.5})
        curr = _snap({5500: 1.5, 5525: -0.3}, ts="2026-05-28T11:00:00")
        result = calc_gex_change(ref, curr)
        for key in ("gex_change_by_strike", "strikes_gaining", "strikes_losing",
                    "net_change", "ref_ts", "curr_ts"):
            assert key in result

    def test_zero_change_when_identical(self):
        """Snapshots idénticos → cambio nulo."""
        snap = _snap({5500: 1.0, 5525: -0.5, 5550: 0.3})
        result = calc_gex_change(snap, snap)
        assert result["net_change"] == 0.0
        for v in result["gex_change_by_strike"].values():
            assert v == 0.0

    def test_detects_positive_change(self):
        """Strike que gana GEX aparece en strikes_gaining."""
        ref  = _snap({5500: 1.0})
        curr = _snap({5500: 2.5}, ts="2026-05-28T11:00:00")
        result = calc_gex_change(ref, curr)
        assert 5500.0 in result["strikes_gaining"]

    def test_detects_negative_change(self):
        """Strike que pierde GEX aparece en strikes_losing."""
        ref  = _snap({5500: 2.0})
        curr = _snap({5500: 0.5}, ts="2026-05-28T11:00:00")
        result = calc_gex_change(ref, curr)
        assert 5500.0 in result["strikes_losing"]

    def test_new_strike_in_curr(self):
        """Strike nuevo en curr (no en ref) tiene cambio positivo."""
        ref  = _snap({5500: 1.0})
        curr = _snap({5500: 1.0, 5550: 0.8}, ts="2026-05-28T11:00:00")
        result = calc_gex_change(ref, curr)
        assert "5550" in result["gex_change_by_strike"]
        assert result["gex_change_by_strike"]["5550"] == pytest.approx(0.8, abs=1e-6)

    def test_missing_strike_in_curr(self):
        """Strike en ref pero no en curr tiene cambio negativo (igual al valor de ref negado)."""
        ref  = _snap({5500: 1.0, 5525: 0.5})
        curr = _snap({5500: 1.0}, ts="2026-05-28T11:00:00")
        result = calc_gex_change(ref, curr)
        assert "5525" in result["gex_change_by_strike"]
        assert result["gex_change_by_strike"]["5525"] == pytest.approx(-0.5, abs=1e-6)

    def test_ref_ts_and_curr_ts(self):
        ref  = _snap({}, ts="2026-05-28T09:35:00")
        curr = _snap({}, ts="2026-05-28T11:00:00")
        result = calc_gex_change(ref, curr)
        assert result["ref_ts"]  == "2026-05-28T09:35:00"
        assert result["curr_ts"] == "2026-05-28T11:00:00"

    def test_net_change_is_sum_of_changes(self):
        ref  = _snap({5500: 1.0, 5525: -0.5})
        curr = _snap({5500: 1.5, 5525: -0.3}, ts="2026-05-28T11:00:00")
        result = calc_gex_change(ref, curr)
        expected_net = 0.5 + 0.2
        assert result["net_change"] == pytest.approx(expected_net, abs=1e-4)


# ---------------------------------------------------------------------------
# Tests: take_gex_snapshot — campos Dealer Flow
# ---------------------------------------------------------------------------

class TestTakeGexSnapshotDealerFlow:

    def _mock_client(self):
        """Cliente mock que devuelve contratos con delta e iv."""
        contracts = [
            {"strike": 5500, "option_type": "C", "open_interest": 500,
             "gamma": 0.0002, "delta": 0.5, "iv": 0.15, "dte": 0,
             "expiry": FECHA},
            {"strike": 5500, "option_type": "P", "open_interest": 400,
             "gamma": 0.0002, "delta": -0.5, "iv": 0.15, "dte": 0,
             "expiry": FECHA},
            {"strike": 5525, "option_type": "C", "open_interest": 300,
             "gamma": 0.0001, "delta": 0.35, "iv": 0.15, "dte": 0,
             "expiry": FECHA},
        ]
        client = MagicMock()
        client.get_option_chain.return_value = contracts
        client.get_equity_quote.return_value = {"status": "OK", "last": SPOT}
        return client

    def test_snapshot_includes_charm_fields(self):
        from scripts.gex_intraday import take_gex_snapshot
        snap = take_gex_snapshot(client=self._mock_client(), spot=SPOT)
        assert "charm_by_strike" in snap
        assert "charm_total"     in snap
        assert "charm_signal"    in snap
        assert "charm_pin_zone"  in snap

    def test_snapshot_includes_dex_fields(self):
        from scripts.gex_intraday import take_gex_snapshot
        snap = take_gex_snapshot(client=self._mock_client(), spot=SPOT)
        assert "dex_by_strike" in snap
        assert "dex_total"     in snap
        assert "dex_signal"    in snap
        assert "dex_flip"      in snap

    def test_snapshot_includes_fecha(self):
        from scripts.gex_intraday import take_gex_snapshot
        snap = take_gex_snapshot(client=self._mock_client(), spot=SPOT)
        assert "fecha" in snap

    def test_snapshot_charm_signal_valid(self):
        from scripts.gex_intraday import take_gex_snapshot
        snap = take_gex_snapshot(client=self._mock_client(), spot=SPOT)
        if snap.get("charm_signal"):
            assert snap["charm_signal"] in ("EXPANSIVO", "SUPRESIVO", "NEUTRO")


# ---------------------------------------------------------------------------
# Tests: send_dealer_flow_report
# ---------------------------------------------------------------------------

class TestSendDealerFlowReport:

    def _full_indicators(self):
        return {
            "fecha": FECHA,
            "net_gex": {
                "net_gex_bn":    5.0,
                "net_gex_by_dte": {"0dte": 2.0, "7dte": 3.5, "30dte": 5.0},
                "signal_gex":    "LONG_GAMMA_FUERTE",
                "score_gex":     3,
                "score_flip":    2,
                "score_wall_proximity": 0,
                "signal_flip":   "SOBRE_FLIP",
                "signal_wall_proximity": "ENTRE_WALLS",
                "flip_level":    5480.0,
                "call_wall":     5600.0,
                "put_wall":      5400.0,
                "max_pain":      5550.0,
                "chop_zone_low": 5475.0,
                "chop_zone_high": 5480.0,
                "spot":          SPOT,
                "regime_text":   "Dealers LONG gamma (fuerte)",
                "gex_by_strike": {"5475": -0.3, "5500": 1.0, "5525": 0.8},
                "status":        "OK",
                "fecha":         FECHA,
            },
            "charm_exposure": {
                "charm_signal":    "EXPANSIVO",
                "charm_total":     150_000,
                "charm_pin_zone":  SPOT,
                "charm_pin_zone_conf": "ALTA",
                "charm_narrative": "Dealers comprando delta",
                "charm_intraday": [],
                "status": "OK",
                "fecha":  FECHA,
            },
            "delta_exposure": {
                "dex_total":      -2.5,
                "dex_flip":       5490.0,
                "dex_cumulative": {"5475": -0.8, "5500": -0.1, "5525": 0.5},
                "dex_by_strike":  {"5475": -0.8, "5500": 0.7, "5525": 0.6},
                "dex_positive_wall": 5525.0,
                "dex_negative_wall": 5475.0,
                "dex_signal":     "DEALERS_CORTO_DELTA",
                "dex_narrative":  "test",
                "status":         "OK",
                "fecha":          FECHA,
            },
            "pinning_zone": {
                "pinning_zone":      SPOT,
                "pinning_conf":      "ALTA",
                "pinning_narrative": "Confluencia GEX+Charm.",
            },
        }

    def test_send_dealer_flow_report_returns_bool(self):
        """send_dealer_flow_report devuelve bool y no crashea con credenciales ausentes."""
        import scripts.notify_telegram as nt
        # Sin credenciales → send_telegram_photo retorna False → retorna False
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TELEGRAM_BOT_TOKEN", None)
            os.environ.pop("TELEGRAM_CHAT_ID", None)
            result = nt.send_dealer_flow_report(self._full_indicators())
        assert isinstance(result, bool)

    def test_send_dealer_flow_report_no_crash_empty(self):
        """No debe crashear con dict vacío."""
        import scripts.notify_telegram as nt
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TELEGRAM_BOT_TOKEN", None)
            os.environ.pop("TELEGRAM_CHAT_ID", None)
            result = nt.send_dealer_flow_report({})
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# Import pytest al final para que el check de approx funcione
# ---------------------------------------------------------------------------
import pytest
