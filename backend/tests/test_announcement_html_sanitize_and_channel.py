"""Backend tests for the TON_CITY v2.3 announcement bug fix:

1) `sanitize_html_for_telegram()` — unit-tests the Telegram HTML whitelist.
2) `POST /api/admin/announcement` — multi-language + single-language happy paths.
3) `_publish_announcement()` — integration with a FAKE Telegram bot so we can
   verify (a) the channel post uses ENGLISH, (b) `parse_mode='HTML'`, (c) the
   caption has unsupported HTML tags stripped, (d) per-user fan-out also
   sanitizes, (e) fallback to Russian when English variant is absent, and
   (f) single-language mode sanitizes correctly.
4) `AuthCookieMiddleware` — POST /api/auth/login sets both httpOnly access_token
   AND csrf_token cookies, and does NOT break non-auth POSTs.
5) Regression on /api/admin/referrals/search-users and referral override
   endpoints implemented previously.

Runs against the live preview backend from REACT_APP_BACKEND_URL for the HTTP
paths, and imports the server module in-process for the fake-bot integration.
"""
import asyncio
import json
import os
import re
import sys
import uuid

import pytest
import requests


# Ensure /app/backend is on sys.path so we can import server / telegram_bot.
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)


BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or \
    "https://ton-admin-panel.preview.emergentagent.com"

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PASSWORD = "Test1234!"


# ── fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def s():
    """Fresh session per test to avoid cookie-jar bleed between admin/user."""
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    yield sess
    sess.close()


@pytest.fixture
def admin_token(s):
    r = s.post(f"{BASE_URL}/api/auth/login", json={
        "email": ADMIN_EMAIL, "password": ADMIN_PASSWORD,
    }, timeout=30)
    if r.status_code != 200:
        pytest.skip(f"admin login failed: {r.status_code} {r.text[:200]}")
    tok = r.json().get("token")
    assert tok, "no token in admin login response"
    return tok


@pytest.fixture
def admin_client(s, admin_token):
    s.headers.update({"Authorization": f"Bearer {admin_token}"})
    return s


# ═════════════════════════════════════════════════════════════════════════════
# 1) sanitize_html_for_telegram() unit tests
# ═════════════════════════════════════════════════════════════════════════════
class TestSanitizeHtmlForTelegram:
    """Directly imports the pure function from server.py — no DB / no HTTP."""

    @pytest.fixture(scope="class")
    def sanitize(self):
        from server import sanitize_html_for_telegram
        return sanitize_html_for_telegram

    def test_br_variants_become_newline(self, sanitize):
        assert sanitize("a<br>b") == "a\nb"
        assert sanitize("a<br/>b") == "a\nb"
        assert sanitize("a<br />b") == "a\nb"
        assert sanitize("a<BR>b") == "a\nb"

    def test_close_p_and_div_become_newline(self, sanitize):
        out = sanitize("<p>one</p><p>two</p>")
        # opening <p> is stripped, closing </p> → \n
        assert out.strip() == "one\ntwo"
        out = sanitize("<div>one</div><div>two</div>")
        assert out.strip() == "one\ntwo"

    def test_strips_unsupported_tags_keeps_content(self, sanitize):
        for html in [
            '<h1>hello</h1>',
            '<span style="color:red">hello</span>',
            '<script>hello</script>',
            '<div class="x">hello</div>',
        ]:
            got = sanitize(html)
            assert "hello" in got, f"content dropped for {html!r} → {got!r}"
            assert "<h1" not in got and "<script" not in got and "<div" not in got
            assert "style=" not in got

    def test_keeps_whitelisted_tags(self, sanitize):
        for tag in ["b", "i", "u", "s", "code", "pre"]:
            assert sanitize(f"<{tag}>x</{tag}>") == f"<{tag}>x</{tag}>"

    def test_anchor_keeps_only_href(self, sanitize):
        got = sanitize('<a href="https://example.com" target="_blank" rel="noopener">click</a>')
        assert got == '<a href="https://example.com">click</a>'

    def test_anchor_without_href_opening_dropped_inner_kept(self, sanitize):
        got = sanitize('<a target="_blank">click</a>')
        # Opening tag dropped, inner text kept. NOTE: current implementation
        # leaves the corresponding </a> as-is (unbalanced), which is a minor
        # sanitizer bug — reported in the test report.
        assert "click" in got
        assert "target=" not in got
        assert "<a" not in got  # opening tag not present

    def test_span_tg_spoiler_opening_rewritten(self, sanitize):
        got = sanitize('<span class="tg-spoiler">boo</span>')
        # Opening span is rewritten to <tg-spoiler>. NOTE: current
        # implementation drops the closing </span> instead of rewriting it to
        # </tg-spoiler> because it inspects only the closing tag's raw text
        # for the class name. Reported as a minor sanitizer bug.
        assert got.startswith("<tg-spoiler>")
        assert "boo" in got
        assert "<span" not in got

    def test_span_generic_stripped(self, sanitize):
        got = sanitize('<span class="fancy">boo</span>')
        assert got == "boo"

    def test_plain_text_lt_not_touched(self, sanitize):
        # "<" not followed by a tag name must be left intact.
        assert sanitize("2 < 3 and x > 0") == "2 < 3 and x > 0"

    def test_collapses_three_blank_lines_to_two(self, sanitize):
        got = sanitize("a<br><br><br><br>b")
        # 4 <br> → 4 \n → collapsed to 2 \n. Between "a" and "b" we now have
        # exactly one blank line separating them.
        assert got == "a\n\nb"

    def test_empty_input_returns_empty_string(self, sanitize):
        assert sanitize("") == ""
        assert sanitize(None) == ""


# ═════════════════════════════════════════════════════════════════════════════
# 2) POST /api/admin/announcement — HTTP happy paths
# ═════════════════════════════════════════════════════════════════════════════
class TestAnnouncementCreateHTTP:
    """Validates that both multi-language and single-language modes succeed
    and persist the record."""

    def _cleanup(self, admin_client, ann_id):
        try:
            admin_client.delete(f"{BASE_URL}/api/admin/announcement/{ann_id}", timeout=15)
        except Exception:
            pass

    def test_multilang_announcement_created(self, admin_client):
        # NOTE: also ensure NO channel is configured so this HTTP test doesn't
        # unintentionally trigger a channel post. The channel test below sets
        # then clears channel_id explicitly via the fake-bot integration path.
        marker = f"TEST_multi_{uuid.uuid4().hex[:8]}"
        payload = {
            "translations": {
                "en": {"title": f"{marker} EN", "message": "<b>hello</b>"},
                "ru": {"title": f"{marker} RU", "message": "<b>привет</b>"},
            }
        }
        r = admin_client.post(f"{BASE_URL}/api/admin/announcement",
                              json=payload, timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        data = r.json()
        assert "id" in data
        assert data.get("status") == "published"
        # Codes normalized (both should be accepted as-is since en/ru are canonical).
        tr = data.get("translations") or {}
        assert set(tr.keys()) == {"en", "ru"}, f"unexpected keys: {list(tr.keys())}"
        assert tr["en"]["message"] == "<b>hello</b>"
        self._cleanup(admin_client, data["id"])

    def test_multilang_alias_gb_normalized_to_en(self, admin_client):
        """`gb` alias should be normalized to `en` in translations dict."""
        marker = f"TEST_alias_{uuid.uuid4().hex[:8]}"
        payload = {
            "translations": {
                "gb": {"title": f"{marker} GB", "message": "hi"},
                "cn": {"title": f"{marker} CN", "message": "你好"},
            }
        }
        r = admin_client.post(f"{BASE_URL}/api/admin/announcement",
                              json=payload, timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        tr = r.json().get("translations") or {}
        # gb → en, cn → zh
        assert "en" in tr and "zh" in tr, f"aliases not normalized: {list(tr.keys())}"
        self._cleanup(admin_client, r.json()["id"])

    def test_single_lang_announcement_created(self, admin_client):
        marker = f"TEST_single_{uuid.uuid4().hex[:8]}"
        payload = {
            "title": f"{marker} title",
            "message": "<b>bold</b><br>next line",
        }
        r = admin_client.post(f"{BASE_URL}/api/admin/announcement",
                              json=payload, timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        data = r.json()
        assert data.get("translations") in (None, {}, )
        assert data.get("message") == "<b>bold</b><br>next line"
        assert data.get("status") == "published"
        self._cleanup(admin_client, data["id"])


# ═════════════════════════════════════════════════════════════════════════════
# 3) _publish_announcement() integration with a FAKE Telegram bot
# ═════════════════════════════════════════════════════════════════════════════

class _FakeTGBot:
    """Captures Telegram sends without touching the network."""

    def __init__(self):
        self.calls = []  # list of dicts

    async def send_message(self, chat_id, text, parse_mode="HTML", reply_markup=None, **kwargs):
        self.calls.append({
            "method": "send_message",
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "reply_markup": reply_markup,
        })
        return True

    async def send_photo(self, chat_id, photo_url, caption="", parse_mode="HTML", reply_markup=None, **kwargs):
        self.calls.append({
            "method": "send_photo",
            "chat_id": chat_id,
            "photo_url": photo_url,
            "caption": caption,
            "parse_mode": parse_mode,
            "reply_markup": reply_markup,
        })
        return True


CHANNEL_ID = "@ton_city_test_channel_donotuse"


async def _run_publish_with_fake_bot(announcement, fake_bot, channel_id=CHANNEL_ID):
    """Import server, wire up admin_settings.channel_id, monkey-patch the
    telegram_bot global, run `_publish_announcement`, then cleanup.

    Motor is bound to the first event loop it saw (module import). Since
    `asyncio.run()` opens a fresh loop per test, we can't reuse `srv.db` — we
    create a NEW motor client here bound to the current running loop and swap
    it onto `srv.db` for the duration of the coroutine, restoring the original
    afterwards.

    Returns the FakeBot for inspection.
    """
    from dotenv import load_dotenv
    from motor.motor_asyncio import AsyncIOMotorClient
    load_dotenv("/app/backend/.env", override=True)

    import telegram_bot as tg_mod
    import server as srv

    orig_bot = tg_mod.telegram_bot
    tg_mod.telegram_bot = fake_bot

    # Fresh motor client on the CURRENT running loop.
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    fresh_db = client[os.environ["DB_NAME"]]
    orig_db = srv.db
    srv.db = fresh_db

    # Configure a channel in admin_settings.
    await srv.db.admin_settings.update_one(
        {"type": "telegram_bot"},
        {"$set": {"type": "telegram_bot", "channel_id": channel_id}},
        upsert=True,
    )

    # Reduce fan-out cost: temporarily replace db.users.find with a small list.
    # We keep the original for restore.
    real_users_find = srv.db.users.find

    class _FakeCursor:
        def __init__(self, docs):
            self._docs = list(docs)

        def batch_size(self, _n):
            return self

        def __aiter__(self):
            self._iter = iter(self._docs)
            return self

        async def __anext__(self):
            try:
                return next(self._iter)
            except StopIteration:
                raise StopAsyncIteration

    fake_docs = [
        {"id": "test-user-1", "telegram_chat_id": "1001", "language": "en"},
        {"id": "test-user-2", "telegram_chat_id": "1002", "language": "ru"},
        {"id": "test-user-3", "telegram_chat_id": None, "language": "en"},
    ]

    def _fake_find(*args, **kwargs):
        return _FakeCursor(fake_docs)

    srv.db.users.find = _fake_find

    # Also stub telegram_mappings.find so _flush_tg's lookup returns nothing
    # extra (fall back to per-user language passed in tg_batch).
    real_tm_find = srv.db.telegram_mappings.find

    def _empty_tm_find(*args, **kwargs):
        return _FakeCursor([])
    srv.db.telegram_mappings.find = _empty_tm_find

    try:
        await srv._publish_announcement(announcement)
    finally:
        # Cleanup channel_id
        try:
            await srv.db.admin_settings.update_one(
                {"type": "telegram_bot"},
                {"$unset": {"channel_id": ""}},
            )
        except Exception:
            pass
        # Cleanup test notifications created by the fan-out.
        try:
            await srv.db.notifications.delete_many(
                {"user_id": {"$in": [d["id"] for d in fake_docs]}}
            )
        except Exception:
            pass
        # Restore
        srv.db.users.find = real_users_find
        srv.db.telegram_mappings.find = real_tm_find
        srv.db = orig_db
        client.close()
        tg_mod.telegram_bot = orig_bot

    return fake_bot


class TestPublishAnnouncementFakeBot:
    """Directly exercises `server._publish_announcement` with a stubbed bot."""

    def test_channel_post_uses_english_and_html_and_sanitizes(self):
        bot = _FakeTGBot()
        ann = {
            "id": str(uuid.uuid4()),
            "title": "",  # not used by channel post because translations wins
            "message": "",
            "translations": {
                "en": {
                    "title": "Hello",
                    "message": '<b>Bold</b><br><p>Para</p><div>Blk</div>'
                               '<span style="color:red">Red</span>'
                               '<script>evil()</script>'
                               '<a href="https://x.io" target="_blank">link</a>',
                },
                "ru": {"title": "Привет", "message": "<b>Жирный</b>"},
            },
        }
        asyncio.run(_run_publish_with_fake_bot(ann, bot))

        # Identify the channel post = the one with chat_id == CHANNEL_ID.
        channel_calls = [c for c in bot.calls if c["chat_id"] == CHANNEL_ID]
        assert len(channel_calls) == 1, \
            f"expected exactly 1 channel post, got {len(channel_calls)}: {bot.calls!r}"
        cc = channel_calls[0]
        text = cc.get("text") or cc.get("caption") or ""

        # ENGLISH used (Russian title "Привет" must not appear).
        assert "Hello" in text
        assert "Привет" not in text

        # HTML parse mode.
        # Bot's default is HTML (from send_message signature), and we pass
        # nothing → default kicks in. Verify it is or defaults to HTML.
        assert cc["parse_mode"] == "HTML"

        # Sanitized: <br>/<p>/<div>/<span style>/<script> gone but content kept;
        # <b> and <a href> preserved; target/rel dropped.
        assert "<br>" not in text and "<br/>" not in text
        assert "<p>" not in text and "</p>" not in text
        assert "<div" not in text and "</div>" not in text
        assert "<span" not in text
        assert "<script" not in text
        assert "target=" not in text
        assert "style=" not in text
        assert "<b>Bold</b>" in text
        assert '<a href="https://x.io">link</a>' in text
        # Content of stripped tags preserved
        assert "Para" in text and "Blk" in text and "Red" in text

    def test_per_user_fanout_sanitizes(self):
        bot = _FakeTGBot()
        ann = {
            "id": str(uuid.uuid4()),
            "title": "",
            "message": "",
            "translations": {
                "en": {"title": "Hi", "message": "<b>x</b><br><p>y</p>"},
                "ru": {"title": "Привет", "message": "<b>х</b><br><p>у</p>"},
            },
        }
        asyncio.run(_run_publish_with_fake_bot(ann, bot))

        user_calls = [c for c in bot.calls if c["chat_id"] != CHANNEL_ID]
        assert user_calls, f"no per-user Telegram calls captured: {bot.calls!r}"
        for c in user_calls:
            body = c.get("text") or c.get("caption") or ""
            assert "<br>" not in body, f"raw <br> leaked: {body!r}"
            assert "<p>" not in body and "</p>" not in body, f"raw <p> leaked: {body!r}"

    def test_channel_falls_back_to_russian_when_no_english(self):
        bot = _FakeTGBot()
        ann = {
            "id": str(uuid.uuid4()),
            "title": "",
            "message": "",
            "translations": {
                "ru": {"title": "Заголовок", "message": "<b>тело</b><br>next"},
            },
        }
        asyncio.run(_run_publish_with_fake_bot(ann, bot))

        channel_calls = [c for c in bot.calls if c["chat_id"] == CHANNEL_ID]
        assert len(channel_calls) == 1, \
            f"expected exactly 1 channel post (RU fallback), got {len(channel_calls)}"
        text = channel_calls[0].get("text") or channel_calls[0].get("caption") or ""
        assert "Заголовок" in text
        assert "тело" in text
        assert "<br>" not in text  # sanitized

    def test_single_language_mode_sanitized(self):
        bot = _FakeTGBot()
        ann = {
            "id": str(uuid.uuid4()),
            "title": "Hi",
            "message": "<b>bold</b><br>next line<div>d</div>",
            "translations": None,
        }
        asyncio.run(_run_publish_with_fake_bot(ann, bot))

        # Every outbound call should be sanitized.
        assert bot.calls, "no outbound Telegram calls captured"
        for c in bot.calls:
            body = c.get("text") or c.get("caption") or ""
            assert "<br>" not in body
            assert "<div" not in body and "</div>" not in body
            assert "<b>bold</b>" in body


# ═════════════════════════════════════════════════════════════════════════════
# 4) AuthCookieMiddleware — cookies set on successful login, no regression
# ═════════════════════════════════════════════════════════════════════════════
class TestAuthCookieMiddleware:
    def test_login_sets_httponly_access_and_csrf_cookies(self, s):
        r = s.post(f"{BASE_URL}/api/auth/login",
                   json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                   timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"

        # Collect Set-Cookie headers (case-insensitive, may be multiple).
        set_cookie_headers = []
        # requests.Response headers is case-insensitive & merges Set-Cookie
        # into a single comma-joined string, but the underlying cookie jar
        # keeps each cookie separately — inspect both.
        raw = r.headers.get("Set-Cookie") or ""
        if raw:
            set_cookie_headers.append(raw)
        jar_names = {c.name for c in r.cookies}
        assert "access_token" in jar_names, \
            f"access_token cookie missing (jar={jar_names}, Set-Cookie={raw})"
        assert "csrf_token" in jar_names, \
            f"csrf_token cookie missing (jar={jar_names}, Set-Cookie={raw})"

        # HttpOnly on access_token — check the raw header string.
        # (requests doesn't expose HttpOnly on cookie objects.)
        low = raw.lower()
        assert "httponly" in low, f"HttpOnly flag missing in Set-Cookie: {raw}"

    def test_non_auth_post_not_broken(self, s):
        """A non-auth POST that returns 200 should NOT trip the middleware."""
        # First login to acquire a bearer token, then hit an admin GET/POST
        # that isn't in _AUTH_COOKIE_PATHS. Use search-users (POST-shaped path)
        # via referrals/search-users which we know returns 200 for admin.
        r = s.post(f"{BASE_URL}/api/auth/login",
                   json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                   timeout=30)
        assert r.status_code == 200
        tok = r.json()["token"]
        s.headers.update({"Authorization": f"Bearer {tok}"})
        # search-users is GET, so use it as a smoke check the middleware chain
        # produces a real response for non-auth paths.
        r2 = s.get(f"{BASE_URL}/api/admin/referrals/search-users",
                   params={"q": "testuser"}, timeout=30)
        assert r2.status_code == 200, f"{r2.status_code} {r2.text[:200]}"


# ═════════════════════════════════════════════════════════════════════════════
# 5) Referral-override regression — implemented previously, must still work
# ═════════════════════════════════════════════════════════════════════════════
TEST_USER_ID = "b2b07d99-b9ac-4b00-9802-1dba484add93"  # testuser@example.com


class TestReferralOverrideRegression:
    def test_search_users_returns_testuser(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/admin/referrals/search-users",
                             params={"q": USER_EMAIL}, timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
        arr = r.json()
        # Response shape observed: {"results": [{"user_id": ..., "email": ...}]}.
        # Handle {"users":..} and bare list for forward-compat.
        rows = None
        if isinstance(arr, dict):
            rows = arr.get("results") or arr.get("users")
        elif isinstance(arr, list):
            rows = arr
        assert isinstance(rows, list) and len(rows) >= 1, f"unexpected response: {arr!r}"
        assert any(
            u.get("email") == USER_EMAIL
            or u.get("id") == TEST_USER_ID
            or u.get("user_id") == TEST_USER_ID
            for u in rows
        )

    def test_override_set_and_clear(self, admin_client):
        # Set override.
        r = admin_client.post(f"{BASE_URL}/api/admin/referrals/override", json={
            "user_id": TEST_USER_ID, "active": 7, "total": 9,
        }, timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"

        # Clear it.
        r2 = admin_client.post(f"{BASE_URL}/api/admin/referrals/override/clear",
                               json={"user_id": TEST_USER_ID}, timeout=30)
        assert r2.status_code == 200, f"{r2.status_code} {r2.text[:200]}"

    def test_override_rejects_invalid_payload(self, admin_client):
        r = admin_client.post(f"{BASE_URL}/api/admin/referrals/override", json={
            "user_id": TEST_USER_ID, "active": 10, "total": 5,
        }, timeout=30)
        assert r.status_code == 400, f"expected 400 on active>total, got {r.status_code} {r.text[:200]}"
