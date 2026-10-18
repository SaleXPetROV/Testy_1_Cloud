"""
Telegram Notification Service for GRAM City
Sends notifications about business status, resources, etc.
"""

import os
import asyncio
import logging
from typing import Optional
import httpx

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_API_BASE = os.environ.get(
    "TELEGRAM_API_BASE", "https://api.telegram.org"
).rstrip("/")
TELEGRAM_API_URL = f"{TELEGRAM_API_BASE}/bot{TELEGRAM_BOT_TOKEN}"


def _get_bot_token() -> str:
    """Resolve the bot token at call time.

    The token is loaded into ``os.environ`` at server startup (from the DB) and
    can also be updated later via the admin panel, so we must NOT cache the
    value captured at import time — otherwise messages silently fail to send.
    """
    return os.environ.get("TELEGRAM_BOT_TOKEN", "") or TELEGRAM_BOT_TOKEN


async def send_telegram_message(chat_id: str, text: str, parse_mode: str = "HTML",
                                reply_markup: Optional[dict] = None,
                                preview_url: Optional[str] = None) -> bool:
    """Send a message via Telegram bot.

    If `preview_url` is given (Bot API 7.0+ `link_preview_options`), the image
    at that URL is rendered as a large media preview ABOVE the message text —
    so the caller can attach a picture and a >1024-char body in a *single*
    Telegram message. Without this, `sendPhoto` limits the caption to 1024
    characters and long marketing copy has to be split into two messages
    (which is what we're trying to avoid).
    """
    bot_token = _get_bot_token()
    if not bot_token or not chat_id:
        logger.warning("Telegram bot token or chat_id not configured")
        return False

    try:
        async with httpx.AsyncClient() as client:
            payload = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
            }
            if reply_markup:
                payload["reply_markup"] = reply_markup
            if preview_url:
                # Bot API 7.0+ — allows attaching an image preview to a
                # sendMessage call so we don't need a second sendMessage.
                payload["link_preview_options"] = {
                    "url": preview_url,
                    "is_disabled": False,
                    "prefer_large_media": True,
                    "show_above_text": True,
                }
                # Older clients that ignore `link_preview_options` will show
                # a normal preview if the URL is anywhere in the text — so
                # we also prepend an invisible anchor as a fallback.
                text = f'<a href="{preview_url}">\u200b</a>{text}'
                payload["text"] = text
            else:
                # No preview requested — silence the auto-link preview that
                # Telegram would otherwise generate from URLs in the body.
                payload["disable_web_page_preview"] = True
            response = await client.post(
                f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage",
                json=payload,
                timeout=10.0
            )
            
            if response.status_code == 200:
                logger.info(f"Telegram message sent to {chat_id}")
                return True
            else:
                logger.error(f"Failed to send Telegram message: {response.text}")
                return False
    except Exception as e:
        logger.error(f"Error sending Telegram message: {e}")
        return False


async def send_telegram_photo(chat_id: str, photo_url: str, caption: str = "",
                              parse_mode: str = "HTML",
                              reply_markup: Optional[dict] = None) -> bool:
    """Send a photo via Telegram bot (with optional HTML caption).

    Falls back to `send_telegram_message` if the photo call fails (e.g. remote
    URL unreachable, caption too long, etc.).
    """
    bot_token = _get_bot_token()
    if not bot_token or not chat_id:
        logger.warning("Telegram bot token or chat_id not configured")
        return False
    try:
        async with httpx.AsyncClient() as client:
            payload = {
                "chat_id": chat_id,
                "photo": photo_url,
                "caption": caption[:1024],  # Telegram caption limit
                "parse_mode": parse_mode,
            }
            if reply_markup:
                payload["reply_markup"] = reply_markup
            response = await client.post(
                f"{TELEGRAM_API_BASE}/bot{bot_token}/sendPhoto",
                json=payload,
                timeout=15.0,
            )
            if response.status_code == 200:
                logger.info(f"Telegram photo sent to {chat_id}")
                return True
            logger.warning(f"sendPhoto failed for {chat_id}: {response.text}")
            # Fallback to plain text (caption may exceed 1024 chars)
            return await send_telegram_message(chat_id, caption, parse_mode, reply_markup)
    except Exception as e:
        logger.error(f"Error sending Telegram photo: {e}")
        return await send_telegram_message(chat_id, caption, parse_mode, reply_markup)


# ==================== BUSINESS NOTIFICATIONS ====================
# Все тексты — из core.notif_i18n на языке пользователя (9 языков).

def _render(key: str, lang: str, **vars_) -> str:
    from core.notif_i18n import render
    title, message = render(key, lang, **vars_)
    return f"<b>{title}</b>\n\n{message}"


async def notify_low_durability(chat_id: str, business_name: str, durability: float, lang: str = "en"):
    return await send_telegram_message(chat_id, _render("low_durability", lang, biz=business_name, durability=f"{durability:.1f}"))


async def notify_durability_warning_20(chat_id: str, business_name: str, durability: float, lang: str = "en"):
    return await send_telegram_message(chat_id, _render("durability_20", lang, biz=business_name, durability=f"{durability:.1f}"))


async def notify_critical_durability(chat_id: str, business_name: str, durability: float, lang: str = "en"):
    return await send_telegram_message(chat_id, _render("critical_durability", lang, biz=business_name, durability=f"{durability:.1f}"))


async def notify_business_stopped(chat_id: str, business_name: str, lang: str = "en"):
    return await send_telegram_message(chat_id, _render("business_stopped", lang, biz=business_name))


async def notify_resources_full(chat_id: str, resource_name: str, amount: float, capacity: float = None, lang: str = "en"):
    return await send_telegram_message(chat_id, _render("resources_full", lang, res=resource_name, amount=f"{amount:.0f}"))


async def notify_business_sold(chat_id: str, business_name: str, amount: float, tax: float, lang: str = "en"):
    return await send_telegram_message(chat_id, _render("business_sold", lang, biz=business_name, amount=f"{amount:.2f}", tax=f"{tax:.2f}"))


# ==================== HELPER FUNCTIONS ====================

async def get_user_telegram_chat_id(db, user_id: str) -> Optional[str]:
    """Get user's Telegram chat ID from database"""
    user = await db.users.find_one(
        {"$or": [{"id": user_id}, {"wallet_address": user_id}]},
        {"_id": 0, "telegram_chat_id": 1}
    )
    return user.get("telegram_chat_id") if user else None


# Threshold for resource notification (100 units)
RESOURCE_NOTIFICATION_THRESHOLD = 100

# Track notified states to avoid spam
_notified_states = {}

def should_notify(user_id: str, notification_type: str, key: str = "") -> bool:
    """Check if we should send notification (to avoid spam)"""
    state_key = f"{user_id}:{notification_type}:{key}"
    if state_key in _notified_states:
        return False
    _notified_states[state_key] = True
    return True

def clear_notification_state(user_id: str, notification_type: str, key: str = ""):
    """Clear notification state when condition is resolved"""
    state_key = f"{user_id}:{notification_type}:{key}"
    _notified_states.pop(state_key, None)
