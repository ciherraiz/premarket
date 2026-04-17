"""Tests para scripts/mancini/trade_manager.py — Gestión de trades Mancini.

Actualizados para trailing stop con 1 contrato (sin salida parcial).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from scripts.mancini.trade_manager import (
    Trade,
    TradeManager,
    TradeStatus,
    ExitReason,
    calc_stop,
    MAX_STOP_PTS,
    STOP_BUFFER_PTS,
    MAX_TRADES_PER_DAY,
)


TS = "2026-04-10T14:00:00Z"
TS2 = "2026-04-10T14:05:00Z"
TS3 = "2026-04-10T14:10:00Z"
TS4 = "2026-04-10T14:15:00Z"


# ── calc_stop ───────────────────────────────────────────────────────

def test_calc_stop_long_technical():
    """Stop técnico: breakdown_low - buffer."""
    stop = calc_stop("LONG", entry_price=6783, breakdown_low=6774)
    assert stop == 6774 - STOP_BUFFER_PTS  # 6772


def test_calc_stop_long_capped():
    """Stop no puede superar MAX_STOP_PTS desde entry."""
    # breakdown_low muy lejos → cap a entry - 15
    stop = calc_stop("LONG", entry_price=6783, breakdown_low=6760)
    assert stop == 6783 - MAX_STOP_PTS  # 6768


def test_calc_stop_short_technical():
    stop = calc_stop("SHORT", entry_price=6809, breakdown_low=6818)
    assert stop == 6818 + STOP_BUFFER_PTS  # 6820


def test_calc_stop_short_capped():
    stop = calc_stop("SHORT", entry_price=6809, breakdown_low=6830)
    assert stop == 6809 + MAX_STOP_PTS  # 6824


# ── TradeManager.open_trade ─────────────────────────────────────────

def test_open_trade_basic():
    tm = TradeManager(fecha="2026-04-10")
    trade = tm.open_trade("LONG", 6783, breakdown_low=6774,
                          targets=[6793, 6809], timestamp=TS)
    assert trade is not None
    assert trade.direction == "LONG"
    assert trade.entry_price == 6783
    assert trade.status == TradeStatus.OPEN
    assert trade.stop_price == 6774 - STOP_BUFFER_PTS
    assert trade.targets == [6793, 6809]
    assert trade.targets_hit == 0
    assert tm.trades_today() == 1


def test_open_trade_max_per_day():
    """No se pueden abrir más de MAX_TRADES_PER_DAY trades."""
    tm = TradeManager(fecha="2026-04-10")
    for i in range(MAX_TRADES_PER_DAY):
        t = tm.open_trade("LONG", 6783 + i, breakdown_low=6774,
                          targets=[6793], timestamp=TS)
        assert t is not None
        # Cerrar para poder abrir otro
        t.status = TradeStatus.CLOSED

    # El siguiente debe fallar
    t = tm.open_trade("LONG", 6790, breakdown_low=6774,
                      targets=[6793], timestamp=TS)
    assert t is None


def test_cannot_open_while_active():
    """No se puede abrir un trade si ya hay uno activo."""
    tm = TradeManager(fecha="2026-04-10")
    tm.open_trade("LONG", 6783, breakdown_low=6774,
                  targets=[6793], timestamp=TS)
    t2 = tm.open_trade("LONG", 6790, breakdown_low=6780,
                       targets=[6800], timestamp=TS)
    assert t2 is None


# ── LONG trailing stop lifecycle ────────────────────────────────────

def test_long_stop_hit():
    """LONG: precio cae al stop → trade cerrado."""
    tm = TradeManager(fecha="2026-04-10")
    tm.open_trade("LONG", 6783, breakdown_low=6774,
                  targets=[6793, 6809], timestamp=TS)

    events = tm.process_tick(6770, timestamp=TS2)
    assert len(events) == 1
    assert events[0]["type"] == "TRADE_CLOSED"
    assert events[0]["reason"] == ExitReason.STOP
    assert tm.active_trade() is None


def test_long_t1_hit_stop_to_breakeven():
    """LONG: T1 alcanzado → stop sube a breakeven (entry_price)."""
    tm = TradeManager(fecha="2026-04-10")
    tm.open_trade("LONG", 6783, breakdown_low=6774,
                  targets=[6793, 6809], timestamp=TS)

    events = tm.process_tick(6793, timestamp=TS2)
    assert len(events) == 1
    assert events[0]["type"] == "TARGET_HIT"
    assert events[0]["target_index"] == 0
    assert events[0]["new_stop"] == 6783  # breakeven

    trade = tm.active_trade()
    assert trade.status == TradeStatus.OPEN  # NO cambia a PARTIAL
    assert trade.stop_price == 6783
    assert trade.targets_hit == 1


def test_long_t2_hit_stop_to_t1():
    """LONG: T2 alcanzado → stop sube a T1."""
    tm = TradeManager(fecha="2026-04-10")
    tm.open_trade("LONG", 6783, breakdown_low=6774,
                  targets=[6793, 6809, 6830], timestamp=TS)

    tm.process_tick(6793, timestamp=TS2)  # T1 → breakeven
    events = tm.process_tick(6809, timestamp=TS3)  # T2

    assert len(events) == 1
    assert events[0]["type"] == "TARGET_HIT"
    assert events[0]["target_index"] == 1
    assert events[0]["new_stop"] == 6793  # T1

    trade = tm.active_trade()
    assert trade.stop_price == 6793
    assert trade.targets_hit == 2


def test_long_t3_hit_stop_to_t2():
    """LONG: T3 alcanzado → stop sube a T2."""
    tm = TradeManager(fecha="2026-04-10")
    tm.open_trade("LONG", 6783, breakdown_low=6774,
                  targets=[6793, 6809, 6830], timestamp=TS)

    tm.process_tick(6793, timestamp=TS2)  # T1
    tm.process_tick(6809, timestamp=TS3)  # T2
    events = tm.process_tick(6830, timestamp=TS4)  # T3

    assert len(events) == 1
    assert events[0]["target_index"] == 2
    assert events[0]["new_stop"] == 6809  # T2

    trade = tm.active_trade()
    assert trade.stop_price == 6809
    assert trade.targets_hit == 3


def test_long_stop_after_t1_breakeven():
    """LONG: tras T1, precio cae a breakeven → cerrado con P&L 0."""
    tm = TradeManager(fecha="2026-04-10")
    tm.open_trade("LONG", 6783, breakdown_low=6774,
                  targets=[6793, 6809], timestamp=TS)

    tm.process_tick(6793, timestamp=TS2)  # T1 → stop a 6783
    events = tm.process_tick(6783, timestamp=TS3)  # toca stop

    assert len(events) == 1
    assert events[0]["type"] == "TRADE_CLOSED"
    assert events[0]["reason"] == ExitReason.STOP
    assert events[0]["pnl_total_pts"] == 0  # breakeven


def test_long_no_event_between_levels():
    """LONG: precio entre entry y target → sin eventos."""
    tm = TradeManager(fecha="2026-04-10")
    tm.open_trade("LONG", 6783, breakdown_low=6774,
                  targets=[6793, 6809], timestamp=TS)

    events = tm.process_tick(6788, timestamp=TS2)
    assert events == []
    assert tm.active_trade().status == TradeStatus.OPEN


def test_long_single_target_no_partial():
    """LONG: con 1 solo target, T1 → stop a breakeven, NO cierra."""
    tm = TradeManager(fecha="2026-04-10")
    tm.open_trade("LONG", 6783, breakdown_low=6774,
                  targets=[6793], timestamp=TS)

    events = tm.process_tick(6793, timestamp=TS2)
    assert len(events) == 1
    assert events[0]["type"] == "TARGET_HIT"

    # Trade sigue abierto con stop a breakeven
    trade = tm.active_trade()
    assert trade is not None
    assert trade.stop_price == 6783
    assert trade.targets_hit == 1


# ── SHORT trailing stop lifecycle ───────────────────────────────────

def test_short_stop_hit():
    """SHORT: precio sube al stop → cerrado."""
    tm = TradeManager(fecha="2026-04-10")
    tm.open_trade("SHORT", 6809, breakdown_low=6818,
                  targets=[6800, 6790], timestamp=TS)

    events = tm.process_tick(6825, timestamp=TS2)
    assert len(events) == 1
    assert events[0]["reason"] == ExitReason.STOP


def test_short_t1_stop_to_breakeven():
    """SHORT: T1 alcanzado → stop baja a breakeven."""
    tm = TradeManager(fecha="2026-04-10")
    tm.open_trade("SHORT", 6809, breakdown_low=6818,
                  targets=[6800, 6790], timestamp=TS)

    events = tm.process_tick(6800, timestamp=TS2)
    assert len(events) == 1
    assert events[0]["type"] == "TARGET_HIT"
    assert events[0]["new_stop"] == 6809  # breakeven

    trade = tm.active_trade()
    assert trade.stop_price == 6809
    assert trade.targets_hit == 1


def test_short_t2_stop_to_t1():
    """SHORT: T2 alcanzado → stop baja a T1."""
    tm = TradeManager(fecha="2026-04-10")
    tm.open_trade("SHORT", 6809, breakdown_low=6818,
                  targets=[6800, 6790], timestamp=TS)

    tm.process_tick(6800, timestamp=TS2)  # T1
    events = tm.process_tick(6790, timestamp=TS3)  # T2

    assert events[0]["new_stop"] == 6800  # T1
    assert tm.active_trade().targets_hit == 2


# ── EOD / Manual close ─────────────────────────────────────────────

def test_close_eod_open_trade():
    """Cierre EOD (manual) con trade abierto."""
    tm = TradeManager(fecha="2026-04-10")
    tm.open_trade("LONG", 6783, breakdown_low=6774,
                  targets=[6793], timestamp=TS)

    event = tm.close_eod(6788, timestamp=TS2)
    assert event is not None
    assert event["reason"] == ExitReason.EOD
    assert event["pnl_total_pts"] == 5  # 6788 - 6783


def test_close_manual_active_trade():
    """Cierre manual via Telegram."""
    tm = TradeManager(fecha="2026-04-10")
    tm.open_trade("LONG", 6783, breakdown_low=6774,
                  targets=[6793, 6809], timestamp=TS)

    tm.process_tick(6793, timestamp=TS2)  # T1

    event = tm.close_manual(6800, timestamp=TS3)
    assert event is not None
    assert event["reason"] == ExitReason.MANUAL
    assert event["pnl_total_pts"] == 17  # 6800 - 6783


def test_close_eod_no_active():
    """Cierre EOD sin trade activo → None."""
    tm = TradeManager(fecha="2026-04-10")
    assert tm.close_eod(6788) is None


# ── Full lifecycle ──────────────────────────────────────────────────

def test_full_lifecycle_trailing_stop():
    """Ciclo completo: open → T1 (breakeven) → T2 (stop a T1) → stop hit."""
    tm = TradeManager(fecha="2026-04-10")
    trade = tm.open_trade("LONG", 6783, breakdown_low=6774,
                          targets=[6793, 6809], timestamp=TS)
    assert trade.status == TradeStatus.OPEN

    # Tick: sin evento
    assert tm.process_tick(6785, timestamp=TS) == []

    # Target 1 → stop a breakeven
    events = tm.process_tick(6795, timestamp=TS2)
    assert events[0]["type"] == "TARGET_HIT"
    assert events[0]["new_stop"] == 6783

    # Tick intermedio: sin evento
    assert tm.process_tick(6800, timestamp=TS3) == []

    # Target 2 → stop a T1
    events = tm.process_tick(6810, timestamp=TS4)
    assert events[0]["type"] == "TARGET_HIT"
    assert events[0]["new_stop"] == 6793  # T1

    # Stop hit a T1
    events = tm.process_tick(6793, timestamp="2026-04-10T14:20:00Z")
    assert events[0]["type"] == "TRADE_CLOSED"
    assert events[0]["reason"] == ExitReason.STOP
    assert events[0]["pnl_total_pts"] == 10  # 6793 - 6783


def test_full_lifecycle_long_stopped_out():
    """Ciclo completo: open → stop hit."""
    tm = TradeManager(fecha="2026-04-10")
    tm.open_trade("LONG", 6783, breakdown_low=6774,
                  targets=[6793, 6809], timestamp=TS)

    events = tm.process_tick(6771, timestamp=TS2)
    assert events[0]["type"] == "TRADE_CLOSED"
    assert events[0]["reason"] == ExitReason.STOP

    trade = tm.trades[0]
    assert trade.pnl_total_pts == -12  # 6771 - 6783


def test_multiple_trades_in_day():
    """Varios trades en un día (cerrar uno, abrir otro)."""
    tm = TradeManager(fecha="2026-04-10")

    # Trade 1: stopped out
    tm.open_trade("LONG", 6783, breakdown_low=6774,
                  targets=[6793], timestamp=TS)
    tm.process_tick(6770, timestamp=TS2)

    # Trade 2: T1 hit → runner with breakeven stop → stop hit at breakeven
    tm.open_trade("LONG", 6790, breakdown_low=6782,
                  targets=[6800], timestamp=TS3)
    events = tm.process_tick(6800, timestamp=TS4)
    assert events[0]["type"] == "TARGET_HIT"

    # Runner con stop a breakeven → toca stop
    events = tm.process_tick(6790, timestamp="2026-04-10T14:20:00Z")
    assert events[0]["type"] == "TRADE_CLOSED"

    assert tm.trades_today() == 2
    assert all(t.status == TradeStatus.CLOSED for t in tm.trades)


# ── targets_hit counter ────────────────────────────────────────────

def test_targets_hit_counter():
    """targets_hit incrementa correctamente con cada target."""
    tm = TradeManager(fecha="2026-04-10")
    tm.open_trade("LONG", 6780, breakdown_low=6770,
                  targets=[6790, 6800, 6810], timestamp=TS)

    trade = tm.active_trade()
    assert trade.targets_hit == 0

    tm.process_tick(6790, timestamp=TS2)
    assert trade.targets_hit == 1

    tm.process_tick(6800, timestamp=TS3)
    assert trade.targets_hit == 2

    tm.process_tick(6810, timestamp=TS4)
    assert trade.targets_hit == 3


# ── Serialización ───────────────────────────────────────────────────

def test_trade_to_dict_roundtrip():
    trade = Trade(
        id="test-123",
        direction="LONG",
        entry_price=6783,
        entry_time=TS,
        stop_price=6772,
        targets=[6793, 6809],
        status=TradeStatus.OPEN,
        targets_hit=1,
        entry_order_id="order-abc",
        stop_order_id="order-def",
        gate_decision={"execute": True, "reasoning": "ok", "risk_factors": []},
        execution_mode="auto",
    )
    d = trade.to_dict()
    restored = Trade.from_dict(d)
    assert restored.id == "test-123"
    assert restored.targets_hit == 1
    assert restored.entry_order_id == "order-abc"
    assert restored.gate_decision["execute"] is True


def test_trade_manager_to_dict_roundtrip():
    tm = TradeManager(fecha="2026-04-10")
    tm.open_trade("LONG", 6783, breakdown_low=6774,
                  targets=[6793], timestamp=TS)

    d = tm.to_dict()
    restored = TradeManager.from_dict(d)
    assert restored.fecha == "2026-04-10"
    assert len(restored.trades) == 1
    assert restored.trades[0].entry_price == 6783
