# Spec: Indicador Net GEX (D-Score — IND-03 e IND-04)

## Estado

- [ ] Implementado

## Qué mide

El Net GEX (Gamma Exposure) cuantifica la presión de cobertura delta que los market makers (MM)
ejercen mecánicamente sobre el SPX. Es el indicador más importante del sistema.

Cuando un inversor compra una call o una put, el MM queda expuesto a riesgo direccional y lo
neutraliza comprando/vendiendo el subyacente (delta hedging). La gamma determina la velocidad
a la que tienen que reajustar ese hedge cuando el precio se mueve.

El GEX agrega toda esa presión en dólares:

- **GEX positivo** → MM long gamma → compran en caídas, venden en subidas → sesión mean-reverting/estable
- **GEX negativo** → MM short gamma → venden en caídas, compran en subidas → sesión trending/inestable

Produce dos scores para el D-Score (IND-03 y IND-04) y tres niveles clave como subproducto.

## Fuente de datos

### Cadena de opciones — nueva función `fetch_option_chain()`

**Símbolo:** SPXW (opciones semanales del SPX, incluyen 0DTE)
**Vencimientos:** hoy + los 5 días naturales siguientes (captura 0DTE + weekly más cercano)
**Campos necesarios por contrato:** `strike`, `option_type` (C/P), `open_interest`, `gamma`, `iv`

```python
def fetch_option_chain(symbol: str = "SPXW", days_ahead: int = 5) -> dict:
    """
    Obtiene la cadena completa de opciones SPXW para hoy + los próximos days_ahead días.
    Usa la herramienta MCP get_option_chain de TastyTrade.

    Returns:
        {
            "contracts": list[dict],  # [{strike, option_type, expiry, open_interest, gamma, iv}, ...]
            "expiries":  list[str],   # fechas procesadas en formato YYYY-MM-DD
            "n_contracts": int,
            "status":    str,         # "OK" | "ERROR" | "EMPTY_CHAIN"
        }
    """
```

**Gamma:** usar el valor del broker si está disponible. Si `gamma` es `None` o `0` para un contrato
con `iv > 0`, calcular con Black-Scholes (ver sección de gamma sintética).

### Spot del SPX — reutilizar de data.json

**No hacer una segunda llamada a get_quotes.** El campo `spx_spot` se añade a `data.json` durante
la implementación, obtenido de la misma llamada que el quote de ES premarket usando `$SPX.X`.

## Fórmula

### GEX por contrato

```
GEX_contrato = gamma × open_interest × 100 × spot² / 1_000_000_000
               × (+1 si call, -1 si put)
```

El divisor 1B convierte el resultado a miles de millones de dólares (billions).

### GEX por strike

```
gex_by_strike[strike] = Σ GEX_contrato  (todos los vencimientos, mismo strike)
```

### Net GEX total

```
net_gex = Σ gex_by_strike  (todos los strikes)
```

### Gamma sintética con Black-Scholes (fallback)

Si el broker no devuelve gamma para un contrato (`gamma` es `None` o `0` con `iv > 0`):

```
T  = días_hasta_vencimiento / 365.25
d1 = (ln(spot/strike) + (r + 0.5 × iv²) × T) / (iv × √T)
gamma = N'(d1) / (spot × iv × √T)
```

Donde:
- `r = 0.05` (tipo libre de riesgo aproximado)
- `iv` = volatilidad implícita como decimal (0.15 para 15%)
- `N'(d1)` = densidad de la distribución normal estándar evaluada en d1
- Si `T ≤ 0` o `iv ≤ 0` → `gamma = 0` (contrato expirado o sin datos)

### Subindicadores derivados

**Flip Level** — frontera entre régimen long y short gamma:
```
gex_cum = cumsum(gex_by_strike ordenado ascendente por strike)
flip_level = primer strike donde gex_cum cruza de negativo a positivo
```
Si el GEX acumulado nunca cruza cero → `flip_level = None`

**Put Wall** — mayor concentración de puts (soporte gravitacional):
```
put_wall = strike donde gex_by_strike es mínimo (valor más negativo)
```

**Call Wall** — mayor concentración de calls (resistencia):
```
call_wall = strike donde gex_by_strike es máximo (valor más positivo)
```

**Max Pain** — precio de mínimo valor intrínseco para compradores (solo 0DTE):
```
para cada strike_candidato en strikes con OI > 0 del vencimiento de hoy:
    pain = Σ max(strike_candidato - strike, 0) × OI_puts × 100    (puts ITM)
           + Σ max(strike - strike_candidato, 0) × OI_calls × 100 (calls ITM)
max_pain = strike_candidato que minimiza pain total
```
El max pain usa **solo el vencimiento de hoy** (0DTE); los vencimientos posteriores no se incluyen.

## Scoring

### IND-03: Score por Net GEX

| net_gex_bn      | Score | Signal               |
|-----------------|-------|----------------------|
| > +2B           | +3    | LONG_GAMMA_FUERTE    |
| 0 a +2B         | +1    | LONG_GAMMA_SUAVE     |
| -2B a 0         | -1    | SHORT_GAMMA_SUAVE    |
| < -2B           | -3    | SHORT_GAMMA_FUERTE   |

### IND-04: Score por Flip Level

| Condición             | Score | Signal     |
|-----------------------|-------|------------|
| spot > flip_level     | +2    | SOBRE_FLIP |
| spot < flip_level     | -2    | BAJO_FLIP  |
| flip_level = None     | 0     | SIN_FLIP   |

**Umbrales configurables** — definir como constantes al inicio de `calculate_indicators.py`
para facilitar calibración una vez haya datos reales del MCP:

```python
GEX_UMBRAL_FUERTE = 2.0   # billions — umbral long/short gamma fuerte vs suave
```

## Output

```python
{
    # Net GEX global
    "net_gex_bn":    float,   # GEX neto total en billions $
    "score_gex":     int,     # -3, -1, +1 o +3
    "signal_gex":    str,     # "LONG_GAMMA_FUERTE" | "LONG_GAMMA_SUAVE"
                              # "SHORT_GAMMA_SUAVE" | "SHORT_GAMMA_FUERTE"

    # Flip Level
    "flip_level":    float,   # strike del flip, None si no existe
    "score_flip":    int,     # -2, 0 o +2
    "signal_flip":   str,     # "SOBRE_FLIP" | "BAJO_FLIP" | "SIN_FLIP"

    # Niveles clave
    "put_wall":      float,   # strike con mayor concentración de puts
    "call_wall":     float,   # strike con mayor concentración de calls
    "max_pain":      float,   # strike de máximo dolor (solo 0DTE)

    # Contexto
    "spot":          float,   # precio del SPX usado en el cálculo
    "n_strikes":     int,     # número de strikes distintos procesados
    "n_expiries":    int,     # número de vencimientos incluidos
    "gamma_source":  str,     # "broker" | "black_scholes" | "mixed"

    # Estado
    "status":        str,     # "OK" | "ERROR" | "MISSING_DATA" | "EMPTY_CHAIN"
    "fecha":         str,     # fecha en formato YYYY-MM-DD
}
```

## Casos de error

| Situación | status | score_gex | score_flip | Comportamiento |
|-----------|--------|-----------|------------|----------------|
| Cadena vacía o MCP sin respuesta | `EMPTY_CHAIN` | 0 | 0 | Pipeline continúa |
| Ningún contrato con gamma ni IV | `ERROR` | 0 | 0 | Pipeline continúa |
| Spot no disponible o None | `MISSING_DATA` | 0 | 0 | Pipeline continúa |
| Flip level no encontrado | `OK` | calculado | 0 / `SIN_FLIP` | Pipeline continúa |
| Cualquier excepción no controlada | `ERROR` | 0 | 0 | Pipeline continúa |

El pipeline **nunca se interrumpe** por un error en este indicador.

En caso de error, los campos numéricos (`net_gex_bn`, `flip_level`, `put_wall`, `call_wall`, `max_pain`) son `None`.

## Integración en el pipeline

### 1. fetch_market_data.py

Añadir `fetch_option_chain()` y obtener `spx_spot`:

```python
# Nueva función
def fetch_option_chain(symbol: str = "SPXW", days_ahead: int = 5) -> dict: ...

# En el bloque principal:
chain_data   = fetch_option_chain("SPXW", days_ahead=5)
data["option_chain"] = chain_data
# spx_spot: añadir $SPX.X a la llamada get_quotes existente de ES premarket
data["spx_spot"] = <valor de $SPX.X del quote>
```

### 2. calculate_indicators.py

Constante configurable al inicio del archivo:
```python
GEX_UMBRAL_FUERTE = 2.0   # billions
```

Nueva función:
```python
def calc_net_gex(chain_data: dict, spot: float, fecha: str) -> dict:
    """
    chain_data: resultado de fetch_option_chain() — dict con clave "contracts"
    spot: precio del SPX (de data["spx_spot"])
    fecha: fecha del análisis en formato YYYY-MM-DD
    """
```

Añadir el resultado al dict de indicadores bajo la clave `"net_gex"`.

### 3. D-Score — actualizar cálculo

```python
# Antes
d_score = vix_vxv_slope["score"] + vix9d_vix_ratio["score"] + overnight_gap["score"]

# Después
d_score = (vix_vxv_slope["score"] + vix9d_vix_ratio["score"]
           + overnight_gap["score"]
           + net_gex["score_gex"] + net_gex["score_flip"])
```

### 4. generate_scorecard.py

Añadir dos filas en la sección D-Score:

```
Net GEX (IND-03)   GEX=+1.23B               +3    LONG_GAMMA_FUERTE
Flip Level (IND-04) Flip=5200  Spot=5215.0   +2    SOBRE_FLIP
```

## Tests a implementar

Ver `tests/test_ind_net_gex.py`. Los tests cubren 6 grupos:

1. **Gamma sintética** (3 tests): `_calc_gamma_bs()` con T>0, T=0, iv=0
2. **Flip Level** (3 tests): detección correcta, GEX siempre positivo (None), spot bajo el flip
3. **Put Wall / Call Wall** (2 tests): concentración correcta con cadena asimétrica
4. **Max Pain** (2 tests): cálculo con cadena sencilla y valor conocido; un único strike
5. **Scoring Net GEX** (4 tests): los cuatro rangos de score_gex
6. **Casos de error** (4 tests): cadena vacía, spot None, sin gamma/IV, excepción sin propagarse

## Verificación

1. Ejecutar `fetch_market_data.py` — `data.json` debe tener `option_chain.n_contracts > 0` y `status: "OK"`.
2. Ejecutar `calculate_indicators.py` — `indicators.json` debe tener `net_gex` con los 14 campos.
3. Verificar que `d_score` = suma de los 5 indicadores (3 previos + score_gex + score_flip).
4. Caso límite: pasar cadena vacía → `status: "EMPTY_CHAIN"`, ambos scores = 0, sin excepción.
5. Verificar `gamma_source`: cadena solo con IV sin gamma → `"black_scholes"` o `"mixed"`.
