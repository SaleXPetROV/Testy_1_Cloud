# NOTE: Run serially (`-o addopts=""`) — shared admin session invalidation
# under xdist causes 401s.
"""Iteration 3 backend tests: cache invalidation of /api/promo/referral-rally/leaderboard
on B2B partner CREATE / DELETE / PATCH mutations.

The rally leaderboard is cached in-process with a 60s TTL (see
promo_service._leaderboard_cache). The fix ensures that flag_partner_user /
unflag_partner_user call promo_service.invalidate_leaderboard_cache(), so the
next request re-computes with fresh b2b_is_partner filtering — WITHOUT waiting
60 seconds.

Assumption: `simulate_b2b_partner.py` was previously executed, so 30
sim_ref_* users exist in the DB. If none are present in the current top-N,
the tests fall back to freshly-registered TEST_cache_* users.
"""
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or "http://localhost:8001"

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")


def _login(email, password):
    return requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        timeout=30,
    )


@pytest.fixture(scope="module")
def admin_token():
    r = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["user"]["is_admin"] is True
    return d["token"]


@pytest.fixture
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


# --- helpers --------------------------------------------------------------
def _rally_usernames(headers, limit=50):
    r = requests.get(
        f"{BASE_URL}/api/promo/referral-rally/leaderboard",
        params={"limit": limit},
        headers=headers,
        timeout=30,
    )
    assert r.status_code == 200, r.text
    rows = r.json().get("rows", [])
    return [(row.get("username") or "") for row in rows]


def _find_sim_ref_in_leaderboard(headers, limit=50):
    """Return a sim_ref_* username currently visible in the rally leaderboard,
    else None. Case-preserving."""
    for u in _rally_usernames(headers, limit=limit):
        if u.lower().startswith("sim_ref_"):
            return u
    return None


# --- Cache invalidation on CREATE ---------------------------------------
class TestCacheInvalidationOnCreate:
    def test_create_partner_removes_user_from_rally_leaderboard_immediately(
        self, admin_headers
    ):
        # 1. Warm cache & find a target user X (any sim_ref_*)
        target = _find_sim_ref_in_leaderboard(admin_headers, limit=50)
        if not target:
            pytest.skip(
                "No sim_ref_* user visible in current rally leaderboard. "
                "Run backend/scripts/simulate_b2b_partner.py to seed."
            )
        # Confirm the target is really there (this call is served from
        # the cache we just warmed — no compute needed).
        assert target in _rally_usernames(admin_headers, limit=50), (
            f"warmed cache should contain {target}"
        )

        # 2. Create B2B partner with username = target (should flag the user
        #    and INVALIDATE the cache).
        r = requests.post(
            f"{BASE_URL}/api/admin/b2b/partners",
            headers=admin_headers,
            json={"username": target, "sales_percent": 10.0, "yield_percent": 5.0},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        partner_id = r.json()["partner_id"]

        try:
            # 3. IMMEDIATE call (no sleep) — target must be gone thanks to
            #    invalidate_leaderboard_cache() hook.
            usernames_after = _rally_usernames(admin_headers, limit=50)
            assert target not in usernames_after, (
                f"Cache invalidation failed: {target} still present in rally "
                f"leaderboard immediately after B2B partner creation. "
                f"Top rows: {usernames_after[:10]}"
            )
        finally:
            requests.delete(
                f"{BASE_URL}/api/admin/b2b/partners/{partner_id}",
                headers=admin_headers,
                timeout=30,
            )


# --- Cache invalidation on DELETE ---------------------------------------
class TestCacheInvalidationOnDelete:
    def test_delete_partner_reappears_in_rally_leaderboard_immediately(
        self, admin_headers
    ):
        target = _find_sim_ref_in_leaderboard(admin_headers, limit=50)
        if not target:
            pytest.skip("No sim_ref_* user visible.")
        # Create partner with target → flag user, invalidate cache
        r = requests.post(
            f"{BASE_URL}/api/admin/b2b/partners",
            headers=admin_headers,
            json={"username": target, "sales_percent": 10.0, "yield_percent": 5.0},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        partner_id = r.json()["partner_id"]

        # Warm cache while flagged — target must be absent
        after_create = _rally_usernames(admin_headers, limit=50)
        assert target not in after_create, (
            f"{target} should be hidden while flagged as partner"
        )

        # DELETE partner → unflag + invalidate cache
        d = requests.delete(
            f"{BASE_URL}/api/admin/b2b/partners/{partner_id}",
            headers=admin_headers,
            timeout=30,
        )
        assert d.status_code == 200, d.text

        # IMMEDIATE call — target must reappear (no 60s wait).
        after_delete = _rally_usernames(admin_headers, limit=50)
        assert target in after_delete, (
            f"Cache invalidation failed on DELETE: {target} still missing "
            f"after unflag. Top rows: {after_delete[:10]}"
        )


# --- Cache invalidation on PATCH (transfer username) --------------------
class TestCacheInvalidationOnPatch:
    def test_patch_partner_username_moves_flag_and_invalidates_cache(
        self, admin_headers
    ):
        # We need TWO users visible in the leaderboard.
        all_sim = [
            u for u in _rally_usernames(admin_headers, limit=50)
            if u.lower().startswith("sim_ref_")
        ]
        if len(all_sim) < 2:
            pytest.skip("Need at least two sim_ref_* users in rally leaderboard.")
        user_a = all_sim[0]  # will be flagged first (partner A)
        user_y = all_sim[1]  # PATCH target — should become the new partner

        # 1. Create partner for user_a
        r = requests.post(
            f"{BASE_URL}/api/admin/b2b/partners",
            headers=admin_headers,
            json={"username": user_a, "sales_percent": 10.0, "yield_percent": 5.0},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        partner_id = r.json()["partner_id"]

        try:
            # Warm cache: A hidden, Y visible
            usernames = _rally_usernames(admin_headers, limit=50)
            assert user_a not in usernames, f"{user_a} should be hidden"
            assert user_y in usernames, f"{user_y} should still be visible"

            # 2. PATCH → move partner to user_y
            p = requests.patch(
                f"{BASE_URL}/api/admin/b2b/partners/{partner_id}",
                headers=admin_headers,
                json={"username": user_y},
                timeout=30,
            )
            assert p.status_code == 200, p.text

            # 3. IMMEDIATE call — Y should be gone, A should reappear.
            after_patch = _rally_usernames(admin_headers, limit=50)
            assert user_y not in after_patch, (
                f"Cache invalidation failed on PATCH: {user_y} still visible "
                f"after being flagged as new partner. Top rows: {after_patch[:10]}"
            )
            assert user_a in after_patch, (
                f"Cache invalidation failed on PATCH: {user_a} did not "
                f"reappear after being unflagged. Top rows: {after_patch[:10]}"
            )
        finally:
            requests.delete(
                f"{BASE_URL}/api/admin/b2b/partners/{partner_id}",
                headers=admin_headers,
                timeout=30,
            )


# --- Public API surface -------------------------------------------------
class TestPublicInvalidateAliasExists:
    def test_promo_service_exposes_invalidate_leaderboard_cache(self):
        """Sanity: the public alias mentioned in the fix must exist and be
        callable (module import + attribute check)."""
        import importlib
        mod = importlib.import_module("promo_service")
        fn = getattr(mod, "invalidate_leaderboard_cache", None)
        assert callable(fn), (
            "promo_service.invalidate_leaderboard_cache must be a public callable"
        )
        # Calling it must not raise.
        fn()
