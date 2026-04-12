# Mancini Weekly Plan — Big Picture View

## Objetivo

Capturar el "Big Picture View" que Mancini publica los fines de semana (sábado o
domingo). Este tweet establece el marco semanal: niveles clave, tendencia dominante
y targets de medio plazo. Sirve como contexto para los planes diarios.

## Qué es el Big Picture View

Mancini publica un tweet los fines de semana con un resumen de la semana pasada
y el plan para la siguiente. Formato típico:

```
Big Picture View: Last week, #ES_F built a 1 month bull flag & it was set to
breakout. This week, it did, ending the downtrend & rallied 300 points.

Plan Next Week: Bulls want to hold 6817, 6793 lowest. This keeps 6903, 6950
live. Dip, then 7068. 6793 fails, we retrace.
```

Contiene:
- **Resumen semana pasada**: qué pasó, qué patrón se formó
- **Sesgo semanal**: alcista/bajista/neutral
- **Niveles clave semanales**: soportes y resistencias de mayor escala
- **Targets semanales**: objetivos de precio a varios días

## Modelo de datos

Reutilizar la estructura `DailyPlan` existente (mismos campos), con dos diferencias:
- `fecha` = lunes de la semana (YYYY-MM-DD), no el día del tweet
- Persistencia en `outputs/mancini_weekly.json` (separado del plan diario)

```python
WEEKLY_PLAN_PATH = Path("outputs/mancini_weekly.json")
```

No se crea un nuevo dataclass. Se usa `DailyPlan` con funciones dedicadas
`save_weekly()` / `load_weekly()` que apuntan al path semanal.

## Módulos afectados

### config.py

Añadir:
```python
WEEKLY_PLAN_PATH = Path("outputs/mancini_weekly.json")

def save_weekly(plan: DailyPlan, path: Path = WEEKLY_PLAN_PATH) -> None
def load_weekly(path: Path = WEEKLY_PLAN_PATH) -> DailyPlan | None
```

### tweet_fetcher.py

Añadir función:
```python
def fetch_mancini_weekend_tweets(max_tweets: int = 40) -> list[dict]
```

Igual que `fetch_mancini_tweets()` pero filtra a **sábado y domingo** en vez
de solo hoy. Busca tweets que contengan "Big Picture" o "Plan Next Week".

### tweet_parser.py

Añadir función:
```python
def parse_weekly_tweets(tweets: list[dict], week_start: str) -> DailyPlan | None
```

Usa un system prompt adaptado que entiende el formato Big Picture View:
- "Bulls want to hold X, Y lowest" → key_level_upper=X, key_level_lower=Y
- "This keeps X, Y live" → targets_upper
- "X fails, we retrace" → key_level_lower
- Incluye campo `notes` con el resumen/sesgo de la semana

### notifier.py

Añadir función:
```python
def notify_weekly_plan(plan: dict) -> bool
```

Alerta Telegram con formato:
```
📊 Mancini Big Picture | Semana 2026-04-14
🟢 Soporte clave: 6817 (mínimo: 6793)
🎯 Targets semana: 6903, 6950, 7068
📝 Sesgo: alcista mientras aguante 6793
```

## Uso como contexto

El plan semanal enriquece la operativa diaria:

1. **Monitor**: al cargar el plan diario, lee también `mancini_weekly.json` y
   compara si los niveles diarios están alineados con el sesgo semanal
2. **Scorecard**: muestra contexto semanal junto al plan del día
3. **Decisiones**: si el plan diario es ambiguo, el sesgo semanal desempata

## Scheduled task

Crear `mancini-weekly-scan`:
- **Horario**: sábado y domingo, 18:00 CEST (12:00 ET), una vez cada día
- **Cron**: `0 18 * * 0,6`
- **Acción**: fetch tweets del fin de semana → parse Big Picture → save weekly
- Si no encuentra Big Picture View, no crea plan (a veces lo publica más tarde)

## Skill

Crear `/mancini-weekly-scan`:
- Mismo flujo que `/mancini-scan` pero llama a las funciones weekly
- Permite ejecución manual si la scheduled task no capturó el tweet

## Ficheros

- `outputs/mancini_weekly.json` — plan semanal (sobrescrito cada fin de semana)
- No se loguea en `mancini_trades.jsonl` (es solo contexto, no genera trades)

## Tests

- `test_weekly_plan`: save/load weekly, merge con plan existente
- `test_fetch_weekend_tweets`: filtrado sábado/domingo, detección "Big Picture"
- `test_parse_weekly`: extracción de niveles del formato Big Picture View
- `test_notify_weekly`: formato de alerta Telegram
