"""
Iteration 6 — Referral Rally sort/broadcast "no active referrals" test.

Validates:
1. current_leaderboard_sort() always returns 'active' (no presale flip-flop)
2. GET /api/admin/promo/referral-rally/current returns top10 sorted by active DESC
3. broadcast-preview text contains the localized "no active referrals" phrase
   in ALL 8 supported languages when the top-3 has active=0 everywhere.
4. When at least one user has active>0, the broadcast text shows medals, not
   the "no active" fallback (regression).
"""
import os
import sys
import pytest
import requests
from datetime import datetime, timedelta, timezone

# Import promo modules directly for unit-level checks
sys.path.insert(0, "/app/backend")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # Fall back to frontend/.env if REACT_APP_BACKEND_URL not exported
    from dotenv import dotenv_values
    _fe = dotenv_values("/app/frontend/.env")
    BASE_URL = (_fe.get("REACT_APP_BACKEND_URL") or "").rstrip("/")

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PW = os.environ.get("TEST_ADMIN_PASSWORD", "")

MSK_TZ = timezone(timedelta(hours=3))
SUPPORTED_LANGS = ("ru", "en", "es", "zh", "fr", "de", "ja", "ko")

EXPECTED_NO_ACTIVE = {
    "ru": "К сожалению, на данный момент нет активных рефералов!",
    "en": "Unfortunately, there are no active referrals at the moment!",
    "es": "Lamentablemente, ¡en este momento no hay referidos activos!",
    "zh": "很遗憾,目前还没有活跃的推荐人!",
    "fr": "Malheureusement, il n'y a aucun filleul actif pour le moment !",
    "de": "Leider gibt es im Moment keine aktiven Empfehlungen!",
    "ja": "残念ながら、現在アクティブな紹介者はいません!",
    "ko": "아쉽게도 현재 활성 추천인이 없습니다!",
}


@pytest.fixture(scope="session")
def admin_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PW},
        timeout=15,
    )
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    tok = r.json().get("access_token") or r.json().get("token")
    assert tok, f"no token in login response: {r.json()}"
    return tok


@pytest.fixture(scope="session")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="session")
def ensure_active_campaign(admin_headers):
    """Make sure there's an active referral_rally campaign; create one if missing."""
    r = requests.get(
        f"{BASE_URL}/api/admin/promo/referral-rally/current",
        headers=admin_headers, timeout=15,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    if data.get("campaign"):
        return data["campaign"]
    # Create with ends_at ~7 days ahead
    ends_at = (datetime.now(MSK_TZ) + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S+03:00")
    r2 = requests.post(
        f"{BASE_URL}/api/admin/promo/referral-rally/start",
        headers=admin_headers,
        json={"ends_at": ends_at, "prizes_ton": [100, 50, 20], "per_active_ton": 1.5},
        timeout=20,
    )
    assert r2.status_code == 200, f"start failed: {r2.status_code} {r2.text}"
    return r2.json()["campaign"]


# ==================== UNIT: current_leaderboard_sort() ====================

def test_current_leaderboard_sort_always_active():
    from promo_service import current_leaderboard_sort
    assert current_leaderboard_sort() == "active"


# ==================== UNIT: _reminder_text with empty top3 for all 8 langs ====================

@pytest.mark.parametrize("lang", SUPPORTED_LANGS)
def test_reminder_text_shows_no_active_when_all_zero(lang):
    from promo_broadcast import _reminder_text
    campaign = {
        "ends_at": (datetime.now(MSK_TZ) + timedelta(days=3)).isoformat(),
        "config": {"prizes_ton": [100, 50, 20], "per_active_ton": 1.5},
    }
    # All top rows have active=0 → should trigger the "no active" fallback
    top3 = [
        {"username": "aaa", "active": 0, "total": 33},
        {"username": "bbb", "active": 0, "total": 29},
        {"username": "ccc", "active": 0, "total": 28},
    ]
    text = _reminder_text(campaign, top3, lang, is_final_hour=False, header="none")
    expected = EXPECTED_NO_ACTIVE[lang]
    assert expected in text, (
        f"[{lang}] expected localized 'no active refs' not found. "
        f"expected={expected!r}\nGOT:\n{text}"
    )
    # And medal rows must NOT be present since nobody is active
    assert "@aaa" not in text, f"[{lang}] leaked medal row for user with active=0"
    assert "@bbb" not in text
    assert "@ccc" not in text


@pytest.mark.parametrize("lang", SUPPORTED_LANGS)
def test_reminder_text_shows_medals_when_at_least_one_active(lang):
    """Regression: if any user in top3 has active>=1, the leaderboard rows
    render (not the fallback string)."""
    from promo_broadcast import _reminder_text
    campaign = {
        "ends_at": (datetime.now(MSK_TZ) + timedelta(days=3)).isoformat(),
        "config": {"prizes_ton": [100, 50, 20], "per_active_ton": 1.5},
    }
    top3 = [
        {"username": "winner1", "active": 5, "total": 10},
        {"username": "winner2", "active": 0, "total": 8},  # filtered out
        {"username": "winner3", "active": 2, "total": 7},
    ]
    text = _reminder_text(campaign, top3, lang, is_final_hour=False, header="none")
    expected_absent = EXPECTED_NO_ACTIVE[lang]
    assert expected_absent not in text, f"[{lang}] fallback leaked despite active leaders"
    # winner1 should appear (active=5)
    assert "@winner1" in text, f"[{lang}] winner1 missing from leaderboard"
    # winner3 (active=2) should also appear
    assert "@winner3" in text, f"[{lang}] winner3 missing from leaderboard"


# ==================== INTEGRATION: /api/admin/promo/referral-rally/current ====================

def test_admin_current_returns_top10_sorted_by_active(admin_headers, ensure_active_campaign):
    r = requests.get(
        f"{BASE_URL}/api/admin/promo/referral-rally/current",
        headers=admin_headers, timeout=15,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("campaign") is not None, "expected active campaign"
    top10 = data.get("top10") or []
    # Ensure sort by active DESC (ties on total OK)
    actives = [int(r.get("active", 0)) for r in top10]
    assert actives == sorted(actives, reverse=True), (
        f"top10 not sorted by active DESC: {actives}"
    )


# ==================== INTEGRATION: broadcast-preview text ====================

def test_admin_broadcast_preview_ru(admin_headers, ensure_active_campaign):
    r = requests.get(
        f"{BASE_URL}/api/admin/promo/referral-rally/broadcast-preview",
        headers=admin_headers, timeout=20,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("ok") is True
    preview = data.get("preview") or {}
    assert preview.get("sort") == "active", f"sort should always be 'active', got {preview.get('sort')!r}"
    text = preview.get("text") or ""
    top3 = preview.get("top3") or []
    max_active = max((int(t.get("active", 0)) for t in top3), default=0)
    if max_active == 0:
        # No active refs → RU fallback must be present
        assert EXPECTED_NO_ACTIVE["ru"] in text, (
            f"expected RU 'no active refs' in preview text.\nGOT:\n{text}"
        )
    else:
        # Regression: real medal row should render, fallback must be absent
        assert EXPECTED_NO_ACTIVE["ru"] not in text, "fallback leaked despite active refs"
        assert "🥇" in text
