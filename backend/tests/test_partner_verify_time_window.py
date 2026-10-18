"""
Partner verify time-window tests (partner_joined_at cutoff).

Scenarios:
  A) old purchases before join must NOT count (402), new ones after join DO count (200)
  B) backfill cutoff: attributed user w/o partner_joined_at → verify anchors it to NOW,
     old purchases excluded => 402
  Regression) referral attribution via new-style fields + start_param, and negative case.
"""
import os
import uuid
import asyncio
from datetime import datetime, timezone, timedelta

import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
def db():
    client = AsyncIOMotorClient(MONGO_URL)
    return client[DB_NAME]


@pytest.fixture(scope="module")
def admin_id(db, event_loop):
    async def _load():
        u = await db.users.find_one({"email": "sanyanazarov212@gmail.com"}, {"_id": 0, "id": 1})
        if not u:
            u = await db.users.find_one({"is_admin": True}, {"_id": 0, "id": 1})
        return u["id"] if u else None

    aid = event_loop.run_until_complete(_load())
    if not aid:
        pytest.skip("Admin user not found")
    return aid


TEST_PREFIX = f"TEST_{uuid.uuid4().hex[:8]}_"


@pytest.fixture(scope="module")
def program(db, event_loop, admin_id):
    api_key = TEST_PREFIX + "key"
    pid = TEST_PREFIX + "prog"
    doc = {
        "id": pid,
        "name": TEST_PREFIX + "prog",
        "api_key": api_key,
        "referrer_user_id": admin_id,
        "active": True,
        "require_land": True,
        "min_market_spend_city": 1000.0,
        "per_active_user_city": 0,
        "income_percent": 0,
        "created_at": _iso(datetime.now(timezone.utc)),
    }
    event_loop.run_until_complete(db.partner_programs.insert_one(doc))
    yield doc

    async def _cleanup():
        await db.partner_programs.delete_many({"id": {"$regex": f"^{TEST_PREFIX}"}})
        await db.users.delete_many({"id": {"$regex": f"^{TEST_PREFIX}"}})
        await db.transactions.delete_many({"buyer_id": {"$regex": f"^{TEST_PREFIX}"}})
        await db.transactions.delete_many({"user_id": {"$regex": f"^{TEST_PREFIX}"}})
        await db.partner_verify_logs.delete_many({"api_key": {"$regex": f"^{TEST_PREFIX}"}})
        await db.partner_program_progress.delete_many({"program_id": {"$regex": f"^{TEST_PREFIX}"}})

    event_loop.run_until_complete(_cleanup())


def _verify(api_key, user_id):
    return requests.get(f"{BASE_URL}/api/partner/verify/{api_key}", params={"user_id": user_id}, timeout=15)


# ---------- Scenario A ----------
def test_scenario_A_old_history_excluded_then_new_counted(db, event_loop, admin_id, program):
    uid = TEST_PREFIX + "userA"
    join_at = datetime.now(timezone.utc)
    old_at = join_at - timedelta(days=5)

    async def setup():
        await db.users.insert_one({
            "id": uid,
            "username": uid,
            "partner_ref_id": admin_id,
            "partner_is_new": False,
            "partner_joined_at": _iso(join_at),
            "created_at": _iso(old_at),
        })
        # OLD txs BEFORE join
        await db.transactions.insert_many([
            {"id": TEST_PREFIX + "ot1", "tx_type": "purchase_plot", "buyer_id": uid,
             "status": "completed", "created_at": _iso(old_at)},
            {"id": TEST_PREFIX + "ot2", "tx_type": "purchase_plot", "buyer_id": uid,
             "status": "completed", "created_at": _iso(old_at)},
            {"id": TEST_PREFIX + "ot3", "tx_type": "market_purchase", "buyer_id": uid,
             "amount_ton": 2.0, "created_at": _iso(old_at)},
        ])
    event_loop.run_until_complete(setup())

    r = _verify(program["api_key"], uid)
    assert r.status_code == 402, r.text
    data = r.json()
    assert data["checks"]["referral"]["ok"] is True
    assert data["checks"]["land"]["count"] == 0, data
    assert data["checks"]["market"]["spent_city"] == 0.0, data
    assert "land" in data["missing"] and "market" in data["missing"]

    # Now add NEW txs AFTER join
    new_at = join_at + timedelta(minutes=1)

    async def add_new():
        await db.transactions.insert_many([
            {"id": TEST_PREFIX + "nt1", "tx_type": "purchase_plot", "buyer_id": uid,
             "status": "completed", "created_at": _iso(new_at)},
            {"id": TEST_PREFIX + "nt2", "tx_type": "market_purchase", "buyer_id": uid,
             "amount_ton": 1.5, "created_at": _iso(new_at)},
        ])
    event_loop.run_until_complete(add_new())

    r2 = _verify(program["api_key"], uid)
    assert r2.status_code == 200, r2.text
    d2 = r2.json()
    assert d2["status"] == "completed"
    assert d2["checks"]["land"]["count"] == 1, d2
    assert d2["checks"]["market"]["spent_city"] == 1500.0, d2


# ---------- Scenario B: backfill cutoff ----------
def test_scenario_B_backfill_cutoff_on_first_verify(db, event_loop, admin_id, program):
    uid = TEST_PREFIX + "userB"
    old_at = datetime.now(timezone.utc) - timedelta(days=10)

    async def setup():
        # Attributed via new-style fields; NO partner_joined_at
        await db.users.insert_one({
            "id": uid, "username": uid,
            "referrer_id": admin_id,
            "ref_by": admin_id,
            "invited_by": admin_id,
            "partner_ref_id": admin_id,
            "created_at": _iso(old_at),
        })
        await db.transactions.insert_many([
            {"id": TEST_PREFIX + "bt1", "tx_type": "purchase_plot", "buyer_id": uid,
             "status": "completed", "created_at": _iso(old_at)},
            {"id": TEST_PREFIX + "bt2", "tx_type": "market_purchase", "buyer_id": uid,
             "amount_ton": 2.0, "created_at": _iso(old_at)},
        ])
    event_loop.run_until_complete(setup())

    r = _verify(program["api_key"], uid)
    assert r.status_code == 402, r.text
    data = r.json()
    assert data["checks"]["referral"]["ok"] is True
    assert data["checks"]["land"]["count"] == 0, data
    assert data["checks"]["market"]["spent_city"] == 0.0, data

    # Confirm cutoff was backfilled onto user doc
    async def _read():
        return await db.users.find_one({"id": uid}, {"_id": 0, "partner_joined_at": 1})
    u = event_loop.run_until_complete(_read())
    assert u.get("partner_joined_at"), "partner_joined_at should be backfilled on first verify"


# ---------- Regression: attribution via various referral fields ----------
@pytest.mark.parametrize("field", ["partner_ref_id", "referrer_id", "ref_by", "invited_by", "start_param"])
def test_regression_referral_attribution_fields(db, event_loop, admin_id, program, field):
    uid = TEST_PREFIX + f"reg_{field}"

    async def setup():
        # user with only ONE referral field set (+ future partner_joined_at so old txs still excluded, but no txs anyway)
        doc = {"id": uid, "username": uid, field: admin_id,
               "partner_joined_at": _iso(datetime.now(timezone.utc)),
               "created_at": _iso(datetime.now(timezone.utc))}
        await db.users.insert_one(doc)
    event_loop.run_until_complete(setup())

    r = _verify(program["api_key"], uid)
    # 402 expected since no purchases; but referral MUST be ok
    assert r.status_code == 402, r.text
    data = r.json()
    assert data["checks"]["referral"]["ok"] is True, f"field {field}: {data}"


def test_regression_unrelated_referrer_fails_attribution(db, event_loop, program):
    uid = TEST_PREFIX + "unrelated"

    async def setup():
        await db.users.insert_one({"id": uid, "username": uid,
                                    "partner_ref_id": "some-other-referrer-xyz",
                                    "created_at": _iso(datetime.now(timezone.utc))})
    event_loop.run_until_complete(setup())

    r = _verify(program["api_key"], uid)
    assert r.status_code == 402
    data = r.json()
    assert data["checks"]["referral"]["ok"] is False
    assert "referral" in data.get("missing", [])
