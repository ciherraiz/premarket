"""
Registro JSONL de trades Mancini — append-only.

Cada trade genera tres registros en mancini_trades.jsonl:
  "open"       — al abrir, con contexto completo de la señal
  "target_hit" — cada vez que se toca un target
  "close"      — al cerrar, con resultado y métricas

Las órdenes TastyTrade se registran en mancini_orders.jsonl.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.mancini.trade_manager import Trade

TRADES_LOG_PATH = Path("logs/mancini_trades.jsonl")
SCAN_LOG_PATH = Path("logs/mancini_scans.jsonl")
ADJUSTMENTS_LOG_PATH = Path("logs/mancini_adjustments.jsonl")
GATE_LOG_PATH = Path("logs/mancini_gate.jsonl")
ORDERS_LOG_PATH = Path("logs/mancini_orders.jsonl")

_ET = ZoneInfo("America/New_York")


def _to_et(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_ET)


def _append(entry: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ── Scan / adjustments / gate ─────────────────────────────────────────────────

def append_scan_result(
    status: str,
    tweets_found: int = 0,
    plan_updated: bool = False,
    reason: str = "",
    fecha: str = "",
    path: Path = SCAN_LOG_PATH,
) -> None:
    _append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "tweets_found": tweets_found,
        "plan_updated": plan_updated,
        "reason": reason,
        "fecha": fecha,
    }, path)


def append_adjustment(adj, path: Path = ADJUSTMENTS_LOG_PATH) -> None:
    from scripts.mancini.config import PlanAdjustment  # noqa: F401
    _append({
        "tweet_id": adj.tweet_id,
        "tweet_text": adj.tweet_text,
        "timestamp": adj.timestamp,
        "adjustment_type": adj.adjustment_type,
        "details": adj.details,
        "reasoning": adj.raw_reasoning,
        "applied_at": datetime.now(timezone.utc).isoformat(),
    }, path)


def append_gate_decision(decision, level: float, price: float,
                         path: Path = GATE_LOG_PATH) -> None:
    _append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "price": price,
        "execute": decision.execute,
        "reasoning": decision.reasoning,
        "risk_factors": decision.risk_factors,
    }, path)


# ── Órdenes TastyTrade ────────────────────────────────────────────────────────

def append_order_result(
    trade_id: str,
    order_type: str,
    result,
    symbol: str = "",
    path: Path = ORDERS_LOG_PATH,
) -> None:
    """Registra el resultado de una llamada al OrderExecutor."""
    _append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "trade_id": trade_id,
        "order_type": order_type,
        "symbol": symbol,
        "success": result.success,
        "order_id": result.order_id,
        "dry_run": result.dry_run,
        "details": result.details,
        "error": result.error,
    }, path)


# ── Ciclo de vida del trade ───────────────────────────────────────────────────

def append_trade_open(
    trade: Trade,
    level: float,
    minutes_from_open: int,
    path: Path = TRADES_LOG_PATH,
) -> None:
    """Registra apertura del trade con contexto completo de la señal."""
    try:
        entry_dt = datetime.fromisoformat(trade.entry_time)
        entry_et = _to_et(entry_dt)
        fecha = entry_et.strftime("%Y-%m-%d")
        entry_time_et = entry_et.strftime("%H:%M")
        day_of_week = entry_et.weekday()
    except Exception:
        fecha = trade.entry_time[:10]
        entry_time_et = ""
        day_of_week = -1

    risk_pts = abs(trade.entry_price - trade.stop_price)
    depth_pts = round(abs(trade.entry_price - (trade.breakdown_low or trade.entry_price)), 2)
    gate = trade.gate_decision or {}

    _append({
        "record_type": "open",
        "trade_id": trade.id,
        "fecha": fecha,
        "level": level,
        "breakdown_low": trade.breakdown_low,
        "depth_pts": depth_pts,
        "direction": trade.direction,
        "alignment": trade.alignment,
        "entry_price": trade.entry_price,
        "entry_time": trade.entry_time,
        "stop_price": trade.stop_price,
        "risk_pts": round(risk_pts, 2),
        "targets": trade.targets,
        "entry_time_et": entry_time_et,
        "minutes_from_open": minutes_from_open,
        "day_of_week": day_of_week,
        "gate_execute": gate.get("execute"),
        "gate_reasoning": gate.get("reasoning", ""),
        "gate_risk_factors": gate.get("risk_factors", []),
        "execution_mode": trade.execution_mode,
        "dry_run": trade.dry_run,
        "entry_order_id": trade.entry_order_id,
        "stop_order_id": trade.stop_order_id,
    }, path)


def append_trade_target_hit(
    trade: Trade,
    event: dict,
    path: Path = TRADES_LOG_PATH,
) -> None:
    """Registra que un target fue alcanzado con P&L y MFE en ese momento."""
    pnl = (event["price"] - trade.entry_price
           if trade.direction == "LONG"
           else trade.entry_price - event["price"])
    _append({
        "record_type": "target_hit",
        "trade_id": trade.id,
        "fecha": trade.entry_time[:10],
        "target_index": event["target_index"],
        "target_price": event["target_price"],
        "price_at_hit": event["price"],
        "timestamp": event["timestamp"],
        "new_stop": event["new_stop"],
        "old_stop": event["old_stop"],
        "pnl_at_hit_pts": round(pnl, 2),
        "mfe_pts": trade.mfe_pts,
    }, path)


def append_trade_close(
    trade: Trade,
    path: Path = TRADES_LOG_PATH,
) -> None:
    """Registra cierre con resultado completo y métricas estadísticas."""
    risk_pts = abs(trade.entry_price - trade.stop_price)
    pnl = trade.pnl_total_pts or 0.0

    try:
        entry_dt = datetime.fromisoformat(trade.entry_time)
        exit_dt = datetime.fromisoformat(trade.exit_time or trade.entry_time)
        duration = int((exit_dt - entry_dt).total_seconds() / 60)
    except Exception:
        duration = 0

    _append({
        "record_type": "close",
        "trade_id": trade.id,
        "fecha": trade.entry_time[:10],
        "exit_price": trade.exit_price,
        "exit_time": trade.exit_time,
        "exit_reason": trade.exit_reason,
        "pnl_total_pts": pnl,
        "targets_hit": trade.targets_hit,
        "mfe_pts": trade.mfe_pts,
        "duration_minutes": duration,
        "pnl_per_risk": round(pnl / risk_pts, 3) if risk_pts > 0 else 0.0,
        "dry_run": trade.dry_run,
    }, path)


def append_trade(trade: Trade, path: Path = TRADES_LOG_PATH) -> None:
    """Backwards-compat: registra cierre del trade."""
    append_trade_close(trade, path)


# ── Lecturas ──────────────────────────────────────────────────────────────────

def read_trades(path: Path = TRADES_LOG_PATH) -> list[dict]:
    if not path.exists():
        return []
    trades = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            trades.append(json.loads(line))
    return trades


def trades_for_date(fecha: str, path: Path = TRADES_LOG_PATH) -> list[dict]:
    return [t for t in read_trades(path)
            if t.get("entry_time", t.get("fecha", "")).startswith(fecha)]
