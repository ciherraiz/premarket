# Spec: IND-OPEN-02 — VIX Delta Open

## Estado
[ ] Pendiente de implementación

## Propósito

Indicador V-Score de la Open Phase. Mide cuánto se ha movido el VIX desde la apertura
del mercado hasta el cierre de la ventana post-open.

**Hipótesis de trading:** El VIX no solo refleja el miedo del mercado en abstracto —
tiene correlación directa con los precios de las opciones SPX que se van a vender.
Un VIX cayendo en la apertura es la confirmación en tiempo real de que la IV implícita
está colapsando: el crédito recibido por el spread fue calculado en un momento de mayor
miedo y ahora las opciones valen menos, poniendo el trade inmediatamente a favor.
Un VIX subiendo indica que la volatilidad se está expandiendo y el riesgo de que el
spread sea alcanzado aumenta considerablemente.

**Ventaja del indicador:** Es completamente autocontenido — no necesita datos de la
Fase 1, no requiere cálculos estadísticos, y solo depende de dos valores del mismo
DataFrame de velas (Open de la primera barra y Close de la última).

---

## Ubicación en el proyecto

```
scripts/fetch_market_data.py           ← nueva función fetch_vix_intraday()
scripts/calculate_open_indicators.py   ← nueva función calc_vix_delta_open()
tests/test_ind_open_vix_delta.py       ← tests unitarios
```

Sigue las mismas convenciones que `calculate_open_indicators.py`.

Integrado en `scripts/run.py` → `run_open_phase()`. El resultado se guarda en
`outputs/indicators.json` bajo la clave `open.vix_delta_open`.

---

## Constantes configurables

En la sección de constantes al inicio de `scripts/calculate_open_indicators.py`:

```python
VIX_DELTA_THRESHOLD: float = 0.5   # puntos VIX de diferencia para señal de volatilidad
```

---

## Contrato de la función

```python
def calc_vix_delta_open(vix_intraday: dict) -> dict:
```

### Input: `vix_intraday`

Dict devuelto por `fetch_vix_intraday()`. Campos usados:

| Campo             | Tipo       | Descripción                                     |
|-------------------|------------|-------------------------------------------------|
| `ohlcv`           | list[dict] | Barras 1-minuto del VIX; ver estructura abajo   |
| `window_minutes`  | int        | Minutos esperados (para detección incompleta)   |
| `fecha`           | str        | Fecha de la sesión (YYYY-MM-DD)                 |
| `status`          | str        | Estado del fetch; si es ERROR se propaga        |

Estructura de cada registro en `ohlcv` (columnas capitalizadas, sin Volume):

```python
{
    "Datetime": str,    # "2026-03-31 09:30:00-04:00"
    "Open":     float,
    "High":     float,
    "Low":      float,
    "Close":    float,
}
```

### Output: dict

```python
{
    "vix_open":          float | None,  # Open de la primera vela (09:30 ET)
    "vix_close":         float | None,  # Close de la última vela (fin ventana)
    "vix_delta":         float | None,  # vix_close - vix_open, redondeado a 2 decimales
    "value":             float | None,  # alias de vix_delta para el scorecard combinado
    "candles_used":      int,           # velas procesadas
    "incomplete_window": bool,          # True si < 50% de velas esperadas
    "score":             int,           # -1, 0, +1
    "signal":            str,           # "IV_COMPRIMIENDO" | "NEUTRO" | "IV_EXPANDIENDO"
    "status":            str,           # "OK" | "ERROR"
    "fecha":             str | None,
}
```

---

## Cálculo paso a paso

### Paso 1: Extraer Open de la primera vela

```python
vix_open = ohlcv[0]["Open"]   # barra de las 09:30 ET
```

### Paso 2: Extraer Close de la última vela

```python
vix_close = ohlcv[-1]["Close"]   # barra del cierre de la ventana (p.ej. 09:59 ET)
```

### Paso 3: Delta

```python
vix_delta = round(vix_close - vix_open, 2)
```

Positivo → VIX ha subido (volatilidad expandiéndose).
Negativo → VIX ha bajado (volatilidad comprimiéndose).

---

## Scoring

| Condición                      | Score | Signal            |
|--------------------------------|-------|-------------------|
| `vix_delta < -VIX_DELTA_THRESHOLD`  | +1    | `IV_COMPRIMIENDO` |
| `vix_delta > +VIX_DELTA_THRESHOLD`  | -1    | `IV_EXPANDIENDO`  |
| entre `-THRESHOLD` y `+THRESHOLD`   |  0    | `NEUTRO`          |

`THRESHOLD = VIX_DELTA_THRESHOLD = 0.5`. El umbral es **estricto** (< y >), no (≤ y ≥).
Un delta exactamente en ±0.5 → score=0.

---

## Validaciones y edge cases

### Fetch fallido
Si `vix_intraday["status"] != "OK"`:
- Devolver `{"score": 0, "signal": "ERROR_FETCH", "status": "ERROR", ...}`
- Propagar el status del fetch.

### Sin velas
Si `ohlcv` es None, vacío o no presente:
- Devolver `{"score": 0, "signal": "ERROR_SIN_DATOS", "status": "ERROR", ...}`

### Columnas faltantes
Si faltan columnas requeridas (`Open`, `Close`) en algún registro:
- Devolver `{"score": 0, "signal": "ERROR_COLUMNAS", "status": "ERROR", ...}`

### Ventana incompleta (< 50% velas)
Si `len(ohlcv) < window_minutes * 0.5`:
- Loggear advertencia
- Calcular igualmente con las velas disponibles (no abortar)
- Incluir `"incomplete_window": True` en el output

**Nota sobre Volume:** El VIX es un índice sintético — yfinance devuelve Volume=0 o NaN.
La función no requiere ni usa el campo Volume; el fetch omite esa columna.

**Nota:** Ninguna condición lanza excepciones. Todos los errores se comunican
mediante el campo `status` y un `signal` descriptivo (convención del proyecto).

---

## Implementación (pseudocódigo)

### fetch_vix_intraday() en fetch_market_data.py

```python
VIX_DELTA_THRESHOLD = 0.5

def fetch_vix_intraday(window_minutes: int = 30) -> dict:
    """
    Descarga barras de 1 minuto del VIX (^VIX) para la sesión actual.
    Filtra desde las 09:30 ET y devuelve las primeras window_minutes barras.
    No incluye Volume (el VIX es un índice sintético).
    """
    result = {
        "ohlcv": None, "bars": 0, "window_minutes": window_minutes,
        "vix_open": None, "vix_close": None,
        "fecha": str(date.today()), "status": "OK",
    }

    try:
        df = yf.download("^VIX", period="1d", interval="1m",
                         prepost=False, auto_adjust=True, progress=False)

        if df.empty:
            result["status"] = "INSUFFICIENT_DATA"
            return result

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        df = df[["Open", "High", "Low", "Close"]].dropna()

        et = ZoneInfo("America/New_York")
        df.index = df.index.tz_convert(et)
        df = df[df.index.time >= time(9, 30)]
        df = df[df.index.date == date.today()]
        df = df.head(window_minutes)

        bars = len(df)
        result["bars"] = bars

        if bars == 0:
            result["status"] = "INSUFFICIENT_DATA"
            return result

        result["fecha"] = str(df.index[-1].date())
        records = [
            {"Datetime": str(idx),
             "Open":  round(float(row["Open"]),  2),
             "High":  round(float(row["High"]),  2),
             "Low":   round(float(row["Low"]),   2),
             "Close": round(float(row["Close"]), 2)}
            for idx, row in df.iterrows()
        ]
        result["ohlcv"]     = records
        result["vix_open"]  = records[0]["Open"]
        result["vix_close"] = records[-1]["Close"]

        if bars < window_minutes:
            result["status"] = "INSUFFICIENT_DATA"

    except Exception:
        result["status"] = "ERROR"

    return result
```

### calc_vix_delta_open() en calculate_open_indicators.py

```python
VIX_DELTA_THRESHOLD = 0.5

def calc_vix_delta_open(vix_intraday: dict) -> dict:
    base = {
        "vix_open": None, "vix_close": None, "vix_delta": None, "value": None,
        "candles_used": 0, "incomplete_window": False,
        "score": 0, "signal": "NEUTRO",
        "status": "OK", "fecha": vix_intraday.get("fecha"),
    }

    if vix_intraday.get("status") != "OK":
        base["status"] = "ERROR"
        base["signal"] = "ERROR_FETCH"
        return base

    records = vix_intraday.get("ohlcv") or []
    if not records:
        base["status"] = "ERROR"
        base["signal"] = "ERROR_SIN_DATOS"
        return base

    df = pd.DataFrame(records)
    required = {"Open", "Close"}
    if not required.issubset(df.columns):
        base["status"] = "ERROR"
        base["signal"] = "ERROR_COLUMNAS"
        return base

    window_minutes = vix_intraday.get("window_minutes", VIX_DELTA_WINDOW_MINUTES)
    n = len(df)
    base["candles_used"] = n

    if n < window_minutes * 0.5:
        base["incomplete_window"] = True

    vix_open  = float(df["Open"].iloc[0])
    vix_close = float(df["Close"].iloc[-1])
    delta     = round(vix_close - vix_open, 2)

    base["vix_open"]  = round(vix_open,  2)
    base["vix_close"] = round(vix_close, 2)
    base["vix_delta"] = delta
    base["value"]     = delta   # alias para el scorecard

    if delta < -VIX_DELTA_THRESHOLD:
        base["score"]  = 1
        base["signal"] = "IV_COMPRIMIENDO"
    elif delta > VIX_DELTA_THRESHOLD:
        base["score"]  = -1
        base["signal"] = "IV_EXPANDIENDO"

    return base
```

---

## Tests requeridos

Archivo: `tests/test_ind_open_vix_delta.py`

| #  | Escenario                   | Input                            | Resultado esperado                          |
|----|-----------------------------|----------------------------------|---------------------------------------------|
| 1  | VIX baja > 0.5              | open=18.5, close=17.8 (Δ=−0.70) | score=+1, signal=IV_COMPRIMIENDO            |
| 2  | VIX sube > 0.5              | open=17.0, close=17.8 (Δ=+0.80) | score=−1, signal=IV_EXPANDIENDO             |
| 3  | Movimiento neutro           | open=17.0, close=17.3 (Δ=+0.30) | score=0, signal=NEUTRO                      |
| 4  | Exactamente −0.5            | open=18.0, close=17.5 (Δ=−0.50) | score=0 (umbral estricto), signal=NEUTRO    |
| 5  | Exactamente +0.5            | open=17.0, close=17.5 (Δ=+0.50) | score=0 (umbral estricto), signal=NEUTRO    |
| 6  | Sin velas (lista vacía)     | ohlcv=[]                         | status=ERROR, signal=ERROR_SIN_DATOS        |
| 7  | Fetch fallido               | status="ERROR"                   | status=ERROR, signal=ERROR_FETCH            |
| 8  | Ventana incompleta          | 5 velas, window_minutes=30       | incomplete_window=True, calcula igualmente  |
| 9  | VIX cae mucho (evento)      | open=22.0, close=19.5 (Δ=−2.50) | score=+1, signal=IV_COMPRIMIENDO            |
| 10 | VIX spike                   | open=17.0, close=21.0 (Δ=+4.00) | score=−1, signal=IV_EXPANDIENDO             |

### Patrón de helpers para los tests

```python
def _make_vix_intraday(vix_open, vix_close, n_bars=30, window_minutes=30, status="OK"):
    """Construye un mock de fetch_vix_intraday con open y close controlados."""
    records = []
    for i in range(n_bars):
        # Interpolación lineal entre open y close para simular movimiento real
        close_i = round(vix_open + (vix_close - vix_open) * (i + 1) / n_bars, 2)
        records.append({
            "Datetime": f"2026-03-31 09:{30+i:02d}:00-04:00",
            "Open":  round(vix_open + (vix_close - vix_open) * i / n_bars, 2),
            "High":  close_i + 0.1,
            "Low":   close_i - 0.1,
            "Close": close_i,
        })
    # Asegurar que la primera barra tiene el open exacto
    if records:
        records[0]["Open"] = vix_open
    return {
        "ohlcv": records if status == "OK" else None,
        "bars": len(records),
        "window_minutes": window_minutes,
        "vix_open": vix_open if records else None,
        "vix_close": vix_close if records else None,
        "fecha": "2026-03-31",
        "status": status,
    }
```

---

## Integración en run_open_phase()

### Cambios en `scripts/run.py`

```python
from fetch_market_data import (
    ...,
    fetch_vix_intraday,   # nueva import
)
from calculate_open_indicators import calc_vwap_position, calc_vix_delta_open  # añadir

# En run_open_phase():
vix_intraday = fetch_vix_intraday(window_minutes)
# ...
vwap      = calc_vwap_position(intraday)
vix_delta = calc_vix_delta_open(vix_intraday)

d_score_open = vwap["score"]
v_score_open = vix_delta["score"]   # antes hardcoded a 0

open_indicators = {
    "vwap_position":  vwap,
    "vix_delta_open": vix_delta,
    "d_score":        d_score_open,
    "v_score":        v_score_open,
    "window_minutes": window_minutes,
}
```

Log de ejecución:
```
[fetch-open] intraday=OK(bars=30) vix_intraday=OK(bars=30) es=OK chain_0dte=OK(n=60)
[calc-open] vwap=SESGO_ALCISTA(+1)  vix_delta=IV_COMPRIMIENDO(+1)  D=+1  V=+1
```

---

## Cambios en generate_scorecard.py

Añadir bloque `[OPEN PHASE — V-SCORE]` en `print_combined_scorecard()`, justo después
del bloque D-Score open y antes de los Totales. Render del valor: `VIX_Δ={vix_delta:+.2f}`.

```python
# Ejemplo de la fila en el bloque V-Score open:
#   vix_delta_open       VIX_Δ=-0.70               +1     IV_COMPRIMIENDO

vix_delta_open = open_phase.get("vix_delta_open", {})
if vix_delta_open.get("status") == "OK":
    delta_val = vix_delta_open.get("vix_delta")
    val = f"VIX_Δ={delta_val:+.2f}"
else:
    val = f"[{vix_delta_open.get('status','ERROR')}]"
print(f"  {'VIX Delta Open':<20} {val:<26} {_sign(vix_delta_open.get('score',0)):<6} "
      f"{vix_delta_open.get('signal','N/A')}")
```

---

## Fuera de scope

- Comparar vix_delta con sesiones anteriores (promedio histórico de apertura)
- Ventana deslizante del delta (rolling VIX delta)
- Ponderar el delta por la magnitud absoluta del VIX (ratio en lugar de diferencia)
- Combinar vix_delta con ATR Ratio premarket (correlación cross-phase)
