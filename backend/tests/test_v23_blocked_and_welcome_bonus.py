"""Tests for the 5 v2.3 fixes:
1. +0.5 TON welcome bonus (idempotent) on registration
2. Blocked user can still login (200, not 403)
3. /api/auth/me returns is_blocked + translated block_reason + block_reason_original
4. Level-0 business is NOT auto-listed on marketplace (see manual DB inspection)
5. The old 24h auto-buyback is gone (City Market replaces it)
"""
import os
import uuid
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://ton-city-v2-1.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PWD = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PWD = "Test1234!"


def _admin_token():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PWD}, timeout=20)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return r.json()["token"]


def _user_token(email, pwd):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pwd}, timeout=20)
    return r


# ── 1. Welcome bonus ────────────────────────────────────────────────────────
def test_registration_welcome_bonus_idempotent():
    email = f"TEST_bonus_{uuid.uuid4().hex[:8]}@example.com"
    pwd = "Test1234!"
    username = f"TEST_b_{uuid.uuid4().hex[:6]}"
    r = requests.post(f"{API}/auth/register", json={
        "email": email, "password": pwd, "username": username, "agreement_accepted": True,
    }, timeout=30)
    assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"
    tok = r.json().get("token")
    assert tok
    h = {"Authorization": f"Bearer {tok}"}
    r1 = requests.get(f"{API}/auth/me", headers=h, timeout=20)
    assert r1.status_code == 200, r1.text
    b1 = r1.json().get("bonus_balance")
    assert abs(float(b1) - 0.5) < 1e-6, f"first /me bonus_balance expected 0.5 got {b1}"
    r2 = requests.get(f"{API}/auth/me", headers=h, timeout=20)
    b2 = r2.json().get("bonus_balance")
    assert abs(float(b2) - 0.5) < 1e-6, f"second /me bonus should still be 0.5 (idempotent) got {b2}"


# ── 2 & 3. Blocked login + /me flags ────────────────────────────────────────
def test_blocked_user_can_login_and_me_returns_flags():
    admin_tok = _admin_token()
    ah = {"Authorization": f"Bearer {admin_tok}"}

    # Get testuser id
    tr = _user_token(USER_EMAIL, USER_PWD)
    assert tr.status_code == 200, tr.text
    utok = tr.json()["token"]
    uh = {"Authorization": f"Bearer {utok}"}
    me = requests.get(f"{API}/auth/me", headers=uh, timeout=20).json()
    uid = me["id"]

    # Ensure user language is 'en' — hit settings endpoint or fall back on DB shape
    # via re-login; we'll set language via /api/user/language if exists, else skip.
    try:
        requests.post(f"{API}/user/language", headers=uh, json={"language": "en"}, timeout=10)
    except Exception:
        pass

    # Block
    reason_ru = "Тестовая причина"
    br = requests.post(f"{API}/admin/user/{uid}/block", headers=ah, json={"reason": reason_ru}, timeout=20)
    assert br.status_code == 200, f"block failed: {br.status_code} {br.text}"

    try:
        # Login the blocked user — MUST be 200
        lr = _user_token(USER_EMAIL, USER_PWD)
        assert lr.status_code == 200, f"blocked user should still login, got {lr.status_code} {lr.text}"
        btok = lr.json()["token"]
        bh = {"Authorization": f"Bearer {btok}"}
        me2 = requests.get(f"{API}/auth/me", headers=bh, timeout=25).json()
        assert me2.get("is_blocked") is True, f"is_blocked flag missing: {me2}"
        assert me2.get("block_reason_original") == reason_ru, f"original mismatch: {me2.get('block_reason_original')}"
        translated = me2.get("block_reason") or ""
        assert translated, "block_reason (translated) should be non-empty"
        # Sanity: translation should not equal the raw Russian when lang=en
        # (LibreTranslate is falling back to Emergent LLM per request).
        if (me2.get("language") or "").lower().startswith("en"):
            assert translated != reason_ru, f"expected English translation, got same Russian: {translated!r}"
    finally:
        ur = requests.post(f"{API}/admin/user/{uid}/unblock", headers=ah, timeout=20)
        assert ur.status_code == 200, f"unblock failed: {ur.status_code} {ur.text}"


# ── 4. Level-0 auto-listing removed (static code check) ─────────────────────
def test_level0_is_auto_listed_in_both_claim_paths():
    """Owner's decision (after v2.3): a claimed level-0 business is put up for
    sale at map_price × 1.2 so another player can buy it out until it is
    upgraded to level 1. Both claim sites must list it."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(here, "routes", "ton_island.py"), encoding="utf-8").read()
    assert src.count("await _list_zero_business(") == 2
    assert "create_zero_listing(" in src


# ── 5. Scheduler job registered ─────────────────────────────────────────────
def test_old_24h_buyback_is_removed():
    """The 24h auto-buyback of level-0 lots was replaced by the City Market
    (market_maker.py, 30 minutes, with tax, limits and a journal)."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in ("zero_lease.py", "background_tasks.py"):
        src = open(os.path.join(here, name), encoding="utf-8").read()
        assert "def process_zero_level_buyback" not in src
        assert 'id="zero_level_buyback"' not in src
