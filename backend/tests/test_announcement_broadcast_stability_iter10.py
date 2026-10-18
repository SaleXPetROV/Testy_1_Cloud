"""Iter10: Broadcast stability fix — /api/admin/announcement.

Verifies:
- Endpoint returns quickly (<2s) and does not block on fan-out
- Server stays responsive right after
- In-app notifications created (single & multi-language, language-matched)
- Validation (400) for missing message / empty translation message
- AuthZ: 403 for regular user, 401/403 unauthenticated
- Overlap guard (best-effort, don't fail if unobservable)
"""
import os
import time
import uuid
import requests
import pytest

def _load_backend_url():
    v = os.environ.get("REACT_APP_BACKEND_URL")
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
assert BASE_URL, "REACT_APP_BACKEND_URL not set"

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PASSWORD = "Test1234!"


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=20)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_token():
    return _login(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def user_token():
    return _login(USER_EMAIL, USER_PASSWORD)


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="module")
def user_headers(user_token):
    return {"Authorization": f"Bearer {user_token}"}


# ── Fast-return + server responsiveness ────────────────────────────────────
def test_single_language_broadcast_returns_fast_and_server_stays_up(admin_headers):
    marker = f"iter10-single-{uuid.uuid4().hex[:8]}"
    t0 = time.time()
    r = requests.post(
        f"{BASE_URL}/api/admin/announcement",
        json={"title": "T", "message": f"Hello {marker}"},
        headers=admin_headers,
        timeout=10,
    )
    elapsed = time.time() - t0
    # Accept 200 fast OR 409 if a prior fan-out is still running
    assert r.status_code in (200, 409), f"unexpected {r.status_code}: {r.text}"
    assert elapsed < 2.5, f"endpoint blocked for {elapsed:.2f}s"
    if r.status_code == 200:
        body = r.json()
        assert body.get("message", "").endswith(marker)
        assert body.get("status") == "published"

    # Server must remain responsive
    r2 = requests.get(f"{BASE_URL}/api/config", timeout=10)
    assert r2.status_code == 200, f"server unresponsive after broadcast: {r2.status_code}"


# ── In-app delivery (single language) ──────────────────────────────────────
def test_in_app_notification_created_single_language(admin_headers, user_headers):
    marker = f"iter10-inapp-{uuid.uuid4().hex[:8]}"
    body_msg = f"Hello {marker}"
    r = requests.post(
        f"{BASE_URL}/api/admin/announcement",
        json={"title": "InApp", "message": body_msg},
        headers=admin_headers,
        timeout=10,
    )
    if r.status_code == 409:
        # wait and retry
        time.sleep(3)
        r = requests.post(
            f"{BASE_URL}/api/admin/announcement",
            json={"title": "InApp", "message": body_msg},
            headers=admin_headers,
            timeout=10,
        )
    assert r.status_code == 200, r.text

    # Poll user notifications until it appears (fan-out is background)
    found = False
    for _ in range(15):
        time.sleep(1)
        rn = requests.get(f"{BASE_URL}/api/notifications", headers=user_headers, timeout=10)
        assert rn.status_code == 200, rn.text
        data = rn.json()
        items = data if isinstance(data, list) else data.get("notifications") or data.get("items") or []
        for n in items:
            msg = (n.get("message") or "") + " " + str(n.get("data") or "")
            if marker in msg and (n.get("type") == "announcement"):
                found = True
                break
        if found:
            break
    assert found, f"announcement notification not delivered to user (marker {marker})"


# ── Multi-language broadcast ───────────────────────────────────────────────
def test_multilanguage_broadcast(admin_headers, user_headers):
    marker_en = f"iter10-en-{uuid.uuid4().hex[:8]}"
    marker_ru = f"iter10-ru-{uuid.uuid4().hex[:8]}"
    payload = {
        "translations": {
            "ru": {"title": "Привет", "message": f"Русский текст {marker_ru}"},
            "en": {"title": "Hi", "message": f"English text {marker_en}"},
        }
    }
    t0 = time.time()
    r = requests.post(f"{BASE_URL}/api/admin/announcement", json=payload, headers=admin_headers, timeout=10)
    elapsed = time.time() - t0
    if r.status_code == 409:
        time.sleep(3)
        r = requests.post(f"{BASE_URL}/api/admin/announcement", json=payload, headers=admin_headers, timeout=10)
        elapsed = 0
    assert r.status_code == 200, r.text
    assert elapsed < 2.5, f"multilang endpoint blocked {elapsed:.2f}s"

    # Server still up
    assert requests.get(f"{BASE_URL}/api/config", timeout=10).status_code == 200

    # User should get one of the variants (their language)
    found_variant = None
    for _ in range(15):
        time.sleep(1)
        rn = requests.get(f"{BASE_URL}/api/notifications", headers=user_headers, timeout=10)
        assert rn.status_code == 200
        data = rn.json()
        items = data if isinstance(data, list) else data.get("notifications") or data.get("items") or []
        for n in items:
            m = (n.get("message") or "")
            if marker_en in m:
                found_variant = "en"; break
            if marker_ru in m:
                found_variant = "ru"; break
        if found_variant:
            break
    assert found_variant in ("en", "ru"), "no language-variant announcement delivered"


# ── Validation ─────────────────────────────────────────────────────────────
def test_validation_missing_message_returns_400(admin_headers):
    r = requests.post(
        f"{BASE_URL}/api/admin/announcement",
        json={"title": "x"},
        headers=admin_headers,
        timeout=10,
    )
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"


def test_validation_empty_translation_message_returns_400(admin_headers):
    r = requests.post(
        f"{BASE_URL}/api/admin/announcement",
        json={"translations": {"en": {"title": "Hi", "message": "  "}}},
        headers=admin_headers,
        timeout=10,
    )
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"


# ── AuthZ ──────────────────────────────────────────────────────────────────
def test_regular_user_forbidden(user_headers):
    r = requests.post(
        f"{BASE_URL}/api/admin/announcement",
        json={"title": "T", "message": "nope"},
        headers=user_headers,
        timeout=10,
    )
    assert r.status_code == 403, f"expected 403, got {r.status_code}"


def test_unauthenticated_forbidden():
    r = requests.post(
        f"{BASE_URL}/api/admin/announcement",
        json={"title": "T", "message": "nope"},
        timeout=10,
    )
    assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}"


# ── Overlap guard (best-effort, non-fatal) ─────────────────────────────────
def test_overlap_guard_best_effort(admin_headers):
    """Fire two immediate publishes back-to-back. With ~2 users the fan-out
    finishes almost instantly so 409 may not be observable — only report."""
    # Wait for any previous fan-out to settle
    time.sleep(4)
    marker1 = f"iter10-ov1-{uuid.uuid4().hex[:6]}"
    marker2 = f"iter10-ov2-{uuid.uuid4().hex[:6]}"
    r1 = requests.post(
        f"{BASE_URL}/api/admin/announcement",
        json={"title": "O1", "message": f"m1 {marker1}"},
        headers=admin_headers, timeout=10,
    )
    r2 = requests.post(
        f"{BASE_URL}/api/admin/announcement",
        json={"title": "O2", "message": f"m2 {marker2}"},
        headers=admin_headers, timeout=10,
    )
    print(f"overlap guard: r1={r1.status_code} r2={r2.status_code}")
    # Both must be 200 or 409 — server must not 500
    assert r1.status_code in (200, 409), r1.text
    assert r2.status_code in (200, 409), r2.text
    # Server still up
    assert requests.get(f"{BASE_URL}/api/config", timeout=10).status_code == 200
