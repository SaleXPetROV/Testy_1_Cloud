"""Shared rules: shift (core/business_rules.py) and ownership (core/helpers.py).

    cd backend && python -m pytest tests/test_shared_rules.py -q
"""
import asyncio
import datetime as dt
import types

import pytest

mongomock_motor = pytest.importorskip("mongomock_motor")
from core import business_rules as br  # noqa: E402
from core.helpers import get_user_identifiers, resolve_owner_keys, owner_businesses_query  # noqa: E402


def _iso(h):
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=h)).isoformat()


# ───────────── shift ─────────────
def test_shift_rule():
    assert br.shift_is_active({"shift_ends_at": _iso(1)}) is True
    assert br.shift_is_active({"shift_ends_at": _iso(-1)}) is False
    assert br.shift_is_active({}) is False
    assert br.shift_is_active({"is_zero_business": True, "level": 0}) is False      # level 0 needs a shift
    assert br.shift_is_active({"tutorial": True}) and br.shift_is_active({"is_trial": True})
    assert br.shift_is_active({"shift_ends_at": "garbage"}) is False


def test_tick_and_server_use_the_same_function():
    import background_tasks
    assert background_tasks.shift_is_active is br.shift_is_active


# ───────────── ownership ─────────────
def test_get_user_identifiers_never_matches_a_stranger():
    async def go():
        db = mongomock_motor.AsyncMongoMockClient()["own"]
        await db.users.insert_many([
            {"id": "other", "wallet_address": None, "email": "other@x.io"},       # inserted first
            {"id": "me", "wallet_address": None, "email": "me@x.io", "username": "meuser"},
        ])
        me = types.SimpleNamespace(id="me", wallet_address=None, email="me@x.io")
        r = await get_user_identifiers(db, me)
        assert r["primary_id"] == "me" and r["user"]["id"] == "me"
        assert r["ids"] == {"me", "me@x.io", "meuser"}
    asyncio.run(go())


def test_business_found_by_owner_wallet_or_username():
    async def go():
        db = mongomock_motor.AsyncMongoMockClient()["own2"]
        await db.users.insert_one({"id": "u", "wallet_address": "EQw", "email": "u@x.io", "username": "uname"})
        await db.businesses.insert_many([
            {"id": "b1", "owner": "uname"},              # legacy: owner stored as username
            {"id": "b2", "owner": "x", "owner_wallet": "EQw"},
        ])
        keys = await resolve_owner_keys(db, "u")
        found = {b["id"] async for b in db.businesses.find(owner_businesses_query(keys))}
        assert found == {"b1", "b2"}
    asyncio.run(go())


def test_quests_has_business_uses_shared_rule():
    """Quest 'open your first business' must see a business stored under the username."""
    async def go():
        import quests
        db = mongomock_motor.AsyncMongoMockClient()["own3"]
        quests.init(db)
        await db.users.insert_one({"id": "u", "username": "uname"})
        await db.businesses.insert_one({"id": "b1", "owner": "uname"})
        assert await quests._has_business("u") is True
    asyncio.run(go())
