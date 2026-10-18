"""Districts of the new city map: open / closed and how many lots are on sale.

    GET /api/city/districts            (public, cached 15 s)
    PUT /api/admin/city/districts      {unlocked: {"1": true, ...}, open_count: {"1": 121, ...}}

A lot can be bought only if its district is unlocked AND the lot is among the first
`open_count` lots of that district (lots are ordered big-first, as on the map). The
buy endpoint enforces this (admins bypass, like the zone trading schedule).
"""
from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException

from core.ttl_cache import cached, invalidate


def _layout_ranks() -> Dict[int, int]:
    from city_island import load_layout
    ranks, seen = {}, {}
    for s in sorted(load_layout()["slots"], key=lambda q: q["slot_id"]):
        d = s["district"]; ranks[s["slot_id"]] = seen.get(d, 0); seen[d] = seen.get(d, 0) + 1
    return ranks


_RANKS: Dict[int, int] = {}
DISTRICT_TOTAL = {1: 121, 2: 119, 3: 119, 4: 119}


def defaults() -> Dict[str, Any]:
    # nothing is on sale until the admin opens lots ("Районы карты"): a price on the map
    # always means the admin put that lot up for sale
    return {"unlocked": {str(d): True for d in DISTRICT_TOTAL}, "open_count": {str(d): 0 for d in DISTRICT_TOTAL}}


async def get_config(db) -> Dict[str, Any]:
    async def load():
        doc = await db.admin_settings.find_one({"type": "city_districts"}, {"_id": 0}) or {}
        cfg = defaults()
        for k in ("unlocked", "open_count"):
            cfg[k].update({str(a): b for a, b in (doc.get(k) or {}).items()})
        return cfg
    return await cached(f"cfg:city_districts:{id(db)}", 15, load, owner=db)


async def cell_open(db, cell: Dict[str, Any]) -> bool:
    """Is this lot of the new map open for sale by the admin's district settings?"""
    if not cell or cell.get("slot_id") is None or cell.get("district") is None:
        return True                                     # old map cells: no district rule
    global _RANKS
    if not _RANKS:
        _RANKS = _layout_ranks()
    cfg = await get_config(db)
    d = str(cell["district"])
    if not cfg["unlocked"].get(d, True):
        return False
    return _RANKS.get(int(cell["slot_id"]), 0) < int(cfg["open_count"].get(d, 10 ** 6))


async def district_unlocked(db, cell: Dict[str, Any]) -> bool:
    """The district of this lot is not closed by the admin (old map cells: always True)."""
    if not cell or cell.get("district") is None:
        return True
    cfg = await get_config(db)
    return cfg["unlocked"].get(str(cell["district"]), True) is not False


def create_city_districts_router(db, get_current_admin) -> APIRouter:
    r = APIRouter()

    @r.get("/api/city/districts")
    async def r_get():
        return await get_config(db)

    @r.get("/api/admin/city/districts/lots")
    async def r_lots(_=Depends(get_current_admin)):
        """Lots of every district in sale order (big first, as «мест в продаже» opens them): business type and
        whether a player already owns it — the admin sees which businesses N open lots are and how many are free."""
        from city_island import load_layout, TO_MAP_KEY
        from map_config import CITY_BUSINESSES
        owned = set()
        async for p in db.plots.find({"island_id": "ton_island", "owner": {"$type": "string"}}, {"_id": 0, "x": 1, "y": 1}):
            owned.add((p.get("x"), p.get("y")))
        out: Dict[str, Any] = {}
        types: Dict[str, Any] = {}
        for sl in sorted(load_layout()["slots"], key=lambda q: q["slot_id"]):
            k = TO_MAP_KEY.get(sl["business_type"], sl["business_type"])
            meta = CITY_BUSINESSES.get(k, {})
            types[k] = {"name": (meta.get("name") or {}).get("ru", k), "icon": meta.get("icon", "🏢"), "tier": meta.get("tier", 1)}
            out.setdefault(str(sl["district"]), []).append({"type": k, "owned": (sl["x"], sl["y"]) in owned})
        return {"districts": out, "types": types}

    @r.put("/api/admin/city/districts")
    async def r_put(body: Dict[str, Any], _=Depends(get_current_admin)):
        upd = {}
        for d, v in (body.get("unlocked") or {}).items():
            if str(d) not in {"1", "2", "3", "4"}:
                raise HTTPException(status_code=400, detail="district must be 1..4")
            upd[f"unlocked.{d}"] = bool(v)
        for d, v in (body.get("open_count") or {}).items():
            if str(d) not in {"1", "2", "3", "4"}:
                raise HTTPException(status_code=400, detail="district must be 1..4")
            n = int(v)
            if not 0 <= n <= DISTRICT_TOTAL[int(d)]:
                raise HTTPException(status_code=400, detail=f"open_count for district {d}: 0..{DISTRICT_TOTAL[int(d)]}")
            upd[f"open_count.{d}"] = n
        if upd:
            await db.admin_settings.update_one({"type": "city_districts"}, {"$set": {"type": "city_districts", **upd}}, upsert=True)
            invalidate("cfg:city_districts")
        return await get_config(db)

    return r
