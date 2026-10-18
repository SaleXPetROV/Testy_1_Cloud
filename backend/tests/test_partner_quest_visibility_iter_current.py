"""
Backend tests for iteration:
1. Partner-quest visibility toggle (show_to_referrals)
2. Resource sale proceeds route to REAL balance_ton (code-level check + smoke)
"""
import os
import time
import uuid
import asyncio
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")

ADMIN = {"email": "admin@test.com", "password": "Admin@12345"}
USER = {"email": "user@test.com", "password": "User@12345"}

PTEST = "PTEST_ITER_CURRENT"


def _login(session, creds):
    r = session.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=20)
    assert r.status_code == 200, f"login failed {creds['email']}: {r.status_code} {r.text}"
    data = r.json()
    token = data.get("token") or data.get("access_token")
    assert token, f"no token in login response: {data}"
    return token


@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    tok = _login(s, ADMIN)
    s.headers.update({"Authorization": f"Bearer {tok}"})
    return s


@pytest.fixture(scope="module")
def user_session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    tok = _login(s, USER)
    s.headers.update({"Authorization": f"Bearer {tok}"})
    return s


@pytest.fixture(scope="module")
def mongo():
    from motor.motor_asyncio import AsyncIOMotorClient
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "test_database")
    client = AsyncIOMotorClient(mongo_url)
    return client[db_name]


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture(scope="module")
def created_task_ids(admin_session, mongo):
    """Create two partner_quest tasks and clean up after."""
    title_hidden = f"TEST_PQ_HIDDEN_{uuid.uuid4().hex[:6]}"
    title_shown = f"TEST_PQ_SHOWN_{uuid.uuid4().hex[:6]}"

    base = {
        "action_type": "partner_quest",
        "quest_kind": "partner",
        "partner_url": "https://partner.example.com/api/check",
        "partner_ref_id": PTEST,
        "partner_method": "GET",
        "reward_city": 100,
    }

    def _extract(resp_json):
        return resp_json.get("task") if isinstance(resp_json, dict) and "task" in resp_json else resp_json

    r1 = admin_session.post(f"{BASE_URL}/api/admin/tasks",
                            json={**base, "title": title_hidden, "show_to_referrals": False})
    assert r1.status_code in (200, 201), f"create hidden task: {r1.status_code} {r1.text}"
    j1 = _extract(r1.json())
    assert j1.get("show_to_referrals") is False, f"hidden task echoed: {j1}"
    id_hidden = j1.get("id")
    assert id_hidden

    r2 = admin_session.post(f"{BASE_URL}/api/admin/tasks",
                            json={**base, "title": title_shown, "show_to_referrals": True})
    assert r2.status_code in (200, 201), f"create shown task: {r2.status_code} {r2.text}"
    j2 = _extract(r2.json())
    assert j2.get("show_to_referrals") is True, f"shown task echoed: {j2}"
    id_shown = j2.get("id")

    yield {"hidden": id_hidden, "shown": id_shown,
           "title_hidden": title_hidden, "title_shown": title_shown}

    # cleanup
    _run(mongo.tasks.delete_many({"title": {"$in": [title_hidden, title_shown]}}))


# ---------- Tests ----------

class TestPartnerQuestVisibility:
    def test_created_tasks_persisted_with_flags(self, admin_session, created_task_ids):
        r = admin_session.get(f"{BASE_URL}/api/admin/tasks")
        assert r.status_code == 200
        raw = r.json()
        if isinstance(raw, dict):
            raw = raw.get("tasks") or raw.get("items") or []
        by_id = {t.get("id"): t for t in raw}
        h = by_id.get(created_task_ids["hidden"])
        s = by_id.get(created_task_ids["shown"])
        assert h and h.get("show_to_referrals") is False
        assert s and s.get("show_to_referrals") is True
        assert h.get("partner_ref_id") == PTEST
        assert s.get("partner_ref_id") == PTEST

    def test_user_as_partner_referral_hides_flagged_task(self, user_session, created_task_ids, mongo):
        # Bind user's partner_ref_id to PTEST
        _run(mongo.users.update_one({"email": USER["email"]},
                                    {"$set": {"partner_ref_id": PTEST}}))
        r = user_session.get(f"{BASE_URL}/api/tasks")
        assert r.status_code == 200, r.text
        tasks = r.json()
        # tasks may be a list or a dict; normalise
        if isinstance(tasks, dict):
            tasks = tasks.get("tasks") or tasks.get("items") or []
        ids = {t.get("id") for t in tasks}
        assert created_task_ids["hidden"] not in ids, "hidden partner task must NOT appear to partner referral"
        assert created_task_ids["shown"] in ids, "shown partner task MUST appear to partner referral"

    def test_user_without_partner_ref_sees_both(self, user_session, created_task_ids, mongo):
        # Unset partner_ref_id (and legacy ref fields to be safe)
        _run(mongo.users.update_one(
            {"email": USER["email"]},
            {"$unset": {"partner_ref_id": "", "referrer_id": "", "ref_by": "",
                        "invited_by": "", "referrerId": "", "start_param": ""}}
        ))
        r = user_session.get(f"{BASE_URL}/api/tasks")
        assert r.status_code == 200
        tasks = r.json()
        if isinstance(tasks, dict):
            tasks = tasks.get("tasks") or tasks.get("items") or []
        ids = {t.get("id") for t in tasks}
        assert created_task_ids["hidden"] in ids, "non-referral user should see the hidden-flag task"
        assert created_task_ids["shown"] in ids, "non-referral user should see shown-flag task"

    def test_response_does_not_leak_partner_fields(self, user_session, created_task_ids):
        r = user_session.get(f"{BASE_URL}/api/tasks")
        tasks = r.json()
        if isinstance(tasks, dict):
            tasks = tasks.get("tasks") or tasks.get("items") or []
        for t in tasks:
            if t.get("id") in (created_task_ids["hidden"], created_task_ids["shown"]):
                assert "partner_url" not in t
                assert "partner_method" not in t
                assert "partner_ref_id" not in t


class TestResourceSaleRouting:
    """Static code check that resource-sale proceeds go to balance_ton, not bonus_balance."""
    def test_market_buy_credits_balance_ton(self):
        with open("/app/backend/server.py", "r") as f:
            src = f.read()
        # market/buy handler
        i = src.index("@api_router.post(\"/market/buy\")")
        end = src.index("@api_router", i + 10)
        chunk = src[i:end]
        assert "Обновляем баланс продавца" in chunk
        assert "balance_ton" in chunk and "total_income" in chunk
        # Ensure no is_active_investor branch routing seller proceeds to bonus_balance
        # within this handler
        assert "is_active_investor" not in chunk, \
            "market/buy still references is_active_investor for seller crediting"

    def test_admin_buyout_credits_balance_ton(self):
        with open("/app/backend/server.py", "r") as f:
            src = f.read()
        i = src.index("Credit the seller (post-tax proceeds)")
        chunk = src[i:i + 800]
        assert "balance_ton" in chunk and "total_income" in chunk
        assert "bonus_balance" not in chunk
