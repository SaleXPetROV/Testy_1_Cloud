"""Payments reconciliation (backend/reconciliation.py).

    cd backend && python -m pytest tests/test_reconciliation.py -q
"""
import asyncio
import types
from datetime import datetime, timedelta, timezone

import pytest

mongomock_motor = pytest.importorskip("mongomock_motor")
import reconciliation as rc  # noqa: E402

ADMIN = types.SimpleNamespace(id="adm", username="admin")


def old(minutes=60):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


async def _db(monkeypatch, onchain=10.0):
    db = mongomock_motor.AsyncMongoMockClient()["rc"]
    await db.users.insert_many([{"id": "u1", "balance_ton": 3.0, "bonus_balance": 0.5},
                                {"id": "u2", "balance_ton": 2.0}])
    await db.transactions.insert_one({"id": "w1", "tx_type": "withdrawal", "status": "pending", "amount_ton": 1.0})
    await db.admin_settings.insert_one({"type": "reconciliation", "wallets": ["EQ" + "a" * 46]})

    async def fake_balance(addr):
        return onchain
    monkeypatch.setattr(rc, "onchain_balance", fake_balance)
    return db


def test_coverage_is_assets_minus_liabilities(monkeypatch):
    async def go():
        db = await _db(monkeypatch, onchain=10.0)
        r = await rc.report(db)
        assert r["liabilities"]["total_ton"] == 6.0                    # 3 + 2 + 1 pending
        assert r["coverage_ton"] == 4.0
        assert not [a for a in r["alerts"] if a["level"] == "critical"]
    asyncio.run(go())


def test_alert_when_not_enough_ton(monkeypatch):
    async def go():
        db = await _db(monkeypatch, onchain=5.0)
        r = await rc.report(db)
        assert r["coverage_ton"] == -1.0
        assert any("Не хватает TON" in a["text"] for a in r["alerts"])
    asyncio.run(go())


def test_stuck_items_are_listed(monkeypatch):
    async def go():
        db = await _db(monkeypatch)
        await db.deposits.insert_one({"id": "d1", "tx_hash": "h", "user_id": "u1", "amount_ton": 1.0,
                                      "status": "crediting", "created_at": old()})
        await db.transactions.insert_many([
            {"id": "w2", "tx_type": "withdrawal", "status": "processing", "processing_started": old(), "amount_ton": 1.0},
            {"id": "w3", "tx_type": "withdrawal", "status": "needs_review", "needs_review_at": old(), "amount_ton": 0.5}])
        r = await rc.report(db)
        assert [d["id"] for d in r["review"]["deposits_crediting"]] == ["d1"]
        assert [w["id"] for w in r["review"]["withdrawals_processing"]] == ["w2"]
        assert [w["id"] for w in r["review"]["withdrawals_needs_review"]] == ["w3"]
    asyncio.run(go())


def test_credit_stuck_deposit_once(monkeypatch):
    async def go():
        db = await _db(monkeypatch)
        await db.deposits.insert_one({"id": "d1", "user_id": "u1", "amount_ton": 1.0, "status": "crediting", "created_at": old()})
        res = await asyncio.gather(*[rc.resolve_deposit(db, ADMIN, "d1", "credit") for _ in range(4)], return_exceptions=True)
        assert sum(1 for x in res if isinstance(x, dict)) == 1
        assert (await db.users.find_one({"id": "u1"}))["balance_ton"] == 4.0
    asyncio.run(go())


def test_needs_review_confirm_or_refund_once(monkeypatch):
    async def go():
        db = await _db(monkeypatch)
        await db.transactions.insert_many([
            {"id": "a", "tx_type": "withdrawal", "status": "needs_review", "user_id": "u2", "amount_ton": 0.5},
            {"id": "b", "tx_type": "withdrawal", "status": "needs_review", "user_id": "u2", "amount_ton": 0.7}])
        await rc.resolve_withdrawal(db, ADMIN, "a", "confirm")            # sent -> no money back
        await rc.resolve_withdrawal(db, ADMIN, "b", "refund")             # not sent -> back to balance
        with pytest.raises(Exception):
            await rc.resolve_withdrawal(db, ADMIN, "b", "refund")         # never twice
        u = await db.users.find_one({"id": "u2"})
        assert abs(u["balance_ton"] - 2.7) < 1e-9
        assert (await db.transactions.find_one({"id": "a"}))["status"] == "completed"
        assert await db.admin_logs.count_documents({}) == 2
    asyncio.run(go())


def test_no_wallets_configured_warns(monkeypatch):
    async def go():
        db = await _db(monkeypatch)
        await db.admin_settings.update_one({"type": "reconciliation"}, {"$set": {"wallets": []}})
        r = await rc.report(db)
        assert r["coverage_ton"] is None and any("кошелька" in a["text"] for a in r["alerts"])
    asyncio.run(go())
