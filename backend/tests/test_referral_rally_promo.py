"""Backend tests for Referral Rally promo campaign (iteration 1)."""
import os
import pytest
import requests
from datetime import datetime, timedelta, timezone

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://countdown-11.preview.emergentagent.com").rstrip("/")

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PASSWORD = "Test1234!"

MSK_TZ = timezone(timedelta(hours=3))


# ==================== FIXTURES ====================

@pytest.fixture(scope="function")
def session():
    """Cookie-less session — critical because backend auth prefers cookie over
    Bearer, so sharing a session across admin+user logins would break auth."""
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    # Disable cookies entirely to keep Authorization Bearer as source of truth.
    s.cookies.clear()
    from requests.cookies import RequestsCookieJar
    class _NoCookies(RequestsCookieJar):
        def set_cookie(self, *a, **kw):  # noqa
            pass
        def extract_cookies(self, *a, **kw):  # noqa
            pass
    s.cookies = _NoCookies()
    return s


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                      headers={"Content-Type": "application/json"})
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    data = r.json()
    assert "token" in data, f"no token in response: {data}"
    assert data["user"]["is_admin"] is True
    return data["token"]


@pytest.fixture(scope="module")
def user_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": USER_EMAIL, "password": USER_PASSWORD},
                      headers={"Content-Type": "application/json"})
    assert r.status_code == 200, f"user login failed: {r.status_code} {r.text}"
    data = r.json()
    return data["token"]


def _admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


def _user_headers(user_token):
    return {"Authorization": f"Bearer {user_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module", autouse=True)
def clean_campaigns_at_end(admin_token):
    """Try to stop any active campaign at teardown to leave DB clean-ish."""
    yield
    try:
        requests.post(f"{BASE_URL}/api/admin/promo/referral-rally/stop",
                      headers={"Authorization": f"Bearer {admin_token}"})
    except Exception:
        pass


# ==================== TESTS ====================

class TestAuth:
    def test_admin_login(self, admin_token):
        assert isinstance(admin_token, str) and len(admin_token) > 20

    def test_user_login(self, user_token):
        assert isinstance(user_token, str) and len(user_token) > 20


class TestAdminGuard:
    def test_regular_user_cannot_access_admin_referrals(self, session, user_token):
        r = session.get(f"{BASE_URL}/api/admin/referrals",
                        headers=_user_headers(user_token))
        assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}: {r.text[:200]}"

    def test_unauth_cannot_access_admin_history(self, session):
        r = requests.get(f"{BASE_URL}/api/admin/promo/referral-rally/history")
        assert r.status_code in (401, 403)


class TestPreconditionCleanup:
    """Ensure no active campaign at start."""
    def test_stop_any_active(self, session, admin_token):
        r = session.post(f"{BASE_URL}/api/admin/promo/referral-rally/stop",
                         headers=_admin_headers(admin_token))
        # 200 if we stopped one, 404 if none active — either is fine
        assert r.status_code in (200, 404), f"unexpected: {r.status_code} {r.text}"


class TestCampaignLifecycle:
    """Full lifecycle: start → active endpoints → prevent duplicate → stop."""
    campaign_id = None

    def test_start_campaign(self, session, admin_token):
        ends_at = (datetime.now(MSK_TZ) + timedelta(days=7)).isoformat()
        r = session.post(
            f"{BASE_URL}/api/admin/promo/referral-rally/start",
            json={"ends_at": ends_at, "prizes_ton": [100, 50, 20], "per_active_ton": 1.5},
            headers=_admin_headers(admin_token),
        )
        assert r.status_code == 200, f"start failed: {r.status_code} {r.text}"
        data = r.json()
        assert data.get("ok") is True
        assert "campaign" in data
        c = data["campaign"]
        assert c.get("status") == "active"
        assert c.get("type") == "referral_rally"
        assert c["config"]["prizes_ton"] == [100.0, 50.0, 20.0]
        assert c["config"]["per_active_ton"] == 1.5
        assert "id" in c
        TestCampaignLifecycle.campaign_id = c["id"]

    def test_cannot_start_second(self, session, admin_token):
        ends_at = (datetime.now(MSK_TZ) + timedelta(days=5)).isoformat()
        r = session.post(
            f"{BASE_URL}/api/admin/promo/referral-rally/start",
            json={"ends_at": ends_at, "prizes_ton": [1, 2, 3]},
            headers=_admin_headers(admin_token),
        )
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"

    def test_promo_active_user_view(self, session, user_token):
        r = session.get(f"{BASE_URL}/api/promo/active",
                        headers=_user_headers(user_token))
        assert r.status_code == 200, f"active failed: {r.text}"
        data = r.json()
        assert data["mode"] == "active"
        assert data["campaign"] is not None
        assert data["campaign"]["status"] == "active"
        assert isinstance(data["top3"], list)
        assert "my_stats" in data
        ms = data["my_stats"]
        assert set(["rank", "active", "total"]).issubset(ms.keys())
        # testuser probably has no referrals
        assert ms["active"] == 0
        assert ms["total"] == 0

    def test_leaderboard_endpoint(self, session, user_token):
        r = session.get(f"{BASE_URL}/api/promo/referral-rally/leaderboard",
                        headers=_user_headers(user_token))
        assert r.status_code == 200, r.text
        data = r.json()
        assert "rows" in data and isinstance(data["rows"], list)
        assert "total_count" in data
        assert "my_stats" in data
        assert data.get("campaign_active") is True

    def test_admin_referrals_default_sort(self, session, admin_token):
        r = session.get(f"{BASE_URL}/api/admin/referrals",
                        headers=_admin_headers(admin_token))
        assert r.status_code == 200
        data = r.json()
        assert data["sort"] == "active"
        assert "rows" in data and "total_count" in data

    def test_admin_referrals_sort_total(self, session, admin_token):
        r = session.get(f"{BASE_URL}/api/admin/referrals?sort=total",
                        headers=_admin_headers(admin_token))
        assert r.status_code == 200
        assert r.json()["sort"] == "total"

    def test_admin_referrals_invalid_sort(self, session, admin_token):
        r = session.get(f"{BASE_URL}/api/admin/referrals?sort=bogus",
                        headers=_admin_headers(admin_token))
        assert r.status_code == 422  # pydantic pattern validation

    def test_promo_dismiss(self, session, user_token):
        r = session.post(f"{BASE_URL}/api/promo/dismiss",
                         headers=_user_headers(user_token))
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert "date" in data

    def test_after_dismiss_show_modal_false(self, session, user_token):
        r = session.get(f"{BASE_URL}/api/promo/active",
                        headers=_user_headers(user_token))
        assert r.status_code == 200
        data = r.json()
        assert data["show_modal"] is False, f"expected show_modal=False after dismiss, got {data}"
        assert data["mode"] == "active"

    def test_admin_current(self, session, admin_token):
        r = session.get(f"{BASE_URL}/api/admin/promo/referral-rally/current",
                        headers=_admin_headers(admin_token))
        assert r.status_code == 200
        data = r.json()
        assert data["campaign"] is not None
        assert data["campaign"]["status"] == "active"
        assert "top10" in data

    def test_csv_export(self, session, admin_token):
        r = session.get(f"{BASE_URL}/api/admin/referrals/export.csv",
                        headers=_admin_headers(admin_token))
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "").lower()
        assert "rank,user_id,username" in r.text

    def test_stop_campaign(self, session, admin_token):
        r = session.post(f"{BASE_URL}/api/admin/promo/referral-rally/stop",
                         headers=_admin_headers(admin_token))
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True

    def test_after_stop_no_active(self, session, user_token):
        r = session.get(f"{BASE_URL}/api/promo/active",
                        headers=_user_headers(user_token))
        assert r.status_code == 200
        data = r.json()
        # After cancel: mode should be None UNLESS there is a recent (<=7d)
        # finished campaign from a prior test run; both are acceptable per spec.
        assert data["mode"] in (None, "finished"), f"unexpected mode: {data['mode']}"
        if data["mode"] is None:
            assert data["campaign"] is None

    def test_history_has_campaign(self, session, admin_token):
        r = session.get(f"{BASE_URL}/api/admin/promo/referral-rally/history",
                        headers=_admin_headers(admin_token))
        assert r.status_code == 200
        data = r.json()
        assert "campaigns" in data
        assert isinstance(data["campaigns"], list)
        # Should have at least the one we just cancelled
        assert len(data["campaigns"]) >= 1
        # Most recent first
        first = data["campaigns"][0]
        assert first["type"] == "referral_rally"


class TestFinalizeFlow:
    """Start a new campaign and finalize it — verify winners[] is written."""
    def test_finalize(self, session, admin_token, user_token):
        ends_at = (datetime.now(MSK_TZ) + timedelta(days=2)).isoformat()
        r = session.post(
            f"{BASE_URL}/api/admin/promo/referral-rally/start",
            json={"ends_at": ends_at, "prizes_ton": [100, 50, 20]},
            headers=_admin_headers(admin_token),
        )
        assert r.status_code == 200, r.text
        cid = r.json()["campaign"]["id"]

        r = session.post(f"{BASE_URL}/api/admin/promo/referral-rally/finalize",
                         headers=_admin_headers(admin_token))
        assert r.status_code == 200, r.text
        c = r.json()["campaign"]
        assert c["status"] == "finished"
        assert isinstance(c["winners"], list)
        assert c["frozen_at"] is not None
        assert c["id"] == cid

        # After finalize: since frozen_at is fresh, mode should be 'finished'
        r = session.get(f"{BASE_URL}/api/promo/active",
                        headers=_user_headers(user_token))
        assert r.status_code == 200
        data = r.json()
        assert data["mode"] == "finished", f"expected mode=finished, got {data['mode']}"


class TestActivationBonusWired:
    """Verify maybe_pay_activation_bonus is imported at all 4 plot-buy sites."""
    def test_import_present_in_server(self):
        with open("/app/backend/server.py", "r") as f:
            content = f.read()
        occurrences = content.count("from promo_service import maybe_pay_activation_bonus")
        assert occurrences >= 4, f"expected 4 imports, found {occurrences}"

    def test_promo_service_import_ok(self):
        import promo_service as ps
        assert hasattr(ps, "maybe_pay_activation_bonus")
        assert hasattr(ps, "get_active_campaign")
        assert hasattr(ps, "msk_today_str")
        assert hasattr(ps, "freeze_campaign")
