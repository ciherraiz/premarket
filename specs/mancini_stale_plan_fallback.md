# Mancini — Fallback al plan del día anterior

## Problema

Mancini publica su plan diario a horas variables (habitualmente entre las
08:00 y las 11:00 ET). El monitor arranca a las 03:00 ET y puede pasar
horas sin plan, ignorando setups válidos aunque el precio esté exactamente
en los mismos niveles clave del día anterior.

Los niveles gamma/key level no se resetean de un día para otro: si ayer el
nivel era 5.580 y hoy el mercado abre en 5.575, el setup sigue siendo
técnicamente idéntico. No tener plan no significa que no haya oportunidad.

---

## Objetivo

Cuando no existe plan para hoy, el monitor utiliza el plan del día anterior
como **fallback provisional**, con las siguientes restricciones:

1. Solo si el precio actual está dentro de la alert zone del nivel
   (distancia ≤ `CONTEXT_ALERT_PTS = 15 pts`).
2. Solo para detectores cuyo estado no sea `DONE` ni `EXPIRED` en el
   estado guardado del día anterior (niveles no "gastados").
3. Marcado siempre como `stale` en logs, notificaciones y estado — nunca
   presentado como plan vigente.
4. Descartado inmediatamente en cuanto el plan de hoy está disponible.

---

## Diseño

### Campo nuevo en DailyPlan

```python
@dataclass
class DailyPlan:
    ...
    is_stale: bool = False   # True si es plan de otro día usado como fallback
```

No se persiste en JSON — se asigna en memoria al cargar el fallback.

### Lógica en `monitor.py` — `load_state()`

Comportamiento actual:
```
plan = load_plan()
if plan.fecha != today:
    plan = None   # descartado
```

Comportamiento nuevo:
```
plan = load_plan()
if plan.fecha != today:
    if _should_use_stale_plan(plan, current_price):
        plan.is_stale = True
        log("Usando plan de {plan.fecha} como fallback (sin plan de hoy)")
    else:
        plan = None
```

### Función `_should_use_stale_plan(plan, price) → bool`

```python
def _should_use_stale_plan(plan: DailyPlan, price: float | None) -> bool:
    if plan is None or price is None:
        return False

    # Solo planes de ayer (no más antiguos)
    today = _now_et().date()
    try:
        plan_date = date.fromisoformat(plan.fecha)
    except ValueError:
        return False
    if (today - plan_date).days > 1:
        return False

    # Precio debe estar en alert zone de al menos un nivel
    for level in _active_levels(plan):
        if abs(price - level) <= CONTEXT_ALERT_PTS:
            return True

    return False


def _active_levels(plan: DailyPlan) -> list[float]:
    """Niveles del plan que no estaban ya en DONE/EXPIRED ayer."""
    from scripts.mancini.detector import load_detectors, State
    yesterday_detectors = load_detectors()  # estado del día anterior (si existe)
    done_levels = {
        d.level for d in yesterday_detectors
        if d.state in (State.DONE, State.EXPIRED)
    }
    levels = []
    if plan.key_level_upper and plan.key_level_upper not in done_levels:
        levels.append(plan.key_level_upper)
    if plan.key_level_lower and plan.key_level_lower not in done_levels:
        levels.append(plan.key_level_lower)
    return levels
```

### Inicialización de detectores con plan stale

`_init_detectors()` no cambia: crea detectores normalmente a partir de los
niveles activos del plan. Los detectores arrancan en estado `WATCHING` —
el estado anterior de DONE/EXPIRED ya fue filtrado en `_active_levels()`.

### Notificación Telegram — plan stale

`notifier.notify_plan_loaded()` recibe el dict del plan. Si `is_stale=True`,
el mensaje incluye un prefijo de advertencia:

```
⚠️ Sin plan de hoy — usando niveles del {fecha_anterior}
Upper: 5.580 → targets [5.595, 5.610]
Lower: 5.565 → targets [5.550, 5.535]
(Se actualizará automáticamente cuando Mancini publique)
```

### Descarte automático

En el loop principal, cuando `_scan_for_plan()` obtiene el plan de hoy:

```python
if self.plan and self.plan.is_stale:
    log("Plan de hoy recibido — descartando fallback de {plan.fecha}")
    # Resetear detectores completamente antes de inicializar con plan nuevo
    self.detectors = []
```

Los detectores del plan stale se descartan; se crean nuevos con el plan real.

### Health check

`check_health()` distingue el estado del plan:

```python
plan_ok = bool(plan and plan.fecha == today and not plan.is_stale)
plan_stale = bool(plan and plan.fecha != today and plan.is_stale)
```

`print_summary()` muestra:
- `✓` si hay plan de hoy
- `⚠ STALE ({fecha})` si hay fallback activo
- `✗` si no hay plan de ningún tipo

---

## Condiciones de activación / desactivación

| Condición | Acción |
|-----------|--------|
| Sin plan de hoy + precio en alert zone de nivel de ayer (no gastado) | Activar fallback stale |
| Sin plan de hoy + precio fuera de alert zone de todos los niveles | No activar fallback (plan=None, monitor espera) |
| Sin plan de hoy + plan de anteayer o más antiguo | No activar fallback nunca |
| Plan de hoy disponible (scan exitoso) | Descartar fallback, reinicializar detectores |
| Precio sale de alert zone mientras stale está activo | Mantener stale (no desactivar en caliente — demasiado ruidoso) |

---

## Ficheros afectados

| Fichero | Cambio |
|---------|--------|
| `scripts/mancini/config.py` | Añadir `is_stale: bool = False` a `DailyPlan` |
| `scripts/mancini/monitor.py` | `load_state()`, `_scan_for_plan()`, `_should_use_stale_plan()`, `_active_levels()` |
| `scripts/mancini/notifier.py` | `notify_plan_loaded()` — mensaje diferenciado si `is_stale` |
| `scripts/mancini/health.py` | `check_health()`, `SystemHealth.print_summary()` |

---

## Tests

- `test_stale_plan_activates_when_price_in_alert_zone` — precio a 10 pts del nivel → fallback activo
- `test_stale_plan_inactive_when_price_far` — precio a 50 pts → fallback no se activa
- `test_stale_plan_inactive_when_level_was_done` — nivel en DONE ayer → excluido de fallback
- `test_stale_plan_discarded_on_new_plan` — llega plan de hoy → detectores reseteados
- `test_stale_plan_only_yesterday` — plan de hace 2 días → no se usa como fallback
- `test_health_shows_stale_status` — `check_health()` retorna `plan_stale=True` correctamente
