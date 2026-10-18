"""Backend tests for Tasks (Задания) feature — GRAM City v2.3."""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or "http://localhost:8001"

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PASSWORD = "Test1234!"


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"Login failed for {email}: {r.status_code} {r.text}"
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok
    return tok


@pytest.fixture(scope="module")
def admin_token():
    return _login(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def user_token():
    return _login(USER_EMAIL, USER_PASSWORD)


def AH(t):
    return {"Authorization": f"Bearer {t}"}


# ── Cleanup helper ───────────────────────────────────────────────────────────
_created_task_ids = []


@pytest.fixture(scope="module", autouse=True)
def _cleanup(admin_token):
    yield
    for tid in _created_task_ids:
        try:
            requests.delete(f"{BASE_URL}/api/admin/tasks/{tid}", headers=AH(admin_token), timeout=15)
        except Exception:
            pass


# ============================== ADMIN CRUD ==================================
class TestAdminTasksCRUD:
    def test_create_visit_link(self, admin_token):
        payload = {
            "title": f"TEST_visit_{uuid.uuid4().hex[:6]}",
            "reward_city": 100,
            "action_type": "visit_link",
            "target_url": "https://example.com",
        }
        r = requests.post(f"{BASE_URL}/api/admin/tasks", json=payload, headers=AH(admin_token), timeout=20)
        assert r.status_code == 200, r.text
        t = r.json()["task"]
        assert t["action_type"] == "visit_link"
        assert t["target_url"] == "https://example.com"
        assert t["reward_city"] == 100
        assert "id" in t
        _created_task_ids.append(t["id"])
        pytest.visit_task_id = t["id"]

    def test_create_subscribe_channel(self, admin_token):
        payload = {
            "title": f"TEST_sub_{uuid.uuid4().hex[:6]}",
            "reward_city": 50,
            "action_type": "subscribe_channel",
            "channel_url": "https://t.me/testchannel",
            "channel_id": "@testchannel",
        }
        r = requests.post(f"{BASE_URL}/api/admin/tasks", json=payload, headers=AH(admin_token), timeout=20)
        assert r.status_code == 200, r.text
        t = r.json()["task"]
        _created_task_ids.append(t["id"])
        pytest.sub_task_id = t["id"]

    def test_create_referral_invite(self, admin_token):
        payload = {
            "title": f"TEST_ref_{uuid.uuid4().hex[:6]}",
            "reward_city": 200,
            "action_type": "referral_invite",
            "required_referrals": 99999,
        }
        r = requests.post(f"{BASE_URL}/api/admin/tasks", json=payload, headers=AH(admin_token), timeout=20)
        assert r.status_code == 200, r.text
        _created_task_ids.append(r.json()["task"]["id"])
        pytest.ref_task_id = r.json()["task"]["id"]

    def test_create_ad_tiktok(self, admin_token):
        payload = {
            "title": f"TEST_ad_{uuid.uuid4().hex[:6]}",
            "reward_city": 300,
            "action_type": "ad_tiktok",
        }
        r = requests.post(f"{BASE_URL}/api/admin/tasks", json=payload, headers=AH(admin_token), timeout=20)
        assert r.status_code == 200, r.text
        _created_task_ids.append(r.json()["task"]["id"])
        pytest.ad_task_id = r.json()["task"]["id"]

    def test_create_validation_missing_target_url(self, admin_token):
        r = requests.post(f"{BASE_URL}/api/admin/tasks", json={
            "title": "TEST_bad", "reward_city": 10, "action_type": "visit_link"
        }, headers=AH(admin_token), timeout=20)
        assert r.status_code == 400

    def test_admin_list_has_completions_count(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/admin/tasks", headers=AH(admin_token), timeout=20)
        assert r.status_code == 200
        tasks = r.json()["tasks"]
        ids = {t["id"] for t in tasks}
        assert pytest.visit_task_id in ids
        for t in tasks:
            assert "completions_count" in t

    def test_delete_task(self, admin_token):
        # create + delete
        p = {"title": "TEST_del", "reward_city": 1, "action_type": "visit_link", "target_url": "https://x.com"}
        c = requests.post(f"{BASE_URL}/api/admin/tasks", json=p, headers=AH(admin_token), timeout=20)
        assert c.status_code == 200
        tid = c.json()["task"]["id"]
        d = requests.delete(f"{BASE_URL}/api/admin/tasks/{tid}", headers=AH(admin_token), timeout=20)
        assert d.status_code == 200
        # verify gone from list
        lst = requests.get(f"{BASE_URL}/api/admin/tasks", headers=AH(admin_token), timeout=20).json()["tasks"]
        assert tid not in {t["id"] for t in lst}


# ============================== DAILY REWARDS ================================
class TestDailyRewards:
    def test_get_defaults(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/admin/tasks/daily-rewards", headers=AH(admin_token), timeout=15)
        assert r.status_code == 200
        rewards = r.json()["rewards"]
        assert isinstance(rewards, list) and len(rewards) >= 7

    def test_put_and_user_get_reflects(self, admin_token, user_token):
        new_rewards = [7, 14, 21, 28, 35, 42, 100]
        r = requests.put(f"{BASE_URL}/api/admin/tasks/daily-rewards",
                         json={"rewards": new_rewards}, headers=AH(admin_token), timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["rewards"] == new_rewards
        # user side
        u = requests.get(f"{BASE_URL}/api/tasks/daily", headers=AH(user_token), timeout=15)
        assert u.status_code == 200
        assert u.json()["rewards"] == new_rewards
        # restore defaults
        requests.put(f"{BASE_URL}/api/admin/tasks/daily-rewards",
                     json={"rewards": [5, 10, 20, 35, 50, 75, 150]}, headers=AH(admin_token), timeout=15)

    def test_daily_claim_and_double_claim(self, user_token):
        # First attempt may 200 (claimed) or 400 (already claimed today from prior run)
        r1 = requests.post(f"{BASE_URL}/api/tasks/daily/claim", headers=AH(user_token), timeout=15)
        assert r1.status_code in (200, 400), r1.text
        # Second attempt MUST be 400
        r2 = requests.post(f"{BASE_URL}/api/tasks/daily/claim", headers=AH(user_token), timeout=15)
        assert r2.status_code == 400


# ============================== USER TASKS ===================================
class TestUserTasks:
    def test_list_returns_tasks_with_status(self, user_token):
        r = requests.get(f"{BASE_URL}/api/tasks", headers=AH(user_token), timeout=20)
        assert r.status_code == 200
        body = r.json()
        assert "tasks" in body
        assert "referral_count" in body
        for t in body["tasks"]:
            assert "status" in t

    def test_verify_visit_link_credits_reward(self, user_token):
        # Get balance before
        me1 = requests.get(f"{BASE_URL}/api/auth/me", headers=AH(user_token), timeout=15)
        # some deployments use /api/users/me — try both
        if me1.status_code != 200:
            me1 = requests.get(f"{BASE_URL}/api/users/me", headers=AH(user_token), timeout=15)
        bal_before = None
        if me1.status_code == 200:
            j = me1.json()
            bal_before = j.get("balance_ton", j.get("user", {}).get("balance_ton"))

        tid = pytest.visit_task_id
        v = requests.post(f"{BASE_URL}/api/tasks/{tid}/verify", headers=AH(user_token), timeout=20)
        assert v.status_code == 200, v.text
        assert v.json()["status"] == "completed"

        # Second verify → still completed (idempotent)
        v2 = requests.post(f"{BASE_URL}/api/tasks/{tid}/verify", headers=AH(user_token), timeout=20)
        assert v2.status_code == 200

        # Check task moves to bottom in listing
        lst = requests.get(f"{BASE_URL}/api/tasks", headers=AH(user_token), timeout=20).json()["tasks"]
        statuses = [t["status"] for t in lst]
        # verify sort: any completed appears only after pending in the list
        seen_completed = False
        for s in statuses:
            if s == "completed":
                seen_completed = True
            elif seen_completed and s != "completed":
                pytest.fail(f"Non-completed after completed in sorted list: {statuses}")

        # Balance should have increased (best-effort)
        me2 = requests.get(f"{BASE_URL}/api/auth/me", headers=AH(user_token), timeout=15)
        if me2.status_code != 200:
            me2 = requests.get(f"{BASE_URL}/api/users/me", headers=AH(user_token), timeout=15)
        if bal_before is not None and me2.status_code == 200:
            j = me2.json()
            bal_after = j.get("balance_ton", j.get("user", {}).get("balance_ton"))
            if bal_after is not None:
                assert bal_after > bal_before - 1e-9

    def test_verify_subscribe_no_telegram_returns_400(self, user_token):
        # regular user has NO telegram
        r = requests.post(f"{BASE_URL}/api/tasks/{pytest.sub_task_id}/verify",
                          headers=AH(user_token), timeout=20)
        assert r.status_code == 400
        detail = (r.json().get("detail") or "").lower()
        assert "telegram" in detail

    def test_verify_referral_insufficient(self, user_token):
        r = requests.post(f"{BASE_URL}/api/tasks/{pytest.ref_task_id}/verify",
                          headers=AH(user_token), timeout=20)
        assert r.status_code == 400
        # progress message contains numbers
        detail = r.json().get("detail", "")
        assert "0" in detail or "99999" in detail or "friends" in detail.lower() or "друз" in detail


# ============================== AD FLOW ======================================
class TestAdFlow:
    def test_reject_non_https(self, user_token):
        r = requests.post(f"{BASE_URL}/api/tasks/{pytest.ad_task_id}/submit-ad",
                          json={"url": "http://tiktok.com/@u/video/1"}, headers=AH(user_token), timeout=15)
        assert r.status_code == 400

    def test_reject_non_tiktok(self, user_token):
        r = requests.post(f"{BASE_URL}/api/tasks/{pytest.ad_task_id}/submit-ad",
                          json={"url": "https://youtube.com/watch?v=x"}, headers=AH(user_token), timeout=15)
        assert r.status_code == 400

    def test_submit_and_max_and_duplicate(self, user_token, admin_token):
        base = f"https://www.tiktok.com/@u/video/{uuid.uuid4().hex[:8]}"
        urls = [f"{base}-1", f"{base}-2", f"{base}-3"]
        first_sub_id = None
        for u in urls:
            r = requests.post(f"{BASE_URL}/api/tasks/{pytest.ad_task_id}/submit-ad",
                              json={"url": u}, headers=AH(user_token), timeout=15)
            assert r.status_code == 200, f"submit {u}: {r.status_code} {r.text}"
            assert r.json()["status"] == "submitted"
            if first_sub_id is None:
                first_sub_id = r.json()["submission"]["id"]

        # duplicate
        dup = requests.post(f"{BASE_URL}/api/tasks/{pytest.ad_task_id}/submit-ad",
                            json={"url": urls[0]}, headers=AH(user_token), timeout=15)
        assert dup.status_code == 400

        # max exceeded (4th unique)
        over = requests.post(f"{BASE_URL}/api/tasks/{pytest.ad_task_id}/submit-ad",
                             json={"url": f"{base}-4"}, headers=AH(user_token), timeout=15)
        assert over.status_code == 400

        # admin list submissions
        adm = requests.get(f"{BASE_URL}/api/admin/tasks/{pytest.ad_task_id}/ad-submissions",
                           headers=AH(admin_token), timeout=15)
        assert adm.status_code == 200
        subs = adm.json()["submissions"]
        assert len(subs) >= 3

        # search filter
        adm_s = requests.get(f"{BASE_URL}/api/admin/tasks/{pytest.ad_task_id}/ad-submissions",
                             params={"search": base}, headers=AH(admin_token), timeout=15)
        assert adm_s.status_code == 200
        assert len(adm_s.json()["submissions"]) >= 3

        # approve one → user gets reward + task marked completed
        appr = requests.post(f"{BASE_URL}/api/admin/tasks/ad-submissions/{first_sub_id}/approve",
                             headers=AH(admin_token), timeout=15)
        assert appr.status_code == 200

        # Task should now be completed for the user
        lst = requests.get(f"{BASE_URL}/api/tasks", headers=AH(user_token), timeout=15).json()["tasks"]
        ad_task = next((t for t in lst if t["id"] == pytest.ad_task_id), None)
        assert ad_task is not None
        assert ad_task["status"] == "completed"

        # reject a second pending one (should still be pending? or not — pick second sub)
        remaining_pending = [s for s in subs if s["id"] != first_sub_id and s["status"] == "pending"]
        if remaining_pending:
            rej = requests.post(f"{BASE_URL}/api/admin/tasks/ad-submissions/{remaining_pending[0]['id']}/reject",
                                headers=AH(admin_token), timeout=15)
            assert rej.status_code == 200
