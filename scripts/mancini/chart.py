"""
Generación de gráficos PNG del plan Mancini.

Produce un mapa vertical de niveles con precio actual /ES,
detectores y trade activo. Se envía a Telegram en eventos clave.
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

import matplotlib
matplotlib.use("Agg")  # backend sin GUI
import matplotlib.pyplot as plt

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


def generate_plan_chart(
    plan: DailyPlan,
    es_price: float,
    detectors: list[FailedBreakdownDetector],
    trade: Trade | None = None,
    timestamp_et: str = "",
) -> bytes:
    """Genera PNG del plan Mancini con precio actual.

    Args:
        plan: plan del día con niveles y targets
        es_price: precio actual de /ES
        detectors: lista de detectores con su estado
        trade: trade activo (None si no hay)
        timestamp_et: hora ET para el título

    Returns:
        Bytes del PNG generado.
    """
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
    ax.set_xlim(0, 1)
    ax.set_xticks([])  # sin eje X

    # ── 1. Targets upper ──────────────────────────────────────────
    for i, target in enumerate(plan.targets_upper):
        hit = trade is not None and trade.targets_hit > i
        color = COLOR_TARGET_HIT if hit else COLOR_TARGET_UP
        label = f"Target {i + 1} \u2713" if hit else f"Target {i + 1}"
        ax.axhline(y=target, color=color, linestyle=":", linewidth=1, alpha=0.7)
        ax.text(0.72, target, f"{target:.0f}  {label}",
                color=color, fontsize=9, va="center",
                fontfamily="monospace")

    # ── 2. Targets lower ──────────────────────────────────────────
    for i, target in enumerate(plan.targets_lower):
        color = COLOR_TARGET_DOWN
        ax.axhline(y=target, color=color, linestyle=":", linewidth=1, alpha=0.7)
        ax.text(0.72, target, f"{target:.0f}  Target {i + 1} \u2193",
                color=color, fontsize=9, va="center",
                fontfamily="monospace")

    # ── 3. Niveles clave con estado del detector ──────────────────
    for detector in detectors:
        color, status_text = _detector_style(detector)
        ax.axhline(y=detector.level, color=color, linewidth=2.5, alpha=0.9)
        side_label = "upper" if detector.side == "upper" else "lower"
        ax.text(0.72, detector.level,
                f"{detector.level:.0f}  Nivel {side_label}\n"
                f"         {status_text}",
                color=color, fontsize=9, va="center",
                fontweight="bold", fontfamily="monospace")

    # ── 4. Chop zone ─────────────────────────────────────────────
    if plan.chop_zone:
        ax.axhspan(plan.chop_zone[0], plan.chop_zone[1],
                   color=COLOR_CHOP, alpha=0.1)
        mid = (plan.chop_zone[0] + plan.chop_zone[1]) / 2
        ax.text(0.05, mid, "Chop zone", color=COLOR_CHOP,
                fontsize=9, alpha=0.7, fontfamily="monospace")

    # ── 5. Trade activo ──────────────────────────────────────────
    if trade:
        # Entry
        ax.axhline(y=trade.entry_price, color=COLOR_ENTRY,
                   linewidth=1.5, linestyle="-")
        ax.text(0.02, trade.entry_price,
                f"\u25b6 Entry {trade.entry_price:.0f}",
                color=COLOR_ENTRY, fontsize=9, fontweight="bold",
                fontfamily="monospace")
        # Stop
        ax.axhline(y=trade.stop_price, color=COLOR_STOP,
                   linewidth=1.5, linestyle="-")
        ax.text(0.02, trade.stop_price,
                f"\u2716 Stop {trade.stop_price:.0f}",
                color=COLOR_STOP, fontsize=9, fontweight="bold",
                fontfamily="monospace")
        # Zona de riesgo
        ax.axhspan(min(trade.entry_price, trade.stop_price),
                   max(trade.entry_price, trade.stop_price),
                   color=COLOR_STOP, alpha=0.08)

    # ── 6. Precio actual /ES ─────────────────────────────────────
    ax.axhline(y=es_price, color=COLOR_ES, linewidth=3, alpha=0.9)
    ax.text(0.02, es_price,
            f"\u25b6 ES {es_price:.2f}",
            color=COLOR_ES, fontsize=11, fontweight="bold",
            fontfamily="monospace",
            bbox=dict(boxstyle="round,pad=0.3", facecolor=BG_OUTER,
                      edgecolor=COLOR_ES, alpha=0.9))

    # ── 7. Título ────────────────────────────────────────────────
    fecha = plan.fecha
    ax.set_title(f"Mancini Plan  |  {fecha}  |  {timestamp_et}",
                 color="white", fontsize=11, fontfamily="monospace",
                 pad=10)

    # ── Estilo del eje Y ─────────────────────────────────────────
    ax.tick_params(axis="y", colors="white", labelsize=9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["bottom"].set_visible(False)
    ax.spines["left"].set_color("#555555")

    plt.tight_layout()

    # Exportar a bytes
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120,
                facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()
