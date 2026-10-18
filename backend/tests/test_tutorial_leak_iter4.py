"""
Iteration 4 regression tests for tutorial resource-leak protection.

Covers:
  T1 Happy path /finish keeps only T3 reward, no leaked biomass/neuro_core.
  T2 /abandon path zeros out granted resources.
  T3 /reset path zeros out granted resources.
  T4 Corrupted snapshot -> fallback clawback via granted_resources.
  T5 /status self-heal of leftover granted_resources.
  T6 Background auto_complete_expired_tutorials cleans stuck users.
  T7 /mark-skipped with leftover state cleans and grants T3.

MongoDB is accessed directly (localhost:27017 / test_database) for state
manipulation and assertions since /api/user/me does not expose resources.
"""
import os
import asyncio

import pytest
import requests
from pymongo import MongoClient

# Load backend env for MONGO_URL / DB_NAME
with open("/app/backend/.env") as _f:
    for _line in _f:
        if "=" in _line and not _line.strip().startswith("#"):
            _k, _v = _line.strip().split("=", 1)
            os.environ.setdefault(_k, _v.strip('"'))

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") if os.environ.get(
    "REACT_APP_BACKEND_URL"
) else open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split("\n")[0].strip().rstrip("/")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

TEST_EMAIL = "testuser@example.com"
TEST_PASSWORD = "Test1234!"


# ---------- fixtures ----------

@pytest.fixture(scope="module")
def db():
    client = MongoClient(MONGO_URL)
    return client[DB_NAME]


@pytest.fixture(scope="module")
def token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        timeout=15,
    )
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    j = r.json()
    tk = j.get("access_token") or j.get("token")
    assert tk, f"no token in login response: {j}"
    return tk


@pytest.fixture(scope="module")
def hdr(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def user_id(hdr):
    for path in ("/api/auth/me", "/api/users/me", "/api/me"):
        r = requests.get(f"{BASE_URL}{path}", headers=hdr, timeout=10)
        if r.status_code == 200:
            j = r.json()
            uid = j.get("id") or j.get("_id") or j.get("user_id")
            if uid:
                return uid
    pytest.fail("Could not fetch user id from any /me endpoint")


def _uq(db, uid):
    return {"id": uid} if db.users.find_one({"id": uid}) else {"_id": uid}


def _reset_user_hard(db, uid):
    """Wipe all tutorial state, resources, restore balance."""
    db.users.update_one(
        _uq(db, uid),
        {
            "$set": {
                "tutorial_active": False,
                "tutorial_completed": False,
                "resources": {},
                "balance_ton": 100.0,
            },
            "$unset": {
                "tutorial_snapshot": "",
                "tutorial_state": "",
                "tutorial_current_step": "",
                "tutorial_started_at": "",
                "tutorial_bonus_ton": "",
                "tutorial_t3_reward_granted": "",
                "tutorial_t3_reward_choice": "",
                "tutorial_t3_reward_granted_at": "",
                "tutorial_pending_t3_auto_activate": "",
                "tutorial_skipped": "",
                "tutorial_skipped_at": "",
                "tutorial_completed_at": "",
            },
        },
    )


@pytest.fixture(autouse=True)
def _clean_between(db, user_id):
    _reset_user_hard(db, user_id)
    yield
    _reset_user_hard(db, user_id)


def _get_resources(db, uid):
    doc = db.users.find_one(_uq(db, uid)) or {}
    return doc.get("resources") or {}


def _non_zero(resources):
    return {k: v for k, v in (resources or {}).items() if v}


# ---------- T1 happy path /finish ----------

def test_t1_happy_finish_only_reward_remains(db, hdr, user_id):
    # start
    r = requests.post(f"{BASE_URL}/api/tutorial/start", headers=hdr, timeout=10)
    assert r.status_code == 200, r.text

    # advance through: welcome, go_island, pick_ton_island, fake_buy_plot,
    # go_businesses, explain_idle (grants +50 biomass on the advance-OUT).
    for step in [
        "welcome", "go_island", "pick_ton_island",
        "fake_buy_plot", "go_businesses", "explain_idle",
    ]:
        r = requests.post(
            f"{BASE_URL}/api/tutorial/advance",
            json={"step_id": step},
            headers=hdr,
            timeout=10,
        )
        assert r.status_code == 200, f"advance {step} failed: {r.status_code} {r.text}"

    # sanity: biomass=50 now
    res_now = _get_resources(db, user_id)
    assert res_now.get("biomass") == 50, f"biomass grant missing: {res_now}"

    # advance out of go_trading_buy -> now on buy_lot
    r = requests.post(
        f"{BASE_URL}/api/tutorial/advance",
        json={"step_id": "go_trading_buy"},
        headers=hdr,
        timeout=10,
    )
    assert r.status_code == 200, r.text

    # buy-lot: +5 neuro_core
    r = requests.post(
        f"{BASE_URL}/api/tutorial/buy-lot",
        json={"amount": 5},
        headers=hdr,
        timeout=10,
    )
    assert r.status_code == 200, f"buy-lot failed: {r.status_code} {r.text}"
    res_now = _get_resources(db, user_id)
    assert res_now.get("biomass") == 50 and res_now.get("neuro_core") == 5, res_now

    # Skip forward directly to `finish` (steps between require creating a real
    # listing / navigating; irrelevant to the leak fix under test).
    db.users.update_one(_uq(db, user_id), {"$set": {"tutorial_current_step": "finish"}})

    # /finish with T3 choice neuro_core
    r = requests.post(
        f"{BASE_URL}/api/tutorial/finish",
        json={"t3_choice": "neuro_core"},
        headers=hdr,
        timeout=15,
    )
    assert r.status_code == 200, f"finish failed: {r.status_code} {r.text}"

    non_zero = _non_zero(_get_resources(db, user_id))
    assert non_zero == {"neuro_core_tutorial": 1}, f"leaked: {non_zero}"


# ---------- T2 /abandon ----------

def test_t2_abandon_zeros_granted_resources(db, hdr, user_id):
    requests.post(f"{BASE_URL}/api/tutorial/start", headers=hdr, timeout=10)
    for step in [
        "welcome", "go_island", "pick_ton_island",
        "fake_buy_plot", "go_businesses", "explain_idle",
    ]:
        rr = requests.post(
            f"{BASE_URL}/api/tutorial/advance",
            json={"step_id": step},
            headers=hdr,
            timeout=10,
        )
        assert rr.status_code == 200, rr.text
    assert _get_resources(db, user_id).get("biomass") == 50

    r = requests.post(f"{BASE_URL}/api/tutorial/abandon", headers=hdr, timeout=15)
    assert r.status_code == 200, r.text

    non_zero = _non_zero(_get_resources(db, user_id))
    assert non_zero == {}, f"abandon leaked: {non_zero}"


# ---------- T3 /reset ----------

def test_t3_reset_zeros_granted_resources(db, hdr, user_id):
    requests.post(f"{BASE_URL}/api/tutorial/start", headers=hdr, timeout=10)
    for step in [
        "welcome", "go_island", "pick_ton_island",
        "fake_buy_plot", "go_businesses", "explain_idle",
    ]:
        rr = requests.post(
            f"{BASE_URL}/api/tutorial/advance",
            json={"step_id": step},
            headers=hdr,
            timeout=10,
        )
        assert rr.status_code == 200, rr.text
    assert _get_resources(db, user_id).get("biomass") == 50

    r = requests.post(f"{BASE_URL}/api/tutorial/reset", headers=hdr, timeout=15)
    assert r.status_code == 200, r.text

    non_zero = _non_zero(_get_resources(db, user_id))
    assert non_zero == {}, f"reset leaked: {non_zero}"


# ---------- T4 corrupted snapshot fallback ----------

def test_t4_corrupted_snapshot_fallback_clawback(db, hdr, user_id):
    requests.post(f"{BASE_URL}/api/tutorial/start", headers=hdr, timeout=10)
    for step in [
        "welcome", "go_island", "pick_ton_island",
        "fake_buy_plot", "go_businesses", "explain_idle",
    ]:
        rr = requests.post(
            f"{BASE_URL}/api/tutorial/advance",
            json={"step_id": step},
            headers=hdr,
            timeout=10,
        )
        assert rr.status_code == 200, rr.text
    assert _get_resources(db, user_id).get("biomass") == 50

    # Corrupt: remove snapshot; granted_resources still has biomass:50
    db.users.update_one(_uq(db, user_id), {"$unset": {"tutorial_snapshot": ""}})

    # Skip to finish
    db.users.update_one(_uq(db, user_id), {"$set": {"tutorial_current_step": "finish"}})

    r = requests.post(
        f"{BASE_URL}/api/tutorial/finish",
        json={"t3_choice": "neuro_core"},
        headers=hdr,
        timeout=15,
    )
    assert r.status_code == 200, f"finish failed: {r.status_code} {r.text}"

    non_zero = _non_zero(_get_resources(db, user_id))
    assert non_zero == {"neuro_core_tutorial": 1}, f"clawback failed: {non_zero}"


# ---------- T5 /status self-heal ----------

def test_t5_status_self_heal(db, hdr, user_id):
    # Seed a stuck-leftover state
    db.users.update_one(
        _uq(db, user_id),
        {
            "$set": {
                "resources": {"biomass": 50},
                "tutorial_active": False,
                "tutorial_completed": True,
                "tutorial_state": {"granted_resources": {"biomass": 50}},
            }
        },
    )

    r = requests.get(f"{BASE_URL}/api/tutorial/status", headers=hdr, timeout=10)
    assert r.status_code == 200, r.text

    doc = db.users.find_one(_uq(db, user_id))
    res = doc.get("resources") or {}
    assert (res.get("biomass") or 0) == 0, f"self-heal did not zero biomass: {res}"
    tut_state = doc.get("tutorial_state") or {}
    assert not tut_state.get("granted_resources"), \
        f"granted_resources not purged: {tut_state}"


# ---------- T6 background auto-complete ----------

def test_t6_auto_complete_expired(db, user_id):
    from datetime import datetime, timezone, timedelta

    old_started = (datetime.now(timezone.utc) - timedelta(minutes=60)).isoformat()
    db.users.update_one(
        _uq(db, user_id),
        {
            "$set": {
                "tutorial_active": True,
                "tutorial_completed": False,
                "tutorial_current_step": "explain_idle",
                "tutorial_started_at": old_started,
                "tutorial_snapshot": {"resources": {}, "balance_ton": 100.0},
                "tutorial_state": {"granted_resources": {"biomass": 50}},
                "resources": {"biomass": 50},
            }
        },
    )

    # Run the async job directly against the same DB via motor.
    import sys
    sys.path.insert(0, "/app/backend")
    from motor.motor_asyncio import AsyncIOMotorClient
    from routes.tutorial import auto_complete_expired_tutorials

    async def _run():
        m = AsyncIOMotorClient(MONGO_URL)
        try:
            return await auto_complete_expired_tutorials(m[DB_NAME], timeout_minutes=0)
        finally:
            m.close()

    completed = asyncio.get_event_loop().run_until_complete(_run()) \
        if False else asyncio.new_event_loop().run_until_complete(_run())
    assert completed >= 1, f"no tutorials completed: {completed}"

    doc = db.users.find_one(_uq(db, user_id))
    res = doc.get("resources") or {}
    assert (res.get("biomass") or 0) == 0, f"auto-complete did not zero biomass: {res}"
    assert doc.get("tutorial_active") is False
    # Random T3 reward: exactly one _tutorial key should be present with value 1
    reward_keys = [k for k in res if k.endswith("_tutorial")]
    assert len(reward_keys) == 1 and res[reward_keys[0]] == 1, \
        f"expected exactly one T3 reward: {res}"


# ---------- T7 /mark-skipped leftover cleanup ----------

def test_t7_mark_skipped_cleans_leftover(db, hdr, user_id):
    db.users.update_one(
        _uq(db, user_id),
        {
            "$set": {
                "tutorial_active": False,
                "tutorial_completed": False,
                "tutorial_snapshot": {"resources": {}, "balance_ton": 100.0},
                "tutorial_state": {"granted_resources": {"biomass": 30}},
                "resources": {"biomass": 30},
            }
        },
    )

    r = requests.post(
        f"{BASE_URL}/api/tutorial/mark-skipped",
        json={"t3_choice": "gold_bill"},
        headers=hdr,
        timeout=15,
    )
    assert r.status_code == 200, f"mark-skipped failed: {r.status_code} {r.text}"

    res = _get_resources(db, user_id)
    assert (res.get("biomass") or 0) == 0, f"biomass leaked: {res}"
    assert res.get("gold_bill_tutorial") == 1, f"reward missing: {res}"
