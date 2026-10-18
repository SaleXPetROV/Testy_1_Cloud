"""
Backend tests for Trash Piles ("Завалы") feature.
Covers: list, scan, collect, warehouse, admin refill, permissions, reward roll distribution.
"""
import os
import pytest
import requests
import asyncio
from datetime import datetime, timezone, timedelta

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://city-mapper-test.preview.emergentagent.com").rstrip("/")

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PASSWORD = "Test1234!"


# ---------------- helpers ----------------
def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"Login failed for {email}: {r.status_code} {r.text}"
    body = r.json()
    return body.get("token") or body.get("access_token"), body.get("user", {})


@pytest.fixture(scope="module")
def admin_auth():
    tok, u = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    return {"token": tok, "user": u, "headers": {"Authorization": f"Bearer {tok}"}}


@pytest.fixture(scope="module")
def user_auth():
    tok, u = _login(USER_EMAIL, USER_PASSWORD)
    return {"token": tok, "user": u, "headers": {"Authorization": f"Bearer {tok}"}}


@pytest.fixture(scope="module")
def db():
    """Marker fixture — actual client created per _run() call to avoid loop mismatches."""
    return None


def _run(coro_fn_or_coro):
    """Run a coroutine on a fresh event loop with a fresh Motor client.
    Accepts either a coroutine object or, preferred, a callable taking `db`.
    """
    from motor.motor_asyncio import AsyncIOMotorClient
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "test_database")
    loop = asyncio.new_event_loop()
    try:
        async def _inner():
            client = AsyncIOMotorClient(mongo_url)
            try:
                db2 = client[db_name]
                if callable(coro_fn_or_coro):
                    return await coro_fn_or_coro(db2)
                return await coro_fn_or_coro
            finally:
                client.close()
        return loop.run_until_complete(_inner())
    finally:
        loop.close()


# ---------------- basic list + spawn ----------------
class TestTrashList:
    def test_list_returns_piles(self, admin_auth):
        r = requests.get(f"{BASE_URL}/api/trash/list", headers=admin_auth["headers"], timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "piles" in data
        piles = data["piles"]
        assert isinstance(piles, list)
        # Should have close to 50 piles after cold-start
        assert 40 <= len(piles) <= 50, f"Expected ~50 piles, got {len(piles)}"

    def test_active_piles_hide_reward_fields(self, admin_auth):
        r = requests.get(f"{BASE_URL}/api/trash/list", headers=admin_auth["headers"], timeout=15)
        piles = r.json()["piles"]
        active = [p for p in piles if p["status"] == "active"]
        assert len(active) > 0, "No active piles found"
        for p in active[:5]:
            assert "reward_resource" not in p, f"Reward exposed on active pile: {p}"
            assert "reward_qty" not in p, f"Reward qty exposed on active pile: {p}"
            # Expected fields present:
            assert "id" in p and "x" in p and "y" in p and "status" in p


# ---------------- admin refill permission ----------------
class TestRefillPermissions:
    def test_non_admin_refill_403(self, user_auth):
        r = requests.post(f"{BASE_URL}/api/trash/spawn/refill", headers=user_auth["headers"], timeout=15)
        assert r.status_code == 403, f"Expected 403, got {r.status_code}: {r.text}"

    def test_admin_refill_ok(self, admin_auth):
        r = requests.post(f"{BASE_URL}/api/trash/spawn/refill", headers=admin_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "spawned" in data and "kept" in data and "deleted" in data


# ---------------- scan flow ----------------
class TestScanFlow:
    def test_scan_active_pile_flips_processing(self, admin_auth, db):
        # Reset daily counter for admin
        admin_id = admin_auth["user"]["id"]
        _run(lambda d: d.users.update_one({"id": admin_id}, {"$unset": {"trash_scan_daily": ""}}))
        # Force refill to ensure fresh active piles
        requests.post(f"{BASE_URL}/api/trash/spawn/refill", headers=admin_auth["headers"], timeout=30)

        r = requests.get(f"{BASE_URL}/api/trash/list", headers=admin_auth["headers"], timeout=15)
        active = [p for p in r.json()["piles"] if p["status"] == "active"]
        assert active, "No active piles to scan"
        pile_id = active[0]["id"]

        r = requests.post(f"{BASE_URL}/api/trash/{pile_id}/scan", headers=admin_auth["headers"], timeout=15)
        assert r.status_code == 200, f"Scan failed: {r.status_code} {r.text}"
        data = r.json()
        assert data["status"] == "processing"
        assert data["scan_duration_sec"] == 600, f"1st daily scan should be 600s, got {data['scan_duration_sec']}"
        assert data["daily_count"] == 1
        assert "ready_at" in data

        # Second scan should be 1200s
        active2 = [p for p in r.json().get("piles", [])] if False else [p for p in requests.get(f"{BASE_URL}/api/trash/list", headers=admin_auth["headers"], timeout=15).json()["piles"] if p["status"] == "active"]
        assert active2, "No more active piles"
        pile2 = active2[0]["id"]
        r2 = requests.post(f"{BASE_URL}/api/trash/{pile2}/scan", headers=admin_auth["headers"], timeout=15)
        assert r2.status_code == 200, r2.text
        d2 = r2.json()
        assert d2["scan_duration_sec"] == 1200, f"2nd daily scan should be 1200s, got {d2['scan_duration_sec']}"
        assert d2["daily_count"] == 2

        # Third scan of the same pile (already processing) → 409
        r3 = requests.post(f"{BASE_URL}/api/trash/{pile2}/scan", headers=admin_auth["headers"], timeout=15)
        assert r3.status_code == 409, f"Expected 409 on double scan, got {r3.status_code}: {r3.text}"


# ---------------- collect flow ----------------
class TestCollectFlow:
    def test_collect_before_ready_returns_425(self, admin_auth, db):
        # Ensure at least one processing pile exists for admin - scan a fresh one
        admin_id = admin_auth["user"]["id"]
        r = requests.get(f"{BASE_URL}/api/trash/list", headers=admin_auth["headers"], timeout=15)
        active = [p for p in r.json()["piles"] if p["status"] == "active"]
        if not active:
            requests.post(f"{BASE_URL}/api/trash/spawn/refill", headers=admin_auth["headers"], timeout=30)
            r = requests.get(f"{BASE_URL}/api/trash/list", headers=admin_auth["headers"], timeout=15)
            active = [p for p in r.json()["piles"] if p["status"] == "active"]
        # Reset streak so scan succeeds
        _run(lambda d: d.users.update_one({"id": admin_id}, {"$unset": {"trash_scan_daily": ""}}))
        pile_id = active[0]["id"]
        sr = requests.post(f"{BASE_URL}/api/trash/{pile_id}/scan", headers=admin_auth["headers"], timeout=15)
        assert sr.status_code == 200
        # Try collect immediately — should be 425
        cr = requests.post(f"{BASE_URL}/api/trash/{pile_id}/collect", headers=admin_auth["headers"], timeout=15)
        assert cr.status_code == 425, f"Expected 425 (too early), got {cr.status_code}: {cr.text}"

    def test_collect_after_ready_success(self, admin_auth, db):
        admin_id = admin_auth["user"]["id"]
        # Ensure warehouse has room (previous seed state may have filled it)
        _run(lambda d: d.users.update_one(
            {"id": admin_id},
            {"$set": {"personal_warehouse": {"capacity": 50, "items": {}}}},
        ))
        # Pick a processing pile scanned by admin
        pile = _run(lambda d: d.trash_piles.find_one({"status": "processing", "scanned_by": admin_id}, {"_id": 0}))
        assert pile, "No processing pile for admin — cannot test collect"
        pile_id = pile["id"]
        # Mutate ready_at to past
        past_iso = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
        _run(lambda d: d.trash_piles.update_one({"id": pile_id}, {"$set": {"ready_at": past_iso}}))

        # Now collect
        cr = requests.post(f"{BASE_URL}/api/trash/{pile_id}/collect", headers=admin_auth["headers"], timeout=15)
        assert cr.status_code == 200, f"Collect failed: {cr.status_code} {cr.text}"
        data = cr.json()
        assert data["success"] is True
        assert data["resource"]
        assert data["qty"] >= 1

        # Pile should be deleted
        gone = _run(lambda d: d.trash_piles.find_one({"id": pile_id}))
        assert gone is None, "Pile should be deleted after collect"

        # Warehouse should include the resource
        wh = requests.get(f"{BASE_URL}/api/trash/warehouse", headers=admin_auth["headers"], timeout=15)
        assert wh.status_code == 200, wh.text
        wdata = wh.json()
        assert wdata["capacity"] == 50
        assert wdata["used"] >= data["qty"] * (1 if wdata["items"] else 1)
        resources_in_wh = [i["resource"] for i in wdata["items"]]
        assert data["resource"] in resources_in_wh, f"Collected resource missing from warehouse: {wdata}"

    def test_other_user_cannot_collect(self, admin_auth, user_auth, db):
        admin_id = admin_auth["user"]["id"]
        # Reset admin streak, scan a pile
        _run(lambda d: d.users.update_one({"id": admin_id}, {"$unset": {"trash_scan_daily": ""}}))
        r = requests.get(f"{BASE_URL}/api/trash/list", headers=admin_auth["headers"], timeout=15)
        active = [p for p in r.json()["piles"] if p["status"] == "active"]
        if not active:
            requests.post(f"{BASE_URL}/api/trash/spawn/refill", headers=admin_auth["headers"], timeout=30)
            r = requests.get(f"{BASE_URL}/api/trash/list", headers=admin_auth["headers"], timeout=15)
            active = [p for p in r.json()["piles"] if p["status"] == "active"]
        pile_id = active[0]["id"]
        sr = requests.post(f"{BASE_URL}/api/trash/{pile_id}/scan", headers=admin_auth["headers"], timeout=15)
        assert sr.status_code == 200
        # Force ready_at in past
        past_iso = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
        _run(lambda d: d.trash_piles.update_one({"id": pile_id}, {"$set": {"ready_at": past_iso}}))
        # testuser tries to collect
        cr = requests.post(f"{BASE_URL}/api/trash/{pile_id}/collect", headers=user_auth["headers"], timeout=15)
        assert cr.status_code == 403, f"Expected 403, got {cr.status_code}: {cr.text}"


# ---------------- warehouse capacity ----------------
class TestWarehouseCapacity:
    def test_warehouse_full_returns_409(self, admin_auth, db):
        admin_id = admin_auth["user"]["id"]
        # Fill warehouse to 50 slots (using tier-1 resource = 1 slot each)
        _run(lambda d: d.users.update_one(
            {"id": admin_id},
            {"$set": {"personal_warehouse": {"capacity": 50, "items": {"energy": 50}}}},
        ))
        # Reset streak; scan a pile; force ready; try collect → should 409 warehouse_full
        _run(lambda d: d.users.update_one({"id": admin_id}, {"$unset": {"trash_scan_daily": ""}}))
        requests.post(f"{BASE_URL}/api/trash/spawn/refill", headers=admin_auth["headers"], timeout=30)
        r = requests.get(f"{BASE_URL}/api/trash/list", headers=admin_auth["headers"], timeout=15)
        active = [p for p in r.json()["piles"] if p["status"] == "active"]
        assert active, "No active piles"
        pile_id = active[0]["id"]
        sr = requests.post(f"{BASE_URL}/api/trash/{pile_id}/scan", headers=admin_auth["headers"], timeout=15)
        assert sr.status_code == 200
        past_iso = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
        _run(lambda d: d.trash_piles.update_one({"id": pile_id}, {"$set": {"ready_at": past_iso}}))

        cr = requests.post(f"{BASE_URL}/api/trash/{pile_id}/collect", headers=admin_auth["headers"], timeout=15)
        assert cr.status_code == 409, f"Expected 409 warehouse_full, got {cr.status_code}: {cr.text}"
        body = cr.json()
        detail = body.get("detail", body)
        # detail may be a dict with code
        code = detail.get("code") if isinstance(detail, dict) else None
        assert code == "warehouse_full", f"Expected code=warehouse_full, got {body}"

        # Cleanup: drop the warehouse back to empty
        _run(lambda d: d.users.update_one(
            {"id": admin_id},
            {"$set": {"personal_warehouse": {"capacity": 50, "items": {}}}},
        ))


# ---------------- reward roll distribution ----------------
class TestRewardRoll:
    def test_reward_roll_distribution(self):
        """Statistical test of _roll_reward: 91.5% t1x1, 8% t1x2, 0.5% t2x1."""
        import sys
        sys.path.insert(0, "/app/backend")
        from routes.trash import _roll_reward
        from business_config import RESOURCE_TYPES

        N = 5000
        t1x1 = t1x2 = t2x1 = 0
        for _ in range(N):
            roll = _roll_reward()
            res = roll["resource"]
            qty = roll["qty"]
            tier = RESOURCE_TYPES.get(res, {}).get("tier")
            if tier == 1 and qty == 1:
                t1x1 += 1
            elif tier == 1 and qty == 2:
                t1x2 += 1
            elif tier == 2 and qty == 1:
                t2x1 += 1

        p1 = t1x1 / N
        p2 = t1x2 / N
        p3 = t2x1 / N
        print(f"\nDistribution over {N} rolls: t1x1={p1:.4f} (target 0.915), t1x2={p2:.4f} (target 0.08), t2x1={p3:.4f} (target 0.005)")
        # 3σ tolerance
        assert 0.895 < p1 < 0.935, f"t1x1 out of range: {p1}"
        assert 0.060 < p2 < 0.105, f"t1x2 out of range: {p2}"
        assert 0.000 <= p3 < 0.015, f"t2x1 out of range: {p3}"
