"""Crypto helpers for encrypting/decrypting wallet mnemonics at rest.

Uses Fernet (AES-128-CBC + HMAC-SHA256) from `cryptography` library.
Key is loaded from the MNEMONIC_ENC_KEY env var. If not set, the module
runs in passthrough mode — no encryption/decryption happens (safe default
for a migration window where old plaintext values remain readable).

Encrypted values are stored with a fixed prefix `enc::` so we can tell
them apart from legacy plaintext mnemonics on the fly.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_ENC_PREFIX = "enc::"
_fernet: Optional[Fernet] = None


def _get_fernet() -> Optional[Fernet]:
    """Return cached Fernet instance if MNEMONIC_ENC_KEY is configured.

    F2 hardening: key can be supplied via one of (highest priority first):
      1. MNEMONIC_ENC_KEY env var (raw Fernet key, base64 44 chars)
      2. MNEMONIC_ENC_KEY_FILE env var — path to a file with the key.
         Recommended on prod: chmod 600, owned by service user, outside repo
         and DB filesystem (e.g. /etc/secrets/gramcity-mnemonic-key).
    """
    global _fernet
    if _fernet is not None:
        return _fernet
    key = os.environ.get("MNEMONIC_ENC_KEY", "").strip()
    if not key:
        key_file = os.environ.get("MNEMONIC_ENC_KEY_FILE", "").strip()
        if key_file and os.path.exists(key_file):
            try:
                with open(key_file, "r") as f:
                    key = f.read().strip()
            except Exception as e:
                logger.error("Cannot read MNEMONIC_ENC_KEY_FILE=%s: %s", key_file, e)
    if not key:
        return None
    try:
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
        return _fernet
    except Exception as e:
        logger.error("Invalid MNEMONIC_ENC_KEY: %s", e)
        return None


def is_encrypted(value: Optional[str]) -> bool:
    return isinstance(value, str) and value.startswith(_ENC_PREFIX)


def encrypt_mnemonic(plain: Optional[str]) -> Optional[str]:
    """Encrypt a mnemonic string. Returns None/empty for falsy input.
    If already encrypted, returns as-is. If no key configured, returns plain
    unchanged (passthrough) — a WARNING is logged so this is visible in prod
    logs. Deployments SHOULD configure MNEMONIC_ENC_KEY / MNEMONIC_ENC_KEY_FILE.
    """
    if not plain:
        return plain
    if is_encrypted(plain):
        return plain
    f = _get_fernet()
    if f is None:
        logger.warning(
            "encrypt_mnemonic: MNEMONIC_ENC_KEY not configured — storing "
            "mnemonic in PLAINTEXT. Configure a Fernet key in prod!"
        )
        return plain
    try:
        token = f.encrypt(plain.encode("utf-8")).decode("ascii")
        return _ENC_PREFIX + token
    except Exception as e:
        logger.error("encrypt_mnemonic failed: %s", e)
        return plain


def decrypt_mnemonic(value: Optional[str]) -> Optional[str]:
    """Decrypt an encrypted mnemonic. If the value isn't encrypted OR no
    key is configured, returns as-is (legacy/passthrough)."""
    if not value:
        return value
    if not is_encrypted(value):
        return value
    f = _get_fernet()
    if f is None:
        logger.warning("decrypt_mnemonic: value is encrypted but MNEMONIC_ENC_KEY is not set")
        return value
    try:
        token = value[len(_ENC_PREFIX):]
        return f.decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:
        logger.error("decrypt_mnemonic: invalid token (key mismatch or corruption)")
        return None
    except Exception as e:
        logger.error("decrypt_mnemonic failed: %s", e)
        return None


async def migrate_plaintext_to_encrypted(db) -> dict:
    """One-shot migration: find any plaintext mnemonic in admin_settings /
    admin_wallets and re-store it encrypted. Idempotent.

    Covers ALL types that store a mnemonic:
      - admin_settings.type in {withdrawal_wallet, sender_wallet, contract_deployer}
      - admin_wallets (percentage-based sender wallets)
    """
    f = _get_fernet()
    if f is None:
        return {"status": "skipped", "reason": "MNEMONIC_ENC_KEY not configured"}

    stats = {"admin_settings": 0, "admin_wallets": 0}

    async for doc in db.admin_settings.find({"mnemonic": {"$exists": True, "$ne": ""}}):
        value = doc.get("mnemonic") or ""
        if is_encrypted(value):
            continue
        enc = encrypt_mnemonic(value)
        if enc and enc != value:
            await db.admin_settings.update_one(
                {"_id": doc["_id"]},
                {"$set": {"mnemonic": enc}}
            )
            stats["admin_settings"] += 1

    async for doc in db.admin_wallets.find({"mnemonic": {"$exists": True, "$ne": ""}}):
        value = doc.get("mnemonic") or ""
        if is_encrypted(value):
            continue
        enc = encrypt_mnemonic(value)
        if enc and enc != value:
            await db.admin_wallets.update_one(
                {"_id": doc["_id"]},
                {"$set": {"mnemonic": enc}}
            )
            stats["admin_wallets"] += 1

    stats["status"] = "done"
    return stats
