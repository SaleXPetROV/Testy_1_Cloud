"""
Backend tests for the current demo-mode iteration:
- Demo business production has NO +8% buff (user_buff_multiplier == 1.0 and
  production.amount == production.base_production).
- Demo referral bonus is +5,000 $CITY (not 50,000).
- Demo profile / entry endpoint sanity.
"""
import os
import asyncio
import pytest
import requests
from dotenv import load_dotenv
load_dotenv("/app/frontend/.env")
load_dotenv("/app/backend/.env")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://city-builder-ton.preview.emergentagent.com").rstrip("/")

TEST_EMAIL = "testuser@example.com"
TEST_PASSWORD = "Test1234!"


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def token(api):
    r = api.post(f"{BASE_URL}/api/auth/login",
                 json={"email": TEST_EMAIL, "password": TEST_PASSWORD})
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    data = r.json()
    assert "token" in data and data["token"]
    return data["token"]


@pytest.fixture(scope="module")
def demo_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Game-Mode": "demo",
    }


# ---------- /api/demo/enter ----------
def test_demo_enter_creates_profile(api, demo_headers):
    r = api.post(f"{BASE_URL}/api/demo/enter", headers=demo_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("is_demo") is True
    assert data.get("profile") is not None
    assert "demo_balance_city" in data["profile"]


# ---------- /api/demo/my-businesses base production, no buff ----------
def test_demo_my_businesses_no_buff(api, demo_headers):
    r = api.get(f"{BASE_URL}/api/demo/my-businesses", headers=demo_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "businesses" in data and len(data["businesses"]) == 1
    biz = data["businesses"][0]
    prod = biz["production"]

    # Core assertions of the new requirement:
    assert prod["user_buff_multiplier"] == 1.0, prod
    # amount must equal base_production for durability >= 50 (fresh biz = 100)
    assert biz["durability"] >= 50, biz
    assert prod["amount"] == prod["base_production"], prod

    # Level-1 base production for Tier-1 businesses in this game = 100 or 110
    # depending on the picked type. It must NOT be 108 (buffed 100) etc.
    assert prod["base_production"] in (100, 110), prod
    # Reject any implicit multiplier > 1.0 sneaking into amount:
    assert prod["amount"] <= prod["base_production"] + 0.001, prod


# ---------- Demo referral bonus value ----------
def test_demo_referral_bonus_constant():
    """DEMO_REFERRAL_BONUS in demo_service must be 5000.0, not 50000."""
    import sys
    sys.path.insert(0, "/app/backend")
    import demo_service
    assert demo_service.DEMO_REFERRAL_BONUS == 5000.0, demo_service.DEMO_REFERRAL_BONUS
    assert demo_service.DEMO_TEST_BUFF_MULTIPLIER == 1.0


def test_credit_demo_referral_increments_by_5000():
    """Call credit_demo_referral directly against the live db and verify
    the demo_balance_city increases by exactly 5000."""
    import sys
    sys.path.insert(0, "/app/backend")
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    import demo_service

    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]

    async def _run():
        client = AsyncIOMotorClient(mongo_url)
        db = client[db_name]
        # Use the real testuser id so profile already exists.
        user = await db.users.find_one({"email": TEST_EMAIL}, {"_id": 0, "id": 1})
        assert user, "testuser@example.com must exist"
        uid = user["id"]
        profile = await demo_service.get_or_create_demo_profile(db, uid)
        before = float(profile.get("demo_balance_city", 0))
        res = await demo_service.credit_demo_referral(db, uid)
        assert res["status"] == "credited"
        assert res["bonus"] == 5000.0
        after = float(res["demo_balance_city"])
        assert round(after - before, 2) == 5000.0, (before, after)
        client.close()

    asyncio.get_event_loop().run_until_complete(_run())
