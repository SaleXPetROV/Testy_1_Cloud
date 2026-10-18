"""
Iteration 4 backend tests for TON_CITY v2.3 login + notifications 401 fix.

IMPORTANT: These tests must be run SERIALLY because the backend enforces
"single active session per user" (session_id in the JWT vs. the db.users row).
Multiple parallel logins for the same test user invalidate one another and
produce spurious 401 session_invalidated responses. Run with:

    python -m pytest tests/test_auth_kick_dedupe_iter4.py -n 0 -v

Covers the specific behaviors requested in the review:
  1. POST /api/auth/login for admin returns 200 + token + is_admin=true.
  2. POST /api/auth/login for regular user returns 200 + token + is_admin=false.
  3. GET /api/auth/me with valid Bearer returns 200 for both roles.
  4. GET /api/notifications/unread_count and /low-durability with valid Bearer
     return 200.
  5. Same endpoints without a Bearer token return 401.
  6. GET /api/maintenance-status is public (200).
  7. POST /api/auth/verify-wallet exists at that path.
  8. Bearer token is stable across sequential /api/auth/me calls (no spurious
     'session_invalidated' when the user is only logged-in from one place).
"""

import os
import pytest
import requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://ton-metropolis-5.preview.emergentagent.com",
).rstrip("/")

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PASSWORD = "Test1234!"


def _fresh_client():
    """Fresh session per test — never share cookies between logins."""
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _login(email, password):
    client = _fresh_client()
    r = client.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        timeout=30,
    )
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text[:200]}"
    data = r.json()
    assert "token" in data and isinstance(data["token"], str) and len(data["token"]) > 20
    return data


# ------------ maintenance-status is public ------------
def test_maintenance_status_public():
    r = requests.get(f"{BASE_URL}/api/maintenance-status", timeout=15)
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert isinstance(body, dict)
    assert ("enabled" in body) or ("is_enabled" in body) or ("active" in body)


# ------------ auth login for both roles ------------
def test_admin_login_returns_token_and_is_admin_true():
    data = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    top = data.get("is_admin")
    nested = (data.get("user") or {}).get("is_admin")
    assert top is True or nested is True, f"expected is_admin true, got: {data}"


def test_user_login_returns_token_and_is_admin_false():
    data = _login(USER_EMAIL, USER_PASSWORD)
    top = data.get("is_admin")
    nested = (data.get("user") or {}).get("is_admin")
    assert not (top is True or nested is True), f"regular user should not be admin: {data}"


def test_login_bad_password_401():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": USER_EMAIL, "password": "definitely-wrong-XYZ"},
        timeout=15,
    )
    assert r.status_code in (400, 401, 403), r.text[:200]


# ------------ /api/auth/me + is_admin flag ------------
def test_auth_me_admin_returns_is_admin_true():
    data = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    # Use a completely fresh (cookie-less) client so only Bearer is sent.
    r = requests.get(
        f"{BASE_URL}/api/auth/me",
        headers={"Authorization": f"Bearer {data['token']}"},
        timeout=15,
    )
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert body.get("is_admin") is True, f"admin flag wrong: {body}"
    assert body.get("email") == ADMIN_EMAIL


def test_auth_me_user_returns_is_admin_false():
    data = _login(USER_EMAIL, USER_PASSWORD)
    r = requests.get(
        f"{BASE_URL}/api/auth/me",
        headers={"Authorization": f"Bearer {data['token']}"},
        timeout=15,
    )
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert body.get("is_admin") in (False, None), f"user should not be admin: {body}"
    assert body.get("email") == USER_EMAIL


def test_auth_me_no_token_401():
    # No cookies, no bearer.
    r = requests.get(f"{BASE_URL}/api/auth/me", timeout=15)
    assert r.status_code == 401, f"expected 401, got {r.status_code} {r.text[:200]}"


# ------------ notifications endpoints ------------
def test_unread_count_with_token_200():
    data = _login(USER_EMAIL, USER_PASSWORD)
    r = requests.get(
        f"{BASE_URL}/api/notifications/unread_count",
        headers={"Authorization": f"Bearer {data['token']}"},
        timeout=15,
    )
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert isinstance(body, dict)
    assert (
        "unread_count" in body or "count" in body or "unread" in body
    ), f"unexpected shape: {body}"


def test_low_durability_with_token_200():
    data = _login(USER_EMAIL, USER_PASSWORD)
    r = requests.get(
        f"{BASE_URL}/api/notifications/low-durability",
        headers={"Authorization": f"Bearer {data['token']}"},
        timeout=15,
    )
    assert r.status_code == 200, r.text[:300]


def test_unread_count_no_token_401():
    r = requests.get(f"{BASE_URL}/api/notifications/unread_count", timeout=15)
    assert r.status_code == 401, f"expected 401, got {r.status_code}"


def test_low_durability_no_token_401():
    r = requests.get(f"{BASE_URL}/api/notifications/low-durability", timeout=15)
    assert r.status_code == 401, f"expected 401, got {r.status_code}"


# ------------ wallet verify endpoint exists ------------
def test_verify_wallet_route_exists():
    r = requests.post(f"{BASE_URL}/api/auth/verify-wallet", json={}, timeout=15)
    assert r.status_code != 404, "verify-wallet missing at /api/auth/verify-wallet"
    assert r.status_code in (400, 401, 403, 422), (
        f"unexpected status {r.status_code}: {r.text[:300]}"
    )


# ------------ session stability sanity check (kick UX regression) ------------
def test_repeated_auth_me_with_same_token_is_stable():
    """
    The kick-UX bug fired because /api/auth/me could 401 with
    'session_invalidated' if the session was intermittently missing. After
    a single login the token must remain valid for many sequential /auth/me
    reads without producing session_invalidated (backend precondition of the
    frontend fix).
    """
    data = _login(USER_EMAIL, USER_PASSWORD)
    h = {"Authorization": f"Bearer {data['token']}"}
    for i in range(4):
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=h, timeout=15)
        assert r.status_code == 200, (
            f"token invalidated on iteration {i}: {r.status_code} {r.text[:200]}"
        )
