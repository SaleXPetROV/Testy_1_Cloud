"""Iteration 6 — FORCED SEIZURE (GRAM CITY repossession), stats bonus TON, admin secret audit.

Covers:
  • core.seizure.process_seizures — durability_zero path
  • core.seizure.process_seizures — credit_default path
  • DELETE /api/market/land/listing/{id} → 403 SEIZED_CONTACT_SUPPORT for former owner
  • GET/POST /api/admin/credits/seized (list / price / return)
  • GET/POST /api/sys-ops/seized (support parity, admin JWT accepted)
  • POST /api/market/land/buy on a seized listing (restore + pay former owner)
  • GET /api/stats total_volume_ton includes bonus_balance
  • Admin user endpoints must not leak secrets
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

sys.path.insert(0, "/app/backend")

_fe = dotenv_values("/app/frontend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or _fe.get("REACT_APP_BACKEND_URL")).rstrip("/")

_be = dotenv_values("/app/backend/.env")
MONGO_URL = _be.get("MONGO_URL") or os.environ["MONGO_URL"]
DB_NAME = _be.get("DB_NAME") or os.environ["DB_NAME"]

ADMIN = {"email": "sanyanazarov212@gmail.com", "password": os.environ.get("TEST_ADMIN_PASSWORD", "")}
USER = {"email": "testuser@example.com", "password": "Test1234!"}

PREFIX = "TEST_SEIZ6_"
SECRET_KEYS = ("hashed_password", "password", "password_hash",
               "two_factor_secret", "totp_secret", "backup_codes")


def _iso(dt):
    return dt.isoformat()


@pytest.fixture(scope="module")
def db():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


def _login(creds):
    r = requests.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=30)
    if r.status_code != 200:
        pytest.fail(f"login failed {creds['email']}: {r.status_code} {r.text[:300]}")
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok, f"no token in login response: {r.text[:300]}"
    return tok


@pytest.fixture(scope="module")
def admin_token():
    return _login(ADMIN)


@pytest.fixture(scope="module")
def user_token():
    return _login(USER)


def H(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def run_seizures():
    import importlib
    from motor.motor_asyncio import AsyncIOMotorClient
    seizure = importlib.import_module("core.seizure")

    async def _go():
        cli = AsyncIOMotorClient(MONGO_URL)
        try:
            return await seizure.process_seizures(cli[DB_NAME])
        finally:
            cli.close()
    return asyncio.run(_go())


def seed_business(db, owner_id, owner_username, suffix, *, durability=0,
                  zero_since_days=8, x=None, y=None, level=3, btype="helios"):
    bid = f"{PREFIX}BIZ_{suffix}"
    pid = f"{PREFIX}PLOT_{suffix}"
    x = x if x is not None else 900 + hash(suffix) % 50
    y = y if y is not None else 900 + hash(suffix) % 37
    db.plots.delete_many({"id": pid})
    db.businesses.delete_many({"id": bid})
    db.plots.insert_one({
        "id": pid, "city_id": "ton_island", "x": x, "y": y,
        "owner": owner_id, "owner_username": owner_username,
        "business_id": bid, "price": 5, "is_available": False,
    })
    doc = {
        "id": bid, "plot_id": pid, "business_type": btype, "level": level,
        "durability": durability, "xp": 0, "owner": owner_id,
        "owner_username": owner_username, "city_id": "ton_island",
        "plot_x": x, "plot_y": y, "status": "active", "is_active": True,
        "created_at": _iso(datetime.now(timezone.utc) - timedelta(days=30)),
    }
    if zero_since_days is not None:
        doc["zero_durability_since"] = _iso(
            datetime.now(timezone.utc) - timedelta(days=zero_since_days))
    db.businesses.insert_one(doc)
    return bid, pid


def cleanup(db):
    ids = [b["id"] for b in db.businesses.find({"id": {"$regex": f"^{PREFIX}"}}, {"id": 1})]
    db.businesses.delete_many({"id": {"$regex": f"^{PREFIX}"}})
    db.plots.delete_many({"id": {"$regex": f"^{PREFIX}"}})
    db.credits.delete_many({"id": {"$regex": f"^{PREFIX}"}})
    if ids:
        db.land_listings.delete_many({"business_id": {"$in": ids}})


@pytest.fixture(scope="module", autouse=True)
def _cleanup_module(db):
    cleanup(db)
    yield
    cleanup(db)


@pytest.fixture(scope="module")
def users(db):
    u = db.users.find_one({"email": USER["email"]}, {"_id": 0})
    a = db.users.find_one({"email": ADMIN["email"]}, {"_id": 0})
    assert u and a, "seed users missing"
    return {"user": u, "admin": a}


# ───────────────────────── Seizure: durability path ─────────────────────────
class TestSeizureDurability:
    def test_durability_seizure_and_flow(self, db, users, admin_token, user_token):
        u = users["user"]
        bid, pid = seed_business(db, u["id"], u.get("username"), "DUR", x=911, y=911)

        res = run_seizures()
        print("process_seizures:", res)

        biz = db.businesses.find_one({"id": bid}, {"_id": 0})
        assert biz["is_seized"] is True, biz
        assert biz["seizure_reason"] == "durability_zero"
        assert biz["status"] == "on_sale"

        lst = db.land_listings.find_one({"business_id": bid}, {"_id": 0})
        assert lst, "no land_listing created for seized business"
        assert lst["is_seized"] is True
        assert lst["seller_username"] == "GRAM CITY"
        assert lst["price"] > 0, lst
        assert lst["former_owner_id"] == u["id"]
        assert lst["status"] == "active"
        print("frozen price:", lst["price"])

        listing_id = lst["id"]

        # --- former owner cannot delist ---
        r = requests.delete(f"{BASE_URL}/api/market/land/listing/{listing_id}",
                            headers=H(user_token), timeout=30)
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text[:300]}"
        assert r.json().get("detail") == "SEIZED_CONTACT_SUPPORT", r.text[:300]

        # --- admin seized list ---
        r = requests.get(f"{BASE_URL}/api/admin/credits/seized", headers=H(admin_token), timeout=30)
        assert r.status_code == 200, r.text[:300]
        rows = r.json()["seized"]
        row = next((x for x in rows if x["listing_id"] == listing_id), None)
        assert row, f"seized listing not in admin list: {[x['listing_id'] for x in rows][:5]}"
        assert row["seizure_reason"] == "durability_zero"
        assert row["former_owner_username"] == u.get("username")
        assert row["sold"] is False
        assert row["business_full"] and row["business_full"]["id"] == bid
        assert "_id" not in row and "_id" not in (row["business_full"] or {})

        # --- support parity (admin JWT accepted by require_support_agent) ---
        r = requests.get(f"{BASE_URL}/api/sys-ops/seized", headers=H(admin_token), timeout=30)
        assert r.status_code == 200, f"/api/sys-ops/seized -> {r.status_code} {r.text[:200]}"
        assert any(x["listing_id"] == listing_id for x in r.json()["seized"])

        # --- edit price ---
        r = requests.post(f"{BASE_URL}/api/admin/credits/seized/{listing_id}/price",
                          json={"price": 12.5}, headers=H(admin_token), timeout=30)
        assert r.status_code == 200, r.text[:300]
        assert db.land_listings.find_one({"id": listing_id})["price"] == 12.5
        assert db.businesses.find_one({"id": bid})["seizure_price"] == 12.5

        # --- buy as admin: restores + pays former owner ---
        db.users.update_one({"id": users["admin"]["id"]}, {"$set": {"balance_ton": 500.0}})
        before = db.users.find_one({"id": u["id"]}, {"_id": 0}).get("balance_ton", 0)
        r = requests.post(f"{BASE_URL}/api/market/land/buy", json={"listing_id": listing_id},
                          headers=H(admin_token), timeout=60)
        assert r.status_code == 200, f"buy failed {r.status_code}: {r.text[:400]}"
        biz = db.businesses.find_one({"id": bid}, {"_id": 0})
        assert biz["owner"] == users["admin"]["id"], biz["owner"]
        assert biz["durability"] == 100
        assert biz.get("is_seized") in (False, None)
        assert biz["status"] == "active"
        assert biz.get("seizure_reason") is None
        after = db.users.find_one({"id": u["id"]}, {"_id": 0}).get("balance_ton", 0)
        gain = round(after - before, 6)
        print(f"former owner paid: {gain} (price 12.5)")
        assert 0 < gain <= 12.5, f"former owner gain {gain} not in (0, 12.5]"
        lst = db.land_listings.find_one({"id": listing_id}, {"_id": 0})
        assert lst["status"] == "sold"
        assert lst["buyer_id"] == users["admin"]["id"]

        # sold row still listed for admin, price edit + return must be rejected
        r = requests.post(f"{BASE_URL}/api/admin/credits/seized/{listing_id}/price",
                          json={"price": 9.0}, headers=H(admin_token), timeout=30)
        assert r.status_code >= 400, f"price edit on SOLD listing allowed: {r.status_code} {r.text[:200]}"
        r = requests.post(f"{BASE_URL}/api/admin/credits/seized/{listing_id}/return",
                          headers=H(admin_token), timeout=30)
        assert r.status_code >= 400, f"return on SOLD listing allowed: {r.status_code} {r.text[:200]}"

    def test_return_seized_to_owner(self, db, users, admin_token):
        u = users["user"]
        bid, pid = seed_business(db, u["id"], u.get("username"), "RET", x=913, y=913)
        run_seizures()
        lst = db.land_listings.find_one({"business_id": bid}, {"_id": 0})
        assert lst and lst["is_seized"]
        r = requests.post(f"{BASE_URL}/api/admin/credits/seized/{lst['id']}/return",
                          headers=H(admin_token), timeout=30)
        assert r.status_code == 200, r.text[:300]
        biz = db.businesses.find_one({"id": bid}, {"_id": 0})
        assert biz["owner"] == u["id"]
        assert biz["durability"] == 100
        assert biz["is_seized"] is False
        assert biz.get("seizure_reason") is None
        assert biz["status"] == "active"
        after = db.land_listings.find_one({"id": lst["id"]}, {"_id": 0})
        assert after["status"] == "cancelled"
        assert after.get("returned_to_owner") is True
        plot = db.plots.find_one({"id": pid}, {"_id": 0})
        assert not plot.get("on_sale")

    def test_seizure_idempotent_and_not_early(self, db, users):
        u = users["user"]
        # only 2 days at zero durability → must NOT be seized
        bid, _ = seed_business(db, u["id"], u.get("username"), "EARLY",
                               zero_since_days=2, x=915, y=915)
        run_seizures()
        biz = db.businesses.find_one({"id": bid}, {"_id": 0})
        assert not biz.get("is_seized"), "business seized before the 7-day threshold"
        assert db.land_listings.count_documents({"business_id": bid}) == 0

        # already seized business must not be double-listed
        bid2, _ = seed_business(db, u["id"], u.get("username"), "IDEM", x=917, y=917)
        run_seizures()
        run_seizures()
        assert db.land_listings.count_documents({"business_id": bid2}) == 1


# ─────────────────────── Seizure: credit-default path ───────────────────────
class TestSeizureCreditDefault:
    def test_credit_default_seizure_and_debt_repayment(self, db, users, admin_token):
        u = users["user"]
        bid, pid = seed_business(db, u["id"], u.get("username"), "CRED",
                                 durability=100, zero_since_days=None, x=921, y=921)
        credit_id = f"{PREFIX}CREDIT_1"
        db.credits.delete_many({"id": credit_id})
        db.credits.insert_one({
            "id": credit_id, "user_id": u["id"], "username": u.get("username"),
            "collateral_business_id": bid, "status": "overdue",
            "amount": 20.0, "remaining": 6.0, "paid": 0.0,
            "next_payment_due": _iso(datetime.now(timezone.utc) - timedelta(days=9)),
            "created_at": _iso(datetime.now(timezone.utc) - timedelta(days=40)),
        })

        res = run_seizures()
        print("credit-default sweep:", res)

        biz = db.businesses.find_one({"id": bid}, {"_id": 0})
        assert biz.get("is_seized") is True, biz
        assert biz["seizure_reason"] == "credit_default"

        lst = db.land_listings.find_one({"business_id": bid}, {"_id": 0})
        assert lst and lst["is_seized"] is True
        assert lst.get("credit_id") == credit_id, lst
        assert lst["seller_username"] == "GRAM CITY"
        assert lst["price"] > 0

        cr = db.credits.find_one({"id": credit_id}, {"_id": 0})
        assert cr["status"] == "defaulted", cr["status"]
        assert cr.get("collateral_seized") is True
        assert cr.get("seized_listing_id") == lst["id"]

        # admin row exposes credit_id
        r = requests.get(f"{BASE_URL}/api/admin/credits/seized", headers=H(admin_token), timeout=30)
        row = next(x for x in r.json()["seized"] if x["listing_id"] == lst["id"])
        assert row["credit_id"] == credit_id
        assert row["seizure_reason"] == "credit_default"

        # buy → debt repaid first, remainder to former owner
        db.users.update_one({"id": users["admin"]["id"]}, {"$set": {"balance_ton": 500.0}})
        before = db.users.find_one({"id": u["id"]}, {"_id": 0}).get("balance_ton", 0)
        price = lst["price"]
        r = requests.post(f"{BASE_URL}/api/market/land/buy", json={"listing_id": lst["id"]},
                          headers=H(admin_token), timeout=60)
        assert r.status_code == 200, f"buy failed {r.status_code}: {r.text[:400]}"
        cr2 = db.credits.find_one({"id": credit_id}, {"_id": 0})
        print(f"credit remaining {cr['remaining']} -> {cr2['remaining']} (price {price})")
        assert cr2["remaining"] < cr["remaining"], "credit remaining not reduced on sale"
        after = db.users.find_one({"id": u["id"]}, {"_id": 0}).get("balance_ton", 0)
        gain = round(after - before, 6)
        print("former owner remainder:", gain)
        repaid = round(cr["remaining"] - cr2["remaining"], 6)
        assert repaid > 0
        assert gain >= 0
        assert round(gain + repaid, 4) <= round(price, 4) + 0.0001, \
            f"payout({gain}) + repaid({repaid}) exceeds price {price}"
        biz = db.businesses.find_one({"id": bid}, {"_id": 0})
        assert biz["durability"] == 100
        assert biz.get("is_seized") in (False, None)
        assert biz["owner"] == users["admin"]["id"]


# ─────────────────────────────── Stats bonus ────────────────────────────────
class TestStatsBonusTon:
    def test_stats_includes_bonus_balance(self, db, users):
        u = users["user"]
        before = requests.get(f"{BASE_URL}/api/stats", timeout=30)
        assert before.status_code == 200, before.text[:200]
        v0 = before.json()["total_volume_ton"]
        prev_bonus = float(db.users.find_one({"id": u["id"]}).get("bonus_balance", 0) or 0)
        db.users.update_one({"id": u["id"]}, {"$set": {"bonus_balance": prev_bonus + 250.0}})
        try:
            after = requests.get(f"{BASE_URL}/api/stats", timeout=30)
            v1 = after.json()["total_volume_ton"]
            print(f"total_volume_ton {v0} -> {v1}")
            assert v1 - v0 >= 249.0, f"bonus TON not reflected in stats: {v0} -> {v1}"
        finally:
            db.users.update_one({"id": u["id"]}, {"$set": {"bonus_balance": prev_bonus}})


# ────────────────────────── Admin secret leak audit ─────────────────────────
class TestAdminSecretAudit:
    def _assert_clean(self, obj, label):
        blob = obj if isinstance(obj, str) else str(obj)
        for k in SECRET_KEYS:
            assert f"'{k}'" not in blob and f'"{k}"' not in blob, f"{label} leaks {k}"

    def test_admin_users_no_secrets(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/admin/users?limit=20", headers=H(admin_token), timeout=30)
        assert r.status_code == 200, r.text[:300]
        self._assert_clean(r.text, "/api/admin/users")

    def test_admin_user_detail_no_secrets(self, admin_token, users):
        uid = users["user"]["id"]
        r = requests.get(f"{BASE_URL}/api/admin/user/{uid}", headers=H(admin_token), timeout=30)
        assert r.status_code == 200, r.text[:300]
        self._assert_clean(r.text, "/api/admin/user/{id}")

    def test_admin_players_search_no_secrets(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/admin/players/search?q=test",
                         headers=H(admin_token), timeout=30)
        assert r.status_code == 200, r.text[:300]
        self._assert_clean(r.text, "/api/admin/players/search")

    def test_admin_player_detail_no_secrets(self, admin_token, users):
        uid = users["user"]["id"]
        r = requests.get(f"{BASE_URL}/api/admin/players/{uid}", headers=H(admin_token), timeout=30)
        assert r.status_code == 200, r.text[:300]
        self._assert_clean(r.text, "/api/admin/players/{id}")
