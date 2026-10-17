"""Iteration 9 — verify the `except HTTPException: raise` guard in google_callback.

Primary production bug: the generic `except Exception` in
auth_handler.google_callback re-wrapped the explicit HTTPException(401,
"Failed to exchange authorization code with Google: ...") into
HTTP 500 "Auth error: 401: ...".

Covers:
  * POST /api/auth/google/callback -> clean 401 with Google's real reason
  * redirect_uri whitelist guard -> 400 Invalid redirect_uri (not 500)
  * bogus state -> 400 Invalid or expired OAuth state (not 500)
  * POST /api/auth/google/init -> 200 state + PKCE challenge
"""
import os

import pytest
import requests
from dotenv import dotenv_values

_fe = dotenv_values("/app/frontend/.env")
_base = os.environ.get("REACT_APP_BACKEND_URL") or _fe.get("REACT_APP_BACKEND_URL")
if not _base:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = _base.rstrip("/")
API = f"{BASE_URL}/api"
VALID_REDIRECT = f"{BASE_URL}/auth/google/callback"
TIMEOUT = 45


# ---------- /api/auth/google/init ----------
class TestGoogleInit:
    def test_init_returns_state_and_pkce(self):
        r = requests.post(f"{API}/auth/google/init", json={}, timeout=TIMEOUT)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        d = r.json()
        assert isinstance(d.get("state"), str) and len(d["state"]) > 16, d
        assert isinstance(d.get("code_challenge"), str) and len(d["code_challenge"]) > 16, d
        assert d.get("code_challenge_method") == "S256", d

    def test_init_state_is_unique(self):
        s1 = requests.post(f"{API}/auth/google/init", json={}, timeout=TIMEOUT).json()["state"]
        s2 = requests.post(f"{API}/auth/google/init", json={}, timeout=TIMEOUT).json()["state"]
        assert s1 != s2


# ---------- primary: 401 not 500 ----------
class TestGoogleCallbackHttpExceptionGuard:
    @pytest.fixture(scope="class")
    def resp(self):
        return requests.post(
            f"{API}/auth/google/callback",
            json={"code": "fake_code_iter9", "redirect_uri": VALID_REDIRECT},
            timeout=TIMEOUT,
        )

    def test_status_is_401_not_500(self, resp):
        assert resp.status_code == 401, f"expected 401, got {resp.status_code}: {resp.text[:400]}"

    def test_detail_not_wrapped_as_auth_error(self, resp):
        detail = resp.json().get("detail", "")
        assert not detail.startswith("Auth error"), detail
        assert "Auth error: 401" not in detail, detail

    def test_detail_prefix_and_google_reason(self, resp):
        detail = resp.json().get("detail", "")
        assert detail.startswith("Failed to exchange authorization code with Google:"), detail
        assert "invalid_client" in detail, detail

    def test_repeatable(self):
        for _ in range(2):
            r = requests.post(
                f"{API}/auth/google/callback",
                json={"code": "fake_code_iter9_rep", "redirect_uri": VALID_REDIRECT},
                timeout=TIMEOUT,
            )
            assert r.status_code == 401, f"{r.status_code}: {r.text[:300]}"


# ---------- guards still intact ----------
class TestGoogleCallbackGuards:
    def test_invalid_redirect_uri(self):
        r = requests.post(
            f"{API}/auth/google/callback",
            json={"code": "x", "redirect_uri": "https://evil.com/auth/google/callback"},
            timeout=TIMEOUT,
        )
        assert r.status_code == 400, f"{r.status_code}: {r.text[:300]}"
        assert "Invalid redirect_uri" in r.json().get("detail", "")

    def test_bogus_state_rejected_400(self):
        r = requests.post(
            f"{API}/auth/google/callback",
            json={"code": "x", "redirect_uri": VALID_REDIRECT, "state": "bogus-not-in-db"},
            timeout=TIMEOUT,
        )
        assert r.status_code == 400, f"{r.status_code}: {r.text[:400]}"
        assert "Invalid or expired OAuth state" in r.json().get("detail", "")

    def test_state_is_single_use(self):
        state = requests.post(f"{API}/auth/google/init", json={}, timeout=TIMEOUT).json()["state"]
        payload = {"code": "x", "redirect_uri": VALID_REDIRECT, "state": state}
        # first use: state valid -> proceeds to Google exchange -> 401 invalid_client
        r1 = requests.post(f"{API}/auth/google/callback", json=payload, timeout=TIMEOUT)
        assert r1.status_code == 401, f"first use {r1.status_code}: {r1.text[:300]}"
        # replay: state consumed -> 400
        r2 = requests.post(f"{API}/auth/google/callback", json=payload, timeout=TIMEOUT)
        assert r2.status_code == 400, f"replay {r2.status_code}: {r2.text[:300]}"
        assert "Invalid or expired OAuth state" in r2.json().get("detail", "")
