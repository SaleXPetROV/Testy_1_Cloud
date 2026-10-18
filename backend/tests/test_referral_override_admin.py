"""
Tests for the new admin Referral Override feature (Акция «Рефералы» -> Изменить данные).

Covers endpoints introduced in /app/backend/routes/promo.py:
- GET  /api/admin/referrals/search-users
- POST /api/admin/referrals/override
- POST /api/admin/referrals/override/clear

Also verifies the override values are honored by:
- GET /api/admin/referrals?sort=total
- GET /api/promo/referral-rally/leaderboard (user-facing)

Cleanup: at the end of the suite we clear the override on testuser.
"""
from __future__ import annotations

import os
import pytest
import requests
from typing import Dict, Any

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # Fallback to reading frontend/.env (executed only if env var is missing)
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
                    break
    except Exception:
        pass

API = f"{BASE_URL}/api"

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PASSWORD = "Test1234!"

TIMEOUT = 30


# ---------- fixtures ----------


@pytest.fixture(scope="function")
def http() -> requests.Session:
    """New session per test to avoid cookie/session cross-contamination
    between admin and regular user across tests."""
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def admin_token() -> str:
    r = requests.post(
        f"{API}/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=TIMEOUT,
    )
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    data = r.json()
    assert data.get("user", {}).get("is_admin") is True, "admin flag not set on Sanya"
    assert isinstance(data.get("token"), str) and len(data["token"]) > 20
    return data["token"]


@pytest.fixture(scope="session")
def user_token_and_id() -> Dict[str, Any]:
    r = requests.post(
        f"{API}/auth/login",
        json={"email": USER_EMAIL, "password": USER_PASSWORD},
        timeout=TIMEOUT,
    )
    assert r.status_code == 200, f"user login failed: {r.status_code} {r.text}"
    d = r.json()
    assert d.get("user", {}).get("is_admin") is False, "regular user should not be admin"
    assert isinstance(d.get("token"), str)
    return {"token": d["token"], "id": d["user"]["id"], "username": d["user"]["username"]}


@pytest.fixture(scope="session")
def admin_headers(admin_token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="session")
def user_headers(user_token_and_id: Dict[str, Any]) -> Dict[str, str]:
    return {"Authorization": f"Bearer {user_token_and_id['token']}"}


# ---------- auth tests ----------


class TestAuthLogin:
    def test_admin_login(self, admin_token: str):
        assert isinstance(admin_token, str) and len(admin_token) > 20

    def test_regular_user_login(self, user_token_and_id: Dict[str, Any]):
        assert user_token_and_id["id"]


# ---------- search-users authorization ----------


class TestSearchUsersAuth:
    def test_search_requires_admin_regular_user_forbidden(self, http: requests.Session, user_headers):
        r = http.get(f"{API}/admin/referrals/search-users", params={"q": "test"},
                     headers=user_headers, timeout=TIMEOUT)
        assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}: {r.text[:200]}"

    def test_search_requires_admin_no_token(self, http: requests.Session):
        # Fresh session (no auth header)
        r = requests.get(f"{API}/admin/referrals/search-users", params={"q": "test"}, timeout=TIMEOUT)
        assert r.status_code in (401, 403), f"expected 401/403 without token, got {r.status_code}"


# ---------- search-users behavior ----------


class TestSearchUsers:
    def test_search_by_email(self, http: requests.Session, admin_headers, user_token_and_id):
        r = http.get(
            f"{API}/admin/referrals/search-users",
            params={"q": USER_EMAIL},
            headers=admin_headers,
            timeout=TIMEOUT,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "results" in data
        assert data.get("count", 0) >= 1
        # Find testuser in results
        match = next((u for u in data["results"] if u.get("email") == USER_EMAIL), None)
        assert match is not None, f"testuser not returned; got: {data}"
        for key in ("user_id", "username", "email", "active", "total",
                    "override_active", "override_total"):
            assert key in match, f"missing key {key} in search result: {match}"
        assert match["user_id"] == user_token_and_id["id"]
        assert match["username"] == user_token_and_id["username"]

    def test_search_by_username_partial(self, http: requests.Session, admin_headers):
        r = http.get(
            f"{API}/admin/referrals/search-users",
            params={"q": "testuser"},
            headers=admin_headers,
            timeout=TIMEOUT,
        )
        assert r.status_code == 200
        data = r.json()
        assert any(u.get("email") == USER_EMAIL for u in data.get("results", []))

    def test_search_by_id(self, http: requests.Session, admin_headers, user_token_and_id):
        r = http.get(
            f"{API}/admin/referrals/search-users",
            params={"q": user_token_and_id["id"]},
            headers=admin_headers,
            timeout=TIMEOUT,
        )
        assert r.status_code == 200
        data = r.json()
        assert data.get("count", 0) >= 1
        assert data["results"][0]["user_id"] == user_token_and_id["id"]


# ---------- override validation & 404 ----------


class TestOverrideValidation:
    def test_override_negative_active(self, http, admin_headers, user_token_and_id):
        r = http.post(f"{API}/admin/referrals/override",
                      json={"user_id": user_token_and_id["id"], "active": -1, "total": 5},
                      headers=admin_headers, timeout=TIMEOUT)
        assert r.status_code == 400, r.text

    def test_override_negative_total(self, http, admin_headers, user_token_and_id):
        r = http.post(f"{API}/admin/referrals/override",
                      json={"user_id": user_token_and_id["id"], "active": 0, "total": -3},
                      headers=admin_headers, timeout=TIMEOUT)
        assert r.status_code == 400, r.text

    def test_override_active_gt_total(self, http, admin_headers, user_token_and_id):
        r = http.post(f"{API}/admin/referrals/override",
                      json={"user_id": user_token_and_id["id"], "active": 10, "total": 5},
                      headers=admin_headers, timeout=TIMEOUT)
        assert r.status_code == 400, r.text

    def test_override_unknown_user_returns_404(self, http, admin_headers):
        r = http.post(f"{API}/admin/referrals/override",
                      json={"user_id": "does-not-exist-xxx", "active": 1, "total": 2},
                      headers=admin_headers, timeout=TIMEOUT)
        assert r.status_code == 404, r.text

    def test_override_requires_admin(self, http, user_headers, user_token_and_id):
        r = http.post(f"{API}/admin/referrals/override",
                      json={"user_id": user_token_and_id["id"], "active": 1, "total": 1},
                      headers=user_headers, timeout=TIMEOUT)
        assert r.status_code in (401, 403), r.text


# ---------- happy path: set override -> verify propagation -> clear ----------


class TestOverrideAppliesEverywhere:
    OVERRIDE_ACTIVE = 12
    OVERRIDE_TOTAL = 15

    def test_a_set_override(self, http, admin_headers, user_token_and_id):
        r = http.post(
            f"{API}/admin/referrals/override",
            json={
                "user_id": user_token_and_id["id"],
                "active": self.OVERRIDE_ACTIVE,
                "total": self.OVERRIDE_TOTAL,
            },
            headers=admin_headers,
            timeout=TIMEOUT,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data == {
            "ok": True,
            "user_id": user_token_and_id["id"],
            "username": user_token_and_id["username"],
            "active": self.OVERRIDE_ACTIVE,
            "total": self.OVERRIDE_TOTAL,
        }, data

    def test_b_search_reflects_override(self, http, admin_headers, user_token_and_id):
        r = http.get(f"{API}/admin/referrals/search-users",
                     params={"q": USER_EMAIL}, headers=admin_headers, timeout=TIMEOUT)
        assert r.status_code == 200
        match = next(u for u in r.json()["results"] if u["user_id"] == user_token_and_id["id"])
        # Override fields should reflect the just-set values
        assert match["override_active"] == self.OVERRIDE_ACTIVE
        assert match["override_total"] == self.OVERRIDE_TOTAL
        # The `active`/`total` fields (computed via compute_user_referral_stats)
        # should also reflect the override.
        assert match["active"] == self.OVERRIDE_ACTIVE
        assert match["total"] == self.OVERRIDE_TOTAL

    def test_c_admin_referrals_sort_total_shows_override(
        self, http, admin_headers, user_token_and_id
    ):
        r = http.get(f"{API}/admin/referrals",
                     params={"sort": "total", "limit": 500},
                     headers=admin_headers, timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        rows = r.json().get("rows", [])
        match = next((row for row in rows if row.get("user_id") == user_token_and_id["id"]), None)
        assert match is not None, "testuser not in leaderboard"
        assert match["total"] == self.OVERRIDE_TOTAL
        assert match["active"] == self.OVERRIDE_ACTIVE
        # With total=15 they should be at the top (rank == 1) since other users
        # typically have 0 real referrals.
        assert match["rank"] == 1, (
            f"expected rank 1 after override total=15, got rank={match['rank']}. "
            f"Top rows: {[(r.get('username'), r.get('total')) for r in rows[:5]]}"
        )

    def test_d_public_leaderboard_reflects_override(
        self, http, user_headers, user_token_and_id
    ):
        r = http.get(f"{API}/promo/referral-rally/leaderboard",
                     params={"limit": 500},
                     headers=user_headers, timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        data = r.json()
        # my_stats — the endpoint returns the caller's stats (testuser)
        my = data.get("my_stats") or {}
        assert my.get("active") == self.OVERRIDE_ACTIVE, f"my_stats.active mismatch: {my}"
        assert my.get("total") == self.OVERRIDE_TOTAL, f"my_stats.total mismatch: {my}"
        # rows include testuser with overridden values
        rows = data.get("rows", [])
        match = next((row for row in rows if row.get("user_id") == user_token_and_id["id"]), None)
        assert match is not None, "testuser not present in leaderboard rows"
        assert match["total"] == self.OVERRIDE_TOTAL
        assert match["active"] == self.OVERRIDE_ACTIVE

    def test_e_clear_override(self, http, admin_headers, user_token_and_id):
        r = http.post(
            f"{API}/admin/referrals/override/clear",
            json={"user_id": user_token_and_id["id"]},
            headers=admin_headers,
            timeout=TIMEOUT,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("ok") is True
        assert data.get("user_id") == user_token_and_id["id"]

    def test_f_clear_unknown_user_returns_404(self, http, admin_headers):
        r = http.post(
            f"{API}/admin/referrals/override/clear",
            json={"user_id": "does-not-exist-xxx"},
            headers=admin_headers,
            timeout=TIMEOUT,
        )
        assert r.status_code == 404, r.text

    def test_g_override_gone_after_clear(self, http, admin_headers, user_token_and_id):
        # After clear, search results should show override fields as None,
        # and computed active/total should revert to real counts (0 in the
        # seeded environment — testuser has no referrals).
        r = http.get(f"{API}/admin/referrals/search-users",
                     params={"q": USER_EMAIL}, headers=admin_headers, timeout=TIMEOUT)
        assert r.status_code == 200
        match = next(u for u in r.json()["results"] if u["user_id"] == user_token_and_id["id"])
        assert match["override_active"] in (None, 0), (
            f"override_active should be cleared (None), got {match['override_active']}"
        )
        assert match["override_total"] in (None, 0), (
            f"override_total should be cleared (None), got {match['override_total']}"
        )
        # If seed didn't invite anyone, real counts should be 0. But we're
        # lenient here in case other test data exists — we just check the
        # override was truly removed (value != previously-set OVERRIDE).
        assert match["active"] != TestOverrideAppliesEverywhere.OVERRIDE_ACTIVE or \
               match["total"] != TestOverrideAppliesEverywhere.OVERRIDE_TOTAL, \
               "Override values still present after clear"


# ---------- final cleanup (safety net) ----------


def test_zz_final_cleanup_clear_override_on_testuser(admin_headers, user_token_and_id):
    """Safety net at end of suite — ensure testuser has no override left."""
    r = requests.post(
        f"{API}/admin/referrals/override/clear",
        json={"user_id": user_token_and_id["id"]},
        headers={**admin_headers, "Content-Type": "application/json"},
        timeout=TIMEOUT,
    )
    # 200 if it was set, but if unknown user_id or already cleared -> also 200
    # (endpoint only 404s on unknown user_id, not on already-clear state).
    assert r.status_code == 200, r.text
