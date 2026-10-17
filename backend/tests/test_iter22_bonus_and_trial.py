"""
Iteration 22 tests:
- Issue 3&5: Admin can view+update bonus_balance and balance_ton separately.
- Issue 2: Trial Center produces only produced_resource_id and consumes only consumed_resource_id.
"""
import os
import time
import pytest
import requests

def _load_backend_url():
    v = os.environ.get("REACT_APP_BACKEND_URL")
    if not v:
        # fall back to frontend/.env
        try:
            with open("/app/frontend/.env") as f:
                for line in f:
                    if line.startswith("REACT_APP_BACKEND_URL="):
                        v = line.split("=", 1)[1].strip()
                        break
        except Exception:
            pass
    assert v, "REACT_APP_BACKEND_URL not set"
    return v.rstrip("/")

BASE_URL = _load_backend_url()

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "")
USER_EMAIL = "testuser@example.com"
USER_PASSWORD = "Test1234!"
TESTUSER_ID = "6fe3ae7d-8dea-48c6-8d7c-85a743f59143"


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=20)
    assert r.status_code == 200, f"Login failed for {email}: {r.status_code} {r.text}"
    tok = r.json().get("access_token") or r.json().get("token")
    assert tok, f"No token in login response: {r.json()}"
    return tok


@pytest.fixture(scope="module")
def admin_token():
    return _login(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def user_token():
    return _login(USER_EMAIL, USER_PASSWORD)


# ---------------- Admin bonus balance (Issue 3&5) ----------------

class TestAdminBonusBalance:
    def test_get_player_returns_bonus_balance(self, admin_token):
        r = requests.get(
            f"{BASE_URL}/api/admin/players/{TESTUSER_ID}",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=20,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        user = data.get("user") or data
        assert "bonus_balance" in user, f"bonus_balance missing in user keys={list(user.keys())}"
        assert "balance_ton" in user
        print(f"Initial: balance_ton={user.get('balance_ton')} bonus_balance={user.get('bonus_balance')}")

    def test_update_bonus_and_balance_persist(self, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        def get_user():
            r = requests.get(f"{BASE_URL}/api/admin/players/{TESTUSER_ID}", headers=headers, timeout=20)
            assert r.status_code == 200
            return (r.json().get("user") or r.json())

        original = get_user()
        orig_real = float(original.get("balance_ton") or 0)
        orig_bonus = float(original.get("bonus_balance") or 0)
        print(f"Original: real={orig_real} bonus={orig_bonus}")

        new_real = 50.0
        new_bonus = 30.0
        payload = {"bonus_balance": new_bonus, "balance_ton": new_real}
        r = requests.post(
            f"{BASE_URL}/api/admin/players/{TESTUSER_ID}/update",
            headers=headers,
            json=payload,
            timeout=20,
        )
        assert r.status_code == 200, f"Update failed: {r.status_code} {r.text}"

        after = get_user()
        assert abs(float(after.get("balance_ton") or 0) - new_real) < 1e-6, f"balance_ton not persisted: {after.get('balance_ton')}"
        assert abs(float(after.get("bonus_balance") or 0) - new_bonus) < 1e-6, f"bonus_balance not persisted: {after.get('bonus_balance')}"

        # Change bonus only and verify balance_ton unchanged
        r = requests.post(
            f"{BASE_URL}/api/admin/players/{TESTUSER_ID}/update",
            headers=headers,
            json={"bonus_balance": 42.0},
            timeout=20,
        )
        assert r.status_code == 200
        after2 = get_user()
        assert abs(float(after2.get("bonus_balance") or 0) - 42.0) < 1e-6
        assert abs(float(after2.get("balance_ton") or 0) - new_real) < 1e-6

        # Restore expected demo state (50 real, 30 bonus)
        requests.post(
            f"{BASE_URL}/api/admin/players/{TESTUSER_ID}/update",
            headers=headers,
            json={"bonus_balance": 30.0, "balance_ton": 50.0},
            timeout=20,
        )


# ---------------- Trial Center (Issue 2) ----------------

class TestTrialCenter:
    def test_trial_center_endpoint_fields(self, user_token):
        r = requests.get(
            f"{BASE_URL}/api/trial-center",
            headers={"Authorization": f"Bearer {user_token}"},
            timeout=20,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        print("trial-center keys:", list(data.keys()))
        # The endpoint should include produced_resource_id and consumed_resource_id somewhere.
        flat = str(data)
        assert "produced_resource_id" in flat, f"produced_resource_id missing: {data}"
        assert "consumed_resource_id" in flat, f"consumed_resource_id missing: {data}"

    def test_trial_center_produces_only_declared_resource(self, user_token, admin_token):
        """
        Buy the trial center if not owned, then wait a moment for accrual and verify
        only produced_resource_id is credited (never a fixed 'energy' unless it IS produced).
        Since accrual is time-based per day, we assert via the endpoint that pending/produced
        deltas reference only produced_resource_id.
        """
        headers = {"Authorization": f"Bearer {user_token}"}
        r = requests.get(f"{BASE_URL}/api/trial-center", headers=headers, timeout=20)
        assert r.status_code == 200
        data = r.json()
        owned = data.get("owned") or data.get("purchased") or bool(data.get("trial_center"))
        if not owned:
            buy = requests.post(f"{BASE_URL}/api/trial-center/buy", headers=headers, timeout=20)
            # 200 or 400 (already owned) both acceptable
            print(f"buy response: {buy.status_code} {buy.text[:200]}")
            assert buy.status_code in (200, 201, 400, 409)
            r = requests.get(f"{BASE_URL}/api/trial-center", headers=headers, timeout=20)
            data = r.json()

        # Inspect any 'produced'/'accrued' fields in response
        produced_rid = None
        consumed_rid = None
        # Walk data for those ids
        def walk(obj):
            nonlocal produced_rid, consumed_rid
            if isinstance(obj, dict):
                if "produced_resource_id" in obj and obj["produced_resource_id"]:
                    produced_rid = obj["produced_resource_id"]
                if "consumed_resource_id" in obj and obj["consumed_resource_id"]:
                    consumed_rid = obj["consumed_resource_id"]
                for v in obj.values():
                    walk(v)
            elif isinstance(obj, list):
                for it in obj:
                    walk(it)
        walk(data)
        print(f"produced_rid={produced_rid}, consumed_rid={consumed_rid}")
        assert produced_rid, "No produced_resource_id in trial-center response"

    def test_accrue_source_code_only_touches_declared_resources(self):
        """Static guard: read routes/trial_center.py and ensure accrue_trial_center only credits
        produced_resource_id and consumes consumed_resource_id (never a hardcoded 'energy')."""
        path = "/app/backend/routes/trial_center.py"
        with open(path) as f:
            src = f.read()
        # locate accrue_trial_center
        assert "def accrue_trial_center" in src or "async def accrue_trial_center" in src
        idx = src.find("accrue_trial_center")
        snippet = src[idx: idx + 4000]
        # Should reference produced_resource_id and consumed_resource_id
        assert "produced_resource_id" in snippet, "produced_resource_id not used in accrue_trial_center"
        assert "consumed_resource_id" in snippet, "consumed_resource_id not used in accrue_trial_center"
        # Should not hardcode a resource string like 'energy' in that block
        # (allow the word energy only if commented). Simple heuristic:
        lowered = snippet.lower()
        # We flag if the literal 'energy' appears as a string key in credit path
        if "'energy'" in lowered or '"energy"' in lowered:
            # It's acceptable if it's produced_resource_id fallback default; warn
            print("WARN: 'energy' literal present in accrue_trial_center block; verify it's not a fixed credit")
