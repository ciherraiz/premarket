"""
Tests para scripts/analyze_predictability.py

Cubre los 10 casos descritos en specs/workflow_predictability.md:
  1. load_history con fichero inexistente
  2. load_history carga N filas correctamente
  3. A-01 accuracy global básica (3 hits de 4)
  4. A-01 excluye d_score=0 del cálculo de accuracy
  5. A-02 indicador con r<0 genera signo_ok=False
  6. A-03 Pearson conocido en datos sintéticos perfectos
  7. A-03 agrupación por tramos devuelve N correcto
  8. A-04 tramos de VIX asignados correctamente
  9. Advertencia cuando N < mínimo de cualquier análisis
 10. run_analysis con fichero vacío no lanza excepción
"""

import json
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import pytest

from scripts.analyze_predictability import (
    analysis_dscore_accuracy,
    analysis_dscore_by_vix,
    analysis_indicator_importance,
    analysis_vscore_vs_vol,
    load_history,
    run_analysis,
)


# ---------------------------------------------------------------------------
# Helpers para construir DataFrames de prueba
# ---------------------------------------------------------------------------

def _pre_df(**kwargs) -> pd.DataFrame:
    """DataFrame premarket mínimo para las pruebas."""
    defaults = {
        "phase": "premarket",
        "fecha": "2026-04-07",
        "d_score": 0,
        "v_score": 0,
        "slope_score": 0,
        "ratio_score": 0,
        "gap_score": 0,
        "gex_score": 0,
        "flip_score": 0,
        "ivr_score": 0,
        "atr_score": 0,
        "slope_vix": 20.0,
        "outcome_direction": None,
        "outcome_spx_change_pct": None,
    }
    defaults.update(kwargs)
    return pd.DataFrame([defaults])


def _build_df(rows: list[dict]) -> pd.DataFrame:
    """Construye un DataFrame a partir de una lista de dicts parciales."""
    base = {
        "phase": "premarket",
        "d_score": 0,
        "v_score": 0,
        "slope_score": 0,
        "ratio_score": 0,
        "gap_score": 0,
        "gex_score": 0,
        "flip_score": 0,
        "ivr_score": 0,
        "atr_score": 0,
        "slope_vix": 20.0,
        "outcome_direction": None,
        "outcome_spx_change_pct": None,
        "fecha": "2026-04-07",
    }
    records = []
    for row in rows:
        r = base.copy()
        r.update(row)
        records.append(r)
    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Test 1 — load_history con fichero inexistente
# ---------------------------------------------------------------------------

def test_load_history_vacio(tmp_path):
    ruta = tmp_path / "no_existe.jsonl"
    df = load_history(ruta)
    assert isinstance(df, pd.DataFrame)
    assert df.empty


# ---------------------------------------------------------------------------
# Test 2 — load_history carga N filas correctamente
# ---------------------------------------------------------------------------

def test_load_history_carga_filas(tmp_path):
    ruta = tmp_path / "history.jsonl"
    registros = [
        {"fecha": "2026-04-07", "phase": "premarket", "d_score": 1},
        {"fecha": "2026-04-08", "phase": "premarket", "d_score": -2},
        {"fecha": "2026-04-08", "phase": "open",      "d_score_total": 3},
    ]
    with open(ruta, "w") as f:
        for r in registros:
            f.write(json.dumps(r) + "\n")

    df = load_history(ruta)
    assert len(df) == 3
    assert "d_score" in df.columns
    assert "phase" in df.columns


# ---------------------------------------------------------------------------
# Test 3 — A-01 accuracy global básica (3 hits de 4)
# ---------------------------------------------------------------------------

def test_dscore_accuracy_global():
    df = _build_df([
        {"d_score":  2, "outcome_direction":  1},   # hit
        {"d_score": -1, "outcome_direction": -1},   # hit
        {"d_score":  3, "outcome_direction":  1},   # hit
        {"d_score":  1, "outcome_direction": -1},   # miss
    ])
    result = analysis_dscore_accuracy(df)
    assert result["accuracy_global"] == pytest.approx(0.75, abs=1e-4)
    assert result["n_activo"] == 4


# ---------------------------------------------------------------------------
# Test 4 — A-01 excluye d_score=0 del cálculo
# ---------------------------------------------------------------------------

def test_dscore_accuracy_excluye_cero():
    df = _build_df([
        {"d_score":  1, "outcome_direction":  1},   # hit
        {"d_score":  0, "outcome_direction": -1},   # NO cuenta
        {"d_score": -1, "outcome_direction":  1},   # miss
    ])
    result = analysis_dscore_accuracy(df)
    # Solo 2 predicciones activas: 1 hit → 0.5
    assert result["accuracy_global"] == pytest.approx(0.50, abs=1e-4)
    assert result["n_activo"] == 2


# ---------------------------------------------------------------------------
# Test 5 — A-02 indicador con r<0 genera signo_ok=False
# ---------------------------------------------------------------------------

def test_indicator_importance_signos():
    # gex_score invertido: cuando gex_score es alto, outcome es bajo
    rows = []
    for i in range(15):
        rows.append({
            "slope_score": 1, "ratio_score": 0, "gap_score": 1,
            "gex_score": 2,   "flip_score": 0,
            "ivr_score": 0,   "atr_score": 0,
            "outcome_direction": -1,   # gex alto → mercado baja (invertido)
        })
    for i in range(15):
        rows.append({
            "slope_score": 1, "ratio_score": 0, "gap_score": 1,
            "gex_score": -2,  "flip_score": 0,
            "ivr_score": 0,   "atr_score": 0,
            "outcome_direction": 1,    # gex bajo → mercado sube (invertido)
        })
    df = _build_df(rows)
    result = analysis_indicator_importance(df)
    gex_info = result["spearman"].get("gex_score", {})
    assert gex_info.get("signo_ok") is False


# ---------------------------------------------------------------------------
# Test 6 — A-03 Pearson ≈ 1.0 con datos perfectamente correlados
# ---------------------------------------------------------------------------

def test_vscore_pearson():
    # v_score y |change_pct| perfectamente correlados
    rows = [{"v_score": i, "outcome_spx_change_pct": float(i)} for i in range(1, 21)]
    df = _build_df(rows)
    result = analysis_vscore_vs_vol(df)
    assert result["pearson_r"] is not None
    assert result["pearson_r"] == pytest.approx(1.0, abs=0.01)


# ---------------------------------------------------------------------------
# Test 7 — A-03 agrupación por tramos devuelve N correcto
# ---------------------------------------------------------------------------

def test_vscore_agrupacion_tramos():
    rows = (
        [{"v_score": -1, "outcome_spx_change_pct": 0.5}] * 4 +   # tramo ≤0
        [{"v_score":  1, "outcome_spx_change_pct": 0.8}] * 6 +   # tramo 1-2
        [{"v_score":  3, "outcome_spx_change_pct": 1.2}] * 3     # tramo 3-4
    )
    df = _build_df(rows)
    result = analysis_vscore_vs_vol(df)
    tramos = result["por_tramo"]
    assert tramos.get("≤0", {}).get("n") == 4
    assert tramos.get("1-2", {}).get("n") == 6
    assert tramos.get("3-4", {}).get("n") == 3


# ---------------------------------------------------------------------------
# Test 8 — A-04 tramos de VIX asignados correctamente
# ---------------------------------------------------------------------------

def test_dscore_by_vix_tramos():
    rows = [
        {"slope_vix": 12.0, "d_score":  2, "outcome_direction":  1},   # <15
        {"slope_vix": 17.5, "d_score": -1, "outcome_direction": -1},   # 15-20
        {"slope_vix": 22.0, "d_score":  3, "outcome_direction": -1},   # 20-25
        {"slope_vix": 28.0, "d_score": -2, "outcome_direction":  1},   # 25-35
        {"slope_vix": 40.0, "d_score":  1, "outcome_direction":  1},   # >35
    ]
    df = _build_df(rows)
    result = analysis_dscore_by_vix(df)
    tramos = result["por_tramo"]
    assert "<15"   in tramos and tramos["<15"]["n"]   == 1
    assert "15-20" in tramos and tramos["15-20"]["n"] == 1
    assert "20-25" in tramos and tramos["20-25"]["n"] == 1
    assert "25-35" in tramos and tramos["25-35"]["n"] == 1
    assert ">35"   in tramos and tramos[">35"]["n"]   == 1


# ---------------------------------------------------------------------------
# Test 9 — Advertencia cuando N < mínimo
# ---------------------------------------------------------------------------

def test_warning_muestra_insuficiente():
    # Solo 5 registros → insuficiente para todos los análisis
    rows = [
        {"d_score": 1, "v_score": 2, "slope_vix": 18.0,
         "outcome_direction": 1, "outcome_spx_change_pct": 0.5,
         "slope_score": 1, "ratio_score": 0, "gap_score": 0,
         "gex_score": 1, "flip_score": 0, "ivr_score": 1, "atr_score": 0}
        for _ in range(5)
    ]
    df = _build_df(rows)

    a01 = analysis_dscore_accuracy(df)
    a02 = analysis_indicator_importance(df)
    a03 = analysis_vscore_vs_vol(df)
    a04 = analysis_dscore_by_vix(df)

    assert a01["warning"] is not None and "insuficiente" in a01["warning"]
    assert a02["warning"] is not None and "insuficiente" in a02["warning"]
    assert a03["warning"] is not None and "insuficiente" in a03["warning"]
    assert a04["warning"] is not None and "insuficiente" in a04["warning"]


# ---------------------------------------------------------------------------
# Test 10 — run_analysis con fichero vacío no lanza excepción
# ---------------------------------------------------------------------------

def test_run_analysis_sin_datos(tmp_path):
    ruta = tmp_path / "history.jsonl"
    ruta.write_text("")   # fichero vacío

    # No debe lanzar excepción
    result = run_analysis(history_path=ruta, save=False)

    assert isinstance(result, dict)
    assert "a01_dscore_accuracy" in result
    assert "a02_indicadores" in result
    assert "a03_vscore_vol" in result
    assert "a04_accuracy_vix" in result
    assert result["meta"]["n_registros"] == 0
