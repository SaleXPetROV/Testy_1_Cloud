"""
Backend tests for TON_CITY_v2.3 wallet-auth 2FA + ton_proof nonce lifecycle bug.

Bug: When TOTP-2FA is enabled on a wallet-linked account, the first
`/api/auth/verify-wallet` call (no totp_code) used to CONSUME the single-use
ton_proof nonce and return `requires_2fa`. The follow-up call with the same
proof envelope + `totp_code` then hit a missing nonce and 401'd with
`ton_proof payload invalid or expired`.

Fix: Backend now PEEKS the nonce on every call (existence + expiry) and only
CONSUMES it atomically right BEFORE issuing the token — after the 2FA gate.

This suite exercises the fix end-to-end by crafting real signed ton_proof
envelopes with nacl+pytoniq_core (no wallet SDK needed) against the seeded
`testuser` account which we temporarily convert into a wallet+TOTP account
for the duration of the tests.

Run:
    MONGO_URL=mongodb://localhost:27017 DB_NAME=test_database \
    BACKEND_URL=http://localhost:8001 \
    pytest /app/backend/tests/test_wallet_auth_2fa_ton_proof.py -v -n 0
"""
import base64
import hashlib
import os
import struct
import time
import uuid

import pyotp
import pytest
import requests
from nacl.signing import SigningKey
from pymongo import MongoClient
from pytoniq_core import Address, begin_cell

# ---------- config ----------

BASE_URL = os.environ.get("BACKEND_URL", "http://localhost:8001").rstrip("/")
USER_EMAIL = "testuser@example.com"
USER_PASSWORD = "Test1234!"
DOMAIN = "localhost"


# ---------- helpers ----------

def _read_env():
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        env_path = "/app/backend/.env"
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("MONGO_URL=") and not mongo_url:
                        mongo_url = line.split("=", 1)[1].strip().strip('"').strip("'")
                    elif line.startswith("DB_NAME=") and not db_name:
                        db_name = line.split("=", 1)[1].strip().strip('"').strip("'")
    return mongo_url or "mongodb://localhost:27017", db_name or "test_database"


@pytest.fixture(scope="session")
def mongo_db():
    mongo_url, db_name = _read_env()
    return MongoClient(mongo_url)[db_name]


def _mint_wallet():
    """Generate a fresh ed25519 keypair + a minimal walletStateInit that
    embeds the pubkey in the standard v4-ish layout the backend can parse."""
    sk = SigningKey.generate()
    pk = bytes(sk.verify_key)
    # data cell: seqno(32) + walletId(32) + pubkey(256) + plugins-empty(1)
    data_cell = (
        begin_cell()
        .store_uint(0, 32)
        .store_uint(698983191, 32)
        .store_bytes(pk)
        .store_uint(0, 1)
        .end_cell()
    )
    # tiny placeholder code cell — hash only used for the address
    code_cell = begin_cell().store_uint(0xDEADBEEF, 32).end_cell()
    si_cell = (
        begin_cell()
        .store_bit(0)
        .store_bit(0)
        .store_bit(1).store_ref(code_cell)
        .store_bit(1).store_ref(data_cell)
        .store_bit(0)
        .end_cell()
    )
    si_b64 = base64.b64encode(si_cell.to_boc()).decode()
    addr_hash = si_cell.hash
    raw = f"0:{addr_hash.hex()}"
    uf = Address(raw).to_str(
        is_user_friendly=True, is_url_safe=True, is_bounceable=False, is_test_only=False
    )
    return {"sk": sk, "pk": pk, "raw": raw, "uf": uf, "state_init_b64": si_b64,
            "addr_hash": addr_hash}


def _sign_proof(wallet, nonce: str, ts: int | None = None,
                domain: str = DOMAIN) -> dict:
    """Build a valid TonProof v2 envelope for the given wallet + nonce."""
    if ts is None:
        ts = int(time.time())
    inner = (
        b"ton-proof-item-v2/"
        + struct.pack("<i", 0)
        + wallet["addr_hash"]
        + struct.pack("<I", len(domain.encode()))
        + domain.encode()
        + struct.pack("<Q", ts)
        + nonce.encode()
    )
    inner_hash = hashlib.sha256(inner).digest()
    outer = b"\xff\xff" + b"ton-connect" + inner_hash
    sign_hash = hashlib.sha256(outer).digest()
    sig = base64.b64encode(wallet["sk"].sign(sign_hash).signature).decode()
    return {
        "timestamp": ts,
        "domain": {"lengthBytes": len(domain), "value": domain},
        "signature": sig,
        "payload": nonce,
        "state_init": wallet["state_init_b64"],
    }


def _get_nonce() -> str:
    r = requests.get(f"{BASE_URL}/api/auth/wallet/proof-payload", timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("payload"), body
    assert body.get("ttl_sec"), body
    return body["payload"]


def _verify_wallet(wallet, nonce: str, *, totp_code: str | None = None,
                   username: str | None = None,
                   proof: dict | None = None) -> requests.Response:
    if proof is None:
        proof = _sign_proof(wallet, nonce)
    body = {
        "address": wallet["uf"],
        "public_key": wallet["pk"].hex(),
        "proof": proof,
        "language": "ru",
    }
    if totp_code is not None:
        body["totp_code"] = totp_code
    if username is not None:
        body["username"] = username
    return requests.post(f"{BASE_URL}/api/auth/verify-wallet", json=body, timeout=15)


def _cleanup_wallet(db, wallet):
    db.wallet_proof_payloads.delete_many({})
    db.users.delete_many({
        "$or": [
            {"raw_address": wallet["raw"]},
            {"wallet_address": wallet["uf"]},
        ],
        "email": {"$ne": USER_EMAIL},
    })


def _detach_testuser(db):
    """Fully reset testuser between tests: no wallet, no 2FA."""
    db.users.update_one(
        {"email": USER_EMAIL},
        {"$unset": {
            "wallet_address": "", "raw_address": "",
            "is_2fa_enabled": "", "two_factor_secret": "", "backup_codes": "",
        }},
    )


def _attach_testuser_to_wallet(db, wallet, totp_secret: str | None = None):
    """Make testuser own this wallet (+ optionally enable TOTP 2FA)."""
    update = {
        "wallet_address": wallet["uf"],
        "raw_address": wallet["raw"],
    }
    if totp_secret:
        update["is_2fa_enabled"] = True
        update["two_factor_secret"] = totp_secret
    db.users.update_one({"email": USER_EMAIL}, {"$set": update})


# ---------- session-wide isolation ----------

@pytest.fixture(scope="session", autouse=True)
def _session_cleanup(mongo_db):
    _detach_testuser(mongo_db)
    mongo_db.wallet_proof_payloads.delete_many({})
    yield
    _detach_testuser(mongo_db)
    mongo_db.wallet_proof_payloads.delete_many({})


# ---------- 0) nonce endpoint sanity ----------

class TestNonceEndpoint:
    def test_issues_payload_and_ttl(self):
        r = requests.get(f"{BASE_URL}/api/auth/wallet/proof-payload", timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert isinstance(body.get("payload"), str) and len(body["payload"]) >= 16
        assert isinstance(body.get("ttl_sec"), int) and body["ttl_sec"] > 0


# ---------- 1) THE bug: 2FA reuses the same proof envelope ----------

class TestTwoFactorProofReuse:
    """Reproduce the reported bug: with 2FA enabled, the SAME ton_proof
    envelope must be usable across `requires_2fa` → totp submission."""

    def test_requires_2fa_then_success_with_same_proof(self, mongo_db):
        wallet = _mint_wallet()
        secret = pyotp.random_base32()
        _cleanup_wallet(mongo_db, wallet)
        _detach_testuser(mongo_db)
        _attach_testuser_to_wallet(mongo_db, wallet, totp_secret=secret)

        try:
            nonce = _get_nonce()
            proof = _sign_proof(wallet, nonce)

            # 1st call — no totp_code → requires_2fa, 200, nonce PRESERVED
            r1 = _verify_wallet(wallet, nonce, proof=proof)
            assert r1.status_code == 200, f"1st call: {r1.status_code} {r1.text}"
            d1 = r1.json()
            assert d1.get("status") == "requires_2fa", d1
            assert d1.get("requires_2fa") is True, d1
            assert "token" not in d1, "must NOT issue token before 2FA"
            # nonce should still be in the DB (peek-only path)
            assert mongo_db.wallet_proof_payloads.find_one({"payload": nonce}), \
                "nonce should NOT be consumed on the 2FA-required branch"

            # 2nd call — same proof + valid TOTP → 200 + token
            code = pyotp.TOTP(secret).now()
            r2 = _verify_wallet(wallet, nonce, proof=proof, totp_code=code)
            assert r2.status_code == 200, \
                f"2nd call must succeed with same proof: {r2.status_code} {r2.text}"
            d2 = r2.json()
            assert d2.get("status") == "ok", d2
            assert d2.get("token"), d2
            assert d2["user"]["wallet_address"] == wallet["uf"]

            # nonce MUST be consumed now
            assert mongo_db.wallet_proof_payloads.find_one({"payload": nonce}) is None, \
                "nonce must be consumed after token issuance"

            # 3rd call — REPLAY same proof: 401
            r3 = _verify_wallet(wallet, nonce, proof=proof, totp_code=code)
            assert r3.status_code == 401, f"replay must fail: {r3.status_code} {r3.text}"
            detail = r3.json().get("detail", "")
            assert "payload" in detail.lower() or "expired" in detail.lower(), detail
        finally:
            _detach_testuser(mongo_db)
            _cleanup_wallet(mongo_db, wallet)


# ---------- 2) Wrong TOTP does NOT consume the nonce ----------

class TestWrongTotpPreservesNonce:
    def test_wrong_totp_survives_then_correct_wins(self, mongo_db):
        wallet = _mint_wallet()
        secret = pyotp.random_base32()
        _cleanup_wallet(mongo_db, wallet)
        _detach_testuser(mongo_db)
        _attach_testuser_to_wallet(mongo_db, wallet, totp_secret=secret)

        try:
            nonce = _get_nonce()
            proof = _sign_proof(wallet, nonce)

            # (2) no totp_code → requires_2fa
            r_req = _verify_wallet(wallet, nonce, proof=proof)
            assert r_req.status_code == 200 and \
                r_req.json().get("status") == "requires_2fa", r_req.text

            # (3) wrong totp_code → 401 "Неверный код 2FA"
            wrong = "000000"
            # ensure it's not accidentally right
            if pyotp.TOTP(secret).verify(wrong, valid_window=1):
                wrong = "111111"
            r_wrong = _verify_wallet(wallet, nonce, proof=proof, totp_code=wrong)
            assert r_wrong.status_code == 401, \
                f"wrong TOTP must 401: {r_wrong.status_code} {r_wrong.text}"
            detail = r_wrong.json().get("detail", "")
            assert "2FA" in detail or "код" in detail.lower() or "totp" in detail.lower(), detail

            # nonce MUST still exist (fix: wrong TOTP doesn't consume)
            assert mongo_db.wallet_proof_payloads.find_one({"payload": nonce}), \
                "nonce must survive a wrong-code retry"

            # (4) correct totp_code → 200 + token
            code = pyotp.TOTP(secret).now()
            r_ok = _verify_wallet(wallet, nonce, proof=proof, totp_code=code)
            assert r_ok.status_code == 200, \
                f"correct TOTP after wrong must succeed: {r_ok.status_code} {r_ok.text}"
            d_ok = r_ok.json()
            assert d_ok.get("status") == "ok" and d_ok.get("token"), d_ok

            # nonce consumed now
            assert mongo_db.wallet_proof_payloads.find_one({"payload": nonce}) is None
        finally:
            _detach_testuser(mongo_db)
            _cleanup_wallet(mongo_db, wallet)


# ---------- 3) Baseline (no 2FA): nonce consumed on successful register ----------

class TestBaselineNoTwoFactor:
    def test_register_then_replay_rejected(self, mongo_db):
        wallet = _mint_wallet()
        _cleanup_wallet(mongo_db, wallet)

        try:
            nonce = _get_nonce()
            proof = _sign_proof(wallet, nonce)
            uname = f"TEST_wallet2fa_{uuid.uuid4().hex[:6]}"

            r1 = _verify_wallet(wallet, nonce, proof=proof, username=uname)
            assert r1.status_code == 200, f"register: {r1.status_code} {r1.text}"
            d1 = r1.json()
            assert d1.get("status") == "ok", d1
            assert d1.get("is_new_user") is True, d1
            assert d1.get("token"), d1

            # nonce is consumed post-register
            assert mongo_db.wallet_proof_payloads.find_one({"payload": nonce}) is None

            # replay MUST 401
            r2 = _verify_wallet(wallet, nonce, proof=proof)
            assert r2.status_code == 401, \
                f"replay must 401: {r2.status_code} {r2.text}"
            detail = r2.json().get("detail", "").lower()
            assert "payload" in detail or "expired" in detail, detail
        finally:
            _cleanup_wallet(mongo_db, wallet)


# ---------- 4) TON_PROOF_REQUIRED=0: permissive mode still works ----------

class TestPermissiveMode:
    """Security policy (v2.3 Part 4): ton_proof is MANDATORY
    (TON_PROOF_REQUIRED=1). A verify-wallet call WITHOUT a proof envelope must
    be rejected with 401 'ton_proof required' — merely knowing a wallet address
    can never grant a session."""

    def test_verify_wallet_without_proof_rejected(self, mongo_db):
        wallet = _mint_wallet()
        _cleanup_wallet(mongo_db, wallet)

        try:
            uname = f"TEST_noproof_{uuid.uuid4().hex[:6]}"
            body = {
                "address": wallet["uf"],
                "language": "ru",
                "username": uname,
            }
            r = requests.post(f"{BASE_URL}/api/auth/verify-wallet",
                              json=body, timeout=15)
            assert r.status_code == 401, f"expected 401, got: {r.status_code} {r.text}"
            assert "ton_proof" in r.text.lower(), r.text
        finally:
            _cleanup_wallet(mongo_db, wallet)
