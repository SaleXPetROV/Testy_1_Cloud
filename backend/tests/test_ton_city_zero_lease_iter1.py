"""
Iteration test: TON_CITY zero-lease / admin buyout / level0-price changes.
Covers:
  - Admin login
  - GET /api/admin/load-stats has bought_today per resource
  - GET /api/admin/market/all-listings shape
  - DELETE /api/admin/market/listing/{id} returns resources and cancels listing
  - GET /api/market/level0-price/{resource_type} for a normal user
"""
import os
import uuid
import pytest
import requests
from pymongo import MongoClient

def _load_frontend_env():
    p = "/app/frontend/.env"
    try:
        with open(p) as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    return line.split("=", 1)[1].strip()
    except FileNotFoundError:
        pass
    return os.environ.get("REACT_APP_BACKEND_URL", "")

BASE_URL = _load_frontend_env().rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL not found"
API = f"{BASE_URL}/api"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

_client = MongoClient(MONGO_URL)
db = _client[DB_NAME]


# ---------- fixtures ----------
@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{API}/auth/login", json={
        "email": "admin@gramcity.dev",
        "password": "GramCity!2025",
    }, timeout=30)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    data = r.json()
    tok = data.get("token") or data.get("access_token")
    assert tok, f"no token in login resp: {data}"
    return tok


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="module")
def player():
    """Register a fresh player and return (token, user_doc_id, email)."""
    tag = uuid.uuid4().hex[:8]
    email = f"TEST_player_{tag}@example.com"
    username = f"TESTp{tag}"
    password = "TestPass!2025"
    r = requests.post(f"{API}/auth/register", json={
        "email": email,
        "username": username,
        "password": password,
        "agreement_accepted": True,
    }, timeout=30)
    assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"
    body = r.json()
    tok = body.get("token") or body.get("access_token")
    assert tok
    user = db.users.find_one({"email": email})
    assert user is not None
    return {"token": tok, "user_id": user["id"], "email": email, "username": username}


@pytest.fixture(scope="module")
def player_headers(player):
    return {"Authorization": f"Bearer {player['token']}"}


# ---------- admin load-stats ----------
def test_admin_load_stats_has_bought_today(admin_headers):
    r = requests.get(f"{API}/admin/load-stats", headers=admin_headers, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "resources" in data and isinstance(data["resources"], list)
    assert len(data["resources"]) > 0
    for item in data["resources"]:
        assert "bought_today" in item, f"missing bought_today in {item}"
        assert isinstance(item["bought_today"], (int, float))


# ---------- level0-price for normal (non-zero) user ----------
def test_level0_price_for_normal_user(player_headers):
    r = requests.get(f"{API}/market/level0-price/energy", headers=player_headers, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("is_level0_seller") is False
    assert "price_ton" in data and "price_city" in data
    # price_city should be a reasonable positive number (admin market price)
    assert float(data["price_city"]) > 0


# ---------- admin all-listings + delete flow ----------
def _seed_business_and_resources(user_id, resource="energy", amount=100):
    """Give the player a real (non-tutorial) business producing `resource`
    and set their resources so they can list."""
    biz_id = str(uuid.uuid4())
    db.businesses.insert_one({
        "id": biz_id,
        "owner_id": user_id,
        "owner_email": None,
        "business_type": "energy_station",
        "produces": resource,
        "level": 1,
        "status": "active",
        "tutorial": False,
    })
    db.users.update_one({"id": user_id},
                        {"$set": {f"resources.{resource}": amount,
                                  "businesses_owned": [biz_id]}})
    return biz_id


def test_admin_all_listings_and_delete_returns_resources(admin_headers, player, player_headers):
    resource = "energy"
    initial_amount = 100
    list_amount = 30
    price = 0.005  # TON/unit

    biz_id = _seed_business_and_resources(player["user_id"], resource, initial_amount)

    # Player creates a listing
    r = requests.post(f"{API}/market/list-resource", headers=player_headers, json={
        "resource_type": resource,
        "amount": list_amount,
        "price_per_unit": price,
        "business_id": biz_id,
    }, timeout=30)
    assert r.status_code == 200, f"list-resource failed: {r.status_code} {r.text}"
    lst = r.json()
    listing_id = lst.get("id") or lst.get("listing_id") or (lst.get("listing") or {}).get("id")
    if not listing_id:
        # find via DB fallback
        doc = db.market_listings.find_one({"seller_id": player["user_id"], "status": "active"})
        assert doc, "no listing created in DB"
        listing_id = doc["id"]

    # Verify seller resources decreased
    u = db.users.find_one({"id": player["user_id"]})
    assert int(u["resources"].get(resource, 0)) == initial_amount - list_amount

    # Admin all-listings should include this listing
    r = requests.get(f"{API}/admin/market/all-listings", headers=admin_headers, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "listings" in data and "total" in data
    ids = [row["listing_id"] for row in data["listings"]]
    assert listing_id in ids, f"created listing {listing_id} not in admin all-listings"
    row = next(row for row in data["listings"] if row["listing_id"] == listing_id)
    for k in ("seller_username", "resource_name", "amount",
              "price_per_unit_city", "total_city"):
        assert k in row, f"missing key {k} in admin listing row: {row}"
    assert row["amount"] == list_amount

    # Admin deletes the listing
    r = requests.delete(f"{API}/admin/market/listing/{listing_id}",
                        headers=admin_headers, timeout=30)
    assert r.status_code == 200, f"admin delete failed: {r.status_code} {r.text}"
    body = r.json()
    assert body.get("status") == "removed"

    # Listing is now cancelled in DB
    doc = db.market_listings.find_one({"id": listing_id})
    assert doc is not None
    assert doc.get("status") == "cancelled"

    # Seller resources restored back
    u = db.users.find_one({"id": player["user_id"]})
    assert int(u["resources"].get(resource, 0)) == initial_amount, (
        f"resources not restored: have {u['resources'].get(resource)}, expected {initial_amount}"
    )

    # Deleting again returns 404
    r = requests.delete(f"{API}/admin/market/listing/{listing_id}",
                        headers=admin_headers, timeout=30)
    assert r.status_code == 404


# ---------- Cleanup ----------
@pytest.fixture(scope="module", autouse=True)
def _cleanup(player):
    yield
    try:
        db.users.delete_many({"email": {"$regex": "^TEST_player_"}})
        db.businesses.delete_many({"owner_id": player["user_id"]})
        db.market_listings.delete_many({"seller_id": player["user_id"]})
    except Exception:
        pass
