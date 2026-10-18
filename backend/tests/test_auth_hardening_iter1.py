"""
Iteration 1 — Auth hardening regression suite (4 issues + reload persistence backend side).

Covers:
  1. Email/username login (+ cookie attributes SameSite=None; Secure; HttpOnly)
  2. Stable JWT secret (/api/auth/me with Bearer token), 401 on missing/invalid token
  3. Telegram Mini App auth (synthesized initData, choice_required -> create -> auto-login, bad hash 401)
  4. Password reset via Resend (200 + backend log '[email] Resend SENT')
"""
import hashlib
import hmac
import json
import os
import re
import subprocess
import time
import urllib.parse
import uuid

import pytest
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values("/app/frontend/.env")
backend_env = dotenv_values("/app/backend/.env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = base_url.rstrip("/")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or backend_env.get("TELEGRAM_BOT_TOKEN")

ADMIN = {"email": "sanyanazarov212@gmail.com", "password": os.environ.get("TEST_ADMIN_PASSWORD", "")}
USER = {"email": "testuser@example.com", "password": "Test1234!"}
USERNAME_LOGIN = {"email": "testuser", "password": "Test1234!"}


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _login(client, payload):
    return client.post(f"{BASE_URL}/api/auth/login", json=payload, timeout=30)


# ---------------------------------------------------------------- Issue 1: login
class TestLogin:
    def test_login_with_username(self, client):
        r = _login(client, USERNAME_LOGIN)
        assert r.status_code == 200, r.text[:500]
        data = r.json()
        token = data.get("token") or data.get("access_token")
        assert isinstance(token, str) and len(token) > 20, f"no token in body: {data}"
        assert data.get("user", {}).get("email") == USER["email"]

    def test_login_with_email(self, client):
        r = _login(client, USER)
        assert r.status_code == 200, r.text[:500]
        data = r.json()
        assert data.get("token") or data.get("access_token")
        assert data["user"]["is_admin"] is False

    def test_login_cookie_attributes(self, client):
        r = requests.post(f"{BASE_URL}/api/auth/login", json=USER, timeout=30)
        set_cookies = r.raw.headers.getlist("Set-Cookie") if hasattr(r.raw, "headers") else []
        access = [c for c in set_cookies if c.startswith("access_token=")]
        assert access, f"No access_token Set-Cookie header. Got: {set_cookies}"
        hdr = access[0].lower()
        assert "httponly" in hdr, f"HttpOnly missing: {access[0]}"
        assert "secure" in hdr, f"Secure missing: {access[0]}"
        assert "samesite=none" in hdr, f"SameSite=None missing: {access[0]}"

    def test_admin_login_is_admin_true(self, client):
        r = _login(client, ADMIN)
        assert r.status_code == 200, r.text[:500]
        data = r.json()
        assert data["user"]["is_admin"] is True, data["user"]

    def test_login_wrong_password_401(self, client):
        r = _login(client, {"email": "testuser", "password": "wrong-password-xyz"})
        assert r.status_code in (400, 401), r.status_code


# ---------------------------------------------------- Issue 2: stable JWT secret
class TestJwtStability:
    def test_me_with_bearer_token(self, client):
        r = _login(client, USER)
        assert r.status_code == 200
        token = r.json().get("token") or r.json().get("access_token")
        me = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        assert me.status_code == 200, me.text[:500]
        body = me.json()
        blob = json.dumps(body)
        assert "testuser" in blob, blob[:400]
        assert "_id" not in body, "raw Mongo _id leaked in /api/auth/me"

    def test_my_businesses_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/my/businesses", timeout=30)
        assert r.status_code == 401, f"expected 401 without token, got {r.status_code}"

    def test_my_businesses_invalid_token(self):
        r = requests.get(
            f"{BASE_URL}/api/my/businesses",
            headers={"Authorization": "Bearer not.a.real.token"},
            timeout=30,
        )
        assert r.status_code == 401, f"expected 401 with bogus token, got {r.status_code}"

    def test_my_businesses_valid_token(self, client):
        token = _login(client, USER).json().get("token")
        r = requests.get(
            f"{BASE_URL}/api/my/businesses",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        assert r.status_code == 200, r.text[:300]


# ------------------------------------------------ Issue 3: Telegram Mini App auth
def build_init_data(tg_id: int, username: str, tamper: bool = False) -> str:
    user = {"id": tg_id, "first_name": "QA", "username": username, "language_code": "en"}
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAF" + uuid.uuid4().hex[:12],
        "user": json.dumps(user, separators=(",", ":")),
    }
    dcs = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    h = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    if tamper:
        h = ("0" if h[0] != "0" else "1") + h[1:]
    fields["hash"] = h
    return urllib.parse.urlencode(fields)


@pytest.fixture(scope="module")
def tg_state():
    return {"init_data": None, "created_user_ids": []}


def _mongo(js: str) -> str:
    db_name = backend_env.get("DB_NAME")
    mongo_url = backend_env.get("MONGO_URL")
    return subprocess.run(
        ["mongosh", mongo_url, "--quiet", "--eval",
         f'db = db.getSiblingDB("{db_name}"); {js}'],
        capture_output=True, text=True,
    ).stdout.strip()


def _new_tg_id():
    return 999000000 + int(time.time() * 1000) % 900000


@pytest.fixture(scope="class")
def tg_cleanup():
    ids = []
    yield ids
    for tg_id in ids:
        _mongo(f'db.users.deleteMany({{telegram_user_id: "{tg_id}"}})')


class TestTelegramMiniApp:
    """Telegram Mini App auth — signature validation + both toggle branches."""

    def test_bot_token_present(self):
        assert BOT_TOKEN, "TELEGRAM_BOT_TOKEN not configured"

    def test_invalid_signature_401(self):
        bad = build_init_data(_new_tg_id(), "qa_bad_sig", tamper=True)
        r = requests.post(
            f"{BASE_URL}/api/auth/telegram/miniapp", json={"init_data": bad}, timeout=30
        )
        assert r.status_code == 401, f"{r.status_code} {r.text[:300]}"
        assert "signature" in r.text.lower(), r.text[:300]

    def test_expired_auth_date_rejected(self):
        # stale auth_date (>24h) must not be accepted
        user = {"id": _new_tg_id(), "first_name": "QA", "username": "qa_stale"}
        fields = {
            "auth_date": str(int(time.time()) - 60 * 60 * 48),
            "user": json.dumps(user, separators=(",", ":")),
        }
        dcs = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
        secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        fields["hash"] = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
        r = requests.post(
            f"{BASE_URL}/api/auth/telegram/miniapp",
            json={"init_data": urllib.parse.urlencode(fields)}, timeout=30,
        )
        assert r.status_code == 401, f"stale initData accepted: {r.status_code} {r.text[:300]}"

    def test_default_toggle_seamless_signup(self, tg_cleanup):
        """DEFAULT (choice_enabled unset/False): brand-new tg id is auto-created."""
        _mongo('db.admin_settings.deleteMany({type:"telegram_registration"})')
        tg_id = _new_tg_id()
        tg_cleanup.append(str(tg_id))
        init = build_init_data(tg_id, f"qa_seamless_{tg_id}")
        r = requests.post(
            f"{BASE_URL}/api/auth/telegram/miniapp", json={"init_data": init}, timeout=30
        )
        assert r.status_code == 200, r.text[:400]
        data = r.json()
        assert data.get("status") == "ok", data
        assert data.get("is_new_signup") is True, data
        assert data.get("token"), data

    def test_choice_flow_when_toggle_enabled(self, tg_cleanup, tg_state):
        """Toggle ON: choice_required -> /miniapp/create -> auto-login."""
        _mongo('db.admin_settings.updateOne({type:"telegram_registration"},'
               '{$set:{choice_enabled:true}},{upsert:true})')
        try:
            tg_id = _new_tg_id()
            tg_cleanup.append(str(tg_id))
            username = f"qa_miniapp_{tg_id}"
            init = build_init_data(tg_id, username)
            tg_state["init_data"] = init

            r1 = requests.post(f"{BASE_URL}/api/auth/telegram/miniapp",
                               json={"init_data": init}, timeout=30)
            assert r1.status_code == 200, r1.text[:400]
            d1 = r1.json()
            assert d1.get("status") == "choice_required", d1
            assert str(d1["telegram"]["id"]) == str(tg_id), d1

            r2 = requests.post(f"{BASE_URL}/api/auth/telegram/miniapp/create",
                               json={"init_data": init}, timeout=30)
            assert r2.status_code == 200, r2.text[:400]
            d2 = r2.json()
            assert d2.get("status") == "ok", d2
            assert d2.get("is_new_signup") is True, d2
            assert d2.get("token"), d2

            # same init_data again -> auto-login, not a new signup
            r3 = requests.post(f"{BASE_URL}/api/auth/telegram/miniapp",
                               json={"init_data": init}, timeout=30)
            assert r3.status_code == 200, r3.text[:400]
            d3 = r3.json()
            assert d3.get("status") == "ok", d3
            assert d3.get("is_new_signup") is False, d3
            token = d3.get("token")
            assert token, d3

            me = requests.get(f"{BASE_URL}/api/auth/me",
                              headers={"Authorization": f"Bearer {token}"}, timeout=30)
            assert me.status_code == 200, me.text[:300]
            assert username in json.dumps(me.json())
        finally:
            _mongo('db.admin_settings.deleteMany({type:"telegram_registration"})')


# ------------------------------------------------- Issue 4: password reset/Resend
class TestPasswordReset:
    def test_reset_for_seeded_testuser_returns_200(self):
        r = requests.post(
            f"{BASE_URL}/api/auth/request-password-reset",
            json={"email": USER["email"]},
            timeout=60,
        )
        assert r.status_code == 200, r.text[:400]
        assert r.json().get("status") == "success", r.json()

    def test_resend_sent_log_for_real_domain(self):
        """Resend live-send proof. NOTE: Resend rejects recipients @example.com,
        so the verified-sender path is proven with the admin's real address."""
        before = subprocess.run(
            ["grep", "-c", r"\[email\] Resend SENT", "/var/log/supervisor/backend.err.log"],
            capture_output=True, text=True,
        ).stdout.strip()
        before_n = int(before or 0)

        r = requests.post(
            f"{BASE_URL}/api/auth/request-password-reset",
            json={"email": ADMIN["email"]},
            timeout=60,
        )
        assert r.status_code == 200, r.text[:400]

        sent_line = None
        for _ in range(12):
            time.sleep(2)
            out = subprocess.run(
                ["tail", "-n", "600", "/var/log/supervisor/backend.err.log"],
                capture_output=True, text=True,
            ).stdout
            hits = re.findall(r"\[email\] Resend SENT.*id=\S+", out)
            now_n = int(subprocess.run(
                ["grep", "-c", r"\[email\] Resend SENT", "/var/log/supervisor/backend.err.log"],
                capture_output=True, text=True,
            ).stdout.strip() or 0)
            if hits and now_n > before_n:
                sent_line = hits[-1]
                break
        assert sent_line, "No new '[email] Resend SENT id=...' line in backend.err.log"
        assert "id=" in sent_line

    def test_unknown_email_no_enumeration(self):
        r = requests.post(
            f"{BASE_URL}/api/auth/request-password-reset",
            json={"email": f"nonexistent_{uuid.uuid4().hex[:8]}@example.com"},
            timeout=60,
        )
        assert r.status_code == 200, r.text[:300]
