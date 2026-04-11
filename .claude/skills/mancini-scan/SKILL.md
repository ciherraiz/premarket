---
name: mancini-scan
description: Obtiene tweets de @AdamMancini4 via twikit, extrae niveles con Claude Haiku, y guarda en outputs/mancini_plan.json. Usar para cargar o actualizar el plan diario de Mancini.
---

Obtiene los tweets de Adam Mancini y extrae los niveles clave para la estrategia Failed Breakdown/Breakout en futuros /ES.

## Instrucciones de ejecucion

### Paso 1: Obtener tweets y parsear plan

Ejecutar desde la raiz del proyecto:

```bash
uv run python -c "
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.mancini.tweet_fetcher import fetch_tweets_sync
from scripts.mancini.tweet_parser import parse_tweets_to_plan
from scripts.mancini.config import save_plan, load_plan

today = datetime.now(ZoneInfo('America/New_York')).strftime('%Y-%m-%d')

# Fetch tweets
tweets = fetch_tweets_sync()
if not tweets:
    print('No se encontraron tweets de Mancini para hoy')
    raise SystemExit(1)

print(f'Encontrados {len(tweets)} tweets de hoy')
for i, t in enumerate(tweets, 1):
    print(f'  {i}. {t[\"text\"][:100]}...')

# Parsear con Haiku
plan = parse_tweets_to_plan(tweets, today)
if plan is None:
    print('Haiku determino que no hay plan nuevo hoy')
    raise SystemExit(0)

# Merge si ya existe plan de hoy
existing = load_plan()
if existing and existing.fecha == today:
    for tweet in plan.raw_tweets:
        existing.merge_update(
            new_targets_upper=plan.targets_upper,
            new_targets_lower=plan.targets_lower,
            new_tweet=tweet,
        )
    if plan.chop_zone and not existing.chop_zone:
        existing.chop_zone = plan.chop_zone
    save_plan(existing)
    plan = existing
    print('Plan actualizado (merge con existente)')
else:
    save_plan(plan)
    print('Plan nuevo guardado')

print(json.dumps(plan.to_dict(), indent=2))
"
```

### Paso 2: Confirmar resultado

Mostrar resumen al usuario:

```
Plan Mancini cargado:
  Fecha:   YYYY-MM-DD
  Upper:   XXXX -> targets XXXX, XXXX
  Lower:   XXXX -> targets XXXX
  Chop:    XXXX-XXXX (o None)
  Tweets:  N
```

Si el plan es None (no hay plan hoy), informar al usuario.

## Requisitos

- `X_COOKIES_FILE` o `X_USERNAME` + `X_PASSWORD` en `.env` para twikit
- `ANTHROPIC_API_KEY` en `.env` para Claude Haiku
- No requiere Chrome MCP

## Reglas importantes

- Los niveles de Mancini son siempre para futuros /ES (no SPX, no SPY)
- Solo extraer niveles del dia actual, ignorar tweets de dias anteriores
- Si no hay tweet de plan para hoy, informar y no crear plan
- Si hay ambiguedad en los niveles, mostrar raw tweets y pedir confirmacion
- Nunca inventar niveles que no esten en el tweet
