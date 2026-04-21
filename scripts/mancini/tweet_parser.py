"""
Parsea tweets de Mancini en un DailyPlan estructurado usando Claude Haiku.

Requiere ANTHROPIC_API_KEY en .env.
"""

from __future__ import annotations

import json
import os
import re

from anthropic import Anthropic
from dotenv import load_dotenv
from pathlib import Path

from scripts.mancini.config import DailyPlan

# Buscar .env en la raíz del proyecto (funciona desde worktrees y subcarpetas)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_env_path = _PROJECT_ROOT / ".env"
if not _env_path.exists() and ".claude" in str(_PROJECT_ROOT):
    _env_path = Path(str(_PROJECT_ROOT).split(".claude")[0]) / ".env"
load_dotenv(_env_path, override=True)

MODEL = os.getenv("MANCINI_PARSER_MODEL", "claude-haiku-4-5-20251001")

SYSTEM_PROMPT = """\
Eres un parser de tweets de Adam Mancini sobre futuros /ES.
Tu tarea es extraer niveles de precio estructurados de sus tweets.

## Formato de salida

Responde SOLO con JSON válido (sin markdown, sin explicaciones):

{
  "key_level_upper": 6809,
  "targets_upper": [6819, 6830],
  "key_level_lower": 6781,
  "targets_lower": [6766],
  "chop_zone": [6788, 6830],
  "notes": "breve resumen de contexto"
}

## Reglas de extracción

- "X reclaims" / "reclaim X" / "above X" → key_level_upper
- Números tras "see", "targets" después del reclaim → targets_upper (ascendente)
- "X fails" / "fail X" / "sell X" / "below X" → key_level_lower
- Números tras "sell", "fails" → targets_lower (descendente)
- "X-Y=chop" / "chop zone" → chop_zone como [X, Y]
- Si no hay chop zone → chop_zone: null
- "Plan: X, Y, Z next slate" → targets_upper (nuevos objetivos de continuación)
- "X=support" / "X-Y=support" → key_level_upper (soporte que debe mantenerse)
- "ride runner" / "runner" = posición existente en curso, no es nivel nuevo
- Si hay "Plan: X, Y, Z next slate" con "X=support", usa el nivel de soporte
  como key_level_upper y los números del "Plan:" como targets_upper

## Notación especial de Mancini

- "6793/88" = dos niveles: 6793 y 6788 (los últimos dígitos completan el número)
- "6766-70" = rango 6766 a 6770 (usa 6766 como nivel)
- "6900-05" = rango 6900 a 6905 (usa 6900 como nivel)
- "(hit)" / "(all hit)" después de un target = ya alcanzado, NO incluir en targets
- "watch traps" = advertencia, no es un nivel
- "runners" = posición existente, no nivel nuevo

## Si no hay plan claro

Si los tweets no contienen un plan nuevo para hoy (solo actualizaciones de
runners, comentarios de volatilidad sin niveles nuevos), responde:

{
  "key_level_upper": null,
  "targets_upper": [],
  "key_level_lower": null,
  "targets_lower": [],
  "chop_zone": null,
  "notes": "descripción de por qué no hay plan"
}

Solo extrae niveles para futuros /ES. Ignora otros instrumentos."""

WEEKLY_SYSTEM_PROMPT = """\
Eres un parser del tweet "Big Picture View" de Adam Mancini sobre futuros /ES.
Este tweet se publica los fines de semana y establece el marco semanal.

## Formato de salida

Responde SOLO con JSON válido (sin markdown, sin explicaciones):

{
  "key_level_upper": 6817,
  "targets_upper": [6903, 6950, 7068],
  "key_level_lower": 6793,
  "targets_lower": [],
  "chop_zone": null,
  "notes": "Sesgo: alcista. Resumen de la semana y contexto."
}

## Reglas de extracción

- "Bulls want to hold X" / "hold X" → key_level_upper (soporte clave alcista)
- "X lowest" / "X is floor" → key_level_lower (soporte mínimo, si falla = retrace)
- "keeps X, Y live" / "targets X, Y" → targets_upper (ascendente)
- "X fails, we retrace" / "X fails" → confirma key_level_lower
- "Dip, then X" → incluir X en targets_upper
- "chop between X-Y" → chop_zone como [X, Y]
- Si no hay chop zone → chop_zone: null

## Campo notes (importante)

En notes incluye:
1. Sesgo semanal: "alcista", "bajista" o "neutral"
2. Resumen breve de la semana pasada (qué patrón se formó)
3. Contexto relevante para la operativa de la semana

## Notación especial de Mancini

- "6793/88" = dos niveles: 6793 y 6788
- "6766-70" = rango 6766 a 6770 (usa 6766)
- "6900-05" = rango 6900 a 6905 (usa 6900)

## Si no hay Big Picture claro

{
  "key_level_upper": null,
  "targets_upper": [],
  "key_level_lower": null,
  "targets_lower": [],
  "chop_zone": null,
  "notes": "descripción de por qué no hay plan semanal"
}

Solo extrae niveles para futuros /ES. Ignora otros instrumentos."""


def parse_tweets_to_plan(tweets: list[dict], fecha: str) -> DailyPlan | None:
    """Envía tweets a Haiku y devuelve DailyPlan o None si no hay plan."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY no configurada en .env")

    client = Anthropic(api_key=api_key)
    user_message = _build_user_message(tweets)

    response = client.messages.create(
        model=MODEL,
        max_tokens=500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    content = response.content[0].text
    raw_tweets = [t["text"] for t in tweets]
    return _parse_response(content, fecha, raw_tweets)


def _build_user_message(tweets: list[dict]) -> str:
    """Formatea tweets en texto numerado para el prompt."""
    lines = ["Tweets de @AdamMancini4 de hoy (más reciente primero):", ""]
    for i, tweet in enumerate(tweets, 1):
        lines.append(f"{i}. [{tweet['created_at']}] {tweet['text']}")
    return "\n".join(lines)


def _parse_response(
    content: str, fecha: str, raw_tweets: list[str]
) -> DailyPlan | None:
    """Parsea la respuesta JSON de Haiku a DailyPlan."""
    # Limpiar posibles fences de markdown
    cleaned = content.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"Haiku devolvió JSON inválido: {e}\nRespuesta: {content}")

    # Si no hay plan (niveles null)
    if data.get("key_level_upper") is None and data.get("key_level_lower") is None:
        return None

    chop = data.get("chop_zone")
    if chop is not None:
        chop = tuple(chop)

    upper = data.get("key_level_upper")
    lower = data.get("key_level_lower")

    return DailyPlan(
        fecha=fecha,
        key_level_upper=float(upper) if upper is not None else None,
        targets_upper=[float(t) for t in data.get("targets_upper", [])],
        key_level_lower=float(lower) if lower is not None else None,
        targets_lower=[float(t) for t in data.get("targets_lower", [])],
        raw_tweets=raw_tweets,
        chop_zone=chop,
        notes=data.get("notes", ""),
    )


def parse_weekly_tweets(
    tweets: list[dict], week_start: str
) -> DailyPlan | None:
    """Parsea tweets Big Picture View en un plan semanal."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY no configurada en .env")

    client = Anthropic(api_key=api_key)

    lines = [
        "Tweet 'Big Picture View' de @AdamMancini4 (fin de semana):", ""
    ]
    for i, tweet in enumerate(tweets, 1):
        lines.append(f"{i}. [{tweet['created_at']}] {tweet['text']}")
    user_message = "\n".join(lines)

    response = client.messages.create(
        model=MODEL,
        max_tokens=500,
        system=WEEKLY_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    content = response.content[0].text
    raw_tweets = [t["text"] for t in tweets]
    return _parse_response(content, week_start, raw_tweets)
