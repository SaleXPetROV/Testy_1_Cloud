"""Дополнительная независимая проверка правок зерогёо-аренды (iter2).
Проверяет:
  А) core.seizure.seize_business возвращает None для business с level==0 или is_zero_business=True.
  Б) process_zero_lease: пороги 24ч и 12ч создают zero_lease_expiring, порог фиксируется в zero_lease_warns
     и не дублируется при повторном запуске.
  В) restore_wrongly_seized_zero_leases НЕ трогает бизнесы уровня >0 (не сбрасывает is_seized).
Запуск: python -m pytest tests/test_zero_lease_extra_iter2.py -s -o addopts=''
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, "/app/backend")

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


def _now():
    return datetime.now(timezone.utc)


async def _mk_zero_biz(db, owner_id, expires_at, **overrides):
    biz_id = str(uuid.uuid4())
    plot_id = str(uuid.uuid4())
    listing_id = str(uuid.uuid4())
    biz = {
        "id": biz_id, "owner": owner_id, "owner_username": "testuser",
        "business_type": "scrapyard", "level": 0, "is_zero_business": True,
        "durability": 98.0, "is_active": True, "on_sale": False,
        "plot_id": plot_id, "island_id": "ton_island", "x": 7, "y": 7,
        "zero_map_price": 5.0, "expires_at": expires_at,
        "zero_listing_id": listing_id,
        "storage": {"capacity": 320, "items": {}},
        "built_at": _now().isoformat(),
    }
    biz.update(overrides)
    plot = {"id": plot_id, "island_id": "ton_island", "x": 7, "y": 7,
            "business_id": biz_id, "on_sale": True, "listing_id": listing_id}
    listing = {"id": listing_id, "business_id": biz_id, "plot_id": plot_id,
               "is_zero_business": True, "status": "active", "price": 6.0,
               "created_at": _now().isoformat()}
    await db.businesses.insert_one(biz.copy())
    await db.plots.insert_one(plot.copy())
    await db.land_listings.insert_one(listing.copy())
    return biz_id, plot_id, listing_id


async def _cleanup(db, ids, owner_id):
    for biz_id, plot_id, listing_id in ids:
        await db.businesses.delete_many({"id": biz_id})
        await db.plots.delete_many({"id": plot_id})
        await db.land_listings.delete_many({"id": listing_id})
    await db.notifications.delete_many({"user_id": owner_id, "type": "zero_lease_expiring"})


async def _run():
    from core.seizure import seize_business
    from zero_lease import process_zero_lease, restore_wrongly_seized_zero_leases

    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    user = await db.users.find_one({"email": "testuser@example.com"}, {"_id": 0})
    assert user, "no test user"
    owner_id = user["id"]
    await db.users.update_one({"id": owner_id}, {"$set": {"language": "ru"}})

    created = []
    try:
        # === A) seize_business early return для 0-го уровня ===
        exp = (_now() + timedelta(days=2)).isoformat()
        biz_id_a, plot_a, list_a = await _mk_zero_biz(db, owner_id, exp)
        created.append((biz_id_a, plot_a, list_a))
        biz = await db.businesses.find_one({"id": biz_id_a}, {"_id": 0})
        res = await seize_business(db, biz, reason="test")
        assert res is None, f"❌ A: seize_business должен вернуть None для level=0, вернул {res}"
        biz_after = await db.businesses.find_one({"id": biz_id_a}, {"_id": 0})
        assert not biz_after.get("is_seized") and biz_after.get("is_active") is True
        print("✅ A: seize_business возвращает None и не трогает бизнес 0-го уровня")

        # Второй кейс — level==0, is_zero_business=False (fallback ветка)
        biz_id_a2, plot_a2, list_a2 = await _mk_zero_biz(
            db, owner_id, exp, is_zero_business=False
        )
        created.append((biz_id_a2, plot_a2, list_a2))
        biz2 = await db.businesses.find_one({"id": biz_id_a2}, {"_id": 0})
        res2 = await seize_business(db, biz2, reason="test")
        assert res2 is None, "❌ A2: seize_business должен вернуть None и для level==0 без флага is_zero_business"
        print("✅ A2: seize_business возвращает None по чистому level==0 (без is_zero_business)")

        # === Б) пороги 24ч и 12ч + идемпотентность ===
        # 24ч порог
        exp24 = (_now() + timedelta(hours=23, minutes=30)).isoformat()
        biz_id_b, plot_b, list_b = await _mk_zero_biz(db, owner_id, exp24)
        created.append((biz_id_b, plot_b, list_b))
        await db.notifications.delete_many({"user_id": owner_id, "type": "zero_lease_expiring"})
        await process_zero_lease(db)
        biz_b = await db.businesses.find_one({"id": biz_id_b}, {"_id": 0})
        assert 24 in (biz_b.get("zero_lease_warns") or []), (
            f"❌ Б: порог 24ч не помечен: {biz_b.get('zero_lease_warns')}")
        n24 = await db.notifications.count_documents(
            {"user_id": owner_id, "type": "zero_lease_expiring"})
        assert n24 >= 1, "❌ Б: уведомление 24ч не создано"
        print(f"✅ Б: 24ч порог — помечен и создано {n24} уведомление(й)")

        # Идемпотентность: повторный запуск не создаёт дубликат для того же порога
        await process_zero_lease(db)
        n24_after = await db.notifications.count_documents(
            {"user_id": owner_id, "type": "zero_lease_expiring"})
        assert n24_after == n24, f"❌ Б: 24ч порог продублирован: было {n24}, стало {n24_after}"
        print("✅ Б: 24ч порог идемпотентен (без дублей)")

        # 12ч порог: тот же бизнес → сдвигаем expires_at
        exp12 = (_now() + timedelta(hours=11, minutes=45)).isoformat()
        await db.businesses.update_one({"id": biz_id_b}, {"$set": {"expires_at": exp12}})
        await process_zero_lease(db)
        biz_b = await db.businesses.find_one({"id": biz_id_b}, {"_id": 0})
        assert 12 in (biz_b.get("zero_lease_warns") or []), (
            f"❌ Б: порог 12ч не помечен: {biz_b.get('zero_lease_warns')}")
        n12 = await db.notifications.count_documents(
            {"user_id": owner_id, "type": "zero_lease_expiring"})
        assert n12 > n24, "❌ Б: уведомление для 12ч не добавилось"
        # Проверим локализацию — русский
        last = await db.notifications.find_one(
            {"user_id": owner_id, "type": "zero_lease_expiring"},
            sort=[("_id", -1)])
        combined = ((last.get("title") or "") + " " + (last.get("message") or "")).lower()
        assert "аренд" in combined, f"❌ Б: уведомление не на русском: {last}"
        print(f"✅ Б: 12ч порог помечен, уведомление RU: «{last.get('title')}»")

        # === В) restore не трогает бизнесы уровня >0 ===
        biz_id_c = str(uuid.uuid4())
        plot_c = str(uuid.uuid4())
        list_c = str(uuid.uuid4())
        biz_lvl1 = {
            "id": biz_id_c, "owner": owner_id, "owner_username": "testuser",
            "business_type": "scrapyard", "level": 1, "is_zero_business": False,
            "is_seized": True, "seizure_reason": "inactivity",
            "is_active": False, "on_sale": True, "status": "on_sale",
            "plot_id": plot_c, "island_id": "ton_island", "x": 8, "y": 8,
            "expires_at": (_now() + timedelta(days=1)).isoformat(),  # даже если есть, не должно возвращаться
            "storage": {"capacity": 320, "items": {}},
        }
        await db.businesses.insert_one(biz_lvl1)
        await db.plots.insert_one({"id": plot_c, "island_id": "ton_island", "x": 8, "y": 8,
                                    "business_id": biz_id_c, "on_sale": True, "listing_id": list_c})
        await db.land_listings.insert_one({"id": list_c, "business_id": biz_id_c, "plot_id": plot_c,
                                            "is_zero_business": False, "is_seized": True,
                                            "status": "seized_listing", "price": 6.0})
        created.append((biz_id_c, plot_c, list_c))
        await restore_wrongly_seized_zero_leases(db)
        biz_c_after = await db.businesses.find_one({"id": biz_id_c}, {"_id": 0})
        assert biz_c_after.get("is_seized") is True, (
            "❌ В: restore_wrongly_seized_zero_leases ошибочно снял is_seized c бизнеса уровня 1")
        print("✅ В: restore не трогает бизнесы уровня >0")

        print("\n🎉 Дополнительные проверки пройдены")
    finally:
        await _cleanup(db, created, owner_id)
        client.close()


def test_all():
    asyncio.get_event_loop().run_until_complete(_run())


if __name__ == "__main__":
    asyncio.run(_run())
