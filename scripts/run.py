import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fetch_market_data import (
    GEX_MAX_STRIKES,
    fetch_es_prev_close,
    fetch_es_quote,
    fetch_option_chain,
    fetch_spx_intraday,
    fetch_spx_ohlcv,
    fetch_vix_history,
    fetch_vix_intraday,
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
from calculate_open_indicators import calc_vwap_position, calc_vix_delta_open, calc_range_expansion, calc_gap_behavior, calc_realized_vol_open
from generate_scorecard import print_combined_scorecard, print_scorecard


def run_premarket_phase(out: Path) -> dict:
    """Fetch y cálculo de indicadores premarket. Devuelve el dict de indicadores."""
    # Paso 1: fetch
    data = fetch_vix_term_structure()
    data["vix_history"] = fetch_vix_history()
    data["es_prev"]     = fetch_es_prev_close()
    data["es"]          = fetch_es_quote()

    spx_ohlcv_data = fetch_spx_ohlcv()
    spx_spot = None
    if spx_ohlcv_data.get("ohlcv"):
        spx_spot = spx_ohlcv_data["ohlcv"][-1]["Close"]

    chain_0dte  = fetch_option_chain(
        "SPXW", days_ahead=0, max_strikes=GEX_MAX_STRIKES, spot=spx_spot
    )
    chain_multi = fetch_option_chain(
        "SPXW", days_ahead=5, max_strikes=GEX_MAX_STRIKES, spot=spx_spot
    )

    data["spx_ohlcv"]          = spx_ohlcv_data
    data["spx_spot"]           = spx_spot
    data["option_chain_0dte"]  = chain_0dte
    data["option_chain_multi"] = chain_multi

    # Guardar data.json con namespace
    data_out = {"fecha": data.get("fecha"), "status": data.get("status"),
                "premarket": {k: v for k, v in data.items()
                              if k not in ("fecha", "status")}}
    existing = _read_json(out / "data.json")
    existing.update(data_out)
    (out / "data.json").write_text(json.dumps(existing, indent=2))

    print(f"[fetch] status={data['status']} fecha={data['fecha']} "
          f"vix_history={data['vix_history']['status']} "
          f"es_prev={data['es_prev']['status']} "
          f"es={data['es']['status']} "
          f"spx_ohlcv={spx_ohlcv_data['status']}(bars={spx_ohlcv_data['bars']}) "
          f"chain_0dte={chain_0dte['status']}(n={chain_0dte['n_contracts']}) "
          f"chain_multi={chain_multi['status']}(n={chain_multi['n_contracts']})")

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
        chain_0dte=data.get("option_chain_0dte", {}),
        chain_multi=data.get("option_chain_multi", {}),
        spot=data.get("spx_spot"),
        fecha=data.get("fecha"),
    )

    d_score = (slope["score"] + ratio["score"] + gap["score"]
               + net_gex["score_gex"] + net_gex["score_flip"])
    v_score = ivr["score"] + atr_ratio["score"]

    premarket_indicators = {
        "fecha":           data.get("fecha"),
        "vix_vxv_slope":   slope,
        "vix9d_vix_ratio": ratio,
        "overnight_gap":   gap,
        "ivr":             ivr,
        "atr_ratio":       atr_ratio,
        "net_gex":         net_gex,
        "d_score":         d_score,
        "v_score":         v_score,
        "spx_prev_close":  spx_spot,   # cierre anterior — necesario para IND-OPEN-05
    }

    # Guardar indicators.json con namespace
    indicators_out = {"fecha": data.get("fecha"), "premarket": premarket_indicators}
    existing = _read_json(out / "indicators.json")
    existing.update(indicators_out)
    (out / "indicators.json").write_text(json.dumps(existing, indent=2))

    print(f"[calc] slope={slope['signal']}({slope['score']})  "
          f"ratio={ratio['signal']}({ratio['score']})  "
          f"gap={gap['signal']}({gap['score']})  "
          f"gex={net_gex['signal_gex']}({net_gex['score_gex']})  "
          f"flip={net_gex['signal_flip']}({net_gex['score_flip']})  "
          f"ivr={ivr['signal']}({ivr['score']})  "
          f"atr={atr_ratio['signal']}({atr_ratio['score']})  "
          f"D={d_score}  V={v_score}")

    return premarket_indicators


def run_open_phase(out: Path, window_minutes: int) -> dict:
    """Fetch intraday y cálculo de indicadores open phase. Devuelve el dict de indicadores."""
    # Paso 1: fetch intraday
    intraday     = fetch_spx_intraday(window_minutes)
    vix_intraday = fetch_vix_intraday(window_minutes)

    spx_spot = None
    if intraday.get("ohlcv"):
        spx_spot = intraday["ohlcv"][-1]["Close"]

    es_quote    = fetch_es_quote()
    chain_0dte  = fetch_option_chain(
        "SPXW", days_ahead=0, max_strikes=GEX_MAX_STRIKES, spot=spx_spot
    )

    open_data = {
        "spx_intraday":       intraday,
        "spx_spot":           spx_spot,
        "es":                 es_quote,
        "option_chain_0dte":  chain_0dte,
    }

    # Actualizar data.json con sección open
    existing_data = _read_json(out / "data.json")
    existing_data["open"] = open_data
    (out / "data.json").write_text(json.dumps(existing_data, indent=2))

    print(f"[fetch-open] intraday={intraday['status']}(bars={intraday['bars']}) "
          f"vix_intraday={vix_intraday['status']}(bars={vix_intraday['bars']}) "
          f"es={es_quote['status']} "
          f"chain_0dte={chain_0dte['status']}(n={chain_0dte['n_contracts']})")

    # Paso 2: calcular indicadores open
    vwap      = calc_vwap_position(intraday)
    vix_delta = calc_vix_delta_open(vix_intraday)

    # Dependencia inter-fase: leer premarket para range expansion, gap behavior y realized vol
    premarket_ind = _read_json(out / "indicators.json").get("premarket", {})
    range_exp     = calc_range_expansion(intraday, premarket_ind)
    gap_beh       = calc_gap_behavior(intraday, premarket_ind)
    realized_vol  = calc_realized_vol_open(intraday, premarket_ind)

    d_score_open = vwap["score"] + gap_beh["score"]
    v_score_open = vix_delta["score"] + range_exp["score"] + realized_vol["score"]

    open_indicators = {
        "vwap_position":     vwap,
        "vix_delta_open":    vix_delta,
        "range_expansion":   range_exp,
        "gap_behavior":      gap_beh,
        "realized_vol_open": realized_vol,
        "d_score":           d_score_open,
        "v_score":           v_score_open,
        "window_minutes":    window_minutes,
    }

    # Actualizar indicators.json con sección open
    existing_ind = _read_json(out / "indicators.json")
    existing_ind["open"] = open_indicators
    (out / "indicators.json").write_text(json.dumps(existing_ind, indent=2))

    print(f"[calc-open] vwap={vwap['signal']}({vwap['score']})  "
          f"gap_beh={gap_beh['signal']}({gap_beh['score']})  "
          f"vix_delta={vix_delta['signal']}({vix_delta['score']})  "
          f"range_exp={range_exp['signal']}({range_exp['score']})  "
          f"realized_vol={realized_vol['signal']}({realized_vol['score']})  "
          f"D={d_score_open}  V={v_score_open}")

    return open_indicators


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


def _read_json(path: Path) -> dict:
    """Lee un JSON si existe, o devuelve dict vacío."""
    if path.exists():
        return json.loads(path.read_text())
    return {}


def _parse_args():
    parser = argparse.ArgumentParser(
        description="Pipeline de análisis pre-apertura SPX 0DTE"
    )
    parser.add_argument(
        "--phase",
        choices=["premarket", "open"],
        default="premarket",
        help="Fase a ejecutar (default: premarket)",
    )
    parser.add_argument(
        "--window",
        type=int,
        default=30,
        metavar="MINUTOS",
        help="Minutos de ventana para open phase (default: 30)",
    )
    parser.add_argument(
        "--notify",
        action="store_true",
        default=False,
        help="Enviar resultado a Telegram tras el pipeline (requiere TELEGRAM_BOT_TOKEN en .env)",
    )
    return parser.parse_args()


def main():
    args = _parse_args()
    out = Path("outputs")
    out.mkdir(exist_ok=True)

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


if __name__ == "__main__":
    main()
