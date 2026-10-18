"""
GRAM City Telegram Bot - Full Implementation
Handles user notifications, admin commands, and account management
"""

import os
import logging
import asyncio
import aiohttp
import uuid
import time
from typing import Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from motor.motor_asyncio import AsyncIOMotorClient
from pathlib import Path as _Path
from dotenv import load_dotenv as _load_dotenv

# Load backend/.env here too: this module is imported by bot_webhook_server.py
# BEFORE it calls load_dotenv, so TELEGRAM_API_BASE / TELEGRAM_PROXY_URL below
# must be resolvable regardless of import order. (Does not override existing env.)
_load_dotenv(_Path(__file__).parent / ".env")

logger = logging.getLogger(__name__)

# Optional outbound proxy for reaching api.telegram.org. Set TELEGRAM_PROXY_URL
# in backend/.env (e.g. http://user:pass@host:port or socks5://host:port) on
# servers where Telegram is network-blocked (the empty-message TimeoutError).
# When empty, requests go direct.
def _telegram_proxy() -> Optional[str]:
    return os.environ.get("TELEGRAM_PROXY_URL", "").strip() or None


# Base URL for the Telegram Bot API. Override with TELEGRAM_API_BASE in
# backend/.env to route ALL bot requests through a proxy (e.g. a Cloudflare
# Worker that mirrors the /bot<token>/<method> path) on servers where
# api.telegram.org is network-blocked (the TimeoutError on sendMessage).
TELEGRAM_API_BASE = os.environ.get(
    "TELEGRAM_API_BASE", "https://api.telegram.org"
).rstrip("/")


# ── Community links + required-subscription channel ──────────────────────────
# All overridable via backend/.env. REQUIRED_CHANNEL_ID accepts a public
# @username (works once the bot is an admin of that channel) or a numeric
# -100… id. The bot gates access until the user joins this channel.
TELEGRAM_CHANNEL_URL = os.environ.get("TELEGRAM_CHANNEL_URL", "https://t.me/gramcity_channel")
TELEGRAM_CHAT_URL = os.environ.get("TELEGRAM_CHAT_URL", "https://t.me/gramcity_chat")
TELEGRAM_BOT_URL = os.environ.get("TELEGRAM_BOT_URL", "https://t.me/gramcity_games_bot")
REQUIRED_CHANNEL_ID = os.environ.get("REQUIRED_CHANNEL_ID", "@gramcity_channel")


def _to_friendly_address_static(address: str) -> str:
    """Convert raw TON address to user-friendly format"""
    try:
        from tonsdk.utils import Address
        return Address(address).to_string(is_user_friendly=True, is_bounceable=True)
    except Exception:
        return address


def _urlify_keyboard(reply_markup: Optional[dict]) -> Optional[dict]:
    """Return a copy of an inline keyboard with every Telegram Mini App
    (`web_app`) button converted to a plain `url` button.

    Telegram rejects the ENTIRE sendMessage (BUTTON_TYPE_INVALID /
    WEBAPP_URL_INVALID) when a `web_app` button URL is not registered in
    BotFather or lives on a different domain. A plain `url` button opens the
    same link in the browser and is always valid, so the user still receives a
    working keyboard instead of total silence.
    """
    if not reply_markup or "inline_keyboard" not in reply_markup:
        return reply_markup
    new_rows = []
    for row in reply_markup["inline_keyboard"]:
        new_row = []
        for btn in row:
            if isinstance(btn, dict) and "web_app" in btn:
                wa = btn.get("web_app") or {}
                url = wa.get("url") if isinstance(wa, dict) else None
                if not (isinstance(url, str) and url.startswith("https://")):
                    url = "https://t.me/gramcity_games_bot/gramcity"
                new_row.append({"text": btn.get("text", "🌐 Open"), "url": url})
            else:
                new_row.append(btn)
        new_rows.append(new_row)
    return {"inline_keyboard": new_rows}

class TelegramBot:
    """Full-featured Telegram bot for GRAM City"""
    
    def __init__(self, db):
        self.db = db
        self.api_url = TELEGRAM_API_BASE + "/bot{token}"
        # Keep strong references to fire-and-forget tasks so Python's asyncio
        # doesn't garbage-collect them before they finish (Python 3.11+ warns
        # on this and, worse, can silently cancel the coroutine mid-flight).
        self._bg_tasks: set = set()
        # SHARED aiohttp session with a connection pool. Creating a new
        # ClientSession per Telegram API call (the old behaviour) meant a fresh
        # TCP+TLS handshake every time and, under 20k-user load, ephemeral-port /
        # fd exhaustion → TimeoutError → the exact 9-21s stalls + "Answer
        # callback error". A single pooled session keeps connections to
        # api.telegram.org warm and reused.
        self._session: Optional[aiohttp.ClientSession] = None
        # Bot-token cache. The DB is the source of truth (admin panel writes it
        # there); we cache in-memory for a few seconds so we don't hit Mongo on
        # every send, but pick up a token change quickly. `TELEGRAM_BOT_TOKEN`
        # env is only a last-resort fallback now — previously it was returned
        # FIRST, which made a separate bot process keep replying with a STALE
        # token after the admin changed it in the panel.
        self._token_cache: Optional[str] = None
        self._token_cache_ts: float = 0.0

    async def _get_session(self) -> aiohttp.ClientSession:
        """Return the shared pooled aiohttp session (lazily created)."""
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(
                limit=200,            # total pooled connections
                limit_per_host=100,   # to api.telegram.org
                ttl_dns_cache=300,
                enable_cleanup_closed=True,
            )
            # trust_env=True lets standard HTTPS_PROXY/HTTP_PROXY env vars work
            # too (in addition to the explicit TELEGRAM_PROXY_URL below).
            self._session = aiohttp.ClientSession(connector=connector, trust_env=True)
        return self._session

    def _spawn(self, coro):
        """Schedule a fire-and-forget coroutine while keeping a reference."""
        task = asyncio.create_task(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
        return task

    async def _track_activity(self, chat_id: str, user_id_tg: str, username: str,
                              first_name: str, is_premium: bool, tg_language_code: str):
        """Record user activity in telegram_mappings. Run FIRE-AND-FORGET
        (asyncio.create_task) — the bot must NEVER wait on this DB write before
        acking a click / deleting a message, otherwise a slow query stalls the
        button reaction. first_activity_at is set once ($ifNull), last_activity_at
        refreshed each hit. Requires an index on `chat_id` (created at startup)
        so this upsert is O(log n) instead of a full collection scan at 20k users.
        """
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            await self.db.telegram_mappings.update_one(
                {"chat_id": chat_id},
                [{
                    "$set": {
                        "chat_id": chat_id,
                        "telegram_user_id": user_id_tg,
                        "username": (username.lower() if username else None),
                        "first_name": first_name,
                        "is_premium": is_premium,
                        "tg_language_code": tg_language_code,
                        "updated_at": now_iso,
                        "last_activity_at": now_iso,
                        "first_activity_at": {"$ifNull": ["$first_activity_at", now_iso]},
                    }
                }],
                upsert=True,
            )
        except Exception as e:
            logger.debug(f"track_activity failed for chat_id={chat_id}: {e}")
    
    def _to_friendly_address(self, address: str) -> str:
        """Convert raw TON address to user-friendly format"""
        return _to_friendly_address_static(address)
        
    async def get_bot_token(self) -> Optional[str]:
        """Return the active bot token. DB is the source of truth.

        Priority: game_settings.telegram_settings (canonical, written by the
        webhook helper + admin panel) → admin_settings.telegram_bot →
        TELEGRAM_BOT_TOKEN env (last resort). Cached in-memory for a few seconds
        so a token change in the admin panel propagates automatically without a
        restart, while avoiding a Mongo read on every single send.
        """
        now = time.monotonic()
        if self._token_cache and (now - self._token_cache_ts) < 5.0:
            return self._token_cache

        token = None
        game_settings = await self.db.game_settings.find_one(
            {"type": "telegram_settings"}, {"_id": 0}
        )
        if game_settings and game_settings.get("bot_token"):
            token = game_settings["bot_token"]

        if not token:
            settings = await self.db.admin_settings.find_one(
                {"type": "telegram_bot"}, {"_id": 0}
            )
            if settings and settings.get("bot_token"):
                token = settings["bot_token"]

        if not token:
            token = os.environ.get("TELEGRAM_BOT_TOKEN", "") or None

        # Keep env mirrored to the fresh token so any other code path that still
        # reads the env directly stays consistent.
        if token:
            os.environ["TELEGRAM_BOT_TOKEN"] = token
        self._token_cache = token
        self._token_cache_ts = now
        return token

    def invalidate_token_cache(self) -> None:
        """Drop the cached token so the next get_bot_token() re-reads the DB.
        Called when the admin changes the token (instant propagation)."""
        self._token_cache = None
        self._token_cache_ts = 0.0
    
    async def get_admin_telegram_id(self) -> Optional[str]:
        """Get admin telegram ID from database"""
        settings = await self.db.admin_settings.find_one({"type": "telegram_bot"}, {"_id": 0})
        return settings.get("admin_telegram_id") if settings else None
    
    # chat_id -> "blocked" | "not_found" | "error": why the last delivery to that chat failed
    last_failure: Dict[str, str] = {}

    @classmethod
    def _note_failure(cls, chat_id, status: int, text: str) -> None:
        t = (text or "").lower()
        kind = ("blocked" if status == 403 or "blocked" in t or "deactivated" in t
                else "not_found" if "chat not found" in t or "user not found" in t else "error")
        if len(cls.last_failure) > 20000:
            cls.last_failure.clear()
        cls.last_failure[str(chat_id)] = kind

    async def send_message(self, chat_id: str, text: str, parse_mode: str = "HTML", 
                          reply_markup: Optional[Dict] = None,
                          link_preview_options: Optional[Dict] = None) -> bool:
        """Send a message via Telegram bot.

        Retries once on network/timeout errors (the intermittent empty
        `Error sending Telegram message:` in the logs is an aiohttp
        TimeoutError, whose str() is empty — which previously made a menu
        message silently disappear). A non-200 from Telegram (payload rejected)
        is NOT retried here — `safe_send_menu` handles keyboard degradation.
        """
        bot_token = await self.get_bot_token()
        if not bot_token or not chat_id:
            logger.warning("Bot token or chat_id not configured")
            return False

        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        # Optional link-preview control (Bot API 7.0+). Used by announcements to
        # show a large image ABOVE long text in a SINGLE message (photo captions
        # are capped at 1024 chars, message text is not).
        if link_preview_options is not None:
            payload["link_preview_options"] = link_preview_options

        last_err = None
        session = await self._get_session()
        for attempt in (1, 2):
            try:
                response = await session.post(
                    f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                    proxy=_telegram_proxy(),
                )
                if response.status == 200:
                    logger.debug(f"Telegram message sent to {chat_id}")   # debug: 1 line per message floods logs on broadcasts
                    self.last_failure.pop(str(chat_id), None)
                    return True
                # Rate limited by Telegram — honor the retry_after hint, then
                # retry once. This is the key guard for large broadcasts.
                if response.status == 429:
                    try:
                        _j = await response.json()
                        retry_after = int((_j.get("parameters") or {}).get("retry_after") or 1)
                    except Exception:
                        retry_after = 1
                    retry_after = min(max(retry_after, 1), 30)
                    logger.warning(f"Telegram 429 for {chat_id}: waiting {retry_after}s")
                    await asyncio.sleep(retry_after)
                    if attempt == 1:
                        continue
                    return False
                # Telegram rejected the payload — do not retry (caller degrades).
                response_text = await response.text()
                self._note_failure(chat_id, response.status, response_text)
                if response.status in (400, 403):
                    logger.info(f"Telegram refused message to {chat_id} (HTTP {response.status}): {response_text[:160]}")
                else:
                    logger.error(f"Failed to send Telegram message (HTTP {response.status}): {response_text}")
                return False
            except Exception as e:
                # Network / timeout error — response never arrived, safe to retry.
                last_err = e
                logger.warning(
                    f"send_message attempt {attempt} to {chat_id} failed: "
                    f"{type(e).__name__}: {e or '(timeout)'}"
                )
                if attempt == 1:
                    await asyncio.sleep(0.3)
                    continue
        logger.error(
            f"Error sending Telegram message to {chat_id} after retries: "
            f"{type(last_err).__name__ if last_err else 'unknown'}: {last_err or '(timeout)'}"
        )
        return False

    async def send_document(self, chat_id: str, content, filename: str = "file.txt",
                            caption: str = "", parse_mode: str = "HTML") -> bool:
        """Send a document (file) to a chat. `content` may be bytes or str."""
        bot_token = await self.get_bot_token()
        if not bot_token or not chat_id:
            logger.warning("send_document: bot token or chat_id not configured")
            return False
        if isinstance(content, str):
            content = content.encode("utf-8")
        try:
            session = await self._get_session()
            form = aiohttp.FormData()
            form.add_field("chat_id", str(chat_id))
            if caption:
                form.add_field("caption", caption[:1024])
                form.add_field("parse_mode", parse_mode)
            form.add_field("document", content, filename=filename,
                           content_type="text/plain; charset=utf-8")
            response = await session.post(
                f"{TELEGRAM_API_BASE}/bot{bot_token}/sendDocument",
                data=form,
                timeout=aiohttp.ClientTimeout(total=30),
                proxy=_telegram_proxy(),
            )
            if response.status == 200:
                logger.info(f"Telegram document sent to {chat_id}")
                return True
            txt = await response.text()
            logger.error(f"send_document failed (HTTP {response.status}): {txt}")
            return False
        except Exception as e:
            logger.error(f"send_document error to {chat_id}: {type(e).__name__}: {e}")
            return False


    async def safe_send_menu(self, chat_id: str, text: str,
                             reply_markup: Optional[Dict] = None,
                             parse_mode: str = "HTML",
                             context: str = "menu") -> bool:
        """Send a MENU message that ALWAYS gets delivered.

        Menu keyboards use Telegram Mini App (`web_app`) buttons, which Telegram
        rejects wholesale (BUTTON_TYPE_INVALID / WEBAPP_URL_INVALID) when the
        Mini App URL isn't registered in BotFather or is on another domain —
        leaving the user with no message AND no buttons (the reported
        `status_businesses` / menu-button failures). This helper degrades
        gracefully so a keyboard message is never lost:
          1) full keyboard (with web_app buttons)
          2) same keyboard, web_app → plain url buttons
          3) plain-text (no HTML) + the url keyboard

        Retries fire ONLY when the previous attempt failed (send_message returns
        False on any non-200), so a successfully-delivered message is never
        duplicated. Use this in EVERY menu handler that renders web_app buttons.
        """
        ok = await self.send_message(chat_id, text, parse_mode=parse_mode, reply_markup=reply_markup)
        if ok:
            return True

        url_keyboard = _urlify_keyboard(reply_markup)
        if url_keyboard != reply_markup:
            logger.warning(
                f"{context}: keyboard with web_app rejected for chat_id={chat_id}, "
                f"retrying with url-only keyboard (register the Mini App URL in "
                f"BotFather to enable the in-app button)."
            )
        ok = await self.send_message(chat_id, text, parse_mode=parse_mode, reply_markup=url_keyboard)
        if ok:
            return True

        # Last resort: drop HTML formatting (in case the body itself was the
        # rejection cause) but KEEP the url keyboard so buttons still show.
        ok = await self.send_message(chat_id, text, parse_mode="", reply_markup=url_keyboard)
        if not ok:
            logger.error(f"{context}: url-only keyboard also failed for chat_id={chat_id}.")
        return ok

    HOME_LABELS = {
        "ru": "🏠 На главную", "en": "🏠 Main menu",
        "es": "🏠 Menú principal", "zh": "🏠 主菜单",
        "fr": "🏠 Menu principal", "de": "🏠 Hauptmenü",
        "ja": "🏠 メインメニュー", "ko": "🏠 메인 메뉴",
    }

    def _home_button(self, lang: str = "ru") -> Dict:
        """Inline button that returns the user to the bot main menu (cmd_start)."""
        return {
            "text": self.HOME_LABELS.get(lang, self.HOME_LABELS["en"]),
            "callback_data": "back_to_menu",
        }

    async def send_photo(self, chat_id: str, photo_url: str, caption: str = "",
                         parse_mode: str = "HTML",
                         reply_markup: Optional[Dict] = None) -> bool:
        """Send a photo with optional caption + inline keyboard.

        Supports two photo sources:
          * Public HTTP(S) URL — sent as JSON `photo` field, Telegram fetches.
          * data:image/...;base64,... — decoded and uploaded as multipart bytes
            (Telegram does NOT accept data: URIs as URL, must be raw upload).
        """
        bot_token = await self.get_bot_token()
        if not bot_token or not chat_id or not photo_url:
            return False
        try:
            import base64 as _b64
            url = f"{TELEGRAM_API_BASE}/bot{bot_token}/sendPhoto"
            caption_clipped = caption[:1024] if caption else ""

            if photo_url.startswith("data:"):
                # Parse `data:<mime>;base64,<payload>`
                try:
                    head, b64 = photo_url.split(",", 1)
                    mime = head.split(";")[0].split(":", 1)[1] if ":" in head else "image/png"
                    raw = _b64.b64decode(b64)
                except Exception as e:
                    logger.error(f"Invalid data URI for photo: {e}")
                    return False
                ext = mime.split("/")[-1] or "png"
                client = await self._get_session()
                form = aiohttp.FormData()
                form.add_field("chat_id", str(chat_id))
                if caption_clipped:
                    form.add_field("caption", caption_clipped)
                    form.add_field("parse_mode", parse_mode)
                if reply_markup:
                    import json as _json
                    form.add_field("reply_markup", _json.dumps(reply_markup))
                form.add_field("photo", raw, filename=f"image.{ext}", content_type=mime)
                response = await client.post(url, data=form, timeout=aiohttp.ClientTimeout(total=30))
                if response.status == 200:
                    self.last_failure.pop(str(chat_id), None)
                    return True
                txt = await response.text()
                self._note_failure(chat_id, response.status, txt)
                logger.info(f"sendPhoto (multipart) failed: {txt[:200]}")
                return False

            # HTTPS URL — Telegram fetches it
            client = await self._get_session()
            payload = {
                "chat_id": chat_id,
                "photo": photo_url,
                "caption": caption_clipped,
                "parse_mode": parse_mode,
            }
            if reply_markup:
                payload["reply_markup"] = reply_markup
            response = await client.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=15))
            if response.status == 200:
                self.last_failure.pop(str(chat_id), None)
                return True
            txt = await response.text()
            self._note_failure(chat_id, response.status, txt)
            logger.info(f"sendPhoto failed: {txt[:200]}")
            return False
        except Exception as e:
            logger.error(f"Error sending Telegram photo: {e}")
            return False
    
    async def delete_message(self, chat_id: str, message_id: int) -> bool:
        """Delete a Telegram message — used by Help → Back to remove the previous message before navigating."""
        bot_token = await self.get_bot_token()
        if not bot_token or not chat_id or not message_id:
            return False
        try:
            client = await self._get_session()
            response = await client.post(
                f"{TELEGRAM_API_BASE}/bot{bot_token}/deleteMessage",
                json={"chat_id": chat_id, "message_id": message_id},
                timeout=aiohttp.ClientTimeout(total=5),
            )
            return response.status == 200
        except Exception as e:
            logger.warning(f"deleteMessage failed: {e}")
            return False
    
    async def process_webhook(self, update: Dict) -> Dict:
        """Process incoming webhook update from Telegram"""
        try:
            # Diagnostic breadcrumb: every incoming update is logged with enough
            # metadata to reconstruct the flow after the fact. This makes it
            # possible to see on prod (`grep TG_WH /var/log/…`) whether /start
            # is even reaching the backend when users report silence.
            _uid = update.get("update_id")
            _has_msg = bool(update.get("message"))
            _has_cb = bool(update.get("callback_query"))
            _txt = (update.get("message") or {}).get("text", "") if _has_msg else ""
            _cb = (update.get("callback_query") or {}).get("data", "") if _has_cb else ""
            _log_txt = "<code>" if _txt.strip().isdigit() else _txt[:40]          # 2FA codes never reach the log
            logger.info(f"TG_WH id={_uid} msg={_has_msg} cb={_has_cb} txt={_log_txt!r} cb_data={_cb[:40]!r}")

            if not update.get("message"):
                # Handle callback queries (button clicks)
                if update.get("callback_query"):
                    return await self.handle_callback_query(update["callback_query"])
                return {"ok": True}
            
            message = update["message"]
            chat_id = str(message.get("chat", {}).get("id", ""))
            text = message.get("text", "")
            _from = message.get("from", {}) or {}
            username = _from.get("username", "")
            user_id_tg = str(_from.get("id", ""))
            first_name = _from.get("first_name", "")
            last_name = _from.get("last_name", "")
            is_premium = bool(_from.get("is_premium", False))
            tg_language_code = _from.get("language_code") or ""
            
            if not chat_id:
                return {"ok": True}
            
            # A 2FA code for a pending withdrawal approval (admin) — handled first
            if await self._maybe_handle_withdrawal_2fa(chat_id, text, message):
                return {"ok": True}

            # Record activity FIRE-AND-FORGET so message handling isn't delayed
            # by the DB write (see _track_activity).
            if username or user_id_tg:
                self._spawn(self._track_activity(chat_id, user_id_tg, username, first_name, is_premium, tg_language_code))
            
            # Stash the raw last_name so downstream handlers (cmd_start login
            # deep-link → confirm_login_link) can build a full display_name.
            self._last_last_name = last_name
            
            # Parse command
            if text.startswith("/"):
                return await self.handle_command(chat_id, text, username, user_id_tg, first_name)

            # Free-text message: if the user is in a support session (Help →
            # Support → Start chat), forward it into the support inbox.
            if text.strip():
                tg_map = await self.db.telegram_mappings.find_one(
                    {"chat_id": chat_id}, {"awaiting_support": 1, "support_mode": 1, "_id": 0}
                )
                if tg_map and (tg_map.get("support_mode") or tg_map.get("awaiting_support")):
                    return await self.submit_support_message(chat_id, text)

            return {"ok": True}
            
        except Exception as e:
            logger.error(f"Telegram webhook error: {e}")
            return {"ok": True}
    
    async def handle_command(self, chat_id: str, text: str, username: str, 
                           user_id_tg: str, first_name: str) -> Dict:
        """Handle bot commands"""
        
        # Parse command and arguments
        parts = text.split()
        command = parts[0].lower().split("@")[0]  # Remove @botname suffix
        args = parts[1:] if len(parts) > 1 else []
        
        # Check if this is admin
        admin_id = await self.get_admin_telegram_id()
        is_admin = admin_id and (user_id_tg == admin_id or chat_id == admin_id)

        # If this user is a B2B partner, they only ever see their partner
        # panel regardless of what they type (except /start with a deep-link
        # token, which is handled inside cmd_start).
        try:
            from b2b_partners import get_partner_for_telegram
            _partner = await get_partner_for_telegram(
                self.db, telegram_user_id=user_id_tg, username=username,
            )
            if _partner and not is_admin:
                # For /start with args, keep the deep-link flow (may be a
                # magic-login token or a p_<code> that we should not swallow).
                if command == "/start" and args:
                    pass
                else:
                    return await self.cmd_b2b_panel(chat_id, username, user_id_tg)
        except Exception as _e:
            logger.debug(f"b2b partner check in handle_command failed: {_e}")

        # Command handlers
        if command == "/start":
            return await self.cmd_start(chat_id, username, first_name, args)
        elif command == "/status" or command == "/balance":
            return await self.cmd_status(chat_id, username, user_id_tg)
        elif command == "/businesses" or command == "/biz":
            return await self.cmd_businesses(chat_id, username, user_id_tg)
        elif command == "/help":
            return await self.cmd_help(chat_id, is_admin)
        elif command == "/link":
            return await self.cmd_link(chat_id, username, args)
        elif command == "/b2b" or command == "/partner":
            return await self.cmd_b2b_panel(chat_id, username, user_id_tg)
        
        # Admin commands
        if is_admin:
            if command == "/admin":
                return await self.cmd_admin(chat_id)
            elif command == "/stats":
                return await self.cmd_admin_stats(chat_id)
            elif command == "/withdrawals" or command == "/wd":
                return await self.cmd_admin_withdrawals(chat_id)
            elif command == "/users":
                return await self.cmd_admin_users(chat_id)
            elif command == "/broadcast":
                return await self.cmd_admin_broadcast(chat_id, " ".join(args))
        
        return {"ok": True}
    
    # ── Channel-subscription gate ────────────────────────────────────────────
    SUB_GATE_TEXT = {
        "ru": ("🏙 <b>Добро пожаловать в GRAM CITY!</b>\n\n"
               "Чтобы получить доступ к игре и начать строить свою экономическую "
               "империю, пожалуйста, подпишитесь на наш официальный новостной канал.\n\n"
               "После подписки нажмите кнопку проверки ниже!"),
        "en": ("🏙 <b>Welcome to GRAM CITY!</b>\n\n"
               "To get access to the game and start building your economic empire, "
               "please subscribe to our official news channel.\n\n"
               "After subscribing, tap the check button below!"),
        "es": ("🏙 <b>¡Bienvenido a GRAM CITY!</b>\n\n"
               "Para acceder al juego y empezar a construir tu imperio económico, "
               "suscríbete a nuestro canal oficial de noticias.\n\n"
               "Después de suscribirte, ¡pulsa el botón de verificación abajo!"),
        "zh": ("🏙 <b>欢迎来到 GRAM CITY！</b>\n\n"
               "要进入游戏并开始建立你的经济帝国，请订阅我们的官方新闻频道。\n\n"
               "订阅后，请点击下方的检查按钮！"),
        "fr": ("🏙 <b>Bienvenue sur GRAM CITY !</b>\n\n"
               "Pour accéder au jeu et commencer à bâtir ton empire économique, "
               "abonne-toi à notre chaîne d'actualités officielle.\n\n"
               "Après l'abonnement, appuie sur le bouton de vérification ci-dessous !"),
        "de": ("🏙 <b>Willkommen bei GRAM CITY!</b>\n\n"
               "Um Zugang zum Spiel zu erhalten und dein Wirtschaftsimperium "
               "aufzubauen, abonniere bitte unseren offiziellen News-Kanal.\n\n"
               "Tippe nach dem Abonnieren auf die Prüf-Schaltfläche unten!"),
        "ja": ("🏙 <b>GRAM CITY へようこそ！</b>\n\n"
               "ゲームにアクセスして経済帝国を築き始めるには、公式ニュースチャンネルに"
               "登録してください。\n\n登録後、下の確認ボタンを押してください！"),
        "ko": ("🏙 <b>GRAM CITY에 오신 것을 환영합니다!</b>\n\n"
               "게임에 접속하고 경제 제국을 건설하려면 공식 뉴스 채널을 구독해 주세요.\n\n"
               "구독 후 아래 확인 버튼을 눌러 주세요!"),
    }
    SUB_BTN_SUBSCRIBE = {
        "ru": "📢 Подписаться на канал", "en": "📢 Subscribe to channel",
        "es": "📢 Suscribirse al canal", "zh": "📢 订阅频道",
        "fr": "📢 S'abonner à la chaîne", "de": "📢 Kanal abonnieren",
        "ja": "📢 チャンネルに登録", "ko": "📢 채널 구독",
    }
    SUB_BTN_CHECK = {
        "ru": "🔄 Проверить подписку", "en": "🔄 Check subscription",
        "es": "🔄 Comprobar suscripción", "zh": "🔄 检查订阅",
        "fr": "🔄 Vérifier l'abonnement", "de": "🔄 Abo prüfen",
        "ja": "🔄 登録を確認", "ko": "🔄 구독 확인",
    }
    SUB_NOT_SUBSCRIBED = {
        "ru": "❌ Вы не подписаны", "en": "❌ You are not subscribed",
        "es": "❌ No estás suscrito", "zh": "❌ 您尚未订阅",
        "fr": "❌ Vous n'êtes pas abonné", "de": "❌ Du bist nicht abonniert",
        "ja": "❌ 登録されていません", "ko": "❌ 구독하지 않았습니다",
    }

    async def is_subscribed(self, user_id, channel_id: Optional[str] = None) -> Optional[bool]:
        """True/False if the user belongs to `channel_id` (defaults to the
        global REQUIRED_CHANNEL_ID when not provided — used by task
        verification with a per-task channel).
        Returns None when we CANNOT verify (bot not a channel admin yet /
        channel misconfigured) so callers can FAIL-OPEN instead of locking
        real users out during setup."""
        target_channel = (channel_id or REQUIRED_CHANNEL_ID)
        bot_token = await self.get_bot_token()
        if not bot_token or not user_id:
            return None
        try:
            uid = int(str(user_id))
        except Exception:
            return None
        try:
            client = await self._get_session()
            resp = await client.post(
                f"{TELEGRAM_API_BASE}/bot{bot_token}/getChatMember",
                json={"chat_id": target_channel, "user_id": uid},
                timeout=aiohttp.ClientTimeout(total=8),
                proxy=_telegram_proxy(),
            )
            data = await resp.json()
            if not data.get("ok"):
                logger.warning(
                    f"getChatMember failed for channel={target_channel}: "
                    f"{data.get('description')} — failing OPEN"
                )
                return None
            status = (data.get("result") or {}).get("status", "")
            return status in ("creator", "administrator", "member", "restricted")
        except Exception as e:
            logger.warning(f"is_subscribed error: {e} — failing OPEN")
            return None

    async def get_chat_boosts(self, chat_id, user_id) -> dict:
        """Check whether `user_id` currently boosts `chat_id` via the official
        Bot API method getUserChatBoosts(chat_id, user_id).

        The bot MUST be an administrator of the channel, otherwise Telegram
        returns an access error. Returns a structured dict so the caller can
        distinguish "no boost" (ok=True, boosts=[]) from a hard failure
        (ok=False, error/error_code set — bot not admin, wrong chat_id, rate
        limit, network error)."""
        bot_token = await self.get_bot_token()
        if not bot_token:
            return {"ok": False, "boosts": [], "error": "bot_token_missing"}
        if not chat_id:
            return {"ok": False, "boosts": [], "error": "chat_id_missing"}
        try:
            uid = int(str(user_id))
        except Exception:
            return {"ok": False, "boosts": [], "error": "invalid_user_id"}
        try:
            client = await self._get_session()
            resp = await client.post(
                f"{TELEGRAM_API_BASE}/bot{bot_token}/getUserChatBoosts",
                json={"chat_id": chat_id, "user_id": uid},
                timeout=aiohttp.ClientTimeout(total=8),
                proxy=_telegram_proxy(),
            )
            data = await resp.json()
            if not data.get("ok"):
                logger.warning(
                    f"getUserChatBoosts failed for chat={chat_id} user={uid}: "
                    f"{data.get('description')}"
                )
                return {
                    "ok": False,
                    "boosts": [],
                    "error": data.get("description") or "telegram_error",
                    "error_code": data.get("error_code"),
                }
            boosts = ((data.get("result") or {}).get("boosts")) or []
            return {"ok": True, "boosts": boosts, "error": None}
        except Exception as e:
            logger.warning(f"get_chat_boosts error: {e}")
            return {"ok": False, "boosts": [], "error": str(e)}


    async def _send_subscription_gate(self, chat_id: str, lang: str) -> bool:
        """Send the 'please subscribe to the channel' gate message."""
        msg = self.SUB_GATE_TEXT.get(lang, self.SUB_GATE_TEXT["en"])
        keyboard = {
            "inline_keyboard": [
                [{"text": self.SUB_BTN_SUBSCRIBE.get(lang, self.SUB_BTN_SUBSCRIBE["en"]),
                  "url": TELEGRAM_CHANNEL_URL}],
                [{"text": self.SUB_BTN_CHECK.get(lang, self.SUB_BTN_CHECK["en"]),
                  "callback_data": "check_subscription"}],
            ]
        }
        return await self.send_message(chat_id, msg, reply_markup=keyboard)
    
    async def cmd_start(self, chat_id: str, username: str, first_name: str, args: list) -> Dict:
        """Handle /start command"""
        # ── TEMP TIMING INSTRUMENTATION ──────────────────────────────────
        # Logs how long each step takes so prod logs pinpoint the slow line
        # (grep `cmd_start timing`). Any step > 1s is flagged with ⚠️.
        _t0 = time.perf_counter()
        _tprev = _t0
        def _tick(label: str):
            nonlocal _tprev
            now = time.perf_counter()
            dt = (now - _tprev) * 1000
            total = (now - _t0) * 1000
            flag = " ⚠️SLOW" if dt > 1000 else ""
            logger.info(f"[cmd_start timing] {label}: +{dt:.0f}ms (total {total:.0f}ms){flag}")
            _tprev = now

        # Check if this is a deep link with token
        if args:
            token = args[0]
            # Universal browser login via /api/auth/telegram/login-link/start:
            # payload is `login_<jti>`. Delegate to the login-link helper and
            # reply with its message; the browser tab will pick up the JWT via
            # /login-link/status/{jti} within ~2s.
            if isinstance(token, str) and token.startswith("login_"):
                try:
                    from routes.telegram_login_link import confirm_login_link
                    tg_last_name = getattr(self, "_last_last_name", "") or ""
                    result = await confirm_login_link(
                        self.db, token, str(chat_id), username, first_name, tg_last_name,
                    )
                    await self.send_message(
                        chat_id,
                        result.get("message") or ("✅ OK" if result.get("ok") else "❌ Error"),
                    )
                    return {"ok": True}
                except Exception as _e:
                    logger.warning(f"tg login-link confirm failed: {_e}")
                    try:
                        from routes.telegram_notifications import tmsg as _tmsg, resolve_bot_language as _resolve_lang
                        _lang = await _resolve_lang(self.db, str(chat_id))
                        _err_msg = _tmsg("login_confirm_failed", _lang)
                    except Exception:
                        _err_msg = "❌ Couldn't confirm login. Please try again from the site."
                    await self.send_message(chat_id, _err_msg)
                    return {"ok": True}
            return await self.process_link_token(chat_id, username, token)

        # If this user is a B2B partner, reply ONLY with the partner panel —
        # they don't see the regular player menu.
        try:
            from b2b_partners import get_partner_for_telegram
            partner = await get_partner_for_telegram(
                self.db, telegram_user_id=chat_id, username=username,
            )
            if partner:
                return await self.cmd_b2b_panel(chat_id, username, chat_id)
        except Exception as _e:
            logger.debug(f"b2b partner check in cmd_start failed: {_e}")

        # Check if user has selected language
        tg_user = await self.db.telegram_mappings.find_one({"chat_id": chat_id}, {"language": 1, "_id": 0})
        _tick("telegram_mappings.find_one")

        # Determine support entry URL based on whether user is a support agent
        agent_doc = None
        try:
            agent_doc = await self.db.support_agents.find_one(
                {"telegram_id": str(chat_id), "is_removed": {"$ne": True}},
                {"_id": 0, "display_name": 1, "telegram_id": 1},
            )
        except Exception:
            agent_doc = None
        _tick("support_agents.find_one")

        # Build base URL — robust resolution that works in dev, in /app
        # containers, AND on the production VPS at /var/www/gramcity. We try
        # in this order so the first non-empty source wins:
        #   1. Settings doc `support_settings.public_url` (admin-configurable)
        #   2. Env vars BACKEND_URL / REACT_APP_BACKEND_URL / PUBLIC_URL
        #   3. Several candidate frontend/.env paths (dev container, VPS)
        #   4. Auto-detect via Telegram getWebhookInfo (last-resort)
        #   5. Empty → caller MUST send a plain text fallback.
        backend_url = ""

        # 0) Admin-configured «URL открытия приложения» (Промо в админке) — wins.
        try:
            _tg = await self.db.game_settings.find_one(
                {"type": "telegram_settings"}, {"_id": 0, "app_url": 1}
            )
            _admin_url = str((_tg or {}).get("app_url") or "").strip()
            if _admin_url:
                backend_url = _admin_url.rstrip("/")
        except Exception:
            pass

        # 1) DB-stored public URL (preferred)
        try:
            _s = await self.db.support_settings.find_one({"_id": "main"})
            if not backend_url and _s and _s.get("public_url"):
                backend_url = str(_s["public_url"]).rstrip("/")
        except Exception:
            pass

        # 2) Environment
        if not backend_url:
            backend_url = (
                os.environ.get("BACKEND_URL", "").rstrip("/")
                or os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
                or os.environ.get("PUBLIC_URL", "").rstrip("/")
            )

        # 3) frontend/.env at multiple candidate paths
        if not backend_url:
            import pathlib as _pl
            _here = _pl.Path(__file__).resolve().parent
            candidate_paths = [
                "/app/frontend/.env",                       # dev container
                str(_here.parent / "frontend" / ".env"),    # repo layout
                "/var/www/gramcity/frontend/.env",          # production VPS
                "/srv/gramcity/frontend/.env",
                "/opt/gramcity/frontend/.env",
            ]
            for _p in candidate_paths:
                try:
                    with open(_p, "r") as _f:
                        for _line in _f:
                            if _line.startswith("REACT_APP_BACKEND_URL="):
                                backend_url = _line.split("=", 1)[1].strip().strip('"').strip("'").rstrip("/")
                                break
                    if backend_url:
                        break
                except Exception:
                    continue

        # 4) Telegram getWebhookInfo — the webhook URL is publicly reachable
        # by definition, so we can derive the public origin from it.
        if not backend_url:
            try:
                bot_token = await self.get_bot_token()
                if bot_token:
                    _client = await self._get_session()
                    _r = await _client.get(
                        f"{TELEGRAM_API_BASE}/bot{bot_token}/getWebhookInfo",
                        timeout=aiohttp.ClientTimeout(total=5),
                    )
                    _j = await _r.json() if _r.status == 200 else {}
                    _whurl = (_j.get("result") or {}).get("url") or ""
                    if _whurl.startswith("https://"):
                            from urllib.parse import urlparse
                            _p = urlparse(_whurl)
                            backend_url = f"{_p.scheme}://{_p.netloc}".rstrip("/")
                            # Cache it so we don't hit Telegram on every /start
                            try:
                                await self.db.support_settings.update_one(
                                    {"_id": "main"},
                                    {"$set": {"public_url": backend_url}},
                                    upsert=True,
                                )
                            except Exception:
                                pass
            except Exception as _e:
                logger.warning(f"Could not derive public URL from webhook: {_e}")

        hidden_path = "sys-ops-panel-x9k2m7q"
        try:
            _s = await self.db.support_settings.find_one({"_id": "main"})
            if _s and _s.get("hidden_path"):
                hidden_path = _s["hidden_path"]
        except Exception:
            pass
        agent_url = f"{backend_url}/{hidden_path}" if backend_url else f"/{hidden_path}"
        user_support_url = f"{backend_url}/?support=open" if backend_url else "/?support=open"
        _tick("backend_url resolution")

        # Telegram REJECTS the whole sendMessage call when any inline-keyboard
        # button has a `web_app` (Mini App) URL that isn't a valid https:// URL.
        # That was why /start could silently fail in production: backend_url was
        # unresolved → user_support_url became the relative "/?support=open" →
        # Telegram returned 400 and the bot appeared silent. From here on we use
        # this helper to decide whether a URL is safe to embed as a Mini App
        # button; when it isn't, callers fall back to a plain `url` button or
        # drop the button entirely.
        def _is_https_url(u: str) -> bool:
            return isinstance(u, str) and u.startswith("https://")

        # Helper: build magic-link with auto-login JWT for the user that owns this TG chat_id
        async def _build_magic_url(base_url: str, target_chat_id: str) -> str:
            try:
                user_doc = await self.db.users.find_one(
                    {"$or": [{"telegram_chat_id": str(target_chat_id)}, {"telegram_id": str(target_chat_id)}]},
                    {"_id": 0, "email": 1, "username": 1, "wallet_address": 1, "session_id": 1},
                )
                if not user_doc:
                    return base_url
                identifier = user_doc.get("email") or user_doc.get("username") or user_doc.get("wallet_address")
                if not identifier:
                    return base_url
                from auth_handler import create_token
                token = create_token({"sub": identifier}, session_id=user_doc.get("session_id"))
                sep = "&" if "?" in base_url else "?"
                return f"{base_url}{sep}auth={token}"
            except Exception as _e:
                logger.debug(f"magic-link build failed: {_e}")
                return base_url

        # If this telegram user is a registered agent — issue one-time login token + send 2 buttons
        if agent_doc:
            display_name = agent_doc.get("display_name", "Agent")
            try:
                from support_handler import issue_agent_login_token
                one_time = await issue_agent_login_token(str(chat_id))
            except Exception as _e:
                logger.error(f"issue_agent_login_token failed: {_e}")
                one_time = None

            if one_time:
                sep = "&" if "?" in agent_url else "?"
                signed_url = f"{agent_url}{sep}login_token={one_time}"
            else:
                signed_url = agent_url

            msg = (
                f"🛡️ <b>GRAM City Support — Agent Panel</b>\n\n"
                f"Добро пожаловать, <b>{display_name}</b>!\n\n"
                f"⚠️ Это <b>одноразовая</b> ссылка для входа (действует 10 минут).\n\n"
                f"🌐 <b>Рекомендуем открывать в браузере</b> — при открытии как мини-приложение "
                f"Telegram выполняет авто-вход и вы можете попасть в панель как обычный игрок.\n\n"
                f"🔗 Ссылка для браузера (скопируйте при необходимости):\n"
                f"<a href=\"{signed_url}\">{signed_url}</a>"
            )
            # First attempt: with the Telegram Mini App button. This requires
            # the bot to have its Mini App URL registered in BotFather AND
            # `signed_url` to live on the same domain. If either condition is
            # not met, Telegram rejects the whole sendMessage with
            # `BUTTON_TYPE_INVALID` / `WEBAPP_URL_INVALID` and the agent gets
            # NOTHING — which previously made it look like the bot was silent
            # for agents only. We now fall back to a simple URL-button keyboard
            # so the agent always receives the login link.
            # The BROWSER button is listed FIRST (primary) because opening the
            # panel as a Mini App triggers Telegram's player auto-login.
            keyboard_full = {
                "inline_keyboard": [
                    [{"text": "🌐 Открыть в браузере", "url": signed_url}],
                    [{"text": "📱 Открыть в приложении", "web_app": {"url": signed_url}}],
                ]
            }
            ok = await self.send_message(chat_id, msg, reply_markup=keyboard_full)
            if not ok:
                logger.warning(
                    "Agent message with web_app button failed, retrying with url-only keyboard. "
                    "Add the Mini App URL to BotFather to enable the in-app button."
                )
                keyboard_simple = {
                    "inline_keyboard": [
                        [{"text": "🌐 Открыть панель агента", "url": signed_url}],
                    ]
                }
                ok = await self.send_message(chat_id, msg, reply_markup=keyboard_simple)
                if not ok:
                    # Last-ditch: plain text with the link inline so the agent
                    # at least sees SOMETHING and can copy-paste the URL.
                    await self.send_message(
                        chat_id,
                        msg + f"\n\n<a href=\"{signed_url}\">🔗 {signed_url}</a>",
                    )
            return {"ok": True}

        # Also build magic-link for the support button (user side) when account is linked.
        # NOTE: we only do this work when the user has already picked a language and
        # actually needs the magic-link URL. On the very first /start (no language yet)
        # we skip this — it was hitting the DB and dragging first-time onboarding.
        if tg_user and tg_user.get("language"):
            user_support_url = await _build_magic_url(user_support_url, chat_id)
        
        if not tg_user or not tg_user.get("language"):
            # Show language selection — all 9 languages supported on the website.
            msg = ("🏙️ <b>GRAM City</b>\n\n"
                   "🌍 <b>Выберите язык / Select language / Seleccione idioma</b>")
            keyboard = {
                "inline_keyboard": [
                    [
                        {"text": "🇬🇧 English", "callback_data": "lang_en"},
                        {"text": "🇷🇺 Русский", "callback_data": "lang_ru"},
                    ],
                    [
                        {"text": "🇪🇸 Español", "callback_data": "lang_es"},
                        {"text": "🇨🇳 中文", "callback_data": "lang_zh"},
                    ],
                    [
                        {"text": "🇫🇷 Français", "callback_data": "lang_fr"},
                        {"text": "🇩🇪 Deutsch", "callback_data": "lang_de"},
                    ],
                    [
                        {"text": "🇯🇵 日本語", "callback_data": "lang_ja"},
                        {"text": "🇰🇷 한국어", "callback_data": "lang_ko"},
                    ],
                    [
                        {"text": "🇮🇩 Bahasa Indonesia", "callback_data": "lang_id"},
                    ],
                ]
            }
            # Robust send: if the HTML+keyboard message fails at Telegram's end
            # (bad parse_mode, invalid emoji rendering, oversized payload, etc.)
            # retry with an unstyled plain-text message so the user is never
            # left with total silence on /start.
            ok = await self.send_message(chat_id, msg, reply_markup=keyboard)
            if not ok:
                logger.warning(f"cmd_start language-select send failed for chat_id={chat_id}, retrying plain-text")
                ok = await self.send_message(
                    chat_id,
                    "GRAM City\n\nChoose your language / Выберите язык",
                    reply_markup=keyboard,
                    parse_mode="",
                )
                if not ok:
                    await self.send_message(
                        chat_id,
                        "GRAM City. Send /start again if you don't see language buttons.",
                        parse_mode="",
                    )
            return {"ok": True}
        
        # Check if user already linked
        user = await self.find_user_by_telegram(chat_id, username)
        lang = tg_user.get("language", "ru")

        # ── Channel-subscription gate ────────────────────────────────────────
        # Users must join the news channel before they can use the bot. In a
        # private chat `chat_id` IS the user's Telegram id, so we can check it
        # directly. Fail-OPEN when we can't verify (is_subscribed → None).
        sub = await self.is_subscribed(chat_id)
        if sub is False:
            await self._send_subscription_gate(chat_id, lang)
            return {"ok": True}
        
        if user:
            balance = user.get('balance_ton', 0)

            # v2.3.x: referral link for the main menu (shown right below balance)
            ref_stats = await self._referral_stats(user)
            ref_link = ref_stats.get("link") or ""
            ref_block = ""
            if ref_link:
                ref_block = (
                    "\n\n"
                    f"{self._stl('referral_link_title', lang)}\n"
                    f"<code>{ref_link}</code>\n"
                    f"{self._stl('referral_link_hint', lang)}"
                )

            from bot_i18n import bt as _bt
            msg = _bt("welcome_linked", lang, name=user.get('username', first_name),
                      ton=f"{balance:.2f}", city=f"{balance * 1000:,.0f}", ref=ref_block)

            # Only use web_app buttons for valid https URLs (Telegram
            # requirement). Otherwise fall back to a plain url button that
            # opens the site in the browser.
            # Two entry points, per user feedback:
            #   1) «Открыть игру» — Telegram Mini App (web_app) — плавно
            #      открывает игру внутри Telegram.
            #   2) «Открыть на сайте» — обычный `url` — откроет игру во
            #      внешнем браузере, если Mini App не работает.
            open_url = backend_url if _is_https_url(backend_url) else "https://gramcity.games"
            play_labels = {
                "ru": "🎮 Открыть игру", "en": "🎮 Open Game",
                "es": "🎮 Abrir juego", "zh": "🎮 打开游戏",
                "fr": "🎮 Ouvrir le jeu", "de": "🎮 Spiel öffnen",
                "ja": "🎮 ゲームを開く", "ko": "🎮 게임 열기",
            }
            play_lbl = play_labels.get(lang, play_labels["en"])
            # Plain URL link (no Telegram Mini App / web_app button). The
            # duplicate "Открыть на сайте" button was removed per user request.
            open_btn = {"text": play_lbl, "url": open_url}

            # 1.2: Support is now available ONLY inside «Помощь» (Help) as a
            # full in-bot chat session — no standalone Support button here.
            status_labels = {
                "ru": "📊 Статус аккаунта", "en": "📊 Account status",
                "es": "📊 Estado de cuenta", "zh": "📊 账户状态",
                "fr": "📊 Statut du compte", "de": "📊 Kontostatus",
                "ja": "📊 アカウント状態", "ko": "📊 계정 상태",
            }
            # Community links (channel + chat) — shown right under the main menu.
            community_channel_labels = {
                "ru": "🏙️ Канал", "en": "🏙️ Channel", "es": "🏙️ Canal", "zh": "🏙️ 频道",
                "fr": "🏙️ Chaîne", "de": "🏙️ Kanal", "ja": "🏙️ チャンネル", "ko": "🏙️ 채널",
            }
            community_chat_labels = {
                "ru": "💬 Чат", "en": "💬 Chat", "es": "💬 Chat", "zh": "💬 聊天",
                "fr": "💬 Chat", "de": "💬 Chat", "ja": "💬 チャット", "ko": "💬 채팅",
            }
            keyboard = {
                "inline_keyboard": [
                    [
                        {"text": status_labels.get(lang, status_labels["en"]), "callback_data": "status"},
                    ],
                    [open_btn],
                    [
                        {"text": community_channel_labels.get(lang, community_channel_labels["en"]), "url": TELEGRAM_CHANNEL_URL},
                        {"text": community_chat_labels.get(lang, community_chat_labels["en"]), "url": TELEGRAM_CHAT_URL},
                    ],
                    [
                        {"text": _bt("btn_settings", lang), "callback_data": "settings"},
                        {"text": _bt("btn_help", lang), "callback_data": "help"}
                    ]
                ]
            }
        else:
            site_url = backend_url or "https://gramcity.games"
            # 8-language welcome for a brand-new (not-yet-linked) user.
            # Two simple onboarding steps + a single primary CTA button to the
            # site. Extra "Help"/"How to link" is kept as secondary buttons so
            # the first-open experience stays uncluttered.
            welcome_texts = {
                "ru": (
                    "🌆 <b>Добро пожаловать в Gram City!</b>\n\n"
                    f"Привет, <b>{first_name or 'друг'}</b>! Я — твой персональный помощник в игре.\n\n"
                    "Чтобы начать строить свою империю и получать уведомления "
                    "о прибыли, бизнесе и важных событиях, сделай два простых шага:\n\n"
                    "1️⃣ <b>Зарегистрируйся на сайте</b>\n"
                    "2️⃣ <b>Привяжи Telegram:</b> Личный кабинет → «Настройки» → «Telegram»\n\n"
                    "Как только ты это сделаешь, я буду присылать тебе отчёты о "
                    "доходах и важные игровые оповещения прямо сюда! 🚀"
                ),
                "en": (
                    "🌆 <b>Welcome to Gram City!</b>\n\n"
                    f"Hi, <b>{first_name or 'friend'}</b>! I'm your personal in-game assistant.\n\n"
                    "To start building your empire and receive notifications about "
                    "profit, business and important events, take two simple steps:\n\n"
                    "1️⃣ <b>Sign up on the website</b>\n"
                    "2️⃣ <b>Link Telegram:</b> Dashboard → Settings → Telegram\n\n"
                    "Once you do this, I'll send you income reports and important "
                    "game notifications right here! 🚀"
                ),
                "es": (
                    "🌆 <b>¡Bienvenido a Gram City!</b>\n\n"
                    f"Hola, <b>{first_name or 'amigo'}</b>. Soy tu asistente personal en el juego.\n\n"
                    "Para empezar a construir tu imperio y recibir notificaciones "
                    "sobre beneficios, negocios y eventos importantes, sigue dos "
                    "pasos simples:\n\n"
                    "1️⃣ <b>Regístrate en el sitio web</b>\n"
                    "2️⃣ <b>Vincula Telegram:</b> Panel → Ajustes → Telegram\n\n"
                    "En cuanto lo hagas, te enviaré informes de ingresos y "
                    "avisos importantes del juego aquí mismo. 🚀"
                ),
                "zh": (
                    "🌆 <b>欢迎来到 Gram City!</b>\n\n"
                    f"你好，<b>{first_name or '朋友'}</b>！我是你的游戏私人助理。\n\n"
                    "开始建立你的帝国并接收利润、企业和重要事件的通知，只需两个简单步骤：\n\n"
                    "1️⃣ <b>在网站上注册</b>\n"
                    "2️⃣ <b>绑定 Telegram：</b> 个人中心 → 设置 → Telegram\n\n"
                    "完成后，我就会把收入报告和重要游戏通知直接发到这里！🚀"
                ),
                "fr": (
                    "🌆 <b>Bienvenue sur Gram City !</b>\n\n"
                    f"Salut, <b>{first_name or 'ami'}</b> ! Je suis ton assistant personnel dans le jeu.\n\n"
                    "Pour commencer à bâtir ton empire et recevoir les notifications "
                    "sur les revenus, les entreprises et les événements importants, "
                    "suis deux étapes simples :\n\n"
                    "1️⃣ <b>Inscris-toi sur le site</b>\n"
                    "2️⃣ <b>Lie Telegram :</b> Tableau de bord → Paramètres → Telegram\n\n"
                    "Une fois cela fait, je t'enverrai les rapports de revenus et "
                    "les alertes de jeu importantes ici même ! 🚀"
                ),
                "de": (
                    "🌆 <b>Willkommen bei Gram City!</b>\n\n"
                    f"Hallo, <b>{first_name or 'Freund'}</b>! Ich bin dein persönlicher Assistent im Spiel.\n\n"
                    "Um dein Imperium aufzubauen und Benachrichtigungen über Gewinne, "
                    "Geschäfte und wichtige Ereignisse zu erhalten, mach zwei einfache Schritte:\n\n"
                    "1️⃣ <b>Registriere dich auf der Website</b>\n"
                    "2️⃣ <b>Verknüpfe Telegram:</b> Konto → Einstellungen → Telegram\n\n"
                    "Sobald das erledigt ist, schicke ich dir Einkommensberichte und "
                    "wichtige Spielbenachrichtigungen direkt hierher! 🚀"
                ),
                "ja": (
                    "🌆 <b>Gram City へようこそ！</b>\n\n"
                    f"こんにちは、<b>{first_name or 'フレンド'}</b>！私はゲーム内の専属アシスタントです。\n\n"
                    "帝国の建設を始め、収益・ビジネス・重要イベントの通知を受け取るには、"
                    "簡単な2ステップを行ってください：\n\n"
                    "1️⃣ <b>サイトで登録する</b>\n"
                    "2️⃣ <b>Telegram を連携：</b> マイページ → 設定 → Telegram\n\n"
                    "これが完了すると、収益レポートや重要な通知をここに直接お送りします！🚀"
                ),
                "ko": (
                    "🌆 <b>Gram City에 오신 것을 환영합니다!</b>\n\n"
                    f"안녕하세요, <b>{first_name or '친구'}</b>! 저는 게임 속 개인 도우미입니다.\n\n"
                    "제국 건설을 시작하고 수익·비즈니스·주요 이벤트 알림을 받으려면 "
                    "간단한 두 단계를 진행하세요:\n\n"
                    "1️⃣ <b>웹사이트에서 회원가입</b>\n"
                    "2️⃣ <b>Telegram 연결:</b> 내 계정 → 설정 → Telegram\n\n"
                    "완료되는 즉시 수익 리포트와 주요 게임 알림을 여기로 바로 보내드립니다! 🚀"
                ),
            }
            from bot_i18n import bt as _bt
            msg = welcome_texts.get(lang) or _bt("welcome_new", lang, name=first_name or _bt("friend", lang))

            # Localised button labels
            go_labels = {
                "ru": "🌐 Перейти на сайт", "en": "🌐 Go to the website",
                "es": "🌐 Ir al sitio",     "zh": "🌐 前往网站",
                "fr": "🌐 Aller sur le site", "de": "🌐 Zur Website",
                "ja": "🌐 サイトへ",          "ko": "🌐 웹사이트로 이동",
            }
            help_labels = {
                "ru": "🔗 Как привязать", "en": "🔗 How to link",
                "es": "🔗 Cómo vincular",  "zh": "🔗 如何绑定",
                "fr": "🔗 Comment lier",   "de": "🔗 Wie verknüpfen",
                "ja": "🔗 連携方法",       "ko": "🔗 연결 방법",
            }
            support_labels = {
                "ru": "🛟 Поддержка", "en": "🛟 Support",
                "es": "🛟 Soporte",   "zh": "🛟 客服",
                "fr": "🛟 Support",   "de": "🛟 Support",
                "ja": "🛟 サポート",  "ko": "🛟 지원",
            }

            # Support button: only render as Mini App button when we have a
            # valid https URL. Otherwise skip it — a broken web_app URL causes
            # Telegram to reject the *entire* sendMessage payload.
            # 1.2: Support lives only inside «Помощь». The first-open screen for
            # a not-yet-linked user keeps just the "how to link" secondary button.
            second_row = [
                {"text": help_labels.get(lang, help_labels["en"]), "callback_data": "how_to_link"},
            ]

            # Primary CTA: always a plain url button (safe in any environment).
            primary_url = site_url if _is_https_url(site_url) else "https://gramcity.games"
            keyboard = {
                "inline_keyboard": [
                    [
                        {"text": go_labels.get(lang, go_labels["en"]), "url": primary_url}
                    ],
                    second_row,
                ]
            }
        
        # Robust send via safe_send_menu: the linked-user menu uses Telegram
        # Mini App (web_app) buttons, which Telegram REJECTS when the Mini App
        # URL isn't registered in BotFather / is on another domain. safe_send_menu
        # degrades gracefully (full → url-only → plain-text) so a keyboard
        # message is ALWAYS delivered on /start and "🏠 На главную".
        _tick("pre-send (menu built)")
        await self.safe_send_menu(chat_id, msg, reply_markup=keyboard, context="cmd_start")
        _tick("safe_send_menu (network send)")
        return {"ok": True}

    async def process_link_token(self, chat_id: str, username: str, token: str) -> Dict:
        """Process account linking via deep link token"""
        # Get token data from the in-process memory cache OR the database.
        # In the standalone bot process `server` is NOT the running module, so
        # doing `from server import telegram_link_tokens` would synchronously
        # import the entire 13k-line server.py and FREEZE the bot's event loop.
        # Only read the cache if server is ALREADY imported (API process);
        # otherwise fall back to the DB, which is the source of truth.
        import sys as _sys
        _srv = _sys.modules.get("server")
        telegram_link_tokens = getattr(_srv, "telegram_link_tokens", {}) if _srv else {}

        # Load from MongoDB if not in memory (happens after every backend restart —
        # the previous in-memory-only cache was the root cause of "linking silently
        # doesn't work" reports).
        token_data = telegram_link_tokens.get(token)
        if not token_data:
            try:
                doc = await self.db.telegram_link_tokens.find_one({"_id": token})
                if doc:
                    token_data = {
                        "user_id": doc.get("user_id"),
                        "user_filter": doc.get("user_filter"),
                        "created_at": doc.get("created_at"),
                        "expires_at": doc.get("expires_at"),
                    }
                    telegram_link_tokens[token] = token_data
            except Exception as _e:
                logger.warning(f"telegram_link_tokens load from DB failed: {_e}")

        if not token_data:
            try:
                from routes.telegram_notifications import resolve_bot_language as _resolve_lang
                _lang = await _resolve_lang(self.db, str(chat_id))
            except Exception:
                _lang = "en"
            _inv = {
                "en": "❌ <b>Invalid token</b>\n\nGenerate a new link on the GRAM City site.",
                "ru": "❌ <b>Недействительный токен</b>\n\nСгенерируйте новую ссылку на сайте GRAM City.",
                "es": "❌ <b>Token no válido</b>\n\nGenere un nuevo enlace en el sitio de GRAM City.",
                "zh": "❌ <b>无效令牌</b>\n\n请在 GRAM City 网站上生成新链接。",
                "fr": "❌ <b>Jeton invalide</b>\n\nGénérez un nouveau lien sur le site GRAM City.",
                "de": "❌ <b>Ungültiger Token</b>\n\nErstelle einen neuen Link auf der GRAM City-Website.",
                "ja": "❌ <b>無効なトークン</b>\n\nGRAM City サイトで新しいリンクを生成してください。",
                "ko": "❌ <b>유효하지 않은 토큰</b>\n\nGRAM City 사이트에서 새 링크를 생성하세요.",
                "id": "❌ <b>Token tidak valid</b>\n\nBuat tautan baru di situs GRAM City.",
            }
            await self.send_message(chat_id, _inv.get(_lang, _inv["en"]))
            return {"ok": True}

        # Check expiry
        expires_at = token_data.get("expires_at")
        if expires_at and isinstance(expires_at, datetime) and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if not expires_at or datetime.now(timezone.utc) > expires_at:
            telegram_link_tokens.pop(token, None)
            try:
                await self.db.telegram_link_tokens.delete_one({"_id": token})
            except Exception:
                pass
            try:
                from routes.telegram_notifications import resolve_bot_language as _resolve_lang
                _lang = await _resolve_lang(self.db, str(chat_id))
            except Exception:
                _lang = "en"
            _exp = {
                "en": "❌ <b>Token expired</b>\n\nGenerate a new link on the GRAM City site.",
                "ru": "❌ <b>Токен истёк</b>\n\nСгенерируйте новую ссылку на сайте GRAM City.",
                "es": "❌ <b>Token caducado</b>\n\nGenere un nuevo enlace en el sitio de GRAM City.",
                "zh": "❌ <b>令牌已过期</b>\n\n请在 GRAM City 网站上生成新链接。",
                "fr": "❌ <b>Jeton expiré</b>\n\nGénérez un nouveau lien sur le site GRAM City.",
                "de": "❌ <b>Token abgelaufen</b>\n\nErstelle einen neuen Link auf der GRAM City-Website.",
                "ja": "❌ <b>トークンの有効期限が切れました</b>\n\nGRAM City サイトで新しいリンクを生成してください。",
                "ko": "❌ <b>토큰 만료됨</b>\n\nGRAM City 사이트에서 새 링크를 생성하세요.",
                "id": "❌ <b>Token kedaluwarsa</b>\n\nBuat tautan baru di situs GRAM City.",
            }
            await self.send_message(chat_id, _exp.get(_lang, _exp["en"]))
            return {"ok": True}
        
        # Refuse if this Telegram identity is already linked to a DIFFERENT
        # site account. Without this guard a second user could just generate a
        # link token, tap it in Telegram, and silently steal an already-linked
        # Telegram identity — see product ticket "Fix 2".
        try:
            from routes.telegram_auth import _find_user_by_telegram as _find_by_tg
        except Exception:
            _find_by_tg = None
        if _find_by_tg is not None:
            try:
                already = await _find_by_tg(self.db, str(chat_id), username)
                if already and already.get("id") != token_data.get("user_id"):
                    telegram_link_tokens.pop(token, None)
                    try:
                        await self.db.telegram_link_tokens.delete_one({"_id": token})
                    except Exception:
                        pass
                    try:
                        from routes.telegram_notifications import tmsg as _tmsg, resolve_bot_language as _resolve_lang
                        _lang = await _resolve_lang(self.db, str(chat_id))
                    except Exception:
                        _tmsg, _lang = None, "en"
                    msg_taken = {
                        "en": "❌ <b>This Telegram is already linked</b>\n\nThis Telegram account is already connected to another GRAM City profile.",
                        "ru": "❌ <b>Этот Telegram уже привязан</b>\n\nЭтот Telegram-аккаунт уже подключён к другому профилю GRAM City.",
                        "es": "❌ <b>Este Telegram ya está vinculado</b>\n\nEste Telegram ya está conectado a otro perfil de GRAM City.",
                        "zh": "❌ <b>此 Telegram 已被绑定</b>\n\n该 Telegram 已连接到其它 GRAM City 账号。",
                        "fr": "❌ <b>Ce Telegram est déjà lié</b>\n\nCe Telegram est déjà connecté à un autre profil GRAM City.",
                        "de": "❌ <b>Dieses Telegram ist bereits verknüpft</b>\n\nDieses Telegram-Konto ist bereits mit einem anderen GRAM City-Profil verbunden.",
                        "ja": "❌ <b>この Telegram はすでにリンク済みです</b>\n\nこの Telegram は他の GRAM City アカウントに接続されています。",
                        "ko": "❌ <b>이 Telegram은 이미 연결되어 있습니다</b>\n\n이 Telegram은 다른 GRAM City 프로필에 연결되어 있습니다。",
                        "id": "❌ <b>Telegram ini sudah terhubung</b>\n\nAkun Telegram ini sudah terhubung dengan profil GRAM City lain.",
                    }.get(_lang, None)
                    if not msg_taken:
                        msg_taken = "❌ <b>This Telegram is already linked</b>\n\nThis Telegram account is already connected to another GRAM City profile."
                    await self.send_message(chat_id, msg_taken)
                    return {"ok": True}
            except Exception as _e:
                logger.warning(f"process_link_token dup-check failed: {_e}")

        # Link account (store tg id in every canonical field so future lookups
        # work regardless of int/str shape and any legacy migrations).
        try:
            _chat_int = int(str(chat_id))
        except (TypeError, ValueError):
            _chat_int = None
        update_data = {
            "telegram_id": _chat_int if _chat_int is not None else str(chat_id),
            "telegram_user_id": str(chat_id),
            "telegram_chat_id": str(chat_id),
            "telegram_verified": True,
            "telegram_notifications": True,
        }
        if username:
            update_data["telegram_username"] = username.lower()

        await self.db.users.update_one(
            {"id": token_data["user_id"]},
            {"$set": update_data}
        )

        # Remove used token (both stores)
        telegram_link_tokens.pop(token, None)
        try:
            await self.db.telegram_link_tokens.delete_one({"_id": token})
        except Exception:
            pass
        
        # Get user info
        user = await self.db.users.find_one({"id": token_data["user_id"]}, {"_id": 0})

        # При привязке язык приложения становится языком бота (выбор пользователя в приложении).
        try:
            from core.notif_i18n import LANGS as _LANGS
            _app_lang = ((user or {}).get("language") or "").lower()
            if _app_lang in _LANGS:
                await self.db.telegram_mappings.update_one(
                    {"chat_id": str(chat_id)}, {"$set": {"language": _app_lang}}, upsert=True
                )
        except Exception:
            pass

        # Localised success screen — «Аккаунт привязан» in the user's chosen
        # bot language (falls back to English for users who never picked one).
        try:
            from routes.telegram_notifications import resolve_bot_language as _resolve_lang
            lang = await _resolve_lang(self.db, str(chat_id))
        except Exception:
            lang = (await self._help_lang(chat_id)) or "en"

        _linked_titles = {
            "en": "✅ <b>Account linked!</b>",
            "ru": "✅ <b>Аккаунт привязан!</b>",
            "es": "✅ <b>¡Cuenta vinculada!</b>",
            "zh": "✅ <b>账号已绑定！</b>",
            "fr": "✅ <b>Compte lié !</b>",
            "de": "✅ <b>Konto verknüpft!</b>",
            "ja": "✅ <b>アカウントをリンクしました！</b>",
            "ko": "✅ <b>계정이 연결되었습니다!</b>",
            "id": "✅ <b>Akun terhubung!</b>",
        }
        _linked_body = {
            "en": "You will now receive notifications about:\n📢 Your businesses\n💰 Deposits & withdrawals\n🔔 Important in-game events",
            "ru": "Теперь вы будете получать уведомления о:\n📢 Состоянии ваших бизнесов\n💰 Пополнениях и выводах\n🔔 Важных событиях игры",
            "es": "Ahora recibirás notificaciones sobre:\n📢 Tus negocios\n💰 Depósitos y retiros\n🔔 Eventos importantes del juego",
            "zh": "您将收到以下通知：\n📢 您的企业\n💰 充值与提现\n🔔 游戏内重要事件",
            "fr": "Vous recevrez désormais des notifications concernant :\n📢 Vos entreprises\n💰 Dépôts et retraits\n🔔 Événements importants du jeu",
            "de": "Du erhältst nun Benachrichtigungen zu:\n📢 Deinen Unternehmen\n💰 Ein-/Auszahlungen\n🔔 Wichtigen Spielereignissen",
            "ja": "以下の通知を受け取れます:\n📢 あなたのビジネス\n💰 入出金\n🔔 重要なゲームイベント",
            "ko": "다음에 대한 알림을 받게 됩니다:\n📢 사업 현황\n💰 입출금\n🔔 주요 게임 이벤트",
            "id": "Anda akan menerima notifikasi tentang:\n📢 Bisnis Anda\n💰 Deposit & penarikan\n🔔 Peristiwa penting dalam game",
        }
        _account_labels = {
            "en": "Your account", "ru": "Ваш аккаунт", "es": "Tu cuenta", "zh": "您的账号",
            "fr": "Votre compte", "de": "Dein Konto", "ja": "あなたのアカウント",
            "ko": "내 계정", "id": "Akun Anda",
        }
        _balance_labels = {
            "en": "Balance", "ru": "Баланс", "es": "Saldo", "zh": "余额",
            "fr": "Solde", "de": "Guthaben", "ja": "残高", "ko": "잔액", "id": "Saldo",
        }
        msg = (
            f"{_linked_titles.get(lang, _linked_titles['en'])}\n\n"
            f"{_linked_body.get(lang, _linked_body['en'])}\n\n"
            f"<b>{_account_labels.get(lang, _account_labels['en'])}:</b>\n"
            f"👤 {user.get('username', 'Unknown')}\n"
            f"💰 {_balance_labels.get(lang, _balance_labels['en'])}: {user.get('balance_ton', 0):.2f} TON"
        )

        # Bottom «Main menu» button that opens the linked-user welcome
        # screen (callback → cmd_start). Localised to the user's bot language.
        home_labels = {
            "ru": "🏠 На главную", "en": "🏠 Main menu",
            "es": "🏠 Menú principal", "zh": "🏠 主菜单",
            "fr": "🏠 Menu principal", "de": "🏠 Hauptmenü",
            "ja": "🏠 メインメニュー", "ko": "🏠 메인 메뉴",
            "id": "🏠 Menu utama",
        }
        keyboard = {"inline_keyboard": [[
            {"text": home_labels.get(lang, home_labels["en"]), "callback_data": "back_to_menu"}
        ]]}
        await self.send_message(chat_id, msg, reply_markup=keyboard)
        return {"ok": True}
    
    @staticmethod
    def _owner_ids(user: Dict) -> list:
        """All identifiers that may appear in business `owner`/`owner_wallet`
        for THIS user. None/empty values are dropped so we never accidentally
        match unowned businesses (owner_wallet=None) on the map."""
        ids = {
            user.get("id"),
            user.get("wallet_address"),
            user.get("email"),
            user.get("username"),
        }
        ids.discard(None)
        ids.discard("")
        return list(ids)

    def _owner_query(self, user: Dict) -> Dict:
        ids = self._owner_ids(user)
        if not ids:
            # No valid identifier → match nothing (definitely not "all").
            return {"owner": "__none__"}
        return {"$or": [{"owner": {"$in": ids}}, {"owner_wallet": {"$in": ids}}]}

    # ── Localised strings for the Account Status / Businesses screens ──
    STATUS_L = {
        "title": {
            "ru": "📊 Статус аккаунта", "en": "📊 Account status",
            "es": "📊 Estado de cuenta", "zh": "📊 账户状态",
            "fr": "📊 Statut du compte", "de": "📊 Kontostatus",
            "ja": "📊 アカウント状態", "ko": "📊 계정 상태",
        },
        "name":     {"ru": "👤 Имя", "en": "👤 Name", "es": "👤 Nombre", "zh": "👤 名称",
                     "fr": "👤 Nom", "de": "👤 Name", "ja": "👤 名前", "ko": "👤 이름"},
        "wallet":   {"ru": "💳 Кошелёк", "en": "💳 Wallet", "es": "💳 Cartera", "zh": "💳 钱包",
                     "fr": "💳 Portefeuille", "de": "💳 Wallet", "ja": "💳 ウォレット", "ko": "💳 지갑"},
        "unlinked": {"ru": "Не привязан", "en": "Not linked", "es": "No vinculada", "zh": "未绑定",
                     "fr": "Non liée", "de": "Nicht verknüpft", "ja": "未連携", "ko": "연결되지 않음"},
        "finances": {"ru": "💰 Финансы", "en": "💰 Finances", "es": "💰 Finanzas", "zh": "💰 财务",
                     "fr": "💰 Finances", "de": "💰 Finanzen", "ja": "💰 資産", "ko": "💰 재정"},
        "balance_ton": {"ru": "Баланс TON", "en": "TON balance", "es": "Saldo TON", "zh": "TON 余额",
                        "fr": "Solde TON", "de": "TON-Guthaben", "ja": "TON残高", "ko": "TON 잔액"},
        "coins":    {"ru": "Монеты $CITY", "en": "$CITY coins", "es": "Monedas $CITY", "zh": "$CITY 币",
                     "fr": "Pièces $CITY", "de": "$CITY-Münzen", "ja": "$CITYコイン", "ko": "$CITY 코인"},
        "businesses_count": {"ru": "🏢 Бизнесов", "en": "🏢 Businesses",
                     "es": "🏢 Negocios", "zh": "🏢 企业",
                     "fr": "🏢 Entreprises", "de": "🏢 Unternehmen",
                     "ja": "🏢 ビジネス", "ko": "🏢 사업"},
        "not_linked_hint": {
            "ru": "❌ <b>Аккаунт не привязан</b>\n\nПривяжите Telegram к аккаунту GRAM City через настройки на сайте.",
            "en": "❌ <b>Account not linked</b>\n\nLink your Telegram to GRAM City in the site settings.",
            "es": "❌ <b>Cuenta no vinculada</b>\n\nVincula tu Telegram con GRAM City en los ajustes del sitio.",
            "zh": "❌ <b>账号未绑定</b>\n\n请在网站设置中将 Telegram 与 GRAM City 账号绑定。",
            "fr": "❌ <b>Compte non lié</b>\n\nLiez votre Telegram à GRAM City dans les paramètres du site.",
            "de": "❌ <b>Konto nicht verknüpft</b>\n\nVerknüpfe dein Telegram in den Website-Einstellungen mit GRAM City.",
            "ja": "❌ <b>アカウント未連携</b>\n\nサイトの設定から Telegram を GRAM City に連携してください。",
            "ko": "❌ <b>계정이 연결되지 않았습니다</b>\n\n사이트 설정에서 Telegram을 GRAM City에 연결하세요.",
        },
        "btn_businesses": {"ru": "🏢 Бизнесы", "en": "🏢 Businesses",
                     "es": "🏢 Negocios", "zh": "🏢 企业",
                     "fr": "🏢 Entreprises", "de": "🏢 Unternehmen",
                     "ja": "🏢 ビジネス", "ko": "🏢 사업"},
        "btn_play": {"ru": "🎮 Играть", "en": "🎮 Play",
                     "es": "🎮 Jugar", "zh": "🎮 开始",
                     "fr": "🎮 Jouer", "de": "🎮 Spielen",
                     "ja": "🎮 プレイ", "ko": "🎮 플레이"},
        "btn_play_site": {"ru": "🌐 Открыть на сайте", "en": "🌐 Open on site",
                     "es": "🌐 Abrir en el sitio", "zh": "🌐 在网站打开",
                     "fr": "🌐 Ouvrir sur le site", "de": "🌐 Auf der Seite öffnen",
                     "ja": "🌐 サイトで開く", "ko": "🌐 사이트에서 열기"},
        "btn_back": {"ru": "◀️ Назад", "en": "◀️ Back",
                     "es": "◀️ Atrás", "zh": "◀️ 返回",
                     "fr": "◀️ Retour", "de": "◀️ Zurück",
                     "ja": "◀️ 戻る", "ko": "◀️ 뒤로"},
        "businesses_title": {"ru": "🏢 <b>Ваши бизнесы</b>", "en": "🏢 <b>Your businesses</b>",
                     "es": "🏢 <b>Tus negocios</b>", "zh": "🏢 <b>你的企业</b>",
                     "fr": "🏢 <b>Vos entreprises</b>", "de": "🏢 <b>Deine Unternehmen</b>",
                     "ja": "🏢 <b>あなたのビジネス</b>", "ko": "🏢 <b>내 사업</b>"},
        "businesses_empty": {"ru": "🏢 У вас пока нет бизнесов.", "en": "🏢 You have no businesses yet.",
                     "es": "🏢 Aún no tienes negocios.", "zh": "🏢 你还没有任何企业。",
                     "fr": "🏢 Vous n'avez pas encore d'entreprises.",
                     "de": "🏢 Du hast noch keine Unternehmen.",
                     "ja": "🏢 まだビジネスがありません。",
                     "ko": "🏢 아직 사업이 없습니다。"},
        "biz_level":  {"ru": "Уровень", "en": "Level", "es": "Nivel", "zh": "等级",
                       "fr": "Niveau", "de": "Level", "ja": "レベル", "ko": "레벨"},
        "biz_dura":   {"ru": "Прочность", "en": "Durability", "es": "Durabilidad", "zh": "耐久度",
                       "fr": "Durabilité", "de": "Haltbarkeit", "ja": "耐久度", "ko": "내구도"},
        # v2.3.x: referral stats block for the Account Status screen and
        # Main-menu referral-link snippet (localized in all 8 languages).
        "referrals_count": {
            "ru": "👥 Рефералов",       "en": "👥 Referrals",
            "es": "👥 Referidos",        "zh": "👥 邀请人数",
            "fr": "👥 Filleuls",         "de": "👥 Empfehlungen",
            "ja": "👥 紹介者",           "ko": "👥 추천인",
        },
        "referrals_earned": {
            "ru": "💎 Заработано с рефералов",
            "en": "💎 Earned from referrals",
            "es": "💎 Ganado por referidos",
            "zh": "💎 邀请收益",
            "fr": "💎 Gains parrainage",
            "de": "💎 Empfehlungsverdienst",
            "ja": "💎 紹介収益",
            "ko": "💎 추천 수익",
        },
        "referral_link_title": {
            "ru": "🔗 <b>Твоя реферальная ссылка</b>",
            "en": "🔗 <b>Your referral link</b>",
            "es": "🔗 <b>Tu enlace de referido</b>",
            "zh": "🔗 <b>你的推荐链接</b>",
            "fr": "🔗 <b>Ton lien de parrainage</b>",
            "de": "🔗 <b>Dein Empfehlungslink</b>",
            "ja": "🔗 <b>あなたの紹介リンク</b>",
            "ko": "🔗 <b>나의 추천 링크</b>",
        },
        "referral_link_hint": {
            "ru": "Приглашай друзей и получай <b>5%</b> с их дохода!",
            "en": "Invite friends and earn <b>5%</b> of their income!",
            "es": "¡Invita amigos y gana el <b>5%</b> de sus ingresos!",
            "zh": "邀请朋友，获得他们收入的 <b>5%</b>！",
            "fr": "Invite tes amis et gagne <b>5 %</b> de leurs revenus !",
            "de": "Lade Freunde ein und erhalte <b>5 %</b> ihres Einkommens!",
            "ja": "友達を招待して、彼らの収入の <b>5%</b> をゲット！",
            "ko": "친구를 초대하고 그들 수입의 <b>5%</b>를 받으세요!",
        },
    }

    def _stl(self, key: str, lang: str) -> str:
        d = self.STATUS_L.get(key, {})
        return d.get(lang) or d.get("en") or ""

    async def _referral_stats(self, user: Dict) -> Dict:
        """v2.3.x: return {count, earned_ton, earned_city, link} for the
        Account Status / main menu referral blocks. Referrals are users whose
        `referrerId` == this user's id. Earnings are the sum of their
        `contributedToReferrer` field (canonical source, same as the /referrals/me
        API and admin panel — see server.py:_build_referral_list)."""
        try:
            user_id = user.get("id")
            if not user_id:
                return {"count": 0, "earned_ton": 0.0, "earned_city": 0.0, "link": ""}
            count = await self.db.users.count_documents({"referrerId": user_id})
            pipeline = [
                {"$match": {"referrerId": user_id}},
                {"$group": {"_id": None, "s": {"$sum": {"$ifNull": ["$contributedToReferrer", 0]}}}},
            ]
            earned_ton = 0.0
            async for doc in self.db.users.aggregate(pipeline):
                earned_ton = float(doc.get("s") or 0.0)
                break
            base = await self._resolve_app_url()
            base = base if (base and base.startswith("https://")) else "https://gramcity.games"
            link = f"{base.rstrip('/')}/?ref={user_id}"
            return {
                "count": int(count),
                "earned_ton": earned_ton,
                "earned_city": earned_ton * 1000.0,
                "link": link,
            }
        except Exception as e:
            logger.debug(f"_referral_stats failed: {e}")
            return {"count": 0, "earned_ton": 0.0, "earned_city": 0.0, "link": ""}

    async def cmd_promo_myrank(self, chat_id: str, user_id_tg: str) -> Dict:
        """Handle 'Мой ранг' callback — show user's current rank in the active
        referral rally campaign."""
        lang = await self._help_lang(chat_id)
        user = await self.find_user_by_telegram(chat_id, "")

        if not user:
            # Not linked — show hint
            msg = {
                "ru": "❗ Ваш Telegram не привязан к аккаунту GRAM CITY.\n\nЗайдите на сайт и привяжите Telegram — тогда сможете отслеживать свой ранг.",
                "en": "❗ Your Telegram is not linked to a GRAM CITY account.\n\nGo to the site and link your Telegram to track your rank.",
            }.get(lang, "❗ Your Telegram is not linked to a GRAM CITY account.")
            await self.send_message(chat_id, msg)
            return {"ok": True}

        # Fetch stats via the promo_service
        try:
            import promo_service as ps
            campaign = await ps.get_active_campaign(self.db)
            if not campaign:
                msg = {
                    "ru": "ℹ️ Сейчас нет активной акции. Заходите позже!",
                    "en": "ℹ️ There is no active campaign right now. Come back later!",
                }.get(lang, "ℹ️ There is no active campaign right now.")
                await self.send_message(chat_id, msg)
                return {"ok": True}

            stats = await ps.compute_user_referral_stats(self.db, user["id"], sort="active")
            rank = stats.get("rank")
            active = stats.get("active", 0)
            total = stats.get("total", 0)

            if lang == "ru":
                text = (
                    f"📊 <b>Твой ранг в акции «Мега-ралли рефералов»</b>\n\n"
                    f"🏆 Место: <b>#{rank}</b>\n"
                    f"👥 Активных рефералов: <b>{active}</b>\n"
                    f"👤 Всего рефералов: <b>{total}</b>\n\n"
                    f"Продолжай приглашать друзей и попади в ТОП-3!"
                )
            else:
                text = (
                    f"📊 <b>Your rank in the Referral Mega-Rally</b>\n\n"
                    f"🏆 Rank: <b>#{rank}</b>\n"
                    f"👥 Active referrals: <b>{active}</b>\n"
                    f"👤 Total referrals: <b>{total}</b>\n\n"
                    f"Keep inviting friends to reach the TOP-3!"
                )
            await self.send_message(chat_id, text)
        except Exception as e:
            logger.error(f"cmd_promo_myrank failed: {e}")
            await self.send_message(chat_id, "⚠️ Не удалось получить статистику. Попробуйте позже.")
        return {"ok": True}

    async def cmd_status(self, chat_id: str, username: str, user_id_tg: str) -> Dict:
        """Handle /status command — «Статус аккаунта»."""
        lang = await self._help_lang(chat_id)
        user = await self.find_user_by_telegram(chat_id, username)

        if not user:
            await self.send_message(chat_id, self._stl("not_linked_hint", lang))
            return {"ok": True}

        # Count businesses (owner-scoped)
        businesses_count = await self.db.businesses.count_documents(self._owner_query(user))

        # v2.3.x: referral stats displayed ABOVE business count
        ref_stats = await self._referral_stats(user)

        # Wallet in friendly format
        wallet_addr = user.get("wallet_address", "")
        friendly_wallet = self._to_friendly_address(wallet_addr) if wallet_addr else self._stl("unlinked", lang)

        # Finances: TON balance + coins ($CITY = TON * 1000)
        balance_ton = float(user.get("balance_ton", 0) or 0)
        balance_city = balance_ton * 1000

        name = user.get("display_name") or user.get("username") or "Unknown"

        msg = (
            f"{self._stl('title', lang)}\n\n"
            f"{self._stl('name', lang)}: <b>{name}</b>\n"
            f"{self._stl('wallet', lang)}: <code>{friendly_wallet}</code>\n\n"
            f"<b>{self._stl('finances', lang)}:</b>\n"
            f"• {self._stl('balance_ton', lang)}: <b>{balance_ton:.4f} TON</b>\n"
            f"• {self._stl('coins', lang)}: <b>{balance_city:,.0f} $CITY</b>\n\n"
            f"{self._stl('referrals_count', lang)}: <b>{ref_stats['count']}</b>\n"
            f"{self._stl('referrals_earned', lang)}: <b>{ref_stats['earned_city']:,.2f} $CITY</b>\n\n"
            f"{self._stl('businesses_count', lang)}: <b>{businesses_count}</b>"
        )

        # Buttons: Businesses / Play (plain URL link) / Back.
        base = await self._resolve_app_url()
        play_url = base if (base and base.startswith("https://")) else "https://gramcity.games"
        play_lbl = self._stl("btn_play", lang)
        play_btn = {"text": play_lbl, "url": play_url}

        keyboard = {"inline_keyboard": [
            [{"text": self._stl("btn_businesses", lang), "callback_data": "status_businesses"}],
            [play_btn],
            [{"text": self._stl("btn_back", lang), "callback_data": "back_to_menu"}],
        ]}
        await self.safe_send_menu(chat_id, msg, reply_markup=keyboard, context="cmd_status")
        return {"ok": True}
    
    async def cmd_businesses(self, chat_id: str, username: str, user_id_tg: str) -> Dict:
        """Handle /businesses command — list of user businesses with buttons
        «Играть» (opens the game) and «Назад» (back to Account Status)."""
        lang = await self._help_lang(chat_id)
        user = await self.find_user_by_telegram(chat_id, username)

        if not user:
            await self.send_message(chat_id, self._stl("not_linked_hint", lang))
            return {"ok": True}

        # Get user businesses
        businesses = await self.db.businesses.find(
            self._owner_query(user), {"_id": 0}
        ).to_list(20)

        base = await self._resolve_app_url()
        play_url = base if (base and base.startswith("https://")) else "https://gramcity.games"
        play_lbl = self._stl("btn_play", lang)
        play_btn = {"text": play_lbl, "url": play_url}
        # From «Бизнесы» the «Назад» button returns to Account Status.
        keyboard = {"inline_keyboard": [
            [play_btn],
            [{"text": self._stl("btn_back", lang), "callback_data": "status"}],
        ]}

        if not businesses:
            await self.safe_send_menu(
                chat_id, self._stl("businesses_empty", lang), reply_markup=keyboard,
                context="cmd_businesses",
            )
            return {"ok": True}

        lvl_lbl = self._stl("biz_level", lang)
        dur_lbl = self._stl("biz_dura", lang)
        lines = [self._stl("businesses_title", lang), ""]
        # Localise business names using BUSINESS_TYPES map from server.py.
        # `name` is a dict like {"en": "Farm", "ru": "Ферма", "zh": "农场"}.
        # For languages we don't have a translation for (es/fr/de/ja/ko),
        # gracefully fall back to en → ru → business_type.
        try:
            from core.constants import BUSINESS_TYPES  # type: ignore
        except Exception:
            BUSINESS_TYPES = {}
        for biz in businesses:
            durability = float(biz.get("durability", 100) or 0)
            status_emoji = "🟢" if durability >= 70 else ("🟡" if durability >= 30 else "🔴")
            btype = biz.get("business_type") or ""
            cfg = BUSINESS_TYPES.get(btype) or {}
            name_map = cfg.get("name") or {}
            if isinstance(name_map, dict):
                name = (
                    name_map.get(lang)
                    or name_map.get("en")
                    or name_map.get("ru")
                    or btype
                    or "?"
                )
            else:
                name = str(name_map) or btype or "?"
            lvl = biz.get("level", 1)
            lines.append(f"{status_emoji} <b>{name}</b>")
            lines.append(f"   📊 {lvl_lbl}: {lvl}")
            lines.append(f"   🔧 {dur_lbl}: {durability:.0f}%")
            lines.append("")
        msg = "\n".join(lines)

        await self.safe_send_menu(chat_id, msg, reply_markup=keyboard, context="cmd_businesses")
        return {"ok": True}
    
    # ─── Help system: FAQ with inline section buttons + Support + Back ────
    # Each section explains one page of the project. Selecting a section
    # opens its dedicated message; "Назад" deletes that message and returns
    # to the FAQ list.
    
    HELP_SUPPORT_URL = "https://telegram.me/willywonkys"
    
    HELP_SECTIONS = [
        # (section_id, emoji, ru_label, en_label)
        # `city` (Город) removed per user request — the section overview is
        # implicit in the main-menu welcome message.
        ("plots",      "🗺️", "Участки и аукцион",       "Plots & auction"),
        ("businesses", "🏢", "Мои бизнесы",             "My businesses"),
        ("market",     "💱", "Рынок и цены",            "Market & prices"),
        ("alliances",  "🤝", "Альянсы и патроны",       "Alliances & patrons"),
        ("buffs",      "✨", "Баффы T3",                "Tier-3 buffs"),
        ("wallet",     "💼", "Кошелёк и вывод",         "Wallet & withdrawals"),
        ("settings",   "⚙️", "Настройки и Telegram",    "Settings & Telegram"),
        ("admin",      "🔑", "Админ-панель",            "Admin panel"),
    ]

    # Localised strings for the in-bot Support flow (all project languages).
    SUPPORT_L = {
        "write":   {"ru": "✍️ Написать", "en": "✍️ Write", "es": "✍️ Escribir", "zh": "✍️ 写消息",
                     "fr": "✍️ Écrire", "de": "✍️ Schreiben", "ja": "✍️ 書く", "ko": "✍️ 작성하기"},
        "back":    {"ru": "◀️ Назад", "en": "◀️ Back", "es": "◀️ Atrás", "zh": "◀️ 返回",
                     "fr": "◀️ Retour", "de": "◀️ Zurück", "ja": "◀️ 戻る", "ko": "◀️ 뒤로"},
        "cancel":  {"ru": "◀️ Отмена", "en": "◀️ Cancel", "es": "◀️ Cancelar", "zh": "◀️ 取消",
                     "fr": "◀️ Annuler", "de": "◀️ Abbrechen", "ja": "◀️ キャンセル", "ko": "◀️ 취소"},
        "menu": {
            "ru": "🛟 <b>Поддержка</b>\n\nНажмите «Написать», чтобы отправить сообщение в поддержку — оно попадёт агентам так же, как сообщения с сайта.",
            "en": "🛟 <b>Support</b>\n\nTap «Write» to send a message to support — it reaches agents just like messages from the website.",
            "es": "🛟 <b>Soporte</b>\n\nPulsa «Escribir» para enviar un mensaje a soporte — llegará a los agentes igual que desde el sitio web.",
            "zh": "🛟 <b>客服</b>\n\n点击「写消息」向客服发送消息 — 它会像网站上的消息一样送达客服。",
            "fr": "🛟 <b>Support</b>\n\nAppuyez sur « Écrire » pour envoyer un message au support — il parvient aux agents comme depuis le site.",
            "de": "🛟 <b>Support</b>\n\nTippe auf «Schreiben», um eine Nachricht an den Support zu senden — sie erreicht die Agenten wie über die Website.",
            "ja": "🛟 <b>サポート</b>\n\n「書く」を押してサポートにメッセージを送信してください — サイトからのメッセージと同じように担当者に届きます。",
            "ko": "🛟 <b>지원</b>\n\n「작성하기」를 눌러 지원팀에 메시지를 보내세요 — 웹사이트에서 보낸 메시지처럼 상담원에게 전달됩니다.",
        },
        "prompt": {
            "ru": "✍️ Напишите ваше сообщение одним сообщением — мы передадим его в поддержку.",
            "en": "✍️ Write your message in a single message — we'll forward it to support.",
            "es": "✍️ Escribe tu mensaje en un solo mensaje — lo enviaremos a soporte.",
            "zh": "✍️ 请用一条消息写下您的问题 — 我们会转发给客服。",
            "fr": "✍️ Écrivez votre message en une seule fois — nous le transmettrons au support.",
            "de": "✍️ Schreibe deine Nachricht in einer einzigen Nachricht — wir leiten sie an den Support weiter.",
            "ja": "✍️ メッセージを1通で書いてください — サポートに転送します。",
            "ko": "✍️ 한 개의 메시지로 문의 내용을 작성해 주세요 — 지원팀에 전달됩니다.",
        },
        "sent": {
            "ru": "✅ Ваше сообщение отправлено в поддержку. Ответ придёт сюда и в раздел поддержки на сайте.",
            "en": "✅ Your message was sent to support. The reply will arrive here and in the support section on the website.",
            "es": "✅ Tu mensaje se envió a soporte. La respuesta llegará aquí y en la sección de soporte del sitio.",
            "zh": "✅ 您的消息已发送给客服。回复将出现在这里以及网站的客服区域。",
            "fr": "✅ Votre message a été envoyé au support. La réponse arrivera ici et dans la section support du site.",
            "de": "✅ Deine Nachricht wurde an den Support gesendet. Die Antwort kommt hierher und in den Support-Bereich der Website.",
            "ja": "✅ メッセージをサポートに送信しました。返信はこことサイトのサポート欄に届きます。",
            "ko": "✅ 메시지가 지원팀에 전송되었습니다. 답변은 여기와 웹사이트 지원 섹션으로 전달됩니다.",
        },
        "not_linked": {
            "ru": "⚠️ Сначала привяжите аккаунт GRAM City: Личный кабинет → «Настройки» → «Telegram». После этого сообщения из бота попадут в поддержку.",
            "en": "⚠️ First link your GRAM City account: Dashboard → Settings → Telegram. After that, bot messages will reach support.",
            "es": "⚠️ Primero vincula tu cuenta de GRAM City: Panel → Ajustes → Telegram. Después, los mensajes del bot llegarán a soporte.",
            "zh": "⚠️ 请先绑定您的 GRAM City 账号：个人中心 → 设置 → Telegram。之后机器人消息才能送达客服。",
            "fr": "⚠️ Liez d'abord votre compte GRAM City : Tableau de bord → Paramètres → Telegram. Ensuite, les messages du bot parviendront au support.",
            "de": "⚠️ Verknüpfe zuerst dein GRAM City-Konto: Konto → Einstellungen → Telegram. Danach erreichen Bot-Nachrichten den Support.",
            "ja": "⚠️ まず GRAM City アカウントを連携してください：マイページ → 設定 → Telegram。その後、ボットのメッセージがサポートに届きます。",
            "ko": "⚠️ 먼저 GRAM City 계정을 연결하세요: 내 계정 → 설정 → Telegram. 그 후 봇 메시지가 지원팀에 전달됩니다.",
        },
        "cancelled": {
            "ru": "Отменено.", "en": "Cancelled.", "es": "Cancelado.", "zh": "已取消。",
            "fr": "Annulé.", "de": "Abgebrochen.", "ja": "キャンセルしました。", "ko": "취소되었습니다.",
        },
        # ── Full in-bot support session (1.2) ──────────────────────────────
        "start":  {"ru": "💬 Начать чат", "en": "💬 Start chat", "es": "💬 Iniciar chat", "zh": "💬 开始聊天",
                    "fr": "💬 Démarrer le chat", "de": "💬 Chat starten", "ja": "💬 チャット開始", "ko": "💬 채팅 시작"},
        "continue": {"ru": "💬 Продолжить чат", "en": "💬 Continue chat", "es": "💬 Continuar chat", "zh": "💬 继续聊天",
                    "fr": "💬 Continuer le chat", "de": "💬 Chat fortsetzen", "ja": "💬 チャットを続ける", "ko": "💬 채팅 계속"},
        "close":  {"ru": "🔚 Завершить чат", "en": "🔚 End chat", "es": "🔚 Finalizar chat", "zh": "🔚 结束聊天",
                    "fr": "🔚 Terminer le chat", "de": "🔚 Chat beenden", "ja": "🔚 チャット終了", "ko": "🔚 채팅 종료"},
        "open_window": {"ru": "🛟 Открыть окно поддержки", "en": "🛟 Open support window", "es": "🛟 Abrir ventana de soporte",
                    "zh": "🛟 打开客服窗口", "fr": "🛟 Ouvrir le support", "de": "🛟 Support-Fenster öffnen",
                    "ja": "🛟 サポート画面を開く", "ko": "🛟 지원 창 열기"},
        "status_active": {
            "ru": "🟢 <b>Активный чат.</b> Просто пишите сообщения — они уйдут в поддержку. Ответ придёт сюда.",
            "en": "🟢 <b>Active chat.</b> Just type your messages — they go to support. Replies arrive here.",
            "es": "🟢 <b>Chat activo.</b> Solo escribe tus mensajes — llegan a soporte. Las respuestas llegan aquí.",
            "zh": "🟢 <b>会话进行中。</b> 直接输入消息即可发送给客服，回复会到这里。",
            "fr": "🟢 <b>Chat actif.</b> Écrivez simplement vos messages — ils vont au support. Les réponses arrivent ici.",
            "de": "🟢 <b>Aktiver Chat.</b> Schreibe einfach deine Nachrichten — sie gehen an den Support. Antworten kommen hierher.",
            "ja": "🟢 <b>チャット進行中。</b> メッセージを入力するだけでサポートに届きます。返信はここに届きます。",
            "ko": "🟢 <b>활성 채팅.</b> 메시지를 입력하면 지원팀에 전달됩니다. 답변은 여기로 옵니다.",
        },
        "status_none": {
            "ru": "🛟 <b>Поддержка</b>\n\nНажмите «Начать чат», чтобы открыть окно поддержки. Здесь вы сможете писать сообщения и получать ответы агентов.",
            "en": "🛟 <b>Support</b>\n\nTap «Start chat» to open the support window. You can send messages and get replies from our agents.",
            "es": "🛟 <b>Soporte</b>\n\nPulsa «Iniciar chat» para abrir la ventana de soporte. Puedes escribir mensajes y recibir respuestas de los agentes.",
            "zh": "🛟 <b>客服</b>\n\n点击「开始聊天」打开客服窗口。您可以发送消息并接收客服回复。",
            "fr": "🛟 <b>Support</b>\n\nAppuyez sur « Démarrer le chat » pour ouvrir la fenêtre de support. Vous pouvez envoyer des messages et recevoir les réponses des agents.",
            "de": "🛟 <b>Support</b>\n\nTippe auf «Chat starten», um das Support-Fenster zu öffnen. Du kannst Nachrichten schreiben und Antworten der Agenten erhalten.",
            "ja": "🛟 <b>サポート</b>\n\n「チャット開始」を押すと、サポート画面が開きます。メッセージの送信と担当者からの返信の受信ができます。",
            "ko": "🛟 <b>지원</b>\n\n「채팅 시작」을 누르면 지원 창이 열립니다. 메시지를 보내고 상담원의 답변을 받을 수 있습니다.",
        },
        "session_prompt": {
            "ru": "✍️ Чат открыт. Напишите сообщение — оно уйдёт в поддержку. Можно писать несколько сообщений подряд.",
            "en": "✍️ Chat opened. Write a message — it goes to support. You can send several messages in a row.",
            "es": "✍️ Chat abierto. Escribe un mensaje — llega a soporte. Puedes enviar varios mensajes seguidos.",
            "zh": "✍️ 会话已开启。输入消息即可发送给客服，可以连续发送多条。",
            "fr": "✍️ Chat ouvert. Écrivez un message — il va au support. Vous pouvez envoyer plusieurs messages d'affilée.",
            "de": "✍️ Chat geöffnet. Schreibe eine Nachricht — sie geht an den Support. Du kannst mehrere Nachrichten hintereinander senden.",
            "ja": "✍️ チャットを開きました。メッセージを入力するとサポートに届きます。連続して送信できます。",
            "ko": "✍️ 채팅이 열렸습니다. 메시지를 입력하면 지원팀에 전달됩니다. 여러 개를 연속으로 보낼 수 있어요.",
        },
        "sent_session": {
            "ru": "✅ Отправлено в поддержку. Пишите ещё или нажмите «Завершить чат».",
            "en": "✅ Sent to support. Write more or tap «End chat».",
            "es": "✅ Enviado a soporte. Escribe más o pulsa «Finalizar chat».",
            "zh": "✅ 已发送给客服。可继续输入或点击「结束聊天」。",
            "fr": "✅ Envoyé au support. Écrivez encore ou appuyez sur « Terminer le chat ».",
            "de": "✅ An den Support gesendet. Schreibe weiter oder tippe auf «Chat beenden».",
            "ja": "✅ サポートに送信しました。続けて入力するか「チャット終了」を押してください。",
            "ko": "✅ 지원팀에 전송되었습니다. 계속 작성하거나 「채팅 종료」를 누르세요.",
        },
        "closed": {
            "ru": "🔚 Чат с поддержкой завершён. Спасибо за обращение!",
            "en": "🔚 Support chat closed. Thanks for reaching out!",
            "es": "🔚 Chat de soporte finalizado. ¡Gracias por contactarnos!",
            "zh": "🔚 客服会话已结束。感谢您的联系！",
            "fr": "🔚 Chat de support terminé. Merci de nous avoir contactés !",
            "de": "🔚 Support-Chat beendet. Danke für deine Nachricht!",
            "ja": "🔚 サポートチャットを終了しました。お問い合わせありがとうございました！",
            "ko": "🔚 지원 채팅이 종료되었습니다. 문의해 주셔서 감사합니다!",
        },
        "reply_notify": {
            "ru": "💬 Поддержка ответила вам! Откройте окно поддержки, чтобы прочитать и ответить.",
            "en": "💬 Support replied to you! Open the support window to read and reply.",
            "es": "💬 ¡Soporte te respondió! Abre la ventana de soporte para leer y responder.",
            "zh": "💬 客服已回复您！打开客服窗口即可查看并回复。",
            "fr": "💬 Le support vous a répondu ! Ouvrez la fenêtre de support pour lire et répondre.",
            "de": "💬 Der Support hat dir geantwortet! Öffne das Support-Fenster zum Lesen und Antworten.",
            "ja": "💬 サポートから返信がありました！サポート画面を開いて確認・返信してください。",
            "ko": "💬 지원팀이 답변했습니다! 지원 창을 열어 확인하고 답장하세요.",
        },
    }

    def _sl(self, key: str, lang: str) -> str:
        d = self.SUPPORT_L.get(key, {})
        return d.get(lang) or d.get("en") or ""

    
    HELP_TEXT_RU = {
        "city":       ("🏙️ <b>Город (главная)</b>\n\nГлавная — сводка вашей империи: общий доход $CITY/ч, "
                       "уровень и прогресс XP, активные баффы и быстрый переход к ключевым разделам. "
                       "Кнопка «Собрать всё» забирает весь накопленный доход со всех бизнесов одним кликом."),
        "plots":      ("🗺️ <b>Участки и аукцион</b>\n\nКарта города делится на участки. Свободные можно купить "
                       "сразу за TON, аукционные — выиграть на торгах. На участке размещается один бизнес "
                       "соответствующего тира. Налог за владение списывается ежечасно."),
        "businesses": ("🏢 <b>Мои бизнесы</b>\n\nКаждый бизнес производит ресурс и потребляет смежные. "
                       "Уровень повышается через прокачку. Износ снижает производство — обслуживайте техникой. "
                       "Кнопкой «Собрать» забираете накопленный $CITY, кнопкой «Подробнее» открываете детали, "
                       "патрона и активный бафф."),
        "market":     ("💱 <b>Рынок и цены</b>\n\nГлобальный рынок ресурсов с динамическим ценообразованием: "
                       "чем больше предложение — тем ниже цена. Покупайте дефицитное, продавайте излишки. "
                       "В админ-панели → «Данные» → «Цены товаров» доступна полная статистика."),
        "alliances":  ("🤝 <b>Альянсы и патроны</b>\n\nБизнесы 1–2 тира берут патрона из 3-го тира. Контракт "
                       "даёт вассалу бафф патрона и часть стейка $CITY. Снять патрона можно в деталях бизнеса "
                       "(кнопка «Снять»). Патрон выбирает один из доступных T3-баффов и они применяются "
                       "ко всем его вассалам."),
        "buffs":      ("✨ <b>Баффы Tier-3</b>\n\nРесурсы Tier-3 — это одновременно и товар, и <b>усиления (баффы)</b> "
                       "для всей вашей империи: пока ресурс третьего эшелона у вас на складе, он даёт постоянное "
                       "преимущество — множитель производства, ёмкость склада, снижение износа и т.п. Владелец T3-бизнеса "
                       "выбирает бафф один раз и может сменить его в любой момент; после смены все вассалы получают "
                       "уведомление, а интерфейс обновляется в реальном времени."),
        "wallet":     ("💼 <b>Кошелёк и вывод</b>\n\nДоход в $CITY конвертируется в TON по фиксированному курсу. "
                       "Для вывода нужен подключённый TON-кошелёк (TonConnect) или email-адрес и пройденная 2FA. "
                       "Заявки на вывод обрабатываются админом — ожидайте уведомление в боте."),
        "referrals":  ("👥 <b>Рефералы и бонусы</b>\n\nПриглашайте друзей по своей реф-ссылке и получайте "
                       "процент от их первых покупок и налогов. Активные промокоды можно ввести в разделе "
                       "«Промо». Ежедневные награды начисляются за вход."),
        "settings":   ("⚙️ <b>Настройки и Telegram</b>\n\nВ настройках вы привязываете Telegram (для уведомлений), "
                       "включаете 2FA, меняете язык и пароль, удаляете аккаунт. Привязка Telegram открывает "
                       "доступ к этому боту, уведомлениям о выводах и важных событиях."),
        "admin":      ("🔑 <b>Админ-панель</b>\n\nДоступна только администраторам. Содержит вкладки: Игроки, "
                       "Цены, Нагрузка, Транзакции (со встроенным поиском по ID), Кредиты, Налоги, Промо, "
                       "Объявления (с картинками и inline-кнопками), Контракт, Мульти-аккаунты."),
    }
    HELP_TEXT_EN = {
        "city":       ("🏙️ <b>City (home)</b>\n\nThe home page summarises your empire: total $CITY/h income, "
                       "level + XP progress, active buffs, quick links to key sections. The «Collect all» "
                       "button claims accumulated income from every business at once."),
        "plots":      ("🗺️ <b>Plots & auction</b>\n\nThe city map is divided into plots. Free ones are sold for "
                       "TON instantly, auction plots go to the highest bidder. One business of the matching "
                       "tier sits on each plot. An hourly tax is charged for ownership."),
        "businesses": ("🏢 <b>My businesses</b>\n\nEach business produces one resource and consumes related ones. "
                       "Level up to boost output. Wear lowers production — use repair kits. «Collect» grabs "
                       "accumulated $CITY, «Details» opens patron and active buff info."),
        "market":     ("💱 <b>Market & prices</b>\n\nGlobal resource market with dynamic pricing: more supply → "
                       "lower price. Buy what's scarce, sell surplus. Admin → Data → Prices has full stats."),
        "alliances":  ("🤝 <b>Alliances & patrons</b>\n\nTier-1/2 businesses can take a Tier-3 patron. The contract "
                       "gives the vassal the patron's buff plus a $CITY stake share. Detach via business "
                       "details → «Remove». Patrons pick one T3 buff applied to every vassal."),
        "buffs":      ("✨ <b>Tier-3 buffs</b>\n\nTier-3 resources double as <b>buffs</b> for your whole empire: while a "
                       "third-tier resource sits in your storage it grants a permanent advantage — production "
                       "multiplier, storage capacity, wear reduction, etc. The T3 owner picks a buff once and can "
                       "swap it at any time; every vassal is notified and the UI updates in real time."),
        "wallet":     ("💼 <b>Wallet & withdrawals</b>\n\n$CITY income converts to TON at a fixed rate. To withdraw "
                       "you need a connected TON wallet (TonConnect) or an email + passed 2FA. Requests are "
                       "approved by the admin — wait for a bot notification."),
        "referrals":  ("👥 <b>Referrals & bonuses</b>\n\nInvite friends using your referral link and earn a "
                       "percentage from their first purchases and taxes. Active promo codes can be redeemed "
                       "in «Promo». Daily login rewards are granted automatically."),
        "settings":   ("⚙️ <b>Settings & Telegram</b>\n\nSettings let you link Telegram (for notifications), "
                       "toggle 2FA, change language and password, delete the account. Linking Telegram unlocks "
                       "this bot, withdrawal notifications and major event alerts."),
        "admin":      ("🔑 <b>Admin panel</b>\n\nFor admins only. Tabs: Players, Prices, Load, Transactions "
                       "(with built-in ID search), Credits, Taxes, Promos, Announcements (with images and inline "
                       "buttons), Contract, Multi-accounts."),
    }

    # Localized section button labels (8 languages).
    HELP_LABELS = {
        "city":       {"ru": "Город (главная)", "en": "City (home)", "es": "Ciudad (inicio)", "zh": "城市（主页）", "fr": "Ville (accueil)", "de": "Stadt (Start)", "ja": "都市（ホーム）", "ko": "도시(홈)"},
        "plots":      {"ru": "Участки и аукцион", "en": "Plots & auction", "es": "Parcelas y subasta", "zh": "地块与拍卖", "fr": "Parcelles & enchères", "de": "Grundstücke & Auktion", "ja": "区画とオークション", "ko": "부지 & 경매"},
        "businesses": {"ru": "Мои бизнесы", "en": "My businesses", "es": "Mis negocios", "zh": "我的企业", "fr": "Mes entreprises", "de": "Meine Unternehmen", "ja": "マイビジネス", "ko": "내 사업"},
        "market":     {"ru": "Рынок и цены", "en": "Market & prices", "es": "Mercado y precios", "zh": "市场与价格", "fr": "Marché & prix", "de": "Markt & Preise", "ja": "市場と価格", "ko": "시장 & 가격"},
        "alliances":  {"ru": "Альянсы и патроны", "en": "Alliances & patrons", "es": "Alianzas y patrones", "zh": "联盟与赞助人", "fr": "Alliances & patrons", "de": "Allianzen & Patrone", "ja": "同盟とパトロン", "ko": "동맹 & 후원자"},
        "buffs":      {"ru": "Баффы T3", "en": "Tier-3 buffs", "es": "Mejoras T3", "zh": "T3 增益", "fr": "Bonus T3", "de": "Tier-3-Buffs", "ja": "T3バフ", "ko": "T3 버프"},
        "wallet":     {"ru": "Кошелёк и вывод", "en": "Wallet & withdrawals", "es": "Cartera y retiros", "zh": "钱包与提现", "fr": "Portefeuille & retraits", "de": "Wallet & Auszahlungen", "ja": "ウォレットと出金", "ko": "지갑 & 출금"},
        "settings":   {"ru": "Настройки и Telegram", "en": "Settings & Telegram", "es": "Ajustes y Telegram", "zh": "设置与 Telegram", "fr": "Paramètres & Telegram", "de": "Einstellungen & Telegram", "ja": "設定と Telegram", "ko": "설정 & Telegram"},
        "admin":      {"ru": "Админ-панель", "en": "Admin panel", "es": "Panel de admin", "zh": "管理面板", "fr": "Panneau admin", "de": "Admin-Panel", "ja": "管理パネル", "ko": "관리자 패널"},
    }

    # Full FAQ text per section, per language (1.4 — describes real features).
    HELP_TEXT = {
        "ru": HELP_TEXT_RU,
        "en": HELP_TEXT_EN,
        "es": {
            "city": "🏙️ <b>Ciudad (inicio)</b>\n\nLa página principal resume tu imperio: ingreso total $CITY/h, nivel y progreso de XP, mejoras activas y accesos rápidos. El botón «Recoger todo» reclama de una vez los ingresos acumulados de todos tus negocios.",
            "plots": "🗺️ <b>Parcelas y subasta</b>\n\nEl mapa se divide en parcelas. Las libres se compran al instante con TON; las de subasta van al mejor postor. En cada parcela cabe un negocio del tier correspondiente. Se cobra un impuesto por hora por la propiedad.",
            "businesses": "🏢 <b>Mis negocios</b>\n\nCada negocio produce un recurso y consume otros relacionados. Sube de nivel para aumentar la producción. El desgaste reduce la producción — usa kits de reparación. «Recoger» toma el $CITY acumulado; «Detalles» abre patrón y mejora activa.",
            "market": "💱 <b>Mercado y precios</b>\n\nMercado global de recursos con precios dinámicos: a más oferta, menor precio. Compra lo escaso y vende el excedente. En Admin → Datos → Precios hay estadísticas completas.",
            "alliances": "🤝 <b>Alianzas y patrones</b>\n\nLos negocios de tier 1–2 pueden tomar un patrón de tier 3. El contrato da al vasallo la mejora del patrón y una parte del stake $CITY. Puedes quitar al patrón en los detalles del negocio.",
            "buffs": "✨ <b>Mejoras Tier-3</b>\n\nLos recursos Tier-3 son a la vez producto y <b>mejoras (buffs)</b> para todo tu imperio: mientras un recurso de tercer nivel esté en tu almacén, otorga una ventaja permanente — multiplicador de producción, capacidad de almacén, reducción de desgaste, etc. El propietario T3 elige la mejora una vez y puede cambiarla en cualquier momento; todos los vasallos reciben aviso y la interfaz se actualiza en tiempo real.",
            "wallet": "💼 <b>Cartera y retiros</b>\n\nLos ingresos en $CITY se convierten a TON a tasa fija. Para retirar necesitas una cartera TON conectada (TonConnect) o un email + 2FA. Las solicitudes las aprueba el admin — espera una notificación del bot.",
            "settings": "⚙️ <b>Ajustes y Telegram</b>\n\nEn ajustes vinculas Telegram (para notificaciones), activas 2FA, cambias idioma y contraseña, o eliminas la cuenta. Vincular Telegram habilita este bot y los avisos de retiros y eventos importantes.",
            "admin": "🔑 <b>Panel de admin</b>\n\nSolo para administradores. Pestañas: Jugadores, Precios, Carga, Transacciones (con búsqueda por ID), Créditos, Impuestos, Promos, Anuncios, Contrato, Multicuentas.",
        },
        "zh": {
            "city": "🏙️ <b>城市（主页）</b>\n\n主页汇总你的商业帝国：$CITY/小时总收入、等级与经验进度、生效的增益以及快捷入口。「全部收取」按钮可一键领取所有企业累计的收入。",
            "plots": "🗺️ <b>地块与拍卖</b>\n\n城市地图划分为地块。空闲地块可用 TON 直接购买，拍卖地块归出价最高者。每个地块放置一个对应等级的企业。持有地块需按小时缴税。",
            "businesses": "🏢 <b>我的企业</b>\n\n每个企业生产一种资源并消耗相关资源。升级可提高产量。磨损会降低产量——使用维修包。「收取」领取累计的 $CITY，「详情」查看赞助人和生效增益。",
            "market": "💱 <b>市场与价格</b>\n\n资源全球市场采用动态定价：供应越多，价格越低。买入稀缺、卖出过剩。管理面板 → 数据 → 价格 提供完整统计。",
            "alliances": "🤝 <b>联盟与赞助人</b>\n\n一、二级企业可选择三级赞助人。合约让附庸获得赞助人的增益及部分 $CITY 权益。可在企业详情中解除赞助人。",
            "buffs": "✨ <b>三级增益</b>\n\n三级资源既是商品，也是整个帝国的<b>增益（Buff）</b>：只要仓库中存有三级资源，就会获得永久优势——产量倍率、仓库容量、磨损降低等。三级企业主可随时选择或更换增益，所有附庸会立即收到通知，界面实时更新。",
            "wallet": "💼 <b>钱包与提现</b>\n\n$CITY 收入按固定汇率兑换为 TON。提现需连接 TON 钱包（TonConnect）或绑定邮箱并通过 2FA。提现申请由管理员审批——请等待机器人通知。",
            "settings": "⚙️ <b>设置与 Telegram</b>\n\n在设置中绑定 Telegram（用于通知）、开启 2FA、修改语言和密码、删除账号。绑定 Telegram 后即可使用本机器人并接收提现与重要事件通知。",
            "admin": "🔑 <b>管理面板</b>\n\n仅管理员可用。标签页：玩家、价格、负载、交易（内置 ID 搜索）、信贷、税收、促销、公告、合约、多账号检测。",
        },
        "fr": {
            "city": "🏙️ <b>Ville (accueil)</b>\n\nLa page d'accueil résume ton empire : revenu total $CITY/h, niveau et progression d'XP, bonus actifs et accès rapides. Le bouton « Tout collecter » récupère d'un coup les revenus accumulés de toutes tes entreprises.",
            "plots": "🗺️ <b>Parcelles & enchères</b>\n\nLa carte est divisée en parcelles. Les libres s'achètent instantanément en TON ; celles aux enchères vont au plus offrant. Une entreprise du tier correspondant occupe chaque parcelle. Une taxe horaire est prélevée pour la possession.",
            "businesses": "🏢 <b>Mes entreprises</b>\n\nChaque entreprise produit une ressource et en consomme d'autres. Monte de niveau pour augmenter la production. L'usure réduit la production — utilise des kits de réparation. « Collecter » prend le $CITY accumulé ; « Détails » ouvre le patron et le bonus actif.",
            "market": "💱 <b>Marché & prix</b>\n\nMarché mondial des ressources à tarification dynamique : plus d'offre → prix plus bas. Achète ce qui est rare, vends le surplus. Admin → Données → Prix propose des statistiques complètes.",
            "alliances": "🤝 <b>Alliances & patrons</b>\n\nLes entreprises tier 1–2 peuvent prendre un patron de tier 3. Le contrat donne au vassal le bonus du patron et une part du stake $CITY. On retire le patron dans les détails de l'entreprise.",
            "buffs": "✨ <b>Bonus Tier-3</b>\n\nLes ressources de tier 3 sont à la fois des marchandises et des <b>bonus</b> pour tout ton empire : tant qu'une ressource de troisième palier reste dans ton stock, elle confère un avantage permanent — multiplicateur de production, capacité de stockage, réduction d'usure, etc. Le propriétaire T3 choisit un bonus et peut en changer à tout moment ; tous les vassaux sont notifiés et l'interface se met à jour en temps réel.",
            "wallet": "💼 <b>Portefeuille & retraits</b>\n\nLes revenus en $CITY se convertissent en TON à taux fixe. Pour retirer, il faut un portefeuille TON connecté (TonConnect) ou un e-mail + 2FA. Les demandes sont approuvées par l'admin — attends une notification du bot.",
            "settings": "⚙️ <b>Paramètres & Telegram</b>\n\nDans les paramètres, tu lies Telegram (pour les notifications), actives la 2FA, changes la langue et le mot de passe, supprimes le compte. Lier Telegram active ce bot et les alertes de retraits et d'événements importants.",
            "admin": "🔑 <b>Panneau admin</b>\n\nRéservé aux administrateurs. Onglets : Joueurs, Prix, Charge, Transactions (recherche par ID intégrée), Crédits, Taxes, Promos, Annonces, Contrat, Multi-comptes.",
        },
        "de": {
            "city": "🏙️ <b>Stadt (Start)</b>\n\nDie Startseite fasst dein Imperium zusammen: Gesamteinkommen $CITY/h, Level und XP-Fortschritt, aktive Buffs und Schnellzugriffe. Der Button «Alles einsammeln» holt das gesammelte Einkommen aller Unternehmen auf einmal.",
            "plots": "🗺️ <b>Grundstücke & Auktion</b>\n\nDie Karte ist in Grundstücke unterteilt. Freie werden sofort mit TON gekauft, Auktions-Grundstücke gehen an den Höchstbietenden. Auf jedem Grundstück steht ein Unternehmen des passenden Tiers. Für den Besitz fällt eine stündliche Steuer an.",
            "businesses": "🏢 <b>Meine Unternehmen</b>\n\nJedes Unternehmen produziert eine Ressource und verbraucht verwandte. Level-Ups erhöhen die Produktion. Verschleiß senkt die Produktion — nutze Reparatur-Kits. «Einsammeln» nimmt das gesammelte $CITY, «Details» öffnet Patron und aktiven Buff.",
            "market": "💱 <b>Markt & Preise</b>\n\nGlobaler Ressourcenmarkt mit dynamischer Preisbildung: mehr Angebot → niedrigerer Preis. Kaufe Knappes, verkaufe Überschuss. Admin → Daten → Preise zeigt vollständige Statistiken.",
            "alliances": "🤝 <b>Allianzen & Patrone</b>\n\nUnternehmen der Tiers 1–2 können einen Tier-3-Patron nehmen. Der Vertrag gibt dem Vasallen den Buff des Patrons und einen Anteil am $CITY-Stake. Den Patron entfernst du in den Unternehmensdetails.",
            "buffs": "✨ <b>Tier-3-Buffs</b>\n\nTier-3-Ressourcen sind zugleich Handelsgut und <b>Buff</b> für dein ganzes Imperium: solange eine Ressource der dritten Stufe in deinem Lager liegt, gibt sie einen dauerhaften Vorteil — Produktionsmultiplikator, Lagerkapazität, Verschleißreduktion usw. Der T3-Besitzer wählt einen Buff und kann ihn jederzeit wechseln; alle Vasallen werden benachrichtigt und die UI aktualisiert sich in Echtzeit.",
            "wallet": "💼 <b>Wallet & Auszahlungen</b>\n\n$CITY-Einkommen wird zu festem Kurs in TON umgewandelt. Zum Auszahlen brauchst du eine verbundene TON-Wallet (TonConnect) oder E-Mail + 2FA. Anträge werden vom Admin freigegeben — warte auf eine Bot-Benachrichtigung.",
            "settings": "⚙️ <b>Einstellungen & Telegram</b>\n\nIn den Einstellungen verknüpfst du Telegram (für Benachrichtigungen), aktivierst 2FA, änderst Sprache und Passwort, löschst das Konto. Telegram zu verknüpfen aktiviert diesen Bot sowie Auszahlungs- und Event-Hinweise.",
            "admin": "🔑 <b>Admin-Panel</b>\n\nNur für Administratoren. Tabs: Spieler, Preise, Last, Transaktionen (mit ID-Suche), Kredite, Steuern, Promos, Ankündigungen, Vertrag, Multi-Accounts.",
        },
        "ja": {
            "city": "🏙️ <b>都市（ホーム）</b>\n\nホームはあなたの帝国の概要です：総収入 $CITY/時、レベルとXP進捗、有効なバフ、主要セクションへのショートカット。「全て回収」ボタンで全ビジネスの蓄積収入を一括で受け取れます。",
            "plots": "🗺️ <b>区画とオークション</b>\n\n都市マップは区画に分かれています。空き区画は TON で即購入、オークション区画は最高入札者へ。各区画には対応ティアのビジネスを1つ配置します。保有には毎時課税されます。",
            "businesses": "🏢 <b>マイビジネス</b>\n\n各ビジネスは1つの資源を生産し関連資源を消費します。レベルアップで生産量が増加。摩耗で生産が低下——リペアキットで整備を。「回収」で蓄積 $CITY を取得、「詳細」でパトロンと有効バフを表示。",
            "market": "💱 <b>市場と価格</b>\n\n動的価格の資源グローバル市場：供給が多いほど価格は下がります。不足を買い、余剰を売りましょう。管理パネル → データ → 価格 に詳細な統計があります。",
            "alliances": "🤝 <b>同盟とパトロン</b>\n\nティア1〜2のビジネスはティア3のパトロンを取れます。契約で臣下はパトロンのバフと $CITY ステークの一部を得ます。パトロンはビジネス詳細から解除できます。",
            "buffs": "✨ <b>ティア3バフ</b>\n\nティア3の資源は商品であると同時に、帝国全体の<b>バフ</b>でもあります：ティア3資源が倉庫にある間、生産倍率・倉庫容量・摩耗軽減などの恒久的な優位がもたらされます。T3所有者はバフを1つ選び、いつでも変更可能——全臣下に通知が届き、UIはリアルタイムで更新されます。",
            "wallet": "💼 <b>ウォレットと出金</b>\n\n$CITY 収入は固定レートで TON に換算されます。出金には接続済みの TON ウォレット（TonConnect）またはメール＋2FA が必要です。申請は管理者が承認——ボットの通知をお待ちください。",
            "settings": "⚙️ <b>設定と Telegram</b>\n\n設定で Telegram を連携（通知用）、2FA の切替、言語やパスワードの変更、アカウント削除が可能。Telegram 連携でこのボットと出金・重要イベント通知が有効になります。",
            "admin": "🔑 <b>管理パネル</b>\n\n管理者専用。タブ：プレイヤー、価格、負荷、取引（ID検索内蔵）、クレジット、税、プロモ、お知らせ、コントラクト、マルチアカウント。",
        },
        "ko": {
            "city": "🏙️ <b>도시(홈)</b>\n\n홈은 당신의 제국 요약입니다: 총수입 $CITY/시, 레벨·XP 진행도, 활성 버프, 주요 섹션 바로가기. 「모두 수집」 버튼으로 모든 사업의 누적 수입을 한 번에 받을 수 있습니다.",
            "plots": "🗺️ <b>부지 & 경매</b>\n\n도시 지도는 부지로 나뉩니다. 빈 부지는 TON으로 즉시 구매, 경매 부지는 최고 입찰자에게. 각 부지에는 해당 티어의 사업 하나를 배치합니다. 보유 시 시간당 세금이 부과됩니다.",
            "businesses": "🏢 <b>내 사업</b>\n\n각 사업은 자원 하나를 생산하고 관련 자원을 소비합니다. 레벨업으로 생산량 증가. 마모는 생산을 낮춥니다——수리 키트를 사용하세요. 「수집」은 누적 $CITY, 「상세」는 후원자와 활성 버프를 엽니다.",
            "market": "💱 <b>시장 & 가격</b>\n\n동적 가격의 글로벌 자원 시장: 공급이 많을수록 가격이 낮아집니다. 부족한 것을 사고 잉여를 파세요. 관리자 → 데이터 → 가격 에서 전체 통계를 볼 수 있습니다.",
            "alliances": "🤝 <b>동맹 & 후원자</b>\n\n티어 1~2 사업은 티어 3 후원자를 둘 수 있습니다. 계약으로 봉신은 후원자의 버프와 $CITY 스테이크 일부를 받습니다. 후원자는 사업 상세에서 해제할 수 있습니다.",
            "buffs": "✨ <b>티어3 버프</b>\n\n티어3 자원은 상품이자 제국 전체를 위한 <b>버프</b>이기도 합니다: 티어3 자원이 창고에 있는 동안 생산 배수, 창고 용량, 마모 감소 등 영구적인 우위를 제공합니다. T3 소유자는 버프를 하나 선택하고 언제든 변경할 수 있으며, 모든 봉신에게 알림이 가고 UI가 실시간으로 갱신됩니다.",
            "wallet": "💼 <b>지갑 & 출금</b>\n\n$CITY 수입은 고정 환율로 TON으로 환산됩니다. 출금하려면 연결된 TON 지갑(TonConnect) 또는 이메일 + 2FA가 필요합니다. 요청은 관리자가 승인——봇 알림을 기다리세요.",
            "settings": "⚙️ <b>설정 & Telegram</b>\n\n설정에서 Telegram 연결(알림용), 2FA 전환, 언어·비밀번호 변경, 계정 삭제가 가능합니다. Telegram을 연결하면 이 봇과 출금·주요 이벤트 알림이 활성화됩니다.",
            "admin": "🔑 <b>관리자 패널</b>\n\n관리자 전용. 탭: 플레이어, 가격, 부하, 거래(ID 검색 내장), 신용, 세금, 프로모, 공지, 컨트랙트, 멀티계정.",
        },
    }

    
    FAQ_INTRO = {
        "ru": "❓ <b>Часто задаваемые вопросы:</b>\n\nВыберите раздел, чтобы получить подробное описание того, что в нём есть и как им пользоваться.",
        "en": "❓ <b>Frequently asked questions:</b>\n\nPick a section to read a full description of what it contains and how to use it.",
        "es": "❓ <b>Preguntas frecuentes:</b>\n\nElige una sección para leer una descripción completa de lo que contiene y cómo usarla.",
        "zh": "❓ <b>常见问题：</b>\n\n选择一个板块，查看其内容与使用方法的完整说明。",
        "fr": "❓ <b>Foire aux questions :</b>\n\nChoisis une section pour lire une description complète de son contenu et de son utilisation.",
        "de": "❓ <b>Häufige Fragen:</b>\n\nWähle einen Bereich für eine vollständige Beschreibung seines Inhalts und seiner Nutzung.",
        "ja": "❓ <b>よくある質問：</b>\n\nセクションを選ぶと、その内容と使い方の詳しい説明が表示されます。",
        "ko": "❓ <b>자주 묻는 질문:</b>\n\n섹션을 선택하면 해당 내용과 사용 방법에 대한 자세한 설명을 볼 수 있습니다.",
    }
    SUPPORT_BTN_LABEL = {"ru": "🛟 Поддержка", "en": "🛟 Support", "es": "🛟 Soporte", "zh": "🛟 客服",
                          "fr": "🛟 Support", "de": "🛟 Support", "ja": "🛟 サポート", "ko": "🛟 지원"}
    BACK_BTN_LABEL = {"ru": "◀️ Назад", "en": "◀️ Back", "es": "◀️ Atrás", "zh": "◀️ 返回",
                       "fr": "◀️ Retour", "de": "◀️ Zurück", "ja": "◀️ 戻る", "ko": "◀️ 뒤로"}

    async def _help_lang(self, chat_id: str) -> str:
        tg_user = await self.db.telegram_mappings.find_one({"chat_id": chat_id}, {"language": 1, "_id": 0})
        return (tg_user or {}).get("language", "en") or "en"

    async def _resolve_app_url(self) -> str:
        """Public site origin for building browser deep-links (support window).

        PRIORITY: the admin-configured «URL открытия приложения» (saved from the
        admin Promo panel into game_settings.telegram_settings.app_url) wins —
        so every bot button/link follows whatever the admin sets there.
        """
        import os
        # 1) Admin-configured app URL (Промо → «URL открытия приложения»).
        try:
            _tg = await self.db.game_settings.find_one(
                {"type": "telegram_settings"}, {"_id": 0, "app_url": 1}
            )
            _admin_url = str((_tg or {}).get("app_url") or "").strip()
            if _admin_url:
                return _admin_url.rstrip("/")
        except Exception:
            pass
        try:
            _s = await self.db.support_settings.find_one({"_id": "main"})
            if _s and _s.get("public_url"):
                return str(_s["public_url"]).rstrip("/")
        except Exception:
            pass
        base = (
            os.environ.get("BACKEND_URL", "").rstrip("/")
            or os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
            or os.environ.get("PUBLIC_URL", "").rstrip("/")
        )
        if base:
            return base
        import pathlib as _pl
        _here = _pl.Path(__file__).resolve().parent
        for _p in ("/app/frontend/.env", str(_here.parent / "frontend" / ".env"),
                   "/var/www/gramcity/frontend/.env"):
            try:
                with open(_p, "r") as _f:
                    for _line in _f:
                        if _line.startswith("REACT_APP_BACKEND_URL="):
                            return _line.split("=", 1)[1].strip().strip('"').strip("'").rstrip("/")
            except Exception:
                continue
        return ""

    async def _magic_url(self, base_url: str, chat_id: str) -> str:
        """Append an auto-login JWT so the user opens the browser already signed in."""
        try:
            user_doc = await self.db.users.find_one(
                {"$or": [{"telegram_chat_id": str(chat_id)}, {"telegram_id": str(chat_id)}]},
                {"_id": 0, "email": 1, "username": 1, "wallet_address": 1, "session_id": 1},
            )
            if not user_doc:
                return base_url
            identifier = user_doc.get("email") or user_doc.get("username") or user_doc.get("wallet_address")
            if not identifier:
                return base_url
            from auth_handler import create_token
            token = create_token({"sub": identifier}, session_id=user_doc.get("session_id"))
            sep = "&" if "?" in base_url else "?"
            return f"{base_url}{sep}auth={token}"
        except Exception as _e:
            logger.debug(f"support magic-link failed: {_e}")
            return base_url

    async def cmd_help(self, chat_id: str, is_admin: bool) -> Dict:
        """Show FAQ landing page — list of section buttons, then Support, then Back."""
        lang = await self._help_lang(chat_id)
        msg = self.FAQ_INTRO.get(lang) or self.FAQ_INTRO["en"]
        # Build 2-column grid of section buttons. Skip admin section for non-admins.
        rows = []
        cur = []
        for sid, emoji, ru, en in self.HELP_SECTIONS:
            if sid == "admin" and not is_admin:
                continue
            lbl = self.HELP_LABELS.get(sid, {})
            label = f"{emoji} {lbl.get(lang) or lbl.get('en') or en}"
            cur.append({"text": label, "callback_data": f"help_{sid}"})
            if len(cur) == 2:
                rows.append(cur)
                cur = []
        if cur:
            rows.append(cur)
        # Support button: opens the dedicated "support-only" page as a plain URL
        # link (no Telegram Mini App / web_app button — those get rejected when
        # the Mini App URL isn't registered in BotFather). Falls back to the
        # in-bot callback flow if we can't resolve a public https URL.
        support_label = self.SUPPORT_BTN_LABEL.get(lang) or self.SUPPORT_BTN_LABEL["en"]
        base = await self._resolve_app_url()
        if base and base.startswith("https://"):
            support_url = await self._magic_url(f"{base}/support-only?lang={lang}", chat_id)
            support_btn = {"text": support_label, "url": support_url}
        else:
            support_btn = {"text": support_label, "callback_data": "help_support"}
        rows.append([support_btn])
        rows.append([{
            "text": self.BACK_BTN_LABEL.get(lang) or self.BACK_BTN_LABEL["en"],
            "callback_data": "back_to_menu"
        }])
        await self.safe_send_menu(chat_id, msg, reply_markup={"inline_keyboard": rows}, context="help_menu")
        return {"ok": True}
    
    async def show_help_section(self, chat_id: str, section_id: str) -> Dict:
        """Show details of a single help section. Bottom keyboard has only Back."""
        lang = await self._help_lang(chat_id)
        text_map = self.HELP_TEXT.get(lang) or self.HELP_TEXT.get("en") or self.HELP_TEXT_EN
        from bot_i18n import bt as _bt
        msg = text_map.get(section_id) or self.HELP_TEXT_EN.get(section_id) or _bt("section_not_found", lang)
        keyboard = {"inline_keyboard": [
            [{"text": self.BACK_BTN_LABEL.get(lang) or self.BACK_BTN_LABEL["en"], "callback_data": "help_back"}],
        ]}
        await self.safe_send_menu(chat_id, msg, reply_markup=keyboard, context="help_section")
        return {"ok": True}

    async def show_support_menu(self, chat_id: str) -> Dict:
        """Support entry from Help. Opens a dedicated «support-only» mini-app
        window that contains ONLY the support chat (no sidebar, no way to
        reach the rest of the site). Auto-authenticates the user via a magic
        JWT link, so the chat shows their username instantly and agents see
        their Telegram profile (name saved on link)."""
        lang = await self._help_lang(chat_id)
        base = await self._resolve_app_url()
        text = self._sl("status_none", lang)
        rows = []
        if base and base.startswith("https://"):
            # Dedicated support-only route as a plain URL link (opens in browser).
            # Auto-login token appended by _magic_url.
            support_url = await self._magic_url(f"{base}/support-only?lang={lang}", chat_id)
            rows.append([{"text": self._sl("start", lang), "url": support_url}])
        else:
            # No public URL resolved — fall back to the in-bot flow so support
            # is still reachable.
            rows.append([{"text": self._sl("start", lang), "callback_data": "support_write"}])
        rows.append([{"text": self._sl("back", lang), "callback_data": "help_back"}])
        # Also offer a direct "🏠 На главную" button, not just the open-chat one.
        rows.append([self._home_button(lang)])
        await self.safe_send_menu(chat_id, text, reply_markup={"inline_keyboard": rows}, context="support_menu")
        return {"ok": True}

    async def start_support_write(self, chat_id: str) -> Dict:
        """Open a persistent support session — every following text message goes
        to support until the user taps «End chat»."""
        lang = await self._help_lang(chat_id)
        await self.db.telegram_mappings.update_one(
            {"chat_id": chat_id},
            {"$set": {"support_mode": True}, "$unset": {"awaiting_support": ""}},
            upsert=True,
        )
        keyboard = {"inline_keyboard": [
            [{"text": self._sl("close", lang), "callback_data": "support_close"}],
            [self._home_button(lang)],
        ]}
        await self.safe_send_menu(chat_id, self._sl("session_prompt", lang), reply_markup=keyboard, context="support_write")
        return {"ok": True}

    async def cancel_support_write(self, chat_id: str) -> Dict:
        lang = await self._help_lang(chat_id)
        await self.db.telegram_mappings.update_one(
            {"chat_id": chat_id}, {"$unset": {"awaiting_support": "", "support_mode": ""}}
        )
        await self.send_message(chat_id, self._sl("cancelled", lang))
        return {"ok": True}

    async def close_support_session(self, chat_id: str) -> Dict:
        """End the in-bot support session and archive the chat (site parity)."""
        lang = await self._help_lang(chat_id)
        await self.db.telegram_mappings.update_one(
            {"chat_id": chat_id}, {"$unset": {"awaiting_support": "", "support_mode": ""}}
        )
        try:
            from support_handler import close_support_chat_from_telegram
            await close_support_chat_from_telegram(chat_id)
        except Exception as e:
            logger.error(f"support close failed: {e}")
        await self.send_message(chat_id, self._sl("closed", lang))
        return {"ok": True}

    async def submit_support_message(self, chat_id: str, text: str) -> Dict:
        """Forward a user's free-text message into the support inbox. Keeps the
        session OPEN so the user can keep chatting until they end it."""
        lang = await self._help_lang(chat_id)
        try:
            from support_handler import create_support_message_from_telegram
            res = await create_support_message_from_telegram(chat_id, text)
        except Exception as e:
            logger.error(f"support ingest failed: {e}")
            res = {"status": "error"}
        if res.get("status") == "ok":
            # Session stays armed; confirm + offer to end.
            await self.db.telegram_mappings.update_one(
                {"chat_id": chat_id}, {"$set": {"support_mode": True}, "$unset": {"awaiting_support": ""}}
            )
            keyboard = {"inline_keyboard": [
                [{"text": self._sl("close", lang), "callback_data": "support_close"}],
                [self._home_button(lang)],
            ]}
            await self.safe_send_menu(chat_id, self._sl("sent_session", lang), reply_markup=keyboard, context="support_sent")
        else:
            # not linked / empty / error → drop the session flag
            await self.db.telegram_mappings.update_one(
                {"chat_id": chat_id}, {"$unset": {"awaiting_support": "", "support_mode": ""}}
            )
            await self.send_message(chat_id, self._sl("not_linked", lang))
        return {"ok": True}
    
    async def cmd_link(self, chat_id: str, username: str, args: list) -> Dict:
        """Handle /link command (текст на языке пользователя)."""
        from bot_i18n import bt as _bt
        lang = await self._help_lang(chat_id)
        await self.send_message(chat_id, _bt("how_to_link", lang))
        return {"ok": True}
    
    async def cmd_withdraw(self, chat_id: str, username: str, user_id_tg: str, args: list) -> Dict:
        """Handle /withdraw command - create withdrawal request"""
        user = await self.find_user_by_telegram(chat_id, username)
        
        if not user:
            await self.send_message(
                chat_id, 
                "❌ <b>Аккаунт не привязан</b>\n\nПривяжите Telegram к аккаунту GRAM City через настройки на сайте."
            )
            return {"ok": True}
        
        # Check if user has wallet
        if not user.get("wallet_address"):
            await self.send_message(
                chat_id,
                "❌ <b>Кошелёк не привязан</b>\n\nДля вывода средств сначала привяжите TON кошелёк на сайте GRAM City."
            )
            return {"ok": True}
        
        # Check withdrawal block
        block_until = user.get("withdrawal_blocked_until")
        if block_until:
            try:
                block_time = datetime.fromisoformat(block_until.replace('Z', '+00:00'))
                if datetime.now(timezone.utc) < block_time:
                    await self.send_message(
                        chat_id,
                        f"🔒 <b>Вывод заблокирован</b>\n\nДо {block_time.strftime('%d.%m.%Y %H:%M:%S')} UTC\n(блокировка после изменения настроек 2FA)"
                    )
                    return {"ok": True}
            except Exception:
                pass
        
        balance = user.get("balance_ton", 0)
        min_withdrawal = 1.0  # Minimum withdrawal amount
        
        if not args:
            await self.send_message(
                chat_id,
                f"""💸 <b>Вывод средств</b>

💰 Ваш баланс: <b>{balance:.4f} TON</b>
📤 Минимум для вывода: <b>{min_withdrawal} TON</b>

<b>Использование:</b>
<code>/withdraw [сумма]</code>

<b>Пример:</b>
<code>/withdraw 5</code> - вывести 5 TON
<code>/withdraw all</code> - вывести всё"""
            )
            return {"ok": True}
        
        # Parse amount
        amount_str = args[0].lower()
        if amount_str == "all" or amount_str == "всё":
            amount = balance
        else:
            try:
                amount = float(amount_str)
            except ValueError:
                await self.send_message(chat_id, "❌ Некорректная сумма. Введите число.")
                return {"ok": True}
        
        # Validate amount
        if amount < min_withdrawal:
            await self.send_message(chat_id, f"❌ Минимальная сумма вывода: <b>{min_withdrawal} TON</b>")
            return {"ok": True}
        
        if amount > balance:
            await self.send_message(chat_id, f"❌ Недостаточно средств. Баланс: <b>{balance:.4f} TON</b>")
            return {"ok": True}
        
        # Create withdrawal request
        import uuid  # noqa: F811
        tx_id = str(uuid.uuid4())
        
        # Calculate fee (example: 5%)
        fee_percent = 5
        fee = amount * fee_percent / 100
        net_amount = amount - fee
        
        wallet_addr = user.get("wallet_address", "")
        friendly_wallet = self._to_friendly_address(wallet_addr) if wallet_addr else wallet_addr
        
        await self.db.transactions.insert_one({
            "id": tx_id,
            "user_id": user["id"],
            "tx_type": "withdrawal",
            "amount": amount,
            "fee": fee,
            "net_amount": net_amount,
            "wallet_address": wallet_addr,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source": "telegram_bot"
        })
        
        # Deduct from balance
        await self.db.users.update_one(
            {"id": user["id"]},
            {"$inc": {"balance_ton": -amount}}
        )
        
        await self.send_message(
            chat_id,
            f"""✅ <b>Заявка на вывод создана!</b>

💵 Сумма: <b>{amount:.4f} TON</b>
💸 Комиссия ({fee_percent}%): <b>{fee:.4f} TON</b>
📤 К выводу: <b>{net_amount:.4f} TON</b>

📬 Кошелёк: <code>{friendly_wallet}</code>

⏳ Статус: <b>Ожидает подтверждения</b>
🆔 ID: <code>{tx_id[:8]}</code>

Администратор рассмотрит вашу заявку в ближайшее время."""
        )
        
        # Notify admin
        await self.notify_admin(
            f"""📤 <b>Новая заявка на вывод!</b>

👤 {user.get('username', 'Unknown')}
💵 Сумма: <b>{amount:.4f} TON</b>
📬 Кошелёк: <code>{friendly_wallet}</code>
🆔 ID: <code>{tx_id[:8]}</code>

/withdrawals - посмотреть все заявки"""
        )
        
        return {"ok": True}
    
    async def cmd_deposit(self, chat_id: str, username: str, user_id_tg: str) -> Dict:
        """Handle /deposit command - show deposit instructions"""
        user = await self.find_user_by_telegram(chat_id, username)
        
        if not user:
            await self.send_message(
                chat_id, 
                "❌ <b>Аккаунт не привязан</b>\n\nПривяжите Telegram к аккаунту GRAM City через настройки на сайте."
            )
            return {"ok": True}
        
        # Check if user has linked wallet
        if not user.get("wallet_address"):
            tg_user = await self.db.telegram_mappings.find_one({"chat_id": chat_id}, {"language": 1, "_id": 0})
            lang = tg_user.get("language", "en") if tg_user else "en"
            
            if lang == "ru":
                msg = """❌ <b>Кошелёк не привязан</b>

Для пополнения баланса необходимо сначала привязать TON кошелёк к вашему аккаунту.

📱 <b>Как привязать:</b>
1. Зайдите на сайт GRAM City
2. Откройте <b>Настройки</b>
3. В разделе <b>TON Кошелёк</b> нажмите "Привязать"
4. Подтвердите в приложении кошелька

После привязки кошелька вы сможете пополнять баланс."""
            else:
                msg = """❌ <b>Wallet not linked</b>

To deposit funds, you first need to link a TON wallet to your account.

📱 <b>How to link:</b>
1. Go to GRAM City website
2. Open <b>Settings</b>
3. In <b>TON Wallet</b> section click "Link"
4. Confirm in your wallet app

After linking your wallet, you will be able to deposit funds."""
            
            keyboard = {
                "inline_keyboard": [
                    [{"text": "🎮 Открыть настройки" if lang == "ru" else "🎮 Open Settings", "url": ((await self._resolve_app_url()) or "https://gramcity.games").rstrip("/") + "/settings?tab=wallet"}],
                    [{"text": "◀️ Назад" if lang == "ru" else "◀️ Back", "callback_data": "back_to_menu"}]
                ]
            }
            
            await self.send_message(chat_id, msg, reply_markup=keyboard)
            return {"ok": True}
        
        # Get deposit wallet (treasury wallet)
        settings = await self.db.admin_settings.find_one({"type": "payment_settings"}, {"_id": 0})
        deposit_wallet = settings.get("deposit_wallet") if settings else None
        
        if not deposit_wallet:
            deposit_wallet = "EQC...TON_CITY_WALLET"  # Placeholder
        
        friendly_deposit = self._to_friendly_address(deposit_wallet) if deposit_wallet else deposit_wallet
        
        await self.send_message(
            chat_id,
            f"""💰 <b>Пополнение баланса</b>

Для пополнения баланса GRAM City отправьте TON на кошелёк:

📬 <code>{friendly_deposit}</code>

⚠️ <b>ВАЖНО:</b>
• В комментарии к переводу укажите ваш ID:
  <code>{user.get('id', '')[:8]}</code>
• Минимальная сумма: <b>1 TON</b>
• Зачисление автоматическое (1-5 мин)

💡 Или пополните через сайт GRAM City - там удобнее и быстрее!

💳 Текущий баланс: <b>{user.get('balance_ton', 0):.4f} TON</b>"""
        )
        
        return {"ok": True}
    
    # ==================== ADMIN COMMANDS ====================
    
    async def cmd_admin(self, chat_id: str) -> Dict:
        """Admin panel overview"""
        # Get stats
        users_count = await self.db.users.count_documents({})
        businesses_count = await self.db.businesses.count_documents({})
        pending_withdrawals = await self.db.transactions.count_documents({
            "tx_type": "withdrawal", "status": "pending"
        })
        
        stats = await self.db.admin_stats.find_one({"type": "treasury"}, {"_id": 0})
        total_deposits = stats.get("total_deposits", 0) if stats else 0
        total_withdrawals = stats.get("total_withdrawals", 0) if stats else 0
        
        msg = f"""👑 <b>Админ-панель GRAM City</b>

📊 <b>Статистика:</b>
• Пользователей: <b>{users_count}</b>
• Бизнесов: <b>{businesses_count}</b>
• Депозитов: <b>{total_deposits:.2f} TON</b>
• Выводов: <b>{total_withdrawals:.2f} TON</b>

⏳ <b>Ожидают:</b>
• Выводов: <b>{pending_withdrawals}</b>

<b>Команды:</b>
/stats - Подробная статистика
/withdrawals - Ожидающие выводы
/users - Пользователи
/broadcast [текст] - Рассылка"""
        
        await self.send_message(chat_id, msg)
        return {"ok": True}
    
    async def cmd_admin_stats(self, chat_id: str) -> Dict:
        """Detailed admin stats"""
        stats = await self.db.admin_stats.find_one({"type": "treasury"}, {"_id": 0})
        
        if not stats:
            await self.send_message(chat_id, "📊 Статистика пока пуста")
            return {"ok": True}
        
        msg = f"""📊 <b>Детальная статистика</b>

💰 <b>Финансы:</b>
• Депозиты: <b>{stats.get('total_deposits', 0):.2f} TON</b>
• Выводы: <b>{stats.get('total_withdrawals', 0):.2f} TON</b>
• Комиссии с выводов: <b>{stats.get('withdrawal_fees', 0):.4f} TON</b>

🏘️ <b>Продажи:</b>
• Продажа земли: <b>{stats.get('total_plot_sales', 0):.2f} TON</b>
• Налоги: <b>{stats.get('total_tax', 0):.2f} TON</b>

📈 <b>Транзакции:</b>
• Кол-во депозитов: <b>{stats.get('deposits_count', 0)}</b>
• Кол-во выводов: <b>{stats.get('total_withdrawals_count', 0)}</b>"""
        
        await self.send_message(chat_id, msg)
        return {"ok": True}
    
    async def cmd_admin_withdrawals(self, chat_id: str) -> Dict:
        """List pending withdrawals with inline action buttons"""
        withdrawals = await self.db.transactions.find({
            "tx_type": "withdrawal", "status": "pending"
        }, {"_id": 0}).sort("created_at", -1).limit(10).to_list(10)
        
        if not withdrawals:
            await self.send_message(
                chat_id, 
                "✅ Нет ожидающих выводов",
                reply_markup={
                    "inline_keyboard": [[
                        {"text": "🔄 Обновить", "callback_data": "refresh_withdrawals"}
                    ]]
                }
            )
            return {"ok": True}
        
        # Send each withdrawal as separate message with buttons
        await self.send_message(chat_id, f"⏳ <b>Ожидающие выводы ({len(withdrawals)}):</b>")
        
        for wd in withdrawals:
            tx_id = wd.get("id", "")
            amount = wd.get("amount_ton", abs(wd.get("amount", 0)))
            net_amount = wd.get("net_amount", amount)
            commission = wd.get("commission", 0)
            
            # Полный адрес в friendly формате
            raw_addr = wd.get('user_wallet') or wd.get('to_address') or '?'
            full_address = wd.get('to_address_display') or self._to_friendly_address(raw_addr)
            
            msg = f"""👤 <b>{wd.get('user_username', 'Unknown')}</b>

💰 Сумма: <b>{amount:.4f} TON</b>
💸 К выплате: <b>{net_amount:.4f} TON</b>
📊 Комиссия: <b>{commission:.4f} TON</b>

📍 Адрес: <code>{full_address}</code>
📅 {wd.get('created_at', '')[:16]}"""
            
            # Inline buttons for approve/reject
            reply_markup = {
                "inline_keyboard": [
                    [
                        {"text": "✅ Одобрить", "callback_data": f"approve_wd_{tx_id}"},
                        {"text": "❌ Отклонить", "callback_data": f"reject_wd_{tx_id}"}
                    ]
                ]
            }
            
            await self.send_message(chat_id, msg, reply_markup=reply_markup)
        
        return {"ok": True}
    
    async def cmd_admin_users(self, chat_id: str) -> Dict:
        """List recent users"""
        users = await self.db.users.find(
            {}, 
            {"_id": 0, "hashed_password": 0}
        ).sort("created_at", -1).limit(10).to_list(10)
        
        msg = f"👥 <b>Последние пользователи ({len(users)}):</b>\n\n"
        
        for user in users:
            msg += f"""• <b>{user.get('username', 'Unknown')}</b>
  💰 {user.get('balance_ton', 0):.2f} TON
  📈 Уровень: {user.get('level', 1)}

"""
        
        await self.send_message(chat_id, msg)
        return {"ok": True}
    
    async def cmd_admin_broadcast(self, chat_id: str, message: str) -> Dict:
        """Broadcast message to all users with telegram"""
        if not message:
            await self.send_message(
                chat_id, 
                "❌ Укажите текст рассылки: /broadcast [текст]"
            )
            return {"ok": True}
        
        # Get all users with telegram_chat_id
        users = await self.db.users.find(
            {"telegram_chat_id": {"$exists": True, "$ne": None}},
            {"_id": 0, "telegram_chat_id": 1, "username": 1}
        ).to_list(1000)
        
        if not users:
            await self.send_message(chat_id, "❌ Нет пользователей с привязанным Telegram")
            return {"ok": True}
        
        broadcast_msg = f"📢 <b>Объявление от GRAM City</b>\n\n{message}"
        
        success = 0
        failed = 0
        
        for user in users:
            try:
                result = await self.send_message(user["telegram_chat_id"], broadcast_msg)
                if result:
                    success += 1
                else:
                    failed += 1
            except Exception:
                failed += 1
        
        await self.send_message(
            chat_id, 
            f"✅ <b>Рассылка завершена</b>\n\n📤 Отправлено: {success}\n❌ Ошибок: {failed}"
        )
        return {"ok": True}
    
    async def handle_callback_query(self, callback_query: Dict) -> Dict:
        """Handle button callback queries"""
        try:
            callback_id = callback_query.get("id")
            data = callback_query.get("data", "")
            chat_id = str(callback_query.get("from", {}).get("id", ""))
            message_id = callback_query.get("message", {}).get("message_id")
            _from = callback_query.get("from", {}) or {}
            username = _from.get("username", "")
            first_name = _from.get("first_name", "")
            user_id_tg = str(_from.get("id", ""))
            is_premium = bool(_from.get("is_premium", False))
            tg_language_code = _from.get("language_code") or ""

            # ── Ack Telegram INSTANTLY (must be the FIRST thing) ─────────────
            # Tell Telegram "click received" BEFORE any DB work, so the button
            # spinner stops immediately and the callback query never expires
            # (the source of `Answer callback error`). Awaited so it is
            # guaranteed sent before we run the (heavier) handler below.
            # EXCEPTION: `check_subscription` answers later WITH a result text
            # (an empty ack would consume the answer and we couldn't show
            # "Вы не подписаны").
            if data != "check_subscription":
                await self.answer_callback(callback_id, "")

            # Track activity FIRE-AND-FORGET. The bot must not wait on this DB
            # write before acking / deleting — otherwise a slow query stalls the
            # click reaction (the reported 10-14s + "Answer callback error").
            if chat_id:
                self._spawn(self._track_activity(chat_id, user_id_tg, username, first_name, is_premium, tg_language_code))

            # 1.3: delete the message that carried the pressed button, so the
            # chat doesn't pile up. Admin withdrawal cards are EXCLUDED because
            # they edit their own message in place (approve/reject/refresh).
            _admin_edit = (
                data.startswith("approve_wd_")
                or data.startswith("reject_wd_")
                or data == "refresh_withdrawals"
            )
            # `check_subscription` must NEVER auto-delete its message: when the
            # user isn't subscribed the gate has to stay on screen so they can
            # retry. We handle its deletion manually (only once subscribed).
            _skip_autodelete = _admin_edit or data == "check_subscription"
            # For navigation callbacks (back/main-menu/language switching) we
            # AWAIT the delete so we can guarantee the previous screen is
            # gone before the new one is drawn — otherwise the messages
            # sometimes stayed visible (reported for «Назад» in Статус and
            # for the language-selection screen). For everything else we
            # keep it fire-and-forget for speed.
            _navigation = data in {
                "back_to_menu", "help", "help_back", "settings", "status",
                "businesses", "status_businesses", "change_lang",
            } or data.startswith("lang_") or (data.startswith("help_") and data != "help_back")
            if message_id and not _skip_autodelete:
                if _navigation:
                    try:
                        await self.delete_message(chat_id, message_id)
                    except Exception as _e:
                        logger.debug(f"nav delete failed: {_e}")
                else:
                    self._spawn(self.delete_message(chat_id, message_id))
            
            # ── Channel-subscription check ───────────────────────────────────
            if data == "check_subscription":
                tg_user = await self.db.telegram_mappings.find_one(
                    {"chat_id": chat_id}, {"language": 1, "_id": 0}
                )
                lang = (tg_user or {}).get("language", "en")
                sub = await self.is_subscribed(chat_id)
                if sub is False:
                    # Not subscribed — show a toast, KEEP the gate message.
                    await self.answer_callback(
                        callback_id,
                        self.SUB_NOT_SUBSCRIBED.get(lang, self.SUB_NOT_SUBSCRIBED["en"]),
                        show_alert=False,
                    )
                    return {"ok": True}
                # Subscribed (or unverifiable → fail-open): remove the gate and
                # show the normal menu.
                await self.answer_callback(callback_id, "")
                if message_id:
                    try:
                        await self.delete_message(chat_id, message_id)
                    except Exception as _e:
                        logger.debug(f"sub-gate delete failed: {_e}")
                return await self.cmd_start(chat_id, username, first_name, [])
            
            # Language selection
            if data.startswith("lang_"):
                lang = data.replace("lang_", "")
                await self.db.telegram_mappings.update_one(
                    {"chat_id": chat_id},
                    {"$set": {"language": lang}},
                    upsert=True
                )
                # Язык, выбранный в боте, применяем и к аккаунту (уведомления с сайта)
                try:
                    await self.db.users.update_one({"telegram_chat_id": str(chat_id)}, {"$set": {"language": lang}})
                except Exception:
                    pass
                # Show main menu
                return await self.cmd_start(chat_id, username, first_name, [])
            
            # User commands
            if data == "status":
                return await self.cmd_status(chat_id, username, user_id_tg)

            # Promo: user's current rank/stats
            if data == "promo_myrank":
                return await self.cmd_promo_myrank(chat_id, user_id_tg)
            
            if data == "businesses" or data == "status_businesses":
                return await self.cmd_businesses(chat_id, username, user_id_tg)
            
            if data == "help":
                admin_id = await self.get_admin_telegram_id()
                is_admin = admin_id and (user_id_tg == admin_id or chat_id == admin_id)
                # Help is now an interactive FAQ — leave the previous message in place,
                # just send the new one. Subsequent navigation deletes itself.
                return await self.cmd_help(chat_id, is_admin)
            
            # Support submenu (from FAQ) — «Написать» / «Назад»
            if data == "help_support":
                return await self.show_support_menu(chat_id)

            if data == "support_write":
                return await self.start_support_write(chat_id)

            if data == "support_cancel":
                return await self.cancel_support_write(chat_id)

            if data == "support_close":
                return await self.close_support_session(chat_id)

            # Help section detail (help_city, help_plots, …) — top-level
            # delete_message already removed the FAQ list.
            if data.startswith("help_") and data != "help_back":
                section_id = data[5:]
                return await self.show_help_section(chat_id, section_id)
            
            # «Назад» from a help section — top-level delete already ran,
            # just re-send the FAQ list.
            if data == "help_back":
                admin_id = await self.get_admin_telegram_id()
                is_admin = admin_id and (user_id_tg == admin_id or chat_id == admin_id)
                return await self.cmd_help(chat_id, is_admin)
            
            if data == "settings":
                return await self.show_settings(chat_id)
            
            if data == "how_to_link":
                return await self.show_link_instructions(chat_id)
            
            if data == "back_to_menu":
                # Top-level delete removed the previous message; send fresh main menu.
                return await self.cmd_start(chat_id, username, first_name, [])

            # B2B partner panel refresh (delete old + send new)
            if data == "b2b_refresh":
                return await self.cmd_b2b_panel(chat_id, username, user_id_tg)
            
            # Change language
            if data == "change_lang":
                # Reset language to force selection
                await self.db.telegram_mappings.update_one(
                    {"chat_id": chat_id},
                    {"$unset": {"language": ""}}
                )
                return await self.cmd_start(chat_id, username, first_name, [])
            
            # Admin commands - check if admin
            admin_id = await self.get_admin_telegram_id()
            if admin_id and (chat_id == admin_id or user_id_tg == admin_id):
                if data.startswith("approve_wd_"):
                    tx_id = data.replace("approve_wd_", "")
                    admin_doc = await self._admin_2fa_account(chat_id, user_id_tg)
                    if admin_doc:                       # 2FA is on: ask for the code, do NOT approve yet
                        return await self._ask_withdrawal_2fa(callback_id, chat_id, message_id, tx_id, admin_doc)
                    return await self.process_withdrawal_action(callback_id, chat_id, message_id, tx_id, "approve")
                
                elif data.startswith("reject_wd_"):
                    tx_id = data.replace("reject_wd_", "")
                    return await self.process_withdrawal_action(callback_id, chat_id, message_id, tx_id, "reject")
                
                elif data == "refresh_withdrawals":
                    return await self.cmd_admin_withdrawals(chat_id)
            
            return {"ok": True}
            
        except Exception as e:
            logger.error(f"Callback query error: {e}")
            return {"ok": True}
    
    async def cmd_b2b_panel(self, chat_id: str, username: str, user_id_tg: str) -> Dict:
        """Show B2B partner panel with a Refresh button. Only visible to registered partners."""
        try:
            from b2b_partners import (
                get_partner_for_telegram,
                compute_partner_stats,
                build_partner_panel_text,
            )
            partner = await get_partner_for_telegram(
                self.db,
                telegram_user_id=user_id_tg,
                username=username,
            )
            tg_user = await self.db.telegram_mappings.find_one({"chat_id": chat_id}, {"language": 1, "_id": 0})
            lang = (tg_user.get("language") if tg_user else "ru") or "ru"

            if not partner:
                not_found = {
                    "ru": ("🤝 <b>B2B Партнёр</b>\n\nВы не зарегистрированы как B2B партнёр. "
                           "Свяжитесь с администратором для получения статуса партнёра."),
                    "en": ("🤝 <b>B2B Partner</b>\n\nYou are not registered as a B2B partner. "
                           "Contact the administrator to obtain partner status."),
                }
                msg = not_found.get(lang, not_found["en"])
                back = "◀️ На главную" if lang == "ru" else "◀️ Home"
                kb = {"inline_keyboard": [[{"text": back, "callback_data": "back_to_menu"}]]}
                await self.send_message(chat_id, msg, reply_markup=kb)
                return {"ok": True}

            # If telegram_user_id was empty, remember it now so future callbacks are instant
            if not partner.get("telegram_user_id") and user_id_tg:
                try:
                    await self.db.b2b_partners.update_one(
                        {"id": partner["id"]},
                        {"$set": {"telegram_user_id": str(user_id_tg)}}
                    )
                except Exception:
                    pass

            stats = await compute_partner_stats(self.db, partner)
            # Resolve bot username for the referral link (falls back to gramcity_games_bot)
            bot_username = "gramcity_games_bot"
            try:
                bot_token = await self.get_bot_token()
                if bot_token:
                    client = await self._get_session()
                    resp = await client.get(
                        f"{TELEGRAM_API_BASE}/bot{bot_token}/getMe",
                        timeout=aiohttp.ClientTimeout(total=5),
                    )
                    j = await resp.json()
                    if j.get("ok") and j.get("result", {}).get("username"):
                        bot_username = j["result"]["username"]
            except Exception:
                pass

            text = build_partner_panel_text(partner, stats, bot_username=bot_username)
            # Telegram HTML doesn't allow ** — convert to <b>
            import re as _re
            text_html = _re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)

            refresh_label = "🔄 Обновить" if lang == "ru" else "🔄 Refresh"
            back_label = "◀️ На главную" if lang == "ru" else "◀️ Home"
            keyboard = {"inline_keyboard": [
                [{"text": refresh_label, "callback_data": "b2b_refresh"}],
                [{"text": back_label, "callback_data": "back_to_menu"}],
            ]}
            await self.send_message(chat_id, text_html, parse_mode="HTML", reply_markup=keyboard)
            return {"ok": True}
        except Exception as e:
            logger.error(f"cmd_b2b_panel failed: {e}")
            try:
                await self.send_message(chat_id, "⚠️ Не удалось загрузить панель партнёра.")
            except Exception:
                pass
            return {"ok": True}

    async def show_settings(self, chat_id: str) -> Dict:
        """Show settings menu — always localised to the user's current language."""
        tg_user = await self.db.telegram_mappings.find_one({"chat_id": chat_id}, {"language": 1, "_id": 0})
        lang = (tg_user.get("language") if tg_user else "ru") or "ru"

        # Localised header (Settings + current language display).
        current_lang_flag = {
            "ru": "🇷🇺 Русский", "en": "🇬🇧 English", "es": "🇪🇸 Español",
            "zh": "🇨🇳 中文", "fr": "🇫🇷 Français", "de": "🇩🇪 Deutsch",
            "ja": "🇯🇵 日本語", "ko": "🇰🇷 한국어",
        }
        header = {
            "ru": ("⚙️ <b>Настройки</b>", "Текущий язык"),
            "en": ("⚙️ <b>Settings</b>", "Current language"),
            "es": ("⚙️ <b>Ajustes</b>", "Idioma actual"),
            "zh": ("⚙️ <b>设置</b>", "当前语言"),
            "fr": ("⚙️ <b>Paramètres</b>", "Langue actuelle"),
            "de": ("⚙️ <b>Einstellungen</b>", "Aktuelle Sprache"),
            "ja": ("⚙️ <b>設定</b>", "現在の言語"),
            "ko": ("⚙️ <b>설정</b>", "현재 언어"),
        }
        title, lang_lbl = header.get(lang, header["en"])
        msg = f"{title}\n\n{lang_lbl}: {current_lang_flag.get(lang, current_lang_flag['en'])}"

        change_labels = {
            "ru": "🌍 Сменить язык", "en": "🌍 Change language",
            "es": "🌍 Cambiar idioma", "zh": "🌍 更改语言",
            "fr": "🌍 Changer de langue", "de": "🌍 Sprache ändern",
            "ja": "🌍 言語を変更", "ko": "🌍 언어 변경",
        }
        back_labels = {
            "ru": "◀️ Назад", "en": "◀️ Back", "es": "◀️ Atrás", "zh": "◀️ 返回",
            "fr": "◀️ Retour", "de": "◀️ Zurück", "ja": "◀️ 戻る", "ko": "◀️ 뒤로",
        }
        keyboard = {
            "inline_keyboard": [
                [{"text": change_labels.get(lang, change_labels["en"]), "callback_data": "change_lang"}],
                [{"text": back_labels.get(lang, back_labels["en"]), "callback_data": "back_to_menu"}]
            ]
        }

        await self.safe_send_menu(chat_id, msg, reply_markup=keyboard, context="show_settings")
        return {"ok": True}
    
    async def show_link_instructions(self, chat_id: str) -> Dict:
        """Show how to link account"""
        tg_user = await self.db.telegram_mappings.find_one({"chat_id": chat_id}, {"language": 1, "_id": 0})
        lang = tg_user.get("language", "en") if tg_user else "en"
        
        from bot_i18n import bt as _bt
        msg = _bt("how_to_link", lang)

        keyboard = {
            "inline_keyboard": [
                [{"text": _bt("btn_open_game", lang), "url": (await self._resolve_app_url()) or "https://gramcity.games"}],
                [{"text": _bt("btn_back", lang), "callback_data": "back_to_menu"}]
            ]
        }
        
        await self.send_message(chat_id, msg, reply_markup=keyboard)
        return {"ok": True}
    
    async def answer_callback(self, callback_id: str, text: str, show_alert: bool = False):
        """Answer callback query (no-op when there is no callback, e.g. after a 2FA code)"""
        if not callback_id:
            return
        bot_token = await self.get_bot_token()
        if not bot_token:
            return
        
        try:
            client = await self._get_session()
            await client.post(
                f"{TELEGRAM_API_BASE}/bot{bot_token}/answerCallbackQuery",
                json={"callback_query_id": callback_id, "text": text, "show_alert": show_alert},
                timeout=aiohttp.ClientTimeout(total=5)
            )
        except Exception as e:
            logger.error(f"Answer callback error: {e}")
    
    async def edit_message(self, chat_id: str, message_id: int, text: str, reply_markup: Dict = None):
        """Edit existing message"""
        bot_token = await self.get_bot_token()
        if not bot_token:
            return False
        
        try:
            client = await self._get_session()
            payload = {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "parse_mode": "HTML"
            }
            if reply_markup:
                payload["reply_markup"] = reply_markup
            
            await client.post(
                f"{TELEGRAM_API_BASE}/bot{bot_token}/editMessageText",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10)
            )
            return True
        except Exception as e:
            logger.error(f"Edit message error: {e}")
            return False
    
    # ───────────── 2FA for withdrawal approvals in the bot ─────────────
    WD_2FA_TTL_SEC = 180
    WD_2FA_ATTEMPTS = 3

    async def _admin_2fa_account(self, chat_id: str, user_id_tg: str = "") -> Optional[Dict]:
        """The admin account linked to this Telegram chat, if it has TOTP 2FA turned on."""
        ors = [{"telegram_chat_id": str(chat_id)}]
        if user_id_tg:
            ors += [{"telegram_id": str(user_id_tg)}, {"telegram_user_id": str(user_id_tg)}]
        u = await self.db.users.find_one({"$or": ors, "is_admin": True},
                                         {"_id": 0, "id": 1, "username": 1, "is_2fa_enabled": 1, "two_factor_secret": 1})
        if u and u.get("is_2fa_enabled") and u.get("two_factor_secret"):
            return u
        return None

    async def _ask_withdrawal_2fa(self, callback_id, chat_id, message_id, tx_id, admin_doc) -> Dict:
        tx = await self.db.transactions.find_one({"id": tx_id}, {"_id": 0, "status": 1, "net_amount": 1, "user_username": 1})
        if not tx:
            await self.answer_callback(callback_id, "❌ Заявка не найдена"); return {"ok": True}
        if tx.get("status") != "pending":
            await self.answer_callback(callback_id, "⚠️ Заявка уже обработана"); return {"ok": True}
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        await self.db.bot_2fa_pending.update_one({"chat_id": str(chat_id)}, {"$set": {
            "chat_id": str(chat_id), "tx_id": tx_id, "message_id": message_id, "admin_id": admin_doc["id"],
            "attempts": 0, "created_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=self.WD_2FA_TTL_SEC)).isoformat()}}, upsert=True)
        await self.answer_callback(callback_id, "🔐 Нужен код 2FA")
        await self.send_message(chat_id,
            f"🔐 <b>Подтверждение вывода</b>\n\n"
            f"👤 {tx.get('user_username', '—')} · 💰 {float(tx.get('net_amount', 0) or 0):.2f} TON\n\n"
            f"Пришлите 6-значный код из приложения-аутентификатора.\n"
            f"На ввод — {self.WD_2FA_TTL_SEC // 60} мин, попыток — {self.WD_2FA_ATTEMPTS}. Отмена: /cancel")
        return {"ok": True}

    async def _maybe_handle_withdrawal_2fa(self, chat_id: str, text: str, message: Dict) -> bool:
        """True when the message was the 2FA step of a pending approval (consumed)."""
        pend = await self.db.bot_2fa_pending.find_one({"chat_id": str(chat_id)}, {"_id": 0})
        if not pend:
            return False
        from datetime import datetime, timezone
        t = (text or "").strip()
        if t.lower() in ("/cancel", "отмена"):
            await self.db.bot_2fa_pending.delete_one({"chat_id": str(chat_id)})
            await self.send_message(chat_id, "Подтверждение вывода отменено. Заявка ждёт решения."); return True
        if datetime.fromisoformat(pend["expires_at"]) < datetime.now(timezone.utc):
            await self.db.bot_2fa_pending.delete_one({"chat_id": str(chat_id)})
            await self.send_message(chat_id, "⏱ Время на ввод кода вышло. Нажмите «Одобрить» ещё раз."); return True
        code = t.replace(" ", "")
        if not (code.isdigit() and len(code) == 6):
            await self.send_message(chat_id, "Пришлите 6-значный код 2FA или /cancel."); return True
        if message.get("message_id"):                   # the code must not stay in the chat
            try:
                await self.delete_message(chat_id, message["message_id"])
            except Exception:
                pass
        admin = await self.db.users.find_one({"id": pend["admin_id"], "is_admin": True},
                                             {"_id": 0, "id": 1, "username": 1, "is_2fa_enabled": 1, "two_factor_secret": 1})
        ok = False
        try:
            import pyotp
            from security.totp_crypto import decrypt_secret
            ok = bool(admin and admin.get("two_factor_secret")
                      and pyotp.TOTP(decrypt_secret(admin["two_factor_secret"])).verify(code, valid_window=1))
        except Exception as e:
            logger.warning(f"bot 2FA verify error: {e}")
        if not ok:
            left = self.WD_2FA_ATTEMPTS - int(pend.get("attempts", 0)) - 1
            await self._log_admin_action(pend, "withdrawal_2fa_failed")
            if left <= 0:
                await self.db.bot_2fa_pending.delete_one({"chat_id": str(chat_id)})
                await self.send_message(chat_id, "❌ Неверный код. Попытки закончились — подтверждение отменено, заявка ждёт решения.")
            else:
                await self.db.bot_2fa_pending.update_one({"chat_id": str(chat_id)}, {"$inc": {"attempts": 1}})
                await self.send_message(chat_id, f"❌ Неверный код. Осталось попыток: {left}.")
            return True
        # one approval per code: remove the pending record BEFORE approving (atomic)
        d = await self.db.bot_2fa_pending.delete_one({"chat_id": str(chat_id), "tx_id": pend["tx_id"]})
        if not d.deleted_count:
            return True
        await self._log_admin_action(pend, "withdrawal_2fa_ok")
        await self.process_withdrawal_action(None, chat_id, pend.get("message_id"), pend["tx_id"], "approve", verified=True)
        return True

    async def _log_admin_action(self, pend: Dict, action: str) -> None:
        try:
            from datetime import datetime, timezone
            await self.db.admin_logs.insert_one({"action": action, "source": "telegram_bot", "admin_id": pend.get("admin_id"),
                                                 "tx_id": pend.get("tx_id"), "created_at": datetime.now(timezone.utc).isoformat()})
        except Exception:
            pass

    async def process_withdrawal_action(self, callback_id: str, chat_id: str, 
                                        message_id: int, tx_id: str, action: str, verified: bool = False) -> Dict:
        """Process withdrawal approve/reject from telegram"""
        try:
            # Find transaction
            tx = await self.db.transactions.find_one({"id": tx_id})
            if not tx:
                await self.answer_callback(callback_id, "❌ Заявка не найдена")
                return {"ok": True}
            
            if tx.get("status") != "pending":
                await self.answer_callback(callback_id, "⚠️ Заявка уже обработана")
                return {"ok": True}
            
            if action == "approve":
                # 2FA guard (defence in depth): an admin with 2FA can only approve after a verified code
                if not verified and await self._admin_2fa_account(chat_id):
                    await self.answer_callback(callback_id, "🔐 Нужен код 2FA")
                    return {"ok": True}
                # Call the approval logic
                result = await self.approve_withdrawal_internal(tx)
                if result.get("success"):
                    await self.answer_callback(callback_id, "✅ Вывод одобрен!")
                    await self.edit_message(
                        chat_id, message_id,
                        f"✅ <b>ОДОБРЕНО</b>\n\n"
                        f"👤 {tx.get('user_username', 'Unknown')}\n"
                        f"💰 {tx.get('net_amount', 0):.2f} TON\n"
                        f"🔗 TX: <code>{result.get('hash', 'N/A')[:20]}...</code>"
                    )
                else:
                    await self.answer_callback(callback_id, f"❌ {result.get('error', 'Ошибка')}")
            
            elif action == "reject":
                result = await self.reject_withdrawal_internal(tx)
                if result.get("success"):
                    await self.answer_callback(callback_id, "❌ Вывод отклонён")
                    await self.edit_message(
                        chat_id, message_id,
                        f"❌ <b>ОТКЛОНЕНО</b>\n\n"
                        f"👤 {tx.get('user_username', 'Unknown')}\n"
                        f"💰 {abs(tx.get('amount_ton', tx.get('amount', 0))):.2f} TON возвращено"
                    )
                else:
                    await self.answer_callback(callback_id, f"❌ {result.get('error', 'Ошибка')}")
            
            return {"ok": True}
            
        except Exception as e:
            logger.error(f"Process withdrawal action error: {e}")
            await self.answer_callback(callback_id, f"❌ Ошибка: {str(e)[:30]}")
            return {"ok": True}
    
    async def approve_withdrawal_internal(self, tx: Dict) -> Dict:
        """Internal method to approve withdrawal - mirrors server.py logic"""
        try:
            import os
            from ton_integration import ton_client
            
            user_wallet = tx.get("user_wallet")
            from core.helpers import find_user
            user = await find_user(self.db, user_id=tx.get("user_id"), wallet=user_wallet)
            
            # Get destination address
            destination_address = None
            if user:
                destination_address = user.get("raw_address") or user.get("wallet_address")
            if not destination_address:
                destination_address = tx.get("user_raw_address") or tx.get("to_address") or user_wallet
            
            if not destination_address:
                return {"success": False, "error": "Адрес не найден"}
            
            # Get mnemonic
            sender_wallet = await self.db.admin_settings.find_one({"type": "sender_wallet"}, {"_id": 0})
            seed = sender_wallet.get("mnemonic") if sender_wallet else None
            if not seed:
                seed = os.getenv("TON_WALLET_MNEMONIC")
            
            if not seed:
                return {"success": False, "error": "Мнемоника не настроена"}
            
            net_amount = float(tx.get("net_amount", 0))
            commission = float(tx.get("commission", 0))
            
            # Получаем username для комментария
            user_username = ""
            if user:
                user_username = user.get("username", "")
            
            # Send TON
            tx_hash = await ton_client.send_ton_payout(
                dest_address=destination_address,
                amount_ton=net_amount,
                mnemonics=seed,
                user_username=user_username
            )
            
            # Update transaction
            now_iso = datetime.now(timezone.utc).isoformat()
            await self.db.transactions.update_one(
                {"id": tx["id"]},
                {"$set": {
                    "status": "completed",
                    "completed_at": now_iso,
                    "blockchain_hash": tx_hash,
                    "from_address": "Система",
                    "to_address": user_wallet
                }}
            )
            
            # Update stats
            await self.db.admin_stats.update_one(
                {"type": "treasury"},
                {"$inc": {"withdrawal_fees": commission, "total_withdrawals": net_amount, "total_withdrawals_count": 1}},
                upsert=True
            )
            
            # Notify user — use core.notify.notify_user so we send both an
            # in-app notification AND ONE mirrored Telegram message (not two).
            if tx.get("user_id"):
                try:
                    from core.notify import notify_user
                    await notify_user(
                        self.db, tx.get("user_id"),
                        title="✅ Вывод одобрен",
                        message=f"💸 Ваш запрос на вывод <b>{net_amount:.4f} TON</b> одобрен и отправлен на ваш кошелёк.",
                        type_key="withdrawal_approved",
                        priority="success",
                        payload={"tx_id": tx.get("id"), "amount": net_amount, "hash": tx_hash},
                        i18n_key="withdrawal_approved",
                        i18n_vars={"amount": f"{net_amount:.4f}"},
                        tx_hash=tx_hash,
                    )
                except Exception as _e:
                    logger.warning(f"withdrawal_approved notify (bot) failed: {_e}")
            
            return {"success": True, "hash": tx_hash}
            
        except Exception as e:
            logger.error(f"Approve withdrawal internal error: {e}")
            # Refund on error
            amount_ton_original = float(tx.get("amount_ton", 0))
            if amount_ton_original <= 0:
                amount_ton_original = float(tx.get("net_amount", 0)) + float(tx.get("commission", 0))
            
            await self.db.users.update_one(
                {"wallet_address": tx.get("user_wallet")},
                {"$inc": {"balance_ton": amount_ton_original}}
            )
            await self.db.transactions.update_one(
                {"id": tx["id"]},
                {"$set": {"status": "failed", "error": str(e)}}
            )
            return {"success": False, "error": str(e)}
    
    async def reject_withdrawal_internal(self, tx: Dict) -> Dict:
        """Internal method to reject withdrawal"""
        try:
            user_address = tx.get("user_wallet") or tx.get("from_address")
            user_id = tx.get("user_id")
            amount_to_return = float(tx.get("amount_ton") or abs(tx.get("amount", 0)))
            
            if amount_to_return <= 0:
                return {"success": False, "error": "Сумма для возврата не указана"}
            
            # Return funds
            or_conditions = []
            if user_id:
                or_conditions.append({"id": user_id})
            if user_address:
                or_conditions.append({"wallet_address": user_address})
                or_conditions.append({"raw_address": user_address})
            
            if not or_conditions:
                return {"success": False, "error": "Пользователь не найден"}
            
            update_result = await self.db.users.update_one(
                {"$or": or_conditions},
                {"$inc": {"balance_ton": amount_to_return}}
            )
            
            if update_result.modified_count > 0:
                await self.db.transactions.update_one(
                    {"id": tx["id"]},
                    {"$set": {
                        "status": "rejected",
                        "rejected_at": datetime.now(timezone.utc).isoformat(),
                        "admin_note": f"Отклонено через Telegram. Возвращено {amount_to_return} TON"
                    }}
                )
                
                # Notify user (in-app + one Telegram message with a home button)
                if user_id:
                    try:
                        from core.notify import notify_user
                        await notify_user(
                            self.db, user_id,
                            title="❌ Вывод отклонён",
                            message=(
                                f"💰 Ваш запрос на вывод <b>{amount_to_return:.4f} TON</b> отклонён администратором.\n\n"
                                f"↩️ Средства возвращены на ваш баланс."
                            ),
                            type_key="withdrawal_rejected",
                            priority="warning",
                            payload={"tx_id": tx.get("id"), "amount": amount_to_return},
                            add_home_button=True,
                            i18n_key="withdrawal_rejected",
                            i18n_vars={"amount": f"{amount_to_return:.4f}"},
                        )
                    except Exception as _e:
                        logger.warning(f"withdrawal_rejected notify (bot) failed: {_e}")
                
                return {"success": True}
            else:
                return {"success": False, "error": "Пользователь не найден для возврата"}
                
        except Exception as e:
            logger.error(f"Reject withdrawal internal error: {e}")
            return {"success": False, "error": str(e)}
    
    # ==================== NOTIFICATION HELPERS ====================
    
    async def find_user_by_telegram(self, chat_id: str, username: str = None) -> Optional[Dict]:
        """Find user by telegram chat_id (primary) or username (fallback)"""
        # First try to find by chat_id (most reliable)
        user = await self.db.users.find_one(
            {"telegram_chat_id": str(chat_id)}, 
            {"_id": 0, "hashed_password": 0}
        )
        if user:
            return user
        
        # Fallback to username if chat_id not found
        if username:
            user = await self.db.users.find_one(
                {"telegram_username": username.lower()}, 
                {"_id": 0, "hashed_password": 0}
            )
            if user:
                # Update chat_id for future lookups
                await self.db.users.update_one(
                    {"id": user["id"]},
                    {"$set": {"telegram_chat_id": str(chat_id)}}
                )
                return user
        
        return None
    
    async def notify_user(self, user_id: str, message: str) -> bool:
        """Send notification to user if they have telegram linked"""
        user = await self.db.users.find_one(
            {"id": user_id},
            {"_id": 0, "telegram_chat_id": 1, "telegram_notifications": 1}
        )
        
        if not user or not user.get("telegram_chat_id"):
            return False
        
        if not user.get("telegram_notifications", True):
            return False
        
        return await self.send_message(user["telegram_chat_id"], message)
    
    async def notify_admin(self, message: str) -> bool:
        """Send notification to admin"""
        admin_id = await self.get_admin_telegram_id()
        if not admin_id:
            return False
        
        return await self.send_message(admin_id, message)
    
    # ==================== BUSINESS NOTIFICATIONS ====================
    # Тексты — из core.notif_i18n на языке пользователя (users.language).

    async def _notify_i18n(self, user_id: str, key: str, **vars_) -> bool:
        from core.notif_i18n import render, user_lang
        user = await self.db.users.find_one({"id": user_id}, {"_id": 0, "language": 1})
        title, message = render(key, user_lang(user), **vars_)
        return await self.notify_user(user_id, f"<b>{title}</b>\n\n{message}")

    async def notify_low_durability(self, user_id: str, business_name: str, durability: float):
        return await self._notify_i18n(user_id, "low_durability", biz=business_name, durability=f"{durability:.1f}")

    async def notify_critical_durability(self, user_id: str, business_name: str, durability: float):
        return await self._notify_i18n(user_id, "critical_durability", biz=business_name, durability=f"{durability:.1f}")

    async def notify_business_stopped(self, user_id: str, business_name: str):
        return await self._notify_i18n(user_id, "business_stopped", biz=business_name)

    async def notify_deposit(self, user_id: str, amount: float, tx_hash: str):
        from core.notif_i18n import label, user_lang
        user = await self.db.users.find_one({"id": user_id}, {"_id": 0, "language": 1})
        tx_line = label("tx_line", user_lang(user)).format(hash=tx_hash) if tx_hash else ""
        return await self._notify_i18n(user_id, "deposit", amount=f"{amount:.4f}", tx_line=tx_line)

    async def notify_withdrawal_approved(self, user_id: str, amount: float, tx_hash: str):
        from core.notif_i18n import label, user_lang
        user = await self.db.users.find_one({"id": user_id}, {"_id": 0, "language": 1})
        tx_line = label("tx_line", user_lang(user)).format(hash=tx_hash) if tx_hash else ""
        return await self._notify_i18n(user_id, "withdrawal_approved", amount=f"{amount:.4f}", tx_line=tx_line)

    async def notify_withdrawal_rejected(self, user_id: str, amount: float, reason: str = ""):
        return await self._notify_i18n(user_id, "withdrawal_rejected", amount=f"{amount:.4f}")

    async def notify_admin_new_withdrawal(self, tx_data: Dict):
        """Notify admin about new withdrawal request with action buttons"""
        admin_id = await self.get_admin_telegram_id()
        if not admin_id:
            logger.warning("Admin telegram ID not configured for withdrawal notification")
            return False
        
        tx_id = tx_data.get("id", "")
        amount = tx_data.get("amount_ton", abs(tx_data.get("amount", 0)))
        net_amount = tx_data.get("net_amount", amount)
        commission = tx_data.get("commission", 0)
        
        # Полный адрес в friendly формате
        raw_addr = tx_data.get('user_wallet') or tx_data.get('to_address') or '?'
        full_address = tx_data.get('to_address_display') or self._to_friendly_address(raw_addr)
        
        msg = f"""🔔 <b>НОВАЯ ЗАЯВКА НА ВЫВОД</b>

👤 Пользователь: <b>{tx_data.get('user_username', 'Unknown')}</b>
💰 Сумма: <b>{amount:.4f} TON</b>
💸 К выплате: <b>{net_amount:.4f} TON</b>
📊 Комиссия: <b>{commission:.4f} TON</b>

📍 Адрес: <code>{full_address}</code>
📅 {tx_data.get('created_at', '')[:16]}"""
        
        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "✅ Одобрить", "callback_data": f"approve_wd_{tx_id}"},
                    {"text": "❌ Отклонить", "callback_data": f"reject_wd_{tx_id}"}
                ]
            ]
        }
        
        return await self.send_message(admin_id, msg, reply_markup=reply_markup)
    
    async def setup_webhook(self, webhook_url: str, secret_token: Optional[str] = None) -> Dict:
        """Setup telegram webhook automatically.

        F34 hardening: pass `secret_token` to Telegram's setWebhook so incoming
        webhook requests can be verified via the `X-Telegram-Bot-Api-Secret-Token`
        header. Callers are responsible for persisting the secret in the DB.
        """
        bot_token = await self.get_bot_token()
        if not bot_token:
            return {"success": False, "error": "Bot token not configured"}
        
        try:
            client = await self._get_session()
            # Delete existing webhook
            await client.post(
                f"{TELEGRAM_API_BASE}/bot{bot_token}/deleteWebhook",
                timeout=aiohttp.ClientTimeout(total=10),
                proxy=_telegram_proxy(),
            )
            
            # Set new webhook
            payload = {"url": webhook_url}
            if secret_token:
                payload["secret_token"] = secret_token
            response = await client.post(
                f"{TELEGRAM_API_BASE}/bot{bot_token}/setWebhook",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
                proxy=_telegram_proxy(),
            )
            
            if response.status == 200:
                data = await response.json()
                if data.get("ok"):
                    logger.info(f"✅ Telegram webhook set to: {webhook_url}")
                    return {"success": True, "url": webhook_url}
                else:
                    return {"success": False, "error": data.get("description", "Unknown error")}
            else:
                return {"success": False, "error": f"HTTP {response.status}"}
                
        except Exception as e:
            logger.error(f"Setup webhook error: {e}")
            return {"success": False, "error": str(e)}


# Global bot instance
telegram_bot: Optional[TelegramBot] = None

async def init_telegram_bot(db) -> TelegramBot:
    """Initialize telegram bot"""
    global telegram_bot
    telegram_bot = TelegramBot(db)
    logger.info("✅ Telegram bot initialized")
    return telegram_bot

def get_telegram_bot() -> Optional[TelegramBot]:
    """Get telegram bot instance"""
    return telegram_bot
