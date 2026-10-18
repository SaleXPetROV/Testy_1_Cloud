"""
Security Router Integration
Combines all security routes and integrates with main server
"""
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt  # PyJWT (python-jose: unpatched CVEs and not in requirements)
from jwt import PyJWTError as JWTError
import os
import logging

from .totp_handler import create_totp_routes
from .passkey_handler import create_passkey_routes
from .withdrawal_handler import create_withdrawal_routes
from .security_service import SecurityService

# Passkey challenges live in MongoDB instead of in-memory `pending_challenges`
# dict. With multi-worker gunicorn each worker has its own memory, so a
# challenge created on worker A is invisible to worker B — that produced the
# "Challenge не найден или истёк" error after the browser finished the
# user-verification step on the user's machine. Using Mongo gives us cross-
# worker visibility plus automatic 5-min expiry via a TTL index.

PASSKEY_CHALLENGE_TTL_SECONDS = 300  # 5 минут


async def _store_passkey_challenge(db, challenge_id: str, payload: dict) -> None:
    doc = {
        "_id": challenge_id,
        "created_at": payload.get("created_at"),
        # Mongo will auto-delete after expires_at via TTL index (see init below).
        "expires_at": payload.get("created_at"),
        **{k: v for k, v in payload.items() if k != "_id"},
    }
    await db.passkey_challenges.replace_one({"_id": challenge_id}, doc, upsert=True)


async def _pop_passkey_challenge(db, challenge_id: str) -> dict | None:
    """Atomically fetch + delete a challenge. Returns None if absent/expired."""
    doc = await db.passkey_challenges.find_one_and_delete({"_id": challenge_id})
    if not doc:
        return None
    # The doc's `_id` is a hex string (not BSON ObjectId), but strip it anyway
    # to make sure no MongoDB-specific types leak to callers / responses.
    doc.pop("_id", None)
    # TTL guard: explicit age check (in case Mongo's TTL background sweep
    # hasn't deleted yet). MongoDB stores datetimes naive-UTC, while
    # `datetime.now(timezone.utc)` is aware → comparing them raises
    # `can't subtract offset-naive and offset-aware datetimes`. Normalize
    # both sides to naive UTC before the diff.
    from datetime import datetime, timezone
    created_at = doc.get("created_at")
    if isinstance(created_at, datetime):
        if created_at.tzinfo is not None:
            created_at_naive = created_at.astimezone(timezone.utc).replace(tzinfo=None)
        else:
            created_at_naive = created_at
        now_naive = datetime.utcnow()
        age = (now_naive - created_at_naive).total_seconds()
        if age > PASSKEY_CHALLENGE_TTL_SECONDS:
            return None
    return doc


async def _ensure_passkey_indexes(db) -> None:
    try:
        await db.passkey_challenges.create_index(
            "expires_at",
            expireAfterSeconds=PASSKEY_CHALLENGE_TTL_SECONDS,
        )
    except Exception:
        pass

logger = logging.getLogger(__name__)

SECRET_KEY = os.environ.get('JWT_SECRET_KEY') or ''
if not SECRET_KEY:
    from security_middleware import get_or_generate_jwt_secret
    SECRET_KEY = get_or_generate_jwt_secret()
ALGORITHM = "HS256"

from auth_cookie import CookieOrBearer
security = CookieOrBearer(auto_error=False)


def create_security_router(db):
    """Create main security router with all sub-routes"""
    
    security_router = APIRouter(prefix="/api/security", tags=["security"])
    security_service = SecurityService(db)

    # Fire-and-forget creation of TTL index for passkey challenges. Idempotent.
    import asyncio
    try:
        asyncio.get_event_loop().create_task(_ensure_passkey_indexes(db))
    except RuntimeError:
        # No running loop yet (startup pre-asgi): index will be created lazily.
        pass
    
    # Auth dependency for security routes
    async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
        if not credentials:
            raise HTTPException(status_code=401, detail="Not authenticated")
        try:
            payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
            identifier: str = payload.get("sub")
            if not identifier:
                raise HTTPException(status_code=401, detail="Invalid token")
            token_sid = payload.get("sid")
            
            user_doc = await db.users.find_one({
                "$or": [
                    {"wallet_address": identifier},
                    {"email": identifier},
                    {"username": identifier}
                ]
            })
            
            if not user_doc:
                raise HTTPException(status_code=404, detail="User not found")
            
            current_sid = user_doc.get("session_id")
            # Single-session enforcement DISABLED — token valid until logout.
            if False and token_sid and current_sid and token_sid != current_sid:
                raise HTTPException(status_code=401, detail="SESSION_OVERRIDDEN")
            if token_sid and not current_sid:
                await db.users.update_one({"_id": user_doc["_id"]}, {"$set": {"session_id": token_sid}})
            
            return {
                "id": user_doc.get("id", str(user_doc.get("_id"))),
                "wallet_address": user_doc.get("wallet_address"),
                "email": user_doc.get("email"),
                "username": user_doc.get("username")
            }
        except JWTError:
            raise HTTPException(status_code=401, detail="Invalid token")
    
    # ==================== MAIN SECURITY STATUS ====================
    
    @security_router.get("/status")
    async def get_security_status(current_user: dict = Depends(get_current_user)):
        """Get complete security status for current user"""
        status = await security_service.get_security_status(current_user["id"])
        return status
    
    @security_router.get("/logs")
    async def get_security_logs(
        limit: int = 50,
        current_user: dict = Depends(get_current_user)
    ):
        """Get security audit logs for current user"""
        logs = await security_service.get_security_logs(current_user["id"], limit=limit)
        return {"logs": logs, "count": len(logs)}
    
    # ==================== TOTP ROUTES ====================
    
    # Helper function to build safe user query
    def build_user_query(current_user: dict) -> dict:
        """Build MongoDB query avoiding None values that match all null fields"""
        conditions = []
        if current_user.get("id"):
            conditions.append({"id": current_user["id"]})
        if current_user.get("wallet_address"):
            conditions.append({"wallet_address": current_user["wallet_address"]})
        if current_user.get("email"):
            conditions.append({"email": current_user["email"]})
        return {"$or": conditions} if conditions else {"id": "NOMATCH"}
    
    @security_router.post("/totp/setup/start")
    async def start_totp_setup(current_user: dict = Depends(get_current_user)):
        """Start TOTP (2FA) setup - generates QR code"""
        from .totp_handler import generate_totp_secret, get_totp_uri, generate_qr_code_base64
        
        user = await db.users.find_one(
            build_user_query(current_user),
            {"_id": 0}
        )
        
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        
        if user.get("is_2fa_enabled"):
            raise HTTPException(status_code=400, detail="2FA уже включена")
        
        if not user.get("email"):
            raise HTTPException(status_code=400, detail="Для 2FA требуется привязать email")
        
        secret = generate_totp_secret()
        uri = get_totp_uri(secret, user["email"])
        qr_code = generate_qr_code_base64(uri)

        from .totp_crypto import encrypt_secret
        await db.users.update_one(
            {"id": user["id"]},
            {"$set": {"pending_2fa_secret": encrypt_secret(secret)}}
        )
        
        return {
            "status": "pending",
            "secret": secret,
            "qr_code": qr_code,
            "uri": uri,
            "message": "Отсканируйте QR-код в приложении аутентификации"
        }
    
    @security_router.post("/totp/setup/confirm")
    async def confirm_totp_setup(code: str, current_user: dict = Depends(get_current_user)):
        """Confirm TOTP setup with code from authenticator"""
        from .totp_handler import verify_totp_code
        from datetime import datetime, timezone
        
        user = await db.users.find_one(
            build_user_query(current_user),
            {"_id": 0}
        )
        
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        
        pending_secret_enc = user.get("pending_2fa_secret")
        if not pending_secret_enc:
            raise HTTPException(status_code=400, detail="Сначала начните настройку 2FA")

        from .totp_crypto import decrypt_secret
        pending_secret = decrypt_secret(pending_secret_enc)
        if not verify_totp_code(pending_secret, code):
            await security_service._log_security_event(
                user["id"], "2fa_setup_failed", {"reason": "invalid_code"}, False
            )
            raise HTTPException(status_code=400, detail="Неверный код")
        
        plain_codes, hashed_codes = SecurityService.generate_backup_codes()
        
        await db.users.update_one(
            {"id": user["id"]},
            {
                "$set": {
                    "two_factor_secret": pending_secret_enc,
                    "is_2fa_enabled": True,
                    "backup_codes": hashed_codes,
                    "2fa_enabled_at": datetime.now(timezone.utc).isoformat()
                },
                "$unset": {"pending_2fa_secret": ""}
            }
        )
        
        await security_service._log_security_event(
            user["id"], "2fa_enabled", {"backup_codes_count": len(plain_codes)}
        )
        
        return {
            "status": "enabled",
            "message": "2FA успешно активирована!",
            "backup_codes": plain_codes,
            "warning": "Сохраните резервные коды в безопасном месте!"
        }
    
    @security_router.post("/totp/verify")
    async def verify_totp(code: str, current_user: dict = Depends(get_current_user)):
        """Verify TOTP code"""
        from .totp_handler import verify_totp_code
        
        user = await db.users.find_one(
            build_user_query(current_user),
            {"_id": 0}
        )
        
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        
        if not user.get("is_2fa_enabled"):
            raise HTTPException(status_code=400, detail="2FA не активирована")
        
        secret = user.get("two_factor_secret")
        if not secret:
            raise HTTPException(status_code=500, detail="Ошибка конфигурации 2FA")

        from .totp_crypto import decrypt_secret
        secret = decrypt_secret(secret)
        if verify_totp_code(secret, code):
            await security_service._log_security_event(
                user["id"], "2fa_verification", {"method": "totp"}, True
            )
            return {"verified": True, "method": "totp"}
        
        if await security_service.verify_backup_code(user["id"], code):
            return {"verified": True, "method": "backup_code"}
        
        await security_service._log_security_event(
            user["id"], "2fa_verification", {"method": "totp"}, False
        )
        raise HTTPException(status_code=400, detail="Неверный код")
    
    @security_router.post("/totp/disable/start")
    async def start_disable_totp(current_user: dict = Depends(get_current_user)):
        """Start 2FA disable process - sends email code"""
        from .totp_handler import send_disable_2fa_email, pending_disable_requests
        import secrets
        import hashlib
        from datetime import datetime, timezone, timedelta
        
        user = await db.users.find_one(
            build_user_query(current_user),
            {"_id": 0}
        )
        
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        
        if not user.get("is_2fa_enabled"):
            raise HTTPException(status_code=400, detail="2FA не активирована")
        
        if not user.get("email"):
            raise HTTPException(status_code=400, detail="Email не привязан")
        
        email_code = secrets.token_hex(3).upper()
        request_id = secrets.token_hex(16)
        
        pending_disable_requests[request_id] = {
            "user_id": user["id"],
            "email_code_hash": hashlib.sha256(email_code.encode()).hexdigest(),
            "created_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=15)
        }
        
        email_sent = await send_disable_2fa_email(user["email"], email_code)
        if not email_sent:
            # Log the code for development/testing (won't send in restricted Resend mode)
            logger.warning(f"2FA disable code for {user['email']}: {email_code} (email delivery failed)")
        
        await security_service._log_security_event(
            user["id"], "2fa_disable_requested", {"email": user["email"]}
        )
        
        return {
            "status": "pending",
            "request_id": request_id,
            "message": "Код отправлен на email"
        }
    
    @security_router.post("/totp/disable/confirm")
    async def confirm_disable_totp(
        request_id: str,
        email_code: str,
        totp_code: str,
        current_user: dict = Depends(get_current_user)
    ):
        """Confirm 2FA disable with both codes"""
        from .totp_handler import verify_totp_code, pending_disable_requests
        import hashlib
        from datetime import datetime, timezone, timedelta
        
        user = await db.users.find_one(
            build_user_query(current_user),
            {"_id": 0}
        )
        
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        
        pending = pending_disable_requests.get(request_id)
        if not pending:
            raise HTTPException(status_code=400, detail="Запрос не найден или истёк")
        
        if pending["user_id"] != user["id"]:
            raise HTTPException(status_code=403, detail="Недостаточно прав")
        
        if datetime.now(timezone.utc) > pending["expires_at"]:
            del pending_disable_requests[request_id]
            raise HTTPException(status_code=400, detail="Запрос истёк")
        
        email_code_hash = hashlib.sha256(email_code.upper().encode()).hexdigest()
        if email_code_hash != pending["email_code_hash"]:
            await security_service._log_security_event(
                user["id"], "2fa_disable_failed", {"reason": "invalid_email_code"}, False
            )
            raise HTTPException(status_code=400, detail="Неверный код из email")
        
        secret = user.get("two_factor_secret")
        from .totp_crypto import decrypt_secret
        if not verify_totp_code(decrypt_secret(secret), totp_code):
            await security_service._log_security_event(
                user["id"], "2fa_disable_failed", {"reason": "invalid_totp"}, False
            )
            raise HTTPException(status_code=400, detail="Неверный код 2FA")
        
        await db.users.update_one(
            {"id": user["id"]},
            {
                "$set": {
                    "is_2fa_enabled": False,
                    "withdrawal_blocked_until": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()  # 24 hours lock after 2FA disable
                },
                "$unset": {
                    "two_factor_secret": "",
                    "backup_codes": "",
                    "pending_2fa_secret": ""
                }
            }
        )
        # 2FA off ends every session (with the 24 h withdrawal lock above)
        from core.token_revocation import revoke_all as _revoke_all
        await _revoke_all(db, {"id": user["id"]})
        
        del pending_disable_requests[request_id]
        
        await security_service._log_security_event(
            user["id"], "2fa_disabled", {"withdraw_locked_hours": 24}
        )
        
        # Schedule telegram notification for when withdrawal unlocks
        unlock_time = datetime.now(timezone.utc) + timedelta(hours=24)
        await db.scheduled_notifications.insert_one({
            "user_id": user["id"],
            "type": "withdrawal_unlocked",
            "scheduled_at": unlock_time.isoformat(),
            "sent": False,
            "created_at": datetime.now(timezone.utc).isoformat()
        })
        
        return {
            "status": "disabled",
            "message": "2FA отключена. Вывод заблокирован на 24 часа.",
            "withdraw_lock_hours": 24
        }
    
    # ==================== PASSKEY ROUTES ====================
    
    @security_router.post("/passkey/register/start")
    async def start_passkey_register(
        http_request: Request,
        device_name: str = "My Device",
        current_user: dict = Depends(get_current_user)
    ):
        """Start passkey registration"""
        from .passkey_handler import (
            RP_NAME, _resolve_webauthn_context,
            generate_registration_options, options_to_json, bytes_to_base64url,
            base64url_to_bytes, AuthenticatorSelectionCriteria,
            AuthenticatorAttachment, ResidentKeyRequirement,
            UserVerificationRequirement, PublicKeyCredentialDescriptor,
            AuthenticatorTransport
        )
        import secrets
        import json
        from datetime import datetime, timezone

        rp_id, origin = _resolve_webauthn_context(http_request)
        
        user = await db.users.find_one(
            build_user_query(current_user),
            {"_id": 0}
        )
        
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        
        user_id = user.get("id")
        username = user.get("username") or user.get("email") or user_id[:8]
        
        existing_passkeys = await db.passkeys.find(
            {"user_id": user_id},
            {"_id": 0, "credential_id": 1}
        ).to_list(20)
        
        exclude_credentials = [
            PublicKeyCredentialDescriptor(
                id=base64url_to_bytes(p["credential_id"]),
                transports=[AuthenticatorTransport.INTERNAL, AuthenticatorTransport.HYBRID]
            )
            for p in existing_passkeys
        ]
        
        options = generate_registration_options(
            rp_id=rp_id,
            rp_name=RP_NAME,
            user_id=user_id.encode(),
            user_name=username,
            user_display_name=user.get("display_name") or username,
            exclude_credentials=exclude_credentials,
            authenticator_selection=AuthenticatorSelectionCriteria(
                authenticator_attachment=AuthenticatorAttachment.PLATFORM,
                resident_key=ResidentKeyRequirement.PREFERRED,
                user_verification=UserVerificationRequirement.REQUIRED
            ),
            timeout=60000
        )
        
        challenge_id = secrets.token_hex(16)
        await _store_passkey_challenge(db, challenge_id, {
            "user_id": user_id,
            "challenge": bytes_to_base64url(options.challenge),
            "device_name": device_name,
            "created_at": datetime.now(timezone.utc),
        })
        
        options_json = json.loads(options_to_json(options))
        
        return {
            "challenge_id": challenge_id,
            "options": options_json
        }
    
    @security_router.post("/passkey/register/finish")
    async def finish_passkey_register(
        challenge_id: str,
        credential: dict,
        http_request: Request,
        device_name: str = "My Device",
        current_user: dict = Depends(get_current_user)
    ):
        """Finish passkey registration"""
        from .passkey_handler import (
            _resolve_webauthn_context,
            verify_registration_response, bytes_to_base64url, base64url_to_bytes
        )
        import secrets
        import traceback
        from datetime import datetime, timezone

        # The frontend posts `{credential: {...}}`. FastAPI treats the SOLE
        # `dict` parameter as the whole body, so `credential` is actually the
        # outer wrapper, not the WebAuthn credential. Unwrap if needed so the
        # webauthn library can find `.id`. Also accept the raw shape in case a
        # different client sends the credential directly.
        if isinstance(credential, dict) and "id" not in credential and isinstance(credential.get("credential"), dict):
            credential = credential["credential"]

        rp_id, origin = _resolve_webauthn_context(http_request)
        
        user = await db.users.find_one(
            build_user_query(current_user),
            {"_id": 0}
        )
        
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        
        pending = await _pop_passkey_challenge(db, challenge_id)
        if not pending:
            raise HTTPException(status_code=400, detail="Challenge не найден или истёк")
        
        if pending["user_id"] != user["id"]:
            raise HTTPException(status_code=403, detail="Недостаточно прав")
        
        try:
            # Defensive: ensure challenge is a str before decoding. In some
            # multi-worker setups MongoDB may rarely return a Binary subtype
            # for fields originally stored as str — coerce explicitly so the
            # webauthn lib never sees a non-bytes-like expected_challenge.
            stored_challenge = pending.get("challenge")
            if isinstance(stored_challenge, (bytes, bytearray, memoryview)):
                expected_challenge_bytes = bytes(stored_challenge)
            else:
                expected_challenge_bytes = base64url_to_bytes(str(stored_challenge))

            verification = verify_registration_response(
                credential=credential,
                expected_challenge=expected_challenge_bytes,
                expected_rp_id=str(rp_id),
                expected_origin=str(origin),
                require_user_verification=True
            )
            
            passkey_id = secrets.token_hex(16)
            passkey_doc = {
                "id": passkey_id,
                "user_id": user["id"],
                "credential_id": bytes_to_base64url(verification.credential_id),
                "public_key": bytes_to_base64url(verification.credential_public_key),
                "sign_count": verification.sign_count,
                "name": device_name or pending.get("device_name", "My Device"),
                "aaguid": bytes_to_base64url(verification.aaguid) if isinstance(verification.aaguid, (bytes, bytearray)) else (verification.aaguid if verification.aaguid else None),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "last_used": None
            }
            
            await db.passkeys.insert_one(passkey_doc)
            # Challenge already removed atomically by _pop_passkey_challenge.
            
            await security_service._log_security_event(
                user["id"],
                "passkey_registered",
                {"passkey_id": passkey_id, "device_name": passkey_doc["name"]}
            )
            
            return {
                "status": "registered",
                "passkey_id": passkey_id,
                "device_name": passkey_doc["name"],
                "message": "Passkey успешно зарегистрирован!"
            }
            
        except HTTPException:
            raise
        except Exception as e:
            # Log full traceback so VPS deployments can quickly identify which
            # library/function raised the underlying error (e.g. cbor2 vs
            # cryptography vs webauthn parsing). Without this the user only
            # sees the stringified error like "a bytes-like object is required,
            # not 'str'" with no line number.
            tb = traceback.format_exc()
            logger.error(
                "Passkey registration failed for user=%s rp_id=%s origin=%s err=%s\n%s",
                user.get("id"), rp_id, origin, e, tb,
            )
            await security_service._log_security_event(
                user["id"],
                "passkey_registration_failed",
                {"error": str(e), "traceback": tb[-2000:]},
                False
            )
            raise HTTPException(status_code=400, detail=f"Ошибка регистрации: {str(e)}")
    
    @security_router.post("/passkey/auth/start")
    async def start_passkey_auth(http_request: Request, current_user: dict = Depends(get_current_user)):
        """Start passkey authentication for withdrawal"""
        from .passkey_handler import (
            _resolve_webauthn_context,
            generate_authentication_options, options_to_json,
            bytes_to_base64url, base64url_to_bytes,
            PublicKeyCredentialDescriptor, AuthenticatorTransport,
            UserVerificationRequirement
        )
        import secrets
        import json
        from datetime import datetime, timezone

        rp_id, origin = _resolve_webauthn_context(http_request)
        
        user = await db.users.find_one(
            build_user_query(current_user),
            {"_id": 0}
        )
        
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        
        passkeys = await db.passkeys.find(
            {"user_id": user["id"]},
            {"_id": 0}
        ).to_list(20)
        
        if not passkeys:
            raise HTTPException(status_code=400, detail="Passkey не найден. Сначала зарегистрируйте устройство.")
        
        allow_credentials = [
            PublicKeyCredentialDescriptor(
                id=base64url_to_bytes(p["credential_id"]),
                transports=[AuthenticatorTransport.INTERNAL, AuthenticatorTransport.HYBRID]
            )
            for p in passkeys
        ]
        
        options = generate_authentication_options(
            rp_id=rp_id,
            allow_credentials=allow_credentials,
            user_verification=UserVerificationRequirement.REQUIRED,
            timeout=60000
        )
        
        challenge_id = secrets.token_hex(16)
        await _store_passkey_challenge(db, challenge_id, {
            "user_id": user["id"],
            "challenge": bytes_to_base64url(options.challenge),
            "type": "authentication",
            "created_at": datetime.now(timezone.utc),
        })
        
        options_json = json.loads(options_to_json(options))
        
        return {
            "challenge_id": challenge_id,
            "options": options_json
        }
    
    @security_router.post("/passkey/auth/finish")
    async def finish_passkey_auth(
        challenge_id: str,
        credential: dict,
        http_request: Request,
        current_user: dict = Depends(get_current_user)
    ):
        """Finish passkey authentication"""
        from .passkey_handler import (
            _resolve_webauthn_context,
            verify_authentication_response, base64url_to_bytes
        )
        from datetime import datetime, timezone

        # See note in /register/finish — same wrapper-vs-bare credential issue.
        if isinstance(credential, dict) and "id" not in credential and isinstance(credential.get("credential"), dict):
            credential = credential["credential"]

        rp_id, origin = _resolve_webauthn_context(http_request)
        
        user = await db.users.find_one(
            build_user_query(current_user),
            {"_id": 0}
        )
        
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        
        pending = await _pop_passkey_challenge(db, challenge_id)
        if not pending:
            raise HTTPException(status_code=400, detail="Challenge не найден или истёк")
        
        if pending["user_id"] != user["id"]:
            raise HTTPException(status_code=403, detail="Недостаточно прав")
        
        credential_id = credential.get("id")
        if not credential_id:
            raise HTTPException(status_code=400, detail="Credential ID не найден")
        
        passkey = await db.passkeys.find_one(
            {"user_id": user["id"], "credential_id": credential_id},
            {"_id": 0}
        )
        
        if not passkey:
            raise HTTPException(status_code=400, detail="Passkey не найден")
        
        try:
            verification = verify_authentication_response(
                credential=credential,
                expected_challenge=base64url_to_bytes(pending["challenge"]),
                expected_rp_id=rp_id,
                expected_origin=origin,
                credential_public_key=base64url_to_bytes(passkey["public_key"]),
                credential_current_sign_count=passkey.get("sign_count", 0),
                require_user_verification=True
            )
            
            await db.passkeys.update_one(
                {"id": passkey["id"]},
                {"$set": {
                    "sign_count": verification.new_sign_count,
                    "last_used": datetime.now(timezone.utc).isoformat()
                }}
            )
            # Challenge already removed atomically by _pop_passkey_challenge.
            
            await security_service._log_security_event(
                user["id"],
                "passkey_authentication",
                {"passkey_id": passkey["id"], "device_name": passkey.get("name")}
            )
            
            return {
                "verified": True,
                "passkey_id": passkey["id"],
                "device_name": passkey.get("name"),
                "message": "Passkey успешно верифицирован!"
            }
            
        except Exception as e:
            await security_service._log_security_event(
                user["id"],
                "passkey_authentication_failed",
                {"error": str(e)},
                False
            )
            raise HTTPException(status_code=400, detail=f"Ошибка аутентификации: {str(e)}")
    
    @security_router.get("/passkey/list")
    async def list_passkeys(current_user: dict = Depends(get_current_user)):
        """List all user's passkeys"""
        user = await db.users.find_one(
            build_user_query(current_user),
            {"_id": 0}
        )
        
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        
        passkeys = await db.passkeys.find(
            {"user_id": user["id"]},
            {"_id": 0, "public_key": 0}
        ).to_list(20)
        
        return {
            "passkeys": passkeys,
            "count": len(passkeys)
        }
    
    @security_router.delete("/passkey/{passkey_id}")
    async def delete_passkey(
        passkey_id: str,
        request: Request,
        current_user: dict = Depends(get_current_user)
    ):
        """Delete a passkey. If the user has 2FA enabled, require a fresh TOTP
        code (sent via `X-TOTP-Code` header or `totp_code` query param) — this
        ensures somebody with a stolen session cookie cannot silently unlink
        the user's hardware keys."""
        user = await db.users.find_one(
            build_user_query(current_user),
            {"_id": 0}
        )
        
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")

        # Require TOTP when 2FA is enabled.
        if user.get("is_2fa_enabled") and user.get("two_factor_secret"):
            totp_code = (
                request.headers.get("X-TOTP-Code")
                or request.headers.get("x-totp-code")
                or request.query_params.get("totp_code")
            )
            if not totp_code:
                raise HTTPException(
                    status_code=401,
                    detail="totp_required",
                )
            try:
                import pyotp
                from .totp_crypto import decrypt_secret
                totp = pyotp.TOTP(decrypt_secret(user["two_factor_secret"]))
                if not totp.verify(str(totp_code).strip(), valid_window=1):
                    # Allow backup codes as alternative
                    if not await security_service.verify_backup_code(user["id"], str(totp_code).strip()):
                        await security_service._log_security_event(
                            user["id"], "passkey_delete_failed",
                            {"reason": "invalid_totp"}, False
                        )
                        raise HTTPException(status_code=401, detail="Неверный код 2FA")
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(status_code=401, detail="Неверный код 2FA")

        passkey = await db.passkeys.find_one(
            {"id": passkey_id, "user_id": user["id"]},
            {"_id": 0}
        )
        
        if not passkey:
            raise HTTPException(status_code=404, detail="Passkey не найден")
        
        status = await security_service.get_security_status(user["id"])
        if status["passkeys_count"] == 1 and not status["is_2fa_enabled"]:
            raise HTTPException(
                status_code=400,
                detail="Нельзя удалить последний Passkey без включенной 2FA"
            )
        
        await db.passkeys.delete_one({"id": passkey_id})
        
        await security_service._log_security_event(
            user["id"],
            "passkey_deleted",
            {"passkey_id": passkey_id, "device_name": passkey.get("name")}
        )
        
        return {
            "status": "deleted",
            "passkey_id": passkey_id,
            "message": "Passkey удалён"
        }
    
    # ─────────────────────────────────────────────────────────────────────
    # Passkey LOGIN flow — unauthenticated endpoints that let the user sign
    # in with a registered hardware key instead of email+password. Returns
    # a fresh JWT just like /auth/login does; 2FA is INTENTIONALLY skipped
    # because the passkey assertion (with user_verification=required) is
    # itself strong multi-factor authentication.
    # ─────────────────────────────────────────────────────────────────────
    @security_router.post("/passkey/login/start")
    async def start_passkey_login(payload: dict, http_request: Request):
        """Begin passkey-based login.
        Body: {"email": "<user email>"}  — optional. When omitted, returns an
        empty `allowCredentials` list so the browser shows the OS-level
        passkey picker (discoverable / resident credentials)."""
        from .passkey_handler import (
            _resolve_webauthn_context,
            generate_authentication_options, options_to_json,
            bytes_to_base64url, base64url_to_bytes,
            PublicKeyCredentialDescriptor, AuthenticatorTransport,
            UserVerificationRequirement,
        )
        import secrets
        import json
        from datetime import datetime, timezone

        email = (payload or {}).get("email", "").strip()

        rp_id, _origin = _resolve_webauthn_context(http_request)

        user = None
        if email:
            # Email is stored AS-IS at registration; match case-insensitively so
            # users who typed `John@x.com` at signup can still log in via passkey
            # by entering `john@x.com`.
            import re as _re
            user = await db.users.find_one(
                {"email": {"$regex": f"^{_re.escape(email)}$", "$options": "i"}},
                {"_id": 0}
            )
            if not user:
                # Don't leak which emails exist — generic error.
                raise HTTPException(status_code=404, detail="passkey_not_available")

        allow_credentials = []
        if user:
            passkeys = await db.passkeys.find(
                {"user_id": user["id"]},
                {"_id": 0}
            ).to_list(20)
            if not passkeys:
                raise HTTPException(status_code=404, detail="passkey_not_available")
            allow_credentials = [
                PublicKeyCredentialDescriptor(
                    id=base64url_to_bytes(p["credential_id"]),
                    transports=[AuthenticatorTransport.INTERNAL, AuthenticatorTransport.HYBRID],
                )
                for p in passkeys
            ]

        options = generate_authentication_options(
            rp_id=rp_id,
            # Empty list when email not provided → browser opens system passkey
            # picker and the user just confirms biometrics. The credential id
            # returned will be looked up in /finish to identify the user.
            allow_credentials=allow_credentials,
            user_verification=UserVerificationRequirement.REQUIRED,
            timeout=60000,
        )

        challenge_id = secrets.token_hex(16)
        await _store_passkey_challenge(db, challenge_id, {
            # When user not yet known (discoverable login) we store None and
            # validate the resolved user matches the credential in /finish.
            "user_id": user["id"] if user else None,
            "challenge": bytes_to_base64url(options.challenge),
            "type": "login",
            "created_at": datetime.now(timezone.utc),
        })

        return {
            "challenge_id": challenge_id,
            "options": json.loads(options_to_json(options)),
        }

    @security_router.post("/passkey/login/finish")
    async def finish_passkey_login(payload: dict, http_request: Request):
        """Finish passkey-based login. Body: {challenge_id, credential, [email]}.
        `email` is optional — when omitted, the user is identified by the
        credential id returned from the authenticator (discoverable login).
        On success returns the same shape as /auth/login: {token, user, ...}."""
        from .passkey_handler import (
            _resolve_webauthn_context,
            verify_authentication_response, base64url_to_bytes,
        )
        from auth_handler import create_token, rotate_user_session
        from datetime import datetime, timezone

        challenge_id = (payload or {}).get("challenge_id")
        credential = (payload or {}).get("credential") or {}
        email = (payload or {}).get("email", "").strip()

        if isinstance(credential, dict) and "id" not in credential and isinstance(credential.get("credential"), dict):
            credential = credential["credential"]

        if not (challenge_id and credential):
            raise HTTPException(status_code=400, detail="missing_fields")

        rp_id, origin = _resolve_webauthn_context(http_request)

        credential_id = credential.get("id")
        if not credential_id:
            raise HTTPException(status_code=400, detail="Credential ID не найден")

        pending = await _pop_passkey_challenge(db, challenge_id)
        if not pending:
            raise HTTPException(status_code=400, detail="Challenge не найден или истёк")

        # Locate the passkey by credential_id — this also tells us WHICH user
        # owns it for the discoverable-credentials flow.
        passkey = await db.passkeys.find_one(
            {"credential_id": credential_id},
            {"_id": 0}
        )
        if not passkey:
            raise HTTPException(status_code=400, detail="Passkey не найден")

        # If the start call narrowed the search to a specific user (email
        # provided), make sure the credential belongs to that user.
        if pending.get("user_id") and pending["user_id"] != passkey["user_id"]:
            raise HTTPException(status_code=403, detail="Недостаточно прав")

        user = await db.users.find_one({"id": passkey["user_id"]}, {"_id": 0})
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")

        # When email was supplied as a hint, double-check it matches (CI).
        if email:
            stored_email = (user.get("email") or "").strip()
            if stored_email.lower() != email.lower():
                raise HTTPException(status_code=403, detail="Недостаточно прав")

        try:
            verification = verify_authentication_response(
                credential=credential,
                expected_challenge=base64url_to_bytes(pending["challenge"]),
                expected_rp_id=str(rp_id),
                expected_origin=str(origin),
                credential_public_key=base64url_to_bytes(passkey["public_key"]),
                credential_current_sign_count=passkey.get("sign_count", 0),
                require_user_verification=True,
            )
        except Exception as e:
            import traceback
            logger.error(
                "Passkey login failed for user=%s rp_id=%s err=%s\n%s",
                user.get("id"), rp_id, e, traceback.format_exc(),
            )
            await security_service._log_security_event(
                user["id"], "passkey_login_failed", {"error": str(e)}, False
            )
            raise HTTPException(status_code=400, detail=f"Ошибка аутентификации: {str(e)}")

        await db.passkeys.update_one(
            {"id": passkey["id"]},
            {"$set": {
                "sign_count": verification.new_sign_count,
                "last_used": datetime.now(timezone.utc).isoformat(),
            }}
        )

        # Issue fresh JWT — passkey login is strong auth, NO 2FA step.
        sid = await rotate_user_session(db, {"id": user["id"]})
        token = create_token(data={"sub": user.get("email") or user.get("username")}, session_id=sid)

        await security_service._log_security_event(
            user["id"], "passkey_login_success",
            {"passkey_id": passkey["id"], "device_name": passkey.get("name")},
        )

        return {
            "status": "ok",
            "token": token,
            "user": {
                "id": user["id"],
                "username": user.get("username"),
                "email": user.get("email"),
                "avatar": user.get("avatar"),
                "is_admin": bool(user.get("is_admin")),
            },
        }
    
    # ─────────────────────────────────────────────────────────────────────
    # Withdrawal passkey-verification flow.
    #
    # When the user has at least one passkey registered, /api/withdraw will
    # additionally require a fresh passkey assertion BEFORE accepting the
    # TOTP code. The frontend calls /withdraw/start to get an assertion
    # challenge, prompts the platform authenticator, then submits the
    # signed assertion to /withdraw/verify which mints a short-lived token
    # (`withdraw_pk_token`) that must be passed along with the TOTP code
    # to /api/withdraw.
    # ─────────────────────────────────────────────────────────────────────
    @security_router.post("/passkey/withdraw/start")
    async def start_passkey_withdraw(
        http_request: Request,
        current_user: dict = Depends(get_current_user)
    ):
        from .passkey_handler import (
            _resolve_webauthn_context,
            generate_authentication_options, options_to_json,
            bytes_to_base64url, base64url_to_bytes,
            PublicKeyCredentialDescriptor, AuthenticatorTransport,
            UserVerificationRequirement,
        )
        import secrets
        import json
        from datetime import datetime, timezone

        rp_id, _origin = _resolve_webauthn_context(http_request)

        user = await db.users.find_one(build_user_query(current_user), {"_id": 0})
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")

        passkeys = await db.passkeys.find({"user_id": user["id"]}, {"_id": 0}).to_list(20)
        if not passkeys:
            # The frontend should not have called this; respond with the
            # specific code so it can fall back to the TOTP-only flow.
            raise HTTPException(status_code=400, detail="no_passkey_registered")

        allow_credentials = [
            PublicKeyCredentialDescriptor(
                id=base64url_to_bytes(p["credential_id"]),
                transports=[AuthenticatorTransport.INTERNAL, AuthenticatorTransport.HYBRID],
            )
            for p in passkeys
        ]
        options = generate_authentication_options(
            rp_id=rp_id,
            allow_credentials=allow_credentials,
            user_verification=UserVerificationRequirement.REQUIRED,
            timeout=60000,
        )

        challenge_id = secrets.token_hex(16)
        await _store_passkey_challenge(db, challenge_id, {
            "user_id": user["id"],
            "challenge": bytes_to_base64url(options.challenge),
            "type": "withdraw",
            "created_at": datetime.now(timezone.utc),
        })

        return {
            "challenge_id": challenge_id,
            "options": json.loads(options_to_json(options)),
        }

    @security_router.post("/passkey/withdraw/verify")
    async def verify_passkey_withdraw(
        payload: dict,
        http_request: Request,
        current_user: dict = Depends(get_current_user)
    ):
        """Verify the passkey assertion and mint a one-shot withdraw token.

        The returned `withdraw_pk_token` must be sent to /api/withdraw within
        5 minutes. It is single-use and bound to this user."""
        from .passkey_handler import (
            _resolve_webauthn_context,
            verify_authentication_response, base64url_to_bytes,
        )
        import secrets
        from datetime import datetime, timezone, timedelta

        challenge_id = (payload or {}).get("challenge_id")
        credential = (payload or {}).get("credential") or {}

        if isinstance(credential, dict) and "id" not in credential and isinstance(credential.get("credential"), dict):
            credential = credential["credential"]

        if not (challenge_id and credential):
            raise HTTPException(status_code=400, detail="missing_fields")

        rp_id, origin = _resolve_webauthn_context(http_request)

        user = await db.users.find_one(build_user_query(current_user), {"_id": 0})
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")

        pending = await _pop_passkey_challenge(db, challenge_id)
        if not pending or pending.get("type") != "withdraw" or pending.get("user_id") != user["id"]:
            raise HTTPException(status_code=400, detail="Challenge не найден или истёк")

        credential_id = credential.get("id")
        passkey = await db.passkeys.find_one(
            {"user_id": user["id"], "credential_id": credential_id}, {"_id": 0}
        )
        if not passkey:
            raise HTTPException(status_code=400, detail="Passkey не найден")

        try:
            verification = verify_authentication_response(
                credential=credential,
                expected_challenge=base64url_to_bytes(pending["challenge"]),
                expected_rp_id=str(rp_id),
                expected_origin=str(origin),
                credential_public_key=base64url_to_bytes(passkey["public_key"]),
                credential_current_sign_count=passkey.get("sign_count", 0),
                require_user_verification=True,
            )
        except Exception as e:
            import traceback
            logger.error("Passkey withdraw verify failed user=%s err=%s\n%s",
                         user["id"], e, traceback.format_exc())
            raise HTTPException(status_code=400, detail=f"Ошибка аутентификации: {str(e)}")

        await db.passkeys.update_one(
            {"id": passkey["id"]},
            {"$set": {
                "sign_count": verification.new_sign_count,
                "last_used": datetime.now(timezone.utc).isoformat(),
            }}
        )

        # Mint one-shot token, valid 5 minutes.
        wpk_token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        await db.withdraw_pk_tokens.insert_one({
            "_id": wpk_token,
            "user_id": user["id"],
            "passkey_id": passkey["id"],
            "expires_at": expires_at,
            "created_at": datetime.now(timezone.utc),
        })

        # Best-effort TTL index — runs once.
        try:
            await db.withdraw_pk_tokens.create_index("expires_at", expireAfterSeconds=0)
        except Exception:
            pass

        return {"withdraw_pk_token": wpk_token, "expires_at": expires_at.isoformat()}
    
    return security_router
