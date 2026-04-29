"""
Tests para la integración GEX ↔ Mancini.

Cubre:
  1. build_auto_levels — GEX ausente (se notifica por separado en apertura)
  2. _in_chop_zone — precio dentro/fuera, snapshot None
  3. notify_gex_open — mensaje Telegram de apertura con niveles combinados
  4. notify_approaching_level — flag chop zone en mensaje Telegram
"""

import json
import sys
import os
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.mancini.auto_levels import build_auto_levels, AutoLevels, TechnicalLevel
from scripts.mancini.monitor import _in_chop_zone


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_auto_levels(spot: float = 5200.0):
    """Llama a build_auto_levels con datos mínimos (sin GEX)."""
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
    )


def _level_labels(auto) -> list[str]:
    return [l.label for l in auto.levels]


def _make_gex_snapshot(flip=5200.0, cn=5150.0, spot=5215.0,
                        chop_low=5195.0, chop_high=5205.0,
                        es_basis=1.006) -> dict:
    return {
        "ts":              "2026-04-29T09:37:00",
        "spot":            spot,
        "es_basis":        es_basis,
        "net_gex_bn":      -1.23,
        "signal_gex":      "SHORT_GAMMA_SUAVE",
        "regime_text":     "Dealers SHORT gamma bajo 5200",
        "flip_level":      flip,
        "control_node":    cn,
        "chop_zone_low":   chop_low,
        "chop_zone_high":  chop_high,
        "put_wall":        5100.0,
        "call_wall":       5300.0,
        "gex_by_strike":   {"5200": 0.12},
        "gex_pct_by_strike": {"5200": 100.0},
        "n_strikes":       1,
        "status":          "OK",
    }


# ---------------------------------------------------------------------------
# Grupo 1: build_auto_levels — GEX ausente
# ---------------------------------------------------------------------------


def test_gex_not_in_auto_levels():
    """Los niveles GEX no aparecen en auto_levels — se notifican en apertura."""
    auto = _make_auto_levels()
    labels = _level_labels(auto)
    assert "FLIP" not in labels
    assert "PUT_WALL" not in labels
    assert "CALL_WALL" not in labels
    assert "CONTROL_NODE" not in labels


def test_no_gex_group_in_auto_levels():
    """El grupo 'gex' no existe en auto_levels."""
    auto = _make_auto_levels()
    groups = {l.group for l in auto.levels}
    assert "gex" not in groups


def test_daily_levels_still_present():
    """PDH, PDL, PDC siguen presentes en auto_levels."""
    auto = _make_auto_levels()
    labels = _level_labels(auto)
    assert "PDH" in labels
    assert "PDL" in labels
    assert "PDC" in labels


def test_round_numbers_still_present():
    """Los round numbers siguen presentes en auto_levels."""
    auto = _make_auto_levels()
    groups = {l.group for l in auto.levels}
    assert "round" in groups


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
# Grupo 3: notify_gex_open
# ---------------------------------------------------------------------------


def test_notify_gex_open_sends_message():
    """notify_gex_open llama a send_telegram con un mensaje no vacío."""
    snap = _make_gex_snapshot()
    with patch("scripts.mancini.notifier.send_telegram") as mock_send:
        mock_send.return_value = True
        from scripts.mancini import notifier
        notifier.notify_gex_open(snap)
        mock_send.assert_called_once()
        msg = mock_send.call_args[0][0]
        assert len(msg) > 0


def test_notify_gex_open_header_present():
    """El mensaje contiene 'Apertura GEX'."""
    snap = _make_gex_snapshot()
    with patch("scripts.mancini.notifier.send_telegram") as mock_send:
        mock_send.return_value = True
        from scripts.mancini import notifier
        notifier.notify_gex_open(snap)
        msg = mock_send.call_args[0][0]
        assert "Apertura GEX" in msg


def test_notify_gex_open_contains_flip():
    """El mensaje incluye el flip level."""
    snap = _make_gex_snapshot(flip=5200.0)
    with patch("scripts.mancini.notifier.send_telegram") as mock_send:
        mock_send.return_value = True
        from scripts.mancini import notifier
        notifier.notify_gex_open(snap)
        msg = mock_send.call_args[0][0]
        assert "5200" in msg
        assert "FLIP" in msg


def test_notify_gex_open_contains_put_call_wall():
    """El mensaje incluye put wall y call wall."""
    snap = _make_gex_snapshot()
    with patch("scripts.mancini.notifier.send_telegram") as mock_send:
        mock_send.return_value = True
        from scripts.mancini import notifier
        notifier.notify_gex_open(snap)
        msg = mock_send.call_args[0][0]
        assert "PUT WALL" in msg
        assert "CALL WALL" in msg


def test_notify_gex_open_contains_control_node_when_present():
    """El mensaje incluye CN cuando control_node no es None."""
    snap = _make_gex_snapshot(cn=5150.0)
    with patch("scripts.mancini.notifier.send_telegram") as mock_send:
        mock_send.return_value = True
        from scripts.mancini import notifier
        notifier.notify_gex_open(snap)
        msg = mock_send.call_args[0][0]
        assert "CN" in msg
        assert "5150" in msg


def test_notify_gex_open_no_cn_when_none():
    """El mensaje no incluye CN cuando control_node es None."""
    snap = _make_gex_snapshot(cn=None)
    with patch("scripts.mancini.notifier.send_telegram") as mock_send:
        mock_send.return_value = True
        from scripts.mancini import notifier
        notifier.notify_gex_open(snap)
        msg = mock_send.call_args[0][0]
        assert "CN" not in msg


def test_notify_gex_open_shows_es_equivalent():
    """Con es_basis, el mensaje muestra el equivalente /ES."""
    snap = _make_gex_snapshot(spot=5215.0, es_basis=1.006)
    with patch("scripts.mancini.notifier.send_telegram") as mock_send:
        mock_send.return_value = True
        from scripts.mancini import notifier
        notifier.notify_gex_open(snap)
        msg = mock_send.call_args[0][0]
        assert "ES" in msg


def test_notify_gex_open_with_auto_levels():
    """Con auto_levels, el mensaje incluye niveles técnicos (PDH, PDC, etc.)."""
    snap = _make_gex_snapshot()
    auto = _make_auto_levels(5215.0)
    with patch("scripts.mancini.notifier.send_telegram") as mock_send:
        mock_send.return_value = True
        from scripts.mancini import notifier
        notifier.notify_gex_open(snap, auto_levels=auto)
        msg = mock_send.call_args[0][0]
        assert "PDH" in msg or "PDC" in msg or "PDL" in msg


def test_notify_gex_open_without_auto_levels_no_crash():
    """Sin auto_levels no lanza excepción y envía mensaje."""
    snap = _make_gex_snapshot()
    with patch("scripts.mancini.notifier.send_telegram") as mock_send:
        mock_send.return_value = True
        from scripts.mancini import notifier
        result = notifier.notify_gex_open(snap, auto_levels=None)
        assert mock_send.called


def test_notify_gex_open_chop_zone_shown():
    """La chop zone aparece en el mensaje cuando está presente en el snapshot."""
    snap = _make_gex_snapshot(chop_low=5195.0, chop_high=5205.0)
    with patch("scripts.mancini.notifier.send_telegram") as mock_send:
        mock_send.return_value = True
        from scripts.mancini import notifier
        notifier.notify_gex_open(snap)
        msg = mock_send.call_args[0][0]
        assert "CHOP" in msg
        assert "5195" in msg
        assert "5205" in msg


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
