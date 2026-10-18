"""Seed a few demo tasks (incl. partner quests) so the Tasks page and the
auto-translation / partner-quest button flow can be exercised.

Text is authored in Russian; the backend auto-translates it to the player's
language at read time (same LibreTranslate engine as the chat).

Usage: python seed_tasks.py
"""
import asyncio
import os
import uuid
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

NOW = datetime.now(timezone.utc).isoformat()


def _base(**over):
    doc = {
        "id": str(uuid.uuid4()),
        "title": "",
        "title_i18n": None,
        "reward_city": None,
        "action_type": "visit_link",
        "require_telegram": False,
        "photo": None,
        "icon": None,
        "icon_url": None,
        "channel_url": None,
        "channel_id": None,
        "target_url": None,
        "required_referrals": None,
        "views_rate": None,
        "action_data": None,
        "quest_kind": None,
        "partner_url": None,
        "partner_ref_id": None,
        "partner_method": None,
        "partner_api_key": None,
        "partner_user_param": None,
        "partner_check_field": None,
        "partner_check_min": None,
        "partner_completed_field": None,
        "instructions": None,
        "instructions_i18n": None,
        "reward_description": None,
        "reward_description_i18n": None,
        "reward_resources": None,
        "reward_skins": None,
        "reward_funds_amount": None,
        "reward_funds_target": None,
        "show_to_referrals": True,
        "active": True,
        "order": 0,
        "created_at": NOW,
    }
    doc.update(over)
    return doc


TASKS = [
    # 1) Simple trust task (visit link) — quick to complete.
    _base(
        title="Посетите наш сайт",
        action_type="visit_link",
        target_url="https://ton.org",
        reward_city=100,
        instructions="Откройте официальный сайт TON и ознакомьтесь с экосистемой.",
        order=1,
    ),
    # 2) Partner quest — LOCAL kind (trust-based). "Проверить" succeeds → done.
    _base(
        title="Задание от партнёра: подпишитесь на канал",
        action_type="partner_quest",
        quest_kind="local",
        target_url="https://t.me/toncoin",
        reward_city=500,
        instructions="Перейдите по ссылке партнёра, подпишитесь на канал, затем нажмите «Проверить», чтобы получить награду.",
        reward_description="Награда за выполнение партнёрского задания.",
        order=2,
    ),
    # 3) Partner quest — PARTNER kind with a threshold metric.
    #    Uses a public echo endpoint that returns {"tradeVolume": 3} so progress
    #    (3 из 5) is shown; "Проверить" will report "not enough" until the value
    #    reaches the threshold. Demonstrates real progress display.
    _base(
        title="Партнёрское задание: наторгуйте объём",
        action_type="partner_quest",
        quest_kind="partner",
        target_url="https://iterra.example/trade",
        partner_url="https://httpbin.org/anything?tradeVolume=3",
        partner_method="GET",
        partner_check_field="args.tradeVolume",
        partner_check_min=5,
        reward_city=1000,
        instructions="Совершите сделки на партнёрской платформе на нужный объём, затем нажмите «Проверить».",
        reward_description="1000 $CITY за достижение торгового объёма.",
        order=3,
    ),
]


async def main():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    for t in TASKS:
        existing = await db.tasks.find_one({"title": t["title"]})
        if existing:
            await db.tasks.update_one({"_id": existing["_id"]}, {"$set": {k: v for k, v in t.items() if k != "id"}})
            print(f"UPDATED  {t['action_type']:14} | {t['title']}")
        else:
            await db.tasks.insert_one(t)
            print(f"INSERTED {t['action_type']:14} | {t['title']}")
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
