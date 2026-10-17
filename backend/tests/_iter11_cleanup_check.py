import asyncio
import os

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")


async def main():
    cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = cli[os.environ["DB_NAME"]]
    leftovers = await db.users.count_documents({"email": {"$regex": "^TEST_iter11"}})
    tg = await db.users.count_documents({"telegram_id": {"$in": [911100011, 911100011.0, "911100011"]}})
    print("leftover TEST_iter11 users:", leftovers)
    print("leftover iter11 tg users:", tg)
    if leftovers:
        r = await db.users.delete_many({"email": {"$regex": "^TEST_iter11"}})
        print("deleted", r.deleted_count)
    if tg:
        r = await db.users.delete_many({"telegram_id": {"$in": [911100011, 911100011.0, "911100011"]}})
        print("deleted tg", r.deleted_count)
    cli.close()


asyncio.run(main())
