# Fix: Log compartido bloquea scan cuando monitor está activo

## Incidente 2026-04-16

### Sintomas
- No se recibieron alertas Telegram del sistema Mancini en todo el dia
- Ventana de cmd negra sin informacion visible (usuario no sabe que proceso es)
- El scan empezo a funcionar justo al cerrar la ventana del monitor (~2 min despues)

### Cronologia

| Hora CEST | Hora ET | Evento |
|---|---|---|
| 13:00 | 07:00 | ManciniMonitor arranca (Windows Task Scheduler). Plan en disco tiene fecha 2026-04-15 |
| 13:00-17:14 | 07:00-11:14 | Monitor en bucle `_wait_for_plan()`: lee `mancini_plan.json`, descarta por fecha incorrecta. 256 iteraciones (1/min). **No hay polling de /ES** |
| 13:00-17:14 | 07:00-11:14 | ManciniScan se dispara cada 10 min pero **no deja rastro en el log**. El plan no se actualiza |
| ~17:15 | ~11:15 | Usuario cierra ventana negra del monitor (Ctrl+C, exit code `0xC000013A`) |
| 17:20 | 11:20 | Primera entrada de scan en el log. Crea plan con fecha de hoy |
| 17:22+ | 11:22+ | Scans sucesivos funcionan cada 10 min con normalidad |

### Causa raiz

**Fichero de log compartido con file handle exclusivo en Windows.**

Ambos `.bat` redirigen output al mismo fichero:

```
monitor_start.bat:  uv run python ... monitor >> logs\mancini_scheduler.log 2>&1
scan_start.bat:     uv run python ... scan    >> logs\mancini_scheduler.log 2>&1
```

El monitor es un proceso de **larga duracion** (~9 horas). Su `>> log 2>&1`
mantiene el file handle abierto durante toda la ejecucion. En Windows,
esto impide que `scan_start.bat` pueda abrir el mismo fichero para append.

Resultado:
- Los `echo >> log` del scan fallan silenciosamente
- La redireccion `>> log 2>&1` del Python del scan tambien falla
- El proceso Python del scan posiblemente se ejecuta pero sin output ni efecto visible
- Al matar el monitor, el handle se libera y el scan funciona inmediatamente

### Problema secundario: ventana negra

`monitor_start.bat` redirige **todo** stdout al log. La ventana cmd queda
completamente vacia. El usuario no puede saber:
- Que proceso es (no hay titulo)
- Si esta haciendo algo o esta colgado
- Si debe cerrarla o dejarla abierta

---

## Solucion

### 1. Separar ficheros de log

Cada tarea escribe a su propio fichero de log para evitar contention:

| Tarea | Fichero de log |
|---|---|
| ManciniMonitor | `logs/mancini_monitor.log` |
| ManciniScan | `logs/mancini_scan.log` |
| ManciniMonitorDomingo | `logs/mancini_monitor.log` (mismo, no solapan) |
| ManciniScanDomingo | `logs/mancini_scan.log` (mismo, no solapan) |
| ManciniWeeklyScan | `logs/mancini_weekly.log` |

El fichero `logs/mancini_scheduler.log` se deja de usar como destino compartido.

### 2. Titulo de ventana en los .bat

Anadir `title` al inicio de cada `.bat` para que la barra del cmd muestre
que proceso es:

```bat
title Mancini Monitor /ES
```

```bat
title Mancini Scan
```

### 3. Output dual: consola + log

En vez de redirigir todo al log (dejando la ventana vacia), usar una
estrategia que muestre output en AMBOS sitios.

**Opcion elegida**: modificar el Python (`_log()` en monitor.py) para que
escriba tambien a un fichero de log directamente, y NO usar redireccion
`>>` en el bat. Asi la ventana del cmd muestra el output en tiempo real
y el log se escribe en paralelo.

Cambios en `monitor.py`:
- `_log()` escribe a stdout (visible en ventana) Y append a `logs/mancini_monitor.log`

Cambios en `run_mancini.py` (cmd_scan):
- Los `print()` del scan ya van a stdout. Anadir escritura paralela a
  `logs/mancini_scan.log`

Cambios en los `.bat`:
- Eliminar `>> logs/mancini_scheduler.log 2>&1`
- El bat solo pone `title`, `cd`, `PATH`, y ejecuta `uv run python ...` sin redireccion
- Los echo de inicio/fin del bat siguen escribiendo a su log propio con `>>`

---

## Ficheros a modificar

| Fichero | Cambio |
|---|---|
| `scripts/mancini/monitor_start.bat` | `title` + quitar redireccion stdout |
| `scripts/mancini/scan_start.bat` | `title` + log propio |
| `scripts/mancini/monitor_sunday.bat` | `title` + quitar redireccion stdout |
| `scripts/mancini/scan_sunday.bat` | `title` + log propio |
| `scripts/mancini/weekly_scan_start.bat` | `title` + log propio |
| `scripts/mancini/monitor.py` | `_log()` escribe a fichero + stdout |
| `scripts/mancini/run_mancini.py` | Configurar logging dual en cmd_scan |
| `specs/scheduled_tasks.md` | Actualizar tabla de ficheros de log |

## Actualizacion de spec existente

Actualizar `specs/scheduled_tasks.md`:
- Tabla de ficheros: reemplazar `logs/mancini_scheduler.log` por los logs individuales
- Seccion "Gestión": mencionar que schtasks no funciona desde bash/git-bash,
  usar PowerShell (`Get-ScheduledTask`)
