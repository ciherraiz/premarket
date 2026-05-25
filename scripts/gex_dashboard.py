"""
Dashboard GEX premarket — panel multi-columna al estilo @quantedOptions.

Genera una imagen PNG de ~1400×800px con tres paneles:
  Izquierdo  — GEX por strike 0DTE (barras horizontales)
  Central    — Net GEX por bucket DTE (barras agrupadas premarket o serie temporal intraday)
  Derecho    — Delta Exposure (DEX) acumulado

Uso:
    uv run python scripts/gex_dashboard.py              # guarda outputs/dashboard_YYYY-MM-DD.png
    uv run python scripts/gex_dashboard.py --show       # abre la imagen tras generarla
    uv run python scripts/gex_dashboard.py --telegram   # envía a Telegram
"""
from __future__ import annotations

import io
import json
import os
import sys
from datetime import date as date_cls
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

# ── Paleta ────────────────────────────────────────────────────────────────────
BG_COLOR    = "#0d1117"
PANEL_COLOR = "#161b22"
TEAL        = "#00B4D8"
CORAL       = "#FF6B6B"
ORANGE      = "#FFA500"
GREEN_LINE  = "#00FF7F"
RED_LINE    = "#FF4444"
WHITE       = "#FFFFFF"
YELLOW      = "#FFD700"
GRAY        = "#444444"
CYAN        = "#00FFFF"
MAGENTA     = "#FF00FF"

DASHBOARD_DPI  = 120
DASHBOARD_SIZE = (14, 8)   # pulgadas → ~1680×960px a 120dpi
N_STRIKES_SHOW = 25        # strikes más cercanos al spot en el panel izquierdo


# ── Función principal ─────────────────────────────────────────────────────────

def build_premarket_dashboard(indicators: dict) -> bytes:
    """
    Construye el dashboard GEX premarket y devuelve los bytes PNG.

    Args:
        indicators: dict de indicators.json (sección "premarket" o raíz).
                    Debe contener net_gex, charm_exposure, delta_exposure, pinning_zone.

    Returns:
        bytes PNG de la imagen generada.
    """
    # ── Extraer datos ─────────────────────────────────────────────────────────
    net_gex  = indicators.get("net_gex", {})
    charm    = indicators.get("charm_exposure", {})
    dex_data = indicators.get("delta_exposure", {})
    pin      = indicators.get("pinning_zone", {})
    fecha    = indicators.get("fecha") or str(date_cls.today())

    spot         = net_gex.get("spot")
    flip_level   = net_gex.get("flip_level")
    call_wall    = net_gex.get("call_wall")
    put_wall     = net_gex.get("put_wall")
    chop_low     = net_gex.get("chop_zone_low")
    chop_high    = net_gex.get("chop_zone_high")
    pinning_zone = pin.get("pinning_zone")
    net_gex_by_dte = net_gex.get("net_gex_by_dte", {})

    gex_by_strike = {float(k): v for k, v in net_gex.get("gex_by_strike", {}).items()}
    dex_cum       = {float(k): v for k, v in dex_data.get("dex_cumulative", {}).items()}

    # ── Figura ────────────────────────────────────────────────────────────────
    fig, (ax_left, ax_center, ax_right) = plt.subplots(
        1, 3,
        figsize=DASHBOARD_SIZE,
        facecolor=BG_COLOR,
        gridspec_kw={"width_ratios": [2, 2, 1.5]},
    )
    for ax in (ax_left, ax_center, ax_right):
        ax.set_facecolor(PANEL_COLOR)
        ax.tick_params(colors=WHITE, labelsize=7)
        for spine in ax.spines.values():
            spine.set_edgecolor(GRAY)

    # ── Panel izquierdo — GEX por strike 0DTE ─────────────────────────────────
    _draw_gex_by_strike(ax_left, gex_by_strike, spot, flip_level, call_wall,
                        put_wall, pinning_zone, chop_low, chop_high, fecha)

    # ── Panel central — Net GEX por bucket DTE ────────────────────────────────
    _draw_net_gex_by_dte(ax_center, net_gex_by_dte, fecha)

    # ── Panel derecho — DEX acumulado ─────────────────────────────────────────
    _draw_dex_cumulative(ax_right, dex_cum, spot, dex_data.get("dex_flip"), fecha)

    # ── Título global ─────────────────────────────────────────────────────────
    _gex_bn = net_gex.get("net_gex_bn")
    _gex_bn_str = f"{_gex_bn:+.1f}B" if _gex_bn is not None else "N/A"
    fig.suptitle(
        f"SPX Dealer Flow — {fecha}   |   "
        f"Net GEX: {_gex_bn_str}   |   "
        f"Régimen: {net_gex.get('signal_gex', 'N/A')}   |   "
        f"Charm: {charm.get('charm_signal', 'N/A')}",
        color=WHITE, fontsize=9, y=0.98,
    )

    plt.tight_layout(rect=[0, 0, 1, 0.96])

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=DASHBOARD_DPI,
                facecolor=BG_COLOR, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ── Paneles internos ──────────────────────────────────────────────────────────

def _draw_gex_by_strike(
    ax,
    gex_by_strike: dict[float, float],
    spot: float | None,
    flip_level: float | None,
    call_wall: float | None,
    put_wall: float | None,
    pinning_zone: float | None,
    chop_low: float | None,
    chop_high: float | None,
    fecha: str,
) -> None:
    """Barras horizontales de GEX por strike, calls en teal, puts en coral."""
    if not gex_by_strike:
        ax.text(0.5, 0.5, "Sin datos GEX", transform=ax.transAxes,
                color=WHITE, ha="center", va="center")
        ax.set_title(f"GEX 0DTE — {fecha}", color=WHITE, fontsize=8)
        return

    # Seleccionar los N_STRIKES_SHOW más cercanos al spot
    all_strikes = sorted(gex_by_strike.keys())
    if spot:
        all_strikes = sorted(all_strikes, key=lambda s: abs(s - spot))[:N_STRIKES_SHOW]
    all_strikes = sorted(all_strikes)

    gex_vals  = [gex_by_strike.get(s, 0.0) for s in all_strikes]
    colors    = [TEAL if v >= 0 else CORAL for v in gex_vals]

    y_pos = range(len(all_strikes))
    ax.barh(list(y_pos), gex_vals, color=colors, height=0.7, alpha=0.85)

    ax.set_yticks(list(y_pos))
    ax.set_yticklabels([f"{int(s)}" for s in all_strikes], fontsize=6)
    ax.set_xlabel("GEX (B)", color=WHITE, fontsize=7)
    ax.axvline(0, color=GRAY, linewidth=0.8)

    def _hline(level, color, label, ls="--", lw=1.0):
        if level is None:
            return
        try:
            idx = all_strikes.index(float(level))
        except ValueError:
            # Interpolación: posición proporcional
            idx = sum(1 for s in all_strikes if s < level) - 0.5
        ax.axhline(idx, color=color, linewidth=lw, linestyle=ls, alpha=0.85)
        ax.text(ax.get_xlim()[1] * 0.98 if ax.get_xlim()[1] > 0 else 0,
                idx + 0.2, label, color=color, fontsize=5, ha="right")

    if spot:
        try:
            idx_spot = min(range(len(all_strikes)), key=lambda i: abs(all_strikes[i] - spot))
            ax.axhline(idx_spot, color=WHITE, linewidth=1.5, linestyle="-", alpha=0.9)
            ax.text(0, idx_spot + 0.3, f"SPX {spot:.0f}", color=WHITE, fontsize=5)
        except Exception:
            pass

    _hline(flip_level,   ORANGE, "Flip",  ls="--")
    _hline(call_wall,    GREEN_LINE, "CW", ls="-.")
    _hline(put_wall,     RED_LINE,   "PW", ls="-.")
    _hline(pinning_zone, YELLOW,    "PIN", ls=":")

    # Chop zone — banda semitransparente
    if chop_low is not None and chop_high is not None:
        try:
            idx_low  = sum(1 for s in all_strikes if s < chop_low)
            idx_high = sum(1 for s in all_strikes if s <= chop_high) - 1
            ax.axhspan(idx_low - 0.5, idx_high + 0.5, alpha=0.12, color=GRAY)
        except Exception:
            pass

    ax.set_title(f"GEX 0DTE — {fecha}", color=WHITE, fontsize=8, pad=4)

    # Leyenda
    patches = [
        mpatches.Patch(color=TEAL,  label="Calls +GEX"),
        mpatches.Patch(color=CORAL, label="Puts −GEX"),
    ]
    ax.legend(handles=patches, fontsize=5, loc="lower right",
              facecolor=PANEL_COLOR, labelcolor=WHITE, framealpha=0.6)


def _draw_net_gex_by_dte(
    ax,
    net_gex_by_dte: dict,
    fecha: str,
) -> None:
    """Barras agrupadas del Net GEX por bucket DTE."""
    buckets = ["0DTE", "≤7DTE", "≤30DTE"]
    vals    = [
        net_gex_by_dte.get("0dte")  or 0.0,
        net_gex_by_dte.get("7dte")  or 0.0,
        net_gex_by_dte.get("30dte") or 0.0,
    ]
    colors = [TEAL, ORANGE, WHITE]
    x = np.arange(len(buckets))

    bars = ax.bar(x, vals, color=colors, width=0.55, alpha=0.85)
    ax.axhline(0, color=GRAY, linewidth=0.8)

    for bar, val in zip(bars, vals):
        ypos = val + (0.05 if val >= 0 else -0.15)
        ax.text(bar.get_x() + bar.get_width() / 2, ypos,
                f"{val:+.1f}B", color=WHITE, fontsize=7, ha="center", va="bottom")

    ax.set_xticks(x)
    ax.set_xticklabels(buckets, color=WHITE, fontsize=8)
    ax.set_ylabel("Net GEX (B)", color=WHITE, fontsize=7)
    ax.set_title(f"Net GEX por DTE — {fecha}", color=WHITE, fontsize=8, pad=4)

    # Colorear fondo según régimen
    net_30 = vals[2]
    bg_alpha = 0.04
    if net_30 > 0:
        ax.set_facecolor(TEAL)
        ax.patch.set_alpha(bg_alpha)
    else:
        ax.set_facecolor(CORAL)
        ax.patch.set_alpha(bg_alpha)


def _draw_dex_cumulative(
    ax,
    dex_cum: dict[float, float],
    spot: float | None,
    dex_flip: float | None,
    fecha: str,
) -> None:
    """DEX acumulado — área rellena cyan (>0) / magenta (<0)."""
    if not dex_cum:
        ax.text(0.5, 0.5, "Sin datos DEX\n(requiere delta en contratos)",
                transform=ax.transAxes, color=WHITE, ha="center", va="center",
                fontsize=7, wrap=True)
        ax.set_title("Delta Exposure (DEX)", color=WHITE, fontsize=8)
        return

    strikes_sorted = sorted(dex_cum.keys())
    dex_vals       = [dex_cum[s] for s in strikes_sorted]

    # Eje Y = strikes (horizontal), Eje X = DEX
    ax.plot(dex_vals, strikes_sorted, color=CYAN, linewidth=1.2)

    # Rellenar positivo (cyan) y negativo (magenta)
    pos_vals = [v if v > 0 else 0 for v in dex_vals]
    neg_vals = [v if v < 0 else 0 for v in dex_vals]
    ax.fill_betweenx(strikes_sorted, 0, pos_vals, color=CYAN,    alpha=0.25)
    ax.fill_betweenx(strikes_sorted, neg_vals, 0, color=MAGENTA, alpha=0.25)

    ax.axvline(0, color=GRAY, linewidth=0.8)

    if spot:
        ax.axhline(spot, color=WHITE, linewidth=1.2, linestyle="-", alpha=0.8)
        ax.text(ax.get_xlim()[0] if ax.get_xlim() else 0,
                spot + (strikes_sorted[-1] - strikes_sorted[0]) * 0.01,
                f"SPX {spot:.0f}", color=WHITE, fontsize=5)

    if dex_flip:
        ax.axhline(dex_flip, color=YELLOW, linewidth=1.0, linestyle="--", alpha=0.8)
        ax.text(0, dex_flip + (strikes_sorted[-1] - strikes_sorted[0]) * 0.01,
                f"DEX Flip {dex_flip:.0f}", color=YELLOW, fontsize=5)

    ax.set_xlabel("DEX (B)", color=WHITE, fontsize=7)
    ax.set_ylabel("Strike", color=WHITE, fontsize=7)
    ax.set_title("Delta Exposure (DEX)\nacumulado", color=WHITE, fontsize=8, pad=4)

    patches = [
        mpatches.Patch(color=CYAN,    label="Dealers largo Δ"),
        mpatches.Patch(color=MAGENTA, label="Dealers corto Δ"),
    ]
    ax.legend(handles=patches, fontsize=5, loc="lower right",
              facecolor=PANEL_COLOR, labelcolor=WHITE, framealpha=0.6)


# ── __main__ ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Dashboard GEX premarket")
    parser.add_argument("--show",     action="store_true", help="Abrir imagen tras generarla")
    parser.add_argument("--telegram", action="store_true", help="Enviar a Telegram")
    parser.add_argument("--date",     default=None,        help="Fecha YYYY-MM-DD (por defecto hoy)")
    args = parser.parse_args()

    out = Path("outputs")
    fecha_str = args.date or str(date_cls.today())

    # Cargar indicators.json
    ind_path = out / "indicators.json"
    if not ind_path.exists():
        print("[ERROR] No existe outputs/indicators.json — ejecuta run.py primero", file=sys.stderr)
        sys.exit(1)

    raw = json.loads(ind_path.read_text())
    # Compatibilidad: puede estar en root o en "premarket"
    indicators = raw.get("premarket", raw)

    print(f"[dashboard] Generando dashboard para {fecha_str} …")
    img_bytes = build_premarket_dashboard(indicators)

    out_path = out / f"dashboard_{fecha_str}.png"
    out_path.write_bytes(img_bytes)
    print(f"[dashboard] Guardado → {out_path}  ({len(img_bytes)//1024} KB)")

    if args.show:
        import subprocess
        subprocess.Popen(["explorer", str(out_path)], shell=True)

    if args.telegram:
        try:
            sys.path.insert(0, str(Path(__file__).parent))
            from notify_telegram import send_telegram_photo
            caption = f"SPX Dealer Flow — {fecha_str}"
            send_telegram_photo(img_bytes, caption)
            print("[dashboard] Enviado a Telegram ✓")
        except Exception as e:
            print(f"[ERROR] Telegram: {e}", file=sys.stderr)
