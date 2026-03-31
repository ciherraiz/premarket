# Spec: IND-OPEN-05 — Gap Behavior

## Estado
[ ] Pendiente de implementación

## Propósito

Indicador D-Score de la Open Phase. Mide si el gap de apertura del SPX —la diferencia
entre el cierre del día anterior y el precio de apertura de la sesión actual— se está
manteniendo o rellenando durante la ventana post-open.

**Fórmulas centrales:**

```
gap_pct      = (open_price - prev_close) / prev_close × 100
gap_fill_pct = (open_price - last_close) / (open_price - prev_close) × 100
```

Donde:
- `prev_close`  = cierre SPX del día anterior (de `premarket_indicators["spx_prev_close"]`)
- `open_price`  = precio de apertura del SPX a las 09:30 ET (`spx_intraday["open_price"]`)
- `last_close`  = cierre de la última vela de la ventana

`gap_fill_pct` mide qué proporción del movimiento inicial ha sido revertida:
- `0 %`   → el precio está exactamente en el open (gap intacto)
- `100 %` → el precio ha vuelto exactamente al prev_close (gap totalmente rellenado)
- `> 100 %` → el precio ha cruzado el prev_close (gap sobrerrellenado)
- `< 0 %`   → el precio se ha alejado aún más del prev_close (gap amplificado)

Las fórmulas funcionan simétricamente para gaps alcistas (`open > prev_close`) y bajistas
(`open < prev_close`) porque el signo de `(open_price - prev_close)` preserva la dirección.

**Hipótesis de trading:**

Un gap que se mantiene abierto (`fill_pct < 25 %`) indica convicción institucional en la
dirección del gap → refuerza la señal de un spread direccional.
Un gap que se rellena rápidamente (`fill_pct ≥ 75 %`) neutraliza el argumento: el mercado
rechaza el movimiento inicial y no debe usarse como argumento direccional.
Gaps por debajo de ±0.15 % son ruido estadístico normal y se ignoran.

**Dependencia inter-fase:** necesita `spx_prev_close` del premarket, persistido en
`indicators.json` bajo la clave `premarket.spx_prev_close`. Este valor ya se calcula
en `run_premarket_phase()` como `spx_spot` (último cierre de `fetch_spx_ohlcv()`)
pero debe añadirse explícitamente al dict `premarket_indicators` para que quede
guardado en `indicators.json`:

```python
# scripts/run.py — run_premarket_phase() (cambio necesario antes de implementar)
premarket_indicators = {
    ...
    "spx_prev_close": spx_spot,   # ← nueva clave para inter-fase
}
```

Si `spx_prev_close` es `None` o `0`, la función devuelve score neutro con
`signal="ERROR_PREV_CLOSE_NO_DISPONIBLE"` en lugar de producir un resultado silenciosamente
incorrecto.

---

## Ubicación en el proyecto

```
scripts/calculate_open_indicators.py   ← función calc_gap_behavior()
tests/test_ind_open_gap_behavior.py    ← tests unitarios (13 tests)
```

Sigue las mismas convenciones que el resto de `calculate_open_indicators.py`.

Se integrará en `scripts/run.py` → `run_open_phase()`. El resultado se guardará en
`outputs/indicators.json` bajo la clave `open.gap_behavior`.

---

## Constantes configurables

En la sección de constantes al inicio de `scripts/calculate_open_indicators.py`:

```python
GAP_MIN_PCT      = 0.15   # |gap_pct| < umbral → GAP_INSIGNIFICANTE (ruido)
GAP_MANTIENE_PCT = 25.0   # gap_fill_pct < 25 % → gap mantenido → score ±2
GAP_NEUTRO_PCT   = 75.0   # gap_fill_pct ≥ 75 % → gap rellenado → score 0
```

---

## Contrato de la función

### Firma

```python
def calc_gap_behavior(spx_intraday: dict, premarket_indicators: dict) -> dict:
```

### Input `spx_intraday`

Dict devuelto por `fetch_spx_intraday()`. Campos usados:

| Campo            | Tipo       | Descripción                                      |
|------------------|------------|--------------------------------------------------|
| `ohlcv`          | list[dict] | Barras 1-minuto con columnas capitalizadas        |
| `open_price`     | float      | Precio de apertura del SPX a las 09:30 ET         |
| `window_minutes` | int        | Minutos esperados de ventana                     |
| `fecha`          | str        | Fecha de la sesión (YYYY-MM-DD)                  |
| `status`         | str        | "OK" o "ERROR"; si es ERROR se propaga           |

Estructura de cada registro en `ohlcv`:

```python
{
    "Datetime": str,    # "2026-03-31 09:30:00-04:00"
    "Open":     float,
    "High":     float,
    "Low":      float,
    "Close":    float,
    "Volume":   int,
}
```

### Input `premarket_indicators`

Sección `premarket` de `outputs/indicators.json`. Campo usado:

| Campo            | Tipo  | Descripción                                       |
|------------------|-------|---------------------------------------------------|
| `spx_prev_close` | float | Cierre SPX del día anterior (de `fetch_spx_ohlcv`) |

La función falla con `ERROR_PREV_CLOSE_NO_DISPONIBLE` si el campo es `None`, `0` o
no está presente.

### Output

```python
{
    "gap_pct":           float | None,   # (open - prev_close) / prev_close × 100, 4 dec
    "gap_fill_pct":      float | None,   # % del gap rellenado, 4 dec (puede ser <0 o >100)
    "gap_direction":     str | None,     # "UP" | "DOWN" | "NONE"
    "prev_close":        float | None,   # cierre SPX del día anterior
    "open_price":        float | None,   # precio de apertura SPX
    "last_close":        float | None,   # último close de la ventana
    "candles_used":      int,
    "incomplete_window": bool,           # True si n < window_minutes × 0.5
    "score":             int,            # −2 / −1 / 0 / +1 / +2
    "signal":            str,
    "status":            str,            # "OK" | "ERROR"
    "fecha":             str | None,
}
```

---

## Cálculo paso a paso

### Paso 1: Validaciones previas

```python
if spx_intraday["status"] != "OK"          → ERROR_FETCH
if ohlcv vacío o ausente                   → ERROR_SIN_DATOS
if falta columna "Close"                   → ERROR_COLUMNAS
if open_price is None                      → ERROR_SPX_OPEN_NULO
if prev_close is None or prev_close == 0   → ERROR_PREV_CLOSE_NO_DISPONIBLE
```

### Paso 2: Tamaño del gap

```python
gap_pts = open_price - prev_close
gap_pct = round(gap_pts / prev_close * 100, 4)
```

### Paso 3: Filtro de ruido

```python
if abs(gap_pct) < GAP_MIN_PCT:   # < 0.15 %
    → score=0, signal="GAP_INSIGNIFICANTE", gap_direction="NONE", status="OK"
```

El cálculo se interrumpe aquí y se devuelve el resultado. `gap_fill_pct` queda `None`.

### Paso 4: Dirección del gap

```python
gap_direction = "UP" if gap_pts > 0 else "DOWN"
```

### Paso 5: Porcentaje de relleno

```python
last_close   = float(df["Close"].iloc[-1])
gap_fill_pct = round((open_price - last_close) / gap_pts * 100, 4)
```

La fórmula es simétrica: para un gap UP (`gap_pts > 0`), `gap_fill_pct` positivo indica
que el precio bajó desde el open (relleno); para un gap DOWN (`gap_pts < 0`), el signo
negativo del denominador invierte correctamente la dirección.

### Paso 6: Scoring

| Dirección | Condición sobre `gap_fill_pct`                    | Score | Signal                 |
|-----------|---------------------------------------------------|-------|------------------------|
| UP        | `< GAP_MANTIENE_PCT` (< 25.0)                     | +2    | GAP_ALCISTA_MANTENIDO  |
| UP        | `GAP_MANTIENE_PCT ≤ x < GAP_NEUTRO_PCT` (25–75)  | +1    | GAP_ALCISTA_PARCIAL    |
| UP        | `≥ GAP_NEUTRO_PCT` (≥ 75.0)                       |  0    | GAP_ALCISTA_RELLENO    |
| DOWN      | `< GAP_MANTIENE_PCT` (< 25.0)                     | −2    | GAP_BAJISTA_MANTENIDO  |
| DOWN      | `GAP_MANTIENE_PCT ≤ x < GAP_NEUTRO_PCT` (25–75)  | −1    | GAP_BAJISTA_PARCIAL    |
| DOWN      | `≥ GAP_NEUTRO_PCT` (≥ 75.0)                       |  0    | GAP_BAJISTA_RELLENO    |

Los umbrales son **estrictos**: `fill == 25.0` → parcial (no mantenido);
`fill == 75.0` → rellenado (no parcial).

Valores de `gap_fill_pct` fuera de [0, 100] son válidos y funcionan correctamente:
- `fill < 0` (gap amplificado) → cumple `< 25` → señal mantenida (score ±2)
- `fill > 100` (sobrerrellenado) → cumple `≥ 75` → señal neutralizada (score 0)

---

## Señales de error

| Signal                          | Causa                                               |
|---------------------------------|-----------------------------------------------------|
| `ERROR_FETCH`                   | `spx_intraday["status"] != "OK"`                    |
| `ERROR_SIN_DATOS`               | `ohlcv` vacío o ausente                             |
| `ERROR_COLUMNAS`                | Falta columna `Close`                               |
| `ERROR_SPX_OPEN_NULO`           | `open_price` es `None`                              |
| `ERROR_PREV_CLOSE_NO_DISPONIBLE`| `spx_prev_close` es `None` o `0`                    |

En todos los casos: `score=0`, `status="ERROR"`.

---

## Validaciones y edge cases

### Ventana incompleta (< 50 % velas esperadas)
Calcular igualmente con las velas disponibles. Incluir `"incomplete_window": True`.

### Gap insignificante (`|gap_pct| < 0.15 %`)
`score=0`, `signal="GAP_INSIGNIFICANTE"`, `gap_direction="NONE"`, `status="OK"`,
`gap_fill_pct=None`. No es un error — es información válida (no hay gap relevante).

### Gap sobrerrellenado (`gap_fill_pct > 100 %`)
El precio cruzó `prev_close`. La condición `≥ 75 %` se satisface → `score=0`,
`signal="GAP_*_RELLENO"`. No es un error.

### Gap amplificado (`gap_fill_pct < 0 %`)
El precio se alejó aún más de `prev_close`. La condición `< 25 %` se satisface → `score=±2`,
`signal="GAP_*_MANTENIDO"`. Señal más fuerte que un gap simplemente mantenido.

---

## Implementación (pseudocódigo)

```python
import pandas as pd

GAP_MIN_PCT      = 0.15
GAP_MANTIENE_PCT = 25.0
GAP_NEUTRO_PCT   = 75.0


def calc_gap_behavior(spx_intraday: dict, premarket_indicators: dict) -> dict:
    base = {
        "gap_pct": None, "gap_fill_pct": None, "gap_direction": None,
        "prev_close": None, "open_price": None, "last_close": None,
        "candles_used": 0, "incomplete_window": False,
        "score": 0, "signal": "NEUTRO",
        "status": "OK", "fecha": spx_intraday.get("fecha"),
    }

    if spx_intraday.get("status") != "OK":
        base.update({"status": "ERROR", "signal": "ERROR_FETCH"})
        return base

    records = spx_intraday.get("ohlcv") or []
    if not records:
        base.update({"status": "ERROR", "signal": "ERROR_SIN_DATOS"})
        return base

    df = pd.DataFrame(records)
    if "Close" not in df.columns:
        base.update({"status": "ERROR", "signal": "ERROR_COLUMNAS"})
        return base

    open_price = spx_intraday.get("open_price")
    if open_price is None:
        base.update({"status": "ERROR", "signal": "ERROR_SPX_OPEN_NULO"})
        return base

    prev_close = premarket_indicators.get("spx_prev_close")
    if not prev_close:   # None o 0
        base.update({"status": "ERROR", "signal": "ERROR_PREV_CLOSE_NO_DISPONIBLE"})
        return base

    window_minutes = spx_intraday.get("window_minutes", 30)
    n = len(df)
    base["candles_used"] = n
    if n < window_minutes * 0.5:
        base["incomplete_window"] = True

    base["prev_close"] = prev_close
    base["open_price"] = open_price

    gap_pts = open_price - prev_close
    gap_pct = round(gap_pts / prev_close * 100, 4)
    base["gap_pct"] = gap_pct

    last_close = round(float(df["Close"].iloc[-1]), 2)
    base["last_close"] = last_close

    if abs(gap_pct) < GAP_MIN_PCT:
        base["signal"]        = "GAP_INSIGNIFICANTE"
        base["gap_direction"] = "NONE"
        return base

    gap_direction = "UP" if gap_pts > 0 else "DOWN"
    base["gap_direction"] = gap_direction

    gap_fill_pct = round((open_price - last_close) / gap_pts * 100, 4)
    base["gap_fill_pct"] = gap_fill_pct

    if gap_direction == "UP":
        if gap_fill_pct < GAP_MANTIENE_PCT:
            base["score"]  = 2
            base["signal"] = "GAP_ALCISTA_MANTENIDO"
        elif gap_fill_pct < GAP_NEUTRO_PCT:
            base["score"]  = 1
            base["signal"] = "GAP_ALCISTA_PARCIAL"
        else:
            base["score"]  = 0
            base["signal"] = "GAP_ALCISTA_RELLENO"
    else:  # DOWN
        if gap_fill_pct < GAP_MANTIENE_PCT:
            base["score"]  = -2
            base["signal"] = "GAP_BAJISTA_MANTENIDO"
        elif gap_fill_pct < GAP_NEUTRO_PCT:
            base["score"]  = -1
            base["signal"] = "GAP_BAJISTA_PARCIAL"
        else:
            base["score"]  = 0
            base["signal"] = "GAP_BAJISTA_RELLENO"

    return base
```

---

## Tests requeridos

Archivo: `tests/test_ind_open_gap_behavior.py`

Helpers:
- `_make_intraday(last_close, open_price, window_minutes, status)` — construye dict
  compatible con `fetch_spx_intraday()` con una sola vela cuyo `Close` es `last_close`
- `_make_premarket(spx_prev_close)` — devuelve `{"spx_prev_close": spx_prev_close}`

Valores de referencia para tests alcistas (1–3, 8–10, 13):
```
prev_close = 5000.00,  open_price = 5020.00
gap_pts = +20,  gap_pct = +0.4000 %
gap_fill_pct = (5020 - last_close) / 20 × 100
```

Valores de referencia para tests bajistas (4–6):
```
prev_close = 5020.00,  open_price = 5000.00
gap_pts = −20,  gap_pct = (5000−5020)/5020 × 100 = −0.3984 %
gap_fill_pct = (5000 − last_close) / (−20) × 100
```

| #  | Nombre del test                             | Condición                                   | Resultado esperado                   |
|----|---------------------------------------------|---------------------------------------------|--------------------------------------|
| 1  | `test_gap_alcista_mantenido`                | UP gap, last_close=5018 → fill=10 %         | score=+2, GAP_ALCISTA_MANTENIDO      |
| 2  | `test_gap_alcista_parcial`                  | UP gap, last_close=5010 → fill=50 %         | score=+1, GAP_ALCISTA_PARCIAL        |
| 3  | `test_gap_alcista_relleno`                  | UP gap, last_close=5004 → fill=80 %         | score=0,  GAP_ALCISTA_RELLENO        |
| 4  | `test_gap_bajista_mantenido`                | DOWN gap, last_close=5002 → fill=10 %       | score=−2, GAP_BAJISTA_MANTENIDO      |
| 5  | `test_gap_bajista_parcial`                  | DOWN gap, last_close=5010 → fill=50 %       | score=−1, GAP_BAJISTA_PARCIAL        |
| 6  | `test_gap_bajista_relleno`                  | DOWN gap, last_close=5016 → fill=80 %       | score=0,  GAP_BAJISTA_RELLENO        |
| 7  | `test_gap_insignificante_por_debajo_umbral` | \|gap_pct\| = 0.10 % < 0.15 %              | score=0,  GAP_INSIGNIFICANTE         |
| 8  | `test_gap_exactamente_umbral_minimo`        | \|gap_pct\| = 0.15 % exacto (umbral <)     | score≠0 (gap significativo)          |
| 9  | `test_umbral_mantiene_exacto`               | UP gap, fill=25.0 % exacto (umbral <)       | score=+1, GAP_ALCISTA_PARCIAL        |
| 10 | `test_umbral_neutro_exacto`                 | UP gap, fill=75.0 % exacto (umbral <)       | score=0,  GAP_ALCISTA_RELLENO        |
| 11 | `test_error_prev_close_none`                | spx_prev_close=None                         | status=ERROR, score=0                |
| 12 | `test_error_prev_close_cero`                | spx_prev_close=0                            | status=ERROR, score=0                |
| 13 | `test_gap_alcista_sobrerellenado`           | UP gap, last_close=4998 → fill=110 % (>100) | score=0,  GAP_ALCISTA_RELLENO        |

---

## Integración prevista en run_open_phase()

```python
# scripts/run.py — ajustes necesarios al implementar

# 1. Importar la nueva función
from calculate_open_indicators import (
    calc_vwap_position, calc_vix_delta_open, calc_range_expansion,
    calc_gap_behavior,   # ← añadir
)

# 2. En run_open_phase(), tras leer premarket_ind:
gap_beh = calc_gap_behavior(intraday, premarket_ind)   # ← añadir

# 3. Incluir en d_score y en el dict de salida:
d_score_open = vwap["score"] + gap_beh["score"]        # ← añadir gap_beh al D-Score
open_indicators = {
    ...
    "gap_behavior": gap_beh,                            # ← añadir
    "d_score": d_score_open,
}
```

Log de ejecución previsto:
```
[calc-open] gap_behavior=GAP_ALCISTA_MANTENIDO(+2)  gap_pct=+0.4000%  fill=10.0000%
```

---

## Fuera de scope

- Gaps pre-market extendidos (overnight futures move): solo se mide el gap SPX vs SPX
- Comparar el gap actual con gaps históricos (sin percentil ni z-score)
- Análisis de gaps de sesiones anteriores
- Considerar el volumen durante el relleno como señal adicional
