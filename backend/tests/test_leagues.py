"""Weekly leagues (backend/leagues.py).

    cd backend && python -m pytest tests/test_leagues.py -q
"""
import asyncio

import pytest

mongomock_motor = pytest.importorskip("mongomock_motor")
import leagues as lg  # noqa: E402


def run(c):
    return asyncio.run(c)


async def _db(n=3, cfg=None):
    db = mongomock_motor.AsyncMongoMockClient()["lg"]
    lg.init(db)
    lg._indexes_ready = False
    for i in range(n):
        await db.users.insert_one({"id": f"u{i}", "username": f"p{i}", "bonus_balance": 0.0})
    if cfg:
        await lg.save_config(db, cfg)
    return db


def test_activity_points_respect_per_action_and_daily_caps():
    async def go():
        db = await _db(1, {"caps": {"shift_start": 3}, "daily_points_cap": 20})
        for _ in range(5):
            await lg.add_activity(db, "u0", "shift_start")          # 2 pts each, 3 counted -> 6
        await lg.add_activity(db, "u0", "daily_goal")               # +10 -> 16
        await lg.add_activity(db, "u0", "daily_goal")               # +10 but day cap 20 -> +4
        m = await db.league_members.find_one({"user_id": "u0"})
        assert m["points"] == 20
    run(go())


def test_sales_fill_units_and_ton_boards_and_capped_points():
    async def go():
        db = await _db(1, {"caps": {"sale": 5}})
        await lg.add_sale(db, "u0", 40, 0.12)                      # 12 raw pts -> capped 5
        await lg.add_sale(db, "u0", 10, 0.05)                      # sale points cap reached
        m = await db.league_members.find_one({"user_id": "u0"})
        assert m["units_sold"] == 50 and abs(m["ton_sold"] - 0.17) < 1e-9 and m["points"] == 5
    run(go())


def test_city_market_and_linked_sales_do_not_count():
    async def go():
        import quests
        db = await _db(2)
        quests.init(db)
        await db.fingerprints.insert_many([{"user_id": "u0", "visitor_id": "d"}, {"user_id": "u1", "visitor_id": "d"}])
        await quests.sale_event("u0", None, 10)                    # City Market: no ton
        await quests.sale_event("u0", "u1", 10, ton=0.05)           # linked buyer
        await asyncio.sleep(0.05)
        assert await db.league_members.count_documents({"user_id": "u0", "units_sold": {"$gt": 0}}) == 0
    run(go())


def test_groups_split_linked_accounts_and_respect_size():
    async def go():
        db = await _db(5, {"group_size": 2, "promote_count": 1, "relegate_count": 1})
        await db.fingerprints.insert_many([{"user_id": "u0", "visitor_id": "d"}, {"user_id": "u1", "visitor_id": "d"}])
        for i in range(5):
            await lg.ensure_member(db, f"u{i}")
        g0 = (await db.league_members.find_one({"user_id": "u0"}))["group_id"]
        g1 = (await db.league_members.find_one({"user_id": "u1"}))["group_id"]
        assert g0 != g1                                           # same device -> different groups
        async for g in db.league_groups.find({}):
            assert g["size"] <= 2
    run(go())


def test_finalize_pays_rewards_promotes_and_relegates():
    async def go():
        db = await _db(4, {"group_size": 4, "promote_count": 1, "relegate_count": 1,
                           "boards": {"points": {"enabled": True, "rewards_city": [300, 100]},
                                      "units_sold": {"enabled": True, "rewards_city": [50]},
                                      "ton_sold": {"enabled": False, "rewards_city": []}},
                           "shield_top_n": 1})
        for i, pts in enumerate([40, 30, 20, 0]):
            await lg.ensure_member(db, f"u{i}")
            await db.league_members.update_one({"user_id": f"u{i}"}, {"$set": {"points": pts}})
        await db.league_members.update_one({"user_id": "u2"}, {"$set": {"units_sold": 99}})
        await db.users.update_one({"id": "u3"}, {"$set": {"league_division": 1}})
        await db.league_members.update_one({"user_id": "u3"}, {"$set": {"division": 1}})
        wk = lg.week_key()
        st = await lg.finalize_week(db, wk)
        assert st["groups"] == 1 and st["promoted"] == 1 and st["relegated"] == 1
        u = {x["id"]: x async for x in db.users.find({})}
        assert u["u0"]["league_division"] == 1                       # promoted
        assert u["u3"]["league_division"] == 0                       # relegated
        assert abs(u["u0"]["bonus_balance"] - 0.300) < 1e-9          # 1st on points
        assert abs(u["u1"]["bonus_balance"] - 0.100) < 1e-9
        assert abs(u["u2"]["bonus_balance"] - 0.050) < 1e-9          # 1st on units sold
        assert u["u0"].get("streak_shields") == 1
        # never paid twice
        st2 = await lg.finalize_week(db, wk)
        assert st2["groups"] == 0
    run(go())


def test_view_has_three_ratings_and_my_ranks():
    async def go():
        db = await _db(2)
        await lg.add_activity(db, "u0", "daily_goal")
        await lg.add_sale(db, "u1", 5, 0.02)
        v = await lg.group_view(db, "u0")
        assert set(v["standings"]) == {"points", "units_sold", "ton_sold"}
        assert v["me"]["ranks"]["points"] == 1
    run(go())


def test_admin_can_disable_a_rating_and_config_is_validated():
    async def go():
        db = await _db(1)
        cfg = await lg.save_config(db, {"boards": {"ton_sold": {"enabled": False}}})
        assert cfg["boards"]["ton_sold"]["enabled"] is False
        v = await lg.group_view(db, "u0")
        assert "ton_sold" not in v["boards"]
        for bad in ({"group_size": 1}, {"promote_count": 20, "relegate_count": 20}, {"promotion_board": "x"},
                    {"points": {"unknown": 1}}, {"promotion_board": "ton_sold"}):
            with pytest.raises(Exception):
                await lg.save_config(db, bad)
    run(go())


def test_rewards_list_accepts_comma_text():
    async def go():
        db = await _db(1)
        cfg = await lg.save_config(db, {"boards": {"points": {"rewards_city": "500, 250,100"}}})
        assert cfg["boards"]["points"]["rewards_city"] == [500, 250, 100]
    run(go())
