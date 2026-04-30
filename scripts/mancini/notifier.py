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
from scripts.notify_telegram import send_telegram, send_telegram_photo, _esc


def notify_plan_loaded(plan: dict,
                       price: float | None = None,
                       session_start: int | None = None,
                       session_end: int | None = None) -> bool:
    """Alerta: plan del día cargado con niveles extraídos.

    Si price se proporciona, muestra el contexto operativo actual
    (distancia al nivel inferior y si hay setup posible).
    Si session_start/session_end se proporcionan, incluye la línea de monitor.
    """
    is_stale = plan.get("is_stale", False)
    is_auto = plan.get("is_auto_levels", False)
    fecha = _esc(plan.get("fecha", "N/A"))
    upper = _esc(plan.get("key_level_upper", "N/A"))
    lower_val = plan.get("key_level_lower")
    lower = _esc(lower_val) if lower_val is not None else "N/A"
    targets_up = ", ".join(_esc(str(t)) for t in plan.get("targets_upper", []))
    targets_down = ", ".join(_esc(str(t)) for t in plan.get("targets_lower", []))
    notes = plan.get("notes", "")

    chop = plan.get("chop_zone")
    chop_line = f"🔄 *Chop zone:* {_esc(chop[0])} \\- {_esc(chop[1])}" if chop else ""

    if is_auto:
        header = f"📐 *Sin plan de Mancini \\— niveles técnicos autónomos \\| {fecha}*"
        stale_footer = "⚠️ _Sin targets conocidos\\. Se actualizará cuando Mancini publique\\._"
    elif is_stale:
        header = f"⚠️ *Fallback plan {fecha} \\(sin plan de hoy\\)*"
        stale_footer = "📅 _Niveles del día anterior\\. Se actualizará cuando Mancini publique\\._"
    else:
        header = f"🎯 *Mancini Plan \\| {fecha}*"
        stale_footer = ""

    lines = [
        header,
        "",
        f"🟢 *Upper:* {upper} → {targets_up}",
        f"🔴 *Lower:* {lower} → {targets_down}",
    ]

    if chop_line:
        lines.append(chop_line)

    # Contexto determinista basado en precio actual
    if price is not None and lower_val is not None:
        dist = price - lower_val
        lines.append("")
        lines.append(f"📊 *ES:* {_esc(f'{price:.2f}')} \\| {_esc(f'{dist:+.1f}')} pts sobre nivel inferior")
        if dist > 15:
            lines.append("⏳ En standby — precio lejos del nivel, sin setup posible")
        elif dist > 0:
            lines.append("👀 Zona de alerta — precio próximo al nivel, vigilar breakdown")
        else:
            lines.append("⚠️ Precio bajo el nivel — detector activo")

    if notes:
        lines += ["", f'💬 {_esc(notes)}']

    if stale_footer:
        lines += ["", stale_footer]

    if session_start is not None and session_end is not None:
        lines.append("")
        lines.append(
            f"📡 Monitor activo {session_start:02d}:00\\-{session_end:02d}:00 ET"
        )

    msg = "\n".join(lines)
    return send_telegram(msg.strip())


def notify_auto_levels(auto) -> bool:
    """Alerta: niveles técnicos autónomos calculados — para comparar con el plan de Mancini."""
    fecha = _esc(auto.fecha)
    spot = auto.spot

    # Separar niveles priority <= 2 (semanales, mensuales, GEX, diarios) — excluir round numbers
    relevant = [l for l in auto.levels if l.priority <= 2]

    above = [l for l in relevant if l.value > spot]
    below = [l for l in relevant if l.value < spot]

    def fmt_level(l) -> str:
        group_tag = {"gex": "GEX", "weekly": "sem", "monthly": "mes", "daily": "día", "overnight": "ON"}.get(l.group, l.group)
        return f"  {_esc(f'{l.value:.2f}')} _{_esc(l.label)}_ \\({group_tag}\\)"

    lines = [
        f"📐 *Niveles técnicos \\| {fecha}*",
        "",
        f"📊 ES referencia: *{_esc(f'{spot:.2f}')}*",
        "",
    ]

    if above:
        lines.append("🔴 *Por encima:*")
        for l in above[:6]:  # máx 6 para no saturar
            lines.append(fmt_level(l))
        lines.append("")

    if below:
        lines.append("🟢 *Por debajo:*")
        for l in below[:6]:
            lines.append(fmt_level(l))
        lines.append("")

    lines.append("_Compara con el plan de Mancini cuando publique\\._")

    return send_telegram("\n".join(lines).strip())


def notify_approaching_level(level: float, price: float, distance: float,
                             gex_snapshot: dict | None = None) -> bool:
    """Alerta: precio entrando en zona de alerta del nivel clave."""
    lines = [
        "👀 *Zona de alerta*",
        "",
        f"📍 Nivel: {_esc(level)}",
        f"📊 ES: {_esc(f'{price:.2f}')} \\({_esc(f'{distance:+.1f}')} pts\\)",
        "",
        "Precio próximo al nivel — vigilar posible breakdown\\.",
    ]
    if gex_snapshot:
        low  = gex_snapshot.get("chop_zone_low")
        high = gex_snapshot.get("chop_zone_high")
        if low is not None and high is not None and low <= price <= high:
            lines.append(
                f"🔀 En Chop Zone GEX \\({_esc(f'{low:.0f}')}\\-{_esc(f'{high:.0f}')}\\) \\— precaución"
            )
    return send_telegram("\n".join(lines))


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
                  breakdown_low: float,
                  alignment: str = "") -> bool:
    """Alerta: señal de entrada — failed breakdown confirmado."""
    risk = abs(entry - stop)

    rr_lines = []
    for i, t in enumerate(targets, 1):
        reward = abs(t - entry)
        rr = f"1:{reward/risk:.1f}" if risk > 0 else "N/A"
        rr_lines.append(f"  T{i} {_esc(str(t))} → {_esc(rr)}")
    rr_str = "\n".join(rr_lines)

    lines = [
        "🟢 *FAILED BREAKDOWN — SEÑAL*",
        "",
        f"📍 Nivel: {_esc(level)} \\| Reclaim: {_esc(price)}",
        f"📉 Breakdown low: {_esc(breakdown_low)}",
        "",
        f"▶️ *Entry:* {_esc(entry)}",
        f"🛑 *Stop:* {_esc(stop)} \\(\\-{_esc(f'{risk:.0f}')} pts\\)",
        f"🎯 *Targets \\(R:R\\):*",
        rr_str,
    ]

    if alignment == "MISALIGNED":
        lines.append("")
        lines.append("⚠️ *Contra sesgo semanal — solo T1*")
    elif alignment == "ALIGNED":
        lines.append("")
        lines.append("✅ *Alineado con Big Picture*")

    return send_telegram("\n".join(lines))


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
                        pnl_total: float) -> bool:
    """Alerta: trade cerrado con resumen P&L."""
    reason_emoji = {
        "STOP": "🛑",
        "EOD": "🕐",
        "MANUAL": "✋",
    }
    emoji = reason_emoji.get(reason, "📊")
    pnl_sign = "\\+" if pnl_total >= 0 else ""

    lines = [
        f"{emoji} *Trade cerrado \\| {_esc(reason)}*",
        "",
        f"▶️ Entry: {_esc(entry)} → Exit: {_esc(exit_price)}",
        f"📊 *P&L total: {pnl_sign}{_esc(f'{pnl_total:.1f}')} pts*",
    ]

    return send_telegram("\n".join(lines))


def notify_target_hit(event: dict) -> bool:
    """Alerta: target alcanzado, trailing stop actualizado."""
    idx = event["target_index"]
    lines = [
        f"🎯 *Target {idx + 1} alcanzado*",
        "",
        f"📍 {_esc(event['target_price'])} \\| ES: {_esc(event['price'])}",
        f"🛑 Stop subido: {_esc(event['old_stop'])} → {_esc(event['new_stop'])}",
    ]

    return send_telegram("\n".join(lines))


def notify_gate_approved(decision, level: float, price: float,
                         stop_price: float, targets: list[float],
                         alignment: str) -> bool:
    """Alerta: Execution Gate aprueba ejecución."""
    risk = abs(price - stop_price)
    targets_str = ", ".join(_esc(str(t)) for t in targets)

    lines = [
        "✅ *Execution Gate — APROBADO*",
        "",
        f"📍 Nivel: {_esc(level)} \\| ES: {_esc(price)}",
        f"🛑 Stop: {_esc(stop_price)} \\(\\-{_esc(f'{risk:.0f}')} pts\\)",
        f"🎯 Targets: {targets_str}",
        "",
        f"🤖 {_esc(decision.reasoning)}",
    ]

    return send_telegram("\n".join(lines))


def notify_trade_rejected(decision) -> bool:
    """Alerta: trade descartado (trader dijo no o timeout)."""
    if decision is None:
        return False

    factors = ", ".join(decision.risk_factors) if decision.risk_factors else "ninguno"

    lines = [
        "🚫 *Trade descartado*",
        "",
        f"🤖 {_esc(decision.reasoning)}",
        f"🔍 Factores: {_esc(factors)}",
    ]

    return send_telegram("\n".join(lines))


def notify_plan_chart(plan, es_price: float, detectors, trade=None,
                      price_history: list[tuple[str, float]] | None = None) -> bool:
    """Genera y envía gráfico del plan a Telegram."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from scripts.mancini.chart import generate_plan_chart

    timestamp_et = datetime.now(ZoneInfo("America/New_York")).strftime("%H:%M ET")
    try:
        png_bytes = generate_plan_chart(
            plan=plan,
            es_price=es_price,
            detectors=detectors,
            trade=trade,
            timestamp_et=timestamp_et,
            price_history=price_history,
        )
    except Exception as e:
        print(f"[notifier] Error generando chart: {e}")
        return False

    return send_telegram_photo(png_bytes, caption=f"📊 Plan Mancini | {plan.fecha}")


def notify_weekly_plan(plan: dict) -> bool:
    """Alerta: Big Picture View semanal cargado."""
    week = _esc(plan.get("fecha", "N/A"))
    upper = _esc(plan.get("key_level_upper", "N/A"))
    lower = _esc(plan.get("key_level_lower", "N/A"))
    targets = ", ".join(_esc(str(t)) for t in plan.get("targets_upper", []))
    notes = _esc(plan.get("notes", ""))

    msg = "\n".join([
        f"📊 *Big Picture \\| Semana {week}*",
        "",
        f"🟢 *Soporte clave:* {upper}",
        f"🔴 *Mínimo:* {lower}",
        f"🎯 *Targets semana:* {targets}",
        "",
        f"📝 {notes}",
    ])
    return send_telegram(msg.strip())


def notify_adjustment(adj) -> bool:
    """Alerta: ajuste intraday clasificado por el LLM.

    Muestra el tweet original de Mancini y la conclusion del clasificador
    para que el trader valore si el ajuste automatico es correcto.
    """
    from scripts.mancini.config import PlanAdjustment

    icons = {
        "INVALIDATION": "🚫",
        "LEVEL_UPDATE": "📐",
        "TARGET_UPDATE": "🎯",
        "BIAS_SHIFT": "🔄",
        "CONTEXT_UPDATE": "💬",
    }
    icon = icons.get(adj.adjustment_type, "📝")

    msg = "\n".join([
        f"{icon} *Mancini Update*",
        "",
        f"📝 @AdamMancini4:",
        f'"{_esc(adj.tweet_text)}"',
        "",
        f"🤖 *Conclusión:* {_esc(adj.raw_reasoning)}",
    ])

    return send_telegram(msg)


def notify_scan_failure(reason: str) -> bool:
    """Alerta: el scan de tweets falló o no encontró plan."""
    msg = "\n".join([
        "⚠️ *Mancini Scan FAILED*",
        "",
        f"📝 {_esc(reason)}",
    ])
    return send_telegram(msg)


def notify_monitor_crash(error: str) -> bool:
    """Alerta: el monitor se ha caído inesperadamente."""
    msg = "\n".join([
        "🔴 *Mancini Monitor CRASHED*",
        "",
        f"💥 {_esc(error)}",
    ])
    return send_telegram(msg)


def notify_gex_open(snapshot: dict, auto_levels=None) -> bool:
    """Primer snapshot GEX del día (~9:35 ET): niveles GEX + técnicos combinados y ordenados."""
    ts = snapshot.get("ts", "")[:16].replace("T", " ")
    spot = snapshot.get("spot")
    es_basis = snapshot.get("es_basis")
    net = snapshot.get("net_gex_bn")
    signal = snapshot.get("signal_gex", "")
    regime = snapshot.get("regime_text", "")

    def _es(v: float | None) -> str:
        if v is None or es_basis is None:
            return ""
        return f" \\(\\~ES {int(round(v * es_basis))}\\)"

    spot_str = f"SPX {int(spot)}" if spot else "SPX N/A"
    es_str = f" / ES {int(round(spot * es_basis))}" if spot and es_basis else ""
    net_str = f"{net:+.2f}B" if net is not None else "N/A"

    lines = [
        f"📊 *Apertura GEX \\| {_esc(ts)} ET*",
        "",
        f"📈 {_esc(spot_str)}{_esc(es_str)} \\| Net: {_esc(net_str)}",
        f"🔮 {_esc(signal)}",
        "",
    ]

    # Nivel combinados: GEX del snapshot + niveles técnicos del premarket
    entries: list[tuple[float, str]] = []

    for key, icon, label in [
        ("call_wall",    "📈", "CALL WALL"),
        ("flip_level",   "🎯", "FLIP"),
        ("control_node", "🔴", "CN"),
        ("put_wall",     "🟢", "PUT WALL"),
    ]:
        val = snapshot.get(key)
        if val is not None:
            entries.append((float(val), f"{icon} {label}{_es(float(val))}"))

    chop_low  = snapshot.get("chop_zone_low")
    chop_high = snapshot.get("chop_zone_high")
    if chop_low is not None and chop_high is not None:
        mid = (chop_low + chop_high) / 2
        entries.append((mid, f"🔀 CHOP {int(chop_low)}\\-{int(chop_high)}"))

    if spot:
        entries.append((spot, f"▶ {_esc(spot_str)}{_esc(es_str)}"))

    if auto_levels is not None and spot is not None:
        group_icon = {
            "daily":     "📊",
            "weekly":    "📅",
            "monthly":   "📆",
            "round":     "⬜",
            "overnight": "🌙",
        }

        # Count GEX key levels already collected per side (to cap total)
        gex_above = sum(
            1 for k in ("call_wall", "flip_level", "control_node", "put_wall")
            if snapshot.get(k) is not None and float(snapshot[k]) > spot
        )
        gex_below = sum(
            1 for k in ("call_wall", "flip_level", "control_node", "put_wall")
            if snapshot.get(k) is not None and float(snapshot[k]) < spot
        )
        take_above = max(0, 4 - gex_above)
        take_below = max(0, 4 - gex_below)

        # Non-round levels within ±75 pts
        tech = [l for l in auto_levels.levels
                if l.group != "round" and abs(l.value - spot) <= 75]
        tech_vals = {l.value for l in tech} | {
            float(snapshot[k]) for k in ("call_wall", "flip_level", "control_node", "put_wall")
            if snapshot.get(k) is not None
        }

        # Round numbers only if within ±5 pts of any other level
        for lvl in auto_levels.levels:
            if lvl.group != "round" or abs(lvl.value - spot) > 75:
                continue
            if any(abs(lvl.value - v) <= 5 for v in tech_vals):
                tech.append(lvl)

        # Closest levels per side up to the cap
        above = sorted([l for l in tech if l.value > spot], key=lambda l: l.value)[:take_above]
        below = sorted([l for l in tech if l.value < spot], key=lambda l: -l.value)[:take_below]

        for lvl in above + below:
            icon = group_icon.get(lvl.group, "⬜")
            entries.append((float(lvl.value), f"{icon} {_esc(lvl.label)}"))

    entries.sort(key=lambda x: x[0], reverse=True)

    if entries:
        lines.append("*Niveles:*")
        for val, label in entries:
            lines.append(f"  {int(val)} {label}")
        lines.append("")

    if regime and regime != "Régimen GEX no disponible":
        lines.append(f"_{_esc(regime)}_")

    return send_telegram("\n".join(lines).strip())


def notify_gex_shift(shift: dict) -> bool:
    """Alerta: el flip_level o control_node se han desplazado > 10 pts intraday."""
    shift_type = shift.get("type", "")
    spot        = shift.get("spot")
    ts          = shift.get("ts", "")[:16].replace("T", " ")  # "2026-04-29 14:32"
    regime_text = shift.get("regime_text", "")

    flip_prev = shift.get("flip_prev")
    flip_curr = shift.get("flip_curr")
    cn_prev   = shift.get("cn_prev")
    cn_curr   = shift.get("cn_curr")

    def _fmt(v, prev=None) -> str:
        if v is not None:
            return str(int(v))
        # Contexto: si el nivel desaparece → régimen cambió
        return "desaparece" if prev is not None else "sin nivel"

    def _delta(prev, curr) -> str:
        if prev is None or curr is None:
            return ""
        d = curr - prev
        return f" \\({'+' if d >= 0 else ''}{int(d)} pts\\)"

    lines = ["⚡ *GEX Shift detectado*", ""]

    if shift_type in ("FLIP_SHIFT", "BOTH"):
        lines.append(
            f"🎯 Flip: {_esc(_fmt(flip_prev))} → *{_esc(_fmt(flip_curr, flip_prev))}*"
            f"{_esc(_delta(flip_prev, flip_curr))}"
        )
    else:
        lines.append(f"🎯 Flip: {_esc(_fmt(flip_curr))} \\(sin cambio\\)")

    if shift_type in ("CONTROL_NODE_SHIFT", "BOTH"):
        lines.append(
            f"🔴 CN:   {_esc(_fmt(cn_prev))} → *{_esc(_fmt(cn_curr, cn_prev))}*"
            f"{_esc(_delta(cn_prev, cn_curr))}"
        )
    else:
        lines.append(f"🔴 CN:   {_esc(_fmt(cn_curr))} \\(sin cambio\\)")

    lines += [
        "",
        f"📊 Spot: {_esc(_fmt(spot))} \\| {_esc(ts)} ET",
    ]

    if regime_text and regime_text != "Régimen GEX no disponible":
        lines += ["", f"_{_esc(regime_text)}_"]

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
