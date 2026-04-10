---
name: mancini-scan
description: Lee los tweets recientes de Adam Mancini (@AdamMancini4) via Chrome, extrae el plan del dia con niveles clave para /ES, y guarda en outputs/mancini_plan.json. Usar para cargar o actualizar el plan diario de Mancini.
---

Lee los tweets de Adam Mancini y extrae los niveles clave para la estrategia Failed Breakdown/Breakout en futuros /ES.

## Instrucciones de ejecucion

### Paso 1: Navegar al perfil de Mancini

Usa Chrome MCP para abrir el perfil de Adam Mancini en X:

```
mcp__Claude_in_Chrome__navigate → https://x.com/AdamMancini4
```

Espera a que cargue la pagina.

### Paso 2: Extraer texto de tweets

```
mcp__Claude_in_Chrome__get_page_text
```

Esto devuelve el texto de los tweets visibles en el timeline.

### Paso 3: Identificar el tweet del plan del dia

Busca el **primer tweet del dia** que contenga niveles de /ES. Palabras clave tipicas:
- "Plan today", "plan", "#ES_F"
- "reclaim", "reclaims", "see"
- "fail", "fails", "sell"
- "chop"
- Numeros de 4 digitos (niveles de precio /ES, tipicamente 5000-7000+)

El tweet del plan tiene un formato como:
```
Plan today: 6793/88 - 6830=chop. 6809 reclaims see 6819, 6830. 6788 fails, sell 6781 (watch traps), 6766-70
```

### Paso 4: Extraer niveles estructurados

Del tweet del plan, extrae:

1. **key_level_upper**: el nivel que si se "reclaim" (recupera) indica LONG
   - Busca: "X reclaims", "reclaim X", "above X"
2. **targets_upper**: niveles objetivo alcistas tras el reclaim
   - Busca: "see X, Y", "targets X, Y" despues del reclaim
3. **key_level_lower**: el nivel que si "fails" (rompe) indica venta
   - Busca: "X fails", "fail X", "sell X", "below X"
4. **targets_lower**: niveles objetivo bajistas tras el fail
   - Busca: numeros despues de "sell", "fails" o al final del tweet
5. **chop_zone** (opcional): rango donde el precio oscila sin tendencia
   - Busca: "X-Y=chop", "chop zone X-Y"

**Formato especial de Mancini:**
- "6793/88" significa 6793 o 6788 (dos niveles)
- "6766-70" significa rango 6766 a 6770 (usa 6766 como nivel)
- "watch traps" es una advertencia, no un nivel

### Paso 5: Verificar si ya existe un plan

Lee el plan actual:
```python
# Verificar si outputs/mancini_plan.json existe
```

- Si **no existe plan**: crear nuevo
- Si **existe plan del mismo dia**: hacer merge (anadir nuevos targets sin perder los existentes)
- Si **existe plan de otro dia**: sobreescribir con plan nuevo

### Paso 6: Guardar el plan

Ejecutar desde la raiz del proyecto:

```bash
uv run python -c "
from scripts.mancini.config import DailyPlan, save_plan, load_plan
import json

plan = load_plan()
today = 'YYYY-MM-DD'  # fecha de hoy

if plan and plan.fecha == today:
    # Merge: anadir nuevos targets
    plan.merge_update(
        new_targets_upper=[...],  # nuevos targets si los hay
        new_targets_lower=[...],
        new_tweet='texto del tweet',
        notes='actualizacion intraday'
    )
else:
    # Plan nuevo
    plan = DailyPlan(
        fecha=today,
        key_level_upper=XXXX,
        targets_upper=[XXXX, XXXX],
        key_level_lower=XXXX,
        targets_lower=[XXXX],
        raw_tweets=['texto del tweet'],
        chop_zone=(XXXX, XXXX),  # o None
    )

save_plan(plan)
print(json.dumps(plan.to_dict(), indent=2))
"
```

### Paso 7: Confirmar y notificar

Tras guardar, mostrar resumen:

```
Plan Mancini cargado:
  Fecha:   2026-04-10
  Upper:   6809 -> targets 6819, 6830
  Lower:   6781 -> targets 6766
  Chop:    6788-6830
  Tweets:  1
```

### Paso 8: Buscar actualizaciones intraday

Si el skill se re-ejecuta durante el dia, busca tweets posteriores al plan que contengan:
- Nuevos niveles ("bonus slate", "add", "targets")
- Confirmaciones ("triggered", "hit", "reclaim was long trigger")
- Cambios de niveles

Hace merge en el plan existente sin perder los niveles previos.

## Reglas importantes

- Los niveles de Mancini son siempre para futuros /ES (no SPX, no SPY)
- Solo extraer niveles del dia actual, ignorar tweets de dias anteriores
- Si no hay tweet de plan para hoy, informar y no crear plan
- Si hay ambiguedad en los niveles, ser conservador y pedir confirmacion al usuario
- Nunca inventar niveles que no esten en el tweet
