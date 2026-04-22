# Mancini Replicant — Failed Breakdown/Breakout ES Futures

## Objetivo

Replicar la estrategia de trading de Adam Mancini (@AdamMancini4) en futuros /ES,
centrada en el patrón **Failed Breakdown/Breakout**. El sistema lee automáticamente
los tweets de Mancini, extrae los niveles clave, monitoriza /ES en tiempo real,
detecta patrones de failed breakdown, y propone trades con gestión de riesgo.

## Módulos

### 1. config.py — Modelo de datos

**SessionMode** (enum):
```
FRESH_SETUP    # niveles nuevos, buscar entrada al producirse el patrón
RUNNER_ACTIVE  # posición ya abierta corriendo, no buscar entrada nueva
WAIT_PULLBACK  # esperar retroceso a un nivel para buscar failed breakdown
NO_SETUP       # sin setup accionable hoy
```

**DailyPlan** (dataclass):
```
fecha: str               # YYYY-MM-DD
raw_tweets: list[str]    # Textos originales de tweets
key_level_upper: float   # Nivel reclaim (long si se recupera)
targets_upper: list[float]  # Objetivos alcistas
key_level_lower: float   # Nivel fail (sell si rompe)
targets_lower: list[float]  # Objetivos bajistas
chop_zone: tuple[float, float] | None  # Rango de consolidación
session_mode: SessionMode  # estado operativo de la sesión
notes: str               # resumen/contexto extraído de los tweets
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
- `SIGNAL` — aceptación confirmada (precio ≥ nivel + ACCEPTANCE_PTS durante ACCEPTANCE_SECONDS continuos)
- `ACTIVE` — trade abierto
- `DONE` — trade cerrado
- `EXPIRED` — ventana cerrada sin señal

Transiciones (Failed Breakdown → señal LONG):
```
WATCHING → BREAKDOWN:   precio < nivel - MIN_BREAK_PTS(2)
                        AND precio > nivel - MAX_BREAK_PTS(11)
BREAKDOWN → RECOVERY:   precio > nivel + ACCEPTANCE_PTS(1.5)  → arranca reloj
RECOVERY → SIGNAL:      precio ≥ nivel + ACCEPTANCE_PTS durante ACCEPTANCE_SECONDS(120) continuos
                        (el reloj se pausa si el precio baja del umbral, se resetea si rompe el nivel)
BREAKDOWN → WATCHING:   precio < nivel - MAX_BREAK_PTS (break real)
SIGNAL → ACTIVE:        trade registrado
ACTIVE → DONE:          target/stop/EOD
Cualquier → EXPIRED:    fuera de ventana de trading
```

Constantes configurables:
```python
MIN_BREAK_PTS = 2        # penetración mínima para break convincente
MAX_BREAK_PTS = 11       # más allá = break real
ACCEPTANCE_PTS = 1.5     # margen sobre nivel para contar aceptación
ACCEPTANCE_SECONDS = 120 # segundos continuos sobre umbral para confirmar señal
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
7. Auto-finaliza a las 16:00 ET

### 5. notifier.py — Alertas Telegram

6 tipos: plan escaneado, plan cargado, breakdown detectado,
señal de entrada, target alcanzado, trade cerrado.

**Formato notify_plan_loaded** (mejorado):
```
🎯 Mancini Plan | YYYY-MM-DD

📊 Modo: RUNNER ACTIVO — dejar correr, no buscar entrada nueva

🟢 Upper: 7135.0 → 7153.0, 7165.0, 7180.0
🔴 Setup pendiente: 7120.0 → retroceso para failed breakdown

💬 "resumen del contexto extraído de los tweets"

📡 Monitor activo 03:00-16:00 ET   ← solo si llamada desde monitor
```
El `session_mode` determina el texto del modo y el icono del nivel inferior:
- `FRESH_SETUP`: sin línea de modo, formato estándar
- `RUNNER_ACTIVE`: "dejar correr, no buscar entrada nueva"
- `WAIT_PULLBACK`: nivel lower se muestra como "Setup pendiente"
- `NO_SETUP`: "sin setup accionable hoy"

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

### 7. tweet_fetcher.py + tweet_parser.py

**tweet_fetcher.py** — obtiene tweets vía `httpx` + GraphQL API de X (session cookies):
1. Carga cookies exportadas con Cookie-Editor (`cookies.json`)
2. Auto-descubre hashes GraphQL desde JS bundles de x.com (sobrevive rotaciones)
3. Usa endpoint SearchTimeline (POST) con query `from:AdamMancini4` — tiempo real
4. Filtrado por ventana de sesión (ver abajo)
5. Retorna lista de `{id, text, created_at}`

**Ventana de búsqueda de tweets**: Mancini publica el plan para la siguiente
sesión después del cierre RTH (16:00 ET). Por ejemplo, el domingo por la noche
publica el plan del lunes. Por tanto, `fetch_mancini_tweets` busca tweets desde
las **16:00 ET del día anterior** hasta el momento actual. Esto cubre:
- Tweets post-cierre del día anterior (plan para mañana)
- Tweets pre-apertura del día actual (ajustes matutinos)
- Tweets intraday del día actual

Ver `specs/mancini_realtime_tweets.md` para detalle de la migración de UserTweets a SearchTimeline.

**tweet_parser.py** — extrae niveles y modo de sesión vía Claude Haiku:
- El JSON de salida incluye `session_mode` además de niveles y notas
- Reglas de detección: "runner"/"nothing to do" → `RUNNER_ACTIVE`;
  "wait for pullback"/"dip to X" → `WAIT_PULLBACK`;
  niveles nuevos accionables → `FRESH_SETUP`; sin niveles → `NO_SETUP`

**tweet_parser.py** — extrae niveles estructurados vía Claude Haiku:
1. Construye prompt con convenciones de notación de Mancini
2. Llama a Haiku (`ANTHROPIC_API_KEY`) con los tweets como input
3. Parsea respuesta JSON a `DailyPlan`
4. Retorna `None` si Haiku determina que no hay plan nuevo

Ficheros requeridos: `cookies.json` (exportado con Cookie-Editor desde x.com)
Env vars requeridas: `ANTHROPIC_API_KEY` (opcional: `X_COOKIES_FILE` para ruta custom)

### 8. run_mancini.py — CLI (punto de entrada único)

Subcomandos:
- `scan` — fetch tweets + parse + save/merge plan diario
- `weekly-scan` — fetch Big Picture View + parse + save plan semanal
- `monitor` — arranca loop de polling (proceso larga duración)
- `status` — muestra estado actual (plan + máquinas + trades)
- `reset` — resetea estado para nuevo día

### 9. Scheduling — Windows Task Scheduler

**Obligatorio**: todas las tareas recurrentes usan Windows Task Scheduler.
No usar CronCreate ni mecanismos dependientes de sesión Claude.

Ver `specs/scheduled_tasks.md` para la configuración completa de cada tarea.

Cada tarea se ejecuta vía un `.bat` wrapper en `scripts/mancini/` que invoca
`run_mancini.py <subcomando>`.

## Ventanas de trading

- 07:00-16:00 ET — scan de tweets (Task Scheduler cada 10 min, cubre toda la sesión regular)
- 03:00-16:00 ET — monitor activo (desde apertura sesión europea, polling cada 60s, auto-para a las 16:00 ET)

## Ficheros de estado

- `outputs/mancini_plan.json` — plan del día (niveles)
- `outputs/mancini_state.json` — estado máquinas + trades activos
- `logs/mancini_trades.jsonl` — historial de trades
