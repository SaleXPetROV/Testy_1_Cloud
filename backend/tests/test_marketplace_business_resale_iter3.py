"""
Marketplace business resale bug fix tests (iter3).

Verifies that a business bought via POST /api/market/land/buy has its
`status` reset from 'on_sale' back to 'active' (and related flags cleared)
so the economic_tick no longer skips it.
"""
import os
import asyncio
import uuid
import time
import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PWD = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PWD = "Test1234!"

TEST_TAG = f"TEST_resale_{uuid.uuid4().hex[:8]}"


# ---------- helpers ----------
def _login(email, password):
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        timeout=20,
    )
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    data = r.json()
    tok = data.get("token") or data.get("access_token")
    assert tok, f"no token for {email}: {data}"
    return tok


async def _mongo():
    c = AsyncIOMotorClient(MONGO_URL)
    return c, c[DB_NAME]


@pytest.fixture(scope="module")
def tokens():
    return {
        "admin": _login(ADMIN_EMAIL, ADMIN_PWD),
        "user": _login(USER_EMAIL, USER_PWD),
    }


@pytest.fixture(scope="module")
def user_ids():
    async def _f():
        c, db = await _mongo()
        try:
            admin = await db.users.find_one({"email": ADMIN_EMAIL}, {"_id": 0, "id": 1})
            user = await db.users.find_one({"email": USER_EMAIL}, {"_id": 0, "id": 1})
            # Ensure buyer has enough TON balance
            await db.users.update_one({"email": USER_EMAIL}, {"$set": {"balance_ton": 100.0}})
            return {"admin": admin["id"], "user": user["id"]}
        finally:
            c.close()
    return asyncio.get_event_loop().run_until_complete(_f())


@pytest.fixture(scope="module")
def seeded(user_ids):
    """Seed plot+business owned by admin in a unique corner of ton_island."""
    async def _f():
        c, db = await _mongo()
        try:
            # Pick coordinates far from real gameplay
            x, y = 900 + int(time.time() % 90), 900 + int(time.time() // 60 % 90)
            plot_id = f"{TEST_TAG}_plot_{uuid.uuid4().hex[:6]}"
            biz_id = f"{TEST_TAG}_biz_{uuid.uuid4().hex[:6]}"

            plot_doc = {
                "id": plot_id,
                "city_id": "ton_island",
                "island_id": "ton_island",
                "x": x,
                "y": y,
                "owner": user_ids["admin"],
                "owner_username": "admin_test",
                "price": 2.0,
                "business_id": biz_id,
                "test_tag": TEST_TAG,
            }
            biz_doc = {
                "id": biz_id,
                "business_type": "helios",  # tier 1, produces energy, no consumption
                "owner": user_ids["admin"],
                "owner_username": "admin_test",
                "island_id": "ton_island",
                "city_id": "ton_island",
                "plot_x": x,
                "plot_y": y,
                "x": x,
                "y": y,
                "plot_id": plot_id,
                "level": 1,
                "durability": 100,
                "is_active": True,
                "status": "active",
                "storage": {"items": {}, "capacity": 1000},
                "test_tag": TEST_TAG,
            }
            await db.plots.insert_one(plot_doc.copy())
            await db.businesses.insert_one(biz_doc.copy())
            return {"plot_id": plot_id, "biz_id": biz_id, "x": x, "y": y}
        finally:
            c.close()
    yield asyncio.get_event_loop().run_until_complete(_f())
    # cleanup
    async def _cleanup():
        c, db = await _mongo()
        try:
            await db.plots.delete_many({"test_tag": TEST_TAG})
            await db.businesses.delete_many({"test_tag": TEST_TAG})
            await db.land_listings.delete_many({"seller_username": {"$in": ["admin_test"]}, "plot_id": {"$regex": f"^{TEST_TAG}"}})
            await db.land_listings.delete_many({"plot_id": {"$regex": f"^{TEST_TAG}"}})
        finally:
            c.close()
    asyncio.get_event_loop().run_until_complete(_cleanup())


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


# ---------- tests ----------
def test_1_list_business_sets_on_sale(tokens, seeded):
    """Listing a plot with a business marks the business status='on_sale'."""
    r = requests.post(
        f"{BASE_URL}/api/market/land/list",
        headers=_auth(tokens["admin"]),
        json={"plot_id": seeded["plot_id"], "price": 1.5},
        timeout=20,
    )
    assert r.status_code == 200, f"list failed: {r.status_code} {r.text}"
    data = r.json()
    listing = data["listing"]
    assert listing["status"] == "active"
    seeded["listing_id"] = listing["id"]

    async def _check():
        c, db = await _mongo()
        try:
            biz = await db.businesses.find_one({"id": seeded["biz_id"]}, {"_id": 0})
            return biz
        finally:
            c.close()

    biz = asyncio.get_event_loop().run_until_complete(_check())
    assert biz["status"] == "on_sale", f"expected on_sale, got {biz.get('status')}"
    assert biz.get("on_sale") is True
    assert biz.get("listing_id") == listing["id"]


def test_2_tick_skips_on_sale_business(seeded):
    """Regression: while listed, the tick must SKIP the business (no last_wear_update)."""
    import sys
    sys.path.insert(0, "/app/backend")
    # Ensure no last_wear_update before tick
    async def _prep_and_tick():
        c, db = await _mongo()
        try:
            await db.businesses.update_one(
                {"id": seeded["biz_id"]},
                {"$unset": {"last_wear_update": "", "last_tick": ""}},
            )
            # Run tick
            import background_tasks as bt
            # Use the real running app's db (bt imports db from server) -- so we
            # must ensure bt.db points to same DB_NAME. It does (server.py env).
            await bt.economic_tick()
            biz = await db.businesses.find_one({"id": seeded["biz_id"]}, {"_id": 0})
            return biz
        finally:
            c.close()

    biz = asyncio.get_event_loop().run_until_complete(_prep_and_tick())
    # Business is on_sale -> tick continues past it. last_wear_update must NOT be set.
    assert biz["status"] == "on_sale"
    assert biz.get("last_wear_update") is None, (
        f"tick should have skipped on_sale business but last_wear_update={biz.get('last_wear_update')}"
    )


def test_3_buy_resets_status_and_owner(tokens, seeded, user_ids):
    """Buying transfers ownership AND resets status='active' + clears on_sale flags."""
    listing_id = seeded["listing_id"]
    r = requests.post(
        f"{BASE_URL}/api/market/land/buy",
        headers=_auth(tokens["user"]),
        json={"listing_id": listing_id},
        timeout=30,
    )
    assert r.status_code == 200, f"buy failed: {r.status_code} {r.text}"

    async def _check():
        c, db = await _mongo()
        try:
            biz = await db.businesses.find_one({"id": seeded["biz_id"]}, {"_id": 0})
            plot = await db.plots.find_one({"id": seeded["plot_id"]}, {"_id": 0})
            return biz, plot
        finally:
            c.close()

    biz, plot = asyncio.get_event_loop().run_until_complete(_check())
    # THE FIX assertions:
    assert biz["status"] == "active", f"business status not reset: {biz.get('status')}"
    assert not biz.get("on_sale"), f"on_sale flag not cleared: {biz.get('on_sale')}"
    assert biz.get("is_active") is True
    assert biz.get("work_status") == "idle"
    assert biz.get("owner") == user_ids["user"], f"owner mismatch: {biz.get('owner')}"
    assert plot.get("owner") == user_ids["user"]
    assert not plot.get("on_sale")


def test_4_tick_processes_purchased_business(seeded):
    """After purchase, tick must NOT skip the business (last_wear_update advances)."""
    import sys
    sys.path.insert(0, "/app/backend")

    async def _run():
        c, db = await _mongo()
        try:
            # Clear timers to detect the first write from tick
            await db.businesses.update_one(
                {"id": seeded["biz_id"]},
                {"$unset": {"last_wear_update": "", "last_tick": ""}},
            )
            import background_tasks as bt
            await bt.economic_tick()
            biz = await db.businesses.find_one({"id": seeded["biz_id"]}, {"_id": 0})
            return biz
        finally:
            c.close()

    biz = asyncio.get_event_loop().run_until_complete(_run())
    assert biz["status"] == "active"
    # Key regression assertion: tick actually processed this business
    assert biz.get("last_wear_update") is not None, (
        "economic_tick still SKIPPED the purchased business — bug not fixed"
    )
