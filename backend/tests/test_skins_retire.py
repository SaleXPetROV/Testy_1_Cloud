"""/api/skins/index must not fail when the old «standard» picture already exists in «classic» (was a 503)."""
import asyncio
import pytest
mongomock_motor = pytest.importorskip("mongomock_motor")
from fastapi import FastAPI
from fastapi.testclient import TestClient
from routes import skins


def test_index_ok_with_duplicate_standard_and_classic():
    db = mongomock_motor.AsyncMongoMockClient()["sk"]
    skins._retired["done"] = False

    async def prep():
        await skins.ensure_skin_indexes(db)
        await db.business_skins.insert_many([
            {"id": "a", "group_key": "classic", "business_type": "bio_farm", "level": 0, "image": "/x.webp"},
            {"id": "b", "group_key": "standard", "business_type": "bio_farm", "level": 0, "image": "/x.webp"},
            {"id": "c", "group_key": "standard", "business_type": "helios", "level": 0, "image": "/y.webp"}])
        await skins.seed_default_skins(db)
    asyncio.run(prep())
    app = FastAPI(); app.include_router(skins.create_skins_user_router(db, lambda: None))
    r = TestClient(app).get("/api/skins/index")
    assert r.status_code == 200
    idx = r.json()["index"]
    assert "standard" not in idx and idx["classic"]["bio_farm"]["0"] and idx["classic"]["helios"]["0"]
