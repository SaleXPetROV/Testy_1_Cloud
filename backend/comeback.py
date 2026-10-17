"""GRAM City — comeback bonus + streak shields.

Comeback bonus
--------------
A player who was away for a while gets a one-time "welcome back" gift when they
return, instead of coming back to an empty, decayed warehouse and leaving again.

    away >= 3 days   -> small gift : bonus $CITY + warehouse decay protection 24 h
    away >= 14 days  -> big gift   : more $CITY + protection 48 h + 1 streak shield

"Away" is measured from `user_active_days` (analytics.py): the last active day
BEFORE today. It is granted once per return (remembered as the day the absence
started), so it cannot be farmed by logging in twice.

Streak shields
--------------
A shield keeps the daily-login streak alive over one missed day (max 2 stored).
Players earn one by finishing all weekly quests (see quests.claim) or with the
big comeback gift. routes/tasks.py consumes them in /daily/claim.

All amounts are admin-configurable (db.tasks_config key "comeback").
Rewards go to the NON-withdrawable bonus balance, like quest rewards.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))
CITY_PER_TON = 1000.0
MAX_SHIELDS = 2

DEFAULTS = {
    "small_after_days": 3,
    "small_city": 30,
    "small_protect_hours": 24,
    "big_after_days": 14,
    "big_city": 100,
    "big_protect_hours": 48,
    "big_shields": 1,
}

_DB = None


def init(db) -> None:
    global _DB
    _DB = db


def _today_msk():
    return datetime.now(timezone.utc).astimezone(MSK).date()


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def config() -> Dict[str, Any]:
    doc = await _DB.tasks_config.find_one({"key": "comeback"}, {"_id": 0}) or {}
    return {k: type(v)(doc.get(k, v)) for k, v in DEFAULTS.items()}


# ───────────────────────────── shields ─────────────────────────────
async def add_shields(user_id: str, n: int = 1) -> int:
    """Give up to `n` shields (capped at MAX_SHIELDS). Returns the new count."""
    if n <= 0:
        return await shields(user_id)
    await _DB.users.update_one({"id": user_id, "streak_shields": None}, {"$set": {"streak_shields": 0}})
    u = await _DB.users.find_one({"id": user_id}, {"_id": 0, "streak_shields": 1}) or {}
    cur = int(u.get("streak_shields") or 0)
    new = min(MAX_SHIELDS, cur + n)
    if new != cur:
        # conditional on the value we read, so two parallel grants cannot exceed the cap
        await _DB.users.update_one({"id": user_id, "streak_shields": cur}, {"$set": {"streak_shields": new}})
    return new


async def shields(user_id: str) -> int:
    u = await _DB.users.find_one({"id": user_id}, {"_id": 0, "streak_shields": 1}) or {}
    return int(u.get("streak_shields") or 0)


# ───────────────────────────── comeback ─────────────────────────────
async def _previous_active_day(user_id: str) -> Optional[str]:
    """Last active MSK day strictly before today (None if never active before)."""
    today = _today_msk().isoformat()
    rows = await _DB.user_active_days.find(
        {"user_id": user_id, "day": {"$lt": today}}, {"_id": 0, "day": 1}
    ).sort("day", -1).limit(1).to_list(1)
    return rows[0]["day"] if rows else None


async def status(user_id: str) -> Dict[str, Any]:
    cfg = await config()
    prev = await _previous_active_day(user_id)
    if not prev:
        return {"available": False, "reason": "no_history"}
    away = (_today_msk() - datetime.fromisoformat(prev).date()).days
    u = await _DB.users.find_one({"id": user_id}, {"_id": 0, "comeback_claimed_for": 1}) or {}
    if u.get("comeback_claimed_for") == prev:
        return {"available": False, "reason": "already_claimed", "away_days": away}
    if away >= cfg["big_after_days"]:
        tier = "big"
    elif away >= cfg["small_after_days"]:
        tier = "small"
    else:
        return {"available": False, "reason": "not_away_long_enough", "away_days": away}
    return {
        "available": True, "tier": tier, "away_days": away, "since": prev,
        "reward": {
            "city": cfg[f"{tier}_city"],
            "protect_hours": cfg[f"{tier}_protect_hours"],
            "shields": cfg["big_shields"] if tier == "big" else 0,
        },
    }


async def claim(user_id: str) -> Dict[str, Any]:
    st = await status(user_id)
    if not st.get("available"):
        raise HTTPException(status_code=400, detail="No comeback bonus available")
    prev = st["since"]
    r = st["reward"]
    protect_until = (datetime.now(timezone.utc) + timedelta(hours=int(r["protect_hours"]))).isoformat()
    # Atomic once-per-return guard: only one request can mark this absence as claimed.
    res = await _DB.users.update_one(
        {"id": user_id, "comeback_claimed_for": {"$ne": prev}},
        {"$set": {"comeback_claimed_for": prev, "comeback_claimed_at": _iso_now(),
                  "decay_protected_until": protect_until}},
    )
    if res.modified_count == 0:
        raise HTTPException(status_code=409, detail="Comeback bonus already claimed")
    city = int(r["city"] or 0)
    if city > 0:
        await _DB.users.update_one({"id": user_id, "bonus_balance": None}, {"$set": {"bonus_balance": 0.0}})
        await _DB.users.update_one({"id": user_id}, {"$inc": {"bonus_balance": city / CITY_PER_TON}})
        try:
            await _DB.transactions.insert_one({
                "id": str(uuid.uuid4()), "tx_type": "comeback_bonus", "type": "comeback_bonus",
                "user_id": user_id, "amount": city / CITY_PER_TON, "amount_ton": city / CITY_PER_TON,
                "reward_city": city, "status": "completed",
                "description": f"Comeback bonus after {st['away_days']} days: +{city} $CITY (bonus)",
                "created_at": _iso_now(), "completed_at": _iso_now(),
            })
        except Exception as e:
            logger.warning(f"comeback tx log failed: {e}")
    new_shields = await add_shields(user_id, int(r.get("shields") or 0)) if r.get("shields") else await shields(user_id)
    try:
        import analytics
        await analytics.track(user_id, "comeback_claimed", tier=st["tier"], away_days=st["away_days"])
    except Exception:
        pass
    return {"ok": True, "tier": st["tier"], "away_days": st["away_days"],
            "granted": {"city": city, "protect_until": protect_until, "shields": new_shields}}


def decay_protected(user_doc: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    """True while the player's warehouse is protected from the midnight decay."""
    until = user_doc.get("decay_protected_until")
    if not until:
        return False
    try:
        dt = datetime.fromisoformat(str(until).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return dt > (now or datetime.now(timezone.utc))


def create_comeback_router(db, get_current_user, get_current_admin) -> APIRouter:
    init(db)
    root = APIRouter()
    router = APIRouter(prefix="/api/comeback", tags=["comeback"])
    admin = APIRouter(prefix="/api/admin/comeback", tags=["comeback-admin"])

    async def _uid(current_user) -> str:
        keys = [k for k in (getattr(current_user, "id", None),) if k]
        if not keys:
            raise HTTPException(status_code=401, detail="Unauthorized")
        return keys[0]

    @router.get("")
    async def get_status(current_user=Depends(get_current_user)):
        uid = await _uid(current_user)
        out = await status(uid)
        out["shields"] = await shields(uid)
        return out

    @router.post("/claim")
    async def post_claim(current_user=Depends(get_current_user)):
        return await claim(await _uid(current_user))

    @admin.get("/config")
    async def get_config(_=Depends(get_current_admin)):
        return await config()

    @admin.get("/stats")
    async def get_stats(days: int = 30, _=Depends(get_current_admin)):
        """Who came back and what they received (from the comeback_bonus ledger)."""
        if days < 1 or days > 365:
            raise HTTPException(status_code=400, detail="days must be 1..365")
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        txs = await db.transactions.find({"tx_type": "comeback_bonus", "created_at": {"$gte": since}},
                                         {"_id": 0, "user_id": 1, "reward_city": 1, "created_at": 1}).to_list(100000)
        evs = await db.analytics_events.find({"event": "comeback_claimed", "ts": {"$gte": since}},
                                             {"_id": 0, "props": 1}).to_list(100000)
        tiers = {"small": 0, "big": 0}
        away = []
        for e in evs:
            p = e.get("props") or {}
            if p.get("tier") in tiers:
                tiers[p["tier"]] += 1
            if isinstance(p.get("away_days"), (int, float)):
                away.append(p["away_days"])
        by_day: Dict[str, int] = {}
        for t in txs:
            d = str(t.get("created_at", ""))[:10]
            by_day[d] = by_day.get(d, 0) + 1
        return {
            "period_days": days,
            "claims": len(txs),
            "players": len({t["user_id"] for t in txs}),
            "city_paid": round(sum(float(t.get("reward_city", 0) or 0) for t in txs), 2),
            "by_tier": tiers,
            "avg_away_days": round(sum(away) / len(away), 1) if away else None,
            "protected_now": await db.users.count_documents({"decay_protected_until": {"$gt": datetime.now(timezone.utc).isoformat()}}),
            "players_with_shields": await db.users.count_documents({"streak_shields": {"$gte": 1}}),
            "by_day": [{"date": d, "claims": n} for d, n in sorted(by_day.items())],
            "config": await config(),
        }

    @admin.put("/config")
    async def put_config(patch: Dict[str, int], _=Depends(get_current_admin)):
        upd = {}
        for k, v in (patch or {}).items():
            if k not in DEFAULTS:
                raise HTTPException(status_code=400, detail=f"Unknown key {k}")
            if not isinstance(v, int) or v < 0:
                raise HTTPException(status_code=400, detail=f"Invalid {k}")
            upd[k] = v
        merged = {**(await config()), **upd}
        if merged["small_after_days"] < 1 or merged["big_after_days"] <= merged["small_after_days"]:
            raise HTTPException(status_code=400, detail="Нужно: 1 ≤ «малый» срок < «большой» срок")
        await db.tasks_config.update_one({"key": "comeback"}, {"$set": {"key": "comeback", **upd}}, upsert=True)
        return {"ok": True, "config": await config()}

    root.include_router(router)
    root.include_router(admin)
    return root
