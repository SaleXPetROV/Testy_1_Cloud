"""Tests for admin telegram app_url settings endpoints."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://city-blockchain.preview.emergentagent.com").rstrip("/")

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PASSWORD = "Test1234!"

DEFAULT_APP_URL = "https://gcapp.games"


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed {r.status_code}: {r.text}"
    return r.json().get("access_token") or r.json().get("token")


@pytest.fixture(scope="module")
def admin_token():
    return _login(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def user_token():
    return _login(USER_EMAIL, USER_PASSWORD)


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="module")
def user_headers(user_token):
    return {"Authorization": f"Bearer {user_token}"}


def test_admin_can_save_app_url(admin_headers):
    r = requests.post(f"{BASE_URL}/api/admin/settings/telegram-app-url",
                      json={"app_url": DEFAULT_APP_URL}, headers=admin_headers, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "ok"
    assert data["app_url"] == DEFAULT_APP_URL


def test_readback_get_telegram_bot(admin_headers):
    r = requests.get(f"{BASE_URL}/api/admin/settings/telegram-bot", headers=admin_headers, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["app_url"] == DEFAULT_APP_URL


@pytest.mark.parametrize("bad_url", ["javascript:alert(1)", "ftp://x", "notaurl", "//example.com"])
def test_reject_non_http(admin_headers, bad_url):
    r = requests.post(f"{BASE_URL}/api/admin/settings/telegram-app-url",
                      json={"app_url": bad_url}, headers=admin_headers, timeout=30)
    assert r.status_code == 400, f"expected 400 for {bad_url}, got {r.status_code}: {r.text}"


def test_empty_allowed(admin_headers):
    r = requests.post(f"{BASE_URL}/api/admin/settings/telegram-app-url",
                      json={"app_url": ""}, headers=admin_headers, timeout=30)
    assert r.status_code == 200, r.text
    assert r.json()["app_url"] == ""

    # Confirm via GET
    g = requests.get(f"{BASE_URL}/api/admin/settings/telegram-bot", headers=admin_headers, timeout=30)
    assert g.status_code == 200
    assert g.json()["app_url"] == ""


def test_authz_regular_user_post_forbidden(user_headers):
    r = requests.post(f"{BASE_URL}/api/admin/settings/telegram-app-url",
                      json={"app_url": "https://gcapp.games"}, headers=user_headers, timeout=30)
    assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text}"


def test_authz_regular_user_get_forbidden(user_headers):
    r = requests.get(f"{BASE_URL}/api/admin/settings/telegram-bot", headers=user_headers, timeout=30)
    assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text}"


def test_unauthenticated_post():
    r = requests.post(f"{BASE_URL}/api/admin/settings/telegram-app-url",
                      json={"app_url": "https://gcapp.games"}, timeout=30)
    assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}"


def test_unauthenticated_get():
    r = requests.get(f"{BASE_URL}/api/admin/settings/telegram-bot", timeout=30)
    assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}"


def test_roundtrip_distinct_url(admin_headers):
    distinct = "https://example-test.games"
    r = requests.post(f"{BASE_URL}/api/admin/settings/telegram-app-url",
                      json={"app_url": distinct}, headers=admin_headers, timeout=30)
    assert r.status_code == 200
    assert r.json()["app_url"] == distinct

    g = requests.get(f"{BASE_URL}/api/admin/settings/telegram-bot", headers=admin_headers, timeout=30)
    assert g.status_code == 200
    assert g.json()["app_url"] == distinct


def test_zzz_restore_default(admin_headers):
    """Restore production default so we don't leave bad state."""
    r = requests.post(f"{BASE_URL}/api/admin/settings/telegram-app-url",
                      json={"app_url": DEFAULT_APP_URL}, headers=admin_headers, timeout=30)
    assert r.status_code == 200
    assert r.json()["app_url"] == DEFAULT_APP_URL

    g = requests.get(f"{BASE_URL}/api/admin/settings/telegram-bot", headers=admin_headers, timeout=30)
    assert g.status_code == 200
    assert g.json()["app_url"] == DEFAULT_APP_URL
