"""Tests for the new chat photo endpoints in /app/backend/chat_handler.py.

Covers PHOTO-1, PHOTO-2, PHOTO-3 from the review request:

  * POST /api/chat/upload-photo — auth required, accepts PNG/JPEG/WEBP/GIF,
    rejects text with 400, rejects >3MB with 413, rejects unauthed with 401.
  * POST /api/chat/send — accepts optional image_url, requires content OR
    image_url, rejects http:// or non-https/non-data schemes with 400,
    persists image_url on the message doc, echoes it back in the response.
  * Text-only, image-only, text+image all succeed.

Uses the public REACT_APP_BACKEND_URL (external Kubernetes ingress) and the
seeded regular test user credentials.
"""
import base64
import io
import os
import struct
import time
import uuid
import zlib

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

# Load frontend env for the public backend URL (mimics what a real user hits).
load_dotenv("/app/frontend/.env")
load_dotenv("/app/backend/.env")

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

TEST_EMAIL = "testuser@example.com"
TEST_PASSWORD = "Test1234!"

TEST_TAG = f"TEST_photo_{uuid.uuid4().hex[:8]}"


# ---------- Helpers ----------

def _make_png(width: int = 4, height: int = 4) -> bytes:
    """Build a minimal valid PNG in-memory (no Pillow dependency)."""
    def _chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # RGB, 8-bit
    row = b"\x00" + b"\xff\x00\x00" * width  # filter byte + red pixels
    raw = row * height
    idat = zlib.compress(raw)
    return sig + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")


# ---------- Fixtures ----------

@pytest.fixture(scope="module")
def token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        timeout=15,
    )
    if r.status_code != 200:
        pytest.skip(f"login failed for {TEST_EMAIL}: {r.status_code} {r.text[:200]}")
    return r.json()["token"]


@pytest.fixture(scope="module")
def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def db():
    client = MongoClient(MONGO_URL)
    yield client[DB_NAME]
    client.close()


# ---------- PHOTO-1: /api/chat/upload-photo ----------

class TestUploadPhoto:
    URL = f"{BASE_URL}/api/chat/upload-photo"

    def test_upload_unauthenticated_returns_401(self):
        png = _make_png()
        r = requests.post(
            self.URL,
            files={"file": ("t.png", png, "image/png")},
            timeout=15,
        )
        assert r.status_code == 401, f"Expected 401, got {r.status_code}: {r.text[:200]}"

    def test_upload_png_returns_data_uri(self, auth_headers):
        png = _make_png()
        r = requests.post(
            self.URL,
            headers=auth_headers,
            files={"file": ("t.png", png, "image/png")},
            timeout=15,
        )
        assert r.status_code == 200, f"upload failed: {r.status_code} {r.text[:300]}"
        body = r.json()
        assert set(["url", "size", "content_type"]).issubset(body.keys())
        assert body["url"].startswith("data:image/"), body["url"][:60]
        assert body["content_type"].startswith("image/")
        assert body["size"] == len(png)
        # data URI must decode back to the same bytes.
        _, b64 = body["url"].split(",", 1)
        assert base64.b64decode(b64) == png

    def test_upload_non_image_text_returns_400(self, auth_headers):
        # Small delay so we don't collide with the previous test's rate-limit
        # window (chat_upload:<user_id>).
        time.sleep(0.2)
        r = requests.post(
            self.URL,
            headers=auth_headers,
            files={"file": ("evil.txt", b"hello world", "text/plain")},
            timeout=15,
        )
        assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.text[:200]}"

    def test_upload_over_3mb_returns_413(self, auth_headers):
        time.sleep(0.2)
        # 3.5MB of PNG-signature-prefixed junk. The size check runs before
        # the signature check, so this is enough to trigger 413.
        big = b"\x89PNG\r\n\x1a\n" + b"\x00" * (int(3.5 * 1024 * 1024))
        r = requests.post(
            self.URL,
            headers=auth_headers,
            files={"file": ("big.png", big, "image/png")},
            timeout=30,
        )
        assert r.status_code == 413, f"Expected 413, got {r.status_code}: {r.text[:200]}"

    def test_upload_mismatched_signature_rejected(self, auth_headers):
        """image/* content-type but the bytes aren't actually an image."""
        time.sleep(0.2)
        r = requests.post(
            self.URL,
            headers=auth_headers,
            files={"file": ("fake.png", b"not-an-image-just-bytes", "image/png")},
            timeout=15,
        )
        assert r.status_code == 400, f"Expected 400 on bad signature, got {r.status_code}: {r.text[:200]}"


# ---------- PHOTO-2/3: /api/chat/send ----------

class TestSendMessageWithImage:
    SEND_URL = f"{BASE_URL}/api/chat/send"
    UPLOAD_URL = f"{BASE_URL}/api/chat/upload-photo"

    @pytest.fixture(scope="class")
    def data_uri(self, auth_headers):
        r = requests.post(
            self.UPLOAD_URL,
            headers=auth_headers,
            files={"file": ("t.png", _make_png(), "image/png")},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        return r.json()["url"]

    def _payload(self, **overrides):
        p = {
            "content": "",
            "chat_type": "global",
            "city_id": None,
            "recipient_id": None,
            "image_url": None,
        }
        p.update(overrides)
        return p

    def test_send_empty_returns_400(self, auth_headers):
        time.sleep(0.2)
        r = requests.post(
            self.SEND_URL,
            headers=auth_headers,
            json=self._payload(),
            timeout=15,
        )
        assert r.status_code == 400, f"Expected 400 for empty message, got {r.status_code}: {r.text[:200]}"
        assert "empty" in r.text.lower()

    def test_send_http_scheme_rejected(self, auth_headers):
        time.sleep(0.2)
        r = requests.post(
            self.SEND_URL,
            headers=auth_headers,
            json=self._payload(image_url="http://evil.example.com/x.png"),
            timeout=15,
        )
        assert r.status_code == 400, f"Expected 400 for http://, got {r.status_code}: {r.text[:200]}"

    def test_send_javascript_scheme_rejected(self, auth_headers):
        time.sleep(0.2)
        r = requests.post(
            self.SEND_URL,
            headers=auth_headers,
            json=self._payload(image_url="javascript:alert(1)"),
            timeout=15,
        )
        assert r.status_code == 400, (
            f"Expected 400 for javascript: scheme, got {r.status_code}: {r.text[:200]}"
        )

    def test_send_text_only_succeeds(self, auth_headers, db):
        time.sleep(0.2)
        text = f"{TEST_TAG} text-only message"
        r = requests.post(
            self.SEND_URL,
            headers=auth_headers,
            json=self._payload(content=text),
            timeout=15,
        )
        assert r.status_code == 200, f"send failed: {r.status_code} {r.text[:300]}"
        msg = r.json()["message"]
        assert msg["content"] == text
        assert msg.get("image_url") is None
        # Cleanup so we can identify our test rows.
        db.chat_messages.delete_one({"id": msg["id"]})

    def test_send_image_only_succeeds_and_persists_image_url(
        self, auth_headers, data_uri, db
    ):
        time.sleep(0.2)
        r = requests.post(
            self.SEND_URL,
            headers=auth_headers,
            # No content — image-only.
            json=self._payload(image_url=data_uri),
            timeout=15,
        )
        assert r.status_code == 200, f"send failed: {r.status_code} {r.text[:300]}"
        body = r.json()
        msg = body["message"]
        # 1. Response echoes image_url.
        assert msg["image_url"] == data_uri
        # 2. Content is empty (blank string is fine — Field default is "").
        assert (msg.get("content") or "") == ""
        # 3. GET from Mongo → image_url actually persisted.
        stored = db.chat_messages.find_one({"id": msg["id"]}, {"_id": 0})
        assert stored is not None
        assert stored.get("image_url") == data_uri, (
            f"image_url not persisted: {stored.get('image_url')!r}"
        )
        # Cleanup.
        db.chat_messages.delete_one({"id": msg["id"]})

    def test_send_text_and_image_succeeds(
        self, auth_headers, data_uri, db
    ):
        time.sleep(0.2)
        caption = f"{TEST_TAG} caption with image"
        r = requests.post(
            self.SEND_URL,
            headers=auth_headers,
            json=self._payload(content=caption, image_url=data_uri),
            timeout=15,
        )
        assert r.status_code == 200, f"send failed: {r.status_code} {r.text[:300]}"
        msg = r.json()["message"]
        assert msg["content"] == caption
        assert msg["image_url"] == data_uri

        stored = db.chat_messages.find_one({"id": msg["id"]}, {"_id": 0})
        assert stored is not None
        assert stored.get("content") == caption
        assert stored.get("image_url") == data_uri
        db.chat_messages.delete_one({"id": msg["id"]})

    def test_https_image_url_accepted(self, auth_headers, db):
        """A plain https:// image URL (not a data URI) must be accepted."""
        time.sleep(0.2)
        https_url = "https://example.com/images/pic.png"
        r = requests.post(
            self.SEND_URL,
            headers=auth_headers,
            json=self._payload(content=f"{TEST_TAG} https link", image_url=https_url),
            timeout=15,
        )
        assert r.status_code == 200, f"https:// image_url rejected: {r.status_code} {r.text[:300]}"
        msg = r.json()["message"]
        assert msg["image_url"] == https_url
        db.chat_messages.delete_one({"id": msg["id"]})


# ---------- PHOTO-FRONTEND (code inspection) ----------

class TestChatPageRendersImageWithoutBubble:
    """Static inspection of ChatPage.jsx — the image branch must NOT wrap
    the <img> in the `p-3 rounded-xl bg-cyber-cyan/20 border ...` bubble."""

    CHAT_PAGE = "/app/frontend/src/pages/ChatPage.jsx"

    def test_image_branch_has_no_bubble_wrapper(self):
        with open(self.CHAT_PAGE, "r", encoding="utf-8") as fh:
            src = fh.read()

        # Locate the image render branch. Loose match keyed on the img selector.
        assert 'msg.image_url ?' in src or 'msg.image_url ? (' in src, (
            "Cannot find the image_url ternary in ChatPage.jsx"
        )
        idx = src.find("msg.image_url ?")
        # Chunk out the image branch — up to the `) : (` that opens the text branch.
        after = src[idx:]
        text_branch_start = after.find(") : (")
        image_branch = after[:text_branch_start] if text_branch_start != -1 else after
        # The image branch itself must not include the bubble CSS.
        assert "p-3 rounded-xl" not in image_branch, (
            "Image render branch still wraps the picture in the p-3 rounded-xl bubble — "
            "per product spec the photo must be bubble-less."
        )
        assert "bg-cyber-cyan/20" not in image_branch, (
            "Image branch still includes bg-cyber-cyan/20 background — bubble-less rule violated."
        )
        # Sanity: the <img> tag with rounded-lg IS present.
        assert "rounded-lg" in image_branch and "src={msg.image_url}" in image_branch

    def test_paperclip_and_hidden_input_and_preview_present(self):
        with open(self.CHAT_PAGE, "r", encoding="utf-8") as fh:
            src = fh.read()
        # Paperclip button handler.
        assert "handlePickPhoto" in src
        assert "handlePhotoFile" in src
        # Hidden file input for image uploads.
        assert 'type="file"' in src
        # Pending photo preview + a remove/dismiss control.
        assert "pendingPhoto" in src
