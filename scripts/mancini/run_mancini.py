#!/usr/bin/env python3
"""
Punto de entrada CLI para el Mancini Replicant.

Subcomandos:
  monitor  — arranca el loop de polling /ES (proceso larga duración)
  status   — muestra estado actual (plan + detectores + trades)
  reset    — resetea estado para un nuevo día

Uso:
  uv run python scripts/mancini/run_mancini.py monitor [--interval 60]
  uv run python scripts/mancini/run_mancini.py status
  uv run python scripts/mancini/run_mancini.py reset
"""

import argparse
import json
import sys
from pathlib import Path

# Asegurar que el proyecto raíz está en sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.mancini.config import load_plan, PLAN_PATH
from scripts.mancini.detector import load_detectors, STATE_PATH, save_detectors
from scripts.mancini.monitor import ManciniMonitor


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

    # monitor
    p_monitor = sub.add_parser("monitor", help="Arranca polling /ES")
    p_monitor.add_argument("--interval", type=int, default=60,
                           help="Intervalo de polling en segundos (default: 60)")
    p_monitor.add_argument("--start", type=int, default=None,
                           help="Hora inicio sesión ET (default: 7)")
    p_monitor.add_argument("--end", type=int, default=None,
                           help="Hora fin sesión ET (default: 11)")

    # status
    sub.add_parser("status", help="Muestra estado actual")

    # reset
    p_reset = sub.add_parser("reset", help="Resetea estado para nuevo día")
    p_reset.add_argument("--keep-plan", action="store_true",
                         help="Conservar el plan actual")

    args = parser.parse_args()

    if args.command == "monitor":
        cmd_monitor(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "reset":
        cmd_reset(args)


if __name__ == "__main__":
    main()
