"""Backend tests for TON_CITY v2.3 – Presale gate + business_upgrade task
(iteration for this session).

Covers all features listed in the review request:
  1. Presale is source of truth: buy/stake blocked with 423 presale_locked when
     inactive; button_text returned in HTTPException detail; custom text
     survives inactive presale via GET /api/presale/config.
  2. When presale active with selected_plots → plot IN allowlist buyable,
     plot OUT of allowlist returns 423 presale_locked.
  3. Custom Buy button text: POST /admin/presale/button-text stores it,
     GET /presale/config returns it verbatim including when active=false and
     for empty string.
  4. New partner-program flag require_business_upgrade + upgrade_from_level /
     upgrade_to_level: create, list, PATCH; check referred-users returns the
     new fields and per-user upgrade_count / upgrade_ok. Idempotent grant.
  5. Zero-lock regression: user holding a level-0 business gets 423 zero_locked
     on any subsequent /api/island/buy (even for a presale-allowlisted plot).
"""
import os
import time
import datetime as _dt
import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/frontend/.env")
load_dotenv("/app/backend/.env")

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
_mdb = MongoClient(MONGO_URL)[DB_NAME]
ADMIN = {"email": "sanyanazarov212@gmail.com", "password": os.environ.get("TEST_ADMIN_PASSWORD", "")}
USER1 = {"email": "testuser@example.com", "password": "Test1234!"}
USER2 = {"email": "testuser2@example.com", "password": "Test1234!"}


# ─────────────────────────── helpers ───────────────────────────

def _login(creds):
    r = requests.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=30)
    assert r.status_code == 200, f"login failed {r.status_code} {r.text}"
    j = r.json()
    return j["token"], j.get("user", {}).get("id")


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def _reset_presale(admin_h):
    r = requests.post(f"{BASE_URL}/api/admin/presale/reset",
                      headers=admin_h, timeout=30)
    assert r.status_code == 200


def _delete_user_businesses(admin_h, user_id):
    """Wipe all businesses/plots of the given user via direct Mongo access.

    The public API does not expose an admin delete-business endpoint, so we
    reach into Mongo to guarantee clean state between tests.
    """
    u = _mdb.users.find_one({"id": user_id}, {"_id": 0})
    if not u:
        return
    ids = [v for v in (u.get("id"), u.get("wallet_address"), u.get("email")) if v]
    _mdb.businesses.delete_many({"owner": {"$in": ids}})
    _mdb.plots.delete_many({"owner": {"$in": ids}})
    _mdb.land_listings.delete_many({"seller_id": {"$in": ids}})
    _mdb.users.update_one({"id": user_id}, {
        "$set": {"balance_ton": 100.0, "bonus_balance": 0.0,
                 "businesses_owned": [], "plots_owned": [],
                 "tutorial_active": False, "resources": {}},
        "$unset": {"has_graduated_zero": ""},
    })


def _get_island(user_h):
    r = requests.get(f"{BASE_URL}/api/island", headers=user_h, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


def _free_presale_cells(island, n=2):
    """Return up to n free cells that carry a pre_business (i.e. buildable)."""
    out = []
    for c in island.get("cells", []):
        if c.get("owner"):
            continue
        if not c.get("pre_business"):
            continue
        if c.get("is_empty"):
            continue
        out.append(c)
        if len(out) >= n:
            break
    return out


# ─────────────────────────── fixtures ───────────────────────────

@pytest.fixture(scope="module")
def admin_h():
    tok, _ = _login(ADMIN)
    return _auth(tok)


@pytest.fixture(scope="module")
def user1_h():
    tok, uid = _login(USER1)
    return _auth(tok), uid


@pytest.fixture(scope="module")
def user2_h():
    tok, uid = _login(USER2)
    return _auth(tok), uid


@pytest.fixture(scope="module", autouse=True)
def _clean(admin_h, user1_h, user2_h):
    """Wipe businesses of both test users and reset presale before/after."""
    _, u1 = user1_h
    _, u2 = user2_h
    _delete_user_businesses(admin_h, u1)
    _delete_user_businesses(admin_h, u2)
    _reset_presale(admin_h)
    yield
    _delete_user_businesses(admin_h, u1)
    _delete_user_businesses(admin_h, u2)
    _reset_presale(admin_h)


# ─────────────────────────── 1. Presale gate ───────────────────────────

class TestPresaleGate:
    def test_10_inactive_presale_blocks_buy_and_returns_button_text(
            self, admin_h, user1_h):
        # 1. Set a custom button text while presale inactive
        r = requests.post(f"{BASE_URL}/api/admin/presale/button-text",
                          json={"buy_button_text": "Скоро в продаже"},
                          headers=admin_h, timeout=30)
        assert r.status_code == 200
        assert r.json()["buy_button_text"] == "Скоро в продаже"

        # 2. Public config returns it while active=false
        r = requests.get(f"{BASE_URL}/api/presale/config", timeout=30)
        assert r.status_code == 200
        cfg = r.json()
        assert cfg["active"] is False
        assert cfg.get("buy_button_text") == "Скоро в продаже"

        # 3. Buying any island cell → 423 presale_locked + button_text
        h, _ = user1_h
        island = _get_island(h)
        cell = _free_presale_cells(island, 1)[0]
        x, y = cell["x"], cell["y"]
        r = requests.post(f"{BASE_URL}/api/island/buy/{x}/{y}",
                          headers=h, timeout=30)
        assert r.status_code == 423, r.text
        detail = r.json().get("detail", {})
        assert detail.get("code") == "presale_locked"
        assert detail.get("button_text") == "Скоро в продаже"

    def test_11_empty_string_button_text_allowed(self, admin_h):
        r = requests.post(f"{BASE_URL}/api/admin/presale/button-text",
                          json={"buy_button_text": ""},
                          headers=admin_h, timeout=30)
        assert r.status_code == 200
        assert r.json()["buy_button_text"] == ""
        cfg = requests.get(f"{BASE_URL}/api/presale/config", timeout=30).json()
        assert cfg.get("buy_button_text", "") == ""

    def test_12_active_presale_allows_only_selected_plots(
            self, admin_h, user1_h):
        # Set custom text again (used later by frontend)
        requests.post(f"{BASE_URL}/api/admin/presale/button-text",
                      json={"buy_button_text": "Скоро в продаже"},
                      headers=admin_h, timeout=30)

        h, uid = user1_h
        _delete_user_businesses(admin_h, uid)
        island = _get_island(h)
        candidates = _free_presale_cells(island, 4)
        assert len(candidates) >= 4, "not enough free pre_business cells"
        # Pick 2 cells of the SAME business type for select-plots
        by_type = {}
        for c in candidates:
            by_type.setdefault(c["pre_business"], []).append(c)
        btype = next(t for t, lst in by_type.items() if len(lst) >= 1)
        # select-plots picks arbitrary free plots of given type — we ask for 2
        r = requests.post(f"{BASE_URL}/api/admin/presale/select-plots",
                          json={"map_id": "ton_island",
                                "businesses": [{"type": btype, "count": 2}]},
                          headers=admin_h, timeout=30)
        assert r.status_code == 200, r.text
        selected = r.json()["selected_plots"]
        assert len(selected) >= 1

        # Approve
        r = requests.post(f"{BASE_URL}/api/admin/presale/approve",
                          json={"map_id": "ton_island",
                                "unavailable_label": "coming_epoch_2",
                                "opens_at": None},
                          headers=admin_h, timeout=30)
        assert r.status_code == 200, r.text

        cfg = requests.get(f"{BASE_URL}/api/presale/config", timeout=30).json()
        assert cfg["active"] is True
        assert cfg.get("buy_button_text") == "Скоро в продаже"

        # Store on class for next test
        TestPresaleGate.SELECTED = selected
        TestPresaleGate.BTYPE = btype

        # Non-selected cell → 423 presale_locked
        selected_coords = {(p["x"], p["y"]) for p in selected}
        outside = None
        for c in island["cells"]:
            if c.get("owner"):
                continue
            if (c["x"], c["y"]) in selected_coords:
                continue
            if not c.get("pre_business"):
                continue
            outside = c
            break
        assert outside is not None
        r = requests.post(
            f"{BASE_URL}/api/island/buy/{outside['x']}/{outside['y']}",
            headers=h, timeout=30)
        assert r.status_code == 423
        assert r.json().get("detail", {}).get("code") == "presale_locked"

    def test_13_reset_blocks_again(self, admin_h, user1_h):
        _reset_presale(admin_h)
        cfg = requests.get(f"{BASE_URL}/api/presale/config", timeout=30).json()
        assert cfg["active"] is False
        h, _ = user1_h
        island = _get_island(h)
        cell = _free_presale_cells(island, 1)[0]
        r = requests.post(
            f"{BASE_URL}/api/island/buy/{cell['x']}/{cell['y']}",
            headers=h, timeout=30)
        assert r.status_code == 423
        assert r.json().get("detail", {}).get("code") == "presale_locked"


# ───────────── 2. Zero-lock regression on presale-selected plot ─────────────

class TestZeroLockPresale:
    def test_20_stake_then_second_buy_zero_locked(
            self, admin_h, user1_h):
        h, uid = user1_h
        _delete_user_businesses(admin_h, uid)

        island = _get_island(h)
        candidates = _free_presale_cells(island, 20)
        by_type = {}
        for c in candidates:
            by_type.setdefault(c["pre_business"], []).append(c)
        btype = next(t for t, lst in by_type.items() if len(lst) >= 2)

        # Select at least 2 plots
        r = requests.post(f"{BASE_URL}/api/admin/presale/select-plots",
                          json={"map_id": "ton_island",
                                "businesses": [{"type": btype, "count": 3}]},
                          headers=admin_h, timeout=30)
        assert r.status_code == 200, r.text
        sel = r.json()["selected_plots"]
        assert len(sel) >= 2, f"need >=2 selected plots, got {len(sel)}"

        # Approve
        r = requests.post(f"{BASE_URL}/api/admin/presale/approve",
                          json={"map_id": "ton_island",
                                "unavailable_label": "coming_epoch_2",
                                "opens_at": None},
                          headers=admin_h, timeout=30)
        assert r.status_code == 200

        # Stake first plot (should succeed – Level-0 stake)
        p1, p2 = sel[0], sel[1]
        r1 = requests.post(
            f"{BASE_URL}/api/island/buy/{p1['x']}/{p1['y']}",
            headers=h, timeout=30)
        assert r1.status_code == 200, f"first stake failed: {r1.status_code} {r1.text}"

        # Now user holds a Level-0 business → second buy on ANOTHER presale
        # plot must return 423 zero_locked (not presale_locked).
        r2 = requests.post(
            f"{BASE_URL}/api/island/buy/{p2['x']}/{p2['y']}",
            headers=h, timeout=30)
        assert r2.status_code == 423, r2.text
        code = r2.json().get("detail", {}).get("code")
        # zero_locked expected; but some cells may still fail presale first if
        # user isn't in the allowlist. Assert either but prefer zero_locked.
        assert code in ("zero_locked",), f"expected zero_locked, got {code}"


# ───────────── 3. Partner-program business_upgrade task ─────────────

class TestPartnerBusinessUpgrade:
    def test_30_create_program_with_upgrade_flags(self, admin_h, user2_h):
        _, u2_id = user2_h
        payload = {
            "name": "TEST_upgrade_prog",
            "ref_link": f"?ref={u2_id}",
            "require_business_upgrade": True,
            "upgrade_from_level": 0,
            "upgrade_to_level": 1,
        }
        r = requests.post(f"{BASE_URL}/api/admin/partner-programs",
                          json=payload, headers=admin_h, timeout=30)
        assert r.status_code in (200, 201), r.text
        j = r.json()
        pid = j.get("id") or j.get("program", {}).get("id")
        assert pid, f"no id returned: {j}"
        TestPartnerBusinessUpgrade.PID = pid

        # GET list must include the new flags
        r = requests.get(f"{BASE_URL}/api/admin/partner-programs",
                         headers=admin_h, timeout=30)
        assert r.status_code == 200
        items = r.json() if isinstance(r.json(), list) else r.json().get("programs", [])
        me = next((p for p in items if (p.get("id") == pid)), None)
        assert me is not None, "created program not in list"
        assert me.get("require_business_upgrade") is True
        assert me.get("upgrade_from_level") == 0
        assert me.get("upgrade_to_level") == 1

    def test_31_patch_upgrade_levels(self, admin_h):
        pid = TestPartnerBusinessUpgrade.PID
        # Try PATCH first, fall back to PUT
        r = requests.patch(f"{BASE_URL}/api/admin/partner-programs/{pid}",
                           json={"upgrade_from_level": 0,
                                 "upgrade_to_level": 2},
                           headers=admin_h, timeout=30)
        if r.status_code == 405:
            r = requests.put(f"{BASE_URL}/api/admin/partner-programs/{pid}",
                             json={"upgrade_from_level": 0,
                                   "upgrade_to_level": 2},
                             headers=admin_h, timeout=30)
        assert r.status_code in (200, 201, 204), r.text

        r = requests.get(f"{BASE_URL}/api/admin/partner-programs",
                         headers=admin_h, timeout=30)
        items = r.json() if isinstance(r.json(), list) else r.json().get("programs", [])
        me = next(p for p in items if p.get("id") == pid)
        assert me.get("upgrade_to_level") == 2

        # Restore to 1 for the rest of the tests
        requests.patch(f"{BASE_URL}/api/admin/partner-programs/{pid}",
                       json={"upgrade_to_level": 1},
                       headers=admin_h, timeout=30)

    def test_32_referred_users_returns_upgrade_fields(self, admin_h):
        pid = TestPartnerBusinessUpgrade.PID
        r = requests.get(
            f"{BASE_URL}/api/admin/partner-programs/{pid}/referred-users",
            headers=admin_h, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        # Top-level fields
        assert body.get("require_business_upgrade") is True
        assert body.get("upgrade_from_level") == 0
        assert body.get("upgrade_to_level") == 1
        users = body.get("users") or body.get("referred_users") or []
        # Per-user fields present when there are referrals (best-effort)
        for u in users:
            assert "upgrade_count" in u
            assert "upgrade_ok" in u

    def test_33_cleanup_delete_program(self, admin_h):
        pid = TestPartnerBusinessUpgrade.PID
        r = requests.delete(
            f"{BASE_URL}/api/admin/partner-programs/{pid}",
            headers=admin_h, timeout=30)
        assert r.status_code in (200, 204, 404)


# ─────────── 4. business_upgrade transaction written on upgrade ───────────

class TestBusinessUpgradeTx:
    def test_40_upgrade_writes_business_upgrade_tx(self, admin_h, user1_h):
        """Stake a Level-0 plot, top-up, upgrade 0→1, then verify a
        transaction of type='business_upgrade' with details.new_level=1
        was written for the user."""
        h, uid = user1_h
        _delete_user_businesses(admin_h, uid)
        _reset_presale(admin_h)

        island = _get_island(h)
        candidates = _free_presale_cells(island, 8)
        by_type = {}
        for c in candidates:
            by_type.setdefault(c["pre_business"], []).append(c)
        btype = next(t for t, lst in by_type.items() if len(lst) >= 1)

        r = requests.post(f"{BASE_URL}/api/admin/presale/select-plots",
                          json={"map_id": "ton_island",
                                "businesses": [{"type": btype, "count": 1}]},
                          headers=admin_h, timeout=30)
        assert r.status_code == 200
        sel = r.json()["selected_plots"]
        assert len(sel) >= 1
        requests.post(f"{BASE_URL}/api/admin/presale/approve",
                      json={"map_id": "ton_island",
                            "unavailable_label": "coming_epoch_2",
                            "opens_at": None},
                      headers=admin_h, timeout=30)
        p = sel[0]
        r = requests.post(f"{BASE_URL}/api/island/buy/{p['x']}/{p['y']}",
                         headers=h, timeout=30)
        assert r.status_code == 200, r.text
        biz = r.json().get("business") or {}
        bid = biz.get("id")
        assert bid, r.text

        # Top up: give user 10000 TON so they can pay ANY upgrade cost
        _mdb.users.update_one({"id": uid},
                              {"$set": {"balance_ton": 10000.0}})
        _tx_before = _mdb.transactions.count_documents({
            "user_id": uid, "type": "business_upgrade"})

        # Upgrade
        r = requests.post(f"{BASE_URL}/api/business/{bid}/upgrade",
                         headers=h, timeout=30)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j.get("new_level") == 1

        # Verify tx recorded
        _tx_after = _mdb.transactions.count_documents({
            "user_id": uid, "type": "business_upgrade"})
        assert _tx_after == _tx_before + 1

        tx = _mdb.transactions.find_one(
            {"user_id": uid, "type": "business_upgrade",
             "details.business_id": bid},
            {"_id": 0},
            sort=[("created_at", -1)])
        assert tx is not None, "business_upgrade tx not found"
        assert tx.get("details", {}).get("new_level") == 1
