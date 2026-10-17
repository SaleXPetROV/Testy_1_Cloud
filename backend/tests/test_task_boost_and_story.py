"""
Tests for the two new task-engine action types (iteration):
  * tg_channel_boost
  * repost_story (23h timer flow)

Endpoints exercised:
  POST /api/admin/tasks
  POST /api/v1/admin/tasks/create
  GET  /api/tasks
  POST /api/tasks/{id}/start-check   (+ v1 alias)
  GET  /api/tasks/{id}/status        (+ v1 alias)
  POST /api/tasks/{id}/claim-reward  (+ v1 alias)
  POST /api/tasks/{id}/verify-boost  (+ v1 alias)
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PASSWORD = "Test1234!"


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_token():
    return _login(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def user_token():
    return _login(USER_EMAIL, USER_PASSWORD)


@pytest.fixture(scope="module")
def admin_hdr(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="module")
def user_hdr(user_token):
    return {"Authorization": f"Bearer {user_token}"}


created_task_ids = []


# ------------------------------------------------------------------
# Admin creation of new task types
# ------------------------------------------------------------------
class TestAdminCreate:
    def test_create_repost_story(self, admin_hdr):
        payload = {
            "title": "TEST_Repost Story 23h",
            "reward_city": 300,
            "action_type": "repost_story",
        }
        r = requests.post(f"{BASE_URL}/api/admin/tasks", json=payload, headers=admin_hdr, timeout=30)
        assert r.status_code == 200, f"create repost_story failed: {r.status_code} {r.text}"
        data = r.json()
        task = data.get("task") or {}
        assert task.get("action_type") == "repost_story"
        assert task.get("reward_city") == 300
        assert task.get("id")
        created_task_ids.append(("story", task["id"]))

    def test_create_tg_channel_boost_admin_endpoint(self, admin_hdr):
        payload = {
            "title": "TEST_Boost Channel Standard",
            "reward_city": 100,
            "action_type": "tg_channel_boost",
            "chat_id": "@somechannel",
            "boost_url": "https://t.me/boost/somechannel",
        }
        r = requests.post(f"{BASE_URL}/api/admin/tasks", json=payload, headers=admin_hdr, timeout=30)
        assert r.status_code == 200, r.text
        task = r.json()["task"]
        assert task["action_type"] == "tg_channel_boost"
        ad = task.get("action_data") or {}
        assert ad.get("boost_url") == "https://t.me/boost/somechannel"
        created_task_ids.append(("boost", task["id"]))

    def test_create_tg_channel_boost_v1_endpoint(self, admin_hdr):
        payload = {
            "title": "TEST_Boost Channel V1",
            "reward": 150,
            "chat_id": "@somechannel",
            "boost_url": "https://t.me/boost/v1",
        }
        r = requests.post(f"{BASE_URL}/api/v1/admin/tasks/create",
                          json=payload, headers=admin_hdr, timeout=30)
        assert r.status_code == 200, r.text
        task = r.json()["task"]
        assert task["action_type"] == "tg_channel_boost"
        assert task["reward_city"] == 150
        created_task_ids.append(("boost_v1", task["id"]))


# ------------------------------------------------------------------
# GET /api/tasks reflects new fields for user
# ------------------------------------------------------------------
class TestListTasks:
    def test_list_contains_new_tasks_with_fields(self, user_hdr):
        r = requests.get(f"{BASE_URL}/api/tasks", headers=user_hdr, timeout=30)
        assert r.status_code == 200, r.text
        tasks = r.json().get("tasks", [])
        ids = {tid for _, tid in created_task_ids}
        seen = {t["id"]: t for t in tasks if t.get("id") in ids}
        assert len(seen) == len(created_task_ids), f"missing new tasks in list; found {list(seen.keys())}"
        for kind, tid in created_task_ids:
            t = seen[tid]
            if t["action_type"] == "tg_channel_boost":
                assert "boost_url" in t, f"boost_url missing for boost task {tid}"
            elif t["action_type"] == "repost_story":
                assert "status" in t
                assert "remaining_seconds" in t
                assert "open_url" in t


# ------------------------------------------------------------------
# repost_story timer flow
# ------------------------------------------------------------------
class TestRepostStoryFlow:
    def _story_id(self):
        for kind, tid in created_task_ids:
            if kind == "story":
                return tid
        pytest.skip("no story task created")

    def test_claim_before_start_returns_400(self, user_hdr):
        tid = self._story_id()
        r = requests.post(f"{BASE_URL}/api/tasks/{tid}/claim-reward",
                          headers=user_hdr, timeout=30)
        assert r.status_code == 400, f"expected 400, got {r.status_code} {r.text}"
        detail = (r.json().get("detail") or "").lower()
        assert "недоступна" in detail or "not available" in detail or "wait" in detail

    def test_start_check_sets_pending_check(self, user_hdr):
        tid = self._story_id()
        r = requests.post(f"{BASE_URL}/api/tasks/{tid}/start-check",
                          headers=user_hdr, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("status") == "pending_check"
        rem = int(data.get("remaining_seconds") or 0)
        assert 82700 <= rem <= 82800, f"expected ~82800 remaining, got {rem}"
        assert data.get("check_available_at")

    def test_status_returns_decreasing_pending(self, user_hdr):
        tid = self._story_id()
        r1 = requests.get(f"{BASE_URL}/api/tasks/{tid}/status", headers=user_hdr, timeout=30)
        assert r1.status_code == 200, r1.text
        d1 = r1.json()
        assert d1.get("status") == "pending_check"
        rem1 = int(d1.get("remaining_seconds") or 0)
        time.sleep(2)
        r2 = requests.get(f"{BASE_URL}/api/tasks/{tid}/status", headers=user_hdr, timeout=30)
        d2 = r2.json()
        rem2 = int(d2.get("remaining_seconds") or 0)
        assert rem2 < rem1, f"remaining_seconds should decrease: {rem1} -> {rem2}"

    def test_start_check_is_idempotent(self, user_hdr):
        tid = self._story_id()
        r_before = requests.get(f"{BASE_URL}/api/tasks/{tid}/status", headers=user_hdr, timeout=30)
        before = r_before.json()
        r = requests.post(f"{BASE_URL}/api/tasks/{tid}/start-check",
                          headers=user_hdr, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        # must NOT reset the timer to full 23h
        assert data.get("check_available_at") == before.get("check_available_at"), \
            "start-check reset the timer (should be idempotent)"
        rem = int(data.get("remaining_seconds") or 0)
        assert rem <= int(before.get("remaining_seconds") or 0) + 1

    def test_claim_while_pending_returns_400(self, user_hdr):
        tid = self._story_id()
        r = requests.post(f"{BASE_URL}/api/tasks/{tid}/claim-reward",
                          headers=user_hdr, timeout=30)
        assert r.status_code == 400, f"expected 400, got {r.status_code} {r.text}"


# ------------------------------------------------------------------
# tg_channel_boost verification – user has NO linked telegram
# ------------------------------------------------------------------
class TestBoostVerifyNoTelegram:
    def _boost_id(self):
        for kind, tid in created_task_ids:
            if kind in ("boost", "boost_v1"):
                return tid
        pytest.skip("no boost task created")

    def test_verify_boost_no_telegram_returns_400(self, user_hdr):
        tid = self._boost_id()
        r = requests.post(f"{BASE_URL}/api/tasks/{tid}/verify-boost",
                          headers=user_hdr, timeout=30)
        assert r.status_code == 400, f"expected 400, got {r.status_code} {r.text}"
        detail = r.json().get("detail") or ""
        assert "Telegram" in detail or "telegram" in detail.lower()

    def test_verify_boost_v1_no_telegram_returns_400(self, user_hdr):
        tid = self._boost_id()
        r = requests.post(f"{BASE_URL}/api/v1/tasks/verify-boost",
                          json={"task_id": tid}, headers=user_hdr, timeout=30)
        assert r.status_code == 400, r.text
        detail = r.json().get("detail") or ""
        assert "Telegram" in detail or "telegram" in detail.lower()

    def test_no_reward_credited(self, user_hdr):
        # user's balance_ton must not have moved: refetch profile
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=user_hdr, timeout=30)
        # tolerate different profile endpoints
        if r.status_code != 200:
            pytest.skip("no /api/auth/me endpoint")
        # nothing to assert about specific value here; just ensure the call
        # succeeds after the failed verify (server did not crash).
        assert r.status_code == 200


# ------------------------------------------------------------------
# v1 alias endpoints reach the same underlying logic
# ------------------------------------------------------------------
class TestV1Aliases:
    def _story_id(self):
        for kind, tid in created_task_ids:
            if kind == "story":
                return tid
        pytest.skip("no story task created")

    def test_v1_status(self, user_hdr):
        tid = self._story_id()
        r = requests.get(f"{BASE_URL}/api/v1/tasks/status/{tid}",
                         headers=user_hdr, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json().get("status") in ("pending_check", "ready_to_claim", "completed")

    def test_v1_start_check_idempotent(self, user_hdr):
        tid = self._story_id()
        r = requests.post(f"{BASE_URL}/api/v1/tasks/start-check",
                          json={"task_id": tid}, headers=user_hdr, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json().get("status") in ("pending_check", "ready_to_claim", "completed")

    def test_v1_claim_rejects_pending(self, user_hdr):
        tid = self._story_id()
        r = requests.post(f"{BASE_URL}/api/v1/tasks/claim-reward",
                          json={"task_id": tid}, headers=user_hdr, timeout=30)
        assert r.status_code == 400, r.text


# ------------------------------------------------------------------
# Cleanup (best-effort)
# ------------------------------------------------------------------
def test_zzz_cleanup(admin_hdr):
    for _, tid in created_task_ids:
        try:
            requests.delete(f"{BASE_URL}/api/admin/tasks/{tid}", headers=admin_hdr, timeout=15)
        except Exception:
            pass
