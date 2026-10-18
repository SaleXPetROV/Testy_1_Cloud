"""Helper: mint signed initData + pre-create/cleanup linked tg identities (iteration 4 frontend testing)."""
import asyncio
import json
import sys

import requests

from test_tg_miniapp_auth_resilience_iter_current import API, build_init_data, MONGO_URL, DB_NAME


def precreate(tg_id):
    init_data = build_init_data(tg_id, first_name="Iter4", username=f"iter4_{tg_id}")
    r = requests.post(f"{API}/auth/telegram/miniapp/create", json={"init_data": init_data}, timeout=30)
    return init_data, r.status_code, (r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text)


def cleanup(tg_ids):
    from motor.motor_asyncio import AsyncIOMotorClient

    async def _go():
        c = AsyncIOMotorClient(MONGO_URL)
        db = c[DB_NAME]
        out = []
        for t in tg_ids:
            res = await db.users.delete_many({"telegram_id": str(t)})
            res2 = await db.users.delete_many({"telegram_id": int(t)})
            out.append((t, res.deleted_count + res2.deleted_count))
        c.close()
        return out

    return asyncio.run(_go())


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "mint":
        print(build_init_data(int(sys.argv[2]), first_name="Iter4", username=f"iter4_{sys.argv[2]}"))
    elif mode == "precreate":
        print(json.dumps(precreate(int(sys.argv[2]))))
    elif mode == "cleanup":
        print(cleanup([int(x) for x in sys.argv[2:]]))
