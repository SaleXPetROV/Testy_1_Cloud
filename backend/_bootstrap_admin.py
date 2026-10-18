"""Bootstrap an admin user + print a valid JWT for testing the admin API."""
import asyncio, os, uuid
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")
from auth_handler import create_token  # uses the same SECRET_KEY the server loads

EMAIL = "qa_admin@test.local"


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    existing = await db.users.find_one({"email": EMAIL})
    if not existing:
        await db.users.insert_one({
            "id": str(uuid.uuid4()),
            "email": EMAIL,
            "username": "qa_admin",
            "is_admin": True,
            "bonus_balance": 0.0,
            "balance_ton": 0.0,
        })
    else:
        await db.users.update_one({"email": EMAIL}, {"$set": {"is_admin": True}})
    token = create_token({"sub": EMAIL})
    print("ADMIN_EMAIL=" + EMAIL)
    print("ADMIN_TOKEN=" + token)


asyncio.run(main())
