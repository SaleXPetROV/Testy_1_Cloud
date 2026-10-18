"""Backend tests for Roadmap + Idea Suggestions (Дорожная карта / 💡).

Covers:
- Public GET /api/roadmap (default ru + translated en)
- Admin CRUD: phase, item, footer
- POST /api/ideas (auth), 500-char limit, empty rejection
- Admin GET /api/admin/ideas
"""
import os
import time
import requests
import pytest

def _get_base_url():
    url = os.environ.get("REACT_APP_BACKEND_URL")
    if not url:
        # read from frontend/.env as fallback
        try:
            with open("/app/frontend/.env") as f:
                for line in f:
                    if line.startswith("REACT_APP_BACKEND_URL="):
                        url = line.split("=", 1)[1].strip()
                        break
        except Exception:
            pass
    assert url, "REACT_APP_BACKEND_URL not set"
    return url.rstrip("/")

BASE_URL = _get_base_url()

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PASSWORD = "Test1234!"


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": password}, timeout=20)
    assert r.status_code == 200, f"login {email} -> {r.status_code} {r.text[:200]}"
    data = r.json()
    tok = data.get("token") or data.get("access_token")
    assert tok, f"no token in login response: {data}"
    return tok


@pytest.fixture(scope="module")
def admin_token():
    return _login(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def user_token():
    return _login(USER_EMAIL, USER_PASSWORD)


@pytest.fixture(scope="module")
def admin_h(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def user_h(user_token):
    return {"Authorization": f"Bearer {user_token}", "Content-Type": "application/json"}


# ---------- Public roadmap ----------
class TestPublicRoadmap:
    def test_get_roadmap_ru(self):
        r = requests.get(f"{BASE_URL}/api/roadmap", timeout=20)
        assert r.status_code == 200
        d = r.json()
        assert "phases" in d and "footer_text" in d and "lang" in d
        assert d["lang"] == "ru"
        assert isinstance(d["phases"], list)
        # seed data: at least 2 phases with items
        assert len(d["phases"]) >= 1
        # inspect item shape
        for ph in d["phases"]:
            for it in ph.get("items", []):
                assert "id" in it and "text" in it and "done" in it

    def test_get_roadmap_en_translated(self):
        r = requests.get(f"{BASE_URL}/api/roadmap", params={"lang": "en"}, timeout=60)
        assert r.status_code == 200
        d = r.json()
        assert d["lang"] == "en"
        # allow LibreTranslate to be slow: retry once if all titles still cyrillic
        def _has_cyr(s):
            return any('\u0400' <= c <= '\u04FF' for c in (s or ""))
        titles = [p.get("title", "") for p in d["phases"]]
        if titles and all(_has_cyr(t) for t in titles):
            time.sleep(3)
            r = requests.get(f"{BASE_URL}/api/roadmap", params={"lang": "en"}, timeout=60)
            d = r.json()
            titles = [p.get("title", "") for p in d["phases"]]
        # at least one should look non-cyrillic (translated)
        assert any((t and not _has_cyr(t)) for t in titles), f"no titles translated: {titles}"


# ---------- Admin CRUD ----------
class TestAdminRoadmapCRUD:
    def test_admin_get_roadmap(self, admin_h):
        r = requests.get(f"{BASE_URL}/api/admin/roadmap", headers=admin_h, timeout=20)
        assert r.status_code == 200
        d = r.json()
        assert "phases" in d and "footer_text" in d

    def test_full_phase_and_item_lifecycle(self, admin_h):
        # CREATE phase
        r = requests.post(f"{BASE_URL}/api/admin/roadmap/phase",
                          headers=admin_h, json={"title": "TEST_Фаза"}, timeout=20)
        assert r.status_code == 200, r.text
        phase = r.json()
        pid = phase["id"]
        assert phase["title"] == "TEST_Фаза"

        # verify via GET admin
        r = requests.get(f"{BASE_URL}/api/admin/roadmap", headers=admin_h, timeout=20)
        assert any(p["id"] == pid for p in r.json()["phases"])

        # CREATE item
        r = requests.post(f"{BASE_URL}/api/admin/roadmap/item",
                          headers=admin_h,
                          json={"phase_id": pid, "text": "TEST_Пункт"}, timeout=20)
        assert r.status_code == 200, r.text
        item = r.json()
        iid = item["id"]
        assert item["done"] is False

        # TOGGLE done
        r = requests.put(f"{BASE_URL}/api/admin/roadmap/item/{iid}",
                         headers=admin_h, json={"done": True}, timeout=20)
        assert r.status_code == 200

        # verify persistence
        r = requests.get(f"{BASE_URL}/api/admin/roadmap", headers=admin_h, timeout=20)
        found_item = None
        for p in r.json()["phases"]:
            if p["id"] == pid:
                for it in p["items"]:
                    if it["id"] == iid:
                        found_item = it
        assert found_item and found_item["done"] is True

        # EDIT phase title
        r = requests.put(f"{BASE_URL}/api/admin/roadmap/phase/{pid}",
                         headers=admin_h, json={"title": "TEST_Фаза2"}, timeout=20)
        assert r.status_code == 200

        # EDIT item text
        r = requests.put(f"{BASE_URL}/api/admin/roadmap/item/{iid}",
                         headers=admin_h, json={"text": "TEST_Пункт2"}, timeout=20)
        assert r.status_code == 200

        # verify edits
        r = requests.get(f"{BASE_URL}/api/admin/roadmap", headers=admin_h, timeout=20)
        phases = {p["id"]: p for p in r.json()["phases"]}
        assert phases[pid]["title"] == "TEST_Фаза2"
        item2 = next(it for it in phases[pid]["items"] if it["id"] == iid)
        assert item2["text"] == "TEST_Пункт2"

        # DELETE item
        r = requests.delete(f"{BASE_URL}/api/admin/roadmap/item/{iid}",
                            headers=admin_h, timeout=20)
        assert r.status_code == 200
        r = requests.delete(f"{BASE_URL}/api/admin/roadmap/item/{iid}",
                            headers=admin_h, timeout=20)
        assert r.status_code == 404

        # DELETE phase
        r = requests.delete(f"{BASE_URL}/api/admin/roadmap/phase/{pid}",
                            headers=admin_h, timeout=20)
        assert r.status_code == 200
        r = requests.delete(f"{BASE_URL}/api/admin/roadmap/phase/{pid}",
                            headers=admin_h, timeout=20)
        assert r.status_code == 404

    def test_footer_update(self, admin_h):
        # capture current
        r = requests.get(f"{BASE_URL}/api/admin/roadmap", headers=admin_h, timeout=20)
        original = r.json().get("footer_text", "")

        new_text = "TEST_footer_" + str(int(time.time()))
        r = requests.put(f"{BASE_URL}/api/admin/roadmap/footer",
                         headers=admin_h, json={"text": new_text}, timeout=20)
        assert r.status_code == 200

        r = requests.get(f"{BASE_URL}/api/admin/roadmap", headers=admin_h, timeout=20)
        assert r.json()["footer_text"] == new_text

        # public /api/roadmap should reflect it (ru = untranslated)
        r = requests.get(f"{BASE_URL}/api/roadmap", timeout=20)
        assert r.json()["footer_text"] == new_text

        # restore
        r = requests.put(f"{BASE_URL}/api/admin/roadmap/footer",
                         headers=admin_h, json={"text": original}, timeout=20)
        assert r.status_code == 200

    def test_admin_endpoints_require_auth(self):
        # public route WITHOUT auth
        r = requests.get(f"{BASE_URL}/api/admin/roadmap", timeout=15)
        assert r.status_code in (401, 403)

    def test_regular_user_cannot_admin(self, user_h):
        r = requests.get(f"{BASE_URL}/api/admin/roadmap", headers=user_h, timeout=15)
        assert r.status_code in (401, 403)


# ---------- Ideas ----------
class TestIdeas:
    def test_submit_idea_ok(self, user_h):
        r = requests.post(f"{BASE_URL}/api/ideas", headers=user_h,
                          json={"text": "TEST_idea_" + str(int(time.time()))}, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json().get("success") is True

    def test_submit_empty_rejected(self, user_h):
        r = requests.post(f"{BASE_URL}/api/ideas", headers=user_h,
                          json={"text": "   "}, timeout=15)
        assert r.status_code == 400

    def test_submit_too_long_rejected(self, user_h):
        r = requests.post(f"{BASE_URL}/api/ideas", headers=user_h,
                          json={"text": "a" * 501}, timeout=15)
        assert r.status_code == 400

    def test_submit_at_limit_ok(self, user_h):
        r = requests.post(f"{BASE_URL}/api/ideas", headers=user_h,
                          json={"text": "TEST_" + "b" * 495}, timeout=30)
        assert r.status_code == 200

    def test_ideas_require_auth(self):
        r = requests.post(f"{BASE_URL}/api/ideas",
                         json={"text": "no auth"}, timeout=15)
        assert r.status_code in (401, 403)

    def test_admin_list_ideas(self, admin_h):
        r = requests.get(f"{BASE_URL}/api/admin/ideas", headers=admin_h, timeout=20)
        assert r.status_code == 200
        d = r.json()
        assert "ideas" in d and "total" in d
        # our just-submitted ideas should be listed
        assert d["total"] >= 1
        # verify TEST_ prefix idea persisted with expected fields
        test_ideas = [i for i in d["ideas"] if (i.get("text_original", "")).startswith("TEST_")]
        assert test_ideas, "no TEST_ ideas returned"
        sample = test_ideas[0]
        assert "user_id" in sample and "text_ru" in sample and "created_at" in sample
