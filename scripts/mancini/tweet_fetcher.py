"""
Obtiene tweets recientes de @AdamMancini4 usando twikit.

Requiere cookies de sesión X en .env:
  X_COOKIES_FILE=cookies.json  (generado tras primer login)
  -- o bien login directo --
  X_USERNAME, X_EMAIL, X_PASSWORD
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from twikit import Client

load_dotenv()

ET = ZoneInfo("America/New_York")
MANCINI_SCREEN_NAME = "AdamMancini4"
COOKIES_PATH = Path(os.getenv("X_COOKIES_FILE", "cookies.json"))


async def _init_client() -> Client:
    """Crea cliente twikit autenticado vía cookies o login."""
    client = Client("en-US")

    if COOKIES_PATH.exists():
        client.load_cookies(str(COOKIES_PATH))
        return client

    # Login con credenciales si no hay cookies
    username = os.getenv("X_USERNAME")
    email = os.getenv("X_EMAIL")
    password = os.getenv("X_PASSWORD")

    if not all([username, password]):
        raise RuntimeError(
            "No se encontró cookies.json ni credenciales X. "
            "Configura X_COOKIES_FILE o X_USERNAME + X_PASSWORD en .env"
        )

    await client.login(
        auth_info_1=username,
        auth_info_2=email,
        password=password,
    )
    client.save_cookies(str(COOKIES_PATH))
    return client


async def fetch_mancini_tweets(max_tweets: int = 20) -> list[dict]:
    """Obtiene tweets recientes de Mancini, filtrados a hoy (ET)."""
    client = await _init_client()

    user = await client.get_user_by_screen_name(MANCINI_SCREEN_NAME)
    tweets = await client.get_user_tweets(user.id, "Tweets", count=max_tweets)

    today = datetime.now(ET).strftime("%Y-%m-%d")
    result = []

    for tweet in tweets:
        # created_at_datetime es datetime aware
        tweet_date = tweet.created_at_datetime.astimezone(ET).strftime("%Y-%m-%d")
        if tweet_date != today:
            continue
        result.append({
            "id": tweet.id,
            "text": tweet.full_text,
            "created_at": tweet.created_at_datetime.isoformat(),
        })

    return result


def fetch_tweets_sync(max_tweets: int = 20) -> list[dict]:
    """Wrapper síncrono para usar desde CLI y skills."""
    return asyncio.run(fetch_mancini_tweets(max_tweets))


if __name__ == "__main__":
    tweets = fetch_tweets_sync()
    print(f"Encontrados {len(tweets)} tweets de hoy")
    for t in tweets:
        print(f"  [{t['created_at']}] {t['text'][:80]}...")
