"""Regression tests for the Referral Rally leaderboard tie-break fix (iter 6).

Bug: promo_service.current_leaderboard_sort() returns 'active' after
PRESALE_MSK (2026-07-21 15:00 MSK). We are now past that time. Before the fix,
compute_referrals_leaderboard's $sort was {sort_field:-1, 'id':1} — meaning
referrers with active=0 (but many total invites) were buried behind arbitrary
0/0 users in the top10.

Fix (backend/promo_service.py:239): sort is now
    {sort_field: -1, "total": -1, "active": -1, "id": 1}
so referrers surface with their real counts even when active is 0.

The seed script (backend/seed_referral_rally_demo.py) creates:
    rally_topguy  total=25 active=3
    rally_second  total=21 active=0
    rally_third   total=4  active=4
    rally_fourth  total=3  active=1
    rally_fifth   total=1  active=0
"""
import os
import pytest
import requests

def _load_base_url():
    url = os.environ.get("REACT_APP_BACKEND_URL")
    if not url:
        # Fallback: parse frontend/.env
        env_path = "/app/frontend/.env"
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    if line.startswith("REACT_APP_BACKEND_URL="):
                        url = line.split("=", 1)[1].strip()
                        break
    if not url:
        raise RuntimeError("REACT_APP_BACKEND_URL not set and not found in frontend/.env")
    return url.rstrip("/")


BASE_URL = _load_base_url()

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PASSWORD = "Test1234!"

DEMO_USERNAMES = {"rally_topguy", "rally_second", "rally_third", "rally_fourth", "rally_fifth"}
EXPECTED_COUNTS = {
    "rally_topguy": {"total": 25, "active": 3},
    "rally_second": {"total": 21, "active": 0},
    "rally_third":  {"total": 4,  "active": 4},
    "rally_fourth": {"total": 3,  "active": 1},
    "rally_fifth":  {"total": 1,  "active": 0},
}
# Expected ordering by (active desc, total desc)
EXPECTED_ORDER_ACTIVE = ["rally_third", "rally_topguy", "rally_fourth", "rally_second", "rally_fifth"]
# Expected ordering by total desc
EXPECTED_ORDER_TOTAL = ["rally_topguy", "rally_second", "rally_third", "rally_fourth", "rally_fifth"]


# ==================== FIXTURES ====================

@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    data = r.json()
    assert "token" in data
    assert data["user"]["is_admin"] is True
    return data["token"]


@pytest.fixture(scope="module")
def user_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": USER_EMAIL, "password": USER_PASSWORD},
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 200, f"user login failed: {r.status_code} {r.text}"
    return r.json()["token"]


def _admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


def _user_headers(user_token):
    return {"Authorization": f"Bearer {user_token}"}


# ==================== TESTS ====================

class TestPresaleSortIsActive:
    """Sanity: confirm the current server clock puts us past PRESALE_MSK,
    which is the precondition of the bug being tested."""

    def test_current_sort_is_active(self, admin_token):
        # We can infer the current sort by calling the user leaderboard which
        # returns `sort` in its response.
        r = requests.get(
            f"{BASE_URL}/api/promo/referral-rally/leaderboard",
            headers=_admin_headers(admin_token),  # admin is also a user; endpoint requires only auth
        )
        assert r.status_code == 200, r.text
        assert r.json().get("sort") == "active", (
            f"Precondition failed: expected sort='active' (past PRESALE_MSK) but got "
            f"{r.json().get('sort')}"
        )


class TestAdminCurrentLeaderboardFix:
    """The main fix: /api/admin/promo/referral-rally/current top10 must surface
    the seeded referrers with their real counts, NOT 0/0."""

    def test_admin_current_returns_campaign_and_top10(self, admin_token):
        r = requests.get(
            f"{BASE_URL}/api/admin/promo/referral-rally/current",
            headers=_admin_headers(admin_token),
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "campaign" in data and data["campaign"] is not None, "No active campaign"
        assert "top10" in data and isinstance(data["top10"], list), "top10 missing"
        assert len(data["top10"]) > 0, "top10 is empty"

    def test_not_every_row_is_zero_zero(self, admin_token):
        """Regression: previously EVERY row in top10 showed 0/0."""
        r = requests.get(
            f"{BASE_URL}/api/admin/promo/referral-rally/current",
            headers=_admin_headers(admin_token),
        )
        assert r.status_code == 200
        rows = r.json()["top10"]
        non_zero = [row for row in rows if (row.get("active", 0) > 0 or row.get("total", 0) > 0)]
        assert len(non_zero) > 0, (
            f"BUG NOT FIXED: every row is 0/0. Rows: {rows}"
        )

    def test_all_five_seeded_referrers_in_top10(self, admin_token):
        """All five demo referrers must appear in top10 with correct counts."""
        r = requests.get(
            f"{BASE_URL}/api/admin/promo/referral-rally/current",
            headers=_admin_headers(admin_token),
        )
        assert r.status_code == 200
        rows = r.json()["top10"]
        by_username = {row.get("username"): row for row in rows}
        for uname, expected in EXPECTED_COUNTS.items():
            assert uname in by_username, (
                f"Referrer {uname} missing from top10. Present usernames: "
                f"{[r.get('username') for r in rows]}"
            )
            row = by_username[uname]
            assert row["active"] == expected["active"], (
                f"{uname} active mismatch: expected {expected['active']}, got {row['active']}"
            )
            assert row["total"] == expected["total"], (
                f"{uname} total mismatch: expected {expected['total']}, got {row['total']}"
            )

    def test_rally_second_is_present_even_with_active_zero(self, admin_token):
        """Regression: rally_second (active=0 but total=21) was buried by the
        old tie-break. It MUST appear in top10 now."""
        r = requests.get(
            f"{BASE_URL}/api/admin/promo/referral-rally/current",
            headers=_admin_headers(admin_token),
        )
        assert r.status_code == 200
        rows = r.json()["top10"]
        second = next((row for row in rows if row.get("username") == "rally_second"), None)
        assert second is not None, (
            f"BUG NOT FIXED: rally_second (0/21) is missing from top10 — "
            f"it was buried behind arbitrary 0/0 users. Rows: "
            f"{[(r.get('username'), r.get('active'), r.get('total')) for r in rows]}"
        )
        assert second["active"] == 0
        assert second["total"] == 21

    def test_expected_relative_ordering(self, admin_token):
        """Expected order among the five seeded referrers (past-presale, sort=active
        with tie-break by total desc):
            rally_third(4/4), rally_topguy(3/25), rally_fourth(1/3),
            rally_second(0/21), rally_fifth(0/1).
        We assert the relative order of these five (ignoring any other users
        that may appear between them; the fix is about tie-break, not exclusion)."""
        r = requests.get(
            f"{BASE_URL}/api/admin/promo/referral-rally/current",
            headers=_admin_headers(admin_token),
        )
        assert r.status_code == 200
        rows = r.json()["top10"]
        positions = {}
        for idx, row in enumerate(rows):
            uname = row.get("username")
            if uname in DEMO_USERNAMES:
                positions[uname] = idx
        # Ensure all five are present
        missing = DEMO_USERNAMES - positions.keys()
        assert not missing, f"Missing referrers from top10: {missing}"
        # Check relative ordering
        ordered = sorted(positions.items(), key=lambda kv: kv[1])
        ordered_names = [name for name, _ in ordered]
        assert ordered_names == EXPECTED_ORDER_ACTIVE, (
            f"Ordering wrong. Expected {EXPECTED_ORDER_ACTIVE}, got {ordered_names}"
        )


class TestSortByTotalOrdering:
    """Sort by total (used by referral list endpoint) should rank by total desc."""

    def test_referrals_list_sort_total(self, admin_token):
        r = requests.get(
            f"{BASE_URL}/api/admin/referrals?sort=total&offset=0&limit=100",
            headers=_admin_headers(admin_token),
        )
        assert r.status_code == 200, r.text
        rows = r.json().get("rows", [])
        positions = {}
        for idx, row in enumerate(rows):
            uname = row.get("username")
            if uname in DEMO_USERNAMES:
                positions[uname] = idx
        missing = DEMO_USERNAMES - positions.keys()
        assert not missing, (
            f"Referrers missing from sort=total list (limit=100). Missing: {missing}"
        )
        ordered = sorted(positions.items(), key=lambda kv: kv[1])
        ordered_names = [name for name, _ in ordered]
        assert ordered_names == EXPECTED_ORDER_TOTAL, (
            f"Total-sort ordering wrong. Expected {EXPECTED_ORDER_TOTAL}, got {ordered_names}"
        )

    def test_referrals_list_sort_active_matches_current(self, admin_token):
        """Verify sort=active on the referrals endpoint yields same ordering as
        the current endpoint (both should use the new tie-break)."""
        r = requests.get(
            f"{BASE_URL}/api/admin/referrals?sort=active&offset=0&limit=100",
            headers=_admin_headers(admin_token),
        )
        assert r.status_code == 200
        rows = r.json().get("rows", [])
        positions = {}
        for idx, row in enumerate(rows):
            uname = row.get("username")
            if uname in DEMO_USERNAMES:
                positions[uname] = idx
        missing = DEMO_USERNAMES - positions.keys()
        assert not missing, f"Missing from sort=active list: {missing}"
        ordered = sorted(positions.items(), key=lambda kv: kv[1])
        ordered_names = [name for name, _ in ordered]
        assert ordered_names == EXPECTED_ORDER_ACTIVE, (
            f"Active-sort ordering wrong. Expected {EXPECTED_ORDER_ACTIVE}, got {ordered_names}"
        )


class TestAdminAuthGuard:
    """Regression: non-admin must be blocked from the admin endpoint."""

    def test_non_admin_blocked_on_current(self, user_token):
        r = requests.get(
            f"{BASE_URL}/api/admin/promo/referral-rally/current",
            headers=_user_headers(user_token),
        )
        assert r.status_code in (401, 403), (
            f"Non-admin should get 401/403, got {r.status_code}: {r.text[:200]}"
        )

    def test_no_auth_blocked_on_current(self):
        r = requests.get(f"{BASE_URL}/api/admin/promo/referral-rally/current")
        assert r.status_code in (401, 403), (
            f"No-auth should get 401/403, got {r.status_code}"
        )


class TestReferralOverridePrecedence:
    """Regression: admin referral override should take precedence over the
    computed counts and be reflected in the leaderboard for that user."""

    OVERRIDE_ACTIVE = 99
    OVERRIDE_TOTAL = 500

    def _find_rally_topguy_id(self, admin_token):
        r = requests.get(
            f"{BASE_URL}/api/admin/referrals/search-users?q=rally_topguy&limit=5",
            headers=_admin_headers(admin_token),
        )
        assert r.status_code == 200, r.text
        results = r.json().get("results", [])
        row = next((x for x in results if x.get("username") == "rally_topguy"), None)
        assert row, f"rally_topguy not found via search: {results}"
        return row["user_id"]

    def test_override_reflected_in_current_leaderboard(self, admin_token):
        uid = self._find_rally_topguy_id(admin_token)

        # Apply override
        r = requests.post(
            f"{BASE_URL}/api/admin/referrals/override",
            json={"user_id": uid, "active": self.OVERRIDE_ACTIVE, "total": self.OVERRIDE_TOTAL},
            headers={**_admin_headers(admin_token), "Content-Type": "application/json"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True
        assert r.json()["active"] == self.OVERRIDE_ACTIVE
        assert r.json()["total"] == self.OVERRIDE_TOTAL

        try:
            # Re-fetch current leaderboard — the override must show
            r = requests.get(
                f"{BASE_URL}/api/admin/promo/referral-rally/current",
                headers=_admin_headers(admin_token),
            )
            assert r.status_code == 200
            rows = r.json()["top10"]
            top = next((row for row in rows if row.get("username") == "rally_topguy"), None)
            assert top is not None, "rally_topguy not in top10 after override"
            assert top["active"] == self.OVERRIDE_ACTIVE, (
                f"Override active not applied: got {top['active']}, expected {self.OVERRIDE_ACTIVE}"
            )
            assert top["total"] == self.OVERRIDE_TOTAL, (
                f"Override total not applied: got {top['total']}, expected {self.OVERRIDE_TOTAL}"
            )
            # With active=99 they should now be #1
            assert rows[0].get("username") == "rally_topguy", (
                f"After override active=99 rally_topguy should be #1, got rows[0]={rows[0]}"
            )
        finally:
            # Cleanup: clear the override
            requests.post(
                f"{BASE_URL}/api/admin/referrals/override/clear",
                json={"user_id": uid},
                headers={**_admin_headers(admin_token), "Content-Type": "application/json"},
            )
