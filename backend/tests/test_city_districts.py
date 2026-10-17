import asyncio
import pytest
mongomock_motor = pytest.importorskip("mongomock_motor")
from fastapi import FastAPI
from fastapi.testclient import TestClient
import city_districts as cd
from city_island import build_city_island


def test_district_rules_and_admin_api():
    db = mongomock_motor.AsyncMongoMockClient()["cdist"]
    app = FastAPI(); app.include_router(cd.create_city_districts_router(db, lambda: {"id": "a"}))
    c = TestClient(app)
    cells = build_city_island()["cells"]
    north = sorted((x for x in cells if x["district"] == 2), key=lambda x: x["slot_id"])
    old_cell = {"x": 1, "y": 1}                                     # old-map cell: no district rule

    async def is_open(cell):
        return await cd.cell_open(db, cell)
    assert not asyncio.run(is_open(north[0])) and asyncio.run(is_open(old_cell))   # nothing on sale by default
    c.put("/api/admin/city/districts", json={"open_count": {"2": 119}})
    assert asyncio.run(is_open(north[0]))
    c.put("/api/admin/city/districts", json={"unlocked": {"2": False}})
    assert not asyncio.run(is_open(north[0])) and asyncio.run(is_open(old_cell))
    c.put("/api/admin/city/districts", json={"unlocked": {"2": True}, "open_count": {"2": 10}})
    assert asyncio.run(is_open(north[9])) and not asyncio.run(is_open(north[10]))   # first 10 only (big first)
    assert c.get("/api/city/districts").json()["open_count"]["2"] == 10
    assert c.put("/api/admin/city/districts", json={"open_count": {"2": 500}}).status_code == 400
    assert c.put("/api/admin/city/districts", json={"unlocked": {"9": True}}).status_code == 400
