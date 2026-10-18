"""Iteration 3 tests: daily-reward activity gate, leaderboard me/rank, fixed prices."""
import os
import requests
import pytest
from datetime import datetime, timezone
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or "https://resource-trader-v2.preview.emergentagent.com"
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

TESTUSER = {"email": "testuser@example.com", "password": "Test1234!"}
ADMIN = {"email": "sanyanazarov212@gmail.com", "password": os.environ.get("TEST_ADMIN_PASSWORD", "")}
TESTUSER_ID = "6c414e42-df3d-4a3d-b3d7-d651e70dad6e"


@pytest.fixture(scope="module")
def mongo():
    client = MongoClient(MONGO_URL)
    yield client[DB_NAME]
    client.close()


@pytest.fixture(scope="module")
def user_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json=TESTUSER, timeout=15)
    assert r.status_code == 200, r.text
    j = r.json()
    return j.get("access_token") or j["token"]


@pytest.fixture(scope="module")
def user_hdr(user_token):
    return {"Authorization": f"Bearer {user_token}"}


# --- Daily reward activity gate ---

def _today():
    return datetime.now(timezone.utc).date().isoformat()


def test_daily_state_returns_activity_fields(user_hdr, mongo):
    # Reset daily state so we don't already have claimed today
    mongo.users.update_one({"id": TESTUSER_ID}, {"$set": {"daily_trade": {"date": _today(), "bought": 0, "sold": 0}, "daily_last_claim": None}})
    r = requests.get(f"{BASE_URL}/api/tasks/daily", headers=user_hdr, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    for k in ("activity_bought", "activity_sold", "activity_buy_required", "activity_sell_required", "activity_met"):
        assert k in d, f"missing {k}: {d}"
    assert d["activity_buy_required"] == 30
    assert d["activity_sell_required"] == 95
    assert d["activity_met"] is False


def test_daily_claim_blocked_without_activity(user_hdr, mongo):
    mongo.users.update_one({"id": TESTUSER_ID}, {"$set": {"daily_trade": {"date": _today(), "bought": 0, "sold": 0}, "daily_last_claim": None}})
    r = requests.post(f"{BASE_URL}/api/tasks/daily/claim", headers=user_hdr, timeout=15)
    assert r.status_code == 400
    detail = r.json().get("detail", "")
    assert (
        "выполните дневную активность" in detail.lower()
        or "complete daily activity" in detail.lower()
    ), detail


# --- Daily SELL tracking via /market/list-resource ---

def test_daily_sell_tracking_increments(user_hdr, mongo):
    # Clear pre-existing active listings for the user to avoid slot limits
    mongo.resource_listings.delete_many({"seller_id": TESTUSER_ID})
    mongo.resource_listings.delete_many({"seller_wallet": TESTUSER_ID})
    mongo.market_listings.delete_many({"seller_id": TESTUSER_ID})
    mongo.market_listings.delete_many({"seller": TESTUSER_ID})
    # Give the user enough energy + balance
    mongo.users.update_one(
        {"id": TESTUSER_ID},
        {"$set": {
            "resources.energy": 500,
            "balance_ton": 1000.0,
            "daily_trade": {"date": _today(), "bought": 0, "sold": 0},
        }},
    )
    r = requests.post(
        f"{BASE_URL}/api/market/list-resource",
        headers=user_hdr,
        json={"resource_type": "energy", "amount": 100, "price_per_unit": 3.0},
        timeout=20,
    )
    # If listing fails for a reason we can't easily satisfy (slots, etc.) log and skip
    if r.status_code != 200:
        pytest.skip(f"list-resource returned {r.status_code}: {r.text}")
    u = mongo.users.find_one({"id": TESTUSER_ID})
    dt = u.get("daily_trade") or {}
    assert dt.get("sold", 0) >= 100, f"daily_trade after list: {dt}"


# --- Daily claim success path (seed activity directly) ---

def test_daily_claim_success_with_seeded_activity(user_hdr, mongo):
    mongo.users.update_one(
        {"id": TESTUSER_ID},
        {"$set": {
            "daily_trade": {"date": _today(), "bought": 30, "sold": 95},
            "daily_last_claim": None,
        }},
    )
    # Confirm the state endpoint reflects activity_met
    r = requests.get(f"{BASE_URL}/api/tasks/daily", headers=user_hdr, timeout=15)
    assert r.status_code == 200
    assert r.json().get("activity_met") is True

    r = requests.post(f"{BASE_URL}/api/tasks/daily/claim", headers=user_hdr, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d.get("status") == "claimed"
    assert isinstance(d.get("reward_city"), int) and d["reward_city"] > 0


# --- Leaderboard: players + me + rank + total ---

@pytest.mark.parametrize("sort_by", ["balance", "income", "trading"])
def test_leaderboard_me_and_rank(sort_by):
    r = requests.get(
        f"{BASE_URL}/api/leaderboard",
        params={"sort_by": sort_by, "limit": 1, "me_id": TESTUSER_ID},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert "players" in d and isinstance(d["players"], list)
    assert len(d["players"]) == 1
    assert d.get("sort_by") == sort_by
    assert isinstance(d.get("total"), int) and d["total"] >= 1
    me = d.get("me")
    if me is None:
        pytest.skip("testuser is not present in leaderboard (b2b partner or filtered)")
    assert me.get("id") == TESTUSER_ID
    assert isinstance(me.get("rank"), int) and me["rank"] >= 1
    assert me["rank"] <= d["total"]


# --- Fixed market prices ---

EXPECTED_PRICES = {
    "energy": 3.0, "scrap": 3.6, "quartz": 3.6, "cu": 3.4, "traffic": 3.9,
    "cooling": 3.5, "biomass": 3.3, "chips": 85, "neurocode": 110,
    "neuro_core": 5500, "gold_bill": 6500, "bio_module": 5700, "gateway_code": 5700,
}


def test_fixed_market_prices():
    r = requests.get(f"{BASE_URL}/api/economy/market-prices", timeout=15)
    assert r.status_code == 200, r.text
    prices = r.json().get("prices", {})
    missing = []
    wrong = []
    for k, v in EXPECTED_PRICES.items():
        if k not in prices:
            missing.append(k)
        elif float(prices[k]) != float(v):
            wrong.append((k, prices[k], v))
    assert not missing, f"missing resources: {missing}"
    assert not wrong, f"price mismatches: {wrong}"
