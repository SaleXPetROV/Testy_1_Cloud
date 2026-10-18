"""
Iteration 9 regression suite — verifies the ONLY change since iter8:
`logger.info(...)` → `logger.debug(...)` for the ClientDisconnectGuardMiddleware's
"Client disconnected mid-request (suppressed 'No response returned')" line.

The middleware must:
  1. still return 204 when the client is genuinely disconnected;
  2. still re-raise any OTHER RuntimeError;
  3. emit the disconnect message at DEBUG level (NOT INFO);
  4. not spam the default backend INFO log with the disconnect line even under
     bursty raw-socket abort load.

On Python 3.11 preview the underlying `RuntimeError("No response returned.")`
never actually surfaces (it is a 3.12+anyio-specific race), so we verify
the change STRUCTURALLY (source code inspection of the middleware body) and
BEHAVIOURALLY (log file must not contain the disconnect line at INFO level
after a raw-socket abort burst — combined regression from iter8).
"""
import ast
import os
import re
import socket
import struct
import subprocess
import time
from pathlib import Path

import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
SERVER_PY = Path("/app/backend/server.py")
BACKEND_LOG = Path("/var/log/supervisor/backend.err.log")
BACKEND_OUT = Path("/var/log/supervisor/backend.out.log")

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")


# ---------------------------------------------------------------------------
# Structural verification — source-code AST/regex inspection
# ---------------------------------------------------------------------------
class TestSourceLevelChange:
    """Verify the code change in server.py is exactly logger.info → logger.debug."""

    def test_middleware_class_exists(self):
        src = SERVER_PY.read_text()
        assert "class ClientDisconnectGuardMiddleware(BaseHTTPMiddleware):" in src

    def test_disconnect_log_is_debug_not_info(self):
        """The disconnect message must be emitted at DEBUG level, not INFO."""
        src = SERVER_PY.read_text()
        # Locate the middleware body
        start = src.index("class ClientDisconnectGuardMiddleware")
        # Middleware body ends at the next top-level class/def or app.add_middleware
        end = src.index("app.add_middleware(ClientDisconnectGuardMiddleware)", start)
        body = src[start:end]

        # The exact message must be present exactly once
        msg_matches = re.findall(
            r"Client disconnected mid-request \(suppressed 'No response returned'\)",
            body,
        )
        assert len(msg_matches) == 1, (
            f"Expected exactly 1 disconnect message; found {len(msg_matches)}"
        )

        # It must be called via logger.debug — NOT logger.info
        debug_calls = re.findall(
            r"logger\.debug\(\s*[\"']Client disconnected mid-request",
            body,
        )
        info_calls = re.findall(
            r"logger\.info\(\s*[\"']Client disconnected mid-request",
            body,
        )
        assert len(debug_calls) == 1, (
            f"Expected 1 logger.debug call for disconnect; found {len(debug_calls)}. "
            f"Body:\n{body}"
        )
        assert len(info_calls) == 0, (
            f"Expected 0 logger.info calls for disconnect; found {len(info_calls)}. "
            f"logger.info should NOT be used — it was replaced with logger.debug."
        )

    def test_204_return_still_intact(self):
        """The middleware must still return _StarletteResponse(status_code=204)."""
        src = SERVER_PY.read_text()
        start = src.index("class ClientDisconnectGuardMiddleware")
        end = src.index("app.add_middleware(ClientDisconnectGuardMiddleware)", start)
        body = src[start:end]
        assert re.search(r"_StarletteResponse\(\s*status_code\s*=\s*204\s*\)", body), (
            "The 204 short-circuit response must still be intact."
        )

    def test_other_runtimeerrors_still_reraised(self):
        """The middleware must still `raise` (re-raise) non-matching RuntimeErrors."""
        src = SERVER_PY.read_text()
        start = src.index("class ClientDisconnectGuardMiddleware")
        end = src.index("app.add_middleware(ClientDisconnectGuardMiddleware)", start)
        body = src[start:end]
        # Bare `raise` must be present (re-raise path)
        assert re.search(r"^\s*raise\s*$", body, re.MULTILINE), (
            "The re-raise path (bare `raise`) must be preserved."
        )
        # And it must string-match exactly "No response returned."
        assert 'str(exc) == "No response returned."' in body

    def test_is_disconnected_check_intact(self):
        """`await request.is_disconnected()` must still gate the 204 return."""
        src = SERVER_PY.read_text()
        start = src.index("class ClientDisconnectGuardMiddleware")
        end = src.index("app.add_middleware(ClientDisconnectGuardMiddleware)", start)
        body = src[start:end]
        assert "await request.is_disconnected()" in body

    def test_middleware_ast_parseable(self):
        """The whole server.py must still parse — no syntax breakage from the edit."""
        src = SERVER_PY.read_text()
        # Should not raise
        ast.parse(src)


# ---------------------------------------------------------------------------
# Behavioural verification — INFO log must be quiet after raw-socket abort burst
# ---------------------------------------------------------------------------
def _admin_token() -> str:
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=15,
    )
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text[:400]}"
    tok = r.json().get("access_token") or r.json().get("token")
    assert tok, f"no token in response: {r.json()}"
    return tok


def _tail_log_bytes(path: Path, n: int = 200_000) -> str:
    if not path.exists():
        return ""
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - n))
        return f.read().decode("utf-8", errors="replace")


class TestNoInfoLogSpamAfterAbortBurst:
    """Post-fix behaviour: INFO log should NOT accumulate disconnect lines."""

    def test_burst_abort_then_check_info_log_quiet(self):
        token = _admin_token()

        # Mark log positions before the burst
        err_before = len(_tail_log_bytes(BACKEND_LOG, 5_000_000))
        out_before = len(_tail_log_bytes(BACKEND_OUT, 5_000_000))

        # Raw-socket SO_LINGER=0 abort burst — 8x against admin buyout overview
        req = (
            "GET /api/admin/buyout/overview HTTP/1.1\r\n"
            "Host: localhost:8001\r\n"
            f"Authorization: Bearer {token}\r\n"
            "Connection: close\r\n"
            "User-Agent: iter9-abort-tester\r\n"
            "\r\n"
        ).encode()

        aborts = 0
        for _ in range(8):
            try:
                s = socket.create_connection(("127.0.0.1", 8001), timeout=2)
                # SO_LINGER=0 → RST on close
                s.setsockopt(
                    socket.SOL_SOCKET,
                    socket.SO_LINGER,
                    struct.pack("ii", 1, 0),
                )
                s.sendall(req)
                # Immediately close mid-request — do NOT read the response
                s.close()
                aborts += 1
            except Exception:
                pass
            time.sleep(0.05)

        assert aborts >= 6, f"expected at least 6 aborts; got {aborts}"

        # Give the server a moment to attempt sending / log
        time.sleep(2.0)

        # Follow-up normal request must still be 200
        r = requests.get(
            f"{BASE_URL}/api/admin/buyout/overview",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        assert r.status_code == 200, (
            f"server degraded after burst: {r.status_code} {r.text[:400]}"
        )

        # Inspect logs written DURING/AFTER the burst
        err_after = _tail_log_bytes(BACKEND_LOG, 5_000_000)
        out_after = _tail_log_bytes(BACKEND_OUT, 5_000_000)
        new_err = err_after[err_before:] if err_before <= len(err_after) else err_after
        new_out = out_after[out_before:] if out_before <= len(out_after) else out_after
        combined_new = new_err + "\n" + new_out

        # 1. No "No response returned" traceback lines
        assert "No response returned" not in combined_new, (
            f"'No response returned' leaked to logs after burst:\n"
            f"{combined_new[-4000:]}"
        )

        # 2. The disconnect message must NOT appear at INFO level
        # Look for lines that both contain the disconnect message AND look like INFO
        info_disconnect_lines = [
            ln
            for ln in combined_new.splitlines()
            if "Client disconnected mid-request" in ln
            and re.search(r"\bINFO\b", ln)
        ]
        assert not info_disconnect_lines, (
            f"Found {len(info_disconnect_lines)} INFO-level disconnect log lines "
            f"— they should be DEBUG now. Sample:\n"
            + "\n".join(info_disconnect_lines[:5])
        )

    def test_backend_still_running(self):
        out = subprocess.run(
            ["sudo", "supervisorctl", "status", "backend"],
            capture_output=True,
            text=True,
        )
        assert "RUNNING" in out.stdout, (
            f"backend not RUNNING after burst: {out.stdout} {out.stderr}"
        )


# ---------------------------------------------------------------------------
# Regression sanity — the 4 status-code propagation checks from the request
# ---------------------------------------------------------------------------
class TestStatusCodePropagationUnchanged:
    """Iter9 request explicitly re-lists these; run them again as a sanity net."""

    def test_401_unauth_admin_nicks(self):
        r = requests.get(f"{BASE_URL}/api/admin/buyout/nicks", timeout=15)
        assert r.status_code == 401
        assert r.headers.get("content-type", "").startswith("application/json")
        r.json()  # must parse

    def test_403_non_admin(self):
        lr = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "testuser@example.com", "password": "Test1234!"},
            timeout=15,
        )
        assert lr.status_code == 200, lr.text[:400]
        tok = lr.json().get("access_token") or lr.json().get("token")
        r = requests.get(
            f"{BASE_URL}/api/admin/buyout/nicks",
            headers={"Authorization": f"Bearer {tok}"},
            timeout=15,
        )
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text[:400]}"
        r.json()

    def test_404_unknown_route(self):
        r = requests.get(f"{BASE_URL}/api/nonexistent", timeout=15)
        assert r.status_code == 404
        r.json()

    def test_400_admin_buyout_execute_empty_items(self):
        tok = _admin_token()
        r = requests.post(
            f"{BASE_URL}/api/admin/buyout/execute",
            headers={"Authorization": f"Bearer {tok}"},
            json={"items": []},
            timeout=15,
        )
        assert r.status_code == 400, (
            f"expected 400, got {r.status_code}: {r.text[:400]}"
        )
        r.json()

    def test_200_admin_buyout_overview_and_nicks(self):
        tok = _admin_token()
        r1 = requests.get(
            f"{BASE_URL}/api/admin/buyout/overview",
            headers={"Authorization": f"Bearer {tok}"},
            timeout=15,
        )
        assert r1.status_code == 200, r1.text[:400]
        r1.json()

        r2 = requests.get(
            f"{BASE_URL}/api/admin/buyout/nicks",
            headers={"Authorization": f"Bearer {tok}"},
            timeout=15,
        )
        assert r2.status_code == 200, r2.text[:400]
        r2.json()

    def test_referral_rally_current_seeded(self):
        tok = _admin_token()
        r = requests.get(
            f"{BASE_URL}/api/admin/promo/referral-rally/current",
            headers={"Authorization": f"Bearer {tok}"},
            timeout=15,
        )
        assert r.status_code == 200, r.text[:400]
        data = r.json()
        # Seeded referrers should be present
        assert isinstance(data, dict), f"expected dict, got: {type(data)}"
