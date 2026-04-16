# Tareas programadas — Referencia completa

Documento de referencia para todas las tareas automáticas del sistema.

## Decisiones de arquitectura

### Scheduler: Windows Task Scheduler (obligatorio)

**Todas** las tareas recurrentes del sistema se ejecutan mediante
**Windows Task Scheduler**, que garantiza persistencia independientemente
de si hay una sesión de Claude Code abierta.

**Prohibido**: usar CronCreate, `mcp__scheduled-tasks`, o cualquier otro
mecanismo que dependa de una sesión activa de Claude Code. Estos mecanismos
son efímeros (se pierden al cerrar la sesión, auto-expiran tras 7 días) y
han causado fallos de producción (2026-04-15: scans no ejecutados por falta
de sesión activa).

### Ejecución: scripts Python standalone

Cada tarea se ejecuta mediante `uv run python scripts/mancini/run_mancini.py <subcomando>`.
Los subcomandos disponibles son:

| Subcomando     | Tipo          | Descripción                              |
|----------------|---------------|------------------------------------------|
| `scan`         | one-shot      | Fetch tweets + parse + save/merge plan   |
| `weekly-scan`  | one-shot      | Fetch Big Picture + parse + save weekly  |
| `monitor`      | larga duración | Polling /ES cada 60s, espera plan si no existe, auto-para a las 16:00 ET |
| `status`       | one-shot      | Muestra estado actual                    |
| `reset`        | one-shot      | Resetea estado para nuevo día            |

### Wrapper: batch files

Cada tarea de Task Scheduler ejecuta un `.bat` en `scripts/mancini/` que:
1. Hace `cd` al directorio del proyecto
2. Añade `uv` al PATH
3. Ejecuta el subcomando correspondiente
4. Redirige output a `logs/mancini_scheduler.log`

---

## Tareas registradas en Task Scheduler

### 1. ManciniScan (diario, entre semana)

**Script**: `scripts/mancini/scan_start.bat`
**Subcomando**: `run_mancini.py scan`
**Ventana**: 13:00–22:00 CEST (07:00–16:00 ET) — cubre toda la sesión regular
**Cadencia**: cada 10 minutos dentro de la ventana

| Parámetro Task Scheduler | Valor |
|---|---|
| Nombre | `ManciniScan` |
| Trigger | Lun-Vie, inicio 13:00 CEST, repetir cada 10 min durante 9h |
| Acción | `scripts/mancini/scan_start.bat` |
| Múltiples instancias | No iniciar nueva si ya hay una corriendo |

El scan es idempotente: si no hay tweets nuevos, termina sin error y sin
notificar (evita spam). Solo notifica a Telegram cuando el plan cambia.
La ventana cubre toda la sesión regular para capturar actualizaciones
intraday de Mancini.

**Prerequisitos**: `cookies.json` (sesión X) y `ANTHROPIC_API_KEY` en `.env`

### 2. ManciniMonitor (diario, entre semana)

**Script**: `scripts/mancini/monitor_start.bat`
**Subcomando**: `run_mancini.py monitor`
**Ventana**: 13:00–22:00 CEST (07:00–16:00 ET)
**Cadencia**: una sola invocación (el monitor corre su propio loop de polling)

| Parámetro Task Scheduler | Valor |
|---|---|
| Nombre | `ManciniMonitor` |
| Trigger | Lun-Vie, inicio 13:00 CEST |
| Acción | `scripts/mancini/monitor_start.bat` |
| Múltiples instancias | No iniciar nueva si ya hay una corriendo |

El monitor arranca a las 13:00 CEST y espera internamente hasta
`SESSION_START_HOUR` (07:00 ET). Si no hay plan del día cuando entra en
sesión, **espera y reintenta** cada 60s en vez de pararse — el scan corre
en paralelo y creará el plan cuando Mancini publique. En cuanto el plan
aparece, el monitor lo carga y empieza a pollear /ES.

**Session end**: el monitor se auto-finaliza a las 16:00 ET (`SESSION_END_HOUR`).

### 3. ManciniMonitorDomingo (domingos)

**Script**: `scripts/mancini/monitor_sunday.bat`
**Subcomando**: `run_mancini.py monitor --start 13 --end 24`
**Ventana**: 19:00 CEST domingo – 00:00 ET lunes

| Parámetro Task Scheduler | Valor |
|---|---|
| Nombre | `ManciniMonitorDomingo` |
| Trigger | Domingos, inicio 19:00 CEST |
| Acción | `scripts/mancini/monitor_sunday.bat` |

Futuros /ES abren a las 18:00 ET los domingos. Este monitor usa la ventana
extendida `--start 13 --end 24` para cubrir la sesión nocturna.

### 4. ManciniScanDomingo (domingos)

**Script**: `scripts/mancini/scan_sunday.bat`
**Subcomando**: `run_mancini.py scan`
**Ventana**: 18:00–23:00 CEST domingo (12:00–17:00 ET)
**Cadencia**: cada 10 minutos dentro de la ventana

| Parámetro Task Scheduler | Valor |
|---|---|
| Nombre | `ManciniScanDomingo` |
| Trigger | Domingos, inicio 18:00 CEST, repetir cada 10 min durante 5h |
| Acción | `scripts/mancini/scan_sunday.bat` |
| Múltiples instancias | No iniciar nueva si ya hay una corriendo |

Mancini a veces publica niveles el domingo por la tarde para la sesión
nocturna. Este scan cubre desde la apertura de futuros (18:00 ET) hasta
las 23:00 CEST. Reutiliza el mismo subcomando `scan` que entre semana.

### 5. ManciniWeeklyScan (fines de semana)

**Script**: `scripts/mancini/weekly_scan_start.bat`
**Subcomando**: `run_mancini.py weekly-scan`
**Días**: sábado y domingo

| Parámetro Task Scheduler | Valor |
|---|---|
| Nombre | `ManciniWeeklyScan` |
| Trigger | Sáb y Dom, inicio 18:00 CEST, repetir cada 2h durante 6h |
| Acción | `scripts/mancini/weekly_scan_start.bat` |
| Múltiples instancias | No iniciar nueva si ya hay una corriendo |

Mancini publica su "Big Picture View" el fin de semana (sábado o domingo,
hora variable). Se escanea cada 2 horas para capturarlo cuando aparezca.
El script es idempotente: si ya existe plan semanal, sobreescribe con la
versión más reciente.

### 6. SPX Premarket + Open Analysis (entre semana)

**Nota**: estas tareas usan `mcp__scheduled-tasks` (no Task Scheduler)
porque ejecutan skills de Claude Code (`/premarket-analysis`,
`/open-analysis`) que requieren una sesión activa. Ver sección
"Tareas en `mcp__scheduled-tasks`" más abajo para detalle.

---

## Tareas en `mcp__scheduled-tasks` (Claude Code)

`mcp__scheduled-tasks` es un scheduler de Claude Code que ejecuta skills
(ficheros `SKILL.md`) dentro de una sesión activa. A diferencia de Task
Scheduler, **requiere que Claude Code esté abierto** para funcionar.

### Tareas activas (requieren sesión Claude Code)

| Tarea | Horario | Motivo |
|---|---|---|
| `spx-premarket-analysis` | L-V 15:10 CEST (09:10 ET) | Ejecuta skill `/premarket-analysis` que necesita Claude |
| `spx-open-analysis` | L-V 16:25 CEST (10:15 ET) | Ejecuta skill `/open-analysis` que necesita Claude |

Estas tareas son aceptables en `mcp__scheduled-tasks` porque el usuario
abre sesión manualmente antes de la apertura del mercado.

### Tareas legacy Mancini (desactivadas 2026-04-15)

Las siguientes tareas fueron **desactivadas** tras la migración a Windows
Task Scheduler. Contenían código Python inline en sus `SKILL.md` que
duplicaba la lógica de `run_mancini.py` — ejecutaban exactamente la misma
lógica de fetch/parse/notify pero dentro de una sesión de Claude Code.

| Tarea Claude Code | Reemplazada por | Estado |
|---|---|---|
| `mancini-scan` | ManciniScan | Desactivada |
| `mancini-weekly-scan` | ManciniWeeklyScan | Desactivada |
| `mancini-scan-domingo` | ManciniScanDomingo | Desactivada |
| `mancini-monitor-start` | ManciniMonitor | Desactivada |

Los ficheros SKILL.md persisten en `~/.claude/scheduled-tasks/mancini-*/`
pero no se ejecutan. No hay API de borrado, solo desactivación.

---

## Resumen visual — Día entre semana (horario CEST)

```
13:00 ─── ManciniScan comienza (cada 10 min) ───────────────────
13:00     ManciniMonitor arranca (espera plan + session_start)
  ...     Monitor reintenta cada 60s hasta que el scan cree el plan
15:30 ─── Apertura mercado (09:30 ET) ───────────────────────────
22:00 ─── ManciniScan + ManciniMonitor terminan (16:00 ET) ──────
```

## Resumen visual — Fin de semana (horario CEST)

```
18:00     ManciniWeeklyScan (Sab+Dom, cada 2h hasta 00:00)
18:00 ─── ManciniScanDomingo comienza (Dom, cada 10 min) ───────
19:00     ManciniMonitorDomingo (Dom, espera plan + polling /ES)
23:00 ─── ManciniScanDomingo termina ───────────────────────────
```

---

## Ficheros involucrados

| Fichero | Propósito |
|---|---|
| `scripts/mancini/run_mancini.py` | CLI con todos los subcomandos |
| `scripts/mancini/scan_start.bat` | Wrapper para Task Scheduler (scan) |
| `scripts/mancini/weekly_scan_start.bat` | Wrapper para Task Scheduler (weekly) |
| `scripts/mancini/monitor_start.bat` | Wrapper para Task Scheduler (monitor L-V) |
| `scripts/mancini/scan_sunday.bat` | Wrapper para Task Scheduler (scan dom) |
| `scripts/mancini/monitor_sunday.bat` | Wrapper para Task Scheduler (monitor dom) |
| `logs/mancini_scheduler.log` | Output de todas las ejecuciones |
| `logs/mancini_scans.jsonl` | Registro de cada scan (éxito/fallo) |

---

## Gestión de las tareas

### Listar tareas registradas

```cmd
schtasks /query /tn "ManciniScan"
schtasks /query /tn "ManciniMonitor"
schtasks /query /tn "ManciniScanDomingo"
schtasks /query /tn "ManciniMonitorDomingo"
schtasks /query /tn "ManciniWeeklyScan"
```

### Ejecutar manualmente

```bash
uv run python scripts/mancini/run_mancini.py scan
uv run python scripts/mancini/run_mancini.py weekly-scan
uv run python scripts/mancini/run_mancini.py monitor
```

### Eliminar tarea

```cmd
schtasks /delete /tn "NombreTarea" /f
```
