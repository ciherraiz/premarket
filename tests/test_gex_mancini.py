"""
Tests para la integración GEX ↔ Mancini (paso 3).

Cubre:
  1. build_auto_levels — control_node incluido/excluido según valor
  2. _in_chop_zone — precio dentro/fuera, snapshot None
  3. _load_gex_levels — preferencia snapshot intraday > indicators.json
  4. notify_approaching_level — flag chop zone en mensaje Telegram
"""

import json
import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.mancini.auto_levels import build_auto_levels, _load_gex_levels
from scripts.mancini.monitor import _in_chop_zone


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_gex(flip=5200.0, put_wall=5100.0, call_wall=5300.0, cn=None) -> dict:
    return {
        "flip_level":   flip,
        "put_wall":     put_wall,
        "call_wall":    call_wall,
        "control_node": cn,
    }


def _make_auto_levels(gex_levels: dict, spot: float = 5200.0):
    """Llama a build_auto_levels con datos mínimos."""
    import pandas as pd
    daily_ohlcv = [
        {"High": 5300, "Low": 5100, "Close": 5200},
        {"High": 5310, "Low": 5110, "Close": 5210},
    ]
    return build_auto_levels(
        daily_ohlcv=daily_ohlcv,
        weekly_df=None,
        monthly_df=None,
        es_spot=spot,
        gex_levels=gex_levels,
    )


def _level_labels(auto) -> list[str]:
    return [l.label for l in auto.levels]


# ---------------------------------------------------------------------------
# Grupo 1: build_auto_levels — control_node
# ---------------------------------------------------------------------------


def test_control_node_added_when_present():
    """control_node con valor → aparece CONTROL_NODE en los niveles."""
    auto = _make_auto_levels(_base_gex(cn=5150.0))
    assert "CONTROL_NODE" in _level_labels(auto)
    cn_level = next(l for l in auto.levels if l.label == "CONTROL_NODE")
    assert cn_level.value == 5150.0
    assert cn_level.group == "gex"
    assert cn_level.priority == 1


def test_control_node_excluded_when_none():
    """control_node = None (régimen long gamma) → no hay CONTROL_NODE en niveles."""
    auto = _make_auto_levels(_base_gex(cn=None))
    assert "CONTROL_NODE" not in _level_labels(auto)


def test_control_node_excluded_when_missing_from_dict():
    """control_node ausente del dict → no hay CONTROL_NODE en niveles."""
    gex = {"flip_level": 5200.0, "put_wall": 5100.0, "call_wall": 5300.0}
    auto = _make_auto_levels(gex)
    assert "CONTROL_NODE" not in _level_labels(auto)


def test_flip_put_call_wall_still_present_with_cn():
    """Al añadir control_node, los demás niveles GEX siguen presentes."""
    auto = _make_auto_levels(_base_gex(cn=5150.0))
    labels = _level_labels(auto)
    assert "FLIP" in labels
    assert "PUT_WALL" in labels
    assert "CALL_WALL" in labels


# ---------------------------------------------------------------------------
# Grupo 2: _in_chop_zone
# ---------------------------------------------------------------------------


def test_in_chop_zone_price_inside():
    snap = {"chop_zone_low": 5195.0, "chop_zone_high": 5205.0}
    assert _in_chop_zone(5200.0, snap) is True


def test_in_chop_zone_price_at_low_boundary():
    snap = {"chop_zone_low": 5195.0, "chop_zone_high": 5205.0}
    assert _in_chop_zone(5195.0, snap) is True


def test_in_chop_zone_price_at_high_boundary():
    snap = {"chop_zone_low": 5195.0, "chop_zone_high": 5205.0}
    assert _in_chop_zone(5205.0, snap) is True


def test_in_chop_zone_price_above():
    snap = {"chop_zone_low": 5195.0, "chop_zone_high": 5205.0}
    assert _in_chop_zone(5210.0, snap) is False


def test_in_chop_zone_price_below():
    snap = {"chop_zone_low": 5195.0, "chop_zone_high": 5205.0}
    assert _in_chop_zone(5190.0, snap) is False


def test_in_chop_zone_none_snapshot():
    assert _in_chop_zone(5200.0, None) is False


def test_in_chop_zone_missing_low():
    snap = {"chop_zone_high": 5205.0}
    assert _in_chop_zone(5200.0, snap) is False


def test_in_chop_zone_missing_high():
    snap = {"chop_zone_low": 5195.0}
    assert _in_chop_zone(5200.0, snap) is False


def test_in_chop_zone_both_none():
    snap = {"chop_zone_low": None, "chop_zone_high": None}
    assert _in_chop_zone(5200.0, snap) is False


# ---------------------------------------------------------------------------
# Grupo 3: _load_gex_levels
# ---------------------------------------------------------------------------


def test_load_gex_levels_prefers_intraday_snapshot(tmp_path, monkeypatch):
    """Si hay snapshot OK del día, se usa en lugar de indicators.json."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "outputs").mkdir()

    snapshot = {
        "flip_level": 5185.0, "put_wall": 5050.0, "call_wall": 5350.0,
        "control_node": 5140.0, "status": "OK",
    }
    snap_path = tmp_path / "outputs" / f"gex_snapshots_{__import__('datetime').date.today().isoformat()}.jsonl"
    snap_path.write_text(json.dumps(snapshot) + "\n", encoding="utf-8")

    result = _load_gex_levels()
    assert result["flip_level"]   == 5185.0
    assert result["control_node"] == 5140.0
    assert result["put_wall"]     == 5050.0


def test_load_gex_levels_skips_error_snapshot(tmp_path, monkeypatch):
    """Snapshot con status != OK no se usa — fallback a indicators.json."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "outputs").mkdir()

    bad_snap = {"flip_level": 5185.0, "status": "ERROR", "control_node": None}
    snap_path = tmp_path / "outputs" / f"gex_snapshots_{__import__('datetime').date.today().isoformat()}.jsonl"
    snap_path.write_text(json.dumps(bad_snap) + "\n", encoding="utf-8")

    indicators = {"premarket": {"net_gex": {"flip_level": 5200.0, "put_wall": 5100.0,
                                             "call_wall": 5300.0, "control_node": 5150.0}}}
    (tmp_path / "outputs" / "indicators.json").write_text(
        json.dumps(indicators), encoding="utf-8"
    )

    result = _load_gex_levels()
    assert result["flip_level"] == 5200.0
    assert result["control_node"] == 5150.0


def test_load_gex_levels_fallback_to_indicators(tmp_path, monkeypatch):
    """Sin snapshots del día, lee indicators.json."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "outputs").mkdir()

    indicators = {"premarket": {"net_gex": {"flip_level": 5200.0, "put_wall": 5100.0,
                                             "call_wall": 5300.0, "control_node": None}}}
    (tmp_path / "outputs" / "indicators.json").write_text(
        json.dumps(indicators), encoding="utf-8"
    )

    result = _load_gex_levels()
    assert result["flip_level"] == 5200.0
    assert result["control_node"] is None


def test_load_gex_levels_empty_when_no_files(tmp_path, monkeypatch):
    """Sin snapshots ni indicators.json → dict vacío."""
    monkeypatch.chdir(tmp_path)
    result = _load_gex_levels()
    assert result == {}


# ---------------------------------------------------------------------------
# Grupo 4: notify_approaching_level — chop zone flag
# ---------------------------------------------------------------------------


def test_notify_approaching_level_no_chop_zone():
    """Sin snapshot → mensaje sin flag de chop zone."""
    with patch("scripts.mancini.notifier.send_telegram") as mock_send:
        mock_send.return_value = True
        from scripts.mancini import notifier
        notifier.notify_approaching_level(5200.0, 5212.0, 12.0, gex_snapshot=None)
        msg = mock_send.call_args[0][0]
        assert "Chop" not in msg


def test_notify_approaching_level_price_in_chop_zone():
    """Precio dentro de chop zone → mensaje incluye flag 🔀."""
    snap = {"chop_zone_low": 5195.0, "chop_zone_high": 5210.0}
    with patch("scripts.mancini.notifier.send_telegram") as mock_send:
        mock_send.return_value = True
        from scripts.mancini import notifier
        notifier.notify_approaching_level(5200.0, 5202.0, 2.0, gex_snapshot=snap)
        msg = mock_send.call_args[0][0]
        assert "🔀" in msg
        assert "5195" in msg
        assert "5210" in msg


def test_notify_approaching_level_price_outside_chop_zone():
    """Precio fuera de chop zone → mensaje sin flag."""
    snap = {"chop_zone_low": 5195.0, "chop_zone_high": 5205.0}
    with patch("scripts.mancini.notifier.send_telegram") as mock_send:
        mock_send.return_value = True
        from scripts.mancini import notifier
        notifier.notify_approaching_level(5200.0, 5215.0, 15.0, gex_snapshot=snap)
        msg = mock_send.call_args[0][0]
        assert "🔀" not in msg
