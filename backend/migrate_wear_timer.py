"""
One-off migration: initialise `last_wear_update` for existing businesses.

Why: durability wear now uses a dedicated `last_wear_update` clock that is
independent of income-collection timers (last_tick / last_collection). For
businesses created before this change the field is missing, so the first tick
would fall back to a possibly very old timer and apply a huge one-time wear.
This script stamps `last_wear_update = now` on every business that lacks it,
so wear starts accruing fresh from deploy time.

Run once after deploy:
    cd backend && python migrate_wear_timer.py
"""
import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(Path(__file__).parent / '.env')

mongo_url = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
db_name = os.environ.get('DB_NAME', 'ton_city')


async def main():
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    now_iso = datetime.now(timezone.utc).isoformat()

    result = await db.businesses.update_many(
        {"last_wear_update": {"$exists": False}},
        {"$set": {"last_wear_update": now_iso}},
    )
    print(f"✅ last_wear_update set on {result.modified_count} businesses (matched {result.matched_count}).")
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
