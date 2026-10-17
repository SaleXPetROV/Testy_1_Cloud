"""Backend tests for NEW Tasks capabilities:
- PUT /api/admin/tasks/reorder
- PATCH /api/admin/tasks/{id}/active (hides from user GET /api/tasks)
- completions_count field on both admin and user endpoints
"""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PASSWORD = "Test1234!"


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    return r.json().get("token") or r.json().get("access_token")


def AH(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def admin_token():
    return _login(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def user_token():
    return _login(USER_EMAIL, USER_PASSWORD)


_created = []


@pytest.fixture(scope="module", autouse=True)
def _cleanup(admin_token):
    yield
    for tid in _created:
        try:
            requests.delete(f"{BASE_URL}/api/admin/tasks/{tid}", headers=AH(admin_token), timeout=15)
        except Exception:
            pass


def _create_visit(admin_token, title_suffix):
    p = {
        "title": f"TEST_reorder_{title_suffix}_{uuid.uuid4().hex[:5]}",
        "reward_city": 10,
        "action_type": "visit_link",
        "target_url": "https://example.com",
    }
    r = requests.post(f"{BASE_URL}/api/admin/tasks", json=p, headers=AH(admin_token), timeout=20)
    assert r.status_code == 200, r.text
    tid = r.json()["task"]["id"]
    _created.append(tid)
    return tid


class TestReorder:
    def test_reorder_persists(self, admin_token):
        t1 = _create_visit(admin_token, "a")
        t2 = _create_visit(admin_token, "b")
        t3 = _create_visit(admin_token, "c")
        pytest.reorder_ids = (t1, t2, t3)

        new_order = [t3, t1, t2]
        r = requests.put(f"{BASE_URL}/api/admin/tasks/reorder",
                         json={"ids": new_order}, headers=AH(admin_token), timeout=20)
        assert r.status_code == 200, r.text
        assert r.json().get("status") == "reordered"

        lst = requests.get(f"{BASE_URL}/api/admin/tasks", headers=AH(admin_token), timeout=20).json()["tasks"]
        # Filter to our created tasks and verify order among them
        by_id = {t["id"]: t for t in lst}
        assert by_id[t3]["order"] == 0
        assert by_id[t1]["order"] == 1
        assert by_id[t2]["order"] == 2

        # Verify listing sort places them in the reordered sequence
        ordered_ids = [t["id"] for t in lst if t["id"] in new_order]
        assert ordered_ids == new_order, f"Expected {new_order}, got {ordered_ids}"


class TestActiveToggle:
    def test_active_toggle_hides_from_user(self, admin_token, user_token):
        tid = _create_visit(admin_token, "toggle")

        # Initially visible to user
        u_lst = requests.get(f"{BASE_URL}/api/tasks", headers=AH(user_token), timeout=20).json()["tasks"]
        assert tid in {t["id"] for t in u_lst}

        # Turn OFF
        r = requests.patch(f"{BASE_URL}/api/admin/tasks/{tid}/active",
                           json={"active": False}, headers=AH(admin_token), timeout=15)
        assert r.status_code == 200, r.text
        assert r.json().get("active") is False

        # Admin still sees it (active=false)
        a_lst = requests.get(f"{BASE_URL}/api/admin/tasks", headers=AH(admin_token), timeout=20).json()["tasks"]
        by_id = {t["id"]: t for t in a_lst}
        assert tid in by_id
        assert by_id[tid].get("active") is False

        # User does NOT see it
        u_lst2 = requests.get(f"{BASE_URL}/api/tasks", headers=AH(user_token), timeout=20).json()["tasks"]
        assert tid not in {t["id"] for t in u_lst2}

        # Turn back ON
        r2 = requests.patch(f"{BASE_URL}/api/admin/tasks/{tid}/active",
                            json={"active": True}, headers=AH(admin_token), timeout=15)
        assert r2.status_code == 200
        assert r2.json().get("active") is True

        u_lst3 = requests.get(f"{BASE_URL}/api/tasks", headers=AH(user_token), timeout=20).json()["tasks"]
        assert tid in {t["id"] for t in u_lst3}

    def test_toggle_unknown_returns_404(self, admin_token):
        r = requests.patch(f"{BASE_URL}/api/admin/tasks/nonexistent-id/active",
                           json={"active": False}, headers=AH(admin_token), timeout=15)
        assert r.status_code == 404


class TestCompletionsCounter:
    def test_completions_count_increments(self, admin_token, user_token):
        tid = _create_visit(admin_token, "counter")

        # Admin sees 0 initially
        a = requests.get(f"{BASE_URL}/api/admin/tasks", headers=AH(admin_token), timeout=20).json()["tasks"]
        adm_task = next(t for t in a if t["id"] == tid)
        assert adm_task.get("completions_count") == 0

        # User sees 0
        u = requests.get(f"{BASE_URL}/api/tasks", headers=AH(user_token), timeout=20).json()["tasks"]
        usr_task = next(t for t in u if t["id"] == tid)
        assert usr_task.get("completions_count") == 0

        # User completes
        v = requests.post(f"{BASE_URL}/api/tasks/{tid}/verify", headers=AH(user_token), timeout=20)
        assert v.status_code == 200

        # Admin sees 1
        a2 = requests.get(f"{BASE_URL}/api/admin/tasks", headers=AH(admin_token), timeout=20).json()["tasks"]
        adm_task2 = next(t for t in a2 if t["id"] == tid)
        assert adm_task2.get("completions_count") == 1

        # User endpoint sees 1
        u2 = requests.get(f"{BASE_URL}/api/tasks", headers=AH(user_token), timeout=20).json()["tasks"]
        usr_task2 = next(t for t in u2 if t["id"] == tid)
        assert usr_task2.get("completions_count") == 1
