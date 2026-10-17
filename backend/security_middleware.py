"""
Security middleware for GRAM City:
- Secure JWT secret generation (S1)
- Rate limiting via slowapi (S3)
- Login brute-force lockout — MongoDB-backed for multi-worker support (S3)
- Security headers with per-request CSP nonce (S7)
- Password strength validation (S4)
- Log sanitization (S6)
"""
import os
import re
import secrets
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from slowapi import Limiter
from slowapi.util import get_remote_address

logger = logging.getLogger(__name__)

# ==================== S1: JWT SECRET ====================

def get_or_generate_jwt_secret() -> str:
    """Return a STABLE JWT secret.

    Priority:
      1. ``JWT_SECRET_KEY`` env var (recommended for production).
      2. A persisted secret file (``backend/jwt_secret.key`` or the path in
         ``JWT_SECRET_FILE``). This is generated ONCE and reused across every
         worker process and every restart — so multi-worker deployments and
         hot-reloads no longer invalidate existing tokens (the previous
         behaviour generated a fresh per-process secret, which caused random
         401 "Invalid token" / "can't log in" failures when more than one
         gunicorn worker was running).

    The generated file is git-ignored (``*.key``) so the secret never leaks
    into the repository, yet stays constant on a given host.
    """
    from pathlib import Path

    secret = os.environ.get("JWT_SECRET_KEY", "").strip()
    legacy_default = "ton-city-builder-secret-key-2025"
    if secret and secret != legacy_default:
        return secret

    secret_file = os.environ.get("JWT_SECRET_FILE", "").strip()
    if not secret_file:
        secret_file = str(Path(__file__).resolve().parent / "jwt_secret.key")

    # Reuse a previously persisted secret if it exists.
    try:
        existing = Path(secret_file).read_text(encoding="utf-8").strip()
        if existing and len(existing) >= 32:
            os.environ["JWT_SECRET_KEY"] = existing
            return existing
    except FileNotFoundError:
        pass
    except Exception as e:  # unreadable file — fall back to generating
        logger.warning("[SECURITY] Could not read JWT secret file %s: %s", secret_file, e)

    generated = secrets.token_urlsafe(48)
    try:
        p = Path(secret_file)
        p.write_text(generated, encoding="utf-8")
        try:
            os.chmod(secret_file, 0o600)
        except Exception:
            pass
        logger.warning(
            "[SECURITY] JWT_SECRET_KEY was not set — generated a stable secret and "
            "persisted it to %s (git-ignored). All workers/restarts will now share "
            "it. For explicit control, set JWT_SECRET_KEY in backend/.env "
            "(e.g. `openssl rand -hex 64`).",
            secret_file,
        )
    except Exception as e:
        # Could not persist (read-only FS). Fall back to per-process secret and
        # warn loudly — multi-worker auth will break in this rare case.
        logger.error(
            "[SECURITY] Could not persist JWT secret to %s (%s). Falling back to a "
            "per-process secret; set a stable JWT_SECRET_KEY in backend/.env to avoid "
            "cross-worker 401 errors.",
            secret_file, e,
        )
    os.environ["JWT_SECRET_KEY"] = generated
    return generated


# ==================== S3: RATE LIMITING ====================

def _get_identifier(request: Request) -> str:
    """Best-effort real client IP.

    Order of preference:
      1. ``CF-Connecting-IP`` — Cloudflare's authoritative header, only ever set
         by Cloudflare itself (a malicious client cannot spoof it because CF
         strips it on the inbound edge). Use this when the deployment sits
         behind Cloudflare.
      2. ``X-Forwarded-For`` — generic reverse-proxy chain. Take the FIRST
         (left-most) IP which is the original client.
      3. The TCP-level peer (slowapi default) — last resort.
    """
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip.strip()
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return get_remote_address(request)

limiter = Limiter(key_func=_get_identifier, default_limits=[])


# ==================== S3: BRUTE-FORCE LOCKOUT (MongoDB) ====================

# Shared DB handle — populated by server.py at startup.
_lockout_db = None
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 60 * 24  # 24 hours
ATTEMPT_TTL_SECONDS = 60 * 60 * 24 * 2  # keep entry 2 days so lock persists


def init_lockout_store(db) -> None:
    """Bind the Motor database + ensure indexes."""
    global _lockout_db
    _lockout_db = db
    # TTL index: Mongo auto-expires entries after ATTEMPT_TTL_SECONDS past last_attempt.
    # We don't do this in an await because init is called synchronously; asyncio
    # will handle the coroutine when the event loop runs the create_index lazily.
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        loop.create_task(_ensure_indexes())
    except RuntimeError:
        pass


async def _ensure_indexes() -> None:
    if _lockout_db is None:
        return
    try:
        await _lockout_db.login_attempts.create_index("key", unique=True)
        await _lockout_db.login_attempts.create_index(
            "last_attempt",
            expireAfterSeconds=ATTEMPT_TTL_SECONDS,
        )
    except Exception as e:
        logger.warning(f"[SECURITY] Failed to create login_attempts indexes: {e}")


def _key(email: str, ip: str) -> str:
    return f"{(email or '').lower()}|{ip}"


async def check_login_lockout_async(email: str, ip: str) -> None:
    """Raise 429 if user/IP is locked out."""
    if _lockout_db is None:
        return
    entry = await _lockout_db.login_attempts.find_one({"key": _key(email, ip)}, {"_id": 0})
    if not entry:
        return
    if entry.get("count", 0) >= MAX_FAILED_ATTEMPTS:
        locked_until = entry.get("locked_until")
        if locked_until:
            if isinstance(locked_until, str):
                try:
                    locked_until = datetime.fromisoformat(locked_until.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    locked_until = None
            # Mongo returns naive UTC datetimes; make them aware
            if isinstance(locked_until, datetime) and locked_until.tzinfo is None:
                locked_until = locked_until.replace(tzinfo=timezone.utc)
            if locked_until and locked_until > datetime.now(timezone.utc):
                total_seconds = (locked_until - datetime.now(timezone.utc)).total_seconds()
                hours = int(total_seconds // 3600)
                minutes = int(round((total_seconds - hours * 3600) / 60))
                if minutes >= 60:
                    hours += 1
                    minutes = 0
                if hours > 0 and minutes > 0:
                    msg = f"Слишком много неудачных попыток входа. Попробуйте через {hours} ч {minutes} мин."
                elif hours > 0:
                    msg = f"Слишком много неудачных попыток входа. Попробуйте через {hours} ч."
                else:
                    msg = f"Слишком много неудачных попыток входа. Попробуйте через {max(minutes, 1)} мин."
                raise HTTPException(
                    status_code=429,
                    detail=msg
                )
            # Expired lockout — clear it
            await _lockout_db.login_attempts.delete_one({"key": _key(email, ip)})


async def record_login_failure_async(email: str, ip: str) -> None:
    """Increment failure counter, start lockout if threshold reached."""
    if _lockout_db is None:
        return
    k = _key(email, ip)
    now = datetime.now(timezone.utc)
    # Upsert + $inc
    await _lockout_db.login_attempts.update_one(
        {"key": k},
        {
            "$inc": {"count": 1},
            "$set": {"last_attempt": now},
            "$setOnInsert": {"first_attempt": now},
        },
        upsert=True,
    )
    entry = await _lockout_db.login_attempts.find_one({"key": k}, {"_id": 0})
    if entry and entry.get("count", 0) >= MAX_FAILED_ATTEMPTS and not entry.get("locked_until"):
        await _lockout_db.login_attempts.update_one(
            {"key": k},
            {"$set": {"locked_until": now + timedelta(minutes=LOCKOUT_MINUTES)}},
        )
        logger.warning(f"[SECURITY] Login lockout triggered for {k}")


async def record_login_success_async(email: str, ip: str) -> None:
    """Reset counter on successful login."""
    if _lockout_db is None:
        return
    await _lockout_db.login_attempts.delete_one({"key": _key(email, ip)})


# ===== Backwards-compatible sync wrappers =====
# auth_handler still calls sync versions; wrap them so they schedule onto the loop.
# These wrappers detect the running loop and await the coroutine.
import asyncio as _asyncio


def _run_async(coro):
    try:
        loop = _asyncio.get_running_loop()
    except RuntimeError:
        return _asyncio.run(coro)
    # Inside an already-running loop (FastAPI) — schedule and return
    return loop.create_task(coro)


def check_login_lockout(email: str, ip: str):
    # In async context the caller should await check_login_lockout_async directly.
    # Kept for backward compat — no-op when DB not initialised.
    if _lockout_db is None:
        return
    # We cannot raise from a scheduled task; caller should use async variant.
    # Returning coroutine lets auth_handler `await` it if needed.
    return check_login_lockout_async(email, ip)


def record_login_failure(email: str, ip: str):
    if _lockout_db is None:
        return
    return record_login_failure_async(email, ip)


def record_login_success(email: str, ip: str):
    if _lockout_db is None:
        return
    return record_login_success_async(email, ip)


# ==================== S4: PASSWORD STRENGTH ====================

PASSWORD_MIN_LEN = 8
_PW_LETTER_RE = re.compile(r"[A-Za-zА-Яа-я]")
_PW_DIGIT_RE = re.compile(r"\d")

# Single, unified password-requirements message. The same key is used by the
# frontend so the user always sees ONE consistent notification regardless of
# which specific rule failed (length / letters / digits).
PASSWORD_REQUIREMENTS_MSG = (
    "Пароль должен содержать минимум 8 символов, включая буквы и цифры"
)


def is_password_strong(password: str) -> bool:
    """Return True if password meets all requirements (length + letter + digit)."""
    if not password or len(password) < PASSWORD_MIN_LEN:
        return False
    if not _PW_LETTER_RE.search(password):
        return False
    if not _PW_DIGIT_RE.search(password):
        return False
    return True


def validate_password_strength(password: str) -> None:
    """Validate password. Raises a SINGLE unified error message on any failure
    so the user is never bounced between multiple different requirement errors."""
    if not is_password_strong(password):
        raise HTTPException(status_code=400, detail=PASSWORD_REQUIREMENTS_MSG)


# ==================== S7: SECURITY HEADERS with CSP nonce ====================

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds security headers + per-request CSP nonce.

    The nonce is accessible via `request.state.csp_nonce` for any endpoint
    that renders HTML and wants to embed an inline <script> safely.
    """

    async def dispatch(self, request: Request, call_next):
        nonce = secrets.token_urlsafe(16)
        request.state.csp_nonce = nonce

        response: Response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        # NOTE: deliberately NOT setting X-Frame-Options here — modern browsers
        # use the CSP `frame-ancestors` directive below (which allows Telegram
        # Web App). Adding X-Frame-Options: DENY here would BLOCK the Telegram
        # Mini App embed and conflict with the CSP.
        # F32: strengthen Referrer-Policy for URLs that expose secrets in query
        # (?token=…, ?code=…). For those pages send no Referer at all, so the
        # secret can't leak via outbound clicks. Everyone else keeps the
        # default strict-origin-when-cross-origin.
        _path = request.url.path or ""
        _sensitive = (
            "/reset-password" in _path
            or "/verify-email" in _path
            or "/verify-code" in _path
            or "/telegram/link" in _path
        )
        response.headers.setdefault(
            "Referrer-Policy",
            "no-referrer" if _sensitive else "strict-origin-when-cross-origin",
        )
        response.headers.setdefault(
            "Permissions-Policy",
            "geolocation=(), microphone=(), camera=()"
        )
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains"
        )
        # CSP. Allow inline scripts (CRA bootstrap) + the 3rd-party SDKs we use:
        # telegram.org (Telegram Web App SDK) and accounts.google.com (Google
        # Identity Services / GSI). 'connect-src' includes wss: + https: so the
        # WebSocket and TON Connect bridges work. img-src already allows https.
        # F4 hardening: removed 'unsafe-eval' from script-src (main XSS→RCE vector).
        # 'unsafe-inline' is retained for now — required by CRA bootstrap and
        # some legacy inline handlers; can be removed once all inline scripts
        # use the CSP nonce.
        csp = (
            "default-src 'self'; "
            f"script-src 'self' 'nonce-{nonce}' 'unsafe-inline' blob: "
            "https://telegram.org https://*.telegram.org "
            "https://accounts.google.com https://*.googleusercontent.com "
            "https://*.gstatic.com "
            "https://connect.facebook.net https://static.cloudflareinsights.com; "
            # PIXI/WebGL and other libs spin up Web Workers created from blob:
            # URLs (off-thread texture decode). Without an explicit worker-src
            # these fall back to script-src; some engines (notably iOS WebKit)
            # then BLOCK the blob worker → the map/emoji render one tick late or
            # not at all. child-src is the legacy fallback for older WebKit.
            "worker-src 'self' blob:; "
            "child-src 'self' blob:; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "img-src 'self' data: blob: https:; "
            "font-src 'self' data: https://fonts.gstatic.com; "
            "connect-src 'self' data: blob: wss: https: "
            "https://accounts.google.com https://oauth2.googleapis.com "
            "https://*.toncenter.com https://*.tonapi.io "
            "https://connect.facebook.net https://www.facebook.com "
            "https://static.cloudflareinsights.com https://cloudflareinsights.com; "
            "frame-src 'self' https://accounts.google.com https://oauth.telegram.org; "
            "frame-ancestors 'self' https://web.telegram.org https://*.telegram.org; "
            "base-uri 'self'; "
            "form-action 'self' https://accounts.google.com"
        )
        response.headers.setdefault("Content-Security-Policy", csp)
        # Expose the nonce so frontend-only pages (if any) can pull it at runtime
        response.headers.setdefault("X-CSP-Nonce", nonce)
        return response


# ==================== S6: LOG SANITIZATION ====================

_SENSITIVE_KEYS = {"password", "hashed_password", "token", "secret", "mnemonic", "private_key"}


def sanitize_for_log(obj):
    if isinstance(obj, dict):
        return {k: ("***" if k.lower() in _SENSITIVE_KEYS else sanitize_for_log(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_for_log(x) for x in obj]
    return obj
