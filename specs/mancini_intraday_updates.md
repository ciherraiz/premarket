# Intraday Tweet Updates — Interpretación de actualizaciones de Mancini en tiempo real

## Objetivo

Mancini no solo publica el plan matutino: durante la sesion va tuiteando
actualizaciones como "buyers defending 6780", "need to see reclaim of 6800 for
continuation", "plan invalidated below 6760". Hoy el sistema solo parsea el plan
inicial. Este spec describe un segundo parser LLM que interpreta cada tweet nuevo
durante la sesion y emite ajustes que el monitor consume en caliente.

## Problema actual

El scan periodico (cada 10 min) re-parsea TODOS los tweets del dia con Haiku para
extraer niveles. Esto tiene dos limitaciones:

1. **No distingue actualizaciones de plan original** — si Mancini invalida un nivel
   a las 11:00, el scan mezcla el tweet de invalidacion con el plan de las 9:00 y
   Haiku puede devolver niveles contradictorios.
2. **No captura contexto cualitativo** — "buyers defending 6780" no cambia niveles
   pero si la conviccion del trade actual. El parser de niveles lo ignora.
3. **Latencia** — un tweet de invalidacion a las 10:05 puede tardar hasta 10 min
   en procesarse si el scan acaba de correr.

## Solucion: PlanAdjustment pipeline

Nuevo flujo complementario al scan existente:

```
tweet_fetcher  ──>  tweets nuevos (no vistos)
      |
      v
tweet_classifier (Haiku)  ──>  PlanAdjustment | None
      |
      v
monitor.apply_adjustment()  ──>  actualizar plan/detectores/trades en caliente
      |
      v
notifier.notify_adjustment()  ──>  alerta Telegram
```

### Separacion de responsabilidades

| Componente | Que hace | Cuando corre |
|------------|----------|--------------|
| **scan** (existente) | Parsear plan completo del dia | Cada 10 min, hasta que haya plan |
| **intraday updater** (nuevo) | Clasificar tweets individuales post-plan | Cada 60s, integrado en monitor loop |

El scan sigue siendo el mecanismo para cargar el plan inicial. El intraday updater
solo se activa una vez que hay un plan cargado.

## Modelo de datos

### PlanAdjustment

```python
@dataclass
class PlanAdjustment:
    tweet_id: str                    # ID del tweet original
    tweet_text: str                  # texto completo
    timestamp: str                   # ISO timestamp del tweet
    adjustment_type: str             # ver tipos abajo
    details: dict                    # contenido especifico por tipo
    raw_reasoning: str               # explicacion breve del LLM
```

### Tipos de adjustment

```
INVALIDATION    — plan invalidado parcial o totalmente
LEVEL_UPDATE    — nivel clave ajustado (nuevo soporte/resistencia)
TARGET_UPDATE   — targets modificados
BIAS_SHIFT      — cambio de sesgo direccional
CONTEXT_UPDATE  — info cualitativa (defensa de nivel, flujo, etc.)
NO_ACTION       — tweet informativo sin impacto en el plan
```

### Detalle por tipo

**INVALIDATION**
```python
{
    "scope": "full" | "upper" | "lower",    # que parte se invalida
    "condition": "below 6760",               # condicion de invalidacion
    "invalidated_levels": [6780, 6800],      # niveles ya no validos
}
```

**LEVEL_UPDATE**
```python
{
    "side": "upper" | "lower",
    "old_level": 6780,           # puede ser None si es nivel nuevo
    "new_level": 6790,
    "reason": "buyers defending higher",
}
```

**TARGET_UPDATE**
```python
{
    "side": "upper" | "lower",
    "new_targets": [6820, 6840],
    "replace": True,             # True = reemplazar targets, False = anadir
}
```

**BIAS_SHIFT**
```python
{
    "old_bias": "bullish",       # puede ser None
    "new_bias": "bearish",
    "trigger": "lost key support at 6780",
}
```

**CONTEXT_UPDATE**
```python
{
    "context_type": "defense" | "momentum" | "volume" | "general",
    "summary": "buyers defending 6780 aggressively",
    "implied_bias": "bullish" | "bearish" | None,
}
```

## Implementacion

### 1. Tweet tracking — config.py

Mantener registro de tweets ya procesados para no re-clasificarlos:

```python
@dataclass
class IntraDayState:
    processed_tweet_ids: set[str]    # tweets ya clasificados
    adjustments: list[PlanAdjustment]  # historial de ajustes del dia
    last_check: str                   # ISO timestamp del ultimo check
```

Persistencia en `outputs/mancini_intraday.json`.

### 2. Tweet classifier — tweet_classifier.py (nuevo)

Modulo nuevo en `scripts/mancini/tweet_classifier.py`.

**Funcion principal:**

```python
def classify_tweet(
    tweet_text: str,
    tweet_id: str,
    tweet_timestamp: str,
    current_plan: DailyPlan,
) -> PlanAdjustment | None:
```

- Envia a Haiku el tweet + contexto del plan actual
- System prompt especifico para clasificacion (ver abajo)
- Devuelve `PlanAdjustment` siempre (Haiku clasifica como NO_ACTION si es ruido)
- NO hay threshold de confianza — Haiku decide la categoria y el monitor
  notifica todo excepto NO_ACTION

**System prompt (resumen):**

```
Eres un clasificador de tweets de trading intraday de @AdamMancini4.

CONTEXTO DEL PLAN ACTUAL:
- Key level upper: {plan.key_level_upper}
- Key level lower: {plan.key_level_lower}
- Targets upper: {plan.targets_upper}
- Targets lower: {plan.targets_lower}
- Chop zone: {plan.chop_zone}

TWEET A CLASIFICAR:
"{tweet_text}"

Clasifica este tweet en una de estas categorias:
1. INVALIDATION — el plan o parte del plan ya no es valido
2. LEVEL_UPDATE — un nivel clave cambia (nuevo soporte/resistencia)
3. TARGET_UPDATE — los targets se modifican
4. BIAS_SHIFT — cambio de sesgo direccional de la sesion
5. CONTEXT_UPDATE — info cualitativa util pero no cambia niveles
6. NO_ACTION — tweet informativo, pregunta de follower, promo, etc.

Responde en JSON con: adjustment_type, details, reasoning.
Un tweet que CONFIRMA el plan existente es CONTEXT_UPDATE, no LEVEL_UPDATE.
Replies a followers, promos, o tweets sin relacion con el plan son NO_ACTION.
```

**Output format:** JSON parseado a `PlanAdjustment`.

### 3. Monitor integration — monitor.py

Cambios en el loop principal:

```python
class ManciniMonitor:
    def __init__(self):
        # ... existente ...
        self.intraday_state = IntraDayState()

    def run(self):
        while not session_ended:
            price = self.poll_es()
            self.process_tick(price, now)

            # Nuevo: check intraday tweets
            if self.plan:
                self._check_intraday_updates()

            self.save_state()
            sleep(interval)

    def _check_intraday_updates(self):
        """Fetch tweets nuevos, clasificar, aplicar ajustes."""
        tweets = fetch_mancini_tweets(max_tweets=10)
        new_tweets = [
            t for t in tweets
            if t["id"] not in self.intraday_state.processed_tweet_ids
        ]

        for tweet in new_tweets:
            self.intraday_state.processed_tweet_ids.add(tweet["id"])
            adjustment = classify_tweet(
                tweet["text"],
                tweet["id"],
                tweet["created_at"],
                self.plan,
            )
            if adjustment:
                self.intraday_state.adjustments.append(adjustment)
                if adjustment.adjustment_type != "NO_ACTION":
                    self._apply_adjustment(adjustment)
                    notify_adjustment(adjustment)

    def _apply_adjustment(self, adj: PlanAdjustment):
        """Aplicar ajuste al plan y detectores activos."""
        match adj.adjustment_type:
            case "INVALIDATION":
                self._handle_invalidation(adj)
            case "LEVEL_UPDATE":
                self._handle_level_update(adj)
            case "TARGET_UPDATE":
                self._handle_target_update(adj)
            case "BIAS_SHIFT":
                self._handle_bias_shift(adj)
            case "CONTEXT_UPDATE":
                self._handle_context_update(adj)
```

### 4. Handlers de ajustes — monitor.py

**INVALIDATION:**
```python
def _handle_invalidation(self, adj):
    scope = adj.details["scope"]
    if scope == "full":
        # Parar todos los detectores, cerrar trades activos
        for det in self.detectors:
            det.state = State.EXPIRED
        self.trade_manager.close_eod(current_price, now)
        logger.info("Plan invalidado completamente")
    elif scope in ("upper", "lower"):
        # Parar solo el detector del lado invalidado
        det = self._get_detector(scope)
        if det and det.state not in (State.DONE, State.EXPIRED):
            det.state = State.EXPIRED
            # Si hay trade activo en ese lado, cerrar con stop
            if det.state == State.ACTIVE:
                self.trade_manager.close_eod(current_price, now)
```

**LEVEL_UPDATE:**
```python
def _handle_level_update(self, adj):
    side = adj.details["side"]
    new_level = adj.details["new_level"]
    if side == "upper":
        self.plan.key_level_upper = new_level
    else:
        self.plan.key_level_lower = new_level
    # Recrear detector para el nuevo nivel si el anterior estaba en WATCHING
    det = self._get_detector(side)
    if det and det.state == State.WATCHING:
        det.level = new_level
    save_plan(self.plan)
```

**TARGET_UPDATE:**
```python
def _handle_target_update(self, adj):
    side = adj.details["side"]
    new_targets = adj.details["new_targets"]
    replace = adj.details.get("replace", False)
    if side == "upper":
        if replace:
            self.plan.targets_upper = new_targets
        else:
            self.plan.targets_upper = sorted(set(self.plan.targets_upper + new_targets))
    else:
        if replace:
            self.plan.targets_lower = new_targets
        else:
            self.plan.targets_lower = sorted(set(self.plan.targets_lower + new_targets), reverse=True)
    save_plan(self.plan)
```

**BIAS_SHIFT:**
```python
def _handle_bias_shift(self, adj):
    new_bias = adj.details["new_bias"]
    # Actualizar notes del plan para reflejar nuevo sesgo
    self.plan.notes = f"Bias shift: {new_bias} (via intraday update)"
    save_plan(self.plan)
    # Recalcular alignment de trade activo si existe
    active_trade = self.trade_manager.get_active_trade()
    if active_trade:
        new_alignment = self._calc_alignment(active_trade.direction)
        logger.info(f"Alignment recalculado: {active_trade.alignment} -> {new_alignment}")
        # No cerrar automaticamente — solo informar via Telegram
```

**CONTEXT_UPDATE:**
```python
def _handle_context_update(self, adj):
    # No cambia plan ni detectores
    # Solo log + alerta Telegram para awareness del trader
    logger.info(f"Context update: {adj.details['summary']}")
```

### 5. Notificaciones — notifier.py

Nuevo tipo de alerta:

```python
def notify_adjustment(adj: PlanAdjustment):
    """Envia a Telegram el tweet original de Mancini y la conclusion del clasificador.

    El objetivo es que el trader pueda leer exactamente lo que dijo Mancini
    y la interpretacion que el sistema ha hecho, para valorar si el ajuste
    automatico es correcto.
    """
    icons = {
        "INVALIDATION": "🚫",
        "LEVEL_UPDATE": "📐",
        "TARGET_UPDATE": "🎯",
        "BIAS_SHIFT": "🔄",
        "CONTEXT_UPDATE": "💬",
    }
    icon = icons.get(adj.adjustment_type, "📝")

    msg = f"""{icon} Mancini Update

📝 @AdamMancini4:
"{adj.tweet_text}"

🤖 Conclusión: {adj.raw_reasoning}"""

    send_telegram(msg)
```

El mensaje tiene dos bloques claros:
1. **Tweet original completo** — sin truncar, para que el trader lea exactamente
   lo que dijo Mancini.
2. **Conclusion del clasificador** — el `raw_reasoning` de Haiku, que explica
   que tipo de ajuste ha detectado y por que. Esto permite al trader valorar
   si la interpretacion automatica es correcta.

### 6. Logging — logger.py

Nuevo fichero de log:

```python
def append_adjustment(adj: PlanAdjustment):
    """Guardar ajuste en logs/mancini_adjustments.jsonl"""
    entry = {
        "tweet_id": adj.tweet_id,
        "tweet_text": adj.tweet_text,
        "timestamp": adj.timestamp,
        "adjustment_type": adj.adjustment_type,
        "details": adj.details,
        "reasoning": adj.raw_reasoning,
        "applied_at": datetime.now(ZoneInfo("US/Eastern")).isoformat(),
    }
    _append_jsonl("logs/mancini_adjustments.jsonl", entry)
```

## Interaccion con scan existente

El scan periodico y el intraday updater coexisten:

- **scan** sigue corriendo cada 10 min para capturar planes nuevos y merges.
  Solo procesa tweets para extraer niveles completos.
- **intraday updater** corre dentro del monitor loop (cada 60s). Solo clasifica
  tweets individuales que el scan no ha procesado aun para ese ciclo.
- Si el scan actualiza el plan (merge), el monitor recarga desde disco y resetea
  los detectores afectados. Los adjustments previos del intraday updater quedan
  en el historial pero no se re-aplican (el plan del scan es la fuente de verdad
  para niveles base).

### Evitar duplicacion

El intraday updater usa `processed_tweet_ids` para no re-clasificar tweets.
Cuando el scan corre y actualiza el plan, el monitor:
1. Detecta cambio en `mancini_plan.json` (ya implementado)
2. Recarga plan
3. NO resetea `processed_tweet_ids` — los tweets ya clasificados no se
   re-procesan

## Consideraciones de coste

- Haiku es el modelo por defecto (barato y rapido)
- Un tweet = 1 llamada a Haiku (~200 tokens input + 100 output)
- Mancini tuitea ~5-15 veces por sesion
- Coste estimado: < $0.01/dia
- Solo se clasifican tweets nuevos (no re-procesamiento)

## Edge cases

1. **Tweet ambiguo** — Haiku lo clasifica como NO_ACTION o CONTEXT_UPDATE segun
   su criterio. Se loguea con reasoning para revision posterior. No hay filtro
   de confianza — todo lo que no sea NO_ACTION llega a Telegram.

2. **Invalidacion con trade activo** — si hay trade OPEN/PARTIAL cuando llega
   INVALIDATION, NO se cierra automaticamente. Se envia alerta urgente al trader
   para decision manual. Razon: Mancini a veces invalida y luego re-valida.

3. **Multiples updates contradictorios** — si en 5 min llegan "plan invalidated"
   y luego "actually still in play", el segundo tweet genera un nuevo adjustment
   que revierte el primero. El historial queda completo.

4. **Rate limiting de X API** — el fetch ya tiene backoff exponencial. El
   intraday updater reutiliza el mismo fetcher con cache de tweets ya vistos.

5. **Monitor sin plan** — el intraday updater no se activa hasta que haya plan
   cargado (check existente en monitor loop).

6. **Tweet de reply a follower** — Haiku debe clasificar como NO_ACTION. El
   system prompt explicita que replies, promos y preguntas no son actionables.

## CLI

Nuevo subcomando para debug:

```bash
uv run python scripts/mancini/run_mancini.py intraday-status
```

Muestra:
- Tweets procesados hoy
- Adjustments aplicados
- Plan actual post-adjustments

## Tests

- `test_classify_invalidation`: tweet "plan invalidated below X" → INVALIDATION
- `test_classify_level_update`: tweet "buyers defending X" con nivel distinto al plan → LEVEL_UPDATE
- `test_classify_context_only`: tweet "nice move, watching 6800" → CONTEXT_UPDATE
- `test_classify_noise`: tweet reply a follower → NO_ACTION (no se notifica)
- `test_no_action_not_notified`: NO_ACTION no envia Telegram ni aplica cambios
- `test_context_update_notified`: CONTEXT_UPDATE si envia Telegram aunque no cambie plan
- `test_apply_invalidation_full`: plan invalidado → detectores EXPIRED
- `test_apply_invalidation_partial`: solo upper invalidado → lower sigue activo
- `test_apply_level_update_watching`: detector en WATCHING actualiza nivel
- `test_apply_level_update_active`: detector en ACTIVE no cambia nivel (trade en curso)
- `test_apply_target_update_replace`: targets reemplazados
- `test_apply_target_update_append`: targets anadidos sin duplicados
- `test_apply_bias_shift_with_active_trade`: recalcula alignment, alerta sin cerrar
- `test_processed_ids_persist`: tweets no se re-clasifican tras restart
- `test_scan_reload_keeps_processed_ids`: scan actualiza plan, ids se mantienen
- `test_intraday_not_active_without_plan`: sin plan → no clasifica
- `test_adjustment_logged_to_jsonl`: cada adjustment se persiste en log
