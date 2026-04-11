"""Tests para scripts/mancini/tweet_fetcher.py"""

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from scripts.mancini.tweet_fetcher import (
    fetch_mancini_tweets,
    fetch_tweets_sync,
    _init_client,
    ET,
)


# ── Helpers ────────────────────────────────────────────────────────────

def _make_tweet(text: str, dt: datetime) -> MagicMock:
    tweet = MagicMock()
    tweet.id = "123456"
    tweet.full_text = text
    tweet.created_at_datetime = dt
    return tweet


def _today_dt(hour=10) -> datetime:
    """Devuelve un datetime de hoy en ET."""
    now = datetime.now(ET)
    return now.replace(hour=hour, minute=0, second=0, microsecond=0)


def _yesterday_dt(hour=10) -> datetime:
    """Devuelve un datetime de ayer en ET."""
    from datetime import timedelta
    return _today_dt(hour) - timedelta(days=1)


# ── _init_client ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_init_client_loads_cookies(tmp_path, monkeypatch):
    """Si cookies.json existe, lo carga."""
    cookies_file = tmp_path / "cookies.json"
    cookies_file.write_text('{"ct0": "abc", "auth_token": "xyz"}')
    monkeypatch.setattr(
        "scripts.mancini.tweet_fetcher.COOKIES_PATH", cookies_file
    )

    with patch("scripts.mancini.tweet_fetcher.Client") as MockClient:
        mock_instance = MagicMock()
        MockClient.return_value = mock_instance
        client = await _init_client()
        mock_instance.load_cookies.assert_called_once_with(str(cookies_file))


@pytest.mark.asyncio
async def test_init_client_raises_without_cookies_or_creds(tmp_path, monkeypatch):
    """Sin cookies ni credenciales lanza RuntimeError."""
    monkeypatch.setattr(
        "scripts.mancini.tweet_fetcher.COOKIES_PATH", tmp_path / "nope.json"
    )
    monkeypatch.delenv("X_USERNAME", raising=False)
    monkeypatch.delenv("X_PASSWORD", raising=False)

    with pytest.raises(RuntimeError, match="No se encontró cookies.json"):
        await _init_client()


@pytest.mark.asyncio
async def test_init_client_login_with_credentials(tmp_path, monkeypatch):
    """Con credenciales pero sin cookies, hace login y guarda cookies."""
    monkeypatch.setattr(
        "scripts.mancini.tweet_fetcher.COOKIES_PATH", tmp_path / "cookies.json"
    )
    monkeypatch.setenv("X_USERNAME", "user")
    monkeypatch.setenv("X_EMAIL", "email@test.com")
    monkeypatch.setenv("X_PASSWORD", "pass")

    with patch("scripts.mancini.tweet_fetcher.Client") as MockClient:
        mock_instance = MagicMock()
        mock_instance.login = AsyncMock()
        MockClient.return_value = mock_instance

        client = await _init_client()
        mock_instance.login.assert_called_once_with(
            auth_info_1="user",
            auth_info_2="email@test.com",
            password="pass",
        )
        mock_instance.save_cookies.assert_called_once()


# ── fetch_mancini_tweets ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_tweets_filters_today(monkeypatch, tmp_path):
    """Solo retorna tweets de hoy."""
    cookies_file = tmp_path / "cookies.json"
    cookies_file.write_text("{}")
    monkeypatch.setattr(
        "scripts.mancini.tweet_fetcher.COOKIES_PATH", cookies_file
    )

    today_tweet = _make_tweet("ES plan today", _today_dt())
    yesterday_tweet = _make_tweet("old plan", _yesterday_dt())

    mock_user = MagicMock()
    mock_user.id = "999"

    with patch("scripts.mancini.tweet_fetcher.Client") as MockClient:
        mock_instance = MagicMock()
        mock_instance.load_cookies = MagicMock()
        mock_instance.get_user_by_screen_name = AsyncMock(return_value=mock_user)
        mock_instance.get_user_tweets = AsyncMock(
            return_value=[today_tweet, yesterday_tweet]
        )
        MockClient.return_value = mock_instance

        result = await fetch_mancini_tweets()

    assert len(result) == 1
    assert result[0]["text"] == "ES plan today"
    assert "id" in result[0]
    assert "created_at" in result[0]


@pytest.mark.asyncio
async def test_fetch_tweets_empty_timeline(monkeypatch, tmp_path):
    """Timeline vacío devuelve lista vacía."""
    cookies_file = tmp_path / "cookies.json"
    cookies_file.write_text("{}")
    monkeypatch.setattr(
        "scripts.mancini.tweet_fetcher.COOKIES_PATH", cookies_file
    )

    mock_user = MagicMock()
    mock_user.id = "999"

    with patch("scripts.mancini.tweet_fetcher.Client") as MockClient:
        mock_instance = MagicMock()
        mock_instance.load_cookies = MagicMock()
        mock_instance.get_user_by_screen_name = AsyncMock(return_value=mock_user)
        mock_instance.get_user_tweets = AsyncMock(return_value=[])
        MockClient.return_value = mock_instance

        result = await fetch_mancini_tweets()

    assert result == []


@pytest.mark.asyncio
async def test_fetch_tweets_multiple_today(monkeypatch, tmp_path):
    """Retorna múltiples tweets de hoy."""
    cookies_file = tmp_path / "cookies.json"
    cookies_file.write_text("{}")
    monkeypatch.setattr(
        "scripts.mancini.tweet_fetcher.COOKIES_PATH", cookies_file
    )

    tweets = [
        _make_tweet("tweet 1", _today_dt(9)),
        _make_tweet("tweet 2", _today_dt(10)),
        _make_tweet("old", _yesterday_dt()),
    ]

    mock_user = MagicMock()
    mock_user.id = "999"

    with patch("scripts.mancini.tweet_fetcher.Client") as MockClient:
        mock_instance = MagicMock()
        mock_instance.load_cookies = MagicMock()
        mock_instance.get_user_by_screen_name = AsyncMock(return_value=mock_user)
        mock_instance.get_user_tweets = AsyncMock(return_value=tweets)
        MockClient.return_value = mock_instance

        result = await fetch_mancini_tweets()

    assert len(result) == 2


# ── fetch_tweets_sync ─────────────────────────────────────────────────

def test_fetch_tweets_sync_wrapper(monkeypatch, tmp_path):
    """El wrapper síncrono funciona."""
    cookies_file = tmp_path / "cookies.json"
    cookies_file.write_text("{}")
    monkeypatch.setattr(
        "scripts.mancini.tweet_fetcher.COOKIES_PATH", cookies_file
    )

    mock_user = MagicMock()
    mock_user.id = "999"
    today_tweet = _make_tweet("sync test", _today_dt())

    with patch("scripts.mancini.tweet_fetcher.Client") as MockClient:
        mock_instance = MagicMock()
        mock_instance.load_cookies = MagicMock()
        mock_instance.get_user_by_screen_name = AsyncMock(return_value=mock_user)
        mock_instance.get_user_tweets = AsyncMock(return_value=[today_tweet])
        MockClient.return_value = mock_instance

        result = fetch_tweets_sync()

    assert len(result) == 1
    assert result[0]["text"] == "sync test"
