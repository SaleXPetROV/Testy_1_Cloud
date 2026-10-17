"""Iteration-8 tests for the THREE new Level-0 (застолблённый) business fixes.

FIX 1 - auto zero marketplace lot carries full business data (name{en,ru}, icon,
        tier, produces, production_per_day, consumes) both in DB and via
        GET /api/market/land/listings.
FIX 3 - claiming a level-0 business grants the DAILY consumption norm into
        user.resources (bio_farm -> cooling 24, pre_business cell via /island/buy).
Covers BOTH claim paths: /island/build (empty plot) and /island/buy (cell with
a pre_business).

ORDER DEPENDENT (module STATE) -> run with `-n 0`.
"""
import os
import sys

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

sys.path.insert(0, "/app/backend")
from business_config import get_consumption_breakdown, get_production  # noqa: E402
from core.helpers import resolve_business_config  # noqa: E402

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


def reset_user(mdb, email, balance_ton=100.0):
    u, ids = _uids(mdb, email)
    mdb.businesses.delete_many({"owner": {"$in": list(ids)}})
    mdb.plots.delete_many({"owner": {"$in": list(ids)}})
    mdb.land_listings.delete_many({"seller_id": {"$in": list(ids)}})
    mdb.notifications.delete_many({"user_id": u["id"], "type": "zero_business_bought"})
    mdb.users.update_one({"email": email}, {
        "$set": {"balance_ton": balance_ton, "bonus_balance": 0.0, "businesses_owned": [],
                 "plots_owned": [], "tutorial_active": False, "resources": {}},
        "$unset": {"has_graduated_zero": ""},
    })
    return u, ids


def free_empty_cell(mdb):
    island = mdb.islands.find_one({"id": "ton_island"}, {"_id": 0})
    taken = {(p.get("x"), p.get("y")) for p in mdb.plots.find({"island_id": "ton_island"}, {"_id": 0, "x": 1, "y": 1})}
    for c in island["cells"]:
        if c.get("is_empty") and not c.get("pre_business") and (c["x"], c["y"]) not in taken:
            return c["x"], c["y"]
    pytest.fail("no free empty cell")


def free_pre_business_cell(mdb):
    island = mdb.islands.find_one({"id": "ton_island"}, {"_id": 0})
    taken = {(p.get("x"), p.get("y")) for p in mdb.plots.find({"island_id": "ton_island"}, {"_id": 0, "x": 1, "y": 1})}
    for c in island["cells"]:
        pre = c.get("pre_business")
        if pre and not c.get("owner") and (c["x"], c["y"]) not in taken:
            btype = pre if isinstance(pre, str) else (pre.get("type") or pre.get("business_type"))
            if get_consumption_breakdown(btype, 1):
                return c["x"], c["y"], btype
    pytest.fail("no free pre_business cell")


def assert_full_business_payload(biz_payload, btype):
    cfg = resolve_business_config(btype) or {}
    assert biz_payload, "listing has no business payload"
    assert biz_payload.get("type") == btype, biz_payload.get("type")
    name = biz_payload.get("name")
    assert isinstance(name, dict), f"name must be localized object, got {name!r}"
    assert name.get("en") == cfg["name"]["en"], name
    assert name.get("ru") == cfg["name"]["ru"], name
    assert biz_payload.get("icon") == cfg["icon"], biz_payload.get("icon")
    assert biz_payload.get("tier") == cfg["tier"], biz_payload.get("tier")
    assert biz_payload.get("produces") == cfg["produces"], biz_payload.get("produces")
    assert float(biz_payload.get("production_per_day")) == float(get_production(btype, 1)), \
        biz_payload.get("production_per_day")
    cons = biz_payload.get("consumes")
    assert isinstance(cons, dict) and cons == get_consumption_breakdown(btype, 1), cons
    assert biz_payload.get("level") == 1, biz_payload.get("level")


# ═══ FIX 1 + FIX 3 via /island/build (empty plot, bio_farm) ══════════════════
class TestBuildPathBioFarm:
    def test_claim_bio_farm_zero(self, mdb, user_client):
        reset_user(mdb, USER_EMAIL)
        x, y = free_empty_cell(mdb)
        r = user_client.post(f"{API}/island/buy/{x}/{y}", timeout=30)
        assert r.status_code == 200, f"plot buy failed: {r.status_code} {r.text[:300]}"
        r = user_client.post(f"{API}/island/build/{x}/{y}", json={"business_type": "bio_farm"}, timeout=30)
        assert r.status_code == 200, f"build failed: {r.status_code} {r.text[:400]}"
        biz = mdb.businesses.find_one({"island_id": "ton_island", "x": x, "y": y}, {"_id": 0})
        assert biz and biz["level"] == 0 and biz.get("is_zero_business") is True, biz
        STATE["biz_id"] = biz["id"]
        STATE["map_price"] = float(biz.get("zero_map_price") or 0)

    def test_fix3_daily_consumption_granted_build(self, mdb):
        u = mdb.users.find_one({"email": USER_EMAIL}, {"_id": 0, "resources": 1})
        res = u.get("resources") or {}
        assert float(res.get("cooling", 0)) == 24.0, f"bio_farm should grant cooling 24, got {res}"

    def test_fix1_lot_payload_in_db(self, mdb):
        lot = mdb.land_listings.find_one({"business_id": STATE["biz_id"], "is_zero_business": True}, {"_id": 0})
        assert lot and lot["status"] == "active", lot
        assert lot.get("admin_proceeds") is True and lot.get("locked_delist") is True, lot
        assert abs(lot["price"] - round(STATE["map_price"] * 1.2, 6)) < 1e-6, (lot["price"], STATE["map_price"])
        assert_full_business_payload(lot.get("business"), "bio_farm")
        STATE["lot_id"] = lot["id"]

    def test_fix1_lot_payload_via_api(self, user_client):
        r = user_client.get(f"{API}/market/land/listings", timeout=30)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        items = body if isinstance(body, list) else (body.get("listings") or body.get("items") or [])
        lot = next((li for li in items if li.get("id") == STATE["lot_id"]), None)
        assert lot, f"zero lot {STATE['lot_id']} not returned by /market/land/listings"
        assert lot.get("is_zero_business") is True, lot.get("is_zero_business")
        assert "_id" not in lot
        assert_full_business_payload(lot.get("business"), "bio_farm")


# ═══ FIX 1 + FIX 3 via /island/buy (cell WITH pre_business) ═════════════════
class TestBuyPathPreBusiness:
    def test_claim_pre_business_zero(self, mdb, admin_client):
        reset_user(mdb, ADMIN_EMAIL, balance_ton=1230.0)
        x, y, btype = free_pre_business_cell(mdb)
        STATE["pre_type"] = btype
        r = admin_client.post(f"{API}/island/buy/{x}/{y}", timeout=30)
        assert r.status_code == 200, f"buy failed: {r.status_code} {r.text[:400]}"
        body = r.json()
        assert body.get("is_zero_business") is True, body
        biz = mdb.businesses.find_one({"island_id": "ton_island", "x": x, "y": y}, {"_id": 0})
        assert biz and biz["level"] == 0, biz
        STATE["biz2_id"] = biz["id"]
        STATE["map_price2"] = float(biz.get("zero_map_price") or 0)

    def test_fix3_daily_consumption_granted_buy(self, mdb):
        expected = get_consumption_breakdown(STATE["pre_type"], 1) or {}
        assert expected, f"no consumption norm for {STATE['pre_type']}"
        u = mdb.users.find_one({"email": ADMIN_EMAIL}, {"_id": 0, "resources": 1})
        res = u.get("resources") or {}
        # iteration-9 FIX B: pseudo/TON-denominated lines are intentionally NOT granted
        pseudo = {"profit_ton", "ton", "city", "gram"}
        for k, v in expected.items():
            if k in pseudo:
                assert k not in res, f"pseudo resource {k} must NOT be granted, got {res}"
                continue
            assert float(res.get(k, 0)) == float(v), f"{STATE['pre_type']} should grant {k}={v}, got {res}"

    def test_fix1_lot_payload_in_db_buy_path(self, mdb):
        lot = mdb.land_listings.find_one({"business_id": STATE["biz2_id"], "is_zero_business": True}, {"_id": 0})
        assert lot, "no auto lot for buy-path claim"
        assert abs(lot["price"] - round(STATE["map_price2"] * 1.2, 6)) < 1e-6, (lot["price"], STATE["map_price2"])
        assert_full_business_payload(lot.get("business"), STATE["pre_type"])


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
            "$set": {"balance_ton": bal, "bonus_balance": 0.0, "businesses_owned": [], "plots_owned": [],
                     "resources": {}},
            "$unset": {"has_graduated_zero": ""}})
