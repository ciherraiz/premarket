import json
from pathlib import Path


def print_scorecard(indicators: dict) -> None:
    fecha = indicators.get("fecha", "N/A")
    slope = indicators.get("vix_vxv_slope", {})
    ratio = indicators.get("vix9d_vix_ratio", {})
    gap   = indicators.get("overnight_gap", {})
    ivr   = indicators.get("ivr", {})

    d_score = indicators.get("d_score", slope.get("score", 0) + ratio.get("score", 0) + gap.get("score", 0))
    v_score = indicators.get("v_score", ivr.get("score", 0))

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

    print(line)
    print(f"  V-Score (volatilidad):  {_sign(v_score)}")
    print()
    print(sep)


if __name__ == "__main__":
    data = json.loads(Path("outputs/indicators.json").read_text())
    print_scorecard(data)
