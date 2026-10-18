"""End-to-end backend tests for v2.3 tutorial-reward T3 SEPARATE-SLOT rule.

Covers:
  1. Login for both seeded users returns a JWT token and correct is_admin.
  2. GET /api/my/resources returns {neuro_core:2, neuro_core_tutorial:1}.
  3. GET /api/resource-buffs/available exposes quantity=3, quantity_regular=2,
     quantity_tutorial=1 for neuro_core.
  4. POST /api/market/list-resource with `neuro_core` amount=1 succeeds WITHOUT
     owning a business (v2.3 T3 rule) and deducts from resources.neuro_core.
  5. POST /api/market/list-resource with `neuro_core_tutorial` returns 400 with
     a message referring to tutorial/not-for-sale.
  6. POST /api/market/list-resource with `neuro_core` amount=3 (only 2 regular
     available; tutorial unit must NOT be counted) returns 400 insufficient.
  7. POST /api/market/list-resource with T1 (`biomass`) without a business
     returns 400 detail='no_business_required_for_action'.
  8. POST /api/resource-buffs/activate/neuro_core with an active business
     consumes the tutorial-reward unit FIRST (neuro_core_tutorial goes 1→0,
     neuro_core stays at 2), and appends to active_resource_buffs.
  9. POST /api/resource-buffs/activate/neuro_core without a business returns
     400 detail='tutorial_buff_needs_business'.
 10. POST /api/market/cancel/{id} restores the amount back to `neuro_core`
     (regular slot), NOT to `neuro_core_tutorial`.

Runs against the local backend (supervisor-managed on :8001) so we don't
depend on the external ingress being reachable.

    pytest /app/backend/tests/test_v23_tutorial_t3_separate_slot.py -v -n 0
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("BACKEND_URL", "http://localhost:8001").rstrip("/")
# Load backend/.env so DB_NAME etc. resolve when pytest is invoked without env.
try:
    from dotenv import load_dotenv as _ld  # noqa
    _ld(os.path.join(os.path.dirname(__file__), "..", ".env"))
except Exception:
    pass
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "ton_city_v23")

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PW = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PW = "Test1234!"

CANONICAL_RESOURCES = {"neuro_core": 2, "neuro_core_tutorial": 1}


# ---------- helpers ----------

@pytest.fixture(scope="session")
def db():
    client = MongoClient(MONGO_URL)
    return client[DB_NAME]


def _reset_user(db, email: str) -> None:
    """Reset test user to canonical seed state so tests can't poison one another."""
    db.users.update_one(
        {"email": email},
        {
            "$set": {
                "resources": dict(CANONICAL_RESOURCES),
                "active_resource_buffs": [],
                "businesses_owned": [],
            },
        },
    )
    # Remove any active listings and businesses left over from previous runs.
    user = db.users.find_one({"email": email}, {"id": 1})
    if user and user.get("id"):
        db.market_listings.delete_many({"seller_id": user["id"]})
        db.businesses.delete_many({
            "$or": [
                {"owner_id": user["id"]},
                {"owner": user["id"]},
                {"owner_wallet": user["id"]},
                {"owner_email": email},
            ]
        })


@pytest.fixture
def clean_user(db):
    """Provide the regular test user in canonical state for each test."""
    _reset_user(db, USER_EMAIL)
    yield
    _reset_user(db, USER_EMAIL)


def _login(email: str, password: str) -> dict:
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        timeout=15,
    )
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    return r.json()


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _get_user(db, email: str) -> dict:
    return db.users.find_one({"email": email}) or {}


def _grant_business(db, email: str) -> str:
    """Insert a real (non-tutorial) business so the user passes
    `user_has_active_business`. Returns the created business id."""
    user = db.users.find_one({"email": email}, {"id": 1})
    assert user and user.get("id"), f"user {email} not found"
    biz_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": biz_id,
        "owner": user["id"],
        "owner_wallet": user["id"],
        "owner_id": user["id"],
        "owner_email": email,
        "business_type": "residential_1",
        "level": 1,
        "durability": 100,
        "max_durability": 100,
        "produced_amount": 0,
        "resources": {},
        "tutorial": False,
        "created_at": now,
        "last_collected": now,
        "status": "active",
    }
    db.businesses.insert_one(doc)
    return biz_id


# ---------- 1. Login ----------

class TestLogin:
    def test_admin_login_returns_token_and_is_admin(self):
        j = _login(ADMIN_EMAIL, ADMIN_PW)
        assert isinstance(j.get("token"), str) and j["token"]
        assert j.get("user", {}).get("is_admin") is True
        assert j["user"].get("email") == ADMIN_EMAIL

    def test_user_login_returns_token_not_admin(self):
        j = _login(USER_EMAIL, USER_PW)
        assert isinstance(j.get("token"), str) and j["token"]
        assert j.get("user", {}).get("is_admin") is False
        assert j["user"].get("email") == USER_EMAIL


# ---------- 2. GET /api/my/resources ----------

class TestMyResources:
    @pytest.mark.parametrize("email,password", [
        (ADMIN_EMAIL, ADMIN_PW),
        (USER_EMAIL, USER_PW),
    ])
    def test_my_resources_contains_tutorial_slot(self, db, email, password):
        _reset_user(db, email)
        tok = _login(email, password)["token"]
        r = requests.get(
            f"{BASE_URL}/api/my/resources",
            headers=_auth_headers(tok),
            timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        res = body.get("resources", {})
        assert res.get("neuro_core") == 2, f"expected 2 got {res}"
        assert res.get("neuro_core_tutorial") == 1, f"expected 1 got {res}"
        # v2.3 merge with upstream: response now includes a `locked` map, but
        # in our approach it must always be an empty dict (we do NOT use
        # `tutorial_reward_locked_qty`).
        assert "locked" in body, f"expected 'locked' key in /my/resources body: {body}"
        assert body["locked"] == {}, f"expected empty locked, got {body['locked']}"


# ---------- 3. GET /api/resource-buffs/available ----------

class TestAvailableBuffs:
    def test_available_reports_split_quantities(self, db, clean_user):
        tok = _login(USER_EMAIL, USER_PW)["token"]
        r = requests.get(
            f"{BASE_URL}/api/resource-buffs/available",
            headers=_auth_headers(tok),
            timeout=15,
        )
        assert r.status_code == 200, r.text
        buffs = r.json().get("buffs", [])
        nc = next((b for b in buffs if b["resource_id"] == "neuro_core"), None)
        assert nc is not None, "neuro_core buff entry missing"
        assert nc["quantity"] == 3, nc
        assert nc["quantity_regular"] == 2, nc
        assert nc["quantity_tutorial"] == 1, nc
        assert nc["can_activate"] is True
        assert nc["already_active"] is False


# ---------- 4. list-resource: T3 without business succeeds ----------

class TestListT3WithoutBusiness:
    def test_list_neuro_core_amount_1_no_business(self, db, clean_user):
        tok = _login(USER_EMAIL, USER_PW)["token"]
        r = requests.post(
            f"{BASE_URL}/api/market/list-resource",
            headers=_auth_headers(tok),
            json={"resource_type": "neuro_core", "amount": 1, "price_per_unit": 100},
            timeout=15,
        )
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
        body = r.json()
        assert body.get("status") == "listed"
        listing = body.get("listing") or {}
        assert listing.get("resource_type") == "neuro_core"
        assert listing.get("amount") == 1
        # Persistence: resources.neuro_core deducted from 2 → 1.
        user = _get_user(db, USER_EMAIL)
        assert user.get("resources", {}).get("neuro_core") == 1, user.get("resources")
        # Tutorial slot untouched.
        assert user.get("resources", {}).get("neuro_core_tutorial") == 1


# ---------- 5. list-resource: tutorial slot blocked ----------

class TestListTutorialBlocked:
    def test_list_neuro_core_tutorial_returns_400(self, db, clean_user):
        tok = _login(USER_EMAIL, USER_PW)["token"]
        r = requests.post(
            f"{BASE_URL}/api/market/list-resource",
            headers=_auth_headers(tok),
            json={"resource_type": "neuro_core_tutorial", "amount": 1, "price_per_unit": 100},
            timeout=15,
        )
        assert r.status_code == 400, r.text
        detail = ""
        try:
            detail = r.json().get("detail", "")
        except Exception:
            detail = r.text
        # Must mention tutorial / sale (Russian "обучение"/"продаж").
        assert any(
            kw in detail.lower()
            for kw in ("tutorial", "обучени", "продаж", "not-for-sale")
        ), f"unexpected detail: {detail!r}"
        # Nothing should have been deducted.
        user = _get_user(db, USER_EMAIL)
        assert user.get("resources", {}).get("neuro_core") == 2
        assert user.get("resources", {}).get("neuro_core_tutorial") == 1


# ---------- 6. list-resource: amount exceeds regular stock ----------

class TestListInsufficientRegular:
    def test_list_neuro_core_amount_3_when_only_2_regular(self, db, clean_user):
        tok = _login(USER_EMAIL, USER_PW)["token"]
        r = requests.post(
            f"{BASE_URL}/api/market/list-resource",
            headers=_auth_headers(tok),
            json={"resource_type": "neuro_core", "amount": 3, "price_per_unit": 100},
            timeout=15,
        )
        assert r.status_code == 400, f"should be 400, got {r.status_code}: {r.text}"
        detail = r.json().get("detail", "")
        assert "недостаточно" in detail.lower() or "insufficient" in detail.lower() \
            or "доступно" in detail.lower(), f"unexpected: {detail!r}"
        # Deduction did NOT happen.
        user = _get_user(db, USER_EMAIL)
        assert user.get("resources", {}).get("neuro_core") == 2
        assert user.get("resources", {}).get("neuro_core_tutorial") == 1


# ---------- 7. list-resource: NON-T3 (biomass) without business — upstream removed the gate ----------

class TestT1NoBusinessGateRemoved:
    """After the upstream v2.3 merge the business-gate was lifted for ALL
    resource types (not just T3). Selling biomass without a business must NOT
    return `detail='no_business_required_for_action'` any more. Expected:
      * 400 with an insufficient-resources / slot-limit error if the user has
        no stock or exceeds the slot cap, OR
      * 200 success if the request is legal (stock >= amount AND slot free).
    """

    def test_list_biomass_without_business_regression(self, db, clean_user):
        # Give the user enough biomass so an amount check alone would pass.
        db.users.update_one({"email": USER_EMAIL}, {"$set": {"resources.biomass": 20}})
        tok = _login(USER_EMAIL, USER_PW)["token"]
        r = requests.post(
            f"{BASE_URL}/api/market/list-resource",
            headers=_auth_headers(tok),
            json={"resource_type": "biomass", "amount": 10, "price_per_unit": 1},
            timeout=15,
        )
        # Explicit regression: the removed business-gate error MUST NOT come back.
        detail = ""
        try:
            detail = r.json().get("detail", "") or ""
        except Exception:
            detail = r.text
        assert detail != "no_business_required_for_action", (
            f"regression: business-gate must be lifted for all resource_types, "
            f"got detail={detail!r} status={r.status_code}"
        )
        # Either 200 (legal listing) or 400 (insufficient / slot-limit).
        assert r.status_code in (200, 400), f"unexpected {r.status_code}: {r.text}"
        user = _get_user(db, USER_EMAIL)
        if r.status_code == 200:
            assert user.get("resources", {}).get("biomass") == 10, user.get("resources")
        else:
            # 400 -> nothing deducted.
            assert user.get("resources", {}).get("biomass") == 20, user.get("resources")


# ---------- 8. activate buff: tutorial consumed first ----------

class TestActivateBuffConsumesTutorialFirst:
    def test_activate_buff_with_business_consumes_tutorial_first(self, db, clean_user):
        # Give user an active business so gate passes.
        _grant_business(db, USER_EMAIL)
        tok = _login(USER_EMAIL, USER_PW)["token"]
        r = requests.post(
            f"{BASE_URL}/api/resource-buffs/activate/neuro_core",
            headers=_auth_headers(tok),
            timeout=15,
        )
        assert r.status_code == 200, f"activate failed: {r.status_code} {r.text}"
        body = r.json()
        assert body.get("success") is True
        assert body.get("buff", {}).get("resource_id") == "neuro_core"

        user = _get_user(db, USER_EMAIL)
        resources = user.get("resources", {})
        # Tutorial spent first, regular untouched.
        assert resources.get("neuro_core_tutorial", 0) == 0, resources
        assert resources.get("neuro_core") == 2, resources
        # active_resource_buffs contains neuro_core.
        active = user.get("active_resource_buffs", []) or []
        assert any(b.get("resource_id") == "neuro_core" for b in active), active


# ---------- 9. activate buff without business rejected ----------

class TestActivateBuffRequiresBusiness:
    def test_activate_without_business_returns_400_tutorial_buff_needs_business(
        self, db, clean_user
    ):
        tok = _login(USER_EMAIL, USER_PW)["token"]
        r = requests.post(
            f"{BASE_URL}/api/resource-buffs/activate/neuro_core",
            headers=_auth_headers(tok),
            timeout=15,
        )
        assert r.status_code == 400, r.text
        assert r.json().get("detail") == "tutorial_buff_needs_business"
        # No mutation.
        user = _get_user(db, USER_EMAIL)
        assert user.get("resources", {}).get("neuro_core") == 2
        assert user.get("resources", {}).get("neuro_core_tutorial") == 1
        assert (user.get("active_resource_buffs") or []) == []


# ---------- 10. cancel listing → refund to regular slot ----------

class TestCancelListingRefundsRegular:
    def test_cancel_neuro_core_refund_goes_to_regular_not_tutorial(self, db, clean_user):
        tok = _login(USER_EMAIL, USER_PW)["token"]
        # Step 1: list 1 unit.
        r = requests.post(
            f"{BASE_URL}/api/market/list-resource",
            headers=_auth_headers(tok),
            json={"resource_type": "neuro_core", "amount": 1, "price_per_unit": 100},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        listing_id = r.json()["listing"]["id"]

        # Sanity: regular now 1, tutorial still 1.
        user = _get_user(db, USER_EMAIL)
        assert user["resources"].get("neuro_core") == 1
        assert user["resources"].get("neuro_core_tutorial") == 1

        # Step 2: cancel.
        r = requests.post(
            f"{BASE_URL}/api/market/cancel/{listing_id}",
            headers=_auth_headers(tok),
            timeout=15,
        )
        assert r.status_code == 200, f"cancel failed: {r.status_code} {r.text}"

        # Refunded to regular; tutorial still exactly 1.
        user = _get_user(db, USER_EMAIL)
        assert user["resources"].get("neuro_core") == 2, user["resources"]
        assert user["resources"].get("neuro_core_tutorial") == 1, user["resources"]
        # Listing removed / marked inactive.
        listing = db.market_listings.find_one({"id": listing_id})
        assert listing is None or listing.get("status") != "active", listing
