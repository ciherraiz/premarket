"""
Tests para fetch_es_quote() con TastyTradeClient mockeado.

No se realizan llamadas reales a TastyTrade — TastyTradeClient se parchea
en el namespace de scripts.fetch_market_data para simular todos los casos
definidos en specs/fetch_tastytrade_sdk.md.
"""

import sys
import os
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.fetch_market_data import fetch_es_quote


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_client(last=5100.0, mark=5100.5, bid=5100.0, ask=5101.0, status="OK"):
    """Crea un mock de TastyTradeClient con get_future_quote configurado."""
    mock = MagicMock()
    mock.get_future_quote.return_value = {
        "symbol": "/ESM5:XCME",
        "last": last,
        "mark": mark,
        "bid": bid,
        "ask": ask,
        "status": status,
    }
    return mock


def _patch_client(mock_instance=None, side_effect=None):
    """Context manager que parchea TastyTradeClient en fetch_market_data."""
    p = patch("scripts.fetch_market_data.TastyTradeClient")
    mock_cls = p.start()
    if side_effect:
        mock_cls.side_effect = side_effect
    elif mock_instance:
        mock_cls.return_value = mock_instance
    return p, mock_cls


# ---------------------------------------------------------------------------
# Casos OK
# ---------------------------------------------------------------------------

def test_quote_ok_con_last():
    """Cuando last > 0, es_premarket debe ser el last."""
    with patch("scripts.fetch_market_data.TastyTradeClient") as MockClient:
        MockClient.return_value = _mock_client(last=5100.0, mark=5100.5)
        result = fetch_es_quote()

    assert result["status"] == "OK"
    assert result["es_premarket"] == 5100.0


def test_quote_ok_sin_last_usa_mark():
    """Cuando last=0, es_premarket debe ser el mark (bid+ask)/2."""
    with patch("scripts.fetch_market_data.TastyTradeClient") as MockClient:
        MockClient.return_value = _mock_client(last=0, mark=5100.5)
        result = fetch_es_quote()

    assert result["status"] == "OK"
    assert result["es_premarket"] == 5100.5


def test_resultado_contiene_fecha():
    """El resultado siempre debe incluir el campo fecha."""
    with patch("scripts.fetch_market_data.TastyTradeClient") as MockClient:
        MockClient.return_value = _mock_client()
        result = fetch_es_quote()

    assert "fecha" in result
    assert result["fecha"] is not None


# ---------------------------------------------------------------------------
# Casos de error en credenciales / autenticación
# ---------------------------------------------------------------------------

def test_credenciales_ausentes():
    """EnvironmentError en __init__ → MISSING_DATA, es_premarket None."""
    with patch("scripts.fetch_market_data.TastyTradeClient") as MockClient:
        MockClient.side_effect = EnvironmentError("TT_USERNAME no configurado")
        result = fetch_es_quote()

    assert result["status"] == "MISSING_DATA"
    assert result["es_premarket"] is None


def test_error_autenticacion():
    """Excepción genérica en __init__ (auth fallida) → ERROR."""
    with patch("scripts.fetch_market_data.TastyTradeClient") as MockClient:
        MockClient.side_effect = Exception("401 Unauthorized")
        result = fetch_es_quote()

    assert result["status"] == "ERROR"
    assert result["es_premarket"] is None


# ---------------------------------------------------------------------------
# Casos de precio inválido
# ---------------------------------------------------------------------------

def test_last_cero_mark_cero():
    """Cuando last=0 y mark=0 no hay precio válido → ERROR."""
    with patch("scripts.fetch_market_data.TastyTradeClient") as MockClient:
        MockClient.return_value = _mock_client(last=0, mark=0)
        result = fetch_es_quote()

    assert result["status"] == "ERROR"
    assert result["es_premarket"] is None


def test_last_none_mark_valido():
    """None en last se trata igual que 0 → fallback a mark."""
    with patch("scripts.fetch_market_data.TastyTradeClient") as MockClient:
        MockClient.return_value = _mock_client(last=None, mark=5099.75)
        result = fetch_es_quote()

    assert result["status"] == "OK"
    assert result["es_premarket"] == 5099.75


# ---------------------------------------------------------------------------
# Casos de status propagado desde get_future_quote
# ---------------------------------------------------------------------------

def test_get_future_quote_status_error():
    """Si get_future_quote devuelve status ERROR, fetch_es_quote lo propaga."""
    with patch("scripts.fetch_market_data.TastyTradeClient") as MockClient:
        MockClient.return_value = _mock_client(status="ERROR")
        result = fetch_es_quote()

    assert result["status"] == "ERROR"
    assert result["es_premarket"] is None


def test_get_future_quote_status_missing():
    """Si get_future_quote devuelve MISSING_DATA, fetch_es_quote lo propaga."""
    with patch("scripts.fetch_market_data.TastyTradeClient") as MockClient:
        MockClient.return_value = _mock_client(status="MISSING_DATA")
        result = fetch_es_quote()

    assert result["status"] == "MISSING_DATA"
    assert result["es_premarket"] is None


# ---------------------------------------------------------------------------
# Caso SDK no disponible
# ---------------------------------------------------------------------------

def test_sdk_no_disponible():
    """Cuando TastyTradeClient es None (SDK no instalado) → MISSING_DATA."""
    with patch("scripts.fetch_market_data.TastyTradeClient", None):
        result = fetch_es_quote()

    assert result["status"] == "MISSING_DATA"
    assert result["es_premarket"] is None
