import os
import logging
from datetime import datetime, timedelta, timezone
from core.dtutils import to_aware
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, EmailStr
from passlib.context import CryptContext
import jwt  # PyJWT (python-jose removed: unpatched CVE)
from jwt import PyJWTError as JWTError
from typing import Optional
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# --- КОНФИГУРАЦИЯ ---
# S1: pull secret from security_middleware (already sanitized + randomized if missing)
from security_middleware import (
    limiter, validate_password_strength,
    check_login_lockout_async, record_login_failure_async, record_login_success_async,
)
SECRET_KEY = os.environ.get("JWT_SECRET_KEY") or ""  # set by server.py before import-time usage
if not SECRET_KEY:
    # Fallback: generate own if server.py hasn't initialized yet
    from security_middleware import get_or_generate_jwt_secret
    SECRET_KEY = get_or_generate_jwt_secret()
ALGORITHM = "HS256"

def _clean_env(name: str) -> str:
    """Read an env var and strip whitespace + accidental surrounding quotes.
    A stray quote/newline in GOOGLE_CLIENT_ID/SECRET makes Google reject the
    token exchange with 'invalid_client (The OAuth client was not found.)'
    even though the value 'looks' correct in the .env file."""
    import re as _re
    v = os.getenv(name, "") or ""
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        v = v[1:-1].strip()
    # Google client_id / client_secret NEVER contain whitespace. A value that
    # got wrapped across lines or picked up a stray space/tab/newline on paste
    # (an extremely common .env copy-paste mistake — the frontend value was
    # seen truncated as "...03b>") would otherwise be forwarded to Google
    # verbatim → 'invalid_client (The OAuth client was not found.)'. Collapsing
    # ALL internal whitespace repairs a wrapped value so it resolves to the
    # real, single-line credential.
    v = _re.sub(r"\s+", "", v)
    return v


def _mask_secret(v: str) -> str:
    """Mask a credential for safe logging: keep first 8 + last 4 chars."""
    if not v:
        return "<empty>"
    if len(v) <= 14:
        return f"{v[:2]}…({len(v)} chars)"
    return f"{v[:8]}…{v[-4:]} (len={len(v)})"


def _mask_email(v: str) -> str:
    """Mask an email for safe logging: keep first char + domain."""
    try:
        name, _, dom = (v or "").partition("@")
        if not dom:
            return "<no-email>"
        head = name[:1] if name else "?"
        return f"{head}***@{dom}"
    except Exception:
        return "<email>"


# Machine-readable error codes for Google OAuth so the FRONTEND can render a
# friendly, localized message instead of Google's raw `invalid_client`.
def _google_error(code: str, google_reason: str = "") -> "HTTPException":
    """Build an HTTPException whose detail carries a stable `code` the frontend
    maps to a localized message, plus the raw Google reason for logs/debug."""
    status_map = {
        "google_config_error": 401,      # invalid_client / unauthorized_client / redirect_uri_mismatch
        "google_session_expired": 401,   # invalid_grant (code expired / reused / verifier mismatch)
        "google_state_invalid": 400,     # our CSRF state expired/reused
        "google_no_id_token": 401,
        "google_no_email": 400,
        "google_not_configured": 503,
        "google_generic": 401,
    }
    return HTTPException(
        status_code=status_map.get(code, 401),
        detail={"code": code, "reason": google_reason or code},
    )

GOOGLE_CLIENT_ID = _clean_env("GOOGLE_CLIENT_ID")  # Add to .env
GOOGLE_CLIENT_SECRET = _clean_env("GOOGLE_CLIENT_SECRET")  # Add to .env


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
auth_router = APIRouter(prefix="/auth", tags=["Auth"])


# Meta Conversions API (CAPI) — server-side Lead tracking on registration
from meta_capi import send_capi_registration_event


def parse_client_info(request: Optional[Request]):
    """Extract client IP, device and browser from a FastAPI Request.
    Returns a dict compatible with the login_history entries used across auth."""
    if request is None:
        return {"ip": "unknown", "device": "Unknown", "browser": "Unknown", "user_agent": "unknown"}

    client_ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else "unknown")
    if client_ip and "," in client_ip:
        client_ip = client_ip.split(",")[0].strip()

    user_agent = request.headers.get("User-Agent", "unknown")

    device = "Desktop"
    if "iPhone" in user_agent or "iPad" in user_agent:
        device = "iOS"
    elif "Mobile" in user_agent or "Android" in user_agent:
        device = "Mobile"
    elif "Tablet" in user_agent:
        device = "Tablet"

    browser = "Unknown"
    ua_lower = user_agent.lower()
    if "edg/" in ua_lower or "edge" in ua_lower:
        browser = "Edge"
    elif "opr/" in ua_lower or "opera" in ua_lower:
        browser = "Opera"
    elif "yabrowser" in ua_lower:
        browser = "Yandex"
    elif "chrome" in ua_lower and "safari" in ua_lower:
        browser = "Chrome"
    elif "firefox" in ua_lower:
        browser = "Firefox"
    elif "safari" in ua_lower:
        browser = "Safari"

    return {
        "ip": client_ip,
        "device": device,
        "browser": browser,
        "user_agent": (user_agent or "unknown")[:200],
    }


def build_registration_device_fields(request: Optional[Request]):
    """Return ($set fields, login_history entry) to persist device/IP at registration."""
    info = parse_client_info(request)
    login_entry = {
        "ip": info["ip"],
        "device": info["device"],
        "browser": info["browser"],
        "user_agent": info["user_agent"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    set_fields = {
        "last_ip": info["ip"],
        "last_device": info["device"],
        "last_browser": info["browser"],
        "last_user_agent": info["user_agent"],
    }
    return set_fields, login_entry


# ─────────────────────────── REFERRAL SYSTEM ───────────────────────────
# A user's referral code IS their public UUID `id` (used in ?ref=USER_ID links).
# `referrerId` is bound ONCE at registration and can never change afterwards.
REFERRAL_RATE = 0.05  # 5% of the trade total goes to the referrer


async def resolve_referrer_id(db, referral_code, new_email=None, new_wallet=None):
    """Validate a referral code (= referrer's UUID id) and return the referrer id.
    Returns None if empty/invalid/self-referral."""
    if not referral_code:
        return None
    code = str(referral_code).strip()
    if not code:
        return None
    ref = await db.users.find_one({"id": code}, {"_id": 0, "id": 1, "email": 1, "wallet_address": 1})
    if not ref:
        return None
    # Prevent self-referral (matching by email or wallet of the newly-created user)
    if new_email and ref.get("email") and ref.get("email") == new_email:
        return None
    if new_wallet and ref.get("wallet_address") and ref.get("wallet_address") == new_wallet:
        return None
    return ref.get("id")


def referral_fields(referrer_id):
    """Default referral fields merged into a freshly-created user document.

    `partner_ref_id` mirrors the referrer id (the value carried by a Telegram
    Mini App `startapp=<id>` link) so a partner can track the users they bring;
    `partner_joined_at` records the first entry via the (partner) referral link.
    """
    from datetime import datetime, timezone
    joined = datetime.now(timezone.utc).isoformat() if referrer_id else None
    return {
        "referrerId": referrer_id,
        "totalEarnedFromReferrals": 0.0,
        "contributedToReferrer": 0.0,
        "partner_ref_id": referrer_id,
        "partner_joined_at": joined,
        "partner_task_completed": False,
        # True → this user was NEW (registered) via the referral link. Existing
        # users bound later (POST /api/partner/bind) get False.
        "partner_is_new": bool(referrer_id),
    }

# --- USERNAME VALIDATION (P1.1) ---
USERNAME_MIN_LEN = 3
USERNAME_MAX_LEN = 20


def validate_username(username: str) -> str:
    """Validate and normalize a username. Enforces length 3..20 characters.
    Returns the trimmed username. Raises HTTPException(400) on failure."""
    name = (username or "").strip()
    if len(name) < USERNAME_MIN_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"Никнейм должен содержать минимум {USERNAME_MIN_LEN} символа",
        )
    if len(name) > USERNAME_MAX_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"Никнейм не должен превышать {USERNAME_MAX_LEN} символов",
        )
    return name


def username_ci_query(name: str) -> dict:
    """Return a MongoDB filter that matches the given username case-INSENSITIVELY.

    Uniqueness check uses `^name$` with case-insensitive option, so that
    "User", "user" and "USER" are treated as the same nickname.
    """
    import re
    # Anchor and escape to avoid partial-match collisions and ReDoS.
    return {"username": {"$regex": f"^{re.escape(name)}$", "$options": "i"}}

# --- МОДЕЛИ ДАННЫХ ---
class EmailRegister(BaseModel):
    email: EmailStr
    password: str
    username: str
    visitor_id: Optional[str] = None
    turnstile_token: Optional[str] = None
    fbp: Optional[str] = None
    fbc: Optional[str] = None

class EmailRegisterInitiate(BaseModel):
    email: EmailStr
    password: str
    username: str
    visitor_id: Optional[str] = None
    turnstile_token: Optional[str] = None
    referral_code: Optional[str] = None
    fbp: Optional[str] = None
    fbc: Optional[str] = None

class EmailVerifyCode(BaseModel):
    email: EmailStr
    code: str
    visitor_id: Optional[str] = None
    turnstile_token: Optional[str] = None
    referral_code: Optional[str] = None
    fbp: Optional[str] = None
    fbc: Optional[str] = None

class EmailLogin(BaseModel):
    email: str  # Changed from EmailStr to str to allow username
    password: str
    visitor_id: Optional[str] = None
    turnstile_token: Optional[str] = None

class GoogleAuth(BaseModel):
    credential: str  # Google ID token
    referral_code: Optional[str] = None
    fbp: Optional[str] = None
    fbc: Optional[str] = None

class WalletAuth(BaseModel):
    address: str

class TelegramLogin(BaseModel):
    init_data: str  # raw window.Telegram.WebApp.initData query string

class UsernameUpdate(BaseModel):
    username: str


# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def generate_avatar_from_initials(name: str) -> str:
    """Генерирует SVG аватар из первых букв имени"""
    if not name:
        name = "U"
    
    # Берем первую букву (или две, если есть пробел)
    parts = name.strip().split()
    if len(parts) >= 2:
        initials = (parts[0][0] + parts[1][0]).upper()
    else:
        initials = name[0].upper()
    
    # Генерируем цвет на основе имени
    hash_val = sum(ord(c) for c in name)
    colors = [
        "#00F0FF",  # cyber-cyan
        "#B026FF",  # neon-purple  
        "#FF6B9D",  # pink
        "#FFB800",  # amber
        "#00FF88",  # green
    ]
    color = colors[hash_val % len(colors)]
    
    # SVG аватар
    svg = f'''<svg width="100" height="100" xmlns="http://www.w3.org/2000/svg">
        <rect width="100" height="100" fill="{color}"/>
        <text x="50" y="50" font-family="Arial" font-size="40" font-weight="bold" 
              fill="#000" text-anchor="middle" dominant-baseline="central">{initials}</text>
    </svg>'''
    
    return f"data:image/svg+xml;base64,{__import__('base64').b64encode(svg.encode()).decode()}"

def create_token(data: dict, session_id: Optional[str] = None):
    """Create JWT. If session_id is provided, embed `sid` claim — used by
    server.get_current_user to enforce single-active-session per account.
    Old sessions become invalid the moment a new login rotates the user's session_id.

    Tokens are issued with a very long TTL (365 days) so the user is NOT
    silently logged out on JWT expiry — the only ways to end a session are
    now: (a) the user clicks "Log out"; (b) a login from another device
    rotates `session_id` (single-session enforcement); (c) admin ban.
    """
    expire = datetime.now(timezone.utc) + timedelta(days=int(os.environ.get("JWT_EXPIRE_DAYS", "30")))   # was 365
    to_encode = data.copy()
    import time as _time
    to_encode.update({"exp": expire, "iat": _time.time() + 0.001})      # issue time: lets us revoke older tokens
    if session_id:
        to_encode["sid"] = session_id
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


async def rotate_user_session(db, user_filter: dict) -> str:
    """Generate a new session_id, persist it on the user doc, and return it.
    Also pushes a `force_logout` WebSocket frame to the previous session (best-effort)
    so the old device disconnects immediately instead of waiting for its next REST call."""
    import uuid as _uuid
    import traceback as _tb
    new_sid = _uuid.uuid4().hex
    try:
        _stack = "".join(_tb.format_stack(limit=8))
        logger.warning("[SESSION_ROTATE] filter=%s new_sid=%s stack=%s", user_filter, new_sid[:8], _stack[-800:])
    except Exception:
        pass
    # Best-effort: notify the previously-connected device to log out NOW.
    try:
        from server import manager  # lazy to avoid circular import
        prev = await db.users.find_one(user_filter, {"_id": 0, "id": 1, "email": 1, "wallet_address": 1, "username": 1, "session_id": 1})
        if prev:
            keys = [prev.get("id"), prev.get("email"), prev.get("wallet_address"), prev.get("username")]
            for k in keys:
                if not k:
                    continue
                try:
                    await manager.send_personal({"type": "force_logout", "reason": "session_invalidated"}, k)
                except Exception:
                    pass
    except Exception:
        pass
    await db.users.update_one(user_filter, {"$set": {"session_id": new_sid}})
    return new_sid


def verify_telegram_init_data(init_data: str, bot_token: str, max_age: int = 24 * 3600) -> Optional[dict]:
    """
    Verify Telegram Mini App initData per https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app

    Returns parsed `user` dict on success, None on signature mismatch / malformed
    payload / STALE data (auth_date older than `max_age` seconds — replay guard).
    """
    import hmac
    import hashlib
    import json
    import time as _time
    from urllib.parse import parse_qsl

    if not init_data or not bot_token:
        return None

    parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = parsed.pop("hash", None)
    if not received_hash:
        return None

    # Build alphabetically-sorted data_check_string
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated_hash, received_hash):
        return None

    # Replay protection: a valid signature is not enough — the payload must be
    # FRESH. auth_date is inside the signed data, so a forged value breaks the
    # HMAC above. Reject missing/stale/future (beyond 5-min skew) timestamps.
    try:
        auth_date = int(parsed.get("auth_date", "0"))
    except (ValueError, TypeError):
        auth_date = 0
    if auth_date <= 0:
        return None
    age = int(_time.time()) - auth_date
    if age > max_age or age < -300:
        return None

    user_json = parsed.get("user")
    if not user_json:
        return None
    try:
        return json.loads(user_json)
    except json.JSONDecodeError:
        return None

# Зависимость для получения текущего пользователя через Bearer token
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from auth_cookie import CookieOrBearer
security = CookieOrBearer(auto_error=True)

async def get_current_user_local(credentials: HTTPAuthorizationCredentials = Depends(security)):
    from server import db
    try:
        token = credentials.credentials
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        token_sid = payload.get("sid")
        
        # Ищем по email, username или wallet_address
        user = await db.users.find_one({
            "$or": [
                {"email": user_id},
                {"username": user_id},
                {"wallet_address": user_id}
            ]
        })
        if user is None:
            raise HTTPException(status_code=401, detail="User not found")
        # NOTE: single-session enforcement intentionally DISABLED — a token
        # keeps working until the user explicitly logs out (no self-kick when
        # another login rotates session_id). See core/dependencies.py.
        current_sid = user.get("session_id")
        if token_sid and not current_sid:
            await db.users.update_one({"_id": user["_id"]}, {"$set": {"session_id": token_sid}})
        return user
    except JWTError:
        raise HTTPException(status_code=401, detail="Could not validate credentials")

# --- ЭНДПОИНТЫ ---

# 1. Инициация регистрации - отправка кода на email
@auth_router.post("/register/initiate")
async def register_initiate(data: EmailRegisterInitiate, request: Request):
    """Start registration - send verification code to email"""
    from server import db
    from email_service import (
        generate_verification_code, store_verification_code,
        send_email_with_code_async,
    )
    
    # Проверка уникальности
    if await db.users.find_one({"email": data.email}):
        raise HTTPException(status_code=400, detail="Email уже зарегистрирован")
    data.username = validate_username(data.username)
    if await db.users.find_one(username_ci_query(data.username)):
        raise HTTPException(status_code=400, detail="Этот Username уже занят")
    
    # S4: enforce password strength (single unified check + message)
    validate_password_strength(data.password)
    
    # Хешируем пароль
    password_hash = pwd_context.hash(data.password)
    
    # Генерируем код
    code = generate_verification_code()
    
    # Сохраняем данные
    store_verification_code(data.email, code, data.username, password_hash)
    
    # Отправляем email (async путь умеет ходить через Resend)
    email_sent = await send_email_with_code_async(data.email, code, "ru", "verification")
    
    if not email_sent:
        # Если SMTP не настроен, создаем пользователя сразу (для разработки)
        import uuid
        avatar = generate_avatar_from_initials(data.username)
        _dev_fields, _login_entry = build_registration_device_fields(request)
        _referrer_id = await resolve_referrer_id(db, getattr(data, "referral_code", None), new_email=data.email)
        user = {
            "id": str(uuid.uuid4()),
            "username": data.username,
            "display_name": data.username,
            "email": data.email,
            "hashed_password": password_hash,
            "wallet_address": None,
            "raw_address": None,
            "avatar": avatar,
            "balance_ton": 0.0,
            "language": "ru",
            "level": "novice",
            "xp": 0,
            "total_turnover": 0,
            "total_income": 0,
            "plots_owned": [],
            "businesses_owned": [],
            "is_admin": False,
            "email_verified": True,  # Auto-verified if SMTP not configured
            "registration_method": "email",
            "created_at": datetime.now(timezone.utc),
            "last_login": datetime.now(timezone.utc),
            **_dev_fields,
            **referral_fields(_referrer_id),
            "login_history": [_login_entry],
        }
        
        await db.users.insert_one(user)
        try:
            import analytics
            _rm = user.get("registration_method") or "email"
            await analytics.track(user["id"], "register", channel=_rm)
            await analytics.mark_active(user["id"])
        except Exception as _ae:
            logger.debug(f"analytics register hook failed: {_ae}")
        try:
            from b2b_partners import tag_user_with_partner
            await tag_user_with_partner(db, user["id"], getattr(data, "referral_code", None))
        except Exception:
            pass
        _sid = await rotate_user_session(db, {"id": user["id"]})
        token = create_token({"sub": data.email}, session_id=_sid)

        # Meta CAPI: fire Lead event (fire-and-forget)
        await send_capi_registration_event(
            user, request,
            fbp=getattr(data, "fbp", None), fbc=getattr(data, "fbc", None),
        )

        return {
            "status": "registered",
            "token": token,
            "type": "bearer",
            "user": {
                "id": user["id"],
                "username": user["username"],
                "email": user["email"],
                "avatar": user["avatar"],
                "display_name": user["display_name"],
                "balance_ton": user["balance_ton"]
            },
            "message": "SMTP не настроен - регистрация без верификации"
        }
    
    return {
        "status": "verification_sent",
        "message": "Код подтверждения отправлен на email"
    }

# 1.1 Подтверждение email и завершение регистрации
@auth_router.post("/register/verify")
async def register_verify(data: EmailVerifyCode, request: Request):
    """Verify email code and complete registration"""
    from server import db
    from email_service import verify_email_code
    from antifraud import record_event as antifraud_record_event
    import uuid
    
    # Проверяем код
    success, message, user_data = verify_email_code(data.email, data.code)
    
    if not success:
        error_messages = {
            "no_code_requested": "Код не был запрошен. Пройдите регистрацию заново.",
            "code_expired": "Код истёк. Пройдите регистрацию заново.",
            "too_many_attempts": "Слишком много попыток. Пройдите регистрацию заново.",
            "invalid_code": "Неверный код"
        }
        raise HTTPException(status_code=400, detail=error_messages.get(message, message))
    
    # Проверяем еще раз уникальность (на случай если кто-то зарегистрировался пока ждали)
    if await db.users.find_one({"email": data.email}):
        raise HTTPException(status_code=400, detail="Email уже зарегистрирован")
    if await db.users.find_one(username_ci_query(user_data["username"])):
        raise HTTPException(status_code=400, detail="Этот Username уже занят")
    
    # Создаем пользователя
    avatar = generate_avatar_from_initials(user_data["username"])

    _dev_fields, _login_entry = build_registration_device_fields(request)
    _referrer_id = await resolve_referrer_id(db, getattr(data, "referral_code", None), new_email=data.email)

    user = {
        "id": str(uuid.uuid4()),
        "username": user_data["username"],
        "display_name": user_data["username"],
        "email": data.email,
        "hashed_password": user_data["password_hash"],
        "wallet_address": None,
        "raw_address": None,
        "avatar": avatar,
        "balance_ton": 0.0,
        "language": "ru",
        "level": "novice",
        "xp": 0,
        "total_turnover": 0,
        "total_income": 0,
        "plots_owned": [],
        "businesses_owned": [],
        "is_admin": False,
        "email_verified": True,
        "registration_method": "email",
        "created_at": datetime.now(timezone.utc),
        "last_login": datetime.now(timezone.utc),
        **_dev_fields,
        **referral_fields(_referrer_id),
        "login_history": [_login_entry],
    }
    
    await db.users.insert_one(user)
    try:
        import analytics
        _rm = user.get("registration_method") or "email"
        await analytics.track(user["id"], "register", channel=_rm)
        await analytics.mark_active(user["id"])
    except Exception as _ae:
        logger.debug(f"analytics register hook failed: {_ae}")
    try:
        from b2b_partners import tag_user_with_partner
        await tag_user_with_partner(db, user["id"], getattr(data, "referral_code", None))
    except Exception:
        pass
    _sid = await rotate_user_session(db, {"id": user["id"]})
    token = create_token({"sub": data.email}, session_id=_sid)

    # If a Referral Rally campaign is currently active, drop the in-app
    # announcement into this user's notification center so they see it on
    # first visit (in addition to the modal). See promo_broadcast.
    try:
        from promo_broadcast import maybe_insert_active_promo_notif_for_user
        await maybe_insert_active_promo_notif_for_user(db, user["id"])
    except Exception as _e:
        logger.debug(f"promo notif at register_verify failed: {_e}")

    # Anti-multi-account: verify Turnstile + record fingerprint (best-effort)
    try:
        from antifraud import record_event as antifraud_record_event, verify_turnstile, get_client_ip
        ts_result = await verify_turnstile(getattr(data, "turnstile_token", None), get_client_ip(request))
        await antifraud_record_event(
            db,
            event_type="register",
            request=request,
            user=user,
            visitor_id=getattr(data, "visitor_id", None),
            turnstile=ts_result,
        )
    except Exception as e:
        logger.warning("antifraud.register_verify failed: %s", e)

    # Meta CAPI: fire Lead event (fire-and-forget)
    await send_capi_registration_event(
        user, request,
        fbp=getattr(data, "fbp", None), fbc=getattr(data, "fbc", None),
    )

    return {
        "token": token,
        "type": "bearer",
        "user": {
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "avatar": user["avatar"],
            "display_name": user["display_name"],
            "balance_ton": user["balance_ton"]
        }
    }


@auth_router.post("/logout")
async def logout():
    """F7: clear the httpOnly session + CSRF cookies. Bearer/localStorage clients
    additionally drop their token client-side."""
    from fastapi.responses import JSONResponse
    from auth_cookie import clear_auth_cookies
    resp = JSONResponse(content={"status": "ok"})
    clear_auth_cookies(resp)
    return resp


# 1.2 Старая регистрация (для совместимости) - теперь редиректит на initiate
@auth_router.post("/register")
async def register(data: EmailRegister, request: Request):
    from server import db
    from antifraud import record_event as antifraud_record_event
    import uuid

    # S4: enforce password strength on direct register as well
    validate_password_strength(data.password)

    # Проверка принятия политики
    if hasattr(data, 'agreement_accepted') and not data.agreement_accepted:
        raise HTTPException(status_code=400, detail="Необходимо принять пользовательское соглашение")
    
    # Проверка уникальности
    if await db.users.find_one({"email": data.email}):
        raise HTTPException(status_code=400, detail="Email уже зарегистрирован")
    data.username = validate_username(data.username)
    if await db.users.find_one(username_ci_query(data.username)):
        raise HTTPException(status_code=400, detail="Этот Username уже занят")
    
    # Генерируем аватар из инициалов
    avatar = generate_avatar_from_initials(data.username)
    
    device_fp = getattr(data, 'device_fingerprint', '') or ''
    
    user = {
        "id": str(uuid.uuid4()),
        "username": data.username,
        "display_name": data.username,
        "email": data.email,
        "hashed_password": pwd_context.hash(data.password),
        "wallet_address": None,
        "raw_address": None,
        "avatar": avatar,
        "balance_ton": 0.0,
        "language": "ru",
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
        "device_fingerprint": device_fp,
        "created_at": datetime.now(timezone.utc),
        "last_login": datetime.now(timezone.utc)
    }
    
    await db.users.insert_one(user)
    try:
        import analytics
        _rm = user.get("registration_method") or "email"
        await analytics.track(user["id"], "register", channel=_rm)
        await analytics.mark_active(user["id"])
    except Exception as _ae:
        logger.debug(f"analytics register hook failed: {_ae}")
    _sid = await rotate_user_session(db, {"id": user["id"]})
    token = create_token({"sub": data.email}, session_id=_sid)

    # If a Referral Rally campaign is currently active, insert the in-app
    # announcement for this newly-registered user (see promo_broadcast).
    try:
        from promo_broadcast import maybe_insert_active_promo_notif_for_user
        await maybe_insert_active_promo_notif_for_user(db, user["id"])
    except Exception as _e:
        logger.debug(f"promo notif at register failed: {_e}")

    # Anti-multi-account: verify Turnstile + record fingerprint (best-effort)
    try:
        from antifraud import verify_turnstile, get_client_ip
        ts_result = await verify_turnstile(getattr(data, "turnstile_token", None), get_client_ip(request))
        await antifraud_record_event(
            db,
            event_type="register",
            request=request,
            user=user,
            visitor_id=getattr(data, "visitor_id", None),
            turnstile=ts_result,
        )
    except Exception as e:
        logger.warning("antifraud.register failed: %s", e)

    # Meta CAPI: fire Lead event (fire-and-forget)
    await send_capi_registration_event(
        user, request,
        fbp=getattr(data, "fbp", None), fbc=getattr(data, "fbc", None),
    )

    return {
        "token": token,
        "type": "bearer",
        "user": {
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "avatar": user["avatar"],
            "display_name": user["display_name"],
            "balance_ton": user["balance_ton"]
        }
    }

# 2. Вход через Email или Username
class EmailLoginWith2FA(BaseModel):
    email: str
    password: str
    totp_code: Optional[str] = None  # 2FA код, если требуется

@auth_router.post("/login")
# Bumped from 10 → 30/minute. A legitimate user can easily exceed 10 attempts
# during a normal session (typo + 2FA prompt + email code re-send) and they
# all share one IP behind Cloudflare. The 24h brute-force lockout (5 wrong
# attempts) is still the primary defence against credential stuffing.
@limiter.limit("30/minute")
async def login(data: EmailLogin, request: Request):
    from server import db

    # S3: brute-force lockout (MongoDB-backed, multi-worker safe).
    # Use the shared identifier helper so the same logic that drives
    # slowapi (Cloudflare → CF-Connecting-IP → X-Forwarded-For → peer)
    # is used for lockout keys too. Otherwise everybody behind Cloudflare
    # would share the same edge-IP and a single attacker could lock all
    # legitimate users out.
    from security_middleware import _get_identifier as _ident
    client_ip = _ident(request)
    await check_login_lockout_async(data.email, client_ip)

    # Поиск пользователя по email ИЛИ username
    user = await db.users.find_one({
        "$or": [
            {"email": data.email},
            {"username": data.email}  # Если передан username в поле email
        ]
    })

    if not user or not pwd_context.verify(data.password, user.get("hashed_password", "")):
        await record_login_failure_async(data.email, client_ip)
        raise HTTPException(status_code=401, detail="Неверный Email/Username или пароль")

    # Success — reset failure counter
    await record_login_success_async(data.email, client_ip)
    
    # NOTE: blocked users are intentionally ALLOWED to log in. They then see a
    # full-screen "account blocked" overlay (BlockedOverlay) with the block
    # reason in their own language and a button to open a support chat FROM
    # their own account. Hard-blocking login here would make it impossible for
    # them to contact support, so the gating is done client-side via the
    # is_blocked flag returned by /api/auth/me.

    # ─── 2FA priority: TOTP > email-code > plain ────────────────────────
    # User contract: if the user has a real TOTP (`is_2fa_enabled=true` +
    # `two_factor_secret`), we ALWAYS ask for the TOTP code and never send an
    # email code — regardless of per-user `is_email_2fa_enabled` or admin's
    # global `email_2fa_force_all` flag. Otherwise, if email-2FA is enabled
    # (either per-user opt-in OR admin-forced), we fall back to email-code.

    # Step 1: TOTP takes absolute precedence.
    if user.get("is_2fa_enabled") and user.get("two_factor_secret"):
        totp_code = getattr(data, 'totp_code', None)
        if not totp_code:
            return {
                "requires_2fa": True,
                "user_id": user.get("id", str(user.get("_id"))),
                "message": "Требуется код 2FA"
            }
        # If totp_code was provided inline (rare path used by wallet-only
        # legacy flow), verify it here. `/auth/login-2fa` is the primary
        # verification path; this is just a shortcut.
        try:
            import pyotp as _pyotp
            from security.totp_crypto import decrypt_secret as _decrypt_secret
            _totp = _pyotp.TOTP(_decrypt_secret(user["two_factor_secret"]))
            if not _totp.verify(totp_code, valid_window=1):
                # Fall through to backup-code check inside /login-2fa if the
                # frontend re-submits; here we simply reject.
                raise HTTPException(status_code=401, detail="Неверный код 2FA")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=401, detail="Неверный код 2FA")

    # Step 2: email-2FA (only reached when TOTP is not configured).
    user_email = user.get("email")
    _auth_settings = await db.admin_settings.find_one({"type": "auth_settings"}, {"_id": 0})
    _force_email_2fa = bool((_auth_settings or {}).get("email_2fa_force_all", False))
    if user_email and (user.get("is_email_2fa_enabled") or _force_email_2fa):
        from email_service import (
            generate_verification_code, store_login_code, send_login_email_async,
            RESEND_AVAILABLE, RESEND_API_KEY,
        )
        code = generate_verification_code()
        store_login_code(user_email, code)
        try:
            await send_login_email_async(user_email, code, user.get("language", "ru"))
        except Exception as e:
            logger.warning(f"[login] failed to send email code: {e}")
        if RESEND_AVAILABLE and RESEND_API_KEY:
            logger.info(f"[login] email code sent to {user_email}")
        else:
            logger.warning(f"[login][DEV] email code for {user_email}: {code}")
        return {
            "requires_email_code": True,
            "email": user_email,
            "message": "Код подтверждения входа отправлен на email",
        }
    
    # Создаем токен с email или username (что есть). Rotate session — kicks any other device.
    identifier = user.get("email") or user.get("username")
    _sid = await rotate_user_session(db, {"_id": user["_id"]})
    token = create_token({"sub": identifier}, session_id=_sid)
    
    # Get client info
    client_ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else "unknown")
    if client_ip and "," in client_ip:
        client_ip = client_ip.split(",")[0].strip()
    user_agent = request.headers.get("User-Agent", "unknown")
    # Parse device from user agent
    device = "Desktop"
    if "Mobile" in user_agent or "Android" in user_agent:
        device = "Mobile"
    elif "iPhone" in user_agent or "iPad" in user_agent:
        device = "iOS"
    elif "Tablet" in user_agent:
        device = "Tablet"
    
    # Parse browser from user agent
    browser = "Unknown"
    ua_lower = user_agent.lower()
    if "edg/" in ua_lower or "edge" in ua_lower:
        browser = "Edge"
    elif "opr/" in ua_lower or "opera" in ua_lower:
        browser = "Opera"
    elif "chrome" in ua_lower and "safari" in ua_lower:
        browser = "Chrome"
    elif "firefox" in ua_lower:
        browser = "Firefox"
    elif "safari" in ua_lower:
        browser = "Safari"
    elif "yabrowser" in ua_lower:
        browser = "Yandex"
    
    login_entry = {
        "ip": client_ip,
        "device": device,
        "browser": browser,
        "user_agent": user_agent[:200],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    
    # Обновляем last_login и device info + push to login_history (keep last 20)
    await db.users.update_one(
        {"_id": user["_id"]},
        {
            "$set": {
                "last_login": datetime.now(timezone.utc),
                "last_ip": client_ip,
                "last_device": device,
                "last_browser": browser,
                "last_user_agent": user_agent[:200]
            },
            "$push": {
                "login_history": {
                    "$each": [login_entry],
                    "$slice": -20
                }
            }
        }
    )
    try:
        import analytics
        await analytics.mark_active(user.get("id"))
    except Exception:
        pass

    # Anti-multi-account fingerprint on login (best-effort)
    try:
        from antifraud import record_event as antifraud_record_event, verify_turnstile, get_client_ip
        ts_result = await verify_turnstile(getattr(data, "turnstile_token", None), get_client_ip(request))
        await antifraud_record_event(
            db,
            event_type="login",
            request=request,
            user=user,
            visitor_id=getattr(data, "visitor_id", None),
            turnstile=ts_result,
        )
    except Exception as e:
        logger.warning("antifraud.login failed: %s", e)
    
    # Возвращаем токен и информацию о пользователе
    return {
        "token": token,
        "type": "bearer",
        "user": {
            "id": user.get("id", str(user.get("_id"))),
            "username": user.get("username"),
            "email": user.get("email"),
            "wallet_address": user.get("wallet_address"),
            "avatar": user.get("avatar"),
            "display_name": user.get("display_name") or user.get("username"),
            "is_admin": user.get("is_admin", False)
        }
    }


# ─── Login email-2FA: verify the code that was emailed after password check ───
class EmailLoginVerifyCode(BaseModel):
    email: str  # email or username (we resolve below)
    code: str
    visitor_id: Optional[str] = None
    turnstile_token: Optional[str] = None


@auth_router.post("/login-verify-email")
@limiter.limit("20/minute")
async def login_verify_email(data: EmailLoginVerifyCode, request: Request):
    """Complete login by verifying the email code sent in step 1.

    Failures count toward the same brute-force lockout (5 attempts → 24h block).
    """
    from server import db
    from email_service import verify_login_code

    client_ip = (request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                 or (request.client.host if request.client else "unknown"))
    # Resolve user first so lockout key uses the canonical email
    user = await db.users.find_one({
        "$or": [{"email": data.email}, {"username": data.email}]
    })
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    canonical_email = user.get("email") or data.email
    await check_login_lockout_async(canonical_email, client_ip)

    ok, message = verify_login_code(canonical_email, data.code)
    if not ok:
        # All non-success branches: bump failure counter (so brute-forcing the code
        # also hits the 5-attempt / 24h lock).
        await record_login_failure_async(canonical_email, client_ip)
        msg_map = {
            "no_code_requested": "Код не был запрошен. Войдите заново.",
            "code_expired": "Код истёк. Войдите заново.",
            "too_many_attempts": "Слишком много попыток. Войдите заново.",
            "invalid_code": "Неверный код",
        }
        raise HTTPException(status_code=400, detail=msg_map.get(message, message))

    # Code verified — reset the counter and issue a token
    await record_login_success_async(canonical_email, client_ip)

    identifier = canonical_email or user.get("username")
    _sid = await rotate_user_session(db, {"_id": user["_id"]})
    token = create_token({"sub": identifier}, session_id=_sid)

    # Update last_login / device info (parity with /auth/login)
    user_agent = request.headers.get("User-Agent", "unknown")
    device = "Desktop"
    if "Mobile" in user_agent or "Android" in user_agent:
        device = "Mobile"
    elif "iPhone" in user_agent or "iPad" in user_agent:
        device = "iOS"
    elif "Tablet" in user_agent:
        device = "Tablet"
    login_entry = {
        "ip": client_ip,
        "device": device,
        "user_agent": user_agent[:200],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await db.users.update_one(
        {"_id": user["_id"]},
        {
            "$set": {
                "last_login": datetime.now(timezone.utc),
                "last_ip": client_ip,
                "last_device": device,
                "last_user_agent": user_agent[:200],
            },
            "$push": {"login_history": {"$each": [login_entry], "$slice": -20}},
        },
    )

    return {
        "token": token,
        "type": "bearer",
        "user": {
            "id": user.get("id", str(user.get("_id"))),
            "username": user.get("username"),
            "email": user.get("email"),
            "wallet_address": user.get("wallet_address"),
            "avatar": user.get("avatar"),
            "display_name": user.get("display_name") or user.get("username"),
            "is_admin": user.get("is_admin", False),
        },
    }


# --- Telegram Mini App account linking ---
# Note: this endpoint **does NOT register or auto-login** users. It only
# attaches Telegram identity (telegram_id / chat_id / username) to an
# already-authenticated account, so notifications can be sent via the bot.
# Registration must go through the regular email / Google / wallet flows.
@auth_router.post("/telegram-link")
@limiter.limit("20/minute")
async def telegram_link(
    data: TelegramLogin,
    request: Request,
    current_user: dict = Depends(get_current_user_local),
):
    """
    Link a Telegram identity (parsed from Mini App initData) to the
    currently authenticated user.

    - Verifies HMAC signature when TELEGRAM_BOT_TOKEN is configured.
    - In dev (no bot token) parses initData without verification and warns.
    - Idempotent: re-linking the same Telegram account is a no-op.
    - Refuses if the same Telegram id is already bound to a *different* user
      (returns 409) — prevents account hijacking.
    """
    from server import db

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    tg_user = None

    if bot_token:
        tg_user = verify_telegram_init_data(data.init_data, bot_token)
        if not tg_user:
            raise HTTPException(status_code=401, detail="Invalid Telegram initData signature")
    else:
        from urllib.parse import parse_qsl
        import json as _json
        parsed = dict(parse_qsl(data.init_data, keep_blank_values=True))
        user_json = parsed.get("user")
        if not user_json:
            raise HTTPException(status_code=400, detail="initData lacks user payload")
        try:
            tg_user = _json.loads(user_json)
        except Exception:
            raise HTTPException(status_code=400, detail="Malformed Telegram user payload")
        logger.warning(
            "[telegram_link] TELEGRAM_BOT_TOKEN not configured — running in UNVERIFIED dev mode"
        )

    telegram_id = str(tg_user.get("id") or "").strip()
    if not telegram_id:
        raise HTTPException(status_code=400, detail="Telegram user id missing")

    # Refuse if this telegram_id is already bound to a different account.
    # Match int + string variants across all three legacy field names, so a
    # linked Telegram identity can never be silently re-bound to a second user.
    try:
        tg_id_int: Optional[int] = int(telegram_id)
    except (TypeError, ValueError):
        tg_id_int = None
    _id_variants: list = [telegram_id]
    if tg_id_int is not None:
        _id_variants.append(tg_id_int)
    other = await db.users.find_one({
        "id": {"$ne": current_user.get("id")},
        "$or": [
            {"telegram_id": {"$in": _id_variants}},
            {"telegram_user_id": {"$in": _id_variants}},
            {"telegram_chat_id": {"$in": _id_variants}},
        ],
    })
    if other:
        raise HTTPException(
            status_code=409,
            detail="telegram_already_linked_to_another_account",
        )

    update_set = {
        # Store as int when possible so all future find_one lookups (in-code,
        # and via the unique sparse index on telegram_id) match consistently.
        "telegram_id": tg_id_int if tg_id_int is not None else telegram_id,
        "telegram_user_id": telegram_id,
        "telegram_chat_id": telegram_id,                 # private DM → chat_id == user id
        "telegram_username": tg_user.get("username"),
        "telegram_verified": True,
        "telegram_notifications": True,
    }

    # Detect whether this Telegram identity was ALREADY linked to this same
    # account. This endpoint runs on every Mini App open (see
    # useTelegramAutoLink), so we must NOT re-send the "🔗 Telegram привязан"
    # message every time — only on the genuine FIRST link.
    _prev_variants = {
        str(current_user.get("telegram_id") or ""),
        str(current_user.get("telegram_user_id") or ""),
        str(current_user.get("telegram_chat_id") or ""),
    }
    was_already_linked = telegram_id in _prev_variants

    await db.users.update_one(
        {"id": current_user.get("id")},
        {"$set": update_set},
    )

    # Fire-and-forget: notify the just-linked Telegram user in their bot chat —
    # ONLY on the first-ever link, never on subsequent app opens.
    if not was_already_linked:
        try:
            from routes.telegram_notifications import notify_link_event as _notify_link_event
            import asyncio as _asyncio
            _asyncio.create_task(_notify_link_event(db, telegram_id, "linked"))
        except Exception:
            pass

    return {
        "linked": True,
        "telegram_id": telegram_id,
        "telegram_username": tg_user.get("username"),
        "telegram_notifications": True,
    }



# Вход с 2FA кодом
@auth_router.post("/login-2fa")
@limiter.limit("15/minute")
async def login_with_2fa(data: EmailLoginWith2FA, request: Request):
    from server import db
    import pyotp

    # Rate-limit + brute-force lockout on the 2FA step too (5 wrong → 24h lock),
    # keyed by the same identifier as /auth/login.
    from security_middleware import _get_identifier as _ident
    client_ip = _ident(request)
    await check_login_lockout_async(data.email, client_ip)

    # Поиск пользователя
    user = await db.users.find_one({
        "$or": [
            {"email": data.email},
            {"username": data.email}
        ]
    })
    
    if not user or not pwd_context.verify(data.password, user.get("hashed_password", "")):
        await record_login_failure_async(data.email, client_ip)
        raise HTTPException(status_code=401, detail="Неверный Email/Username или пароль")
    
    # Проверка 2FA
    if user.get("is_2fa_enabled") and user.get("two_factor_secret"):
        if not data.totp_code:
            raise HTTPException(status_code=400, detail="Требуется код 2FA")

        # Проверяем TOTP код (секрет хранится зашифрованным — расшифровываем).
        # Verification is wrapped so a malformed/undecryptable secret can NEVER
        # bubble up as a 500 "internal error" — it degrades to "invalid code".
        from security.totp_crypto import decrypt_secret
        try:
            totp = pyotp.TOTP(decrypt_secret(user["two_factor_secret"]))
            code_ok = bool(totp.verify(data.totp_code, valid_window=1))
        except Exception:
            logger.warning("[login-2fa] TOTP verify raised for user=%s — treating as invalid",
                           user.get("id"))
            code_ok = False
        if not code_ok:
            # Проверяем резервные коды
            import hashlib
            code_hash = hashlib.sha256(data.totp_code.upper().encode()).hexdigest()
            backup_codes = user.get("backup_codes", [])

            if code_hash in backup_codes:
                # Использован резервный код - удаляем его
                backup_codes.remove(code_hash)
                await db.users.update_one(
                    {"_id": user["_id"]},
                    {"$set": {"backup_codes": backup_codes}}
                )
            else:
                await record_login_failure_async(data.email, client_ip)
                raise HTTPException(status_code=401, detail="Неверный код 2FA")

    # Success — reset the brute-force counter.
    await record_login_success_async(data.email, client_ip)
    
    # Создаем токен. Rotate session — kicks any other device.
    identifier = user.get("email") or user.get("username")
    _sid = await rotate_user_session(db, {"_id": user["_id"]})
    token = create_token({"sub": identifier}, session_id=_sid)
    
    # Обновляем last_login
    await db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {"last_login": datetime.now(timezone.utc)}}
    )
    
    return {
        "token": token,
        "type": "bearer",
        "user": {
            "id": user.get("id", str(user.get("_id"))),
            "username": user.get("username"),
            "email": user.get("email"),
            "wallet_address": user.get("wallet_address"),
            "avatar": user.get("avatar"),
            "display_name": user.get("display_name") or user.get("username"),
            "is_admin": user.get("is_admin", False)
        }
    }


# 2.5. Вход/Регистрация через Google OAuth
@auth_router.post("/google")
async def google_auth(data: GoogleAuth, request: Request):
    """
    Аутентификация через Google OAuth
    Принимает Google ID token от фронтенда
    """
    from server import db
    import uuid

    is_new_user = False

    if not GOOGLE_CLIENT_ID:
        raise HTTPException(
            status_code=503,
            detail="Google OAuth not configured. Please add GOOGLE_CLIENT_ID to .env"
        )
    
    try:
        # Верифицируем Google ID token
        idinfo = id_token.verify_oauth2_token(
            data.credential,
            google_requests.Request(),
            GOOGLE_CLIENT_ID
        )
        
        # Получаем данные пользователя из Google
        email = idinfo.get('email')
        name = idinfo.get('name', '')
        picture = idinfo.get('picture', '')
        google_id = idinfo.get('sub')
        
        if not email:
            raise HTTPException(status_code=400, detail="Email not provided by Google")
        
        # Ищем пользователя по email или google_id
        user = await db.users.find_one({
            "$or": [
                {"email": email},
                {"google_id": google_id}
            ]
        })
        
        if user:
            # Пользователь существует - обновляем данные при необходимости
            updates = {}
            if not user.get("google_id"):
                updates["google_id"] = google_id
            # Refresh Google avatar on each login UNLESS the user has uploaded
            # their own custom photo (`custom_avatar_uploaded == True`). Old
            # logic used `avatar_uploaded`, which we wrongly set to `True` for
            # every Google signup — that effectively froze the avatar to the
            # first Google picture forever and never picked up updates from
            # the user's Google profile. We keep `avatar_uploaded` for
            # backward-compat (it still gates the "manually uploaded" check)
            # but ALSO accept the new explicit flag so existing Google users
            # automatically get fresh photos.
            if picture and not user.get("custom_avatar_uploaded"):
                updates["avatar"] = picture
            if not user.get("display_name"):
                updates["display_name"] = name
            
            if updates:
                updates["last_login"] = datetime.now(timezone.utc)
                await db.users.update_one(
                    {"_id": user["_id"]},
                    {"$set": updates}
                )
                user.update(updates)
            
        else:
            # Новый пользователь - создаем аккаунт
            is_new_user = True
            # Генерируем уникальный username из email
            base_username = email.split('@')[0]
            username = base_username
            counter = 1
            while await db.users.find_one(username_ci_query(username)):
                username = f"{base_username}{counter}"
                counter += 1
            
            # Используем Google avatar или генерируем из инициалов
            avatar = picture if picture else generate_avatar_from_initials(name or username)

            _dev_fields, _login_entry = build_registration_device_fields(request)
            _referrer_id = await resolve_referrer_id(db, getattr(data, "referral_code", None), new_email=email)

            user = {
                "id": str(uuid.uuid4()),
                "username": username,
                "display_name": name or username,
                "email": email,
                "google_id": google_id,
                "hashed_password": None,  # Google users don't have password
                "wallet_address": None,
                "raw_address": None,
                "avatar": avatar,
                "avatar_uploaded": False,  # Will become True only after user manually uploads via /auth/avatar
                "custom_avatar_uploaded": False,  # Google picture should refresh on each login
                "balance_ton": 0,
                "language": "ru",
                "level": "novice",
                "xp": 0,
                "total_turnover": 0,
                "total_income": 0,
                "plots_owned": [],
                "businesses_owned": [],
                "is_admin": False,
                "registration_method": "google",
                "created_at": datetime.now(timezone.utc),
                "last_login": datetime.now(timezone.utc),
                **_dev_fields,
                **referral_fields(_referrer_id),
                "login_history": [_login_entry],
            }
            
            await db.users.insert_one(user)
            try:
                import analytics
                _rm = user.get("registration_method") or "email"
                await analytics.track(user["id"], "register", channel=_rm)
                await analytics.mark_active(user["id"])
            except Exception as _ae:
                logger.debug(f"analytics register hook failed: {_ae}")
            try:
                from b2b_partners import tag_user_with_partner
                await tag_user_with_partner(db, user["id"], getattr(data, "referral_code", None))
            except Exception:
                pass

            # Meta CAPI: fire Lead event for new Google user (fire-and-forget)
            await send_capi_registration_event(
                user, request,
                fbp=getattr(data, "fbp", None), fbc=getattr(data, "fbc", None),
            )

            # Rally in-app announcement for the new Google user (if active)
            try:
                from promo_broadcast import maybe_insert_active_promo_notif_for_user
                await maybe_insert_active_promo_notif_for_user(db, user["id"])
            except Exception as _e:
                logger.debug(f"promo notif at google register failed: {_e}")
        
        # Создаем токен. Rotate session — kicks any other device.
        _sid = await rotate_user_session(db, {"email": email})
        token = create_token({"sub": email}, session_id=_sid)
        
        return {
            "token": token,
            "type": "bearer",
            "is_new_user": is_new_user,
            "user": {
                "id": user.get("id", str(user.get("_id"))),
                "username": user.get("username"),
                "email": user.get("email"),
                "wallet_address": user.get("wallet_address"),
                "avatar": user.get("avatar"),
                "display_name": user.get("display_name")
            }
        }
        
    except ValueError as e:
        # Invalid token
        raise HTTPException(status_code=401, detail=f"Invalid Google token: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Google auth error: {str(e)}")


# 2.5b. Google OAuth Callback (Authorization Code Flow - works on mobile)
class GoogleCallbackRequest(BaseModel):
    code: str
    redirect_uri: str
    state: Optional[str] = None  # F26: CSRF/PKCE binding
    referral_code: Optional[str] = None
    fbp: Optional[str] = None
    fbc: Optional[str] = None


# ==================== F26: OAuth state + PKCE ====================
def _pkce_challenge(verifier: str) -> str:
    import hashlib, base64
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@auth_router.post("/google/init")
async def google_oauth_init():
    """F26: start an OAuth login. Returns a one-time `state` (CSRF) and a PKCE
    `code_challenge` (S256). The matching `code_verifier` is stored server-side
    keyed by `state` with a 10-minute TTL and never leaves the backend.
    """
    import secrets as _secrets
    from server import db
    state = _secrets.token_urlsafe(32)
    code_verifier = _secrets.token_urlsafe(64)
    now = datetime.now(timezone.utc)
    await db.oauth_states.insert_one({
        "state": state,
        "code_verifier": code_verifier,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=10)).isoformat(),
    })
    logger.info("[google_oauth] init: issued state=%s… (PKCE S256), client_id=%s",
                state[:8], _mask_secret(_clean_env("GOOGLE_CLIENT_ID")))
    return {
        "state": state,
        "code_challenge": _pkce_challenge(code_verifier),
        "code_challenge_method": "S256",
    }


async def _consume_oauth_state(db, state: str) -> Optional[str]:
    """Validate + atomically consume a state. Returns its code_verifier or None."""
    if not state:
        return None
    doc = await db.oauth_states.find_one_and_delete({"state": state})
    if not doc:
        return None
    try:
        exp = datetime.fromisoformat(str(doc.get("expires_at")).replace("Z", "+00:00"))
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < datetime.now(timezone.utc):
            return None
    except Exception:
        return None
    return doc.get("code_verifier")


def _oauth_redirect_uri_allowed(candidate: str, request: "Request" = None) -> bool:
    """F27 hardening: verify the client-supplied redirect_uri is safe.

    The frontend always builds the redirect as `window.location.origin +
    '/auth/google/callback'` (never hardcoded / never from an env var), so the
    app works on the preview URL, the production domain (gramcity.app) and any
    custom domain WITHOUT per-domain backend config. We therefore accept the
    fixed callback path when its ORIGIN is one we trust, and keep blocking
    arbitrary open-redirect targets (foreign origins or non-callback paths).

    Trusted origins (combined):
      1. OAUTH_REDIRECT_WHITELIST env (comma-separated full URLs)  -> exact match
      2. PUBLIC_APP_URL / FRONTEND_URL / BACKEND_URL / APP_URL      -> origin
      3. CORS_ORIGINS env                                          -> origin
      4. The Origin/Referer of THIS request (our own frontend that
         initiated the OAuth flow)                                 -> origin
      5. localhost dev shortcut
    """
    from urllib.parse import urlparse
    if not candidate:
        return False
    p = urlparse(candidate)
    if p.scheme not in ("http", "https") or not p.netloc:
        return False
    # Fragments in redirect_uri are always suspicious.
    if p.fragment:
        return False

    CALLBACK_PATH = "/auth/google/callback"

    allowed_full: set = set()     # exact full-URL matches
    allowed_origins: set = set()  # scheme://host that may host the callback path

    def _add_origin(value: str):
        value = (value or "").strip().rstrip("/")
        if not value or value == "*":
            return
        vp = urlparse(value)
        if vp.scheme in ("http", "https") and vp.netloc:
            allowed_origins.add(f"{vp.scheme}://{vp.netloc}")

    # 1. explicit full-URL whitelist
    for raw in (os.environ.get("OAUTH_REDIRECT_WHITELIST", "") or "").split(","):
        v = raw.strip()
        if v:
            allowed_full.add(v.rstrip("/"))
            _add_origin(v)
    # 2. app URL envs -> full callback + origin
    for base in (
        os.environ.get("PUBLIC_APP_URL", ""),
        os.environ.get("FRONTEND_URL", ""),
        os.environ.get("BACKEND_URL", ""),
        os.environ.get("APP_URL", ""),
    ):
        base = (base or "").strip().rstrip("/")
        if base:
            allowed_full.add(f"{base}{CALLBACK_PATH}")
            _add_origin(base)
    # 3. CORS_ORIGINS -> origins
    for raw in (os.environ.get("CORS_ORIGINS", "") or "").split(","):
        _add_origin(raw)
    # 4. the Origin/Referer/Host of the request that started the flow (our
    #    frontend is served from the SAME host as this backend). NOTE: the k8s
    #    ingress may strip the inbound Origin header, so we also trust the
    #    forwarded Host / request base_url for the fixed callback path.
    if request is not None:
        try:
            _add_origin(request.headers.get("origin", ""))
            ref = request.headers.get("referer", "")
            if ref:
                rp = urlparse(ref)
                if rp.scheme and rp.netloc:
                    _add_origin(f"{rp.scheme}://{rp.netloc}")
            xf_host = request.headers.get("x-forwarded-host") or request.headers.get("host")
            if xf_host:
                xf_proto = (request.headers.get("x-forwarded-proto") or "https").split(",")[0].strip()
                _add_origin(f"{xf_proto}://{xf_host.split(',')[0].strip()}")
            try:
                _add_origin(str(request.base_url))
            except Exception:
                pass
        except Exception:
            pass
    # 5. Dev fallback
    allowed_full.add("http://localhost:3000/auth/google/callback")
    allowed_full.add("http://127.0.0.1:3000/auth/google/callback")
    _add_origin("http://localhost:3000")
    _add_origin("http://127.0.0.1:3000")

    cand_norm = candidate.rstrip("/")
    if cand_norm in allowed_full:
        return True
    # Origin match, but ONLY for the fixed OAuth callback path.
    if p.path.rstrip("/") == CALLBACK_PATH:
        cand_origin = f"{p.scheme}://{p.netloc}"
        if cand_origin in allowed_origins:
            return True
    return False


@auth_router.post("/google/callback")
async def google_oauth_callback(data: GoogleCallbackRequest, request: Request):
    """
    Google OAuth callback - exchange authorization code for tokens
    This method works better on mobile devices than One Tap.

    F27: `redirect_uri` is validated against a strict whitelist before being
    forwarded to Google. Prevents open-redirect via a spoofed callback URL.
    """
    import uuid as _uuid_mod
    _req_id = _uuid_mod.uuid4().hex[:8]
    logger.info(
        "[google_oauth %s] callback START redirect_uri=%r has_code=%s has_state=%s",
        _req_id, data.redirect_uri, bool(data.code), bool(data.state),
    )

    # F27: enforce whitelist (origin of our own frontend + configured domains)
    if not _oauth_redirect_uri_allowed(data.redirect_uri, request):
        logger.warning("[google_oauth %s] redirect_uri REJECTED: %r", _req_id, data.redirect_uri)
        raise HTTPException(status_code=400, detail="Invalid redirect_uri")

    import httpx
    import uuid
    from server import db
    
    # Re-read fresh + cleaned (strip quotes/whitespace) so a stray character in
    # the .env cannot cause Google 'invalid_client'.
    GOOGLE_CLIENT_ID = _clean_env("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = _clean_env("GOOGLE_CLIENT_SECRET")

    # F26: validate + consume state FIRST (before any env/config check) so a
    # bogus/expired/reused state always yields 400 regardless of provisioning.
    code_verifier = None
    if data.state:
        code_verifier = await _consume_oauth_state(db, data.state)
        if not code_verifier:
            logger.warning("[google_oauth %s] state invalid/expired/reused (rejected)", _req_id)
            raise _google_error("google_state_invalid", "state expired or reused")
        logger.info("[google_oauth %s] state OK, PKCE verifier consumed", _req_id)

    if not GOOGLE_CLIENT_ID:
        logger.error("[google_oauth %s] GOOGLE_CLIENT_ID missing on the server", _req_id)
        raise _google_error("google_not_configured", "GOOGLE_CLIENT_ID missing")

    try:
        # Exchange authorization code for tokens
        logger.info(
            "[google_oauth %s] exchanging code with Google (client_id=%s secret=%s pkce=%s)",
            _req_id, _mask_secret(GOOGLE_CLIENT_ID), _mask_secret(GOOGLE_CLIENT_SECRET),
            bool(code_verifier),
        )
        async with httpx.AsyncClient() as client:
            token_payload = {
                "code": data.code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": data.redirect_uri,
                "grant_type": "authorization_code"
            }
            if code_verifier:
                token_payload["code_verifier"] = code_verifier
            token_response = await client.post(
                "https://oauth2.googleapis.com/token",
                data=token_payload
            )
            
            if token_response.status_code != 200:
                try:
                    error_data = token_response.json()
                except Exception:
                    error_data = {"error": "non_json_response", "raw": token_response.text[:300]}
                logger.error("[google_oauth %s] token exchange FAILED (%s): %s",
                             _req_id, token_response.status_code, error_data)
                g_err = str(error_data.get("error", "unknown"))
                g_desc = str(error_data.get("error_description", ""))
                # DIAGNOSTIC: log the EXACT (masked) client_id/secret + redirect_uri
                # the backend used. Lets prod misconfig be pinpointed instantly:
                # an 'invalid_client' here almost always means the backend
                # GOOGLE_CLIENT_ID/SECRET differs from the one the frontend used
                # for the authorize step (or is truncated/blank).
                if g_err in ("invalid_client", "unauthorized_client"):
                    logger.error(
                        "[google_oauth %s] invalid_client — backend used client_id=%s secret=%s redirect_uri=%r. "
                        "Verify these EXACTLY match the frontend REACT_APP_GOOGLE_CLIENT_ID and the "
                        "OAuth client in Google Console, then RESTART the backend.",
                        _req_id, _mask_secret(GOOGLE_CLIENT_ID), _mask_secret(GOOGLE_CLIENT_SECRET),
                        data.redirect_uri,
                    )
                # Map Google's raw reason -> a stable code the frontend renders
                # as a friendly localized message (never a bare 'invalid_client').
                if g_err in ("invalid_client", "unauthorized_client"):
                    raise _google_error("google_config_error", f"{g_err} {g_desc}".strip())
                if g_err == "redirect_uri_mismatch":
                    raise _google_error("google_config_error", f"{g_err} {g_desc}".strip())
                if g_err == "invalid_grant":
                    raise _google_error("google_session_expired", f"{g_err} {g_desc}".strip())
                raise _google_error("google_generic", f"{g_err} {g_desc}".strip())
            
            tokens = token_response.json()
            id_token_str = tokens.get("id_token")
            
            if not id_token_str:
                logger.error("[google_oauth %s] no id_token in Google response", _req_id)
                raise _google_error("google_no_id_token", "no id_token from Google")
            
            # Verify and decode the ID token
            idinfo = id_token.verify_oauth2_token(
                id_token_str,
                google_requests.Request(),
                GOOGLE_CLIENT_ID
            )
            logger.info("[google_oauth %s] id_token verified for sub=%s", _req_id, idinfo.get("sub"))
        
        # Get user info from token
        email = idinfo.get('email')
        name = idinfo.get('name', '')
        picture = idinfo.get('picture', '')
        google_id = idinfo.get('sub')
        
        if not email:
            logger.error("[google_oauth %s] Google returned no email", _req_id)
            raise _google_error("google_no_email", "email not provided by Google")
        logger.info("[google_oauth %s] resolved email=%s", _req_id, _mask_email(email))
        
        # Find or create user
        user = await db.users.find_one({
            "$or": [
                {"email": email},
                {"google_id": google_id}
            ]
        })
        
        if user:
            # Update existing user
            updates = {"last_login": datetime.now(timezone.utc).isoformat()}
            if not user.get("google_id"):
                updates["google_id"] = google_id
            # Refresh Google avatar unless the user has uploaded their own.
            if picture and not user.get("custom_avatar_uploaded"):
                updates["avatar"] = picture
            if not user.get("display_name") and name:
                updates["display_name"] = name
            
            await db.users.update_one({"_id": user["_id"]}, {"$set": updates})
            
            _sid = await rotate_user_session(db, {"_id": user["_id"]})
            token = create_token(data={"sub": email}, session_id=_sid)
            logger.info("[google_oauth %s] LOGIN OK existing user=%s email=%s",
                        _req_id, user.get("id", str(user.get("_id"))), _mask_email(email))
            
            return {
                "status": "ok",
                "token": token,
                "is_new_user": False,
                "user": {
                    "id": user.get("id", str(user.get("_id"))),
                    "username": user.get("username"),
                    "email": email,
                    "avatar": user.get("avatar", picture),
                    "is_admin": user.get("is_admin", False)
                }
            }
        else:
            # Create new user
            username = name.split()[0] if name else email.split("@")[0]
            avatar = picture or generate_avatar_from_initials(name or username)

            _dev_fields, _login_entry = build_registration_device_fields(request)
            _referrer_id = await resolve_referrer_id(db, getattr(data, "referral_code", None), new_email=email)

            new_user = {
                "id": str(uuid.uuid4()),
                "username": username,
                "display_name": name,
                "email": email,
                "google_id": google_id,
                "hashed_password": None,
                "avatar": avatar,
                "avatar_uploaded": False,
                "custom_avatar_uploaded": False,  # Google picture refreshes on each login
                "balance_ton": 0.0,
                "level": 1,
                "xp": 0,
                "is_admin": False,
                "registration_method": "google",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "last_login": datetime.now(timezone.utc).isoformat(),
                "email_verified": True,
                "plots_owned": [],
                "businesses_owned": [],
                **_dev_fields,
                **referral_fields(_referrer_id),
                "login_history": [_login_entry],
            }
            
            await db.users.insert_one(new_user)

            # Meta CAPI: fire Lead event for new Google (OAuth) user (fire-and-forget)
            await send_capi_registration_event(
                new_user, request,
                fbp=getattr(data, "fbp", None), fbc=getattr(data, "fbc", None),
            )

            # Rally in-app announcement (if a campaign is currently active)
            try:
                from promo_broadcast import maybe_insert_active_promo_notif_for_user
                await maybe_insert_active_promo_notif_for_user(db, new_user["id"])
            except Exception as _e:
                logger.debug(f"promo notif at oauth register failed: {_e}")
            
            _sid = await rotate_user_session(db, {"id": new_user["id"]})
            token = create_token(data={"sub": email}, session_id=_sid)
            logger.info("[google_oauth %s] REGISTER OK new user=%s email=%s",
                        _req_id, new_user["id"], _mask_email(email))
            
            return {
                "status": "ok",
                "token": token,
                "is_new_user": True,
                "user": {
                    "id": new_user["id"],
                    "username": username,
                    "email": email,
                    "avatar": avatar,
                    "is_admin": False
                }
            }
            
    except httpx.RequestError as e:
        logger.error("[google_oauth %s] network error contacting Google: %s", _req_id, e)
        raise _google_error("google_generic", "network error contacting Google")
    except HTTPException:
        # Never swallow explicit HTTP errors (e.g. the 401 with Google's real
        # reason, the 400 invalid redirect_uri). Re-raise so the client gets
        # the accurate status + detail instead of a generic 500 'Auth error'.
        raise
    except ValueError as e:
        logger.error("[google_oauth %s] id_token validation error: %s", _req_id, e)
        raise _google_error("google_session_expired", "id_token validation failed")
    except Exception as e:
        logger.exception("[google_oauth %s] unexpected error: %s", _req_id, e)
        raise _google_error("google_generic", "unexpected server error")


# 2.6. (REMOVED) Emergent Google OAuth — функциональность удалена.


# 3. Проверка/Вход через Кошелек (Wallet Check)
@auth_router.post("/wallet-check")
async def wallet_check(data: WalletAuth):
    from server import db
    user = await db.users.find_one({"wallet_address": data.address})
    
    if not user:
        # Если юзера нет, создаем "черновик" без Username
        new_user = {
            "username": None,
            "email": None,
            "wallet_address": data.address,
            "balance_ton": 0,
            "created_at": datetime.now(timezone.utc)
        }
        await db.users.insert_one(new_user)
        _sid = await rotate_user_session(db, {"wallet_address": data.address})
        token = create_token({"sub": data.address}, session_id=_sid)
        return {"status": "need_username", "token": token}
    
    # Если юзер есть, но ник почему-то не установлен
    if not user.get("username"):
        _sid = await rotate_user_session(db, {"_id": user["_id"]})
        token = create_token({"sub": data.address}, session_id=_sid)
        return {"status": "need_username", "token": token}
    
    # Обычный вход. Rotate session — kicks any other device.
    _sid = await rotate_user_session(db, {"_id": user["_id"]})
    token = create_token({"sub": data.address}, session_id=_sid)
    return {"status": "ok", "token": token}

# 4. Установка Username (вызывается в модалке после Wallet/Google входа)
@auth_router.post("/set-username")
async def set_username(data: UsernameUpdate, token: str):
    from server import db
    # Получаем юзера по временному токену
    current_user = await get_current_user_local(token)
    
    # Проверяем, свободен ли ник
    data.username = validate_username(data.username)
    if await db.users.find_one(username_ci_query(data.username)):
        raise HTTPException(status_code=400, detail="Этот ник уже занят")

    await db.users.update_one(
        {"_id": current_user["_id"]},
        {"$set": {"username": data.username}}
    )
    
    return {"status": "success"}


# 5. Настройки пользователя
class UpdateUsernameRequest(BaseModel):
    username: str

class UpdateEmailRequest(BaseModel):
    email: EmailStr
    password: str  # Требуется текущий пароль для подтверждения

class UpdatePasswordRequest(BaseModel):
    current_password: str
    new_password: str

class LinkWalletRequest(BaseModel):
    wallet_address: str

class UploadAvatarRequest(BaseModel):
    avatar_data: str  # Base64 encoded image or URL

@auth_router.put("/update-username")
async def update_username(data: UpdateUsernameRequest, current_user: dict = Depends(get_current_user_local)):
    """Изменение username"""
    from server import db
    
    if len(data.username) < 3:
        raise HTTPException(status_code=400, detail="Username слишком короткий (минимум 3 символа)")
    
    data.username = validate_username(data.username)
    # Проверяем уникальность (case-insensitive — "User" == "user" == "USER")
    existing = await db.users.find_one(username_ci_query(data.username))
    if existing and str(existing.get("_id")) != str(current_user.get("_id")):
        raise HTTPException(status_code=400, detail="Этот username уже занят")
    
    await db.users.update_one(
        {"_id": current_user["_id"]},
        {"$set": {"username": data.username, "display_name": data.username}}
    )
    
    return {"status": "success", "username": data.username}

@auth_router.put("/update-email")
async def update_email(data: UpdateEmailRequest, current_user: dict = Depends(get_current_user_local)):
    """Изменение email (требуется пароль)"""
    from server import db
    
    # Проверка: у пользователя должен быть пароль (не Google auth)
    if not current_user.get("hashed_password"):
        raise HTTPException(status_code=400, detail="Невозможно изменить email для аккаунта Google")
    
    # Проверяем текущий пароль
    if not pwd_context.verify(data.password, current_user.get("hashed_password", "")):
        raise HTTPException(status_code=401, detail="Неверный пароль")
    
    # Проверяем уникальность email
    existing = await db.users.find_one({"email": data.email})
    if existing and str(existing.get("_id")) != str(current_user.get("_id")):
        raise HTTPException(status_code=400, detail="Этот email уже используется")
    
    await db.users.update_one(
        {"_id": current_user["_id"]},
        {"$set": {"email": data.email}}
    )
    
    return {"status": "success", "email": data.email}

@auth_router.put("/update-password")
async def update_password(data: UpdatePasswordRequest, current_user: dict = Depends(get_current_user_local)):
    """Изменение пароля"""
    from server import db
    
    # Проверка: у пользователя должен быть пароль (не Google auth)
    if not current_user.get("hashed_password"):
        raise HTTPException(status_code=400, detail="Невозможно установить пароль для аккаунта Google")
    
    # Проверяем текущий пароль
    if not pwd_context.verify(data.current_password, current_user.get("hashed_password", "")):
        raise HTTPException(status_code=401, detail="Неверный текущий пароль")
    
    # Проверяем сложность нового пароля (единая проверка + сообщение)
    validate_password_strength(data.new_password)
    
    # Хешируем новый пароль
    new_hashed = pwd_context.hash(data.new_password)
    
    await db.users.update_one(
        {"_id": current_user["_id"]},
        {"$set": {"hashed_password": new_hashed}}
    )
    
    # a new password ends every session: a stolen token stops working at once
    from core.token_revocation import revoke_all as _revoke_all
    await _revoke_all(db, {"_id": current_user["_id"]})
    
    await rotate_user_session(db, {"_id": current_user["_id"]})
    
    return {"status": "success"}

# 4.4. Update preferred UI language
class UpdateLanguageRequest(BaseModel):
    language: str

_SUPPORTED_LANGS = {"en", "ru", "es", "zh", "fr", "de", "ja", "ko", "id"}

@auth_router.put("/update-language")
async def update_language(data: UpdateLanguageRequest, current_user: dict = Depends(get_current_user_local)):
    """Persist the user's preferred UI language across sessions/devices.

    Without this endpoint the LanguageContext on the client falls back to
    `user.language` from /auth/me on every refresh, overwriting the choice the
    user made locally — so on next reload the language seemingly "resets".
    """
    from server import db
    lang = (data.language or "").strip().lower()
    if lang not in _SUPPORTED_LANGS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported language. Allowed: {sorted(_SUPPORTED_LANGS)}",
        )
    await db.users.update_one(
        {"_id": current_user["_id"]},
        {"$set": {"language": lang}},
    )
    # Синхронизируем язык Telegram-бота с выбранным в приложении.
    _chat_id = current_user.get("telegram_chat_id")
    if _chat_id:
        try:
            await db.telegram_mappings.update_one({"chat_id": str(_chat_id)}, {"$set": {"language": lang}})
        except Exception:
            pass
    return {"status": "success", "language": lang}

@auth_router.post("/link-wallet")
async def link_wallet(data: LinkWalletRequest, current_user: dict = Depends(get_current_user_local)):
    """Привязка кошелька к аккаунту"""
    from server import db
    from core.helpers import normalize_wallet
    from datetime import datetime, timezone

    # Canonical normalization (raw = source of truth)
    wallet_uf, raw_address = normalize_wallet(data.wallet_address)
    if not wallet_uf or not raw_address:
        raise HTTPException(status_code=400, detail="Некорректный адрес кошелька")

    # Проверяем, не привязан ли кошелек к другому аккаунту
    existing = await db.users.find_one({
        "$or": [
            {"raw_address": raw_address},
            {"wallet_address": wallet_uf},
            {"wallet_address": data.wallet_address},
        ]
    })

    if existing and str(existing.get("_id")) != str(current_user.get("_id")):
        # Requirement (Сценарий C): do NOT switch accounts — reject with a
        # STABLE machine code so the frontend can localize it into every
        # project language ("кошелёк занят").
        raise HTTPException(status_code=400, detail="wallet_already_linked")

    # IMPORTANT: Set wallet_linked_at to NOW to ignore old transactions (Problem #4 fix).
    # One account holds at most ONE wallet (single field) — re-linking overwrites
    # the previous one, freeing it automatically.
    await db.users.update_one(
        {"_id": current_user["_id"]},
        {"$set": {
            "wallet_address": wallet_uf,
            "raw_address": raw_address,
            "wallet_linked_at": datetime.now(timezone.utc).isoformat()
        }}
    )

    return {"status": "success", "wallet_address": wallet_uf}

@auth_router.post("/unlink-wallet")
async def unlink_wallet(current_user: dict = Depends(get_current_user_local)):
    """Отвязка кошелька от аккаунта"""
    from server import db
    
    # Проверяем, есть ли у пользователя email (иначе он потеряет доступ к аккаунту)
    if not current_user.get("email") and not current_user.get("hashed_password"):
        raise HTTPException(
            status_code=400, 
            detail="Невозможно отвязать кошелек - у вас нет email. Сначала добавьте email в настройках."
        )
    
    # an NFT reward on its way to this wallet: unlinking now would lose track of it
    if current_user.get("id") and await db.mg_nft_grants.find_one({"user_id": current_user["id"], "status": "sending"}):
        raise HTTPException(status_code=400, detail="nft_sending")

    await db.users.update_one(
        {"_id": current_user["_id"]},
        {"$unset": {
            "wallet_address": "",
            "raw_address": ""
        }}
    )
    
    return {"status": "success", "message": "Кошелек отвязан"}

@auth_router.post("/upload-avatar")
async def upload_avatar(data: UploadAvatarRequest, current_user: dict = Depends(get_current_user_local)):
    """Загрузка пользовательского аватара"""
    from server import db
    
    # В реальном приложении здесь была бы загрузка на S3/CDN
    # Пока просто сохраняем base64/URL
    await db.users.update_one(
        {"_id": current_user["_id"]},
        {"$set": {
            "avatar": data.avatar_data,
            "avatar_uploaded": True,
            # New explicit flag — when True, Google login will NOT overwrite
            # the user's uploaded photo. This is the "manual upload" marker.
            "custom_avatar_uploaded": True
        }}
    )
    
    return {"status": "success", "avatar": data.avatar_data}



# ==================== PASSWORD RESET ====================

class RequestPasswordResetRequest(BaseModel):
    email: EmailStr

class VerifyResetCodeRequest(BaseModel):
    email: EmailStr
    code: str

class ResetPasswordRequest(BaseModel):
    email: EmailStr
    code: str
    new_password: str

@auth_router.post("/request-password-reset")
async def request_password_reset(data: RequestPasswordResetRequest):
    """Запрос сброса пароля - отправляет код на email.

    F28 hardening: always return the same generic success response regardless
    of whether the email exists, so the endpoint cannot be used for email
    enumeration. We still do the real work when the account exists; otherwise
    we run a dummy bcrypt-equivalent delay so response timing is comparable.
    """
    from server import db
    from email_service import generate_reset_code, store_reset_code, send_email_with_code_async
    import secrets as _secrets
    import asyncio as _asyncio

    # Generic response — never disclose whether email/account exists.
    generic_response = {"status": "success", "message": "code_sent"}

    user = await db.users.find_one({"email": data.email})

    # Case: user does not exist. Anti-enumeration — return the same generic
    # response but do NOT send an email. We still mimic the timing of the real
    # send path so response timing can't be used to probe which emails exist.
    #
    # NOTE (fix): previously we ALSO skipped accounts that had no password yet
    # (Google / Telegram / wallet signups). That meant a user who registered
    # with Google and later tried "forgot password" got a "code sent" toast but
    # never received any email. We now send a reset code to ANY existing account
    # that has a real email — the reset flow then simply SETS a password for
    # passwordless accounts, which is exactly what the user wants.
    real_email = (user or {}).get("email") if user else None
    if not user or not real_email or "@" not in str(real_email):
        # Small constant delay to blur timing differences (~40-80ms range).
        await _asyncio.sleep(0.05 + _secrets.randbelow(30) / 1000.0)
        return generic_response

    # Real path: generate + store code, send email.
    code = generate_reset_code()
    store_reset_code(data.email, code)
    language = user.get("language", "ru")
    logger.info("[password_reset] request for %s (user=%s lang=%s) — sending code",
                _mask_email(data.email), user.get("id"), language)
    # Best-effort send. We do NOT surface send failures to the caller here,
    # because doing so would re-introduce a side-channel (200 vs 500 for
    # existing vs non-existing emails when the SMTP relay is down).
    try:
        _sent = await send_email_with_code_async(data.email, code, language, "reset")
        logger.info("[password_reset] email dispatch for %s result=%s",
                    _mask_email(data.email), _sent)
    except Exception as _e:
        import logging as _logging
        _logging.getLogger(__name__).warning(f"password-reset email send failed for {data.email}: {_e}")

    return generic_response

@auth_router.post("/verify-reset-code")
async def verify_reset_code_endpoint(data: VerifyResetCodeRequest):
    """Проверка кода сброса (без смены пароля)"""
    from email_service import verify_reset_code, store_reset_code, generate_reset_code
    import logging
    logger = logging.getLogger(__name__)
    
    # Получаем текущий код для проверки без удаления
    from email_service import reset_codes
    email_lower = data.email.lower()
    
    # Strip whitespace only, keep case
    received_code = data.code.strip()
    
    logger.info(f"Verify code attempt for {email_lower}, received code: '{received_code}'")
    
    if email_lower not in reset_codes:
        logger.warning(f"No code found for {email_lower}")
        raise HTTPException(status_code=400, detail="no_code_requested")
    
    stored = reset_codes[email_lower]
    stored_code = stored['code']
    logger.info(f"Stored code for {email_lower}: '{stored_code}'")
    
    from datetime import datetime, timezone
    if datetime.now(timezone.utc) > stored["expires_at"]:
        del reset_codes[email_lower]
        raise HTTPException(status_code=400, detail="code_expired")
    
    if stored["attempts"] >= 5:
        del reset_codes[email_lower]
        raise HTTPException(status_code=400, detail="too_many_attempts")
    
    if stored_code != received_code:
        logger.warning(f"Code mismatch: stored='{stored_code}' vs received='{received_code}'")
        stored["attempts"] += 1
        raise HTTPException(status_code=400, detail="invalid_code")
    
    # Код верный, но не удаляем его - пользователь еще будет менять пароль
    return {"status": "success", "valid": True}

@auth_router.post("/reset-password")
async def reset_password(data: ResetPasswordRequest):
    """Сброс пароля с использованием кода"""
    from server import db
    from email_service import verify_reset_code
    
    # Проверяем код
    success, message = verify_reset_code(data.email, data.code)
    
    if not success:
        raise HTTPException(status_code=400, detail=message)
    
    # Проверяем сложность нового пароля (единая проверка + сообщение)
    validate_password_strength(data.new_password)
    
    # Обновляем пароль
    new_hash = pwd_context.hash(data.new_password)
    
    result = await db.users.update_one(
        {"email": data.email},
        {"$set": {"hashed_password": new_hash}}
    )
    
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="user_not_found")
    # a reset password ends every session (a stolen token stops working at once)
    from core.token_revocation import revoke_all as _revoke_all
    await _revoke_all(db, {"email": data.email})
    
    return {"status": "success", "message": "password_changed"}


# ==================== EMAIL CHANGE WITH VERIFICATION ====================

# In-memory storage for email change codes
email_change_codes = {}

class EmailChangeStartRequest(BaseModel):
    pass  # No body needed, uses current user

class EmailChangeVerifyOldRequest(BaseModel):
    code: str

class EmailChangeSendNewRequest(BaseModel):
    new_email: EmailStr
    old_code: str

class EmailChangeCompleteRequest(BaseModel):
    new_email: EmailStr
    new_code: str
    old_code: str


@auth_router.post("/email-change/start")
async def email_change_start(current_user = Depends(get_current_user_local)):
    """Step 1: Send verification code to current email"""
    from server import db
    from email_service import send_email_with_code_async
    import secrets
    
    # current_user is a dict, not an object
    user_email = current_user.get("email")
    user_id = current_user.get("id")
    
    user = await db.users.find_one(
        {"$or": [{"email": user_email}, {"id": user_id}]},
        {"_id": 0}
    )
    
    if not user or not user.get("email"):
        raise HTTPException(status_code=400, detail="Email не найден")
    
    # Check if email was changed recently (7 days limit)
    last_email_change = user.get("last_email_change")
    if last_email_change:
        last_email_change = to_aware(last_email_change)
        days_since_change = (datetime.now(timezone.utc) - last_email_change).days if last_email_change else 999
        if days_since_change < 7:
            days_left = 7 - days_since_change
            raise HTTPException(status_code=400, detail=f"Смена email доступна через {days_left} дн. (раз в 7 дней)")
    
    email = user["email"]
    code = ''.join(secrets.choice('0123456789') for _ in range(6))
    
    # Store code
    email_change_codes[email.lower()] = {
        "old_code": code,
        "new_code": None,
        "new_email": None,
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=15),
        "user_id": user.get("id")
    }
    
    # Send email using async function
    try:
        email_sent = await send_email_with_code_async(email, code, user.get("language", "ru"), "verification")
        if not email_sent:
            logger.warning(f"Email change code for {email}: {code} (email not sent)")
    except Exception as e:
        logger.error(f"Failed to send email change code: {e}")
        logger.info(f"Email change code for {email}: {code}")
    
    return {"status": "success", "message": "Код отправлен на вашу почту"}


@auth_router.post("/email-change/verify-old")
async def email_change_verify_old(data: EmailChangeVerifyOldRequest, current_user = Depends(get_current_user_local)):
    """Step 2: Verify code from old email"""
    from server import db
    
    user_email = current_user.get("email")
    user_id = current_user.get("id")
    
    user = await db.users.find_one(
        {"$or": [{"email": user_email}, {"id": user_id}]},
        {"_id": 0}
    )
    
    if not user or not user.get("email"):
        raise HTTPException(status_code=400, detail="Email не найден")
    
    email = user["email"].lower()
    
    stored = email_change_codes.get(email)
    if not stored:
        raise HTTPException(status_code=400, detail="Код не найден. Запросите новый")
    
    if datetime.now(timezone.utc) > stored["expires_at"]:
        del email_change_codes[email]
        raise HTTPException(status_code=400, detail="Код истёк. Запросите новый")
    
    if stored["old_code"] != data.code:
        raise HTTPException(status_code=400, detail="Неверный код")
    
    return {"status": "success", "message": "Код подтверждён"}


@auth_router.post("/email-change/send-new")
async def email_change_send_new(data: EmailChangeSendNewRequest, current_user = Depends(get_current_user_local)):
    """Step 3: Send verification code to new email"""
    from server import db
    from email_service import send_email_with_code_async
    import secrets
    
    user_email = current_user.get("email")
    user_id = current_user.get("id")
    
    user = await db.users.find_one(
        {"$or": [{"email": user_email}, {"id": user_id}]},
        {"_id": 0}
    )
    
    if not user or not user.get("email"):
        raise HTTPException(status_code=400, detail="Email не найден")
    
    email = user["email"].lower()
    
    # Verify old code first
    stored = email_change_codes.get(email)
    if not stored or stored["old_code"] != data.old_code:
        raise HTTPException(status_code=400, detail="Сначала подтвердите текущий email")
    
    # Check if new email is already used
    existing = await db.users.find_one({"email": data.new_email})
    if existing:
        raise HTTPException(status_code=400, detail="Этот email уже используется")
    
    # Generate code for new email
    new_code = ''.join(secrets.choice('0123456789') for _ in range(6))
    stored["new_code"] = new_code
    stored["new_email"] = data.new_email
    stored["expires_at"] = datetime.now(timezone.utc) + timedelta(minutes=15)
    
    # Send email to new address
    try:
        email_sent = await send_email_with_code_async(data.new_email, new_code, user.get("language", "ru"), "verification")
        if not email_sent:
            logger.warning(f"Email change code for {data.new_email}: {new_code} (email not sent)")
    except Exception as e:
        logger.error(f"Failed to send new email code: {e}")
        logger.info(f"Email change code for {data.new_email}: {new_code}")
    
    return {"status": "success", "message": "Код отправлен на новую почту"}


@auth_router.post("/email-change/complete")
async def email_change_complete(data: EmailChangeCompleteRequest, current_user = Depends(get_current_user_local)):
    """Step 4: Complete email change"""
    from server import db
    
    user_email = current_user.get("email")
    user_id = current_user.get("id")
    
    user = await db.users.find_one(
        {"$or": [{"email": user_email}, {"id": user_id}]},
        {"_id": 0}
    )
    
    if not user or not user.get("email"):
        raise HTTPException(status_code=400, detail="Email не найден")
    
    email = user["email"].lower()
    
    stored = email_change_codes.get(email)
    if not stored:
        raise HTTPException(status_code=400, detail="Процесс смены email не найден")
    
    if datetime.now(timezone.utc) > stored["expires_at"]:
        del email_change_codes[email]
        raise HTTPException(status_code=400, detail="Время истекло. Начните заново")
    
    if stored["old_code"] != data.old_code:
        raise HTTPException(status_code=400, detail="Неверный код старой почты")
    
    if stored["new_code"] != data.new_code:
        raise HTTPException(status_code=400, detail="Неверный код новой почты")
    
    if stored["new_email"] != data.new_email:
        raise HTTPException(status_code=400, detail="Email не совпадает")
    
    # Update email in database
    result = await db.users.update_one(
        {"email": user["email"]},
        {"$set": {
            "email": data.new_email, 
            "email_verified": True,
            "last_email_change": datetime.now(timezone.utc).isoformat()
        }}
    )
    
    if result.modified_count == 0:
        raise HTTPException(status_code=500, detail="Не удалось обновить email")
    
    # Clean up
    del email_change_codes[email]
    
    return {"status": "success", "message": "Email успешно изменён"}



# ==================== ADD EMAIL TO WALLET-ONLY USER ====================

# In-memory storage for "add email" verification codes
email_add_codes = {}

class EmailAddStartRequest(BaseModel):
    new_email: EmailStr

class EmailAddVerifyRequest(BaseModel):
    new_email: EmailStr
    code: str


@auth_router.post("/email-add/start")
async def email_add_start(data: EmailAddStartRequest, current_user = Depends(get_current_user_local)):
    """Send verification code to a new email so wallet-only user can attach it."""
    from server import db
    from email_service import send_email_with_code_async
    import secrets

    user_id = current_user.get("id")
    user_wallet = current_user.get("wallet_address")

    user = await db.users.find_one(
        {"$or": [{"id": user_id}, {"wallet_address": user_wallet}]},
        {"_id": 0},
    )
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    if user.get("email"):
        raise HTTPException(status_code=400, detail="К аккаунту уже привязан email. Используйте смену email.")

    new_email = data.new_email.lower().strip()

    # Make sure no other user already uses this email
    existing = await db.users.find_one({"email": new_email})
    if existing:
        raise HTTPException(status_code=400, detail="Этот email уже используется")

    code = ''.join(secrets.choice('0123456789') for _ in range(6))
    email_add_codes[user.get("id")] = {
        "code": code,
        "new_email": new_email,
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=15),
    }

    try:
        email_sent = await send_email_with_code_async(
            new_email, code, user.get("language", "ru"), "verification"
        )
        if not email_sent:
            logger.warning(f"Email-add code for {new_email}: {code} (email not sent)")
    except Exception as e:
        logger.error(f"Failed to send email-add code: {e}")
        logger.info(f"Email-add code for {new_email}: {code}")

    return {"status": "success", "message": "Код отправлен на указанный email"}


@auth_router.post("/email-add/verify")
async def email_add_verify(data: EmailAddVerifyRequest, current_user = Depends(get_current_user_local)):
    """Confirm code and attach email to the wallet-only user."""
    from server import db

    user_id = current_user.get("id")
    user_wallet = current_user.get("wallet_address")

    user = await db.users.find_one(
        {"$or": [{"id": user_id}, {"wallet_address": user_wallet}]},
        {"_id": 0},
    )
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    if user.get("email"):
        raise HTTPException(status_code=400, detail="К аккаунту уже привязан email")

    stored = email_add_codes.get(user.get("id"))
    if not stored:
        raise HTTPException(status_code=400, detail="Запросите код заново")

    if datetime.now(timezone.utc) > stored["expires_at"]:
        del email_add_codes[user.get("id")]
        raise HTTPException(status_code=400, detail="Код истёк. Запросите новый")

    new_email = data.new_email.lower().strip()
    if stored["new_email"] != new_email:
        raise HTTPException(status_code=400, detail="Email не совпадает с тем, на который отправили код")

    if stored["code"] != data.code:
        raise HTTPException(status_code=400, detail="Неверный код")

    # Last race-condition check
    existing = await db.users.find_one({"email": new_email})
    if existing and existing.get("id") != user.get("id"):
        raise HTTPException(status_code=400, detail="Этот email уже используется")

    await db.users.update_one(
        {"id": user.get("id")},
        {"$set": {
            "email": new_email,
            "email_verified": True,
            "last_email_change": datetime.now(timezone.utc).isoformat(),
        }},
    )

    del email_add_codes[user.get("id")]
    return {"status": "success", "message": "Email успешно привязан", "email": new_email}


@auth_router.post("/logout-all")
async def logout_all_devices(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """End every session of this account (e.g. a phone was lost); THIS device gets a fresh token."""
    from server import db
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    sub = payload.get("sub")
    # "sub" is the user id for new logins, an e-mail / wallet for older ones (same lookup as get_current_user)
    user = await db.users.find_one({"$or": [{"id": sub}, {"email": sub}, {"wallet_address": sub}]},
                                   {"_id": 0, "id": 1, "session_id": 1})
    from core.token_revocation import is_revoked as _is_revoked
    if not user or await _is_revoked(db, payload):     # any valid (not revoked) token of this account may do it
        raise HTTPException(status_code=401, detail="Session expired")
    from core.token_revocation import revoke_all as _revoke_all
    await _revoke_all(db, {"id": user["id"]})
    sid = await rotate_user_session(db, {"id": user["id"]})
    return {"status": "ok", "access_token": create_token({"sub": sub}, session_id=sid)}
