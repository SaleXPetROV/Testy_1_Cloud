"""
Iteration 13 REGRESSION test for /api/referrals/me cross-user leak fix.

Scenarios (from review request):
  1. Register two DIFFERENT new email users via SMTP-off /register/initiate.
     For EACH, GET /api/referrals/me with own bearer -> referral_id == own id,
     count == 0, and users must NOT receive admin's data or each other's.
  2. Admin's /api/referrals/me still returns admin's own referral_id.
  3. Register a new user with referral_code = admin_id: admin's referral list
     count increases and includes the new username; the referred user's
     /api/referrals/me still returns THEIR OWN id (count 0), NOT admin's.
"""
import os
import uuid
import pytest
import requests

if not os.environ.get("REACT_APP_BACKEND_URL"):
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                os.environ["REACT_APP_BACKEND_URL"] = line.split("=", 1)[1].strip()
                break

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")


def _register(referral_code=None, prefix="TEST_iter13"):
    email = f"{prefix}_{uuid.uuid4().hex[:10]}@example.com"
    username = f"i13_{uuid.uuid4().hex[:8]}"
    payload = {
        "email": email,
        "password": "Test1234!",
        "username": username,
        "visitor_id": f"vis_{uuid.uuid4().hex[:8]}",
    }
    if referral_code:
        payload["referral_code"] = referral_code
    r = requests.post(f"{API}/auth/register/initiate", json=payload)
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert body.get("status") == "registered", body
    user = body.get("user") or {}
    return {
        "email": email,
        "username": username,
        "password": "Test1234!",
        "id": user.get("id"),
        "body": body,
    }


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text[:300]
    return r.json().get("access_token") or r.json().get("token")


def _me(token):
    r = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text[:200]
    return r.json()


def _referrals_me(token):
    r = requests.get(f"{API}/referrals/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text[:300]
    return r.json()


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200
    return r.json().get("access_token") or r.json().get("token")


@pytest.fixture(scope="module")
def admin_id(admin_token):
    return _me(admin_token).get("id")


class TestReferralsMeNoLeak:

    def test_two_new_users_get_own_ids_no_leak(self, admin_id):
        """Register two fresh email users. Each must see ONLY their own referral_id."""
        u1 = _register(prefix="TEST_iter13_a")
        u2 = _register(prefix="TEST_iter13_b")

        assert u1["id"] and u2["id"] and u1["id"] != u2["id"]
        assert u1["id"] != admin_id and u2["id"] != admin_id

        t1 = _login(u1["email"], u1["password"])
        t2 = _login(u2["email"], u2["password"])

        # Re-confirm ids via /auth/me
        me1 = _me(t1)
        me2 = _me(t2)
        assert me1["id"] == u1["id"], (me1["id"], u1["id"])
        assert me2["id"] == u2["id"], (me2["id"], u2["id"])

        r1 = _referrals_me(t1)
        r2 = _referrals_me(t2)

        # user1: own id, count 0, no leak of admin or user2
        assert r1["referral_id"] == u1["id"], f"user1 leak: got {r1['referral_id']} expected {u1['id']}"
        assert r1["referral_id"] != admin_id, "user1 leaked admin id"
        assert r1["referral_id"] != u2["id"], "user1 leaked user2 id"
        assert r1["count"] == 0, r1
        assert r1["total_earned_ton"] == 0 and r1["total_earned_city"] == 0
        assert r1["referrals"] == []
        assert r1["referral_path"] == f"/?ref={u1['id']}"

        # user2: own id, count 0, no leak
        assert r2["referral_id"] == u2["id"], f"user2 leak: got {r2['referral_id']} expected {u2['id']}"
        assert r2["referral_id"] != admin_id, "user2 leaked admin id"
        assert r2["referral_id"] != u1["id"], "user2 leaked user1 id"
        assert r2["count"] == 0
        assert r2["referrals"] == []

    def test_admin_referrals_me_still_returns_admin_own_id(self, admin_token, admin_id):
        b = _referrals_me(admin_token)
        assert b["referral_id"] == admin_id, (
            f"admin referrals_me broken: got {b['referral_id']} expected {admin_id}"
        )
        assert b["referral_path"] == f"/?ref={admin_id}"
        # admin has some existing referrals (from previous iterations); just assert non-negative
        assert isinstance(b["count"], int) and b["count"] >= 0

    def test_referred_user_sees_own_id_admin_count_increases(self, admin_token, admin_id):
        # Baseline admin referrals count
        base = requests.get(
            f"{API}/admin/players/{admin_id}/referrals",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert base.status_code == 200, base.text[:200]
        base_count = base.json().get("count", 0)

        # Register a new user carrying referral_code = admin_id
        ref = _register(referral_code=admin_id, prefix="TEST_iter13_boundadmin")
        assert ref["id"] != admin_id

        # Admin referrals list should now include this new username and count++
        r = requests.get(
            f"{API}/admin/players/{admin_id}/referrals",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r.status_code == 200
        rj = r.json()
        assert rj["count"] == base_count + 1, (
            f"admin count did not increment: base={base_count}, now={rj['count']}"
        )
        usernames = [row.get("username") for row in rj["referrals"]]
        assert ref["username"] in usernames, (
            f"expected {ref['username']} in admin referrals list, got sample={usernames[:10]}"
        )

        # Referred user's own /referrals/me must still return THEIR OWN id, count 0
        tok = _login(ref["email"], ref["password"])
        me = _me(tok)
        assert me["id"] == ref["id"]
        rm = _referrals_me(tok)
        assert rm["referral_id"] == ref["id"], (
            f"LEAK: referred user got referral_id={rm['referral_id']} expected {ref['id']}"
        )
        assert rm["referral_id"] != admin_id
        assert rm["count"] == 0
        assert rm["referrals"] == []
