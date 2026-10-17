"""Server-load guards: cached configs, DB-side sums, indexes.

    cd backend && python -m pytest tests/test_perf_guards.py -q
"""
import asyncio

import pytest

mongomock_motor = pytest.importorskip("mongomock_motor")


def run(c):
    return asyncio.run(c)


def test_league_config_is_cached_and_invalidated_on_save():
    async def go():
        import leagues
        db = mongomock_motor.AsyncMongoMockClient()["perf1"]
        assert (await leagues.get_config(db))["group_size"] == 30
        # a change written straight to the DB is NOT re-read on every event …
        await db.admin_settings.update_one({"type": "leagues"}, {"$set": {"type": "leagues", "group_size": 7}}, upsert=True)
        for _ in range(20):
            assert (await leagues.get_config(db))["group_size"] == 30
        # … but saving through the admin invalidates the cache at once
        await leagues.save_config(db, {"group_size": 25})
        assert (await leagues.get_config(db))["group_size"] == 25
    run(go())


def test_cache_never_mixes_two_databases():
    async def go():
        import city_pass
        a = mongomock_motor.AsyncMongoMockClient()["perf_a"]
        b = mongomock_motor.AsyncMongoMockClient()["perf_b"]
        await city_pass.save_config(a, {"premium_price_ton": 2.0})
        await city_pass.save_config(b, {"premium_price_ton": 5.0})
        assert (await city_pass.get_config(a))["premium_price_ton"] == 2.0
        assert (await city_pass.get_config(b))["premium_price_ton"] == 5.0
    run(go())


def test_reconciliation_sums_by_aggregation(monkeypatch):
    async def go():
        import reconciliation as rc
        db = mongomock_motor.AsyncMongoMockClient()["perf2"]
        await db.users.insert_many([{"id": f"u{i}", "balance_ton": 1.5, "bonus_balance": 0.5} for i in range(100)]
                                   + [{"id": "nobal"}])
        await db.transactions.insert_one({"tx_type": "withdrawal", "status": "pending", "amount_ton": 2.0})

        async def nobal(_):
            return 0.0
        monkeypatch.setattr(rc, "onchain_balance", nobal)
        r = await rc.report(db)
        assert r["liabilities"]["real_balances_ton"] == 150.0 and r["liabilities"]["bonus_balances_ton"] == 50.0
        assert r["liabilities"]["pending_withdrawals_ton"] == 2.0
    run(go())


def test_indexes_created():
    async def go():
        from core.db_indexes import ensure_all
        db = mongomock_motor.AsyncMongoMockClient()["perf3"]
        res = await ensure_all(db)
        assert res["ok"] > 20
        info = await db.market_listings.index_information()
        assert any("status" in str(v["key"]) and "is_bot" in str(v["key"]) for v in info.values())
    run(go())
