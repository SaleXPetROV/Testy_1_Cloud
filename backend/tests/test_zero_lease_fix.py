"""Проверка исправлений аренды бизнеса 0-го уровня:
  1) джоб неактивности НЕ изымает арендованные бизнесы 0-го уровня;
  2) восстановление ошибочно изъятых, но ещё арендованных бизнесов;
  3) уведомления за 24/12/3 ч до конца аренды;
  4) по истечении аренды бизнес удаляется отовсюду (бизнес, участок, листинг).
Запуск: python -m pytest tests/test_zero_lease_fix.py -s
"""
import asyncio
import os
import uuid
from datetime import datetime, timezone, timedelta

from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


def _now():
    return datetime.now(timezone.utc)


async def _mk_zero_biz(db, owner_id, expires_at):
    biz_id = str(uuid.uuid4())
    plot_id = str(uuid.uuid4())
    listing_id = str(uuid.uuid4())
    biz = {
        "id": biz_id, "owner": owner_id, "owner_username": "testuser",
        "business_type": "scrapyard", "level": 0, "is_zero_business": True,
        "durability": 98.0, "is_active": True, "on_sale": False,
        "plot_id": plot_id, "island_id": "ton_island", "x": 5, "y": 5,
        "zero_map_price": 5.0, "expires_at": expires_at,
        "zero_listing_id": listing_id,
        "storage": {"capacity": 320, "items": {}},
        "built_at": _now().isoformat(),
    }
    plot = {"id": plot_id, "island_id": "ton_island", "x": 5, "y": 5,
            "business_id": biz_id, "on_sale": True, "listing_id": listing_id}
    listing = {"id": listing_id, "business_id": biz_id, "plot_id": plot_id,
               "is_zero_business": True, "status": "active", "price": 6.0,
               "created_at": _now().isoformat()}
    await db.businesses.insert_one(biz.copy())
    await db.plots.insert_one(plot.copy())
    await db.land_listings.insert_one(listing.copy())
    return biz_id, plot_id, listing_id


async def _cleanup(db, biz_id, plot_id, listing_id, owner_id):
    await db.businesses.delete_many({"id": biz_id})
    await db.plots.delete_many({"id": plot_id})
    await db.land_listings.delete_many({"id": listing_id})
    await db.notifications.delete_many({"user_id": owner_id})


def test_all():
    asyncio.get_event_loop().run_until_complete(_run())


async def _run():
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    import sys
    sys.path.insert(0, "/app/backend")
    from inactivity import seize_inactive_businesses
    from zero_lease import restore_wrongly_seized_zero_leases, process_zero_lease

    user = await db.users.find_one({"email": "testuser@example.com"}, {"_id": 0})
    assert user, "нет тестового пользователя"
    owner_id = user["id"]
    # у пользователя должен быть язык для локализованных уведомлений
    await db.users.update_one({"id": owner_id}, {"$set": {"language": "ru", "tutorial_active": False}})

    # ── ТЕСТ 1: джоб неактивности НЕ трогает арендованный бизнес 0-го уровня ──
    exp = (_now() + timedelta(days=3)).isoformat()
    biz_id, plot_id, listing_id = await _mk_zero_biz(db, owner_id, exp)
    await seize_inactive_businesses(db)
    b = await db.businesses.find_one({"id": biz_id}, {"_id": 0})
    assert not b.get("is_seized"), "❌ ТЕСТ1: бизнес 0-го уровня ошибочно изъят джобом неактивности"
    assert b.get("is_active") is True, "❌ ТЕСТ1: бизнес остановлен"
    print("✅ ТЕСТ1: джоб неактивности не изъял арендованный бизнес 0-го уровня")

    # ── ТЕСТ 2: восстановление ошибочно изъятого, но ещё арендованного бизнеса ──
    await db.businesses.update_one({"id": biz_id}, {"$set": {
        "is_seized": True, "seizure_reason": "inactivity", "on_sale": True,
        "status": "on_sale", "is_active": False}})
    await db.land_listings.update_one({"id": listing_id}, {"$set": {
        "is_seized": True, "seizure_reason": "inactivity", "former_owner_id": owner_id}})
    restored = await restore_wrongly_seized_zero_leases(db)
    b = await db.businesses.find_one({"id": biz_id}, {"_id": 0})
    lst = await db.land_listings.find_one({"id": listing_id}, {"_id": 0})
    assert restored >= 1, "❌ ТЕСТ2: восстановление не сработало"
    assert not b.get("is_seized"), "❌ ТЕСТ2: флаг is_seized не снят"
    assert b.get("is_active") is True and not b.get("on_sale"), "❌ ТЕСТ2: бизнес не вернулся в работу"
    assert lst and lst.get("status") == "active" and not lst.get("is_seized"), "❌ ТЕСТ2: листинг не очищен"
    print("✅ ТЕСТ2: ошибочно изъятый арендованный бизнес возвращён в работу")

    # ── ТЕСТ 3: уведомление за 3 часа до конца аренды ──
    await db.notifications.delete_many({"user_id": owner_id})
    exp3 = (_now() + timedelta(hours=2, minutes=30)).isoformat()
    await db.businesses.update_one({"id": biz_id}, {"$set": {"expires_at": exp3},
                                                    "$unset": {"zero_lease_warns": "", "zero_lease_warned": ""}})
    await process_zero_lease(db)
    b = await db.businesses.find_one({"id": biz_id}, {"_id": 0})
    assert 3 in (b.get("zero_lease_warns") or []), "❌ ТЕСТ3: порог 3ч не помечен отправленным"
    notif = await db.notifications.find_one({"user_id": owner_id, "type": "zero_lease_expiring"}, {"_id": 0})
    assert notif, "❌ ТЕСТ3: уведомление об окончании аренды не создано"
    assert notif.get("title") and "аренд" in (notif.get("title", "") + notif.get("message", "")).lower(), \
        f"❌ ТЕСТ3: уведомление не на русском: {notif.get('title')}"
    print(f"✅ ТЕСТ3: уведомление за 3ч создано и локализовано: «{notif.get('title')}»")

    # ── ТЕСТ 4: по истечении аренды бизнес удаляется отовсюду ──
    exp_past = (_now() - timedelta(minutes=5)).isoformat()
    await db.businesses.update_one({"id": biz_id}, {"$set": {"expires_at": exp_past}})
    await process_zero_lease(db)
    b = await db.businesses.find_one({"id": biz_id}, {"_id": 0})
    p = await db.plots.find_one({"id": plot_id}, {"_id": 0})
    lst = await db.land_listings.find_one({"id": listing_id}, {"_id": 0})
    assert b is None, "❌ ТЕСТ4: бизнес не удалён после истечения аренды"
    assert p is None, "❌ ТЕСТ4: участок не освобождён"
    assert lst is None, "❌ ТЕСТ4: листинг не убран с маркетплейса"
    print("✅ ТЕСТ4: по истечении аренды бизнес удалён, участок свободен, листинг снят")

    await _cleanup(db, biz_id, plot_id, listing_id, owner_id)
    client.close()
    print("\n🎉 Все тесты аренды/изъятия пройдены")


if __name__ == "__main__":
    asyncio.run(_run())
