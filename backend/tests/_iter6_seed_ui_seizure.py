"""Seed (or clean) a seized business for iteration-6 frontend testing."""
import sys
from datetime import datetime, timezone, timedelta
from pymongo import MongoClient
from dotenv import dotenv_values

env = dotenv_values("/app/backend/.env")
db = MongoClient(env["MONGO_URL"])[env["DB_NAME"]]
PFX = "TEST_SEIZ6UI_"
BID, PID = PFX + "BIZ", PFX + "PLOT"


def clean():
    db.businesses.delete_many({"id": BID})
    db.plots.delete_many({"id": PID})
    db.land_listings.delete_many({"business_id": BID})
    db.users.update_one({"email": "testuser@example.com"},
                        {"$unset": {"tutorial_completed": ""}})
    print("CLEANED")


if len(sys.argv) > 1 and sys.argv[1] == "clean":
    clean()
    raise SystemExit(0)

clean()
u = db.users.find_one({"email": "testuser@example.com"}, {"_id": 0})
db.users.update_one({"id": u["id"]}, {"$set": {"tutorial_completed": True}})
now = datetime.now(timezone.utc)
db.plots.insert_one({"id": PID, "city_id": "ton_island", "x": 931, "y": 931,
                     "owner": u["id"], "owner_username": u.get("username"),
                     "business_id": BID, "price": 5, "is_available": False})
db.businesses.insert_one({
    "id": BID, "plot_id": PID, "business_type": "helios", "level": 3,
    "durability": 0, "xp": 0, "owner": u["id"], "owner_username": u.get("username"),
    "city_id": "ton_island", "plot_x": 931, "plot_y": 931, "status": "active",
    "is_active": True, "created_at": (now - timedelta(days=30)).isoformat(),
    "zero_durability_since": (now - timedelta(days=9)).isoformat(),
})

import asyncio  # noqa: E402
sys.path.insert(0, "/app/backend")
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
from core.seizure import process_seizures  # noqa: E402
res = asyncio.run(process_seizures(AsyncIOMotorClient(env["MONGO_URL"])[env["DB_NAME"]]))
print("SWEEP", res)
lst = db.land_listings.find_one({"business_id": BID}, {"_id": 0})
print("LISTING", lst and lst["id"], lst and lst["price"], lst and lst["status"])
print("USER_ID", u["id"])
