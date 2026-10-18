"""One-off script: create two test users directly in MongoDB.

Usage: python create_test_users.py
"""
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from passlib.context import CryptContext
from pymongo import MongoClient

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _initials_avatar(name: str) -> dict:
    initials = "".join([w[0].upper() for w in (name or "U").split()[:2]]) or "U"
    palette = ["#6366f1", "#8b5cf6", "#ec4899", "#f43f5e", "#f59e0b", "#10b981", "#14b8a6", "#3b82f6"]
    color = palette[sum(ord(c) for c in name) % len(palette)]
    return {"type": "initials", "initials": initials, "color": color}


def make_user(email: str, username: str, password: str, is_admin: bool = False) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "username": username,
        "display_name": username,
        "email": email,
        "hashed_password": pwd_context.hash(password),
        "wallet_address": None,
        "raw_address": None,
        "avatar": _initials_avatar(username),
        "balance_ton": 100.0 if is_admin else 10.0,
        "language": "ru",
        "level": "novice",
        "xp": 0,
        "total_turnover": 0,
        "total_income": 0,
        "resources": {},
        "plots_owned": [],
        "businesses_owned": [],
        "is_admin": is_admin,
        "roles": ["superadmin"] if is_admin else [],
        "email_verified": True,
        "agreement_accepted": True,
        "created_at": datetime.now(timezone.utc),
        "last_login": datetime.now(timezone.utc),
    }


def main():
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    client = MongoClient(mongo_url)
    db = client[db_name]

    # Passwords come from the environment so they are not committed to the repo.
    # SEED_ADMIN_PASSWORD / SEED_USER_PASSWORD must be set; refuse otherwise.
    admin_pw = os.environ.get("SEED_ADMIN_PASSWORD")
    user_pw = os.environ.get("SEED_USER_PASSWORD")
    if not admin_pw or not user_pw:
        raise SystemExit(
            "Set SEED_ADMIN_PASSWORD and SEED_USER_PASSWORD before seeding test users, e.g.:\n"
            "  SEED_ADMIN_PASSWORD=... SEED_USER_PASSWORD=... python create_test_users.py"
        )
    seeds = [
        {"email": os.environ.get("SEED_ADMIN_EMAIL", "sanyanazarov212@gmail.com"), "username": "admin", "password": admin_pw, "is_admin": True},
        {"email": os.environ.get("SEED_USER_EMAIL", "testuser@example.com"), "username": "testuser", "password": user_pw, "is_admin": False},
    ]

    for s in seeds:
        existing = db.users.find_one({"email": s["email"]})
        if existing:
            # Ensure password / admin flag are correct and normalise
            update = {
                "hashed_password": pwd_context.hash(s["password"]),
                "is_admin": s["is_admin"],
                "email_verified": True,
                "agreement_accepted": True,
                "roles": ["superadmin"] if s["is_admin"] else existing.get("roles") or [],
            }
            db.users.update_one({"_id": existing["_id"]}, {"$set": update})
            print(f"UPDATED  {s['email']} (id={existing.get('id')}) admin={s['is_admin']}")
        else:
            doc = make_user(s["email"], s["username"], s["password"], s["is_admin"])
            db.users.insert_one(doc)
            print(f"INSERTED {s['email']} (id={doc['id']}) admin={s['is_admin']}")

    client.close()


if __name__ == "__main__":
    main()
