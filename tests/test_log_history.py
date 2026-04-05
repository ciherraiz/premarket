"""Tests unitarios para scripts/log_history.py."""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.log_history import append_record, fill_outcomes


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_path_jsonl(tmp_path):
    return tmp_path / "history.jsonl"


def _pre_record(fecha="2026-04-02", spot=6500.0, outcome_close=None):
    return {
        "fecha": fecha, "phase": "premarket", "timestamp": "2026-04-02T13:10:00Z",
        "spot": spot, "d_score": -1, "v_score": 1,
        "outcome_spx_close": outcome_close,
        "outcome_spx_change_pct": None,
        "outcome_direction": None,
    }


def _open_record(fecha="2026-04-02", spot_open=6480.0, outcome_close=None):
    return {
        "fecha": fecha, "phase": "open", "timestamp": "2026-04-02T14:25:00Z",
        "spot_open": spot_open, "d_score_total": 2, "v_score_total": 1,
        "outcome_spx_close": outcome_close,
        "outcome_spx_change_from_open_pct": None,
        "outcome_direction": None,
    }


# ── Test 1: append crea el fichero si no existe ───────────────────────────────

def test_append_crea_fichero(tmp_path_jsonl):
    assert not tmp_path_jsonl.exists()
    append_record(_pre_record(), path=tmp_path_jsonl)
    assert tmp_path_jsonl.exists()


# ── Test 2: append añade exactamente una línea ────────────────────────────────

def test_append_añade_linea(tmp_path_jsonl):
    append_record(_pre_record(), path=tmp_path_jsonl)
    lines = [l for l in tmp_path_jsonl.read_text().splitlines() if l.strip()]
    assert len(lines) == 1
    assert json.loads(lines[0])["phase"] == "premarket"


# ── Test 3: N appends → N líneas JSON válidas ─────────────────────────────────

def test_append_multiples_registros(tmp_path_jsonl):
    records = [_pre_record("2026-04-0" + str(i)) for i in range(2, 6)]
    for rec in records:
        append_record(rec, path=tmp_path_jsonl)
    lines = [l for l in tmp_path_jsonl.read_text().splitlines() if l.strip()]
    assert len(lines) == 4
    for line in lines:
        parsed = json.loads(line)
        assert "fecha" in parsed


# ── Test 4: fill_outcomes rellena los campos outcome_* ────────────────────────

def test_fill_outcomes_rellena_fecha(tmp_path_jsonl):
    append_record(_pre_record("2026-04-02", spot=6500.0), path=tmp_path_jsonl)
    n = fill_outcomes(6450.0, "2026-04-02", path=tmp_path_jsonl)
    assert n == 1
    rec = json.loads(tmp_path_jsonl.read_text().splitlines()[0])
    assert rec["outcome_spx_close"] == 6450.0
    assert rec["outcome_spx_change_pct"] is not None
    assert rec["outcome_direction"] == -1


# ── Test 5: fill_outcomes no toca otras fechas ────────────────────────────────

def test_fill_outcomes_no_toca_otras_fechas(tmp_path_jsonl):
    append_record(_pre_record("2026-04-01", spot=6400.0), path=tmp_path_jsonl)
    append_record(_pre_record("2026-04-02", spot=6500.0), path=tmp_path_jsonl)
    fill_outcomes(6450.0, "2026-04-02", path=tmp_path_jsonl)
    lines = [json.loads(l) for l in tmp_path_jsonl.read_text().splitlines() if l.strip()]
    rec_01 = next(r for r in lines if r["fecha"] == "2026-04-01")
    rec_02 = next(r for r in lines if r["fecha"] == "2026-04-02")
    assert rec_01["outcome_spx_close"] is None
    assert rec_02["outcome_spx_close"] == 6450.0


# ── Test 6: fill_outcomes devuelve 0 si no hay registros de esa fecha ─────────

def test_fill_outcomes_sin_registros(tmp_path_jsonl):
    append_record(_pre_record("2026-04-01"), path=tmp_path_jsonl)
    n = fill_outcomes(6450.0, "2026-04-05", path=tmp_path_jsonl)
    assert n == 0


# ── Test 7: fill_outcomes calcula direction correctamente ──────────────────────

def test_fill_outcomes_calcula_direction(tmp_path_jsonl):
    # Subida: close > spot → direction = +1
    append_record(_pre_record("2026-04-02", spot=6400.0), path=tmp_path_jsonl)
    fill_outcomes(6500.0, "2026-04-02", path=tmp_path_jsonl)
    rec = json.loads(tmp_path_jsonl.read_text().splitlines()[0])
    assert rec["outcome_direction"] == 1
    change = round((6500.0 - 6400.0) / 6400.0 * 100, 4)
    assert abs(rec["outcome_spx_change_pct"] - change) < 1e-6

    # Bajada: close < spot → direction = -1
    tmp_path_jsonl.write_text("")
    append_record(_pre_record("2026-04-03", spot=6500.0), path=tmp_path_jsonl)
    fill_outcomes(6400.0, "2026-04-03", path=tmp_path_jsonl)
    rec = json.loads(tmp_path_jsonl.read_text().splitlines()[0])
    assert rec["outcome_direction"] == -1

    # Sin movimiento: close == spot → direction = 0
    tmp_path_jsonl.write_text("")
    append_record(_pre_record("2026-04-04", spot=6500.0), path=tmp_path_jsonl)
    fill_outcomes(6500.0, "2026-04-04", path=tmp_path_jsonl)
    rec = json.loads(tmp_path_jsonl.read_text().splitlines()[0])
    assert rec["outcome_direction"] == 0


# ── Test 8: compatible con pandas ─────────────────────────────────────────────

def test_pandas_compatible(tmp_path_jsonl):
    try:
        import pandas as pd
    except ImportError:
        pytest.skip("pandas no disponible")

    for i in range(2, 5):
        append_record(_pre_record(f"2026-04-0{i}", spot=6400.0 + i * 10), path=tmp_path_jsonl)
        append_record(_open_record(f"2026-04-0{i}", spot_open=6390.0 + i * 10), path=tmp_path_jsonl)

    df = pd.read_json(tmp_path_jsonl, lines=True)
    assert df.shape[0] == 6
    assert "fecha" in df.columns
    assert "phase" in df.columns
    assert "outcome_direction" in df.columns


# ── Test bonus: fill_outcomes sobre phase open usa spot_open ──────────────────

def test_fill_outcomes_open_usa_spot_open(tmp_path_jsonl):
    append_record(_open_record("2026-04-02", spot_open=6480.0), path=tmp_path_jsonl)
    fill_outcomes(6528.0, "2026-04-02", path=tmp_path_jsonl)
    rec = json.loads(tmp_path_jsonl.read_text().splitlines()[0])
    assert rec["outcome_spx_close"] == 6528.0
    assert rec["outcome_direction"] == 1
    expected_change = round((6528.0 - 6480.0) / 6480.0 * 100, 4)
    assert abs(rec["outcome_spx_change_from_open_pct"] - expected_change) < 1e-6


# ── Test: fill_outcomes devuelve 0 si fichero no existe ───────────────────────

def test_fill_outcomes_fichero_inexistente(tmp_path):
    n = fill_outcomes(6500.0, "2026-04-02", path=tmp_path / "noexiste.jsonl")
    assert n == 0
