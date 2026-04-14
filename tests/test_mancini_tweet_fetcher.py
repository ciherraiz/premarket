"""Tests para scripts/mancini/tweet_fetcher.py — SearchTimeline + auto-discovery."""

import json
import os
import sys
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from scripts.mancini.tweet_fetcher import (
    _load_cookies,
    _build_client,
    _parse_x_datetime,
    _discover_graphql_hash,
    _search_tweets,
    fetch_mancini_tweets,
    fetch_mancini_weekend_tweets,
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


# ── _discover_graphql_hash ────────────────────────────────────────────

def test_discover_hash_from_js_bundle(monkeypatch):
    """Descubre hash de SearchTimeline desde JS bundle de x.com."""
    monkeypatch.setattr("scripts.mancini.tweet_fetcher._hash_cache", {})

    mock_main_resp = MagicMock()
    mock_main_resp.text = (
        '<script src="https://abs.twimg.com/responsive-web/client-web/main.abc123.js"></script>'
    )

    mock_js_resp = MagicMock()
    mock_js_resp.text = (
        'e.exports={queryId:"FAKE_HASH_123",operationName:"SearchTimeline",'
        'operationType:"query"}'
    )

    with patch("scripts.mancini.tweet_fetcher.httpx.get") as mock_get:
        mock_get.side_effect = [mock_main_resp, mock_js_resp]
        result = _discover_graphql_hash("SearchTimeline")

    assert result == "FAKE_HASH_123"


def test_discover_hash_uses_cache(monkeypatch):
    """Usa cache si el hash ya fue descubierto."""
    monkeypatch.setattr(
        "scripts.mancini.tweet_fetcher._hash_cache",
        {"SearchTimeline": "CACHED_HASH"},
    )

    with patch("scripts.mancini.tweet_fetcher.httpx.get") as mock_get:
        result = _discover_graphql_hash("SearchTimeline")

    assert result == "CACHED_HASH"
    mock_get.assert_not_called()


def test_discover_hash_not_found(monkeypatch):
    """Lanza RuntimeError si no encuentra el hash en ningún bundle."""
    monkeypatch.setattr("scripts.mancini.tweet_fetcher._hash_cache", {})

    mock_main_resp = MagicMock()
    mock_main_resp.text = (
        '<script src="https://abs.twimg.com/responsive-web/client-web/main.abc.js"></script>'
    )

    mock_js_resp = MagicMock()
    mock_js_resp.text = "var x = 42; // no graphql here"

    with patch("scripts.mancini.tweet_fetcher.httpx.get") as mock_get:
        mock_get.side_effect = [mock_main_resp, mock_js_resp]
        with pytest.raises(RuntimeError, match="No se pudo descubrir"):
            _discover_graphql_hash("SearchTimeline")


# ── _search_tweets ────────────────────────────────────────────────────

def _make_search_response(tweets_data: list[dict]) -> dict:
    """Crea estructura de respuesta SearchTimeline."""
    entries = []
    for t in tweets_data:
        entries.append({"content": {
            "entryType": "TimelineTimelineItem",
            "itemContent": {"tweet_results": {"result": {"legacy": {
                "id_str": t["id"],
                "full_text": t["text"],
                "created_at": t["created_at"],
            }}}},
        }})
    return {
        "data": {"search_by_raw_query": {"search_timeline": {"timeline": {
            "instructions": [{"entries": entries}],
        }}}}
    }


def test_search_tweets_parses_results(monkeypatch):
    """Parsea tweets de la respuesta SearchTimeline."""
    monkeypatch.setattr(
        "scripts.mancini.tweet_fetcher._hash_cache",
        {"SearchTimeline": "HASH"},
    )

    mock_resp = MagicMock()
    mock_resp.json.return_value = _make_search_response([
        {"id": "1", "text": "ES plan today", "created_at": "Mon Apr 14 14:00:00 +0000 2026"},
        {"id": "2", "text": "Another tweet", "created_at": "Mon Apr 14 15:00:00 +0000 2026"},
    ])

    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp

    result = _search_tweets(mock_client, "from:AdamMancini4")
    assert len(result) == 2
    assert result[0]["text"] == "ES plan today"
    assert result[1]["text"] == "Another tweet"


def test_search_tweets_empty_response(monkeypatch):
    """Respuesta sin tweets devuelve lista vacía."""
    monkeypatch.setattr(
        "scripts.mancini.tweet_fetcher._hash_cache",
        {"SearchTimeline": "HASH"},
    )

    mock_resp = MagicMock()
    mock_resp.json.return_value = _make_search_response([])

    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp

    result = _search_tweets(mock_client, "from:AdamMancini4")
    assert result == []


# ── fetch_mancini_tweets ──────────────────────────────────────────────

def _today_x_date(hour=10) -> str:
    """Genera fecha en formato X para hoy."""
    now = datetime.now(ET).replace(hour=hour, minute=0, second=0, microsecond=0)
    utc = now.astimezone()
    return utc.strftime("%a %b %d %H:%M:%S +0000 %Y")


def _yesterday_x_date(hour=10) -> str:
    """Genera fecha en formato X para ayer."""
    now = datetime.now(ET).replace(hour=hour, minute=0, second=0, microsecond=0)
    yesterday = now - timedelta(days=1)
    utc = yesterday.astimezone()
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

    with patch("scripts.mancini.tweet_fetcher._build_client") as mock_build, \
         patch("scripts.mancini.tweet_fetcher._search_tweets") as mock_search:
        mock_search.return_value = [
            {"id": "1", "text": "ES plan today", "created_at": _today_x_date()},
            {"id": "2", "text": "old plan", "created_at": _yesterday_x_date()},
        ]
        mock_build.return_value = MagicMock()

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

    with patch("scripts.mancini.tweet_fetcher._build_client") as mock_build, \
         patch("scripts.mancini.tweet_fetcher._search_tweets") as mock_search:
        mock_search.return_value = []
        mock_build.return_value = MagicMock()

        result = fetch_mancini_tweets()

    assert result == []


def test_fetch_tweets_sync_is_alias():
    """fetch_tweets_sync es alias de fetch_mancini_tweets."""
    assert fetch_tweets_sync is fetch_mancini_tweets


# ── fetch_mancini_weekend_tweets ──────────────────────────────────────

def _saturday_x_date(hour=12) -> str:
    """Genera fecha en formato X para el sábado más reciente."""
    now = datetime.now(ET)
    days_since_sat = (now.weekday() + 2) % 7
    if now.weekday() == 5:
        days_since_sat = 0
    sat = now - timedelta(days=days_since_sat)
    sat = sat.replace(hour=hour, minute=0, second=0, microsecond=0)
    utc = sat.astimezone()
    return utc.strftime("%a %b %d %H:%M:%S +0000 %Y")


def test_fetch_weekend_tweets_filters_big_picture(tmp_path, monkeypatch):
    """Solo retorna tweets de fin de semana con 'Big Picture'."""
    cookies_file = tmp_path / "cookies.json"
    cookies_file.write_text(json.dumps([
        {"name": "ct0", "value": "abc"},
        {"name": "auth_token", "value": "xyz"},
    ]))
    monkeypatch.setattr(
        "scripts.mancini.tweet_fetcher.COOKIES_PATH", cookies_file
    )

    sat_date = _saturday_x_date()

    with patch("scripts.mancini.tweet_fetcher._build_client") as mock_build, \
         patch("scripts.mancini.tweet_fetcher._search_tweets") as mock_search:
        mock_search.return_value = [
            {"id": "1", "text": "Big Picture View: Bulls hold 6817", "created_at": sat_date},
            {"id": "2", "text": "Random weekend thought", "created_at": sat_date},
            {"id": "3", "text": "Plan Next Week: 6903 target", "created_at": sat_date},
        ]
        mock_build.return_value = MagicMock()

        result = fetch_mancini_weekend_tweets()

    assert len(result) == 2
    assert any("Big Picture" in t["text"] for t in result)
    assert any("Plan Next Week" in t["text"] for t in result)


def test_fetch_weekend_tweets_no_big_picture(tmp_path, monkeypatch):
    """Sin tweets Big Picture devuelve lista vacía."""
    cookies_file = tmp_path / "cookies.json"
    cookies_file.write_text(json.dumps([
        {"name": "ct0", "value": "abc"},
        {"name": "auth_token", "value": "xyz"},
    ]))
    monkeypatch.setattr(
        "scripts.mancini.tweet_fetcher.COOKIES_PATH", cookies_file
    )

    sat_date = _saturday_x_date()

    with patch("scripts.mancini.tweet_fetcher._build_client") as mock_build, \
         patch("scripts.mancini.tweet_fetcher._search_tweets") as mock_search:
        mock_search.return_value = [
            {"id": "1", "text": "Enjoying the weekend", "created_at": sat_date},
        ]
        mock_build.return_value = MagicMock()

        result = fetch_mancini_weekend_tweets()

    assert result == []
