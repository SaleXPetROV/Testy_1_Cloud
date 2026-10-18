"""Telegram profile photo as the player's avatar.

Players who registered through Telegram (Mini App, login widget, the bot) — or linked Telegram — get their
Telegram profile photo as the avatar, unless they changed the avatar in the project themselves
(users.custom_avatar_uploaded / avatar_uploaded — set by /api/auth/upload-avatar): the photo they chose wins.

The photo is taken with the Bot API (getUserProfilePhotos → getFile; the file URL contains the bot token, so it is
never given to the browser) or, when the bot can't see it, from the photo_url Telegram passed at login. It is
cropped to a square, 256 px WebP, stored in uploads/avatars and served by GET /api/avatars/<file> (the file name
holds a content hash, so a new photo is a new URL). The user gets avatar = {"type": "url", "url": "/api/avatars/…"}.

When: on every Telegram login (in the background, at most once in 12 h per player) and a background job for
everyone else (players registered by the bot, older accounts) — refreshed every 7 days.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

logger = logging.getLogger(__name__)

LOGIN_RECHECK_HOURS = 12
JOB_RECHECK_DAYS = 7
NAME_RE = re.compile(r"^tg_[a-zA-Z0-9-]{1,64}_[0-9a-f]{12}\.webp$")
_TASKS: set = set()


def avatars_dir() -> Path:
    root = Path(os.environ.get("UPLOADS_ROOT") or (Path(__file__).resolve().parent.parent / "uploads"))
    d = root / "avatars"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _now() -> datetime:
    return datetime.now(timezone.utc)


def tg_id_of(user: Dict[str, Any]) -> Optional[str]:
    for k in ("telegram_id", "telegram_user_id", "telegram_chat_id"):
        v = user.get(k)
        if v not in (None, ""):
            s = str(v).strip()
            if re.fullmatch(r"-?\d{3,20}", s):
                return s
    return None


def is_custom(user: Dict[str, Any]) -> bool:
    """The player set the avatar in the project → never replaced by the Telegram photo."""
    return bool(user.get("custom_avatar_uploaded") or user.get("avatar_uploaded"))


def may_replace(user: Dict[str, Any]) -> bool:
    if is_custom(user):
        return False
    av = user.get("avatar")
    if av in (None, "") or user.get("avatar_source") == "telegram":
        return True
    if isinstance(av, dict):
        if av.get("type") == "initials":
            return True
        url = str(av.get("url") or "")
    else:
        url = str(av)
        if url.startswith("data:image/svg"):                # the generated initials picture (not a photo)
            return True
    # an old Telegram photo link (login widget) is re-hosted; a Google picture etc. is left alone
    return bool(re.search(r"(^|//)(t\.me|telegram\.org|[a-z0-9.-]*telesco\.pe)/", url))


def _token() -> str:
    return (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()


def _api_base() -> str:
    return (os.environ.get("TELEGRAM_API_BASE") or "https://api.telegram.org").rstrip("/")


def _client():
    import httpx
    proxy = (os.environ.get("TELEGRAM_PROXY_URL") or "").strip() or None
    return httpx.AsyncClient(timeout=15, proxy=proxy) if proxy else httpx.AsyncClient(timeout=15)


async def _bot_photo(tg_id: str) -> Optional[bytes]:
    token = _token()
    if not token:
        return None
    base = _api_base()
    async with _client() as c:
        r = await c.get(f"{base}/bot{token}/getUserProfilePhotos", params={"user_id": tg_id, "limit": 1})
        j = r.json() if r.status_code == 200 else {}
        photos = ((j.get("result") or {}).get("photos") or []) if j.get("ok") else []
        if not photos or not photos[0]:
            return None
        sizes = sorted(photos[0], key=lambda p: int(p.get("width") or 0))
        pick = next((p for p in sizes if int(p.get("width") or 0) >= 320), sizes[-1])
        r = await c.get(f"{base}/bot{token}/getFile", params={"file_id": pick["file_id"]})
        fp = ((r.json() or {}).get("result") or {}).get("file_path") if r.status_code == 200 else None
        if not fp:
            return None
        r = await c.get(f"{base}/file/bot{token}/{fp}")
        return r.content if r.status_code == 200 and r.content else None


async def _url_photo(url: str) -> Optional[bytes]:
    if not url or not url.startswith("https://"):
        return None
    async with _client() as c:
        r = await c.get(url, follow_redirects=True)
        return r.content if r.status_code == 200 and r.content and len(r.content) < 8 * 1024 * 1024 else None


def to_webp(raw: bytes) -> Optional[bytes]:
    """Square crop, 256 px, WebP. None if it is not a raster image (e.g. Telegram's SVG placeholder)."""
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(raw))
        im.load()
        im = im.convert("RGB")
        w, h = im.size
        s = min(w, h)
        im = im.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s)).resize((256, 256), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "WEBP", quality=86, method=6)
        return buf.getvalue()
    except Exception:
        return None


async def refresh(db, user: Dict[str, Any], photo_url: Optional[str] = None, force: bool = False,
                  recheck: timedelta = timedelta(hours=LOGIN_RECHECK_HOURS)) -> Optional[str]:
    """Set the Telegram photo as the avatar if allowed. Returns the new avatar URL, or None (nothing changed)."""
    uid = user.get("id")
    tg_id = tg_id_of(user)
    if not uid or not tg_id or not may_replace(user):
        return None
    last = user.get("tg_avatar_checked_at")
    if not force and last:
        try:
            if datetime.fromisoformat(str(last)) > _now() - recheck:
                return None
        except Exception:
            pass
    await db.users.update_one({"id": uid}, {"$set": {"tg_avatar_checked_at": _now().isoformat()}})
    raw = None
    try:
        raw = await _bot_photo(tg_id)
    except Exception as e:
        logger.debug("tg avatar bot %s: %s", uid, e)
    if raw is None:
        try:
            raw = await _url_photo(photo_url or user.get("tg_photo_url") or "")
        except Exception as e:
            logger.debug("tg avatar url %s: %s", uid, e)
    webp = to_webp(raw) if raw else None
    if not webp:
        return None
    name = f"tg_{uid}_{hashlib.sha1(webp).hexdigest()[:12]}.webp"
    d = avatars_dir()
    if not (d / name).is_file():
        (d / name).write_bytes(webp)
    url = f"/api/avatars/{name}"
    # atomic: never over a photo the player set meanwhile
    r = await db.users.update_one({"id": uid, "custom_avatar_uploaded": {"$ne": True}, "avatar_uploaded": {"$ne": True}},
                                  {"$set": {"avatar": {"type": "url", "url": url}, "avatar_source": "telegram"}})
    old = user.get("avatar") if isinstance(user.get("avatar"), dict) else {}
    old_name = str((old or {}).get("url") or "").rsplit("/", 1)[-1]
    if r.modified_count and old_name != name and NAME_RE.match(old_name or ""):
        try:
            (d / old_name).unlink()
        except Exception:
            pass
    return url if r.modified_count else None


def refresh_bg(db, user: Dict[str, Any], photo_url: Optional[str] = None) -> None:
    """Fire-and-forget (login must not wait for Telegram)."""
    async def go():
        try:
            await refresh(db, user, photo_url)
        except Exception as e:                       # pragma: no cover
            logger.debug("tg avatar refresh: %s", e)
    try:
        t = asyncio.get_running_loop().create_task(go())
        _TASKS.add(t)
        t.add_done_callback(_TASKS.discard)
    except RuntimeError:
        pass


async def refresh_due(db, limit: int = 150) -> Dict[str, int]:
    """Background job: players with Telegram, no own avatar, not checked for JOB_RECHECK_DAYS."""
    if not _token():
        return {"checked": 0, "updated": 0}
    edge = (_now() - timedelta(days=JOB_RECHECK_DAYS)).isoformat()
    q = {"$and": [
        {"$or": [{"telegram_id": {"$nin": [None, ""]}}, {"telegram_user_id": {"$nin": [None, ""]}}, {"telegram_chat_id": {"$nin": [None, ""]}}]},
        {"custom_avatar_uploaded": {"$ne": True}}, {"avatar_uploaded": {"$ne": True}},
        {"$or": [{"tg_avatar_checked_at": {"$exists": False}}, {"tg_avatar_checked_at": {"$lt": edge}}]},
    ]}
    proj = {"_id": 0, "id": 1, "avatar": 1, "avatar_source": 1, "telegram_id": 1, "telegram_user_id": 1, "telegram_chat_id": 1,
            "custom_avatar_uploaded": 1, "avatar_uploaded": 1, "tg_avatar_checked_at": 1, "tg_photo_url": 1}
    checked = updated = 0
    async for u in db.users.find(q, proj).limit(limit):
        checked += 1
        try:
            if await refresh(db, u, recheck=timedelta(days=JOB_RECHECK_DAYS)):
                updated += 1
        except Exception as e:                       # pragma: no cover
            logger.debug("tg avatar job %s: %s", u.get("id"), e)
        await asyncio.sleep(0.25)                    # well under the Bot API limits
    return {"checked": checked, "updated": updated}


def create_avatars_router() -> APIRouter:
    r = APIRouter(prefix="/api/avatars", tags=["avatars"])

    @r.get("/{name}")
    async def avatar_file(name: str):
        if not NAME_RE.match(name or ""):
            raise HTTPException(status_code=404)
        p = avatars_dir() / name
        if not p.is_file():
            raise HTTPException(status_code=404)
        return FileResponse(p, media_type="image/webp", headers={"Cache-Control": "public, max-age=31536000, immutable"})

    return r
