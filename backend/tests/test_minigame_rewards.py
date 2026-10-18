"""Rewards of the «Сортировщик» promotion — the acceptance criteria of the spec (section 13)."""
import asyncio
import datetime as dt
from collections import Counter

import pytest

mongomock_motor = pytest.importorskip("mongomock_motor")
from fastapi import FastAPI
from fastapi.testclient import TestClient

import minigame_rewards as mr
import minigames as mg
import minigames_sorter as ms
import minigame_rewards_routes as mrr


class U:
    def __init__(self, uid): self.id = uid


def run(coro):
    return asyncio.run(coro)


def fresh_db():
    return mongomock_motor.AsyncMongoMockClient()["rw"]


async def base(db):
    await mr.ensure_indexes(db)
    await mr.seed_defaults(db)
    await db.users.insert_many([{"id": f"p{i}", "username": f"user{i}", "resources": {}} for i in range(1, 6)])


def world(monkeypatch, tmp_path=None):
    db = fresh_db()
    who = {"u": "p1"}
    app = FastAPI()
    app.include_router(mg.create_minigames_router(db, lambda: U(who["u"]), lambda: {"id": "adm"}, None))
    app.include_router(mrr.create_minigame_rewards_router(db, lambda: U(who["u"]), lambda: {"id": "adm"}, mg.get_config))
    c = TestClient(app)
    import city_pass

    async def fake_xp(_db, uid, action, n=1, ton=0.0):
        return n
    monkeypatch.setattr(city_pass, "add_xp", fake_xp)
    if tmp_path is not None:
        monkeypatch.setenv("UPLOADS_ROOT", str(tmp_path))
    run(base(db))
    now = dt.datetime.now(dt.timezone.utc)
    c.put("/api/admin/minigames/event", json={"enabled": True, "starts_at": (now - dt.timedelta(hours=1)).isoformat(),
                                              "ends_at": (now + dt.timedelta(days=7)).isoformat()})
    return db, c, who


def perfect(seed, reaction=400, n=100, jitter=True):
    t, acts = 0, []
    for it in ms.make_items(seed)[:n]:
        r = min(reaction + ((it["i"] * 37) % 120 if jitter else 0), it["window"] - 10)
        a = {"i": it["i"], "b": -1 if it["hazard"] else it["type"], "t": t + r}
        t = a["t"] + ms.GAP_MS
        acts.append(a)
    return acts


def play(db, c, n=100, reaction=400, jitter=True):
    s = c.post("/api/minigames/sorter/start").json()
    run(db.minigame_sessions.update_one({"id": s["session_id"]}, {"$set": {
        "started_at": (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=3)).isoformat()}}))
    return c.post("/api/minigames/sorter/finish", json={"session_id": s["session_id"],
                                                        "actions": perfect(s["seed"], reaction, n, jitter)}).json()


# ───────────── thresholds ─────────────
def test_thresholds_exact_below_and_jump(monkeypatch):
    db = fresh_db()
    run(base(db))

    async def go():
        assert await mr.check_thresholds(db, "p1", "camp", points=14999, best=999) == []         # 1 below
        got = await mr.check_thresholds(db, "p1", "camp", points=15000, best=1000)              # exactly on it
        assert sorted(g["reward"]["code"] for g in got) == ["best_chest", "pts_chest"]
        got = await mr.check_thresholds(db, "p1", "camp", points=51000, best=1000)              # jump over two at once
        assert sorted(g["reward"]["code"] for g in got) == ["pts_autoshift", "pts_badge"]
        assert await mr.check_thresholds(db, "p1", "camp", points=51000, best=1000) == []       # never twice
        assert await db.mg_user_boosters.count_documents({"user_id": "p1", "status": "active"}) == 1   # activated at once
        assert await db.mg_user_containers.count_documents({"user_id": "p1"}) == 2
        assert not await db.mg_rewards.find_one({"type": "frame", "is_active": True})          # no frame reward any more
        # a new campaign gives the points rewards again, the record rewards stay once for all time
        again = await mr.check_thresholds(db, "p1", "camp2", points=15000, best=1000)
        assert [g["reward"]["code"] for g in again] == ["pts_chest"]
    run(go())


def test_concurrent_grant_only_once():
    db = fresh_db()
    run(base(db))

    async def go():
        rw = await db.mg_rewards.find_one({"code": "pts_chest"}, {"_id": 0})
        res = await asyncio.gather(*[mr.grant_reward(db, "p1", rw, "camp") for _ in range(8)])
        assert sum(1 for r in res if r) == 1
        assert await db.mg_user_rewards.count_documents({"user_id": "p1"}) == 1
        assert await db.mg_user_containers.count_documents({"user_id": "p1"}) == 1
    run(go())


# ───────────── chest for a game ─────────────
def test_chest_needs_two_stars_and_max_four_a_day(monkeypatch):
    db = fresh_db()
    run(base(db))
    day = {"d": "2026-10-17"}
    monkeypatch.setattr(mr, "msk_day", lambda: day["d"])
    cfg = {"chest_container_id": "c_sorter", "chest_min_stars": 2, "chests_per_day": 4}

    async def go():
        assert (await mr.game_chest(db, "p1", "s0", 1, cfg))["reason"] == "low_stars"           # ★ — no
        got = [await mr.game_chest(db, "p1", f"s{i}", 2 + i % 2, cfg) for i in range(1, 6)]
        assert [g["given"] for g in got] == [True, True, True, True, False]                     # the 5th — no
        assert got[-1]["reason"] == "daily_limit" and got[-1]["chests_today"] == 4
        day["d"] = "2026-10-18"                                                                 # a new MSK day — 4 again
        assert (await mr.game_chest(db, "p1", "s9", 3, cfg))["given"]
        assert await db.mg_user_containers.count_documents({"user_id": "p1", "source": "game"}) == 5
    run(go())


def test_finish_response_has_chest_points_and_new_rewards(monkeypatch):
    db, c, who = world(monkeypatch)
    r = play(db, c)
    assert r["stars"] == 3 and r["chest"]["given"] and r["chests_today"] == 1 and r["chests_per_day"] == 4
    assert r["campaign_points"] == r["points"] and r["best_score"] == r["points"]
    assert {x["type"] for x in r["new_rewards"]} >= {"container", "booster"}      # record ≥ 2000: chest + ×2 XP
    me = c.get("/api/minigames/rewards/me").json()
    assert me["chests_today"] == 1 and me["campaign_points"] == r["points"]
    # the game chest + the threshold chest are opened at once (closed only while waiting for warehouse room)
    opened = [x for x in r["opened_chests"] if x["status"] == "opened"]
    waiting = [x for x in r["opened_chests"] if x["status"] != "opened"]
    assert len(r["opened_chests"]) >= 2 and all(x.get("waiting_space") for x in waiting)
    assert me["unopened"] == len(waiting) and all(x["results"] for x in opened)


# ───────────── leaderboard + campaign end ─────────────
def test_leaderboard_me_outside_top_prizes_and_ties(monkeypatch):
    db, c, who = world(monkeypatch)

    async def fill():
        for i, (u, p, t) in enumerate([("p1", 900, "3"), ("p2", 1200, "1"), ("p3", 900, "2"), ("p4", 50, "4")]):
            await db.minigame_points.insert_one({"campaign_id": mg.EVENT_ID, "user_id": u, "points": p, "updated_at": t})
    run(fill())
    c.put("/api/admin/minigames/event", json={"leaderboard_prizes": [{"from": 1, "to": 1, "kind": "nft", "ref_id": "n_sorter_master"},
                                                                     {"from": 2, "to": 3, "kind": "container", "ref_id": "c_sorter"}]})
    who["u"] = "p4"
    lb = run(mr.leaderboard(db, mg.EVENT_ID, uid="p4", limit=2, prizes=run(mg.get_config(db))["leaderboard_prizes"]))
    assert [r["user_id"] for r in lb["rows"]] == ["p2", "p3"]                 # p3 reached 900 earlier than p1
    assert lb["rows"][0]["prize"]["kind"] == "nft" and lb["rows"][0]["prize"]["name"] == "Мастер сортировки"
    assert lb["me"] == {"place": 4, "points": 50, "prize": None, "username": "user4"}   # me always, even outside the top
    # the end: prizes exactly by places, once; points of the campaign stop, the record stays
    run(db.users.update_one({"id": "p2"}, {"$set": {"mg_best_score": 1200}}))
    rep = c.post("/api/admin/minigames/campaign/finish").json()
    assert rep["awarded"] == 3
    assert c.post("/api/admin/minigames/campaign/finish").status_code == 409
    assert run(db.mg_nft_grants.count_documents({"user_id": "p2", "source": "leaderboard"})) == 1
    assert run(db.mg_user_containers.count_documents({"source": "leaderboard"})) == 2
    assert run(db.mg_user_containers.count_documents({"user_id": "p4"})) == 0
    assert c.get("/api/minigames/event").json()["active"] is False
    assert run(db.users.find_one({"id": "p2"}))["mg_best_score"] == 1200
    # a new campaign: points from zero
    c.put("/api/admin/minigames/event", json={"event_id": "sorter_week_2", "enabled": True})
    assert run(mr.campaign_points(db, "p2", "sorter_week_2")) == 0


def test_points_only_while_the_campaign_is_active(monkeypatch):
    db, c, who = world(monkeypatch)
    s = c.post("/api/minigames/sorter/start").json()
    c.put("/api/admin/minigames/event", json={"enabled": False})
    run(db.minigame_sessions.update_one({"id": s["session_id"]}, {"$set": {
        "started_at": (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=3)).isoformat()}}))
    r = c.post("/api/minigames/sorter/finish", json={"session_id": s["session_id"], "actions": perfect(s["seed"])}).json()
    assert r["points"] > 0 and r["campaign_points"] == 0 and r["chest"]["given"] is False
    assert r["best_score"] == r["points"]                                     # the record still counts


# ───────────── containers ─────────────
def test_container_weights_bounds_and_zero_weight(monkeypatch):
    # the roll itself: 10 000 draws within 3 % of the weights
    cnt = Counter(mr._roll_index([50, 30, 20]) for _ in range(10000))
    for i, w in enumerate((0.5, 0.3, 0.2)):
        assert abs(cnt[i] / 10000 - w) < 0.03
    db = fresh_db()
    run(base(db))
    import core.warehouse as wh

    async def big(_db, _u, **k):
        return wh.state(0, 10 ** 9)
    monkeypatch.setattr(wh, "user_warehouse", big)

    async def go():
        await db.mg_containers.insert_one({"id": "cw", "name": "w", "rolls": 1, "is_active": True, "rows": [
            {"kind": "resource", "resource": "energy", "min": 2, "max": 5, "weight": 50},
            {"kind": "resource", "resource": "cu", "min": 1, "max": 1, "weight": 30},
            {"kind": "resource", "resource": "scrap", "min": 1, "max": 1, "weight": 0}]})
        seen, amounts = Counter(), set()
        for i in range(300):
            uc = await mr.grant_container(db, "p1", "cw", "admin", str(i), open_now=False)
            for x in (await mr.open_container(db, "p1", uc["id"]))["results"]:
                seen[x["resource"]] += 1
                if x["resource"] == "energy":
                    amounts.add(x["amount"])
        assert seen["scrap"] == 0 and seen["energy"] > 0 and seen["cu"] > 0   # weight 0 never drops
        assert amounts == {2, 3, 4, 5}                                        # min..max inclusive
    run(go())


def test_container_full_warehouse_double_and_foreign(monkeypatch):
    db = fresh_db()
    run(base(db))
    import core.warehouse as wh
    space = {"free": 0}

    async def fake(_db, _u, **k):
        return wh.state(1000 - space["free"], 1000)
    monkeypatch.setattr(wh, "user_warehouse", fake)

    async def go():
        uc = await mr.grant_container(db, "p1", "c_sorter", "admin", "x", open_now=False)
        with pytest.raises(mr.NoSpace) as e:
            await mr.open_container(db, "p1", uc["id"])
        assert e.value.need > 0
        doc = await db.mg_user_containers.find_one({"id": uc["id"]})
        assert doc["status"] == "unopened"                                    # stays closed, not lost
        plan = doc["plan"]
        with pytest.raises(ValueError, match="not_found"):
            await mr.open_container(db, "p2", uc["id"])                        # someone else's
        space["free"] = 1000
        res = await mr.open_container(db, "p1", uc["id"])
        assert [{"resource": x["resource"], "amount": x["amount"]} for x in res["results"]] == \
               [{"resource": p["resource"], "amount": p["amount"]} for p in plan]   # the same roll, no reroll
        with pytest.raises(ValueError, match="already_opened"):
            await mr.open_container(db, "p1", uc["id"])
        u = await db.users.find_one({"id": "p1"})
        assert sum(u["resources"].values()) == sum(p["amount"] for p in plan)
        assert await db.transactions.count_documents({"tx_type": "container_open", "user_id": "p1"}) == 1
    run(go())


def test_container_validation():
    with pytest.raises(ValueError):
        mr.validate_container({"rolls": 1, "rows": [{"kind": "resource", "resource": "energy_tutorial", "min": 1, "max": 2, "weight": 1}]})
    with pytest.raises(ValueError):
        mr.validate_container({"rolls": 6, "rows": [{"kind": "resource", "resource": "energy", "min": 1, "max": 2, "weight": 1}]})
    with pytest.raises(ValueError):
        mr.validate_container({"rolls": 1, "rows": [{"kind": "resource", "resource": "energy", "min": 3, "max": 2, "weight": 1}]})
    with pytest.raises(ValueError):
        mr.validate_container({"rolls": 1, "rows": [{"kind": "resource", "resource": "energy", "min": 1, "max": 2, "weight": 0}]})
    assert mr.validate_container({"rolls": 2, "rows": [{"kind": "resource", "resource": "energy", "min": 1, "max": 2, "weight": 1}]})["rolls"] == 2


# ───────────── boosters ─────────────
def test_boosters_auto_activate_extend_and_expire():
    db = fresh_db()
    run(base(db))

    async def go():
        a = await mr.grant_booster(db, "p1", "b_xp_x2_12", "admin")          # a won booster works at once
        b = await mr.grant_booster(db, "p1", "b_xp_x2_12", "admin")          # the same effect again: extended
        assert a["status"] == "active" and b["status"] == "active"
        t1, t2 = mr._parse(a["expires_at"]), mr._parse(b["expires_at"])
        assert round((t2 - t1).total_seconds() / 3600) == 12                 # extended, not reset
        with pytest.raises(ValueError):
            await mr.activate_booster(db, "p2", a["id"])                     # someone else's
        u = await db.users.find_one({"id": "p1"})
        assert mr.xp_multiplier(u) == 2
        assert mr.xp_multiplier(u, now=t2 + dt.timedelta(minutes=1)) == 1
        assert await mr.expire_boosters(db, now=t2 + dt.timedelta(minutes=1)) == 2
        assert await db.mg_user_boosters.count_documents({"user_id": "p1", "status": "expired"}) == 2
    run(go())


def test_xp_x2_doubles_city_pass_xp(monkeypatch):
    db = fresh_db()
    import city_pass

    async def go():
        now = dt.datetime.now(dt.timezone.utc)
        await db.users.insert_one({"id": "p1", "xp_x2_until": (now + dt.timedelta(hours=1)).isoformat()})
        assert await city_pass._xp_mult(db, "p1") == 2
        await db.users.update_one({"id": "p1"}, {"$set": {"xp_x2_until": (now - dt.timedelta(hours=1)).isoformat()}})
        assert await city_pass._xp_mult(db, "p1") == 1
    run(go())


# ───────────── NFT warehouse ─────────────
async def add_tradable(db, n=2, supply=3):
    await db.mg_nfts.insert_one({"id": "n_tr", "name": "Trade", "kind": "tradable", "supply_total": supply, "granted": 0, "is_active": True})
    for i in range(n):
        await db.mg_nft_items.insert_one({"id": f"it{i}", "nft_id": "n_tr", "kind": "tradable", "nft_address": f"EQ{i}", "status": "free"})


def test_one_nft_never_to_two_players_and_waiting_stock():
    db = fresh_db()
    run(base(db))

    async def go():
        await add_tradable(db, n=2, supply=3)
        gs = await asyncio.gather(*[mr.grant_nft(db, f"p{i}", "n_tr", "admin", f"g{i}") for i in range(1, 5)])
        assert sum(1 for g in gs if g) == 3                                     # supply 3: the 4th gets nothing
        items = await db.mg_nft_items.find({}, {"_id": 0}).to_list(None)
        owners = [i["user_id"] for i in items if i["status"] == "reserved"]
        assert len(owners) == 2 and len(set(owners)) == 2                       # one NFT — one player
        waiting = await db.mg_nft_grants.find({"status": "waiting_stock"}, {"_id": 0}).to_list(None)
        assert len(waiting) == 1                                                # empty warehouse: waits
        await db.mg_nft_items.insert_one({"id": "it9", "nft_id": "n_tr", "kind": "tradable", "nft_address": "EQ9", "status": "free"})
        assert await mr.assign_waiting(db) == 1                                 # pinned after the admin adds one
        assert (await db.mg_nft_items.find_one({"id": "it9"}))["user_id"] == waiting[0]["user_id"]
    run(go())


def test_sbt_supply_is_a_hard_limit():
    db = fresh_db()
    run(base(db))

    async def go():
        await db.mg_nfts.update_one({"id": "n_sorter_master"}, {"$set": {"supply_total": 2}})
        gs = await asyncio.gather(*[mr.grant_nft(db, f"p{i}", "n_sorter_master", "admin", f"s{i}") for i in range(1, 5)])
        assert sum(1 for g in gs if g) == 2
        n = await db.mg_nfts.find_one({"id": "n_sorter_master"})
        assert n["granted"] == 2 and n["next_index"] == 2
        assert sorted(i["index"] for i in await db.mg_nft_items.find({"nft_id": "n_sorter_master"}).to_list(None)) == [0, 1]
    run(go())


class FakeSender:
    def __init__(self, fail=0):
        self.fail, self.sent, self.owners = fail, [], {}

    def raw(self, a):
        return str(a).lower()

    async def transfer_nft(self, net, item, owner):
        if self.fail:
            self.fail -= 1
            raise RuntimeError("network down")
        self.sent.append((item, owner))
        self.owners[item] = owner
        return f"h{len(self.sent)}"

    async def mint_sbt(self, net, coll, index, owner, content):
        self.sent.append((coll, index, owner, content))
        self.owners[f"sbt{index}"] = owner
        return "hs"

    async def item_owner(self, net, item):
        return self.owners.get(item)

    async def sbt_item(self, net, coll, index):
        o = self.owners.get(f"sbt{index}")
        return {"owner_address": o, "address": f"EQsbt{index}"} if o else None


def test_nft_send_wait_wallet_success_retries_and_no_double_send(monkeypatch):
    db = fresh_db()
    run(base(db))
    monkeypatch.setattr(mr, "notify_admin", lambda *a, **k: asyncio.sleep(0))

    async def go():
        await add_tradable(db, n=1, supply=1)
        await db.admin_settings.insert_one({"type": "minigame_nft", "network": "testnet", "sending_enabled": True})
        g = await mr.grant_nft(db, "p1", "n_tr", "admin", "x")
        snd = FakeSender(fail=3)
        await mr.process_nft_queue(db, sender=snd)
        assert (await db.mg_nft_grants.find_one({"id": g["id"]}))["status"] == "reserved"    # no wallet: waits
        await db.users.update_one({"id": "p1"}, {"$set": {"wallet_address": "UQplayer"}})
        for _ in range(3):                                                    # 3 failures, an hour apart
            await mr.process_nft_queue(db, sender=snd)
            await db.mg_nft_grants.update_one({"id": g["id"]}, {"$set": {"next_try_at": "2000-01-01T00:00:00+00:00"}})
        doc = await db.mg_nft_grants.find_one({"id": g["id"]})
        assert doc["status"] == "failed" and doc["attempts"] == 3
        await mr.process_nft_queue(db, sender=snd)
        assert snd.sent == []                                                 # after the 3rd error: the admin decides
        await db.mg_nft_grants.update_one({"id": g["id"]}, {"$set": {"status": "reserved", "attempts": 0}})   # manual retry
        await asyncio.gather(mr.process_nft_queue(db, sender=snd), mr.process_nft_queue(db, sender=snd))
        assert snd.sent == [("EQ0", "UQplayer")]                              # sent once, even with two runs at a time
        await mr.process_nft_queue(db, sender=snd)
        doc = await db.mg_nft_grants.find_one({"id": g["id"]})
        assert doc["status"] == "delivered" and doc["tx_hash"] == "h1"
        assert (await db.mg_nft_items.find_one({"id": "it0"}))["status"] == "delivered"
    run(go())


# ───────────── puzzles ─────────────
async def puzzle_world(db, supply=5):
    await db.mg_nfts.insert_one({"id": "n_pz", "name": "Puzzle NFT", "kind": "sbt", "supply_total": supply, "granted": 0,
                                 "next_index": 0, "is_active": True})
    await db.mg_puzzles.insert_one({"id": "pz", "name": "Город", "nft_id": "n_pz", "is_active": True, "repeatable": False})
    await db.mg_containers.insert_one({"id": "cp", "name": "p", "rolls": 1, "is_active": True,
                                       "rows": [{"kind": "puzzle", "puzzle_id": "pz", "weight": 1}]})


def test_puzzle_only_missing_pieces_assemble_needs_wallet_and_once():
    db = fresh_db()
    run(base(db))

    async def go():
        await puzzle_world(db)
        got = []
        for i in range(12):
            uc = await mr.grant_container(db, "p1", "cp", "admin", str(i), open_now=False)
            res = await mr.open_container(db, "p1", uc["id"])
            got += [x["piece"] for x in res["results"]]
        assert sorted(got) == list(range(1, 10))                              # no duplicates; after 9/9 nothing drops
        up = await db.mg_user_puzzles.find_one({"user_id": "p1"})
        assert up["status"] == "complete"
        r = await mr.assemble_puzzle(db, "p1", "pz")
        assert r == {"ok": False, "need_wallet": True}                        # nothing changed
        assert (await db.mg_user_puzzles.find_one({"user_id": "p1"}))["status"] == "complete"
        assert await db.mg_nft_grants.count_documents({}) == 0
        await db.users.update_one({"id": "p1"}, {"$set": {"wallet_address": "UQ1"}})
        r = await mr.assemble_puzzle(db, "p1", "pz")
        assert r["ok"] and r["grant"]["status"] == "reserved"
        with pytest.raises(ValueError):
            await mr.assemble_puzzle(db, "p1", "pz")                          # one puzzle — once
        uc = await mr.grant_container(db, "p1", "cp", "admin", "again", open_now=False)
        assert (await mr.open_container(db, "p1", uc["id"]))["results"] == []   # no more pieces of an assembled puzzle
    run(go())


def test_puzzle_drops_stop_when_supply_left_equals_started_players():
    db = fresh_db()
    run(base(db))

    async def go():
        await puzzle_world(db, supply=2)
        for u in ("p1", "p2", "p3"):
            uc = await mr.grant_container(db, u, "cp", "admin", u, open_now=False)
            await mr.open_container(db, u, uc["id"])
        started = await db.mg_user_puzzles.distinct("user_id")
        assert sorted(started) == ["p1", "p2"]                                # the 3rd can't start: 2 NFTs, 2 started
        uc = await mr.grant_container(db, "p1", "cp", "admin", "more", open_now=False)
        assert len((await mr.open_container(db, "p1", uc["id"]))["results"]) == 1   # a started player keeps getting pieces
    run(go())


# ───────────── anti-cheat ─────────────
def test_daily_cap_and_flat_reaction(monkeypatch):
    db, c, who = world(monkeypatch)
    c.put("/api/admin/minigames/event", json={"daily_cap": 2})
    r = play(db, c, reaction=300, jitter=False)                               # every tap exactly the same: a bot?
    assert r["points"] > 0                                                    # counted…
    assert run(db.mg_anomalies.count_documents({"reason": "flat_reaction"})) == 1   # …but marked for review
    play(db, c)
    assert c.post("/api/minigames/sorter/start").status_code == 429           # the daily ceiling
    assert run(db.mg_anomalies.count_documents({"reason": "daily_cap"})) == 1


def test_impossible_game_gets_zero_and_is_logged(monkeypatch):
    db, c, who = world(monkeypatch)
    s = c.post("/api/minigames/sorter/start").json()                          # started just now
    r = c.post("/api/minigames/sorter/finish", json={"session_id": s["session_id"], "actions": perfect(s["seed"])}).json()
    assert r["rejected"] and r["points"] == 0 and r["chest"]["given"] is False
    assert run(db.mg_anomalies.count_documents({"reason": "impossible"})) == 1


# ───────────── admin ─────────────
def test_admin_nft_supply_rules_and_prize_validation(monkeypatch, tmp_path):
    db, c, who = world(monkeypatch, tmp_path)
    n = c.post("/api/admin/minigames/nfts", json={"name": "T", "kind": "tradable", "supply_total": 1}).json()
    run(db.mg_nft_items.insert_one({"id": "i1", "nft_id": n["id"], "kind": "tradable", "nft_address": "EQa", "status": "free"}))
    r = run(mrr.create_minigame_rewards_router.__globals__["mr"].grant_nft(db, "p1", n["id"], "admin", "a"))
    assert r["status"] == "reserved"
    bad = c.put(f"/api/admin/minigames/nfts/{n['id']}", json={"name": "T", "kind": "tradable", "supply_total": 0})
    assert bad.status_code == 400
    bad = c.put("/api/admin/minigames/event", json={"leaderboard_prizes": [{"from": 1, "to": 3, "kind": "city", "city": 1},
                                                                           {"from": 3, "to": 5, "kind": "city", "city": 1}]})
    assert bad.status_code == 400                                             # overlapping places
    ok = c.put("/api/admin/minigames/event", json={"chests_per_day": 4, "chest_min_stars": 2, "chest_container_id": "c_sorter"})
    assert ok.status_code == 200
    grant = c.post("/api/admin/minigames/players/p2/grant", json={"kind": "container", "ref_id": "c_sorter"})
    assert grant.status_code == 200 and run(db.mg_user_containers.count_documents({"user_id": "p2"})) == 1
    assert c.post("/api/admin/minigames/players/p2/reset", json={"what": "best"}).status_code == 400   # needs confirmation
