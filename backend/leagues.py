"""GRAM City — weekly leagues (shown on the «Общение» page).

Competition by ACTIVITY and TRADE, not by wealth, inside small groups of equals
so a newcomer can actually win.

Structure
    5 divisions: Бронза → Серебро → Золото → Платина → Алмаз (0..4).
    Week = Monday 00:00 – Sunday 23:59 (Moscow time).
    Groups of `group_size` players of one division, rebuilt every week. Accounts
    sharing a device are never put in the same group.

Three ratings in every group (each can be switched off by the admin)
    points     — activity points (daily/weekly goals, shifts, repairs, sales,
                 streak days) with per-action and per-day caps;
    units_sold — units of resources sold to OTHER players this week;
    ton_sold   — TON earned from those sales this week.
    Sales to the City Market and between linked accounts never count.

End of week
    Rewards per rating and place (bonus $CITY, non-withdrawable), streak shields
    for the top N of the points rating, promotion / relegation by the rating the
    admin picks (default: points). Results are notified to every member.

Everything in DEFAULT_CONFIG is editable in the admin (Лиги tab).
"""
from __future__ import annotations

import logging
import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))
DIVISIONS = ["bronze", "silver", "gold", "platinum", "diamond"]
DIVISION_NAMES_RU = ["Бронза", "Серебро", "Золото", "Платина", "Алмаз"]
BOARDS = ["points", "units_sold", "ton_sold"]

DEFAULT_CONFIG: Dict[str, Any] = {
    "enabled": True,
    "group_size": 30,
    "promote_count": 5,
    "relegate_count": 5,
    "promotion_board": "points",
    "daily_points_cap": 150,
    "points": {                      # points per action
        "daily_goal": 10, "weekly_goal": 30, "shift_start": 2, "repair": 3,
        "sale_per_0_01_ton": 1, "streak_day": 5,
    },
    "caps": {                        # max actions counted per day (sale: max points per day)
        "daily_goal": 3, "weekly_goal": 3, "shift_start": 6, "repair": 3, "sale": 50, "streak_day": 1,
    },
    "boards": {
        "points":     {"enabled": True, "rewards_city": [300, 150, 150]},
        "units_sold": {"enabled": True, "rewards_city": [200, 100, 100]},
        "ton_sold":   {"enabled": True, "rewards_city": [200, 100, 100]},
    },
    "shield_top_n": 10,              # streak shield for the top N of the points rating
}

_DB = None


def init(db) -> None:
    global _DB
    _DB = db


def _now() -> datetime:
    return datetime.now(timezone.utc)


def week_key(dt: Optional[datetime] = None) -> str:
    d = (dt or _now()).astimezone(MSK)
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def week_bounds(key: str) -> tuple:
    year, w = key.split("-W")
    monday = datetime.fromisocalendar(int(year), int(w), 1).replace(tzinfo=MSK)
    return monday.astimezone(timezone.utc), (monday + timedelta(days=7)).astimezone(timezone.utc)


def _day() -> str:
    return _now().astimezone(MSK).date().isoformat()


# ───────────────────────────── config ─────────────────────────────
def _merge(base: Dict, over: Dict) -> Dict:
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            out[k] = _merge(base[k], v)
        else:
            out[k] = v
    return out


async def get_config(db=None) -> Dict[str, Any]:
    db = db if db is not None else _DB

    async def load():
        doc = await db.admin_settings.find_one({"type": "leagues"}, {"_id": 0}) or {}
        doc.pop("type", None)
        return _merge(DEFAULT_CONFIG, doc)
    from core.ttl_cache import cached
    import copy
    return copy.deepcopy(await cached(f"cfg:leagues:{id(db)}", 30, load, owner=db))


async def save_config(db, patch: Dict[str, Any]) -> Dict[str, Any]:
    cur = await get_config(db)
    new = _merge(cur, patch or {})
    # validation
    for k in ("group_size", "promote_count", "relegate_count", "daily_points_cap", "shield_top_n"):
        try:
            new[k] = int(new[k])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"{k} must be an integer")
        if new[k] < 0:
            raise HTTPException(status_code=400, detail=f"{k} must be >= 0")
    if new["group_size"] < 2:
        raise HTTPException(status_code=400, detail="group_size must be >= 2")
    if new["promote_count"] + new["relegate_count"] > new["group_size"]:
        raise HTTPException(status_code=400, detail="promote_count + relegate_count must not exceed group_size")
    if new["promotion_board"] not in BOARDS:
        raise HTTPException(status_code=400, detail=f"promotion_board must be one of {BOARDS}")
    for sect in ("points", "caps"):
        for k, v in list(new[sect].items()):
            if k not in DEFAULT_CONFIG[sect]:
                raise HTTPException(status_code=400, detail=f"unknown {sect}.{k}")
            try:
                new[sect][k] = max(0, int(v))
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=f"{sect}.{k} must be an integer")
    for b in BOARDS:
        bd = new["boards"].get(b) or {}
        rewards = bd.get("rewards_city", [])
        if isinstance(rewards, str):
            rewards = [x for x in rewards.replace(";", ",").split(",") if x.strip()]
        try:
            rewards = [max(0, int(float(x))) for x in rewards][:50]
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"boards.{b}.rewards_city must be numbers")
        new["boards"][b] = {"enabled": bool(bd.get("enabled", True)), "rewards_city": rewards}
    for k in list(new["boards"]):
        if k not in BOARDS:
            new["boards"].pop(k)
    if not new["boards"][new["promotion_board"]]["enabled"]:
        raise HTTPException(status_code=400, detail="the promotion rating must be enabled")
    new["enabled"] = bool(new.get("enabled", True))
    await db.admin_settings.update_one({"type": "leagues"}, {"$set": {"type": "leagues", **new}}, upsert=True)
    from core.ttl_cache import invalidate
    invalidate("cfg:leagues")
    return await get_config(db)


# ───────────────────────────── membership ─────────────────────────────
_indexes_ready = False


async def _ensure_indexes(db) -> None:
    global _indexes_ready
    if _indexes_ready:
        return
    _indexes_ready = True
    try:
        await db.league_members.create_index([("user_id", 1), ("week", 1)], unique=True)
        await db.league_members.create_index([("group_id", 1), ("week", 1)])
        await db.league_groups.create_index([("week", 1), ("division", 1), ("finalized", 1)])
        await db.league_history.create_index([("user_id", 1), ("week", -1)])
    except Exception as e:
        logger.warning(f"leagues: index creation failed: {e}")


async def _device_mates(db, uid: str) -> set:
    visitors = await db.fingerprints.distinct("visitor_id", {"user_id": uid, "visitor_id": {"$ne": None}})
    if not visitors:
        return set()
    return set(await db.fingerprints.distinct("user_id", {"visitor_id": {"$in": visitors}})) - {uid}


async def ensure_member(db, uid: str, cfg: Optional[Dict] = None) -> Optional[Dict[str, Any]]:
    """The player's row for the current week; joins a group on first activity."""
    cfg = cfg or await get_config(db)
    await _ensure_indexes(db)
    wk = week_key()
    m = await db.league_members.find_one({"user_id": uid, "week": wk}, {"_id": 0})
    if m:
        return m
    u = await db.users.find_one({"id": uid}, {"_id": 0, "id": 1, "league_division": 1, "username": 1})
    if not u:
        return None
    div = int(u.get("league_division", 0) or 0)
    mates = await _device_mates(db, uid)
    group = None
    async for g in db.league_groups.find({"week": wk, "division": div, "finalized": {"$ne": True},
                                          "size": {"$lt": int(cfg["group_size"])}}, {"_id": 0}).sort("created_at", 1):
        if not mates or not (set(g.get("members", [])) & mates):
            group = g
            break
    if not group:
        group = {"id": str(uuid.uuid4()), "week": wk, "division": div, "members": [], "size": 0,
                 "created_at": _now().isoformat()}
        await db.league_groups.insert_one(dict(group))
    res = await db.league_groups.update_one({"id": group["id"], "size": {"$lt": int(cfg["group_size"])}},
                                            {"$addToSet": {"members": uid}, "$inc": {"size": 1}})
    if res.modified_count == 0:            # filled meanwhile — try again with a fresh group
        group = {"id": str(uuid.uuid4()), "week": wk, "division": div, "members": [uid], "size": 1,
                 "created_at": _now().isoformat()}
        await db.league_groups.insert_one(dict(group))
    m = {"user_id": uid, "week": wk, "division": div, "group_id": group["id"],
         "points": 0, "units_sold": 0, "ton_sold": 0.0, "daily": {}, "joined_at": _now().isoformat()}
    try:
        await db.league_members.insert_one(dict(m))
    except Exception:
        m = await db.league_members.find_one({"user_id": uid, "week": wk}, {"_id": 0}) or m
    return m


# ───────────────────────────── scoring ─────────────────────────────
async def add_activity(db, uid: str, action: str, count: int = 1) -> int:
    """Activity points for daily_goal / weekly_goal / shift_start / repair / streak_day."""
    if not uid or count <= 0:
        return 0
    cfg = await get_config(db)
    if not cfg["enabled"] or action not in cfg["points"] or action == "sale_per_0_01_ton":
        return 0
    m = await ensure_member(db, uid, cfg)
    if not m:
        return 0
    day = _day()
    d = (m.get("daily") or {}).get(day, {})
    cap = int(cfg["caps"].get(action, 0))
    allowed = max(0, min(count, cap - int(d.get(action, 0))))
    pts = allowed * int(cfg["points"][action])
    pts = max(0, min(pts, int(cfg["daily_points_cap"]) - int(d.get("points", 0))))
    if allowed <= 0:
        return 0
    await db.league_members.update_one({"user_id": uid, "week": m["week"]},
                                       {"$inc": {"points": pts, f"daily.{day}.{action}": allowed,
                                                 f"daily.{day}.points": pts}})
    return pts


async def add_sale(db, uid: str, units: int, ton: float) -> int:
    """A sale to ANOTHER player (callers exclude the City Market and linked accounts)."""
    if not uid or (units <= 0 and ton <= 0):
        return 0
    cfg = await get_config(db)
    if not cfg["enabled"]:
        return 0
    m = await ensure_member(db, uid, cfg)
    if not m:
        return 0
    day = _day()
    d = (m.get("daily") or {}).get(day, {})
    raw = int(math.floor(float(ton) / 0.01 + 1e-9)) * int(cfg["points"]["sale_per_0_01_ton"])
    pts = max(0, min(raw, int(cfg["caps"]["sale"]) - int(d.get("sale_points", 0))))
    pts = max(0, min(pts, int(cfg["daily_points_cap"]) - int(d.get("points", 0))))
    await db.league_members.update_one({"user_id": uid, "week": m["week"]},
                                       {"$inc": {"units_sold": int(units), "ton_sold": round(float(ton), 6),
                                                 "points": pts, f"daily.{day}.sale_points": pts,
                                                 f"daily.{day}.points": pts}})
    return pts


def _spawn(coro) -> None:
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(coro)
    task.add_done_callback(lambda t: t.exception() and logger.debug(f"league hook failed: {t.exception()}"))


def activity_bg(uid: str, action: str, count: int = 1) -> None:
    if _DB is not None:
        _spawn(add_activity(_DB, uid, action, count))


def sale_bg(uid: str, units: int, ton: float) -> None:
    if _DB is not None:
        _spawn(add_sale(_DB, uid, units, ton))


# ───────────────────────────── standings ─────────────────────────────
def _rank(members: List[Dict], board: str) -> List[Dict]:
    return sorted(members, key=lambda m: (-float(m.get(board, 0) or 0), m.get("joined_at", "")))


async def group_view(db, uid: str) -> Dict[str, Any]:
    cfg = await get_config(db)
    wk = week_key()
    start, end = week_bounds(wk)
    me = await db.league_members.find_one({"user_id": uid, "week": wk}, {"_id": 0})
    u = await db.users.find_one({"id": uid}, {"_id": 0, "league_division": 1})
    div = int((me or {}).get("division", (u or {}).get("league_division", 0)) or 0)
    out: Dict[str, Any] = {
        "enabled": cfg["enabled"], "week": wk, "ends_at": end.isoformat(),
        "division": div, "division_key": DIVISIONS[div],
        "joined": bool(me), "group_size": cfg["group_size"],
        "promote_count": cfg["promote_count"], "relegate_count": cfg["relegate_count"],
        "promotion_board": cfg["promotion_board"],
        "boards": {b: cfg["boards"][b] for b in BOARDS if cfg["boards"][b]["enabled"]},
        "points_table": cfg["points"], "caps": cfg["caps"], "daily_points_cap": cfg["daily_points_cap"],
        "shield_top_n": cfg["shield_top_n"], "standings": {}, "me": None,
    }
    if me:
        members = await db.league_members.find({"group_id": me["group_id"], "week": wk}, {"_id": 0, "daily": 0}).to_list(500)
        ids = [m["user_id"] for m in members]
        names = {x["id"]: (x.get("username") or "player") async for x in
                 db.users.find({"id": {"$in": ids}}, {"_id": 0, "id": 1, "username": 1})}
        for b in out["boards"]:
            ranked = _rank(members, b)
            out["standings"][b] = [{"rank": i + 1, "user_id": m["user_id"], "name": names.get(m["user_id"], "player"),
                                    "value": round(float(m.get(b, 0) or 0), 4), "me": m["user_id"] == uid}
                                   for i, m in enumerate(ranked)]
        out["me"] = {"points": me.get("points", 0), "units_sold": me.get("units_sold", 0),
                     "ton_sold": round(float(me.get("ton_sold", 0) or 0), 4),
                     "ranks": {b: next(r["rank"] for r in out["standings"][b] if r["me"]) for b in out["standings"]}}
    hist = await db.league_history.find({"user_id": uid}, {"_id": 0}).sort("week", -1).limit(6).to_list(6)
    out["history"] = hist
    return out


# ───────────────────────────── end of week ─────────────────────────────
async def _notify_result(db, uid: str, title: str, message: str) -> None:
    try:
        from core.notify import notify_user_background
        notify_user_background(db, uid, title=title, message=message, type_key="league_result", priority="info")
    except Exception as e:
        logger.debug(f"league notify failed: {e}")


async def finalize_week(db, wk: str) -> Dict[str, Any]:
    """Rewards, shields, promotion / relegation for every group of week `wk`."""
    cfg = await get_config(db)
    from routes.tasks import credit_task_reward_bonus
    stats = {"groups": 0, "members": 0, "rewards_city": 0, "promoted": 0, "relegated": 0}
    async for g in db.league_groups.find({"week": wk, "finalized": {"$ne": True}}, {"_id": 0}):
        # claim the group so two workers never pay twice
        res = await db.league_groups.update_one({"id": g["id"], "finalized": {"$ne": True}},
                                                {"$set": {"finalized": True, "finalized_at": _now().isoformat()}})
        if res.modified_count == 0:
            continue
        members = await db.league_members.find({"group_id": g["id"], "week": wk}, {"_id": 0}).to_list(500)
        if not members:
            continue
        stats["groups"] += 1
        stats["members"] += len(members)
        ranks: Dict[str, Dict[str, int]] = {m["user_id"]: {} for m in members}
        paid: Dict[str, int] = {m["user_id"]: 0 for m in members}
        for b in BOARDS:
            if not cfg["boards"][b]["enabled"]:
                continue
            ranked = _rank(members, b)
            rewards = cfg["boards"][b]["rewards_city"]
            for i, m in enumerate(ranked):
                ranks[m["user_id"]][b] = i + 1
                # a reward needs a real result on that rating (no prizes for 0)
                if i < len(rewards) and rewards[i] > 0 and float(m.get(b, 0) or 0) > 0:
                    await credit_task_reward_bonus(db, m["user_id"], rewards[i],
                                                   f"League {wk}: place {i + 1} ({b})", tx_type="league_reward")
                    paid[m["user_id"]] += rewards[i]
                    stats["rewards_city"] += rewards[i]
        # streak shields for the top N of the points rating
        if cfg["shield_top_n"] > 0 and cfg["boards"]["points"]["enabled"]:
            try:
                import comeback
                comeback.init(db) if comeback._DB is None else None
                for m in _rank(members, "points")[:cfg["shield_top_n"]]:
                    if float(m.get("points", 0) or 0) > 0:
                        await comeback.add_shields(m["user_id"], 1)
            except Exception as e:
                logger.warning(f"league shields failed: {e}")
        # promotion / relegation
        pb = cfg["promotion_board"]
        ranked = _rank(members, pb)
        n = len(ranked)
        for i, m in enumerate(ranked):
            div = int(m.get("division", 0) or 0)
            move = "stay"
            active = float(m.get(pb, 0) or 0) > 0
            if i < cfg["promote_count"] and active and div < len(DIVISIONS) - 1:
                div += 1
                move = "up"
                stats["promoted"] += 1
            elif i >= n - cfg["relegate_count"] and n > cfg["promote_count"] and div > 0:
                div -= 1
                move = "down"
                stats["relegated"] += 1
            await db.users.update_one({"id": m["user_id"]}, {"$set": {"league_division": div}})
            if i < 5 and active:
                try:
                    import city_pass
                    await city_pass.add_xp(db, m["user_id"], "league_top", 1)
                except Exception:
                    pass
            await db.league_history.insert_one({
                "user_id": m["user_id"], "week": wk, "group_id": g["id"], "division": int(m.get("division", 0) or 0),
                "new_division": div, "move": move, "ranks": ranks[m["user_id"]], "reward_city": paid[m["user_id"]],
                "points": m.get("points", 0), "units_sold": m.get("units_sold", 0),
                "ton_sold": round(float(m.get("ton_sold", 0) or 0), 4), "at": _now().isoformat(),
            })
            r = ranks[m["user_id"]]
            parts = [f"очки — {r['points']}-е" if "points" in r else None,
                     f"продано ед. — {r['units_sold']}-е" if "units_sold" in r else None,
                     f"сумма продаж — {r['ton_sold']}-е" if "ton_sold" in r else None]
            mv = {"up": f"Вы поднялись в {DIVISION_NAMES_RU[div]}!", "down": f"Вы опустились в {DIVISION_NAMES_RU[div]}.",
                  "stay": f"Вы остаётесь в дивизионе {DIVISION_NAMES_RU[div]}."}[move]
            await _notify_result(db, m["user_id"], "🏆 Итоги недели в лиге",
                                 f"Места: {', '.join(p for p in parts if p)}. {mv}"
                                 + (f" Награда: +{paid[m['user_id']]} $CITY на бонусный баланс." if paid[m["user_id"]] else ""))
    if stats["groups"]:
        logger.info(f"🏆 league week {wk} finalized: {stats}")
    return stats


async def finalize_due(db) -> Dict[str, Any]:
    """Finalize every past week that still has open groups (scheduled job)."""
    cur = week_key()
    out = {}
    for wk in await db.league_groups.distinct("week", {"finalized": {"$ne": True}}):
        if wk < cur:
            out[wk] = await finalize_week(db, wk)
    return out


# ───────────────────────────── analytics ─────────────────────────────
async def analytics(db) -> Dict[str, Any]:
    wk = week_key()
    members = await db.league_members.find({"week": wk}, {"_id": 0, "daily": 0}).to_list(100000)
    by_div = [0] * len(DIVISIONS)
    for m in members:
        by_div[int(m.get("division", 0) or 0)] += 1
    n = len(members)
    # 7-day retention: players active last week — members vs non-members, active again this week
    start, end = week_bounds(wk)
    prev_start = start - timedelta(days=7)
    prev_wk = week_key(prev_start + timedelta(hours=12))

    def days(a, b):
        out, d = [], a.astimezone(MSK).date()
        while d < b.astimezone(MSK).date():
            out.append(d.isoformat())
            d += timedelta(days=1)
        return out
    prev_active = set(await db.user_active_days.distinct("user_id", {"day": {"$in": days(prev_start, start)}}))
    now_active = set(await db.user_active_days.distinct("user_id", {"day": {"$in": days(start, end)}}))
    prev_members = set(await db.league_members.distinct("user_id", {"week": prev_wk}))
    pm, pn = prev_active & prev_members, prev_active - prev_members
    rt = lambda s: round(100.0 * len(s & now_active) / len(s), 1) if s else None  # noqa: E731
    rewards = await db.transactions.find({"tx_type": "league_reward"}, {"_id": 0, "reward_city": 1}).to_list(100000)
    return {
        "week": wk, "ends_at": end.isoformat(), "participants": n,
        "by_division": [{"division": DIVISION_NAMES_RU[i], "players": c} for i, c in enumerate(by_div)],
        "groups": await db.league_groups.count_documents({"week": wk}),
        "avg_points": round(sum(m.get("points", 0) for m in members) / n, 1) if n else 0,
        "units_sold": sum(int(m.get("units_sold", 0) or 0) for m in members),
        "ton_sold": round(sum(float(m.get("ton_sold", 0) or 0) for m in members), 4),
        "retention_prev_week": {"members_pct": rt(pm), "members": len(pm), "non_members_pct": rt(pn), "non_members": len(pn)},
        "rewards_city_total": round(sum(float(r.get("reward_city", 0) or 0) for r in rewards), 2),
        "config": await get_config(db),
    }


# ───────────────────────────── API ─────────────────────────────
def create_leagues_router(db, get_current_user, get_current_admin) -> APIRouter:
    init(db)
    root = APIRouter()
    r = APIRouter(prefix="/api/leagues", tags=["leagues"])
    a = APIRouter(prefix="/api/admin/leagues", tags=["leagues-admin"])

    @r.get("/me")
    async def me(current_user=Depends(get_current_user)):
        return await group_view(db, current_user.id)

    @r.post("/join")
    async def join(current_user=Depends(get_current_user)):
        cfg = await get_config(db)
        if not cfg["enabled"]:
            raise HTTPException(status_code=400, detail="Leagues are disabled")
        await ensure_member(db, current_user.id, cfg)
        return await group_view(db, current_user.id)

    @a.get("/config")
    async def a_get(_=Depends(get_current_admin)):
        return await get_config(db)

    @a.put("/config")
    async def a_put(patch: Dict[str, Any], _=Depends(get_current_admin)):
        return await save_config(db, patch)

    @a.get("/analytics")
    async def a_analytics(_=Depends(get_current_admin)):
        return await analytics(db)

    @a.post("/finalize")
    async def a_finalize(week: Optional[str] = None, _=Depends(get_current_admin)):
        """Finalize past weeks now (or one given week)."""
        return await finalize_week(db, week) if week else await finalize_due(db)

    root.include_router(r)
    root.include_router(a)
    return root
