# Spec: Dashboard GEX y Heatmap de Evolución Intraday

## Estado

- [x] Implementado

## Objetivo

Generar visualizaciones del perfil GEX 0DTE bajo demanda:
1. **Dashboard terminal (ASCII)** — tabla rápida del estado GEX actual con barra visual por strike.
2. **Heatmap imagen Telegram** — mapa de calor de la evolución GEX por strike a lo largo de la sesión.

Ambos se lanzan manualmente; ninguno es automático. Se accede mediante:

```bash
# Dashboard terminal — estado actual
uv run python scripts/gex_heatmap.py

# Heatmap imagen — evolución del día, enviado a Telegram
uv run python scripts/gex_heatmap.py --telegram

# Heatmap de una fecha específica
uv run python scripts/gex_heatmap.py --telegram --date 2026-04-28
```

Esta spec depende de:
- `specs/gex_enrich_0dte.md` (campos `gex_pct_by_strike`, `control_node`, `chop_zone_*`)
- `specs/gex_snapshots_intraday.md` (ficheros `outputs/gex_snapshots_YYYY-MM-DD.jsonl`)

---

## 1. Dashboard Terminal (ASCII)

### Fuente de datos

Si hay snapshots del día → usa el último snapshot.
Si no → usa `indicators.json` → `net_gex`.

### Formato de salida

```
══════════════════════════════════════════════════════════════════
  GEX 0DTE  |  SPX 7139  |  04/29/26 14:32 ET
  Net GEX: −$52.18M  →  SHORT_GAMMA_FUERTE
  Dealers SHORT gamma bajo 7175 — caídas se aceleran
──────────────────────────────────────────────────────────────────
  Strike     GEX ($M)    %      Barra
──────────────────────────────────────────────────────────────────
  7205          +1.1M  +  9%   ██
  7200          +3.8M  + 30%   ██████
  7195          +0.7M  +  6%   █
  7180          +2.9M  + 23%   █████
▶ 7175          +5.0M  +100%   ████████████████████  ← Call Wall
  7170          +2.7M  + 21%   ████
  7165          +1.5M  + 12%   ██
  7160          −0.6M  −  5%   █
  ·········· CHOP ZONE [7130–7140] ··········
  7155          +3.4M  + 68%   █████████████
  7150         −15.8M  − 98%   ████████████████████  ← (−98%)
  7145         −20.4M  −100%   ████████████████████  ← Control Node *
  7140         −24.4M  − 98%   ████████████████████
● 7135         −42.1M  − 92%   ██████████████████    ← FLIP ~7160
  7130          −9.9M  − 45%   █████████
  7125         −26.5M  − 73%   ██████████████
  7120          −4.8M  − 12%   ██
  7100          −5.7M  + 50%   ██████████  ← Put Wall
──────────────────────────────────────────────────────────────────
  ▶ = precio actual   ● = Control Node   * = máx. neg. absoluto
══════════════════════════════════════════════════════════════════
```

Notas de formato:
- Barras ASCII: `█` por cada 5% de GEX relativo, máximo 20 caracteres.
- Columnas positivas a la derecha del cero, negativas a la izquierda (o con prefijo `−`).
- Marcas: `▶` en el strike más cercano al precio actual, `●` en el Control Node.
- Línea separadora `·· CHOP ZONE ··` insertada entre `chop_zone_low` y `chop_zone_high`.
- Etiquetas de niveles clave (Put Wall, Call Wall, Control Node) al final de la fila.
- Solo mostrar los 25 strikes más cercanos al precio actual (±12–13 strikes).

### Implementación: `print_gex_terminal(snapshot: dict) -> None`

```python
def print_gex_terminal(snapshot: dict) -> None:
    """
    Imprime el dashboard ASCII del estado GEX en el terminal.
    """
```

---

## 2. Heatmap imagen (matplotlib)

### Diseño visual

**Modo evolución intraday** (cuando hay múltiples snapshots):

```
Eje Y: strikes (ascendente, solo los 30 ATM del último snapshot)
Eje X: tiempo (timestamps de los snapshots, una columna por snapshot)
Color: escala divergente — rojo saturado para GEX muy negativo,
       verde saturado para GEX muy positivo, blanco/gris en cero.
       Normalizado por el máximo absoluto del día.
Overlays:
  - Línea blanca: precio del SPX en cada timestamp
  - Línea amarilla discontinua: flip_level en cada timestamp
  - Línea naranja discontinua: control_node en cada timestamp (cuando existe)
  - Banda sombreada: chop_zone en cada timestamp
Título: "GEX 0DTE — SPX {fecha} | {n_snapshots} snapshots"
Pie:    "Net GEX: {último_net_gex_bn:+.2f}B | {signal_gex} | {regime_text}"
```

**Modo snapshot único** (solo hay un snapshot o se pide el estado actual):

```
Gráfico de barras horizontales:
  Eje Y: strikes
  Eje X: GEX en $M
  Colores: rojo para negativo, verde para positivo
  Marcas verticales: flip_level (amarillo), control_node (naranja), spot (blanco)
  Banda sombreada: chop_zone
```

### Implementación: `build_gex_heatmap(snapshots: list[dict]) -> bytes`

```python
def build_gex_heatmap(snapshots: list[dict]) -> bytes:
    """
    Genera el heatmap como imagen PNG en memoria.

    Args:
        snapshots: lista de snapshots del día, orden cronológico.
                   Si len == 1, genera gráfico de barras en lugar de heatmap.

    Returns:
        bytes del PNG generado (para enviar directamente a Telegram).
    """
```

Dependencias: `matplotlib`, `numpy`. Añadir a `pyproject.toml` si no están.

### Parámetros de la imagen

```python
HEATMAP_DPI    = 150        # resolución
HEATMAP_SIZE   = (12, 8)    # pulgadas (ancho × alto)
HEATMAP_CMAP   = "RdYlGn"  # divergente rojo-amarillo-verde
N_STRIKES_SHOW = 30         # strikes a mostrar centrados en el último spot
```

### Función de envío: `send_heatmap_telegram(img_bytes: bytes, caption: str) -> None`

```python
def send_heatmap_telegram(img_bytes: bytes, caption: str) -> None:
    """
    Envía la imagen como foto a Telegram via Bot API.
    Reutiliza las credenciales de notify_telegram.py (TELEGRAM_TOKEN, TELEGRAM_CHAT_ID).
    """
```

Usa `requests.post` con `files={"photo": img_bytes}` al endpoint `sendPhoto` del Bot API.

---

## 3. Módulo `scripts/gex_heatmap.py`

### Estructura

```python
# scripts/gex_heatmap.py

def print_gex_terminal(snapshot: dict) -> None: ...
def build_gex_heatmap(snapshots: list[dict]) -> bytes: ...
def send_heatmap_telegram(img_bytes: bytes, caption: str) -> None: ...

def _load_source(date: str | None) -> tuple[list[dict], str]:
    """
    Carga snapshots del día. Si no hay, carga indicators.json como snapshot único.
    Retorna (snapshots, source_label).
    """

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--telegram", action="store_true")
    parser.add_argument("--date", default=None)
    args = parser.parse_args()

    snapshots, source = _load_source(args.date)

    if not snapshots:
        print("Sin datos GEX disponibles para hoy.")
        return

    if args.telegram:
        img   = build_gex_heatmap(snapshots)
        last  = snapshots[-1]
        cap   = (f"GEX 0DTE {last.get('ts_et','')[:10]} | "
                 f"Net={last.get('net_gex_bn',0):+.2f}B | "
                 f"{last.get('signal_gex','N/A')}")
        send_heatmap_telegram(img, cap)
        print(f"Heatmap enviado a Telegram ({len(snapshots)} snapshots, fuente: {source})")
    else:
        print_gex_terminal(snapshots[-1])

if __name__ == "__main__":
    main()
```

---

## 4. Caption del mensaje Telegram

Formato del caption de la imagen (máx. 1024 chars):

```
📊 GEX 0DTE — SPX 04/29/26
Net GEX: −$52.18M → SHORT_GAMMA_FUERTE
Dealers SHORT gamma bajo 7175 — caídas se aceleran

🎯 Flip:      7175
🔴 Control:   7145
🟢 Put Wall:  7100
🔴 Call Wall: 7200
🔀 Chop Zone: 7130–7140

14 snapshots | 09:30–14:32 ET
```

---

## 5. Dependencias

```toml
# pyproject.toml — añadir si no están
matplotlib = ">=3.8"
numpy      = ">=1.26"
```

`requests` ya está disponible (usado en `notify_telegram.py`).

---

## 6. Tests

Los tests de esta spec son principalmente de integración y visuales. Solo se testea
la lógica de selección y preparación de datos, no el rendering matplotlib.

### `tests/test_gex_heatmap.py`

```python
def test_print_gex_terminal_no_crash(capsys):
    snapshot = {
        "status": "OK", "spot": 5215.0, "net_gex_bn": -1.23,
        "signal_gex": "SHORT_GAMMA_SUAVE", "regime_text": "...",
        "flip_level": 5200, "control_node": 5150,
        "chop_zone_low": 5195, "chop_zone_high": 5205,
        "put_wall": 5100, "call_wall": 5300,
        "gex_pct_by_strike": {"5100": -87.3, "5150": -70.7, "5200": 9.8},
        "gex_by_strike": {"5100": -1.23, "5150": -0.87, "5200": 0.12},
        "ts_et": "2026-04-29T14:32:00-04:00",
    }
    print_gex_terminal(snapshot)
    out = capsys.readouterr().out
    assert "GEX 0DTE" in out
    assert "SHORT_GAMMA_SUAVE" in out
    assert "CHOP ZONE" in out

def test_build_heatmap_returns_bytes():
    snapshots = [...]  # dos snapshots mínimos válidos
    img = build_gex_heatmap(snapshots)
    assert isinstance(img, bytes)
    assert img[:4] == b"\x89PNG"  # cabecera PNG válida

def test_load_source_falls_back_to_indicators(tmp_path, monkeypatch):
    # Sin fichero JSONL → debe cargar indicators.json y retornar un snapshot
    ...
```

---

## Verificación

1. Ejecutar `uv run python scripts/gex_heatmap.py` → debe imprimir dashboard ASCII
   sin errores, con strikes ordenados y barras proporcionales.
2. Ejecutar `uv run python scripts/gex_heatmap.py --telegram` con snapshots reales
   → debe llegar una imagen al chat de Telegram en < 10 segundos.
3. Ejecutar con `--date` de un día sin snapshots → mensaje "Sin datos GEX disponibles".
4. Ejecutar con exactamente un snapshot → imagen en modo barras horizontales (no heatmap).
5. Ejecutar con 10+ snapshots → imagen en modo heatmap de evolución temporal con línea de precio.
6. Verificar que la banda de Chop Zone es visible en la imagen cuando `chop_zone_low != None`.
