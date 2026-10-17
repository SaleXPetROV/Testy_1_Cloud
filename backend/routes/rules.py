"""Game Rules (Правила игры) endpoints.

Admin authors rule items in Russian using a simple rich-text editor (bold /
italic / underline / colour + inline images). Users read them translated into
THEIR selected language via LibreTranslate (with the Emergent-LLM fallback),
while embedded images are preserved untouched.

User endpoint (mounted under /api):
  GET  /api/rules?lang=xx        -> localized rule items

Admin endpoints (mounted under /api/admin):
  GET    /api/admin/rules
  POST   /api/admin/rules
  PUT    /api/admin/rules/{rule_id}
  DELETE /api/admin/rules/{rule_id}
"""
from __future__ import annotations

import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from pydantic import BaseModel

from core.dependencies import get_admin_user
from translation_service import translate_html_preserving, translate_cached

logger = logging.getLogger(__name__)


class RulePayload(BaseModel):
    title: Optional[str] = ""
    content_html: Optional[str] = ""
    order: Optional[int] = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_rules_router(db):
    router = APIRouter(prefix="/api")

    @router.get("/rules")
    async def get_rules(lang: str = Query("ru")):
        """Public: return all rule items, translated into `lang` (default ru)."""
        items = await db.game_rules.find({}, {"_id": 0}).sort("order", 1).to_list(200)
        out = []
        for it in items:
            content = it.get("content_html") or ""
            title = it.get("title") or ""
            if lang and lang != "ru":
                try:
                    content = await translate_html_preserving(db, content, lang, "ru")
                    if title:
                        title = await translate_cached(db, title, lang, "ru")
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"rules translate failed: {e}")
            out.append({
                "id": it.get("id"),
                "title": title,
                "content_html": content,
                "order": it.get("order", 0),
            })
        return {"rules": out, "lang": lang}

    @router.get("/admin/rules")
    async def admin_list_rules(admin=Depends(get_admin_user)):
        """Admin: raw (Russian) rule items for editing."""
        items = await db.game_rules.find({}, {"_id": 0}).sort("order", 1).to_list(200)
        return {"rules": items}

    @router.post("/admin/rules")
    async def admin_create_rule(payload: RulePayload, admin=Depends(get_admin_user)):
        content = (payload.content_html or "").strip()
        if not content:
            raise HTTPException(status_code=400, detail="content_html is required")
        if payload.order is None:
            last = await db.game_rules.find({}, {"order": 1}).sort("order", -1).limit(1).to_list(1)
            order = (int(last[0].get("order", 0)) + 1) if last else 0
        else:
            order = int(payload.order)
        doc = {
            "id": str(uuid.uuid4()),
            "title": (payload.title or "").strip(),
            "content_html": content,
            "order": order,
            "created_at": _now(),
            "updated_at": _now(),
        }
        await db.game_rules.insert_one(doc.copy())
        doc.pop("_id", None)
        return doc

    @router.put("/admin/rules/{rule_id}")
    async def admin_update_rule(rule_id: str, payload: RulePayload, admin=Depends(get_admin_user)):
        upd = {"updated_at": _now()}
        if payload.title is not None:
            upd["title"] = (payload.title or "").strip()
        if payload.content_html is not None:
            c = (payload.content_html or "").strip()
            if not c:
                raise HTTPException(status_code=400, detail="content_html cannot be empty")
            upd["content_html"] = c
        if payload.order is not None:
            upd["order"] = int(payload.order)
        res = await db.game_rules.update_one({"id": rule_id}, {"$set": upd})
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Rule not found")
        return {"success": True}

    @router.delete("/admin/rules/{rule_id}")
    async def admin_delete_rule(rule_id: str, admin=Depends(get_admin_user)):
        res = await db.game_rules.delete_one({"id": rule_id})
        if res.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Rule not found")
        return {"success": True}

    return router
