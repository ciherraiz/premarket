"""Tests para scripts/mancini/logger.py — Registro JSONL de trades."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from scripts.mancini.trade_manager import Trade, TradeStatus, ExitReason
from scripts.mancini.logger import append_trade, read_trades, trades_for_date


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


def test_append_and_read(tmp_path):
    path = tmp_path / "trades.jsonl"
    trade = _make_trade()
    append_trade(trade, path=path)

    trades = read_trades(path=path)
    assert len(trades) == 1
    assert trades[0]["id"] == "test-001"
    assert trades[0]["pnl_total_pts"] == 10


def test_append_multiple(tmp_path):
    path = tmp_path / "trades.jsonl"
    append_trade(_make_trade(id="t1"), path=path)
    append_trade(_make_trade(id="t2"), path=path)

    trades = read_trades(path=path)
    assert len(trades) == 2
    assert trades[0]["id"] == "t1"
    assert trades[1]["id"] == "t2"


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
    assert {t["id"] for t in filtered} == {"t1", "t3"}


def test_trades_for_date_no_match(tmp_path):
    path = tmp_path / "trades.jsonl"
    append_trade(_make_trade(entry_time="2026-04-10T14:00:00Z"), path=path)

    assert trades_for_date("2026-04-11", path=path) == []


def test_jsonl_format(tmp_path):
    """Cada trade es una línea JSON válida."""
    path = tmp_path / "trades.jsonl"
    append_trade(_make_trade(id="t1"), path=path)
    append_trade(_make_trade(id="t2"), path=path)

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    for line in lines:
        parsed = json.loads(line)
        assert "id" in parsed
