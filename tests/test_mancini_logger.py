"""Tests para scripts/mancini/logger.py — Registro JSONL de trades."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from scripts.mancini.trade_manager import Trade, TradeStatus, ExitReason
from scripts.mancini.logger import (
    append_trade, append_trade_open, append_trade_close,
    append_trade_target_hit, read_trades, trades_for_date,
)


def _make_trade(entry_time="2026-04-10T14:00:00Z", **kwargs) -> Trade:
    defaults = dict(
        id="test-001",
        direction="LONG",
        entry_price=6783,
        entry_time=entry_time,
        stop_price=6772,
        targets=[6793, 6809],
        status=TradeStatus.CLOSED,
        exit_price=6793,
        exit_time="2026-04-10T14:30:00Z",
        exit_reason=ExitReason.TARGET_1,
        pnl_total_pts=10,
    )
    defaults.update(kwargs)
    return Trade(**defaults)


# ── append_trade (compat) ─────────────────────────────────────────────────────

def test_append_and_read(tmp_path):
    path = tmp_path / "trades.jsonl"
    trade = _make_trade()
    append_trade(trade, path=path)

    trades = read_trades(path=path)
    assert len(trades) == 1
    assert trades[0]["trade_id"] == "test-001"
    assert trades[0]["pnl_total_pts"] == 10
    assert trades[0]["record_type"] == "close"


def test_append_multiple(tmp_path):
    path = tmp_path / "trades.jsonl"
    append_trade(_make_trade(id="t1"), path=path)
    append_trade(_make_trade(id="t2"), path=path)

    trades = read_trades(path=path)
    assert len(trades) == 2
    assert trades[0]["trade_id"] == "t1"
    assert trades[1]["trade_id"] == "t2"


def test_read_empty_file(tmp_path):
    path = tmp_path / "trades.jsonl"
    assert read_trades(path=path) == []


def test_creates_parent_dirs(tmp_path):
    path = tmp_path / "sub" / "dir" / "trades.jsonl"
    append_trade(_make_trade(), path=path)
    assert path.exists()


def test_trades_for_date(tmp_path):
    path = tmp_path / "trades.jsonl"
    append_trade(_make_trade(id="t1", entry_time="2026-04-10T14:00:00Z"), path=path)
    append_trade(_make_trade(id="t2", entry_time="2026-04-11T09:00:00Z"), path=path)
    append_trade(_make_trade(id="t3", entry_time="2026-04-10T15:30:00Z"), path=path)

    filtered = trades_for_date("2026-04-10", path=path)
    assert len(filtered) == 2
    assert {t["trade_id"] for t in filtered} == {"t1", "t3"}


def test_trades_for_date_no_match(tmp_path):
    path = tmp_path / "trades.jsonl"
    append_trade(_make_trade(entry_time="2026-04-10T14:00:00Z"), path=path)

    assert trades_for_date("2026-04-11", path=path) == []


def test_jsonl_format(tmp_path):
    """Cada registro close es una línea JSON válida con trade_id."""
    path = tmp_path / "trades.jsonl"
    append_trade(_make_trade(id="t1"), path=path)
    append_trade(_make_trade(id="t2"), path=path)

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    for line in lines:
        parsed = json.loads(line)
        assert "trade_id" in parsed
        assert parsed["record_type"] == "close"


# ── append_trade_close ────────────────────────────────────────────────────────

def test_close_schema(tmp_path):
    """Registro close contiene campos estadísticos."""
    path = tmp_path / "trades.jsonl"
    trade = _make_trade(id="c1")
    append_trade_close(trade, path=path)

    records = read_trades(path=path)
    assert len(records) == 1
    r = records[0]
    assert r["record_type"] == "close"
    assert r["trade_id"] == "c1"
    assert "pnl_total_pts" in r
    assert "pnl_per_risk" in r
    assert "duration_minutes" in r
    assert "mfe_pts" in r
    assert "dry_run" in r


def test_pnl_per_risk(tmp_path):
    """pnl_per_risk = pnl / risk_pts."""
    path = tmp_path / "trades.jsonl"
    trade = _make_trade(entry_price=6783, stop_price=6773, pnl_total_pts=10)  # risk=10
    append_trade_close(trade, path=path)

    r = read_trades(path=path)[0]
    assert r["pnl_per_risk"] == pytest.approx(1.0, abs=0.01)


def test_duration_minutes(tmp_path):
    """duration_minutes calculado desde entry a exit."""
    path = tmp_path / "trades.jsonl"
    trade = _make_trade(
        entry_time="2026-04-10T14:00:00Z",
        exit_time="2026-04-10T15:00:00Z",
    )
    append_trade_close(trade, path=path)

    r = read_trades(path=path)[0]
    assert r["duration_minutes"] == 60


# ── append_trade_open ─────────────────────────────────────────────────────────

def test_open_schema(tmp_path):
    """Registro open contiene contexto de entrada."""
    path = tmp_path / "trades.jsonl"
    trade = _make_trade(id="o1", breakdown_low=6775.0, alignment="ALIGNED")
    append_trade_open(trade, level=6780.0, minutes_from_open=45, path=path)

    records = read_trades(path=path)
    assert len(records) == 1
    r = records[0]
    assert r["record_type"] == "open"
    assert r["trade_id"] == "o1"
    assert r["level"] == 6780.0
    assert r["alignment"] == "ALIGNED"
    assert r["minutes_from_open"] == 45
    assert "risk_pts" in r
    assert "depth_pts" in r
    assert "day_of_week" in r


# ── append_trade_target_hit ───────────────────────────────────────────────────

def test_target_hit_schema(tmp_path):
    """Registro target_hit contiene pnl y mfe en ese momento."""
    path = tmp_path / "trades.jsonl"
    trade = _make_trade(id="th1", mfe_pts=12.5)
    event = {
        "target_index": 0,
        "target_price": 6793.0,
        "price": 6793.5,
        "timestamp": "2026-04-10T14:20:00Z",
        "new_stop": 6783.0,
        "old_stop": 6772.0,
    }
    append_trade_target_hit(trade, event, path=path)

    records = read_trades(path=path)
    assert len(records) == 1
    r = records[0]
    assert r["record_type"] == "target_hit"
    assert r["trade_id"] == "th1"
    assert r["target_index"] == 0
    assert r["pnl_at_hit_pts"] == pytest.approx(10.5, abs=0.1)
    assert r["mfe_pts"] == 12.5


# ── lifecycle completo ────────────────────────────────────────────────────────

def test_three_records_same_trade_id(tmp_path):
    """Los tres registros de un trade comparten trade_id."""
    path = tmp_path / "trades.jsonl"
    trade = _make_trade(id="full-trade")

    append_trade_open(trade, level=6780.0, minutes_from_open=30, path=path)
    append_trade_target_hit(trade, {
        "target_index": 0, "target_price": 6793.0, "price": 6793.0,
        "timestamp": "2026-04-10T14:20:00Z", "new_stop": 6783.0, "old_stop": 6772.0,
    }, path=path)
    append_trade_close(trade, path=path)

    records = read_trades(path=path)
    assert len(records) == 3
    assert all(r["trade_id"] == "full-trade" for r in records)
    types = {r["record_type"] for r in records}
    assert types == {"open", "target_hit", "close"}
