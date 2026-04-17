"""
Registro JSONL de trades Mancini — append-only en logs/mancini_trades.jsonl.

Sigue el mismo patrón que scripts/log_history.py.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.mancini.trade_manager import Trade

TRADES_LOG_PATH = Path("logs/mancini_trades.jsonl")
SCAN_LOG_PATH = Path("logs/mancini_scans.jsonl")
ADJUSTMENTS_LOG_PATH = Path("logs/mancini_adjustments.jsonl")
GATE_LOG_PATH = Path("logs/mancini_gate.jsonl")


def append_scan_result(
    status: str,
    tweets_found: int = 0,
    plan_updated: bool = False,
    reason: str = "",
    fecha: str = "",
    path: Path = SCAN_LOG_PATH,
) -> None:
    """Registra el resultado de una ejecución del scan."""
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "tweets_found": tweets_found,
        "plan_updated": plan_updated,
        "reason": reason,
        "fecha": fecha,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def append_adjustment(adj, path: Path = ADJUSTMENTS_LOG_PATH) -> None:
    """Registra un ajuste intraday en el fichero JSONL."""
    from scripts.mancini.config import PlanAdjustment

    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "tweet_id": adj.tweet_id,
        "tweet_text": adj.tweet_text,
        "timestamp": adj.timestamp,
        "adjustment_type": adj.adjustment_type,
        "details": adj.details,
        "reasoning": adj.raw_reasoning,
        "applied_at": datetime.now(timezone.utc).isoformat(),
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def append_gate_decision(decision, level: float, price: float,
                         path: Path = GATE_LOG_PATH) -> None:
    """Registra una decisión del Execution Gate en el fichero JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "price": price,
        "execute": decision.execute,
        "reasoning": decision.reasoning,
        "risk_factors": decision.risk_factors,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def append_trade(trade: Trade, path: Path = TRADES_LOG_PATH) -> None:
    """Añade un trade cerrado al fichero JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(trade.to_dict(), ensure_ascii=False) + "\n")


def read_trades(path: Path = TRADES_LOG_PATH) -> list[dict]:
    """Lee todos los trades del fichero JSONL."""
    if not path.exists():
        return []
    trades = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            trades.append(json.loads(line))
    return trades


def trades_for_date(fecha: str, path: Path = TRADES_LOG_PATH) -> list[dict]:
    """Filtra trades por fecha (campo 'entry_time' empieza con fecha)."""
    return [t for t in read_trades(path)
            if t.get("entry_time", "").startswith(fecha)]
