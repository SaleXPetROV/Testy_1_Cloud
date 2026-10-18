"""Reversible encryption for TOTP 2FA secrets at rest.

TOTP secrets (base32 strings from pyotp) MUST be stored encrypted but
reversibly — pyotp needs the original secret to verify codes, so hashing is not
an option. We use Fernet (authenticated symmetric encryption) with a key read
ONLY from the TOTP_ENC_KEY environment variable.

Backward compatibility: `decrypt_secret` transparently returns legacy plaintext
secrets (stored before encryption was introduced) unchanged, so existing 2FA
users keep working until the one-time migration re-encrypts them.
"""
import os
import logging
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_KEY = (os.environ.get("TOTP_ENC_KEY") or "").strip()
try:
    _fernet = Fernet(_KEY.encode()) if _KEY else None
except Exception as e:  # malformed key
    logger.error(f"Invalid TOTP_ENC_KEY, 2FA secrets will NOT be encrypted: {e}")
    _fernet = None


def encrypt_secret(secret: str) -> str:
    """Encrypt a TOTP secret for storage (returns a Fernet token string)."""
    if not secret:
        return secret
    if _fernet is None:
        logger.warning("TOTP_ENC_KEY not configured — 2FA secret stored UNENCRYPTED")
        return secret
    return _fernet.encrypt(secret.encode()).decode()


def _looks_base32(value: str) -> bool:
    """True if `value` is a plausible pyotp base32 secret (safe to feed to TOTP).
    pyotp raises binascii.Error on non-base32 input, so we gate on this."""
    import base64 as _b64
    if not value:
        return False
    try:
        _b64.b32decode(value.strip().upper() + "=" * ((8 - len(value.strip()) % 8) % 8))
        return True
    except Exception:
        return False


def decrypt_secret(value: str) -> str:
    """Return the plaintext TOTP secret. Legacy plaintext values are returned
    unchanged so pre-encryption 2FA setups keep verifying.

    Hardening: if the value is an ENCRYPTED token we cannot decrypt (missing or
    changed TOTP_ENC_KEY) we return "" instead of the raw ciphertext. Passing a
    Fernet token to `pyotp.TOTP(...).verify()` raises binascii.Error ("Non-base32
    digit found") → an unhandled 500 "internal error" on the 2FA screen. Returning
    "" makes verification cleanly FAIL (401 "invalid code") and we log the real
    cause so the operator knows TOTP_ENC_KEY must be fixed."""
    if not value:
        return value
    if _fernet is not None:
        try:
            return _fernet.decrypt(value.encode()).decode()
        except InvalidToken:
            pass  # legacy plaintext OR key mismatch → decide below
        except Exception:
            pass
    # Could not decrypt (no key, or key mismatch). If it looks like a valid
    # base32 secret it is legacy plaintext — return as-is. Otherwise it is an
    # undecryptable ciphertext: return "" so pyotp never crashes.
    if _looks_base32(value):
        return value
    logger.error(
        "Cannot decrypt a stored TOTP secret — it is not valid base32 and does "
        "not match the current TOTP_ENC_KEY. 2FA will fail for this user until "
        "TOTP_ENC_KEY is restored to the value used when 2FA was enabled (or the "
        "user resets 2FA). Returning empty secret to avoid a 500."
    )
    return ""


def is_encrypted(value: str) -> bool:
    """True if `value` is a valid Fernet token decryptable with the current key."""
    if not value or _fernet is None:
        return False
    try:
        _fernet.decrypt(value.encode())
        return True
    except Exception:
        return False


def encryption_enabled() -> bool:
    return _fernet is not None
