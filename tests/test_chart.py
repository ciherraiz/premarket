"""Tests para scripts/mancini/chart.py — generación de gráficos PNG."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from scripts.mancini.chart import generate_plan_chart, _detector_style
from scripts.mancini.config import DailyPlan
from scripts.mancini.detector import FailedBreakdownDetector, State
from scripts.mancini.trade_manager import Trade, TradeStatus

PNG_HEADER = b"\x89PNG"


def _make_plan(**overrides) -> DailyPlan:
    defaults = dict(
        fecha="2026-04-17",
        key_level_upper=5850.0,
        targets_upper=[5870.0, 5890.0, 5910.0],
        key_level_lower=5800.0,
        targets_lower=[5780.0, 5760.0],
        raw_tweets=["test tweet"],
    )
    defaults.update(overrides)
    return DailyPlan(**defaults)


def _make_detector(level=5800.0, side="lower",
                   state=State.WATCHING, **kw) -> FailedBreakdownDetector:
    return FailedBreakdownDetector(level=level, side=side, state=state, **kw)


def _make_trade(**overrides) -> Trade:
    defaults = dict(
        id="test-trade-1",
        direction="LONG",
        entry_price=5805.0,
        entry_time="2026-04-17T14:00:00Z",
        stop_price=5790.0,
        targets=[5870.0, 5890.0, 5910.0],
        status=TradeStatus.OPEN,
        targets_hit=0,
    )
    defaults.update(overrides)
    return Trade(**defaults)


class TestGenerateChart:
    def test_basic_plan(self):
        """Plan con niveles + precio → PNG válido."""
        plan = _make_plan()
        detectors = [
            _make_detector(5850.0, "upper"),
            _make_detector(5800.0, "lower"),
        ]
        result = generate_plan_chart(plan, 5820.0, detectors)
        assert isinstance(result, bytes)
        assert len(result) > 0
        assert result[:4] == PNG_HEADER

    def test_with_trade(self):
        """Plan + trade activo → PNG incluye entry/stop."""
        plan = _make_plan()
        detectors = [_make_detector(5800.0, "lower", State.ACTIVE)]
        trade = _make_trade()
        result = generate_plan_chart(plan, 5820.0, detectors, trade=trade)
        assert result[:4] == PNG_HEADER
        assert len(result) > 1000  # imagen no trivial

    def test_with_targets_hit(self):
        """Targets alcanzados se marcan con ✓."""
        plan = _make_plan()
        detectors = [_make_detector(5800.0, "lower", State.ACTIVE)]
        trade = _make_trade(targets_hit=2)
        result = generate_plan_chart(plan, 5895.0, detectors, trade=trade)
        assert result[:4] == PNG_HEADER

    def test_no_detectors(self):
        """Plan sin detectores → no falla."""
        plan = _make_plan()
        result = generate_plan_chart(plan, 5820.0, [])
        assert result[:4] == PNG_HEADER

    def test_chop_zone(self):
        """Plan con chop zone → no falla."""
        plan = _make_plan(chop_zone=(5810.0, 5840.0))
        detectors = [_make_detector(5800.0, "lower")]
        result = generate_plan_chart(plan, 5825.0, detectors)
        assert result[:4] == PNG_HEADER

    def test_only_upper_level(self):
        """Plan con solo key_level_upper → no falla."""
        plan = _make_plan(key_level_lower=None, targets_lower=[])
        detectors = [_make_detector(5850.0, "upper")]
        result = generate_plan_chart(plan, 5830.0, detectors)
        assert result[:4] == PNG_HEADER

    def test_returns_valid_png(self):
        """Los primeros bytes son \\x89PNG."""
        plan = _make_plan()
        result = generate_plan_chart(plan, 5820.0, [])
        assert result[:4] == PNG_HEADER

    def test_with_timestamp(self):
        """timestamp_et se incluye en el título."""
        plan = _make_plan()
        result = generate_plan_chart(plan, 5820.0, [], timestamp_et="14:30 ET")
        assert result[:4] == PNG_HEADER

    def test_with_price_history(self):
        """Price history dibuja línea temporal con eje X."""
        plan = _make_plan()
        history = [("09:30", 5810.0), ("09:35", 5815.0), ("09:40", 5820.0)]
        result = generate_plan_chart(plan, 5820.0, [], price_history=history)
        assert result[:4] == PNG_HEADER

    def test_with_empty_price_history(self):
        """Historial vacío → fallback a línea horizontal."""
        plan = _make_plan()
        result = generate_plan_chart(plan, 5820.0, [], price_history=[])
        assert result[:4] == PNG_HEADER

    def test_with_single_point_history(self):
        """Un solo punto → fallback (necesita >=2)."""
        plan = _make_plan()
        result = generate_plan_chart(plan, 5820.0, [],
                                     price_history=[("09:30", 5810.0)])
        assert result[:4] == PNG_HEADER

    def test_price_history_with_trade(self):
        """Historial + trade activo renderiza ambos."""
        plan = _make_plan()
        history = [("09:30", 5810.0), ("10:00", 5820.0), ("10:30", 5825.0)]
        trade = _make_trade()
        detectors = [_make_detector(5800.0, "lower", State.ACTIVE)]
        result = generate_plan_chart(plan, 5825.0, detectors, trade=trade,
                                     price_history=history)
        assert result[:4] == PNG_HEADER
        assert len(result) > 1000

    def test_price_history_long_session(self):
        """Sesión completa (540 ticks, 9h cada 60s) → no falla."""
        plan = _make_plan()
        history = [(f"{7 + i // 60:02d}:{i % 60:02d}", 5800.0 + i * 0.1)
                   for i in range(540)]
        result = generate_plan_chart(plan, 5854.0, [], price_history=history)
        assert result[:4] == PNG_HEADER


class TestDetectorStyle:
    @pytest.mark.parametrize("state,expected_text", [
        (State.WATCHING, "VIGILANDO"),
        (State.SIGNAL, "SEÑAL CONFIRMADA"),
        (State.ACTIVE, "TRADE ACTIVO"),
        (State.DONE, "COMPLETADO"),
        (State.EXPIRED, "EXPIRADO"),
    ])
    def test_states(self, state, expected_text):
        det = _make_detector(state=state)
        color, text = _detector_style(det)
        assert expected_text in text
        assert color.startswith("#")

    def test_breakdown_with_low(self):
        det = _make_detector(state=State.BREAKDOWN, breakdown_low=5795.0)
        color, text = _detector_style(det)
        assert "BREAKDOWN" in text
        assert "5 pts" in text

    def test_recovery_with_polls(self):
        det = _make_detector(state=State.RECOVERY)
        det.acceptance_count = 2
        color, text = _detector_style(det)
        assert "RECUPERANDO" in text
        assert "2 polls" in text
