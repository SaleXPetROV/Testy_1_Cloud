"""ONE rule for a player's warehouse.

Before this module the same calculation lived in five places (the
/my/businesses summary, /market/buy + manual collect, the admin buyout, the
economic tick and the trash pile) and they had drifted apart: some counted
resources listed on the market, some applied the storage buff, some did not.
That is how "businesses keep producing over a full warehouse" happened. Every
caller now goes through the functions below.

The rule
--------
used     = weighted personal resources (floored per resource)
         + weighted resources locked in the player's ACTIVE market listings
capacity = sum over the player's businesses of storage.capacity × the
           business's storage_multiplier buff
         = PERSONAL_WAREHOUSE_CAPACITY (50) if that sum is 0 (no business,
           or legacy businesses without storage)
full     = capacity > 0 and used >= capacity
free     = max(0, capacity - used)

Weights come from business_config.get_warehouse_weight (tier 1 = 1, tier 2 =
5, tier 3 = 20). Business storage.items are NOT counted: they are already part
of user.resources.

Pure helpers (no DB) are exported for the economic tick, which preloads
everything in bulk and must not do per-player queries.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from business_config import get_warehouse_weight

PERSONAL_WAREHOUSE_CAPACITY = 50


# ───────────────────────────── pure helpers ─────────────────────────────
def used_by_resources(resources: Optional[Dict[str, Any]]) -> int:
    """Weighted space taken by a resources dict (floored per resource)."""
    total = 0
    for res, v in (resources or {}).items():
        try:
            n = int(float(v or 0))
        except (TypeError, ValueError):
            continue
        if n > 0:
            total += n * get_warehouse_weight(res)
    return total


def used_by_listing(listing: Dict[str, Any]) -> int:
    """Weighted space a single market listing keeps occupied."""
    res = listing.get("resource_type")
    try:
        amt = int(listing.get("amount") or 0)
    except (TypeError, ValueError):
        amt = 0
    if not res or amt <= 0:
        return 0
    return amt * get_warehouse_weight(res)


def business_capacity(business: Dict[str, Any], buff: Optional[Dict[str, Any]] = None) -> int:
    """storage.capacity of one business, with its storage_multiplier buff applied."""
    cap = (business.get("storage") or {}).get("capacity", 0) or 0
    try:
        cap = int(cap)
    except (TypeError, ValueError):
        cap = 0
    if buff:
        from game_systems import buff_multiplier
        mult = buff_multiplier(buff, "storage_multiplier", 1.0)
        if mult != 1.0:
            cap = int(cap * mult)
    return cap


def total_capacity(businesses: Iterable[Dict[str, Any]], buff_map: Optional[Dict[str, Dict]] = None) -> int:
    """Capacity of a player's whole warehouse (50 if they own no business)."""
    bizs = list(businesses or [])
    buff_map = buff_map or {}
    cap = sum(business_capacity(b, buff_map.get(b.get("id"))) for b in bizs)
    # A player always has at least the personal 50-slot warehouse — also when
    # their businesses report no storage (legacy docs). This is what the UI
    # has always shown; the other copies of this rule disagreed (0 / never full).
    return cap if cap > 0 else PERSONAL_WAREHOUSE_CAPACITY


def state(used: int, capacity: int) -> Dict[str, Any]:
    used, capacity = int(used), int(capacity)
    return {
        "used": used,
        "capacity": capacity,
        "free": max(0, capacity - used),
        "full": capacity > 0 and used >= capacity,
    }


# ───────────────────────────── DB helpers ─────────────────────────────
async def listed_used(db, user_doc: Dict[str, Any]) -> int:
    """Weighted space locked in the player's active market listings."""
    conds = []
    if user_doc.get("id"):
        conds.append({"seller_id": user_doc["id"]})
    if user_doc.get("email"):
        conds.append({"seller_email": user_doc["email"]})
    if not conds:
        return 0
    total = 0
    async for lst in db.market_listings.find(
        {"$or": conds, "status": "active"}, {"_id": 0, "resource_type": 1, "amount": 1}
    ):
        total += used_by_listing(lst)
    return total


async def buff_map_for(db, businesses: Iterable[Dict[str, Any]]) -> Dict[str, Dict]:
    """{business_id: active buff} — contract buff or patron buff (resolve_business_buff)."""
    from game_systems import resolve_business_buff
    out: Dict[str, Dict] = {}
    patron_cache: Dict[str, Any] = {}
    for biz in businesses:
        contract_doc = None
        if biz.get("contract_id"):
            contract_doc = await db.contracts.find_one({"id": biz["contract_id"], "status": "active"}, {"_id": 0})
        patron_doc = None
        pid = biz.get("patron_id")
        if pid:
            if pid not in patron_cache:
                patron_cache[pid] = await db.businesses.find_one({"id": pid}, {"_id": 0})
            patron_doc = patron_cache[pid]
        buff = resolve_business_buff(biz, contract_doc, patron_doc)
        if buff:
            out[biz.get("id")] = buff
    return out


async def user_businesses(db, user_doc: Dict[str, Any]) -> list:
    from core.helpers import resolve_owner_keys, owner_businesses_query
    keys = await resolve_owner_keys(db, user_doc.get("id"))
    return await db.businesses.find(owner_businesses_query(keys), {"_id": 0}).to_list(1000)


async def user_warehouse(db, user_doc: Dict[str, Any], *,
                         businesses: Optional[list] = None,
                         buff_map: Optional[Dict[str, Dict]] = None) -> Dict[str, Any]:
    """Full warehouse state of one player: used / capacity / free / full.

    Pass `businesses` / `buff_map` when the caller already loaded them (saves
    queries); otherwise they are fetched.
    """
    if not user_doc:
        return state(0, 0)
    if businesses is None:
        businesses = await user_businesses(db, user_doc)
    if buff_map is None:
        buff_map = await buff_map_for(db, businesses)
    used = used_by_resources(user_doc.get("resources")) + await listed_used(db, user_doc)
    return state(used, total_capacity(businesses, buff_map))
