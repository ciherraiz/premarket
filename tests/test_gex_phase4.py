"""
Tests Fase 4 — Visualizaciones: dashboard PNG, charm heatmap, GEX change chart.

Verifica que las funciones de generación de imágenes devuelven bytes PNG válidos
y no crashean en condiciones de datos vacíos o incompletos.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.gex_dashboard import build_premarket_dashboard
from scripts.gex_heatmap import build_charm_heatmap, build_gex_change_chart


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_png(data: bytes) -> bool:
    """Verifica la firma PNG (primeros 8 bytes)."""
    return data[:8] == b"\x89PNG\r\n\x1a\n"


def _minimal_indicators(
    net_gex_bn=5.0, spot=5500.0, fecha="2026-05-23",
    call_wall=5600.0, put_wall=5400.0, flip_level=5480.0,
) -> dict:
    return {
        "fecha": fecha,
        "net_gex": {
            "net_gex_bn":    net_gex_bn,
            "net_gex_by_dte": {"0dte": 2.0, "7dte": 3.5, "30dte": net_gex_bn},
            "signal_gex":    "LONG_GAMMA_FUERTE",
            "spot":          spot,
            "call_wall":     call_wall,
            "put_wall":      put_wall,
            "flip_level":    flip_level,
            "chop_zone_low": flip_level - 5,
            "chop_zone_high": flip_level,
            "gex_by_strike": {
                str(int(spot - 50)): -0.5,
                str(int(spot - 25)): -0.2,
                str(int(spot)):       0.8,
                str(int(spot + 25)):  1.2,
                str(int(spot + 50)):  0.6,
            },
        },
        "charm_exposure": {
            "charm_signal":    "EXPANSIVO",
            "charm_total":     150_000,
            "charm_pin_zone":  spot,
        },
        "delta_exposure": {
            "dex_cumulative": {
                str(int(spot - 50)): -0.8,
                str(int(spot - 25)): -0.3,
                str(int(spot)):       0.2,
                str(int(spot + 25)):  0.6,
                str(int(spot + 50)):  0.9,
            },
            "dex_flip": spot - 10,
        },
        "pinning_zone": {
            "pinning_zone": spot,
            "pinning_conf": "ALTA",
        },
    }


def _minimal_snapshot(ts: str, spot: float, fecha: str) -> dict:
    return {
        "timestamp":       ts,
        "fecha":           fecha,
        "spot":            spot,
        "charm_by_strike": {
            str(int(spot - 25)): -50_000.0,
            str(int(spot)):       120_000.0,
            str(int(spot + 25)): -30_000.0,
        },
        "charm_pin_zone":  spot,
    }


# ---------------------------------------------------------------------------
# Tests: build_premarket_dashboard
# ---------------------------------------------------------------------------

class TestPremarketDashboard:

    def test_dashboard_returns_png_bytes(self):
        img = build_premarket_dashboard(_minimal_indicators())
        assert isinstance(img, bytes)
        assert len(img) > 1000
        assert _is_png(img)

    def test_dashboard_empty_indicators(self):
        """No debe crashear con indicadores vacíos."""
        img = build_premarket_dashboard({})
        assert _is_png(img)

    def test_dashboard_no_crash_empty_charm(self):
        """Funciona si charm_exposure no está disponible."""
        ind = _minimal_indicators()
        del ind["charm_exposure"]
        img = build_premarket_dashboard(ind)
        assert _is_png(img)

    def test_dashboard_no_crash_empty_dex(self):
        """Funciona si delta_exposure no está disponible."""
        ind = _minimal_indicators()
        del ind["delta_exposure"]
        img = build_premarket_dashboard(ind)
        assert _is_png(img)

    def test_dashboard_no_crash_no_spot(self):
        """Funciona cuando spot es None."""
        ind = _minimal_indicators()
        ind["net_gex"]["spot"] = None
        img = build_premarket_dashboard(ind)
        assert _is_png(img)

    def test_dashboard_no_crash_no_gex_by_strike(self):
        """Funciona con gex_by_strike vacío."""
        ind = _minimal_indicators()
        ind["net_gex"]["gex_by_strike"] = {}
        img = build_premarket_dashboard(ind)
        assert _is_png(img)

    def test_dashboard_no_crash_empty_dex_cumulative(self):
        """Funciona con dex_cumulative vacío."""
        ind = _minimal_indicators()
        ind["delta_exposure"]["dex_cumulative"] = {}
        img = build_premarket_dashboard(ind)
        assert _is_png(img)


# ---------------------------------------------------------------------------
# Tests: build_charm_heatmap
# ---------------------------------------------------------------------------

class TestCharmHeatmap:

    def test_charm_heatmap_returns_png(self):
        """Con 3 snapshots válidos debe devolver PNG."""
        snaps = [
            _minimal_snapshot("2026-05-23T09:30:00", 5500, "2026-05-23"),
            _minimal_snapshot("2026-05-23T11:00:00", 5505, "2026-05-23"),
            _minimal_snapshot("2026-05-23T13:30:00", 5498, "2026-05-23"),
        ]
        img = build_charm_heatmap(snaps)
        assert _is_png(img)

    def test_charm_heatmap_empty_snapshots(self):
        """Lista vacía → PNG de 'Sin datos'."""
        img = build_charm_heatmap([])
        assert _is_png(img)

    def test_charm_heatmap_no_charm_data(self):
        """Snapshots sin charm_by_strike → PNG de 'Sin datos'."""
        snaps = [{"timestamp": "2026-05-23T09:30:00", "spot": 5500, "fecha": "2026-05-23"}]
        img = build_charm_heatmap(snaps)
        assert _is_png(img)

    def test_charm_heatmap_single_snapshot(self):
        """Un solo snapshot también genera PNG válido."""
        snaps = [_minimal_snapshot("2026-05-23T09:30:00", 5500, "2026-05-23")]
        img = build_charm_heatmap(snaps)
        assert _is_png(img)


# ---------------------------------------------------------------------------
# Tests: build_gex_change_chart
# ---------------------------------------------------------------------------

class TestGexChangeChart:

    def _gex_change_dict(self, spot=5500.0):
        return {
            "gex_change_by_strike": {
                str(int(spot - 50)): -0.3,
                str(int(spot - 25)): -0.1,
                str(int(spot)):       0.2,
                str(int(spot + 25)):  0.5,
                str(int(spot + 50)):  0.1,
            },
            "strikes_gaining": [spot + 25],
            "strikes_losing":  [spot - 50],
            "net_change":      0.4,
            "ref_ts":          "09:30",
            "curr_ts":         "11:00",
        }

    def test_gex_change_chart_returns_png(self):
        img = build_gex_change_chart(self._gex_change_dict(), 5500.0, "2026-05-23")
        assert _is_png(img)

    def test_gex_change_chart_empty(self):
        """Dict vacío → PNG de 'Sin datos'."""
        img = build_gex_change_chart({}, 5500.0)
        assert _is_png(img)

    def test_gex_change_chart_direct_dict(self):
        """Acepta también dict directo {strike: cambio} sin wrapper."""
        direct = {"5450": -0.3, "5500": 0.4, "5550": 0.1}
        img = build_gex_change_chart(direct, 5500.0)
        assert _is_png(img)
