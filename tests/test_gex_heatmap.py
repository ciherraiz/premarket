"""
Tests para scripts/gex_heatmap.py.

Cubre lógica de datos y rendering básico (sin envío real a Telegram).
"""
from __future__ import annotations

import json
import sys
import os
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.gex_heatmap import print_gex_terminal, build_gex_heatmap, _load_source


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_snapshot(flip=5200.0, cn=5150.0, spot=5215.0,
                   chop_low=5195.0, chop_high=5205.0,
                   ts="2026-04-29T14:32:00") -> dict:
    strikes = [5100, 5150, 5175, 5195, 5200, 5205, 5215, 5225, 5300]
    gex_bn   = {str(s): round((s - 5200) * 0.001, 4) for s in strikes}
    max_abs  = max(abs(v) for v in gex_bn.values()) or 1
    gex_pct  = {k: round(v / max_abs * 100, 1) for k, v in gex_bn.items()}
    return {
        "ts":                ts,
        "ts_et":             ts + "-04:00",
        "spot":              spot,
        "net_gex_bn":        -1.23,
        "signal_gex":        "SHORT_GAMMA_SUAVE",
        "regime_text":       "Dealers SHORT gamma bajo 5200 — rebotes débiles",
        "flip_level":        flip,
        "control_node":      cn,
        "chop_zone_low":     chop_low,
        "chop_zone_high":    chop_high,
        "put_wall":          5100.0,
        "call_wall":         5300.0,
        "gex_by_strike":     gex_bn,
        "gex_pct_by_strike": gex_pct,
        "n_strikes":         len(strikes),
        "status":            "OK",
    }


def _make_snapshots(n: int = 3) -> list[dict]:
    times = [f"2026-04-29T{9 + i // 6:02d}:{(i % 6) * 10:02d}:00" for i in range(n)]
    return [_make_snapshot(ts=t) for t in times]


# ---------------------------------------------------------------------------
# Grupo 1: print_gex_terminal
# ---------------------------------------------------------------------------


def test_print_gex_terminal_no_crash(capsys):
    """print_gex_terminal no lanza excepción con snapshot válido."""
    snap = _make_snapshot()
    print_gex_terminal(snap)
    out = capsys.readouterr().out
    assert "GEX 0DTE" in out


def test_print_gex_terminal_shows_signal(capsys):
    snap = _make_snapshot()
    print_gex_terminal(snap)
    out = capsys.readouterr().out
    assert "SHORT_GAMMA_SUAVE" in out


def test_print_gex_terminal_shows_chop_zone(capsys):
    """La línea CHOP ZONE aparece cuando chop_zone_low y chop_zone_high están presentes."""
    snap = _make_snapshot(chop_low=5195.0, chop_high=5205.0)
    print_gex_terminal(snap)
    out = capsys.readouterr().out
    assert "CHOP ZONE" in out
    assert "5195" in out
    assert "5205" in out


def test_print_gex_terminal_no_chop_zone_when_none(capsys):
    """Sin chop zone no aparece la línea separadora."""
    snap = _make_snapshot(chop_low=None, chop_high=None)
    print_gex_terminal(snap)
    out = capsys.readouterr().out
    assert "CHOP ZONE" not in out


def test_print_gex_terminal_strike_markers(capsys):
    """▶ aparece una sola vez (strike más cercano al spot)."""
    snap = _make_snapshot(spot=5215.0)
    print_gex_terminal(snap)
    out = capsys.readouterr().out
    assert "▶" in out


def test_print_gex_terminal_control_node_marker(capsys):
    """● aparece cuando control_node tiene valor."""
    snap = _make_snapshot(cn=5150.0)
    print_gex_terminal(snap)
    out = capsys.readouterr().out
    assert "●" in out


def test_print_gex_terminal_no_control_node_marker(capsys):
    """● NO aparece cuando control_node es None."""
    snap = _make_snapshot(cn=None)
    print_gex_terminal(snap)
    out = capsys.readouterr().out
    assert "●" not in out


def test_print_gex_terminal_empty_gex_no_crash(capsys):
    """Snapshot sin strikes no lanza excepción."""
    snap = _make_snapshot()
    snap["gex_by_strike"] = {}
    snap["gex_pct_by_strike"] = {}
    print_gex_terminal(snap)  # no debe lanzar


# ---------------------------------------------------------------------------
# Grupo 2: build_gex_heatmap
# ---------------------------------------------------------------------------


def test_build_heatmap_single_snapshot_returns_png():
    """Un snapshot → gráfico de barras → bytes PNG válido."""
    snap = _make_snapshot()
    img = build_gex_heatmap([snap])
    assert isinstance(img, bytes)
    assert img[:4] == b"\x89PNG"


def test_build_heatmap_multiple_snapshots_returns_png():
    """Múltiples snapshots → heatmap temporal → bytes PNG válido."""
    snaps = _make_snapshots(5)
    img = build_gex_heatmap(snaps)
    assert isinstance(img, bytes)
    assert img[:4] == b"\x89PNG"


def test_build_heatmap_two_snapshots_returns_png():
    """Exactamente dos snapshots también genera PNG correcto."""
    img = build_gex_heatmap(_make_snapshots(2))
    assert img[:4] == b"\x89PNG"


def test_build_heatmap_raises_on_empty():
    """Sin snapshots → ValueError."""
    with pytest.raises(ValueError):
        build_gex_heatmap([])


def test_build_heatmap_snapshot_none_control_node():
    """control_node = None no rompe el heatmap."""
    snap = _make_snapshot(cn=None)
    img = build_gex_heatmap([snap])
    assert img[:4] == b"\x89PNG"


def test_build_heatmap_snapshot_none_chop_zone():
    """chop_zone = None no rompe el heatmap."""
    snap = _make_snapshot(chop_low=None, chop_high=None)
    img = build_gex_heatmap([snap])
    assert img[:4] == b"\x89PNG"


# ---------------------------------------------------------------------------
# Grupo 3: _load_source
# ---------------------------------------------------------------------------


def test_load_source_prefers_intraday_snapshot(tmp_path, monkeypatch):
    """Si hay JSONL con snapshots OK, _load_source los retorna."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "outputs").mkdir()

    snap = _make_snapshot()
    today = date.today().isoformat()
    path = tmp_path / "outputs" / f"gex_snapshots_{today}.jsonl"
    path.write_text(json.dumps(snap) + "\n", encoding="utf-8")

    snaps, source = _load_source(None)
    assert len(snaps) == 1
    assert "intraday" in source


def test_load_source_filters_error_snapshots(tmp_path, monkeypatch):
    """Snapshots con status != OK se filtran; solo se retornan los OK."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "outputs").mkdir()

    bad  = _make_snapshot(); bad["status"] = "ERROR"
    good = _make_snapshot(spot=5220.0)
    today = date.today().isoformat()
    path = tmp_path / "outputs" / f"gex_snapshots_{today}.jsonl"
    path.write_text(
        json.dumps(bad) + "\n" + json.dumps(good) + "\n",
        encoding="utf-8",
    )

    snaps, _ = _load_source(None)
    assert len(snaps) == 1
    assert snaps[0]["spot"] == 5220.0


def test_load_source_fallback_to_indicators(tmp_path, monkeypatch):
    """Sin JSONL → lee indicators.json y construye un snapshot único."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "outputs").mkdir()

    ind = {
        "premarket": {
            "spx_spot": 5215.0,
            "net_gex": {
                "net_gex_bn": -1.23,
                "signal_gex": "SHORT_GAMMA_SUAVE",
                "regime_text": "Test regime",
                "flip_level": 5200.0,
                "control_node": 5150.0,
                "chop_zone_low": 5195.0,
                "chop_zone_high": 5205.0,
                "put_wall": 5100.0,
                "call_wall": 5300.0,
                "gex_by_strike": {"5100": -1.23, "5200": 0.12},
                "gex_pct_by_strike": {"5100": -100.0, "5200": 9.8},
                "n_strikes": 2,
                "status": "OK",
            },
        }
    }
    (tmp_path / "outputs" / "indicators.json").write_text(
        json.dumps(ind), encoding="utf-8"
    )

    snaps, source = _load_source(None)
    assert len(snaps) == 1
    assert snaps[0]["flip_level"] == 5200.0
    assert "indicators" in source


def test_load_source_empty_when_no_files(tmp_path, monkeypatch):
    """Sin JSONL ni indicators.json → lista vacía."""
    monkeypatch.chdir(tmp_path)
    snaps, source = _load_source(None)
    assert snaps == []
    assert source == "ninguna"


def test_load_source_specific_date(tmp_path, monkeypatch):
    """--date selecciona el fichero JSONL correcto."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "outputs").mkdir()

    snap = _make_snapshot()
    path = tmp_path / "outputs" / "gex_snapshots_2026-04-28.jsonl"
    path.write_text(json.dumps(snap) + "\n", encoding="utf-8")

    snaps, source = _load_source("2026-04-28")
    assert len(snaps) == 1
    assert "2026-04-28" in source
