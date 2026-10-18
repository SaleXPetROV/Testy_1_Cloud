"""Sprint 1 + Sprint 2 regression suite for TON_CITY_v2.3.

Covers (per current review request):
- Telegram fix: /api/admin/settings/telegram-bot-token, telegram-bot-username, GET telegram-bot
- F17 RBAC: require_scope("finance") on admin_router endpoints
- F26 OAuth state + PKCE (google/init + invalid state on callback)
- F37 Honeytokens: /api/admin/backup-download, /api/admin/db-dump return 404
- F8 WS token-in-first-message: /api/ws/chat, /api/ws/support/agent, legacy /api/ws/chat?token=
- F10/F40 chat send + rate-limit
- General regression: /api/health
"""
import asyncio
import os
import time
import json
import pytest
import requests
import websockets

def _load_backend_url():
    v = os.environ.get("REACT_APP_BACKEND_URL", "").strip()
    if v:
        return v.rstrip("/")
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    return line.split("=", 1)[1].strip().rstrip("/")
    except Exception:
        pass
    return ""

BASE_URL = _load_backend_url()
assert BASE_URL, "REACT_APP_BACKEND_URL missing"
WSS_BASE = BASE_URL.replace("https://", "wss://").replace("http://", "ws://")

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PASSWORD = "Test1234!"

VALID_BOT_TOKEN = "123456789:AAElongtoken_ABCDEFGHIJKLMNOP"
INVALID_BOT_TOKEN = "abc"


@pytest.fixture(scope="session")
def s():
    return requests.Session()


@pytest.fixture(scope="session")
def admin_token(s):
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=15)
    assert r.status_code == 200, r.text[:400]
    return r.json()["token"]


@pytest.fixture(scope="session")
def user_token(s):
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": USER_EMAIL, "password": USER_PASSWORD}, timeout=15)
    assert r.status_code == 200, r.text[:400]
    return r.json()["token"]


def h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ---------- Health / auth ----------
def test_health(s):
    r = s.get(f"{BASE_URL}/api/health", timeout=10)
    assert r.status_code == 200
    assert r.json().get("status") == "healthy"


def test_admin_login(admin_token):
    assert isinstance(admin_token, str) and len(admin_token) > 20


def test_user_login(user_token):
    assert isinstance(user_token, str) and len(user_token) > 20


# ---------- Telegram fix ----------
class TestTelegramFix:
    def test_set_bot_token_success(self, s, admin_token):
        r = s.post(f"{BASE_URL}/api/admin/settings/telegram-bot-token",
                   json={"bot_token": VALID_BOT_TOKEN}, headers=h(admin_token), timeout=15)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d.get("status") == "success"
        assert d.get("bot_configured") is True

    def test_get_bot_config_shows_configured(self, s, admin_token):
        r = s.get(f"{BASE_URL}/api/admin/settings/telegram-bot",
                  headers=h(admin_token), timeout=10)
        assert r.status_code == 200, r.text[:300]
        assert r.json().get("bot_configured") is True

    def test_set_bot_token_invalid(self, s, admin_token):
        r = s.post(f"{BASE_URL}/api/admin/settings/telegram-bot-token",
                   json={"bot_token": INVALID_BOT_TOKEN}, headers=h(admin_token), timeout=10)
        assert r.status_code == 400, f"expected 400 got {r.status_code}: {r.text[:200]}"

    def test_set_bot_username(self, s, admin_token):
        r = s.post(f"{BASE_URL}/api/admin/settings/telegram-bot-username",
                   json={"username": "gram_city_bot"}, headers=h(admin_token), timeout=10)
        assert r.status_code == 200, r.text[:300]
        assert r.json().get("status") == "success"

        g = s.get(f"{BASE_URL}/api/admin/settings/telegram-bot",
                  headers=h(admin_token), timeout=10)
        assert g.status_code == 200
        assert g.json().get("bot_username") == "gram_city_bot"

    def test_bot_endpoints_require_admin(self, s, user_token):
        r = s.get(f"{BASE_URL}/api/admin/settings/telegram-bot",
                  headers=h(user_token), timeout=10)
        assert r.status_code in (401, 403)


# ---------- F17 RBAC ----------
class TestF17RBAC:
    def test_admin_can_call_finance_deploy(self, s, admin_token):
        r = s.post(f"{BASE_URL}/api/admin/contract-deployer/deploy",
                   headers=h(admin_token), timeout=20)
        # Not 403/401 = RBAC allowed superadmin. 400/500 is fine (no wallet).
        assert r.status_code != 403, f"superadmin got 403: {r.text[:300]}"
        assert r.status_code != 401, f"superadmin got 401: {r.text[:300]}"

    def test_user_blocked_on_finance(self, s, user_token):
        r = s.post(f"{BASE_URL}/api/admin/contract-deployer/deploy",
                   headers=h(user_token), timeout=15)
        assert r.status_code in (401, 403)

    def test_user_blocked_on_admin_generic(self, s, user_token):
        r = s.get(f"{BASE_URL}/api/admin/settings/telegram-bot",
                  headers=h(user_token), timeout=10)
        assert r.status_code in (401, 403)


# ---------- F26 OAuth ----------
class TestF26OAuth:
    def test_google_init(self, s):
        r = s.post(f"{BASE_URL}/api/auth/google/init", timeout=10)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert "state" in d and isinstance(d["state"], str) and len(d["state"]) > 10
        assert "code_challenge" in d and len(d["code_challenge"]) > 10
        assert d.get("code_challenge_method") == "S256"

    def test_google_callback_invalid_state(self, s):
        r = s.post(f"{BASE_URL}/api/auth/google/callback", json={
            "code": "x",
            "redirect_uri": "https://blockchain-town.preview.emergentagent.com/auth/google/callback",
            "state": "nonexistent_state_xyz",
        }, timeout=15)
        assert r.status_code == 400, f"expected 400 got {r.status_code}: {r.text[:300]}"
        assert "state" in r.text.lower() or "invalid" in r.text.lower()


# ---------- F37 Honeytokens ----------
class TestF37Honeytokens:
    def test_backup_download_trap(self, s):
        r = s.get(f"{BASE_URL}/api/admin/backup-download", timeout=10)
        assert r.status_code == 404, r.text[:200]

    def test_db_dump_trap(self, s):
        r = s.get(f"{BASE_URL}/api/admin/db-dump", timeout=10)
        assert r.status_code == 404, r.text[:200]

    def test_users_export_trap(self, s):
        r = s.get(f"{BASE_URL}/api/admin/users/export.csv", timeout=10)
        assert r.status_code == 404


# ---------- F8 WebSocket auth via first message ----------
async def _ws_recv(ws, timeout=5):
    return await asyncio.wait_for(ws.recv(), timeout=timeout)


async def _chat_auth_ping(token_query=None, first_msg_token=None):
    url = f"{WSS_BASE}/api/ws/chat"
    if token_query:
        url += f"?token={token_query}"
    async with websockets.connect(url, open_timeout=10) as ws:
        if first_msg_token is not None:
            await ws.send(json.dumps({"action": "auth", "token": first_msg_token}))
        # brief pause to allow server auth
        await asyncio.sleep(0.3)
        await ws.send(json.dumps({"action": "ping"}))
        # collect a few frames, look for pong
        for _ in range(5):
            try:
                raw = await _ws_recv(ws, timeout=4)
            except asyncio.TimeoutError:
                return None
            try:
                m = json.loads(raw)
            except Exception:
                continue
            if m.get("type") == "pong":
                return "pong"
        return None


class TestF8WebSocket:
    def test_chat_ws_first_message_auth(self, admin_token):
        result = asyncio.get_event_loop().run_until_complete(
            _chat_auth_ping(first_msg_token=admin_token)
        )
        assert result == "pong", f"expected pong via first-message auth, got {result}"

    def test_chat_ws_bad_first_message_closes_4001(self):
        async def run():
            url = f"{WSS_BASE}/api/ws/chat"
            try:
                async with websockets.connect(url, open_timeout=10) as ws:
                    await ws.send(json.dumps({"action": "auth", "token": "totally_invalid"}))
                    # Wait for close
                    try:
                        await asyncio.wait_for(ws.recv(), timeout=5)
                    except websockets.ConnectionClosed as e:
                        return e.code
                    except asyncio.TimeoutError:
                        return None
                    # If we got a frame, keep reading until close
                    for _ in range(3):
                        try:
                            await asyncio.wait_for(ws.recv(), timeout=3)
                        except websockets.ConnectionClosed as e:
                            return e.code
                        except asyncio.TimeoutError:
                            return None
            except websockets.ConnectionClosed as e:
                return e.code
            return None

        code = asyncio.get_event_loop().run_until_complete(run())
        # Accept 4001 (our custom) or any 4xxx close indicating auth reject
        assert code == 4001 or (isinstance(code, int) and 4000 <= code < 5000), \
            f"expected 4001-family close code, got {code}"

    def test_chat_ws_legacy_query_token(self, admin_token):
        result = asyncio.get_event_loop().run_until_complete(
            _chat_auth_ping(token_query=admin_token)
        )
        assert result == "pong", f"legacy query-token flow failed: {result}"

    def test_support_agent_ws_first_message(self, admin_token):
        async def run():
            url = f"{WSS_BASE}/api/ws/support/agent"
            async with websockets.connect(url, open_timeout=10) as ws:
                await ws.send(json.dumps({"action": "auth", "token": admin_token}))
                await asyncio.sleep(0.3)
                await ws.send(json.dumps({"action": "ping"}))
                for _ in range(5):
                    try:
                        raw = await _ws_recv(ws, timeout=4)
                    except asyncio.TimeoutError:
                        return None
                    try:
                        m = json.loads(raw)
                    except Exception:
                        continue
                    if m.get("type") == "pong":
                        return "pong"
                return None

        result = asyncio.get_event_loop().run_until_complete(run())
        assert result == "pong", f"support agent WS: {result}"

    def test_game_ws_ping(self, s, admin_token):
        # Need user_id for the parametrized game socket
        me = s.get(f"{BASE_URL}/api/auth/me", headers=h(admin_token), timeout=10)
        if me.status_code != 200:
            pytest.skip(f"/api/auth/me not available: {me.status_code}")
        user_id = me.json().get("id") or me.json().get("user", {}).get("id")
        if not user_id:
            pytest.skip("no user id from /me")

        async def run():
            url = f"{WSS_BASE}/api/ws/{user_id}"
            async with websockets.connect(url, open_timeout=10) as ws:
                await ws.send(json.dumps({"type": "ping"}))
                for _ in range(5):
                    try:
                        raw = await _ws_recv(ws, timeout=4)
                    except asyncio.TimeoutError:
                        return None
                    try:
                        m = json.loads(raw)
                    except Exception:
                        continue
                    if m.get("type") == "pong":
                        return "pong"
                return None

        result = asyncio.get_event_loop().run_until_complete(run())
        assert result == "pong", f"game WS ping failed: {result}"


# ---------- F40 chat rate limit + F10 sanity ----------
class TestChatRateLimit:
    def test_chat_send_ok(self, s, user_token):
        r = s.post(f"{BASE_URL}/api/chat/send",
                   json={"content": "hello world", "chat_type": "global"},
                   headers=h(user_token), timeout=10)
        assert r.status_code == 200, r.text[:300]
        assert r.json().get("status") == "sent"

    def test_chat_send_rate_limit_429(self, s, user_token):
        # Reuse same user; limit is 60/min. Send 75.
        codes = []
        for i in range(75):
            r = s.post(f"{BASE_URL}/api/chat/send",
                       json={"content": f"spam {i}", "chat_type": "global"},
                       headers=h(user_token), timeout=8)
            codes.append(r.status_code)
            if r.status_code == 429:
                break
        assert 429 in codes, f"no 429 seen in 75 rapid sends; codes={codes[:10]}...{codes[-5:]}"


# ---------- F10 atomic sanity: withdraw endpoint should not 500 ----------
class TestF10Sanity:
    def test_withdraw_instant_no_500(self, s, user_token):
        r = s.post(f"{BASE_URL}/api/withdraw/instant",
                   json={"amount": 0.001, "wallet_address": "UQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"},
                   headers=h(user_token), timeout=15)
        # Expect a clean 4xx (insufficient balance/invalid wallet), never 500
        assert r.status_code != 500, f"withdraw returned 500: {r.text[:300]}"
