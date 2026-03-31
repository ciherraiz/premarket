import json
from pathlib import Path


def print_scorecard(indicators: dict, phase: str = "premarket") -> None:
    # Retrocompatibilidad: si el dict tiene namespace, extraer la sección correcta.
    # Si no tiene namespace (tests legacy o llamada directa con dict plano), usar tal cual.
    if phase in indicators:
        data = indicators[phase]
    else:
        data = indicators

    fecha = indicators.get("fecha") or data.get("fecha", "N/A")
    slope     = data.get("vix_vxv_slope", {})
    ratio     = data.get("vix9d_vix_ratio", {})
    gap       = data.get("overnight_gap", {})
    ivr       = data.get("ivr", {})
    atr_ratio = data.get("atr_ratio", {})
    net_gex   = data.get("net_gex", {})

    d_score = data.get("d_score", slope.get("score", 0) + ratio.get("score", 0) + gap.get("score", 0))
    v_score = data.get("v_score", ivr.get("score", 0) + atr_ratio.get("score", 0))

    sep  = "=" * 62
    line = "-" * 62

    def _sign(n):
        return f"+{n}" if n >= 0 else str(n)

    print(sep)
    print(f"  PRE-MARKET SCORECARD — {fecha}")
    print(sep)
    print()

    # --- D-SCORE block ---
    print("  [D-SCORE — DIRECCIONAL]")
    print(f"  {'Indicador':<20} {'Valor':<26} {'Score':<6} Signal")
    print(line)

    # VIX/VXV Slope row
    slope_status = slope.get("status", "ERROR")
    if slope_status == "OK":
        vix = slope.get("vix")
        vxv = slope.get("vxv")
        slope_val = f"VIX={vix}  VXV={vxv}"
    else:
        slope_val = f"[{slope_status}]"
    slope_score  = slope.get("score", 0)
    slope_signal = slope.get("signal", "N/A")
    print(f"  {'VIX/VXV Slope':<20} {slope_val:<26} {_sign(slope_score):<6} {slope_signal}")

    # VIX9D/VIX Ratio row
    ratio_status = ratio.get("status", "ERROR")
    if ratio_status == "OK":
        vix9d = ratio.get("vix9d")
        vix2  = ratio.get("vix")
        ratio_val = f"VIX9D={vix9d}  VIX={vix2}"
    else:
        ratio_val = f"[{ratio_status}]"
    ratio_score  = ratio.get("score", 0)
    ratio_signal = ratio.get("signal", "N/A")
    print(f"  {'VIX9D/VIX Ratio':<20} {ratio_val:<26} {_sign(ratio_score):<6} {ratio_signal}")

    # Overnight Gap row
    gap_status = gap.get("status", "ERROR")
    if gap_status == "OK":
        gap_pct = gap.get("gap_pct")
        gap_val = f"Gap={gap_pct:+.2f}%"
    else:
        gap_val = f"[{gap_status}]"
    gap_score  = gap.get("score", 0)
    gap_signal = gap.get("signal", "N/A")
    print(f"  {'Overnight Gap':<20} {gap_val:<26} {_sign(gap_score):<6} {gap_signal}")

    # Net GEX (IND-03)
    gex_status = net_gex.get("status", "ERROR")
    if gex_status == "OK":
        gex_bn  = net_gex.get("net_gex_bn")
        gex_val = f"GEX={gex_bn:+.2f}B"
    else:
        gex_val = f"[{gex_status}]"
    gex_score  = net_gex.get("score_gex", 0)
    gex_signal = net_gex.get("signal_gex", "N/A")
    print(f"  {'Net GEX':<20} {gex_val:<26} {_sign(gex_score):<6} {gex_signal}")

    # Flip Level (IND-04)
    flip_status = net_gex.get("status", "ERROR")
    flip_level  = net_gex.get("flip_level")
    if flip_status == "OK" and flip_level is not None:
        spot_val = net_gex.get("spot") or 0
        flip_val = f"Flip={flip_level:.0f}  Spot={spot_val:.0f}"
    elif flip_status == "OK":
        flip_val = "SIN_FLIP"
    else:
        flip_val = f"[{flip_status}]"
    flip_score  = net_gex.get("score_flip", 0)
    flip_signal = net_gex.get("signal_flip", "N/A")
    print(f"  {'Flip Level':<20} {flip_val:<26} {_sign(flip_score):<6} {flip_signal}")

    print(line)
    print(f"  D-Score (direccional):  {_sign(d_score)}")
    print()

    # --- V-SCORE block ---
    print("  [V-SCORE — VOLATILIDAD]")
    print(f"  {'Indicador':<20} {'Valor':<26} {'Score':<6} Signal")
    print(line)

    # IV Rank (IVR) row
    ivr_status = ivr.get("status", "ERROR")
    if ivr_status == "OK":
        vix_ivr = ivr.get("vix")
        ivr_val_num = ivr.get("ivr")
        ivr_val = f"VIX={vix_ivr}  IVR={ivr_val_num}%"
    else:
        ivr_val = f"[{ivr_status}]"
    ivr_score  = ivr.get("score", 0)
    ivr_signal = ivr.get("signal", "N/A")
    print(f"  {'IV Rank (IVR)':<20} {ivr_val:<26} {_sign(ivr_score):<6} {ivr_signal}")

    # ATR Ratio row
    atr_status = atr_ratio.get("status", "ERROR")
    if atr_status == "OK":
        atr_val_num = atr_ratio.get("atr_ratio")
        atr_val = f"ATR_ratio={atr_val_num}"
    else:
        atr_val = f"[{atr_status}]"
    atr_score  = atr_ratio.get("score", 0)
    atr_signal = atr_ratio.get("signal", "N/A")
    print(f"  {'ATR Ratio':<20} {atr_val:<26} {_sign(atr_score):<6} {atr_signal}")

    print(line)
    print(f"  V-Score (volatilidad):  {_sign(v_score)}")
    print()
    print(sep)


def print_combined_scorecard(
    premarket: dict,
    open_phase: dict,
    window_minutes: int = 30,
) -> None:
    """
    Imprime el scorecard combinado con ambas fases y la decisión final.
    premarket: dict plano de indicadores premarket
    open_phase: dict plano de indicadores open phase
    window_minutes: minutos de la ventana open phase (para el header)
    """
    sep  = "=" * 62
    line = "-" * 62

    def _sign(n):
        return f"+{n}" if n >= 0 else str(n)

    fecha = premarket.get("fecha") or open_phase.get("fecha", "N/A")

    print(sep)
    print(f"  SCORECARD COMBINADO — {fecha}  [ventana: {window_minutes} min]")
    print(sep)

    # --- Bloque premarket (compacto) ---
    slope   = premarket.get("vix_vxv_slope", {})
    ratio   = premarket.get("vix9d_vix_ratio", {})
    gap     = premarket.get("overnight_gap", {})
    ivr     = premarket.get("ivr", {})
    atr     = premarket.get("atr_ratio", {})
    net_gex = premarket.get("net_gex", {})
    d_pre   = premarket.get("d_score", 0)
    v_pre   = premarket.get("v_score", 0)

    print()
    print("  [PRE-MARKET — D-SCORE]")
    print(f"  {'Indicador':<20} {'Valor':<26} {'Score':<6} Signal")
    print(line)

    def _slope_row():
        if slope.get("status") == "OK":
            val = f"VIX={slope.get('vix')}  VXV={slope.get('vxv')}"
        else:
            val = f"[{slope.get('status','ERROR')}]"
        print(f"  {'VIX/VXV Slope':<20} {val:<26} {_sign(slope.get('score',0)):<6} {slope.get('signal','N/A')}")

    def _ratio_row():
        if ratio.get("status") == "OK":
            val = f"VIX9D={ratio.get('vix9d')}  VIX={ratio.get('vix')}"
        else:
            val = f"[{ratio.get('status','ERROR')}]"
        print(f"  {'VIX9D/VIX Ratio':<20} {val:<26} {_sign(ratio.get('score',0)):<6} {ratio.get('signal','N/A')}")

    def _gap_row():
        if gap.get("status") == "OK":
            val = f"Gap={gap.get('gap_pct'):+.2f}%"
        else:
            val = f"[{gap.get('status','ERROR')}]"
        print(f"  {'Overnight Gap':<20} {val:<26} {_sign(gap.get('score',0)):<6} {gap.get('signal','N/A')}")

    def _gex_row():
        if net_gex.get("status") == "OK":
            val = f"GEX={net_gex.get('net_gex_bn'):+.2f}B"
        else:
            val = f"[{net_gex.get('status','ERROR')}]"
        print(f"  {'Net GEX':<20} {val:<26} {_sign(net_gex.get('score_gex',0)):<6} {net_gex.get('signal_gex','N/A')}")

    def _flip_row():
        flip_level = net_gex.get("flip_level")
        if net_gex.get("status") == "OK" and flip_level is not None:
            val = f"Flip={flip_level:.0f}  Spot={net_gex.get('spot') or 0:.0f}"
        elif net_gex.get("status") == "OK":
            val = "SIN_FLIP"
        else:
            val = f"[{net_gex.get('status','ERROR')}]"
        print(f"  {'Flip Level':<20} {val:<26} {_sign(net_gex.get('score_flip',0)):<6} {net_gex.get('signal_flip','N/A')}")

    _slope_row()
    _ratio_row()
    _gap_row()
    _gex_row()
    _flip_row()
    print(line)
    print(f"  D-Score premarket:  {_sign(d_pre)}")
    print()

    print("  [PRE-MARKET — V-SCORE]")
    print(f"  {'Indicador':<20} {'Valor':<26} {'Score':<6} Signal")
    print(line)

    if ivr.get("status") == "OK":
        ivr_val = f"VIX={ivr.get('vix')}  IVR={ivr.get('ivr')}%"
    else:
        ivr_val = f"[{ivr.get('status','ERROR')}]"
    print(f"  {'IV Rank (IVR)':<20} {ivr_val:<26} {_sign(ivr.get('score',0)):<6} {ivr.get('signal','N/A')}")

    if atr.get("status") == "OK":
        atr_val = f"ATR_ratio={atr.get('atr_ratio')}"
    else:
        atr_val = f"[{atr.get('status','ERROR')}]"
    print(f"  {'ATR Ratio':<20} {atr_val:<26} {_sign(atr.get('score',0)):<6} {atr.get('signal','N/A')}")

    print(line)
    print(f"  V-Score premarket:  {_sign(v_pre)}")
    print()

    # --- Bloque open phase ---
    d_open = open_phase.get("d_score", 0)
    v_open = open_phase.get("v_score", 0)

    open_ind_keys = [k for k in open_phase
                     if k not in ("d_score", "v_score", "window_minutes", "fecha")]

    print(f"  [OPEN PHASE — D-SCORE]  (primeros {window_minutes} min)")
    print(f"  {'Indicador':<20} {'Valor':<26} {'Score':<6} Signal")
    print(line)

    if open_ind_keys:
        for key in open_ind_keys:
            ind = open_phase[key]
            if isinstance(ind, dict):
                score  = ind.get("score", 0)
                signal = ind.get("signal", "N/A")
                raw    = ind.get("value", "")
                # Formatear el valor numérico con unidad si está disponible
                if isinstance(raw, float):
                    vwap_level = ind.get("vwap")
                    if vwap_level is not None:
                        value = f"Dist={raw:+.4f}%  VWAP={vwap_level}"
                    else:
                        value = f"{raw:+.4f}%"
                else:
                    value = str(raw)
                print(f"  {key:<20} {value:<26} {_sign(score):<6} {signal}")
    else:
        print(f"  {'(pendiente)':<20} {'—':<26} {'0':<6} —")

    print(line)
    print(f"  D-Score open:  {_sign(d_open)}")
    print()

    # --- Totales y decisión ---
    d_total = d_pre + d_open
    v_total = v_pre + v_open

    print(sep)
    print("  DECISIÓN FINAL")
    print(f"  D-Score total:  {_sign(d_total):<6}  (premarket {_sign(d_pre)}  |  open {_sign(d_open)})")
    print(f"  V-Score total:  {_sign(v_total):<6}  (premarket {_sign(v_pre)}  |  open {_sign(v_open)})")
    print()

    regimen, estrategia = _interpret(d_total, v_total)
    print(f"  Régimen:    {regimen}")
    print(f"  Estrategia: {estrategia}")
    print(sep)


def _interpret(d_score: int, v_score: int) -> tuple[str, str]:
    """Tabla de decisión provisional (pendiente de calibración con datos reales)."""
    if d_score >= 5:
        if v_score >= 3:
            return "Tendencia alcista + vol alta", "Call spread OTM agresivo"
        return "Tendencia alcista + vol baja", "Call spread OTM conservador"
    elif d_score <= -5:
        if v_score >= 3:
            return "Tendencia bajista + vol alta", "Put spread OTM agresivo"
        return "Tendencia bajista + vol baja", "Put spread OTM conservador"
    else:
        if v_score >= 3:
            return "Rango + vol alta", "Iron condor amplio"
        return "Rango + vol baja", "Iron condor estrecho"


if __name__ == "__main__":
    data = json.loads(Path("outputs/indicators.json").read_text())
    print_scorecard(data)
