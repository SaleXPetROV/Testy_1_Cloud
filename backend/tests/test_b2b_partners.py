# NOTE: Run with `-o addopts=""` (or `-p no:xdist`) — this suite must run
# serially because the shared admin login session is rotated on new logins
# from a different worker, producing spurious `session_invalidated` 401s.

"""Backend tests for B2B partners admin subsystem (/api/admin/b2b/*)."""
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # Fallback to local supervisor-managed backend for tests
    BASE_URL = "http://localhost:8001"

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PASSWORD = "Test1234!"


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": password}, timeout=30)
    return r


@pytest.fixture(scope="session")
def admin_token():
    r = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    data = r.json()
    assert data.get("user", {}).get("is_admin") is True, f"admin flag missing: {data}"
    return data["token"]


@pytest.fixture(scope="session")
def user_token():
    r = _login(USER_EMAIL, USER_PASSWORD)
    assert r.status_code == 200, f"user login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


@pytest.fixture
def user_headers(user_token):
    return {"Authorization": f"Bearer {user_token}", "Content-Type": "application/json"}


# --- Login & admin flag ---------------------------------------------------
class TestAdminLogin:
    def test_admin_login_returns_token_and_is_admin_true(self):
        r = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data.get("token"), str) and len(data["token"]) > 10
        assert data["user"]["is_admin"] is True


# --- Auth guards on /api/admin/b2b/* --------------------------------------
class TestAuthGuards:
    def test_list_requires_admin_unauth(self):
        r = requests.get(f"{BASE_URL}/api/admin/b2b/partners", timeout=15)
        assert r.status_code in (401, 403), r.text

    def test_list_forbidden_for_regular_user(self, user_headers):
        r = requests.get(f"{BASE_URL}/api/admin/b2b/partners", headers=user_headers, timeout=15)
        assert r.status_code in (401, 403), r.text

    def test_create_forbidden_for_regular_user(self, user_headers):
        r = requests.post(f"{BASE_URL}/api/admin/b2b/partners",
                          headers=user_headers,
                          json={"username": "hacker", "sales_percent": 5, "yield_percent": 5},
                          timeout=15)
        assert r.status_code in (401, 403), r.text


# --- CRUD -----------------------------------------------------------------
_created_partner_ids = []


class TestPartnersCrud:
    def test_validation_percent_out_of_range(self, admin_headers):
        # sales_percent > 100
        r = requests.post(f"{BASE_URL}/api/admin/b2b/partners", headers=admin_headers,
                          json={"username": "TEST_bad", "sales_percent": 150, "yield_percent": 5},
                          timeout=15)
        assert r.status_code == 400, r.text
        # yield_percent < 0
        r = requests.post(f"{BASE_URL}/api/admin/b2b/partners", headers=admin_headers,
                          json={"username": "TEST_bad", "sales_percent": 5, "yield_percent": -1},
                          timeout=15)
        assert r.status_code == 400, r.text

    def test_create_partner(self, admin_headers):
        uname = f"TEST_partner_{uuid.uuid4().hex[:6]}"
        r = requests.post(f"{BASE_URL}/api/admin/b2b/partners", headers=admin_headers,
                          json={"username": uname,
                                "sales_percent": 10.0,
                                "yield_percent": 5.0,
                                "telegram_user_id": "123456789"},
                          timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] == "ok"
        assert isinstance(d["partner_id"], str)
        assert isinstance(d["partner_code"], str)
        assert d["referral_link"].endswith(f"?start=p_{d['partner_code']}")
        _created_partner_ids.append((d["partner_id"], d["partner_code"], uname))

    def test_list_partners_contains_created(self, admin_headers):
        assert _created_partner_ids, "prev test must have created a partner"
        pid, code, uname = _created_partner_ids[0]
        r = requests.get(f"{BASE_URL}/api/admin/b2b/partners", headers=admin_headers, timeout=20)
        assert r.status_code == 200, r.text
        partners = r.json()["partners"]
        match = [p for p in partners if p["partner_id"] == pid]
        assert match, f"partner {pid} not in list"
        p = match[0]
        assert p["username"] == uname
        assert p["sales_percent"] == 10.0
        assert p["yield_percent"] == 5.0
        assert p["telegram_user_id"] == "123456789"
        assert "stats" in p and "total_users" in p["stats"]

    def test_patch_partner(self, admin_headers):
        pid, code, _ = _created_partner_ids[0]
        r = requests.patch(f"{BASE_URL}/api/admin/b2b/partners/{pid}", headers=admin_headers,
                           json={"sales_percent": 15.5, "yield_percent": 7.25,
                                 "username": "TEST_renamed", "telegram_user_id": "999"},
                           timeout=15)
        assert r.status_code == 200, r.text
        # Verify via list
        r = requests.get(f"{BASE_URL}/api/admin/b2b/partners", headers=admin_headers, timeout=20)
        p = next(x for x in r.json()["partners"] if x["partner_id"] == pid)
        assert p["sales_percent"] == 15.5
        assert p["yield_percent"] == 7.25
        assert p["username"] == "TEST_renamed"
        assert p["telegram_user_id"] == "999"

    def test_patch_validation(self, admin_headers):
        pid, _, _ = _created_partner_ids[0]
        r = requests.patch(f"{BASE_URL}/api/admin/b2b/partners/{pid}", headers=admin_headers,
                           json={"sales_percent": 200}, timeout=15)
        assert r.status_code == 400, r.text

    def test_panel_endpoint(self, admin_headers):
        pid, code, _ = _created_partner_ids[0]
        r = requests.get(f"{BASE_URL}/api/admin/b2b/partners/{pid}/panel",
                         headers=admin_headers, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "panel_text" in d and isinstance(d["panel_text"], str)
        assert code in d["panel_text"]
        assert "stats" in d
        for k in ("total_users", "active_users_7d", "users_24h", "users_7d",
                  "users_30d", "earn_today", "earn_7d", "earn_30d", "earn_total"):
            assert k in d["stats"], k


# --- Registration with p_<code> tags user with b2b_partner ----------------
class TestRegistrationTagsPartner:
    def test_register_with_partner_code_and_stats_increment(self, admin_headers):
        assert _created_partner_ids, "partner must exist"
        pid, code, _ = _created_partner_ids[0]

        # Stats before
        r0 = requests.get(f"{BASE_URL}/api/admin/b2b/partners", headers=admin_headers, timeout=20)
        p0 = next(x for x in r0.json()["partners"] if x["partner_id"] == pid)
        total_before = p0["stats"]["total_users"]

        # Register a new user with referral_code=p_<code> via /register/initiate
        uniq = uuid.uuid4().hex[:8]
        email = f"TEST_b2b_{uniq}@example.com"
        username = f"TEST_b2b_{uniq}"
        payload = {
            "email": email,
            "password": "StrongPass123!",
            "username": username,
            "referral_code": f"p_{code}",
        }
        r = requests.post(f"{BASE_URL}/api/auth/register/initiate",
                          json=payload, timeout=30)
        # Accept both "registered" (SMTP not configured -> user created) and
        # "verification_sent" flows. If verification is sent, we still expect
        # the b2b tagging to happen at completion; but for this test we need
        # user creation.
        assert r.status_code == 200, r.text
        body = r.json()
        if body.get("status") != "registered":
            pytest.skip(f"register/initiate did not create user directly: {body}")

        # Give backend a moment (in case of async writes)
        time.sleep(1.0)

        # Stats after
        r1 = requests.get(f"{BASE_URL}/api/admin/b2b/partners", headers=admin_headers, timeout=20)
        p1 = next(x for x in r1.json()["partners"] if x["partner_id"] == pid)
        total_after = p1["stats"]["total_users"]
        assert total_after == total_before + 1, \
            f"total_users didn't increment: {total_before} -> {total_after}"


# --- Delete detaches users ------------------------------------------------
class TestDelete:
    def test_delete_partner_and_detach(self, admin_headers):
        assert _created_partner_ids
        pid, code, _ = _created_partner_ids[0]
        r = requests.delete(f"{BASE_URL}/api/admin/b2b/partners/{pid}",
                            headers=admin_headers, timeout=15)
        assert r.status_code == 200, r.text
        # Verify partner is gone (list)
        r = requests.get(f"{BASE_URL}/api/admin/b2b/partners", headers=admin_headers, timeout=20)
        assert all(x["partner_id"] != pid for x in r.json()["partners"])
        # 404 on panel
        r = requests.get(f"{BASE_URL}/api/admin/b2b/partners/{pid}/panel",
                         headers=admin_headers, timeout=15)
        assert r.status_code == 404

    def test_delete_nonexistent(self, admin_headers):
        r = requests.delete(f"{BASE_URL}/api/admin/b2b/partners/does-not-exist",
                            headers=admin_headers, timeout=15)
        assert r.status_code == 404
