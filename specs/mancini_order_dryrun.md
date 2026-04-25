# Mancini — Activación dry-run de órdenes TastyTrade

## Estado actual

La infraestructura de ejecución está implementada pero **nunca ha ejecutado una
orden real ni dry-run** contra TastyTrade. La primera señal real del 2026-04-24
confirma que el pipeline de detección funciona. El siguiente paso es conectar
esa señal con órdenes validadas por TastyTrade en modo simulado.

### Qué existe

| Módulo | Estado |
|--------|--------|
| `order_executor.py` | ✅ Implementado. `place_entry`, `place_stop`, `update_stop`, `close_position` |
| `monitor.py` | ✅ Integrado. `_place_trade_orders()`, `update_stop` en TARGET_HIT |
| `run_mancini.py` | ✅ Lee `MANCINI_DRY_RUN`, construye `OrderExecutor`, pasa `--live` flag |
| `telegram_confirm.py` | ✅ Confirmación interactiva con botones |
| `logger.py` | ✅ Logs de trades, gate decisions — **sin log de órdenes** |

### Gaps detectados

1. **Sin log de órdenes** — Las llamadas dry-run a TastyTrade no dejan rastro en
   ningún fichero. Si una validación falla o el SDK retorna un warning no hay forma
   de auditarlo.

2. **Sin notificación Telegram del resultado de la orden** — Cuando el gate aprueba
   y se lanza la orden, el trader no recibe confirmación de que TastyTrade la aceptó
   ni del resultado de la validación (buying power, margin check).

3. **Sin smoke-test manual** — Para verificar que las credenciales y el símbolo
   funcionan, hoy hay que esperar a que el detector genere una señal real.
   No existe un script de prueba aislado.

4. **Sin campo `dry_run` en Trade** — El Trade persiste `entry_order_id` y
   `stop_order_id`, pero no si esas órdenes fueron dry-run o live. El log JSONL
   no permite distinguir entre una sesión simulada y una real.

---

## Objetivo

Activar el modo dry-run de forma controlada y verificable:

1. Poder lanzar una orden dry-run manualmente (smoke-test) sin señal real.
2. Registrar cada llamada al SDK con su resultado completo.
3. Notificar al trader el resultado de la validación vía Telegram.
4. Marcar el Trade como dry-run en el log JSONL.

---

## Cambios requeridos

### 1. Campo `dry_run` en Trade

**Fichero:** `scripts/mancini/trade_manager.py`

Añadir campo al dataclass `Trade`:

```python
@dataclass
class Trade:
    ...
    dry_run: bool = True  # True = órdenes dry-run, False = live
```

Se asigna en `TradeManager.open_trade()` a partir de un parámetro nuevo:

```python
def open_trade(self, ..., dry_run: bool = True) -> Trade | None:
    ...
    trade = Trade(
        ...
        dry_run=dry_run,
    )
```

El monitor pasa `dry_run=self.order_executor.dry_run if self.order_executor else True`.

---

### 2. Log de órdenes

**Fichero:** `scripts/mancini/logger.py`

Nuevo path y función:

```python
ORDERS_LOG_PATH = Path("logs/mancini_orders.jsonl")

def append_order_result(
    trade_id: str,
    order_type: str,          # "entry" | "stop" | "update_stop" | "close"
    result: "OrderResult",
    symbol: str = "",
    path: Path = ORDERS_LOG_PATH,
) -> None:
    """Registra el resultado de una llamada al OrderExecutor."""
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "trade_id": trade_id,
        "order_type": order_type,
        "symbol": symbol,
        "success": result.success,
        "order_id": result.order_id,
        "dry_run": result.dry_run,
        "details": result.details,
        "error": result.error,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
```

---

### 3. Llamadas a `append_order_result` en monitor.py

**Fichero:** `scripts/mancini/monitor.py`, método `_place_trade_orders`

```python
def _place_trade_orders(self, trade, direction: str) -> None:
    if not self.order_executor or not self.es_symbol:
        return

    entry_result = self.order_executor.place_entry(direction, self.es_symbol)
    append_order_result(trade.id, "entry", entry_result, self.es_symbol)

    if entry_result.success:
        trade.entry_order_id = entry_result.order_id
        stop_result = self.order_executor.place_stop(
            direction, self.es_symbol, trade.stop_price
        )
        append_order_result(trade.id, "stop", stop_result, self.es_symbol)
        if stop_result.success:
            trade.stop_order_id = stop_result.order_id
        ...
```

También en el handler de TARGET_HIT (update_stop):

```python
update_result = self.order_executor.update_stop(
    trade.stop_order_id, event["new_stop"]
)
append_order_result(trade.id, "update_stop", update_result, self.es_symbol)
```

---

### 4. Notificación Telegram del resultado de la orden

**Fichero:** `scripts/mancini/notifier.py`

Nueva función:

```python
def notify_order_result(
    order_type: str,          # "entry" | "stop" | "update_stop"
    result: "OrderResult",
    trade_info: str = "",
) -> bool:
    """Notifica al trader el resultado de una orden TastyTrade."""
    mode = "DRY-RUN" if result.dry_run else "🔴 LIVE"
    status = "✅" if result.success else "❌"

    lines = [
        f"{status} *Orden {_esc(order_type.upper())}* — {_esc(mode)}",
    ]
    if trade_info:
        lines += ["", _esc(trade_info)]

    if result.success:
        if result.order_id:
            lines.append(f"🆔 Order ID: {_esc(result.order_id)}")
        # Mostrar buying power effect si el SDK lo retorna
        bp = result.details.get("buying_power_effect")
        if bp:
            lines.append(f"💰 Buying power: {_esc(str(bp))}")
    else:
        lines.append(f"⚠️ Error: {_esc(result.error or 'desconocido')}")

    return send_telegram("\n".join(lines))
```

Se llama desde `_place_trade_orders` en monitor.py solo para la orden de entry
(la de stop es subordinada, no merece notificación independiente salvo error):

```python
if entry_result.success:
    notifier.notify_order_result("entry", entry_result,
                                 trade_info=f"Nivel {level} | ES {price}")
elif not entry_result.success:
    notifier.notify_order_result("entry", entry_result)  # error
```

---

### 5. Script de smoke-test

**Fichero nuevo:** `scripts/mancini/smoke_test_order.py`

Permite verificar credenciales, símbolo y dry-run sin esperar señal real:

```python
"""
Smoke-test del OrderExecutor en modo dry-run.

Lanza una orden LONG de mercado en /ES en dry-run y un stop GTC,
e imprime el resultado del SDK. No ejecuta nada real.

Uso:
    uv run python scripts/mancini/smoke_test_order.py
"""
import os
from decimal import Decimal

from tastytrade import Account
from scripts.tastytrade_client import TastyTradeClient
from scripts.mancini.order_executor import OrderExecutor


def main() -> None:
    client = TastyTradeClient()
    es_symbol = client.get_front_month_symbol("ES")
    if not es_symbol:
        print("❌ No se pudo resolver /ES front-month")
        return
    print(f"✅ Símbolo resuelto: {es_symbol}")

    accounts = Account.get_accounts(client.session)
    if not accounts:
        print("❌ No se encontraron cuentas TastyTrade")
        return
    account = accounts[0]
    print(f"✅ Cuenta: {account.account_number}")

    executor = OrderExecutor(
        session=client.session,
        account=account,
        dry_run=True,
        contracts=1,
    )

    # Obtener precio actual para construir stop razonable
    quote = client.get_future_quote("/ES")
    if not quote or not quote.get("mark"):
        print("❌ No se pudo obtener precio /ES")
        return
    price = float(quote["mark"])
    stop = round(price - 15, 2)
    print(f"✅ Precio /ES: {price} | Stop simulado: {stop}")

    # Orden de entrada
    print("\n--- Orden ENTRY (dry-run) ---")
    entry = executor.place_entry("LONG", es_symbol)
    print(f"  success={entry.success}")
    print(f"  order_id={entry.order_id}")
    print(f"  dry_run={entry.dry_run}")
    print(f"  error={entry.error}")
    print(f"  details={entry.details}")

    # Orden de stop
    print("\n--- Orden STOP (dry-run) ---")
    stop_result = executor.place_stop("LONG", es_symbol, stop)
    print(f"  success={stop_result.success}")
    print(f"  order_id={stop_result.order_id}")
    print(f"  error={stop_result.error}")
    print(f"  details={stop_result.details}")


if __name__ == "__main__":
    main()
```

**Uso:**
```bash
uv run python scripts/mancini/smoke_test_order.py
```

Criterio de éxito: ambas órdenes retornan `success=True`, `dry_run=True`.

---

## Respuesta del SDK TastyTrade en dry-run

Cuando `dry_run=True`, el SDK llama a:
```
POST /accounts/{account}/orders/dry-run
```

TastyTrade valida:
- Formato de la orden (tipo, acción, símbolo)
- Disponibilidad de buying power
- Margen requerido
- Si el mercado está abierto (para órdenes MARKET)

La respuesta contiene `buying_power_effect` con campos relevantes:
- `change_in_buying_power`: impacto en buying power (negativo = consume)
- `current_buying_power`: buying power disponible antes de la orden
- `new_buying_power`: buying power si la orden se ejecutara

Si la validación falla (ej. mercado cerrado para MARKET orders), retorna error
que el `OrderResult.error` captura.

**Implicación importante:** Las órdenes MARKET en dry-run pueden fallar si el
mercado está cerrado. Para smoke-tests fuera de horario, usar `OrderType.LIMIT`
con un precio límite razonable en lugar de MARKET.

---

## Configuración

Variables de entorno relevantes (ya definidas en `.env`):

```env
MANCINI_DRY_RUN=true       # true (default) = dry-run, false = live
MANCINI_CONTRACTS=1        # contratos por trade
MANCINI_GATE_ENABLED=true  # true = LLM gate activo
```

Para activar dry-run al arrancar el monitor:

```bash
# Arrancar con dry-run (default, MANCINI_DRY_RUN=true)
scripts\mancini\monitor_start.bat

# Verificar que el OrderExecutor se inicializó:
# [LOG] OrderExecutor: DRY-RUN | 1 contrato(s) | /ESM6:XCME
```

---

## Fases de validación

### Fase A: Smoke-test offline (hoy)
1. Ejecutar `smoke_test_order.py` fuera de horario de mercado
2. Verificar que TastyTrade responde (incluso con error de mercado cerrado)
3. Comprobar que `OrderResult.details` contiene campos útiles del SDK

### Fase B: Smoke-test en horario de mercado
1. Ejecutar `smoke_test_order.py` entre 09:30 y 16:00 ET
2. Verificar `success=True` en ambas órdenes
3. Confirmar que TastyTrade NO ejecuta nada real (buying power sin cambio real)

### Fase C: Primera señal real en dry-run
1. Arrancar monitor con `MANCINI_DRY_RUN=true` (default)
2. Verificar en Telegram que al producirse la señal aparece:
   - Mensaje del gate (APROBADO)
   - Mensaje de orden entry (DRY-RUN ✅)
3. Verificar en `logs/mancini_orders.jsonl` que se registró la orden
4. Verificar en `logs/mancini_trades.jsonl` que el trade tiene `dry_run=true`

### Fase D: Live (tras calibración)
- Cambiar `MANCINI_DRY_RUN=false` en `.env`
- Primera operativa live con 1 contrato, gate activo y confirmación Telegram

---

## Tests

### test_order_log.py

```python
def test_append_order_result_success(tmp_path):
    """Orden exitosa se persiste con todos los campos."""

def test_append_order_result_error(tmp_path):
    """Orden fallida persiste error y success=False."""

def test_append_order_result_dry_run_flag(tmp_path):
    """El campo dry_run del OrderResult se registra correctamente."""
```

### test_trade_dry_run_field.py

```python
def test_trade_dry_run_default_true():
    """Trade creado sin parámetro tiene dry_run=True."""

def test_trade_dry_run_false_when_live():
    """Trade creado con dry_run=False lo refleja en el dict."""

def test_trade_dry_run_persists_in_to_dict():
    """El campo dry_run aparece en Trade.to_dict()."""
```

### test_notify_order_result.py

```python
def test_notify_entry_success_dry_run(mock_send):
    """Mensaje incluye DRY-RUN y ✅ si success=True."""

def test_notify_entry_failure(mock_send):
    """Mensaje incluye ❌ y texto de error si success=False."""

def test_notify_includes_buying_power(mock_send):
    """Si details contiene buying_power_effect se muestra en Telegram."""
```

### test_smoke_test_integration.py (opcional, requiere VCR/mock del SDK)

```python
def test_smoke_test_resolves_symbol(mock_client):
    """get_front_month_symbol retorna símbolo válido."""

def test_smoke_test_place_entry_dry_run(mock_executor):
    """place_entry dry_run=True retorna success=True sin tocar mercado."""
```

---

## Módulos afectados

| Módulo | Cambio |
|--------|--------|
| `trade_manager.py` | Campo `dry_run: bool = True` en `Trade` |
| `logger.py` | `append_order_result()` + `ORDERS_LOG_PATH` |
| `monitor.py` | Llamadas a `append_order_result` en `_place_trade_orders` y TARGET_HIT |
| `notifier.py` | `notify_order_result()` |
| `smoke_test_order.py` | Fichero nuevo de smoke-test manual |

No hay cambios en `order_executor.py` ni en `run_mancini.py` — ya están completos.
