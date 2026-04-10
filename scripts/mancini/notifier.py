"""
Alertas Telegram específicas para la estrategia Mancini.

Reutiliza send_telegram() y _esc() de scripts/notify_telegram.py.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Importar utilidades del notifier existente
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from scripts.notify_telegram import send_telegram, _esc


def notify_plan_loaded(plan: dict) -> bool:
    """Alerta: plan del día cargado con niveles extraídos."""
    fecha = _esc(plan.get("fecha", "N/A"))
    upper = _esc(plan.get("key_level_upper", "N/A"))
    lower = _esc(plan.get("key_level_lower", "N/A"))
    targets_up = ", ".join(_esc(str(t)) for t in plan.get("targets_upper", []))
    targets_down = ", ".join(_esc(str(t)) for t in plan.get("targets_lower", []))

    chop = plan.get("chop_zone")
    chop_line = ""
    if chop:
        chop_line = f"\n🔄 *Chop zone:* {_esc(chop[0])} \\- {_esc(chop[1])}"

    msg = "\n".join([
        f"🎯 *Mancini Plan \\| {fecha}*",
        "",
        f"🟢 *Upper:* {upper} → {targets_up}",
        f"🔴 *Lower:* {lower} → {targets_down}",
        chop_line,
        "",
        "📡 Monitor activo 08:00\\-11:00 ET",
    ])
    return send_telegram(msg.strip())


def notify_breakdown(level: float, price: float, depth: float) -> bool:
    """Alerta: breakdown detectado, vigilando recuperación."""
    msg = "\n".join([
        "⚠️ *Breakdown detectado*",
        "",
        f"📍 Nivel: {_esc(level)}",
        f"💰 ES: {_esc(price)} \\({_esc(f'{depth:+.1f}')} pts\\)",
        "",
        "Vigilando recuperación\\.\\.\\.",
    ])
    return send_telegram(msg)


def notify_signal(level: float, price: float, entry: float,
                  stop: float, targets: list[float],
                  breakdown_low: float) -> bool:
    """Alerta: señal de entrada — failed breakdown confirmado."""
    risk = abs(entry - stop)
    targets_str = ", ".join(_esc(str(t)) for t in targets)
    reward_1 = abs(targets[0] - entry) if targets else 0

    msg = "\n".join([
        "🟢 *FAILED BREAKDOWN \\— SEÑAL*",
        "",
        f"📍 Nivel: {_esc(level)} \\| Reclaim: {_esc(price)}",
        f"📉 Breakdown low: {_esc(breakdown_low)}",
        "",
        f"▶️ *Entry:* {_esc(entry)}",
        f"🛑 *Stop:* {_esc(stop)} \\(\\-{_esc(f'{risk:.0f}')} pts\\)",
        f"🎯 *Targets:* {targets_str}",
        f"📊 R:R \\= 1:{_esc(f'{reward_1/risk:.1f}') if risk > 0 else 'N/A'}",
    ])
    return send_telegram(msg)


def notify_partial_exit(price: float, pnl_pts: float,
                        runner_stop: float) -> bool:
    """Alerta: Target 1 alcanzado, profit parcial."""
    msg = "\n".join([
        "✅ *Target 1 alcanzado*",
        "",
        f"💰 Parcial: {_esc(price)} \\(\\+{_esc(f'{pnl_pts:.0f}')} pts\\)",
        f"🛑 Stop → breakeven: {_esc(runner_stop)}",
        "",
        "Runner activo buscando Target 2\\.\\.\\.",
    ])
    return send_telegram(msg)


def notify_trade_closed(reason: str, entry: float, exit_price: float,
                        pnl_total: float, pnl_partial: float | None = None,
                        pnl_runner: float | None = None) -> bool:
    """Alerta: trade cerrado con resumen P&L."""
    reason_emoji = {
        "TARGET_1": "🎯",
        "TARGET_2": "🎯🎯",
        "STOP": "🛑",
        "RUNNER_STOP": "🔄",
        "EOD": "🕐",
        "MANUAL": "✋",
    }
    emoji = reason_emoji.get(reason, "📊")
    pnl_sign = "\\+" if pnl_total >= 0 else ""

    lines = [
        f"{emoji} *Trade cerrado \\| {_esc(reason)}*",
        "",
        f"▶️ Entry: {_esc(entry)} → Exit: {_esc(exit_price)}",
    ]

    if pnl_partial is not None and pnl_runner is not None:
        lines.append(
            f"💰 Parcial: \\+{_esc(f'{pnl_partial:.0f}')} pts "
            f"\\| Runner: {_esc(f'{pnl_runner:+.0f}')} pts"
        )

    lines.append(f"📊 *P&L total: {pnl_sign}{_esc(f'{pnl_total:.1f}')} pts*")

    return send_telegram("\n".join(lines))


def notify_session_summary(fecha: str, trades_count: int,
                           total_pnl: float) -> bool:
    """Alerta: resumen de la sesión al finalizar."""
    pnl_sign = "\\+" if total_pnl >= 0 else ""
    pnl_emoji = "🟢" if total_pnl > 0 else ("🔴" if total_pnl < 0 else "⚪")

    msg = "\n".join([
        f"📋 *Resumen sesión \\| {_esc(fecha)}*",
        "",
        f"📊 Trades: {_esc(trades_count)}",
        f"{pnl_emoji} *P&L total: {pnl_sign}{_esc(f'{total_pnl:.1f}')} pts*",
    ])
    return send_telegram(msg)
