"""Renting businesses out: offer, rent, daily payout with treasury commission, return,
early end, deposit, rules (level 0, limits, guards)."""
import asyncio, datetime as dt
import pytest
mongomock_motor = pytest.importorskip("mongomock_motor")
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import rental, zero_business as zb


class U:
    def __init__(self, uid): self.id = uid


def world():
    db = mongomock_motor.AsyncMongoMockClient()["rent"]
    app = FastAPI(); who = {"u": "owner"}
    app.include_router(rental.create_rental_router(db, lambda: U(who["u"]), lambda: {"id": "adm"}))
    async def seed():
        await db.users.insert_many([{"id": "owner", "username": "own", "balance_ton": 0.0},
                                    {"id": "renter", "username": "ren", "balance_ton": 100.0},
                                    {"id": "zero", "username": "z", "balance_ton": 100.0},
                                    {"id": "poor", "username": "p", "balance_ton": 0.0001}])
        await db.businesses.insert_many([
            {"id": "b1", "owner": "owner", "business_type": "helios", "level": 3, "durability": 90},
            {"id": "b0", "owner": "owner", "business_type": "helios", "level": 0, "is_zero_business": True},
            {"id": "zb", "owner": "zero", "business_type": "bio_farm", "level": 0, "is_zero_business": True}])
    asyncio.run(seed())
    return db, TestClient(app), who


def offer(c, who, **kw):
    who["u"] = "owner"
    est = c.get("/api/rental/estimate/b1").json()
    price = kw.get("price", est["bounds"]["min_city"])
    return c.post("/api/rental/offers", json={"business_id": kw.get("biz", "b1"), "price_per_day_city": price, "min_days": 1, "max_days": 5}), price


def test_offer_rules_and_estimate():
    db, c, who = world()
    est = c.get("/api/rental/estimate/b1").json()
    assert est["estimate"]["shifts_per_day"] == 3 and "net_city" in est["estimate"] and est["bounds"]["max_city"] >= est["bounds"]["min_city"]
    r, _ = offer(c, who, biz="b0"); assert r.status_code == 400                       # level 0: no rent-out
    r, _ = offer(c, who, price=10 ** 9); assert r.status_code == 400                  # above the admin bound
    r, _ = offer(c, who); assert r.status_code == 200
    r, _ = offer(c, who); assert r.status_code == 409                                 # one offer per business


def test_rent_payout_commission_and_return():
    db, c, who = world()
    o, price = offer(c, who); oid = o.json()["id"]
    who["u"] = "zero"; assert c.post(f"/api/rental/offers/{oid}/rent", json={"days": 2}).status_code == 423   # holds level 0
    who["u"] = "poor"; assert c.post(f"/api/rental/offers/{oid}/rent", json={"days": 2}).status_code == 400   # real balance
    who["u"] = "renter"
    r = c.post(f"/api/rental/offers/{oid}/rent", json={"days": 2}); assert r.status_code == 200
    rt = r.json(); per = price / 1000
    async def go():
        u = await db.users.find_one({"id": "renter"})
        assert abs(u["balance_ton"] - (100 - per * 3)) < 1e-6 and abs(u["frozen_ton"] - per * 3) < 1e-9   # frozen, not gone
        b = await db.businesses.find_one({"id": "b1"})
        assert b["owner"] == "renter" and b["rental_owner"] == "owner"                # works for the renter
        with pytest.raises(HTTPException):
            rental.assert_not_rented(b)                                               # no sell / list / upgrade / skin
        assert not await zb.can_stake_zero(db, await db.users.find_one({"id": "renter"}), ["renter"])   # renter: no level 0
        assert await zb.count_real_businesses(db, ["owner"]) >= 1                     # owner still counts it
        # one day later: the owner gets one day minus the commission
        await rental.settle(db, now=dt.datetime.fromisoformat(rt["started_at"]) + dt.timedelta(days=1, minutes=1))
        o_ = await db.users.find_one({"id": "owner"}); fee = per * 0.10
        assert abs(o_["balance_ton"] - (per - fee)) < 1e-6
        assert abs((await db.admin_stats.find_one({"type": "treasury"}))["rental_commission"] - fee) < 1e-9
        await rental.settle(db, now=dt.datetime.fromisoformat(rt["started_at"]) + dt.timedelta(days=1, minutes=5))   # idempotent
        assert abs((await db.users.find_one({"id": "owner"}))["balance_ton"] - (per - fee)) < 1e-6
        # term over: business back, deposit back to the renter (little wear)
        await rental.settle(db, now=dt.datetime.fromisoformat(rt["ends_at"]) + dt.timedelta(minutes=1))
        b = await db.businesses.find_one({"id": "b1"}); assert b["owner"] == "owner" and "rental_id" not in b
        assert abs((await db.users.find_one({"id": "owner"}))["balance_ton"] - 2 * (per - fee)) < 1e-6
        ren = await db.users.find_one({"id": "renter"})
        assert abs(ren["balance_ton"] - (100 - per * 2)) < 1e-6 and abs(ren["frozen_ton"]) < 1e-9   # nothing left frozen
        assert (await db.rentals.find_one({"id": rt["id"]}))["status"] == "ended"
        kinds = {t["tx_type"] async for t in db.transactions.find({"rental_id": rt["id"]})}
        assert {"rental_freeze", "rental_charge", "rental_payout", "rental_commission", "rental_unfreeze"} <= kinds
    asyncio.run(go())


def test_early_end_refund_and_deposit_for_heavy_wear():
    db, c, who = world()
    o, price = offer(c, who); oid = o.json()["id"]
    who["u"] = "renter"; rt = c.post(f"/api/rental/offers/{oid}/rent", json={"days": 5}).json(); per = price / 1000
    async def wear():
        await db.businesses.update_one({"id": "b1"}, {"$set": {"durability": 40}})     # lost 50 > 20 points
    asyncio.run(wear())
    assert c.post(f"/api/rental/{rt['id']}/end").status_code == 200
    async def go():
        r = await db.rentals.find_one({"id": rt["id"]})
        assert r["released_days"] == 2 and r["refund_ton"] == pytest.approx(per * 3)   # 1 used + 1 penalty day
        assert r["deposit_to_owner_ton"] == pytest.approx(per)                           # heavy wear: deposit -> owner
        assert (await db.businesses.find_one({"id": "b1"}))["owner"] == "owner"
    asyncio.run(go())


def test_business_limit_counts_rented():
    db, c, who = world()
    async def seed():
        await db.businesses.insert_many([{"id": f"r{i}", "owner": "renter", "business_type": "helios", "level": 1} for i in range(3)])
    asyncio.run(seed())
    o, _ = offer(c, who); who["u"] = "renter"
    r = c.post(f"/api/rental/offers/{o.json()['id']}/rent", json={"days": 1})
    assert r.status_code == 400 and "3" in r.json()["detail"]


def test_admin_stats_chart_and_totals():
    db, c, who = world()
    o, price = offer(c, who); who["u"] = "renter"
    rt = c.post(f"/api/rental/offers/{o.json()['id']}/rent", json={"days": 1}).json()
    async def go():
        await rental.settle(db, now=dt.datetime.fromisoformat(rt["ends_at"]) + dt.timedelta(minutes=1))
    asyncio.run(go())
    st = c.get("/api/admin/rental/stats?days=7").json()
    assert len(st["chart"]) == 7 and st["totals"]["commission_city"] == pytest.approx(price * 0.10, abs=0.01)
    assert st["totals"]["rent_paid_city"] == pytest.approx(price * 0.90, abs=0.01)
    assert sum(d["commission_city"] for d in st["chart"]) == pytest.approx(price * 0.10, abs=0.01)
    assert any(t["tx_type"] == "rental_commission" for t in st["transactions"])
