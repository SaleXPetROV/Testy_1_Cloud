"""Mini-game promotion «Сортировщик» (the first mini-game) — campaign, games, leaderboard, campaign end.

  GET  /api/minigames/event                 campaign info, my points / best / place / chests today (auth optional)
  GET  /api/minigames/leaderboard           places by campaign points + prizes of the places + `me` (always)
  POST /api/minigames/sorter/start          a new game: seed + rules (synonym /api/game/start)
  POST /api/minigames/sorter/finish         {session_id, actions:[{i,b,t}]} -> the SERVER replays the score (synonym /api/game/finish)
  GET/PUT /api/admin/minigames/event        settings of the campaign; GET /api/admin/minigames/stats
  GET  /api/admin/minigames/campaign/preview   who gets which prize + linked accounts among the winners
  POST /api/admin/minigames/campaign/finish    give the prizes, close the campaign (synonym /api/admin/campaign/end)
Rewards (thresholds, chests, puzzles, boosters, NFT): minigame_rewards.py / minigame_rewards_routes.py.
"""
import random
import statistics
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

import minigame_rewards as mr
import minigames_sorter as ms

EVENT_ID = "sorter_week_1"
DEFAULTS = {
    "enabled": False, "event_id": EVENT_ID, "game": "sorter", "title": "Неделя Сортировщика",
    "starts_at": "", "ends_at": "",
    "attempts_per_day": 0,                 # 0 = unlimited games (the spec); chests are limited instead
    "daily_cap": 100,                      # anti-cheat ceiling of games per MSK day
    "xp_by_stars": {"1": 10, "2": 20, "3": 35},
    "star_points": [300, 1000, 2000],      # points for ★ / ★★ / ★★★ (endless game: no maximum)
    # a chest for a game: the admin's container, only from chest_min_stars, not more than chests_per_day a day
    "chest_container_id": "c_sorter", "chest_min_stars": 2, "chests_per_day": 4,
    # prizes of the list of leaders (campaign points): kind city | reward | container | booster | nft
    "leaderboard_prizes": [{"from": 1, "to": 1, "kind": "city", "city": 5000},
                           {"from": 2, "to": 3, "kind": "city", "city": 2500},
                           {"from": 4, "to": 10, "kind": "city", "city": 1000}],
    "prizes": [],                          # legacy (city only) — converted to leaderboard_prizes
}
SESSION_TTL_MIN = 10
FLAT_MIN_ITEMS, FLAT_MAX_SPREAD_MS = 50, 20


def _now():
    return datetime.now(timezone.utc)


def _parse(s) -> Optional[datetime]:
    if not s:
        return None
    d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _msk_day() -> str:
    from core.timeutil import msk_today_str
    return msk_today_str()


async def get_config(db) -> Dict[str, Any]:
    doc = await db.admin_settings.find_one({"type": "minigame_event"}, {"_id": 0}) or {}
    cfg = {**DEFAULTS, **{k: v for k, v in doc.items() if k in DEFAULTS}}
    if not doc.get("leaderboard_prizes") and doc.get("prizes"):        # old settings: city prizes
        cfg["leaderboard_prizes"] = [{"from": p["from"], "to": p["to"], "kind": "city", "city": p.get("city", 0)} for p in doc["prizes"]]
    cfg["finalized"] = doc.get("finalized")
    return cfg


def is_active(cfg, now=None) -> bool:
    now = now or _now()
    s, e = _parse(cfg.get("starts_at")), _parse(cfg.get("ends_at"))
    return bool(cfg.get("enabled")) and cfg.get("finalized") != cfg.get("event_id") and \
        (s is None or s <= now) and (e is None or now < e)


async def _games_today(db, uid, cfg) -> int:
    return await db.minigame_sessions.count_documents({"user_id": uid, "event_id": cfg["event_id"], "day": _msk_day()})


def _attempts_left(cfg, used: int) -> Optional[int]:
    lim = int(cfg.get("attempts_per_day") or 0)
    return None if lim <= 0 else max(0, lim - used)


def reaction_times(seed: int, actions) -> list:
    """Reaction time of every counted tap (same timeline as minigames_sorter.score)."""
    items = ms.make_items(seed)
    by = {}
    for a in actions or []:
        try:
            by.setdefault(int(a.get("i")), (int(a.get("b")), float(a.get("t"))))
        except (TypeError, ValueError, AttributeError):
            continue
    at, lives, out = 0.0, ms.LIVES, []
    for it in items:
        if lives <= 0:
            break
        a = by.get(it["i"])
        end = at + it["window"]
        resolved = end
        if a and at + ms.MIN_REACTION_MS <= a[1] <= end:
            resolved = a[1]
            out.append(a[1] - at)
            ok = (a[0] == -1) if it["hazard"] else (a[0] == it["type"])
        else:
            ok = it["hazard"]
        if not ok:
            lives -= 1
        at = resolved + ms.GAP_MS
    return out


async def finish_campaign(db, now=None, force: bool = False) -> Dict[str, Any]:
    """Give the prizes of the list of leaders ONCE, then close the campaign (its points stop counting).
    The best score (all time) is never reset. Called by the admin button or by the end date."""
    cfg = await get_config(db)
    e = _parse(cfg.get("ends_at"))
    if not force and (not e or (now or _now()) < e):
        return {"awarded": 0, "finished": False}
    cid = cfg["event_id"]
    claimed = await db.admin_settings.update_one({"type": "minigame_event", "finalized": {"$ne": cid}},
                                                 {"$set": {"finalized": cid, "enabled": False}})
    if not claimed.modified_count:
        return {"awarded": 0, "finished": False, "reason": "already_finished"}
    prizes = cfg.get("leaderboard_prizes") or []
    last = max([int(p.get("to", 0)) for p in prizes] or [0])
    lb = await mr.leaderboard(db, cid, limit=max(1, last), prizes=prizes)
    given = []
    for row in lb["rows"]:
        p = mr.prize_for(row["place"], prizes)
        if not p:
            continue
        res = await mr.give_prize(db, row["user_id"], p, cid, row["place"])
        given.append({"place": row["place"], "user_id": row["user_id"], "username": row["username"], "points": row["points"], **res})
        try:
            from core.notify import notify_user
            await notify_user(db, row["user_id"], f"🏆 {cfg['title']}: {row['place']} место!",
                              "Приз зачислен — откройте «Награды».", type_key="minigame_prize")
        except Exception:
            pass
    players = await db.minigame_points.count_documents({"campaign_id": cid})
    report = {"campaign_id": cid, "title": cfg["title"], "starts_at": cfg.get("starts_at"), "ends_at": cfg.get("ends_at"),
              "finished_at": _now().isoformat(), "prizes_given": given, "players_with_points": players}
    await db.mg_campaigns.update_one({"id": cid}, {"$set": {"id": cid, **report}}, upsert=True)
    return {"awarded": len(given), "finished": True, "report": report}


async def finalize(db, now=None) -> Dict[str, int]:
    """Scheduled every 10 min: closes the campaign when its end date has passed."""
    r = await finish_campaign(db, now=now)
    return {"awarded": r.get("awarded", 0)}


def create_minigames_router(db, get_current_user, get_current_admin, get_optional_user=None) -> APIRouter:
    r = APIRouter()

    async def _me(request: Request):
        if not get_optional_user:
            return None
        try:
            me = await get_optional_user(request)
        except Exception:
            return None
        return (me.id if hasattr(me, "id") else (me or {}).get("id")) if me else None

    @r.get("/api/minigames/event")
    async def event(request: Request):
        cfg = await get_config(db)
        prizes = await mr.describe_prizes(db, cfg["leaderboard_prizes"])
        out = {"enabled": cfg["enabled"], "active": is_active(cfg), "event_id": cfg["event_id"], "game": cfg["game"],
               "title": cfg["title"], "starts_at": cfg["starts_at"], "ends_at": cfg["ends_at"],
               "attempts_per_day": cfg["attempts_per_day"], "xp_by_stars": cfg["xp_by_stars"], "prizes": prizes,
               "star_points": cfg["star_points"], "lives": ms.LIVES,
               "chest_min_stars": cfg["chest_min_stars"], "chests_per_day": cfg["chests_per_day"],
               "chest_min_points": int(cfg["star_points"][max(0, int(cfg["chest_min_stars"]) - 1)]),
               "top": (await mr.leaderboard(db, cfg["event_id"], limit=20, prizes=cfg["leaderboard_prizes"]))["rows"]}
        uid = await _me(request)
        if uid:
            lb = await mr.leaderboard(db, cfg["event_id"], uid=uid, limit=1, prizes=cfg["leaderboard_prizes"])
            u = await db.users.find_one({"id": uid}, {"_id": 0, "mg_best_score": 1}) or {}
            unopened = await db.mg_user_containers.count_documents({"user_id": uid, "status": "unopened"})
            boosters = await db.mg_user_boosters.count_documents({"user_id": uid, "status": "available"})
            out["me"] = {"attempts_left": _attempts_left(cfg, await _games_today(db, uid, cfg)),
                         "points": lb["me"]["points"], "place": lb["me"]["place"], "best": int(u.get("mg_best_score") or 0),
                         "chests_today": await mr.chests_today(db, uid), "unopened": unopened, "boosters_available": boosters}
        return out

    @r.get("/api/minigames/leaderboard")
    async def leaders(request: Request, limit: int = 100):
        cfg = await get_config(db)
        return await mr.leaderboard(db, cfg["event_id"], uid=await _me(request), limit=max(1, min(500, limit)),
                                    prizes=cfg["leaderboard_prizes"])

    async def _start(current_user):
        cfg = await get_config(db)
        if not is_active(cfg):
            raise HTTPException(status_code=403, detail="event_not_active")
        uid = current_user.id
        used = await _games_today(db, uid, cfg)
        if used >= int(cfg.get("daily_cap") or 100):
            await mr.log_anomaly(db, uid, "daily_cap", details={"games_today": used})
            raise HTTPException(status_code=429, detail="daily_cap")
        left = _attempts_left(cfg, used)
        if left is not None and left <= 0:
            raise HTTPException(status_code=429, detail="no_attempts_left")
        seed = random.SystemRandom().randrange(1, 2 ** 32 - 1)
        sid = str(uuid.uuid4())
        await db.minigame_sessions.insert_one({"id": sid, "user_id": uid, "event_id": cfg["event_id"], "game": "sorter",
                                               "seed": seed, "day": _msk_day(), "status": "active", "started_at": _now().isoformat()})
        return {"session_id": sid, "seed": seed, "rules": {"lives": ms.LIVES, "gap_ms": ms.GAP_MS}}

    @r.post("/api/minigames/sorter/start")
    async def start(current_user=Depends(get_current_user)):
        return await _start(current_user)

    @r.post("/api/game/start")
    async def start_alias(current_user=Depends(get_current_user)):
        return await _start(current_user)

    async def _finish(body: Dict[str, Any], current_user):
        uid = current_user.id
        s = await db.minigame_sessions.find_one({"id": body.get("session_id"), "user_id": uid}, {"_id": 0})
        if not s:
            raise HTTPException(status_code=404, detail="session_not_found")
        # one result per session (atomic), and only within its time limit
        claimed = await db.minigame_sessions.update_one({"id": s["id"], "status": "active"}, {"$set": {"status": "finishing"}})
        if not claimed.modified_count:
            raise HTTPException(status_code=409, detail="session_already_finished")
        started = _parse(s["started_at"])
        actions = body.get("actions") if isinstance(body.get("actions"), list) else []
        actions = actions[: ms.MAX_ITEMS * 2]
        res = ms.score(int(s["seed"]), actions)
        elapsed_ms = (_now() - started).total_seconds() * 1000
        items_played = res["last_item"] + 1
        reason = None
        if elapsed_ms > SESSION_TTL_MIN * 60 * 1000:
            reason = "too_late"                                   # the session lives 10 minutes
        elif res["duration_ms"] > elapsed_ms + 2000 and len(actions) > 0:
            reason = "impossible"                                 # longer than the real time since start (+2 s network)
        elif len(actions) > 0 and elapsed_ms + 2000 < items_played * (ms.MIN_REACTION_MS + ms.GAP_MS):
            reason = "too_fast"                                   # shorter than the pauses between its items
        cfg = await get_config(db)
        points = 0 if reason else res["points"]
        if reason:
            await mr.log_anomaly(db, uid, reason, s["id"], {"replay_ms": res["duration_ms"], "elapsed_ms": round(elapsed_ms),
                                                            "claimed_points": res["points"]})
        rts = reaction_times(int(s["seed"]), actions) if not reason else []
        if len(rts) >= FLAT_MIN_ITEMS and statistics.pstdev(rts) < FLAT_MAX_SPREAD_MS:
            await mr.log_anomaly(db, uid, "flat_reaction", s["id"], {"stdev_ms": round(statistics.pstdev(rts), 1), "taps": len(rts)})
        st = ms.stars(points, tuple(cfg.get("star_points") or (300, 1000, 2000)))
        xp = int((cfg.get("xp_by_stars") or {}).get(str(st), 0)) if st else 0
        if xp:
            try:
                import city_pass
                xp = await city_pass.add_xp(db, uid, "quest", xp)        # ×2 XP booster is applied inside
            except Exception:
                xp = 0
        await db.minigame_sessions.update_one({"id": s["id"]}, {"$set": {
            "status": "done", "points": points, "stars": st, "xp": xp, "cleared": res["cleared"], "best_combo": res["best_combo"],
            "rejected": bool(reason), "reject_reason": reason, "finished_at": _now().isoformat(),
            "actions": actions, "replay_ms": res["duration_ms"], "elapsed_ms": round(elapsed_ms)}})   # kept for audits / disputes
        # best of THIS campaign (legacy board) + all-time best + campaign points
        prev = await db.minigame_scores.find_one({"event_id": s["event_id"], "user_id": uid}, {"_id": 0, "best": 1})
        if points > int((prev or {}).get("best", 0)):
            await db.minigame_scores.update_one({"event_id": s["event_id"], "user_id": uid},
                                                {"$set": {"event_id": s["event_id"], "user_id": uid, "best": points, "stars": st,
                                                          "best_at": _now().isoformat()}}, upsert=True)
        best, new_best = await mr.update_best(db, uid, points)
        active = is_active(cfg) and s["event_id"] == cfg["event_id"]
        cpoints = await mr.add_points(db, uid, cfg["event_id"], points if active else 0)
        # the player left in the middle of the game (the app sent the finish while closing): what was won is
        # opened anyway and they get a notification in Telegram too; otherwise the app shows the opening itself
        notify = "full" if body.get("background") else "app"
        new = await mr.check_thresholds(db, uid, cfg["event_id"] if active else "", cpoints, best, notify=notify)
        chest = await mr.game_chest(db, uid, s["id"], st, cfg, notify=notify) if (active and not reason) else \
            {"given": False, "reason": "rejected" if reason else "inactive", "chests_today": await mr.chests_today(db, uid),
             "chests_per_day": int(cfg.get("chests_per_day") or 0)}
        return {"points": points, "stars": st, "xp": xp, "cleared": res["cleared"], "best_combo": res["best_combo"],
                "new_best": new_best, "best_score": best, "campaign_points": cpoints,
                "rejected": bool(reason), "reject_reason": reason, "chest": chest,
                "chests_today": chest.get("chests_today"), "chests_per_day": chest.get("chests_per_day"),
                "new_rewards": [{"id": n["reward"]["id"], "type": n["reward"]["type"], "name": n["reward"]["name"],
                                 "name_i18n": n["reward"].get("name_i18n")} for n in new],
                "new_containers": [n["user_container_id"] for n in new if n.get("user_container_id")],
                # chests already opened (the game chest + chests of reward thresholds): the app plays the opening
                "opened_chests": ([chest["chest"]] if chest.get("chest") else []) + [n["chest"] for n in new if n.get("chest")],
                "new_boosters": [n["user_booster_id"] for n in new if n.get("user_booster_id")],
                "attempts_left": _attempts_left(cfg, await _games_today(db, uid, cfg))}

    @r.post("/api/minigames/sorter/finish")
    async def finish(body: Dict[str, Any], current_user=Depends(get_current_user)):
        return await _finish(body, current_user)

    @r.post("/api/game/finish")
    async def finish_alias(body: Dict[str, Any], current_user=Depends(get_current_user)):
        return await _finish(body, current_user)

    # ───────────── admin ─────────────
    @r.get("/api/admin/minigames/event")
    async def a_get(_=Depends(get_current_admin)):
        return await get_config(db)

    @r.put("/api/admin/minigames/event")
    async def a_put(body: Dict[str, Any], _=Depends(get_current_admin)):
        upd = {k: v for k, v in body.items() if k in DEFAULTS}
        if "star_points" in upd:
            sp = sorted(max(0, int(float(x))) for x in list(upd["star_points"])[:3])
            if len(sp) != 3:
                raise HTTPException(status_code=400, detail="star_points: три числа")
            upd["star_points"] = sp
        if "attempts_per_day" in upd:
            upd["attempts_per_day"] = max(0, min(50, int(upd["attempts_per_day"] or 0)))
        if "daily_cap" in upd:
            upd["daily_cap"] = max(1, min(1000, int(upd["daily_cap"] or 100)))
        if "chest_min_stars" in upd:
            upd["chest_min_stars"] = max(1, min(3, int(upd["chest_min_stars"] or 2)))
        if "chests_per_day" in upd:
            upd["chests_per_day"] = max(0, min(50, int(upd["chests_per_day"] or 0)))
        if "chest_container_id" in upd and upd["chest_container_id"]:
            if not await db.mg_containers.find_one({"id": upd["chest_container_id"]}):
                raise HTTPException(status_code=400, detail="Такого сундука нет")
        if "xp_by_stars" in upd:
            upd["xp_by_stars"] = {str(k): max(0, int(v)) for k, v in dict(upd["xp_by_stars"]).items() if str(k) in ("1", "2", "3")}
        if "leaderboard_prizes" in upd:
            pr = []
            for p in upd["leaderboard_prizes"] or []:
                a, b = int(p.get("from", 0)), int(p.get("to", 0))
                kind = p.get("kind") or "city"
                if not (1 <= a <= b <= 1000) or kind not in ("city", "reward", "container", "booster", "nft"):
                    raise HTTPException(status_code=400, detail=f"Призы: неверный диапазон {a}–{b} или тип {kind}")
                item = {"from": a, "to": b, "kind": kind}
                if kind == "city":
                    item["city"] = max(0.0, float(p.get("city") or 0))
                else:
                    coll = {"reward": "mg_rewards", "container": "mg_containers", "booster": "mg_boosters", "nft": "mg_nfts"}[kind]
                    if not await db[coll].find_one({"id": p.get("ref_id")}):
                        raise HTTPException(status_code=400, detail=f"Призы {a}–{b}: не выбран объект")
                    item["ref_id"] = p["ref_id"]
                pr.append(item)
            pr.sort(key=lambda x: x["from"])
            for x, y in zip(pr, pr[1:]):
                if y["from"] <= x["to"]:
                    raise HTTPException(status_code=400, detail=f"Призы: места {x['from']}–{x['to']} и {y['from']}–{y['to']} пересекаются")
            upd["leaderboard_prizes"] = pr
            upd["prizes"] = []
        for k in ("starts_at", "ends_at"):
            if k in upd and upd[k]:
                try:
                    upd[k] = _parse(upd[k]).isoformat()
                except Exception:
                    raise HTTPException(status_code=400, detail=f"{k}: неверная дата")
        if "event_id" in upd and upd["event_id"] != (await get_config(db))["event_id"]:
            upd["finalized"] = None                       # a NEW campaign: points from zero, prizes can be given again
        await db.admin_settings.update_one({"type": "minigame_event"}, {"$set": {"type": "minigame_event", **upd}}, upsert=True)
        return await get_config(db)

    @r.get("/api/admin/minigames/campaign/preview")
    async def a_preview(_=Depends(get_current_admin)):
        cfg = await get_config(db)
        prizes = cfg.get("leaderboard_prizes") or []
        last = max([int(p.get("to", 0)) for p in prizes] or [0])
        lb = await mr.leaderboard(db, cfg["event_id"], limit=max(1, last), prizes=prizes)
        winners = [row for row in lb["rows"] if row["prize"]]
        return {"campaign_id": cfg["event_id"], "winners": winners,
                "linked": await mr.linked_winners(db, [w["user_id"] for w in winners]),
                "players_with_points": await db.minigame_points.count_documents({"campaign_id": cfg["event_id"]}),
                "finished": cfg.get("finalized") == cfg["event_id"]}

    async def _a_finish():
        r_ = await finish_campaign(db, force=True)
        if not r_.get("finished"):
            raise HTTPException(status_code=409, detail="Акция уже завершена")
        return r_

    @r.post("/api/admin/minigames/campaign/finish")
    async def a_finish(_=Depends(get_current_admin)):
        return await _a_finish()

    @r.post("/api/admin/campaign/end")
    async def a_finish_alias(_=Depends(get_current_admin)):
        return await _a_finish()

    @r.get("/api/admin/minigames/stats")
    async def a_stats(_=Depends(get_current_admin)):
        cfg = await get_config(db)
        q = {"event_id": cfg["event_id"], "status": "done"}
        plays = await db.minigame_sessions.count_documents(q)
        players = len(await db.minigame_sessions.distinct("user_id", q))
        rejected = await db.minigame_sessions.count_documents({**q, "rejected": True})
        st = {str(k): await db.minigame_sessions.count_documents({**q, "stars": k}) for k in (0, 1, 2, 3)}
        best_game = await db.minigame_sessions.find({"status": "done", "rejected": {"$ne": True}}, {"_id": 0, "user_id": 1, "points": 1, "finished_at": 1}) \
            .sort("points", -1).limit(1).to_list(1)
        if best_game:
            u = await db.users.find_one({"id": best_game[0]["user_id"]}, {"_id": 0, "username": 1}) or {}
            best_game[0]["username"] = u.get("username")
        top_best = await db.users.find({"mg_best_score": {"$gt": 0}}, {"_id": 0, "id": 1, "username": 1, "mg_best_score": 1}) \
            .sort("mg_best_score", -1).limit(10).to_list(10)
        lb = await mr.leaderboard(db, cfg["event_id"], limit=50, prizes=cfg["leaderboard_prizes"])
        return {"plays": plays, "players": players, "rejected": rejected, "stars": st,
                "best_game": best_game[0] if best_game else None, "top_best": top_best, "top": lb["rows"]}

    return r
