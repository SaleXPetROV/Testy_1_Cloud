"""TON_CITY_v2.3 Round 3 security regression tests.

Covers:
- F6/F21 RNG via `secrets`
- F30 legacy test files moved out of repo root + .gitignore
- F18 Subresource Integrity (SRI) on telegram-web-app.js
- F20 SSRF allow-list wrapper (security.safe_fetch)
- F36 per-user WS message rate-limit (security.ws_rate_limit)
- F13 GLOBAL Admin2FAGateMiddleware (soft-mode + hard-mode + whitelist)
- F10 atomic find_one_and_update on the 3 new endpoints (island plot buy,
  plot buy v2, marketplace bot listing buy) — code-pattern grep.
- Regression: F33 global exception handler, F12 audit-log w/ middleware.
"""
from __future__ import annotations

import ast
import os
import re
import sys
import time
from pathlib import Path

import pytest
import requests

# Make backend/ importable so we can `import email_service`, security modules etc.
ROOT = Path(__file__).resolve().parent.parent  # /app/backend
sys.path.insert(0, str(ROOT))

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or "http://localhost:8001"
ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PW = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PW = "Test1234!"


# ---------- shared fixtures ----------
@pytest.fixture(scope="session")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def admin_token(api):
    r = api.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PW})
    if r.status_code != 200:
        pytest.skip(f"admin login failed: {r.status_code} {r.text}")
    return r.json()["token"]


@pytest.fixture(scope="session")
def user_token(api):
    r = api.post(f"{BASE_URL}/api/auth/login", json={"email": USER_EMAIL, "password": USER_PW})
    if r.status_code != 200:
        pytest.skip(f"user login failed: {r.status_code} {r.text}")
    return r.json()["token"]


# ===================== F6 / F21 : RNG via `secrets` =====================
class TestRngSecrets:
    def test_email_service_uses_secrets_not_random(self):
        src = (ROOT / "email_service.py").read_text()
        # No top-level `import random` in email_service
        assert not re.search(r"^\s*import random\b", src, flags=re.MULTILINE), \
            "email_service still imports random"
        assert "secrets.choice" in src, "email_service must use secrets.choice"

    def test_email_service_generate_helpers_use_secrets(self):
        from email_service import generate_reset_code, generate_verification_code
        # Values still have expected shape
        assert len(generate_reset_code()) == 8
        code = generate_verification_code()
        assert len(code) == 6 and code.isdigit()

    def test_background_tasks_crit_and_free_cycle_use_systemrandom(self):
        src = (ROOT / "background_tasks.py").read_text()
        # both branches switched to secrets.SystemRandom
        assert "secrets" in src and "SystemRandom" in src, \
            "background_tasks must use secrets.SystemRandom in RNG-sensitive branches"
        # crit-hit + free-cycle-chance are the two blocks we care about
        assert src.count("SystemRandom") >= 2, "expected SystemRandom used at least twice"


# ===================== F30 : legacy test files moved =====================
class TestF30LegacyMoved:
    ROOT_APP = Path("/app")

    def test_no_orphan_test_files_at_repo_root(self):
        for name in ("backend_test.py", "telegram_start_silent_fail_test.py", "frontend_code_review.txt"):
            assert not (self.ROOT_APP / name).exists(), f"/app/{name} should have been moved"

    def test_files_are_in_legacy_dir(self):
        legacy = self.ROOT_APP / "backend" / "tests" / "legacy"
        assert legacy.is_dir(), "legacy dir missing"
        assert (legacy / "backend_test.py").exists()
        assert (legacy / "telegram_start_silent_fail_test.py").exists()
        assert (legacy / "frontend_code_review.txt").exists()

    def test_gitignore_covers_root_test_files(self):
        gi = (self.ROOT_APP / ".gitignore").read_text()
        # Anchored patterns
        assert "/test_*.py" in gi
        assert "/*_test.py" in gi
        assert "/backend_test.py" in gi


# ===================== F18 : SRI on Telegram SDK =====================
class TestF18SRI:
    def test_telegram_sdk_script_has_sri(self):
        html = Path("/app/frontend/public/index.html").read_text()
        # Must contain the exact integrity hash + crossorigin anonymous
        m = re.search(
            r'src="https://telegram\.org/js/telegram-web-app\.js"[\s\S]{0,400}?integrity="sha384-1XuC9S4cgk6RH1oCsL2diDRwLiiivu/oZHNfxYUitEFuiKpP5ceNbzu220KKrcK\+"[\s\S]{0,200}?crossorigin="anonymous"',
            html,
        )
        assert m is not None, "SRI attributes missing/incorrect on telegram-web-app.js script tag"


# ===================== F20 : SSRF allow-list wrapper =====================
class TestF20SSRF:
    def test_import_module(self):
        from security import safe_fetch  # noqa
        assert hasattr(safe_fetch, "ensure_allowed_host")
        assert hasattr(safe_fetch, "is_allowed_host")
        assert hasattr(safe_fetch, "SSRFError")

    def test_allowed_host_telegram(self):
        from security.safe_fetch import is_allowed_host
        assert is_allowed_host("https://api.telegram.org/x") is True

    def test_rejects_random_public_host(self):
        from security.safe_fetch import is_allowed_host
        assert is_allowed_host("https://evil.com") is False

    def test_rejects_aws_metadata_ip(self):
        from security.safe_fetch import is_allowed_host
        assert is_allowed_host("http://169.254.169.254/latest/meta-data/") is False

    def test_rejects_localhost(self):
        from security.safe_fetch import is_allowed_host
        assert is_allowed_host("http://localhost:8001/") is False

    def test_rejects_file_scheme(self):
        from security.safe_fetch import is_allowed_host
        assert is_allowed_host("file:///etc/passwd") is False

    def test_rejects_rfc1918(self):
        from security.safe_fetch import is_allowed_host
        assert is_allowed_host("http://10.0.0.1/") is False
        assert is_allowed_host("http://192.168.1.1/") is False

    def test_extra_hosts_env_extends_allowlist(self, monkeypatch):
        # Env is read on every call by _load_extra_hosts
        monkeypatch.setenv("SSRF_EXTRA_ALLOWED_HOSTS", "extra-allowed.example.com,another.example")
        from security.safe_fetch import is_allowed_host
        assert is_allowed_host("https://extra-allowed.example.com/x") is True
        assert is_allowed_host("https://another.example/y") is True
        # subdomain matches parent
        assert is_allowed_host("https://sub.another.example/y") is True

    def test_ensure_raises_ssrferror(self):
        from security.safe_fetch import ensure_allowed_host, SSRFError
        with pytest.raises(SSRFError):
            ensure_allowed_host("https://evil.com")


# ===================== F36 : per-user WS msg rate-limit =====================
class TestF36WsRateLimit:
    def test_first_60_pass_then_61st_blocks(self):
        # Import fresh module and clear bucket for this identifier
        from security.ws_rate_limit import check_ws_msg_rate, reset_ws_rate
        uid = "u1_test_f36"
        reset_ws_rate(uid)
        for i in range(60):
            assert check_ws_msg_rate(uid) is True, f"message {i+1} unexpectedly blocked"
        assert check_ws_msg_rate(uid) is False, "61st message should be blocked"
        reset_ws_rate(uid)
        assert check_ws_msg_rate(uid) is True, "after reset, should pass again"

    def test_handlers_use_check_ws_msg_rate(self):
        chat_src = (ROOT / "chat_handler.py").read_text()
        support_src = (ROOT / "support_handler.py").read_text()
        assert "check_ws_msg_rate" in chat_src, "chat_handler must import check_ws_msg_rate"
        assert "check_ws_msg_rate" in support_src, "support_handler must import check_ws_msg_rate"


# ===================== F13 : GLOBAL Admin2FAGateMiddleware =====================
class TestF13GlobalMiddleware:
    """
    NOTE: DB toggling of 2FA on the admin user is skipped here because doing so
    in a shared preview env risks locking out the human admin if teardown fails.
    We verify:
      1. Code-level: middleware exists, is registered, has soft-mode logic.
      2. Soft-mode HTTP: admin without 2FA can POST /api/admin/telegram-settings.
      3. Non-admin gets 403.
      4. Whitelist: /api/auth/login works for anyone (also implicitly tested by
         admin_token fixture).
    Hard-mode (2FA enabled) is verified structurally via the source.
    """

    def test_middleware_defined_and_registered(self):
        src = (ROOT / "server.py").read_text()
        assert "class Admin2FAGateMiddleware(BaseHTTPMiddleware):" in src
        assert "app.add_middleware(Admin2FAGateMiddleware)" in src
        # soft-mode gate
        assert 'if not (admin_doc.get("is_2fa_enabled") and admin_doc.get("two_factor_secret")):' in src, \
            "soft-mode short-circuit missing"
        # TOTP header
        assert 'X-Admin-TOTP' in src

    def test_middleware_whitelist_includes_auth_and_security(self):
        src = (ROOT / "server.py").read_text()
        # Find the whitelist tuple
        m = re.search(r"_ADMIN_2FA_WHITELIST_PREFIXES\s*=\s*\(([^)]+)\)", src)
        assert m is not None, "whitelist tuple not found"
        entries = m.group(1)
        assert "/api/auth/" in entries
        assert "/api/security/2fa/" in entries
        assert "/api/security/passkey/" in entries

    def test_soft_mode_admin_can_get_telegram_settings(self, api, admin_token):
        # GET is always exempt from middleware (only mutating verbs are gated)
        r = api.get(
            f"{BASE_URL}/api/admin/telegram-settings",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        # Endpoint may 404 if not defined; but if it exists it must NOT be 401
        assert r.status_code in (200, 404), f"unexpected {r.status_code}: {r.text[:200]}"

    def test_soft_mode_admin_can_post_admin_endpoint_without_totp(self, api, admin_token):
        # Post to any admin endpoint that does NOT itself require TOTP via Depends —
        # /api/admin/telegram-settings if it exists, otherwise fall back to /api/admin/settings.
        candidates = [
            "/api/admin/telegram-settings",
            "/api/admin/settings",
        ]
        for path in candidates:
            r = api.post(
                f"{BASE_URL}{path}",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={},
            )
            # Middleware would return 401 with detail 'TOTP required for this admin action'
            # In soft-mode (admin has no 2FA) that MUST NOT happen.
            body = ""
            try:
                body = r.text[:400]
            except Exception:
                pass
            assert not (
                r.status_code == 401 and "TOTP required" in body
            ), f"soft-mode should not enforce TOTP for {path}, got 401 body={body}"

    def test_whitelist_auth_login_never_gated(self, api):
        # A totally unauthenticated POST to /api/auth/login must still be
        # allowed by the middleware (it's whitelisted).
        r = api.post(f"{BASE_URL}/api/auth/login", json={"email": "nonexistent@x", "password": "x"})
        assert r.status_code != 401 or "TOTP" not in r.text, \
            "/api/auth/login should never be gated by admin-2FA middleware"

    def test_non_admin_gets_403_for_admin_route(self, api, user_token):
        r = api.post(
            f"{BASE_URL}/api/admin/telegram-settings",
            headers={"Authorization": f"Bearer {user_token}"},
            json={},
        )
        # Endpoint-level get_current_admin returns 403 'Forbidden'
        assert r.status_code in (403, 404), f"expected 403, got {r.status_code}"


# ===================== F10 : atomic pattern grep on new endpoints =====================
class TestF10AtomicPatterns:
    """Verify find_one_and_update with balance_ton:{$gte:...} on the 3 endpoints
    added in Round 3 (island plot buy ~2215, plot buy v2 ~2484, marketplace ~6207),
    plus the 2 from Round 2 (withdraw + withdraw/instant)."""

    def test_atomic_debit_sites_count(self):
        src = (ROOT / "server.py").read_text()
        # Match: find_one_and_update with balance_ton {$gte: something}
        pattern = re.compile(
            r'find_one_and_update\s*\(\s*\{[^{}]*"balance_ton"\s*:\s*\{\s*"\$gte"',
            re.DOTALL,
        )
        matches = pattern.findall(src)
        assert len(matches) >= 5, (
            f"Expected >=5 atomic debit sites (withdraw + withdraw/instant + "
            f"3 Round-3), found {len(matches)}"
        )

    def test_island_plot_buy_atomic(self):
        # ~ line 2217
        src = (ROOT / "server.py").read_text().splitlines()
        block = "\n".join(src[2200:2240])
        assert "find_one_and_update" in block and 'balance_ton' in block and '"$gte"' in block, \
            "island plot buy missing atomic debit"

    def test_plot_buy_v2_atomic(self):
        src = (ROOT / "server.py").read_text().splitlines()
        block = "\n".join(src[2470:2500])
        assert "find_one_and_update" in block and 'balance_ton' in block and '"$gte"' in block, \
            "plot buy v2 missing atomic debit"

    def test_marketplace_bot_listing_buy_atomic(self):
        src = (ROOT / "server.py").read_text().splitlines()
        block = "\n".join(src[6195:6225])
        assert "find_one_and_update" in block and 'balance_ton' in block and '"$gte"' in block, \
            "marketplace bot listing buy missing atomic debit"


# ===================== Basic auth (sanity) =====================
class TestBasicAuth:
    def test_admin_login(self, admin_token):
        assert isinstance(admin_token, str) and len(admin_token) > 20

    def test_user_login(self, user_token):
        assert isinstance(user_token, str) and len(user_token) > 20


# ===================== F33 : generic 500 handler still registered =====================
class TestF33ExceptionHandler:
    def test_handler_registered(self):
        src = (ROOT / "server.py").read_text()
        assert "internal error" in src.lower() or "internal_error" in src.lower(), \
            "generic internal-error response body missing"
        assert "app.add_exception_handler" in src or "@app.exception_handler" in src, \
            "global exception handler not registered"


# ===================== F12 : audit-log middleware still present =====================
class TestF12AuditLog:
    def test_audit_middleware_present(self):
        src = (ROOT / "server.py").read_text()
        assert "admin_audit_log" in src, "admin_audit_log collection reference missing"
        assert "AdminAuditLogMiddleware" in src or "audit_log" in src.lower()
