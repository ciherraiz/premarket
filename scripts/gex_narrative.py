"""
GEX Narrative — Generación automática de price paths y texto del reporte Dealer Flow.

Uso:
    from gex_narrative import calc_price_paths, build_dealer_flow_text
"""
from __future__ import annotations


def calc_price_paths(
    gex:   dict,
    charm: dict,
    dex:   dict,
    spot:  float,
) -> dict:
    """
    Genera los price paths alcista y bajista basándose en la estructura GEX.

    Lógica:
    - Path alcista: spot → niveles sobre spot hasta call_wall (en orden)
    - Path bajista: spot → niveles bajo spot hasta put_wall (en orden descendente)

    Candidatos de niveles (ordenados por relevancia):
      call_wall, dex_positive_wall, max_pain, pinning_zone, +25/+50/+100 pts redondos
      put_wall,  dex_negative_wall, flip_level, chop_zone_low, -25/-50/-100 pts redondos

    Args:
        gex:   output de calc_net_gex
        charm: output de calc_charm_exposure
        dex:   output de calc_delta_exposure
        spot:  precio spot del SPX

    Returns:
        {
            "path_alcista":      list[float],   # [spot, nivel1, nivel2, nivel3]
            "path_bajista":      list[float],   # [spot, nivel1, nivel2, nivel3]
            "key_decision":      float | None,  # nivel pivote
            "key_decision_desc": str,
        }
    """
    base: dict = {
        "path_alcista":      [spot] if spot else [],
        "path_bajista":      [spot] if spot else [],
        "key_decision":      None,
        "key_decision_desc": "",
    }

    if not spot or spot <= 0:
        return base

    call_wall    = gex.get("call_wall")
    put_wall     = gex.get("put_wall")
    flip_level   = gex.get("flip_level")
    max_pain     = gex.get("max_pain")
    chop_low     = gex.get("chop_zone_low")
    dex_pos_wall = dex.get("dex_positive_wall")
    dex_neg_wall = dex.get("dex_negative_wall")
    dex_flip     = dex.get("dex_flip")
    charm_pin    = charm.get("charm_pin_zone")
    charm_signal = charm.get("charm_signal", "NEUTRO")

    # ── Candidatos alcistas (sobre spot) ─────────────────────────────────────
    alcista_candidates: set[float] = set()

    # Niveles estructurales
    for lvl in [flip_level, max_pain, dex_pos_wall, dex_flip, charm_pin, call_wall]:
        if lvl and lvl > spot:
            alcista_candidates.add(_round25(lvl))

    # Niveles redondos sobre spot (múltiplos de 25)
    next_round = _ceil25(spot + 1)
    for i in range(8):
        candidate = next_round + i * 25
        if candidate > spot:
            alcista_candidates.add(candidate)
        if len(alcista_candidates) >= 10:
            break

    path_alcista = _build_path(spot, sorted(alcista_candidates), ascending=True, n=3)

    # ── Candidatos bajistas (bajo spot) ──────────────────────────────────────
    bajista_candidates: set[float] = set()

    for lvl in [flip_level, chop_low, dex_neg_wall, dex_flip, charm_pin, put_wall]:
        if lvl and lvl < spot:
            bajista_candidates.add(_round25(lvl))

    prev_round = _floor25(spot - 1)
    for i in range(8):
        candidate = prev_round - i * 25
        if candidate < spot:
            bajista_candidates.add(candidate)
        if len(bajista_candidates) >= 10:
            break

    path_bajista = _build_path(spot, sorted(bajista_candidates, reverse=True), ascending=False, n=3)

    # ── Key Decision ──────────────────────────────────────────────────────────
    # El nivel más cercano al spot que sea estructuralmente significativo
    key = None
    key_desc = ""

    if flip_level and abs(flip_level - spot) <= 100:
        key = flip_level
        if spot > flip_level:
            key_desc = f"Mantener {flip_level:.0f} es clave — pérdida activa path bajista"
        else:
            key_desc = f"Recuperar {flip_level:.0f} necesario para sesgo alcista"
    elif charm_pin and abs(charm_pin - spot) <= 50:
        key = charm_pin
        key_desc = f"Charm pin en {charm_pin:.0f} — imán de precio intraday"
    elif call_wall and abs(call_wall - spot) <= 75:
        key = call_wall
        key_desc = f"Call Wall {call_wall:.0f} — resistencia techo de sesión"
    elif put_wall and abs(put_wall - spot) <= 75:
        key = put_wall
        key_desc = f"Put Wall {put_wall:.0f} — soporte suelo de sesión"

    base["path_alcista"]      = path_alcista
    base["path_bajista"]      = path_bajista
    base["key_decision"]      = key
    base["key_decision_desc"] = key_desc

    return base


def build_dealer_flow_text(indicators: dict) -> str:
    """
    Construye el texto completo del reporte Dealer Flow para Telegram / terminal.

    Args:
        indicators: dict de indicadores (sección "premarket" o raíz de indicators.json)

    Returns:
        str con el reporte formateado.
    """
    net_gex  = indicators.get("net_gex", {})
    charm    = indicators.get("charm_exposure", {})
    dex_data = indicators.get("delta_exposure", {})
    pin      = indicators.get("pinning_zone", {})
    fecha    = indicators.get("fecha", "")

    spot       = net_gex.get("spot")
    flip       = net_gex.get("flip_level")
    call_wall  = net_gex.get("call_wall")
    put_wall   = net_gex.get("put_wall")
    max_pain   = net_gex.get("max_pain")
    chop_low   = net_gex.get("chop_zone_low")
    chop_high  = net_gex.get("chop_zone_high")
    net_gex_bn = net_gex.get("net_gex_bn")
    nbd        = net_gex.get("net_gex_by_dte", {})
    signal_gex = net_gex.get("signal_gex", "N/A")

    charm_signal   = charm.get("charm_signal", "N/A")
    charm_total    = charm.get("charm_total")
    charm_pin      = charm.get("charm_pin_zone")
    charm_pin_conf = charm.get("charm_pin_zone_conf", "")
    charm_intraday = charm.get("charm_intraday", [])

    dex_signal  = dex_data.get("dex_signal", "N/A")
    dex_flip    = dex_data.get("dex_flip")
    dex_total   = dex_data.get("dex_total")

    pinning_zone = pin.get("pinning_zone")
    pinning_conf = pin.get("pinning_conf", "")
    pinning_nar  = pin.get("pinning_narrative", "")

    # Price paths
    paths = calc_price_paths(net_gex, charm, dex_data, spot or 0)
    path_alc = paths["path_alcista"]
    path_baj = paths["path_bajista"]
    key_dec  = paths.get("key_decision")
    key_desc = paths.get("key_decision_desc", "")

    def _fmt(v, decimals=0) -> str:
        if v is None:
            return "N/A"
        fmt = f".{decimals}f"
        return format(v, fmt)

    def _dist(wall) -> str:
        if wall is None or spot is None:
            return ""
        d = wall - spot
        return f" (dist: {d:+.0f} pts)"

    # ── Construir texto ───────────────────────────────────────────────────────
    lines = []
    lines.append(f"📊 *SPX Dealer Flow — Premarket {fecha}*")
    lines.append("═" * 42)
    lines.append("")

    # Régimen
    gex_str = f"{net_gex_bn:+.1f}B" if net_gex_bn is not None else "N/A"
    lines.append(f"*RÉGIMEN:* {signal_gex}  Net GEX: {gex_str}")

    # GEX por bucket
    g0  = nbd.get("0dte")
    g7  = nbd.get("7dte")
    g30 = nbd.get("30dte")
    bucket_parts = []
    if g0  is not None: bucket_parts.append(f"0DTE: {g0:+.1f}B")
    if g7  is not None: bucket_parts.append(f"≤7DTE: {g7:+.1f}B")
    if g30 is not None: bucket_parts.append(f"≤30DTE: {g30:+.1f}B")
    if bucket_parts:
        lines.append("  " + "  |  ".join(bucket_parts))

    # Charm
    charm_k = f"~{charm_total/1000:.0f}K δ/h" if charm_total is not None else "N/A"
    lines.append(f"*Charm:* {charm_signal}  ({charm_k})")
    lines.append("")

    # Niveles clave
    lines.append("*NIVELES CLAVE*")
    lines.append(f"  Flip Level:   {_fmt(flip)}{_dist(flip)}")
    lines.append(f"  Call Wall:    {_fmt(call_wall)}{_dist(call_wall)}")
    lines.append(f"  Put Wall:     {_fmt(put_wall)}{_dist(put_wall)}")

    if pinning_zone:
        lines.append(f"  Pinning Zone: {_fmt(pinning_zone)}  [{pinning_conf}]")
    if chop_low and chop_high:
        lines.append(f"  Chop Zone:    {_fmt(chop_low)} – {_fmt(chop_high)}")
    if max_pain:
        lines.append(f"  Max Pain:     {_fmt(max_pain)}")
    if dex_flip:
        lines.append(f"  DEX Flip:     {_fmt(dex_flip)}  ({dex_signal or 'N/A'})")
    lines.append("")

    # Charm intraday (muestra 4–5 puntos relevantes)
    if charm_intraday:
        lines.append("*CHARM FLOW ESPERADO*")
        horas_show = ["09:30", "11:00", "13:00", "15:00", "15:30"]
        for entry in charm_intraday:
            if entry["hora"] in horas_show:
                delta_k = entry["charm_delta"] / 1000
                sig_icon = "⬆" if entry["signal"] == "EXPANSIVO" else ("⬇" if entry["signal"] == "SUPRESIVO" else "➡")
                lines.append(f"  {entry['hora']}  {delta_k:+.0f}K  {sig_icon} {entry['signal']}")
        lines.append("")

    # Price paths
    if len(path_alc) > 1 or len(path_baj) > 1:
        lines.append("*PRICE PATHS*")
    if len(path_alc) > 1:
        lines.append(f"  ↑ " + " → ".join(f"{p:.0f}" for p in path_alc))
    if len(path_baj) > 1:
        lines.append(f"  ↓ " + " → ".join(f"{p:.0f}" for p in path_baj))
    if key_dec and key_desc:
        lines.append(f"\n  📌 {key_desc}")
    lines.append("")

    # Pinning Zone narrativa
    if pinning_nar:
        lines.append(f"💎 {pinning_nar}")

    return "\n".join(lines)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _round25(v: float) -> float:
    """Redondea al múltiplo de 25 más cercano."""
    return round(v / 25) * 25


def _ceil25(v: float) -> float:
    """Redondea hacia arriba al múltiplo de 25."""
    import math
    return math.ceil(v / 25) * 25


def _floor25(v: float) -> float:
    """Redondea hacia abajo al múltiplo de 25."""
    import math
    return math.floor(v / 25) * 25


def _build_path(
    spot: float,
    candidates: list[float],
    ascending: bool,
    n: int = 3,
) -> list[float]:
    """
    Construye el path de precio desde spot usando los candidatos dados.

    Args:
        spot:       precio de partida
        candidates: lista de niveles candidatos (ya ordenada, ascendente o descendente)
        ascending:  True para path alcista, False para bajista
        n:          número máximo de niveles después del spot

    Returns:
        [spot, nivel1, nivel2, ..., nivelN]
    """
    path = [spot]
    for lvl in candidates:
        if ascending and lvl <= spot:
            continue
        if not ascending and lvl >= spot:
            continue
        # Evitar niveles demasiado juntos (< 10 pts del anterior)
        if abs(lvl - path[-1]) < 10:
            continue
        path.append(round(lvl))
        if len(path) - 1 >= n:
            break
    return path
