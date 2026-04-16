"""
Clasificador de tweets intraday de Mancini usando Claude Haiku.

Recibe un tweet individual + el plan actual y determina si el tweet
representa un ajuste al plan (invalidacion, cambio de nivel, etc.)
o si es ruido (NO_ACTION).
"""

from __future__ import annotations

import json
import os
import re

from anthropic import Anthropic
from dotenv import load_dotenv
from pathlib import Path

from scripts.mancini.config import DailyPlan, PlanAdjustment

# Buscar .env en la raiz del proyecto (funciona desde worktrees y subcarpetas)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_env_path = _PROJECT_ROOT / ".env"
if not _env_path.exists() and ".claude" in str(_PROJECT_ROOT):
    _env_path = Path(str(_PROJECT_ROOT).split(".claude")[0]) / ".env"
load_dotenv(_env_path, override=True)

MODEL = os.getenv("MANCINI_PARSER_MODEL", "claude-haiku-4-5-20251001")

CLASSIFIER_SYSTEM_PROMPT = """\
Eres un clasificador de tweets de trading intraday de @AdamMancini4 sobre futuros /ES.

Tu tarea es analizar un tweet individual en el contexto del plan de trading del dia
y determinar si el tweet modifica, invalida o aporta contexto al plan actual.

## Plan actual del dia

- Key level upper: {key_level_upper}
- Key level lower: {key_level_lower}
- Targets upper: {targets_upper}
- Targets lower: {targets_lower}
- Chop zone: {chop_zone}

## Categorias de clasificacion

1. INVALIDATION — el plan o parte del plan ya no es valido
   Ejemplos: "plan invalidated below 6760", "levels no longer in play"
   details: {{"scope": "full"|"upper"|"lower", "condition": "...", "invalidated_levels": [...]}}

2. LEVEL_UPDATE — un nivel clave cambia (nuevo soporte/resistencia)
   Ejemplos: "buyers defending 6790 now" (cuando key_level era 6780)
   details: {{"side": "upper"|"lower", "old_level": ..., "new_level": ..., "reason": "..."}}

3. TARGET_UPDATE — los targets se modifican
   Ejemplos: "next target 6840", "taking 6820 off the table"
   details: {{"side": "upper"|"lower", "new_targets": [...], "replace": true|false}}

4. BIAS_SHIFT — cambio de sesgo direccional de la sesion
   Ejemplos: "flipped bearish", "bulls taking control"
   details: {{"old_bias": "bullish"|"bearish"|null, "new_bias": "bullish"|"bearish", "trigger": "..."}}

5. CONTEXT_UPDATE — info cualitativa util pero no cambia niveles numericos
   Ejemplos: "buyers defending 6780 aggressively", "volume picking up"
   details: {{"context_type": "defense"|"momentum"|"volume"|"general", "summary": "...", "implied_bias": "bullish"|"bearish"|null}}

6. NO_ACTION — tweet sin impacto en el plan
   Ejemplos: replies a followers, promos, preguntas, comentarios genericos
   details: {{}}

## Reglas importantes

- Un tweet que CONFIRMA el plan existente sin cambiarlo es CONTEXT_UPDATE, no LEVEL_UPDATE.
- Replies a followers, promos, o tweets sin relacion con /ES son NO_ACTION.
- "runners" = posicion existente, no nuevo target.
- Si Mancini menciona un nivel que YA es el key_level actual, es CONTEXT_UPDATE.
- Solo usa LEVEL_UPDATE si el nivel numerico realmente cambia respecto al plan.

## Formato de respuesta

Responde SOLO con JSON valido (sin markdown, sin explicaciones):

{{"adjustment_type": "...", "details": {{...}}, "reasoning": "breve explicacion en espanol de por que esta clasificacion"}}
"""


def classify_tweet(
    tweet_text: str,
    tweet_id: str,
    tweet_timestamp: str,
    current_plan: DailyPlan,
) -> PlanAdjustment:
    """Clasifica un tweet individual contra el plan actual.

    Siempre retorna un PlanAdjustment (incluyendo NO_ACTION para ruido).
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY no configurada en .env")

    client = Anthropic(api_key=api_key)

    system = CLASSIFIER_SYSTEM_PROMPT.format(
        key_level_upper=current_plan.key_level_upper,
        key_level_lower=current_plan.key_level_lower,
        targets_upper=current_plan.targets_upper,
        targets_lower=current_plan.targets_lower,
        chop_zone=current_plan.chop_zone,
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=300,
        system=system,
        messages=[{"role": "user", "content": f'Tweet: "{tweet_text}"'}],
    )

    content = response.content[0].text
    return _parse_classifier_response(content, tweet_id, tweet_text, tweet_timestamp)


def _parse_classifier_response(
    content: str,
    tweet_id: str,
    tweet_text: str,
    tweet_timestamp: str,
) -> PlanAdjustment:
    """Parsea la respuesta JSON de Haiku a PlanAdjustment."""
    cleaned = content.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Si Haiku devuelve JSON invalido, tratar como NO_ACTION
        return PlanAdjustment(
            tweet_id=tweet_id,
            tweet_text=tweet_text,
            timestamp=tweet_timestamp,
            adjustment_type="NO_ACTION",
            details={},
            raw_reasoning=f"JSON invalido del clasificador: {content[:200]}",
        )

    return PlanAdjustment(
        tweet_id=tweet_id,
        tweet_text=tweet_text,
        timestamp=tweet_timestamp,
        adjustment_type=data.get("adjustment_type", "NO_ACTION"),
        details=data.get("details", {}),
        raw_reasoning=data.get("reasoning", ""),
    )
