"""
One-shot migration:
  1) Normalize every user's `wallet_address` / `raw_address` pair to the
     canonical (user_friendly, raw) form from `core.helpers.normalize_wallet`.
  2) Detect and RESOLVE duplicate wallets — where more than one account
     claims the same `raw_address`. Policy (user-approved):
        Keep the OLDEST account (earliest `created_at`), DELETE the rest.

Idempotent: safe to re-run. Prints a report at the end.
"""
import asyncio
import os
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

from core.helpers import normalize_wallet  # noqa: E402


def _parse_created(v):
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        except Exception:
            return datetime.now(timezone.utc)
    return datetime.now(timezone.utc)


async def main():
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    normalized = 0
    invalid = 0
    unchanged = 0
    per_raw: dict[str, list[dict]] = {}

    async for user in db.users.find({"wallet_address": {"$nin": [None, ""]}}):
        addr = user.get("wallet_address")
        uf, raw = normalize_wallet(addr)
        if not uf or not raw:
            invalid += 1
            # Clear invalid — better than leaving a poisoned value that
            # future lookups can't match.
            await db.users.update_one(
                {"_id": user["_id"]},
                {"$unset": {"wallet_address": "", "raw_address": ""}},
            )
            continue

        need_update = (
            user.get("wallet_address") != uf
            or user.get("raw_address") != raw
        )
        if need_update:
            await db.users.update_one(
                {"_id": user["_id"]},
                {"$set": {"wallet_address": uf, "raw_address": raw}},
            )
            normalized += 1
        else:
            unchanged += 1

        per_raw.setdefault(raw, []).append({
            "_id": user["_id"],
            "id": user.get("id"),
            "email": user.get("email"),
            "username": user.get("username"),
            "created_at": _parse_created(user.get("created_at")),
        })

    dup_groups = {r: g for r, g in per_raw.items() if len(g) > 1}
    deleted_accounts = 0
    for raw, group in dup_groups.items():
        group.sort(key=lambda u: u["created_at"])
        keeper = group[0]
        losers = group[1:]
        loser_ids = [u["_id"] for u in losers]
        res = await db.users.delete_many({"_id": {"$in": loser_ids}})
        deleted_accounts += res.deleted_count
        print(f"[dup] raw={raw[:24]}… kept={keeper.get('email') or keeper.get('username') or keeper.get('id')} "
              f"deleted={[u.get('email') or u.get('username') or u.get('id') for u in losers]}")

    print("\n" + "=" * 60)
    print("WALLET NORMALIZATION MIGRATION — SUMMARY")
    print("=" * 60)
    print(f"Normalized (rewritten to canonical form): {normalized}")
    print(f"Unchanged (already canonical):            {unchanged}")
    print(f"Invalid addresses cleared:                {invalid}")
    print(f"Duplicate wallet groups found:            {len(dup_groups)}")
    print(f"Duplicate accounts deleted:               {deleted_accounts}")
    print("=" * 60)

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
