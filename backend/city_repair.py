"""Repair of the new city map after the migration was re-run by mistake.

What happened: `city_switch.needs_switch` treated every owned business WITHOUT `city_slot_id` as "still on the old
map". A purchase on the new map never set that field, so after every purchase the next server start (or a new
worker process) re-ran the whole migration with --force. That run:
  • took only the newly bought businesses and planned slots for them WITHOUT knowing which slots were occupied —
    they were moved away from the lot the player bought (sometimes into a lot that already had a business);
  • deleted every plot record of the new map and re-created owners only for the businesses it had just moved —
    every other player's lot became «free» (the map said «Доступно» on the player's own business, the «mine»
    mark disappeared, and the lot looked buyable again).

`repair(db)` (idempotent, run at startup) puts things back:
  1. businesses moved by such a re-run go back to the lot they were bought on (taken from the migration backup
     of that run — `migration_backup_<tag>` whose saved island was ALREADY the new map), if that lot is free;
  2. owned businesses without a slot are linked to the slot at their coordinates (nothing moves);
  3. plot records follow the businesses: a lot with a business gets its owner back, a lot whose business left
     is freed. Lots claimed by two businesses are only reported (`admin_settings.city_map_repair.conflicts`).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

ISLAND_ID = "ton_island"
PREFIX = "city_v1-"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _layout():
    from city_island import load_layout
    return load_layout()


def _canon(t: Optional[str]) -> str:
    try:
        from scripts.migrate_to_city_map import canon_type
        return canon_type(t)
    except Exception:
        return t or ""


def _slot_fields(s: Dict) -> Dict[str, Any]:
    return {"plot_id": f"{PREFIX}{s['slot_id']}", "x": s["x"], "y": s["y"], "island_id": ISLAND_ID,
            "city_island_id": "city_v1", "city_slot_id": s["slot_id"], "district_id": s["district"],
            "footprint": {"w": s["w"], "h": s["h"]}}


async def _user_of(db, owner: str, cache: Dict) -> Optional[Dict]:
    if owner in cache:
        return cache[owner]
    u = await db.users.find_one({"$or": [{"id": owner}, {"wallet_address": owner}, {"email": owner}]},
                                {"_id": 0, "id": 1, "username": 1, "avatar": 1})
    cache[owner] = u
    return u


OWNED_BIZ = {"is_trial": {"$ne": True}, "tutorial": {"$ne": True}, "owner": {"$nin": [None, ""]}}


async def link_unslotted(db) -> Dict[str, int]:
    """Owned businesses on the new map without `city_slot_id`: link them to the slot at their coordinates."""
    lay = _layout()
    by_xy = {(s["x"], s["y"]): s for s in lay["slots"]}
    linked = unmatched = 0
    async for b in db.businesses.find({**OWNED_BIZ, "city_slot_id": {"$exists": False},
                                       "island_id": {"$in": [ISLAND_ID, None]}}, {"_id": 0, "id": 1, "x": 1, "y": 1, "business_type": 1}):
        s = by_xy.get((b.get("x"), b.get("y")))
        if s and _canon(s["business_type"]) == _canon(b.get("business_type")):
            await db.businesses.update_one({"id": b["id"]}, {"$set": _slot_fields(s)})
            linked += 1
        else:
            unmatched += 1
    return {"linked": linked, "unmatched": unmatched}


async def _undo_wrong_moves(db) -> int:
    """Businesses moved by a migration re-run (the backup island of that run was already the new map) go back to
    the lot they were bought on, if nobody else stands there now."""
    lay = _layout()
    by_xy = {(s["x"], s["y"]): s for s in lay["slots"]}
    names = sorted(n for n in await db.list_collection_names() if n.startswith("migration_backup_"))
    done: set = set()
    restored = 0
    for name in names:                                   # oldest run first: the lot it was really bought on
        bk = db[name]
        isl = await bk.find_one({"kind": "island"})
        if not isl or (isl.get("doc") or {}).get("version") != "city_v1":
            continue                                     # the first, real migration from the old map: keep
        async for row in bk.find({"kind": "business"}):
            d = row.get("doc") or {}
            bid = d.get("id")
            if not bid or bid in done:
                continue
            done.add(bid)
            s = by_xy.get((d.get("x"), d.get("y")))
            if not s or _canon(s["business_type"]) != _canon(d.get("business_type")):
                continue
            cur = await db.businesses.find_one({"id": bid}, {"_id": 0, "city_slot_id": 1, "owner": 1})
            if not cur or cur.get("city_slot_id") == s["slot_id"]:
                continue
            other = await db.businesses.find_one({**OWNED_BIZ, "id": {"$ne": bid}, "city_slot_id": s["slot_id"]}, {"_id": 0, "id": 1})
            if other:
                continue                                 # someone stands there now: leave it, report via conflicts
            await db.businesses.update_one({"id": bid}, {"$set": {**_slot_fields(s), "repaired_at": _now()},
                                                         "$unset": {"pre_migration": "", "migrated_at": ""}})
            await db.land_listings.update_many({"business_id": bid}, {"$set": {"plot_id": f"{PREFIX}{s['slot_id']}", "x": s["x"], "y": s["y"],
                                                                               "island_id": ISLAND_ID}})
            restored += 1
    return restored


async def reconcile_plots(db) -> Dict[str, Any]:
    """Plot records follow the businesses (one record per slot, id city_v1-<slot>)."""
    lay = _layout()
    slots = {s["slot_id"]: s for s in lay["slots"]}
    cache: Dict = {}
    by_slot: Dict[int, List[Dict]] = {}
    async for b in db.businesses.find({**OWNED_BIZ, "city_slot_id": {"$exists": True}},
                                      {"_id": 0, "id": 1, "owner": 1, "city_slot_id": 1, "built_at": 1, "created_at": 1}):
        by_slot.setdefault(int(b["city_slot_id"]), []).append(b)
    freed = owned = created = 0
    conflicts = []
    # lots whose business is gone or moved elsewhere become free
    async for p in db.plots.find({"island_id": ISLAND_ID, "city_slot_id": {"$exists": True}, "owner": {"$type": "string"}},
                                 {"_id": 0, "id": 1, "city_slot_id": 1, "business_id": 1}):
        here = by_slot.get(int(p["city_slot_id"])) or []
        if p.get("business_id") and not any(b["id"] == p["business_id"] for b in here) and not here:
            await db.plots.update_one({"id": p["id"]}, {"$set": {"owner": None, "owner_username": None, "owner_avatar": None,
                                                                "business_id": None, "business": None}})
            freed += 1
    for sid, bl in by_slot.items():
        s = slots.get(sid)
        if not s:
            continue
        bl = sorted(bl, key=lambda b: b.get("built_at") or b.get("created_at") or "")
        if len(bl) > 1:
            conflicts.append({"slot_id": sid, "businesses": [b["id"] for b in bl]})
        keep = bl[0]
        u = await _user_of(db, keep["owner"], cache)
        if not u:
            continue
        pid = f"{PREFIX}{sid}"
        p = await db.plots.find_one({"id": pid}, {"_id": 0, "owner": 1, "business_id": 1})
        if p is None:
            await db.plots.insert_one({"id": pid, "island_id": ISLAND_ID, "city_slot_id": sid, "slot_id": sid, "district": s["district"],
                                       "size": s["size"], "x": s["x"], "y": s["y"], "w": s["w"], "h": s["h"], "business_type": s["business_type"],
                                       "owner": u["id"], "owner_username": u.get("username"), "owner_avatar": u.get("avatar"),
                                       "business_id": keep["id"], "is_empty": False, "warehouses": [], "created_at": _now(),
                                       "purchased_at": keep.get("built_at") or keep.get("created_at") or _now()})
            created += 1
        elif p.get("owner") != u["id"] or p.get("business_id") != keep["id"]:
            await db.plots.update_one({"id": pid}, {"$set": {"owner": u["id"], "owner_username": u.get("username"),
                                                            "owner_avatar": u.get("avatar"), "business_id": keep["id"]}})
            owned += 1
        # the lot's free twin (an extra record without owner) never stays next to it
        await db.plots.delete_many({"island_id": ISLAND_ID, "x": s["x"], "y": s["y"], "owner": None, "id": {"$ne": pid}})
    return {"plots_given_back": owned, "plots_created": created, "plots_freed": freed, "conflicts": conflicts}


async def repair(db) -> Dict[str, Any]:
    isl = await db.islands.find_one({"id": ISLAND_ID}, {"_id": 0, "version": 1})
    if not isl or isl.get("version") != "city_v1":
        return {"skipped": "not on the new map"}
    rep: Dict[str, Any] = {"restored_moves": await _undo_wrong_moves(db)}
    rep.update(await link_unslotted(db))
    rep.update(await reconcile_plots(db))
    try:
        from core.ttl_cache import invalidate
        invalidate("island")
    except Exception:
        pass
    if rep["restored_moves"] or rep["linked"] or rep["plots_given_back"] or rep["plots_created"] or rep["plots_freed"] or rep["conflicts"]:
        await db.admin_settings.update_one({"type": "city_map_repair"}, {"$set": {"type": "city_map_repair", "at": _now(), **rep}}, upsert=True)
        logger.warning("🗺  city map repair: %s", {k: (len(v) if isinstance(v, list) else v) for k, v in rep.items()})
    return rep
