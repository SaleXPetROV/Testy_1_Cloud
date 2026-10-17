"""
Referral Rally promo endpoints (user + admin).

User endpoints (mounted under /api):
  GET  /api/promo/active
  GET  /api/promo/referral-rally/leaderboard
  POST /api/promo/dismiss

Admin endpoints (mounted under /api/admin):
  POST /api/admin/promo/referral-rally/start
  POST /api/admin/promo/referral-rally/stop
  POST /api/admin/promo/referral-rally/finalize
  GET  /api/admin/promo/referral-rally/current
  GET  /api/admin/promo/referral-rally/history
  GET  /api/admin/referrals
  GET  /api/admin/referrals/export.csv
"""
from __future__ import annotations

import asyncio
import io
import csv
import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core.dependencies import get_current_user, get_admin_user
from core.models import User
import promo_service as ps

logger = logging.getLogger(__name__)


class StartRallyRequest(BaseModel):
    ends_at: str  # ISO datetime; MSK preferred but any offset works
    prizes_ton: Optional[List[float]] = None
    per_active_ton: Optional[float] = 1.5


class ReferralOverrideRequest(BaseModel):
    user_id: str
    active: int
    total: int


class ReferralOverrideClearRequest(BaseModel):
    user_id: str


def create_promo_router(db):
    router = APIRouter(prefix="/api", tags=["promo"])

    # -------- USER endpoints --------

    @router.get("/promo/active")
    async def promo_active(current_user: User = Depends(get_current_user)):
        """Return active-or-recently-finished campaign snapshot + my stats
        + whether the modal should be shown today (MSK).

        Response shape:
          {campaign, top3, my_stats, show_modal, mode: 'active'|'finished'|null}
        """
        active = await ps.get_active_campaign(db)
        mode = "active" if active else None
        campaign = active
        if not campaign:
            recent = await ps.get_recent_finished_campaign(db, days=7)
            if recent:
                campaign = recent
                mode = "finished"

        if not campaign:
            return {"campaign": None, "top3": [], "my_stats": None, "show_modal": False, "mode": None}

        # Top-3 live or frozen
        if mode == "finished":
            top3 = [{
                "user_id": w.get("user_id"),
                "username": w.get("username"),
                "active": w.get("active_count", 0),
                "total": w.get("total_count", 0),
                "rank": w.get("rank", 0),
            } for w in (campaign.get("winners") or [])]
        else:
            _sort = ps.current_leaderboard_sort()
            rows, _ = await ps.get_leaderboard_cached(db, sort=_sort, offset=0, limit=3,
                                                     campaign_id=campaign["id"])
            top3 = rows

        my_stats = await ps.compute_user_referral_stats(
            db, current_user.id, sort=ps.current_leaderboard_sort())

        # Modal cooldown: MSK day-based. Show if user's last_seen_date differs
        # from today's MSK date.
        today = ps.msk_today_str()
        udoc = await db.users.find_one({"id": current_user.id}, {"_id": 0, "promo_last_seen_date_msk": 1})
        last_seen = (udoc or {}).get("promo_last_seen_date_msk", "")
        show_modal = (last_seen != today)

        return {
            "campaign": campaign,
            "top3": top3,
            "my_stats": my_stats,
            "show_modal": bool(show_modal),
            "mode": mode,
        }

    @router.get("/promo/referral-rally/leaderboard")
    async def promo_leaderboard(
        current_user: User = Depends(get_current_user),
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=500),
    ):
        """Return paginated referral leaderboard. Sort follows the presale
        switch: by TOTAL invited before the presale, by ACTIVE after — same as
        the promo announcement. Includes the current user's rank/active/total."""
        # Look up any campaign (active or recent finished) for context
        active = await ps.get_active_campaign(db)
        recent_finished = await ps.get_recent_finished_campaign(db, days=7) if not active else None
        campaign = active or recent_finished
        cid = campaign["id"] if campaign else "_global_"

        _sort = ps.current_leaderboard_sort()
        rows, total_count = await ps.get_leaderboard_cached(
            db, sort=_sort, offset=offset, limit=limit, campaign_id=cid,
        )
        my_stats = await ps.compute_user_referral_stats(db, current_user.id, sort=_sort)
        return {
            "rows": rows,
            "total_count": total_count,
            "offset": offset,
            "limit": limit,
            "my_stats": my_stats,
            "sort": _sort,
            "campaign_active": bool(active),
            "campaign_finished": bool(recent_finished and not active),
        }

    @router.post("/promo/dismiss")
    async def promo_dismiss(current_user: User = Depends(get_current_user)):
        """Mark the modal as seen today (MSK). Called when user closes the popup."""
        today = ps.msk_today_str()
        await db.users.update_one(
            {"id": current_user.id},
            {"$set": {"promo_last_seen_date_msk": today}},
        )
        return {"ok": True, "date": today}

    return router


def create_promo_admin_router(db):
    router = APIRouter(prefix="/api/admin", tags=["promo-admin"])

    # -------- ADMIN: campaign control --------

    @router.post("/promo/referral-rally/start")
    async def admin_start_rally(req: StartRallyRequest, admin: User = Depends(get_admin_user)):
        try:
            campaign = await ps.create_campaign(
                db,
                admin_id=admin.id,
                ends_at_iso_msk=req.ends_at,
                prizes_ton=req.prizes_ton or [100.0, 50.0, 20.0],
                per_active_ton=float(req.per_active_ton or 1.5),
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # Fire-and-forget first broadcast
        try:
            from promo_broadcast import broadcast_active_rally
            asyncio.create_task(broadcast_active_rally(db, campaign))
        except Exception as e:
            logger.warning(f"failed to schedule first broadcast: {e}")

        return {"ok": True, "campaign": campaign}

    @router.post("/promo/referral-rally/stop")
    async def admin_stop_rally(admin: User = Depends(get_admin_user)):
        campaign = await ps.get_active_campaign(db)
        if not campaign:
            raise HTTPException(status_code=404, detail="Нет активной акции")
        ok = await ps.cancel_campaign(db, campaign["id"], admin.id)
        return {"ok": bool(ok)}

    @router.post("/promo/referral-rally/finalize")
    async def admin_finalize_rally(admin: User = Depends(get_admin_user)):
        campaign = await ps.get_active_campaign(db)
        if not campaign:
            raise HTTPException(status_code=404, detail="Нет активной акции")
        frozen = await ps.freeze_campaign(db, campaign)
        # Broadcast final
        try:
            from promo_broadcast import broadcast_finished_rally
            asyncio.create_task(broadcast_finished_rally(db, frozen))
        except Exception as e:
            logger.warning(f"finalize broadcast failed: {e}")
        return {"ok": True, "campaign": frozen}

    @router.post("/promo/referral-rally/winners/{user_id}/toggle-paid")
    async def admin_toggle_paid(user_id: str, admin: User = Depends(get_admin_user)):
        """Toggle the `paid` flag on a winner row (admin-managed manual payout)."""
        campaigns = await db[ps.COLLECTION].find({"type": ps.CAMPAIGN_TYPE, "status": "finished"}).to_list(500)
        for c in campaigns:
            winners = c.get("winners", [])
            changed = False
            for w in winners:
                if w.get("user_id") == user_id:
                    w["paid"] = not bool(w.get("paid"))
                    changed = True
                    break
            if changed:
                await db[ps.COLLECTION].update_one(
                    {"id": c["id"]},
                    {"$set": {"winners": winners}},
                )
                return {"ok": True, "campaign_id": c["id"]}
        raise HTTPException(status_code=404, detail="Winner not found")

    @router.get("/promo/referral-rally/current")
    async def admin_current_rally(admin: User = Depends(get_admin_user)):
        campaign = await ps.get_active_campaign(db)
        if not campaign:
            return {"campaign": None, "top10": []}
        rows, _ = await ps.compute_referrals_leaderboard(
            db, sort=ps.current_leaderboard_sort(), offset=0, limit=10)
        return {"campaign": campaign, "top10": rows}

    @router.get("/promo/referral-rally/broadcast-preview")
    async def admin_broadcast_preview(admin: User = Depends(get_admin_user)):
        """Preview the notification (with current top-3 winners) that would be
        broadcast to all bot subscribers, so the admin can review before sending."""
        campaign = await ps.get_active_campaign(db)
        if not campaign:
            raise HTTPException(status_code=404, detail="Нет активной акции")
        from promo_broadcast import build_daily_broadcast_preview
        preview = await build_daily_broadcast_preview(db, campaign, lang="ru")
        return {"ok": True, "preview": preview}

    @router.post("/promo/referral-rally/broadcast")
    async def admin_broadcast_now(admin: User = Depends(get_admin_user)):
        """Send the promo reminder (top-3) broadcast to all bot subscribers now.
        Triggered manually by the admin from the promo panel (replaces the old
        automatic daily 10:00 MSK job)."""
        campaign = await ps.get_active_campaign(db)
        if not campaign:
            raise HTTPException(status_code=404, detail="Нет активной акции")
        subscriber_count = await db.telegram_mappings.count_documents({})
        from promo_broadcast import broadcast_rally_daily
        asyncio.create_task(broadcast_rally_daily(db, campaign))
        return {"ok": True, "subscribers": subscriber_count}

    @router.get("/promo/referral-rally/history")
    async def admin_rally_history(admin: User = Depends(get_admin_user)):
        history = await ps.get_campaign_history(db, limit=100)
        return {"campaigns": history}

    # -------- ADMIN: referrals data section --------

    @router.get("/referrals")
    async def admin_referrals_list(
        admin: User = Depends(get_admin_user),
        sort: str = Query("active", pattern="^(active|total)$"),
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=500),
        search: Optional[str] = Query(None),
    ):
        """Referrer list with total/active counts. Optional username search."""
        rows, total_count = await ps.compute_referrals_leaderboard(
            db, sort=sort, offset=offset, limit=limit, include_partners=True)
        if search:
            s = search.lower().strip()
            rows = [r for r in rows if s in (r.get("username") or "").lower()]
        return {
            "rows": rows,
            "total_count": total_count,
            "offset": offset,
            "limit": limit,
            "sort": sort,
        }

    @router.get("/referrals/export.csv")
    async def admin_referrals_export(admin: User = Depends(get_admin_user),
                                     sort: str = Query("active", pattern="^(active|total)$")):
        """Full CSV export of referrers."""
        rows, _ = await ps.compute_referrals_leaderboard(db, sort=sort, offset=0, limit=500, include_partners=True)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["rank", "user_id", "username", "wallet_address", "total_referrals", "active_referrals"])
        for r in rows:
            w.writerow([
                r.get("rank"),
                r.get("user_id"),
                r.get("username") or "",
                r.get("wallet_address") or "",
                r.get("total", 0),
                r.get("active", 0),
            ])
        buf.seek(0)
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=referrals.csv"},
        )

    # -------- ADMIN: user search + referral override --------

    @router.get("/referrals/search-users")
    async def admin_search_users(
        admin: User = Depends(get_admin_user),
        q: str = Query(..., min_length=1),
        limit: int = Query(20, ge=1, le=50),
    ):
        """Search users by username, email or id (partial, case-insensitive).
        Returns matched users with their current referral totals (including any
        admin override already applied)."""
        import re
        qs = q.strip()
        pattern = re.escape(qs)
        # Exact ID match OR partial username / email
        query = {
            "$or": [
                {"id": qs},
                {"username": {"$regex": pattern, "$options": "i"}},
                {"email": {"$regex": pattern, "$options": "i"}},
            ]
        }
        docs = await db.users.find(
            query,
            {
                "_id": 0, "id": 1, "username": 1, "email": 1, "avatar": 1,
                "referral_override_active": 1, "referral_override_total": 1,
            },
        ).limit(int(limit)).to_list(int(limit))

        # Enrich each user with computed real active/total counts, so the
        # admin sees the current numbers before overriding.
        results = []
        for u in docs:
            stats = await ps.compute_user_referral_stats(
                db, u["id"], sort="active",
            )
            results.append({
                "user_id": u["id"],
                "username": u.get("username") or "",
                "email": u.get("email") or "",
                "avatar": u.get("avatar"),
                "active": stats.get("active", 0),
                "total": stats.get("total", 0),
                "override_active": u.get("referral_override_active"),
                "override_total": u.get("referral_override_total"),
            })
        return {"results": results, "count": len(results)}

    @router.post("/referrals/override")
    async def admin_set_referral_override(
        req: ReferralOverrideRequest,
        admin: User = Depends(get_admin_user),
    ):
        """Set (or update) an admin override for a user's active/total referral
        counts. This value is stored on the user document and takes precedence
        over the real, computed referral counts everywhere the referral
        leaderboard is used (admin promo panel, public rating page, top-3
        broadcast, freeze/finalize)."""
        if req.active < 0 or req.total < 0:
            raise HTTPException(status_code=400, detail="Значения не могут быть отрицательными")
        if req.active > req.total:
            raise HTTPException(status_code=400, detail="Активных не может быть больше, чем всего")

        user = await db.users.find_one({"id": req.user_id}, {"_id": 0, "id": 1, "username": 1})
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")

        from datetime import datetime, timezone
        await db.users.update_one(
            {"id": req.user_id},
            {"$set": {
                "referral_override_active": int(req.active),
                "referral_override_total": int(req.total),
                "referral_override_set_by": admin.id,
                "referral_override_set_at": datetime.now(timezone.utc).isoformat(),
            }},
        )
        ps._invalidate_leaderboard_cache()
        return {
            "ok": True,
            "user_id": req.user_id,
            "username": user.get("username"),
            "active": int(req.active),
            "total": int(req.total),
        }

    @router.post("/referrals/override/clear")
    async def admin_clear_referral_override(
        req: ReferralOverrideClearRequest,
        admin: User = Depends(get_admin_user),
    ):
        """Remove an existing admin override, restoring the real computed
        counts for the user."""
        user = await db.users.find_one({"id": req.user_id}, {"_id": 0, "id": 1})
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        await db.users.update_one(
            {"id": req.user_id},
            {"$unset": {
                "referral_override_active": "",
                "referral_override_total": "",
                "referral_override_set_by": "",
                "referral_override_set_at": "",
            }},
        )
        ps._invalidate_leaderboard_cache()
        return {"ok": True, "user_id": req.user_id}

    return router
