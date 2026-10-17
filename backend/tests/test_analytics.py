"""Retention analytics (backend/analytics.py).

    cd backend && python -m pytest tests/test_analytics.py -q
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

mongomock_motor = pytest.importorskip("mongomock_motor")
import analytics  # noqa: E402

MSK = timezone(timedelta(hours=3))


def run(c):
    return asyncio.run(c)


async def _db():
    db = mongomock_motor.AsyncMongoMockClient()["an"]
    analytics.init(db)
    analytics._indexes_ready = False
    return db


def _msk_day_dt(days_ago):
    return (datetime.now(MSK) - timedelta(days=days_ago)).astimezone(timezone.utc)


def _day(days_ago):
    return (datetime.now(MSK) - timedelta(days=days_ago)).date().isoformat()


async def _add_user(db, uid, days_ago, group="quests"):
    await db.users.insert_one({"id": uid, "created_at": _msk_day_dt(days_ago), "onboarding_group": group})


def test_mark_active_is_idempotent_per_day():
    async def go():
        db = await _db()
        for _ in range(3):
            await analytics.mark_active("u1")
        assert await db.user_active_days.count_documents({"user_id": "u1"}) == 1
    run(go())


def test_cohort_retention_d1():
    async def go():
        db = await _db()
        # cohort registered 2 days ago: u1 came back on D1, u2 did not
        await _add_user(db, "u1", 2)
        await _add_user(db, "u2", 2)
        await db.user_active_days.insert_one({"user_id": "u1", "day": _day(1)})  # D1 after reg
        rep = await analytics.cohort_retention(30)
        row = next(r for r in rep["cohorts"] if r["date"] == _day(2))
        assert row["users"] == 2 and row["d1"] == 1 and row["d1_pct"] == 50.0
        # a cohort registered today is too young for D1 → None
        await _add_user(db, "u3", 0)
        rep2 = await analytics.cohort_retention(30)
        today_row = next(r for r in rep2["cohorts"] if r["date"] == _day(0))
        assert today_row["d1"] is None
    run(go())


def test_retention_group_filter():
    async def go():
        db = await _db()
        await _add_user(db, "q1", 2, group="quests")
        await _add_user(db, "t1", 2, group="tutorial")
        rep = await analytics.cohort_retention(30, group="quests")
        assert rep["overall"]["users"] == 1 and rep["group"] == "quests"
    run(go())


def test_funnel_counts_state_and_events():
    async def go():
        db = await _db()
        await _add_user(db, "u1", 1)
        await _add_user(db, "u2", 1)
        await db.businesses.insert_one({"id": "b1", "owner": "u1"})
        await db.analytics_events.insert_one({"user_id": "u1", "event": "first_shift", "ts": "x"})
        await db.analytics_events.insert_one({"user_id": "u1", "event": "first_sale", "ts": "x"})
        f = await analytics.funnel(30)
        steps = {s["event"]: s for s in f["steps"]}
        assert steps["register"]["users"] == 2
        assert steps["first_business"]["users"] == 1
        assert steps["first_sale"]["users"] == 1
        assert steps["first_sale"]["pct"] == 50.0
    run(go())


def test_active_users_series():
    async def go():
        db = await _db()
        await db.user_active_days.insert_many([
            {"user_id": "a", "day": _day(0)}, {"user_id": "b", "day": _day(0)},
            {"user_id": "a", "day": _day(1)},
        ])
        a = await analytics.active_users(3)
        by = {r["date"]: r["dau"] for r in a["series"]}
        assert by[_day(0)] == 2 and by[_day(1)] == 1
        assert a["today"] == 2
    run(go())
