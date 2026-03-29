# SPEC — IND: VIX/VXV Slope Ratio

## Estado
[ ] En desarrollo

## Objetivo
Calcular el ratio entre la volatilidad implícita a 30 días (VIX) y la volatilidad
implícita a 93 días (VXV) para determinar la pendiente de la curva de volatilidad
y asignar un score direccional.

## Contexto
El VIX mide la volatilidad implícita del SPX a 30 días. El VXV hace lo mismo
a 93 días. En condiciones normales de mercado el VXV es mayor que el VIX porque
hay más incertidumbre a largo plazo que a corto — la curva tiene pendiente positiva
y se llama contango. Cuando el VIX supera al VXV la curva se invierte (backwardation),
señalando pánico de corto plazo y estrés en el mercado.

Larry Connors documentó en backtests sobre SPY (2007–2018) que cuando este ratio
es inferior a 0.82 el retorno esperado a 5 días es positivo en el 74% de los casos.
Por encima de 1.0 el retorno esperado es negativo en el 68% de los casos.

Este es el indicador de mayor evidencia empírica del bloque direccional
basado en estructura de volatilidad.

## Fuente de datos
- Proveedor : yfinance
- Tickers   : ^VIX y ^VXV
- Frecuencia: diario (cierre del día anterior)
- Periodo   : últimos 5 días (margen para festivos)

## Fórmula
```
ratio = VIX_close / VXV_close
```

## Tabla de scoring

| Condición              | Score | Signal              | Interpretación                   |
|------------------------|-------|---------------------|----------------------------------|
| ratio < 0.83           | +2    | CONTANGO_FUERTE     | Curva normal pronunciada → alcista |
| 0.83 ≤ ratio < 0.90    | +1    | CONTANGO_SUAVE      | Curva normal suave → leve alcista |
| 0.90 ≤ ratio < 0.96    |  0    | NEUTRO              | Sin señal clara                  |
| 0.96 ≤ ratio < 1.00    | -1    | TENSION             | Curva aplanándose → precaución   |
| ratio ≥ 1.00           | -2    | BACKWARDATION       | Curva invertida → bajista        |

## Estructura del output
```python
{
    "vix": float,      # valor absoluto del VIX
    "vxv": float,      # valor absoluto del VXV
    "ratio": float,    # VIX / VXV, redondeado a 4 decimales
    "score": int,      # -2, -1, 0, +1 o +2
    "signal": str,     # "CONTANGO_FUERTE" | "CONTANGO_SUAVE" | "NEUTRO"
                       # "TENSION" | "BACKWARDATION"
    "status": str,     # "OK" | "ERROR" | "MISSING_DATA"
    "fecha": str,      # fecha del dato en formato YYYY-MM-DD
}
```

## Casos de error a manejar

- yfinance no devuelve dato (festivo, mercado cerrado): status = "MISSING_DATA", score = 0
- VXV = 0 (división por cero): status = "ERROR", score = 0
- Cualquier excepción no controlada: status = "ERROR", score = 0
- En todos los casos de error el pipeline continúa sin interrumpirse

## Relación con otros indicadores

Este indicador comparte la llamada a yfinance con ind_vix9d_vix_ratio y
ind_vvix_percentile. Los tres se nutren de la misma función
fetch_vix_term_structure() que descarga ^VIX9D, ^VIX, ^VXV y ^VVIX
en una única llamada. No hacer llamadas separadas por indicador.

## Ubicación del código

- Fetch     : scripts/fetch_market_data.py  → fetch_vix_term_structure() -> dict
- Cálculo   : scripts/calculate_indicators.py → calc_vix_vxv_slope(vix_current: dict) -> dict
- Tests     : tests/test_ind_vix_vxv_slope.py

## Tests a implementar

| Test                  | Input                  | Output esperado                        |
|-----------------------|------------------------|----------------------------------------|
| Contango fuerte       | vix=13.5, vxv=18.2     | ratio=0.7418, score=+2, signal="CONTANGO_FUERTE" |
| Contango suave        | vix=15.0, vxv=18.2     | ratio=0.8242, score=+1, signal="CONTANGO_SUAVE"  |
| Neutro                | vix=16.5, vxv=18.2     | ratio=0.9066, score=0,  signal="NEUTRO"          |
| Tensión               | vix=17.5, vxv=18.2     | ratio=0.9615, score=-1, signal="TENSION"         |
| Backwardation         | vix=19.0, vxv=18.2     | ratio=1.0440, score=-2, signal="BACKWARDATION"   |
| VXV = 0               | vix=16.0, vxv=0        | score=0, status="ERROR"                          |
| VIX ausente           | vix=None, vxv=18.2     | score=0, status="MISSING_DATA"                   |
| VXV ausente           | vix=16.0, vxv=None     | score=0, status="MISSING_DATA"                   |

## Prompt de inicio para Claude Code
```
Lee specs/ind_vix_vxv_slope.md completamente antes de escribir ningún código.

Implementa en este orden exacto:

1. fetch_vix_term_structure() en scripts/fetch_market_data.py
   Descarga ^VIX9D, ^VIX, ^VXV y ^VVIX de yfinance en una única llamada.
   Devuelve un dict con claves: vix9d, vix, vxv, vvix, fecha.
   Maneja los casos de error devolviendo None en cada campo si falla.

2. calc_vix_vxv_slope() en scripts/calculate_indicators.py
   Recibe el dict de fetch_vix_term_structure().
   Aplica la tabla de scoring del spec.
   Devuelve el dict de output definido en el spec.

3. tests/test_ind_vix_vxv_slope.py
   Cubre todos los casos de la tabla de tests del spec.
   Usa valores mock, sin llamadas reales a yfinance.

4. Ejecuta los tests con: uv run pytest tests/test_ind_vix_vxv_slope.py -v
   Confirma que todos pasan antes de terminar.

No implementes nada fuera de lo descrito en el spec.
```