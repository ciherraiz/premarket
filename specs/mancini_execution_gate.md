# Execution Gate — Validación LLM + ejecución de órdenes en /ES

## Objetivo

Añadir una capa de juicio contextual (LLM) entre la señal SIGNAL del detector
y la apertura real de posición. El gate decide si la situación es favorable
para ejecutar. Si lo es, lanza una orden en /ES via TastyTrade SDK (inicialmente
en dry-run). Si detecta riesgos, pregunta al trader via Telegram antes de proceder.

## Problema actual

El paso SIGNAL → ACTIVE es hoy mecánico: si el detector confirma un failed
breakdown, el trade se abre inmediatamente. No hay evaluación contextual de:

- Hora de la sesión (trade a las 15:45 ET tiene poco recorrido)
- Movimiento exhausto (breakdowns en rango estrecho)
- Acumulación de pérdidas en el día
- Actualizaciones intraday recientes de Mancini
- Contexto cualitativo del mercado

Mancini haría esta valoración instintivamente. El LLM la replica.

## Diseño: tres componentes

```
SIGNAL detectado
     ↓
[1] ExecutionGate (Haiku)
     ├─ execute=true  → [2] OrderExecutor (TastyTrade SDK)
     │                        ├─ dry_run=true (fase inicial)
     │                        └─ dry_run=false (fase live)
     └─ execute=false → Telegram: pregunta al trader
                              ├─ "Sí" → OrderExecutor
                              └─ "No" / timeout → trade descartado
```

---

## Componente 1: ExecutionGate

### Módulo: `scripts/mancini/execution_gate.py`

```python
@dataclass
class GateDecision:
    execute: bool              # True = ejecutar, False = consultar trader
    reasoning: str             # explicación en español para Telegram
    risk_factors: list[str]    # factores de riesgo detectados (puede estar vacío)
```

### Función principal

```python
def evaluate_signal(
    signal_price: float,
    signal_level: float,
    breakdown_low: float,
    direction: str,
    plan: DailyPlan,
    weekly: DailyPlan | None,
    alignment: str,
    trades_today: list[Trade],
    recent_adjustments: list[PlanAdjustment],
    current_time_et: datetime,
    session_end_hour: int,
) -> GateDecision:
```

### System prompt para Haiku

```
Eres un validador de ejecución para la estrategia Failed Breakdown en futuros /ES.

Se ha detectado una señal técnica válida (failed breakdown confirmado por la
máquina de estados). Tu trabajo es evaluar si el CONTEXTO es favorable para
ejecutar el trade, no si la señal técnica es correcta (eso ya está confirmado).

## Datos de la señal
- Nivel: {signal_level}
- Precio actual: {signal_price}
- Breakdown low: {breakdown_low}
- Dirección: {direction}
- Stop calculado: {stop_price} ({risk_pts} pts de riesgo)
- Targets: {targets}

## Contexto
- Hora actual (ET): {current_time}
- Hora cierre sesión: {session_end}:00 ET
- Minutos restantes: {minutes_remaining}
- Alignment semanal: {alignment}
- Trades hoy: {trades_count} ({trades_summary})
- P&L del día: {daily_pnl} pts
- Actualizaciones intraday recientes: {recent_updates}
- Notas del plan: {plan_notes}

## Criterios de evaluación

Factores que FAVORECEN ejecución:
- Más de 60 minutos de sesión restantes
- Alineado con sesgo semanal
- Sin trades perdedores previos hoy (o el primero del día)
- Sin actualizaciones intraday recientes que contradigan el trade
- Riesgo razonable (stop < 10 pts)

Factores de RIESGO (no necesariamente descalificantes):
- Menos de 30 minutos para cierre (poco recorrido)
- Contra sesgo semanal (MISALIGNED)
- Día con 2+ trades perdedores (drawdown)
- Invalidación intraday reciente seguida de re-validación
- Riesgo alto (stop > 12 pts)
- Breakdown muy poco profundo (< 3 pts, señal débil)

## Decisión

Responde SOLO con JSON:

{
  "execute": true/false,
  "reasoning": "explicación breve en español de por qué ejecutar o consultar",
  "risk_factors": ["factor1", "factor2"]
}

- execute=true: la situación es claramente favorable, ejecutar sin consultar.
- execute=false: hay factores de riesgo relevantes, consultar al trader.

Sé conservador: en caso de duda, execute=false. Es mejor preguntar que perder.
```

### User prompt

```
Evalúa esta señal de trading para ejecución automática.
```

El contexto completo va en el system prompt para que Haiku tenga toda la
información antes de procesar.

### Parseo de respuesta

Igual que tweet_classifier: JSON limpio, fallback a `execute=false` si el
JSON es inválido (conservador por defecto).

---

## Componente 2: OrderExecutor

### Módulo: `scripts/mancini/order_executor.py`

Wrapper del SDK de TastyTrade para lanzar órdenes en /ES.

### Dependencias del SDK

```python
from tastytrade import Account, Session
from tastytrade.order import (
    NewOrder, Leg,
    OrderAction, OrderType, OrderTimeInForce, InstrumentType,
)
from tastytrade.instruments import Future
```

### Configuración

```python
# .env
TT_SECRET=...
TT_REFRESH=...

# Modo de ejecución (en config o .env)
MANCINI_DRY_RUN=true          # true = dry-run, false = live
MANCINI_CONTRACTS=1            # contratos a operar
```

### Clase OrderExecutor

```python
@dataclass
class OrderResult:
    success: bool
    order_id: str | None        # ID de la orden (None si dry-run)
    dry_run: bool
    details: dict               # respuesta del SDK
    error: str | None


class OrderExecutor:
    def __init__(self, session: Session, account: Account,
                 dry_run: bool = True, contracts: int = 1):
        self.session = session
        self.account = account
        self.dry_run = dry_run
        self.contracts = contracts

    def place_entry(self, direction: str, symbol: str) -> OrderResult:
        """Lanza orden de mercado para entrar en /ES."""
        action = OrderAction.BUY if direction == "LONG" else OrderAction.SELL
        leg = Leg(
            instrument_type=InstrumentType.FUTURE,
            symbol=symbol,          # ej. "/ESM6:XCME"
            action=action,
            quantity=self.contracts,
        )
        order = NewOrder(
            time_in_force=OrderTimeInForce.DAY,
            order_type=OrderType.MARKET,
            legs=[leg],
        )
        return self._submit(order)

    def place_stop(self, direction: str, symbol: str,
                   stop_price: float) -> OrderResult:
        """Lanza orden stop-loss."""
        # Stop para LONG = Sell, para SHORT = Buy
        action = OrderAction.SELL if direction == "LONG" else OrderAction.BUY
        leg = Leg(
            instrument_type=InstrumentType.FUTURE,
            symbol=symbol,
            action=action,
            quantity=self.contracts,
        )
        order = NewOrder(
            time_in_force=OrderTimeInForce.GTC,
            order_type=OrderType.STOP,
            stop_trigger=Decimal(str(stop_price)),
            legs=[leg],
        )
        return self._submit(order)

    def update_stop(self, order_id: str, new_stop: float) -> OrderResult:
        """Modifica el stop-loss existente (ej. mover a breakeven)."""
        try:
            response = self.account.replace_order(
                self.session,
                order_id,
                stop_trigger=Decimal(str(new_stop)),
            )
            return OrderResult(
                success=True, order_id=order_id,
                dry_run=False, details={"replaced": True}, error=None,
            )
        except Exception as e:
            return OrderResult(
                success=False, order_id=order_id,
                dry_run=False, details={}, error=str(e),
            )

    def close_position(self, direction: str, symbol: str) -> OrderResult:
        """Cierra posición con orden de mercado."""
        action = OrderAction.SELL if direction == "LONG" else OrderAction.BUY
        leg = Leg(
            instrument_type=InstrumentType.FUTURE,
            symbol=symbol,
            action=action,
            quantity=self.contracts,
        )
        order = NewOrder(
            time_in_force=OrderTimeInForce.DAY,
            order_type=OrderType.MARKET,
            legs=[leg],
        )
        return self._submit(order)

    def _submit(self, order: NewOrder) -> OrderResult:
        try:
            response = self.account.place_order(
                self.session, order, dry_run=self.dry_run
            )
            return OrderResult(
                success=True,
                order_id=getattr(response, 'id', None) if not self.dry_run else None,
                dry_run=self.dry_run,
                details=response.model_dump() if hasattr(response, 'model_dump') else {},
                error=None,
            )
        except Exception as e:
            return OrderResult(
                success=False, order_id=None,
                dry_run=self.dry_run, details={}, error=str(e),
            )
```

### Resolución del símbolo /ES

El `OrderExecutor` necesita el símbolo completo del contrato front-month
(ej. `/ESM6:XCME`). Esto ya se resuelve en `tastytrade_client.py` via
`_resolve_and_fetch`. Se añade un método público:

```python
# tastytrade_client.py
def get_front_month_symbol(self, product_code: str) -> str | None:
    """Resuelve el símbolo del contrato front-month activo."""
    ...
```

---

## Componente 3: Confirmación Telegram interactiva

### Problema

Hoy el bot de Telegram es push-only (envía mensajes, no recibe respuestas).
Para la confirmación del trader necesitamos interacción bidireccional.

### Solución: Inline Keyboard + polling de updates

Telegram Bot API soporta **inline keyboards** — botones dentro del mensaje
que el usuario puede pulsar. No requiere webhook, se puede comprobar via
polling con `getUpdates`.

### Implementación en `scripts/mancini/telegram_confirm.py`

```python
def ask_trader_confirmation(
    signal_info: str,
    risk_factors: list[str],
    reasoning: str,
    timeout_seconds: int = 120,
) -> bool | None:
    """Envía pregunta con botones Sí/No al trader. Retorna respuesta o None si timeout."""

    # 1. Construir mensaje con inline keyboard
    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Ejecutar", "callback_data": "exec_yes"},
            {"text": "❌ Descartar", "callback_data": "exec_no"},
        ]]
    }

    msg = f"""⚠️ *Señal pendiente de confirmación*

{signal_info}

🔍 *Factores de riesgo:*
{chr(10).join(f"  • {f}" for f in risk_factors)}

🤖 *Razonamiento:* {reasoning}

¿Ejecutar el trade?"""

    # 2. Enviar mensaje con botones
    response = httpx.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": escape_markdown(msg),
            "parse_mode": "MarkdownV2",
            "reply_markup": keyboard,
        },
    )
    message_id = response.json()["result"]["message_id"]

    # 3. Polling de callback_query (esperar respuesta del trader)
    deadline = time.time() + timeout_seconds
    last_update_id = 0

    while time.time() < deadline:
        updates = httpx.post(
            f"https://api.telegram.org/bot{token}/getUpdates",
            json={
                "offset": last_update_id + 1,
                "timeout": 10,          # long polling 10s
                "allowed_updates": ["callback_query"],
            },
        ).json()

        for update in updates.get("result", []):
            last_update_id = update["update_id"]
            cb = update.get("callback_query", {})
            if cb.get("message", {}).get("message_id") == message_id:
                # Responder al callback (quitar spinner)
                httpx.post(
                    f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                    json={"callback_query_id": cb["id"]},
                )
                answer = cb["data"]  # "exec_yes" o "exec_no"

                # Editar mensaje para reflejar decisión
                decision_text = "✅ Trade ejecutado" if answer == "exec_yes" else "❌ Trade descartado"
                httpx.post(
                    f"https://api.telegram.org/bot{token}/editMessageText",
                    json={
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "text": escape_markdown(f"{msg}\n\n*Decisión:* {decision_text}"),
                        "parse_mode": "MarkdownV2",
                    },
                )
                return answer == "exec_yes"

    # 4. Timeout — editar mensaje para indicar que expiró
    httpx.post(
        f"https://api.telegram.org/bot{token}/editMessageText",
        json={
            "chat_id": chat_id,
            "message_id": message_id,
            "text": escape_markdown(f"{msg}\n\n*⏰ Timeout — trade descartado*"),
            "parse_mode": "MarkdownV2",
        },
    )
    return None  # timeout = no ejecutar
```

### Timeout

- Default: 120 segundos (2 minutos)
- Si no hay respuesta: trade descartado (conservador)
- El mensaje se edita para mostrar que expiró

### Interacción con el monitor loop

El polling de confirmación **bloquea** el monitor loop durante hasta 2 min.
Esto es aceptable porque:
- Solo ocurre cuando hay factores de riesgo (gate dice execute=false)
- Durante ese tiempo, el precio sigue moviendose pero no hay acción pendiente
- Si el trader no responde, se descarta (seguro)

---

## Integración en monitor.py

### Cambios en `_handle_transition` (cuando `t.to_state == State.SIGNAL`)

```python
elif t.to_state == State.SIGNAL:
    _log(f"SIGNAL en {t.level} — ES={price}")
    breakdown_low = t.details.get("breakdown_low", price)
    direction = "LONG"
    alignment = self.calc_alignment(direction)
    targets = self._get_targets_for_level(t.level, alignment)

    # ── NUEVO: Execution Gate ──
    decision = evaluate_signal(
        signal_price=price,
        signal_level=t.level,
        breakdown_low=breakdown_low,
        direction=direction,
        plan=self.plan,
        weekly=self.weekly,
        alignment=alignment,
        trades_today=self.trade_manager.trades,
        recent_adjustments=self.intraday_state.adjustments,
        current_time_et=_now_et(),
        session_end_hour=self.session_end,
    )

    should_execute = decision.execute

    if not should_execute:
        # Preguntar al trader via Telegram
        stop = calc_stop(direction, price, breakdown_low)
        risk = abs(price - stop)
        signal_info = (
            f"📍 Nivel: {t.level} | ES: {price}\n"
            f"📉 Breakdown low: {breakdown_low}\n"
            f"🛑 Stop: {stop} (-{risk:.0f} pts)\n"
            f"🎯 Targets: {targets}\n"
            f"📊 Alignment: {alignment}"
        )
        trader_says_yes = ask_trader_confirmation(
            signal_info=signal_info,
            risk_factors=decision.risk_factors,
            reasoning=decision.reasoning,
            timeout_seconds=120,
        )
        if trader_says_yes:
            should_execute = True
            _log("Trader confirma ejecución manual")
        else:
            _log(f"Trade descartado: {'timeout' if trader_says_yes is None else 'trader dijo no'}")
            notifier.notify_trade_rejected(decision)
            return event

    # ── Ejecutar trade (lógica existente) ──
    trade = self.trade_manager.open_trade(...)

    # ── NUEVO: Lanzar orden en TastyTrade ──
    if trade and self.order_executor:
        entry_result = self.order_executor.place_entry(direction, self.es_symbol)
        if entry_result.success:
            stop_result = self.order_executor.place_stop(
                direction, self.es_symbol, trade.stop_price
            )
            trade.entry_order_id = entry_result.order_id
            trade.stop_order_id = stop_result.order_id if stop_result.success else None
            _log(f"Orden {'dry-run' if entry_result.dry_run else 'LIVE'}: entry OK, stop {'OK' if stop_result.success else 'FAIL'}")
        else:
            _log(f"Error lanzando orden: {entry_result.error}")

    ...
```

### Gestión del stop en `_handle_trade_event`

Cuando se alcanza un target, mover stop al target anterior (trailing):

```python
if event["type"] == "TARGET_HIT":
    _log(f"Target {event['target_index']+1} alcanzado: {event['target_price']}, stop → {event['new_stop']}")
    if self.order_executor and trade.stop_order_id:
        self.order_executor.update_stop(
            trade.stop_order_id, event["new_stop"]
        )
    notifier.notify_target_hit(event)
```

Cuando el trade se cierra por stop, la orden ya se ejecutó en TastyTrade
(el stop GTC se triggeró). El monitor solo actualiza el estado local:

```python
if event["type"] == "TRADE_CLOSED":
    # Stop GTC ya ejecutado en TastyTrade, solo limpiar estado
    _log(f"Trade cerrado: {event['reason']}")
```

---

## Política de stop-loss y gestión del contrato único

### Contexto: 1 contrato, sin salida parcial

Con `MANCINI_CONTRACTS=1` (caso base), no se puede cerrar el 50% en Target 1.
El contrato entero funciona como runner desde la apertura. La salida parcial
del TradeManager actual (50%/50%) **no aplica** con 1 contrato.

### Trailing stop: un target por detrás

Mancini mantiene runners overnight — el tweet de domingo a las 18:00 sigue
generando profit el miércoles (+240 pts). El cierre solo ocurre cuando el
stop se toca. No hay cierre EOD automático.

El stop sube (trailing) cada vez que se alcanza un nuevo target, pero se
coloca **en el target anterior**, no en el que se acaba de alcanzar. Esto
da margen al precio para respirar sin que un retroceso normal cierre la
posición.

### Tabla de trailing stop

| Evento | Stop se mueve a | Ejemplo (entry=6783) |
|--------|----------------|----------------------|
| Apertura | `breakdown_low - 2 pts` (máx 15 pts riesgo) | 6776 - 2 = 6774 |
| T1 alcanzado (6793) | `entry_price` (breakeven) | 6783 |
| T2 alcanzado (6809) | T1 (6793) | 6793 |
| T3 alcanzado (6830) | T2 (6809) | 6809 |
| TN alcanzado | T(N-1) | ... |
| Stop tocado | Cierre del contrato | posición cerrada |

### Sin cierre EOD automático

A diferencia de la implementación actual, el runner **no se cierra** a las
16:00 ET. El trade sobrevive overnight y el monitor retoma la gestión al
día siguiente cuando recarga el estado desde disco.

El cierre de `close_session()` cambia:
- Antes: cerraba trades activos a las 16:00 ET
- Ahora: solo expira detectores, NO cierra trades activos
- El trade activo se persiste en estado y se retoma al reiniciar el monitor

### Cierre manual vía Telegram

Se añade un botón en Telegram para cerrar manualmente el runner en
cualquier momento:

```
📊 Runner activo | +47 pts

📍 Entry: 6783 | Actual: 6830
🛑 Stop: 6809 (T2)
🎯 Siguiente: 6850

[🔒 Cerrar runner]
```

El botón `Cerrar runner` usa el mismo mecanismo de `callback_query` que
la confirmación de ejecución.

### Implementación en TradeManager

Cambios necesarios en `trade_manager.py`:

```python
class TradeManager:
    def process_tick(self, price, timestamp) -> list[dict]:
        """Procesa tick — con 1 contrato, no hay parcial."""
        trade = self.active_trade()
        if not trade:
            return []

        events = []

        # Check stop (trailing)
        if trade.direction == "LONG" and price <= trade.stop_price:
            events.append(self._close_trade(trade, price, ts, ExitReason.STOP))
            return events

        # Check targets — trailing stop, NO cierre parcial
        for i, target in enumerate(trade.targets):
            if trade.targets_hit >= i + 1:
                continue  # ya alcanzado
            if (trade.direction == "LONG" and price >= target) or \
               (trade.direction == "SHORT" and price <= target):
                trade.targets_hit = i + 1
                # Mover stop al target anterior
                if i == 0:
                    new_stop = trade.entry_price  # breakeven
                else:
                    new_stop = trade.targets[i - 1]  # target anterior
                trade.stop_price = new_stop
                events.append({
                    "type": "TARGET_HIT",
                    "trade_id": trade.id,
                    "target_index": i,
                    "target_price": target,
                    "new_stop": new_stop,
                    "price": price,
                    "timestamp": ts,
                })
                break  # un target por tick

        return events
```

Campo nuevo en Trade:
```python
@dataclass
class Trade:
    ...
    targets_hit: int = 0  # número de targets alcanzados
```

### Sincronización con TastyTrade

El `OrderExecutor` replica el trailing stop en órdenes reales:

1. **Entry**: `place_entry()` (market) + `place_stop()` (GTC stop)
2. **Target N alcanzado**: `update_stop(order_id, new_stop_price)`
3. **Stop tocado**: TastyTrade ejecuta la orden stop automáticamente.
   El monitor detecta el cierre en el siguiente poll y actualiza estado.

En dry-run, las llamadas se ejecutan pero no afectan el mercado. El SDK
retorna la validación de la orden (márgenes, formato) sin ejecutarla.

### Notificación en cada target hit

```
🎯 Target 2 alcanzado

📍 6809 | ES: 6810
🛑 Stop subido: 6774 → 6793 (T1)
📈 Runner activo: +27 pts

Siguiente target: 6830
```

---

## Notificaciones Telegram

### Nuevos tipos de alerta en `notifier.py`

**Gate aprueba ejecución:**
```
✅ Execution Gate — APROBADO

📍 Nivel: 6781 | ES: 6783
🛑 Stop: 6771 (-12 pts)
🎯 Targets: 6793, 6809

🤖 Contexto favorable: primer trade del día, 4h de sesión,
   alineado con sesgo semanal.

📊 Orden: dry-run | 1x /ESM6:XCME
```

**Gate rechaza (pregunta al trader):**
```
⚠️ Señal pendiente de confirmación

📍 Nivel: 6781 | ES: 6783
🛑 Stop: 6771 (-12 pts)
🎯 Targets: 6793, 6809

🔍 Factores de riesgo:
  • Menos de 25 min para cierre
  • Segundo trade perdedor del día

🤖 Señal técnicamente válida pero poco recorrido y día negativo.

[✅ Ejecutar]  [❌ Descartar]
```

**Trade rechazado (trader dijo no o timeout):**
```
🚫 Trade descartado

📍 Nivel: 6781 | ES: 6783
❌ Razón: trader rechazó / timeout

🤖 Factores: poco recorrido, día negativo
```

---

## Configuración

### Variables de entorno nuevas

```env
# Execution mode
MANCINI_DRY_RUN=true              # true = dry-run (default), false = live
MANCINI_CONTRACTS=1                # contratos por trade (default: 1)
MANCINI_GATE_ENABLED=true          # true = gate LLM activo, false = ejecutar sin gate
MANCINI_CONFIRM_TIMEOUT=120        # segundos de espera en confirmación Telegram
```

### Flags en monitor

```python
class ManciniMonitor:
    def __init__(self, ..., order_executor=None, gate_enabled=True):
        self.order_executor = order_executor  # None = sin órdenes
        self.gate_enabled = gate_enabled
```

Si `order_executor=None`, el sistema funciona como hasta ahora (solo tracking
local). Si se proporciona, las órdenes se lanzan en TastyTrade.

Si `gate_enabled=False`, el trade se ejecuta directamente sin consultar al LLM.

---

## Fases de despliegue

### Fase 1: Gate + dry-run (esta implementación)
- LLM evalúa cada señal
- Órdenes en dry-run (TastyTrade valida pero no ejecuta)
- Confirmación Telegram cuando hay riesgo
- Log de todas las decisiones para calibración posterior

### Fase 2: Live con confirmación obligatoria
- `MANCINI_DRY_RUN=false`
- Toda señal pasa por el gate
- Si gate dice execute=false → Telegram obligatorio
- Si gate dice execute=true → ejecutar automáticamente

### Fase 3: Full auto (futuro, tras calibración)
- Gate con historial de aciertos
- Si confidence > threshold calibrado → ejecutar sin preguntar
- Si confidence < threshold → Telegram

---

## Módulos afectados

### Nuevos
- `scripts/mancini/execution_gate.py` — LLM gate de validación
- `scripts/mancini/order_executor.py` — wrapper TastyTrade órdenes
- `scripts/mancini/telegram_confirm.py` — confirmación interactiva

### Modificados
- `scripts/mancini/monitor.py` — integración gate + executor en SIGNAL
- `scripts/mancini/notifier.py` — nuevas alertas (gate approved, rejected, etc.)
- `scripts/mancini/trade_manager.py` — campo `targets_hit`, trailing stop, eliminar salida parcial, campos order_id en Trade
- `scripts/tastytrade_client.py` — método `get_front_month_symbol()`
- `scripts/mancini/run_mancini.py` — nuevos flags CLI (`--dry-run`, `--no-gate`)
- `scripts/mancini/logger.py` — log de decisiones del gate

---

## Trade dataclass — campos nuevos

```python
@dataclass
class Trade:
    ...
    # Nuevos campos para trailing stop
    targets_hit: int = 0                 # número de targets alcanzados
    # Nuevos campos para órdenes
    entry_order_id: str | None = None    # ID orden entry en TastyTrade
    stop_order_id: str | None = None     # ID orden stop-loss
    gate_decision: dict | None = None    # {execute, reasoning, risk_factors}
    execution_mode: str = ""             # "auto" | "manual_confirm" | "rejected"
```

---

## Tests

### test_execution_gate.py
- `test_gate_approves_favorable_conditions`: primer trade, hora temprana → execute=True
- `test_gate_rejects_late_session`: menos de 30 min → execute=False
- `test_gate_rejects_after_losses`: 2 trades perdedores → execute=False
- `test_gate_invalid_json_defaults_false`: JSON inválido → execute=False (conservador)
- `test_gate_includes_risk_factors`: factores de riesgo en respuesta
- `test_gate_disabled_always_executes`: gate_enabled=False → siempre ejecutar

### test_order_executor.py
- `test_place_entry_long_dry_run`: orden market BUY en dry-run
- `test_place_entry_short_dry_run`: orden market SELL en dry-run
- `test_place_stop_long`: stop SELL con trigger
- `test_update_stop_breakeven`: modificar stop existente
- `test_close_position`: cerrar con market order
- `test_place_entry_error_handling`: error del SDK → OrderResult con error

### test_telegram_confirm.py
- `test_ask_confirmation_yes`: callback "exec_yes" → True
- `test_ask_confirmation_no`: callback "exec_no" → False
- `test_ask_confirmation_timeout`: sin respuesta → None
- `test_message_includes_risk_factors`: mensaje formateado correctamente
- `test_message_edited_after_decision`: mensaje editado con resultado

### test_monitor_gate_integration.py
- `test_signal_with_gate_approved`: gate OK → trade abierto + orden
- `test_signal_with_gate_rejected_trader_confirms`: gate NO + trader sí → trade abierto
- `test_signal_with_gate_rejected_trader_declines`: gate NO + trader no → trade descartado
- `test_signal_with_gate_rejected_timeout`: gate NO + timeout → trade descartado
- `test_signal_without_gate`: gate_enabled=False → ejecución directa
- `test_no_executor_works_as_before`: sin executor → comportamiento actual

### test_trailing_stop.py
- `test_t1_hit_stop_to_breakeven`: T1 alcanzado → stop sube a entry_price
- `test_t2_hit_stop_to_t1`: T2 alcanzado → stop sube a T1
- `test_t3_hit_stop_to_t2`: T3 alcanzado → stop sube a T2
- `test_no_partial_exit_single_contract`: 1 contrato → sin evento PARTIAL_EXIT
- `test_stop_updated_in_tastytrade_on_target_hit`: trailing stop sincronizado
- `test_runner_survives_eod`: trade activo NO se cierra a las 16:00 ET
- `test_runner_persists_across_restarts`: trade se carga desde disco al reiniciar
- `test_stop_hit_closes_trade`: precio toca stop → cierre completo
- `test_targets_hit_counter`: targets_hit incrementa correctamente
