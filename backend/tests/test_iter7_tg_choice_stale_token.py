"""Iter7 backend sanity: brand-new Telegram id → /miniapp returns choice_required, no user created.

Also verifies /miniapp/create then completes the account for that same signed init_data.
Test data: TEST_ITER7_TG_ID = 7770707077 (cleaned up on teardown).
"""
import os, sys, json, hmac, hashlib, urllib.parse, asyncio
from pathlib import Path
import pytest, requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

# BASE_URL from frontend/.env
_fe_env = Path("/app/frontend/.env").read_text()
BASE_URL = ""
for line in _fe_env.splitlines():
    if line.startswith("REACT_APP_BACKEND_URL="):
        BASE_URL = line.split("=", 1)[1].strip().strip('"').rstrip("/")
API = f"{BASE_URL}/api"

TG_ID = 7770707077
FIRST_NAME = "Iter7Test"
USERNAME = "iter7test"


def build_init_data(tg_id=TG_ID, first_name=FIRST_NAME, username=USERNAME, auth_date=2000000000, query_id="AAA"):
    user_payload = json.dumps({
        "id": int(tg_id),
        "first_name": first_name,
        "username": username,
        "language_code": "en",
    }, separators=(",", ":"))
    fields = {"auth_date": str(auth_date), "query_id": query_id, "user": user_payload}
    dcs = "\n".join(f"{k}={fields[k]}" for k in sorted(fields.keys()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    hash_hex = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    parts = [f"{k}={urllib.parse.quote(v, safe='')}" for k, v in fields.items()]
    parts.append(f"hash={hash_hex}")
    return "&".join(parts)


def _cleanup_tg(tg_id=TG_ID):
    from motor.motor_asyncio import AsyncIOMotorClient
    async def _do():
        cli = AsyncIOMotorClient(MONGO_URL)
        db = cli[DB_NAME]
        await db.users.delete_many({"$or": [{"telegram_id": int(tg_id)}, {"telegram_id": str(tg_id)}]})
        cli.close()
    asyncio.run(_do())


@pytest.fixture(autouse=True)
def _clean():
    _cleanup_tg()
    yield
    _cleanup_tg()


def test_miniapp_choice_required_for_new_tg_id():
    init_data = build_init_data()
    r = requests.post(f"{API}/auth/telegram/miniapp", json={"init_data": init_data}, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("status") == "choice_required", body
    # telegram identity echoed back to the client for the modal
    tg = body.get("telegram") or {}
    assert str(tg.get("id")) == str(TG_ID) or tg.get("first_name") == FIRST_NAME

    # And crucially: NO user record was created yet.
    from motor.motor_asyncio import AsyncIOMotorClient
    async def _count():
        cli = AsyncIOMotorClient(MONGO_URL); db = cli[DB_NAME]
        n = await db.users.count_documents({"$or": [{"telegram_id": int(TG_ID)}, {"telegram_id": str(TG_ID)}]})
        cli.close(); return n
    assert asyncio.run(_count()) == 0


def test_miniapp_create_then_login_ok():
    init_data = build_init_data()
    # First choice_required
    r1 = requests.post(f"{API}/auth/telegram/miniapp", json={"init_data": init_data}, timeout=30)
    assert r1.json().get("status") == "choice_required"
    # Now create
    r2 = requests.post(f"{API}/auth/telegram/miniapp/create", json={"init_data": init_data}, timeout=30)
    assert r2.status_code == 200, r2.text
    d = r2.json()
    assert "token" in d and d["token"]
    # Same signed init_data now returns a token (linked account auto-login)
    r3 = requests.post(f"{API}/auth/telegram/miniapp", json={"init_data": init_data}, timeout=30)
    assert r3.status_code == 200
    d3 = r3.json()
    assert d3.get("status") != "choice_required"
    assert "token" in d3


def test_seeded_login_regression():
    r = requests.post(f"{API}/auth/login", json={"email": "testuser@example.com", "password": "Test1234!"}, timeout=30)
    assert r.status_code == 200, r.text
    token = r.json().get("token") or r.json().get("access_token")
    assert token
    me = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"}, timeout=30)
    assert me.status_code == 200
