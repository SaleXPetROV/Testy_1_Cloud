"""
Tests for the current iteration: Google OAuth config, Resend email,
TON Connect manifest/icon, Telegram Mini App auto-auth default.
"""
import os
import time
import subprocess
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL")
if not BASE_URL:
    # try reading frontend/.env
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip()
                break
BASE_URL = BASE_URL.rstrip("/")

ADMIN_EMAIL = "admin@gramcity.app"
ADMIN_PWD = "GramAdmin!2026"
PLAYER_EMAIL = "player@gramcity.app"
PLAYER_PWD = "GramPlayer!2026"


@pytest.fixture(scope="module")
def s():
    # Use plain requests (no session) to avoid cookie state carrying between tests
    class _S:
        def get(self, url, **kw):
            return requests.get(url, **kw)
        def post(self, url, **kw):
            return requests.post(url, **kw)
    return _S()


@pytest.fixture(scope="module")
def admin_token(s):
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PWD}, timeout=30)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    data = r.json()
    tok = data.get("access_token") or data.get("token")
    assert tok, f"no token in login response: {data}"
    return tok


@pytest.fixture(scope="module")
def player_token(s):
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": PLAYER_EMAIL, "password": PLAYER_PWD}, timeout=30)
    assert r.status_code == 200, f"player login failed: {r.status_code} {r.text}"
    data = r.json()
    return data.get("access_token") or data.get("token")


# ---------- 1. Admin login + /me ----------
def test_admin_login_and_me(s, admin_token):
    r = s.get(f"{BASE_URL}/api/auth/me",
              headers={"Authorization": f"Bearer {admin_token}"}, timeout=30)
    assert r.status_code == 200, r.text
    me = r.json()
    assert me.get("email") == ADMIN_EMAIL
    assert me.get("is_admin") is True, f"expected is_admin true, got: {me}"


# ---------- 2. Regular user login + /me ----------
def test_player_login_and_me(s, player_token):
    r = s.get(f"{BASE_URL}/api/auth/me",
              headers={"Authorization": f"Bearer {player_token}"}, timeout=30)
    assert r.status_code == 200, r.text
    me = r.json()
    assert me.get("email") == PLAYER_EMAIL


# ---------- 3. Password reset — real send + generic response for unknown ----------
def test_password_reset_sends_email_for_known(s):
    # Snapshot backend log offset
    log_path = "/var/log/supervisor/backend.out.log"
    err_path = "/var/log/supervisor/backend.err.log"
    def size(p):
        try: return os.path.getsize(p)
        except OSError: return 0
    off_out, off_err = size(log_path), size(err_path)

    r = s.post(f"{BASE_URL}/api/auth/request-password-reset",
               json={"email": ADMIN_EMAIL}, timeout=60)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("status") == "success", body
    assert body.get("message") == "code_sent", body

    # Give the async send a moment
    time.sleep(3)

    def tail_since(p, off):
        try:
            with open(p, "rb") as f:
                f.seek(off)
                return f.read().decode("utf-8", errors="ignore")
        except FileNotFoundError:
            return ""
    combined = tail_since(log_path, off_out) + "\n" + tail_since(err_path, off_err)
    assert f"Email sent via Resend to {ADMIN_EMAIL}" in combined, \
        f"Expected Resend send log, got:\n{combined[-2000:]}"


def test_password_reset_generic_response_for_unknown(s):
    log_path = "/var/log/supervisor/backend.out.log"
    err_path = "/var/log/supervisor/backend.err.log"
    def size(p):
        try: return os.path.getsize(p)
        except OSError: return 0
    off_out, off_err = size(log_path), size(err_path)

    r = s.post(f"{BASE_URL}/api/auth/request-password-reset",
               json={"email": "does-not-exist-xyz@gramcity.app"}, timeout=60)
    # Should return generic success (not disclose existence)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("status") == "success", body

    time.sleep(2)
    def tail_since(p, off):
        try:
            with open(p, "rb") as f:
                f.seek(off)
                return f.read().decode("utf-8", errors="ignore")
        except FileNotFoundError:
            return ""
    combined = tail_since(log_path, off_out) + "\n" + tail_since(err_path, off_err)
    assert "Email sent via Resend to does-not-exist-xyz@gramcity.app" not in combined, \
        "Resend was called for unknown user; must not send."


# ---------- 4. Google OAuth config ----------
def test_google_init_returns_pkce(s):
    r = s.post(f"{BASE_URL}/api/auth/google/init", json={}, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("state"), body
    assert body.get("code_challenge"), body


def test_google_invalid_credential_is_4xx_not_503(s):
    r = s.post(f"{BASE_URL}/api/auth/google",
               json={"credential": "not.a.valid.jwt"}, timeout=30)
    # Must not be 503 "not configured"
    assert r.status_code != 503, f"Got 503 (means client id missing): {r.text}"
    assert 400 <= r.status_code < 500, f"expected 4xx, got {r.status_code} {r.text}"
    assert "not configured" not in r.text.lower(), r.text


# ---------- 5. TON Connect manifest & icon ----------
def test_tonconnect_manifest_iconurl(s):
    r = s.get(f"{BASE_URL}/api/tonconnect-manifest-v3.json", timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    icon = body.get("iconUrl", "")
    assert icon.endswith("/api/tonconnect-icon.png"), f"unexpected iconUrl={icon}"


def test_tonconnect_icon_served(s):
    r = s.get(f"{BASE_URL}/api/tonconnect-icon.png", timeout=30)
    assert r.status_code == 200, r.status_code
    ct = r.headers.get("content-type", "")
    assert "image/png" in ct, ct
    assert len(r.content) > 0


# ---------- 6. Telegram auto-auth default + miniapp 503 ----------
def test_telegram_registration_default_auto(s, admin_token):
    r = s.get(f"{BASE_URL}/api/admin/settings/telegram-registration",
              headers={"Authorization": f"Bearer {admin_token}"}, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("choice_enabled") is False, f"expected False (auto-authorize), got {body}"


def test_telegram_miniapp_without_bot_token(s):
    r = s.post(f"{BASE_URL}/api/auth/telegram/miniapp",
               json={"init_data": "user=%7B%22id%22%3A1%7D&auth_date=1&hash=x"}, timeout=30)
    assert r.status_code == 503, f"expected 503, got {r.status_code} {r.text}"
    assert "not configured" in r.text.lower(), r.text
