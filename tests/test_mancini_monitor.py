"""Tests para scripts/mancini/monitor.py — Monitor /ES con detectores y trades."""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from scripts.mancini.config import DailyPlan, save_plan, save_weekly
from scripts.mancini.detector import State, save_detectors, FailedBreakdownDetector
from scripts.mancini.trade_manager import TradeStatus
from scripts.mancini.monitor import ManciniMonitor, ET, compute_level_context, CONTEXT_ALERT_PTS


@pytest.fixture
def plan_path(tmp_path):
    return tmp_path / "mancini_plan.json"


@pytest.fixture
def state_path(tmp_path):
    return tmp_path / "mancini_state.json"


@pytest.fixture
def sample_plan(plan_path):
    plan = DailyPlan(
        fecha="2026-04-10",
        key_level_upper=6809,
        targets_upper=[6819, 6830],
        key_level_lower=6781,
        targets_lower=[6766],
    )
    save_plan(plan, plan_path)
    return plan


@pytest.fixture
def weekly_path(tmp_path):
    return tmp_path / "mancini_weekly.json"


@pytest.fixture
def monitor(plan_path, state_path, weekly_path):
    """Monitor sin client, gate desactivado (para tests sin TastyTrade/LLM)."""
    m = ManciniMonitor(client=None, plan_path=plan_path, state_path=state_path,
                       weekly_path=weekly_path, gate_enabled=False)
    return m


# ── Mock notifier para todos los tests ──────────────────────────────

@pytest.fixture(autouse=True)
def mock_now_et():
    """Parchea _now_et para devolver 2026-04-10 (coincide con sample_plan.fecha)."""
    fake_now = datetime(2026, 4, 10, 9, 30, 0, tzinfo=ET)
    with patch("scripts.mancini.monitor._now_et", return_value=fake_now):
        yield fake_now


@pytest.fixture(autouse=True)
def mock_notifier():
    with patch("scripts.mancini.monitor.notifier") as mock:
        mock.notify_plan_loaded.return_value = True
        mock.notify_breakdown.return_value = True
        mock.notify_signal.return_value = True
        mock.notify_trade_closed.return_value = True
        mock.notify_target_hit.return_value = True
        mock.notify_gate_approved.return_value = True
        mock.notify_trade_rejected.return_value = True
        mock.notify_session_summary.return_value = True
        yield mock


@pytest.fixture(autouse=True)
def mock_logger():
    with patch("scripts.mancini.monitor.append_trade") as mock_trade, \
         patch("scripts.mancini.monitor.append_gate_decision") as mock_gate:
        yield mock_trade


# ── load_state ──────────────────────────────────────────────────────

def test_load_state_creates_detectors(monitor, sample_plan):
    monitor.load_state()
    assert monitor.plan is not None
    assert monitor.plan.key_level_upper == 6809
    assert len(monitor.detectors) == 2
    assert monitor.detectors[0].level == 6809
    assert monitor.detectors[1].level == 6781


def test_load_state_no_plan(monitor):
    monitor.load_state()
    assert monitor.plan is None
    assert monitor.detectors == []


def test_load_state_restores_existing(monitor, sample_plan, state_path):
    # Pre-guardar detectores con estado
    detectors = [
        FailedBreakdownDetector(level=6809, side="upper", state=State.BREAKDOWN, breakdown_low=6804),
        FailedBreakdownDetector(level=6781, side="lower"),
    ]
    save_detectors(detectors, state_path)

    monitor.load_state()
    assert monitor.detectors[0].state == State.BREAKDOWN
    assert monitor.detectors[0].breakdown_low == 6804


# ── process_tick — secuencia completa ───────────────────────────────

def test_process_tick_no_event(monitor, sample_plan):
    """Precio fuera de rango de breakdown → sin eventos."""
    monitor.load_state()
    events = monitor.process_tick(6790, "2026-04-10T14:00:00Z")
    assert events == []


def test_process_tick_breakdown(monitor, sample_plan, mock_notifier):
    """Precio rompe nivel inferior → BREAKDOWN + alerta."""
    monitor.load_state()
    events = monitor.process_tick(6776, "2026-04-10T14:00:00Z")

    # Debe haber un evento de breakdown para el nivel 6781
    breakdown_events = [e for e in events if "BREAKDOWN" in e["type"]]
    assert len(breakdown_events) == 1
    assert breakdown_events[0]["level"] == 6781

    mock_notifier.notify_breakdown.assert_called_once()


def test_full_failed_breakdown_to_trade(monitor, sample_plan, mock_notifier):
    """Secuencia completa: breakdown → recovery → signal → trade abierto."""
    monitor.load_state()

    # Breakdown en nivel inferior (6781)
    monitor.process_tick(6776, "2026-04-10T14:00:00Z")
    assert monitor.detectors[1].state == State.BREAKDOWN

    # Recovery
    monitor.process_tick(6783, "2026-04-10T14:01:00Z")
    assert monitor.detectors[1].state == State.RECOVERY

    # Aceptacion (3 polls)
    monitor.process_tick(6784, "2026-04-10T14:02:00Z")
    events = monitor.process_tick(6785, "2026-04-10T14:03:00Z")

    # Debe haber signal + trade abierto
    signal_events = [e for e in events if "SIGNAL" in e["type"]]
    assert len(signal_events) == 1

    mock_notifier.notify_signal.assert_called_once()

    # Trade LONG con targets_upper (6819, 6830) — no targets_lower
    trade = monitor.trade_manager.active_trade()
    assert trade is not None
    assert trade.direction == "LONG"
    assert trade.targets == [6819, 6830]  # targets hacia arriba
    assert monitor.detectors[1].state == State.ACTIVE


def test_full_sequence_with_target(monitor, sample_plan, mock_notifier):
    """Secuencia completa hasta target 1 (trailing stop a breakeven)."""
    monitor.load_state()

    # Breakdown → Recovery → Signal
    monitor.process_tick(6776, "2026-04-10T14:00:00Z")
    monitor.process_tick(6783, "2026-04-10T14:01:00Z")
    monitor.process_tick(6784, "2026-04-10T14:02:00Z")
    monitor.process_tick(6785, "2026-04-10T14:03:00Z")  # SIGNAL + trade LONG

    # Trade abierto LONG con targets [6819, 6830]
    trade = monitor.trade_manager.active_trade()
    assert trade is not None
    assert trade.targets == [6819, 6830]

    # Precio sube hacia Target 1 (6819)
    monitor.process_tick(6810, "2026-04-10T14:04:00Z")  # sin evento
    events = monitor.process_tick(6819, "2026-04-10T14:05:00Z")  # Target 1!

    target_events = [e for e in events if e["type"] == "TARGET_HIT"]
    assert len(target_events) == 1
    assert target_events[0]["target_index"] == 0
    assert target_events[0]["new_stop"] == 6785  # breakeven (entry_price)

    # Trade sigue OPEN con stop a breakeven
    trade = monitor.trade_manager.active_trade()
    assert trade.status == TradeStatus.OPEN
    assert trade.stop_price == 6785  # breakeven
    assert trade.targets_hit == 1


def test_state_persistence(monitor, sample_plan, state_path):
    """Estado se persiste correctamente tras process_tick."""
    monitor.load_state()
    monitor.process_tick(6776, "2026-04-10T14:00:00Z")
    monitor.save_state()

    assert state_path.exists()
    data = json.loads(state_path.read_text(encoding="utf-8"))
    detectors = data["detectors"]
    lower = [d for d in detectors if d["side"] == "lower"][0]
    assert lower["state"] == "BREAKDOWN"


def test_scan_for_plan_finds_existing(monitor, sample_plan):
    """_scan_for_plan encuentra plan existente en disco."""
    # Plan ya existe en disco (sample_plan fixture)
    found = monitor._scan_for_plan()
    assert found is True
    assert monitor.plan is not None
    assert monitor.plan.key_level_upper == 6809


# ── close_session ───────────────────────────────────────────────────

def test_close_session_no_trades(monitor, sample_plan, mock_notifier):
    """Cierre de sesion sin trades → resumen con 0 trades."""
    monitor.load_state()
    monitor.close_session()

    mock_notifier.notify_session_summary.assert_called_once()
    call_args = mock_notifier.notify_session_summary.call_args[0]
    assert call_args[1] == 0  # trades_count
    assert call_args[2] == 0  # total_pnl


def test_close_session_expires_detectors(monitor, sample_plan):
    """Cierre de sesion expira detectores activos."""
    monitor.load_state()
    monitor.close_session()

    for d in monitor.detectors:
        assert d.state == State.EXPIRED


# ── Weekly alignment ──────────────────────────────────────────────────

def test_calc_weekly_bias_bullish(monitor, weekly_path):
    """Plan semanal con notes alcista → BULLISH."""
    weekly = DailyPlan(
        fecha="2026-04-14",
        key_level_upper=6817,
        targets_upper=[6903, 6950],
        key_level_lower=6793,
        targets_lower=[],
        notes="Sesgo: alcista. Bull flag breakout.",
    )
    save_weekly(weekly, weekly_path)
    monitor.weekly = weekly
    assert monitor.calc_weekly_bias() == "BULLISH"


def test_calc_weekly_bias_bearish(monitor, weekly_path):
    """Plan semanal bajista → BEARISH."""
    weekly = DailyPlan(
        fecha="2026-04-14",
        key_level_upper=6800,
        targets_upper=[],
        key_level_lower=6750,
        targets_lower=[6700, 6650],
        notes="Sesgo: bajista. Breakdown confirmado.",
    )
    save_weekly(weekly, weekly_path)
    monitor.weekly = weekly
    assert monitor.calc_weekly_bias() == "BEARISH"


def test_calc_weekly_bias_neutral_no_weekly(monitor):
    """Sin plan semanal → NEUTRAL."""
    assert monitor.calc_weekly_bias() == "NEUTRAL"


def test_calc_weekly_bias_fallback_targets(monitor):
    """Sin palabra clave pero targets solo alcistas → BULLISH."""
    monitor.weekly = DailyPlan(
        fecha="2026-04-14",
        key_level_upper=6817,
        targets_upper=[6903],
        key_level_lower=6793,
        targets_lower=[],
        notes="Plan para la semana.",
    )
    assert monitor.calc_weekly_bias() == "BULLISH"


def test_calc_alignment_aligned(monitor):
    """LONG con sesgo BULLISH → ALIGNED."""
    monitor.weekly = DailyPlan(
        fecha="2026-04-14", key_level_upper=6817, targets_upper=[6903],
        key_level_lower=6793, targets_lower=[],
        notes="Sesgo: alcista",
    )
    assert monitor.calc_alignment("LONG") == "ALIGNED"


def test_calc_alignment_misaligned(monitor):
    """SHORT con sesgo BULLISH → MISALIGNED."""
    monitor.weekly = DailyPlan(
        fecha="2026-04-14", key_level_upper=6817, targets_upper=[6903],
        key_level_lower=6793, targets_lower=[],
        notes="Sesgo: alcista",
    )
    assert monitor.calc_alignment("SHORT") == "MISALIGNED"


def test_calc_alignment_neutral(monitor):
    """Sin weekly → NEUTRAL."""
    assert monitor.calc_alignment("LONG") == "NEUTRAL"


def test_misaligned_trade_only_t1(monitor, sample_plan, mock_notifier, weekly_path):
    """Trade MISALIGNED solo tiene Target 1 (sin runner)."""
    # Weekly bajista → LONG será MISALIGNED
    weekly = DailyPlan(
        fecha="2026-04-14", key_level_upper=6800, targets_upper=[],
        key_level_lower=6750, targets_lower=[6700],
        notes="Sesgo: bajista",
    )
    save_weekly(weekly, weekly_path)
    monitor.load_state()

    # Secuencia: breakdown → recovery → signal
    monitor.process_tick(6776, "2026-04-10T14:00:00Z")
    monitor.process_tick(6783, "2026-04-10T14:01:00Z")
    monitor.process_tick(6784, "2026-04-10T14:02:00Z")
    monitor.process_tick(6785, "2026-04-10T14:03:00Z")

    trade = monitor.trade_manager.active_trade()
    assert trade is not None
    assert trade.alignment == "MISALIGNED"
    assert len(trade.targets) == 1  # Solo T1, sin runner


def test_aligned_trade_extended_targets(monitor, sample_plan, mock_notifier, weekly_path):
    """Trade ALIGNED enriquece targets con weekly."""
    # Weekly alcista con target 6950 (mayor que daily 6830)
    weekly = DailyPlan(
        fecha="2026-04-14", key_level_upper=6817,
        targets_upper=[6903, 6950],
        key_level_lower=6793, targets_lower=[],
        notes="Sesgo: alcista",
    )
    save_weekly(weekly, weekly_path)
    monitor.load_state()

    # Secuencia: breakdown → recovery → signal
    monitor.process_tick(6776, "2026-04-10T14:00:00Z")
    monitor.process_tick(6783, "2026-04-10T14:01:00Z")
    monitor.process_tick(6784, "2026-04-10T14:02:00Z")
    monitor.process_tick(6785, "2026-04-10T14:03:00Z")

    trade = monitor.trade_manager.active_trade()
    assert trade is not None
    assert trade.alignment == "ALIGNED"
    # Daily targets [6819, 6830] + weekly [6903] (primer target > 6830)
    assert 6903 in trade.targets
    assert trade.targets == [6819, 6830, 6903]


def test_alignment_in_notification(monitor, sample_plan, mock_notifier, weekly_path):
    """Notificación incluye alignment."""
    weekly = DailyPlan(
        fecha="2026-04-14", key_level_upper=6817, targets_upper=[6903],
        key_level_lower=6793, targets_lower=[],
        notes="Sesgo: alcista",
    )
    save_weekly(weekly, weekly_path)
    monitor.load_state()

    # Secuencia completa hasta SIGNAL
    monitor.process_tick(6776, "2026-04-10T14:00:00Z")
    monitor.process_tick(6783, "2026-04-10T14:01:00Z")
    monitor.process_tick(6784, "2026-04-10T14:02:00Z")
    monitor.process_tick(6785, "2026-04-10T14:03:00Z")

    # Verificar que notify_signal recibió alignment
    mock_notifier.notify_signal.assert_called_once()
    call_kwargs = mock_notifier.notify_signal.call_args
    assert call_kwargs.kwargs.get("alignment") == "ALIGNED" or \
           (len(call_kwargs.args) > 6 and call_kwargs.args[6] == "ALIGNED")


# ── Date validation ────────────────────────────────────────────────

def test_load_state_stale_plan_discarded(plan_path, state_path, weekly_path):
    """Plan con fecha distinta a hoy se descarta."""
    # Plan de ayer
    plan = DailyPlan(
        fecha="2026-04-09",
        key_level_upper=6809,
        targets_upper=[6819, 6830],
        key_level_lower=6781,
        targets_lower=[6766],
    )
    save_plan(plan, plan_path)

    # _now_et devuelve 2026-04-10 (mock_now_et fixture)
    m = ManciniMonitor(client=None, plan_path=plan_path, state_path=state_path,
                       weekly_path=weekly_path, gate_enabled=False)
    m.load_state()
    assert m.plan is None
    assert m.detectors == []


# ── Scan for plan ─────────────────────────────────────────────────

def test_scan_for_plan_finds_existing_on_disk(plan_path, state_path, weekly_path,
                                               mock_notifier):
    """_scan_for_plan detecta plan existente en disco y envía chart + notificación."""
    plan = DailyPlan(
        fecha="2026-04-10",
        key_level_upper=6809,
        targets_upper=[6819, 6830],
        key_level_lower=6781,
        targets_lower=[6766],
    )
    save_plan(plan, plan_path)

    m = ManciniMonitor(client=None, plan_path=plan_path, state_path=state_path,
                       weekly_path=weekly_path, poll_interval=0, gate_enabled=False)

    with patch.object(m, "poll_es", return_value=6810.0):
        found = m._scan_for_plan()

    assert found is True
    assert m.plan is not None
    assert m.plan.fecha == "2026-04-10"
    # Notificaciones enviadas también cuando el plan viene de disco
    mock_notifier.notify_plan_loaded.assert_called_once()
    mock_notifier.notify_plan_chart.assert_called_once()


def test_scan_for_plan_respects_session_end(plan_path, state_path, weekly_path):
    """_scan_for_plan se para al llegar a session_end sin plan."""
    # session_end=9, _now_et devuelve 09:30 → ya pasó session_end
    m = ManciniMonitor(client=None, plan_path=plan_path, state_path=state_path,
                       weekly_path=weekly_path, session_end=9, poll_interval=0,
                       gate_enabled=False)

    found = m._scan_for_plan()
    assert found is False
    assert m.plan is None


@patch("scripts.mancini.tweet_parser.parse_tweets_to_plan")
@patch("scripts.mancini.tweet_fetcher.fetch_mancini_tweets")
def test_scan_for_plan_fetches_tweets(mock_fetch, mock_parse,
                                       plan_path, state_path, weekly_path,
                                       mock_notifier, tmp_path):
    """_scan_for_plan hace fetch + parse cuando no hay plan en disco."""
    mock_fetch.return_value = [
        {"id": "t1", "text": "ES 7058 reclaims, see 7103, 7116", "created_at": "2026-04-10T08:00:00-04:00"},
    ]
    mock_parse.return_value = DailyPlan(
        fecha="2026-04-10",
        key_level_upper=7058,
        targets_upper=[7103, 7116],
        key_level_lower=None,
        targets_lower=[],
        raw_tweets=["ES 7058 reclaims, see 7103, 7116"],
    )

    intraday_path = tmp_path / "mancini_intraday.json"
    m = ManciniMonitor(client=None, plan_path=plan_path, state_path=state_path,
                       weekly_path=weekly_path, intraday_path=intraday_path,
                       poll_interval=0, gate_enabled=False)

    with patch("scripts.mancini.monitor._now_et",
               return_value=datetime(2026, 4, 10, 9, 30, 0, tzinfo=ET)):
        found = m._scan_for_plan()

    assert found is True
    assert m.plan.key_level_upper == 7058
    assert m.plan.targets_upper == [7103, 7116]
    # Tweet marcado como procesado para que el clasificador no lo re-procese
    assert "t1" in m.intraday_state.processed_tweet_ids
    mock_notifier.notify_plan_loaded.assert_called_once()


@patch("scripts.mancini.tweet_parser.parse_tweets_to_plan")
@patch("scripts.mancini.tweet_fetcher.fetch_mancini_tweets")
def test_scan_for_plan_no_plan_keeps_tweets_unprocessed(mock_fetch, mock_parse,
                                                         plan_path, state_path,
                                                         weekly_path, mock_notifier,
                                                         tmp_path):
    """Cuando Haiku no encuentra plan, los tweets NO se marcan como procesados."""
    mock_fetch.return_value = [
        {"id": "t1", "text": "Some reply tweet", "created_at": "2026-04-23T08:00:00-04:00"},
    ]
    mock_parse.return_value = None  # Haiku no encontró plan

    intraday_path = tmp_path / "mancini_intraday.json"
    # session_end=4: cuando _now_et devuelva 4:00 ET el loop sale
    m = ManciniMonitor(client=None, plan_path=plan_path, state_path=state_path,
                       weekly_path=weekly_path, intraday_path=intraday_path,
                       poll_interval=0, tweet_poll_interval=0, session_end=4,
                       gate_enabled=False)

    times = [
        datetime(2026, 4, 23, 3, 0, 0, tzinfo=ET),   # primer ciclo: buscar tweets
        datetime(2026, 4, 23, 4, 0, 0, tzinfo=ET),   # segundo ciclo: hour>=session_end → salir
    ]
    time_iter = iter(times)

    with patch("scripts.mancini.monitor._now_et", side_effect=lambda: next(time_iter, times[-1])):
        m._scan_for_plan()

    # El tweet NO debe estar en processed_tweet_ids — puede reintentarse cuando haya plan real
    assert "t1" not in m.intraday_state.processed_tweet_ids


# ── compute_level_context ────────────────────────────────────────────

def test_context_standby_far_above_level():
    """Precio muy por encima del nivel → STANDBY."""
    ctx = compute_level_context(7151.0, 7120.0, State.WATCHING)
    assert ctx == "STANDBY"


def test_context_alert_zone_near_level():
    """Precio dentro de CONTEXT_ALERT_PTS → ALERT_ZONE."""
    ctx = compute_level_context(7124.0, 7120.0, State.WATCHING)
    assert ctx == "ALERT_ZONE"


def test_context_alert_zone_exactly_at_threshold():
    """Precio exactamente en el umbral (nivel + CONTEXT_ALERT_PTS) → ALERT_ZONE."""
    ctx = compute_level_context(7120.0 + CONTEXT_ALERT_PTS, 7120.0, State.WATCHING)
    assert ctx == "ALERT_ZONE"


def test_context_just_above_threshold_is_standby():
    """Un punto sobre el umbral → STANDBY."""
    ctx = compute_level_context(7120.0 + CONTEXT_ALERT_PTS + 1, 7120.0, State.WATCHING)
    assert ctx == "STANDBY"


def test_context_below_level():
    """Precio bajo el nivel (sin activar detector) → BELOW_LEVEL."""
    ctx = compute_level_context(7118.0, 7120.0, State.WATCHING)
    assert ctx == "BELOW_LEVEL"


def test_context_delegates_to_detector_state():
    """Si el detector no está en WATCHING, retorna el valor del estado."""
    assert compute_level_context(7118.0, 7120.0, State.BREAKDOWN) == "BREAKDOWN"
    assert compute_level_context(7122.0, 7120.0, State.RECOVERY) == "RECOVERY"
    assert compute_level_context(7122.0, 7120.0, State.SIGNAL) == "SIGNAL"
    assert compute_level_context(7122.0, 7120.0, State.ACTIVE) == "ACTIVE"


def test_approaching_alert_fires_on_standby_to_alert(mock_notifier, sample_plan, state_path, plan_path, weekly_path):
    """El monitor envía notify_approaching_level al entrar en ALERT_ZONE desde STANDBY."""
    monitor = ManciniMonitor(
        client=None,
        plan_path=plan_path,
        state_path=state_path,
        weekly_path=weekly_path,
        poll_interval=0,
        gate_enabled=False,
    )
    monitor.plan = sample_plan
    monitor._init_detectors()

    level = sample_plan.key_level_lower  # 6781

    # Primer tick: precio lejos → STANDBY (no alerta)
    monitor.process_tick(level + CONTEXT_ALERT_PTS + 5)
    mock_notifier.notify_approaching_level.assert_not_called()

    # Segundo tick: precio entra en ALERT_ZONE → alerta
    monitor.process_tick(level + CONTEXT_ALERT_PTS - 1)
    mock_notifier.notify_approaching_level.assert_called_once()
