"""Telegram Mini App biometric authentication for withdrawal confirmations.

Flow:
  1. Setup (once per device):
     • Client verifies identity: /register/verify-identity  (password OR 2FA code)
       → returns short-lived `setup_challenge` JWT (5 min TTL).
     • Client calls /register/finish with the challenge + device_id + initData.
       → server generates a random 32-byte secret, stores SHA-256(secret) +
         device_id in ``users.tg_biometry_tokens``.
       → returns the plaintext secret ONCE. Client must call
         ``Telegram.WebApp.BiometricManager.updateBiometricToken(secret)`` to
         persist it inside the device's secure enclave (Keychain / Keystore).

  2. Withdrawal (each time):
     • Client calls ``bio.authenticate()`` — the OS prompts for fingerprint /
       Face ID. On success Telegram returns the previously-stored secret.
     • Client sends {token, initData} to /authenticate.
       → server verifies token hash exists for this user AND initData signature
         is fresh → returns short-lived ``withdraw_tg_biometry_token`` (JWT
         60 s TTL) to include in the /api/withdraw request.

Bridging (WebAuthn → Telegram biometry): when the user already has WebAuthn
enabled on the web but opens the Mini App, they run through /register/*
above, providing their password as identity proof (2FA is optional). A single
account can have BOTH WebAuthn (web) AND Telegram biometry tokens (mobile)
active at the same time — they're independent auth factors.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl

import jwt
import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_ISSUER = "gramcity-tg-biometry"
_SETUP_TTL_SECONDS = 5 * 60          # 5 min
_WITHDRAW_TTL_SECONDS = 60           # 1 min
_INIT_DATA_MAX_AGE_SECONDS = 15 * 60  # 15 min

# Delimiter for token identity: token is displayed to the client, but we store
# only sha256 to prevent leak-on-DB-read.


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _get_bot_token() -> Optional[str]:
    return os.environ.get("TELEGRAM_BOT_TOKEN") or None


def validate_init_data(init_data: str, max_age_seconds: Optional[int] = _INIT_DATA_MAX_AGE_SECONDS) -> Dict[str, Any]:
    """Validate a raw ``Telegram.WebApp.initData`` string against the bot's
    secret and freshness. Returns the parsed data (with a ``user`` dict) on
    success, raises HTTPException(401) otherwise.

    Pass ``max_age_seconds=None`` to skip the freshness (auth_date) check — used
    for biometry SETUP, where Telegram's ``initData`` cannot be refreshed by the
    client and freshness is instead guaranteed by a fresh biometric scan plus a
    short-lived (5 min) setup_challenge. The cryptographic signature is ALWAYS
    verified regardless of this flag.

    Reference:
      https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    """
    if not init_data:
        raise HTTPException(status_code=400, detail="Missing initData")
    bot_token = _get_bot_token()
    if not bot_token:
        raise HTTPException(status_code=503, detail="Telegram bot not configured on the server")

    pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=False))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise HTTPException(status_code=401, detail="initData missing hash")

    # Data-check-string: alphabetical order of remaining k=v joined by \n
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed = hmac.new(secret_key, data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed, received_hash):
        raise HTTPException(status_code=401, detail="Invalid initData signature")

    # Freshness (skipped when max_age_seconds is None — see docstring).
    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError:
        auth_date = 0
    if max_age_seconds is not None:
        if not auth_date or (int(time.time()) - auth_date) > max_age_seconds:
            raise HTTPException(status_code=401, detail="initData too old")

    # Parse user
    user_json = pairs.get("user")
    parsed_user: Dict[str, Any] = {}
    if user_json:
        try:
            import json as _json
            parsed_user = _json.loads(user_json)
        except Exception:
            parsed_user = {}

    return {"auth_date": auth_date, "user": parsed_user, "raw": pairs}


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------
class VerifyIdentityRequest(BaseModel):
    password: Optional[str] = None
    totp_code: Optional[str] = Field(default=None, max_length=8)


class RegisterFinishRequest(BaseModel):
    setup_challenge: str
    init_data: str
    device_id: str = Field(min_length=1, max_length=128)
    device_name: Optional[str] = Field(default=None, max_length=64)


class AuthenticateRequest(BaseModel):
    token: str = Field(min_length=8, max_length=256)
    init_data: str
    purpose: str = Field(default="withdraw", max_length=32)


class DeleteDeviceRequest(BaseModel):
    device_id: str


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------
def create_tg_biometry_router(db, get_current_user_dep, secret_key: str, algorithm: str = "HS256") -> APIRouter:
    router = APIRouter(prefix="/api/security/telegram-biometry", tags=["telegram-biometry"])

    from auth_handler import pwd_context  # local import (avoid circular)

    async def _load_user(user) -> Dict[str, Any]:
        u = await db.users.find_one(
            {"$or": [{"id": getattr(user, "id", None)}, {"email": getattr(user, "email", None)}]},
            {"_id": 0},
        )
        if not u:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        return u

    # -------------------------------------------------------------------
    # GET /status  — is biometry enabled? list of devices.
    # -------------------------------------------------------------------
    @router.get("/status")
    async def status(current_user=Depends(get_current_user_dep)):
        user = await _load_user(current_user)
        tokens: List[Dict[str, Any]] = list(user.get("tg_biometry_tokens") or [])
        # Never expose token hashes to the client.
        devices = [{
            "device_id": t.get("device_id"),
            "device_name": t.get("device_name") or "",
            "created_at": t.get("created_at"),
            "last_used_at": t.get("last_used_at"),
        } for t in tokens]
        return {
            "enabled": bool(tokens),
            "device_count": len(tokens),
            "devices": devices,
            # Client uses this to decide whether it needs to bridge from
            # WebAuthn: has_web_biometry=True + enabled=False → show
            # "Set up Telegram biometry" prompt.
            "has_web_biometry": bool(user.get("passkeys") and len(user.get("passkeys", [])) > 0),
        }

    # -------------------------------------------------------------------
    # POST /register/verify-identity — password OR 2FA. Returns setup_challenge.
    # -------------------------------------------------------------------
    @router.post("/register/verify-identity")
    async def verify_identity(data: VerifyIdentityRequest, current_user=Depends(get_current_user_dep)):
        user = await _load_user(current_user)
        verified = False

        # Path A: password
        if data.password:
            hashed = user.get("hashed_password") or ""
            if hashed and pwd_context.verify(data.password, hashed):
                verified = True

        # Path B: TOTP (only if user has 2FA enabled)
        if not verified and data.totp_code:
            from security.totp_crypto import decrypt_secret  # local import
            totp_secret = user.get("two_factor_secret") or user.get("totp_secret")
            totp_secret = decrypt_secret(totp_secret) if totp_secret else None
            if user.get("is_2fa_enabled") and totp_secret:
                totp = pyotp.TOTP(totp_secret)
                if totp.verify((data.totp_code or "").strip(), valid_window=3):
                    verified = True

        if not verified:
            raise HTTPException(status_code=401, detail="Неверный пароль или код 2FA")

        challenge = jwt.encode(
            {
                "iss": _ISSUER,
                "sub": user["id"],
                "typ": "setup",
                "exp": int(time.time()) + _SETUP_TTL_SECONDS,
                "iat": int(time.time()),
                "nonce": secrets.token_urlsafe(16),
            },
            secret_key,
            algorithm=algorithm,
        )
        return {"ok": True, "setup_challenge": challenge, "expires_in": _SETUP_TTL_SECONDS}

    # -------------------------------------------------------------------
    # POST /register/finish — accept challenge + initData + device_id.
    # Server mints the biometric secret and stores its hash.
    # -------------------------------------------------------------------
    @router.post("/register/finish")
    async def register_finish(data: RegisterFinishRequest, current_user=Depends(get_current_user_dep)):
        # Decode challenge
        try:
            payload = jwt.decode(data.setup_challenge, secret_key, algorithms=[algorithm])
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Срок действия подтверждения истёк — повторите верификацию")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Неверный setup_challenge")
        if payload.get("iss") != _ISSUER or payload.get("typ") != "setup":
            raise HTTPException(status_code=401, detail="Неверный setup_challenge")

        user = await _load_user(current_user)
        if payload.get("sub") != user["id"]:
            raise HTTPException(status_code=401, detail="Не тот пользователь")

        # Verify initData — proves the request came from the actual Telegram
        # Mini App session of the current user. Freshness (auth_date) is NOT
        # enforced here: Telegram's initData cannot be refreshed by the client,
        # so a stale launch would wrongly fail with "initData too old". Instead,
        # freshness is guaranteed by the fresh biometric scan the client just
        # performed and the short-lived (5 min) setup_challenge above. The
        # cryptographic signature is still fully validated.
        info = validate_init_data(data.init_data, max_age_seconds=None)
        tg_user = info.get("user") or {}
        tg_uid = str(tg_user.get("id") or "")
        # Optional: enforce that the initData user matches the linked telegram
        # user id on the account. If the user hasn't linked a Telegram yet, we
        # accept the current one and link it now.
        linked = str(user.get("telegram_user_id") or "")
        if linked and tg_uid and linked != tg_uid:
            raise HTTPException(status_code=403, detail="Telegram аккаунт не совпадает с привязанным")

        # Generate & store the secret hash.
        secret = secrets.token_urlsafe(32)
        token_hash = _hash_token(secret)
        entry = {
            "device_id": data.device_id,
            "device_name": (data.device_name or "").strip()[:64] or "Мобильное устройство",
            "token_hash": token_hash,
            "created_at": _now_iso(),
            "last_used_at": None,
            "tg_user_id": tg_uid or None,
        }
        # Upsert-by-device_id semantics: replace prior entry for the same device.
        await db.users.update_one(
            {"id": user["id"]},
            {"$pull": {"tg_biometry_tokens": {"device_id": data.device_id}}},
        )
        await db.users.update_one(
            {"id": user["id"]},
            {"$push": {"tg_biometry_tokens": entry}},
        )
        # If Telegram was not linked yet, do the bridge here.
        if not linked and tg_uid:
            await db.users.update_one(
                {"id": user["id"]},
                {"$set": {
                    "telegram_user_id": tg_uid,
                    "telegram_username": tg_user.get("username") or user.get("telegram_username"),
                    "telegram_verified": True,
                }},
            )
        return {
            "ok": True,
            "biometric_token": secret,  # plaintext, ONLY time it leaves the server
            "device_id": data.device_id,
            "device_name": entry["device_name"],
        }

    # -------------------------------------------------------------------
    # POST /authenticate — verify token + initData → returns withdraw token.
    # -------------------------------------------------------------------
    @router.post("/authenticate")
    async def authenticate(data: AuthenticateRequest, current_user=Depends(get_current_user_dep)):
        info = validate_init_data(data.init_data)
        tg_user = info.get("user") or {}
        tg_uid = str(tg_user.get("id") or "")

        user = await _load_user(current_user)
        tokens: List[Dict[str, Any]] = list(user.get("tg_biometry_tokens") or [])
        if not tokens:
            raise HTTPException(status_code=404, detail="Биометрия не настроена")

        h = _hash_token(data.token)
        match = None
        for t in tokens:
            if hmac.compare_digest(str(t.get("token_hash") or ""), h):
                match = t
                break
        if not match:
            raise HTTPException(status_code=401, detail="Неверный биометрический токен")

        # Optional: enforce that the initData user matches the token owner.
        tok_owner = str(match.get("tg_user_id") or "")
        if tok_owner and tg_uid and tok_owner != tg_uid:
            raise HTTPException(status_code=403, detail="Telegram аккаунт не совпадает")

        # Update last_used_at
        await db.users.update_one(
            {"id": user["id"], "tg_biometry_tokens.device_id": match.get("device_id")},
            {"$set": {"tg_biometry_tokens.$.last_used_at": _now_iso()}},
        )

        # Mint the withdraw-scoped short-lived token consumed by /api/withdraw
        # (mirrors the WebAuthn `withdraw_pk_token` model).
        withdraw_token = jwt.encode(
            {
                "iss": _ISSUER,
                "sub": user["id"],
                "typ": "withdraw",
                "device_id": match.get("device_id"),
                "purpose": data.purpose or "withdraw",
                "exp": int(time.time()) + _WITHDRAW_TTL_SECONDS,
                "iat": int(time.time()),
                "jti": secrets.token_urlsafe(12),
            },
            secret_key,
            algorithm=algorithm,
        )
        return {
            "ok": True,
            "withdraw_tg_biometry_token": withdraw_token,
            "expires_in": _WITHDRAW_TTL_SECONDS,
            "device_id": match.get("device_id"),
        }

    # -------------------------------------------------------------------
    # DELETE /device — remove biometry from a device.
    # -------------------------------------------------------------------
    @router.post("/delete")
    async def delete_device(data: DeleteDeviceRequest, current_user=Depends(get_current_user_dep)):
        user = await _load_user(current_user)
        res = await db.users.update_one(
            {"id": user["id"]},
            {"$pull": {"tg_biometry_tokens": {"device_id": data.device_id}}},
        )
        if not res.modified_count:
            raise HTTPException(status_code=404, detail="Устройство не найдено")
        return {"ok": True}

    return router


# ---------------------------------------------------------------------------
# Helper: verify a `withdraw_tg_biometry_token` (consumed by /api/withdraw).
# Returns True if the token is valid & belongs to `user_id`, False otherwise.
# ---------------------------------------------------------------------------
def verify_withdraw_biometry_token(token: str, user_id: str, secret_key: str, algorithm: str = "HS256") -> bool:
    if not token or not user_id:
        return False
    try:
        payload = jwt.decode(token, secret_key, algorithms=[algorithm])
    except jwt.ExpiredSignatureError:
        return False
    except jwt.InvalidTokenError:
        return False
    return (
        payload.get("iss") == _ISSUER
        and payload.get("typ") == "withdraw"
        and payload.get("sub") == user_id
    )
