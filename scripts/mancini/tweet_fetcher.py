"""
Obtiene tweets recientes de @AdamMancini4 usando httpx + cookies de X.

Requiere cookies de sesión X exportadas con Cookie-Editor (Chrome):
  X_COOKIES_FILE=cookies.json  (por defecto en raíz del proyecto)
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv

# Buscar .env en la raíz del proyecto (funciona desde worktrees y subcarpetas)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_env_path = _PROJECT_ROOT / ".env"
if not _env_path.exists() and ".claude" in str(_PROJECT_ROOT):
    _env_path = Path(str(_PROJECT_ROOT).split(".claude")[0]) / ".env"
load_dotenv(_env_path, override=True)

ET = ZoneInfo("America/New_York")
MANCINI_SCREEN_NAME = "AdamMancini4"
def _resolve_cookies_path() -> Path:
    """Busca cookies.json en la raíz del proyecto o en el repo principal."""
    env_path = os.getenv("X_COOKIES_FILE")
    if env_path:
        return Path(env_path)
    # Buscar en la raíz del proyecto (funciona en worktrees)
    candidate = _PROJECT_ROOT / "cookies.json"
    if candidate.exists():
        return candidate
    # Si estamos en un worktree (.claude/worktrees/X), buscar en repo principal
    main_root = _PROJECT_ROOT
    if ".claude" in str(main_root):
        main_root = Path(str(main_root).split(".claude")[0])
        candidate = main_root / "cookies.json"
        if candidate.exists():
            return candidate
    return _PROJECT_ROOT / "cookies.json"  # default, fallará con error claro


COOKIES_PATH = _resolve_cookies_path()

# Bearer token público de X (embebido en el JS de x.com)
BEARER_TOKEN = (
    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs"
    "%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)

GRAPHQL_URL = "https://x.com/i/api/graphql"

# Features requeridas por la API GraphQL de X
USER_FEATURES = {
    "hidden_profile_subscriptions_enabled": True,
    "rweb_tipjar_consumption_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "subscriptions_verification_info_is_identity_verified_enabled": True,
    "subscriptions_verification_info_verified_since_enabled": True,
    "highlights_tweets_tab_ui_enabled": True,
    "responsive_web_twitter_article_notes_tab_enabled": True,
    "subscriptions_feature_can_gift_premium": True,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "responsive_web_graphql_timeline_navigation_enabled": True,
}

TWEET_FEATURES = {
    "rweb_tipjar_consumption_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "articles_preview_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "creator_subscriptions_quote_tweet_preview_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "rweb_video_timestamps_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
}


def _load_cookies() -> dict[str, str]:
    """Carga cookies de sesión desde Cookie-Editor JSON."""
    if not COOKIES_PATH.exists():
        raise RuntimeError(
            f"No se encontró {COOKIES_PATH}. "
            "Exporta cookies de x.com con Cookie-Editor (Chrome) → JSON."
        )

    raw = json.loads(COOKIES_PATH.read_text(encoding="utf-8"))

    # Cookie-Editor exporta [{name, value, ...}], convertir a {name: value}
    if isinstance(raw, list):
        return {c["name"]: c["value"] for c in raw}
    return raw


def _build_client(cookies: dict[str, str]) -> httpx.Client:
    """Crea cliente httpx con headers y cookies de X."""
    ct0 = cookies.get("ct0", "")
    auth_token = cookies.get("auth_token", "")

    if not ct0 or not auth_token:
        raise RuntimeError(
            "Cookies incompletas: se necesitan 'ct0' y 'auth_token'. "
            "Asegúrate de estar logueado en x.com antes de exportar cookies."
        )

    headers = {
        "Authorization": f"Bearer {BEARER_TOKEN}",
        "X-Csrf-Token": ct0,
        "Content-Type": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Referer": f"https://x.com/{MANCINI_SCREEN_NAME}",
        "X-Twitter-Active-User": "yes",
        "X-Twitter-Auth-Type": "OAuth2Session",
        "X-Twitter-Client-Language": "en",
    }

    client = httpx.Client(
        headers=headers,
        cookies=httpx.Cookies({
            "ct0": ct0,
            "auth_token": auth_token,
        }),
        timeout=30,
        follow_redirects=True,
    )
    return client


def _get_user_id(client: httpx.Client, screen_name: str) -> str:
    """Obtiene el user ID de X a partir del screen name."""
    variables = json.dumps({
        "screen_name": screen_name,
        "withSafetyModeUserFields": True,
    })
    features = json.dumps(USER_FEATURES)

    resp = client.get(
        f"{GRAPHQL_URL}/xc8f1g7BYqr6VTzTbvNlGw/UserByScreenName",
        params={"variables": variables, "features": features},
    )
    resp.raise_for_status()
    data = resp.json()

    try:
        return data["data"]["user"]["result"]["rest_id"]
    except (KeyError, TypeError) as e:
        raise RuntimeError(
            f"No se pudo obtener user ID para @{screen_name}. "
            "Las cookies pueden haber expirado."
        ) from e


def _get_user_tweets(
    client: httpx.Client, user_id: str, count: int = 20
) -> list[dict]:
    """Obtiene tweets del timeline de un usuario vía GraphQL."""
    variables = json.dumps({
        "userId": user_id,
        "count": count,
        "includePromotedContent": False,
        "withQuickPromoteEligibilityTweetFields": True,
        "withVoice": True,
        "withV2Timeline": True,
    })
    features = json.dumps(TWEET_FEATURES)

    resp = client.get(
        f"{GRAPHQL_URL}/E3opETHurmVJflFsUBVuUQ/UserTweets",
        params={"variables": variables, "features": features},
    )
    resp.raise_for_status()
    data = resp.json()

    tweets = []
    try:
        instructions = (
            data["data"]["user"]["result"]["timeline_v2"]
            ["timeline"]["instructions"]
        )
        for instruction in instructions:
            if instruction.get("type") != "TimelineAddEntries":
                continue
            for entry in instruction.get("entries", []):
                content = entry.get("content", {})
                if content.get("entryType") != "TimelineTimelineItem":
                    continue
                result = (
                    content.get("itemContent", {})
                    .get("tweet_results", {})
                    .get("result", {})
                )
                legacy = result.get("legacy", {})
                if not legacy.get("full_text"):
                    continue
                tweets.append({
                    "id": legacy.get("id_str", result.get("rest_id", "")),
                    "text": legacy["full_text"],
                    "created_at": legacy.get("created_at", ""),
                })
    except (KeyError, TypeError):
        pass

    return tweets


def _parse_x_datetime(date_str: str) -> datetime | None:
    """Parsea el formato de fecha de X: 'Wed Oct 10 20:19:24 +0000 2018'."""
    try:
        return datetime.strptime(date_str, "%a %b %d %H:%M:%S %z %Y")
    except (ValueError, TypeError):
        return None


def fetch_mancini_tweets(max_tweets: int = 20) -> list[dict]:
    """Obtiene tweets recientes de Mancini, filtrados a hoy (ET)."""
    cookies = _load_cookies()
    client = _build_client(cookies)

    user_id = _get_user_id(client, MANCINI_SCREEN_NAME)
    raw_tweets = _get_user_tweets(client, user_id, count=max_tweets)

    today = datetime.now(ET).strftime("%Y-%m-%d")
    result = []

    for tweet in raw_tweets:
        dt = _parse_x_datetime(tweet["created_at"])
        if dt is None:
            continue
        tweet_date = dt.astimezone(ET).strftime("%Y-%m-%d")
        if tweet_date != today:
            continue
        result.append({
            "id": tweet["id"],
            "text": tweet["text"],
            "created_at": dt.isoformat(),
        })

    return result


# Alias para compatibilidad con el skill (era async, ahora es sync)
fetch_tweets_sync = fetch_mancini_tweets


if __name__ == "__main__":
    tweets = fetch_tweets_sync()
    print(f"Encontrados {len(tweets)} tweets de hoy")
    for t in tweets:
        print(f"  [{t['created_at']}] {t['text'][:80]}...")
