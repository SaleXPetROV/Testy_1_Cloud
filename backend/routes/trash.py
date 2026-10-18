"""
Trash Piles ("Завалы") — per-user spawnable resource-drop objects on empty
GRAM City plots.

Per-user model (approved):
  Every player has their OWN piles. `/list` only returns the caller's piles,
  so two players never contend for the same drop. Each pile document carries
  `user_id`.

Life-cycle (per pile):
  1. Spawned in an empty GRAM-City plot (is_empty=True) with status="active".
  2. Player taps "Scan" → status="processing", timer starts. Timer length
     depends on this player's daily-scan count (see SCAN_DURATIONS).
  3. When now >= ready_at → status "ready" (computed on read).
  4. Player taps "Collect" → reward is added to their global `resources`
     inventory (shown on «Мои бизнесы → Мои ресурсы»), pile is DELETED.

Spawn rules (scheduler every 4h48m, one pile per user per tick):
  - For each user, delete their status=="active" pile (ignored → replaced).
  - piles in {"processing","ready"} are untouched — the player can come back
    hours later and still collect.
  - Spawn exactly ONE new active pile on a random free cell (up to 50 piles
    per user maximum — never more piles than there are fields).

Reward roll (per pile, decided AT SPAWN TIME so preview is stable):
  - 91.5% → 1 unit of a random Tier-1 resource.
  -   8%  → 2 units of a random Tier-1 resource.
  -  0.5% → 1 unit of a random Tier-2 resource.
"""
from __future__ import annotations

import logging
import random
import uuid
from datetime import datetime, timezone, timedelta
from core.dtutils import to_aware
from typing import Optional, List, Dict

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from core.dependencies import get_current_user
from core.models import User
from core.helpers import resolve_owner_keys, owner_businesses_query
from business_config import RESOURCE_TYPES, get_warehouse_weight

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SPAWN_TARGET = 50                # max simultaneous piles PER USER (= number of fields)
SPAWN_INTERVAL_HOURS = 4.8       # cron cadence (matches APScheduler interval)
PERSONAL_WAREHOUSE_CAPACITY = 50 # warehouse slots for players without a business
COLLECTION = "trash_piles"

# Daily scan streak → timer length (seconds). 5 spawns/day maximum.
SCAN_DURATIONS = [
    600,     # 1st  : 10 minutes
    1200,    # 2nd  : 20 minutes
    2400,    # 3rd  : 40 minutes
    4800,    # 4th  : 1h 20min
    10800,   # 5th+ : 3h
]

# Reward roll: cumulative (91.5% → t1x1, 99.5% → t1x2, 100% → t2x1)
_ROLL_T1_X1 = 0.915
_ROLL_T1_X2 = 0.995   # 0.915 + 0.08
# rest → t2x1 (0.5%)


def _daily_reset_key(now: Optional[datetime] = None) -> str:
    """Day key for the "5 spawns/day" rule. Reset at 00:00 MSK == 21:00 UTC."""
    now = now or datetime.now(timezone.utc)
    msk = now + timedelta(hours=3)
    return msk.strftime("%Y-%m-%d")


def _tier_resources(tier: int) -> List[str]:
    return [k for k, v in RESOURCE_TYPES.items() if v.get("tier") == tier]


def _roll_reward() -> Dict:
    """Return {"resource": id, "qty": int} respecting the 91.5/8/0.5 table."""
    r = random.random()
    if r < _ROLL_T1_X1:
        return {"resource": random.choice(_tier_resources(1)), "qty": 1}
    if r < _ROLL_T1_X2:
        return {"resource": random.choice(_tier_resources(1)), "qty": 2}
    return {"resource": random.choice(_tier_resources(2)), "qty": 1}


def _compute_status(doc: Dict) -> str:
    """Read-time transition processing → ready once the timer expired."""
    st = doc.get("status")
    if st == "processing":
        ready_at = doc.get("ready_at")
        ready_dt = to_aware(ready_at)
        if ready_dt and ready_dt <= datetime.now(timezone.utc):
            return "ready"
    return st


def _serialize(pile: Dict, viewer_user: Optional[User] = None) -> Dict:
    """
    Prepare a pile for JSON response. Reward is revealed only once the pile is
    'ready' (the player scanned it and the timer finished) — hidden while
    active/processing so the drop is a surprise until scanning completes.
    """
    st = _compute_status(pile)
    out = {
        "id": pile["id"],
        "x": pile["x"],
        "y": pile["y"],
        "status": st,
        "spawned_at": pile.get("spawned_at"),
        "scanned_by": pile.get("scanned_by"),
        "scan_started_at": pile.get("scan_started_at"),
        "scan_duration_sec": pile.get("scan_duration_sec"),
        "ready_at": pile.get("ready_at"),
    }
    viewer_id = getattr(viewer_user, "id", None) if viewer_user else None
    if st == "ready" and viewer_id and pile.get("user_id") == viewer_id:
        out["reward_resource"] = pile.get("reward_resource")
        out["reward_qty"] = pile.get("reward_qty")
    return out


# ---------------------------------------------------------------------------
# Spawn logic
# ---------------------------------------------------------------------------

async def _get_empty_cell_pool(db) -> List[Dict]:
    """Empty GRAM-City cells (is_empty=True) that can host a trash pile."""
    island = await db.islands.find_one({"id": "ton_island"}, {"_id": 0})
    if not island:
        try:
            from ton_island import generate_ton_island_map
            island = generate_ton_island_map()
            await db.islands.insert_one(island.copy())
        except Exception as e:  # pragma: no cover
            logger.error("Could not generate ton_island: %s", e)
            return []
    return [c for c in island.get("cells", []) if c.get("is_empty")]


async def spawn_for_user(db, user_id: str) -> bool:
    """
    Spawn ONE new active pile for a single user:
      - delete their stale 'active' pile (ignored → replaced);
      - keep processing/ready piles;
      - if under the 50-pile cap and a free cell exists, create one active pile.
    Returns True if a pile was spawned.
    """
    if not user_id:
        return False
    now = datetime.now(timezone.utc).isoformat()

    # Ignored active pile is replaced by the fresh one.
    await db[COLLECTION].delete_many({"user_id": user_id, "status": "active"})

    remaining = await db[COLLECTION].find(
        {"user_id": user_id, "status": {"$in": ["processing", "ready"]}}, {"_id": 0}
    ).to_list(1000)
    if len(remaining) >= SPAWN_TARGET:
        return False  # map full for this user

    busy = {(p["x"], p["y"]) for p in remaining}
    pool = await _get_empty_cell_pool(db)
    free = [c for c in pool if (c["x"], c["y"]) not in busy]
    if not free:
        return False

    cell = random.choice(free)
    reward = _roll_reward()
    await db[COLLECTION].insert_one({
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "x": cell["x"],
        "y": cell["y"],
        "status": "active",
        "spawned_at": now,
        "scanned_by": None,
        "scan_started_at": None,
        "scan_duration_sec": None,
        "ready_at": None,
        "reward_resource": reward["resource"],
        "reward_qty": reward["qty"],
    })
    return True


async def refill_trash_piles(db) -> Dict:
    """
    Scheduler routine (every 4h48m): spawn ONE active pile per user, replacing
    each user's ignored active pile.
    """
    # One-time cleanup of legacy global piles (pre per-user migration).
    await db[COLLECTION].delete_many({"user_id": {"$exists": False}})

    users = await db.users.find({}, {"_id": 0, "id": 1}).to_list(100000)
    spawned = 0
    for u in users:
        try:
            if await spawn_for_user(db, u.get("id")):
                spawned += 1
        except Exception as e:  # pragma: no cover
            logger.warning("trash spawn for user %s failed: %s", u.get("id"), e)

    logger.info("trash-spawn: processed %d users, spawned %d active piles", len(users), spawned)
    return {"users": len(users), "spawned": spawned}


# ---------------------------------------------------------------------------
# Warehouse helpers (unified with global user.resources inventory)
# ---------------------------------------------------------------------------

async def _capacity_and_used(db, user_doc: Dict) -> tuple:
    """(capacity, used) of the player's warehouse — the game-wide rule from
    core/warehouse.py (now also applies storage buffs, which this copy ignored)."""
    from core.warehouse import user_warehouse
    st = await user_warehouse(db, user_doc)
    return st["capacity"], st["used"]


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

class TrashScanResponse(BaseModel):
    id: str
    status: str
    scan_duration_sec: int
    ready_at: str
    reward_resource: str
    reward_qty: int


class TrashCollectResponse(BaseModel):
    success: bool
    resource: str
    qty: int
    warehouse_used: int
    warehouse_capacity: int


def create_trash_router(db):
    router = APIRouter(prefix="/api/trash", tags=["trash"])

    @router.get("/list")
    async def list_trash(current_user: User = Depends(get_current_user)):
        """
        Return the caller's own piles. New players get their first pile spawned
        lazily (one-time) so they see a Завал immediately; subsequent cadence is
        driven by the 4.8h scheduler.
        """
        piles = await db[COLLECTION].find({"user_id": current_user.id}, {"_id": 0}).to_list(1000)
        if not piles:
            user_doc = await db.users.find_one(
                {"id": current_user.id}, {"_id": 0, "trash_initialized": 1}
            )
            if not (user_doc or {}).get("trash_initialized"):
                await spawn_for_user(db, current_user.id)
                await db.users.update_one(
                    {"id": current_user.id}, {"$set": {"trash_initialized": True}}
                )
                piles = await db[COLLECTION].find(
                    {"user_id": current_user.id}, {"_id": 0}
                ).to_list(1000)
        return {"piles": [_serialize(p, current_user) for p in piles]}

    @router.post("/{pile_id}/scan", response_model=TrashScanResponse)
    async def scan_pile(pile_id: str, current_user: User = Depends(get_current_user)):
        """
        Start scanning the player's own active pile. Timer length grows with the
        player's daily scan count (reset at 00:00 MSK). The reward (rolled at
        spawn) is returned so the UI can show what's coming once it finishes.
        """
        now = datetime.now(timezone.utc)
        day_key = _daily_reset_key(now)

        pile = await db[COLLECTION].find_one({"id": pile_id}, {"_id": 0})
        if not pile:
            raise HTTPException(404, "Pile not found")
        if pile.get("user_id") != current_user.id:
            raise HTTPException(403, "This pile belongs to another player")
        if pile.get("status") != "active":
            raise HTTPException(409, "Pile is not available for scanning")

        user_doc = await db.users.find_one({"id": current_user.id}, {"_id": 0})
        if not user_doc:
            raise HTTPException(404, "User not found")

        streak = user_doc.get("trash_scan_daily") or {}
        streak_day = streak.get("day_key")
        streak_count = int(streak.get("count") or 0) if streak_day == day_key else 0

        if streak_count >= len(SCAN_DURATIONS):
            raise HTTPException(429, "Daily scan limit reached (5 per day)")

        duration = SCAN_DURATIONS[streak_count]
        ready_at = now + timedelta(seconds=duration)

        result = await db[COLLECTION].find_one_and_update(
            {"id": pile_id, "status": "active", "user_id": current_user.id},
            {"$set": {
                "status": "processing",
                "scanned_by": current_user.id,
                "scan_started_at": now.isoformat(),
                "scan_duration_sec": duration,
                "ready_at": ready_at.isoformat(),
            }},
            return_document=True,
        )
        if not result:
            raise HTTPException(409, "Pile is not available anymore")

        await db.users.update_one(
            {"id": current_user.id},
            {"$set": {"trash_scan_daily": {"day_key": day_key, "count": streak_count + 1}}},
        )

        return TrashScanResponse(
            id=pile_id,
            status="processing",
            scan_duration_sec=duration,
            ready_at=ready_at.isoformat(),
            reward_resource=pile.get("reward_resource"),
            reward_qty=int(pile.get("reward_qty") or 1),
        )

    @router.post("/{pile_id}/collect", response_model=TrashCollectResponse)
    async def collect_pile(pile_id: str, current_user: User = Depends(get_current_user)):
        """
        Collect a ready pile → add reward to the player's global `resources`
        inventory (subject to warehouse capacity; 50 for no-business players),
        then delete the pile so the cell is free again.
        """
        pile = await db[COLLECTION].find_one({"id": pile_id}, {"_id": 0})
        if not pile:
            raise HTTPException(404, "Pile not found")
        if pile.get("user_id") != current_user.id:
            raise HTTPException(403, "This pile belongs to another player")
        if pile.get("status") not in ("processing", "ready"):
            raise HTTPException(409, "Pile is not in a collectable state")
        if _compute_status(pile) != "ready":
            raise HTTPException(425, "Scan is still in progress")

        user_doc = await db.users.find_one({"id": current_user.id}, {"_id": 0})
        if not user_doc:
            raise HTTPException(404, "User not found")

        resource = pile["reward_resource"]
        qty = int(pile["reward_qty"])
        added_weight = get_warehouse_weight(resource) * qty
        capacity, used = await _capacity_and_used(db, user_doc)
        if used + added_weight > capacity:
            raise HTTPException(409, {
                "code": "warehouse_full",
                "message": "Warehouse is full",
                "used": used,
                "capacity": capacity,
                "needed": added_weight,
            })

        await db.users.update_one(
            {"id": current_user.id},
            {"$inc": {f"resources.{resource}": qty}},
        )
        await db[COLLECTION].delete_one({"id": pile_id})

        return TrashCollectResponse(
            success=True,
            resource=resource,
            qty=qty,
            warehouse_used=used + added_weight,
            warehouse_capacity=capacity,
        )

    @router.post("/spawn/refill")
    async def admin_refill(current_user: User = Depends(get_current_user)):
        """Admin: force a spawn cycle right now."""
        if not getattr(current_user, "is_admin", False):
            raise HTTPException(403, "Admin only")
        return await refill_trash_piles(db)

    return router
