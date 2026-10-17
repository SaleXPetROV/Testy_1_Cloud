"""Iteration-6 follow-up tests for the Level-0 business fixes.

Covers ONLY the newly-fixed backend behaviours:
  * /market/land/buy on a zero lot -> storage.capacity recalculated for level 1
  * /market/land/buy on a zero lot -> zero_business_income += price and total_tax UNCHANGED
  * /auth/me exposes has_graduated_zero (False before, True after 0->1 upgrade)

ORDER DEPENDENT (module STATE) -> run with `-n 0`.
"""
import os
import sys

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

sys.path.insert(0, "/app/backend")
from business_config import get_storage_capacity  # noqa: E402

frontend_env = dotenv_values("/app/frontend/.env")
backend_env = dotenv_values("/app/backend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")).rstrip("/")
API = f"{BASE_URL}/api"
MONGO_URL = os.environ.get("MONGO_URL") or backend_env.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME") or backend_env.get("DB_NAME")

USER_EMAIL = "testuser@example.com"
USER_PASS = "Test1234!"
ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASS = os.environ.get("TEST_ADMIN_PASSWORD", "")
BIZ_TYPE = "helios"
BIZ_PRICE_TON = 6.5

STATE = {}


@pytest.fixture(scope="module")
def mdb():
    return MongoClient(MONGO_URL)[DB_NAME]


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    if r.status_code != 200:
        pytest.fail(f"login failed for {email}: {r.status_code} {r.text[:300]}")
    token = r.json().get("access_token") or r.json().get("token")
    if not token:
        pytest.fail("no token in login response")
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def user_client():
    return _login(USER_EMAIL, USER_PASS)


@pytest.fixture(scope="module")
def admin_client():
    return _login(ADMIN_EMAIL, ADMIN_PASS)


def _uids(mdb, email):
    u = mdb.users.find_one({"email": email}, {"_id": 0})
    assert u, f"user {email} missing"
    return u, {v for v in (u.get("id"), u.get("wallet_address"), u.get("email")) if v}


def reset_user(mdb, email, balance_ton=100.0, bonus=0.0):
    u, ids = _uids(mdb, email)
    mdb.businesses.delete_many({"owner": {"$in": list(ids)}})
    mdb.plots.delete_many({"owner": {"$in": list(ids)}})
    mdb.land_listings.delete_many({"seller_id": {"$in": list(ids)}})
    mdb.notifications.delete_many({"user_id": u["id"], "type": "zero_business_bought"})
    mdb.users.update_one({"email": email}, {
        "$set": {"balance_ton": balance_ton, "bonus_balance": bonus, "businesses_owned": [],
                 "plots_owned": [], "tutorial_active": False},
        "$unset": {"has_graduated_zero": ""},
    })
    return u, ids


def free_empty_cells(mdb, count=1):
    island = mdb.islands.find_one({"id": "ton_island"}, {"_id": 0})
    taken = {(p.get("x"), p.get("y")) for p in mdb.plots.find({"island_id": "ton_island"}, {"_id": 0, "x": 1, "y": 1})}
    out = []
    for c in island["cells"]:
        if c.get("is_empty") and not c.get("pre_business") and (c["x"], c["y"]) not in taken:
            out.append((c["x"], c["y"]))
            if len(out) >= count:
                break
    assert len(out) >= count
    return out


def claim_zero(mdb, client, cell):
    x, y = cell
    r = client.post(f"{API}/island/buy/{x}/{y}", timeout=30)
    assert r.status_code == 200, f"buy plot failed: {r.status_code} {r.text[:300]}"
    return client.post(f"{API}/island/build/{x}/{y}", json={"business_type": BIZ_TYPE}, timeout=30)


# ═══ /auth/me exposes has_graduated_zero ═════════════════════════════════════
class TestAuthMeGraduatedFlag:
    def test_auth_me_false_before_graduation(self, mdb, user_client):
        reset_user(mdb, USER_EMAIL, balance_ton=100.0)
        r = user_client.get(f"{API}/auth/me", timeout=30)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert "has_graduated_zero" in body, "field missing from /auth/me"
        assert body["has_graduated_zero"] is False, body["has_graduated_zero"]


# ═══ zero-lot marketplace purchase: capacity + treasury accounting ═══════════
class TestZeroLotBuyAccounting:
    def test_claim_zero(self, mdb, user_client):
        cell = free_empty_cells(mdb, 1)[0]
        r = claim_zero(mdb, user_client, cell)
        assert r.status_code == 200, r.text[:400]
        biz = mdb.businesses.find_one({"island_id": "ton_island", "x": cell[0], "y": cell[1]}, {"_id": 0})
        assert biz["level"] == 0 and biz.get("is_zero_business") is True, biz
        STATE["biz_id"] = biz["id"]
        STATE["biz_type"] = biz.get("business_type")
        STATE["level0_capacity"] = (biz.get("storage") or {}).get("capacity")
        lot = mdb.land_listings.find_one({"business_id": biz["id"], "is_zero_business": True}, {"_id": 0})
        assert lot and lot["status"] == "active", lot
        STATE["lot_id"] = lot["id"]
        STATE["lot_price"] = lot["price"]

    def test_capacity_recalculated_and_total_tax_untouched(self, mdb, admin_client):
        mdb.businesses.update_one({"id": STATE["biz_id"]}, {"$set": {"storage.items": {"energy": 42}}})
        tre = mdb.admin_stats.find_one({"type": "treasury"}) or {}
        zero_before = float(tre.get("zero_business_income", 0) or 0)
        tax_before = float(tre.get("total_tax", 0) or 0)

        r = admin_client.post(f"{API}/market/land/buy", json={"listing_id": STATE["lot_id"]}, timeout=60)
        assert r.status_code == 200, f"land/buy failed: {r.status_code} {r.text[:400]}"

        biz = mdb.businesses.find_one({"id": STATE["biz_id"]}, {"_id": 0})
        assert biz["level"] == 1, biz["level"]
        storage = biz.get("storage") or {}
        assert not any(float(v or 0) for v in (storage.get("items") or {}).values()), storage.get("items")
        expected_cap = get_storage_capacity(STATE["biz_type"], 1)
        assert float(storage.get("capacity")) == float(expected_cap), \
            f"capacity not recalculated: {storage.get('capacity')} != {expected_cap}"

        tre_after = mdb.admin_stats.find_one({"type": "treasury"}) or {}
        assert abs((float(tre_after.get("zero_business_income", 0) or 0) - zero_before) - STATE["lot_price"]) < 1e-6
        assert abs(float(tre_after.get("total_tax", 0) or 0) - tax_before) < 1e-6, \
            "total_tax must NOT be increased for zero-lot purchases"

    def test_old_owner_notified_and_reset(self, mdb):
        u, ids = _uids(mdb, USER_EMAIL)
        assert mdb.businesses.count_documents({"owner": {"$in": list(ids)}, "is_trial": {"$ne": True}}) == 0
        assert mdb.notifications.find_one({"user_id": u["id"], "type": "zero_business_bought"})


# ═══ /auth/me true after 0->1 upgrade ════════════════════════════════════════
class TestGraduationFlagAfterUpgrade:
    def test_upgrade_then_auth_me_true(self, mdb, user_client):
        u, ids = _uids(mdb, USER_EMAIL)
        mdb.plots.delete_many({"owner": {"$in": list(ids)}})
        mdb.users.update_one({"email": USER_EMAIL}, {"$set": {"balance_ton": 100.0, "bonus_balance": 0.0}})
        cell = free_empty_cells(mdb, 1)[0]
        r = claim_zero(mdb, user_client, cell)
        assert r.status_code == 200, r.text[:400]
        biz = mdb.businesses.find_one({"island_id": "ton_island", "x": cell[0], "y": cell[1]}, {"_id": 0})
        assert biz["level"] == 0

        up = user_client.post(f"{API}/business/{biz['id']}/upgrade", timeout=30)
        assert up.status_code == 200, f"upgrade failed: {up.status_code} {up.text[:400]}"
        assert up.json().get("new_level") == 1

        me = user_client.get(f"{API}/auth/me", timeout=30)
        assert me.status_code == 200
        assert me.json().get("has_graduated_zero") is True, me.json().get("has_graduated_zero")


@pytest.fixture(scope="module", autouse=True)
def cleanup(mdb):
    yield
    for email, bal in ((USER_EMAIL, 100.0), (ADMIN_EMAIL, 1230.0)):
        try:
            u, ids = _uids(mdb, email)
        except Exception:
            continue
        mdb.businesses.delete_many({"owner": {"$in": list(ids)}})
        mdb.plots.delete_many({"owner": {"$in": list(ids)}})
        mdb.land_listings.delete_many({"seller_id": {"$in": list(ids)}})
        mdb.market_listings.delete_many({"seller_id": {"$in": list(ids)}})
        mdb.notifications.delete_many({"user_id": u["id"], "type": "zero_business_bought"})
        mdb.users.update_one({"email": email}, {
            "$set": {"balance_ton": bal, "bonus_balance": 0.0, "businesses_owned": [], "plots_owned": []},
            "$unset": {"has_graduated_zero": ""}})
