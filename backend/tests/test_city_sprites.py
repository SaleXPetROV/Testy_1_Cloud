import asyncio
import pytest
mongomock_motor = pytest.importorskip("mongomock_motor")
from fastapi import FastAPI
from fastapi.testclient import TestClient
import city_sprites


def make_client():
    db = mongomock_motor.AsyncMongoMockClient()["cs"]
    app = FastAPI()
    app.include_router(city_sprites.create_city_sprites_router(db, lambda: {"id": "admin"}))
    return TestClient(app)


def test_tuning_set_all_stages_reset_and_validation():
    c = make_client()
    assert c.get("/api/city-sprites/tuning").json() == {"tuning": {}, "overrides": {}, "overrides_alt": {}}
    r = c.put("/api/admin/city-sprites/tuning", json={"type": "cyber_cafe", "stage": "all", "scale": 1.2, "dx": 0.05, "dy": -0.02})
    t = r.json()["tuning"]["cyber_cafe"]
    assert set(t) == {"1", "2", "3"} and t["2"] == {"scale": 1.2, "sx": 1.0, "sy": 1.0, "dx": 0.05, "dy": -0.02}
    t = c.put("/api/admin/city-sprites/tuning", json={"type": "dex", "stage": "1", "sx": 0.8, "sy": 1.4}).json()["tuning"]["dex"]["1"]
    assert t["sx"] == 0.8 and t["sy"] == 1.4
    c.put("/api/admin/city-sprites/tuning", json={"type": "cyber_cafe", "stage": "3", "scale": 0.9})
    assert c.get("/api/city-sprites/tuning").json()["tuning"]["cyber_cafe"]["3"]["scale"] == 0.9
    c.delete("/api/admin/city-sprites/tuning/cyber_cafe/1")
    assert "1" not in c.get("/api/city-sprites/tuning").json()["tuning"]["cyber_cafe"]
    for bad in ({"type": "nope", "scale": 1}, {"type": "dex", "stage": "7"}, {"type": "dex", "scale": 9}, {"type": "dex", "dx": 2}, {"type": "dex", "sy": 5}):
        assert c.put("/api/admin/city-sprites/tuning", json=bad).status_code == 400


def test_upload_replaces_a_sprite_and_reset(tmp_path, monkeypatch):
    import io
    from PIL import Image, ImageDraw
    monkeypatch.setenv("UPLOADS_ROOT", str(tmp_path))
    c = make_client()
    # a building on a dark opaque background (like the owner's pictures)
    im = Image.new("RGB", (600, 600), (4, 6, 14)); d = ImageDraw.Draw(im)
    d.polygon([(100, 420), (300, 520), (500, 420), (300, 320)], fill=(60, 70, 110))        # foundation diamond
    d.rectangle([220, 180, 380, 440], fill=(30, 160, 220))                                    # building
    buf = io.BytesIO(); im.save(buf, "PNG")
    r = c.post("/api/admin/city-sprites/upload", data={"type": "helios", "stage": "all"}, files={"file": ("h.png", buf.getvalue(), "image/png")})
    assert r.status_code == 200, r.text
    ov = r.json()["overrides"]["helios"]
    assert set(ov) == {"1", "2", "3"} and ov["1"]["url"].startswith("/api/city-sprites/file/helios/")
    assert 0.6 < ov["1"]["footprint_width"] < 0.95 and ov["1"]["size"] == [400, 500]
    f = c.get(ov["1"]["url"]); assert f.status_code == 200 and f.headers["content-type"] == "image/webp"
    got = Image.open(io.BytesIO(f.content)); assert got.mode == "RGBA" and got.getpixel((5, 5))[3] == 0     # background cut
    assert c.get("/api/city-sprites/tuning").json()["overrides"]["helios"]["2"]["url"] == ov["2"]["url"]
    assert c.get("/api/city-sprites/file/helios/..%2Fsecret.webp").status_code == 404
    assert c.post("/api/admin/city-sprites/upload", data={"type": "helios", "view": "alt"}, files={"file": ("h.png", buf.getvalue(), "image/png")}).status_code == 400
    c.delete("/api/admin/city-sprites/override/helios/all")
    assert c.get("/api/city-sprites/tuning").json()["overrides"].get("helios", {}) == {}
