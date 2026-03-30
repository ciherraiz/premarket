import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fetch_market_data import (
    fetch_vix_term_structure,
    fetch_vix_history,
    fetch_es_prev_close,
    fetch_es_quote,
)
from calculate_indicators import (
    calc_vix_vxv_slope,
    calc_vix9d_vix_ratio,
    calc_ivr,
    calc_overnight_gap,
)
from generate_scorecard import print_scorecard


def main():
    out = Path("outputs")
    out.mkdir(exist_ok=True)

    # Paso 1: fetch
    data = fetch_vix_term_structure()
    data["vix_history"] = fetch_vix_history()
    data["es_prev"]     = fetch_es_prev_close()
    data["es"]          = fetch_es_quote()
    (out / "data.json").write_text(json.dumps(data, indent=2))
    print(f"[fetch] status={data['status']} fecha={data['fecha']} "
          f"vix_history={data['vix_history']['status']} "
          f"es_prev={data['es_prev']['status']} "
          f"es={data['es']['status']}")
    if data["status"] != "OK":
        print(f"[ERROR] fetch: status={data['status']}", file=sys.stderr)
        sys.exit(1)

    # Paso 2: calcular indicadores
    slope = calc_vix_vxv_slope(data)
    ratio = calc_vix9d_vix_ratio(data)
    gap   = calc_overnight_gap(data.get("es_prev", {}), data.get("es", {}))
    ivr   = calc_ivr(data, data.get("vix_history", {}))

    indicators = {
        "fecha":           data.get("fecha"),
        "vix_vxv_slope":   slope,
        "vix9d_vix_ratio": ratio,
        "overnight_gap":   gap,
        "ivr":             ivr,
        "d_score":         slope["score"] + ratio["score"] + gap["score"],
        "v_score":         ivr["score"],
    }
    (out / "indicators.json").write_text(json.dumps(indicators, indent=2))
    print(f"[calc] slope={slope['signal']}({slope['score']})  "
          f"ratio={ratio['signal']}({ratio['score']})  "
          f"gap={gap['signal']}({gap['score']})  "
          f"ivr={ivr['signal']}({ivr['score']})  "
          f"D={indicators['d_score']}  V={indicators['v_score']}")

    # Paso 3: scorecard
    print_scorecard(indicators)


if __name__ == "__main__":
    main()
