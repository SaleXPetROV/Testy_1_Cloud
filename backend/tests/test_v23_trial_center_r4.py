"""
Iter 4 — Trial Center round-3 fixes.

Covers:
  1. Login for both testuser + sanyanazarov (admin).
  2. Proportional warehouse split when the owner has BOTH a real business
     (Helios cap 360) AND a Trial Center (cap 300).
  3. Consume/Produce apply on the OWNER's GLOBAL user.resources.
  4. Durability wears at 50% / day.
  5. Trial /api/trial-center exposes storage_info as a proportional share.
  6. cleanup: after tests, restore sanyanazarov to the required baseline
     (tutorial_completed=False, resources={}, no trial biz, no purchase flag).
"""
import os
import time
from datetime import datetime, timedelta, timezone

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

TEST_USER = {"email": "testuser@example.com", "password": "Test1234!"}
ADMIN = {"email": "sanyanazarov212@gmail.com", "password": os.environ.get("TEST_ADMIN_PASSWORD", "")}


# ---------- helpers ----------
def _login(creds):
    r = requests.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=30)
    assert r.status_code == 200, f"login failed for {creds['email']}: {r.status_code} {r.text}"
    return r.json()["token"]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def mongo():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


@pytest.fixture(scope="module")
def testuser_token():
    return _login(TEST_USER)


@pytest.fixture(scope="module")
def admin_token():
    return _login(ADMIN)


def _delete_trial_for(db, email):
    u = db.users.find_one({"email": email})
    if u:
        db.businesses.delete_many({"is_trial": True, "owner": u.get("id")})
        db.users.update_one(
            {"email": email},
            {"$unset": {"trial_center_purchased": "", "trial_center_hidden": "", "trial_center_started_at": ""}},
        )


# ---------- 1. Login sanity ----------
def test_login_testuser(testuser_token):
    assert isinstance(testuser_token, str) and len(testuser_token) > 20


def test_login_admin(admin_token):
    assert isinstance(admin_token, str) and len(admin_token) > 20


# ---------- 2. Trial buy on sanyanazarov + proportional warehouse ----------
def test_proportional_warehouse_split(mongo, admin_token):
    # clean state (safety)
    _delete_trial_for(mongo, ADMIN["email"])
    # reset resources so accrual has predictable state, capture what we set
    mongo.users.update_one({"email": ADMIN["email"]}, {"$set": {"resources": {}}})

    # confirm Helios exists at cap 360
    me = requests.get(f"{BASE_URL}/api/auth/me", headers=_hdr(admin_token), timeout=30).json()
    assert me.get("email") == ADMIN["email"]

    r = requests.get(f"{BASE_URL}/api/my/businesses", headers=_hdr(admin_token), timeout=30)
    assert r.status_code == 200, r.text
    d0 = r.json()
    cap0 = d0.get("summary", {}).get("total_warehouse_capacity")
    assert cap0 == 360, f"expected Helios-only cap 360, got {cap0} — summary={d0.get('summary')}"

    # buy trial
    r = requests.post(f"{BASE_URL}/api/trial-center/buy", headers=_hdr(admin_token), timeout=30)
    assert r.status_code == 200, r.text
    buy = r.json()
    assert buy["status"] == "purchased"
    # buy grants 25 cu to user.resources → global used = 25 * weight(cu)
    # (weight is >=1). We don't hardcode weight; verify proportionality instead.

    # /my/businesses now should have total_warehouse_capacity == 360 + 300 == 660
    r = requests.get(f"{BASE_URL}/api/my/businesses", headers=_hdr(admin_token), timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    summary = d.get("summary", {})
    assert summary.get("total_warehouse_capacity") == 660, (
        f"expected 660, got {summary.get('total_warehouse_capacity')} — summary={summary}"
    )
    total_used_global = int(summary.get("total_warehouse_used", 0))
    assert total_used_global > 0, "after buy, global warehouse used should be >0 (25 cu credited)"

    # Helios in the businesses list should get proportional used = total*360/660
    biz_list = d.get("businesses") or d.get("items") or []
    helios = next((b for b in biz_list if (b.get("name") in ("Helios",) or (isinstance(b.get("name"), dict) and b.get("name", {}).get("en") == "Helios"))), None)
    assert helios is not None, f"Helios not found in /my/businesses: {[b.get('name') for b in biz_list]}"
    h_used = int((helios.get("storage_info") or {}).get("used", -1))
    expected_h = int(total_used_global * 360 / 660)
    assert abs(h_used - expected_h) <= 1, (
        f"Helios used should be proportional (~{expected_h}), got {h_used} "
        f"(total_used={total_used_global}, cap=660)"
    )
    # Also verify Helios capacity == 360
    assert (helios.get("storage_info") or {}).get("capacity") == 360

    # /api/trial-center should also report the proportional share
    r = requests.get(f"{BASE_URL}/api/trial-center", headers=_hdr(admin_token), timeout=30)
    assert r.status_code == 200, r.text
    tc = r.json()
    assert tc.get("owned") is True
    s = tc["business"]["storage_info"]
    assert s["capacity"] == 300
    expected_t = int(total_used_global * 300 / 660)
    assert abs(s["used"] - expected_t) <= 1, (
        f"Trial used should be proportional (~{expected_t}), got {s['used']}"
    )
    # Ensure they do NOT both equal 25 (previous bug):
    assert not (h_used == 25 and s["used"] == 25), (
        "Both businesses show full 25 units — proportional split failed"
    )
    # Sanity: sum of shares ~= total (±2 for rounding)
    assert abs((h_used + s["used"]) - total_used_global) <= 2


# ---------- 3+4. Consume/Produce global + durability -50%/day ----------
def test_accrual_consume_produce_and_durability(mongo, admin_token):
    """Backdate the trial by 24h and hit /api/trial-center to trigger _accrue."""
    u = mongo.users.find_one({"email": ADMIN["email"]})
    biz = mongo.businesses.find_one({"is_trial": True, "owner": u["id"]})
    assert biz is not None, "trial must exist from previous test"

    # snapshot resources BEFORE
    res_before = (mongo.users.find_one({"email": ADMIN["email"]}, {"resources": 1}) or {}).get("resources", {}) or {}
    cu_before = float(res_before.get("cu", 0) or 0)
    cooling_before = float(res_before.get("cooling", 0) or 0)

    # backdate ~24h
    past = (datetime.now(timezone.utc) - timedelta(hours=24, minutes=1)).isoformat()
    mongo.businesses.update_one(
        {"id": biz["id"]},
        {"$set": {"trial_start_timestamp": past, "created_at": past, "last_accrued": past}},
    )

    # trigger accrual via GET (server's _accrue mutates DB + returns state)
    r = requests.get(f"{BASE_URL}/api/trial-center", headers=_hdr(admin_token), timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    dur = d["business"]["durability"]
    # 50%/day means after 24h durability should be ~50 (starting from 100)
    assert 48.0 <= dur <= 52.0, f"expected durability ≈50 after 24h, got {dur}"

    # resources should reflect: cu decreased (bounded by availability 25), cooling increased ≈89
    res_after = (mongo.users.find_one({"email": ADMIN["email"]}, {"resources": 1}) or {}).get("resources", {}) or {}
    cu_after = float(res_after.get("cu", 0) or 0)
    cooling_after = float(res_after.get("cooling", 0) or 0)

    cu_delta = cu_after - cu_before          # negative
    cooling_delta = cooling_after - cooling_before  # positive
    # Bound by 25 (only 25 cu were available); worked_days should equal 25/25 = 1
    assert -25.5 <= cu_delta <= -24.5, f"cu should decrease by ~25 (bounded by stock); delta={cu_delta}"
    # If worked_days==1 exactly, cooling produced = 89
    assert 88.0 <= cooling_delta <= 90.0, f"cooling should increase by ~89, delta={cooling_delta}"


# ---------- 5. Testuser flow still works (buy → warehouse 300, seed 25) ----------
def test_testuser_trial_buy_still_works(mongo, testuser_token):
    _delete_trial_for(mongo, TEST_USER["email"])
    mongo.users.update_one({"email": TEST_USER["email"]}, {"$set": {"resources": {}}})

    r = requests.post(f"{BASE_URL}/api/trial-center/buy", headers=_hdr(testuser_token), timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "purchased"
    assert d["business"]["storage_info"]["capacity"] == 300
    # NOTE: /buy response's storage_info is computed WITHOUT the global context
    # (falls back to biz.storage.items which is empty → used=0). The proper
    # used=25 shows up on the very next GET /api/trial-center, verified below.
    # Confirm proportional used via GET (25 cu × weight in shared pool).
    r_get = requests.get(f"{BASE_URL}/api/trial-center", headers=_hdr(testuser_token), timeout=30)
    assert r_get.status_code == 200
    dg = r_get.json()
    used = dg["business"]["storage_info"]["used"]
    # testuser has no other biz → global_cap == 300, so proportional == global_used.
    # Weight of cu is a small positive int; used should be >=25 (assuming weight>=1).
    assert used >= 25, f"expected proportional used >= 25 after buy, got {used}"

    # second buy → 400
    r2 = requests.post(f"{BASE_URL}/api/trial-center/buy", headers=_hdr(testuser_token), timeout=30)
    assert r2.status_code == 400


# ---------- 6. Cleanup (LAST) ----------
def test_zzz_cleanup_restore_user_baselines(mongo):
    """Restore both accounts to what the review request requires:
       - No trial center owned
       - sanyanazarov: tutorial_completed=False, resources={}
    """
    for email in (ADMIN["email"], TEST_USER["email"]):
        _delete_trial_for(mongo, email)

    mongo.users.update_one(
        {"email": ADMIN["email"]},
        {"$set": {"tutorial_completed": False, "resources": {}}},
    )
    # testuser: leave tutorial as-is but ensure resources cleared
    mongo.users.update_one(
        {"email": TEST_USER["email"]},
        {"$set": {"resources": {}}},
    )

    # verify
    a = mongo.users.find_one({"email": ADMIN["email"]}, {"_id": 0, "tutorial_completed": 1, "resources": 1, "trial_center_purchased": 1})
    assert a.get("tutorial_completed") is False
    assert a.get("resources") == {}
    assert not a.get("trial_center_purchased")
    assert mongo.businesses.count_documents({"is_trial": True, "owner": mongo.users.find_one({"email": ADMIN['email']})["id"]}) == 0

    t = mongo.users.find_one({"email": TEST_USER["email"]}, {"_id": 0, "trial_center_purchased": 1, "resources": 1})
    assert not t.get("trial_center_purchased")
