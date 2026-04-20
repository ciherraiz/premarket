"""
Obtiene tweets recientes de @AdamMancini4 usando httpx + cookies de X.

Usa el endpoint SearchTimeline (POST) que devuelve resultados en tiempo real,
a diferencia de UserTweets que tiene cache de ~1 hora.

Los hashes de los endpoints GraphQL se auto-descubren desde el JS de x.com
para sobrevivir las rotaciones periódicas de X.

Requiere cookies de sesión X exportadas con Cookie-Editor (Chrome):
  X_COOKIES_FILE=cookies.json  (por defecto en raíz del proyecto)
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
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
    candidate = _PROJECT_ROOT / "cookies.json"
    if candidate.exists():
        return candidate
    main_root = _PROJECT_ROOT
    if ".claude" in str(main_root):
        main_root = Path(str(main_root).split(".claude")[0])
        candidate = main_root / "cookies.json"
        if candidate.exists():
            return candidate
    return _PROJECT_ROOT / "cookies.json"


COOKIES_PATH = _resolve_cookies_path()

# Bearer token público de X (embebido en el JS de x.com)
BEARER_TOKEN = (
    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs"
    "%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)

GRAPHQL_URL = "https://x.com/i/api/graphql"

# Features requeridas para SearchTimeline
SEARCH_FEATURES = {
    "rweb_video_screen_enabled": False,
    "rweb_cashtags_enabled": True,
    "profile_label_improvements_pcf_label_in_post_enabled": True,
    "responsive_web_profile_redirect_enabled": True,
    "rweb_tipjar_consumption_enabled": True,
    "verified_phone_label_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "premium_content_api_read_enabled": False,
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
    "responsive_web_grok_analyze_post_followups_enabled": False,
    "responsive_web_jetfuel_frame": False,
    "responsive_web_grok_share_attachment_enabled": False,
    "responsive_web_grok_annotations_enabled": False,
    "articles_preview_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "content_disclosure_indicator_enabled": False,
    "content_disclosure_ai_generated_indicator_enabled": False,
    "responsive_web_grok_show_grok_translated_post": False,
    "responsive_web_grok_analysis_button_from_backend": False,
    "post_ctas_fetch_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "responsive_web_grok_image_annotation_enabled": False,
    "responsive_web_grok_imagine_annotation_enabled": False,
    "responsive_web_grok_community_note_auto_translation_is_enabled": False,
    "responsive_web_enhance_cards_enabled": False,
}

SEARCH_FIELD_TOGGLES = {
    "withArticleRichContentState": True,
    "withArticlePlainText": False,
    "withGrokAnalyze": False,
    "withDisallowedReplyControls": False,
}

# Cache de hashes descubiertos (válido durante la vida del proceso)
_hash_cache: dict[str, str] = {}


def _load_cookies() -> dict[str, str]:
    """Carga cookies de sesión desde Cookie-Editor JSON."""
    if not COOKIES_PATH.exists():
        raise RuntimeError(
            f"No se encontró {COOKIES_PATH}. "
            "Exporta cookies de x.com con Cookie-Editor (Chrome) → JSON."
        )

    raw = json.loads(COOKIES_PATH.read_text(encoding="utf-8"))

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
        "Referer": f"https://x.com/search?q=from%3A{MANCINI_SCREEN_NAME}&f=live",
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


def _discover_graphql_hash(operation: str) -> str:
    """Auto-descubre el queryId actual de un endpoint GraphQL de X.

    Extrae los hashes de los JS bundles de x.com. Los hashes rotan
    con cada despliegue de X, así que no se pueden hardcodear.
    """
    if operation in _hash_cache:
        return _hash_cache[operation]

    resp = httpx.get(
        "https://x.com",
        follow_redirects=True,
        timeout=15,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        },
    )

    js_urls = re.findall(
        r"https://abs\.twimg\.com/responsive-web/client-web[^\"]+\.js",
        resp.text,
    )

    pattern = re.compile(
        rf'queryId:"([^"]+)",operationName:"{re.escape(operation)}"'
    )

    for url in js_urls:
        try:
            js = httpx.get(url, timeout=15).text
            match = pattern.search(js)
            if match:
                qid = match.group(1)
                _hash_cache[operation] = qid
                return qid
        except httpx.HTTPError:
            continue

    raise RuntimeError(
        f"No se pudo descubrir el hash para '{operation}'. "
        "X puede haber cambiado la estructura de sus bundles JS."
    )


def _search_tweets(
    client: httpx.Client, query: str, count: int = 20
) -> list[dict]:
    """Busca tweets vía SearchTimeline (POST, tiempo real)."""
    qid = _discover_graphql_hash("SearchTimeline")

    body = {
        "variables": {
            "rawQuery": query,
            "count": count,
            "querySource": "typed_query",
            "product": "Latest",
        },
        "features": SEARCH_FEATURES,
        "fieldToggles": SEARCH_FIELD_TOGGLES,
    }

    resp = client.post(f"{GRAPHQL_URL}/{qid}/SearchTimeline", json=body)
    resp.raise_for_status()
    data = resp.json()

    tweets = []
    try:
        instructions = (
            data["data"]["search_by_raw_query"]["search_timeline"]
            ["timeline"]["instructions"]
        )
        for instruction in instructions:
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
    except (KeyError, TypeError) as e:
        raise RuntimeError(f"Error parsing X Search response: {e}") from e

    return tweets


def _parse_x_datetime(date_str: str) -> datetime | None:
    """Parsea el formato de fecha de X: 'Wed Oct 10 20:19:24 +0000 2018'."""
    try:
        return datetime.strptime(date_str, "%a %b %d %H:%M:%S %z %Y")
    except (ValueError, TypeError):
        return None


def fetch_mancini_tweets(max_tweets: int = 20) -> list[dict]:
    """Obtiene tweets recientes de Mancini desde el cierre RTH anterior.

    Ventana de búsqueda: desde las 16:00 ET del día anterior hasta ahora.
    Mancini publica el plan de la siguiente sesión después del cierre (16:00 ET),
    por ejemplo el domingo por la noche para el lunes. Este filtro captura tanto
    tweets post-cierre del día anterior como tweets del día actual.
    """
    cookies = _load_cookies()
    client = _build_client(cookies)

    raw_tweets = _search_tweets(
        client, f"from:{MANCINI_SCREEN_NAME}", count=max_tweets
    )

    # Ventana: desde 16:00 ET del día anterior
    now_et = datetime.now(ET)
    yesterday = now_et - timedelta(days=1)
    cutoff = yesterday.replace(hour=16, minute=0, second=0, microsecond=0)

    result = []

    for tweet in raw_tweets:
        dt = _parse_x_datetime(tweet["created_at"])
        if dt is None:
            continue
        dt_et = dt.astimezone(ET)
        if dt_et < cutoff:
            continue
        result.append({
            "id": tweet["id"],
            "text": tweet["text"],
            "created_at": dt.isoformat(),
        })

    return result


def fetch_mancini_weekend_tweets(max_tweets: int = 40) -> list[dict]:
    """Obtiene tweets del fin de semana que contengan 'Big Picture'."""
    cookies = _load_cookies()
    client = _build_client(cookies)

    raw_tweets = _search_tweets(
        client, f"from:{MANCINI_SCREEN_NAME}", count=max_tweets
    )

    now = datetime.now(ET)
    weekday = now.weekday()
    if weekday == 5:  # sábado
        weekend_dates = {now.strftime("%Y-%m-%d")}
    elif weekday == 6:  # domingo
        from datetime import timedelta
        weekend_dates = {
            (now - timedelta(days=1)).strftime("%Y-%m-%d"),
            now.strftime("%Y-%m-%d"),
        }
    else:
        from datetime import timedelta
        days_since_saturday = weekday + 2
        sat = now - timedelta(days=days_since_saturday)
        sun = sat + timedelta(days=1)
        weekend_dates = {sat.strftime("%Y-%m-%d"), sun.strftime("%Y-%m-%d")}

    result = []
    for tweet in raw_tweets:
        dt = _parse_x_datetime(tweet["created_at"])
        if dt is None:
            continue
        tweet_date = dt.astimezone(ET).strftime("%Y-%m-%d")
        if tweet_date not in weekend_dates:
            continue
        text_lower = tweet["text"].lower()
        if "big picture" in text_lower or "plan next week" in text_lower:
            result.append({
                "id": tweet["id"],
                "text": tweet["text"],
                "created_at": dt.isoformat(),
            })

    return result


# Alias para compatibilidad con el skill
fetch_tweets_sync = fetch_mancini_tweets


if __name__ == "__main__":
    tweets = fetch_tweets_sync()
    print(f"Encontrados {len(tweets)} tweets de hoy")
    for t in tweets:
        print(f"  [{t['created_at']}] {t['text'][:80]}...")
