"""Tests para scripts/mancini/order_executor.py — Wrapper TastyTrade."""

import os
import sys
from decimal import Decimal
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from scripts.mancini.order_executor import OrderExecutor, OrderResult


@pytest.fixture
def mock_session():
    return MagicMock()


@pytest.fixture
def mock_account():
    return MagicMock()


@pytest.fixture
def executor(mock_session, mock_account):
    """Executor en dry-run con 1 contrato."""
    return OrderExecutor(
        session=mock_session,
        account=mock_account,
        dry_run=True,
        contracts=1,
    )


# ── place_entry ──────────────────────────────────────────────────────

def test_place_entry_long_dry_run(executor, mock_account):
    """Entry LONG en dry-run → BUY market."""
    mock_response = MagicMock()
    mock_response.model_dump.return_value = {"status": "ok"}
    mock_account.place_order.return_value = mock_response

    result = executor.place_entry("LONG", "/ESM6:XCME")

    assert result.success is True
    assert result.dry_run is True
    assert result.order_id is None  # dry-run no tiene order_id
    mock_account.place_order.assert_called_once()

    # Verificar la orden
    call_args = mock_account.place_order.call_args
    order = call_args[0][1]  # segundo arg posicional
    assert call_args.kwargs["dry_run"] is True


def test_place_entry_short_dry_run(executor, mock_account):
    """Entry SHORT en dry-run → SELL market."""
    mock_response = MagicMock()
    mock_response.model_dump.return_value = {}
    mock_account.place_order.return_value = mock_response

    result = executor.place_entry("SHORT", "/ESM6:XCME")
    assert result.success is True


def test_place_entry_live(mock_session, mock_account):
    """Entry en modo live devuelve order_id."""
    executor = OrderExecutor(mock_session, mock_account, dry_run=False)

    mock_response = MagicMock()
    mock_response.id = "order-123"
    mock_response.model_dump.return_value = {"id": "order-123"}
    mock_account.place_order.return_value = mock_response

    result = executor.place_entry("LONG", "/ESM6:XCME")
    assert result.success is True
    assert result.dry_run is False
    assert result.order_id == "order-123"


def test_place_entry_error(executor, mock_account):
    """Error del SDK → OrderResult con error."""
    mock_account.place_order.side_effect = Exception("Connection timeout")

    result = executor.place_entry("LONG", "/ESM6:XCME")
    assert result.success is False
    assert "Connection timeout" in result.error


# ── place_stop ───────────────────────────────────────────────────────

def test_place_stop_long(executor, mock_account):
    """Stop para LONG → SELL stop GTC."""
    mock_response = MagicMock()
    mock_response.model_dump.return_value = {}
    mock_account.place_order.return_value = mock_response

    result = executor.place_stop("LONG", "/ESM6:XCME", 6772.0)
    assert result.success is True


def test_place_stop_short(executor, mock_account):
    """Stop para SHORT → BUY stop GTC."""
    mock_response = MagicMock()
    mock_response.model_dump.return_value = {}
    mock_account.place_order.return_value = mock_response

    result = executor.place_stop("SHORT", "/ESM6:XCME", 6820.0)
    assert result.success is True


# ── update_stop ──────────────────────────────────────────────────────

def test_update_stop_success(executor, mock_account):
    """Modificar stop existente (trailing)."""
    mock_account.replace_order.return_value = MagicMock()

    result = executor.update_stop("order-456", 6793.0)
    assert result.success is True
    assert result.order_id == "order-456"

    mock_account.replace_order.assert_called_once_with(
        executor.session, "order-456",
        stop_trigger=Decimal("6793.0"),
    )


def test_update_stop_error(executor, mock_account):
    """Error al modificar stop."""
    mock_account.replace_order.side_effect = Exception("Order not found")

    result = executor.update_stop("order-456", 6793.0)
    assert result.success is False
    assert "Order not found" in result.error


# ── close_position ───────────────────────────────────────────────────

def test_close_position_long(executor, mock_account):
    """Cerrar posición LONG → SELL market."""
    mock_response = MagicMock()
    mock_response.model_dump.return_value = {}
    mock_account.place_order.return_value = mock_response

    result = executor.close_position("LONG", "/ESM6:XCME")
    assert result.success is True


# ── cancel_order ─────────────────────────────────────────────────────

def test_cancel_order_success(executor, mock_account):
    """Cancelar orden pendiente."""
    result = executor.cancel_order("order-789")
    assert result.success is True
    mock_account.delete_order.assert_called_once_with(executor.session, "order-789")


def test_cancel_order_error(executor, mock_account):
    """Error al cancelar orden."""
    mock_account.delete_order.side_effect = Exception("Already filled")

    result = executor.cancel_order("order-789")
    assert result.success is False
    assert "Already filled" in result.error


# ── OrderResult serialización ─────────────────────────────────────────

def test_order_result_to_dict():
    r = OrderResult(
        success=True, order_id="abc", dry_run=True,
        details={"status": "ok"}, error=None,
    )
    d = r.to_dict()
    assert d["success"] is True
    assert d["order_id"] == "abc"
