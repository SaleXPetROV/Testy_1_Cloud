"""Iter12 helper: count users with a given email in Mongo."""
import asyncio
import os
import sys

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")


async def main(email):
    cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = cli[os.environ["DB_NAME"]]
    n = await db.users.count_documents({"email": email})
    cli.close()
    print(f"COUNT={n}")


asyncio.run(main(sys.argv[1]))
