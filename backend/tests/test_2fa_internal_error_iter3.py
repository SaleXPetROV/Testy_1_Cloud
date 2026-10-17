"""Iter3 regression: a 2FA (TOTP) login must NEVER return 500 "internal error".

Bug: TOTP secrets are stored encrypted (TOTP_ENC_KEY). When the key is missing or
changed, decrypt_secret() used to return the raw ciphertext; pyotp.TOTP(ciphertext)
then raised binascii.Error → unhandled → HTTP 500 on the /auth 2FA screen.

Covers:
  * unit: security.totp_crypto.decrypt_secret / _looks_base32
  * unit: security.totp_handler.verify_totp_code never raises
  * API : POST /api/auth/login-2fa valid code → 200 + token
  * API : POST /api/auth/login-2fa wrong code → 401 (not 500)
  * API : POST /api/auth/login-2fa with an UNDECRYPTABLE stored secret → 401 (not 500)
  * API : admin login path unaffected

State: mutates users.two_factor_secret / is_2fa_enabled for `testuser` and RESETS
it (2FA disabled, secret unset) at module teardown so /app/memory/test_credentials.md
credentials keep working. Also clears login_attempts lockout rows for the test user.
"""
import os
import sys
import time
import logging

import pyotp
import pytest
import requests
from cryptography.fernet import Fernet
from dotenv import dotenv_values
from pymongo import MongoClient

_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from security import totp_crypto  # noqa: E402
from security.totp_handler import verify_totp_code  # noqa: E402

_fe_env = dotenv_values("/app/frontend/.env")
_base = os.environ.get("REACT_APP_BACKEND_URL") or _fe_env.get("REACT_APP_BACKEND_URL")
if not _base:
    raise RuntimeError("REACT_APP_BACKEND_URL missing from env and /app/frontend/.env")
BASE_URL = _base.rstrip("/")

_be_env = dotenv_values("/app/backend/.env")
MONGO_URL = os.environ.get("MONGO_URL") or _be_env.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME") or _be_env.get("DB_NAME")
if not MONGO_URL or not DB_NAME:
    raise RuntimeError("MONGO_URL / DB_NAME missing from /app/backend/.env")

USER_EMAIL = "testuser@example.com"
USER_LOGIN = "testuser"
USER_PASSWORD = "Test1234!"
ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")

BAD_CIPHERTEXT = "gAAAAABm-not-a-valid-base32-fernet-token_xyz=="


# ==================== fixtures ====================

@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def db():
    c = MongoClient(MONGO_URL, serverSelectionTimeoutMS=8000)
    yield c[DB_NAME]
    c.close()


def _clear_lockout(db):
    db.login_attempts.delete_many({"key": {"$regex": "^(testuser|testuser@example.com)\\|"}})


def _set_secret(db, secret, enabled=True):
    res = db.users.update_one(
        {"email": USER_EMAIL},
        {"$set": {"two_factor_secret": secret, "is_2fa_enabled": enabled}},
    )
    assert res.matched_count == 1, "seeded user testuser@example.com not found in DB"
    _clear_lockout(db)


@pytest.fixture(scope="module", autouse=True)
def reset_testuser_2fa(db):
    """Always leave testuser with 2FA DISABLED and no stored secret."""
    yield
    db.users.update_one(
        {"email": USER_EMAIL},
        {
            "$set": {"is_2fa_enabled": False},
            "$unset": {"two_factor_secret": "", "backup_codes": "", "pending_2fa_secret": ""},
        },
    )
    _clear_lockout(db)
    doc = db.users.find_one({"email": USER_EMAIL}, {"_id": 0, "is_2fa_enabled": 1, "two_factor_secret": 1})
    assert doc is not None
    assert doc.get("is_2fa_enabled") in (False, None)
    assert "two_factor_secret" not in doc


def _login_2fa(client, code, password=USER_PASSWORD, email=USER_LOGIN, secret=None, _retry=True):
    """POST /api/auth/login-2fa. If `secret` is given the TOTP code is derived
    fresh at request time (so a rate-limit backoff can't stale the code)."""
    payload = {"email": email, "password": password}
    if secret is not None:
        payload["totp_code"] = _fresh_code(secret)
    elif code is not None:
        payload["totp_code"] = code
    r = client.post(f"{BASE_URL}/api/auth/login-2fa", json=payload, timeout=40)
    # /auth/login-2fa is rate limited to 15/min — back off once so back-to-back
    # runs of this suite don't produce false failures.
    if r.status_code == 429 and _retry:
        time.sleep(62)
        return _login_2fa(client, code, password=password, email=email,
                          secret=secret, _retry=False)
    return r


def _fresh_code(secret):
    """Return a TOTP code with enough window left to survive the round-trip."""
    if 30 - (int(time.time()) % 30) < 6:
        time.sleep(7)
    return pyotp.TOTP(secret).now()


# ==================== unit: security/totp_crypto.py ====================

class TestTotpCryptoUnit:
    def test_looks_base32_true_for_pyotp_secret(self):
        for _ in range(5):
            assert totp_crypto._looks_base32(pyotp.random_base32()) is True
        assert totp_crypto._looks_base32(pyotp.random_base32(length=32)) is True

    def test_looks_base32_false_for_fernet_token(self):
        token = Fernet(Fernet.generate_key()).encrypt(b"JBSWY3DPEHPK3PXP").decode()
        assert totp_crypto._looks_base32(token) is False
        assert totp_crypto._looks_base32(BAD_CIPHERTEXT) is False
        assert totp_crypto._looks_base32("") is False

    def test_decrypt_secret_returns_legacy_plaintext_unchanged(self):
        secret = pyotp.random_base32()
        assert totp_crypto.decrypt_secret(secret) == secret

    def test_decrypt_secret_returns_empty_for_undecryptable(self, caplog):
        token = Fernet(Fernet.generate_key()).encrypt(b"JBSWY3DPEHPK3PXP").decode()
        with caplog.at_level(logging.ERROR, logger="security.totp_crypto"):
            out = totp_crypto.decrypt_secret(token)
        assert out == "", f"raw ciphertext leaked back: {out[:40]!r}"
        assert out != token
        assert any(r.levelno >= logging.ERROR for r in caplog.records), "no ERROR logged"

        assert totp_crypto.decrypt_secret(BAD_CIPHERTEXT) == ""

    def test_decrypt_secret_empty_input(self):
        assert totp_crypto.decrypt_secret("") == ""
        assert totp_crypto.decrypt_secret(None) is None

    def test_pyotp_never_raises_on_decrypted_bad_secret(self):
        """The exact crash site: pyotp.TOTP(decrypt_secret(ct)).verify(code).

        Covers the UNWRAPPED call sites (server.py ~1427 / ~7401 withdrawal
        paths) which rely on decrypt_secret returning '' instead of ciphertext.
        """
        for value in (BAD_CIPHERTEXT, Fernet(Fernet.generate_key()).encrypt(b"X").decode()):
            secret = totp_crypto.decrypt_secret(value)
            assert secret == ""
            # must not raise binascii.Error
            assert pyotp.TOTP(secret).verify("123456", valid_window=3) is False
            assert pyotp.TOTP(secret).verify("000000", valid_window=1) is False


# ==================== unit: security/totp_handler.py ====================

class TestVerifyTotpCodeUnit:
    def test_empty_secret(self):
        assert verify_totp_code("", "123456") is False

    def test_non_base32_secret_does_not_raise(self):
        assert verify_totp_code("not-base32!!", "123456") is False
        assert verify_totp_code(BAD_CIPHERTEXT, "123456") is False

    def test_none_and_empty_code(self):
        secret = pyotp.random_base32()
        assert verify_totp_code(secret, "") is False
        assert verify_totp_code(secret, None) is False
        assert verify_totp_code(None, "123456") is False

    def test_valid_secret_and_current_code(self):
        secret = pyotp.random_base32()
        assert verify_totp_code(secret, _fresh_code(secret)) is True

    def test_valid_secret_wrong_code(self):
        secret = pyotp.random_base32()
        code = pyotp.TOTP(secret).now()
        wrong = "000000" if code != "000000" else "111111"
        assert verify_totp_code(secret, wrong) is False


# ==================== API: /api/auth/login-2fa ====================

class TestLogin2FAApi:
    def test_a_login_step1_requires_2fa(self, client, db):
        secret = pyotp.random_base32()
        _set_secret(db, secret)
        r = client.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": USER_LOGIN, "password": USER_PASSWORD},
            timeout=40,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"
        data = r.json()
        assert data.get("requires_2fa") is True, f"expected requires_2fa, got {data}"
        assert "token" not in data, "token must not be issued before 2FA"

    def test_b_valid_code_returns_token(self, client, db):
        secret = pyotp.random_base32()
        _set_secret(db, secret)
        r = _login_2fa(client, None, secret=secret)
        assert r.status_code != 500, f"REGRESSION 500 on valid code: {r.text[:500]}"
        assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"
        data = r.json()
        assert isinstance(data.get("token"), str) and len(data["token"]) > 20
        assert data.get("type") == "bearer"
        assert data["user"]["email"] == USER_EMAIL
        assert "_id" not in data.get("user", {}), "MongoDB _id leaked"

        # token must be usable
        me = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {data['token']}"},
            timeout=40,
        )
        assert me.status_code == 200, f"/auth/me {me.status_code} {me.text[:300]}"

    def test_c_wrong_code_returns_401(self, client, db):
        secret = pyotp.random_base32()
        _set_secret(db, secret)
        r = _login_2fa(client, "000000")
        assert r.status_code != 500, f"500 on wrong code: {r.text[:500]}"
        assert r.status_code == 401, f"expected 401 got {r.status_code} {r.text[:400]}"
        assert "2FA" in r.json().get("detail", ""), r.text[:300]
        _clear_lockout(db)

    def test_d_undecryptable_secret_returns_401_not_500(self, client, db):
        """CRITICAL REGRESSION: undecryptable ciphertext must degrade to 401."""
        _set_secret(db, BAD_CIPHERTEXT)
        for code in ("123456", "000000", pyotp.TOTP(pyotp.random_base32()).now()):
            r = _login_2fa(client, code)
            assert r.status_code != 500, (
                f"REGRESSION: 500 'internal error' with undecryptable secret "
                f"(code={code}): {r.text[:500]}"
            )
            assert r.status_code == 401, f"expected 401 got {r.status_code} {r.text[:400]}"
            assert "2FA" in r.json().get("detail", ""), r.text[:300]
            _clear_lockout(db)

    def test_e_undecryptable_secret_real_fernet_token(self, client, db):
        token = Fernet(Fernet.generate_key()).encrypt(pyotp.random_base32().encode()).decode()
        _set_secret(db, token)
        r = _login_2fa(client, "123456")
        assert r.status_code != 500, f"REGRESSION: 500 with real Fernet token: {r.text[:500]}"
        assert r.status_code == 401, f"expected 401 got {r.status_code} {r.text[:400]}"
        _clear_lockout(db)

    def test_f_missing_code_returns_400(self, client, db):
        _set_secret(db, pyotp.random_base32())
        r = _login_2fa(client, None)
        assert r.status_code != 500, f"500 on missing code: {r.text[:500]}"
        assert r.status_code == 400, f"expected 400 got {r.status_code} {r.text[:400]}"

    def test_g_wrong_password_returns_401(self, client, db):
        secret = pyotp.random_base32()
        _set_secret(db, secret)
        r = _login_2fa(client, None, secret=secret, password="definitely-wrong")
        assert r.status_code != 500, f"500 on wrong password: {r.text[:500]}"
        assert r.status_code == 401, f"expected 401 got {r.status_code} {r.text[:400]}"
        _clear_lockout(db)

    def test_h_login_step1_inline_totp_bad_secret_no_500(self, client, db):
        """/auth/login step-1 with a bad stored secret must not 500.

        NOTE: EmailLogin has no `totp_code` field, so the inline TOTP branch
        (auth_handler ~line 850) is unreachable — step-1 always answers
        requires_2fa. Assert only that nothing blows up.
        """
        _set_secret(db, BAD_CIPHERTEXT)
        r = client.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": USER_LOGIN, "password": USER_PASSWORD, "totp_code": "123456"},
            timeout=40,
        )
        assert r.status_code != 500, f"REGRESSION: 500 on /auth/login inline TOTP: {r.text[:500]}"
        assert r.status_code in (200, 401), f"unexpected {r.status_code} {r.text[:400]}"
        if r.status_code == 200:
            assert r.json().get("requires_2fa") is True
            assert "token" not in r.json()
        _clear_lockout(db)

    def test_i_valid_code_still_works_after_failures(self, client, db):
        secret = pyotp.random_base32()
        _set_secret(db, secret)
        r = _login_2fa(client, None, secret=secret)
        assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"
        assert "token" in r.json()


# ==================== API: admin login unaffected ====================

class TestAdminLogin:
    def test_admin_login_no_2fa(self, client):
        r = client.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
            timeout=40,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"
        data = r.json()
        assert isinstance(data.get("token"), str) and len(data["token"]) > 20


# ==================== API: admin 2FA gate with a bad secret ====================

class TestAdmin2FAGateBadSecret:
    """Admin2FAGateMiddleware / get_current_admin must answer 401 (not 500)
    when the admin's stored TOTP secret is undecryptable."""

    def test_admin_gate_returns_401_not_500(self, client, db):
        login = client.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
            timeout=40,
        )
        assert login.status_code == 200, f"admin login failed: {login.text[:300]}"
        token = login.json()["token"]
        hdr = {"Authorization": f"Bearer {token}"}

        original = db.users.find_one({"email": ADMIN_EMAIL}, {"_id": 0, "is_2fa_enabled": 1,
                                                              "two_factor_secret": 1})
        assert original is not None, "admin account not found"
        try:
            db.users.update_one(
                {"email": ADMIN_EMAIL},
                {"$set": {"two_factor_secret": BAD_CIPHERTEXT, "is_2fa_enabled": True}},
            )
            # Mutating admin request goes through the 2FA gate BEFORE routing,
            # so a non-existent probe path is safe (no data is touched).
            probe = f"{BASE_URL}/api/admin/__totp_gate_probe__"
            r = client.post(probe, json={}, headers=hdr, timeout=40)
            assert r.status_code != 500, f"REGRESSION: admin gate 500: {r.text[:400]}"
            assert r.status_code == 401, f"expected 401 got {r.status_code} {r.text[:300]}"
            assert "TOTP" in r.text

            r2 = client.post(probe, json={}, headers={**hdr, "X-Admin-TOTP": "123456"}, timeout=40)
            assert r2.status_code != 500, f"REGRESSION: admin gate 500 with code: {r2.text[:400]}"
            assert r2.status_code == 401, f"expected 401 got {r2.status_code} {r2.text[:300]}"
            assert "Invalid TOTP" in r2.text
        finally:
            unset = {}
            setter = {"is_2fa_enabled": bool(original.get("is_2fa_enabled", False))}
            if original.get("two_factor_secret"):
                setter["two_factor_secret"] = original["two_factor_secret"]
            else:
                unset["two_factor_secret"] = ""
            update = {"$set": setter}
            if unset:
                update["$unset"] = unset
            db.users.update_one({"email": ADMIN_EMAIL}, update)
            after = db.users.find_one({"email": ADMIN_EMAIL}, {"_id": 0, "is_2fa_enabled": 1,
                                                               "two_factor_secret": 1})
            assert after.get("is_2fa_enabled") == original.get("is_2fa_enabled", False)
            assert after.get("two_factor_secret") == original.get("two_factor_secret")
            # admin must still be able to log in normally
            back = client.post(
                f"{BASE_URL}/api/auth/login",
                json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                timeout=40,
            )
            assert back.status_code == 200 and "token" in back.json(), back.text[:300]
