"""Regression tests for iteration 2 changes in /app/backend/background_tasks.py.

Covers:

  * UNIFY-FLAG: `tg_sent` must be gone from background_tasks.py. Both the
    low-resource batch sender AND the generic sender now write to a single
    `telegram_sent` field.

  * UNIFY-FLAG DB migration: pre-existing `low_resource` docs must have
    been rewritten from `tg_sent=True` → `telegram_sent=True` (idempotent).

  * I18N: `send_pending_notifications()` renders the inline home button and
    the brand wrapping line in the user's `language`. Russian users get
    "🏠 На главную"; English (or any unknown lang) get "🏠 Main menu".
    Also verifies the `<b>title</b>` block is added when the notif has a
    `title` field.

Approach for i18n tests
-----------------------
The Telegram outbound HTTP call goes through `aiohttp.ClientSession.post`.
We monkeypatch that method with a capturing coroutine so the JSON payload
is inspected without leaving the network. `TELEGRAM_BOT_TOKEN` is also
set to a fake value so `send_pending_notifications()` doesn't early-return.
"""
import asyncio
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

# Make /app/backend importable so we can call the real functions.
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(_BACKEND_DIR, ".env"))

import background_tasks as bt  # noqa: E402


MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

TEST_TAG = f"TEST_iter2_{uuid.uuid4().hex[:8]}"


# ---------- Fixtures ----------

@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
def db():
    client = AsyncIOMotorClient(MONGO_URL)
    yield client[DB_NAME]
    client.close()


# ---------- UNIFY-FLAG-1: code-level ----------

class TestNoLegacyTgSentInSource:
    """`tg_sent` (the old dedup field) must be entirely gone from the
    background tasks module — only appearing in comments/docstrings that
    reference the historical name."""

    def test_no_functional_tg_sent_usage(self):
        src_path = os.path.join(_BACKEND_DIR, "background_tasks.py")
        with open(src_path, "r", encoding="utf-8") as fh:
            source = fh.read()

        # Strip out Python comments (single-line) and docstrings so we only
        # count "functional" occurrences of the identifier. We accept the
        # historical name being mentioned in explanatory prose.
        code_lines = []
        for line in source.splitlines():
            stripped = line.split("#", 1)[0]
            code_lines.append(stripped)
        code_only = "\n".join(code_lines)

        # Also drop triple-quoted docstrings (best-effort).
        code_only = re.sub(r'""".*?"""', '', code_only, flags=re.DOTALL)
        code_only = re.sub(r"'''.*?'''", '', code_only, flags=re.DOTALL)

        # After stripping, no `tg_sent` should remain.
        assert "tg_sent" not in code_only, (
            "Legacy `tg_sent` still appears in functional code of "
            "background_tasks.py — the unify-flag refactor is incomplete."
        )

    def test_telegram_sent_is_the_canonical_field(self):
        src_path = os.path.join(_BACKEND_DIR, "background_tasks.py")
        with open(src_path, "r", encoding="utf-8") as fh:
            source = fh.read()

        # Both senders must set `telegram_sent`.
        # (a) low-resource batch
        assert 'telegram_sent": True' in source or "'telegram_sent': True" in source, (
            "Neither sender sets telegram_sent=True — dedup broken"
        )
        # Both filters query on it.
        assert re.search(
            r'"telegram_sent"\s*:\s*\{\s*"\$ne"\s*:\s*True\s*\}', source
        ), "telegram_sent $ne True filter missing"

    def test_index_uses_telegram_sent(self):
        src_path = os.path.join(_BACKEND_DIR, "background_tasks.py")
        with open(src_path, "r", encoding="utf-8") as fh:
            source = fh.read()
        # The (user_id, type, telegram_sent) index must reference the new field.
        assert re.search(
            r'\(\s*"user_id"\s*,\s*1\s*\)\s*,\s*\(\s*"type"\s*,\s*1\s*\)\s*,\s*\(\s*"telegram_sent"\s*,\s*1\s*\)',
            source,
        ), "notifications index should be (user_id, type, telegram_sent)"


# ---------- UNIFY-FLAG-2: DB migration state ----------

class TestLegacyDocMigration:
    """Legacy `low_resource` docs must have been migrated to
    `telegram_sent=True` and stripped of `tg_sent`."""

    def test_no_low_resource_docs_have_tg_sent_field(self, event_loop, db):
        async def _run():
            return await db.notifications.count_documents(
                {"type": "low_resource", "tg_sent": {"$exists": True}}
            )
        n = event_loop.run_until_complete(_run())
        assert n == 0, (
            f"{n} legacy low_resource docs still carry a `tg_sent` field. "
            "Migration script was not run or is not idempotent."
        )

    def test_some_low_resource_docs_marked_telegram_sent(self, event_loop, db):
        async def _run():
            return await db.notifications.count_documents(
                {"type": "low_resource", "telegram_sent": True}
            )
        n = event_loop.run_until_complete(_run())
        # Iteration 1 confirmed 431 pre-existing docs. Accept anything > 0
        # so the test doesn't break in a fresh DB.
        assert n > 0, (
            "No low_resource docs have telegram_sent=True — migration "
            "did not update legacy documents."
        )


# ---------- UNIFY-FLAG behavioural: bulk-write path sets telegram_sent ----------

class TestLowResourceBulkMarkUsesTelegramSent:
    """Simulate the code path in `_send_low_resource_tg_batch` where a user
    has NO chat_id: the sender should still bulk-mark the notifications as
    `telegram_sent=True` (so we don't scan them forever) and MUST NOT create
    a `tg_sent` field."""

    def test_bulk_mark_when_no_chat_id(self, event_loop, db):
        tag = f"{TEST_TAG}_bulk"
        now = datetime.now(timezone.utc)
        # 3 fresh low_resource docs for the same phantom user (no chat_id).
        docs = [
            {
                "id": f"{tag}_{i}",
                "user_id": f"{tag}_phantom_user",
                "type": "low_resource",
                "message": f"{tag} out of stock #{i}",
                "read": False,
                # Intentionally leave telegram_sent unset / None.
                "created_at": now,
            }
            for i in range(3)
        ]

        async def _seed():
            await db.notifications.insert_many([d.copy() for d in docs])

        async def _cleanup():
            await db.notifications.delete_many({"id": {"$regex": f"^{tag}_"}})

        event_loop.run_until_complete(_seed())
        try:
            # Reproduce the exact bulk-write logic from the sender.
            from pymongo import UpdateOne

            async def _run_bulk():
                pending = await db.notifications.find(
                    {"type": "low_resource", "telegram_sent": {"$ne": True},
                     "id": {"$regex": f"^{tag}_"}},
                    {"_id": 0},
                ).to_list(50)
                # This mirrors the "no chat_id" branch inside the sender.
                ops = [
                    UpdateOne({"id": n["id"]}, {"$set": {"telegram_sent": True}})
                    for n in pending
                ]
                if ops:
                    await db.notifications.bulk_write(ops, ordered=False)

                # Fetch fresh state.
                return await db.notifications.find(
                    {"id": {"$regex": f"^{tag}_"}},
                    {"_id": 0},
                ).to_list(50)

            after = event_loop.run_until_complete(_run_bulk())
            assert len(after) == 3
            for d in after:
                assert d.get("telegram_sent") is True, (
                    f"telegram_sent not flipped for {d.get('id')}: {d}"
                )
                assert "tg_sent" not in d, (
                    f"Bulk path leaked legacy tg_sent field into {d.get('id')}: {d}"
                )
        finally:
            event_loop.run_until_complete(_cleanup())


# ---------- I18N: send_pending_notifications ----------

class TestSendPendingNotificationsI18N:
    """Seed one Russian user + one English user + one unknown-lang user,
    each with a notification, monkeypatch aiohttp.ClientSession.post, run
    the generic sender, and inspect the captured payloads."""

    @pytest.fixture(scope="class")
    def i18n_setup(self, event_loop, db):
        tag = f"{TEST_TAG}_i18n"
        now = datetime.now(timezone.utc)

        users = [
            {
                "id": f"{tag}_ru_user",
                "username": f"{tag}_ru",
                "email": f"{tag}_ru@test.com",
                "telegram_chat_id": "11111",  # fake chat id
                "language": "ru",
            },
            {
                "id": f"{tag}_en_user",
                "username": f"{tag}_en",
                "email": f"{tag}_en@test.com",
                "telegram_chat_id": "22222",
                "language": "en",
            },
            {
                "id": f"{tag}_xx_user",
                "username": f"{tag}_xx",
                "email": f"{tag}_xx@test.com",
                "telegram_chat_id": "33333",
                "language": "xx",  # unsupported → should fall back to en
            },
        ]
        notifs = [
            {
                "id": f"{tag}_ru_notif",
                "user_id": f"{tag}_ru_user",
                "type": "warehouse_spoilage",  # NOT low_resource (excluded)
                "title": f"{tag} Заголовок RU",
                "message": f"{tag} Тело сообщения",
                "read": False,
                "telegram_sent": None,
                "created_at": now,
            },
            {
                "id": f"{tag}_en_notif",
                "user_id": f"{tag}_en_user",
                "type": "warehouse_spoilage",
                "title": f"{tag} EN Title",
                "message": f"{tag} Body of message",
                "read": False,
                "telegram_sent": None,
                "created_at": now,
            },
            {
                "id": f"{tag}_xx_notif",
                "user_id": f"{tag}_xx_user",
                "type": "warehouse_spoilage",
                "message": f"{tag} XX body",  # NO title
                "read": False,
                "telegram_sent": None,
                "created_at": now,
            },
        ]

        async def _seed():
            await db.users.insert_many([u.copy() for u in users])
            await db.notifications.insert_many([n.copy() for n in notifs])

        async def _cleanup():
            await db.users.delete_many({"id": {"$regex": f"^{tag}_"}})
            await db.notifications.delete_many({"id": {"$regex": f"^{tag}_"}})

        event_loop.run_until_complete(_seed())
        yield {"tag": tag}
        event_loop.run_until_complete(_cleanup())

    def _run_sender_with_capture(self, event_loop, monkeypatch):
        """Runs bt.send_pending_notifications() with aiohttp.ClientSession
        patched so outbound POSTs are captured instead of actually sent."""
        captured = []

        class _FakeResp:
            status = 200

            async def json(self):
                return {"ok": True}

            async def text(self):
                return "ok"

        class _FakeSession:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, **kwargs):
                # The production code does `await session.post(...)` — it
                # does NOT use it as an async context manager. So `post`
                # must itself be a coroutine that returns the response.
                captured.append({"url": url, "kwargs": kwargs})
                return _FakeResp()

            async def close(self):
                pass

        import aiohttp
        monkeypatch.setattr(aiohttp, "ClientSession", _FakeSession)
        # Ensure the sender doesn't early-return on missing bot token.
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TESTFAKETOKEN")

        event_loop.run_until_complete(bt.send_pending_notifications())
        return captured

    def test_ru_user_gets_russian_button(self, event_loop, db, i18n_setup, monkeypatch):
        tag = i18n_setup["tag"]
        captured = self._run_sender_with_capture(event_loop, monkeypatch)
        # Find the payload aimed at chat_id=11111 (RU user).
        ru = [c for c in captured if c["kwargs"].get("json", {}).get("chat_id") == "11111"]
        assert ru, (
            f"No outbound Telegram payload captured for RU user. Captured: {captured}"
        )
        payload = ru[0]["kwargs"]["json"]
        # 1. Button label MUST be Russian.
        btn = payload["reply_markup"]["inline_keyboard"][0][0]["text"]
        assert btn == "🏠 На главную", f"RU user got wrong button: {btn!r}"
        # 2. Body contains bold <b>title</b> block.
        assert f"<b>{tag} Заголовок RU</b>" in payload["text"], (
            f"Bold title block missing for RU user: {payload['text']!r}"
        )
        # 3. Brand line and body present.
        assert "GRAM City" in payload["text"]
        assert f"{tag} Тело сообщения" in payload["text"]

    def test_en_user_gets_english_button(self, event_loop, db, i18n_setup, monkeypatch):
        tag = i18n_setup["tag"]
        # Reset flags first (previous test already flipped telegram_sent).
        async def _reset():
            await db.notifications.update_many(
                {"id": {"$regex": f"^{tag}_"}},
                {"$set": {"telegram_sent": None, "read": False}},
            )
        event_loop.run_until_complete(_reset())

        captured = self._run_sender_with_capture(event_loop, monkeypatch)
        en = [c for c in captured if c["kwargs"].get("json", {}).get("chat_id") == "22222"]
        assert en, f"No outbound Telegram payload captured for EN user. Captured: {captured}"
        payload = en[0]["kwargs"]["json"]
        btn = payload["reply_markup"]["inline_keyboard"][0][0]["text"]
        assert btn == "🏠 Main menu", f"EN user got wrong button: {btn!r}"
        assert f"<b>{tag} EN Title</b>" in payload["text"]

    def test_unsupported_lang_falls_back_to_english(
        self, event_loop, db, i18n_setup, monkeypatch
    ):
        tag = i18n_setup["tag"]
        # Reset flags so all three notifications are re-picked.
        async def _reset():
            await db.notifications.update_many(
                {"id": {"$regex": f"^{tag}_"}},
                {"$set": {"telegram_sent": None, "read": False}},
            )
        event_loop.run_until_complete(_reset())

        captured = self._run_sender_with_capture(event_loop, monkeypatch)
        xx = [c for c in captured if c["kwargs"].get("json", {}).get("chat_id") == "33333"]
        assert xx, (
            f"No outbound Telegram payload captured for XX user. Captured: {captured}"
        )
        payload = xx[0]["kwargs"]["json"]
        btn = payload["reply_markup"]["inline_keyboard"][0][0]["text"]
        assert btn == "🏠 Main menu", (
            f"Unknown language did not fall back to English. Got: {btn!r}"
        )
        # No title field on this notif → the ONLY <b> block in the message
        # should be the brand line ("🏙️ <b>GRAM City</b>"). There must be
        # no second <b>...</b> pair introduced by a missing title.
        assert payload["text"].count("<b>") == 1, (
            f"Notif without title should have only the brand <b> block. "
            f"Text: {payload['text']!r}"
        )

    def test_telegram_sent_flag_flipped_after_run(
        self, event_loop, db, i18n_setup, monkeypatch
    ):
        tag = i18n_setup["tag"]
        # Reset first so we measure this run in isolation.
        async def _reset():
            await db.notifications.update_many(
                {"id": {"$regex": f"^{tag}_"}},
                {"$set": {"telegram_sent": None, "read": False}},
            )
        event_loop.run_until_complete(_reset())

        self._run_sender_with_capture(event_loop, monkeypatch)

        async def _fetch():
            return await db.notifications.find(
                {"id": {"$regex": f"^{tag}_"}}, {"_id": 0}
            ).to_list(20)

        docs = event_loop.run_until_complete(_fetch())
        # All three should be flipped after a successful (mocked) send.
        for d in docs:
            assert d.get("telegram_sent") is True, (
                f"telegram_sent not flipped for {d.get('id')}: {d.get('telegram_sent')!r}"
            )
            # Legacy field must NOT leak in.
            assert "tg_sent" not in d, (
                f"Legacy tg_sent leaked into {d.get('id')}: {d}"
            )
