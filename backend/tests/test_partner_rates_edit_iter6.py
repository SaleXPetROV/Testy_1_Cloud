"""Partner Programs: editing payout rates must NOT change api_key / verify URL."""
import os
import pytest
import requests
from dotenv import dotenv_values

_env = dotenv_values("/app/frontend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or _env.get("REACT_APP_BACKEND_URL")).rstrip("/")

PROGRAM_ID = "24554814-e689-4a5d-ad03-bdf92fd250f6"
API_KEY = "HLAOGvqmlxeorRwEyn7mSQ"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": "sanyanazarov212@gmail.com", "password": os.environ.get("TEST_ADMIN_PASSWORD", "")}, timeout=30)
    if r.status_code != 200:
        pytest.fail(f"admin login failed {r.status_code}: {r.text[:300]}")
    tok = r.json().get("token") or r.json().get("access_token")
    if not tok:
        pytest.fail(f"no token in login response: {r.text[:300]}")
    return tok


@pytest.fixture(scope="module")
def hdrs(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


def _get_program(hdrs):
    r = requests.get(f"{BASE_URL}/api/admin/partner-programs", headers=hdrs, timeout=30)
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    items = body if isinstance(body, list) else (body.get("programs") or body.get("items") or [])
    for p in items:
        if p.get("id") == PROGRAM_ID:
            assert "_id" not in p, "MongoDB _id leaked in response"
            return p
    pytest.fail(f"program {PROGRAM_ID} not found; got ids={[i.get('id') for i in items]}")


def _verify_url(p):
    return p.get("verify_url") or p.get("verify_path")


class TestPartnerRatesEdit:
    def test_verify_url_invariance_on_rate_patch(self, hdrs):
        before = _get_program(hdrs)
        assert before.get("api_key") == API_KEY
        url_before = _verify_url(before)
        assert url_before, f"no verify_url/verify_path in program payload: {list(before.keys())}"
        print(f"BEFORE verify_url={url_before!r}")

        r = requests.patch(f"{BASE_URL}/api/admin/partner-programs/{PROGRAM_ID}",
                           headers=hdrs, json={"per_active_user_city": 25, "income_percent": 12}, timeout=30)
        assert r.status_code == 200, f"PATCH failed {r.status_code}: {r.text[:300]}"
        prog = r.json().get("program") or {}
        assert float(prog.get("per_active_user_city")) == 25.0
        assert float(prog.get("income_percent")) == 12.0
        assert prog.get("api_key") == API_KEY
        assert _verify_url(prog) == url_before, "verify url changed in PATCH response"

        after = _get_program(hdrs)
        assert float(after["per_active_user_city"]) == 25.0
        assert float(after["income_percent"]) == 12.0
        assert after["api_key"] == API_KEY, "api_key changed!"
        assert _verify_url(after) == url_before, "verify url changed after PATCH!"

    def test_income_percent_clamped_to_100(self, hdrs):
        r = requests.patch(f"{BASE_URL}/api/admin/partner-programs/{PROGRAM_ID}",
                           headers=hdrs, json={"income_percent": 150}, timeout=30)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        after = _get_program(hdrs)
        assert float(after["income_percent"]) == 100.0, after["income_percent"]
        assert after["api_key"] == API_KEY

    def test_negative_income_clamped_to_zero(self, hdrs):
        before = _get_program(hdrs)
        url_before = _verify_url(before)
        r = requests.patch(f"{BASE_URL}/api/admin/partner-programs/{PROGRAM_ID}",
                           headers=hdrs, json={"income_percent": -5}, timeout=30)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        after = _get_program(hdrs)
        assert float(after["income_percent"]) == 0.0
        assert _verify_url(after) == url_before

    def test_verify_endpoint_still_works_with_same_api_key(self, hdrs):
        p = _get_program(hdrs)
        r = requests.get(f"{BASE_URL}/api/partner/verify/{API_KEY}",
                         params={"user_id": "nonexistent-user-id"}, timeout=30)
        # 402 = key resolved, quest checks incomplete (expected). 401/403/404 would mean invalid key.
        assert r.status_code in (200, 400, 402), f"{r.status_code}: {r.text[:300]}"
        assert "Неверный" not in r.text and "invalid" not in r.text.lower()
        print(f"verify endpoint -> {r.status_code} {r.text[:200]}")

    def test_patch_requires_auth(self):
        r = requests.patch(f"{BASE_URL}/api/admin/partner-programs/{PROGRAM_ID}",
                           json={"income_percent": 5}, timeout=30)
        assert r.status_code in (401, 403), r.status_code

    def test_restore_final_values(self, hdrs):
        r = requests.patch(f"{BASE_URL}/api/admin/partner-programs/{PROGRAM_ID}",
                           headers=hdrs, json={"per_active_user_city": 25, "income_percent": 12}, timeout=30)
        assert r.status_code == 200
        after = _get_program(hdrs)
        assert float(after["per_active_user_city"]) == 25.0
        assert float(after["income_percent"]) == 12.0
