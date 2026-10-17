"""Task / daily-login rewards go to the BONUS balance; tasks are split into
«Система» and «Партнёры».

    cd backend && python -m pytest tests/test_task_rewards_bonus.py -q
"""
import asyncio

import pytest

mongomock_motor = pytest.importorskip("mongomock_motor")
from routes.tasks import credit_task_reward_bonus, task_category  # noqa: E402


def test_reward_goes_to_bonus_not_real_balance():
    async def go():
        db = mongomock_motor.AsyncMongoMockClient()["tr"]
        await db.users.insert_one({"id": "u1", "balance_ton": 1.0, "bonus_balance": None, "total_income": 0})
        await credit_task_reward_bonus(db, "u1", 150, "Daily login reward")
        u = await db.users.find_one({"id": "u1"})
        assert u["balance_ton"] == 1.0                       # withdrawable balance untouched
        assert abs(u["bonus_balance"] - 0.150) < 1e-9        # null coerced, then credited
        assert u["total_income"] == 0
        tx = await db.transactions.find_one({"user_id": "u1"})
        assert tx["balance"] == "bonus" and tx["reward_city"] == 150
    asyncio.run(go())


def test_zero_or_bad_reward_is_ignored():
    async def go():
        db = mongomock_motor.AsyncMongoMockClient()["tr2"]
        await db.users.insert_one({"id": "u1", "bonus_balance": 0.0})
        await credit_task_reward_bonus(db, "u1", 0, "x")
        await credit_task_reward_bonus(db, "u1", "abc", "x")
        assert (await db.users.find_one({"id": "u1"}))["bonus_balance"] == 0.0
        assert await db.transactions.count_documents({}) == 0
    asyncio.run(go())


def test_task_category():
    assert task_category({"action_type": "partner_quest", "quest_kind": "partner"}) == "partner"
    assert task_category({"action_type": "partner_quest", "quest_kind": "local"}) == "system"
    assert task_category({"action_type": "partner_quest"}) == "system"          # default kind = local
    assert task_category({"action_type": "subscribe_channel"}) == "system"
    assert task_category({"action_type": "repost_story"}) == "system"


def test_no_task_reward_path_writes_the_real_balance():
    """Static guard: routes/tasks.py must not credit balance_ton anywhere."""
    import pathlib, re
    src = pathlib.Path(__file__).resolve().parents[1].joinpath("routes", "tasks.py").read_text()
    assert not re.search(r'"\$inc":\s*\{[^}]*"balance_ton"', src)
