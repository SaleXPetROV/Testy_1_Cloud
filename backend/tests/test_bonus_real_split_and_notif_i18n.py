"""
NOTE: Run with `-n 0` (serial). Tests mutate the shared player user's
`bonus_balance` and `balance_ton`, so xdist parallelism (the repo's default
addopts `-n 2 --dist loadscope`) will produce false failures.

Verification tests for TON_CITY_v2.3 features:

1) Purchase payment logic must debit BONUS balance first, then REAL balance.
   'Insufficient funds' only when (bonus + real) < price.
   Applies to /api/market/buy (and general purchases).
2) Exception A: Level-0 -> Level-1 business upgrade REQUIRES real balance only.
3) Exception B: Marketplace buyout of a zero-business REQUIRES real balance only.
4) Notifications: core.notif_i18n.render() localizes across 9 languages.
5) translation_service.translation_configured() must be True (EMERGENT_LLM_KEY).
"""
import os
import sys
import uuid
import time
import pytest
import requests
from pymongo import MongoClient

# Ensure backend package importable for core.notif_i18n / translation_service
sys.path.insert(0, "/app/backend")

# ---------- env ----------
def _load_backend_url():
    v = os.environ.get("REACT_APP_BACKEND_URL")
    if not v:
        try:
            with open("/app/frontend/.env") as f:
                for line in f:
                    if line.startswith("REACT_APP_BACKEND_URL="):
                        v = line.split("=", 1)[1].strip().strip('"')
                        break
        except Exception:
            pass
    assert v, "REACT_APP_BACKEND_URL not set"
    return v.rstrip("/")


BASE_URL = _load_backend_url()

# Load MONGO_URL/DB_NAME from backend/.env
def _load_env(path="/app/backend/.env"):
    env = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


ENV = _load_env()
MONGO_URL = ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = ENV.get("DB_NAME") or os.environ.get("DB_NAME")
assert MONGO_URL and DB_NAME

PLAYER_EMAIL = "player@gramcity.app"
PLAYER_PASSWORD = "GramPlayer!2026"
PLAYER_ID = "35e52b7d-b2fc-4253-b9dc-57e9dc95006e"

ADMIN_EMAIL = "admin@gramcity.app"
ADMIN_PASSWORD = "GramAdmin!2026"
ADMIN_ID = "58a39888-593f-41a8-bdf5-a9cfe655c401"


# ---------- fixtures ----------
@pytest.fixture(scope="session")
def db():
    client = MongoClient(MONGO_URL)
    return client[DB_NAME]


@pytest.fixture(scope="session")
def player_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": PLAYER_EMAIL, "password": PLAYER_PASSWORD},
                      timeout=20)
    assert r.status_code == 200, r.text
    return r.json().get("access_token") or r.json().get("token")


@pytest.fixture(scope="session")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                      timeout=20)
    assert r.status_code == 200, r.text
    return r.json().get("access_token") or r.json().get("token")


def _set_balances(db, user_id, bonus_ton, real_ton):
    db.users.update_one({"id": user_id},
                        {"$set": {"bonus_balance": float(bonus_ton),
                                  "balance_ton": float(real_ton),
                                  "frozen_city_for_tenders": 0}})


def _ensure_buyer_real_business(db, user_id):
    """Ensure the player owns at least one non-trial business with warehouse capacity."""
    biz = db.businesses.find_one(
        {"owner": user_id, "is_trial": {"$ne": True}, "is_zero_business": {"$ne": True}},
        {"_id": 0},
    )
    if biz:
        db.businesses.update_one({"id": biz["id"]},
                                 {"$set": {"storage.capacity": 1000},
                                  "$unset": {"is_trial": ""}})
        return biz["id"]
    biz_id = f"testbiz_{uuid.uuid4().hex[:8]}"
    db.businesses.insert_one({
        "id": biz_id, "owner": user_id, "owner_username": "player",
        "business_type": "farm", "level": 3, "is_trial": False,
        "storage": {"capacity": 1000, "items": {}},
        "durability": 100, "on_sale": False,
    })
    db.users.update_one({"id": user_id}, {"$addToSet": {"businesses_owned": biz_id}})
    return biz_id


def _make_seller(db):
    """Create a seller user if not already present."""
    sid = "testseller_" + uuid.uuid4().hex[:8]
    db.users.insert_one({
        "id": sid, "email": f"{sid}@x.test", "username": sid,
        "balance_ton": 0.0, "bonus_balance": 0.0, "language": "en",
        "resources": {}, "businesses_owned": [], "plots_owned": [],
    })
    return sid


def _seed_market_listing(db, seller_id, resource_type="chips", amount=1,
                         price_per_unit=0.030):
    """Directly seed a market_listing so /api/market/buy has a target."""
    lid = "testlist_" + uuid.uuid4().hex[:8]
    # Seller needs a business that produces this resource for listing creation via API,
    # but seeding directly bypasses that.
    biz_id = "sellerbiz_" + uuid.uuid4().hex[:8]
    db.businesses.insert_one({
        "id": biz_id, "owner": seller_id, "business_type": "chip_factory",
        "level": 3, "is_trial": False, "storage": {"capacity": 1000, "items": {}},
    })
    db.market_listings.insert_one({
        "id": lid, "seller_id": seller_id, "seller_user_id": seller_id,
        "seller_email": None, "seller_wallet": None,
        "business_id": biz_id,
        "resource_type": resource_type,
        "amount": amount,
        "price_per_unit": price_per_unit,
        "status": "active",
        "created_at": time.time(),
    })
    return lid


def _cleanup(db, seller_id, listing_id=None):
    db.users.delete_one({"id": seller_id})
    db.businesses.delete_many({"owner": seller_id})
    if listing_id:
        db.market_listings.delete_many({"id": listing_id})


# =============== /api/market/buy split payment ===============
class TestMarketBuySplit:

    def test_bonus_plus_real_split(self, db, player_token):
        _ensure_buyer_real_business(db, PLAYER_ID)
        _set_balances(db, PLAYER_ID, bonus_ton=0.008, real_ton=3.400)
        seller = _make_seller(db)
        lid = _seed_market_listing(db, seller, "chips", 1, 0.030)
        try:
            r = requests.post(
                f"{BASE_URL}/api/market/buy",
                headers={"Authorization": f"Bearer {player_token}"},
                json={"listing_id": lid, "amount": 1},
                timeout=20,
            )
            assert r.status_code == 200, f"{r.status_code} {r.text}"
            data = r.json()
            print("split-response:", data)
            assert abs(float(data["paid_from_bonus"]) - 0.008) < 1e-6, data
            assert abs(float(data["paid_from_real"]) - 0.022) < 1e-6, data
            u = db.users.find_one({"id": PLAYER_ID}, {"_id": 0, "bonus_balance": 1, "balance_ton": 1})
            assert abs(float(u["bonus_balance"])) < 1e-9, u
            assert abs(float(u["balance_ton"]) - 3.378) < 1e-6, u
        finally:
            _cleanup(db, seller, lid)

    def test_insufficient_when_sum_too_low(self, db, player_token):
        _ensure_buyer_real_business(db, PLAYER_ID)
        _set_balances(db, PLAYER_ID, bonus_ton=0.008, real_ton=0.010)
        seller = _make_seller(db)
        lid = _seed_market_listing(db, seller, "chips", 1, 0.030)
        try:
            r = requests.post(
                f"{BASE_URL}/api/market/buy",
                headers={"Authorization": f"Bearer {player_token}"},
                json={"listing_id": lid, "amount": 1},
                timeout=20,
            )
            assert r.status_code in (400, 402, 409), f"{r.status_code} {r.text}"
            body = r.json()
            print("insufficient response:", body)
            detail = body.get("detail")
            # detail may be a dict with code or a localized string
            if isinstance(detail, dict):
                assert detail.get("code") == "insufficient_funds", detail
            else:
                assert "недостат" in str(detail).lower() or "insufficient" in str(detail).lower()
            # Balances unchanged (no partial debit)
            u = db.users.find_one({"id": PLAYER_ID}, {"_id": 0, "bonus_balance": 1, "balance_ton": 1})
            assert abs(float(u["bonus_balance"]) - 0.008) < 1e-9, u
            assert abs(float(u["balance_ton"]) - 0.010) < 1e-9, u
        finally:
            _cleanup(db, seller, lid)

    def test_bonus_only_sufficient(self, db, player_token):
        _ensure_buyer_real_business(db, PLAYER_ID)
        _set_balances(db, PLAYER_ID, bonus_ton=0.050, real_ton=0.500)
        seller = _make_seller(db)
        lid = _seed_market_listing(db, seller, "chips", 1, 0.030)
        try:
            r = requests.post(
                f"{BASE_URL}/api/market/buy",
                headers={"Authorization": f"Bearer {player_token}"},
                json={"listing_id": lid, "amount": 1},
                timeout=20,
            )
            assert r.status_code == 200, f"{r.status_code} {r.text}"
            data = r.json()
            print("bonus-only response:", data)
            assert abs(float(data["paid_from_bonus"]) - 0.030) < 1e-6, data
            assert abs(float(data["paid_from_real"])) < 1e-9, data
            u = db.users.find_one({"id": PLAYER_ID}, {"_id": 0, "bonus_balance": 1, "balance_ton": 1})
            assert abs(float(u["bonus_balance"]) - 0.020) < 1e-9, u
            assert abs(float(u["balance_ton"]) - 0.500) < 1e-9, u
        finally:
            _cleanup(db, seller, lid)


# =============== Exception A: zero-business 0->1 upgrade ===============
class TestZeroBusinessUpgradeRealOnly:

    def _seed_zero_biz(self, db, user_id, map_price_ton=0.5):
        biz_id = "zerobiz_" + uuid.uuid4().hex[:8]
        db.businesses.insert_one({
            "id": biz_id,
            "owner": user_id,
            "owner_username": "player",
            "business_type": "farm",
            "level": 0,
            "is_zero_business": True,
            "zero_map_price": map_price_ton,
            "storage": {"capacity": 100, "items": {}},
            "durability": 100,
            "on_sale": True,
        })
        return biz_id

    def test_zero_upgrade_rejects_when_only_bonus(self, db, player_token):
        _set_balances(db, PLAYER_ID, bonus_ton=100.0, real_ton=0.0)
        biz_id = self._seed_zero_biz(db, PLAYER_ID, map_price_ton=0.5)
        try:
            r = requests.post(
                f"{BASE_URL}/api/business/{biz_id}/upgrade",
                headers={"Authorization": f"Bearer {player_token}"},
                timeout=20,
            )
            assert r.status_code == 400, f"{r.status_code} {r.text}"
            detail = r.json().get("detail")
            print("zero_upgrade insufficient detail:", detail)
            assert isinstance(detail, dict), detail
            assert detail.get("code") == "zero_upgrade_need_real", detail
            # Bonus NOT consumed
            u = db.users.find_one({"id": PLAYER_ID}, {"_id": 0, "bonus_balance": 1, "balance_ton": 1})
            assert abs(float(u["bonus_balance"]) - 100.0) < 1e-9, u
            assert abs(float(u["balance_ton"])) < 1e-9, u
            # Still level 0
            b = db.businesses.find_one({"id": biz_id}, {"_id": 0, "level": 1})
            assert int(b["level"]) == 0
        finally:
            db.businesses.delete_one({"id": biz_id})

    def test_zero_upgrade_succeeds_with_real(self, db, player_token):
        _set_balances(db, PLAYER_ID, bonus_ton=100.0, real_ton=1.0)
        biz_id = self._seed_zero_biz(db, PLAYER_ID, map_price_ton=0.5)
        try:
            r = requests.post(
                f"{BASE_URL}/api/business/{biz_id}/upgrade",
                headers={"Authorization": f"Bearer {player_token}"},
                timeout=20,
            )
            assert r.status_code == 200, f"{r.status_code} {r.text}"
            data = r.json()
            print("zero_upgrade success:", data)
            u = db.users.find_one({"id": PLAYER_ID}, {"_id": 0, "bonus_balance": 1, "balance_ton": 1})
            # Bonus untouched
            assert abs(float(u["bonus_balance"]) - 100.0) < 1e-9, u
            # Real reduced by 0.5
            assert abs(float(u["balance_ton"]) - 0.5) < 1e-6, u
            b = db.businesses.find_one({"id": biz_id}, {"_id": 0, "level": 1})
            assert int(b["level"]) == 1
        finally:
            db.businesses.delete_one({"id": biz_id})
            db.users.update_one({"id": PLAYER_ID}, {"$unset": {"has_graduated_zero": ""}})


# =============== Exception B: marketplace buyout of zero-business ===============
class TestMarketplaceZeroBuyoutRealOnly:

    def _seed_zero_land_listing(self, db, seller_id, biz_id, plot_id, price_ton=0.030):
        lid = "zeroland_" + uuid.uuid4().hex[:8]
        db.land_listings.insert_one({
            "id": lid,
            "seller_id": seller_id,
            "seller_user_id": seller_id,
            "business_id": biz_id,
            "plot_id": plot_id,
            "price": float(price_ton),
            "status": "active",
            "is_zero_business": True,
            "created_at": time.time(),
        })
        return lid

    def test_buyout_rejects_bonus_only(self, db, player_token):
        # Buyer has zero-business? Must NOT — this endpoint rejects buyers with a zero biz.
        # Ensure player has no zero_business record
        db.businesses.delete_many({"owner": PLAYER_ID, "is_zero_business": True})
        _set_balances(db, PLAYER_ID, bonus_ton=100.0, real_ton=0.010)
        seller = _make_seller(db)
        # Seed seller's zero business + plot
        biz_id = "zerobizmp_" + uuid.uuid4().hex[:8]
        plot_id = "zeroplot_" + uuid.uuid4().hex[:8]
        db.businesses.insert_one({
            "id": biz_id, "owner": seller, "owner_username": "sel",
            "business_type": "farm", "level": 0, "is_zero_business": True,
            "storage": {"capacity": 100, "items": {}}, "durability": 100,
            "on_sale": True, "plot_id": plot_id,
        })
        db.plots.insert_one({"id": plot_id, "owner": seller, "on_sale": True,
                              "business": {"type": "farm", "level": 0, "owner": seller,
                                           "is_zero_business": True}})
        lid = self._seed_zero_land_listing(db, seller, biz_id, plot_id, 0.030)
        try:
            r = requests.post(
                f"{BASE_URL}/api/market/land/buy",
                headers={"Authorization": f"Bearer {player_token}"},
                json={"listing_id": lid},
                timeout=20,
            )
            assert r.status_code == 400, f"{r.status_code} {r.text}"
            assert "недостат" in r.text.lower() or "insufficient" in r.text.lower()
            # Balances unchanged
            u = db.users.find_one({"id": PLAYER_ID}, {"_id": 0, "bonus_balance": 1, "balance_ton": 1})
            assert abs(float(u["bonus_balance"]) - 100.0) < 1e-9, u
            assert abs(float(u["balance_ton"]) - 0.010) < 1e-9, u
            # Listing back to active
            after = db.land_listings.find_one({"id": lid}, {"_id": 0, "status": 1})
            assert after["status"] == "active"
        finally:
            db.land_listings.delete_many({"id": lid})
            db.businesses.delete_many({"id": biz_id})
            db.plots.delete_many({"id": plot_id})
            _cleanup(db, seller)

    def test_buyout_succeeds_with_real_only(self, db, player_token):
        db.businesses.delete_many({"owner": PLAYER_ID, "is_zero_business": True})
        _set_balances(db, PLAYER_ID, bonus_ton=100.0, real_ton=0.100)
        seller = _make_seller(db)
        biz_id = "zerobizmp2_" + uuid.uuid4().hex[:8]
        plot_id = "zeroplot2_" + uuid.uuid4().hex[:8]
        db.businesses.insert_one({
            "id": biz_id, "owner": seller, "owner_username": "sel",
            "business_type": "farm", "level": 0, "is_zero_business": True,
            "storage": {"capacity": 100, "items": {}}, "durability": 100,
            "on_sale": True, "plot_id": plot_id,
        })
        db.plots.insert_one({"id": plot_id, "owner": seller, "on_sale": True,
                              "business": {"type": "farm", "level": 0, "owner": seller,
                                           "is_zero_business": True}})
        lid = self._seed_zero_land_listing(db, seller, biz_id, plot_id, 0.030)
        try:
            r = requests.post(
                f"{BASE_URL}/api/market/land/buy",
                headers={"Authorization": f"Bearer {player_token}"},
                json={"listing_id": lid},
                timeout=20,
            )
            assert r.status_code == 200, f"{r.status_code} {r.text}"
            data = r.json()
            print("zero-buyout success:", data)
            u = db.users.find_one({"id": PLAYER_ID}, {"_id": 0, "bonus_balance": 1, "balance_ton": 1})
            # Bonus untouched
            assert abs(float(u["bonus_balance"]) - 100.0) < 1e-9, u
            # Real reduced by 0.030
            assert abs(float(u["balance_ton"]) - 0.070) < 1e-6, u
        finally:
            # Cleanup transferred artifacts
            db.land_listings.delete_many({"id": lid})
            db.businesses.delete_many({"id": biz_id})
            db.plots.delete_many({"id": plot_id})
            db.users.update_one({"id": PLAYER_ID},
                                {"$pull": {"businesses_owned": biz_id, "plots_owned": plot_id}})
            _cleanup(db, seller)


# =============== Notification i18n (9 languages) ===============
class TestNotifI18N:

    def test_render_all_languages(self):
        from core.notif_i18n import render, LANGS, NOTIF
        for key in ("business_sold", "withdrawal_pending", "zero_business_lost"):
            assert key in NOTIF, f"missing i18n key: {key}"
            for lang in LANGS:
                title, msg = render(key, lang, biz="TestBiz", amount="1.0",
                                    tax="0.1", tx_line="")
                assert title and msg, f"{key}/{lang} empty"
                # Ensure it isn't returning the fallback (key) string
                assert title != key

    def test_translation_configured(self):
        from translation_service import translation_configured
        assert translation_configured() is True, \
            "EMERGENT_LLM_KEY (or LIBRETRANSLATE_URL) must be set for auto-translate"
