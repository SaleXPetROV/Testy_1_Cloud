"""
Iteration 15 backend tests:
- GET /api/referrals/me aggregate for admin (fake invitee => 0.0175 TON = 17.5 CITY)
- Admin endpoint /api/admin/players/{admin_id}/referrals returns same aggregate
- Security: /api/referrals/me for regular user returns own referral_id
- Auto-seed users exist
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # Fallback: read frontend .env
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
                    break
    except Exception:
        pass

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASS = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PASS = "Test1234!"


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login failed {email}: {r.status_code} {r.text[:300]}"
    data = r.json()
    return data["token"], data["user"]


@pytest.fixture(scope="module")
def admin_ctx():
    token, user = _login(ADMIN_EMAIL, ADMIN_PASS)
    return {"token": token, "user": user}


@pytest.fixture(scope="module")
def user_ctx():
    token, user = _login(USER_EMAIL, USER_PASS)
    return {"token": token, "user": user}


# --- Seed users existence ---
def test_admin_seeded_and_login():
    token, user = _login(ADMIN_EMAIL, ADMIN_PASS)
    assert user["email"] == ADMIN_EMAIL


def test_user_seeded_and_login():
    token, user = _login(USER_EMAIL, USER_PASS)
    assert user["email"] == USER_EMAIL


# --- /api/referrals/me admin aggregate ---
def test_referrals_me_admin_aggregate(admin_ctx):
    headers = {"Authorization": f"Bearer {admin_ctx['token']}"}
    r = requests.get(f"{BASE_URL}/api/referrals/me", headers=headers, timeout=15)
    assert r.status_code == 200, r.text[:300]
    data = r.json()
    print("admin /referrals/me:", {k: data.get(k) for k in
          ["count", "total_earned_ton", "total_earned_city", "referral_id"]})
    assert data.get("referral_id"), "referral_id missing"
    # invitees should include fakeReferral
    referrals = data.get("referrals", [])
    assert isinstance(referrals, list) and len(referrals) >= 1, f"expected >=1 invitee, got {referrals}"
    total_ton = float(data.get("total_earned_ton", 0))
    total_city = float(data.get("total_earned_city", 0))
    assert abs(total_ton - 0.0175) < 1e-9, f"total_earned_ton={total_ton}, expected 0.0175"
    assert abs(total_city - 17.5) < 1e-6, f"total_earned_city={total_city}, expected 17.5"


# --- /api/admin/players/{id}/referrals ---
def test_admin_players_referrals_aggregate(admin_ctx):
    admin_id = admin_ctx["user"]["id"]
    headers = {"Authorization": f"Bearer {admin_ctx['token']}"}
    r = requests.get(f"{BASE_URL}/api/admin/players/{admin_id}/referrals",
                     headers=headers, timeout=15)
    assert r.status_code == 200, r.text[:300]
    data = r.json()
    print("admin players referrals:", {k: data.get(k) for k in
          ["count", "total_earned_ton", "total_earned_city"]})
    assert data.get("count", 0) >= 1
    total_ton = float(data.get("total_earned_ton", 0))
    total_city = float(data.get("total_earned_city", 0))
    assert abs(total_ton - 0.0175) < 1e-9
    assert abs(total_city - 17.5) < 1e-6
    assert len(data.get("referrals", [])) >= 1


# --- Security: regular user should get own referral_id ---
def test_referrals_me_regular_user_security(user_ctx):
    headers = {"Authorization": f"Bearer {user_ctx['token']}"}
    r = requests.get(f"{BASE_URL}/api/referrals/me", headers=headers, timeout=15)
    assert r.status_code == 200, r.text[:300]
    data = r.json()
    print("user /referrals/me:", {k: data.get(k) for k in
          ["count", "total_earned_ton", "referral_id"]})
    # Should NOT match admin id
    assert data.get("referral_id") != "382eff46-2bca-4af0-9bd0-989b1e544717"
    # Count should be 0 (no referrals)
    assert int(data.get("count", 0)) == 0
    assert float(data.get("total_earned_ton", 0)) == 0.0
