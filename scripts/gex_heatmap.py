"""
Dashboard GEX 0DTE y heatmap de evolución intraday.

Uso:
    uv run python scripts/gex_heatmap.py              # dashboard ASCII terminal
    uv run python scripts/gex_heatmap.py --telegram   # heatmap imagen → Telegram
    uv run python scripts/gex_heatmap.py --telegram --date 2026-04-28
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date as date_cls, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

ET = ZoneInfo("America/New_York")

HEATMAP_DPI    = 150
HEATMAP_SIZE   = (12, 8)
HEATMAP_CMAP   = "RdYlGn"
N_STRIKES_SHOW = 30
_TERM_WIDTH    = 70


# ── Dashboard ASCII ──────────────────────────────────────────────────────────

def print_gex_terminal(snapshot: dict) -> None:
    """Imprime el dashboard ASCII del perfil GEX en el terminal."""
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    spot          = snapshot.get("spot") or 0.0
    es_basis      = snapshot.get("es_basis")
    net_gex_bn    = snapshot.get("net_gex_bn")
    signal_gex    = snapshot.get("signal_gex", "N/A")
    regime_text   = snapshot.get("regime_text", "")
    flip_level    = snapshot.get("flip_level")
    control_node  = snapshot.get("control_node")
    chop_low      = snapshot.get("chop_zone_low")
    chop_high     = snapshot.get("chop_zone_high")
    put_wall      = snapshot.get("put_wall")
    call_wall     = snapshot.get("call_wall")
    gex_by_strike     = snapshot.get("gex_by_strike", {})
    gex_pct_by_strike = snapshot.get("gex_pct_by_strike", {})
    ts_et = snapshot.get("ts_et", "")

    def _es(v: float | None) -> str:
        """Equivalente /ES entre paréntesis."""
        if v is None or es_basis is None:
            return ""
        return f"  (~ES {int(round(v * es_basis))})"

    # Timestamp: "04/29/26 14:32 ET"
    try:
        ts_display = datetime.fromisoformat(ts_et).strftime("%m/%d/%y %H:%M")
    except Exception:
        ts_display = ts_et[:16].replace("T", " ") if ts_et else "N/A"

    net_str = f"${net_gex_bn * 1000:+.1f}M" if net_gex_bn is not None else "N/A"

    # Select 25 strikes closest to spot, display descending
    all_strikes = sorted(gex_by_strike.keys(), key=float)
    closest = sorted(all_strikes, key=lambda s: abs(float(s) - spot))[:25]
    strikes = sorted(closest, key=float, reverse=True)

    # Nearest strike to spot (for ▶ marker)
    nearest_key = min(strikes, key=lambda s: abs(float(s) - spot)) if strikes else None

    # Labels per strike key (str(int(strike))) — incluyen equivalente /ES si hay basis
    special: dict[str, str] = {}
    if call_wall is not None:
        special[str(int(call_wall))] = f"Call Wall{_es(call_wall)}"
    if put_wall is not None:
        special[str(int(put_wall))] = f"Put Wall{_es(put_wall)}"
    if control_node is not None:
        special[str(int(control_node))] = f"Control Node *{_es(control_node)}"

    es_spot_str = f"  /  ES {int(round(spot * es_basis))}" if es_basis else ""

    W = _TERM_WIDTH
    print("═" * W)
    print(f"  GEX 0DTE  |  SPX {spot:.0f}{es_spot_str}  |  {ts_display} ET")
    print(f"  Net GEX: {net_str}  →  {signal_gex}")
    if regime_text:
        print(f"  {regime_text}")
    print("─" * W)
    print(f"  {'Strike':<8}  {'GEX ($M)':>10}  {'%':>5}  {'Barra'}")
    print("─" * W)

    chop_sep_done = False

    for sk in strikes:
        s_float = float(sk)
        s_int   = str(int(s_float))

        # Insert chop zone separator when we first drop into the chop zone from above
        if (chop_high is not None and chop_low is not None
                and not chop_sep_done and s_float <= chop_high):
            chop_sep_done = True
            sep = f"·· CHOP ZONE [{int(chop_low)}–{int(chop_high)}] ··"
            print(f"  {sep:^{W - 4}}")

        gex_m  = float(gex_by_strike.get(sk, 0)) * 1000  # billions → millions
        pct    = float(gex_pct_by_strike.get(sk, 0))
        bars   = min(20, int(abs(pct) / 5))
        bar    = "█" * bars

        prefix = "●" if s_int == (str(int(control_node)) if control_node is not None else None) \
                 else ("▶" if sk == nearest_key else " ")

        m_sign   = "+" if gex_m >= 0 else "−"
        pct_sign = "+" if pct >= 0 else "−"

        label = f"  ← {special[s_int]}" if s_int in special else ""

        print(
            f"{prefix} {int(s_float):<6}  {m_sign}{abs(gex_m):>8.1f}M  "
            f"{pct_sign}{abs(pct):>4.0f}%  {bar}{label}"
        )

    print("─" * W)
    legend = "  ▶ = precio actual"
    if control_node is not None:
        legend += "   ● = Control Node   * = máx. neg. absoluto"
    print(legend)
    print("═" * W)


# ── Heatmap imagen ───────────────────────────────────────────────────────────

def _plot_line(ax, xs: list, ys: list, color: str, lw: float, ls: str, label: str) -> None:
    """Dibuja una línea con gaps donde ys es None."""
    segs_x: list[list] = []
    segs_y: list[list] = []
    seg_x: list = []
    seg_y: list = []
    for x, y in zip(xs, ys):
        if y is None:
            if seg_x:
                segs_x.append(seg_x)
                segs_y.append(seg_y)
                seg_x, seg_y = [], []
        else:
            seg_x.append(x)
            seg_y.append(y)
    if seg_x:
        segs_x.append(seg_x)
        segs_y.append(seg_y)

    for i, (sx, sy) in enumerate(zip(segs_x, segs_y)):
        ax.plot(sx, sy, color=color, linewidth=lw, linestyle=ls,
                label=label if i == 0 else None, alpha=0.85)


def build_gex_heatmap(snapshots: list[dict]) -> bytes:
    """
    Genera el heatmap GEX como imagen PNG en memoria.

    Un snapshot → gráfico de barras horizontales.
    Múltiples snapshots → heatmap de evolución temporal.

    Returns bytes del PNG (listo para enviar a Telegram).
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from io import BytesIO

    if not snapshots:
        raise ValueError("Sin snapshots para renderizar")

    last = snapshots[-1]
    last_spot = last.get("spot") or 0.0

    # Strikes a mostrar: los N_STRIKES_SHOW más cercanos al último spot
    all_strikes: set[str] = set()
    for snap in snapshots:
        all_strikes.update(snap.get("gex_by_strike", {}).keys())
    strikes_nearby = sorted(
        sorted(all_strikes, key=float),
        key=lambda s: abs(float(s) - last_spot),
    )[:N_STRIKES_SHOW]
    strikes_display = sorted(strikes_nearby, key=float)  # ascendente para eje Y

    BG    = "#1a1a2e"
    PANEL = "#16213e"

    def _y_idx(val: float | None) -> float | None:
        if val is None:
            return None
        vals = [float(s) for s in strikes_display]
        return min(range(len(vals)), key=lambda i: abs(vals[i] - val))

    if len(snapshots) == 1:
        # ── Modo barras horizontales ──────────────────────────────────────
        snap   = snapshots[0]
        gex    = snap.get("gex_by_strike", {})
        values = [float(gex.get(s, 0)) * 1000 for s in strikes_display]
        colors = ["#d73027" if v < 0 else "#1a9850" for v in values]

        fig, ax = plt.subplots(figsize=HEATMAP_SIZE, dpi=HEATMAP_DPI, facecolor=BG)
        ax.set_facecolor(PANEL)

        y_pos = list(range(len(strikes_display)))
        ax.barh(y_pos, values, color=colors, alpha=0.85)
        ax.set_yticks(y_pos)
        ax.set_yticklabels([str(int(float(s))) for s in strikes_display],
                           color="white", fontsize=8)
        ax.set_xlabel("GEX ($M)", color="white")
        ax.tick_params(colors="white")
        for spine in ax.spines.values():
            spine.set_color("#444")
        ax.axvline(0, color="white", linewidth=0.5)

        # Overlays
        flip      = snap.get("flip_level")
        cn        = snap.get("control_node")
        spot      = snap.get("spot")
        chop_low  = snap.get("chop_zone_low")
        chop_high = snap.get("chop_zone_high")

        if flip is not None:
            fi = _y_idx(flip)
            if fi is not None:
                ax.axhline(fi, color="yellow", lw=1.5, ls="--",
                           label=f"Flip {int(flip)}", alpha=0.85)
        if cn is not None:
            ci = _y_idx(cn)
            if ci is not None:
                ax.axhline(ci, color="orange", lw=1.5, ls="--",
                           label=f"CN {int(cn)}", alpha=0.85)
        if spot is not None:
            si = _y_idx(spot)
            if si is not None:
                ax.axhline(si, color="white", lw=2,
                           label=f"Spot {int(spot)}", alpha=0.9)
        if chop_low is not None and chop_high is not None:
            yl = _y_idx(chop_low)
            yh = _y_idx(chop_high)
            if yl is not None and yh is not None:
                ax.axhspan(yl - 0.5, yh + 0.5, color="royalblue",
                           alpha=0.15, label="Chop Zone")

        ax.legend(loc="lower right", facecolor=BG, labelcolor="white", fontsize=8)

        net    = snap.get("net_gex_bn")
        signal = snap.get("signal_gex", "N/A")
        fecha  = (snap.get("ts_et") or "")[:10]
        ax.set_title(f"GEX 0DTE — SPX {fecha}", color="white", pad=10)
        footer = (f"Net GEX: {net:+.2f}B | {signal}" if net is not None else signal)
        fig.text(0.5, 0.01, footer, ha="center", color="lightgray", fontsize=9)

    else:
        # ── Modo heatmap temporal ─────────────────────────────────────────
        n_rows = len(strikes_display)
        n_cols = len(snapshots)
        matrix = np.zeros((n_rows, n_cols))
        for col, snap in enumerate(snapshots):
            gex = snap.get("gex_by_strike", {})
            for row, sk in enumerate(strikes_display):
                matrix[row, col] = float(gex.get(sk, 0)) * 1000

        max_abs      = float(np.max(np.abs(matrix))) or 1.0
        matrix_norm  = matrix / max_abs

        fig, ax = plt.subplots(figsize=HEATMAP_SIZE, dpi=HEATMAP_DPI, facecolor=BG)
        ax.set_facecolor(PANEL)

        cmap = plt.get_cmap(HEATMAP_CMAP)
        img  = ax.imshow(
            matrix_norm, aspect="auto", cmap=cmap,
            vmin=-1, vmax=1, origin="lower",
            extent=[-0.5, n_cols - 0.5, -0.5, n_rows - 0.5],
        )
        plt.colorbar(img, ax=ax, label="GEX (normalizado)", fraction=0.04, pad=0.01)

        ytick_step = max(1, n_rows // 10)
        ax.set_yticks(range(0, n_rows, ytick_step))
        ax.set_yticklabels(
            [str(int(float(strikes_display[i]))) for i in range(0, n_rows, ytick_step)],
            color="white", fontsize=8,
        )

        xtick_step = max(1, n_cols // 8)
        ax.set_xticks(range(0, n_cols, xtick_step))
        ax.set_xticklabels(
            [(snapshots[i].get("ts") or "")[-8:-3] for i in range(0, n_cols, xtick_step)],
            color="white", fontsize=8, rotation=30,
        )
        ax.tick_params(colors="white")
        for spine in ax.spines.values():
            spine.set_color("#444")
        ax.set_xlabel("Tiempo ET", color="white")
        ax.set_ylabel("Strike", color="white")

        xs       = list(range(n_cols))
        spot_ys  = [_y_idx(s.get("spot"))         for s in snapshots]
        flip_ys  = [_y_idx(s.get("flip_level"))   for s in snapshots]
        cn_ys    = [_y_idx(s.get("control_node")) for s in snapshots]

        _plot_line(ax, xs, spot_ys, "white",  2.0, "-",  "Spot")
        _plot_line(ax, xs, flip_ys, "yellow", 1.5, "--", "Flip")
        _plot_line(ax, xs, cn_ys,   "orange", 1.5, "--", "CN")

        # Banda chop zone columna a columna
        for col, snap in enumerate(snapshots):
            cl = snap.get("chop_zone_low")
            ch = snap.get("chop_zone_high")
            yl = _y_idx(cl)
            yh = _y_idx(ch)
            if yl is not None and yh is not None:
                ax.fill_betweenx(
                    [yl - 0.5, yh + 0.5], col - 0.5, col + 0.5,
                    color="royalblue", alpha=0.15,
                )

        ax.legend(loc="upper right", facecolor=BG, labelcolor="white", fontsize=8)

        fecha  = (last.get("ts_et") or "")[:10]
        net    = last.get("net_gex_bn")
        signal = last.get("signal_gex", "N/A")
        regime = last.get("regime_text", "")
        ax.set_title(f"GEX 0DTE — SPX {fecha} | {n_cols} snapshots",
                     color="white", pad=10)
        footer = (
            f"Net GEX: {net:+.2f}B | {signal} | {regime}"
            if net is not None else f"{signal} | {regime}"
        )
        fig.text(0.5, 0.01, footer, ha="center", color="lightgray", fontsize=9)

    fig.patch.set_facecolor(BG)
    plt.tight_layout(rect=[0, 0.04, 1, 1])

    from io import BytesIO
    buf = BytesIO()
    plt.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def send_heatmap_telegram(img_bytes: bytes, caption: str) -> None:
    """Envía la imagen PNG a Telegram usando las credenciales de notify_telegram."""
    from scripts.notify_telegram import send_telegram_photo
    send_telegram_photo(img_bytes, caption)


# ── Carga de datos ───────────────────────────────────────────────────────────

def _load_source(date: str | None = None) -> tuple[list[dict], str]:
    """
    Carga snapshots GEX del día. Si no hay JSONL → lee indicators.json como snapshot único.
    Retorna (snapshots_ok, source_label).
    """
    from scripts.gex_intraday import load_snapshots

    date_str = date or date_cls.today().isoformat()
    raw = load_snapshots(date_str=date_str)
    ok  = [s for s in raw if s.get("status") == "OK"]
    if ok:
        return ok, f"intraday JSONL ({date_str})"

    # Fallback: indicators.json
    try:
        ind     = json.loads(Path("outputs/indicators.json").read_text(encoding="utf-8"))
        pre_ind = ind.get("premarket", ind)
        ng      = pre_ind.get("net_gex", {})
        spot    = pre_ind.get("spx_spot") or ng.get("spot")

        snap = {
            "ts":                datetime.now(ET).strftime("%Y-%m-%dT%H:%M:%S"),
            "ts_et":             datetime.now(ET).isoformat(),
            "spot":              float(spot) if spot is not None else None,
            "net_gex_bn":        ng.get("net_gex_bn"),
            "signal_gex":        ng.get("signal_gex"),
            "regime_text":       ng.get("regime_text", ""),
            "flip_level":        ng.get("flip_level"),
            "control_node":      ng.get("control_node"),
            "chop_zone_low":     ng.get("chop_zone_low"),
            "chop_zone_high":    ng.get("chop_zone_high"),
            "put_wall":          ng.get("put_wall"),
            "call_wall":         ng.get("call_wall"),
            "gex_by_strike":     ng.get("gex_by_strike", {}),
            "gex_pct_by_strike": ng.get("gex_pct_by_strike", {}),
            "n_strikes":         ng.get("n_strikes", 0),
            "status":            "OK",
        }
        if snap["gex_by_strike"]:
            return [snap], "indicators.json (premarket)"
    except Exception:
        pass

    return [], "ninguna"


# ── Entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Dashboard GEX 0DTE / Heatmap Telegram")
    parser.add_argument("--telegram", action="store_true",
                        help="Enviar imagen heatmap a Telegram en lugar de mostrar ASCII")
    parser.add_argument("--date", default=None, metavar="YYYY-MM-DD",
                        help="Fecha de los snapshots (default: hoy)")
    args = parser.parse_args()

    snapshots, source = _load_source(args.date)

    if not snapshots:
        print("Sin datos GEX disponibles.")
        return

    if args.telegram:
        img  = build_gex_heatmap(snapshots)
        last = snapshots[-1]
        net  = last.get("net_gex_bn")
        cap  = (
            f"📊 GEX 0DTE — SPX {(last.get('ts_et') or '')[:10]}\n"
            f"Net GEX: {net:+.2f}B | {last.get('signal_gex', 'N/A')}\n"
            f"{last.get('regime_text', '')}\n\n"
        )
        flip     = last.get("flip_level")
        cn       = last.get("control_node")
        pw       = last.get("put_wall")
        cw       = last.get("call_wall")
        cl       = last.get("chop_zone_low")
        ch       = last.get("chop_zone_high")
        basis    = last.get("es_basis")

        def _cap_es(v):
            return f" (~ES {int(round(v * basis))})" if (v is not None and basis) else ""

        if flip is not None:
            cap += f"🎯 Flip:      SPX {int(flip)}{_cap_es(flip)}\n"
        if cn is not None:
            cap += f"🔴 Control:   SPX {int(cn)}{_cap_es(cn)}\n"
        if pw is not None:
            cap += f"🟢 Put Wall:  SPX {int(pw)}{_cap_es(pw)}\n"
        if cw is not None:
            cap += f"🔴 Call Wall: SPX {int(cw)}{_cap_es(cw)}\n"
        if cl is not None and ch is not None:
            cap += f"🔀 Chop Zone: SPX {int(cl)}–{int(ch)}\n"
        n   = len(snapshots)
        ts0 = (snapshots[0].get("ts") or "")[-8:-3]
        ts1 = (last.get("ts") or "")[-8:-3]
        cap += f"\n{n} snapshots | {ts0}–{ts1} ET"
        cap = cap[:1024]  # Telegram caption limit

        send_heatmap_telegram(img, cap)
        print(f"Heatmap enviado a Telegram ({n} snapshots, fuente: {source})")
    else:
        print_gex_terminal(snapshots[-1])


if __name__ == "__main__":
    main()
