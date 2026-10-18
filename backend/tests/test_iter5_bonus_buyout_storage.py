"""
Iteration 5 backend tests — TON_CITY v2.3 bug-fix round.

ITEM 2: POST /api/market/buy spends bonus_balance FIRST, then balance_ton.
ITEM 1: Admin buyout credits a NON-active-investor seller's bonus_balance
        (not withdrawable balance_ton); active investor -> balance_ton.
ITEM 3: When a user's warehouse is 100% full, ALL their businesses go idle:
        work_status='idle', work_status_reason='storage_full', is_active=False,
        with NO production and NO consumption.

Seeded docs are TEST_ prefixed and removed in teardown.
"""

import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


def _base_url():
    u = os.environ.get("REACT_APP_BACKEND_URL") or dotenv_values("/app/frontend/.env").get("REACT_APP_BACKEND_URL")
    assert u, "REACT_APP_BACKEND_URL missing"
    return u.rstrip("/")


BASE_URL = _base_url()
API = f"{BASE_URL}/api"

ADMIN_EMAIL, ADMIN_PASSWORD = "sanyanazarov212@gmail.com", os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL, USER_PASSWORD = "testuser@example.com", "Test1234!"

_env = dotenv_values("/app/backend/.env")
_client = MongoClient(_env["MONGO_URL"])
DB = _client[_env["DB_NAME"]]

TAG = "TEST_iter5"


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text[:200]}"
    return r.json()["token"]


def _headers(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _mk_listing(seller_id, seller_email, resource="energy", price=0.01, amount=100):
    lid = f"{TAG}_listing_{uuid.uuid4().hex[:8]}"
    DB.market_listings.insert_one({
        "id": lid,
        "seller_id": seller_id,
        "seller_email": seller_email,
        "seller_username": f"{TAG}_seller",
        "resource_type": resource,
        "amount": amount,
        "price_per_unit": price,
        "status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return lid


def _mk_seller(is_investor=False):
    sid = f"{TAG}_seller_{uuid.uuid4().hex[:8]}"
    email = f"{sid}@example.com"
    DB.users.insert_one({
        "id": sid,
        "email": email,
        "username": sid,
        "balance_ton": 0.0,
        "bonus_balance": 0.0,
        "total_income": 0.0,
        "is_active_investor": is_investor,
        "resources": {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return sid, email


def _mk_business(owner_id, biz_type="scrap_yard", capacity=1000, is_trial=False, level=1,
                 last_tick_hours_ago=2.0):
    bid = f"{TAG}_biz_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    lt = (now - timedelta(hours=last_tick_hours_ago)).isoformat()
    DB.businesses.insert_one({
        "id": bid,
        "owner": owner_id,
        "business_type": biz_type,
        "level": level,
        "durability": 100,
        "is_active": True,
        "is_trial": is_trial,
        "status": "active",
        "storage": {"capacity": capacity, "items": {}},
        "last_tick": lt,
        "last_collection": lt,
        "last_wear_update": lt,
        "created_at": now.isoformat(),
    })
    return bid


def _user(email=None, uid=None):
    q = {"email": email} if email else {"id": uid}
    return DB.users.find_one(q, {"_id": 0})


def _set_buyer(bonus, real, resources=None):
    DB.users.update_one(
        {"email": USER_EMAIL},
        {"$set": {"bonus_balance": float(bonus), "balance_ton": float(real),
                  "resources": resources if resources is not None else {}}},
    )


@pytest.fixture(scope="module")
def admin_headers():
    return _headers(_login(ADMIN_EMAIL, ADMIN_PASSWORD))


@pytest.fixture(scope="module")
def user_headers():
    return _headers(_login(USER_EMAIL, USER_PASSWORD))


@pytest.fixture(scope="module")
def buyer_trial_biz():
    """Buyer needs a business (P2P gate) + warehouse capacity."""
    buyer = _user(email=USER_EMAIL)
    assert buyer, "seed user testuser@example.com missing"
    orig = {k: buyer.get(k) for k in ("bonus_balance", "balance_ton", "resources")}
    bid = _mk_business(buyer["id"], biz_type="scrap_yard", capacity=5000, is_trial=True)
    yield buyer["id"]
    DB.businesses.delete_one({"id": bid})
    DB.users.update_one({"email": USER_EMAIL}, {"$set": {
        "bonus_balance": orig.get("bonus_balance") or 0.0,
        "balance_ton": orig.get("balance_ton") or 0.0,
        "resources": orig.get("resources") or {},
    }})


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    DB.market_listings.delete_many({"id": {"$regex": f"^{TAG}"}})
    DB.users.delete_many({"id": {"$regex": f"^{TAG}"}})
    DB.businesses.delete_many({"id": {"$regex": f"^{TAG}"}})


# ============================================================
# ITEM 2 — buyer pays with bonus funds (bonus first)
# ============================================================
class TestItem2BonusPurchase:
    def test_buy_fully_from_bonus(self, user_headers, buyer_trial_biz):
        sid, semail = _mk_seller()
        lid = _mk_listing(sid, semail, resource="energy", price=0.01, amount=100)
        _set_buyer(bonus=1.0, real=0.0)

        r = requests.post(f"{API}/market/buy", json={"listing_id": lid, "amount": 10},
                          headers=user_headers, timeout=30)
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text[:400]}"

        buyer = _user(email=USER_EMAIL)
        assert abs(float(buyer["bonus_balance"]) - 0.9) < 1e-6, f"bonus_balance={buyer['bonus_balance']} (expected 0.9)"
        assert abs(float(buyer["balance_ton"]) - 0.0) < 1e-9, f"balance_ton must stay 0, got {buyer['balance_ton']}"
        assert int(float(buyer.get("resources", {}).get("energy", 0))) == 10, buyer.get("resources")

    def test_buy_mixed_bonus_then_real(self, user_headers, buyer_trial_biz):
        sid, semail = _mk_seller()
        lid = _mk_listing(sid, semail, resource="energy", price=0.01, amount=100)
        _set_buyer(bonus=0.04, real=1.0)

        r = requests.post(f"{API}/market/buy", json={"listing_id": lid, "amount": 10},
                          headers=user_headers, timeout=30)
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text[:400]}"

        buyer = _user(email=USER_EMAIL)
        assert abs(float(buyer["bonus_balance"])) < 1e-6, f"bonus should be drained first, got {buyer['bonus_balance']}"
        assert abs(float(buyer["balance_ton"]) - 0.94) < 1e-6, f"balance_ton={buyer['balance_ton']} (expected 0.94)"
        assert int(float(buyer.get("resources", {}).get("energy", 0))) == 10

    def test_buy_insufficient_bonus_plus_real(self, user_headers, buyer_trial_biz):
        sid, semail = _mk_seller()
        lid = _mk_listing(sid, semail, resource="energy", price=0.01, amount=100)
        _set_buyer(bonus=0.02, real=0.03)

        r = requests.post(f"{API}/market/buy", json={"listing_id": lid, "amount": 10},
                          headers=user_headers, timeout=30)
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text[:400]}"
        buyer = _user(email=USER_EMAIL)
        assert abs(float(buyer["bonus_balance"]) - 0.02) < 1e-9
        assert abs(float(buyer["balance_ton"]) - 0.03) < 1e-9
        assert int(float(buyer.get("resources", {}).get("energy", 0))) == 0


# ============================================================
# ITEM 1 — admin buyout revenue routing
# ============================================================
class TestItem1AdminBuyoutRouting:
    def _execute(self, admin_headers, lid, amount=10):
        return requests.post(f"{API}/admin/buyout/execute",
                             json={"items": [{"listing_id": lid, "amount": amount}], "mask_mode": "auto"},
                             headers=admin_headers, timeout=60)

    def test_non_investor_seller_credited_to_bonus(self, admin_headers):
        sid, semail = _mk_seller(is_investor=False)
        lid = _mk_listing(sid, semail, resource="energy", price=0.01, amount=100)

        r = self._execute(admin_headers, lid, 10)
        assert r.status_code == 200, f"buyout failed: {r.status_code} {r.text[:400]}"

        seller = _user(uid=sid)
        bonus = float(seller.get("bonus_balance") or 0)
        real = float(seller.get("balance_ton") or 0)
        assert bonus > 0, "non-investor seller bonus_balance did not increase"
        assert bonus <= 0.1 + 1e-9, f"bonus {bonus} exceeds gross 0.1"
        assert abs(real) < 1e-9, f"balance_ton must NOT increase for non-investor, got {real}"
        TestItem1AdminBuyoutRouting._non_investor_credit = bonus

    def test_investor_seller_credited_to_balance_ton(self, admin_headers):
        sid, semail = _mk_seller(is_investor=True)
        lid = _mk_listing(sid, semail, resource="energy", price=0.01, amount=100)

        r = self._execute(admin_headers, lid, 10)
        assert r.status_code == 200, f"buyout failed: {r.status_code} {r.text[:400]}"

        seller = _user(uid=sid)
        bonus = float(seller.get("bonus_balance") or 0)
        real = float(seller.get("balance_ton") or 0)
        income = float(seller.get("total_income") or 0)
        assert real > 0, "investor seller balance_ton did not increase"
        assert abs(bonus) < 1e-9, f"bonus_balance must stay 0 for investor, got {bonus}"
        assert income > 0, "total_income not credited for investor seller"
        prev = getattr(TestItem1AdminBuyoutRouting, "_non_investor_credit", None)
        if prev is not None:
            assert abs(prev - real) < 1e-6, f"post-tax proceeds differ: bonus route {prev} vs real route {real}"


# ============================================================
# ITEM 3 — warehouse full => all businesses idle (storage_full)
# ============================================================
class TestItem3StorageFullIdle:
    @pytest.fixture(scope="class")
    def scenario(self):
        # FULL user: capacity 10, 200 energy (weight 1) => used 200 >= 10
        full_id = f"{TAG}_full_{uuid.uuid4().hex[:6]}"
        DB.users.insert_one({"id": full_id, "email": f"{full_id}@example.com",
                             "username": full_id, "balance_ton": 5.0, "bonus_balance": 0.0,
                             "resources": {"energy": 200}})
        full_b1 = _mk_business(full_id, capacity=10)
        full_b2 = _mk_business(full_id, biz_type="quartz_mine", capacity=0)

        # FREE user: plenty of capacity + inputs
        free_id = f"{TAG}_free_{uuid.uuid4().hex[:6]}"
        DB.users.insert_one({"id": free_id, "email": f"{free_id}@example.com",
                             "username": free_id, "balance_ton": 5.0, "bonus_balance": 0.0,
                             "resources": {"energy": 500}})
        free_b = _mk_business(free_id, capacity=5000)

        subprocess.run([sys.executable, "/app/backend/tests/_iter5_run_tick.py"],
                       cwd="/app/backend", check=True, capture_output=True, timeout=180)
        yield {"full_id": full_id, "full_biz": [full_b1, full_b2],
               "free_id": free_id, "free_biz": free_b}
        DB.users.delete_many({"id": {"$in": [full_id, free_id]}})
        DB.businesses.delete_many({"id": {"$in": [full_b1, full_b2, free_b]}})

    def test_full_user_businesses_idle_storage_full(self, scenario):
        for bid in scenario["full_biz"]:
            b = DB.businesses.find_one({"id": bid}, {"_id": 0})
            assert b["work_status"] == "idle", f"{bid}: work_status={b.get('work_status')}"
            assert b["work_status_reason"] == "storage_full", f"{bid}: reason={b.get('work_status_reason')}"
            assert b["is_active"] is False, f"{bid}: is_active={b.get('is_active')}"

    def test_full_user_no_consumption_no_production(self, scenario):
        u = _user(uid=scenario["full_id"])
        res = u.get("resources", {})
        assert int(float(res.get("energy", 0))) == 200, f"energy consumed while full: {res.get('energy')}"
        assert float(res.get("scrap", 0) or 0) == 0, f"produced scrap while full: {res.get('scrap')}"
        assert float(res.get("quartz", 0) or 0) == 0, f"produced quartz while full: {res.get('quartz')}"
        for bid in scenario["full_biz"]:
            b = DB.businesses.find_one({"id": bid}, {"_id": 0})
            assert not (b.get("storage", {}).get("items") or {}), f"{bid} storage got items: {b['storage']}"

    def test_free_space_user_active_and_producing(self, scenario):
        b = DB.businesses.find_one({"id": scenario["free_biz"]}, {"_id": 0})
        assert b["work_status"] == "active", f"work_status={b.get('work_status')} reason={b.get('work_status_reason')}"
        assert b.get("work_status_reason") in (None, ""), b.get("work_status_reason")
        assert b["is_active"] is True
        u = _user(uid=scenario["free_id"])
        res = u.get("resources", {})
        assert float(res.get("scrap", 0) or 0) > 0, f"no production for free-space user: {res}"
        assert float(res.get("energy", 0) or 0) < 500, f"no consumption for free-space user: {res}"
