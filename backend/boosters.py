"""GRAM City — boosters («Усилители»): non-tradable items and their effects.

Rewards of the City Pass (and future systems) are ITEMS, in the style of the
tutorial tier-3 reward: they cannot be sold or transferred, take no warehouse
space and are activated by the player on the Resources page → «Усилители».

Item keys (users.boosters.<key> = count)
    auto_shift_<H>h       — shifts of all the player's businesses restart by
                            themselves for H hours (users.auto_shift_until)
    warehouse_guard_<H>h  — no midnight warehouse decay for H hours
                            (users.decay_protected_until, same as comeback)
    repair_all            — every business of the player back to 100 %
Granted directly (no item):
    streak_shield         — +1 streak shield (max 2, comeback.add_shields)
    t3:<resource>         — +1 `<resource>_tutorial`: the unsellable tier-3
                            item, activated as a buff via /api/resource-buffs

A reward is a dict: {"type": "auto_shift", "hours": 24, "count": 1},
{"type": "warehouse_guard", "hours": 24}, {"type": "repair_all"},
{"type": "streak_shield"}, {"type": "t3", "resource": "neuro_core"}.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

logger = logging.getLogger(__name__)

REWARD_TYPES = ("auto_shift", "warehouse_guard", "repair_all", "streak_shield", "t3")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts: Any) -> Optional[datetime]:
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def item_key(reward: Dict[str, Any]) -> Optional[str]:
    t = reward.get("type")
    if t == "auto_shift":
        return f"auto_shift_{int(reward.get('hours', 24))}h"
    if t == "warehouse_guard":
        return f"warehouse_guard_{int(reward.get('hours', 24))}h"
    if t == "repair_all":
        return "repair_all"
    return None


def validate_reward(r: Dict[str, Any]) -> Dict[str, Any]:
    from business_config import RESOURCE_TYPES
    t = r.get("type")
    if t not in REWARD_TYPES:
        raise HTTPException(status_code=400, detail=f"unknown reward type {t}")
    out: Dict[str, Any] = {"type": t, "count": max(1, int(r.get("count", 1) or 1))}
    if t in ("auto_shift", "warehouse_guard"):
        h = int(r.get("hours", 24) or 24)
        if h < 1 or h > 24 * 30:
            raise HTTPException(status_code=400, detail="hours must be 1..720")
        out["hours"] = h
    if t == "t3":
        res = r.get("resource")
        if (RESOURCE_TYPES.get(res) or {}).get("tier") != 3:
            raise HTTPException(status_code=400, detail=f"{res} is not a tier-3 resource")
        out["resource"] = res
    return out


async def grant(db, uid: str, reward: Dict[str, Any]) -> Dict[str, Any]:
    """Give a reward to the player. Returns what was granted."""
    r = validate_reward(reward)
    n = r["count"]
    if r["type"] == "streak_shield":
        import comeback
        if comeback._DB is None:
            comeback.init(db)
        got = await comeback.add_shields(uid, n)
        return {**r, "shields_now": got}
    if r["type"] == "t3":
        await db.users.update_one({"id": uid}, {"$inc": {f"resources.{r['resource']}_tutorial": n}})
        return r
    key = item_key(r)
    await db.users.update_one({"id": uid}, {"$inc": {f"boosters.{key}": n}})
    return {**r, "item": key}


async def activate(db, uid: str, key: str) -> Dict[str, Any]:
    """Use one item. Atomic: an item is never spent twice."""
    if not (key.startswith("auto_shift_") or key.startswith("warehouse_guard_") or key == "repair_all"):
        raise HTTPException(status_code=400, detail="Unknown item")
    res = await db.users.update_one({"id": uid, f"boosters.{key}": {"$gte": 1}}, {"$inc": {f"boosters.{key}": -1}})
    if res.modified_count == 0:
        raise HTTPException(status_code=400, detail="Нет такого усилителя")
    u = await db.users.find_one({"id": uid}, {"_id": 0}) or {}
    now = _now()
    if key == "repair_all":
        from core.helpers import resolve_owner_keys, owner_businesses_query
        keys = await resolve_owner_keys(db, uid)
        r = await db.businesses.update_many({**owner_businesses_query(keys), "is_trial": {"$ne": True}},
                                            {"$set": {"durability": 100, "zero_durability_since": None,
                                                      "last_wear_update": now.isoformat()}})
        return {"ok": True, "repaired": r.modified_count}
    hours = int(key.rsplit("_", 1)[1].rstrip("h"))
    field = "auto_shift_until" if key.startswith("auto_shift_") else "decay_protected_until"
    base = max(now, _parse(u.get(field)) or now)          # stacks with what is already running
    until = (base + timedelta(hours=hours)).isoformat()
    await db.users.update_one({"id": uid}, {"$set": {field: until}})
    return {"ok": True, field: until}


async def inventory(db, uid: str) -> Dict[str, Any]:
    from business_config import RESOURCE_TYPES
    u = await db.users.find_one({"id": uid}, {"_id": 0}) or {}
    now = _now()
    items: List[Dict[str, Any]] = []
    for key, cnt in (u.get("boosters") or {}).items():
        if int(cnt or 0) > 0:
            kind = "repair_all" if key == "repair_all" else key.rsplit("_", 1)[0]
            items.append({"key": key, "kind": kind, "count": int(cnt),
                          "hours": int(key.rsplit("_", 1)[1].rstrip("h")) if key != "repair_all" else None})
    t3_items = []
    for rid, cnt in (u.get("resources") or {}).items():
        if rid.endswith("_tutorial") and int(float(cnt or 0)) > 0:
            base = rid[:-len("_tutorial")]
            meta = RESOURCE_TYPES.get(base) or {}
            t3_items.append({"key": rid, "resource": base, "count": int(float(cnt)),
                             "name_ru": meta.get("name_ru"), "name_en": meta.get("name_en"), "icon": meta.get("icon")})
    active = []
    for field, kind in (("auto_shift_until", "auto_shift"), ("decay_protected_until", "warehouse_guard")):
        t = _parse(u.get(field))
        if t and t > now:
            active.append({"kind": kind, "until": t.isoformat()})
    for b in u.get("active_resource_buffs") or []:
        t = _parse(b.get("expires_at"))
        if t and t > now:
            active.append({"kind": "t3_buff", "resource": b.get("resource_id"), "until": t.isoformat(),
                           "name": b.get("name"), "icon": b.get("icon"),
                           "effect_type": b.get("effect_type"), "effect_value": b.get("effect_value")})
    return {"items": sorted(items, key=lambda x: x["key"]), "t3_items": t3_items, "active": active,
            "streak_shields": int(u.get("streak_shields") or 0)}


def auto_shift_active(user_doc: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    t = _parse((user_doc or {}).get("auto_shift_until"))
    return bool(t and t > (now or _now()))


def create_boosters_router(db, get_current_user) -> APIRouter:
    r = APIRouter(prefix="/api/boosters", tags=["boosters"])

    @r.get("")
    async def get_inventory(current_user=Depends(get_current_user)):
        return await inventory(db, current_user.id)

    @r.post("/activate/{key}")
    async def post_activate(key: str, current_user=Depends(get_current_user)):
        return await activate(db, current_user.id, key)

    return r
