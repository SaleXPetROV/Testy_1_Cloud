"""Iteration-9 tests: re-verification of the 2 fixes from iteration 8.

FIX A (frontend) is verified via Playwright, but the backend contract it relies
on (claiming an EXPENSIVE pre_business cell for 0 TON with a low balance) is
asserted here too.
FIX B (backend): grant_zero_consumption must EXCLUDE pseudo/TON-denominated
consumption lines ('profit_ton', 'ton', 'city', 'gram'). Claiming the arena
(consumes scrap 244 + profit_ton 33) must credit ONLY scrap.
REGRESSION: bio_farm -> cooling 24, helios -> biomass 26.

ORDER DEPENDENT (module STATE) -> run with `-n 0`.
"""
import os
import sys

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

sys.path.insert(0, "/app/backend")
from business_config import get_consumption_breakdown  # noqa: E402

frontend_env = dotenv_values("/app/frontend/.env")
backend_env = dotenv_values("/app/backend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")).rstrip("/")
API = f"{BASE_URL}/api"
MONGO_URL = os.environ.get("MONGO_URL") or backend_env.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME") or backend_env.get("DB_NAME")

USER_EMAIL = "testuser@example.com"
USER_PASS = "Test1234!"

PSEUDO = {"profit_ton", "ton", "city", "gram"}


@pytest.fixture(scope="module")
def mdb():
    return MongoClient(MONGO_URL)[DB_NAME]


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed {r.status_code} {r.text[:300]}"
    token = r.json().get("access_token") or r.json().get("token")
    assert token, "no token"
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def user_client():
    return _login(USER_EMAIL, USER_PASS)


def reset_user(mdb, email, balance_ton=100.0):
    u = mdb.users.find_one({"email": email}, {"_id": 0})
    assert u, f"missing user {email}"
    ids = [v for v in (u.get("id"), u.get("wallet_address"), u.get("email")) if v]
    mdb.businesses.delete_many({"owner": {"$in": ids}})
    mdb.plots.delete_many({"owner": {"$in": ids}})
    mdb.land_listings.delete_many({"seller_id": {"$in": ids}})
    mdb.users.update_one({"email": email}, {
        "$set": {"balance_ton": balance_ton, "bonus_balance": 0.0, "businesses_owned": [],
                 "plots_owned": [], "tutorial_active": False, "resources": {}},
        "$unset": {"has_graduated_zero": ""},
    })
    return u, ids


def cell_of_type(mdb, wanted_type):
    """Find a free pre_business cell of the given business type."""
    island = mdb.islands.find_one({"id": "ton_island"}, {"_id": 0})
    taken = {(p.get("x"), p.get("y")) for p in mdb.plots.find({"island_id": "ton_island"}, {"_id": 0, "x": 1, "y": 1})}
    best = None
    for c in island["cells"]:
        pre = c.get("pre_business")
        if not pre or c.get("owner") or (c["x"], c["y"]) in taken:
            continue
        btype = pre if isinstance(pre, str) else (pre.get("type") or pre.get("business_type"))
        if btype != wanted_type:
            continue
        price = float(c.get("price") or c.get("price_ton") or 0)
        if best is None or price > best[2]:
            best = (c["x"], c["y"], price)
    if best is None:
        pytest.skip(f"no free pre_business cell of type {wanted_type}")
    return best


def _claim(mdb, user_client, btype):
    u, _ = reset_user(mdb, USER_EMAIL, balance_ton=100.0)
    x, y, price = cell_of_type(mdb, btype)
    r = user_client.post(f"{API}/island/buy/{x}/{y}", timeout=40)
    assert r.status_code == 200, f"claim {btype} at ({x},{y}) failed: {r.status_code} {r.text[:400]}"
    biz = mdb.businesses.find_one({"island_id": "ton_island", "x": x, "y": y}, {"_id": 0})
    assert biz, "business not created"
    assert biz["level"] == 0, biz["level"]
    assert biz.get("is_zero_business") is True
    assert biz.get("business_type") == btype, biz.get("business_type")
    fresh = mdb.users.find_one({"email": USER_EMAIL}, {"_id": 0, "balance_ton": 1, "resources": 1, "bonus_balance": 1})
    return x, y, price, biz, fresh


# ═══ FIX B: pseudo resources excluded from the zero-claim grant ══════════════
class TestFixBPseudoResourceExcluded:
    def test_arena_claim_grants_only_real_resources(self, mdb, user_client):
        x, y, price, biz, fresh = _claim(mdb, user_client, "arena")
        assert price > 100, f"expected an EXPENSIVE arena cell (>100 TON), got {price} at ({x},{y})"
        # zero-stake: nothing charged
        assert float(fresh["balance_ton"]) == 100.0, fresh["balance_ton"]
        res = fresh.get("resources") or {}
        breakdown = get_consumption_breakdown("arena", 1)
        assert "profit_ton" in breakdown, "test premise broken: arena should consume profit_ton"
        # real resource granted
        assert float(res.get("scrap", 0)) == float(breakdown["scrap"]), res
        # pseudo lines NOT granted
        for k in PSEUDO:
            assert k not in res, f"pseudo resource {k} was granted: {res}"

    def test_arena_zero_lot_price_and_flags(self, mdb):
        biz = mdb.businesses.find_one({"business_type": "arena", "level": 0}, {"_id": 0})
        assert biz, "arena level-0 business missing"
        lot = mdb.land_listings.find_one({"business_id": biz["id"], "status": "active"}, {"_id": 0})
        assert lot, "auto zero lot missing"
        assert round(lot["price"], 4) == round(float(biz["zero_map_price"]) * 1.2, 4), lot["price"]
        assert lot.get("is_zero_business") is True and lot.get("admin_proceeds") is True
        assert lot.get("locked_delist") is True
        assert "_id" not in lot


# ═══ REGRESSION: normal consumption grants still work ════════════════════════
class TestRegressionConsumptionGrant:
    @pytest.mark.parametrize("btype,res_key", [("bio_farm", "cooling"), ("helios", "biomass")])
    def test_real_resource_granted(self, mdb, user_client, btype, res_key):
        _x, _y, _p, _biz, fresh = _claim(mdb, user_client, btype)
        expected = get_consumption_breakdown(btype, 1)[res_key]
        res = fresh.get("resources") or {}
        assert float(res.get(res_key, 0)) == float(expected), f"{btype}: {res}"
        for k in PSEUDO:
            assert k not in res, f"pseudo resource {k} granted for {btype}: {res}"


# ═══ REGRESSION: lock while holding a level-0 business ═══════════════════════
class TestRegressionLock:
    def test_second_buy_returns_423(self, mdb, user_client):
        _claim(mdb, user_client, "bio_farm")
        island = mdb.islands.find_one({"id": "ton_island"}, {"_id": 0})
        taken = {(p.get("x"), p.get("y")) for p in mdb.plots.find({"island_id": "ton_island"}, {"_id": 0, "x": 1, "y": 1})}
        target = None
        for c in island["cells"]:
            if c.get("pre_business") and not c.get("owner") and (c["x"], c["y"]) not in taken:
                target = (c["x"], c["y"])
                break
        assert target, "no second cell available"
        r = user_client.post(f"{API}/island/buy/{target[0]}/{target[1]}", timeout=40)
        assert r.status_code == 423, f"expected 423 zero_locked, got {r.status_code} {r.text[:300]}"
        body = r.json()
        detail = body.get("detail") if isinstance(body, dict) else body
        code = detail.get("code") if isinstance(detail, dict) else detail
        assert "zero_locked" in str(code), body


# ═══ REGRESSION: upgrade 0 -> 1 real-only ════════════════════════════════════
class TestRegressionUpgrade:
    def test_bonus_rejected_then_real_upgrade(self, mdb, user_client):
        _x, _y, _p, biz, _fresh = _claim(mdb, user_client, "bio_farm")
        map_price = float(biz["zero_map_price"])
        cost_ton = map_price
        # give enough bonus only -> must be rejected
        mdb.users.update_one({"email": USER_EMAIL}, {"$set": {"balance_ton": 0.0, "bonus_balance": cost_ton * 2}})
        r = user_client.post(f"{API}/business/{biz['id']}/upgrade", timeout=40)
        assert r.status_code == 400, f"expected 400, got {r.status_code} {r.text[:300]}"
        assert "zero_upgrade_need_real" in r.text, r.text[:300]
        # now with real balance
        mdb.users.update_one({"email": USER_EMAIL}, {"$set": {"balance_ton": cost_ton + 5}})
        r = user_client.post(f"{API}/business/{biz['id']}/upgrade", json={}, timeout=60)
        assert r.status_code == 200, f"upgrade failed: {r.status_code} {r.text[:400]}"
        after = mdb.businesses.find_one({"id": biz["id"]}, {"_id": 0})
        assert after["level"] == 1, after["level"]
        u = mdb.users.find_one({"email": USER_EMAIL}, {"_id": 0})
        assert u.get("has_graduated_zero") is True, "has_graduated_zero not set"
        lot = mdb.land_listings.find_one({"business_id": biz["id"], "status": "active"})
        assert lot is None, "auto zero lot was not removed after upgrade"

    def test_graduated_user_cannot_claim_again(self, mdb, user_client):
        u = mdb.users.find_one({"email": USER_EMAIL}, {"_id": 0})
        assert u.get("has_graduated_zero") is True
        ids = [v for v in (u.get("id"), u.get("wallet_address"), u.get("email")) if v]
        mdb.businesses.delete_many({"owner": {"$in": ids}})
        mdb.plots.delete_many({"owner": {"$in": ids}})
        mdb.users.update_one({"email": USER_EMAIL}, {"$set": {"balance_ton": 5.0, "businesses_owned": [], "plots_owned": []}})
        x, y, price = cell_of_type(mdb, "arena")
        r = user_client.post(f"{API}/island/buy/{x}/{y}", timeout=40)
        assert r.status_code != 200, "graduated user claimed an expensive cell for free!"
        assert r.status_code in (400, 402, 403), f"unexpected {r.status_code} {r.text[:300]}"


@pytest.fixture(scope="module", autouse=True)
def cleanup(mdb):
    yield
    reset_user(mdb, USER_EMAIL, balance_ton=100.0)
