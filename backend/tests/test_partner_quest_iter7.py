"""
Partner/Local Quests E2E backend tests (Iteration 7).

Covers admin creation of partner_quest tasks (local + partner kinds),
user verification flow with success + failure paths, reward crediting
(coins/resources/skins) and secret-hiding in user-facing list.
"""
import os
import uuid
import time
import pytest
import requests

def _load_backend_url():
    v = os.environ.get("REACT_APP_BACKEND_URL")
    if not v:
        try:
            with open("/app/frontend/.env") as f:
                for line in f:
                    if line.startswith("REACT_APP_BACKEND_URL="):
                        v = line.split("=", 1)[1].strip()
                        break
        except FileNotFoundError:
            pass
    if not v:
        raise RuntimeError("REACT_APP_BACKEND_URL missing")
    return v.rstrip("/")


BASE_URL = _load_backend_url()
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PW = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PW = "Test1234!"

PARTNER_OK_URL = f"{BASE_URL}/api/health"
PARTNER_FAIL_URL = f"{BASE_URL}/api/nonexistent-xyz-{uuid.uuid4().hex[:6]}"


def _login(email, pw):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=15)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    j = r.json()
    tok = j.get("access_token") or j.get("token")
    assert tok, f"no token in login resp: {j}"
    return tok


@pytest.fixture(scope="module")
def admin_token():
    return _login(ADMIN_EMAIL, ADMIN_PW)


@pytest.fixture(scope="module")
def user_token():
    return _login(USER_EMAIL, USER_PW)


@pytest.fixture(scope="module")
def created_tasks(admin_token):
    """Create 3 quests: local, partner-ok (200), partner-fail (404). Yield ids, cleanup after."""
    hdr = {"Authorization": f"Bearer {admin_token}"}
    ids = {}

    payload_local = {
        "title": f"TEST_local_quest_{uuid.uuid4().hex[:6]}",
        "action_type": "partner_quest",
        "reward_city": 10,
        "quest_kind": "local",
        "target_url": "https://example.com",
        "instructions": "Do the thing then Verify",
        "reward_resources": {"crops": 100},
        "reward_skins": [{"id": f"skin_test_{uuid.uuid4().hex[:6]}", "name": "TestSkin"}],
    }
    r = requests.post(f"{API}/admin/tasks", json=payload_local, headers=hdr, timeout=15)
    assert r.status_code == 200, f"local create failed: {r.status_code} {r.text}"
    tj = r.json()["task"]
    ids["local"] = tj["id"]
    ids["local_skin_id"] = payload_local["reward_skins"][0]["id"]

    payload_ok = {
        "title": f"TEST_partner_ok_{uuid.uuid4().hex[:6]}",
        "action_type": "partner_quest",
        "reward_city": 20,
        "quest_kind": "partner",
        "partner_url": PARTNER_OK_URL,
        "partner_ref_id": "ref_test_ok",
        "partner_method": "GET",
        "target_url": "https://example.com",
    }
    r = requests.post(f"{API}/admin/tasks", json=payload_ok, headers=hdr, timeout=15)
    assert r.status_code == 200, f"partner_ok create failed: {r.status_code} {r.text}"
    ids["partner_ok"] = r.json()["task"]["id"]

    payload_fail = {
        "title": f"TEST_partner_fail_{uuid.uuid4().hex[:6]}",
        "action_type": "partner_quest",
        "reward_city": 15,
        "quest_kind": "partner",
        "partner_url": PARTNER_FAIL_URL,
        "partner_ref_id": "ref_test_fail",
        "partner_method": "GET",
    }
    r = requests.post(f"{API}/admin/tasks", json=payload_fail, headers=hdr, timeout=15)
    assert r.status_code == 200, f"partner_fail create failed: {r.status_code} {r.text}"
    ids["partner_fail"] = r.json()["task"]["id"]

    yield ids

    # cleanup
    for key in ("local", "partner_ok", "partner_fail"):
        try:
            requests.delete(f"{API}/admin/tasks/{ids[key]}", headers=hdr, timeout=10)
        except Exception:
            pass


class TestAdminCreatesQuests:
    def test_local_created(self, created_tasks):
        assert created_tasks["local"]

    def test_partner_created(self, created_tasks):
        assert created_tasks["partner_ok"]
        assert created_tasks["partner_fail"]

    def test_admin_list_contains_partner_secrets(self, admin_token, created_tasks):
        hdr = {"Authorization": f"Bearer {admin_token}"}
        r = requests.get(f"{API}/admin/tasks", headers=hdr, timeout=15)
        assert r.status_code == 200
        arr = r.json() if isinstance(r.json(), list) else r.json().get("tasks", [])
        found = [t for t in arr if t.get("id") == created_tasks["partner_ok"]]
        assert found, "partner_ok task missing in admin list"
        t = found[0]
        assert t.get("partner_url") == PARTNER_OK_URL
        assert t.get("quest_kind") == "partner"


class TestUserListSecrecy:
    def test_user_list_hides_partner_secrets(self, user_token, created_tasks):
        hdr = {"Authorization": f"Bearer {user_token}"}
        r = requests.get(f"{API}/tasks", headers=hdr, timeout=15)
        assert r.status_code == 200
        payload = r.json()
        arr = payload if isinstance(payload, list) else payload.get("tasks", [])
        partner_ids = {created_tasks["partner_ok"], created_tasks["partner_fail"]}
        seen = 0
        for t in arr:
            if t.get("id") in partner_ids:
                seen += 1
                assert "partner_url" not in t, f"partner_url leaked: {t}"
                assert "partner_ref_id" not in t, f"partner_ref_id leaked: {t}"
        assert seen == 2, f"expected 2 partner quests, saw {seen}"

    def test_user_list_shows_reward_chips(self, user_token, created_tasks):
        hdr = {"Authorization": f"Bearer {user_token}"}
        r = requests.get(f"{API}/tasks", headers=hdr, timeout=15)
        arr = r.json() if isinstance(r.json(), list) else r.json().get("tasks", [])
        local = next((t for t in arr if t.get("id") == created_tasks["local"]), None)
        assert local, "local quest not visible to user"
        assert local.get("reward_resources", {}).get("crops") == 100
        assert local.get("reward_skins"), "skins missing"
        assert local.get("instructions") == "Do the thing then Verify"


class TestVerifyFlows:
    def _me(self, token):
        r = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"}, timeout=15)
        return r.json() if r.status_code == 200 else {}

    def test_local_verify_grants_all(self, user_token, created_tasks):
        hdr = {"Authorization": f"Bearer {user_token}"}
        before = self._me(user_token)
        b_bal = float(before.get("balance_ton") or 0)
        b_crops = 0.0
        rr = requests.get(f"{API}/economy/my-resources", headers=hdr, timeout=15)
        if rr.status_code == 200:
            body = rr.json()
            res_map = body.get("resources") if isinstance(body, dict) else {}
            if isinstance(res_map, dict):
                v = res_map.get("crops")
                if isinstance(v, dict):
                    b_crops = float(v.get("amount") or 0)
                elif v is not None:
                    b_crops = float(v)

        r = requests.post(f"{API}/tasks/{created_tasks['local']}/verify", headers=hdr, timeout=20)
        assert r.status_code == 200, f"local verify: {r.status_code} {r.text}"

        after = self._me(user_token)
        a_bal = float(after.get("balance_ton") or 0)
        a_crops = 0.0
        rr = requests.get(f"{API}/economy/my-resources", headers=hdr, timeout=15)
        if rr.status_code == 200:
            body = rr.json()
            res_map = body.get("resources") if isinstance(body, dict) else {}
            if isinstance(res_map, dict):
                v = res_map.get("crops")
                if isinstance(v, dict):
                    a_crops = float(v.get("amount") or 0)
                elif v is not None:
                    a_crops = float(v)
        # reward_city=10 -> +0.010 TON
        assert a_bal - b_bal >= 0.009, f"coins not credited: {b_bal}->{a_bal}"
        assert a_crops - b_crops >= 100, f"crops not credited: {b_crops}->{a_crops}"

        # skins/my should include the granted skin
        rs = requests.get(f"{API}/tasks/skins/my", headers=hdr, timeout=15)
        assert rs.status_code == 200, rs.text
        skins_payload = rs.json()
        skins_list = skins_payload if isinstance(skins_payload, list) else skins_payload.get("skins", [])
        ids = {(s.get("id") if isinstance(s, dict) else s) for s in skins_list}
        assert created_tasks["local_skin_id"] in ids, f"skin not granted: {ids}"

    def test_partner_ok_verify_succeeds(self, user_token, created_tasks):
        hdr = {"Authorization": f"Bearer {user_token}"}
        before = self._me(user_token)
        b_bal = float(before.get("balance_ton") or 0)
        r = requests.post(f"{API}/tasks/{created_tasks['partner_ok']}/verify", headers=hdr, timeout=25)
        assert r.status_code == 200, f"partner_ok verify: {r.status_code} {r.text}"
        after = self._me(user_token)
        a_bal = float(after.get("balance_ton") or 0)
        # reward_city=20 -> +0.020 TON
        assert a_bal - b_bal >= 0.019, f"partner ok coins not credited: {b_bal}->{a_bal}"

    def test_partner_fail_verify_shows_ru_error(self, user_token, created_tasks):
        hdr = {"Authorization": f"Bearer {user_token}", "Accept-Language": "ru"}
        r = requests.post(f"{API}/tasks/{created_tasks['partner_fail']}/verify", headers=hdr, timeout=25)
        assert r.status_code == 400, f"partner_fail should not credit: {r.status_code} {r.text}"
        # RU message must be a "conditions not met yet" hint
        body = r.text
        assert ("Условия квеста" in body) or ("не выполнены" in body), f"missing RU msg: {body}"
