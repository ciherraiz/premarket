"""
Monitor de precio /ES para la estrategia Mancini.

Proceso de larga duración que:
1. Lee el plan del día (outputs/mancini_plan.json)
2. Polls /ES cada 60s via TastyTradeClient
3. Alimenta detectores Failed Breakdown
4. Gestiona trades (entry, stops, targets)
5. Envía alertas Telegram en cada transición
6. Se auto-finaliza al llegar a SESSION_END_ET

Estado persistido en outputs/mancini_state.json para sobrevivir reinicios.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.mancini.config import (
    DailyPlan, PlanAdjustment, IntraDayState,
    load_plan, load_weekly, save_plan, save_intraday_state, load_intraday_state,
    PLAN_PATH, WEEKLY_PLAN_PATH, INTRADAY_STATE_PATH,
)
from scripts.mancini.detector import (
    FailedBreakdownDetector,
    State,
    StateTransition,
    save_detectors,
    load_detectors,
    STATE_PATH,
)
from scripts.mancini.trade_manager import TradeManager, TradeStatus, calc_stop
from scripts.mancini.logger import append_trade, append_adjustment, append_gate_decision
from scripts.mancini import notifier

ET = ZoneInfo("America/New_York")

# ── Constantes ──────────────────────────────────────────────────────
POLL_INTERVAL_S = 60
SESSION_START_HOUR = 7   # 07:00 ET (13:00 CEST)
SESSION_END_HOUR = 16    # 16:00 ET (22:00 CEST) — cierre mercado regular


def _now_et() -> datetime:
    return datetime.now(ET)


def _log(msg: str) -> None:
    ts = _now_et().strftime("%H:%M:%S ET")
    print(f"[mancini {ts}] {msg}", flush=True)


class ManciniMonitor:
    """Orquesta polling, detección y gestión de trades."""

    def __init__(self, client=None, poll_interval: int = POLL_INTERVAL_S,
                 plan_path: Path = PLAN_PATH, state_path: Path = STATE_PATH,
                 weekly_path: Path = WEEKLY_PLAN_PATH,
                 intraday_path: Path = INTRADAY_STATE_PATH,
                 session_start: int = SESSION_START_HOUR,
                 session_end: int = SESSION_END_HOUR,
                 order_executor=None,
                 gate_enabled: bool = True,
                 es_symbol: str = ""):
        self.client = client
        self.poll_interval = poll_interval
        self.plan_path = plan_path
        self.state_path = state_path
        self.weekly_path = weekly_path
        self.intraday_path = intraday_path
        self.session_start = session_start
        self.session_end = session_end
        self.order_executor = order_executor  # None = sin órdenes TastyTrade
        self.gate_enabled = gate_enabled  # False = ejecutar sin consultar LLM
        self.es_symbol = es_symbol  # símbolo /ES resuelto, ej. "/ESM6:XCME"
        self.plan: DailyPlan | None = None
        self.weekly: DailyPlan | None = None
        self.detectors: list[FailedBreakdownDetector] = []
        self.trade_manager = TradeManager()
        self.intraday_state = IntraDayState()
        self._plan_mtime: float = 0

    def load_state(self) -> None:
        """Carga plan, weekly y detectores desde disco."""
        self.plan = load_plan(self.plan_path)
        self.weekly = load_weekly(self.weekly_path)

        # Validar que el plan corresponde a hoy (ET)
        if self.plan:
            today_et = _now_et().strftime("%Y-%m-%d")
            if self.plan.fecha != today_et:
                _log(f"Plan descartado: fecha {self.plan.fecha} != hoy {today_et}")
                self.plan = None

        if self.plan:
            self.trade_manager.fecha = self.plan.fecha
            self._plan_mtime = self.plan_path.stat().st_mtime if self.plan_path.exists() else 0

        self.intraday_state = load_intraday_state(self.intraday_path)

        self.detectors = load_detectors(self.state_path)
        if not self.detectors and self.plan:
            self._init_detectors()

    def _init_detectors(self) -> None:
        """Crea detectores a partir del plan actual."""
        self.detectors = []
        if self.plan.key_level_upper is not None:
            self.detectors.append(
                FailedBreakdownDetector(level=self.plan.key_level_upper, side="upper")
            )
        if self.plan.key_level_lower is not None:
            self.detectors.append(
                FailedBreakdownDetector(level=self.plan.key_level_lower, side="lower")
            )

    def calc_weekly_bias(self) -> str:
        """Calcula sesgo semanal: BULLISH, BEARISH o NEUTRAL."""
        if not self.weekly:
            return "NEUTRAL"

        notes = (self.weekly.notes or "").lower()
        if "alcista" in notes or "bullish" in notes:
            return "BULLISH"
        if "bajista" in notes or "bearish" in notes:
            return "BEARISH"

        # Fallback: inferir del balance de targets
        has_up = bool(self.weekly.targets_upper)
        has_down = bool(self.weekly.targets_lower)
        if has_up and not has_down:
            return "BULLISH"
        if has_down and not has_up:
            return "BEARISH"

        return "NEUTRAL"

    def calc_alignment(self, direction: str) -> str:
        """Calcula alignment de un trade con el sesgo semanal."""
        bias = self.calc_weekly_bias()
        if bias == "NEUTRAL":
            return "NEUTRAL"
        if (bias == "BULLISH" and direction == "LONG") or \
           (bias == "BEARISH" and direction == "SHORT"):
            return "ALIGNED"
        return "MISALIGNED"

    def save_state(self) -> None:
        """Persiste detectores y estado intraday en disco."""
        save_detectors(self.detectors, self.state_path)
        save_intraday_state(self.intraday_state, self.intraday_path)

    def _scan_for_plan(self) -> bool:
        """Busca tweets de Mancini y extrae el plan del día.

        Integra la lógica del scan dentro del monitor: fetch tweets,
        parsear con Haiku, guardar plan. Reintenta cada poll_interval
        hasta session_end.

        Returns:
            True si se encontró plan, False si se agotó el tiempo.
        """
        from scripts.mancini.tweet_fetcher import fetch_mancini_tweets
        from scripts.mancini.tweet_parser import parse_tweets_to_plan
        from scripts.mancini.logger import append_scan_result

        today_et = _now_et().strftime("%Y-%m-%d")
        _log("Buscando plan de hoy en tweets de Mancini...")

        while True:
            now = _now_et()
            if now.hour >= self.session_end:
                _log("Fin de sesión sin plan — cerrando monitor")
                return False

            # 1. Intentar cargar plan existente de disco (otro proceso pudo crearlo)
            self.load_state()
            if self.plan:
                _log("Plan de hoy encontrado en disco")
                self._log_plan_info()
                return True

            # 2. Fetch tweets y parsear
            try:
                tweets = fetch_mancini_tweets(max_tweets=20)
            except Exception as e:
                _log(f"Error fetching tweets: {e}")
                time.sleep(self.poll_interval)
                continue

            if not tweets:
                _log("Sin tweets de Mancini hoy — reintentando...")
                time.sleep(self.poll_interval)
                continue

            _log(f"Encontrados {len(tweets)} tweets, parseando con Haiku...")

            try:
                plan = parse_tweets_to_plan(tweets, today_et)
            except Exception as e:
                _log(f"Error parseando tweets: {e}")
                append_scan_result("parse_error", len(tweets), False, str(e), today_et)
                time.sleep(self.poll_interval)
                continue

            if plan is None:
                _log("Haiku no encontró plan nuevo — reintentando...")
                append_scan_result("no_plan", len(tweets), False, "no plan", today_et)
                time.sleep(self.poll_interval)
                continue

            # 3. Merge con plan existente o guardar nuevo
            existing = load_plan(self.plan_path)
            if existing and existing.fecha == today_et:
                for tweet_text in plan.raw_tweets:
                    existing.merge_update(
                        new_targets_upper=plan.targets_upper,
                        new_targets_lower=plan.targets_lower,
                        new_tweet=tweet_text,
                    )
                if plan.chop_zone and not existing.chop_zone:
                    existing.chop_zone = plan.chop_zone
                save_plan(existing, self.plan_path)
                plan = existing
            else:
                save_plan(plan, self.plan_path)

            self.plan = plan
            self.trade_manager.fecha = plan.fecha
            self._plan_mtime = self.plan_path.stat().st_mtime if self.plan_path.exists() else 0
            self._init_detectors()

            # Marcar tweets como procesados (evitar que el clasificador los re-procese)
            for t in tweets:
                self.intraday_state.processed_tweet_ids.add(t["id"])
            self.save_state()

            append_scan_result("success", len(tweets), True, "", today_et)
            _log("Plan creado!")
            self._log_plan_info()
            notifier.notify_plan_loaded(
                plan.to_dict(),
                session_start=self.session_start,
                session_end=self.session_end,
            )
            return True

    def poll_es(self) -> float | None:
        """Obtiene precio actual de /ES. Retorna None si falla."""
        if self.client is None:
            return None
        try:
            quote = self.client.get_future_quote("/ES")
            if quote.get("status") != "OK":
                _log(f"Quote status: {quote.get('status')}")
                return None
            price = quote.get("last", 0)
            if price <= 0:
                price = quote.get("mark", 0)
            return price if price > 0 else None
        except Exception as e:
            _log(f"Error polling /ES: {e}")
            return None

    def process_tick(self, price: float, timestamp: str | None = None) -> list[dict]:
        """
        Procesa un tick de precio. Retorna lista de eventos generados.

        Este método es el núcleo del monitor y puede usarse en tests
        sin necesidad de TastyTradeClient.
        """
        ts = timestamp or datetime.now(timezone.utc).isoformat()
        events = []

        # 1. Alimentar detectores
        for detector in self.detectors:
            transition = detector.process_tick(price, ts)
            if transition:
                events.append(self._handle_transition(transition, price, ts))

        # 2. Gestionar trade activo
        trade_events = self.trade_manager.process_tick(price, ts)
        for te in trade_events:
            events.append(te)
            self._handle_trade_event(te)

        return events

    def _handle_transition(self, t: StateTransition, price: float,
                           ts: str) -> dict:
        """Maneja una transición de estado del detector."""
        event = {
            "type": f"DETECTOR_{t.to_state.value}",
            "from": t.from_state.value,
            "level": t.level,
            "price": price,
            "timestamp": ts,
            "details": t.details,
        }

        if t.to_state == State.BREAKDOWN:
            _log(f"BREAKDOWN en {t.level} — ES={price} ({t.details.get('depth_pts', 0):+.1f} pts)")
            notifier.notify_breakdown(t.level, price, t.details.get("depth_pts", 0))

        elif t.to_state == State.SIGNAL:
            _log(f"SIGNAL en {t.level} — ES={price}")
            breakdown_low = t.details.get("breakdown_low", price)
            direction = "LONG"
            alignment = self.calc_alignment(direction)
            targets = self._get_targets_for_level(t.level, alignment)

            if alignment == "MISALIGNED":
                _log(f"⚠️ Trade MISALIGNED (contra sesgo semanal) — solo T1")

            # ── Execution Gate ──
            stop_price = calc_stop(direction, price, breakdown_low)
            should_execute, gate_decision = self._evaluate_gate(
                price, t.level, breakdown_low, direction,
                stop_price, targets, alignment, ts,
            )

            if not should_execute:
                _log(f"Trade descartado por gate/trader")
                notifier.notify_trade_rejected(gate_decision)
                return event

            # Proponer trade
            trade = self.trade_manager.open_trade(
                direction=direction,
                entry_price=price,
                breakdown_low=breakdown_low,
                targets=targets,
                timestamp=ts,
                alignment=alignment,
            )
            if trade:
                # Guardar decisión del gate en el trade
                if gate_decision:
                    trade.gate_decision = gate_decision.to_dict()
                    trade.execution_mode = "auto" if gate_decision.execute else "manual_confirm"

                # Marcar detector como activo
                for d in self.detectors:
                    if d.level == t.level and d.state == State.SIGNAL:
                        d.mark_active()

                # ── Lanzar orden en TastyTrade ──
                self._place_trade_orders(trade, direction)

                notifier.notify_signal(
                    level=t.level, price=price, entry=trade.entry_price,
                    stop=trade.stop_price, targets=trade.targets,
                    breakdown_low=breakdown_low,
                    alignment=alignment,
                )
                _log(f"Trade abierto: {direction} {trade.entry_price} stop={trade.stop_price} [{alignment}]")
            else:
                _log("No se pudo abrir trade (límite diario o trade activo)")

        elif t.to_state == State.WATCHING and t.from_state == State.BREAKDOWN:
            _log(f"Break demasiado profundo en {t.level} — volver a WATCHING")

        return event

    def _handle_trade_event(self, event: dict) -> None:
        """Maneja un evento del trade manager."""
        if event["type"] == "TARGET_HIT":
            idx = event["target_index"]
            _log(
                f"Target {idx + 1} alcanzado: {event['target_price']}, "
                f"stop {event['old_stop']} → {event['new_stop']}"
            )
            # Sincronizar trailing stop con TastyTrade
            trade = self._find_trade(event["trade_id"])
            if trade and self.order_executor and trade.stop_order_id:
                result = self.order_executor.update_stop(
                    trade.stop_order_id, event["new_stop"]
                )
                if result.success:
                    _log(f"Stop actualizado en TastyTrade: {event['new_stop']}")
                else:
                    _log(f"Error actualizando stop en TastyTrade: {result.error}")

            notifier.notify_target_hit(event)

        elif event["type"] == "TRADE_CLOSED":
            _log(f"Trade cerrado ({event['reason']}): P&L={event['pnl_total_pts']:+.1f} pts")
            # Marcar detector como DONE
            for d in self.detectors:
                if d.state == State.ACTIVE:
                    d.mark_done()

            # Buscar el trade y loggearlo
            trade = self._find_trade(event["trade_id"])
            if trade:
                append_trade(trade)
                notifier.notify_trade_closed(
                    reason=event["reason"],
                    entry=trade.entry_price,
                    exit_price=event["price"],
                    pnl_total=event["pnl_total_pts"],
                )

    def _get_targets_for_level(self, level: float,
                               alignment: str = "NEUTRAL") -> list[float]:
        """
        Obtiene los targets para un trade LONG desde failed breakdown.

        Failed breakdown siempre produce señal LONG (precio se recupera hacia arriba).
        Si el trade es ALIGNED y el weekly tiene targets superiores a los diarios,
        enriquece la lista con el primer weekly target que supere el último daily.
        """
        if not self.plan:
            return []

        targets = list(self.plan.targets_upper)

        # Enriquecer con targets semanales si ALIGNED
        if alignment == "ALIGNED" and self.weekly and self.weekly.targets_upper:
            max_daily = max(targets) if targets else 0
            for wt in sorted(self.weekly.targets_upper):
                if wt > max_daily and wt not in targets:
                    targets.append(wt)
                    break  # Solo añadir el siguiente target semanal

        return sorted(targets)

    def _find_trade(self, trade_id: str):
        """Busca un trade por ID."""
        for t in self.trade_manager.trades:
            if t.id == trade_id:
                return t
        return None

    def _evaluate_gate(
        self, price: float, level: float, breakdown_low: float,
        direction: str, stop_price: float, targets: list[float],
        alignment: str, ts: str,
    ) -> tuple[bool, "GateDecision | None"]:
        """Evalúa el Execution Gate. Retorna (should_execute, decision)."""
        if not self.gate_enabled:
            return True, None

        from scripts.mancini.execution_gate import evaluate_signal, GateDecision
        from scripts.mancini.telegram_confirm import ask_trader_confirmation

        try:
            decision = evaluate_signal(
                signal_price=price,
                signal_level=level,
                breakdown_low=breakdown_low,
                direction=direction,
                stop_price=stop_price,
                targets=targets,
                plan_notes=self.plan.notes if self.plan else "",
                alignment=alignment,
                trades_today=self.trade_manager.trades,
                recent_adjustments=self.intraday_state.adjustments,
                current_time_et=_now_et(),
                session_end_hour=self.session_end,
            )
        except Exception as e:
            _log(f"Error en Execution Gate: {e} — ejecutando sin gate")
            return True, None

        append_gate_decision(decision, level, price)

        if decision.execute:
            _log(f"Gate APRUEBA: {decision.reasoning}")
            notifier.notify_gate_approved(decision, level, price, stop_price, targets, alignment)
            return True, decision

        # Gate dice no → preguntar al trader via Telegram
        _log(f"Gate RECHAZA: {decision.reasoning}")
        risk = abs(price - stop_price)
        signal_info = (
            f"📍 Nivel: {level} | ES: {price}\n"
            f"📉 Breakdown low: {breakdown_low}\n"
            f"🛑 Stop: {stop_price} (-{risk:.0f} pts)\n"
            f"🎯 Targets: {targets}\n"
            f"📊 Alignment: {alignment}"
        )

        try:
            trader_says_yes = ask_trader_confirmation(
                signal_info=signal_info,
                risk_factors=decision.risk_factors,
                reasoning=decision.reasoning,
                timeout_seconds=120,
            )
        except Exception as e:
            _log(f"Error en confirmación Telegram: {e} — descartando trade")
            return False, decision

        if trader_says_yes:
            _log("Trader confirma ejecución manual")
            return True, decision
        else:
            reason = "timeout" if trader_says_yes is None else "trader dijo no"
            _log(f"Trade descartado: {reason}")
            return False, decision

    def _place_trade_orders(self, trade, direction: str) -> None:
        """Lanza órdenes entry + stop en TastyTrade si hay executor."""
        if not self.order_executor or not self.es_symbol:
            return

        entry_result = self.order_executor.place_entry(direction, self.es_symbol)
        if entry_result.success:
            trade.entry_order_id = entry_result.order_id
            stop_result = self.order_executor.place_stop(
                direction, self.es_symbol, trade.stop_price
            )
            if stop_result.success:
                trade.stop_order_id = stop_result.order_id
            else:
                _log(f"Error lanzando stop: {stop_result.error}")
            mode = "dry-run" if entry_result.dry_run else "LIVE"
            _log(f"Orden {mode}: entry OK, stop {'OK' if stop_result.success else 'FAIL'}")
        else:
            _log(f"Error lanzando orden entry: {entry_result.error}")

    # ── Intraday tweet updates ─────────────────────────────────────

    def check_intraday_updates(self) -> list[PlanAdjustment]:
        """Fetch tweets nuevos, clasificar y aplicar ajustes al plan.

        Retorna lista de adjustments aplicados (para testing).
        """
        from scripts.mancini.tweet_fetcher import fetch_mancini_tweets
        from scripts.mancini.tweet_classifier import classify_tweet

        applied = []

        try:
            tweets = fetch_mancini_tweets(max_tweets=10)
        except Exception as e:
            _log(f"Error fetching tweets intraday: {e}")
            return applied

        new_tweets = [
            t for t in tweets
            if t["id"] not in self.intraday_state.processed_tweet_ids
        ]

        for tweet in new_tweets:
            self.intraday_state.processed_tweet_ids.add(tweet["id"])
            try:
                adjustment = classify_tweet(
                    tweet["text"],
                    tweet["id"],
                    tweet["created_at"],
                    self.plan,
                )
            except Exception as e:
                _log(f"Error clasificando tweet {tweet['id']}: {e}")
                continue

            self.intraday_state.adjustments.append(adjustment)
            append_adjustment(adjustment)

            if adjustment.adjustment_type != "NO_ACTION":
                self._apply_adjustment(adjustment)
                notifier.notify_adjustment(adjustment)
                applied.append(adjustment)

        self.intraday_state.last_check = datetime.now(timezone.utc).isoformat()
        return applied

    def _apply_adjustment(self, adj: PlanAdjustment) -> None:
        """Aplica un ajuste al plan y detectores activos."""
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

    def _handle_invalidation(self, adj: PlanAdjustment) -> None:
        scope = adj.details.get("scope", "full")
        if scope == "full":
            for det in self.detectors:
                if det.state not in (State.DONE, State.EXPIRED):
                    det.mark_expired()
            _log("Plan invalidado completamente — detectores pausados")
        elif scope in ("upper", "lower"):
            det = self._get_detector_by_side(scope)
            if det and det.state not in (State.DONE, State.EXPIRED):
                det.mark_expired()
                _log(f"Nivel {scope} invalidado — detector pausado")

    def _handle_level_update(self, adj: PlanAdjustment) -> None:
        side = adj.details.get("side")
        new_level = adj.details.get("new_level")
        if not side or new_level is None:
            return
        new_level = float(new_level)
        if side == "upper":
            self.plan.key_level_upper = new_level
        else:
            self.plan.key_level_lower = new_level
        det = self._get_detector_by_side(side)
        if det and det.state == State.WATCHING:
            det.level = new_level
        save_plan(self.plan, self.plan_path)
        _log(f"Nivel {side} actualizado a {new_level}")

    def _handle_target_update(self, adj: PlanAdjustment) -> None:
        side = adj.details.get("side")
        new_targets = adj.details.get("new_targets", [])
        replace = adj.details.get("replace", False)
        if not side or not new_targets:
            return
        new_targets = [float(t) for t in new_targets]
        if side == "upper":
            if replace:
                self.plan.targets_upper = new_targets
            else:
                self.plan.targets_upper = sorted(
                    set(self.plan.targets_upper + new_targets)
                )
        else:
            if replace:
                self.plan.targets_lower = new_targets
            else:
                self.plan.targets_lower = sorted(
                    set(self.plan.targets_lower + new_targets), reverse=True
                )
        save_plan(self.plan, self.plan_path)
        _log(f"Targets {side} actualizados: {new_targets}")

    def _handle_bias_shift(self, adj: PlanAdjustment) -> None:
        new_bias = adj.details.get("new_bias", "")
        self.plan.notes = f"Bias shift: {new_bias} (via intraday update)"
        save_plan(self.plan, self.plan_path)
        active_trade = self.trade_manager.active_trade()
        if active_trade:
            new_alignment = self.calc_alignment(active_trade.direction)
            _log(f"Alignment recalculado: {active_trade.alignment} -> {new_alignment}")
        _log(f"Sesgo actualizado: {new_bias}")

    def _handle_context_update(self, adj: PlanAdjustment) -> None:
        _log(f"Context update: {adj.details.get('summary', adj.raw_reasoning)}")

    def _get_detector_by_side(self, side: str) -> FailedBreakdownDetector | None:
        """Busca detector por lado (upper/lower)."""
        for d in self.detectors:
            if d.side == side:
                return d
        return None

    def close_session(self) -> None:
        """Cierra la sesión: expira detectores, NO cierra trades activos.

        Los runners sobreviven overnight. El trade activo se persiste
        en estado y se retoma al reiniciar el monitor al día siguiente.
        """
        now = _now_et()

        # NO cerrar trades activos — runners overnight
        trade = self.trade_manager.active_trade()
        if trade:
            _log(f"Runner activo persiste overnight: entry={trade.entry_price} stop={trade.stop_price} targets_hit={trade.targets_hit}")

        # Expirar detectores activos
        for d in self.detectors:
            if d.state not in (State.DONE, State.EXPIRED):
                d.mark_expired()

        # Resumen
        total_pnl = sum(
            t.pnl_total_pts or 0 for t in self.trade_manager.trades
            if t.status == TradeStatus.CLOSED
        )
        fecha = self.plan.fecha if self.plan else now.strftime("%Y-%m-%d")
        _log(f"Sesión finalizada — {self.trade_manager.trades_today()} trades, P&L={total_pnl:+.1f} pts")
        notifier.notify_session_summary(fecha, self.trade_manager.trades_today(), total_pnl)

        self.save_state()

    def _log_plan_info(self) -> None:
        """Muestra info del plan y weekly al log."""
        _log(f"Plan: upper={self.plan.key_level_upper} lower={self.plan.key_level_lower}")
        _log(f"Targets up: {self.plan.targets_upper}")
        _log(f"Targets down: {self.plan.targets_lower}")
        bias = self.calc_weekly_bias()
        if self.weekly:
            _log(f"Weekly: upper={self.weekly.key_level_upper} lower={self.weekly.key_level_lower} sesgo={bias}")
        else:
            _log(f"Weekly: no cargado (sesgo={bias})")

    def _wait_for_plan(self) -> bool:
        """Alias de _scan_for_plan para compatibilidad con tests."""
        return self._scan_for_plan()

    def run(self) -> None:
        """Loop principal del monitor. Se auto-finaliza a SESSION_END_HOUR ET."""
        _log("Monitor arrancando...")
        self.load_state()

        consecutive_errors = 0
        MAX_CONSECUTIVE_ERRORS = 5

        try:
            while True:
                try:
                    now = _now_et()

                    # Auto-finalizar
                    if now.hour >= self.session_end:
                        self.close_session()
                        break

                    # Esperar a session_start
                    if now.hour < self.session_start:
                        _log(f"Esperando inicio de sesión ({self.session_start}:00 ET)...")
                        time.sleep(self.poll_interval)
                        continue

                    # Si no hay plan, buscarlo en tweets de Mancini
                    if not self.plan:
                        if not self._scan_for_plan():
                            break
                        continue

                    # Poll
                    price = self.poll_es()
                    if price is None:
                        time.sleep(self.poll_interval)
                        continue

                    _log(f"ES={price:.2f}")
                    self.process_tick(price)

                    # Clasificar tweets intraday nuevos
                    if self.plan:
                        self.check_intraday_updates()

                    self.save_state()

                    consecutive_errors = 0
                    time.sleep(self.poll_interval)

                except Exception as e:
                    consecutive_errors += 1
                    _log(f"ERROR en loop ({consecutive_errors}/{MAX_CONSECUTIVE_ERRORS}): {e}")
                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        _log("Demasiados errores consecutivos, cerrando monitor")
                        notifier.notify_monitor_crash(
                            f"{consecutive_errors} errores consecutivos. Ultimo: {e}"
                        )
                        self.save_state()
                        break
                    time.sleep(self.poll_interval)

        except KeyboardInterrupt:
            _log("Interrumpido por usuario")
            self.close_session()
        except Exception as e:
            _log(f"FATAL: {e}")
            notifier.notify_monitor_crash(f"Crash fatal: {e}")
            self.save_state()
            raise
