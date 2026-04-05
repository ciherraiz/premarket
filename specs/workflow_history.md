# Spec: Workflow History — Trazabilidad de cálculos diarios

## Estado
[ ] Pendiente de implementación

## Propósito

Almacenar en disco todos los cálculos diarios (premarket + open phase) en un formato
plano y persistente para:

1. **Trazabilidad**: saber exactamente qué valores se calcularon cada día y cuándo.
2. **Evaluación de predictibilidad**: comparar la dirección predicha por D-Score con
   la dirección real del mercado, e.g. ¿el D-Score negativo premarket predijo un día bajista?
3. **Calibración**: identificar qué indicadores individuales tienen mayor poder predictivo
   y ajustar sus pesos.

El formato está diseñado para cargarse directamente en pandas:

```python
import pandas as pd
df = pd.read_json("logs/history.jsonl", lines=True)
```

---

## Archivo de almacenamiento

`logs/history.jsonl` — JSON Lines (una línea JSON por registro).

**Por qué JSONL:**
- Append-only: cada ejecución añade una línea, sin reescribir el fichero.
- Sin schema rígido: se pueden añadir columnas nuevas sin migrar datos históricos.
- `pd.read_json(lines=True)` lo carga en un DataFrame directamente.
- Human-readable e inspeccionable con cualquier editor.

El fichero `logs/history.jsonl` se acumula (nunca se sobreescribe). Un mismo día puede
tener hasta dos registros: uno con `phase="premarket"` y otro con `phase="open"`.

---

## Schema de registros

### Registro premarket

Un registro por cada ejecución de `--phase premarket`.

```json
{
  "fecha":              "2026-04-02",
  "phase":              "premarket",
  "timestamp":          "2026-04-02T13:10:42Z",

  "slope_vix":          23.87,
  "slope_vxv":          24.72,
  "slope_ratio":        0.9656,
  "slope_score":        -1,
  "slope_signal":       "TENSION",

  "ratio_vix9d":        21.71,
  "ratio_vix":          23.87,
  "ratio_value":        0.9095,
  "ratio_score":        0,
  "ratio_signal":       "NEUTRO",

  "gap_pct":            -0.3378,
  "gap_score":          -1,
  "gap_signal":         "GAP_BAJISTA",

  "gex_bn":             2.3389,
  "gex_score":          1,
  "gex_signal":         "LONG_GAMMA_SUAVE",

  "flip_level":         null,
  "flip_score":         0,
  "flip_signal":        "SIN_FLIP",

  "ivr":                26.76,
  "ivr_vix":            23.87,
  "ivr_score":          1,
  "ivr_signal":         "PRIMA_NORMAL",

  "atr_ratio":          1.0605,
  "atr_score":          0,
  "atr_signal":         "NEUTRO",

  "d_score":            -1,
  "v_score":            1,

  "spot":               6582.69,
  "put_wall":           null,
  "call_wall":          null,
  "max_pain":           null,

  "outcome_spx_close":       null,
  "outcome_spx_change_pct":  null,
  "outcome_direction":       null
}
```

### Registro open phase

Un registro por cada ejecución de `--phase open`.

```json
{
  "fecha":              "2026-04-02",
  "phase":              "open",
  "timestamp":          "2026-04-02T14:25:31Z",
  "window_minutes":     30,

  "vwap_value":         6580.5,
  "vwap_score":         1,
  "vwap_signal":        "SESGO_ALCISTA",

  "gap_beh_fill_pct":   10.0,
  "gap_beh_score":      2,
  "gap_beh_signal":     "GAP_BAJISTA_MANTENIDO",

  "vix_delta":          -0.5,
  "vix_delta_score":    1,
  "vix_delta_signal":   "IV_COMPRIMIENDO",

  "range_exp_ratio":    0.85,
  "range_exp_score":    0,
  "range_exp_signal":   "NEUTRO",

  "rv_ratio":           0.92,
  "rv_score":           0,
  "rv_signal":          "NEUTRO",

  "d_score_open":       3,
  "v_score_open":       1,

  "d_score_premarket":  -1,
  "v_score_premarket":  1,
  "d_score_total":      2,
  "v_score_total":      2,
  "strategy":           "Put spread OTM conservador",

  "spot_open":          6580.5,

  "outcome_spx_close":                  null,
  "outcome_spx_change_from_open_pct":   null,
  "outcome_direction":                  null
}
```

**Campos `outcome_*`:** se rellenan `null` en el momento del cálculo. Se actualizan
automáticamente al día siguiente durante el premarket (ver sección "Relleno de outcomes").

---

## Relleno de outcomes (automático)

El premarket fetch ya obtiene `es_prev_close` = cierre del ES del día anterior.
Este valor es la aproximación más inmediata y disponible del cierre de ayer.

### Flujo

```
Martes 09:10 ET — premarket corre:
  1. fetch es_prev_close  →  cierre del ES del lunes
  2. Buscar en history.jsonl los registros de ayer (fecha = lunes)
  3. Para cada registro de ayer encontrado:
       outcome_spx_close      = es_prev_close
       outcome_spx_change_pct = calculado según phase
       outcome_direction      = +1 / -1 / 0
  4. Reescribir history.jsonl con esos registros actualizados
  5. Añadir nuevo registro de hoy (martes) sin outcome
```

### Cálculo de outcome por phase

| Phase      | Fórmula change_pct                                        | direction         |
|------------|-----------------------------------------------------------|-------------------|
| premarket  | `(spx_close - spot) / spot × 100`                        | sign(change_pct)  |
| open       | `(spx_close - spot_open) / spot_open × 100`              | sign(change_pct)  |

Donde:
- `spot` = campo `spot` del registro premarket (precio SPX en momento del cálculo premarket).
- `spot_open` = campo `spot_open` del registro open (precio de apertura de la sesión a las 09:30 ET).
- `outcome_direction`: `+1` si subida, `-1` si bajada, `0` si sin movimiento.

### Limitaciones conocidas

- El outcome se rellena al **siguiente día hábil** en que corre el premarket.
- Si el premarket no corre un día (festivo, fallo), ese día queda sin outcome
  hasta el siguiente premarket exitoso.
- El último registro siempre queda sin outcome hasta el día siguiente.
- `es_prev_close` es el cierre de futuros ES, no exactamente el cierre SPX cash.
  Es la mejor aproximación disponible sin fetch adicional.

---

## Evaluación de predictibilidad (uso del historial)

Con el DataFrame cargado se pueden responder las siguientes preguntas:

### D-Score direccional (premarket)

```python
df_pre = df[df.phase == "premarket"].dropna(subset=["outcome_direction"])
df_pre["pred"] = df_pre["d_score"].apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
df_pre["hit"]  = df_pre["pred"] == df_pre["outcome_direction"]
print(df_pre["hit"].mean())                          # accuracy global
print(df_pre.groupby("pred")["hit"].mean())          # accuracy por régimen predicho
```

### Contribución individual de cada indicador

```python
from sklearn.linear_model import LogisticRegression
X = df_pre[["slope_score", "ratio_score", "gap_score", "gex_score", "flip_score"]]
y = (df_pre["outcome_direction"] == 1).astype(int)
model = LogisticRegression().fit(X, y)
print(dict(zip(X.columns, model.coef_[0])))          # importancia por indicador
```

### V-Score y volatilidad realizada

```python
df_pre["actual_move"] = df_pre["outcome_spx_change_pct"].abs()
df_pre.groupby(pd.cut(df_pre["v_score"], bins=[-3, -1, 1, 3, 6]))[
    "actual_move"].mean()                            # movimiento medio por rango de v_score
```

### D-Score combinado (open phase)

```python
df_open = df[df.phase == "open"].dropna(subset=["outcome_direction"])
df_open["pred_total"] = df_open["d_score_total"].apply(
    lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
df_open["hit"] = df_open["pred_total"] == df_open["outcome_direction"]
print(df_open["hit"].mean())
```

---

## Implementación

### Fichero nuevo: `scripts/log_history.py`

Contiene dos funciones públicas:

```python
def append_record(record: dict, path: Path = Path("logs/history.jsonl")) -> None:
    """Añade un registro al fichero JSONL. Crea el fichero si no existe."""

def fill_outcomes(es_prev_close: float, fecha_ayer: str,
                  path: Path = Path("logs/history.jsonl")) -> int:
    """
    Busca registros de fecha_ayer en history.jsonl y rellena los campos outcome_*.
    Devuelve el número de registros actualizados.
    Reescribe el fichero completo con los registros actualizados.
    """
```

### Cambios en `scripts/run.py`

**`run_premarket_phase()`:**
1. Importar `append_record`, `fill_outcomes` de `log_history`.
2. Calcular `fecha_ayer` a partir de la fecha del fetch (`data["fecha"]`) retrocediendo
   al día hábil anterior.
3. Tras obtener `es_prev_close`, llamar a `fill_outcomes(es_prev_close_value, fecha_ayer)`.
4. Al final de la función, construir el registro premarket plano y llamar a `append_record(record)`.
5. `timestamp = datetime.utcnow().isoformat(timespec="seconds") + "Z"`

**`run_open_phase()`:**
1. Al final, construir el registro open plano incluyendo `d_score_premarket` y
   `v_score_premarket` leídos de `premarket_ind`.
2. Incluir `spot_open = intraday.get("open_price")` en el registro.
3. Llamar a `append_record(record)`.

**Campo adicional en `open_indicators` (indicators.json):**

```python
open_indicators = {
    ...
    "spot_open": intraday.get("open_price"),   # ← necesario para fill_outcomes
}
```

### Construcción del registro premarket plano

```python
from datetime import datetime, timezone

record = {
    "fecha":         data.get("fecha"),
    "phase":         "premarket",
    "timestamp":     datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),

    "slope_vix":     slope.get("vix"),
    "slope_vxv":     slope.get("vxv"),
    "slope_ratio":   slope.get("ratio"),
    "slope_score":   slope.get("score"),
    "slope_signal":  slope.get("signal"),

    "ratio_vix9d":   ratio.get("vix9d"),
    "ratio_vix":     ratio.get("vix"),
    "ratio_value":   ratio.get("ratio"),
    "ratio_score":   ratio.get("score"),
    "ratio_signal":  ratio.get("signal"),

    "gap_pct":       gap.get("gap_pct"),
    "gap_score":     gap.get("score"),
    "gap_signal":    gap.get("signal"),

    "gex_bn":        net_gex.get("net_gex_bn"),
    "gex_score":     net_gex.get("score_gex"),
    "gex_signal":    net_gex.get("signal_gex"),

    "flip_level":    net_gex.get("flip_level"),
    "flip_score":    net_gex.get("score_flip"),
    "flip_signal":   net_gex.get("signal_flip"),

    "ivr":           ivr.get("ivr"),
    "ivr_vix":       ivr.get("vix"),
    "ivr_score":     ivr.get("score"),
    "ivr_signal":    ivr.get("signal"),

    "atr_ratio":     atr_ratio.get("atr_ratio"),
    "atr_score":     atr_ratio.get("score"),
    "atr_signal":    atr_ratio.get("signal"),

    "d_score":       d_score,
    "v_score":       v_score,

    "spot":          net_gex.get("spot"),
    "put_wall":      net_gex.get("put_wall"),
    "call_wall":     net_gex.get("call_wall"),
    "max_pain":      net_gex.get("max_pain"),

    "outcome_spx_close":      None,
    "outcome_spx_change_pct": None,
    "outcome_direction":      None,
}
```

### Construcción del registro open plano

```python
record = {
    "fecha":            intraday.get("fecha"),
    "phase":            "open",
    "timestamp":        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    "window_minutes":   window_minutes,

    "vwap_value":       vwap.get("value"),
    "vwap_score":       vwap.get("score"),
    "vwap_signal":      vwap.get("signal"),

    "gap_beh_fill_pct": gap_beh.get("gap_fill_pct"),
    "gap_beh_score":    gap_beh.get("score"),
    "gap_beh_signal":   gap_beh.get("signal"),

    "vix_delta":        vix_delta.get("vix_delta"),
    "vix_delta_score":  vix_delta.get("score"),
    "vix_delta_signal": vix_delta.get("signal"),

    "range_exp_ratio":  range_exp.get("ratio"),
    "range_exp_score":  range_exp.get("score"),
    "range_exp_signal": range_exp.get("signal"),

    "rv_ratio":         realized_vol.get("rv_ratio"),
    "rv_score":         realized_vol.get("score"),
    "rv_signal":        realized_vol.get("signal"),

    "d_score_open":       d_score_open,
    "v_score_open":       v_score_open,

    "d_score_premarket":  premarket_ind.get("d_score"),
    "v_score_premarket":  premarket_ind.get("v_score"),
    "d_score_total":      (premarket_ind.get("d_score") or 0) + d_score_open,
    "v_score_total":      (premarket_ind.get("v_score") or 0) + v_score_open,
    "strategy":           _interpret_strategy(
                              (premarket_ind.get("d_score") or 0) + d_score_open,
                              (premarket_ind.get("v_score") or 0) + v_score_open
                          ),

    "spot_open":          intraday.get("open_price"),

    "outcome_spx_close":                None,
    "outcome_spx_change_from_open_pct": None,
    "outcome_direction":                None,
}
```

Nota: `_interpret_strategy` replica la tabla de decisión de `generate_scorecard.py`
(ya existe como `_interpret` en `notify_telegram.py` — reusar o mover a un módulo común).

---

## Ficheros a modificar / crear

| Acción     | Fichero                         | Cambio                                                   |
|------------|---------------------------------|----------------------------------------------------------|
| Crear      | `scripts/log_history.py`        | Módulo con `append_record` y `fill_outcomes`             |
| Crear      | `tests/test_log_history.py`     | 8 tests unitarios                                        |
| Modificar  | `scripts/run.py`                | Importar y llamar log_history en ambas fases             |

---

## Tests requeridos (`tests/test_log_history.py`)

| #  | Test                                    | Qué verifica                                              |
|----|-----------------------------------------|-----------------------------------------------------------|
| 1  | `test_append_crea_fichero`              | Si no existe el fichero, se crea al hacer append          |
| 2  | `test_append_añade_linea`               | Cada append añade exactamente una línea                   |
| 3  | `test_append_multiples_registros`       | N appends → N líneas, cada una JSON válido                |
| 4  | `test_fill_outcomes_rellena_fecha`      | fill_outcomes actualiza los campos outcome_*              |
| 5  | `test_fill_outcomes_no_toca_otras_fechas` | Solo modifica registros de fecha_ayer                   |
| 6  | `test_fill_outcomes_sin_registros`      | Devuelve 0 si no hay registros de esa fecha               |
| 7  | `test_fill_outcomes_calcula_direction`  | direction=+1 si spx_close > spot, -1 si menor, 0 si igual|
| 8  | `test_pandas_compatible`                | `pd.read_json(lines=True)` carga correctamente N filas    |

---

## Verificación end-to-end

```bash
# 1. Ejecutar premarket
uv run python scripts/run.py --phase premarket

# 2. Verificar que se creó logs/history.jsonl con un registro
python -c "
import json
with open('logs/history.jsonl') as f:
    for line in f:
        print(json.dumps(json.loads(line), indent=2))
"

# 3. Ejecutar open phase
uv run python scripts/run.py --phase open --window 30

# 4. Verificar que hay dos registros
python -c "print(sum(1 for _ in open('logs/history.jsonl')))"  # debe ser 2

# 5. Simular premarket del día siguiente pasando un es_prev_close ficticio
# → outcome_* del día anterior deben rellenarse automáticamente

# 6. Cargar en pandas y verificar schema completo
python -c "
import pandas as pd
df = pd.read_json('logs/history.jsonl', lines=True)
print(df.shape)
print(df.columns.tolist())
print(df[['fecha','phase','d_score','v_score','outcome_direction']])
"

# 7. Tests unitarios
uv run pytest tests/test_log_history.py -v
```

---

## Fuera de scope

- **Deduplicación**: si el pipeline corre dos veces el mismo día, habrá dos líneas con la
  misma `fecha` y `phase`. Se resuelve en el análisis filtrando por `timestamp` más reciente.
- **Días sin premarket**: si el premarket no corre (festivo, fallo), los outcomes de ese
  día se rellenarán en el siguiente premarket exitoso.
- **Base de datos SQL o Parquet**: el formato JSONL es suficiente para el volumen actual
  (~250 registros/año). Migración futura posible sin perder datos.
- **Rentabilidad de estrategias**: requiere pricing de opciones (segunda fase).
