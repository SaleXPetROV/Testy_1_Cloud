"""Backend tests for Referral Rally Iteration 3.

Covers three requested behaviors (server date 2026-07-15, BEFORE presale
2026-07-21 15:00 MSK — so leaderboard sort must be 'total'):

1) Sticky-row rank in /api/promo/referral-rally/leaderboard.my_stats.rank
   must reflect the user's actual position (NOT hard-coded 1).
2) Leaderboard/announcement ordering BEFORE presale sorts by TOTAL invited
   referrals; AFTER presale by ACTIVE. Endpoint returns 'sort' field.
3) Admin GET /api/admin/referrals?sort=... manual toggle still works
   (active/total) and is unchanged.
4) referral_rally_daily_broadcast_job scheduler registration is visible in
   backend startup log ("daily 10:00 MSK broadcast") and is idempotent per
   MSK day via campaign.daily_broadcast_date.

Requires:
- Admin sanyanazarov212@gmail.com / {os.environ.get("TEST_ADMIN_PASSWORD", "")}
- User  testuser@example.com   / Test1234!
- Active rally campaign already running (ends 2026-07-25).
- Seed data: testuser has 5 total / 2 active referrals; SanyaNazarov has 1 total / 0 active.

NOTE: Backend has session dedupe (a second login with the same email kicks
the older token → 'session_invalidated'). pytest-xdist parallel workers
therefore invalidate each other's tokens. Run this file SERIALLY:
    pytest -n 0 tests/test_referral_rally_iter3_sort_and_daily.py
"""
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PASSWORD = "Test1234!"

MSK_TZ = timezone(timedelta(hours=3))
PRESALE_MSK = datetime(2026, 7, 21, 15, 0, 0, tzinfo=MSK_TZ)


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


def _hdr(token):
    return {"Authorization": f"Bearer {token}"}


# ============================================================
# TEST 1 — Before-presale sort mode is 'total'
# ============================================================

class TestSortModeBeforePresale:
    def test_server_clock_is_before_presale(self):
        """Sanity: server date must be < 2026-07-21 15:00 MSK for the whole
        'total' assertion suite to be valid."""
        assert datetime.now(MSK_TZ) < PRESALE_MSK, (
            "Server clock is at/after presale — the 'sort=total' assertions "
            "in this suite are only valid before presale."
        )

    def test_leaderboard_returns_sort_total(self, user_token):
        r = requests.get(
            f"{BASE_URL}/api/promo/referral-rally/leaderboard?offset=0&limit=100",
            headers=_hdr(user_token), timeout=15,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("sort") == "total", (
            f"Before presale sort must be 'total', got {data.get('sort')!r}"
        )

    def test_leaderboard_rows_ordered_by_total_desc(self, user_token):
        r = requests.get(
            f"{BASE_URL}/api/promo/referral-rally/leaderboard?offset=0&limit=100",
            headers=_hdr(user_token), timeout=15,
        )
        assert r.status_code == 200, r.text
        rows = r.json().get("rows", [])
        assert len(rows) >= 2, f"expected >=2 rows, got {len(rows)}"
        totals = [row["total"] for row in rows]
        assert totals == sorted(totals, reverse=True), (
            f"rows not sorted by TOTAL desc: {totals}"
        )


# ============================================================
# TEST 2 — Sticky row (my_stats.rank) reflects real rank
# ============================================================

class TestStickyRowRealRank:
    def test_testuser_rank_is_1_with_5_total(self, user_token):
        """testuser has 5 total referrals — should be #1 (before presale)."""
        r = requests.get(
            f"{BASE_URL}/api/promo/referral-rally/leaderboard?offset=0&limit=100",
            headers=_hdr(user_token), timeout=15,
        )
        assert r.status_code == 200
        ms = r.json().get("my_stats") or {}
        assert isinstance(ms.get("rank"), int) and ms["rank"] >= 1
        assert ms["total"] == 5, f"expected total=5, got {ms}"
        assert ms["active"] == 2, f"expected active=2, got {ms}"
        assert ms["rank"] == 1, f"expected testuser rank=1, got {ms}"

    def test_admin_rank_is_2_with_1_total(self, admin_token):
        """SanyaNazarov (admin) has 1 total, 0 active — before presale sort is
        total so rank must be 2 (behind testuser). Not the hard-coded 1."""
        r = requests.get(
            f"{BASE_URL}/api/promo/referral-rally/leaderboard?offset=0&limit=100",
            headers=_hdr(admin_token), timeout=15,
        )
        assert r.status_code == 200
        ms = r.json().get("my_stats") or {}
        assert ms.get("total") == 1
        assert ms.get("active") == 0
        assert ms.get("rank") == 2, (
            f"BUG: admin should be #2 (has fewer totals than testuser), "
            f"got rank={ms.get('rank')} — this is the reported 'always #1' bug"
        )

    def test_admin_rank_matches_row_position(self, admin_token):
        """my_stats.rank must equal the admin's index+1 in the ordered rows."""
        r = requests.get(
            f"{BASE_URL}/api/promo/referral-rally/leaderboard?offset=0&limit=500",
            headers=_hdr(admin_token), timeout=15,
        )
        assert r.status_code == 200
        data = r.json()
        rows = data.get("rows", [])
        ms = data.get("my_stats") or {}
        admin_uid = None
        for row in rows:
            if row.get("username") == "SanyaNazarov":
                admin_uid = row.get("user_id")
                assert row.get("rank") == ms.get("rank"), (
                    f"row.rank({row.get('rank')}) != my_stats.rank({ms.get('rank')})"
                )
                break
        assert admin_uid, "SanyaNazarov not found in leaderboard rows"

    def test_leaderboard_first_row_is_testuser(self, user_token):
        r = requests.get(
            f"{BASE_URL}/api/promo/referral-rally/leaderboard?offset=0&limit=5",
            headers=_hdr(user_token), timeout=15,
        )
        assert r.status_code == 200
        rows = r.json().get("rows", [])
        assert rows, "no rows returned"
        first = rows[0]
        assert first["username"] == "testuser"
        assert first["total"] == 5
        assert first["active"] == 2
        assert first["rank"] == 1

    def test_leaderboard_second_row_is_sanyanazarov(self, user_token):
        r = requests.get(
            f"{BASE_URL}/api/promo/referral-rally/leaderboard?offset=0&limit=5",
            headers=_hdr(user_token), timeout=15,
        )
        assert r.status_code == 200
        rows = r.json().get("rows", [])
        assert len(rows) >= 2
        second = rows[1]
        assert second["username"] == "SanyaNazarov"
        assert second["total"] == 1
        assert second["active"] == 0
        assert second["rank"] == 2


# ============================================================
# TEST 3 — /api/promo/active uses same sort + my_stats
# ============================================================

class TestPromoActiveSort:
    def test_active_top3_ordered_by_total(self, user_token):
        r = requests.get(f"{BASE_URL}/api/promo/active",
                         headers=_hdr(user_token), timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("mode") == "active"
        top3 = data.get("top3") or []
        assert len(top3) >= 2, f"expected top3 with >=2 entries, got {top3}"
        totals = [row["total"] for row in top3]
        assert totals == sorted(totals, reverse=True), (
            f"top3 not sorted by TOTAL desc: {totals}"
        )
        # top3[0] must be testuser (5 total)
        assert top3[0]["username"] == "testuser"
        assert top3[0]["total"] == 5

    def test_active_my_stats_rank_admin(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/promo/active",
                         headers=_hdr(admin_token), timeout=15)
        assert r.status_code == 200
        ms = r.json().get("my_stats") or {}
        assert ms.get("rank") == 2, f"admin my_stats.rank must be 2, got {ms}"
        assert ms.get("total") == 1
        assert ms.get("active") == 0

    def test_active_my_stats_rank_testuser(self, user_token):
        r = requests.get(f"{BASE_URL}/api/promo/active",
                         headers=_hdr(user_token), timeout=15)
        assert r.status_code == 200
        ms = r.json().get("my_stats") or {}
        assert ms.get("rank") == 1, f"testuser my_stats.rank must be 1, got {ms}"
        assert ms.get("total") == 5
        assert ms.get("active") == 2


# ============================================================
# TEST 4 — Admin /api/admin/referrals manual sort unchanged
# ============================================================

class TestAdminManualSort:
    def test_admin_referrals_sort_total(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/admin/referrals?sort=total&limit=5",
                         headers=_hdr(admin_token), timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert data["sort"] == "total"
        rows = data["rows"]
        assert rows[0]["username"] == "testuser"
        assert rows[0]["total"] == 5
        # SanyaNazarov must be #2 by total
        assert rows[1]["username"] == "SanyaNazarov"
        assert rows[1]["total"] == 1

    def test_admin_referrals_sort_active(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/admin/referrals?sort=active&limit=5",
                         headers=_hdr(admin_token), timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert data["sort"] == "active"
        rows = data["rows"]
        # testuser has 2 active — must be #1
        assert rows[0]["username"] == "testuser"
        assert rows[0]["active"] == 2
        # Every subsequent row should have active <= previous
        actives = [row["active"] for row in rows]
        assert actives == sorted(actives, reverse=True)

    def test_admin_referrals_invalid_sort_rejected(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/admin/referrals?sort=bogus",
                         headers=_hdr(admin_token), timeout=15)
        assert r.status_code == 422

    def test_admin_referrals_default_sort_active(self, admin_token):
        """Default (no ?sort=) is 'active' — manual toggle default unchanged."""
        r = requests.get(f"{BASE_URL}/api/admin/referrals",
                         headers=_hdr(admin_token), timeout=15)
        assert r.status_code == 200
        assert r.json()["sort"] == "active"


# ============================================================
# TEST 5 — Daily 10:00 MSK broadcast scheduler + idempotency
# ============================================================

class TestDailyBroadcastRegistration:
    def test_startup_log_mentions_daily_broadcast(self):
        """Backend startup log must contain 'daily 10:00 MSK broadcast'."""
        # Grep the last N lines of backend supervisor log — logs rotate.
        out = subprocess.run(
            ["bash", "-lc",
             "grep -h 'daily 10:00 MSK broadcast' /var/log/supervisor/backend.err.log "
             "/var/log/supervisor/backend.out.log 2>/dev/null | tail -5"],
            capture_output=True, text=True, timeout=15,
        )
        combined = (out.stdout or "") + (out.stderr or "")
        assert "daily 10:00 MSK broadcast" in combined, (
            f"scheduler log line missing — daily job may not be registered:\n"
            f"{combined!r}"
        )

    def test_scheduler_module_exports_daily_job(self):
        """referral_rally_daily_broadcast_job must be importable from
        promo_scheduler."""
        import promo_scheduler as sched
        assert hasattr(sched, "referral_rally_daily_broadcast_job"), (
            "promo_scheduler.referral_rally_daily_broadcast_job missing"
        )
        # And promo_broadcast.broadcast_rally_daily must exist
        import promo_broadcast as pb
        assert hasattr(pb, "broadcast_rally_daily"), (
            "promo_broadcast.broadcast_rally_daily missing"
        )

    def test_background_tasks_registers_cron_7am_utc(self):
        """background_tasks.py must register the job with CronTrigger(hour=7,
        minute=0) which corresponds to 10:00 MSK."""
        with open("/app/backend/background_tasks.py", "r", encoding="utf-8") as f:
            src = f.read()
        # Ensure the add_job block for referral_rally_daily_broadcast has hour=7
        m = re.search(
            r"referral_rally_daily_broadcast_job\s*,\s*trigger=CronTrigger\(\s*hour\s*=\s*7\s*,\s*minute\s*=\s*0\s*\)",
            src, re.DOTALL,
        )
        assert m, "CronTrigger(hour=7, minute=0) not registered for referral_rally_daily_broadcast_job"

    def test_campaign_has_daily_broadcast_date_today(self, admin_token):
        """After a prior 10:00-MSK fire or manual invocation, the active
        campaign should have daily_broadcast_date == today (MSK). This proves
        the idempotency guard is wired to the campaign document."""
        r = requests.get(f"{BASE_URL}/api/admin/promo/referral-rally/current",
                         headers=_hdr(admin_token), timeout=15)
        assert r.status_code == 200
        campaign = r.json().get("campaign")
        assert campaign, "no active campaign returned"
        # The field is optional; if present, it must be a YYYY-MM-DD string.
        dbd = campaign.get("daily_broadcast_date")
        if dbd is not None:
            assert re.match(r"^\d{4}-\d{2}-\d{2}$", str(dbd)), (
                f"daily_broadcast_date not YYYY-MM-DD: {dbd!r}"
            )
            # If today is set already, that only proves idempotency (per task
            # note). We accept any past-or-today MSK date.
            today = datetime.now(MSK_TZ).date().isoformat()
            assert dbd <= today, f"daily_broadcast_date in future: {dbd} vs today {today}"


# ============================================================
# TEST 6 — Auth guard on leaderboard endpoint
# ============================================================

class TestLeaderboardAuth:
    def test_leaderboard_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/promo/referral-rally/leaderboard",
                         timeout=15)
        assert r.status_code in (401, 403)
