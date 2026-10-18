"""Register the «Неон» skin set (frontend/public/sprites/neon/<business_type>.webp)
for every business type. Idempotent.

    cd backend && python -m scripts.seed_neon_skins            # MONGO_URL / DB_NAME from env
    give a player the set:  db.users.update_one({...}, {"$addToSet": {"available_skins": "neon"}})
"""
import asyncio
import os
import uuid
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient

GROUP_KEY, GROUP_NAME = "neon", "Неон"
TYPES = ["helios", "nano_dc", "quartz_mine", "signal_tower", "hydro_cooling", "bio_farm", "scrap_yard",
         "chips_factory", "nft_studio", "ai_lab", "logistics_hub", "cyber_cafe", "repair_shop", "vr_club",
         "validator", "gram_bank", "dex", "casino", "arena", "incubator", "bridge"]


async def main():
    db = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))[os.environ.get("DB_NAME", "ton_city")]
    now = datetime.now(timezone.utc).isoformat()
    for t in TYPES:
        await db.business_skins.update_one(
            {"group_key": GROUP_KEY, "business_type": t, "level": 0},
            {"$set": {"group_key": GROUP_KEY, "group_name": GROUP_NAME, "business_type": t, "level": 0,
                      "image": f"/sprites/neon/{t}.webp", "is_standard": False, "height_pct": 100, "width_pct": 100},
             "$setOnInsert": {"id": str(uuid.uuid4()), "created_at": now}}, upsert=True)
    print(f"skin group '{GROUP_KEY}': {len(TYPES)} business types")


if __name__ == "__main__":
    asyncio.run(main())
