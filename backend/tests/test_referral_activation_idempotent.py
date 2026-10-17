"""
Referral activation bonus idempotency (bugfix verification).

Verifies the fix in promo_service.maybe_pay_activation_bonus so that the
1.5 TON referrer bonus is paid EXACTLY ONCE per invitee, even across multiple
land purchases by that invitee. Uses the REAL /api/island/buy HTTP path.
"""
import os
import sys
import time
import uuid
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
import requests
from dotenv import load_dotenv

# Ensure backend .env is loaded for MONGO_URL/DB_NAME
load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")

sys.path.insert(0, "/app/backend")
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

INVITEE_EMAIL = "testuser@example.com"
INVITEE_PASS = "Test1234!"

REFERRER_ID = f"TEST_REF_{uuid.uuid4().hex[:8]}"
REFERRER_USERNAME = f"test_referrer_{uuid.uuid4().hex[:6]}"

CAMPAIGN_IDS: list[str] = []
PLOT_IDS_BOUGHT: list[str] = []
PLOT_COORDS_BOUGHT: list[tuple[int, int]] = []


# ────────────────────────── helpers ──────────────────────────
def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
def db():
    client = AsyncIOMotorClient(MONGO_URL)
    return client[DB_NAME]


@pytest.fixture(scope="module")
def invitee_token():
    r = requests.post(f"{API}/auth/login", json={"email": INVITEE_EMAIL, "password": INVITEE_PASS}, timeout=15)
    assert r.status_code == 200, f"login failed {r.status_code} {r.text}"
    data = r.json()
    tok = data.get("access_token") or data.get("token")
    assert tok, f"no token in {data}"
    return tok


@pytest.fixture(scope="module")
def invitee_id(db):
    async def _fetch():
        u = await db.users.find_one({"email": INVITEE_EMAIL}, {"_id": 0, "id": 1})
        return u and u.get("id")
    uid = run(_fetch())
    assert uid, "testuser id not found"
    return uid


async def _seed_referrer(db):
    await db.users.delete_many({"id": REFERRER_ID})
    await db.users.insert_one({
        "id": REFERRER_ID,
        "username": REFERRER_USERNAME,
        "email": f"{REFERRER_USERNAME}@test.local",
        "balance_ton": 0.0,
        "hashed_password": "$2b$12$placeholder_not_used_for_login",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "referralBonusEarned": 0.0,
    })


async def _seed_campaign(db) -> str:
    cid = f"TEST_CAMP_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    await db.promo_campaigns.insert_one({
        "id": cid,
        "type": "referral_rally",
        "status": "active",
        "starts_at": now.isoformat(),
        "ends_at": (now + timedelta(days=7)).isoformat(),
        "frozen_at": None,
        "config": {"prizes_ton": [100, 50, 20], "per_active_ton": 1.5},
        "winners": [],
        "created_at": now.isoformat(),
    })
    CAMPAIGN_IDS.append(cid)
    return cid


async def _prep_invitee(db, invitee_id):
    # Delete any prior test plots owned by invitee. Delete any prior
    # referral_activation tx for invitee. Reset flag and plots_owned.
    await db.transactions.delete_many({"tx_type": "referral_activation_bonus", "referred_user_id": invitee_id})
    await db.plots.delete_many({"owner": invitee_id})
    await db.users.update_one(
        {"id": invitee_id},
        {
            "$set": {
                "referrerId": REFERRER_ID,
                "plots_owned": [],
                "balance_ton": 500.0,
                "tutorial_active": False,
                "tutorial_completed": True,
            },
            "$unset": {"referral_activation_paid": "", "referral_activation_paid_at": ""},
        },
    )


async def _find_free_cheap_cells(db, want=2):
    """Return up to `want` (x,y) tuples for empty, un-owned outskirts cells."""
    island = await db.islands.find_one({"id": "ton_island"}, {"_id": 0})
    if not island:
        return []
    taken = set()
    async for p in db.plots.find({"island_id": "ton_island", "owner": {"$type": "string"}}, {"_id": 0, "x": 1, "y": 1}):
        taken.add((p["x"], p["y"]))
    # Prefer is_empty cells (no pre_business complications) sorted by price
    cells = [c for c in island["cells"] if c.get("is_empty") and (c["x"], c["y"]) not in taken]
    cells.sort(key=lambda c: (c.get("price_ton", 999), abs(c["x"] - 50) + abs(c["y"] - 50)))
    picked = []
    for c in cells:
        picked.append((c["x"], c["y"]))
        if len(picked) >= want:
            break
    return picked


# ────────────────────────── tests ──────────────────────────
def test_primary_bonus_paid_exactly_once(db, invitee_token, invitee_id):
    """PRIMARY: two plot purchases → referrer +1.5 total, ONE bonus tx."""
    run(_seed_referrer(db))
    run(_seed_campaign(db))
    run(_prep_invitee(db, invitee_id))

    coords = run(_find_free_cheap_cells(db, want=2))
    assert len(coords) >= 2, f"need 2 free plots, got {coords}"

    headers = {"Authorization": f"Bearer {invitee_token}"}
    for (x, y) in coords[:2]:
        r = requests.post(f"{API}/island/buy/{x}/{y}", headers=headers, timeout=20)
        assert r.status_code == 200, f"buy ({x},{y}) failed: {r.status_code} {r.text}"
        PLOT_COORDS_BOUGHT.append((x, y))
        try:
            body = r.json()
            pid = (body.get("plot") or {}).get("id") or body.get("id")
            if pid:
                PLOT_IDS_BOUGHT.append(pid)
        except Exception:
            pass

    # Assertions on DB
    async def _check():
        ref = await db.users.find_one({"id": REFERRER_ID}, {"_id": 0, "balance_ton": 1})
        tx_count = await db.transactions.count_documents({
            "tx_type": "referral_activation_bonus",
            "referred_user_id": invitee_id,
        })
        invitee = await db.users.find_one({"id": invitee_id}, {"_id": 0, "referral_activation_paid": 1, "plots_owned": 1})
        return ref, tx_count, invitee

    ref, tx_count, invitee = run(_check())
    assert ref is not None, "referrer doc missing"
    assert abs(float(ref.get("balance_ton", 0.0)) - 1.5) < 1e-6, (
        f"expected referrer balance_ton==1.5, got {ref.get('balance_ton')}; tx_count={tx_count}"
    )
    assert tx_count == 1, f"expected exactly 1 referral_activation_bonus tx, got {tx_count}"
    assert invitee.get("referral_activation_paid") is True, "flag should be set on invitee"
    assert len(invitee.get("plots_owned") or []) >= 2, "invitee should have 2 plots"


def test_secondary_no_bonus_without_active_campaign(db, invitee_token, invitee_id):
    """SECONDARY: campaign expired → no bonus paid on next purchase."""
    async def _prep():
        # Expire ALL test campaigns
        for cid in CAMPAIGN_IDS:
            await db.promo_campaigns.update_one({"id": cid}, {"$set": {"status": "finished"}})
        # Also, defensive: mark any lingering rally campaigns as finished
        await db.promo_campaigns.update_many(
            {"type": "referral_rally", "status": "active"},
            {"$set": {"status": "finished"}},
        )
        # Reset invitee: clear flag, plots_owned, delete prior bonus tx, delete plots
        await db.transactions.delete_many({"tx_type": "referral_activation_bonus", "referred_user_id": invitee_id})
        await db.plots.delete_many({"owner": invitee_id})
        await db.users.update_one(
            {"id": invitee_id},
            {"$set": {"plots_owned": [], "balance_ton": 500.0},
             "$unset": {"referral_activation_paid": ""}},
        )
    run(_prep())

    # Record referrer balance BEFORE
    async def _bal():
        d = await db.users.find_one({"id": REFERRER_ID}, {"_id": 0, "balance_ton": 1})
        return float(d.get("balance_ton", 0.0)) if d else 0.0
    bal_before = run(_bal())

    coords = run(_find_free_cheap_cells(db, want=1))
    assert coords, "no free cell for secondary test"
    x, y = coords[0]
    headers = {"Authorization": f"Bearer {invitee_token}"}
    r = requests.post(f"{API}/island/buy/{x}/{y}", headers=headers, timeout=20)
    assert r.status_code == 200, f"buy failed: {r.status_code} {r.text}"
    PLOT_COORDS_BOUGHT.append((x, y))

    bal_after = run(_bal())
    assert abs(bal_after - bal_before) < 1e-9, (
        f"referrer balance changed without active campaign: {bal_before} -> {bal_after}"
    )
    # Also assert no new bonus tx exists
    async def _tx():
        return await db.transactions.count_documents({
            "tx_type": "referral_activation_bonus", "referred_user_id": invitee_id,
        })
    tx_ct = run(_tx())
    assert tx_ct == 0, f"unexpected referral bonus tx after campaign expiry: {tx_ct}"


def test_zzz_cleanup(db, invitee_id):
    """CLEANUP: remove test referrer, campaigns, bonus txs, test plots,
    restore testuser to clean state."""
    async def _cleanup():
        # Delete test referrer
        await db.users.delete_many({"id": REFERRER_ID})
        # Delete test campaigns
        for cid in CAMPAIGN_IDS:
            await db.promo_campaigns.delete_many({"id": cid})
        # Delete any lingering test bonus txs for this invitee
        await db.transactions.delete_many({"tx_type": "referral_activation_bonus", "referred_user_id": invitee_id})
        # Delete plots we bought (by coords and by owner)
        await db.plots.delete_many({"owner": invitee_id})
        for (x, y) in PLOT_COORDS_BOUGHT:
            await db.plots.delete_many({"island_id": "ton_island", "x": x, "y": y})
        # Restore invitee
        await db.users.update_one(
            {"id": invitee_id},
            {
                "$set": {
                    "balance_ton": 100.0,
                    "plots_owned": [],
                    "wallet_address": None,
                    "tutorial_active": False,
                    "tutorial_completed": True,
                },
                "$unset": {
                    "referrerId": "",
                    "referral_activation_paid": "",
                    "referral_activation_paid_at": "",
                },
            },
        )
        # Also delete businesses linked to those plots (if any)
        for (x, y) in PLOT_COORDS_BOUGHT:
            await db.businesses.delete_many({"island_id": "ton_island", "x": x, "y": y, "owner": invitee_id})
    run(_cleanup())

    # sanity: verify
    async def _verify():
        return (
            await db.users.find_one({"id": REFERRER_ID}),
            await db.transactions.count_documents({"tx_type": "referral_activation_bonus", "referred_user_id": invitee_id}),
        )
    ref_doc, ct = run(_verify())
    assert ref_doc is None
    assert ct == 0
