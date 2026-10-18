"""backend/scripts/migrate_to_city_map.py on a fake database."""
import argparse, asyncio, json, math
import pytest
mongomock_motor = pytest.importorskip("mongomock_motor")
from scripts import migrate_to_city_map as mig


def args(**kw):
    a = dict(apply=False, force=False, allow_unplaced=False, rollback=None, layout=str(mig.LAYOUT), report="/tmp/mig_report.json")
    a.update(kw); return argparse.Namespace(**a)


async def world(monkeypatch):
    client = mongomock_motor.AsyncMongoMockClient()
    monkeypatch.setattr(mig, "AsyncIOMotorClient", lambda *a, **k: client)
    monkeypatch.setenv("DB_NAME", "mig")
    db = client["mig"]
    await db.users.insert_many([{"id": "u1", "username": "alice"}, {"id": "u2", "username": "bob", "wallet_address": "EQbob"},
                                {"id": "u3", "username": "carol"}])
    rows = [("b1", "u1", "helios", 3), ("b2", "u1", "chip_factory", 5), ("b3", "u1", "gram_bank", 7),
            ("b4", "EQbob", "cold_storage", 2), ("b5", "u3", "bio_farm", 0)]                 # wallet owner, legacy names, level 0
    rows += [(f"c{i}", "u3", "casino", 1) for i in range(5)]                                 # 5 casinos: Core has 1, map has 4
    for bid, owner, t, lvl in rows:
        await db.businesses.insert_one({"id": bid, "owner": owner, "business_type": t, "level": lvl, "plot_id": f"old-{bid}", "x": 1, "y": 2,
                                        "durability": 77, "storage": {"items": {"energy": 5}}, **({"is_zero_business": True, "expires_at": "x"} if lvl == 0 else {})})
        await db.plots.insert_one({"id": f"old-{bid}", "island_id": "ton_island", "owner": owner, "business_id": bid})
    await db.land_listings.insert_one({"id": "L1", "business_id": "b1", "plot_id": "old-b1", "price": 9})
    return db


def test_dry_run_changes_nothing_and_reports(monkeypatch):
    async def go():
        db = await world(monkeypatch)
        code = await mig.run(args())
        r = json.load(open("/tmp/mig_report.json"))
        assert code == 0 and r["to_move"] == 9 and len(r["unplaced"]) == 1          # 5th casino has no slot anywhere
        assert (await db.businesses.find_one({"id": "b1"}))["plot_id"] == "old-b1"   # untouched
    asyncio.run(go())


def test_apply_keeps_ids_counts_and_prefers_core(monkeypatch):
    async def go():
        db = await world(monkeypatch)
        assert await mig.run(args(apply=True)) == 2                                   # refuses: one unplaced
        code = await mig.run(args(apply=True, allow_unplaced=True))
        assert code == 0
        layout = json.load(open(mig.LAYOUT)); slots = {s["slot_id"]: s for s in layout["slots"]}
        moved = [b async for b in db.businesses.find({"city_island_id": "city_v1"})]
        isl = await db.islands.find_one({"id": "ton_island"})
        assert isl["version"] == "city_v1" and isl["total_cells"] == 478 and all(b["island_id"] == "ton_island" for b in moved)
        assert {b["id"] for b in moved} == {"b1", "b2", "b3", "b4", "b5", "c0", "c1", "c2", "c3"}  # same ids
        for b in moved:                                                               # right type on the slot
            s = slots[b["city_slot_id"]]
            assert s["business_type"] == mig.canon_type(b["business_type"])
            assert b["durability"] == 77 and b["storage"]["items"]["energy"] == 5      # nothing else changed
        alice = [b for b in moved if b["owner"] == "u1"]
        assert all(b["district_id"] == 1 for b in alice)                              # Core first
        c = [slots[b["city_slot_id"]] for b in alice]
        assert max(math.hypot(a["x"] - z["x"], a["y"] - z["y"]) for a in c for z in c) < 20   # close together
        lvl0 = await db.businesses.find_one({"id": "b5"}); assert lvl0["is_zero_business"] and lvl0["expires_at"] == "x"
        cas = [b for b in moved if b["business_type"] == "casino"]
        assert sorted(b["district_id"] for b in cas)[0] == 1 and len({b["district_id"] for b in cas}) > 1   # overflow
        assert (await db.businesses.find_one({"id": "c4"}))["plot_id"] == "old-c4"     # unplaced kept as it was
        assert await db.plots.count_documents({"island_id": "ton_island", "city_slot_id": {"$exists": True}}) == 478
        assert await db.plots.count_documents({"island_id": "ton_island", "city_slot_id": {"$exists": True}, "owner": {"$ne": None}}) == 9
        old = await db.plots.find_one({"id": "old-b1"}); assert old["archived"] is True and old["island_id"] == "ton_island_legacy"
        assert (await db.land_listings.find_one({"id": "L1"}))["plot_id"].startswith("city_v1-")
        assert await mig.run(args(apply=True, allow_unplaced=True)) == 1               # idempotent
    asyncio.run(go())


def test_rollback_restores_everything(monkeypatch):
    async def go():
        db = await world(monkeypatch)
        await mig.run(args(apply=True, allow_unplaced=True))
        tag = (await db.admin_settings.find_one({"type": "city_map_migration"}))["tag"]
        assert await mig.run(args(rollback=tag)) == 0
        b1 = await db.businesses.find_one({"id": "b1"})
        assert b1["plot_id"] == "old-b1" and "city_island_id" not in b1
        assert await db.plots.count_documents({"city_slot_id": {"$exists": True}}) == 0
        assert (await db.land_listings.find_one({"id": "L1"}))["plot_id"] == "old-b1"
    asyncio.run(go())
