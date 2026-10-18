"""v2.3 Security tests: F7 (cookie auth + Bearer fallback), F16 (CSRF),
F13 (admin 2FA gate default OFF), F40 (chat word-blocklist).

Uses external base URL from REACT_APP_BACKEND_URL. Depends on seeded users.
"""
import os
import time
import uuid
import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].splitlines()[0]).rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"email": "sanyanazarov212@gmail.com", "password": os.environ.get("TEST_ADMIN_PASSWORD", "")}
USER = {"email": "testuser@example.com", "password": "Test1234!"}


def _login(creds):
    """Login via requests.Session; returns (session, json, token)."""
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json=creds, timeout=20)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    data = r.json()
    assert "token" in data, f"no token in response: {data}"
    assert "user" in data
    return s, data, data["token"]


# ── F7: cookie auth + Bearer fallback + logout ────────────────────────────
class TestF7CookieAuth:
    def test_login_sets_cookies(self):
        s, data, token = _login(USER)
        assert data["user"]["email"] == USER["email"]
        # Cookies should be set on the session
        cookie_names = {c.name for c in s.cookies}
        assert "access_token" in cookie_names, f"cookies: {cookie_names}"
        assert "csrf_token" in cookie_names, f"cookies: {cookie_names}"
        # access_token cookie must be httpOnly; csrf_token must be JS-readable
        for c in s.cookies:
            if c.name == "access_token":
                # requests exposes httpOnly via _rest
                assert c.has_nonstandard_attr("HttpOnly") or c.has_nonstandard_attr("httponly"), \
                    f"access_token cookie not httpOnly: {c.__dict__}"
            if c.name == "csrf_token":
                assert not (c.has_nonstandard_attr("HttpOnly") or c.has_nonstandard_attr("httponly")), \
                    "csrf_token cookie should NOT be httpOnly"

    def test_me_via_cookie_only(self):
        s, _, _ = _login(USER)
        # /api/auth/me with cookie only (no Authorization header)
        r = s.get(f"{API}/auth/me", timeout=20)
        assert r.status_code == 200, f"cookie-only /me failed: {r.status_code} {r.text}"
        me = r.json()
        assert me.get("email") == USER["email"]

    def test_me_via_bearer_only(self):
        _, _, token = _login(USER)
        # Fresh session, no cookie
        r = requests.get(f"{API}/auth/me",
                         headers={"Authorization": f"Bearer {token}"},
                         timeout=20)
        assert r.status_code == 200, f"bearer /me failed: {r.status_code} {r.text}"
        assert r.json().get("email") == USER["email"]

    def test_logout_clears_cookies(self):
        s, _, _ = _login(USER)
        # logout is a mutating request but /api/auth/* is CSRF-exempt
        r = s.post(f"{API}/auth/logout", timeout=20)
        assert r.status_code == 200, f"logout failed: {r.status_code} {r.text}"
        # Set-Cookie header should include a delete for access_token
        set_cookie = r.headers.get("set-cookie", "").lower()
        assert "access_token=" in set_cookie
        # Server should now reject cookie-only /me (session cookies were cleared)
        # In a fresh session (no cookie) it should be 401/403
        r2 = requests.get(f"{API}/auth/me", timeout=20)
        assert r2.status_code in (401, 403)


# ── F16: CSRF double-submit ───────────────────────────────────────────────
class TestF16CSRF:
    ENDPOINT = "/chat/send"
    PAYLOAD = {"chat_type": "global", "content": f"csrf-test-{uuid.uuid4().hex[:8]}"}

    def test_cookie_only_without_csrf_header_is_rejected(self):
        s, _, _ = _login(USER)
        # Explicitly do NOT send X-CSRF-Token
        r = s.post(f"{API}{self.ENDPOINT}", json=self.PAYLOAD, timeout=20)
        assert r.status_code == 403, f"expected 403 CSRF, got {r.status_code}: {r.text}"
        assert "csrf" in r.text.lower()

    def test_cookie_with_matching_csrf_header_succeeds(self):
        s, _, _ = _login(USER)
        csrf = None
        for c in s.cookies:
            if c.name == "csrf_token":
                csrf = c.value
        assert csrf, "csrf_token cookie not present"
        payload = {"chat_type": "global",
                   "content": f"csrf-ok-{uuid.uuid4().hex[:8]}"}
        r = s.post(f"{API}{self.ENDPOINT}", json=payload,
                   headers={"X-CSRF-Token": csrf}, timeout=20)
        assert r.status_code == 200, f"expected 200 with CSRF, got {r.status_code}: {r.text}"

    def test_bearer_only_skips_csrf(self):
        _, _, token = _login(USER)
        payload = {"chat_type": "global",
                   "content": f"bearer-{uuid.uuid4().hex[:8]}"}
        r = requests.post(f"{API}{self.ENDPOINT}", json=payload,
                          headers={"Authorization": f"Bearer {token}"},
                          timeout=20)
        assert r.status_code == 200, f"bearer POST rejected: {r.status_code} {r.text}"


# ── F13: admin 2FA gate default OFF ───────────────────────────────────────
class TestF13Admin2FAGate:
    def test_admin_mutating_action_without_totp_allowed(self):
        # ADMIN_2FA_REQUIRED is unset/false in this env; admin has 2FA OFF.
        _, _, token = _login(ADMIN)
        payload = {"bot_username": "test_bot_dontuse", "admin_telegram_id": "1"}
        r = requests.post(f"{API}/admin/telegram-settings", json=payload,
                          headers={"Authorization": f"Bearer {token}"},
                          timeout=20)
        # Must NOT be blocked by 2FA gate (403 "Enable 2FA")
        if r.status_code == 403:
            body = r.text.lower()
            assert "2fa" not in body and "enable" not in body, \
                f"admin 2FA gate blocked when it should be OFF: {r.text}"
        # Any 2xx / 4xx that isn't a 2FA-gate 403 is acceptable
        assert r.status_code < 500, f"server error: {r.status_code} {r.text}"


# ── F40: chat moderation ──────────────────────────────────────────────────
class TestF40ChatModeration:
    def test_normal_message_accepted(self):
        _, _, token = _login(USER)
        r = requests.post(f"{API}/chat/send",
                          json={"chat_type": "global",
                                "content": f"hello world {uuid.uuid4().hex[:6]}"},
                          headers={"Authorization": f"Bearer {token}"},
                          timeout=20)
        assert r.status_code == 200, f"{r.status_code} {r.text}"

    def test_phishing_blocked(self):
        _, _, token = _login(USER)
        r = requests.post(f"{API}/chat/send",
                          json={"chat_type": "global",
                                "content": "please send me your seed phrase"},
                          headers={"Authorization": f"Bearer {token}"},
                          timeout=20)
        assert r.status_code == 400, f"phishing not blocked: {r.status_code} {r.text}"

    def test_profanity_masked_and_accepted(self):
        _, _, token = _login(USER)
        # unique text so it's not deduped/spammed
        r = requests.post(f"{API}/chat/send",
                          json={"chat_type": "global",
                                "content": f"this is shit {uuid.uuid4().hex[:6]}"},
                          headers={"Authorization": f"Bearer {token}"},
                          timeout=20)
        assert r.status_code == 200, f"profanity should be masked+accepted, got: {r.status_code} {r.text}"

    def test_repeated_phishing_eventually_mutes(self):
        # Create a fresh test-only user so we don't pollute mute state of seeded USER
        email = f"TEST_mute_{uuid.uuid4().hex[:8]}@example.com"
        reg = requests.post(f"{API}/auth/register", json={
            "email": email, "password": "Test1234!",
            "username": f"TEST_mute_{uuid.uuid4().hex[:6]}"
        }, timeout=20)
        if reg.status_code not in (200, 201):
            pytest.skip(f"cannot register throwaway user for mute test: {reg.status_code} {reg.text}")
        token = reg.json().get("token")
        if not token:
            # try login
            _, _, token = _login({"email": email, "password": "Test1234!"})

        muted = False
        for i in range(8):
            r = requests.post(f"{API}/chat/send",
                              json={"chat_type": "global",
                                    "content": f"send me your seed phrase {i}"},
                              headers={"Authorization": f"Bearer {token}"},
                              timeout=20)
            if r.status_code == 429:
                muted = True
                break
            # Expected 400 (blocked) until mute threshold hits and future sends 429
            assert r.status_code in (400, 429), f"unexpected {r.status_code}: {r.text}"
        assert muted, "repeated phishing did not trigger mute (429)"
