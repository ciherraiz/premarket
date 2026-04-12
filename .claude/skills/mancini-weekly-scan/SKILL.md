---
name: mancini-weekly-scan
description: Obtiene el tweet Big Picture View de @AdamMancini4 del fin de semana, extrae niveles semanales con Claude Haiku, y guarda en outputs/mancini_weekly.json. Usar para cargar el plan semanal de Mancini.
---

Obtiene el Big Picture View de Adam Mancini y extrae los niveles clave semanales para futuros /ES.

## Instrucciones de ejecucion

### Paso 1: Obtener tweets y parsear plan semanal

Ejecutar desde la raiz del proyecto:

```bash
uv run python -c "
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from scripts.mancini.tweet_fetcher import fetch_mancini_weekend_tweets
from scripts.mancini.tweet_parser import parse_weekly_tweets
from scripts.mancini.config import save_weekly, load_weekly

ET = ZoneInfo('America/New_York')
now = datetime.now(ET)

# Calcular lunes de la proxima semana (o esta si ya es lunes+)
weekday = now.weekday()
if weekday < 5:  # lun-vie: lunes de esta semana
    monday = now - timedelta(days=weekday)
else:  # sab-dom: lunes siguiente
    monday = now + timedelta(days=(7 - weekday))
week_start = monday.strftime('%Y-%m-%d')

# Fetch tweets Big Picture del fin de semana
tweets = fetch_mancini_weekend_tweets()
if not tweets:
    print('No se encontro Big Picture View este fin de semana')
    raise SystemExit(0)

print(f'Encontrados {len(tweets)} tweets Big Picture')
for i, t in enumerate(tweets, 1):
    print(f'  {i}. {t[\"text\"][:120]}...')

# Parsear con Haiku
plan = parse_weekly_tweets(tweets, week_start)
if plan is None:
    print('Haiku determino que no hay plan semanal claro')
    raise SystemExit(0)

# Guardar (sobreescribe si ya existe)
save_weekly(plan)
print(f'Plan semanal guardado para semana del {week_start}')
print(json.dumps(plan.to_dict(), indent=2))
"
```

### Paso 2: Confirmar resultado

Mostrar resumen al usuario:

```
Big Picture Mancini:
  Semana:   2026-04-14
  Soporte:  6817 (minimo: 6793)
  Targets:  6903, 6950, 7068
  Sesgo:    alcista
```

Si no hay Big Picture View, informar al usuario.

## Requisitos

- `cookies.json` en raiz del proyecto (session cookies de x.com)
- `ANTHROPIC_API_KEY` en `.env` para Claude Haiku

## Reglas importantes

- Solo busca tweets del sabado y domingo mas recientes
- Solo extrae tweets que contengan "Big Picture" o "Plan Next Week"
- Los niveles son siempre para futuros /ES
- Si no hay Big Picture, no crear plan semanal
- Nunca inventar niveles que no esten en el tweet
