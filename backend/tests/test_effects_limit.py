"""Not more than 2 boosters / tier-3 buffs at the same time (core/effects.py)."""
import asyncio, datetime as dt
import pytest
mongomock_motor = pytest.importorskip("mongomock_motor")
import boosters
import minigame_rewards as mr
from core.effects import active_effects, can_activate


def iso(h):
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=h)).isoformat()


def test_rule():
    u = {"auto_shift_until": iso(2), "active_resource_buffs": [{"resource_id": "neuro_core", "expires_at": iso(5)}]}
    assert sorted(active_effects(u)) == ["auto_shift", "t3:neuro_core"]
    assert not can_activate(u, "warehouse_guard")
    assert can_activate(u, "auto_shift")                     # extending a running one is fine
    assert can_activate({"auto_shift_until": iso(-1)}, "xp_x2")


def test_boosters_and_game_boosters_respect_the_limit():
    db = mongomock_motor.AsyncMongoMockClient()["fx"]

    async def go():
        await mr.seed_defaults(db)
        await db.users.insert_one({"id": "u", "boosters": {"auto_shift_24h": 1, "warehouse_guard_24h": 1, "xp_x2_12h": 1}})
        await boosters.activate(db, "u", "auto_shift_24h")
        await boosters.activate(db, "u", "xp_x2_12h")
        with pytest.raises(Exception) as e:
            await boosters.activate(db, "u", "warehouse_guard_24h")
        assert "boosters_limit" in str(getattr(e.value, "detail", e.value))
        # a booster won in the game: 2 already run -> it goes to the inventory instead of activating
        got = await mr.grant_booster(db, "u", "b_guard_24", "game")
        assert got["status"] == "stored"
        u = await db.users.find_one({"id": "u"})
        assert u["boosters"]["warehouse_guard_24h"] == 2
        # with a free slot it activates at once
        await db.users.insert_one({"id": "v"})
        got = await mr.grant_booster(db, "v", "b_xp_x2_12", "game")
        assert got["status"] == "active" and (await db.users.find_one({"id": "v"}))["xp_x2_until"]
    asyncio.run(go())
