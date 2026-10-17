import asyncio
import pytest
mongomock_motor = pytest.importorskip("mongomock_motor")
from scripts import normalize_owner_ids as n


def test_wallet_and_email_owners_become_ids_and_rerun_is_noop():
    async def go():
        db = mongomock_motor.AsyncMongoMockClient()["own"]
        await db.users.insert_many([{"id": "u1", "wallet_address": "EQa", "email": "a@x.io"}, {"id": "u2"}])
        await db.businesses.insert_many([{"id": "b1", "owner": "EQa"}, {"id": "b2", "owner": "a@x.io"}, {"id": "b3", "owner": "u2"},
                                         {"id": "b4", "owner": "EQunknown"}])
        await db.land_listings.insert_one({"id": "l1", "seller_id": "EQa"})
        assert (await n.run(False, db)) == {"businesses.owner": 2, "land_listings.seller_id": 1}   # dry run
        assert (await db.businesses.find_one({"id": "b1"}))["owner"] == "EQa"
        await n.run(True, db)
        owners = {b["id"]: b["owner"] async for b in db.businesses.find({})}
        assert owners == {"b1": "u1", "b2": "u1", "b3": "u2", "b4": "EQunknown"}           # unknown owner left as is
        assert (await db.land_listings.find_one({"id": "l1"}))["seller_id"] == "u1"
        assert await n.run(True, db) == {}                                                   # idempotent
    asyncio.run(go())
