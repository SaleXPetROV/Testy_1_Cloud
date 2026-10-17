"""Backend tests for two new features:
1) Per-zone trading schedule (public GET, admin POST, buy lock)
2) Announcement scheduling (immediate/scheduled/cancel/auto-publish)
"""
import os
import time
from datetime import datetime, timedelta, timezone

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASS = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PASS = "Test1234!"

FAR_FUTURE = (datetime.now(timezone.utc) + timedelta(days=365 * 5)).isoformat()


# ───────── Fixtures ─────────
@pytest.fixture(scope="session")
def admin_token():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=30)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="session")
def user_token():
    r = requests.post(f"{API}/auth/login", json={"email": USER_EMAIL, "password": USER_PASS}, timeout=30)
    assert r.status_code == 200, f"user login failed: {r.status_code} {r.text}"
    return r.json()["token"]


def H(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ───────── Trading schedule endpoints ─────────
class TestTradingSchedule:
    def test_get_public_no_auth(self):
        r = requests.get(f"{API}/trading-schedule", timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert "zones" in body
        for z in ["core", "center", "middle", "outer"]:
            assert z in body["zones"]

    def test_admin_save_persists(self, admin_token):
        # Save a known config
        payload = {
            "zones": {
                "core": None,
                "center": None,
                "middle": FAR_FUTURE,
                "outer": None,
            }
        }
        r = requests.post(f"{API}/admin/trading-schedule", headers=H(admin_token), json=payload, timeout=15)
        assert r.status_code == 200, r.text
        zones = r.json()["zones"]
        assert zones["middle"] is not None
        # GET back
        r2 = requests.get(f"{API}/trading-schedule", timeout=15)
        assert r2.status_code == 200
        zones2 = r2.json()["zones"]
        assert zones2["middle"] is not None
        # ISO comparable date portion
        assert zones2["middle"].startswith(FAR_FUTURE[:10])

    def test_admin_invalid_datetime_400(self, admin_token):
        r = requests.post(
            f"{API}/admin/trading-schedule",
            headers=H(admin_token),
            json={"zones": {"core": "not-a-date"}},
            timeout=15,
        )
        assert r.status_code == 400

    def test_non_admin_cannot_save(self, user_token):
        r = requests.post(
            f"{API}/admin/trading-schedule",
            headers=H(user_token),
            json={"zones": {"core": None}},
            timeout=15,
        )
        assert r.status_code in (401, 403)


# ───────── Buy lock enforcement for middle zone ─────────
class TestBuyTradingLock:
    def _find_middle_available_plot(self, token):
        """Try a few likely endpoints; return (x,y) or None."""
        try:
            r = requests.get(f"{API}/island", headers=H(token), timeout=30)
            if r.status_code != 200:
                return None
            data = r.json()
            cells = data.get("cells") or []
            for c in cells:
                if c.get("zone") == "middle" and not c.get("owner"):
                    # exclude obstacles (water/mountain) – plots usually have type land/plot/empty
                    ct = (c.get("type") or "").lower()
                    if ct in ("water", "mountain", "obstacle", "rock", "river", "lake"):
                        continue
                    x = c.get("x")
                    y = c.get("y")
                    if x is not None and y is not None:
                        return int(x), int(y), "/island"
        except Exception as e:
            print(f"island fetch error: {e}")
        return None

    def test_user_blocked_with_trading_not_open(self, admin_token, user_token):
        # Ensure middle zone is locked far in future
        requests.post(
            f"{API}/admin/trading-schedule",
            headers=H(admin_token),
            json={"zones": {"middle": FAR_FUTURE}},
            timeout=15,
        )
        found = self._find_middle_available_plot(user_token)
        if not found:
            pytest.skip("No available middle-zone plot found via known endpoints")
        x, y, src = found
        print(f"Trying buy at middle plot x={x} y={y} (via {src})")
        r = requests.post(f"{API}/island/buy/{x}/{y}", headers=H(user_token), timeout=20)
        assert r.status_code == 403, f"expected 403 got {r.status_code} body={r.text}"
        try:
            detail = r.json().get("detail")
        except Exception:
            detail = r.text
        assert "trading_not_open" in str(detail), f"expected trading_not_open, got {detail}"


# ───────── Announcement scheduling ─────────
class TestAnnouncements:
    def test_publish_now(self, admin_token):
        r = requests.post(
            f"{API}/admin/announcement",
            headers=H(admin_token),
            json={"title": "TEST_NOW", "message": "TEST_now_msg", "lang": "all"},
            timeout=20,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "published"
        ann_id = body["id"]
        # cleanup
        requests.delete(f"{API}/admin/announcement/{ann_id}", headers=H(admin_token), timeout=15)

    def test_schedule_future(self, admin_token):
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        r = requests.post(
            f"{API}/admin/announcement",
            headers=H(admin_token),
            json={"title": "TEST_SCHED", "message": "TEST_sched_msg", "scheduled_at": future},
            timeout=20,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "scheduled", body
        assert body["scheduled_at"] is not None
        # cancel
        d = requests.delete(f"{API}/admin/announcement/{body['id']}", headers=H(admin_token), timeout=15)
        assert d.status_code == 200

    def test_past_scheduled_treated_as_now(self, admin_token):
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        r = requests.post(
            f"{API}/admin/announcement",
            headers=H(admin_token),
            json={"title": "TEST_PAST", "message": "TEST_past_msg", "scheduled_at": past},
            timeout=20,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "published"
        requests.delete(f"{API}/admin/announcement/{body['id']}", headers=H(admin_token), timeout=15)

    def test_invalid_scheduled_at(self, admin_token):
        r = requests.post(
            f"{API}/admin/announcement",
            headers=H(admin_token),
            json={"title": "TEST_BAD", "message": "x", "scheduled_at": "not-a-date"},
            timeout=20,
        )
        assert r.status_code == 400

    def test_delete_unknown_404(self, admin_token):
        r = requests.delete(f"{API}/admin/announcement/no-such-id-zzz", headers=H(admin_token), timeout=15)
        assert r.status_code == 404

    def test_auto_publish_by_scheduler(self, admin_token):
        """Schedule ~5s in the future and wait up to ~90s for scheduler to flip status."""
        soon = (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat()
        r = requests.post(
            f"{API}/admin/announcement",
            headers=H(admin_token),
            json={"title": "TEST_AUTO", "message": "TEST_auto_msg", "scheduled_at": soon},
            timeout=20,
        )
        assert r.status_code == 200, r.text
        ann = r.json()
        assert ann["status"] == "scheduled"
        ann_id = ann["id"]

        # Poll the announcements list (admin) up to 90s
        status = None
        deadline = time.time() + 90
        while time.time() < deadline:
            lr = requests.get(f"{API}/admin/announcements", headers=H(admin_token), timeout=15)
            if lr.status_code == 200:
                body = lr.json()
                items = body.get("announcements") if isinstance(body, dict) else body
                items = items or []
                for it in items:
                    if it.get("id") == ann_id:
                        status = it.get("status")
                        break
                if status == "published":
                    break
            time.sleep(5)

        # cleanup regardless
        requests.delete(f"{API}/admin/announcement/{ann_id}", headers=H(admin_token), timeout=15)

        if status is None:
            pytest.skip("admin announcements list endpoint not found; cannot verify auto-publish via API")
        assert status == "published", f"status still {status} after 90s"


# ───────── Teardown: restore middle to a future date ─────────
def teardown_module(module):
    try:
        r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=15)
        if r.status_code == 200:
            tok = r.json()["token"]
            restore = "2030-01-01T12:00:00+00:00"
            requests.post(
                f"{API}/admin/trading-schedule",
                headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
                json={"zones": {"core": None, "center": None, "middle": restore, "outer": None}},
                timeout=15,
            )
    except Exception:
        pass
