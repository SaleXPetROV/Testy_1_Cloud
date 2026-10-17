"""Dev-only: seed ONE level-0 (leased) business for a user at a given cell so we
can screenshot the "My Businesses" + map UI at different lease-timer states.

Usage:
    python seed_zero_lease_demo.py <user_email> <hours_left>

<hours_left> sets expires_at = now + hours_left (float). Re-running updates the
same cell in place (idempotent-ish for demo purposes).
"""
import asyncio
import sys
import uuid
from datetime import datetime, timezone, timedelta

from motor.motor_asyncio import AsyncIOMotorClient
import os

X, Y = 28, 16
BIZ_TYPE = "bio_farm"


async def main(email: str, hours_left: float):
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    from ton_island import CITY_BUSINESSES, generate_ton_island_map
    from business_config import get_storage_capacity

    user = await db.users.find_one({"email": email}, {"_id": 0})
    if not user:
        print(f"user {email} not found")
        return
    user_id = user["id"]

    # find the cell in the generated map for zone/price
    island = await db.islands.find_one({"id": "ton_island"}, {"_id": 0})
    if not island:
        island = generate_ton_island_map()
        await db.islands.insert_one(island.copy())
    cell = next((c for c in island["cells"] if c["x"] == X and c["y"] == Y), None)
    if not cell:
        print("cell not found")
        return

    price_ton = cell.get("price_ton", 6.5)
    price_city = cell.get("price_city", price_ton * 1000)
    biz_config = CITY_BUSINESSES.get(BIZ_TYPE)

    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(hours=hours_left)).isoformat()

    # wipe any previous demo docs at this cell
    old = await db.businesses.find_one({"island_id": "ton_island", "x": X, "y": Y}, {"_id": 0})
    if old:
        await db.land_listings.delete_many({"business_id": old.get("id")})
    await db.businesses.delete_many({"island_id": "ton_island", "x": X, "y": Y})
    await db.plots.delete_many({"island_id": "ton_island", "x": X, "y": Y})

    business_id = str(uuid.uuid4())
    plot_id = str(uuid.uuid4())

    full_business = {
        "id": business_id,
        "business_type": BIZ_TYPE,
        "name": biz_config["name"],
        "icon": biz_config["icon"],
        "tier": biz_config["tier"],
        "level": 0,
        "owner": user_id,
        "owner_username": user.get("username"),
        "plot_id": plot_id,
        "island_id": "ton_island",
        "x": X,
        "y": Y,
        "zone": cell["zone"],
        "skin_group": "standard",
        "durability": 100,
        "is_active": True,
        "pending_income": 0,
        "total_income": 0,
        "monthly_income_ton": biz_config["monthly_income_ton"],
        "monthly_income_city": biz_config["monthly_income_ton"] * 1000,
        "base_cost_ton": price_ton,
        "storage": {"capacity": get_storage_capacity(BIZ_TYPE, 1) or biz_config.get("storage_capacity", 100), "items": {}},
        "workers": [],
        "on_sale": True,
        "is_zero_business": True,
        "zero_map_price": price_ton,
        "expires_at": expires_at,
        "built_at": now.isoformat(),
        "last_collection": now.isoformat(),
    }
    business_data = {
        "id": business_id,
        "type": BIZ_TYPE,
        "name": biz_config["name"],
        "icon": biz_config["icon"],
        "tier": biz_config["tier"],
        "level": 0,
        "is_zero_business": True,
        "expires_at": expires_at,
        "monthly_income_ton": biz_config["monthly_income_ton"],
        "monthly_income_city": biz_config["monthly_income_ton"] * 1000,
        "built_at": now.isoformat(),
        "last_collection": now.isoformat(),
    }
    plot = {
        "id": plot_id,
        "island_id": "ton_island",
        "x": X,
        "y": Y,
        "zone": cell["zone"],
        "price_ton": price_ton,
        "price_city": price_city,
        "owner": user_id,
        "owner_username": user.get("username"),
        "owner_avatar": user.get("avatar"),
        "business": business_data,
        "business_id": business_id,
        "is_empty": False,
        "warehouses": [],
        "purchased_at": now.isoformat(),
        "on_sale": True,
    }

    await db.businesses.insert_one(full_business.copy())
    await db.plots.insert_one(plot.copy())
    await db.users.update_one({"id": user_id}, {"$addToSet": {"businesses_owned": business_id, "plots_owned": plot_id}})

    # auto marketplace listing (admin proceeds), mirrors zero_business.create_zero_listing
    import zero_business as zb
    listing_id, price = await zb.create_zero_listing(
        db, full_business, user_id, user.get("username"), uuid, datetime, timezone
    )
    await db.businesses.update_one({"id": business_id}, {"$set": {"zero_listing_id": listing_id}})
    await db.plots.update_one({"id": plot_id}, {"$set": {"listing_id": listing_id, "business.zero_listing_id": listing_id}})

    print(f"seeded level-0 {BIZ_TYPE} at ({X},{Y}) for {email}; expires_at={expires_at}; listing={listing_id} price={price}")
    client.close()


if __name__ == "__main__":
    email = sys.argv[1] if len(sys.argv) > 1 else "leasetest@example.com"
    hours = float(sys.argv[2]) if len(sys.argv) > 2 else 71.0
    asyncio.run(main(email, hours))
