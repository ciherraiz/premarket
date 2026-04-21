---
name: mancini-monitor
description: Arranca el monitor de precio /ES para la estrategia Mancini. Usa start-day (idempotente) para gestionar el ciclo de vida completo: scan + launch + health check. Detecta Failed Breakdowns y envia alertas Telegram.
---

Arranca el monitor de precio /ES para detectar Failed Breakdowns segun el plan de Mancini.

## Prerequisitos

- Credenciales TastyTrade en `.env` (TT_SECRET, TT_REFRESH)
- Credenciales Telegram en `.env` (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)

## Instrucciones de ejecucion

### Paso 1: Comprobar estado del sistema

```bash
uv run python scripts/mancini/run_mancini.py health
```

### Paso 2: Arrancar la jornada (comando principal)

```bash
uv run python scripts/mancini/run_mancini.py start-day
```

Este comando es **idempotente** y gestiona todo el ciclo:
1. Si el monitor ya corre y está sano → no hace nada
2. Mata procesos huérfanos
3. Limpia estado del día anterior
4. Ejecuta scan de tweets (obtiene el plan)
5. Lanza el monitor como proceso detached (sobrevive al cierre del terminal)
6. Verifica arranque via PID file + primera quote
7. Notifica a Telegram

Opciones:
- `--skip-scan` — no ejecutar scan (usar plan ya existente)
- `--dry-run` — mostrar qué haría sin ejecutar nada

### Paso 3: Mostrar resumen de estado

Tras arrancar, mostrar la salida de `health`:

```
=== Mancini System Health ===
Plan:       ✓ 2026-04-21  (upper=5300 → [5320, 5340])
Monitor:    ✓ CORRIENDO (PID 12345, activo hace 2m 30s)
Quote:      ✓ OK  ES=5300.50  hace 45s
Detectores: 2 activo(s)
Trade:      sin trade activo

Estado general: ✓ OK
```

## Otros comandos utiles

```bash
# Parar el monitor limpiamente
uv run python scripts/mancini/run_mancini.py stop-day

# Parar forzando kill inmediato
uv run python scripts/mancini/run_mancini.py stop-day --force

# Recuperar sistema desde estado inconsistente (PID stale, huérfanos, plan viejo)
uv run python scripts/mancini/run_mancini.py recover

# Ver estado sin modificar nada
uv run python scripts/mancini/run_mancini.py health

# Arrancar monitor directamente (sin scan, sin gestión de ciclo de vida)
uv run python scripts/mancini/run_mancini.py monitor
```

## Notas

- El monitor corre como proceso completamente independiente (DETACHED_PROCESS en Windows)
- El PID file `outputs/mancini_monitor.pid` es la única fuente de verdad sobre si está activo
- Si hay problemas tras un reinicio, usar `recover` antes que `start-day`
- El scan de tweets (`/mancini-scan`) puede actualizar el plan en paralelo; el monitor detecta cambios automaticamente
