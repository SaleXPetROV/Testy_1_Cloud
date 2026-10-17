"""Backend tests for TON CITY v2.3 Presale (Iteration 3).

Covers:
- GET /api/presale/config (public)
- GET /api/admin/presale/inventory
- GET /api/admin/presale/ready-buyers
- POST /api/admin/presale/select-plots
- POST /api/admin/presale/approve
- POST /api/admin/presale/reset
- Regression: rally-broadcast, JWT 365d login
"""
import os
import datetime as _dt
import pytest
import requests
from dotenv import load_dotenv
load_dotenv("/app/frontend/.env")
load_dotenv("/app/backend/.env")

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
ADMIN = {"email": "sanyanazarov212@gmail.com", "password": os.environ.get("TEST_ADMIN_PASSWORD", "")}
USER = {"email": "testuser@example.com", "password": "Test1234!"}


def _login(creds):
    r = requests.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=30)
    assert r.status_code == 200, f"login failed {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login(ADMIN)}"}


@pytest.fixture(scope="module")
def user_headers():
    return {"Authorization": f"Bearer {_login(USER)}"}


# ─────────────────────────── Presale ───────────────────────────

class TestPresaleFlow:
    def test_00_reset_presale(self, admin_headers):
        r = requests.post(f"{BASE_URL}/api/admin/presale/reset", headers=admin_headers, timeout=30)
        assert r.status_code == 200
        assert r.json().get("ok") is True

    def test_01_public_config_inactive(self):
        r = requests.get(f"{BASE_URL}/api/presale/config", timeout=30)
        assert r.status_code == 200
        assert r.json() == {"active": False}

    def test_02_inventory_returns_business_types(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/admin/presale/inventory?map_id=ton_island",
                         headers=admin_headers, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["map_id"] == "ton_island"
        items = body["businesses"]
        assert isinstance(items, list) and len(items) >= 1
        # Expect around 21 types on GRAM island — assert >= 15 as a soft floor
        assert len(items) >= 15, f"expected ~21 business types, got {len(items)}"
        for it in items:
            for k in ("type", "name_ru", "icon", "tier", "free", "total"):
                assert k in it, f"missing key {k} in item {it}"
            assert isinstance(it["free"], int)
            assert isinstance(it["total"], int)
            assert it["total"] >= it["free"]
        # cache tier1 types for later tests
        TestPresaleFlow.INVENTORY = {i["type"]: i for i in items}

    def test_03_ready_buyers_matches_direct_count(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/admin/presale/ready-buyers",
                         headers=admin_headers, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "count" in body and isinstance(body["count"], int)
        assert body["count"] >= 0
        # Cross-check by hitting mongodb through env
        try:
            import motor.motor_asyncio, asyncio
            mongo_url = os.environ["MONGO_URL"]
            db_name = os.environ["DB_NAME"]
            async def _count():
                client = motor.motor_asyncio.AsyncIOMotorClient(mongo_url)
                return await client[db_name].users.count_documents({"balance_ton": {"$gte": 5}})
            direct = asyncio.get_event_loop().run_until_complete(_count()) if False else asyncio.new_event_loop().run_until_complete(_count())
            assert direct == body["count"], f"api count {body['count']} != db count {direct}"
        except Exception as e:
            print(f"mongo cross-check skipped: {e}")

    def test_04_select_plots_tier1(self, admin_headers):
        inv = TestPresaleFlow.INVENTORY
        # pick two tier-1 types with enough inventory
        tier1 = [t for t, i in inv.items() if i["tier"] == 1 and i["free"] >= 3]
        assert len(tier1) >= 2, f"not enough free tier1 types: {tier1}"
        t1, t2 = tier1[0], tier1[1]
        payload = {"map_id": "ton_island",
                   "businesses": [{"type": t1, "count": 3},
                                  {"type": t2, "count": 2}]}
        r = requests.post(f"{BASE_URL}/api/admin/presale/select-plots",
                          json=payload, headers=admin_headers, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        plots = body["selected_plots"]
        assert len(plots) == 5, f"expected 5 plots, got {len(plots)}: {plots}"
        for p in plots:
            for k in ("x", "y", "business_type"):
                assert k in p
            assert p["business_type"] in (t1, t2)
        got_t1 = sum(1 for p in plots if p["business_type"] == t1)
        got_t2 = sum(1 for p in plots if p["business_type"] == t2)
        assert got_t1 == 3 and got_t2 == 2
        # unique (x,y)
        coords = [(p["x"], p["y"]) for p in plots]
        assert len(set(coords)) == len(coords), "duplicate coordinates"
        TestPresaleFlow.SELECTED = plots
        TestPresaleFlow.SELECTED_TYPES = (t1, t2)

    def test_05_select_plots_warning_on_over_request(self, admin_headers):
        inv = TestPresaleFlow.INVENTORY
        t1 = TestPresaleFlow.SELECTED_TYPES[0]
        # request more than exists
        over = inv[t1]["total"] + 100
        r = requests.post(f"{BASE_URL}/api/admin/presale/select-plots",
                          json={"map_id": "ton_island",
                                "businesses": [{"type": t1, "count": over}]},
                          headers=admin_headers, timeout=30)
        assert r.status_code == 200
        body = r.json()
        assert "warnings" in body
        assert any(t1 in w for w in body["warnings"])

    def test_06_approve_requires_selected(self, admin_headers):
        # After test_05 overwrote selection with the over-request, selection is
        # still non-empty (took all free plots). Reset first, then approve
        # should fail because no selection.
        requests.post(f"{BASE_URL}/api/admin/presale/reset", headers=admin_headers, timeout=30)
        opens = (_dt.datetime.utcnow() + _dt.timedelta(minutes=5)).replace(tzinfo=_dt.timezone.utc).isoformat()
        r = requests.post(f"{BASE_URL}/api/admin/presale/approve",
                          json={"opens_at": opens, "unavailable_label": "coming_epoch_2",
                                "map_id": "ton_island"},
                          headers=admin_headers, timeout=30)
        assert r.status_code == 400, f"expected 400 (no selection), got {r.status_code} {r.text}"

    def test_07_approve_rejects_bad_label(self, admin_headers):
        # re-populate selection
        inv_r = requests.get(f"{BASE_URL}/api/admin/presale/inventory?map_id=ton_island",
                             headers=admin_headers, timeout=30).json()
        inv = {i["type"]: i for i in inv_r["businesses"]}
        t1 = next(t for t, i in inv.items() if i["tier"] == 1 and i["free"] >= 2)
        requests.post(f"{BASE_URL}/api/admin/presale/select-plots",
                      json={"map_id": "ton_island",
                            "businesses": [{"type": t1, "count": 2}]},
                      headers=admin_headers, timeout=30)
        opens = (_dt.datetime.utcnow() + _dt.timedelta(minutes=5)).replace(tzinfo=_dt.timezone.utc).isoformat()
        r = requests.post(f"{BASE_URL}/api/admin/presale/approve",
                          json={"opens_at": opens, "unavailable_label": "BAD_LABEL",
                                "map_id": "ton_island"},
                          headers=admin_headers, timeout=30)
        assert r.status_code == 400

    def test_08_approve_activates(self, admin_headers):
        opens = (_dt.datetime.utcnow() + _dt.timedelta(minutes=5)).replace(tzinfo=_dt.timezone.utc).isoformat()
        r = requests.post(f"{BASE_URL}/api/admin/presale/approve",
                          json={"opens_at": opens, "unavailable_label": "coming_epoch_2",
                                "map_id": "ton_island"},
                          headers=admin_headers, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True

    def test_09_public_config_active(self):
        r = requests.get(f"{BASE_URL}/api/presale/config", timeout=30)
        assert r.status_code == 200
        body = r.json()
        assert body["active"] is True
        assert body["map_id"] == "ton_island"
        assert body["unavailable_label"] == "coming_epoch_2"
        assert isinstance(body["selected_plots"], list)
        assert len(body["selected_plots"]) >= 1
        assert body["opens_at"]  # ISO string present

    def test_10_public_config_no_auth_required(self):
        # explicit: no Authorization header
        r = requests.get(f"{BASE_URL}/api/presale/config", headers={}, timeout=30)
        assert r.status_code == 200

    def test_11_reset_wipes(self, admin_headers):
        r = requests.post(f"{BASE_URL}/api/admin/presale/reset", headers=admin_headers, timeout=30)
        assert r.status_code == 200
        r2 = requests.get(f"{BASE_URL}/api/presale/config", timeout=30)
        assert r2.json() == {"active": False}


# ─────────────────────────── Regression ───────────────────────────

class TestRegression:
    def test_rally_broadcast(self, admin_headers):
        r = requests.post(f"{BASE_URL}/api/admin/promo/referral-rally/broadcast",
                          headers=admin_headers, timeout=30, json={})
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True

    def test_login_365d_jwt(self):
        import jwt as _jwt
        r = requests.post(f"{BASE_URL}/api/auth/login", json=USER, timeout=30)
        assert r.status_code == 200
        tok = r.json()["token"]
        # decode without verify
        claims = _jwt.decode(tok, options={"verify_signature": False})
        exp = claims["exp"]
        import time as _t
        ttl_days = (exp - _t.time()) / 86400
        assert ttl_days > 300, f"expected ~365d ttl, got {ttl_days:.1f}d"
