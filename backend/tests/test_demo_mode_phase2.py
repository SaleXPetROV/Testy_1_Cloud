"""Demo (Sandbox) mode Phase 2 — backend economy regression tests.

Covers /api/demo/* economy endpoints:
- market-prices
- business/collect (idempotent 2nd call → nothing/near-zero)
- trade/sell (happy + insufficient)
- trade/buy (happy + insufficient_balance)
- business/repair (already_full path)
- isolation of real user's balance_ton/resources
- guard regression (X-Game-Mode: demo blocks real POSTs, does NOT block /api/demo/*)
- credit_demo_referral function
"""
import os
import asyncio
import pytest
import requests

INTERNAL_URL = "http://localhost:8001"
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", INTERNAL_URL).rstrip("/")

USER_EMAIL = "testuser@example.com"
USER_PW = "Test1234!"


def _login(email, pw):
    for base in (INTERNAL_URL, BASE_URL):
        try:
            r = requests.post(f"{base}/api/auth/login",
                              json={"email": email, "password": pw}, timeout=15)
            if r.status_code == 200 and r.json().get("token"):
                return r.json()["token"], base
        except Exception:
            continue
    return None, None


@pytest.fixture(scope="module")
def user_token():
    tok, base = _login(USER_EMAIL, USER_PW)
    assert tok, f"login failed for {USER_EMAIL}"
    return tok, base


@pytest.fixture(scope="module")
def auth_headers(user_token):
    tok, base = user_token
    return {"Authorization": f"Bearer {tok}"}, base


# ---------- Enter demo (setup) ----------
def test_enter_demo(auth_headers):
    h, base = auth_headers
    r = requests.post(f"{base}/api/demo/enter", headers=h, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("is_demo") is True
    prof = data.get("profile") or {}
    biz = prof.get("demo_business") or {}
    assert biz.get("x") == 13 and biz.get("y") == 12
    assert "demo_balance_city" in prof


# ---------- market-prices ----------
def test_market_prices(auth_headers):
    h, base = auth_headers
    r = requests.get(f"{base}/api/demo/market-prices", headers=h, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "prices" in data and isinstance(data["prices"], dict)
    assert "meta" in data and isinstance(data["meta"], dict)
    assert "energy" in data["prices"], f"missing energy price: {data['prices']}"
    assert data["prices"]["energy"] > 0
    em = data["meta"]["energy"]
    # meta is dict with localized name (ru/en) + icon
    assert ("name_ru" in em or "ru" in em) and ("name_en" in em or "en" in em) and "icon" in em


# ---------- collect ----------
def test_collect_first_and_idempotent(auth_headers):
    h, base = auth_headers
    r1 = requests.post(f"{base}/api/demo/business/collect", headers=h, timeout=15)
    assert r1.status_code == 200, r1.text
    d1 = r1.json()
    assert d1.get("status") in ("collected", "nothing", "halted"), d1
    assert "durability" in d1
    assert "resources" in d1
    # Second call immediately → nothing (or tiny collected because hours~0)
    r2 = requests.post(f"{base}/api/demo/business/collect", headers=h, timeout=15)
    assert r2.status_code == 200, r2.text
    d2 = r2.json()
    assert d2.get("status") in ("collected", "nothing", "halted")
    if d2.get("status") == "collected":
        assert float(d2.get("collected", 0)) < 1.0, f"unexpectedly large collected on idempotent call: {d2}"


# ---------- trade/sell ----------
def test_trade_sell_happy_and_insufficient(auth_headers):
    h, base = auth_headers
    # Get current state
    st = requests.get(f"{base}/api/demo/state", headers=h, timeout=15).json()
    prof = st.get("profile") or {}
    resources = prof.get("demo_resources") or {}
    balance_before = float(prof.get("demo_balance_city", 0))
    energy_have = float(resources.get("energy", 0))

    if energy_have <= 0:
        # Buy 1 energy first to seed the test
        rb = requests.post(f"{base}/api/demo/trade/buy", headers=h,
                           json={"resource": "energy", "amount": 1}, timeout=15)
        assert rb.status_code == 200
        assert rb.json().get("status") == "bought", rb.text
        energy_have = 1.0
        balance_before = float(rb.json().get("demo_balance_city", balance_before))

    sell_amt = min(energy_have, 0.5) if energy_have < 1 else 1.0
    # Insufficient case first
    r_ins = requests.post(f"{base}/api/demo/trade/sell", headers=h,
                          json={"resource": "energy", "amount": energy_have + 9999}, timeout=15)
    assert r_ins.status_code == 200, r_ins.text
    assert r_ins.json().get("status") == "insufficient", r_ins.text

    # Happy path
    r = requests.post(f"{base}/api/demo/trade/sell", headers=h,
                      json={"resource": "energy", "amount": sell_amt}, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d.get("status") == "sold", d
    assert d.get("resource") == "energy"
    expected = round(sell_amt * float(d["price_ton"]) * 1000.0, 2)
    assert abs(float(d["proceeds_city"]) - expected) < 0.05, d
    assert float(d["demo_balance_city"]) > balance_before - 0.01
    assert float(d["resources"].get("energy", 0)) == round(energy_have - sell_amt, 2)


# ---------- trade/buy ----------
def test_trade_buy_happy_and_insufficient_balance(auth_headers):
    h, base = auth_headers
    st = requests.get(f"{base}/api/demo/state", headers=h, timeout=15).json()
    prof = st.get("profile") or {}
    energy_before = float((prof.get("demo_resources") or {}).get("energy", 0))
    balance_before = float(prof.get("demo_balance_city", 0))

    r = requests.post(f"{base}/api/demo/trade/buy", headers=h,
                      json={"resource": "energy", "amount": 1}, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d.get("status") == "bought", d
    expected_cost = round(1.0 * float(d["price_ton"]) * 1000.0, 2)
    assert abs(float(d["cost_city"]) - expected_cost) < 0.05
    assert float(d["demo_balance_city"]) == round(balance_before - expected_cost, 2)
    assert float(d["resources"]["energy"]) == round(energy_before + 1, 2)

    # Insufficient balance — huge amount
    r2 = requests.post(f"{base}/api/demo/trade/buy", headers=h,
                       json={"resource": "energy", "amount": 100000000}, timeout=15)
    assert r2.status_code == 200, r2.text
    assert r2.json().get("status") == "insufficient_balance", r2.text


# ---------- repair ----------
def test_repair_already_full_or_repaired(auth_headers):
    h, base = auth_headers
    r = requests.post(f"{base}/api/demo/business/repair", headers=h, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d.get("status") in ("already_full", "repaired", "insufficient"), d
    if d.get("status") == "already_full":
        assert float(d.get("durability", 0)) > 99


# ---------- isolation ----------
def test_isolation_real_user_untouched(auth_headers):
    """Real user's balance_ton/resources must NOT change from demo ops."""
    h, base = auth_headers
    # /api/auth/me is the canonical current-user endpoint
    r_me = requests.get(f"{base}/api/auth/me", headers=h, timeout=15)
    assert r_me.status_code == 200, r_me.text
    me_before = r_me.json()
    bt_before = me_before.get("balance_ton")
    res_before = dict(me_before.get("resources") or {})

    # Do a demo buy+sell
    requests.post(f"{base}/api/demo/trade/buy", headers=h,
                  json={"resource": "energy", "amount": 1}, timeout=15)
    requests.post(f"{base}/api/demo/trade/sell", headers=h,
                  json={"resource": "energy", "amount": 1}, timeout=15)

    r_me2 = requests.get(f"{base}/api/auth/me", headers=h, timeout=15)
    me_after = r_me2.json()
    assert me_after.get("balance_ton") == bt_before, \
        f"real balance_ton changed! {bt_before} -> {me_after.get('balance_ton')}"
    assert dict(me_after.get("resources") or {}) == res_before, \
        f"real resources changed! {res_before} -> {me_after.get('resources')}"


# ---------- guard regression ----------
def test_guard_blocks_real_trade_but_not_demo(auth_headers):
    h, base = auth_headers
    hd = {**h, "X-Game-Mode": "demo"}
    # Real island buy should be blocked (in BLOCKED_DEMO_WRITE_PREFIXES)
    r_isl = requests.post(f"{base}/api/island/buy/5/5", headers=hd, timeout=15)
    assert r_isl.status_code == 403, r_isl.text[:200]
    assert r_isl.json().get("detail") == "demo_mode_blocked"

    # Real market buy should be blocked
    r_mkt = requests.post(f"{base}/api/market/buy", headers=hd,
                         json={"listing_id": "nope"}, timeout=15)
    assert r_mkt.status_code == 403, r_mkt.text[:200]
    assert r_mkt.json().get("detail") == "demo_mode_blocked"

    # NOTE: /api/economy/trade is NOT currently in BLOCKED_DEMO_WRITE_PREFIXES.
    # This is a gap per the review request (should be 403). Verify current state
    # so main agent can decide to add it.
    r_econ = requests.post(f"{base}/api/economy/trade", headers=hd,
                           json={"resource": "energy", "amount": 1, "action": "sell"}, timeout=15)
    # Not asserting 403 here — recorded as a gap in the report.

    # Demo endpoints must NOT be blocked
    r_demo = requests.get(f"{base}/api/demo/market-prices", headers=hd, timeout=15)
    assert r_demo.status_code == 200, r_demo.text

    r_demo2 = requests.post(f"{base}/api/demo/trade/sell", headers=hd,
                            json={"resource": "energy", "amount": 0.001}, timeout=15)
    assert r_demo2.status_code == 200, r_demo2.text


# ---------- credit_demo_referral function ----------
def test_credit_demo_referral_function(auth_headers):
    """Directly invoke demo_service.credit_demo_referral and verify +50000."""
    import sys, importlib
    sys.path.insert(0, "/app/backend")
    from motor.motor_asyncio import AsyncIOMotorClient

    async def _run():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        # Find testuser id
        u = await db.users.find_one({"email": USER_EMAIL}, {"_id": 0, "id": 1})
        assert u, "testuser not found"
        uid = u["id"]
        before = await db.demo_profiles.find_one({"user_id": uid}) or {}
        b0 = float(before.get("demo_balance_city", 0))

        demo_service = importlib.import_module("demo_service")
        res = await demo_service.credit_demo_referral(db, uid)
        assert res.get("status") == "credited", res
        assert float(res.get("bonus")) == 50000.0
        after = await db.demo_profiles.find_one({"user_id": uid})
        b1 = float(after.get("demo_balance_city", 0))
        assert round(b1 - b0, 2) == 50000.0, f"expected +50000, got {b1 - b0}"
        # Rollback to avoid inflating demo balance
        await db.demo_profiles.update_one({"user_id": uid},
                                          {"$set": {"demo_balance_city": b0}})
        client.close()

    asyncio.get_event_loop().run_until_complete(_run()) if False else asyncio.run(_run())


# ---------- cleanup ----------
def test_zzz_exit_demo(auth_headers):
    h, base = auth_headers
    r = requests.post(f"{base}/api/demo/exit", headers=h, timeout=15)
    assert r.status_code == 200
    assert r.json().get("is_demo") is False
