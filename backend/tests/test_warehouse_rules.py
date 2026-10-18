"""ONE warehouse rule (backend/core/warehouse.py) and the places that use it.

    cd backend && python -m pytest tests/test_warehouse_rules.py -q
"""
import asyncio

import pytest

mongomock_motor = pytest.importorskip("mongomock_motor")
from core import warehouse as wh  # noqa: E402


def run(c):
    return asyncio.run(c)


async def _db(resources=None, businesses=(), listings=(), wallet=None):
    db = mongomock_motor.AsyncMongoMockClient()["wh_rules"]
    await db.users.insert_one({"id": "u1", "email": "u1@x.io", "wallet_address": wallet, "resources": resources or {}})
    for b in businesses:
        await db.businesses.insert_one({"owner": "u1", **b})
    for i, l in enumerate(listings):
        await db.market_listings.insert_one({"id": f"l{i}", "seller_id": "u1", **l})
    return db


# ───────────── pure helpers ─────────────
def test_used_by_resources_is_floored_and_weighted():
    # energy w1 floor(37.9)=37, biomass w1 12, neuro_core (tier 3) w20
    assert wh.used_by_resources({"energy": 37.9, "biomass": 12, "neuro_core": 1}) == 69
    assert wh.used_by_resources({"energy": 0.9, "bad": "x"}) == 0
    assert wh.used_by_resources(None) == 0


def test_capacity_minimum_is_personal_warehouse():
    assert wh.total_capacity([]) == 50                                  # no business
    assert wh.total_capacity([{"id": "b", "storage": {"capacity": 0}}]) == 50   # legacy, no storage
    assert wh.total_capacity([{"id": "a", "storage": {"capacity": 100}},
                              {"id": "b", "storage": {"capacity": 260}}]) == 360


def test_storage_buff_applies():
    from business_config import TIER3_BUFFS
    buff = TIER3_BUFFS["deep_storage"]                                  # +10 %
    assert wh.business_capacity({"storage": {"capacity": 200}}, buff) == 220
    assert wh.total_capacity([{"id": "a", "storage": {"capacity": 200}}], {"a": buff}) == 220


def test_state_full_and_free():
    assert wh.state(100, 100) == {"used": 100, "capacity": 100, "free": 0, "full": True}
    assert wh.state(40, 100)["free"] == 60 and not wh.state(40, 100)["full"]


# ───────────── user_warehouse (DB) ─────────────
def test_user_warehouse_counts_only_active_lots():
    async def go():
        db = await _db({"energy": 10}, [{"id": "b1", "storage": {"capacity": 100}}],
                       [{"resource_type": "energy", "amount": 30, "status": "active"},
                        {"resource_type": "energy", "amount": 99, "status": "sold"}])
        st = await wh.user_warehouse(db, await db.users.find_one({"id": "u1"}))
        assert st == {"used": 40, "capacity": 100, "free": 60, "full": False}
    run(go())


def test_user_warehouse_patron_storage_buff():
    """The case two old copies (trash pile, admin buyout) got wrong: they ignored buffs."""
    async def go():
        db = await _db({"energy": 105}, [{"id": "b1", "storage": {"capacity": 100}, "patron_id": "pat"}])
        await db.businesses.insert_one({"id": "pat", "owner": "someone", "patron_buff": "deep_storage"})
        st = await wh.user_warehouse(db, await db.users.find_one({"id": "u1"}))
        assert st["capacity"] == 110 and st["used"] == 105 and not st["full"]   # buff gives room
    run(go())


def test_businesses_owned_by_wallet_are_counted():
    async def go():
        db = await _db({"energy": 1}, wallet="EQwallet")
        await db.businesses.insert_one({"id": "bw", "owner": "EQwallet", "storage": {"capacity": 300}})
        st = await wh.user_warehouse(db, await db.users.find_one({"id": "u1"}))
        assert st["capacity"] == 300
    run(go())


# ───────────── consistency: callers agree ─────────────
def test_trash_pile_uses_the_same_rule():
    async def go():
        db = await _db({"energy": 105}, [{"id": "b1", "storage": {"capacity": 100}, "patron_id": "pat"}])
        await db.businesses.insert_one({"id": "pat", "owner": "someone", "patron_buff": "deep_storage"})
        from routes.trash import _capacity_and_used
        user = await db.users.find_one({"id": "u1"})
        cap, used = await _capacity_and_used(db, user)
        st = await wh.user_warehouse(db, user)
        assert (cap, used) == (st["capacity"], st["used"]) == (110, 105)
    run(go())
