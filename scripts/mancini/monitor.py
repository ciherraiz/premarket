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

from scripts.mancini.config import DailyPlan, load_plan, load_weekly, PLAN_PATH, WEEKLY_PLAN_PATH
from scripts.mancini.detector import (
    FailedBreakdownDetector,
    State,
    StateTransition,
    save_detectors,
    load_detectors,
    STATE_PATH,
)
from scripts.mancini.trade_manager import TradeManager, TradeStatus
from scripts.mancini.logger import append_trade
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
                 session_start: int = SESSION_START_HOUR,
                 session_end: int = SESSION_END_HOUR):
        self.client = client
        self.poll_interval = poll_interval
        self.plan_path = plan_path
        self.state_path = state_path
        self.weekly_path = weekly_path
        self.session_start = session_start
        self.session_end = session_end
        self.plan: DailyPlan | None = None
        self.weekly: DailyPlan | None = None
        self.detectors: list[FailedBreakdownDetector] = []
        self.trade_manager = TradeManager()
        self._plan_mtime: float = 0

    def load_state(self) -> None:
        """Carga plan, weekly y detectores desde disco."""
        self.plan = load_plan(self.plan_path)
        self.weekly = load_weekly(self.weekly_path)
        if self.plan:
            self.trade_manager.fecha = self.plan.fecha
            self._plan_mtime = self.plan_path.stat().st_mtime if self.plan_path.exists() else 0

        self.detectors = load_detectors(self.state_path)
        if not self.detectors and self.plan:
            self._init_detectors()

    def _init_detectors(self) -> None:
        """Crea detectores a partir del plan actual."""
        self.detectors = [
            FailedBreakdownDetector(level=self.plan.key_level_upper, side="upper"),
            FailedBreakdownDetector(level=self.plan.key_level_lower, side="lower"),
        ]

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
        """Persiste detectores en disco."""
        save_detectors(self.detectors, self.state_path)

    def _check_plan_updates(self) -> None:
        """Recarga el plan si el fichero ha cambiado (scan de tweets actualizó)."""
        if not self.plan_path.exists():
            return
        mtime = self.plan_path.stat().st_mtime
        if mtime > self._plan_mtime:
            old_plan = self.plan
            self.plan = load_plan(self.plan_path)
            self._plan_mtime = mtime
            if self.plan and old_plan:
                # Detectar nuevos targets
                new_up = set(self.plan.targets_upper) - set(old_plan.targets_upper)
                new_down = set(self.plan.targets_lower) - set(old_plan.targets_lower)
                new_upper = self.plan.key_level_upper != old_plan.key_level_upper
                new_lower = self.plan.key_level_lower != old_plan.key_level_lower
                if new_up or new_down or new_upper or new_lower:
                    _log(f"Plan actualizado — nuevos targets: up={new_up} down={new_down}")
                    notifier.notify_plan_loaded(self.plan.to_dict())
                    # Reiniciar detectores si cambiaron los niveles clave
                    if new_upper or new_lower:
                        _log("Niveles clave cambiaron — reiniciando detectores")
                        self._init_detectors()

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
            runner_mode = alignment != "MISALIGNED"

            if alignment == "MISALIGNED":
                _log(f"⚠️ Trade MISALIGNED (contra sesgo semanal) — solo T1")

            # Proponer trade
            trade = self.trade_manager.open_trade(
                direction=direction,
                entry_price=price,
                breakdown_low=breakdown_low,
                targets=targets,
                timestamp=ts,
                runner_mode=runner_mode,
                alignment=alignment,
            )
            if trade:
                # Marcar detector como activo
                for d in self.detectors:
                    if d.level == t.level and d.state == State.SIGNAL:
                        d.mark_active()

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
        if event["type"] == "PARTIAL_EXIT":
            _log(f"Target 1 alcanzado: +{event['pnl_partial_pts']:.0f} pts, stop→breakeven")
            notifier.notify_partial_exit(
                event["price"], event["pnl_partial_pts"], event["runner_stop"]
            )
        elif event["type"] == "TRADE_CLOSED":
            _log(f"Trade cerrado ({event['reason']}): P&L={event['pnl_total_pts']:+.1f} pts")
            # Marcar detector como DONE
            for d in self.detectors:
                if d.state == State.ACTIVE:
                    d.mark_done()

            # Buscar el trade y loggearlo
            for t in self.trade_manager.trades:
                if t.id == event["trade_id"]:
                    append_trade(t)
                    notifier.notify_trade_closed(
                        reason=event["reason"],
                        entry=t.entry_price,
                        exit_price=event["price"],
                        pnl_total=event["pnl_total_pts"],
                        pnl_partial=t.pnl_partial_pts,
                        pnl_runner=t.pnl_runner_pts,
                    )
                    break

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

    def close_session(self) -> None:
        """Cierra la sesión: EOD trades activos, envía resumen."""
        now = _now_et()
        ts = datetime.now(timezone.utc).isoformat()

        # Cerrar trades activos
        trade = self.trade_manager.active_trade()
        if trade:
            price = self.poll_es()
            if price:
                event = self.trade_manager.close_eod(price, ts)
                if event:
                    self._handle_trade_event(event)

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

    def run(self) -> None:
        """Loop principal del monitor. Se auto-finaliza a SESSION_END_HOUR ET."""
        _log("Monitor arrancando...")
        self.load_state()

        if not self.plan:
            _log("ERROR: No hay plan cargado. Ejecuta /mancini-scan primero.")
            return

        _log(f"Plan: upper={self.plan.key_level_upper} lower={self.plan.key_level_lower}")
        _log(f"Targets up: {self.plan.targets_upper}")
        _log(f"Targets down: {self.plan.targets_lower}")
        bias = self.calc_weekly_bias()
        if self.weekly:
            _log(f"Weekly: upper={self.weekly.key_level_upper} lower={self.weekly.key_level_lower} sesgo={bias}")
        else:
            _log(f"Weekly: no cargado (sesgo={bias})")

        # Enviar plan a Telegram al arrancar
        notifier.notify_plan_loaded(self.plan.to_dict())

        try:
            while True:
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

                # Recargar plan si cambió
                self._check_plan_updates()

                # Poll
                price = self.poll_es()
                if price is None:
                    time.sleep(self.poll_interval)
                    continue

                _log(f"ES={price:.2f}")
                self.process_tick(price)
                self.save_state()

                time.sleep(self.poll_interval)

        except KeyboardInterrupt:
            _log("Interrumpido por usuario")
            self.close_session()
