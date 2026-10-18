"""Dev-only helper: give test users a couple of businesses so the redesigned
My Businesses page can be exercised. NOT wired into deploy/startup."""
import asyncio
import os
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

BUSINESS_TYPES = ["bio_farm", "nano_dc", "quartz_mine"]

TARGET_EMAILS = ["testuser@example.com", "sanyanazarov212@gmail.com"]


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    for email in TARGET_EMAILS:
        user = await db.users.find_one({"email": email})
        if not user:
            print(f"SKIP {email}: no user")
            continue
        uid = user["id"]
        # how many test businesses already exist for this user
        existing_ids = [b async for b in db.businesses.find({"owner": uid, "id": {"$regex": "^testbiz_"}}, {"id": 1})]
        if existing_ids:
            print(f"{email}: already has {len(existing_ids)} test businesses")
            continue
        made = []
        for i, btype in enumerate(BUSINESS_TYPES[:2]):
            bid = f"testbiz_{uid[:8]}_{i}"
            doc = {
                "id": bid,
                "city_id": "test_city",
                "plot_id": f"testplot_{uid[:8]}_{i}",
                "plot_x": i,
                "plot_y": 0,
                "business_type": btype,
                "owner": uid,
                "owner_username": user.get("username"),
                "level": 3,
                "durability": 100.0,
                "xp": 0,
                "storage": {"capacity": 500, "items": {}},
                "built_at": datetime.now(timezone.utc).isoformat(),
                "last_collection": datetime.now(timezone.utc).isoformat(),
                "last_tick": datetime.now(timezone.utc).isoformat(),
                "last_wear_update": datetime.now(timezone.utc).isoformat(),
                "total_income": 0,
                "status": "active",
                "is_active": False,
            }
            await db.businesses.insert_one(doc)
            await db.users.update_one({"id": uid}, {"$addToSet": {"businesses_owned": bid}})
            made.append(bid)
        print(f"{email}: created {made}")


if __name__ == "__main__":
    asyncio.run(main())
