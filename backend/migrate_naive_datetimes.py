"""
One-shot migration: normalize naive datetime STRINGS in Mongo to timezone-aware
UTC ISO strings (append '+00:00').

Root cause it fixes
-------------------
Some documents stored datetimes WITHOUT timezone info, e.g.
    "2026-09-13T15:00:00"        (naive)
instead of
    "2026-09-13T15:00:00+00:00"  (aware, UTC)

Comparing/subtracting a naive datetime with `datetime.now(timezone.utc)` raises
`TypeError: can't compare offset-naive and offset-aware datetimes`, which bubbled
up as HTTP 500 (e.g. /api/my/businesses, /api/my/active-buff-multipliers).

The application code was also hardened (core/dtutils.to_aware) so naive values no
longer crash at runtime — this migration additionally cleans the stored data so
the first cause disappears.

Idempotent: safe to re-run. Only rewrites values that are naive ISO strings.
Values that already carry an offset ('...+00:00' / '...Z') are left untouched.

Run:  cd /app/backend && python migrate_naive_datetimes.py
"""
import asyncio
import os
import re
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

# Matches an ISO datetime string that has NO timezone info (no trailing Z / ±HH:MM).
NAIVE_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?$")

# Primary target requested: `expires_at` everywhere. Plus the other datetime
# fields that runtime code compares against "now".
TOP_LEVEL_FIELDS = {
    "expires_at", "accepted_at", "started_at", "created_at", "completed_at",
    "overdue_since", "last_payment", "last_collection", "built_at",
    "last_wear_update", "upgraded_at", "on_sale_at", "ready_at",
    "withdrawal_blocked_until", "withdraw_lock_until", "last_email_change",
    "opens_at", "scheduled_at", "inactive_since", "last_update",
}

# Nested list fields: {collection: {list_field: [date_keys...]}}
NESTED_LIST_FIELDS = {
    "users": {"active_resource_buffs": ["expires_at", "activated_at"]},
}


def normalize_str(v):
    """Return an aware-UTC ISO string if `v` is a naive ISO string, else None."""
    if not isinstance(v, str):
        return None
    if not NAIVE_ISO.match(v.strip()):
        return None
    try:
        dt = datetime.fromisoformat(v.strip())
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is not None:
        return None
    return dt.replace(tzinfo=timezone.utc).isoformat()


async def fix_top_level(db, coll_name):
    coll = db[coll_name]
    fixed = 0
    # Only look at fields that actually appear as naive ISO strings.
    for field in TOP_LEVEL_FIELDS:
        query = {field: {"$type": "string", "$regex": NAIVE_ISO.pattern}}
        cursor = coll.find(query, {"_id": 1, field: 1})
        async for doc in cursor:
            new_val = normalize_str(doc.get(field))
            if new_val:
                await coll.update_one({"_id": doc["_id"]}, {"$set": {field: new_val}})
                fixed += 1
    return fixed


async def fix_nested(db, coll_name, list_field, date_keys):
    coll = db[coll_name]
    fixed_docs = 0
    cursor = coll.find({list_field: {"$type": "array", "$ne": []}},
                       {"_id": 1, list_field: 1})
    async for doc in cursor:
        arr = doc.get(list_field) or []
        changed = False
        for item in arr:
            if not isinstance(item, dict):
                continue
            for k in date_keys:
                nv = normalize_str(item.get(k))
                if nv:
                    item[k] = nv
                    changed = True
        if changed:
            await coll.update_one({"_id": doc["_id"]}, {"$set": {list_field: arr}})
            fixed_docs += 1
    return fixed_docs


async def main():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    collections = await db.list_collection_names()
    total_fields_fixed = 0
    per_collection = {}

    for coll_name in collections:
        if coll_name.startswith("system."):
            continue
        n = await fix_top_level(db, coll_name)
        if n:
            per_collection[coll_name] = per_collection.get(coll_name, 0) + n
            total_fields_fixed += n

    total_nested_docs = 0
    for coll_name, spec in NESTED_LIST_FIELDS.items():
        if coll_name not in collections:
            continue
        for list_field, date_keys in spec.items():
            m = await fix_nested(db, coll_name, list_field, date_keys)
            total_nested_docs += m
            if m:
                per_collection[f"{coll_name}.{list_field}[]"] = m

    print("\n" + "=" * 60)
    print("NAIVE DATETIME NORMALIZATION — SUMMARY")
    print("=" * 60)
    for k in sorted(per_collection):
        print(f"  {k}: {per_collection[k]} value(s) fixed")
    if not per_collection:
        print("  Nothing to fix — all datetime strings already timezone-aware.")
    print("-" * 60)
    print(f"Top-level field values fixed: {total_fields_fixed}")
    print(f"Nested (buffs) docs fixed:    {total_nested_docs}")
    print("=" * 60)

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
