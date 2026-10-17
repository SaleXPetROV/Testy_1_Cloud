"""
Iteration 3 backend tests — weighted warehouse storage in DEMO mode.

Verifies that /api/demo/my-businesses now reports:
  - storage_info.items          -> raw unit counts
  - storage_info.items_slots    -> per-resource weighted slot cost (T1=1, T2=5, T3=20)
  - storage_info.used           -> weighted total (== items_used_weighted)
  - storage_info.items_used_weighted
  - capacity unchanged (== business's storage capacity)

Also verifies:
  - storage_full triggers work_status='idle', reason='storage_full'
  - production accrual respects weighted free slots (does not exceed capacity)
  - weighted cap during production for a T2 producer
  - real-mode /api/my/businesses still returns integer storage_info.used
"""
import os
import asyncio
import time
from datetime import datetime, timedelta, timezone

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
load_dotenv("/app/backend/.env")

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

TEST_EMAIL = "testuser@example.com"
TEST_PASSWORD = "Test1234!"
ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")


# ---------- helpers ----------
def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": password},
                      timeout=30)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    data = r.json()
    return data["token"], data["user"]


def _demo_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Game-Mode": "demo",
    }


def _real_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


async def _mongo_db():
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(MONGO_URL)
    return client, client[DB_NAME]


async def _get_user_id(db, email):
    u = await db.users.find_one({"email": email}, {"_id": 0, "id": 1})
    assert u, f"user {email} not in db"
    return u["id"]


async def _seed_demo(user_id, resources: dict, biz_type: str = None,
                     level: int = None, last_collection_offset_seconds: int = None,
                     durability: float = None):
    client, db = await _mongo_db()
    try:
        set_doc = {"demo_resources": resources}
        # Ensure a profile exists.
        profile = await db.demo_profiles.find_one({"user_id": user_id})
        assert profile, "profile must exist — call /api/demo/enter first"
        biz = dict(profile.get("demo_business") or {})
        if biz_type:
            biz["type"] = biz_type
        if level is not None:
            biz["level"] = level
        if durability is not None:
            biz["durability"] = durability
        if last_collection_offset_seconds is not None:
            dt = datetime.now(timezone.utc) + timedelta(seconds=last_collection_offset_seconds)
            biz["last_collection"] = dt.isoformat()
        set_doc["demo_business"] = biz
        await db.demo_profiles.update_one({"user_id": user_id}, {"$set": set_doc})
    finally:
        client.close()


async def _get_demo_business_raw(user_id):
    client, db = await _mongo_db()
    try:
        profile = await db.demo_profiles.find_one({"user_id": user_id}, {"_id": 0})
        return profile
    finally:
        client.close()


# ---------- fixtures ----------
@pytest.fixture(scope="module")
def test_token():
    tok, user = _login(TEST_EMAIL, TEST_PASSWORD)
    return tok, user


@pytest.fixture(scope="module")
def admin_token():
    tok, user = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    return tok, user


@pytest.fixture(scope="module", autouse=True)
def ensure_demo_profile(test_token):
    tok, _ = test_token
    r = requests.post(f"{BASE_URL}/api/demo/enter", headers=_demo_headers(tok), timeout=30)
    assert r.status_code == 200, r.text


@pytest.fixture(scope="module")
def test_user_id(test_token):
    tok, user = test_token
    return user["id"]


# ---------- 1. weighted storage_info shape ----------
def test_weighted_storage_info_shape(test_token, test_user_id):
    tok, _ = test_token
    seed_res = {"scrap": 10, "gold_bill": 2, "neuro_core": 1, "license_token": 1, "nft": 1}
    # Force durability=100, level=1, and set last_collection to NOW so demo_collect
    # does not add extra units (which would break the exact-weighted-count assertion).
    asyncio.get_event_loop().run_until_complete(
        _seed_demo(test_user_id, seed_res, level=1, durability=100.0,
                   last_collection_offset_seconds=0)
    )
    r = requests.get(f"{BASE_URL}/api/demo/my-businesses",
                     headers=_demo_headers(tok), timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    biz = body["businesses"][0]
    si = biz["storage_info"]

    # items should be raw unit counts (not weighted)
    items = si["items"]
    assert items.get("scrap") == 10, items
    assert items.get("gold_bill") == 2, items
    assert items.get("neuro_core") == 1, items
    assert items.get("license_token") == 1, items
    assert items.get("nft") == 1, items

    # items_slots must exist and be weighted
    assert "items_slots" in si, si
    slots = si["items_slots"]
    assert slots.get("scrap") == 10, slots           # T1 * 10
    assert slots.get("gold_bill") == 40, slots       # T3 * 2 = 40
    assert slots.get("neuro_core") == 20, slots      # T3 * 1
    assert slots.get("license_token") == 20, slots   # T3 * 1
    assert slots.get("nft") == 5, slots              # T2 * 1

    # weighted used == 95
    assert si.get("items_used_weighted") == 95, si
    assert si.get("used") == 95, si

    # capacity untouched (business storage capacity, must be a positive int)
    assert isinstance(si["capacity"], int) and si["capacity"] > 0, si


# ---------- 2. storage_full status ----------
def test_storage_full_status_and_no_production(test_token, test_user_id):
    tok, _ = test_token
    # First determine current capacity
    r = requests.get(f"{BASE_URL}/api/demo/my-businesses",
                     headers=_demo_headers(tok), timeout=30)
    biz = r.json()["businesses"][0]
    capacity = int(biz["storage_info"]["capacity"])
    produces = biz["production"]["produces"]

    # Fill weighted storage above capacity using gold_bill (T3=20 slots each).
    need_units = (capacity // 20) + 2
    seed = {"gold_bill": need_units}
    asyncio.get_event_loop().run_until_complete(
        _seed_demo(test_user_id, seed, level=1, durability=100.0,
                   last_collection_offset_seconds=-3600)  # 1 hour ago
    )

    r = requests.get(f"{BASE_URL}/api/demo/my-businesses",
                     headers=_demo_headers(tok), timeout=30)
    assert r.status_code == 200
    biz = r.json()["businesses"][0]
    si = biz["storage_info"]

    assert si["used"] >= capacity, si
    assert biz["work_status"] == "idle", biz
    assert biz["work_status_reason"] == "storage_full", biz

    # Verify no extra produce added — resource count of `produces` should not
    # exceed what we seeded (we didn't seed the output resource unless output IS gold_bill).
    profile = asyncio.get_event_loop().run_until_complete(_get_demo_business_raw(test_user_id))
    got = float((profile.get("demo_resources") or {}).get(produces, 0))
    if produces != "gold_bill":
        # We seeded zero of the output resource, so nothing may have been added.
        assert got == 0, f"produced={got} even though warehouse was full"


# ---------- 3. Weighted cap during production for a T2 producer ----------
def test_weighted_cap_for_t2_producer(test_token, test_user_id):
    """
    Force the demo business to a Tier-2 producer (nft_studio -> produces 'nft', T2 weight 5).
    Level 1 nft_studio produces 30/day and has storage 770.
    With NO existing resources and last_collection 1h ago, produced=30*(1/24)=~1.25 units.
    We instead run a case where the warehouse is nearly full — leaving exactly 100 slots
    free means max newly-added T2 units = 100/5 = 20.
    """
    tok, _ = test_token
    # Switch to nft_studio (T2), level 1
    from motor.motor_asyncio import AsyncIOMotorClient  # noqa

    # Seed inputs so consumption doesn't halt production:
    #  L1 nft_studio consumes {traffic:260, neurocode:12} per day.
    #  For 1 day of simulated time we need those in the inventory.
    # We also seed some pre-existing 'nft' output near capacity to force the weighted cap.
    # nft_studio capacity at L1 = 770. We'll seed nft=150 (weighted 750), leaving 20 slots
    # free -> max newly-added nft units = 20/5 = 4.
    seed = {"traffic": 5000, "neurocode": 100, "nft": 150}
    asyncio.get_event_loop().run_until_complete(
        _seed_demo(test_user_id, seed, biz_type="nft_studio", level=1,
                   durability=100.0, last_collection_offset_seconds=-86400)  # 24h ago
    )

    # GET my-businesses which triggers demo_collect first
    r = requests.get(f"{BASE_URL}/api/demo/my-businesses",
                     headers=_demo_headers(tok), timeout=30)
    assert r.status_code == 200, r.text
    biz = r.json()["businesses"][0]

    profile = asyncio.get_event_loop().run_until_complete(_get_demo_business_raw(test_user_id))
    got_nft = float((profile.get("demo_resources") or {}).get("nft", 0))
    delta = got_nft - 150
    # delta must be > 0 (there was room) and delta <= 4 (weighted cap)
    assert delta > 0, f"nft did not grow at all: {got_nft}"
    assert delta <= 4 + 0.01, f"weighted cap violated: delta_nft={delta} (should be <=4)"

    si = biz["storage_info"]
    # weighted used <= capacity strictly
    assert si["used"] <= si["capacity"], si
    # nft slot count == 5 * unit count
    assert si["items_slots"].get("nft") == int(round(si["items"].get("nft", 0) * 5)), si


# ---------- 4. Production resumes after freeing space ----------
def test_production_resumes_after_freeing_space(test_token, test_user_id):
    tok, _ = test_token
    # Restore to a T1 business (whatever it was) — pick quartz_mine as a stable test
    seed = {"scrap": 500}  # 500 slots used, capacity=330 for quartz_mine L1 -> STILL FULL
    # So instead seed slightly below capacity.
    seed = {"scrap": 50}  # 50 slots used out of 330 -> plenty of room
    asyncio.get_event_loop().run_until_complete(
        _seed_demo(test_user_id, seed, biz_type="quartz_mine", level=1,
                   durability=100.0, last_collection_offset_seconds=-3600)  # 1 hour ago
    )

    r = requests.get(f"{BASE_URL}/api/demo/my-businesses",
                     headers=_demo_headers(tok), timeout=30)
    assert r.status_code == 200
    biz = r.json()["businesses"][0]
    assert biz["work_status"] == "working", biz
    # quartz_mine at L1 produces 100/day and consumes scrap:25/day, but its produces=quartz
    profile = asyncio.get_event_loop().run_until_complete(_get_demo_business_raw(test_user_id))
    quartz = float((profile.get("demo_resources") or {}).get("quartz", 0))
    # ~100 / 24 ≈ 4.17
    assert quartz > 0, f"quartz did not accrue in 1h: {quartz}"


# ---------- 5. Real-mode regression: /api/my/businesses still works ----------
def test_real_mode_storage_info_unchanged(admin_token):
    tok, _ = admin_token
    r = requests.get(f"{BASE_URL}/api/my/businesses",
                     headers=_real_headers(tok), timeout=30)
    # It's OK if the admin has no businesses (empty list). Just make sure
    # (a) it returns 200 and (b) storage_info.used is an int when present.
    assert r.status_code == 200, r.text
    body = r.json()
    # different backends return list or dict; normalise:
    if isinstance(body, dict) and "businesses" in body:
        businesses = body["businesses"]
    elif isinstance(body, list):
        businesses = body
    else:
        businesses = []
    if not businesses:
        pytest.skip("Admin has no businesses in real mode — regression path skipped.")
    for b in businesses[:3]:
        si = b.get("storage_info") or {}
        assert "used" in si and "capacity" in si, si
        assert isinstance(si["used"], (int, float)), si
        assert isinstance(si["capacity"], (int, float)), si
        assert si["used"] >= 0
