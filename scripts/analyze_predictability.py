"""
analyze_predictability.py — Evaluación de predictibilidad de D-Score y V-Score.

Carga logs/history.jsonl y ejecuta cuatro análisis:
  A-01  D-Score accuracy vs outcome_direction
  A-02  Importancia de indicadores individuales (Spearman)
  A-03  V-Score vs volatilidad realizada (|change_pct|)
  A-04  Accuracy del D-Score segmentada por régimen de VIX

Uso:
    uv run python scripts/analyze_predictability.py
    uv run python scripts/analyze_predictability.py --save
    uv run python scripts/analyze_predictability.py --history logs/history.jsonl --save
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from scipy.stats import pearsonr, spearmanr

# ---------------------------------------------------------------------------
# Mínimos orientativos de muestra por análisis
# ---------------------------------------------------------------------------
MIN_A01 = 20
MIN_A02 = 30
MIN_A03 = 20
MIN_A04 = 40
MIN_VIX_TRAMO = 5   # observaciones mínimas por tramo para no marcar ⚠


# ---------------------------------------------------------------------------
# Carga
# ---------------------------------------------------------------------------

def load_history(path: Path = Path("logs/history.jsonl")) -> pd.DataFrame:
    """
    Carga history.jsonl en un DataFrame.
    Devuelve DataFrame vacío si el fichero no existe o está vacío.
    """
    if not path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_json(path, lines=True)
        return df if not df.empty else pd.DataFrame()
    except (ValueError, Exception):
        return pd.DataFrame()


def _premarket_con_outcome(df: pd.DataFrame) -> pd.DataFrame:
    """Filtra registros premarket con outcome_direction relleno."""
    if df.empty:
        return pd.DataFrame()
    mask = (df.get("phase") == "premarket") & df["outcome_direction"].notna()
    return df[mask].copy()


# ---------------------------------------------------------------------------
# A-01 — D-Score vs dirección real
# ---------------------------------------------------------------------------

def analysis_dscore_accuracy(df: pd.DataFrame) -> dict:
    """
    A-01. Recibe df ya filtrado (phase=premarket, outcome no nulo).
    Calcula accuracy global y desglosada por régimen y magnitud de señal.
    """
    result: dict = {
        "n_total": len(df),
        "accuracy_global": None,
        "n_activo": 0,
        "por_regimen": {},
        "por_magnitud": {},
        "warning": None,
    }

    if df.empty or "d_score" not in df.columns or "outcome_direction" not in df.columns:
        result["warning"] = "sin_datos"
        return result

    if len(df) < MIN_A01:
        result["warning"] = f"muestra_insuficiente (N={len(df)}, min={MIN_A01})"

    df = df.copy()
    df["pred"] = df["d_score"].apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    df["hit"] = df["pred"] == df["outcome_direction"]

    # Solo predicciones activas (d_score != 0)
    df_activo = df[df["pred"] != 0]
    result["n_activo"] = len(df_activo)

    if df_activo.empty:
        return result

    result["accuracy_global"] = round(df_activo["hit"].mean(), 4)

    # Por régimen predicho
    for pred_val, grupo in df_activo.groupby("pred"):
        key = str(int(pred_val))
        result["por_regimen"][key] = {
            "hit_rate": round(grupo["hit"].mean(), 4),
            "n": len(grupo),
        }

    # Por magnitud de |d_score|
    df_activo = df_activo.copy()
    df_activo["abs_d"] = df_activo["d_score"].abs()
    df_activo["mag"] = df_activo["abs_d"].apply(lambda x: "≥4" if x >= 4 else str(int(x)))
    for mag_val, grupo in df_activo.groupby("mag", sort=True):
        result["por_magnitud"][mag_val] = {
            "hit_rate": round(grupo["hit"].mean(), 4),
            "n": len(grupo),
        }

    return result


# ---------------------------------------------------------------------------
# A-02 — Importancia de indicadores individuales
# ---------------------------------------------------------------------------

def analysis_indicator_importance(df: pd.DataFrame) -> dict:
    """
    A-02. Correlación de Spearman de cada indicador D-Score con outcome_direction.
    Regresión logística opcional si scikit-learn está instalado y N >= 50.
    """
    FEATURES = ["slope_score", "ratio_score", "gap_score", "gex_score", "flip_score"]
    VSCORE_FEATURES = ["ivr_score", "atr_score"]

    result: dict = {
        "n": len(df),
        "spearman": {},
        "logistica": None,
        "warning": None,
    }

    if df.empty or "outcome_direction" not in df.columns:
        result["warning"] = "sin_datos"
        return result

    if len(df) < MIN_A02:
        result["warning"] = f"muestra_insuficiente (N={len(df)}, min={MIN_A02})"

    y = df["outcome_direction"]

    for col in FEATURES + VSCORE_FEATURES:
        if col not in df.columns:
            continue
        serie = df[col].fillna(0)
        try:
            r, p = spearmanr(serie, y)
        except Exception:
            r, p = float("nan"), float("nan")
        result["spearman"][col] = {
            "r_spearman": round(float(r), 4),
            "p_valor": round(float(p), 4),
            "signo_ok": bool(r >= 0),  # esperamos r positivo en todos
        }

    # Regresión logística opcional
    if len(df) >= 50:
        try:
            from sklearn.linear_model import LogisticRegression
            from sklearn.preprocessing import StandardScaler

            cols_presentes = [c for c in FEATURES if c in df.columns]
            X = df[cols_presentes].fillna(0)
            y_bin = (df["outcome_direction"] == 1).astype(int)
            X_s = StandardScaler().fit_transform(X)
            model = LogisticRegression(C=1.0, max_iter=500).fit(X_s, y_bin)
            result["logistica"] = {
                col: round(float(coef), 4)
                for col, coef in zip(cols_presentes, model.coef_[0])
            }
        except ImportError:
            result["logistica"] = None

    return result


# ---------------------------------------------------------------------------
# A-03 — V-Score vs volatilidad realizada
# ---------------------------------------------------------------------------

def analysis_vscore_vs_vol(df: pd.DataFrame) -> dict:
    """
    A-03. Correlación de Pearson entre v_score y |outcome_spx_change_pct|.
    Tabla de movimiento medio por tramos de V-Score.
    """
    result: dict = {
        "n": len(df),
        "pearson_r": None,
        "p_valor": None,
        "por_tramo": {},
        "warning": None,
    }

    needed = {"v_score", "outcome_spx_change_pct"}
    if df.empty or not needed.issubset(df.columns):
        result["warning"] = "sin_datos"
        return result

    df = df.dropna(subset=["v_score", "outcome_spx_change_pct"]).copy()

    if len(df) < MIN_A03:
        result["warning"] = f"muestra_insuficiente (N={len(df)}, min={MIN_A03})"

    df["actual_move"] = df["outcome_spx_change_pct"].abs()

    try:
        r, p = pearsonr(df["v_score"], df["actual_move"])
        result["pearson_r"] = round(float(r), 4)
        result["p_valor"] = round(float(p), 4)
    except Exception:
        pass

    bins = [-float("inf"), 0, 2, 4, float("inf")]
    labels = ["≤0", "1-2", "3-4", "≥5"]
    df["tramo"] = pd.cut(df["v_score"], bins=bins, labels=labels)

    for tramo, grupo in df.groupby("tramo", observed=True):
        result["por_tramo"][str(tramo)] = {
            "move_medio": round(float(grupo["actual_move"].mean()), 4),
            "move_std": round(float(grupo["actual_move"].std()), 4) if len(grupo) > 1 else None,
            "n": len(grupo),
        }

    return result


# ---------------------------------------------------------------------------
# A-04 — Accuracy por régimen de VIX
# ---------------------------------------------------------------------------

def analysis_dscore_by_vix(df: pd.DataFrame) -> dict:
    """
    A-04. Accuracy del D-Score segmentada por tramos del nivel de VIX (slope_vix).
    """
    result: dict = {
        "n": len(df),
        "por_tramo": {},
        "mejor_tramo": None,
        "peor_tramo": None,
        "warning": None,
    }

    needed = {"slope_vix", "d_score", "outcome_direction"}
    if df.empty or not needed.issubset(df.columns):
        result["warning"] = "sin_datos"
        return result

    if len(df) < MIN_A04:
        result["warning"] = f"muestra_insuficiente (N={len(df)}, min={MIN_A04})"

    df = df.copy()
    df["pred"] = df["d_score"].apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    df_activo = df[df["pred"] != 0].dropna(subset=["slope_vix"]).copy()
    df_activo["hit"] = df_activo["pred"] == df_activo["outcome_direction"]

    bins = [0, 15, 20, 25, 35, float("inf")]
    labels = ["<15", "15-20", "20-25", "25-35", ">35"]
    df_activo["tramo_vix"] = pd.cut(df_activo["slope_vix"], bins=bins, labels=labels)

    tramo_accuracy = {}
    for tramo, grupo in df_activo.groupby("tramo_vix", observed=True):
        entry: dict = {
            "accuracy": round(float(grupo["hit"].mean()), 4),
            "n": len(grupo),
        }
        if len(grupo) < MIN_VIX_TRAMO:
            entry["warning"] = "muestra_insuficiente"
        result["por_tramo"][str(tramo)] = entry
        tramo_accuracy[str(tramo)] = entry["accuracy"] if len(grupo) >= MIN_VIX_TRAMO else None

    validos = {k: v for k, v in tramo_accuracy.items() if v is not None}
    if validos:
        result["mejor_tramo"] = max(validos, key=lambda k: validos[k])
        result["peor_tramo"] = min(validos, key=lambda k: validos[k])

    return result


# ---------------------------------------------------------------------------
# Presentación
# ---------------------------------------------------------------------------

def print_report(results: dict) -> None:
    """Imprime el reporte completo en terminal."""

    meta = results.get("meta", {})
    n    = meta.get("n_registros", "?")
    desde = meta.get("periodo_desde", "?")
    hasta = meta.get("periodo_hasta", "?")

    print()
    print("=" * 65)
    print("  ANÁLISIS DE PREDICTIBILIDAD — logs/history.jsonl")
    print(f"  Registros premarket con outcome: N={n}")
    print(f"  Periodo: {desde} → {hasta}")
    print("=" * 65)

    # A-01
    a01 = results.get("a01_dscore_accuracy", {})
    print()
    print("[A-01] D-SCORE vs DIRECCIÓN REAL")
    if a01.get("warning"):
        print(f"  ⚠  {a01['warning']}")
    if a01.get("accuracy_global") is not None:
        print(f"  Accuracy global: {a01['accuracy_global']:.2f}  "
              f"(N={a01.get('n_activo', '?')}, excl. d_score=0)")
        print("  Por régimen:")
        for reg, datos in sorted(a01.get("por_regimen", {}).items()):
            signo = "+" if int(reg) > 0 else ""
            print(f"    pred={signo}{reg}  →  hit={datos['hit_rate']:.2f}  (N={datos['n']})")
        if a01.get("por_magnitud"):
            print("  Por magnitud de señal:")
            for mag, datos in sorted(a01["por_magnitud"].items()):
                print(f"    |d_score|={mag}  →  hit={datos['hit_rate']:.2f}  (N={datos['n']})")
    else:
        print("  Sin datos suficientes.")

    # A-02
    a02 = results.get("a02_indicadores", {})
    print()
    print("[A-02] IMPORTANCIA DE INDICADORES (Spearman)")
    if a02.get("warning"):
        print(f"  ⚠  {a02['warning']}")
    spearman = a02.get("spearman", {})
    if spearman:
        mejor = max(spearman, key=lambda k: abs(spearman[k]["r_spearman"]))
        for col, datos in spearman.items():
            r    = datos["r_spearman"]
            p    = datos["p_valor"]
            marca = "⚠ signo invertido" if not datos["signo_ok"] else "✓"
            estrella = "  ← mayor |r|" if col == mejor else ""
            print(f"  {col:15}  r={r:+.2f}  p={p:.3f}  {marca}{estrella}")
        if a02.get("logistica"):
            print("  Regresión logística (coeficientes estandarizados):")
            for col, coef in a02["logistica"].items():
                print(f"    {col:15}  coef={coef:+.3f}")
    else:
        print("  Sin datos suficientes.")

    # A-03
    a03 = results.get("a03_vscore_vol", {})
    print()
    print("[A-03] V-SCORE vs VOLATILIDAD REALIZADA")
    if a03.get("warning"):
        print(f"  ⚠  {a03['warning']}")
    if a03.get("pearson_r") is not None:
        signo = "✓ correlación positiva" if a03["pearson_r"] > 0 else "⚠ correlación negativa"
        print(f"  Pearson r={a03['pearson_r']:+.2f}  p={a03['p_valor']:.3f}  {signo}")
        print("  Por tramo de V-Score:")
        for tramo, datos in a03.get("por_tramo", {}).items():
            std_str = f"std={datos['move_std']:.2f}" if datos["move_std"] is not None else "std=n/a"
            print(f"    v_score {tramo:5}  →  move_medio={datos['move_medio']:.2f}%  "
                  f"{std_str}  N={datos['n']}")
    else:
        print("  Sin datos suficientes.")

    # A-04
    a04 = results.get("a04_accuracy_vix", {})
    print()
    print("[A-04] ACCURACY POR RÉGIMEN DE VIX")
    if a04.get("warning"):
        print(f"  ⚠  {a04['warning']}")
    if a04.get("por_tramo"):
        for tramo, datos in a04["por_tramo"].items():
            warn = "  ⚠ muestra insuficiente" if datos.get("warning") else ""
            print(f"  VIX {tramo:6}  →  accuracy={datos['accuracy']:.2f}  N={datos['n']}{warn}")
        if a04.get("mejor_tramo"):
            mejor = a04["mejor_tramo"]
            peor  = a04["peor_tramo"]
            print(f"  Mejor régimen:  VIX {mejor}  "
                  f"(accuracy={a04['por_tramo'][mejor]['accuracy']:.2f})")
            print(f"  Peor régimen:   VIX {peor}  "
                  f"(accuracy={a04['por_tramo'][peor]['accuracy']:.2f})")
    else:
        print("  Sin datos suficientes.")

    print()
    print("=" * 65)
    print()


def save_report(
    results: dict,
    path: Path = Path("outputs/predictability.json"),
) -> None:
    """Guarda el reporte en JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------

def run_analysis(
    history_path: Path = Path("logs/history.jsonl"),
    save: bool = False,
) -> dict:
    """
    Carga history.jsonl, ejecuta los 4 análisis, imprime el reporte
    y opcionalmente guarda outputs/predictability.json.
    Devuelve el dict completo de resultados.
    """
    df_all = load_history(history_path)
    df_pre = _premarket_con_outcome(df_all)

    # Metadatos
    n = len(df_pre)
    desde = str(df_pre["fecha"].min()) if n > 0 else "—"
    hasta = str(df_pre["fecha"].max()) if n > 0 else "—"

    results = {
        "generado": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "meta": {
            "n_registros": n,
            "periodo_desde": desde,
            "periodo_hasta": hasta,
        },
        "a01_dscore_accuracy":   analysis_dscore_accuracy(df_pre),
        "a02_indicadores":       analysis_indicator_importance(df_pre),
        "a03_vscore_vol":        analysis_vscore_vs_vol(df_pre),
        "a04_accuracy_vix":      analysis_dscore_by_vix(df_pre),
    }

    print_report(results)

    if save:
        save_report(results)

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Análisis de predictibilidad de D-Score y V-Score"
    )
    parser.add_argument(
        "--history",
        type=Path,
        default=Path("logs/history.jsonl"),
        help="Ruta al fichero history.jsonl (default: logs/history.jsonl)",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Guardar resultados en outputs/predictability.json",
    )
    args = parser.parse_args()
    run_analysis(history_path=args.history, save=args.save)
