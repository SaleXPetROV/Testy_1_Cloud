"""Level-0 (застолблённый) business onboarding mechanic — end-to-end backend tests.

Covers: zero-stake build, global LOCK (423), credit block (403), delist block (403),
sell/demolish block (403), upgrade 0->1 (real-only), bonus-block rejection,
graduated normal level-1 build, marketplace purchase of a zero lot by another
player (admin proceeds + notification + owner reset), resource-sale -> bonus_balance.

Tests are ORDER DEPENDENT (module scoped state) — run the file as a whole.
"""
import os
import uuid
from datetime import datetime, timezone

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

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


# ─── fixtures ────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def mdb():
    client = MongoClient(MONGO_URL)
    return client[DB_NAME]


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    if r.status_code != 200:
        pytest.fail(f"login failed for {email}: {r.status_code} {r.text[:300]}")
    body = r.json()
    token = body.get("access_token") or body.get("token")
    if not token:
        pytest.fail(f"no token in login response: {str(body)[:300]}")
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def user_client():
    return _login(USER_EMAIL, USER_PASS)


@pytest.fixture(scope="module")
def admin_client():
    return _login(ADMIN_EMAIL, ADMIN_PASS)


# ─── helpers ─────────────────────────────────────────────────────────────────
def _uids(mdb, email):
    u = mdb.users.find_one({"email": email}, {"_id": 0})
    assert u, f"user {email} missing in DB"
    return u, {v for v in (u.get("id"), u.get("wallet_address"), u.get("email")) if v}


def reset_user(mdb, email, balance_ton=100.0, bonus=0.0):
    """Clean slate: no businesses, no plots, not graduated."""
    u, ids = _uids(mdb, email)
    mdb.businesses.delete_many({"owner": {"$in": list(ids)}})
    for p in mdb.plots.find({"owner": {"$in": list(ids)}}, {"_id": 0, "id": 1}):
        mdb.land_listings.delete_many({"plot_id": p["id"]})
    mdb.plots.delete_many({"owner": {"$in": list(ids)}})
    mdb.land_listings.delete_many({"seller_id": {"$in": list(ids)}})
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
    assert len(out) >= count, f"not enough free empty cells: {len(out)}"
    return out


def claim_zero(mdb, client, cell):
    """buy empty plot (paid) then build -> level 0 claim. Returns build response."""
    x, y = cell
    r = client.post(f"{API}/island/buy/{x}/{y}", timeout=30)
    assert r.status_code == 200, f"buy plot {cell} failed: {r.status_code} {r.text[:300]}"
    b = client.post(f"{API}/island/build/{x}/{y}", json={"business_type": BIZ_TYPE}, timeout=30)
    return b


# ═══ 1. zero-stake via build ═════════════════════════════════════════════════
class TestZeroStakeClaim:
    def test_claim_level0_via_build(self, mdb, user_client):
        u, ids = reset_user(mdb, USER_EMAIL, balance_ton=100.0, bonus=0.0)
        cells = free_empty_cells(mdb, 4)
        STATE["cells"] = cells
        before = mdb.users.find_one({"email": USER_EMAIL}, {"_id": 0})["balance_ton"]
        r = claim_zero(mdb, user_client, cells[0])
        assert r.status_code == 200, f"build failed: {r.status_code} {r.text[:400]}"
        body = r.json()
        assert body.get("is_zero_business") is True, body
        assert float(body.get("cost_ton", body.get("paid_ton", 0)) or 0) == 0.0, body

        biz = mdb.businesses.find_one({"island_id": "ton_island", "x": cells[0][0], "y": cells[0][1]}, {"_id": 0})
        assert biz and biz["level"] == 0 and biz.get("is_zero_business") is True, biz
        assert abs(float(biz.get("zero_map_price")) - BIZ_PRICE_TON) < 1e-6, biz.get("zero_map_price")
        STATE["biz_id"] = biz["id"]

        # only the plot purchase price was charged, business itself cost 0
        after = mdb.users.find_one({"email": USER_EMAIL}, {"_id": 0})["balance_ton"]
        assert after <= before, (before, after)

        lot = mdb.land_listings.find_one({"business_id": biz["id"], "is_zero_business": True}, {"_id": 0})
        assert lot, "auto marketplace lot missing"
        assert abs(lot["price"] - round(BIZ_PRICE_TON * 1.2, 6)) < 1e-6, lot["price"]
        assert lot.get("admin_proceeds") is True and lot.get("locked_delist") is True, lot
        assert lot.get("status") == "active"
        STATE["lot_id"] = lot["id"]
        STATE["lot_price"] = lot["price"]

    def test_cell_endpoint_exposes_zero_fields(self, user_client):
        x, y = STATE["cells"][0]
        r = user_client.get(f"{API}/island/cell/{x}/{y}", timeout=30)
        assert r.status_code == 200, r.text[:300]
        biz = r.json().get("business") or {}
        assert biz.get("is_zero_business") is True, biz
        assert biz.get("level") == 0, biz
        assert biz.get("owner_username"), biz
        assert biz.get("zero_listing_id") == STATE["lot_id"], biz
        assert abs(float(biz.get("zero_price_city")) - round(STATE["lot_price"] * 1000, 2)) < 0.01, biz


# ═══ 2. LOCK while holding level-0 ═══════════════════════════════════════════
class TestZeroLock:
    def test_buy_plot_locked_423(self, user_client):
        x, y = STATE["cells"][1]
        r = user_client.post(f"{API}/island/buy/{x}/{y}", timeout=30)
        assert r.status_code == 423, f"expected 423 got {r.status_code} {r.text[:300]}"
        detail = r.json().get("detail")
        assert isinstance(detail, dict) and detail.get("code") == "zero_locked", detail

    def test_build_locked_423(self, mdb, user_client):
        """Give the user a second EMPTY plot directly in Mongo, then BUILD must 423."""
        u, ids = _uids(mdb, USER_EMAIL)
        x, y = STATE["cells"][2]
        pid = str(uuid.uuid4())
        mdb.plots.insert_one({
            "id": pid, "island_id": "ton_island", "x": x, "y": y,
            "owner": u["id"], "owner_username": u.get("username"), "is_empty": True,
            "purchased_at": datetime.now(timezone.utc).isoformat(),
        })
        STATE["extra_plot_id"] = pid
        try:
            r = user_client.post(f"{API}/island/build/{x}/{y}", json={"business_type": BIZ_TYPE}, timeout=30)
            assert r.status_code == 423, f"expected 423 got {r.status_code} {r.text[:300]}"
            detail = r.json().get("detail")
            assert isinstance(detail, dict) and detail.get("code") == "zero_locked", detail
        finally:
            mdb.plots.delete_one({"id": pid})

    def test_credit_blocked_403(self, user_client):
        bid = STATE["biz_id"]
        r1 = user_client.get(f"{API}/credit/calculate/{bid}", timeout=30)
        assert r1.status_code == 403, f"credit/calculate expected 403 got {r1.status_code} {r1.text[:300]}"
        r2 = user_client.post(f"{API}/credit/apply", json={
            "collateral_business_id": bid, "amount": 1.0,
            "salary_deduction_percent": 10, "lender_type": "government",
        }, timeout=30)
        assert r2.status_code == 403, f"credit/apply expected 403 got {r2.status_code} {r2.text[:300]}"

    def test_delist_blocked_403(self, user_client):
        r = user_client.delete(f"{API}/market/land/listing/{STATE['lot_id']}", timeout=30)
        assert r.status_code == 403, f"expected 403 got {r.status_code} {r.text[:300]}"
        assert "ZERO_BUSINESS_LOCKED" in r.text, r.text[:300]

    def test_sell_blocked_403(self, user_client):
        r = user_client.post(f"{API}/business/{STATE['biz_id']}/sell", json={"price": 5.0}, timeout=30)
        assert r.status_code == 403, f"sell expected 403 got {r.status_code} {r.text[:300]}"

    def test_demolish_blocked_403(self, user_client):
        r = user_client.post(f"{API}/businesses/demolish/{STATE['biz_id']}", timeout=30)
        assert r.status_code == 403, f"demolish expected 403 got {r.status_code} {r.text[:300]}"


# ═══ 3. resource sale proceeds -> bonus_balance for a level-0 holder ══════════
class TestResourceSaleBonusCrediting:
    def test_seller_with_zero_business_credited_on_bonus(self, mdb, admin_client):
        seller, sids = _uids(mdb, USER_EMAIL)
        admin, aids = _uids(mdb, ADMIN_EMAIL)
        # admin needs >=1 real business to be allowed to buy resources + warehouse room
        if mdb.businesses.count_documents({"owner": {"$in": list(aids)}, "is_trial": {"$ne": True}}) == 0:
            mdb.businesses.insert_one({
                "id": str(uuid.uuid4()), "owner": admin["id"], "owner_username": admin.get("username"),
                "business_type": BIZ_TYPE, "type": BIZ_TYPE, "level": 1, "island_id": "seed_none",
                "x": -99, "y": -99, "storage": {"resources": {}, "capacity": 1000},
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            STATE["admin_seed_biz"] = True
        mdb.users.update_one({"email": ADMIN_EMAIL}, {"$set": {"balance_ton": 1230.0, "bonus_balance": 0.0}})

        listing_id = str(uuid.uuid4())
        mdb.market_listings.insert_one({
            "id": listing_id, "seller_id": seller["id"], "seller_email": seller.get("email"),
            "seller_username": seller.get("username"), "business_id": STATE["biz_id"],
            "resource_type": "energy", "amount": 100, "price_per_unit": 0.01,
            "total_price": 1.0, "status": "active",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        STATE["res_listing"] = listing_id
        before = mdb.users.find_one({"email": USER_EMAIL}, {"_id": 0})
        r = admin_client.post(f"{API}/market/buy", json={"listing_id": listing_id, "amount": 10}, timeout=30)
        assert r.status_code == 200, f"market/buy failed: {r.status_code} {r.text[:400]}"
        after = mdb.users.find_one({"email": USER_EMAIL}, {"_id": 0})
        d_bonus = float(after.get("bonus_balance", 0)) - float(before.get("bonus_balance", 0))
        d_real = float(after.get("balance_ton", 0)) - float(before.get("balance_ton", 0))
        assert d_bonus > 0, f"bonus_balance not credited (delta {d_bonus})"
        assert abs(d_real) < 1e-9, f"real balance_ton changed by {d_real}, expected 0"
        mdb.market_listings.delete_one({"id": listing_id})


# ═══ 4. upgrade 0->1 must reject bonus-only funds ════════════════════════════
class TestUpgradeBonusRejected:
    def test_bonus_only_rejected_400(self, mdb, user_client):
        mdb.users.update_one({"email": USER_EMAIL}, {"$set": {"balance_ton": 0.5, "bonus_balance": 100.0}})
        r = user_client.post(f"{API}/business/{STATE['biz_id']}/upgrade", timeout=30)
        assert r.status_code == 400, f"expected 400 got {r.status_code} {r.text[:300]}"
        detail = r.json().get("detail")
        assert isinstance(detail, dict) and detail.get("code") == "zero_upgrade_need_real", detail
        assert abs(float(detail.get("need_city")) - BIZ_PRICE_TON * 1000) < 0.01, detail
        # nothing changed
        biz = mdb.businesses.find_one({"id": STATE["biz_id"]}, {"_id": 0})
        assert biz["level"] == 0, biz["level"]
        u = mdb.users.find_one({"email": USER_EMAIL}, {"_id": 0})
        assert u.get("has_graduated_zero") is not True
        assert abs(float(u["bonus_balance"]) - 100.0) < 1e-6


# ═══ 5. another player buys the level-0 lot from the marketplace ═════════════
class TestMarketplaceZeroLotPurchase:
    def test_admin_buys_zero_lot(self, mdb, admin_client):
        seller, sids = _uids(mdb, USER_EMAIL)
        admin, aids = _uids(mdb, ADMIN_EMAIL)
        # storage must be emptied for the buyer -> seed some resources first
        mdb.businesses.update_one({"id": STATE["biz_id"]}, {"$set": {"storage.items": {"energy": 42}}})
        treas_before = float((mdb.admin_stats.find_one({"type": "treasury"}) or {}).get("zero_business_income", 0) or 0)
        bal_before = float(mdb.users.find_one({"email": ADMIN_EMAIL})["balance_ton"])
        seller_bonus_before = float(seller.get("bonus_balance", 0) or 0)

        r = admin_client.post(f"{API}/market/land/buy", json={"listing_id": STATE["lot_id"]}, timeout=60)
        assert r.status_code == 200, f"land/buy failed: {r.status_code} {r.text[:400]}"

        biz = mdb.businesses.find_one({"id": STATE["biz_id"]}, {"_id": 0})
        assert biz, "business vanished"
        assert biz["level"] == 1, f"buyer must get level-1, got {biz['level']}"
        assert biz.get("is_zero_business") in (None, False), biz.get("is_zero_business")
        assert biz.get("owner") in aids, f"owner not transferred: {biz.get('owner')}"
        stored = (biz.get("storage") or {}).get("items") or {}
        assert all(float(v or 0) == 0 for v in stored.values()), f"storage not emptied: {stored}"

        # admin treasury credited with the full lot price
        treas_after = float((mdb.admin_stats.find_one({"type": "treasury"}) or {}).get("zero_business_income", 0) or 0)
        assert abs((treas_after - treas_before) - STATE["lot_price"]) < 1e-6, (treas_before, treas_after)
        bal_after = float(mdb.users.find_one({"email": ADMIN_EMAIL})["balance_ton"])
        assert abs((bal_before - bal_after) - STATE["lot_price"]) < 1e-6, (bal_before, bal_after)

        # old owner: lost the business, keeps bonus, gets notification, listing gone
        assert mdb.businesses.count_documents({"owner": {"$in": list(sids)}, "is_trial": {"$ne": True}}) == 0
        seller_after = mdb.users.find_one({"email": USER_EMAIL}, {"_id": 0})
        assert abs(float(seller_after.get("bonus_balance", 0)) - seller_bonus_before) < 1e-6, "bonus lost"
        assert seller_after.get("has_graduated_zero") is not True
        notif = mdb.notifications.find_one({"user_id": seller["id"], "type": "zero_business_bought"})
        assert notif, "zero_business_bought notification missing"
        assert notif.get("title") and notif.get("message")
        lot = mdb.land_listings.find_one({"id": STATE["lot_id"]}, {"_id": 0})
        assert (lot is None) or lot.get("status") != "active", lot

    def test_old_owner_can_claim_again(self, mdb, user_client):
        # keep within the 3-plot limit
        u, ids = _uids(mdb, USER_EMAIL)
        mdb.plots.delete_many({"owner": {"$in": list(ids)}})
        mdb.users.update_one({"email": USER_EMAIL}, {"$set": {"balance_ton": 100.0}})
        cell = free_empty_cells(mdb, 1)[0]
        STATE["cell_second"] = cell
        r = claim_zero(mdb, user_client, cell)
        assert r.status_code == 200, f"re-claim build failed: {r.status_code} {r.text[:400]}"
        assert r.json().get("is_zero_business") is True, r.json()
        biz = mdb.businesses.find_one({"island_id": "ton_island", "x": cell[0], "y": cell[1]}, {"_id": 0})
        assert biz["level"] == 0, biz
        STATE["biz_id2"] = biz["id"]
        lot = mdb.land_listings.find_one({"business_id": biz["id"], "is_zero_business": True}, {"_id": 0})
        assert lot and lot.get("status") == "active", lot
        STATE["lot_id2"] = lot["id"]


# ═══ 6. successful upgrade 0->1 + graduation ═════════════════════════════════
class TestUpgradeSuccessAndGraduation:
    def test_upgrade_with_real_balance(self, mdb, user_client):
        mdb.users.update_one({"email": USER_EMAIL}, {"$set": {"balance_ton": 50.0, "bonus_balance": 100.0}})
        r = user_client.post(f"{API}/business/{STATE['biz_id2']}/upgrade", timeout=30)
        assert r.status_code == 200, f"upgrade failed: {r.status_code} {r.text[:400]}"
        body = r.json()
        assert body.get("new_level") == 1, body
        biz = mdb.businesses.find_one({"id": STATE["biz_id2"]}, {"_id": 0})
        assert biz["level"] == 1 and not biz.get("is_zero_business"), biz
        u = mdb.users.find_one({"email": USER_EMAIL}, {"_id": 0})
        assert abs(float(u["balance_ton"]) - (50.0 - BIZ_PRICE_TON)) < 1e-6, u["balance_ton"]
        assert abs(float(u["bonus_balance"]) - 100.0) < 1e-6, "bonus must not be touched"
        assert u.get("has_graduated_zero") is True, "has_graduated_zero not set"
        assert mdb.land_listings.count_documents({"id": STATE["lot_id2"], "status": "active"}) == 0, "auto lot not removed"

    def test_graduated_user_builds_normal_level1(self, mdb, user_client):
        u, ids = _uids(mdb, USER_EMAIL)
        mdb.users.update_one({"email": USER_EMAIL}, {"$set": {"balance_ton": 60.0, "bonus_balance": 0.0}})
        cell = free_empty_cells(mdb, 1)[0]
        x, y = cell
        r = user_client.post(f"{API}/island/buy/{x}/{y}", timeout=30)
        assert r.status_code == 200, f"buy plot failed: {r.status_code} {r.text[:300]}"
        bal_after_plot = float(mdb.users.find_one({"email": USER_EMAIL})["balance_ton"])
        b = user_client.post(f"{API}/island/build/{x}/{y}", json={"business_type": BIZ_TYPE}, timeout=30)
        assert b.status_code == 200, f"build failed: {b.status_code} {b.text[:400]}"
        assert b.json().get("is_zero_business") in (False, None), b.json()
        biz = mdb.businesses.find_one({"island_id": "ton_island", "x": x, "y": y}, {"_id": 0})
        assert biz["level"] == 1, biz
        bal_after_build = float(mdb.users.find_one({"email": USER_EMAIL})["balance_ton"])
        assert abs((bal_after_plot - bal_after_build) - BIZ_PRICE_TON) < 1e-6, (bal_after_plot, bal_after_build)

    def test_graduated_user_cannot_claim_zero_again(self, mdb, user_client):
        """Wipe businesses (0 businesses) but graduated -> build must charge real price."""
        u, ids = _uids(mdb, USER_EMAIL)
        mdb.businesses.delete_many({"owner": {"$in": list(ids)}})
        mdb.plots.delete_many({"owner": {"$in": list(ids)}})
        mdb.users.update_one({"email": USER_EMAIL}, {"$set": {"balance_ton": 60.0, "bonus_balance": 0.0}})
        cell = free_empty_cells(mdb, 1)[0]
        x, y = cell
        assert user_client.post(f"{API}/island/buy/{x}/{y}", timeout=30).status_code == 200
        b = user_client.post(f"{API}/island/build/{x}/{y}", json={"business_type": BIZ_TYPE}, timeout=30)
        assert b.status_code == 200, b.text[:300]
        biz = mdb.businesses.find_one({"island_id": "ton_island", "x": x, "y": y}, {"_id": 0})
        assert biz["level"] == 1, f"graduated user got level {biz['level']} (must be 1)"
        assert mdb.land_listings.count_documents({"business_id": biz["id"], "is_zero_business": True}) == 0


# ═══ cleanup ═════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module", autouse=True)
def cleanup(mdb):
    yield
    for email in (USER_EMAIL, ADMIN_EMAIL):
        try:
            u, ids = _uids(mdb, email)
        except Exception:
            continue
        mdb.businesses.delete_many({"owner": {"$in": list(ids)}})
        mdb.plots.delete_many({"owner": {"$in": list(ids)}})
        mdb.land_listings.delete_many({"seller_id": {"$in": list(ids)}})
        mdb.market_listings.delete_many({"seller_id": {"$in": list(ids)}})
        mdb.notifications.delete_many({"user_id": u["id"], "type": "zero_business_bought"})
    mdb.users.update_one({"email": USER_EMAIL}, {"$set": {"balance_ton": 100.0, "bonus_balance": 0.0,
                                                          "businesses_owned": [], "plots_owned": []},
                                                 "$unset": {"has_graduated_zero": ""}})
    mdb.users.update_one({"email": ADMIN_EMAIL}, {"$set": {"balance_ton": 1230.0, "bonus_balance": 0.0,
                                                           "businesses_owned": [], "plots_owned": []},
                                                  "$unset": {"has_graduated_zero": ""}})
