# Spec: Integración Net GEX en el D-Score

## Estado

- [ ] Implementado

## Objetivo

Conectar el indicador Net GEX (definido en `specs/ind_net_gex.md`) al pipeline de producción.
Al terminar, el D-Score incluirá cinco contribuyentes:

| Indicador      | Score range | Clave en indicators.json |
|----------------|-------------|--------------------------|
| VIX/VXV Slope  | -2 a +2     | `vix_vxv_slope.score`    |
| VIX9D/VIX      | -2 a +2     | `vix9d_vix_ratio.score`  |
| Overnight Gap  | -1 a +1     | `overnight_gap.score`    |
| **Net GEX (IND-03)** | **-3 a +3** | **`net_gex.score_gex`** |
| **Flip Level (IND-04)** | **-2 a +2** | **`net_gex.score_flip`** |

Rango total del D-Score: **-10 a +10** (antes: -5 a +5).

## Archivos a modificar

| Archivo | Cambio |
|---------|--------|
| `scripts/tastytrade_client.py` | Nuevos métodos `get_equity_quote()` y `get_option_chain()` |
| `scripts/fetch_market_data.py` | Nuevas funciones `fetch_spx_spot()` y `fetch_option_chain()` |
| `scripts/calculate_indicators.py` | Constantes GEX, nueva función `calc_net_gex()` y `_calc_gamma_bs()`, actualizar D-Score |
| `scripts/generate_scorecard.py` | Dos filas nuevas en bloque D-SCORE |
| `scripts/run.py` | Añadir llamadas a fetch y cálculo de net_gex; sincronizar con atr_ratio |

---

## 1. tastytrade_client.py — nuevos métodos

### 1a. `get_equity_quote(symbol)` — spot del SPX

Obtiene el quote de un equity/index via DXLink streaming.
El SPX no cotiza premarket, así que se obtiene el último precio del día anterior (`last` o `mark`).

```python
def get_equity_quote(self, streamer_symbol: str) -> dict:
    """
    Obtiene bid/ask/last de un equity o index por su símbolo DXLink.

    Args:
        streamer_symbol: símbolo DXLink, ej. "$SPX.X" para el SPX

    Returns:
        {
            "symbol": str,
            "last":   float,
            "mark":   float,
            "bid":    float,
            "ask":    float,
            "status": str,   # "OK" | "ERROR" | "MISSING_DATA"
        }
    """
```

Sigue el mismo patrón async que `_resolve_and_fetch` en `get_future_quote()`,
pero sin resolución de contrato: suscribe directamente a `Quote` con el símbolo recibido.

### 1b. `get_option_chain(symbol, expiry)` — cadena de opciones

Obtiene la cadena completa de opciones para un símbolo y una fecha de vencimiento.

```python
def get_option_chain(self, symbol: str, expiry: str) -> list[dict]:
    """
    Devuelve la cadena de opciones para (symbol, expiry).

    Args:
        symbol: ej. "SPXW"
        expiry: fecha en formato "YYYY-MM-DD"

    Returns:
        lista de contratos, cada uno con:
        {
            "strike":       float,
            "option_type":  str,   # "C" o "P"
            "expiry":       str,   # "YYYY-MM-DD"
            "open_interest": int,
            "gamma":        float | None,
            "iv":           float | None,   # volatilidad implícita como decimal
        }
        Lista vacía si no hay datos.
    """
```

Usa `tastytrade.instruments.NestedOptionChain` para obtener los strikes y contratos,
y `tastytrade.dxfeed.Greeks` / `Summary` via DXLink para obtener gamma e IV por contrato.

**Nota:** si el broker no devuelve gamma para un contrato pero devuelve IV, dejar `gamma=None`
para que `calc_net_gex()` aplique el fallback Black-Scholes.

---

## 2. fetch_market_data.py — nuevas funciones

### 2a. `fetch_spx_spot()` — precio de referencia del SPX

```python
def fetch_spx_spot() -> dict:
    """
    Obtiene el precio de referencia del SPX vía TastyTradeClient.get_equity_quote("$SPX.X").
    Fallback: último cierre de ^GSPC desde yfinance si el SDK no está disponible.

    Returns:
        {
            "spx_spot": float | None,
            "fecha":    str,
            "source":   str,   # "tastytrade" | "yfinance"
            "status":   str,   # "OK" | "ERROR" | "MISSING_DATA"
        }
    """
```

**Prioridad de fuente:**
1. TastyTrade SDK → `get_equity_quote("$SPX.X")`, campo `last` si > 0, si no `mark`
2. yfinance fallback → `^GSPC` period="2d", último cierre disponible

La fuente se registra en `"source"` para trazabilidad. El GEX es insensible a diferencias
de ±0.5% en el spot, así que el cierre de yfinance es aceptable si el SDK falla.

### 2b. `fetch_option_chain(symbol, days_ahead)` — cadena SPXW

```python
def fetch_option_chain(symbol: str = "SPXW", days_ahead: int = 5) -> dict:
    """
    Obtiene la cadena de opciones para hoy + los próximos days_ahead días naturales.
    Llama a TastyTradeClient.get_option_chain() por cada fecha de vencimiento.

    Returns:
        {
            "contracts":   list[dict],  # todos los contratos de todos los vencimientos
            "expiries":    list[str],   # fechas procesadas, formato YYYY-MM-DD
            "n_contracts": int,
            "status":      str,         # "OK" | "ERROR" | "EMPTY_CHAIN"
        }
    """
```

Itera sobre `[hoy, hoy+1, hoy+2, ..., hoy+days_ahead]` (días naturales).
Ignora silenciosamente vencimientos sin contratos (fines de semana, no hay 0DTE).
Si ningún vencimiento devuelve contratos → `status = "EMPTY_CHAIN"`.

### 2c. Integración en el bloque `__main__` de fetch_market_data.py

```python
# Añadir tras fetch_spx_ohlcv():
spx_spot_data   = fetch_spx_spot()
option_chain    = fetch_option_chain("SPXW", days_ahead=5)

data["spx_spot"]      = spx_spot_data.get("spx_spot")
data["option_chain"]  = option_chain
```

El campo `data["spx_spot"]` es un `float | None` directamente (no un dict anidado)
para simplificar el acceso en `calc_net_gex()`.

---

## 3. calculate_indicators.py — `calc_net_gex()` y actualización D-Score

### 3a. Constantes configurables (inicio del archivo)

```python
# --- Umbrales Net GEX (ajustar con datos reales una vez en producción) ---
GEX_UMBRAL_FUERTE = 2.0   # billions — separa long/short gamma fuerte de suave
```

### 3b. Función privada `_calc_gamma_bs(spot, strike, iv, days_to_exp)`

Calcula gamma sintética con Black-Scholes cuando el broker no la devuelve:

```python
def _calc_gamma_bs(spot: float, strike: float, iv: float, days_to_exp: int) -> float:
    """
    Gamma Black-Scholes para una opción europea.
    Devuelve 0.0 si T <= 0 o iv <= 0 (contrato expirado o sin datos).

    Parámetros: r=0.05 (tipo libre de riesgo fijo), T=days_to_exp/365.25
    """
    import math
    from scipy.stats import norm

    T = days_to_exp / 365.25
    r = 0.05
    if T <= 0 or iv <= 0:
        return 0.0
    d1 = (math.log(spot / strike) + (r + 0.5 * iv**2) * T) / (iv * math.sqrt(T))
    return norm.pdf(d1) / (spot * iv * math.sqrt(T))
```

### 3c. Función `calc_net_gex(chain_data, spot, fecha)`

```python
def calc_net_gex(chain_data: dict, spot: float, fecha: str) -> dict:
    """
    Calcula Net GEX, flip level, put/call wall y max pain a partir de la cadena
    de opciones SPXW.

    Args:
        chain_data: resultado de fetch_option_chain() — dict con "contracts", "expiries", "status"
        spot:       precio del SPX (float o None)
        fecha:      fecha del análisis "YYYY-MM-DD"
    """
```

**Estructura interna del cálculo:**

```
1. Validaciones rápidas:
   - chain_data["status"] == "EMPTY_CHAIN" o contracts vacío → EMPTY_CHAIN
   - spot es None o <= 0                                      → MISSING_DATA
   - chain_data["status"] == "ERROR"                          → ERROR (propagar)

2. Por cada contrato:
   a. Determinar gamma:
      - Si contrato["gamma"] no es None y > 0 → usar, source="broker"
      - Si no, calcular _calc_gamma_bs(spot, strike, iv, days_to_exp) → source="black_scholes"
      - days_to_exp = (date.fromisoformat(expiry) - date.fromisoformat(fecha)).days
   b. Calcular GEX del contrato:
      sign = +1 si option_type=="C", -1 si option_type=="P"
      gex  = gamma × oi × 100 × spot² / 1e9 × sign
   c. Acumular en gex_by_strike[strike] += gex

3. Si todos los GEX calculados son 0 (sin gamma ni IV válidos) → ERROR

4. Net GEX total: net_gex_bn = sum(gex_by_strike.values())

5. Flip level:
   strikes_sorted = sorted(gex_by_strike.keys())
   gex_cum = cumsum por strike ascendente
   flip_level = primer strike donde gex_cum >= 0 (habiendo partido de negativo)
   Si gex_cum nunca es negativo → flip_level = None

6. Put wall:  strike con gex_by_strike mínimo (más negativo)
   Call wall: strike con gex_by_strike máximo (más positivo)

7. Max pain (solo contratos con expiry == fecha):
   para cada strike_candidato: pain = Σ puts_itm + Σ calls_itm
   max_pain = strike_candidato con pain mínimo

8. Scoring:
   score_gex:  net_gex_bn > GEX_UMBRAL_FUERTE → +3
               net_gex_bn > 0                 → +1
               net_gex_bn >= -GEX_UMBRAL_FUERTE → -1
               else                           → -3
   score_flip: spot > flip_level → +2 / spot < flip_level → -2 / None → 0

9. gamma_source: "broker" si todos broker, "black_scholes" si todos BS, "mixed" si mezcla
```

### 3d. Actualización del D-Score

En el bloque `__main__` de `calculate_indicators.py`:

```python
# Importar calc_net_gex al inicio del bloque
net_gex = calc_net_gex(
    data.get("option_chain", {}),
    spot=data.get("spx_spot"),
    fecha=data.get("fecha"),
)

# D-Score actualizado
d_score = (slope["score"] + ratio["score"] + gap["score"]
           + net_gex["score_gex"] + net_gex["score_flip"])

# Añadir al dict de indicadores
indicators["net_gex"] = net_gex
```

---

## 4. generate_scorecard.py — dos filas nuevas en D-SCORE

Añadir en `print_scorecard()`, justo antes del separador `print(line)` del bloque D-SCORE:

```python
# Net GEX (IND-03)
net_gex   = indicators.get("net_gex", {})
gex_status = net_gex.get("status", "ERROR")
if gex_status == "OK":
    gex_bn  = net_gex.get("net_gex_bn")
    gex_val = f"GEX={gex_bn:+.2f}B"
else:
    gex_val = f"[{gex_status}]"
gex_score  = net_gex.get("score_gex", 0)
gex_signal = net_gex.get("signal_gex", "N/A")
print(f"  {'Net GEX':<20} {gex_val:<26} {_sign(gex_score):<6} {gex_signal}")

# Flip Level (IND-04)
flip_level = net_gex.get("flip_level")
flip_status = net_gex.get("status", "ERROR")
if flip_status == "OK" and flip_level is not None:
    spot_val = net_gex.get("spot")
    flip_val = f"Flip={flip_level:.0f}  Spot={spot_val:.0f}"
elif flip_status == "OK":
    flip_val = "SIN_FLIP"
else:
    flip_val = f"[{flip_status}]"
flip_score  = net_gex.get("score_flip", 0)
flip_signal = net_gex.get("signal_flip", "N/A")
print(f"  {'Flip Level':<20} {flip_val:<26} {_sign(flip_score):<6} {flip_signal}")
```

Resultado esperado en terminal:
```
  [D-SCORE — DIRECCIONAL]
  Indicador            Valor                      Score  Signal
  --------------------------------------------------------------
  VIX/VXV Slope        VIX=17.5  VXV=19.2         +1    CONTANGO_SUAVE
  VIX9D/VIX Ratio      VIX9D=14.1  VIX=17.5       +2    CONTANGO_FUERTE
  Overnight Gap        Gap=+0.18%                  +1    GAP_ALCISTA
  Net GEX              GEX=+1.43B                  +1    LONG_GAMMA_SUAVE
  Flip Level           Flip=5200  Spot=5215         +2    SOBRE_FLIP
  --------------------------------------------------------------
  D-Score (direccional):  +7
```

---

## 5. run.py — sincronización completa

`run.py` está actualmente detrás de `calculate_indicators.py __main__` (no incluye `atr_ratio`
ni `net_gex`). Actualizar para quedar en paridad:

```python
from fetch_market_data import (
    fetch_vix_term_structure,
    fetch_vix_history,
    fetch_es_prev_close,
    fetch_es_quote,
    fetch_spx_ohlcv,       # añadir
    fetch_spx_spot,        # añadir
    fetch_option_chain,    # añadir
)
from calculate_indicators import (
    calc_vix_vxv_slope,
    calc_vix9d_vix_ratio,
    calc_ivr,
    calc_overnight_gap,
    calc_atr_ratio,        # añadir
    calc_net_gex,          # añadir
)
```

En `main()`:

```python
# Paso 1: fetch (añadir al bloque existente)
data["spx_ohlcv"]     = fetch_spx_ohlcv()
data["spx_spot"]      = fetch_spx_spot().get("spx_spot")
data["option_chain"]  = fetch_option_chain("SPXW", days_ahead=5)

# Paso 2: calcular indicadores (añadir)
atr_ratio = calc_atr_ratio(data.get("spx_ohlcv", {}))
net_gex   = calc_net_gex(data.get("option_chain", {}), data.get("spx_spot"), data["fecha"])

# D-Score y V-Score actualizados
d_score = (slope["score"] + ratio["score"] + gap["score"]
           + net_gex["score_gex"] + net_gex["score_flip"])
v_score = ivr["score"] + atr_ratio["score"]

# Añadir al dict de indicadores
indicators["atr_ratio"] = atr_ratio
indicators["net_gex"]   = net_gex
```

---

## Verificación

1. Ejecutar `python scripts/fetch_market_data.py` — `data.json` debe tener:
   - `option_chain.n_contracts > 0`, `option_chain.status = "OK"`
   - `spx_spot` como float > 0

2. Ejecutar `python scripts/calculate_indicators.py` — `indicators.json` debe tener:
   - `net_gex` con 14 campos, `status = "OK"`
   - `net_gex.n_strikes > 0`, `net_gex.gamma_source` en `{"broker","black_scholes","mixed"}`
   - `d_score` = suma de los 5 scores

3. Ejecutar `python scripts/run.py` — scorecard en terminal con 5 filas en D-SCORE.

4. Caso error: desactivar credenciales TastyTrade → `option_chain.status = "MISSING_DATA"`,
   `net_gex.status = "MISSING_DATA"`, ambos scores = 0, pipeline sin excepción, scorecard
   muestra `[MISSING_DATA]` en las filas Net GEX y Flip Level.

5. Verificar gamma sintética: forzar contratos sin gamma (gamma=None) con IV válido →
   `gamma_source = "black_scholes"`, GEX calculado > 0.

---

## Notas de implementación

- `scipy` es nueva dependencia (para `norm.pdf` en Black-Scholes). Añadir a `pyproject.toml`.
- La llamada a `get_option_chain()` puede ser lenta si el broker devuelve muchos strikes.
  Limitar a strikes con `open_interest > 0` para reducir el volumen de datos DXLink.
- El max pain solo usa contratos con `expiry == fecha` (0DTE). Validar que `fecha` está en
  ISO format antes de comparar.
- `GEX_UMBRAL_FUERTE = 2.0` es orientativo. Dejar como constante al inicio de
  `calculate_indicators.py` para ajuste fácil tras los primeros días de datos reales.
