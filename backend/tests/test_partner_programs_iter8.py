"""B2B Partner Programs (INCOMING verification) — iter 8 tests."""
import os
import requests
import pytest

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://quest-rewards-74.preview.emergentagent.com").rstrip("/")
ADMIN = {"email": "sanyanazarov212@gmail.com", "password": os.environ.get("TEST_ADMIN_PASSWORD", "")}
USER = {"email": "testuser@example.com", "password": "Test1234!"}


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE}/api/auth/login", json=ADMIN, timeout=15)
    assert r.status_code == 200, r.text
    j = r.json()
    return j.get("access_token") or j.get("token")


@pytest.fixture(scope="module")
def admin_id():
    r = requests.post(f"{BASE}/api/auth/login", json=ADMIN, timeout=15)
    return r.json()["user"]["id"]


@pytest.fixture(scope="module")
def testuser_id():
    r = requests.post(f"{BASE}/api/auth/login", json=USER, timeout=15)
    assert r.status_code == 200
    return r.json()["user"]["id"]


@pytest.fixture(scope="module")
def hdr(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


created_ids = []


# ---- Ref-link validation ----
def test_create_bad_ref_link_no_query(hdr):
    r = requests.post(f"{BASE}/api/admin/partner-programs", headers=hdr,
                      json={"name": "TEST_bad1", "ref_link": "https://site/nothing-here/"}, timeout=15)
    assert r.status_code == 400, r.text


def test_create_ref_link_unknown_user(hdr):
    r = requests.post(f"{BASE}/api/admin/partner-programs", headers=hdr,
                      json={"name": "TEST_bad2", "ref_link": "https://site/?ref=nonexistent_user_xyz_123"},
                      timeout=15)
    assert r.status_code == 400
    assert "не найден" in r.text.lower() or "not found" in r.text.lower() or "найден" in r.text.lower()


# ---- CRUD + verify ----
def test_create_valid_program(hdr, admin_id):
    payload = {
        "name": "TEST_program_iter8",
        "ref_link": f"https://quest-rewards-74.preview.emergentagent.com/?ref={admin_id}",
        "require_land": True,
        "min_market_spend_city": 100,
        "per_active_user_city": 500,
        "income_percent": 10,
    }
    r = requests.post(f"{BASE}/api/admin/partner-programs", headers=hdr, json=payload, timeout=15)
    assert r.status_code == 200, r.text
    prog = r.json()["program"]
    assert prog["referrer_user_id"] == admin_id
    assert prog["api_key"]
    assert prog["min_market_spend_city"] == 100
    assert prog["per_active_user_city"] == 500
    assert prog["income_percent"] == 10
    assert prog["require_land"] is True
    assert prog["active"] is True
    assert "verify_path" in prog
    created_ids.append((prog["id"], prog["api_key"]))


def test_list_programs_contains_created(hdr):
    r = requests.get(f"{BASE}/api/admin/partner-programs", headers=hdr, timeout=15)
    assert r.status_code == 200
    ids = [p["id"] for p in r.json()["programs"]]
    assert created_ids[0][0] in ids


def test_verify_returns_402_for_unmet(testuser_id):
    _, api_key = created_ids[0]
    r = requests.get(f"{BASE}/api/partner/verify/{api_key}", params={"user_id": testuser_id}, timeout=15)
    assert r.status_code == 402, r.text
    body = r.json()
    assert body["status"] == "incomplete"
    assert "missing" in body
    assert "checks" in body
    # referral or land or market should be among missing
    assert body["missing"], "missing should be non-empty"


def test_verify_missing_user_id_400():
    _, api_key = created_ids[0]
    r = requests.get(f"{BASE}/api/partner/verify/{api_key}", timeout=15)
    assert r.status_code == 400


def test_verify_unknown_key_404(testuser_id):
    r = requests.get(f"{BASE}/api/partner/verify/nonexistent_key_zzz", params={"user_id": testuser_id}, timeout=15)
    assert r.status_code == 404


def test_logs_contain_402(hdr):
    pid, _ = created_ids[0]
    r = requests.get(f"{BASE}/api/admin/partner-programs/{pid}/logs", headers=hdr, timeout=15)
    assert r.status_code == 200
    logs = r.json()["logs"]
    assert len(logs) >= 1
    assert any(l["result_code"] == 402 and l["success"] is False for l in logs)


def test_logs_filter_failed(hdr):
    pid, _ = created_ids[0]
    r = requests.get(f"{BASE}/api/admin/partner-programs/{pid}/logs", params={"status": "failed"}, headers=hdr, timeout=15)
    assert r.status_code == 200
    for l in r.json()["logs"]:
        assert l["success"] is False


def test_toggle_active(hdr):
    pid, api_key = created_ids[0]
    r = requests.patch(f"{BASE}/api/admin/partner-programs/{pid}", headers=hdr,
                      json={"active": False}, timeout=15)
    assert r.status_code == 200
    assert r.json()["program"]["active"] is False
    # verify now 403
    r2 = requests.get(f"{BASE}/api/partner/verify/{api_key}", params={"user_id": "any"}, timeout=15)
    assert r2.status_code == 403
    # toggle back
    requests.patch(f"{BASE}/api/admin/partner-programs/{pid}", headers=hdr, json={"active": True}, timeout=15)


def test_delete_program(hdr):
    pid, _ = created_ids[0]
    r = requests.delete(f"{BASE}/api/admin/partner-programs/{pid}", headers=hdr, timeout=15)
    assert r.status_code == 200
    # gone from list
    r2 = requests.get(f"{BASE}/api/admin/partner-programs", headers=hdr, timeout=15)
    ids = [p["id"] for p in r2.json()["programs"]]
    assert pid not in ids
