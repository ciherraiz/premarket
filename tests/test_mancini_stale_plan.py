"""Tests para el fallback de plan stale (día anterior) en monitor.py."""

import os
import sys
from datetime import datetime, date, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from scripts.mancini.config import DailyPlan, save_plan
from scripts.mancini.detector import State, save_detectors, FailedBreakdownDetector
from scripts.mancini.monitor import (
    ManciniMonitor, ET, CONTEXT_ALERT_PTS,
    _should_use_stale_plan, _active_levels,
)


TODAY = date(2026, 4, 24)
YESTERDAY = TODAY - timedelta(days=1)
TWO_DAYS_AGO = TODAY - timedelta(days=2)

KEY_UPPER = 5300.0
KEY_LOWER = 5250.0


@pytest.fixture
def plan_path(tmp_path):
    return tmp_path / "mancini_plan.json"


@pytest.fixture
def state_path(tmp_path):
    return tmp_path / "mancini_state.json"


@pytest.fixture
def weekly_path(tmp_path):
    return tmp_path / "mancini_weekly.json"


@pytest.fixture
def intraday_path(tmp_path):
    return tmp_path / "mancini_intraday.json"


@pytest.fixture
def yesterday_plan(plan_path):
    plan = DailyPlan(
        fecha=YESTERDAY.isoformat(),
        key_level_upper=KEY_UPPER,
        targets_upper=[5315.0, 5330.0],
        key_level_lower=KEY_LOWER,
        targets_lower=[5235.0, 5220.0],
    )
    save_plan(plan, plan_path)
    return plan


@pytest.fixture
def monitor(plan_path, state_path, weekly_path, intraday_path):
    return ManciniMonitor(
        client=None,
        plan_path=plan_path,
        state_path=state_path,
        weekly_path=weekly_path,
        intraday_path=intraday_path,
        gate_enabled=False,
    )


@pytest.fixture(autouse=True)
def mock_today():
    fake_now = datetime(TODAY.year, TODAY.month, TODAY.day, 9, 30, 0, tzinfo=ET)
    with patch("scripts.mancini.monitor._now_et", return_value=fake_now):
        yield


@pytest.fixture(autouse=True)
def mock_notifier():
    with patch("scripts.mancini.monitor.notifier") as mock:
        mock.notify_plan_loaded.return_value = True
        yield mock


# ── _should_use_stale_plan ──────────────────────────────────────────

class TestShouldUseStalePlan:

    def test_activa_cuando_precio_en_alert_zone_upper(self, state_path, yesterday_plan):
        price = KEY_UPPER + 5  # 5 pts sobre el nivel → alert zone
        assert _should_use_stale_plan(yesterday_plan, price, state_path) is True

    def test_activa_cuando_precio_en_alert_zone_lower(self, state_path, yesterday_plan):
        price = KEY_LOWER + 10  # 10 pts sobre nivel lower → alert zone
        assert _should_use_stale_plan(yesterday_plan, price, state_path) is True

    def test_no_activa_cuando_precio_lejos(self, state_path, yesterday_plan):
        price = KEY_UPPER + CONTEXT_ALERT_PTS + 5  # fuera de alert zone
        # lower también está lejos (price - KEY_LOWER = 55 pts)
        assert _should_use_stale_plan(yesterday_plan, price, state_path) is False

    def test_no_activa_sin_plan(self, state_path):
        assert _should_use_stale_plan(None, 5300.0, state_path) is False

    def test_no_activa_sin_precio(self, state_path, yesterday_plan):
        assert _should_use_stale_plan(yesterday_plan, None, state_path) is False

    def test_no_activa_plan_de_hace_dos_dias(self, plan_path, state_path):
        old_plan = DailyPlan(
            fecha=TWO_DAYS_AGO.isoformat(),
            key_level_upper=KEY_UPPER,
            targets_upper=[5315.0],
            key_level_lower=KEY_LOWER,
            targets_lower=[5235.0],
        )
        save_plan(old_plan, plan_path)
        assert _should_use_stale_plan(old_plan, KEY_UPPER + 5, state_path) is False

    def test_no_activa_nivel_done_ayer(self, state_path, yesterday_plan):
        # El nivel upper estaba en DONE ayer
        det = FailedBreakdownDetector(level=KEY_UPPER, side="upper")
        det.state = State.DONE
        save_detectors([det], state_path)
        # Solo queda lower; precio está lejos de lower
        price = KEY_UPPER + 5  # cerca de upper (DONE), lejos de lower (50 pts)
        assert _should_use_stale_plan(yesterday_plan, price, state_path) is False

    def test_activa_si_un_nivel_done_pero_otro_activo(self, state_path, yesterday_plan):
        # Upper en DONE, lower activo y precio cerca de lower
        det = FailedBreakdownDetector(level=KEY_UPPER, side="upper")
        det.state = State.DONE
        save_detectors([det], state_path)
        price = KEY_LOWER + 8  # cerca de lower → debe activarse
        assert _should_use_stale_plan(yesterday_plan, price, state_path) is True


# ── _active_levels ──────────────────────────────────────────────────

class TestActiveLevels:

    def test_devuelve_ambos_niveles_sin_estado_previo(self, state_path, yesterday_plan):
        levels = _active_levels(yesterday_plan, state_path)
        assert KEY_UPPER in levels
        assert KEY_LOWER in levels

    def test_excluye_nivel_done(self, state_path, yesterday_plan):
        det = FailedBreakdownDetector(level=KEY_UPPER, side="upper")
        det.state = State.DONE
        save_detectors([det], state_path)
        levels = _active_levels(yesterday_plan, state_path)
        assert KEY_UPPER not in levels
        assert KEY_LOWER in levels

    def test_excluye_nivel_expired(self, state_path, yesterday_plan):
        det = FailedBreakdownDetector(level=KEY_LOWER, side="lower")
        det.state = State.EXPIRED
        save_detectors([det], state_path)
        levels = _active_levels(yesterday_plan, state_path)
        assert KEY_LOWER not in levels
        assert KEY_UPPER in levels

    def test_devuelve_lista_vacia_si_todo_done(self, state_path, yesterday_plan):
        dets = [
            FailedBreakdownDetector(level=KEY_UPPER, side="upper"),
            FailedBreakdownDetector(level=KEY_LOWER, side="lower"),
        ]
        dets[0].state = State.DONE
        dets[1].state = State.EXPIRED
        save_detectors(dets, state_path)
        levels = _active_levels(yesterday_plan, state_path)
        assert levels == []


# ── load_state con fallback stale ───────────────────────────────────

class TestLoadStateStale:

    def test_carga_plan_stale_cuando_precio_en_zona(self, monitor, yesterday_plan):
        price = KEY_UPPER + 8
        monitor.load_state(current_price=price)
        assert monitor.plan is not None
        assert monitor.plan.is_stale is True
        assert monitor.plan.fecha == YESTERDAY.isoformat()

    def test_no_carga_stale_cuando_precio_lejos(self, monitor, yesterday_plan):
        price = KEY_UPPER + 50  # lejos de ambos niveles
        monitor.load_state(current_price=price)
        assert monitor.plan is None

    def test_no_carga_stale_sin_precio(self, monitor, yesterday_plan):
        monitor.load_state(current_price=None)
        assert monitor.plan is None

    def test_detectores_stale_solo_niveles_activos(self, monitor, state_path, yesterday_plan):
        # Upper en DONE → solo debe crear detector de lower
        det = FailedBreakdownDetector(level=KEY_UPPER, side="upper")
        det.state = State.DONE
        save_detectors([det], state_path)
        price = KEY_LOWER + 5
        monitor.load_state(current_price=price)
        assert monitor.plan is not None
        assert len(monitor.detectors) == 1
        assert monitor.detectors[0].level == KEY_LOWER

    def test_plan_hoy_tiene_prioridad_sobre_stale(self, monitor, plan_path):
        today_plan = DailyPlan(
            fecha=TODAY.isoformat(),
            key_level_upper=KEY_UPPER,
            targets_upper=[5315.0],
            key_level_lower=KEY_LOWER,
            targets_lower=[5235.0],
        )
        save_plan(today_plan, plan_path)
        monitor.load_state(current_price=KEY_UPPER + 5)
        assert monitor.plan is not None
        assert monitor.plan.is_stale is False
        assert monitor.plan.fecha == TODAY.isoformat()


# ── DailyPlan.to_dict y save_plan ───────────────────────────────────

class TestStaleSerialization:

    def test_is_stale_no_se_persiste_en_json(self, plan_path):
        plan = DailyPlan(
            fecha=YESTERDAY.isoformat(),
            key_level_upper=KEY_UPPER,
            targets_upper=[5315.0],
            key_level_lower=KEY_LOWER,
            targets_lower=[5235.0],
        )
        plan.is_stale = True
        save_plan(plan, plan_path)
        import json
        saved = json.loads(plan_path.read_text())
        assert "is_stale" not in saved

    def test_is_stale_incluido_en_to_dict(self):
        plan = DailyPlan(
            fecha=YESTERDAY.isoformat(),
            key_level_upper=KEY_UPPER,
            targets_upper=[],
            key_level_lower=None,
            targets_lower=[],
        )
        plan.is_stale = True
        d = plan.to_dict()
        assert d["is_stale"] is True

    def test_from_dict_ignora_is_stale(self):
        d = {
            "fecha": YESTERDAY.isoformat(),
            "key_level_upper": KEY_UPPER,
            "targets_upper": [],
            "key_level_lower": None,
            "targets_lower": [],
            "is_stale": True,
        }
        plan = DailyPlan.from_dict(d)
        assert plan.is_stale is False


# ── health.py — plan_stale ──────────────────────────────────────────

class TestHealthStale:

    def test_health_plan_stale_cuando_plan_de_ayer(self, tmp_path):
        from scripts.mancini.health import check_health, OUTPUTS_DIR, LOGS_DIR
        plan_path = OUTPUTS_DIR / "mancini_plan.json"
        original = plan_path.read_text(encoding="utf-8") if plan_path.exists() else None
        try:
            plan = DailyPlan(
                fecha=YESTERDAY.isoformat(),
                key_level_upper=KEY_UPPER,
                targets_upper=[5315.0],
                key_level_lower=KEY_LOWER,
                targets_lower=[5235.0],
            )
            save_plan(plan, plan_path)
            health = check_health()
            assert health.plan_ok is False
            assert health.plan_stale is True
            assert health.plan_fecha == YESTERDAY.isoformat()
        finally:
            if original is not None:
                plan_path.write_text(original, encoding="utf-8")
            elif plan_path.exists():
                plan_path.unlink()
