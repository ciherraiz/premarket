"""
Generación de gráficos PNG del plan Mancini.

Produce un mapa vertical de niveles con precio actual /ES,
detectores y trade activo. Se envía a Telegram en eventos clave.

Si se proporciona historial de precios, dibuja la línea de precio
intraday con eje X temporal. Si no, muestra solo la línea horizontal
del precio actual (modo estático).
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import TYPE_CHECKING

import matplotlib
matplotlib.use("Agg")  # backend sin GUI
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

if TYPE_CHECKING:
    from scripts.mancini.config import DailyPlan
    from scripts.mancini.detector import FailedBreakdownDetector
    from scripts.mancini.trade_manager import Trade


# ── Colores ────────────────────────────────────────────────────────
BG_OUTER = "#1a1a2e"
BG_INNER = "#16213e"
COLOR_ES = "#3498db"
COLOR_ENTRY = "#2ecc71"
COLOR_STOP = "#e74c3c"
COLOR_TARGET_UP = "#4ecca3"
COLOR_TARGET_DOWN = "#e74c3c"
COLOR_TARGET_HIT = "#555555"
COLOR_CHOP = "#f1c40f"

_STATE_STYLES: dict[str, tuple[str, str]] = {
    "WATCHING":  ("#888888", "VIGILANDO — esperando breakdown"),
    "BREAKDOWN": ("#e67e22", "BREAKDOWN"),
    "RECOVERY":  ("#f1c40f", "RECUPERANDO"),
    "SIGNAL":    ("#2ecc71", "SEÑAL CONFIRMADA"),
    "ACTIVE":    ("#2ecc71", "TRADE ACTIVO"),
    "DONE":      ("#555555", "COMPLETADO"),
    "EXPIRED":   ("#555555", "EXPIRADO"),
}


def _detector_style(detector: FailedBreakdownDetector) -> tuple[str, str]:
    """Retorna (color, texto_estado) para un detector."""
    state_val = detector.state.value
    color, text = _STATE_STYLES.get(state_val, ("#888888", state_val))

    if state_val == "BREAKDOWN" and detector.breakdown_low is not None:
        pts = abs(detector.level - detector.breakdown_low)
        text = f"BREAKDOWN ({pts:.0f} pts bajo nivel)"
    elif state_val == "RECOVERY":
        polls = getattr(detector, "acceptance_count", "?")
        text = f"RECUPERANDO — {polls} polls confirmando"

    return color, text


def _parse_price_history(
    price_history: list[tuple[str, float]] | None,
) -> tuple[list[datetime], list[float]]:
    """Parsea historial de precios a listas de datetime y float.

    Returns:
        (times, prices) — listas paralelas. Vacías si input es None/inválido.
    """
    if not price_history or len(price_history) < 2:
        return [], []

    times: list[datetime] = []
    prices: list[float] = []
    for t_str, p in price_history:
        try:
            dt = datetime.strptime(t_str, "%H:%M").replace(
                year=2000, month=1, day=1,
            )
            times.append(dt)
            prices.append(p)
        except ValueError:
            continue

    if len(times) < 2:
        return [], []

    return times, prices


def generate_plan_chart(
    plan: DailyPlan,
    es_price: float,
    detectors: list[FailedBreakdownDetector],
    trade: Trade | None = None,
    timestamp_et: str = "",
    price_history: list[tuple[str, float]] | None = None,
) -> bytes:
    """Genera PNG del plan Mancini con precio actual.

    Args:
        plan: plan del día con niveles y targets
        es_price: precio actual de /ES
        detectors: lista de detectores con su estado
        trade: trade activo (None si no hay)
        timestamp_et: hora ET para el título
        price_history: historial de precios [(HH:MM, price), ...]
                       Si tiene >=2 puntos, dibuja línea temporal.

    Returns:
        Bytes del PNG generado.
    """
    plt.close("all")  # liberar figuras anteriores antes de crear una nueva
    fig, ax = plt.subplots(figsize=(8, 6))

    # Estilo oscuro
    fig.patch.set_facecolor(BG_OUTER)
    ax.set_facecolor(BG_INNER)

    # Recopilar todos los niveles para calcular rango del eje Y
    levels: list[float] = []
    if plan.key_level_upper is not None:
        levels.append(plan.key_level_upper)
    if plan.key_level_lower is not None:
        levels.append(plan.key_level_lower)
    levels.extend(plan.targets_upper)
    levels.extend(plan.targets_lower)
    levels.append(es_price)
    if trade:
        levels.extend([trade.entry_price, trade.stop_price])

    if not levels:
        levels = [es_price]

    y_min = min(levels) - 15
    y_max = max(levels) + 15

    ax.set_ylim(y_min, y_max)

    # ── Modo temporal vs estático ────────────────────────────────
    times, prices = _parse_price_history(price_history)
    has_history = len(times) >= 2

    if has_history:
        ax.set_xlim(times[0], times[-1])
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        ax.tick_params(axis="x", colors="white", labelsize=8, rotation=45)
    else:
        ax.set_xlim(0, 1)
        ax.set_xticks([])

    # Transform blended: X en coordenadas de axes (0..1), Y en datos.
    # Funciona tanto en modo temporal como estático.
    ytx = ax.get_yaxis_transform()

    # ── 1. Targets upper ──────────────────────────────────────────
    for i, target in enumerate(plan.targets_upper):
        passed = target <= es_price
        color = COLOR_TARGET_HIT if passed else COLOR_TARGET_UP
        alpha = 0.4 if passed else 0.7
        label = f"Target {i + 1} \u2713" if passed else f"Target {i + 1}"
        ax.axhline(y=target, color=color, linestyle=":", linewidth=1, alpha=alpha)
        ax.text(0.72, target, f"{target:.0f}  {label}",
                color=color, fontsize=9, va="center",
                fontfamily="monospace", transform=ytx, alpha=alpha)

    # ── 2. Targets lower ──────────────────────────────────────────
    for i, target in enumerate(plan.targets_lower):
        passed = target >= es_price
        color = COLOR_TARGET_HIT if passed else COLOR_TARGET_DOWN
        alpha = 0.4 if passed else 0.7
        label = f"Target {i + 1} \u2193 \u2713" if passed else f"Target {i + 1} \u2193"
        ax.axhline(y=target, color=color, linestyle=":", linewidth=1, alpha=alpha)
        ax.text(0.72, target, f"{target:.0f}  {label}",
                color=color, fontsize=9, va="center",
                fontfamily="monospace", transform=ytx, alpha=alpha)

    # ── 3. Niveles clave con estado del detector ──────────────────
    # Líneas horizontales en el gráfico
    for detector in detectors:
        color, _status_text = _detector_style(detector)
        ax.axhline(y=detector.level, color=color, linewidth=2.5, alpha=0.9)
        side_label = "upper" if detector.side == "upper" else "lower"
        ax.text(0.72, detector.level,
                f"{detector.level:.0f}  Nivel {side_label}",
                color=color, fontsize=9, va="center",
                fontweight="bold", fontfamily="monospace",
                transform=ytx)

    # Panel de estado: esquina superior izquierda, fuera de la zona de datos
    if detectors:
        status_lines = []
        for detector in detectors:
            color, status_text = _detector_style(detector)
            side_label = "Upper" if detector.side == "upper" else "Lower"
            status_lines.append(f"{detector.level:.0f} {side_label}: {status_text}")
        status_block = "\n".join(status_lines)
        ax.text(0.02, 0.97, status_block,
                color="white", fontsize=9,
                fontfamily="monospace", fontweight="bold",
                va="top", transform=ax.transAxes,
                bbox=dict(boxstyle="round,pad=0.4",
                          facecolor=BG_OUTER, edgecolor="#555555",
                          alpha=0.9))

    # ── 4. Chop zone ─────────────────────────────────────────────
    if plan.chop_zone:
        ax.axhspan(plan.chop_zone[0], plan.chop_zone[1],
                   color=COLOR_CHOP, alpha=0.1)
        mid = (plan.chop_zone[0] + plan.chop_zone[1]) / 2
        ax.text(0.05, mid, "Chop zone", color=COLOR_CHOP,
                fontsize=9, alpha=0.7, fontfamily="monospace",
                transform=ytx)

    # ── 5. Trade activo ──────────────────────────────────────────
    if trade:
        # Entry
        ax.axhline(y=trade.entry_price, color=COLOR_ENTRY,
                   linewidth=1.5, linestyle="-")
        ax.text(0.02, trade.entry_price,
                f"\u25b6 Entry {trade.entry_price:.0f}",
                color=COLOR_ENTRY, fontsize=9, fontweight="bold",
                fontfamily="monospace", transform=ytx)
        # Stop
        ax.axhline(y=trade.stop_price, color=COLOR_STOP,
                   linewidth=1.5, linestyle="-")
        ax.text(0.02, trade.stop_price,
                f"\u2716 Stop {trade.stop_price:.0f}",
                color=COLOR_STOP, fontsize=9, fontweight="bold",
                fontfamily="monospace", transform=ytx)
        # Zona de riesgo
        ax.axhspan(min(trade.entry_price, trade.stop_price),
                   max(trade.entry_price, trade.stop_price),
                   color=COLOR_STOP, alpha=0.08)

    # ── 6. Precio actual /ES ─────────────────────────────────────
    if has_history:
        # Línea de precio intraday
        ax.plot(times, prices, color=COLOR_ES, linewidth=2, alpha=0.9,
                zorder=5)
        # Marker del precio actual en el último punto
        ax.text(0.02, es_price,
                f"\u25b6 ES {es_price:.2f}",
                color=COLOR_ES, fontsize=11, fontweight="bold",
                fontfamily="monospace", transform=ytx,
                bbox=dict(boxstyle="round,pad=0.3", facecolor=BG_OUTER,
                          edgecolor=COLOR_ES, alpha=0.9),
                zorder=6)
    else:
        # Modo estático: línea horizontal
        ax.axhline(y=es_price, color=COLOR_ES, linewidth=3, alpha=0.9)
        ax.text(0.02, es_price,
                f"\u25b6 ES {es_price:.2f}",
                color=COLOR_ES, fontsize=11, fontweight="bold",
                fontfamily="monospace", transform=ytx,
                bbox=dict(boxstyle="round,pad=0.3", facecolor=BG_OUTER,
                          edgecolor=COLOR_ES, alpha=0.9))

    # ── 7. Título ────────────────────────────────────────────────
    fecha = plan.fecha
    ax.set_title(f"Mancini Plan  |  {fecha}  |  {timestamp_et}",
                 color="white", fontsize=11, fontfamily="monospace",
                 pad=10)

    # ── Estilo de ejes ───────────────────────────────────────────
    ax.tick_params(axis="y", colors="white", labelsize=9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#555555")
    if has_history:
        ax.spines["bottom"].set_color("#555555")
    else:
        ax.spines["bottom"].set_visible(False)

    plt.subplots_adjust(right=0.68)

    # Exportar a bytes
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100,
                facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()
