"""Iteration 3: verify skins alias fix + production numbers for /my/businesses."""
import os
import requests
import pytest

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") if False else "https://ton-metropolis-7.preview.emergentagent.com"


def _login(email, password):
    r = requests.post(f"{BASE}/api/auth/login", json={"email": email, "password": password}, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_token():
    return _login("sanyanazarov212@gmail.com", os.environ.get("TEST_ADMIN_PASSWORD", ""))


@pytest.fixture(scope="module")
def user_token():
    return _login("testuser@example.com", "Test1234!")


def test_skins_my_bio_farm(admin_token):
    r = requests.get(f"{BASE}/api/skins/my?business_type=bio_farm",
                     headers={"Authorization": f"Bearer {admin_token}"}, timeout=20)
    assert r.status_code == 200, r.text
    data = r.json()
    groups = [g.get("group_key") for g in data.get("skins", data if isinstance(data, list) else [])]
    print("bio_farm groups:", groups)
    assert "standard" in groups
    assert "crazy_bio_farm" in groups


def test_skins_my_signal_tower_alias(admin_token):
    """Alias fix: signal_tower should return skins stored under 'signal' alias."""
    r = requests.get(f"{BASE}/api/skins/my?business_type=signal_tower",
                     headers={"Authorization": f"Bearer {admin_token}"}, timeout=20)
    assert r.status_code == 200, r.text
    data = r.json()
    groups = [g.get("group_key") for g in data.get("skins", data if isinstance(data, list) else [])]
    print("signal_tower groups:", groups)
    assert "standard" in groups, f"missing standard, got {groups}"
    assert "neon_signal" in groups, f"missing neon_signal (alias fix broken), got {groups}"


def test_my_businesses_production(admin_token):
    r = requests.get(f"{BASE}/api/my/businesses",
                     headers={"Authorization": f"Bearer {admin_token}"}, timeout=20)
    assert r.status_code == 200, r.text
    items = r.json().get("businesses", [])
    print("business types:", [b.get("business_type") for b in items])
    bio = next((b for b in items if b.get("business_type") == "bio_farm"), None)
    assert bio is not None
    prod = bio.get("production") or {}
    print("bio_farm production:", prod)
    per_day = prod.get("production")
    cons_break = prod.get("consumption_breakdown") or prod.get("consumption") or {}
    assert per_day is not None, f"missing production.production: {prod}"
    # Expected ~182.52/day -> 7.61/h
    assert 170 <= float(per_day) <= 200, f"unexpected per_day={per_day}"
    assert cons_break.get("cooling") == 35, f"cooling should be 35, got {cons_break}"


def test_my_businesses_signal_tower_exists(admin_token):
    r = requests.get(f"{BASE}/api/my/businesses",
                     headers={"Authorization": f"Bearer {admin_token}"}, timeout=20)
    items = r.json().get("businesses", [])
    types = [b.get("business_type") for b in items]
    assert "signal_tower" in types, f"admin missing signal_tower, has {types}"
