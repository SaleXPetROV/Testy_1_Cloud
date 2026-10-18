"""
migrate_remove_trial_center.py
================================
ONE command that fully retires the Trial Center from every account:

  1) Finds every user who BOUGHT a Trial Center. A user counts as a buyer if
     EITHER they own a Trial Center business (businesses collection:
     is_trial == True  OR  business_type == "trial_center")
     OR they carry the purchase flag  trial_center_purchased == True.

  2) Credits EACH such user with +1 GRAM (== 1.0 on `bonus_balance`, the
     in-game bonus balance) — EXACTLY ONCE per user, even if they somehow
     owned several trial businesses. This is the "instead of the trial center
     they get 1 GRAM" compensation.

  3) DELETES all Trial Center businesses from the `businesses` collection.

  4) Clears the per-user trial flags so nothing about the trial remains
     (trial_center_purchased / trial_center_started_at / trial_center_hidden).

The whole thing runs as a SINGLE command:

    python migrate_remove_trial_center.py            # apply changes
    python migrate_remove_trial_center.py --dry-run  # preview only, no writes

Idempotent & safe to re-run: a one-time marker `trial_center_refunded=True`
is written on every refunded user, so running it again NEVER double-credits.

Connection comes from the environment (same as the app):
    MONGO_URL   e.g. mongodb://localhost:27017
    DB_NAME     the game database name
It reads backend/.env automatically.
"""
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")

# +1 GRAM == 1 TON, credited to the in-game bonus balance.
GRAM_REFUND = 1.0
REFUND_FIELD = "bonus_balance"

# A business is a Trial Center if EITHER of these matches.
TRIAL_BIZ_FILTER = {"$or": [{"is_trial": True}, {"business_type": "trial_center"}]}


def _owner_clauses(biz: dict):
    """Resolve the owner of a trial business by ANY identifier it might carry
    (wallet / email / telegram id / mongo _id), mirroring the app's own lookup
    so wallet/Telegram/mini-app accounts are matched correctly."""
    keys = [k for k in {biz.get("owner"), biz.get("owner_wallet")} if k]
    if not keys:
        return None
    clauses = []
    for field in ("id", "wallet_address", "raw_address", "email",
                  "telegram_chat_id", "telegram_id", "telegram_user_id",
                  "username", "google_id"):
        clauses.extend([{field: k} for k in keys])
    for k in keys:
        try:
            ik = int(str(k))
            clauses.extend([{"telegram_chat_id": ik}, {"telegram_id": ik},
                            {"telegram_user_id": ik}])
        except (TypeError, ValueError):
            pass
    try:
        from bson import ObjectId
        for k in keys:
            if ObjectId.is_valid(str(k)):
                clauses.append({"_id": ObjectId(str(k))})
    except Exception:
        pass
    return {"$or": clauses}


async def main(dry_run: bool = False):
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    print(f"→ DB: {db_name}   dry_run={dry_run}")

    # --- 1) Collect the distinct set of buyers (as user _id) --------------
    buyer_ids = set()

    # (a) owners resolved from every trial business
    trial_count = await db.businesses.count_documents(TRIAL_BIZ_FILTER)
    async for biz in db.businesses.find(TRIAL_BIZ_FILTER):
        of = _owner_clauses(biz)
        if not of:
            continue
        udoc = await db.users.find_one(of, {"_id": 1})
        if udoc:
            buyer_ids.add(udoc["_id"])

    # (b) anyone flagged as a trial-center purchaser
    async for udoc in db.users.find({"trial_center_purchased": True}, {"_id": 1}):
        buyer_ids.add(udoc["_id"])

    print(f"→ trial businesses found: {trial_count}")
    print(f"→ distinct buyers to refund (1 GRAM each): {len(buyer_ids)}")

    # --- 2) Credit +1 GRAM once per buyer (idempotent via marker) ---------
    refunded = 0
    skipped_already = 0
    for uid in buyer_ids:
        udoc = await db.users.find_one(
            {"_id": uid}, {"_id": 1, "trial_center_refunded": 1, "bonus_balance": 1}
        )
        if not udoc:
            continue
        if udoc.get("trial_center_refunded") is True:
            skipped_already += 1
            continue
        if dry_run:
            refunded += 1
            continue
        await db.users.update_one(
            {"_id": uid},
            {
                "$inc": {REFUND_FIELD: GRAM_REFUND},
                "$set": {"trial_center_refunded": True},
                "$unset": {
                    "trial_center_purchased": "",
                    "trial_center_started_at": "",
                    "trial_center_hidden": "",
                },
            },
        )
        refunded += 1

    # --- 3) Delete all Trial Center businesses ----------------------------
    if dry_run:
        deleted = trial_count
    else:
        res = await db.businesses.delete_many(TRIAL_BIZ_FILTER)
        deleted = res.deleted_count

    # --- 4) Safety sweep: clear trial flags on ANY leftover users ---------
    if not dry_run:
        await db.users.update_many(
            {"$or": [
                {"trial_center_purchased": {"$exists": True}},
                {"trial_center_started_at": {"$exists": True}},
                {"trial_center_hidden": {"$exists": True}},
            ]},
            {"$unset": {
                "trial_center_purchased": "",
                "trial_center_started_at": "",
                "trial_center_hidden": "",
            }},
        )

    print("\n===== SUMMARY =====")
    print(f"  trial businesses deleted : {deleted}")
    print(f"  users credited +1 GRAM   : {refunded}")
    print(f"  users already refunded   : {skipped_already} (skipped, no double credit)")
    print(f"  GRAM credited to field   : {REFUND_FIELD}")
    print("  dry-run (no writes)      :" if dry_run else "  changes applied.", dry_run or "")
    client.close()


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    asyncio.run(main(dry_run=dry))
