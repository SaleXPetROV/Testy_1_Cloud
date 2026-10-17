"""A full warehouse stops ALL of a player's businesses; free space resumes them.

Runs the real economic_tick on an in-memory Mongo.
    cd backend && python -m pytest tests/test_warehouse_full.py -q
"""
import asyncio
import datetime as dt
import uuid

import pytest

mongomock_motor = pytest.importorskip("mongomock_motor")
import background_tasks as bt  # noqa: E402


def _iso(delta_h=0.0):
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=delta_h)).isoformat()


async def _setup(monkeypatch, *, resources, listing=None, owner_kind="id", shift=True):
    db = mongomock_motor.AsyncMongoMockClient()["wh"]
    monkeypatch.setattr(bt, "_get_shared_db", lambda: db)
    uid = "u-" + uuid.uuid4().hex[:6]
    wallet = "EQwallet" + uid
    await db.users.insert_one({"id": uid, "wallet_address": wallet, "email": f"{uid}@x.io", "resources": resources})
    owner = uid if owner_kind == "id" else wallet
    bid = "b-" + uuid.uuid4().hex[:6]
    await db.businesses.insert_one({
        "id": bid, "owner": owner, "business_type": "helios", "level": 1, "durability": 100,
        "storage": {"capacity": 100, "items": {}}, "plot_id": "p-" + bid,
        "last_tick": _iso(-1), "last_collection": _iso(-1), "last_wear_update": _iso(-1),
        "shift_started_at": _iso(-1), "shift_ends_at": _iso(7 if shift else -0.1),
    })
    if listing:
        await db.market_listings.insert_one({"id": "lot-" + bid, "seller_id": uid, "status": "active", **listing})
    return db, uid, bid


async def _energy(db, uid):
    u = await db.users.find_one({"id": uid})
    return round(float((u.get("resources") or {}).get("energy", 0)), 2)


def test_space_free_business_works(monkeypatch):
    async def go():
        db, uid, bid = await _setup(monkeypatch, resources={"energy": 10, "biomass": 50})
        await bt.economic_tick()
        b = await db.businesses.find_one({"id": bid})
        assert b["is_active"] is True and b["work_status"] == "active"
        assert await _energy(db, uid) > 10
    asyncio.run(go())


def test_full_by_market_listing_stops_production(monkeypatch):
    """The reported bug: lots on the market fill the warehouse; the tick ignored them."""
    async def go():
        db, uid, bid = await _setup(monkeypatch, resources={"energy": 10, "biomass": 50},
                                    listing={"resource_type": "energy", "amount": 45})
        await bt.economic_tick()
        b = await db.businesses.find_one({"id": bid})
        assert b["is_active"] is False
        assert b["work_status"] == "idle" and b["work_status_reason"] == "storage_full"
        assert await _energy(db, uid) == 10            # nothing produced
    asyncio.run(go())


def test_full_by_resources_stops_production(monkeypatch):
    async def go():
        db, uid, bid = await _setup(monkeypatch, resources={"energy": 50, "biomass": 50})
        await bt.economic_tick()
        b = await db.businesses.find_one({"id": bid})
        assert b["work_status_reason"] == "storage_full" and await _energy(db, uid) == 50
    asyncio.run(go())


def test_wallet_owned_business_still_sees_full_warehouse(monkeypatch):
    """Business owned by the wallet string, resources/listings by id — same player."""
    async def go():
        db, uid, bid = await _setup(monkeypatch, resources={"energy": 10, "biomass": 50},
                                    listing={"resource_type": "energy", "amount": 45}, owner_kind="wallet")
        await bt.economic_tick()
        b = await db.businesses.find_one({"id": bid})
        assert b["work_status_reason"] == "storage_full"
    asyncio.run(go())


def test_resumes_when_space_frees(monkeypatch):
    async def go():
        db, uid, bid = await _setup(monkeypatch, resources={"energy": 10, "biomass": 50},
                                    listing={"resource_type": "energy", "amount": 45})
        await bt.economic_tick()
        assert (await db.businesses.find_one({"id": bid}))["is_active"] is False
        await db.market_listings.update_many({"seller_id": uid}, {"$set": {"status": "cancelled"}})
        await db.businesses.update_one({"id": bid}, {"$set": {"last_tick": _iso(-1)}})
        await bt.economic_tick()
        b = await db.businesses.find_one({"id": bid})
        assert b["is_active"] is True and b["work_status"] == "active"
        assert await _energy(db, uid) > 10
    asyncio.run(go())


def test_no_shift_means_idle_even_with_space(monkeypatch):
    async def go():
        db, uid, bid = await _setup(monkeypatch, resources={"energy": 10, "biomass": 50}, shift=False)
        await bt.economic_tick()
        b = await db.businesses.find_one({"id": bid})
        assert b["work_status_reason"] == "shift_ended" and await _energy(db, uid) == 10
    asyncio.run(go())
