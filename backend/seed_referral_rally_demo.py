"""
Seed demo data for the Referral Rally promo leaderboard.

Creates an active referral_rally campaign + a few referrers with referred users
(some 'active' = have plots_owned, most not) so the admin leaderboard can be
verified to surface real referrers WITH their counts (regression fix: after the
presale sort switched to 'active', referrers with 0 active but many total were
buried behind arbitrary 0/0 users).

Idempotent: removes previously seeded rally-demo users/campaign (marked
`rally_demo: True`) before re-creating.
"""
import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()
MSK = timezone(timedelta(hours=3))

# (username, total_refs, active_refs)
REFERRERS = [
    ("rally_topguy", 25, 3),
    ("rally_second", 21, 0),
    ("rally_third", 4, 4),
    ("rally_fourth", 3, 1),
    ("rally_fifth", 1, 0),
]


async def main():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    # Cleanup previous rally-demo data
    old = await db.users.find({"rally_demo": True}, {"_id": 0, "id": 1}).to_list(5000)
    old_ids = [u["id"] for u in old]
    if old_ids:
        await db.users.delete_many({"id": {"$in": old_ids}})
    await db.promo_campaigns.delete_many({"rally_demo": True})
    print(f"Cleaned {len(old_ids)} previous rally-demo users")

    # Active campaign (ends in 2 days)
    now = datetime.now(MSK)
    campaign = {
        "id": str(uuid.uuid4()),
        "type": "referral_rally",
        "status": "active",
        "starts_at": now.isoformat(),
        "ends_at": (now + timedelta(days=2)).isoformat(),
        "frozen_at": None,
        "config": {"prizes_ton": [100.0, 50.0, 20.0], "per_active_ton": 1.5},
        "winners": [],
        "created_by": "seed",
        "created_at": now.isoformat(),
        "rally_demo": True,
    }
    # Only insert if no active campaign already exists
    existing = await db.promo_campaigns.find_one({"type": "referral_rally", "status": "active"}, {"_id": 0})
    if existing:
        print(f"Active campaign already exists (id={existing['id']}), reusing it")
    else:
        await db.promo_campaigns.insert_one(dict(campaign))
        print(f"Created active campaign id={campaign['id']}")

    total_refs = 0
    for username, total, active in REFERRERS:
        rid = str(uuid.uuid4())
        await db.users.insert_one({
            "id": rid,
            "username": username,
            "display_name": username.replace("_", " ").title(),
            "email": f"{username}@example.com",
            "rally_demo": True,
            "plots_owned": [],
            "created_at": now.isoformat(),
        })
        for i in range(total):
            is_active = i < active
            await db.users.insert_one({
                "id": str(uuid.uuid4()),
                "username": f"{username}_ref{i}",
                "email": f"{username}_ref{i}@example.com",
                "referrerId": rid,
                "rally_demo": True,
                "plots_owned": (["plot_%d" % i] if is_active else []),
                "created_at": now.isoformat(),
            })
            total_refs += 1
        print(f"  {username}: total={total}, active={active}")

    print(f"\nCreated {len(REFERRERS)} referrers, {total_refs} referred users.")
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
