"""
Tests for admin business delete cascade (frees plot fully).
Endpoint: DELETE /api/admin/players/{player_id}/business/{business_id}
"""
import os
import uuid
import pytest
import requests
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PASSWORD = "Test1234!"


@pytest.fixture(scope="module")
def mongo():
    client = MongoClient(MONGO_URL)
    yield client[DB_NAME]
    client.close()


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=20)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_token():
    return _login(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def user_token():
    return _login(USER_EMAIL, USER_PASSWORD)


@pytest.fixture(scope="module")
def player(mongo):
    u = mongo.users.find_one({"email": USER_EMAIL}, {"_id": 0})
    assert u, "test user not seeded"
    return u


def _seed(mongo, player_id, with_plot_id_on_biz=True):
    """Seed occupied plot + linked business. Returns (plot_id, business_id)."""
    plot_id = f"TEST_plot_{uuid.uuid4().hex[:10]}"
    business_id = f"TEST_biz_{uuid.uuid4().hex[:10]}"
    mongo.plots.insert_one({
        "id": plot_id,
        "x": 999, "y": 999,
        "is_occupied": True,
        "is_available": False,
        "is_empty": False,
        "owner": player_id,
        "owner_id": player_id,
        "owner_username": "testuser",
        "business_id": business_id,
        "business_type": "trial_center",
        "building": {"type": "trial_center", "level": 1},
        "business": {"id": business_id, "business_type": "trial_center"},
    })
    biz_doc = {
        "id": business_id,
        "owner": player_id,
        "business_type": "trial_center",
        "level": 1,
    }
    if with_plot_id_on_biz:
        biz_doc["plot_id"] = plot_id
    mongo.businesses.insert_one(biz_doc)
    return plot_id, business_id


def _cleanup(mongo, plot_id, business_id):
    mongo.plots.delete_one({"id": plot_id})
    mongo.businesses.delete_one({"id": business_id})


def test_admin_delete_cascades_and_frees_plot(mongo, admin_token, player):
    plot_id, business_id = _seed(mongo, player["id"], with_plot_id_on_biz=True)
    try:
        r = requests.delete(
            f"{BASE_URL}/api/admin/players/{player['id']}/business/{business_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=30,
        )
        assert r.status_code == 200, f"expected 200, got {r.status_code} {r.text}"
        body = r.json()
        assert body.get("plot_freed") is True
        assert body.get("cascade", {}).get("plots_touched", 0) >= 1

        # Business gone
        assert mongo.businesses.find_one({"id": business_id}) is None

        # Plot fully reset
        plot = mongo.plots.find_one({"id": plot_id})
        assert plot is not None
        assert plot.get("is_occupied") is False
        assert plot.get("is_available") is True
        assert plot.get("is_empty") is True
        for f in ("owner", "owner_id", "owner_username", "business_id",
                  "business", "business_type", "building"):
            assert plot.get(f) is None, f"plot.{f} should be null, got {plot.get(f)!r}"
    finally:
        _cleanup(mongo, plot_id, business_id)


def test_defence_in_depth_business_id_only_link(mongo, admin_token, player):
    """Business has no plot_id, but plot references business_id -> still freed."""
    plot_id, business_id = _seed(mongo, player["id"], with_plot_id_on_biz=False)
    try:
        r = requests.delete(
            f"{BASE_URL}/api/admin/players/{player['id']}/business/{business_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=30,
        )
        assert r.status_code == 200, f"expected 200, got {r.status_code} {r.text}"
        body = r.json()
        assert body.get("plot_freed") is True
        assert body.get("cascade", {}).get("plots_touched", 0) >= 1

        plot = mongo.plots.find_one({"id": plot_id})
        assert plot.get("is_occupied") is False
        assert plot.get("is_available") is True
        assert plot.get("business_id") is None
        assert plot.get("owner") is None
    finally:
        _cleanup(mongo, plot_id, business_id)


def test_requires_admin_no_token(mongo, player):
    plot_id, business_id = _seed(mongo, player["id"])
    try:
        r = requests.delete(
            f"{BASE_URL}/api/admin/players/{player['id']}/business/{business_id}",
            timeout=15,
        )
        assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code} {r.text}"
        # Business must NOT be deleted
        assert mongo.businesses.find_one({"id": business_id}) is not None
    finally:
        _cleanup(mongo, plot_id, business_id)


def test_requires_admin_regular_user_forbidden(mongo, admin_token, user_token, player):
    plot_id, business_id = _seed(mongo, player["id"])
    try:
        r = requests.delete(
            f"{BASE_URL}/api/admin/players/{player['id']}/business/{business_id}",
            headers={"Authorization": f"Bearer {user_token}"},
            timeout=15,
        )
        assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code} {r.text}"
        assert mongo.businesses.find_one({"id": business_id}) is not None
    finally:
        _cleanup(mongo, plot_id, business_id)


def test_not_found_for_wrong_player(mongo, admin_token, player):
    # Seed a biz owned by player, but attempt delete via admin as if belonging to another player id.
    plot_id, business_id = _seed(mongo, player["id"])
    fake_player_id = f"TEST_nonexistent_{uuid.uuid4().hex[:8]}"
    try:
        r = requests.delete(
            f"{BASE_URL}/api/admin/players/{fake_player_id}/business/{business_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=15,
        )
        # Either 404 (player not found) — endpoint returns 404 in both cases
        assert r.status_code == 404, f"expected 404, got {r.status_code} {r.text}"
        # No cascade should have run
        assert mongo.businesses.find_one({"id": business_id}) is not None
        plot = mongo.plots.find_one({"id": plot_id})
        assert plot.get("is_occupied") is True
    finally:
        _cleanup(mongo, plot_id, business_id)


def test_not_found_business_id_wrong(mongo, admin_token, player):
    r = requests.delete(
        f"{BASE_URL}/api/admin/players/{player['id']}/business/TEST_nonexistent_biz_xyz",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=15,
    )
    assert r.status_code == 404, f"expected 404, got {r.status_code} {r.text}"
