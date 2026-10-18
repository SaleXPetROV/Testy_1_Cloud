"""Telegram Login Link — universal, domain-free "Login with Telegram" flow
for regular browsers (desktop AND mobile).

Flow
----
1. Browser  →  POST /api/auth/telegram/login-link/start
              ← { deeplink: "https://t.me/<bot>?start=login_<jti>",
                  jti, expires_in }
              (server stores a `pending` record in `tg_login_links`)

2. User taps the deeplink → Telegram opens the bot → bot handles /start with
   payload `login_<jti>`; sees the pending record; verifies the tap comes from
   an actual Telegram user; upserts the site user (find-or-create by
   telegram_id); mints a JWT; stores it on the login-link record with
   status="confirmed"; replies "Готово, вернитесь в браузер".

3. Browser polls GET /api/auth/telegram/login-link/status/{jti} every 2 s
   until status=="confirmed", then saves the token → logged in.

No @BotFather /setdomain, no widget popup, no `REACT_APP_TELEGRAM_BOT_ID`
required. The only ops requirement is that the Telegram bot's webhook points
at this backend (which is already handled by `server.on_event("startup")`).
"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from core.dependencies import get_current_user

logger = logging.getLogger(__name__)

# TTL for a login link — long enough to type on mobile, short enough to keep
# the pending window small.
LINK_TTL_SECONDS = 5 * 60


class StartResponse(BaseModel):
    ok: bool
    jti: str
    deeplink: str
    expires_in: int
    bot_username: str


async def _get_bot_username() -> Optional[str]:
    """Return the @-less username of the bot behind TELEGRAM_BOT_TOKEN.
    Cached in the module for the process lifetime; env override supported."""
    env_uname = (os.environ.get("TELEGRAM_BOT_USERNAME") or "").lstrip("@").strip()
    if env_uname:
        return env_uname
    if getattr(_get_bot_username, "_cache", None):
        return _get_bot_username._cache  # type: ignore[attr-defined]
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        return None
    import aiohttp
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"https://api.telegram.org/bot{token}/getMe",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                data = await r.json()
        if not data.get("ok"):
            return None
        uname = (data.get("result") or {}).get("username")
        if uname:
            _get_bot_username._cache = uname  # type: ignore[attr-defined]
        return uname
    except Exception as e:
        logger.warning("[tg_login_link] getMe failed: %s", e)
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_telegram_login_link_router(db) -> APIRouter:
    router = APIRouter(prefix="/api/auth/telegram", tags=["telegram-auth"])

    @router.post("/login-link/start", response_model=StartResponse)
    async def start_login_link():
        bot_username = await _get_bot_username()
        if not bot_username:
            raise HTTPException(
                status_code=503,
                detail="Telegram bot not configured on the server",
            )
        jti = secrets.token_urlsafe(24)
        await db.tg_login_links.insert_one({
            "_id": jti,
            "status": "pending",
            "created_at": _now(),
            "expires_at": _now() + timedelta(seconds=LINK_TTL_SECONDS),
            "token": None,
            "user_id": None,
        })
        # Best-effort TTL index (idempotent).
        try:
            await db.tg_login_links.create_index("expires_at", expireAfterSeconds=0)
        except Exception:
            pass
        deeplink = f"https://t.me/{bot_username}?start=login_{jti}"
        return StartResponse(
            ok=True,
            jti=jti,
            deeplink=deeplink,
            expires_in=LINK_TTL_SECONDS,
            bot_username=bot_username,
        )

    @router.get("/login-link/status/{jti}")
    async def status_login_link(jti: str):
        doc = await db.tg_login_links.find_one({"_id": jti})
        if not doc:
            return {"status": "not_found"}
        exp = doc.get("expires_at")
        if isinstance(exp, datetime):
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if _now() > exp and doc.get("status") not in ("confirmed", "choice_required"):
                return {"status": "expired"}
        if doc.get("status") == "choice_required":
            # Telegram identity is not linked yet — the browser must show the
            # create/link choice. We keep the record until the user decides.
            return {
                "status": "choice_required",
                "jti": jti,
                "telegram": {
                    "id": doc.get("tg_user_id"),
                    "username": doc.get("tg_username"),
                    "first_name": doc.get("tg_first_name"),
                },
            }
        if doc.get("status") == "confirmed" and doc.get("token"):
            # One-shot: purge after handing out the token.
            token = doc["token"]
            user = doc.get("user_public") or {"id": doc.get("user_id")}
            is_new_signup = bool(doc.get("is_new_signup"))
            await db.tg_login_links.delete_one({"_id": jti})
            return {"status": "confirmed", "token": token, "user": user, "is_new_signup": is_new_signup}
        return {"status": doc.get("status", "pending")}

    @router.post("/login-link/create/{jti}")
    async def create_from_login_link(jti: str):
        """User chose "Create new account" for the Telegram identity captured
        by this login link. Creates the passwordless account and returns a JWT.
        """
        import uuid
        from pymongo.errors import DuplicateKeyError
        from routes.telegram_auth import (
            _find_user_by_telegram, _avatar_for, _now_iso, _public_user, _issue_token_for,
        )
        doc = await db.tg_login_links.find_one({"_id": jti})
        if not doc or doc.get("status") != "choice_required":
            raise HTTPException(status_code=400, detail="Invalid or expired login link")
        tg_user_id = str(doc.get("tg_user_id") or "")
        tg_username = doc.get("tg_username")
        tg_first_name = doc.get("tg_first_name")
        tg_last_name = doc.get("tg_last_name")
        if not tg_user_id:
            raise HTTPException(status_code=400, detail="Telegram identity missing")
        try:
            telegram_id_int = int(tg_user_id)
        except (TypeError, ValueError):
            telegram_id_int = None

        existing = await _find_user_by_telegram(db, tg_user_id, tg_username)
        if existing:
            user = existing
            is_new = False
        else:
            base_name = tg_username or (tg_first_name or f"tg{tg_user_id[-6:]}")
            username = base_name if not await db.users.find_one({"username": base_name}) else f"{base_name}_{tg_user_id[-4:]}"
            display_name = ((tg_first_name or "") + " " + (tg_last_name or "")).strip() or tg_first_name or username
            user = {
                "id": str(uuid.uuid4()),
                "username": username,
                "display_name": display_name,
                "email": None,
                "hashed_password": None,
                "wallet_address": None,
                "raw_address": None,
                "avatar": _avatar_for(display_name),
                "balance_ton": 0.0,
                "language": "en",
                "level": "novice",
                "xp": 0,
                "total_turnover": 0,
                "total_income": 0,
                "resources": {},
                "plots_owned": [],
                "businesses_owned": [],
                "is_admin": False,
                "email_verified": False,
                "agreement_accepted": True,
                "registration_method": "telegram",
                "telegram_id": telegram_id_int if telegram_id_int is not None else tg_user_id,
                "telegram_user_id": tg_user_id,
                "telegram_chat_id": tg_user_id,
                "telegram_username": tg_username,
                "tg_username": tg_username,
                "tg_first_name": tg_first_name,
                "tg_last_name": tg_last_name,
                "telegram_verified": True,
                "telegram_notifications": True,
                "telegram_auth_verified_at": _now_iso(),
                "login_methods": ["telegram"],
                "last_seen_at": _now_iso(),
                "created_at": _now(),
                "last_login": _now(),
            }
            try:
                await db.users.insert_one(user)
                is_new = True
            except DuplicateKeyError:
                user = await _find_user_by_telegram(db, tg_user_id, tg_username)
                is_new = False
                if not user:
                    raise HTTPException(status_code=409, detail="Concurrent signup conflict")

        token = await _issue_token_for(db, user)
        await db.tg_login_links.delete_one({"_id": jti})
        return {"status": "confirmed", "token": token, "user": _public_user(user), "is_new_signup": is_new}

    @router.post("/login-link/link/{jti}")
    async def link_from_login_link(jti: str, current_user=Depends(get_current_user)):
        """User chose "Link to existing account": after logging in with their
        existing method, the browser calls this with their Bearer token to
        attach the Telegram identity captured by the login link."""
        from routes.telegram_auth import _find_user_by_telegram, _now_iso, _public_user, _issue_token_for
        doc = await db.tg_login_links.find_one({"_id": jti})
        if not doc or doc.get("status") != "choice_required":
            raise HTTPException(status_code=400, detail="Invalid or expired login link")
        tg_user_id = str(doc.get("tg_user_id") or "")
        tg_username = doc.get("tg_username")
        if not tg_user_id:
            raise HTTPException(status_code=400, detail="Telegram identity missing")
        try:
            telegram_id_int = int(tg_user_id)
        except (TypeError, ValueError):
            telegram_id_int = None

        # Refuse if this Telegram is already linked to a DIFFERENT account.
        other = await _find_user_by_telegram(db, tg_user_id, tg_username)
        uid = current_user.get("id") if isinstance(current_user, dict) else getattr(current_user, "id", None)
        if other and other.get("id") != uid:
            raise HTTPException(status_code=409, detail="Telegram already linked to another account")

        was_already_linked = tg_user_id in {
            str(current_user.get("telegram_id") or "") if isinstance(current_user, dict) else str(getattr(current_user, "telegram_id", "") or ""),
            str(current_user.get("telegram_user_id") or "") if isinstance(current_user, dict) else str(getattr(current_user, "telegram_user_id", "") or ""),
        }
        await db.users.update_one(
            {"id": uid},
            {"$set": {
                "telegram_id": telegram_id_int if telegram_id_int is not None else tg_user_id,
                "telegram_user_id": tg_user_id,
                "telegram_chat_id": tg_user_id,
                "telegram_username": tg_username,
                "tg_username": tg_username,
                "tg_first_name": doc.get("tg_first_name"),
                "telegram_verified": True,
                "telegram_notifications": True,
                "telegram_auth_verified_at": _now_iso(),
            }},
        )
        await db.tg_login_links.delete_one({"_id": jti})
        if not was_already_linked:
            try:
                from routes.telegram_notifications import notify_link_event as _notify
                import asyncio as _asyncio
                _asyncio.create_task(_notify(db, tg_user_id, "linked"))
            except Exception:
                pass
        return {"linked": True, "telegram_id": tg_user_id}

    return router


# ---------------------------------------------------------------------------
# Bot-side helper: consume a `login_<jti>` deep-link payload during /start.
# Called from telegram_bot.cmd_start when args[0].startswith("login_").
# ---------------------------------------------------------------------------
async def confirm_login_link(
    db,
    payload: str,
    tg_user_id: str,
    tg_username: Optional[str],
    tg_first_name: Optional[str],
    tg_last_name: Optional[str] = None,
) -> dict:
    """Return {ok, message} for the bot to reply with; if ok, the linked
    site user is now marked as logged-in on the login-link record."""
    from routes.telegram_notifications import tmsg as _tmsg, resolve_bot_language as _resolve_lang

    _lang = await _resolve_lang(db, str(tg_user_id))
    if not payload or not payload.startswith("login_"):
        return {"ok": False, "message": _tmsg("login_link_invalid", _lang)}
    jti = payload[len("login_"):]
    if not jti:
        return {"ok": False, "message": _tmsg("login_link_invalid", _lang)}

    doc = await db.tg_login_links.find_one({"_id": jti})
    if not doc:
        return {"ok": False, "message": _tmsg("login_link_invalid", _lang)}
    exp = doc.get("expires_at")
    if isinstance(exp, datetime):
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if _now() > exp:
            return {"ok": False, "message": _tmsg("login_link_expired", _lang)}
    if doc.get("status") == "confirmed":
        return {"ok": True, "message": _tmsg("login_link_used", _lang)}

    # Find or create the site user tied to this Telegram id (same code path as
    # /api/auth/telegram/miniapp, kept here to avoid a circular import).
    from pymongo.errors import DuplicateKeyError
    from routes.telegram_auth import (
        _find_user_by_telegram, _avatar_for, _now_iso, _public_user, _issue_token_for,
    )
    import uuid

    telegram_id_int: Optional[int]
    try:
        telegram_id_int = int(tg_user_id)
    except (TypeError, ValueError):
        telegram_id_int = None

    user = await _find_user_by_telegram(db, str(tg_user_id), tg_username)
    if not user:
        # NEW POLICY: never silently auto-create here. If this Telegram id is
        # not linked to any account, hand control back to the browser/app so
        # the user can CHOOSE to create a new account or link this Telegram to
        # an existing one (same UX as the Mini App choice modal).
        await db.tg_login_links.update_one(
            {"_id": jti},
            {"$set": {
                "status": "choice_required",
                "tg_user_id": str(tg_user_id),
                "tg_username": tg_username,
                "tg_first_name": tg_first_name,
                "tg_last_name": tg_last_name,
                "choice_at": _now(),
            }},
        )
        logger.info("[tg_login_link] choice_required jti=%s tg=%s", jti, tg_user_id)
        return {"ok": True, "message": _tmsg("login_choose", _lang)}

    # Existing account for this Telegram id → confirm + issue token.
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {
            "telegram_id": telegram_id_int if telegram_id_int is not None else str(tg_user_id),
            "telegram_user_id": str(tg_user_id),
            "telegram_chat_id": user.get("telegram_chat_id") or str(tg_user_id),
            "telegram_username": tg_username or user.get("telegram_username"),
            "tg_username": tg_username or user.get("tg_username"),
            "tg_first_name": tg_first_name or user.get("tg_first_name"),
            "tg_last_name": tg_last_name or user.get("tg_last_name"),
            "telegram_verified": True,
            "telegram_auth_verified_at": _now_iso(),
            "last_seen_at": _now_iso(),
        }},
    )
    user = await db.users.find_one({"id": user["id"]})
    is_new = False

    # Mint the JWT and stash it on the login-link record for the browser poller.
    jwt_token = await _issue_token_for(db, user)
    await db.tg_login_links.update_one(
        {"_id": jti},
        {"$set": {
            "status": "confirmed",
            "token": jwt_token,
            "user_id": user["id"],
            "user_public": _public_user(user),
            "is_new_signup": is_new,
            "confirmed_at": _now(),
        }},
    )
    logger.info(
        "[tg_login_link] confirmed jti=%s user=%s new=%s tg=%s",
        jti, user["id"], is_new, tg_user_id,
    )
    # Re-resolve language now that the user doc is up-to-date (site language
    # may serve as a fallback for users who haven't touched the bot menu).
    try:
        _lang_final = await _resolve_lang(db, str(tg_user_id))
    except Exception:
        _lang_final = _lang
    return {
        "ok": True,
        "message": _tmsg("login_new" if is_new else "login_existing", _lang_final),
    }
