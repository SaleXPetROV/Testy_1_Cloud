"""
Seed script for two test users used during manual QA of the tutorial-reward
rules and the marketplace T3 flow.

Users created:
  • admin   — SEED_ADMIN_EMAIL / SEED_ADMIN_PASSWORD
  • regular — SEED_USER_EMAIL / SEED_USER_PASSWORD

Both come pre-configured with:
  • tutorial_completed = True
  • tutorial_t3_reward_granted = True
  • resources = {"neuro_core_tutorial": 1}   ← the one-shot tutorial reward
      sits in a SEPARATE resource id and is intentionally not sellable.
  • resources[neuro_core] = 2 (regular sellable stock, for testing)
  • balance_ton = 100
so the app can be exercised immediately after login.

Usage:
    cd /app/backend && python -m scripts.seed_test_users
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Ensure /app/backend is on sys.path when run as a plain script.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from motor.motor_asyncio import AsyncIOMotorClient
from passlib.context import CryptContext

from email_crypto import email_fields

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Credentials come from the environment so they are not committed to the repo.
_ADMIN_PW = os.environ.get("SEED_ADMIN_PASSWORD")
_USER_PW = os.environ.get("SEED_USER_PASSWORD")
if not _ADMIN_PW or not _USER_PW:
    raise SystemExit("Set SEED_ADMIN_PASSWORD and SEED_USER_PASSWORD before seeding test users.")

TEST_USERS = [
    {
        "email": os.environ.get("SEED_ADMIN_EMAIL", "sanyanazarov212@gmail.com"),
        "password": _ADMIN_PW,
        "username": "sanyanazarov212",
        "is_admin": True,
    },
    {
        "email": os.environ.get("SEED_USER_EMAIL", "testuser@example.com"),
        "password": _USER_PW,
        "username": "testuser",
        "is_admin": False,
    },
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def build_user_doc(spec: dict) -> dict:
    email = spec["email"].strip().lower()
    return {
        "id": str(uuid.uuid4()),
        "username": spec["username"],
        "display_name": spec["username"],
        **email_fields(email),
        "hashed_password": pwd_context.hash(spec["password"]),
        "wallet_address": None,
        "raw_address": None,
        "avatar": None,
        "balance_ton": 100.0,
        "language": "ru",
        "level": "novice",
        "xp": 0,
        "total_turnover": 0,
        "total_income": 0,
        "plots_owned": [],
        "businesses_owned": [],
        "resources": {
            # Regular sellable stock — can be listed on the marketplace even
            # without owning a business (v2.3 rule).
            "neuro_core": 2,
            # One-shot tutorial reward — stored in a separate `<base>_tutorial`
            # key so it renders as its own card in "My Resources" and cannot
            # be sold on the marketplace. Consumed FIRST when activating buffs.
            "neuro_core_tutorial": 1,
        },
        "active_resource_buffs": [],
        "is_admin": spec["is_admin"],
        "email_verified": True,
        "registration_method": "email",
        "tutorial_completed": True,
        "tutorial_active": False,
        "tutorial_t3_reward_granted": True,
        "tutorial_t3_reward_choice": "neuro_core",
        "tutorial_t3_reward_granted_at": _now().isoformat(),
        # Pending one-shot flag — auto-activates the tutorial Neuro-Core as a buff
        # the moment the user buys their (first) business. Cleared once applied.
        "tutorial_pending_t3_auto_activate": "neuro_core",
        "created_at": _now(),
        "last_login": _now(),
    }


async def main() -> None:
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    for spec in TEST_USERS:
        email = spec["email"].strip().lower()
        # Idempotent: replace-in-place so the script can be re-run safely.
        existing = await db.users.find_one({"email": email})
        doc = build_user_doc(spec)
        if existing:
            # Keep the original id so joined data (businesses, plots) stays valid.
            doc["id"] = existing.get("id", doc["id"])
            doc["created_at"] = existing.get("created_at", doc["created_at"])
            await db.users.replace_one({"_id": existing["_id"]}, {**existing, **doc})
            print(f"[seed] updated: {email} (admin={spec['is_admin']}) id={doc['id']}")
        else:
            await db.users.insert_one(doc)
            print(f"[seed] created: {email} (admin={spec['is_admin']}) id={doc['id']}")

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
