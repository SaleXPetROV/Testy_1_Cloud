"""Startup security guard.

In production (``ENV``/``ENVIRONMENT``/``APP_ENV`` = production|prod) the app must
refuse to start with missing or well-known-default secrets, so a deploy can never
silently run with the public ``admin-secret-key-2025`` or an unset wallet key.

Called once from server.py at import time.
"""
import logging
import os

logger = logging.getLogger(__name__)

KNOWN_BAD = {
    "admin-secret-key-2025", "ton-city-builder-secret-key-2025",
    "change-me", "changeme", "secret", "admin", "test", "",
}


def is_production() -> bool:
    env = (os.environ.get("ENV") or os.environ.get("ENVIRONMENT") or os.environ.get("APP_ENV") or "").strip().lower()
    return env in ("production", "prod")


def _check(name: str, value: str, *, min_len: int = 16) -> list:
    problems = []
    v = (value or "").strip()
    if not v:
        problems.append(f"{name} is not set")
    elif v.lower() in KNOWN_BAD:
        problems.append(f"{name} uses a well-known default value")
    elif len(v) < min_len:
        problems.append(f"{name} is too short (min {min_len} chars)")
    return problems


def startup_security_check(*, admin_secret: str, jwt_secret: str) -> None:
    """Collect secret problems. In production raise RuntimeError (block start);
    otherwise just warn so local dev stays convenient."""
    problems = []
    problems += _check("ADMIN_SECRET", admin_secret)
    problems += _check("JWT_SECRET_KEY/SECRET_KEY", jwt_secret, min_len=32)

    # Payout wallet: warn if a mnemonic env is present but obviously a placeholder.
    mnem = (os.environ.get("TON_WALLET_MNEMONIC") or "").strip()
    if mnem and len(mnem.split()) not in (0, 24):
        problems.append("TON_WALLET_MNEMONIC is set but is not 24 words")

    if not problems:
        logger.info("startup security check: OK")
        return

    if is_production():
        msg = ("Refusing to start in production with insecure configuration:\n  - "
               + "\n  - ".join(problems)
               + "\nSet strong values (e.g. `openssl rand -hex 32`) for these in the environment.")
        logger.critical(msg)
        raise RuntimeError(msg)
    logger.warning("Insecure configuration (allowed outside production): " + "; ".join(problems))
