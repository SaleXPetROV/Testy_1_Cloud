"""Iteration 9 — Retest of FIX 3(a) and spot-check FIX 3(b).

FIX 3(a): Fresh TG-only user (no telegram_mappings, no users doc) does
/api/auth/telegram/login-link/start + /start login_<jti> webhook must get an
ENGLISH reply (tmsg('login_new','en')). The new users doc language must be 'en'.

FIX 3(b): After posting a `lang_id` callback_query for a chat_id (writes
telegram_mappings.language='id'), a subsequent /start login_<jti> from that
chat_id must reply in Indonesian (tmsg('login_new','id')).
"""
from __future__ import annotations

import os
import sys
import time
import uuid
import asyncio
import pytest
from pymongo import MongoClient

# Ensure /app/backend is importable so we can call confirm_login_link directly
sys.path.insert(0, "/app/backend")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://ton-auth-debug.preview.emergentagent.com").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


@pytest.fixture(scope="module")
def mongo_db():
    client = MongoClient(MONGO_URL)
    yield client[DB_NAME]
    client.close()


def _fresh_tg_id(seed_prefix: str = "91") -> int:
    # Ensures a numeric id unlikely to collide with any existing chat
    return int(seed_prefix + str(uuid.uuid4().int)[:7])


def _cleanup(db, tg_uid: int):
    db.telegram_mappings.delete_many({"chat_id": str(tg_uid)})
    db.users.delete_many({"telegram_chat_id": str(tg_uid)})
    db.users.delete_many({"telegram_user_id": str(tg_uid)})


class TestFix3aRetest:
    def test_fresh_tg_user_gets_english_reply_and_lang_en(self, mongo_db):
        """Directly call confirm_login_link with a fresh tg id and assert the
        returned reply message is ENGLISH login_new and the user's language is 'en'."""
        from motor.motor_asyncio import AsyncIOMotorClient
        from routes.telegram_login_link import confirm_login_link
        from routes.telegram_notifications import tmsg

        tg_uid = 91000001
        _cleanup(mongo_db, tg_uid)

        # Create a pending login-link jti directly in mongo (same as
        # /api/auth/telegram/login-link/start would).
        from datetime import datetime, timezone, timedelta
        jti = uuid.uuid4().hex
        mongo_db.tg_login_links.insert_one({
            "_id": jti,
            "status": "pending",
            "created_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=300),
            "token": None,
            "user_id": None,
        })

        async def _run():
            client = AsyncIOMotorClient(MONGO_URL)
            try:
                return await confirm_login_link(
                    client[DB_NAME],
                    payload=f"login_{jti}",
                    tg_user_id=str(tg_uid),
                    tg_username=f"qa_iter9_{tg_uid}",
                    tg_first_name="QA",
                    tg_last_name=None,
                )
            finally:
                client.close()

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(_run())
        finally:
            loop.close()

        assert result.get("ok") is True, f"confirm_login_link failed: {result}"
        expected_en = tmsg("login_new", "en")
        # Cross-check: message must equal ENGLISH login_new
        assert result["message"] == expected_en, (
            f"Expected English reply {expected_en!r}, got {result['message']!r}"
        )
        # And should NOT match the Russian variant
        try:
            ru_variant = tmsg("login_new", "ru")
            assert result["message"] != ru_variant, "Reply is still Russian!"
        except Exception:
            pass

        # And the newly-created users doc must have language='en'
        u = mongo_db.users.find_one({"telegram_user_id": str(tg_uid)})
        assert u is not None, "user doc was not created"
        assert u.get("language") == "en", f"expected language='en', got {u.get('language')!r}"
        assert u.get("registration_method") == "telegram"

        # cleanup
        mongo_db.tg_login_links.delete_one({"_id": jti})
        _cleanup(mongo_db, tg_uid)


class TestFix3bSpotCheck:
    def test_lang_id_mapping_then_login_replies_indonesian(self, mongo_db):
        """Simulate: user picks Indonesian via lang_id callback -> mapping
        row set with language='id'. Then confirm_login_link returns
        tmsg('login_new','id') for a fresh signup from that chat_id."""
        import requests
        from motor.motor_asyncio import AsyncIOMotorClient
        from routes.telegram_login_link import confirm_login_link
        from routes.telegram_notifications import tmsg

        tg_uid = 91000002
        _cleanup(mongo_db, tg_uid)

        # Post the lang_id callback via the real webhook. This is what the
        # bot does when the user taps the "Bahasa Indonesia" button.
        cb = requests.post(f"{BASE_URL}/api/telegram/webhook", json={
            "update_id": int(time.time()) + 900,
            "callback_query": {
                "id": str(uuid.uuid4()),
                "from": {"id": tg_uid, "is_bot": False, "first_name": "QA",
                         "username": f"qa_iter9b_{tg_uid}"},
                "message": {
                    "message_id": 1,
                    "chat": {"id": tg_uid, "type": "private"},
                    "date": int(time.time()),
                    "text": "menu",
                },
                "chat_instance": "0",
                "data": "lang_id",
            }
        }, timeout=15)
        assert cb.status_code == 200, cb.text
        # Give the async handler a moment to persist the mapping
        for _ in range(20):
            m = mongo_db.telegram_mappings.find_one({"chat_id": str(tg_uid)})
            if m and m.get("language") == "id":
                break
            time.sleep(0.4)
        m = mongo_db.telegram_mappings.find_one({"chat_id": str(tg_uid)})
        assert m and m.get("language") == "id", (
            f"telegram_mappings.language not set to 'id': {m!r}"
        )

        # Create pending login-link and confirm from this chat_id
        from datetime import datetime, timezone, timedelta
        jti = uuid.uuid4().hex
        mongo_db.tg_login_links.insert_one({
            "_id": jti,
            "status": "pending",
            "created_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=300),
            "token": None,
            "user_id": None,
        })

        async def _run():
            client = AsyncIOMotorClient(MONGO_URL)
            try:
                return await confirm_login_link(
                    client[DB_NAME],
                    payload=f"login_{jti}",
                    tg_user_id=str(tg_uid),
                    tg_username=f"qa_iter9b_{tg_uid}",
                    tg_first_name="QA",
                    tg_last_name=None,
                )
            finally:
                client.close()

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(_run())
        finally:
            loop.close()

        assert result.get("ok") is True, f"confirm_login_link failed: {result}"
        expected_id = tmsg("login_new", "id")
        assert result["message"] == expected_id, (
            f"Expected Indonesian reply {expected_id!r}, got {result['message']!r}"
        )
        # Extra sanity: contains at least one of the Indonesian markers per spec
        assert any(tok in result["message"] for tok in ("Akun dibuat", "Kembali ke browser", "Akun")), (
            f"Reply does not look Indonesian: {result['message']!r}"
        )

        # cleanup
        mongo_db.tg_login_links.delete_one({"_id": jti})
        mongo_db.telegram_mappings.delete_many({"chat_id": str(tg_uid)})
        _cleanup(mongo_db, tg_uid)


@pytest.fixture(scope="module", autouse=True)
def cleanup_after(mongo_db):
    yield
    # Final safety net
    for uid in (91000001, 91000002):
        _cleanup(mongo_db, uid)
    mongo_db.users.delete_many({
        "registration_method": "telegram",
        "$or": [
            {"tg_username": {"$regex": "^qa_iter9"}},
            {"telegram_username": {"$regex": "^qa_iter9"}},
        ],
    })
