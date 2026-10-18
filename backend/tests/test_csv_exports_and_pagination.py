"""Backend tests (Jan 2026 iteration):
- TG-bot CSV export endpoint (GET /api/admin/telegram-bot-stats/export-csv)
- Transactions CSV export (POST /api/admin/transactions/export-csv) with BOM+sep hint
- Multi-language + single-language announcement still work after pagination refactor
- No backend crash / 500 in /var/log/supervisor/backend.err.log
"""
import csv
import io
import os
import time

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL not set"
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASS = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PASS = "Test1234!"

EXPECTED_TG_HEADERS = [
    "Chat ID", "Telegram User ID", "Username", "First Name",
    "Is Premium", "Bot Language", "First Activity", "Last Activity",
    "Linked Project ID", "Linked Username", "Linked Email", "Linked Display Name",
]

EXPECTED_TX_HEADERS = [
    "ID", "Date", "Type", "Status", "User", "Wallet/Email",
    "Amount TON", "Amount $CITY", "Business", "Plot", "Description",
]


# ---------- Fixtures ----------
@pytest.fixture(scope="session")
def admin_token():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=30)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="session")
def user_token():
    r = requests.post(f"{API}/auth/login", json={"email": USER_EMAIL, "password": USER_PASS}, timeout=30)
    assert r.status_code == 200, f"user login failed: {r.status_code} {r.text}"
    return r.json()["token"]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _parse_csv_body(body: str):
    """Verify BOM+sep hint prefix then parse rows. Returns list of rows."""
    assert body.startswith("\ufeff"), "Missing UTF-8 BOM at start"
    stripped = body[1:]
    assert stripped.startswith("sep=,\r\n"), f"Missing 'sep=,' hint. Got prefix: {stripped[:40]!r}"
    csv_content = stripped[len("sep=,\r\n"):]
    rows = list(csv.reader(io.StringIO(csv_content)))
    return rows


# ---------- TG-bot CSV export ----------
def test_tgbot_export_csv_no_auth():
    r = requests.get(f"{API}/admin/telegram-bot-stats/export-csv", timeout=15)
    assert r.status_code in (401, 403), f"Expected 401/403, got {r.status_code} {r.text[:200]}"


def test_tgbot_export_csv_regular_user_forbidden(user_token):
    r = requests.get(f"{API}/admin/telegram-bot-stats/export-csv",
                     headers=_hdr(user_token), timeout=15)
    assert r.status_code == 403, f"Expected 403, got {r.status_code} {r.text[:200]}"


def test_tgbot_export_csv_admin_ok(admin_token):
    r = requests.get(f"{API}/admin/telegram-bot-stats/export-csv",
                     headers=_hdr(admin_token), timeout=30)
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
    ct = r.headers.get("content-type", "")
    assert "text/csv" in ct.lower(), f"Wrong content-type: {ct}"

    # Preserve BOM: use r.content decoded as utf-8-sig? No - we need to inspect the raw
    body = r.content.decode("utf-8")
    rows = _parse_csv_body(body)
    assert len(rows) >= 1, "No rows returned"

    header = rows[0]
    assert header == EXPECTED_TG_HEADERS, f"Header mismatch: {header}"
    assert len(header) == 12, f"Expected 12 columns, got {len(header)}"

    # Every data row should have exactly 12 columns
    data_rows = rows[1:]
    assert len(data_rows) >= 3, f"Expected >=3 seeded rows, got {len(data_rows)}"
    for i, row in enumerate(data_rows):
        assert len(row) == 12, f"Row {i} has {len(row)} cols, not 12: {row}"

    # Check quoted fields: raw csv body (after BOM+hint) should have every field quoted.
    # csv.QUOTE_ALL will wrap every value in double quotes. Sanity check the first data line.
    csv_content = body[1 + len("sep=,\r\n"):]
    first_data_line = csv_content.split("\r\n")[1] if len(csv_content.split("\r\n")) > 1 else ""
    assert first_data_line.startswith('"'), f"Fields not quoted: {first_data_line[:80]}"
    assert '","' in first_data_line, f"Comma separator not found between quoted fields: {first_data_line[:80]}"

    # Verify pre-seeded chat_ids are present
    chat_ids = {row[0] for row in data_rows}
    for cid in ("100000001", "200000002", "300000003"):
        assert cid in chat_ids, f"Seeded chat_id {cid} missing. Present: {list(chat_ids)[:15]}"


# ---------- Transactions CSV export ----------
def test_transactions_export_csv_admin(admin_token):
    r = requests.post(
        f"{API}/admin/transactions/export-csv",
        headers=_hdr(admin_token),
        json={"filters": {"limit": 5}},
        timeout=30,
    )
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
    ct = r.headers.get("content-type", "")
    assert "text/csv" in ct.lower(), f"Wrong content-type: {ct}"

    body = r.content.decode("utf-8")
    rows = _parse_csv_body(body)
    assert len(rows) >= 1, "No rows returned"
    header = rows[0]
    assert header == EXPECTED_TX_HEADERS, f"Header mismatch: {header}"
    assert len(header) == 11, f"Expected 11 columns, got {len(header)}"

    # Every data row should have 11 columns too (if any data present)
    for i, row in enumerate(rows[1:]):
        assert len(row) == 11, f"Row {i} has {len(row)} cols, not 11: {row}"

    # Check quoted fields on header line
    csv_content = body[1 + len("sep=,\r\n"):]
    first_line = csv_content.split("\r\n")[0]
    assert first_line.startswith('"ID"'), f"Header not quoted: {first_line[:80]}"
    assert '","' in first_line, f"Comma separator not found: {first_line[:80]}"


def test_transactions_export_csv_no_auth():
    r = requests.post(f"{API}/admin/transactions/export-csv",
                      json={"filters": {"limit": 5}}, timeout=15)
    assert r.status_code in (401, 403)


# ---------- Announcement broadcast after pagination refactor ----------
_created_ids: list = []


def test_announcement_single_language_after_refactor(admin_token, user_token):
    payload = {
        "title": "TEST_pag_single",
        "message": "<b>single</b> lang broadcast",
        "buttons": [],
    }
    r = requests.post(f"{API}/admin/announcement", headers=_hdr(admin_token), json=payload, timeout=45)
    assert r.status_code in (200, 201), f"{r.status_code} {r.text}"
    body = r.json()
    aid = body.get("id") or body.get("_id") or body.get("announcement_id")
    if aid:
        _created_ids.append(aid)

    time.sleep(1.5)
    n = requests.get(f"{API}/notifications", headers=_hdr(user_token), timeout=15)
    assert n.status_code == 200
    notifs = n.json() if isinstance(n.json(), list) else n.json().get("notifications", [])
    found = [x for x in notifs if x.get("title") == "TEST_pag_single"]
    assert found, f"Single-lang notification not delivered. Titles: {[x.get('title') for x in notifs[:10]]}"


def test_announcement_multilang_after_refactor(admin_token, user_token):
    payload = {
        "translations": {
            "ru": {"title": "TEST_pag_multi_ru", "message": "<b>Русский</b> variant", "buttons": []},
            "gb": {"title": "TEST_pag_multi_en", "message": "<b>English</b> variant", "buttons": []},
        },
    }
    r = requests.post(f"{API}/admin/announcement", headers=_hdr(admin_token), json=payload, timeout=60)
    assert r.status_code in (200, 201), f"{r.status_code} {r.text}"
    body = r.json()
    assert body.get("status") == "published", body
    trs = body.get("translations") or {}
    assert "ru" in trs and "en" in trs and "gb" not in trs, f"Bad normalization: {list(trs.keys())}"

    aid = body.get("id") or body.get("_id") or body.get("announcement_id")
    if aid:
        _created_ids.append(aid)

    time.sleep(1.5)
    n = requests.get(f"{API}/notifications", headers=_hdr(user_token), timeout=15)
    assert n.status_code == 200
    notifs = n.json() if isinstance(n.json(), list) else n.json().get("notifications", [])
    # testuser has language ru → should get Russian variant
    ru_found = [x for x in notifs if x.get("title") == "TEST_pag_multi_ru"]
    assert ru_found, f"Russian variant not delivered. Titles: {[x.get('title') for x in notifs[:10]]}"
    assert "<b>Русский</b>" in (ru_found[0].get("message") or ""), f"Wrong msg: {ru_found[0]}"


def test_no_backend_exception_after_broadcast():
    """Look for Python tracebacks / '_publish_announcement' errors in backend.err.log
    that were written within the last ~2 minutes."""
    logf = "/var/log/supervisor/backend.err.log"
    if not os.path.exists(logf):
        pytest.skip(f"{logf} not present")
    try:
        with open(logf, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 30000))
            tail = f.read().decode("utf-8", errors="replace")
    except Exception as e:
        pytest.skip(f"Could not read log: {e}")

    lower = tail.lower()
    bad_markers = [
        "traceback (most recent call last)",
        "error in _publish_announcement",
        "error in _process_announcement_chunk",
    ]
    hits = [m for m in bad_markers if m in lower]
    assert not hits, f"Suspicious markers in backend.err.log tail: {hits}\n--- tail ---\n{tail[-2000:]}"


# ---------- Cleanup ----------
def test_delete_test_announcements(admin_token):
    if not _created_ids:
        pytest.skip("No announcement ids captured")
    for aid in _created_ids:
        r = requests.delete(f"{API}/admin/announcement/{aid}",
                            headers=_hdr(admin_token), timeout=15)
        assert r.status_code in (200, 204), f"Delete failed {aid}: {r.status_code} {r.text}"
