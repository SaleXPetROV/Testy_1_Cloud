"""Iteration 4 — improved actionable error for POST /api/admin/telegram/set-webhook.

Two modes (driven by env var WEBHOOK_TEST_MODE consumed by the TEST process only):
  * default / "auto"     -> backend .env has NO TELEGRAM_WEBHOOK_URL  (clean state)
  * "override"           -> backend .env has TELEGRAM_WEBHOOK_URL=<...workers.dev>

Only a FAKE bot token is used, so no real Telegram bot webhook is ever modified.
"""
import os

import pytest
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values("/app/frontend/.env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = base_url.rstrip("/")

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")
FAKE_TOKEN = "123456:FAKE_TOKEN_FOR_TEST"
MODE = os.environ.get("WEBHOOK_TEST_MODE", "auto")


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def admin_token(client):
    r = client.post(f"{BASE_URL}/api/auth/login",
                    json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    if r.status_code != 200:
        pytest.fail(f"Admin login failed {r.status_code}: {r.text[:400]}")
    data = r.json()
    token = data.get("access_token") or data.get("token")
    assert isinstance(token, str) and token, f"no token in login body: {list(data.keys())}"
    user = data.get("user") or {}
    assert user.get("is_admin") is True, f"user.is_admin not true: {user}"
    return token


# ---------- Admin auth (no 2FA -> plain Bearer accepted on admin endpoints) ----------
class TestAdminAuth:
    def test_admin_login_and_plain_bearer_admin_access(self, client, admin_token):
        r = client.get(f"{BASE_URL}/api/admin/settings/telegram-bot",
                       headers={"Authorization": f"Bearer {admin_token}"}, timeout=30)
        assert r.status_code == 200, f"admin endpoint rejected plain bearer: {r.status_code} {r.text[:300]}"
        assert isinstance(r.json(), dict)

    def test_set_webhook_requires_auth(self, client):
        r = client.post(f"{BASE_URL}/api/admin/telegram/set-webhook",
                        params={"bot_token": FAKE_TOKEN}, timeout=30)
        assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}"


# ---------- set-webhook error surface ----------
class TestSetWebhookError:
    def _call(self, client, admin_token):
        return client.post(f"{BASE_URL}/api/admin/telegram/set-webhook",
                           params={"bot_token": FAKE_TOKEN},
                           headers={"Authorization": f"Bearer {admin_token}"}, timeout=60)

    @pytest.mark.skipif(MODE != "auto", reason="clean-env mode only")
    def test_auto_derived_webhook_url_in_error(self, client, admin_token):
        r = self._call(client, admin_token)
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text[:400]}"
        detail = r.json().get("detail", "")
        print(f"AUTO detail: {detail}")
        assert isinstance(detail, str) and detail.startswith("Ошибка:")
        assert "webhook_url=" in detail, detail
        assert "/api/telegram/webhook" in detail, detail
        assert "Unauthorized" in detail, detail

    @pytest.mark.skipif(MODE != "override", reason="override-env mode only")
    def test_stale_workers_dev_url_gives_actionable_hint(self, client, admin_token):
        r = self._call(client, admin_token)
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text[:400]}"
        detail = r.json().get("detail", "")
        print(f"OVERRIDE detail: {detail}")
        assert "workers.dev" in detail, detail
        assert "webhook_url=" in detail, detail
        assert "ПОДСКАЗКА" in detail, detail
        assert "TELEGRAM_WEBHOOK_URL" in detail, detail
