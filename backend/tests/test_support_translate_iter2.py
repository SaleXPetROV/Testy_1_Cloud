"""Backend tests for the SUPPORT AGENT translation features (iter 2).

Covers:
 1. POST /api/sys-ops/message/{id}/translate — caches on the message doc; 2nd call returns cached:true.
 2. POST /api/sys-ops/chat/{id}/message with target_lang -> stores translation as content, original_content=RU.
    Without target_lang (or ru) stores plain Russian, no original_content.
 3. GET  /api/sys-ops/chat/{id} returns chat.user_language.
 4. Regression: POST /api/chat/translate still works and caches on the message.
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL must be set"

ADMIN = {"email": "sanyanazarov212@gmail.com", "password": os.environ.get("TEST_ADMIN_PASSWORD", "")}
USER = {"email": "testuser@example.com", "password": "Test1234!"}


def _login(session: requests.Session, creds):
    r = session.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=20)
    assert r.status_code == 200, f"login failed {r.status_code} {r.text[:200]}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_token():
    s = requests.Session()
    return _login(s, ADMIN)


@pytest.fixture(scope="module")
def user_token():
    s = requests.Session()
    return _login(s, USER)


@pytest.fixture(scope="module")
def support_chat(user_token, admin_token):
    """Create a support chat (as user), claim it (as admin)."""
    uh = {"Authorization": f"Bearer {user_token}"}
    ah = {"Authorization": f"Bearer {admin_token}"}

    # Create chat with an ENGLISH initial message so we can translate to RU.
    r = requests.post(
        f"{BASE_URL}/api/support/chat/create",
        headers=uh,
        json={"initial_message": "Hello, I need help with my account."},
        timeout=20,
    )
    if r.status_code == 400 and "активный" in r.text:
        # Reuse existing active chat
        lc = requests.get(f"{BASE_URL}/api/support/chats", headers=uh, timeout=20)
        assert lc.status_code == 200, f"list chats: {lc.status_code} {lc.text[:200]}"
        payload = lc.json()
        chats = payload.get("chats") or payload if isinstance(payload, list) else payload.get("chats", [])
        assert chats, f"no existing chat found: {payload}"
        active = next((c for c in chats if c.get("status") != "archived"), chats[0])
        chat_id = active["id"]
        # Send an English user message to ensure we have something to translate
        requests.post(f"{BASE_URL}/api/support/chat/{chat_id}/message", headers=uh,
                      json={"content": "Hello, I need help please."}, timeout=20)
    else:
        assert r.status_code == 200, f"create chat: {r.status_code} {r.text[:200]}"
        chat = r.json()["chat"]
        chat_id = chat["id"]

    # Admin claims (may already be claimed if re-run; ignore 400/409)
    rc = requests.post(f"{BASE_URL}/api/sys-ops/chat/{chat_id}/claim", headers=ah, timeout=20)
    assert rc.status_code in (200, 400, 409), f"claim: {rc.status_code} {rc.text[:200]}"

    return {"chat_id": chat_id, "user_headers": uh, "agent_headers": ah}


# ---- Test 1: GET /chat returns user_language + provides an incoming message id
def test_agent_get_chat_has_user_language(support_chat):
    r = requests.get(
        f"{BASE_URL}/api/sys-ops/chat/{support_chat['chat_id']}",
        headers=support_chat["agent_headers"],
        timeout=20,
    )
    assert r.status_code == 200, r.text[:300]
    data = r.json()
    assert "chat" in data and "messages" in data
    assert "user_language" in data["chat"], "chat.user_language missing"
    assert isinstance(data["chat"]["user_language"], str)
    assert len(data["chat"]["user_language"]) >= 2
    # Should have the initial user message
    user_msgs = [m for m in data["messages"] if m.get("sender_type") == "user"]
    assert user_msgs, "expected at least one user message from initial_message"
    support_chat["_first_user_msg_id"] = user_msgs[0]["id"]


# ---- Test 2: translate endpoint caches on the message doc
def test_agent_translate_message_caches(support_chat):
    msg_id = support_chat.get("_first_user_msg_id")
    assert msg_id, "must run test_agent_get_chat_has_user_language first"

    url = f"{BASE_URL}/api/sys-ops/message/{msg_id}/translate"
    r1 = requests.post(url, headers=support_chat["agent_headers"],
                       json={"target_lang": "ru"}, timeout=45)
    assert r1.status_code == 200, r1.text[:300]
    d1 = r1.json()
    assert d1["target_lang"] == "ru"
    assert isinstance(d1.get("translation"), str) and d1["translation"].strip(), \
        f"translation empty: {d1}"

    # 2nd call → must be cached
    r2 = requests.post(url, headers=support_chat["agent_headers"],
                       json={"target_lang": "ru"}, timeout=20)
    assert r2.status_code == 200, r2.text[:300]
    d2 = r2.json()
    assert d2["cached"] is True, f"expected cached True on 2nd call, got {d2}"
    assert d2["translation"] == d1["translation"]


# ---- Test 3a: agent sends WITH target_lang → stored content is translated
def test_agent_send_with_target_lang_stores_translation(support_chat):
    chat_id = support_chat["chat_id"]
    russian = "Здравствуйте, чем я могу вам помочь?"
    r = requests.post(
        f"{BASE_URL}/api/sys-ops/chat/{chat_id}/message",
        headers=support_chat["agent_headers"],
        json={"content": russian, "target_lang": "en"},
        timeout=45,
    )
    assert r.status_code == 200, r.text[:300]

    # Fetch and inspect the last agent message
    rg = requests.get(f"{BASE_URL}/api/sys-ops/chat/{chat_id}",
                      headers=support_chat["agent_headers"], timeout=20)
    assert rg.status_code == 200
    msgs = rg.json()["messages"]
    agent_msgs = [m for m in msgs if m.get("sender_type") == "agent"]
    assert agent_msgs, "no agent message after send"
    last = agent_msgs[-1]

    assert last.get("original_content") == russian, \
        f"original_content mismatch: {last.get('original_content')}"
    # content should be a translation (English) — non-empty and not identical to russian
    assert last["content"] and last["content"] != russian, \
        f"content should be translated, got: {last['content']}"
    assert last.get("lang") == "en", f"lang should be 'en', got {last.get('lang')}"
    tr = last.get("translations") or {}
    assert tr.get("ru") == russian
    assert tr.get("en") == last["content"]


# ---- Test 3b: agent sends WITHOUT target_lang → plain Russian, no original_content
def test_agent_send_without_target_lang_is_plain_russian(support_chat):
    chat_id = support_chat["chat_id"]
    russian = "Понял вас, минуту."
    r = requests.post(
        f"{BASE_URL}/api/sys-ops/chat/{chat_id}/message",
        headers=support_chat["agent_headers"],
        json={"content": russian},  # no target_lang
        timeout=20,
    )
    assert r.status_code == 200, r.text[:300]

    rg = requests.get(f"{BASE_URL}/api/sys-ops/chat/{chat_id}",
                      headers=support_chat["agent_headers"], timeout=20)
    msgs = rg.json()["messages"]
    last = [m for m in msgs if m.get("sender_type") == "agent"][-1]
    assert last["content"] == russian
    assert not last.get("original_content"), \
        f"original_content should be falsy, got: {last.get('original_content')}"
    assert last.get("lang") == "ru"
    assert not last.get("translations"), \
        f"translations should be empty, got: {last.get('translations')}"


# ---- Test 3c: target_lang='ru' behaves like no target_lang (plain)
def test_agent_send_with_target_ru_is_plain(support_chat):
    chat_id = support_chat["chat_id"]
    russian = "Спасибо!"
    r = requests.post(
        f"{BASE_URL}/api/sys-ops/chat/{chat_id}/message",
        headers=support_chat["agent_headers"],
        json={"content": russian, "target_lang": "ru"},
        timeout=20,
    )
    assert r.status_code == 200
    rg = requests.get(f"{BASE_URL}/api/sys-ops/chat/{chat_id}",
                      headers=support_chat["agent_headers"], timeout=20)
    last = [m for m in rg.json()["messages"] if m.get("sender_type") == "agent"][-1]
    assert last["content"] == russian
    assert not last.get("original_content")
    assert last.get("lang") == "ru"


# ---- Test 4: /api/chat/translate regression (global chat) still works + caches
def test_global_chat_translate_regression(user_token):
    uh = {"Authorization": f"Bearer {user_token}"}
    # Send a non-Russian message on global chat
    text = "Good morning, this is a test message."
    rs = requests.post(f"{BASE_URL}/api/chat/send", headers=uh,
                       json={"content": text}, timeout=20)
    assert rs.status_code == 200, rs.text[:300]
    msg = rs.json().get("message") or rs.json()
    mid = msg.get("id") or msg.get("message_id")
    assert mid, f"no id in send response: {rs.json()}"

    r1 = requests.post(f"{BASE_URL}/api/chat/translate", headers=uh,
                       json={"message_id": mid, "target_lang": "ru"}, timeout=45)
    assert r1.status_code == 200, r1.text[:300]
    d1 = r1.json()
    assert d1.get("translation") or d1.get("translated_text"), f"empty translation: {d1}"

    r2 = requests.post(f"{BASE_URL}/api/chat/translate", headers=uh,
                       json={"message_id": mid, "target_lang": "ru"}, timeout=20)
    assert r2.status_code == 200
    d2 = r2.json()
    # cached flag should be True on 2nd call (feature under test)
    assert d2.get("cached") is True, f"expected cached=True on 2nd call, got: {d2}"
