"""Интеграционная проверка iTerra: baseline-учёт и прогресс порогового квеста.
Поднимает локальный мок-сервер партнёра и гоняет реальные API проекта.
Запуск: python tests/test_iterra_baseline.py
"""
import asyncio
import os
import json
import httpx
from aiohttp import web

API = None
with open("/app/frontend/.env") as f:
    for line in f:
        if line.startswith("REACT_APP_BACKEND_URL"):
            API = line.strip().split("=", 1)[1]

ADMIN = {"email": "sanyanazarov212@gmail.com", "password": os.environ.get("TEST_ADMIN_PASSWORD", "")}
USER = {"email": "testuser@example.com", "password": "Test1234!"}

MOCK_PORT = 9977
_state = {"value": 3}  # текущее значение метрики партнёра (tradeVolume)


async def _mock_handler(request):
    # Всегда HTTP 200 + текущее значение метрики.
    return web.json_response({"ok": True, "data": {"tradeVolume": _state["value"]}})


async def _login(client, creds):
    r = await client.post(f"{API}/api/auth/login", json=creds)
    r.raise_for_status()
    return r.json()["token"]


async def _run():
    assert API, "нет REACT_APP_BACKEND_URL"
    # запускаем мок-сервер партнёра
    app = web.Application()
    app.router.add_route("*", "/check", _mock_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", MOCK_PORT)
    await site.start()

    task_id = None
    try:
        # ВАЖНО: отдельные клиенты для админа и юзера — иначе auth-cookie одного
        # перекрывает Bearer-токен другого (httpx хранит cookie между запросами).
        async with httpx.AsyncClient(timeout=40, cookies=None) as ca, \
                   httpx.AsyncClient(timeout=40, cookies=None) as cu:
            admin_t = await _login(ca, ADMIN)
            user_t = await _login(cu, USER)
            ah = {"Authorization": f"Bearer {admin_t}"}
            uh = {"Authorization": f"Bearer {user_t}"}
            # используем ca для админских вызовов, cu — для пользовательских
            c = cu  # пользовательские вызовы по умолчанию

            # 1) создаём партнёрский пороговый квест iTerra (tradeVolume >= 5)
            payload = {
                "title": "iTerra tradeVolume test",
                "reward_city": 100,
                "action_type": "partner_quest",
                "quest_kind": "partner",
                "partner_url": f"http://127.0.0.1:{MOCK_PORT}/check",
                "partner_method": "GET",
                "partner_check_field": "data.tradeVolume",
                "partner_check_min": 5,
            }
            r = await ca.post(f"{API}/api/admin/tasks", headers=ah, json=payload)
            assert r.status_code == 200, f"создание задачи: {r.status_code} {r.text}"
            task_id = r.json()["task"]["id"]
            print(f"✅ Создан партнёрский квест iTerra: {task_id}")

            # 2) baseline фиксируется при первом просмотре: value=3 → have=0 (старые сделки не в счёт)
            _state["value"] = 3
            r = await cu.get(f"{API}/api/tasks", headers=uh)
            t = next((x for x in r.json()["tasks"] if x["id"] == task_id), None)
            assert t, "квест не виден пользователю"
            assert t.get("partner_need") == "5", f"need={t.get('partner_need')}"
            assert t.get("partner_metric") == "tradeVolume", f"metric={t.get('partner_metric')}"
            assert t.get("partner_have") == "0", f"❌ baseline не учтён: have={t.get('partner_have')} (ожидалось 0)"
            print(f"✅ Baseline зафиксирован: показывает {t.get('partner_metric')} {t.get('partner_have')} из {t.get('partner_need')} (старые сделки не засчитаны)")

            # 3) verify при value=3 → прирост 0 < 5 → не выполнено
            r = await cu.post(f"{API}/api/tasks/{task_id}/verify", headers=uh)
            assert r.status_code == 400, f"❌ квест не должен завершаться при приросте 0: {r.status_code} {r.text}"
            print(f"✅ Проверка при приросте 0 отклонена: {r.json().get('detail')}")

            # 4) value=9 → прирост 9-3=6 >= 5 → выполнено
            _state["value"] = 9
            r = await cu.post(f"{API}/api/tasks/{task_id}/verify", headers=uh)
            assert r.status_code == 200, f"❌ квест должен завершиться при приросте 6: {r.status_code} {r.text}"
            print("✅ Проверка при приросте 6 (>=5) успешна — квест выполнен")

            # 5) сброс baseline при обновлении задания админом
            r = await ca.put(f"{API}/api/admin/tasks/{task_id}/update", headers=ah, json=payload)
            assert r.status_code == 200, f"обновление: {r.status_code} {r.text}"
            # baseline удалён → при новом просмотре value=9 станет новым baseline → have=0
            # (задача уже completed для пользователя, поэтому проверим коллекцию напрямую)
            from motor.motor_asyncio import AsyncIOMotorClient
            db = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))[os.environ.get("DB_NAME", "test_database")]
            cnt = await db.task_partner_baselines.count_documents({"task_id": task_id})
            assert cnt == 0, f"❌ baseline не сброшен при обновлении задания (осталось {cnt})"
            print("✅ Baseline сброшен при выдаче обновлённого задания")

        print("\n🎉 Все проверки iTerra (baseline + прогресс) пройдены")
    finally:
        # уборка
        try:
            from motor.motor_asyncio import AsyncIOMotorClient
            db = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))[os.environ.get("DB_NAME", "test_database")]
            if task_id:
                await db.tasks.delete_many({"id": task_id})
                await db.task_completions.delete_many({"task_id": task_id})
                await db.task_partner_baselines.delete_many({"task_id": task_id})
        except Exception as e:
            print("cleanup warn:", e)
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(_run())
