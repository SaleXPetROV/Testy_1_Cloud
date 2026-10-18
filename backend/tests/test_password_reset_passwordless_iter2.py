"""
Iteration-2 backend regression: password-reset now sends email for existing
accounts even if they have no password yet (Google/TG/wallet signups).

Verifications:
  1. Normal password account: request-password-reset returns generic success
     AND backend log contains 'Email sent via Resend to <email>'.
  2. Passwordless (Google) account: request-password-reset now ALSO sends via
     Resend (regression: this used to be silently skipped).
  3. Non-existent email: same generic success, but NO 'Email sent via Resend'
     log line for that address (anti-enumeration).
  4. Full E2E for the passwordless account: request → read code from log →
     verify-reset-code → reset-password → login with new password succeeds
     (confirms hashed_password was set on a previously passwordless user).
"""
import os
import re
import time
import uuid
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

BACKEND_ERR_LOG = "/var/log/supervisor/backend.err.log"
BACKEND_OUT_LOG = "/var/log/supervisor/backend.out.log"

ADMIN_EMAIL = "admin@gramcity.app"
ADMIN_PASSWORD = "GramAdmin!2026"
GOOGLE_EMAIL = "googleuser_test@gmail.com"
NON_EXISTENT_EMAIL = "definitely-not-a-user-9999@gmail.com"


# ---------- helpers ----------

def _read_logs_tail(bytes_to_read: int = 200_000) -> str:
    """Read tail of both backend log files, concatenated."""
    chunks = []
    for path in (BACKEND_ERR_LOG, BACKEND_OUT_LOG):
        try:
            with open(path, "rb") as f:
                try:
                    f.seek(-bytes_to_read, os.SEEK_END)
                except OSError:
                    f.seek(0)
                chunks.append(f.read().decode("utf-8", errors="replace"))
        except FileNotFoundError:
            pass
    return "\n".join(chunks)


def _log_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _read_logs_since(offsets: dict) -> str:
    """Read log content added since the recorded offsets."""
    chunks = []
    for path, start in offsets.items():
        try:
            with open(path, "rb") as f:
                f.seek(start)
                chunks.append(f.read().decode("utf-8", errors="replace"))
        except FileNotFoundError:
            pass
    return "\n".join(chunks)


def _snapshot_offsets() -> dict:
    return {p: _log_size(p) for p in (BACKEND_ERR_LOG, BACKEND_OUT_LOG)}


# ---------- fixtures ----------

@pytest.fixture(scope="module")
def mongo_db():
    client = MongoClient(MONGO_URL)
    yield client[DB_NAME]
    client.close()


@pytest.fixture(scope="module", autouse=True)
def seed_google_user(mongo_db):
    """Ensure a passwordless Google-registered user exists."""
    users = mongo_db.users
    existing = users.find_one({"email": GOOGLE_EMAIL})
    if not existing:
        users.insert_one({
            "id": str(uuid.uuid4()),
            "username": "googleuser_test",
            "email": GOOGLE_EMAIL,
            "hashed_password": None,
            "registration_method": "google",
            "email_verified": True,
            "agreement_accepted": True,
            "language": "en",
            "coins": 0,
        })
    else:
        # Reset to passwordless state for a deterministic run.
        users.update_one(
            {"email": GOOGLE_EMAIL},
            {"$set": {"hashed_password": None, "registration_method": "google"}},
        )
    yield
    # cleanup — leave the seed user in place for reuse; only unset the password.
    users.update_one(
        {"email": GOOGLE_EMAIL},
        {"$set": {"hashed_password": None, "registration_method": "google"}},
    )


# ---------- tests ----------

class TestPasswordResetPasswordlessFix:

    def test_1_normal_password_account_sends_email(self):
        offsets = _snapshot_offsets()
        r = requests.post(
            f"{BASE_URL}/api/auth/request-password-reset",
            json={"email": ADMIN_EMAIL},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("status") == "success"
        assert body.get("message") == "code_sent"
        # Give the async send a moment to flush the log line.
        time.sleep(2.0)
        logs = _read_logs_since(offsets)
        assert f"Email sent via Resend to {ADMIN_EMAIL}" in logs, \
            f"expected Resend log line for {ADMIN_EMAIL}; last logs:\n{logs[-4000:]}"

    def test_2_passwordless_google_account_now_sends_email(self, mongo_db):
        # Sanity: the seed really is passwordless.
        u = mongo_db.users.find_one({"email": GOOGLE_EMAIL})
        assert u is not None, "seeded google user missing"
        assert u.get("hashed_password") in (None, ""), \
            f"seed precondition failed: hashed_password={u.get('hashed_password')!r}"

        offsets = _snapshot_offsets()
        r = requests.post(
            f"{BASE_URL}/api/auth/request-password-reset",
            json={"email": GOOGLE_EMAIL},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("status") == "success"
        assert body.get("message") == "code_sent"
        time.sleep(2.0)
        logs = _read_logs_since(offsets)
        # THE regression assertion — this used to be silently skipped.
        assert f"Email sent via Resend to {GOOGLE_EMAIL}" in logs, \
            f"passwordless account got NO send; last logs:\n{logs[-4000:]}"
        # Also confirm a reset code was stored.
        assert f"Storing reset code for {GOOGLE_EMAIL}" in logs, \
            "expected 'Storing reset code' log for passwordless user"

    def test_3_nonexistent_email_generic_success_no_send(self):
        offsets = _snapshot_offsets()
        r = requests.post(
            f"{BASE_URL}/api/auth/request-password-reset",
            json={"email": NON_EXISTENT_EMAIL},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Anti-enumeration: same shape as the "real send" branch.
        assert body.get("status") == "success"
        assert body.get("message") == "code_sent"
        time.sleep(1.5)
        logs = _read_logs_since(offsets)
        assert f"Email sent via Resend to {NON_EXISTENT_EMAIL}" not in logs, \
            "unknown email must NOT trigger a Resend send"
        assert f"Storing reset code for {NON_EXISTENT_EMAIL}" not in logs, \
            "unknown email must NOT get a reset code stored"

    def test_4_full_reset_flow_end_to_end_for_passwordless(self, mongo_db):
        # Request a fresh code for the google account.
        offsets = _snapshot_offsets()
        r = requests.post(
            f"{BASE_URL}/api/auth/request-password-reset",
            json={"email": GOOGLE_EMAIL},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        time.sleep(2.0)
        logs = _read_logs_since(offsets)

        # Pull the most recent stored code out of the log line
        # 'Storing reset code for googleuser_test@gmail.com: <CODE>'.
        matches = re.findall(
            rf"Storing reset code for {re.escape(GOOGLE_EMAIL)}:\s*'?([A-Za-z0-9]{{8}})'?",
            logs,
        )
        assert matches, f"could not extract reset code from logs; tail:\n{logs[-4000:]}"
        code = matches[-1]

        # Verify code.
        rv = requests.post(
            f"{BASE_URL}/api/auth/verify-reset-code",
            json={"email": GOOGLE_EMAIL, "code": code},
            timeout=30,
        )
        assert rv.status_code == 200, rv.text
        vbody = rv.json()
        assert vbody.get("valid") is True

        # Reset password.
        new_password = "NewPass!2026"
        rp = requests.post(
            f"{BASE_URL}/api/auth/reset-password",
            json={"email": GOOGLE_EMAIL, "code": code, "new_password": new_password},
            timeout=30,
        )
        assert rp.status_code == 200, rp.text
        pbody = rp.json()
        assert pbody.get("message") == "password_changed"

        # Verify persistence: hashed_password is now set in Mongo.
        u = mongo_db.users.find_one({"email": GOOGLE_EMAIL})
        assert u is not None
        assert u.get("hashed_password"), \
            "reset-password should have SET a real hashed_password on the passwordless account"

        # Login with new password.
        rl = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": GOOGLE_EMAIL, "password": new_password},
            timeout=30,
        )
        assert rl.status_code == 200, f"login failed after reset: {rl.status_code} {rl.text}"
        lbody = rl.json()
        # Token key varies across versions; accept common shapes.
        assert any(k in lbody for k in ("access_token", "token", "session_token")) or lbody.get("status") == "success", \
            f"unexpected login response: {lbody}"
