# Spec: Indicador ATR Ratio (V-Score)

## Qué mide

El ATR Ratio compara la volatilidad realizada reciente del SPX con la de un periodo anterior para determinar si el mercado está en **expansión** o **contracción** de rango diario.

Responde a la pregunta: ¿los rangos diarios del SPX se están ampliando o estrechando respecto a las últimas semanas?

Es un indicador de volatilidad puro — no dice nada sobre dirección. Es crítico para decidir la anchura de los strikes en un credit spread: en contracción se pueden alejar más, en expansión se necesita más margen o directamente no operar crédito.

Tiene base estadística en el fenómeno **NR7** (Narrow Range 7) documentado por Toby Crabel: días con rango muy estrecho respecto a la media tienden a preceder días de mayor amplitud, y viceversa. El ATR Ratio captura este efecto con ventana más amplia y robusta que el NR7 original.

## Fórmula

### True Range diario
```
TR = max(
    High - Low,
    |High - Close_anterior|,
    |Low  - Close_anterior|
)
```
Incluye gaps de apertura, lo que lo hace más completo que el simple High-Low.

### ATR de dos periodos
```
ATR_actual = media(TR, días -1 a -14)   # últimas 14 sesiones
ATR_lag    = media(TR, días -15 a -28)  # 14 sesiones anteriores
ATR_ratio  = ATR_actual / ATR_lag
```

Un ratio de 1.20 → rangos recientes 20% más amplios que hace un mes (expansión).
Un ratio de 0.80 → rangos recientes 20% más estrechos (contracción).

Necesita al menos **30 barras diarias** (28 para los dos periodos + 2 de margen para calcular TR con close anterior). Se recomienda descargar 35 barras para tener margen ante días festivos.

## Fuente de datos

**Solo yfinance** — histórico OHLCV diario del SPX con ticker `^GSPC`.

### Nueva función en fetch_market_data.py: `fetch_spx_ohlcv()`

No existe actualmente ninguna función que descargue OHLCV de ^GSPC (el indicador overnight_gap fue migrado a ES=F en el commit `c74f9f4`). Se debe crear `fetch_spx_ohlcv()` en `scripts/fetch_market_data.py`.

```python
def fetch_spx_ohlcv(period_days: int = 35) -> dict:
    """
    Descarga el histórico OHLCV diario del SPX (^GSPC).
    Devuelve un DataFrame con columnas Open, High, Low, Close, Volume
    y metadatos de estado.

    Args:
        period_days: número de barras diarias a solicitar (mínimo 35)

    Returns:
        {
            "ohlcv":   pd.DataFrame | None,  # columnas: Open, High, Low, Close, Volume
            "bars":    int,                  # número de barras disponibles
            "fecha":   str,                  # fecha del último bar, YYYY-MM-DD
            "status":  str,                  # "OK" | "ERROR"
        }
    """
```

**Nota de reutilización:** esta función sirve también como fuente de `Close` anterior para el gap si en el futuro se vuelve a SPX. Una sola descarga de 35 barras de ^GSPC cubre tanto el ATR Ratio como cualquier uso del cierre anterior del SPX.

## Scoring

| ATR_ratio       | Score | Signal              |
|-----------------|-------|---------------------|
| < 0.80          | +2    | CONTRACCION_FUERTE  |
| 0.80 – 0.92     | +1    | CONTRACCION_SUAVE   |
| 0.92 – 1.08     |  0    | NEUTRO              |
| 1.08 – 1.20     | -1    | EXPANSION_SUAVE     |
| > 1.20          | -2    | EXPANSION_FUERTE    |

Scores positivos indican contracción (volatilidad decreciente → favorable para credit spreads).
Scores negativos indican expansión (volatilidad creciente → mayor riesgo).

## Output

```python
{
    "atr_actual":  float,   # ATR de los últimos 14 días en puntos SPX
    "atr_lag":     float,   # ATR de los 14 días anteriores en puntos SPX
    "atr_ratio":   float,   # atr_actual / atr_lag, redondeado a 4 decimales
    "score":       int,     # -2, -1, 0, +1 o +2
    "signal":      str,     # "CONTRACCION_FUERTE" | "CONTRACCION_SUAVE"
                            # "NEUTRO" | "EXPANSION_SUAVE" | "EXPANSION_FUERTE"
    "status":      str,     # "OK" | "ERROR" | "INSUFFICIENT_DATA"
    "fecha":       str,     # fecha del último bar usado, YYYY-MM-DD
}
```

## Casos de error

| Situación | status | score | Comportamiento |
|-----------|--------|-------|----------------|
| Menos de 30 barras disponibles en yfinance | `INSUFFICIENT_DATA` | 0 | Pipeline continúa |
| ATR_lag = 0 (división por cero) | `ERROR` | 0 | Pipeline continúa |
| Cualquier excepción no controlada | `ERROR` | 0 | Pipeline continúa |

El pipeline **nunca se interrumpe** por un error en este indicador.

En caso de `INSUFFICIENT_DATA` o `ERROR`, los campos numéricos (`atr_actual`, `atr_lag`, `atr_ratio`) pueden ser `None`.

## Integración en el pipeline

### 1. fetch_market_data.py
- Añadir `fetch_spx_ohlcv()` (ver sección Fuente de datos).
- Llamarla en el bloque principal y añadir su resultado al dict global bajo la clave `"spx_ohlcv"`.
- El DataFrame se serializa en `data.json` como lista de registros (`df.to_dict("records")`).

### 2. calculate_indicators.py
- Añadir `calc_atr_ratio(spx_ohlcv_data: dict) -> dict`.
- Recibe el dict con clave `"ohlcv"` (lista de registros que se reconstruye como DataFrame).
- Calcula TR, ATR_actual, ATR_lag, ATR_ratio y aplica el scoring.
- Añadir el resultado al dict de indicadores bajo la clave `"atr_ratio"`.

### 3. V-Score
Actualizar el cálculo del V-Score sumando el nuevo indicador:

```python
# Antes
v_score = ivr["score"]

# Después
v_score = ivr["score"] + atr_ratio["score"]
```

### 4. generate_scorecard.py
Añadir una fila para el ATR Ratio en la sección de V-Score del scorecard mostrado en terminal.

## Verificación

1. Ejecutar `fetch_market_data.py` — comprobar que `data.json` incluye la clave `spx_ohlcv` con ≥30 registros.
2. Ejecutar `calculate_indicators.py` — comprobar que `indicators.json` incluye `atr_ratio` con `status: "OK"` y un `score` entre -2 y +2.
3. Comprobar que `v_score` en `indicators.json` es la suma de `ivr.score + atr_ratio.score`.
4. Caso límite: simular datos insuficientes pasando un DataFrame de 20 barras — debe devolver `status: "INSUFFICIENT_DATA"` y `score: 0` sin lanzar excepción.
