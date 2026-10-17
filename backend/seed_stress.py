"""Stress-seed: create ~1200 users and ~1500 businesses so we can benchmark
economic_tick performance close to the production scale (>1100 users).

Usage:  python seed_stress.py [num_users]
"""
import asyncio
import os
import sys
import random
import uuid
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

BUSINESS_TYPES = [
    "helios", "nano_dc", "quartz_mine", "signal_tower", "hydro_cooling",
    "bio_food", "scrap_yard", "chips_factory", "nft_studio", "ai_lab",
    "logistics_hub", "cyber_cafe", "repair_shop", "vr_club",
]

RESOURCE_TYPES = [
    "energy", "cu", "quartz", "traffic", "cooling", "biomass", "scrap",
    "chips", "nft", "neurocode", "logistics", "repair_kits", "vr_experience",
]


async def main():
    num_users = int(sys.argv[1]) if len(sys.argv) > 1 else 1200
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    print(f"🌱 Stress-seeding {num_users} users and their businesses…")

    # Wipe previous stress data (identified by prefix)
    await db.users.delete_many({"username": {"$regex": "^stress_"}})
    await db.businesses.delete_many({"stress_seed": True})

    now_iso = datetime.now(timezone.utc).isoformat()
    users_docs = []
    for i in range(1, num_users + 1):
        uid = str(uuid.uuid4())
        wallet = f"0:stress{i:06d}{'a' * 46}"[:66]
        resources = {r: random.randint(50, 500) for r in RESOURCE_TYPES}
        users_docs.append({
            "id": uid,
            "wallet_address": wallet,
            "raw_address": wallet,
            "username": f"stress_{i}",
            "email": f"stress_{i}@example.com",
            "hashed_password": "$2b$12$stubstubstubstubstubstubstubstubstubstubstubstubstubstub",
            "balance_ton": 100.0,
            "level": 1,
            "xp": 0,
            "language": "en",
            "resources": resources,
            "created_at": now_iso,
        })
    if users_docs:
        await db.users.insert_many(users_docs)
        print(f"✅ inserted {len(users_docs)} users")

    biz_docs = []
    for u in users_docs:
        # 0-3 businesses per user, weighted toward 1
        n = random.choices([0, 1, 2, 3], weights=[10, 60, 25, 5])[0]
        for _ in range(n):
            biz_docs.append({
                "id": str(uuid.uuid4()),
                "island_id": "ton_island",
                "plot_id": str(uuid.uuid4()),
                "business_type": random.choice(BUSINESS_TYPES),
                "level": random.randint(1, 5),
                "durability": random.uniform(30.0, 100.0),
                "owner": u["id"],
                "owner_wallet": u["wallet_address"],
                "owner_username": u["username"],
                "storage": {"capacity": 5000, "items": {}},
                "last_collection": now_iso,
                "last_wear_update": now_iso,
                "last_tick": now_iso,
                "created_at": now_iso,
                "stress_seed": True,
            })
    if biz_docs:
        await db.businesses.insert_many(biz_docs)
        print(f"✅ inserted {len(biz_docs)} businesses")

    print("🎯 Stress seed complete.")
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
