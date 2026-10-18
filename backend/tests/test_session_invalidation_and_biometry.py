"""Tests for session_invalidated fix + tg-biometry verify-identity 401 without creds."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PASSWORD = "Test1234!"


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    return r


class TestLogin:
    def test_admin_login(self):
        r = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "token" in data or "access_token" in data
        token = data.get("token") or data.get("access_token")
        assert token
        user = data.get("user") or {}
        # admin flag
        assert user.get("is_admin") is True, f"admin flag missing: {user}"

    def test_user_login(self):
        r = _login(USER_EMAIL, USER_PASSWORD)
        assert r.status_code == 200, r.text
        data = r.json()
        token = data.get("token") or data.get("access_token")
        assert token


class TestSingleSessionEnforcement:
    def test_second_login_invalidates_first_token(self):
        # login #1 -> token A
        r1 = _login(USER_EMAIL, USER_PASSWORD)
        assert r1.status_code == 200
        token_a = r1.json().get("token") or r1.json().get("access_token")
        assert token_a

        # /me with token A - should work
        me1 = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token_a}"}, timeout=30)
        assert me1.status_code == 200, f"expected 200 for token A first call, got {me1.status_code}: {me1.text}"

        # login #2 -> token B  (rotates session_id)
        r2 = _login(USER_EMAIL, USER_PASSWORD)
        assert r2.status_code == 200
        token_b = r2.json().get("token") or r2.json().get("access_token")
        assert token_b
        assert token_b != token_a

        # /me with token A - should now be 401 session_invalidated
        me_a2 = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token_a}"}, timeout=30)
        assert me_a2.status_code == 401, f"expected 401 for stale token A, got {me_a2.status_code}: {me_a2.text}"
        detail = ""
        try:
            detail = me_a2.json().get("detail", "")
        except Exception:
            detail = me_a2.text
        assert "session_invalidated" in str(detail), f"expected session_invalidated, got {detail!r}"

        # /me with token B - should work
        me_b = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token_b}"}, timeout=30)
        assert me_b.status_code == 200, f"expected 200 for token B, got {me_b.status_code}: {me_b.text}"


class TestBiometryVerifyIdentity:
    def _get_user_token(self):
        r = _login(USER_EMAIL, USER_PASSWORD)
        assert r.status_code == 200
        return r.json().get("token") or r.json().get("access_token")

    def test_verify_identity_no_creds_returns_401(self):
        token = self._get_user_token()
        r = requests.post(
            f"{API}/security/telegram-biometry/register/verify-identity",
            headers={"Authorization": f"Bearer {token}"},
            json={},
            timeout=30,
        )
        # spec: must return 401 when neither password nor valid totp provided
        assert r.status_code == 401, f"expected 401 without creds, got {r.status_code}: {r.text}"

    def test_verify_identity_invalid_totp_returns_401(self):
        token = self._get_user_token()
        r = requests.post(
            f"{API}/security/telegram-biometry/register/verify-identity",
            headers={"Authorization": f"Bearer {token}"},
            json={"totp_code": "000000"},
            timeout=30,
        )
        assert r.status_code == 401, f"expected 401 for invalid totp, got {r.status_code}: {r.text}"
