"""Iteration 7 — Admin task EDIT endpoint: PUT /api/admin/tasks/{task_id}/update"""
import os
import pytest
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values("/app/frontend/.env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = base_url.rstrip("/")

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=60)
    if r.status_code != 200:
        pytest.fail(f"admin login failed {r.status_code}: {r.text[:300]}")
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok, f"no token in login response: {r.text[:300]}"
    return tok


@pytest.fixture(scope="module")
def client(admin_token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def created_ids():
    return []


@pytest.fixture(scope="module", autouse=True)
def cleanup(client, created_ids):
    yield
    for tid in created_ids:
        requests.delete(f"{BASE_URL}/api/admin/tasks/{tid}", headers=dict(client.headers), timeout=60)


class TestAdminTaskEdit:
    def test_create_update_persist(self, client, created_ids):
        # (1) create
        r = client.post(f"{BASE_URL}/api/admin/tasks", json={
            "title": "TEST_QA Edit Test", "action_type": "visit_link",
            "target_url": "https://a.example", "reward_city": 10}, timeout=120)
        assert r.status_code == 200, r.text[:400]
        task = r.json()["task"]
        tid, order = task["id"], task["order"]
        created_ids.append(tid)
        assert task["title"] == "TEST_QA Edit Test"
        assert task["reward_city"] == 10

        list_before = client.get(f"{BASE_URL}/api/admin/tasks", timeout=60).json()["tasks"]
        count_before = len(list_before)

        # (2) update
        u = client.put(f"{BASE_URL}/api/admin/tasks/{tid}/update", json={
            "title": "TEST_QA Edit Test 2", "action_type": "visit_link",
            "target_url": "https://b.example", "reward_city": 25}, timeout=120)
        assert u.status_code == 200, u.text[:400]
        assert u.json().get("status") == "updated"

        # (3) verify persistence via GET
        tasks = client.get(f"{BASE_URL}/api/admin/tasks", timeout=60).json()["tasks"]
        assert len(tasks) == count_before, "task count changed — edit created a new task"
        found = [t for t in tasks if t["id"] == tid]
        assert len(found) == 1
        t = found[0]
        assert t["title"] == "TEST_QA Edit Test 2"
        assert t["reward_city"] == 25
        assert t["target_url"] == "https://b.example"
        assert t["order"] == order, f"order changed {order} -> {t['order']}"
        assert t.get("active") is True
        assert "_id" not in t

    def test_reorder_not_shadowed(self, client):
        tasks = client.get(f"{BASE_URL}/api/admin/tasks", timeout=60).json()["tasks"]
        ids = [t["id"] for t in tasks]
        r = client.put(f"{BASE_URL}/api/admin/tasks/reorder", json={"ids": ids}, timeout=60)
        assert r.status_code == 200, r.text[:400]
        assert r.json().get("status") == "reordered"

    def test_update_validation_referral(self, client, created_ids):
        tid = created_ids[0]
        r = client.put(f"{BASE_URL}/api/admin/tasks/{tid}/update", json={
            "title": "TEST_bad", "action_type": "referral_invite",
            "required_referrals": 0, "reward_city": 5}, timeout=60)
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text[:300]}"

    def test_update_unknown_task_404(self, client):
        r = client.put(f"{BASE_URL}/api/admin/tasks/does-not-exist-xyz/update", json={
            "title": "TEST_x", "action_type": "visit_link",
            "target_url": "https://c.example", "reward_city": 1}, timeout=60)
        assert r.status_code == 404, f"expected 404, got {r.status_code}: {r.text[:300]}"

    def test_update_requires_auth(self):
        r = requests.put(f"{BASE_URL}/api/admin/tasks/whatever/update", json={
            "title": "x", "action_type": "visit_link", "target_url": "https://d.example"}, timeout=60)
        assert r.status_code in (401, 403), f"got {r.status_code}"
