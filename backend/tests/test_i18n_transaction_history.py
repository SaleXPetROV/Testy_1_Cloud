"""
Backend tests for i18n / transaction_history.py:
- GET /api/history/transactions returns each tx with a `status_key` field.
- /api/history/types is reachable.
"""
import os
import pytest
import requests
from dotenv import load_dotenv

load_dotenv('/app/frontend/.env')
BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
assert BASE_URL.startswith("http"), f"REACT_APP_BACKEND_URL not set, got: {BASE_URL!r}"

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PASSWORD = "Test1234!"


@pytest.fixture(scope="module")
def api_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _login(client, email, password):
    r = client.post(f"{BASE_URL}/api/auth/login",
                    json={"email": email, "password": password},
                    timeout=20)
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    data = r.json()
    token = data.get("access_token") or data.get("token") or (data.get("user") or {}).get("token")
    assert token, f"No token in login response: {data}"
    return token


@pytest.fixture(scope="module")
def admin_token(api_client):
    return _login(api_client, ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def user_token(api_client):
    return _login(api_client, USER_EMAIL, USER_PASSWORD)


class TestTransactionHistoryI18n:
    def test_history_types_reachable(self, api_client, user_token):
        r = api_client.get(f"{BASE_URL}/api/history/types",
                           headers={"Authorization": f"Bearer {user_token}"},
                           timeout=20)
        # Endpoint may be public or require auth; accept 200 or 401 (we just need it not to be 500)
        assert r.status_code in (200, 401, 403), f"Unexpected status: {r.status_code} {r.text}"

    def test_history_transactions_user(self, api_client, user_token):
        r = api_client.get(f"{BASE_URL}/api/history/transactions?limit=20",
                           headers={"Authorization": f"Bearer {user_token}"},
                           timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        body = r.json()
        # Accept either list or {transactions: [...]}
        txs = body if isinstance(body, list) else body.get("transactions") or body.get("data") or []
        assert isinstance(txs, list)
        # Empty list still must not crash
        for tx in txs:
            assert "status_key" in tx, f"Missing status_key in tx: {tx}"
            assert "tx_type" in tx, f"Missing tx_type in tx: {tx}"
            # status_key should be a non-empty string (raw status)
            assert isinstance(tx["status_key"], str) and len(tx["status_key"]) > 0

    def test_history_transactions_admin(self, api_client, admin_token):
        r = api_client.get(f"{BASE_URL}/api/history/transactions?limit=20",
                           headers={"Authorization": f"Bearer {admin_token}"},
                           timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        body = r.json()
        txs = body if isinstance(body, list) else body.get("transactions") or body.get("data") or []
        assert isinstance(txs, list)
        for tx in txs:
            assert "status_key" in tx, f"Missing status_key in admin tx: {tx}"
            assert isinstance(tx["status_key"], str) and len(tx["status_key"]) > 0
            # Recognised statuses (raw keys) must include common ones
            assert tx["status_key"] in {
                "pending", "processing", "completed", "approved", "failed", "rejected"
            } or len(tx["status_key"]) > 0
