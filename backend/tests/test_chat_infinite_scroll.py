"""Backend tests for chat infinite-scroll pagination (cursor: ?before=<created_at>).

Covers three endpoints:
  * GET /api/chat/messages/global?limit=50&before=<ts>
  * GET /api/chat/messages/city/{city_id}?limit=50&before=<ts>
  * GET /api/chat/messages/private/{user_id}?limit=50&before=<ts>

Focus: private endpoint must NOT mark inbound messages as read when called
with a `before` cursor (only the first page — no cursor — marks as read).
"""
import os
import time
import uuid

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/frontend/.env")
load_dotenv("/app/backend/.env")

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PASSWORD = "Test1234!"

TEST_TAG = f"TEST_scroll_{uuid.uuid4().hex[:6]}"


def _login(email, password):
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        timeout=15,
    )
    if r.status_code != 200:
        pytest.skip(f"login failed for {email}: {r.status_code} {r.text[:200]}")
    body = r.json()
    return body["token"], body.get("user", {})


@pytest.fixture(scope="module")
def db():
    client = MongoClient(MONGO_URL)
    yield client[DB_NAME]
    client.close()


@pytest.fixture(scope="module")
def user_auth():
    token, user = _login(USER_EMAIL, USER_PASSWORD)
    return {"token": token, "user": user, "headers": {"Authorization": f"Bearer {token}"}}


@pytest.fixture(scope="module")
def admin_auth():
    token, user = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    return {"token": token, "user": user, "headers": {"Authorization": f"Bearer {token}"}}


# ==================== GLOBAL PAGINATION ====================

class TestGlobalPagination:
    def _seed(self, headers, n, tag):
        """Seed N global messages; return count actually sent."""
        sent = 0
        for i in range(n):
            r = requests.post(
                f"{BASE_URL}/api/chat/send",
                headers=headers,
                json={"content": f"{tag} msg {i}", "chat_type": "global"},
                timeout=15,
            )
            if r.status_code == 200:
                sent += 1
            elif r.status_code == 429:
                # Rate limited — back off a bit
                time.sleep(1.2)
            # small spacing so created_at ordering is monotonic
            time.sleep(0.05)
        return sent

    def test_global_limit_50_and_before_cursor(self, user_auth, db):
        tag = f"{TEST_TAG}_g"
        try:
            self._seed(user_auth["headers"], 60, tag)

            # First page — newest 50
            r1 = requests.get(f"{BASE_URL}/api/chat/messages/global?limit=50", timeout=15)
            assert r1.status_code == 200
            page1 = r1.json()["messages"]
            assert len(page1) <= 50, f"limit=50 returned {len(page1)} messages"
            # Sorted ascending (server reverses after DESC fetch)
            times1 = [m["created_at"] for m in page1]
            assert times1 == sorted(times1), "page1 must be ascending"

            # Cursor with `before` = created_at of the OLDEST (page1[0])
            oldest_ts = page1[0]["created_at"]
            r2 = requests.get(
                f"{BASE_URL}/api/chat/messages/global?limit=50&before={oldest_ts}",
                timeout=15,
            )
            assert r2.status_code == 200
            page2 = r2.json()["messages"]
            # Every returned message must be strictly older than the cursor
            for m in page2:
                assert m["created_at"] < oldest_ts, (
                    f"got message with created_at={m['created_at']} >= cursor {oldest_ts}"
                )
            # And no overlap by id
            ids1 = {m["id"] for m in page1}
            for m in page2:
                assert m["id"] not in ids1

        finally:
            db.chat_messages.delete_many({"content": {"$regex": f"^{tag}"}})


# ==================== CITY PAGINATION ====================

class TestCityPagination:
    def test_city_limit_and_before_cursor(self, user_auth, db):
        # Pick any existing city
        r_cities = requests.get(f"{BASE_URL}/api/cities", timeout=15)
        if r_cities.status_code != 200:
            pytest.skip("cannot fetch cities")
        cities = r_cities.json().get("cities") or []
        if not cities:
            pytest.skip("no cities available")
        city_id = cities[0]["id"]

        tag = f"{TEST_TAG}_c"
        try:
            # Seed 55 messages
            for i in range(55):
                r = requests.post(
                    f"{BASE_URL}/api/chat/send",
                    headers=user_auth["headers"],
                    json={"content": f"{tag} c{i}", "chat_type": "city", "city_id": city_id},
                    timeout=15,
                )
                if r.status_code == 429:
                    time.sleep(1.2)
                time.sleep(0.05)

            r1 = requests.get(
                f"{BASE_URL}/api/chat/messages/city/{city_id}?limit=50", timeout=15
            )
            assert r1.status_code == 200
            page1 = r1.json()["messages"]
            assert len(page1) <= 50
            if not page1:
                pytest.skip("no messages seeded (possibly all rate-limited)")

            oldest_ts = page1[0]["created_at"]
            r2 = requests.get(
                f"{BASE_URL}/api/chat/messages/city/{city_id}?limit=50&before={oldest_ts}",
                timeout=15,
            )
            assert r2.status_code == 200
            for m in r2.json()["messages"]:
                assert m["created_at"] < oldest_ts

        finally:
            db.chat_messages.delete_many({"content": {"$regex": f"^{tag}"}})


# ==================== PRIVATE PAGINATION + is_read invariant ====================

class TestPrivatePaginationAndIsRead:
    def test_private_before_does_not_mark_as_read(self, user_auth, admin_auth, db):
        """Private endpoint: calling with ?before=<ts> must NOT flip is_read
        for messages received by the caller."""
        me = user_auth["user"]
        other = admin_auth["user"]
        assert me.get("id") and other.get("id"), "missing user ids"

        tag = f"{TEST_TAG}_p"
        try:
            # OTHER (admin) sends 3 messages to ME (testuser). Recipient=me.
            for i in range(3):
                r = requests.post(
                    f"{BASE_URL}/api/chat/send",
                    headers=admin_auth["headers"],
                    json={
                        "content": f"{tag} p{i}",
                        "chat_type": "private",
                        "recipient_id": me["id"],
                    },
                    timeout=15,
                )
                if r.status_code == 429:
                    time.sleep(1.2)
                time.sleep(0.05)

            # Verify they are unread initially in DB
            unread_before = db.chat_messages.count_documents({
                "chat_type": "private",
                "recipient_id": me["id"],
                "sender_id": other["id"],
                "content": {"$regex": f"^{tag}"},
                "is_read": False,
            })
            assert unread_before >= 1, "expected at least one unread test message"

            # Fetch WITH before cursor set in the future — every seeded
            # message is older than "now" — expect pagination to return them.
            future_ts = "9999-12-31T00:00:00+00:00"
            r_paged = requests.get(
                f"{BASE_URL}/api/chat/messages/private/{other['id']}"
                f"?limit=50&before={future_ts}",
                headers=user_auth["headers"],
                timeout=15,
            )
            assert r_paged.status_code == 200, r_paged.text[:300]

            # After a "load older" (`before` present) — messages must STILL be unread.
            unread_after = db.chat_messages.count_documents({
                "chat_type": "private",
                "recipient_id": me["id"],
                "sender_id": other["id"],
                "content": {"$regex": f"^{tag}"},
                "is_read": False,
            })
            assert unread_after == unread_before, (
                f"is_read leak: before={unread_before}, after={unread_after} — "
                "load-older must not mark messages as read"
            )

            # Now the FIRST page (no cursor) SHOULD mark them as read.
            r_first = requests.get(
                f"{BASE_URL}/api/chat/messages/private/{other['id']}?limit=50",
                headers=user_auth["headers"],
                timeout=15,
            )
            assert r_first.status_code == 200
            time.sleep(0.3)
            unread_after_first = db.chat_messages.count_documents({
                "chat_type": "private",
                "recipient_id": me["id"],
                "sender_id": other["id"],
                "content": {"$regex": f"^{tag}"},
                "is_read": False,
            })
            assert unread_after_first == 0, (
                f"first-page fetch should mark unread=0, still {unread_after_first}"
            )

        finally:
            db.chat_messages.delete_many({"content": {"$regex": f"^{tag}"}})

    def test_private_before_cursor_filters_older(self, user_auth, admin_auth, db):
        me = user_auth["user"]
        other = admin_auth["user"]
        tag = f"{TEST_TAG}_pf"
        try:
            for i in range(4):
                requests.post(
                    f"{BASE_URL}/api/chat/send",
                    headers=user_auth["headers"],
                    json={
                        "content": f"{tag} u{i}",
                        "chat_type": "private",
                        "recipient_id": other["id"],
                    },
                    timeout=15,
                )
                time.sleep(0.1)

            r1 = requests.get(
                f"{BASE_URL}/api/chat/messages/private/{other['id']}?limit=50",
                headers=user_auth["headers"],
                timeout=15,
            )
            assert r1.status_code == 200
            msgs = r1.json()["messages"]
            ours = [m for m in msgs if m.get("content", "").startswith(tag)]
            if len(ours) < 2:
                pytest.skip("could not seed enough private messages")

            cursor = ours[-1]["created_at"]  # newest of our test batch
            r2 = requests.get(
                f"{BASE_URL}/api/chat/messages/private/{other['id']}"
                f"?limit=50&before={cursor}",
                headers=user_auth["headers"],
                timeout=15,
            )
            assert r2.status_code == 200
            for m in r2.json()["messages"]:
                assert m["created_at"] < cursor
        finally:
            db.chat_messages.delete_many({"content": {"$regex": f"^{tag}"}})
