# Mancini Health Manager — Gestión de procesos y estado del sistema

## Problema

El sistema Mancini es un proceso de larga duración (monitor) coordinado con
tareas periódicas (scan). Sin un contrato claro de "qué proceso es el oficial
y cuál es su estado", cada intento de diagnóstico o reinicio puede crear
instancias duplicadas que compiten, escriben en el mismo log y acceden al
mismo archivo de estado. En casos reales se han observado 13 procesos monitor
corriendo simultáneamente.

Las causas raíz:

1. **Sin PID file** — no hay forma de saber si el monitor está corriendo sin
   escanear todos los procesos del sistema.
2. **Sin stop limpio** — matar por nombre de proceso (`run_mancini.py`) termina
   el proceso abruptamente, sin flush de estado.
3. **Sin start idempotente** — lanzar el monitor dos veces crea dos monitores.
4. **Sin health check rápido** — diagnosticar el sistema requiere leer logs,
   buscar procesos y revisar JSONs manualmente.

---

## Objetivo

Un módulo `scripts/mancini/health.py` que:

- Gestiona el ciclo de vida del monitor con **PID file** como única fuente de
  verdad sobre si el proceso está activo.
- Expone comandos de ciclo de jornada: `start-day`, `stop-day`, `health`,
  `recover`.
- Hace que cada operación sea **idempotente**: ejecutarla dos veces tiene el
  mismo efecto que ejecutarla una.
- Ofrece un camino de recuperación determinista ante cualquier estado corrupto.

---

## Archivos nuevos / modificados

```
scripts/mancini/health.py          ← módulo nuevo (este spec)
outputs/mancini_monitor.pid        ← PID file (runtime, no commitear)
outputs/mancini_stop               ← stop flag (runtime, no commitear)
scripts/mancini/run_mancini.py     ← nuevos subcomandos: start-day, stop-day,
                                      health, recover
```

---

## Componente 1: PID file

### Ubicación

```
outputs/mancini_monitor.pid
```

### Ciclo de vida

| Evento | Acción sobre el PID file |
|--------|--------------------------|
| Monitor arranca | Escribe su PID |
| Monitor termina limpiamente | Elimina el archivo |
| Monitor termina por crash | Archivo queda stale (PID inválido) |
| `start-day` | Comprueba PID file antes de lanzar |
| `stop-day` | Espera a que el monitor lo elimine |
| `recover` | Limpia PID file stale si el proceso no existe |

### API

```python
PID_PATH = Path("outputs/mancini_monitor.pid")

def write_pid(pid: int) -> None:
    """Escribe PID del proceso actual en el archivo."""

def read_pid() -> int | None:
    """Lee PID del archivo. Retorna None si no existe."""

def clear_pid() -> None:
    """Elimina el PID file (llamado al cerrar el monitor)."""

def is_monitor_running() -> bool:
    """True si el PID file existe y el proceso está vivo."""

def get_stale_pids() -> list[int]:
    """Busca procesos run_mancini monitor huérfanos (sin PID file válido)."""
```

### Comportamiento de `is_monitor_running()`

```python
def is_monitor_running() -> bool:
    pid = read_pid()
    if pid is None:
        return False
    # Comprobar si el proceso existe en el sistema
    try:
        os.kill(pid, 0)   # señal 0 = no hace nada, solo comprueba existencia
        return True
    except (ProcessLookupError, PermissionError):
        return False      # proceso no existe → PID file stale
```

---

## Componente 2: Stop flag

Para shutdown limpio sin depender de señales Unix (problemático en Windows).

```
outputs/mancini_stop
```

El monitor comprueba en cada ciclo del loop si este archivo existe. Si existe:
- Termina el ciclo limpiamente
- Guarda estado
- Elimina el PID file
- Elimina el stop flag
- Sale con código 0

```python
STOP_FLAG_PATH = Path("outputs/mancini_stop")

def request_stop() -> None:
    """Crea el stop flag para pedir al monitor que se detenga."""
    STOP_FLAG_PATH.touch()

def clear_stop_flag() -> None:
    """Elimina el stop flag (llamado por el monitor al arrancar y al salir)."""
    STOP_FLAG_PATH.unlink(missing_ok=True)

def stop_requested() -> bool:
    """True si el stop flag existe."""
    return STOP_FLAG_PATH.exists()
```

### Cambio en `monitor.py`

En el loop principal, añadir comprobación al inicio de cada ciclo:

```python
while True:
    # ── NUEVO: comprobar stop flag ──
    if stop_requested():
        _log("Stop solicitado — cerrando monitor limpiamente")
        clear_stop_flag()
        self.close_session()
        break

    now = _now_et()
    if now.hour >= self.session_end:
        ...
```

---

## Componente 3: Monitor con PID file integrado

### Cambios en `ManciniMonitor.run()`

```python
def run(self) -> None:
    from scripts.mancini.health import write_pid, clear_pid, clear_stop_flag, stop_requested

    # Limpiar stop flag de ejecuciones anteriores
    clear_stop_flag()

    # Registrar PID
    write_pid(os.getpid())
    _log("Monitor arrancando...")

    try:
        while True:
            if stop_requested():
                _log("Stop solicitado — cerrando limpiamente")
                clear_stop_flag()
                self.close_session()
                break
            ...  # loop existente sin cambios
    finally:
        clear_pid()   # siempre limpiar PID al salir (crash o normal)
```

---

## Componente 4: Comando `health`

Muestra el estado del sistema en menos de 2 segundos. No modifica ningún estado.

### Salida esperada

```
=== Mancini System Health ===

Plan:       2026-04-21 ✓  (upper=7147 → [7186, 7194, 7217])
Monitor:    CORRIENDO (PID 12644, arrancó hace 1h 23m)
Quote:      OK  ES=7131.38  hace 47s
Detectores: 1 activo  (upper 7147 → WATCHING)
Trade:      sin trade activo

Estado general: ✓ OK
```

### Salidas de error

```
Plan:       ✗ NO HAY PLAN para hoy (último: 2026-04-20)
Monitor:    ✗ DETENIDO  (PID file stale: PID 9999 no existe)
Quote:      ✗ ERROR  (último intento hace 3m 12s)
Detectores: 0 activos
Trade:      -

Estado general: ✗ DEGRADADO — ejecutar: uv run python scripts/mancini/run_mancini.py recover
```

### Implementación

```python
@dataclass
class SystemHealth:
    plan_ok: bool
    plan_fecha: str | None
    plan_upper: float | None
    plan_targets_upper: list[float]
    monitor_running: bool
    monitor_pid: int | None
    monitor_uptime_s: float | None    # segundos desde inicio (del PID file mtime)
    last_quote_ok: bool
    last_quote_price: float | None
    last_quote_age_s: float | None    # segundos desde el último quote en el log
    detector_count: int
    detector_states: list[str]        # ej. ["upper 7147 → WATCHING"]
    active_trade: bool
    overall_ok: bool


def check_health() -> SystemHealth:
    """Comprueba el estado del sistema sin modificar nada."""
```

Para `last_quote_age_s`, parsear la última línea `ES=` del log de monitor.

---

## Componente 5: Comando `start-day`

Flujo determinista para iniciar la jornada desde cualquier estado.

### Algoritmo

```
1. Comprobar si monitor ya corre
   → Si corre y está sano: informar y salir (idempotente)

2. Matar procesos huérfanos (run_mancini monitor sin PID file válido)

3. Limpiar archivos de estado del día anterior
   - outputs/mancini_state.json  (detectores)
   - outputs/mancini_intraday.json
   - outputs/mancini_monitor.pid (si stale)
   - outputs/mancini_stop        (si existe)
   NO tocar mancini_plan.json aquí — puede ya tener el plan de hoy

4. Ejecutar scan para obtener/confirmar plan de hoy
   - Si hay plan con fecha=hoy: skip scan (ya está)
   - Si no hay plan de hoy: fetch tweets y parsear
   - Si scan falla o no hay tweets: advertir, continuar sin plan
     (el monitor lo buscará en su primer ciclo)

5. Lanzar monitor como proceso detached
   → Usar subprocess con stdout/stderr → log file, NO heredar handles del padre
   → Esperar hasta 30s a que el PID file aparezca

6. Verificar que monitor arrancó y obtuvo primera quote
   → Leer PID file
   → Esperar hasta 30s a que aparezca primera línea ES= en el log

7. Notificar a Telegram: "Sistema Mancini iniciado. Plan: ..."

8. Imprimir health summary
```

### API

```python
def start_day(
    skip_scan: bool = False,    # --skip-scan: útil si ya hay plan de hoy
    dry_run: bool = False,      # --dry-run: no lanza el monitor, solo simula
) -> bool:
    """Inicia la jornada. Retorna True si el sistema queda sano."""
```

### Lanzamiento del monitor (sin herencia de handles)

El problema de los 13 procesos era que cada `uv run ... &` o background task
heredaba file handles y se proliferaban. La solución:

```python
import subprocess, sys

def _launch_monitor() -> int:
    """Lanza el monitor como proceso independiente. Retorna PID."""
    cmd = [
        sys.executable,                          # python del venv
        "scripts/mancini/run_mancini.py",
        "monitor",
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=open("logs/mancini_monitor.log", "a"),
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        close_fds=True,                          # no heredar file descriptors
        env={**os.environ, "PYTHONUTF8": "1"},
        cwd=PROJECT_ROOT,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        # ^ Windows: proceso completamente independiente del padre
    )
    return proc.pid
```

`DETACHED_PROCESS` en Windows garantiza que el monitor sobrevive aunque el
proceso padre (Claude Code, terminal, BAT) termine. No se pueden acumular
instancias porque `start-day` comprueba el PID file antes de lanzar.

---

## Componente 6: Comando `stop-day`

Shutdown limpio del monitor y resumen de la jornada.

### Algoritmo

```
1. Comprobar si monitor corre (PID file)
   → Si no corre: informar y salir

2. Crear stop flag (outputs/mancini_stop)

3. Esperar hasta 90s a que el monitor elimine el PID file
   → Polling cada 2s
   → Si timeout: kill forzado y limpiar PID file manualmente

4. Generar resumen de jornada:
   - Trades del día (de mancini_adjustments.jsonl)
   - P&L total estimado
   - Niveles alcanzados

5. Notificar a Telegram: resumen de jornada

6. Imprimir confirmación
```

### API

```python
def stop_day(force: bool = False) -> bool:
    """
    Para el monitor limpiamente.
    force=True: kill inmediato sin esperar stop flag.
    """
```

---

## Componente 7: Comando `recover`

Para cuando el sistema está en estado desconocido. Lleva al sistema a un
estado estable sin pérdida de datos.

### Algoritmo

```
1. Ejecutar health check

2. Para cada problema detectado, aplicar la corrección mínima:

   Problema: procesos huérfanos (monitor sin PID file)
   → Matar procesos huérfanos, limpiar PID file stale

   Problema: PID file stale (proceso no existe)
   → Eliminar PID file

   Problema: plan de ayer (fecha != hoy)
   → Ejecutar scan para obtener plan de hoy

   Problema: monitor no corre
   → Si hay plan: lanzar monitor (via _launch_monitor)
   → Si no hay plan: esperar — el monitor lo buscará al arrancar

   Problema: quote errors (monitor corre pero no obtiene precios)
   → NO actuar: puede ser transitorio. Informar al usuario.

3. Ejecutar health check final

4. Notificar resultado a Telegram

5. Imprimir estado final
```

### API

```python
def recover(dry_run: bool = False) -> SystemHealth:
    """
    Detecta y corrige inconsistencias. Retorna el estado final.
    dry_run=True: describe qué haría sin ejecutar nada.
    """
```

---

## Integración en `run_mancini.py`

### Nuevos subcomandos

```
uv run python scripts/mancini/run_mancini.py health
uv run python scripts/mancini/run_mancini.py start-day [--skip-scan]
uv run python scripts/mancini/run_mancini.py stop-day  [--force]
uv run python scripts/mancini/run_mancini.py recover   [--dry-run]
```

Los subcomandos existentes (`monitor`, `scan`, `status`, `reset`) se mantienen
sin cambios para compatibilidad con los BAT files y Task Scheduler.

### Argparse

```python
# En main():
subparsers = parser.add_subparsers(dest="command")

p_health = subparsers.add_parser("health", help="Estado del sistema")

p_start = subparsers.add_parser("start-day", help="Iniciar jornada")
p_start.add_argument("--skip-scan", action="store_true")

p_stop = subparsers.add_parser("stop-day", help="Parar monitor limpiamente")
p_stop.add_argument("--force", action="store_true")

p_recover = subparsers.add_parser("recover", help="Recuperar estado consistente")
p_recover.add_argument("--dry-run", action="store_true")
```

---

## Actualización de los BAT files

Los BAT files existentes se simplificarán para usar `start-day` en lugar de
lanzar directamente `monitor`:

```bat
REM monitor_start.bat — reemplazado por:
uv run python scripts/mancini/run_mancini.py start-day
```

Los BAT files de scan y weekly-scan no cambian (son tareas periódicas, no
el monitor de larga duración).

---

## Skill `/mancini-monitor` actualizada

El skill existente pasa a ser:

```
### Paso 1: Verificar estado actual
uv run python scripts/mancini/run_mancini.py health

### Paso 2: Si el sistema está sano → no hacer nada
### Si hay problemas → recover

### Paso 3: Si el monitor no corre → start-day
uv run python scripts/mancini/run_mancini.py start-day
```

---

## Tests

### `tests/test_health.py`

```python
# PID file
test_write_and_read_pid()
test_is_monitor_running_with_valid_pid()
test_is_monitor_running_with_stale_pid()     # PID de proceso inexistente → False
test_is_monitor_running_no_file()            # sin archivo → False
test_clear_pid_removes_file()

# Stop flag
test_request_stop_creates_file()
test_stop_requested_true_when_file_exists()
test_stop_requested_false_when_no_file()
test_clear_stop_flag_removes_file()

# Health check
test_check_health_ok()                       # plan hoy + monitor running + quote OK
test_check_health_no_plan()                  # sin plan → plan_ok=False
test_check_health_old_plan()                 # plan de ayer → plan_ok=False
test_check_health_monitor_not_running()      # sin PID file → monitor_running=False
test_check_health_stale_pid()                # PID file con PID inválido → monitor_running=False
test_check_health_overall_ok()               # todos OK → overall_ok=True
test_check_health_overall_degraded()         # algún fallo → overall_ok=False

# start-day (mocked subprocess)
test_start_day_already_running()             # monitor corre → no relanzar
test_start_day_kills_orphans()               # huérfanos → matar antes de lanzar
test_start_day_idempotent()                  # llamar dos veces → igual que una
test_start_day_skip_scan_when_plan_today()   # plan hoy → no re-escanear
test_start_day_waits_for_pid_file()          # espera hasta 30s

# stop-day (mocked stop flag)
test_stop_day_creates_stop_flag()
test_stop_day_waits_for_pid_removal()
test_stop_day_force_kills_if_timeout()
test_stop_day_not_running()                  # monitor no corre → informar, no error

# recover
test_recover_fixes_stale_pid()
test_recover_kills_orphan_processes()
test_recover_runs_scan_for_old_plan()
test_recover_launches_monitor_if_stopped()
test_recover_dry_run_describes_actions()
test_recover_leaves_system_healthy()
```

---

## Notas de implementación

### Windows vs Unix

`os.kill(pid, 0)` funciona en Windows para comprobar si un proceso existe
(no lanza señal real, solo comprueba). Para terminar un proceso en Windows
se usa `os.kill(pid, signal.SIGTERM)` o `subprocess.Popen.terminate()`.

### Detección de huérfanos

```python
def get_stale_pids() -> list[int]:
    """Busca procesos run_mancini monitor que no corresponden al PID file."""
    import psutil
    official_pid = read_pid()
    stale = []
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmd = " ".join(proc.info["cmdline"] or [])
            if "run_mancini" in cmd and "monitor" in cmd:
                if proc.info["pid"] != official_pid:
                    stale.append(proc.info["pid"])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return stale
```

Requiere añadir `psutil` a las dependencias del proyecto.

### Idempotencia de `start-day`

```python
def start_day(skip_scan=False, dry_run=False) -> bool:
    if is_monitor_running():
        health = check_health()
        if health.overall_ok:
            print("Monitor ya está corriendo y sano. Sin cambios.")
            return True
        # Monitor corre pero con problemas → continuar con recovery parcial

    # ... resto del flujo
```

### Timeout en `_wait_for_pid_file`

```python
def _wait_for_pid_file(timeout_s: int = 30) -> bool:
    """Espera hasta que el PID file aparezca. Retorna True si apareció."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if PID_PATH.exists():
            return True
        time.sleep(1)
    return False
```

---

## Dependencias nuevas

```toml
# pyproject.toml
psutil = ">=5.9"
```

---

## Prioridad de implementación

1. `health.py` con PID file + stop flag + `check_health()`
2. Integrar PID file en `monitor.py` (`write_pid` / `clear_pid` / `stop_requested`)
3. `start-day` con `_launch_monitor` vía `subprocess.Popen` detached
4. `stop-day`
5. `recover`
6. Tests
7. Actualizar BAT files y skill `/mancini-monitor`
