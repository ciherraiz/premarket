# Mancini — Niveles Técnicos Autónomos

## Problema

El sistema depende de que Mancini publique su plan en Twitter para tener niveles.
Si no hay tweet (tardanza, fin de semana, fallo de scraping), el monitor opera
sin referencia o activa el fallback stale del día anterior.

Los niveles de Mancini son en gran parte reproducibles algorítmicamente:
Prior Day/Week/Month H/L/C, pivot points clásicos, round numbers psicológicos,
y los niveles GEX (ya calculados). Con estos datos cubrimos ~70-80% de los
niveles que Mancini publica habitualmente.

---

## Objetivo

Calcular automáticamente un conjunto de niveles técnicos candidatos para /ES
que sirva como:

1. **Fallback de segundo nivel**: cuando no hay plan de Mancini ni plan stale
   válido, el monitor puede operar con estos niveles calculados.
2. **Validación cruzada**: cuando el plan de Mancini sí llega, comparar sus
   niveles con los calculados para medir la tasa de coincidencia (aprendizaje).
3. **Contexto adicional**: mostrar en el scorecard premarket los niveles clave
   aunque no haya plan de Mancini.

---

## Fuentes de datos

| Datos | Fuente | Estado |
|-------|--------|--------|
| OHLC diario SPX/ES | yfinance `^GSPC` 35 barras | Ya disponible en `data.json` |
| OHLC semanal SPX | yfinance `interval="1wk"` | **Nuevo fetch** |
| OHLC mensual SPX | yfinance `interval="1mo"` | **Nuevo fetch** |
| Quote /ES premarket | TastyTrade `get_future_quote` | Ya disponible |
| Flip Level / Put Wall / Call Wall | GEX calculado | Ya en `indicators.json` |

> **Nota sobre ES vs SPX**: yfinance no ofrece datos históricos fiables de
> `/ES` (futuros continuos). Usamos `^GSPC` (SPX cash) para todos los cálculos
> de niveles. La diferencia típica (basis) es <10 pts — irrelevante para S/R.

---

## Niveles a calcular

### Grupo A — Prior Session (diarios)
Extraídos de las últimas 2 barras diarias de SPX (`^GSPC`):

| Nivel | Cálculo |
|-------|---------|
| `PDH` | Prior Day High |
| `PDL` | Prior Day Low |
| `PDC` | Prior Day Close |
| `PP_D` | Pivot Point diario = (PDH + PDL + PDC) / 3 |
| `R1_D` | 2 × PP_D − PDL |
| `R2_D` | PP_D + (PDH − PDL) |
| `S1_D` | 2 × PP_D − PDH |
| `S2_D` | PP_D − (PDH − PDL) |

### Grupo B — Prior Week (semanales)
Extraídos de las últimas 2 barras semanales de SPX:

| Nivel | Cálculo |
|-------|---------|
| `PWH` | Prior Week High |
| `PWL` | Prior Week Low |
| `PWC` | Prior Week Close |
| `PP_W` | Pivot Point semanal = (PWH + PWL + PWC) / 3 |
| `R1_W` | 2 × PP_W − PWL |
| `S1_W` | 2 × PP_W − PWH |

### Grupo C — Prior Month (mensuales)
Extraídos de las últimas 2 barras mensuales de SPX:

| Nivel | Cálculo |
|-------|---------|
| `PMH` | Prior Month High |
| `PML` | Prior Month Low |
| `PMC` | Prior Month Close |

### Grupo D — Round Numbers
Múltiplos de 25 pts dentro de ±3% del precio actual de /ES.
Ejemplo: si ES = 5.350, rango 5.190–5.510 → [5.200, 5.225, ..., 5.500].

### Grupo E — GEX Levels (ya calculados)
Reutilizados directamente de `indicators.json`:
- `flip_level` — nivel gamma flip
- `put_wall` — strike con mayor gamma put
- `call_wall` — strike con mayor gamma call

---

## Modelo de datos

```python
# scripts/mancini/auto_levels.py

@dataclass
class TechnicalLevel:
    value: float
    label: str        # "PDH", "PWL", "PP_D", "R1_W", "RND_5350", "FLIP", etc.
    group: str        # "daily", "weekly", "monthly", "round", "gex"
    priority: int     # 1 (alta) a 3 (baja) — ver tabla abajo

@dataclass
class AutoLevels:
    fecha: str                     # YYYY-MM-DD
    spot: float                    # precio /ES al calcular
    levels: list[TechnicalLevel]   # todos los niveles, ordenados por value desc
    calculated_at: str             # ISO timestamp
```

**Prioridad por grupo:**

| Grupo | Priority | Justificación |
|-------|----------|---------------|
| `gex` | 1 | Mancini usa GEX implícitamente; alta coincidencia observada |
| `weekly` | 1 | Niveles semanales son los más citados por Mancini |
| `monthly` | 1 | PMH/PML son referencias de largo plazo frecuentes |
| `daily` | 2 | PDH/PDL son referencias cotidianas |
| `round` | 3 | Usados como confirmación, raramente como nivel primario |

Persistencia: `outputs/mancini_auto_levels.json` (sobrescrito en cada cálculo).

---

## Módulo `auto_levels.py`

```python
# scripts/mancini/auto_levels.py

def fetch_weekly_ohlc(symbol: str = "^GSPC", bars: int = 4) -> pd.DataFrame:
    """Descarga barras semanales via yfinance. Retorna DataFrame con OHLC."""

def fetch_monthly_ohlc(symbol: str = "^GSPC", bars: int = 4) -> pd.DataFrame:
    """Descarga barras mensuales via yfinance. Retorna DataFrame con OHLC."""

def calc_pivot_points(high: float, low: float, close: float) -> dict[str, float]:
    """Calcula PP, R1, R2, S1, S2 clásicos."""

def calc_round_numbers(spot: float, step: int = 25, pct: float = 0.03) -> list[float]:
    """Retorna múltiplos de `step` dentro del rango spot ± pct*spot."""

def build_auto_levels(
    daily_ohlcv: list[dict],   # de data.json["spx_ohlcv"]["ohlcv"]
    weekly_df: pd.DataFrame,
    monthly_df: pd.DataFrame,
    es_spot: float,
    gex_levels: dict,          # de indicators.json: flip_level, put_wall, call_wall
) -> AutoLevels:
    """Ensambla todos los niveles en un AutoLevels."""

def load_auto_levels() -> AutoLevels | None:
    """Lee outputs/mancini_auto_levels.json. Retorna None si no existe o error."""

def save_auto_levels(levels: AutoLevels) -> None:
    """Serializa y escribe outputs/mancini_auto_levels.json."""
```

### Función principal de cálculo

```python
def calculate_and_save(
    data_path: str = "outputs/data.json",
    indicators_path: str = "outputs/indicators.json",
) -> AutoLevels:
    """
    Lee data.json e indicators.json, calcula todos los niveles,
    persiste en mancini_auto_levels.json y retorna el objeto.
    """
```

No tiene dependencias de TastyTrade en tiempo real: usa el `es_premarket`
ya disponible en `data.json`.

---

## Integración con el monitor

### Jerarquía de planes (de mayor a menor preferencia)

```
1. Plan Mancini de hoy (tweet parseado)           → mancini_plan.json
2. Plan stale de ayer (specs/mancini_stale_plan_fallback.md)
3. Auto-levels calculados                          → mancini_auto_levels.json  ← NUEVO
4. Sin plan — monitor en standby
```

### Cambios en `monitor.py`

En `load_state()`, después del bloque stale existente:

```python
# Nivel 3: auto-levels como fallback de último recurso
if plan is None:
    auto = load_auto_levels()
    if auto and auto.fecha == today:
        plan = _auto_levels_to_plan(auto, current_price)
        if plan:
            plan.is_stale = True  # reutiliza el flag para "no es tweet real"
            log("Usando auto-levels calculados como fallback (sin plan de Mancini)")
```

### Función `_auto_levels_to_plan(auto, price) → DailyPlan | None`

Selecciona los dos niveles más relevantes (priority 1, más cercanos al precio)
para mapearlos a `key_level_upper` y `key_level_lower`:

```python
def _auto_levels_to_plan(auto: AutoLevels, price: float) -> DailyPlan | None:
    # Filtra niveles priority 1 dentro de ±50 pts del precio actual
    candidates = [l for l in auto.levels
                  if l.priority == 1 and abs(l.value - price) <= 50]
    if len(candidates) < 2:
        return None  # no suficientes niveles relevantes cerca

    above = [l for l in candidates if l.value > price]
    below = [l for l in candidates if l.value < price]

    if not above or not below:
        return None  # precio en extremo — no construir plan

    upper = min(above, key=lambda l: l.value - price)  # el más cercano arriba
    lower = max(below, key=lambda l: price - l.value)  # el más cercano abajo

    return DailyPlan(
        fecha=auto.fecha,
        raw_tweets=[f"[AUTO] Calculado desde {upper.label} y {lower.label}"],
        key_level_upper=upper.value,
        key_level_lower=lower.value,
        targets_upper=[],   # sin targets conocidos
        targets_lower=[],
        notes=f"Niveles técnicos autónomos. Upper={upper.label}({upper.value}), "
              f"Lower={lower.label}({lower.value}). Sin tweet de Mancini.",
    )
```

### Notificación Telegram diferenciada

`notifier.notify_plan_loaded()` añade un segundo prefijo para auto-levels:

```
📐 Sin plan de Mancini — usando niveles técnicos autónomos

🟢 Upper: 5.580 [PWH]
🔴 Lower: 5.555 [FLIP]

⚠️ Sin targets conocidos. Gestión manual de salidas.
(Se actualizará cuando Mancini publique)
```

---

## Cuándo recalcular

Los auto-levels se calculan una vez al día, idealmente antes de las 09:00 ET.
Dos puntos de cálculo:

1. **`run.py`** (pipeline premarket existente): al final del paso de `fetch_market_data`,
   si existe `indicators.json` del día, llamar `calculate_and_save()`.
   Esto hace que el pipeline premarket actualice automáticamente los niveles.

2. **`run_mancini.py start-day`**: antes de arrancar el monitor, calcular
   si `mancini_auto_levels.json` no existe o es de un día anterior.

No hace falta una tarea de Task Scheduler independiente — los dos puntos
existentes de activación son suficientes.

---

## Validación cruzada (fase 2, no bloquea implementación)

Cuando el plan de Mancini llega, registrar en `logs/mancini_level_match.jsonl`:

```json
{
  "fecha": "2026-04-28",
  "mancini_upper": 5580.0,
  "mancini_lower": 5555.0,
  "auto_upper": 5580.0,
  "auto_lower": 5550.0,
  "upper_match": true,
  "lower_match": false,
  "upper_delta": 0.0,
  "lower_delta": 5.0,
  "matched_label_upper": "PWH",
  "matched_label_lower": "FLIP"
}
```

Un nivel se considera "match" si la distancia al nivel de Mancini es ≤ 5 pts.
Este log permitirá calibrar qué grupos/labels tienen mayor tasa de acierto.

---

## Ficheros afectados

| Fichero | Cambio |
|---------|--------|
| `scripts/mancini/auto_levels.py` | **Nuevo módulo** |
| `scripts/fetch_market_data.py` | Añadir `fetch_weekly_ohlc()` y `fetch_monthly_ohlc()` |
| `outputs/data.json` | Campos nuevos: `spx_weekly_ohlc`, `spx_monthly_ohlc` |
| `scripts/mancini/monitor.py` | `load_state()` — nivel 3 de fallback; `_auto_levels_to_plan()` |
| `scripts/mancini/notifier.py` | Mensaje diferenciado para auto-levels |
| `scripts/run.py` | Llamar `calculate_and_save()` al final del pipeline |
| `scripts/mancini/run_mancini.py` | `start-day` — calcular auto-levels si no existen |

---

## Tests

- `test_calc_pivot_points` — verifica fórmulas PP/R1/R2/S1/S2 con valores conocidos
- `test_calc_round_numbers` — verifica rango y step con spot=5350
- `test_build_auto_levels_completo` — con fixtures de daily/weekly/monthly, verifica
  que todos los grupos están presentes y ordenados por value
- `test_auto_levels_to_plan_selecciona_mas_cercano` — precio en medio de varios
  candidatos → selecciona el más próximo arriba y abajo
- `test_auto_levels_to_plan_insuficientes` — menos de 2 candidatos priority 1 → None
- `test_auto_levels_to_plan_precio_en_extremo` — todos los niveles por encima → None
- `test_calculate_and_save_roundtrip` — escribe y lee `mancini_auto_levels.json`
- `test_monitor_usa_auto_levels_si_no_hay_plan` — sin plan ni stale → monitor usa auto-levels
- `test_monitor_descarta_auto_levels_si_llega_plan` — al llegar tweet real → auto-levels descartados
