"""Iteration 12 — LIVE Resend send verification through real API endpoints + quick regressions.

Modules covered:
  * email_service: _clean env values, send_email_via_resend, send_email_with_code_async (live valid key)
  * auth_handler POST /api/auth/register/initiate       (verification code email -> Resend)
  * auth_handler POST /api/auth/request-password-reset   (reset code email -> Resend)
  * Regressions: Google callback error surfacing, ton_proof allowlist, TON manifest, Telegram miniapp
"""
import asyncio
import glob
import importlib
import os
import subprocess
import sys
import time
import uuid

import pytest
import requests
from dotenv import dotenv_values, load_dotenv

sys.path.insert(0, "/app/backend")
sys.path.insert(0, "/app/backend/tests")
load_dotenv("/app/backend/.env", override=True)

frontend_env = dotenv_values("/app/frontend/.env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = base_url.rstrip("/")
API = f"{BASE_URL}/api"
TIMEOUT = 40
LOG_GLOB = "/var/log/supervisor/backend.*.log"
SINK = "delivered@resend.dev"


def log_offsets() -> dict:
    """Snapshot current byte size of each backend log file."""
    out = {}
    for path in sorted(glob.glob(LOG_GLOB)):
        try:
            out[path] = os.path.getsize(path)
        except OSError:
            out[path] = 0
    return out


def log_delta(offsets: dict) -> str:
    """Read only the content appended to each log file since the snapshot."""
    chunks = []
    for path in sorted(glob.glob(LOG_GLOB)):
        start = offsets.get(path, 0)
        try:
            with open(path, "rb") as fh:
                fh.seek(max(0, start - 500))
                chunks.append(fh.read().decode("utf-8", "replace"))
        except OSError:
            continue
    return "\n".join(chunks)


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ─────────────── email_service unit-level with the LIVE valid key ───────────────
class TestEmailServiceLive:
    def test_env_values_loaded_and_cleaned(self):
        import email_service
        importlib.reload(email_service)
        assert email_service.RESEND_AVAILABLE is True
        assert email_service.RESEND_API_KEY.startswith("re_"), email_service.RESEND_API_KEY[:6]
        assert '"' not in email_service.RESEND_API_KEY and "'" not in email_service.RESEND_API_KEY
        assert email_service.SENDER_EMAIL == "Support GRAM CITY <noreply@gramcity.app>", \
            email_service.SENDER_EMAIL

    def test_send_email_via_resend_returns_true(self):
        import email_service
        ok = asyncio.run(email_service.send_email_via_resend(
            SINK, "TEST_ iter12 direct", "<p>iter12 direct</p>"))
        assert ok is True

    def test_send_email_with_code_async_returns_true(self):
        import email_service
        ok = asyncio.run(email_service.send_email_with_code_async(
            SINK, "654321", "en", "verification"))
        assert ok is True, "send_email_with_code_async must return True with a valid Resend key"

    def test_bad_key_graceful_false_no_raise(self, monkeypatch):
        """Regression: a bad key must return False and never raise (so endpoints can't 500)."""
        import resend

        import email_service
        monkeypatch.setattr(email_service, "RESEND_API_KEY", "re_invalid_iter12_key", raising=False)
        old = getattr(resend, "api_key", None)
        resend.api_key = "re_invalid_iter12_key"
        try:
            res = asyncio.run(email_service.send_email_via_resend(
                SINK, "TEST_ iter12 badkey", "<p>x</p>"))
        finally:
            resend.api_key = old
        assert res is False


# ─────────────── real endpoints must reach Resend successfully ───────────────
class TestEndpointsSendViaResend:
    def test_register_initiate_sends_via_resend(self, client):
        uniq = uuid.uuid4().hex[:8]
        email = f"delivered+gc{uniq}@resend.dev"
        username = f"TESTiter12{uniq[:6]}"
        before = log_offsets()
        r = client.post(f"{API}/auth/register/initiate", json={
            "email": email,
            "username": username,
            "password": "Str0ng!Passw0rd#2026",
        }, timeout=TIMEOUT)
        print("register/initiate ->", r.status_code, r.text[:300])
        assert r.status_code < 500, f"5xx: {r.text[:400]}"
        assert r.status_code == 200, r.text[:400]

        time.sleep(3)
        tail = log_delta(before)
        assert f"Email sent via Resend to {email}" in tail, \
            "no Resend success line; delta:\n" + tail[-2500:]
        assert "SMTP credentials not configured and Resend unavailable" not in tail

    def test_register_initiate_success_does_not_autocreate_user(self, client):
        """With a working Resend key the dev fallback (auto-active user) must NOT run."""
        uniq = uuid.uuid4().hex[:8]
        email = f"delivered+nc{uniq}@resend.dev"
        r = client.post(f"{API}/auth/register/initiate", json={
            "email": email,
            "username": f"TESTiter12n{uniq[:5]}",
            "password": "Str0ng!Passw0rd#2026",
        }, timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:300]
        out = subprocess.run([sys.executable, "/app/backend/tests/_iter12_count_user.py", email],
                             capture_output=True, text=True)
        print("db count:", out.stdout.strip(), out.stderr[-200:])
        assert "COUNT=0" in out.stdout, f"user auto-created despite successful email: {out.stdout}"

    def test_request_password_reset_sends_via_resend(self, client):
        uniq = uuid.uuid4().hex[:8]
        email = f"delivered+rst{uniq}@resend.dev"
        username = f"TESTiter12r{uniq[:5]}"
        seed = subprocess.run(
            [sys.executable, "/app/backend/tests/_iter12_seed_user.py", "create", email, username],
            capture_output=True, text=True)
        assert "OK created" in seed.stdout, seed.stdout + seed.stderr

        before = log_offsets()
        r = client.post(f"{API}/auth/request-password-reset", json={"email": email}, timeout=TIMEOUT)
        print("request-password-reset ->", r.status_code, r.text[:200])
        assert r.status_code == 200, r.text[:400]
        assert r.json().get("message") == "code_sent", r.json()

        time.sleep(3)
        tail = log_delta(before)
        assert f"Email sent via Resend to {email}" in tail, \
            "no Resend success line for password reset; delta:\n" + tail[-2500:]
        assert "SMTP credentials not configured and Resend unavailable" not in tail

    def test_server_healthy_after_sends(self, client):
        r = client.get(f"{API}/tonconnect-manifest-v3.json", timeout=TIMEOUT)
        assert r.status_code == 200


# ─────────────── quick regressions ───────────────
class TestGoogleRegression:
    def test_same_origin_401_invalid_client(self, client):
        r = client.post(f"{API}/auth/google/callback", json={
            "code": "fake_code_iter12",
            "redirect_uri": f"{BASE_URL}/auth/google/callback",
        }, timeout=TIMEOUT)
        print("google same-origin:", r.status_code, r.text[:300])
        assert r.status_code == 401, f"{r.status_code}: {r.text[:400]}"
        assert "invalid_client" in r.text, r.text[:400]

    def test_foreign_origin_400(self, client):
        r = client.post(f"{API}/auth/google/callback", json={
            "code": "fake_code_iter12",
            "redirect_uri": "https://evil.com/auth/google/callback",
        }, timeout=TIMEOUT)
        assert r.status_code == 400, f"{r.status_code}: {r.text[:400]}"


class TestTonProofRegression:
    def test_walletbot_allowlist(self, monkeypatch):
        from core.ton_proof import _domain_allowed, _get_allowed_domains
        monkeypatch.setenv("TON_PROOF_ALLOWED_DOMAINS", "gramcity.app")
        allowed = _get_allowed_domains()
        assert _domain_allowed("proxy.walletbot.net", allowed) is True
        assert _domain_allowed("evil.com", allowed) is False

    def test_manifest_origin_and_icon(self, client):
        r = client.get(f"{API}/tonconnect-manifest-v3.json", timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:300]
        m = r.json()
        assert m["url"] == BASE_URL, m
        assert m["iconUrl"] == f"{BASE_URL}/tonconnect-icon-v2.png", m


from test_tg_miniapp_auth_resilience_iter_current import build_init_data, cleanup_tg  # noqa: E402


class TestTelegramRegression:
    TG_ID = 911100012

    @pytest.fixture(scope="class", autouse=True)
    def _cleanup(self):
        cleanup_tg(self.TG_ID)
        yield
        cleanup_tg(self.TG_ID)

    def test_valid_init_data_choice_required(self, client):
        init = build_init_data(self.TG_ID, first_name="Iter12", username="iter12_user")
        r = client.post(f"{API}/auth/telegram/miniapp", json={"init_data": init}, timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:300]
        assert r.json().get("status") == "choice_required", r.json()

    def test_tampered_init_data_rejected(self, client):
        init = build_init_data(self.TG_ID, first_name="Iter12", username="iter12_user")
        r = client.post(f"{API}/auth/telegram/miniapp", json={"init_data": init[:-4] + "dead"},
                        timeout=TIMEOUT)
        assert r.status_code in (400, 401), f"{r.status_code}: {r.text[:300]}"


# ─────────────── cleanup ───────────────
def test_zz_cleanup_test_users():
    out = subprocess.run([sys.executable, "/app/backend/tests/_iter12_seed_user.py", "cleanup"],
                         capture_output=True, text=True)
    print(out.stdout[-500:], out.stderr[-300:])
    assert "CLEANUP_OK" in out.stdout
