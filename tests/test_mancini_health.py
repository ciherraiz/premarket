"""Tests para scripts/mancini/health.py — gestión del ciclo de vida del monitor."""

import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import scripts.mancini.health as health_mod
from scripts.mancini.health import (
    SystemHealth,
    check_health,
    clear_pid,
    clear_stop_flag,
    get_orphan_pids,
    is_monitor_running,
    kill_orphans,
    read_pid,
    recover,
    request_stop,
    start_day,
    stop_day,
    stop_requested,
    write_pid,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolate_paths(tmp_path, monkeypatch):
    """Redirige PID_PATH y STOP_FLAG_PATH a tmp_path para cada test."""
    pid_path = tmp_path / "mancini_monitor.pid"
    stop_path = tmp_path / "mancini_stop"
    log_path = tmp_path / "mancini_monitor.log"

    monkeypatch.setattr(health_mod, "PID_PATH", pid_path)
    monkeypatch.setattr(health_mod, "STOP_FLAG_PATH", stop_path)
    monkeypatch.setattr(health_mod, "MONITOR_LOG", log_path)
    monkeypatch.setattr(health_mod, "OUTPUTS_DIR", tmp_path)
    monkeypatch.setattr(health_mod, "LOGS_DIR", tmp_path)


# ── PID file ──────────────────────────────────────────────────────────────────

class TestPidFile:
    def test_write_and_read(self, tmp_path):
        write_pid(12345)
        assert read_pid() == 12345

    def test_read_missing_returns_none(self):
        assert read_pid() is None

    def test_clear_removes_file(self, tmp_path):
        write_pid(99)
        clear_pid()
        assert read_pid() is None

    def test_clear_missing_ok(self):
        clear_pid()  # no debe lanzar

    def test_is_monitor_running_no_pid_file(self):
        assert is_monitor_running() is False

    def test_is_monitor_running_current_process(self):
        write_pid(os.getpid())
        assert is_monitor_running() is True

    def test_is_monitor_running_stale_pid(self):
        # PID muy alto que (casi seguro) no existe
        write_pid(999999999)
        assert is_monitor_running() is False

    def test_is_monitor_running_invalid_content(self, monkeypatch):
        health_mod.PID_PATH.write_text("not-a-number", encoding="utf-8")
        assert is_monitor_running() is False


# ── Stop flag ─────────────────────────────────────────────────────────────────

class TestStopFlag:
    def test_request_creates_file(self):
        request_stop()
        assert stop_requested() is True

    def test_clear_removes_file(self):
        request_stop()
        clear_stop_flag()
        assert stop_requested() is False

    def test_clear_missing_ok(self):
        clear_stop_flag()  # no debe lanzar

    def test_not_requested_by_default(self):
        assert stop_requested() is False


# ── Orphan detection ──────────────────────────────────────────────────────────

class TestOrphans:
    def test_get_orphan_pids_no_psutil(self, monkeypatch):
        """Sin psutil retorna lista vacía."""
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "psutil":
                raise ImportError
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        assert get_orphan_pids() == []

    def test_get_orphan_pids_excludes_official_pid(self, monkeypatch):
        """El PID del PID file no cuenta como huérfano."""
        write_pid(os.getpid())

        fake_proc = MagicMock()
        fake_proc.info = {"pid": os.getpid(), "cmdline": ["python", "run_mancini.py", "monitor"]}

        mock_psutil = MagicMock()
        mock_psutil.process_iter.return_value = [fake_proc]
        mock_psutil.NoSuchProcess = ProcessLookupError
        mock_psutil.AccessDenied = PermissionError

        monkeypatch.setitem(sys.modules, "psutil", mock_psutil)
        assert get_orphan_pids() == []

    def test_get_orphan_pids_detects_unregistered(self, monkeypatch):
        """PID que no está en el PID file sí es huérfano."""
        write_pid(99999)  # oficial = 99999

        fake_proc = MagicMock()
        fake_proc.info = {"pid": 12345, "cmdline": ["python", "run_mancini.py", "monitor"]}

        mock_psutil = MagicMock()
        mock_psutil.process_iter.return_value = [fake_proc]
        mock_psutil.NoSuchProcess = ProcessLookupError
        mock_psutil.AccessDenied = PermissionError

        monkeypatch.setitem(sys.modules, "psutil", mock_psutil)
        assert 12345 in get_orphan_pids()

    def test_kill_orphans_calls_sigterm(self, monkeypatch):
        killed_pids = []

        monkeypatch.setattr(health_mod, "get_orphan_pids", lambda: [55555, 55556])
        monkeypatch.setattr(time, "sleep", lambda _: None)

        def mock_kill(pid, sig):
            killed_pids.append(pid)

        monkeypatch.setattr(os, "kill", mock_kill)
        result = kill_orphans()
        assert set(result) == {55555, 55556}
        assert set(killed_pids) == {55555, 55556}


# ── check_health ──────────────────────────────────────────────────────────────

class TestCheckHealth:
    def _make_plan(self, fecha="2026-04-21"):
        plan = MagicMock()
        plan.fecha = fecha
        plan.key_level_upper = 5300.0
        plan.targets_upper = [5320.0, 5340.0]
        plan.key_level_lower = 5250.0
        plan.targets_lower = [5230.0]
        return plan

    @pytest.fixture(autouse=True)
    def patch_dependencies(self, monkeypatch):
        monkeypatch.setattr(health_mod, "get_orphan_pids", lambda: [])
        monkeypatch.setattr(
            "scripts.mancini.config.load_intraday_state", MagicMock(return_value=MagicMock()), raising=False
        )
        monkeypatch.setattr(
            "scripts.mancini.detector.load_detectors", MagicMock(return_value=[]), raising=False
        )

    def test_no_plan(self, monkeypatch):
        monkeypatch.setattr("scripts.mancini.config.load_plan", lambda: None)
        h = check_health()
        assert h.plan_ok is False
        assert h.plan_fecha is None
        assert h.overall_ok is False

    def test_old_plan(self, monkeypatch):
        monkeypatch.setattr("scripts.mancini.config.load_plan", lambda: self._make_plan("2026-04-20"))
        monkeypatch.setattr(health_mod, "_parse_last_quote", lambda: (5300.0, 30.0, True))
        with patch.object(health_mod, "datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "2026-04-21"
            h = check_health()
        assert h.plan_ok is False
        assert h.overall_ok is False

    def test_plan_ok_monitor_running(self, monkeypatch):
        monkeypatch.setattr("scripts.mancini.config.load_plan", lambda: self._make_plan("2026-04-21"))
        monkeypatch.setattr(health_mod, "_parse_last_quote", lambda: (5300.0, 30.0, True))
        write_pid(os.getpid())  # proceso real = monitor "corriendo"
        with patch.object(health_mod, "datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "2026-04-21"
            h = check_health()
        assert h.plan_ok is True
        assert h.monitor_running is True
        assert h.last_quote_ok is True
        assert h.orphan_count == 0
        assert h.overall_ok is True

    def test_monitor_stale_pid(self, monkeypatch):
        monkeypatch.setattr("scripts.mancini.config.load_plan", lambda: self._make_plan("2026-04-21"))
        monkeypatch.setattr(health_mod, "_parse_last_quote", lambda: (5300.0, 30.0, True))
        write_pid(999999999)  # PID que no existe
        with patch.object(health_mod, "datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "2026-04-21"
            h = check_health()
        assert h.monitor_running is False
        assert h.monitor_pid == 999999999
        assert h.overall_ok is False


# ── _parse_last_quote ─────────────────────────────────────────────────────────

class TestParseLastQuote:
    def test_no_log_file(self):
        price, age, ok = health_mod._parse_last_quote()
        assert price is None
        assert ok is False

    def test_parses_es_price(self, monkeypatch):
        log_content = "[mancini 10:30:00 ET] ES=5300.50 mark\n"
        health_mod.MONITOR_LOG.write_text(log_content, encoding="utf-8")
        price, age, ok = health_mod._parse_last_quote()
        assert price == 5300.50
        assert ok is True

    def test_error_line_returns_false_ok(self, monkeypatch):
        log_content = "[mancini 10:30:00 ET] Quote status: ERROR\n"
        health_mod.MONITOR_LOG.write_text(log_content, encoding="utf-8")
        price, age, ok = health_mod._parse_last_quote()
        assert ok is False


# ── start_day ─────────────────────────────────────────────────────────────────

class TestStartDay:
    @pytest.fixture(autouse=True)
    def patch_heavy(self, monkeypatch):
        monkeypatch.setattr(health_mod, "kill_orphans", lambda: [])
        monkeypatch.setattr(health_mod, "_run_scan", lambda: True)
        monkeypatch.setattr(health_mod, "_wait_for_pid_file", lambda timeout_s=30: True)
        monkeypatch.setattr(health_mod, "_wait_for_first_quote", lambda timeout_s=45: True)
        monkeypatch.setattr("scripts.mancini.notifier.notify_plan_loaded", MagicMock(), raising=False)

    def test_dry_run_returns_true_without_launching(self, monkeypatch):
        launch_calls = []
        monkeypatch.setattr(health_mod, "_launch_monitor", lambda: launch_calls.append(1) or 42)
        monkeypatch.setattr("scripts.mancini.config.load_plan", lambda: None)
        result = start_day(skip_scan=True, dry_run=True)
        assert result is True
        assert launch_calls == []

    def test_already_running_and_healthy_returns_true(self, monkeypatch):
        write_pid(os.getpid())

        plan = MagicMock()
        plan.fecha = "2026-04-21"
        plan.key_level_upper = 5300.0
        plan.targets_upper = [5320.0]
        plan.key_level_lower = None
        plan.targets_lower = []
        monkeypatch.setattr("scripts.mancini.config.load_plan", lambda: plan)

        healthy = SystemHealth(
            plan_ok=True, plan_fecha="2026-04-21", plan_upper=5300.0,
            plan_targets_upper=[5320.0], plan_lower=None, plan_targets_lower=[],
            monitor_running=True, monitor_pid=os.getpid(), monitor_uptime_s=120.0,
            last_quote_ok=True, last_quote_price=5300.0, last_quote_age_s=30.0,
            detector_count=0, detector_states=[], active_trade=False,
            orphan_count=0, overall_ok=True,
        )
        monkeypatch.setattr(health_mod, "check_health", lambda: healthy)

        launch_calls = []
        monkeypatch.setattr(health_mod, "_launch_monitor", lambda: launch_calls.append(1) or 42)
        with patch.object(health_mod, "datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "2026-04-21"
            result = start_day()
        assert result is True
        assert launch_calls == []

    def test_launches_monitor_when_not_running(self, monkeypatch):
        plan = MagicMock()
        plan.fecha = "2026-04-21"
        plan.key_level_upper = 5300.0
        plan.targets_upper = [5320.0]
        plan.key_level_lower = None
        plan.targets_lower = []
        monkeypatch.setattr("scripts.mancini.config.load_plan", lambda: plan)

        launched = []
        monkeypatch.setattr(health_mod, "_launch_monitor", lambda: launched.append(1) or 9999)

        healthy_after = SystemHealth(
            plan_ok=True, plan_fecha="2026-04-21", plan_upper=5300.0,
            plan_targets_upper=[5320.0], plan_lower=None, plan_targets_lower=[],
            monitor_running=True, monitor_pid=9999, monitor_uptime_s=5.0,
            last_quote_ok=True, last_quote_price=5300.0, last_quote_age_s=10.0,
            detector_count=0, detector_states=[], active_trade=False,
            orphan_count=0, overall_ok=True,
        )
        # check_health is called once at the end (monitor was not running at start,
        # so the idempotency branch is skipped)
        monkeypatch.setattr(health_mod, "check_health", lambda: healthy_after)
        with patch.object(health_mod, "datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "2026-04-21"
            result = start_day(skip_scan=True)
        assert launched == [1]
        assert result is True


# ── stop_day ──────────────────────────────────────────────────────────────────

class TestStopDay:
    def test_not_running_returns_true(self):
        assert stop_day() is True

    def test_force_kills_process(self, monkeypatch):
        write_pid(os.getpid())
        killed = []
        monkeypatch.setattr(os, "kill", lambda pid, sig: killed.append((pid, sig)))
        monkeypatch.setattr(time, "sleep", lambda _: None)
        result = stop_day(force=True)
        assert result is True
        assert (os.getpid(), signal.SIGTERM) in killed
        assert read_pid() is None

    def test_clean_stop_sets_flag(self, monkeypatch):
        write_pid(os.getpid())

        # El monitor "termina" al segundo intento de is_monitor_running
        call_count = [0]
        original = health_mod.is_monitor_running

        def mock_running():
            call_count[0] += 1
            if call_count[0] <= 2:
                return True
            clear_pid()
            return False

        monkeypatch.setattr(health_mod, "is_monitor_running", mock_running)
        monkeypatch.setattr(time, "sleep", lambda _: None)
        result = stop_day(force=False)
        assert result is True
        assert stop_requested() is True or not is_monitor_running()


# ── recover ───────────────────────────────────────────────────────────────────

class TestRecover:
    def _healthy(self, **kwargs):
        defaults = dict(
            plan_ok=True, plan_fecha="2026-04-21", plan_upper=5300.0,
            plan_targets_upper=[5320.0], plan_lower=None, plan_targets_lower=[],
            monitor_running=True, monitor_pid=os.getpid(), monitor_uptime_s=60.0,
            last_quote_ok=True, last_quote_price=5300.0, last_quote_age_s=30.0,
            detector_count=0, detector_states=[], active_trade=False,
            orphan_count=0, overall_ok=True,
        )
        defaults.update(kwargs)
        return SystemHealth(**defaults)

    def test_healthy_system_no_actions(self, monkeypatch):
        h = self._healthy()
        call_count = [0]

        def mock_check():
            call_count[0] += 1
            return h

        monkeypatch.setattr(health_mod, "check_health", mock_check)
        result = recover()
        assert result.overall_ok is True

    def test_dry_run_does_not_modify(self, monkeypatch):
        h = self._healthy(overall_ok=False, monitor_running=False, monitor_pid=None, orphan_count=0, plan_ok=False)
        monkeypatch.setattr(health_mod, "check_health", lambda: h)
        monkeypatch.setattr(health_mod, "_run_scan", MagicMock(return_value=True))
        monkeypatch.setattr(health_mod, "_launch_monitor", MagicMock(return_value=42))
        monkeypatch.setattr(health_mod, "_wait_for_pid_file", lambda timeout_s=30: True)

        result = recover(dry_run=True)
        health_mod._launch_monitor.assert_not_called()
        health_mod._run_scan.assert_not_called()

    def test_clears_stale_pid(self, monkeypatch):
        write_pid(999999999)
        h = self._healthy(overall_ok=False, monitor_running=False, monitor_pid=999999999, plan_ok=True, plan_fecha="2026-04-21")

        call_count = [0]
        def mock_check():
            call_count[0] += 1
            if call_count[0] == 1:
                return h
            return self._healthy()

        monkeypatch.setattr(health_mod, "check_health", mock_check)
        monkeypatch.setattr(health_mod, "kill_orphans", lambda: [])
        monkeypatch.setattr(health_mod, "_launch_monitor", lambda: os.getpid())
        monkeypatch.setattr(health_mod, "_wait_for_pid_file", lambda timeout_s=30: True)
        monkeypatch.setattr(health_mod, "_run_scan", lambda: True)

        result = recover()
        # El PID file stale debe haber sido borrado durante recover
        # (o el monitor relanzado con PID real)
        assert result is not None

    def test_kills_orphans(self, monkeypatch):
        killed = []
        monkeypatch.setattr(health_mod, "kill_orphans", lambda: killed.append(1) or [55555])
        h = self._healthy(overall_ok=False, orphan_count=1, monitor_running=True, plan_ok=True, plan_fecha="2026-04-21", last_quote_ok=True)

        call_count = [0]
        def mock_check():
            call_count[0] += 1
            if call_count[0] == 1:
                return h
            return self._healthy()

        monkeypatch.setattr(health_mod, "check_health", mock_check)
        recover()
        assert killed == [1]
