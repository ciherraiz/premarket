# Spec: Workflow Predictabilidad — Evaluación de D-Score y V-Score

## Estado
[ ] Pendiente de implementación

## Propósito

Evaluar la calidad predictiva de D-Score y V-Score usando el historial acumulado
en `logs/history.jsonl` (definido en `specs/workflow_history.md`).

Cuatro análisis progresivos que van de lo global a lo granular:

| ID   | Análisis                          | Pregunta clave                                    |
|------|-----------------------------------|---------------------------------------------------|
| A-01 | D-Score vs dirección real         | ¿El signo de d_score predice la dirección?        |
| A-02 | Importancia de indicadores        | ¿Qué indicador individual correlaciona más?       |
| A-03 | V-Score vs volatilidad realizada  | ¿V-Score alto predice días de mayor movimiento?   |
| A-04 | Accuracy por régimen de VIX       | ¿En qué nivel de VIX funciona mejor el D-Score?  |

La rentabilidad de estrategias (requiere pricing de opciones) queda fuera de
scope — se aborda en una segunda fase.

---

## Prerequisitos del dataset

El script lee `logs/history.jsonl` y filtra registros con `outcome_direction != null`.
Los análisis requieren una muestra mínima orientativa para ser interpretables
(no estadísticamente significativos, pero sí indicativos de tendencias):

| Análisis | Mínimo orientativo | Justificación                              |
|----------|--------------------|--------------------------------------------|
| A-01     | 20 días            | Accuracy binaria fiable desde ~20 obs.     |
| A-02     | 30 días            | Spearman necesita varianza suficiente       |
| A-03     | 20 días            | Correlación Pearson razonablemente estable |
| A-04     | 40 días            | ≥5 observaciones por tramo de VIX          |

Si no se alcanza el mínimo, el script **imprime una advertencia** junto al resultado
pero **no aborta**: el análisis con pocos datos es orientativo y visible.

---

## Columnas del DataFrame usadas

El DataFrame se construye desde `logs/history.jsonl` filtrando `phase == "premarket"`.
Las columnas relevantes (definidas en `workflow_history.md`) son:

**Predictores (disponibles en el momento del análisis premarket):**

| Columna        | Tipo    | Descripción                                      |
|----------------|---------|--------------------------------------------------|
| `d_score`      | int     | D-Score premarket (aprox. −10 a +10)             |
| `v_score`      | int     | V-Score premarket (aprox. −2 a +5)               |
| `slope_score`  | int     | Score de VIX/VXV Slope (−2 a +2)                 |
| `ratio_score`  | int     | Score de VIX9D/VIX Ratio (−2 a +2)               |
| `gap_score`    | int     | Score de Overnight Gap (−1 a +1)                 |
| `gex_score`    | int     | Score de Net GEX (−3 a +3)                       |
| `flip_score`   | int     | Score de Flip Level (−2 a +2)                    |
| `ivr_score`    | int     | Score de IV Rank (−3 a +3)                       |
| `atr_score`    | int     | Score de ATR Ratio (−2 a +2)                     |
| `slope_vix`    | float   | Nivel de VIX en el momento del cálculo (proxy)   |

**Outcomes (rellenados al día siguiente por `fill_outcomes`):**

| Columna                  | Tipo    | Descripción                                   |
|--------------------------|---------|-----------------------------------------------|
| `outcome_direction`      | int     | +1 subida, −1 bajada, 0 plano                 |
| `outcome_spx_change_pct` | float   | Variación % real del día (SPX cierre vs spot) |

---

## Análisis A-01 — D-Score vs dirección real

### Qué mide
Accuracy global de `sign(d_score)` contra `outcome_direction`.
Responde a: ¿el signo del D-Score premarket predice la dirección de la sesión?

### Metodología

```python
df_pre = df[(df.phase == "premarket") & df.outcome_direction.notna()]
df_pre["pred"] = df_pre["d_score"].apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))

# 1. Accuracy global (excluye d_score=0, que no es predicción)
df_activo = df_pre[df_pre.pred != 0]
accuracy_global = (df_activo.pred == df_activo.outcome_direction).mean()

# 2. Accuracy por régimen predicho
df_activo.groupby("pred").apply(
    lambda g: pd.Series({"hit_rate": (g.pred == g.outcome_direction).mean(), "N": len(g)})
)

# 3. Accuracy por magnitud de |d_score|
df_pre["abs_d"] = df_pre["d_score"].abs()
df_pre["mag"] = df_pre["abs_d"].clip(upper=4).map({1: "1", 2: "2", 3: "3", 4: "≥4"})
df_activo.groupby("mag")["hit"].mean()
```

### Output esperado

```
[A-01] D-SCORE vs DIRECCIÓN REAL
  Accuracy global: 0.62  (N=50, excl. d_score=0)
  Por régimen:
    pred=-1  →  hit=0.58  (N=24)
    pred=+1  →  hit=0.67  (N=27)
  Por magnitud de señal:
    |d_score|=1  →  hit=0.51  (N=15)
    |d_score|=2  →  hit=0.63  (N=18)
    |d_score|=3  →  hit=0.71  (N=12)
    |d_score|≥4  →  hit=0.80  (N=5)
```

### Interpretación
- Accuracy > 0.55 sostenida → señal de poder predictivo real
- Magnitud creciente con |d_score| → las señales extremas son más fiables
- Assimetría entre pred=+1 y pred=−1 → el sistema funciona mejor en un régimen

---

## Análisis A-02 — Importancia de indicadores individuales

### Qué mide
Qué indicador del D-Score tiene mayor correlación individual con `outcome_direction`.
Permite detectar indicadores bien calibrados, sobrепonderados o con signo invertido.

### Metodología

**Método principal: correlación de Spearman** (robusta con N pequeño y variables ordinales)

```python
from scipy.stats import spearmanr

features = ["slope_score", "ratio_score", "gap_score", "gex_score", "flip_score"]
for col in features:
    r, p = spearmanr(df_pre[col], df_pre["outcome_direction"])
    warning = "⚠ signo invertido" if r < 0 else "✓"
    print(f"  {col:15}  r={r:+.2f}  p={p:.3f}  {warning}")
```

**Método secundario: regresión logística** (solo cuando N ≥ 50, marcado como opcional)

```python
# Opcional — activar si N >= 50
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

X = df_pre[features].fillna(0)
y = (df_pre["outcome_direction"] == 1).astype(int)
X_s = StandardScaler().fit_transform(X)
model = LogisticRegression(C=1.0, max_iter=500).fit(X_s, y)
coefs = dict(zip(features, model.coef_[0]))
# coef > 0 → indicador alcista correlaciona con días alcistas (correcto)
# coef < 0 → indicador tiene efecto contrario al diseñado (recalibrar)
```

### Output esperado

```
[A-02] IMPORTANCIA DE INDICADORES (Spearman)
  slope_score  →  r=+0.21  p=0.082  ✓
  ratio_score  →  r=+0.15  p=0.213
  gap_score    →  r=+0.31  p=0.012  ✓  ← mayor correlación
  gex_score    →  r=-0.08  p=0.514  ⚠ signo invertido
  flip_score   →  r=+0.18  p=0.134
  ivr_score    →  r=+0.09  p=0.431  (V-Score, referencia)
  atr_score    →  r=+0.12  p=0.298  (V-Score, referencia)
```

### Interpretación
- `r` positivo y bajo p-valor → indicador alineado y predictivo
- `r` positivo y p-valor alto → indicador alineado pero sin señal clara aún
- `r` negativo → el indicador va en sentido contrario al esperado; candidato a recalibrar peso o lógica
- El indicador de mayor `|r|` es el que más aporta al D-Score en la muestra actual

---

## Análisis A-03 — V-Score vs volatilidad realizada

### Qué mide
Si V-Score alto predice días de mayor movimiento absoluto del SPX.
El V-Score no predice dirección, sino amplitud — por eso la métrica es `|change_pct|`.

### Metodología

```python
df_pre = df[(df.phase == "premarket") & df.outcome_spx_change_pct.notna()]
df_pre["actual_move"] = df_pre["outcome_spx_change_pct"].abs()

# 1. Correlación de Pearson
from scipy.stats import pearsonr
r, p = pearsonr(df_pre["v_score"], df_pre["actual_move"])

# 2. Agrupación por tramos de V-Score
bins   = [-float("inf"), 0, 2, 4, float("inf")]
labels = ["≤0", "1–2", "3–4", "≥5"]
df_pre["tramo"] = pd.cut(df_pre["v_score"], bins=bins, labels=labels)
tabla = df_pre.groupby("tramo", observed=True)["actual_move"].agg(
    move_medio="mean", move_std="std", N="count"
)
```

### Output esperado

```
[A-03] V-SCORE vs VOLATILIDAD REALIZADA
  Pearson r=+0.38  p=0.003  ✓ correlación positiva
  Por tramo de V-Score:
    v_score ≤0    →  move_medio=0.42%  std=0.31  N=8
    v_score 1–2   →  move_medio=0.79%  std=0.45  N=25
    v_score 3–4   →  move_medio=1.21%  std=0.61  N=14
    v_score ≥5    →  move_medio=1.85%  std=0.90  N=3
```

### Interpretación
- Pearson r > +0.25 → V-Score tiene poder predictivo sobre la amplitud del movimiento
- `move_medio` creciente con `v_score` → la tabla de estrategia (spreads más amplios en V-Score alto) está justificada
- Si `move_medio` es plano entre tramos → V-Score no discrimina amplitud; revisar indicadores

---

## Análisis A-04 — Accuracy del D-Score por régimen de VIX

### Qué mide
Si el D-Score funciona mejor o peor según el nivel de VIX en el momento del análisis.
Permite identificar regímenes de mercado donde el sistema es más o menos fiable.

### Metodología

```python
bins   = [0, 15, 20, 25, 35, float("inf")]
labels = ["<15", "15–20", "20–25", "25–35", ">35"]
df_pre["tramo_vix"] = pd.cut(df_pre["slope_vix"], bins=bins, labels=labels)

df_pre["pred"] = df_pre["d_score"].apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
df_activo = df_pre[df_pre.pred != 0].copy()
df_activo["hit"] = df_activo["pred"] == df_activo["outcome_direction"]

tabla = df_activo.groupby("tramo_vix", observed=True)["hit"].agg(
    accuracy="mean", N="count"
)
```

### Output esperado

```
[A-04] ACCURACY POR RÉGIMEN DE VIX
  VIX < 15     →  accuracy=0.71  N=7
  VIX 15–20    →  accuracy=0.65  N=18
  VIX 20–25    →  accuracy=0.58  N=14
  VIX 25–35    →  accuracy=0.52  N=9
  VIX > 35     →  accuracy=0.40  N=2  ⚠ muestra insuficiente
  Mejor régimen:   VIX < 15  (accuracy=0.71)
  Peor régimen:    VIX > 35  (accuracy=0.40)
```

### Interpretación
- Accuracy alta en VIX bajo → el sistema funciona bien en mercados tendenciales y tranquilos
- Accuracy baja en VIX alto → en regímenes de pánico las señales son menos fiables;
  considerar reducir tamaño de posición o pasar a estrategias neutrales
- Tramos con N < 5 → marcados con ⚠; no conclusivos

---

## Output del script

### Terminal (siempre)

```
=================================================================
  ANÁLISIS DE PREDICTIBILIDAD — logs/history.jsonl
  Registros premarket con outcome: N=50
  Periodo: 2026-04-07 → 2026-08-15
=================================================================

[A-01] D-SCORE vs DIRECCIÓN REAL
  ...

[A-02] IMPORTANCIA DE INDICADORES (Spearman)
  ...

[A-03] V-SCORE vs VOLATILIDAD REALIZADA
  ...

[A-04] ACCURACY POR RÉGIMEN DE VIX
  ...

=================================================================
```

### Fichero JSON (opcional, `outputs/predictability.json`)

Se genera si el script se invoca con `--save`:

```json
{
  "generado":     "2026-08-15T09:15:00Z",
  "n_registros":  50,
  "periodo_desde": "2026-04-07",
  "periodo_hasta": "2026-08-15",
  "a01_dscore_accuracy": {
    "accuracy_global": 0.62,
    "n": 50,
    "por_regimen":  { "-1": {"hit_rate": 0.58, "n": 24}, "+1": {"hit_rate": 0.67, "n": 27} },
    "por_magnitud": { "1": {"hit_rate": 0.51, "n": 15}, "2": {"hit_rate": 0.63, "n": 18} }
  },
  "a02_indicadores": {
    "slope_score":  {"r_spearman": 0.21, "p_valor": 0.082, "signo_ok": true},
    "ratio_score":  {"r_spearman": 0.15, "p_valor": 0.213, "signo_ok": true},
    "gap_score":    {"r_spearman": 0.31, "p_valor": 0.012, "signo_ok": true},
    "gex_score":    {"r_spearman": -0.08, "p_valor": 0.514, "signo_ok": false},
    "flip_score":   {"r_spearman": 0.18, "p_valor": 0.134, "signo_ok": true}
  },
  "a03_vscore_vol": {
    "pearson_r": 0.38,
    "p_valor": 0.003,
    "por_tramo": {
      "≤0":  {"move_medio": 0.42, "move_std": 0.31, "n": 8},
      "1-2": {"move_medio": 0.79, "move_std": 0.45, "n": 25}
    }
  },
  "a04_accuracy_vix": {
    "<15":   {"accuracy": 0.71, "n": 7},
    "15-20": {"accuracy": 0.65, "n": 18},
    "20-25": {"accuracy": 0.58, "n": 14},
    "25-35": {"accuracy": 0.52, "n": 9},
    ">35":   {"accuracy": 0.40, "n": 2, "warning": "muestra_insuficiente"}
  }
}
```

---

## Implementación

### Nuevo fichero: `scripts/analyze_predictability.py`

```python
def load_history(path: Path = Path("logs/history.jsonl")) -> pd.DataFrame:
    """Carga history.jsonl. Devuelve DataFrame vacío si no existe o está vacío."""

def analysis_dscore_accuracy(df: pd.DataFrame) -> dict:
    """A-01. Recibe df filtrado phase=premarket con outcome_direction no nulo."""

def analysis_indicator_importance(df: pd.DataFrame) -> dict:
    """A-02. Spearman por indicador + regresión logística opcional si N≥50."""

def analysis_vscore_vs_vol(df: pd.DataFrame) -> dict:
    """A-03. Pearson r + tabla por tramos de v_score."""

def analysis_dscore_by_vix(df: pd.DataFrame) -> dict:
    """A-04. Accuracy por tramo de slope_vix."""

def print_report(results: dict) -> None:
    """Imprime el reporte completo en terminal."""

def save_report(results: dict, path: Path = Path("outputs/predictability.json")) -> None:
    """Guarda el reporte en JSON. Solo se llama con --save."""

def run_analysis(
    history_path: Path = Path("logs/history.jsonl"),
    save: bool = False,
) -> dict:
    """Punto de entrada. Carga, ejecuta los 4 análisis, imprime y devuelve dict."""
```

**CLI:**
```bash
# Solo terminal
uv run python scripts/analyze_predictability.py

# Terminal + guardar outputs/predictability.json
uv run python scripts/analyze_predictability.py --save

# Path custom
uv run python scripts/analyze_predictability.py --history logs/history.jsonl --save
```

### Dependencias nuevas

| Paquete       | Uso                              | Obligatorio |
|---------------|----------------------------------|-------------|
| `scipy`       | `spearmanr`, `pearsonr`          | Sí          |
| `scikit-learn`| Regresión logística en A-02      | No (opcional, N≥50) |
| `pandas`      | DataFrame, `pd.cut`, `groupby`   | Ya presente |

Añadir en `pyproject.toml`:
```toml
"scipy>=1.13",
```

`scikit-learn` no se añade como dependencia fija — se importa con `try/except` en A-02
y solo se usa si está disponible y N ≥ 50.

### Ficheros a crear / modificar

| Acción   | Fichero                                  | Cambio                            |
|----------|------------------------------------------|-----------------------------------|
| Crear    | `scripts/analyze_predictability.py`      | Script principal                  |
| Crear    | `tests/test_analyze_predictability.py`   | 10 tests unitarios                |
| Modificar| `pyproject.toml`                         | Añadir `scipy>=1.13`              |

Ningún fichero existente del pipeline (`run.py`, `calculate_indicators.py`, etc.) se modifica.

---

## Tests (`tests/test_analyze_predictability.py`)

| #  | Nombre                              | Qué verifica                                                          |
|----|-------------------------------------|-----------------------------------------------------------------------|
| 1  | `test_load_history_vacio`           | Fichero inexistente → DataFrame vacío sin excepción                   |
| 2  | `test_load_history_carga_filas`     | N líneas JSONL → DataFrame con N filas y columnas correctas           |
| 3  | `test_dscore_accuracy_global`       | 3 hits de 4 predicciones activas → accuracy=0.75                     |
| 4  | `test_dscore_accuracy_excluye_cero` | d_score=0 no se cuenta ni en numerador ni en denominador             |
| 5  | `test_indicator_importance_signos`  | Indicador con r<0 genera flag `signo_ok=False` en el resultado       |
| 6  | `test_vscore_pearson`               | Datos sintéticos con correlación perfecta → r≈1.0                   |
| 7  | `test_vscore_agrupacion_tramos`     | Registros en distintos tramos → tabla con N correcto por tramo       |
| 8  | `test_dscore_by_vix_tramos`         | VIX=12 → tramo "<15"; VIX=22 → tramo "20–25"                        |
| 9  | `test_warning_muestra_insuficiente` | N < mínimo del análisis → dict resultado incluye clave `warning`     |
| 10 | `test_run_analysis_sin_datos`       | history.jsonl vacío → `run_analysis` devuelve dict sin lanzar error  |

---

## Verificación end-to-end

```bash
# 1. Instalar scipy
uv add scipy

# 2. Ejecutar con datos reales (una vez history.jsonl tenga ≥20 días con outcome)
uv run python scripts/analyze_predictability.py

# 3. Ejecutar con guardado
uv run python scripts/analyze_predictability.py --save
# → outputs/predictability.json debe existir y ser JSON válido

# 4. Tests unitarios
uv run pytest tests/test_analyze_predictability.py -v

# 5. Suite completa
uv run pytest
```

---

## Fuera de scope

- **Análisis open phase**: usar `d_score_total` de registros `phase=open` — se añade
  en una iteración futura cuando haya suficiente historial de la fase open.
- **Rentabilidad de estrategias**: requiere pricing de opciones (segunda fase).
- **Comparación temporal**: gráficas de accuracy deslizante — herramienta de visualización
  fuera del alcance de un script CLI.
- **Calibración automática de pesos**: ajustar los pesos de los indicadores basándose
  en los coeficientes de A-02 — requiere un proceso de validación cruzada separado.
