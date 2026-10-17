"""One-time migration: encrypt existing plaintext TOTP 2FA secrets at rest.

Scans users for `two_factor_secret` / `pending_2fa_secret` that are NOT already
Fernet-encrypted (i.e. legacy base32 plaintext) and re-stores them encrypted
with TOTP_ENC_KEY. Idempotent — running again is a no-op once all are encrypted.

Usage:
    cd /app/backend && python -m security.migrate_2fa_encryption
"""
import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from security.totp_crypto import encrypt_secret, is_encrypted, encryption_enabled

FIELDS = ("two_factor_secret", "pending_2fa_secret")


async def main():
    if not encryption_enabled():
        print("ERROR: TOTP_ENC_KEY is not configured — aborting (nothing encrypted).")
        return
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    query = {"$or": [{f: {"$exists": True, "$nin": [None, ""]}} for f in FIELDS]}
    migrated = 0
    scanned = 0
    async for user in db.users.find(query, {"_id": 1, **{f: 1 for f in FIELDS}}):
        scanned += 1
        updates = {}
        for f in FIELDS:
            val = user.get(f)
            if val and not is_encrypted(val):
                updates[f] = encrypt_secret(val)
        if updates:
            await db.users.update_one({"_id": user["_id"]}, {"$set": updates})
            migrated += 1
    print(f"2FA secret migration complete: scanned={scanned}, encrypted={migrated}")


if __name__ == "__main__":
    asyncio.run(main())
