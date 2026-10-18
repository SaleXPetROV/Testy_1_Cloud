"""
Seed demo data for the admin "Выкуп" (buyout) panel.

Creates a handful of business owners, some with active P2P resource listings,
so the admin panel has realistic data to display and buy out.

Idempotent: removes previously seeded demo players (username starts with
`demo_`) and their businesses/listings before re-creating them.
"""
import asyncio
import os
import uuid
import random
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient
from passlib.context import CryptContext
from dotenv import load_dotenv

load_dotenv()
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

# (username, buildings[(type, produces)], resources_on_hand, lots[(resource, amount, price_city)])
DEMO = [
    ("pavel_ton",  [("helios", "energy"), ("scrap_yard", "scrap")],
     {"energy": 120, "scrap": 30}, [("energy", 100, 3.4), ("scrap", 40, 3.6)]),
    ("crypto_guy", [("quartz_mine", "quartz")],
     {"quartz": 190}, [("quartz", 110, 3.6)]),
    ("whale_99",   [("helios", "energy"), ("nano_dc", "cu"), ("quartz_mine", "quartz"),
                    ("signal_tower", "traffic"), ("hydro_cooling", "cooling")],
     {"energy": 50}, []),
    ("nastya_k",   [("bio_farm", "biomass"), ("chips_factory", "chips")],
     {"biomass": 40, "chips": 10}, [("biomass", 80, 3.3), ("chips", 20, 90.0)]),
    ("igor_v",     [("nano_dc", "cu")],
     {"cu": 60}, [("cu", 150, 3.4)]),
    ("max_wolf",   [("signal_tower", "traffic"), ("hydro_cooling", "cooling")],
     {"traffic": 100, "cooling": 90}, [("traffic", 60, 3.9), ("cooling", 50, 3.5)]),
    ("ai_labs",    [("ai_lab", "neurocode")],
     {"neurocode": 15}, [("neurocode", 25, 110.0)]),
    ("sleeper_joe",[("scrap_yard", "scrap")],
     {"scrap": 290}, []),  # warehouse almost full, not selling
]

BIZ_CAPACITY = 300


async def main():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    # Cleanup previous demo data (marked with demo_seed flag)
    demo_users = await db.users.find({"demo_seed": True}, {"_id": 0, "id": 1}).to_list(1000)
    demo_ids = [u["id"] for u in demo_users]
    if demo_ids:
        await db.businesses.delete_many({"owner": {"$in": demo_ids}})
        await db.market_listings.delete_many({"seller_id": {"$in": demo_ids}})
        await db.users.delete_many({"id": {"$in": demo_ids}})
    print(f"Cleaned {len(demo_ids)} previous demo users")

    created = 0
    for username, buildings, resources, lots in DEMO:
        uid = str(uuid.uuid4())
        user = {
            "id": uid,
            "username": username,
            "display_name": username.replace("_", " ").title(),
            "email": f"{username}@example.com",
            "hashed_password": pwd.hash("Demo1234!"),
            "is_admin": False,
            "roles": [],
            "demo_seed": True,
            "balance_ton": round(random.uniform(5, 60), 2),
            "level": random.randint(1, 5),
            "xp": random.randint(0, 500),
            "language": "ru",
            "registration_method": "email",
            "resources": {k: int(v) for k, v in resources.items()},
            "businesses_owned": [],
            "plots_owned": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_login": datetime.now(timezone.utc).isoformat(),
        }
        biz_ids = []
        biz_by_res = {}
        for i, (btype, produces) in enumerate(buildings):
            bid = str(uuid.uuid4())
            biz = {
                "id": bid,
                "island_id": "ton_island",
                "plot_id": str(uuid.uuid4()),
                "x": random.randint(10, 40),
                "y": random.randint(10, 40),
                "business_type": btype,
                "level": random.randint(1, 4),
                "durability": random.randint(60, 100),
                "xp": 0,
                "owner": uid,
                "owner_wallet": None,
                "owner_username": username,
                "storage": {"capacity": BIZ_CAPACITY, "items": {}},
                "pending_income": 0,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "last_collection": datetime.now(timezone.utc).isoformat(),
            }
            biz_ids.append(bid)
            biz_by_res[produces] = bid
            await db.businesses.insert_one(biz)
        user["businesses_owned"] = biz_ids
        await db.users.insert_one(user)

        for resource, amount, price_city in lots:
            price_ton = price_city / 1000.0
            listing = {
                "id": str(uuid.uuid4()),
                "seller_id": uid,
                "seller_email": user["email"],
                "seller_username": username,
                "business_id": biz_by_res.get(resource),
                "resource_type": resource,
                "amount": int(amount),
                "price_per_unit": price_ton,
                "total_price": round(int(amount) * price_ton, 6),
                "status": "active",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            await db.market_listings.insert_one(listing)
        created += 1
        print(f"  {username}: {len(buildings)} biz, {len(lots)} lots")

    print(f"\nCreated {created} demo owners.")
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
