#!/usr/bin/env python3
"""
Punto de entrada CLI para el Mancini Replicant.

Subcomandos:
  scan         — obtiene tweets de Mancini y extrae plan diario
  weekly-scan  — obtiene Big Picture View del fin de semana
  monitor      — arranca el loop de polling /ES (proceso larga duración)
  status       — muestra estado actual (plan + detectores + trades)
  reset        — resetea estado para un nuevo día

Uso:
  uv run python scripts/mancini/run_mancini.py scan
  uv run python scripts/mancini/run_mancini.py weekly-scan
  uv run python scripts/mancini/run_mancini.py monitor [--interval 60]
  uv run python scripts/mancini/run_mancini.py status
  uv run python scripts/mancini/run_mancini.py reset
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# Asegurar que el proyecto raíz está en sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# ── Logging dual: stdout + fichero ────────────────────────────────

LOG_DIR = Path("logs")

class _Tee:
    """Escribe a stdout (visible en ventana cmd) y a un fichero de log."""

    def __init__(self, log_path: Path):
        self._stdout = sys.__stdout__
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self._file = log_path.open("a", encoding="utf-8")

    def write(self, data: str) -> int:
        self._stdout.write(data)
        self._file.write(data)
        return len(data)

    def flush(self) -> None:
        self._stdout.flush()
        self._file.flush()

    def close(self) -> None:
        self._file.close()


def _setup_dual_output(log_path: Path) -> None:
    """Redirige stdout y stderr a consola + fichero."""
    tee = _Tee(log_path)
    sys.stdout = tee  # type: ignore[assignment]
    sys.stderr = _Tee(log_path)  # type: ignore[assignment]

from scripts.mancini.config import (
    load_plan, save_plan, save_weekly, load_weekly, load_intraday_state,
    PLAN_PATH, INTRADAY_STATE_PATH,
)
from scripts.mancini.detector import load_detectors, STATE_PATH, save_detectors
from scripts.mancini.monitor import ManciniMonitor

ET = ZoneInfo("America/New_York")


def cmd_scan(args) -> None:
    """Obtiene tweets de Mancini y extrae/actualiza el plan diario."""
    _setup_dual_output(LOG_DIR / "mancini_scan.log")

    from scripts.mancini.tweet_fetcher import fetch_tweets_sync
    from scripts.mancini.tweet_parser import parse_tweets_to_plan
    from scripts.mancini.logger import append_scan_result
    from scripts.mancini import notifier

    today = datetime.now(ET).strftime("%Y-%m-%d")

    # Fetch tweets
    try:
        tweets = fetch_tweets_sync()
    except Exception as e:
        print(f"Error fetching tweets: {e}")
        append_scan_result("error", 0, False, str(e), today)
        sys.exit(1)

    if not tweets:
        print(f"No se encontraron tweets de Mancini para {today}")
        append_scan_result("no_tweets", 0, False, "No tweets found", today)
        sys.exit(0)

    # Excluir tweets que el clasificador intraday ya procesó
    # (evita que el scan re-extraiga targets que el clasificador decidió no aplicar)
    intraday_state = load_intraday_state()
    if intraday_state.processed_tweet_ids:
        before = len(tweets)
        tweets = [t for t in tweets if t["id"] not in intraday_state.processed_tweet_ids]
        skipped = before - len(tweets)
        if skipped:
            print(f"Excluidos {skipped} tweets ya procesados por clasificador intraday")

    print(f"Encontrados {len(tweets)} tweets de hoy")
    for i, t in enumerate(tweets, 1):
        print(f"  {i}. {t['text'][:100]}...")

    if not tweets:
        print("Todos los tweets ya fueron procesados por el clasificador intraday")
        append_scan_result("no_new_tweets", 0, False, "All processed by classifier", today)
        sys.exit(0)

    # Parsear con Haiku
    try:
        plan = parse_tweets_to_plan(tweets, today)
    except Exception as e:
        print(f"Error parsing tweets: {e}")
        append_scan_result("parse_error", len(tweets), False, str(e), today)
        sys.exit(1)

    if plan is None:
        print("Haiku determinó que no hay plan nuevo hoy")
        append_scan_result("no_plan", len(tweets), False, "Haiku: no plan", today)
        sys.exit(0)

    # Merge si ya existe plan de hoy
    existing = load_plan()
    is_update = False
    if existing and existing.fecha == today:
        old_targets = set(existing.targets_upper + existing.targets_lower)
        for tweet in plan.raw_tweets:
            existing.merge_update(
                new_targets_upper=plan.targets_upper,
                new_targets_lower=plan.targets_lower,
                new_tweet=tweet,
            )
        if plan.chop_zone and not existing.chop_zone:
            existing.chop_zone = plan.chop_zone
        save_plan(existing)
        new_targets = set(existing.targets_upper + existing.targets_lower)
        is_update = new_targets != old_targets
        plan = existing
        print("Plan actualizado (merge con existente)")
    else:
        save_plan(plan)
        is_update = True
        print("Plan nuevo guardado")

    # Notificar a Telegram si hay cambios
    if is_update:
        notifier.notify_plan_loaded(plan.to_dict())
        print("Notificación Telegram enviada")

    append_scan_result("success", len(tweets), is_update, "", today)
    print(json.dumps(plan.to_dict(), indent=2))


def cmd_weekly_scan(args) -> None:
    """Obtiene Big Picture View del fin de semana."""
    _setup_dual_output(LOG_DIR / "mancini_weekly.log")

    from scripts.mancini.tweet_fetcher import fetch_mancini_weekend_tweets
    from scripts.mancini.tweet_parser import parse_weekly_tweets
    from scripts.mancini import notifier

    now = datetime.now(ET)

    # Calcular lunes de la próxima semana (o esta si ya es lun-vie)
    weekday = now.weekday()
    if weekday < 5:  # lun-vie: lunes de esta semana
        monday = now - timedelta(days=weekday)
    else:  # sab-dom: lunes siguiente
        monday = now + timedelta(days=(7 - weekday))
    week_start = monday.strftime("%Y-%m-%d")

    # Si ya existe plan para esta semana, no buscar más
    existing = load_weekly()
    if existing and existing.fecha == week_start:
        print(f"Plan semanal ya existe para {week_start} — nada que hacer")
        sys.exit(0)

    # Fetch tweets Big Picture del fin de semana
    try:
        tweets = fetch_mancini_weekend_tweets()
    except Exception as e:
        print(f"Error fetching weekend tweets: {e}")
        sys.exit(1)

    if not tweets:
        print("No se encontró Big Picture View este fin de semana")
        sys.exit(0)

    print(f"Encontrados {len(tweets)} tweets Big Picture")
    for i, t in enumerate(tweets, 1):
        print(f"  {i}. {t['text'][:120]}...")

    # Parsear con Haiku
    try:
        plan = parse_weekly_tweets(tweets, week_start)
    except Exception as e:
        print(f"Error parsing weekly tweets: {e}")
        sys.exit(1)

    if plan is None:
        print("Haiku determinó que no hay plan semanal claro")
        sys.exit(0)

    # Guardar y notificar (primera y única vez)
    save_weekly(plan)
    notifier.notify_weekly_plan(plan.to_dict())
    print(f"Plan semanal guardado para semana del {week_start}")
    print(json.dumps(plan.to_dict(), indent=2))


def cmd_monitor(args) -> None:
    """Arranca el monitor de precio /ES."""
    import os
    _setup_dual_output(LOG_DIR / "mancini_monitor.log")

    from scripts.tastytrade_client import TastyTradeClient

    client = TastyTradeClient()
    kwargs = {"client": client, "poll_interval": args.interval}
    if args.start is not None:
        kwargs["session_start"] = args.start
    if args.end is not None:
        kwargs["session_end"] = args.end

    # Execution Gate
    kwargs["gate_enabled"] = not args.no_gate

    # OrderExecutor (TastyTrade)
    if not args.no_orders:
        dry_run_env = os.getenv("MANCINI_DRY_RUN", "true").lower()
        dry_run = dry_run_env in ("true", "1", "yes")
        if args.live:
            dry_run = False
        contracts = int(os.getenv("MANCINI_CONTRACTS", "1"))

        try:
            from tastytrade import Account
            from scripts.mancini.order_executor import OrderExecutor

            accounts = Account.get_accounts(client.session)
            if accounts:
                account = accounts[0]
                executor = OrderExecutor(
                    session=client.session,
                    account=account,
                    dry_run=dry_run,
                    contracts=contracts,
                )
                kwargs["order_executor"] = executor

                # Resolver símbolo /ES front-month
                es_symbol = client.get_front_month_symbol("ES")
                if es_symbol:
                    kwargs["es_symbol"] = es_symbol
                    print(f"OrderExecutor: {'DRY-RUN' if dry_run else 'LIVE'} | {contracts} contrato(s) | {es_symbol}")
                else:
                    print("⚠️ No se pudo resolver /ES front-month, sin órdenes")
                    kwargs.pop("order_executor", None)
            else:
                print("⚠️ No se encontraron cuentas TastyTrade, sin órdenes")
        except Exception as e:
            print(f"⚠️ Error inicializando OrderExecutor: {e}, sin órdenes")

    monitor = ManciniMonitor(**kwargs)
    monitor.run()


def cmd_status(args) -> None:
    """Muestra el estado actual del sistema."""
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # Plan
    plan = load_plan()
    if plan:
        print(f"📋 Plan: {plan.fecha}")
        print(f"   Upper: {plan.key_level_upper} → targets {plan.targets_upper}")
        print(f"   Lower: {plan.key_level_lower} → targets {plan.targets_lower}")
        if plan.chop_zone:
            print(f"   Chop: {plan.chop_zone[0]}-{plan.chop_zone[1]}")
        print(f"   Tweets: {len(plan.raw_tweets)}")
        print(f"   Actualizado: {plan.updated_at}")
    else:
        print("❌ No hay plan cargado")

    print()

    # Detectores
    detectors = load_detectors()
    if detectors:
        print("🔍 Detectores:")
        for d in detectors:
            extra = ""
            if d.breakdown_low is not None:
                extra = f" (low={d.breakdown_low})"
            print(f"   {d.side}: {d.level} → {d.state.value}{extra}")
    else:
        print("🔍 No hay detectores activos")

    print()

    # State file info
    if STATE_PATH.exists():
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        print(f"📁 State: {STATE_PATH} ({len(data.get('detectors', []))} detectores)")
    else:
        print(f"📁 State: no existe ({STATE_PATH})")


def cmd_intraday_status(args) -> None:
    """Muestra el estado del clasificador intraday."""
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    state = load_intraday_state()

    print(f"📡 Intraday Classifier Status")
    print(f"   Tweets procesados: {len(state.processed_tweet_ids)}")
    print(f"   Último check: {state.last_check or 'nunca'}")
    print()

    if not state.adjustments:
        print("   Sin ajustes hoy")
        return

    # Contar por tipo
    by_type: dict[str, int] = {}
    for adj in state.adjustments:
        by_type[adj.adjustment_type] = by_type.get(adj.adjustment_type, 0) + 1

    print(f"   Ajustes por tipo:")
    for atype, count in sorted(by_type.items()):
        print(f"     {atype}: {count}")
    print()

    # Mostrar ajustes actionables (no NO_ACTION)
    actionable = [a for a in state.adjustments if a.adjustment_type != "NO_ACTION"]
    if actionable:
        print(f"   Ajustes aplicados ({len(actionable)}):")
        for adj in actionable:
            tweet_preview = adj.tweet_text[:80] + ("..." if len(adj.tweet_text) > 80 else "")
            print(f"     [{adj.adjustment_type}] \"{tweet_preview}\"")
            print(f"       → {adj.raw_reasoning}")
            print()


def cmd_reset(args) -> None:
    """Resetea estado para un nuevo día."""
    if STATE_PATH.exists():
        STATE_PATH.unlink()
        print(f"✓ Eliminado {STATE_PATH}")
    else:
        print(f"  {STATE_PATH} no existía")

    if INTRADAY_STATE_PATH.exists():
        INTRADAY_STATE_PATH.unlink()
        print(f"✓ Eliminado {INTRADAY_STATE_PATH}")
    else:
        print(f"  {INTRADAY_STATE_PATH} no existía")

    if not args.keep_plan and PLAN_PATH.exists():
        PLAN_PATH.unlink()
        print(f"✓ Eliminado {PLAN_PATH}")
    elif args.keep_plan:
        print(f"  Plan conservado ({PLAN_PATH})")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mancini Replicant — Failed Breakdown/Breakout /ES"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # scan
    sub.add_parser("scan", help="Fetch tweets y extrae plan diario")

    # weekly-scan
    sub.add_parser("weekly-scan", help="Fetch Big Picture View semanal")

    # monitor
    p_monitor = sub.add_parser("monitor", help="Arranca polling /ES")
    p_monitor.add_argument("--interval", type=int, default=60,
                           help="Intervalo de polling en segundos (default: 60)")
    p_monitor.add_argument("--start", type=int, default=None,
                           help="Hora inicio sesión ET (default: 7)")
    p_monitor.add_argument("--end", type=int, default=None,
                           help="Hora fin sesión ET (default: 16)")
    p_monitor.add_argument("--no-gate", action="store_true",
                           help="Desactivar Execution Gate LLM")
    p_monitor.add_argument("--no-orders", action="store_true",
                           help="No lanzar órdenes en TastyTrade")
    p_monitor.add_argument("--live", action="store_true",
                           help="Modo live (sobrescribe MANCINI_DRY_RUN)")

    # status
    sub.add_parser("status", help="Muestra estado actual")

    # intraday-status
    sub.add_parser("intraday-status", help="Muestra estado del clasificador intraday")

    # reset
    p_reset = sub.add_parser("reset", help="Resetea estado para nuevo día")
    p_reset.add_argument("--keep-plan", action="store_true",
                         help="Conservar el plan actual")

    # health
    sub.add_parser("health", help="Muestra estado de salud del sistema")

    # start-day
    p_start = sub.add_parser("start-day", help="Inicia la jornada (scan + monitor)")
    p_start.add_argument("--skip-scan", action="store_true",
                         help="No ejecutar scan si ya hay plan de hoy")
    p_start.add_argument("--dry-run", action="store_true",
                         help="Simular sin lanzar monitor ni modificar estado")

    # stop-day
    p_stop = sub.add_parser("stop-day", help="Para el monitor limpiamente")
    p_stop.add_argument("--force", action="store_true",
                        help="Kill inmediato sin esperar stop flag")

    # recover
    p_recover = sub.add_parser("recover", help="Detecta y corrige inconsistencias")
    p_recover.add_argument("--dry-run", action="store_true",
                           help="Describir acciones sin ejecutarlas")

    args = parser.parse_args()

    if args.command == "scan":
        cmd_scan(args)
    elif args.command == "weekly-scan":
        cmd_weekly_scan(args)
    elif args.command == "monitor":
        cmd_monitor(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "intraday-status":
        cmd_intraday_status(args)
    elif args.command == "reset":
        cmd_reset(args)
    elif args.command == "health":
        from scripts.mancini.health import check_health
        check_health().print_summary()
    elif args.command == "start-day":
        from scripts.mancini.health import start_day
        ok = start_day(skip_scan=args.skip_scan, dry_run=args.dry_run)
        sys.exit(0 if ok else 1)
    elif args.command == "stop-day":
        from scripts.mancini.health import stop_day
        stop_day(force=args.force)
    elif args.command == "recover":
        from scripts.mancini.health import recover
        recover(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
