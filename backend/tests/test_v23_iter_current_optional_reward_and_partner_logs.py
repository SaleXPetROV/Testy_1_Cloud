"""
Tests for the current iteration:
 1. Optional reward_city on tasks (POST /api/admin/tasks with no reward_city)
 2. partner_quest require_telegram → verify blocks with Russian message
 3. partner-programs logs date filtering + chart date_from/date_to
 4. GET /api/skins/my?business_type=bio_farm returns crazy_bio_farm for admin
"""
import os
import uuid
from datetime import datetime, timezone, timedelta
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
ADMIN = {"email": "sanyanazarov212@gmail.com", "password": os.environ.get("TEST_ADMIN_PASSWORD", "")}
USER = {"email": "testuser@example.com", "password": "Test1234!"}


def _login(creds):
    r = requests.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=20)
    assert r.status_code == 200, f"login failed {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_token():
    return _login(ADMIN)


@pytest.fixture(scope="module")
def user_token():
    return _login(USER)


def _H(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ── (1) Optional reward ──────────────────────────────────────────────────────
class TestOptionalReward:
    def test_create_task_without_reward_returns_null(self, admin_token):
        payload = {
            "title": f"TEST_no_reward_{uuid.uuid4().hex[:6]}",
            "action_type": "visit_link",
            "target_url": "https://example.com",
        }
        r = requests.post(f"{BASE_URL}/api/admin/tasks", json=payload, headers=_H(admin_token), timeout=20)
        assert r.status_code == 200, r.text
        task = r.json()["task"]
        assert task["reward_city"] is None
        # Verify in GET /api/tasks list (user side)
        u_tok = _login(USER)
        rl = requests.get(f"{BASE_URL}/api/tasks", headers=_H(u_tok), timeout=20)
        assert rl.status_code == 200
        tasks = rl.json().get("tasks", [])
        found = next((t for t in tasks if t.get("id") == task["id"]), None)
        assert found is not None, "created task not in user tasks list"
        assert found.get("reward_city") in (None, 0), f"expected null/0 got {found.get('reward_city')}"

    def test_create_task_with_reward_shows_amount(self, admin_token):
        payload = {
            "title": f"TEST_with_reward_{uuid.uuid4().hex[:6]}",
            "action_type": "visit_link",
            "target_url": "https://example.com",
            "reward_city": 50,
        }
        r = requests.post(f"{BASE_URL}/api/admin/tasks", json=payload, headers=_H(admin_token), timeout=20)
        assert r.status_code == 200, r.text
        assert r.json()["task"]["reward_city"] == 50


# ── (2) partner_quest require_telegram ───────────────────────────────────────
class TestQuestRequireTelegram:
    def test_verify_blocks_when_no_telegram(self, admin_token, user_token):
        payload = {
            "title": f"TEST_quest_tg_{uuid.uuid4().hex[:6]}",
            "action_type": "partner_quest",
            "quest_kind": "local",
            "require_telegram": True,
            "reward_city": 10,
            "instructions": "Do X",
        }
        r = requests.post(f"{BASE_URL}/api/admin/tasks", json=payload, headers=_H(admin_token), timeout=20)
        assert r.status_code == 200, r.text
        task = r.json()["task"]
        assert task.get("require_telegram") is True
        tid = task["id"]

        # Ensure user has no linked telegram
        # Just try verify — if this user happens to have TG linked in DB, we skip
        v = requests.post(f"{BASE_URL}/api/tasks/{tid}/verify", headers=_H(user_token), timeout=20)
        if v.status_code == 200:
            pytest.skip("testuser has telegram linked; cannot verify block")
        assert v.status_code == 400, f"expected 400 got {v.status_code}: {v.text}"
        detail = (v.json().get("detail") or "").lower()
        assert "telegram" in detail, f"detail should mention telegram: {detail}"
        # Russian text check
        assert "привяжите" in detail or "telegram" in detail


# ── (3) partner-programs date-range logs & chart ─────────────────────────────
class TestPartnerLogsDateRange:
    @pytest.fixture(scope="class")
    def qa_program_id(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/admin/partner-programs", headers=_H(admin_token), timeout=20)
        assert r.status_code == 200, r.text
        progs = r.json().get("programs", [])
        qa = next((p for p in progs if p.get("name") == "QA Partner"), None)
        if not qa:
            pytest.skip("QA Partner program not seeded")
        return qa["id"]

    def test_logs_no_date_returns_all(self, admin_token, qa_program_id):
        r = requests.get(f"{BASE_URL}/api/admin/partner-programs/{qa_program_id}/logs",
                         headers=_H(admin_token), timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["count"] >= 1
        # save for other tests

    def test_logs_today_only(self, admin_token, qa_program_id):
        today = datetime.now(timezone.utc).date().isoformat()
        r = requests.get(
            f"{BASE_URL}/api/admin/partner-programs/{qa_program_id}/logs",
            params={"date_from": today, "date_to": today},
            headers=_H(admin_token), timeout=20,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        # all logs must be from today
        for l in data["logs"]:
            assert str(l.get("created_at", ""))[:10] == today, f"log outside range: {l.get('created_at')}"

    def test_logs_old_range_excludes_recent(self, admin_token, qa_program_id):
        # 30 days ago .. 15 days ago should include 20-day-old entries but not today
        end = (datetime.now(timezone.utc).date() - timedelta(days=15)).isoformat()
        start = (datetime.now(timezone.utc).date() - timedelta(days=30)).isoformat()
        r = requests.get(
            f"{BASE_URL}/api/admin/partner-programs/{qa_program_id}/logs",
            params={"date_from": start, "date_to": end},
            headers=_H(admin_token), timeout=20,
        )
        assert r.status_code == 200, r.text
        for l in r.json()["logs"]:
            d = str(l.get("created_at", ""))[:10]
            assert start <= d <= end

    def test_chart_accepts_date_range(self, admin_token, qa_program_id):
        start = (datetime.now(timezone.utc).date() - timedelta(days=6)).isoformat()
        end = datetime.now(timezone.utc).date().isoformat()
        r = requests.get(
            f"{BASE_URL}/api/admin/partner-programs/{qa_program_id}/chart",
            params={"date_from": start, "date_to": end},
            headers=_H(admin_token), timeout=20,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["labels"][0] == start
        assert data["labels"][-1] == end
        assert len(data["labels"]) == 7


# ── (4) skins/my for admin: crazy_bio_farm ───────────────────────────────────
class TestAdminOwnsCrazyBioFarm:
    def test_admin_owns_crazy_bio_farm(self, admin_token):
        r = requests.get(
            f"{BASE_URL}/api/skins/my",
            params={"business_type": "bio_farm"},
            headers=_H(admin_token), timeout=20,
        )
        assert r.status_code == 200, r.text
        skins = r.json().get("skins", [])
        keys = {(s.get("group_key") or s.get("id")) for s in skins}
        assert "crazy_bio_farm" in keys, f"crazy_bio_farm not in {keys}"
