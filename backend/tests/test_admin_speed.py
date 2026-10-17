"""Admin actions must not wait for slow notification delivery.

Regression tests for: approving withdrawals / buying out lots in the admin
panel took minutes because every action awaited Telegram (and WebSocket)
delivery inline.

    cd backend && python -m pytest tests/test_admin_speed.py -q
"""
import asyncio
import time

import pytest

mongomock_motor = pytest.importorskip("mongomock_motor")

from core import notify as notify_mod  # noqa: E402
from core.websocket import ConnectionManager  # noqa: E402


class _StuckSocket:
    """A client socket whose send never completes (half-dead connection)."""
    async def send_json(self, _msg):
        await asyncio.sleep(3600)


class _FastSocket:
    def __init__(self):
        self.got = []

    async def send_json(self, msg):
        self.got.append(msg)


def test_send_personal_does_not_hang_on_stuck_socket():
    async def go():
        m = ConnectionManager()
        m.SEND_TIMEOUT_S = 0.2
        m.active_connections["u1"] = _StuckSocket()
        t = time.monotonic()
        await m.send_personal({"type": "x"}, "u1")
        assert time.monotonic() - t < 1.0
        assert "u1" not in m.active_connections      # dead socket dropped
    asyncio.run(go())


def test_broadcast_is_parallel_and_skips_stuck_clients():
    async def go():
        m = ConnectionManager()
        m.SEND_TIMEOUT_S = 0.2
        fast = _FastSocket()
        m.active_connections.update({"a": _StuckSocket(), "b": _StuckSocket(), "c": fast})
        t = time.monotonic()
        await m.broadcast({"type": "x"})
        assert time.monotonic() - t < 0.6               # not 0.2 s per stuck client in a row
        assert fast.got == [{"type": "x"}]
        assert set(m.active_connections) == {"c"}
    asyncio.run(go())


def test_notify_user_background_returns_immediately(monkeypatch):
    async def go():
        done = asyncio.Event()

        async def slow_notify(db, user, *a, **kw):
            await asyncio.sleep(0.5)
            done.set()
        monkeypatch.setattr(notify_mod, "notify_user", slow_notify)
        t = time.monotonic()
        notify_mod.notify_user_background(None, "u1", title="t", message="m")
        assert time.monotonic() - t < 0.05             # caller is not blocked
        await asyncio.wait_for(done.wait(), timeout=2)  # but delivery still happens
    asyncio.run(go())


def test_notify_user_background_swallows_errors_and_timeouts(monkeypatch):
    async def go():
        async def boom(*a, **kw):
            raise RuntimeError("telegram down")

        async def forever(*a, **kw):
            await asyncio.sleep(3600)
        async def run_one(fn, **kw):
            monkeypatch.setattr(notify_mod, "notify_user", fn)
            before = set(notify_mod._BG_TASKS)
            notify_mod.notify_user_background(None, "u1", title="t", message="m", **kw)
            mine = set(notify_mod._BG_TASKS) - before
            assert len(mine) == 1
            return await asyncio.wait_for(asyncio.gather(*mine, return_exceptions=True), timeout=2)

        assert await run_one(boom) == [None]                    # error swallowed
        assert await run_one(forever, timeout=0.1) == [None]    # timeout swallowed
    asyncio.run(go())


def test_slow_telegram_is_not_waited_twice(monkeypatch):
    """When the bot already gave up (timeout), the legacy sender must not try
    the same slow Telegram API again."""
    async def go():
        monkeypatch.delenv("LIBRETRANSLATE_URL", raising=False)
        monkeypatch.delenv("EMERGENT_LLM_KEY", raising=False)
        db = mongomock_motor.AsyncMongoMockClient()["speed"]
        await db.users.insert_one({"id": "u1", "language": "ru", "telegram_chat_id": "111"})

        class _Bot:
            calls = 0

            async def send_message(self, *a, **kw):
                _Bot.calls += 1
                return False                              # e.g. timed out after its retry
        legacy_calls = []

        async def legacy(*a, **kw):
            legacy_calls.append(a)
            return True
        import telegram_bot
        import telegram_notifications
        monkeypatch.setattr(telegram_bot, "get_telegram_bot", lambda: _Bot())
        monkeypatch.setattr(telegram_notifications, "send_telegram_message", legacy)
        await notify_mod.notify_user(db, "u1", title="Привет", message="Тест")
        assert _Bot.calls == 1
        assert legacy_calls == []
        assert await db.notifications.count_documents({"user_id": "u1"}) == 1
    asyncio.run(go())
