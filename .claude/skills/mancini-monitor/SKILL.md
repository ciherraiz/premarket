---
name: mancini-monitor
description: Arranca el monitor de precio /ES para la estrategia Mancini. Requiere plan cargado previamente con /mancini-scan. Ejecuta polling cada 60s, detecta Failed Breakdowns y envia alertas Telegram.
---

Arranca el monitor de precio /ES para detectar Failed Breakdowns segun el plan de Mancini.

## Prerequisitos

- Plan del dia cargado en `outputs/mancini_plan.json` (ejecutar `/mancini-scan` primero)
- Credenciales TastyTrade en `.env` (TT_SECRET, TT_REFRESH)
- Credenciales Telegram en `.env` (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)

## Instrucciones de ejecucion

### Paso 1: Verificar que hay plan cargado

```bash
uv run python scripts/mancini/run_mancini.py status
```

Si no hay plan, ejecutar `/mancini-scan` primero.

### Paso 2: Arrancar el monitor

```bash
uv run python scripts/mancini/run_mancini.py monitor
```

Opciones:
- `--interval 60` — intervalo de polling en segundos (default: 60)

### Paso 3: El monitor corre en foreground

El monitor:
- Polls /ES cada 60 segundos via TastyTrade
- Detecta patrones Failed Breakdown en los niveles del plan
- Envia alertas Telegram en cada transicion de estado
- Se auto-finaliza a las 11:00 ET
- Persiste estado en `outputs/mancini_state.json`

### Paso 4: Mostrar resumen de estado

Tras arrancar, mostrar:

```
Monitor Mancini arrancado.
  Plan:     2026-04-10
  Upper:    6809 -> targets 6819, 6830
  Lower:    6781 -> targets 6766
  Intervalo: 60s
  Sesion:   08:00-11:00 ET
```

## Otros comandos utiles

```bash
# Ver estado actual
uv run python scripts/mancini/run_mancini.py status

# Resetear para nuevo dia
uv run python scripts/mancini/run_mancini.py reset
```

## Notas

- El monitor es un proceso de larga duracion — corre hasta las 11:00 ET o Ctrl+C
- Si se interrumpe, el estado se persiste y se puede retomar
- El scan de tweets (`/mancini-scan`) puede actualizar el plan en paralelo; el monitor detecta cambios automaticamente
