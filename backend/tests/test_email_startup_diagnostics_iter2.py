"""
Iteration 2 — Email startup diagnostics (secret-free) + password-reset regression.
Modules under test: backend/email_service.py (_sender_domain, email_startup_diagnostics),
backend/server.py startup_event wiring, POST /api/auth/request-password-reset.
"""
import os
import re
import sys
import time
import logging
import subprocess

import pytest
import requests
from dotenv import dotenv_values

sys.path.insert(0, "/app/backend")

# email_service reads env at import time; the backend loads .env before importing it.
from dotenv import load_dotenv  # noqa: E402
load_dotenv("/app/backend/.env")

frontend_env = dotenv_values("/app/frontend/.env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = base_url.rstrip("/")

BACKEND_LOG = "/var/log/supervisor/backend.err.log"


# ---------------------------------------------------------------- unit: _sender_domain
class TestSenderDomain:
    @pytest.mark.parametrize("raw,expected", [
        ("Support GRAM CITY <support@gramcity.app>", "gramcity.app"),
        ("support@gramcity.app", "gramcity.app"),
        ("Support GRAM CITY <support@gramcity.games>", "gramcity.games"),
        ("  Mixed CASE <Support@GramCity.APP>  ", "gramcity.app"),
        ("", ""),
        ("not-an-email", ""),
        (None, ""),
    ])
    def test_sender_domain_extraction(self, raw, expected):
        import email_service
        assert email_service._sender_domain(raw) == expected


# ---------------------------------------------------------------- unit: diagnostics log line
class TestStartupDiagnostics:
    def test_diagnostics_emits_infoline_no_warning_with_verified_domain(self, caplog):
        import email_service
        caplog.clear()
        with caplog.at_level(logging.INFO, logger="email_service"):
            email_service.email_startup_diagnostics()
        text = caplog.text
        assert "[email] startup:" in text
        for key in ("resend_installed=", "resend_key_set=", "sender=", "sender_domain=", "smtp_user_set="):
            assert key in text, f"missing {key}"
        # current preview config
        assert "sender_domain=gramcity.app" in text
        assert "UNVERIFIED" not in text
        # secret-free: no API key value leaked
        if email_service.RESEND_API_KEY:
            assert email_service.RESEND_API_KEY not in text

    def test_diagnostics_warns_on_unverified_fallback_sender(self, caplog, monkeypatch):
        import email_service
        monkeypatch.setattr(email_service, "SENDER_EMAIL",
                            "Support GRAM CITY <support@gramcity.games>")
        caplog.clear()
        with caplog.at_level(logging.INFO, logger="email_service"):
            email_service.email_startup_diagnostics()
        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert warnings, "expected a WARNING for unverified fallback domain"
        joined = " ".join(r.getMessage() for r in warnings)
        assert "UNVERIFIED" in joined
        assert "gramcity.games" in joined

    def test_diagnostics_warns_when_resend_key_empty(self, caplog, monkeypatch):
        import email_service
        monkeypatch.setattr(email_service, "RESEND_API_KEY", "")
        caplog.clear()
        with caplog.at_level(logging.INFO, logger="email_service"):
            email_service.email_startup_diagnostics()
        warnings = [(r.getMessage() % r.args if r.args else r.getMessage())
                    for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("RESEND_API_KEY is EMPTY" in w for w in warnings), warnings
        assert "resend_key_set=False" in caplog.text

    def test_startup_event_invokes_diagnostics(self):
        src = open("/app/backend/server.py", encoding="utf-8").read()
        assert "email_startup_diagnostics()" in src


# ---------------------------------------------------------------- log presence after restart
class TestBackendLogDiagnostic:
    def test_diagnostic_line_present_in_backend_log(self):
        assert os.path.exists(BACKEND_LOG), f"{BACKEND_LOG} missing"
        with open(BACKEND_LOG, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()[-4000:]
        hits = [ln for ln in lines if "[email] startup:" in ln]
        assert hits, "no '[email] startup:' diagnostic line found in backend.err.log"
        last = hits[-1]
        assert "sender_domain=gramcity.app" in last, last
        unverified = [ln for ln in lines if "UNVERIFIED" in ln]
        assert not unverified, f"unexpected UNVERIFIED warning: {unverified[-1:]}"


# ---------------------------------------------------------------- regression: password reset
class TestPasswordResetRegression:
    def test_reset_returns_generic_success_for_test_user(self):
        r = requests.post(f"{BASE_URL}/api/auth/request-password-reset",
                          json={"email": "testuser@example.com"}, timeout=45)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert data.get("status") == "success", data

    def test_reset_returns_generic_success_for_unknown_email(self):
        r = requests.post(f"{BASE_URL}/api/auth/request-password-reset",
                          json={"email": "TEST_nonexistent_qa@example.com"}, timeout=45)
        assert r.status_code == 200, r.text[:300]
        assert r.json().get("status") == "success"

    def test_reset_live_send_for_real_domain_recipient_logs_resend_sent(self, admin_email):
        marker = time.time()
        with open(BACKEND_LOG, encoding="utf-8", errors="replace") as fh:
            before = len(fh.readlines())
        r = requests.post(f"{BASE_URL}/api/auth/request-password-reset",
                          json={"email": admin_email}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        assert r.json().get("status") == "success"
        sent = None
        for _ in range(15):
            time.sleep(2)
            with open(BACKEND_LOG, encoding="utf-8", errors="replace") as fh:
                new = fh.readlines()[before:]
            hits = [ln for ln in new if "[email] Resend SENT" in ln]
            if hits:
                sent = hits[-1]
                break
        assert sent, "no '[email] Resend SENT' log after live reset request (marker=%s)" % marker
        assert re.search(r"id=\S+", sent), sent


@pytest.fixture(scope="session")
def admin_email():
    """Real-domain recipient: the current admin account email straight from Mongo
    (the seeded sanyanazarov212@gmail.com was changed to another gmail by an
    earlier iteration, so read it instead of hardcoding)."""
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient

    async def _get():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        doc = await db.users.find_one({"username": "sanyanazarov212"}, {"_id": 0, "email": 1})
        client.close()
        return (doc or {}).get("email")

    email = asyncio.get_event_loop().run_until_complete(_get()) if False else asyncio.run(_get())
    if not email or email.endswith("@example.com"):
        pytest.fail(f"admin account has no deliverable email: {email!r}")
    return email
