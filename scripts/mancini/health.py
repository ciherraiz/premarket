"""
Mancini Health Manager — gestión del ciclo de vida del monitor.

Proporciona:
- PID file como única fuente de verdad sobre si el monitor está activo
- Stop flag para shutdown limpio sin matar procesos abruptamente
- check_health() para diagnóstico rápido sin modificar estado
- start_day() idempotente: scan + launch con subprocess detached
- stop_day() con shutdown limpio vía stop flag
- recover() para llevar el sistema a estado consistente desde cualquier situación
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUTS_DIR  = PROJECT_ROOT / "outputs"
LOGS_DIR     = PROJECT_ROOT / "logs"

PID_PATH       = OUTPUTS_DIR / "mancini_monitor.pid"
STOP_FLAG_PATH = OUTPUTS_DIR / "mancini_stop"
MONITOR_LOG    = LOGS_DIR / "mancini_monitor.log"

ET = ZoneInfo("America/New_York")


# ── PID file ──────────────────────────────────────────────────────────────────

def write_pid(pid: int) -> None:
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    PID_PATH.write_text(str(pid), encoding="utf-8")


def read_pid() -> int | None:
    try:
        return int(PID_PATH.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        return None


def clear_pid() -> None:
    PID_PATH.unlink(missing_ok=True)


def is_monitor_running() -> bool:
    pid = read_pid()
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


# ── Stop flag ─────────────────────────────────────────────────────────────────

def request_stop() -> None:
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    STOP_FLAG_PATH.touch()


def clear_stop_flag() -> None:
    STOP_FLAG_PATH.unlink(missing_ok=True)


def stop_requested() -> bool:
    return STOP_FLAG_PATH.exists()


# ── Detección de procesos huérfanos ───────────────────────────────────────────

def get_orphan_pids() -> list[int]:
    """Busca procesos run_mancini monitor que no coinciden con el PID file."""
    try:
        import psutil
    except ImportError:
        return []

    official_pid = read_pid()
    orphans = []
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmd = " ".join(proc.info["cmdline"] or [])
            if "run_mancini" in cmd and "monitor" in cmd:
                if proc.info["pid"] != official_pid:
                    orphans.append(proc.info["pid"])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return orphans


def kill_orphans() -> list[int]:
    """Mata procesos huérfanos. Retorna lista de PIDs terminados."""
    killed = []
    for pid in get_orphan_pids():
        try:
            os.kill(pid, signal.SIGTERM)
            killed.append(pid)
        except (ProcessLookupError, PermissionError, OSError):
            pass
    if killed:
        time.sleep(2)
    return killed


# ── Health check ─────────────────────────────────────────────────────────────

@dataclass
class SystemHealth:
    plan_ok: bool
    plan_fecha: str | None
    plan_upper: float | None
    plan_targets_upper: list[float]
    plan_lower: float | None
    plan_targets_lower: list[float]
    monitor_running: bool
    monitor_pid: int | None
    monitor_uptime_s: float | None
    last_quote_ok: bool
    last_quote_price: float | None
    last_quote_age_s: float | None
    detector_count: int
    detector_states: list[str]
    active_trade: bool
    orphan_count: int
    overall_ok: bool

    def print_summary(self) -> None:
        ok  = lambda b: "✓" if b else "✗"
        nl  = "\n"

        plan_line = (
            f"{ok(self.plan_ok)} {self.plan_fecha}  "
            f"(upper={self.plan_upper} → {self.plan_targets_upper}"
            + (f" | lower={self.plan_lower} → {self.plan_targets_lower}" if self.plan_lower else "")
            + ")"
            if self.plan_ok
            else f"✗ NO HAY PLAN para hoy (último: {self.plan_fecha or 'ninguno'})"
        )

        if self.monitor_running:
            uptime = ""
            if self.monitor_uptime_s is not None:
                m, s = divmod(int(self.monitor_uptime_s), 60)
                h, m = divmod(m, 60)
                uptime = f", activo hace {h}h {m}m" if h else f", activo hace {m}m {s}s"
            monitor_line = f"✓ CORRIENDO (PID {self.monitor_pid}{uptime})"
        else:
            pid_note = f" (PID file stale: {self.monitor_pid})" if self.monitor_pid else ""
            monitor_line = f"✗ DETENIDO{pid_note}"

        if self.last_quote_ok and self.last_quote_price:
            age = f"hace {int(self.last_quote_age_s or 0)}s"
            quote_line = f"✓ OK  ES={self.last_quote_price}  {age}"
        elif self.last_quote_price:
            quote_line = f"✗ ERROR  (última quote: ES={self.last_quote_price})"
        else:
            quote_line = "✗ SIN DATOS"

        det_line = (
            f"{self.detector_count} activo(s)  ({', '.join(self.detector_states)})"
            if self.detector_count
            else "0 activos"
        )

        trade_line = "trade activo" if self.active_trade else "sin trade activo"

        orphan_line = (
            f"  ⚠️  {self.orphan_count} proceso(s) huérfano(s) — ejecutar recover{nl}"
            if self.orphan_count
            else ""
        )

        overall = "✓ OK" if self.overall_ok else "✗ DEGRADADO — ejecutar: uv run python scripts/mancini/run_mancini.py recover"

        print(
            f"\n=== Mancini System Health ==={nl}"
            f"Plan:       {plan_line}{nl}"
            f"Monitor:    {monitor_line}{nl}"
            f"Quote:      {quote_line}{nl}"
            f"Detectores: {det_line}{nl}"
            f"Trade:      {trade_line}{nl}"
            f"{orphan_line}"
            f"\nEstado general: {overall}\n"
        )


def check_health() -> SystemHealth:
    """Comprueba el estado del sistema sin modificar nada."""
    from scripts.mancini.config import load_plan, load_intraday_state
    from scripts.mancini.detector import load_detectors

    today = datetime.now(ET).strftime("%Y-%m-%d")

    # Plan
    plan = load_plan()
    plan_ok = bool(plan and plan.fecha == today)
    plan_fecha = plan.fecha if plan else None
    plan_upper = plan.key_level_upper if plan else None
    plan_targets_upper = plan.targets_upper if plan else []
    plan_lower = plan.key_level_lower if plan else None
    plan_targets_lower = plan.targets_lower if plan else []

    # Monitor
    monitor_pid = read_pid()
    monitor_running = is_monitor_running()
    monitor_uptime_s: float | None = None
    if monitor_running and PID_PATH.exists():
        monitor_uptime_s = time.time() - PID_PATH.stat().st_mtime

    # Última quote del log
    last_quote_price, last_quote_age_s, last_quote_ok = _parse_last_quote()

    # Detectores
    detectors = load_detectors()
    detector_states = [f"{d.side} {d.level} → {d.state.value}" for d in detectors]

    # Trade activo
    try:
        intraday = load_intraday_state()
        active_trade = False  # IntraDayState no tiene trades; se infiere de logs
    except Exception:
        active_trade = False

    # Huérfanos
    orphan_count = len(get_orphan_pids())

    overall_ok = (
        plan_ok
        and monitor_running
        and last_quote_ok
        and orphan_count == 0
    )

    return SystemHealth(
        plan_ok=plan_ok,
        plan_fecha=plan_fecha,
        plan_upper=plan_upper,
        plan_targets_upper=plan_targets_upper,
        plan_lower=plan_lower,
        plan_targets_lower=plan_targets_lower,
        monitor_running=monitor_running,
        monitor_pid=monitor_pid,
        monitor_uptime_s=monitor_uptime_s,
        last_quote_ok=last_quote_ok,
        last_quote_price=last_quote_price,
        last_quote_age_s=last_quote_age_s,
        detector_count=len(detectors),
        detector_states=detector_states,
        active_trade=active_trade,
        orphan_count=orphan_count,
        overall_ok=overall_ok,
    )


def _parse_last_quote() -> tuple[float | None, float | None, bool]:
    """
    Parsea el log del monitor para obtener el último precio ES.

    Retorna: (price, age_seconds, is_ok)
    - is_ok=True si el último evento fue ES=X (no un ERROR)
    """
    if not MONITOR_LOG.exists():
        return None, None, False

    last_price: float | None = None
    last_price_ts: float | None = None
    last_was_error = False

    try:
        with MONITOR_LOG.open("r", encoding="utf-8", errors="replace") as f:
            # Leer solo las últimas 200 líneas para no cargar el fichero entero
            lines = f.readlines()[-200:]

        for line in reversed(lines):
            line = line.strip()
            if "ES=" in line and "Quote status" not in line:
                # Formato: [mancini HH:MM:SS ET] ES=XXXX.XX
                try:
                    price_str = line.split("ES=")[1].split()[0]
                    last_price = float(price_str)
                    last_was_error = False
                except (IndexError, ValueError):
                    pass
                # Intentar parsear el timestamp del log
                last_price_ts = MONITOR_LOG.stat().st_mtime
                break
            elif "Quote status: ERROR" in line and last_price is None:
                last_was_error = True

        if last_price is not None and last_price_ts is not None:
            age = time.time() - last_price_ts
            return last_price, age, not last_was_error

    except OSError:
        pass

    return None, None, False


# ── Lanzamiento del monitor ───────────────────────────────────────────────────

def _launch_monitor() -> int:
    """
    Lanza el monitor como proceso completamente independiente del padre.

    Usa DETACHED_PROCESS en Windows para que el monitor sobreviva aunque
    el proceso padre (Claude Code, terminal, BAT) termine. El PID file
    garantiza que no se acumulan instancias.
    """
    python = sys.executable
    script = str(PROJECT_ROOT / "scripts" / "mancini" / "run_mancini.py")

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOGS_DIR / "mancini_monitor.log"

    env = {**os.environ, "PYTHONUTF8": "1"}

    kwargs: dict = {
        "stdout": open(log_file, "a", encoding="utf-8"),
        "stderr": subprocess.STDOUT,
        "stdin":  subprocess.DEVNULL,
        "env":    env,
        "cwd":    str(PROJECT_ROOT),
    }

    if sys.platform == "win32":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        kwargs["start_new_session"] = True  # Unix: detach del grupo de sesión

    proc = subprocess.Popen([python, script, "monitor"], **kwargs)
    return proc.pid


def _wait_for_pid_file(timeout_s: int = 30) -> bool:
    """Espera hasta que el PID file aparezca. Retorna True si apareció."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if PID_PATH.exists() and is_monitor_running():
            return True
        time.sleep(1)
    return False


def _wait_for_first_quote(timeout_s: int = 45) -> bool:
    """Espera hasta que el monitor loguee al menos un ES=. Retorna True si ocurrió."""
    if not MONITOR_LOG.exists():
        return False
    initial_size = MONITOR_LOG.stat().st_size
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with MONITOR_LOG.open("r", encoding="utf-8", errors="replace") as f:
                f.seek(initial_size)
                new_content = f.read()
            if "ES=" in new_content and "Quote status" not in new_content.split("ES=")[-1][:20]:
                return True
        except OSError:
            pass
        time.sleep(2)
    return False


# ── start_day ─────────────────────────────────────────────────────────────────

def start_day(skip_scan: bool = False, dry_run: bool = False) -> bool:
    """
    Inicia la jornada Mancini de forma determinista e idempotente.

    Flujo:
    1. Si el monitor ya corre y está sano → no hacer nada
    2. Matar procesos huérfanos
    3. Limpiar estado del día anterior
    4. Scan de tweets para obtener plan de hoy
    5. Lanzar monitor como proceso detached
    6. Verificar arranque (PID file + primera quote)
    7. Notificar a Telegram
    """
    from scripts.mancini.config import load_plan, save_plan
    from scripts.mancini import notifier

    today = datetime.now(ET).strftime("%Y-%m-%d")

    print("=== Mancini start-day ===\n")

    # 1. Idempotencia
    if is_monitor_running():
        health = check_health()
        if health.overall_ok:
            print("Monitor ya está corriendo y sano. Sin cambios.")
            health.print_summary()
            return True
        print("Monitor corre pero con problemas — continuando con recovery...")

    # 2. Matar huérfanos
    orphans = kill_orphans()
    if orphans:
        print(f"  Procesos huérfanos eliminados: {orphans}")

    # 3. Limpiar estado del día anterior
    print("  Limpiando estado anterior...")
    if not dry_run:
        for path in [
            OUTPUTS_DIR / "mancini_state.json",
            OUTPUTS_DIR / "mancini_intraday.json",
        ]:
            path.unlink(missing_ok=True)
        clear_pid()
        clear_stop_flag()

    # 4. Scan de tweets
    plan = load_plan()
    if plan and plan.fecha == today:
        print(f"  Plan de hoy ya existe (upper={plan.key_level_upper}). Scan omitido.")
    elif not skip_scan:
        print("  Ejecutando scan de tweets...")
        if not dry_run:
            ok = _run_scan()
            if ok:
                plan = load_plan()
                print(f"  Plan obtenido: upper={plan.key_level_upper if plan else '?'}")
            else:
                print("  ⚠️  Scan sin plan nuevo — el monitor lo buscará al arrancar")
    else:
        print("  Scan omitido (--skip-scan)")

    # 5. Lanzar monitor
    print("  Lanzando monitor...")
    if not dry_run:
        pid = _launch_monitor()
        print(f"  Monitor iniciado (PID inicial: {pid})")

        # 6. Verificar arranque
        print("  Esperando PID file...", end=" ", flush=True)
        if _wait_for_pid_file(timeout_s=30):
            real_pid = read_pid()
            print(f"OK (PID {real_pid})")
        else:
            print("TIMEOUT — el monitor puede no haber arrancado")
            return False

        print("  Esperando primera quote...", end=" ", flush=True)
        if _wait_for_first_quote(timeout_s=45):
            print("OK")
        else:
            print("TIMEOUT — verificar logs/mancini_monitor.log")

        # 7. Notificar Telegram
        try:
            plan = load_plan()
            if plan and plan.fecha == today:
                notifier.notify_plan_loaded(plan.to_dict())
        except Exception:
            pass
    else:
        print("  [DRY RUN] No se lanza el monitor")

    # Resumen final
    if not dry_run:
        health = check_health()
        health.print_summary()
        return health.monitor_running
    return True


def _run_scan() -> bool:
    """Ejecuta el scan de tweets en proceso hijo. Retorna True si hay plan nuevo."""
    python = sys.executable
    script = str(PROJECT_ROOT / "scripts" / "mancini" / "run_mancini.py")
    result = subprocess.run(
        [python, script, "scan"],
        cwd=str(PROJECT_ROOT),
        env={**os.environ, "PYTHONUTF8": "1"},
        timeout=120,
    )
    return result.returncode == 0


# ── stop_day ──────────────────────────────────────────────────────────────────

def stop_day(force: bool = False) -> bool:
    """
    Para el monitor limpiamente vía stop flag.

    force=True: kill inmediato sin esperar al stop flag.
    """
    print("=== Mancini stop-day ===\n")

    if not is_monitor_running():
        print("El monitor no está corriendo.")
        return True

    pid = read_pid()

    if force:
        print(f"  Forzando parada (PID {pid})...")
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass
        time.sleep(2)
        clear_pid()
        clear_stop_flag()
        print("  Parado.")
        return True

    # Stop limpio vía flag
    print(f"  Solicitando parada al monitor (PID {pid})...")
    request_stop()

    # Esperar hasta 90s a que el monitor elimine el PID file
    print("  Esperando shutdown limpio...", end=" ", flush=True)
    deadline = time.time() + 90
    while time.time() < deadline:
        if not is_monitor_running():
            print("OK")
            break
        time.sleep(2)
    else:
        print("TIMEOUT — forzando kill")
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass
        time.sleep(2)
        clear_pid()
        clear_stop_flag()

    print("  Monitor detenido.")
    return True


# ── recover ───────────────────────────────────────────────────────────────────

def recover(dry_run: bool = False) -> SystemHealth:
    """
    Detecta y corrige inconsistencias con la corrección mínima necesaria.

    dry_run=True: describe qué haría sin ejecutar nada.
    """
    prefix = "[DRY RUN] " if dry_run else ""
    print("=== Mancini recover ===\n")

    # 1. Health check inicial
    health = check_health()
    health.print_summary()

    if health.overall_ok:
        print("Sistema sano — sin acciones necesarias.")
        return health

    actions_taken = []

    # 2. Procesos huérfanos
    if health.orphan_count > 0:
        print(f"  {prefix}Eliminando {health.orphan_count} proceso(s) huérfano(s)...")
        if not dry_run:
            killed = kill_orphans()
            actions_taken.append(f"Eliminados PIDs huérfanos: {killed}")

    # 3. PID file stale
    if health.monitor_pid and not health.monitor_running:
        print(f"  {prefix}Limpiando PID file stale (PID {health.monitor_pid})...")
        if not dry_run:
            clear_pid()
            actions_taken.append("PID file stale eliminado")

    # 4. Plan desactualizado
    if not health.plan_ok:
        today = datetime.now(ET).strftime("%Y-%m-%d")
        print(f"  {prefix}Plan no es de hoy ({health.plan_fecha}) — ejecutando scan...")
        if not dry_run:
            ok = _run_scan()
            actions_taken.append(f"Scan ejecutado: {'plan nuevo' if ok else 'sin cambios'}")

    # 5. Monitor no corre
    if not health.monitor_running:
        print(f"  {prefix}Monitor detenido — lanzando...")
        if not dry_run:
            clear_stop_flag()
            pid = _launch_monitor()
            if _wait_for_pid_file(timeout_s=30):
                actions_taken.append(f"Monitor relanzado (PID {read_pid()})")
            else:
                actions_taken.append("Monitor lanzado pero sin confirmación de PID")

    # 6. Quote errors: no actuar, solo informar
    if health.monitor_running and not health.last_quote_ok:
        print("  ⚠️  Monitor corre pero con errores de quote — puede ser transitorio.")
        print("      Verificar en 2 minutos o revisar logs/mancini_monitor.log")

    # Resumen
    if actions_taken:
        print(f"\n  Acciones realizadas:")
        for a in actions_taken:
            print(f"    • {a}")

    # Health check final
    if not dry_run:
        print()
        final = check_health()
        final.print_summary()
        return final

    return health
