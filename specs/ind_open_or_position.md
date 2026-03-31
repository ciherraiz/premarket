# Spec: IND-OPEN-03 — OR Position

## Estado
[Especificado]

## Propósito

Indicador D-score de la Open Phase. Mide dónde está el precio del SPX al cierre de la
ventana post-open en relación al rango que el mercado ha construido desde la apertura
(Opening Range).

**Hipótesis de trading:** El mercado tiende a continuar en la dirección en la que cerró
la ventana de apertura. Si al cabo de 30 minutos el precio está en la mitad superior del
Opening Range, los compradores han controlado esa primera media hora y es probable que el
sesgo alcista se mantenga el resto del día — suficiente para que un bull put spread expire
sin ser alcanzado. Lo contrario aplica si el precio cierra en la mitad inferior. La zona
neutral (0.4–0.6) indica que el mercado no ha tomado una dirección clara: el OR podría
actuar como zona de consolidación, lo que favorece un iron condor pero reduce la convicción
para un spread direccional.

**Ventaja operativa:** A diferencia de IND-OPEN-01 (VWAP position), este indicador genera
tres niveles de referencia explícitos — `or_high`, `or_low`, `or_mid` — que se usan
directamente para colocar los strikes del spread:

- Bull put spread → short strike por debajo de `or_low`
- Bear call spread → short strike por encima de `or_high`
- Iron condor → or_high y or_low como límites de la zona de consolidación

Esto convierte al indicador en herramienta de señal **y** de gestión de riesgo.

---

## Ubicación en el proyecto

```
scripts/calculate_open_indicators.py   ← función calc_or_position()
tests/test_ind_open_or_position.py     ← tests unitarios (13 tests)
```

Sigue las mismas convenciones que `calculate_open_indicators.py`.

Se integrará en `scripts/run.py` → `run_open_phase()`. El resultado se guardará en
`outputs/indicators.json` bajo la clave `open.or_position`.

---

## Constantes configurables

En la sección de constantes al inicio de `scripts/calculate_open_indicators.py`:

```python
OR_NEUTRAL_LOW:    float = 0.40   # umbral inferior de la zona neutra (estricto)
OR_NEUTRAL_HIGH:   float = 0.60   # umbral superior de la zona neutra (estricto)
OR_WINDOW_MINUTES: int   = 30     # ventana esperada (para detectar datos incompletos)
```

---

## Contrato de la función

```python
def calc_or_position(spx_intraday: dict) -> dict:
```

### Input: `spx_intraday`

Dict devuelto por `fetch_spx_intraday()`. Campos usados:

| Campo             | Tipo       | Descripción                                   |
|-------------------|------------|-----------------------------------------------|
| `ohlcv`           | list[dict] | Barras 1-minuto; ver estructura abajo          |
| `window_minutes`  | int        | Minutos esperados (para detección incompleta)  |
| `fecha`           | str        | Fecha de la sesión (YYYY-MM-DD)                |
| `status`          | str        | Estado del fetch; si es ERROR se propaga       |

Estructura de cada registro en `ohlcv` (columnas capitalizadas):

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

### Output: dict

```python
{
    "or_high":           float | None,  # máximo de todos los High de la ventana
    "or_low":            float | None,  # mínimo de todos los Low de la ventana
    "or_mid":            float | None,  # (or_high + or_low) / 2
    "or_position":       float | None,  # (close - or_low) / (or_high - or_low) ∈ [0, 1]
    "close":             float | None,  # último Close de la ventana
    "candles_used":      int,           # velas procesadas
    "incomplete_window": bool,          # True si < 50% de velas esperadas
    "score":             int,           # -1, 0, +1
    "signal":            str,           # "SESGO_ALCISTA" | "NEUTRO" | "SESGO_BAJISTA" | ...
    "status":            str,           # "OK" | "ERROR"
    "fecha":             str | None,
}
```

Los campos `or_high`, `or_low` y `or_mid` se incluirán en el CombinedScorecard como
zonas de referencia para situar los strikes del spread.

---

## Cálculo paso a paso

### Paso 1: Opening Range High y Low

```python
or_high = df["High"].max()
or_low  = df["Low"].min()
```

El OR se construye sobre **todas las velas de la ventana** (no solo la primera vela).

### Paso 2: Punto medio del OR

```python
or_mid = (or_high + or_low) / 2
```

### Paso 3: Precio de referencia

```python
close = df["Close"].iloc[-1]   # último close de la ventana
```

### Paso 4: Posición dentro del OR

```python
or_range    = or_high - or_low
or_position = (close - or_low) / or_range   # solo si or_range > 0
```

- Valor 0 → close pegado al mínimo del OR
- Valor 1 → close pegado al máximo del OR
- Valor 0.5 → close exactamente en el punto medio

---

## Scoring

| Condición                           | Score | Signal           |
|-------------------------------------|-------|------------------|
| `or_position > OR_NEUTRAL_HIGH`     | +1    | `SESGO_ALCISTA`  |
| `or_position < OR_NEUTRAL_LOW`      | -1    | `SESGO_BAJISTA`  |
| `OR_NEUTRAL_LOW ≤ or_position ≤ OR_NEUTRAL_HIGH` | 0 | `NEUTRO` |

Los umbrales son **estrictos** (>, <), no (≥, ≤). Un valor exactamente en 0.40 o 0.60
produce score=0.

---

## Validaciones y edge cases

### Fetch fallido
Si `spx_intraday["status"] != "OK"`:
- Devolver `{"score": 0, "signal": "ERROR_FETCH", "status": "ERROR", ...}`

### Sin velas
Si `ohlcv` es None, vacío o no presente:
- Devolver `{"score": 0, "signal": "ERROR_SIN_DATOS", "status": "ERROR", ...}`

### Columnas faltantes
Si faltan columnas requeridas (`High`, `Low`, `Close`) en algún registro:
- Devolver `{"score": 0, "signal": "ERROR_COLUMNAS", "status": "ERROR", ...}`

### Rango cero (`or_high == or_low`)
Todas las velas tienen el mismo High y Low — mercado completamente flat:
- No se puede calcular `or_position` (división por cero)
- Devolver `{"score": 0, "signal": "RANGO_CERO", "status": "OK", "or_position": None, ...}`
- `or_high`, `or_low` y `or_mid` siguen siendo válidos y se incluyen en el output

### Ventana incompleta (< 50% velas)
Si `len(ohlcv) < window_minutes * 0.5`:
- Loggear advertencia
- Calcular igualmente con las velas disponibles (no abortar)
- Incluir `"incomplete_window": True` en el output

**Ninguna condición lanza excepciones.** Todos los errores se comunican mediante el campo
`status` y un `signal` descriptivo (convención del proyecto).

---

## Implementación (pseudocódigo)

```python
import pandas as pd

OR_NEUTRAL_LOW    = 0.40
OR_NEUTRAL_HIGH   = 0.60
OR_WINDOW_MINUTES = 30


def calc_or_position(spx_intraday: dict) -> dict:
    base = {
        "or_high": None, "or_low": None, "or_mid": None,
        "or_position": None, "close": None,
        "candles_used": 0, "incomplete_window": False,
        "score": 0, "signal": "NEUTRO",
        "status": "OK", "fecha": spx_intraday.get("fecha"),
    }

    if spx_intraday.get("status") != "OK":
        base["status"] = "ERROR"
        base["signal"] = "ERROR_FETCH"
        return base

    records = spx_intraday.get("ohlcv") or []
    if not records:
        base["status"] = "ERROR"
        base["signal"] = "ERROR_SIN_DATOS"
        return base

    df = pd.DataFrame(records)
    required = {"High", "Low", "Close"}
    if not required.issubset(df.columns):
        base["status"] = "ERROR"
        base["signal"] = "ERROR_COLUMNAS"
        return base

    window_minutes = spx_intraday.get("window_minutes", OR_WINDOW_MINUTES)
    n = len(df)
    base["candles_used"] = n

    if n < window_minutes * 0.5:
        base["incomplete_window"] = True

    or_high = float(df["High"].max())
    or_low  = float(df["Low"].min())
    or_mid  = (or_high + or_low) / 2
    close   = float(df["Close"].iloc[-1])

    base["or_high"] = round(or_high, 2)
    base["or_low"]  = round(or_low, 2)
    base["or_mid"]  = round(or_mid, 2)
    base["close"]   = round(close, 2)

    or_range = or_high - or_low
    if or_range == 0:
        base["signal"] = "RANGO_CERO"
        return base

    or_position = (close - or_low) / or_range
    base["or_position"] = round(or_position, 4)

    if or_position > OR_NEUTRAL_HIGH:
        base["score"]  = 1
        base["signal"] = "SESGO_ALCISTA"
    elif or_position < OR_NEUTRAL_LOW:
        base["score"]  = -1
        base["signal"] = "SESGO_BAJISTA"

    return base
```

---

## Tests requeridos

Archivo: `tests/test_ind_open_or_position.py`

| # | Escenario | Condición | Resultado esperado |
|---|-----------|-----------|-------------------|
| 1 | Close en parte alta del OR | or_position ≈ 0.85 | score=+1, SESGO_ALCISTA |
| 2 | Close en parte baja del OR | or_position ≈ 0.15 | score=-1, SESGO_BAJISTA |
| 3 | Close en zona neutra (or_mid) | or_position = 0.50 | score=0, NEUTRO |
| 4 | Umbral superior exacto | or_position == 0.60 | score=0 (umbral estricto) |
| 5 | Umbral inferior exacto | or_position == 0.40 | score=0 (umbral estricto) |
| 6 | Rango cero | or_high == or_low | score=0, RANGO_CERO, or_position=None |
| 7 | Sin velas | ohlcv=[] | status=ERROR, ERROR_SIN_DATOS |
| 8 | Fetch fallido | status="ERROR" | status=ERROR, ERROR_FETCH |
| 9 | Columnas faltantes | sin "High" en registros | status=ERROR, ERROR_COLUMNAS |
| 10 | Ventana incompleta | 5 velas para 30 min | incomplete_window=True, calcula |
| 11 | Valores or_high/or_low/or_mid | datos conocidos | verificar aritmética exacta |
| 12 | Extremo inferior (or_position=0.0) | close == or_low | score=-1, or_position=0.0 |
| 13 | Extremo superior (or_position=1.0) | close == or_high en Close | score=+1, or_position=1.0 |

---

## Integración prevista en run_open_phase()

```python
# run.py — run_open_phase() (pendiente de implementar)
or_pos = calc_or_position(intraday)
d_score_open = vwap["score"] + or_pos["score"]
open_indicators = {
    "vwap_position": vwap,
    "or_position":   or_pos,
    "vix_delta_open": vix_delta,
    "d_score":        d_score_open,
    "v_score":        vix_delta["score"],
    "window_minutes": window_minutes,
}
```

Log de ejecución previsto:
```
[calc-open] or_position=SESGO_ALCISTA(+1)  or_high=5220.50  or_low=5195.25  or_mid=5207.88
```

---

## Fuera de scope

- OR extendido (pre-market incluido) — solo se usa la ventana post-open
- OR de múltiples timeframes — solo la ventana configurada (30 min por defecto)
- Comparar el OR actual con ORs de sesiones anteriores
