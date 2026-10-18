"""Integration tests for TON_CITY v2.3 bug fixes (iteration 13).

Covers:
  • TASK 2 — TON Connect icon endpoint + dynamic manifest (v3/v4/v5) serve the
    favicon-512 PNG (~177 KB) and reference it via /api/tonconnect-icon.png.
  • TASK 3 — GET /api/admin/settings/withdrawal-wallet uses
    get_contract_deployer(db).get_wallet_balance (toncenter getAddressBalance),
    returns {configured, address, balance} and does not fail when unconfigured.
  • TASK 3 — POST /api/admin/withdrawal/reject/{tx_id} refunds amount_ton to
    user's balance_ton on a pending withdrawal; second reject → 400.
"""
import os
import uuid
import hashlib
import requests
import pytest
from pathlib import Path
from pymongo import MongoClient


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
FAVICON_PATH = "/app/backend/static/tonconnect-icon-favicon.png"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{API}/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                      timeout=15)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text[:200]}"
    data = r.json()
    tok = data.get("token") or data.get("access_token")
    assert tok, f"no token in login response: {data}"
    return tok


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="module")
def mongo_db():
    mc = MongoClient(os.environ["MONGO_URL"])
    return mc[os.environ["DB_NAME"]]


# ---------- TASK 2: TON Connect icon + manifests ----------

class TestTonConnectIconAndManifest:
    def test_icon_endpoint_serves_favicon_512(self):
        r = requests.get(f"{API}/tonconnect-icon.png", timeout=15)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("image/png")
        # size must match the favicon_512 RGB file (177242 bytes)
        with open(FAVICON_PATH, "rb") as f:
            expected = f.read()
        assert len(r.content) == len(expected), \
            f"icon size mismatch: got {len(r.content)}, expected {len(expected)}"
        assert hashlib.sha256(r.content).hexdigest() == hashlib.sha256(expected).hexdigest()

    @pytest.mark.parametrize("path", [
        "/tonconnect-manifest.json",
        "/tonconnect-manifest-v2.json",
        "/tonconnect-manifest-v3.json",
        "/tonconnect-manifest-v4.json",
        "/tonconnect-manifest-v5.json",
    ])
    def test_manifest_versions_dynamic(self, path):
        r = requests.get(f"{API}{path}", timeout=15)
        assert r.status_code == 200, f"{path} → {r.status_code}"
        data = r.json()
        assert data.get("name") == "GRAM CITY"
        icon_url = data.get("iconUrl", "")
        assert icon_url.endswith("/api/tonconnect-icon.png"), icon_url
        assert "url" in data

    def test_all_manifest_versions_identical(self):
        payloads = []
        for v in ["", "-v2", "-v3", "-v4", "-v5"]:
            r = requests.get(f"{API}/tonconnect-manifest{v}.json", timeout=15)
            assert r.status_code == 200
            payloads.append(r.json())
        for p in payloads[1:]:
            assert p == payloads[0], "all manifest versions must serve identical dynamic payload"


# ---------- TASK 3: withdrawal-wallet balance endpoint ----------

class TestWithdrawalWalletEndpoint:
    def test_requires_admin(self):
        r = requests.get(f"{API}/admin/settings/withdrawal-wallet", timeout=15)
        assert r.status_code in (401, 403)

    def test_returns_shape_when_configured_or_not(self, admin_headers):
        r = requests.get(f"{API}/admin/settings/withdrawal-wallet",
                         headers=admin_headers, timeout=20)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert "configured" in data
        assert "address" in data
        assert "balance" in data
        assert isinstance(data["balance"], (int, float))

        if not data["configured"]:
            # Unconfigured branch must not crash and returns 0
            assert data["balance"] == 0
            assert data["address"] in (None, "")
        else:
            # Balance must be a non-negative number (from getAddressBalance)
            assert data["balance"] >= 0

    def test_balance_matches_toncenter_getaddressbalance(self, admin_headers):
        """When a wallet address is configured, the endpoint's balance value
        must match a direct toncenter getAddressBalance call (the SAME endpoint
        the deployer card uses)."""
        r = requests.get(f"{API}/admin/settings/withdrawal-wallet",
                         headers=admin_headers, timeout=20)
        assert r.status_code == 200
        data = r.json()
        addr = data.get("address")
        if not addr:
            pytest.skip("withdrawal wallet not configured in this environment")

        # Direct toncenter call for cross-check
        tc = requests.get("https://toncenter.com/api/v2/getAddressBalance",
                         params={"address": addr}, timeout=20)
        if tc.status_code != 200:
            pytest.skip(f"toncenter unavailable: {tc.status_code}")
        j = tc.json()
        if not j.get("ok"):
            pytest.skip(f"toncenter not ok: {j}")
        direct_ton = int(j.get("result", 0)) / 1e9
        # Allow small delta because balance can shift between the two calls.
        assert abs(data["balance"] - round(direct_ton, 4)) < 0.5, \
            f"endpoint balance {data['balance']} vs toncenter {direct_ton}"


# ---------- TASK 3: reject regression (refund + idempotency) ----------

class TestWithdrawalRejectRefund:
    def test_reject_refunds_and_double_reject_400(self, admin_headers, mongo_db):
        # Seed a TEST user with 0 balance and a pending withdrawal tx
        user_id = f"TEST_wd_user_{uuid.uuid4().hex[:8]}"
        wallet = f"UQ_TEST_{uuid.uuid4().hex[:20]}"
        mongo_db.users.insert_one({
            "id": user_id,
            "email": f"TEST_{user_id}@example.com",
            "wallet_address": wallet,
            "balance_ton": 0.0,
        })
        tx_id = f"TEST_tx_{uuid.uuid4().hex[:10]}"
        amount = 3.5
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
            assert abs(float(u["balance_ton"]) - amount) < 1e-6, \
                f"balance not refunded: {u['balance_ton']} vs {amount}"

            t = mongo_db.transactions.find_one({"id": tx_id})
            assert t["status"] == "rejected"

            # Second reject must fail
            r2 = requests.post(f"{API}/admin/withdrawal/reject/{tx_id}",
                               headers=admin_headers, timeout=20)
            assert r2.status_code == 400, f"second reject should be 400, got {r2.status_code}"
        finally:
            mongo_db.users.delete_one({"id": user_id})
            mongo_db.transactions.delete_one({"id": tx_id})
