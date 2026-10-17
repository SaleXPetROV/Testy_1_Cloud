"""
Iter8 backend tests — demo repair now priced/charged in $CITY.

Covers:
 - GET /api/demo/business/repair-cost returns {status:'ok', cost_city, cost_per_pct,
   missing_pct, demo_balance_city} — priced in $CITY, no resource reference.
 - POST /api/demo/business/repair charges demo_balance_city, returns paid_city.
 - Insufficient balance path returns currency:'city' (NOT resource error).
 - already_full path when durability≈100.
 - Regression: seeded testuser login + /api/auth/me still 200.
"""
import os
import asyncio
import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

USER_EMAIL = "testuser@example.com"
USER_PASSWORD = "Test1234!"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": USER_EMAIL, "password": USER_PASSWORD}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def demo_headers(token):
    return {"Authorization": f"Bearer {token}", "X-Game-Mode": "demo"}


@pytest.fixture(scope="module")
def user_id(token):
    r = requests.get(f"{BASE_URL}/api/auth/me",
                     headers={"Authorization": f"Bearer {token}"}, timeout=15)
    assert r.status_code == 200
    return r.json()["id"]


def _set_demo(user_id, patch):
    async def _do():
        cli = AsyncIOMotorClient(MONGO_URL)
        db = cli[DB_NAME]
        await db.demo_profiles.update_one({"user_id": user_id}, {"$set": patch})
        cli.close()
    asyncio.get_event_loop().run_until_complete(_do())


def _get_demo(user_id):
    async def _do():
        cli = AsyncIOMotorClient(MONGO_URL)
        db = cli[DB_NAME]
        doc = await db.demo_profiles.find_one({"user_id": user_id}, {"_id": 0})
        cli.close()
        return doc
    return asyncio.get_event_loop().run_until_complete(_do())


def test_login_and_me(token):
    r = requests.get(f"{BASE_URL}/api/auth/me",
                     headers={"Authorization": f"Bearer {token}"}, timeout=15)
    assert r.status_code == 200
    assert r.json()["email"] == USER_EMAIL


def test_enter_demo(demo_headers):
    r = requests.post(f"{BASE_URL}/api/demo/enter", headers=demo_headers, timeout=15)
    assert r.status_code == 200
    j = r.json()
    assert j["is_demo"] is True
    assert j["profile"]["demo_business"] is not None


def test_repair_cost_quote_priced_in_city(demo_headers, user_id):
    # Force durability to 60 and balance to 5000 so quote is deterministic.
    prof = _get_demo(user_id)
    biz = dict(prof["demo_business"])
    biz["durability"] = 60.0
    _set_demo(user_id, {"demo_business": biz, "demo_balance_city": 5000})

    r = requests.get(f"{BASE_URL}/api/demo/business/repair-cost",
                     headers=demo_headers, timeout=15)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["status"] == "ok"
    # priced in $CITY
    assert isinstance(j["cost_city"], (int, float))
    assert j["cost_city"] > 0
    assert "cost_per_pct" in j and j["cost_per_pct"] >= 1
    assert "missing_pct" in j and 39.0 <= j["missing_pct"] <= 41.0
    assert "demo_balance_city" in j
    # NOT a resource-based response
    assert "resource" not in j
    assert "need_resource" not in j


def test_repair_charges_city_and_returns_paid_city(demo_headers, user_id):
    # Ensure durability<100 and sufficient balance.
    prof = _get_demo(user_id)
    biz = dict(prof["demo_business"])
    biz["durability"] = 70.0
    _set_demo(user_id, {"demo_business": biz, "demo_balance_city": 5000})

    quote = requests.get(f"{BASE_URL}/api/demo/business/repair-cost",
                         headers=demo_headers, timeout=15).json()
    expected_cost = quote["cost_city"]
    balance_before = quote["demo_balance_city"]

    r = requests.post(f"{BASE_URL}/api/demo/business/repair",
                      headers=demo_headers, timeout=15)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["status"] == "repaired"
    assert j["paid_city"] == expected_cost
    assert j["demo_balance_city"] == round(balance_before - expected_cost, 2)
    assert j["durability"] == 100.0


def test_repair_already_full(demo_headers, user_id):
    prof = _get_demo(user_id)
    biz = dict(prof["demo_business"])
    biz["durability"] = 100.0
    _set_demo(user_id, {"demo_business": biz})

    r = requests.post(f"{BASE_URL}/api/demo/business/repair",
                      headers=demo_headers, timeout=15)
    assert r.status_code == 200
    assert r.json()["status"] == "already_full"


def test_repair_insufficient_balance_returns_currency_city(demo_headers, user_id):
    prof = _get_demo(user_id)
    biz = dict(prof["demo_business"])
    biz["durability"] = 50.0  # missing 50%
    _set_demo(user_id, {"demo_business": biz, "demo_balance_city": 1})

    r = requests.post(f"{BASE_URL}/api/demo/business/repair",
                      headers=demo_headers, timeout=15)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["status"] == "insufficient"
    assert j.get("currency") == "city"
    assert "need" in j and "have" in j
    # NOT the old resource-based error shape
    assert "resource" not in j

    # Restore balance so subsequent user experience is clean.
    _set_demo(user_id, {"demo_balance_city": 5000})
