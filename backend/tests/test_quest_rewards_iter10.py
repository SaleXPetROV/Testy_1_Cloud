"""Iter 10: Quest reward funds target (bonus vs real) + skin group grant."""
import os
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://quest-rewards-74.preview.emergentagent.com').rstrip('/')
MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PW = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PW = "Test1234!"


@pytest.fixture(scope="module")
def db():
    return MongoClient(MONGO_URL)[DB_NAME]


def _login(email, pw):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json().get("token") or r.json().get("access_token")


@pytest.fixture(scope="module")
def admin_token():
    return _login(ADMIN_EMAIL, ADMIN_PW)


@pytest.fixture(scope="module")
def user_token():
    return _login(USER_EMAIL, USER_PW)


def _create_quest(admin_token, funds_target, amount=3000):
    payload = {
        "title": f"TEST_iter10_quest_{funds_target}",
        "reward_city": 0,
        "action_type": "partner_quest",
        "quest_kind": "local",
        "reward_skins": [{"id": "crazy_bio_farm", "name": "Crazy Bio Farm"}],
        "reward_funds_amount": amount,
        "reward_funds_target": funds_target,
    }
    r = requests.post(f"{BASE_URL}/api/admin/tasks",
                      json=payload,
                      headers={"Authorization": f"Bearer {admin_token}"}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["task"]


def _reset_user(db, task_ids):
    db.users.update_one({"email": USER_EMAIL},
                        {"$set": {"bonus_balance": 0, "balance_ton": 0, "available_skins": []}})
    for tid in task_ids:
        db.task_completions.delete_many({"task_id": tid})
        db.tasks.delete_one({"id": tid})


def test_quest_reward_bonus_target(db, admin_token, user_token):
    task = _create_quest(admin_token, "bonus", 3000)
    tid = task["id"]
    try:
        # baseline
        db.users.update_one({"email": USER_EMAIL},
                            {"$set": {"bonus_balance": 0, "balance_ton": 0, "available_skins": []}})
        before = db.users.find_one({"email": USER_EMAIL})
        r = requests.post(f"{BASE_URL}/api/tasks/{tid}/verify",
                          headers={"Authorization": f"Bearer {user_token}"}, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("status") == "completed"
        rewards = body.get("rewards") or {}
        assert rewards.get("funds") == {"amount": 3000, "target": "bonus"}, rewards
        skin_ids = [s.get("id") for s in (rewards.get("skins") or [])]
        assert "crazy_bio_farm" in skin_ids

        after = db.users.find_one({"email": USER_EMAIL})
        assert round(after.get("bonus_balance", 0) - before.get("bonus_balance", 0), 6) == 3.0
        # real balance should NOT change
        assert round(after.get("balance_ton", 0) - before.get("balance_ton", 0), 6) == 0.0
        assert "crazy_bio_farm" in (after.get("available_skins") or [])
    finally:
        _reset_user(db, [tid])


def test_quest_reward_real_target(db, admin_token, user_token):
    task = _create_quest(admin_token, "real", 3000)
    tid = task["id"]
    try:
        db.users.update_one({"email": USER_EMAIL},
                            {"$set": {"bonus_balance": 0, "balance_ton": 0, "available_skins": []}})
        before = db.users.find_one({"email": USER_EMAIL})
        r = requests.post(f"{BASE_URL}/api/tasks/{tid}/verify",
                          headers={"Authorization": f"Bearer {user_token}"}, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        rewards = body.get("rewards") or {}
        assert rewards.get("funds") == {"amount": 3000, "target": "real"}, rewards

        after = db.users.find_one({"email": USER_EMAIL})
        assert round(after.get("balance_ton", 0) - before.get("balance_ton", 0), 6) == 3.0
        assert round(after.get("bonus_balance", 0) - before.get("bonus_balance", 0), 6) == 0.0
    finally:
        _reset_user(db, [tid])


def test_admin_skin_groups_endpoint(admin_token):
    r = requests.get(f"{BASE_URL}/api/admin/skins/groups",
                     headers={"Authorization": f"Bearer {admin_token}"}, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    # normalize
    groups = data.get("groups") if isinstance(data, dict) else data
    keys = []
    if isinstance(groups, list):
        for g in groups:
            keys.append(g.get("group_key") or g.get("key") or g.get("id"))
    assert "crazy_bio_farm" in keys or "standard" in keys, groups
