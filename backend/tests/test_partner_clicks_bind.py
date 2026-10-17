"""Iter 26: click counter, bind existing user, metrics (clicks/unique/new/completed)."""
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    try:
        with open("/app/frontend/.env") as _fh:
            for _ln in _fh:
                if _ln.startswith("REACT_APP_BACKEND_URL="):
                    BASE_URL = _ln.split("=", 1)[1].strip().rstrip("/")
                    break
    except Exception:
        pass
assert BASE_URL, "REACT_APP_BACKEND_URL not set"
ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")
REFERRER_ID = "6fe3ae7d-8dea-48c6-8d7c-85a743f59143"


# ── Fixtures ────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def anon_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def admin_client():
    boot = requests.Session()
    boot.headers.update({"Content-Type": "application/json"})
    r = boot.post(f"{BASE_URL}/api/auth/login",
                  json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text[:300]}"
    tok = r.json().get("access_token") or r.json().get("token")
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json",
                      "Authorization": f"Bearer {tok}"})
    return s


def _fetch_demo(admin_client):
    r = admin_client.get(f"{BASE_URL}/api/admin/partner-programs")
    assert r.status_code == 200, r.text[:200]
    progs = r.json().get("programs", [])
    demo = next((p for p in progs if p.get("name") == "Demo Partner"
                 and p.get("referrer_user_id") == REFERRER_ID), None)
    assert demo, f"Demo Partner not found among {[p.get('name') for p in progs]}"
    return demo


# ── 1) Click counter (public, no auth) ──────────────────────────────────────
class TestClickCounter:
    def test_click_increments_counter(self, anon_client, admin_client):
        before = _fetch_demo(admin_client)["clicks_count"]
        for _ in range(2):
            r = anon_client.post(f"{BASE_URL}/api/partner/click",
                                 json={"ref": REFERRER_ID})
            assert r.status_code == 200, r.text[:200]
            j = r.json()
            assert j.get("ok") is True
            assert j.get("counted") is True, j
        after = _fetch_demo(admin_client)["clicks_count"]
        assert after == before + 2, f"expected +2, got before={before} after={after}"

    def test_click_bad_ref(self, anon_client):
        r = anon_client.post(f"{BASE_URL}/api/partner/click",
                             json={"ref": "not-a-real-user"})
        assert r.status_code == 200
        j = r.json()
        assert j.get("counted") is False, j


# ── 2) Bind existing user via /api/partner/bind ─────────────────────────────
class TestPartnerBind:
    @pytest.fixture(scope="class")
    def new_user(self, anon_client):
        suffix = uuid.uuid4().hex[:10]
        email = f"TEST_bind_{suffix}@example.com"
        username = f"TESTbind{suffix[:8]}"
        password = "Str0ngPass!123"
        r = anon_client.post(f"{BASE_URL}/api/auth/register",
                             json={"email": email, "username": username,
                                   "password": password})
        assert r.status_code == 200, f"register failed: {r.status_code} {r.text[:300]}"
        tok = r.json().get("token") or r.json().get("access_token")
        uid = r.json().get("user", {}).get("id")
        assert tok and uid
        return {"token": tok, "id": uid, "email": email, "username": username}

    def _auth(self, user):
        s = requests.Session()
        s.headers.update({"Content-Type": "application/json",
                          "Authorization": f"Bearer {user['token']}"})
        return s

    def test_new_user_is_unbound(self, new_user, admin_client):
        # Confirm via referred-users that this user is NOT bound to Demo Partner
        demo = _fetch_demo(admin_client)
        r = admin_client.get(
            f"{BASE_URL}/api/admin/partner-programs/{demo['id']}/referred-users",
            params={"search": new_user["username"]})
        assert r.status_code == 200
        users = r.json()["users"]
        assert users == [], f"user should not yet be bound; got {users}"

    def test_bind_then_idempotent(self, new_user, admin_client):
        cli = self._auth(new_user)
        r = cli.post(f"{BASE_URL}/api/partner/bind",
                     json={"ref": REFERRER_ID})
        assert r.status_code == 200, r.text[:300]
        j = r.json()
        assert j.get("ok") is True and j.get("bound") is True, j

        # Second call: already bound → bound False
        r2 = cli.post(f"{BASE_URL}/api/partner/bind",
                      json={"ref": REFERRER_ID})
        assert r2.status_code == 200
        assert r2.json().get("bound") is False, r2.json()

    def test_bound_user_shows_as_existing(self, new_user, admin_client):
        demo = _fetch_demo(admin_client)
        r = admin_client.get(
            f"{BASE_URL}/api/admin/partner-programs/{demo['id']}/referred-users",
            params={"search": new_user["username"]})
        assert r.status_code == 200
        users = r.json()["users"]
        assert len(users) == 1, users
        u = users[0]
        assert u["is_new"] is False, u
        assert u["partner_task_completed"] is False


# ── 3) Metrics correctness on the Demo Partner ──────────────────────────────
class TestDemoMetrics:
    def test_list_endpoint_metrics(self, admin_client):
        d = _fetch_demo(admin_client)
        assert d["clicks_count"] >= 5, d
        assert d["unique_users_count"] >= 3, d
        assert d["new_users_count"] >= 2, d
        assert d["completed_count"] >= 1, d

    def test_referred_users_metrics_and_flags(self, admin_client):
        d = _fetch_demo(admin_client)
        r = admin_client.get(
            f"{BASE_URL}/api/admin/partner-programs/{d['id']}/referred-users")
        assert r.status_code == 200
        data = r.json()
        assert data["clicks_count"] == d["clicks_count"]
        assert data["unique_users_count"] == d["unique_users_count"]
        assert data["new_users_count"] == d["new_users_count"]
        assert data["completed_count"] == d["completed_count"]
        users = data["users"]
        required_keys = {"is_new", "land_count", "market_spent_city",
                         "partner_task_completed", "telegram_id"}
        for u in users:
            assert required_keys.issubset(u.keys()), u
        by_tg = {str(u["telegram_id"]): u for u in users if u.get("telegram_id")}
        assert "700111" in by_tg and "700222" in by_tg and "700333" in by_tg, by_tg.keys()
        alice = by_tg["700111"]; bob = by_tg["700222"]; carol = by_tg["700333"]
        assert alice["partner_task_completed"] is True and alice["is_new"] is True, alice
        assert bob["partner_task_completed"] is False and bob["is_new"] is True, bob
        assert carol["partner_task_completed"] is False and carol["is_new"] is False, carol

    def test_search_variants(self, admin_client):
        d = _fetch_demo(admin_client)
        pid = d["id"]
        r = admin_client.get(
            f"{BASE_URL}/api/admin/partner-programs/{pid}/referred-users",
            params={"search": "700222"})
        u = r.json()["users"]
        assert len(u) == 1 and str(u[0]["telegram_id"]) == "700222"

        r = admin_client.get(
            f"{BASE_URL}/api/admin/partner-programs/{pid}/referred-users",
            params={"search": "AliceRef"})
        u = r.json()["users"]
        assert len(u) == 1 and (u[0]["username"] or "").lower() == "aliceref"

        r = admin_client.get(
            f"{BASE_URL}/api/admin/partner-programs/{pid}/referred-users",
            params={"search": "zzz"})
        assert r.json()["users"] == []
