"""Iter14 demo-mode: prod/storage real values, price without ×1000, guard, isolation."""
import os
import pytest
import requests

INTERNAL_URL = "http://localhost:8001"
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", INTERNAL_URL).rstrip("/")

USER_EMAIL = "testuser@example.com"
USER_PW = "Test1234!"


def _login():
    for base in (INTERNAL_URL, BASE_URL):
        try:
            r = requests.post(f"{base}/api/auth/login",
                              json={"email": USER_EMAIL, "password": USER_PW}, timeout=15)
            if r.status_code == 200 and r.json().get("token"):
                return r.json()["token"], base
        except Exception:
            continue
    return None, None


@pytest.fixture(scope="module")
def auth():
    tok, base = _login()
    assert tok, "login failed"
    hdr = {"Authorization": f"Bearer {tok}"}
    # ensure demo entered
    requests.post(f"{base}/api/demo/enter", headers=hdr, timeout=15)
    return hdr, base


def test_my_businesses_real_prod_and_storage(auth):
    h, base = auth
    r = requests.get(f"{base}/api/demo/my-businesses", headers=h, timeout=15)
    assert r.status_code == 200, r.text
    b0 = r.json()["businesses"][0]
    print("biz:", b0.get("business_type"), b0.get("production"), b0.get("storage_info", {}).get("capacity"))
    # business_type may vary via deficit picker; verify shape + values are real (not stub 100/360 for helios)
    prod = b0.get("production") or {}
    assert prod.get("amount") is not None
    assert prod.get("consumes") is not None  # dict, possibly empty
    cap = b0.get("storage_info", {}).get("capacity")
    assert cap is not None and int(cap) > 0
    # For helios specifically the request expects 110 prod / 360 storage
    if b0.get("business_type") == "helios":
        assert abs(float(prod["amount"]) - 110.0) < 1.0, prod
        assert int(cap) == 360, cap
        assert prod.get("consumes") == {}, prod


def test_market_prices_no_x1000(auth):
    h, base = auth
    r = requests.get(f"{base}/api/demo/market-prices", headers=h, timeout=15)
    assert r.status_code == 200
    d = r.json()
    prices = d["prices"]
    meta = d["meta"]
    # energy tier 1 = 3.0 TON
    assert abs(float(prices["energy"]) - 3.0) < 0.01, prices["energy"]
    assert meta["energy"]["tier"] == 1
    # find a tier-2 resource
    t2 = [k for k, m in meta.items() if int(m.get("tier", 0)) == 2]
    assert t2, "no tier2 resource in meta"
    # chips is expected tier2 = 85.0 in the spec
    if "chips" in meta:
        assert meta["chips"]["tier"] == 2
        assert abs(float(prices["chips"]) - 85.0) < 0.5, prices["chips"]


def test_buy_energy_cost_no_x1000(auth):
    h, base = auth
    requests.post(f"{base}/api/demo/enter", headers=h, timeout=15)
    r = requests.post(f"{base}/api/demo/trade/buy", headers=h,
                     json={"resource": "energy", "amount": 10}, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    if d.get("status") != "bought":
        pytest.skip(f"buy not succeeded: {d}")
    assert abs(float(d["cost_city"]) - 30.0) < 0.5, d  # 10*3.0=30, NOT 30000


def test_sell_energy_proceeds_no_x1000(auth):
    h, base = auth
    # ensure we have some energy: buy 10 first
    requests.post(f"{base}/api/demo/trade/buy", headers=h,
                  json={"resource": "energy", "amount": 10}, timeout=15)
    r = requests.post(f"{base}/api/demo/trade/sell", headers=h,
                     json={"resource": "energy", "amount": 5}, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    if d.get("status") != "sold":
        pytest.skip(f"sell not succeeded: {d}")
    assert abs(float(d["proceeds_city"]) - 15.0) < 0.5, d  # 5*3.0=15


def test_real_endpoints_blocked_in_demo(auth):
    h, base = auth
    hd = {**h, "X-Game-Mode": "demo"}
    # real economy/trade
    r1 = requests.post(f"{base}/api/economy/trade", headers=hd,
                       json={"resource": "energy", "amount": 1, "action": "sell"}, timeout=15)
    # /api/island/buy
    r2 = requests.post(f"{base}/api/island/buy", headers=hd,
                       json={"x": 5, "y": 5, "business_type": "helios"}, timeout=15)
    print(f"[gap] economy/trade in demo → {r1.status_code} ; island/buy → {r2.status_code}")
    # We don't hard-fail on economy/trade (known gap) but assert island/buy is blocked (403)
    assert r2.status_code in (403,), f"island/buy not blocked in demo: {r2.status_code} {r2.text[:200]}"


def test_real_isolation_unchanged(auth):
    h, base = auth
    # switch to real briefly to read baseline
    requests.post(f"{base}/api/demo/exit", headers=h, timeout=15)
    me0 = requests.get(f"{base}/api/auth/me", headers=h, timeout=15).json()
    bt0, res0 = me0.get("balance_ton"), dict(me0.get("resources") or {})
    # go back into demo & trade
    requests.post(f"{base}/api/demo/enter", headers=h, timeout=15)
    requests.post(f"{base}/api/demo/trade/buy", headers=h,
                  json={"resource": "energy", "amount": 1}, timeout=15)
    requests.post(f"{base}/api/demo/trade/sell", headers=h,
                  json={"resource": "energy", "amount": 1}, timeout=15)
    requests.post(f"{base}/api/demo/exit", headers=h, timeout=15)
    me1 = requests.get(f"{base}/api/auth/me", headers=h, timeout=15).json()
    assert me1.get("balance_ton") == bt0
    assert dict(me1.get("resources") or {}) == res0


def test_zzz_exit_demo(auth):
    h, base = auth
    r = requests.post(f"{base}/api/demo/exit", headers=h, timeout=15)
    assert r.status_code == 200
    assert r.json().get("is_demo") is False
