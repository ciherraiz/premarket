# Spec: IND-OPEN-01 — VWAP Position

## Estado
[Implementado]

## Propósito

Indicador D-score de la Open Phase. Mide la posición del precio del SPX respecto al VWAP
de sesión al cierre de la ventana post-open.

**Hipótesis de trading:** Los market makers y algoritmos institucionales usan el VWAP
intraday como referencia de valor justo. Un precio por encima del VWAP indica que los
compradores controlan la sesión; por debajo, los vendedores. Para un credit spread 0DTE,
esta señal define el sesgo direccional del día con alta fiabilidad en la primera media hora.

**Ventaja del indicador:** Es completamente autocontenido — solo necesita las velas de la
propia ventana. No requiere datos externos ni comparaciones con sesiones anteriores.

---

## Ubicación en el proyecto

```
scripts/calculate_open_indicators.py   ← función calc_vwap_position()
tests/test_ind_open_vwap_position.py   ← tests unitarios (10 tests, todos pasan)
```

Sigue las mismas convenciones que `calculate_indicators.py`.

Integrado en `scripts/run.py` → `run_open_phase()`. El resultado se guarda en
`outputs/indicators.json` bajo la clave `open.vwap_position`.

---

## Constantes configurables

En la sección de constantes al inicio de `scripts/calculate_open_indicators.py`:

```python
VWAP_THRESHOLD_PCT: float = 0.10   # umbral para sesgo direccional (%)
VWAP_WINDOW_MINUTES: int  = 30     # ventana esperada (para detectar datos incompletos)
```

---

## Contrato de la función

```python
def calc_vwap_position(spx_intraday: dict) -> dict:
```

### Input: `spx_intraday`

Dict devuelto por `fetch_spx_intraday()`. Campos usados:

| Campo             | Tipo       | Descripción                                   |
|-------------------|------------|-----------------------------------------------|
| `ohlcv`           | list[dict] | Barras 1-minuto; ver estructura abajo          |
| `window_minutes`  | int        | Minutos esperados (para detección incompleta)  |
| `fecha`           | str        | Fecha de la sesión (YYYY-MM-DD)                |
| `status`          | str        | Estado del fetch; si es ERROR se propaga       |

Estructura de cada registro en `ohlcv` (columnas capitalizadas, igual que `fetch_spx_ohlcv`):

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
    "vwap":                float | None,  # nivel VWAP en puntos SPX (referencia para strikes)
    "close":               float | None,  # precio de cierre de la ventana
    "vwap_distance_pct":   float | None,  # (close - vwap) / vwap × 100
    "candles_used":        int,           # velas procesadas
    "incomplete_window":   bool,          # True si < 50% de velas esperadas
    "score":               int,           # -1, 0, +1
    "signal":              str,           # "SESGO_ALCISTA" | "NEUTRO" | "SESGO_BAJISTA"
    "status":              str,           # "OK" | "ERROR"
    "fecha":               str | None,
}
```

El campo `vwap` del output se incluirá en el CombinedScorecard como zona de referencia
para situar los strikes del spread.

---

## Cálculo paso a paso

### Paso 1: Typical Price por vela

```python
typical_price = (High + Low + Close) / 3
```

### Paso 2: VWAP acumulado de sesión

```python
tp_x_vol = typical_price * Volume
vwap = tp_x_vol.sum() / Volume.sum()
```

VWAP estándar: acumulado desde 09:30, calculado sobre todas las velas de la ventana.
No es un VWAP rolling.

### Paso 3: Precio de referencia

```python
close = ohlcv[-1]["Close"]   # último close de la ventana
```

### Paso 4: Distancia porcentual

```python
vwap_distance_pct = (close - vwap) / vwap * 100
```

Positivo → precio sobre VWAP (sesgo alcista).
Negativo → precio bajo VWAP (sesgo bajista).

---

## Scoring

| Condición                            | Score | Signal           |
|--------------------------------------|-------|------------------|
| `vwap_distance_pct > +THRESHOLD`     | +1    | `SESGO_ALCISTA`  |
| `vwap_distance_pct < -THRESHOLD`     | -1    | `SESGO_BAJISTA`  |
| entre `-THRESHOLD` y `+THRESHOLD`    |  0    | `NEUTRO`         |

`THRESHOLD = VWAP_THRESHOLD_PCT = 0.10`. El umbral es **estricto** (>, <), no (≥, ≤).
Precio exactamente en el umbral → score=0.

---

## Validaciones y edge cases

### Fetch fallido
Si `spx_intraday["status"] != "OK"`:
- Devolver `{"score": 0, "signal": "ERROR_FETCH", "status": "ERROR", ...}`
- Propagar el status del fetch.

### Sin velas
Si `ohlcv` es None, vacío o no presente:
- Devolver `{"score": 0, "signal": "ERROR_SIN_DATOS", "status": "ERROR", ...}`

### Columnas faltantes
Si faltan columnas requeridas (`High`, `Low`, `Close`, `Volume`) en algún registro:
- Devolver `{"score": 0, "signal": "ERROR_COLUMNAS", "status": "ERROR", ...}`

### Volumen cero
Si `Volume.sum() == 0`:
- El VWAP no se puede calcular.
- Devolver `{"score": 0, "signal": "ERROR_VOLUMEN_CERO", "status": "ERROR", ...}`

### Ventana incompleta (< 50% velas)
Si `len(ohlcv) < window_minutes * 0.5`:
- Loggear advertencia
- Calcular igualmente con las velas disponibles (no abortar)
- Incluir `"incomplete_window": True` en el output

**Nota:** Ninguna condición lanza excepciones. Todos los errores se comunican
mediante el campo `status` y un `signal` descriptivo (convención del proyecto).

---

## Implementación (pseudocódigo)

```python
import pandas as pd

VWAP_THRESHOLD_PCT = 0.10
VWAP_WINDOW_MINUTES = 30


def calc_vwap_position(spx_intraday: dict) -> dict:
    base = {
        "vwap": None, "close": None, "vwap_distance_pct": None,
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
    required = {"High", "Low", "Close", "Volume"}
    if not required.issubset(df.columns):
        base["status"] = "ERROR"
        base["signal"] = "ERROR_COLUMNAS"
        return base

    window_minutes = spx_intraday.get("window_minutes", VWAP_WINDOW_MINUTES)
    n = len(df)
    base["candles_used"] = n

    if n < window_minutes * 0.5:
        base["incomplete_window"] = True
        # continúa el cálculo

    if df["Volume"].sum() == 0:
        base["status"] = "ERROR"
        base["signal"] = "ERROR_VOLUMEN_CERO"
        return base

    tp   = (df["High"] + df["Low"] + df["Close"]) / 3
    vwap = (tp * df["Volume"]).sum() / df["Volume"].sum()
    close = float(df["Close"].iloc[-1])
    dist  = (close - vwap) / vwap * 100

    base["vwap"]              = round(float(vwap), 2)
    base["close"]             = round(close, 2)
    base["vwap_distance_pct"] = round(dist, 4)

    if dist > VWAP_THRESHOLD_PCT:
        base["score"]  = 1
        base["signal"] = "SESGO_ALCISTA"
    elif dist < -VWAP_THRESHOLD_PCT:
        base["score"]  = -1
        base["signal"] = "SESGO_BAJISTA"

    return base
```

---

## Tests requeridos

Archivo: `tests/test_ind_open_vwap_position.py`

| # | Escenario | Condición | Resultado esperado |
|---|---|---|---|
| 1 | Precio sobre VWAP | close > vwap + 0.10% | score=+1, signal=SESGO_ALCISTA |
| 2 | Precio bajo VWAP | close < vwap - 0.10% | score=-1, signal=SESGO_BAJISTA |
| 3 | Precio en VWAP | close ≈ vwap, dentro de ±0.10% | score=0, signal=NEUTRO |
| 4 | Exactamente en umbral | vwap_distance_pct == +0.10 exacto | score=0 (umbral estricto) |
| 5 | Volumen cero | volume=0 en todas las velas | status=ERROR, signal=ERROR_VOLUMEN_CERO |
| 6 | Sin velas (lista vacía) | ohlcv=[] | status=ERROR, signal=ERROR_SIN_DATOS |
| 7 | Ventana incompleta | 5 velas para ventana de 30 min | incomplete_window=True, calcula igualmente |
| 8 | Fetch fallido | status="ERROR" en spx_intraday | status=ERROR, signal=ERROR_FETCH |

### Patrón de helpers para los tests

```python
def _make_intraday(closes, highs=None, lows=None, volumes=None,
                   window_minutes=30, status="OK"):
    n = len(closes)
    if highs is None:  highs = [c + 1.0 for c in closes]
    if lows is None:   lows  = [c - 1.0 for c in closes]
    if volumes is None: volumes = [1500] * n
    records = [
        {"Datetime": f"2026-03-31 09:{30+i:02d}:00-04:00",
         "High": highs[i], "Low": lows[i], "Close": closes[i],
         "Volume": volumes[i], "Open": closes[i]}
        for i in range(n)
    ]
    return {
        "ohlcv": records, "bars": n, "window_minutes": window_minutes,
        "open_price": closes[0] if closes else None,
        "fecha": "2026-03-31", "status": status,
    }
```

---

## Integración en run_open_phase() (implementada)

`scripts/run.py` importa `calc_vwap_position` y lo llama sobre `intraday`
(resultado de `fetch_spx_intraday`). El dict resultante se almacena bajo
`open_indicators["vwap_position"]` y su `score` contribuye al `d_score` open.

```python
# run.py — run_open_phase()
vwap = calc_vwap_position(intraday)
d_score_open = vwap["score"]
open_indicators = {
    "vwap_position":  vwap,
    "d_score":        d_score_open,
    "v_score":        0,
    "window_minutes": window_minutes,
}
```

Log de ejecución:
```
[calc-open] vwap=SESGO_ALCISTA(+1)  D=+1  V=0
```

---

## Fuera de scope

- VWAP con bandas de desviación estándar (VWAP bands) — v2
- VWAP rolling (ventana deslizante) — no aplica para 0DTE
- Comparar VWAP intraday con VWAP de días anteriores
