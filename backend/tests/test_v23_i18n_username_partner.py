"""
Iteration 1 backend tests for GRAM City v2.3:
- Task auto-translation via LibreTranslate at read time (GET /api/tasks)
- Partner-quest verify flow (LOCAL success, PARTNER threshold fail with revert)
- Partner-quest progress (X of 5)
- Username enrichment across chat / market / land / map
"""

import os
import time
import uuid
import requests
import pytest

def _read_frontend_url():
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    return line.split("=", 1)[1].strip()
    except Exception:
        return None
    return None

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or _read_frontend_url()).rstrip("/")
API = f"{BASE_URL}/api"

USER_EMAIL = "testuser@example.com"
USER_PASS = "Test1234!"
ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASS = os.environ.get("TEST_ADMIN_PASSWORD", "")


def _login(session: requests.Session, email: str, password: str) -> str:
    r = session.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed {r.status_code}: {r.text[:400]}"
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok, f"no token: {r.json()}"
    return tok


@pytest.fixture(scope="module")
def user_client():
    s = requests.Session()
    tok = _login(s, USER_EMAIL, USER_PASS)
    s.headers.update({"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def admin_client():
    s = requests.Session()
    tok = _login(s, ADMIN_EMAIL, ADMIN_PASS)
    s.headers.update({"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    return s


# ------------- health / auth -------------
class TestHealth:
    def test_login_user(self):
        s = requests.Session()
        _login(s, USER_EMAIL, USER_PASS)

    def test_login_admin(self):
        s = requests.Session()
        _login(s, ADMIN_EMAIL, ADMIN_PASS)


# ------------- Task translation -------------
class TestTaskTranslation:
    def _set_lang(self, client, lang):
        r = client.put(f"{API}/auth/update-language", json={"language": lang})
        assert r.status_code == 200, f"update-language {lang} => {r.status_code}: {r.text[:300]}"

    def _get_tasks(self, client):
        r = client.get(f"{API}/tasks")
        assert r.status_code == 200, f"GET /api/tasks -> {r.status_code}: {r.text[:400]}"
        data = r.json()
        # Support either list or {tasks: [...]} shape
        if isinstance(data, dict):
            return data.get("tasks") or data.get("items") or []
        return data

    def test_language_en_translates_tasks(self, user_client):
        self._set_lang(user_client, "en")
        time.sleep(1.0)
        tasks = self._get_tasks(user_client)
        assert len(tasks) > 0
        # Backend populates title_i18n / instructions_i18n for the user's language
        for t in tasks:
            ti = t.get("title_i18n") or {}
            ii = t.get("instructions_i18n") or {}
            print("EN i18n for", t.get("id"), "title_en=", ti.get("en"), "instr_en=", (ii.get("en") or "")[:60])
            assert ti.get("en"), f"title_i18n.en missing for {t.get('title')}"
            assert ii.get("en"), f"instructions_i18n.en missing for {t.get('title')}"
        # Confirm one of them looks English
        joined = " ".join((t.get("title_i18n") or {}).get("en", "").lower() for t in tasks)
        assert any(w in joined for w in ("visit", "website", "partner", "subscribe", "channel", "trade", "task")), f"english translation looks off: {joined}"

    def test_language_es_translates_tasks(self, user_client):
        self._set_lang(user_client, "es")
        time.sleep(2.0)
        tasks = self._get_tasks(user_client)
        # At least one task should have es entry after switching language
        any_es = any((t.get("title_i18n") or {}).get("es") for t in tasks)
        print("ES samples:", [(t.get("id"), (t.get("title_i18n") or {}).get("es")) for t in tasks])
        assert any_es, f"no ES translations populated: {[t.get('title_i18n') for t in tasks]}"


# ------------- Partner-quest verify flow -------------
class TestPartnerQuestFlow:
    def _get_tasks(self, client):
        r = client.get(f"{API}/tasks")
        assert r.status_code == 200
        data = r.json()
        if isinstance(data, dict):
            return data.get("tasks") or data.get("items") or []
        return data

    def _find(self, tasks, predicate):
        for t in tasks:
            if predicate(t):
                return t
        return None

    def test_local_partner_quest_verify_success(self, user_client):
        user_client.put(f"{API}/auth/update-language", json={"language": "ru"})
        tasks = self._get_tasks(user_client)
        task = self._find(
            tasks,
            lambda t: t.get("action_type") == "partner_quest" and t.get("quest_kind") == "local",
        )
        assert task, f"LOCAL partner quest not found in seed: {[(t.get('action_type'),t.get('quest_kind')) for t in tasks]}"
        tid = task["id"]
        if task.get("status") in ("done", "completed"):
            pytest.skip("LOCAL partner quest already completed")
        r = user_client.post(f"{API}/tasks/{tid}/verify", json={})
        print("LOCAL verify:", r.status_code, r.text[:400])
        assert r.status_code in (200, 201), f"expected verify success, got {r.status_code}: {r.text[:300]}"
        body = r.json()
        # accept various response shapes
        assert body.get("ok") is True or body.get("status") in ("done", "completed") or body.get("completed") is True or body.get("success") is True, f"unexpected body: {body}"

        # Re-verify
        r2 = user_client.post(f"{API}/tasks/{tid}/verify", json={})
        print("LOCAL re-verify:", r2.status_code, r2.text[:300])
        assert r2.status_code in (200, 400, 409)

    def test_partner_quest_threshold_fail_and_progress(self, user_client):
        user_client.put(f"{API}/auth/update-language", json={"language": "ru"})
        tasks = self._get_tasks(user_client)
        task = self._find(
            tasks,
            lambda t: t.get("action_type") == "partner_quest" and t.get("quest_kind") == "partner",
        )
        assert task, f"threshold partner quest not found. types={[(t.get('action_type'),t.get('quest_kind')) for t in tasks]}"
        tid = task["id"]

        need = task.get("partner_need") or task.get("partner_check_min")
        have = task.get("partner_have")
        ready = task.get("partner_progress_ready")
        print("Threshold progress: have=%r need=%r ready=%r metric=%r" % (have, need, ready, task.get("partner_metric")))
        assert need is not None and str(need) != "", f"partner_need missing: {task}"
        assert have is not None and str(have) != "", f"partner_have missing (stuck 'updating'?): {task}"
        assert ready is True, f"partner_progress_ready should be True (not stuck 'Обновляется…'): {task}"

        r = user_client.post(f"{API}/tasks/{tid}/verify", json={})
        print("PARTNER threshold verify:", r.status_code, r.text[:400])
        if r.status_code == 200:
            body = r.json()
            assert body.get("ok") is False or body.get("success") is False or body.get("status") not in ("done", "completed"), f"threshold task wrongly succeeded: {body}"
        else:
            assert r.status_code in (400, 409, 422)


# ------------- Username enrichment -------------
class TestUsernameEnrichment:
    def test_change_username_and_verify_me(self, user_client):
        new_name = f"testuser_{uuid.uuid4().hex[:6]}"
        r = user_client.put(f"{API}/auth/update-username", json={"username": new_name})
        print("update-username:", r.status_code, r.text[:250])
        assert r.status_code == 200, r.text[:300]
        # verify /me returns the new username
        me = user_client.get(f"{API}/auth/me")
        assert me.status_code == 200
        got = me.json().get("username") or me.json().get("user", {}).get("username")
        assert got == new_name, f"me username mismatch: {got} vs {new_name}"
        # store for other tests
        pytest._new_username = new_name

    def test_chat_send_shows_new_username(self, user_client):
        new_name = getattr(pytest, "_new_username", None)
        assert new_name, "prior test didn't set username"
        payload = {"content": f"hello from {new_name} {uuid.uuid4().hex[:4]}", "chat_type": "global"}
        r = user_client.post(f"{API}/chat/send", json=payload)
        print("chat send:", r.status_code, r.text[:300])
        assert r.status_code in (200, 201), r.text[:300]
        rg = user_client.get(f"{API}/chat/messages/global", params={"limit": 20})
        assert rg.status_code == 200, rg.text[:300]
        data = rg.json()
        msgs = data if isinstance(data, list) else (data.get("messages") or data.get("items") or [])
        assert msgs, "no chat messages returned"
        found = any((m.get("sender_username") == new_name) or (m.get("username") == new_name) for m in msgs)
        assert found, f"new username not found in chat messages. sample keys: {list(msgs[0].keys())[:15]} first: {msgs[0]}"

    def test_market_listings_seller_username(self, user_client):
        new_name = getattr(pytest, "_new_username", None)
        # Just verify listing objects have seller_username string (enrichment applies at read time)
        r = user_client.get(f"{API}/market/listings")
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        items = data if isinstance(data, list) else (data.get("items") or data.get("listings") or [])
        # not asserting any of them belong to test user; only that seller_username exists when there are items
        for it in items[:10]:
            assert "seller_username" in it or "seller" in it, f"missing seller_username in listing: {list(it.keys())[:10]}"
        r2 = user_client.get(f"{API}/market/land/listings")
        assert r2.status_code == 200, r2.text[:300]

    def test_map_owner_username(self, user_client):
        # Best-effort: try island endpoint
        r = user_client.get(f"{API}/ton-island")
        if r.status_code == 404:
            r = user_client.get(f"{API}/ton-island/state")
        print("ton-island:", r.status_code)
        if r.status_code != 200:
            pytest.skip(f"island endpoint not available: {r.status_code}")
        data = r.json()
        # Just ensure cells expose owner_username field when owner exists
        cells = data.get("cells") or data.get("map") or []
        if not cells:
            pytest.skip("no cells returned")
        owned = [c for c in cells if c.get("owner_id") or c.get("owner")]
        if not owned:
            pytest.skip("no owned cells in map to verify")
        for c in owned[:5]:
            assert "owner_username" in c, f"owner_username missing in owned cell: {list(c.keys())}"
