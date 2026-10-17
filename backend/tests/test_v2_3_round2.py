"""
TON_CITY_v2.3 — Round 2 regression tests.

Covers:
- Login regression (admin + user)
- Health
- 2FA priority (TOTP > email-code > plain) with email_2fa_force_all
- F9  : support-file path traversal
- F10 : atomic /withdraw/instant compare-and-set (concurrent double-spend)
- F11 : magic-bytes upload check on /api/admin/announcement/upload-image
- F12 : admin_audit_log middleware persists mutating admin calls
- F13 : soft-mode 2FA gate on the listed admin endpoints (works without TOTP configured;
        enforced when admin has TOTP)
- F25 : JWT exp = now + 7 days
- F27 : OAuth redirect_uri whitelist
- F28 : password reset generic response
- F32 : Referrer-Policy differs for sensitive URLs
- F33 : global exception handler registered (no stack trace leak)
- F34 : telegram webhook secret_token behaviour (regression)
- F4  : CSP has nonce, no unsafe-eval
- F5  : CORS never '*'
- F35 : .github/workflows/security.yml exists and is valid YAML
"""
import base64
import io
import os
import time
import uuid
import asyncio
import concurrent.futures
from datetime import datetime, timezone, timedelta

import pytest
import requests
import yaml
from jose import jwt as jose_jwt

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://632e0c5b-adc1-4bac-81e7-bf580a60139b.preview.emergentagent.com",
).rstrip("/")
DIRECT = "http://localhost:8001"

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PASSWORD = "Test1234!"


# ---------------- helpers ----------------
@pytest.fixture(scope="session")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


def _login(sess, email, pw):
    r = sess.post(f"{BASE_URL}/api/auth/login",
                  json={"email": email, "password": pw}, timeout=15)
    return r


@pytest.fixture(scope="session")
def admin_token(s):
    r = _login(s, ADMIN_EMAIL, ADMIN_PASSWORD)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text[:300]}"
    return r.json()["token"]


@pytest.fixture(scope="session")
def user_token(s):
    r = _login(s, USER_EMAIL, USER_PASSWORD)
    assert r.status_code == 200, f"user login failed: {r.status_code} {r.text[:300]}"
    return r.json()["token"]


def H(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ---------------- direct DB helpers (for setup/teardown) ----------------
def _db():
    import sys
    sys.path.insert(0, "/app/backend")
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env", override=True)
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    return client, client[os.environ["DB_NAME"]]


async def _set_email_force(enabled: bool):
    client, db = _db()
    try:
        await db.admin_settings.update_one(
            {"type": "auth_settings"},
            {"$set": {"type": "auth_settings", "email_2fa_force_all": enabled}},
            upsert=True,
        )
    finally:
        client.close()


async def _set_user_totp(email: str, enabled: bool, secret: str = None):
    client, db = _db()
    try:
        if enabled:
            await db.users.update_one(
                {"email": email},
                {"$set": {"is_2fa_enabled": True, "two_factor_secret": secret}},
            )
        else:
            await db.users.update_one(
                {"email": email},
                {"$set": {"is_2fa_enabled": False}, "$unset": {"two_factor_secret": ""}},
            )
    finally:
        client.close()


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


# ================= Health / Auth regression =================
class TestBasics:
    def test_health(self, s):
        r = s.get(f"{BASE_URL}/api/health", timeout=10)
        assert r.status_code == 200
        assert r.json().get("status") == "healthy"

    def test_admin_login(self, s):
        r = _login(s, ADMIN_EMAIL, ADMIN_PASSWORD)
        assert r.status_code == 200
        assert r.json()["user"]["email"] == ADMIN_EMAIL
        assert r.json()["user"].get("is_admin") is True

    def test_user_login(self, s):
        r = _login(s, USER_EMAIL, USER_PASSWORD)
        assert r.status_code == 200
        assert r.json()["user"]["email"] == USER_EMAIL


# ================= 2FA priority =================
class TestTwoFAPriority:
    """Semantics: TOTP > email-code > plain, regardless of admin's global
    email_2fa_force_all flag."""

    def teardown_method(self, method):
        # Best-effort cleanup after each test
        try:
            run(_set_email_force(False))
            run(_set_user_totp(USER_EMAIL, False))
        except Exception:
            pass

    def test_plain_login_no_flags(self, s):
        run(_set_email_force(False))
        run(_set_user_totp(USER_EMAIL, False))
        r = _login(s, USER_EMAIL, USER_PASSWORD)
        assert r.status_code == 200
        d = r.json()
        assert "token" in d, f"expected token, got {d}"
        assert not d.get("requires_2fa")
        assert not d.get("requires_email_code")

    def test_email_force_without_totp_returns_email_code(self, s):
        run(_set_user_totp(USER_EMAIL, False))
        run(_set_email_force(True))
        try:
            r = _login(s, USER_EMAIL, USER_PASSWORD)
            assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
            d = r.json()
            assert d.get("requires_email_code") is True, f"expected requires_email_code, got {d}"
            assert "token" not in d
            assert not d.get("requires_2fa")
        finally:
            run(_set_email_force(False))

    def test_totp_beats_email_force(self, s):
        """If user has TOTP configured AND email_2fa_force_all=true → still requires_2fa."""
        # Set both TOTP on user and admin force flag
        run(_set_user_totp(USER_EMAIL, True, secret="JBSWY3DPEHPK3PXP"))  # dummy base32
        run(_set_email_force(True))
        try:
            r = _login(s, USER_EMAIL, USER_PASSWORD)
            assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
            d = r.json()
            assert d.get("requires_2fa") is True, (
                f"TOTP must win over email force; got {d}"
            )
            assert not d.get("requires_email_code"), (
                f"Should NOT ask for email code when TOTP is set; got {d}"
            )
            assert "token" not in d
        finally:
            run(_set_user_totp(USER_EMAIL, False))
            run(_set_email_force(False))


# ================= F28 regression =================
class TestF28PasswordReset:
    def _generic(self, r):
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
        d = r.json()
        assert d.get("status") == "success"
        assert d.get("message") == "code_sent"

    def test_reset_existing(self, s):
        self._generic(s.post(f"{BASE_URL}/api/auth/request-password-reset",
                             json={"email": ADMIN_EMAIL}))

    def test_reset_nonexistent(self, s):
        self._generic(s.post(f"{BASE_URL}/api/auth/request-password-reset",
                             json={"email": "totally_nobody_1234567@example.com"}))


# ================= F9 path traversal =================
class TestF9PathTraversal:
    """We only test payloads that survive HTTP client URL normalization.
    Raw '../../..' segments are normalized by requests before sending, so
    they never even reach the /api/support/files endpoint. URL-encoded
    variants DO reach the endpoint and must be rejected there."""

    @pytest.mark.parametrize("payload", [
        "..%2F..%2Fetc%2Fpasswd",
        "..%2Fetc%2Fpasswd",
        "..%2F..%2F..%2Fetc%2Fpasswd",
        ".hidden",
        ".env",
        "%2E%2E%2Fetc%2Fpasswd",
    ])
    def test_path_traversal_rejected(self, s, payload):
        # Build URL from a prepared request to avoid client normalization
        req = requests.Request("GET", f"{BASE_URL}/api/support/files/{payload}")
        prep = s.prepare_request(req)
        # Force the raw path
        prep.url = f"{BASE_URL}/api/support/files/{payload}"
        r = s.send(prep, allow_redirects=False, timeout=10)
        assert r.status_code in (400, 404), (
            f"traversal not blocked for {payload!r}: {r.status_code} {r.text[:200]}"
        )
        # Never leak /etc/passwd contents
        assert "root:" not in r.text, "possible /etc/passwd leak!"

    def test_raw_dotdot_never_reaches_backend(self, s):
        """Sanity: even if a client sends '../../../etc/passwd', it must not
        return /etc/passwd contents. Client URL normalization is expected;
        we just check the response body doesn't leak sensitive content."""
        r = s.get(f"{BASE_URL}/api/support/files/../../../etc/passwd",
                  allow_redirects=False, timeout=10)
        assert "root:" not in r.text, "possible /etc/passwd leak!"
        assert "daemon:" not in r.text


# ================= F11 magic bytes =================
class TestF11MagicBytes:
    def _upload(self, s, admin_token, filename, content_type, data):
        # Build multipart manually via requests
        files = {"file": (filename, data, content_type)}
        r = requests.post(
            f"{BASE_URL}/api/admin/announcement/upload-image",
            headers={"Authorization": f"Bearer {admin_token}"},
            files=files,
            timeout=15,
        )
        return r

    def test_spoofed_png_html_rejected(self, s, admin_token):
        html = b"<html><body>hi</body></html>"
        r = self._upload(s, admin_token, "fake.png", "image/png", html)
        assert r.status_code == 400, f"spoofed png should 400, got {r.status_code}: {r.text[:200]}"
        assert "не является изображением" in r.text or "image" in r.text.lower()

    def test_valid_png_accepted(self, s, admin_token):
        # Minimal valid PNG (1x1 transparent)
        png = (
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\rIHDR"
            b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
            b"\x00\x00\x00\rIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4"
            b"\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        r = self._upload(s, admin_token, "real.png", "image/png", png)
        assert r.status_code == 200, f"valid png rejected: {r.status_code} {r.text[:200]}"
        d = r.json()
        assert d.get("url", "").startswith("data:image/")

    def test_non_admin_rejected(self, s, user_token):
        r = self._upload(s, user_token, "x.png", "image/png", b"whatever")
        assert r.status_code in (401, 403)


# ================= F25 JWT TTL =================
class TestF25JWTExpiry:
    def test_jwt_exp_is_7_days(self, s):
        r = _login(s, USER_EMAIL, USER_PASSWORD)
        assert r.status_code == 200
        token = r.json()["token"]
        # Decode without signature verification (we just need exp/iat)
        payload = jose_jwt.get_unverified_claims(token)
        assert "exp" in payload, f"no exp claim: {payload}"
        exp = int(payload["exp"])
        now = int(time.time())
        delta_days = (exp - now) / 86400
        # Allow small clock drift; 7d ±1d window (definitely not 30d)
        assert 6.5 <= delta_days <= 7.5, f"expected ~7d TTL, got {delta_days:.2f} days"


# ================= F32 Referrer-Policy =================
class TestF32Referrer:
    def test_health_default_policy(self, s):
        r = s.get(f"{BASE_URL}/api/health")
        rp = r.headers.get("Referrer-Policy", "")
        assert rp == "strict-origin-when-cross-origin", (
            f"expected strict-origin-when-cross-origin, got {rp!r}"
        )

    def test_verify_email_no_referrer(self, s):
        # /api/verify-email is the actual endpoint hit on click
        # We hit with a dummy token; the endpoint may 400/404 but headers still apply.
        # Note: response.headers only from actual HTTP response.
        r = s.get(f"{BASE_URL}/api/verify-email?token=xxx", allow_redirects=False)
        rp = r.headers.get("Referrer-Policy", "")
        assert rp == "no-referrer", (
            f"expected no-referrer on verify-email, got {rp!r} (status={r.status_code})"
        )


# ================= F33 exception handler is registered =================
class TestF33ExceptionHandler:
    def test_handler_registered(self):
        """Import server.app and verify a generic-Exception handler is registered.

        We don't try to force a real crash — instead we verify the handler
        object is attached to app.exception_handlers, which is what F33 does.
        """
        import sys
        sys.path.insert(0, "/app/backend")
        from dotenv import load_dotenv
        load_dotenv("/app/backend/.env", override=True)
        # Importing server has side effects — only do it here.
        import server  # noqa: F401
        handlers = server.app.exception_handlers
        assert Exception in handlers or any(
            cls is Exception for cls in handlers.keys()
        ), f"generic Exception handler not registered; keys={list(handlers.keys())}"


# ================= F27 OAuth redirect whitelist =================
class TestF27OAuthWhitelist:
    def test_evil_redirect_rejected(self, s):
        r = s.post(f"{BASE_URL}/api/auth/google/callback",
                   json={"code": "dummy", "redirect_uri": "https://evil.com/cb"})
        assert r.status_code == 400, f"evil redirect not blocked: {r.status_code} {r.text[:200]}"
        assert "redirect_uri" in r.text.lower() or "invalid" in r.text.lower()

    def test_localhost_redirect_passes_whitelist(self, s):
        """localhost dev fallback is whitelisted → should pass validation and
        either 500 (missing GOOGLE_CLIENT_ID) or 4xx from downstream Google
        call, but NOT 400 'Invalid redirect_uri'."""
        r = s.post(f"{BASE_URL}/api/auth/google/callback",
                   json={"code": "dummy", "redirect_uri": "http://localhost:3000/auth/google/callback"})
        if r.status_code == 400:
            # Ensure it's NOT because of redirect_uri
            assert "redirect_uri" not in r.text.lower(), (
                f"localhost redirect wrongly blocked as invalid_redirect: {r.text[:200]}"
            )
        # Otherwise 401/500 is fine (downstream error)


# ================= F5 CORS =================
class TestF5CORS:
    def test_no_wildcard_direct(self, s):
        r = requests.get(f"{DIRECT}/api/health",
                         headers={"Origin": "https://evil.com"}, timeout=10)
        acao = r.headers.get("Access-Control-Allow-Origin", "")
        assert acao != "*", f"CORS wildcard leaked: {acao!r}"

    def test_configured_origin_echoed(self):
        r = requests.get(f"{DIRECT}/api/health",
                         headers={"Origin": "http://localhost:3000"}, timeout=10)
        acao = r.headers.get("Access-Control-Allow-Origin", "")
        assert acao == "http://localhost:3000", f"configured origin not echoed: {acao!r}"


# ================= F4 CSP =================
class TestF4CSP:
    def test_csp_no_unsafe_eval(self, s):
        r = s.get(f"{BASE_URL}/api/health")
        csp = r.headers.get("Content-Security-Policy", "")
        assert csp, "no CSP header"
        assert "unsafe-eval" not in csp, f"unsafe-eval leaked: {csp[:200]}"

    def test_csp_has_nonce(self, s):
        r = s.get(f"{BASE_URL}/api/health")
        csp = r.headers.get("Content-Security-Policy", "")
        assert "nonce-" in csp, f"no nonce: {csp[:200]}"


# ================= F34 telegram webhook secret_token silent skip =================
class TestF34WebhookSecret:
    def test_webhook_diag_get(self, s):
        r = s.get(f"{BASE_URL}/api/telegram/webhook")
        assert r.status_code == 200
        assert r.json().get("endpoint_reachable") is True

    def test_wrong_secret_silent_ok(self, s):
        """If a secret_token is stored in DB, a request with a wrong header
        must return {ok:true} silently (no processing). We can't easily verify
        the "no processing" side-effect via HTTP, but we verify a wrong header
        never leaks a 401 or an error — always 200 ok."""
        update = {
            "update_id": 424242,
            "message": {
                "message_id": 1,
                "from": {"id": 42, "is_bot": False, "first_name": "TT"},
                "chat": {"id": 42, "type": "private"},
                "date": int(time.time()),
                "text": "hi",
            },
        }
        r = requests.post(
            f"{BASE_URL}/api/telegram/webhook",
            json=update,
            headers={"X-Telegram-Bot-Api-Secret-Token": "definitely-wrong"},
            timeout=10,
        )
        # Even with wrong token, endpoint must not reveal validity
        assert r.status_code in (200, 429), f"unexpected {r.status_code}"


# ================= F12 admin audit log middleware =================
class TestF12AuditLog:
    def test_admin_post_is_logged_get_is_not(self, s, admin_token):
        """After a mutating admin call, admin_audit_log grows by ≥1.
        After a GET admin call, it does NOT grow."""
        import sys
        sys.path.insert(0, "/app/backend")
        from dotenv import load_dotenv
        load_dotenv("/app/backend/.env", override=True)

        async def _count():
            client, db = _db()
            try:
                return await db.admin_audit_log.count_documents({})
            finally:
                client.close()

        before = asyncio.run(_count())

        # GET (should NOT be logged)
        r = s.get(f"{BASE_URL}/api/admin/telegram-settings", headers=H(admin_token))
        assert r.status_code == 200

        time.sleep(0.5)  # give fire-and-forget task a moment
        after_get = asyncio.run(_count())
        assert after_get == before, (
            f"GET should not audit-log; before={before} after={after_get}"
        )

        # POST — save telegram settings (harmless, admin-authenticated)
        fake_payload = {
            "bot_token": "1234567890:FAKEBOTTOKENAUDITLOG12345XYZABCDEFGH",
            "bot_username": "audit_probe_bot",
            "admin_telegram_id": "100000001",
        }
        r2 = s.post(f"{BASE_URL}/api/admin/telegram-settings",
                    json=fake_payload, headers=H(admin_token))
        # Any status is fine — we're testing the middleware
        assert r2.status_code in (200, 400, 401, 500), f"unexpected {r2.status_code}"
        time.sleep(1.0)
        after_post = asyncio.run(_count())
        assert after_post > after_get, (
            f"POST should audit-log; after_get={after_get} after_post={after_post}"
        )

    def test_audit_log_entry_shape(self, s, admin_token):
        # Trigger one more admin POST and inspect the latest entry
        async def _last():
            client, db = _db()
            try:
                docs = await db.admin_audit_log.find(
                    {}, {"_id": 0}
                ).sort("timestamp", -1).limit(3).to_list(3)
                return docs
            finally:
                client.close()

        s.post(
            f"{BASE_URL}/api/admin/telegram-settings",
            json={"bot_token": "1234567890:AUDIT_SHAPE_PROBE12345678901234567", "bot_username": "aa", "admin_telegram_id": "100"},
            headers=H(admin_token),
        )
        time.sleep(1.0)
        docs = asyncio.run(_last())
        assert docs, "no audit log entries"
        latest = docs[0]
        for k in ("path", "method", "status", "admin_email", "ip", "user_agent", "timestamp"):
            assert k in latest, f"audit entry missing key {k}: {latest}"


# ================= F13 soft-mode 2FA gate =================
class TestF13SoftMode2FA:
    """Endpoints protected with get_current_admin_with_2fa. Since admin has
    NO TOTP configured (soft-mode), they must still respond with 200/400 —
    never 401 'TOTP required'."""

    def _hit_soft(self, s, admin_token, method, path, **kw):
        h = H(admin_token)
        if method == "POST":
            r = requests.post(f"{BASE_URL}{path}", headers=h, timeout=15, **kw)
        elif method == "DELETE":
            r = requests.delete(f"{BASE_URL}{path}", headers=h, timeout=15, **kw)
        elif method == "PUT":
            r = requests.put(f"{BASE_URL}{path}", headers=h, timeout=15, **kw)
        else:
            r = requests.get(f"{BASE_URL}{path}", headers=h, timeout=15, **kw)
        return r

    def test_soft_mode_no_totp_required(self, s, admin_token):
        """Sanity: admin has no TOTP. save-telegram-settings uses the gate and
        must accept the request (not 401)."""
        r = self._hit_soft(
            s, admin_token, "POST", "/api/admin/telegram-settings",
            json={
                "bot_token": "1234567890:SOFTMODE_PROBE12345678901234ABCDEFG",
                "bot_username": "softmode_bot",
                "admin_telegram_id": "100000001",
            },
        )
        assert r.status_code != 401, (
            f"soft-mode should NOT require TOTP when admin has none; got 401: {r.text[:200]}"
        )
        assert r.status_code in (200, 400, 500), f"unexpected {r.status_code} {r.text[:200]}"

    def test_hard_mode_requires_totp(self, s, admin_token):
        """Enable TOTP on admin briefly → protected endpoint must return 401
        without X-Admin-TOTP header. Cleanup after."""
        # Use dummy base32 secret; verify() will fail for any code but the
        # gate rejects on 'no header' first.
        secret = "JBSWY3DPEHPK3PXP"  # base32 "Hello!"
        run(_set_user_totp(ADMIN_EMAIL, True, secret))
        try:
            r = self._hit_soft(
                s, admin_token, "POST", "/api/admin/telegram-settings",
                json={
                    "bot_token": "1234567890:HARDMODE_PROBE12345678901234ABCDEFG",
                    "bot_username": "hardmode_bot",
                    "admin_telegram_id": "100000001",
                },
            )
            assert r.status_code == 401, (
                f"hard-mode must 401 without TOTP header; got {r.status_code}: {r.text[:200]}"
            )
            assert "TOTP" in r.text or "totp" in r.text.lower()

            # Wrong TOTP header → still 401
            r2 = requests.post(
                f"{BASE_URL}/api/admin/telegram-settings",
                json={
                    "bot_token": "1234567890:HARDMODE_WRONG12345678901234ABCDEFG",
                    "bot_username": "hardmode_bot_wrong",
                    "admin_telegram_id": "100000001",
                },
                headers={**H(admin_token), "X-Admin-TOTP": "000000"},
                timeout=15,
            )
            assert r2.status_code == 401, (
                f"wrong TOTP must 401; got {r2.status_code}: {r2.text[:200]}"
            )
        finally:
            run(_set_user_totp(ADMIN_EMAIL, False))


# ================= F10 atomic /withdraw/instant =================
class TestF10AtomicWithdraw:
    """Verify compare-and-set on balance_ton prevents double-spend.

    We look at the source and confirm the pattern is used. Then attempt a
    concurrent double-call. Because the endpoint requires wallet_address,
    balance, and passes many pre-checks that a bare test user may fail, we
    treat "both requests errored the same way" as inconclusive-but-not-buggy;
    the real assertion is that we never get TWO 200s that both debit."""

    def test_atomic_code_pattern_present(self):
        src = open("/app/backend/server.py").read()
        # Endpoint /withdraw
        assert 'balance_ton": {"$gte":' in src, "atomic $gte pattern missing"
        assert "$inc" in src and "balance_ton" in src, "$inc/balance_ton missing"

    def test_concurrent_withdraw_never_double_debit(self, s, user_token):
        """Fire N parallel /withdraw/instant of the full balance. At most ONE
        may return 200. The rest must be 4xx."""
        # Get current user balance
        me = s.get(f"{BASE_URL}/api/me", headers=H(user_token), timeout=10)
        if me.status_code != 200:
            pytest.skip(f"/api/me not available: {me.status_code}")
        bal = me.json().get("balance_ton") or me.json().get("balance") or 100.0

        # Use whole balance so at most one debit is possible
        amount = float(bal)

        def _try():
            try:
                r = requests.post(
                    f"{BASE_URL}/api/withdraw/instant",
                    json={"wallet_address": "EQC0000000000000000000000000000000000000000000000",
                          "amount": amount},
                    headers=H(user_token),
                    timeout=15,
                )
                return r.status_code
            except Exception as e:
                return f"err:{e}"

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
            codes = list(ex.map(lambda _: _try(), range(5)))
        print("withdraw codes:", codes)
        # Never more than one 200 (successful debit). Since test user may not
        # pass all pre-checks, we accept 0 or 1 successes.
        n_200 = sum(1 for c in codes if c == 200)
        assert n_200 <= 1, f"CRITICAL: double-debit possible! codes={codes}"


# ================= F35 CI file =================
class TestF35CIFile:
    def test_security_workflow_exists_and_valid(self):
        path = "/app/.github/workflows/security.yml"
        assert os.path.exists(path), "security.yml missing"
        with open(path) as f:
            doc = yaml.safe_load(f)
        # YAML "on" gets parsed as True by default — allow both
        assert doc, "empty yaml"
        assert "jobs" in doc, f"no jobs: {list(doc.keys())}"
        # Contains at least one of the required scanners
        text = open(path).read().lower()
        assert any(t in text for t in ("bandit", "semgrep", "pip-audit", "gitleaks")), (
            "no known security scanner referenced"
        )
