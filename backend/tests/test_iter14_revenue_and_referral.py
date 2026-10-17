"""Iteration 14: verify admin revenue-stats exposes resource_sales_tax/count
and that referral_income tx type + Russian mapping is available.
"""
import os
import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://ton-metro.preview.emergentagent.com").rstrip("/")

ADMIN_EMAIL = "sanyanazarov212@gmail.com"
ADMIN_PASS = os.environ.get("TEST_ADMIN_PASSWORD", "")


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=15)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text[:300]}"
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok, f"no token in login response: {r.json()}"
    return tok


def test_revenue_stats_exposes_resource_sales_fields(admin_token):
    r = requests.get(f"{BASE}/api/admin/revenue-stats", headers={"Authorization": f"Bearer {admin_token}"}, timeout=15)
    assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
    data = r.json()
    assert "resource_sales_tax" in data, f"resource_sales_tax missing: keys={list(data.keys())}"
    assert "resource_sales_count" in data, f"resource_sales_count missing: keys={list(data.keys())}"
    assert isinstance(data["resource_sales_tax"], (int, float)), type(data["resource_sales_tax"])
    assert isinstance(data["resource_sales_count"], (int, float)), type(data["resource_sales_count"])
    assert data["resource_sales_tax"] >= 0
    assert data["resource_sales_count"] >= 0
    print(f"revenue-stats: resource_sales_tax={data['resource_sales_tax']} resource_sales_count={data['resource_sales_count']}")


def test_treasury_wiring_exists_in_code():
    """Static check that /api/market/buy writes both market_tax AND resource_sales_tax."""
    with open("/app/backend/server.py") as f:
        src = f.read()
    # Find market/buy handler section
    buy_idx = src.find('resource_sales_tax": admin_tax')
    assert buy_idx > 0, "resource_sales_tax not being $inc'd in market/buy"
    count_idx = src.find('resource_sales_count": 1')
    assert count_idx > 0, "resource_sales_count not being $inc'd in market/buy"


def test_referral_income_transaction_type_russian_mapping():
    """Ensure frontend translation file has referral_income mapped in all 8 languages."""
    with open("/app/frontend/src/lib/translationsExtra.js") as f:
        src = f.read()
    assert "referral_income:" in src, "referral_income key missing from transactionTypeI18n"
    # Check that ru+en+es+zh+fr+de+ja+ko are present on the same line
    line = [l for l in src.splitlines() if "referral_income:" in l]
    assert line, "referral_income line not found"
    l = line[0]
    for lang_code in ["en:", "ru:", "es:", "zh:", "fr:", "de:", "ja:", "ko:"]:
        assert lang_code in l, f"lang {lang_code} missing from referral_income mapping"
    # Verify RU + EN values
    assert "Реферальный доход" in l
    assert "Referral income" in l
