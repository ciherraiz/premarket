# Spec: IND-OPEN-06 — Realized Volatility Open

## Estado
[ ] Pendiente de implementación

---

## Propósito

Indicador V-Score de la Open Phase. Mide si la volatilidad realizada durante los primeros
minutos de sesión está por encima o por debajo de la volatilidad implícita que el mercado
de opciones había fijado antes de la apertura.

**Fórmulas centrales:**

```
log_returns  = log(close[i] / close[i-1])   para i en 1..n-1
rv_1m        = std(log_returns, ddof=1) × sqrt(252 × 390)   # RV anualizada, decimal
iv_daily     = VIX / 100                                     # IV diaria, decimal
rv_ratio     = rv_1m / iv_daily
```

El factor `sqrt(252 × 390)` anualiza la desviación estándar de log-returns de 1 minuto:
- 252 días de trading al año
- 390 minutos de trading por día (misma constante `TRADING_MINUTES_DAY` del módulo)

**Interpretación del ratio:**

| rv_ratio | Significado |
|----------|-------------|
| = 1.0 | El mercado se mueve exactamente a la velocidad que la IV predecía |
| = 0.5 | El mercado se mueve a la mitad de la velocidad esperada → opciones caras |
| = 1.5 | El mercado se mueve un 50% más rápido de lo esperado → opciones baratas |

**Hipótesis de trading:**

| rv_ratio | Score | Signal | Interpretación |
|----------|-------|--------|----------------|
| < 0.8 | +2 | PRIMA_SOBREVALORADA | RV baja vs IV → opciones caras → favorable para vender premium |
| 0.8 ≤ ratio ≤ 1.2 | 0 | NEUTRO | RV en línea con IV → entorno ambiguo |
| > 1.2 | −2 | PRIMA_INFRAVALORADA | RV alta vs IV → opciones baratas → peligroso vender premium |

Un ratio bajo confirma intraday que el entorno de baja volatilidad realizada es coherente
con el IVR elevado del premarket: las dos métricas apuntan al mismo entorno de prima alta.
Un ratio alto puede indicar un evento de volatilidad que hace que las opciones estén
relativamente baratas respecto al movimiento actual.

**Dependencia inter-fase:** necesita el VIX del premarket, guardado en `indicators.json`
bajo `premarket.ivr.vix` con fallback a `premarket.vix_vxv_slope.vix`. La función lo
recibe como parámetro `premarket_indicators`. Misma convención que `calc_range_expansion`.

---

## Ubicación en el proyecto

```
scripts/calculate_open_indicators.py   ← función calc_realized_vol_open()
tests/test_ind_open_realized_vol.py    ← tests unitarios (14 tests)
```

Se integrará en `scripts/run.py` → `run_open_phase()`. El resultado se guardará en
`outputs/indicators.json` bajo la clave `open.realized_vol_open`.

---

## Constantes configurables

En la sección de constantes al inicio de `scripts/calculate_open_indicators.py`:

```python
RV_OPEN_MIN_CANDLES = 5     # mínimo de closes para calcular (< 5 → INSUFFICIENT_DATA)
RV_OPEN_RATIO_BAJO  = 0.8   # rv_ratio < → PRIMA_SOBREVALORADA → score +2
RV_OPEN_RATIO_ALTO  = 1.2   # rv_ratio > → PRIMA_INFRAVALORADA → score -2
```

El factor de anualización se calcula en línea como `math.sqrt(252 * TRADING_MINUTES_DAY)`,
reutilizando la constante `TRADING_MINUTES_DAY = 390` ya definida en el módulo.

---

## Contrato de la función

### Firma

```python
def calc_realized_vol_open(spx_intraday: dict, premarket_indicators: dict) -> dict:
```

### Input `spx_intraday`

Dict devuelto por `fetch_spx_intraday()`. Campos usados:

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `ohlcv` | list[dict] | Barras 1-minuto con columnas capitalizadas |
| `window_minutes` | int | Minutos esperados de ventana |
| `fecha` | str | Fecha de la sesión (YYYY-MM-DD) |
| `status` | str | "OK" o "ERROR"; si es ERROR se propaga |

Solo se usa la columna `Close`. Las demás se ignoran pero deben estar presentes.

### Input `premarket_indicators`

Sección `premarket` de `outputs/indicators.json`. Campos usados:

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `ivr.vix` | float | Nivel VIX del premarket (fuente primaria) |
| `vix_vxv_slope.vix` | float | VIX alternativo (fallback si `ivr.vix` es None) |

### Output

```python
{
    "rv_1m":        float | None,   # RV anualizada en decimal (ej. 0.152 = 15.2%)
    "iv_daily":     float | None,   # IV del VIX en decimal (ej. 0.160 = 16%)
    "rv_ratio":     float | None,   # rv_1m / iv_daily, redondeado a 4 decimales
    "candles_used": int,            # número de closes usados
    "score":        int,            # −2 / 0 / +2
    "signal":       str,            # PRIMA_SOBREVALORADA | NEUTRO | PRIMA_INFRAVALORADA
    "status":       str,            # OK | ERROR | INSUFFICIENT_DATA | MISSING_DATA
    "fecha":        str | None,     # YYYY-MM-DD
}
```

Este indicador no incluye `incomplete_window` porque el criterio de calidad es
el número mínimo absoluto de closes (`RV_OPEN_MIN_CANDLES`), no un porcentaje
de la ventana esperada.

---

## Cálculo paso a paso

### Paso 1: Validaciones previas

```
si spx_intraday["status"] != "OK"  → status=ERROR, signal=ERROR_FETCH, score=0
si ohlcv vacío o ausente           → status=ERROR, signal=ERROR_FETCH, score=0
si falta columna "Close"           → status=ERROR, signal=ERROR_FETCH, score=0
si n_closes < RV_OPEN_MIN_CANDLES  → status=INSUFFICIENT_DATA, signal=INSUFFICIENT_DATA, score=0
```

`candles_used` se fija a `n_closes` antes de la validación de mínimo para que el
test pueda verificar el valor incluso en el caso `INSUFFICIENT_DATA`.

### Paso 2: Obtener IV del premarket

```python
vix = premarket_indicators["ivr"]["vix"]          # fuente primaria
if vix is None:
    vix = premarket_indicators["vix_vxv_slope"]["vix"]   # fallback
if vix is None:
    → status=MISSING_DATA, signal=IV_NO_DISPONIBLE, score=0

iv_daily = vix / 100
if iv_daily == 0:
    → status=ERROR, signal=ERROR_CALCULO, score=0
```

### Paso 3: Calcular log-returns

```python
log_returns = [math.log(closes[i] / closes[i-1]) for i in range(1, n)]
```

### Paso 4: Desviación estándar y anualización

```python
std_lr   = pd.Series(log_returns).std(ddof=1)          # muestral
rv_1m    = std_lr * math.sqrt(252 * TRADING_MINUTES_DAY)
rv_ratio = round(rv_1m / iv_daily, 4)
```

Closes completamente flat (`std_lr = 0`) producen `rv_ratio = 0.0`.
Eso es un resultado válido (baja volatilidad extrema), no un error.
`rv_ratio = 0.0 < RV_OPEN_RATIO_BAJO` → score=+2, PRIMA_SOBREVALORADA.

### Paso 5: Scoring

```python
if rv_ratio < RV_OPEN_RATIO_BAJO:     # < 0.8  (estricto)
    score = +2;  signal = "PRIMA_SOBREVALORADA"
elif rv_ratio > RV_OPEN_RATIO_ALTO:   # > 1.2  (estricto)
    score = -2;  signal = "PRIMA_INFRAVALORADA"
else:                                  # 0.8 ≤ ratio ≤ 1.2
    score = 0;   signal = "NEUTRO"
```

Los umbrales son **estrictos**: `rv_ratio == 0.8` o `rv_ratio == 1.2` → score=0, NEUTRO.

---

## Tabla de scoring

| Condición | Score | Signal |
|-----------|-------|--------|
| `rv_ratio < RV_OPEN_RATIO_BAJO` (< 0.8) | +2 | PRIMA_SOBREVALORADA |
| `RV_OPEN_RATIO_BAJO ≤ rv_ratio ≤ RV_OPEN_RATIO_ALTO` | 0 | NEUTRO |
| `rv_ratio > RV_OPEN_RATIO_ALTO` (> 1.2) | −2 | PRIMA_INFRAVALORADA |

---

## Señales de error y status

| Status | Signal | Causa |
|--------|--------|-------|
| `ERROR` | `ERROR_FETCH` | `spx_intraday["status"] != "OK"`, ohlcv vacío o ausente, falta columna Close |
| `INSUFFICIENT_DATA` | `INSUFFICIENT_DATA` | Menos de `RV_OPEN_MIN_CANDLES` (5) closes |
| `MISSING_DATA` | `IV_NO_DISPONIBLE` | VIX es None en `ivr.vix` y en `vix_vxv_slope.vix` |
| `ERROR` | `ERROR_CALCULO` | `iv_daily == 0` (VIX = 0) |

En todos los casos de error: `score=0`, campos de cálculo (`rv_1m`, `iv_daily`, `rv_ratio`) = None.

---

## Validaciones y edge cases

### Mínimo de velas (< 5 closes)
Se necesitan al menos 4 log-returns, lo que requiere 5 closes.
Con < 5 closes → `INSUFFICIENT_DATA`. La validación ocurre **después** de verificar
el status del fetch y la existencia de la columna Close, pero **antes** de buscar el VIX.

### Closes completamente flat
`closes = [5200.0] * n` → todos los log-returns son 0.0 → `std_lr = 0` → `rv_1m = 0.0`
→ `rv_ratio = 0.0` → score=+2, PRIMA_SOBREVALORADA. No es un error: es el caso extremo
de baja volatilidad realizada (el mercado no se movió durante la ventana).

### División por cero (VIX = 0)
`iv_daily = 0` → `status=ERROR, signal=ERROR_CALCULO`. Esta situación no puede ocurrir
con datos reales pero se protege para robustez.

### IV fallback
Si `ivr.vix` es None, la función intenta `vix_vxv_slope.vix`. Solo si ambos son None
se devuelve `MISSING_DATA`. El test `test_iv_fallback_vix_vxv_slope` cubre el éxito
del fallback.

### Nota sobre `incomplete_window`
Este indicador no expone `incomplete_window` en el output porque su criterio de
validez es un mínimo absoluto de closes (5), no relativo a la ventana esperada.
Con exactamente 5 closes el resultado es estadísticamente marginal pero válido.

---

## Tests requeridos

Fichero: `tests/test_ind_open_realized_vol.py`

Helpers:
- `_make_intraday(closes, window_minutes, status)` — construye dict `fetch_spx_intraday()`
- `_make_premarket(vix)` — devuelve `{"ivr": {"vix": vix, "status": "OK"}}`
- `_closes_for_target_ratio(target_ratio, vix, n, base)` — serie alternante `±r` cuya
  std = r, de modo que el rv_ratio resultante ≈ target_ratio

| # | Nombre del test | Condición | Resultado esperado |
|---|-----------------|-----------|-------------------|
| 1 | `test_score_positivo_ratio_bajo` | rv_ratio ≈ 0.4 | score=+2, PRIMA_SOBREVALORADA, status=OK |
| 2 | `test_score_negativo_ratio_alto` | rv_ratio ≈ 1.8 | score=−2, PRIMA_INFRAVALORADA, status=OK |
| 3 | `test_score_neutro_ratio_medio` | rv_ratio ≈ 1.0 | score=0, NEUTRO, status=OK |
| 4 | `test_umbral_inferior_exacto_score_neutro` | rv_ratio == 0.8 exacto | score=0, NEUTRO |
| 5 | `test_umbral_superior_exacto_score_neutro` | rv_ratio == 1.2 exacto | score=0, NEUTRO |
| 6 | `test_fetch_fallido_propaga_error` | status=ERROR en intraday | status=ERROR, signal=ERROR_FETCH, score=0 |
| 7 | `test_sin_velas_lista_vacia` | ohlcv=[] | status=ERROR, signal=ERROR_FETCH, score=0 |
| 8 | `test_columna_close_faltante` | registros sin campo "Close" | status=ERROR, signal=ERROR_FETCH, score=0 |
| 9 | `test_menos_de_cinco_velas_insuficiente` | 4 closes | status=INSUFFICIENT_DATA, candles_used=4 |
| 10 | `test_exactamente_cinco_velas_calcula` | 5 closes | status=OK, score in {−2, 0, +2} |
| 11 | `test_iv_no_disponible_ambos_none` | ivr.vix=None y vix_vxv.vix=None | status=MISSING_DATA, IV_NO_DISPONIBLE |
| 12 | `test_iv_fallback_vix_vxv_slope` | ivr.vix=None, vix_vxv.vix=16.0 | status=OK, iv_daily=0.16 |
| 13 | `test_verificacion_aritmetica` | closes lineales + VIX=20 | rv_1m, iv_daily, rv_ratio exactos |
| 14 | `test_closes_flat_score_positivo` | closes idénticos → rv_ratio=0.0 | score=+2, PRIMA_SOBREVALORADA |

---

## Integración prevista

### `scripts/run.py`

```python
# Import (línea 27)
from calculate_open_indicators import (
    calc_vwap_position, calc_vix_delta_open, calc_range_expansion,
    calc_gap_behavior, calc_realized_vol_open,
)

# En run_open_phase(), tras gap_beh:
realized_vol = calc_realized_vol_open(intraday, premarket_ind)

# v_score_open:
v_score_open = vix_delta["score"] + range_exp["score"] + realized_vol["score"]

# open_indicators dict:
"realized_vol_open": realized_vol,
```

### `scripts/generate_scorecard.py`

Añadir fila "Realized Vol" en el bloque OPEN PHASE - V-SCORE, tras Range Expansion:

```python
rv_open = open_phase.get("realized_vol_open", {})
if rv_open:
    if rv_open.get("status") == "OK":
        ratio_val = rv_open.get("rv_ratio")
        rv_val = f"rv_ratio={ratio_val:.4f}" if ratio_val is not None else "-"
    else:
        rv_val = f"[{rv_open.get('status','ERROR')}]"
    print(f"  {'Realized Vol':<20} {rv_val:<26} {_sign(rv_open.get('score',0)):<6} {rv_open.get('signal','N/A')}")

# Actualizar guarda del bloque vacío:
if not any([vix_delta, range_exp, rv_open]):
```

### Impacto en el rango del V-Score open

Este indicador pesa ±2. El rango del V-Score open pasa de `[−2, +2]`
(vix_delta ±1 + range_exp ±1) a `[−4, +4]`. Los umbrales de interpretación
del scorecard combinado pueden necesitar recalibración.

---

## Fuera de scope

- Comparar la RV actual con percentiles históricos de RV (sin ranking)
- Calcular RV sobre ventanas de 5 o 15 minutos (solo 1-minuto)
- Usar OHLC para estimar RV con el estimador de Parkinson o Garman-Klass
- Segmentar los log-returns por dirección (upside vs downside vol)
- Comparar RV open con RV premarket (overnight implied move)
