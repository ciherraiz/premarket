"""
Registro JSONL de trades Mancini — append-only en logs/mancini_trades.jsonl.

Sigue el mismo patrón que scripts/log_history.py.
"""

import json
from pathlib import Path

from scripts.mancini.trade_manager import Trade

TRADES_LOG_PATH = Path("logs/mancini_trades.jsonl")


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
