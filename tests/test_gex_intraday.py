"""
Tests para el módulo gex_intraday.py.

Cubre:
  1. save_snapshot / load_snapshots
  2. detect_shift — umbrales y tipos
  3. _error_snapshot — estructura correcta
"""

import json
import sys
import os
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.gex_intraday import (
    save_snapshot,
    load_snapshots,
    detect_shift,
    _error_snapshot,
    SNAPSHOT_PATH_TPL,
    GEX_SHIFT_ALERT_PTS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_snapshot(flip=5200.0, cn=5150.0, spot=5195.0, status="OK",
                   es_basis=1.0058) -> dict:
    return {
        "ts":                "2026-04-29T10:00:00",
        "ts_et":             "2026-04-29T10:00:00-04:00",
        "spot":              spot,
        "es_basis":          es_basis,
        "net_gex_bn":        -1.23,
        "signal_gex":        "SHORT_GAMMA_SUAVE",
        "regime_text":       "Dealers SHORT gamma bajo 5200",
        "flip_level":        flip,
        "control_node":      cn,
        "chop_zone_low":     5195.0,
        "chop_zone_high":    5200.0,
        "put_wall":          5100.0,
        "call_wall":         5300.0,
        "gex_by_strike":     {"5150": -0.87, "5200": 0.12},
        "gex_pct_by_strike": {"5150": -87.0, "5200": 12.0},
        "n_strikes":         2,
        "status":            status,
    }


# ---------------------------------------------------------------------------
# Grupo 1: save_snapshot / load_snapshots
# ---------------------------------------------------------------------------


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    """Guardar un snapshot y cargarlo devuelve el mismo contenido."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "outputs").mkdir()

    snap = _make_snapshot()
    save_snapshot(snap, date_str="2026-04-29")

    loaded = load_snapshots(date_str="2026-04-29")
    assert len(loaded) == 1
    assert loaded[0]["flip_level"] == snap["flip_level"]
    assert loaded[0]["net_gex_bn"] == snap["net_gex_bn"]
    assert loaded[0]["status"] == "OK"


def test_multiple_snapshots_appended(tmp_path, monkeypatch):
    """Varios snapshots se acumulan en el mismo fichero."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "outputs").mkdir()

    for i in range(3):
        snap = _make_snapshot(flip=5200.0 + i * 5)
        save_snapshot(snap, date_str="2026-04-29")

    loaded = load_snapshots(date_str="2026-04-29")
    assert len(loaded) == 3
    assert loaded[2]["flip_level"] == 5210.0


def test_load_snapshots_empty_when_no_file(tmp_path, monkeypatch):
    """Sin fichero JSONL → lista vacía."""
    monkeypatch.chdir(tmp_path)
    loaded = load_snapshots(date_str="2026-04-29")
    assert loaded == []


def test_load_snapshots_ignores_malformed_lines(tmp_path, monkeypatch):
    """Línea malformada en el JSONL se ignora silenciosamente."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "outputs").mkdir()

    path = tmp_path / "outputs" / "gex_snapshots_2026-04-29.jsonl"
    path.write_text(
        json.dumps(_make_snapshot()) + "\n"
        + "ESTO NO ES JSON\n"
        + json.dumps(_make_snapshot(flip=5190.0)) + "\n",
        encoding="utf-8",
    )

    loaded = load_snapshots(date_str="2026-04-29")
    assert len(loaded) == 2
    assert loaded[1]["flip_level"] == 5190.0


def test_load_snapshots_unicode_preserved(tmp_path, monkeypatch):
    """Caracteres unicode en regime_text se preservan."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "outputs").mkdir()

    snap = _make_snapshot()
    snap["regime_text"] = "Dealers SHORT gamma — caídas se aceleran"
    save_snapshot(snap, date_str="2026-04-29")

    loaded = load_snapshots(date_str="2026-04-29")
    assert "caídas" in loaded[0]["regime_text"]


# ---------------------------------------------------------------------------
# Grupo 2: detect_shift
# ---------------------------------------------------------------------------


def test_detect_shift_flip_above_threshold():
    """Flip cae más de GEX_SHIFT_ALERT_PTS → FLIP_SHIFT."""
    prev = _make_snapshot(flip=5200.0, cn=5150.0)
    curr = _make_snapshot(flip=5185.0, cn=5150.0)

    shift = detect_shift(prev, curr)
    assert shift is not None
    assert shift["type"] == "FLIP_SHIFT"
    assert shift["flip_prev"] == 5200.0
    assert shift["flip_curr"] == 5185.0


def test_detect_shift_below_threshold_returns_none():
    """Flip sube solo 5 pts (< umbral) → sin shift."""
    prev = _make_snapshot(flip=5200.0, cn=5150.0)
    curr = _make_snapshot(flip=5205.0, cn=5150.0)

    assert detect_shift(prev, curr) is None


def test_detect_shift_exactly_at_threshold():
    """Desplazamiento exactamente igual al umbral → se alerta."""
    prev = _make_snapshot(flip=5200.0, cn=5150.0)
    curr = _make_snapshot(flip=5200.0 - GEX_SHIFT_ALERT_PTS, cn=5150.0)

    shift = detect_shift(prev, curr)
    assert shift is not None
    assert shift["type"] == "FLIP_SHIFT"


def test_detect_shift_control_node_above_threshold():
    """Control Node se desplaza > umbral → CONTROL_NODE_SHIFT."""
    prev = _make_snapshot(flip=5200.0, cn=5150.0)
    curr = _make_snapshot(flip=5200.0, cn=5130.0)

    shift = detect_shift(prev, curr)
    assert shift is not None
    assert shift["type"] == "CONTROL_NODE_SHIFT"


def test_detect_shift_both():
    """Flip y CN se desplazan → BOTH."""
    prev = _make_snapshot(flip=5200.0, cn=5150.0)
    curr = _make_snapshot(flip=5185.0, cn=5130.0)

    shift = detect_shift(prev, curr)
    assert shift is not None
    assert shift["type"] == "BOTH"


def test_detect_shift_regime_change_cn_none_to_float():
    """Control Node pasa de None (long gamma) a valor (short gamma) → shift."""
    prev = _make_snapshot(flip=5200.0, cn=None)
    curr = _make_snapshot(flip=5200.0, cn=5150.0)

    shift = detect_shift(prev, curr)
    assert shift is not None
    assert shift["type"] == "CONTROL_NODE_SHIFT"
    assert shift["cn_prev"] is None
    assert shift["cn_curr"] == 5150.0


def test_detect_shift_regime_change_cn_float_to_none():
    """Control Node desaparece (régimen cambia a long gamma) → shift."""
    prev = _make_snapshot(flip=5200.0, cn=5150.0)
    curr = _make_snapshot(flip=5200.0, cn=None)

    shift = detect_shift(prev, curr)
    assert shift is not None


def test_detect_shift_first_snapshot_returns_none():
    """Sin snapshot previo (primer poll) → sin shift."""
    curr = _make_snapshot()
    assert detect_shift(None, curr) is None


def test_detect_shift_no_change_returns_none():
    """Mismos niveles en ambos snapshots → sin shift."""
    snap = _make_snapshot(flip=5200.0, cn=5150.0)
    assert detect_shift(snap, snap) is None


# ---------------------------------------------------------------------------
# Grupo 3: _error_snapshot
# ---------------------------------------------------------------------------


def test_error_snapshot_has_required_keys():
    """El snapshot de error contiene todos los campos requeridos."""
    err = _error_snapshot(5200.0, "ERROR")
    required = [
        "ts", "ts_et", "spot", "es_basis", "net_gex_bn", "signal_gex", "regime_text",
        "flip_level", "control_node", "chop_zone_low", "chop_zone_high",
        "put_wall", "call_wall", "gex_by_strike", "gex_pct_by_strike",
        "n_strikes", "status",
    ]
    for key in required:
        assert key in err, f"Campo '{key}' ausente en snapshot de error"


def test_error_snapshot_status_propagated():
    """El status del error se propaga correctamente."""
    err = _error_snapshot(None, "MISSING_DATA")
    assert err["status"] == "MISSING_DATA"
    assert err["spot"] is None
    assert err["gex_by_strike"] == {}


def test_error_snapshot_es_basis_computed():
    """Con spot y es_price, el snapshot de error calcula es_basis."""
    err = _error_snapshot(5200.0, "ERROR", es_price=5229.0)
    assert err["es_basis"] is not None
    assert abs(err["es_basis"] - round(5229.0 / 5200.0, 6)) < 1e-6


def test_error_snapshot_es_basis_none_without_es_price():
    """Sin es_price, es_basis es None."""
    err = _error_snapshot(5200.0, "ERROR")
    assert err["es_basis"] is None


def test_error_snapshot_es_basis_none_without_spot():
    """Sin spot, es_basis es None aunque haya es_price."""
    err = _error_snapshot(None, "MISSING_DATA", es_price=5229.0)
    assert err["es_basis"] is None


# ---------------------------------------------------------------------------
# Grupo 4: detect_shift — propagación de es_basis
# ---------------------------------------------------------------------------


def test_detect_shift_propagates_es_basis():
    """detect_shift incluye es_basis del snapshot actual."""
    prev = _make_snapshot(flip=5200.0, cn=5150.0, es_basis=1.005)
    curr = _make_snapshot(flip=5185.0, cn=5150.0, es_basis=1.006)

    shift = detect_shift(prev, curr)
    assert shift is not None
    assert shift["es_basis"] == 1.006


def test_detect_shift_es_basis_none_when_missing():
    """Si el snapshot actual no tiene es_basis, detect_shift devuelve None para ese campo."""
    prev = _make_snapshot(flip=5200.0, cn=5150.0)
    curr = _make_snapshot(flip=5185.0, cn=5150.0)
    curr.pop("es_basis", None)

    shift = detect_shift(prev, curr)
    assert shift is not None
    assert shift.get("es_basis") is None
