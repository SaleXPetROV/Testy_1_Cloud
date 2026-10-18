"""Backend tests for:
1) Admin TG-bot stats endpoint /api/admin/telegram-bot-stats
2) Multi-language announcement broadcast
3) HTML preservation in announcement notifications
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://city-games-test.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASS = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PASS = "Test1234!"


# ---------- Fixtures ----------
@pytest.fixture(scope="session")
def admin_token():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=30)
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text}"
    data = r.json()
    assert data["user"].get("is_admin") is True, f"Admin flag missing: {data['user']}"
    return data["token"]


@pytest.fixture(scope="session")
def user_token():
    r = requests.post(f"{API}/auth/login", json={"email": USER_EMAIL, "password": USER_PASS}, timeout=30)
    assert r.status_code == 200, f"User login failed: {r.status_code} {r.text}"
    return r.json()["token"]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ---------- Health ----------
def test_health():
    r = requests.get(f"{API}/health", timeout=15)
    assert r.status_code == 200
    data = r.json()
    # accept common healthy responses
    assert data.get("status") in ("healthy", "ok") or data.get("ok") is True, data


# ---------- Auth ----------
def test_admin_login_returns_is_admin(admin_token):
    assert isinstance(admin_token, str) and len(admin_token) > 20


def test_user_login(user_token):
    assert isinstance(user_token, str) and len(user_token) > 20


# ---------- TG-bot stats ----------
def test_tg_bot_stats_admin(admin_token):
    r = requests.get(f"{API}/admin/telegram-bot-stats", headers=_hdr(admin_token), timeout=30)
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    data = r.json()
    for k in ("total", "premium_count", "non_premium_count", "users"):
        assert k in data, f"Missing field {k}: {data.keys()}"
    assert isinstance(data["users"], list)
    assert data["total"] >= 3, f"Expected >=3 seeded rows, got {data['total']}"

    # Validate each user entry structure
    required_keys = {"chat_id", "telegram_user_id", "username", "is_premium", "language",
                     "first_activity_at", "last_activity_at", "linked_account"}
    for u in data["users"]:
        missing = required_keys - set(u.keys())
        assert not missing, f"User entry missing keys {missing}: {u}"

    # Find seeded chat_ids
    by_chat = {str(u["chat_id"]): u for u in data["users"]}
    for cid in ("100000001", "200000002", "300000003"):
        assert cid in by_chat, f"Seeded chat_id {cid} missing. Present: {list(by_chat.keys())[:10]}"

    # 100000001 should be linked to admin
    linked = by_chat["100000001"].get("linked_account")
    assert linked is not None, "Expected linked_account for 100000001"
    assert linked.get("email") == ADMIN_EMAIL, f"Linked account mismatch: {linked}"
    for lk in ("id", "username", "email", "display_name"):
        assert lk in linked, f"linked_account missing {lk}: {linked}"


def test_tg_bot_stats_no_auth():
    r = requests.get(f"{API}/admin/telegram-bot-stats", timeout=15)
    assert r.status_code in (401, 403), f"Expected 401/403, got {r.status_code} {r.text}"


def test_tg_bot_stats_regular_user_forbidden(user_token):
    r = requests.get(f"{API}/admin/telegram-bot-stats", headers=_hdr(user_token), timeout=15)
    assert r.status_code == 403, f"Expected 403 for non-admin, got {r.status_code} {r.text}"


# ---------- Announcement: single-language w/ HTML ----------
_created_ids = []


def test_announcement_single_language_html(admin_token, user_token):
    payload = {
        "title": "TEST_single",
        "message": "<b>Bold</b> and <i>italic</i>",
        "buttons": [{"text": "Go", "url": "https://gramcity.games"}],
        "image_url": None,
    }
    r = requests.post(f"{API}/admin/announcement", headers=_hdr(admin_token), json=payload, timeout=30)
    assert r.status_code in (200, 201), f"{r.status_code} {r.text}"
    body = r.json()
    ann_id = body.get("id") or body.get("_id") or body.get("announcement_id")
    if ann_id:
        _created_ids.append(ann_id)
    assert body.get("status") in ("published", "sent", "ok") or "id" in body, body

    # verify notification for user preserves HTML
    time.sleep(1)
    notif = requests.get(f"{API}/notifications", headers=_hdr(user_token), timeout=15)
    assert notif.status_code == 200, notif.text
    notifs = notif.json() if isinstance(notif.json(), list) else notif.json().get("notifications", [])
    found = [n for n in notifs if n.get("title") == "TEST_single"]
    assert found, f"Announcement notification not found. Sample titles: {[n.get('title') for n in notifs[:10]]}"
    assert "<b>Bold</b>" in (found[0].get("message") or ""), f"HTML not preserved: {found[0]}"


# ---------- Announcement: multi-language ----------
def test_announcement_multilang(admin_token, user_token):
    payload = {
        "translations": {
            "ru": {"title": "TEST_multi_ru", "message": "<b>Русский</b>", "buttons": []},
            "gb": {"title": "TEST_multi_en", "message": "<b>English</b>",
                   "buttons": [{"text": "Open", "url": "https://gramcity.games"}]},
        },
    }
    r = requests.post(f"{API}/admin/announcement", headers=_hdr(admin_token), json=payload, timeout=30)
    assert r.status_code in (200, 201), f"{r.status_code} {r.text}"
    body = r.json()
    assert body.get("status") == "published", f"status: {body}"
    trs = body.get("translations")
    assert isinstance(trs, dict), f"translations missing: {body}"
    # 'gb' should be normalized to 'en'
    assert "en" in trs, f"Expected normalized 'en' key. Got: {list(trs.keys())}"
    assert "ru" in trs, f"Expected 'ru' key. Got: {list(trs.keys())}"
    assert "gb" not in trs, f"'gb' should be normalized away. Got: {list(trs.keys())}"

    ann_id = body.get("id") or body.get("_id") or body.get("announcement_id")
    if ann_id:
        _created_ids.append(ann_id)

    # testuser has language ru → should receive russian variant
    time.sleep(1)
    notif = requests.get(f"{API}/notifications", headers=_hdr(user_token), timeout=15)
    assert notif.status_code == 200
    notifs = notif.json() if isinstance(notif.json(), list) else notif.json().get("notifications", [])
    ru_found = [n for n in notifs if n.get("title") == "TEST_multi_ru"]
    assert ru_found, f"Russian variant not delivered. Titles seen: {[n.get('title') for n in notifs[:10]]}"
    assert "<b>Русский</b>" in (ru_found[0].get("message") or ""), f"Wrong or escaped msg: {ru_found[0]}"


def test_announcement_multilang_empty_message_400(admin_token):
    payload = {
        "translations": {
            "ru": {"title": "TEST_bad", "message": "", "buttons": []},
        },
    }
    r = requests.post(f"{API}/admin/announcement", headers=_hdr(admin_token), json=payload, timeout=15)
    assert r.status_code == 400, f"Expected 400, got {r.status_code} {r.text}"


# ---------- Delete ----------
def test_delete_announcements(admin_token):
    if not _created_ids:
        pytest.skip("No announcement id captured to delete")
    for aid in _created_ids:
        r = requests.delete(f"{API}/admin/announcement/{aid}", headers=_hdr(admin_token), timeout=15)
        assert r.status_code in (200, 204), f"Delete failed for {aid}: {r.status_code} {r.text}"
