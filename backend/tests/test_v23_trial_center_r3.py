"""Iter 3 tests — Trial Center v2 (warehouse 300, seed 25, bonus_balance after tutorial)."""
import os
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")

TESTUSER = {"email": "testuser@example.com", "password": "Test1234!"}


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json=TESTUSER, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ---------- /auth/me exposes bonus_balance ----------
def test_auth_me_has_bonus_balance(headers):
    r = requests.get(f"{BASE_URL}/api/auth/me", headers=headers, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    assert "bonus_balance" in d, f"bonus_balance missing in /auth/me: keys={list(d.keys())}"
    assert isinstance(d["bonus_balance"], (int, float))


# ---------- Tutorial -> bonus_balance >= 1.0 ----------
def test_tutorial_finish_grants_bonus_balance(headers):
    # reset then start then finish
    r = requests.post(f"{BASE_URL}/api/tutorial/reset", headers=headers, timeout=30)
    assert r.status_code == 200, r.text
    r = requests.post(f"{BASE_URL}/api/tutorial/start", headers=headers, timeout=30)
    assert r.status_code == 200, r.text
    # finish (may require t3_choice on first-ever completion; user already claimed once so it should be idempotent)
    r = requests.post(
        f"{BASE_URL}/api/tutorial/finish",
        json={"t3_choice": "neuro_core"},
        headers=headers,
        timeout=30,
    )
    assert r.status_code == 200, r.text
    # verify bonus_balance >= 1
    me = requests.get(f"{BASE_URL}/api/auth/me", headers=headers, timeout=30).json()
    assert me.get("bonus_balance", 0) >= 1.0, f"bonus_balance not topped up: {me.get('bonus_balance')}"


# ---------- Trial Center: GET, BUY, warehouse=300, seed=25 ----------
def _reset_trial(db_uid_email):
    """Direct mongo cleanup — best effort via python driver."""
    from pymongo import MongoClient
    mongo = MongoClient(os.environ["MONGO_URL"])
    db = mongo[os.environ["DB_NAME"]]
    db.businesses.delete_many({"is_trial": True, "$or": [{"owner_email": db_uid_email}]})
    # actual owner field is 'owner' (uid). We'll delete via user lookup instead:
    u = db.users.find_one({"email": db_uid_email})
    if u:
        db.businesses.delete_many({"is_trial": True, "owner": u.get("id")})
        db.users.update_one({"email": db_uid_email},
                            {"$unset": {"trial_center_purchased": "", "trial_center_hidden": ""}})
    mongo.close()


def test_trial_center_buy_flow_warehouse_and_seed(headers):
    # clean state
    _reset_trial(TESTUSER["email"])
    # GET (not owned)
    r = requests.get(f"{BASE_URL}/api/trial-center", headers=headers, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d.get("owned") is False, d
    # BUY
    r = requests.post(f"{BASE_URL}/api/trial-center/buy", headers=headers, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d.get("status") == "purchased"
    biz = d["business"]
    assert biz["storage_info"]["capacity"] == 300
    assert biz["storage_info"]["used"] == 25, f"expected 25 seed units, got {biz['storage_info']}"
    # GET after buy
    r = requests.get(f"{BASE_URL}/api/trial-center", headers=headers, timeout=30)
    assert r.status_code == 200
    d = r.json()
    assert d["owned"] is True
    b = d["business"]
    assert b["storage_info"]["capacity"] == 300
    # seed still ~25 (accrual may have decremented a tiny amount within seconds)
    assert 24 <= b["storage_info"]["used"] <= 25
    assert b["is_active"] is True
    assert b["remaining_seconds"] > 0
    # Second buy must fail
    r2 = requests.post(f"{BASE_URL}/api/trial-center/buy", headers=headers, timeout=30)
    assert r2.status_code == 400
