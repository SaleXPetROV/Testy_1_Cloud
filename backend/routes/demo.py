"""
Demo (Sandbox) mode API — Phase 1.
==================================
Isolated endpoints under /api/demo/*. These never touch real balances.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core.dependencies import get_current_user
from core.models import User
from demo_service import (
    get_or_create_demo_profile, DEMO_PLOT_COORDS,
    get_npc_prices, demo_collect, demo_repair, demo_repair_cost, demo_quick_sell, demo_quick_buy,
    resource_name, demo_my_businesses, demo_upgrade, demo_upgrade_cost,
)

logger = logging.getLogger(__name__)


class TradeReq(BaseModel):
    resource: str
    amount: float


def create_demo_router(db):
    router = APIRouter(prefix="/api/demo", tags=["demo"])

    async def _resolve_user(current_user: User) -> dict:
        user = None
        if current_user.id:
            user = await db.users.find_one({"id": current_user.id}, {"_id": 0})
        if not user and current_user.email:
            user = await db.users.find_one({"id": current_user.id}, {"_id": 0})
        if not user and current_user.wallet_address:
            user = await db.users.find_one({"id": current_user.id}, {"_id": 0})
        return user

    @router.get("/state")
    async def demo_state(current_user: User = Depends(get_current_user)):
        """Return the caller's demo profile (created on first access) + mode."""
        user = await _resolve_user(current_user)
        if not user:
            return {"is_demo": False, "profile": None}
        profile = await get_or_create_demo_profile(db, user["id"])
        return {
            "is_demo": bool(user.get("is_demo")),
            "demo_plot_coords": DEMO_PLOT_COORDS,
            "profile": profile,
        }

    @router.post("/enter")
    async def demo_enter(current_user: User = Depends(get_current_user)):
        """Switch the caller into demo mode (creates the demo profile if new)."""
        user = await _resolve_user(current_user)
        if not user:
            return {"is_demo": False, "profile": None}
        profile = await get_or_create_demo_profile(db, user["id"])
        set_doc = {"is_demo": True}
        if not user.get("demo_first_entered_at"):
            set_doc["demo_first_entered_at"] = datetime.now(timezone.utc).isoformat()
        await db.users.update_one({"id": user["id"]}, {"$set": set_doc})
        return {"is_demo": True, "demo_plot_coords": DEMO_PLOT_COORDS, "profile": profile}

    @router.post("/exit")
    async def demo_exit(current_user: User = Depends(get_current_user)):
        """Switch the caller back to real mode. Demo progress is preserved."""
        user = await _resolve_user(current_user)
        if not user:
            return {"is_demo": False}
        await db.users.update_one({"id": user["id"]}, {"$set": {"is_demo": False}})
        return {"is_demo": False}

    # ── Phase 2: demo economy ──────────────────────────────────────────────
    @router.get("/market-prices")
    async def demo_market_prices(current_user: User = Depends(get_current_user)):
        """Current NPC prices (TON/unit) used by the demo quick sell/buy bot."""
        prices = await get_npc_prices(db)
        meta = {res: resource_name(res) for res in prices.keys()}
        return {"prices": prices, "meta": meta}

    @router.post("/business/collect")
    async def demo_business_collect(current_user: User = Depends(get_current_user)):
        user = await _resolve_user(current_user)
        if not user:
            return {"status": "no_user"}
        return await demo_collect(db, user["id"])

    @router.post("/business/repair")
    async def demo_business_repair(current_user: User = Depends(get_current_user)):
        user = await _resolve_user(current_user)
        if not user:
            return {"status": "no_user"}
        return await demo_repair(db, user["id"])

    @router.get("/business/repair-cost")
    async def demo_business_repair_cost(current_user: User = Depends(get_current_user)):
        user = await _resolve_user(current_user)
        if not user:
            return {"status": "no_user"}
        return await demo_repair_cost(db, user["id"])

    @router.get("/my-businesses")
    async def demo_my_businesses_route(current_user: User = Depends(get_current_user)):
        user = await _resolve_user(current_user)
        if not user:
            return {"businesses": [], "summary": {}, "active_resource_buffs": []}
        return await demo_my_businesses(db, user["id"])

    @router.get("/business/upgrade-cost")
    async def demo_business_upgrade_cost(current_user: User = Depends(get_current_user)):
        user = await _resolve_user(current_user)
        if not user:
            return {"can_upgrade": False}
        return await demo_upgrade_cost(db, user["id"])

    @router.post("/business/upgrade")
    async def demo_business_upgrade(current_user: User = Depends(get_current_user)):
        user = await _resolve_user(current_user)
        if not user:
            return {"status": "no_user"}
        return await demo_upgrade(db, user["id"])

    @router.post("/trade/sell")
    async def demo_trade_sell(req: TradeReq, current_user: User = Depends(get_current_user)):
        user = await _resolve_user(current_user)
        if not user:
            return {"status": "no_user"}
        return await demo_quick_sell(db, user["id"], req.resource, req.amount)

    @router.post("/trade/buy")
    async def demo_trade_buy(req: TradeReq, current_user: User = Depends(get_current_user)):
        user = await _resolve_user(current_user)
        if not user:
            return {"status": "no_user"}
        return await demo_quick_buy(db, user["id"], req.resource, req.amount)

    return router
