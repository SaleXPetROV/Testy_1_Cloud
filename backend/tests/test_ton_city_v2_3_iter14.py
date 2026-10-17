"""Iteration 14 tests for TON_CITY v2.3.

Covers two new fixes on top of iter13:
  1) ton_integration.send_ton_payout normalises TONCENTER_API_ENDPOINT by
     stripping a trailing "/jsonRPC" (or lowercased variants) so REST calls
     like getAddressBalance / getWalletInformation / sendBoc land on the
     correct URLs even when the .env value is set to the JSON-RPC form
     (which happens on prod).
  2) admin_approve_withdrawal refunds the user via an OR-match on
     {id, wallet_address, raw_address} when send_ton_payout raises, and
     marks the transaction 'failed' (HTTP 502 to caller).
"""
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

import pytest
import requests
from pymongo import MongoClient

sys.path.insert(0, "/app/backend")


def _load_env_file(p):
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env_file(Path("/app/frontend/.env"))
_load_env_file(Path("/app/backend/.env"))

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def admin_headers():
    r = requests.post(f"{API}/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                      timeout=15)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text[:200]}"
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def mongo_db():
    mc = MongoClient(os.environ["MONGO_URL"])
    return mc[os.environ["DB_NAME"]]


# ---------------------------------------------------------------------------
# Fake toncenter httpx client (records every URL for URL-shape assertions)
# ---------------------------------------------------------------------------

class _FakeResp:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._d = data or {}
        self.text = json.dumps(self._d)

    def json(self):
        return self._d


class _FakeClient:
    """Records every URL passed to GET/POST; balance queue is round-robin."""
    calls = []  # class-level so the test can inspect after context exits

    def __init__(self, *a, **kw):
        self._addr_idx = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None, headers=None):
        _FakeClient.calls.append(("GET", url, params))
        if "getAddressBalance" in url:
            # V4R2 has enough for 1 TON + 0.01 gas
            balances = [str(int(12 * 1e9)), str(int(0 * 1e9))]
            v = balances[self._addr_idx] if self._addr_idx < len(balances) else balances[-1]
            self._addr_idx += 1
            return _FakeResp(200, {"ok": True, "result": v})
        if "getWalletInformation" in url:
            return _FakeResp(200, {"ok": True, "result": {"seqno": 0}})
        return _FakeResp(404, {"ok": False})

    async def post(self, url, json=None, headers=None):
        _FakeClient.calls.append(("POST", url, json))
        if "sendBoc" in url:
            return _FakeResp(200, {"ok": True, "result": {"hash": "iter14_hash"}})
        return _FakeResp(404, {"ok": False})


# 24-word test mnemonic (valid tonsdk vector)
TEST_MNEMONIC = (
    "abandon abandon abandon abandon abandon abandon "
    "abandon abandon abandon abandon abandon abandon "
    "abandon abandon abandon abandon abandon abandon "
    "abandon abandon abandon abandon abandon art"
)


def _derive_dest():
    from tonsdk.crypto import mnemonic_to_wallet_key
    from tonsdk.contract.wallet import WalletV3ContractR2
    pub, priv = mnemonic_to_wallet_key(TEST_MNEMONIC.split())
    w = WalletV3ContractR2(public_key=pub, private_key=priv, workchain=0)
    return w.address.to_string(True, True, False)


DEST_ADDR = _derive_dest()


# ---------------------------------------------------------------------------
# TASK 1 — endpoint normalisation
# ---------------------------------------------------------------------------

class TestEndpointNormalisation:
    def _run(self, endpoint_value, monkeypatch):
        import ton_integration
        _FakeClient.calls = []
        monkeypatch.setenv("TONCENTER_API_ENDPOINT", endpoint_value)
        monkeypatch.setattr(ton_integration.httpx, "AsyncClient", _FakeClient)
        client = ton_integration.TONClient()
        tx_hash = asyncio.run(client.send_ton_payout(
            dest_address=DEST_ADDR,
            amount_ton=1.0,
            mnemonics=TEST_MNEMONIC,
            user_username="iter14",
        ))
        return tx_hash, list(_FakeClient.calls)

    def test_jsonrpc_suffix_is_stripped(self, monkeypatch):
        tx_hash, calls = self._run(
            "https://toncenter.com/api/v2/jsonRPC", monkeypatch)
        assert tx_hash, "send_ton_payout should succeed and return a hash"
        urls = [c[1] for c in calls]
        # No call should contain /jsonRPC/ (bad concatenation)
        for u in urls:
            assert "/jsonRPC/" not in u and "/jsonrpc/" not in u, f"bad URL: {u}"
        joined = " ".join(urls)
        assert "/api/v2/getAddressBalance" in joined, urls
        assert "/api/v2/getWalletInformation" in joined, urls
        assert "/api/v2/sendBoc" in joined, urls

    def test_lowercase_jsonrpc_suffix_is_stripped(self, monkeypatch):
        tx_hash, calls = self._run(
            "https://toncenter.com/api/v2/jsonrpc", monkeypatch)
        assert tx_hash
        for _, u, _ in calls:
            assert "/jsonrpc/" not in u.lower(), u

    def test_plain_endpoint_still_works(self, monkeypatch):
        tx_hash, calls = self._run(
            "https://toncenter.com/api/v2", monkeypatch)
        assert tx_hash
        joined = " ".join(c[1] for c in calls)
        assert "/api/v2/getAddressBalance" in joined
        assert "/api/v2/sendBoc" in joined


# ---------------------------------------------------------------------------
# TASK 2 — approve failure refunds via OR-match
# ---------------------------------------------------------------------------

class TestApproveRefundOnFailure:
    def test_refund_via_or_match_and_tx_failed(self, admin_headers, mongo_db):
        # Seed TEST user with a starting balance and an intentionally MISMATCHED
        # user_wallet on the transaction (uppercased) so a naive
        # {wallet_address: user_wallet} lookup would miss and the OR-match
        # (via {id}) is what actually saves the refund.
        user_id = f"TEST_appr_{uuid.uuid4().hex[:8]}"
        wallet = f"UQ_test_{uuid.uuid4().hex[:18]}"
        raw = f"0:{uuid.uuid4().hex}"
        starting_balance = 0.25
        mongo_db.users.insert_one({
            "id": user_id,
            "email": f"TEST_{user_id}@example.com",
            "wallet_address": wallet,
            "raw_address": raw,
            "balance_ton": starting_balance,
        })

        tx_id = f"TEST_txa_{uuid.uuid4().hex[:10]}"
        amount = 2.75
        # Store a wallet variant that differs in case so the direct
        # {wallet_address: user_wallet} equality is not the one that finds
        # the user — the OR-match by id is what must fire.
        mongo_db.transactions.insert_one({
            "id": tx_id,
            "user_id": user_id,
            "user_wallet": wallet.upper(),   # mismatched on purpose
            "amount_ton": amount,
            "net_amount": amount - 0.05,
            "commission": 0.05,
            "status": "pending",
            "type": "withdrawal",
        })

        # Ensure a withdrawal wallet is configured so admin_approve_withdrawal
        # actually reaches send_ton_payout; use a bogus 24-word mnemonic that
        # will crash inside ton_integration (invalid checksum → exception),
        # producing the failure branch we want to test.
        # To avoid clobbering prod config, we use admin_settings snapshot.
        original_ws = mongo_db.admin_settings.find_one({"type": "withdrawal_wallet"})
        from mnemonic_crypto import encrypt_mnemonic
        bogus_seed = "bogus mnemonic that will not decode properly at all here " * 2
        try:
            mongo_db.admin_settings.update_one(
                {"type": "withdrawal_wallet"},
                {"$set": {
                    "type": "withdrawal_wallet",
                    "mnemonic": encrypt_mnemonic(bogus_seed),
                    "address": "UQ_bogus_for_TEST",
                }},
                upsert=True,
            )

            r = requests.post(f"{API}/admin/withdrawal/approve/{tx_id}",
                              headers=admin_headers, timeout=30)
            # The failure branch must return 502 (network/TON error) rather
            # than 500 (unhandled).
            assert r.status_code == 502, f"expected 502 got {r.status_code}: {r.text[:300]}"

            # Refund must have landed on the user via OR-match on {id}
            u = mongo_db.users.find_one({"id": user_id})
            assert u is not None
            assert abs(float(u["balance_ton"]) - (starting_balance + amount)) < 1e-6, \
                f"balance not refunded: {u['balance_ton']} vs {starting_balance + amount}"

            # Transaction must be marked 'failed'
            t = mongo_db.transactions.find_one({"id": tx_id})
            assert t["status"] == "failed", t.get("status")
            assert "error" in t

        finally:
            # Restore withdrawal_wallet setting
            if original_ws is not None:
                original_ws.pop("_id", None)
                mongo_db.admin_settings.replace_one(
                    {"type": "withdrawal_wallet"}, original_ws, upsert=True)
            else:
                mongo_db.admin_settings.delete_one({"type": "withdrawal_wallet"})
            mongo_db.users.delete_one({"id": user_id})
            mongo_db.transactions.delete_one({"id": tx_id})


# ---------------------------------------------------------------------------
# TASK 3 — reject regression (still refunds, second reject → 400)
# ---------------------------------------------------------------------------

class TestRejectRegression:
    def test_reject_refunds_and_double_reject_400(self, admin_headers, mongo_db):
        user_id = f"TEST_rej_{uuid.uuid4().hex[:8]}"
        wallet = f"UQ_TEST_{uuid.uuid4().hex[:20]}"
        mongo_db.users.insert_one({
            "id": user_id,
            "email": f"TEST_{user_id}@example.com",
            "wallet_address": wallet,
            "balance_ton": 0.0,
        })
        tx_id = f"TEST_txr_{uuid.uuid4().hex[:10]}"
        amount = 1.5
        mongo_db.transactions.insert_one({
            "id": tx_id,
            "user_id": user_id,
            "user_wallet": wallet,
            "amount_ton": amount,
            "net_amount": amount - 0.05,
            "commission": 0.05,
            "status": "pending",
            "type": "withdrawal",
        })
        try:
            r = requests.post(f"{API}/admin/withdrawal/reject/{tx_id}",
                              headers=admin_headers, timeout=20)
            assert r.status_code == 200, r.text[:300]

            u = mongo_db.users.find_one({"id": user_id})
            assert abs(float(u["balance_ton"]) - amount) < 1e-6

            t = mongo_db.transactions.find_one({"id": tx_id})
            assert t["status"] == "rejected"

            r2 = requests.post(f"{API}/admin/withdrawal/reject/{tx_id}",
                               headers=admin_headers, timeout=20)
            assert r2.status_code == 400
        finally:
            mongo_db.users.delete_one({"id": user_id})
            mongo_db.transactions.delete_one({"id": tx_id})


# ---------------------------------------------------------------------------
# TASK 4 — regression: tonconnect icon + manifest still work
# ---------------------------------------------------------------------------

class TestTonConnectRegression:
    def test_icon_endpoint(self):
        r = requests.get(f"{API}/tonconnect-icon.png", timeout=15)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("image/png")
        assert len(r.content) == 177242, len(r.content)

    @pytest.mark.parametrize("v", ["-v3", "-v4", "-v5"])
    def test_manifest_versions_icon_url(self, v):
        r = requests.get(f"{API}/tonconnect-manifest{v}.json", timeout=15)
        assert r.status_code == 200
        assert r.json().get("iconUrl", "").endswith("/api/tonconnect-icon.png")

    def test_withdrawal_wallet_settings_endpoint(self, admin_headers):
        r = requests.get(f"{API}/admin/settings/withdrawal-wallet",
                         headers=admin_headers, timeout=20)
        assert r.status_code == 200
        d = r.json()
        assert "configured" in d and "address" in d and "balance" in d
