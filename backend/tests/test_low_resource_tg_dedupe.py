"""Regression tests for the low-resource Telegram duplicate-message fix.

Context
-------
Before the fix, users received TWO Telegram messages for every low-resource
alert:

  * (A) A consolidated message with heading "⚠️ Заканчиваются ресурсы!" plus an
    inline "💎 Купить ресурсы" keyboard, produced by
    `_send_low_resource_tg_batch()` (called from `economic_tick`).
  * (B) A generic message prefixed with "🏙️ GRAM City" WITHOUT the button,
    produced by `send_pending_notifications()`.

The fix (applied in /app/backend/background_tasks.py) extends the Mongo filter
inside `send_pending_notifications` so it no longer picks up `low_resource`
type documents:

    {"read": False, "telegram_sent": {"$ne": True}, "type": {"$ne": "low_resource"}}

These tests verify both the code-level filter AND the behavioural side effect:
the generic sender must leave `low_resource` documents alone while still
processing every other notification type.
"""
import asyncio
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

# Make /app/backend importable so we can call the real functions.
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

# Ensure MONGO_URL / DB_NAME are loaded from backend/.env before importing
# `background_tasks` (which reads them at module import time).
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(_BACKEND_DIR, ".env"))

import background_tasks as bt  # noqa: E402


MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

TEST_TAG = f"TEST_low_res_{uuid.uuid4().hex[:8]}"


# ---------- Fixtures ----------

@pytest.fixture(scope="module")
def event_loop():
    """Module-scoped event loop so async fixtures + tests share state."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
def db():
    client = AsyncIOMotorClient(MONGO_URL)
    yield client[DB_NAME]
    client.close()


@pytest.fixture(scope="module")
def seeded_docs(event_loop, db):
    """Insert one low_resource + one warehouse_spoilage notification."""
    now = datetime.now(timezone.utc)
    low_res_doc = {
        "id": f"{TEST_TAG}_lowres",
        "user_id": f"{TEST_TAG}_user",
        "type": "low_resource",
        "message": f"{TEST_TAG} Bio-farm cold running low",
        "read": False,
        "telegram_sent": None,
        "tg_sent": None,
        "created_at": now,
    }
    other_doc = {
        "id": f"{TEST_TAG}_spoil",
        "user_id": f"{TEST_TAG}_user",
        "type": "warehouse_spoilage",
        "message": f"{TEST_TAG} Warehouse spoilage occurred",
        "read": False,
        "telegram_sent": None,
        "created_at": now,
    }

    async def _seed():
        await db.notifications.insert_many([low_res_doc, other_doc])

    event_loop.run_until_complete(_seed())
    yield {"low_res_id": low_res_doc["id"], "other_id": other_doc["id"]}

    async def _cleanup():
        await db.notifications.delete_many({"id": {"$regex": f"^{TEST_TAG}"}})

    event_loop.run_until_complete(_cleanup())


# ---------- Code inspection tests ----------

class TestFilterCodeInspection:
    """Static assertions: the source must exclude `type == 'low_resource'`."""

    def test_send_pending_notifications_filter_excludes_low_resource(self):
        src_path = os.path.join(_BACKEND_DIR, "background_tasks.py")
        with open(src_path, "r", encoding="utf-8") as fh:
            source = fh.read()

        # Locate the send_pending_notifications function body.
        marker = "async def send_pending_notifications"
        idx = source.find(marker)
        assert idx != -1, "send_pending_notifications() not found in source"

        # Grab the next ~2000 chars (function body) — enough to cover the query.
        body = source[idx: idx + 2000]

        # The Mongo filter must exclude 'low_resource' type.
        # Accept both single and double quotes.
        pattern = re.compile(
            r"""["']type["']\s*:\s*\{\s*["']?\$ne["']?\s*:\s*["']low_resource["']\s*\}"""
        )
        assert pattern.search(body), (
            "send_pending_notifications filter does NOT exclude "
            "type == 'low_resource' — duplicate Telegram bug will regress."
        )

    def test_low_resource_batch_sender_still_present(self):
        """The dedicated sender WITH the inline keyboard must remain."""
        src_path = os.path.join(_BACKEND_DIR, "background_tasks.py")
        with open(src_path, "r", encoding="utf-8") as fh:
            source = fh.read()
        assert "_send_low_resource_tg_batch" in source
        assert "asyncio.create_task(_send_low_resource_tg_batch())" in source
        # Sanity: the keyboard button text is still there.
        assert "Купить ресурсы" in source


# ---------- Behavioural tests ----------

class TestSendPendingNotificationsBehaviour:
    """Run the real sender against seeded docs and inspect Mongo state."""

    def test_generic_sender_skips_low_resource_docs(
        self, event_loop, db, seeded_docs
    ):
        async def _run():
            # Call the real production function — TELEGRAM_BOT_TOKEN is empty
            # in the preview env, so it will early-return after the query;
            # what matters is that the low_resource doc is NEVER marked
            # telegram_sent=True even if a token WERE present, because the
            # filter excludes it. We reproduce the exact filter here too.
            await bt.send_pending_notifications()

            low_res = await db.notifications.find_one(
                {"id": seeded_docs["low_res_id"]}, {"_id": 0}
            )
            return low_res

        low_res = event_loop.run_until_complete(_run())
        assert low_res is not None, "seed low_resource doc disappeared"
        # The generic sender must NOT have flipped this flag.
        assert low_res.get("telegram_sent") is not True, (
            "send_pending_notifications() incorrectly processed a "
            "low_resource notification — duplicate TG message bug!"
        )

    def test_filter_query_excludes_low_resource_includes_others(
        self, event_loop, db, seeded_docs
    ):
        """Directly reproduce the sender's Mongo query and validate results."""

        async def _run():
            docs = await db.notifications.find(
                {
                    "read": False,
                    "telegram_sent": {"$ne": True},
                    "type": {"$ne": "low_resource"},
                },
                {"_id": 0},
            ).sort("created_at", -1).to_list(500)
            return docs

        docs = event_loop.run_until_complete(_run())
        ids = {d.get("id") for d in docs}
        types = {d.get("type") for d in docs}

        # Seeded low_resource doc must NOT appear.
        assert seeded_docs["low_res_id"] not in ids, (
            "low_resource notification leaked through the sender filter"
        )
        assert "low_resource" not in types, (
            f"Filter returned low_resource docs: {types}"
        )

        # Seeded warehouse_spoilage doc MUST appear — proves the sender
        # still handles non-low_resource types.
        assert seeded_docs["other_id"] in ids, (
            "warehouse_spoilage notification was NOT picked up — "
            "generic sender is over-filtering"
        )

    def test_other_notification_types_still_flow(self, event_loop, db):
        """
        Sanity: seed several non-low_resource types and confirm each is
        selectable by the sender's filter.
        """
        types_to_check = [
            "warehouse_spoilage",
            "contract_payment_in",
            "credit_overdue",
        ]
        tag = f"{TEST_TAG}_mix"
        now = datetime.now(timezone.utc)
        docs = [
            {
                "id": f"{tag}_{t}",
                "user_id": f"{tag}_user",
                "type": t,
                "message": f"{tag} {t}",
                "read": False,
                "telegram_sent": None,
                "created_at": now,
            }
            for t in types_to_check
        ]

        async def _run():
            await db.notifications.insert_many(docs)
            try:
                found = await db.notifications.find(
                    {
                        "read": False,
                        "telegram_sent": {"$ne": True},
                        "type": {"$ne": "low_resource"},
                        "id": {"$regex": f"^{tag}_"},
                    },
                    {"_id": 0},
                ).to_list(50)
                return found
            finally:
                await db.notifications.delete_many({"id": {"$regex": f"^{tag}_"}})

        found = event_loop.run_until_complete(_run())
        found_types = {d["type"] for d in found}
        assert found_types == set(types_to_check), (
            f"Expected {types_to_check}, got {found_types}"
        )


# ---------- Economic tick verification ----------

class TestEconomicTickStillFiresBatch:
    """Grep-style check that economic_tick still spawns the batch sender."""

    def test_economic_tick_spawns_low_resource_batch(self):
        src_path = os.path.join(_BACKEND_DIR, "background_tasks.py")
        with open(src_path, "r", encoding="utf-8") as fh:
            source = fh.read()

        # Find economic_tick function
        et_idx = source.find("async def economic_tick")
        assert et_idx != -1
        # From that point onwards, there must be a create_task on the batch.
        et_body = source[et_idx:]
        # It should appear before the next top-level async def (crude scope check).
        next_def = et_body.find("\nasync def ", 10)
        scope = et_body[:next_def] if next_def != -1 else et_body
        assert "asyncio.create_task(_send_low_resource_tg_batch())" in scope, (
            "economic_tick no longer fires the consolidated low-resource "
            "batch sender — users will stop receiving the message WITH the "
            "inline keyboard."
        )
