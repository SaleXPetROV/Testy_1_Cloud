"""Standalone one-time migration: encrypt existing plaintext TOTP 2FA secrets.

Self-contained — does NOT import the `security` package (so it won't pull in
pyotp/fastapi/etc). Only needs: cryptography, motor, python-dotenv.

Run with the SAME Python interpreter that runs the backend (the project's
virtualenv), from the backend/ directory:

    cd /var/www/gramcity/backend
    # find your backend interpreter, e.g. the venv used by supervisor/systemd:
    ./venv/bin/python migrate_2fa.py         # example
    # or, if deps are installed globally:
    python3 migrate_2fa.py

Idempotent: re-running only encrypts values still in plaintext.
"""
import asyncio
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from cryptography.fernet import Fernet
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(Path(__file__).resolve().parent / ".env")

FIELDS = ("two_factor_secret", "pending_2fa_secret")
_KEY = (os.environ.get("TOTP_ENC_KEY") or "").strip()
_BASE32_RE = re.compile(r"^[A-Z2-7]+=*$")  # pyotp secret alphabet


def _is_encrypted(fernet: Fernet, value: str) -> bool:
    try:
        fernet.decrypt(value.encode())
        return True
    except Exception:
        return False


async def main():
    if not _KEY:
        print("ERROR: TOTP_ENC_KEY is not set in backend/.env — aborting.")
        return
    try:
        fernet = Fernet(_KEY.encode())
    except Exception as e:
        print(f"ERROR: invalid TOTP_ENC_KEY: {e}")
        return

    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    query = {"$or": [{f: {"$exists": True, "$nin": [None, ""]}} for f in FIELDS]}
    scanned = migrated = already = 0
    async for user in db.users.find(query, {"_id": 1, **{f: 1 for f in FIELDS}}):
        scanned += 1
        updates = {}
        for f in FIELDS:
            val = user.get(f)
            if not val:
                continue
            if _is_encrypted(fernet, val):
                already += 1
                continue
            updates[f] = fernet.encrypt(val.encode()).decode()
        if updates:
            await db.users.update_one({"_id": user["_id"]}, {"$set": updates})
            migrated += 1

    print(f"2FA secret migration complete: users_scanned={scanned}, "
          f"users_encrypted={migrated}, fields_already_encrypted={already}")


if __name__ == "__main__":
    asyncio.run(main())
