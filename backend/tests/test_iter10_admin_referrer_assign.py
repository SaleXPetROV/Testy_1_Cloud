"""
Iteration 10 tests:
- GET /api/admin/players/{id} includes 'referrer' (null when none)
- POST /api/admin/players/{player_id}/referrer assigns/changes referrer
- Self-referral -> 400; unknown referrer -> 404
- After change, /api/admin/players/<admin>/referrals includes testuser
Cleanup at end: unset referrerId/partner_ref_id/ref_by/partner_joined_at on testuser.
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
ADMIN_ID = "eb15ac93-28ca-4d98-8215-4450108af240"
TESTUSER_ID = "a48b93c7-e789-4eb2-ab37-85781ab617ad"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=15)
    assert r.status_code == 200, r.text[:200]
    return r.json().get("token") or r.json().get("access_token")


@pytest.fixture(scope="module")
def db():
    return MongoClient(MONGO_URL)[DB_NAME]


def _h(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module", autouse=True)
def _cleanup(db):
    # Ensure clean before + after
    db.users.update_one({"id": TESTUSER_ID}, {"$unset": {
        "referrerId": "", "partner_ref_id": "", "ref_by": "", "partner_joined_at": ""
    }})
    yield
    db.users.update_one({"id": TESTUSER_ID}, {"$unset": {
        "referrerId": "", "partner_ref_id": "", "ref_by": "", "partner_joined_at": ""
    }})


def test_player_details_referrer_null_initially(admin_token):
    r = requests.get(f"{BASE_URL}/api/admin/players/{TESTUSER_ID}", headers=_h(admin_token), timeout=15)
    assert r.status_code == 200, r.text[:300]
    data = r.json()
    assert "referrer" in data, f"missing referrer key: {list(data.keys())[:20]}"
    assert data["referrer"] is None, f"expected None, got {data['referrer']}"


def test_self_referral_returns_400(admin_token):
    r = requests.post(
        f"{BASE_URL}/api/admin/players/{TESTUSER_ID}/referrer",
        headers=_h(admin_token), json={"referrer_id": TESTUSER_ID}, timeout=15)
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text[:200]}"


def test_unknown_referrer_returns_404(admin_token):
    r = requests.post(
        f"{BASE_URL}/api/admin/players/{TESTUSER_ID}/referrer",
        headers=_h(admin_token), json={"referrer_id": "TEST_nonexistent_referrer_zzz"}, timeout=15)
    assert r.status_code == 404, f"expected 404, got {r.status_code}: {r.text[:200]}"


def test_assign_referrer_and_verify(admin_token, db):
    r = requests.post(
        f"{BASE_URL}/api/admin/players/{TESTUSER_ID}/referrer",
        headers=_h(admin_token), json={"referrer_id": ADMIN_ID}, timeout=15)
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert body.get("referrer", {}).get("id") == ADMIN_ID

    # verify DB
    tu = db.users.find_one({"id": TESTUSER_ID})
    assert tu.get("referrerId") == ADMIN_ID
    assert tu.get("partner_ref_id") == ADMIN_ID
    assert tu.get("ref_by") == ADMIN_ID

    # GET player details now returns referrer
    r2 = requests.get(f"{BASE_URL}/api/admin/players/{TESTUSER_ID}", headers=_h(admin_token), timeout=15)
    assert r2.status_code == 200
    ref = r2.json().get("referrer")
    assert ref and ref.get("id") == ADMIN_ID, ref

    # GET admin's referrals includes testuser
    r3 = requests.get(f"{BASE_URL}/api/admin/players/{ADMIN_ID}/referrals", headers=_h(admin_token), timeout=15)
    assert r3.status_code == 200
    payload = r3.json()
    assert payload.get("count", 0) >= 1
    referrals = payload.get("referrals") or payload.get("items") or payload.get("rows") or []
    # look for testuser in any form
    hit = any(
        (it.get("id") == TESTUSER_ID) or (it.get("user_id") == TESTUSER_ID)
        or (it.get("username") == "testuser") or ("testuser" in str(it).lower())
        for it in referrals
    )
    assert hit, f"testuser not found in admin referrals: {referrals}"
