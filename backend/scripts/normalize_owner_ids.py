"""Owner references -> user ids (idempotent).

Old records may store the owner / seller / buyer as a WALLET or an E-MAIL instead of the user id.
That keeps personal data in plain text in those collections (even with PII encryption on) and makes
every owner lookup check three fields. This rewrites every such reference to the user's id.

    cd backend
    python -m scripts.normalize_owner_ids            # DRY RUN: what would change
    python -m scripts.normalize_owner_ids --apply

The server also runs it once at startup (nothing to do = no writes). Env: MONGO_URL, DB_NAME.
"""
import argparse, asyncio, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

FIELDS = {
    "businesses": ["owner", "rental_owner"],
    "plots": ["owner"],
    "land_listings": ["seller_id", "buyer_id"],
    "market_listings": ["seller_id"],
    "contracts": ["patron_id", "vassal_id"],
    "supply_contracts": ["seller_id", "buyer_id"],
}


async def run(apply: bool, db=None) -> dict:
    db = db if db is not None else AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))[os.environ.get("DB_NAME", "ton_city")]
    ids = set()
    async for u in db.users.find({}, {"_id": 0, "id": 1}):
        if u.get("id"):
            ids.add(u["id"])
    cache, stats = {}, {}
    for coll, fields in FIELDS.items():
        for f in fields:
            try:
                values = await db[coll].distinct(f)
            except Exception:
                continue
            changed = 0
            for v in values:
                if not v or not isinstance(v, str) or v in ids:
                    continue
                if v not in cache:              # wallet or e-mail -> the user's id
                    u = await db.users.find_one({"$or": [{"wallet_address": v}, {"email": v}, {"raw_address": v}]}, {"_id": 0, "id": 1})
                    cache[v] = (u or {}).get("id")
                uid = cache[v]
                if not uid:
                    continue
                if apply:
                    r = await db[coll].update_many({f: v}, {"$set": {f: uid}})
                    changed += r.modified_count
                else:
                    changed += await db[coll].count_documents({f: v})
            if changed:
                stats[f"{coll}.{f}"] = changed
    print(("APPLIED " if apply else "DRY RUN ") + str(stats or "nothing to change"))
    return stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true")
    asyncio.run(run(ap.parse_args().apply))
