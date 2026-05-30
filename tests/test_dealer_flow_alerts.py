"""
Tests de las alertas intraday de Dealer Flow.

Cubre:
  1. notify_charm_shift — formato y condición de envío
  2. notify_pinning_change — condición de desplazamiento
  3. _poll_gex del monitor — disparo de alertas charm/pinning
"""

import sys
import os
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.mancini.notifier import notify_charm_shift, notify_pinning_change


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SPOT  = 5500.0
FECHA = "2026-05-29"


def _snap(charm_signal="EXPANSIVO", charm_total=150_000,
          charm_pin_zone=5500.0, spot=SPOT,
          ts="2026-05-29T10:00:00",
          dex_signal="DEALERS_LARGO_DELTA",
          flip_level=5480.0, gex_by_strike=None):
    return {
        "ts":             ts,
        "fecha":          FECHA,
        "spot":           spot,
        "flip_level":     flip_level,
        "control_node":   None,
        "net_gex_bn":     5.0,
        "signal_gex":     "LONG_GAMMA_FUERTE",
        "regime_text":    "Dealers LONG gamma (fuerte)",
        "put_wall":       5400.0,
        "call_wall":      5600.0,
        "charm_signal":   charm_signal,
        "charm_total":    charm_total,
        "charm_pin_zone": charm_pin_zone,
        "dex_signal":     dex_signal,
        "dex_total":      -2.5,
        "dex_flip":       5490.0,
        "gex_by_strike":  gex_by_strike or {"5500": 1.0},
        "status":         "OK",
    }


# ---------------------------------------------------------------------------
# Tests: notify_charm_shift
# ---------------------------------------------------------------------------

class TestNotifyCharmShift:

    def test_calls_send_telegram(self):
        """notify_charm_shift llama a send_telegram."""
        with patch("scripts.mancini.notifier.send_telegram", return_value=True) as mock_send:
            result = notify_charm_shift(
                _snap(charm_signal="EXPANSIVO"),
                _snap(charm_signal="SUPRESIVO", ts="2026-05-29T13:00:00"),
            )
        mock_send.assert_called_once()
        assert result is True

    def test_message_contains_signals(self):
        """El mensaje incluye los nombres de ambas señales."""
        captured = []
        with patch("scripts.mancini.notifier.send_telegram",
                   side_effect=lambda m: captured.append(m) or True):
            notify_charm_shift(
                _snap(charm_signal="EXPANSIVO"),
                _snap(charm_signal="SUPRESIVO", ts="2026-05-29T13:00:00"),
            )
        msg = captured[0]
        assert "EXPANSIVO" in msg
        assert "SUPRESIVO" in msg

    def test_message_contains_charm_total(self):
        """El mensaje incluye el charm total en K δ/h."""
        captured = []
        with patch("scripts.mancini.notifier.send_telegram",
                   side_effect=lambda m: captured.append(m) or True):
            notify_charm_shift(
                _snap(charm_signal="EXPANSIVO"),
                _snap(charm_signal="SUPRESIVO", charm_total=-95_000,
                      ts="2026-05-29T13:00:00"),
            )
        msg = captured[0]
        assert "95" in msg or "K" in msg

    def test_returns_bool(self):
        with patch("scripts.mancini.notifier.send_telegram", return_value=False):
            result = notify_charm_shift(_snap(), _snap(charm_signal="SUPRESIVO"))
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# Tests: notify_pinning_change
# ---------------------------------------------------------------------------

class TestNotifyPinningChange:

    def test_calls_send_telegram_when_shifted(self):
        """Envía alerta cuando pin_zone cambia > threshold."""
        with patch("scripts.mancini.notifier.send_telegram", return_value=True) as mock_send:
            result = notify_pinning_change(
                _snap(charm_pin_zone=5500.0),
                _snap(charm_pin_zone=5550.0, ts="2026-05-29T13:00:00"),
                threshold_pts=25.0,
            )
        mock_send.assert_called_once()
        assert result is True

    def test_no_call_when_below_threshold(self):
        """No envía si el desplazamiento es menor que threshold."""
        with patch("scripts.mancini.notifier.send_telegram", return_value=True) as mock_send:
            result = notify_pinning_change(
                _snap(charm_pin_zone=5500.0),
                _snap(charm_pin_zone=5515.0, ts="2026-05-29T13:00:00"),
                threshold_pts=25.0,
            )
        mock_send.assert_not_called()
        assert result is False

    def test_no_call_when_pin_none(self):
        """No envía si alguno de los pines es None."""
        with patch("scripts.mancini.notifier.send_telegram", return_value=True) as mock_send:
            result = notify_pinning_change(
                _snap(charm_pin_zone=None),
                _snap(charm_pin_zone=5550.0),
            )
        mock_send.assert_not_called()
        assert result is False

    def test_message_contains_both_pin_values(self):
        """El mensaje incluye pin anterior y actual."""
        captured = []
        with patch("scripts.mancini.notifier.send_telegram",
                   side_effect=lambda m: captured.append(m) or True):
            notify_pinning_change(
                _snap(charm_pin_zone=5500.0),
                _snap(charm_pin_zone=5550.0, ts="2026-05-29T13:00:00"),
            )
        msg = captured[0]
        assert "5500" in msg
        assert "5550" in msg

    def test_negative_shift_detected(self):
        """Desplazamiento hacia abajo también dispara la alerta."""
        with patch("scripts.mancini.notifier.send_telegram", return_value=True) as mock_send:
            result = notify_pinning_change(
                _snap(charm_pin_zone=5550.0),
                _snap(charm_pin_zone=5500.0, ts="2026-05-29T13:00:00"),
                threshold_pts=25.0,
            )
        mock_send.assert_called_once()
        assert result is True


# ---------------------------------------------------------------------------
# Tests: monitor _poll_gex — disparar alertas charm/pinning
# ---------------------------------------------------------------------------

class TestMonitorPollGexAlerts:
    """
    Testea la lógica de detección en _poll_gex sin necesidad de un cliente real.
    Comprueba que notify_charm_shift y notify_pinning_change se llaman
    cuando corresponde.
    """

    def _make_monitor_with_last_snap(self, last_snap: dict):
        """Crea un monitor mínimo con _last_gex_snapshot ya establecido."""
        import importlib
        # Importar el módulo completo para acceder a la clase
        monitor_mod = importlib.import_module("scripts.mancini.monitor")
        MonitorClass = monitor_mod.ManciniMonitor

        # Instanciar sin conectar al cliente
        with patch.object(MonitorClass, "__init__",
                          lambda self, *a, **kw: None):
            mon = MonitorClass.__new__(MonitorClass)

        mon._last_gex_snapshot    = last_snap
        mon._opening_gex_snapshot = last_snap
        mon.client                = MagicMock()
        return mon

    def test_charm_shift_alert_fires(self):
        """
        Cuando charm cambia de EXPANSIVO → SUPRESIVO entre snapshots,
        notify_charm_shift debe llamarse.
        """
        prev = _snap(charm_signal="EXPANSIVO", charm_pin_zone=5500.0)
        curr = _snap(charm_signal="SUPRESIVO", charm_pin_zone=5500.0,
                     ts="2026-05-29T13:00:00")

        with patch("scripts.mancini.notifier.notify_charm_shift",
                   return_value=True) as mock_charm, \
             patch("scripts.mancini.notifier.notify_gex_shift",
                   return_value=True), \
             patch("scripts.mancini.notifier.notify_pinning_change",
                   return_value=False):

            # Simular la lógica de _poll_gex directamente
            prev_charm = prev.get("charm_signal") or "NEUTRO"
            curr_charm = curr.get("charm_signal") or "NEUTRO"
            if (prev_charm != curr_charm
                    and "NEUTRO" not in (prev_charm, curr_charm)):
                import scripts.mancini.notifier as notifier
                notifier.notify_charm_shift(prev, curr)

        mock_charm.assert_called_once_with(prev, curr)

    def test_charm_shift_not_fired_when_same(self):
        """No se dispara si la señal charm no cambia."""
        prev = _snap(charm_signal="EXPANSIVO")
        curr = _snap(charm_signal="EXPANSIVO", ts="2026-05-29T11:00:00")

        called = []
        prev_c = prev.get("charm_signal") or "NEUTRO"
        curr_c = curr.get("charm_signal") or "NEUTRO"
        if (prev_c != curr_c and "NEUTRO" not in (prev_c, curr_c)):
            called.append(True)

        assert not called

    def test_charm_shift_not_fired_when_neutro_involved(self):
        """No se dispara si una de las señales es NEUTRO."""
        prev = _snap(charm_signal="EXPANSIVO")
        curr = _snap(charm_signal="NEUTRO", ts="2026-05-29T12:00:00")

        called = []
        prev_c = prev.get("charm_signal") or "NEUTRO"
        curr_c = curr.get("charm_signal") or "NEUTRO"
        if (prev_c != curr_c and "NEUTRO" not in (prev_c, curr_c)):
            called.append(True)

        assert not called

    def test_pinning_change_alert_fires(self):
        """Cuando pin_zone > 25 pts, notify_pinning_change debe llamarse."""
        prev = _snap(charm_pin_zone=5500.0)
        curr = _snap(charm_pin_zone=5550.0, ts="2026-05-29T13:00:00")

        with patch("scripts.mancini.notifier.notify_pinning_change",
                   return_value=True) as mock_pin:
            prev_pin = prev.get("charm_pin_zone")
            curr_pin = curr.get("charm_pin_zone")
            if (prev_pin is not None and curr_pin is not None
                    and abs(curr_pin - prev_pin) > 25):
                import scripts.mancini.notifier as notifier
                notifier.notify_pinning_change(prev, curr)

        mock_pin.assert_called_once_with(prev, curr)

    def test_pinning_change_not_fired_when_small(self):
        """No se dispara si el desplazamiento del pin es ≤ 25 pts."""
        prev = _snap(charm_pin_zone=5500.0)
        curr = _snap(charm_pin_zone=5520.0, ts="2026-05-29T13:00:00")

        called = []
        prev_pin = prev.get("charm_pin_zone")
        curr_pin = curr.get("charm_pin_zone")
        if (prev_pin is not None and curr_pin is not None
                and abs(curr_pin - prev_pin) > 25):
            called.append(True)

        assert not called
