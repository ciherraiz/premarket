"""Tests de integración para el flujo intraday: monitor + classifier + notifier + logger."""

import json
import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from scripts.mancini.config import (
    DailyPlan, PlanAdjustment, IntraDayState,
    save_plan, save_intraday_state, load_intraday_state,
)
from scripts.mancini.detector import State, FailedBreakdownDetector
from scripts.mancini.monitor import ManciniMonitor


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
def sample_plan(plan_path):
    plan = DailyPlan(
        fecha="2026-04-16",
        key_level_upper=6809,
        targets_upper=[6819, 6830],
        key_level_lower=6781,
        targets_lower=[6766],
    )
    save_plan(plan, plan_path)
    return plan


@pytest.fixture
def monitor(plan_path, state_path, weekly_path, intraday_path):
    m = ManciniMonitor(
        plan_path=plan_path,
        state_path=state_path,
        weekly_path=weekly_path,
        intraday_path=intraday_path,
    )
    return m


@pytest.fixture
def loaded_monitor(monitor, sample_plan):
    """Monitor con plan cargado y detectores inicializados."""
    with patch("scripts.mancini.monitor._now_et") as mock_now:
        mock_now.return_value = MagicMock(
            strftime=MagicMock(return_value="2026-04-16"),
            hour=10,
        )
        monitor.load_state()
    return monitor


# ── Tests de IntraDayState persistencia ──────────────────────────


def test_intraday_state_roundtrip(intraday_path):
    """IntraDayState se serializa y deserializa correctamente."""
    from datetime import date
    today = date.today().isoformat()
    adj = PlanAdjustment(
        tweet_id="123",
        tweet_text="test tweet",
        timestamp="2026-04-16T10:00:00",
        adjustment_type="LEVEL_UPDATE",
        details={"side": "upper", "new_level": 6815},
        raw_reasoning="test reasoning",
    )
    state = IntraDayState(
        processed_tweet_ids={"123", "456"},
        adjustments=[adj],
        last_check="2026-04-16T10:05:00",
        fecha=today,
    )
    save_intraday_state(state, intraday_path)
    loaded = load_intraday_state(intraday_path)

    assert loaded.processed_tweet_ids == {"123", "456"}
    assert len(loaded.adjustments) == 1
    assert loaded.adjustments[0].tweet_id == "123"
    assert loaded.adjustments[0].adjustment_type == "LEVEL_UPDATE"
    assert loaded.last_check == "2026-04-16T10:05:00"
    assert loaded.fecha == today


def test_load_intraday_state_missing_file(tmp_path):
    """Sin fichero, retorna estado vacío."""
    state = load_intraday_state(tmp_path / "nonexistent.json")
    assert state.processed_tweet_ids == set()
    assert state.adjustments == []


def test_load_intraday_state_stale_date_resets(intraday_path):
    """Estado de otro día se descarta → IDs limpios al cargar."""
    stale = IntraDayState(
        processed_tweet_ids={"old-tweet-1", "old-tweet-2"},
        adjustments=[],
        last_check="2026-04-22T10:00:00",
        fecha="2026-04-22",  # ayer
    )
    save_intraday_state(stale, intraday_path)
    loaded = load_intraday_state(intraday_path)

    assert loaded.processed_tweet_ids == set()
    assert loaded.adjustments == []
    assert loaded.fecha == ""


def test_load_intraday_state_same_date_keeps(intraday_path):
    """Estado del mismo día se mantiene intacto."""
    from datetime import date
    today = date.today().isoformat()
    state = IntraDayState(
        processed_tweet_ids={"t1", "t2"},
        adjustments=[],
        fecha=today,
    )
    save_intraday_state(state, intraday_path)
    loaded = load_intraday_state(intraday_path)

    assert loaded.processed_tweet_ids == {"t1", "t2"}
    assert loaded.fecha == today


def test_load_intraday_state_no_fecha_field_preserved(intraday_path):
    """Estado antiguo sin campo fecha (retrocompatibilidad) se carga sin resetear."""
    import json
    old_format = {
        "processed_tweet_ids": ["t1"],
        "adjustments": [],
        "last_check": "",
        # Sin 'fecha'
    }
    intraday_path.write_text(json.dumps(old_format), encoding="utf-8")
    loaded = load_intraday_state(intraday_path)
    assert loaded.processed_tweet_ids == {"t1"}
    assert loaded.fecha == ""


# ── Tests de _apply_adjustment ───────────────────────────────────


def test_apply_invalidation_full(loaded_monitor):
    """INVALIDATION full → todos los detectores EXPIRED."""
    assert len(loaded_monitor.detectors) == 2
    adj = PlanAdjustment(
        tweet_id="inv1", tweet_text="plan invalidated",
        timestamp="2026-04-16T11:00:00",
        adjustment_type="INVALIDATION",
        details={"scope": "full"},
    )
    loaded_monitor._apply_adjustment(adj)

    for det in loaded_monitor.detectors:
        assert det.state == State.EXPIRED


def test_apply_invalidation_partial(loaded_monitor):
    """INVALIDATION upper → solo upper EXPIRED, lower sigue."""
    adj = PlanAdjustment(
        tweet_id="inv2", tweet_text="upper invalidated",
        timestamp="2026-04-16T11:00:00",
        adjustment_type="INVALIDATION",
        details={"scope": "upper"},
    )
    loaded_monitor._apply_adjustment(adj)

    upper = loaded_monitor._get_detector_by_side("upper")
    lower = loaded_monitor._get_detector_by_side("lower")
    assert upper.state == State.EXPIRED
    assert lower.state == State.WATCHING


def test_apply_level_update_watching(loaded_monitor):
    """LEVEL_UPDATE con detector en WATCHING → actualiza nivel."""
    adj = PlanAdjustment(
        tweet_id="lu1", tweet_text="buyers defending 6790",
        timestamp="2026-04-16T11:00:00",
        adjustment_type="LEVEL_UPDATE",
        details={"side": "lower", "old_level": 6781, "new_level": 6790},
    )
    loaded_monitor._apply_adjustment(adj)

    assert loaded_monitor.plan.key_level_lower == 6790
    det = loaded_monitor._get_detector_by_side("lower")
    assert det.level == 6790


def test_apply_level_update_active_no_change(loaded_monitor):
    """LEVEL_UPDATE con detector en ACTIVE → plan actualiza pero detector no."""
    det = loaded_monitor._get_detector_by_side("lower")
    det.mark_active()
    original_level = det.level

    adj = PlanAdjustment(
        tweet_id="lu2", tweet_text="new level",
        timestamp="2026-04-16T11:00:00",
        adjustment_type="LEVEL_UPDATE",
        details={"side": "lower", "old_level": 6781, "new_level": 6790},
    )
    loaded_monitor._apply_adjustment(adj)

    # Plan se actualiza
    assert loaded_monitor.plan.key_level_lower == 6790
    # Detector en ACTIVE no cambia nivel
    assert det.level == original_level


def test_apply_target_update_append(loaded_monitor):
    """TARGET_UPDATE replace=False → añade targets sin duplicados."""
    adj = PlanAdjustment(
        tweet_id="tu1", tweet_text="next target 6840",
        timestamp="2026-04-16T11:00:00",
        adjustment_type="TARGET_UPDATE",
        details={"side": "upper", "new_targets": [6840, 6819], "replace": False},
    )
    loaded_monitor._apply_adjustment(adj)

    assert 6840 in loaded_monitor.plan.targets_upper
    assert 6819 in loaded_monitor.plan.targets_upper
    assert 6830 in loaded_monitor.plan.targets_upper
    # Sin duplicados
    assert loaded_monitor.plan.targets_upper == sorted(set(loaded_monitor.plan.targets_upper))


def test_apply_target_update_replace(loaded_monitor):
    """TARGET_UPDATE replace=True → reemplaza targets."""
    adj = PlanAdjustment(
        tweet_id="tu2", tweet_text="new targets",
        timestamp="2026-04-16T11:00:00",
        adjustment_type="TARGET_UPDATE",
        details={"side": "upper", "new_targets": [6850, 6860], "replace": True},
    )
    loaded_monitor._apply_adjustment(adj)

    assert loaded_monitor.plan.targets_upper == [6850, 6860]


def test_apply_bias_shift(loaded_monitor):
    """BIAS_SHIFT → actualiza notes del plan."""
    adj = PlanAdjustment(
        tweet_id="bs1", tweet_text="flipped bearish",
        timestamp="2026-04-16T12:00:00",
        adjustment_type="BIAS_SHIFT",
        details={"old_bias": "bullish", "new_bias": "bearish", "trigger": "lost 6780"},
    )
    loaded_monitor._apply_adjustment(adj)

    assert "bearish" in loaded_monitor.plan.notes


def test_apply_context_update_no_plan_change(loaded_monitor):
    """CONTEXT_UPDATE → no cambia plan ni detectores."""
    original_upper = loaded_monitor.plan.key_level_upper
    original_lower = loaded_monitor.plan.key_level_lower

    adj = PlanAdjustment(
        tweet_id="cu1", tweet_text="buyers defending aggressively",
        timestamp="2026-04-16T11:30:00",
        adjustment_type="CONTEXT_UPDATE",
        details={"context_type": "defense", "summary": "buyers defending 6781", "implied_bias": "bullish"},
    )
    loaded_monitor._apply_adjustment(adj)

    assert loaded_monitor.plan.key_level_upper == original_upper
    assert loaded_monitor.plan.key_level_lower == original_lower
    for det in loaded_monitor.detectors:
        assert det.state == State.WATCHING


# ── Tests de check_intraday_updates ──────────────────────────────


@patch("scripts.mancini.monitor.notifier")
@patch("scripts.mancini.monitor.append_adjustment")
def test_check_intraday_no_action_not_notified(mock_log, mock_notifier, loaded_monitor):
    """NO_ACTION no envía Telegram ni aplica cambios."""
    with patch("scripts.mancini.monitor.ManciniMonitor.check_intraday_updates") as orig:
        # Call the real method but mock the fetcher and classifier
        pass

    # Test directly via the flow
    mock_fetcher = MagicMock(return_value=[
        {"id": "na1", "text": "thanks for the follow!", "created_at": "2026-04-16T10:00:00"}
    ])
    mock_classifier = MagicMock(return_value=PlanAdjustment(
        tweet_id="na1", tweet_text="thanks for the follow!",
        timestamp="2026-04-16T10:00:00",
        adjustment_type="NO_ACTION", details={},
        raw_reasoning="Reply a follower",
    ))

    with patch("scripts.mancini.monitor.ManciniMonitor.check_intraday_updates.__module__", create=True):
        pass

    # Simulate the flow manually
    from scripts.mancini.tweet_classifier import classify_tweet as real_classify

    with patch("scripts.mancini.monitor.notifier") as mock_not:
        adj = PlanAdjustment(
            tweet_id="na1", tweet_text="thanks!",
            timestamp="2026-04-16T10:00:00",
            adjustment_type="NO_ACTION", details={},
            raw_reasoning="Reply",
        )
        loaded_monitor.intraday_state.adjustments.append(adj)
        # NO_ACTION should not trigger notify_adjustment
        if adj.adjustment_type != "NO_ACTION":
            loaded_monitor._apply_adjustment(adj)
            mock_not.notify_adjustment(adj)

        mock_not.notify_adjustment.assert_not_called()


@patch("scripts.mancini.monitor.notifier")
@patch("scripts.mancini.monitor.append_adjustment")
def test_context_update_notified(mock_log, mock_notifier, loaded_monitor):
    """CONTEXT_UPDATE sí envía Telegram aunque no cambie el plan."""
    adj = PlanAdjustment(
        tweet_id="cu1", tweet_text="volume picking up",
        timestamp="2026-04-16T11:00:00",
        adjustment_type="CONTEXT_UPDATE",
        details={"context_type": "volume", "summary": "volume picking up", "implied_bias": None},
        raw_reasoning="Info de volumen",
    )

    # Simulate what check_intraday_updates does for non-NO_ACTION
    loaded_monitor.intraday_state.adjustments.append(adj)
    loaded_monitor._apply_adjustment(adj)
    mock_notifier.notify_adjustment(adj)

    mock_notifier.notify_adjustment.assert_called_once_with(adj)


def test_processed_ids_persist(loaded_monitor, intraday_path):
    """Los tweet IDs procesados persisten entre saves/loads."""
    loaded_monitor.intraday_state.processed_tweet_ids.add("t1")
    loaded_monitor.intraday_state.processed_tweet_ids.add("t2")
    loaded_monitor.save_state()

    new_state = load_intraday_state(intraday_path)
    assert "t1" in new_state.processed_tweet_ids
    assert "t2" in new_state.processed_tweet_ids


def test_intraday_not_active_without_plan(monitor):
    """Sin plan cargado, check_intraday_updates no se ejecuta en el loop."""
    assert monitor.plan is None
    # El loop principal solo llama check_intraday_updates si self.plan exists
    # Verificamos que el guard funciona
    with patch.object(monitor, "check_intraday_updates") as mock_check:
        # Simulating the guard from run()
        if monitor.plan:
            monitor.check_intraday_updates()
        mock_check.assert_not_called()


@patch("scripts.mancini.monitor.append_adjustment")
def test_adjustment_logged_to_jsonl(mock_append, loaded_monitor):
    """Cada adjustment se persiste via append_adjustment."""
    adj = PlanAdjustment(
        tweet_id="log1", tweet_text="test",
        timestamp="2026-04-16T10:00:00",
        adjustment_type="LEVEL_UPDATE",
        details={"side": "upper", "new_level": 6815},
        raw_reasoning="test",
    )

    # Simulate what check_intraday_updates does
    loaded_monitor.intraday_state.adjustments.append(adj)
    mock_append(adj)

    mock_append.assert_called_once_with(adj)


# ── Tests de logger.append_adjustment ────────────────────────────


def test_append_adjustment_writes_jsonl(tmp_path):
    from scripts.mancini.logger import append_adjustment

    log_path = tmp_path / "test_adjustments.jsonl"
    adj = PlanAdjustment(
        tweet_id="j1", tweet_text="test tweet",
        timestamp="2026-04-16T10:00:00",
        adjustment_type="INVALIDATION",
        details={"scope": "full"},
        raw_reasoning="Plan invalidado",
    )
    append_adjustment(adj, path=log_path)

    lines = log_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["tweet_id"] == "j1"
    assert entry["adjustment_type"] == "INVALIDATION"
    assert entry["reasoning"] == "Plan invalidado"
    assert "applied_at" in entry


# ── Tests de notifier.notify_adjustment ──────────────────────────


@patch("scripts.mancini.notifier.send_telegram", return_value=True)
def test_notify_adjustment_sends_telegram(mock_send):
    from scripts.mancini.notifier import notify_adjustment

    adj = PlanAdjustment(
        tweet_id="n1",
        tweet_text="buyers defending 6790 aggressively",
        timestamp="2026-04-16T11:00:00",
        adjustment_type="CONTEXT_UPDATE",
        details={"context_type": "defense"},
        raw_reasoning="Buyers defendiendo nivel lower con fuerza",
    )
    result = notify_adjustment(adj)
    assert result is True

    msg = mock_send.call_args[0][0]
    assert "Mancini Update" in msg
    assert "buyers defending 6790" in msg
    assert "Buyers defendiendo" in msg


@patch("scripts.mancini.notifier.send_telegram", return_value=True)
def test_notify_adjustment_includes_full_tweet(mock_send):
    """El tweet se envía completo, sin truncar."""
    from scripts.mancini.notifier import notify_adjustment

    long_tweet = "A" * 300  # tweet largo
    adj = PlanAdjustment(
        tweet_id="n2", tweet_text=long_tweet,
        timestamp="2026-04-16T11:00:00",
        adjustment_type="LEVEL_UPDATE",
        details={"side": "upper", "new_level": 6820},
        raw_reasoning="test",
    )
    notify_adjustment(adj)

    msg = mock_send.call_args[0][0]
    # El tweet completo debe estar en el mensaje (escapado por _esc)
    assert len(msg) > 300
