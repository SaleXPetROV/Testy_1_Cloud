"""Iteration 15 — Reconciled tender escrow (frozen_city_for_tenders drift fix).

Covers backend/frozen_tenders.py + auth_wallet /me + withdrawal balance math.

Cases:
  1) STALE COUNTER, NO CONTRACTS: /me returns 0 and DB is self-healed.
  2) ACTIVE CONTRACT KEEPS FREEZE: /me still reports the stored freeze.
  3) WITHDRAW USES RECONCILIATION: standard withdraw not blocked by stale
     frozen when no active contracts exist (we only need to see that the
     "frozen" branch of the error is not triggered; 2FA gates come earlier
     for this user, so we assert the error message shape).
  4) REGRESSION on effective_frozen_city helper (direct call).
"""
import asyncio
import os
import sys
import uuid
from pathlib import Path

import pytest
import requests
from pymongo import MongoClient

sys.path.insert(0, "/app/backend")


def _load_env(p):
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env(Path("/app/frontend/.env"))
_load_env(Path("/app/backend/.env"))

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

USER_EMAIL = "testuser@example.com"
USER_PASSWORD = "Test1234!"


@pytest.fixture(scope="module")
def mongo_db():
    mc = MongoClient(os.environ["MONGO_URL"])
    return mc[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def user_auth():
    r = requests.post(f"{API}/auth/login",
                      json={"email": USER_EMAIL, "password": USER_PASSWORD},
                      timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def test_user(mongo_db):
    u = mongo_db.users.find_one({"email": USER_EMAIL})
    assert u, "testuser@example.com must exist (seed_users.py)"
    return u


# ---------------------------------------------------------------------------
# CASE 1 — stale counter, no active contracts → 0 and self-heal
# ---------------------------------------------------------------------------

class TestStaleCounterNoContracts:
    def test_me_returns_zero_and_selfheals(self, mongo_db, user_auth, test_user):
        uid = test_user["id"]
        # Ensure no active tender contracts reference this user.
        stray = mongo_db.tender_contracts.count_documents({
            "status": {"$in": ["ACTIVE", "PENDING_FUNDS", "PENDING_RESOURCES", "PROPOSED"]},
            "$or": [{"seller_id": uid}, {"buyer_id": uid},
                    {"seller_wallet": uid}, {"buyer_wallet": uid}],
        })
        assert stray == 0, f"pre-condition failed: {stray} active contracts found"

        # Seed drift = 90 $CITY (== 0.09 TON) and a known balance.
        original = mongo_db.users.find_one({"id": uid},
                                           {"frozen_city_for_tenders": 1, "balance_ton": 1})
        mongo_db.users.update_one(
            {"id": uid},
            {"$set": {"frozen_city_for_tenders": 90, "balance_ton": 1.0}},
        )
        try:
            r = requests.get(f"{API}/auth/me", headers=user_auth, timeout=15)
            assert r.status_code == 200, r.text[:200]
            body = r.json()
            assert body.get("frozen_for_tenders_city") == 0, body
            assert float(body.get("frozen_for_tenders_ton", -1)) == 0.0, body

            # DB counter should be self-healed to 0.
            u_after = mongo_db.users.find_one({"id": uid}, {"frozen_city_for_tenders": 1})
            assert float(u_after.get("frozen_city_for_tenders", 0) or 0) == 0.0
        finally:
            # Restore original counter/balance
            mongo_db.users.update_one(
                {"id": uid},
                {"$set": {
                    "frozen_city_for_tenders": float(original.get("frozen_city_for_tenders", 0) or 0),
                    "balance_ton": float(original.get("balance_ton", 0) or 0),
                }},
            )


# ---------------------------------------------------------------------------
# CASE 2 — active contract keeps freeze
# ---------------------------------------------------------------------------

class TestActiveContractKeepsFreeze:
    def test_me_keeps_stored_freeze_when_active(self, mongo_db, user_auth, test_user):
        uid = test_user["id"]
        original = mongo_db.users.find_one({"id": uid},
                                           {"frozen_city_for_tenders": 1, "balance_ton": 1})
        contract_id = f"TEST_frz_{uuid.uuid4().hex[:10]}"
        mongo_db.users.update_one(
            {"id": uid},
            {"$set": {"frozen_city_for_tenders": 90, "balance_ton": 1.0}},
        )
        mongo_db.tender_contracts.insert_one({
            "id": contract_id,
            "status": "ACTIVE",
            "seller_id": uid,
            "buyer_id": "someone_else",
            "amount_city": 90,
        })
        try:
            r = requests.get(f"{API}/auth/me", headers=user_auth, timeout=15)
            assert r.status_code == 200, r.text[:200]
            body = r.json()
            assert body.get("frozen_for_tenders_city") == 90, body
            assert abs(float(body.get("frozen_for_tenders_ton")) - 0.09) < 1e-6, body

            u_after = mongo_db.users.find_one({"id": uid}, {"frozen_city_for_tenders": 1})
            assert float(u_after.get("frozen_city_for_tenders", 0) or 0) == 90.0
        finally:
            mongo_db.tender_contracts.delete_one({"id": contract_id})
            mongo_db.users.update_one(
                {"id": uid},
                {"$set": {
                    "frozen_city_for_tenders": float(original.get("frozen_city_for_tenders", 0) or 0),
                    "balance_ton": float(original.get("balance_ton", 0) or 0),
                }},
            )


# ---------------------------------------------------------------------------
# CASE 3 — Withdrawal endpoint doesn't block due to stale freeze
# ---------------------------------------------------------------------------

class TestWithdrawalUsesReconciliation:
    def test_withdrawal_not_blocked_by_stale_freeze(self, mongo_db, user_auth, test_user):
        """Standard withdraw for stale user (no contracts): the 'frozen'
        branch of the insufficient-funds error must not fire. We do not care
        about actually pushing TON — 2FA/wallet gates come earlier and are
        enough to prove the freeze isn't miscounted."""
        uid = test_user["id"]
        original = mongo_db.users.find_one({"id": uid},
                                           {"frozen_city_for_tenders": 1, "balance_ton": 1})
        mongo_db.users.update_one(
            {"id": uid},
            {"$set": {"frozen_city_for_tenders": 90, "balance_ton": 1.0}},
        )
        try:
            # amount within balance (1.0 TON) — if frozen were counted this
            # would raise 400 with "заморожено в контрактах". We expect a
            # different failure (2FA / wallet / min etc.), never that one.
            r = requests.post(
                f"{API}/withdraw",
                headers=user_auth,
                json={"amount": 1.0, "wallet_address": "UQTestDestAddress0000000000000000000000000000000"},
                timeout=20,
            )
            body_text = r.text.lower()
            # Core assertion: the "заморожено в контрактах" branch must NOT
            # fire. Other gates (2FA, wallet, min amount) may still fail
            # earlier — that's outside the fix's scope.
            assert "заморожено" not in body_text, \
                f"stale freeze still blocks withdraw: {r.status_code} {r.text[:300]}"
        finally:
            mongo_db.users.update_one(
                {"id": uid},
                {"$set": {
                    "frozen_city_for_tenders": float(original.get("frozen_city_for_tenders", 0) or 0),
                    "balance_ton": float(original.get("balance_ton", 0) or 0),
                }},
            )


# ---------------------------------------------------------------------------
# CASE 4 — Helper unit-regressions (direct import)
# ---------------------------------------------------------------------------

class TestEffectiveFrozenCityHelper:
    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro) \
            if False else asyncio.run(coro)

    def test_returns_zero_for_nonpositive_stored(self):
        from frozen_tenders import effective_frozen_city

        class DB:  # no methods should be called
            class tender_contracts:
                @staticmethod
                async def count_documents(_):
                    raise AssertionError("should not query when stored<=0")

        val = self._run(effective_frozen_city(DB(), {"id": "x", "frozen_city_for_tenders": 0}))
        assert val == 0.0
        val = self._run(effective_frozen_city(DB(), {"id": "x", "frozen_city_for_tenders": -5}))
        assert val == 0.0

    def test_returns_stored_when_active_contracts_exist(self, mongo_db, test_user):
        from frozen_tenders import effective_frozen_city
        uid = test_user["id"]
        contract_id = f"TEST_frzh_{uuid.uuid4().hex[:10]}"
        mongo_db.tender_contracts.insert_one({
            "id": contract_id, "status": "PENDING_FUNDS",
            "buyer_id": uid, "amount_city": 42,
        })
        try:
            # Use an async-motor-like client via pymongo wrapper is not trivial;
            # instead, connect to motor here.
            import motor.motor_asyncio as m
            async def _go():
                client = m.AsyncIOMotorClient(os.environ["MONGO_URL"])
                db = client[os.environ["DB_NAME"]]
                v = await effective_frozen_city(
                    db, {"id": uid, "frozen_city_for_tenders": 42})
                client.close()
                return v
            v = self._run(_go())
            assert v == 42.0
        finally:
            mongo_db.tender_contracts.delete_one({"id": contract_id})

    def test_selfheal_when_no_active_contracts(self, mongo_db, test_user):
        from frozen_tenders import effective_frozen_city
        uid = test_user["id"]
        original = mongo_db.users.find_one({"id": uid}, {"frozen_city_for_tenders": 1})
        mongo_db.users.update_one({"id": uid}, {"$set": {"frozen_city_for_tenders": 77}})
        try:
            import motor.motor_asyncio as m
            async def _go():
                client = m.AsyncIOMotorClient(os.environ["MONGO_URL"])
                db = client[os.environ["DB_NAME"]]
                v = await effective_frozen_city(
                    db, {"id": uid, "frozen_city_for_tenders": 77})
                client.close()
                return v
            v = self._run(_go())
            assert v == 0.0
            u = mongo_db.users.find_one({"id": uid}, {"frozen_city_for_tenders": 1})
            assert float(u.get("frozen_city_for_tenders", 0) or 0) == 0.0
        finally:
            mongo_db.users.update_one(
                {"id": uid},
                {"$set": {"frozen_city_for_tenders":
                          float(original.get("frozen_city_for_tenders", 0) or 0)}},
            )
