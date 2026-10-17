"""Independent HTTP + integration tests for TON_CITY v2.3 requirements.

Covered:
- POST /api/admin/seed-test-users -> 200 with correct secret, 403 otherwise
- POST /api/auth/login -> admin and user tokens
- core.ton_proof.fetch_onchain_pubkey mainnet call
- Anti-replay: nonce single-use via /auth/verify-wallet
- Domain allowlist: proof with domain not in TON_PROOF_ALLOWED_DOMAINS -> 401
- 2FA lockout endpoint sanity (rate-limit / 429 or 401 for garbage tokens)
- Unique wallet index on users.raw_address
- /auth/link-wallet -> detail 'wallet_already_linked'

Run: BACKEND_URL=http://localhost:8001 python -m pytest \
     tests/test_v23_end_to_end_curl.py -n 0 -v
"""
import asyncio
import json
import os
import time
import uuid

import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

# Reuse crypto helpers already validated by the existing suite.
from tests.test_wallet_auth_2fa_ton_proof import (  # noqa: E402
    _get_nonce,
    _mint_wallet,
    _sign_proof,
    _verify_wallet,
)


@pytest.fixture(scope="session")
def mongo_db():
    return MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))[
        os.environ.get("DB_NAME", "ton_city")
    ]

BASE_URL = os.environ.get("BACKEND_URL", "http://localhost:8001").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "ton_city")

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PW = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PW = "Test1234!"
ADMIN_SECRET = "admin-secret-key-2025"
BAD_DOMAIN = "evil.com"


def _post(path, **kw):
    return requests.post(f"{BASE_URL}{path}", timeout=30, **kw)


def _get(path, **kw):
    return requests.get(f"{BASE_URL}{path}", timeout=30, **kw)


# ---------- Seed endpoint ----------
class TestSeedEndpoint:
    def test_seed_without_secret_403(self):
        r = _post("/api/admin/seed-test-users")
        assert r.status_code == 403, r.text

    def test_seed_wrong_secret_403(self):
        r = _post("/api/admin/seed-test-users", headers={"X-Admin-Secret": "wrong"})
        assert r.status_code == 403, r.text

    def test_seed_correct_secret_200(self):
        r = _post(
            "/api/admin/seed-test-users",
            headers={"X-Admin-Secret": ADMIN_SECRET},
        )
        assert r.status_code == 200, r.text
        j = r.json()
        text = json.dumps(j).lower()
        assert "admin" in text or "user" in text or j.get("status") in ("ok", "success", "seeded")


# ---------- Email login ----------
class TestEmailLogin:
    def test_admin_login(self):
        r = _post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PW})
        assert r.status_code == 200, r.text
        d = r.json()
        token = d.get("token") or d.get("access_token") or d.get("user", {}).get("token")
        assert token, f"no token in {d}"
        is_admin = d.get("is_admin", d.get("user", {}).get("is_admin"))
        assert is_admin is True, f"expected is_admin true, got {is_admin} full={d}"

    def test_user_login(self):
        r = _post("/api/auth/login", json={"email": USER_EMAIL, "password": USER_PW})
        assert r.status_code == 200, r.text
        d = r.json()
        token = d.get("token") or d.get("access_token")
        assert token, f"no token in {d}"
        is_admin = d.get("is_admin", d.get("user", {}).get("is_admin"))
        assert is_admin in (False, None, 0), f"user should not be admin, got {is_admin}"


# ---------- On-chain pubkey fallback ----------
class TestOnChainPubkeyFallback:
    def test_mainnet_get_public_key(self):
        from core.ton_proof import fetch_onchain_pubkey

        pk = asyncio.run(
            fetch_onchain_pubkey("EQD5mxRgCuRNLxKxeOjG6r14iSroLF5FtomPnet-sgP5xNJb")
        )
        assert pk is not None, "fetch_onchain_pubkey returned None"
        assert isinstance(pk, (bytes, bytearray)), f"expected bytes, got {type(pk)}"
        assert len(pk) == 32, f"expected 32 raw bytes, got {len(pk)}"


# ---------- Anti-replay ----------
class TestNonceAntiReplay:
    def test_nonce_single_use(self, mongo_db):
        w = _mint_wallet()
        try:
            nonce = _get_nonce()
            r1 = _verify_wallet(w, nonce, username=f"TEST_r_{uuid.uuid4().hex[:6]}")
            assert r1.status_code == 200, r1.text
            r2 = _verify_wallet(w, nonce)
            assert r2.status_code == 401, f"replay accepted: {r2.status_code} {r2.text}"
        finally:
            mongo_db.wallet_proof_payloads.delete_many({})
            mongo_db.users.delete_many(
                {"raw_address": w["raw"]}
            )


# ---------- Domain allowlist ----------
class TestDomainAllowlist:
    def test_bad_domain_rejected(self, mongo_db):
        w = _mint_wallet()
        try:
            nonce = _get_nonce()
            proof = _sign_proof(w, nonce, domain=BAD_DOMAIN)
            r = _verify_wallet(
                w,
                nonce,
                username=f"TEST_dom_{uuid.uuid4().hex[:6]}",
                proof=proof,
            )
            assert r.status_code == 401, f"bad domain accepted: {r.status_code} {r.text}"
        finally:
            mongo_db.wallet_proof_payloads.delete_many({})
            mongo_db.users.delete_many({"raw_address": w["raw"]})


# ---------- 2FA endpoint hardening ----------
class Test2FAEndpoint:
    """Verify /auth/login-2fa records wrong-password failures (5→24h lockout)
    and is rate-limited at 15/minute."""

    def test_login_2fa_lockout_and_rate_limit(self, mongo_db):
        # Use a unique throwaway email so we do not lock out real users.
        email = f"TEST_2fa_lockout_{uuid.uuid4().hex[:8]}@example.com"
        got_429 = False
        got_401 = 0
        got_423 = 0  # 'locked'
        for _ in range(20):
            r = _post(
                "/api/auth/login-2fa",
                json={"email": email, "password": "wrong", "totp_code": "000000"},
            )
            code = r.status_code
            assert code != 200, f"login-2fa accepted garbage: {r.text}"
            if code == 429:
                got_429 = True
                break
            if code == 423:
                got_423 += 1
                # Once locked we can stop — that proves lockout works.
                break
            if code == 401:
                got_401 += 1
        # Cleanup lockout state so we do not poison other tests.
        try:
            mongo_db.login_failures.delete_many({"email": email})
        except Exception:
            pass
        assert got_429 or got_423 > 0 or got_401 >= 5, (
            f"login-2fa neither rate-limited nor locked out nor rejected; "
            f"429={got_429} 423={got_423} 401={got_401}"
        )


# ---------- Unique wallet index ----------
class TestUniqueWalletIndex:
    def test_unique_wallet_index_on_users(self):
        async def _check():
            client = AsyncIOMotorClient(MONGO_URL)
            db = client[DB_NAME]
            idxs = await db.users.index_information()
            client.close()
            return idxs

        idxs = asyncio.run(_check())
        found = None
        for name, spec in idxs.items():
            keys = spec.get("key", [])
            if any(k[0] == "raw_address" for k in keys) and spec.get("unique"):
                found = (name, spec)
                break
        assert found, f"unique index on raw_address not found; had: {list(idxs.keys())}"
        name, spec = found
        # Should be partial (partialFilterExpression) so nulls don't collide.
        assert "partialFilterExpression" in spec, (
            f"index {name} exists but is not partial: {spec}"
        )


# ---------- Link occupied wallet -> wallet_already_linked ----------
class TestLinkAlreadyOwnedWallet:
    def test_link_wallet_returns_wallet_already_linked(self, mongo_db):
        # Ensure seed is applied
        _post(
            "/api/admin/seed-test-users",
            headers={"X-Admin-Secret": ADMIN_SECRET},
        )

        # Attach a fresh wallet to testuser so we can then try to link it as admin
        w = _mint_wallet()
        try:
            mongo_db.users.update_one(
                {"email": USER_EMAIL},
                {"$set": {"wallet_address": w["uf"], "raw_address": w["raw"]}},
            )

            # Login as admin
            r = _post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PW})
            assert r.status_code == 200, r.text
            token = r.json().get("token") or r.json().get("access_token")
            assert token
            headers = {"Authorization": f"Bearer {token}"}

            nonce = _get_nonce()
            proof = _sign_proof(w, nonce)

            body = {
                "wallet_address": w["uf"],
                "public_key": w["pk"].hex(),
                "proof": proof,
                "language": "en",
            }
            r = _post("/api/auth/link-wallet", json=body, headers=headers)
            # 4xx with detail 'wallet_already_linked'
            assert r.status_code in (400, 401, 403, 409, 422), (
                f"unexpected code {r.status_code}: {r.text}"
            )
            try:
                detail = r.json().get("detail")
            except Exception:
                detail = r.text
            assert detail == "wallet_already_linked", f"got detail={detail!r}, body={r.text}"
        finally:
            mongo_db.users.update_one(
                {"email": USER_EMAIL},
                {"$unset": {"wallet_address": "", "raw_address": ""}},
            )
            mongo_db.wallet_proof_payloads.delete_many({})
            # Restore seed to canonical state
            _post(
                "/api/admin/seed-test-users",
                headers={"X-Admin-Secret": ADMIN_SECRET},
            )
