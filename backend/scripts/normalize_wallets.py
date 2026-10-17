"""
One-off data migration for the wallet-auth fix.

1) Normalizes every stored `wallet_address` to its canonical user-friendly
   form and (re)computes `raw_address` (0:hex) as the source of truth.
2) Detects wallets bound to MORE THAN ONE account (data-integrity violation)
   and DELETES the duplicate accounts, keeping the OLDEST one (earliest
   created_at, falling back to wallet_linked_at / _id).

Run:  python scripts/normalize_wallets.py           # dry-run (report only)
      python scripts/normalize_wallets.py --apply   # perform changes
"""
import os
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from motor.motor_asyncio import AsyncIOMotorClient
from core.helpers import normalize_wallet


def _sort_key(u):
    # Oldest first: created_at, then wallet_linked_at, then _id as tie-breaker.
    return (
        str(u.get("created_at") or "9999"),
        str(u.get("wallet_linked_at") or "9999"),
        str(u.get("_id")),
    )


async def main(apply: bool):
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    users = await db.users.find({"wallet_address": {"$exists": True, "$ne": None}}).to_list(length=None)
    print(f"Scanning {len(users)} user(s) with a wallet_address...\n")

    normalized = 0
    invalid = 0
    by_raw = {}

    for u in users:
        uf, raw = normalize_wallet(u.get("wallet_address"))
        if not uf or not raw:
            invalid += 1
            print(f"  ⚠️ INVALID wallet on user={u.get('username')} ({u.get('wallet_address')}) — leaving as-is")
            continue
        # Heal drifted forms
        if u.get("wallet_address") != uf or u.get("raw_address") != raw:
            normalized += 1
            print(f"  🔧 normalize user={u.get('username')}: {u.get('wallet_address')} -> {uf}")
            if apply:
                await db.users.update_one({"_id": u["_id"]}, {"$set": {"wallet_address": uf, "raw_address": raw}})
        by_raw.setdefault(raw, []).append(u)

    # Find duplicates (same wallet on >1 account)
    dup_groups = {raw: accts for raw, accts in by_raw.items() if len(accts) > 1}
    deleted = 0
    print(f"\nDuplicate wallets (bound to >1 account): {len(dup_groups)}")
    for raw, accts in dup_groups.items():
        accts_sorted = sorted(accts, key=_sort_key)
        keep = accts_sorted[0]
        drop = accts_sorted[1:]
        print(f"  wallet raw={raw}")
        print(f"    KEEP  : {keep.get('username')} (id={keep.get('id')}, created={keep.get('created_at')})")
        for d in drop:
            print(f"    DELETE: {d.get('username')} (id={d.get('id')}, created={d.get('created_at')})")
            if apply:
                await db.users.delete_one({"_id": d["_id"]})
                deleted += 1

    print("\n===== SUMMARY =====")
    print(f"  normalized wallet forms : {normalized}")
    print(f"  invalid addresses       : {invalid}")
    print(f"  duplicate wallet groups : {len(dup_groups)}")
    print(f"  accounts deleted        : {deleted if apply else '(dry-run — 0)'}")
    print(f"  mode                    : {'APPLIED' if apply else 'DRY-RUN'}")
    client.close()


if __name__ == "__main__":
    apply = "--apply" in sys.argv
    asyncio.run(main(apply))
