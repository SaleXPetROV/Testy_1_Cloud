"""Iteration 3 — Google OAuth 'invalid_client' RCA + hardening verification.

Verifies:
  (a) The backend's currently-configured GOOGLE_CLIENT_ID/SECRET are VALID by
      probing Google's token endpoint directly. Google must respond with
      'invalid_grant' (fake code) NOT 'invalid_client'. That proves the pair
      is registered with Google.
  (b) auth_handler._clean_env hardening: strips whitespace + quotes AND
      collapses ALL internal whitespace (repairs a wrapped/multi-line paste).
  (c) auth_handler._mask_secret: masks (never leaks) a secret, '<empty>' for
      empty input.
  (d) POST /api/auth/google/init returns 200 with state + code_challenge (PKCE).
  (e) POST /api/auth/google/callback with a FRESH state + fake code +
      redirect_uri on the app's own origin surfaces Google's real reason
      (detail contains 'invalid_grant', NOT 'invalid_client', NOT 503).
"""
import os
import sys

import httpx
import pytest
import requests
from dotenv import dotenv_values

sys.path.insert(0, "/app/backend")

# Load backend env so GOOGLE_CLIENT_ID/SECRET are available for the
# direct-Google probe (auth_handler._clean_env reads os.environ).
_be = dotenv_values("/app/backend/.env")
for _k, _v in _be.items():
    if _v is not None and not os.environ.get(_k):
        os.environ[_k] = _v

_fe = dotenv_values("/app/frontend/.env")
_base = os.environ.get("REACT_APP_BACKEND_URL") or _fe.get("REACT_APP_BACKEND_URL")
if not _base:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = _base.rstrip("/")
API = f"{BASE_URL}/api"
TIMEOUT = 45


# ─────────────────────────────────────────────────────────────
# (a) Direct Google token-endpoint probe — proves creds are VALID
# ─────────────────────────────────────────────────────────────
class TestGoogleCredentialsAreValid:
    def test_direct_google_probe_returns_invalid_grant_not_invalid_client(self):
        """Hit https://oauth2.googleapis.com/token directly with the backend's
        client_id/secret and a fake code. If the client_id/secret pair exists
        in Google, Google returns 'invalid_grant' (malformed auth code). If
        the pair does NOT exist, Google returns 'invalid_client'."""
        import auth_handler
        cid = auth_handler._clean_env("GOOGLE_CLIENT_ID")
        csec = auth_handler._clean_env("GOOGLE_CLIENT_SECRET")
        assert cid, "GOOGLE_CLIENT_ID missing in backend/.env"
        assert csec, "GOOGLE_CLIENT_SECRET missing in backend/.env"
        r = httpx.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": "fake_iter3_probe_code",
                "client_id": cid,
                "client_secret": csec,
                "redirect_uri": "https://gramcity.app/auth/google/callback",
                "grant_type": "authorization_code",
            },
            timeout=TIMEOUT,
        )
        body = r.json()
        err = str(body.get("error", ""))
        print(f"Google direct probe -> {r.status_code} {body}")
        # If Google says 'invalid_client', the deployed creds are wrong.
        assert err != "invalid_client", (
            "Google returned 'invalid_client' — backend GOOGLE_CLIENT_ID/SECRET "
            f"NOT recognized by Google. body={body}"
        )
        assert err != "unauthorized_client", body
        # Fake code -> Google should return invalid_grant on a valid client.
        assert err == "invalid_grant", (
            f"Expected 'invalid_grant' from Google (creds valid, code fake); "
            f"got error={err!r}. body={body}"
        )


# ─────────────────────────────────────────────────────────────
# (b) _clean_env hardening (unit)
# ─────────────────────────────────────────────────────────────
class TestCleanEnvHardening:
    def _clean(self):
        import auth_handler
        return auth_handler._clean_env

    def test_wrapped_multiline_client_id_collapses(self, monkeypatch):
        raw = (
            "179436368222-00gs0egn408voihsp03b\n"
            "m6nmlk2vd7sk.apps.googleusercontent.com"
        )
        monkeypatch.setenv("ITER3_TEST_CID", raw)
        got = self._clean()("ITER3_TEST_CID")
        assert got == (
            "179436368222-00gs0egn408voihsp03bm6nmlk2vd7sk"
            ".apps.googleusercontent.com"
        ), repr(got)
        # no whitespace anywhere in result
        assert not any(c.isspace() for c in got), repr(got)

    def test_wrapped_with_quotes_and_spaces(self, monkeypatch):
        raw = '  "179436368222-abc\n def.apps.googleusercontent.com"  '
        monkeypatch.setenv("ITER3_TEST_CID_Q", raw)
        got = self._clean()("ITER3_TEST_CID_Q")
        assert got == "179436368222-abcdef.apps.googleusercontent.com", repr(got)

    def test_trailing_tab_and_space(self, monkeypatch):
        monkeypatch.setenv("ITER3_TEST_TAB", "abc123\t ")
        assert self._clean()("ITER3_TEST_TAB") == "abc123"

    def test_leading_and_trailing_newlines(self, monkeypatch):
        monkeypatch.setenv("ITER3_TEST_NL", "\n\nabc123\n")
        assert self._clean()("ITER3_TEST_NL") == "abc123"

    def test_empty_and_missing(self, monkeypatch):
        monkeypatch.setenv("ITER3_TEST_EMPTY", "")
        assert self._clean()("ITER3_TEST_EMPTY") == ""
        monkeypatch.delenv("ITER3_TEST_MISSING", raising=False)
        assert self._clean()("ITER3_TEST_MISSING") == ""


# ─────────────────────────────────────────────────────────────
# (c) _mask_secret helper — never leaks
# ─────────────────────────────────────────────────────────────
class TestMaskSecret:
    def _mask(self):
        import auth_handler
        return auth_handler._mask_secret

    def test_empty_returns_placeholder(self):
        assert self._mask()("") == "<empty>"
        assert self._mask()(None) == "<empty>"  # type: ignore[arg-type]

    def test_long_secret_masked(self):
        s = "GOCSPX-abcdefghijklmnopqrstuvwxyz0123"
        out = self._mask()(s)
        # Full secret must NOT appear in the mask.
        assert s not in out, out
        # Must include length marker.
        assert f"len={len(s)}" in out, out
        # First 8 chars visible, last 4 visible.
        assert out.startswith(s[:8]), out
        assert s[-4:] in out, out

    def test_short_secret_not_fully_leaked(self):
        s = "short"
        out = self._mask()(s)
        assert s not in out, out
        assert "5 chars" in out, out


# ─────────────────────────────────────────────────────────────
# (d) /api/auth/google/init
# ─────────────────────────────────────────────────────────────
class TestGoogleInit:
    def test_init_returns_state_and_pkce_challenge(self):
        r = requests.post(f"{API}/auth/google/init", timeout=TIMEOUT)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        body = r.json()
        assert isinstance(body.get("state"), str) and len(body["state"]) >= 20, body
        assert isinstance(body.get("code_challenge"), str) and len(body["code_challenge"]) >= 20, body
        assert body.get("code_challenge_method") == "S256", body


# ─────────────────────────────────────────────────────────────
# (e) /api/auth/google/callback surfaces Google's real reason
# ─────────────────────────────────────────────────────────────
class TestGoogleCallbackSurfacesRealReason:
    def test_callback_with_fresh_state_and_fake_code_returns_invalid_grant(self):
        # 1. get a fresh state (so we pass the state check → reach Google)
        init = requests.post(f"{API}/auth/google/init", timeout=TIMEOUT)
        assert init.status_code == 200, init.text[:300]
        state = init.json()["state"]

        # 2. call callback with fake code + preview-origin redirect_uri
        redirect_uri = f"{BASE_URL}/auth/google/callback"
        r = requests.post(
            f"{API}/auth/google/callback",
            json={"code": "fake_iter3_bad_code", "state": state, "redirect_uri": redirect_uri},
            timeout=TIMEOUT,
        )
        print(f"callback -> {r.status_code}: {r.text[:400]}")
        # MUST reach Google (not 503 "not configured") — creds are set.
        assert r.status_code != 503, (
            f"backend reports 'not configured' — GOOGLE_CLIENT_ID likely empty. body={r.text[:300]}"
        )
        # MUST NOT be 400 Invalid redirect_uri — preview origin is whitelisted.
        assert r.status_code != 400 or "Invalid redirect_uri" not in r.text, (
            f"redirect_uri whitelist rejected the preview origin: {r.text[:300]}"
        )
        assert r.status_code == 401, f"{r.status_code}: {r.text[:400]}"
        detail = r.json().get("detail", "")
        # Detail should surface Google's real reason.
        assert detail.startswith("Failed to exchange authorization code with Google:"), detail
        # KEY assertion: 'invalid_grant' (fake code), NOT 'invalid_client'.
        assert "invalid_client" not in detail, (
            "Detail contains 'invalid_client' — backend creds NOT recognized by Google. "
            f"detail={detail!r}"
        )
        assert "unauthorized_client" not in detail, detail
        assert "invalid_grant" in detail, (
            f"Expected 'invalid_grant' from Google (creds valid, code fake); "
            f"got detail={detail!r}"
        )
