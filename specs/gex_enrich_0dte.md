# Spec: Enriquecimiento del cálculo GEX 0DTE

## Estado

- [x] Implementado

## Objetivo

Ampliar `calc_net_gex()` con cuatro conceptos nuevos derivados de la cadena 0DTE:
**Control Node**, **Chop Zone**, **GEX relativo por strike** y **Regime Text**.
No cambia la arquitectura del pipeline — solo enriquece el output del indicador existente.

---

## Conceptos

### Control Node

El strike con el mayor GEX negativo absoluto en la cadena 0DTE.
Conceptualmente distinto del `put_wall` (que es el strike de mínimo GEX):
el Control Node es el nivel donde los dealers concentran el mayor volumen
de delta-hedging vendedor. Cuando el mercado está en short gamma,
este nivel actúa como "centro de gravedad": los rebotes tienden a agotarse
aquí y las caídas aceleran al perderlo.

Solo existe en régimen short gamma (`net_gex_bn < 0`). Si el mercado está
en long gamma, `control_node = None` (no hay un nodo dominante de presión vendedora).

```
control_node = strike con gex_0dte[strike] más negativo
               solo si net_gex_bn < 0, si no → None
```

Nota: en short gamma, el Control Node y el `put_wall` coinciden matemáticamente
(ambos son el mínimo de `gex_0dte`). Se mantienen como campos separados porque
tienen semánticas distintas en el uso operativo (put_wall = soporte gravitacional
en long gamma; control_node = nivel de aceleración en short gamma).

### Chop Zone

Rango de precios alrededor del flip_level donde el GEX acumulado oscila
cerca de cero — zona de posicionamiento dealer two-sided. Dentro de este
rango el mercado tiene tendencia a whipsaw sin edge claro.

Definición:
```
strikes_sorted = sorted(gex_0dte.keys())
gex_cum[i]     = sum(gex_0dte[s] for s in strikes_sorted[:i+1])

chop_zone_low  = strike inmediatamente inferior al flip_level
                 (mayor strike con gex_cum < 0 antes del flip)
chop_zone_high = strike inmediatamente superior al flip_level
                 (menor strike con gex_cum > 0 después del flip)
```

Si `flip_level = None` → `chop_zone_low = chop_zone_high = None`.

### GEX relativo por strike (gex_pct_by_strike)

GEX de cada strike normalizado respecto al máximo absoluto de la cadena 0DTE.
Permite comparar la importancia relativa de cada strike independientemente
del nivel absoluto de OI del día.

```
max_abs = max(abs(v) for v in gex_0dte.values())
gex_pct_by_strike[strike] = round(gex_0dte[strike] / max_abs * 100, 1)
```

El strike con `gex_pct = -100%` o `+100%` es el más impactante estructuralmente.
Si `max_abs == 0` (cadena sin gamma válida) → dict vacío.

### Regime Text

Descripción operativa en lenguaje natural del posicionamiento dealer,
derivada de `signal_gex` y `flip_level`. Útil para el mensaje Telegram
y para contexto en el sistema Mancini.

| signal_gex           | Texto                                                                    |
|----------------------|--------------------------------------------------------------------------|
| LONG_GAMMA_FUERTE    | `"Dealers LONG gamma (fuerte) — sesión contenida, rebotes comprados"`    |
| LONG_GAMMA_SUAVE     | `"Dealers LONG gamma — tendencia a mean-reversion, movimientos limitados"` |
| SHORT_GAMMA_SUAVE    | `"Dealers SHORT gamma bajo {flip} — rebotes débiles, sin cobertura"` |
| SHORT_GAMMA_FUERTE   | `"Dealers SHORT gamma (fuerte) bajo {flip} — caídas se aceleran"` |
| None / error         | `"Régimen GEX no disponible"` |

Cuando `flip_level` es None, omitir "bajo {flip}" del texto.

---

## Archivos a modificar

| Archivo | Cambio |
|---------|--------|
| `scripts/calculate_indicators.py` | Ampliar `calc_net_gex()` — añadir 6 campos nuevos al output |
| `tests/test_ind_net_gex.py` | Tests para los 4 conceptos nuevos |

---

## 1. calculate_indicators.py — cambios en `calc_net_gex()`

### 1a. Nuevos campos en el dict `base`

```python
base = {
    # ... campos existentes sin cambio ...
    "control_node":      None,   # float | None
    "chop_zone_low":     None,   # float | None
    "chop_zone_high":    None,   # float | None
    "gex_pct_by_strike": {},     # dict[str, float]  — clave es str(strike)
    "regime_text":       "Régimen GEX no disponible",  # str
}
```

### 1b. Cálculo del Control Node (añadir tras calcular `gex_0dte`)

```python
# Control Node (solo en short gamma)
if gex_0dte and net_gex_bn < 0:
    base["control_node"] = min(gex_0dte, key=gex_0dte.get)
```

### 1c. Cálculo de la Chop Zone (añadir tras calcular `flip_level`)

```python
if flip_level is not None and len(strikes_sorted) >= 2:
    # chop_zone_low: mayor strike con gex_cum < 0 antes del flip
    # chop_zone_high: menor strike con gex_cum >= 0 en o tras el flip
    chop_low  = None
    chop_high = None
    cumsum = 0.0
    for s in strikes_sorted:
        cumsum += gex_0dte[s]
        if cumsum < 0:
            chop_low = s
        elif chop_high is None:
            chop_high = s
            break
    base["chop_zone_low"]  = chop_low
    base["chop_zone_high"] = chop_high
```

### 1d. Cálculo de gex_pct_by_strike (añadir tras calcular `gex_0dte`)

```python
if gex_0dte:
    max_abs = max(abs(v) for v in gex_0dte.values())
    if max_abs > 0:
        base["gex_pct_by_strike"] = {
            str(int(k)): round(v / max_abs * 100, 1)
            for k, v in gex_0dte.items()
        }
```

### 1e. Cálculo de regime_text (añadir tras calcular `signal_gex`)

```python
flip_str = f" bajo {flip_level:.0f}" if flip_level is not None else ""
_regime_map = {
    "LONG_GAMMA_FUERTE":  "Dealers LONG gamma (fuerte) — sesión contenida, rebotes comprados",
    "LONG_GAMMA_SUAVE":   "Dealers LONG gamma — tendencia a mean-reversion, movimientos limitados",
    "SHORT_GAMMA_SUAVE":  f"Dealers SHORT gamma{flip_str} — rebotes débiles, sin cobertura",
    "SHORT_GAMMA_FUERTE": f"Dealers SHORT gamma (fuerte){flip_str} — caídas se aceleran",
}
base["regime_text"] = _regime_map.get(base["signal_gex"], "Régimen GEX no disponible")
```

### 1f. Output completo del indicador enriquecido

```python
{
    # campos existentes
    "net_gex_bn":    float,
    "score_gex":     int,
    "signal_gex":    str,
    "flip_level":    float | None,
    "score_flip":    int,
    "signal_flip":   str,
    "put_wall":      float | None,
    "call_wall":     float | None,
    "max_pain":      float | None,
    "spot":          float,
    "n_strikes":     int,
    "n_expiries":    int,
    "status":        str,
    "fecha":         str,
    # campos nuevos
    "control_node":       float | None,   # strike con mayor GEX negativo (short gamma)
    "chop_zone_low":      float | None,   # límite inferior zona chop
    "chop_zone_high":     float | None,   # límite superior zona chop
    "gex_pct_by_strike":  dict,           # {"5200": -87.3, "5250": 42.1, ...}
    "regime_text":        str,            # descripción operativa dealer
}
```

---

## 2. Impacto en generate_scorecard.py y notify_telegram.py

### generate_scorecard.py

Añadir dos líneas informativas bajo las filas existentes de Net GEX y Flip Level:

```python
# Control Node (solo si existe)
control_node = net_gex.get("control_node")
if control_node is not None:
    print(f"  {'  Control Node':<20} {'CN='+str(int(control_node)):<26}")

# Chop Zone (solo si existe)
chop_low  = net_gex.get("chop_zone_low")
chop_high = net_gex.get("chop_zone_high")
if chop_low is not None and chop_high is not None:
    print(f"  {'  Chop Zone':<20} {str(int(chop_low))+' – '+str(int(chop_high)):<26}")

# Regime text
print(f"\n  {net_gex.get('regime_text','')}")
```

### notify_telegram.py

Añadir al bloque de niveles GEX en el mensaje:

```
🔴 Control Node: {control_node}
🔀 Chop Zone:   {chop_zone_low} – {chop_zone_high}
📋 {regime_text}
```

---

## 3. Tests a añadir en `tests/test_ind_net_gex.py`

### Control Node

```python
def test_control_node_short_gamma():
    # cadena donde el strike 5150 tiene el GEX más negativo
    # → control_node = 5150, net_gex < 0
    ...

def test_control_node_none_when_long_gamma():
    # net_gex > 0 → control_node = None
    ...
```

### Chop Zone

```python
def test_chop_zone_calculated_around_flip():
    # flip_level=5200 → chop_zone_low < 5200 < chop_zone_high
    ...

def test_chop_zone_none_when_no_flip():
    # GEX siempre positivo → flip_level=None → chop_zone_low=None, chop_zone_high=None
    ...
```

### GEX relativo

```python
def test_gex_pct_max_is_100():
    # el strike con mayor abs(GEX) debe tener abs(pct) == 100.0
    ...

def test_gex_pct_empty_when_no_gamma():
    # cadena sin contratos con gamma → gex_pct_by_strike == {}
    ...
```

### Regime Text

```python
def test_regime_text_short_gamma_fuerte_includes_flip():
    # signal_gex = SHORT_GAMMA_FUERTE, flip_level = 5200
    # → "bajo 5200" en el texto
    ...

def test_regime_text_no_flip():
    # flip_level = None → texto sin "bajo X"
    ...
```

---

## Verificación

1. Ejecutar `uv run python scripts/calculate_indicators.py` — `indicators.json` debe tener
   `net_gex` con 19 campos (13 anteriores + 6 nuevos).
2. Verificar `control_node`:
   - Si `signal_gex` es SHORT_GAMMA_*: `control_node` debe ser un float igual al `put_wall`.
   - Si `signal_gex` es LONG_GAMMA_*: `control_node` debe ser `null`.
3. Verificar `chop_zone_low < flip_level < chop_zone_high` cuando flip_level no es None.
4. Verificar que `max(abs(v) for v in gex_pct_by_strike.values()) == 100.0`.
5. Verificar que `regime_text` contiene el número del flip_level cuando la señal es SHORT_GAMMA_*.
6. Ejecutar `uv run pytest tests/test_ind_net_gex.py` — todos los tests en verde.
