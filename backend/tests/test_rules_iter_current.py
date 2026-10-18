"""Backend tests for game rules feature (/api/admin/rules & /api/rules).

Covers:
 - Admin CRUD (POST/GET/PUT/DELETE) auth-gated
 - Public GET returns raw text for ru and translated text for en
 - HTML tags including <img data:...> are preserved after translation
"""
import os
import re
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or \
           os.environ.get("EXTERNAL_URL", "").rstrip("/")

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PW = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PW = "Test1234!"

PNG_1x1_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)
IMG_TAG = f'<img src="data:image/png;base64,{PNG_1x1_B64}" alt="logo"/>'


def _login(email, pw):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, f"login failed {email}: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_token():
    return _login(ADMIN_EMAIL, ADMIN_PW)


@pytest.fixture(scope="module")
def user_token():
    return _login(USER_EMAIL, USER_PW)


@pytest.fixture(scope="module")
def admin_h(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="module")
def user_h(user_token):
    return {"Authorization": f"Bearer {user_token}"}


class TestRulesAdminAuth:
    def test_admin_endpoints_require_admin(self, user_h):
        # non-admin token
        r = requests.get(f"{BASE_URL}/api/admin/rules", headers=user_h, timeout=30)
        assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code} {r.text[:200]}"

    def test_admin_endpoints_no_token(self):
        r = requests.get(f"{BASE_URL}/api/admin/rules", timeout=30)
        assert r.status_code in (401, 403)


class TestRulesCrud:
    created_id = None

    def test_create_rule(self, admin_h):
        payload = {
            "title": "Основные правила",
            "content_html": f"<b>Привет мир</b> — это <i>правила</i>. {IMG_TAG}",
        }
        r = requests.post(f"{BASE_URL}/api/admin/rules", json=payload, headers=admin_h, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "id" in data and data["title"] == "Основные правила"
        assert IMG_TAG in data["content_html"]
        TestRulesCrud.created_id = data["id"]

    def test_admin_list_contains_rule(self, admin_h):
        r = requests.get(f"{BASE_URL}/api/admin/rules", headers=admin_h, timeout=30)
        assert r.status_code == 200
        ids = [x.get("id") for x in r.json().get("rules", [])]
        assert TestRulesCrud.created_id in ids

    def test_public_get_ru_unchanged(self):
        r = requests.get(f"{BASE_URL}/api/rules?lang=ru", timeout=30)
        assert r.status_code == 200
        rules = r.json().get("rules", [])
        found = next((x for x in rules if x["id"] == TestRulesCrud.created_id), None)
        assert found is not None
        assert "Привет мир" in found["content_html"]
        assert IMG_TAG in found["content_html"]

    def test_public_get_en_translated_preserves_img(self):
        # translation via emergent may take a while
        r = requests.get(f"{BASE_URL}/api/rules?lang=en", timeout=90)
        assert r.status_code == 200
        rules = r.json().get("rules", [])
        found = next((x for x in rules if x["id"] == TestRulesCrud.created_id), None)
        assert found is not None, "created rule missing in en response"
        html = found["content_html"]
        # img tag & data URI preserved
        assert 'data:image/png;base64' in html, f"img data URI stripped: {html[:400]}"
        assert re.search(r"<img[^>]*>", html), f"img tag missing: {html[:400]}"
        # formatting tags preserved
        assert "<b>" in html and "</b>" in html
        assert "<i>" in html and "</i>" in html
        # text actually translated (differs from ru)
        assert "Привет мир" not in html, f"text was not translated: {html[:400]}"

    def test_update_rule(self, admin_h):
        rid = TestRulesCrud.created_id
        r = requests.put(
            f"{BASE_URL}/api/admin/rules/{rid}",
            json={"title": "Обновлено", "content_html": f"<u>новый</u> {IMG_TAG}"},
            headers=admin_h, timeout=30,
        )
        assert r.status_code == 200
        # Verify persistence via admin list
        r2 = requests.get(f"{BASE_URL}/api/admin/rules", headers=admin_h, timeout=30)
        row = next(x for x in r2.json()["rules"] if x["id"] == rid)
        assert row["title"] == "Обновлено"
        assert "<u>новый</u>" in row["content_html"]

    def test_delete_rule(self, admin_h):
        rid = TestRulesCrud.created_id
        r = requests.delete(f"{BASE_URL}/api/admin/rules/{rid}", headers=admin_h, timeout=30)
        assert r.status_code == 200
        # gone
        r2 = requests.get(f"{BASE_URL}/api/admin/rules", headers=admin_h, timeout=30)
        ids = [x.get("id") for x in r2.json().get("rules", [])]
        assert rid not in ids

    def test_delete_non_existent(self, admin_h):
        r = requests.delete(f"{BASE_URL}/api/admin/rules/does-not-exist", headers=admin_h, timeout=30)
        assert r.status_code == 404

    def test_create_empty_content_rejected(self, admin_h):
        r = requests.post(f"{BASE_URL}/api/admin/rules", json={"title": "x", "content_html": ""}, headers=admin_h, timeout=30)
        assert r.status_code == 400
