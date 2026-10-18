"""Iter2 tests: SESSION_OVERRIDDEN detail + Telegram miniapp choice/create/link flows.

Signs its own initData using TELEGRAM_BOT_TOKEN from backend/.env, so it runs
without a real Telegram client. Cleans up any test users/telegram fields it
creates.
"""
import os
import hmac
import hashlib
import json
import time
import urllib.parse
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PASSWORD = "Test1234!"

# read TELEGRAM_BOT_TOKEN from backend/.env directly
def _bot_token():
    tok = os.environ.get("TELEGRAM_BOT_TOKEN")
    if tok:
        return tok.strip().strip('"').strip("'")
    try:
        with open("/app/backend/.env") as f:
            for line in f:
                if line.startswith("TELEGRAM_BOT_TOKEN"):
                    _, _, v = line.partition("=")
                    return v.strip().strip('"').strip("'")
    except Exception:
        return None
    return None


BOT_TOKEN = _bot_token()


def build_init_data(tg_id: int, first_name="TestTG", username="testtg", auth_date=2000000000, query_id="AAA"):
    user_payload = json.dumps({
        "id": tg_id,
        "first_name": first_name,
        "username": username,
        "language_code": "en",
    }, separators=(",", ":"))
    fields = {
        "auth_date": str(auth_date),
        "query_id": query_id,
        "user": user_payload,
    }
    data_check_string = "\n".join(f"{k}={fields[k]}" for k in sorted(fields.keys()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    hash_hex = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    # url-encode field values, add hash last (order doesn't matter for validator)
    parts = [f"{k}={urllib.parse.quote(v, safe='')}" for k, v in fields.items()]
    parts.append(f"hash={hash_hex}")
    return "&".join(parts)


def _login(email, password):
    return requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)


# ---------------------------------------------------------------------------
# 1) SESSION_OVERRIDDEN detail on single-session rotation
# ---------------------------------------------------------------------------
class TestSessionOverridden:
    def test_second_login_returns_session_overridden_detail(self):
        r1 = _login(USER_EMAIL, USER_PASSWORD)
        assert r1.status_code == 200, r1.text
        token_a = r1.json().get("token") or r1.json().get("access_token")
        assert token_a

        me1 = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token_a}"}, timeout=30)
        assert me1.status_code == 200, me1.text

        r2 = _login(USER_EMAIL, USER_PASSWORD)
        assert r2.status_code == 200
        token_b = r2.json().get("token") or r2.json().get("access_token")
        assert token_b and token_b != token_a

        me_a2 = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token_a}"}, timeout=30)
        assert me_a2.status_code == 401, me_a2.text
        detail = me_a2.json().get("detail", "")
        assert detail == "SESSION_OVERRIDDEN", f"expected SESSION_OVERRIDDEN, got {detail!r}"

        me_b = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token_b}"}, timeout=30)
        assert me_b.status_code == 200, me_b.text


# ---------------------------------------------------------------------------
# 2) Basic login for both seeded users
# ---------------------------------------------------------------------------
class TestSeededLogins:
    def test_admin_login_is_admin(self):
        r = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
        assert r.status_code == 200, r.text
        assert (r.json().get("user") or {}).get("is_admin") is True

    def test_user_login(self):
        r = _login(USER_EMAIL, USER_PASSWORD)
        assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# 3) Telegram miniapp CHOICE + CREATE flow (unlinked → choice_required → create → auto-login)
# ---------------------------------------------------------------------------
TG_ID_NEW = 777111222  # brand-new telegram id for create flow
TG_ID_LINK = 777333444  # brand-new telegram id for link flow


@pytest.fixture(scope="module")
def created_tg_user_ids():
    ids = []
    yield ids
    # teardown: delete any users created here, and unlink telegram fields on testuser
    try:
        # need admin session
        r = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
        if r.status_code != 200:
            return
        admin_token = r.json().get("token") or r.json().get("access_token")
        headers = {"Authorization": f"Bearer {admin_token}"}
        # try admin delete endpoint if available; else best-effort via Mongo (skip)
        # We'll rely on direct pymongo if available.
    except Exception:
        pass
    try:
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient
        MONGO_URL = None
        with open("/app/backend/.env") as f:
            for line in f:
                if line.startswith("MONGO_URL"):
                    MONGO_URL = line.split("=", 1)[1].strip().strip('"').strip("'")
                if line.startswith("DB_NAME"):
                    DB_NAME = line.split("=", 1)[1].strip().strip('"').strip("'")
        client = AsyncIOMotorClient(MONGO_URL)
        db = client[DB_NAME]

        async def cleanup():
            SEEDED_EMAILS = {ADMIN_EMAIL, USER_EMAIL}
            for tg_id in [TG_ID_NEW, TG_ID_LINK]:
                await db.users.delete_many({
                    "email": {"$nin": list(SEEDED_EMAILS)},
                    "$or": [
                        {"telegram_id": tg_id},
                        {"telegram_id": str(tg_id)},
                        {"telegram_user_id": str(tg_id)},
                    ],
                })
            # unlink telegram fields from testuser@example.com
            await db.users.update_one(
                {"email": USER_EMAIL},
                {"$unset": {
                    "telegram_id": "",
                    "telegram_user_id": "",
                    "telegram_chat_id": "",
                    "telegram_username": "",
                    "tg_username": "",
                    "tg_first_name": "",
                    "telegram_verified": "",
                    "telegram_auth_verified_at": "",
                }},
            )

        asyncio.get_event_loop().run_until_complete(cleanup())
    except Exception as e:
        print("cleanup warn:", e)


class TestTelegramMiniAppChoice:
    def test_bot_token_available(self):
        assert BOT_TOKEN, "TELEGRAM_BOT_TOKEN must be present"

    def test_miniapp_unlinked_returns_choice_required(self, created_tg_user_ids):
        init_data = build_init_data(TG_ID_NEW, first_name="NewTG", username="newtg")
        r = requests.post(f"{API}/auth/telegram/miniapp", json={"init_data": init_data}, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("status") == "choice_required", body
        assert "token" not in body, "must NOT return token on unlinked miniapp"
        tg = body.get("telegram") or {}
        assert str(tg.get("id")) == str(TG_ID_NEW)

    def test_miniapp_create_then_auto_login(self, created_tg_user_ids):
        init_data = build_init_data(TG_ID_NEW, first_name="NewTG", username="newtg")
        r = requests.post(f"{API}/auth/telegram/miniapp/create", json={"init_data": init_data}, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        token = body.get("token") or body.get("access_token")
        assert token, body
        assert body.get("is_new_signup") is True, body
        created_tg_user_ids.append(TG_ID_NEW)

        # Now the same init_data should auto-login (linked) with is_new_signup=false
        r2 = requests.post(f"{API}/auth/telegram/miniapp", json={"init_data": init_data}, timeout=30)
        assert r2.status_code == 200, r2.text
        body2 = r2.json()
        assert body2.get("status") == "ok", body2
        assert body2.get("token"), body2
        assert body2.get("is_new_signup") is False


# ---------------------------------------------------------------------------
# 4) Telegram LINK-to-existing flow
# ---------------------------------------------------------------------------
class TestTelegramLinkExisting:
    def test_link_and_auto_login_linked_account(self, created_tg_user_ids):
        # login testuser email
        r = _login(USER_EMAIL, USER_PASSWORD)
        assert r.status_code == 200
        token = r.json().get("token") or r.json().get("access_token")
        assert token

        init_data = build_init_data(TG_ID_LINK, first_name="LinkTG", username="linktg")
        headers = {"Authorization": f"Bearer {token}"}

        r1 = requests.post(f"{API}/auth/telegram-link", json={"init_data": init_data}, headers=headers, timeout=30)
        assert r1.status_code == 200, r1.text
        b1 = r1.json()
        assert b1.get("linked") is True, b1

        # Idempotent second call
        r2 = requests.post(f"{API}/auth/telegram-link", json={"init_data": init_data}, headers=headers, timeout=30)
        assert r2.status_code == 200, r2.text
        assert r2.json().get("linked") is True

        created_tg_user_ids.append(TG_ID_LINK)

        # Now POST miniapp with this init_data — should auto-login to testuser
        rm = requests.post(f"{API}/auth/telegram/miniapp", json={"init_data": init_data}, timeout=30)
        assert rm.status_code == 200, rm.text
        body = rm.json()
        assert body.get("status") == "ok", body
        assert body.get("token"), body
        assert (body.get("user") or {}).get("email") == USER_EMAIL, body
