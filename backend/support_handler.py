"""
GRAM City — Support System
=========================
Полнофункциональная система поддержки с:
- REST API для пользователей, агентов и админа
- WebSocket для real-time чата
- Скрытый обфусцированный URL для агентов/админа
- Антифрод (rate-limit, лог просмотра конф. данных, защита от race-claim)
- Загрузка изображений локально
- Уведомления через Telegram-бот (если WebApp закрыт)
"""
from fastapi import APIRouter, HTTPException, Depends, WebSocket, WebSocketDisconnect, UploadFile, File, Form, Request
from fastapi.security import HTTPBearer
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
import uuid
import os
import json
import asyncio
import logging
import shutil
import secrets
from pathlib import Path

from passlib.context import CryptContext

logger = logging.getLogger(__name__)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Routers
support_router = APIRouter(prefix="/api/support", tags=["Support"])
support_agent_router = APIRouter(prefix="/api/sys-ops", tags=["SupportAgent"])
support_admin_router = APIRouter(prefix="/api/admin/support", tags=["SupportAdmin"])
from auth_cookie import CookieOrBearer
security = CookieOrBearer(auto_error=False)

# Globals (set from server.py)
db = None
_get_current_user = None
_get_admin_user = None
_telegram_bot_getter = None  # callable returning bot instance


# Dependency wrappers — FastAPI evaluates these at request time, so we forward
# to the module-level callables configured via init_support().
async def get_current_user_dep(request: Request):
    if _get_current_user is None:
        raise HTTPException(status_code=500, detail="Support module not initialized")
    # Accept httpOnly cookie session first, then Authorization: Bearer (fallback)
    from fastapi.security.http import HTTPAuthorizationCredentials
    from auth_cookie import extract_token
    token = extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    return await _get_current_user(creds)


async def get_admin_user_dep(request: Request):
    if _get_admin_user is None:
        raise HTTPException(status_code=500, detail="Support module not initialized")
    user = await get_current_user_dep(request)
    if not getattr(user, "is_admin", False):
        raise HTTPException(status_code=403, detail="Forbidden")
    return user

# Upload directory
def _resolve_upload_dir() -> Path:
    """Pick an upload directory that exists and is writable.

    Tries: env var SUPPORT_UPLOAD_DIR → /app/backend/uploads/support →
    relative-to-this-file backend/uploads/support → /var/www/gramcity/...
    → /tmp/gramcity-uploads as last resort. The path is mkdir'd on the way.
    """
    candidates = []
    env_dir = os.environ.get("SUPPORT_UPLOAD_DIR")
    if env_dir:
        candidates.append(Path(env_dir))
    here = Path(__file__).resolve().parent
    candidates.extend([
        Path("/app/backend/uploads/support"),
        here / "uploads" / "support",
        Path("/var/www/gramcity/backend/uploads/support"),
        Path("/srv/gramcity/backend/uploads/support"),
        Path("/tmp/gramcity-uploads/support"),
    ])
    for p in candidates:
        try:
            p.mkdir(parents=True, exist_ok=True)
            # Write-test
            probe = p / ".write_probe"
            probe.write_bytes(b"")
            probe.unlink(missing_ok=True)
            return p
        except Exception:
            continue
    # If everything failed return /tmp (which mkdir above should always succeed) — but as a final guard
    return Path("/tmp")


UPLOAD_DIR = _resolve_upload_dir()
MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5MB
# iPhone Safari sends HEIC/HEIF by default, Android / desktop Chrome may send
# WebP. Older clients can also leave content-type as "application/octet-stream".
# We accept the common image MIMEs explicitly AND fall back to extension-based
# detection so a missing/wrong content-type doesn't break the upload.
ALLOWED_IMAGE_TYPES = {
    "image/png", "image/jpeg", "image/jpg", "image/pjpeg",
    "image/webp", "image/gif",
    "image/heic", "image/heif",
    "image/heic-sequence", "image/heif-sequence",
}
ALLOWED_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".heic", ".heif"}

# Constants
MAX_AGENT_ACTIVE_CHATS = 3
USER_MAX_CHATS_PER_HOUR = 3
USER_COOLDOWN_AFTER_CLOSE_SECONDS = 5 * 60  # 5 minutes
AGENT_INACTIVITY_MINUTES = 20
USER_INACTIVITY_MINUTES = 20  # auto-close chat if user is silent this long
HIDDEN_PATH = "sys-ops-panel-x9k2m7q"


def init_support(database, get_current_user, get_admin_user, telegram_bot_getter=None):
    """Initialize support module from server.py"""
    global db, _get_current_user, _get_admin_user, _telegram_bot_getter
    db = database
    _get_current_user = get_current_user
    _get_admin_user = get_admin_user
    _telegram_bot_getter = telegram_bot_getter


# ==================== MODELS ====================

class CreateChatRequest(BaseModel):
    initial_message: Optional[str] = None


class SendMessageRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)
    # Agent-only: when set (and != "ru"), the agent's Russian `content` is
    # translated into this language before being stored/sent to the user.
    target_lang: Optional[str] = None


# Support translation: supported target languages (project's 8 languages).
SUPPORT_LANGS = {"ru", "en", "es", "zh", "fr", "de", "ja", "ko"}


class TranslateMessageRequest(BaseModel):
    target_lang: str = "ru"


class RateChatRequest(BaseModel):
    rating: int = Field(..., ge=1, le=5)


class AddAgentRequest(BaseModel):
    telegram_id: str
    display_name: str
    avatar_url: Optional[str] = None


class UpdateAgentRequest(BaseModel):
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None


# ==================== WEBSOCKET MANAGERS ====================

class SupportWSManager:
    """Tracks WebSocket connections for users and agents."""
    def __init__(self):
        # user_id -> set of WebSocket
        self.user_conns: Dict[str, set] = {}
        # agent telegram_id -> set of WebSocket
        self.agent_conns: Dict[str, set] = {}

    async def connect_user(self, ws: WebSocket, user_id: str, accept: bool = True):
        if accept:
            await ws.accept()
        self.user_conns.setdefault(user_id, set()).add(ws)

    async def connect_agent(self, ws: WebSocket, agent_tg_id: str, accept: bool = True):
        if accept:
            await ws.accept()
        self.agent_conns.setdefault(agent_tg_id, set()).add(ws)

    def disconnect_user(self, ws: WebSocket, user_id: str):
        try:
            self.user_conns.get(user_id, set()).discard(ws)
            if not self.user_conns.get(user_id):
                self.user_conns.pop(user_id, None)
        except Exception:
            pass

    def disconnect_agent(self, ws: WebSocket, agent_tg_id: str):
        try:
            self.agent_conns.get(agent_tg_id, set()).discard(ws)
            if not self.agent_conns.get(agent_tg_id):
                self.agent_conns.pop(agent_tg_id, None)
        except Exception:
            pass

    def is_user_online(self, user_id: str) -> bool:
        return user_id in self.user_conns and len(self.user_conns[user_id]) > 0

    async def send_to_user(self, user_id: str, payload: dict):
        for ws in list(self.user_conns.get(user_id, set())):
            try:
                await ws.send_json(payload)
            except Exception:
                self.disconnect_user(ws, user_id)

    async def send_to_agent(self, agent_tg_id: str, payload: dict):
        for ws in list(self.agent_conns.get(agent_tg_id, set())):
            try:
                await ws.send_json(payload)
            except Exception:
                self.disconnect_agent(ws, agent_tg_id)

    async def broadcast_to_all_agents(self, payload: dict):
        for agent_id in list(self.agent_conns.keys()):
            await self.send_to_agent(agent_id, payload)


ws_manager = SupportWSManager()


# ==================== HELPERS ====================

async def _ensure_settings():
    """Ensure support_settings doc exists"""
    settings = await db.support_settings.find_one({"_id": "main"})
    if not settings:
        await db.support_settings.insert_one({
            "_id": "main",
            "hidden_path": HIDDEN_PATH,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        settings = {"hidden_path": HIDDEN_PATH}
    return settings


async def _get_agent_by_tg(tg_id: str) -> Optional[dict]:
    if not tg_id:
        return None
    return await db.support_agents.find_one({"telegram_id": str(tg_id)}, {"_id": 0})


async def _is_user_agent_or_admin(user_doc: dict) -> bool:
    """Check whether a user (by their telegram_id link) is a support agent or admin."""
    if not user_doc:
        return False
    # If this is an agent-only auth dict, allow
    if user_doc.get("_is_agent_only"):
        return True
    if user_doc.get("is_admin"):
        return True
    tg_chat_id = user_doc.get("telegram_chat_id") or user_doc.get("telegram_id")
    if tg_chat_id:
        agent = await _get_agent_by_tg(str(tg_chat_id))
        if agent and not agent.get("is_removed"):
            return True
    return False


async def require_support_agent(request: Request):
    """Dependency: accept either main JWT (admin) or support_jwt (agent)."""
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth or not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=404, detail="Not found")
    token = auth.split(" ", 1)[1].strip()

    # Try as support_jwt first
    try:
        import jwt as _jwt
        from jwt import PyJWTError as _JWTError
        from security_middleware import get_or_generate_jwt_secret
        secret = get_or_generate_jwt_secret()
        try:
            payload = _jwt.decode(token, secret, algorithms=["HS256"], options={"verify_aud": False})
            if payload.get("aud") == "support_agent" and payload.get("agent_tg_id"):
                tg_id = str(payload["agent_tg_id"])
                # Validate session_id stored on agent doc
                agent_doc = await db.support_agents.find_one({"telegram_id": tg_id, "is_removed": {"$ne": True}}, {"_id": 0})
                if not agent_doc:
                    raise HTTPException(status_code=401, detail="Agent removed")
                if agent_doc.get("session_id") and payload.get("sid") and agent_doc["session_id"] != payload["sid"]:
                    raise HTTPException(status_code=401, detail="SESSION_OVERRIDDEN")
                # Return identity in same shape as user_doc
                return {
                    "id": agent_doc.get("id"),
                    "telegram_chat_id": tg_id,
                    "telegram_id": tg_id,
                    "is_admin": False,
                    "_is_agent_only": True,
                    "agent_doc": agent_doc,
                }
        except _JWTError:
            pass
    except Exception:
        pass

    # Fallback: try as main project JWT (admin)
    try:
        from fastapi.security.http import HTTPAuthorizationCredentials
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        if _get_current_user is None:
            raise HTTPException(status_code=500, detail="Support not initialized")
        user = await _get_current_user(creds)
        user_doc = user.dict() if hasattr(user, "dict") else dict(user) if user else {}
        if user_doc.get("id"):
            full = await db.users.find_one({"id": user_doc["id"]}, {"_id": 0})
            if full:
                user_doc = full
        if not await _is_user_agent_or_admin(user_doc):
            raise HTTPException(status_code=404, detail="Not found")
        return user_doc
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="Not found")


def _system_msg(chat_id: str, text_key: str, text: str, extra: dict = None) -> dict:
    """Create a system message"""
    return {
        "id": str(uuid.uuid4()),
        "chat_id": chat_id,
        "sender_type": "system",
        "sender_id": "system",
        "content": text,
        "system_key": text_key,
        "system_extra": extra or {},
        "image_url": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


async def _notify_telegram(user_doc: dict, message: str, link: str = None, reply_markup: dict = None):
    """Send Telegram notification to a user if their WebApp is closed."""
    try:
        if not _telegram_bot_getter:
            return
        bot = _telegram_bot_getter()
        if not bot:
            return
        chat_id = user_doc.get("telegram_chat_id") or user_doc.get("telegram_id")
        if not chat_id:
            return
        full = message
        if link:
            full = f"{message}\n\n<a href=\"{link}\">Открыть</a>"
        await bot.send_message(chat_id, full, reply_markup=reply_markup)
    except Exception as e:
        logger.debug(f"telegram notify failed: {e}")


async def _resolve_public_url() -> str:
    """Best-effort public site URL for building support deep-links."""
    try:
        s = await db.support_settings.find_one({"_id": "main"})
        if s and s.get("public_url"):
            return str(s["public_url"]).rstrip("/")
    except Exception:
        pass
    import os
    for k in ("PUBLIC_APP_URL", "BACKEND_URL", "PUBLIC_URL", "FRONTEND_URL",
              "REACT_APP_BACKEND_URL"):
        v = os.environ.get(k)
        if v and v.startswith("https://"):
            return v.rstrip("/")
    # Fallback: read REACT_APP_BACKEND_URL from frontend/.env (same layout the
    # Telegram bot uses). This is what the preview/prod environment ships.
    import pathlib as _pl
    _here = _pl.Path(__file__).resolve().parent
    for _p in ("/app/frontend/.env", str(_here.parent / "frontend" / ".env"),
               "/var/www/gramcity/frontend/.env"):
        try:
            with open(_p, "r") as _f:
                for _line in _f:
                    if _line.startswith("REACT_APP_BACKEND_URL="):
                        v = _line.split("=", 1)[1].strip().strip('"').strip("'").rstrip("/")
                        if v.startswith("https://"):
                            return v
        except Exception:
            continue
    return ""


async def _support_reply_markup_for_user(user_id: str) -> tuple:
    """Build (localized_text, inline_keyboard) for the 'support replied' push:
    a button that opens the support window on the site, translated to the
    language the user picked in the bot (?lang=xx)."""
    from telegram_bot import TelegramBot  # for SUPPORT_L strings
    # bot language from telegram_mappings
    user_doc = await db.users.find_one(
        {"id": user_id},
        {"_id": 0, "telegram_chat_id": 1, "telegram_id": 1, "language": 1,
         "email": 1, "username": 1, "wallet_address": 1, "session_id": 1},
    )
    tg = str((user_doc or {}).get("telegram_chat_id") or (user_doc or {}).get("telegram_id") or "")
    lang = (user_doc or {}).get("language") or "ru"
    if tg:
        tg_map = await db.telegram_mappings.find_one({"chat_id": tg}, {"_id": 0, "language": 1})
        if tg_map and tg_map.get("language"):
            lang = tg_map["language"]

    def _sl(key):
        d = TelegramBot.SUPPORT_L.get(key, {})
        return d.get(lang) or d.get("en") or ""

    text = _sl("reply_notify") or "💬 Support replied to you!"
    base = await _resolve_public_url()
    keyboard = None
    if base:
        # Open the dedicated support-only mini app (chat only, no site chrome).
        url = f"{base}/support-only?lang={lang}"
        # Auto-login the user so the chat window shows their username instantly.
        try:
            u = user_doc or {}
            identifier = u.get("email") or u.get("username") or u.get("wallet_address")
            if identifier:
                from auth_handler import create_token
                token = create_token(
                    {"sub": identifier}, session_id=u.get("session_id")
                )
                url = f"{url}&auth={token}"
        except Exception:
            pass
        # Use `url` (opens in-app browser) instead of `web_app` — inline
        # `web_app` buttons require the URL to be registered as the bot's
        # Mini App in BotFather; otherwise Telegram rejects the whole
        # sendMessage and the notification silently disappears.
        keyboard = {"inline_keyboard": [[
            {"text": _sl("open_window") or "🛟 Support", "url": url}
        ]]}
    return text, keyboard


# ==================== USER ENDPOINTS ====================

async def create_support_message_from_telegram(telegram_chat_id: str, content: str) -> dict:
    """Ingest a message sent via the Telegram bot into the SAME support inbox
    the website uses (support_chats / support_messages), so agents see it
    identically. Reuses the user's open chat or creates a new one.

    Returns {"status": "ok"|"not_linked"|"empty", ...}.
    """
    tg = str(telegram_chat_id)
    user_doc = await db.users.find_one(
        {"$or": [{"telegram_chat_id": tg}, {"telegram_id": tg}]}, {"_id": 0}
    )
    if not user_doc:
        return {"status": "not_linked"}

    content = (content or "").strip()[:2000]
    if not content:
        return {"status": "empty"}

    user_id = user_doc.get("id")
    # Prefer Telegram-side handle so agents see the same name as in the bot.
    tg_map = await db.telegram_mappings.find_one(
        {"chat_id": tg}, {"_id": 0, "first_name": 1, "username": 1}
    )
    tg_first = None
    if tg_map:
        tg_first = tg_map.get("first_name") or tg_map.get("username")
    username = (
        tg_first
        or user_doc.get("telegram_username")
        or user_doc.get("username")
        or user_doc.get("display_name")
        or "User"
    )
    now = datetime.now(timezone.utc)

    chat = await db.support_chats.find_one(
        {"user_id": user_id, "status": {"$in": ["new", "active"]}}, {"_id": 0}
    )
    created = False
    if not chat:
        chat_id = str(uuid.uuid4())
        chat = {
            "id": chat_id,
            "short_id": chat_id.split("-")[0].upper(),
            "user_id": user_id,
            "user_username": username,
            "agent_id": None,
            "agent_tg_id": None,
            "agent_name": None,
            "status": "new",
            "created_at": now.isoformat(),
            "first_msg_at": now.isoformat(),
            "claimed_at": None,
            "closed_at": None,
            "last_activity": now.isoformat(),
            "user_last_activity": now.isoformat(),
            "rating": None,
            "messages_count": 0,
            "unread_for_user": 0,
            "unread_for_agent": 1,
            "source": "telegram_bot",
        }
        await db.support_chats.insert_one(chat.copy())
        await db.support_messages.insert_one(
            _system_msg(chat_id, "chat_created", "Чат создан").copy()
        )
        created = True

    chat_id = chat["id"]
    msg = {
        "id": str(uuid.uuid4()),
        "chat_id": chat_id,
        "sender_type": "user",
        "sender_id": user_id,
        "sender_name": username,
        "content": content,
        "image_url": None,
        "created_at": now.isoformat(),
    }
    await db.support_messages.insert_one(msg.copy())
    upd = {"last_activity": now.isoformat(), "user_last_activity": now.isoformat()}
    if not chat.get("first_msg_at"):
        upd["first_msg_at"] = now.isoformat()
    await db.support_chats.update_one(
        {"id": chat_id}, {"$set": upd, "$inc": {"messages_count": 1, "unread_for_agent": 1}}
    )

    # Notify agents identically to the website flow.
    if created:
        await ws_manager.broadcast_to_all_agents(
            {"type": "new_chat", "chat": {**chat, "first_msg_at": now.isoformat()}}
        )
    if chat.get("agent_tg_id"):
        await ws_manager.send_to_agent(
            chat["agent_tg_id"], {"type": "new_message", "chat_id": chat_id, "message": msg}
        )
    else:
        await ws_manager.broadcast_to_all_agents(
            {"type": "chat_updated", "chat_id": chat_id, "preview": content[:80]}
        )

    try:
        agents = await db.support_agents.find({"is_removed": {"$ne": True}}, {"_id": 0}).to_list(100)
        for ag in agents:
            await _notify_telegram(
                {"telegram_chat_id": ag.get("telegram_id")},
                f"💬 Сообщение в поддержку от {username} (через Telegram)",
            )
    except Exception as e:
        logger.debug(f"agent tg notify failed: {e}")

    return {"status": "ok", "chat_id": chat_id, "created": created}


async def get_active_support_chat_from_telegram(telegram_chat_id: str) -> Optional[dict]:
    """Return the user's open (new|active) support chat, or None. Used by the
    Telegram bot to show session status."""
    tg = str(telegram_chat_id)
    user_doc = await db.users.find_one(
        {"$or": [{"telegram_chat_id": tg}, {"telegram_id": tg}]}, {"_id": 0, "id": 1}
    )
    if not user_doc:
        return None
    return await db.support_chats.find_one(
        {"user_id": user_doc["id"], "status": {"$in": ["new", "active"]}}, {"_id": 0}
    )


async def close_support_chat_from_telegram(telegram_chat_id: str) -> dict:
    """Close (archive) the user's open support chat from the Telegram bot.
    Mirrors the website 'close chat' action so agents see it consistently."""
    tg = str(telegram_chat_id)
    user_doc = await db.users.find_one(
        {"$or": [{"telegram_chat_id": tg}, {"telegram_id": tg}]}, {"_id": 0, "id": 1}
    )
    if not user_doc:
        return {"status": "not_linked"}
    chat = await db.support_chats.find_one(
        {"user_id": user_doc["id"], "status": {"$in": ["new", "active"]}}, {"_id": 0}
    )
    if not chat:
        return {"status": "no_active"}
    now = datetime.now(timezone.utc)
    await db.support_chats.update_one(
        {"id": chat["id"]},
        {"$set": {"status": "archived", "closed_at": now.isoformat(), "last_activity": now.isoformat()}},
    )
    await db.support_messages.insert_one(
        _system_msg(chat["id"], "chat_closed", "Чат завершён пользователем").copy()
    )
    try:
        await ws_manager.broadcast_to_all_agents({"type": "chat_closed", "chat_id": chat["id"]})
        if chat.get("agent_tg_id"):
            await ws_manager.send_to_agent(chat["agent_tg_id"], {"type": "chat_closed", "chat_id": chat["id"]})
    except Exception as e:
        logger.debug(f"close broadcast failed: {e}")
    return {"status": "ok", "chat_id": chat["id"]}


@support_router.get("/config")
async def support_user_config(current_user=Depends(get_current_user_dep)):
    """Return public support config for user (no hidden_path)."""
    return {
        "max_active": 1,
        "max_chats_per_hour": USER_MAX_CHATS_PER_HOUR,
        "cooldown_seconds": USER_COOLDOWN_AFTER_CLOSE_SECONDS,
    }


@support_router.get("/chats")
async def user_list_chats(current_user=Depends(get_current_user_dep)):
    """List user's chats (active + closed)."""
    user_id = current_user.id if hasattr(current_user, "id") else current_user.get("id")
    chats = await db.support_chats.find({"user_id": user_id}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"chats": chats}


@support_router.post("/chat/create")
async def user_create_chat(data: CreateChatRequest, current_user=Depends(get_current_user_dep)):
    """Create new support chat (with rate-limits + max-1-active)."""
    user_id = current_user.id if hasattr(current_user, "id") else current_user.get("id")

    # Check for existing active chat
    existing_active = await db.support_chats.find_one({
        "user_id": user_id,
        "status": {"$in": ["new", "active"]},
    })
    if existing_active:
        raise HTTPException(status_code=400, detail="У вас уже есть активный чат")

    now = datetime.now(timezone.utc)

    # Rate limit: max 3 chats / hour
    one_hour_ago = (now - timedelta(hours=1)).isoformat()
    recent_count = await db.support_chats.count_documents({
        "user_id": user_id,
        "created_at": {"$gte": one_hour_ago},
    })
    if recent_count >= USER_MAX_CHATS_PER_HOUR:
        raise HTTPException(status_code=429, detail=f"Лимит {USER_MAX_CHATS_PER_HOUR} чатов в час")

    # Cooldown after close
    last_closed = await db.support_chats.find_one(
        {"user_id": user_id, "status": "archived"},
        sort=[("closed_at", -1)],
    )
    if last_closed and last_closed.get("closed_at"):
        try:
            closed_dt = datetime.fromisoformat(str(last_closed["closed_at"]).replace("Z", "+00:00"))
            if closed_dt.tzinfo is None:
                closed_dt = closed_dt.replace(tzinfo=timezone.utc)
            delta = (now - closed_dt).total_seconds()
            if delta < USER_COOLDOWN_AFTER_CLOSE_SECONDS:
                remaining = int(USER_COOLDOWN_AFTER_CLOSE_SECONDS - delta)
                raise HTTPException(status_code=429, detail=f"Создать новый чат можно через {remaining} сек")
        except HTTPException:
            raise
        except Exception:
            pass

    chat_id = str(uuid.uuid4())
    short_id = chat_id.split("-")[0].upper()

    # Get user info. Prefer Telegram name when the account is linked so the
    # agent sees the same handle as in the bot conversation.
    user_doc = await db.users.find_one({"id": user_id}, {"_id": 0})
    if user_doc:
        tg_chat = str(user_doc.get("telegram_chat_id") or user_doc.get("telegram_id") or "")
        tg_first = None
        if tg_chat:
            tg_map = await db.telegram_mappings.find_one(
                {"chat_id": tg_chat}, {"_id": 0, "first_name": 1, "username": 1}
            )
            if tg_map:
                tg_first = tg_map.get("first_name") or tg_map.get("username")
        username = (
            tg_first
            or user_doc.get("telegram_username")
            or user_doc.get("username")
            or user_doc.get("display_name")
            or "User"
        )
    else:
        username = "User"

    chat = {
        "id": chat_id,
        "short_id": short_id,
        "user_id": user_id,
        "user_username": username,
        "agent_id": None,
        "agent_tg_id": None,
        "agent_name": None,
        "status": "new",
        "created_at": now.isoformat(),
        "first_msg_at": None,
        "claimed_at": None,
        "closed_at": None,
        "last_activity": now.isoformat(),
        "user_last_activity": now.isoformat(),
        "rating": None,
        "messages_count": 0,
        "unread_for_user": 0,
        "unread_for_agent": 1 if data.initial_message else 0,
    }
    await db.support_chats.insert_one(chat.copy())

    # Add system message
    sys_msg = _system_msg(chat_id, "chat_created", "Чат создан")
    await db.support_messages.insert_one(sys_msg.copy())

    # Add initial user message if provided
    if data.initial_message:
        user_msg = {
            "id": str(uuid.uuid4()),
            "chat_id": chat_id,
            "sender_type": "user",
            "sender_id": user_id,
            "sender_name": username,
            "content": data.initial_message[:2000],
            "image_url": None,
            "created_at": now.isoformat(),
        }
        await db.support_messages.insert_one(user_msg.copy())
        await db.support_chats.update_one(
            {"id": chat_id},
            {"$set": {"first_msg_at": now.isoformat()}, "$inc": {"messages_count": 1}},
        )

    # Notify all agents
    await ws_manager.broadcast_to_all_agents({
        "type": "new_chat",
        "chat": {**chat, "first_msg_at": now.isoformat() if data.initial_message else None},
    })

    # Telegram notify agents who set up bot
    try:
        agents = await db.support_agents.find({"is_removed": {"$ne": True}}, {"_id": 0}).to_list(100)
        for ag in agents:
            await _notify_telegram(
                {"telegram_chat_id": ag.get("telegram_id")},
                f"🆕 Новый чат поддержки от {username}",
            )
    except Exception as e:
        logger.debug(f"agent tg notify failed: {e}")

    return {"chat": {**chat, "first_msg_at": now.isoformat() if data.initial_message else None}}


@support_router.get("/chat/{chat_id}/messages")
async def user_get_messages(chat_id: str, current_user=Depends(get_current_user_dep)):
    """Get messages of chat (only owner)."""
    user_id = current_user.id if hasattr(current_user, "id") else current_user.get("id")
    chat = await db.support_chats.find_one({"id": chat_id, "user_id": user_id}, {"_id": 0})
    if not chat:
        raise HTTPException(status_code=404, detail="Чат не найден")
    msgs = await db.support_messages.find({"chat_id": chat_id}, {"_id": 0}).sort("created_at", 1).to_list(500)
    return {"chat": chat, "messages": msgs}


@support_router.post("/chat/{chat_id}/message")
async def user_send_message(chat_id: str, data: SendMessageRequest, current_user=Depends(get_current_user_dep)):
    """User sends a message in their chat."""
    user_id = current_user.id if hasattr(current_user, "id") else current_user.get("id")
    chat = await db.support_chats.find_one({"id": chat_id, "user_id": user_id}, {"_id": 0})
    if not chat:
        raise HTTPException(status_code=404, detail="Чат не найден")
    if chat["status"] == "archived":
        raise HTTPException(status_code=400, detail="Чат завершён")

    now = datetime.now(timezone.utc)
    user_doc = await db.users.find_one({"id": user_id}, {"_id": 0})
    username = (user_doc.get("username") or user_doc.get("display_name") or "User") if user_doc else "User"

    msg = {
        "id": str(uuid.uuid4()),
        "chat_id": chat_id,
        "sender_type": "user",
        "sender_id": user_id,
        "sender_name": username,
        "content": data.content[:2000],
        "image_url": None,
        "created_at": now.isoformat(),
    }
    await db.support_messages.insert_one(msg.copy())
    update_fields = {"last_activity": now.isoformat(), "user_last_activity": now.isoformat()}
    if not chat.get("first_msg_at"):
        update_fields["first_msg_at"] = now.isoformat()
    await db.support_chats.update_one({"id": chat_id}, {"$set": update_fields, "$inc": {"messages_count": 1, "unread_for_agent": 1}})

    # Notify agent
    if chat.get("agent_tg_id"):
        await ws_manager.send_to_agent(chat["agent_tg_id"], {"type": "new_message", "chat_id": chat_id, "message": msg})
    else:
        # Notify all agents in queue
        await ws_manager.broadcast_to_all_agents({"type": "chat_updated", "chat_id": chat_id, "preview": msg["content"][:80]})

    return {"message": msg}


@support_router.post("/chat/{chat_id}/upload")
async def user_upload_image(chat_id: str, file: UploadFile = File(...), current_user=Depends(get_current_user_dep)):
    """User uploads image."""
    user_id = current_user.id if hasattr(current_user, "id") else current_user.get("id")
    chat = await db.support_chats.find_one({"id": chat_id, "user_id": user_id}, {"_id": 0})
    if not chat:
        raise HTTPException(status_code=404, detail="Чат не найден")
    if chat["status"] == "archived":
        raise HTTPException(status_code=400, detail="Чат завершён")

    return await _handle_upload(chat_id, file, sender_type="user", sender_id=user_id)


@support_router.post("/chat/{chat_id}/mark-read")
async def user_mark_read(chat_id: str, current_user=Depends(get_current_user_dep)):
    """Reset unread_for_user counter."""
    user_id = current_user.id if hasattr(current_user, "id") else current_user.get("id")
    res = await db.support_chats.update_one({"id": chat_id, "user_id": user_id}, {"$set": {"unread_for_user": 0}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"status": "ok"}


@support_router.post("/chat/{chat_id}/rate")
async def user_rate_chat(chat_id: str, data: RateChatRequest, current_user=Depends(get_current_user_dep)):
    """Submit rating for closed chat."""
    user_id = current_user.id if hasattr(current_user, "id") else current_user.get("id")
    chat = await db.support_chats.find_one({"id": chat_id, "user_id": user_id}, {"_id": 0})
    if not chat:
        raise HTTPException(status_code=404, detail="Чат не найден")
    if chat["status"] != "archived":
        raise HTTPException(status_code=400, detail="Можно оценить только завершённый чат")
    if chat.get("rating") is not None:
        raise HTTPException(status_code=400, detail="Уже оценено")

    await db.support_chats.update_one({"id": chat_id}, {"$set": {"rating": int(data.rating)}})

    # Update agent stats
    if chat.get("agent_tg_id"):
        await db.support_agents.update_one(
            {"telegram_id": chat["agent_tg_id"]},
            {"$inc": {"rating_sum": int(data.rating), "rating_count": 1}},
        )
        # Track per-star distribution
        await db.support_agents.update_one(
            {"telegram_id": chat["agent_tg_id"]},
            {"$inc": {f"rating_dist.s{data.rating}": 1}},
        )

    # System message
    sys = _system_msg(chat_id, "chat_rated", f"Оценка пользователя: {'⭐' * int(data.rating)}", {"rating": int(data.rating)})
    await db.support_messages.insert_one(sys.copy())

    return {"status": "ok"}


class AgentExchangeBody(BaseModel):
    login_session: str
    password: str = Field(..., min_length=6, max_length=128)


def _make_support_jwt(agent_tg_id: str, session_id: str) -> str:
    import jwt as _jwt
    from security_middleware import get_or_generate_jwt_secret
    secret = get_or_generate_jwt_secret()
    payload = {
        "aud": "support_agent",
        "agent_tg_id": str(agent_tg_id),
        "sid": session_id,
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
    }
    return _jwt.encode(payload, secret, algorithm="HS256")


async def issue_agent_login_token(telegram_id: str) -> Optional[str]:
    """Called from the Telegram bot. Generates one-time login token for an agent.

    Returns the token string, or None if telegram_id is not a registered agent.
    Token TTL = 10 minutes, single-use.
    """
    if db is None:
        # Bot process forgot to call init_support() — never blow up /start.
        logger.warning("issue_agent_login_token: support db not initialised; skipping")
        return None
    agent = await db.support_agents.find_one(
        {"telegram_id": str(telegram_id), "is_removed": {"$ne": True}},
        {"_id": 0},
    )
    if not agent:
        return None
    token = secrets.token_urlsafe(32)
    await db.support_login_tokens.insert_one({
        "token": token,
        "agent_tg_id": str(telegram_id),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        "used_at": None,
    })
    return token


@support_agent_router.post("/auth/exchange")
async def agent_auth_exchange(payload: Dict[str, Any]):
    """Consume a one-time login_token (from bot link). Returns short-lived login_session.
    The login_session is then used to either set-password (first time) or login (subsequent).
    """
    token = (payload or {}).get("token")
    if not token:
        raise HTTPException(status_code=400, detail="token required")
    rec = await db.support_login_tokens.find_one_and_update(
        {"token": token, "used_at": None},
        {"$set": {"used_at": datetime.now(timezone.utc).isoformat()}},
    )
    if not rec:
        raise HTTPException(status_code=401, detail="Invalid or already used token")
    try:
        exp = datetime.fromisoformat(str(rec["expires_at"]).replace("Z", "+00:00"))
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < datetime.now(timezone.utc):
            raise HTTPException(status_code=401, detail="Token expired")
    except HTTPException:
        raise
    except Exception:
        pass

    tg_id = str(rec["agent_tg_id"])
    agent = await db.support_agents.find_one({"telegram_id": tg_id, "is_removed": {"$ne": True}}, {"_id": 0})
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Create login session (short-lived, 10 min, single-use after password submission)
    login_session = secrets.token_urlsafe(24)
    await db.support_login_sessions.insert_one({
        "id": login_session,
        "agent_tg_id": tg_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        "consumed": False,
    })

    needs_password = not agent.get("password_hash")
    return {
        "login_session": login_session,
        "telegram_id": tg_id,
        "display_name": agent.get("display_name"),
        "avatar_url": agent.get("avatar_url"),
        "needs_password": needs_password,
    }


async def _consume_login_session(login_session: str) -> str:
    """Validate & consume a login_session. Returns agent_tg_id or raises 401."""
    rec = await db.support_login_sessions.find_one_and_update(
        {"id": login_session, "consumed": False},
        {"$set": {"consumed": True}},
    )
    if not rec:
        raise HTTPException(status_code=401, detail="Invalid login session")
    try:
        exp = datetime.fromisoformat(str(rec["expires_at"]).replace("Z", "+00:00"))
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < datetime.now(timezone.utc):
            raise HTTPException(status_code=401, detail="Session expired")
    except HTTPException:
        raise
    except Exception:
        pass
    return str(rec["agent_tg_id"])


@support_agent_router.post("/auth/set-password")
async def agent_set_password(body: AgentExchangeBody):
    """First-time password set. Login session consumed; returns support JWT."""
    tg_id = await _consume_login_session(body.login_session)
    agent = await db.support_agents.find_one({"telegram_id": tg_id, "is_removed": {"$ne": True}}, {"_id": 0})
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.get("password_hash"):
        raise HTTPException(status_code=400, detail="Password already set, use login")

    pwd_hash = pwd_context.hash(body.password)
    session_id = secrets.token_urlsafe(16)
    await db.support_agents.update_one(
        {"telegram_id": tg_id},
        {"$set": {
            "password_hash": pwd_hash,
            "session_id": session_id,
            "last_login_at": datetime.now(timezone.utc).isoformat(),
        }},
    )
    token = _make_support_jwt(tg_id, session_id)
    return {"support_token": token, "agent": {
        "telegram_id": tg_id,
        "display_name": agent.get("display_name"),
        "avatar_url": agent.get("avatar_url"),
    }}


@support_agent_router.post("/auth/login")
async def agent_login(body: AgentExchangeBody):
    """Login with password. Login session consumed; returns support JWT."""
    tg_id = await _consume_login_session(body.login_session)
    agent = await db.support_agents.find_one({"telegram_id": tg_id, "is_removed": {"$ne": True}}, {"_id": 0})
    if not agent or not agent.get("password_hash"):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not pwd_context.verify(body.password, agent["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Rotate session_id → invalidates previous support_jwt
    session_id = secrets.token_urlsafe(16)
    await db.support_agents.update_one(
        {"telegram_id": tg_id},
        {"$set": {"session_id": session_id, "last_login_at": datetime.now(timezone.utc).isoformat()}},
    )
    token = _make_support_jwt(tg_id, session_id)
    return {"support_token": token, "agent": {
        "telegram_id": tg_id,
        "display_name": agent.get("display_name"),
        "avatar_url": agent.get("avatar_url"),
    }}


# ==================== AGENT ENDPOINTS ====================

@support_agent_router.get("/whoami")
async def agent_whoami(agent=Depends(require_support_agent)):
    """Return agent info (used by frontend on hidden page load)."""
    tg_id = agent.get("telegram_chat_id") or agent.get("telegram_id")
    agent_doc = await _get_agent_by_tg(str(tg_id)) if tg_id else None
    # Strip sensitive fields
    if agent_doc:
        agent_doc = {k: v for k, v in agent_doc.items() if k not in ("password_hash", "session_id")}
    is_admin = agent.get("is_admin", False)
    return {
        "telegram_id": str(tg_id) if tg_id else None,
        "is_admin": is_admin,
        "agent": agent_doc,
        "user_id": agent.get("id"),
    }


@support_agent_router.get("/chats")
async def agent_list_chats(status: str = "new", agent=Depends(require_support_agent)):
    """List chats by status (new|active|archived)."""
    if status not in ("new", "active", "archived"):
        raise HTTPException(status_code=400, detail="Invalid status")

    tg_id = str(agent.get("telegram_chat_id") or agent.get("telegram_id") or "")
    query: Dict[str, Any] = {"status": status}
    if status == "active":
        # Active means assigned to this agent
        if not agent.get("is_admin"):
            query["agent_tg_id"] = tg_id

    chats = await db.support_chats.find(query, {"_id": 0}).sort("created_at", 1 if status == "new" else -1).to_list(500)
    return {"chats": chats}


@support_agent_router.post("/chat/{chat_id}/claim")
async def agent_claim_chat(chat_id: str, agent=Depends(require_support_agent)):
    """Atomically claim a chat (race-safe)."""
    tg_id = str(agent.get("telegram_chat_id") or agent.get("telegram_id") or "")
    if not tg_id:
        raise HTTPException(status_code=400, detail="No Telegram ID linked to your account")

    agent_doc = await _get_agent_by_tg(tg_id)
    if not agent_doc:
        raise HTTPException(status_code=403, detail="You are not registered as agent")

    # Check max active chats
    active_count = await db.support_chats.count_documents({"agent_tg_id": tg_id, "status": "active"})
    if active_count >= MAX_AGENT_ACTIVE_CHATS:
        raise HTTPException(status_code=400, detail=f"Достигнут лимит {MAX_AGENT_ACTIVE_CHATS} активных чатов")

    now = datetime.now(timezone.utc)
    # Atomic claim
    result = await db.support_chats.find_one_and_update(
        {"id": chat_id, "status": "new", "agent_id": None},
        {"$set": {
            "status": "active",
            "agent_id": agent_doc.get("id") or tg_id,
            "agent_tg_id": tg_id,
            "agent_name": agent_doc.get("display_name", "Agent"),
            "claimed_at": now.isoformat(),
            "last_activity": now.isoformat(),
        }},
        return_document=True,
    )
    if not result:
        raise HTTPException(status_code=409, detail="Чат уже занят другим агентом")
    # Strip MongoDB ObjectId so response is JSON-serializable
    result.pop("_id", None)

    # Compute first response time (sec)
    if result.get("first_msg_at"):
        try:
            first_dt = datetime.fromisoformat(str(result["first_msg_at"]).replace("Z", "+00:00"))
            if first_dt.tzinfo is None:
                first_dt = first_dt.replace(tzinfo=timezone.utc)
            response_seconds = (now - first_dt).total_seconds()
            await db.support_agents.update_one(
                {"telegram_id": tg_id},
                {"$inc": {"response_time_sum": response_seconds, "response_time_count": 1}},
            )
        except Exception:
            pass

    # System message
    agent_name = agent_doc.get("display_name", "Agent")
    sys_msg = _system_msg(chat_id, "agent_joined", f"Агент {agent_name} подключился к чату", {"agent_name": agent_name})
    await db.support_messages.insert_one(sys_msg.copy())

    # Notify user via WS
    await ws_manager.send_to_user(result["user_id"], {"type": "agent_joined", "chat_id": chat_id, "agent_name": agent_name, "message": sys_msg})
    # Notify other agents to remove from "new"
    await ws_manager.broadcast_to_all_agents({"type": "chat_claimed", "chat_id": chat_id, "by": tg_id})

    # Telegram notify user if offline
    if not ws_manager.is_user_online(result["user_id"]):
        user_doc = await db.users.find_one({"id": result["user_id"]}, {"_id": 0})
        if user_doc:
            await _notify_telegram(user_doc, f"💬 Агент {agent_name} подключился к вашему чату поддержки!")

    return {"status": "claimed", "chat": {**result, "agent_name": agent_name}}


@support_agent_router.post("/chat/{chat_id}/message")
async def agent_send_message(chat_id: str, data: SendMessageRequest, agent=Depends(require_support_agent)):
    """Agent sends message."""
    tg_id = str(agent.get("telegram_chat_id") or agent.get("telegram_id") or "")
    chat = await db.support_chats.find_one({"id": chat_id}, {"_id": 0})
    if not chat:
        raise HTTPException(status_code=404, detail="Чат не найден")
    if chat["status"] == "archived":
        raise HTTPException(status_code=400, detail="Чат завершён")
    if chat.get("agent_tg_id") and chat["agent_tg_id"] != tg_id and not agent.get("is_admin"):
        raise HTTPException(status_code=403, detail="Этот чат ведёт другой агент")

    agent_doc = await _get_agent_by_tg(tg_id) or {}
    now = datetime.now(timezone.utc)

    # Agent composes in Russian. When a target language is chosen (and it is
    # not Russian), translate before storing so the USER receives the message
    # in their language, while the agent still sees the original Russian.
    original_content = data.content[:2000]
    outgoing_content = original_content
    msg_lang = "ru"
    translations = {}
    tgt = (data.target_lang or "").strip().lower()
    if tgt and tgt in SUPPORT_LANGS and tgt != "ru":
        from translation_service import translate_text as _translate
        try:
            translated = await _translate(original_content, tgt, source_lang="ru")
            if translated:
                outgoing_content = translated
                msg_lang = tgt
                translations = {"ru": original_content, tgt: translated}
        except Exception as e:
            logger.warning(f"support agent send translation failed: {e}")

    msg = {
        "id": str(uuid.uuid4()),
        "chat_id": chat_id,
        "sender_type": "agent",
        "sender_id": tg_id,
        "sender_name": agent_doc.get("display_name", "Agent"),
        "content": outgoing_content,
        "original_content": original_content if translations else None,
        "lang": msg_lang,
        "translations": translations,
        "image_url": None,
        "created_at": now.isoformat(),
    }
    await db.support_messages.insert_one(msg.copy())
    await db.support_chats.update_one({"id": chat_id}, {"$set": {"last_activity": now.isoformat()}, "$inc": {"messages_count": 1, "unread_for_user": 1}})

    # Notify user
    await ws_manager.send_to_user(chat["user_id"], {"type": "new_message", "chat_id": chat_id, "message": msg})
    # Notify OTHER agents (broadcast for shared awareness, e.g. unread counts).
    # We intentionally do NOT echo back to the sending agent — the REST
    # response already adds the message to their UI, and a WS echo causes
    # occasional double-render artefacts on slow networks.
    for other_tg in list(ws_manager.agent_conns.keys()):
        if other_tg != tg_id:
            await ws_manager.send_to_agent(other_tg, {"type": "new_message", "chat_id": chat_id, "message": msg})

    # Telegram notify user ALWAYS on agent reply — even when their WebApp is
    # open, the notification is what makes them re-open the bot in the first
    # place. WebSocket delivers the message live in the mini-app; the Telegram
    # push ensures the user sees the notification even after they close it.
    user_doc = await db.users.find_one({"id": chat["user_id"]}, {"_id": 0})
    if user_doc:
        try:
            _text, _kb = await _support_reply_markup_for_user(chat["user_id"])
        except Exception as e:
            logger.debug(f"support reply markup build failed: {e}")
            _text, _kb = f"💬 Агент {agent_doc.get('display_name', 'Agent')} ответил вам в чате поддержки!", None
        await _notify_telegram(user_doc, _text, reply_markup=_kb)

    return {"message": msg}


@support_agent_router.post("/chat/{chat_id}/upload")
async def agent_upload_image(chat_id: str, file: UploadFile = File(...), agent=Depends(require_support_agent)):
    """Agent uploads image."""
    tg_id = str(agent.get("telegram_chat_id") or agent.get("telegram_id") or "")
    chat = await db.support_chats.find_one({"id": chat_id}, {"_id": 0})
    if not chat:
        raise HTTPException(status_code=404, detail="Чат не найден")
    if chat["status"] == "archived":
        raise HTTPException(status_code=400, detail="Чат завершён")
    if chat.get("agent_tg_id") and chat["agent_tg_id"] != tg_id and not agent.get("is_admin"):
        raise HTTPException(status_code=403, detail="Forbidden")
    agent_doc = await _get_agent_by_tg(tg_id) or {}
    return await _handle_upload(chat_id, file, sender_type="agent", sender_id=tg_id, sender_name=agent_doc.get("display_name", "Agent"))


@support_agent_router.post("/chat/{chat_id}/close")
async def agent_close_chat(chat_id: str, agent=Depends(require_support_agent)):
    """Close chat → archived."""
    tg_id = str(agent.get("telegram_chat_id") or agent.get("telegram_id") or "")
    chat = await db.support_chats.find_one({"id": chat_id}, {"_id": 0})
    if not chat:
        raise HTTPException(status_code=404, detail="Чат не найден")
    if chat["status"] == "archived":
        return {"status": "already_archived"}
    if chat.get("agent_tg_id") and chat["agent_tg_id"] != tg_id and not agent.get("is_admin"):
        raise HTTPException(status_code=403, detail="Forbidden")

    now = datetime.now(timezone.utc)
    # Compute chat duration
    duration_sec = 0
    if chat.get("claimed_at"):
        try:
            claimed_dt = datetime.fromisoformat(str(chat["claimed_at"]).replace("Z", "+00:00"))
            if claimed_dt.tzinfo is None:
                claimed_dt = claimed_dt.replace(tzinfo=timezone.utc)
            duration_sec = (now - claimed_dt).total_seconds()
        except Exception:
            pass

    await db.support_chats.update_one(
        {"id": chat_id},
        {"$set": {"status": "archived", "closed_at": now.isoformat(), "unread_for_user": 0, "unread_for_agent": 0}},
    )

    # Increment agent stats
    if chat.get("agent_tg_id"):
        await db.support_agents.update_one(
            {"telegram_id": chat["agent_tg_id"]},
            {"$inc": {"total_chats_closed": 1, "duration_sum": duration_sec, "duration_count": 1}},
        )

    # System message
    sys_msg = _system_msg(chat_id, "chat_closed", "Чат завершён. Пожалуйста, оцените работу агента.")
    await db.support_messages.insert_one(sys_msg.copy())

    # Notify
    await ws_manager.send_to_user(chat["user_id"], {"type": "chat_closed", "chat_id": chat_id, "message": sys_msg})
    await ws_manager.broadcast_to_all_agents({"type": "chat_closed", "chat_id": chat_id})

    return {"status": "closed"}


@support_agent_router.get("/user-info/{user_id}")
async def agent_get_user_info(user_id: str, agent=Depends(require_support_agent)):
    """Get full user information (with access logging)."""
    tg_id = str(agent.get("telegram_chat_id") or agent.get("telegram_id") or "")

    user = await db.users.find_one({"id": user_id}, {"_id": 0, "hashed_password": 0, "two_factor_secret": 0, "backup_codes": 0})
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    # Log access
    await db.support_access_log.insert_one({
        "id": str(uuid.uuid4()),
        "agent_tg_id": tg_id,
        "agent_id": agent.get("id"),
        "viewed_user_id": user_id,
        "viewed_user_email": user.get("email"),
        "action": "info_view",
        "viewed_at": datetime.now(timezone.utc).isoformat(),
    })

    # Get businesses
    businesses = await db.businesses.find(
        {"$or": [{"owner": user_id}, {"owner": user.get("email")}, {"owner_wallet": user.get("wallet_address")}]},
        {"_id": 0, "id": 1, "business_type": 1, "level": 1, "durability": 1, "is_active": 1},
    ).to_list(200)

    # Get transactions
    transactions = await db.transactions.find(
        {"$or": [{"user_id": user_id}, {"user_wallet": user.get("wallet_address")}]},
        {"_id": 0},
    ).sort("created_at", -1).limit(50).to_list(50)

    return {
        "user": {
            "id": user.get("id"),
            "email": user.get("email"),
            "username": user.get("username"),
            "display_name": user.get("display_name"),
            "balance_ton": user.get("balance_ton", 0),
            "created_at": user.get("created_at"),
            "wallet_address": user.get("wallet_address"),
            "resources": user.get("resources", {}),
        },
        "businesses": businesses,
        "transactions": transactions,
    }


@support_agent_router.get("/operation/{op_id}")
async def agent_get_operation(op_id: str, agent=Depends(require_support_agent)):
    """Get operation/transaction details by id."""
    tg_id = str(agent.get("telegram_chat_id") or agent.get("telegram_id") or "")
    tx = await db.transactions.find_one({"id": op_id}, {"_id": 0})
    if not tx:
        raise HTTPException(status_code=404, detail="Операция не найдена")
    await db.support_access_log.insert_one({
        "id": str(uuid.uuid4()),
        "agent_tg_id": tg_id,
        "agent_id": agent.get("id"),
        "viewed_user_id": tx.get("user_id"),
        "action": "operation_view",
        "operation_id": op_id,
        "viewed_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"operation": tx}


# ─────────────────────── Support «Изъятые» (seized) ───────────────────────
# Full parity with the admin «Кредиты → Изъятые» panel for support staff.

@support_agent_router.get("/seized")
async def agent_list_seized(agent=Depends(require_support_agent)):
    from core.seizure import list_seized
    rows = await list_seized(db)
    return {"seized": rows, "count": len(rows)}


@support_agent_router.post("/seized/{listing_id}/price")
async def agent_set_seized_price(listing_id: str, data: dict, agent=Depends(require_support_agent)):
    from core.seizure import set_seized_price
    res = await set_seized_price(db, listing_id, float(data.get("price", 0)))
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("reason", "error"))
    await db.support_access_log.insert_one({
        "id": str(uuid.uuid4()), "agent_id": agent.get("id"),
        "action": "seized_price_edit", "listing_id": listing_id,
        "new_price": res.get("price"), "viewed_at": datetime.now(timezone.utc).isoformat(),
    })
    return res


@support_agent_router.post("/seized/{listing_id}/return")
async def agent_return_seized(listing_id: str, agent=Depends(require_support_agent)):
    from core.seizure import return_seized
    res = await return_seized(db, listing_id)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("reason", "error"))
    await db.support_access_log.insert_one({
        "id": str(uuid.uuid4()), "agent_id": agent.get("id"),
        "action": "seized_return", "listing_id": listing_id,
        "viewed_at": datetime.now(timezone.utc).isoformat(),
    })
    return res




@support_agent_router.post("/chat/{chat_id}/mark-read")
async def agent_mark_read(chat_id: str, agent=Depends(require_support_agent)):
    """Reset unread_for_agent counter."""
    res = await db.support_chats.update_one({"id": chat_id}, {"$set": {"unread_for_agent": 0}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"status": "ok"}


@support_agent_router.get("/chat/{chat_id}")
async def agent_get_chat(chat_id: str, agent=Depends(require_support_agent)):
    """View full chat (any status)."""
    chat = await db.support_chats.find_one({"id": chat_id}, {"_id": 0})
    if not chat:
        raise HTTPException(status_code=404, detail="Чат не найден")
    # Attach the user's project language so the agent panel can pre-select the
    # send-translation target automatically.
    user_doc = await db.users.find_one({"id": chat.get("user_id")}, {"_id": 0, "language": 1})
    chat["user_language"] = (user_doc or {}).get("language") or "en"
    msgs = await db.support_messages.find({"chat_id": chat_id}, {"_id": 0}).sort("created_at", 1).to_list(2000)
    return {"chat": chat, "messages": msgs}


@support_agent_router.post("/message/{message_id}/translate")
async def agent_translate_message(message_id: str, data: TranslateMessageRequest, agent=Depends(require_support_agent)):
    """Translate a support message into `target_lang` (default Russian).

    Translations are cached ON the message document (translations.<lang>) and
    shared across agents, so repeat requests for the same language never hit
    the translation provider again."""
    target = (data.target_lang or "ru").strip().lower()
    if target not in SUPPORT_LANGS:
        raise HTTPException(status_code=400, detail="Unsupported target language")

    msg = await db.support_messages.find_one({"id": message_id}, {"_id": 0})
    if not msg:
        raise HTTPException(status_code=404, detail="Сообщение не найдено")

    # Nothing to translate if the message is already in the target language.
    if (msg.get("lang") or "") == target:
        return {"message_id": message_id, "target_lang": target,
                "translation": msg.get("content", ""), "cached": True}

    cached = (msg.get("translations") or {}).get(target)
    if cached:
        return {"message_id": message_id, "target_lang": target,
                "translation": cached, "cached": True}

    from translation_service import translate_text as _translate
    translated = await _translate(msg.get("content", ""), target, source_lang="auto")
    await db.support_messages.update_one(
        {"id": message_id},
        {"$set": {f"translations.{target}": translated}},
    )
    return {"message_id": message_id, "target_lang": target,
            "translation": translated, "cached": False}


# ==================== ADMIN ENDPOINTS ====================

@support_admin_router.get("/agents")
async def admin_list_agents(admin=Depends(get_admin_user_dep)):
    """List agents with metrics."""
    agents = await db.support_agents.find({"is_removed": {"$ne": True}}, {"_id": 0}).to_list(200)
    enriched = []
    for ag in agents:
        tg_id = ag.get("telegram_id")
        active_count = await db.support_chats.count_documents({"agent_tg_id": tg_id, "status": "active"})
        rating_sum = ag.get("rating_sum", 0)
        rating_count = ag.get("rating_count", 0)
        avg_rating = round(rating_sum / rating_count, 2) if rating_count > 0 else 0
        resp_sum = ag.get("response_time_sum", 0)
        resp_count = ag.get("response_time_count", 0)
        avg_response = round(resp_sum / resp_count, 1) if resp_count > 0 else None
        dur_sum = ag.get("duration_sum", 0)
        dur_count = ag.get("duration_count", 0)
        avg_duration = round(dur_sum / dur_count, 1) if dur_count > 0 else None

        is_online = tg_id in ws_manager.agent_conns and len(ws_manager.agent_conns[tg_id]) > 0
        status = "offline"
        if is_online:
            status = "busy" if active_count >= MAX_AGENT_ACTIVE_CHATS else "online"

        enriched.append({
            **ag,
            "active_chats": active_count,
            "max_chats": MAX_AGENT_ACTIVE_CHATS,
            "avg_rating": avg_rating,
            "rating_count": rating_count,
            "rating_dist": ag.get("rating_dist", {}),
            "total_chats_closed": ag.get("total_chats_closed", 0),
            "avg_response_seconds": avg_response,
            "avg_duration_seconds": avg_duration,
            "status": status,
        })
    return {"agents": enriched}


@support_admin_router.post("/agents")
async def admin_add_agent(data: AddAgentRequest, admin=Depends(get_admin_user_dep)):
    """Add agent by telegram_id."""
    existing = await db.support_agents.find_one({"telegram_id": str(data.telegram_id)})
    if existing:
        # Reactivate if removed
        if existing.get("is_removed"):
            await db.support_agents.update_one(
                {"telegram_id": str(data.telegram_id)},
                {"$set": {"is_removed": False, "display_name": data.display_name, "avatar_url": data.avatar_url}},
            )
            return {"status": "reactivated"}
        raise HTTPException(status_code=400, detail="Agent already exists")

    agent = {
        "id": str(uuid.uuid4()),
        "telegram_id": str(data.telegram_id),
        "display_name": data.display_name,
        "avatar_url": data.avatar_url,
        "is_removed": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "rating_sum": 0,
        "rating_count": 0,
        "rating_dist": {},
        "total_chats_closed": 0,
        "response_time_sum": 0,
        "response_time_count": 0,
        "duration_sum": 0,
        "duration_count": 0,
    }
    await db.support_agents.insert_one(agent.copy())
    return {"status": "created", "agent": agent}


@support_admin_router.patch("/agents/{agent_id}")
async def admin_update_agent(agent_id: str, data: UpdateAgentRequest, admin=Depends(get_admin_user_dep)):
    """Update agent name/avatar."""
    update_fields = {}
    if data.display_name is not None:
        update_fields["display_name"] = data.display_name
    if data.avatar_url is not None:
        update_fields["avatar_url"] = data.avatar_url
    if not update_fields:
        return {"status": "noop"}
    result = await db.support_agents.update_one({"id": agent_id}, {"$set": update_fields})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "updated"}


@support_admin_router.delete("/agents/{agent_id}")
async def admin_remove_agent(agent_id: str, admin=Depends(get_admin_user_dep)):
    """Remove agent (soft-delete)."""
    result = await db.support_agents.update_one(
        {"id": agent_id},
        {"$set": {"is_removed": True}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "removed"}


@support_admin_router.post("/agents/{agent_id}/avatar")
async def admin_upload_agent_avatar(agent_id: str, file: UploadFile = File(...), admin=Depends(get_admin_user_dep)):
    """Upload agent avatar image."""
    ext = _resolve_image_extension(file)
    if not ext:
        raise HTTPException(
            status_code=400,
            detail="Поддерживаются только изображения (PNG / JPG / WEBP / HEIC / GIF)",
        )
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="Файл слишком большой (максимум 5MB)")
    import base64 as _b64
    url = f"data:{_ext_to_mime(ext)};base64,{_b64.b64encode(content).decode('ascii')}"
    await db.support_agents.update_one({"id": agent_id}, {"$set": {"avatar_url": url}})
    return {"avatar_url": url}


@support_admin_router.get("/agents/{agent_tg_id}/access-log")
async def admin_get_access_log(agent_tg_id: str, admin=Depends(get_admin_user_dep)):
    """View access log of an agent (anti-corruption)."""
    logs = await db.support_access_log.find({"agent_tg_id": agent_tg_id}, {"_id": 0}).sort("viewed_at", -1).limit(500).to_list(500)
    return {"logs": logs}


@support_admin_router.get("/agents/{agent_tg_id}/active-tickets")
async def admin_get_agent_active(agent_tg_id: str, admin=Depends(get_admin_user_dep)):
    chats = await db.support_chats.find({"agent_tg_id": agent_tg_id, "status": "active"}, {"_id": 0}).to_list(100)
    return {"chats": chats}


@support_admin_router.get("/agents/{agent_tg_id}/history")
async def admin_get_agent_history(agent_tg_id: str, admin=Depends(get_admin_user_dep)):
    chats = await db.support_chats.find({"agent_tg_id": agent_tg_id, "status": "archived"}, {"_id": 0}).sort("closed_at", -1).limit(200).to_list(200)
    return {"chats": chats}


@support_admin_router.get("/settings")
async def admin_get_settings(admin=Depends(get_admin_user_dep)):
    s = await _ensure_settings()
    return {
        "hidden_path": s.get("hidden_path", HIDDEN_PATH),
        "public_url": s.get("public_url", ""),
    }


class UpdateSupportSettingsRequest(BaseModel):
    public_url: Optional[str] = None


@support_admin_router.patch("/settings")
async def admin_update_settings(data: UpdateSupportSettingsRequest, admin=Depends(get_admin_user_dep)):
    """Admin can pin the public origin used by the bot when building agent
    login links. Empty string clears the override and the bot falls back to
    env vars / Telegram getWebhookInfo auto-detection."""
    updates = {}
    if data.public_url is not None:
        v = data.public_url.strip().rstrip("/")
        if v and not (v.startswith("http://") or v.startswith("https://")):
            raise HTTPException(status_code=400, detail="public_url must start with http(s)://")
        updates["public_url"] = v
    if not updates:
        return {"status": "noop"}
    await db.support_settings.update_one({"_id": "main"}, {"$set": updates}, upsert=True)
    return {"status": "updated", **updates}


# ==================== FILE SERVING ====================

@support_router.get("/files/{filename}")
async def serve_support_file(filename: str):
    """Serve support uploads (public for chat participants).

    F9 hardening: use `Path.name` (which strips all directory components) and
    verify the resolved path stays under UPLOAD_DIR to defend against symlink
    tricks and path traversal payloads. Also reject dotfiles and empty names.
    """
    # Strip any path separators / traversal segments — Path(...).name yields
    # only the final component (e.g. "../../etc/passwd" → "passwd").
    from pathlib import Path as _Path
    safe = _Path(filename).name
    if not safe or safe.startswith(".") or len(safe) > 255:
        raise HTTPException(status_code=400, detail="Invalid filename")
    upload_root = UPLOAD_DIR.resolve()
    candidate = (upload_root / safe).resolve()
    try:
        candidate.relative_to(upload_root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(str(candidate))


# ==================== UPLOAD HELPER ====================

def _resolve_image_extension(file: UploadFile) -> Optional[str]:
    """Pick a safe filesystem extension for an uploaded image.

    Order: content_type (if recognised) → filename extension (lowered).
    Returns None when neither yields a supported image format.
    """
    ct = (file.content_type or "").lower().strip()
    if ct in ALLOWED_IMAGE_TYPES:
        if "png" in ct:
            return "png"
        if "webp" in ct:
            return "webp"
        if "gif" in ct:
            return "gif"
        if "heic" in ct or "heif" in ct:
            # Keep original heic extension — frontend renders via <img> which
            # works for HEIC in modern Safari; other browsers will at least
            # offer download.
            return "heic" if "heic" in ct else "heif"
        return "jpg"  # default for jpeg variants
    # Fallback: trust filename extension
    name = (file.filename or "").lower()
    for ext in ALLOWED_IMAGE_EXT:
        if name.endswith(ext):
            return ext.lstrip(".")
    return None


def _ext_to_mime(ext: str) -> str:
    """Map a normalized image extension to its MIME type for data-URIs."""
    return {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "gif": "image/gif",
        "heic": "image/heic",
        "heif": "image/heif",
    }.get(ext, "image/png")


def _verify_image_magic_bytes(content: bytes, ext: str) -> bool:
    """F11: verify uploaded file starts with a real image magic-number so
    content_type / filename extension can't be spoofed to smuggle a script.

    Uses stdlib byte comparisons (no extra deps). Recognises PNG, JPEG, WEBP,
    GIF, HEIC/HEIF. Returns True when the payload matches the declared ext.
    """
    if len(content) < 12:
        return False
    head = content[:12]
    # PNG: 89 50 4E 47 0D 0A 1A 0A
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return ext in ("png",)
    # JPEG: FF D8 FF
    if head[:3] == b"\xff\xd8\xff":
        return ext in ("jpg", "jpeg")
    # GIF: GIF87a / GIF89a
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return ext == "gif"
    # WEBP: "RIFF" .... "WEBP"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ext == "webp"
    # HEIC/HEIF: bytes 4-8 == "ftyp", 8-12 in {heic, heix, hevc, mif1, msf1, heim, heis, hevm, hevs}
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"heic", b"heix", b"hevc", b"mif1", b"msf1", b"heim", b"heis", b"hevm", b"hevs", b"heif"):
            return ext in ("heic", "heif")
    return False


async def _handle_upload(chat_id: str, file: UploadFile, sender_type: str, sender_id: str, sender_name: str = None):
    ext = _resolve_image_extension(file)
    if not ext:
        raise HTTPException(
            status_code=400,
            detail="Поддерживаются только изображения (PNG / JPG / WEBP / HEIC / GIF)",
        )
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="Файл слишком большой (максимум 5MB)")
    # F11: magic-byte verification — reject if content doesn't match declared type.
    if not _verify_image_magic_bytes(content, ext):
        raise HTTPException(
            status_code=400,
            detail="Файл повреждён или не является изображением (проверка сигнатуры)",
        )
    import base64 as _b64
    url = f"data:{_ext_to_mime(ext)};base64,{_b64.b64encode(content).decode('ascii')}"
    now = datetime.now(timezone.utc)

    if not sender_name:
        if sender_type == "user":
            u = await db.users.find_one({"id": sender_id}, {"_id": 0, "username": 1, "display_name": 1})
            sender_name = (u.get("username") or u.get("display_name") or "User") if u else "User"
        else:
            a = await _get_agent_by_tg(sender_id)
            sender_name = (a.get("display_name") if a else "Agent")

    msg = {
        "id": str(uuid.uuid4()),
        "chat_id": chat_id,
        "sender_type": sender_type,
        "sender_id": sender_id,
        "sender_name": sender_name,
        "content": "",
        "image_url": url,
        "created_at": now.isoformat(),
    }
    await db.support_messages.insert_one(msg.copy())
    upload_update = {"$set": {"last_activity": now.isoformat()}, "$inc": {"messages_count": 1}}
    if sender_type == "user":
        upload_update["$set"]["user_last_activity"] = now.isoformat()
        upload_update["$inc"]["unread_for_agent"] = 1
    else:
        upload_update["$inc"]["unread_for_user"] = 1
    await db.support_chats.update_one({"id": chat_id}, upload_update)

    chat = await db.support_chats.find_one({"id": chat_id}, {"_id": 0})
    if chat:
        if sender_type == "user" and chat.get("agent_tg_id"):
            await ws_manager.send_to_agent(chat["agent_tg_id"], {"type": "new_message", "chat_id": chat_id, "message": msg})
        elif sender_type == "agent":
            await ws_manager.send_to_user(chat["user_id"], {"type": "new_message", "chat_id": chat_id, "message": msg})

    return {"message": msg}


# ==================== WEBSOCKET ENDPOINTS ====================

async def _ws_authenticate(token: str) -> Optional[dict]:
    """Decode JWT and return user-like dict.

    Accepts BOTH main project JWT (regular users + admin) and support agent JWT.
    For agent JWT, returns a dict with `_is_agent_only` marker and telegram_chat_id.
    """
    import jwt  # PyJWT (python-jose removed: unpatched CVE)
    from jwt import PyJWTError as JWTError
    from security_middleware import get_or_generate_jwt_secret
    secret = get_or_generate_jwt_secret()
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"], options={"verify_aud": False})
        # Support-agent JWT path
        if payload.get("aud") == "support_agent" and payload.get("agent_tg_id"):
            tg_id = str(payload["agent_tg_id"])
            agent_doc = await db.support_agents.find_one({"telegram_id": tg_id, "is_removed": {"$ne": True}}, {"_id": 0})
            if not agent_doc:
                return None
            if agent_doc.get("session_id") and payload.get("sid") and agent_doc["session_id"] != payload["sid"]:
                return None
            return {
                "id": agent_doc.get("id"),
                "telegram_chat_id": tg_id,
                "telegram_id": tg_id,
                "is_admin": False,
                "_is_agent_only": True,
            }
        # Main project JWT path (regular users)
        identifier = payload.get("sub")
        if not identifier:
            return None
        user = await db.users.find_one(
            {"$or": [{"wallet_address": identifier}, {"email": identifier}, {"username": identifier}, {"id": identifier}]},
            {"_id": 0},
        )
        return user
    except JWTError:
        return None


async def support_user_ws_handler(websocket: WebSocket, token: str, pre_accepted: bool = False):
    """User WebSocket: receives messages in real time."""
    from security.ws_rate_limit import check_ws_msg_rate, reset_ws_rate

    user = await _ws_authenticate(token)
    if not user:
        await websocket.close(code=4001)
        return
    user_id = user.get("id")
    await ws_manager.connect_user(websocket, user_id, accept=not pre_accepted)
    try:
        while True:
            data = await websocket.receive_json()
            # F36: per-user message rate-limit.
            if not check_ws_msg_rate(f"support_user:{user_id}"):
                try:
                    await websocket.send_json({"type": "error", "code": "rate_limited"})
                except Exception:
                    pass
                continue
            if data.get("action") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        ws_manager.disconnect_user(websocket, user_id)
        reset_ws_rate(f"support_user:{user_id}")
    except Exception:
        ws_manager.disconnect_user(websocket, user_id)
        reset_ws_rate(f"support_user:{user_id}")


async def support_agent_ws_handler(websocket: WebSocket, token: str, pre_accepted: bool = False):
    """Agent WebSocket."""
    from security.ws_rate_limit import check_ws_msg_rate, reset_ws_rate

    user = await _ws_authenticate(token)
    if not user:
        await websocket.close(code=4001)
        return
    if not await _is_user_agent_or_admin(user):
        await websocket.close(code=4003)
        return
    tg_id = str(user.get("telegram_chat_id") or user.get("telegram_id") or user.get("id"))
    await ws_manager.connect_agent(websocket, tg_id, accept=not pre_accepted)
    try:
        while True:
            data = await websocket.receive_json()
            # F36: per-agent message rate-limit.
            if not check_ws_msg_rate(f"support_agent:{tg_id}"):
                try:
                    await websocket.send_json({"type": "error", "code": "rate_limited"})
                except Exception:
                    pass
                continue
            if data.get("action") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        ws_manager.disconnect_agent(websocket, tg_id)
        reset_ws_rate(f"support_agent:{tg_id}")
    except Exception:
        ws_manager.disconnect_agent(websocket, tg_id)
        reset_ws_rate(f"support_agent:{tg_id}")


# ==================== BACKGROUND TASK: AUTO-RECLAIM INACTIVE ====================

async def auto_reclaim_inactive_chats():
    """If an agent is inactive on a claimed chat for AGENT_INACTIVITY_MINUTES, return chat to 'new'."""
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=AGENT_INACTIVITY_MINUTES)
        cutoff_iso = cutoff.isoformat()
        chats = await db.support_chats.find(
            {"status": "active", "last_activity": {"$lt": cutoff_iso}},
            {"_id": 0},
        ).to_list(100)
        for chat in chats:
            await db.support_chats.update_one(
                {"id": chat["id"]},
                {"$set": {"status": "new", "agent_id": None, "agent_tg_id": None, "agent_name": None, "claimed_at": None}},
            )
            sys = _system_msg(chat["id"], "agent_timeout", "Агент неактивен — чат возвращён в очередь")
            await db.support_messages.insert_one(sys.copy())
            await ws_manager.send_to_user(chat["user_id"], {"type": "agent_left", "chat_id": chat["id"]})
            await ws_manager.broadcast_to_all_agents({"type": "new_chat", "chat": {**chat, "status": "new"}})
            logger.info(f"Auto-reclaimed inactive chat {chat['id']}")
    except Exception as e:
        logger.error(f"auto_reclaim_inactive_chats error: {e}")


async def auto_close_user_inactive_chats():
    """Auto-close any active chat where the USER has not sent a message for
    USER_INACTIVITY_MINUTES. Inactivity is measured on the per-user field
    `user_last_activity` so an agent talking to themselves does NOT keep the
    chat open."""
    try:
        now = datetime.now(timezone.utc)
        cutoff_iso = (now - timedelta(minutes=USER_INACTIVITY_MINUTES)).isoformat()
        # Chats where the user hasn't been active long enough. We also accept
        # chats missing the field (legacy rows) and fall back to claimed_at /
        # created_at so they don't linger forever.
        chats = await db.support_chats.find(
            {
                "status": "active",
                "$or": [
                    {"user_last_activity": {"$lt": cutoff_iso}},
                    {"user_last_activity": {"$exists": False}, "last_activity": {"$lt": cutoff_iso}},
                ],
            },
            {"_id": 0},
        ).to_list(200)
        for chat in chats:
            duration_sec = 0
            if chat.get("claimed_at"):
                try:
                    claimed_dt = datetime.fromisoformat(str(chat["claimed_at"]).replace("Z", "+00:00"))
                    if claimed_dt.tzinfo is None:
                        claimed_dt = claimed_dt.replace(tzinfo=timezone.utc)
                    duration_sec = (now - claimed_dt).total_seconds()
                except Exception:
                    pass
            await db.support_chats.update_one(
                {"id": chat["id"]},
                {"$set": {
                    "status": "archived",
                    "closed_at": now.isoformat(),
                    "auto_closed_reason": "user_inactivity",
                    "unread_for_user": 0,
                    "unread_for_agent": 0,
                }},
            )
            if chat.get("agent_tg_id"):
                await db.support_agents.update_one(
                    {"telegram_id": chat["agent_tg_id"]},
                    {"$inc": {"total_chats_closed": 1, "duration_sum": duration_sec, "duration_count": 1}},
                )
            sys_msg = _system_msg(
                chat["id"],
                "user_timeout",
                f"Чат автоматически завершён: пользователь не активен более {USER_INACTIVITY_MINUTES} минут.",
            )
            await db.support_messages.insert_one(sys_msg.copy())
            await ws_manager.send_to_user(chat["user_id"], {"type": "chat_closed", "chat_id": chat["id"], "message": sys_msg})
            await ws_manager.broadcast_to_all_agents({"type": "chat_closed", "chat_id": chat["id"]})
            logger.info(f"Auto-closed user-inactive chat {chat['id']} (inactive > {USER_INACTIVITY_MINUTES}m)")
    except Exception as e:
        logger.error(f"auto_close_user_inactive_chats error: {e}")


async def cleanup_empty_chats():
    """P1.5: Delete any support chat that was created but never received a
    first user message (an "empty" chat). With the new flow the chat is only
    created when the user sends their first message, so going forward these
    should not appear — this routine removes any legacy/empty chats and their
    orphaned messages. Runs on startup."""
    try:
        empty = await db.support_chats.find(
            {
                "$or": [
                    {"first_msg_at": None},
                    {"first_msg_at": {"$exists": False}},
                ],
                # never had a user message
                "$and": [
                    {"$or": [{"messages_count": {"$lte": 0}}, {"messages_count": {"$exists": False}}]},
                ],
            },
            {"_id": 0, "id": 1},
        ).to_list(1000)
        if not empty:
            return 0
        ids = [c["id"] for c in empty if c.get("id")]
        if not ids:
            return 0
        await db.support_messages.delete_many({"chat_id": {"$in": ids}})
        res = await db.support_chats.delete_many({"id": {"$in": ids}})
        logger.info(f"cleanup_empty_chats: removed {res.deleted_count} empty support chats")
        return res.deleted_count
    except Exception as e:
        logger.error(f"cleanup_empty_chats error: {e}")
        return 0
