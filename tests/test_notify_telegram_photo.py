"""Tests para send_telegram_photo en scripts/notify_telegram.py."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch, MagicMock

import pytest

from scripts.notify_telegram import send_telegram_photo


PNG_BYTES = b"\x89PNG\r\n\x1a\nfake_image_data"


class TestSendTelegramPhoto:
    @patch("scripts.notify_telegram.httpx.post")
    @patch.dict("os.environ", {
        "TELEGRAM_BOT_TOKEN": "test-token",
        "TELEGRAM_CHAT_ID": "123456",
    })
    def test_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_post.return_value = mock_resp

        result = send_telegram_photo(PNG_BYTES)
        assert result is True
        mock_post.assert_called_once()

        # Verificar que se envió como multipart con photo
        call_kwargs = mock_post.call_args
        assert "files" in call_kwargs.kwargs
        assert "data" in call_kwargs.kwargs
        assert call_kwargs.kwargs["data"]["chat_id"] == "123456"

    @patch.dict("os.environ", {}, clear=True)
    def test_no_credentials(self):
        result = send_telegram_photo(PNG_BYTES)
        assert result is False

    @patch("scripts.notify_telegram.httpx.post")
    @patch.dict("os.environ", {
        "TELEGRAM_BOT_TOKEN": "test-token",
        "TELEGRAM_CHAT_ID": "123456",
    })
    def test_with_caption(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_post.return_value = mock_resp

        result = send_telegram_photo(PNG_BYTES, caption="Test chart")
        assert result is True

        call_kwargs = mock_post.call_args
        assert call_kwargs.kwargs["data"]["caption"] == "Test chart"

    @patch("scripts.notify_telegram.httpx.post")
    @patch.dict("os.environ", {
        "TELEGRAM_BOT_TOKEN": "test-token",
        "TELEGRAM_CHAT_ID": "123456",
    })
    def test_api_error(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.is_success = False
        mock_resp.status_code = 400
        mock_resp.text = "Bad Request"
        mock_post.return_value = mock_resp

        result = send_telegram_photo(PNG_BYTES)
        assert result is False
