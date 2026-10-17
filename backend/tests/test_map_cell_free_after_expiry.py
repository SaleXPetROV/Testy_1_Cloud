"""UI/API-проверка: после изъятия аренды клетка на карте снова свободна.
Использует реальный публичный эндпоинт карты GET /api/island/cell/{x}/{y}.
Запуск: python tests/test_map_cell_free_after_expiry.py
"""
import asyncio
import os
import sys
import uuid
import httpx
from datetime import datetime, timezone, timedelta

sys.path.insert(0, "/app/backend")
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")
API = None
with open("/app/frontend/.env") as f:
    for line in f:
        if line.startswith("REACT_APP_BACKEND_URL"):
            API = line.strip().split("=", 1)[1]


def _now():
    return datetime.now(timezone.utc)


async def _run():
    db = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
    from zero_lease import process_zero_lease

    user = await db.users.find_one({"email": "testuser@example.com"}, {"_id": 0})
    owner_id = user["id"]

    # Находим свободную клетку на острове (нет владельца, нет pre_business).
    island = await db.islands.find_one({"id": "ton_island"}, {"_id": 0})
    assert island, "остров не сгенерирован"
    plots = {(p["x"], p["y"]) async for p in db.plots.find({"island_id": "ton_island"}, {"_id": 0, "x": 1, "y": 1})}
    free = None
    for c in island["cells"]:
        if (c["x"], c["y"]) in plots:
            continue
        if c.get("pre_business") or c.get("owner"):
            continue
        free = (c["x"], c["y"])
        break
    assert free, "нет свободной клетки для теста"
    x, y = free
    print(f"➡️  Тестовая свободная клетка: ({x},{y})")

    biz_id = str(uuid.uuid4())
    plot_id = str(uuid.uuid4())
    listing_id = str(uuid.uuid4())
    exp = (_now() + timedelta(days=3)).isoformat()

    async def cell_state():
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{API}/api/island/cell/{x}/{y}")
            r.raise_for_status()
            d = r.json()
            return d

    try:
        # 1) Клетка изначально свободна
        d0 = await cell_state()
        assert not d0.get("owner"), f"клетка изначально занята: {d0.get('owner')}"
        assert not d0.get("business"), "на клетке изначально есть бизнес"
        print("✅ До застолбления: клетка свободна (нет владельца/бизнеса)")

        # 2) Застолбить бизнес 0-го уровня (plot + business + авто-листинг)
        await db.businesses.insert_one({
            "id": biz_id, "owner": owner_id, "owner_username": "testuser",
            "business_type": "scrapyard", "level": 0, "is_zero_business": True,
            "durability": 98.0, "is_active": True, "on_sale": False,
            "plot_id": plot_id, "island_id": "ton_island", "x": x, "y": y,
            "zero_map_price": 5.0, "expires_at": exp, "zero_listing_id": listing_id,
            "storage": {"capacity": 320, "items": {}}, "built_at": _now().isoformat(),
        })
        await db.plots.insert_one({
            "id": plot_id, "island_id": "ton_island", "x": x, "y": y,
            "owner": owner_id, "owner_username": "testuser",
            "business_id": biz_id, "on_sale": True, "listing_id": listing_id,
        })
        await db.land_listings.insert_one({
            "id": listing_id, "business_id": biz_id, "plot_id": plot_id,
            "is_zero_business": True, "status": "active", "price": 6.0,
            "x": x, "y": y, "created_at": _now().isoformat(),
        })

        d1 = await cell_state()
        assert d1.get("owner") == owner_id, f"клетка не занята после застолбления: {d1.get('owner')}"
        assert d1.get("business") and d1["business"].get("is_zero_business"), "нет бизнеса 0-го уровня на клетке"
        assert d1["business"].get("zero_listing_id") == listing_id, "листинг не привязан к клетке"
        print(f"✅ После застолбления: клетка занята игроком, бизнес 0-го уровня доступен к выкупу (listing={d1['business'].get('zero_listing_id')})")

        # 3) Истечение аренды → бизнес удаляется отовсюду
        await db.businesses.update_one({"id": biz_id}, {"$set": {"expires_at": (_now() - timedelta(minutes=1)).isoformat()}})
        await process_zero_lease(db)

        # 4) Клетка снова свободна в API карты
        d2 = await cell_state()
        assert not d2.get("owner"), f"❌ клетка всё ещё занята после изъятия: {d2.get('owner')}"
        assert not d2.get("business"), "❌ на клетке остался бизнес после изъятия"
        # и данных в БД не осталось
        assert await db.businesses.find_one({"id": biz_id}) is None, "❌ бизнес не удалён из БД"
        assert await db.plots.find_one({"id": plot_id}) is None, "❌ участок не удалён из БД"
        assert await db.land_listings.find_one({"id": listing_id}) is None, "❌ листинг не удалён из БД"
        print("✅ После изъятия аренды: клетка снова СВОБОДНА в API карты и готова к покупке другим игроком")
        print(f"   (owner={d2.get('owner')}, business={d2.get('business')}, is_available={d2.get('is_available')})")

        print("\n🎉 Проверка карты пройдена: клетка освобождается сразу после изъятия аренды")
    finally:
        await db.businesses.delete_many({"id": biz_id})
        await db.plots.delete_many({"id": plot_id})
        await db.land_listings.delete_many({"id": listing_id})
        await db.notifications.delete_many({"user_id": owner_id, "type": "zero_lease_expired"})


if __name__ == "__main__":
    asyncio.run(_run())
