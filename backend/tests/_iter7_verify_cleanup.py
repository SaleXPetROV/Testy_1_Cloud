"""Verify iteration-7 test fixtures were cleaned up from the users collection."""
import asyncio

from motor.motor_asyncio import AsyncIOMotorClient

from test_tg_miniapp_auth_resilience_iter_current import DB_NAME, MONGO_URL


async def main():
    cli = AsyncIOMotorClient(MONGO_URL)
    db = cli[DB_NAME]
    leftovers = await db.users.find(
        {"$or": [
            {"id": {"$regex": "^TEST_legacy_"}},
            {"telegram_username": {"$regex": "^(victim_|legacy_|old_|new_|reg_|bad_)"}},
            {"telegram_id": {"$gte": 950000000, "$lt": 960000000}},
            {"telegram_user_id": {"$regex": "^95"}},
        ]},
        {"_id": 0, "id": 1, "username": 1, "telegram_id": 1, "telegram_username": 1},
    ).to_list(50)
    print("leftovers:", leftovers)
    print("total users:", await db.users.count_documents({}))
    cli.close()


asyncio.run(main())
