"""Helper: create a fresh Telegram Mini App account and print JWT + tg_id.

Used by iter6 frontend testing (SmartAvatar + Home nav bug fix).
"""
import os, sys, json, hmac, hashlib, urllib.parse, requests, asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
BASE_URL = os.environ["REACT_APP_BACKEND_URL"] if "REACT_APP_BACKEND_URL" in os.environ else None
if not BASE_URL:
    # frontend/.env
    fe = Path("/app/frontend/.env").read_text()
    for line in fe.splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().strip('"')
BASE_URL = BASE_URL.rstrip("/")
API = f"{BASE_URL}/api"

TG_ID = int(os.environ.get("ITER6_TG_ID", "889600601"))
FIRST_NAME = os.environ.get("ITER6_FN", "willywo")
USERNAME = os.environ.get("ITER6_UN", "willywo")


def build_init_data(tg_id, first_name, username, auth_date=2000000000, query_id="AAA"):
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


def _cleanup(tg_id):
    from motor.motor_asyncio import AsyncIOMotorClient
    mongo = os.environ["MONGO_URL"]; db_name = os.environ["DB_NAME"]
    async def _do():
        cli = AsyncIOMotorClient(mongo)
        db = cli[db_name]
        await db.users.delete_many({"$or": [
            {"telegram_id": int(tg_id)}, {"telegram_id": str(tg_id)}
        ]})
        cli.close()
    asyncio.run(_do())


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "create"
    if action == "cleanup":
        _cleanup(TG_ID); print("cleanup_ok"); return

    _cleanup(TG_ID)  # start fresh
    init_data = build_init_data(TG_ID, FIRST_NAME, USERNAME)
    r1 = requests.post(f"{API}/auth/telegram/miniapp", json={"init_data": init_data}, timeout=30)
    assert r1.status_code == 200, (r1.status_code, r1.text)
    assert r1.json().get("status") == "choice_required", r1.json()

    r2 = requests.post(f"{API}/auth/telegram/miniapp/create", json={"init_data": init_data}, timeout=30)
    assert r2.status_code == 200, (r2.status_code, r2.text)
    data = r2.json()
    token = data["token"]
    user = data["user"]
    avatar = user.get("avatar")
    # Also verify /api/auth/me
    me = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"}, timeout=30).json()
    print(json.dumps({
        "token": token, "user": user, "avatar": avatar, "me_avatar": me.get("avatar"),
        "tg_id": TG_ID,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
