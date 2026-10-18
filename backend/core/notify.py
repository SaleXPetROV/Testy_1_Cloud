"""Centralised in-app + Telegram notification helper.

Use ``notify_user`` from any backend module to:
  • Insert a row into ``db.notifications`` for the in-app drawer
  • Push a ``notification_new`` event over the WebSocket so the bell shakes
    instantly (no polling delay)
  • Mirror the same text to Telegram if the user has connected their account
    and has notifications enabled

This is a thin coroutine — callers should NOT await it inside hot loops or
critical paths. Best-effort: any error is logged but never raised.
"""
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)
_BG_TASKS: set = set()


# Inline keyboard with a single "🏠 На главную" button. The Telegram bot
# already handles the `back_to_menu` callback (see telegram_bot.py) — tapping
# it returns the user to the bot's main menu (cmd_start).
HOME_BUTTON_MARKUP: Dict[str, Any] = {
    "inline_keyboard": [[{"text": "🏠 На главную", "callback_data": "back_to_menu"}]]
}


def ton_explorer_url(tx_hash: str) -> Optional[str]:
    """Build a TON explorer link for a transaction hash (tonviewer)."""
    if not tx_hash or tx_hash == "sent_success":
        return None
    return f"https://tonviewer.com/transaction/{tx_hash}"


def home_markup(lang: str = "en") -> Dict[str, Any]:
    from core.notif_i18n import label
    return {"inline_keyboard": [[{"text": label("home_button", lang), "callback_data": "back_to_menu"}]]}


async def resolve_miniapp_url(db) -> Optional[str]:
    """Mini-app URL configured by the admin (game_settings.telegram_settings.app_url).
    Falls back to env PUBLIC_APP_URL / APP_URL. Returns None if nothing set."""
    url = ""
    try:
        doc = await db.game_settings.find_one({"type": "telegram_settings"}, {"_id": 0, "app_url": 1})
        url = str((doc or {}).get("app_url") or "").strip()
    except Exception:
        url = ""
    if not url:
        import os as _os
        url = (_os.environ.get("PUBLIC_APP_URL") or _os.environ.get("APP_URL") or "").strip()
    if not url:
        return None
    if not url.startswith("http"):
        url = "https://" + url
    return url.rstrip("/")


async def augment_markup_with_miniapp(db, markup: Optional[Dict[str, Any]], lang: str = "en") -> Optional[Dict[str, Any]]:
    """Append a localized "Open the app" URL button (mini-app link from admin)
    to any Telegram inline keyboard. Every bot notification gets this link."""
    from core.notif_i18n import label
    url = await resolve_miniapp_url(db)
    if not url:
        return markup
    btn = {"text": label("open_app", lang), "url": url}
    if not markup or not isinstance(markup, dict) or not markup.get("inline_keyboard"):
        return {"inline_keyboard": [[btn]]}
    rows = list(markup.get("inline_keyboard") or [])
    rows.append([btn])
    return {"inline_keyboard": rows}


def tx_and_home_markup(tx_hash: str = None, lang: str = "en") -> Dict[str, Any]:
    """Inline keyboard: optional transaction link button + localized home button."""
    from core.notif_i18n import label
    tx_label = label("tx_button", lang)
    home_label = label("home_button", lang)
    rows = []
    url = ton_explorer_url(tx_hash) if tx_hash else None
    if url:
        rows.append([{"text": tx_label, "url": url}])
    rows.append([{"text": home_label, "callback_data": "back_to_menu"}])
    return {"inline_keyboard": rows}


def notify_user_background(db, user_doc_or_id: Any, *args, timeout: float = 60.0, **kwargs) -> None:
    """Fire-and-forget notify_user: the caller (e.g. an admin approving a
    withdrawal or buying out lots) gets its HTTP response immediately instead
    of waiting for Telegram / WebSocket delivery, which can take tens of
    seconds when Telegram answers slowly. Failures are logged, never raised."""
    import asyncio

    async def _run():
        try:
            await asyncio.wait_for(notify_user(db, user_doc_or_id, *args, **kwargs), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(f"notify_user (background) timed out after {timeout}s: {kwargs.get('type_key')}")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"notify_user (background) failed: {e}")

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(_run())
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)


async def notify_user(
    db,
    user_doc_or_id: Any,
    title: str,
    message: str,
    type_key: str = "system",
    priority: str = "info",
    payload: Optional[Dict[str, Any]] = None,
    image_url: Optional[str] = None,
    reply_markup: Optional[Dict[str, Any]] = None,
    add_home_button: bool = False,
    telegram_message: Optional[str] = None,
    i18n_key: Optional[str] = None,
    i18n_vars: Optional[Dict[str, Any]] = None,
    tx_hash: Optional[str] = None,
    _inline: bool = False,
    in_app: bool = True,
    telegram: bool = True,
    pretranslated: bool = False,
) -> None:
    """Send a notification in-app + telegram + WS push. Best-effort.

    ``i18n_key`` — ключ из core.notif_i18n: title/message рендерятся на языке
    пользователя (users.language); ключ и переменные сохраняются в payload,
    чтобы фронт мог перерисовать текст при смене языка.
    ``tx_hash`` — добавляет строку с хэшем в web-версию и кнопку «Транзакция» в Telegram.
    """
    user_doc = None
    user_id = None

    if isinstance(user_doc_or_id, dict):
        user_doc = user_doc_or_id
        user_id = user_doc.get("id")
    elif isinstance(user_doc_or_id, str):
        user_id = user_doc_or_id
        try:
            user_doc = await db.users.find_one({"id": user_id}, {"_id": 0})
        except Exception as e:
            logger.warning(f"notify_user: user lookup failed: {e}")

    if not user_id:
        return

    from core.notif_i18n import user_lang, render, label, NOTIF
    lang = user_lang(user_doc)
    payload = dict(payload or {})
    if i18n_key and i18n_key in NOTIF:
        vars_ = dict(i18n_vars or {})
        if tx_hash and tx_hash != "sent_success":
            vars_["tx_line"] = label("tx_line", lang).format(hash=tx_hash)
            payload.setdefault("tx_hash", tx_hash)
        else:
            vars_.setdefault("tx_line", "")
        title, message = render(i18n_key, lang, **vars_)
        if telegram_message is None and vars_.get("tx_line"):
            telegram_message = render(i18n_key, lang, **{**vars_, "tx_line": ""})[1]
        payload["i18n_key"] = i18n_key
        payload["i18n_vars"] = {k: v for k, v in vars_.items() if k != "tx_line"}
        if tx_hash and tx_hash != "sent_success" and reply_markup is None:
            reply_markup = tx_and_home_markup(tx_hash, lang)
    else:
        if i18n_key:
            payload["i18n_key"] = i18n_key
            if i18n_vars:
                payload["i18n_vars"] = i18n_vars
        # Нет шаблона на 9 языков → автоперевод исходного текста на язык пользователя.
        try:
            from translation_service import script_language, translate_cached, translation_configured
            src = script_language(f"{title or ''} {message or ''}") or "en"
            if pretranslated:
                pass  # caller already localized title/message (e.g. smart_notify via LibreTranslate)
            elif translation_configured() and src != lang and not _inline:
                # Перевод может занять секунды — не блокируем API-запрос, доставляем в фоне.
                import asyncio
                task = asyncio.create_task(notify_user(
                    db, user_doc or user_id, title, message, type_key=type_key, priority=priority,
                    payload=payload, image_url=image_url, reply_markup=reply_markup,
                    add_home_button=add_home_button, telegram_message=telegram_message,
                    i18n_key=i18n_key, i18n_vars=i18n_vars, tx_hash=tx_hash, _inline=True,
                    in_app=in_app, telegram=telegram,
                ))
                _BG_TASKS.add(task)
                task.add_done_callback(_BG_TASKS.discard)
                return
            if not pretranslated and translation_configured() and src != lang:
                if title:
                    title = await translate_cached(db, title, lang, src)
                if message:
                    message = await translate_cached(db, message, lang, src)
                if telegram_message:
                    telegram_message = await translate_cached(db, telegram_message, lang, src)
        except Exception as e:
            logger.debug(f"notify_user auto-translate skipped: {e}")

    notif = {
        "id": str(_uuid.uuid4()),
        "user_id": user_id,
        "type": type_key,
        "priority": priority,
        "title": title or "",
        "message": message or "",
        "payload": payload,
        "image_url": image_url,
        "read": False,
        # notify_user handles Telegram mirroring inline below, so mark the
        # notification as already-delivered to Telegram. Without this flag the
        # `send_pending_notifications` background job would find the row a few
        # minutes later and send a THIRD duplicate copy prefixed with
        # "🏙️ GRAM City" to the user's chat.
        "telegram_sent": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if in_app:
        try:
            await db.notifications.insert_one(dict(notif))
        except Exception as e:
            logger.warning(f"notify_user db insert failed: {e}")

        # Real-time WS push so the bell shakes instantly
        try:
            from core.websocket import manager as ws_manager
            await ws_manager.send_personal({"type": "notification_new", "notification": notif}, user_id)
        except Exception as e:
            logger.debug(f"notify_user ws push failed: {e}")

    if not telegram:
        return

    # Mirror to Telegram (best-effort). Internal callers pass trusted text with
    # intentional HTML tags (<b>, <code>, …), so we DO NOT escape those — the
    # previous escape converted `<b>` into `&lt;b&gt;` which Telegram then
    # rendered as literal "<b>text</b>" characters instead of bold text.
    if not user_doc:
        return
    chat_id = user_doc.get("telegram_chat_id")
    if not chat_id or not user_doc.get("telegram_notifications", True):
        return

    markup = reply_markup or (home_markup(lang) if add_home_button else None)
    # Every bot notification carries the admin-configured mini-app link.
    try:
        markup = await augment_markup_with_miniapp(db, markup, lang)
    except Exception as e:
        logger.debug(f"notify_user miniapp markup failed: {e}")
    tg_src = telegram_message if telegram_message is not None else message
    body = f"<b>{title}</b>\n\n{tg_src}" if title else (tg_src or "")

    # Preferred path: send through the live TelegramBot instance. Its
    # `send_message` resolves the bot token dynamically from env/DB on every
    # call and always uses parse_mode="HTML", so HTML tags render correctly and
    # inline keyboards (the "🏠 На главную" button) are supported.
    bot = None
    try:
        from telegram_bot import get_telegram_bot
        bot = get_telegram_bot()
        if bot is not None:
            await bot.send_message(str(chat_id), body, reply_markup=markup)
            # Sent, or Telegram rejected / timed out after the bot's own retry.
            # Do NOT fall through to the legacy sender in that case: it would
            # wait for the same slow Telegram API a second time.
            return
    except Exception as e:
        logger.debug(f"notify_user bot send failed, falling back: {e}")

    # Fallback ONLY when the bot instance is unavailable or crashed.
    try:
        from telegram_notifications import send_telegram_message
        await send_telegram_message(str(chat_id), body, reply_markup=markup)
    except Exception as e:
        logger.debug(f"notify_user telegram mirror failed: {e}")
