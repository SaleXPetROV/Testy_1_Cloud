"""
Iteration 5 — Telegram login-link (deeplink flow) + regression for
Telegram miniapp/widget/verify-2fa now that TELEGRAM_BOT_TOKEN is configured.

Endpoints under test:
- POST /api/auth/telegram/login-link/start        -> 200 { ok, jti, deeplink, expires_in, bot_username }
- GET  /api/auth/telegram/login-link/status/{jti} -> pending / not_found / expired / confirmed
- POST /api/auth/telegram/miniapp                 -> 401 invalid signature (bot token present)
- POST /api/auth/telegram/widget                  -> 401 invalid signature (bot token present)
- POST /api/auth/telegram/verify-2fa              -> 401 invalid pre-auth token
- Regression: /api/health, /api/auth/login (admin+user), /api/auth/me
- OpenAPI schema exposes the two new login-link paths (via internal localhost:8001)
"""
import os
import re
import pytest
import requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://e9d6f8ec-7abc-4b8a-a67a-9fed40e494ce.preview.emergentagent.com",
).rstrip("/")

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PASSWORD = "Test1234!"


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


# --- Health ---
def test_health(s):
    r = s.get(f"{BASE_URL}/api/health", timeout=15)
    assert r.status_code == 200, r.text
    assert r.json().get("status") == "healthy"


# --- Login regression ---
class TestLoginRegression:
    def test_admin_login(self, s):
        r = s.post(f"{BASE_URL}/api/auth/login",
                   json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        token = data.get("access_token") or data.get("token")
        assert token and len(token) > 20
        assert (data.get("user") or {}).get("is_admin") is True
        pytest.admin_token = token

    def test_user_login(self, s):
        r = s.post(f"{BASE_URL}/api/auth/login",
                   json={"email": USER_EMAIL, "password": USER_PASSWORD}, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        token = data.get("access_token") or data.get("token")
        assert token and len(token) > 20
        assert (data.get("user") or {}).get("is_admin") is False
        pytest.user_token = token

    def test_admin_me(self):
        tok = getattr(pytest, "admin_token", None)
        assert tok
        r = requests.get(f"{BASE_URL}/api/auth/me",
                         headers={"Authorization": f"Bearer {tok}"}, timeout=15)
        assert r.status_code == 200, r.text
        me = r.json()
        assert me.get("email") == ADMIN_EMAIL
        assert me.get("is_admin") is True

    def test_user_me(self):
        tok = getattr(pytest, "user_token", None)
        assert tok
        r = requests.get(f"{BASE_URL}/api/auth/me",
                         headers={"Authorization": f"Bearer {tok}"}, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json().get("email") == USER_EMAIL


# --- Login-link endpoints ---
class TestLoginLink:
    def test_start_returns_deeplink(self, s):
        r = s.post(f"{BASE_URL}/api/auth/telegram/login-link/start", json={}, timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        data = r.json()
        assert data.get("ok") is True, data
        jti = data.get("jti")
        deeplink = data.get("deeplink")
        expires_in = data.get("expires_in")
        bot_username = data.get("bot_username")
        assert isinstance(jti, str) and len(jti) > 10, data
        assert isinstance(bot_username, str) and len(bot_username) > 0, data
        assert isinstance(expires_in, int) and expires_in > 0, data
        assert isinstance(deeplink, str), data
        assert deeplink.startswith("https://t.me/"), deeplink
        # deeplink shape: https://t.me/<bot_username>?start=login_<jti>
        m = re.match(r"^https://t\.me/([^?]+)\?start=login_(.+)$", deeplink)
        assert m, f"deeplink shape mismatch: {deeplink}"
        assert m.group(1) == bot_username, (m.group(1), bot_username)
        assert m.group(2) == jti, (m.group(2), jti)
        pytest.link_jti = jti
        pytest.link_bot_username = bot_username

    def test_status_pending_for_fresh_jti(self, s):
        jti = getattr(pytest, "link_jti", None)
        assert jti, "start test must run first"
        r = s.get(f"{BASE_URL}/api/auth/telegram/login-link/status/{jti}", timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("status") == "pending", data
        # Should NOT expose a token in pending state
        assert "token" not in data or data.get("token") is None

    def test_status_not_found(self, s):
        r = s.get(f"{BASE_URL}/api/auth/telegram/login-link/status/nonexistent-jti-xyz", timeout=15)
        assert r.status_code == 200, r.text
        assert r.json().get("status") == "not_found"

    def test_start_returns_unique_jti(self, s):
        # Two starts should produce different jtis
        r1 = s.post(f"{BASE_URL}/api/auth/telegram/login-link/start", json={}, timeout=30)
        r2 = s.post(f"{BASE_URL}/api/auth/telegram/login-link/start", json={}, timeout=30)
        assert r1.status_code == 200 and r2.status_code == 200
        assert r1.json()["jti"] != r2.json()["jti"]


# --- Telegram auth endpoints (bot token now configured -> 401, not 503) ---
class TestTelegramAuth:
    def test_miniapp_invalid_signature(self, s):
        r = s.post(f"{BASE_URL}/api/auth/telegram/miniapp",
                   json={"init_data": "user=%7B%22id%22%3A123%7D&auth_date=1700000000&hash=deadbeef"},
                   timeout=15)
        assert r.status_code == 401, f"{r.status_code} {r.text}"
        detail = (r.json().get("detail") or "").lower()
        assert "invalid" in detail and ("signature" in detail or "initdata" in detail), r.text

    def test_widget_invalid_signature(self, s):
        r = s.post(f"{BASE_URL}/api/auth/telegram/widget", json={
            "data": {"id": 123, "first_name": "T", "auth_date": 1700000000, "hash": "deadbeef"}
        }, timeout=15)
        assert r.status_code == 401, f"{r.status_code} {r.text}"
        detail = (r.json().get("detail") or "").lower()
        assert "invalid" in detail and "signature" in detail, r.text

    def test_verify_2fa_invalid_pre_auth_token(self, s):
        r = s.post(f"{BASE_URL}/api/auth/telegram/verify-2fa",
                   json={"pre_auth_token": "not-a-real-token", "code": "123456"},
                   timeout=15)
        assert r.status_code == 401, f"{r.status_code} {r.text}"
        detail = (r.json().get("detail") or "").lower()
        assert "invalid" in detail or "expired" in detail, r.text


# --- OpenAPI ---
def test_openapi_exposes_login_link_paths():
    r = requests.get("http://localhost:8001/openapi.json", timeout=30)
    assert r.status_code == 200
    paths = r.json().get("paths", {})
    required = [
        "/api/auth/telegram/login-link/start",
        "/api/auth/telegram/login-link/status/{jti}",
        "/api/auth/telegram/miniapp",
        "/api/auth/telegram/widget",
        "/api/auth/telegram/verify-2fa",
    ]
    missing = [p for p in required if p not in paths]
    assert not missing, f"missing OpenAPI paths: {missing}"
