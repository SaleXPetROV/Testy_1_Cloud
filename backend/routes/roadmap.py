"""Roadmap (Дорожная карта) + Idea suggestions (Предложить идею).

Admin authors roadmap phases and items IN RUSSIAN; users read them translated
into THEIR selected language via LibreTranslate (with Emergent-LLM fallback).
Each item is either done (green check) or pending (yellow clock).

Users can submit ideas (max 500 chars). Whatever language the user writes in,
we translate the idea to Russian on submit and store it. A daily scheduler job
(10:00 MSK) collects all un-sent ideas into a nicely formatted .txt and sends
it as a Telegram document to every admin with a connected Telegram account.

User endpoints (mounted under /api):
  GET  /api/roadmap?lang=xx        -> localized phases/items/footer
  POST /api/ideas                  -> submit an idea (auth required)

Admin endpoints (mounted under /api/admin):
  GET    /api/admin/roadmap
  PUT    /api/admin/roadmap/footer
  POST   /api/admin/roadmap/phase
  PUT    /api/admin/roadmap/phase/{phase_id}
  DELETE /api/admin/roadmap/phase/{phase_id}
  POST   /api/admin/roadmap/item
  PUT    /api/admin/roadmap/item/{item_id}
  DELETE /api/admin/roadmap/item/{item_id}
  GET    /api/admin/ideas
"""
from __future__ import annotations

import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from core.dependencies import get_admin_user, get_current_user
from translation_service import translate_cached, translate_text, detect_language

logger = logging.getLogger(__name__)

IDEA_MAX_CHARS = 500


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PhasePayload(BaseModel):
    title: Optional[str] = None
    order: Optional[int] = None


class ItemPayload(BaseModel):
    phase_id: Optional[str] = None
    text: Optional[str] = None
    done: Optional[bool] = None
    order: Optional[int] = None


class FooterPayload(BaseModel):
    text: Optional[str] = ""


class IdeaPayload(BaseModel):
    text: str


def create_roadmap_router(db):
    router = APIRouter(prefix="/api")

    # ---------- USER ----------
    @router.get("/roadmap")
    async def get_roadmap(lang: str = Query("ru")):
        """Public: phases + items + footer text, translated into `lang`."""
        phases = await db.roadmap_phases.find({}, {"_id": 0}).sort("order", 1).to_list(200)
        items = await db.roadmap_items.find({}, {"_id": 0}).sort("order", 1).to_list(1000)
        settings = await db.roadmap_settings.find_one({"_id": "singleton"}) or {}
        footer_text = (settings.get("footer_text") or "").strip()

        translate = lang and lang != "ru"

        by_phase: dict = {}
        for it in items:
            by_phase.setdefault(it.get("phase_id"), []).append(it)

        out_phases = []
        for ph in phases:
            title = ph.get("title") or ""
            if translate and title:
                try:
                    title = await translate_cached(db, title, lang, "ru")
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"roadmap phase translate failed: {e}")
            out_items = []
            for it in by_phase.get(ph.get("id"), []):
                text = it.get("text") or ""
                if translate and text:
                    try:
                        text = await translate_cached(db, text, lang, "ru")
                    except Exception as e:  # noqa: BLE001
                        logger.warning(f"roadmap item translate failed: {e}")
                out_items.append({
                    "id": it.get("id"),
                    "text": text,
                    "done": bool(it.get("done")),
                    "order": it.get("order", 0),
                })
            out_phases.append({
                "id": ph.get("id"),
                "title": title,
                "order": ph.get("order", 0),
                "items": out_items,
            })

        if translate and footer_text:
            try:
                footer_text = await translate_cached(db, footer_text, lang, "ru")
            except Exception as e:  # noqa: BLE001
                logger.warning(f"roadmap footer translate failed: {e}")

        return {"phases": out_phases, "footer_text": footer_text, "lang": lang}

    @router.post("/ideas")
    async def submit_idea(payload: IdeaPayload, current_user=Depends(get_current_user)):
        text = (payload.text or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="Empty idea")
        if len(text) > IDEA_MAX_CHARS:
            raise HTTPException(status_code=400, detail=f"Idea too long (max {IDEA_MAX_CHARS})")

        user_doc = await db.users.find_one({"id": current_user.id}, {"_id": 0}) or {}
        src = detect_language(text) or "en"
        text_ru = text
        if src != "ru":
            try:
                text_ru = await translate_text(text, "ru", src)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"idea translate failed: {e}")
                text_ru = text

        doc = {
            "id": str(uuid.uuid4()),
            "user_id": current_user.id,
            "username": user_doc.get("username") or "",
            "display_name": user_doc.get("display_name") or user_doc.get("username") or "",
            "telegram_username": user_doc.get("telegram_username") or "",
            "text_original": text,
            "source_lang": src,
            "text_ru": (text_ru or text).strip(),
            "sent": False,
            "created_at": _now(),
        }
        await db.idea_suggestions.insert_one(doc.copy())
        return {"success": True}

    # ---------- ADMIN ----------
    @router.get("/admin/roadmap")
    async def admin_get_roadmap(admin=Depends(get_admin_user)):
        phases = await db.roadmap_phases.find({}, {"_id": 0}).sort("order", 1).to_list(200)
        items = await db.roadmap_items.find({}, {"_id": 0}).sort("order", 1).to_list(1000)
        settings = await db.roadmap_settings.find_one({"_id": "singleton"}) or {}
        by_phase: dict = {}
        for it in items:
            by_phase.setdefault(it.get("phase_id"), []).append(it)
        for ph in phases:
            ph["items"] = by_phase.get(ph.get("id"), [])
        return {"phases": phases, "footer_text": (settings.get("footer_text") or "")}

    @router.put("/admin/roadmap/footer")
    async def admin_set_footer(payload: FooterPayload, admin=Depends(get_admin_user)):
        await db.roadmap_settings.update_one(
            {"_id": "singleton"},
            {"$set": {"footer_text": (payload.text or "").strip(), "updated_at": _now()}},
            upsert=True,
        )
        return {"success": True}

    @router.post("/admin/roadmap/phase")
    async def admin_create_phase(payload: PhasePayload, admin=Depends(get_admin_user)):
        title = (payload.title or "").strip()
        if not title:
            raise HTTPException(status_code=400, detail="title is required")
        last = await db.roadmap_phases.find({}, {"order": 1}).sort("order", -1).limit(1).to_list(1)
        order = int(payload.order) if payload.order is not None else ((int(last[0].get("order", 0)) + 1) if last else 0)
        doc = {"id": str(uuid.uuid4()), "title": title, "order": order,
               "created_at": _now(), "updated_at": _now()}
        await db.roadmap_phases.insert_one(doc.copy())
        doc.pop("_id", None)
        return doc

    @router.put("/admin/roadmap/phase/{phase_id}")
    async def admin_update_phase(phase_id: str, payload: PhasePayload, admin=Depends(get_admin_user)):
        upd = {"updated_at": _now()}
        if payload.title is not None:
            t = (payload.title or "").strip()
            if not t:
                raise HTTPException(status_code=400, detail="title cannot be empty")
            upd["title"] = t
        if payload.order is not None:
            upd["order"] = int(payload.order)
        res = await db.roadmap_phases.update_one({"id": phase_id}, {"$set": upd})
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Phase not found")
        return {"success": True}

    @router.delete("/admin/roadmap/phase/{phase_id}")
    async def admin_delete_phase(phase_id: str, admin=Depends(get_admin_user)):
        await db.roadmap_items.delete_many({"phase_id": phase_id})
        res = await db.roadmap_phases.delete_one({"id": phase_id})
        if res.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Phase not found")
        return {"success": True}

    @router.post("/admin/roadmap/item")
    async def admin_create_item(payload: ItemPayload, admin=Depends(get_admin_user)):
        phase_id = (payload.phase_id or "").strip()
        text = (payload.text or "").strip()
        if not phase_id or not text:
            raise HTTPException(status_code=400, detail="phase_id and text are required")
        phase = await db.roadmap_phases.find_one({"id": phase_id}, {"_id": 0, "id": 1})
        if not phase:
            raise HTTPException(status_code=404, detail="Phase not found")
        last = await db.roadmap_items.find({"phase_id": phase_id}, {"order": 1}).sort("order", -1).limit(1).to_list(1)
        order = int(payload.order) if payload.order is not None else ((int(last[0].get("order", 0)) + 1) if last else 0)
        doc = {"id": str(uuid.uuid4()), "phase_id": phase_id, "text": text,
               "done": bool(payload.done) if payload.done is not None else False,
               "order": order, "created_at": _now(), "updated_at": _now()}
        await db.roadmap_items.insert_one(doc.copy())
        doc.pop("_id", None)
        return doc

    @router.put("/admin/roadmap/item/{item_id}")
    async def admin_update_item(item_id: str, payload: ItemPayload, admin=Depends(get_admin_user)):
        upd = {"updated_at": _now()}
        if payload.text is not None:
            t = (payload.text or "").strip()
            if not t:
                raise HTTPException(status_code=400, detail="text cannot be empty")
            upd["text"] = t
        if payload.done is not None:
            upd["done"] = bool(payload.done)
        if payload.order is not None:
            upd["order"] = int(payload.order)
        if payload.phase_id is not None:
            upd["phase_id"] = payload.phase_id
        res = await db.roadmap_items.update_one({"id": item_id}, {"$set": upd})
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Item not found")
        return {"success": True}

    @router.delete("/admin/roadmap/item/{item_id}")
    async def admin_delete_item(item_id: str, admin=Depends(get_admin_user)):
        res = await db.roadmap_items.delete_one({"id": item_id})
        if res.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Item not found")
        return {"success": True}

    @router.get("/admin/ideas")
    async def admin_list_ideas(only_unsent: bool = Query(False), admin=Depends(get_admin_user)):
        q = {"sent": {"$ne": True}} if only_unsent else {}
        ideas = await db.idea_suggestions.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
        return {"ideas": ideas, "total": len(ideas)}

    return router


async def send_daily_ideas_digest(db) -> dict:
    """Collect all un-sent ideas, build a Russian .txt digest and send it as a
    Telegram document to every admin with a connected Telegram chat. Idempotent:
    ideas are marked `sent=True` only after a successful send to at least one
    admin. Called by the scheduler daily at 10:00 MSK (07:00 UTC)."""
    ideas = await db.idea_suggestions.find({"sent": {"$ne": True}}, {"_id": 0}).sort("created_at", 1).to_list(2000)
    if not ideas:
        logger.info("ideas digest: nothing to send")
        return {"sent": 0, "ideas": 0}

    admins = await db.users.find(
        {"is_admin": True, "telegram_chat_id": {"$nin": [None, ""]}},
        {"_id": 0, "telegram_chat_id": 1, "id": 1},
    ).to_list(200)
    if not admins:
        logger.warning("ideas digest: no admins with Telegram connected — keeping ideas unsent")
        return {"sent": 0, "ideas": len(ideas), "reason": "no_admin_chat"}

    today = datetime.now(timezone.utc).strftime("%d.%m.%Y")
    lines = [
        "💡 ИДЕИ ПОЛЬЗОВАТЕЛЕЙ",
        f"Дата: {today}",
        f"Всего новых идей: {len(ideas)}",
        "=" * 40,
        "",
    ]
    for i, idea in enumerate(ideas, 1):
        who = idea.get("display_name") or idea.get("username") or "Без имени"
        tg = idea.get("telegram_username")
        who_line = f"{i}. 👤 {who}"
        if tg:
            who_line += f" (@{tg})"
        who_line += f"  ·  ID: {idea.get('user_id', '')}"
        created = (idea.get("created_at") or "").replace("T", " ")[:19]
        lines.append(who_line)
        lines.append(f"🗓 {created} UTC")
        if idea.get("source_lang") and idea.get("source_lang") != "ru":
            lines.append(f"🌐 Язык оригинала: {idea.get('source_lang')}")
        lines.append("")
        lines.append((idea.get("text_ru") or idea.get("text_original") or "").strip())
        lines.append("")
        lines.append("-" * 40)
        lines.append("")
    content = "\n".join(lines)
    filename = f"ideas_{datetime.now(timezone.utc).strftime('%Y%m%d')}.txt"
    caption = f"💡 <b>Идеи пользователей</b> — {today}\nНовых идей: {len(ideas)}"

    delivered = 0
    try:
        from telegram_bot import get_telegram_bot
        bot = get_telegram_bot()
    except Exception as e:  # noqa: BLE001
        logger.error(f"ideas digest: bot unavailable: {e}")
        bot = None
    if bot is None:
        return {"sent": 0, "ideas": len(ideas), "reason": "no_bot"}

    for adm in admins:
        chat_id = adm.get("telegram_chat_id")
        if not chat_id:
            continue
        try:
            ok = await bot.send_document(str(chat_id), content, filename=filename, caption=caption)
            if ok:
                delivered += 1
        except Exception as e:  # noqa: BLE001
            logger.warning(f"ideas digest send to {chat_id} failed: {e}")

    if delivered > 0:
        ids = [idea["id"] for idea in ideas if idea.get("id")]
        await db.idea_suggestions.update_many(
            {"id": {"$in": ids}},
            {"$set": {"sent": True, "sent_at": _now()}},
        )
        logger.info(f"ideas digest: delivered to {delivered} admin(s), marked {len(ids)} idea(s) sent")
    else:
        logger.warning("ideas digest: delivery failed to all admins — ideas kept unsent")
    return {"sent": delivered, "ideas": len(ideas)}
