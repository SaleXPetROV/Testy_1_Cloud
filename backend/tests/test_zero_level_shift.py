"""Level-0 businesses work only during a shift, like every other business.

    cd backend && python -m pytest tests/test_zero_level_shift.py -q
"""
import asyncio
import datetime as dt

import pytest

mongomock_motor = pytest.importorskip("mongomock_motor")
import background_tasks as bt  # noqa: E402


def _iso(h=0.0):
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=h)).isoformat()


def test_shift_rule_has_no_level0_exception():
    zero = {"is_zero_business": True, "level": 0}
    assert bt.shift_is_active(zero) is False                                   # no shift -> idle
    assert bt.shift_is_active({**zero, "shift_ends_at": _iso(2)}) is True       # shift running
    assert bt.shift_is_active({"tutorial": True}) is True                      # sandbox still auto
    assert bt.shift_is_active({"is_trial": True}) is True                      # trial centre still auto


async def _world(monkeypatch, shift):
    db = mongomock_motor.AsyncMongoMockClient()["z0"]
    monkeypatch.setattr(bt, "_get_shared_db", lambda: db)
    await db.users.insert_one({"id": "p1", "resources": {"biomass": 60}})
    doc = {"id": "b0", "owner": "p1", "business_type": "helios", "level": 0, "is_zero_business": True,
           "durability": 100, "storage": {"capacity": 200, "items": {}}, "plot_id": "pl0",
           "last_tick": _iso(-1), "last_collection": _iso(-1), "last_wear_update": _iso(-1)}
    if shift:
        doc.update({"shift_started_at": _iso(-1), "shift_ends_at": _iso(7)})
    await db.businesses.insert_one(doc)
    return db


async def _energy(db):
    u = await db.users.find_one({"id": "p1"})
    return float((u.get("resources") or {}).get("energy", 0))


def test_level0_idle_without_shift(monkeypatch):
    async def go():
        db = await _world(monkeypatch, shift=False)
        await bt.economic_tick()
        b = await db.businesses.find_one({"id": "b0"})
        assert b["work_status_reason"] == "shift_ended" and await _energy(db) == 0
    asyncio.run(go())


def test_level0_produces_during_shift(monkeypatch):
    async def go():
        db = await _world(monkeypatch, shift=True)
        await bt.economic_tick()
        b = await db.businesses.find_one({"id": "b0"})
        assert b["is_active"] is True and await _energy(db) > 0
    asyncio.run(go())
