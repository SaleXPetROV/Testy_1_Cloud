"""Iter15 backend regression for demo mode after hiding deposit/withdraw buttons.
Verifies: demo/enter=5000, my-businesses helios(prod 110, storage 360),
demo/trade/buy energy amount=10 -> cost 30, /api/economy/trade guard 403 with X-Game-Mode: demo."""
import os
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://sandbox-island.preview.emergentagent.com').rstrip('/')
EMAIL = "testuser@example.com"
PASSWORD = "Test1234!"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": EMAIL, "password": PASSWORD}, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json().get("token") or r.json().get("access_token")


@pytest.fixture(scope="module")
def headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module", autouse=True)
def enter_demo(headers):
    r = requests.post(f"{BASE_URL}/api/demo/enter", headers=headers, timeout=15)
    assert r.status_code == 200, r.text
    yield
    # cleanup: exit demo
    requests.post(f"{BASE_URL}/api/demo/exit", headers=headers, timeout=15)


def test_demo_enter_balance_5000(headers):
    r = requests.post(f"{BASE_URL}/api/demo/enter", headers=headers, timeout=15)
    assert r.status_code == 200
    d = r.json()
    bal = d.get("profile", {}).get("demo_balance_city") or d.get("demo_balance_city")
    # some responses put balance at top-level or inside profile
    assert bal == 5000 or bal == 5000.0, f"expected 5000, got {bal}: {d}"


def test_demo_my_businesses_helios(headers):
    r = requests.get(f"{BASE_URL}/api/demo/my-businesses", headers=headers, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    biz = d.get("businesses", [])
    assert len(biz) >= 1
    b0 = biz[0]
    assert b0["production"]["amount"] == 110
    assert b0["storage_info"]["capacity"] == 360


def test_demo_trade_buy_energy_10_cost_30(headers):
    r = requests.post(f"{BASE_URL}/api/demo/trade/buy", headers=headers,
                      json={"resource": "energy", "amount": 10}, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    cost = d.get("cost_city") or d.get("cost")
    assert cost == 30 or cost == 30.0, f"expected cost 30, got {cost}: {d}"


def test_economy_trade_blocked_with_demo_header(headers):
    h = dict(headers)
    h["X-Game-Mode"] = "demo"
    # Any POST body – guard should reject before validation
    r = requests.post(f"{BASE_URL}/api/economy/trade", headers=h,
                      json={"side": "buy", "resource": "energy", "amount": 1}, timeout=15)
    assert r.status_code == 403, f"expected 403, got {r.status_code} {r.text}"
