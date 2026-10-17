"""2FA (TOTP) login flow regression tests — bug: correct TOTP code returned 500.

Covers:
  * POST /api/auth/login  → requires_2fa for a TOTP-enabled user
  * POST /api/auth/login-2fa → 200 + token with a valid current TOTP code
  * POST /api/auth/login-2fa → clean 401 (never 500) with a wrong code
  * POST /api/auth/login  → direct token for admin (2FA disabled)
"""
import os
import time

import pyotp
import pytest
import requests
from dotenv import dotenv_values

_env = dotenv_values("/app/frontend/.env")
_base = os.environ.get("REACT_APP_BACKEND_URL") or _env.get("REACT_APP_BACKEND_URL")
if not _base:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = _base.rstrip("/")

TOTP_SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
USER_EMAIL = "testuser@example.com"
USER_PASSWORD = "Test1234!"
ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _fresh_code():
    """Return a code with enough time left in the window to survive the round-trip."""
    totp = pyotp.TOTP(TOTP_SECRET)
    if 30 - (int(time.time()) % 30) < 5:
        time.sleep(6)
    return totp.now()


def _login_2fa(client, code):
    return client.post(
        f"{BASE_URL}/api/auth/login-2fa",
        json={
            "email": USER_EMAIL,
            "password": USER_PASSWORD,
            "totp_code": code,
            "visitor_id": "",
            "turnstile_token": "",
        },
        timeout=30,
    )


class TestTwoFactorLogin:
    """Ordered: valid code first (resets lockout counter), wrong code after,
    then a valid code again so the account is left unlocked."""

    def test_login_requires_2fa(self, client):
        r = client.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": USER_EMAIL, "password": USER_PASSWORD},
            timeout=30,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"
        data = r.json()
        assert data.get("requires_2fa") is True, f"expected requires_2fa, got {data}"
        assert "token" not in data, "token must NOT be issued before 2FA"

    def test_login_2fa_valid_code_returns_token(self, client):
        r = _login_2fa(client, _fresh_code())
        assert r.status_code != 500, f"REGRESSION: 500 on valid TOTP code: {r.text[:500]}"
        assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"
        data = r.json()
        assert isinstance(data.get("token"), str) and len(data["token"]) > 20
        assert data.get("type") == "bearer"
        assert data["user"]["email"] == USER_EMAIL

    def test_token_from_2fa_login_is_usable(self, client):
        r = _login_2fa(client, _fresh_code())
        assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"
        token = r.json()["token"]
        me = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        assert me.status_code == 200, f"/auth/me failed: {me.status_code} {me.text[:300]}"
        body = me.json()
        assert body.get("email") == USER_EMAIL or body.get("user", {}).get("email") == USER_EMAIL
        assert "_id" not in body, "MongoDB _id leaked in /auth/me response"

    def test_login_2fa_wrong_code_returns_401(self, client):
        r = _login_2fa(client, "000000")
        assert r.status_code != 500, f"500 on wrong TOTP code: {r.text[:500]}"
        assert r.status_code == 401, f"expected 401, got {r.status_code} {r.text[:400]}"
        assert "2FA" in r.json().get("detail", "")

    def test_login_2fa_missing_code_returns_400(self, client):
        r = _login_2fa(client, None)
        assert r.status_code != 500, f"500 on missing TOTP code: {r.text[:500]}"
        assert r.status_code == 400, f"expected 400, got {r.status_code} {r.text[:400]}"

    def test_login_2fa_wrong_password_returns_401(self, client):
        r = client.post(
            f"{BASE_URL}/api/auth/login-2fa",
            json={"email": USER_EMAIL, "password": "wrong-pass", "totp_code": _fresh_code()},
            timeout=30,
        )
        assert r.status_code != 500, f"500 on wrong password: {r.text[:500]}"
        assert r.status_code == 401, f"expected 401, got {r.status_code} {r.text[:400]}"

    def test_valid_code_still_works_after_failures(self, client):
        """Resets the brute-force counter so the account is left in a clean state."""
        r = _login_2fa(client, _fresh_code())
        assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"
        assert "token" in r.json()


class TestAdminLoginNo2FA:
    def test_admin_login_returns_token_directly(self, client):
        r = client.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
            timeout=30,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"
        data = r.json()
        assert data.get("requires_2fa") is not True, f"admin unexpectedly needs 2FA: {data}"
        assert isinstance(data.get("token"), str) and len(data["token"]) > 20
