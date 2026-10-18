"""
Seed a single working business for each QA test user so the «Business» screen
shows the full adaptive layout (durability / warehouse / income chips +
Repair / Start-shift / Upgrade buttons).

Usage:
    cd /app/backend && python -m scripts.seed_test_business
"""
import asyncio
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from core.database import db

try:
    from core.helpers import get_storage_capacity
except Exception:  # pragma: no cover
    def get_storage_capacity(_bt, _lvl):
        return 500

BUSINESS_TYPE = "bio_farm"
USERNAMES = ["sanyanazarov212", "testuser"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def seed():
    for uname in USERNAMES:
        user = await db.users.find_one({"username": uname})
        if not user:
            print(f"[seed-biz] user not found: {uname}")
            continue
        uid = user["id"]

        # remove any previous seeded business for a clean, idempotent run
        await db.businesses.delete_many({"owner": uid, "seed_qa": True})

        biz_id = str(uuid.uuid4())
        try:
            cap = get_storage_capacity(BUSINESS_TYPE, 1) or 500
        except Exception:
            cap = 500

        full_business = {
            "id": biz_id,
            "business_type": BUSINESS_TYPE,
            "tier": 1,
            "level": 3,
            "owner": uid,
            "owner_username": uname,
            "owner_wallet": user.get("wallet_address"),
            "plot_id": f"qa-plot-{uid}",
            "island_id": "ton_island",
            "x": 5,
            "y": 5,
            "zone": "residential",
            "skin_group": "standard",
            "durability": 100,
            "is_active": True,
            "building_progress": 100,
            "pending_income": 0,
            "total_income": 0,
            "storage": {"capacity": cap, "items": {}},
            "workers": [],
            "on_sale": False,
            "built_at": _now_iso(),
            "created_at": _now_iso(),
            "last_collection": _now_iso(),
            "seed_qa": True,
        }
        await db.businesses.insert_one(full_business.copy())
        print(f"[seed-biz] created {BUSINESS_TYPE} for {uname} id={biz_id}")


if __name__ == "__main__":
    asyncio.run(seed())
