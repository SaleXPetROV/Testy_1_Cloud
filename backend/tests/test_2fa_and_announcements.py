"""Tests for:
 - 2FA/TOTP secrets encrypted at rest (Fernet)
 - Legacy plaintext 2FA secrets still verify (backward compatibility)
 - Announcements: no 📢 prefix (code inspection), publish-now works,
   scheduled multi-language announcement publishes at scheduled time.
"""
import os
import sys
import time
import asyncio
import pathlib
from datetime import datetime, timedelta, timezone

import pytest
import pyotp
import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

# Load backend .env explicitly so MONGO_URL/DB_NAME/TOTP_ENC_KEY are available.
BACKEND_DIR = pathlib.Path("/app/backend")
load_dotenv(BACKEND_DIR / ".env")
sys.path.insert(0, str(BACKEND_DIR))

FRONTEND_ENV = pathlib.Path("/app/frontend/.env")
load_dotenv(FRONTEND_ENV, override=False)

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")
TOTP_ENC_KEY = os.environ.get("TOTP_ENC_KEY")

assert BASE_URL, "REACT_APP_BACKEND_URL missing"
assert MONGO_URL and DB_NAME, "MONGO_URL/DB_NAME missing"

TEST_USER_EMAIL = "testuser@example.com"
TEST_USER_PASSWORD = "Test1234!"
ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")


# ─────────────────────────── fixtures ───────────────────────────
@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def db(event_loop):
    client = AsyncIOMotorClient(MONGO_URL)
    return client[DB_NAME]


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed {r.status_code}: {r.text}"
    return r.json().get("token")


@pytest.fixture(scope="session")
def user_token():
    return _login(TEST_USER_EMAIL, TEST_USER_PASSWORD)


@pytest.fixture(scope="session")
def admin_token():
    return _login(ADMIN_EMAIL, ADMIN_PASSWORD)


async def _cleanup_2fa(db, email):
    await db.users.update_one(
        {"email": email},
        {"$set": {"is_2fa_enabled": False},
         "$unset": {"two_factor_secret": "", "pending_2fa_secret": "", "backup_codes": ""}}
    )


# ─────────────────────────── 2FA encryption ───────────────────────────
class Test2FAEncryption:
    def test_full_2fa_setup_stores_encrypted(self, user_token, db, event_loop):
        headers = {"Authorization": f"Bearer {user_token}"}

        # Ensure clean starting state (in case a prior run left 2FA enabled).
        event_loop.run_until_complete(_cleanup_2fa(db, TEST_USER_EMAIL))

        # 1. start setup
        r = requests.post(f"{BASE_URL}/api/security/totp/setup/start",
                          headers=headers, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        secret = data["secret"]
        assert secret and secret.isalnum(), "plaintext secret should be base32"

        # 2. Verify DB stores ENCRYPTED pending_2fa_secret (Fernet gAAAAA…)
        async def _check_pending():
            u = await db.users.find_one({"email": TEST_USER_EMAIL})
            return u.get("pending_2fa_secret")

        pending_enc = event_loop.run_until_complete(_check_pending())
        assert pending_enc, "pending_2fa_secret not stored"
        assert pending_enc != secret, "pending_2fa_secret is stored as PLAINTEXT (bug)"
        assert pending_enc.startswith("gAAAAA"), (
            f"pending_2fa_secret should be Fernet gAAAAA…, got prefix {pending_enc[:10]}"
        )

        # 3. Confirm setup with a valid TOTP code
        code = pyotp.TOTP(secret).now()
        r = requests.post(
            f"{BASE_URL}/api/security/totp/setup/confirm",
            params={"code": code}, headers=headers, timeout=30,
        )
        assert r.status_code == 200, r.text
        confirm = r.json()
        assert confirm["status"] == "enabled"
        assert isinstance(confirm.get("backup_codes"), list) and confirm["backup_codes"]

        # 4. two_factor_secret in DB must be encrypted, pending removed
        async def _check_confirmed():
            u = await db.users.find_one({"email": TEST_USER_EMAIL})
            return u

        u = event_loop.run_until_complete(_check_confirmed())
        stored = u.get("two_factor_secret")
        assert stored and stored.startswith("gAAAAA"), (
            f"two_factor_secret must be encrypted, got prefix {str(stored)[:10]}"
        )
        assert u.get("is_2fa_enabled") is True
        assert not u.get("pending_2fa_secret")

        # 5. Verify decrypt-on-verify: /totp/verify accepts a fresh code
        code2 = pyotp.TOTP(secret).now()
        r = requests.post(f"{BASE_URL}/api/security/totp/verify",
                          params={"code": code2}, headers=headers, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json().get("verified") is True

        # CLEANUP — always disable 2FA on testuser
        event_loop.run_until_complete(_cleanup_2fa(db, TEST_USER_EMAIL))

    def test_legacy_plaintext_secret_still_verifies(self, user_token, db, event_loop):
        """Simulate a legacy user whose two_factor_secret is PLAINTEXT
        (pre-encryption). /totp/verify must transparently accept it via
        decrypt_secret() returning legacy value unchanged."""
        headers = {"Authorization": f"Bearer {user_token}"}
        legacy_secret = "JBSWY3DPEHPK3PXP"  # base32 test secret

        async def _write_plain():
            await db.users.update_one(
                {"email": TEST_USER_EMAIL},
                {"$set": {"two_factor_secret": legacy_secret, "is_2fa_enabled": True},
                 "$unset": {"pending_2fa_secret": ""}}
            )
        event_loop.run_until_complete(_write_plain())

        try:
            code = pyotp.TOTP(legacy_secret).now()
            r = requests.post(f"{BASE_URL}/api/security/totp/verify",
                              params={"code": code}, headers=headers, timeout=30)
            assert r.status_code == 200, r.text
            assert r.json().get("verified") is True
            assert r.json().get("method") == "totp"
        finally:
            event_loop.run_until_complete(_cleanup_2fa(db, TEST_USER_EMAIL))


# ─────────────────────────── Announcements ───────────────────────────
class TestAnnouncements:
    def test_no_speaker_emoji_in_code(self):
        """Code-inspection: verify 📢 prefix removed from c_caption/tg_caption."""
        src = (BACKEND_DIR / "server.py").read_text(encoding="utf-8")
        assert "📢" not in src, "📢 emoji found in backend/server.py — must be removed"

    def test_publish_now_returns_published(self, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        payload = {
            "title": "TEST_pub_now",
            "message": "TEST publish-now body",
            "lang": "all",
        }
        r = requests.post(f"{BASE_URL}/api/admin/announcement",
                          json=payload, headers=headers, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "published"
        assert data.get("id")

    def test_scheduled_multilang_publishes_at_time(self, admin_token, db, event_loop):
        headers = {"Authorization": f"Bearer {admin_token}"}
        # Schedule ~45s in the future. The scheduler runs every 60s so we
        # need to wait up to ~scheduled_at + 70s ≈ 115s.
        sched_at = datetime.now(timezone.utc) + timedelta(seconds=45)
        payload = {
            "title": "TEST_sched_multi",
            "message": "fallback body",
            "lang": "multi",
            "translations": {
                "gb": {
                    "title": "TEST scheduled EN",
                    "message": "English body",
                    "buttons": [{"text": "Open", "url": "https://example.com"}],
                },
                "ru": {
                    "title": "TEST scheduled RU",
                    "message": "Русский текст",
                },
            },
            "scheduled_at": sched_at.isoformat(),
        }
        r = requests.post(f"{BASE_URL}/api/admin/announcement",
                          json=payload, headers=headers, timeout=30)
        assert r.status_code == 200, r.text
        ann = r.json()
        assert ann["status"] == "scheduled", ann
        assert ann.get("scheduled_at")
        ann_id = ann["id"]

        # Poll DB (also test via public? we use DB for reliability) up to 130s
        async def _wait_for_published(_id, timeout_s=130):
            deadline = time.time() + timeout_s
            last = None
            while time.time() < deadline:
                doc = await db.announcements.find_one({"id": _id})
                last = doc
                if doc and doc.get("status") == "published":
                    return doc
                await asyncio.sleep(5)
            return last

        final = event_loop.run_until_complete(_wait_for_published(ann_id))
        assert final is not None, "announcement missing from DB"
        assert final.get("status") == "published", (
            f"scheduled announcement did not publish in time; status={final.get('status')}"
        )
        assert final.get("published_at"), "published_at not set"

        # Cleanup
        event_loop.run_until_complete(db.announcements.delete_one({"id": ann_id}))
