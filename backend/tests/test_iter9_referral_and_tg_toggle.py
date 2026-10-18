"""
Iteration 9 tests:
- Admin login
- GET/POST /api/admin/settings/telegram-registration
- GET /api/admin/referrals sort=total (include partners)
- GET /api/leaderboard sort_by=balance (balance=balance_ton+bonus_balance, businesses_count present, exclude partners)
- Referral attribution logic via inserted fake user (ref_by=<admin_id>)
"""
import os
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PASSWORD = "Test1234!"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=15)
    return r


@pytest.fixture(scope="module")
def admin_token():
    r = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text[:200]}"
    data = r.json()
    assert data.get("user", {}).get("is_admin") is True or data.get("is_admin") is True, f"is_admin missing: {data}"
    return data.get("token") or data.get("access_token")


@pytest.fixture(scope="module")
def user_token():
    r = _login(USER_EMAIL, USER_PASSWORD)
    assert r.status_code == 200, f"user login failed: {r.status_code} {r.text[:200]}"
    return r.json().get("token") or r.json().get("access_token")


@pytest.fixture(scope="module")
def db():
    client = MongoClient(MONGO_URL)
    return client[DB_NAME]


def _h(token):
    return {"Authorization": f"Bearer {token}"}


# ----------------- Admin telegram-registration toggle -----------------

def test_get_tg_registration_setting_default_true(admin_token):
    r = requests.get(f"{BASE_URL}/api/admin/settings/telegram-registration", headers=_h(admin_token), timeout=15)
    assert r.status_code == 200, r.text[:300]
    data = r.json()
    assert "choice_enabled" in data
    assert data["choice_enabled"] is True


def test_toggle_tg_registration_off_then_back_on(admin_token):
    # OFF
    r = requests.post(
        f"{BASE_URL}/api/admin/settings/telegram-registration",
        headers=_h(admin_token),
        json={"choice_enabled": False},
        timeout=15,
    )
    assert r.status_code == 200, r.text[:300]
    assert r.json().get("choice_enabled") is False

    r2 = requests.get(f"{BASE_URL}/api/admin/settings/telegram-registration", headers=_h(admin_token), timeout=15)
    assert r2.status_code == 200
    assert r2.json().get("choice_enabled") is False

    # restore ON
    r3 = requests.post(
        f"{BASE_URL}/api/admin/settings/telegram-registration",
        headers=_h(admin_token),
        json={"choice_enabled": True},
        timeout=15,
    )
    assert r3.status_code == 200
    assert r3.json().get("choice_enabled") is True


def test_tg_registration_requires_admin(user_token):
    r = requests.get(f"{BASE_URL}/api/admin/settings/telegram-registration", headers=_h(user_token), timeout=15)
    assert r.status_code in (401, 403), r.status_code


# ----------------- Admin referrals -----------------

def _rows(payload):
    if isinstance(payload, dict):
        return payload.get("rows") or payload.get("items") or []
    return payload or []


def test_admin_referrals_sort_total_includes_partners(admin_token, db):
    r = requests.get(f"{BASE_URL}/api/admin/referrals?sort=total", headers=_h(admin_token), timeout=15)
    assert r.status_code == 200, r.text[:300]
    data = r.json()
    rows = _rows(data)
    total_count = data.get("total_count") if isinstance(data, dict) else len(rows)
    users_in_db = db.users.count_documents({})
    assert total_count == users_in_db, f"total_count {total_count} != users {users_in_db}"
    assert len(rows) >= users_in_db
    for it in rows:
        assert "total" in it, f"missing total: {it}"


# ----------------- Leaderboard -----------------

def test_leaderboard_balance_and_businesses_count(db):
    r = requests.get(f"{BASE_URL}/api/leaderboard?sort_by=balance", timeout=15)
    assert r.status_code == 200, r.text[:300]
    data = r.json()
    players = data.get("players") if isinstance(data, dict) else data
    assert isinstance(players, list)
    # find admin & user; b2b partners must be excluded, so mark none as partner for this baseline
    for p in players:
        assert "businesses_count" in p, f"missing businesses_count in {p}"
        assert isinstance(p["businesses_count"], int)
        assert "balance_ton" in p
    # Check that balance_ton reflects balance_ton+bonus_balance from DB
    for p in players[:5]:
        uid = p.get("id") or p.get("user_id")
        if not uid:
            continue
        u = db.users.find_one({"id": uid}) or db.users.find_one({"_id": uid})
        if not u:
            continue
        expected = float(u.get("balance_ton", 0) or 0) + float(u.get("bonus_balance", 0) or 0)
        # tolerate small float
        assert abs(float(p["balance_ton"]) - expected) < 1e-6, f"{p['balance_ton']} != {expected}"


def test_leaderboard_excludes_partners(db, admin_token):
    # Mark admin as b2b partner temporarily
    admin = db.users.find_one({"email": ADMIN_EMAIL})
    assert admin is not None
    admin_id = admin.get("id") or str(admin.get("_id"))
    db.users.update_one({"email": ADMIN_EMAIL}, {"$set": {"b2b_is_partner": True}})
    try:
        r = requests.get(f"{BASE_URL}/api/leaderboard?sort_by=balance", timeout=15)
        assert r.status_code == 200
        players = r.json().get("players") if isinstance(r.json(), dict) else r.json()
        ids = [p.get("id") or p.get("user_id") for p in players]
        assert admin_id not in ids, f"admin partner leaked into public leaderboard: {ids}"

        # But admin referrals list still contains partners
        r2 = requests.get(f"{BASE_URL}/api/admin/referrals?sort=total", headers=_h(admin_token), timeout=15)
        assert r2.status_code == 200
        rows = _rows(r2.json())
        ref_ids = [it.get("user_id") or it.get("id") for it in rows]
        assert admin_id in ref_ids, f"partner excluded from admin referrals list: {ref_ids}"
    finally:
        db.users.update_one({"email": ADMIN_EMAIL}, {"$set": {"b2b_is_partner": False}})


# ----------------- Referral attribution logic -----------------

def test_referral_attribution_via_ref_by(admin_token, db):
    admin = db.users.find_one({"email": ADMIN_EMAIL})
    testuser = db.users.find_one({"email": USER_EMAIL})
    assert admin and testuser
    admin_id = admin.get("id") or str(admin.get("_id"))
    testuser_id = testuser.get("id") or str(testuser.get("_id"))

    fake_id = "TEST_referral_fake_user_iter9"
    db.users.delete_many({"id": fake_id})
    db.users.insert_one({
        "id": fake_id,
        "email": "TEST_fake@example.com",
        "ref_by": admin_id,
        "referrerId": testuser_id,
        "plots_owned": ["x"],
        "balance_ton": 0,
        "bonus_balance": 0,
    })
    try:
        # admin player referrals endpoint
        r = requests.get(f"{BASE_URL}/api/admin/players/{admin_id}/referrals", headers=_h(admin_token), timeout=15)
        assert r.status_code == 200, r.text[:300]
        payload = r.json()
        count = payload.get("count", 0)
        assert count >= 1, f"count should be >=1 after inserting fake ref, got {count}, payload={payload}"

        # admin referrals aggregate list — admin row total should be >=1
        r2 = requests.get(f"{BASE_URL}/api/admin/referrals?sort=total", headers=_h(admin_token), timeout=15)
        assert r2.status_code == 200
        rows = _rows(r2.json())
        admin_row = next((it for it in rows if (it.get("user_id") or it.get("id")) == admin_id), None)
        assert admin_row is not None, f"admin row missing: {rows}"
        tot = admin_row.get("total", 0)
        assert int(tot) >= 1, f"admin total should reflect fake referral, got {tot}"
    finally:
        db.users.delete_many({"id": fake_id})
