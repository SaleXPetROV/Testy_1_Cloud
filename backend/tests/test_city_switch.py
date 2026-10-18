"""The switch to the new map must see an OLD island (it has no "version" field)."""
import asyncio
import pytest
mongomock_motor = pytest.importorskip("mongomock_motor")
import city_switch


def test_old_island_without_version_needs_the_switch():
    async def go():
        db = mongomock_motor.AsyncMongoMockClient()["sw"]
        assert await city_switch.needs_switch(db) is False                     # no island: fresh start
        await db.islands.insert_one({"id": "ton_island", "cells": []})         # old island: no version
        assert await city_switch.needs_switch(db) is True
        await db.islands.update_one({"id": "ton_island"}, {"$set": {"version": "city_v1"}})
        assert await city_switch.needs_switch(db) is False
        await db.businesses.insert_one({"id": "b", "owner": "u1"})             # a business without a slot
        assert await city_switch.needs_switch(db) is True
    asyncio.run(go())
