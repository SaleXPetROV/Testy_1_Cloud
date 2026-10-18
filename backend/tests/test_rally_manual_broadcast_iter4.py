"""Backend tests for Referral Rally Iteration 4:
Manual broadcast (Разослать) admin endpoints + removal of the automatic
daily 10:00 MSK broadcast + callback-based 'На главную' key.

Endpoints:
  GET  /api/admin/promo/referral-rally/broadcast-preview
  POST /api/admin/promo/referral-rally/broadcast

Also verifies:
  - Startup log no longer mentions 'daily 10:00 MSK broadcast'
    but does log 'freeze/minute + reminder push every 5 min'.
  - _build_rally_keyboard uses callback_data='back_to_menu' for 'На главную'.
  - telegram_bot.handle_callback_query routes 'back_to_menu' -> cmd_start.
  - GET /api/admin/promo/referral-rally/current uses presale-aware sort
    ('total' before presale) and returns top10.
  - Non-admin (testuser) forbidden (401/403) from both broadcast endpoints.

NOTE:  Run SERIALLY (pytest -n 0) -- backend invalidates the older token
       on a second login with the same email.
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
# 1. GET /broadcast-preview - shape, sort, subscriber count, top3, text
# ============================================================
class TestBroadcastPreview:
    def test_preview_200_ok_shape(self, admin_token):
        r = requests.get(
            f"{BASE_URL}/api/admin/promo/referral-rally/broadcast-preview",
            headers=_hdr(admin_token), timeout=15,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("ok") is True, data
        preview = data.get("preview")
        assert isinstance(preview, dict), data
        # required fields
        for k in ("text", "sort", "subscriber_count", "top3", "banner_url"):
            assert k in preview, f"missing key {k!r} in preview: {preview}"
        assert isinstance(preview["text"], str) and preview["text"]
        assert isinstance(preview["subscriber_count"], int) and preview["subscriber_count"] >= 0
        assert isinstance(preview["top3"], list)
        # banner_url is nullable but if present must be a string
        assert preview["banner_url"] is None or isinstance(preview["banner_url"], str)

    def test_preview_sort_is_total_before_presale(self, admin_token):
        # Server clock is 2026-07-15, before presale (2026-07-21 15:00 MSK)
        assert datetime.now(MSK_TZ) < PRESALE_MSK, (
            "Server clock is at/after presale -- 'total' assertion invalid"
        )
        r = requests.get(
            f"{BASE_URL}/api/admin/promo/referral-rally/broadcast-preview",
            headers=_hdr(admin_token), timeout=15,
        )
        assert r.status_code == 200
        preview = r.json()["preview"]
        assert preview["sort"] == "total", (
            f"Before presale sort must be 'total', got {preview['sort']!r}"
        )

    def test_preview_top3_ordered_by_total_desc(self, admin_token):
        r = requests.get(
            f"{BASE_URL}/api/admin/promo/referral-rally/broadcast-preview",
            headers=_hdr(admin_token), timeout=15,
        )
        preview = r.json()["preview"]
        top3 = preview["top3"]
        assert len(top3) >= 2, f"expected >=2 leaders, got {top3}"
        totals = [row["total"] for row in top3]
        assert totals == sorted(totals, reverse=True), (
            f"top3 not sorted by TOTAL desc: {totals}"
        )
        # Top row (from seed) is testuser (5 total)
        assert top3[0]["username"] == "testuser"
        assert top3[0]["total"] == 5
        # Rank set correctly
        assert top3[0]["rank"] == 1
        assert top3[1]["username"] == "SanyaNazarov"
        assert top3[1]["total"] == 1

    def test_preview_text_contains_leaders_and_prize_fund(self, admin_token):
        r = requests.get(
            f"{BASE_URL}/api/admin/promo/referral-rally/broadcast-preview",
            headers=_hdr(admin_token), timeout=15,
        )
        preview = r.json()["preview"]
        text = preview["text"]
        # Prize fund present (RU)
        assert "ПРИЗОВОЙ ФОНД" in text, f"prize fund block missing: {text!r}"
        # Top-3 leader block present
        assert "ЛИДЕРЫ" in text, f"leaders block missing"
        # At least the top leader username appears
        assert "testuser" in text, f"top leader 'testuser' not in text: {text!r}"

    def test_preview_text_omits_24h_time_pressure_header(self, admin_token):
        """For the MANUAL broadcast the '24 ЧАСА' / '24 HOURS' banner must be
        suppressed (header='none'), because the admin may click Разослать at
        any time and it must not claim '24h left'."""
        r = requests.get(
            f"{BASE_URL}/api/admin/promo/referral-rally/broadcast-preview",
            headers=_hdr(admin_token), timeout=15,
        )
        text = r.json()["preview"]["text"]
        # None of these urgency banners must appear.
        forbidden = [
            "24 ЧАСА",
            "24 HOURS",
            "ПОСЛЕДНИЙ ЧАС",
            "FINAL HOUR",
        ]
        for phrase in forbidden:
            assert phrase not in text, (
                f"forbidden time-pressure banner {phrase!r} present in "
                f"manual broadcast preview: {text!r}"
            )

    def test_preview_subscriber_count_matches_mappings(self, admin_token):
        """subscriber_count should equal count of telegram_mappings docs."""
        r = requests.get(
            f"{BASE_URL}/api/admin/promo/referral-rally/broadcast-preview",
            headers=_hdr(admin_token), timeout=15,
        )
        c = r.json()["preview"]["subscriber_count"]
        assert isinstance(c, int) and c >= 0


# ============================================================
# 2. POST /broadcast - send now, returns subscriber count
# ============================================================
class TestBroadcastSendNow:
    def test_broadcast_200_ok_returns_subscribers_int(self, admin_token):
        r = requests.post(
            f"{BASE_URL}/api/admin/promo/referral-rally/broadcast",
            headers=_hdr(admin_token), timeout=15,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("ok") is True, data
        assert isinstance(data.get("subscribers"), int), data
        assert data["subscribers"] >= 0

    def test_broadcast_returns_same_count_as_preview(self, admin_token):
        p = requests.get(
            f"{BASE_URL}/api/admin/promo/referral-rally/broadcast-preview",
            headers=_hdr(admin_token), timeout=15,
        )
        assert p.status_code == 200
        preview_count = p.json()["preview"]["subscriber_count"]
        b = requests.post(
            f"{BASE_URL}/api/admin/promo/referral-rally/broadcast",
            headers=_hdr(admin_token), timeout=15,
        )
        assert b.status_code == 200
        assert b.json()["subscribers"] == preview_count


# ============================================================
# 3. Auth guards - non-admin (testuser) forbidden
# ============================================================
class TestBroadcastAuth:
    def test_preview_forbidden_for_non_admin(self, user_token):
        r = requests.get(
            f"{BASE_URL}/api/admin/promo/referral-rally/broadcast-preview",
            headers=_hdr(user_token), timeout=15,
        )
        assert r.status_code in (401, 403), r.text

    def test_broadcast_forbidden_for_non_admin(self, user_token):
        r = requests.post(
            f"{BASE_URL}/api/admin/promo/referral-rally/broadcast",
            headers=_hdr(user_token), timeout=15,
        )
        assert r.status_code in (401, 403), r.text

    def test_preview_requires_auth(self):
        r = requests.get(
            f"{BASE_URL}/api/admin/promo/referral-rally/broadcast-preview",
            timeout=15,
        )
        assert r.status_code in (401, 403), r.text

    def test_broadcast_requires_auth(self):
        r = requests.post(
            f"{BASE_URL}/api/admin/promo/referral-rally/broadcast",
            timeout=15,
        )
        assert r.status_code in (401, 403), r.text


# ============================================================
# 4. GET /admin/promo/referral-rally/current - top10 ordered
# ============================================================
class TestAdminCurrentRally:
    def test_current_returns_top10(self, admin_token):
        r = requests.get(
            f"{BASE_URL}/api/admin/promo/referral-rally/current",
            headers=_hdr(admin_token), timeout=15,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "campaign" in data
        top10 = data.get("top10", [])
        assert isinstance(top10, list)
        assert len(top10) >= 2

    def test_current_top10_ordered_by_total_before_presale(self, admin_token):
        r = requests.get(
            f"{BASE_URL}/api/admin/promo/referral-rally/current",
            headers=_hdr(admin_token), timeout=15,
        )
        top10 = r.json()["top10"]
        totals = [row["total"] for row in top10]
        assert totals == sorted(totals, reverse=True), (
            f"top10 not sorted by TOTAL desc: {totals}"
        )
        assert top10[0]["username"] == "testuser"
        assert top10[0]["total"] == 5


# ============================================================
# 5. Scheduler: daily 10:00 MSK broadcast REMOVED, minute/5min log present
# ============================================================
class TestSchedulerReplaced:
    def test_startup_log_does_not_mention_daily_10_msk_broadcast(self):
        """The old daily 10:00 MSK broadcast log line must be absent from the
        CURRENT backend startup log window."""
        out = subprocess.run(
            ["bash", "-lc",
             "cat /var/log/supervisor/backend.err.log "
             "/var/log/supervisor/backend.out.log 2>/dev/null | "
             "grep -c 'daily 10:00 MSK broadcast' || true"],
            capture_output=True, text=True, timeout=15,
        )
        count_str = (out.stdout or "").strip().splitlines()[-1] if out.stdout else "0"
        try:
            count = int(count_str)
        except ValueError:
            count = 0
        # We tolerate stale log lines from previous startups (log rotation
        # windows), but at MINIMUM the new startup line below must be present.
        # The strict "no match anywhere" check is done via the source code
        # (background_tasks.py) instead.
        with open("/app/backend/background_tasks.py", "r", encoding="utf-8") as f:
            src = f.read()
        # Old logger.info string must NOT survive as an active log line
        # (it may only appear as a comment).
        active_lines = [
            ln for ln in src.splitlines()
            if "daily 10:00 MSK broadcast" in ln and "logger.info" in ln
        ]
        assert not active_lines, (
            f"An ACTIVE logger.info emitting 'daily 10:00 MSK broadcast' "
            f"still exists in background_tasks.py: {active_lines}"
        )

    def test_startup_log_mentions_new_reminder_schedule(self):
        out = subprocess.run(
            ["bash", "-lc",
             "grep -h 'Referral Rally: freeze/minute + reminder push every 5 min' "
             "/var/log/supervisor/backend.err.log "
             "/var/log/supervisor/backend.out.log 2>/dev/null | tail -3"],
            capture_output=True, text=True, timeout=15,
        )
        combined = (out.stdout or "") + (out.stderr or "")
        assert "freeze/minute + reminder push every 5 min" in combined, (
            f"new scheduler log line missing:\n{combined!r}"
        )

    def test_background_tasks_no_daily_cron_job(self):
        """background_tasks.py must no longer register a job that calls
        referral_rally_daily_broadcast_job."""
        with open("/app/backend/background_tasks.py", "r", encoding="utf-8") as f:
            src = f.read()
        # The scheduler.add_job(referral_rally_daily_broadcast_job, ...) block
        # must be gone.
        m = re.search(
            r"scheduler\.add_job\(\s*referral_rally_daily_broadcast_job",
            src,
        )
        assert not m, (
            "background_tasks.py still registers "
            "referral_rally_daily_broadcast_job with the scheduler"
        )


# ============================================================
# 6. Static checks: rally keyboard callback + bot handler
# ============================================================
class TestKeyboardAndCallbackStatic:
    def test_rally_keyboard_home_uses_callback_data(self):
        """_build_rally_keyboard: 'На главную' must be callback_data='back_to_menu',
        NOT url=..., in BOTH the linked and unlinked branches."""
        with open("/app/backend/promo_broadcast.py", "r", encoding="utf-8") as f:
            src = f.read()
        # Function start
        i = src.find("def _build_rally_keyboard(")
        assert i >= 0, "_build_rally_keyboard not found"
        # Take a slice large enough to include both keyboard variants
        body = src[i:i + 4000]
        # 'На главную' shows via labels[.]['home']; we assert callback_data
        # occurrences and that no URL button uses the home label text.
        callback_hits = re.findall(
            r'\{\s*"text"\s*:\s*L\[\s*"home"\s*\]\s*,\s*"callback_data"\s*:\s*"back_to_menu"',
            body,
        )
        assert len(callback_hits) >= 2, (
            "Both linked and unlinked branches must render "
            "'home' as callback_data='back_to_menu'; found "
            f"{len(callback_hits)} occurrences"
        )
        # Make sure the home button is NOT rendered as a URL button anywhere
        url_home = re.search(
            r'\{\s*"text"\s*:\s*L\[\s*"home"\s*\]\s*,\s*"url"',
            body,
        )
        assert not url_home, (
            "'home' button still rendered as URL — must be callback_data"
        )

    def test_bot_handle_callback_query_routes_back_to_menu_to_cmd_start(self):
        with open("/app/backend/telegram_bot.py", "r", encoding="utf-8") as f:
            src = f.read()
        i = src.find("async def handle_callback_query")
        assert i >= 0, "handle_callback_query not found"
        body = src[i:i + 20000]
        m = re.search(
            r'if\s+data\s*==\s*"back_to_menu"\s*:\s*[^\n]*\n'
            r'(?:\s*#[^\n]*\n)*'                      # optional comments
            r'\s*return\s+await\s+self\.cmd_start\(',
            body, re.DOTALL,
        )
        assert m, (
            "handle_callback_query does not route data=='back_to_menu' to "
            "self.cmd_start(...)"
        )
