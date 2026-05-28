"""
Snapshots intraday del perfil GEX 0DTE.

Captura el GEX por strike de la cadena 0DTE en el momento actual,
persiste en JSONL y detecta desplazamientos de niveles clave.
"""
from __future__ import annotations

import json
import sys
import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.calculate_indicators import calc_net_gex, calc_charm_exposure, calc_delta_exposure

ET = ZoneInfo("America/New_York")

SNAPSHOT_PATH_TPL    = "outputs/gex_snapshots_{date}.jsonl"
SESSION_START_ET     = (9, 30)
SESSION_END_ET       = (16, 0)
GEX_SHIFT_ALERT_PTS  = 10


def _now_et() -> datetime:
    return datetime.now(ET)


def _error_snapshot(spot: float | None, reason: str,
                    es_price: float | None = None) -> dict:
    now = _now_et()
    es_basis = round(es_price / spot, 6) if spot and es_price else None
    return {
        "ts":                now.strftime("%Y-%m-%dT%H:%M:%S"),
        "ts_et":             now.isoformat(),
        "spot":              spot,
        "es_basis":          es_basis,
        "net_gex_bn":        None,
        "signal_gex":        None,
        "regime_text":       "Régimen GEX no disponible",
        "flip_level":        None,
        "control_node":      None,
        "chop_zone_low":     None,
        "chop_zone_high":    None,
        "put_wall":          None,
        "call_wall":         None,
        "gex_by_strike":     {},
        "gex_pct_by_strike": {},
        "n_strikes":         0,
        "status":            reason,
    }


def take_gex_snapshot(client=None, spot: float | None = None,
                      es_price: float | None = None) -> dict:
    """
    Captura el perfil GEX 0DTE en el momento actual.

    Args:
        client:   TastyTradeClient autenticado, o None para crear uno nuevo (CLI).
        spot:     precio SPX cash (float) o None para obtenerlo via get_equity_quote.
        es_price: precio /ES (float) o None. Solo se usa para calcular es_basis.

    Returns:
        dict con el snapshot completo. status != "OK" si hay error.
        Incluye es_basis = round(es_price/spot, 6) para traducir niveles a /ES.
    """
    try:
        # Resolver cliente
        if client is None:
            try:
                from scripts.tastytrade_client import TastyTradeClient
                client = TastyTradeClient()
            except Exception:
                return _error_snapshot(spot, "MISSING_DATA", es_price)

        # Obtener SPX cash via TastyTrade
        if spot is None or spot <= 0:
            try:
                quote = client.get_equity_quote("SPX")
                if quote.get("status") == "OK":
                    spot = quote.get("last") or quote.get("mark")
            except Exception:
                pass

        if not spot or spot <= 0:
            return _error_snapshot(None, "MISSING_DATA", es_price)

        es_basis = round(es_price / spot, 6) if es_price and es_price > 0 else None

        today = date.today()
        fecha = str(today)

        # Fetch cadena 0DTE (SPXW) via TastyTrade
        try:
            contracts = client.get_option_chain(
                "SPXW", expiry=fecha, max_strikes=60, spot=spot
            )
        except Exception:
            return _error_snapshot(spot, "ERROR", es_price)

        chain_0dte = {
            "contracts":   contracts or [],
            "expiries":    [fecha] if contracts else [],
            "n_contracts": len(contracts) if contracts else 0,
            "status":      "OK" if contracts else "EMPTY_CHAIN",
        }

        # Calcular GEX
        gex   = calc_net_gex(chain_0dte, chain_0dte, spot=spot, fecha=fecha)
        charm = calc_charm_exposure(chain_0dte, spot, fecha)
        dex   = calc_delta_exposure(chain_0dte, spot, fecha)

        now = _now_et()
        snapshot = {
            "ts":                now.strftime("%Y-%m-%dT%H:%M:%S"),
            "ts_et":             now.isoformat(),
            "fecha":             fecha,
            "spot":              spot,
            "es_basis":          es_basis,
            "net_gex_bn":        gex.get("net_gex_bn"),
            "signal_gex":        gex.get("signal_gex"),
            "regime_text":       gex.get("regime_text", "Régimen GEX no disponible"),
            "flip_level":        gex.get("flip_level"),
            "control_node":      gex.get("control_node"),
            "chop_zone_low":     gex.get("chop_zone_low"),
            "chop_zone_high":    gex.get("chop_zone_high"),
            "put_wall":          gex.get("put_wall"),
            "call_wall":         gex.get("call_wall"),
            "gex_by_strike":     gex.get("gex_by_strike", {}),
            "gex_pct_by_strike": gex.get("gex_pct_by_strike", {}),
            "n_strikes":         gex.get("n_strikes", 0),
            "status":            gex.get("status", "ERROR"),
            # ── Dealer Flow fields (Fase 3) ───────────────────────────────
            "charm_by_strike":   charm.get("charm_by_strike", {}),
            "charm_total":       charm.get("charm_total"),
            "charm_signal":      charm.get("charm_signal"),
            "charm_pin_zone":    charm.get("charm_pin_zone"),
            "dex_by_strike":     dex.get("dex_by_strike", {}),
            "dex_total":         dex.get("dex_total"),
            "dex_signal":        dex.get("dex_signal"),
            "dex_flip":          dex.get("dex_flip"),
        }
        return snapshot

    except Exception:
        return _error_snapshot(spot, "ERROR", es_price)


def save_snapshot(snapshot: dict, date_str: str | None = None) -> None:
    """Añade el snapshot al fichero JSONL del día (append). Crea el fichero si no existe."""
    if date_str is None:
        date_str = date.today().isoformat()
    path = Path(SNAPSHOT_PATH_TPL.format(date=date_str))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(snapshot, ensure_ascii=False) + "\n")


def load_snapshots(date_str: str | None = None) -> list[dict]:
    """
    Carga todos los snapshots del día indicado.
    Retorna lista vacía si el fichero no existe o no hay líneas válidas.
    """
    if date_str is None:
        date_str = date.today().isoformat()
    path = Path(SNAPSHOT_PATH_TPL.format(date=date_str))
    if not path.exists():
        return []
    snapshots = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            snapshots.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return snapshots


def _level_shifted(prev_val: float | None, curr_val: float | None,
                   threshold: float) -> bool:
    """True si los valores difieren más del umbral, o si uno es None y el otro no."""
    if prev_val is None and curr_val is None:
        return False
    if prev_val is None or curr_val is None:
        return True  # cambio de régimen
    return abs(curr_val - prev_val) >= threshold


def detect_shift(prev: dict | None, curr: dict) -> dict | None:
    """
    Compara dos snapshots consecutivos y detecta desplazamientos significativos.

    Retorna un dict con los campos del shift, o None si no hay shift relevante.
    """
    if prev is None:
        return None

    flip_shifted = _level_shifted(
        prev.get("flip_level"), curr.get("flip_level"), GEX_SHIFT_ALERT_PTS
    )
    cn_shifted = _level_shifted(
        prev.get("control_node"), curr.get("control_node"), GEX_SHIFT_ALERT_PTS
    )

    if not flip_shifted and not cn_shifted:
        return None

    if flip_shifted and cn_shifted:
        shift_type = "BOTH"
    elif flip_shifted:
        shift_type = "FLIP_SHIFT"
    else:
        shift_type = "CONTROL_NODE_SHIFT"

    return {
        "type":        shift_type,
        "flip_prev":   prev.get("flip_level"),
        "flip_curr":   curr.get("flip_level"),
        "cn_prev":     prev.get("control_node"),
        "cn_curr":     curr.get("control_node"),
        "spot":        curr.get("spot"),
        "es_basis":    curr.get("es_basis"),
        "ts":          curr.get("ts", ""),
        "regime_text": curr.get("regime_text", ""),
    }


def calc_gex_change(ref_snapshot: dict, curr_snapshot: dict) -> dict:
    """
    Calcula el cambio de GEX por strike entre dos snapshots.

    El GEX Change muestra qué strikes están ganando o perdiendo relevancia
    durante la sesión respecto a un snapshot de referencia (apertura del día
    o el snapshot anterior).

    Args:
        ref_snapshot:  snapshot de referencia (p.ej. apertura del día)
        curr_snapshot: snapshot actual

    Returns:
        {
            "gex_change_by_strike": dict[str, float],  # gex_curr - gex_ref por strike
            "strikes_gaining":      list[float],        # top 5 strikes con GEX más positivo
            "strikes_losing":       list[float],        # top 5 strikes con GEX más negativo
            "net_change":           float,              # cambio neto total
            "ref_ts":               str,
            "curr_ts":              str,
        }
    """
    ref_gex  = ref_snapshot.get("gex_by_strike",  {})
    curr_gex = curr_snapshot.get("gex_by_strike", {})

    all_strikes = set(ref_gex.keys()) | set(curr_gex.keys())
    gex_change  = {
        s: (curr_gex.get(s, 0.0) or 0.0) - (ref_gex.get(s, 0.0) or 0.0)
        for s in all_strikes
    }

    sorted_changes = sorted(gex_change.items(), key=lambda x: x[1])
    strikes_losing  = [float(s) for s, v in sorted_changes[:5]  if v < 0]
    strikes_gaining = [float(s) for s, v in sorted_changes[-5:] if v > 0]
    net_change      = sum(gex_change.values())

    return {
        "gex_change_by_strike": {k: round(v, 6) for k, v in gex_change.items()},
        "strikes_gaining":      strikes_gaining,
        "strikes_losing":       strikes_losing,
        "net_change":           round(net_change, 4),
        "ref_ts":               ref_snapshot.get("ts", ""),
        "curr_ts":              curr_snapshot.get("ts", ""),
    }


if __name__ == "__main__":
    snapshot = take_gex_snapshot(client=None, spot=None)
    print(json.dumps(snapshot, indent=2, ensure_ascii=False))
    if snapshot.get("status") == "OK":
        save_snapshot(snapshot)
        print(f"\nSnapshot guardado en {SNAPSHOT_PATH_TPL.format(date=date.today().isoformat())}")
    else:
        print(f"\nError: {snapshot.get('status')}")
