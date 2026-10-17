"""Tests for TON Connect manifest v6, icon v3, and zero-locked buy behavior."""
import os
import io
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # fallback: read from frontend env
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL"):
                    BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
    except Exception:
        pass

assert BASE_URL, "REACT_APP_BACKEND_URL required"


# ---------- TON Connect manifest v6 ----------
class TestTonConnectManifestV6:
    def test_get_manifest_v6(self):
        r = requests.get(f"{BASE_URL}/api/tonconnect-manifest-v6.json", timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("name") == "GRAM CITY", data
        assert "url" in data
        assert data.get("iconUrl", "").endswith("/api/tonconnect-icon-v3.png")
        assert "termsOfUseUrl" in data
        assert "privacyPolicyUrl" in data

    def test_head_manifest_v6(self):
        r = requests.head(f"{BASE_URL}/api/tonconnect-manifest-v6.json", timeout=15)
        assert r.status_code == 200, r.status_code

    @pytest.mark.parametrize("path", [
        "/api/tonconnect-manifest.json",
        "/api/tonconnect-manifest-v3.json",
        "/api/tonconnect-manifest-v4.json",
        "/api/tonconnect-manifest-v5.json",
    ])
    def test_old_manifest_paths_still_200(self, path):
        r = requests.get(f"{BASE_URL}{path}", timeout=15)
        assert r.status_code == 200, f"{path}: {r.status_code}"


# ---------- TON Connect icon v3 PNG ----------
class TestTonConnectIcon:
    @pytest.mark.parametrize("path", ["/api/tonconnect-icon-v3.png", "/api/tonconnect-icon.png"])
    def test_get_icon(self, path):
        r = requests.get(f"{BASE_URL}{path}", timeout=15)
        assert r.status_code == 200, r.status_code
        assert r.headers.get("content-type", "").startswith("image/png")
        assert r.headers.get("access-control-allow-origin") == "*"
        # PNG magic
        assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
        # Verify 512x512 by parsing IHDR
        # IHDR chunk width at bytes 16..20
        width = int.from_bytes(r.content[16:20], "big")
        height = int.from_bytes(r.content[20:24], "big")
        assert width == 512 and height == 512, f"{path} {width}x{height}"

    @pytest.mark.parametrize("path", ["/api/tonconnect-icon-v3.png", "/api/tonconnect-icon.png"])
    def test_head_icon_not_405(self, path):
        r = requests.head(f"{BASE_URL}{path}", timeout=15)
        assert r.status_code == 200, f"{path}: {r.status_code}"
        assert r.headers.get("content-type", "").startswith("image/png")


# ---------- Zero-locked buy gate ----------
class TestZeroLockedBuy:
    @pytest.fixture(scope="class")
    def token(self):
        r = requests.post(f"{BASE_URL}/api/auth/login",
                          json={"email": "testuser@example.com", "password": "Test1234!"},
                          timeout=15)
        assert r.status_code == 200, r.text
        return r.json()["token"]

    def _find_free_cell_with_pre(self, token):
        for x, y in [(12, 26), (11, 25), (10, 26), (13, 25), (11, 26), (12, 24)]:
            r = requests.get(f"{BASE_URL}/api/island/cell/{x}/{y}",
                             headers={"Authorization": f"Bearer {token}"}, timeout=15)
            if r.status_code == 200:
                d = r.json()
                if not d.get("owner") and d.get("pre_business"):
                    return x, y
        return 12, 26

    def test_zero_locked_returns_423(self, token):
        """Zero-locked must fire when presale allows the cell.
        Backend order: presale gate → zero-locked gate. Seed presale allowlist
        with the target cell so zero_locked is what we observe."""
        import asyncio, os
        from motor.motor_asyncio import AsyncIOMotorClient

        x, y = self._find_free_cell_with_pre(token)
        mongo_url = os.environ.get("MONGO_URL")
        db_name = os.environ.get("DB_NAME")
        assert mongo_url and db_name, "MONGO_URL/DB_NAME must be set for zero_locked test"

        async def setup_presale():
            c = AsyncIOMotorClient(mongo_url)
            db = c[db_name]
            existing = await db.admin_settings.find_one({"type": "presale"}, {"_id": 0})
            await db.admin_settings.update_one(
                {"type": "presale"},
                {"$set": {
                    "type": "presale",
                    "active": True,
                    "map_id": "ton_island",
                    "selected_plots": [{"x": x, "y": y}],
                    "buy_button_text": "",
                }},
                upsert=True,
            )
            return existing

        async def restore_presale(prev):
            c = AsyncIOMotorClient(mongo_url)
            db = c[db_name]
            if prev is None:
                await db.admin_settings.delete_one({"type": "presale"})
            else:
                await db.admin_settings.replace_one({"type": "presale"}, prev, upsert=True)

        prev = asyncio.get_event_loop().run_until_complete(setup_presale()) if False else None
        # simpler: run in a fresh loop
        prev = asyncio.new_event_loop().run_until_complete(setup_presale())
        try:
            r = requests.post(f"{BASE_URL}/api/island/buy/{x}/{y}",
                              headers={"Authorization": f"Bearer {token}"}, timeout=15)
            assert r.status_code == 423, f"got {r.status_code}: {r.text}"
            body = r.json()
            detail = body.get("detail", {})
            assert isinstance(detail, dict) and detail.get("code") == "zero_locked", detail
            assert "уровня 1" in detail.get("message", "") or "level 1" in detail.get("message", "").lower(), detail
        finally:
            asyncio.new_event_loop().run_until_complete(restore_presale(prev))
