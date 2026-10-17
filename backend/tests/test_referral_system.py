"""
Referral System tests (Iteration 12)
- Registration binding of referrerId
- Self-referral / invalid code -> referrerId = null
- Immutability: no player-update route can change referrerId
- GET /api/referrals/me (player) response shape
- GET /api/admin/players/{player_id}/referrals (admin) response shape
- Admin binding verification: admin's referrals list includes the referred user

Notes:
- SMTP is off => POST /api/auth/register/initiate returns status='registered' immediately.
- Base URL from REACT_APP_BACKEND_URL. All routes under /api.
- register/initiate returns a Set-Cookie access_token; MUST clear before using
  admin session on same requests.Session (get_current_user prefers cookie).
"""
import os
import uuid
import time
import pytest
import requests

# Load REACT_APP_BACKEND_URL from frontend/.env if not in os.environ
if not os.environ.get("REACT_APP_BACKEND_URL"):
    try:
        with open("/app/frontend/.env") as _f:
            for _line in _f:
                if _line.startswith("REACT_APP_BACKEND_URL="):
                    os.environ["REACT_APP_BACKEND_URL"] = _line.split("=", 1)[1].strip()
                    break
    except Exception:
        pass

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")


def _login(email, password):
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": password},
    )
    return r


@pytest.fixture(scope="module")
def admin_token():
    r = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text[:200]}"
    body = r.json()
    tok = body.get("access_token") or body.get("token")
    assert tok, f"no admin token: {body}"
    return tok


@pytest.fixture(scope="module")
def admin_id(admin_token):
    r = requests.get(
        f"{API}/auth/me",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200, r.text[:200]
    return r.json().get("id")


def _register_new_user(referral_code=None, prefix="TEST_ref"):
    """Register a fresh email user via SMTP-off path. Returns (user_dict_from_admin, email, id_hint).
    Because register/initiate sets an auth cookie, we use a bare requests call (no session)."""
    email = f"{prefix}_{uuid.uuid4().hex[:10]}@example.com"
    username = f"tref_{uuid.uuid4().hex[:8]}"
    payload = {
        "email": email,
        "password": "Test1234!",
        "username": username,
        "visitor_id": f"vis_{uuid.uuid4().hex[:8]}",
    }
    if referral_code is not None:
        payload["referral_code"] = referral_code

    r = requests.post(f"{API}/auth/register/initiate", json=payload)
    assert r.status_code == 200, f"register/initiate failed: {r.status_code} {r.text[:400]}"
    body = r.json()
    assert body.get("status") == "registered", f"expected registered, got: {body}"
    return email, username, body


def _admin_get_player(admin_token, player_id_or_email):
    r = requests.get(
        f"{API}/admin/players/{player_id_or_email}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    return r


# ---------- Registration binding ----------

class TestReferralBinding:

    def test_admin_id_available(self, admin_id):
        assert admin_id and isinstance(admin_id, str)

    def test_register_with_valid_ref_binds_referrerId(self, admin_token, admin_id):
        email, username, body = _register_new_user(referral_code=admin_id)
        # Admin lookup
        r = _admin_get_player(admin_token, email)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        user = data["user"]
        assert user.get("referrerId") == admin_id, (
            f"expected referrerId={admin_id} got {user.get('referrerId')}"
        )
        assert user.get("totalEarnedFromReferrals", 0) == 0
        assert user.get("contributedToReferrer", 0) == 0

    def test_register_without_ref_has_null_referrerId(self, admin_token):
        email, _, _ = _register_new_user(referral_code=None, prefix="TEST_noref")
        r = _admin_get_player(admin_token, email)
        assert r.status_code == 200
        user = r.json()["user"]
        assert user.get("referrerId") in (None, ""), f"expected null referrerId, got {user.get('referrerId')}"

    def test_register_with_nonexistent_ref_has_null_referrerId(self, admin_token):
        bogus = f"nonexistent_{uuid.uuid4().hex}"
        email, _, _ = _register_new_user(referral_code=bogus, prefix="TEST_bogusref")
        r = _admin_get_player(admin_token, email)
        assert r.status_code == 200
        user = r.json()["user"]
        assert user.get("referrerId") in (None, ""), (
            f"invalid ref should yield null referrerId, got {user.get('referrerId')}"
        )


# ---------- Immutability ----------

class TestReferrerImmutability:

    def test_admin_update_cannot_change_referrerId(self, admin_token, admin_id):
        # Create a referred user
        email, _, _ = _register_new_user(referral_code=admin_id, prefix="TEST_immut")
        r = _admin_get_player(admin_token, email)
        assert r.status_code == 200
        uid = r.json()["user"]["id"]
        original_ref = r.json()["user"].get("referrerId")
        assert original_ref == admin_id

        # Try to change referrerId via admin update
        # admin_router.post /players/{player_id}/update whitelists specific fields;
        # referrerId is NOT in that whitelist -> silently ignored.
        rr = requests.post(
            f"{API}/admin/players/{uid}/update",
            json={"referrerId": "attacker_id_xxx"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        # 200 = ignored, 400/422 also acceptable (rejected). Anything but success-with-change.
        assert rr.status_code in (200, 400, 422), rr.text[:300]

        # Re-read and confirm unchanged
        r2 = _admin_get_player(admin_token, uid)
        assert r2.status_code == 200
        assert r2.json()["user"].get("referrerId") == original_ref, (
            "referrerId must be immutable after registration"
        )

    def test_second_registration_with_same_email_is_rejected(self, admin_token, admin_id):
        # Create user, then attempt registering the same email again with a different ref -> must fail
        email, _, _ = _register_new_user(referral_code=admin_id, prefix="TEST_dupe")
        payload = {
            "email": email,
            "password": "Test1234!",
            "username": f"dupe_{uuid.uuid4().hex[:8]}",
            "referral_code": "some_other_ref",
        }
        r = requests.post(f"{API}/auth/register/initiate", json=payload)
        assert r.status_code != 200 or r.json().get("status") != "registered", (
            f"duplicate email registration should NOT succeed as new: {r.status_code} {r.text[:200]}"
        )


# ---------- GET /api/referrals/me ----------

class TestReferralsMe:

    def test_referrals_me_shape(self):
        # Register a new user, then login and hit /api/referrals/me
        email, username, _ = _register_new_user(prefix="TEST_me")
        lr = _login(email, "Test1234!")
        assert lr.status_code == 200
        tok = lr.json().get("access_token") or lr.json().get("token")
        assert tok
        r = requests.get(
            f"{API}/referrals/me",
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert r.status_code == 200, r.text[:300]
        b = r.json()
        for k in ("referral_id", "referral_path", "count", "total_earned_ton",
                  "total_earned_city", "referrals"):
            assert k in b, f"missing key {k} in response: {b}"
        assert b["referral_path"] == f"/?ref={b['referral_id']}"
        assert isinstance(b["referrals"], list)

    def test_referrals_me_returns_own_id_not_another_users(self):
        """CRITICAL BUG DETECTION: `/api/referrals/me` must return the CURRENT user's id
        as referral_id, not some other user's id.

        Root cause: `get_my_referrals` looks up the user via
            {"$or": [{"id": current_user.id}, {"email": current_user.email},
                     {"wallet_address": current_user.wallet_address}]}
        For an email-only user, current_user.wallet_address is None, and
        MongoDB matches {"wallet_address": None} against ANY document where
        wallet_address is null or absent. `find_one` returns the first such
        doc (typically admin), so the endpoint leaks admin's referral_id and
        admin's referral list to every regular user.
        """
        # Get current user's id via /auth/me
        email, username, _ = _register_new_user(prefix="TEST_mine")
        lr = _login(email, "Test1234!")
        tok = lr.json().get("access_token") or lr.json().get("token")
        me = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {tok}"}).json()
        my_id = me.get("id")

        r = requests.get(f"{API}/referrals/me", headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 200
        b = r.json()
        assert b["referral_id"] == my_id, (
            f"SECURITY BUG: /api/referrals/me returned referral_id={b['referral_id']} "
            f"but current user's id is {my_id}. Endpoint is leaking another user's "
            f"referral tree (likely admin's due to wallet_address=None $or match)."
        )
        assert b["count"] == 0
        assert b["total_earned_ton"] == 0
        assert b["total_earned_city"] == 0


# ---------- GET /api/admin/players/{id}/referrals ----------

class TestAdminReferrals:

    def test_admin_referrals_lists_bound_user(self, admin_token, admin_id):
        # Register a user bound to admin
        email, username, _ = _register_new_user(referral_code=admin_id, prefix="TEST_adminref")

        # Fetch admin referrals
        r = requests.get(
            f"{API}/admin/players/{admin_id}/referrals",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r.status_code == 200, r.text[:300]
        b = r.json()
        for k in ("referral_id", "referral_path", "count", "total_earned_city", "referrals"):
            assert k in b, f"missing key {k} in admin referrals response: {b}"
        assert b["referral_id"] == admin_id
        assert b["referral_path"] == f"/?ref={admin_id}"
        assert b["count"] >= 1, f"expected >=1 referral, got {b['count']}"
        usernames = [row.get("username") for row in b["referrals"]]
        assert username in usernames, (
            f"expected {username} in admin referrals list, got {usernames[:20]}"
        )

    def test_admin_referrals_requires_admin(self):
        # Regular user token should NOT access admin endpoint
        email, _, _ = _register_new_user(prefix="TEST_notadmin")
        lr = _login(email, "Test1234!")
        tok = lr.json().get("access_token") or lr.json().get("token")
        r = requests.get(
            f"{API}/admin/players/{uuid.uuid4().hex}/referrals",
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert r.status_code in (401, 403), f"non-admin got {r.status_code}"
