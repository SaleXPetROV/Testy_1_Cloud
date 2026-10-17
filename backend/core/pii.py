"""Encryption of personal data at rest (AES-256-GCM) + blind indexes (HMAC-SHA256).

    PII_ENC_KEY    base64, 32 bytes — encrypts values  (python -m scripts.encrypt_pii --new-keys)
    PII_INDEX_KEY  base64, 32 bytes — blind index: equal values give equal HMACs, so the
                   database can group / look up WITHOUT knowing the value
Both keys live only in the server environment (never in the database or the repo).
Encrypted values look like "enc1:<base64(nonce|ciphertext|tag)>"; `dec()` returns plain
values unchanged, so old records keep working until the migration encrypts them.
Losing PII_ENC_KEY means the encrypted values can't be read any more — keep a copy offline.
"""
import base64
import hashlib
import hmac
import logging
import os
from functools import lru_cache
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)
PREFIX = "enc1:"


@lru_cache(maxsize=1)
def _keys():
    def load(name):
        raw = os.environ.get(name, "")
        try:
            k = base64.b64decode(raw) if raw else b""
        except Exception:
            k = b""
        return k if len(k) == 32 else None
    enc, idx = load("PII_ENC_KEY"), load("PII_INDEX_KEY")
    if not enc or not idx:
        logger.warning("[PII] PII_ENC_KEY / PII_INDEX_KEY not set — personal data is stored WITHOUT encryption")
    return enc, idx


def enabled() -> bool:
    enc, idx = _keys()
    return bool(enc and idx)


def enc(value: Optional[str]) -> Optional[str]:
    if value in (None, ""):
        return value
    value = str(value)
    if value.startswith(PREFIX):
        return value
    key = _keys()[0]
    if not key:
        return value
    nonce = os.urandom(12)
    return PREFIX + base64.b64encode(nonce + AESGCM(key).encrypt(nonce, value.encode(), b"pii")).decode()


def dec(value: Optional[str]) -> Optional[str]:
    if not isinstance(value, str) or not value.startswith(PREFIX):
        return value
    key = _keys()[0]
    if not key:
        return None
    try:
        raw = base64.b64decode(value[len(PREFIX):])
        return AESGCM(key).decrypt(raw[:12], raw[12:], b"pii").decode()
    except Exception:
        return None


def bidx(value: Optional[str]) -> Optional[str]:
    """Blind index of a value (normalised: trimmed, lower-case)."""
    if value in (None, ""):
        return None
    key = _keys()[1]
    norm = str(value).strip().lower().encode()
    if not key:
        return hashlib.sha256(b"no-index-key:" + norm).hexdigest()
    return hmac.new(key, norm, hashlib.sha256).hexdigest()
