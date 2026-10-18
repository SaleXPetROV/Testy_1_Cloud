"""
Backend tests for TON_CITY_v2.3 wallet-auth bug-fix round.

NOTE: Run with `-n 0` (serial). These tests share DB state (seeded testuser +
admin + TEST/FREE wallets) and the login endpoint rotates sessions per user
(one active session per user) — running two workers logs in the same user
concurrently and the older token gets invalidated (401 session_invalidated).


Covered:
    - Email/password login for seeded testuser and admin
    - /api/auth/verify-wallet flow:
        * unknown wallet + no username → status=need_username, no user created
        * unknown wallet + username → status=ok, is_new_user=true
        * same wallet, NO username → status=ok, is_new_user=false (re-login owner)
        * same wallet via RAW form → same user, is_new_user=false
    - /api/auth/link-wallet:
        * REJECTS a wallet already owned by another account (400) —
          testuser's wallet_address MUST remain None
        * SUCCEEDS for a free wallet
    - /api/auth/unlink-wallet frees the wallet
    - After unlink, the freed wallet is linkable by another account (admin)
    - Uniqueness invariant: no two users share wallet_address / raw_address
      after full flow
"""
import os
import uuid
import base64
import hashlib
import struct
import time
import pytest
import requests
from pymongo import MongoClient
from nacl.signing import SigningKey
from pytoniq_core import Address, begin_cell

BASE_URL = os.environ.get("BACKEND_URL", "http://localhost:8001").rstrip("/")

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PASSWORD = "Test1234!"

# Canonical test wallet (from problem statement)
TEST_WALLET_UF = "UQCD39VS5jcptHL8vMjEXrzGaRcCgX2bgbHm3i-wPB5SczbU"
TEST_WALLET_RAW = "0:83dfd552e63729b472fcbcc8c45ebcc6691702817d9b81b1e6de2fb03c1e5273"

# Second test wallet — free, not owned by anyone before test
FREE_WALLET_RAW = "0:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
FREE_WALLET_UF = "UQCqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqppe"


# ------------------------- fixtures / helpers -------------------------

@pytest.fixture(scope="session")
def mongo_db():
    """Direct Mongo handle for cleanup + invariant checks."""
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "ton_city")
    # Fall back to reading backend/.env if env vars aren't set in test proc
    if not mongo_url or not db_name or db_name == "ton_city":
        env_path = "/app/backend/.env"
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    if line.startswith("MONGO_URL=") and not os.environ.get("MONGO_URL"):
                        mongo_url = line.split("=", 1)[1].strip()
                    elif line.startswith("DB_NAME="):
                        db_name = line.split("=", 1)[1].strip()
    client = MongoClient(mongo_url)
    return client[db_name]


@pytest.fixture(scope="session", autouse=True)
def clean_state(mongo_db):
    """Before + after the test session: remove any wallet_address/raw_address
    from seeded users and delete accounts created by the wallet flow so the
    tests are idempotent."""
    def _cleanup():
        # Delete wallet-only accounts spun up by verify-wallet during tests
        mongo_db.users.delete_many({
            "$or": [
                {"raw_address": TEST_WALLET_RAW},
                {"wallet_address": TEST_WALLET_UF},
                {"raw_address": FREE_WALLET_RAW},
                {"wallet_address": FREE_WALLET_UF},
            ],
            "email": {"$nin": [ADMIN_EMAIL, USER_EMAIL]},
        })
        # Unlink any wallet on seeded users
        mongo_db.users.update_many(
            {"email": {"$in": [ADMIN_EMAIL, USER_EMAIL]}},
            {"$unset": {"wallet_address": "", "raw_address": ""}}
        )

    _cleanup()
    yield
    _cleanup()


def _login(email: str, password: str) -> dict:
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        timeout=15,
    )
    assert r.status_code == 200, f"login({email}) failed: {r.status_code} {r.text}"
    data = r.json()
    assert "token" in data, data
    assert "user" in data, data
    return data


@pytest.fixture
def testuser_token():
    return _login(USER_EMAIL, USER_PASSWORD)["token"]


@pytest.fixture
def admin_token():
    return _login(ADMIN_EMAIL, ADMIN_PASSWORD)["token"]


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---- ton_proof helpers (mandatory-proof mode: TON_PROOF_REQUIRED=1) ----
DOMAIN = "localhost"


def _mint_wallet():
    """Fresh ed25519 keypair + minimal walletStateInit embedding the pubkey."""
    sk = SigningKey.generate()
    pk = bytes(sk.verify_key)
    data_cell = (
        begin_cell().store_uint(0, 32).store_uint(698983191, 32)
        .store_bytes(pk).store_uint(0, 1).end_cell()
    )
    code_cell = begin_cell().store_uint(0xDEADBEEF, 32).end_cell()
    si_cell = (
        begin_cell().store_bit(0).store_bit(0)
        .store_bit(1).store_ref(code_cell)
        .store_bit(1).store_ref(data_cell)
        .store_bit(0).end_cell()
    )
    si_b64 = base64.b64encode(si_cell.to_boc()).decode()
    addr_hash = si_cell.hash
    raw = f"0:{addr_hash.hex()}"
    uf = Address(raw).to_str(is_user_friendly=True, is_url_safe=True,
                             is_bounceable=False, is_test_only=False)
    return {"sk": sk, "pk": pk, "raw": raw, "uf": uf,
            "state_init_b64": si_b64, "addr_hash": addr_hash}


def _sign_proof(wallet, nonce, ts=None, domain=DOMAIN):
    if ts is None:
        ts = int(time.time())
    inner = (
        b"ton-proof-item-v2/" + struct.pack("<i", 0) + wallet["addr_hash"]
        + struct.pack("<I", len(domain.encode())) + domain.encode()
        + struct.pack("<Q", ts) + nonce.encode()
    )
    inner_hash = hashlib.sha256(inner).digest()
    sign_hash = hashlib.sha256(b"\xff\xff" + b"ton-connect" + inner_hash).digest()
    sig = base64.b64encode(wallet["sk"].sign(sign_hash).signature).decode()
    return {
        "timestamp": ts,
        "domain": {"lengthBytes": len(domain), "value": domain},
        "signature": sig,
        "payload": nonce,
        "state_init": wallet["state_init_b64"],
    }


def _get_nonce():
    r = requests.get(f"{BASE_URL}/api/auth/wallet/proof-payload", timeout=10)
    assert r.status_code == 200, r.text
    return r.json()["payload"]


def _verify_wallet_signed(wallet, *, username=None, address=None):
    nonce = _get_nonce()
    proof = _sign_proof(wallet, nonce)
    body = {
        "address": address or wallet["uf"],
        "public_key": wallet["pk"].hex(),
        "proof": proof,
        "language": "ru",
    }
    if username is not None:
        body["username"] = username
    return requests.post(f"{BASE_URL}/api/auth/verify-wallet", json=body, timeout=15)


def _cleanup_minted(db, wallet):
    db.users.delete_many({
        "$or": [{"raw_address": wallet["raw"]}, {"wallet_address": wallet["uf"]}],
        "email": {"$nin": [ADMIN_EMAIL, USER_EMAIL]},
    })


# ------------------------- 1) login tests -------------------------

class TestLogin:
    def test_login_testuser(self):
        d = _login(USER_EMAIL, USER_PASSWORD)
        assert d["user"]["email"] == USER_EMAIL
        # admin flag should be False for regular user
        assert d["user"].get("is_admin", False) is False

    def test_login_admin(self):
        d = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
        assert d["user"]["email"] == ADMIN_EMAIL
        assert d["user"].get("is_admin") is True


# ------------------------- 2) verify-wallet tests -------------------------

class TestVerifyWallet:
    """Cover the wallet-first flow (A/B/C) with REAL signed ton_proofs
    (mandatory-proof mode). A single minted wallet is reused across the
    ordered steps."""

    # Shared minted wallet for the whole class (tests run in file order).
    W = _mint_wallet()

    def test_a_need_username_when_unknown(self, mongo_db):
        _cleanup_minted(mongo_db, self.W)
        r = _verify_wallet_signed(self.W)  # no username
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("status") == "need_username", data
        # No user should have been created
        found = mongo_db.users.find_one({
            "$or": [
                {"raw_address": self.W["raw"]},
                {"wallet_address": self.W["uf"]},
            ]
        })
        assert found is None, f"User should NOT be created on need_username, got: {found}"

    def test_b_register_new_user_with_username(self, mongo_db):
        uname = f"walletuser_{uuid.uuid4().hex[:6]}"
        pytest.wallet_username = uname
        r = _verify_wallet_signed(self.W, username=uname)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("status") == "ok", data
        assert data.get("is_new_user") is True, data
        assert data.get("token"), data
        assert data["user"]["username"] == uname
        assert data["user"]["wallet_address"] == self.W["uf"]

    def test_c_relogin_same_wallet_no_username(self, mongo_db):
        r = _verify_wallet_signed(self.W)  # no username → owner login
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("status") == "ok", data
        assert data.get("is_new_user") is False, data
        assert data["user"]["username"] == getattr(pytest, "wallet_username", None)
        count = mongo_db.users.count_documents({
            "$or": [
                {"raw_address": self.W["raw"]},
                {"wallet_address": self.W["uf"]},
            ]
        })
        assert count == 1, f"Expected exactly 1 user for wallet, got {count}"

    def test_d_relogin_by_raw_form(self, mongo_db):
        # Same wallet, address supplied in RAW (0:hex) form → same owner.
        r = _verify_wallet_signed(self.W, address=self.W["raw"])
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("status") == "ok", data
        assert data.get("is_new_user") is False, data
        assert data["user"]["username"] == getattr(pytest, "wallet_username", None)
        _cleanup_minted(mongo_db, self.W)


# ------------------------- 3) link-wallet tests -------------------------

class TestLinkWallet:
    def test_link_rejects_already_owned_wallet(self, mongo_db, testuser_token):
        # Pre-check: testuser must have no wallet
        u = mongo_db.users.find_one({"email": USER_EMAIL})
        assert not u.get("wallet_address"), \
            f"testuser should start with no wallet, has: {u.get('wallet_address')}"

        # Register a fresh wallet to a DIFFERENT (new) account via signed proof,
        # so the wallet is genuinely "occupied" by someone else.
        owner_wallet = _mint_wallet()
        _cleanup_minted(mongo_db, owner_wallet)
        reg = _verify_wallet_signed(owner_wallet, username=f"owner_{uuid.uuid4().hex[:6]}")
        assert reg.status_code == 200 and reg.json().get("status") == "ok", reg.text

        try:
            # Now testuser tries to link that same (occupied) wallet → rejected.
            r = requests.post(
                f"{BASE_URL}/api/auth/link-wallet",
                headers=_auth_header(testuser_token),
                json={"wallet_address": owner_wallet["uf"]},
                timeout=15,
            )
            assert r.status_code == 400, f"expected 400, got {r.status_code} {r.text}"
            detail = r.json().get("detail", "")
            # Стабильный machine-код (Сценарий C) → фронт локализует его.
            assert detail == "wallet_already_linked", detail

            # testuser's wallet_address MUST remain unset
            u2 = mongo_db.users.find_one({"email": USER_EMAIL})
            assert not u2.get("wallet_address"), \
                f"testuser wallet should remain None, got {u2.get('wallet_address')}"
        finally:
            _cleanup_minted(mongo_db, owner_wallet)

    def test_link_succeeds_for_free_wallet(self, mongo_db, testuser_token):
        # Ensure FREE wallet not owned
        mongo_db.users.update_many(
            {"$or": [
                {"raw_address": FREE_WALLET_RAW},
                {"wallet_address": FREE_WALLET_UF},
            ]},
            {"$unset": {"wallet_address": "", "raw_address": ""}}
        )
        r = requests.post(
            f"{BASE_URL}/api/auth/link-wallet",
            headers=_auth_header(testuser_token),
            json={"wallet_address": FREE_WALLET_RAW},
            timeout=15,
        )
        assert r.status_code == 200, f"expected 200, got {r.status_code} {r.text}"
        data = r.json()
        assert data.get("status") == "success", data
        assert data.get("wallet_address") == FREE_WALLET_UF, data
        # verify persisted
        u = mongo_db.users.find_one({"email": USER_EMAIL})
        assert u.get("wallet_address") == FREE_WALLET_UF
        assert u.get("raw_address") == FREE_WALLET_RAW


# ------------------------- 4) unlink-wallet -------------------------

class TestUnlinkWallet:
    def test_unlink_frees_wallet(self, mongo_db, testuser_token):
        # Precondition: testuser owns FREE wallet from previous test.
        # If prior test didn't run in this session, link it now.
        u = mongo_db.users.find_one({"email": USER_EMAIL})
        if not u.get("wallet_address"):
            r0 = requests.post(
                f"{BASE_URL}/api/auth/link-wallet",
                headers=_auth_header(testuser_token),
                json={"wallet_address": FREE_WALLET_RAW},
                timeout=15,
            )
            assert r0.status_code == 200, r0.text

        r = requests.post(
            f"{BASE_URL}/api/auth/unlink-wallet",
            headers=_auth_header(testuser_token),
            timeout=15,
        )
        assert r.status_code == 200, r.text
        # verify via GET /api/auth/me
        me = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers=_auth_header(testuser_token),
            timeout=15,
        )
        assert me.status_code == 200, me.text
        assert not me.json().get("wallet_address"), me.json()

    def test_freed_wallet_relinkable_by_admin(self, mongo_db, admin_token):
        # Ensure admin also starts with no wallet
        mongo_db.users.update_one(
            {"email": ADMIN_EMAIL},
            {"$unset": {"wallet_address": "", "raw_address": ""}}
        )
        r = requests.post(
            f"{BASE_URL}/api/auth/link-wallet",
            headers=_auth_header(admin_token),
            json={"wallet_address": FREE_WALLET_RAW},
            timeout=15,
        )
        assert r.status_code == 200, f"expected 200 after unlink, got {r.status_code} {r.text}"
        data = r.json()
        assert data.get("status") == "success"
        assert data.get("wallet_address") == FREE_WALLET_UF


# ------------------------- 5) uniqueness invariant -------------------------

class TestUniqueness:
    def test_no_two_users_share_wallet(self, mongo_db):
        # Aggregate: any wallet_address that isn't null/empty owned by >1 users?
        pipeline = [
            {"$match": {"wallet_address": {"$exists": True, "$nin": [None, ""]}}},
            {"$group": {"_id": "$wallet_address", "n": {"$sum": 1}}},
            {"$match": {"n": {"$gt": 1}}},
        ]
        dups = list(mongo_db.users.aggregate(pipeline))
        assert dups == [], f"Duplicate wallet_address found: {dups}"

        pipeline_raw = [
            {"$match": {"raw_address": {"$exists": True, "$nin": [None, ""]}}},
            {"$group": {"_id": "$raw_address", "n": {"$sum": 1}}},
            {"$match": {"n": {"$gt": 1}}},
        ]
        dups_raw = list(mongo_db.users.aggregate(pipeline_raw))
        assert dups_raw == [], f"Duplicate raw_address found: {dups_raw}"
