"""
Backend tests for the Admin Buyout (Выкуп) — v2.3 BUG-FIX round (iteration 4).

Verifies 4 fixes + regression:

FIX 1 — Seller sees the buyout as "Продажа ресурсов" (tx_type resource_sale via
        market_purchase), NOT "admin_buyout", in transaction history.
FIX 2 — history 'amount' equals gross − tax (seller_net_after_credit), not the
        gross deal amount.
FIX 3 — Per-lot targeting: buying only ONE of a multi-lot seller's lots leaves
        the other lot untouched. Backend accepts items:[{listing_id,amount}].
FIX 4 — 50 masked buyer nicknames MUST NOT contain 'demo' / 'test' substrings.
        Also demo seller accounts are realistic usernames (pavel_ton, nastya_k,
        max_wolf, igor_v, crypto_guy, whale_99, ai_labs, sleeper_joe) — none
        of them start with 'demo_' or 'test'.

REGRESSION — Overview/execute/logs still function; non-admin blocked.

Re-seeds `python seed_buyout_demo.py` before each mutating test (idempotent).
"""

import os
import subprocess
import sys
import time
import pytest
import requests

def _load_base_url():
    u = os.environ.get("REACT_APP_BACKEND_URL")
    if not u:
        # Fallback: read /app/frontend/.env
        try:
            with open("/app/frontend/.env") as f:
                for line in f:
                    if line.startswith("REACT_APP_BACKEND_URL="):
                        u = line.split("=", 1)[1].strip()
                        break
        except FileNotFoundError:
            pass
    assert u, "REACT_APP_BACKEND_URL not set"
    return u.rstrip("/")


BASE_URL = _load_base_url()
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PASSWORD = "Test1234!"
DEMO_PASSWORD = "Demo1234!"

DEMO_USERNAMES = {
    "pavel_ton", "crypto_guy", "whale_99", "nastya_k",
    "igor_v", "max_wolf", "ai_labs", "sleeper_joe",
}


# -------------------- helpers --------------------

def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text[:200]}"
    return r.json()["token"]


def _reseed():
    subprocess.run(
        [sys.executable, "seed_buyout_demo.py"],
        cwd="/app/backend",
        check=True,
        capture_output=True,
        timeout=60,
    )
    time.sleep(0.4)


# -------------------- fixtures --------------------

@pytest.fixture(scope="module")
def admin_headers():
    tok = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def user_headers():
    tok = _login(USER_EMAIL, USER_PASSWORD)
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture()
def seeded():
    _reseed()
    yield


def _seller_headers(username):
    return {"Authorization": f"Bearer {_login(f'{username}@example.com', DEMO_PASSWORD)}",
            "Content-Type": "application/json"}


def _get_lots(admin_headers, username):
    r = requests.get(f"{API}/admin/buyout/overview?status=with_lots",
                     headers=admin_headers, timeout=30)
    assert r.status_code == 200, r.text
    row = next((row for row in r.json()["rows"] if row["username"] == username), None)
    assert row is not None, f"{username} not found in overview"
    return row["player_id"], row["lots"]


# ============================================================
# FIX 4 — buyer nicks pool must not contain demo/test
# ============================================================

class TestFix4BuyerNicks:
    def test_nicks_returns_50_and_no_demo_test(self, admin_headers):
        r = requests.get(f"{API}/admin/buyout/nicks", headers=admin_headers, timeout=15)
        assert r.status_code == 200, r.text
        nicks = r.json()["nicks"]
        assert len(nicks) == 50
        for n in nicks:
            assert "demo" not in n.lower(), f"'demo' substring found in nick: {n}"
            assert "test" not in n.lower(), f"'test' substring found in nick: {n}"

    def test_seller_usernames_not_demo_prefixed(self, admin_headers, seeded):
        r = requests.get(f"{API}/admin/buyout/overview", headers=admin_headers, timeout=30)
        assert r.status_code == 200
        rows = r.json()["rows"]
        usernames = {row["username"] for row in rows}
        # All 8 realistic usernames must be present
        for u in DEMO_USERNAMES:
            assert u in usernames, f"expected demo seller {u} missing in overview"
        # And none of the demo sellers start with demo_ or test_
        for u in DEMO_USERNAMES:
            assert not u.startswith("demo_"), f"seller {u} starts with demo_"
            assert not u.startswith("test_"), f"seller {u} starts with test_"


# ============================================================
# FIX 3 — per-lot selection: buy only one of two lots
# ============================================================

class TestFix3PerLotSelection:
    def test_nastya_k_has_two_lots(self, admin_headers, seeded):
        _, lots = _get_lots(admin_headers, "nastya_k")
        rts = {lot["resource_type"] for lot in lots}
        assert rts == {"biomass", "chips"}, f"expected biomass+chips, got {rts}"

    def test_buying_only_chips_leaves_biomass_untouched(self, admin_headers, seeded):
        pid, lots = _get_lots(admin_headers, "nastya_k")
        chips_lot = next(l for l in lots if l["resource_type"] == "chips")
        biomass_lot = next(l for l in lots if l["resource_type"] == "biomass")
        biomass_amount_before = biomass_lot["amount"]

        # Buy ONLY the chips lot (partial)
        r = requests.post(
            f"{API}/admin/buyout/execute",
            headers=admin_headers,
            json={"items": [{"listing_id": chips_lot["listing_id"], "amount": 5}],
                  "mask_mode": "auto"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        # only 1 lot bought
        assert data["purchased_count"] == 1
        assert data["details"][0]["resource_type"] == "chips"
        assert data["details"][0]["amount"] == 5

        # Re-read overview: biomass lot must be unchanged, chips lot decreased by 5
        r2 = requests.get(f"{API}/admin/buyout/overview?status=with_lots",
                          headers=admin_headers, timeout=30)
        nastya = next(row for row in r2.json()["rows"] if row["username"] == "nastya_k")
        by_rt = {l["resource_type"]: l for l in nastya["lots"]}
        assert by_rt["biomass"]["amount"] == biomass_amount_before, \
            f"biomass lot changed: was {biomass_amount_before}, now {by_rt['biomass']['amount']}"
        assert by_rt["chips"]["amount"] == chips_lot["amount"] - 5

    def test_multi_lot_owners_have_two_lots(self, admin_headers, seeded):
        for u in ("pavel_ton", "nastya_k", "max_wolf"):
            _, lots = _get_lots(admin_headers, u)
            assert len(lots) == 2, f"{u} expected 2 lots got {len(lots)}"


# ============================================================
# FIX 1 + FIX 2 — Seller history shows 'Продажа ресурсов' with NET amount
# ============================================================

class TestFix1And2HistoryTxTypeAndNetAmount:
    def test_seller_history_shows_resource_sale_with_net_amount(self, admin_headers, seeded):
        # Use nastya_k's chips lot (20 @ 0.090 TON per unit)
        pid, lots = _get_lots(admin_headers, "nastya_k")
        chips_lot = next(l for l in lots if l["resource_type"] == "chips")
        listing_id = chips_lot["listing_id"]
        price_ton = chips_lot["price_per_unit_ton"]

        # Execute buyout for a fixed amount
        buy_amount = 10
        r = requests.post(
            f"{API}/admin/buyout/execute",
            headers=admin_headers,
            json={"items": [{"listing_id": listing_id, "amount": buy_amount}],
                  "mask_mode": "auto"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        result = r.json()
        gross = round(buy_amount * price_ton, 6)
        tax = float(result["details"][0]["total_cost_ton"]) - float(result["details"][0]["seller_received_ton"])
        seller_net = float(result["details"][0]["seller_received_ton"])
        # sanity: gross close to buy_amount * price
        assert abs(result["details"][0]["total_cost_ton"] - gross) < 1e-4
        assert tax > 0, f"expected positive tax, got {tax}"

        # Login as seller and hit /api/history/transactions
        s_headers = _seller_headers("nastya_k")
        rh = requests.get(f"{API}/history/transactions?limit=10", headers=s_headers, timeout=30)
        assert rh.status_code == 200, rh.text
        txs = rh.json().get("transactions", [])
        assert txs, "seller has no transactions after buyout"

        # Find the newest sale entry (should be the buyout we just executed)
        newest = txs[0]

        # FIX 1: tx_type must be 'resource_sale' and type_name 'Продажа ресурсов'
        assert newest["tx_type"] == "resource_sale", \
            f"expected tx_type resource_sale, got {newest['tx_type']} (raw={newest})"
        assert newest["type_name"] == "Продажа ресурсов", \
            f"expected type_name 'Продажа ресурсов', got {newest['type_name']}"
        # Absolutely must NOT be admin_buyout
        assert newest["tx_type"] != "admin_buyout"

        # FIX 2: amount must equal seller_net_after_credit (~ gross - tax)
        assert abs(float(newest["amount"]) - seller_net) < 1e-4, \
            f"expected amount≈{seller_net}, got {newest['amount']} (gross={gross}, tax={tax})"
        assert float(newest["amount"]) < gross, \
            f"amount {newest['amount']} should be less than gross {gross} (post-tax)"

        # FIX 1b: detail endpoint must NOT report admin_buyout
        tx_id = newest["id"]
        rd = requests.get(f"{API}/history/transactions/{tx_id}", headers=s_headers, timeout=30)
        assert rd.status_code == 200, rd.text
        detail = rd.json()
        # get transaction object regardless of envelope
        detail_tx = detail.get("transaction") or detail
        assert detail_tx.get("tx_type") != "admin_buyout", \
            f"detail returned admin_buyout: {detail_tx}"

    def test_igor_50cu_at_0_0034_matches_curl_scenario(self, admin_headers, seeded):
        """Regression from PRD example: 50 cu @ 0.0034 = gross 0.17, net ≈ 0.1445 (15% tier tax)."""
        pid, lots = _get_lots(admin_headers, "igor_v")
        cu_lot = next(l for l in lots if l["resource_type"] == "cu")
        listing_id = cu_lot["listing_id"]

        r = requests.post(
            f"{API}/admin/buyout/execute",
            headers=admin_headers,
            json={"items": [{"listing_id": listing_id, "amount": 50}], "mask_mode": "auto"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        details = r.json()["details"][0]
        gross = float(details["total_cost_ton"])
        net = float(details["seller_received_ton"])
        # 50 * 0.0034 = 0.17
        assert abs(gross - 0.17) < 1e-4, f"gross expected 0.17, got {gross}"
        # net should be strictly less than gross
        assert net < gross
        # Seller-side history reflects net
        s_headers = _seller_headers("igor_v")
        rh = requests.get(f"{API}/history/transactions?limit=5", headers=s_headers, timeout=30)
        assert rh.status_code == 200
        newest = rh.json()["transactions"][0]
        assert newest["tx_type"] == "resource_sale"
        assert abs(float(newest["amount"]) - net) < 1e-4, \
            f"seller history amount {newest['amount']} != net {net}"


# ============================================================
# REGRESSION — core flow
# ============================================================

class TestRegressionCoreBuyout:
    def test_overview_stats_and_rows(self, admin_headers, seeded):
        r = requests.get(f"{API}/admin/buyout/overview", headers=admin_headers, timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert "stats" in data and "rows" in data
        assert data["stats"]["total_units_on_market"] > 0
        # Sellers with lots contain per-lot arrays
        for row in data["rows"]:
            for lot in row["lots"]:
                assert "listing_id" in lot and "resource_type" in lot and "amount" in lot

    def test_execute_empty_items_400(self, admin_headers, seeded):
        r = requests.post(f"{API}/admin/buyout/execute", headers=admin_headers,
                          json={"items": []}, timeout=15)
        assert r.status_code == 400

    def test_execute_specific_mask_invalid_400(self, admin_headers, seeded):
        _, lots = _get_lots(admin_headers, "igor_v")
        r = requests.post(
            f"{API}/admin/buyout/execute", headers=admin_headers,
            json={"items": [{"listing_id": lots[0]["listing_id"], "amount": 1}],
                  "mask_mode": "specific", "bot_username": "NotInPoolZZZ"},
            timeout=15,
        )
        assert r.status_code == 400

    def test_logs_endpoint_after_buyout(self, admin_headers, seeded):
        pid, lots = _get_lots(admin_headers, "ai_labs")
        lot = lots[0]
        r = requests.post(
            f"{API}/admin/buyout/execute", headers=admin_headers,
            json={"items": [{"listing_id": lot["listing_id"], "amount": 3}], "mask_mode": "auto"},
            timeout=30,
        )
        assert r.status_code == 200, r.text

        rl = requests.get(f"{API}/admin/buyout/logs/{pid}", headers=admin_headers, timeout=15)
        assert rl.status_code == 200
        data = rl.json()
        assert data["player_id"] == pid
        assert isinstance(data["logs"], list)
        # Logs contain the market_purchase (buyout) tx with a display_amount_ton
        candidates = [l for l in data["logs"] if l.get("is_admin_buyout") or l.get("tx_type") in ("market_purchase", "admin_buyout")]
        assert candidates, f"no buyout log entries: {data['logs']}"
        top = candidates[0]
        assert "display_amount_ton" in top
        # display_amount_ton must be positive (net credit to seller)
        assert float(top["display_amount_ton"]) > 0

    def test_non_admin_forbidden_all_endpoints(self, user_headers):
        # nicks
        r1 = requests.get(f"{API}/admin/buyout/nicks", headers=user_headers, timeout=15)
        assert r1.status_code in (401, 403)
        # overview
        r2 = requests.get(f"{API}/admin/buyout/overview", headers=user_headers, timeout=15)
        assert r2.status_code in (401, 403)
        # execute
        r3 = requests.post(f"{API}/admin/buyout/execute", headers=user_headers,
                           json={"items": [{"listing_id": "x", "amount": 1}]}, timeout=15)
        assert r3.status_code in (401, 403)
        # logs
        r4 = requests.get(f"{API}/admin/buyout/logs/x", headers=user_headers, timeout=15)
        assert r4.status_code in (401, 403)

    def test_specific_mask_uses_provided_nick(self, admin_headers, seeded):
        nicks = requests.get(f"{API}/admin/buyout/nicks", headers=admin_headers, timeout=15).json()["nicks"]
        chosen = nicks[0]
        _, lots = _get_lots(admin_headers, "crypto_guy")
        r = requests.post(
            f"{API}/admin/buyout/execute", headers=admin_headers,
            json={"items": [{"listing_id": lots[0]["listing_id"], "amount": 10}],
                  "mask_mode": "specific", "bot_username": chosen},
            timeout=30,
        )
        assert r.status_code == 200
        assert r.json()["details"][0]["buyer_nick"] == chosen
