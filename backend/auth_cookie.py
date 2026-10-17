"""F7 + F16 — httpOnly cookie session layer + CSRF protection.

Design (backward compatible, keeps Bearer fallback per user's choice):
- Auth endpoints keep returning `{"token": ...}` in JSON (mobile / Telegram Mini
  App / legacy clients keep using `Authorization: Bearer`).
- We ALSO set the JWT in an httpOnly `access_token` cookie (Secure + SameSite=Lax)
  so browser sessions are protected from XSS token theft, and a readable
  `csrf_token` cookie for double-submit CSRF.
- `CookieOrBearer` extracts the token from the cookie FIRST, then the
  Authorization header — so every endpoint that used `Depends(security)` now
  transparently accepts cookie auth.
- CSRF middleware protects mutating requests. SameSite=Lax already blocks
  cross-site cookie POSTs; the double-submit check is defense-in-depth for any
  cookie-only client.
"""
import os
import secrets as _secrets
from typing import Optional
from fastapi import Request, HTTPException
from fastapi.security import HTTPAuthorizationCredentials

ACCESS_COOKIE = "access_token"
CSRF_COOKIE = "csrf_token"


def _cookie_opts() -> dict:
    return {
        "secure": os.environ.get("COOKIE_SECURE", "true").strip().lower() in ("1", "true", "yes"),
        "samesite": os.environ.get("COOKIE_SAMESITE", "lax").strip().lower(),
        "max_age": int(os.environ.get("COOKIE_MAX_AGE", str(7 * 24 * 3600))),
        "path": "/",
    }


def extract_token(request: Request) -> Optional[str]:
    """Token from httpOnly cookie first, then Authorization: Bearer (fallback)."""
    tok = request.cookies.get(ACCESS_COOKIE)
    if tok and tok not in ("null", "undefined", ""):
        return tok
    auth = request.headers.get("Authorization") or request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        val = auth.split(" ", 1)[1].strip()
        if val and val not in ("null", "undefined"):
            return val
    return None


class CookieOrBearer:
    """Drop-in replacement for HTTPBearer that also reads the httpOnly cookie."""

    def __init__(self, auto_error: bool = False):
        self.auto_error = auto_error

    async def __call__(self, request: Request) -> Optional[HTTPAuthorizationCredentials]:
        token = extract_token(request)
        if not token:
            if self.auto_error:
                raise HTTPException(status_code=401, detail="Not authenticated")
            return None
        return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def set_auth_cookies(response, token: str) -> str:
    opts = _cookie_opts()
    response.set_cookie(ACCESS_COOKIE, token, httponly=True, **opts)
    csrf = _secrets.token_urlsafe(32)
    # CSRF cookie must be readable by JS (double-submit), so NOT httpOnly.
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, **opts)
    return csrf


def clear_auth_cookies(response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
