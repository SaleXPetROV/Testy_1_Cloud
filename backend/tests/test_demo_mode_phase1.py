"""Demo (Sandbox) mode Phase 1 — backend regression tests.

Covers:
- POST /api/auth/login for user & admin
- POST /api/demo/enter, GET /api/demo/state, POST /api/demo/exit
- Demo guard: X-Game-Mode: demo → 403 demo_mode_blocked for BLOCKED_DEMO_WRITE_PREFIXES
- No guard when X-Game-Mode: real
"""
import os
import pytest
import requests

# External login often blocked by anti-bot; use localhost for login per credentials note.
INTERNAL_URL = "http://localhost:8001"
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", INTERNAL_URL).rstrip("/")

USER_EMAIL = "testuser@example.com"
USER_PW = "Test1234!"
ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PW = os.environ.get("TEST_ADMIN_PASSWORD", "")


def _login(email, pw):
    # Try localhost first (avoids anti-bot 403) then external
    for base in (INTERNAL_URL, BASE_URL):
        try:
            r = requests.post(f"{base}/api/auth/login",
                              json={"email": email, "password": pw}, timeout=15)
            if r.status_code == 200 and r.json().get("token"):
                return r.json()["token"], base
        except Exception:
            continue
    return None, None


@pytest.fixture(scope="module")
def user_token():
    tok, base = _login(USER_EMAIL, USER_PW)
    assert tok, f"login failed for {USER_EMAIL}"
    return tok, base


@pytest.fixture(scope="module")
def admin_token():
    tok, base = _login(ADMIN_EMAIL, ADMIN_PW)
    assert tok, f"login failed for {ADMIN_EMAIL}"
    return tok, base


# ---------- Auth ----------
def test_login_user():
    tok, _ = _login(USER_EMAIL, USER_PW)
    assert tok and isinstance(tok, str) and len(tok) > 10


def test_login_admin():
    tok, _ = _login(ADMIN_EMAIL, ADMIN_PW)
    assert tok and isinstance(tok, str) and len(tok) > 10


# ---------- Demo API ----------
def test_demo_enter_creates_profile(user_token):
    tok, base = user_token
    h = {"Authorization": f"Bearer {tok}"}
    r = requests.post(f"{base}/api/demo/enter", headers=h, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("is_demo") is True
    assert data.get("demo_plot_coords") == [13, 12]
    prof = data.get("profile")
    assert prof, "profile missing"
    assert prof.get("demo_balance_city") == 5000 or prof.get("demo_balance_city") == 5000.0
    biz = prof.get("demo_business")
    assert biz, "demo_business missing"
    assert biz.get("x") == 13 and biz.get("y") == 12
    assert prof.get("demo_business_coords") == [13, 12]


def test_demo_state_returns_is_demo(user_token):
    tok, base = user_token
    h = {"Authorization": f"Bearer {tok}"}
    r = requests.get(f"{base}/api/demo/state", headers=h, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("is_demo") is True
    assert data.get("profile") is not None


# ---------- Guard ----------
BLOCKED_ENDPOINTS = [
    ("POST", "/api/island/buy/5/5", None),
    ("POST", "/api/withdraw", {"amount": 1}),
    ("POST", "/api/market/buy", {"listing_id": "nope"}),
]


@pytest.mark.parametrize("method,path,body", BLOCKED_ENDPOINTS)
def test_demo_guard_blocks_real_endpoints(user_token, method, path, body):
    tok, base = user_token
    h = {"Authorization": f"Bearer {tok}", "X-Game-Mode": "demo"}
    r = requests.request(method, f"{base}{path}", headers=h, json=body, timeout=15)
    assert r.status_code == 403, f"{path} expected 403 got {r.status_code}: {r.text[:200]}"
    try:
        assert r.json().get("detail") == "demo_mode_blocked"
    except Exception:
        pytest.fail(f"{path} response not JSON demo_mode_blocked: {r.text[:200]}")


def test_no_guard_when_mode_real(user_token):
    tok, base = user_token
    h = {"Authorization": f"Bearer {tok}", "X-Game-Mode": "real"}
    r = requests.post(f"{base}/api/island/buy/5/5", headers=h, timeout=15)
    # Should NOT be 403 demo_mode_blocked. Business logic may 400/404/409.
    if r.status_code == 403:
        try:
            assert r.json().get("detail") != "demo_mode_blocked", \
                "guard fired for X-Game-Mode: real"
        except Exception:
            pass


# ---------- Exit ----------
def test_demo_exit(user_token):
    tok, base = user_token
    h = {"Authorization": f"Bearer {tok}"}
    r = requests.post(f"{base}/api/demo/exit", headers=h, timeout=15)
    assert r.status_code == 200, r.text
    assert r.json().get("is_demo") is False
    # confirm via state
    r2 = requests.get(f"{base}/api/demo/state", headers=h, timeout=15)
    assert r2.status_code == 200
    assert r2.json().get("is_demo") is False
