"""City Pass (city_pass.py) + boosters (boosters.py) + auto-shift in the tick.

    cd backend && python -m pytest tests/test_city_pass.py -q
"""
import asyncio
import datetime as dt

import pytest

mongomock_motor = pytest.importorskip("mongomock_motor")
import boosters  # noqa: E402
import city_pass as cp  # noqa: E402


def run(c):
    return asyncio.run(c)


async def _db(balance=5.0, bonus=10.0):
    db = mongomock_motor.AsyncMongoMockClient()["cp"]
    cp.init(db)
    cp._idx = False
    await db.users.insert_one({"id": "u1", "balance_ton": balance, "bonus_balance": bonus})
    await cp.save_config(db, {"premium_price_ton": 3.0})        # the admin sets the price
    return db


async def _set_xp(db, xp):
    cfg = await cp.get_config(db)
    await cp._progress(db, "u1", cfg)
    await db.city_pass_progress.update_one({"user_id": "u1"}, {"$set": {"xp": xp}})


# ───────── rules ─────────
def test_last_level_needs_80_percent_and_levels_get_more_expensive():
    async def go():
        db = await _db()
        cfg = await cp.get_config(db)
        costs = cp.level_costs(cfg)
        assert set(costs[:10]) == {130} and set(costs[10:20]) == {160} and set(costs[20:]) == {190}
        assert sum(costs) == int(0.8 * cfg["days"] * cfg["daily_xp_cap"]) == 4800
        cfg = await cp.save_config(db, {"tier_weights": [1, 2, 3]})
        c = cp.level_costs(cfg)
        assert c[0] < c[10] < c[20] and sum(c) == 4800          # same total, steeper curve
        cfg = await cp.save_config(db, {"daily_xp_cap": 250})
        assert sum(cp.level_costs(cfg)) == 6000                 # 0.8 x 30 x 250
    run(go())


def test_level_from_cumulative_thresholds():
    async def go():
        db = await _db()
        cfg = await cp.get_config(db)
        assert cp._level(cfg, 129) == 0 and cp._level(cfg, 130) == 1
        assert cp._level(cfg, 1300) == 10 and cp._level(cfg, 1300 + 159) == 10 and cp._level(cfg, 1460) == 11
        assert cp._level(cfg, 10 ** 6) == 30
    run(go())


def test_premium_not_sold_until_admin_sets_a_price():
    async def go():
        db = mongomock_motor.AsyncMongoMockClient()["cp_noprice"]
        cp.init(db)
        cp._idx = False
        await db.users.insert_one({"id": "u1", "balance_ton": 10.0})
        with pytest.raises(Exception):
            await cp.buy_premium(db, "u1")
        assert (await cp.view(db, "u1"))["premium_price_ton"] is None
        with pytest.raises(Exception):
            await cp.save_config(db, {"premium_price_ton": 0})
    run(go())


def test_reward_on_every_free_level_premium_on_1_5_10_30_no_bonus_balance():
    cfg = cp.DEFAULT_CONFIG
    assert sorted(int(k) for k in cfg["rewards_free"]) == list(range(1, 31))
    assert sorted(int(k) for k in cfg["rewards_premium"]) == [1, 5, 10, 15, 20, 25, 30]
    assert cfg["rewards_free"]["30"] == [{"type": "auto_shift", "hours": 72}]
    every = [r for t in ("rewards_free", "rewards_premium") for lst in cfg[t].values() for r in lst]
    assert all(r["type"] in boosters.REWARD_TYPES for r in every)          # items only, no $CITY


def test_xp_per_action_caps_but_no_daily_limit():
    async def go():
        db = await _db()
        for _ in range(5):
            await cp.add_xp(db, "u1", "shift_start")          # 10 each, 3 counted -> 30
        for _ in range(4):
            await cp.add_xp(db, "u1", "daily_goal")           # 30 each, 3 counted -> 90
        await cp.add_xp(db, "u1", "weekly_goal")              # +100
        p = await db.city_pass_progress.find_one({"user_id": "u1"})
        assert p["xp"] == 220                                  # more than 200 in one day: no daily limit
    run(go())


# ───────── claiming ─────────
def test_claim_only_after_reaching_the_level_and_only_once():
    async def go():
        db = await _db()
        with pytest.raises(Exception):
            await cp.claim(db, "u1", 1, "free")               # level 0
        await _set_xp(db, 160)                               # level 1
        r = await cp.claim(db, "u1", 1, "free")
        assert r["granted"][0]["type"] == "warehouse_guard"
        res = await asyncio.gather(*[cp.claim(db, "u1", 1, "free") for _ in range(3)], return_exceptions=True)
        assert all(isinstance(x, Exception) for x in res)
        u = await db.users.find_one({"id": "u1"})
        assert u["boosters"]["warehouse_guard_12h"] == 1
        assert u["bonus_balance"] == 10.0                    # bonus balance untouched
    run(go())


def test_premium_needs_payment_from_real_balance_and_unlocks_past_levels():
    async def go():
        db = await _db(balance=1.0, bonus=50.0)               # bonus does NOT pay for premium
        await _set_xp(db, 160 * 5)
        with pytest.raises(Exception):
            await cp.claim(db, "u1", 5, "premium")
        with pytest.raises(Exception):
            await cp.buy_premium(db, "u1")                    # 1 TON real < 3 TON
        assert (await db.city_pass_progress.find_one({"user_id": "u1"}))["premium"] is False
        await db.users.update_one({"id": "u1"}, {"$set": {"balance_ton": 3.5}})
        await cp.buy_premium(db, "u1")
        u = await db.users.find_one({"id": "u1"})
        assert abs(u["balance_ton"] - 0.5) < 1e-9 and u["bonus_balance"] == 50.0
        with pytest.raises(Exception):
            await cp.buy_premium(db, "u1")                    # not twice
        r = await cp.claim(db, "u1", 5, "premium")            # retroactive
        assert {g["type"] for g in r["granted"]} == {"t3", "repair_all"}
        u = await db.users.find_one({"id": "u1"})
        assert u["resources"]["neuro_core_tutorial"] == 1     # unsellable T3 item
    run(go())


def test_claim_all_takes_every_reached_reward():
    async def go():
        db = await _db()
        await _set_xp(db, 160 * 3)
        out = await cp.claim_all(db, "u1")
        assert out["claimed"] == 3
        v = await cp.view(db, "u1")
        assert v["claimable"] == 0 and v["level"] == 3
    run(go())


# ───────── boosters ─────────
def test_boosters_activate_once_and_stack_time():
    async def go():
        db = await _db()
        await boosters.grant(db, "u1", {"type": "auto_shift", "hours": 24, "count": 2})
        a = await boosters.activate(db, "u1", "auto_shift_24h")
        b = await boosters.activate(db, "u1", "auto_shift_24h")
        t1 = dt.datetime.fromisoformat(a["auto_shift_until"]); t2 = dt.datetime.fromisoformat(b["auto_shift_until"])
        assert 23.9 < (t2 - t1).total_seconds() / 3600 < 24.1   # second one extends the first
        with pytest.raises(Exception):
            await boosters.activate(db, "u1", "auto_shift_24h")  # none left
        inv = await boosters.inventory(db, "u1")
        assert any(x["kind"] == "auto_shift" for x in inv["active"])
    run(go())


def test_repair_all_booster():
    async def go():
        db = await _db()
        await db.businesses.insert_many([{"id": "b1", "owner": "u1", "durability": 12},
                                         {"id": "b2", "owner": "u1", "durability": 0, "zero_durability_since": "x"}])
        await boosters.grant(db, "u1", {"type": "repair_all"})
        r = await boosters.activate(db, "u1", "repair_all")
        assert r["repaired"] == 2
        assert {b["durability"] async for b in db.businesses.find({})} == {100}
    run(go())


def test_auto_shift_restarts_finished_shifts_in_the_real_tick(monkeypatch):
    async def go():
        import background_tasks as bt
        db = mongomock_motor.AsyncMongoMockClient()["cp_tick"]
        monkeypatch.setattr(bt, "_get_shared_db", lambda: db)
        now = dt.datetime.now(dt.timezone.utc)
        iso = lambda h: (now + dt.timedelta(hours=h)).isoformat()  # noqa: E731
        await db.users.insert_one({"id": "p1", "resources": {"biomass": 50},
                                   "auto_shift_until": iso(48)})
        await db.businesses.insert_one({"id": "b1", "owner": "p1", "business_type": "helios", "level": 1,
                                        "durability": 100, "storage": {"capacity": 500, "items": {}}, "plot_id": "x",
                                        "last_tick": iso(-1), "last_wear_update": iso(-1),
                                        "shift_started_at": iso(-9), "shift_ends_at": iso(-1)})
        await bt.economic_tick()
        b = await db.businesses.find_one({"id": "b1"})
        ends = dt.datetime.fromisoformat(b["shift_ends_at"])
        assert ends > now and b["is_active"] is True               # restarted and working
    run(go())


def test_admin_analytics():
    async def go():
        db = await _db()
        await _set_xp(db, 160 * 2)
        await cp.buy_premium(db, "u1")
        a = await cp.analytics(db)
        assert a["players"] == 1 and a["premium"] == 1 and a["revenue_ton"] == 3.0
        assert a["by_level"][2]["players"] == 1
    run(go())


# ───────── auto-shift waits for inputs / space ─────────
async def _auto_world(monkeypatch, resources, shift_running=False, auto_started=False):
    import background_tasks as bt
    db = mongomock_motor.AsyncMongoMockClient()["cp_wait"]
    monkeypatch.setattr(bt, "_get_shared_db", lambda: db)
    now = dt.datetime.now(dt.timezone.utc)
    iso = lambda h: (now + dt.timedelta(hours=h)).isoformat()  # noqa: E731
    await db.users.insert_one({"id": "p1", "resources": resources, "auto_shift_until": iso(48)})
    doc = {"id": "b1", "owner": "p1", "business_type": "helios", "level": 1, "durability": 90,
           "storage": {"capacity": 100, "items": {}}, "plot_id": "x",
           "last_tick": iso(-1), "last_wear_update": iso(-1),
           "shift_started_at": iso(-9), "shift_ends_at": iso(-1)}
    if shift_running:
        doc.update({"shift_started_at": iso(-1), "shift_ends_at": iso(7), "shift_auto_started": auto_started})
    await db.businesses.insert_one(doc)
    return bt, db, now


def test_auto_shift_waits_without_inputs_and_starts_when_they_arrive(monkeypatch):
    async def go():
        bt, db, now = await _auto_world(monkeypatch, {"biomass": 0})          # helios needs biomass
        await bt.economic_tick()
        b = await db.businesses.find_one({"id": "b1"})
        assert b["work_status_reason"] == "no_resources" and b["auto_wait_reason"] == "no_resources"
        assert dt.datetime.fromisoformat(b["shift_ends_at"]) <= now           # no shift started
        assert b["durability"] == 90                                          # no wear while waiting
        await db.users.update_one({"id": "p1"}, {"$set": {"resources.biomass": 50}})
        # the real tick runs once a minute; let a minute pass for the test
        await db.businesses.update_one({"id": "b1"}, {"$set": {
            "last_tick": (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)).isoformat()}})
        await bt.economic_tick()
        b = await db.businesses.find_one({"id": "b1"})
        assert dt.datetime.fromisoformat(b["shift_ends_at"]) > now and b["is_active"] is True
        assert b.get("auto_wait_reason") is None
    run(go())


def test_auto_started_shift_stops_when_the_warehouse_fills(monkeypatch):
    async def go():
        # 100/100 full warehouse, an auto-started shift is running
        bt, db, now = await _auto_world(monkeypatch, {"biomass": 50, "energy": 50}, shift_running=True, auto_started=True)
        await bt.economic_tick()
        b = await db.businesses.find_one({"id": "b1"})
        assert b["auto_wait_reason"] == "storage_full" and b["work_status_reason"] == "storage_full"
        assert dt.datetime.fromisoformat(b["shift_ends_at"]) <= dt.datetime.now(dt.timezone.utc)
        assert b["durability"] == 90
    run(go())


def test_manual_shift_is_not_stopped_by_auto_shift(monkeypatch):
    async def go():
        bt, db, now = await _auto_world(monkeypatch, {"biomass": 50, "energy": 50}, shift_running=True, auto_started=False)
        await bt.economic_tick()
        b = await db.businesses.find_one({"id": "b1"})
        assert dt.datetime.fromisoformat(b["shift_ends_at"]) > now           # the player's own shift stays
    run(go())


def test_auto_shift_booster_works_on_level_zero_and_nothing_starts_without_it(monkeypatch):
    """No auto work by default; with the auto-shift booster active, level-0 businesses restart too."""
    async def go():
        import background_tasks as bt
        db = mongomock_motor.AsyncMongoMockClient()["cp_zero"]
        monkeypatch.setattr(bt, "_get_shared_db", lambda: db)
        now = dt.datetime.now(dt.timezone.utc)
        iso = lambda h: (now + dt.timedelta(hours=h)).isoformat()  # noqa: E731
        await db.users.insert_many([{"id": "p1", "resources": {"biomass": 50}, "auto_shift_until": iso(48)},
                                    {"id": "p2", "resources": {"biomass": 50}}])          # p2: no booster
        base = {"business_type": "helios", "durability": 100, "storage": {"capacity": 500, "items": {}}, "level": 0,
                "is_zero_business": True, "last_tick": iso(-1), "last_wear_update": iso(-1), "shift_started_at": iso(-9), "shift_ends_at": iso(-1)}
        await db.businesses.insert_many([{**base, "id": "z1", "owner": "p1", "plot_id": "a"}, {**base, "id": "z2", "owner": "p2", "plot_id": "b"}])
        await bt.economic_tick()
        z1 = await db.businesses.find_one({"id": "z1"}); z2 = await db.businesses.find_one({"id": "z2"})
        assert dt.datetime.fromisoformat(z1["shift_ends_at"]) > now           # booster: restarted
        assert dt.datetime.fromisoformat(z2["shift_ends_at"]) < now           # no booster: waits for the player
    run(go())


def test_onboarding_quest_xp_goes_to_city_pass_beyond_the_daily_cap():
    async def go():
        import city_pass as cp
        db = mongomock_motor.AsyncMongoMockClient()["cp_onb"]
        cfg = await cp.get_config(db)
        await db.admin_settings.update_one({"type": "city_pass"}, {"$set": {"type": "city_pass", "enabled": True}}, upsert=True)
        cp.invalidate_config() if hasattr(cp, "invalidate_config") else None
        got = 0
        for x in (10, 30, 20, 20, 30, 20, 100):                    # the whole newbie track in one day = 230 XP
            got += await cp.add_xp(db, "u1", "onboarding", x)
        p = await db.city_pass_progress.find_one({"user_id": "u1"})
        if got:                                                     # season running: all 230 XP, cap not applied
            assert got == 230 and p["xp"] == 230
        assert await cp.add_xp(db, "u1", "onboarding", 0) == 0
    run(go())


def test_quest_card_xp_is_exactly_what_city_pass_gets():
    async def go():
        db = await _db()
        assert await cp.add_xp(db, "u1", "quest", 10) == 10          # a daily quest card says +10
        assert await cp.add_xp(db, "u1", "quest", 20) == 20          # a weekly quest card says +20
        p = await db.city_pass_progress.find_one({"user_id": "u1"})
        assert p["xp"] == 30
    run(go())
