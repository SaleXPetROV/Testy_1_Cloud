"""Notifications endpoints.

Provides full CRUD for in-app notifications + real-time push via the global
WebSocket manager. Tender, alliance, and economic modules call into
helpers like ``_notify_user`` which insert into the ``notifications``
collection and ws-push a ``notification_new`` event.
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional

from core.dependencies import get_current_user
from core.models import User
from core.helpers import get_user_identifiers as _helper_gui


def create_notifications_router(db):
    router = APIRouter(prefix="/api", tags=["notifications"])

    async def get_user_identifiers(current_user):
        return await _helper_gui(db, current_user)

    # ───────────── GET list (with filters) ─────────────
    @router.get("/notifications")
    async def get_user_notifications(
        current_user: User = Depends(get_current_user),
        unread_only: bool = False,
        priority: Optional[str] = None,
        limit: int = 50,
        skip: int = 0,
    ):
        ui = await get_user_identifiers(current_user)
        if not ui["user"]:
            return {"notifications": [], "unread_count": 0, "total": 0}
        user_id = ui["user"].get("id", "")
        query = {"user_id": user_id}
        if unread_only:
            query["read"] = False
        if priority:
            query["priority"] = priority

        cursor = db.notifications.find(query, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit)
        notifications = await cursor.to_list(limit)
        unread_count = await db.notifications.count_documents({"user_id": user_id, "read": False})
        total = await db.notifications.count_documents({"user_id": user_id})
        return {
            "notifications": notifications,
            "unread_count": unread_count,
            "total": total,
        }

    @router.get("/notifications/unread_count")
    async def unread_count(current_user: User = Depends(get_current_user)):
        ui = await get_user_identifiers(current_user)
        if not ui["user"]:
            return {"count": 0, "has_critical": False}
        user_id = ui["user"].get("id", "")
        count = await db.notifications.count_documents({"user_id": user_id, "read": False})
        has_critical = (await db.notifications.count_documents(
            {"user_id": user_id, "read": False, "priority": "critical"}
        )) > 0
        return {"count": count, "has_critical": has_critical}

    # ───────────── Mark read / delete ─────────────
    @router.post("/notifications/{notif_id}/read")
    async def mark_notification_read(notif_id: str, current_user: User = Depends(get_current_user)):
        ui = await get_user_identifiers(current_user)
        user_id = (ui.get("user") or {}).get("id", "")
        result = await db.notifications.update_one(
            {"id": notif_id, "user_id": user_id}, {"$set": {"read": True}}
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Notification not found")
        return {"status": "ok"}

    @router.post("/notifications/read_all")
    async def mark_all_read(current_user: User = Depends(get_current_user)):
        ui = await get_user_identifiers(current_user)
        user_id = (ui.get("user") or {}).get("id", "")
        result = await db.notifications.update_many(
            {"user_id": user_id, "read": False}, {"$set": {"read": True}}
        )
        return {"status": "ok", "updated": result.modified_count}

    @router.delete("/notifications/{notif_id}")
    async def delete_notification(notif_id: str, current_user: User = Depends(get_current_user)):
        ui = await get_user_identifiers(current_user)
        user_id = (ui.get("user") or {}).get("id", "")
        result = await db.notifications.delete_one({"id": notif_id, "user_id": user_id})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Notification not found")
        return {"status": "ok"}

    @router.delete("/notifications")
    async def clear_all_notifications(current_user: User = Depends(get_current_user)):
        ui = await get_user_identifiers(current_user)
        user_id = (ui.get("user") or {}).get("id", "")
        result = await db.notifications.delete_many({"user_id": user_id, "read": True})
        return {"status": "ok", "deleted": result.deleted_count}

    # ───────────── User preferences ─────────────
    @router.get("/notifications/preferences")
    async def get_notification_preferences(current_user: User = Depends(get_current_user)):
        ui = await get_user_identifiers(current_user)
        user = ui.get("user") or {}
        prefs = user.get("notification_preferences") or {
            "sound": True,
            "telegram": user.get("telegram_notifications", True),
        }
        return prefs

    @router.post("/notifications/preferences")
    async def update_notification_preferences(
        payload: dict, current_user: User = Depends(get_current_user)
    ):
        ui = await get_user_identifiers(current_user)
        user_id = (ui.get("user") or {}).get("id", "")
        allowed = {"sound": bool(payload.get("sound", True)),
                   "telegram": bool(payload.get("telegram", True))}
        await db.users.update_one(
            {"id": user_id},
            {"$set": {"notification_preferences": allowed,
                      "telegram_notifications": allowed["telegram"]}},
        )
        return {"status": "ok", "preferences": allowed}

    # ───────────── Low-durability banner (existing) ─────────────
    @router.get("/notifications/low-durability")
    async def get_low_durability_banners(current_user: User = Depends(get_current_user)):
        ui = await get_user_identifiers(current_user)
        if not ui["user"]:
            return {"alerts": []}

        user_ids = list(ui["ids"])
        or_conditions = [{"owner": uid} for uid in user_ids]
        or_conditions.extend([{"owner_wallet": uid} for uid in user_ids])

        cursor = db.businesses.find(
            {
                "$or": or_conditions,
                "durability": {"$lt": 20},
            },
            {"_id": 0, "id": 1, "business_type": 1, "level": 1, "durability": 1, "name": 1},
        ).limit(20)

        alerts = []
        async for biz in cursor:
            alerts.append({
                "business_id": biz.get("id"),
                "business_type": biz.get("business_type"),
                "level": biz.get("level", 1),
                "durability": round(float(biz.get("durability", 0) or 0), 1),
                "severity": "critical" if (biz.get("durability", 0) or 0) < 10 else "warning",
            })

        return {"alerts": alerts, "count": len(alerts)}

    return router
