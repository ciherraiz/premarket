# Mancini — Overnight High/Low

## Problema

Los niveles actuales de `auto_levels.py` cubren referencias diarias/semanales/mensuales
y GEX, pero no incluyen el rango de la sesión Globex (overnight).

Mancini referencia frecuentemente los extremos overnight porque el mercado RTH
tiende a testear esos niveles en la primera hora. Son especialmente relevantes
cuando el overnight dejó un rango amplio o cuando el precio abre dentro del rango
overnight (sin gap significativo).

---

## Definición sesión overnight

| Sesión | Horario ET |
|--------|-----------|
| RTH (Regular Trading Hours) | 09:30 – 16:15 |
| Globex / Overnight | 18:00 día anterior – 09:29 día actual |

El Overnight High (ONH) es el máximo del periodo 18:00 ET (día anterior) – 09:29 ET (hoy).
El Overnight Low (ONL) es el mínimo del mismo periodo.

> No se incluyen barras de RTH del día anterior (16:16–17:59 ET) para aislar
> la sesión nocturna pura, que es la referencia que usa Mancini.

---

## Objetivo

Añadir ONH y ONL como niveles en `AutoLevels` con:
- `group = "overnight"`
- `priority = 2` (mismo que diario — son referencias intraday, no estructurales)
- Label `"ONH"` / `"ONL"`
- Ya en términos /ES — **no requieren ajuste de basis**

---

## Fuente de datos

`yfinance` ticker `ES=F` con `interval="1h"` y `period="2d"`.

- `ES=F` cotiza en términos de futuros /ES directamente.
- Barras horarias son suficientes para identificar ONH/ONL con precisión ±0.25 pts
  (tamaño de tick de /ES).
- `period="2d"` garantiza cubrir la sesión overnight completa incluso los lunes
  (que tienen overnight del viernes).

---

## Diseño

### Nueva función `fetch_overnight_ohlc`

```python
def fetch_overnight_ohlc(symbol: str = "ES=F") -> tuple[float, float] | None:
    """
    Descarga barras horarias de /ES y calcula ONH/ONL de la sesión overnight
    actual (18:00 ET ayer – 09:29 ET hoy).

    Retorna (onh, onl) o None si no hay barras suficientes.
    """
```

Pasos internos:
1. Descargar barras 1h con `yf.download("ES=F", period="2d", interval="1h")`
2. Convertir index a timezone `America/New_York`
3. Filtrar barras cuyo timestamp esté en `[ayer 18:00, hoy 09:29]` ET
4. Si hay ≥ 1 barra: `onh = max(High)`, `onl = min(Low)`
5. Retornar `(onh, onl)` o `None`

### Integración en `build_auto_levels`

Nuevo parámetro `overnight: tuple[float, float] | None = None`:

```python
# Grupo F: overnight
if overnight is not None:
    onh, onl = overnight
    levels.append(TechnicalLevel(value=onh, label="ONH", group="overnight", priority=2))
    levels.append(TechnicalLevel(value=onl, label="ONL", group="overnight", priority=2))
```

### Integración en `calculate_and_save`

```python
overnight = fetch_overnight_ohlc()
auto = build_auto_levels(..., overnight=overnight)
```

### Integración en `notifier.py`

Añadir `"overnight"` al dict de `group_tag` en `notify_auto_levels`:

```python
group_tag = {
    "gex": "GEX", "weekly": "sem", "monthly": "mes",
    "daily": "día", "overnight": "ON",
}.get(l.group, l.group)
```

---

## Casos límite

| Caso | Comportamiento |
|------|---------------|
| Lunes (overnight del viernes) | `period="2d"` cubre el fin de semana; yfinance devuelve barras del domingo noche |
| Mercado cerrado (festivo) | No hay barras → `None` → no se añaden niveles |
| ONH ≈ PDH (±2 pts) | `_dedup_levels` los fusiona conservando el de mayor prioridad |
| Overnight muy estrecho (<5 pts) | Se añaden igualmente — el monitor y el trader valoran si son útiles |

---

## Tests

| Test | Descripción |
|------|-------------|
| `test_fetch_overnight_returns_tuple_or_none` | Mock yfinance, verificar retorno correcto |
| `test_overnight_barras_filtradas_correctamente` | Solo barras en rango 18:00–09:29 ET |
| `test_overnight_niveles_en_auto_levels` | ONH/ONL presentes en resultado de `build_auto_levels` |
| `test_overnight_none_no_añade_niveles` | Si `overnight=None`, no se crean niveles ON |
| `test_overnight_group_tag_en_notifier` | `fmt_level` muestra `(ON)` para grupo overnight |
| `test_overnight_sin_basis_adjustment` | ONH/ONL no se multiplican por basis (ya son /ES) |

---

## Archivos a modificar

| Archivo | Cambio |
|---------|--------|
| `scripts/mancini/auto_levels.py` | + `fetch_overnight_ohlc()`, + parámetro `overnight` en `build_auto_levels`, integración en `calculate_and_save` |
| `scripts/mancini/notifier.py` | + tag `"overnight": "ON"` en `notify_auto_levels` |
| `tests/test_mancini_auto_levels.py` | + 6 nuevos tests |
