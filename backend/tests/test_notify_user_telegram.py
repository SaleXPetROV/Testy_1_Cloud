"""notify_user → Telegram: sent through the live bot; without a bot instance → the direct Bot API sender;
users who turned Telegram notifications off (or have no chat) get nothing."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))


class _Coll:
    async def find_one(self, *a, **k):
        return None

    async def insert_one(self, *a, **k):
        return None


class _DB:
    def __getattr__(self, _name):
        return _Coll()


class _Bot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, parse_mode="HTML", reply_markup=None, **kw):
        self.sent.append((chat_id, text))
        return True


def _run(monkeypatch, user, bot):
    import telegram_bot as tg_mod
    import telegram_notifications as tn
    from core import notify
    direct = []

    async def _direct(chat_id, text, parse_mode="HTML", reply_markup=None, preview_url=None):
        direct.append((chat_id, text))
        return True

    monkeypatch.setattr(tg_mod, "telegram_bot", bot)
    monkeypatch.setattr(tn, "send_telegram_message", _direct)
    asyncio.run(notify.notify_user(_DB(), user, title="Title", message="Body <b>x</b>", in_app=False, pretranslated=True))
    return direct


def test_sent_via_bot(monkeypatch):
    bot = _Bot()
    direct = _run(monkeypatch, {"id": "u1", "telegram_chat_id": "42", "language": "ru"}, bot)
    assert bot.sent and bot.sent[0][0] == "42" and "<b>Title</b>" in bot.sent[0][1] and "<b>x</b>" in bot.sent[0][1]
    assert direct == []


def test_fallback_without_bot_instance(monkeypatch):
    direct = _run(monkeypatch, {"id": "u1", "telegram_chat_id": "42", "language": "en"}, None)
    assert len(direct) == 1 and direct[0][0] == "42"


def test_opted_out_or_no_chat(monkeypatch):
    bot = _Bot()
    assert _run(monkeypatch, {"id": "u1", "telegram_chat_id": "42", "telegram_notifications": False}, bot) == []
    assert _run(monkeypatch, {"id": "u2", "telegram_chat_id": None}, bot) == []
    assert bot.sent == []
