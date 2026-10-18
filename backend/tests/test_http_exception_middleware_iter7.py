"""Iteration 7 — verify that the generic Exception handler no longer re-raises
HTTPException (which under Python 3.12 + anyio + BaseHTTPMiddleware caused
`RuntimeError: No response returned`).

Every case below must:
  (a) return the correct status code (401 / 403 / 404 / 400 / 200 / 500),
  (b) return a valid JSON body with a `detail` field,
  (c) NOT produce `RuntimeError: No response returned` in
      /var/log/supervisor/backend.*.log during the request window.
"""
import json
import os
import re
import time
from pathlib import Path

import pytest
import requests

# ---------- Config ----------

def _read_backend_url() -> str:
    url = os.environ.get("REACT_APP_BACKEND_URL")
    if url:
        return url.rstrip("/")
    env_path = Path("/app/frontend/.env")
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("REACT_APP_BACKEND_URL="):
                return line.split("=", 1)[1].strip().rstrip("/")
    raise RuntimeError("REACT_APP_BACKEND_URL not found")

BASE_URL = _read_backend_url()
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASS = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PASS = "Test1234!"

BACKEND_LOG_GLOB = "/var/log/supervisor/backend.*.log"

# ---------- Log helpers ----------

def _log_snapshot_size() -> int:
    """Return combined size of backend supervisor log files (bytes)."""
    import glob
    total = 0
    for p in glob.glob(BACKEND_LOG_GLOB):
        try:
            total += os.path.getsize(p)
        except OSError:
            pass
    return total

def _log_tail_since(offset: int) -> str:
    """Return concatenated tail of all backend log files past the given offset."""
    import glob
    buf = []
    for p in sorted(glob.glob(BACKEND_LOG_GLOB)):
        try:
            with open(p, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                start = min(offset, size)
                f.seek(start)
                buf.append(f.read().decode("utf-8", errors="replace"))
        except OSError:
            pass
    return "\n".join(buf)


BAD_PATTERNS = [
    r"RuntimeError: No response returned",
    r"anyio.*ExceptionGroup",
    r"BaseExceptionGroup",  # only if suspicious in stack
]

def _assert_no_bad_log(pre_offset: int) -> None:
    """Assert no `RuntimeError: No response returned` appeared in the backend
    logs since `pre_offset`.
    """
    time.sleep(0.5)  # let uvicorn flush
    tail = _log_tail_since(pre_offset)
    # ExceptionGroup alone is not necessarily bad, but "No response returned" IS.
    assert "RuntimeError: No response returned" not in tail, (
        "Backend logged `RuntimeError: No response returned` — the exception "
        "handler is corrupting the response iterator.\n---LOG TAIL---\n" + tail[-4000:]
    )

# ---------- Fixtures ----------

@pytest.fixture(scope="module")
def s():
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session

def _login(s, email, password):
    r = s.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"Login failed for {email}: {r.status_code} {r.text}"
    body = r.json()
    tok = body.get("token") or body.get("access_token")
    assert tok, f"No token in login response: {body}"
    return tok

@pytest.fixture(scope="module")
def admin_token(s):
    return _login(s, ADMIN_EMAIL, ADMIN_PASS)

@pytest.fixture(scope="module")
def user_token(s):
    return _login(s, USER_EMAIL, USER_PASS)


# =========================================================================
# 1) HTTPException status codes propagate through middleware WITHOUT
#    producing `No response returned`.
# =========================================================================

class TestHTTPExceptionPropagation:
    """Every HTTPException raised in a dependency or route must reach the
    client as its intended status + JSON detail, never as a 500 nor as a
    RuntimeError-corrupted response.
    """

    def test_a_no_auth_returns_401_with_detail(self, s):
        pre = _log_snapshot_size()
        r = requests.get(f"{API}/admin/promo/referral-rally/current", timeout=15)
        assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text}"
        body = r.json()
        assert "detail" in body and isinstance(body["detail"], str) and body["detail"], body
        _assert_no_bad_log(pre)

    def test_b_non_admin_returns_403_with_detail(self, s, user_token):
        pre = _log_snapshot_size()
        r = requests.get(
            f"{API}/admin/promo/referral-rally/current",
            headers={"Authorization": f"Bearer {user_token}"},
            timeout=15,
        )
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text}"
        body = r.json()
        assert "detail" in body and body["detail"], body
        _assert_no_bad_log(pre)

    def test_c_unknown_route_returns_404_with_detail(self, s):
        pre = _log_snapshot_size()
        r = requests.get(f"{API}/this-route-does-not-exist", timeout=15)
        assert r.status_code == 404, f"expected 404, got {r.status_code}: {r.text}"
        body = r.json()
        assert "detail" in body, body
        _assert_no_bad_log(pre)

    def test_d_admin_buyout_execute_empty_items_returns_4xx_with_detail(
        self, s, admin_token
    ):
        """POST /api/admin/buyout/execute with empty items should raise 400/422,
        NOT crash with RuntimeError."""
        pre = _log_snapshot_size()
        r = requests.post(
            f"{API}/admin/buyout/execute",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"items": []},
            timeout=15,
        )
        # Backend may raise 400 (custom validation) or 422 (FastAPI validation).
        assert r.status_code in (400, 422), (
            f"expected 400/422, got {r.status_code}: {r.text}"
        )
        body = r.json()
        assert "detail" in body, body
        _assert_no_bad_log(pre)


# =========================================================================
# 2) Auth flows still work — HTTPExceptions raised in dependencies flow
#    cleanly back through AuthCookie/CSRF middlewares.
# =========================================================================

class TestAuthFlowsIntact:
    def test_admin_login_returns_token(self, admin_token):
        assert isinstance(admin_token, str) and len(admin_token) > 10

    def test_admin_endpoint_returns_200_with_leaderboard(self, admin_token):
        pre = _log_snapshot_size()
        r = requests.get(
            f"{API}/admin/promo/referral-rally/current",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=20,
        )
        assert r.status_code == 200, f"{r.status_code}: {r.text[:400]}"
        body = r.json()
        assert "top10" in body or "leaderboard" in body or "campaign" in body, body
        _assert_no_bad_log(pre)

    def test_user_login_and_authenticated_me(self, s, user_token):
        pre = _log_snapshot_size()
        # /api/auth/me is a standard authenticated route
        r = requests.get(
            f"{API}/auth/me",
            headers={"Authorization": f"Bearer {user_token}"},
            timeout=15,
        )
        # If /auth/me does not exist in this app, fall back to /profile/me
        if r.status_code == 404:
            r = requests.get(
                f"{API}/profile/me",
                headers={"Authorization": f"Bearer {user_token}"},
                timeout=15,
            )
        assert r.status_code == 200, f"{r.status_code}: {r.text[:400]}"
        _assert_no_bad_log(pre)


# =========================================================================
# 3) Genuine 500 path (non-HTTP exception) still returns clean 500 JSON.
#    We can't easily force a real 500 from outside — this is best-effort:
#    we look for a known route that used to trigger 500 on bad input.
#    If none is reachable safely, we just re-verify no "No response returned"
#    occurred during our whole run so far.
# =========================================================================

class TestNoResponseReturnedAbsent:
    def test_backend_logs_have_no_no_response_returned_during_suite(self):
        """Read the last ~200KB of backend log and ensure the specific
        RuntimeError we fixed is not present."""
        import glob
        found = []
        for p in sorted(glob.glob(BACKEND_LOG_GLOB)):
            try:
                sz = os.path.getsize(p)
                with open(p, "rb") as f:
                    f.seek(max(0, sz - 200_000))
                    tail = f.read().decode("utf-8", errors="replace")
                if "RuntimeError: No response returned" in tail:
                    found.append(p)
            except OSError:
                pass
        assert not found, f"'No response returned' still appearing in: {found}"


# =========================================================================
# 4) REGRESSION — recent features intact after the fix.
# =========================================================================

class TestRegression:
    def test_referral_rally_current_has_seeded_referrers(self, admin_token):
        r = requests.get(
            f"{API}/admin/promo/referral-rally/current",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=20,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        top10 = body.get("top10") or body.get("leaderboard") or []
        assert isinstance(top10, list) and len(top10) > 0, f"empty leaderboard: {body}"
        usernames = {row.get("username") or row.get("user", {}).get("username") for row in top10}
        # At least one of our seeded referrers should appear
        seeded = {"rally_topguy", "rally_second", "rally_third", "rally_fourth", "rally_fifth"}
        assert usernames & seeded, f"none of {seeded} in leaderboard: {usernames}"

    def test_admin_buyout_overview_200(self, admin_token):
        r = requests.get(
            f"{API}/admin/buyout/overview",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=20,
        )
        assert r.status_code == 200, f"{r.status_code}: {r.text[:400]}"
        body = r.json()
        assert isinstance(body, (dict, list)), body

    def test_admin_buyout_nicks_200(self, admin_token):
        r = requests.get(
            f"{API}/admin/buyout/nicks",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=20,
        )
        assert r.status_code == 200, f"{r.status_code}: {r.text[:400]}"
        body = r.json()
        # Should be a list of nicknames or dict containing them
        assert isinstance(body, (list, dict))

    def test_rate_limit_and_pymongo_handlers_registered(self):
        """Verify the specific handlers still exist in the running module — we
        import them directly (not via HTTP)."""
        import importlib
        server = importlib.import_module("server")
        handlers = getattr(server.app, "exception_handlers", {})
        # exception_handlers is keyed by exception class in Starlette
        keys = {getattr(k, "__name__", str(k)) for k in handlers.keys()}
        assert "RateLimitExceeded" in keys, f"missing RateLimitExceeded handler: {keys}"
        assert "PyMongoError" in keys, f"missing PyMongoError handler: {keys}"
        assert "Exception" in keys, f"missing generic Exception handler: {keys}"
