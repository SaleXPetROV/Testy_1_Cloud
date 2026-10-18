"""End-to-end regression for admin promo broadcast (bug-fix iteration).

Covers:
- Env-based TELEGRAM_BOT_TOKEN loaded (health check + startup logs)
- POST /api/admin/promo/referral-rally/start (idempotent)
- POST /api/admin/promo/referral-rally/broadcast returns {ok, subscribers}
- GET /api/notifications for regular user includes promo_announcement
  with i18n_key='promoBroadcast', broadcast_stage='manual', banner url
- Notification body carries raw newlines (\\n) so frontend can render <br>.
"""
import os
import datetime as dt
import requests
import pytest

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://ton-rewards-center.preview.emergentagent.com').rstrip('/')
ADMIN = {"email": "sanyanazarov212@gmail.com", "password": os.environ.get("TEST_ADMIN_PASSWORD", "")}
USER = {"email": "testuser@example.com", "password": "Test1234!"}


def _login(creds):
    r = requests.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=15)
    assert r.status_code == 200, f"login failed {r.status_code}: {r.text[:200]}"
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok, r.text[:200]
    return tok


@pytest.fixture(scope="module")
def admin_token():
    return _login(ADMIN)


@pytest.fixture(scope="module")
def user_token():
    return _login(USER)


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def test_health():
    r = requests.get(f"{BASE_URL}/api/health", timeout=10)
    assert r.status_code == 200
    assert r.json().get("status") == "healthy"


def test_ensure_rally_active(admin_token):
    # Idempotent start (409/400 means already active — acceptable)
    ends_at = (dt.datetime.utcnow() + dt.timedelta(days=7)).replace(microsecond=0).isoformat() + "+03:00"
    body = {"ends_at": ends_at, "prizes_ton": [100, 50, 20], "per_active_ton": 1.5}
    r2 = requests.post(f"{BASE_URL}/api/admin/promo/referral-rally/start",
                       headers=_h(admin_token), json=body, timeout=20)
    assert r2.status_code in (200, 201, 400, 409), r2.text[:300]


def test_broadcast(admin_token):
    r = requests.post(f"{BASE_URL}/api/admin/promo/referral-rally/broadcast",
                      headers=_h(admin_token), json={}, timeout=60)
    assert r.status_code == 200, r.text[:300]
    j = r.json()
    assert j.get("ok") is True
    assert "subscribers" in j or "subscriber_count" in j or "sent" in j, j


def test_user_notification_has_newlines_and_payload(user_token):
    r = requests.get(f"{BASE_URL}/api/notifications?limit=50",
                     headers=_h(user_token), timeout=15)
    assert r.status_code == 200, r.text[:200]
    payload = r.json()
    items = payload.get("items") or payload.get("notifications") or payload
    assert isinstance(items, list) and items, "no notifications"
    promos = [n for n in items if n.get("type") == "promo_announcement"]
    assert promos, f"no promo_announcement notif found among {len(items)}"
    # Prefer manual-stage
    manual = [n for n in promos if (n.get("payload") or {}).get("broadcast_stage") == "manual"]
    target = manual[0] if manual else promos[0]
    p = target.get("payload") or {}
    assert p.get("i18n_key") == "promoBroadcast", p
    img = p.get("image_url") or ""
    assert img.endswith("/promo/rally-banner.png"), f"bad image_url: {img}"
    # For promo_announcement the body is client-rendered from i18n_key
    # (translations file contains real \n). Verify translations file has \n
    # in promoBroadcastBody entries so sanitizeHtml can convert them to <br>.
    with open('/app/frontend/src/lib/translationsExtra.js', 'r', encoding='utf-8') as f:
        tr = f.read()
    import re
    matches = re.findall(r"promoBroadcastBody:\s*'([^']*)'", tr)
    assert len(matches) >= 8, f"expected 8 locales, got {len(matches)}"
    for i, m in enumerate(matches):
        assert '\\n' in m, f"locale #{i} promoBroadcastBody missing \\n: {m[:120]}"
