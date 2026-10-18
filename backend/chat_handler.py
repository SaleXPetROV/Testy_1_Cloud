"""
GRAM City Builder - Chat System
Global chat, city chat, and private messages
"""
from fastapi import APIRouter, HTTPException, Depends, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.security import HTTPBearer
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
import uuid
import json
import asyncio
import logging

logger = logging.getLogger(__name__)
from motor.motor_asyncio import AsyncIOMotorClient
import os

# Router
chat_router = APIRouter(prefix="/chat", tags=["Chat"])
from auth_cookie import CookieOrBearer
security = CookieOrBearer(auto_error=False)

# JWT Configuration (F1 security fix)
SECRET_KEY = os.environ.get('JWT_SECRET_KEY') or ''
if not SECRET_KEY:
    from security_middleware import get_or_generate_jwt_secret
    SECRET_KEY = get_or_generate_jwt_secret()
ALGORITHM = "HS256"

# MongoDB connection (will be set from main server)
db = None

def set_db(database):
    global db
    db = database


def _detect_lang(text: str):
    from translation_service import detect_language
    try:
        return detect_language(text)
    except Exception:
        return None


async def _enrich_messages(messages: list) -> list:
    """Backfill missing `lang` (via detection) and attach each sender's CURRENT
    avatar from the users collection so the chat shows real profile pictures.
    Detected languages are persisted so detection runs at most once per message.
    """
    if not messages:
        return messages

    # 1) Backfill missing language on old messages, and correct any clearly
    #    wrong stored lang when the script is unambiguous (e.g. Cyrillic text
    #    saved as "en" by an earlier version).
    from translation_service import script_language
    for m in messages:
        content = m.get("content", "")
        scripted = None
        try:
            scripted = script_language(content)
        except Exception:
            scripted = None
        new_lang = None
        if not m.get("lang"):
            new_lang = scripted or _detect_lang(content)
        elif scripted and scripted != m.get("lang"):
            new_lang = scripted
        if new_lang and new_lang != m.get("lang"):
            m["lang"] = new_lang
            try:
                await db.chat_messages.update_one({"id": m["id"]}, {"$set": {"lang": new_lang}})
            except Exception:
                pass

    # 2) Attach current sender avatars + CURRENT username (single batched
    #    lookup) so a user who renames themselves in Settings shows their
    #    latest name on every past chat message.
    sender_ids = list({m.get("sender_id") for m in messages if m.get("sender_id")})
    if sender_ids:
        info = {}
        async for u in db.users.find(
            {"id": {"$in": sender_ids}},
            {"_id": 0, "id": 1, "avatar": 1, "username": 1, "display_name": 1, "alliance_tag": 1},
        ):
            info[u["id"]] = u
        for m in messages:
            u = info.get(m.get("sender_id"))
            if not u:
                continue
            if u.get("avatar"):
                m["sender_avatar"] = u.get("avatar")
            name = u.get("username") or u.get("display_name")
            if name:
                m["sender_username"] = name
            m["sender_alliance_tag"] = u.get("alliance_tag") or None     # «[TAG] name»
    return messages


# ==================== MODELS ====================

class SendMessageRequest(BaseModel):
    # `content` is optional when `image_url` is provided — image-only
    # messages are supported. When BOTH are absent the endpoint rejects
    # the request.
    content: str = Field(default="", max_length=1000)
    chat_type: str = "global"  # global, city, private, alliance (the sender's alliance)
    city_id: Optional[str] = None
    recipient_id: Optional[str] = None
    # Optional image attachment. Accepts either a `data:image/*;base64,…`
    # URI produced by `POST /chat/upload-photo` OR a plain HTTPS URL of an
    # image already hosted elsewhere. Rendered borderless in the UI.
    image_url: Optional[str] = None


class TranslateRequest(BaseModel):
    message_id: str
    target_lang: str


# Supported project languages + English names used in the translation prompt.
CHAT_LANGS = {
    "ru": "Russian", "en": "English", "es": "Spanish", "zh": "Chinese (Simplified)",
    "fr": "French", "de": "German", "ja": "Japanese", "ko": "Korean", "id": "Indonesian",
}


async def translate_text(text: str, target_lang: str) -> str:
    """Translate `text` into `target_lang`. Returns ONLY the translated string.
    Delegates to the unified translation_service (LibreTranslate → Emergent LLM)."""
    from translation_service import translate_text as _translate
    return await _translate(text, target_lang)


class ChatMessage(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    content: str
    chat_type: str
    city_id: Optional[str] = None
    sender_id: str
    sender_username: str
    sender_avatar: Optional[str] = None
    recipient_id: Optional[str] = None
    recipient_username: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_read: bool = False


# ==================== WEBSOCKET CONNECTIONS ====================

class ConnectionManager:
    def __init__(self):
        # user_id -> WebSocket
        self.active_connections: Dict[str, WebSocket] = {}
        # city_id -> set of user_ids
        self.city_subscribers: Dict[str, set] = {}
        # All global chat subscribers
        self.global_subscribers: set = set()
    
    async def connect(self, websocket: WebSocket, user_id: str, accept: bool = True):
        if accept:
            await websocket.accept()
        self.active_connections[user_id] = websocket
        self.global_subscribers.add(user_id)
    
    def disconnect(self, user_id: str):
        if user_id in self.active_connections:
            del self.active_connections[user_id]
        self.global_subscribers.discard(user_id)
        # Remove from all city subscriptions
        for city_subs in self.city_subscribers.values():
            city_subs.discard(user_id)
    
    def subscribe_to_city(self, user_id: str, city_id: str):
        if city_id not in self.city_subscribers:
            self.city_subscribers[city_id] = set()
        self.city_subscribers[city_id].add(user_id)
    
    def unsubscribe_from_city(self, user_id: str, city_id: str):
        if city_id in self.city_subscribers:
            self.city_subscribers[city_id].discard(user_id)
    
    async def broadcast_global(self, message: dict):
        """Send message to all connected users"""
        for user_id in self.global_subscribers:
            if user_id in self.active_connections:
                try:
                    await self.active_connections[user_id].send_json(message)
                except Exception:
                    pass
    
    async def broadcast_city(self, city_id: str, message: dict):
        """Send message to users subscribed to a city"""
        if city_id not in self.city_subscribers:
            return
        for user_id in self.city_subscribers[city_id]:
            if user_id in self.active_connections:
                try:
                    await self.active_connections[user_id].send_json(message)
                except Exception:
                    pass
    
    async def send_private(self, user_id: str, message: dict):
        """Send private message to specific user"""
        if user_id in self.active_connections:
            try:
                await self.active_connections[user_id].send_json(message)
            except Exception:
                pass


manager = ConnectionManager()


# ==================== AUTH HELPER ====================

async def get_current_user_from_token(token: str):
    """Get user from JWT token"""
    import jwt
    from jwt import PyJWTError as JWTError
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        from core.token_revocation import is_revoked as _is_revoked
        if await _is_revoked(db, payload):          # revoked tokens can't open the chat socket either
            return None
        identifier = payload.get("sub")
        if not identifier:
            return None
        
        # Search by wallet_address, email, username (same as main server)
        user = await db.users.find_one({
            "$or": [
                {"wallet_address": identifier},
                {"email": identifier},
                {"username": identifier},
                {"id": identifier}
            ]
        }, {"_id": 0, "hashed_password": 0})
        
        return user
    except JWTError:
        return None


# ==================== REST ENDPOINTS ====================

@chat_router.get("/messages/global")
async def get_global_messages(limit: int = 50, before: str = None):
    """Get global chat messages"""
    query = {"chat_type": "global"}
    if before:
        query["created_at"] = {"$lt": before}
    
    messages = await db.chat_messages.find(
        query, {"_id": 0}
    ).sort("created_at", -1).limit(limit).to_list(limit)
    messages = list(reversed(messages))
    messages = await _enrich_messages(messages)
    return {"messages": messages, "total": len(messages)}


@chat_router.get("/messages/alliance")
async def get_alliance_messages(limit: int = 50, before: str = None, credentials = Depends(security)):
    """Messages of the player's alliance channel (members only)."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    current_user = await get_current_user_from_token(credentials.credentials)
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    am = await db.alliance_members.find_one({"user_id": current_user.get("id")}, {"_id": 0, "alliance_id": 1})
    if not am:
        return {"messages": [], "total": 0, "member": False}
    query = {"chat_type": "alliance", "alliance_id": am["alliance_id"]}
    if before:
        query["created_at"] = {"$lt": before}
    messages = await db.chat_messages.find(query, {"_id": 0}).sort("created_at", -1).limit(min(limit, 100)).to_list(min(limit, 100))
    messages = await _enrich_messages(list(reversed(messages)))
    return {"messages": messages, "total": len(messages), "member": True}


@chat_router.get("/messages/city/{city_id}")
async def get_city_messages(city_id: str, limit: int = 50, before: str = None):
    """Get city chat messages"""
    query = {"chat_type": "city", "city_id": city_id}
    if before:
        query["created_at"] = {"$lt": before}
    
    messages = await db.chat_messages.find(
        query, {"_id": 0}
    ).sort("created_at", -1).limit(limit).to_list(limit)
    messages = list(reversed(messages))
    messages = await _enrich_messages(messages)
    return {"messages": messages, "total": len(messages)}


@chat_router.get("/messages/private/{user_id}")
async def get_private_messages(
    user_id: str,
    limit: int = 50,
    before: str = None,
    credentials = Depends(security)
):
    """Get private messages with specific user"""
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    current_user = await get_current_user_from_token(credentials.credentials)
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    my_id = current_user.get("id")
    
    query = {
        "chat_type": "private",
        "$or": [
            {"sender_id": my_id, "recipient_id": user_id},
            {"sender_id": user_id, "recipient_id": my_id}
        ]
    }
    if before:
        # Support cursor pagination for infinite scroll (load older messages
        # in batches of `limit` as the user scrolls the private thread up).
        query["created_at"] = {"$lt": before}
    
    messages = await db.chat_messages.find(
        query, {"_id": 0}
    ).sort("created_at", -1).limit(limit).to_list(limit)
    
    # Mark as read (only on the FIRST page — `before` means we are scrolling
    # older, don't touch is_read for messages the user isn't actively viewing).
    if not before:
        await db.chat_messages.update_many(
            {"recipient_id": my_id, "sender_id": user_id, "is_read": False},
            {"$set": {"is_read": True}}
        )
    
    messages = list(reversed(messages))
    messages = await _enrich_messages(messages)
    return {"messages": messages, "total": len(messages)}


@chat_router.get("/conversations")
async def get_conversations(credentials = Depends(security)):
    """Get list of private conversations"""
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    current_user = await get_current_user_from_token(credentials.credentials)
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    my_id = current_user.get("id")
    
    # Get unique conversation partners
    pipeline = [
        {"$match": {
            "chat_type": "private",
            "$or": [{"sender_id": my_id}, {"recipient_id": my_id}]
        }},
        {"$sort": {"created_at": -1}},
        {"$group": {
            "_id": {
                "$cond": [
                    {"$eq": ["$sender_id", my_id]},
                    "$recipient_id",
                    "$sender_id"
                ]
            },
            "last_message": {"$first": "$$ROOT"},
            "unread_count": {
                "$sum": {
                    "$cond": [
                        {"$and": [
                            {"$eq": ["$recipient_id", my_id]},
                            {"$eq": ["$is_read", False]}
                        ]},
                        1, 0
                    ]
                }
            }
        }}
    ]
    
    result = await db.chat_messages.aggregate(pipeline).to_list(50)
    
    conversations = []
    for r in result:
        partner_id = r["_id"]
        partner = await db.users.find_one(
            {"id": partner_id},
            {"_id": 0, "username": 1, "avatar": 1}
        )
        conversations.append({
            "partner_id": partner_id,
            "partner_username": partner.get("username") if partner else "Unknown",
            "partner_avatar": partner.get("avatar") if partner else None,
            "last_message": r["last_message"],
            "unread_count": r["unread_count"]
        })
    
    return {"conversations": conversations}


@chat_router.post("/upload-photo")
async def upload_chat_photo(
    file: UploadFile = File(...),
    credentials = Depends(security),
):
    """Upload a chat photo (any authenticated user). Returns a data URI
    that the caller then passes as `image_url` in `POST /chat/send`.

    Mirrors the admin announcement uploader (server.py::admin_upload_announcement_image):
      • max 3 MB
      • only image/* content-types
      • magic-byte signature check (PNG / JPEG / GIF / WEBP)
    We store the image as a base64 `data:` URI so message rendering
    doesn't need a separate static-file server or CDN.
    """
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = await get_current_user_from_token(credentials.credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Rate-limit uploads with the same sliding-window limiter used for
    # `chat_send` so image-spam can't bypass the text-message limiter.
    from security.ws_rate_limit import check_ws_msg_rate
    if not check_ws_msg_rate(f"chat_upload:{user.get('id')}"):
        raise HTTPException(status_code=429, detail="Слишком много загрузок. Подождите немного.")

    import base64 as _b64
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty file")
    if len(data) > 3 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image must be ≤ 3 MB")
    ctype = (file.content_type or "image/png").lower()
    if not ctype.startswith("image/"):
        raise HTTPException(status_code=400, detail=f"Only image/* uploads are allowed (got {ctype})")
    head = data[:12]
    is_image = (
        head.startswith(b"\x89PNG\r\n\x1a\n")
        or head[:3] == b"\xff\xd8\xff"
        or head[:6] in (b"GIF87a", b"GIF89a")
        or (head[:4] == b"RIFF" and head[8:12] == b"WEBP")
    )
    if not is_image:
        raise HTTPException(
            status_code=400,
            detail="Файл не является изображением (проверка сигнатуры)",
        )
    b64 = _b64.b64encode(data).decode("ascii")
    return {"url": f"data:{ctype};base64,{b64}", "size": len(data), "content_type": ctype}


CHAT_COOLDOWN_SEC = 15                      # one message per player every 15 seconds


@chat_router.post("/send")
async def send_message(data: SendMessageRequest, credentials = Depends(security)):
    """Send a chat message"""
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    current_user = await get_current_user_from_token(credentials.credentials)
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # F40: per-user anti-spam rate limit on chat message creation (reuses the
    # in-memory sliding-window limiter, default 60/min via WS_MSG_LIMIT_PER_MIN).
    from security.ws_rate_limit import check_ws_msg_rate
    if not check_ws_msg_rate(f"chat_send:{current_user.get('id')}"):
        raise HTTPException(status_code=429, detail="Слишком много сообщений. Подождите немного.")

    # One message per 15 seconds per player (admins are not limited). Atomic: two quick requests can't both pass.
    if not current_user.get("is_admin"):
        from datetime import timedelta as _td
        _now = datetime.now(timezone.utc)
        _ok = await db.users.update_one(
            {"id": current_user.get("id"), "$or": [{"chat_last_sent_at": {"$exists": False}},
                                                   {"chat_last_sent_at": {"$lte": (_now - _td(seconds=CHAT_COOLDOWN_SEC)).isoformat()}}]},
            {"$set": {"chat_last_sent_at": _now.isoformat()}})
        if not _ok.modified_count:
            _u = await db.users.find_one({"id": current_user.get("id")}, {"_id": 0, "chat_last_sent_at": 1}) or {}
            try:
                _last = datetime.fromisoformat(str(_u.get("chat_last_sent_at")))
                _wait = max(1, int(CHAT_COOLDOWN_SEC - (_now - _last).total_seconds()) + 1)
            except Exception:
                _wait = CHAT_COOLDOWN_SEC
            raise HTTPException(status_code=429, detail={"code": "chat_cooldown", "wait": _wait})

    # F40: content moderation (word-blocklist, no external API). Blocks phishing/
    # scam lures outright, masks profanity, auto-mutes repeat offenders.
    from chat_moderation import moderate_message, is_muted
    _uid = current_user.get("id")
    _remaining = is_muted(_uid)
    if _remaining > 0:
        raise HTTPException(status_code=429, detail=f"Вы заглушены в чате. Осталось ~{int(_remaining)} сек.")
    # `content` and `image_url` are BOTH allowed to be present; at least
    # one must be non-empty. Text moderation only runs when there IS text.
    _has_text = bool((data.content or "").strip())
    _has_image = bool((data.image_url or "").strip())
    if not _has_text and not _has_image:
        raise HTTPException(status_code=400, detail="Message is empty")
    if _has_text:
        _mod = moderate_message(data.content, _uid)
        if not _mod["allowed"]:
            raise HTTPException(status_code=400, detail=_mod["reason"])
        data.content = _mod["content"]
    else:
        data.content = ""

    # Validate image_url shape when present. We accept a `data:image/*;base64,…`
    # URI produced by our own /chat/upload-photo endpoint OR any HTTPS URL.
    # Anything else (http://, javascript:, file://, …) is rejected up-front.
    if _has_image:
        _iu = data.image_url.strip()
        if not (_iu.startswith("data:image/") or _iu.startswith("https://")):
            raise HTTPException(status_code=400, detail="image_url must be a data:image/... URI or https:// URL")
        # Cap the size of data-URI attachments so we never insert megabytes
        # into MongoDB (the /chat/upload-photo endpoint already enforces
        # this, but we double-check for clients that skip it).
        if _iu.startswith("data:image/") and len(_iu) > 4 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Image is too large (max ~3 MB)")
        data.image_url = _iu

    # Validate chat type
    if data.chat_type == "city" and not data.city_id:
        raise HTTPException(status_code=400, detail="city_id required for city chat")
    
    if data.chat_type == "private" and not data.recipient_id:
        raise HTTPException(status_code=400, detail="recipient_id required for private chat")

    _alliance_id = None
    if data.chat_type == "alliance":
        _am = await db.alliance_members.find_one({"user_id": current_user.get("id")}, {"_id": 0, "alliance_id": 1})
        if not _am:
            raise HTTPException(status_code=403, detail={"code": "not_member"})
        _alliance_id = _am["alliance_id"]
    
    # Create message
    message = {
        "id": str(uuid.uuid4()),
        "content": data.content,
        "image_url": data.image_url,
        "chat_type": data.chat_type,
        "city_id": data.city_id,
        "sender_id": current_user.get("id"),
        "sender_username": current_user.get("username", "Anonymous"),
        "sender_avatar": current_user.get("avatar"),
        "recipient_id": data.recipient_id,
        "alliance_id": _alliance_id,
        "sender_alliance_tag": current_user.get("alliance_tag"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "is_read": False,
        # Author's project language — used to decide whether to show the
        # per-message "translate" button to other users. We detect the actual
        # language of the text (more accurate than the sender's UI language),
        # falling back to the sender's project language. Image-only messages
        # store the sender's UI language directly (nothing to detect).
        "lang": (
            (_detect_lang(data.content) if data.content else None)
            or current_user.get("language")
            or "en"
        ),
        # Shared translation cache: { "<lang>": "<translated text>" }.
        "translations": {},
    }
    
    # Get recipient username for private messages
    if data.chat_type == "private" and data.recipient_id:
        recipient = await db.users.find_one({"id": data.recipient_id}, {"username": 1})
        message["recipient_username"] = recipient.get("username") if recipient else None
    
    # Save to database
    await db.chat_messages.insert_one(message.copy())
    
    # Broadcast via WebSocket
    ws_message = {
        "type": "new_message",
        "message": message
    }
    
    if data.chat_type == "global":
        await manager.broadcast_global(ws_message)
    elif data.chat_type == "city":
        await manager.broadcast_city(data.city_id, ws_message)
    elif data.chat_type == "alliance":
        _ids = [m["user_id"] async for m in db.alliance_members.find({"alliance_id": _alliance_id}, {"_id": 0, "user_id": 1})]
        for _mid in _ids:
            await manager.send_private(_mid, ws_message)
    elif data.chat_type == "private":
        # Send to recipient
        await manager.send_private(data.recipient_id, ws_message)
        # Send back to sender (confirmation)
        await manager.send_private(current_user.get("id"), ws_message)
    
    return {"status": "sent", "message": message}


@chat_router.post("/translate")
async def translate_message(data: TranslateRequest, credentials = Depends(security)):
    """Translate a chat message into the requested language.

    Translations are cached ON the message document (shared by all users), so
    once anyone translates a message into a given language, every later request
    for that same language is served from the DB — no new LLM call."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    current_user = await get_current_user_from_token(credentials.credentials)
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if data.target_lang not in CHAT_LANGS:
        raise HTTPException(status_code=400, detail="Unsupported target language")

    # Light anti-abuse rate limit (shares the chat sliding-window limiter).
    from security.ws_rate_limit import check_ws_msg_rate
    if not check_ws_msg_rate(f"chat_translate:{current_user.get('id')}"):
        raise HTTPException(status_code=429, detail="Too many translation requests. Please wait.")

    msg = await db.chat_messages.find_one({"id": data.message_id}, {"_id": 0})
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    # closed channels: only their members may read (and so translate) a message
    if msg.get("chat_type") == "alliance":
        _am = await db.alliance_members.find_one({"user_id": current_user.get("id")}, {"_id": 0, "alliance_id": 1})
        if not _am or _am.get("alliance_id") != msg.get("alliance_id"):
            raise HTTPException(status_code=404, detail="Message not found")
    elif msg.get("chat_type") == "private" and current_user.get("id") not in (msg.get("sender_id"), msg.get("recipient_id")):
        raise HTTPException(status_code=404, detail="Message not found")

    # Same language → nothing to translate.
    if (msg.get("lang") or "") == data.target_lang:
        return {"message_id": data.message_id, "target_lang": data.target_lang,
                "translation": msg.get("content", ""), "cached": True}

    # Cache hit (shared across users).
    translations = msg.get("translations") or {}
    cached = translations.get(data.target_lang)
    if cached:
        return {"message_id": data.message_id, "target_lang": data.target_lang,
                "translation": cached, "cached": True}

    # Cache miss → translate once, then persist for everyone.
    try:
        translated = await translate_text(msg.get("content", ""), data.target_lang)
    except Exception as e:                        # no translator reachable (LibreTranslate / LLM) — not a server crash
        logger.warning(f"chat translate failed: {e}")
        raise HTTPException(status_code=503, detail={"code": "translation_unavailable"})
    if not translated:
        raise HTTPException(status_code=503, detail={"code": "translation_unavailable"})
    await db.chat_messages.update_one(
        {"id": data.message_id},
        {"$set": {f"translations.{data.target_lang}": translated}},
    )
    return {"message_id": data.message_id, "target_lang": data.target_lang,
            "translation": translated, "cached": False}


@chat_router.get("/unread-count")
async def get_unread_count(credentials = Depends(security)):
    """Total unread message count = unread PRIVATE messages + unread GLOBAL
    messages (global counted as messages from other users posted after the
    user last opened the global chat)."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    current_user = await get_current_user_from_token(credentials.credentials)
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    my_id = current_user.get("id")

    private_count = await db.chat_messages.count_documents({
        "recipient_id": my_id,
        "is_read": False
    })

    # Global unread: messages from OTHERS created after the user's last read of
    # the global channel. First-time default = account creation time so we don't
    # dump the entire history as "unread".
    # NOTE: chat message `created_at` is stored as an ISO STRING. The user's
    # `created_at` may be a BSON Date (seeded users) — comparing a string field
    # against a Date always fails in Mongo (types sort separately), which made
    # the count silently 0. Coerce the cursor to an ISO string so the $gt
    # comparison is string-vs-string.
    last_read = current_user.get("chat_read_global_at") or current_user.get("created_at") or ""
    if hasattr(last_read, "isoformat"):
        last_read = last_read.isoformat()
    elif not isinstance(last_read, str):
        last_read = str(last_read)
    global_query = {"chat_type": "global", "sender_id": {"$ne": my_id}}
    if last_read:
        global_query["created_at"] = {"$gt": last_read}
    global_count = await db.chat_messages.count_documents(global_query)

    alliance_count = 0
    am = await db.alliance_members.find_one({"user_id": my_id}, {"_id": 0, "alliance_id": 1, "joined_at": 1})
    if am:
        a_read = current_user.get("chat_read_alliance_at") or am.get("joined_at") or ""
        aq = {"chat_type": "alliance", "alliance_id": am["alliance_id"], "sender_id": {"$ne": my_id}}
        if a_read:
            aq["created_at"] = {"$gt": str(a_read)}
        alliance_count = await db.chat_messages.count_documents(aq)

    return {
        "unread_count": private_count + global_count + alliance_count,
        "private_unread": private_count,
        "global_unread": global_count,
        "alliance_unread": alliance_count,
    }


class MarkReadRequest(BaseModel):
    chat_type: str = "global"
    city_id: Optional[str] = None


@chat_router.post("/mark-read")
async def mark_chat_read(data: MarkReadRequest, credentials = Depends(security)):
    """Mark a channel as read for the current user (moves their read-cursor to
    now). Used by the global/city tabs so the unread badge drops to 0 the moment
    the user opens/looks at that channel."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    current_user = await get_current_user_from_token(credentials.credentials)
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    my_id = current_user.get("id")
    now_iso = datetime.now(timezone.utc).isoformat()
    if data.chat_type == "city" and data.city_id:
        await db.users.update_one({"id": my_id}, {"$set": {f"chat_read_city_at.{data.city_id}": now_iso}})
    elif data.chat_type == "alliance":
        await db.users.update_one({"id": my_id}, {"$set": {"chat_read_alliance_at": now_iso}})
    else:
        await db.users.update_one({"id": my_id}, {"$set": {"chat_read_global_at": now_iso}})
    return {"ok": True, "at": now_iso}


# ==================== WEBSOCKET ENDPOINT ====================

async def chat_websocket_handler(websocket: WebSocket, token: str, pre_accepted: bool = False):
    """WebSocket handler for real-time chat"""
    from security.ws_rate_limit import check_ws_msg_rate, reset_ws_rate

    user = await get_current_user_from_token(token)
    if not user:
        await websocket.close(code=4001, reason="Invalid token")
        return
    
    user_id = user.get("id")
    await manager.connect(websocket, user_id, accept=not pre_accepted)
    
    try:
        while True:
            data = await websocket.receive_json()

            # F36: per-user message rate-limit. Silently drops excess frames
            # to protect against a compromised client flooding the socket.
            if not check_ws_msg_rate(f"chat:{user_id}"):
                try:
                    await websocket.send_json({"type": "error", "code": "rate_limited"})
                except Exception:
                    pass
                continue

            # Handle subscription to city chat
            if data.get("action") == "subscribe_city":
                city_id = data.get("city_id")
                if city_id:
                    manager.subscribe_to_city(user_id, city_id)
                    await websocket.send_json({
                        "type": "subscribed",
                        "city_id": city_id
                    })
            
            elif data.get("action") == "unsubscribe_city":
                city_id = data.get("city_id")
                if city_id:
                    manager.unsubscribe_from_city(user_id, city_id)
                    await websocket.send_json({
                        "type": "unsubscribed",
                        "city_id": city_id
                    })
            
            # Ping/pong for keepalive
            elif data.get("action") == "ping":
                await websocket.send_json({"type": "pong"})
                
    except WebSocketDisconnect:
        manager.disconnect(user_id)
        reset_ws_rate(f"chat:{user_id}")
    except Exception as e:
        manager.disconnect(user_id)
        reset_ws_rate(f"chat:{user_id}")
