"""New city map: purchases never re-run the migration; the repair puts moved businesses and lot owners back."""
import asyncio

import pytest

mongomock_motor = pytest.importorskip("mongomock_motor")

import city_repair as cr
import city_switch as cs
from city_island import load_layout


def run(c):
    return asyncio.run(c)


@pytest.fixture
def db():
    d = mongomock_motor.AsyncMongoMockClient()["cr"]
    run(d.islands.insert_one({"id": "ton_island", "version": "city_v1"}))
    run(d.users.insert_many([{"id": "u1", "username": "alice"}, {"id": "u2", "username": "bob"}]))
    slots = load_layout()["slots"]
    run(d.plots.insert_many([{"id": f"city_v1-{s['slot_id']}", "island_id": "ton_island", "city_slot_id": s["slot_id"],
                              "x": s["x"], "y": s["y"], "owner": None, "business_id": None} for s in slots[:60]]))
    return d, slots


def bio(slots, skip=0):
    return [s for s in slots[:60] if s["business_type"] == "bio_farm"][skip]


def test_no_migration_rerun_on_new_map(db):
    d, slots = db
    s = bio(slots)
    run(d.businesses.insert_one({"id": "b1", "owner": "u1", "business_type": "bio_farm", "x": s["x"], "y": s["y"], "island_id": "ton_island"}))
    assert run(cs.needs_switch(d)) is False                        # used to be True -> full re-run with --force
    r = run(cr.link_unslotted(d))
    assert r == {"linked": 1, "unmatched": 0}
    b = run(d.businesses.find_one({"id": "b1"}))
    assert b["city_slot_id"] == s["slot_id"] and b["plot_id"] == f"city_v1-{s['slot_id']}"


def test_repair_moves_back_and_gives_owners_back(db):
    d, slots = db
    bought, wrong, other = bio(slots, 0), bio(slots, 1), bio(slots, 2)
    # a re-run moved b1 from the lot it was bought on to another one; b2's lot was made free
    run(d.businesses.insert_many([
        {"id": "b1", "owner": "u1", "business_type": "bio_farm", "x": wrong["x"], "y": wrong["y"], "city_slot_id": wrong["slot_id"],
         "city_island_id": "city_v1", "built_at": "2026-10-01"},
        {"id": "b2", "owner": "u2", "business_type": "bio_farm", "x": other["x"], "y": other["y"], "city_slot_id": other["slot_id"],
         "city_island_id": "city_v1", "built_at": "2026-09-01"},
    ]))
    run(d.plots.update_one({"id": f"city_v1-{wrong['slot_id']}"}, {"$set": {"owner": "u1", "business_id": "b1"}}))
    bk = d["migration_backup_20261018_150536"]
    run(bk.insert_many([{"kind": "island", "doc": {"id": "ton_island", "version": "city_v1"}},
                        {"kind": "business", "doc": {"id": "b1", "business_type": "bio_farm", "x": bought["x"], "y": bought["y"]}}]))
    rep = run(cr.repair(d))
    assert rep["restored_moves"] == 1 and not rep["conflicts"]
    b1 = run(d.businesses.find_one({"id": "b1"}))
    assert (b1["x"], b1["y"], b1["city_slot_id"]) == (bought["x"], bought["y"], bought["slot_id"])
    p = lambda s: run(d.plots.find_one({"id": f"city_v1-{s['slot_id']}"}))
    assert p(bought)["owner"] == "u1" and p(bought)["business_id"] == "b1"
    assert p(wrong)["owner"] is None                                   # the lot it was moved to is free again
    assert p(other)["owner"] == "u2"                                   # the wiped owner is back
    assert run(cr.repair(d))["restored_moves"] == 0                    # idempotent


def test_first_real_migration_is_not_undone(db):
    d, slots = db
    s = bio(slots)
    run(d.businesses.insert_one({"id": "b9", "owner": "u1", "business_type": "bio_farm", "x": s["x"], "y": s["y"],
                                 "city_slot_id": s["slot_id"], "city_island_id": "city_v1"}))
    bk = d["migration_backup_20261005_000000"]
    run(bk.insert_many([{"kind": "island", "doc": {"id": "ton_island"}},                 # the OLD map: a real move
                        {"kind": "business", "doc": {"id": "b9", "business_type": "bio_farm", "x": 3, "y": 4}}]))
    assert run(cr.repair(d))["restored_moves"] == 0
