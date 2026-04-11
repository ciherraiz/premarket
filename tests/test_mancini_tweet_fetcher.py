"""Tests para scripts/mancini/tweet_fetcher.py — httpx + cookies de X."""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from scripts.mancini.tweet_fetcher import (
    _load_cookies,
    _build_client,
    _parse_x_datetime,
    fetch_mancini_tweets,
    fetch_tweets_sync,
    ET,
)


# ── _load_cookies ──────────────────────────────────────────────────────

def test_load_cookies_list_format(tmp_path, monkeypatch):
    """Cookie-Editor exporta lista de objetos [{name, value, ...}]."""
    cookies_file = tmp_path / "cookies.json"
    cookies_file.write_text(json.dumps([
        {"name": "ct0", "value": "abc123", "domain": ".x.com"},
        {"name": "auth_token", "value": "xyz789", "domain": ".x.com"},
    ]))
    monkeypatch.setattr(
        "scripts.mancini.tweet_fetcher.COOKIES_PATH", cookies_file
    )
    result = _load_cookies()
    assert result == {"ct0": "abc123", "auth_token": "xyz789"}


def test_load_cookies_dict_format(tmp_path, monkeypatch):
    """Formato dict simple {name: value}."""
    cookies_file = tmp_path / "cookies.json"
    cookies_file.write_text(json.dumps({"ct0": "abc", "auth_token": "xyz"}))
    monkeypatch.setattr(
        "scripts.mancini.tweet_fetcher.COOKIES_PATH", cookies_file
    )
    result = _load_cookies()
    assert result["ct0"] == "abc"
    assert result["auth_token"] == "xyz"


def test_load_cookies_missing_file(tmp_path, monkeypatch):
    """Sin cookies.json lanza RuntimeError."""
    monkeypatch.setattr(
        "scripts.mancini.tweet_fetcher.COOKIES_PATH", tmp_path / "nope.json"
    )
    with pytest.raises(RuntimeError, match="No se encontró"):
        _load_cookies()


# ── _build_client ──────────────────────────────────────────────────────

def test_build_client_ok():
    """Crea cliente httpx con cookies válidas."""
    client = _build_client({"ct0": "token123", "auth_token": "auth456"})
    assert client is not None
    assert "Bearer" in client.headers["authorization"]
    assert client.headers["x-csrf-token"] == "token123"


def test_build_client_missing_ct0():
    """Sin ct0 lanza RuntimeError."""
    with pytest.raises(RuntimeError, match="ct0"):
        _build_client({"auth_token": "abc"})


def test_build_client_missing_auth_token():
    """Sin auth_token lanza RuntimeError."""
    with pytest.raises(RuntimeError, match="auth_token"):
        _build_client({"ct0": "abc"})


# ── _parse_x_datetime ─────────────────────────────────────────────────

def test_parse_x_datetime_valid():
    """Parsea formato de fecha de X correctamente."""
    dt = _parse_x_datetime("Fri Apr 11 14:44:47 +0000 2026")
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 4
    assert dt.day == 11


def test_parse_x_datetime_invalid():
    """Fecha inválida retorna None."""
    assert _parse_x_datetime("invalid") is None
    assert _parse_x_datetime("") is None
    assert _parse_x_datetime(None) is None


# ── fetch_mancini_tweets ──────────────────────────────────────────────

def _today_x_date(hour=10) -> str:
    """Genera fecha en formato X para hoy."""
    now = datetime.now(ET).replace(hour=hour, minute=0, second=0, microsecond=0)
    utc = now.astimezone(ZoneInfo("UTC"))
    return utc.strftime("%a %b %d %H:%M:%S +0000 %Y")


def _yesterday_x_date(hour=10) -> str:
    """Genera fecha en formato X para ayer."""
    now = datetime.now(ET).replace(hour=hour, minute=0, second=0, microsecond=0)
    yesterday = now - timedelta(days=1)
    utc = yesterday.astimezone(ZoneInfo("UTC"))
    return utc.strftime("%a %b %d %H:%M:%S +0000 %Y")


def test_fetch_tweets_filters_today(tmp_path, monkeypatch):
    """Solo retorna tweets de hoy."""
    cookies_file = tmp_path / "cookies.json"
    cookies_file.write_text(json.dumps([
        {"name": "ct0", "value": "abc"},
        {"name": "auth_token", "value": "xyz"},
    ]))
    monkeypatch.setattr(
        "scripts.mancini.tweet_fetcher.COOKIES_PATH", cookies_file
    )

    mock_user_resp = MagicMock()
    mock_user_resp.json.return_value = {
        "data": {"user": {"result": {"rest_id": "12345"}}}
    }

    mock_tweets_resp = MagicMock()
    mock_tweets_resp.json.return_value = {
        "data": {"user": {"result": {"timeline_v2": {"timeline": {"instructions": [{
            "type": "TimelineAddEntries",
            "entries": [
                {"content": {
                    "entryType": "TimelineTimelineItem",
                    "itemContent": {"tweet_results": {"result": {"legacy": {
                        "id_str": "1", "full_text": "ES plan today",
                        "created_at": _today_x_date(),
                    }}}},
                }},
                {"content": {
                    "entryType": "TimelineTimelineItem",
                    "itemContent": {"tweet_results": {"result": {"legacy": {
                        "id_str": "2", "full_text": "old plan",
                        "created_at": _yesterday_x_date(),
                    }}}},
                }},
            ],
        }]}}}}}
    }

    with patch("scripts.mancini.tweet_fetcher._build_client") as mock_build:
        mock_client = MagicMock()
        mock_client.get.side_effect = [mock_user_resp, mock_tweets_resp]
        mock_build.return_value = mock_client

        result = fetch_mancini_tweets()

    assert len(result) == 1
    assert result[0]["text"] == "ES plan today"
    assert "id" in result[0]
    assert "created_at" in result[0]


def test_fetch_tweets_empty_timeline(tmp_path, monkeypatch):
    """Timeline sin tweets de hoy devuelve lista vacía."""
    cookies_file = tmp_path / "cookies.json"
    cookies_file.write_text(json.dumps([
        {"name": "ct0", "value": "abc"},
        {"name": "auth_token", "value": "xyz"},
    ]))
    monkeypatch.setattr(
        "scripts.mancini.tweet_fetcher.COOKIES_PATH", cookies_file
    )

    mock_user_resp = MagicMock()
    mock_user_resp.json.return_value = {
        "data": {"user": {"result": {"rest_id": "12345"}}}
    }

    mock_tweets_resp = MagicMock()
    mock_tweets_resp.json.return_value = {
        "data": {"user": {"result": {"timeline_v2": {"timeline": {"instructions": [{
            "type": "TimelineAddEntries", "entries": [],
        }]}}}}}
    }

    with patch("scripts.mancini.tweet_fetcher._build_client") as mock_build:
        mock_client = MagicMock()
        mock_client.get.side_effect = [mock_user_resp, mock_tweets_resp]
        mock_build.return_value = mock_client

        result = fetch_mancini_tweets()

    assert result == []


def test_fetch_tweets_sync_is_alias():
    """fetch_tweets_sync es alias de fetch_mancini_tweets."""
    assert fetch_tweets_sync is fetch_mancini_tweets
