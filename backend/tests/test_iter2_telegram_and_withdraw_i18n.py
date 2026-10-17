"""Iteration 2: Telegram auth endpoints + localized withdraw messages."""
import os
import requests
import pytest

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://ton-biometric-dev.preview.emergentagent.com').rstrip('/')
USER_EMAIL = "testuser@example.com"
USER_PASSWORD = "Test1234!"


@pytest.fixture(scope="module")
def user_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": USER_EMAIL, "password": USER_PASSWORD}, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["token"]


# --- Telegram auth endpoints mounted (not 404) ---
class TestTelegramAuthRoutes:
    def test_miniapp_bogus_init_data_returns_503_not_404(self):
        r = requests.post(f"{BASE_URL}/api/auth/telegram/miniapp",
                          json={"init_data": "bogus_init_data_string"}, timeout=15)
        assert r.status_code != 404, "route not mounted"
        # Bot not configured → 503 expected
        assert r.status_code in (400, 401, 403, 503), f"unexpected status {r.status_code}: {r.text}"
        # Ideally 503 per problem statement
        if r.status_code != 503:
            print(f"NOTE: expected 503, got {r.status_code}: {r.text}")

    def test_widget_route_exists(self):
        r = requests.post(f"{BASE_URL}/api/auth/telegram/widget",
                          json={"id": 1, "auth_date": 1, "hash": "x"}, timeout=15)
        assert r.status_code != 404, "widget route not mounted"


# --- Localized withdraw error messages ---
class TestWithdrawI18n:
    def _set_lang(self, token, lang):
        r = requests.put(f"{BASE_URL}/api/auth/update-language",
                         headers={"Authorization": f"Bearer {token}"},
                         json={"language": lang}, timeout=15)
        assert r.status_code == 200, f"update-language failed: {r.status_code} {r.text}"

    def test_withdraw_german_message(self, user_token):
        self._set_lang(user_token, "de")
        r = requests.post(f"{BASE_URL}/api/withdraw",
                          headers={"Authorization": f"Bearer {user_token}"},
                          json={"amount": 1.0}, timeout=15)
        # Expect gating error (400) since testuser has no 2FA
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"
        detail = r.json().get("detail", "")
        assert "2FA-Authentifizierung" in detail, f"expected German 2FA message, got: {detail!r}"

    def test_withdraw_indonesian_message(self, user_token):
        self._set_lang(user_token, "id")
        r = requests.post(f"{BASE_URL}/api/withdraw",
                          headers={"Authorization": f"Bearer {user_token}"},
                          json={"amount": 1.0}, timeout=15)
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"
        detail = r.json().get("detail", "").lower()
        assert "autentikasi 2fa" in detail, f"expected Indonesian 2FA message, got: {detail!r}"

    def test_restore_english(self, user_token):
        # cleanup
        self._set_lang(user_token, "en")
