"""
Iter 4 regression: bonus_balance can pay for a marketplace BUSINESS listing
ONLY if the buyer already owns a level>=1 business (excluding is_zero_business).

Covers POST /api/market/land/buy business-listing branch:
  A) buyer w/o level1 biz, big bonus + tiny real balance   -> 403, no charge
  B) buyer w/o level1 biz but enough real balance          -> success, bonus untouched
  C) buyer WITH a level1 biz + big bonus                   -> success, bonus consumed first
  D) plain LAND listing (business=None), bonus-only funds  -> success (regression)
"""
import os
import uuid
import asyncio
import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient
from passlib.context import CryptContext
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

TAG = f"TEST_bonusgate_{uuid.uuid4().hex[:8]}"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


async def _mongo():
    c = AsyncIOMotorClient(MONGO_URL)
    return c, c[DB_NAME]


def _login(email, password):
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        timeout=20,
    )
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text}"
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok, f"no token for {email}: {r.json()}"
    return tok


def _seed_user(db, email, password, uid, extra=None):
    doc = {
        "id": uid,
        "email": email,
        "username": f"tu_{uuid.uuid4().hex[:12]}",
        "hashed_password": pwd_context.hash(password),
        "balance_ton": 0.0,
        "bonus_balance": 0.0,
        "wallet_address": None,
        "test_tag": TAG,
        "is_active_investor": False,
        "role": "USER",
    }
    if extra:
        doc.update(extra)
    return db.users.insert_one(doc)


@pytest.fixture(scope="module")
def env():
    """Seed 3 users (seller_A/B/C listings need distinct sellers optional; using single seller),
    3 buyers, 3 plot+business + 1 plain-plot pairs, and 4 land_listings."""

    async def _setup():
        c, db = await _mongo()
        try:
            # ---- users ----
            seller_id = f"{TAG}_seller"
            buyerA_id = f"{TAG}_buyerA"   # no level1 biz, bonus-only funds
            buyerB_id = f"{TAG}_buyerB"   # no level1 biz, real funds
            buyerC_id = f"{TAG}_buyerC"   # has level1 biz, bonus funds
            buyerD_id = f"{TAG}_buyerD"   # for land-only test, bonus-only funds

            seller_email = f"{TAG}_seller@t.local"
            buyerA_email = f"{TAG}_buyerA@t.local"
            buyerB_email = f"{TAG}_buyerB@t.local"
            buyerC_email = f"{TAG}_buyerC@t.local"
            buyerD_email = f"{TAG}_buyerD@t.local"
            PWD = "Test1234!"

            await _seed_user(db, seller_email, PWD, seller_id)
            await _seed_user(db, buyerA_email, PWD, buyerA_id,
                             {"balance_ton": 0.5, "bonus_balance": 50.0})
            await _seed_user(db, buyerB_email, PWD, buyerB_id,
                             {"balance_ton": 50.0, "bonus_balance": 5.0})
            await _seed_user(db, buyerC_email, PWD, buyerC_id,
                             {"balance_ton": 0.5, "bonus_balance": 50.0})
            await _seed_user(db, buyerD_email, PWD, buyerD_id,
                             {"balance_ton": 0.5, "bonus_balance": 50.0})

            # buyerC already owns a level-1 helios business (not for sale)
            existing_biz_id = f"{TAG}_ownedbiz_{uuid.uuid4().hex[:6]}"
            existing_plot_id = f"{TAG}_ownedplot_{uuid.uuid4().hex[:6]}"
            await db.plots.insert_one({
                "id": existing_plot_id, "city_id": "ton_island", "island_id": "ton_island",
                "x": 800, "y": 800, "owner": buyerC_id, "test_tag": TAG,
            })
            await db.businesses.insert_one({
                "id": existing_biz_id, "business_type": "helios", "owner": buyerC_id,
                "island_id": "ton_island", "city_id": "ton_island",
                "plot_x": 800, "plot_y": 800, "x": 800, "y": 800,
                "plot_id": existing_plot_id, "level": 1,
                "is_active": True, "status": "active",
                "storage": {"items": {}, "capacity": 1000},
                "test_tag": TAG,
            })

            # ---- three BUSINESS listings (for A/B/C) + one LAND-only listing (D) ----
            listings_meta = []
            for tag in ("A", "B", "C"):
                pid = f"{TAG}_plot{tag}_{uuid.uuid4().hex[:6]}"
                bid = f"{TAG}_biz{tag}_{uuid.uuid4().hex[:6]}"
                lid = f"{TAG}_listing{tag}_{uuid.uuid4().hex[:6]}"
                x, y = 900 + ord(tag), 900 + ord(tag)
                await db.plots.insert_one({
                    "id": pid, "city_id": "ton_island", "island_id": "ton_island",
                    "x": x, "y": y, "owner": seller_id, "on_sale": True,
                    "listing_id": lid, "business_id": bid, "test_tag": TAG,
                })
                await db.businesses.insert_one({
                    "id": bid, "business_type": "helios", "owner": seller_id,
                    "island_id": "ton_island", "city_id": "ton_island",
                    "plot_x": x, "plot_y": y, "x": x, "y": y,
                    "plot_id": pid, "level": 1,
                    "is_active": True, "status": "on_sale", "on_sale": True,
                    "listing_id": lid,
                    "storage": {"items": {}, "capacity": 1000},
                    "test_tag": TAG,
                })
                await db.land_listings.insert_one({
                    "id": lid,
                    "seller_id": seller_id,
                    "seller_user_id": seller_id,
                    "seller_username": f"seller_{TAG[:12]}",
                    "plot_id": pid,
                    "business_id": bid,
                    "city_id": "ton_island",
                    "island_id": "ton_island",
                    "x": x, "y": y,
                    "price": 2.0,
                    "tax_amount": 0.1,
                    "seller_receives": 1.9,
                    "business": {"type": "helios", "level": 1, "name": "Helios"},
                    "status": "active",
                    "city_name": "GRAM Island",
                    "test_tag": TAG,
                })
                listings_meta.append({"tag": tag, "listing_id": lid, "plot_id": pid, "biz_id": bid})

            # LAND-only listing (no business)
            plotD = f"{TAG}_plotD_{uuid.uuid4().hex[:6]}"
            lidD = f"{TAG}_listingD_{uuid.uuid4().hex[:6]}"
            await db.plots.insert_one({
                "id": plotD, "city_id": "ton_island", "island_id": "ton_island",
                "x": 950, "y": 950, "owner": seller_id, "on_sale": True,
                "listing_id": lidD, "test_tag": TAG,
            })
            await db.land_listings.insert_one({
                "id": lidD,
                "seller_id": seller_id,
                "seller_user_id": seller_id,
                "seller_username": f"tuser_{seller_id[:6]}",
                "plot_id": plotD,
                "city_id": "ton_island",
                "island_id": "ton_island",
                "x": 950, "y": 950,
                "price": 2.0,
                "tax_amount": 0.1,
                "seller_receives": 1.9,
                "business": None,
                "status": "active",
                "city_name": "GRAM Island",
                "test_tag": TAG,
            })

            return {
                "PWD": PWD,
                "seller_email": seller_email,
                "buyerA_email": buyerA_email, "buyerB_email": buyerB_email,
                "buyerC_email": buyerC_email, "buyerD_email": buyerD_email,
                "buyerA_id": buyerA_id, "buyerB_id": buyerB_id,
                "buyerC_id": buyerC_id, "buyerD_id": buyerD_id,
                "listings": listings_meta, "listingD_id": lidD,
                "existing_biz_id": existing_biz_id, "existing_plot_id": existing_plot_id,
            }
        finally:
            c.close()

    data = _run(_setup())

    # Fetch tokens
    data["tok"] = {
        "A": _login(data["buyerA_email"], data["PWD"]),
        "B": _login(data["buyerB_email"], data["PWD"]),
        "C": _login(data["buyerC_email"], data["PWD"]),
        "D": _login(data["buyerD_email"], data["PWD"]),
    }

    yield data

    async def _cleanup():
        c, db = await _mongo()
        try:
            await db.users.delete_many({"test_tag": TAG})
            await db.plots.delete_many({"test_tag": TAG})
            await db.businesses.delete_many({"test_tag": TAG})
            await db.land_listings.delete_many({"test_tag": TAG})
            await db.transactions.delete_many({"user_id": {"$regex": f"^{TAG}"}})
        finally:
            c.close()

    _run(_cleanup())


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


async def _get_user(uid):
    c, db = await _mongo()
    try:
        return await db.users.find_one({"id": uid}, {"_id": 0})
    finally:
        c.close()


async def _get_listing(lid):
    c, db = await _mongo()
    try:
        return await db.land_listings.find_one({"id": lid}, {"_id": 0})
    finally:
        c.close()


# ---------- Test A: no level1 biz + bonus only -> 403 ----------
def test_A_no_level1_biz_bonus_only_rejected(env):
    listing = env["listings"][0]  # A
    before = _run(_get_user(env["buyerA_id"]))
    r = requests.post(
        f"{BASE_URL}/api/market/land/buy",
        headers=_auth(env["tok"]["A"]),
        json={"listing_id": listing["listing_id"]},
        timeout=20,
    )
    assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text}"
    detail = (r.json().get("detail") or "").lower()
    assert "бизнес" in detail or "бонус" in detail, f"unexpected detail: {r.text}"

    after = _run(_get_user(env["buyerA_id"]))
    assert after["bonus_balance"] == before["bonus_balance"], "bonus was charged on 403"
    assert after["balance_ton"] == before["balance_ton"], "real balance was charged on 403"

    lst = _run(_get_listing(listing["listing_id"]))
    assert lst["status"] == "active", f"listing status flipped: {lst.get('status')}"


# ---------- Test B: no level1 biz but enough real -> success, bonus untouched ----------
def test_B_no_level1_biz_real_balance_succeeds(env):
    listing = env["listings"][1]  # B
    before = _run(_get_user(env["buyerB_id"]))
    r = requests.post(
        f"{BASE_URL}/api/market/land/buy",
        headers=_auth(env["tok"]["B"]),
        json={"listing_id": listing["listing_id"]},
        timeout=30,
    )
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
    after = _run(_get_user(env["buyerB_id"]))

    # bonus MUST be unchanged (rule: no bonus allowed for this buyer)
    assert after["bonus_balance"] == before["bonus_balance"], (
        f"bonus consumed for user w/o level1 biz: before={before['bonus_balance']} after={after['bonus_balance']}"
    )
    # real balance must have decreased by 2.0
    assert abs(before["balance_ton"] - after["balance_ton"] - 2.0) < 1e-6, (
        f"real balance delta wrong: before={before['balance_ton']} after={after['balance_ton']}"
    )


# ---------- Test C: has level1 biz + bonus -> success, bonus consumed first ----------
def test_C_has_level1_biz_bonus_used(env):
    listing = env["listings"][2]  # C
    before = _run(_get_user(env["buyerC_id"]))
    r = requests.post(
        f"{BASE_URL}/api/market/land/buy",
        headers=_auth(env["tok"]["C"]),
        json={"listing_id": listing["listing_id"]},
        timeout=30,
    )
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
    after = _run(_get_user(env["buyerC_id"]))
    # bonus must have decreased by full price (2.0) since bonus>=price
    assert abs(before["bonus_balance"] - after["bonus_balance"] - 2.0) < 1e-6, (
        f"bonus not consumed first: before={before['bonus_balance']} after={after['bonus_balance']}"
    )
    # real balance unchanged
    assert abs(before["balance_ton"] - after["balance_ton"]) < 1e-6, (
        f"real balance moved unexpectedly: before={before['balance_ton']} after={after['balance_ton']}"
    )


# ---------- Test D: plain LAND listing (no business), bonus-only funds ----------
def test_D_land_only_listing_bonus_allowed(env):
    before = _run(_get_user(env["buyerD_id"]))
    r = requests.post(
        f"{BASE_URL}/api/market/land/buy",
        headers=_auth(env["tok"]["D"]),
        json={"listing_id": env["listingD_id"]},
        timeout=30,
    )
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
    after = _run(_get_user(env["buyerD_id"]))
    # bonus must have decreased by 2.0 (bonus first)
    assert abs(before["bonus_balance"] - after["bonus_balance"] - 2.0) < 1e-6, (
        f"bonus not used for land-only listing: before={before['bonus_balance']} after={after['bonus_balance']}"
    )
