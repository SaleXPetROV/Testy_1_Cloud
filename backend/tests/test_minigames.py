"""«Сортировщик» promotion: server-side score, attempts, anti-cheat, prizes; same rules as the app."""
import asyncio, datetime as dt, json, os, shutil, subprocess
import pytest
mongomock_motor = pytest.importorskip("mongomock_motor")
from fastapi import FastAPI
from fastapi.testclient import TestClient
import minigames as mg, minigames_sorter as ms


class U:
    def __init__(self, uid): self.id = uid


def world(monkeypatch):
    db = mongomock_motor.AsyncMongoMockClient()["mg"]
    who = {"u": "p1"}
    app = FastAPI(); app.include_router(mg.create_minigames_router(db, lambda: U(who["u"]), lambda: {"id": "adm"}, None))
    c = TestClient(app)
    import city_pass
    got = []
    async def fake_xp(_db, uid, action, n=1, ton=0.0): got.append((uid, n)); return n
    monkeypatch.setattr(city_pass, "add_xp", fake_xp)
    now = dt.datetime.now(dt.timezone.utc)
    c.put("/api/admin/minigames/event", json={"enabled": True, "starts_at": (now - dt.timedelta(hours=1)).isoformat(),
                                              "ends_at": (now + dt.timedelta(days=7)).isoformat(), "attempts_per_day": 2})
    async def users():
        await db.users.insert_many([{"id": "p1", "username": "alice"}, {"id": "p2", "username": "bob"}])
    asyncio.run(users())
    return db, c, who, got


def perfect(seed, reaction=400, n=100):
    """A good player: right answers for n items, then stops tapping (loses the 3 lives by time)."""
    t, acts = 0, []
    for it in ms.make_items(seed)[:n]:
        a = {"i": it["i"], "b": -1 if it["hazard"] else it["type"], "t": t + min(reaction, it["window"] - 10)}
        t = a["t"] + ms.GAP_MS; acts.append(a)
    return acts


def test_server_replays_the_score_and_cheats_get_nothing(monkeypatch):
    db, c, who, got = world(monkeypatch)
    s = c.post("/api/minigames/sorter/start").json()
    async def backdate(sid):                                       # pretend the game really lasted long enough
        await db.minigame_sessions.update_one({"id": sid}, {"$set": {"started_at": (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=2)).isoformat()}})
    asyncio.run(backdate(s["session_id"]))
    r = c.post("/api/minigames/sorter/finish", json={"session_id": s["session_id"], "actions": perfect(s["seed"])}).json()
    assert r["stars"] == 3 and r["points"] >= 2000 and r["cleared"] >= 100 and r["xp"] == 35 and got == [("p1", 35)]
    assert c.post("/api/minigames/sorter/finish", json={"session_id": s["session_id"], "actions": []}).status_code == 409   # once
    # superhuman reactions (60 ms) are not counted
    s2 = c.post("/api/minigames/sorter/start").json(); asyncio.run(backdate(s2["session_id"]))
    r2 = c.post("/api/minigames/sorter/finish", json={"session_id": s2["session_id"], "actions": perfect(s2["seed"], reaction=60)}).json()
    assert r2["stars"] == 0 and r2["points"] < 300                   # every tap ignored -> 3 items missed -> game over (only skipped hazards count)
    assert c.post("/api/minigames/sorter/start").status_code == 429                          # an admin limit of 2 games a day (0 = unlimited)
    ev = c.get("/api/minigames/event").json()
    assert ev["active"] and ev["top"][0]["username"] == "alice" and ev["top"][0]["points"] == r["points"] + r2["points"]


def test_a_game_longer_than_real_time_is_rejected(monkeypatch):
    db, c, who, got = world(monkeypatch)
    s = c.post("/api/minigames/sorter/start").json()                 # started just now
    r = c.post("/api/minigames/sorter/finish", json={"session_id": s["session_id"], "actions": perfect(s["seed"])}).json()
    assert r["rejected"] and r["points"] == 0 and r["xp"] == 0       # a 50-second game «finished» in 0 s


def test_prizes_once_when_the_event_ends(monkeypatch):
    db, c, who, got = world(monkeypatch)
    async def go():
        await db.minigame_points.insert_many([{"campaign_id": mg.EVENT_ID, "user_id": "p1", "points": 900, "updated_at": "1"},
                                              {"campaign_id": mg.EVENT_ID, "user_id": "p2", "points": 1200, "updated_at": "2"}])
        later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=8)
        assert (await mg.finalize(db, now=later))["awarded"] == 2
        assert (await mg.finalize(db, now=later))["awarded"] == 0                              # only once
        bob = await db.users.find_one({"id": "p2"}); alice = await db.users.find_one({"id": "p1"})
        assert bob["bonus_balance"] == pytest.approx(5.0) and alice["bonus_balance"] == pytest.approx(2.5)   # 5000 / 2500 $CITY
    asyncio.run(go())


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_same_rules_in_the_app_and_on_the_server():
    root = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "src", "minigames", "sorterCore.js")
    js = subprocess.run(["node", "--input-type=module", "-e",
        f"import {{ makeItems, score }} from '{os.path.abspath(root)}'; const o={{}}; for (const s of [7, 99, 31337]) {{ let t=0; const a=makeItems(s).slice(0,90).map(x=>{{const r={{i:x.i,b:x.hazard?-1:(x.i%13===12?(x.type+1)%4:x.type),t:t+Math.min(380,x.window-10)}}; t=r.t+250; return r;}}); o[s]={{i:makeItems(s).map(x=>[x.type,x.hazard?1:0,x.window]), a, sc:score(s,a)}}; }} console.log(JSON.stringify(o));"],
        capture_output=True, text=True, timeout=60).stdout
    for s, v in json.loads(js).items():
        assert [[x["type"], 1 if x["hazard"] else 0, x["window"]] for x in ms.make_items(int(s))] == v["i"]
        py = ms.score(int(s), v["a"])
        assert all(py[k] == v["sc"][k] for k in ("points", "cleared", "lives_left", "last_item", "best_combo"))



def test_endless_mode_three_lives():
    seed = 777
    items = ms.make_items(seed)
    assert items[0]["window"] == 1600 and items[120]["window"] == 450 and items[300]["window"] == 450   # faster, then flat
    t, acts, wrong = 0, [], 0
    for it in items[:50]:                                              # 3 wrong bins -> game over right there
        b = -1 if it["hazard"] else it["type"]
        if not it["hazard"] and it["i"] in (5, 10, 15):
            b = (it["type"] + 1) % 4; wrong += 1
        a = {"i": it["i"], "b": b, "t": t + 400}; t = a["t"] + ms.GAP_MS; acts.append(a)
    r = ms.score(seed, acts)
    assert r["lives_left"] == 0 and r["last_item"] == 15 and r["cleared"] == 13
