"""
Regression tests for tutorial-finish resource leak fix.
"""
import os
import pytest
import requests
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://city-economy-preview.preview.emergentagent.com").rstrip("/")
# Load backend env
with open("/app/backend/.env") as f:
    for line in f:
        if "=" in line:
            k, v = line.strip().split("=", 1)
            os.environ[k] = v.strip('"')

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

TEST_EMAIL = "testuser@example.com"
TEST_PASSWORD = "Test1234!"


@pytest.fixture(scope="module")
def db():
    client = MongoClient(MONGO_URL)
    return client[DB_NAME]


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": TEST_EMAIL, "password": TEST_PASSWORD})
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    return r.json().get("access_token") or r.json().get("token")


@pytest.fixture(scope="module")
def user_id(token):
    r = requests.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    data = r.json()
    return data.get("id") or data.get("_id") or data.get("user_id")


def _seed_leaked_finish_state(db, uid):
    """Simulate a user at finish step with leaked resources."""
    db.users.update_one(
        {"id": uid} if db.users.find_one({"id": uid}) else {"_id": uid},
        {
            "$set": {
                "tutorial_active": True,
                "tutorial_completed": False,
                "tutorial_current_step": "finish",
                "tutorial_snapshot": {
                    "balance_ton": 5.0,
                    "resources": {},
                    "active_resource_buffs": [],
                    "level": 1,
                    "xp": 0,
                    "total_turnover": 0,
                    "total_income": 0,
                    "plots_owned": [],
                    "businesses_owned": [],
                },
                "resources": {"biomass": 50, "energy": 12, "neuro_core": 1},
                "balance_ton": 55.0,
            },
            "$unset": {
                "tutorial_t3_reward_granted": "",
                "tutorial_t3_reward_choice": "",
                "tutorial_t3_reward_granted_at": "",
                "tutorial_pending_t3_auto_activate": "",
            },
        },
    )


def test_primary_finish_cleans_leaked_resources(db, token, user_id):
    _seed_leaked_finish_state(db, user_id)

    r = requests.post(
        f"{BASE_URL}/api/tutorial/finish",
        json={"t3_choice": "neuro_core"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, f"finish failed: {r.status_code} {r.text}"

    # /api/auth/me doesn't expose `resources`; assert against DB directly.
    q = {"id": user_id} if db.users.find_one({"id": user_id}) else {"_id": user_id}
    after = db.users.find_one(q)
    resources = after.get("resources") or {}
    non_zero = {k: v for k, v in resources.items() if v}
    assert non_zero == {"neuro_core_tutorial": 1}, f"resources leaked: {resources}"
    assert after.get("balance_ton") == 5.0, f"balance not restored: {after.get('balance_ton')}"
    # Also confirm /me sees the restored balance
    me = requests.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me.get("balance_ton") == 5.0


def test_secondary_tutorial_reward_not_sellable(token):
    r = requests.post(
        f"{BASE_URL}/api/market/list-resource",
        json={"resource_type": "neuro_core_tutorial", "amount": 1, "price_per_unit": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"


def test_tertiary_market_blocked_during_tutorial(db, token, user_id):
    # Re-activate tutorial
    db.users.update_one(
        {"id": user_id} if db.users.find_one({"id": user_id}) else {"_id": user_id},
        {"$set": {"tutorial_active": True, "tutorial_completed": False}},
    )

    r1 = requests.post(
        f"{BASE_URL}/api/market/list-resource",
        json={"resource_type": "biomass", "amount": 1, "price_per_unit": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r1.status_code == 403, f"list-resource not blocked: {r1.status_code} {r1.text}"
    assert "tutorial_action_blocked" in r1.text

    r2 = requests.post(
        f"{BASE_URL}/api/market/buy",
        json={"listing_id": "nonexistent", "amount": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r2.status_code == 403, f"buy not blocked: {r2.status_code} {r2.text}"
    assert "tutorial_action_blocked" in r2.text

    # Deactivate tutorial: endpoints should no longer return 403 tutorial_action_blocked
    db.users.update_one(
        {"id": user_id} if db.users.find_one({"id": user_id}) else {"_id": user_id},
        {"$set": {"tutorial_active": False, "tutorial_completed": True}},
    )

    r3 = requests.post(
        f"{BASE_URL}/api/market/list-resource",
        json={"resource_type": "biomass", "amount": 1, "price_per_unit": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    if r3.status_code == 403:
        assert "tutorial_action_blocked" not in r3.text, f"still blocked by tutorial: {r3.text}"

    r4 = requests.post(
        f"{BASE_URL}/api/market/buy",
        json={"listing_id": "nonexistent", "amount": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    if r4.status_code == 403:
        assert "tutorial_action_blocked" not in r4.text, f"still blocked by tutorial: {r4.text}"


def test_zzz_cleanup(db, user_id):
    """Restore testuser@example.com to a clean state."""
    q = {"id": user_id} if db.users.find_one({"id": user_id}) else {"_id": user_id}
    db.users.update_one(
        q,
        {
            "$set": {
                "tutorial_active": False,
                "tutorial_completed": True,
                "resources": {},
                "balance_ton": 100.0,
                "wallet_address": None,
            },
            "$unset": {
                "tutorial_snapshot": "",
                "tutorial_state": "",
                "tutorial_current_step": "",
                "tutorial_t3_reward_granted": "",
                "tutorial_t3_reward_choice": "",
                "tutorial_t3_reward_granted_at": "",
                "tutorial_pending_t3_auto_activate": "",
            },
        },
    )
    doc = db.users.find_one(q)
    assert doc["tutorial_active"] is False
    assert doc["resources"] == {}
    assert doc["balance_ton"] == 100.0
