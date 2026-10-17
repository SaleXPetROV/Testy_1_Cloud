"""Iter4: Telegram DEEP-LINK login choice/create/link flow.

Verifies the fix for the bug where the browser deep-link Telegram sign-in was
silently auto-creating an account instead of offering the create/link choice.

Uses the acceptable alternate path per the task spec: import
`routes.telegram_login_link.confirm_login_link` and call it directly to
simulate the bot's /start login_<jti> confirmation. This avoids the need to
craft a valid signed Telegram webhook update.

Cleans up the test telegram identities (888100200, 888300400) and any
telegram_* fields it stamps onto testuser@example.com; keeps seeded users
intact.
"""
import os
import sys
import asyncio
import pytest
import requests

sys.path.insert(0, "/app/backend")


def _read_frontend_env(key):
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        return None
    return None


BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or _read_frontend_env("REACT_APP_BACKEND_URL") or "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL must be set"
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PASSWORD = "Test1234!"

TG_ID_CREATE = 888100200  # deep-link CREATE flow
TG_ID_LINK = 888300400    # deep-link LINK flow


def _read_env(key):
    v = os.environ.get(key)
    if v:
        return v.strip().strip('"').strip("'")
    try:
        with open("/app/backend/.env") as f:
            for line in f:
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        return None
    return None


MONGO_URL = _read_env("MONGO_URL")
DB_NAME = _read_env("DB_NAME")
BOT_TOKEN = _read_env("TELEGRAM_BOT_TOKEN")


def _get_db():
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(MONGO_URL)
    return client[DB_NAME]


def _run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _login(email, password):
    return requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)


# ----------------------------------------------------------------------------
# Fixtures / cleanup
# ----------------------------------------------------------------------------
@pytest.fixture(scope="module", autouse=True)
def _cleanup_at_end():
    yield

    async def _do():
        db = _get_db()
        SEEDED = {ADMIN_EMAIL, USER_EMAIL}
        for tg_id in [TG_ID_CREATE, TG_ID_LINK]:
            await db.users.delete_many({
                "email": {"$nin": list(SEEDED)},
                "$or": [
                    {"telegram_id": tg_id},
                    {"telegram_id": str(tg_id)},
                    {"telegram_user_id": str(tg_id)},
                ],
            })
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
        # also purge any lingering tg_login_links from previous partial runs
        await db.tg_login_links.delete_many({"tg_user_id": {"$in": [str(TG_ID_CREATE), str(TG_ID_LINK)]}})

    try:
        _run(_do())
    except Exception as e:
        print("cleanup warn:", e)


# ----------------------------------------------------------------------------
# Regression: seeded email logins + SESSION_OVERRIDDEN
# ----------------------------------------------------------------------------
class TestRegression:
    def test_admin_login(self):
        r = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
        assert r.status_code == 200, r.text
        assert (r.json().get("user") or {}).get("is_admin") is True

    def test_user_login(self):
        r = _login(USER_EMAIL, USER_PASSWORD)
        assert r.status_code == 200, r.text

    def test_session_overridden_on_rotation(self):
        r1 = _login(USER_EMAIL, USER_PASSWORD)
        assert r1.status_code == 200
        t_a = r1.json().get("token") or r1.json().get("access_token")
        assert t_a
        me1 = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {t_a}"}, timeout=30)
        assert me1.status_code == 200

        r2 = _login(USER_EMAIL, USER_PASSWORD)
        assert r2.status_code == 200
        t_b = r2.json().get("token") or r2.json().get("access_token")
        assert t_b and t_b != t_a

        me_a2 = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {t_a}"}, timeout=30)
        assert me_a2.status_code == 401, me_a2.text
        assert me_a2.json().get("detail") == "SESSION_OVERRIDDEN"

        me_b = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {t_b}"}, timeout=30)
        assert me_b.status_code == 200


# ----------------------------------------------------------------------------
# Helper: simulate the bot confirming a deep-link by directly invoking
# confirm_login_link against the real Mongo database.
# ----------------------------------------------------------------------------
def _simulate_bot_confirm(jti, tg_id, username, first_name):
    async def _do():
        from routes.telegram_login_link import confirm_login_link
        db = _get_db()
        return await confirm_login_link(
            db, f"login_{jti}", str(tg_id), username, first_name, None,
        )
    return _run(_do())


def _start_link():
    r = requests.post(f"{API}/auth/telegram/login-link/start", timeout=30)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b.get("ok") is True
    assert b.get("jti")
    assert b.get("deeplink", "").startswith("https://t.me/")
    return b["jti"]


def _find_user_by_tg(tg_id):
    async def _do():
        db = _get_db()
        return await db.users.find_one({
            "$or": [
                {"telegram_id": int(tg_id)},
                {"telegram_id": str(tg_id)},
                {"telegram_user_id": str(tg_id)},
            ],
        })
    return _run(_do())


# ----------------------------------------------------------------------------
# Deep-link login choice: unlinked TG -> choice_required (no auto-create)
# ----------------------------------------------------------------------------
class TestDeeplinkChoice:
    def test_unlinked_tg_yields_choice_required(self):
        # Ensure clean slate for this tg id
        async def _pre():
            db = _get_db()
            await db.users.delete_many({
                "email": {"$nin": [ADMIN_EMAIL, USER_EMAIL]},
                "$or": [
                    {"telegram_id": TG_ID_CREATE},
                    {"telegram_id": str(TG_ID_CREATE)},
                    {"telegram_user_id": str(TG_ID_CREATE)},
                ],
            })
        _run(_pre())

        jti = _start_link()
        res = _simulate_bot_confirm(jti, TG_ID_CREATE, "qa_newtg", "QA")
        assert res.get("ok") is True, res

        # status must be choice_required, and no user should exist yet
        r = requests.get(f"{API}/auth/telegram/login-link/status/{jti}", timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("status") == "choice_required", body
        tg = body.get("telegram") or {}
        assert str(tg.get("id")) == str(TG_ID_CREATE), body

        user = _find_user_by_tg(TG_ID_CREATE)
        assert user is None, f"no user must be auto-created; found {user and user.get('email')}"

        # stash jti for the next test in the class
        TestDeeplinkChoice._create_jti = jti

    def test_create_new_account_from_deeplink(self):
        jti = getattr(TestDeeplinkChoice, "_create_jti", None)
        assert jti, "prior test must set _create_jti"

        r = requests.post(f"{API}/auth/telegram/login-link/create/{jti}", timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("status") == "confirmed", body
        assert body.get("is_new_signup") is True, body
        token = body.get("token")
        assert token, body

        # token authenticates /auth/me
        me = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"}, timeout=30)
        assert me.status_code == 200, me.text

        # user with the tg id now exists
        user = _find_user_by_tg(TG_ID_CREATE)
        assert user is not None, "user should exist after create"

        # jti should be consumed (deleted)
        r2 = requests.get(f"{API}/auth/telegram/login-link/status/{jti}", timeout=30)
        assert r2.status_code == 200
        assert r2.json().get("status") == "not_found"


# ----------------------------------------------------------------------------
# Deep-link LINK to existing account
# ----------------------------------------------------------------------------
def _build_init_data(tg_id, first_name="LinkTG", username="linktg", auth_date=2000000000, query_id="AAA"):
    import hmac, hashlib, json, urllib.parse
    user_payload = json.dumps({
        "id": int(tg_id),
        "first_name": first_name,
        "username": username,
        "language_code": "en",
    }, separators=(",", ":"))
    fields = {"auth_date": str(auth_date), "query_id": query_id, "user": user_payload}
    data_check_string = "\n".join(f"{k}={fields[k]}" for k in sorted(fields.keys()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    hash_hex = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    parts = [f"{k}={urllib.parse.quote(v, safe='')}" for k, v in fields.items()]
    parts.append(f"hash={hash_hex}")
    return "&".join(parts)


class TestDeeplinkLinkExisting:
    def test_link_requires_auth(self):
        jti = _start_link()
        res = _simulate_bot_confirm(jti, TG_ID_LINK, "qa_linktg", "QA-Link")
        assert res.get("ok") is True

        # No auth header → 401 or 403
        r = requests.post(f"{API}/auth/telegram/login-link/link/{jti}", timeout=30)
        assert r.status_code in (401, 403), r.text

        TestDeeplinkLinkExisting._jti = jti

    def test_link_with_testuser_then_miniapp_auto_login(self):
        jti = getattr(TestDeeplinkLinkExisting, "_jti", None)
        assert jti, "prior test must set _jti"

        # Ensure state still choice_required
        r_st = requests.get(f"{API}/auth/telegram/login-link/status/{jti}", timeout=30)
        assert r_st.json().get("status") == "choice_required", r_st.json()

        # Login testuser to obtain Bearer
        rl = _login(USER_EMAIL, USER_PASSWORD)
        assert rl.status_code == 200
        token = rl.json().get("token") or rl.json().get("access_token")
        assert token

        r = requests.post(
            f"{API}/auth/telegram/login-link/link/{jti}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("linked") is True, body

        # miniapp with signed initData for TG_ID_LINK must auto-login as testuser
        init_data = _build_init_data(TG_ID_LINK)
        rm = requests.post(f"{API}/auth/telegram/miniapp", json={"init_data": init_data}, timeout=30)
        assert rm.status_code == 200, rm.text
        b = rm.json()
        assert b.get("status") == "ok", b
        assert b.get("token"), b
        assert (b.get("user") or {}).get("email") == USER_EMAIL, b


# ----------------------------------------------------------------------------
# i18n static check
# ----------------------------------------------------------------------------
class TestI18nSec2faNeedEmail:
    def test_all_9_langs_have_key(self):
        with open("/app/frontend/src/lib/translations.js", encoding="utf-8") as f:
            content = f.read()
        assert "__sec2faEmailI18n" in content, "expected __sec2faEmailI18n block"
        for lang in ["en", "ru", "es", "zh", "fr", "de", "ja", "ko", "id"]:
            # Look inside the __sec2faEmailI18n object for a `<lang>:` line with sec2faNeedEmail
            marker = f"{lang}: {{ sec2faNeedEmail:"
            assert marker in content, f"language '{lang}' missing sec2faNeedEmail in __sec2faEmailI18n"

    def test_securitypage_uses_t_key(self):
        with open("/app/frontend/src/pages/SecurityPage.jsx", encoding="utf-8") as f:
            src = f.read()
        assert "t('sec2faNeedEmail')" in src or 't("sec2faNeedEmail")' in src, \
            "SecurityPage.jsx must use t('sec2faNeedEmail')"
