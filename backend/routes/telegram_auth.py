"""Telegram authentication — Mini App seamless auto-login, Login Widget (web),
unlink, and step-up. Complements the existing account-linking deep-link flow
(server.generate_telegram_link_token + telegram_bot.process_link_token).

All identity validation is HMAC-SHA256 against TELEGRAM_BOT_TOKEN:
  • Mini App initData → verify_telegram_init_data (auth_handler)
  • Login Widget      → _verify_login_widget (this module)
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
import jwt  # PyJWT (python-jose: unpatched CVEs and not in requirements)
from jwt import PyJWTError as JWTError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth/telegram", tags=["telegram-auth"])


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class MiniAppLogin(BaseModel):
    init_data: str


class WidgetLogin(BaseModel):
    # Raw fields returned by the Telegram Login Widget callback.
    data: Dict[str, Any]


class StepUpRequest(BaseModel):
    init_data: str


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _bot_token() -> str:
    return (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _verify_login_widget(data: Dict[str, Any], bot_token: str) -> Optional[Dict[str, Any]]:
    """Validate Telegram Login Widget payload.

    secret_key = SHA256(bot_token); data_check_string = sorted "k=v" (excluding
    `hash`) joined by \n; compare HMAC-SHA256.
    Ref: https://core.telegram.org/widgets/login#checking-authorization
    """
    if not data or not bot_token:
        return None
    received_hash = str(data.get("hash") or "")
    if not received_hash:
        return None
    pairs = {k: v for k, v in data.items() if k != "hash" and v is not None}
    data_check = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs.keys()))
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    calc = hmac.new(secret_key, data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received_hash):
        return None
    # Freshness: 24h
    try:
        auth_date = int(data.get("auth_date") or 0)
    except (ValueError, TypeError):
        auth_date = 0
    if not auth_date or (int(time.time()) - auth_date) > 24 * 3600:
        return None
    return {
        "id": data.get("id"),
        "username": data.get("username"),
        "first_name": data.get("first_name"),
        "last_name": data.get("last_name"),
        "photo_url": data.get("photo_url"),
    }


def _avatar_for(name: str) -> dict:
    initials = "".join([w[0].upper() for w in (name or "U").split()[:2]]) or "U"
    palette = ["#6366f1", "#8b5cf6", "#ec4899", "#f43f5e", "#f59e0b", "#10b981", "#14b8a6", "#3b82f6"]
    color = palette[sum(ord(c) for c in (name or "U")) % len(palette)]
    return {"type": "initials", "initials": initials, "color": color}


async def _find_user_by_telegram(db, telegram_id: str, username: Optional[str] = None) -> Optional[dict]:
    """Find the user linked to this Telegram identity.

    SECURITY: account identity is bound STRICTLY to the immutable numeric
    Telegram user id. We match it across all three legacy fields
    (telegram_id / telegram_user_id / telegram_chat_id) in both string and int
    shapes. We deliberately DO NOT fall back to `telegram_username`: usernames
    are mutable and can be reassigned, so a different telegram_id sharing the
    same username must never be able to log into an existing account.
    Legacy rows linked only by username must re-link via an explicit,
    authenticated flow (they no longer auto-login by username).
    """
    tg_id_str = str(telegram_id).strip()
    try:
        tg_id_int = int(tg_id_str)
    except (TypeError, ValueError):
        tg_id_int = None
    or_clauses: list = [
        {"telegram_id": tg_id_str},
        {"telegram_user_id": tg_id_str},
        {"telegram_chat_id": tg_id_str},
    ]
    if tg_id_int is not None:
        or_clauses.extend([
            {"telegram_id": tg_id_int},
            {"telegram_user_id": tg_id_int},
            {"telegram_chat_id": tg_id_int},
        ])
    return await db.users.find_one({"$or": or_clauses})


def _login_methods(user: dict) -> list:
    methods = []
    if user.get("hashed_password"):
        methods.append("password")
    if user.get("telegram_id") or user.get("telegram_user_id") or user.get("telegram_chat_id"):
        methods.append("telegram")
    if user.get("wallet_address"):
        methods.append("wallet")
    if user.get("google_id") or user.get("registration_method") == "google":
        methods.append("google")
    return methods or ["password"]


def _public_user(user: dict) -> dict:
    return {
        "id": user.get("id"),
        "username": user.get("username"),
        "display_name": user.get("display_name") or user.get("username"),
        "email": user.get("email"),
        "avatar": user.get("avatar"),
        "wallet_address": user.get("wallet_address"),
        "balance_ton": user.get("balance_ton", 0),
        "language": user.get("language", "en"),
        "is_admin": bool(user.get("is_admin")),
        "telegram_username": user.get("telegram_username"),
        "password_set": bool(user.get("hashed_password")),
        "login_methods": _login_methods(user),
    }


async def _issue_token_for(db, user: dict) -> str:
    from auth_handler import create_token, rotate_user_session
    identifier = user.get("email") or user.get("username") or user.get("wallet_address") or user.get("id")
    user_filter = {"id": user["id"]}
    sid = await rotate_user_session(db, user_filter)
    return create_token({"sub": identifier}, session_id=sid)


_INDEX_READY = False


async def _ensure_indexes(db):
    """Unique sparse index on telegram_id to prevent auto-signup race conditions."""
    global _INDEX_READY
    if _INDEX_READY:
        return
    try:
        await db.users.create_index("telegram_id", unique=True, sparse=True)
    except Exception as e:  # index may already exist with different options
        logger.warning("[tg_auth] create_index telegram_id: %s", e)
    _INDEX_READY = True


def _extract_start_param(init_data: str) -> Optional[str]:
    """Pull `start_param` (referral / deep-link payload) out of raw initData."""
    try:
        from urllib.parse import parse_qs
        q = parse_qs(init_data)
        val = q.get("start_param", [None])[0]
        return val or None
    except Exception:
        return None


async def _tg_choice_enabled(db) -> bool:
    """Global admin toggle: when True an unlinked Telegram identity is shown the
    create/link choice modal; when False (default) the Mini App silently creates
    a fresh account and logs the user in automatically (seamless auth on the
    very first activity inside Telegram — no manual step)."""
    try:
        doc = await db.admin_settings.find_one(
            {"type": "telegram_registration"}, {"_id": 0, "choice_enabled": 1}
        )
    except Exception:
        return False
    if not doc or doc.get("choice_enabled") is None:
        return False
    return bool(doc.get("choice_enabled"))


async def _referral_binding_fields(db, start_param: Optional[str]) -> dict:
    """Resolve the `start_param` (=referrer's UUID id carried by the Mini App
    `startapp=<id>` link) into the standard referral fields so the referrer
    (incl. B2B partners) actually receives this user in their referral list.
    Returns {} when there is no valid referrer."""
    if not start_param:
        return {}
    try:
        from auth_handler import resolve_referrer_id, referral_fields
        referrer_id = await resolve_referrer_id(db, start_param)
        if not referrer_id:
            return {}
        return referral_fields(referrer_id)
    except Exception as e:
        logger.warning("[tg_auth] referral binding failed: %s", e)
        return {}


def _make_preauth_token(user_id: str) -> str:
    from auth_handler import SECRET_KEY, ALGORITHM
    payload = {
        "sub": user_id,
        "preauth": True,
        "exp": datetime.now(timezone.utc) + __import__("datetime").timedelta(minutes=10),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def _read_preauth_token(token: str) -> Optional[str]:
    from auth_handler import SECRET_KEY, ALGORITHM
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if not payload.get("preauth"):
            return None
        return payload.get("sub")
    except JWTError:
        return None


def _verify_totp(user: dict, code: str) -> bool:
    """Verify a TOTP code or a single-use backup code (sha256-hashed)."""
    import pyotp
    import hashlib
    secret = user.get("two_factor_secret") or user.get("totp_secret")
    if not secret or not code:
        return False
    code = code.strip()
    # Primary: raw secret (matches login_with_2fa).
    try:
        if pyotp.TOTP(secret).verify(code, valid_window=1):
            return True
    except Exception:
        pass
    # Fallback: encrypted secret (matches withdraw path).
    try:
        from security.totp_crypto import decrypt_secret
        if pyotp.TOTP(decrypt_secret(secret)).verify(code, valid_window=1):
            return True
    except Exception:
        pass
    # Backup codes.
    code_hash = hashlib.sha256(code.upper().encode()).hexdigest()
    return code_hash in (user.get("backup_codes") or [])


async def _login_or_2fa(db, user: dict, photo_url: Optional[str] = None) -> dict:
    """Telegram auth is a strong factor by itself (initData/widget hash is
    HMAC-signed by the bot). Per product spec: DO NOT prompt for 2FA after a
    successful Telegram login — issue the final access token directly."""
    token = await _issue_token_for(db, user)
    # the Telegram profile photo becomes the avatar unless the player set their own (in the background)
    try:
        from core import tg_avatar
        if photo_url and str(photo_url).startswith("https://") and user.get("tg_photo_url") != photo_url:
            await db.users.update_one({"id": user.get("id")}, {"$set": {"tg_photo_url": str(photo_url)[:500]}})
        tg_avatar.refresh_bg(db, user, photo_url)
    except Exception as _e:
        logger.debug(f"tg avatar hook: {_e}")
    return {"status": "ok", "token": token, "user": _public_user(user)}


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
def _validate_init_or_raise(init_data: str, max_age: int = 24 * 3600) -> dict:
    from auth_handler import verify_telegram_init_data
    bot_token = _bot_token()
    if not bot_token:
        raise HTTPException(status_code=503, detail="Telegram bot not configured on the server")
    tg_user = verify_telegram_init_data(init_data, bot_token, max_age=max_age)
    if not tg_user:
        # verify_telegram_init_data enforces BOTH the HMAC signature AND the
        # auth_date freshness (replay guard), returning None for either failure.
        raise HTTPException(status_code=401, detail="Invalid Telegram initData signature or expired")
    return tg_user


@router.post("/miniapp")
async def telegram_miniapp_login(data: MiniAppLogin, request: Request):
    """Seamless Mini App login. Validates initData and:
      • if the Telegram id is already linked to an account → issues our JWT
        (auto-login to the linked account).
      • if the Telegram id is NOT linked to anyone → depending on the global
        admin toggle: return {status:"choice_required"} (default) OR silently
        create a fresh account and log in.
    Passwordless."""
    from server import db

    _t0 = time.monotonic()
    logger.info("[AUTH99] /miniapp START bot_token_configured=%s init_data_len=%s",
                bool(_bot_token()), len(data.init_data or ""))
    await _ensure_indexes(db)
    try:
        tg_user = _validate_init_or_raise(data.init_data)
    except HTTPException as _he:
        # 401 (bad/expired signature) or 503 (bot token missing) — this is a
        # FREQUENT cause of the endless "99%" preloader, because the frontend
        # retries 5xx forever. Log it loudly so it is visible in the server log.
        logger.error("[AUTH99] /miniapp initData validation FAILED status=%s detail=%s",
                     _he.status_code, _he.detail)
        raise
    telegram_id = str(tg_user.get("id") or "").strip()
    tg_username = tg_user.get("username")
    tg_first_name = tg_user.get("first_name")
    start_param = _extract_start_param(data.init_data)
    if not telegram_id:
        logger.error("[AUTH99] /miniapp telegram_id MISSING in validated initData")
        raise HTTPException(status_code=400, detail="Telegram user id missing")
    try:
        telegram_id_int = int(telegram_id)
    except (ValueError, TypeError):
        telegram_id_int = None

    user = await _find_user_by_telegram(db, telegram_id, tg_username)
    logger.info("[AUTH99] /miniapp tg_id=%s username=%s user_found=%s",
                telegram_id, tg_username, bool(user))

    if not user:
        # Unlinked Telegram identity. When the admin has DISABLED the choice
        # modal, register a new account silently (same as tapping "Create new").
        if not await _tg_choice_enabled(db):
            user = await _create_miniapp_user(db, tg_user, start_param)
            resp = await _login_or_2fa(db, user, photo_url=(tg_user or {}).get("photo_url"))
            resp["is_new_signup"] = True
            logger.info("[AUTH99] /miniapp OK branch=create-new user=%s took=%.0fms",
                        user.get("id"), (time.monotonic() - _t0) * 1000)
            return resp
        logger.info("[AUTH99] /miniapp OK branch=choice_required tg_id=%s took=%.0fms",
                    telegram_id, (time.monotonic() - _t0) * 1000)
        return {
            "status": "choice_required",
            "telegram": {
                "id": telegram_id,
                "username": tg_username,
                "first_name": tg_first_name,
            },
        }

    # Linked account → refresh identity + auto-login. Also (re)bind the referrer
    # ONCE if it was never recorded, so a user who first arrives via a partner
    # link is credited to that partner.
    _ref_bind = {}
    if start_param and not user.get("referrerId"):
        _ref_bind = await _referral_binding_fields(db, start_param)
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {
            "telegram_id": telegram_id_int if telegram_id_int is not None else telegram_id,
            "telegram_user_id": telegram_id,
            "telegram_chat_id": user.get("telegram_chat_id") or telegram_id,
            "telegram_username": tg_username or user.get("telegram_username"),
            "tg_username": tg_username or user.get("tg_username"),
            "tg_first_name": tg_first_name or user.get("tg_first_name"),
            **({"ref_by": start_param} if start_param and not user.get("ref_by") else {}),
            **_ref_bind,
            "telegram_verified": True,
            "telegram_auth_verified_at": _now_iso(),
            "last_seen_at": _now_iso(),
            **({"mini_app_first_seen_at": _now_iso()} if not user.get("mini_app_first_seen_at") else {}),
        }},
    )
    user = await db.users.find_one({"id": user["id"]})

    resp = await _login_or_2fa(db, user, photo_url=(tg_user or {}).get("photo_url"))
    resp["is_new_signup"] = False
    logger.info("[AUTH99] /miniapp OK branch=login user=%s balance=%s businesses=%s took=%.0fms",
                user.get("id"), user.get("balance_ton"),
                len(user.get("businesses_owned") or []), (time.monotonic() - _t0) * 1000)
    return resp


async def _create_miniapp_user(db, tg_user: dict, start_param: Optional[str]) -> dict:
    """Create a brand-new passwordless account bound to this Telegram identity,
    binding the referrer from `start_param` so the referrer/partner gets credit.
    Assumes the caller already verified initData and that no linked user exists."""
    from pymongo.errors import DuplicateKeyError
    telegram_id = str(tg_user.get("id") or "").strip()
    tg_username = tg_user.get("username")
    tg_first_name = tg_user.get("first_name")
    try:
        telegram_id_int = int(telegram_id)
    except (ValueError, TypeError):
        telegram_id_int = None

    base_name = tg_username or (tg_first_name or f"tg{telegram_id[-6:]}")
    username = base_name
    if await db.users.find_one({"username": username}):
        username = f"{base_name}_{telegram_id[-4:]}"
    lang_code = (tg_user.get("language_code") or "en")[:2]
    from core.i18n_messages import SUPPORTED as _LANGS
    language = lang_code if lang_code in _LANGS else "en"
    display_name = (
        ((tg_first_name or "") + " " + (tg_user.get("last_name") or "")).strip()
        or username
    )
    _ref_bind = await _referral_binding_fields(db, start_param)
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
        "language": language,
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
        "telegram_id": telegram_id_int if telegram_id_int is not None else telegram_id,
        "telegram_user_id": telegram_id,
        "telegram_chat_id": telegram_id,
        "telegram_username": tg_username,
        "tg_username": tg_username,
        "tg_first_name": tg_first_name,
        "ref_by": start_param,
        "telegram_verified": True,
        "telegram_notifications": True,
        "telegram_auth_verified_at": _now_iso(),
        "login_methods": ["telegram"],
        "mini_app_first_seen_at": _now_iso(),
        "last_seen_at": _now_iso(),
        "created_at": datetime.now(timezone.utc),
        "last_login": datetime.now(timezone.utc),
        **_ref_bind,
    }
    try:
        await db.users.insert_one(user)
        logger.info("[tg_miniapp] create-new user=%s tg=%s ref=%s",
                    user["id"], telegram_id, _ref_bind.get("referrerId"))
    except DuplicateKeyError:
        existing = await _find_user_by_telegram(db, telegram_id, tg_username)
        if not existing:
            raise HTTPException(status_code=409, detail="Concurrent signup conflict")
        return existing
    return user


@router.post("/miniapp/create")
async def telegram_miniapp_create(data: MiniAppLogin, request: Request):
    """Create a brand-new passwordless account bound to this Telegram identity.
    Called only when the user explicitly chose "Create new account" after a
    `choice_required` response. Re-validates initData (stateless)."""
    from server import db

    await _ensure_indexes(db)
    tg_user = _validate_init_or_raise(data.init_data)
    telegram_id = str(tg_user.get("id") or "").strip()
    tg_username = tg_user.get("username")
    start_param = _extract_start_param(data.init_data)
    if not telegram_id:
        raise HTTPException(status_code=400, detail="Telegram user id missing")

    # Guard: if it got linked in the meantime, just log in.
    existing = await _find_user_by_telegram(db, telegram_id, tg_username)
    if existing:
        resp = await _login_or_2fa(db, existing, photo_url=(tg_user or {}).get("photo_url"))
        resp["is_new_signup"] = False
        return resp

    user = await _create_miniapp_user(db, tg_user, start_param)
    resp = await _login_or_2fa(db, user, photo_url=(tg_user or {}).get("photo_url"))
    resp["is_new_signup"] = True
    return resp


@router.post("/widget")
async def telegram_widget_login(data: WidgetLogin, request: Request):
    """Browser Telegram Login Widget → find-or-create user → JWT (or 2FA challenge)."""
    from server import db
    from pymongo.errors import DuplicateKeyError
    await _ensure_indexes(db)
    bot_token = _bot_token()
    if not bot_token:
        raise HTTPException(status_code=503, detail="Telegram bot not configured on the server")
    tg_user = _verify_login_widget(data.data, bot_token)
    if not tg_user:
        raise HTTPException(status_code=401, detail="Invalid Telegram login signature")
    telegram_id = str(tg_user.get("id") or "").strip()
    if not telegram_id:
        raise HTTPException(status_code=400, detail="Telegram user id missing")
    try:
        telegram_id_int = int(telegram_id)
    except (ValueError, TypeError):
        telegram_id_int = None

    user = await _find_user_by_telegram(db, telegram_id, tg_user.get("username"))
    if not user:
        return {
            "status": "choice_required",
            "telegram": {
                "id": telegram_id,
                "username": tg_user.get("username"),
                "first_name": tg_user.get("first_name"),
            },
        }
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {
            "telegram_id": telegram_id_int if telegram_id_int is not None else telegram_id,
            "telegram_user_id": telegram_id,
            "telegram_username": tg_user.get("username") or user.get("telegram_username"),
            "tg_username": tg_user.get("username") or user.get("tg_username"),
            "tg_first_name": tg_user.get("first_name") or user.get("tg_first_name"),
            "telegram_verified": True,
            "telegram_auth_verified_at": _now_iso(),
            "last_seen_at": _now_iso(),
        }},
    )
    user = await db.users.find_one({"id": user["id"]})

    resp = await _login_or_2fa(db, user, photo_url=(tg_user or {}).get("photo_url"))
    resp["is_new_signup"] = False
    return resp


@router.post("/widget/create")
async def telegram_widget_create(data: WidgetLogin, request: Request):
    """Create a new passwordless account bound to this Telegram identity
    (browser Login Widget). Called after a `choice_required` response."""
    from server import db
    from pymongo.errors import DuplicateKeyError
    await _ensure_indexes(db)
    bot_token = _bot_token()
    if not bot_token:
        raise HTTPException(status_code=503, detail="Telegram bot not configured on the server")
    tg_user = _verify_login_widget(data.data, bot_token)
    if not tg_user:
        raise HTTPException(status_code=401, detail="Invalid Telegram login signature")
    telegram_id = str(tg_user.get("id") or "").strip()
    if not telegram_id:
        raise HTTPException(status_code=400, detail="Telegram user id missing")
    try:
        telegram_id_int = int(telegram_id)
    except (ValueError, TypeError):
        telegram_id_int = None

    existing = await _find_user_by_telegram(db, telegram_id, tg_user.get("username"))
    if existing:
        resp = await _login_or_2fa(db, existing, photo_url=(tg_user or {}).get("photo_url"))
        resp["is_new_signup"] = False
        return resp

    base_name = tg_user.get("username") or (tg_user.get("first_name") or f"tg{telegram_id[-6:]}")
    username = base_name if not await db.users.find_one({"username": base_name}) else f"{base_name}_{telegram_id[-4:]}"
    display_name = ((tg_user.get("first_name") or "") + " " + (tg_user.get("last_name") or "")).strip() or username
    user = {
        "id": str(uuid.uuid4()),
        "username": username,
        "display_name": display_name,
        "email": None,
        "hashed_password": None,
        "wallet_address": None,
        "avatar": {"type": "url", "url": tg_user.get("photo_url")} if tg_user.get("photo_url") else _avatar_for(display_name),
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
        "telegram_id": telegram_id_int if telegram_id_int is not None else telegram_id,
        "telegram_user_id": telegram_id,
        "telegram_chat_id": telegram_id,
        "telegram_username": tg_user.get("username"),
        "tg_username": tg_user.get("username"),
        "tg_first_name": tg_user.get("first_name"),
        "telegram_verified": True,
        "telegram_notifications": True,
        "telegram_auth_verified_at": _now_iso(),
        "login_methods": ["telegram"],
        "last_seen_at": _now_iso(),
        "created_at": datetime.now(timezone.utc),
        "last_login": datetime.now(timezone.utc),
    }
    try:
        await db.users.insert_one(user)
    except DuplicateKeyError:
        user = await _find_user_by_telegram(db, telegram_id, tg_user.get("username"))
        if not user:
            raise HTTPException(status_code=409, detail="Concurrent signup conflict")

    resp = await _login_or_2fa(db, user, photo_url=(tg_user or {}).get("photo_url"))
    resp["is_new_signup"] = True
    return resp


@router.post("/verify-2fa")
async def telegram_verify_2fa(payload: Dict[str, Any]):
    """Exchange a `pre_auth_token` + TOTP/backup code for a final access token.
    Used to complete Telegram Mini App / Widget login when 2FA is enabled."""
    from server import db
    pre_auth_token = str(payload.get("pre_auth_token") or "")
    totp_code = str(payload.get("totp_code") or "")
    uid = _read_preauth_token(pre_auth_token)
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid or expired pre-auth token")
    user = await db.users.find_one({"id": uid})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not _verify_totp(user, totp_code):
        raise HTTPException(status_code=401, detail="Invalid 2FA code")
    # Consume backup code if one was used.
    import hashlib
    ch = hashlib.sha256(totp_code.strip().upper().encode()).hexdigest()
    if ch in (user.get("backup_codes") or []):
        await db.users.update_one({"id": uid}, {"$pull": {"backup_codes": ch}})
    token = await _issue_token_for(db, user)
    return {"status": "ok", "token": token, "user": _public_user(user)}


@router.post("/unlink")
async def telegram_unlink(current_user: dict = Depends(lambda: None)):
    """Placeholder dependency replaced at include time (see create_telegram_auth_router)."""
    raise HTTPException(status_code=500, detail="not wired")


@router.post("/stepup")
async def telegram_stepup(data: StepUpRequest):
    raise HTTPException(status_code=500, detail="not wired")


def create_telegram_auth_router(get_current_user_dep) -> APIRouter:
    """Build the router with auth-dependent endpoints wired to the app's
    current-user dependency (unlink, stepup)."""
    r = APIRouter(prefix="/api/auth/telegram", tags=["telegram-auth"])

    # Re-expose the passwordless endpoints from the module-level router.
    r.add_api_route("/miniapp", telegram_miniapp_login, methods=["POST"])
    r.add_api_route("/miniapp/create", telegram_miniapp_create, methods=["POST"])
    r.add_api_route("/widget", telegram_widget_login, methods=["POST"])
    r.add_api_route("/widget/create", telegram_widget_create, methods=["POST"])
    r.add_api_route("/verify-2fa", telegram_verify_2fa, methods=["POST"])

    @r.post("/unlink")
    async def unlink(current_user=Depends(get_current_user_dep)):
        from server import db
        uid = getattr(current_user, "id", None) or (current_user.get("id") if isinstance(current_user, dict) else None)
        user = await db.users.find_one({"id": uid})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        has_password = bool(user.get("hashed_password"))
        has_wallet = bool(user.get("wallet_address") or user.get("raw_address"))
        has_google = bool(user.get("google_id")) or user.get("registration_method") == "google"
        if not (has_password or has_wallet or has_google):
            raise HTTPException(status_code=400, detail="telegram_only_auth_cannot_unlink")
        _chat_id = str(user.get("telegram_chat_id") or user.get("telegram_id") or "").strip()
        await db.users.update_one(
            {"id": uid},
            {"$unset": {
                "telegram_id": "", "telegram_user_id": "", "telegram_chat_id": "",
                "telegram_username": "", "telegram_verified": "", "telegram_auth_verified_at": "",
                "telegram_notifications": "",
            }},
        )
        try:
            if _chat_id:
                from routes.telegram_notifications import notify_link_event as _notify_link_event
                import asyncio as _asyncio
                _asyncio.create_task(_notify_link_event(db, _chat_id, "unlinked"))
        except Exception:
            pass
        user = await db.users.find_one({"id": uid})
        return {"ok": True, "login_methods": _login_methods(user)}

    @r.post("/stepup")
    async def stepup(data: StepUpRequest, current_user=Depends(get_current_user_dep)):
        """Fresh initData (< 5 min) proving the caller is the linked Telegram
        user — used to authorize sensitive operations without a password."""
        tg_user = _validate_init_or_raise(data.init_data, max_age=5 * 60)
        uid = getattr(current_user, "id", None) or (current_user.get("id") if isinstance(current_user, dict) else None)
        from server import db
        user = await db.users.find_one({"id": uid})
        linked = str((user or {}).get("telegram_id") or (user or {}).get("telegram_user_id") or "")
        if linked and str(tg_user.get("id")) != linked:
            raise HTTPException(status_code=403, detail="Telegram account mismatch")
        return {"ok": True, "verified_at": _now_iso()}

    return r
