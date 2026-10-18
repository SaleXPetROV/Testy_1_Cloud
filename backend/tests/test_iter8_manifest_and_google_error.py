"""Iteration 8 — verification of two code fixes + Telegram regression.

Covers:
  * TON Connect dynamic manifest endpoint (fix C): origin-derived url/iconUrl + icon reachable
  * Google callback error surfacing (fix A diagnostics): 401 detail includes Google's real reason
  * Google redirect_uri whitelist guard still intact (400 Invalid redirect_uri)
  * Regression: Telegram Mini App auth (choice_required -> create -> ok, tampered hash -> 401)
"""
import os
from urllib.parse import urlparse

import pytest
import requests
from dotenv import dotenv_values

from test_tg_miniapp_auth_resilience_iter_current import (
    API,
    BASE_URL,
    build_init_data,
    cleanup_tg,
)

_fe = dotenv_values("/app/frontend/.env")
ORIGIN = (os.environ.get("REACT_APP_BACKEND_URL") or _fe.get("REACT_APP_BACKEND_URL")).rstrip("/")


# ---------- fix C: TON Connect manifest ----------
class TestTonConnectManifest:
    @pytest.mark.parametrize("path", [
        "/api/tonconnect-manifest.json",
        "/api/tonconnect-manifest-v2.json",
        "/api/tonconnect-manifest-v3.json",
    ])
    def test_manifest_origin_and_icon(self, path):
        r = requests.get(f"{BASE_URL}{path}", timeout=30)
        assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text[:300]}"
        assert r.headers.get("content-type", "").startswith("application/json")
        data = r.json()
        assert data["url"] == ORIGIN, f"manifest url {data['url']} != request origin {ORIGIN}"
        assert data["iconUrl"] == f"{ORIGIN}/tonconnect-icon-v2.png"
        assert data["name"] == "GRAM CITY"
        assert data["termsOfUseUrl"] == f"{ORIGIN}/terms"
        assert data["privacyPolicyUrl"] == f"{ORIGIN}/privacy"
        # no hardcoded legacy domains anywhere
        blob = r.text
        assert "gramcity.games" not in blob
        assert urlparse(data["url"]).netloc == urlparse(ORIGIN).netloc

    def test_icon_url_is_reachable_image(self):
        manifest = requests.get(f"{BASE_URL}/api/tonconnect-manifest-v3.json", timeout=30).json()
        icon = requests.get(manifest["iconUrl"], timeout=30)
        assert icon.status_code == 200, f"icon unreachable: {icon.status_code}"
        ctype = icon.headers.get("content-type", "")
        assert ctype.startswith("image/"), f"icon content-type={ctype}"
        assert len(icon.content) > 1000
        assert icon.content[:8] == b"\x89PNG\r\n\x1a\n", "icon is not a real PNG"


# ---------- fix A: Google error surfacing ----------
class TestGoogleCallbackErrorSurfacing:
    @staticmethod
    def _call():
        return requests.post(
            f"{API}/auth/google/callback",
            json={"code": "fake_code", "redirect_uri": f"{ORIGIN}/auth/google/callback"},
            timeout=45,
        )

    def test_fake_code_returns_real_google_reason(self):
        r = self._call()
        detail = r.json().get("detail", "")
        assert "Failed to exchange authorization code with Google:" in detail, detail
        # must NOT be the old opaque message
        assert detail.strip() != "Failed to exchange authorization code"
        # dummy creds => Google replies invalid_client
        assert "invalid_client" in detail, f"expected invalid_client in detail: {detail}"
        assert "(" in detail and ")" in detail, f"expected error_description in detail: {detail}"

    def test_fake_code_status_is_401_not_500(self):
        """BUG: generic `except Exception` in google_callback swallows the HTTPException(401)
        and re-raises 500 'Auth error: 401: ...' (missing `except HTTPException: raise`)."""
        r = self._call()
        assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text[:400]}"
        assert not r.json().get("detail", "").startswith("Auth error:")

    def test_invalid_redirect_uri_rejected(self):
        r = requests.post(
            f"{API}/auth/google/callback",
            json={"code": "fake_code", "redirect_uri": "https://evil.com/auth/google/callback"},
            timeout=30,
        )
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text[:400]}"
        assert "Invalid redirect_uri" in r.json().get("detail", "")


# ---------- regression: Telegram Mini App auth ----------
class TestTelegramRegression:
    TG_ID = 918800771

    @classmethod
    def teardown_class(cls):
        cleanup_tg(cls.TG_ID)

    def test_full_flow(self):
        cleanup_tg(self.TG_ID)
        init_data = build_init_data(self.TG_ID, first_name="Iter8", username="iter8_tester")

        r1 = requests.post(f"{API}/auth/telegram/miniapp", json={"init_data": init_data}, timeout=30)
        assert r1.status_code == 200, f"{r1.status_code}: {r1.text[:300]}"
        d1 = r1.json()
        assert d1.get("status") == "choice_required", d1

        r2 = requests.post(f"{API}/auth/telegram/miniapp/create", json={"init_data": init_data}, timeout=30)
        assert r2.status_code == 200, f"{r2.status_code}: {r2.text[:300]}"
        d2 = r2.json()
        assert d2.get("access_token") or d2.get("token"), d2

        r3 = requests.post(f"{API}/auth/telegram/miniapp", json={"init_data": init_data}, timeout=30)
        assert r3.status_code == 200, f"{r3.status_code}: {r3.text[:300]}"
        d3 = r3.json()
        assert d3.get("status") == "ok", d3
        token = d3.get("access_token") or d3.get("token")
        assert token

        me = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"}, timeout=30)
        assert me.status_code == 200, f"{me.status_code}: {me.text[:300]}"
        me_data = me.json()
        # /api/auth/me exposes the telegram link via telegram_chat_id (no telegram_id field)
        assert str(me_data.get("telegram_chat_id")) == str(self.TG_ID), me_data
        assert me_data.get("telegram_linked") is True
        assert me_data.get("telegram_username") == "iter8_tester"

    def test_tampered_hash_rejected(self):
        init_data = build_init_data(self.TG_ID + 1, first_name="Bad", username="bad_iter8")
        tampered = init_data[:-4] + "dead"
        r = requests.post(f"{API}/auth/telegram/miniapp", json={"init_data": tampered}, timeout=30)
        assert r.status_code in (400, 401), f"{r.status_code}: {r.text[:300]}"
