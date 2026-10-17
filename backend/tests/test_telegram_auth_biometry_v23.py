"""
Backend tests for TON_CITY_v2.3 Telegram multi-platform auth + biometry endpoints.

Coverage:
- Health
- Login flows for seeded admin + regular test users
- /api/auth/me with returned JWT
- Telegram miniapp/widget/verify-2fa returning 503 (empty bot token) or 401 for bad token
- /api/security/telegram-biometry/status auth requirement + fresh-token state
- OpenAPI schema exposes the new paths
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://e9d6f8ec-7abc-4b8a-a67a-9fed40e494ce.preview.emergentagent.com").rstrip("/")

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PASSWORD = "Test1234!"


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


def _login(s, email, password):
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=30)
    return r


# --- Health ---
def test_health(s):
    r = s.get(f"{BASE_URL}/api/health", timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("status") == "healthy", data


# --- Login flows ---
class TestLogin:
    def test_admin_login(self, s):
        r = _login(s, ADMIN_EMAIL, ADMIN_PASSWORD)
        assert r.status_code == 200, r.text
        data = r.json()
        token = data.get("access_token") or data.get("token")
        assert token and isinstance(token, str) and len(token) > 20, data
        user = data.get("user") or {}
        # is_admin should be true
        assert user.get("is_admin") is True, user
        pytest.admin_token = token
        pytest.admin_user = user

    def test_user_login(self, s):
        r = _login(s, USER_EMAIL, USER_PASSWORD)
        assert r.status_code == 200, r.text
        data = r.json()
        token = data.get("access_token") or data.get("token")
        assert token and isinstance(token, str) and len(token) > 20, data
        user = data.get("user") or {}
        assert user.get("is_admin") is False, user
        pytest.user_token = token

    def test_admin_me(self):
        tok = getattr(pytest, "admin_token", None)
        assert tok, "admin login must run first"
        # fresh session (no cookies) to ensure Bearer token is the auth path
        r = requests.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": f"Bearer {tok}"}, timeout=15)
        assert r.status_code == 200, r.text
        me = r.json()
        assert me.get("email") == ADMIN_EMAIL
        assert me.get("is_admin") is True

    def test_user_me(self):
        tok = getattr(pytest, "user_token", None)
        assert tok, "user login must run first"
        r = requests.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": f"Bearer {tok}"}, timeout=15)
        assert r.status_code == 200, r.text
        me = r.json()
        assert me.get("email") == USER_EMAIL
        assert me.get("is_admin") is False


# --- Telegram multi-platform auth (bot token empty => 503) ---
class TestTelegramAuth:
    def test_miniapp_503(self, s):
        r = s.post(f"{BASE_URL}/api/auth/telegram/miniapp", json={"init_data": "user=%7B%22id%22%3A123%7D&auth_date=1700000000&hash=deadbeef"}, timeout=15)
        assert r.status_code == 503, f"{r.status_code} {r.text}"
        body = r.json()
        detail = body.get("detail") or body.get("message") or ""
        assert "not configured" in detail.lower(), body

    def test_widget_503(self, s):
        r = s.post(f"{BASE_URL}/api/auth/telegram/widget", json={
            "data": {"id": 123, "first_name": "T", "auth_date": 1700000000, "hash": "deadbeef"}
        }, timeout=15)
        assert r.status_code == 503, f"{r.status_code} {r.text}"
        body = r.json()
        detail = body.get("detail") or body.get("message") or ""
        assert "not configured" in detail.lower(), body

    def test_verify_2fa_invalid_token(self, s):
        r = s.post(f"{BASE_URL}/api/auth/telegram/verify-2fa", json={
            "pre_auth_token": "not-a-real-token", "code": "123456"
        }, timeout=15)
        assert r.status_code == 401, f"{r.status_code} {r.text}"
        body = r.json()
        detail = (body.get("detail") or body.get("message") or "").lower()
        assert "invalid" in detail or "expired" in detail, body


# --- Biometry status ---
class TestBiometry:
    def test_status_requires_auth(self):
        # Fresh session — no cookies from prior logins
        r = requests.get(f"{BASE_URL}/api/security/telegram-biometry/status", timeout=15)
        assert r.status_code in (401, 403), r.text

    def test_status_with_fresh_token(self):
        tok = getattr(pytest, "user_token", None)
        assert tok
        r = requests.get(f"{BASE_URL}/api/security/telegram-biometry/status",
                         headers={"Authorization": f"Bearer {tok}"}, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("enabled") is False, data
        assert data.get("device_count") == 0, data


# --- OpenAPI ---
def test_openapi_exposes_new_paths():
    # OpenAPI is not exposed publicly (only /api/* routes are). Query backend directly.
    r = requests.get("http://localhost:8001/openapi.json", timeout=30)
    assert r.status_code == 200
    paths = r.json().get("paths", {})
    for p in [
        "/api/auth/telegram/miniapp",
        "/api/auth/telegram/widget",
        "/api/auth/telegram/verify-2fa",
        "/api/security/telegram-biometry/status",
    ]:
        assert p in paths, f"missing OpenAPI path: {p}"
