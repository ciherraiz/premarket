# Mancini Replicant — Failed Breakdown/Breakout ES Futures

## Objetivo

Replicar la estrategia de trading de Adam Mancini (@AdamMancini4) en futuros /ES,
centrada en el patrón **Failed Breakdown/Breakout**. El sistema lee automáticamente
los tweets de Mancini, extrae los niveles clave, monitoriza /ES en tiempo real,
detecta patrones de failed breakdown, y propone trades con gestión de riesgo.

## Módulos

### 1. config.py — Modelo de datos

**DailyPlan** (dataclass):
```
fecha: str               # YYYY-MM-DD
raw_tweets: list[str]    # Textos originales de tweets
key_level_upper: float   # Nivel reclaim (long si se recupera)
targets_upper: list[float]  # Objetivos alcistas
key_level_lower: float   # Nivel fail (sell si rompe)
targets_lower: list[float]  # Objetivos bajistas
chop_zone: tuple[float, float] | None  # Rango de consolidación
notes: str               # Notas / actualizaciones intraday
created_at: str           # ISO timestamp
updated_at: str           # ISO timestamp última actualización
```

Persistencia: `outputs/mancini_plan.json` (sobrescrito por scan de tweets).

### 2. detector.py — Máquina de estados

**FailedBreakdownDetector**: una instancia por nivel clave.

Estados:
- `WATCHING` — monitorizando precio cerca del nivel
- `BREAKDOWN` — precio rompió el nivel (2-11 pts penetración)
- `RECOVERY` — precio recuperó el nivel
- `SIGNAL` — aceptación confirmada (3 polls consecutivos sobre nivel)
- `ACTIVE` — trade abierto
- `DONE` — trade cerrado
- `EXPIRED` — ventana cerrada sin señal

Transiciones (Failed Breakdown → señal LONG):
```
WATCHING → BREAKDOWN:   precio < nivel - MIN_BREAK_PTS(2)
                        AND precio > nivel - MAX_BREAK_PTS(11)
BREAKDOWN → RECOVERY:   precio > nivel + ACCEPTANCE_PTS(1.5)
RECOVERY → SIGNAL:      ACCEPTANCE_POLLS(3) consecutivos sobre nivel
BREAKDOWN → WATCHING:   precio < nivel - MAX_BREAK_PTS (break real)
SIGNAL → ACTIVE:        trade registrado
ACTIVE → DONE:          target/stop/EOD
Cualquier → EXPIRED:    fuera de ventana de trading
```

Constantes configurables:
```python
MIN_BREAK_PTS = 2
MAX_BREAK_PTS = 11
ACCEPTANCE_PTS = 1.5
ACCEPTANCE_POLLS = 3
```

Estado persistido en `outputs/mancini_state.json` para sobrevivir reinicios.

Método principal: `process_tick(price: float, timestamp: str) -> StateTransition | None`

### 3. trade_manager.py — Gestión de trades

**Trade** (dataclass):
```
id: str                    # UUID
direction: str             # "LONG" | "SHORT"
entry_price: float
entry_time: str
stop_price: float          # Debajo del breakdown low, máx 15 pts
targets: list[float]
status: str                # "OPEN" | "PARTIAL" | "CLOSED"
partial_exit_price: float | None
partial_exit_time: str | None
runner_stop: float | None  # Breakeven tras Target 1
exit_price: float | None
exit_time: str | None
exit_reason: str | None    # "TARGET_1" | "TARGET_2" | "STOP" | "RUNNER_STOP" | "EOD"
pnl_points: float | None
```

Reglas Mancini:
- Entry al confirmarse SIGNAL, al precio actual
- Stop debajo del mínimo del breakdown (máx 15 pts)
- Target 1: parcial 50%
- Tras Target 1: stop a breakeven (nunca green-to-red)
- Runner: posición restante busca Target 2+
- Máx 3 trades/día
- Objetivo 10-15 pts por trade

### 4. monitor.py — Polling /ES

Proceso Python de larga duración. Cada 60 segundos:
1. Lee `outputs/mancini_plan.json`
2. Lee/escribe `outputs/mancini_state.json`
3. Poll /ES via `TastyTradeClient.get_future_quote("/ES")`
4. Alimenta detectores con `process_tick()`
5. Gestiona trades activos
6. Alerta Telegram si hay transición
7. Auto-finaliza a las 11:00 ET

### 5. notifier.py — Alertas Telegram

6 tipos: plan escaneado, plan cargado, breakdown detectado,
señal de entrada, target alcanzado, trade cerrado.

Reutiliza `send_telegram()` y `_esc()` de `scripts/notify_telegram.py`.

### 6. logger.py — Registro JSONL

Append-only en `logs/mancini_trades.jsonl`. Cada trade:
```json
{
  "fecha": "YYYY-MM-DD",
  "trade_id": "uuid",
  "direction": "LONG",
  "key_level": 6781,
  "breakdown_low": 6776,
  "entry_price": 6783,
  "stop_initial": 6773,
  "targets": [6793, 6809],
  "exit_price": 6793,
  "exit_reason": "TARGET_1",
  "pnl_points": 10
}
```

### 7. tweet_fetcher.py + tweet_parser.py + Skill /mancini-scan

**tweet_fetcher.py** — obtiene tweets vía `httpx` + GraphQL API de X (session cookies):
1. Carga cookies exportadas con Cookie-Editor (`cookies.json`)
2. Usa GraphQL API de X (UserByScreenName + UserTweets) con bearer token público
3. Filtrado a tweets del día (timezone ET)
4. Retorna lista de `{id, text, created_at}`

**tweet_parser.py** — extrae niveles estructurados vía Claude Haiku:
1. Construye prompt con convenciones de notación de Mancini
2. Llama a Haiku (`ANTHROPIC_API_KEY`) con los tweets como input
3. Parsea respuesta JSON a `DailyPlan`
4. Retorna `None` si Haiku determina que no hay plan nuevo

**Skill /mancini-scan** — orquesta fetch + parse + save:
1. `fetch_tweets_sync()` → tweets del día
2. `parse_tweets_to_plan()` → DailyPlan o None
3. Merge con plan existente si ya hay uno de hoy
4. `save_plan()` → `outputs/mancini_plan.json`

Ficheros requeridos: `cookies.json` (exportado con Cookie-Editor desde x.com)
Env vars requeridas: `ANTHROPIC_API_KEY` (opcional: `X_COOKIES_FILE` para ruta custom)

### 8. run_mancini.py — CLI

Subcomandos:
- `monitor` — arranca loop de polling (proceso larga duración)
- `status` — muestra estado actual (plan + máquinas + trades)
- `reset` — resetea estado para nuevo día

## Ventanas de trading

- 07:00-11:30 ET — scan de tweets (scheduled task cada 10 min)
- 08:00-11:00 ET — monitor activo (polling cada 60s)
- 14:00-16:00 ET — sesión tarde (opcional)

## Ficheros de estado

- `outputs/mancini_plan.json` — plan del día (niveles)
- `outputs/mancini_state.json` — estado máquinas + trades activos
- `logs/mancini_trades.jsonl` — historial de trades
