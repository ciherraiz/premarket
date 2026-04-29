"""
Snapshots intraday del perfil GEX 0DTE.

Captura el GEX por strike de la cadena 0DTE en el momento actual,
persiste en JSONL y detecta desplazamientos de niveles clave.

El GEX se calcula siempre en términos del índice SPX cash (^GSPC).
El campo `es_basis` (ratio /ES / SPX) permite traducir los niveles
clave a términos /ES para uso operativo en el monitor Mancini.
"""
from __future__ import annotations

import json
import sys
import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.calculate_indicators import calc_net_gex

ET = ZoneInfo("America/New_York")

SNAPSHOT_PATH_TPL    = "outputs/gex_snapshots_{date}.jsonl"
SESSION_START_ET     = (9, 30)
SESSION_END_ET       = (16, 0)
GEX_SHIFT_ALERT_PTS  = 10


def _now_et() -> datetime:
    return datetime.now(ET)


def _fetch_spx_spot() -> float | None:
    """
    Precio cash del SPX (^GSPC) via yfinance.
    Solo retorna valor durante la sesión regular (9:30–16:00 ET).
    Fuera de sesión retorna None — el GEX no se calcula pre/post-market.
    """
    now = _now_et()
    session_start = now.replace(hour=SESSION_START_ET[0], minute=SESSION_START_ET[1],
                                second=0, microsecond=0)
    session_end   = now.replace(hour=SESSION_END_ET[0],   minute=SESSION_END_ET[1],
                                second=0, microsecond=0)
    if not (session_start <= now <= session_end):
        return None
    try:
        import yfinance as yf
        price = yf.Ticker("^GSPC").fast_info.get("last_price")
        if price and float(price) > 0:
            return float(price)
    except Exception:
        pass
    return None


def _error_snapshot(spot: float | None, reason: str,
                    es_price: float | None = None) -> dict:
    now = _now_et()
    return {
        "ts":                now.strftime("%Y-%m-%dT%H:%M:%S"),
        "ts_et":             now.isoformat(),
        "spot":              spot,
        "es_basis":          round(es_price / spot, 6) if (es_price and spot) else None,
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
        client:   TastyTradeClient autenticado, o None para crear uno (CLI).
        spot:     Precio cash del SPX (^GSPC). Si es None, se obtiene via yfinance.
                  El GEX siempre se calcula en términos SPX — no usar /ES como spot.
        es_price: Precio del futuro /ES (opcional). Solo sirve para calcular el
                  es_basis (ratio de conversión SPX → /ES) que se guarda en el snapshot.

    Returns:
        dict con el snapshot completo. status != "OK" si hay error.
    """
    try:
        # Resolver cliente
        if client is None:
            try:
                from scripts.tastytrade_client import TastyTradeClient
                client = TastyTradeClient()
            except Exception:
                return _error_snapshot(spot, "MISSING_DATA", es_price)

        # Resolver spot SPX cash
        if spot is None or spot <= 0:
            spot = _fetch_spx_spot()

        if not spot or spot <= 0:
            return _error_snapshot(None, "OUT_OF_SESSION", es_price)

        # Basis /ES / SPX para traducción de niveles a términos operativos
        es_basis = round(es_price / spot, 6) if (es_price and es_price > 0) else None

        today = date.today()
        fecha = str(today)

        # Fetch cadena 0DTE SPXW
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

        # Calcular GEX en términos SPX (misma cadena 0dte para presión intraday)
        gex = calc_net_gex(chain_0dte, chain_0dte, spot=spot, fecha=fecha)

        now = _now_et()
        return {
            "ts":                now.strftime("%Y-%m-%dT%H:%M:%S"),
            "ts_et":             now.isoformat(),
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
        }

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
    Retorna un dict con los campos del shift (incluyendo es_basis para traducción),
    o None si no hay shift relevante.
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


if __name__ == "__main__":
    spx = _fetch_spx_spot()
    if spx is None:
        print("Mercado fuera de sesión (9:30–16:00 ET) — GEX no disponible.")
        sys.exit(0)

    # Obtener /ES para calcular el basis de traducción
    es_price = None
    try:
        from scripts.tastytrade_client import TastyTradeClient
        client = TastyTradeClient()
        q = client.get_future_quote("/ES")
        if q.get("status") == "OK":
            es_price = q.get("mark") or q.get("last") or None
    except Exception:
        client = None

    snapshot = take_gex_snapshot(client=client if "client" in dir() else None,
                                 spot=spx, es_price=es_price)
    print(json.dumps(snapshot, indent=2, ensure_ascii=False))
    if snapshot.get("status") == "OK":
        save_snapshot(snapshot)
        print(f"\nSnapshot guardado en {SNAPSHOT_PATH_TPL.format(date=date.today().isoformat())}")
    else:
        print(f"\nError: {snapshot.get('status')}")
