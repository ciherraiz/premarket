# Spec: Skill /premarket-analysis + Sistema de Notificaciones Telegram

## Estado
[Development]

## Propósito

Definir el skill de Claude Code `/premarket-analysis` y el sistema de notificaciones
automáticas vía Telegram para el análisis premarket del SPX 0DTE.

El skill orquesta la ejecución del pipeline completo y el envío determinista
de mensajes a Telegram. Los mensajes tienen **formato fijo**: cada campo aparece
en posición exacta, mismos emojis, misma estructura, todos los días.
`notify_telegram.py` es el único responsable del formato — Claude no genera
ni modifica el texto del mensaje Telegram.

---

## Arquitectura

```
/premarket-analysis [--phase premarket|open] [--window N]
        │
        └─ uv run python scripts/run.py --phase <fase> [--window N] --notify
                │
                ├─ run_premarket_phase() / run_open_phase()
                ├─ print_scorecard() / print_combined_scorecard()  → terminal
                └─ _call_notify(phase, window)
                            │
                            └─ sys.executable scripts/notify_telegram.py --phase <fase>
                                        │
                                        ├─ Lee outputs/indicators.json
                                        ├─ Formatea mensaje (plantilla fija MarkdownV2)
                                        └─ POST api.telegram.org/bot<TOKEN>/sendMessage

Tareas programadas:
  09:10 ET (L-V) → --phase premarket --notify  →  Mensaje 1 (orientativo)
  10:15 ET (L-V) → --phase open --window 30 --notify  →  Mensaje 2 (decisión final)
```

`notify_telegram.py` es **stateless**: solo lee `indicators.json` y envía.
No calcula nada. La notificación es best-effort — si falla, el pipeline no aborta.

---

## Variables de entorno (.env)

| Variable | Descripción |
|---|---|
| `TASTYTRADE_USERNAME` | Ya existente |
| `TASTYTRADE_PASSWORD` | Ya existente |
| `TELEGRAM_BOT_TOKEN` | Token del bot (obtener de @BotFather en Telegram) |
| `TELEGRAM_CHAT_ID` | ID del chat/canal destino (negativo si es canal) |

**Cómo obtener las credenciales Telegram:**
1. `TELEGRAM_BOT_TOKEN`: abrir Telegram → buscar @BotFather → `/newbot` → copiar el token
2. `TELEGRAM_CHAT_ID`: añadir el bot a tu canal/grupo → enviar un mensaje → llamar
   `https://api.telegram.org/bot<TOKEN>/getUpdates` → copiar `chat.id` del resultado

---

## Plantilla Telegram — Fase Premarket (09:10 ET)

Parse mode: `MarkdownV2`. Todos los valores dinámicos deben pasar por `_escape_md()`.
Los caracteres `_`, `*`, `[`, `]`, `(`, `)`, `~`, `` ` ``, `>`, `#`, `+`, `-`, `=`,
`|`, `{`, `}`, `.`, `!` se escapan con `\`.

```
📊 *SPX 0DTE — Premarket* | {FECHA}

━━━ D\-Score \({D_SCORE:+d}\) ━━━━━━━━━━━━━━━━━━━
{E_SLOPE} VIX/VXV Slope:   VIX={VIX}  VXV={VXV}  →  {SIGNAL_SLOPE} \({SCORE_SLOPE:+d}\)
{E_RATIO} VIX9D/VIX:       VIX9D={VIX9D}  VIX={VIX}  →  {SIGNAL_RATIO} \({SCORE_RATIO:+d}\)
{E_GAP}   Gap nocturno:    {GAP_PCT:+.2f}%  →  {SIGNAL_GAP} \({SCORE_GAP:+d}\)
{E_GEX}   Net GEX:         {GEX_BN:+.2f}B  →  {SIGNAL_GEX} \({SCORE_GEX:+d}\)
{E_FLIP}  Flip Level:      Flip={FLIP}  Spot={SPOT}  →  {SIGNAL_FLIP} \({SCORE_FLIP:+d}\)

━━━ V\-Score \({V_SCORE:+d}\) ━━━━━━━━━━━━━━━━━━━
{E_IVR}   IV Rank \(IVR\):  VIX={VIX}  IVR={IVR}%  →  {SIGNAL_IVR} \({SCORE_IVR:+d}\)
{E_ATR}   ATR Ratio:       {ATR_RATIO}  →  {SIGNAL_ATR} \({SCORE_ATR:+d}\)

━━━ Niveles Clave ━━━━━━━━━━━━━━━━━━━━
🎯 Flip:      {FLIP_LEVEL}
🟢 Put Wall:  {PUT_WALL}
🔴 Call Wall: {CALL_WALL}
⚡ Max Pain:  {MAX_PAIN}

⚠️ _Scorecard orientativo — aguardar Open Phase a las 10:15 ET_
```

### Manejo de datos faltantes (plantilla premarket)

- Si `status != "OK"` en cualquier indicador → sustituir el valor por `[ERROR]` o `[MISSING]`,
  mostrar score `(0)`.
- Si `flip_level` es `None` → mostrar `SIN_FLIP` en lugar de `Flip={FLIP} Spot={SPOT}`.
- Si `put_wall`, `call_wall` o `max_pain` son `None` → mostrar `N/D`.

---

## Plantilla Telegram — Fase Open / Combinada (10:15 ET)

```
📊 *SPX 0DTE — Análisis Final* | {FECHA}

━━━ Premarket: D={D_PRE:+d} \| V={V_PRE:+d} ━━━━━━━━━
{E_SLOPE} Slope: {SIGNAL_SLOPE} \({SCORE_SLOPE:+d}\)   ·  {E_RATIO} Ratio: {SIGNAL_RATIO} \({SCORE_RATIO:+d}\)
{E_GAP}   Gap:   {SIGNAL_GAP} \({SCORE_GAP:+d}\)    ·  {E_GEX}  GEX:   {SIGNAL_GEX} \({SCORE_GEX:+d}\)
{E_FLIP}  Flip:  {SIGNAL_FLIP} \({SCORE_FLIP:+d}\)   ·  {E_IVR}  IVR:   {SIGNAL_IVR} \({SCORE_IVR:+d}\)
{E_ATR}   ATR:   {SIGNAL_ATR} \({SCORE_ATR:+d}\)

━━━ Open Phase \({WINDOW}min\): D={D_OPEN:+d} \| V={V_OPEN:+d} ━━━
{E_VWAP}  VWAP:         {SIGNAL_VWAP} \({SCORE_VWAP:+d}\)
{E_GAPB}  Gap Behavior: {SIGNAL_GAP_BEH} \({SCORE_GAP_BEH:+d}\)
{E_VD}    VIX Delta:    {SIGNAL_VIX_DELTA} \({SCORE_VIX_DELTA:+d}\)
{E_RE}    Range Exp:    {SIGNAL_RANGE_EXP} \({SCORE_RANGE_EXP:+d}\)
{E_RV}    Realized Vol: {SIGNAL_RV} \({SCORE_RV:+d}\)

━━━ DECISIÓN FINAL ━━━━━━━━━━━━━━━━━━━
D\-total: *{D_TOTAL:+d}*   V\-total: *{V_TOTAL:+d}*
Régimen: _{REGIMEN}_

🎯 *Estrategia: {ESTRATEGIA}*

━━━ Ejecución ━━━━━━━━━━━━━━━━━━━━━━━
{E_SHORT} Short leg: Delta {DELTA_SHORT}  \({GUIDANCE_SHORT}\)
{E_LONG}  Long leg:  {GUIDANCE_LONG}
📐 Ancho spread: {ANCHO_PTS} pts
⚖️ Perfil: {RISK_PROFILE}

━━━ Niveles ━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 Flip:      {FLIP_LEVEL}
🟢 Put Wall:  {PUT_WALL}
🔴 Call Wall: {CALL_WALL}
⚡ Max Pain:  {MAX_PAIN}
```

---

## Tabla de emojis por señal (SIGNAL_EMOJI — determinista)

Mapeo completo señal → emoji. **No debe haber variación entre ejecuciones.**
Señales no reconocidas devuelven `⚪`.

| Señal | Emoji |
|---|---|
| CONTANGO_FUERTE | 🟢 |
| CONTANGO_SUAVE | 🟡 |
| NEUTRO | ⚪ |
| TENSION | 🟠 |
| BACKWARDATION | 🔴 |
| GAP_ALCISTA_GRANDE | 🟢 |
| GAP_ALCISTA | 🟢 |
| PLANO | ⚪ |
| GAP_BAJISTA | 🔴 |
| GAP_BAJISTA_GRANDE | 🔴 |
| LONG_GAMMA_FUERTE | 🟢 |
| LONG_GAMMA_SUAVE | 🟡 |
| SHORT_GAMMA_SUAVE | 🟠 |
| SHORT_GAMMA_FUERTE | 🔴 |
| SOBRE_FLIP | 🟢 |
| SIN_FLIP | ⚪ |
| BAJO_FLIP | 🔴 |
| PRIMA_ALTA | 🟢 |
| PRIMA_ELEVADA | 🟢 |
| PRIMA_NORMAL | 🟡 |
| PRIMA_BAJA | ⚪ |
| PRIMA_MUY_BAJA | 🔴 |
| CONTRACCION_FUERTE | 🟢 |
| CONTRACCION_SUAVE | 🟡 |
| EXPANSION_SUAVE | 🟠 |
| EXPANSION_FUERTE | 🔴 |
| SESGO_ALCISTA | 🟢 |
| SESGO_BAJISTA | 🔴 |
| IV_COMPRIMIENDO | 🟢 |
| IV_EXPANDIENDO | 🔴 |
| EXPANSION_BAJA | 🟢 |
| EXPANSION_ALTA | 🔴 |
| GAP_ALCISTA_MANTENIDO | 🟢 |
| GAP_ALCISTA_PARCIAL | 🟡 |
| GAP_ALCISTA_RELLENO | ⚪ |
| GAP_BAJISTA_MANTENIDO | 🔴 |
| GAP_BAJISTA_PARCIAL | 🟠 |
| GAP_BAJISTA_RELLENO | ⚪ |
| GAP_INSIGNIFICANTE | ⚪ |
| PRIMA_SOBREVALORADA | 🟢 |
| PRIMA_INFRAVALORADA | 🔴 |

---

## Lógica de estrategia expandida (STRATEGY_DETAIL)

La función `_interpret(d_score, v_score)` de `generate_scorecard.py` devuelve
`(regimen, estrategia)`. `notify_telegram.py` usa `STRATEGY_DETAIL[estrategia]`
para añadir orientación de ejecución. Los valores son **orientativos** — validar
siempre con la cadena SPXW del día.

| Estrategia | Delta short | Ancho | Guidance short | Guidance long | Perfil |
|---|---|---|---|---|---|
| Put spread OTM agresivo | ~0.20 | 25 pts | ~25-30 pts OTM (puts) | comprar 25 pts debajo del short | Agresivo — crédito mayor, riesgo mayor |
| Put spread OTM conservador | ~0.12 | 15 pts | ~35-40 pts OTM (puts) | comprar 15 pts debajo del short | Conservador — menor crédito, mayor seguridad |
| Call spread OTM agresivo | ~0.20 | 25 pts | ~25-30 pts OTM (calls) | comprar 25 pts arriba del short | Agresivo — crédito mayor, riesgo mayor |
| Call spread OTM conservador | ~0.12 | 15 pts | ~35-40 pts OTM (calls) | comprar 15 pts arriba del short | Conservador — menor crédito, mayor seguridad |
| Iron condor amplio | ~0.15 | 25 pts c/lado | ~30 pts OTM cada lado | ancho 25 pts cada lado | Amplio — mayor colateral, menor prob. touch |
| Iron condor estrecho | ~0.10 | 15 pts c/lado | ~40 pts OTM cada lado | ancho 15 pts cada lado | Estrecho — menor colateral, crédito neto menor |

Implementación como constante en `notify_telegram.py`:

```python
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
```

Si `estrategia` no está en `STRATEGY_DETAIL` (p.ej. estrategia nueva aún no mapeada),
usar fallback con todos los campos en `"N/D"`.

---

## Integración con run.py

### Nuevo argumento CLI

```python
parser.add_argument(
    "--notify",
    action="store_true",
    default=False,
    help="Enviar resultado a Telegram tras el pipeline (requiere TELEGRAM_BOT_TOKEN en .env)",
)
```

### Helper _call_notify

```python
def _call_notify(phase: str, window: int = 30) -> None:
    """Invoca notify_telegram.py como subprocess. Best-effort: no aborta el pipeline."""
    import subprocess
    notify_script = Path(__file__).parent / "notify_telegram.py"
    cmd = [sys.executable, str(notify_script), "--phase", phase]
    if phase == "open":
        cmd += ["--window", str(window)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"[notify] WARN: {result.stderr.strip()}", file=sys.stderr)
        else:
            print("[notify] Mensaje Telegram enviado.")
    except Exception as e:
        print(f"[notify] WARN: no se pudo invocar notify_telegram.py: {e}", file=sys.stderr)
```

`sys.executable` apunta al Python del venv de uv — `httpx` y `dotenv` estarán
disponibles sin necesidad de anidar `uv run`.

### Llamada desde main()

```python
def main():
    args = _parse_args()
    ...
    if args.phase == "premarket":
        indicators = run_premarket_phase(out)
        print_scorecard(indicators)
        if args.notify:
            _call_notify("premarket")

    elif args.phase == "open":
        open_ind = run_open_phase(out, args.window)
        full = _read_json(out / "indicators.json")
        pre_ind = full.get("premarket", {})
        print_combined_scorecard(pre_ind, open_ind, args.window)
        if args.notify:
            _call_notify("open", args.window)
```

---

## Estructura de scripts/notify_telegram.py

```python
#!/usr/bin/env python3
"""
Notificación Telegram para el análisis premarket SPX 0DTE.
Lee outputs/indicators.json y envía el mensaje con formato MarkdownV2 fijo.

Uso:
  uv run python scripts/notify_telegram.py --phase premarket
  uv run python scripts/notify_telegram.py --phase open [--window 30]
"""
import argparse, json, os, sys
from pathlib import Path
import httpx
from dotenv import load_dotenv

load_dotenv()

INDICATORS_PATH = Path("outputs/indicators.json")
TELEGRAM_API    = "https://api.telegram.org/bot{token}/sendMessage"

SIGNAL_EMOJI: dict[str, str] = { ... }   # tabla completa de la sección anterior
STRATEGY_DETAIL: dict[str, dict] = { ... }  # tabla completa de la sección anterior


# ── Helpers ──────────────────────────────────────────────────────────────────

def _sign(n) -> str:
    """Formatea número con signo explícito (+N / -N)."""
    try:
        v = int(float(n))
        return f"+{v}" if v >= 0 else str(v)
    except (TypeError, ValueError):
        return "0"

def _fmt(v, fmt=".2f", fallback="N/D") -> str:
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
    """Construye el mensaje MarkdownV2 para la fase premarket."""
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

    # Valores o fallbacks
    slope_val = (f"VIX={_esc(slope.get('vix'))}  VXV={_esc(slope.get('vxv'))}"
                 if slope.get("status") == "OK" else f"\\[{slope.get('status','ERROR')}\\]")
    ratio_val = (f"VIX9D={_esc(ratio.get('vix9d'))}  VIX={_esc(ratio.get('vix'))}"
                 if ratio.get("status") == "OK" else f"\\[{ratio.get('status','ERROR')}\\]")
    gap_val   = (f"{_esc(_fmt(gap.get('gap_pct'), '+.2f'))}%"
                 if gap.get("status") == "OK" else f"\\[{gap.get('status','ERROR')}\\]")
    gex_val   = (f"{_esc(_fmt(gex.get('net_gex_bn'), '+.2f'))}B"
                 if gex.get("status") == "OK" else f"\\[{gex.get('status','ERROR')}\\]")
    flip_level = gex.get("flip_level")
    flip_val  = (f"Flip={_esc(_fmt(flip_level, '.0f'))}  Spot={_esc(_fmt(gex.get('spot'), '.0f'))}"
                 if gex.get("status") == "OK" and flip_level is not None
                 else ("SIN\\_FLIP" if gex.get("status") == "OK"
                       else f"\\[{gex.get('status','ERROR')}\\]"))
    ivr_val   = (f"VIX={_esc(ivr.get('vix'))}  IVR={_esc(_fmt(ivr.get('ivr'), '.2f'))}%"
                 if ivr.get("status") == "OK" else f"\\[{ivr.get('status','ERROR')}\\]")
    atr_val   = (f"{_esc(_fmt(atr.get('atr_ratio'), '.4f'))}"
                 if atr.get("status") == "OK" else f"\\[{atr.get('status','ERROR')}\\]")

    put_wall  = _esc(_fmt(gex.get("put_wall"),  ".0f"))
    call_wall = _esc(_fmt(gex.get("call_wall"), ".0f"))
    max_pain  = _esc(_fmt(gex.get("max_pain"),  ".0f"))
    flip_disp = _esc(_fmt(flip_level, ".0f")) if flip_level is not None else "N/D"

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
    """Construye el mensaje MarkdownV2 para la fase open/combinada."""
    from scripts.generate_scorecard import _interpret  # reutilizar lógica existente

    pre  = indicators.get("premarket", {})
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

    vwap     = open_.get("vwap_position", {})
    gap_beh  = open_.get("gap_behavior", {})
    vix_d    = open_.get("vix_delta_open", {})
    range_e  = open_.get("range_expansion", {})
    rv_open  = open_.get("realized_vol_open", {})
    d_open   = open_.get("d_score", 0)
    v_open   = open_.get("v_score", 0)

    d_total = d_pre + d_open
    v_total = v_pre + v_open
    regimen, estrategia = _interpret(d_total, v_total)

    detail = STRATEGY_DETAIL.get(estrategia, {
        "delta_short": "N/D", "ancho_pts": "N/D",
        "guidance_short": "N/D", "guidance_long": "N/D",
        "risk_profile": "N/D", "emoji_short": "⚪", "emoji_long": "🛡️",
    })

    flip_level = gex.get("flip_level")
    put_wall   = _esc(_fmt(gex.get("put_wall"),  ".0f"))
    call_wall  = _esc(_fmt(gex.get("call_wall"), ".0f"))
    max_pain   = _esc(_fmt(gex.get("max_pain"),  ".0f"))
    flip_disp  = _esc(_fmt(flip_level, ".0f")) if flip_level is not None else "N/D"

    def _open_row(d: dict, label: str, val_key: str, fmt_str: str, signal_key: str, score_key: str) -> str:
        if d.get("status") == "OK":
            val = _esc(_fmt(d.get(val_key), fmt_str))
        else:
            val = f"\\[{d.get('status','ERROR')}\\]"
        return (f"{_emoji(d.get(signal_key,''))} {label}: {val}  →  "
                f"{_esc(d.get(signal_key,'N/A'))} \\({_esc(_sign(d.get(score_key,0)))}\\)")

    lines = [
        f"📊 *SPX 0DTE — Análisis Final* \\| {_esc(fecha)}",
        "",
        f"━━━ Premarket: D={_esc(_sign(d_pre))} \\| V={_esc(_sign(v_pre))} ━━━━━━━━━",
        f"{_emoji(slope.get('signal',''))} Slope: {_esc(slope.get('signal','N/A'))} \\({_esc(_sign(slope.get('score',0)))}\\)   ·  {_emoji(ratio.get('signal',''))} Ratio: {_esc(ratio.get('signal','N/A'))} \\({_esc(_sign(ratio.get('score',0)))}\\)",
        f"{_emoji(gap.get('signal',''))}   Gap:   {_esc(gap.get('signal','N/A'))} \\({_esc(_sign(gap.get('score',0)))}\\)    ·  {_emoji(gex.get('signal_gex',''))}  GEX:   {_esc(gex.get('signal_gex','N/A'))} \\({_esc(_sign(gex.get('score_gex',0)))}\\)",
        f"{_emoji(gex.get('signal_flip',''))}  Flip:  {_esc(gex.get('signal_flip','N/A'))} \\({_esc(_sign(gex.get('score_flip',0)))}\\)  ·  {_emoji(ivr.get('signal',''))}  IVR:   {_esc(ivr.get('signal','N/A'))} \\({_esc(_sign(ivr.get('score',0)))}\\)",
        f"{_emoji(atr.get('signal',''))}   ATR:   {_esc(atr.get('signal','N/A'))} \\({_esc(_sign(atr.get('score',0)))}\\)",
        "",
        f"━━━ Open Phase \\({_esc(str(window))}min\\): D={_esc(_sign(d_open))} \\| V={_esc(_sign(v_open))} ━━━",
        _open_row(vwap,    "VWAP        ", "value",      ".4f", "signal", "score"),
        _open_row(gap_beh, "Gap Behavior", "gap_fill_pct", ".1f", "signal", "score"),
        _open_row(vix_d,   "VIX Delta   ", "vix_delta",  "+.2f", "signal", "score"),
        _open_row(range_e, "Range Exp   ", "ratio",      ".4f", "signal", "score"),
        _open_row(rv_open, "Realized Vol", "rv_ratio",   ".4f", "signal", "score"),
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
        print("[notify] ERROR: TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID no configurados",
              file=sys.stderr)
        return False
    url  = TELEGRAM_API.format(token=token)
    resp = httpx.post(url, json={
        "chat_id":    chat_id,
        "text":       message,
        "parse_mode": "MarkdownV2",
    }, timeout=10)
    if not resp.is_success:
        print(f"[notify] ERROR Telegram {resp.status_code}: {resp.text}", file=sys.stderr)
        return False
    return True


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Notificación Telegram premarket SPX")
    parser.add_argument("--phase", choices=["premarket", "open"], required=True)
    parser.add_argument("--window", type=int, default=30)
    args = parser.parse_args()

    if not INDICATORS_PATH.exists():
        print(f"[notify] ERROR: {INDICATORS_PATH} no existe — ejecutar el pipeline primero",
              file=sys.stderr)
        sys.exit(1)

    indicators = json.loads(INDICATORS_PATH.read_text(encoding="utf-8"))

    if args.phase == "premarket":
        message = build_premarket_message(indicators)
    else:
        message = build_open_message(indicators, args.window)

    ok = send_telegram(message)
    sys.exit(0 if ok else 1)
```

**Nota sobre el import `_interpret`:**
En `build_open_message`, importar `_interpret` desde `generate_scorecard` añade
una dependencia interna. Alternativa sin dependencia circular: duplicar la tabla
de decisión como constante en `notify_telegram.py` o importar con `importlib`.
La implementación definitiva debe elegir la opción que no genere import circular.

---

## Dependencia httpx

Añadir a `pyproject.toml`:

```toml
dependencies = [
    "pandas>=3.0.1",
    "yfinance>=1.2.0",
    "tastytrade>=9.0",
    "python-dotenv>=1.0",
    "httpx>=0.27",
]
```

Instalar: `uv add httpx`

---

## Tareas programadas

Las tareas se crean con `mcp__scheduled-tasks__create_scheduled_task`.
La timezone `America/New_York` maneja automáticamente el cambio horario ET/EDT.

| Tarea | Cron (ET) | Timezone | Comando |
|---|---|---|---|
| spx-premarket-analysis | `10 9 * * 1-5` | America/New_York | `uv run python scripts/run.py --phase premarket --notify` |
| spx-open-analysis | `15 10 * * 1-5` | America/New_York | `uv run python scripts/run.py --phase open --window 30 --notify` |

**Nota:** El working directory del agente programado debe ser la raíz del proyecto
(`premarket/`) para que `outputs/` y `scripts/` sean accesibles con rutas relativas.

---

## Skill de Claude Code (.claude/skills/premarket-analysis.md)

Ver archivo `.claude/skills/premarket-analysis.md`.

El skill define:
- Cómo interpretar argumentos `--phase` y `--window`
- El comando exacto a ejecutar (con `--notify`)
- Qué mostrar en terminal (solo estado, no repetir el scorecard)
- Que Claude NO genera el mensaje Telegram — lo genera `notify_telegram.py`
- Gestión de errores (pipeline falla → mostrar stderr, no enviar nada)

---

## Verificación

```bash
# 1. Instalar dependencia
uv add httpx

# 2. Configurar credenciales Telegram en .env
# TELEGRAM_BOT_TOKEN=<token de @BotFather>
# TELEGRAM_CHAT_ID=<chat_id>

# 3. Ejecutar pipeline premarket (genera outputs/indicators.json)
uv run python scripts/run.py --phase premarket

# 4. Test notificador standalone (sin pipeline)
uv run python scripts/notify_telegram.py --phase premarket

# 5. Test integrado premarket (pipeline + notificación)
uv run python scripts/run.py --phase premarket --notify

# 6. Test integrado open phase (después de las 10:00 ET para tener datos)
uv run python scripts/run.py --phase open --window 30 --notify

# 7. Test de resiliencia — token incorrecto, pipeline no debe abortar
TELEGRAM_BOT_TOKEN=invalid uv run python scripts/run.py --phase premarket --notify
# Esperado: pipeline exit 0, mensaje de WARN en stderr

# 8. Regresión — tests existentes deben pasar sin cambios
uv run pytest

# 9. Verificar tareas programadas creadas
# mcp__scheduled-tasks__list_scheduled_tasks
```

El mensaje de Telegram debe:
- Mostrar todos los campos en el orden exacto de la plantilla
- Usar los emojis definidos en `SIGNAL_EMOJI` (sin variación)
- Escapar correctamente los caracteres especiales (sin errores de parseo MarkdownV2)
- Mostrar `N/D` / `[ERROR]` / `[MISSING]` en campos con datos faltantes
