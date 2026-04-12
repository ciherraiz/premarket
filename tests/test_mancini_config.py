"""Tests para scripts/mancini/config.py — DailyPlan y persistencia JSON."""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from scripts.mancini.config import DailyPlan, save_plan, load_plan, save_weekly, load_weekly


# ── DailyPlan basics ────────────────────────────────────────────────

def test_daily_plan_creation():
    plan = DailyPlan(
        fecha="2026-04-10",
        key_level_upper=6809,
        targets_upper=[6819, 6830],
        key_level_lower=6781,
        targets_lower=[6766],
    )
    assert plan.fecha == "2026-04-10"
    assert plan.key_level_upper == 6809
    assert plan.targets_upper == [6819, 6830]
    assert plan.key_level_lower == 6781
    assert plan.targets_lower == [6766]
    assert plan.chop_zone is None
    assert plan.created_at  # auto-filled
    assert plan.updated_at  # auto-filled


def test_daily_plan_with_chop_zone():
    plan = DailyPlan(
        fecha="2026-04-10",
        key_level_upper=6809,
        targets_upper=[6819],
        key_level_lower=6781,
        targets_lower=[6766],
        chop_zone=(6788, 6830),
    )
    assert plan.chop_zone == (6788, 6830)


# ── merge_update ────────────────────────────────────────────────────

def test_merge_update_adds_new_targets():
    plan = DailyPlan(
        fecha="2026-04-10",
        key_level_upper=6809,
        targets_upper=[6819, 6830],
        key_level_lower=6781,
        targets_lower=[6766],
    )
    plan.merge_update(
        new_targets_upper=[6846, 6854],
        new_targets_lower=[6770],
    )
    assert plan.targets_upper == [6819, 6830, 6846, 6854]
    assert 6770 in plan.targets_lower


def test_merge_update_no_duplicates():
    plan = DailyPlan(
        fecha="2026-04-10",
        key_level_upper=6809,
        targets_upper=[6819, 6830],
        key_level_lower=6781,
        targets_lower=[6766],
    )
    plan.merge_update(new_targets_upper=[6819, 6850])
    assert plan.targets_upper.count(6819) == 1
    assert 6850 in plan.targets_upper


def test_merge_update_adds_tweet():
    plan = DailyPlan(
        fecha="2026-04-10",
        key_level_upper=6809,
        targets_upper=[6819],
        key_level_lower=6781,
        targets_lower=[6766],
        raw_tweets=["tweet 1"],
    )
    plan.merge_update(new_tweet="tweet 2")
    assert len(plan.raw_tweets) == 2
    # No duplica
    plan.merge_update(new_tweet="tweet 2")
    assert len(plan.raw_tweets) == 2


def test_merge_update_appends_notes():
    plan = DailyPlan(
        fecha="2026-04-10",
        key_level_upper=6809,
        targets_upper=[6819],
        key_level_lower=6781,
        targets_lower=[6766],
        notes="nota 1",
    )
    plan.merge_update(notes="nota 2")
    assert "nota 1" in plan.notes
    assert "nota 2" in plan.notes


def test_merge_update_updates_timestamp():
    plan = DailyPlan(
        fecha="2026-04-10",
        key_level_upper=6809,
        targets_upper=[6819],
        key_level_lower=6781,
        targets_lower=[6766],
    )
    old_updated = plan.updated_at
    plan.merge_update(new_targets_upper=[6850])
    assert plan.updated_at >= old_updated


# ── Serialización ───────────────────────────────────────────────────

def test_to_dict_and_from_dict_roundtrip():
    plan = DailyPlan(
        fecha="2026-04-10",
        key_level_upper=6809,
        targets_upper=[6819, 6830],
        key_level_lower=6781,
        targets_lower=[6766],
        chop_zone=(6788, 6830),
        raw_tweets=["Plan today: ..."],
        notes="test",
    )
    d = plan.to_dict()
    restored = DailyPlan.from_dict(d)
    assert restored.fecha == plan.fecha
    assert restored.key_level_upper == plan.key_level_upper
    assert restored.targets_upper == plan.targets_upper
    assert restored.key_level_lower == plan.key_level_lower
    assert restored.targets_lower == plan.targets_lower
    assert restored.chop_zone == plan.chop_zone
    assert restored.raw_tweets == plan.raw_tweets
    assert restored.notes == plan.notes


def test_to_dict_chop_zone_none():
    plan = DailyPlan(
        fecha="2026-04-10",
        key_level_upper=6809,
        targets_upper=[6819],
        key_level_lower=6781,
        targets_lower=[6766],
    )
    d = plan.to_dict()
    assert d["chop_zone"] is None
    restored = DailyPlan.from_dict(d)
    assert restored.chop_zone is None


# ── Persistencia JSON ───────────────────────────────────────────────

def test_save_and_load_plan(tmp_path):
    path = tmp_path / "mancini_plan.json"
    plan = DailyPlan(
        fecha="2026-04-10",
        key_level_upper=6809,
        targets_upper=[6819, 6830],
        key_level_lower=6781,
        targets_lower=[6766],
        chop_zone=(6788, 6830),
    )
    save_plan(plan, path=path)
    assert path.exists()

    loaded = load_plan(path=path)
    assert loaded is not None
    assert loaded.fecha == "2026-04-10"
    assert loaded.key_level_upper == 6809
    assert loaded.chop_zone == (6788, 6830)


def test_load_plan_nonexistent(tmp_path):
    path = tmp_path / "nonexistent.json"
    assert load_plan(path=path) is None


def test_save_plan_creates_parent_dirs(tmp_path):
    path = tmp_path / "subdir" / "deep" / "plan.json"
    plan = DailyPlan(
        fecha="2026-04-10",
        key_level_upper=6809,
        targets_upper=[6819],
        key_level_lower=6781,
        targets_lower=[6766],
    )
    save_plan(plan, path=path)
    assert path.exists()


# ── Weekly plan ────────────────────────────────────────────────────────

def test_save_and_load_weekly(tmp_path):
    path = tmp_path / "weekly.json"
    plan = DailyPlan(
        fecha="2026-04-14",  # lunes de la semana
        key_level_upper=6817,
        targets_upper=[6903, 6950, 7068],
        key_level_lower=6793,
        targets_lower=[],
        notes="Sesgo: alcista mientras aguante 6793",
    )
    save_weekly(plan, path=path)
    assert path.exists()

    loaded = load_weekly(path=path)
    assert loaded is not None
    assert loaded.fecha == "2026-04-14"
    assert loaded.key_level_upper == 6817
    assert loaded.key_level_lower == 6793
    assert loaded.targets_upper == [6903, 6950, 7068]
    assert loaded.notes == "Sesgo: alcista mientras aguante 6793"


def test_load_weekly_nonexistent(tmp_path):
    path = tmp_path / "nope.json"
    assert load_weekly(path=path) is None
