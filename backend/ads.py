"""Rewarded ads (Monetag) before the daily login bonus.

The player presses «Забрать» → watches N ads (default 2) → the bonus is credited.

  GET  /api/ads/config                     public: enabled, zone id, how many ads, min gap
  POST /api/ads/daily/watched              the app reports one finished ad (Monetag SDK promise resolved)
  GET  /api/ads/monetag/postback           Monetag server-to-server postback (?ymid=<user id>&secret=...)
  GET/PUT /api/admin/ads                   settings (admin)

With «verify_postback» on, only views confirmed by Monetag's postback count (the client report alone is not
trusted). Without it the client's report counts, limited by a minimum gap between two ads.
"""
from __future__ import annotations

import re
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request

DEFAULTS = {"enabled": False, "monetag_zone_id": "", "daily_ads_required": 2, "min_gap_sec": 8,
            "verify_postback": False, "postback_secret": "",
            # the SDK tag copied from the Monetag cabinet (admin → «Данные» → «Monetag»), and what was parsed from it
            "sdk_tag": "", "sdk_src": "", "sdk_fn": ""}

DEFAULT_SDK_SRC = "https://libtl.com/sdk.js"
_ATTR = r"""\b{name}\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))"""


def _attr(tag: str, name: str) -> str:
    m = re.search(_ATTR.format(name=re.escape(name)), tag, re.I)
    return (m.group(1) or m.group(2) or m.group(3) or "").strip() if m else ""


def parse_sdk_tag(tag: str) -> Dict[str, str]:
    """`<script src='//libtl.com/sdk.js' data-zone='10012345' data-sdk='show_10012345'></script>` →
    {sdk_src, monetag_zone_id, sdk_fn}. Raises ValueError with a Russian message for the admin."""
    tag = (tag or "").strip()
    if "<script" not in tag.lower():
        raise ValueError("Вставьте тег целиком: <script src=… data-zone=… data-sdk=…></script>")
    src = _attr(tag, "src")
    if src.startswith("//"):
        src = "https:" + src
    if not re.match(r"^https://[A-Za-z0-9.-]+(/[^\s\"'<>]*)?$", src):
        raise ValueError("В теге нет адреса SDK (src=https://…)")
    zone = "".join(ch for ch in _attr(tag, "data-zone") if ch.isdigit())
    if not zone:
        raise ValueError("В теге нет номера зоны (data-zone)")
    fn = _attr(tag, "data-sdk") or f"show_{zone}"
    if not re.match(r"^[A-Za-z_$][A-Za-z0-9_$]{0,63}$", fn):
        raise ValueError("Неверное имя функции в data-sdk")
    return {"sdk_src": src, "monetag_zone_id": zone, "sdk_fn": fn}


def _now():
    return datetime.now(timezone.utc)


def _day() -> str:
    from core.timeutil import msk_today_str
    return msk_today_str()


async def get_config(db) -> Dict[str, Any]:
    d = await db.admin_settings.find_one({"type": "ads"}, {"_id": 0}) or {}
    cfg = {**DEFAULTS, **{k: v for k, v in d.items() if k in DEFAULTS}}
    if not cfg["postback_secret"]:
        cfg["postback_secret"] = secrets.token_urlsafe(16)
        await db.admin_settings.update_one({"type": "ads"}, {"$set": {"type": "ads", "postback_secret": cfg["postback_secret"]}}, upsert=True)
    return cfg


def ads_active(cfg) -> bool:
    return bool(cfg.get("enabled")) and bool(str(cfg.get("monetag_zone_id") or "").strip()) and int(cfg.get("daily_ads_required") or 0) > 0


async def watched_today(db, uid: str, cfg=None) -> int:
    cfg = cfg or await get_config(db)
    q = {"user_id": uid, "day": _day(), "purpose": "daily"}
    if cfg.get("verify_postback"):
        q["source"] = "postback"
    else:
        q["source"] = "client"
    return await db.ad_views.count_documents(q)


async def daily_gate(db, uid: str) -> Dict[str, Any]:
    """{required, watched, ok} for the daily login bonus."""
    cfg = await get_config(db)
    if not ads_active(cfg):
        return {"required": 0, "watched": 0, "ok": True}
    req = int(cfg["daily_ads_required"])
    w = await watched_today(db, uid, cfg)
    return {"required": req, "watched": min(w, req), "ok": w >= req}


def create_ads_router(db, get_current_user, get_current_admin) -> APIRouter:
    r = APIRouter()

    @r.get("/api/ads/config")
    async def config():
        cfg = await get_config(db)
        zone = str(cfg["monetag_zone_id"] or "")
        return {"enabled": ads_active(cfg), "zone_id": zone, "daily_ads_required": int(cfg["daily_ads_required"]),
                "sdk_src": cfg.get("sdk_src") or DEFAULT_SDK_SRC, "sdk_fn": cfg.get("sdk_fn") or (f"show_{zone}" if zone else ""),
                "min_gap_sec": int(cfg["min_gap_sec"]), "verify_postback": bool(cfg["verify_postback"])}

    @r.post("/api/ads/daily/watched")
    async def watched(current_user=Depends(get_current_user)):
        cfg = await get_config(db)
        if not ads_active(cfg):
            return {"required": 0, "watched": 0, "ok": True}
        uid = current_user.id
        req = int(cfg["daily_ads_required"])
        if await db.ad_views.count_documents({"user_id": uid, "day": _day(), "purpose": "daily", "source": "client"}) >= req:
            return await daily_gate(db, uid)
        last = await db.ad_views.find({"user_id": uid, "purpose": "daily", "source": "client"}, {"_id": 0, "created_at": 1}) \
            .sort("created_at", -1).limit(1).to_list(1)
        if last:
            gap = (_now() - datetime.fromisoformat(last[0]["created_at"])).total_seconds()
            if gap < int(cfg["min_gap_sec"]):
                raise HTTPException(status_code=429, detail="ad_too_fast")
        await db.ad_views.insert_one({"id": str(uuid.uuid4()), "user_id": uid, "day": _day(), "purpose": "daily",
                                      "source": "client", "created_at": _now().isoformat()})
        return await daily_gate(db, uid)

    @r.get("/api/ads/monetag/postback")
    async def postback(request: Request):
        """Monetag postback URL (set in the Monetag dashboard):
        https://<domain>/api/ads/monetag/postback?ymid={ymid}&event={event_type}&secret=<postback_secret>"""
        cfg = await get_config(db)
        q = request.query_params
        if q.get("secret") != cfg["postback_secret"]:
            raise HTTPException(status_code=403, detail="bad secret")
        uid = (q.get("ymid") or "").split(":")[0]
        event = (q.get("event") or q.get("event_type") or "impression").lower()
        if not uid or not await db.users.find_one({"id": uid}, {"_id": 0, "id": 1}):
            return {"ok": False}
        if event not in ("impression", "valued", "click", "complete", "reward"):
            return {"ok": False}
        await db.ad_views.insert_one({"id": str(uuid.uuid4()), "user_id": uid, "day": _day(), "purpose": "daily",
                                      "source": "postback", "event": event, "created_at": _now().isoformat()})
        return {"ok": True}

    @r.get("/api/admin/ads")
    async def a_get(_=Depends(get_current_admin)):
        cfg = await get_config(db)
        today = _day()
        return {**cfg, "views_today": await db.ad_views.count_documents({"day": today}),
                "players_today": len(await db.ad_views.distinct("user_id", {"day": today}))}

    @r.put("/api/admin/ads")
    async def a_put(body: Dict[str, Any], _=Depends(get_current_admin)):
        upd = {k: v for k, v in body.items() if k in DEFAULTS and k not in ("sdk_src", "sdk_fn", "postback_secret")}
        if "sdk_tag" in upd:
            tag = str(upd["sdk_tag"] or "").strip()
            if tag:
                try:
                    upd.update(parse_sdk_tag(tag))
                except ValueError as e:
                    raise HTTPException(status_code=400, detail=str(e))
                upd["sdk_tag"] = tag[:2000]
            else:
                upd.update({"sdk_tag": "", "sdk_src": "", "sdk_fn": ""})
        if "daily_ads_required" in upd:
            upd["daily_ads_required"] = max(0, min(5, int(upd["daily_ads_required"] or 0)))
        if "min_gap_sec" in upd:
            upd["min_gap_sec"] = max(0, min(120, int(upd["min_gap_sec"] or 0)))
        if "monetag_zone_id" in upd:
            upd["monetag_zone_id"] = "".join(ch for ch in str(upd["monetag_zone_id"]) if ch.isdigit())
        for k in ("enabled", "verify_postback"):
            if k in upd:
                upd[k] = bool(upd[k])
        await db.admin_settings.update_one({"type": "ads"}, {"$set": {"type": "ads", **upd}}, upsert=True)
        return await a_get()

    return r
