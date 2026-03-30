# SPEC — IND: Overnight Gap

## Estado
[ ] En desarrollo

## Objetivo
Calcular el gap entre el precio premarket del futuro ES y el cierre anterior del SPX
para determinar si el mercado abre con sesgo alcista o bajista, y asignar un score direccional.

## Contexto
El Overnight Gap responde a la pregunta: ¿cómo ha abierto el mercado respecto a ayer
y qué sesgo direccional implica?

Cuando el ES cotiza en premarket por encima del cierre del SPX del día anterior hay un gap
alcista — el mercado ha absorbido noticias o flujos positivos fuera de horario.
Cuando cotiza por debajo hay un gap bajista.

La asimetría clave del indicador: no todos los gaps tienen el mismo significado direccional.
Los gaps pequeños tienden a continuar en la misma dirección durante la sesión.
Los gaps grandes tienden a rellenarse porque atraen vendedores institucionales (gaps alcistas)
o compradores (gaps bajistas). Bulkowski documentó una tasa de relleno del 71% para gaps
superiores al 0.5% en el SPX. Por eso el scoring no es lineal — los gaps extremos reciben
score neutro (0).

Este es el primer indicador del D-Score que consume el MCP de TastyTrade.

## Fuente de datos

### SPX cierre anterior
- Proveedor  : yfinance
- Ticker     : ^GSPC
- Nueva función `fetch_spx_prev_close()` en fetch_market_data.py
- Periodo    : últimos 5 días (margen para festivos), toma el último cierre disponible

### ES precio premarket
- Proveedor  : TastyTrade MCP
- Símbolo    : /ES
- Nueva función `fetch_es_quote()` en fetch_market_data.py
- Herramienta MCP: `get_quotes` con símbolo `/ES`
- Extrae el precio `last` (o `mark` como fallback si `last` es None o 0)

## Fórmula
```
gap_points = ES_premarket - SPX_cierre_anterior
gap_pct    = (ES_premarket - SPX_cierre_anterior) / SPX_cierre_anterior × 100
```

## Tabla de scoring

| Condición              | Score | Signal                | Interpretación                               |
|------------------------|-------|-----------------------|----------------------------------------------|
| +0.10% a +0.50%        | +1    | GAP_ALCISTA           | Gap alcista moderado → continuación probable |
| -0.10% a -0.50%        | -1    | GAP_BAJISTA           | Gap bajista moderado → continuación probable |
| -0.10% a +0.10%        |  0    | PLANO                 | Sin gap significativo                        |
| > +0.50%               |  0    | GAP_ALCISTA_GRANDE    | Gap alcista extremo → relleno probable (71%) |
| < -0.50%               |  0    | GAP_BAJISTA_GRANDE    | Gap bajista extremo → relleno probable (71%) |

## Estructura del output
```python
{
    "es_premarket":   float,   # precio actual del ES en premarket
    "spx_prev_close": float,   # cierre del SPX del día anterior
    "gap_points":     float,   # diferencia en puntos, 2 decimales
    "gap_pct":        float,   # diferencia en porcentaje, 4 decimales
    "score":          int,     # -1, 0 o +1
    "signal":         str,     # "GAP_ALCISTA" | "GAP_BAJISTA" | "PLANO"
                               # "GAP_ALCISTA_GRANDE" | "GAP_BAJISTA_GRANDE"
    "status":         str,     # "OK" | "ERROR" | "MISSING_DATA"
    "fecha":          str,     # fecha en formato YYYY-MM-DD
}
```

## Casos de error a manejar

- MCP no disponible o sin respuesta: status = "MISSING_DATA", score = 0
- SPX cierre no disponible en yfinance: status = "MISSING_DATA", score = 0
- ES precio = 0 o None: status = "ERROR", score = 0
- SPX cierre = 0 o None: status = "ERROR", score = 0
- Cualquier excepción no controlada: status = "ERROR", score = 0
- En todos los casos de error el pipeline continúa sin interrumpirse

## Relación con otros indicadores

`fetch_spx_prev_close()` es una función nueva independiente — no comparte datos
con `fetch_vix_term_structure()` aunque ambas usan yfinance.
`fetch_es_quote()` es la primera función del proyecto que llama al MCP de TastyTrade.
Ambas se llaman desde fetch_market_data.py y su output se fusiona en data.json.

## Ubicación del código

- Fetch SPX : scripts/fetch_market_data.py → `fetch_spx_prev_close() -> dict`
- Fetch ES  : scripts/fetch_market_data.py → `fetch_es_quote() -> dict`
- Cálculo   : scripts/calculate_indicators.py → `calc_overnight_gap(spx_data: dict, es_data: dict) -> dict`
- Tests     : tests/test_ind_overnight_gap.py

## Tests a implementar

| Test                        | Input                          | Output esperado                                        |
|-----------------------------|--------------------------------|--------------------------------------------------------|
| Gap alcista moderado        | es=5100.0, spx_close=5080.0   | gap_pct=+0.3937, score=+1, signal="GAP_ALCISTA"        |
| Gap bajista moderado        | es=5060.0, spx_close=5080.0   | gap_pct=-0.3937, score=-1, signal="GAP_BAJISTA"        |
| Gap plano (dentro ±0.10%)   | es=5081.0, spx_close=5080.0   | gap_pct=+0.0197, score=0,  signal="PLANO"              |
| Gap alcista grande          | es=5130.0, spx_close=5080.0   | gap_pct=+0.9843, score=0,  signal="GAP_ALCISTA_GRANDE" |
| Gap bajista grande          | es=5000.0, spx_close=5080.0   | gap_pct=-1.5748, score=0,  signal="GAP_BAJISTA_GRANDE" |
| Límite exacto +0.10%        | es=5085.08, spx_close=5080.0  | gap_pct=+0.1000, score=+1, signal="GAP_ALCISTA"        |
| Límite exacto +0.50%        | es=5105.40, spx_close=5080.0  | gap_pct=+0.5000, score=+1, signal="GAP_ALCISTA"        |
| Límite exacto -0.50%        | es=5054.60, spx_close=5080.0  | gap_pct=-0.5000, score=-1, signal="GAP_BAJISTA"        |
| ES precio None              | es=None, spx_close=5080.0     | score=0, status="MISSING_DATA"                         |
| SPX cierre None             | es=5100.0, spx_close=None     | score=0, status="MISSING_DATA"                         |
| ES precio = 0               | es=0, spx_close=5080.0        | score=0, status="ERROR"                                |
| SPX cierre = 0              | es=5100.0, spx_close=0        | score=0, status="ERROR"                                |

## Prompt de inicio para Claude Code
```
Lee specs/ind_overnight_gap.md completamente antes de escribir ningún código.

Implementa en este orden exacto:

1. fetch_spx_prev_close() en scripts/fetch_market_data.py
   Descarga el historial de ^GSPC de yfinance con period="5d".
   Toma el último cierre disponible (dropna().iloc[-1]).
   Devuelve un dict con claves: spx_prev_close (float), fecha (str), status (str).
   Maneja errores devolviendo status="MISSING_DATA" y spx_prev_close=None.

2. fetch_es_quote() en scripts/fetch_market_data.py
   Llama al MCP de TastyTrade con get_quotes y símbolo /ES.
   Extrae el precio `last` del dict devuelto (fallback a `mark` si `last` es None o 0).
   Devuelve un dict con claves: es_premarket (float), fecha (str), status (str).
   Si el MCP no responde o el precio es inválido: status="MISSING_DATA", es_premarket=None.

3. calc_overnight_gap() en scripts/calculate_indicators.py
   Recibe dos dicts: spx_data (de fetch_spx_prev_close) y es_data (de fetch_es_quote).
   Aplica la fórmula y la tabla de scoring del spec.
   Devuelve el dict de output definido en el spec.

4. tests/test_ind_overnight_gap.py
   Cubre todos los casos de la tabla de tests del spec.
   Usa valores mock, sin llamadas reales a yfinance ni al MCP.

5. Ejecuta los tests con: uv run pytest tests/test_ind_overnight_gap.py -v
   Confirma que todos pasan antes de terminar.

No implementes nada fuera de lo descrito en el spec.
```
