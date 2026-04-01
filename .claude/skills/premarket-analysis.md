# Skill: /premarket-analysis

Ejecuta el pipeline completo de análisis premarket SPX 0DTE y envía el resultado a Telegram.

## Argumentos

| Argumento | Valores | Default | Descripción |
|---|---|---|---|
| `--phase` | `premarket` \| `open` | `premarket` | Fase a ejecutar |
| `--window` | entero (minutos) | `30` | Ventana open phase |

## Instrucciones de ejecución

### Paso 1: Determinar fase y parámetros

- Sin argumentos o `--phase premarket` → `phase=premarket`
- `--phase open` → `phase=open`, `window=30` (o el valor de `--window` si se provee)

### Paso 2: Verificar directorio de trabajo

El pipeline debe ejecutarse desde la **raíz del proyecto** (donde están `scripts/` y `outputs/`).
Si el directorio actual no es la raíz, navegar allí antes de ejecutar.

### Paso 3: Ejecutar el pipeline

**Fase premarket:**
```bash
uv run python scripts/run.py --phase premarket --notify
```

**Fase open:**
```bash
uv run python scripts/run.py --phase open --window {WINDOW} --notify
```

El flag `--notify` envía automáticamente el resultado a Telegram al finalizar.
No ejecutar el pipeline más de una vez por invocación del skill.

### Paso 4: Mostrar resumen de estado

Tras la ejecución, mostrar solo un resumen conciso — no repetir el scorecard
que ya se ha impreso en terminal:

```
Pipeline completado.
  Fase:     {phase}
  Outputs:  outputs/indicators.json actualizado
  Telegram: mensaje enviado ✓
```

Si la notificación falla (aviso en stderr), indicarlo:
```
Pipeline completado.
  Fase:     {phase}
  Outputs:  outputs/indicators.json actualizado
  Telegram: ERROR — revisar TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID en .env
```

### Paso 5: En caso de error del pipeline

Si el pipeline falla (exit code != 0):
1. Mostrar el error completo de stderr
2. No enviar nada a Telegram
3. Sugerir diagnóstico según el error:
   - `MISSING_DATA` en fetch → verificar conexión de red y credenciales TastyTrade en `.env`
   - `ModuleNotFoundError: httpx` → ejecutar `uv add httpx`
   - `TELEGRAM_BOT_TOKEN no configurado` → añadir variables en `.env`

## Reglas de formato

El mensaje Telegram lo genera `scripts/notify_telegram.py` con formato MarkdownV2 fijo.
Claude **no genera ni modifica** el texto del mensaje Telegram.
El formato está definido en `specs/skill_premarket_analysis.md` sección "Plantilla Telegram".

## Ejemplos de uso

```
/premarket-analysis
→ uv run python scripts/run.py --phase premarket --notify

/premarket-analysis --phase open
→ uv run python scripts/run.py --phase open --window 30 --notify

/premarket-analysis --phase open --window 15
→ uv run python scripts/run.py --phase open --window 15 --notify
```

## Ejecución automática (tareas programadas)

Este skill se ejecuta automáticamente a través de tareas programadas:
- **09:10 ET (L-V):** fase premarket → scorecard orientativo
- **10:15 ET (L-V):** fase open (ventana 30min) → análisis final + estrategia

Ver `specs/skill_premarket_analysis.md` sección "Tareas programadas" para la configuración.
