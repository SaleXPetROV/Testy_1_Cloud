"""Admin broadcast → Telegram delivery.

1) the bot instance is missing in the API process (startup init failed / token saved later) →
   `_publish_announcement` re-initialises it instead of silently skipping Telegram;
2) several accounts linked to the same Telegram chat → exactly one message per chat;
3) delivery stats: telegram_total = real recipients, sent counted.
"""
import asyncio
import os
import sys
import uuid

_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
sys.path.insert(0, _BACKEND_DIR)


class _FakeBot:
    last_failure: dict = {}

    def __init__(self):
        self.calls = []

    async def send_message(self, chat_id, text, parse_mode="HTML", reply_markup=None, **kw):
        self.calls.append(("msg", str(chat_id), text))
        return True

    async def send_photo(self, chat_id, photo_url, caption="", parse_mode="HTML", reply_markup=None, **kw):
        self.calls.append(("photo", str(chat_id), caption))
        return True


class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def batch_size(self, _n):
        return self

    def __aiter__(self):
        self._it = iter(self._docs)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


async def _run():
    from dotenv import load_dotenv
    from motor.motor_asyncio import AsyncIOMotorClient
    load_dotenv(os.path.join(_BACKEND_DIR, ".env"))
    import telegram_bot as tg_mod
    import server as srv

    tag = uuid.uuid4().hex[:8]
    users = [
        {"id": f"tgt-{tag}-1", "telegram_chat_id": "7001", "language": "en"},
        {"id": f"tgt-{tag}-2", "telegram_chat_id": "7001", "language": "en"},   # same Telegram as user 1
        {"id": f"tgt-{tag}-3", "telegram_chat_id": 7002, "language": "ru"},
        {"id": f"tgt-{tag}-4", "telegram_chat_id": None, "language": "en"},
    ]
    fake = _FakeBot()
    orig_bot, orig_init, orig_db = tg_mod.telegram_bot, tg_mod.init_telegram_bot, srv.db
    orig_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    srv.db = client[os.environ["DB_NAME"]]

    async def _fake_init(_db):
        tg_mod.telegram_bot = fake
        return fake

    try:
        tg_mod.telegram_bot = None                      # bot missing in this process
        tg_mod.init_telegram_bot = _fake_init
        os.environ["TELEGRAM_BOT_TOKEN"] = "123:test"
        await srv.db.users.insert_many([dict(u) for u in users])   # real rows (motor collections can't be patched)
        ann_id = f"ann-{tag}"
        await srv.db.announcements.insert_one({"id": ann_id, "title": f"Hello {tag}"})
        await srv._publish_announcement({"id": ann_id, "title": f"Hello {tag}", "message": "World"})
        doc = await srv.db.announcements.find_one({"id": ann_id}) or {}
        return fake, doc.get("delivery") or {}
    finally:
        await srv.db.users.delete_many({"id": {"$in": [u["id"] for u in users]}})
        # the broadcast reaches every account of the test database: remove all its notifications
        await srv.db.notifications.delete_many({"title": f"Hello {tag}"})
        await srv.db.announcements.delete_many({"id": f"ann-{tag}"})
        tg_mod.telegram_bot, tg_mod.init_telegram_bot = orig_bot, orig_init
        srv.db = orig_db
        if orig_token is None:
            os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        else:
            os.environ["TELEGRAM_BOT_TOKEN"] = orig_token


def test_broadcast_reinits_bot_and_dedupes_chats():
    fake, delivery = asyncio.run(_run())
    chats = [c for (_k, c, _t) in fake.calls]
    assert chats.count("7001") == 1 and chats.count("7002") == 1, fake.calls   # one per chat, bot re-initialised
    assert all("Hello" in t for (_k, _c, t) in fake.calls)
    assert delivery.get("telegram_total") == len(set(chats)) >= 2
    assert delivery.get("sent") == len(chats)
    assert delivery.get("in_app") >= 4
    assert delivery.get("status") == "done"
