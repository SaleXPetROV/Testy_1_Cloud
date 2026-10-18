"""Iteration 4: biometry SETUP must accept stale-but-validly-signed initData.

Covers:
  • /api/auth/login-2fa token acquisition for testuser@example.com
  • /api/security/telegram-biometry/register/verify-identity (live TOTP)
  • /api/security/telegram-biometry/register/finish with OLD auth_date -> 200
  • /register/finish with tampered hash -> 401 Invalid initData signature
  • /register/finish with fresh initData -> 200
  • /api/security/telegram-biometry/authenticate regression (no 500)
"""
import hashlib
import hmac
import json
import os
import time
import urllib.parse

import pyotp
import pytest
import requests
from dotenv import dotenv_values

_env = dotenv_values("/app/frontend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or _env.get("REACT_APP_BACKEND_URL")).rstrip("/")

_benv = dotenv_values("/app/backend/.env")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or _benv.get("TELEGRAM_BOT_TOKEN")

EMAIL = "testuser@example.com"
PASSWORD = "Test1234!"
TOTP_SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
TG_UID = 999000111


def build_init_data(age_seconds: int = 0, tamper: bool = False) -> str:
    user = json.dumps(
        {"id": TG_UID, "first_name": "Test", "username": "tester"}, separators=(",", ":")
    )
    auth_date = int(time.time()) - age_seconds
    pairs = {"auth_date": str(auth_date), "user": user, "query_id": "AAtest"}
    dcs = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    h = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    if tamper:
        first = h[0]
        h = ("0" if first != "0" else "1") + h[1:]
    return urllib.parse.urlencode({**pairs, "hash": h})


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def token(client):
    code = pyotp.TOTP(TOTP_SECRET).now()
    r = client.post(
        f"{BASE_URL}/api/auth/login-2fa",
        json={"email": EMAIL, "password": PASSWORD, "totp_code": code},
        timeout=45,
    )
    if r.status_code != 200:
        pytest.fail(f"login-2fa failed {r.status_code}: {r.text[:400]}")
    data = r.json()
    tok = data.get("access_token") or data.get("token")
    assert tok, f"no token in response: {data}"
    return tok


@pytest.fixture(scope="module")
def auth(token):
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    return s


def _challenge(auth):
    code = pyotp.TOTP(TOTP_SECRET).now()
    r = auth.post(
        f"{BASE_URL}/api/security/telegram-biometry/register/verify-identity",
        json={"totp_code": code},
        timeout=45,
    )
    assert r.status_code == 200, f"verify-identity {r.status_code}: {r.text[:400]}"
    body = r.json()
    assert body.get("ok") is True
    assert isinstance(body.get("setup_challenge"), str) and body["setup_challenge"]
    return body["setup_challenge"]


class TestBiometrySetupFreshness:
    def test_env_bot_token_present(self):
        assert BOT_TOKEN, "TELEGRAM_BOT_TOKEN missing in backend/.env"

    def test_status_endpoint(self, auth):
        r = auth.get(f"{BASE_URL}/api/security/telegram-biometry/status", timeout=30)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert "enabled" in d and "devices" in d
        assert "_id" not in json.dumps(d)

    def test_register_finish_old_initdata_accepted(self, auth):
        ch = _challenge(auth)
        r = auth.post(
            f"{BASE_URL}/api/security/telegram-biometry/register/finish",
            json={
                "setup_challenge": ch,
                "init_data": build_init_data(age_seconds=3600),
                "device_id": "TEST_device-1",
                "device_name": "Fingerprint",
            },
            timeout=45,
        )
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text[:400]}"
        d = r.json()
        assert d.get("ok") is True
        assert isinstance(d.get("biometric_token"), str) and len(d["biometric_token"]) > 10
        assert d.get("device_id") == "TEST_device-1"
        assert d.get("device_name") == "Fingerprint"
        # persistence check
        st = auth.get(f"{BASE_URL}/api/security/telegram-biometry/status", timeout=30).json()
        assert st["enabled"] is True
        assert any(x["device_id"] == "TEST_device-1" for x in st["devices"])
        # token hash must never be exposed
        assert "token_hash" not in json.dumps(st)

    def test_register_finish_tampered_signature_rejected(self, auth):
        ch = _challenge(auth)
        r = auth.post(
            f"{BASE_URL}/api/security/telegram-biometry/register/finish",
            json={
                "setup_challenge": ch,
                "init_data": build_init_data(age_seconds=3600, tamper=True),
                "device_id": "TEST_device-tamper",
                "device_name": "Bad",
            },
            timeout=45,
        )
        assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text[:300]}"
        assert "signature" in r.text.lower()

    def test_register_finish_fresh_initdata_accepted(self, auth):
        ch = _challenge(auth)
        r = auth.post(
            f"{BASE_URL}/api/security/telegram-biometry/register/finish",
            json={
                "setup_challenge": ch,
                "init_data": build_init_data(age_seconds=5),
                "device_id": "TEST_device-2",
                "device_name": "FaceID",
            },
            timeout=45,
        )
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text[:400]}"
        assert r.json().get("biometric_token")

    def test_authenticate_still_enforces_freshness(self, auth):
        # get a valid biometric token first (fresh setup)
        ch = _challenge(auth)
        reg = auth.post(
            f"{BASE_URL}/api/security/telegram-biometry/register/finish",
            json={
                "setup_challenge": ch,
                "init_data": build_init_data(age_seconds=5),
                "device_id": "TEST_device-3",
                "device_name": "Auth",
            },
            timeout=45,
        )
        assert reg.status_code == 200, reg.text[:300]
        bio = reg.json()["biometric_token"]

        old = auth.post(
            f"{BASE_URL}/api/security/telegram-biometry/authenticate",
            json={"token": bio, "init_data": build_init_data(age_seconds=3600)},
            timeout=45,
        )
        assert old.status_code != 500, f"500 on authenticate: {old.text[:300]}"
        assert old.status_code == 401, f"expected 401 old initData, got {old.status_code}: {old.text[:300]}"
        assert "too old" in old.text.lower()

        fresh = auth.post(
            f"{BASE_URL}/api/security/telegram-biometry/authenticate",
            json={"token": bio, "init_data": build_init_data(age_seconds=5)},
            timeout=45,
        )
        assert fresh.status_code == 200, f"expected 200, got {fresh.status_code}: {fresh.text[:300]}"
        assert fresh.json().get("withdraw_tg_biometry_token")

    def test_unauthenticated_finish_rejected(self, client):
        r = client.post(
            f"{BASE_URL}/api/security/telegram-biometry/register/finish",
            json={
                "setup_challenge": "x",
                "init_data": build_init_data(),
                "device_id": "TEST_noauth",
            },
            timeout=30,
        )
        assert r.status_code in (401, 403), f"got {r.status_code}: {r.text[:200]}"

    def test_cleanup_devices(self, auth):
        for dev in ["TEST_device-1", "TEST_device-2", "TEST_device-3"]:
            r = auth.post(
                f"{BASE_URL}/api/security/telegram-biometry/delete",
                json={"device_id": dev},
                timeout=30,
            )
            assert r.status_code in (200, 404), f"{dev}: {r.status_code} {r.text[:200]}"
