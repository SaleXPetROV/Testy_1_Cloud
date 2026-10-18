"""Plot records of the city map: one record per cell.

The new city map keeps a FREE record (owner = None) for every slot. A purchase must turn THAT record into the
owned one — it used to insert a second record next to it, and then:
  • GET /api/island (last record of a cell wins) showed the owner and the player's «mine» mark, but
  • GET /api/island/cell/{x}/{y} (first record wins) answered «free»: the window said «Доступно» with the map
    price and «Купить», and the click wrote that free record back into the map, so the «mine» mark disappeared.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

OWNED = {"$type": "string"}


async def cell_plot(db, island_id: str, x: int, y: int, projection: Optional[Dict[str, Any]] = None) -> Optional[Dict]:
    """The record of a cell: the owned one if there is one, otherwise the free one."""
    proj = projection if projection is not None else {"_id": 0}
    q = {"island_id": island_id, "x": x, "y": y, "archived": {"$ne": True}}
    return (await db.plots.find_one({**q, "owner": OWNED}, proj)) or (await db.plots.find_one(q, proj))


def prefer_owned(plots) -> Dict:
    """{(x, y): record} — when a cell has several records, the owned one wins."""
    out: Dict = {}
    for p in plots:
        k = (p.get("x"), p.get("y"))
        cur = out.get(k)
        if cur is None or (not isinstance(cur.get("owner"), str) and isinstance(p.get("owner"), str)):
            out[k] = p
    return out


async def drop_free_duplicates(db, island_id: Optional[str] = None) -> int:
    """Delete FREE records (no owner, no business) of cells that already have an owned record. Idempotent."""
    q: Dict[str, Any] = {"owner": OWNED, "archived": {"$ne": True}}
    if island_id:
        q["island_id"] = island_id
    removed = 0
    async for p in db.plots.find(q, {"_id": 0, "island_id": 1, "x": 1, "y": 1}):
        r = await db.plots.delete_many({"island_id": p.get("island_id"), "x": p.get("x"), "y": p.get("y"),
                                        "owner": None, "business_id": None, "archived": {"$ne": True}})
        removed += r.deleted_count
    return removed


async def ensure_business_ids(db) -> Dict[str, int]:
    """Every business has its own id: give one to any record without it, then a UNIQUE index on businesses.id.
    If old duplicates exist the index is not created (the duplicates are reported) — nothing is deleted here."""
    import uuid
    fixed = 0
    async for b in db.businesses.find({"$or": [{"id": {"$exists": False}}, {"id": None}, {"id": ""}]}, {"_id": 1}):
        await db.businesses.update_one({"_id": b["_id"]}, {"$set": {"id": str(uuid.uuid4())}})
        fixed += 1
    seen, dups = set(), 0
    async for b in db.businesses.find({}, {"_id": 0, "id": 1}):
        if b.get("id") in seen:
            dups += 1
        seen.add(b.get("id"))
    if not dups:
        try:
            await db.businesses.create_index("id", unique=True, name="uniq_business_id")
        except Exception:
            # an older non-unique index named id_1 exists: replace it
            try:
                await db.businesses.drop_index("id_1")
                await db.businesses.create_index("id", unique=True, name="uniq_business_id")
            except Exception:
                pass
    return {"fixed": fixed, "duplicates": dups}
