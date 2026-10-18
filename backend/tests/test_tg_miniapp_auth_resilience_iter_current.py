"""Telegram Mini App seamless auth — iteration: resilience fix verification.

Covers:
  * POST /api/auth/telegram/miniapp  (valid initData, brand-new tg id -> choice_required)
  * POST /api/auth/telegram/miniapp/create (creates passwordless account, returns JWT)
  * POST /api/auth/telegram/miniapp  (same initData -> status ok + token, returning-user auto-login)
  * signature validation (tampered hash / garbage / empty -> 400/401)
  * GET /api/auth/me with the issued JWT
"""
import asyncio
import hashlib
import hmac
import json
import os
import time
import urllib.parse
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

_be = dotenv_values("/app/backend/.env")
_fe = dotenv_values("/app/frontend/.env")

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or _fe.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
if not BASE_URL:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
API = f"{BASE_URL}/api"
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or _be.get("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN missing from backend/.env")

MONGO_URL = _be.get("MONGO_URL")
DB_NAME = _be.get("DB_NAME")


def build_init_data(tg_id, first_name="Test", username="tester", lang="ru",
                    auth_date=None, start_param=None):
    user_payload = json.dumps(
        {"id": int(tg_id), "first_name": first_name, "username": username, "language_code": lang},
        separators=(",", ":"),
    )
    fields = {
        "auth_date": str(auth_date or int(time.time())),
        "query_id": "AAA",
        "user": user_payload,
    }
    if start_param:
        fields["start_param"] = start_param
    dcs = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(fields)


def cleanup_tg(tg_id):
    if not (MONGO_URL and DB_NAME):
        return
    from motor.motor_asyncio import AsyncIOMotorClient

    async def _do():
        cli = AsyncIOMotorClient(MONGO_URL)
        await cli[DB_NAME].users.delete_many(
            {"$or": [{"telegram_id": int(tg_id)}, {"telegram_id": str(tg_id)},
                     {"telegram_user_id": str(tg_id)}]}
        )
        cli.close()

    asyncio.run(_do())


TG_ID = 770001234


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    yield s
    cleanup_tg(TG_ID)
    s.close()


class TestMiniAppAuthFlow:
    """First-time create -> returning auto-login, with a valid signed initData."""

    state = {}

    def test_01_new_telegram_id_requires_choice(self, session):
        cleanup_tg(TG_ID)
        init_data = build_init_data(TG_ID)
        self.state["init_data"] = init_data
        r = session.post(f"{API}/auth/telegram/miniapp", json={"init_data": init_data}, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("status") == "choice_required", d
        assert str(d["telegram"]["id"]) == str(TG_ID)
        assert d["telegram"]["username"] == "tester"
        assert "token" not in d

    def test_02_create_returns_jwt_and_user(self, session):
        init_data = self.state["init_data"]
        r = session.post(f"{API}/auth/telegram/miniapp/create",
                         json={"init_data": init_data}, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert isinstance(d.get("token"), str) and len(d["token"]) > 20, d
        user = d.get("user")
        assert isinstance(user, dict), d
        assert user.get("telegram_username") == "tester"
        assert user.get("login_methods") == ["telegram"]
        assert user.get("password_set") is False
        assert d.get("is_new_signup") is True
        assert "_id" not in user, "MongoDB _id leaked in response"
        assert "hashed_password" not in user or user.get("hashed_password") in (None, "")
        self.state["token"] = d["token"]
        self.state["user_id"] = user.get("id")

    def test_03_returning_user_auto_login(self, session):
        init_data = self.state["init_data"]
        r = session.post(f"{API}/auth/telegram/miniapp", json={"init_data": init_data}, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("status") == "ok", d
        assert isinstance(d.get("token"), str) and d["token"], d
        assert d.get("is_new_signup") is False
        assert d["user"]["id"] == self.state["user_id"]
        self.state["login_token"] = d["token"]

    def test_04_repeated_logins_are_stable(self, session):
        """Simulate several app opens in a row — every one must authorize."""
        init_data = self.state["init_data"]
        for i in range(5):
            r = session.post(f"{API}/auth/telegram/miniapp",
                             json={"init_data": init_data}, timeout=30)
            assert r.status_code == 200, (i, r.status_code, r.text)
            d = r.json()
            assert d.get("status") == "ok" and d.get("token"), (i, d)

    def test_05_auth_me_with_issued_jwt(self, session):
        token = self.state["login_token"]
        r = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"}, timeout=30)
        assert r.status_code == 200, r.text
        me = r.json()
        assert me.get("id") == self.state["user_id"]
        assert "_id" not in me

    def test_06_create_when_already_linked_logs_in(self, session):
        r = session.post(f"{API}/auth/telegram/miniapp/create",
                         json={"init_data": self.state["init_data"]}, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("token")
        assert d.get("is_new_signup") is False
        assert d["user"]["id"] == self.state["user_id"]


class TestMiniAppSignatureValidation:
    """Signature/validation must stay strict."""

    def test_tampered_hash_rejected(self, session):
        init_data = build_init_data(880009999)
        parsed = dict(urllib.parse.parse_qsl(init_data))
        parsed["hash"] = "0" * 64
        bad = urllib.parse.urlencode(parsed)
        r = session.post(f"{API}/auth/telegram/miniapp", json={"init_data": bad}, timeout=30)
        assert r.status_code == 401, (r.status_code, r.text)
        assert "signature" in json.dumps(r.json()).lower()

    def test_tampered_user_payload_rejected(self, session):
        init_data = build_init_data(880009998)
        parsed = dict(urllib.parse.parse_qsl(init_data))
        parsed["user"] = json.dumps({"id": 999, "first_name": "Hacker"}, separators=(",", ":"))
        bad = urllib.parse.urlencode(parsed)
        r = session.post(f"{API}/auth/telegram/miniapp", json={"init_data": bad}, timeout=30)
        assert r.status_code == 401, (r.status_code, r.text)

    def test_garbage_init_data_rejected(self, session):
        r = session.post(f"{API}/auth/telegram/miniapp",
                         json={"init_data": "not-valid-init-data"}, timeout=30)
        assert r.status_code in (400, 401, 422), (r.status_code, r.text)

    def test_empty_init_data_rejected(self, session):
        r = session.post(f"{API}/auth/telegram/miniapp", json={"init_data": ""}, timeout=30)
        assert r.status_code in (400, 401, 422), (r.status_code, r.text)

    def test_missing_hash_rejected(self, session):
        parsed = dict(urllib.parse.parse_qsl(build_init_data(880009997)))
        parsed.pop("hash")
        r = session.post(f"{API}/auth/telegram/miniapp",
                         json={"init_data": urllib.parse.urlencode(parsed)}, timeout=30)
        assert r.status_code in (400, 401), (r.status_code, r.text)

    def test_create_with_invalid_signature_rejected(self, session):
        parsed = dict(urllib.parse.parse_qsl(build_init_data(880009996)))
        parsed["hash"] = "f" * 64
        r = session.post(f"{API}/auth/telegram/miniapp/create",
                         json={"init_data": urllib.parse.urlencode(parsed)}, timeout=30)
        assert r.status_code == 401, (r.status_code, r.text)

    def test_stale_auth_date_rejected(self, session):
        """initData older than the allowed max_age (24h) must not authorize."""
        old = build_init_data(880009995, username="stale_uniq_user_xyz",
                              auth_date=1500000000)
        r = session.post(f"{API}/auth/telegram/miniapp", json={"init_data": old}, timeout=30)
        assert r.status_code in (200, 401), r.status_code
        if r.status_code == 200:
            pytest.fail(f"Stale initData (auth_date 2017) accepted: {r.json()}")

    def test_username_fallback_does_not_hijack_other_account(self, session):
        """A DIFFERENT telegram_id that happens to share a telegram_username must
        NOT be logged into the existing account (username linkage fallback)."""
        other_id = 880007777
        cleanup_tg(other_id)
        init_data = build_init_data(other_id, username="tester")
        r = session.post(f"{API}/auth/telegram/miniapp", json={"init_data": init_data}, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        if d.get("status") == "ok":
            pytest.fail(
                "Different telegram_id with same username auto-logged into an existing "
                f"account (username-only linkage): {d.get('user', {}).get('id')}"
            )
        assert d.get("status") == "choice_required", d

    def test_unauthenticated_me_rejected(self):
        r = requests.get(f"{API}/auth/me", timeout=30)
        assert r.status_code in (401, 403), r.status_code
