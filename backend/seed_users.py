"""
Seed Users Script for GRAM City
Creates 2 test users: 1 admin (sanyanazarov212@gmail.com) and 1 regular user
"""
import asyncio
import uuid
import hashlib
import os
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient
from passlib.context import CryptContext
from dotenv import load_dotenv

load_dotenv()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Test user data per user request
TEST_USERS = [
    {
        "username": "SanyaNazarov",
        "email": "sanyanazarov212@gmail.com",
        "password": os.environ.get("SEED_ADMIN_PASSWORD", ""),
        "is_admin": True,
        "roles": ["superadmin"],
        "balance_ton": 1230.0,
        "level": 10,
        "display_name": "Sanya Admin",
        "available_skins": ["crazy_bio_farm"],
        # Required for support-agent /sys-ops routes (claim chat etc.)
        "telegram_chat_id": "100000001"
    },
    {
        "username": "testuser",
        "email": "testuser@example.com",
        "password": os.environ.get("SEED_USER_PASSWORD", ""),
        "is_admin": False,
        "roles": [],
        "balance_ton": 100.0,
        "level": 1,
        "display_name": "Test User"
    },
    {
        "username": "testuser2",
        "email": "testuser2@example.com",
        "password": os.environ.get("SEED_USER2_PASSWORD", ""),
        "is_admin": False,
        "roles": [],
        "balance_ton": 100.0,
        "level": 1,
        "display_name": "Test User 2"
    }
]


def generate_avatar(username: str) -> str:
    """Generate simple SVG avatar from initials"""
    initials = username[:2].upper()
    
    # Generate color based on username hash
    hash_val = int(hashlib.md5(username.encode()).hexdigest()[:6], 16)
    hue = hash_val % 360
    
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
        <defs>
            <linearGradient id="grad" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" style="stop-color:hsl({hue},70%,50%);stop-opacity:1" />
                <stop offset="100%" style="stop-color:hsl({(hue + 30) % 360},70%,40%);stop-opacity:1" />
            </linearGradient>
        </defs>
        <rect width="100" height="100" fill="url(#grad)"/>
        <text x="50" y="55" font-family="Arial, sans-serif" font-size="32" font-weight="bold" 
              fill="white" text-anchor="middle" dominant-baseline="middle">{initials}</text>
    </svg>'''
    
    import base64
    svg_bytes = svg.encode('utf-8')
    b64 = base64.b64encode(svg_bytes).decode('utf-8')
    return f"data:image/svg+xml;base64,{b64}"


async def create_users():
    """Create test users in MongoDB"""
    mongo_url = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
    db_name = os.environ.get('DB_NAME', 'test_database')
    
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    
    created_users = []
    
    for user_data in TEST_USERS:
        # Check if user already exists
        existing = await db.users.find_one({
            "$or": [
                {"username": user_data["username"]},
                {"email": user_data["email"]}
            ]
        })
        
        if existing:
            print(f"User {user_data['username']} already exists, updating...")
            # Update existing user
            await db.users.update_one(
                {"_id": existing["_id"]},
                {
                    "$set": {
                        "hashed_password": pwd_context.hash(user_data["password"]),
                        "is_admin": user_data["is_admin"],
                        "roles": user_data.get("roles", []),
                        "balance_ton": user_data["balance_ton"],
                        "level": user_data["level"],
                        "display_name": user_data["display_name"],
                        "tutorial_active": False,
                        "tutorial_completed": True,
                        **({"available_skins": user_data["available_skins"]} if user_data.get("available_skins") else {}),
                        # Required for support-agent /sys-ops routes
                        **({"telegram_chat_id": user_data["telegram_chat_id"]} if user_data.get("telegram_chat_id") else {}),
                    },
                    "$unset": {
                        "tutorial_current_step": "",
                        "tutorial_snapshot": "",
                        "tutorial_state": "",
                        "tutorial_started_at": "",
                        "tutorial_completed_at": "",
                        # Reset the one-shot T3 tutorial reward so these TEST
                        # accounts can replay the tutorial and be offered the
                        # T3 resource picker again. (Production users keep the
                        # one-shot behaviour — this only runs for seeded test
                        # accounts.)
                        "tutorial_t3_reward_granted": "",
                        "tutorial_t3_reward_choice": "",
                        "tutorial_t3_reward_granted_at": "",
                        "tutorial_pending_t3_auto_activate": "",
                    },
                },
            )
            created_users.append({
                "id": existing.get("id"),
                "username": user_data["username"],
                "email": user_data["email"],
                "password": user_data["password"],
                "is_admin": user_data["is_admin"]
            })
            continue
        
        # Create new user
        user_doc = {
            "id": str(uuid.uuid4()),
            "username": user_data["username"],
            "email": user_data["email"],
            "hashed_password": pwd_context.hash(user_data["password"]),
            "display_name": user_data["display_name"],
            "avatar": generate_avatar(user_data["username"]),
            "is_admin": user_data["is_admin"],
            "roles": user_data.get("roles", []),
            "balance_ton": user_data["balance_ton"],
            "level": user_data["level"],
            "xp": 0,
            "total_turnover": 0,
            "total_income": 0.0,
            "language": "ru",
            "registration_method": "email",
            "is_2fa_enabled": False,
            "two_factor_secret": None,
            "backup_codes": [],
            "withdraw_lock_until": None,
            "plots_owned": [],
            "businesses_owned": [],
            "tutorial_active": False,
            "tutorial_completed": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_login": datetime.now(timezone.utc).isoformat()
        }
        if user_data.get("available_skins"):
            user_doc["available_skins"] = user_data["available_skins"]
        if user_data.get("telegram_chat_id"):
            user_doc["telegram_chat_id"] = user_data["telegram_chat_id"]
        
        await db.users.insert_one(user_doc)
        
        created_users.append({
            "id": user_doc["id"],
            "username": user_data["username"],
            "email": user_data["email"],
            "password": user_data["password"],
            "is_admin": user_data["is_admin"]
        })
        
        print(f"Created user: {user_data['username']} ({user_data['email']})")
    
    client.close()
    
    return created_users


async def main():
    print("\n" + "="*60)
    print("Seeding users for GRAM-City")
    print("="*60 + "\n")
    
    users = await create_users()
    
    print("\n" + "="*60)
    print("USER CREDENTIALS")
    print("="*60)
    
    for user in users:
        admin_badge = " [ADMIN]" if user["is_admin"] else ""
        print(f"\n{user['username']}{admin_badge}")
        print(f"  Email: {user['email']}")
        print("  Password: (from SEED_*_PASSWORD env)")
    
    print("\n" + "="*60)
    print("Users seeded successfully!")
    print("="*60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
