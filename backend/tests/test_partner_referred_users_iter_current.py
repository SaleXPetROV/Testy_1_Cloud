"""Iter current: Partner referred-users endpoint + metrics."""
import os
import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].splitlines()[0]).rstrip("/")
ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")
REFERRER_ID = "6fe3ae7d-8dea-48c6-8d7c-85a743f59143"


@pytest.fixture(scope="module")
def admin_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text[:300]}"
    tok = r.json().get("access_token") or r.json().get("token")
    assert tok
    s.headers.update({"Authorization": f"Bearer {tok}"})
    return s


@pytest.fixture(scope="module")
def demo_program(admin_client):
    r = admin_client.get(f"{BASE_URL}/api/admin/partner-programs")
    assert r.status_code == 200, r.text[:300]
    progs = r.json().get("programs", [])
    demo = next((p for p in progs if p.get("name") == "Demo Partner" and p.get("referrer_user_id") == REFERRER_ID), None)
    assert demo, f"Demo Partner not found among {[p.get('name') for p in progs]}"
    return demo


def test_list_metrics(demo_program):
    assert demo_program["clicks_count"] == 3, demo_program
    assert demo_program["completed_count"] == 1, demo_program


def test_referred_users_all(admin_client, demo_program):
    pid = demo_program["id"]
    r = admin_client.get(f"{BASE_URL}/api/admin/partner-programs/{pid}/referred-users")
    assert r.status_code == 200, r.text[:300]
    data = r.json()
    assert data["clicks_count"] == 3
    assert data["completed_count"] == 1
    users = data["users"]
    assert len(users) == 3
    for u in users:
        for k in ("user_id","telegram_id","username","partner_joined_at","land_count","market_spent_city","partner_task_completed","land_ok","market_ok"):
            assert k in u, f"missing {k} in {u}"
    by_tg = {str(u["telegram_id"]): u for u in users}
    assert "700111" in by_tg and "700222" in by_tg and "700333" in by_tg, by_tg.keys()
    alice = by_tg["700111"]
    bob = by_tg["700222"]
    carol = by_tg["700333"]
    assert alice["partner_task_completed"] is True
    assert alice["land_count"] >= 1
    assert alice["market_spent_city"] >= 100
    assert bob["partner_task_completed"] is False
    assert bob["market_spent_city"] < 100
    assert carol["partner_task_completed"] is False
    assert carol["land_count"] == 0


def test_search_username(admin_client, demo_program):
    pid = demo_program["id"]
    r = admin_client.get(f"{BASE_URL}/api/admin/partner-programs/{pid}/referred-users", params={"search": "AliceRef"})
    assert r.status_code == 200
    users = r.json()["users"]
    assert len(users) == 1
    assert (users[0].get("username") or "").lower() == "aliceref"


def test_search_telegram(admin_client, demo_program):
    pid = demo_program["id"]
    r = admin_client.get(f"{BASE_URL}/api/admin/partner-programs/{pid}/referred-users", params={"search": "700222"})
    assert r.status_code == 200
    users = r.json()["users"]
    assert len(users) == 1
    assert str(users[0]["telegram_id"]) == "700222"


def test_search_no_match(admin_client, demo_program):
    pid = demo_program["id"]
    r = admin_client.get(f"{BASE_URL}/api/admin/partner-programs/{pid}/referred-users", params={"search": "zzzzz"})
    assert r.status_code == 200
    assert r.json()["users"] == []


def test_idempotent_completed_count(admin_client, demo_program):
    """Repeated GETs must not drift completed_count."""
    pid = demo_program["id"]
    for _ in range(3):
        r = admin_client.get(f"{BASE_URL}/api/admin/partner-programs")
        progs = r.json()["programs"]
        d = next(p for p in progs if p["id"] == pid)
        assert d["clicks_count"] == 3
        assert d["completed_count"] == 1
