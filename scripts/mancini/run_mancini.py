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

from scripts.mancini.config import load_plan, save_plan, save_weekly, PLAN_PATH
from scripts.mancini.detector import load_detectors, STATE_PATH, save_detectors
from scripts.mancini.monitor import ManciniMonitor

ET = ZoneInfo("America/New_York")


def cmd_scan(args) -> None:
    """Obtiene tweets de Mancini y extrae/actualiza el plan diario."""
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

    print(f"Encontrados {len(tweets)} tweets de hoy")
    for i, t in enumerate(tweets, 1):
        print(f"  {i}. {t['text'][:100]}...")

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

    # Guardar (sobreescribe si ya existe)
    save_weekly(plan)
    notifier.notify_weekly_plan(plan.to_dict())
    print(f"Plan semanal guardado para semana del {week_start}")
    print(json.dumps(plan.to_dict(), indent=2))


def cmd_monitor(args) -> None:
    """Arranca el monitor de precio /ES."""
    from scripts.tastytrade_client import TastyTradeClient

    client = TastyTradeClient()
    kwargs = {"client": client, "poll_interval": args.interval}
    if args.start is not None:
        kwargs["session_start"] = args.start
    if args.end is not None:
        kwargs["session_end"] = args.end
    monitor = ManciniMonitor(**kwargs)
    monitor.run()


def cmd_status(args) -> None:
    """Muestra el estado actual del sistema."""
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


def cmd_reset(args) -> None:
    """Resetea estado para un nuevo día."""
    if STATE_PATH.exists():
        STATE_PATH.unlink()
        print(f"✓ Eliminado {STATE_PATH}")
    else:
        print(f"  {STATE_PATH} no existía")

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

    # status
    sub.add_parser("status", help="Muestra estado actual")

    # reset
    p_reset = sub.add_parser("reset", help="Resetea estado para nuevo día")
    p_reset.add_argument("--keep-plan", action="store_true",
                         help="Conservar el plan actual")

    args = parser.parse_args()

    if args.command == "scan":
        cmd_scan(args)
    elif args.command == "weekly-scan":
        cmd_weekly_scan(args)
    elif args.command == "monitor":
        cmd_monitor(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "reset":
        cmd_reset(args)


if __name__ == "__main__":
    main()
