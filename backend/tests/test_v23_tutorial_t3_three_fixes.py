"""End-to-end backend tests for the 3 targeted v2.3 fixes.

Fixes under test:
  1) Tutorial-slot resources (`<base>_tutorial`) MUST occupy 0 warehouse slots.
     • /api/my/businesses.summary.total_warehouse_used excludes tutorial units.
     • Adding/removing a `_tutorial` unit does NOT change warehouse_used.

  2) /api/resource-buffs/available reports quantity=regular+tutorial for
     `neuro_core` (2 + 1 = 3).

  3) Auto-activation on business purchase: after POST /api/island/buy/{x}/{y}
     succeeds for a plot with a pre-assigned business, the user's
     `active_resource_buffs` contains a buff with resource_id='neuro_core'
     and source='tutorial_reward', `resources.neuro_core_tutorial` drops to 0,
     regular `resources.neuro_core` stays at 2, and
     `tutorial_pending_t3_auto_activate` flag is cleared.

  Bonus: trash pile reveal — once a pile is 'ready', /api/trash/list must
  include `reward_resource` + `reward_qty`.

Run:
    pytest /app/backend/tests/test_v23_tutorial_t3_three_fixes.py -v
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone, timedelta

import pytest
import requests
from pymongo import MongoClient

# Load backend/.env so DB_NAME etc. resolve.
try:
    from dotenv import load_dotenv as _ld  # noqa
    _ld(os.path.join(os.path.dirname(__file__), "..", ".env"))
except Exception:
    pass

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL") or os.environ.get(
    "BACKEND_URL", "http://localhost:8001"
)
BASE_URL = BASE_URL.rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PW = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PW = "Test1234!"


# ---------- helpers ----------

@pytest.fixture(scope="session")
def db():
    client = MongoClient(MONGO_URL)
    return client[DB_NAME]


def _login(email: str, password: str) -> dict:
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        timeout=20,
    )
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    return r.json()


def _headers(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _reset_user_seed(db, email: str) -> None:
    """Reset user to canonical seed state so tests don't poison each other."""
    db.users.update_one(
        {"email": email},
        {
            "$set": {
                "resources": {"neuro_core": 2, "neuro_core_tutorial": 1},
                "active_resource_buffs": [],
                "tutorial_pending_t3_auto_activate": "neuro_core",
                "tutorial_completed": True,
                "tutorial_t3_reward_granted": True,
                "tutorial_active": False,
                "balance_ton": 100000,  # ensure enough to buy any plot
            }
        },
    )
    user = db.users.find_one({"email": email}, {"id": 1})
    if user and user.get("id"):
        uid = user["id"]
        # Remove any plots/businesses the user owns to reset for buy-tests.
        db.plots.delete_many({"owner": uid})
        db.businesses.delete_many({
            "$or": [
                {"owner": uid}, {"owner_id": uid},
                {"owner_wallet": uid}, {"owner_email": email},
            ]
        })
        db.users.update_one({"email": email}, {"$set": {"plots_owned": []}})


# =========================================================================
# 1. LOGIN
# =========================================================================

class TestLogin:
    def test_admin_login(self):
        j = _login(ADMIN_EMAIL, ADMIN_PW)
        assert j["user"]["email"] == ADMIN_EMAIL
        assert j["user"]["is_admin"] is True
        assert isinstance(j["token"], str) and j["token"]

    def test_user_login(self):
        j = _login(USER_EMAIL, USER_PW)
        assert j["user"]["email"] == USER_EMAIL
        assert j["user"]["is_admin"] is False


# =========================================================================
# 2. Warehouse used excludes tutorial units
# =========================================================================

class TestWarehouseIgnoresTutorial:
    def test_summary_warehouse_used_only_counts_regular(self, db):
        _reset_user_seed(db, USER_EMAIL)
        tok = _login(USER_EMAIL, USER_PW)["token"]
        r = requests.get(f"{BASE_URL}/api/my/businesses", headers=_headers(tok), timeout=20)
        assert r.status_code == 200, r.text
        summary = r.json().get("summary", {})
        # neuro_core:2 * weight 20 = 40; neuro_core_tutorial contributes 0.
        assert summary.get("total_warehouse_used") == 40, summary
        assert summary.get("total_warehouse_capacity") == 50, summary

    def test_tutorial_unit_add_remove_does_not_change_warehouse_used(self, db):
        _reset_user_seed(db, USER_EMAIL)
        tok = _login(USER_EMAIL, USER_PW)["token"]

        def _used() -> int:
            r = requests.get(f"{BASE_URL}/api/my/businesses", headers=_headers(tok), timeout=20)
            assert r.status_code == 200
            return r.json()["summary"]["total_warehouse_used"]

        baseline = _used()
        # Bump tutorial slot to 5 — must not affect warehouse_used.
        db.users.update_one({"email": USER_EMAIL}, {"$set": {"resources.neuro_core_tutorial": 5}})
        assert _used() == baseline, "adding tutorial units changed warehouse_used"
        # Drop tutorial slot to 0 — still no change.
        db.users.update_one({"email": USER_EMAIL}, {"$set": {"resources.neuro_core_tutorial": 0}})
        assert _used() == baseline, "removing tutorial units changed warehouse_used"


# =========================================================================
# 3. /api/resource-buffs/available reports quantity = regular + tutorial
# =========================================================================

class TestAvailableBuffsQuantity:
    def test_neuro_core_quantity_3_split(self, db):
        _reset_user_seed(db, USER_EMAIL)
        tok = _login(USER_EMAIL, USER_PW)["token"]
        r = requests.get(
            f"{BASE_URL}/api/resource-buffs/available", headers=_headers(tok), timeout=20
        )
        assert r.status_code == 200, r.text
        buffs = r.json().get("buffs", [])
        nc = next((b for b in buffs if b["resource_id"] == "neuro_core"), None)
        assert nc is not None, f"neuro_core missing from buffs: {buffs}"
        assert nc["quantity_regular"] == 2, nc
        assert nc["quantity_tutorial"] == 1, nc
        assert nc["quantity"] == 3, nc
        assert nc["can_activate"] is True
        assert nc["already_active"] is False


# =========================================================================
# 4. Auto-activation on business purchase (admin, /api/island/buy)
# =========================================================================

def _find_free_plot_with_pre_business(db) -> tuple[int, int]:
    """Return (x, y) of a not-yet-owned island cell that has a pre_business."""
    island = db.islands.find_one({"id": "ton_island"}, {"_id": 0})
    assert island, "ton_island not initialised"
    owned = {(p["x"], p["y"]) for p in db.plots.find({"island_id": "ton_island"}, {"x": 1, "y": 1})}
    for c in island["cells"]:
        if (
            c.get("pre_business")
            and not c.get("is_empty")
            and (c["x"], c["y"]) not in owned
            and not c.get("is_center")  # avoid overpriced core if possible
        ):
            return c["x"], c["y"]
    # fallback: any free pre_business cell
    for c in island["cells"]:
        if c.get("pre_business") and not c.get("is_empty") and (c["x"], c["y"]) not in owned:
            return c["x"], c["y"]
    raise RuntimeError("no free pre_business plot available")


class TestAutoActivateOnBusinessPurchase:
    def test_buy_plot_auto_activates_tutorial_t3(self, db):
        # Prime the ADMIN user (bypasses plot/business limits & schedule).
        _reset_user_seed(db, ADMIN_EMAIL)

        tok = _login(ADMIN_EMAIL, ADMIN_PW)["token"]
        x, y = _find_free_plot_with_pre_business(db)

        r = requests.post(
            f"{BASE_URL}/api/island/buy/{x}/{y}", headers=_headers(tok), timeout=30
        )
        assert r.status_code == 200, f"buy failed: {r.status_code} {r.text}"
        body = r.json()
        assert body.get("status") == "purchased"
        assert body.get("business"), f"expected business created, got {body}"

        # Reload user & assert auto-activation happened.
        u = db.users.find_one({"email": ADMIN_EMAIL}, {"_id": 0})
        resources = u.get("resources", {}) or {}
        active = u.get("active_resource_buffs", []) or []

        # tutorial-reward T3 was consumed
        assert int(resources.get("neuro_core_tutorial", 0) or 0) == 0, (
            f"neuro_core_tutorial should be 0, got {resources}"
        )
        # regular stock untouched
        assert int(resources.get("neuro_core", 0) or 0) == 2, (
            f"regular neuro_core must stay 2, got {resources}"
        )
        # buff added with the tutorial marker
        tut_buff = next(
            (b for b in active if b.get("resource_id") == "neuro_core"), None
        )
        assert tut_buff is not None, f"no neuro_core buff activated: {active}"
        assert tut_buff.get("source") == "tutorial_reward", tut_buff
        # buff has a future expires_at
        exp = datetime.fromisoformat(tut_buff["expires_at"].replace("Z", "+00:00"))
        assert exp > datetime.now(timezone.utc), tut_buff

        # pending flag cleared
        assert "tutorial_pending_t3_auto_activate" not in u or not u.get(
            "tutorial_pending_t3_auto_activate"
        ), f"flag not cleared: {u.get('tutorial_pending_t3_auto_activate')}"

        # Cleanup: remove created plot + business + reseed admin.
        plot = body.get("plot") or {}
        biz = body.get("business") or {}
        if plot.get("id"):
            db.plots.delete_one({"id": plot["id"]})
        if biz.get("id"):
            db.businesses.delete_one({"id": biz["id"]})
        _reset_user_seed(db, ADMIN_EMAIL)


# =========================================================================
# 5. Trash flow: reward revealed only when pile is 'ready'
# =========================================================================

class TestTrashRewardRevealOnReady:
    def test_processing_pile_hides_reward_ready_pile_reveals(self, db):
        _reset_user_seed(db, USER_EMAIL)
        tok = _login(USER_EMAIL, USER_PW)["token"]

        user = db.users.find_one({"email": USER_EMAIL}, {"id": 1})
        uid = user["id"]
        # Ensure at least one 'active' pile exists for this user.
        db.trash_piles.delete_many({"user_id": uid})
        pile_id = str(uuid.uuid4())
        db.trash_piles.insert_one({
            "id": pile_id,
            "user_id": uid,
            "x": 0, "y": 0,
            "status": "active",
            "spawned_at": datetime.now(timezone.utc).isoformat(),
            "scanned_by": None,
            "scan_started_at": None,
            "scan_duration_sec": None,
            "ready_at": None,
            "reward_resource": "energy",
            "reward_qty": 3,
        })

        # 1) List while active — reward hidden.
        r = requests.get(f"{BASE_URL}/api/trash/list", headers=_headers(tok), timeout=20)
        assert r.status_code == 200, r.text
        piles = r.json().get("piles", [])
        p = next((p for p in piles if p["id"] == pile_id), None)
        assert p is not None, f"pile not in list: {piles}"
        assert "reward_resource" not in p, p
        assert p["status"] == "active"

        # 2) Flip to processing with ready_at IN THE PAST — should compute as 'ready'
        #    on the very next list and reveal the reward.
        past = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
        db.trash_piles.update_one(
            {"id": pile_id},
            {"$set": {
                "status": "processing",
                "scanned_by": uid,
                "scan_started_at": (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat(),
                "scan_duration_sec": 5,
                "ready_at": past,
            }},
        )
        r = requests.get(f"{BASE_URL}/api/trash/list", headers=_headers(tok), timeout=20)
        assert r.status_code == 200, r.text
        piles = r.json().get("piles", [])
        p = next((p for p in piles if p["id"] == pile_id), None)
        assert p is not None
        assert p["status"] == "ready", f"expected ready, got {p}"
        assert p.get("reward_resource") == "energy", p
        assert p.get("reward_qty") == 3, p

        # 3) Collect the pile — reward is added to resources.
        before = db.users.find_one({"id": uid}, {"resources": 1}).get("resources", {}) or {}
        r = requests.post(
            f"{BASE_URL}/api/trash/{pile_id}/collect",
            headers=_headers(tok),
            timeout=20,
        )
        assert r.status_code == 200, f"collect failed: {r.status_code} {r.text}"
        body = r.json()
        assert body.get("success") is True
        assert body.get("resource") == "energy"
        assert body.get("qty") == 3
        after = db.users.find_one({"id": uid}, {"resources": 1}).get("resources", {}) or {}
        assert int(after.get("energy", 0) or 0) == int(before.get("energy", 0) or 0) + 3

        # cleanup
        db.trash_piles.delete_many({"user_id": uid})
        db.users.update_one({"id": uid}, {"$set": {"resources.energy": before.get("energy", 0)}})
