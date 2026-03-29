# SPEC — IND: IV Rank (IVR)

## Estado
[ ] En desarrollo

## Objetivo
Calcular el IV Rank del VIX para determinar si la volatilidad implícita del SPX
está cara o barata respecto a su rango del último año, y asignar un score de volatilidad.

## Contexto
El IV Rank (IVR) responde a la pregunta: ¿dónde está el VIX hoy dentro de su rango anual?
No predice dirección de mercado. Predice si tiene sentido estructural vender prima.

Un IVR alto significa que las opciones están caras respecto a su historia reciente —
vender crédito es estructuralmente favorable porque el comprador paga una prima elevada.
Un IVR bajo significa que las opciones están baratas — vender crédito tiene poco margen
de seguridad y el riesgo/beneficio es desfavorable.

Ejemplo: IVR del 70% significa que el VIX está en el percentil 70 de su rango del último año.
IVR del 15% significa que el VIX está casi en mínimos anuales.

Este es el indicador base del bloque de volatilidad (V-Score), complementario al D-Score.

## Fuente de datos
- Proveedor  : yfinance
- Ticker     : ^VIX
- VIX actual : clave `vix` del dict devuelto por `fetch_vix_term_structure()` (ya existe)
- Historial  : nueva función `fetch_vix_history()` — periodo `1y` (≈ 252 días hábiles)
- Frecuencia : diario (cierres del día anterior)

## Fórmula
```
IVR = (VIX_hoy - VIX_mínimo_52w) / (VIX_máximo_52w - VIX_mínimo_52w) × 100
```

## Tabla de scoring

| Condición         | Score | Signal          | Interpretación                              |
|-------------------|-------|-----------------|---------------------------------------------|
| IVR > 60%         | +3    | PRIMA_ALTA      | VIX caro → vender prima muy favorable       |
| 40% ≤ IVR ≤ 60%  | +2    | PRIMA_ELEVADA   | VIX elevado → vender prima favorable        |
| 25% ≤ IVR < 40%  | +1    | PRIMA_NORMAL    | VIX en zona media → vender prima aceptable  |
| 15% ≤ IVR < 25%  |  0    | PRIMA_BAJA      | VIX bajo → sin margen claro                 |
| IVR < 15%         | -2    | PRIMA_MUY_BAJA  | VIX en mínimos → vender prima desfavorable  |

## Estructura del output
```python
{
    "vix": float,          # valor absoluto del VIX actual
    "vix_min_52w": float,  # mínimo del VIX en las últimas 52 semanas
    "vix_max_52w": float,  # máximo del VIX en las últimas 52 semanas
    "ivr": float,          # porcentaje IVR, redondeado a 2 decimales
    "score": int,          # -2, 0, +1, +2 o +3
    "signal": str,         # "PRIMA_ALTA" | "PRIMA_ELEVADA" | "PRIMA_NORMAL"
                           # "PRIMA_BAJA" | "PRIMA_MUY_BAJA"
    "status": str,         # "OK" | "ERROR" | "INSUFFICIENT_DATA"
    "fecha": str,          # fecha del dato en formato YYYY-MM-DD
}
```

## Casos de error a manejar

- Historial con menos de 50 días disponibles: status = "INSUFFICIENT_DATA", score = 0
- VIX_máximo igual a VIX_mínimo (rango cero): status = "ERROR", score = 0
- yfinance no devuelve dato del VIX actual: status = "MISSING_DATA", score = 0
- Cualquier excepción no controlada: status = "ERROR", score = 0
- En todos los casos de error el pipeline continúa sin interrumpirse

## Relación con otros indicadores

El VIX actual se reutiliza del dict devuelto por `fetch_vix_term_structure()` —
no hacer una segunda llamada a yfinance para el dato de hoy.
El historial de 252 días se obtiene con la nueva `fetch_vix_history()`, llamada
separada porque los otros indicadores no necesitan ese volumen de datos históricos.

## Ubicación del código

- Fetch actual : scripts/fetch_market_data.py → `fetch_vix_term_structure()` (existente, clave `vix`)
- Fetch historial: scripts/fetch_market_data.py → `fetch_vix_history()` (nueva)
- Cálculo       : scripts/calculate_indicators.py → `calc_ivr(vix_current: dict, vix_history: dict) -> dict`
- Tests         : tests/test_ind_ivr.py

## Tests a implementar

| Test                     | Input                                          | Output esperado                                   |
|--------------------------|------------------------------------------------|---------------------------------------------------|
| IVR alto (PRIMA_ALTA)    | vix=28.0, min=10.0, max=35.0                  | ivr=72.00, score=+3, signal="PRIMA_ALTA"          |
| IVR elevado              | vix=22.0, min=10.0, max=35.0                  | ivr=48.00, score=+2, signal="PRIMA_ELEVADA"       |
| IVR normal               | vix=18.5, min=10.0, max=35.0                  | ivr=34.00, score=+1, signal="PRIMA_NORMAL"        |
| IVR bajo                 | vix=14.0, min=10.0, max=35.0                  | ivr=16.00, score=0,  signal="PRIMA_BAJA"          |
| IVR muy bajo             | vix=11.0, min=10.0, max=35.0                  | ivr=4.00,  score=-2, signal="PRIMA_MUY_BAJA"      |
| IVR en límite 60%        | vix=25.0, min=10.0, max=35.0                  | ivr=60.00, score=+2, signal="PRIMA_ELEVADA"       |
| IVR en límite 40%        | vix=20.0, min=10.0, max=35.0                  | ivr=40.00, score=+2, signal="PRIMA_ELEVADA"       |
| IVR en límite 25%        | vix=16.25, min=10.0, max=35.0                 | ivr=25.00, score=0,  signal="PRIMA_BAJA"          |
| IVR en límite 15%        | vix=13.75, min=10.0, max=35.0                 | ivr=15.00, score=0,  signal="PRIMA_BAJA"          |
| Rango cero (max == min)  | vix=16.0, min=16.0, max=16.0                  | score=0, status="ERROR"                           |
| Historial insuficiente   | historial con 30 días                         | score=0, status="INSUFFICIENT_DATA"               |
| VIX actual ausente       | vix=None                                      | score=0, status="MISSING_DATA"                    |

## Prompt de inicio para Claude Code
```
Lee specs/ind_ivr.md completamente antes de escribir ningún código.

Implementa en este orden exacto:

1. fetch_vix_history() en scripts/fetch_market_data.py
   Descarga el historial diario de ^VIX de yfinance con period="1y".
   Devuelve un dict con claves: vix_min_52w (float), vix_max_52w (float),
   dias_disponibles (int), fecha (str), status (str).
   Maneja errores devolviendo status="ERROR" y None en los valores numéricos.

2. calc_ivr() en scripts/calculate_indicators.py
   Recibe dos dicts: vix_current (de fetch_vix_term_structure) y
   vix_history (de fetch_vix_history).
   Aplica la fórmula y la tabla de scoring del spec.
   Devuelve el dict de output definido en el spec.

3. tests/test_ind_ivr.py
   Cubre todos los casos de la tabla de tests del spec.
   Usa valores mock, sin llamadas reales a yfinance.

4. Ejecuta los tests con: uv run pytest tests/test_ind_ivr.py -v
   Confirma que todos pasan antes de terminar.

No implementes nada fuera de lo descrito en el spec.
```
