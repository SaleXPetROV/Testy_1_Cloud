"""Iteration 8 — GET /api/admin/announcements pagination + translations exclusion."""
import os

import pytest
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values("/app/frontend/.env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = base_url.rstrip("/")

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    if r.status_code != 200:
        pytest.fail(f"admin login failed {r.status_code}: {r.text[:300]}")
    data = r.json()
    token = data.get("token") or data.get("access_token")
    if not token:
        pytest.fail(f"no token in login response: {data}")
    return token


@pytest.fixture(scope="module")
def client(admin_token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {admin_token}",
                      "Content-Type": "application/json"})
    return s


def _qa_titles(items):
    return [a.get("title") for a in items if str(a.get("title", "")).startswith("QA Announce")]


class TestAnnouncementsPagination:
    def test_limit_1_returns_newest_only(self, client):
        r = client.get(f"{BASE_URL}/api/admin/announcements?limit=1", timeout=30)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert "announcements" in data and "total" in data
        assert data["total"] == 3, f"expected total 3, got {data['total']}"
        assert len(data["announcements"]) == 1
        item = data["announcements"][0]
        assert item["title"] == "QA Announce 3", item
        assert "translations" not in item
        assert "_id" not in item

    def test_limit_100_returns_all_newest_first(self, client):
        r = client.get(f"{BASE_URL}/api/admin/announcements?limit=100", timeout=30)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert data["total"] == 3
        assert len(data["announcements"]) == 3
        assert _qa_titles(data["announcements"]) == ["QA Announce 3", "QA Announce 2", "QA Announce 1"]
        for a in data["announcements"]:
            assert "translations" not in a
            assert "_id" not in a
            assert a.get("id")

    def test_skip_offset(self, client):
        r = client.get(f"{BASE_URL}/api/admin/announcements?limit=1&skip=1", timeout=30)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert len(data["announcements"]) == 1
        assert data["announcements"][0]["title"] == "QA Announce 2"
        assert data["total"] == 3

    def test_default_no_params(self, client):
        r = client.get(f"{BASE_URL}/api/admin/announcements", timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data.get("announcements"), list)
        assert data["total"] == 3
        assert len(data["announcements"]) == 3

    def test_limit_clamped_above_100(self, client):
        r = client.get(f"{BASE_URL}/api/admin/announcements?limit=100000", timeout=30)
        assert r.status_code == 200, r.text[:300]
        assert len(r.json()["announcements"]) <= 100

    def test_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/admin/announcements?limit=1", timeout=30)
        assert r.status_code in (401, 403), r.status_code
