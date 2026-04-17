"""
Confirmación interactiva via Telegram con inline keyboards.

Envía un mensaje con botones [✅ Ejecutar] [❌ Descartar] y espera la
respuesta del trader via callback_query polling. Timeout conservador:
si no hay respuesta, el trade se descarta.
"""

from __future__ import annotations

import os
import time

import httpx

from scripts.notify_telegram import _esc


def _get_credentials() -> tuple[str, str]:
    """Lee TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID del entorno."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    return token, chat_id


def ask_trader_confirmation(
    signal_info: str,
    risk_factors: list[str],
    reasoning: str,
    timeout_seconds: int = 120,
) -> bool | None:
    """Envía pregunta con botones Sí/No al trader.

    Args:
        signal_info: texto descriptivo de la señal (sin markdown)
        risk_factors: lista de factores de riesgo detectados
        reasoning: explicación del gate
        timeout_seconds: segundos de espera máxima (default 120)

    Returns:
        True si el trader confirma, False si rechaza, None si timeout.
    """
    token, chat_id = _get_credentials()
    if not token or not chat_id:
        return None

    # 1. Construir mensaje con inline keyboard
    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Ejecutar", "callback_data": "exec_yes"},
            {"text": "❌ Descartar", "callback_data": "exec_no"},
        ]]
    }

    factors_str = "\n".join(f"  • {f}" for f in risk_factors) if risk_factors else "  ninguno"

    msg = (
        "⚠️ *Señal pendiente de confirmación*\n\n"
        f"{_esc(signal_info)}\n\n"
        f"🔍 *Factores de riesgo:*\n{_esc(factors_str)}\n\n"
        f"🤖 *Razonamiento:* {_esc(reasoning)}\n\n"
        "¿Ejecutar el trade?"
    )

    # 2. Enviar mensaje con botones
    try:
        response = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": msg,
                "parse_mode": "MarkdownV2",
                "reply_markup": keyboard,
            },
            timeout=10.0,
        )
        result = response.json()
        if not result.get("ok"):
            return None
        message_id = result["result"]["message_id"]
    except Exception:
        return None

    # 3. Polling de callback_query (esperar respuesta del trader)
    deadline = time.time() + timeout_seconds
    last_update_id = 0

    while time.time() < deadline:
        try:
            updates_response = httpx.post(
                f"https://api.telegram.org/bot{token}/getUpdates",
                json={
                    "offset": last_update_id + 1,
                    "timeout": 10,  # long polling 10s
                    "allowed_updates": ["callback_query"],
                },
                timeout=15.0,
            )
            updates = updates_response.json()
        except Exception:
            continue

        for update in updates.get("result", []):
            last_update_id = update["update_id"]
            cb = update.get("callback_query", {})
            if cb.get("message", {}).get("message_id") == message_id:
                # Responder al callback (quitar spinner)
                try:
                    httpx.post(
                        f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                        json={"callback_query_id": cb["id"]},
                        timeout=5.0,
                    )
                except Exception:
                    pass

                answer = cb["data"]  # "exec_yes" o "exec_no"

                # Editar mensaje para reflejar decisión
                decision_text = "✅ Trade ejecutado" if answer == "exec_yes" else "❌ Trade descartado"
                try:
                    httpx.post(
                        f"https://api.telegram.org/bot{token}/editMessageText",
                        json={
                            "chat_id": chat_id,
                            "message_id": message_id,
                            "text": f"{msg}\n\n*Decisión:* {_esc(decision_text)}",
                            "parse_mode": "MarkdownV2",
                        },
                        timeout=5.0,
                    )
                except Exception:
                    pass

                return answer == "exec_yes"

    # 4. Timeout — editar mensaje para indicar que expiró
    try:
        httpx.post(
            f"https://api.telegram.org/bot{token}/editMessageText",
            json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": f"{msg}\n\n*⏰ Timeout — trade descartado*",
                "parse_mode": "MarkdownV2",
            },
            timeout=5.0,
        )
    except Exception:
        pass

    return None  # timeout = no ejecutar


def ask_close_runner(
    trade_info: str,
    timeout_seconds: int = 120,
) -> bool | None:
    """Envía botón para cerrar runner manualmente.

    Args:
        trade_info: texto descriptivo del trade activo
        timeout_seconds: segundos de espera

    Returns:
        True si confirma cierre, False si rechaza, None si timeout.
    """
    token, chat_id = _get_credentials()
    if not token or not chat_id:
        return None

    keyboard = {
        "inline_keyboard": [[
            {"text": "🔒 Cerrar runner", "callback_data": "close_yes"},
            {"text": "▶️ Mantener", "callback_data": "close_no"},
        ]]
    }

    msg = (
        "📊 *Runner activo*\n\n"
        f"{_esc(trade_info)}\n\n"
        "¿Cerrar el runner?"
    )

    try:
        response = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": msg,
                "parse_mode": "MarkdownV2",
                "reply_markup": keyboard,
            },
            timeout=10.0,
        )
        result = response.json()
        if not result.get("ok"):
            return None
        message_id = result["result"]["message_id"]
    except Exception:
        return None

    deadline = time.time() + timeout_seconds
    last_update_id = 0

    while time.time() < deadline:
        try:
            updates_response = httpx.post(
                f"https://api.telegram.org/bot{token}/getUpdates",
                json={
                    "offset": last_update_id + 1,
                    "timeout": 10,
                    "allowed_updates": ["callback_query"],
                },
                timeout=15.0,
            )
            updates = updates_response.json()
        except Exception:
            continue

        for update in updates.get("result", []):
            last_update_id = update["update_id"]
            cb = update.get("callback_query", {})
            if cb.get("message", {}).get("message_id") == message_id:
                try:
                    httpx.post(
                        f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                        json={"callback_query_id": cb["id"]},
                        timeout=5.0,
                    )
                except Exception:
                    pass

                answer = cb["data"]
                decision_text = "🔒 Runner cerrado" if answer == "close_yes" else "▶️ Runner mantenido"
                try:
                    httpx.post(
                        f"https://api.telegram.org/bot{token}/editMessageText",
                        json={
                            "chat_id": chat_id,
                            "message_id": message_id,
                            "text": f"{msg}\n\n*Decisión:* {_esc(decision_text)}",
                            "parse_mode": "MarkdownV2",
                        },
                        timeout=5.0,
                    )
                except Exception:
                    pass

                return answer == "close_yes"

    return None
