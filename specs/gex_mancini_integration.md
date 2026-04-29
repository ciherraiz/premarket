# Spec: Integración GEX Intraday con el Sistema Mancini

## Estado

- [x] Implementado

## Objetivo

Conectar los niveles GEX enriquecidos (Control Node, Chop Zone) con el sistema Mancini
de tres formas:

1. **Control Node como nivel técnico** — añadirlo a `auto_levels.py` para que el monitor
   lo tenga en cuenta como nivel de soporte/resistencia GEX primario en short gamma.
2. **Chop Zone como contexto de señal** — cuando el precio está dentro de la Chop Zone,
   el monitor emite un aviso específico: el setup pierde fiabilidad estadística.
3. **Snapshot intraday como fuente de niveles actualizada** — si hay snapshots del día,
   el monitor usa el último en lugar de los indicadores premarket estáticos para los
   niveles GEX en `auto_levels`.

Esta spec depende de:
- `specs/gex_enrich_0dte.md` (Control Node, Chop Zone disponibles en indicators.json)
- `specs/gex_snapshots_intraday.md` (snapshots JSONL disponibles durante sesión)

---

## Prerequisitos de datos

| Fuente | Cuándo disponible | Qué aporta |
|--------|-------------------|------------|
| `outputs/indicators.json` → `net_gex` | Premarket (antes 9:25 ET) | Niveles GEX iniciales del día |
| `outputs/gex_snapshots_YYYY-MM-DD.jsonl` | Durante sesión (cada 10 min) | Niveles GEX actualizados |

Si no hay snapshots del día (fuera de sesión, primeros minutos), se usan los de `indicators.json`.
Si no hay `indicators.json`, se continúa sin niveles GEX (comportamiento actual).

---

## 1. auto_levels.py — añadir Control Node

### Cambio en `build_auto_levels()`

En el bloque **Grupo E: GEX** (línea ~229), añadir `control_node` junto a los existentes:

```python
# Antes
for key, label in [("flip_level", "FLIP"), ("put_wall", "PUT_WALL"), ("call_wall", "CALL_WALL")]:

# Después
for key, label in [
    ("flip_level",    "FLIP"),
    ("put_wall",      "PUT_WALL"),
    ("call_wall",     "CALL_WALL"),
    ("control_node",  "CONTROL_NODE"),
]:
```

El Control Node solo tiene valor cuando `signal_gex` es SHORT_GAMMA_* (el dict ya lo
pone a None en long gamma), así que el guard existente `if val` lo excluye automáticamente.

**Prioridad**: `priority=1` (igual que los demás niveles GEX) — el Control Node es
tan relevante para el setup de Mancini como el flip_level en entornos short gamma.

### Fuente de gex_levels en `load_auto_levels()`

La función actualmente lee `indicators.json`. Añadir lógica para preferir el último
snapshot intraday si existe:

```python
def _load_gex_levels() -> dict:
    """
    Carga niveles GEX del último snapshot intraday disponible.
    Fallback: indicators.json premarket.
    """
    from scripts.gex_intraday import load_snapshots
    snapshots = load_snapshots()  # fecha de hoy por defecto
    if snapshots:
        last = snapshots[-1]
        if last.get("status") == "OK":
            return {
                "flip_level":   last.get("flip_level"),
                "put_wall":     last.get("put_wall"),
                "call_wall":    last.get("call_wall"),
                "control_node": last.get("control_node"),
            }
    # Fallback: indicators.json
    try:
        ind = json.loads(Path("outputs/indicators.json").read_text())
        ng  = ind.get("net_gex", {})
        return {
            "flip_level":   ng.get("flip_level"),
            "put_wall":     ng.get("put_wall"),
            "call_wall":    ng.get("call_wall"),
            "control_node": ng.get("control_node"),
        }
    except Exception:
        return {}
```

Llamar `_load_gex_levels()` en lugar del bloque manual que actualmente lee `indicators.json`
en `load_auto_levels()`.

**Importante**: `load_auto_levels()` se llama al inicio del monitor (premarket).
Durante la sesión, los niveles GEX se actualizan vía `_poll_gex()` en el monitor
(spec gex_snapshots_intraday), no recalculando auto_levels. auto_levels no se recalcula
intraday: es un cálculo premarket. Lo que sí se actualiza son los niveles GEX en memoria
del monitor cuando llega un nuevo snapshot.

---

## 2. monitor.py — contexto Chop Zone

### Nueva función `_in_chop_zone(price, snapshot) -> bool`

```python
def _in_chop_zone(price: float, snapshot: dict | None) -> bool:
    """
    Retorna True si el precio está dentro de la Chop Zone del último snapshot GEX.
    """
    if snapshot is None:
        return False
    low  = snapshot.get("chop_zone_low")
    high = snapshot.get("chop_zone_high")
    if low is None or high is None:
        return False
    return low <= price <= high
```

### Integración en el bucle de precio

En el punto donde el monitor evalúa el contexto de cada nivel (función
`compute_level_context` o equivalente), añadir detección de Chop Zone:

```python
# Ejemplo: al emitir una transición a ALERT_ZONE o en cualquier log de estado
if _in_chop_zone(price, self._last_gex_snapshot):
    _log(f"⚠️  Precio en Chop Zone GEX "
         f"[{self._last_gex_snapshot['chop_zone_low']:.0f}–"
         f"{self._last_gex_snapshot['chop_zone_high']:.0f}] — "
         f"señal menos fiable")
```

El monitor **no bloquea ni filtra** señales por la Chop Zone — eso sería
premature optimization sin datos de backtest. Solo anota el contexto en log
y lo incluye en las notificaciones Telegram de estado.

### Integración en notificaciones de nivel

Cuando `notifier.notify_level_status()` envía una actualización de estado de un nivel,
añadir al mensaje un flag visual si el precio está en Chop Zone:

```python
# En notifier.py, en la función que construye el mensaje de estado de nivel
chop_flag = ""
if gex_snapshot and _in_chop_zone(price, gex_snapshot):
    chop_zone_low  = gex_snapshot.get("chop_zone_low", 0)
    chop_zone_high = gex_snapshot.get("chop_zone_high", 0)
    chop_flag = f"\n🔀 En Chop Zone GEX ({chop_zone_low:.0f}–{chop_zone_high:.0f}) — precaución"
```

---

## 3. Actualización de niveles GEX en memoria durante sesión

Cuando `_poll_gex()` obtiene un nuevo snapshot con niveles distintos a los premarket,
el monitor actualiza su referencia interna pero **no recrea los detectores ni
los `TechnicalLevel`** de auto_levels durante la sesión.

El uso operativo de los snapshots intraday para Mancini en esta primera iteración es:
- Contexto visual / log: saber en qué punto de la estructura GEX está el precio.
- Chop Zone warning: avisar cuando el precio entra en la zona de ambigüedad.
- Shift alert: avisar cuando los niveles clave se desplazan significativamente.
- Fuente de datos para el heatmap (spec gex_heatmap.md).

La integración más profunda (p.ej. modificar la lógica del detector cuando el
Control Node se convierte en nivel de breakdown) se reserva para una iteración
posterior, una vez tengamos observaciones empíricas del comportamiento.

---

## 4. Cambios en archivos

| Archivo | Cambio |
|---------|--------|
| `scripts/mancini/auto_levels.py` | Añadir `control_node` a Grupo E GEX; función `_load_gex_levels()` |
| `scripts/mancini/monitor.py` | Función `_in_chop_zone()`; log de Chop Zone en bucle de precio |
| `scripts/mancini/notifier.py` | Flag Chop Zone en mensajes de estado de nivel |

---

## 5. Tests

### `tests/test_gex_mancini.py`

```python
def test_control_node_added_to_auto_levels():
    # Simular gex_levels con control_node != None
    # → build_auto_levels() debe incluir TechnicalLevel con label="CONTROL_NODE"
    ...

def test_control_node_excluded_when_none():
    # gex_levels con control_node = None (long gamma)
    # → build_auto_levels() NO incluye ningún nivel CONTROL_NODE
    ...

def test_in_chop_zone_true():
    snapshot = {"chop_zone_low": 5195.0, "chop_zone_high": 5205.0}
    assert _in_chop_zone(5200.0, snapshot) is True

def test_in_chop_zone_false_above():
    snapshot = {"chop_zone_low": 5195.0, "chop_zone_high": 5205.0}
    assert _in_chop_zone(5210.0, snapshot) is False

def test_in_chop_zone_false_no_snapshot():
    assert _in_chop_zone(5200.0, None) is False

def test_load_gex_levels_prefers_snapshot(tmp_path):
    # Si hay snapshot OK del día, se usa en lugar de indicators.json
    ...

def test_load_gex_levels_fallback_to_indicators(tmp_path):
    # Sin snapshots del día, se lee indicators.json
    ...
```

---

## Verificación

1. Añadir manualmente un snapshot con `control_node=5150` en el JSONL de hoy.
   Ejecutar `load_auto_levels()` → los niveles deben incluir `CONTROL_NODE=5150`.
2. Simular precio dentro de `[chop_zone_low, chop_zone_high]` en el monitor →
   debe aparecer el warning en log y en el mensaje Telegram de estado de nivel.
3. Simular precio fuera de la Chop Zone → no aparece el warning.
4. Verificar que el monitor no falla si `_last_gex_snapshot = None`
   (inicio de sesión antes del primer poll GEX).
5. Ejecutar `uv run pytest tests/test_gex_mancini.py` — todos los tests en verde.
