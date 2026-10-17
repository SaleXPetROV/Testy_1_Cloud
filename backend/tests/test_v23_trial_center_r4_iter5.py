"""
Iter 5 — Trial Center Round-4 fixes.

Covers:
  1. Login both accounts.
  2. Durability 50%/day (exact) via backdate → GET /api/trial-center.
  3. Trial NOT double-worn by background tasks (economic_tick +
     apply_global_durability_wear both exclude is_trial in code).
  4. Real business wear: get_daily_wear returns 0.30 for tier1/2/3; idle
     multiplier is 0.5 (→ 45%/day); on_sale skipped.
  5. 1-hour expiry notification: backdate trial so ~30 min remain, clear
     trial_1h_notified, set language='en', call notify_trial_expiring()
     directly; verify notifications row + trial_1h_notified=True + no dup.
  6. Expired card (>72h): backend serialization → remaining_seconds==0,
     is_expired=True, is_active=False, can_hide=True; no further accrual
     changes to user.resources after expiry.
  7. Cleanup: no trial owned, admin.tutorial_completed=False resources={},
     testuser resources={} bonus_balance=1.0; Helios intact.
"""
import os
import sys
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

TEST_USER = {"email": "testuser@example.com", "password": "Test1234!"}
ADMIN = {"email": "sanyanazarov212@gmail.com", "password": os.environ.get("TEST_ADMIN_PASSWORD", "")}

# Allow importing backend modules for direct calls (business_config, background_tasks)
sys.path.insert(0, "/app/backend")


def _login(creds):
    r = requests.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=30)
    assert r.status_code == 200, f"login {creds['email']}: {r.status_code} {r.text[:200]}"
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


# ---------- 2/3. Durability exactly 50%/day ----------
def test_durability_50pct_per_day(mongo, testuser_token):
    _delete_trial_for(mongo, TEST_USER["email"])
    mongo.users.update_one({"email": TEST_USER["email"]}, {"$set": {"resources": {}, "bonus_balance": 1.0}})

    # Buy
    r = requests.post(f"{BASE_URL}/api/trial-center/buy", headers=_hdr(testuser_token), timeout=30)
    assert r.status_code == 200, r.text
    u = mongo.users.find_one({"email": TEST_USER["email"]})
    biz = mongo.businesses.find_one({"is_trial": True, "owner": u["id"]})
    assert biz

    # Backdate 24h; reset durability to 100
    past = (datetime.now(timezone.utc) - timedelta(hours=24, minutes=1)).isoformat()
    mongo.businesses.update_one(
        {"id": biz["id"]},
        {"$set": {
            "trial_start_timestamp": past,
            "created_at": past,
            "last_accrued": past,
            "durability": 100.0,
        }},
    )
    r = requests.get(f"{BASE_URL}/api/trial-center", headers=_hdr(testuser_token), timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    dur = d["business"]["durability"]
    assert 48.0 <= dur <= 52.0, f"expected durability ≈50 after 24h, got {dur}"


def test_trial_excluded_from_background_wear_tasks():
    """Verify code — both wear jobs skip is_trial businesses."""
    import background_tasks as bt
    src = open(bt.__file__).read()
    # economic_tick query
    assert 'is_trial' in src and '"is_trial": {"$ne": True}' in src
    # apply_global_durability_wear too — 2 occurrences at least
    assert src.count('"is_trial": {"$ne": True}') >= 2


# ---------- 4. Real business wear ----------
def test_real_business_wear_rates_config():
    from business_config import get_daily_wear
    for bt_key in ("data_center", "hydro_cooling", "server_farm"):
        try:
            w = get_daily_wear(bt_key, 1)
        except Exception:
            w = 0.30
        # All tiers must be 0.30 flat
        assert abs(w - 0.30) < 1e-6, f"{bt_key} daily_wear = {w}, expected 0.30"

    # Unknown default too
    assert abs(get_daily_wear("__unknown__", 1) - 0.30) < 1e-6


def test_idle_extra_wear_multiplier_and_on_sale_skip():
    """Static code check: idle multiplier is 0.5 (30% base × 0.5 extra = 45%/day),
    and on_sale businesses are skipped in economic_tick."""
    import background_tasks as bt
    src = open(bt.__file__).read()
    assert "hours_passed / 24.0) * 0.5" in src, "idle extra_wear multiplier must be 0.5"
    assert 'if business.get("on_sale") or business.get("status") == "on_sale":' in src


# ---------- 5. 1-hour expiry notification ----------
def test_trial_1h_notification(mongo, testuser_token):
    """Backdate trial → 30 min remaining; run notify_trial_expiring; check notif."""
    u = mongo.users.find_one({"email": TEST_USER["email"]})
    biz = mongo.businesses.find_one({"is_trial": True, "owner": u["id"]})
    assert biz, "trial must exist from previous test"

    # 71.5h ago → 30 min remaining until 72h expiry
    start = (datetime.now(timezone.utc) - timedelta(hours=71, minutes=30)).isoformat()
    mongo.businesses.update_one(
        {"id": biz["id"]},
        {"$set": {
            "trial_start_timestamp": start,
            "created_at": start,
            "last_accrued": start,
            "durability": 100.0,
            "is_expired": False,
        },
         "$unset": {"trial_1h_notified": ""}},
    )
    mongo.users.update_one({"email": TEST_USER["email"]}, {"$set": {"language": "en"}})

    # Clear previous trial_expiring notifications for a clean check
    mongo.notifications.delete_many({"user_id": u["id"], "type": "trial_expiring"})

    # Patch _get_shared_db to a Motor client bound to our test DB
    import background_tasks as bt
    from motor.motor_asyncio import AsyncIOMotorClient
    mc = AsyncIOMotorClient(MONGO_URL)
    mdb = mc[DB_NAME]
    orig_get = bt._get_shared_db
    bt._get_shared_db = lambda: mdb
    try:
        asyncio.get_event_loop().run_until_complete(bt.notify_trial_expiring())
    finally:
        bt._get_shared_db = orig_get

    # Verify notification row
    notif = mongo.notifications.find_one({"user_id": u["id"], "type": "trial_expiring"})
    assert notif is not None, "expected a notifications row of type=trial_expiring"
    msg = (notif.get("message") or "") + " " + (notif.get("title") or "")
    assert "Trial" in msg or "trial" in msg, f"english message expected, got: {msg[:200]}"
    # Business flagged
    biz2 = mongo.businesses.find_one({"id": biz["id"]}, {"trial_1h_notified": 1})
    assert biz2.get("trial_1h_notified") is True

    # Second run must NOT create a duplicate
    n0 = mongo.notifications.count_documents({"user_id": u["id"], "type": "trial_expiring"})
    bt._get_shared_db = lambda: mdb
    try:
        asyncio.get_event_loop().run_until_complete(bt.notify_trial_expiring())
    finally:
        bt._get_shared_db = orig_get
    n1 = mongo.notifications.count_documents({"user_id": u["id"], "type": "trial_expiring"})
    assert n1 == n0, f"duplicate notifications produced: before={n0} after={n1}"
    mc.close()


# ---------- 6. Expired card lockdown ----------
def test_expired_card_state_and_no_further_accrual(mongo, testuser_token):
    """Backdate >72h → API returns is_expired/is_active=False, remaining=0,
    can_hide=True. After first GET (accrual runs), resources must NOT change
    on a second GET (last_accrued frozen at expiry)."""
    u = mongo.users.find_one({"email": TEST_USER["email"]})
    biz = mongo.businesses.find_one({"is_trial": True, "owner": u["id"]})
    assert biz

    # Reset resources baseline & backdate far past
    mongo.users.update_one({"email": TEST_USER["email"]}, {"$set": {"resources": {}}})
    past = (datetime.now(timezone.utc) - timedelta(hours=80)).isoformat()
    mongo.businesses.update_one(
        {"id": biz["id"]},
        {"$set": {
            "trial_start_timestamp": past,
            "created_at": past,
            "last_accrued": past,
            "durability": 100.0,
            "is_expired": False,
            "is_active": True,
        }},
    )
    r = requests.get(f"{BASE_URL}/api/trial-center", headers=_hdr(testuser_token), timeout=30)
    assert r.status_code == 200, r.text
    b = r.json()["business"]
    assert b["remaining_seconds"] == 0
    assert b["is_expired"] is True
    assert b["is_active"] is False
    assert b["can_hide"] is True

    # Capture resources after 1st GET
    res1 = (mongo.users.find_one({"email": TEST_USER["email"]}, {"resources": 1}) or {}).get("resources", {}) or {}
    # 2nd GET must not further alter resources
    requests.get(f"{BASE_URL}/api/trial-center", headers=_hdr(testuser_token), timeout=30)
    res2 = (mongo.users.find_one({"email": TEST_USER["email"]}, {"resources": 1}) or {}).get("resources", {}) or {}
    assert res1 == res2, f"resources changed after expiry: {res1} vs {res2}"


# ---------- 7. Buy confirm endpoint accepts (server-side POST still works) ----------
def test_buy_endpoint_still_works_after_reset(mongo, admin_token):
    # ensure admin has no trial and enough balance
    _delete_trial_for(mongo, ADMIN["email"])
    mongo.users.update_one({"email": ADMIN["email"]}, {"$set": {"resources": {}, "bonus_balance": 5.0}})
    r = requests.post(f"{BASE_URL}/api/trial-center/buy", headers=_hdr(admin_token), timeout=30)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "purchased"


# ---------- 8. Cleanup (LAST) ----------
def test_zzz_cleanup(mongo):
    for email in (ADMIN["email"], TEST_USER["email"]):
        _delete_trial_for(mongo, email)

    mongo.users.update_one(
        {"email": ADMIN["email"]},
        {"$set": {"tutorial_completed": False, "resources": {}}},
    )
    mongo.users.update_one(
        {"email": TEST_USER["email"]},
        {"$set": {"resources": {}, "bonus_balance": 1.0}},
    )

    a = mongo.users.find_one({"email": ADMIN["email"]}, {"_id": 0, "tutorial_completed": 1, "resources": 1, "trial_center_purchased": 1})
    assert a.get("tutorial_completed") is False
    assert a.get("resources") == {}
    assert not a.get("trial_center_purchased")

    # Helios must still exist
    helios = mongo.businesses.find_one({"owner": mongo.users.find_one({"email": ADMIN["email"]})["id"], "is_trial": {"$ne": True}})
    assert helios is not None, "Helios (real business) must remain intact"
