# Spec: Workflow Pipeline Completo

## Estado
[Development]

## Propósito
Conectar los scripts existentes en un pipeline ejecutable de extremo a extremo:
`fetch_market_data.py` → `outputs/data.json` → `calculate_indicators.py` → `outputs/indicators.json` → `generate_scorecard.py`

El orquestador `run.py` ejecuta los tres pasos en secuencia con un único comando.

---

## 1. scripts/fetch_market_data.py

### Estado actual
La función `fetch_vix_term_structure() -> dict` ya está implementada.
Descarga `^VIX9D`, `^VIX`, `^VXV`, `^VVIX` de yfinance en una sola llamada.

### Añadir: bloque `__main__`
Cuando se ejecuta como script, guarda el resultado en `outputs/data.json`.

```python
if __name__ == "__main__":
    import json
    from pathlib import Path

    data = fetch_vix_term_structure()
    out = Path("outputs")
    out.mkdir(exist_ok=True)
    (out / "data.json").write_text(json.dumps(data, indent=2))
    print(f"[fetch] status={data['status']} fecha={data['fecha']}")
```

### Salida: `outputs/data.json`
```json
{
  "vix9d": 13.42,
  "vix": 16.05,
  "vxv": 18.30,
  "vvix": 88.12,
  "fecha": "2026-03-28",
  "status": "OK"
}
```

### Ejecución directa
```
uv run python scripts/fetch_market_data.py
```

---

## 2. scripts/calculate_indicators.py

### Estado actual
Las funciones `calc_vix_vxv_slope(vix_current: dict) -> dict` y
`calc_vix9d_vix_ratio(vix_current: dict) -> dict` ya están implementadas.

### Añadir: bloque `__main__`
Cuando se ejecuta como script, lee `outputs/data.json`, calcula ambos indicadores y
guarda el resultado en `outputs/indicators.json`.

```python
if __name__ == "__main__":
    import json
    from pathlib import Path

    data = json.loads(Path("outputs/data.json").read_text())
    slope = calc_vix_vxv_slope(data)
    ratio = calc_vix9d_vix_ratio(data)

    indicators = {
        "fecha": data.get("fecha"),
        "vix_vxv_slope": slope,
        "vix9d_vix_ratio": ratio,
    }

    Path("outputs/indicators.json").write_text(json.dumps(indicators, indent=2))
    print(f"[calc] vix_vxv_slope={slope['signal']}({slope['score']})  "
          f"vix9d_vix_ratio={ratio['signal']}({ratio['score']})")
```

### Salida: `outputs/indicators.json`
```json
{
  "fecha": "2026-03-28",
  "vix_vxv_slope": {
    "vix": 16.05,
    "vxv": 18.30,
    "ratio": 0.8770,
    "score": 1,
    "signal": "CONTANGO_SUAVE",
    "status": "OK",
    "fecha": "2026-03-28"
  },
  "vix9d_vix_ratio": {
    "vix9d": 13.42,
    "vix": 16.05,
    "ratio": 0.8362,
    "score": 2,
    "signal": "CONTANGO_FUERTE",
    "status": "OK",
    "fecha": "2026-03-28"
  }
}
```

### Ejecución directa
```
uv run python scripts/calculate_indicators.py
```

---

## 3. scripts/generate_scorecard.py (nuevo)

### Propósito
Lee `outputs/indicators.json` e imprime un scorecard en terminal.

### Comportamiento
- Lee `outputs/indicators.json` con `json.loads`
- Calcula `d_score = vix_vxv_slope["score"] + vix9d_vix_ratio["score"]`
- Imprime la tabla con solo `print()` y stdlib (sin dependencias externas)

### Formato de salida en terminal
```
============================================================
  PRE-MARKET SCORECARD — 2026-03-28
============================================================
  Indicador          Valor    Ratio    Score  Signal
  --------------------------------------------------------
  VIX/VXV Slope     VIX=16.05  VXV=18.30  0.8770  +1  CONTANGO_SUAVE
  VIX9D/VIX Ratio  VIX9D=13.42  VIX=16.05  0.8362  +2  CONTANGO_FUERTE
  --------------------------------------------------------
  D-Score parcial (direccional):  +3
============================================================
```

### Estructura del módulo
```python
import json
from pathlib import Path


def print_scorecard(indicators: dict) -> None:
    """Imprime la tabla del scorecard dado el dict de indicators.json."""
    ...


if __name__ == "__main__":
    data = json.loads(Path("outputs/indicators.json").read_text())
    print_scorecard(data)
```

La función `print_scorecard` se define por separado para facilitar tests futuros.

### Ejecución directa
```
uv run python scripts/generate_scorecard.py
```

---

## 4. scripts/run.py (nuevo)

### Propósito
Orquestador que ejecuta el pipeline completo en secuencia desde un único punto de entrada.

### Comportamiento
1. Importa y ejecuta `fetch_vix_term_structure()` → guarda `outputs/data.json`
2. Lee `outputs/data.json` → ejecuta ambos `calc_*` → guarda `outputs/indicators.json`
3. Lee `outputs/indicators.json` → llama `print_scorecard()`
4. Si en cualquier paso el `status` es `"ERROR"` o `"MISSING_DATA"`, imprime advertencia y aborta con `sys.exit(1)`

### Estructura
```python
import json
import sys
from pathlib import Path

from fetch_market_data import fetch_vix_term_structure
from calculate_indicators import calc_vix_vxv_slope, calc_vix9d_vix_ratio
from generate_scorecard import print_scorecard


def main():
    # Paso 1: fetch
    data = fetch_vix_term_structure()
    out = Path("outputs")
    out.mkdir(exist_ok=True)
    (out / "data.json").write_text(json.dumps(data, indent=2))
    if data["status"] != "OK":
        print(f"[ERROR] fetch: status={data['status']}", file=sys.stderr)
        sys.exit(1)

    # Paso 2: calcular indicadores
    slope = calc_vix_vxv_slope(data)
    ratio = calc_vix9d_vix_ratio(data)
    indicators = {
        "fecha": data.get("fecha"),
        "vix_vxv_slope": slope,
        "vix9d_vix_ratio": ratio,
    }
    (out / "indicators.json").write_text(json.dumps(indicators, indent=2))

    # Paso 3: scorecard
    print_scorecard(indicators)


if __name__ == "__main__":
    main()
```

### Uso
```
uv run python scripts/run.py
```

> Nota: los imports relativos entre scripts funcionan porque `uv run` ejecuta desde
> la raíz del proyecto y añade `scripts/` al path si se invoca con `python scripts/run.py`.
> Alternativamente, usar `sys.path.insert(0, Path(__file__).parent)` al inicio de `run.py`.

---

## Dependencias
No se añaden dependencias nuevas. El pipeline usa solo:
- `yfinance` (ya en `pyproject.toml`)
- `json`, `pathlib`, `sys` (stdlib)

## Ficheros que genera el pipeline
| Fichero | Generado por | Sobreescrito |
|---|---|---|
| `outputs/data.json` | `fetch_market_data.py` | Sí, cada ejecución |
| `outputs/indicators.json` | `calculate_indicators.py` | Sí, cada ejecución |

Ambos están en `.gitignore`.

## Verificación
1. `uv run python scripts/run.py` → imprime scorecard en terminal sin errores
2. `outputs/data.json` existe y contiene valores numéricos (no `null`)
3. `outputs/indicators.json` existe con `status: "OK"` en ambos indicadores
4. D-Score aparece como suma correcta de los dos scores individuales
5. `uv run pytest` → todos los tests existentes siguen pasando
