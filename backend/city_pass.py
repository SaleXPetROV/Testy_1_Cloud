"""GRAM City — City Pass (seasonal pass).

Season: `days` long, `levels` levels. Reaching the LAST level takes 80 % of all
XP a player can possibly earn in the season (xp_ratio × days × daily_xp_cap,
default 0.8 × 30 × 200 = 4800 XP). Levels are split into three equal TIERS
(1–10, 11–20, 21–30) whose levels cost more and more XP, by the admin's tier
weights (default 1.3 / 1.6 / 1.9 → 130 / 160 / 190 XP per level). The total
stays exactly at 80 %, only its distribution changes.

XP comes from the same game events as quests and leagues (daily / weekly
goals, shifts, repairs, sales to other players, login streak, league top 5),
each with its own cap, plus a total daily cap. Sales to the City Market and
between linked accounts never count.

Rewards are ITEMS (boosters.py) — no bonus balance: tier-3 items like the
tutorial reward (unsellable, activated as a buff), auto-shift, warehouse
guard, repair-all, streak shields.
    free track     — a reward on EVERY level (level 30: auto-shift for 3 days)
    premium track  — EXTRA rewards on levels 1, 5, 10, 15, 20, 25, 30
A reward is taken only by pressing «Забрать» once the level is reached
(premium: also needs the paid pass). Every claim is atomic. After the season
ends, rewards can still be claimed for `claim_grace_days`.

Premium is paid from the REAL balance (price in TON, admin setting).
"""
from __future__ import annotations

import logging
import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

import boosters

logger = logging.getLogger(__name__)
MSK = timezone(timedelta(hours=3))

PREMIUM_LEVELS = [1, 5, 10, 15, 20, 25, 30]


def _r(t, **kw):
    return {"type": t, **kw}


def _default_free() -> Dict[str, List[Dict]]:
    t3 = ["neuro_core", "war_protocol", "gold_bill", "bio_module", "luck_chip"]
    cycle = [lambda h: _r("warehouse_guard", hours=h), lambda h: _r("repair_all"),
             lambda h: _r("auto_shift", hours=h), lambda h: _r("streak_shield")]
    out: Dict[str, List[Dict]] = {}
    for lvl in range(1, 31):
        if lvl == 30:
            out["30"] = [_r("auto_shift", hours=72)]                    # the end reward: 3 days of auto-shift
        elif lvl % 5 == 0:
            out[str(lvl)] = [_r("t3", resource=t3[(lvl // 5 - 1) % len(t3)])]
        else:
            hours = 12 if lvl < 6 else 24 if lvl < 21 else 48
            out[str(lvl)] = [cycle[(lvl - 1) % 4 if lvl % 5 else 0](hours)]
    return out


def _default_premium() -> Dict[str, List[Dict]]:
    return {
        "1":  [_r("auto_shift", hours=24), _r("warehouse_guard", hours=24)],
        "5":  [_r("t3", resource="neuro_core"), _r("repair_all")],
        "10": [_r("t3", resource="license_token"), _r("auto_shift", hours=48)],
        "15": [_r("t3", resource="war_protocol", count=2)],
        "20": [_r("auto_shift", hours=72), _r("warehouse_guard", hours=72)],
        "25": [_r("t3", resource="gateway_code", count=2), _r("repair_all")],
        "30": [_r("t3", resource="neuro_core", count=3), _r("auto_shift", hours=168)],
    }


DEFAULT_CONFIG: Dict[str, Any] = {
    "enabled": True,
    "season_id": "S1",
    "season_name": "Сезон 1: Энергия острова",
    "starts_at": None,              # ISO; None = first time the pass is opened
    "days": 30,
    "levels": 30,
    "daily_xp_cap": 200,
    "xp_ratio": 0.8,                # the last level needs 80 % of the season's maximum XP
    "tier_weights": [1.3, 1.6, 1.9],  # XP cost of levels in tiers 1-10 / 11-20 / 21-30 (-> 130 / 160 / 190)
    "claim_grace_days": 3,
    "premium_price_ton": None,       # set by the admin; premium is not sold until a price is set
    "xp": {"daily_goal": 30, "weekly_goal": 100, "shift_start": 10, "repair": 10,
           "sale_per_0_01_ton": 1, "streak_day": 20, "league_top": 100},
    "caps": {"daily_goal": 3, "weekly_goal": 3, "shift_start": 3, "repair": 2,
             "sale": 40, "streak_day": 1, "league_top": 1},
    "rewards_free": _default_free(),
    "rewards_premium": _default_premium(),
}

_DB = None


def init(db) -> None:
    global _DB
    _DB = db


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _day() -> str:
    return _now().astimezone(MSK).date().isoformat()


def season_xp_total(cfg: Dict[str, Any]) -> int:
    """XP needed for the LAST level = xp_ratio × the season maximum."""
    return int(round(float(cfg["xp_ratio"]) * int(cfg["days"]) * int(cfg["daily_xp_cap"])))


def level_costs(cfg: Dict[str, Any]) -> List[int]:
    """XP cost of each level (index 0 = level 1). Three equal tiers weighted by
    cfg["tier_weights"]; rounding is absorbed by the last level so the sum is
    exactly season_xp_total()."""
    n = int(cfg["levels"])
    w = [max(0.01, float(x)) for x in (list(cfg.get("tier_weights") or [1, 1, 1]) + [1, 1, 1])[:3]]
    tier_of = [min(2, (i * 3) // n) for i in range(n)]
    total = season_xp_total(cfg)
    unit = total / sum(w[t] for t in tier_of)
    costs = [max(1, int(round(unit * w[t]))) for t in tier_of]
    costs[-1] = max(1, costs[-1] + (total - sum(costs)))
    return costs


def thresholds(cfg: Dict[str, Any]) -> List[int]:
    """Cumulative XP needed to REACH each level (index 0 = level 1)."""
    out, acc = [], 0
    for c in level_costs(cfg):
        acc += c
        out.append(acc)
    return out


def xp_per_level(cfg: Dict[str, Any]) -> int:
    """Average XP per level (kept for display / backwards compatibility)."""
    return max(1, math.ceil(season_xp_total(cfg) / int(cfg["levels"])))


async def get_config(db) -> Dict[str, Any]:
    from core.ttl_cache import cached
    import copy
    return copy.deepcopy(await cached(f"cfg:city_pass:{id(db)}", 30, lambda: _load_config(db), owner=db))


async def _load_config(db) -> Dict[str, Any]:
    doc = await db.admin_settings.find_one({"type": "city_pass"}, {"_id": 0}) or {}
    cfg = {**DEFAULT_CONFIG, **{k: v for k, v in doc.items() if k in DEFAULT_CONFIG}}
    for k in ("xp", "caps"):
        cfg[k] = {**DEFAULT_CONFIG[k], **(doc.get(k) or {})}
    if not cfg["starts_at"]:
        cfg["starts_at"] = _now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        await db.admin_settings.update_one({"type": "city_pass"},
                                           {"$set": {"type": "city_pass", "starts_at": cfg["starts_at"]}}, upsert=True)
    return cfg


def season_bounds(cfg: Dict[str, Any]):
    start = datetime.fromisoformat(str(cfg["starts_at"]).replace("Z", "+00:00"))
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    end = start + timedelta(days=int(cfg["days"]))
    return start, end, end + timedelta(days=int(cfg["claim_grace_days"]))


async def save_config(db, patch: Dict[str, Any]) -> Dict[str, Any]:
    cur = await get_config(db)
    upd: Dict[str, Any] = {}
    for k, v in (patch or {}).items():
        if k not in DEFAULT_CONFIG:
            raise HTTPException(status_code=400, detail=f"unknown setting {k}")
        if k in ("days", "levels", "daily_xp_cap", "claim_grace_days"):
            v = int(v)
            if v < 1:
                raise HTTPException(status_code=400, detail=f"{k} must be >= 1")
        elif k == "xp_ratio":
            v = float(v)
            if not 0.1 <= v <= 1.0:
                raise HTTPException(status_code=400, detail="xp_ratio must be 0.1..1.0")
        elif k == "premium_price_ton":
            if v in (None, ""):
                v = None
            else:
                v = float(v)
                if v <= 0:
                    raise HTTPException(status_code=400, detail="Цена премиума должна быть больше 0 TON")
        elif k == "tier_weights":
            if not isinstance(v, list) or len(v) != 3:
                raise HTTPException(status_code=400, detail="tier_weights: три числа для уровней 1–10, 11–20, 21–30")
            v = [float(x) for x in v]
            if any(x <= 0 for x in v):
                raise HTTPException(status_code=400, detail="tier weights must be > 0")
        elif k in ("xp", "caps"):
            v = {kk: max(0, int(vv)) for kk, vv in {**cur[k], **(v or {})}.items() if kk in DEFAULT_CONFIG[k]}
        elif k in ("rewards_free", "rewards_premium"):
            if not isinstance(v, dict):
                raise HTTPException(status_code=400, detail=f"{k} must be an object level -> rewards")
            v = {str(int(lvl)): [boosters.validate_reward(x) for x in (lst or [])] for lvl, lst in v.items()}
        elif k == "enabled":
            v = bool(v)
        upd[k] = v
    await db.admin_settings.update_one({"type": "city_pass"}, {"$set": {"type": "city_pass", **upd}}, upsert=True)
    from core.ttl_cache import invalidate
    invalidate("cfg:city_pass")
    return await get_config(db)


# ───────────────────────────── progress ─────────────────────────────
_idx = False


async def _progress(db, uid: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    global _idx
    if not _idx:
        _idx = True
        try:
            await db.city_pass_progress.create_index([("user_id", 1), ("season_id", 1)], unique=True)
        except Exception as e:
            logger.warning(f"city pass index: {e}")
    sid = cfg["season_id"]
    p = await db.city_pass_progress.find_one({"user_id": uid, "season_id": sid}, {"_id": 0})
    if p:
        return p
    p = {"user_id": uid, "season_id": sid, "xp": 0, "premium": False, "claimed_free": [], "claimed_premium": [],
         "daily": {}, "created_at": _now().isoformat()}
    try:
        await db.city_pass_progress.insert_one(dict(p))
    except Exception:
        p = await db.city_pass_progress.find_one({"user_id": uid, "season_id": sid}, {"_id": 0}) or p
    return p


def _level(cfg, xp: int) -> int:
    import bisect
    return bisect.bisect_right(thresholds(cfg), int(xp))


async def _xp_mult(db, uid: str) -> int:
    try:
        u = await db.users.find_one({"id": uid}, {"_id": 0, "xp_x2_until": 1}) or {}
        from minigame_rewards import xp_multiplier
        return xp_multiplier(u)
    except Exception:
        return 1


async def add_xp(db, uid: str, action: str, count: int = 1, ton: float = 0.0) -> int:
    if not uid:
        return 0
    cfg = await get_config(db)
    start, end, _ = season_bounds(cfg)
    now = _now()
    if not cfg["enabled"] or not (start <= now < end):
        return 0
    p = await _progress(db, uid, cfg)
    day = _day()
    d = (p.get("daily") or {}).get(day, {})
    if action in ("onboarding", "quest"):
        # the XP written on a quest card (newbie / daily / weekly), once per claim (the claim is atomic)
        xp = max(0, int(count)) * await _xp_mult(db, uid)
        if xp <= 0:
            return 0
        before = _level(cfg, p.get("xp", 0))
        await db.city_pass_progress.update_one({"user_id": uid, "season_id": cfg["season_id"]},
                                               {"$inc": {"xp": xp, f"daily.{day}.xp": xp, f"daily.{day}.{action}": xp}})
        after = _level(cfg, int(p.get("xp", 0)) + xp)
        if after > before:
            try:
                from core.notify import notify_user_background
                notify_user_background(db, uid, title=f"🎫 City Pass: уровень {after}!",
                                       message="Новая награда ждёт — откройте City Pass и заберите её.",
                                       type_key="city_pass_level", priority="info", telegram=False)
            except Exception:
                pass
        return xp
    if action == "sale":
        raw = int(math.floor(float(ton) / 0.01 + 1e-9)) * int(cfg["xp"]["sale_per_0_01_ton"])
        xp = max(0, min(raw, int(cfg["caps"]["sale"]) - int(d.get("sale_xp", 0))))
        counter = {f"daily.{day}.sale_xp": xp}
    else:
        if action not in cfg["xp"]:
            return 0
        allowed = max(0, min(int(count), int(cfg["caps"].get(action, 0)) - int(d.get(action, 0))))
        xp = allowed * int(cfg["xp"][action])
        counter = {f"daily.{day}.{action}": allowed}
    # no limit per day: `daily_xp_cap` only sizes the levels (season XP total), it never cuts XP
    if xp <= 0:
        return 0
    xp *= await _xp_mult(db, uid)                   # «×2 XP» booster of the mini-game rewards
    before = _level(cfg, p.get("xp", 0))
    await db.city_pass_progress.update_one({"user_id": uid, "season_id": cfg["season_id"]},
                                           {"$inc": {"xp": xp, f"daily.{day}.xp": xp, **counter}})
    after = _level(cfg, int(p.get("xp", 0)) + xp)
    if after > before:
        try:
            from core.notify import notify_user_background
            notify_user_background(db, uid, title=f"🎫 City Pass: уровень {after}!",
                                   message="Новая награда ждёт — откройте City Pass и заберите её.",
                                   type_key="city_pass_level", priority="info", telegram=False)
        except Exception:
            pass
    return xp


def _spawn(coro):
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    t = loop.create_task(coro)
    t.add_done_callback(lambda x: x.exception() and logger.debug(f"city pass hook: {x.exception()}"))


def xp_bg(uid: str, action: str, count: int = 1) -> None:
    if _DB is not None:
        _spawn(add_xp(_DB, uid, action, count))


def sale_bg(uid: str, ton: float) -> None:
    if _DB is not None:
        _spawn(add_xp(_DB, uid, "sale", 1, ton))


# ───────────────────────────── claim / premium ─────────────────────────────
async def claim(db, uid: str, level: int, track: str) -> Dict[str, Any]:
    if track not in ("free", "premium"):
        raise HTTPException(status_code=400, detail="track must be free or premium")
    cfg = await get_config(db)
    start, end, claim_until = season_bounds(cfg)
    if _now() > claim_until:
        raise HTTPException(status_code=400, detail="Сезон закончился, награды больше нельзя забрать")
    rewards = (cfg["rewards_free"] if track == "free" else cfg["rewards_premium"]).get(str(level)) or []
    if not rewards:
        raise HTTPException(status_code=400, detail="На этом уровне нет награды")
    p = await _progress(db, uid, cfg)
    if _level(cfg, p.get("xp", 0)) < level:
        raise HTTPException(status_code=400, detail="Уровень ещё не пройден")
    field = "claimed_free" if track == "free" else "claimed_premium"
    flt = {"user_id": uid, "season_id": cfg["season_id"], field: {"$ne": level}}
    if track == "premium":
        flt["premium"] = True
    res = await db.city_pass_progress.update_one(flt, {"$addToSet": {field: level}})
    if res.modified_count == 0:
        if track == "premium" and not p.get("premium"):
            raise HTTPException(status_code=403, detail="Нужен премиум City Pass")
        raise HTTPException(status_code=409, detail="Награда уже получена")
    granted = [await boosters.grant(db, uid, r) for r in rewards]
    await db.city_pass_claims.insert_one({"user_id": uid, "season_id": cfg["season_id"], "level": level,
                                          "track": track, "rewards": granted, "at": _now().isoformat()})
    return {"ok": True, "level": level, "track": track, "granted": granted}


async def claim_all(db, uid: str) -> Dict[str, Any]:
    cfg = await get_config(db)
    p = await _progress(db, uid, cfg)
    lvl = _level(cfg, p.get("xp", 0))
    got = []
    for track, table, done in (("free", cfg["rewards_free"], p.get("claimed_free", [])),
                               ("premium", cfg["rewards_premium"], p.get("claimed_premium", []))):
        if track == "premium" and not p.get("premium"):
            continue
        for level in range(1, lvl + 1):
            if level in done or not table.get(str(level)):
                continue
            try:
                got.append(await claim(db, uid, level, track))
            except HTTPException:
                pass
    return {"ok": True, "claimed": len(got)}


async def buy_premium(db, uid: str) -> Dict[str, Any]:
    """Paid from the REAL balance only (bonus balance does not count)."""
    cfg = await get_config(db)
    start, end, _ = season_bounds(cfg)
    if _now() >= end:
        raise HTTPException(status_code=400, detail="Сезон уже закончился")
    if not cfg.get("premium_price_ton"):
        raise HTTPException(status_code=400, detail="Премиум пока недоступен")
    price = round(float(cfg["premium_price_ton"]), 6)
    await _progress(db, uid, cfg)
    lock = await db.city_pass_progress.update_one(
        {"user_id": uid, "season_id": cfg["season_id"], "premium": {"$ne": True}},
        {"$set": {"premium": True, "premium_at": _now().isoformat()}})
    if lock.modified_count == 0:
        raise HTTPException(status_code=409, detail="Премиум уже куплен")
    if True:
        paid = await db.users.update_one({"id": uid, "balance_ton": {"$gte": price}}, {"$inc": {"balance_ton": -price}})
        if paid.modified_count == 0:
            await db.city_pass_progress.update_one({"user_id": uid, "season_id": cfg["season_id"]},
                                                   {"$set": {"premium": False}, "$unset": {"premium_at": ""}})
            raise HTTPException(status_code=400, detail=f"Недостаточно средств на реальном балансе: нужно {round(price * 1000, 2):g} $CITY")
    await db.transactions.insert_one({
        "id": str(uuid.uuid4()), "tx_type": "city_pass_premium", "type": "city_pass_premium", "user_id": uid,
        "amount": price, "amount_ton": price, "season_id": cfg["season_id"], "status": "completed",
        "description": f"City Pass premium ({cfg['season_id']})", "created_at": _now().isoformat()})
    p_after = await _progress(db, uid, cfg)
    lvl = _level(cfg, p_after.get("xp", 0))
    unlocked = [int(k) for k, v in cfg["rewards_premium"].items()
                if v and int(k) <= lvl and int(k) not in (p_after.get("claimed_premium") or [])]
    return {"ok": True, "price_ton": price, "price_city": round(price * 1000, 2),
            "unlocked_levels": sorted(unlocked)}


# ───────────────────────────── views ─────────────────────────────
async def view(db, uid: str) -> Dict[str, Any]:
    cfg = await get_config(db)
    start, end, claim_until = season_bounds(cfg)
    p = await _progress(db, uid, cfg)
    th = thresholds(cfg)
    costs = level_costs(cfg)
    xp = int(p.get("xp", 0))
    lvl = _level(cfg, xp)
    prev_th = th[lvl - 1] if lvl > 0 else 0
    cur_cost = costs[lvl] if lvl < len(costs) else costs[-1]
    rows = []
    for level in range(1, int(cfg["levels"]) + 1):
        def state(track, done):
            rw = (cfg["rewards_free"] if track == "free" else cfg["rewards_premium"]).get(str(level)) or []
            if not rw:
                return None
            if level in done:
                st = "claimed"
            elif level > lvl:
                st = "locked"
            elif track == "premium" and not p.get("premium"):
                st = "need_premium"
            else:
                st = "claimable"
            return {"rewards": rw, "state": st}
        rows.append({"level": level, "xp_cost": costs[level - 1], "free": state("free", p.get("claimed_free", [])),
                     "premium": state("premium", p.get("claimed_premium", []))})
    claimable = sum(1 for r in rows for t in ("free", "premium") if r[t] and r[t]["state"] == "claimable")
    return {
        "enabled": cfg["enabled"], "season_id": cfg["season_id"], "season_name": cfg["season_name"],
        "starts_at": start.isoformat(), "ends_at": end.isoformat(), "claim_until": claim_until.isoformat(),
        "active": start <= _now() < end, "levels": int(cfg["levels"]),
        # xp_per_level = cost of the CURRENT level (it grows with the tiers)
        "xp_per_level": cur_cost, "level_costs": costs, "season_xp_total": th[-1],
        "xp": xp, "level": lvl, "xp_in_level": (xp - prev_th) if lvl < int(cfg["levels"]) else cur_cost,
        "max_season_xp": int(cfg["days"]) * int(cfg["daily_xp_cap"]),
        "daily_xp_cap": int(cfg["daily_xp_cap"]), "xp_table": cfg["xp"], "caps": cfg["caps"],
        "today_xp": int(((p.get("daily") or {}).get(_day()) or {}).get("xp", 0)),
        "premium": bool(p.get("premium")),
        "premium_price_ton": float(cfg["premium_price_ton"]) if cfg.get("premium_price_ton") else None,
        "premium_price_city": round(float(cfg["premium_price_ton"]) * 1000, 2) if cfg.get("premium_price_ton") else None,
        "rows": rows, "claimable": claimable,
    }


async def analytics(db) -> Dict[str, Any]:
    cfg = await get_config(db)
    sid = cfg["season_id"]
    rows = await db.city_pass_progress.find({"season_id": sid}, {"_id": 0, "xp": 1, "premium": 1, "user_id": 1}).to_list(200000)
    levels = [0] * (int(cfg["levels"]) + 1)
    for r in rows:
        levels[_level(cfg, int(r.get("xp", 0)))] += 1
    prem = [r for r in rows if r.get("premium")]
    revenue = 0.0
    async for t in db.transactions.find({"tx_type": "city_pass_premium", "season_id": sid}, {"_id": 0, "amount_ton": 1}):
        revenue += float(t.get("amount_ton", 0) or 0)
    claims = await db.city_pass_claims.count_documents({"season_id": sid})
    start, end, claim_until = season_bounds(cfg)
    # 7-day retention: pass players vs others among users active in the first week of the season
    def days(a, n):
        return [(a + timedelta(days=i)).astimezone(MSK).date().isoformat() for i in range(n)]
    wk1 = set(await db.user_active_days.distinct("user_id", {"day": {"$in": days(start, 7)}}))
    wk2 = set(await db.user_active_days.distinct("user_id", {"day": {"$in": days(start + timedelta(days=7), 7)}}))
    players = {r["user_id"] for r in rows if int(r.get("xp", 0)) > 0}
    a, b = wk1 & players, wk1 - players
    pct = lambda s: round(100.0 * len(s & wk2) / len(s), 1) if s else None  # noqa: E731
    return {
        "season_id": sid, "season_name": cfg["season_name"], "starts_at": start.isoformat(), "ends_at": end.isoformat(),
        "xp_per_level": xp_per_level(cfg), "level_costs": level_costs(cfg), "season_xp_total": season_xp_total(cfg),
        "max_season_xp": int(cfg["days"]) * int(cfg["daily_xp_cap"]),
        "players": len(players), "premium": len(prem), "revenue_ton": round(revenue, 4),
        "claims": claims, "by_level": [{"level": i, "players": c} for i, c in enumerate(levels)],
        "retention_week2": {"pass_pct": pct(a), "pass_n": len(a), "others_pct": pct(b), "others_n": len(b)},
        "config": cfg,
    }


def create_city_pass_router(db, get_current_user, get_current_admin) -> APIRouter:
    init(db)
    root = APIRouter()
    r = APIRouter(prefix="/api/pass", tags=["city-pass"])
    a = APIRouter(prefix="/api/admin/pass", tags=["city-pass-admin"])

    @r.get("/me")
    async def me(current_user=Depends(get_current_user)):
        return await view(db, current_user.id)

    @r.post("/claim")
    async def post_claim(body: Dict[str, Any], current_user=Depends(get_current_user)):
        return await claim(db, current_user.id, int(body.get("level", 0)), str(body.get("track", "free")))

    @r.post("/claim-all")
    async def post_claim_all(current_user=Depends(get_current_user)):
        return await claim_all(db, current_user.id)

    @r.post("/premium")
    async def post_premium(current_user=Depends(get_current_user)):
        return await buy_premium(db, current_user.id)

    @a.get("/analytics")
    async def a_analytics(_=Depends(get_current_admin)):
        return await analytics(db)

    @a.put("/config")
    async def a_config(patch: Dict[str, Any], _=Depends(get_current_admin)):
        return await save_config(db, patch)

    @a.post("/new-season")
    async def a_new_season(body: Dict[str, Any], _=Depends(get_current_admin)):
        sid = str(body.get("season_id") or "").strip()
        if not sid:
            raise HTTPException(status_code=400, detail="season_id required")
        patch = {"season_id": sid, "starts_at": body.get("starts_at") or _now().isoformat()}
        if body.get("season_name"):
            patch["season_name"] = str(body["season_name"])
        await db.admin_settings.update_one({"type": "city_pass"}, {"$set": {"type": "city_pass", **patch}}, upsert=True)
        from core.ttl_cache import invalidate
        invalidate("cfg:city_pass")
        return await get_config(db)

    root.include_router(r)
    root.include_router(a)
    return root
