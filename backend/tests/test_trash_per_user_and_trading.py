"""
Iteration 2 backend tests for the PER-USER Trash Piles rewrite + Trading
gate removal.

Covers:
  * /api/trash/list is scoped to caller; fresh user gets exactly 1 pile.
  * /api/trash/{id}/scan returns reward_resource + reward_qty, foreign scan 403,
    daily-timer growth 600,1200,2400,4800,10800 and 6th → 429.
  * /api/trash/{id}/collect only works when ready (else 425); on success it
    deposits into user.resources (NOT personal_warehouse) and deletes the pile.
    Warehouse capacity=50 enforced for no-business player.
  * /api/my/businesses summary.total_warehouse_capacity == 50 for no-business.
  * /api/market/list-resource works for no-business user, 2nd listing blocked.
  * /api/market/my-listings slot_info.max == 1 for no-business.
  * /api/market/buy no longer returns the old 'no_business_required_for_action'
    gating — returns normal errors.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone, timedelta

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL must be set for tests"

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PASSWORD = "Test1234!"


# ----------------------------- helpers -----------------------------
def _login(email: str, password: str):
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        timeout=15,
    )
    assert r.status_code == 200, f"Login failed for {email}: {r.status_code} {r.text}"
    body = r.json()
    tok = body.get("token") or body.get("access_token")
    return tok, body.get("user", {})


def _run(coro_fn):
    """Run an async lambda(db) on a fresh event loop with a fresh Motor client."""
    from motor.motor_asyncio import AsyncIOMotorClient

    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "test_database")
    loop = asyncio.new_event_loop()
    try:
        async def _inner():
            client = AsyncIOMotorClient(mongo_url)
            try:
                return await coro_fn(client[db_name])
            finally:
                client.close()

        return loop.run_until_complete(_inner())
    finally:
        loop.close()


async def _reset_user_trash(db, user_id: str) -> None:
    await db.trash_piles.delete_many({"user_id": user_id})
    await db.users.update_one(
        {"id": user_id},
        {"$unset": {"trash_initialized": "", "trash_scan_daily": ""}},
    )


async def _clear_market_for_user(db, user_id: str) -> None:
    await db.market_listings.delete_many({"seller_id": user_id})


# ----------------------------- fixtures -----------------------------
@pytest.fixture(scope="module")
def admin_auth():
    tok, u = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    return {"token": tok, "user": u, "headers": {"Authorization": f"Bearer {tok}"}}


@pytest.fixture(scope="module")
def user_auth():
    tok, u = _login(USER_EMAIL, USER_PASSWORD)
    return {"token": tok, "user": u, "headers": {"Authorization": f"Bearer {tok}"}}


# ============================================================
# Trash: /list per-user and lazy spawn
# ============================================================
class TestTrashListPerUser:
    def test_fresh_user_gets_exactly_one_pile(self, user_auth):
        user_id = user_auth["user"]["id"]
        _run(lambda d: _reset_user_trash(d, user_id))

        r = requests.get(
            f"{BASE_URL}/api/trash/list", headers=user_auth["headers"], timeout=15
        )
        assert r.status_code == 200, r.text
        piles = r.json().get("piles", [])
        assert isinstance(piles, list)
        assert len(piles) == 1, f"Fresh user should get exactly 1 pile, got {len(piles)}"
        p = piles[0]
        assert p["status"] == "active"
        assert "reward_resource" not in p  # hidden on active
        assert "reward_qty" not in p

    def test_list_scoped_to_caller(self, user_auth, admin_auth):
        # user's pile must not appear in admin's list
        user_piles = requests.get(
            f"{BASE_URL}/api/trash/list", headers=user_auth["headers"], timeout=15
        ).json()["piles"]
        admin_piles = requests.get(
            f"{BASE_URL}/api/trash/list", headers=admin_auth["headers"], timeout=15
        ).json()["piles"]
        user_ids = {p["id"] for p in user_piles}
        admin_ids = {p["id"] for p in admin_piles}
        assert user_ids.isdisjoint(admin_ids), "Piles must be scoped per user"


# ============================================================
# Trash: /scan reward + foreign 403 + daily timer ladder
# ============================================================
class TestTrashScan:
    def test_scan_returns_reward_and_600s(self, user_auth):
        user_id = user_auth["user"]["id"]
        _run(lambda d: _reset_user_trash(d, user_id))

        piles = requests.get(
            f"{BASE_URL}/api/trash/list", headers=user_auth["headers"], timeout=15
        ).json()["piles"]
        assert piles and piles[0]["status"] == "active"
        pile_id = piles[0]["id"]

        r = requests.post(
            f"{BASE_URL}/api/trash/{pile_id}/scan",
            headers=user_auth["headers"],
            timeout=15,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "processing"
        assert data["scan_duration_sec"] == 600
        assert "ready_at" in data
        assert data.get("reward_resource")
        assert int(data.get("reward_qty") or 0) >= 1

    def test_foreign_scan_returns_403(self, user_auth, admin_auth):
        """Admin tries to scan the user's active pile → 403."""
        user_id = user_auth["user"]["id"]
        _run(lambda d: _reset_user_trash(d, user_id))
        # get user's freshly spawned active pile
        user_piles = requests.get(
            f"{BASE_URL}/api/trash/list", headers=user_auth["headers"], timeout=15
        ).json()["piles"]
        active = [p for p in user_piles if p["status"] == "active"]
        assert active
        pid = active[0]["id"]
        r = requests.post(
            f"{BASE_URL}/api/trash/{pid}/scan",
            headers=admin_auth["headers"],
            timeout=15,
        )
        assert r.status_code == 403, f"Expected 403 foreign-scan, got {r.status_code}: {r.text}"

    def test_daily_scan_ladder_and_429(self, user_auth):
        user_id = user_auth["user"]["id"]
        expected = [600, 1200, 2400, 4800, 10800]
        # Prime: reset user; then for each expected duration, spawn a fresh
        # active pile, scan it, and assert scan_duration_sec == expected[i].
        _run(lambda d: _reset_user_trash(d, user_id))

        # We can't call the admin refill (it iterates all users). Instead we
        # directly insert extra active piles into MongoDB for this user, then
        # scan them one after another.
        async def _seed_extra_piles(d):
            # remove any active piles first (keep processing/ready from previous run)
            await d.trash_piles.delete_many({"user_id": user_id, "status": "active"})
            # Ensure at least 5 free active piles are available:
            for i in range(6):
                await d.trash_piles.insert_one({
                    "id": f"TEST_pile_{i}_{user_id}",
                    "user_id": user_id,
                    "x": 100 + i,   # arbitrary coordinates (do not collide with real cells)
                    "y": 100 + i,
                    "status": "active",
                    "spawned_at": datetime.now(timezone.utc).isoformat(),
                    "scanned_by": None,
                    "scan_started_at": None,
                    "scan_duration_sec": None,
                    "ready_at": None,
                    "reward_resource": "biomass",
                    "reward_qty": 1,
                })
            # clear streak
            await d.users.update_one(
                {"id": user_id}, {"$unset": {"trash_scan_daily": ""}}
            )

        _run(_seed_extra_piles)

        for i, dur in enumerate(expected):
            pid = f"TEST_pile_{i}_{user_id}"
            r = requests.post(
                f"{BASE_URL}/api/trash/{pid}/scan",
                headers=user_auth["headers"],
                timeout=15,
            )
            assert r.status_code == 200, f"scan #{i+1} failed: {r.status_code} {r.text}"
            data = r.json()
            assert data["scan_duration_sec"] == dur, (
                f"scan #{i+1}: expected {dur}s, got {data['scan_duration_sec']}"
            )

        # 6th scan → 429
        pid6 = f"TEST_pile_5_{user_id}"
        r = requests.post(
            f"{BASE_URL}/api/trash/{pid6}/scan",
            headers=user_auth["headers"],
            timeout=15,
        )
        assert r.status_code == 429, f"Expected 429 on 6th scan, got {r.status_code}: {r.text}"

        # cleanup test piles
        _run(lambda d: d.trash_piles.delete_many({"id": {"$regex": f"^TEST_pile_.*_{user_id}$"}}))


# ============================================================
# Trash: /collect
# ============================================================
class TestTrashCollect:
    def test_collect_before_ready_returns_425(self, user_auth):
        user_id = user_auth["user"]["id"]
        _run(lambda d: _reset_user_trash(d, user_id))

        piles = requests.get(
            f"{BASE_URL}/api/trash/list", headers=user_auth["headers"], timeout=15
        ).json()["piles"]
        pid = piles[0]["id"]
        sr = requests.post(
            f"{BASE_URL}/api/trash/{pid}/scan",
            headers=user_auth["headers"],
            timeout=15,
        )
        assert sr.status_code == 200, sr.text

        cr = requests.post(
            f"{BASE_URL}/api/trash/{pid}/collect",
            headers=user_auth["headers"],
            timeout=15,
        )
        assert cr.status_code == 425, f"Expected 425, got {cr.status_code}: {cr.text}"

    def test_collect_ready_deposits_into_user_resources(self, user_auth):
        user_id = user_auth["user"]["id"]
        _run(lambda d: _reset_user_trash(d, user_id))
        # Zero-out user resources for a clean assertion
        _run(lambda d: d.users.update_one({"id": user_id}, {"$set": {"resources": {}}}))

        piles = requests.get(
            f"{BASE_URL}/api/trash/list", headers=user_auth["headers"], timeout=15
        ).json()["piles"]
        pid = piles[0]["id"]
        sr = requests.post(
            f"{BASE_URL}/api/trash/{pid}/scan",
            headers=user_auth["headers"],
            timeout=15,
        )
        assert sr.status_code == 200
        reward_resource = sr.json()["reward_resource"]
        reward_qty = int(sr.json()["reward_qty"])

        # Force ready_at into the past
        past = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
        _run(lambda d: d.trash_piles.update_one({"id": pid}, {"$set": {"ready_at": past}}))

        cr = requests.post(
            f"{BASE_URL}/api/trash/{pid}/collect",
            headers=user_auth["headers"],
            timeout=15,
        )
        assert cr.status_code == 200, cr.text
        data = cr.json()
        assert data["success"] is True
        assert data["resource"] == reward_resource
        assert data["qty"] == reward_qty
        assert data["warehouse_capacity"] == 50, (
            f"No-business player must have warehouse capacity == 50, got {data['warehouse_capacity']}"
        )

        # Reward must land in user.resources (NOT personal_warehouse.items)
        user_doc = _run(lambda d: d.users.find_one({"id": user_id}, {"_id": 0}))
        resources_val = int((user_doc.get("resources") or {}).get(reward_resource) or 0)
        assert resources_val >= reward_qty, (
            f"Reward {reward_resource} x{reward_qty} not deposited to user.resources; got {resources_val}"
        )
        # personal_warehouse should NOT contain the reward
        pw_items = (user_doc.get("personal_warehouse") or {}).get("items") or {}
        assert int(pw_items.get(reward_resource) or 0) == 0, (
            "Reward must NOT go into personal_warehouse anymore"
        )

        # Pile must be deleted
        gone = _run(lambda d: d.trash_piles.find_one({"id": pid}))
        assert gone is None, "Pile should be deleted after collect"

    def test_collect_warehouse_full_returns_409(self, user_auth):
        user_id = user_auth["user"]["id"]
        _run(lambda d: _reset_user_trash(d, user_id))
        # Fill warehouse to exactly 50 slots using tier-1 (weight 1 each)
        _run(lambda d: d.users.update_one(
            {"id": user_id},
            {"$set": {"resources": {"biomass": 50}}},
        ))

        piles = requests.get(
            f"{BASE_URL}/api/trash/list", headers=user_auth["headers"], timeout=15
        ).json()["piles"]
        pid = piles[0]["id"]
        sr = requests.post(
            f"{BASE_URL}/api/trash/{pid}/scan",
            headers=user_auth["headers"],
            timeout=15,
        )
        assert sr.status_code == 200
        past = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
        _run(lambda d: d.trash_piles.update_one({"id": pid}, {"$set": {"ready_at": past}}))

        cr = requests.post(
            f"{BASE_URL}/api/trash/{pid}/collect",
            headers=user_auth["headers"],
            timeout=15,
        )
        assert cr.status_code == 409, f"Expected 409 warehouse_full, got {cr.status_code}: {cr.text}"
        detail = cr.json().get("detail") or {}
        code = detail.get("code") if isinstance(detail, dict) else None
        assert code == "warehouse_full", f"Expected code=warehouse_full, got {cr.json()}"

        # cleanup
        _run(lambda d: d.users.update_one({"id": user_id}, {"$set": {"resources": {}}}))


# ============================================================
# /my/businesses summary.total_warehouse_capacity == 50 (no business)
# ============================================================
class TestBusinessSummaryCapacity:
    def test_no_business_capacity_is_50(self, user_auth):
        """The no-business testuser should see warehouse capacity == 50."""
        r = requests.get(
            f"{BASE_URL}/api/my/businesses",
            headers=user_auth["headers"],
            timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        summary = body.get("summary") or {}
        # Sanity check: the caller has no real businesses
        real = [b for b in body.get("businesses", []) if not b.get("tutorial")]
        assert len(real) == 0, f"testuser should have no real businesses, got {real}"
        assert summary.get("total_warehouse_capacity") == 50, (
            f"Expected total_warehouse_capacity=50, got {summary.get('total_warehouse_capacity')}"
        )


# ============================================================
# Market: list-resource + my-listings + buy for no-business user
# ============================================================
class TestMarketNoBusinessSell:
    def test_no_business_can_list_resource(self, user_auth):
        user_id = user_auth["user"]["id"]
        # Prepare: clear existing listings, give the user 30 biomass
        _run(lambda d: _clear_market_for_user(d, user_id))
        _run(lambda d: d.users.update_one(
            {"id": user_id}, {"$set": {"resources": {"biomass": 30}}}
        ))

        payload = {"resource_type": "biomass", "amount": 10, "price_per_unit": 0.01}
        r = requests.post(
            f"{BASE_URL}/api/market/list-resource",
            json=payload,
            headers=user_auth["headers"],
            timeout=15,
        )
        assert r.status_code == 200, f"Listing failed: {r.status_code} {r.text}"
        # Response must not carry the removed gate code
        body_str = str(r.json())
        assert "no_business_required" not in body_str.lower()

    def test_second_listing_blocked(self, user_auth):
        user_id = user_auth["user"]["id"]
        # Ensure previous test created a listing. Try to create a second one.
        active_ct = _run(lambda d: d.market_listings.count_documents({"seller_id": user_id, "status": "active"}))
        assert active_ct == 1, f"Expected exactly 1 active listing, got {active_ct}"

        payload = {"resource_type": "biomass", "amount": 10, "price_per_unit": 0.01}
        r = requests.post(
            f"{BASE_URL}/api/market/list-resource",
            json=payload,
            headers=user_auth["headers"],
            timeout=15,
        )
        # 2nd listing must be blocked with the "Лимит" 400 (max_listings=1)
        assert r.status_code == 400, f"Expected 400 limit, got {r.status_code}: {r.text}"
        assert "лимит" in r.text.lower() or "limit" in r.text.lower(), r.text

    def test_my_listings_slot_info_max_is_1(self, user_auth):
        r = requests.get(
            f"{BASE_URL}/api/market/my-listings",
            headers=user_auth["headers"],
            timeout=15,
        )
        assert r.status_code == 200, r.text
        info = (r.json() or {}).get("slot_info") or {}
        assert info.get("max") == 1, f"Expected slot_info.max==1 for no-business, got {info}"

    def test_buy_returns_normal_error_no_gate(self, user_auth):
        # Attempt buy against a non-existent listing → must return normal
        # 404 "Listing not found ...", NOT the old no_business_required gate.
        r = requests.post(
            f"{BASE_URL}/api/market/buy",
            json={"listing_id": "does-not-exist", "amount": 10},
            headers=user_auth["headers"],
            timeout=15,
        )
        assert r.status_code == 404, f"Expected 404 Listing not found, got {r.status_code}: {r.text}"
        assert "no_business_required" not in r.text.lower(), (
            f"Old no-business gate still active: {r.text}"
        )
        assert "listing not found" in r.text.lower()
