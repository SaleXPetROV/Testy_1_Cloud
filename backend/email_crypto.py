"""F31 — email at rest: normalized hash (for lookups) + reversible encryption
(for sending). Dependency-free key management like the JWT secret: key comes
from EMAIL_ENC_KEY, else a persisted git-ignored file, so it survives restarts
and multiple workers without any manual server config.

Rollout is SAFE / staged:
  1. Deploy this code — new/updated users get `email_lc_hash` + `email_enc`
     while plaintext `email` is kept, and all lookups use `email_query()` which
     matches EITHER field (dual-read). Nothing breaks.
  2. Run `python migrate_email_hashing.py --backfill` to populate hash+enc for
     existing users.
  3. When validated, run `python migrate_email_hashing.py --drop-plaintext` to
     remove the plaintext `email` field. Lookups still work (hash), and code that
     reads `user["email"]` keeps working because loaders decrypt into `email`.
"""
import os
import hashlib
import logging
from pathlib import Path
from typing import Optional
from cryptography.fernet import Fernet

logger = logging.getLogger("server")


def _load_key() -> bytes:
    key = os.environ.get("EMAIL_ENC_KEY", "").strip()
    if key:
        return key.encode() if isinstance(key, str) else key
    key_file = os.environ.get("EMAIL_ENC_KEY_FILE", "").strip() or str(
        Path(__file__).resolve().parent / "email_enc.key"
    )
    try:
        existing = Path(key_file).read_text(encoding="utf-8").strip()
        if existing:
            return existing.encode()
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.warning("[F31] could not read email key file %s: %s", key_file, e)
    generated = Fernet.generate_key()
    try:
        Path(key_file).write_text(generated.decode(), encoding="utf-8")
        try:
            os.chmod(key_file, 0o600)
        except Exception:
            pass
        logger.warning("[F31] generated EMAIL_ENC_KEY and persisted to %s (git-ignored).", key_file)
    except Exception as e:
        logger.error("[F31] could not persist email key (%s); using ephemeral key.", e)
    return generated


_FERNET = Fernet(_load_key())


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def email_hash(email: str) -> str:
    return hashlib.sha256(normalize_email(email).encode("utf-8")).hexdigest()


def encrypt_email(email: str) -> str:
    return _FERNET.encrypt(normalize_email(email).encode("utf-8")).decode("utf-8")


def decrypt_email(enc: Optional[str]) -> Optional[str]:
    if not enc:
        return None
    try:
        return _FERNET.decrypt(enc.encode("utf-8")).decode("utf-8")
    except Exception:
        return None


def email_fields(email: str) -> dict:
    """Fields to persist for an email (dual-write). Keep `email` plaintext until
    the drop-plaintext migration is run."""
    e = normalize_email(email)
    return {"email": e, "email_lc_hash": email_hash(e), "email_enc": encrypt_email(e)}


def email_query(email: str) -> dict:
    """Dual-read lookup: matches by hash (post-migration) OR plaintext (pre)."""
    e = normalize_email(email)
    return {"$or": [{"email_lc_hash": email_hash(e)}, {"email": e}]}


def resolve_email(user_doc: dict) -> Optional[str]:
    """Return a usable plaintext email for a loaded user doc (for sending mail):
    plaintext if present, else decrypted `email_enc`."""
    if not user_doc:
        return None
    if user_doc.get("email"):
        return user_doc["email"]
    return decrypt_email(user_doc.get("email_enc"))
