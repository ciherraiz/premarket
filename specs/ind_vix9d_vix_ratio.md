# SPEC — IND: VIX9D/VIX Short-Term Ratio

## Estado
[ ] En desarrollo

## Objetivo
Calcular el ratio entre la volatilidad implícita a 9 días (VIX9D) y la volatilidad
implícita a 30 días (VIX) para determinar si la estructura temporal de volatilidad
está en contango o backwardation, y asignar un score direccional.

## Contexto
El VIX9D y el VIX son índices publicados por el CBOE que miden la volatilidad
implícita del SPX a 9 y 30 días respectivamente. Cuando VIX9D > VIX el mercado
está pagando más por protección inmediata que por protección a 30 días — señal
de estrés de muy corto plazo. Cuando VIX9D < VIX el entorno es tranquilo y el
sesgo estadístico es alcista.

## Fuente de datos
- Proveedor : yfinance
- Tickers   : ^VIX9D y ^VIX
- Frecuencia: diario (cierre del día anterior)
- Periodo   : últimos 5 días (para tener margen si hay festivos)

## Fórmula
```
ratio = VIX9D_close / VIX_close
```

## Tabla de scoring

| Condición         | Score | Interpretación                        |
|-------------------|-------|---------------------------------------|
| ratio < 0.88      | +2    | Contango pronunciado → sesgo alcista  |
| 0.88 ≤ ratio < 1.02 |  0  | Neutro                                |
| 1.02 ≤ ratio < 1.05 | -1  | Tensión incipiente                    |
| ratio ≥ 1.05      | -2    | Backwardation → sesgo bajista         |

## Estructura del output
```python
{
    "vix9d": float,          # valor absoluto del VIX9D
    "vix": float,            # valor absoluto del VIX
    "ratio": float,          # VIX9D / VIX, redondeado a 4 decimales
    "score": int,            # -2, -1, 0 o +2
    "signal": str,           # "CONTANGO_FUERTE" | "NEUTRO" | "TENSION" | "BACKWARDATION"
    "status": str,           # "OK" | "ERROR" | "MISSING_DATA"
    "fecha": str,            # fecha del dato en formato YYYY-MM-DD
}
```

## Casos de error a manejar

- yfinance no devuelve dato (mercado cerrado, festivo): status = "MISSING_DATA", score = 0
- VIX = 0 (división por cero): status = "ERROR", score = 0
- Cualquier excepción no controlada: status = "ERROR", score = 0
- En todos los casos de error el pipeline debe continuar sin interrumpirse

## Ubicación del código
- Función principal : `scripts/calculate_indicators.py` → `calc_vix9d_vix_ratio(vix_current: dict) -> dict`
- Fetch de datos    : `scripts/fetch_market_data.py` → `fetch_vix_term_structure() -> dict`
- El fetch ya recoge VIX9D y VIX junto con VXV y VVIX en una sola llamada a yfinance

## Tests a implementar
`tests/test_ind_vix9d_vix_ratio.py`

| Test | Input | Output esperado |
|---|---|---|
| Contango pronunciado | vix9d=13.5, vix=16.2 | ratio=0.8333, score=+2, signal="CONTANGO_FUERTE" |
| Neutro | vix9d=15.8, vix=16.2 | ratio=0.9753, score=0, signal="NEUTRO" |
| Tensión incipiente | vix9d=16.53, vix=16.2 | ratio=1.0204, score=-1, signal="TENSION" |
| Backwardation | vix9d=17.5, vix=16.2 | ratio=1.0802, score=-2, signal="BACKWARDATION" |
| VIX = 0 | vix9d=15.0, vix=0 | score=0, status="ERROR" |
| Dato ausente | vix9d=None, vix=16.2 | score=0, status="MISSING_DATA" |

## Prompt de inicio para Claude Code
```
Lee specs/ind_vix9d_vix_ratio.md completamente.

Implementa lo siguiente en este orden:
1. La función fetch_vix_term_structure() en scripts/fetch_market_data.py
   que descargue VIX9D, VIX, VXV y VVIX de yfinance
2. La función calc_vix9d_vix_ratio() en scripts/calculate_indicators.py
   con el scoring exacto de la tabla del spec
3. Los tests en tests/test_ind02_vix9d_vix_ratio.py cubriendo todos
   los casos de la tabla de tests
4. Ejecuta los tests y confirma que todos pasan

No implementes nada más allá de lo descrito en el spec.
```