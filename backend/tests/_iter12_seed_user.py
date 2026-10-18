"""Iter12 helper: seed/cleanup an email+password test user for password-reset testing."""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from passlib.context import CryptContext

load_dotenv("/app/backend/.env")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

EMAIL_PATTERNS = [
    {"email": {"$regex": "resend.dev$", "$options": "i"}},
    {"email": {"$regex": "^TEST_iter12", "$options": "i"}},
    {"username": {"$regex": "^TESTiter12", "$options": "i"}},
]


async def create(email, username):
    cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = cli[os.environ["DB_NAME"]]
    await db.users.delete_many({"email": email})
    await db.users.insert_one({
        "id": str(uuid.uuid4()),
        "username": username,
        "display_name": username,
        "email": email,
        "hashed_password": pwd_context.hash("Str0ng!Passw0rd#2026"),
        "avatar": None,
        "balance_ton": 0.0,
        "language": "en",
        "level": "novice",
        "xp": 0,
        "plots_owned": [],
        "businesses_owned": [],
        "is_admin": False,
        "email_verified": True,
        "registration_method": "email",
        "created_at": datetime.now(timezone.utc),
    })
    cli.close()
    print("OK created", email)


async def cleanup():
    cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = cli[os.environ["DB_NAME"]]
    total = 0
    for q in EMAIL_PATTERNS:
        r = await db.users.delete_many(q)
        total += r.deleted_count
    cli.close()
    print(f"CLEANUP_OK deleted={total}")


if __name__ == "__main__":
    if sys.argv[1] == "create":
        asyncio.run(create(sys.argv[2], sys.argv[3]))
    else:
        asyncio.run(cleanup())
