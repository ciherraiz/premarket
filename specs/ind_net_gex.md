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
**Campos necesarios por contrato:** `strike`, `option_type` (C/P), `open_interest`, `gamma`

Se llama **dos veces** con distintos rangos de vencimiento:

| Llamada | `days_ahead` | Uso |
|---------|-------------|-----|
| 0DTE | `0` (solo hoy) | flip_level, put_wall, call_wall, max_pain |
| Multi-día | `5` (hoy + 5 días naturales) | net_gex_bn total |

Rationale: los niveles intraday (flip, walls, max_pain) reflejan la presión de hedging de opciones
que expiran **hoy** — mezclar el weekly contamina los niveles con gamma que no colapsa intraday.
El régimen GEX (signo) necesita el posicionamiento total del dealer, por eso usa la term structure completa.

```python
def fetch_option_chain(symbol: str = "SPXW", days_ahead: int = 0) -> dict:
    """
    Obtiene la cadena completa de opciones SPXW para hoy + los próximos days_ahead días.
    Usa la herramienta MCP get_option_chain de TastyTrade.

    Returns:
        {
            "contracts": list[dict],  # [{strike, option_type, expiry, open_interest, gamma}, ...]
            "expiries":  list[str],   # fechas procesadas en formato YYYY-MM-DD
            "n_contracts": int,
            "status":    str,         # "OK" | "ERROR" | "EMPTY_CHAIN"
        }
    """
```

**Gamma:** usar el valor del broker directamente. Si `gamma` es `None` o `0` para un contrato,
ese contrato se excluye del cálculo (contribución GEX = 0). No hay fallback Black-Scholes
porque el SDK de TastyTrade devuelve gamma vía `Greeks` de DXLink.

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

### GEX por strike — cadena 0DTE

```
gex_by_strike_0dte[strike] = Σ GEX_contrato  (solo vencimiento de hoy)
```

### GEX por strike — cadena multi-día

```
gex_by_strike_all[strike] = Σ GEX_contrato  (todos los vencimientos)
```

### Net GEX total

```
net_gex = Σ gex_by_strike_all  (todos los strikes, cadena multi-día)
```

### Subindicadores derivados (usan cadena 0DTE)

**Flip Level** — frontera entre régimen long y short gamma (cadena 0DTE):
```
gex_cum = cumsum(gex_by_strike_0dte ordenado ascendente por strike)
flip_level = primer strike donde gex_cum cruza de negativo a positivo
```
Si el GEX acumulado nunca cruza cero → `flip_level = None`

**Put Wall** — mayor concentración de puts, soporte gravitacional (cadena 0DTE):
```
put_wall = strike donde gex_by_strike_0dte es mínimo (valor más negativo)
```

**Call Wall** — mayor concentración de calls, resistencia (cadena 0DTE):
```
call_wall = strike donde gex_by_strike_0dte es máximo (valor más positivo)
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
| > +15B          | +3    | LONG_GAMMA_FUERTE    |
| 0 a +15B        | +1    | LONG_GAMMA_SUAVE     |
| -5B a 0         | -1    | SHORT_GAMMA_SUAVE    |
| < -5B           | -3    | SHORT_GAMMA_FUERTE   |

Nota: el SPX tiene OI masivo — los valores típicos son decenas de billions en días normales,
y pueden bajar a terreno negativo (-5B a -20B) en días de alta volatilidad.
Fuente de referencia para calibración inicial: SpotGamma / SqueezeMetrics.

### IND-04: Score por Flip Level

| Condición             | Score | Signal     |
|-----------------------|-------|------------|
| spot > flip_level     | +2    | SOBRE_FLIP |
| spot < flip_level     | -2    | BAJO_FLIP  |
| flip_level = None     | 0     | SIN_FLIP   |

**Umbrales configurables** — definir como constantes al inicio de `calculate_indicators.py`
para facilitar calibración una vez haya datos reales del MCP:

```python
GEX_UMBRAL_FUERTE  = 15.0   # billions — long gamma fuerte
GEX_UMBRAL_NEGATIVO = 5.0   # billions — short gamma fuerte (valor absoluto)
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
    "n_strikes":     int,     # número de strikes distintos procesados (cadena 0DTE)
    "n_expiries":    int,     # número de vencimientos incluidos (cadena multi-día)

    # Estado
    "status":        str,     # "OK" | "ERROR" | "MISSING_DATA" | "EMPTY_CHAIN"
    "fecha":         str,     # fecha en formato YYYY-MM-DD
}
```

## Casos de error

| Situación | status | score_gex | score_flip | Comportamiento |
|-----------|--------|-----------|------------|----------------|
| Cadena vacía o MCP sin respuesta | `EMPTY_CHAIN` | 0 | 0 | Pipeline continúa |
| Ningún contrato con gamma válida | `ERROR` | 0 | 0 | Pipeline continúa |
| Spot no disponible o None | `MISSING_DATA` | 0 | 0 | Pipeline continúa |
| Flip level no encontrado | `OK` | calculado | 0 / `SIN_FLIP` | Pipeline continúa |
| Cualquier excepción no controlada | `ERROR` | 0 | 0 | Pipeline continúa |

El pipeline **nunca se interrumpe** por un error en este indicador.

En caso de error, los campos numéricos (`net_gex_bn`, `flip_level`, `put_wall`, `call_wall`, `max_pain`) son `None`.

## Integración en el pipeline

### 1. fetch_market_data.py

Añadir `fetch_option_chain()` y obtener `spx_spot`. Se llama **dos veces**:

```python
# Nueva función
def fetch_option_chain(symbol: str = "SPXW", days_ahead: int = 0) -> dict: ...

# En el bloque principal:
chain_0dte  = fetch_option_chain("SPXW", days_ahead=0)  # niveles intraday
chain_multi = fetch_option_chain("SPXW", days_ahead=5)  # régimen GEX

data["option_chain_0dte"]  = chain_0dte
data["option_chain_multi"] = chain_multi

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
def calc_net_gex(chain_0dte: dict, chain_multi: dict, spot: float, fecha: str) -> dict:
    """
    chain_0dte:  resultado de fetch_option_chain(days_ahead=0) — niveles intraday
    chain_multi: resultado de fetch_option_chain(days_ahead=5) — régimen GEX
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

Ver `tests/test_ind_net_gex.py`. Los tests cubren 5 grupos:

1. **Flip Level** (3 tests): detección correcta, GEX siempre positivo (None), spot bajo el flip
2. **Put Wall / Call Wall** (2 tests): concentración correcta con cadena asimétrica
3. **Max Pain** (2 tests): cálculo con cadena sencilla y valor conocido; un único strike
4. **Scoring Net GEX** (4 tests): los cuatro rangos de score_gex
5. **Casos de error** (3 tests): cadena vacía, spot None, ningún contrato con gamma válida

Nota: no hay tests de gamma sintética porque el SDK devuelve `gamma` directamente — los contratos
sin gamma simplemente se excluyen del cálculo.

## Verificación

1. Ejecutar `fetch_market_data.py` — `data.json` debe tener `option_chain_0dte.n_contracts > 0`,
   `option_chain_multi.n_contracts > 0` y ambos con `status: "OK"`.
2. Ejecutar `calculate_indicators.py` — `indicators.json` debe tener `net_gex` con los 13 campos.
3. Verificar que `d_score` = suma de los 5 indicadores (3 previos + score_gex + score_flip).
4. Caso límite: pasar cadena vacía → `status: "EMPTY_CHAIN"`, ambos scores = 0, sin excepción.
5. Verificar que `flip_level`, `put_wall`, `call_wall`, `max_pain` se calculan con 0DTE solamente
   (controlar pasando cadenas con distinto número de contratos y comprobar `n_strikes`).
