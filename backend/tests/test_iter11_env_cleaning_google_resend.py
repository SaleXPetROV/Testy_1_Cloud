"""Iteration 11 — env-value cleaning hardening.

PRIMARY:
  * auth_handler._clean_env strips whitespace + surrounding quotes (Google
    'invalid_client' root cause when .env has stray quotes/newlines).
  * email_service._clean strips whitespace + surrounding quotes for
    RESEND_API_KEY / SENDER_EMAIL.
  * Google /auth/google/callback still surfaces Google's real reason as 401.
  * Resend invalid key -> code-email endpoints must NOT 500.

REGRESSIONS: ton_proof walletbot allowlist, TON manifest, Telegram miniapp.
"""
import os
import sys
import uuid

import pytest
import requests
from dotenv import dotenv_values

sys.path.insert(0, "/app/backend")
sys.path.insert(0, "/app/backend/tests")

_fe = dotenv_values("/app/frontend/.env")
_base = os.environ.get("REACT_APP_BACKEND_URL") or _fe.get("REACT_APP_BACKEND_URL")
if not _base:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = _base.rstrip("/")
API = f"{BASE_URL}/api"
TIMEOUT = 45


# ─────────────── UNIT: auth_handler._clean_env ───────────────
class TestGoogleEnvCleaning:
    def _helper(self):
        import auth_handler
        return auth_handler._clean_env

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ('"abc"', "abc"),
            ("'abc'", "abc"),
            (" abc \n", "abc"),
            ('"  abc  "', "abc"),
            ("\n'my-client-id.apps.googleusercontent.com'\n", "my-client-id.apps.googleusercontent.com"),
            ("plain", "plain"),
            ('"unbalanced', '"unbalanced'),
            ("", ""),
        ],
    )
    def test_clean_env_variants(self, monkeypatch, raw, expected):
        clean = self._helper()
        monkeypatch.setenv("ITER11_TEST_VAR", raw)
        assert clean("ITER11_TEST_VAR") == expected

    def test_clean_env_missing_var(self, monkeypatch):
        clean = self._helper()
        monkeypatch.delenv("ITER11_MISSING_VAR", raising=False)
        assert clean("ITER11_MISSING_VAR") == ""

    def test_module_level_google_id_is_clean(self):
        import auth_handler
        cid = auth_handler.GOOGLE_CLIENT_ID
        assert cid == cid.strip(), repr(cid)
        assert not (cid[:1] in ("'", '"')), repr(cid)
        sec = auth_handler.GOOGLE_CLIENT_SECRET
        assert sec == sec.strip(), "GOOGLE_CLIENT_SECRET not stripped"

    def test_callback_rereads_env_fresh(self, monkeypatch):
        """google_oauth_callback must re-read via _clean_env (not the frozen
        import-time value) — verified by source inspection of the function."""
        import inspect

        import auth_handler
        src = inspect.getsource(auth_handler.google_oauth_callback)
        assert 'GOOGLE_CLIENT_ID = _clean_env("GOOGLE_CLIENT_ID")' in src, src[:500]
        assert 'GOOGLE_CLIENT_SECRET = _clean_env("GOOGLE_CLIENT_SECRET")' in src


# ─────────────── UNIT: email_service._clean ───────────────
class TestResendEnvCleaning:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ('"re_x"', "re_x"),
            ("  re_y  ", "re_y"),
            ("'re_z'", "re_z"),
            ("re_plain\n", "re_plain"),
            ('"Support <a@b.com>"', "Support <a@b.com>"),
            ("", ""),
            (None, ""),
        ],
    )
    def test_clean_variants(self, raw, expected):
        import email_service
        assert email_service._clean(raw) == expected

    def test_module_values_clean(self):
        import email_service
        assert email_service.RESEND_API_KEY == email_service.RESEND_API_KEY.strip()
        assert email_service.RESEND_API_KEY[:1] not in ("'", '"')
        assert email_service.SENDER_EMAIL == email_service.SENDER_EMAIL.strip()
        assert email_service.SENDER_EMAIL[:1] not in ("'", '"')


# ─────────────── Google callback HTTP behaviour ───────────────
class TestGoogleCallbackHTTP:
    def test_invalid_client_surfaced_as_401(self):
        r = requests.post(
            f"{API}/auth/google/callback",
            json={"code": "fake_iter11", "redirect_uri": f"{BASE_URL}/auth/google/callback"},
            timeout=TIMEOUT,
        )
        assert r.status_code == 401, f"{r.status_code}: {r.text[:400]}"
        detail = r.json().get("detail", "")
        assert detail.startswith("Failed to exchange authorization code with Google:"), detail
        assert "invalid_client" in detail, detail
        assert "Auth error" not in detail, detail

    def test_foreign_redirect_uri_400(self):
        r = requests.post(
            f"{API}/auth/google/callback",
            json={"code": "fake_iter11", "redirect_uri": "https://evil.com/auth/google/callback"},
            timeout=TIMEOUT,
        )
        assert r.status_code == 400, f"{r.status_code}: {r.text[:300]}"
        assert "Invalid redirect_uri" in r.json().get("detail", ""), r.text[:300]


# ─────────────── Resend graceful failure (no 500) ───────────────
class TestEmailEndpointsGraceful:
    def test_request_password_reset_unknown_email_no_500(self):
        r = requests.post(
            f"{API}/auth/request-password-reset",
            json={"email": f"TEST_iter11_{uuid.uuid4().hex[:8]}@example.com"},
            timeout=TIMEOUT,
        )
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        assert r.json().get("status") == "success", r.json()

    def test_register_initiate_invalid_resend_no_500(self, tmp_path):
        """Invalid Resend key must not crash registration initiate."""
        suffix = uuid.uuid4().hex[:8]
        email = f"TEST_iter11_{suffix}@example.com"
        username = f"TESTi11{suffix}"
        r = requests.post(
            f"{API}/auth/register/initiate",
            json={
                "email": email,
                "username": username,
                "password": "Str0ng!Passw0rd#2026",
            },
            timeout=TIMEOUT,
        )
        assert r.status_code < 500, f"{r.status_code}: {r.text[:400]}"
        print(f"register/initiate -> {r.status_code}: {r.text[:200]}")
        # cleanup any user created by the dev fallback path
        try:
            import asyncio

            from motor.motor_asyncio import AsyncIOMotorClient

            async def _rm():
                cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
                await cli[os.environ["DB_NAME"]].users.delete_many({"email": email})
                cli.close()

            asyncio.run(_rm())
        except Exception as e:  # pragma: no cover
            print(f"cleanup skipped: {e}")

    def test_send_email_via_resend_invalid_key_returns_false(self, monkeypatch):
        """Invalid Resend API key -> returns False, never raises (real Resend call)."""
        import asyncio

        import resend

        import email_service
        monkeypatch.setattr(email_service, "RESEND_AVAILABLE", True, raising=False)
        monkeypatch.setattr(email_service, "RESEND_API_KEY", "re_invalid_iter11_key", raising=False)
        old = getattr(resend, "api_key", None)
        resend.api_key = "re_invalid_iter11_key"
        try:
            ok = asyncio.run(email_service.send_email_via_resend(
                "TEST_iter11@example.com", "TEST subject", "<b>code 123456</b>"))
        finally:
            resend.api_key = old
        assert ok is False, "invalid Resend key should yield False, not True"

    def test_send_email_with_code_async_no_raise(self):
        """Code-email helper must swallow provider failures (returns bool)."""
        import asyncio

        import email_service
        res = asyncio.run(email_service.send_email_with_code_async(
            "TEST_iter11@example.com", "123456", "ru", "reset"))
        assert res in (True, False), res

    def test_server_still_up_after_email_attempts(self):
        r = requests.get(f"{API}/tonconnect-manifest-v3.json", timeout=TIMEOUT)
        assert r.status_code == 200, r.status_code


# ─────────────── REGRESSIONS ───────────────
class TestTonProofRegression:
    def test_walletbot_allowlist(self, monkeypatch):
        from core.ton_proof import _domain_allowed, _get_allowed_domains
        monkeypatch.setenv("TON_PROOF_ALLOWED_DOMAINS", "gramcity.app")
        allowed = _get_allowed_domains()
        assert allowed >= {"walletbot.net", "*.walletbot.net", "gramcity.app"}, allowed
        assert _domain_allowed("proxy.walletbot.net", allowed) is True
        assert _domain_allowed("evil.com", allowed) is False
        assert _domain_allowed("gramcity.games", allowed) is False

    def test_manifest_origin_and_icon(self):
        r = requests.get(f"{API}/tonconnect-manifest-v3.json", timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:300]
        m = r.json()
        assert m["url"] == BASE_URL, m
        assert m["iconUrl"] == f"{BASE_URL}/tonconnect-icon-v2.png", m
        icon = requests.get(m["iconUrl"], timeout=TIMEOUT)
        assert icon.status_code == 200, icon.status_code


from test_tg_miniapp_auth_resilience_iter_current import build_init_data, cleanup_tg  # noqa: E402


class TestTelegramRegression:
    TG_ID = 911100011

    @pytest.fixture(scope="class", autouse=True)
    def _cleanup(self):
        cleanup_tg(self.TG_ID)
        yield
        cleanup_tg(self.TG_ID)

    def test_valid_init_data_choice_required(self):
        init = build_init_data(self.TG_ID, first_name="Iter11", username="iter11_user")
        r = requests.post(f"{API}/auth/telegram/miniapp", json={"init_data": init}, timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:300]
        assert r.json().get("status") == "choice_required", r.json()

    def test_tampered_init_data_rejected(self):
        init = build_init_data(self.TG_ID, first_name="Iter11", username="iter11_user")
        r = requests.post(f"{API}/auth/telegram/miniapp", json={"init_data": init[:-4] + "dead"},
                          timeout=TIMEOUT)
        assert r.status_code in (400, 401), f"{r.status_code}: {r.text[:300]}"
