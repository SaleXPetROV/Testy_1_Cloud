"""
Iter8 — ClientDisconnectGuardMiddleware verification.

Verifies:
  1. Full middleware-stack status-code propagation (401/403/404/400/200) —
     no `RuntimeError: No response returned` in backend logs, valid JSON body.
  2. Client-disconnect resilience: raw socket that closes before reading the
     response must NOT accumulate `RuntimeError: No response returned`
     ExceptionGroup tracebacks. Backend process stays RUNNING. A subsequent
     normal request still returns 200 (server not degraded).
  3. Regression: normal auth + feature flows unaffected (admin login, buyout
     overview/nicks, referral-rally leaderboard, user login).
  4. Genuine (non-disconnect) errors still surface — the guard must NOT swallow
     ordinary HTTPExceptions; they must still yield 4xx/5xx JSON, not 204.
"""
import os
import socket
import subprocess
import time
import json as _json
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL must be set"
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PW = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PW = "Test1234!"

BACKEND_ERR_LOG = "/var/log/supervisor/backend.err.log"
BACKEND_OUT_LOG = "/var/log/supervisor/backend.out.log"


# ─────────────────────────── helpers ───────────────────────────

def _read_logs() -> str:
    txt = ""
    for p in (BACKEND_ERR_LOG, BACKEND_OUT_LOG):
        try:
            with open(p, "r", errors="ignore") as f:
                txt += f.read()
        except Exception:
            pass
    return txt


def _count_no_response_returned(txt: str) -> int:
    # Only count actual RuntimeError tracebacks — not the INFO log line
    # "Client disconnected mid-request (suppressed 'No response returned')".
    n = 0
    for line in txt.splitlines():
        if "RuntimeError: No response returned" in line:
            n += 1
    return n


def _login(email: str, pw: str) -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=15)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text[:200]}"
    tok = r.json().get("access_token") or r.json().get("token")
    assert tok, f"no token in response: {r.text[:200]}"
    return tok


# ─────────────────────────── fixtures ───────────────────────────

# NOTE: fixtures are function-scoped because the server invalidates prior
# sessions on every fresh /auth/login call (`session_invalidated` on next
# request with the old token). A module-scoped token would be killed by
# `TestRegressionsUnaffected.test_*_login_returns_token`. Login is cheap
# (~200 ms) so this is acceptable.
@pytest.fixture
def admin_token() -> str:
    return _login(ADMIN_EMAIL, ADMIN_PW)


@pytest.fixture
def user_token() -> str:
    return _login(USER_EMAIL, USER_PW)


@pytest.fixture(scope="module", autouse=True)
def _truncate_logs():
    """Truncate backend logs before the module starts so we can count
    `No response returned` errors caused only by these tests."""
    for p in (BACKEND_ERR_LOG, BACKEND_OUT_LOG):
        try:
            with open(p, "w") as f:
                f.write("")
        except Exception:
            pass
    yield


# ─────────────────── 1. Status-code propagation ────────────────────

class TestMiddlewareStackStatusCodes:
    """No 'No response returned' and valid JSON for each status code."""

    def test_401_unauthenticated_admin_route(self):
        r = requests.get(f"{API}/admin/promo/referral-rally/current", timeout=15)
        assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text[:200]}"
        body = r.json()
        assert "detail" in body
        assert isinstance(body["detail"], str)

    def test_403_non_admin_hitting_admin_route(self, user_token):
        r = requests.get(
            f"{API}/admin/promo/referral-rally/current",
            headers={"Authorization": f"Bearer {user_token}"},
            timeout=15,
        )
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text[:200]}"
        assert "detail" in r.json()

    def test_404_nonexistent_route(self):
        r = requests.get(f"{API}/nonexistent-route-xyz-42", timeout=15)
        assert r.status_code == 404, f"expected 404, got {r.status_code}: {r.text[:200]}"
        # FastAPI returns JSON {"detail":"Not Found"} for 404.
        assert "detail" in r.json()

    def test_400_admin_buyout_execute_empty_items(self, admin_token):
        r = requests.post(
            f"{API}/admin/buyout/execute",
            json={"items": []},
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=30,
        )
        # Endpoint returns 400 for empty items; some validation could yield 422.
        assert r.status_code in (400, 422), (
            f"expected 400/422, got {r.status_code}: {r.text[:300]}"
        )
        body = r.json()
        assert "detail" in body

    def test_200_admin_buyout_overview(self, admin_token):
        r = requests.get(
            f"{API}/admin/buyout/overview",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=30,
        )
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text[:300]}"
        assert isinstance(r.json(), (dict, list))

    def test_logs_clean_after_status_code_tests(self):
        # Give any pending background writes a moment to flush.
        time.sleep(0.5)
        txt = _read_logs()
        n = _count_no_response_returned(txt)
        assert n == 0, (
            f"Backend logs contained {n} 'RuntimeError: No response returned' "
            f"line(s) after status-code tests — should be 0.\n"
            f"---LOG TAIL---\n{txt[-4000:]}"
        )


# ─────────────────── 2. Client-disconnect resilience ────────────────────

class TestClientDisconnectGuard:
    """Raw-socket abort scenarios: server must NOT log
    `RuntimeError: No response returned` ExceptionGroup tracebacks;
    process stays up; subsequent requests still succeed."""

    def _abort_request(self, path: str, token: str = None, delay_ms: int = 0):
        """Open raw socket to backend on localhost:8001, send a GET, then
        close the socket immediately without reading."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect(("127.0.0.1", 8001))
        auth = f"Authorization: Bearer {token}\r\n" if token else ""
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: localhost\r\n"
            f"{auth}"
            f"Connection: close\r\n"
            f"User-Agent: iter8-disconnect-test\r\n"
            f"\r\n"
        )
        s.sendall(req.encode("ascii"))
        if delay_ms:
            time.sleep(delay_ms / 1000.0)
        # Force abort: RST via SO_LINGER=0, then close.
        try:
            import struct
            s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        except Exception:
            pass
        s.close()

    def test_repeated_client_aborts_do_not_flood_logs(self, admin_token):
        before = _count_no_response_returned(_read_logs())
        # Repeat 6 times, mixing zero-delay and small-delay aborts.
        for i in range(6):
            self._abort_request("/api/admin/buyout/overview", token=admin_token,
                                delay_ms=(0 if i % 2 == 0 else 25))
        # Give the backend time to finish processing/handling.
        time.sleep(3.0)
        after_txt = _read_logs()
        after = _count_no_response_returned(after_txt)
        added = after - before
        assert added == 0, (
            f"Client-disconnect burst added {added} 'RuntimeError: No response "
            f"returned' line(s) to the backend log — the guard middleware is not "
            f"swallowing them.\n---LOG TAIL---\n{after_txt[-6000:]}"
        )

    def test_backend_process_still_running_after_aborts(self):
        out = subprocess.run(
            ["supervisorctl", "status", "backend"], capture_output=True, text=True
        )
        assert "RUNNING" in out.stdout, f"backend not RUNNING: {out.stdout} {out.stderr}"

    def test_normal_request_still_200_after_aborts(self, admin_token):
        r = requests.get(
            f"{API}/admin/buyout/overview",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=30,
        )
        assert r.status_code == 200, (
            f"server appears degraded — expected 200 after disconnect burst, "
            f"got {r.status_code}: {r.text[:300]}"
        )


# ─────────────────── 3. Regression — auth + features ────────────────────

class TestRegressionsUnaffected:
    def test_admin_login_returns_token(self):
        tok = _login(ADMIN_EMAIL, ADMIN_PW)
        assert isinstance(tok, str) and len(tok) > 10

    def test_user_login_returns_token(self):
        tok = _login(USER_EMAIL, USER_PW)
        assert isinstance(tok, str) and len(tok) > 10

    def test_admin_buyout_overview_ok(self, admin_token):
        r = requests.get(
            f"{API}/admin/buyout/overview",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=30,
        )
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert isinstance(body, (dict, list))

    def test_admin_buyout_nicks_ok(self, admin_token):
        r = requests.get(
            f"{API}/admin/buyout/nicks",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=30,
        )
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        # Endpoint returns either a list or a dict with a nicks/list field.
        assert isinstance(body, (list, dict))

    def test_referral_rally_current_seeded(self, admin_token):
        r = requests.get(
            f"{API}/admin/promo/referral-rally/current",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=30,
        )
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert isinstance(body, dict)
        # Should include a leaderboard (may be `leaderboard` / `top` / `referrers`).
        blob = _json.dumps(body).lower()
        assert any(k in blob for k in ("rally_topguy", "rally_second", "leaderboard", "referrers", "top")), (
            f"referral-rally current missing seeded referrers/leaderboard: {body}"
        )


# ─────────────── 4. Genuine (non-disconnect) errors still surface ───────────────

class TestGenuineErrorsStillSurface:
    """The guard must ONLY swallow when the request is actually disconnected —
    a normal request that internally errors must still yield a 4xx/5xx JSON
    response, never a silent 204."""

    def test_401_is_not_swallowed_to_204(self):
        r = requests.get(f"{API}/admin/buyout/overview", timeout=15)
        assert r.status_code == 401
        assert r.status_code != 204
        assert "detail" in r.json()

    def test_403_is_not_swallowed_to_204(self, user_token):
        r = requests.get(
            f"{API}/admin/buyout/overview",
            headers={"Authorization": f"Bearer {user_token}"},
            timeout=15,
        )
        assert r.status_code == 403
        assert r.status_code != 204
        assert "detail" in r.json()

    def test_404_is_not_swallowed_to_204(self):
        r = requests.get(f"{API}/definitely-not-a-real-route-9x8", timeout=15)
        assert r.status_code == 404
        assert r.status_code != 204

    def test_422_validation_error_is_not_swallowed(self, admin_token):
        # Send malformed JSON body to a POST endpoint that expects a schema.
        r = requests.post(
            f"{API}/admin/buyout/execute",
            json={"bad_field": "value"},  # missing "items"
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=15,
        )
        # Either FastAPI 422 (validation) or handler-level 400.
        assert r.status_code in (400, 422), (
            f"expected 400/422 for bad body, got {r.status_code}: {r.text[:300]}"
        )
        assert r.status_code != 204

    def test_final_log_still_clean(self):
        time.sleep(0.5)
        txt = _read_logs()
        n = _count_no_response_returned(txt)
        assert n == 0, (
            f"Backend logs contained {n} 'RuntimeError: No response returned' "
            f"line(s) after full run — should be 0.\n---LOG TAIL---\n{txt[-6000:]}"
        )
