"""Tests for TON CITY v2.3 redesign: 8h shift, dev-notice, my/businesses shift fields."""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # Fallback to reading frontend/.env
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
                    break
    except Exception:
        pass

TESTUSER = {"email": "testuser@example.com", "password": "Test1234!"}
ADMIN = {"email": "sanyanazarov212@gmail.com", "password": os.environ.get("TEST_ADMIN_PASSWORD", "")}


def _login(payload):
    r = requests.post(f"{BASE_URL}/api/auth/login", json=payload, timeout=20)
    return r


@pytest.fixture(scope="module")
def user_token():
    r = _login(TESTUSER)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    tok = r.json().get("access_token") or r.json().get("token")
    assert tok, r.text
    return tok


@pytest.fixture(scope="module")
def admin_token():
    r = _login(ADMIN)
    assert r.status_code == 200, r.text
    tok = r.json().get("access_token") or r.json().get("token")
    assert tok, r.text
    return tok


# ---- Login ----
def test_login_regular():
    r = _login(TESTUSER)
    assert r.status_code == 200
    assert r.json().get("access_token") or r.json().get("token")


def test_login_admin():
    r = _login(ADMIN)
    assert r.status_code == 200


# ---- dev-notice ----
def test_dev_notice_ru():
    r = requests.get(f"{BASE_URL}/api/i18n/dev-notice", params={"lang": "ru"}, timeout=20)
    assert r.status_code == 200
    data = r.json()
    assert data.get("text") == "Функция в разработке"


def test_dev_notice_en():
    r = requests.get(f"{BASE_URL}/api/i18n/dev-notice", params={"lang": "en"}, timeout=30)
    assert r.status_code == 200
    data = r.json()
    text = data.get("text", "")
    # Should differ from Russian base and be non-empty
    assert text and text != "Функция в разработке", f"got: {text}"


# ---- my/businesses shift fields ----
def test_my_businesses_shift_fields(user_token):
    r = requests.get(f"{BASE_URL}/api/my/businesses",
                     headers={"Authorization": f"Bearer {user_token}"}, timeout=20)
    assert r.status_code == 200, r.text
    data = r.json()
    # Response may be a list or dict wrapper
    businesses = data if isinstance(data, list) else data.get("businesses") or data.get("items") or []
    assert businesses, f"No businesses returned: {data}"
    for b in businesses:
        assert "shift_active" in b, f"missing shift_active: {b.keys()}"
        assert "shift_ends_at" in b
        assert "shift_remaining_seconds" in b


def _get_business_ids(token):
    r = requests.get(f"{BASE_URL}/api/my/businesses",
                     headers={"Authorization": f"Bearer {token}"}, timeout=20)
    data = r.json()
    businesses = data if isinstance(data, list) else data.get("businesses") or data.get("items") or []
    return businesses


# ---- start-shift ----
def test_start_shift_success(user_token):
    businesses = _get_business_ids(user_token)
    assert businesses
    biz = businesses[0]
    bid = biz["id"]
    r = requests.post(f"{BASE_URL}/api/business/{bid}/start-shift",
                      headers={"Authorization": f"Bearer {user_token}"}, timeout=20)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d.get("shift_active") is True
    assert 28700 <= d.get("shift_remaining_seconds", 0) <= 28810
    assert d.get("shift_ends_at")

    # Subsequent GET reflects it
    time.sleep(1)
    businesses2 = _get_business_ids(user_token)
    match = next((b for b in businesses2 if b["id"] == bid), None)
    assert match
    assert match.get("shift_active") is True
    assert match.get("work_status") != "shift_ended"


def test_start_shift_404():
    # need auth token
    r = _login(TESTUSER)
    tok = r.json().get("access_token") or r.json().get("token")
    r = requests.post(f"{BASE_URL}/api/business/nonexistent_biz_xyz/start-shift",
                      headers={"Authorization": f"Bearer {tok}"}, timeout=20)
    assert r.status_code == 404, r.text


def test_start_shift_403_not_owner(admin_token, user_token):
    # Admin tries to start user's business shift → 403 (admin is not owner)
    user_bizs = _get_business_ids(user_token)
    assert user_bizs
    bid = user_bizs[0]["id"]
    r = requests.post(f"{BASE_URL}/api/business/{bid}/start-shift",
                      headers={"Authorization": f"Bearer {admin_token}"}, timeout=20)
    assert r.status_code == 403, r.text


# ---- Durability protection: businesses with no started shift should show idle/shift_ended ----
def test_idle_business_shift_ended(user_token):
    businesses = _get_business_ids(user_token)
    # Find one that has NEVER started a shift
    idle = [b for b in businesses if not b.get("shift_ends_at") and not b.get("shift_active")]
    if not idle:
        pytest.skip("All businesses have started shifts already")
    b = idle[0]
    # work_status should be idle with reason shift_ended (or similar)
    assert b.get("work_status") in ("idle", "shift_ended", None), b
