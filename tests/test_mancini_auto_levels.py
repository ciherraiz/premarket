"""Tests para el módulo de niveles técnicos autónomos (auto_levels.py)."""

import json
import os
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.mancini.auto_levels import (
    AutoLevels,
    TechnicalLevel,
    build_auto_levels,
    calc_pivot_points,
    calc_round_numbers,
    fetch_overnight_ohlc,
    load_auto_levels,
    save_auto_levels,
    _dedup_levels,
)
from scripts.mancini.monitor import _auto_levels_to_plan


# ── calc_pivot_points ──────────────────────────────────────────────────

class TestCalcPivotPoints:

    def test_valores_conocidos(self):
        # PP = (110 + 90 + 100) / 3 = 100
        result = calc_pivot_points(high=110.0, low=90.0, close=100.0)
        assert result["PP"] == 100.0
        assert result["R1"] == pytest.approx(110.0, abs=0.1)   # 2*100 - 90
        assert result["R2"] == pytest.approx(120.0, abs=0.1)   # 100 + 20
        assert result["S1"] == pytest.approx(90.0, abs=0.1)    # 2*100 - 110
        assert result["S2"] == pytest.approx(80.0, abs=0.1)    # 100 - 20

    def test_retorna_cinco_claves(self):
        result = calc_pivot_points(5400.0, 5300.0, 5350.0)
        assert set(result.keys()) == {"PP", "R1", "R2", "S1", "S2"}

    def test_valores_redondeados_a_dos_decimales(self):
        result = calc_pivot_points(5401.33, 5298.66, 5350.01)
        for v in result.values():
            assert v == round(v, 2)


# ── calc_round_numbers ─────────────────────────────────────────────────

class TestCalcRoundNumbers:

    def test_con_spot_5350_step_25(self):
        levels = calc_round_numbers(5350.0, step=25, pct=0.03)
        assert 5350.0 in levels
        assert 5375.0 in levels
        assert 5325.0 in levels
        # fuera del rango ±3% = ±160.5 → no debe aparecer 5100
        assert 5100.0 not in levels

    def test_todos_son_multiplos_del_step(self):
        levels = calc_round_numbers(5250.0, step=25, pct=0.03)
        for l in levels:
            assert l % 25 == 0.0

    def test_rango_correcto(self):
        spot = 5000.0
        pct = 0.02
        levels = calc_round_numbers(spot, step=50, pct=pct)
        for l in levels:
            assert (spot - spot * pct) <= l <= (spot + spot * pct)

    def test_lista_vacia_si_no_hay_multiplos(self):
        # step=1000 con spot=500 y pct=0.01 → rango [495, 505] → 0 múltiplos de 1000
        levels = calc_round_numbers(500.0, step=1000, pct=0.01)
        assert levels == []


# ── _dedup_levels ──────────────────────────────────────────────────────

class TestDedupLevels:

    def test_elimina_niveles_proximos(self):
        lvls = [
            TechnicalLevel(value=5300.0, label="A", group="daily", priority=2),
            TechnicalLevel(value=5301.0, label="B", group="round", priority=3),
        ]
        result = _dedup_levels(lvls, threshold=2.0)
        assert len(result) == 1

    def test_conserva_mayor_prioridad(self):
        lvls = [
            TechnicalLevel(value=5300.0, label="FLIP", group="gex", priority=1),
            TechnicalLevel(value=5300.5, label="RND_5300", group="round", priority=3),
        ]
        result = _dedup_levels(lvls, threshold=2.0)
        assert len(result) == 1
        assert result[0].label == "FLIP"

    def test_conserva_niveles_lejanos(self):
        lvls = [
            TechnicalLevel(value=5300.0, label="A", group="daily", priority=2),
            TechnicalLevel(value=5310.0, label="B", group="weekly", priority=1),
        ]
        result = _dedup_levels(lvls, threshold=2.0)
        assert len(result) == 2


# ── build_auto_levels ──────────────────────────────────────────────────

DAILY_OHLCV = [
    {"Date": "2026-04-23", "Open": 5300.0, "High": 5350.0, "Low": 5280.0, "Close": 5320.0, "Volume": 1000000},
    {"Date": "2026-04-24", "Open": 5320.0, "High": 5380.0, "Low": 5310.0, "Close": 5360.0, "Volume": 1200000},
    {"Date": "2026-04-25", "Open": 5360.0, "High": 5400.0, "Low": 5340.0, "Close": 5370.0, "Volume": 900000},
]

WEEKLY_DATA = pd.DataFrame({
    "Open":  [5200.0, 5280.0, 5300.0],
    "High":  [5250.0, 5320.0, 5380.0],
    "Low":   [5180.0, 5260.0, 5290.0],
    "Close": [5230.0, 5310.0, 5360.0],
})

MONTHLY_DATA = pd.DataFrame({
    "Open":  [5100.0, 5300.0],
    "High":  [5200.0, 5400.0],
    "Low":   [5050.0, 5250.0],
    "Close": [5150.0, 5350.0],
})

GEX = {
    "flip_level": 5340.0,
    "put_wall":   5300.0,
    "call_wall":  5400.0,
}


class TestBuildAutoLevels:

    def test_contiene_niveles_diarios(self):
        auto = build_auto_levels(DAILY_OHLCV, None, None, 5370.0, {})
        labels = {l.label for l in auto.levels}
        assert "PDH" in labels
        assert "PDL" in labels
        assert "PDC" in labels
        assert "PP_D" in labels

    def test_contiene_niveles_semanales(self):
        auto = build_auto_levels(DAILY_OHLCV, WEEKLY_DATA, None, 5370.0, {})
        labels = {l.label for l in auto.levels}
        assert "PWH" in labels
        assert "PWL" in labels
        assert "PP_W" in labels

    def test_contiene_niveles_mensuales(self):
        auto = build_auto_levels(DAILY_OHLCV, None, MONTHLY_DATA, 5370.0, {})
        labels = {l.label for l in auto.levels}
        assert "PMH" in labels
        assert "PML" in labels

    def test_contiene_gex_levels(self):
        auto = build_auto_levels(DAILY_OHLCV, None, None, 5370.0, GEX)
        labels = {l.label for l in auto.levels}
        assert "FLIP" in labels
        assert "PUT_WALL" in labels
        assert "CALL_WALL" in labels

    def test_contiene_round_numbers(self):
        auto = build_auto_levels(DAILY_OHLCV, None, None, 5370.0, {})
        groups = {l.group for l in auto.levels}
        assert "round" in groups

    def test_ordenados_descendente(self):
        auto = build_auto_levels(DAILY_OHLCV, WEEKLY_DATA, MONTHLY_DATA, 5370.0, GEX)
        values = [l.value for l in auto.levels]
        assert values == sorted(values, reverse=True)

    def test_sin_datos_ohlcv_no_lanza_error(self):
        auto = build_auto_levels([], None, None, 5370.0, {})
        assert auto is not None
        assert auto.levels is not None

    def test_spot_guardado_correctamente(self):
        auto = build_auto_levels(DAILY_OHLCV, None, None, 5370.25, {})
        assert auto.spot == 5370.25

    def test_fecha_es_hoy(self):
        auto = build_auto_levels(DAILY_OHLCV, None, None, 5370.0, {})
        assert auto.fecha == str(date.today())

    def test_basis_correction_aplica_ratio(self):
        # SPX=5360, ES=5380 → ratio=1.00373
        # PDH en SPX = 5380 → PDH ajustado = 5380 * (5380/5360) ≈ 5400.1
        auto_adj = build_auto_levels(DAILY_OHLCV, None, None, 5380.0, {}, spx_spot=5360.0)
        auto_raw = build_auto_levels(DAILY_OHLCV, None, None, 5380.0, {}, spx_spot=None)

        pdh_adj = next(l for l in auto_adj.levels if l.label == "PDH")
        pdh_raw = next(l for l in auto_raw.levels if l.label == "PDH")

        assert pdh_adj.value > pdh_raw.value  # ajustado debe ser mayor (ES > SPX)
        ratio = 5380.0 / 5360.0
        assert pdh_adj.value == pytest.approx(pdh_raw.value * ratio, abs=0.1)

    def test_basis_correction_no_afecta_round_numbers(self):
        # Los round numbers deben ser múltiplos exactos de 25 centrados en es_spot,
        # independientemente de spx_spot (no se multiplican por el ratio de basis)
        es_spot = 5380.0
        auto_adj = build_auto_levels(DAILY_OHLCV, None, None, es_spot, {}, spx_spot=5360.0)

        for lvl in auto_adj.levels:
            if lvl.group == "round":
                assert lvl.value % 25 == 0.0, f"{lvl.value} no es múltiplo de 25"
                assert abs(lvl.value - es_spot) <= es_spot * 0.03 + 25

    def test_basis_sin_spx_spot_no_modifica_valores(self):
        auto = build_auto_levels(DAILY_OHLCV, None, None, 5370.0, {}, spx_spot=None)
        auto_explicit_1 = build_auto_levels(DAILY_OHLCV, None, None, 5370.0, {})

        vals1 = [l.value for l in auto.levels]
        vals2 = [l.value for l in auto_explicit_1.levels]
        assert vals1 == vals2


# ── load/save_auto_levels ──────────────────────────────────────────────

class TestPersistence:

    def test_roundtrip(self, tmp_path):
        path = tmp_path / "auto_levels.json"
        auto = build_auto_levels(DAILY_OHLCV, WEEKLY_DATA, MONTHLY_DATA, 5370.0, GEX)
        save_auto_levels(auto, path)
        loaded = load_auto_levels(path)
        assert loaded is not None
        assert loaded.fecha == auto.fecha
        assert loaded.spot == auto.spot
        assert len(loaded.levels) == len(auto.levels)
        assert loaded.levels[0].label == auto.levels[0].label

    def test_load_retorna_none_si_no_existe(self, tmp_path):
        result = load_auto_levels(tmp_path / "noexiste.json")
        assert result is None

    def test_load_retorna_none_si_json_invalido(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("no es json", encoding="utf-8")
        result = load_auto_levels(path)
        assert result is None


# ── _auto_levels_to_plan ───────────────────────────────────────────────

class TestAutoLevelsToPlan:

    def _make_auto(self, levels_data: list[dict]) -> AutoLevels:
        levels = [TechnicalLevel(**l) for l in levels_data]
        return AutoLevels(
            fecha=str(date.today()),
            spot=5370.0,
            levels=sorted(levels, key=lambda l: l.value, reverse=True),
            calculated_at="2026-04-26T09:00:00",
        )

    def test_selecciona_mas_cercano_arriba_y_abajo(self):
        auto = self._make_auto([
            {"value": 5400.0, "label": "PWH",  "group": "weekly", "priority": 1},
            {"value": 5380.0, "label": "FLIP",  "group": "gex",    "priority": 1},
            {"value": 5350.0, "label": "PWL",  "group": "weekly", "priority": 1},
            {"value": 5330.0, "label": "PP_W", "group": "weekly", "priority": 1},
        ])
        plan = _auto_levels_to_plan(auto, 5370.0)
        assert plan is not None
        assert plan.key_level_upper == 5380.0  # más cercano por encima
        assert plan.key_level_lower == 5350.0  # más cercano por debajo

    def test_retorna_none_si_no_hay_nivel_por_encima(self):
        auto = self._make_auto([
            {"value": 5350.0, "label": "PWL", "group": "weekly", "priority": 1},
            {"value": 5330.0, "label": "PP_W", "group": "weekly", "priority": 1},
        ])
        plan = _auto_levels_to_plan(auto, 5370.0)
        assert plan is None

    def test_retorna_none_si_no_hay_nivel_por_debajo(self):
        auto = self._make_auto([
            {"value": 5390.0, "label": "PWH", "group": "weekly", "priority": 1},
            {"value": 5410.0, "label": "FLIP", "group": "gex",   "priority": 1},
        ])
        plan = _auto_levels_to_plan(auto, 5370.0)
        assert plan is None

    def test_retorna_none_si_niveles_priority1_fuera_de_50pts(self):
        auto = self._make_auto([
            {"value": 5450.0, "label": "PMH", "group": "monthly", "priority": 1},
            {"value": 5290.0, "label": "PML", "group": "monthly", "priority": 1},
        ])
        plan = _auto_levels_to_plan(auto, 5370.0)
        assert plan is None  # ambos a >50 pts

    def test_plan_tiene_is_stale_y_is_auto_levels(self):
        auto = self._make_auto([
            {"value": 5380.0, "label": "FLIP", "group": "gex",    "priority": 1},
            {"value": 5350.0, "label": "PWL",  "group": "weekly", "priority": 1},
        ])
        plan = _auto_levels_to_plan(auto, 5370.0)
        assert plan is not None
        assert plan.is_stale is True
        assert plan.is_auto_levels is True

    def test_plan_raw_tweets_tiene_prefijo_auto(self):
        auto = self._make_auto([
            {"value": 5380.0, "label": "FLIP", "group": "gex",    "priority": 1},
            {"value": 5350.0, "label": "PWL",  "group": "weekly", "priority": 1},
        ])
        plan = _auto_levels_to_plan(auto, 5370.0)
        assert plan is not None
        assert plan.raw_tweets[0].startswith("[AUTO]")

    def test_ignora_niveles_priority_2_y_3(self):
        # Solo hay priority=2 y priority=3 — debe retornar None
        auto = self._make_auto([
            {"value": 5380.0, "label": "PDH",     "group": "daily", "priority": 2},
            {"value": 5350.0, "label": "RND_5350", "group": "round", "priority": 3},
        ])
        plan = _auto_levels_to_plan(auto, 5370.0)
        assert plan is None


# ── Integración: monitor load_state con auto-levels ────────────────────

class TestMonitorLoadStateAutoLevels:

    @pytest.fixture
    def paths(self, tmp_path):
        return {
            "plan":     tmp_path / "plan.json",
            "state":    tmp_path / "state.json",
            "weekly":   tmp_path / "weekly.json",
            "intraday": tmp_path / "intraday.json",
            "auto":     tmp_path / "auto_levels.json",
        }

    @pytest.fixture(autouse=True)
    def mock_today(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        ET = ZoneInfo("America/New_York")
        fake_now = datetime(2026, 4, 26, 9, 30, 0, tzinfo=ET)
        with patch("scripts.mancini.monitor._now_et", return_value=fake_now):
            yield

    @pytest.fixture(autouse=True)
    def mock_notifier(self):
        with patch("scripts.mancini.monitor.notifier"):
            yield

    def test_usa_auto_levels_si_no_hay_plan(self, paths):
        from scripts.mancini.monitor import ManciniMonitor, AUTO_LEVELS_PATH

        # Crear auto_levels de hoy
        auto = build_auto_levels(DAILY_OHLCV, WEEKLY_DATA, None, 5370.0, GEX)
        save_auto_levels(auto, paths["auto"])

        monitor = ManciniMonitor(
            client=None,
            plan_path=paths["plan"],
            state_path=paths["state"],
            weekly_path=paths["weekly"],
            intraday_path=paths["intraday"],
            gate_enabled=False,
        )
        with patch("scripts.mancini.monitor.AUTO_LEVELS_PATH", paths["auto"]):
            with patch("scripts.mancini.monitor.load_auto_levels") as mock_load:
                mock_load.return_value = auto
                monitor.load_state(current_price=5370.0)

        assert monitor.plan is not None
        assert monitor.plan.is_auto_levels is True
        assert monitor.plan.is_stale is True

    def test_no_usa_auto_levels_si_hay_plan_hoy(self, paths):
        from scripts.mancini.monitor import ManciniMonitor
        from scripts.mancini.config import DailyPlan, save_plan

        today_plan = DailyPlan(
            fecha="2026-04-26",
            key_level_upper=5380.0,
            targets_upper=[5395.0],
            key_level_lower=5350.0,
            targets_lower=[5335.0],
        )
        save_plan(today_plan, paths["plan"])

        monitor = ManciniMonitor(
            client=None,
            plan_path=paths["plan"],
            state_path=paths["state"],
            weekly_path=paths["weekly"],
            intraday_path=paths["intraday"],
            gate_enabled=False,
        )
        monitor.load_state(current_price=5370.0)

        assert monitor.plan is not None
        assert monitor.plan.is_auto_levels is False
        assert monitor.plan.is_stale is False
        assert monitor.plan.fecha == "2026-04-26"


# ── fetch_overnight_ohlc ───────────────────────────────────────────────

def _make_hourly_df(rows: list[dict]) -> pd.DataFrame:
    """Crea un DataFrame de barras horarias con index tz-aware (UTC)."""
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
    index = pd.to_datetime([r["ts"] for r in rows], utc=True)
    df = pd.DataFrame(
        {"High": [r["h"] for r in rows], "Low": [r["l"] for r in rows]},
        index=index,
    )
    return df


class TestFetchOvernightOhlc:

    def test_retorna_onh_onl_de_barras_overnight(self):
        """Con barras dentro de la ventana 18:00–09:29 ET, retorna (max_high, min_low)."""
        from zoneinfo import ZoneInfo
        from datetime import datetime as dt
        ET = ZoneInfo("America/New_York")
        # Simulamos "hoy" = 2026-04-26 09:00 ET
        fake_now = dt(2026, 4, 26, 9, 0, 0, tzinfo=ET)

        rows = [
            # Dentro de ventana: 2026-04-25 18:00, 20:00, 2026-04-26 02:00, 08:00
            {"ts": "2026-04-25 22:00:00+00:00", "h": 5200.0, "l": 5190.0},  # 18:00 ET
            {"ts": "2026-04-26 00:00:00+00:00", "h": 5210.0, "l": 5185.0},  # 20:00 ET
            {"ts": "2026-04-26 06:00:00+00:00", "h": 5195.0, "l": 5180.0},  # 02:00 ET
            {"ts": "2026-04-26 12:00:00+00:00", "h": 5205.0, "l": 5182.0},  # 08:00 ET
            # Fuera de ventana: 2026-04-26 10:00 ET (RTH)
            {"ts": "2026-04-26 14:00:00+00:00", "h": 5220.0, "l": 5150.0},
        ]
        df = _make_hourly_df(rows)

        with patch("scripts.mancini.auto_levels.yf.download", return_value=df), \
             patch("scripts.mancini.auto_levels.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: __import__("datetime").datetime(*a, **kw)
            result = fetch_overnight_ohlc()

        assert result is not None
        onh, onl = result
        assert onh == pytest.approx(5210.0, abs=0.1)  # max dentro de ventana
        assert onl == pytest.approx(5180.0, abs=0.1)  # min dentro de ventana

    def test_retorna_none_si_dataframe_vacio(self):
        empty_df = pd.DataFrame()
        with patch("scripts.mancini.auto_levels.yf.download", return_value=empty_df):
            result = fetch_overnight_ohlc()
        assert result is None

    def test_retorna_none_si_yfinance_lanza_excepcion(self):
        with patch("scripts.mancini.auto_levels.yf.download", side_effect=Exception("timeout")):
            result = fetch_overnight_ohlc()
        assert result is None

    def test_retorna_none_si_no_hay_barras_en_ventana(self):
        """Si todas las barras están fuera del rango overnight, retorna None."""
        from zoneinfo import ZoneInfo
        from datetime import datetime as dt
        ET = ZoneInfo("America/New_York")
        fake_now = dt(2026, 4, 26, 9, 0, 0, tzinfo=ET)

        # Solo barra RTH: 2026-04-26 14:00 UTC = 10:00 ET (fuera de ventana)
        rows = [{"ts": "2026-04-26 14:00:00+00:00", "h": 5220.0, "l": 5150.0}]
        df = _make_hourly_df(rows)

        with patch("scripts.mancini.auto_levels.yf.download", return_value=df), \
             patch("scripts.mancini.auto_levels.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: __import__("datetime").datetime(*a, **kw)
            result = fetch_overnight_ohlc()

        assert result is None


class TestOvernightEnBuildAutoLevels:

    def test_overnight_niveles_presentes(self):
        """Con overnight=(5210, 5180), ONH y ONL aparecen en los niveles."""
        auto = build_auto_levels(DAILY_OHLCV, None, None, 5370.0, {},
                                 overnight=(5210.0, 5180.0))
        labels = {l.label for l in auto.levels}
        assert "ONH" in labels
        assert "ONL" in labels

    def test_overnight_none_no_añade_niveles(self):
        """Sin overnight, no se añaden niveles de grupo overnight."""
        auto = build_auto_levels(DAILY_OHLCV, None, None, 5370.0, {}, overnight=None)
        grupos = {l.group for l in auto.levels}
        assert "overnight" not in grupos

    def test_overnight_group_y_priority(self):
        """ONH/ONL tienen group=overnight y priority=2."""
        auto = build_auto_levels(DAILY_OHLCV, None, None, 5370.0, {},
                                 overnight=(5210.0, 5180.0))
        onh = next(l for l in auto.levels if l.label == "ONH")
        onl = next(l for l in auto.levels if l.label == "ONL")
        assert onh.group == "overnight"
        assert onl.group == "overnight"
        assert onh.priority == 2
        assert onl.priority == 2

    def test_overnight_no_recibe_basis_adjustment(self):
        """ONH/ONL no se ven afectados por el ratio SPX→ES (ya son /ES)."""
        # Con basis=1.003, los niveles diarios/semanales se ajustan,
        # pero ONH/ONL deben mantenerse en su valor original.
        auto = build_auto_levels(DAILY_OHLCV, None, None, 5380.0, {},
                                 spx_spot=5360.0, overnight=(5210.0, 5180.0))
        onh = next(l for l in auto.levels if l.label == "ONH")
        onl = next(l for l in auto.levels if l.label == "ONL")
        assert onh.value == pytest.approx(5210.0, abs=0.01)
        assert onl.value == pytest.approx(5180.0, abs=0.01)
