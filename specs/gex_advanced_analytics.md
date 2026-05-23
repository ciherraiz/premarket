# Spec: GEX Advanced Analytics — Dealer Flow completo al estilo quantedOptions / 42traders

## Estado

- [ ] Fase 1 — Enriquecimiento de datos (delta, charm)
- [ ] Fase 2 — GEX parametrizado por DTE
- [ ] Fase 3 — Nuevos cálculos (Charm Exposure, Delta Exposure, GEX Change, Pinning Zone)
- [ ] Fase 4 — Visualizaciones avanzadas (multi-panel, heatmap charm, GEX change bars)
- [ ] Fase 5 — Narrativa automática (price paths, charm narrative, scorecard enriquecido)

---

## Motivación y contexto

Los traders profesionales de 0DTE (cuentas como @quantedOptions, @42traders) publican
análisis diarios con tres elementos que nuestro sistema actual no tiene:

1. **Charm Exposure** — muestra cómo el delta de los dealers cambia mecánicamente a lo largo
   del día sin que el precio se mueva. En 0DTE, el charm domina desde la apertura: a medida que
   las opciones ATM aceleran su decay, los dealers reajustan el hedge de forma predecible.
   Permite anticipar si el hedging intraday será comprador ("expansivo") o vendedor ("supresivo").

2. **Delta Exposure (DEX)** — agrega el delta total por strike. Complementa el GEX:
   el GEX dice *cuánto reajustan* los dealers cuando el precio se mueve; el DEX dice
   *en qué dirección están posicionados* ahora mismo. Identifica dónde los dealers
   están "atrapados" y necesitan cubrir con más agresividad.

3. **GEX Change intraday** — diferencia del GEX por strike entre el snapshot actual y el anterior.
   Detecta qué strikes están ganando o perdiendo relevancia durante la sesión, antes de que
   el OI oficial se actualice al cierre.

Estos tres elementos, combinados con los que ya tenemos (flip, walls, control node, chop zone),
permiten construir los reportes de "Dealer Flow" que los autores de referencia publican.

---

## Visión del output final

### Reporte premarket (equivale a @quantedOptions)

```
SPX Dealer Flow — Premarket  [fecha]
═══════════════════════════════════════════════════════

RÉGIMEN:  LONG GAMMA FUERTE  Net GEX: +26.6B  (0DTE: +8.2B | ≤7DTE: +19.1B)
Charm:    EXPANSIVO  (+340K delta/hora saliendo al mercado)

NIVELES CLAVE
  Flip Level:    7360   │  Spot sobre flip (+141 pts)
  Call Wall:     7500   │  Distancia: +58 pts  ⚠ CERCA CALL WALL
  Put Wall:      7375   │  Distancia: -126 pts
  Pinning Zone:  7460   │  Charm máximo ATM  (confianza: ALTA)
  Max Pain:      7560
  Chop Zone:     7355 – 7360

CHARM FLOW ESPERADO (09:30 – 16:00)
  09:30  +120K  expansivo
  11:00  +180K  expansivo (pico)
  13:00  +95K   expansivo
  15:00  +40K   neutro
  15:30  −80K   supresivo (decay 0DTE acelera)

POSIBLES PRICE PATHS
  ↑ Alcista:  7430 → 7460 → 7478 → 7500
  ↓ Bajista:  7410 → 7385 → 7360 → 7340
```

### Panel visual premarket (3 columnas, equivale a @quantedOptions)

```
[GEX por strike 0DTE]  [Net GEX intraday por DTE]  [DEX acumulado]
  barras horizontales    serie temporal + bandas       barras ±
  calls=teal, puts=rojo  0DTE / 7DTE / 30DTE           cyan / magenta
```

### Heatmap intraday (equivale a @42traders panel derecho)

```
  [GEX Change por strike]  [Charm Exposure heatmap]
   barras cyan/magenta      X=tiempo, Y=strike, color=intensidad
   delta respecto apertura  muestra flujo de hedging intraday
```

---

## Fase 1 — Enriquecimiento de datos: delta y charm

### Objetivo

Extraer los campos `delta` y `charm` del evento DXLink Greeks que TastyTrade
ya envía para cada contrato. Actualmente solo usamos `gamma` e `iv` de ese evento.
Sin este cambio, las fases 3-5 no tienen datos de entrada.

### Análisis del evento DXLink Greeks

El objeto `Greeks` del SDK de TastyTrade (paquete `tastytrade`) tiene los campos:

```python
Greeks(
    event_type,
    event_symbol,
    price,       # precio del contrato
    volatility,  # IV (ya lo extraemos → campo "iv")
    delta,       # ← NUEVO
    gamma,       # ya lo extraemos → campo "gamma"
    theta,       # decay diario (no necesario ahora)
    vega,        # sensibilidad a IV (no necesario ahora)
    rho,         # sensibilidad a tipos (no necesario ahora)
    # charm no está en Greeks de DXLink como campo independiente:
    # se aproxima numéricamente (ver sección Cálculo de charm)
)
```

**Nota sobre charm**: DXLink no devuelve `charm` (dDelta/dTime) directamente.
Se calcula numéricamente a partir de dos snapshots de delta con distancia temporal
conocida, o bien se aproxima analíticamente con la fórmula Black-Scholes usando
delta, gamma, spot, vol, y tiempo hasta vencimiento. Ver sección de cálculo.

### Archivos a modificar

| Archivo | Cambio |
|---------|--------|
| `scripts/tastytrade_client.py` | Extraer `delta` del evento Greeks |
| `scripts/fetch_market_data.py` | Incluir `delta` en el contrato devuelto |
| `scripts/calculate_indicators.py` | Usar `delta` en cálculos de charm (Fase 3) |

### 1.1 tastytrade_client.py — extracción de delta

**Localización**: función `_fetch_option_chain_async`, bloque de extracción de Greeks
(actualmente lines ~291-294 donde se extrae gamma).

**Cambio**: añadir extracción de delta junto a gamma.

```python
# Antes (solo gamma)
gamma = None
if greek is not None and greek.gamma is not None:
    g = float(greek.gamma)
    gamma = g if g > 0 else None

# Después (gamma + delta)
gamma = None
delta = None
if greek is not None:
    if greek.gamma is not None:
        g = float(greek.gamma)
        gamma = g if g > 0 else None
    if greek.delta is not None:
        delta = float(greek.delta)
        # delta puede ser negativo (puts) o positivo (calls) — no filtrar por signo
```

**Retorno**: añadir `"delta": delta` al dict de cada contrato.

```python
return {
    "strike":        strike_price,
    "option_type":   option_type,
    "expiry":        expiry_str,
    "open_interest": oi,
    "gamma":         gamma,
    "delta":         delta,   # ← NUEVO: float o None
    "iv":            iv,
}
```

### 1.2 fetch_market_data.py — propagación de delta

`fetch_option_chain()` ya construye el contrato a partir del retorno del cliente.
El campo `delta` se propagará automáticamente si el cliente lo incluye.

Verificar que el schema de `data.json` documenta el nuevo campo:

```json
"option_chain_0dte": {
  "contracts": [
    {
      "strike": 7500,
      "option_type": "C",
      "expiry": "2026-05-22",
      "open_interest": 5234,
      "gamma": 0.00015,
      "delta": 0.52,
      "iv": 0.28
    }
  ]
}
```

### 1.3 Cálculo de charm a partir de delta e IV

El charm no se obtiene directamente de TastyTrade. Se calcula analíticamente
con la fórmula Black-Scholes. Para un contrato con delta conocido:

```
charm = -dDelta/dT

Para calls:
  charm_call = -N'(d1) × (2r×T - d2×σ) / (2T×σ√T)

Para puts:
  charm_put  = charm_call  (mismo valor por put-call parity de charm)

Aproximación práctica usando los campos disponibles:
  d1  = (ln(S/K) + (r + 0.5×σ²)×T) / (σ×√T)
  d2  = d1 - σ×√T
  N'(d1) = exp(-d1²/2) / √(2π)

Parámetros:
  S  = spot (spx_spot de data.json)
  K  = strike del contrato
  σ  = iv del contrato
  T  = días hasta vencimiento / 365  (en años)
  r  = 0.05  (tipo libre de riesgo, constante configurable)
```

Esta función se implementa en `calculate_indicators.py` como utilidad interna
`_calc_charm(spot, strike, iv, dte, r=0.05) -> float | None`.

Si `iv` es None o `dte == 0` (contrato expira hoy en décimas de día ≈ fracción)
se usa `dte = 0.5/365` para 0DTE (media sesión restante al momento del cálculo).

---

## Fase 2 — GEX parametrizado por DTE

### Objetivo

Reemplazar la lógica actual de "0DTE" y "multi (5 días)" por un sistema
donde cualquier cálculo GEX acepta un parámetro `max_dte` que agrega todos
los contratos con `DTE ≤ max_dte`. Esto habilita los tres buckets estándar:

| Bucket | max_dte | Uso |
|--------|---------|-----|
| `0dte`  | 0       | Niveles intraday (flip, walls, max pain) — igual que ahora |
| `7dte`  | 7       | Estructura de corto plazo (semana actual) |
| `30dte` | 30      | Posicionamiento estructural del dealer |

### 2.1 fetch_market_data.py — refactorizar fetch_option_chain

**Cambio de firma**: de `days_ahead: int` a `max_dte: int`.

```python
# Antes
def fetch_option_chain(symbol: str = "SPXW", days_ahead: int = 0,
                       max_strikes: int = 60, spot: float | None = None) -> dict:

# Después
def fetch_option_chain(symbol: str = "SPXW", max_dte: int = 0,
                       max_strikes: int = 60, spot: float | None = None) -> dict:
    """
    Obtiene todos los contratos con DTE <= max_dte.

    max_dte=0  → solo el vencimiento de hoy (0DTE)
    max_dte=7  → todos los vencimientos hasta 7 días naturales
    max_dte=30 → todos los vencimientos hasta 30 días naturales

    Para cada vencimiento dentro del rango, obtiene los max_strikes más
    cercanos al spot. El resultado agrega todos los contratos de todos
    los vencimientos en una sola lista.
    """
```

**Lógica interna**: iterar sobre los vencimientos disponibles en la cadena,
filtrar los que cumplan `(expiry_date - today).days <= max_dte`, y llamar
`client.get_option_chain(symbol, expiry, max_strikes, spot)` para cada uno.

**Añadir campo `dte` a cada contrato**:

```python
contract = {
    "strike":        strike_price,
    "option_type":   option_type,
    "expiry":        expiry_str,
    "dte":           (expiry_date - today).days,   # ← NUEVO
    "open_interest": oi,
    "gamma":         gamma,
    "delta":         delta,
    "iv":            iv,
}
```

### 2.2 fetch_market_data.py — tres cadenas en data.json

En el bloque principal, reemplazar las dos llamadas actuales por tres:

```python
# Reemplaza chain_0dte y chain_multi
chain_0dte  = fetch_option_chain("SPXW", max_dte=0,  max_strikes=GEX_MAX_STRIKES, spot=spx_spot)
chain_7dte  = fetch_option_chain("SPXW", max_dte=7,  max_strikes=GEX_MAX_STRIKES, spot=spx_spot)
chain_30dte = fetch_option_chain("SPXW", max_dte=30, max_strikes=GEX_MAX_STRIKES, spot=spx_spot)

data["option_chain_0dte"]  = chain_0dte
data["option_chain_7dte"]  = chain_7dte
data["option_chain_30dte"] = chain_30dte
```

**Eliminar** `data["option_chain_multi"]` (reemplazado por `chain_7dte` y `chain_30dte`).

**Compatibilidad**: en `calculate_indicators.py`, la función `calc_net_gex()` recibe
`chain_0dte` para niveles (sin cambio) y `chain_30dte` para el Net GEX total
(reemplaza `chain_multi`). El campo `chain_7dte` alimenta los nuevos cálculos.

### 2.3 calculate_indicators.py — Net GEX por bucket

Añadir al output de `calc_net_gex()` los valores de Net GEX por bucket:

```python
# Nuevo subcampo en el output
"net_gex_by_dte": {
    "0dte":  float | None,   # GEX solo contratos con DTE=0
    "7dte":  float | None,   # GEX contratos con DTE<=7 (incluye 0DTE)
    "30dte": float | None,   # GEX contratos con DTE<=30 (incluye todos)
}
```

**Rationale**: el Net GEX principal (`net_gex_bn`) usa `chain_30dte` para el régimen
global. El campo `net_gex_by_dte` desglosa la contribución por horizonte, lo que permite
detectar si el posicionamiento dominante es de corto o largo plazo — información
que @quantedOptions usa explícitamente ("Move driven by short term deltas").

### 2.4 Actualizar gex_intraday.py

`take_gex_snapshot()` actualmente llama `fetch_option_chain(days_ahead=0)`.
Actualizar a `fetch_option_chain(max_dte=0)` manteniendo el comportamiento igual.

---

## Fase 3 — Nuevos cálculos

### 3.1 Charm Exposure

#### Qué mide

El charm (dDelta/dTime) de cada contrato indica cuánto delta cede (o gana) ese
contrato por unidad de tiempo. Multiplicado por el OI, da el flujo de hedging
que los dealers necesitan hacer mecánicamente durante la sesión para mantenerse
delta-neutral, sin que el precio se mueva.

- **Charm negativo** (puts OTM, calls OTM en regime normal): dealers *compran*
  delta a lo largo del día para compensar el decay del hedge → soporte mecánico.
- **Charm positivo** (calls ATM cerca de vencimiento): dealers *venden* delta →
  presión bajista mecánica.

En 0DTE, el charm domina la dinámica intraday porque el decay es máximo.

#### Fórmula

```
charm_exposure_strike = Σ charm(S, K, σ, T) × OI × 100 × sign(option_type)

charm_total = Σ charm_exposure_strike  (todos los strikes 0DTE)
```

Unidades: deltas por hora que los dealers deben comprar/vender en conjunto.

#### Implementación

Nueva función en `calculate_indicators.py`:

```python
def calc_charm_exposure(chain_0dte: dict, spot: float, fecha: str) -> dict:
    """
    Calcula la exposición charm por strike y el flujo charm total esperado
    durante la sesión del día.

    Args:
        chain_0dte: cadena de opciones 0DTE con delta e iv por contrato
        spot:       precio spot del SPX
        fecha:      YYYY-MM-DD

    Returns:
        {
            "charm_by_strike":    dict[str, float],  # charm_exposure por strike
            "charm_total":        float | None,       # suma total en deltas/hora
            "charm_signal":       str,                # "EXPANSIVO" | "SUPRESIVO" | "NEUTRO"
            "charm_narrative":    str,                # texto interpretativo
            "charm_pin_zone":     float | None,       # strike de máximo abs(charm) ATM
            "charm_pin_zone_conf": str,               # "ALTA" | "MEDIA" | "BAJA"
            "charm_intraday":     list[dict],         # proyección por hora
            "status":             str,
            "fecha":              str,
        }
    """
```

#### Cálculo de charm_intraday

Proyecta el charm esperado para cada hora de la sesión. El charm varía porque
`T` (tiempo hasta vencimiento en años) decrece durante el día.

```python
# Para cada hora h desde 9:30 hasta 15:30 ET:
#   T_h = (horas restantes hasta 16:00) / (252 × 6.5)
#   charm_h = Σ _calc_charm(spot, K, iv, T_h) × OI × sign × 100
#   charm_intraday[h] = {"hora": "09:30", "charm_delta": charm_h, "signal": ...}
```

```python
# Formato de cada elemento en charm_intraday:
{
    "hora":         "09:30",      # hora ET (cada 30 min)
    "charm_delta":  +120_000,     # deltas que los dealers compran (+) o venden (-)
    "signal":       "EXPANSIVO"   # "EXPANSIVO" | "SUPRESIVO" | "NEUTRO"
}
```

#### Charm Pin Zone

El strike con mayor `abs(charm_exposure)` dentro de un rango ±50 pts del spot.
Es la zona donde el hedging inducido por tiempo es máximo → el mercado tiende
a ser "atraído" a ese strike cuando el charm es el driver dominante.

```python
atm_strikes = {k: v for k, v in charm_by_strike.items()
               if abs(k - spot) <= 50}
charm_pin_zone = max(atm_strikes, key=lambda k: abs(atm_strikes[k]))

# Confianza basada en concentración relativa del charm ATM:
charm_atm_ratio = abs(charm_by_strike[charm_pin_zone]) / abs(charm_total)
charm_pin_zone_conf = (
    "ALTA"  if charm_atm_ratio > 0.4 else
    "MEDIA" if charm_atm_ratio > 0.2 else
    "BAJA"
)
```

#### Charm Signal y narrativa

```python
# Signal basada en el signo de charm_total
if charm_total > +50_000:
    charm_signal = "EXPANSIVO"
    charm_narrative = (
        f"Dealers comprando ~{charm_total/1000:.0f}K delta/hora "
        "por decay — soporte mecánico intraday"
    )
elif charm_total < -50_000:
    charm_signal = "SUPRESIVO"
    charm_narrative = (
        f"Dealers vendiendo ~{abs(charm_total)/1000:.0f}K delta/hora "
        "por decay — presión bajista mecánica"
    )
else:
    charm_signal = "NEUTRO"
    charm_narrative = "Charm balanceado — sin sesgo direccional por tiempo"
```

Constante configurable: `CHARM_SIGNAL_THRESHOLD = 50_000` (deltas/hora).

### 3.2 Delta Exposure (DEX)

#### Qué mide

El DEX agrega el delta neto por strike, mostrando dónde los dealers están
largos o cortos en delta. A diferencia del GEX (que mide la *velocidad* del
reajuste), el DEX mide la *posición* actual.

Un DEX muy negativo en un strike significa que los dealers tienen delta corto
ahí y necesitarán comprar si el precio sube → soporte. Un DEX muy positivo
significa que venderán si el precio baja → resistencia.

#### Fórmula

```
dex_strike = Σ delta × OI × 100 × sign(option_type)
             (sign: calls = +1, puts = -1)

dex_cumulative[strike] = Σ dex[s] para s <= strike
                         (acumulado de strikes bajos a altos)

dex_total = Σ dex_strike  (todos los strikes)
```

El `dex_cumulative` muestra el "muro" de delta acumulado — dónde cambia de signo
es el nivel donde los dealers pasan de largos a cortos en delta.

#### Implementación

Nueva función en `calculate_indicators.py`:

```python
def calc_delta_exposure(chain_0dte: dict, spot: float, fecha: str) -> dict:
    """
    Returns:
        {
            "dex_by_strike":         dict[str, float],  # DEX por strike (billions equiv.)
            "dex_cumulative":        dict[str, float],  # DEX acumulado
            "dex_total":             float | None,
            "dex_flip":              float | None,      # strike donde DEX cum cruza cero
            "dex_positive_wall":     float | None,      # strike con DEX más positivo
            "dex_negative_wall":     float | None,      # strike con DEX más negativo
            "dex_signal":            str,               # "DEALERS_LARGO_DELTA" | "DEALERS_CORTO_DELTA"
            "dex_narrative":         str,
            "status":                str,
            "fecha":                 str,
        }
    """
```

Escalar igual que GEX: `dex_value = delta × OI × 100 × spot / 1_000_000_000 × sign`
(mantener unidades de billions para comparabilidad visual con GEX).

### 3.3 GEX Change (intraday)

#### Qué mide

El GEX Change es la diferencia de GEX por strike entre el snapshot actual
y un snapshot de referencia (por defecto: el snapshot de apertura del día o
el snapshot anterior). Muestra qué strikes están ganando/perdiendo relevancia
durante la sesión.

Es lo que @42traders llama "Current Strike Dealer GEX Change" en su panel izquierdo.

#### Implementación

Nueva función en `gex_intraday.py`:

```python
def calc_gex_change(ref_snapshot: dict, curr_snapshot: dict) -> dict:
    """
    Calcula el cambio de GEX por strike entre dos snapshots.

    Args:
        ref_snapshot:  snapshot de referencia (apertura del día u anterior)
        curr_snapshot: snapshot actual

    Returns:
        {
            "gex_change_by_strike": dict[str, float],  # gex_curr - gex_ref por strike
            "strikes_gaining":      list[float],        # strikes con GEX más positivo
            "strikes_losing":       list[float],        # strikes con GEX más negativo
            "net_change":           float,              # cambio neto total
            "ref_ts":               str,
            "curr_ts":              str,
        }
    """
```

```python
# Lógica principal
ref_gex  = ref_snapshot.get("gex_by_strike", {})
curr_gex = curr_snapshot.get("gex_by_strike", {})

all_strikes = set(ref_gex.keys()) | set(curr_gex.keys())
gex_change  = {
    s: curr_gex.get(s, 0.0) - ref_gex.get(s, 0.0)
    for s in all_strikes
}

# Top movers
sorted_changes = sorted(gex_change.items(), key=lambda x: x[1])
strikes_losing  = [float(s) for s, v in sorted_changes[:5] if v < 0]
strikes_gaining = [float(s) for s, v in sorted_changes[-5:] if v > 0]
```

**Integración en monitor**: en `_poll_gex()`, calcular el GEX Change respecto al
primer snapshot del día (apertura). Incluir en el snapshot guardado:

```python
# En take_gex_snapshot(), añadir gex_change si hay snapshot de apertura:
if opening_snapshot:
    snapshot["gex_change"] = calc_gex_change(opening_snapshot, snapshot)
```

### 3.4 Pinning Zone (actualización)

El concepto de "Dealer/Pinning Zone" de @42traders combina tres señales:
GEX máximo + Charm máximo ATM + spot próximo al nivel.

**Fórmula**:

```python
def calc_pinning_zone(gex_result: dict, charm_result: dict, spot: float) -> dict:
    """
    Identifica el strike con mayor probabilidad de actuar como imán del precio.

    Un strike es candidato a Pinning Zone si:
    1. Es Put Wall o Call Wall (alto GEX)
    2. Y/O es Charm Pin Zone (alto charm ATM)
    3. El spot está dentro de ±100 pts

    Returns:
        {
            "pinning_zone":      float | None,
            "pinning_conf":      str,     # "ALTA" | "MEDIA" | "BAJA" | "NINGUNA"
            "pinning_narrative": str,
        }
    """
```

```python
candidates = []
# Candidato 1: put_wall o call_wall más cercano al spot
for wall in [gex_result["call_wall"], gex_result["put_wall"]]:
    if wall and abs(wall - spot) <= 100:
        score = abs(gex_result["net_gex_by_dte"]["0dte"] or 0) * 0.6
        candidates.append({"strike": wall, "score": score, "source": "GEX_WALL"})

# Candidato 2: charm_pin_zone si está ATM
cp = charm_result.get("charm_pin_zone")
if cp and abs(cp - spot) <= 50:
    charm_score = abs(charm_result.get("charm_total") or 0) / 100_000
    candidates.append({"strike": cp, "score": charm_score, "source": "CHARM"})

# Combinar: si GEX_WALL y CHARM coinciden en el mismo strike → confianza ALTA
# Si solo uno → confianza MEDIA si score alto, BAJA si score bajo
```

---

## Fase 4 — Visualizaciones avanzadas

### 4.1 Multi-panel premarket (3 columnas)

**Archivo nuevo**: `scripts/gex_dashboard.py`

**Función**: `build_premarket_dashboard(indicators: dict) -> bytes`

Genera una imagen PNG de ~1400×800px con tres paneles:

#### Panel izquierdo — GEX por strike 0DTE (barras horizontales)

```
  Eje Y: strikes (25 más cercanos al spot, de mayor a menor)
  Eje X: GEX en billions (escala simétrica)
  Calls: barras en teal (#00B4D8)
  Puts:  barras en coral/rojo (#FF6B6B)
  Líneas de referencia:
    - spot (línea blanca, etiqueta "SPX")
    - flip_level (línea naranja, etiqueta "Flip")
    - call_wall (línea verde, "CW")
    - put_wall (línea roja, "PW")
    - pinning_zone (línea amarilla, "PIN")
    - chop_zone_low / chop_zone_high (banda semitransparente gris)
  Título: "GEX 0DTE — {fecha}"
```

#### Panel central — Net GEX por DTE bucket (área temporal)

Si hay snapshots intraday (durante sesión):

```
  Eje X: tiempo ET (09:30 – 16:00)
  Eje Y: Net GEX en billions
  Tres líneas solapadas:
    - 0DTE:  línea teal fina
    - 7DTE:  línea naranja media
    - 30DTE: línea blanca gruesa (GEX total)
  Banda de relleno entre 0 y la línea 30DTE (teal semitransparente si >0, rojo si <0)
  Línea horizontal en y=0 (flip de régimen)
  Título: "Net GEX por bucket — intraday"
```

Si es premarket (un solo punto de datos):

```
  Gráfico de barras agrupadas:
    Tres barras por cluster: 0DTE, 7DTE, 30DTE
    Colores: teal / naranja / blanco
  Título: "Net GEX por DTE — premarket"
```

#### Panel derecho — DEX acumulado

```
  Eje Y: strikes (mismo rango que panel izquierdo)
  Eje X: DEX acumulado en billions
  Área rellena: cyan cuando DEX >0 (dealers largos delta), magenta cuando <0
  Línea vertical en x=0
  Línea horizontal en dex_flip (donde los dealers pasan de largos a cortos)
  Título: "Delta Exposure (DEX) acumulado"
```

### 4.2 Heatmap Charm Exposure (temporal)

**Archivo**: añadir a `scripts/gex_heatmap.py`

**Función**: `build_charm_heatmap(snapshots: list[dict]) -> bytes`

```
  Eje X: tiempo ET (cada snapshot = columna)
  Eje Y: strikes (rango ±100 pts del spot medio del día)
  Color: intensidad del charm_exposure por strike
    positivo (dealers compran) → teal/cyan
    negativo (dealers venden) → magenta/rojo
    neutro → negro
  Escala de color: divergente, centrada en 0
  Overlay:
    - línea spot (blanca)
    - pinning_zone (amarilla punteada)
    - charm_pin_zone de cada snapshot (círculos blancos)
  Título: "SPX — Dealer Charm Exposure Heatmap"
```

### 4.3 GEX Change bars

**Archivo**: añadir a `scripts/gex_heatmap.py`

**Función**: `build_gex_change_chart(gex_change: dict, spot: float) -> bytes`

```
  Eje Y: strikes (25 más cercanos al spot)
  Eje X: cambio de GEX vs apertura (en billions)
  Barras cyan: GEX ganado (strikes que se fortalecen)
  Barras magenta: GEX perdido (strikes que se debilitan)
  Línea spot (blanca)
  Título: "SPX — Dealer GEX Change vs apertura"
```

### 4.4 Función de envío Telegram enriquecida

**Archivo**: `scripts/notify_telegram.py`

Nueva función `send_dealer_flow_report(indicators: dict) -> None`:

```python
def send_dealer_flow_report(indicators: dict) -> None:
    """
    Envía el reporte completo de Dealer Flow:
    1. Imagen multi-panel premarket (PNG)
    2. Texto del reporte premarket
    3. Heatmap charm (si hay snapshots intraday)
    """
    # Construir imagen
    img_bytes = build_premarket_dashboard(indicators)
    caption   = _build_dealer_flow_text(indicators)
    send_telegram_photo(img_bytes, caption)
```

---

## Fase 5 — Narrativa automática

### 5.1 Price Paths

Generar automáticamente los posibles caminos de precio basándose en la estructura GEX.

**Archivo**: nueva función en `calculate_indicators.py` o módulo propio `gex_narrative.py`.

```python
def calc_price_paths(gex: dict, charm: dict, dex: dict, spot: float) -> dict:
    """
    Genera los price paths alcista y bajista basándose en los niveles GEX.

    Lógica:
    - Path alcista: spot → siguiente resistencia entre spot y call_wall
                   → call_wall → siguiente nivel post-call_wall (si hay)
    - Path bajista: spot → flip_level (si spot > flip)
                   → put_wall → siguiente nivel post-put_wall (si hay)

    Niveles candidatos (ordenados por relevancia):
      call_wall, dex_positive_wall, max_pain (si > spot), +50/+100 pts redondos
      put_wall,  dex_negative_wall, flip_level, chop_zone_low, -50/-100 pts redondos

    Returns:
        {
            "path_alcista":  list[float],   # [spot, nivel1, nivel2, nivel3]
            "path_bajista":  list[float],   # [spot, nivel1, nivel2, nivel3]
            "key_decision":  float | None,  # nivel pivote — si se pierde cambia el sesgo
            "key_decision_desc": str,
        }
    """
```

Criterios para path alcista:
1. Si spot > flip_level y charm_signal == "EXPANSIVO" → seguir hacia call_wall
2. Si spot < flip_level → primer path es recuperar flip, luego ATH_zone

Criterios para path bajista:
1. Si charm_signal == "SUPRESIVO" → añadir presión adicional a los niveles bajistas
2. Si dex_flip < spot → dealers cortos delta por encima → resistencia adicional

### 5.2 Texto del reporte premarket

Función `_build_dealer_flow_text(indicators: dict) -> str`:

```
SPX Dealer Flow — Premarket {fecha}
═══════════════════════════════════════

RÉGIMEN: {signal_gex}  Net GEX: {net_gex_bn:+.1f}B
  0DTE: {net_gex_0dte:+.1f}B | ≤7DTE: {net_gex_7dte:+.1f}B | ≤30DTE: {net_gex_30dte:+.1f}B
Charm: {charm_signal}  ({charm_total:+.0f}K delta/hora)

NIVELES CLAVE
  Flip Level:   {flip_level}  [{score_flip_text}]
  Call Wall:    {call_wall}   [dist: {dist_call:+.0f} pts{near_cw_warn}]
  Put Wall:     {put_wall}    [dist: {dist_put:+.0f} pts]
  Pinning Zone: {pinning_zone} [{pinning_conf}]
  Chop Zone:    {chop_low} – {chop_high}
  Max Pain:     {max_pain}

{regime_text}
{charm_narrative}
{dex_narrative}

PRICE PATHS
  ↑ {path_alcista_str}
  ↓ {path_bajista_str}

Pivote clave: {key_decision} — {key_decision_desc}
```

### 5.3 Actualización del scorecard de terminal

`generate_scorecard.py` — ampliar la sección GEX con los nuevos campos:

```
Net GEX (IND-03)     GEX=+26.6B  (0d:+8.2  7d:+19.1)    +3   LONG_GAMMA_FUERTE
Flip Level (IND-04)  Flip=7360   Spot=7418                +2   SOBRE_FLIP
Wall Proximity       CW=7500 PW=7375  dist=+82/−43        −2   CERCA_CALL_WALL

─── Dealer Flow ────────────────────────────────────────────────────────────
Charm Exposure       +340K δ/h   Expansivo                     SOPORTE_MECANICO
Delta Exposure       DEX=−12.3B  Dealers corto delta            RESISTENCIA_DELTA
Pinning Zone         7460        confianza ALTA                 CHARM+GEX

─── Price Paths ────────────────────────────────────────────────────────────
↑  7418 → 7460 → 7478 → 7500
↓  7418 → 7385 → 7360 → 7340
```

---

## Integración con el monitor Mancini

Los nuevos cálculos se integran en el ciclo de snapshots GEX existente (`_poll_gex`):

1. `take_gex_snapshot()` llama además `calc_charm_exposure()` y `calc_delta_exposure()`.
2. El snapshot JSONL incluye los campos `charm_by_strike`, `dex_by_strike`, `gex_change`.
3. Alertas nuevas vía `notifier.py`:
   - `notify_charm_shift()`: cuando `charm_signal` cambia de EXPANSIVO a SUPRESIVO o viceversa.
   - `notify_pinning_change()`: cuando la `pinning_zone` se desplaza > 25 pts entre snapshots.

**Formato de alerta charm shift**:

```
⚡ Charm Shift detectado
De: EXPANSIVO → A: SUPRESIVO
Dealers ahora venden ~95K δ/hora por decay
Pin zone: 7460  Spot: 7445 | 13:30 ET
```

---

## Estructura de archivos resultante

```
scripts/
├── tastytrade_client.py          ← Fase 1: añadir delta al contrato
├── fetch_market_data.py          ← Fase 2: max_dte, tres cadenas, campo dte
├── calculate_indicators.py       ← Fase 1+3: charm sintético, calc_charm_exposure,
│                                              calc_delta_exposure, calc_pinning_zone
├── gex_intraday.py               ← Fase 2+3: max_dte=0, calc_gex_change, GEX Change
├── gex_heatmap.py                ← Fase 4: build_charm_heatmap, build_gex_change_chart
├── gex_dashboard.py              ← Fase 4 (nuevo): build_premarket_dashboard
├── gex_narrative.py              ← Fase 5 (nuevo): calc_price_paths, _build_dealer_flow_text
├── generate_scorecard.py         ← Fase 5: scorecard enriquecido
├── notify_telegram.py            ← Fase 4+5: send_dealer_flow_report, nuevas alertas
└── mancini/
    └── monitor.py                ← Fase 3+5: charm/DEX en snapshots, nuevas alertas

outputs/
├── data.json                     ← option_chain_0/7/30dte con campo "delta"
├── indicators.json               ← net_gex enriquecido + charm_exposure + delta_exposure
└── gex_snapshots_YYYY-MM-DD.jsonl ← snapshots con gex_change, charm_by_strike, dex_by_strike

specs/
└── gex_advanced_analytics.md    ← este documento
```

---

## Output schemas finales

### data.json — campo option_chain_Xdte

```json
{
  "option_chain_0dte": {
    "contracts": [
      {
        "strike":        7500,
        "option_type":   "C",
        "expiry":        "2026-05-22",
        "dte":           0,
        "open_interest": 5234,
        "gamma":         0.00015,
        "delta":         0.52,
        "iv":            0.28
      }
    ],
    "n_contracts": 60,
    "expiries":    ["2026-05-22"],
    "status":      "OK"
  },
  "option_chain_7dte":  { "...": "idem" },
  "option_chain_30dte": { "...": "idem" }
}
```

### indicators.json — sección net_gex (enriquecida)

```json
{
  "net_gex": {
    "net_gex_bn":    26.6,
    "net_gex_by_dte": {
      "0dte":  8.2,
      "7dte":  19.1,
      "30dte": 26.6
    },
    "score_gex":     3,
    "signal_gex":    "LONG_GAMMA_FUERTE",
    "flip_level":    7360.0,
    "score_flip":    2,
    "signal_flip":   "SOBRE_FLIP",
    "put_wall":      7375.0,
    "call_wall":     7500.0,
    "max_pain":      7560.0,
    "control_node":  null,
    "chop_zone_low": 7355.0,
    "chop_zone_high":7360.0,
    "expected_range_pts": 125.0,
    "score_wall_proximity": -2,
    "signal_wall_proximity": "CERCA_CALL_WALL",
    "gex_by_strike": {},
    "gex_pct_by_strike": {},
    "regime_text":   "Dealers LONG gamma (fuerte) — sesión contenida, rebotes comprados",
    "spot":          7418.0,
    "n_strikes":     60,
    "n_expiries":    4,
    "status":        "OK",
    "fecha":         "2026-05-22"
  },
  "charm_exposure": {
    "charm_by_strike":     {},
    "charm_total":         340000,
    "charm_signal":        "EXPANSIVO",
    "charm_narrative":     "Dealers comprando ~340K delta/hora por decay — soporte mecánico intraday",
    "charm_pin_zone":      7460.0,
    "charm_pin_zone_conf": "ALTA",
    "charm_intraday": [
      {"hora": "09:30", "charm_delta": 120000, "signal": "EXPANSIVO"},
      {"hora": "10:00", "charm_delta": 150000, "signal": "EXPANSIVO"},
      {"hora": "15:30", "charm_delta": -80000, "signal": "SUPRESIVO"}
    ],
    "status": "OK",
    "fecha":  "2026-05-22"
  },
  "delta_exposure": {
    "dex_by_strike":     {},
    "dex_cumulative":    {},
    "dex_total":         -12300000000,
    "dex_flip":          7390.0,
    "dex_positive_wall": 7500.0,
    "dex_negative_wall": 7350.0,
    "dex_signal":        "DEALERS_CORTO_DELTA",
    "dex_narrative":     "Dealers netos cortos delta — resistencia adicional sobre 7390",
    "status":            "OK",
    "fecha":             "2026-05-22"
  },
  "pinning_zone": {
    "pinning_zone":      7460.0,
    "pinning_conf":      "ALTA",
    "pinning_narrative": "7460 — confluencia GEX Wall + Charm máximo ATM. Imán de precio probable.",
    "path_alcista":      [7418, 7460, 7478, 7500],
    "path_bajista":      [7418, 7385, 7360, 7340],
    "key_decision":      7418,
    "key_decision_desc": "Mantener 7418 es clave — pérdida activa path bajista"
  }
}
```

---

## Casos de error por fase

| Fase | Situación | Comportamiento |
|------|-----------|----------------|
| Fase 1 | `delta` None en DXLink | Contrato excluido de DEX; GEX no afectado |
| Fase 1 | `iv` None (charm no calculable) | charm=None para ese contrato; charm_total suma los disponibles |
| Fase 2 | No hay contratos con DTE≤7 | `chain_7dte.status = "EMPTY_CHAIN"`, net_gex_by_dte["7dte"] = None |
| Fase 3 | `charm_total = None` | charm_signal = "NEUTRO", narrativa por defecto |
| Fase 3 | `dex_total = None` | dex_signal = None, narativa vacía |
| Todas | Cualquier excepción no controlada | status = "ERROR", scores = 0, pipeline continúa |

---

## Tests por fase

### Fase 1
- `test_delta_extracted_from_greeks()` — delta propagado al contrato
- `test_delta_negative_for_puts()` — puts tienen delta negativo, no se filtra
- `test_charm_calc_valid_iv()` — charm sintético con inputs conocidos
- `test_charm_calc_zero_dte_uses_halfday()` — T = 0 → usa 0.5/365

### Fase 2
- `test_fetch_chain_max_dte_filters_expiries()` — max_dte=0 solo devuelve hoy
- `test_fetch_chain_7dte_includes_weekly()` — max_dte=7 incluye semanales
- `test_contract_has_dte_field()` — cada contrato tiene campo "dte"
- `test_net_gex_by_dte_fields_present()` — output incluye net_gex_by_dte

### Fase 3
- `test_charm_exposure_positive_calls_atm()` — calls ATM expirando → charm positivo
- `test_charm_total_sign()` — suma total coherente con señal
- `test_charm_pin_zone_within_atm_range()` — pin zone dentro de ±50 pts del spot
- `test_charm_intraday_decreasing_T()` — charm cambia con T decreciente
- `test_dex_flip_zero_crossing()` — dex_flip donde DEX cum cruza cero
- `test_dex_negative_puts_dominant()` — cadena put-heavy → DEX negativo
- `test_gex_change_zero_when_identical()` — snapshots iguales → cambio nulo
- `test_gex_change_detects_new_strikes()` — strike nuevo → cambio positivo
- `test_pinning_zone_confluence_alta()` — coincidencia GEX+charm → ALTA
- `test_pinning_zone_solo_charm_media()` — solo charm → MEDIA

### Fase 4
- `test_dashboard_returns_png()` — build_premarket_dashboard → bytes PNG
- `test_charm_heatmap_returns_png()` — build_charm_heatmap con 3 snapshots → PNG
- `test_gex_change_chart_returns_png()` — build_gex_change_chart → PNG
- `test_dashboard_no_crash_empty_charm()` — funciona si charm_exposure no disponible

### Fase 5
- `test_price_paths_alcista_above_spot()` — todos los niveles > spot
- `test_price_paths_bajista_below_spot()` — todos los niveles < spot
- `test_scorecard_includes_charm_row()` — charm aparece en scorecard
- `test_dealer_flow_text_contains_key_levels()` — texto incluye flip, walls, paths

---

## Verificación por fase

### Fase 1
1. Ejecutar `uv run python scripts/run.py`
2. Verificar que `data.json` tiene `"delta": <float>` en al menos el 80% de contratos
3. Verificar que puts tienen delta negativo y calls delta positivo

### Fase 2
1. `data.json` debe tener `option_chain_0dte`, `option_chain_7dte`, `option_chain_30dte`
2. `option_chain_0dte.n_contracts` ≤ `option_chain_7dte.n_contracts`
3. `indicators.json` tiene `net_gex.net_gex_by_dte` con tres valores no nulos
4. `option_chain_multi` ya no existe en `data.json`

### Fase 3
1. `indicators.json` tiene secciones `charm_exposure`, `delta_exposure`, `pinning_zone`
2. `charm_signal` es uno de EXPANSIVO / SUPRESIVO / NEUTRO
3. `charm_intraday` tiene al menos 13 entradas (09:30 a 15:30 cada 30 min)
4. `dex_flip` tiene sentido: está entre put_wall y call_wall

### Fase 4
1. Ejecutar `uv run python scripts/gex_dashboard.py` → genera PNG en `outputs/dashboard_YYYY-MM-DD.png`
2. Abrir la imagen: tres paneles visibles, etiquetas legibles, spot marcado
3. Ejecutar con snapshots intraday → panel central muestra serie temporal

### Fase 5
1. Ejecutar `uv run python scripts/run.py` → scorecard terminal muestra sección Dealer Flow
2. Verificar que Price Paths tienen 3-4 niveles y son coherentes con los niveles GEX
3. Ejecutar `send_dealer_flow_report()` manualmente → llega imagen + texto a Telegram
