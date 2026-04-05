"""
Trazabilidad de cálculos diarios — append a logs/history.jsonl.

Funciones públicas:
  append_record(record, path)  — añade una línea JSON al fichero JSONL
  fill_outcomes(es_prev_close, fecha_ayer, path) — rellena outcome_* del día anterior
"""
import json
from pathlib import Path


HISTORY_PATH = Path("logs/history.jsonl")


def append_record(record: dict, path: Path = HISTORY_PATH) -> None:
    """Añade un registro al fichero JSONL. Crea el fichero (y el directorio) si no existe."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def fill_outcomes(es_prev_close: float, fecha_ayer: str,
                  path: Path = HISTORY_PATH) -> int:
    """
    Busca en history.jsonl los registros de fecha_ayer y rellena los campos outcome_*.

    Para cada registro de ayer:
      - outcome_spx_close      = es_prev_close
      - outcome_spx_change_pct = (spx_close - spot_ref) / spot_ref * 100
      - outcome_direction      = +1 / -1 / 0

    La referencia de precio (`spot_ref`) depende de la fase:
      - premarket: campo `spot` (precio SPX en el momento del cálculo premarket)
      - open:      campo `spot_open` (precio de apertura a las 09:30 ET)

    Devuelve el número de registros actualizados.
    Si el fichero no existe, devuelve 0 sin error.
    """
    if not path.exists():
        return 0

    lines = path.read_text(encoding="utf-8").splitlines()
    updated = 0

    new_lines = []
    for line in lines:
        if not line.strip():
            new_lines.append(line)
            continue

        rec = json.loads(line)
        if rec.get("fecha") == fecha_ayer and rec.get("outcome_spx_close") is None:
            phase = rec.get("phase")
            spot_ref = None
            if phase == "premarket":
                spot_ref = rec.get("spot")
            elif phase == "open":
                spot_ref = rec.get("spot_open")

            rec["outcome_spx_close"] = es_prev_close

            if spot_ref and spot_ref != 0:
                change_pct = round((es_prev_close - spot_ref) / spot_ref * 100, 4)
                rec[_change_key(phase)] = change_pct
                rec["outcome_direction"] = _direction(change_pct)
            else:
                rec[_change_key(phase)] = None
                rec["outcome_direction"] = None

            updated += 1

        new_lines.append(json.dumps(rec, ensure_ascii=False))

    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return updated


def _change_key(phase: str) -> str:
    return "outcome_spx_change_from_open_pct" if phase == "open" else "outcome_spx_change_pct"


def _direction(change_pct: float) -> int:
    if change_pct > 0:
        return 1
    if change_pct < 0:
        return -1
    return 0
