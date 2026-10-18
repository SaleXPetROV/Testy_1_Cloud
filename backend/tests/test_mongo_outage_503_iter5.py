"""
Iteration 5 — Graceful 503 handling when MongoDB is unreachable.

Scenarios:
  1. REGRESSION (Mongo UP): /api/ health = 200, admin login works, admin buyout
     endpoints return 200.
  2. GRACEFUL 503 (Mongo DOWN): after `supervisorctl stop mongodb`, authenticated
     DB-touching endpoints return HTTP 503 (JSON detail mentions DB unavailable),
     NOT 500, and the response returns within ~6s (well under a 10s hang).
     Backend process must remain RUNNING across multiple such requests.
  3. POST-RECOVERY: after restart + short wait, endpoints return 200 again and
     demo data is intact (re-seed if needed).

IMPORTANT: this test intentionally stops MongoDB. It ALWAYS restarts it in a
`finally` block / teardown fixture so the app is left healthy.
"""

import os
import subprocess
import sys
import time
import pytest
import requests


# --------------------- config ---------------------

def _load_base_url():
    u = os.environ.get("REACT_APP_BACKEND_URL")
    if not u:
        try:
            with open("/app/frontend/.env") as f:
                for line in f:
                    if line.startswith("REACT_APP_BACKEND_URL="):
                        u = line.split("=", 1)[1].strip()
                        break
        except FileNotFoundError:
            pass
    assert u, "REACT_APP_BACKEND_URL not set"
    return u.rstrip("/")


BASE_URL = _load_base_url()
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")


# --------------------- helpers ---------------------

def _supervisor(action, program):
    r = subprocess.run(
        ["sudo", "supervisorctl", action, program],
        capture_output=True, text=True, timeout=30,
    )
    return r.returncode, r.stdout + r.stderr


def _supervisor_status(program):
    r = subprocess.run(
        ["sudo", "supervisorctl", "status", program],
        capture_output=True, text=True, timeout=10,
    )
    return r.stdout.strip()


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
    return r.json()["token"]


# --------------------- fixtures ---------------------

@pytest.fixture(scope="module")
def admin_token():
    """Get admin token BEFORE stopping mongo (login needs the DB)."""
    return _login(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="module", autouse=True)
def _ensure_mongo_up_at_end():
    """Safety net — always restart mongo + re-seed demo data at teardown."""
    yield
    print("\n[teardown] ensuring mongodb is RUNNING")
    _supervisor("start", "mongodb")
    time.sleep(6)
    # Re-seed demo data
    try:
        subprocess.run(
            [sys.executable, "seed_buyout_demo.py"],
            cwd="/app/backend",
            check=False,
            capture_output=True,
            timeout=60,
        )
    except Exception as e:
        print(f"[teardown] reseed error: {e}")
    print("[teardown] mongodb status:", _supervisor_status("mongodb"))


# --------------------- 1. REGRESSION (Mongo UP) ---------------------

class TestRegressionMongoUp:
    def test_health_endpoint_200(self):
        r = requests.get(f"{API}/", timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "message" in body

    def test_admin_login_ok(self):
        tok = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
        assert isinstance(tok, str) and len(tok) > 20

    def test_admin_buyout_overview_200(self, admin_token):
        h = {"Authorization": f"Bearer {admin_token}"}
        r = requests.get(f"{API}/admin/buyout/overview", headers=h, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "stats" in data and "rows" in data

    def test_admin_buyout_nicks_200(self, admin_token):
        h = {"Authorization": f"Bearer {admin_token}"}
        r = requests.get(f"{API}/admin/buyout/nicks", headers=h, timeout=15)
        assert r.status_code == 200, r.text
        assert len(r.json()["nicks"]) == 50

    def test_backend_running(self):
        assert "RUNNING" in _supervisor_status("backend")


# --------------------- 2. GRACEFUL 503 (Mongo DOWN) ---------------------

class TestGraceful503WhenMongoDown:
    """Stop mongodb, hit authenticated DB-touching endpoint, expect 503.

    The class scope keeps mongo DOWN across this class's tests and starts it
    in teardown.
    """

    @pytest.fixture(scope="class", autouse=True)
    def stop_mongo(self, admin_token):
        # Sanity: mongo up before we stop it
        assert "RUNNING" in _supervisor_status("mongodb"), "mongodb not RUNNING before test"

        code, out = _supervisor("stop", "mongodb")
        print(f"[stop_mongo] code={code} out={out.strip()}")
        # give supervisor a moment to actually stop the process
        time.sleep(2.0)
        try:
            yield
        finally:
            code, out = _supervisor("start", "mongodb")
            print(f"[start_mongo] code={code} out={out.strip()}")
            # wait for mongod to actually become responsive
            for _ in range(20):
                time.sleep(1)
                if "RUNNING" in _supervisor_status("mongodb"):
                    break
            time.sleep(3)  # extra grace for driver to reconnect

    def test_mongo_actually_down(self):
        st = _supervisor_status("mongodb")
        assert "STOPPED" in st or "EXITED" in st or "FATAL" in st, \
            f"mongodb should be stopped, got: {st}"

    def test_authenticated_endpoint_returns_503_not_500(self, admin_token):
        """Primary path: get_current_user → db.users.find_one → PyMongoError → 503."""
        h = {"Authorization": f"Bearer {admin_token}"}
        t0 = time.time()
        r = requests.get(f"{API}/admin/buyout/overview", headers=h, timeout=15)
        elapsed = time.time() - t0
        print(f"[503 test] status={r.status_code} elapsed={elapsed:.2f}s body={r.text[:200]}")

        # MUST be 503 (not 500, not an unhandled ASGI error)
        assert r.status_code == 503, \
            f"expected 503 when mongo down, got {r.status_code}: {r.text[:200]}"
        # JSON body mentions DB unavailability
        try:
            body = r.json()
        except Exception:
            pytest.fail(f"response not JSON: {r.text[:200]}")
        detail = str(body.get("detail", "")).lower()
        assert any(kw in detail for kw in ["база данных", "database", "недоступ", "unavailable"]), \
            f"detail should mention DB unavailable, got: {body}"
        # Failure must occur within ~6s (5000ms serverSelectionTimeoutMS + a bit)
        assert elapsed < 8.0, f"response took too long ({elapsed:.2f}s) — timeout tuning off"

    def test_second_endpoint_also_503(self, admin_token):
        """Nicks endpoint also touches DB — must also 503, not 500/hang."""
        h = {"Authorization": f"Bearer {admin_token}"}
        t0 = time.time()
        r = requests.get(f"{API}/admin/buyout/nicks", headers=h, timeout=15)
        elapsed = time.time() - t0
        print(f"[503 nicks] status={r.status_code} elapsed={elapsed:.2f}s")
        assert r.status_code == 503, f"expected 503, got {r.status_code}: {r.text[:200]}"
        assert elapsed < 8.0

    def test_history_transactions_returns_503(self, admin_token):
        """/api/history/transactions is another DB-hitting authenticated route."""
        h = {"Authorization": f"Bearer {admin_token}"}
        t0 = time.time()
        r = requests.get(f"{API}/history/transactions?limit=5", headers=h, timeout=15)
        elapsed = time.time() - t0
        print(f"[503 history] status={r.status_code} elapsed={elapsed:.2f}s")
        # Some endpoints may respond 401 (if middleware runs before DB) — the
        # required behavior for DB-dependent path is 503 (not 500).
        assert r.status_code != 500, \
            f"MUST NOT be 500 (unhandled ASGI) — got 500: {r.text[:200]}"
        assert r.status_code in (503, 401), \
            f"expected 503 (or 401 if auth-only path), got {r.status_code}: {r.text[:200]}"
        assert elapsed < 8.0

    def test_backend_still_running_after_multiple_503s(self, admin_token):
        """Fire several requests; backend must NOT crash."""
        h = {"Authorization": f"Bearer {admin_token}"}
        for i in range(3):
            r = requests.get(f"{API}/admin/buyout/overview", headers=h, timeout=15)
            assert r.status_code == 503, f"iter {i}: {r.status_code}"
        assert "RUNNING" in _supervisor_status("backend"), "backend crashed during outage"

    def test_public_health_endpoint_still_responds(self):
        """/api/ does not touch DB — must still respond 200 even while mongo is down."""
        r = requests.get(f"{API}/", timeout=10)
        # Health endpoint returns a hardcoded JSON — should stay 200
        assert r.status_code == 200, f"health endpoint failed while mongo down: {r.status_code}"


# --------------------- 3. POST-RECOVERY REGRESSION ---------------------

class TestPostRecovery:
    """After the previous class restarts mongo in teardown, verify the app
    fully recovers.  The module-level `_ensure_mongo_up_at_end` also guards
    this."""

    def test_mongo_running_again(self):
        # Fresh call — ensure mongo came back up
        for _ in range(10):
            if "RUNNING" in _supervisor_status("mongodb"):
                break
            time.sleep(1)
        assert "RUNNING" in _supervisor_status("mongodb")

    def test_admin_login_works_again(self):
        tok = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
        assert tok and len(tok) > 20

    def test_admin_buyout_overview_200_again(self):
        tok = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
        h = {"Authorization": f"Bearer {tok}"}
        # Give the driver a moment to reconnect if needed
        last = None
        for _ in range(6):
            r = requests.get(f"{API}/admin/buyout/overview", headers=h, timeout=15)
            last = r
            if r.status_code == 200:
                break
            time.sleep(2)
        assert last.status_code == 200, f"post-recovery still failing: {last.status_code} {last.text[:200]}"
        data = last.json()
        assert "rows" in data

    def test_demo_data_present_or_reseed(self):
        # If overview is empty (fresh DB), re-seed demo data
        tok = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
        h = {"Authorization": f"Bearer {tok}"}
        r = requests.get(f"{API}/admin/buyout/overview", headers=h, timeout=15)
        assert r.status_code == 200
        rows = r.json().get("rows", [])
        if len(rows) < 3:
            subprocess.run(
                [sys.executable, "seed_buyout_demo.py"],
                cwd="/app/backend",
                check=True,
                capture_output=True,
                timeout=60,
            )
            time.sleep(1)
            r2 = requests.get(f"{API}/admin/buyout/overview", headers=h, timeout=15)
            rows = r2.json().get("rows", [])
        assert len(rows) >= 3, f"expected demo rows, got {len(rows)}"
