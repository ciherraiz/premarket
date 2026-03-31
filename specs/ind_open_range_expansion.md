# Spec: IND-OPEN-04 — Range Expansion

## Estado
[ ] Pendiente de implementación

## Propósito

Indicador V-Score de la Open Phase. Mide si el mercado ha consumido durante la ventana
post-open más o menos movimiento del que la volatilidad implícita predecía para ese período.

**Fórmula central:**

```
ratio = OR_realized / expected_range

OR_realized   = OR_high - OR_low  (en puntos SPX)
iv_daily_pts  = SPX_open × (VIX / 100) / sqrt(252)
expected_range = iv_daily_pts × sqrt(OPEN_WINDOW_MINUTES / 390)
```

El ajuste por raíz cuadrada del tiempo escala la IV diaria (que cubre 390 minutos) a
la ventana de apertura, en la misma forma que usan los modelos de opciones.

**Interpretación del ratio:**
- `ratio = 1.0` → el mercado se ha movido exactamente lo que la IV predecía
- `ratio = 0.5` → se ha movido la mitad del presupuesto de movimiento
- `ratio = 1.5` → se ha movido un 50% más de lo esperado

**Hipótesis de trading:**

| Ratio         | Señal            | Interpretación |
|---------------|------------------|----------------|
| < 0.6         | EXPANSION_BAJA   | IV sobreestima el movimiento → opciones caras → favorable para vender premium |
| 0.6 – 1.2     | NEUTRO           | Movimiento en línea con la IV → entorno ambiguo |
| > 1.2         | EXPANSION_ALTA   | Mercado ya absorbió más de lo esperado → peligroso vender premium cerca |

Un ratio bajo es la confirmación intraday de que el entorno es favorable para credit spreads.
Un ratio alto puede indicar un día de tendencia o evento macro que absorbió movimiento.

**Dependencia inter-fase:** necesita el VIX del premarket (guardado en `indicators.json`
bajo `premarket.ivr.vix`). La función lo recibe como parámetro `premarket_indicators`
para facilitar los tests y mantener la separación de responsabilidades.

---

## Ubicación en el proyecto

```
scripts/calculate_open_indicators.py   ← función calc_range_expansion()
tests/test_ind_open_range_expansion.py ← tests unitarios (13 tests)
```

Sigue las mismas convenciones que el resto de `calculate_open_indicators.py`.

Se integrará en `scripts/run.py` → `run_open_phase()`. El resultado se guardará en
`outputs/indicators.json` bajo la clave `open.range_expansion`.

---

## Constantes configurables

En la sección de constantes al inicio de `scripts/calculate_open_indicators.py`:

```python
RANGE_EXPANSION_LOW      = 0.6    # ratio < → EXPANSION_BAJA → score +1
RANGE_EXPANSION_HIGH     = 1.2    # ratio > → EXPANSION_ALTA → score -1
RANGE_EXP_WINDOW_MINUTES = 30     # ventana esperada (para detección de incompletos)
TRADING_MINUTES_DAY      = 390    # minutos de una jornada completa de trading
```

---

## Contrato de la función

### Firma

```python
def calc_range_expansion(spx_intraday: dict, premarket_indicators: dict) -> dict:
```

### Input `spx_intraday`

Dict devuelto por `fetch_spx_intraday()`:

```python
{
    "ohlcv":          [{"Datetime": str, "Open": float, "High": float,
                        "Low": float, "Close": float, "Volume": int}, ...],
    "bars":           int,
    "window_minutes": int,       # minutos de la ventana (ej. 30)
    "open_price":     float,     # precio de apertura del SPX a las 09:30
    "fecha":          str,
    "status":         "OK" | "ERROR",
}
```

### Input `premarket_indicators`

Dict del premarket (sección `premarket` de `outputs/indicators.json`):

```python
{
    "ivr": {
        "vix":    float,    # nivel VIX utilizado para IVR
        "status": str,
        ...
    },
    "vix_vxv_slope": {
        "vix": float,       # fallback si ivr.vix no está disponible
        ...
    },
    ...
}
```

La función lee primero `premarket_indicators["ivr"]["vix"]`.
Si ese campo es `None`, intenta `premarket_indicators["vix_vxv_slope"]["vix"]`.
Si ambos son `None`, devuelve `ERROR_IV_NO_DISPONIBLE`.

### Output

```python
{
    "or_high":           float | None,   # max(High) de todas las velas de la ventana
    "or_low":            float | None,   # min(Low) de todas las velas de la ventana
    "or_realized":       float | None,   # or_high - or_low en puntos SPX
    "iv_daily_pts":      float | None,   # SPX_open × (VIX/100) / sqrt(252)
    "expected_range":    float | None,   # iv_daily_pts × sqrt(window_minutes / 390)
    "ratio":             float | None,   # or_realized / expected_range (4 decimales)
    "value":             float | None,   # alias de ratio para el scorecard combinado
    "vix_used":          float | None,   # VIX utilizado en el cálculo
    "spx_open":          float | None,   # precio de apertura SPX utilizado
    "candles_used":      int,
    "incomplete_window": bool,           # True si n < window_minutes × 0.5
    "score":             int,            # -1 / 0 / +1
    "signal":            str,
    "status":            str,            # "OK" | "ERROR"
    "fecha":             str | None,
}
```

---

## Tabla de scoring

| Condición                             | Score | Signal            |
|---------------------------------------|-------|-------------------|
| `ratio < RANGE_EXPANSION_LOW`  (< 0.6)  | +1    | EXPANSION_BAJA    |
| `RANGE_EXPANSION_LOW ≤ ratio ≤ RANGE_EXPANSION_HIGH` | 0 | NEUTRO |
| `ratio > RANGE_EXPANSION_HIGH` (> 1.2)  | −1    | EXPANSION_ALTA    |

Los umbrales son **estrictos**: `ratio == 0.6` o `ratio == 1.2` devuelven `score=0`.

---

## Señales de error

| Signal                  | Causa                                              |
|-------------------------|----------------------------------------------------|
| ERROR_FETCH             | `spx_intraday["status"] != "OK"`                   |
| ERROR_SIN_DATOS         | `ohlcv` vacío o ausente                            |
| ERROR_COLUMNAS          | Faltan columnas `High`, `Low`, o `Close`           |
| ERROR_IV_NO_DISPONIBLE  | VIX es `None` en ambos campos de `premarket_indicators` |
| ERROR_SPX_OPEN_NULO     | `open_price` es `None` en `spx_intraday`           |

En todos los casos de error: `score=0`, `status="ERROR"`.

---

## Integración en `run.py`

```python
# scripts/run.py — run_open_phase()

from calculate_open_indicators import (
    calc_vwap_position, calc_vix_delta_open, calc_range_expansion
)

def run_open_phase(out: Path, window_minutes: int) -> dict:
    # ... fetch intraday ...

    vwap      = calc_vwap_position(intraday)
    vix_delta = calc_vix_delta_open(vix_intraday)

    # Dependencia inter-fase: leer VIX del premarket
    premarket_ind = _read_json(out / "indicators.json").get("premarket", {})
    range_exp     = calc_range_expansion(intraday, premarket_ind)

    d_score_open = vwap["score"]
    v_score_open = vix_delta["score"] + range_exp["score"]

    open_indicators = {
        "vwap_position":   vwap,
        "vix_delta_open":  vix_delta,
        "range_expansion": range_exp,
        "d_score":         d_score_open,
        "v_score":         v_score_open,
        "window_minutes":  window_minutes,
    }
```

---

## Tests requeridos

Fichero: `tests/test_ind_open_range_expansion.py`

Helpers:
- `_make_intraday(closes, highs, lows, window_minutes, open_price, status)` — construye
  dict compatible con `fetch_spx_intraday()`
- `_make_premarket(vix)` — devuelve `{"ivr": {"vix": vix, "status": "OK"}}`

| # | Nombre del test                             | Verificación clave                                    |
|---|---------------------------------------------|-------------------------------------------------------|
| 1 | `test_score_positivo_ratio_bajo`            | ratio < 0.6 → score=+1, signal=EXPANSION_BAJA        |
| 2 | `test_score_negativo_ratio_alto`            | ratio > 1.2 → score=−1, signal=EXPANSION_ALTA        |
| 3 | `test_score_neutro_ratio_medio`             | 0.6 ≤ ratio ≤ 1.2 → score=0, signal=NEUTRO           |
| 4 | `test_umbral_inferior_exacto_score_neutro`  | ratio == 0.6 exacto → score=0 (umbral estricto)       |
| 5 | `test_umbral_superior_exacto_score_neutro`  | ratio == 1.2 exacto → score=0 (umbral estricto)       |
| 6 | `test_fetch_fallido_propaga_error`          | status=ERROR → signal=ERROR_FETCH, score=0            |
| 7 | `test_sin_velas_lista_vacia`               | ohlcv=[] → signal=ERROR_SIN_DATOS                    |
| 8 | `test_columnas_faltantes_devuelve_error`   | sin campo High → signal=ERROR_COLUMNAS               |
| 9 | `test_iv_no_disponible_devuelve_error`     | vix=None → signal=ERROR_IV_NO_DISPONIBLE             |
| 10| `test_spx_open_nulo_devuelve_error`        | open_price=None → signal=ERROR_SPX_OPEN_NULO         |
| 11| `test_ventana_incompleta_calcula_igualmente` | n < window*0.5 → incomplete_window=True, score válido |
| 12| `test_verificacion_aritmetica`             | iv_daily_pts, expected_range y ratio exactos          |
| 13| `test_rango_cero_precio_flat`              | or_realized=0 → ratio=0.0 → score=+1                 |
