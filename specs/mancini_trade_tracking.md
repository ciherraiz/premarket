# Mancini — Trade Tracking: updates periódicos y log estadístico

## Estado actual

| Qué existe | Qué falta |
|------------|-----------|
| `append_trade(trade)` llamado al cierre | No hay log al abrir ni durante el trade |
| `notify_trade_closed` — P&L final | No hay updates periódicos de P&L abierto |
| `notify_target_hit` — al tocar target | No hay MFE tracking ni contexto estadístico |
| Trade tiene entry/exit/pnl_total_pts | Faltan campos para análisis: level, depth, duración, hora relativa |

El log `logs/mancini_trades.jsonl` contiene solo trades cerrados, sin registro
de apertura ni evolución. No es posible reconstruir el ciclo de vida completo
ni calcular estadísticas como MFE, win rate por alineación, o rendimiento por
franja horaria.

---

## Objetivo

1. **Updates periódicos en Telegram** mientras hay un runner activo — el trader
   sabe en todo momento dónde está la posición sin tener que preguntar.

2. **Log de ciclo de vida completo** — cada trade genera tres registros
   (apertura, evolución de targets, cierre) con todos los campos necesarios
   para análisis estadístico posterior.

---

## Parte 1: Updates periódicos de P&L

### Qué se envía y cuándo

**Trigger temporal:** cada `RUNNER_UPDATE_INTERVAL` minutos mientras hay trade activo.
Valor por defecto: 30 minutos. Configurable con `MANCINI_RUNNER_UPDATE_INTERVAL`.

**Trigger por evento:** además del temporal, se envía update inmediato cuando:
- Se alcanza el 50% de la distancia al siguiente target ("a mitad de camino")
- Se alcanza un nuevo MFE (Maximum Favorable Excursion) redondo (10, 20, 30… pts)

**No se envía si:** el precio no ha cambiado más de 1 pt desde el último update
(evitar spam en mercado lateral).

### Formato del mensaje

```
📊 *Runner activo — update*

▶️ Entry: 7163 | Actual: 7191
⏱ En trade: 47 min
📈 *P&L abierto: +28 pts* 🟢
🏆 Máximo: +31 pts

🛑 Stop: 7186 (T1) | Riesgo: 5 pts
🎯 Siguiente: 7193 | Faltan: 2 pts
   Targets pendientes: T3(7200) T4(7211) T5(7230)
```

Cuando el trade está en pérdida (entre entry y stop):

```
📊 *Runner activo — update*

▶️ Entry: 7163 | Actual: 7155
⏱ En trade: 12 min
📉 *P&L abierto: -8 pts* 🔴
🛑 Stop: 7149 | Riesgo restante: 6 pts
🎯 Primer target: 7186 | Faltan: 31 pts
```

### MFE tracking

El monitor necesita rastrear el precio más favorable desde la apertura:
- Para LONG: precio máximo desde entry
- Para SHORT: precio mínimo desde entry

Se calcula en el loop principal y se persiste en el objeto `Trade`.

Nuevo campo en `Trade`:
```python
mfe_pts: float = 0.0  # Maximum Favorable Excursion en puntos
```

Se actualiza en `process_tick()` o en el poll loop del monitor.

### Implementación en monitor.py

Nuevo atributo del monitor:
```python
self._last_runner_update: float = 0.0  # timestamp del último update
```

En el loop principal, después de procesar el tick:
```python
def _maybe_send_runner_update(self, price: float, ts: str) -> None:
    """Envía update periódico si hay trade activo y ha pasado el intervalo."""
    trade = self.trade_manager.active_trade()
    if trade is None:
        return

    now = time.time()
    interval = int(os.getenv("MANCINI_RUNNER_UPDATE_INTERVAL", "30")) * 60

    # Actualizar MFE
    if trade.direction == "LONG":
        pnl = price - trade.entry_price
        if pnl > trade.mfe_pts:
            trade.mfe_pts = round(pnl, 2)
    else:
        pnl = trade.entry_price - price
        if pnl > trade.mfe_pts:
            trade.mfe_pts = round(pnl, 2)

    # Precio sin cambio significativo — no enviar
    if abs(price - getattr(self, "_last_runner_price", price)) < 1.0:
        if now - self._last_runner_update < interval:
            return

    if now - self._last_runner_update < interval:
        # Chequear trigger de MFE redondo (10, 20, 30...)
        last_mfe = getattr(self, "_last_notified_mfe", 0)
        mfe_floor = int(trade.mfe_pts / 10) * 10
        if mfe_floor <= last_mfe or mfe_floor == 0:
            return
        self._last_notified_mfe = mfe_floor

    self._last_runner_update = now
    self._last_runner_price = price
    notifier.notify_runner_update(trade, price)
```

### Nueva función en notifier.py

```python
def notify_runner_update(trade, current_price: float) -> bool:
    """Update periódico del runner activo."""
    from datetime import datetime, timezone

    pnl = (current_price - trade.entry_price
           if trade.direction == "LONG"
           else trade.entry_price - current_price)
    pnl_sign = "\\+" if pnl >= 0 else ""
    pnl_emoji = "🟢" if pnl > 0 else ("🔴" if pnl < 0 else "⚪")

    # Tiempo en trade
    try:
        entry_dt = datetime.fromisoformat(trade.entry_time)
        elapsed = datetime.now(timezone.utc) - entry_dt
        elapsed_min = int(elapsed.total_seconds() / 60)
    except Exception:
        elapsed_min = 0

    # Próximo target
    next_targets = [t for t in trade.targets[trade.targets_hit:]]
    next_target = next_targets[0] if next_targets else None
    remaining_targets = next_targets[1:] if len(next_targets) > 1 else []

    lines = [
        "📊 *Runner activo — update*",
        "",
        f"▶️ Entry: {_esc(trade.entry_price)} \\| Actual: {_esc(current_price)}",
        f"⏱ En trade: {_esc(elapsed_min)} min",
        f"{'📈' if pnl >= 0 else '📉'} *P&L abierto: "
        f"{pnl_sign}{_esc(f'{pnl:.1f}')} pts* {pnl_emoji}",
    ]

    if trade.mfe_pts > 0:
        lines.append(f"🏆 Máximo: \\+{_esc(f'{trade.mfe_pts:.1f}')} pts")

    stop_risk = abs(current_price - trade.stop_price)
    lines.append("")
    lines.append(f"🛑 Stop: {_esc(trade.stop_price)} \\| Riesgo: {_esc(f'{stop_risk:.1f}')} pts")

    if next_target:
        dist = abs(next_target - current_price)
        t_idx = trade.targets_hit + 1
        lines.append(f"🎯 Siguiente: T{t_idx} {_esc(next_target)} \\| Faltan: {_esc(f'{dist:.1f}')} pts")

    if remaining_targets:
        rest_str = " ".join(
            f"T{trade.targets_hit + 2 + i}\\({_esc(t)}\\)"
            for i, t in enumerate(remaining_targets)
        )
        lines.append(f"   Pendientes: {rest_str}")

    return send_telegram("\n".join(lines))
```

---

## Parte 2: Log estadístico completo

### Diseño: tres tipos de registro por trade

El fichero `logs/mancini_trades.jsonl` pasa de solo-cierre a ciclo de vida
completo. Cada línea tiene un campo `record_type` que identifica cuándo se generó:

| `record_type` | Cuándo | Propósito |
|---------------|--------|-----------|
| `"open"` | Al abrir el trade | Snapshot de condiciones de entrada |
| `"target_hit"` | Cada vez que se toca un target | Evolución del trade |
| `"close"` | Al cerrar el trade | Resultado final + estadísticas |

Los tres registros comparten el mismo `trade_id` para poder reconstruir
el ciclo de vida completo con un JOIN en análisis.

### Schema del registro `"open"`

```json
{
  "record_type": "open",
  "trade_id": "uuid",
  "fecha": "2026-04-24",

  // Contexto de la señal
  "level": 7161.0,
  "breakdown_low": 7151.12,
  "depth_pts": 9.88,
  "direction": "LONG",
  "alignment": "ALIGNED",

  // Precios y riesgo
  "entry_price": 7163.38,
  "entry_time": "2026-04-24T14:41:00Z",
  "stop_price": 7149.12,
  "risk_pts": 14.26,
  "targets": [7186.0, 7193.0, 7200.0, 7211.0, 7230.0],

  // Contexto temporal
  "entry_time_et": "10:41",
  "minutes_from_open": 71,       // minutos desde las 09:30 ET
  "day_of_week": 3,              // 0=lunes, 4=viernes

  // Gate y ejecución
  "gate_execute": true,
  "gate_reasoning": "...",
  "gate_risk_factors": [],
  "execution_mode": "auto",      // "auto" | "manual_confirm"
  "dry_run": true,

  // Órdenes TastyTrade
  "entry_order_id": null,
  "stop_order_id": null
}
```

### Schema del registro `"target_hit"`

```json
{
  "record_type": "target_hit",
  "trade_id": "uuid",
  "fecha": "2026-04-24",
  "target_index": 0,             // 0-based
  "target_price": 7186.0,
  "price_at_hit": 7186.5,
  "timestamp": "2026-04-24T15:10:00Z",
  "new_stop": 7163.38,           // stop tras el trailing
  "old_stop": 7149.12,
  "pnl_at_hit_pts": 23.12,       // P&L realizado a este punto
  "mfe_pts": 23.12               // MFE acumulado hasta aquí
}
```

### Schema del registro `"close"`

```json
{
  "record_type": "close",
  "trade_id": "uuid",
  "fecha": "2026-04-24",

  // Resultado
  "exit_price": 7163.38,
  "exit_time": "2026-04-24T15:45:00Z",
  "exit_reason": "STOP",         // STOP | MANUAL | EOD
  "pnl_total_pts": 0.0,

  // Estadísticas del trade
  "targets_hit": 1,
  "mfe_pts": 23.12,              // máximo beneficio abierto alcanzado
  "duration_minutes": 64,
  "mae_pts": 0.0,                // Maximum Adverse Excursion (mín. P&L)

  // Para el analysis posterior
  "pnl_per_risk": 0.0,           // pnl_total_pts / risk_pts (= R múltiple)
  "dry_run": true
}
```

### Nuevas funciones en logger.py

```python
def append_trade_open(trade: Trade, level: float,
                      minutes_from_open: int) -> None:
    """Registra apertura del trade con contexto completo."""
    from datetime import datetime, timezone

    entry_dt = datetime.fromisoformat(trade.entry_time)
    entry_et = _to_et(entry_dt)  # helper timezone conversion

    risk_pts = abs(trade.entry_price - trade.stop_price)
    depth_pts = abs(trade.entry_price - (trade.breakdown_low or trade.entry_price))

    gate = trade.gate_decision or {}
    entry = {
        "record_type": "open",
        "trade_id": trade.id,
        "fecha": entry_et.strftime("%Y-%m-%d"),
        "level": level,
        "breakdown_low": trade.breakdown_low,
        "depth_pts": round(depth_pts, 2),
        "direction": trade.direction,
        "alignment": trade.alignment,
        "entry_price": trade.entry_price,
        "entry_time": trade.entry_time,
        "stop_price": trade.stop_price,
        "risk_pts": round(risk_pts, 2),
        "targets": trade.targets,
        "entry_time_et": entry_et.strftime("%H:%M"),
        "minutes_from_open": minutes_from_open,
        "day_of_week": entry_et.weekday(),
        "gate_execute": gate.get("execute"),
        "gate_reasoning": gate.get("reasoning", ""),
        "gate_risk_factors": gate.get("risk_factors", []),
        "execution_mode": trade.execution_mode,
        "dry_run": trade.dry_run,
        "entry_order_id": trade.entry_order_id,
        "stop_order_id": trade.stop_order_id,
    }
    _append(entry, TRADES_LOG_PATH)


def append_trade_target_hit(trade: Trade, event: dict) -> None:
    """Registra que un target fue alcanzado."""
    pnl = (event["price"] - trade.entry_price
           if trade.direction == "LONG"
           else trade.entry_price - event["price"])
    entry = {
        "record_type": "target_hit",
        "trade_id": trade.id,
        "fecha": trade.entry_time[:10],
        "target_index": event["target_index"],
        "target_price": event["target_price"],
        "price_at_hit": event["price"],
        "timestamp": event["timestamp"],
        "new_stop": event["new_stop"],
        "old_stop": event["old_stop"],
        "pnl_at_hit_pts": round(pnl, 2),
        "mfe_pts": trade.mfe_pts,
    }
    _append(entry, TRADES_LOG_PATH)


def append_trade_close(trade: Trade) -> None:
    """Registra cierre con resultado completo y métricas."""
    risk_pts = abs(trade.entry_price - trade.stop_price)
    pnl = trade.pnl_total_pts or 0.0

    try:
        entry_dt = datetime.fromisoformat(trade.entry_time)
        exit_dt = datetime.fromisoformat(trade.exit_time)
        duration = int((exit_dt - entry_dt).total_seconds() / 60)
    except Exception:
        duration = 0

    entry = {
        "record_type": "close",
        "trade_id": trade.id,
        "fecha": trade.entry_time[:10],
        "exit_price": trade.exit_price,
        "exit_time": trade.exit_time,
        "exit_reason": trade.exit_reason,
        "pnl_total_pts": pnl,
        "targets_hit": trade.targets_hit,
        "mfe_pts": trade.mfe_pts,
        "duration_minutes": duration,
        "pnl_per_risk": round(pnl / risk_pts, 3) if risk_pts > 0 else 0.0,
        "dry_run": trade.dry_run,
    }
    _append(entry, TRADES_LOG_PATH)


def _append(entry: dict, path: Path) -> None:
    """Helper: escribe una línea JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
```

El método `append_trade` existente se **reemplaza** por los tres nuevos.
La función antigua queda como alias para compatibilidad con tests existentes:
```python
def append_trade(trade: Trade, path: Path = TRADES_LOG_PATH) -> None:
    append_trade_close(trade, path)  # backwards compat
```

### Helper de timezone en logger.py

```python
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")

def _to_et(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_ET)
```

### Integración en monitor.py

Tres puntos de llamada:

**1. Al abrir trade** (en `_handle_transition`, State.SIGNAL):
```python
trade = self.trade_manager.open_trade(...)
if trade:
    # Calcular minutos desde apertura de sesión (09:30 ET)
    now_et = _now_et()
    session_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    minutes_from_open = max(0, int((now_et - session_open).total_seconds() / 60))
    append_trade_open(trade, level=t.level, minutes_from_open=minutes_from_open)
```

**2. Al tocar target** (en `_handle_trade_event`, TARGET_HIT):
```python
trade = self._find_trade(event["trade_id"])
if trade:
    append_trade_target_hit(trade, event)
```

**3. Al cerrar** (en `_handle_trade_event`, TRADE_CLOSED):
```python
if trade:
    append_trade_close(trade)
    # append_trade(trade)  ← eliminar la llamada antigua
```

---

## Campos para análisis estadístico

Con los tres registros por trade se pueden calcular:

| Métrica | Cómo |
|---------|------|
| Win rate | `close.pnl_total_pts > 0` |
| Profit factor | `sum(ganadores) / abs(sum(perdedores))` |
| Average R | `mean(close.pnl_per_risk)` |
| MFE vs exit | `close.mfe_pts - close.pnl_total_pts` (dinero dejado) |
| Win rate por alignment | Group by `open.alignment` |
| Win rate por franja horaria | Group by `open.entry_time_et` (bins 30 min) |
| Rendimiento por día | Group by `open.day_of_week` |
| Targets alcanzados | `mean(close.targets_hit)` |
| Duración media por resultado | Group by winner/loser, `mean(close.duration_minutes)` |
| Eficiencia del gate | % señales `gate_execute=false` que habrían ganado |

---

## Configuración

```env
MANCINI_RUNNER_UPDATE_INTERVAL=30  # minutos entre updates periódicos (default: 30)
```

---

## Tests

### test_mancini_runner_update.py

```python
def test_runner_update_sent_after_interval():
    """Update enviado cuando pasa el intervalo configurado."""

def test_runner_update_not_sent_if_price_unchanged():
    """No se envía si precio cambió menos de 1 pt y no pasó el intervalo."""

def test_runner_update_triggered_by_mfe_milestone():
    """Update enviado al alcanzar MFE en múltiplo de 10 (10, 20, 30…)."""

def test_runner_update_shows_pnl_positive(mock_send):
    """Mensaje incluye P&L positivo con emoji verde."""

def test_runner_update_shows_pnl_negative(mock_send):
    """Mensaje incluye P&L negativo con emoji rojo."""

def test_runner_update_shows_next_target_distance(mock_send):
    """Mensaje muestra distancia al siguiente target."""

def test_mfe_tracked_correctly():
    """mfe_pts se actualiza solo cuando P&L supera el máximo previo."""
```

### test_trade_log_lifecycle.py

```python
def test_append_trade_open_creates_record(tmp_path):
    """Registro 'open' se escribe al abrir trade."""

def test_append_trade_open_schema(tmp_path):
    """Registro 'open' contiene todos los campos requeridos."""

def test_append_trade_target_hit_schema(tmp_path):
    """Registro 'target_hit' contiene pnl_at_hit_pts y mfe_pts."""

def test_append_trade_close_schema(tmp_path):
    """Registro 'close' contiene pnl_per_risk y duration_minutes."""

def test_three_records_same_trade_id(tmp_path):
    """Los tres registros de un trade comparten trade_id."""

def test_pnl_per_risk_calculation(tmp_path):
    """pnl_per_risk = pnl_total_pts / risk_pts calculado correctamente."""

def test_duration_minutes_calculated(tmp_path):
    """duration_minutes = diferencia exit_time - entry_time en minutos."""

def test_append_trade_backwards_compat(tmp_path):
    """append_trade() sigue funcionando (llama a append_trade_close)."""
```

---

## Módulos afectados

| Módulo | Cambio |
|--------|--------|
| `trade_manager.py` | Campo `mfe_pts: float = 0.0` en `Trade` |
| `logger.py` | `append_trade_open`, `append_trade_target_hit`, `append_trade_close`, helper `_append`, `_to_et` |
| `monitor.py` | Llamadas a los tres `append_trade_*`; `_maybe_send_runner_update` en el loop |
| `notifier.py` | `notify_runner_update(trade, current_price)` |

No hay cambios en `order_executor.py`, `execution_gate.py` ni `telegram_confirm.py`.
