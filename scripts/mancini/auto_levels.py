"""
Niveles técnicos autónomos para /ES — calculados sin tweets de Mancini.

Calcula Prior Day/Week/Month H/L/C, pivot points clásicos y round numbers.
Sirve como fallback cuando no hay plan de Mancini disponible.
Los niveles GEX se notifican por separado en la apertura (~9:35 ET).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, asdict
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf
from zoneinfo import ZoneInfo

AUTO_LEVELS_PATH = Path("outputs/mancini_auto_levels.json")
_ET = ZoneInfo("America/New_York")


@dataclass
class TechnicalLevel:
    value: float
    label: str    # "PDH", "PWL", "PP_D", "R1_W", "RND_5350", "FLIP", etc.
    group: str    # "daily", "weekly", "monthly", "round", "gex"
    priority: int  # 1 (alta) a 3 (baja)


@dataclass
class AutoLevels:
    fecha: str                    # YYYY-MM-DD
    spot: float                   # precio /ES al calcular
    levels: list[TechnicalLevel]  # ordenados por value desc
    calculated_at: str            # ISO timestamp


def fetch_weekly_ohlc(symbol: str = "^GSPC", bars: int = 4) -> pd.DataFrame | None:
    """Descarga barras semanales via yfinance. Retorna DataFrame con OHLC o None si falla."""
    try:
        df = yf.download(symbol, period=f"{bars * 7 + 14}d", interval="1wk",
                         auto_adjust=True, progress=False)
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        df = df[["Open", "High", "Low", "Close"]].dropna()
        return df.tail(bars)
    except Exception:
        return None


def fetch_monthly_ohlc(symbol: str = "^GSPC", bars: int = 4) -> pd.DataFrame | None:
    """Descarga barras mensuales via yfinance. Retorna DataFrame con OHLC o None si falla."""
    try:
        df = yf.download(symbol, period=f"{bars * 31 + 31}d", interval="1mo",
                         auto_adjust=True, progress=False)
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        df = df[["Open", "High", "Low", "Close"]].dropna()
        return df.tail(bars)
    except Exception:
        return None


def fetch_overnight_ohlc(symbol: str = "ES=F") -> tuple[float, float] | None:
    """
    Calcula el ONH/ONL de la sesión Globex actual (18:00 ET ayer – 09:29 ET hoy).

    Descarga barras horarias de /ES via yfinance y filtra las que caen dentro
    del rango overnight. Retorna (onh, onl) en términos /ES (sin basis adjustment)
    o None si no hay barras suficientes o falla la descarga.
    """
    try:
        df = yf.download(symbol, period="2d", interval="1h",
                         auto_adjust=True, progress=False)
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        df = df[["High", "Low"]].dropna()

        # Convertir index a ET
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        df.index = df.index.tz_convert(_ET)

        now_et = datetime.now(_ET)
        today_et = now_et.date()
        yesterday_et = (now_et - pd.Timedelta(days=1)).date()

        # Ventana overnight: 18:00 ET ayer → 09:29 ET hoy
        window_start = datetime(yesterday_et.year, yesterday_et.month, yesterday_et.day,
                                18, 0, 0, tzinfo=_ET)
        window_end   = datetime(today_et.year, today_et.month, today_et.day,
                                9, 29, 0, tzinfo=_ET)

        overnight = df[(df.index >= window_start) & (df.index <= window_end)]
        if overnight.empty:
            return None

        onh = round(float(overnight["High"].max()), 2)
        onl = round(float(overnight["Low"].min()), 2)
        return onh, onl
    except Exception:
        return None


def calc_pivot_points(high: float, low: float, close: float) -> dict[str, float]:
    """Calcula PP, R1, R2, S1, S2 clásicos desde OHLC previo."""
    pp = (high + low + close) / 3
    r1 = 2 * pp - low
    r2 = pp + (high - low)
    s1 = 2 * pp - high
    s2 = pp - (high - low)
    return {
        "PP": round(pp, 2),
        "R1": round(r1, 2),
        "R2": round(r2, 2),
        "S1": round(s1, 2),
        "S2": round(s2, 2),
    }


def calc_round_numbers(spot: float, step: int = 25, pct: float = 0.03) -> list[float]:
    """Retorna múltiplos de `step` dentro del rango spot ± pct*spot."""
    margin = spot * pct
    lo = spot - margin
    hi = spot + margin
    first = math.ceil(lo / step) * step
    levels = []
    v = first
    while v <= hi:
        levels.append(round(float(v), 2))
        v += step
    return levels


def _dedup_levels(levels: list[TechnicalLevel], threshold: float = 2.0) -> list[TechnicalLevel]:
    """Elimina niveles muy próximos (<= threshold pts), conservando el de mayor prioridad."""
    # Ordenar por prioridad ascendente (1 = mayor), valor secundario
    sorted_lvls = sorted(levels, key=lambda l: (l.priority, l.value))
    result: list[TechnicalLevel] = []
    for lvl in sorted_lvls:
        if not any(abs(lvl.value - r.value) <= threshold for r in result):
            result.append(lvl)
    return result


def build_auto_levels(
    daily_ohlcv: list[dict],
    weekly_df: pd.DataFrame | None,
    monthly_df: pd.DataFrame | None,
    es_spot: float,
    spx_spot: float | None = None,
    overnight: tuple[float, float] | None = None,
) -> AutoLevels:
    """
    Ensambla todos los niveles técnicos en un AutoLevels.

    spx_spot: cierre SPX cash de la misma sesión que es_spot.
    Si se proporciona, los niveles calculados desde SPX (daily, weekly, monthly)
    se multiplican por el ratio es_spot/spx_spot para convertirlos a términos /ES,
    el mismo sistema de referencia que usa Mancini.
    Los round numbers y overnight no se ajustan porque ya están en términos /ES.

    overnight: tupla (onh, onl) del rango Globex. Ya en /ES — no se aplica basis.
    Los niveles GEX se notifican por separado en apertura (~9:35 ET).
    """
    # Ratio de conversión SPX cash → /ES. Sin spx_spot, no se ajusta.
    basis = (es_spot / spx_spot) if spx_spot and spx_spot > 0 else 1.0

    def adj(v: float) -> float:
        return round(v * basis, 2)

    levels: list[TechnicalLevel] = []

    # ── Grupo A: niveles diarios ────────────────────────────────────────
    if len(daily_ohlcv) >= 2:
        prev = daily_ohlcv[-2]  # penúltimo = día anterior completo
        pdh, pdl, pdc = adj(prev["High"]), adj(prev["Low"]), adj(prev["Close"])
        levels += [
            TechnicalLevel(value=pdh, label="PDH", group="daily", priority=2),
            TechnicalLevel(value=pdl, label="PDL", group="daily", priority=2),
            TechnicalLevel(value=pdc, label="PDC", group="daily", priority=2),
        ]
        for label, val in calc_pivot_points(pdh, pdl, pdc).items():
            levels.append(TechnicalLevel(value=val, label=f"{label}_D", group="daily", priority=2))

    # ── Grupo B: niveles semanales ──────────────────────────────────────
    if weekly_df is not None and len(weekly_df) >= 2:
        pw = weekly_df.iloc[-2]  # semana anterior completa
        pwh = adj(float(pw["High"]))
        pwl = adj(float(pw["Low"]))
        pwc = adj(float(pw["Close"]))
        levels += [
            TechnicalLevel(value=pwh, label="PWH", group="weekly", priority=1),
            TechnicalLevel(value=pwl, label="PWL", group="weekly", priority=1),
            TechnicalLevel(value=pwc, label="PWC", group="weekly", priority=1),
        ]
        pivots_w = calc_pivot_points(pwh, pwl, pwc)
        levels.append(TechnicalLevel(value=pivots_w["PP"], label="PP_W", group="weekly", priority=1))
        levels.append(TechnicalLevel(value=pivots_w["R1"], label="R1_W", group="weekly", priority=1))
        levels.append(TechnicalLevel(value=pivots_w["S1"], label="S1_W", group="weekly", priority=1))

    # ── Grupo C: niveles mensuales ──────────────────────────────────────
    if monthly_df is not None and len(monthly_df) >= 2:
        pm = monthly_df.iloc[-2]  # mes anterior completo
        levels += [
            TechnicalLevel(value=adj(float(pm["High"])),  label="PMH", group="monthly", priority=1),
            TechnicalLevel(value=adj(float(pm["Low"])),   label="PML", group="monthly", priority=1),
            TechnicalLevel(value=adj(float(pm["Close"])), label="PMC", group="monthly", priority=1),
        ]

    # ── Grupo D: round numbers (ya en /ES — no se ajustan) ─────────────
    for rnd in calc_round_numbers(es_spot):
        levels.append(TechnicalLevel(
            value=rnd,
            label=f"RND_{int(rnd)}",
            group="round",
            priority=3,
        ))

    # ── Grupo E: Overnight High/Low (ya en /ES — no se ajustan) ──────
    if overnight is not None:
        onh, onl = overnight
        levels.append(TechnicalLevel(value=onh, label="ONH", group="overnight", priority=2))
        levels.append(TechnicalLevel(value=onl, label="ONL", group="overnight", priority=2))

    levels = _dedup_levels(levels)
    levels.sort(key=lambda l: l.value, reverse=True)

    return AutoLevels(
        fecha=str(date.today()),
        spot=round(es_spot, 2),
        levels=levels,
        calculated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def load_auto_levels(path: Path = AUTO_LEVELS_PATH) -> AutoLevels | None:
    """Lee mancini_auto_levels.json. Retorna None si no existe o hay error."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        levels = [TechnicalLevel(**lvl) for lvl in data.get("levels", [])]
        return AutoLevels(
            fecha=data["fecha"],
            spot=data["spot"],
            levels=levels,
            calculated_at=data["calculated_at"],
        )
    except (FileNotFoundError, KeyError, TypeError, json.JSONDecodeError):
        return None


def save_auto_levels(levels: AutoLevels, path: Path = AUTO_LEVELS_PATH) -> None:
    """Serializa y escribe mancini_auto_levels.json."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "fecha": levels.fecha,
        "spot": levels.spot,
        "levels": [asdict(l) for l in levels.levels],
        "calculated_at": levels.calculated_at,
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def calculate_and_save(
    data_path: str = "outputs/data.json",
    output_path: Path = AUTO_LEVELS_PATH,
) -> AutoLevels | None:
    """
    Lee data.json, calcula niveles técnicos (sin GEX),
    persiste en mancini_auto_levels.json y retorna el objeto.
    Retorna None si faltan datos esenciales.
    Los niveles GEX se notifican por separado en apertura (~9:35 ET).
    """
    try:
        data = json.loads(Path(data_path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None

    # Extraer OHLCV diario (soporta formato antiguo y nuevo con namespace)
    premarket = data.get("premarket", data)
    spx_ohlcv = premarket.get("spx_ohlcv", {})
    daily_ohlcv = spx_ohlcv.get("ohlcv") or []

    # Precio spot — en orden de preferencia
    es_spot = (
        (premarket.get("es") or {}).get("es_premarket")
        or (premarket.get("es_prev") or {}).get("es_prev_close")
        or premarket.get("spx_spot")
    )
    if es_spot is None:
        return None

    weekly_df = fetch_weekly_ohlc()
    monthly_df = fetch_monthly_ohlc()
    overnight = fetch_overnight_ohlc()

    spx_spot = premarket.get("spx_spot")
    auto = build_auto_levels(
        daily_ohlcv, weekly_df, monthly_df,
        float(es_spot),
        spx_spot=float(spx_spot) if spx_spot else None,
        overnight=overnight,
    )
    save_auto_levels(auto, output_path)
    return auto
