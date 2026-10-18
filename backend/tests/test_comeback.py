"""Comeback bonus + streak shields (backend/comeback.py).

    cd backend && python -m pytest tests/test_comeback.py -q
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

mongomock_motor = pytest.importorskip("mongomock_motor")
from fastapi import HTTPException  # noqa: E402
import comeback  # noqa: E402

MSK = timezone(timedelta(hours=3))


def run(c):
    return asyncio.run(c)


def _day(days_ago):
    return (datetime.now(MSK) - timedelta(days=days_ago)).date().isoformat()


async def _db(uid="u1"):
    db = mongomock_motor.AsyncMongoMockClient()["cb"]
    comeback.init(db)
    await db.users.insert_one({"id": uid, "bonus_balance": 0.0})
    return db


async def _active(db, uid, days_ago):
    await db.user_active_days.insert_one({"user_id": uid, "day": _day(days_ago)})


def test_no_bonus_without_history():
    async def go():
        db = await _db()
        assert (await comeback.status("u1"))["available"] is False
    run(go())


def test_small_and_big_tiers():
    async def go():
        db = await _db()
        await _active(db, "u1", 4)                       # away 4 days
        st = await comeback.status("u1")
        assert st["available"] and st["tier"] == "small" and st["away_days"] == 4
        db2 = await _db("u2")
        await _active(db2, "u2", 20)
        st2 = await comeback.status("u2")
        assert st2["tier"] == "big" and st2["reward"]["shields"] == 1
    run(go())


def test_not_away_long_enough():
    async def go():
        db = await _db()
        await _active(db, "u1", 2)                       # away 2 days < 3
        assert (await comeback.status("u1"))["available"] is False
    run(go())


def test_claim_grants_and_is_once_per_return():
    async def go():
        db = await _db()
        await _active(db, "u1", 5)
        r = await comeback.claim("u1")
        assert r["granted"]["city"] == 30
        u = await db.users.find_one({"id": "u1"})
        assert abs(u["bonus_balance"] - 0.030) < 1e-9
        assert comeback.decay_protected(u) is True
        with pytest.raises(HTTPException) as e:
            await comeback.claim("u1")
        assert e.value.status_code in (400, 409)
    run(go())


def test_big_claim_gives_shield():
    async def go():
        db = await _db()
        await _active(db, "u1", 20)
        r = await comeback.claim("u1")
        assert r["granted"]["shields"] == 1
        assert await comeback.shields("u1") == 1
    run(go())


def test_concurrent_claims_pay_once():
    async def go():
        db = await _db()
        await _active(db, "u1", 5)
        res = await asyncio.gather(*[comeback.claim("u1") for _ in range(5)], return_exceptions=True)
        assert sum(1 for x in res if isinstance(x, dict)) == 1
        u = await db.users.find_one({"id": "u1"})
        assert abs(u["bonus_balance"] - 0.030) < 1e-9
    run(go())


def test_shields_capped_at_two():
    async def go():
        await _db()
        assert await comeback.add_shields("u1", 1) == 1
        assert await comeback.add_shields("u1", 5) == 2       # capped
    run(go())


def test_config_override():
    async def go():
        db = await _db()
        await db.tasks_config.insert_one({"key": "comeback", "small_after_days": 2, "small_city": 7})
        await _active(db, "u1", 2)
        st = await comeback.status("u1")
        assert st["available"] and st["reward"]["city"] == 7
    run(go())
