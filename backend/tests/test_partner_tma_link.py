"""Backend tests for the new TMA referral-link generation in Partner Programs.

Covers:
  - POST /api/admin/partner-programs/generate-tma-link (pure generation)
  - POST /api/admin/partner-programs (create with tma_base_url persists tma_ref_url)
  - POST /api/admin/partner-programs/{id}/tma-link (save on existing program)
  - GET  /api/admin/partner-programs (list reflects persisted tma_ref_url)
  - DELETE /api/admin/partner-programs/{id} (cleanup)
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")
TEST_USER_ID = "6fe3ae7d-8dea-48c6-8d7c-85a743f59143"
WEB_REF = f"https://gcapp.games/?ref={TEST_USER_ID}"
WEB_REF_2 = "https://gcapp.games/?ref=37ee3eee-b28c-422d-aa9f-08003778908d"
TMA_BASE_APP = "https://t.me/GramCityBot/app"
TMA_BASE_GAME = "https://t.me/GramCityBot/game"


@pytest.fixture(scope="module")
def admin_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=30,
    )
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text[:200]}"
    token = r.json().get("token")
    assert token, "no token returned"
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


# ─── generate-tma-link (pure generation) ────────────────────────────────────

class TestGenerateTmaLink:
    def test_generate_from_web_ref(self, admin_client):
        r = admin_client.post(
            f"{BASE_URL}/api/admin/partner-programs/generate-tma-link",
            json={"web_ref_url": WEB_REF_2, "tma_base_url": TMA_BASE_APP},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ref_id"] == "37ee3eee-b28c-422d-aa9f-08003778908d"
        assert data["tma_ref_url"] == (
            "https://t.me/GramCityBot/app?startapp=37ee3eee-b28c-422d-aa9f-08003778908d"
        )

    def test_generate_from_tma_link(self, admin_client):
        already_tma = (
            "https://t.me/GramCityBot/app?startapp=37ee3eee-b28c-422d-aa9f-08003778908d"
        )
        r = admin_client.post(
            f"{BASE_URL}/api/admin/partner-programs/generate-tma-link",
            json={"web_ref_url": already_tma, "tma_base_url": TMA_BASE_APP},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ref_id"] == "37ee3eee-b28c-422d-aa9f-08003778908d"
        assert data["tma_ref_url"] == already_tma

    def test_generate_without_ref_returns_400(self, admin_client):
        r = admin_client.post(
            f"{BASE_URL}/api/admin/partner-programs/generate-tma-link",
            json={"web_ref_url": "https://gcapp.games/", "tma_base_url": TMA_BASE_APP},
        )
        assert r.status_code == 400, r.text
        detail = (r.json() or {}).get("detail", "")
        # Russian message about ?ref / startapp not found
        assert "ref" in detail.lower() or "startapp" in detail.lower() or "не найден" in detail


# ─── create + persist / save-on-existing / list / delete ────────────────────

class TestCreateAndSaveTma:
    def test_full_flow(self, admin_client):
        # CREATE with tma_base_url — must persist tma_ref_url
        create_payload = {
            "name": "TEST_TMA_QA",
            "ref_link": WEB_REF,
            "tma_base_url": TMA_BASE_APP,
        }
        r = admin_client.post(
            f"{BASE_URL}/api/admin/partner-programs", json=create_payload
        )
        assert r.status_code == 200, r.text
        program = r.json()["program"]
        program_id = program["id"]
        expected_app = f"{TMA_BASE_APP}?startapp={TEST_USER_ID}"

        try:
            assert program["tma_base_url"] == TMA_BASE_APP
            assert program["tma_ref_url"] == expected_app

            # GET list — must include our program with the persisted tma_ref_url
            r2 = admin_client.get(f"{BASE_URL}/api/admin/partner-programs")
            assert r2.status_code == 200, r2.text
            programs = r2.json()["programs"]
            found = next((p for p in programs if p["id"] == program_id), None)
            assert found is not None, "created program missing from list"
            assert found["tma_ref_url"] == expected_app
            assert found["tma_base_url"] == TMA_BASE_APP

            # SAVE new base on the existing program → refreshed tma_ref_url
            r3 = admin_client.post(
                f"{BASE_URL}/api/admin/partner-programs/{program_id}/tma-link",
                json={"tma_base_url": TMA_BASE_GAME},
            )
            assert r3.status_code == 200, r3.text
            body = r3.json()
            expected_game = f"{TMA_BASE_GAME}?startapp={TEST_USER_ID}"
            assert body["tma_ref_url"] == expected_game
            assert body["ref_id"] == TEST_USER_ID
            assert body["program"]["tma_base_url"] == TMA_BASE_GAME
            assert body["program"]["tma_ref_url"] == expected_game

            # Verify persistence via GET
            r4 = admin_client.get(f"{BASE_URL}/api/admin/partner-programs")
            assert r4.status_code == 200
            programs = r4.json()["programs"]
            found = next((p for p in programs if p["id"] == program_id), None)
            assert found is not None
            assert found["tma_ref_url"] == expected_game
            assert found["tma_base_url"] == TMA_BASE_GAME
        finally:
            # CLEANUP
            rd = admin_client.delete(
                f"{BASE_URL}/api/admin/partner-programs/{program_id}"
            )
            assert rd.status_code in (200, 204), rd.text
