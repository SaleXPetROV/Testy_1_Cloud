"""A claimed level-0 business is put up for sale (owner's decision after v2.3).

    cd backend && python -m pytest tests/test_zero_listing.py -q
"""
import asyncio

import pytest

mongomock_motor = pytest.importorskip("mongomock_motor")


def test_claimed_level0_business_is_listed_for_buyout():
    async def go():
        from routes.ton_island import _list_zero_business
        import zero_business as zb
        db = mongomock_motor.AsyncMongoMockClient()["zl"]
        biz = {"id": "b0", "business_type": "helios", "level": 0, "is_zero_business": True, "zero_map_price": 5.0,
               "owner": "u1", "plot_id": "p1"}
        await db.businesses.insert_one(dict(biz))
        await db.plots.insert_one({"id": "p1", "business": {"id": "b0"}})
        await _list_zero_business(db, biz, "u1", {"username": "newbie"}, "b0", "p1")
        lot = await db.land_listings.find_one({"business_id": "b0"})
        assert lot and lot["is_zero_business"] is True and lot["status"] == "active"
        assert abs(lot["price"] - 5.0 * zb.ZERO_PRICE_MULTIPLIER) < 1e-9          # map price × 1.2
        assert (await db.businesses.find_one({"id": "b0"}))["zero_listing_id"] == lot["id"]
        assert (await db.plots.find_one({"id": "p1"}))["business"]["zero_listing_id"] == lot["id"]
    asyncio.run(go())


def test_listing_failure_never_breaks_the_claim():
    async def go():
        from routes.ton_island import _list_zero_business
        db = mongomock_motor.AsyncMongoMockClient()["zl2"]
        # broken payload (no map price, no type) must not raise
        await _list_zero_business(db, {}, "u1", None, "bX", "pX")
    asyncio.run(go())
