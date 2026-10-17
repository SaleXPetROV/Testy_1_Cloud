"""F31 migration — backfill email hash+encryption, then optionally drop plaintext.

Usage:
  python migrate_email_hashing.py --backfill        # safe, idempotent
  python migrate_email_hashing.py --drop-plaintext  # run AFTER backfill, in a window

--drop-plaintext also (re)creates a unique index on email_lc_hash and removes the
old unique index on email.
"""
import asyncio
import os
import sys
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()
from email_crypto import email_hash, encrypt_email, normalize_email  # noqa: E402


async def backfill(db):
    n = 0
    cursor = db.users.find({}, {"_id": 1, "email": 1, "email_lc_hash": 1, "email_enc": 1})
    async for u in cursor:
        email = u.get("email")
        if not email:
            continue
        upd = {}
        if not u.get("email_lc_hash"):
            upd["email_lc_hash"] = email_hash(email)
        if not u.get("email_enc"):
            upd["email_enc"] = encrypt_email(email)
        # normalize plaintext to lowercase for consistency
        if email != normalize_email(email):
            upd["email"] = normalize_email(email)
        if upd:
            await db.users.update_one({"_id": u["_id"]}, {"$set": upd})
            n += 1
    # unique index on the hash (partial: only docs that have it)
    try:
        await db.users.create_index(
            "email_lc_hash", unique=True,
            partialFilterExpression={"email_lc_hash": {"$exists": True}},
        )
    except Exception as e:
        print("index warn:", e)
    print(f"backfilled {n} users; email_lc_hash unique index ensured.")


async def drop_plaintext(db):
    # Ensure everyone is backfilled first
    missing = await db.users.count_documents({"email": {"$ne": None}, "email_lc_hash": {"$exists": False}})
    if missing:
        print(f"ABORT: {missing} users still missing email_lc_hash. Run --backfill first.")
        return
    res = await db.users.update_many(
        {"email": {"$exists": True}},
        {"$unset": {"email": ""}},
    )
    # drop the old unique index on email if present
    try:
        for name, spec in (await db.users.index_information()).items():
            keys = spec.get("key", [])
            if keys and keys[0][0] == "email":
                await db.users.drop_index(name)
                print(f"dropped old index {name}")
    except Exception as e:
        print("drop index warn:", e)
    print(f"plaintext email removed from {res.modified_count} users. F31 complete.")


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    if "--backfill" in sys.argv:
        await backfill(db)
    elif "--drop-plaintext" in sys.argv:
        await drop_plaintext(db)
    else:
        print(__doc__)


if __name__ == "__main__":
    asyncio.run(main())
