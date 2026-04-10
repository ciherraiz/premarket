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

from scripts.mancini.config import DailyPlan, load_plan, PLAN_PATH
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
SESSION_START_HOUR = 8   # 08:00 ET
SESSION_END_HOUR = 11    # 11:00 ET


def _now_et() -> datetime:
    return datetime.now(ET)


def _log(msg: str) -> None:
    ts = _now_et().strftime("%H:%M:%S ET")
    print(f"[mancini {ts}] {msg}", flush=True)


class ManciniMonitor:
    """Orquesta polling, detección y gestión de trades."""

    def __init__(self, client=None, poll_interval: int = POLL_INTERVAL_S,
                 plan_path: Path = PLAN_PATH, state_path: Path = STATE_PATH):
        self.client = client
        self.poll_interval = poll_interval
        self.plan_path = plan_path
        self.state_path = state_path
        self.plan: DailyPlan | None = None
        self.detectors: list[FailedBreakdownDetector] = []
        self.trade_manager = TradeManager()
        self._plan_mtime: float = 0

    def load_state(self) -> None:
        """Carga plan y detectores desde disco."""
        self.plan = load_plan(self.plan_path)
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
                if new_up or new_down:
                    _log(f"Plan actualizado — nuevos targets: up={new_up} down={new_down}")

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
            targets = self._get_targets_for_level(t.level)

            # Proponer trade
            trade = self.trade_manager.open_trade(
                direction="LONG",
                entry_price=price,
                breakdown_low=breakdown_low,
                targets=targets,
                timestamp=ts,
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
                )
                _log(f"Trade abierto: LONG {trade.entry_price} stop={trade.stop_price}")
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

    def _get_targets_for_level(self, level: float) -> list[float]:
        """
        Obtiene los targets para un trade LONG desde failed breakdown.

        Failed breakdown siempre produce señal LONG (precio se recupera hacia arriba).
        - Nivel inferior (6781 fails → recovery): targets son los niveles superiores
          del plan (6809, 6819, 6830) — el precio sube hacia ellos.
        - Nivel superior (6809 fails → recovery): targets son los targets_upper
          (6819, 6830) — el precio continúa subiendo.
        """
        if not self.plan:
            return []
        # Failed breakdown = LONG → siempre targets hacia arriba
        return self.plan.targets_upper

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

        try:
            while True:
                now = _now_et()

                # Auto-finalizar
                if now.hour >= SESSION_END_HOUR:
                    self.close_session()
                    break

                # Esperar a SESSION_START_HOUR
                if now.hour < SESSION_START_HOUR:
                    _log(f"Esperando inicio de sesión ({SESSION_START_HOUR}:00 ET)...")
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
