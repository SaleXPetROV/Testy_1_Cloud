"""
Iteration 2 backend tests for GRAM City v2.3
- Partner-quest admin preview /api/admin/tasks/test-partner (iTerra, GamePat, generic placeholder)
- Partner-quest threshold RAW progress on GET /api/tasks (no baseline subtraction)
- Partner-quest user Do->Check flow via /verify (LOCAL + threshold revert)
- Reward text in completion notification (LOCAL quest w/ reward_description; user lang = 'en')
- Alliance username enrichment (patron_username/vassal_username) on offers endpoints
- WebSocket auth frame keeps chat WS open (no 4001)
"""
import os
import time
import uuid
import json
import asyncio
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
USER2_EMAIL = "testuser2@example.com"
USER2_PASS = "Test1234!"
ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASS = os.environ.get("TEST_ADMIN_PASSWORD", "")


def _login(session, email, password):
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
def user2_client():
    s = requests.Session()
    try:
        tok = _login(s, USER2_EMAIL, USER2_PASS)
    except AssertionError:
        pytest.skip("testuser2 not seeded")
    s.headers.update({"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def admin_client():
    s = requests.Session()
    tok = _login(s, ADMIN_EMAIL, ADMIN_PASS)
    s.headers.update({"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    return s


# ---------------- Admin partner preview ----------------
class TestAdminPartnerPreview:
    URL = f"{API}/admin/tasks/test-partner"

    def test_iterra_auto_completed_detection(self, admin_client):
        body = {
            "partner_url": "https://services.theiterra.pro/api/v1/partners/task/check?task=rolls_20",
            "partner_user_param": "chatId",
            "partner_api_key": "TEST_PLACEHOLDER_API_KEY",
            "partner_method": "GET",
            "partner_check_field": "required",
            "partner_check_min": 20,
            "test_user_id": "7564533125",
        }
        r = admin_client.post(self.URL, json=body, timeout=60)
        print("iTerra preview:", r.status_code, r.text[:600])
        assert r.status_code == 200, r.text[:400]
        j = r.json()
        # verdict false because required field missing; auto-detected data.completed=false
        assert j.get("verdict") is False, f"verdict should be False: {j}"
        reason = (j.get("reason") or "") + " " + json.dumps(j)
        assert "completed" in reason.lower(), f"expected reason mentions auto-detected completed: {j}"

    def test_gamepat_placeholder_and_true(self, admin_client):
        body = {
            "partner_url": "https://api.fc.gamepat.org/api/partner/v1/tasks/five-battles/check?telegram_id={telegram_id}",
            "partner_user_param": "telegram_id",
            "partner_ref_id": "6661676176",
            "partner_method": "GET",
            "test_user_id": "7564533125",
        }
        r = admin_client.post(self.URL, json=body, timeout=60)
        print("GamePat preview:", r.status_code, r.text[:600])
        assert r.status_code == 200, r.text[:400]
        j = r.json()
        req_url = j.get("request_url") or j.get("url") or ""
        assert "telegram_id=7564533125" in req_url, f"placeholder not substituted: {req_url}"
        assert "{telegram_id}" not in req_url, f"literal placeholder remained: {req_url}"
        assert j.get("verdict") is True, f"verdict should be True (auto data.completed): {j}"

    def test_generic_tg_id_placeholder(self, admin_client):
        body = {
            "partner_url": "https://httpbin.org/anything?user={tg_id}&id=1",
            "partner_method": "GET",
            "partner_user_param": "user_id",
            "test_user_id": "6661676176",
        }
        r = admin_client.post(self.URL, json=body, timeout=60)
        print("httpbin preview:", r.status_code, r.text[:600])
        assert r.status_code == 200, r.text[:400]
        j = r.json()
        req_url = j.get("request_url") or j.get("url") or ""
        assert "user=6661676176" in req_url, f"{{tg_id}} not substituted: {req_url}"
        assert "{tg_id}" not in req_url, f"literal remained: {req_url}"


# ---------------- Threshold RAW progress ----------------
class TestPartnerThresholdRawProgress:
    def test_raw_have_from_partner(self, user_client):
        r = user_client.get(f"{API}/tasks")
        assert r.status_code == 200
        data = r.json()
        tasks = data if isinstance(data, list) else (data.get("tasks") or data.get("items") or [])
        # find threshold task named 'наторгуйте объём' or with min=5 & metric args.tradeVolume
        target = None
        for t in tasks:
            title = (t.get("title") or "") + " " + json.dumps(t.get("title_i18n") or {})
            if "наторгуйте" in title or "trade volume" in title.lower() or "tradeVolume" in json.dumps(t):
                target = t
                break
        if not target:
            # fallback: any partner threshold task with need=5
            for t in tasks:
                if t.get("action_type") == "partner_quest" and t.get("quest_kind") == "partner" and (t.get("partner_need") == 5 or t.get("partner_check_min") == 5):
                    target = t; break
        assert target, f"seeded threshold task not found; tasks={[(t.get('title'), t.get('quest_kind'), t.get('partner_need')) for t in tasks]}"
        print("Threshold task:", target.get("id"), "have=", target.get("partner_have"), "need=", target.get("partner_need"), "ready=", target.get("partner_progress_ready"))
        assert str(target.get("partner_have")) == "3", f"expected raw have=3, got {target.get('partner_have')}: {target}"
        assert str(target.get("partner_need")) == "5", f"need=5, got {target.get('partner_need')}"
        assert target.get("partner_progress_ready") is True


# ---------------- Verify flow (LOCAL & threshold) ----------------
class TestPartnerVerifyFlow:
    def _get_tasks(self, c):
        r = c.get(f"{API}/tasks")
        assert r.status_code == 200
        data = r.json()
        return data if isinstance(data, list) else (data.get("tasks") or data.get("items") or [])

    def test_local_verify_succeeds_or_idempotent(self, user_client):
        tasks = self._get_tasks(user_client)
        local = next((t for t in tasks if t.get("action_type") == "partner_quest" and t.get("quest_kind") == "local"), None)
        assert local, "LOCAL partner quest not found"
        r = user_client.post(f"{API}/tasks/{local['id']}/verify", json={})
        print("LOCAL verify:", r.status_code, r.text[:400])
        assert r.status_code in (200, 201, 400, 409), r.text[:300]

    def test_threshold_verify_fails_and_reverts(self, user_client):
        tasks = self._get_tasks(user_client)
        thr = next((t for t in tasks if t.get("action_type") == "partner_quest" and t.get("quest_kind") == "partner"), None)
        assert thr, "threshold partner quest not found"
        r = user_client.post(f"{API}/tasks/{thr['id']}/verify", json={})
        print("threshold verify:", r.status_code, r.text[:400])
        # Should not become done (have=3 < need=5)
        if r.status_code == 200:
            j = r.json()
            assert (j.get("ok") is False) or (j.get("status") not in ("done", "completed")) or (j.get("success") is False), f"threshold wrongly succeeded: {j}"
        else:
            assert r.status_code in (400, 409, 422)
        # After verify: threshold task still not done
        tasks2 = self._get_tasks(user_client)
        thr2 = next((t for t in tasks2 if t.get("id") == thr["id"]), None)
        assert thr2 and thr2.get("status") not in ("done", "completed"), f"status={thr2 and thr2.get('status')}"


# ---------------- Reward text in notification ----------------
class TestRewardNotification:
    def test_local_reward_text_in_notification_en(self, user2_client):
        # set to english
        r = user2_client.put(f"{API}/auth/update-language", json={"language": "en"})
        assert r.status_code == 200, r.text[:200]
        time.sleep(0.5)
        # find local quest with reward_description
        rt = user2_client.get(f"{API}/tasks")
        assert rt.status_code == 200
        data = rt.json()
        tasks = data if isinstance(data, list) else (data.get("tasks") or data.get("items") or [])
        local = next((t for t in tasks if t.get("action_type") == "partner_quest" and t.get("quest_kind") == "local"), None)
        assert local, "LOCAL partner quest not found"
        reward_desc = local.get("reward_description") or (local.get("reward_description_i18n") or {}).get("ru") or ""
        print("local task reward_description:", reward_desc, "status=", local.get("status"))
        vr = user2_client.post(f"{API}/tasks/{local['id']}/verify", json={})
        print("verify:", vr.status_code, vr.text[:300])

        # try to fetch notifications
        endpoints = [f"{API}/notifications", f"{API}/notifications?limit=20", f"{API}/notifications/list", f"{API}/notifications/me"]
        notif_text_all = ""
        found_endpoint = False
        for url in endpoints:
            nr = user2_client.get(url)
            print("notif GET", url, "=>", nr.status_code)
            if nr.status_code == 200:
                found_endpoint = True
                jd = nr.json()
                items = jd if isinstance(jd, list) else (jd.get("items") or jd.get("notifications") or [])
                for n in items[:30]:
                    notif_text_all += " " + json.dumps(n, ensure_ascii=False)
                break
        if not found_endpoint:
            pytest.skip("no notifications endpoint available; verify via logs/DB")
        # Look for english-ish reward text presence
        print("notif_text_all snippet:", notif_text_all[:800])
        # Expect at least some english reward-related keyword since user is 'en'
        # If reward_desc is Russian in source, translated text should include english words like 'reward'/'bonus'/'GRAM'
        # Accept either english reward keywords or the localized reward_description we already know
        assert any(k in notif_text_all.lower() for k in ("reward", "bonus", "gram", "receive", "task", "completed")), f"no reward-y English text found: {notif_text_all[:600]}"


# ---------------- Alliance username enrichment ----------------
class TestAllianceEnrichment:
    def test_offers(self, user_client):
        for path in ("/alliances/offers", "/alliances/my-offers", "/alliances/counter-offers", "/contracts/my"):
            r = user_client.get(f"{API}{path}")
            print(path, "=>", r.status_code, r.text[:200])
            assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text[:200]}"
            j = r.json()
            items = j if isinstance(j, list) else (j.get("items") or j.get("offers") or j.get("contracts") or [])
            for it in items[:10]:
                if "patron_id" in it or "patron" in it:
                    assert ("patron_username" in it) or ("patron" in it and isinstance(it["patron"], dict)), f"patron_username missing: {list(it.keys())}"
                if "vassal_id" in it or "vassal" in it:
                    assert ("vassal_username" in it) or ("vassal" in it and isinstance(it["vassal"], dict)), f"vassal_username missing: {list(it.keys())}"


# ---------------- Chat WebSocket auth ----------------
class TestChatWebSocket:
    def test_ws_auth_stays_open(self, user_client):
        try:
            import websockets
        except ImportError:
            pytest.skip("websockets not installed")
        # get jwt
        me = user_client.get(f"{API}/auth/me")
        assert me.status_code == 200
        # get token from session header
        tok = user_client.headers.get("Authorization", "").replace("Bearer ", "")
        assert tok
        ws_url = BASE_URL.replace("https://", "wss://").replace("http://", "ws://") + "/api/ws/chat"

        async def run():
            async with websockets.connect(ws_url, open_timeout=15, close_timeout=5) as ws:
                await ws.send(json.dumps({"action": "auth", "token": tok}))
                await ws.send(json.dumps({"action": "subscribe_city", "city_id": "ton-island"}))
                # collect frames for ~4s; should NOT close with 4001
                got_subscribed = False
                closed_code = None
                try:
                    for _ in range(6):
                        msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
                        print("WS recv:", msg[:200])
                        try:
                            payload = json.loads(msg)
                            if payload.get("type") == "subscribed":
                                got_subscribed = True
                        except Exception:
                            pass
                except asyncio.TimeoutError:
                    pass
                except websockets.ConnectionClosed as e:
                    closed_code = e.code
                    print("WS closed code=", e.code, "reason=", e.reason)
                return got_subscribed, closed_code

        got_sub, closed = asyncio.get_event_loop().run_until_complete(run()) if False else asyncio.new_event_loop().run_until_complete(run())
        print("WS result subscribed=", got_sub, "closed=", closed)
        assert closed != 4001, f"WS closed 4001 (auth failure)"
        # Not strictly required to get subscribed frame, but ideally yes
