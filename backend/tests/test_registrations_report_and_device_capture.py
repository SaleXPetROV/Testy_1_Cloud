"""
Tests for Registration Report + IP/Device capture fix.

Covers:
  1. Admin login (sanyanazarov212@gmail.com / {os.environ.get("TEST_ADMIN_PASSWORD", "")}).
  2. Email registration (SMTP off => status "registered" path).
  3. GET /api/admin/registrations returns {stats, registrations}
     with stats.email/google/ton/total keys.
  4. Newly-created user row is present with method "email" and
     ip/device/browser != "Не определено" (i.e. captured at registration).
"""
import os
import uuid
import time
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://ton-metro.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")

UNDEF = "Не определено"

# Realistic browser UA so parser assigns Chrome/Desktop
CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({
        "Content-Type": "application/json",
        "User-Agent": CHROME_UA,
        "X-Forwarded-For": "203.0.113.42",
    })
    return s


@pytest.fixture(scope="module")
def admin_token(session):
    resp = session.post(
        f"{API}/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert resp.status_code == 200, f"Admin login failed: {resp.status_code} {resp.text[:300]}"
    data = resp.json()
    tok = data.get("token") or data.get("access_token")
    assert tok, f"No token in admin login response: {data}"
    return tok


@pytest.fixture(scope="module")
def new_email_user(session):
    """Register a fresh email user via /api/auth/register/initiate (SMTP off => 'registered')."""
    uid = uuid.uuid4().hex[:10]
    username = f"TESTreg{uid}"
    email = f"TEST_reg_{uid}@example.com"
    password = "Test1234!"
    body = {
        "username": username,
        "email": email,
        "password": password,
    }
    resp = session.post(f"{API}/auth/register/initiate", json=body)
    assert resp.status_code == 200, f"register/initiate failed: {resp.status_code} {resp.text[:400]}"
    data = resp.json()
    # IMPORTANT: register/initiate sets a Set-Cookie access_token for the NEW
    # user. If we leave those cookies on the shared session, later admin
    # requests would be authenticated as this new (non-admin) user via the
    # cookie fallback in get_current_user, giving a spurious 403 on admin
    # endpoints. Clear cookies so subsequent admin requests rely only on the
    # Authorization: Bearer header.
    session.cookies.clear()
    return {
        "username": username,
        "email": email,
        "password": password,
        "status": data.get("status"),
        "user_id": (data.get("user") or {}).get("id"),
        "response": data,
    }


# ---- Tests ----

def test_admin_login_ok(admin_token):
    assert isinstance(admin_token, str) and len(admin_token) > 10


def test_email_register_immediate_success(new_email_user):
    # SMTP off in this env => registration completes right away with token
    assert new_email_user["status"] == "registered", (
        f"Expected status 'registered' (SMTP off path); got {new_email_user['status']}: "
        f"{new_email_user['response']}"
    )
    assert new_email_user["user_id"], "No user id returned from register/initiate"


def test_admin_registrations_endpoint_shape(session, admin_token):
    resp = session.get(
        f"{API}/admin/registrations",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, f"admin/registrations failed: {resp.status_code} {resp.text[:300]}"
    data = resp.json()
    assert isinstance(data, dict)
    assert "stats" in data and "registrations" in data
    stats = data["stats"]
    for k in ("email", "google", "ton", "total"):
        assert k in stats, f"Missing stats key {k}: {stats}"
        assert isinstance(stats[k], int)
    assert isinstance(data["registrations"], list)
    # total should equal sum of buckets
    assert stats["total"] == stats["email"] + stats["google"] + stats["ton"], stats


def test_new_user_has_ip_device_browser_captured(session, admin_token, new_email_user):
    # Give the DB write a moment
    time.sleep(1.0)
    resp = session.get(
        f"{API}/admin/registrations",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, resp.text[:300]
    rows = resp.json().get("registrations", [])
    match = next(
        (r for r in rows if (r.get("email") or "").lower() == new_email_user["email"].lower()),
        None,
    )
    assert match is not None, (
        f"Newly-registered user {new_email_user['email']} not found in "
        f"admin/registrations (rows count={len(rows)})"
    )
    assert match["method"] == "email", f"method mismatch: {match}"
    assert match.get("ip") and match["ip"] != UNDEF, f"IP not captured: {match}"
    assert match.get("device") and match["device"] != UNDEF, f"device not captured: {match}"
    assert match.get("browser") and match["browser"] != UNDEF, f"browser not captured: {match}"
    # We sent X-Forwarded-For=203.0.113.42 and a Chrome UA
    assert match["browser"] == "Chrome", f"expected Chrome, got {match['browser']}"
    assert match["device"] == "Desktop", f"expected Desktop, got {match['device']}"
    # IP should reflect X-Forwarded-For first hop
    assert match["ip"] == "203.0.113.42", f"expected 203.0.113.42, got {match['ip']}"


def test_registrations_requires_admin(session):
    # Without auth => unauthorised
    resp = session.get(f"{API}/admin/registrations")
    assert resp.status_code in (401, 403), f"Expected auth error, got {resp.status_code}"


def test_cleanup_delete_test_users(session, admin_token, new_email_user):
    """Best-effort cleanup: try DELETE /api/admin/user/{id} if it exists.
    Not fatal if endpoint does not exist — the test data is prefixed TEST_.
    """
    uid = new_email_user.get("user_id")
    if not uid:
        pytest.skip("no user_id to clean up")
    for url in (
        f"{API}/admin/user/{uid}",
        f"{API}/admin/users/{uid}",
    ):
        resp = session.delete(url, headers={"Authorization": f"Bearer {admin_token}"})
        if resp.status_code in (200, 204):
            return
    # Not being able to delete is not a test failure — data is TEST_-prefixed
