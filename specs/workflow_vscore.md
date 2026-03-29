# Spec: Integración IVR y construcción del V-Score

## Estado
[ ] En desarrollo

## Propósito
Extender el pipeline existente para incorporar el indicador IV Rank (IVR) y calcular
el primer V-Score (score de volatilidad), paralelo al D-Score ya implementado.

El V-Score responde a la pregunta: ¿tiene sentido estructural vender prima hoy?
El D-Score responde a: ¿cuál es el sesgo direccional del mercado?
Ambos scores se muestran juntos en el scorecard final.

Referencia: `specs/ind_ivr.md` — leer antes de implementar cualquier parte de esta spec.

---

## Cambios en el pipeline

```
fetch_market_data.py  →  outputs/data.json  →  calculate_indicators.py  →  outputs/indicators.json  →  generate_scorecard.py
       ↑                        ↑                          ↑                           ↑
  + fetch_vix_history()   + vix_history{}            + calc_ivr()              + ivr: {...}
                                                                                + v_score: int
```

---

## 1. scripts/fetch_market_data.py

### Añadir: `fetch_vix_history() -> dict`

Nueva función que descarga el historial diario del VIX del último año.
Se llama **por separado** de `fetch_vix_term_structure()` porque los otros
indicadores del pipeline no necesitan datos históricos.

```python
def fetch_vix_history() -> dict:
    """
    Descarga el historial diario de cierre del VIX del último año (≈ 252 días hábiles).
    Devuelve mínimo y máximo del periodo para calcular el IV Rank.
    """
```

**Salida del dict:**
```python
{
    "vix_min_52w": float,       # mínimo del VIX en los últimos 252 días
    "vix_max_52w": float,       # máximo del VIX en los últimos 252 días
    "dias_disponibles": int,    # número de días con datos (para validación)
    "fecha": str,               # fecha del último dato disponible, YYYY-MM-DD
    "status": str               # "OK" | "ERROR"
}
```

**Comportamiento:**
- Usa `yfinance.download("^VIX", period="1y", auto_adjust=False)`
- Extrae la columna `"Close"` y elimina NaN antes de calcular min/max
- Si `dias_disponibles < 50` → `status = "INSUFFICIENT_DATA"`, min/max = `None`
- Si yfinance lanza excepción → `status = "ERROR"`, todos los valores numéricos = `None`

### Actualizar: bloque `__main__`

Añadir la llamada a `fetch_vix_history()` y guardar su resultado en `data.json`
bajo la clave `"vix_history"`.

```python
if __name__ == "__main__":
    import json
    from pathlib import Path

    data = fetch_vix_term_structure()
    data["vix_history"] = fetch_vix_history()

    out = Path("outputs")
    out.mkdir(exist_ok=True)
    (out / "data.json").write_text(json.dumps(data, indent=2))
    print(f"[fetch] status={data['status']} fecha={data['fecha']} "
          f"vix_history={data['vix_history']['status']}")
```

### Salida actualizada: `outputs/data.json`
```json
{
  "vix9d": 13.42,
  "vix": 16.05,
  "vxv": 18.30,
  "vvix": 88.12,
  "fecha": "2026-03-28",
  "status": "OK",
  "vix_history": {
    "vix_min_52w": 10.62,
    "vix_max_52w": 65.73,
    "dias_disponibles": 252,
    "fecha": "2026-03-27",
    "status": "OK"
  }
}
```

---

## 2. scripts/calculate_indicators.py

### Añadir: `calc_ivr(vix_current: dict, vix_history: dict) -> dict`

Implementar según la spec completa de `specs/ind_ivr.md`.

Recibe dos dicts:
- `vix_current`: salida de `fetch_vix_term_structure()` — usa la clave `"vix"`
- `vix_history`: salida de `fetch_vix_history()` — usa `"vix_min_52w"` y `"vix_max_52w"`

### Añadir: cálculo del V-Score

El V-Score es la suma de los scores de todos los indicadores de volatilidad.
En esta versión inicial solo incluye IVR. El diseño debe permitir añadir
indicadores futuros sin refactorizar.

```python
v_score = ivr["score"]
```

### Actualizar: bloque `__main__`

```python
if __name__ == "__main__":
    import json
    from pathlib import Path

    data = json.loads(Path("outputs/data.json").read_text())

    slope = calc_vix_vxv_slope(data)
    ratio = calc_vix9d_vix_ratio(data)
    ivr   = calc_ivr(data, data.get("vix_history", {}))

    d_score = slope["score"] + ratio["score"]
    v_score = ivr["score"]

    indicators = {
        "fecha": data.get("fecha"),
        "vix_vxv_slope":   slope,
        "vix9d_vix_ratio": ratio,
        "ivr":             ivr,
        "d_score":         d_score,
        "v_score":         v_score,
    }

    Path("outputs/indicators.json").write_text(json.dumps(indicators, indent=2))
    print(f"[calc] slope={slope['signal']}({slope['score']})  "
          f"ratio={ratio['signal']}({ratio['score']})  "
          f"ivr={ivr['signal']}({ivr['score']})  "
          f"D={d_score}  V={v_score}")
```

### Salida actualizada: `outputs/indicators.json`
```json
{
  "fecha": "2026-03-28",
  "vix_vxv_slope": {
    "vix": 16.05, "vxv": 18.30, "ratio": 0.8770,
    "score": 1, "signal": "CONTANGO_SUAVE", "status": "OK", "fecha": "2026-03-28"
  },
  "vix9d_vix_ratio": {
    "vix9d": 13.42, "vix": 16.05, "ratio": 0.8362,
    "score": 2, "signal": "CONTANGO_FUERTE", "status": "OK", "fecha": "2026-03-28"
  },
  "ivr": {
    "vix": 16.05, "vix_min_52w": 10.62, "vix_max_52w": 65.73,
    "ivr": 9.77, "score": -2, "signal": "PRIMA_MUY_BAJA", "status": "OK", "fecha": "2026-03-28"
  },
  "d_score": 3,
  "v_score": -2
}
```

---

## 3. scripts/generate_scorecard.py

### Actualizar: `print_scorecard(indicators: dict) -> None`

Extender la función existente para mostrar el bloque de V-Score debajo del D-Score.

### Formato de salida en terminal
```
============================================================
  PRE-MARKET SCORECARD — 2026-03-28
============================================================

  [D-SCORE — DIRECCIONAL]
  Indicador            Valor                  Score  Signal
  ----------------------------------------------------------
  VIX/VXV Slope        VIX=16.05  VXV=18.30  +1     CONTANGO_SUAVE
  VIX9D/VIX Ratio      VIX9D=13.42  VIX=16.05  +2   CONTANGO_FUERTE
  ----------------------------------------------------------
  D-Score (direccional):  +3

  [V-SCORE — VOLATILIDAD]
  Indicador            Valor                  Score  Signal
  ----------------------------------------------------------
  IV Rank (IVR)        VIX=16.05  IVR=9.77%  -2     PRIMA_MUY_BAJA
  ----------------------------------------------------------
  V-Score (volatilidad):  -2

============================================================
```

**Reglas de formato:**
- Si un indicador tiene `status != "OK"`, mostrar `"[status]"` en lugar de los valores numéricos
- D-Score y V-Score se muestran siempre, aunque algún indicador haya fallado
- No usar librerías externas — solo `print()` y stdlib

---

## 4. scripts/run.py

### Actualizar: `main()`

Añadir la llamada a `fetch_vix_history()` y `calc_ivr()`.

```python
from fetch_market_data import fetch_vix_term_structure, fetch_vix_history
from calculate_indicators import calc_vix_vxv_slope, calc_vix9d_vix_ratio, calc_ivr
from generate_scorecard import print_scorecard

def main():
    # Paso 1: fetch
    data = fetch_vix_term_structure()
    data["vix_history"] = fetch_vix_history()
    out = Path("outputs")
    out.mkdir(exist_ok=True)
    (out / "data.json").write_text(json.dumps(data, indent=2))
    if data["status"] != "OK":
        print(f"[ERROR] fetch: status={data['status']}", file=sys.stderr)
        sys.exit(1)

    # Paso 2: calcular indicadores
    slope = calc_vix_vxv_slope(data)
    ratio = calc_vix9d_vix_ratio(data)
    ivr   = calc_ivr(data, data.get("vix_history", {}))

    indicators = {
        "fecha":           data.get("fecha"),
        "vix_vxv_slope":   slope,
        "vix9d_vix_ratio": ratio,
        "ivr":             ivr,
        "d_score":         slope["score"] + ratio["score"],
        "v_score":         ivr["score"],
    }
    (out / "indicators.json").write_text(json.dumps(indicators, indent=2))

    # Paso 3: scorecard
    print_scorecard(indicators)
```

**Nota sobre errores en fetch_vix_history:**
Si `vix_history["status"] != "OK"`, el pipeline **no aborta** — `calc_ivr` manejará
el error internamente y devolverá `status="INSUFFICIENT_DATA"` o `"ERROR"` con `score=0`.
Solo se aborta si `fetch_vix_term_structure` falla (datos intradiarios del VIX actual).

---

## 5. Tests

### Nuevo fichero: `tests/test_workflow_vscore.py`

Tests de integración que verifican que todos los componentes encajan correctamente.
Usan mocks para evitar llamadas reales a yfinance.

| Test | Descripción | Verificación |
|------|-------------|--------------|
| Pipeline completo OK | data.json + indicators.json correctos | d_score y v_score presentes y con tipos int |
| IVR con historial insuficiente | `fetch_vix_history` devuelve INSUFFICIENT_DATA | v_score = 0 en indicators.json |
| IVR con rango cero | vix_min_52w == vix_max_52w | ivr["status"] = "ERROR", v_score = 0 |
| Scorecard muestra ambos scores | indicators dict completo | output contiene "D-Score" y "V-Score" |
| fetch_vix_history falla | status = "ERROR" | pipeline continúa, scorecard muestra error en IVR |

---

## Orden de implementación

1. `fetch_vix_history()` en `fetch_market_data.py`
2. Actualizar bloque `__main__` de `fetch_market_data.py`
3. `calc_ivr()` en `calculate_indicators.py` (según `specs/ind_ivr.md`)
4. Actualizar bloque `__main__` de `calculate_indicators.py` (añadir ivr, d_score, v_score)
5. Actualizar `print_scorecard()` en `generate_scorecard.py`
6. Actualizar `main()` en `run.py`
7. `tests/test_ind_ivr.py` (tests unitarios del indicador — ver `specs/ind_ivr.md`)
8. `tests/test_workflow_vscore.py` (tests de integración del pipeline)
9. Ejecutar `uv run pytest` y confirmar que todos los tests pasan

---

## Dependencias

Sin dependencias nuevas. El historial del VIX se obtiene con `yfinance` (ya en `pyproject.toml`).

## Verificación final

1. `uv run python scripts/run.py` imprime scorecard con bloque D-Score y bloque V-Score
2. `outputs/indicators.json` contiene claves `ivr`, `d_score` y `v_score`
3. `outputs/data.json` contiene la clave `vix_history` con `status: "OK"`
4. `uv run pytest` → todos los tests pasan, incluidos los nuevos
5. Si se ejecuta sin conexión a internet el pipeline falla en fetch con mensaje claro

## Prompt de inicio para Claude Code
```
Lee specs/workflow_vscore.md y specs/ind_ivr.md completamente antes de escribir ningún código.

Implementa en el orden exacto indicado en la sección "Orden de implementación":

1. fetch_vix_history() en scripts/fetch_market_data.py
2. Actualizar __main__ de fetch_market_data.py
3. calc_ivr() en scripts/calculate_indicators.py
4. Actualizar __main__ de calculate_indicators.py con ivr, d_score y v_score
5. Actualizar print_scorecard() en scripts/generate_scorecard.py para mostrar V-Score
6. Actualizar main() en scripts/run.py
7. tests/test_ind_ivr.py — todos los casos de specs/ind_ivr.md
8. tests/test_workflow_vscore.py — tests de integración
9. uv run pytest → confirma que todos los tests pasan

No implementes nada fuera de lo descrito en estas dos specs.
```
