import json
from pathlib import Path


def print_scorecard(indicators: dict) -> None:
    fecha = indicators.get("fecha", "N/A")
    slope = indicators.get("vix_vxv_slope", {})
    ratio = indicators.get("vix9d_vix_ratio", {})

    d_score = slope.get("score", 0) + ratio.get("score", 0)
    sign = "+" if d_score >= 0 else ""

    sep = "=" * 62
    line = "-" * 62

    print(sep)
    print(f"  PRE-MARKET SCORECARD - {fecha}")
    print(sep)
    print(f"  {'Indicador':<20} {'Valores':>20}  {'Ratio':>7}  {'Score':>5}  Signal")
    print(line)

    vix = slope.get("vix")
    vxv = slope.get("vxv")
    slope_ratio = slope.get("ratio")
    slope_score = slope.get("score", 0)
    slope_signal = slope.get("signal", "N/A")
    slope_vals = f"VIX={vix}  VXV={vxv}"
    score_str = f"+{slope_score}" if slope_score > 0 else str(slope_score)
    print(f"  {'VIX/VXV Slope':<20} {slope_vals:>20}  {str(slope_ratio):>7}  {score_str:>5}  {slope_signal}")

    vix9d = ratio.get("vix9d")
    vix2 = ratio.get("vix")
    ratio_ratio = ratio.get("ratio")
    ratio_score = ratio.get("score", 0)
    ratio_signal = ratio.get("signal", "N/A")
    ratio_vals = f"VIX9D={vix9d}  VIX={vix2}"
    score_str2 = f"+{ratio_score}" if ratio_score > 0 else str(ratio_score)
    print(f"  {'VIX9D/VIX Ratio':<20} {ratio_vals:>20}  {str(ratio_ratio):>7}  {score_str2:>5}  {ratio_signal}")

    print(line)
    print(f"  D-Score parcial (direccional):  {sign}{d_score}")
    print(sep)


if __name__ == "__main__":
    data = json.loads(Path("outputs/indicators.json").read_text())
    print_scorecard(data)
