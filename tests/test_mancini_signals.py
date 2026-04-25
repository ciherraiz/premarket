"""Tests para signal_tracker.py y el logging de señales Failed Breakdown."""

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from scripts.mancini.signal_tracker import FailedBreakdownSignal
from scripts.mancini.logger import append_signal, read_signals


def _make_signal(**kwargs) -> FailedBreakdownSignal:
    defaults = dict(
        signal_id="sig-001",
        detected_at="2026-04-24T14:40:00+00:00",
        level=7161.0,
        direction="LONG",
        breakdown_depth_pts=9.88,
        acceptance_pauses=0,
        acceptance_max_above_level=2.38,
        recovery_velocity_pts_min=1.16,
        time_quality="prime",
        alignment="ALIGNED",
        d_score=3,
        v_score=2,
        t1_price=7186.0,
        stop_price=7148.0,
    )
    defaults.update(kwargs)
    return FailedBreakdownSignal(**defaults)


# ── FailedBreakdownSignal ────────────────────────────────────────────

def test_initial_status():
    s = _make_signal()
    assert s.status == "detected"
    assert s.confirmed_at is None
    assert s.invalidated_at is None
    assert s.minutes_to_resolution is None


def test_confirm():
    s = _make_signal()
    ts = "2026-04-24T14:58:00+00:00"
    s.confirm(ts)
    assert s.status == "confirmed"
    assert s.confirmed_at == ts
    assert s.minutes_to_resolution == 18.0


def test_invalidate():
    s = _make_signal()
    ts = "2026-04-24T14:50:00+00:00"
    s.invalidate(ts)
    assert s.status == "invalidated"
    assert s.invalidated_at == ts
    assert s.minutes_to_resolution == 10.0


def test_expire():
    s = _make_signal()
    ts = "2026-04-24T21:00:00+00:00"
    s.expire(ts)
    assert s.status == "expired"


def test_to_dict_keys():
    s = _make_signal()
    d = s.to_dict()
    expected_keys = {
        "signal_id", "detected_at", "level", "direction",
        "breakdown_depth_pts", "acceptance_pauses",
        "acceptance_max_above_level", "recovery_velocity_pts_min",
        "time_quality", "alignment", "d_score", "v_score",
        "status", "t1_price", "stop_price",
        "confirmed_at", "invalidated_at", "minutes_to_resolution",
        "trade_id", "gate_execute", "gate_reasoning",
    }
    assert expected_keys == set(d.keys())


def test_to_dict_values():
    s = _make_signal()
    s.confirm("2026-04-24T14:58:00+00:00")
    d = s.to_dict()
    assert d["level"] == 7161.0
    assert d["d_score"] == 3
    assert d["status"] == "confirmed"
    assert d["minutes_to_resolution"] == 18.0


# ── logger append_signal / read_signals ─────────────────────────────

def test_append_and_read(tmp_path):
    path = tmp_path / "signals.jsonl"
    s = _make_signal()
    s.confirm("2026-04-24T14:58:00+00:00")
    append_signal(s, path=path)

    signals = read_signals(path=path)
    assert len(signals) == 1
    assert signals[0]["signal_id"] == "sig-001"
    assert signals[0]["status"] == "confirmed"


def test_append_multiple(tmp_path):
    path = tmp_path / "signals.jsonl"
    s1 = _make_signal(signal_id="s1")
    s2 = _make_signal(signal_id="s2")
    s1.confirm("2026-04-24T14:58:00+00:00")
    s2.invalidate("2026-04-24T14:52:00+00:00")
    append_signal(s1, path=path)
    append_signal(s2, path=path)

    signals = read_signals(path=path)
    assert len(signals) == 2
    assert signals[0]["signal_id"] == "s1"
    assert signals[1]["signal_id"] == "s2"


def test_read_empty(tmp_path):
    path = tmp_path / "signals.jsonl"
    assert read_signals(path=path) == []


def test_creates_parent_dirs(tmp_path):
    path = tmp_path / "sub" / "signals.jsonl"
    append_signal(_make_signal(), path=path)
    assert path.exists()


def test_jsonl_format(tmp_path):
    path = tmp_path / "signals.jsonl"
    append_signal(_make_signal(signal_id="s1"), path=path)
    append_signal(_make_signal(signal_id="s2"), path=path)

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    for line in lines:
        parsed = json.loads(line)
        assert "signal_id" in parsed
        assert "status" in parsed
