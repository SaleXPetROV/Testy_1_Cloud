"""Incoming deposits (payment_monitor.py): never lost, never credited twice.

    cd backend && python -m pytest tests/test_payment_deposits.py -q
"""
import asyncio
import time

import pytest

mongomock_motor = pytest.importorskip("mongomock_motor")
from payment_monitor import TONPaymentMonitor  # noqa: E402


async def _mon():
    db = mongomock_motor.AsyncMongoMockClient()["dep"]
    await db.users.insert_one({"id": "u1", "wallet_address": "EQplayer", "balance_ton": 0.0})
    mon = TONPaymentMonitor(db)

    async def noop(*a, **k):
        return None
    mon.distribute_deposit_to_wallets = noop
    await mon.ensure_indexes()
    return db, mon


def tx(h, ton, ago):
    return {"hash": h, "sender": "EQplayer", "amount": int(ton * 1_000_000_000), "utime": int(time.time()) - ago}


def test_two_deposits_in_one_poll_are_both_credited():
    """Regression: toncenter lists newest first; the older deposit used to be dropped."""
    async def go():
        db, mon = await _mon()
        await mon.process_incoming_payment(tx("tx-new", 2.0, 5))
        await mon.process_incoming_payment(tx("tx-old", 1.0, 8))
        u = await db.users.find_one({"id": "u1"})
        assert abs(u["balance_ton"] - 3.0) < 1e-9
        assert await db.deposits.count_documents({"status": "completed"}) == 2
    asyncio.run(go())


def test_same_transaction_is_never_credited_twice():
    async def go():
        db, mon = await _mon()
        for _ in range(3):
            await mon.process_incoming_payment(tx("tx-1", 1.5, 5))
        u = await db.users.find_one({"id": "u1"})
        assert abs(u["balance_ton"] - 1.5) < 1e-9
        assert await db.deposits.count_documents({"tx_hash": "tx-1"}) == 1
    asyncio.run(go())


def test_parallel_processing_credits_once():
    async def go():
        db, mon = await _mon()
        await asyncio.gather(*[mon.process_incoming_payment(tx("tx-p", 1.0, 5)) for _ in range(5)])
        u = await db.users.find_one({"id": "u1"})
        assert abs(u["balance_ton"] - 1.0) < 1e-9
    asyncio.run(go())
