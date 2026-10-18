"""Backend tests for Referral Rally Iteration 2 bug fixes.

Covers:
- BUG 1: telegram_bot supervisor process alive + /api/telegram/webhook GET diagnostics OK.
- BUG 2: create_campaign clears promo_last_seen_date_msk for ALL users, and
         subsequent GET /api/promo/active returns show_modal=True for a user who dismissed today.
- BUG 3: leaderboard/admin/referrals include ALL registered users (with total=0, active=0),
         my_stats.rank is a positive int (not null) for a user with no referrals.
"""
import os
import subprocess
from datetime import datetime, timedelta, timezone

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://countdown-11.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PASSWORD = "Test1234!"
MSK_TZ = timezone(timedelta(hours=3))


def _login(email, password):
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        headers={"Content-Type": "application/json"},
        timeout=15,
    )
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_token():
    return _login(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def user_token():
    return _login(USER_EMAIL, USER_PASSWORD)


@pytest.fixture(scope="module", autouse=True)
def cleanup_after(admin_token):
    yield
    try:
        requests.post(
            f"{BASE_URL}/api/admin/promo/referral-rally/stop",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=15,
        )
    except Exception:
        pass


# ================== BUG 1 — Telegram Bot Process ==================


class TestBotProcess:
    def test_supervisor_running(self):
        out = subprocess.run(
            ["supervisorctl", "status", "telegram_bot"],
            capture_output=True, text=True, timeout=15,
        )
        combined = (out.stdout or "") + (out.stderr or "")
        assert "RUNNING" in combined, f"telegram_bot not RUNNING: {combined!r}"

    def test_bot_health(self):
        r = requests.get("http://127.0.0.1:8002/internal/health", timeout=10)
        assert r.status_code == 200
        j = r.json()
        assert j.get("status") == "ok"
        assert j.get("service") == "bot_webhook_server"

    def test_webhook_diagnostics(self):
        r = requests.get(f"{BASE_URL}/api/telegram/webhook", timeout=15)
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
        j = r.json()
        assert j.get("endpoint_reachable") is True
        assert j.get("bot_token_loaded") is True
        assert j.get("bot_initialized") is True


# ================== BUG 2 — Modal Reset on Activation ==================


class TestModalResetOnActivation:
    def test_dismiss_then_activate_shows_modal_again(self, admin_token, user_token):
        u_hdr = {"Authorization": f"Bearer {user_token}"}
        a_hdr = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}

        # Precondition: no active campaign
        requests.post(
            f"{BASE_URL}/api/admin/promo/referral-rally/stop",
            headers={"Authorization": f"Bearer {admin_token}"}, timeout=15,
        )

        # 1) Start a fresh campaign — should reset cooldown for all users.
        ends_at = (datetime.now(MSK_TZ) + timedelta(days=3)).isoformat()
        r = requests.post(
            f"{BASE_URL}/api/admin/promo/referral-rally/start",
            json={"ends_at": ends_at, "prizes_ton": [100, 50, 20], "per_active_ton": 1.5},
            headers=a_hdr, timeout=15,
        )
        assert r.status_code == 200, r.text

        # 2) User dismisses.
        r = requests.post(f"{BASE_URL}/api/promo/dismiss", headers=u_hdr, timeout=15)
        assert r.status_code == 200

        # 3) After dismiss, show_modal must be False.
        r = requests.get(f"{BASE_URL}/api/promo/active", headers=u_hdr, timeout=15)
        assert r.status_code == 200
        assert r.json().get("show_modal") is False

        # 4) Stop and start a NEW campaign — this must clear promo_last_seen_date_msk.
        r = requests.post(
            f"{BASE_URL}/api/admin/promo/referral-rally/stop",
            headers={"Authorization": f"Bearer {admin_token}"}, timeout=15,
        )
        assert r.status_code == 200

        ends_at2 = (datetime.now(MSK_TZ) + timedelta(days=4)).isoformat()
        r = requests.post(
            f"{BASE_URL}/api/admin/promo/referral-rally/start",
            json={"ends_at": ends_at2, "prizes_ton": [100, 50, 20], "per_active_ton": 1.5},
            headers=a_hdr, timeout=15,
        )
        assert r.status_code == 200, r.text

        # 5) show_modal must now be True again — even though user dismissed earlier today.
        r = requests.get(f"{BASE_URL}/api/promo/active", headers=u_hdr, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("mode") == "active"
        assert data.get("show_modal") is True, (
            f"Expected show_modal=True after admin restart, got: {data}"
        )


# ================== BUG 3 — Leaderboard shows ALL users ==================


class TestLeaderboardAllUsers:
    """After BUG 2 test above, a campaign is active. Verify all-users semantic."""

    def test_leaderboard_includes_all_users(self, user_token):
        u_hdr = {"Authorization": f"Bearer {user_token}"}
        r = requests.get(
            f"{BASE_URL}/api/promo/referral-rally/leaderboard?offset=0&limit=100",
            headers=u_hdr, timeout=15,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        rows = data.get("rows", [])
        # Must include at least 2 users (admin + testuser at minimum).
        assert len(rows) >= 2, f"expected >=2 rows, got {len(rows)}: {rows}"
        # Every row has required fields.
        required = {"user_id", "username", "total", "active", "rank"}
        for row in rows:
            missing = required - set(row.keys())
            assert not missing, f"row missing fields {missing}: {row}"
            assert isinstance(row["total"], int)
            assert isinstance(row["active"], int)
            assert isinstance(row["rank"], int) and row["rank"] >= 1
        # total_count should be > 0 and at least the number of rows.
        assert data.get("total_count", 0) >= len(rows)
        # Sort: active DESC, then id ASC (rows are already ranked).
        actives = [r["active"] for r in rows]
        assert actives == sorted(actives, reverse=True), (
            f"rows not sorted by active DESC: {actives}"
        )

    def test_my_stats_rank_is_positive_int(self, user_token):
        u_hdr = {"Authorization": f"Bearer {user_token}"}
        r = requests.get(f"{BASE_URL}/api/promo/active", headers=u_hdr, timeout=15)
        assert r.status_code == 200
        ms = r.json().get("my_stats", {})
        assert ms.get("active") == 0
        assert ms.get("total") == 0
        rank = ms.get("rank")
        assert isinstance(rank, int) and rank >= 1, (
            f"expected positive-int rank even without referrals, got: {ms}"
        )

    def test_admin_referrals_shows_all_users(self, admin_token):
        a_hdr = {"Authorization": f"Bearer {admin_token}"}
        r = requests.get(
            f"{BASE_URL}/api/admin/referrals?offset=0&limit=100",
            headers=a_hdr, timeout=15,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        rows = data.get("rows", [])
        assert len(rows) >= 2, f"expected >=2 rows for admin referrals, got {len(rows)}"
        assert data.get("total_count", 0) >= len(rows)
        # Every row has the same structure
        for row in rows:
            assert "user_id" in row
            assert "username" in row
            assert "total" in row and isinstance(row["total"], int)
            assert "active" in row and isinstance(row["active"], int)
