import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fetch_market_data import (
    GEX_MAX_STRIKES,
    fetch_es_prev_close,
    fetch_es_quote,
    fetch_option_chain,
    fetch_spx_ohlcv,
    fetch_vix_history,
    fetch_vix_term_structure,
)
from calculate_indicators import (
    calc_atr_ratio,
    calc_ivr,
    calc_net_gex,
    calc_overnight_gap,
    calc_vix9d_vix_ratio,
    calc_vix_vxv_slope,
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

    spx_ohlcv_data = fetch_spx_ohlcv()
    spx_spot = None
    if spx_ohlcv_data.get("ohlcv"):
        spx_spot = spx_ohlcv_data["ohlcv"][-1]["Close"]

    option_chain = fetch_option_chain(
        "SPXW", days_ahead=5, max_strikes=GEX_MAX_STRIKES, spot=spx_spot
    )

    data["spx_ohlcv"]    = spx_ohlcv_data
    data["spx_spot"]     = spx_spot
    data["option_chain"] = option_chain

    (out / "data.json").write_text(json.dumps(data, indent=2))
    print(f"[fetch] status={data['status']} fecha={data['fecha']} "
          f"vix_history={data['vix_history']['status']} "
          f"es_prev={data['es_prev']['status']} "
          f"es={data['es']['status']} "
          f"spx_ohlcv={spx_ohlcv_data['status']}(bars={spx_ohlcv_data['bars']}) "
          f"option_chain={option_chain['status']}(n={option_chain['n_contracts']})")

    if data["status"] != "OK":
        print(f"[ERROR] fetch: status={data['status']}", file=sys.stderr)
        sys.exit(1)

    # Paso 2: calcular indicadores
    slope     = calc_vix_vxv_slope(data)
    ratio     = calc_vix9d_vix_ratio(data)
    gap       = calc_overnight_gap(data.get("es_prev", {}), data.get("es", {}))
    ivr       = calc_ivr(data, data.get("vix_history", {}))
    atr_ratio = calc_atr_ratio(data.get("spx_ohlcv", {}))
    net_gex   = calc_net_gex(
        data.get("option_chain", {}),
        spot=data.get("spx_spot"),
        fecha=data.get("fecha"),
    )

    d_score = (slope["score"] + ratio["score"] + gap["score"]
               + net_gex["score_gex"] + net_gex["score_flip"])
    v_score = ivr["score"] + atr_ratio["score"]

    indicators = {
        "fecha":           data.get("fecha"),
        "vix_vxv_slope":   slope,
        "vix9d_vix_ratio": ratio,
        "overnight_gap":   gap,
        "ivr":             ivr,
        "atr_ratio":       atr_ratio,
        "net_gex":         net_gex,
        "d_score":         d_score,
        "v_score":         v_score,
    }
    (out / "indicators.json").write_text(json.dumps(indicators, indent=2))
    print(f"[calc] slope={slope['signal']}({slope['score']})  "
          f"ratio={ratio['signal']}({ratio['score']})  "
          f"gap={gap['signal']}({gap['score']})  "
          f"gex={net_gex['signal_gex']}({net_gex['score_gex']})  "
          f"flip={net_gex['signal_flip']}({net_gex['score_flip']})  "
          f"ivr={ivr['signal']}({ivr['score']})  "
          f"atr={atr_ratio['signal']}({atr_ratio['score']})  "
          f"D={d_score}  V={v_score}")

    # Paso 3: scorecard
    print_scorecard(indicators)


if __name__ == "__main__":
    main()
