#!/usr/bin/env python3
"""
Notificación Telegram para el análisis premarket SPX 0DTE.
Lee outputs/indicators.json y envía el mensaje con formato MarkdownV2 fijo.

Uso:
  uv run python scripts/notify_telegram.py --phase premarket
  uv run python scripts/notify_telegram.py --phase open [--window 30]
"""
import argparse
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(usecwd=True, raise_error_if_not_found=False))

INDICATORS_PATH = Path("outputs/indicators.json")
TELEGRAM_API    = "https://api.telegram.org/bot{token}/sendMessage"

# Mapeo determinista señal → emoji. Misma señal, mismo emoji siempre.
SIGNAL_EMOJI: dict[str, str] = {
    # D-Score premarket
    "CONTANGO_FUERTE":        "🟢",
    "CONTANGO_SUAVE":         "🟡",
    "NEUTRO":                 "⚪",
    "TENSION":                "🟠",
    "BACKWARDATION":          "🔴",
    "GAP_ALCISTA_GRANDE":     "🟢",
    "GAP_ALCISTA":            "🟢",
    "PLANO":                  "⚪",
    "GAP_BAJISTA":            "🔴",
    "GAP_BAJISTA_GRANDE":     "🔴",
    "LONG_GAMMA_FUERTE":      "🟢",
    "LONG_GAMMA_SUAVE":       "🟡",
    "SHORT_GAMMA_SUAVE":      "🟠",
    "SHORT_GAMMA_FUERTE":     "🔴",
    "SOBRE_FLIP":             "🟢",
    "SIN_FLIP":               "⚪",
    "BAJO_FLIP":              "🔴",
    # V-Score premarket
    "PRIMA_ALTA":             "🟢",
    "PRIMA_ELEVADA":          "🟢",
    "PRIMA_NORMAL":           "🟡",
    "PRIMA_BAJA":             "⚪",
    "PRIMA_MUY_BAJA":         "🔴",
    "CONTRACCION_FUERTE":     "🟢",
    "CONTRACCION_SUAVE":      "🟡",
    "EXPANSION_SUAVE":        "🟠",
    "EXPANSION_FUERTE":       "🔴",
    # Open phase
    "SESGO_ALCISTA":          "🟢",
    "SESGO_BAJISTA":          "🔴",
    "IV_COMPRIMIENDO":        "🟢",
    "IV_EXPANDIENDO":         "🔴",
    "EXPANSION_BAJA":         "🟢",
    "EXPANSION_ALTA":         "🔴",
    "GAP_ALCISTA_MANTENIDO":  "🟢",
    "GAP_ALCISTA_PARCIAL":    "🟡",
    "GAP_ALCISTA_RELLENO":    "⚪",
    "GAP_BAJISTA_MANTENIDO":  "🔴",
    "GAP_BAJISTA_PARCIAL":    "🟠",
    "GAP_BAJISTA_RELLENO":    "⚪",
    "GAP_INSIGNIFICANTE":     "⚪",
    "PRIMA_SOBREVALORADA":    "🟢",
    "PRIMA_INFRAVALORADA":    "🔴",
}

# Detalles de ejecución por estrategia (orientativos — validar con cadena SPXW del día)
STRATEGY_DETAIL: dict[str, dict] = {
    "Put spread OTM agresivo": {
        "delta_short":    "~0.20",
        "ancho_pts":      25,
        "guidance_short": "~25-30 pts OTM (puts)",
        "guidance_long":  "comprar 25 pts debajo del short",
        "risk_profile":   "Agresivo — crédito mayor, riesgo mayor",
        "emoji_short":    "🟢",
        "emoji_long":     "🛡️",
    },
    "Put spread OTM conservador": {
        "delta_short":    "~0.12",
        "ancho_pts":      15,
        "guidance_short": "~35-40 pts OTM (puts)",
        "guidance_long":  "comprar 15 pts debajo del short",
        "risk_profile":   "Conservador — menor crédito, mayor seguridad",
        "emoji_short":    "🟢",
        "emoji_long":     "🛡️",
    },
    "Call spread OTM agresivo": {
        "delta_short":    "~0.20",
        "ancho_pts":      25,
        "guidance_short": "~25-30 pts OTM (calls)",
        "guidance_long":  "comprar 25 pts arriba del short",
        "risk_profile":   "Agresivo — crédito mayor, riesgo mayor",
        "emoji_short":    "🔴",
        "emoji_long":     "🛡️",
    },
    "Call spread OTM conservador": {
        "delta_short":    "~0.12",
        "ancho_pts":      15,
        "guidance_short": "~35-40 pts OTM (calls)",
        "guidance_long":  "comprar 15 pts arriba del short",
        "risk_profile":   "Conservador — menor crédito, mayor seguridad",
        "emoji_short":    "🔴",
        "emoji_long":     "🛡️",
    },
    "Iron condor amplio": {
        "delta_short":    "~0.15",
        "ancho_pts":      25,
        "guidance_short": "~30 pts OTM cada lado",
        "guidance_long":  "ancho 25 pts cada lado",
        "risk_profile":   "Amplio — mayor colateral, menor prob. touch",
        "emoji_short":    "🔴🟢",
        "emoji_long":     "🛡️",
    },
    "Iron condor estrecho": {
        "delta_short":    "~0.10",
        "ancho_pts":      15,
        "guidance_short": "~40 pts OTM cada lado",
        "guidance_long":  "ancho 15 pts cada lado",
        "risk_profile":   "Estrecho — menor colateral, crédito neto menor",
        "emoji_short":    "🔴🟢",
        "emoji_long":     "🛡️",
    },
}

# Tabla de decisión (réplica de _interpret en generate_scorecard.py)
# Se replica para evitar dependencia interna y posibles imports circulares.
def _interpret(d_score: int, v_score: int) -> tuple[str, str]:
    if d_score >= 5:
        if v_score >= 3:
            return "Tendencia alcista + vol alta", "Put spread OTM agresivo"
        return "Tendencia alcista + vol baja", "Put spread OTM conservador"
    elif d_score <= -5:
        if v_score >= 3:
            return "Tendencia bajista + vol alta", "Call spread OTM agresivo"
        return "Tendencia bajista + vol baja", "Call spread OTM conservador"
    else:
        if v_score >= 3:
            return "Rango + vol alta", "Iron condor amplio"
        return "Rango + vol baja", "Iron condor estrecho"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _sign(n) -> str:
    """Formatea número con signo explícito (+N / -N)."""
    try:
        v = int(float(n))
        return f"+{v}" if v >= 0 else str(v)
    except (TypeError, ValueError):
        return "0"


def _fmt(v, fmt: str = ".2f", fallback: str = "N/D") -> str:
    """Formatea float o devuelve fallback si None."""
    if v is None:
        return fallback
    try:
        return format(float(v), fmt)
    except (TypeError, ValueError):
        return fallback


def _emoji(signal: str) -> str:
    return SIGNAL_EMOJI.get(signal, "⚪")


def _esc(text) -> str:
    """Escapa caracteres especiales para MarkdownV2 de Telegram."""
    special = r"_[]()~`>#+-=|{}.!"
    result = ""
    for ch in str(text):
        result += f"\\{ch}" if ch in special else ch
    return result


# ── Builders de mensaje ───────────────────────────────────────────────────────

def build_premarket_message(indicators: dict) -> str:
    """Construye el mensaje MarkdownV2 para la fase premarket. Formato fijo."""
    data    = indicators.get("premarket", indicators)
    fecha   = indicators.get("fecha", data.get("fecha", "N/A"))
    slope   = data.get("vix_vxv_slope", {})
    ratio   = data.get("vix9d_vix_ratio", {})
    gap     = data.get("overnight_gap", {})
    ivr     = data.get("ivr", {})
    atr     = data.get("atr_ratio", {})
    gex     = data.get("net_gex", {})
    d_score = data.get("d_score", 0)
    v_score = data.get("v_score", 0)

    def _ind_val(d: dict, ok_fn):
        return ok_fn() if d.get("status") == "OK" else f"\\[{_esc(d.get('status', 'ERROR'))}\\]"

    slope_val = _ind_val(slope, lambda: f"VIX\\={_esc(slope.get('vix'))}  VXV\\={_esc(slope.get('vxv'))}")
    ratio_val = _ind_val(ratio, lambda: f"VIX9D\\={_esc(ratio.get('vix9d'))}  VIX\\={_esc(ratio.get('vix'))}")
    gap_val   = _ind_val(gap,   lambda: f"{_esc(_fmt(gap.get('gap_pct'), '+.2f'))}%")
    gex_val   = _ind_val(gex,   lambda: f"{_esc(_fmt(gex.get('net_gex_bn'), '+.2f'))}B")
    ivr_val   = _ind_val(ivr,   lambda: f"VIX\\={_esc(ivr.get('vix'))}  IVR\\={_esc(_fmt(ivr.get('ivr'), '.2f'))}%")
    atr_val   = _ind_val(atr,   lambda: f"{_esc(_fmt(atr.get('atr_ratio'), '.4f'))}")

    flip_level = gex.get("flip_level")
    if gex.get("status") == "OK" and flip_level is not None:
        flip_val = f"Flip\\={_esc(_fmt(flip_level, '.0f'))}  Spot\\={_esc(_fmt(gex.get('spot'), '.0f'))}"
    elif gex.get("status") == "OK":
        flip_val = "SIN\\_FLIP"
    else:
        flip_val = f"\\[{_esc(gex.get('status', 'ERROR'))}\\]"

    flip_disp = _esc(_fmt(flip_level, ".0f")) if flip_level is not None else "N/D"
    put_wall  = _esc(_fmt(gex.get("put_wall"),  ".0f"))
    call_wall = _esc(_fmt(gex.get("call_wall"), ".0f"))
    max_pain  = _esc(_fmt(gex.get("max_pain"),  ".0f"))

    lines = [
        f"📊 *SPX 0DTE — Premarket* \\| {_esc(fecha)}",
        "",
        f"━━━ D\\-Score \\({_esc(_sign(d_score))}\\) ━━━━━━━━━━━━━━━━━━━",
        f"{_emoji(slope.get('signal',''))} VIX/VXV Slope:   {slope_val}  →  {_esc(slope.get('signal','N/A'))} \\({_esc(_sign(slope.get('score',0)))}\\)",
        f"{_emoji(ratio.get('signal',''))} VIX9D/VIX:       {ratio_val}  →  {_esc(ratio.get('signal','N/A'))} \\({_esc(_sign(ratio.get('score',0)))}\\)",
        f"{_emoji(gap.get('signal',''))}   Gap nocturno:    {gap_val}  →  {_esc(gap.get('signal','N/A'))} \\({_esc(_sign(gap.get('score',0)))}\\)",
        f"{_emoji(gex.get('signal_gex',''))}   Net GEX:         {gex_val}  →  {_esc(gex.get('signal_gex','N/A'))} \\({_esc(_sign(gex.get('score_gex',0)))}\\)",
        f"{_emoji(gex.get('signal_flip',''))}  Flip Level:      {flip_val}  →  {_esc(gex.get('signal_flip','N/A'))} \\({_esc(_sign(gex.get('score_flip',0)))}\\)",
        "",
        f"━━━ V\\-Score \\({_esc(_sign(v_score))}\\) ━━━━━━━━━━━━━━━━━━━",
        f"{_emoji(ivr.get('signal',''))}   IV Rank \\(IVR\\):  {ivr_val}  →  {_esc(ivr.get('signal','N/A'))} \\({_esc(_sign(ivr.get('score',0)))}\\)",
        f"{_emoji(atr.get('signal',''))}   ATR Ratio:       {atr_val}  →  {_esc(atr.get('signal','N/A'))} \\({_esc(_sign(atr.get('score',0)))}\\)",
        "",
        "━━━ Niveles Clave ━━━━━━━━━━━━━━━━━━━━",
        f"🎯 Flip:      {flip_disp}",
        f"🟢 Put Wall:  {put_wall}",
        f"🔴 Call Wall: {call_wall}",
        f"⚡ Max Pain:  {max_pain}",
        "",
        "⚠️ _Scorecard orientativo — aguardar Open Phase a las 10:15 ET_",
    ]
    return "\n".join(lines)


def build_open_message(indicators: dict, window: int = 30) -> str:
    """Construye el mensaje MarkdownV2 para la fase open/combinada. Formato fijo."""
    pre   = indicators.get("premarket", {})
    open_ = indicators.get("open", {})
    fecha = indicators.get("fecha", pre.get("fecha", "N/A"))

    slope = pre.get("vix_vxv_slope", {})
    ratio = pre.get("vix9d_vix_ratio", {})
    gap   = pre.get("overnight_gap", {})
    ivr   = pre.get("ivr", {})
    atr   = pre.get("atr_ratio", {})
    gex   = pre.get("net_gex", {})
    d_pre = pre.get("d_score", 0)
    v_pre = pre.get("v_score", 0)

    vwap    = open_.get("vwap_position", {})
    gap_beh = open_.get("gap_behavior", {})
    vix_d   = open_.get("vix_delta_open", {})
    range_e = open_.get("range_expansion", {})
    rv_open = open_.get("realized_vol_open", {})
    d_open  = open_.get("d_score", 0)
    v_open  = open_.get("v_score", 0)

    d_total = d_pre + d_open
    v_total = v_pre + v_open
    regimen, estrategia = _interpret(d_total, v_total)

    detail = STRATEGY_DETAIL.get(estrategia, {
        "delta_short": "N/D", "ancho_pts": "N/D",
        "guidance_short": "N/D", "guidance_long": "N/D",
        "risk_profile": "N/D", "emoji_short": "⚪", "emoji_long": "🛡️",
    })

    flip_level = gex.get("flip_level")
    flip_disp  = _esc(_fmt(flip_level, ".0f")) if flip_level is not None else "N/D"
    put_wall   = _esc(_fmt(gex.get("put_wall"),  ".0f"))
    call_wall  = _esc(_fmt(gex.get("call_wall"), ".0f"))
    max_pain   = _esc(_fmt(gex.get("max_pain"),  ".0f"))

    def _open_row(d: dict, label: str, val_key: str, fmt_str: str,
                  signal_key: str, score_key: str) -> str:
        if d.get("status") == "OK":
            val = _esc(_fmt(d.get(val_key), fmt_str))
        else:
            val = f"\\[{_esc(d.get('status', 'ERROR'))}\\]"
        sig   = _esc(d.get(signal_key, "N/A"))
        score = _esc(_sign(d.get(score_key, 0)))
        return f"{_emoji(d.get(signal_key,''))} {label}: {val}  →  {sig} \\({score}\\)"

    lines = [
        f"📊 *SPX 0DTE — Análisis Final* \\| {_esc(fecha)}",
        "",
        f"━━━ Premarket: D={_esc(_sign(d_pre))} \\| V={_esc(_sign(v_pre))} ━━━━━━━━━",
        (f"{_emoji(slope.get('signal',''))} Slope: {_esc(slope.get('signal','N/A'))} \\({_esc(_sign(slope.get('score',0)))}\\)"
         f"   ·  {_emoji(ratio.get('signal',''))} Ratio: {_esc(ratio.get('signal','N/A'))} \\({_esc(_sign(ratio.get('score',0)))}\\)"),
        (f"{_emoji(gap.get('signal',''))}   Gap:   {_esc(gap.get('signal','N/A'))} \\({_esc(_sign(gap.get('score',0)))}\\)"
         f"    ·  {_emoji(gex.get('signal_gex',''))}  GEX:   {_esc(gex.get('signal_gex','N/A'))} \\({_esc(_sign(gex.get('score_gex',0)))}\\)"),
        (f"{_emoji(gex.get('signal_flip',''))}  Flip:  {_esc(gex.get('signal_flip','N/A'))} \\({_esc(_sign(gex.get('score_flip',0)))}\\)"
         f"   ·  {_emoji(ivr.get('signal',''))}  IVR:   {_esc(ivr.get('signal','N/A'))} \\({_esc(_sign(ivr.get('score',0)))}\\)"),
        f"{_emoji(atr.get('signal',''))}   ATR:   {_esc(atr.get('signal','N/A'))} \\({_esc(_sign(atr.get('score',0)))}\\)",
        "",
        f"━━━ Open Phase \\({_esc(str(window))}min\\): D={_esc(_sign(d_open))} \\| V={_esc(_sign(v_open))} ━━━",
        _open_row(vwap,    "VWAP        ", "value",       ".4f",  "signal", "score"),
        _open_row(gap_beh, "Gap Behavior", "gap_fill_pct", ".1f", "signal", "score"),
        _open_row(vix_d,   "VIX Delta   ", "vix_delta",   "+.2f", "signal", "score"),
        _open_row(range_e, "Range Exp   ", "ratio",        ".4f", "signal", "score"),
        _open_row(rv_open, "Realized Vol", "rv_ratio",     ".4f", "signal", "score"),
        "",
        "━━━ DECISIÓN FINAL ━━━━━━━━━━━━━━━━━━━",
        f"D\\-total: *{_esc(_sign(d_total))}*   V\\-total: *{_esc(_sign(v_total))}*",
        f"Régimen: _{_esc(regimen)}_",
        "",
        f"🎯 *Estrategia: {_esc(estrategia)}*",
        "",
        "━━━ Ejecución ━━━━━━━━━━━━━━━━━━━━━━━",
        f"{detail['emoji_short']} Short leg: Delta {_esc(detail['delta_short'])}  \\({_esc(detail['guidance_short'])}\\)",
        f"{detail['emoji_long']}  Long leg:  {_esc(detail['guidance_long'])}",
        f"📐 Ancho spread: {_esc(str(detail['ancho_pts']))} pts",
        f"⚖️ Perfil: {_esc(detail['risk_profile'])}",
        "",
        "━━━ Niveles ━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🎯 Flip:      {flip_disp}",
        f"🟢 Put Wall:  {put_wall}",
        f"🔴 Call Wall: {call_wall}",
        f"⚡ Max Pain:  {max_pain}",
    ]
    return "\n".join(lines)


# ── Envío ─────────────────────────────────────────────────────────────────────

def send_telegram(message: str) -> bool:
    """Envía mensaje a Telegram. Devuelve True si exitoso."""
    token   = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print(
            "[notify] ERROR: TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID no configurados en .env",
            file=sys.stderr,
        )
        return False
    url  = TELEGRAM_API.format(token=token)
    resp = httpx.post(
        url,
        json={"chat_id": chat_id, "text": message, "parse_mode": "MarkdownV2"},
        timeout=10,
    )
    if not resp.is_success:
        print(f"[notify] ERROR Telegram {resp.status_code}: {resp.text}", file=sys.stderr)
        return False
    return True


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Notificación Telegram premarket SPX 0DTE")
    parser.add_argument("--phase", choices=["premarket", "open"], required=True,
                        help="Fase del pipeline cuyo resultado enviar")
    parser.add_argument("--window", type=int, default=30,
                        help="Minutos de ventana open phase (default: 30)")
    args = parser.parse_args()

    if not INDICATORS_PATH.exists():
        print(
            f"[notify] ERROR: {INDICATORS_PATH} no existe — ejecutar el pipeline primero",
            file=sys.stderr,
        )
        sys.exit(1)

    indicators = json.loads(INDICATORS_PATH.read_text(encoding="utf-8"))

    if args.phase == "premarket":
        message = build_premarket_message(indicators)
    else:
        message = build_open_message(indicators, args.window)

    ok = send_telegram(message)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
