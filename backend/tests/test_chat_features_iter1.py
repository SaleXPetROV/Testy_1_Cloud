"""Chat feature tests — 4 new chat requirements:
 - message send does not duplicate
 - lang + translations={} stamped on new messages
 - translate endpoint returns cached=False first, cached=True second
 - global message endpoint returns messages sorted, no _id
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

USER_EMAIL = "testuser@example.com"
USER_PASSWORD = "Test1234!"
ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")


@pytest.fixture(scope="module")
def user_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": USER_EMAIL, "password": USER_PASSWORD}, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    data = r.json()
    tok = data.get("access_token") or data.get("token")
    assert tok, f"no token in login response: {data}"
    return tok


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=15)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    data = r.json()
    tok = data.get("access_token") or data.get("token")
    assert tok
    return tok


class TestChatGlobalList:
    def test_global_messages_public_no_mongo_id(self):
        r = requests.get(f"{BASE_URL}/api/chat/messages/global?limit=50", timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert "messages" in data and isinstance(data["messages"], list)
        assert len(data["messages"]) > 0, "seed_chat should have produced messages"
        for m in data["messages"]:
            assert "_id" not in m
            assert "id" in m and "content" in m and "created_at" in m
            # New fields added by feature
            assert "lang" in m, f"message missing 'lang': {m}"
            assert "translations" in m, f"message missing 'translations': {m}"


class TestChatSend:
    def test_send_message_returns_lang_and_empty_translations(self, user_token):
        content = f"TEST_ping_{int(time.time())}"
        r = requests.post(f"{BASE_URL}/api/chat/send",
                          headers={"Authorization": f"Bearer {user_token}"},
                          json={"content": content, "chat_type": "global"}, timeout=15)
        assert r.status_code == 200, f"send failed: {r.status_code} {r.text}"
        data = r.json()
        msg = data["message"]
        assert msg["content"] == content
        assert "lang" in msg
        assert msg.get("translations") == {}
        # Verify persisted exactly once in DB via the list endpoint
        r2 = requests.get(f"{BASE_URL}/api/chat/messages/global?limit=100", timeout=15)
        assert r2.status_code == 200
        msgs = r2.json()["messages"]
        matches = [m for m in msgs if m["content"] == content]
        assert len(matches) == 1, f"expected exactly one message with content {content}, found {len(matches)}"


class TestChatTranslateCache:
    """Translate: 1st call → cached=False (LLM), 2nd call → cached=True (DB)."""

    def test_translate_uses_cache_on_second_call(self, user_token, admin_token):
        # Post a Russian message from admin (user language is ru per seed)
        content = "Привет мир_" + str(int(time.time()))
        r = requests.post(f"{BASE_URL}/api/chat/send",
                          headers={"Authorization": f"Bearer {admin_token}"},
                          json={"content": content, "chat_type": "global"}, timeout=15)
        assert r.status_code == 200, r.text
        mid = r.json()["message"]["id"]
        author_lang = r.json()["message"].get("lang")

        # Pick a target lang different from author's lang
        target = "en" if author_lang != "en" else "es"

        # First call — expect LLM path (cached=False)
        r1 = requests.post(f"{BASE_URL}/api/chat/translate",
                           headers={"Authorization": f"Bearer {user_token}"},
                           json={"message_id": mid, "target_lang": target}, timeout=60)
        assert r1.status_code == 200, f"translate1 failed: {r1.status_code} {r1.text}"
        d1 = r1.json()
        assert d1["message_id"] == mid
        assert d1["target_lang"] == target
        assert isinstance(d1["translation"], str) and len(d1["translation"]) > 0
        assert d1["cached"] is False, f"first call should NOT be cached, got {d1}"

        # Second call — expect DB cache path (cached=True), same translation text
        r2 = requests.post(f"{BASE_URL}/api/chat/translate",
                           headers={"Authorization": f"Bearer {user_token}"},
                           json={"message_id": mid, "target_lang": target}, timeout=15)
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2["cached"] is True, f"second call should be cached, got {d2}"
        assert d2["translation"] == d1["translation"], "cached translation must match first result"

    def test_translate_same_lang_returns_cached_true_original(self, user_token):
        # Fetch any global message, request translation to its own language
        r = requests.get(f"{BASE_URL}/api/chat/messages/global?limit=50", timeout=15)
        assert r.status_code == 200
        msgs = r.json()["messages"]
        assert msgs
        m = msgs[-1]
        r2 = requests.post(f"{BASE_URL}/api/chat/translate",
                           headers={"Authorization": f"Bearer {user_token}"},
                           json={"message_id": m["id"], "target_lang": m.get("lang") or "ru"},
                           timeout=15)
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2["cached"] is True
        assert d2["translation"] == m["content"]

    def test_translate_unauthed_401(self):
        r = requests.post(f"{BASE_URL}/api/chat/translate",
                          json={"message_id": "x", "target_lang": "en"}, timeout=10)
        assert r.status_code in (401, 403)

    def test_translate_bad_lang_400(self, user_token):
        r = requests.post(f"{BASE_URL}/api/chat/translate",
                          headers={"Authorization": f"Bearer {user_token}"},
                          json={"message_id": "notfound", "target_lang": "xx"}, timeout=10)
        assert r.status_code == 400
