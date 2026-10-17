"""
Iter 9 backend tests: Business Skins system + partner referrals/completions chart.
Covers /api/skins/index, /api/skins/my, /api/admin/skins CRUD (webp guard + 409 conflict),
and /api/admin/partner-programs/{id}/chart.
"""
import os
import base64
import uuid
from datetime import datetime, timezone

import pytest
import requests
from pymongo import MongoClient

def _read_env(path, key):
    try:
        for line in open(path):
            line = line.strip()
            if line.startswith(key + "="):
                v = line.split("=", 1)[1].strip().strip('"').strip("'")
                return v
    except FileNotFoundError:
        pass
    return None

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or _read_env("/app/frontend/.env", "REACT_APP_BACKEND_URL")).rstrip("/")
MONGO_URL = (os.environ.get("MONGO_URL")
             or _read_env("/app/backend/.env", "MONGO_URL")
             or "mongodb://localhost:27017")
DB_NAME = (os.environ.get("DB_NAME")
           or _read_env("/app/backend/.env", "DB_NAME")
           or "test_database")

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PASSWORD = "Test1234!"

# Smallest valid WEBP (VP8L 1x1) base64
WEBP_1X1_B64 = "UklGRhoAAABXRUJQVlA4TA0AAAAvAAAAEAcQERGIiP4HAA=="
WEBP_DATA_URL = f"data:image/webp;base64,{WEBP_1X1_B64}"


@pytest.fixture(scope="module")
def db():
    c = MongoClient(MONGO_URL)
    return c[DB_NAME]


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text}"
    return r.json()


@pytest.fixture(scope="module")
def admin_auth():
    d = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    return {"token": d.get("token") or d.get("access_token"), "user": d.get("user") or d}


@pytest.fixture(scope="module")
def user_auth():
    d = _login(USER_EMAIL, USER_PASSWORD)
    return {"token": d.get("token") or d.get("access_token"), "user": d.get("user") or d}


def h(t):
    return {"Authorization": f"Bearer {t}", "Content-Type": "application/json"}


# ── Skins index / groups ─────────────────────────────────────────────────────
class TestSkinsIndexAndGroups:
    def test_index_public_has_standard_and_crazy(self):
        r = requests.get(f"{BASE_URL}/api/skins/index", timeout=30)
        assert r.status_code == 200, r.text
        idx = r.json().get("index", {})
        assert "standard" in idx and "bio_farm" in idx["standard"], idx
        assert idx["standard"]["bio_farm"].get("0") == "/sprites/bio_farm/bio_farm.webp"
        assert "crazy_bio_farm" in idx
        assert idx["crazy_bio_farm"]["bio_farm"].get("0") == "/sprites/crazy_bio_farm/crazy_bio_farm.webp"

    def test_admin_groups_lists_both(self, admin_auth):
        r = requests.get(f"{BASE_URL}/api/admin/skins/groups", headers=h(admin_auth["token"]), timeout=30)
        assert r.status_code == 200, r.text
        keys = {g["group_key"] for g in r.json().get("groups", [])}
        assert "standard" in keys and "crazy_bio_farm" in keys, keys


# ── my-skins for regular user ────────────────────────────────────────────────
class TestMySkins:
    def test_only_standard_initially_then_grant_crazy(self, user_auth, db):
        uid = user_auth["user"].get("id")
        # Reset
        db.users.update_one({"id": uid}, {"$set": {"available_skins": []}})
        r = requests.get(f"{BASE_URL}/api/skins/my?business_type=bio_farm",
                         headers=h(user_auth["token"]), timeout=30)
        assert r.status_code == 200, r.text
        keys = {s["group_key"] for s in r.json().get("skins", [])}
        assert keys == {"standard"}, keys
        # Grant crazy
        db.users.update_one({"id": uid}, {"$addToSet": {"available_skins": "crazy_bio_farm"}})
        r = requests.get(f"{BASE_URL}/api/skins/my?business_type=bio_farm",
                         headers=h(user_auth["token"]), timeout=30)
        assert r.status_code == 200
        keys = {s["group_key"] for s in r.json().get("skins", [])}
        assert keys == {"standard", "crazy_bio_farm"}, keys
        # Cleanup
        db.users.update_one({"id": uid}, {"$set": {"available_skins": []}})


# ── Admin create / conflict / non-webp / delete ──────────────────────────────
class TestAdminSkinsCRUD:
    _created_id = None
    _group_key = f"TEST_grp_{uuid.uuid4().hex[:6]}"

    def test_create_webp_data_url_ok(self, admin_auth):
        payload = {
            "group_key": self._group_key,
            "group_name": "TEST Group",
            "business_type": "bio_farm",
            "level": 1,
            "image": WEBP_DATA_URL,
            "is_standard": False,
        }
        r = requests.post(f"{BASE_URL}/api/admin/skins",
                          headers=h(admin_auth["token"]), json=payload, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("status") == "created"
        assert data["skin"]["group_key"] == self._group_key
        TestAdminSkinsCRUD._created_id = data["skin"]["id"]

    def test_conflict_on_duplicate(self, admin_auth):
        payload = {
            "group_key": self._group_key,
            "group_name": "TEST Group",
            "business_type": "bio_farm",
            "level": 1,
            "image": WEBP_DATA_URL,
        }
        r = requests.post(f"{BASE_URL}/api/admin/skins",
                          headers=h(admin_auth["token"]), json=payload, timeout=30)
        assert r.status_code == 409, r.text

    def test_reject_non_webp(self, admin_auth):
        payload = {
            "group_key": self._group_key + "_png",
            "group_name": "TEST PNG",
            "business_type": "bio_farm",
            "level": 2,
            "image": "data:image/png;base64,iVBORw0KGgo=",
        }
        r = requests.post(f"{BASE_URL}/api/admin/skins",
                          headers=h(admin_auth["token"]), json=payload, timeout=30)
        assert r.status_code == 400, r.text

    def test_delete_created(self, admin_auth):
        assert TestAdminSkinsCRUD._created_id
        r = requests.delete(
            f"{BASE_URL}/api/admin/skins/{TestAdminSkinsCRUD._created_id}",
            headers=h(admin_auth["token"]), timeout=30)
        assert r.status_code == 200
        assert r.json().get("status") == "deleted"


# ── Partner chart end-to-end ─────────────────────────────────────────────────
class TestPartnerChart:
    _pid = None

    def test_chart_flow(self, admin_auth, user_auth, db):
        admin_id = admin_auth["user"].get("id")
        user_id = user_auth["user"].get("id")
        assert admin_id and user_id

        # Create program
        r = requests.post(f"{BASE_URL}/api/admin/partner-programs",
                          headers=h(admin_auth["token"]),
                          json={"name": f"TEST_prog_{uuid.uuid4().hex[:6]}",
                                "ref_link": f"https://x/?ref={admin_id}",
                                "require_land": True,
                                "min_market_spend_city": 100,
                                "per_active_user_city": 0,
                                "income_percent": 0},
                          timeout=30)
        assert r.status_code == 200, r.text
        prog = r.json().get("program") or r.json()
        pid = prog.get("id")
        api_key = prog.get("api_key")
        assert pid and api_key
        TestPartnerChart._pid = pid

        today_iso = datetime.now(timezone.utc).isoformat()
        today_ymd = today_iso[:10]

        # Attribute testuser to admin partner + mark createdAt today
        db.users.update_one({"id": user_id},
                            {"$set": {"referrerId": admin_id, "created_at": today_iso}})

        # Insert a land purchase tx and market_purchase (0.2 TON = 200 CITY, meets 100 threshold)
        db.transactions.insert_one({
            "id": f"TEST_tx_{uuid.uuid4().hex}", "tx_type": "purchase_plot",
            "user_id": user_id, "buyer_id": user_id, "amount": 1,
            "created_at": today_iso,
        })
        db.transactions.insert_one({
            "id": f"TEST_tx_{uuid.uuid4().hex}", "tx_type": "market_purchase",
            "buyer_id": user_id, "amount_ton": 0.2, "created_at": today_iso,
        })

        # Verify (public endpoint, activates progress)
        vr = requests.get(f"{BASE_URL}/api/partner/verify/{api_key}",
                         params={"user_id": user_id}, timeout=30)
        assert vr.status_code == 200, vr.text

        # Chart
        cr = requests.get(f"{BASE_URL}/api/admin/partner-programs/{pid}/chart",
                         headers=h(admin_auth["token"]), params={"days": 7}, timeout=30)
        assert cr.status_code == 200, cr.text
        data = cr.json()
        assert "labels" in data and today_ymd in data["labels"], data
        idx = data["labels"].index(today_ymd)
        assert data["referrals"][idx] >= 1, data
        assert data["completions"][idx] >= 1, data

    def test_cleanup(self, admin_auth, user_auth, db):
        user_id = user_auth["user"].get("id")
        # Remove attribution + test txns + program + progress
        db.users.update_one({"id": user_id}, {"$unset": {"referrerId": ""}})
        db.transactions.delete_many({"id": {"$regex": "^TEST_tx_"}})
        if TestPartnerChart._pid:
            db.partner_program_progress.delete_many({"program_id": TestPartnerChart._pid})
            requests.delete(
                f"{BASE_URL}/api/admin/partner-programs/{TestPartnerChart._pid}",
                headers=h(admin_auth["token"]), timeout=30)
