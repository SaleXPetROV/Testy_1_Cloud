"""Iteration 8 — Backend tests for 5 Telegram auth fixes.

FIX 1: TG-only user cannot unlink Telegram (both endpoints must return 400
       telegram_only_auth_cannot_unlink).
FIX 2: Same Telegram identity cannot be bound to a second site account via
       /api/telegram/generate-link-token + /start <link_token>.
FIX 3: Bot notifications default to English; Indonesian added, respects
       telegram_mappings.language.
FIX 4: Session rotates on every login — old tokens across methods invalidated.
FIX 5: Multi-method auth: same account is reachable via email/password AND
       Telegram login-link once bound.
"""
from __future__ import annotations

import os
import time
import uuid
import asyncio
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://ton-auth-debug.preview.emergentagent.com").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PASSWORD = "Test1234!"

TG_FIELDS_UNSET = {
    "telegram_id": "",
    "telegram_user_id": "",
    "telegram_chat_id": "",
    "telegram_username": "",
    "telegram_verified": "",
    "telegram_notifications": "",
    "telegram_auth_verified_at": "",
    "tg_username": "",
    "tg_first_name": "",
    "tg_last_name": "",
}


@pytest.fixture(scope="module")
def mongo_db():
    client = MongoClient(MONGO_URL)
    yield client[DB_NAME]
    client.close()


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


def _login(sess, email, password):
    # Use a bare request (no session cookies) so subsequent /me calls that pass
    # Bearer tokens aren't shadowed by the login-set access_token cookie.
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login failed {r.status_code} {r.text}"
    j = r.json()
    return j.get("access_token") or j.get("token")


def _me(sess, token):
    # Cookie-less client so the Bearer token is what actually authenticates.
    return requests.get(
        f"{BASE_URL}/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )


def _unset_admin_tg(db):
    db.users.update_one({"email": ADMIN_EMAIL}, {"$unset": TG_FIELDS_UNSET})


def _cleanup_qa_tg_users(db):
    db.users.delete_many({"registration_method": "telegram", "$or": [
        {"tg_username": {"$regex": "^qa_"}},
        {"telegram_username": {"$regex": "^qa_"}},
    ]})


# ------------------------------------------------------------------
# FIX 1 — TG-only user cannot unlink Telegram
# ------------------------------------------------------------------
class TestFix1TelegramOnlyUnlinkRefused:
    def test_tg_only_unlink_both_endpoints_return_400(self, s, mongo_db):
        # Create a TG-only user directly (registration_method='telegram', no
        # password, no wallet, no google). Then mint a JWT for them via
        # /api/telegram/login-link + simulated webhook.
        tg_uid = int(str(uuid.uuid4().int)[:9])  # unique numeric tg id
        username = f"qa_tgonly_{tg_uid}"

        # Kick off login-link
        start = s.post(f"{BASE_URL}/api/auth/telegram/login-link/start", timeout=15)
        assert start.status_code == 200, start.text
        jti = start.json()["jti"]

        # Simulate /start login_<jti>
        wh = s.post(f"{BASE_URL}/api/telegram/webhook", json={
            "update_id": int(time.time()),
            "message": {
                "message_id": 1,
                "from": {"id": tg_uid, "is_bot": False, "first_name": "QA", "username": username, "language_code": "en"},
                "chat": {"id": tg_uid, "type": "private"},
                "date": int(time.time()),
                "text": f"/start login_{jti}",
                "entities": [{"offset": 0, "length": 6, "type": "bot_command"}],
            }
        }, timeout=15)
        assert wh.status_code == 200, wh.text

        # Poll status
        token = None
        for _ in range(20):
            r = s.get(f"{BASE_URL}/api/auth/telegram/login-link/status/{jti}", timeout=10)
            j = r.json()
            if j.get("status") == "confirmed":
                token = j.get("token")
                break
            time.sleep(0.6)
        assert token, "TG login-link did not confirm"

        # Sanity: the user is TG-only
        user_doc = mongo_db.users.find_one({"telegram_user_id": str(tg_uid)})
        assert user_doc, "TG-only user was not created"
        assert not user_doc.get("hashed_password")
        assert not user_doc.get("wallet_address") and not user_doc.get("raw_address")
        assert not user_doc.get("google_id")

        headers = {"Authorization": f"Bearer {token}"}

        # Endpoint A: /api/auth/telegram/unlink
        r1 = s.post(f"{BASE_URL}/api/auth/telegram/unlink", headers=headers, timeout=15)
        assert r1.status_code == 400, f"expected 400 got {r1.status_code} {r1.text}"
        assert r1.json().get("detail") == "telegram_only_auth_cannot_unlink"

        # Endpoint B: /api/auth/unlink-telegram
        r2 = s.post(f"{BASE_URL}/api/auth/unlink-telegram", headers=headers, timeout=15)
        assert r2.status_code == 400, f"expected 400 got {r2.status_code} {r2.text}"
        assert r2.json().get("detail") == "telegram_only_auth_cannot_unlink"

        # cleanup
        mongo_db.users.delete_one({"id": user_doc["id"]})


# ------------------------------------------------------------------
# FIX 2 — Same TG identity cannot be bound to two site accounts
# ------------------------------------------------------------------
class TestFix2NoDuplicateBinding:
    def test_second_bind_rejected_admin_stays_unbound(self, s, mongo_db):
        _unset_admin_tg(mongo_db)

        # 1) Bind TG_A -> SITE_A (a fresh TG-only user) via login-link
        tg_uid = int(str(uuid.uuid4().int)[:9])
        username = f"qa_dup_{tg_uid}"
        start = s.post(f"{BASE_URL}/api/auth/telegram/login-link/start", timeout=15)
        jti = start.json()["jti"]
        s.post(f"{BASE_URL}/api/telegram/webhook", json={
            "update_id": int(time.time()) + 1,
            "message": {
                "message_id": 1,
                "from": {"id": tg_uid, "is_bot": False, "first_name": "QA", "username": username},
                "chat": {"id": tg_uid, "type": "private"},
                "date": int(time.time()),
                "text": f"/start login_{jti}",
                "entities": [{"offset": 0, "length": 6, "type": "bot_command"}],
            }
        }, timeout=15)
        # Confirm site_a exists
        site_a_id = None
        for _ in range(20):
            r = s.get(f"{BASE_URL}/api/auth/telegram/login-link/status/{jti}", timeout=10)
            if r.json().get("status") == "confirmed":
                site_a_id = r.json()["user"]["id"]
                break
            time.sleep(0.6)
        assert site_a_id, "site_a not created"

        # 2) Admin (SITE_B) generates a link-token
        admin_token = _login(s, ADMIN_EMAIL, ADMIN_PASSWORD)
        gen = s.post(f"{BASE_URL}/api/telegram/generate-link-token",
                     headers={"Authorization": f"Bearer {admin_token}"}, timeout=15)
        assert gen.status_code == 200, gen.text
        link_token = gen.json()["token"]

        # 3) SAME TG_A opens /start <link_token> in the bot
        wh = s.post(f"{BASE_URL}/api/telegram/webhook", json={
            "update_id": int(time.time()) + 2,
            "message": {
                "message_id": 2,
                "from": {"id": tg_uid, "is_bot": False, "first_name": "QA", "username": username},
                "chat": {"id": tg_uid, "type": "private"},
                "date": int(time.time()),
                "text": f"/start {link_token}",
                "entities": [{"offset": 0, "length": 6, "type": "bot_command"}],
            }
        }, timeout=15)
        assert wh.status_code == 200
        time.sleep(1.5)  # let background task run

        # 4) Admin (re-login for freshness) must still have NO telegram fields
        admin_token2 = _login(s, ADMIN_EMAIL, ADMIN_PASSWORD)
        r = _me(s, admin_token2)
        assert r.status_code == 200, r.text
        me = r.json()
        assert not me.get("telegram_id"), f"admin telegram_id leaked: {me.get('telegram_id')}"
        assert not me.get("telegram_chat_id"), f"admin telegram_chat_id leaked: {me.get('telegram_chat_id')}"
        assert not me.get("telegram_username"), f"admin telegram_username leaked: {me.get('telegram_username')}"

        # Direct DB check for legacy fields too
        admin_doc = mongo_db.users.find_one({"email": ADMIN_EMAIL})
        for f in ("telegram_id", "telegram_user_id", "telegram_chat_id", "telegram_username"):
            assert not admin_doc.get(f), f"admin.{f} leaked in DB: {admin_doc.get(f)}"

        # cleanup site_a
        mongo_db.users.delete_one({"id": site_a_id})


# ------------------------------------------------------------------
# FIX 3 — Language defaults to English; Indonesian added
# ------------------------------------------------------------------
class TestFix3LanguageDefaults:
    def test_catalogue_has_indonesian_and_keyboard_has_lang_id(self, mongo_db):
        # Static check on the code catalogue
        from routes.telegram_notifications import _MESSAGES  # type: ignore
        for key in ("linked", "unlinked", "login_new", "login_existing",
                    "login_link_invalid", "login_link_used", "login_link_expired",
                    "login_failed", "login_confirm_failed"):
            assert key in _MESSAGES, f"missing key {key}"
            assert "id" in _MESSAGES[key], f"missing 'id' translation for {key}"
            assert "en" in _MESSAGES[key], f"missing 'en' translation for {key}"

        # cmd_start keyboard must include lang_id (Bahasa Indonesia)
        import re
        with open("/app/backend/telegram_bot.py", "r") as f:
            src = f.read()
        assert "Bahasa Indonesia" in src
        assert 'callback_data": "lang_id"' in src

    def test_new_tg_user_default_language_is_en_after_signup(self, s, mongo_db):
        """FIX 3(a) end-to-end: for a fresh TG id (never used the bot),
        `/start login_<jti>` should reply in ENGLISH — even though the
        newly-created user document should not force a non-English
        language override.

        Product spec: "the reply from the bot must be in ENGLISH" when the
        user has NEVER picked a language.
        """
        tg_uid = int(str(uuid.uuid4().int)[:9])
        username = f"qa_langfresh_{tg_uid}"
        # Ensure no prior state
        mongo_db.telegram_mappings.delete_many({"chat_id": str(tg_uid)})
        mongo_db.users.delete_many({"telegram_chat_id": str(tg_uid)})

        start = s.post(f"{BASE_URL}/api/auth/telegram/login-link/start", timeout=15)
        jti = start.json()["jti"]
        s.post(f"{BASE_URL}/api/telegram/webhook", json={
            "update_id": int(time.time()) + 100,
            "message": {
                "message_id": 1,
                "from": {"id": tg_uid, "is_bot": False, "first_name": "QA",
                         "username": username, "language_code": "en"},
                "chat": {"id": tg_uid, "type": "private"},
                "date": int(time.time()),
                "text": f"/start login_{jti}",
                "entities": [{"offset": 0, "length": 6, "type": "bot_command"}],
            }
        }, timeout=15)

        # Wait for confirmation
        for _ in range(20):
            r = s.get(f"{BASE_URL}/api/auth/telegram/login-link/status/{jti}", timeout=10)
            if r.json().get("status") == "confirmed":
                break
            time.sleep(0.6)

        # After signup, resolve_bot_language for this chat_id should still be 'en'
        from routes.telegram_notifications import resolve_bot_language as _rbl2
        from motor.motor_asyncio import AsyncIOMotorClient as _MC2
        loop = asyncio.new_event_loop()
        try:
            async def _r():
                client = _MC2(MONGO_URL)
                try:
                    return await _rbl2(client[DB_NAME], str(tg_uid))
                finally:
                    client.close()
            lang = loop.run_until_complete(_r())
        finally:
            loop.close()

        # cleanup
        mongo_db.users.delete_many({"telegram_chat_id": str(tg_uid)})

        assert lang == "en", (
            f"After /start login_<jti> from a fresh TG id with no prior "
            f"language selection, resolve_bot_language returned {lang!r} — "
            f"the bot reply will therefore be sent in that language "
            f"instead of English (FIX 3(a) spec)."
        )
        # (a) resolve_bot_language for a fresh TG id (no mapping, no user)
        # must return "en" per FIX 3 default. This is the pre-/start state
        # the bot uses to reply to a first-time /start.
        from routes.telegram_notifications import resolve_bot_language, tmsg
        from motor.motor_asyncio import AsyncIOMotorClient

        fresh_uid = int(str(uuid.uuid4().int)[:9])
        mongo_db.telegram_mappings.delete_many({"chat_id": str(fresh_uid)})
        # Make sure no existing user has this tg id
        mongo_db.users.delete_many({"telegram_chat_id": str(fresh_uid)})
        mongo_db.users.delete_many({"telegram_id": str(fresh_uid)})

        async def _resolve(uid):
            client = AsyncIOMotorClient(MONGO_URL)
            try:
                return await resolve_bot_language(client[DB_NAME], str(uid))
            finally:
                client.close()

        loop = asyncio.new_event_loop()
        try:
            lang_default = loop.run_until_complete(_resolve(fresh_uid))
        finally:
            loop.close()
        assert lang_default == "en", f"expected default 'en' for a fresh chat_id, got {lang_default!r}"
        msg_en = tmsg("login_new", "en")
        assert "Signed in" in msg_en or "Account created" in msg_en, msg_en

        # (b) When telegram_mappings.language='id' is set, resolve returns 'id'.
        selected_uid = int(str(uuid.uuid4().int)[:9])
        mongo_db.telegram_mappings.update_one(
            {"chat_id": str(selected_uid)},
            {"$set": {"chat_id": str(selected_uid), "language": "id"}},
            upsert=True,
        )
        loop = asyncio.new_event_loop()
        try:
            lang_id = loop.run_until_complete(_resolve(selected_uid))
        finally:
            loop.close()
        assert lang_id == "id", f"expected 'id' after mapping, got {lang_id!r}"
        msg_id = tmsg("login_new", "id")
        assert ("Anda" in msg_id) or ("Akun" in msg_id) or ("masuk" in msg_id.lower()), msg_id

        # cleanup
        mongo_db.telegram_mappings.delete_many(
            {"chat_id": {"$in": [str(fresh_uid), str(selected_uid)]}}
        )


# ------------------------------------------------------------------
# FIX 4 — Session rotates on every login
# ------------------------------------------------------------------
class TestFix4SessionRotation:
    def test_email_then_tg_then_email_rotation(self, s, mongo_db):
        _unset_admin_tg(mongo_db)

        # Bind TG to admin so we can login via TG. Use link-token flow.
        admin_seed = _login(s, ADMIN_EMAIL, ADMIN_PASSWORD)
        gen = s.post(f"{BASE_URL}/api/telegram/generate-link-token",
                     headers={"Authorization": f"Bearer {admin_seed}"}, timeout=15)
        link_token = gen.json()["token"]
        tg_uid = int(str(uuid.uuid4().int)[:9])
        # ensure this TG id is not already on any account
        mongo_db.users.update_many({"telegram_user_id": str(tg_uid)}, {"$unset": TG_FIELDS_UNSET})
        s.post(f"{BASE_URL}/api/telegram/webhook", json={
            "update_id": int(time.time()) + 30,
            "message": {
                "message_id": 1,
                "from": {"id": tg_uid, "is_bot": False, "first_name": "Admin", "username": f"qa_admin_bind_{tg_uid}"},
                "chat": {"id": tg_uid, "type": "private"},
                "date": int(time.time()),
                "text": f"/start {link_token}",
                "entities": [{"offset": 0, "length": 6, "type": "bot_command"}],
            }
        }, timeout=15)
        # Wait for bind
        for _ in range(20):
            doc = mongo_db.users.find_one({"email": ADMIN_EMAIL})
            if str(doc.get("telegram_user_id") or "") == str(tg_uid) or \
               str(doc.get("telegram_chat_id") or "") == str(tg_uid):
                break
            time.sleep(0.5)
        admin_doc = mongo_db.users.find_one({"email": ADMIN_EMAIL})
        assert str(admin_doc.get("telegram_user_id") or admin_doc.get("telegram_chat_id") or "") == str(tg_uid), \
            "admin TG bind failed — cannot proceed with FIX 4"

        # STEP 1: login via email
        TOKEN_EMAIL = _login(s, ADMIN_EMAIL, ADMIN_PASSWORD)
        r = _me(s, TOKEN_EMAIL)
        assert r.status_code == 200

        # STEP 2: login via TG (fresh /start login_<jti>)
        start = s.post(f"{BASE_URL}/api/auth/telegram/login-link/start", timeout=15)
        jti = start.json()["jti"]
        s.post(f"{BASE_URL}/api/telegram/webhook", json={
            "update_id": int(time.time()) + 40,
            "message": {
                "message_id": 1,
                "from": {"id": tg_uid, "is_bot": False, "first_name": "Admin", "username": f"qa_admin_bind_{tg_uid}"},
                "chat": {"id": tg_uid, "type": "private"},
                "date": int(time.time()),
                "text": f"/start login_{jti}",
                "entities": [{"offset": 0, "length": 6, "type": "bot_command"}],
            }
        }, timeout=15)
        TOKEN_TG = None
        for _ in range(20):
            r = s.get(f"{BASE_URL}/api/auth/telegram/login-link/status/{jti}", timeout=10)
            if r.json().get("status") == "confirmed":
                TOKEN_TG = r.json()["token"]
                break
            time.sleep(0.6)
        assert TOKEN_TG, "TG login did not confirm"

        # Old TOKEN_EMAIL now invalid
        r_old = _me(s, TOKEN_EMAIL)
        assert r_old.status_code == 401, f"old email token should be 401 got {r_old.status_code}"
        detail = r_old.json().get("detail", "")
        assert "session_invalidated" in str(detail).lower(), f"unexpected detail: {detail}"

        # New TOKEN_TG works, same admin
        r_tg = _me(s, TOKEN_TG)
        assert r_tg.status_code == 200
        me_tg = r_tg.json()
        assert me_tg.get("email") == ADMIN_EMAIL
        assert me_tg.get("is_admin") is True

        # STEP 3: login via email again
        TOKEN_EMAIL2 = _login(s, ADMIN_EMAIL, ADMIN_PASSWORD)
        r_tg_old = _me(s, TOKEN_TG)
        assert r_tg_old.status_code == 401, f"old TG token should be 401 got {r_tg_old.status_code}"
        r_email2 = _me(s, TOKEN_EMAIL2)
        assert r_email2.status_code == 200

        # Save for FIX 5 chain
        TestFix4SessionRotation.saved_tg_uid = tg_uid


# ------------------------------------------------------------------
# FIX 5 — Multi-method auth: both flows land on the same admin account
# ------------------------------------------------------------------
class TestFix5MultiMethodAuth:
    def test_email_and_tg_land_on_same_account(self, s, mongo_db):
        # Ensure admin is bound to a TG id
        tg_uid = getattr(TestFix4SessionRotation, "saved_tg_uid", None)
        if not tg_uid:
            # Fresh bind
            admin_seed = _login(s, ADMIN_EMAIL, ADMIN_PASSWORD)
            gen = s.post(f"{BASE_URL}/api/telegram/generate-link-token",
                         headers={"Authorization": f"Bearer {admin_seed}"}, timeout=15).json()
            link_token = gen["token"]
            tg_uid = int(str(uuid.uuid4().int)[:9])
            s.post(f"{BASE_URL}/api/telegram/webhook", json={
                "update_id": int(time.time()) + 50,
                "message": {
                    "message_id": 1,
                    "from": {"id": tg_uid, "is_bot": False, "first_name": "Admin", "username": f"qa_admin_5_{tg_uid}"},
                    "chat": {"id": tg_uid, "type": "private"},
                    "date": int(time.time()),
                    "text": f"/start {link_token}",
                    "entities": [{"offset": 0, "length": 6, "type": "bot_command"}],
                }
            }, timeout=15)
            time.sleep(2)

        admin_doc = mongo_db.users.find_one({"email": ADMIN_EMAIL})
        admin_id = admin_doc["id"]

        # (a) email/password login
        tok_email = _login(s, ADMIN_EMAIL, ADMIN_PASSWORD)
        me_email = _me(s, tok_email).json()
        assert me_email["id"] == admin_id
        assert me_email["email"] == ADMIN_EMAIL
        assert me_email.get("is_admin") is True

        # (b) TG login-link
        start = s.post(f"{BASE_URL}/api/auth/telegram/login-link/start", timeout=15)
        jti = start.json()["jti"]
        s.post(f"{BASE_URL}/api/telegram/webhook", json={
            "update_id": int(time.time()) + 60,
            "message": {
                "message_id": 1,
                "from": {"id": tg_uid, "is_bot": False, "first_name": "Admin", "username": f"qa_admin_5_{tg_uid}"},
                "chat": {"id": tg_uid, "type": "private"},
                "date": int(time.time()),
                "text": f"/start login_{jti}",
                "entities": [{"offset": 0, "length": 6, "type": "bot_command"}],
            }
        }, timeout=15)
        tok_tg = None
        for _ in range(20):
            r = s.get(f"{BASE_URL}/api/auth/telegram/login-link/status/{jti}", timeout=10)
            if r.json().get("status") == "confirmed":
                tok_tg = r.json()["token"]
                break
            time.sleep(0.6)
        assert tok_tg
        me_tg = _me(s, tok_tg).json()
        assert me_tg["id"] == admin_id, f"TG login resolved to different user {me_tg['id']} vs {admin_id}"
        assert me_tg["email"] == ADMIN_EMAIL
        assert me_tg.get("is_admin") is True


# Final cleanup — remove any qa_* TG users we created
@pytest.fixture(scope="module", autouse=True)
def cleanup_after(mongo_db):
    yield
    _cleanup_qa_tg_users(mongo_db)
    _unset_admin_tg(mongo_db)
