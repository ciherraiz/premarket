# Spec: Workflow Open Phase

## Estado
[Development]

## Propósito

Extender el pipeline premarket con una segunda fase de ejecución que corre
N minutos después de la apertura del mercado. La Open Phase calcula indicadores
sobre los primeros N minutos de sesión real y produce un scorecard combinado
que es la base de la decisión de trading del día.

La decisión de trading **no se toma antes de ejecutar la Open Phase**.

---

## Modelo de dos fases

```
FASE PREMARKET                          FASE OPEN
─────────────────────────               ─────────────────────────
Antes de 09:25 ET                       10:15 ET (para ventana de 30 min)
                                        (= apertura + ventana + 15 min delay yfinance)

uv run python scripts/run.py            uv run python scripts/run.py \
  --phase premarket                       --phase open --window 30

  ↓                                         ↓
outputs/indicators.json                 outputs/indicators.json
  { "premarket": { ... } }               { "premarket": {...},
                                           "open": { ... } }

  ↓                                         ↓
Scorecard premarket en terminal         Scorecard combinado en terminal
(orientativo, no accionable)            (DECISIÓN DE TRADING)
```

### Timing con delay de yfinance

yfinance provee datos intraday de 1 minuto con ~15 minutos de retraso (free-tier).
Para obtener barras completas de la ventana, el script debe ejecutarse al final
del delay:

| Ventana (min) | Fin ventana | Ejecutar a las | Barras disponibles |
|---|---|---|---|
| 15 | 09:45 ET | 10:00 ET | 09:30–09:45 ✓ |
| 30 | 10:00 ET | 10:15 ET | 09:30–10:00 ✓ |
| 60 | 10:30 ET | 10:45 ET | 09:30–10:30 ✓ |

---

## Parámetros CLI

`run.py` acepta argumentos opcionales vía `argparse`:

| Parámetro | Valores | Default | Descripción |
|---|---|---|---|
| `--phase` | `premarket`, `open` | `premarket` | Fase a ejecutar |
| `--window` | entero positivo | `30` | Minutos de ventana open phase |

`--window` solo aplica cuando `--phase open`. Se ignora en premarket.

### Retrocompatibilidad

```bash
# Forma antigua (sin argumentos) — sigue funcionando
uv run python scripts/run.py

# Equivalente explícito
uv run python scripts/run.py --phase premarket
```

---

## Estructura de outputs/indicators.json

El archivo se escribe en dos pasadas: premarket primero, open phase después.

### Tras ejecutar --phase premarket

```json
{
  "fecha": "2026-03-31",
  "premarket": {
    "vix_vxv_slope":   { "score": 1, "signal": "CONTANGO_SUAVE", ... },
    "vix9d_vix_ratio": { "score": 2, "signal": "CONTANGO_FUERTE", ... },
    "overnight_gap":   { "score": 1, "signal": "GAP_ALCISTA", ... },
    "ivr":             { "score": 1, "signal": "PRIMA_NORMAL", ... },
    "atr_ratio":       { "score": 1, "signal": "CONTRACCION_SUAVE", ... },
    "net_gex":         { "score_gex": 1, "score_flip": 2, ... },
    "d_score": 7,
    "v_score": 2
  }
}
```

### Tras ejecutar --phase open (mismo archivo, añade sección)

```json
{
  "fecha": "2026-03-31",
  "premarket": { ... },
  "open": {
    "<ind_open_1>": { "score": ..., "signal": ..., "status": "OK", ... },
    "<ind_open_2>": { "score": ..., "signal": ..., "status": "OK", ... },
    "d_score": 3,
    "v_score": 1
  }
}
```

Los nombres de indicadores open-phase se definen en sus specs individuales
(`specs/ind_open_*.md`).

---

## Estructura de outputs/data.json

Mismo patrón de namespacing:

### Tras --phase premarket

```json
{
  "fecha": "2026-03-31",
  "status": "OK",
  "premarket": {
    "vix9d": 13.42,
    "vix": 16.05,
    "vxv": 18.30,
    "vvix": 88.12,
    "vix_history": { ... },
    "es_prev": { ... },
    "es": { ... },
    "spx_ohlcv": { ... },
    "spx_spot": 5195.50,
    "option_chain_0dte": { ... },
    "option_chain_multi": { ... }
  }
}
```

### Tras --phase open (añade sección)

```json
{
  "fecha": "2026-03-31",
  "premarket": { ... },
  "open": {
    "spx_intraday": {
      "ohlcv": [ { "Datetime": "2026-03-31 09:30:00-04:00", "Open": 5200.0, ... }, ... ],
      "bars": 30,
      "window_minutes": 30,
      "open_price": 5200.0,
      "fecha": "2026-03-31",
      "status": "OK"
    },
    "spx_spot": 5215.25,
    "option_chain_0dte": { ... }
  }
}
```

---

## Fuente de datos: open phase

| Dato | Fuente | Observaciones |
|---|---|---|
| Barras 1min SPX | yfinance `^GSPC`, `interval="1m"` | 15 min delay; ejecutar con offset |
| Precio spot actual | yfinance (última barra de spx_intraday) | — |
| Greeks/GEX actualizados | TastyTrade SDK `get_option_chain()` | Misma función que premarket |

### fetch_spx_intraday(window_minutes: int = 30) → dict

Nueva función en `fetch_market_data.py`:

```python
def fetch_spx_intraday(window_minutes: int = 30) -> dict:
    """
    Descarga barras de 1 minuto de ^GSPC para la sesión actual.
    Filtra desde las 09:30 ET y toma las primeras window_minutes barras.
    """
```

**Salida:**
```python
{
    "ohlcv": [
        {
            "Datetime": "2026-03-31 09:30:00-04:00",
            "Open":  5200.00,
            "High":  5205.50,
            "Low":   5198.25,
            "Close": 5203.75,
            "Volume": 123456
        },
        ...
    ],
    "bars": int,                # número de barras devueltas
    "window_minutes": int,      # parámetro recibido
    "open_price": float,        # Open de la primera barra (09:30 ET)
    "fecha": "2026-03-31",
    "status": "OK"              # OK | ERROR | INSUFFICIENT_DATA
}
```

**Status codes:**
- `OK` — se obtuvieron al menos `window_minutes` barras
- `INSUFFICIENT_DATA` — menos barras de lo esperado (mercado no abierto aún o delay)
- `ERROR` — excepción en la llamada a yfinance

**Implementación:**
```python
import yfinance as yf
import pytz
from datetime import datetime, time

ticker = yf.Ticker("^GSPC")
df = ticker.history(period="1d", interval="1m", prepost=False)

# Filtrar desde 09:30 ET
et = pytz.timezone("America/New_York")
df.index = df.index.tz_convert(et)
open_time = time(9, 30)
df = df[df.index.time >= open_time]

# Tomar primeras window_minutes barras
df = df.head(window_minutes)
```

---

## Flujo de run.py

```python
def run_premarket_phase(out: Path) -> dict:
    """Lógica actual de main(). Devuelve el dict de indicators."""
    # ... (cuerpo actual de main(), sin cambios internos)
    # Escribe indicators.json con namespace "premarket"

def run_open_phase(out: Path, window_minutes: int) -> dict:
    """Fetch intraday + calcular indicadores open. Devuelve indicators open."""
    # 1. fetch_spx_intraday(window_minutes)
    # 2. fetch_es_quote() para spot actualizado
    # 3. fetch_option_chain() con spot actualizado (GEX intraday)
    # 4. calcular indicadores open (calc_* de calculate_open_indicators.py)
    # 5. Leer indicators.json existente, añadir sección "open", reescribir

def main():
    args = parse_args()
    out = Path("outputs")
    out.mkdir(exist_ok=True)

    if args.phase == "premarket":
        indicators = run_premarket_phase(out)
        print_scorecard(indicators["premarket"])

    elif args.phase == "open":
        open_ind = run_open_phase(out, args.window)
        pre_ind = json.loads((out / "indicators.json").read_text())
        print_combined_scorecard(pre_ind["premarket"], open_ind)
```

---

## Módulo de indicadores open phase

Los indicadores open-phase residen en un módulo separado:

```
scripts/calculate_open_indicators.py
```

Sigue exactamente las mismas convenciones que `calculate_indicators.py`:
- Constantes configurables al inicio del fichero
- Funciones `calc_*` que aceptan dicts y devuelven dicts
- Dict de salida con `score`, `signal`, `status`, `fecha`
- Sin excepciones: status propagation pattern

Los indicadores concretos se definen en `specs/ind_open_*.md` antes de implementarse.

---

## Verificación

```bash
# Premarket (comportamiento actual sin cambios)
uv run python scripts/run.py
uv run python scripts/run.py --phase premarket

# Open phase (ejecutar a las 10:15 ET para ventana 30 min)
uv run python scripts/run.py --phase open --window 30

# Open phase con ventana de 15 minutos (ejecutar a las 10:00 ET)
uv run python scripts/run.py --phase open --window 15

# Tests (deben pasar tras todas las adaptaciones)
uv run pytest
```

El fichero `outputs/indicators.json` tras la segunda ejecución debe contener
tanto `"premarket"` como `"open"` con sus respectivos scores y señales.
