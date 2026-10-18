"""
Iter17 — Follow-up race-safety fixes:
  1. HIGH: /api/market/land/buy on a legacy listing WITHOUT x/y fields must NOT
     500 and must NOT lose buyer's money (was: KeyError → 500 after debit).
  2. Normalization: /api/market/buy pre-check (amount > available) must now
     return 409 RESOURCE_UNAVAILABLE (was 400). 404 is also acceptable if the
     listing is already sold (frontend handles both).

Run serially: pytest -n 0 (mutates shared testuser accounts).
"""
import os
import uuid
import pytest
import requests
from pymongo import MongoClient


BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

BUYER_A = ("testuser@example.com", "Test1234!")
BUYER_B = ("testuser2@example.com", "Test1234!")


# ── shared fixtures ──────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def mongo():
    cli = MongoClient(MONGO_URL)
    yield cli[DB_NAME]
    cli.close()


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": password}, timeout=15)
    r.raise_for_status()
    j = r.json()
    return j["token"], j["user"]


@pytest.fixture(scope="module")
def users(mongo):
    tok_a, u_a = _login(*BUYER_A)
    tok_b, u_b = _login(*BUYER_B)
    orig_a = mongo.users.find_one({"id": u_a["id"]}, {"balance_ton": 1})
    orig_b = mongo.users.find_one({"id": u_b["id"]}, {"balance_ton": 1})
    yield {"a": {"token": tok_a, "user": u_a, "orig": orig_a},
           "b": {"token": tok_b, "user": u_b, "orig": orig_b}}
    mongo.users.update_one({"id": u_a["id"]}, {"$set": {
        "balance_ton": float(orig_a.get("balance_ton", 0) or 0)}})
    mongo.users.update_one({"id": u_b["id"]}, {"$set": {
        "balance_ton": float(orig_b.get("balance_ton", 0) or 0)}})


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ── TEST 1 ── Legacy land listing without x/y — no 500, no money loss ───────
class TestLegacyLandListingNoXY:
    """
    HIGH FIX regression: land_listing without x/y (and possibly without
    plot_id/city_id) must not cause a 500 after buyer debit. Buyer either
    succeeds (200) or gets a controlled error (4xx) with balance intact.
    """

    def test_legacy_listing_no_xy_purchase_succeeds_or_controlled(self, mongo, users):
        buyer = users["b"]
        buyer_id = buyer["user"]["id"]
        # synthetic seller (never logs in) to avoid own-listing guard
        seller_id = "TEST_LEGACY_SELLER_" + uuid.uuid4().hex[:6]
        seller_wallet = "TEST_LEGACY_WALLET_" + uuid.uuid4().hex[:6]
        seller_email = f"TEST_legacy_seller_{uuid.uuid4().hex[:6]}@ex.com"
        mongo.users.insert_one({
            "id": seller_id, "email": seller_email,
            "wallet_address": seller_wallet, "balance_ton": 0, "bonus_balance": 0,
            "username": "TEST_legacy_seller",
        })

        # park existing plots to prevent 3-plot cap issues
        park = f"TEST_PARK_LEGACY_{buyer_id[:8]}"
        mongo.plots.update_many({"owner": buyer_id}, {"$set": {"owner": park}})

        # A legacy plot: has id, owner=seller_id, on_sale, listing_id, city_id
        # but NO x/y fields on the plot doc itself.
        plot_id = f"TEST_legacy_plot_{uuid.uuid4().hex[:8]}"
        listing_id = f"TEST_legacy_list_{uuid.uuid4().hex[:8]}"
        price = 0.001

        mongo.plots.insert_one({
            "id": plot_id, "owner": seller_id, "owner_wallet": seller_wallet,
            "on_sale": True, "listing_id": listing_id,
            "city_id": "gram_city",
            "island_id": "gram_city",
            # NO x, NO y, NO coordinates — legacy shape
        })
        # legacy land_listing: has plot_id + city_id but NO x/y
        mongo.land_listings.insert_one({
            "id": listing_id, "status": "active", "plot_id": plot_id,
            "seller_id": seller_id, "seller_user_id": seller_id,
            "seller_email": seller_email, "seller_wallet": seller_wallet,
            "price": price, "city_id": "gram_city",
            "created_at": "2026-01-01T00:00:00Z",
            # NO x, NO y, NO business field
        })

        # Ensure buyer has funds
        mongo.users.update_one({"id": buyer_id},
                               {"$set": {"balance_ton": 5.0, "plots_owned": []}})
        bal_before = float(mongo.users.find_one({"id": buyer_id})["balance_ton"])

        try:
            r = requests.post(f"{BASE_URL}/api/market/land/buy",
                              json={"listing_id": listing_id},
                              headers=_hdr(buyer["token"]), timeout=20)
            print(f"legacy no-xy purchase: status={r.status_code} body={r.text[:300]}")

            # Must NOT be 500
            assert r.status_code != 500, f"REGRESSION: 500 returned: {r.text}"

            bal_after = float(mongo.users.find_one({"id": buyer_id})["balance_ton"])
            listing_after = mongo.land_listings.find_one({"id": listing_id})

            if r.status_code == 200:
                # Success path: balance should be debited by ~price and listing sold.
                assert abs((bal_before - bal_after) - price) < 0.001, \
                    f"balance debit wrong: before={bal_before} after={bal_after} price={price}"
                assert listing_after["status"] == "sold"
                # Plot should now belong to buyer
                plot_after = mongo.plots.find_one({"id": plot_id})
                assert plot_after["owner"] == buyer_id
            else:
                # Controlled error: balance MUST NOT be silently debited.
                assert abs(bal_after - bal_before) < 0.001, \
                    f"MONEY LOSS: buyer debited on {r.status_code} error: " \
                    f"before={bal_before} after={bal_after} body={r.text}"

        finally:
            mongo.plots.delete_one({"id": plot_id})
            mongo.land_listings.delete_one({"id": listing_id})
            mongo.users.delete_one({"id": seller_id})
            mongo.users.update_one({"id": buyer_id},
                                   {"$pull": {"plots_owned": {"$in": [plot_id]}}})
            # restore parked plots
            mongo.plots.update_many({"owner": park}, {"$set": {"owner": buyer_id}})

    def test_legacy_listing_no_xy_with_business(self, mongo, users):
        """Same as above but with a business field on the listing (still no x/y)."""
        buyer = users["a"]
        buyer_id = buyer["user"]["id"]
        seller_id = "TEST_LEGACY_SELLER2_" + uuid.uuid4().hex[:6]
        seller_wallet = "TEST_LEGACY_W2_" + uuid.uuid4().hex[:6]
        seller_email = f"TEST_legacy2_{uuid.uuid4().hex[:6]}@ex.com"
        mongo.users.insert_one({
            "id": seller_id, "email": seller_email,
            "wallet_address": seller_wallet, "balance_ton": 0,
            "username": "TEST_legacy2",
        })
        park = f"TEST_PARK_L2_{buyer_id[:8]}"
        mongo.plots.update_many({"owner": buyer_id}, {"$set": {"owner": park}})

        plot_id = f"TEST_legacy2_plot_{uuid.uuid4().hex[:8]}"
        listing_id = f"TEST_legacy2_list_{uuid.uuid4().hex[:8]}"
        biz_id = f"TEST_legacy2_biz_{uuid.uuid4().hex[:8]}"
        price = 0.002

        mongo.plots.insert_one({
            "id": plot_id, "owner": seller_id, "owner_wallet": seller_wallet,
            "on_sale": True, "listing_id": listing_id,
            "city_id": "gram_city",
        })
        mongo.businesses.insert_one({
            "id": biz_id, "plot_id": plot_id, "owner": seller_id,
            "owner_wallet": seller_wallet, "business_type": "cafe", "level": 1,
            "is_trial": False, "storage": {"capacity": 100, "items": {}},
        })
        mongo.land_listings.insert_one({
            "id": listing_id, "status": "active", "plot_id": plot_id,
            "seller_id": seller_id, "seller_user_id": seller_id,
            "seller_email": seller_email, "seller_wallet": seller_wallet,
            "price": price, "city_id": "gram_city",
            "business_id": biz_id,
            "business": {"id": biz_id, "type": "cafe", "level": 1, "tier": 1},
            "created_at": "2026-01-01T00:00:00Z",
            # NO x, NO y
        })

        mongo.users.update_one({"id": buyer_id},
                               {"$set": {"balance_ton": 5.0, "plots_owned": []}})
        bal_before = float(mongo.users.find_one({"id": buyer_id})["balance_ton"])
        try:
            r = requests.post(f"{BASE_URL}/api/market/land/buy",
                              json={"listing_id": listing_id},
                              headers=_hdr(buyer["token"]), timeout=20)
            print(f"legacy no-xy w/ biz: status={r.status_code} body={r.text[:300]}")
            assert r.status_code != 500, f"REGRESSION: 500 returned: {r.text}"
            bal_after = float(mongo.users.find_one({"id": buyer_id})["balance_ton"])
            if r.status_code == 200:
                assert abs((bal_before - bal_after) - price) < 0.001
                biz_after = mongo.businesses.find_one({"id": biz_id})
                # ownership transferred
                assert biz_after["owner"] == buyer_id
            else:
                assert abs(bal_after - bal_before) < 0.001, \
                    f"MONEY LOSS on {r.status_code}: before={bal_before} after={bal_after}"
        finally:
            mongo.plots.delete_one({"id": plot_id})
            mongo.businesses.delete_one({"id": biz_id})
            mongo.land_listings.delete_one({"id": listing_id})
            mongo.users.delete_one({"id": seller_id})
            mongo.users.update_one({"id": buyer_id},
                                   {"$pull": {"plots_owned": {"$in": [plot_id]}}})
            mongo.plots.update_many({"owner": park}, {"$set": {"owner": buyer_id}})


# ── TEST 2 ── /api/market/buy pre-check normalization to 409 ────────────────
class TestResourcePrecheck409:
    """
    /api/market/buy: requesting amount > listing.amount must return 409
    (RESOURCE_UNAVAILABLE), not 400. 404 also OK if listing is sold in between.
    """
    def test_precheck_amount_exceeds_available_returns_409(self, mongo, users):
        buyer = users["a"]
        buyer_id = buyer["user"]["id"]
        _wallet = buyer["user"].get("wallet_address")

        # Ensure buyer owns a real business (P2P gate)
        biz_ids_created = []
        _or = [{"owner": buyer_id}]
        if _wallet:
            _or.append({"owner_wallet": _wallet})
        existing = mongo.businesses.count_documents({"$or": _or, "is_trial": {"$ne": True}})
        if existing == 0:
            bid = f"TEST_pcbiz_{uuid.uuid4().hex[:8]}"
            _biz_doc = {
                "id": bid, "owner": buyer_id,
                "business_type": "factory", "level": 2, "is_trial": False,
                "storage": {"capacity": 5000, "items": {}},
            }
            if buyer["user"].get("wallet_address"):
                _biz_doc["owner_wallet"] = buyer["user"]["wallet_address"]
            mongo.businesses.insert_one(_biz_doc)
            biz_ids_created.append(bid)

        seller_id = "TEST_PC_SELLER_" + uuid.uuid4().hex[:6]
        listing_id = f"TEST_pc_list_{uuid.uuid4().hex[:10]}"
        mongo.market_listings.insert_one({
            "id": listing_id, "status": "active",
            "seller_id": seller_id, "seller_email": "TEST_pc@example.com",
            "resource_type": "scrap", "amount": 10,
            "price_per_unit": 0.0001,
            "created_at": "2026-01-01T00:00:00Z",
        })
        mongo.users.update_one({"id": buyer_id},
                               {"$set": {"balance_ton": 5.0}})

        try:
            # Request 20 units (>10 available) → must be 409
            r = requests.post(f"{BASE_URL}/api/market/buy",
                              json={"listing_id": listing_id, "amount": 20},
                              headers=_hdr(buyer["token"]), timeout=20)
            print(f"precheck excess: status={r.status_code} body={r.text[:200]}")
            assert r.status_code == 409, \
                f"NORMALIZATION FAIL: expected 409 for amount>available, got " \
                f"{r.status_code}/{r.text}"
            assert r.json().get("detail") == "RESOURCE_UNAVAILABLE", r.text
            # Listing must remain active (no accidental mutation)
            listing_after = mongo.market_listings.find_one({"id": listing_id})
            assert listing_after["status"] == "active"
            assert listing_after["amount"] == 10
        finally:
            mongo.market_listings.delete_one({"id": listing_id})
            if biz_ids_created:
                mongo.businesses.delete_many({"id": {"$in": biz_ids_created}})
