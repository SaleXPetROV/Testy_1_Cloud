"""Iter5: Token persistence after re-login (single-session enforcement DISABLED).

Verifies the intentional REVERSE of iter1..iter4 behavior:
- Logging in twice for the same user must NOT invalidate the earlier token.
- Both tokens must return 200 on /api/auth/me.
- No endpoint (auth/me, /api/businesses/patrons, /api/history/types,
  /api/security/status) may return 401 SESSION_OVERRIDDEN for a validly-signed
  token whose user still exists.
- Telegram miniapp create flow: two consecutive miniapp calls for the same
  tg id must both yield tokens that authenticate afterwards.
- Regression: create/link Telegram choice flow (from iter4) still works.

Cleans up any created telegram-test users and unlinks telegram_* fields it
stamps on seeded accounts. Seeded users are preserved.
"""
import os
import sys
import hmac
import hashlib
import json
import urllib.parse
import asyncio
import pytest
import requests

sys.path.insert(0, "/app/backend")


def _read_env_file(path, key):
    try:
        with open(path) as f:
            for line in f:
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        return None
    return None


BASE_URL = (
    os.environ.get("REACT_APP_BACKEND_URL")
    or _read_env_file("/app/frontend/.env", "REACT_APP_BACKEND_URL")
    or ""
).rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL must be set"
API = f"{BASE_URL}/api"

MONGO_URL = os.environ.get("MONGO_URL") or _read_env_file("/app/backend/.env", "MONGO_URL")
DB_NAME = os.environ.get("DB_NAME") or _read_env_file("/app/backend/.env", "DB_NAME")
BOT_TOKEN = (
    os.environ.get("TELEGRAM_BOT_TOKEN")
    or _read_env_file("/app/backend/.env", "TELEGRAM_BOT_TOKEN")
)

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PASSWORD = "Test1234!"

TG_ID_PERSIST = 889100100  # miniapp double-create persistence
TG_ID_CHOICE = 889200200   # regression create/link choice


def _run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _get_db():
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(MONGO_URL)
    return client[DB_NAME]


def _login(email, password):
    return requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)


def _me(token):
    return requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"}, timeout=30)


def build_init_data(tg_id, first_name="PersistTG", username="persisttg", auth_date=2000000000, query_id="AAA"):
    user_payload = json.dumps({
        "id": int(tg_id),
        "first_name": first_name,
        "username": username,
        "language_code": "en",
    }, separators=(",", ":"))
    fields = {"auth_date": str(auth_date), "query_id": query_id, "user": user_payload}
    dcs = "\n".join(f"{k}={fields[k]}" for k in sorted(fields.keys()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    hash_hex = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    parts = [f"{k}={urllib.parse.quote(v, safe='')}" for k, v in fields.items()]
    parts.append(f"hash={hash_hex}")
    return "&".join(parts)


def _cleanup_tg_ids(tg_ids):
    async def _do():
        db = _get_db()
        SEEDED = {ADMIN_EMAIL, USER_EMAIL}
        for tg in tg_ids:
            await db.users.delete_many({
                "email": {"$nin": list(SEEDED)},
                "$or": [
                    {"telegram_id": tg},
                    {"telegram_id": str(tg)},
                    {"telegram_user_id": str(tg)},
                ],
            })
        await db.tg_login_links.delete_many(
            {"tg_user_id": {"$in": [str(x) for x in tg_ids]}}
        )
    try:
        _run(_do())
    except Exception as e:
        print("cleanup warn:", e)


@pytest.fixture(scope="module", autouse=True)
def _cleanup():
    yield

    async def _do():
        db = _get_db()
        # unlink any telegram_* fields from seeded testuser
        await db.users.update_one(
            {"email": USER_EMAIL},
            {"$unset": {
                "telegram_id": "",
                "telegram_user_id": "",
                "telegram_chat_id": "",
                "telegram_username": "",
                "tg_username": "",
                "tg_first_name": "",
                "tg_last_name": "",
                "telegram_verified": "",
                "telegram_auth_verified_at": "",
                "telegram_notifications": "",
            }},
        )
        await db.tg_login_links.delete_many({"tg_user_id": {"$in": [str(TG_ID_PERSIST), str(TG_ID_CHOICE)]}})

    try:
        _run(_do())
    except Exception as e:
        print("cleanup warn:", e)


@pytest.fixture(scope="class")
def _clean_persist():
    _cleanup_tg_ids([TG_ID_PERSIST])
    yield
    _cleanup_tg_ids([TG_ID_PERSIST])


@pytest.fixture(scope="class")
def _clean_choice():
    _cleanup_tg_ids([TG_ID_CHOICE])
    yield
    _cleanup_tg_ids([TG_ID_CHOICE])


# ---------------------------------------------------------------------------
# 1) Seeded email logins work
# ---------------------------------------------------------------------------
class TestSeededLogins:
    def test_admin_login(self):
        r = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
        assert r.status_code == 200, r.text
        b = r.json()
        assert (b.get("user") or {}).get("is_admin") is True, b
        assert b.get("token") or b.get("access_token")

    def test_user_login(self):
        r = _login(USER_EMAIL, USER_PASSWORD)
        assert r.status_code == 200, r.text
        assert r.json().get("token") or r.json().get("access_token")


# ---------------------------------------------------------------------------
# 2) Core fix: earlier token stays valid after a second login
# ---------------------------------------------------------------------------
class TestTokenPersistence:
    def _double_login_check(self, email, password):
        r1 = _login(email, password)
        assert r1.status_code == 200, r1.text
        t_a = r1.json().get("token") or r1.json().get("access_token")
        assert t_a

        me_a1 = _me(t_a)
        assert me_a1.status_code == 200, me_a1.text

        r2 = _login(email, password)
        assert r2.status_code == 200, r2.text
        t_b = r2.json().get("token") or r2.json().get("access_token")
        assert t_b and t_b != t_a

        # BOTH tokens must still authenticate — no SESSION_OVERRIDDEN
        me_a2 = _me(t_a)
        assert me_a2.status_code == 200, f"token A must survive re-login, got {me_a2.status_code} {me_a2.text}"
        assert me_a2.json().get("detail") != "SESSION_OVERRIDDEN"

        me_b = _me(t_b)
        assert me_b.status_code == 200, me_b.text
        return t_a, t_b

    def test_user_token_persists_across_relogin(self):
        self._double_login_check(USER_EMAIL, USER_PASSWORD)

    def test_admin_token_persists_across_relogin(self):
        self._double_login_check(ADMIN_EMAIL, ADMIN_PASSWORD)


# ---------------------------------------------------------------------------
# 3) Regression: routers with formerly-strict session checks accept OLD token
# ---------------------------------------------------------------------------
class TestRoutersNoSessionOverridden:
    def test_business_history_security_accept_old_token(self):
        r1 = _login(USER_EMAIL, USER_PASSWORD)
        assert r1.status_code == 200
        t_a = r1.json().get("token") or r1.json().get("access_token")

        r2 = _login(USER_EMAIL, USER_PASSWORD)
        assert r2.status_code == 200
        t_b = r2.json().get("token") or r2.json().get("access_token")
        assert t_a and t_b and t_a != t_b

        h = {"Authorization": f"Bearer {t_a}"}  # OLD token

        endpoints = [
            f"{API}/businesses/patrons",
            f"{API}/history/types",
            f"{API}/history/summary",
            f"{API}/security/status",
            f"{API}/auth/me",
        ]
        for url in endpoints:
            r = requests.get(url, headers=h, timeout=30)
            assert r.status_code != 401 or (r.json().get("detail") != "SESSION_OVERRIDDEN"), \
                f"{url} -> {r.status_code} {r.text}"
            # For auth/me / patrons / history / security_status we expect 200
            if url.endswith(("/auth/me", "/businesses/patrons", "/history/types",
                             "/history/summary", "/security/status")):
                assert r.status_code == 200, f"{url} -> {r.status_code} {r.text}"


# ---------------------------------------------------------------------------
# 4) Telegram miniapp: two consecutive calls for same TG id -> both tokens work
# ---------------------------------------------------------------------------
class TestMiniappTokenPersistence:
    def test_pre_cleanup_and_create(self, _clean_persist):
        # pre-clean this TG id
        async def _pre():
            db = _get_db()
            await db.users.delete_many({
                "email": {"$nin": [ADMIN_EMAIL, USER_EMAIL]},
                "$or": [
                    {"telegram_id": TG_ID_PERSIST},
                    {"telegram_id": str(TG_ID_PERSIST)},
                    {"telegram_user_id": str(TG_ID_PERSIST)},
                ],
            })
        _run(_pre())

        init_data = build_init_data(TG_ID_PERSIST)
        # First call -> choice_required (unlinked)
        r_choice = requests.post(f"{API}/auth/telegram/miniapp", json={"init_data": init_data}, timeout=30)
        assert r_choice.status_code == 200, r_choice.text
        assert r_choice.json().get("status") == "choice_required", r_choice.json()

        # CREATE -> token T1
        r_create = requests.post(f"{API}/auth/telegram/miniapp/create", json={"init_data": init_data}, timeout=30)
        assert r_create.status_code == 200, r_create.text
        b1 = r_create.json()
        t1 = b1.get("token")
        assert t1, b1

        me1a = _me(t1)
        assert me1a.status_code == 200, me1a.text

        # Second miniapp call for SAME tg id -> auto-login token T2 (linked now)
        r2 = requests.post(f"{API}/auth/telegram/miniapp", json={"init_data": init_data}, timeout=30)
        assert r2.status_code == 200, r2.text
        b2 = r2.json()
        assert b2.get("status") == "ok", b2
        t2 = b2.get("token")
        assert t2 and t2 != t1, b2

        # BOTH tokens must remain valid
        me1b = _me(t1)
        assert me1b.status_code == 200, \
            f"miniapp T1 must survive T2 issuance, got {me1b.status_code} {me1b.text}"
        assert me1b.json().get("detail") != "SESSION_OVERRIDDEN"

        me2 = _me(t2)
        assert me2.status_code == 200, me2.text


# ---------------------------------------------------------------------------
# 5) Regression: iter4 deep-link/miniapp create + link-to-existing still works
# ---------------------------------------------------------------------------
class TestChoiceFlowRegression:
    def test_choice_create_and_link_existing(self, _clean_choice):
        # pre-clean
        async def _pre():
            db = _get_db()
            await db.users.delete_many({
                "email": {"$nin": [ADMIN_EMAIL, USER_EMAIL]},
                "$or": [
                    {"telegram_id": TG_ID_CHOICE},
                    {"telegram_id": str(TG_ID_CHOICE)},
                    {"telegram_user_id": str(TG_ID_CHOICE)},
                ],
            })
            await db.users.update_one(
                {"email": USER_EMAIL},
                {"$unset": {"telegram_id": "", "telegram_user_id": ""}},
            )
        _run(_pre())

        init_data = build_init_data(TG_ID_CHOICE, first_name="ChoiceTG", username="choicetg")

        # Unlinked -> choice_required
        r1 = requests.post(f"{API}/auth/telegram/miniapp", json={"init_data": init_data}, timeout=30)
        assert r1.status_code == 200, r1.text
        assert r1.json().get("status") == "choice_required", r1.json()

        # Login testuser -> bearer
        rl = _login(USER_EMAIL, USER_PASSWORD)
        assert rl.status_code == 200
        bearer = rl.json().get("token") or rl.json().get("access_token")

        # Link this TG id to existing testuser via /auth/telegram-link
        r_link = requests.post(
            f"{API}/auth/telegram-link",
            json={"init_data": init_data},
            headers={"Authorization": f"Bearer {bearer}"},
            timeout=30,
        )
        assert r_link.status_code == 200, f"link failed: {r_link.status_code} {r_link.text}"
        assert r_link.json().get("linked") is True, r_link.text

        # Now miniapp for same tg id -> auto login as testuser
        r_auto = requests.post(f"{API}/auth/telegram/miniapp", json={"init_data": init_data}, timeout=30)
        assert r_auto.status_code == 200, r_auto.text
        b = r_auto.json()
        assert b.get("status") == "ok", b
        assert (b.get("user") or {}).get("email") == USER_EMAIL, b

        # And /auth/me works with new token
        t = b.get("token")
        assert t
        assert _me(t).status_code == 200
