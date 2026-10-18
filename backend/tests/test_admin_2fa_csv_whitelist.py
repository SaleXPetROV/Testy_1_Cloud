"""
Test admin 2FA middleware whitelist for CSV export endpoints.
Bug fix: CSV export endpoints should NOT require X-Admin-TOTP header even
when admin has 2FA enabled.
"""
import os
import asyncio
import pytest
import requests
import pyotp
from motor.motor_asyncio import AsyncIOMotorClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")

MONGO_URL = None
DB_NAME = None
with open("/app/backend/.env") as f:
    for line in f:
        if line.startswith("MONGO_URL="):
            MONGO_URL = line.split("=", 1)[1].strip().strip('"').strip("'")
        elif line.startswith("DB_NAME="):
            DB_NAME = line.split("=", 1)[1].strip().strip('"').strip("'")

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASS = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PASS = "Test1234!"
TOTP_SECRET = "JBSWY3DPEHPK3PXP"


def _login_plain(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=15)
    return r


@pytest.fixture(scope="module")
def admin_token():
    r = _login_plain(ADMIN_EMAIL, ADMIN_PASS)
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text}"
    data = r.json()
    assert "token" in data, f"No token in login response: {data}"
    return data["token"]


@pytest.fixture(scope="module")
def user_token():
    r = _login_plain(USER_EMAIL, USER_PASS)
    assert r.status_code == 200, f"User login failed: {r.status_code} {r.text}"
    return r.json()["token"]


# --- Test 1 & 2: CSV export with 2FA DISABLED (default) ---
class TestCsvExportsNo2FA:
    def test_transactions_export_csv_post(self, admin_token):
        r = requests.post(
            f"{BASE_URL}/api/admin/transactions/export-csv",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={},
            timeout=30,
        )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:500]}"
        body = r.content
        assert body.startswith(b"\xef\xbb\xbf"), "Missing UTF-8 BOM"
        text = body.decode("utf-8-sig")
        first_line, _, rest = text.partition("\r\n")
        assert first_line == "sep=,", f"First line should be 'sep=,' but was: {first_line!r}"
        header_line = rest.split("\r\n", 1)[0]
        cols = header_line.split(",")
        assert len(cols) == 11, f"Expected 11 columns, got {len(cols)}: {header_line}"
        for c in cols:
            assert c.startswith('"') and c.endswith('"'), f"Column not quoted: {c}"

    def test_telegram_bot_stats_export_csv_get(self, admin_token):
        r = requests.get(
            f"{BASE_URL}/api/admin/telegram-bot-stats/export-csv",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=30,
        )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:500]}"
        body = r.content
        text = body.decode("utf-8-sig", errors="replace")
        # Find header line (first line may be sep=,)
        lines = text.split("\r\n") if "\r\n" in text else text.split("\n")
        # Header could be first or second line
        header = lines[1] if lines[0].startswith("sep=") else lines[0]
        cols = header.split(",")
        assert len(cols) == 12, f"Expected 12 columns, got {len(cols)}: {header}"


# --- Test 5: Non-admin cannot access CSV exports ---
class TestNonAdminForbidden:
    def test_user_cannot_post_transactions_export(self, user_token):
        r = requests.post(
            f"{BASE_URL}/api/admin/transactions/export-csv",
            headers={"Authorization": f"Bearer {user_token}"},
            json={},
            timeout=15,
        )
        assert r.status_code == 403, f"Expected 403, got {r.status_code}: {r.text[:300]}"

    def test_user_cannot_get_tg_bot_stats_export(self, user_token):
        r = requests.get(
            f"{BASE_URL}/api/admin/telegram-bot-stats/export-csv",
            headers={"Authorization": f"Bearer {user_token}"},
            timeout=15,
        )
        assert r.status_code == 403, f"Expected 403, got {r.status_code}: {r.text[:300]}"


# --- Test 3: With 2FA ENABLED ---
class TestCsvExportsWith2FA:
    @pytest.fixture(scope="class", autouse=True)
    def enable_2fa(self):
        """Enable 2FA on admin, then reset after tests."""
        async def _set(enabled, secret):
            client = AsyncIOMotorClient(MONGO_URL)
            db = client[DB_NAME]
            await db.users.update_one(
                {"email": ADMIN_EMAIL},
                {"$set": {"is_2fa_enabled": enabled, "two_factor_secret": secret}},
            )
            client.close()

        asyncio.get_event_loop().run_until_complete(_set(True, TOTP_SECRET))
        yield
        # Reset admin back to 2FA disabled
        asyncio.get_event_loop().run_until_complete(_set(False, None))

    @pytest.fixture(scope="class")
    def admin_2fa_token(self):
        # Step 1: plain login -> should ask for 2FA
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
            timeout=15,
        )
        assert r.status_code == 200, f"login step1 failed: {r.status_code} {r.text}"
        data = r.json()
        assert data.get("requires_2fa") is True, f"Expected requires_2fa=true, got {data}"
        # Step 2: login-2fa
        totp = pyotp.TOTP(TOTP_SECRET).now()
        r2 = requests.post(
            f"{BASE_URL}/api/auth/login-2fa",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASS, "totp_code": totp},
            timeout=15,
        )
        assert r2.status_code == 200, f"login-2fa failed: {r2.status_code} {r2.text}"
        d = r2.json()
        assert "token" in d, f"No token: {d}"
        return d["token"]

    def test_a_transactions_export_bypasses_2fa_gate(self, admin_2fa_token):
        # No X-Admin-TOTP header — should still work due to whitelist
        r = requests.post(
            f"{BASE_URL}/api/admin/transactions/export-csv",
            headers={"Authorization": f"Bearer {admin_2fa_token}"},
            json={},
            timeout=30,
        )
        assert r.status_code == 200, f"Whitelist bypass failed: {r.status_code} {r.text[:500]}"

    def test_b_tg_bot_stats_export_get_bypasses_2fa(self, admin_2fa_token):
        r = requests.get(
            f"{BASE_URL}/api/admin/telegram-bot-stats/export-csv",
            headers={"Authorization": f"Bearer {admin_2fa_token}"},
            timeout=30,
        )
        assert r.status_code == 200, f"GET was blocked by 2FA gate: {r.status_code} {r.text[:300]}"

    def test_c_announcement_still_gated(self, admin_2fa_token):
        # POST /api/admin/announcement without X-Admin-TOTP should be 401
        r = requests.post(
            f"{BASE_URL}/api/admin/announcement",
            headers={"Authorization": f"Bearer {admin_2fa_token}"},
            json={"message": "test", "translations": {"en": "test"}},
            timeout=15,
        )
        assert r.status_code == 401, f"Expected 401 (2FA gate), got {r.status_code}: {r.text[:300]}"

    def test_d_announcement_works_with_totp_header(self, admin_2fa_token):
        """Regression: multi-language announcement broadcast still works with proper TOTP header."""
        totp = pyotp.TOTP(TOTP_SECRET).now()
        r = requests.post(
            f"{BASE_URL}/api/admin/announcement",
            headers={
                "Authorization": f"Bearer {admin_2fa_token}",
                "X-Admin-TOTP": totp,
            },
            json={
                "translations": {
                    "en": {"title": "TEST_regr_en", "message": "TEST_ regression announcement", "buttons": []},
                    "ru": {"title": "TEST_regr_ru", "message": "TEST_ регрессионное объявление", "buttons": []},
                },
            },
            timeout=20,
        )
        assert r.status_code in (200, 201), f"Announcement broadcast failed: {r.status_code} {r.text[:500]}"
