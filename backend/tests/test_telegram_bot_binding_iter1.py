"""
Tests for the specific review request:
- Admin login
- Regular user login
- Admin sets Telegram bot token
- Admin registers Telegram webhook (should not timeout)
- Regular user is forbidden from admin endpoint
"""

import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://ton-city-hub-2.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PASSWORD = "Test1234!"
BOT_TOKEN = "000000000:TEST_PLACEHOLDER_TOKEN_NOT_REAL_000000"


@pytest.fixture(scope="module")
def http():
    # Do NOT share cookies across users - use a fresh session per request
    class NoCookieSession:
        def post(self, *args, **kwargs):
            kwargs.setdefault("timeout", 30)
            return requests.post(*args, **kwargs)
        def get(self, *args, **kwargs):
            kwargs.setdefault("timeout", 30)
            return requests.get(*args, **kwargs)
    return NoCookieSession()


@pytest.fixture(scope="module")
def admin_token(http):
    r = http.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    data = r.json()
    token = data.get("access_token") or data.get("token")
    assert token, f"no access token in admin login: {data}"
    # is_admin true
    user = data.get("user") or {}
    assert user.get("is_admin") is True, f"admin login did not return is_admin=true: {user}"
    return token


@pytest.fixture(scope="module")
def user_token(http):
    r = http.post(f"{API}/auth/login", json={"email": USER_EMAIL, "password": USER_PASSWORD}, timeout=30)
    assert r.status_code == 200, f"user login failed: {r.status_code} {r.text}"
    data = r.json()
    token = data.get("access_token") or data.get("token")
    assert token, f"no access token in user login: {data}"
    user = data.get("user") or {}
    assert user.get("is_admin") in (False, None), f"regular user should not be admin: {user}"
    return token


def test_admin_login(admin_token):
    assert isinstance(admin_token, str) and len(admin_token) > 10


def test_user_login(user_token):
    assert isinstance(user_token, str) and len(user_token) > 10


def test_admin_save_bot_token(http, admin_token):
    r = http.post(
        f"{API}/admin/settings/telegram-bot-token",
        json={"bot_token": BOT_TOKEN},
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=60,
    )
    assert r.status_code == 200, f"save bot token failed: {r.status_code} {r.text}"
    data = r.json()
    assert data.get("status") == "success", f"unexpected status: {data}"
    assert data.get("bot_configured") is True, f"bot_configured should be true: {data}"


def test_admin_set_webhook(http, admin_token):
    r = http.post(
        f"{API}/admin/telegram/set-webhook",
        params={"bot_token": BOT_TOKEN},
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=90,
    )
    assert r.status_code == 200, f"set-webhook returned {r.status_code}: {r.text}"
    data = r.json()
    # Should NOT be a timeout / Telegram API error
    body_text = str(data).lower()
    assert "timeout" not in body_text, f"unexpected timeout in response: {data}"
    assert "telegram api error" not in body_text, f"telegram api error in response: {data}"
    # Should contain webhook_set status and url ending with /api/telegram/webhook
    status = data.get("status") or data.get("result") or ""
    url = data.get("url") or data.get("webhook_url") or ""
    assert "webhook" in str(status).lower() or "success" in str(status).lower(), f"unexpected status: {data}"
    assert str(url).endswith("/api/telegram/webhook"), f"webhook url does not match: {data}"


def test_regular_user_forbidden_on_bot_token(http, user_token):
    r = http.post(
        f"{API}/admin/settings/telegram-bot-token",
        json={"bot_token": BOT_TOKEN},
        headers={"Authorization": f"Bearer {user_token}"},
        timeout=30,
    )
    assert r.status_code in (401, 403), f"regular user should be forbidden, got {r.status_code} {r.text}"
