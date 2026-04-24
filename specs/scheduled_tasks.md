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
| `scan`         | one-shot      | Fetch tweets + parse + save/merge plan (uso manual o en start-day) |
| `weekly-scan`  | one-shot      | Fetch Big Picture + parse + save weekly  |
| `monitor`      | larga duración | Polling /ES cada 60s + scan de tweets integrado cada 10 min + updates intraday |
| `status`       | one-shot      | Muestra estado actual                    |
| `reset`        | one-shot      | Resetea estado para nuevo día            |

**El monitor es autosuficiente**: integra el scan de tweets internamente
(`_scan_for_plan()` y `check_intraday_updates()`). No se necesita ninguna
tarea externa de scan corriendo en paralelo.

### Wrapper: batch files

Cada tarea de Task Scheduler ejecuta un `.bat` en `scripts/mancini/` que:
1. Pone `title` en la ventana cmd (ej. "Mancini Monitor /ES")
2. Hace `cd` al directorio del proyecto
3. Añade `uv` al PATH
4. Ejecuta el subcomando correspondiente (sin redirección `>>`)

El output va a **consola** (ventana cmd visible) y a **fichero de log**
simultáneamente, gestionado por `_Tee` en `run_mancini.py`. Cada tarea
escribe a su propio fichero para evitar contención de file handles en Windows:
monitor → `logs/mancini_monitor.log`, scan → `logs/mancini_scan.log`,
weekly → `logs/mancini_weekly.log`.

---

## Tareas registradas en Task Scheduler

### 1. ManciniMonitor (diario, entre semana)

**Script**: `scripts/mancini/monitor_start.bat`
**Subcomando**: `run_mancini.py monitor`
**Ventana**: 09:00–22:00 CEST (03:00–16:00 ET)
**Cadencia**: una sola invocación (el monitor corre su propio loop de polling)

| Parámetro Task Scheduler | Valor |
|---|---|
| Nombre | `ManciniMonitor` |
| Trigger | Lun-Vie, inicio 09:00 CEST |
| Acción | `scripts/mancini/monitor_start.bat` |
| Múltiples instancias | No iniciar nueva si ya hay una corriendo |

El monitor arranca a las 09:00 CEST (apertura sesión europea) y empieza
a pollear /ES inmediatamente (`SESSION_START_HOUR` = 03:00 ET). Si no hay
plan del día, **busca tweets de Mancini él mismo** cada 10 min hasta
obtenerlo (`_scan_for_plan()`). Una vez con plan, detecta patrones y
también clasifica tweets intraday nuevos (`check_intraday_updates()`) cada
10 min. No se necesita ningún proceso de scan externo.

**Session end**: el monitor se auto-finaliza a las 16:00 ET (`SESSION_END_HOUR`).

### 3. ManciniMonitorDomingo (domingos)

**Script**: `scripts/mancini/monitor_sunday.bat`
**Subcomando**: `run_mancini.py monitor --start 18 --end 24`
**Ventana**: 00:00 CEST lunes (18:00 ET domingo) – 06:00 CEST lunes (00:00 ET)

| Parámetro Task Scheduler | Valor |
|---|---|
| Nombre | `ManciniMonitorDomingo` |
| Trigger | Domingos, inicio 00:00 CEST (lunes) |
| Acción | `scripts/mancini/monitor_sunday.bat` |

Futuros /ES abren a las 18:00 ET los domingos. El monitor usa `--start 18`
para alinearse con la apertura real de futuros y `--end 24` para cubrir
la sesión nocturna hasta medianoche ET. El lunes a las 13:00 CEST arranca
el monitor normal (`monitor_start.bat`) que cubre la sesión RTH.

### 4. ManciniWeeklyScan (fines de semana)

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
09:00 ─── ManciniMonitor arranca (start-day: scan + monitor) ───
  ...     Monitor pollea /ES cada 60s
  ...     Si sin plan: busca tweets cada 10 min (_scan_for_plan)
  ...     Si con plan: clasifica tweets intraday cada 10 min
15:30 ─── Apertura mercado (09:30 ET) ───────────────────────────
22:00 ─── ManciniMonitor termina (16:00 ET) ─────────────────────
```

## Resumen visual — Fin de semana (horario CEST)

```
18:00     ManciniWeeklyScan (Sab+Dom, cada 2h hasta 00:00)
00:00     ManciniMonitorDomingo arranca (18:00 ET, sesión nocturna)
          Monitor busca tweets de Mancini internamente si los publica
06:00 ─── ManciniMonitorDomingo termina (00:00 ET) ─────────────
```

---

## Ficheros involucrados

| Fichero | Propósito |
|---|---|
| `scripts/mancini/run_mancini.py` | CLI con todos los subcomandos |
| `scripts/mancini/monitor_start.bat` | Wrapper para Task Scheduler (monitor L-V) |
| `scripts/mancini/monitor_sunday.bat` | Wrapper para Task Scheduler (monitor dom) |
| `scripts/mancini/weekly_scan_start.bat` | Wrapper para Task Scheduler (weekly) |
| `logs/mancini_monitor.log` | Output del monitor (polling, tweets, detectores, trades) |
| `logs/mancini_weekly.log` | Output de los scans semanales |
| `logs/mancini_scans.jsonl` | Registro estructurado de cada scan (éxito/fallo) |

---

## Gestión de las tareas

### Listar tareas registradas

**Usar schtasks** (PowerShell Get-ScheduledTask puede no mostrar todas):

```bash
schtasks /query /fo LIST | grep -A2 "Mancini"
```

### Ejecutar manualmente

```bash
# Arrancar/reiniciar el monitor (idempotente)
scripts/mancini/monitor_start.bat

# Forzar scan de tweets manualmente (sin lanzar monitor)
uv run python scripts/mancini/run_mancini.py scan

# Scan semanal
uv run python scripts/mancini/run_mancini.py weekly-scan
```

### Eliminar tarea

```cmd
schtasks /delete /tn "NombreTarea" /f
```
