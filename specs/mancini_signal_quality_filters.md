# Signal Quality Filters — Reducción de Falsos Positivos en Failed Breakdown

## Objetivo

Reducir los falsos positivos en la detección de Failed Breakdown añadiendo métricas
de calidad de señal al detector y enriqueciéndolas al execution gate. El objetivo
no es elevar el umbral de confirmación temporal (ya son 120s), sino caracterizar
**cómo** se produce esa confirmación y descartar las que ocurren de forma débil.

---

## Problema actual

La confirmación se basa únicamente en tiempo: precio sobre `nivel + 1.5 pts`
durante 120 segundos continuos. Esto es necesario pero no suficiente porque no
distingue entre:

- **Señal fuerte**: precio sube agresivamente +5/+7 pts sobre el nivel tras la
  recuperación, no mira atrás, con convicción visible.
- **Señal débil**: precio se arrastra lentamente justo por encima del nivel durante
  120s, duda constantemente, oscilando entre el nivel y el umbral de aceptación.

Ambas generan la misma confirmación hoy. La segunda es frecuentemente un falso
positivo que revierte.

**Limitación estructural**: con `POLL_INTERVAL_S = 60`, una ventana de 120s
produce solo ~2 observaciones de precio. Es imposible calcular velocidad ni contar
retests con esa resolución.

---

## Filtros propuestos — análisis

| ID  | Filtro                    | Tipo         | Impacto | Esfuerzo | Prerequisito |
|-----|---------------------------|--------------|---------|----------|--------------|
| F1  | Reducir poll a 15s        | Infraestructura | Alto   | Mínimo   | —            |
| F2  | Velocidad de recuperación | Métrica calidad | Alto  | Bajo     | F1           |
| F3  | Retests durante aceptación | Métrica calidad | Alto  | Mínimo   | F1           |
| F4  | Precio máximo en ventana  | Métrica calidad | Medio  | Mínimo   | F1           |
| F5  | Filtro horario            | Filtro duro  | Medio   | Mínimo   | —            |
| F6  | Profundidad del breakdown | Métrica calidad | Bajo-Medio | Mínimo | — (ya disponible) |
| F7  | VIX snapshot en señal     | Dato externo | Medio   | Medio    | —            |

### F1 — Reducir poll interval a 15s

**Razón**: fundamento de todo lo demás. Con 60s solo ves 2 ticks en 120s.
Con 15s ves 8 ticks. Suficiente para medir velocidad y contar pausas.

**Riesgo**: más llamadas API a TastyTrade. El endpoint REST de quotes es ligero;
60 llamadas/hora → 240 llamadas/hora. Dentro de los límites del SDK.

**Implementación**: cambiar `POLL_INTERVAL_S = 60` a `POLL_INTERVAL_S = 15`
en `monitor.py`.

### F2 — Velocidad de recuperación

**Razón**: una recuperación genuina acelera. Un falso positivo se arrastra.
La velocidad media durante la ventana de aceptación discrimina muy bien.

**Métrica**: `recovery_velocity = (precio_max_en_ventana - nivel) / elapsed_seconds * 60`
(puntos por minuto sobre el nivel). Una señal fuerte a los 2 minutos debería
tener precio +4/+5 pts sobre el nivel, no +1.6 pts.

**Implementación**: el detector acumula `acceptance_max_price` durante RECOVERY.
Al emitir SIGNAL, calcula y añade `recovery_velocity_pts_min` a `details`.

**Umbral orientativo** (calibrar con datos reales):
- `>= 2.0 pts/min` → señal fuerte
- `1.0–2.0 pts/min` → señal media (consultar gate)
- `< 1.0 pts/min` → señal débil (gate escala a confirmación manual)

### F3 — Retests durante aceptación

**Razón**: si el precio intenta volver al nivel repetidamente durante los 120s,
hay vendedores activos. Cada "pausa" del reloj (precio cae bajo ACCEPTANCE_PTS)
es una señal de debilidad.

**Métrica**: `acceptance_pauses` — número de veces que `acceptance_since` se
pone a `None` durante RECOVERY (el reloj se pausa porque el precio cae bajo el
umbral pero no suficiente para volver a BREAKDOWN).

- `0 pausas` → aceptación limpia, señal fuerte
- `1 pausa` → aceptación con un tropiezo, aceptable
- `2+ pausas` → indecisión evidente, señal débil

**Filtro duro opcional**: si `acceptance_pauses >= 3`, resetear a WATCHING en
lugar de emitir SIGNAL. Tres retests al nivel durante la ventana = trampa no
completamente resuelta.

### F4 — Precio máximo en ventana de aceptación

**Razón**: precio que llega +5 pts sobre el nivel durante los 120s (aunque
luego retroceda al umbral) indica más convicción que uno que nunca supera +2 pts.

**Métrica**: `acceptance_max_price` — ya necesaria para F2. Se añade directamente
a `details` del SIGNAL como `acceptance_max_above_level`.

### F5 — Filtro horario (time of day)

**Razón**: los failed breakdowns de Mancini son más fiables en las primeras
horas de sesión. Después de las 14:00 ET el volumen cae, los niveles se
respetan menos y las señales tienen menos recorrido (aunque el gate ya evalúa
`minutes_remaining`).

**Implementación**: en `monitor.py`, al recibir SIGNAL añadir `time_quality`
a los detalles antes de pasarlo al gate:

| Hora ET         | `time_quality` | Comportamiento recomendado         |
|-----------------|----------------|-------------------------------------|
| 09:30 – 12:30   | `"prime"`      | Ejecutar si gate aprueba            |
| 12:30 – 14:00   | `"extended"`   | Ejecutar con gate normal            |
| 14:00 – 15:00   | `"late"`       | Gate debe escalar a manual confirm  |
| 15:00+          | Ya cubierto por gate (`minutes_remaining < 60`) |

**Nota**: no bloquear la señal antes de las 09:30 ET — Mancini opera desde
apertura europea (03:00 ET) y los niveles del pre-market también generan setups.

### F6 — Profundidad del breakdown

**Razón**: paradójicamente, los breakdowns más profundos que recuperan son
señales más fiables (más vendedores atrapados). Un breakdown de solo 2-3 pts
puede ser ruido de mercado, no una trampa real.

**Disponibilidad**: `breakdown_low` ya se rastrea. La profundidad
(`nivel - breakdown_low`) ya aparece en `details` del BREAKDOWN pero no se
propaga al SIGNAL.

**Implementación**: añadir `breakdown_depth_pts` a `details` del SIGNAL
tomándolo de `self.breakdown_low`.

**Orientativo**:
- `2–3 pts` → señal débil (puede ser ruido)
- `4–8 pts` → zona óptima
- `9–11 pts` → señal fuerte (pero cercana al límite MAX_BREAK_PTS)

### F7 — VIX snapshot en señal

**Razón**: si el VIX está subiendo mientras el precio de /ES recupera el nivel,
hay divergencia. El mercado de opciones está comprando protección mientras el
spot sube → la recuperación puede ser artificial.

**Datos disponibles**: `tastytrade_client.py` ya tiene `get_equity_quote()`.
El índice `$VIX.X` es consultable via API REST de TastyTrade.

**Implementación**: en `monitor.py`, al recibir SIGNAL, hacer una llamada
adicional para obtener el VIX actual y añadirlo como `vix_at_signal` a los
detalles del evento.

**Comparación**: contrastar con `vix_premarket` del `DailyPlan` (si disponible)
o con la primera lectura del día.

**Complejidad adicional**: requiere guardar un `vix_baseline` al inicio de la
sesión para tener referencia de comparación. No es complicado pero añade estado.

---

## Priorización y fases de implementación

### Criterio de priorización

El objetivo es eliminar falsos positivos con el mínimo riesgo de eliminar
señales válidas. Empezar por los cambios más baratos en información nueva
(F1: frecuencia) y más directos en impacto (F2 velocidad + F3 retests), y
dejar para fases posteriores los que requieren datos externos (F7 VIX).

### Fase 1 — Fundación (prerequisito)

**F1: Reducir poll interval a 15 segundos**

Un cambio de una línea, sin efectos secundarios en la lógica del detector.
Multiplica por 4 la resolución de la señal.

### Fase 2 — Métricas de calidad en el detector

**F2 + F3 + F4 + F6: Enriquecer StateTransition.details del SIGNAL**

Cambios puramente aditivos al detector. No modifican la lógica de transición
de estados, solo acumulan datos durante RECOVERY y los exponen en el SIGNAL.

Campos nuevos en `FailedBreakdownDetector`:
- `acceptance_pauses: int = 0` — contador de retests
- `acceptance_max_price: float | None = None` — precio máximo en ventana

Campos nuevos en `StateTransition.details` al emitir SIGNAL:
- `breakdown_depth_pts: float` — profundidad del breakdown (ya calculable)
- `acceptance_pauses: int` — retests durante aceptación
- `acceptance_max_above_level: float` — máximo sobre nivel durante aceptación
- `recovery_velocity_pts_min: float` — velocidad media de recuperación

**Filtro duro (opcional, conservador)**:
- Si `acceptance_pauses >= 3` → no emitir SIGNAL, volver a WATCHING con `reason: "excessive_retests"`

### Fase 3 — Integración con el Execution Gate

**F5 (time_quality) + F2/F3/F4/F6 (quality metrics): Actualizar execution_gate.py**

Pasar las nuevas métricas al gate y actualizar el system prompt para que las evalúe.

El gate ya existe y evalúa contexto. Solo hay que:
1. Añadir los nuevos campos a la signatura de `evaluate_signal()`
2. Actualizar el system prompt para incluirlos como criterios adicionales

### Fase 4 — VIX snapshot (standalone, baja urgencia)

**F7**: requiere persistir un `vix_baseline` al arranque del monitor y consultar
el VIX en el momento de la señal. Útil pero menor impacto marginal respecto a F2/F3.

---

## Implementación detallada — Fase 1

### `scripts/mancini/monitor.py`

```python
# Antes
POLL_INTERVAL_S = 60

# Después
POLL_INTERVAL_S = 15
```

Sin más cambios. El resto de la lógica es agnóstica al intervalo de polling.

---

## Implementación detallada — Fase 2

### `scripts/mancini/detector.py`

#### Nuevas constantes

```python
MAX_ACCEPTANCE_PAUSES = 3  # Más retests que esto → señal inválida, volver a WATCHING
```

#### Campos nuevos en `FailedBreakdownDetector`

```python
@dataclass
class FailedBreakdownDetector:
    level: float
    side: str
    state: State = State.WATCHING
    breakdown_low: float | None = None
    acceptance_since: str | None = None
    signal_price: float | None = None
    signal_timestamp: str | None = None
    # ── NUEVOS ──────────────────────────────────────────
    acceptance_pauses: int = 0                   # retests durante ventana aceptación
    acceptance_max_price: float | None = None    # precio máximo en ventana aceptación
```

#### `_process_recovery` modificado

```python
def _process_recovery(self, price: float, timestamp: str,
                      prev_state: State) -> StateTransition | None:
    # Si el precio vuelve a caer bajo el nivel → volver a BREAKDOWN
    if price < self.level - MIN_BREAK_PTS:
        self.state = State.BREAKDOWN
        self.acceptance_since = None
        self.acceptance_pauses = 0          # resetear contador
        self.acceptance_max_price = None    # resetear máximo
        if self.breakdown_low is None or price < self.breakdown_low:
            self.breakdown_low = price
        return StateTransition(
            from_state=prev_state,
            to_state=State.BREAKDOWN,
            level=self.level,
            price=price,
            timestamp=timestamp,
            details={"reason": "failed_recovery"},
        )

    if price >= self.level + ACCEPTANCE_PTS:
        # Actualizar precio máximo alcanzado
        if self.acceptance_max_price is None or price > self.acceptance_max_price:
            self.acceptance_max_price = price

        # Reiniciar reloj si se había pausado
        if self.acceptance_since is None:
            self.acceptance_since = timestamp

        elapsed = _elapsed_seconds(self.acceptance_since, timestamp)

        if elapsed >= ACCEPTANCE_SECONDS:
            # Calcular métricas de calidad
            depth_pts = round(self.level - (self.breakdown_low or self.level), 2)
            max_above = round((self.acceptance_max_price or price) - self.level, 2)
            velocity = round(max_above / (elapsed / 60), 2) if elapsed > 0 else 0.0

            self.state = State.SIGNAL
            self.signal_price = price
            self.signal_timestamp = timestamp
            return StateTransition(
                from_state=prev_state,
                to_state=State.SIGNAL,
                level=self.level,
                price=price,
                timestamp=timestamp,
                details={
                    "breakdown_low": self.breakdown_low,
                    "elapsed_seconds": round(elapsed, 1),
                    # ── NUEVAS MÉTRICAS DE CALIDAD ──
                    "breakdown_depth_pts": depth_pts,
                    "acceptance_pauses": self.acceptance_pauses,
                    "acceptance_max_above_level": max_above,
                    "recovery_velocity_pts_min": velocity,
                },
            )
    else:
        # Entre nivel y umbral: pausar reloj y contar retest
        if self.acceptance_since is not None:
            self.acceptance_pauses += 1

            # Filtro duro: demasiados retests → señal inválida
            if self.acceptance_pauses >= MAX_ACCEPTANCE_PAUSES:
                self.state = State.WATCHING
                self.breakdown_low = None
                self.acceptance_since = None
                self.acceptance_pauses = 0
                self.acceptance_max_price = None
                return StateTransition(
                    from_state=prev_state,
                    to_state=State.WATCHING,
                    level=self.level,
                    price=price,
                    timestamp=timestamp,
                    details={
                        "reason": "excessive_retests",
                        "pauses": MAX_ACCEPTANCE_PAUSES,
                    },
                )

        self.acceptance_since = None

    return None
```

#### `reset()` actualizado

```python
def reset(self) -> None:
    self.state = State.WATCHING
    self.breakdown_low = None
    self.acceptance_since = None
    self.signal_price = None
    self.signal_timestamp = None
    self.acceptance_pauses = 0
    self.acceptance_max_price = None
```

#### `to_dict()` / `from_dict()` actualizados

```python
def to_dict(self) -> dict:
    return {
        "level": self.level,
        "side": self.side,
        "state": self.state.value,
        "breakdown_low": self.breakdown_low,
        "acceptance_since": self.acceptance_since,
        "signal_price": self.signal_price,
        "signal_timestamp": self.signal_timestamp,
        "acceptance_pauses": self.acceptance_pauses,
        "acceptance_max_price": self.acceptance_max_price,
    }

@classmethod
def from_dict(cls, d: dict) -> FailedBreakdownDetector:
    return cls(
        level=d["level"],
        side=d["side"],
        state=State(d["state"]),
        breakdown_low=d.get("breakdown_low"),
        acceptance_since=d.get("acceptance_since"),
        signal_price=d.get("signal_price"),
        signal_timestamp=d.get("signal_timestamp"),
        acceptance_pauses=d.get("acceptance_pauses", 0),
        acceptance_max_price=d.get("acceptance_max_price"),
    )
```

---

## Implementación detallada — Fase 3

### `scripts/mancini/execution_gate.py`

#### Nuevos parámetros en `evaluate_signal()`

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
    # ── NUEVOS: métricas de calidad de señal ──
    breakdown_depth_pts: float = 0.0,
    acceptance_pauses: int = 0,
    acceptance_max_above_level: float = 0.0,
    recovery_velocity_pts_min: float = 0.0,
    time_quality: str = "prime",             # "prime" | "extended" | "late"
) -> GateDecision:
```

#### Actualización del system prompt

Añadir sección nueva al prompt existente:

```
## Métricas de calidad de la señal técnica

Estas métricas describen CÓMO se produjo la confirmación, no si ocurrió.
Úsalas para evaluar la convicción de la señal:

- Profundidad del breakdown: {breakdown_depth_pts} pts
  (óptimo: 4-8 pts; < 3 = posible ruido; 9-11 = fuerte)
- Retests durante aceptación: {acceptance_pauses}
  (0 = limpio; 1 = aceptable; 2+ = debilidad)
- Precio máximo sobre nivel durante aceptación: {acceptance_max_above_level} pts
  (> 3 pts = convicción; < 1.5 pts = precio apenas superó el umbral)
- Velocidad de recuperación: {recovery_velocity_pts_min} pts/min
  (> 2.0 = agresiva; < 1.0 = lenta, posible trampa)
- Calidad horaria: {time_quality}
  (prime = señal prioritaria; extended = normal; late = requiere confirmación manual)

Factores de RIESGO adicionales por métricas de calidad:
- Profundidad < 3 pts (posible ruido, no trampa real)
- 2 o más retests (indecisión prolongada en el nivel)
- Velocidad < 1.0 pts/min (recuperación anémica)
- Precio máximo < 2 pts sobre nivel (precio nunca mostró convicción)
- time_quality = "late" (poca ventana horaria)

Si hay 2 o más factores de riesgo de calidad activos simultáneamente,
establece execute=false aunque el resto del contexto sea favorable.
```

#### Integración en `monitor.py` al manejar SIGNAL

```python
elif t.to_state == State.SIGNAL:
    # ... código existente ...

    # ── Extraer métricas de calidad del SIGNAL ──
    breakdown_depth_pts = t.details.get("breakdown_depth_pts", 0.0)
    acceptance_pauses   = t.details.get("acceptance_pauses", 0)
    max_above_level     = t.details.get("acceptance_max_above_level", 0.0)
    velocity            = t.details.get("recovery_velocity_pts_min", 0.0)

    # ── Calcular time_quality ──
    hour_et = _now_et().hour
    if hour_et < 12 or (hour_et == 12 and _now_et().minute < 30):
        time_quality = "prime"
    elif hour_et < 14:
        time_quality = "extended"
    else:
        time_quality = "late"

    decision = evaluate_signal(
        # ... parámetros existentes ...
        breakdown_depth_pts=breakdown_depth_pts,
        acceptance_pauses=acceptance_pauses,
        acceptance_max_above_level=max_above_level,
        recovery_velocity_pts_min=velocity,
        time_quality=time_quality,
    )
```

---

## Implementación detallada — Fase 4 (VIX snapshot)

### Estado nuevo en `ManciniMonitor`

```python
class ManciniMonitor:
    def __init__(self, ...):
        ...
        self.vix_baseline: float | None = None  # primer VIX de la sesión
```

### Captura del baseline al inicio

En el primer poll del día (o al arrancar el monitor), guardar el VIX:

```python
def _capture_vix_baseline(self) -> None:
    """Captura el VIX al inicio de sesión como referencia."""
    try:
        quote = self.client.get_equity_quote("$VIX.X")
        self.vix_baseline = quote.get("last") or quote.get("mark")
        _log(f"VIX baseline capturado: {self.vix_baseline}")
    except Exception as e:
        _log(f"No se pudo capturar VIX baseline: {e}")
```

### En el SIGNAL handler

```python
# Obtener VIX actual
vix_now = None
try:
    vix_quote = self.client.get_equity_quote("$VIX.X")
    vix_now = vix_quote.get("last") or vix_quote.get("mark")
except Exception:
    pass

# Calcular delta VIX si tenemos baseline
vix_delta = None
if vix_now and self.vix_baseline:
    vix_delta = round(vix_now - self.vix_baseline, 2)
    # VIX subiendo mientras /ES recupera = divergencia bajista para LONG
    # VIX bajando mientras /ES recupera = confirmación adicional

# Pasar al gate como parte de details o como parámetro adicional
```

---

## Calibración posterior

Todas las métricas de calidad se registran en el log de señales (`logs/`).
Después de acumular 20-30 señales reales, comparar:
- Métricas de señales que resultaron en trades ganadores
- Métricas de señales que resultaron en stops

Esto permitirá afinar los umbrales de:
- `recovery_velocity_pts_min` (actualmente orientativo: 1.0/2.0)
- `acceptance_max_above_level` (actualmente orientativo: 1.5/3.0)
- `MAX_ACCEPTANCE_PAUSES` (actualmente: 3)

---

## Tests

### `tests/test_mancini_detector.py` — añadir

**Nuevas métricas en SIGNAL details**:
- `test_signal_includes_quality_metrics`: SIGNAL emitido contiene `breakdown_depth_pts`,
  `acceptance_pauses`, `acceptance_max_above_level`, `recovery_velocity_pts_min`
- `test_acceptance_pauses_increments_on_dip`: precio cae bajo ACCEPTANCE_PTS durante
  RECOVERY → `acceptance_pauses` sube a 1, reloj se resetea
- `test_acceptance_pauses_not_incremented_below_level`: precio cae bajo el nivel
  (→ BREAKDOWN) NO incrementa `acceptance_pauses` (se resetea)
- `test_max_price_tracked_during_acceptance`: precio sube a nivel+5, luego vuelve
  a nivel+2, SIGNAL incluye `acceptance_max_above_level = 5`
- `test_velocity_calculated_correctly`: recovery en 60s con max +4 pts →
  velocity = 4 pts / (60/60 min) = 4.0 pts/min

**Filtro duro retests**:
- `test_excessive_retests_resets_to_watching`: 3 pausas durante RECOVERY →
  transición a WATCHING con `reason: "excessive_retests"`, no SIGNAL
- `test_two_pauses_still_emits_signal`: 2 pausas son aceptables, SIGNAL emitido
- `test_reset_clears_pause_counter`: `reset()` pone `acceptance_pauses = 0`

**Persistencia**:
- `test_to_dict_includes_new_fields`: `acceptance_pauses` y `acceptance_max_price`
  en el dict serializado
- `test_from_dict_with_missing_new_fields`: diccionarios viejos (sin los campos
  nuevos) se deserializan con valores por defecto `0` y `None`

**Poll interval menor**:
- `test_signal_with_15s_polls`: simulación de 8 ticks a 15s cada uno en RECOVERY
  → SIGNAL tras 120s, métricas calculadas correctamente

### `tests/test_mancini_execution_gate.py` — añadir

- `test_gate_uses_velocity_as_risk_factor`: velocity=0.5 → en `risk_factors`
- `test_gate_uses_retests_as_risk_factor`: acceptance_pauses=2 → en `risk_factors`
- `test_gate_escalates_late_time_quality`: time_quality="late" → execute=false
- `test_gate_two_quality_risk_factors_escalates`: velocity baja + retests altos
  → execute=false aunque contexto temporal sea favorable

### `tests/test_mancini_monitor_quality.py` — nuevo

- `test_monitor_passes_quality_metrics_to_gate`: al recibir SIGNAL con details,
  monitor extrae métricas y las pasa correctamente a `evaluate_signal()`
- `test_monitor_calculates_time_quality_prime`: hora 10:00 ET → `time_quality="prime"`
- `test_monitor_calculates_time_quality_late`: hora 14:30 ET → `time_quality="late"`

---

## Módulos afectados

| Módulo | Cambios |
|--------|---------|
| `scripts/mancini/monitor.py` | `POLL_INTERVAL_S = 15`; extracción de métricas del SIGNAL; cálculo de `time_quality`; VIX baseline (Fase 4) |
| `scripts/mancini/detector.py` | Campos `acceptance_pauses`, `acceptance_max_price`; lógica en `_process_recovery`; filtro duro `MAX_ACCEPTANCE_PAUSES`; métricas en SIGNAL details |
| `scripts/mancini/execution_gate.py` | Nuevos parámetros; system prompt ampliado con sección de métricas de calidad |
| `tests/test_mancini_detector.py` | Tests nuevos (ver sección Tests) |
| `tests/test_mancini_execution_gate.py` | Tests nuevos (ver sección Tests) |
| `tests/test_mancini_monitor_quality.py` | Nuevo archivo de tests |

---

## Resumen de fases

| Fase | Qué incluye | Valor inmediato |
|------|-------------|-----------------|
| **1** | Poll 15s | Fundación: más resolución para todo lo demás |
| **2** | Métricas en detector + filtro duro retests | El detector ya descarta señales de mala calidad |
| **3** | Gate integra métricas | El gate contextualiza señales débiles y escala a confirmación manual |
| **4** | VIX snapshot | Capa adicional de confirmación (baja urgencia) |
