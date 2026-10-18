"""Seed demo global chat messages to visualize day separators, grouping and translate button."""
import asyncio, os, uuid
from datetime import datetime, timezone, timedelta
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv()

async def main():
    client = AsyncIOMotorClient(os.environ['MONGO_URL'])
    db = client[os.environ['DB_NAME']]
    admin = await db.users.find_one({"email": "sanyanazarov212@gmail.com"})
    user = await db.users.find_one({"email": "testuser@example.com"})
    await db.chat_messages.delete_many({"chat_type": "global"})
    now = datetime.now(timezone.utc)
    yesterday = now - timedelta(days=1)

    def mk(sender, content, when, lang="ru"):
        return {
            "id": str(uuid.uuid4()), "content": content, "chat_type": "global",
            "city_id": None, "sender_id": sender["id"],
            "sender_username": sender.get("username"), "sender_avatar": sender.get("avatar"),
            "recipient_id": None, "created_at": when.isoformat(), "is_read": True,
            "lang": lang, "translations": {},
        }

    msgs = [
        # Yesterday: user sends 3 in a row (grouped), then admin, then user again
        mk(user, "Привет всем!", yesterday.replace(hour=10, minute=0)),
        mk(user, "Как дела в городе?", yesterday.replace(hour=10, minute=1)),
        mk(user, "Кто-нибудь онлайн?", yesterday.replace(hour=10, minute=2)),
        mk(admin, "Hi there, welcome to GRAM CITY!", yesterday.replace(hour=10, minute=5), lang="en"),
        mk(user, "О, привет админ!", yesterday.replace(hour=10, minute=6)),
        # Today: admin sends 2 grouped, then user
        mk(admin, "Сегодня обновление экономики.", now.replace(hour=9, minute=0)),
        mk(admin, "Проверьте свои бизнесы.", now.replace(hour=9, minute=1)),
        mk(user, "Отлично, спасибо!", now.replace(hour=9, minute=30)),
    ]
    await db.chat_messages.insert_many(msgs)
    print(f"Inserted {len(msgs)} messages. admin={admin['id']} user={user['id']}")
    client.close()

asyncio.run(main())
