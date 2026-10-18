"""Withdrawal approval in the Telegram bot requires the admin's TOTP code when 2FA is on."""
import asyncio
import pytest
mongomock_motor = pytest.importorskip("mongomock_motor")
pyotp = pytest.importorskip("pyotp")
import telegram_bot as tb
from security.totp_crypto import encrypt_secret


class Bot(tb.TelegramBot):
    def __init__(self, db):                       # no network: record what the bot would do
        self.db = db; self.sent = []; self.deleted = []; self.approved = []; self.answers = []
    async def send_message(self, chat_id, text, *a, **k): self.sent.append(text); return True
    async def delete_message(self, chat_id, message_id): self.deleted.append(message_id); return True
    async def answer_callback(self, callback_id, text, show_alert=False):
        if callback_id: self.answers.append(text)
    async def edit_message(self, *a, **k): return True
    async def approve_withdrawal_internal(self, tx):
        self.approved.append(tx["id"]); await self.db.transactions.update_one({"id": tx["id"]}, {"$set": {"status": "completed"}})
        return {"success": True, "tx_hash": "h"}


def world(with_2fa=True):
    db = mongomock_motor.AsyncMongoMockClient()["b2fa"]
    secret = pyotp.random_base32()
    async def seed():
        await db.users.insert_one({"id": "adm", "is_admin": True, "telegram_chat_id": "777", "username": "boss",
                                   **({"is_2fa_enabled": True, "two_factor_secret": encrypt_secret(secret)} if with_2fa else {})})
        await db.transactions.insert_one({"id": "w1", "status": "pending", "net_amount": 3.5, "user_username": "alice"})
    asyncio.run(seed())
    return db, secret


def test_code_required_wrong_codes_then_right_code():
    db, secret = world()
    bot = Bot(db)
    async def go():
        adm = await bot._admin_2fa_account("777")
        await bot._ask_withdrawal_2fa("cb1", "777", 55, "w1", adm)
        assert bot.approved == [] and "6-значный код" in bot.sent[-1]             # asked, not approved
        assert await bot.process_withdrawal_action("cb2", "777", 55, "w1", "approve") == {"ok": True}
        assert bot.approved == []                                                  # bypass blocked
        assert await bot._maybe_handle_withdrawal_2fa("777", "000000", {"message_id": 91})
        assert bot.approved == [] and "Осталось попыток: 2" in bot.sent[-1] and 91 in bot.deleted
        good = pyotp.TOTP(secret).now()
        assert await bot._maybe_handle_withdrawal_2fa("777", good, {"message_id": 92})
        assert bot.approved == ["w1"] and await db.bot_2fa_pending.count_documents({}) == 0
        assert await db.admin_logs.count_documents({"action": "withdrawal_2fa_ok"}) == 1
    asyncio.run(go())


def test_three_wrong_codes_cancel():
    db, _ = world()
    bot = Bot(db)
    async def go():
        await bot._ask_withdrawal_2fa("cb", "777", 1, "w1", await bot._admin_2fa_account("777"))
        for _ in range(3):
            await bot._maybe_handle_withdrawal_2fa("777", "123456", {"message_id": 5})
        assert "Попытки закончились" in bot.sent[-1] and await db.bot_2fa_pending.count_documents({}) == 0
        assert bot.approved == [] and (await db.transactions.find_one({"id": "w1"}))["status"] == "pending"
        assert not await bot._maybe_handle_withdrawal_2fa("777", "123456", {})    # nothing pending any more
    asyncio.run(go())


def test_admin_without_2fa_approves_as_before():
    db, _ = world(with_2fa=False)
    bot = Bot(db)
    async def go():
        assert await bot._admin_2fa_account("777") is None
        await bot.process_withdrawal_action("cb", "777", 1, "w1", "approve")
        assert bot.approved == ["w1"]
    asyncio.run(go())
