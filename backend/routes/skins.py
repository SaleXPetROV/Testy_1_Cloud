"""
Business Skins system.
======================
A "skin" re-textures a business on the map. Skins are grouped: the GROUP is what
the player sees (e.g. "Bio Farm", "Crazy Bio Farm") and is identified by a unique
`group_key`. Within a group each (business_type, level) can have its own image so
a business looks different at every level; if a level has no image the level 0
("any") image (or the standard skin) is used as a fallback.

Documents (db.business_skins):
  { id, group_key, group_name, business_type, level (0 = any level),
    image (public /sprites path OR data:image/webp;base64 URL),
    is_standard (bool), created_at }
Unique key: (group_key, business_type, level).

Ownership: everyone owns the "standard" group. A player owns other groups when the
group_key is present in `user.available_skins` (granted by partner quests). A skin
is applied PER BUSINESS via `business.skin_group`.
"""
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional
from fastapi import UploadFile, File, Form, APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

STANDARD_GROUP = "standard"

# Business-type aliases: the map config / catalogue historically use different
# keys for the same building (e.g. cold_storage <-> cooler). A skin saved under
# one key must still resolve when the live business carries the other key,
# otherwise admin-added skins appear "missing" for some users. Mirrors the
# frontend TYPE_ALIASES in lib/skins.js.
SKIN_TYPE_ALIASES = {
    "cold_storage": "cooler", "cooler": "cold_storage",
    "signal_tower": "signal", "signal": "signal_tower",
    "scrap_yard": "scrap", "scrap": "scrap_yard",
}


def _type_variants(business_type):
    """Return [type] plus its known alias, for alias-tolerant skin lookups."""
    if not business_type:
        return []
    variants = [business_type]
    alias = SKIN_TYPE_ALIASES.get(business_type)
    if alias and alias not in variants:
        variants.append(alias)
    return variants


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_webp(image: str) -> bool:
    if not image:
        return False
    s = image.strip().lower()
    return s.endswith(".webp") or s.startswith("data:image/webp")


async def ensure_skin_indexes(db):
    try:
        await db.business_skins.create_index(
            [("group_key", 1), ("business_type", 1), ("level", 1)], unique=True, name="uniq_skin")
    except Exception as e:
        logger.debug(f"skin index ensure failed: {e}")


DEFAULT_SKINS = [
    {
        "group_key": STANDARD_GROUP, "group_name": "Standard",
        "business_type": "bio_farm", "level": 0,
        "image": "/sprites/bio_farm/bio_farm.webp", "is_standard": True,
    },
    {
        "group_key": "crazy_bio_farm", "group_name": "Crazy",
        "business_type": "bio_farm", "level": 0,
        "image": "/sprites/crazy_bio_farm/crazy_bio_farm.webp", "is_standard": False,
    },
]


async def seed_default_skins(db):
    await ensure_skin_indexes(db)
    for s in DEFAULT_SKINS:
        try:
            existing = await db.business_skins.find_one(
                {"group_key": s["group_key"], "business_type": s["business_type"], "level": s["level"]})
            if existing:
                await db.business_skins.update_one(
                    {"id": existing["id"]},
                    {"$set": {"image": s["image"], "group_name": s["group_name"], "is_standard": s["is_standard"]}})
            else:
                doc = {"id": str(uuid.uuid4()), "created_at": _now_iso(), **s}
                await db.business_skins.insert_one(doc)
        except Exception as e:
            logger.debug(f"seed skin failed: {e}")


def _clean(s: dict) -> dict:
    s.pop("_id", None)
    return s


class SkinCreate(BaseModel):
    group_key: str
    group_name: str
    business_type: str
    level: int = Field(0, ge=0, le=10)
    image: str  # /sprites path or data:image/webp;base64,...
    is_standard: bool = False


class ApplySkin(BaseModel):
    business_id: str
    group_key: str


class SkinSizeUpdate(BaseModel):
    # Display size on the map as a PERCENTAGE of the skin's natural size.
    # 100 = original. Bounded to sane values so a bad input can't break the map.
    height_pct: float = Field(100, ge=10, le=400)
    width_pct: float = Field(100, ge=10, le=400)


STAGE_LEVELS = {"1": range(0, 4), "2": range(4, 7), "3": range(7, 11)}   # same stages as the city map
_retired = {"done": False}


async def retire_old_standard(db) -> None:
    """«Стандарт» = the buildings of the city map now. Old pictures stored as the
    `standard` group are kept — moved to «Классика (старый стандарт)» (grant or delete them)."""
    if _retired["done"]:
        return
    await db.business_skins.update_many({"group_key": STANDARD_GROUP},
                                        {"$set": {"group_key": "classic", "group_name": "Классика (старый стандарт)", "is_standard": False}})
    _retired["done"] = True


def skins_dir():
    import os
    from pathlib import Path
    root = Path(os.environ.get("UPLOADS_ROOT") or (Path(__file__).resolve().parents[1] / "uploads"))
    d = root / "skins"
    d.mkdir(parents=True, exist_ok=True)
    return d


def create_skins_admin_router(db, admin_dependency):
    router = APIRouter(prefix="/api/admin/skins", tags=["skins-admin"])

    @router.post("/upload")
    async def upload_skin(group_key: str = Form(...), group_name: str = Form(""), business_type: str = Form(...),
                          stage: str = Form("all"), file: UploadFile = File(...), admin=Depends(admin_dependency)):
        """A skin picture for a group / business / stage, processed like the city buildings
        (background cut, foundation placed) and set on every level of that stage."""
        import re as _re, time as _time
        from city_sprites import TIER, TYPES as _TYPES
        g = (group_key or "").strip().lower()
        if not _re.fullmatch(r"[a-z0-9_]{2,40}", g):
            raise HTTPException(status_code=400, detail="Ключ группы: латиница, цифры и _, 2–40 символов")
        if g == STANDARD_GROUP:
            raise HTTPException(status_code=400, detail="«Стандарт» — это здания карты: меняются в группе «Стандарт»")
        if business_type not in _TYPES:
            raise HTTPException(status_code=400, detail="unknown business type")
        stages = list(STAGE_LEVELS) if stage == "all" else [stage]
        if any(st not in STAGE_LEVELS for st in stages):
            raise HTTPException(status_code=400, detail="stage must be 1, 2, 3 or all")
        raw = await file.read()
        if not raw or len(raw) > 12 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="file is empty or larger than 12 MB")
        try:
            from core.sprite_art import make_sprite
            webp, meta = make_sprite(raw, TIER[business_type], business_type)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"cannot process the image: {e}")
        d = skins_dir() / g / business_type; d.mkdir(parents=True, exist_ok=True)
        name = f"{'all' if stage == 'all' else stage}_{int(_time.time())}.webp"
        (d / name).write_bytes(webp)
        url = f"/api/skins/file/{g}/{business_type}/{name}"
        gname = (group_name or "").strip() or ((await db.business_skins.find_one({"group_key": g}, {"_id": 0, "group_name": 1})) or {}).get("group_name") or g
        for st in stages:
            for lvl in STAGE_LEVELS[st]:
                await db.business_skins.update_one(
                    {"group_key": g, "business_type": business_type, "level": lvl},
                    {"$set": {"group_key": g, "group_name": gname, "business_type": business_type, "level": lvl,
                              "image": url, "meta": meta, "is_standard": False, "height_pct": 100, "width_pct": 100},
                     "$setOnInsert": {"id": str(uuid.uuid4())}}, upsert=True)
        return {"ok": True, "image": url, "meta": meta}

    @router.delete("/stage/{group_key}/{business_type}/{stage}")
    async def delete_skin_stage(group_key: str, business_type: str, stage: str, admin=Depends(admin_dependency)):
        stages = list(STAGE_LEVELS) if stage == "all" else [stage]
        if group_key == STANDARD_GROUP or any(st not in STAGE_LEVELS for st in stages):
            raise HTTPException(status_code=400, detail="bad group / stage")
        lv = [l for st in stages for l in STAGE_LEVELS[st]]
        r = await db.business_skins.delete_many({"group_key": group_key, "business_type": business_type, "level": {"$in": lv}})
        return {"ok": True, "deleted": r.deleted_count}

    @router.get("")
    async def list_skins(group_key: Optional[str] = None, business_type: Optional[str] = None,
                         level: Optional[int] = None, admin=Depends(admin_dependency)):
        q = {}
        if group_key:
            q["group_key"] = group_key
        if business_type:
            q["business_type"] = business_type
        if level is not None:
            q["level"] = level
        await retire_old_standard(db)
        skins = await db.business_skins.find(q, {"_id": 0}).sort("group_key", 1).to_list(5000)
        return {"skins": skins, "count": len(skins)}

    @router.get("/groups")
    async def list_groups(admin=Depends(admin_dependency)):
        await retire_old_standard(db)
        skins = await db.business_skins.find({}, {"_id": 0}).to_list(5000)
        groups = {}
        for s in skins:
            g = groups.setdefault(s["group_key"], {
                "group_key": s["group_key"], "group_name": s.get("group_name"),
                "is_standard": s.get("is_standard", False), "count": 0,
                "image": None,
                "business_types": set()})
            g["count"] += 1
            g["business_types"].add(s.get("business_type"))
            # Representative preview image: prefer the level-0 ("any") image,
            # otherwise keep the first non-empty image we encounter.
            img = s.get("image")
            if img and (g["image"] is None or int(s.get("level", 0) or 0) == 0):
                g["image"] = img
        out = []
        for g in groups.values():
            g["business_types"] = sorted(list(g["business_types"]))
            out.append(g)
        return {"groups": sorted(out, key=lambda x: (not x["is_standard"], x["group_key"]))}

    @router.get("/exists")
    async def skin_exists(group_key: str, business_type: str, level: int = 0, admin=Depends(admin_dependency)):
        s = await db.business_skins.find_one(
            {"group_key": group_key, "business_type": business_type, "level": level}, {"_id": 0})
        return {"exists": bool(s), "skin": s}

    @router.post("")
    async def create_skin(data: SkinCreate, admin=Depends(admin_dependency)):
        if not _is_webp(data.image):
            raise HTTPException(status_code=400, detail="Изображение должно быть в формате WEBP")
        existing = await db.business_skins.find_one(
            {"group_key": data.group_key, "business_type": data.business_type, "level": data.level}, {"_id": 0})
        if existing:
            raise HTTPException(status_code=409, detail={
                "message": "Скин для этой группы, бизнеса и уровня уже существует",
                "existing": existing,
            })
        doc = {
            "id": str(uuid.uuid4()),
            "group_key": data.group_key.strip(),
            "group_name": data.group_name.strip() or data.group_key.strip(),
            "business_type": data.business_type,
            "level": int(data.level),
            "image": data.image,
            "is_standard": bool(data.is_standard),
            "created_at": _now_iso(),
        }
        await db.business_skins.insert_one(doc.copy())
        return {"status": "created", "skin": _clean(doc)}

    @router.delete("/{skin_id}")
    async def delete_skin(skin_id: str, admin=Depends(admin_dependency)):
        res = await db.business_skins.delete_one({"id": skin_id})
        if res.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Скин не найден")
        return {"status": "deleted"}

    @router.patch("/{skin_id}/size")
    async def update_skin_size(skin_id: str, data: SkinSizeUpdate, admin=Depends(admin_dependency)):
        """Persist per-skin display size (height/width as % of the original)."""
        res = await db.business_skins.update_one(
            {"id": skin_id},
            {"$set": {
                "height_pct": float(data.height_pct),
                "width_pct": float(data.width_pct),
                "size_updated_at": _now_iso(),
            }},
        )
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Скин не найден")
        skin = await db.business_skins.find_one({"id": skin_id}, {"_id": 0})
        return {"status": "updated", "skin": skin}

    return router


def create_skins_user_router(db, get_current_user):
    router = APIRouter(prefix="/api/skins", tags=["skins"])

    async def _full_user(current_user):
        uid = getattr(current_user, "id", None) or (current_user.get("id") if isinstance(current_user, dict) else None)
        doc = await db.users.find_one({"id": uid}, {"_id": 0})
        return doc or {}

    @router.get("/file/{group_key}/{business_type}/{name}")
    async def skin_file(group_key: str, business_type: str, name: str):
        from fastapi.responses import FileResponse
        if any(x in (group_key + business_type + name) for x in ("/", "..")) or not name.endswith(".webp"):
            raise HTTPException(status_code=404, detail="not found")
        f = skins_dir() / group_key / business_type / name
        if not f.is_file():
            raise HTTPException(status_code=404, detail="not found")
        return FileResponse(f, media_type="image/webp", headers={"Cache-Control": "public, max-age=31536000, immutable"})

    @router.get("/index")
    async def skins_index():
        """Nested index for the map renderer: {group_key: {business_type: {level: image}}}
        plus a parallel `sizes` map {group_key: {business_type: {level: {h, w}}}} with
        the admin-configured display size (percent of original, 100 = original)."""
        await retire_old_standard(db)
        skins = await db.business_skins.find({}, {"_id": 0}).to_list(5000)
        idx = {}
        sizes = {}
        metas = {}                                  # placement on the lot (skins processed like the city buildings)
        for s in skins:
            lvl = str(s["level"])
            idx.setdefault(s["group_key"], {}).setdefault(s["business_type"], {})[lvl] = s["image"]
            sizes.setdefault(s["group_key"], {}).setdefault(s["business_type"], {})[lvl] = {
                "h": float(s.get("height_pct", 100) or 100),
                "w": float(s.get("width_pct", 100) or 100),
            }
            if s.get("meta"):
                metas.setdefault(s["group_key"], {}).setdefault(s["business_type"], {})[lvl] = s["meta"]
        return {"index": idx, "sizes": sizes, "meta": metas}

    @router.get("/my")
    async def my_skins(business_type: Optional[str] = None, current_user=Depends(get_current_user)):
        """Groups the player owns (standard + available_skins) that have a skin for
        the given business_type. Returns a representative image + name per group."""
        await retire_old_standard(db)
        user_doc = await _full_user(current_user)
        owned = set(user_doc.get("available_skins") or [])
        owned.add(STANDARD_GROUP)
        q = {"group_key": {"$in": list(owned)}}
        if business_type:
            q["business_type"] = {"$in": _type_variants(business_type)}
        skins = await db.business_skins.find(q, {"_id": 0}).to_list(2000)
        groups = {}
        for s in skins:
            g = groups.setdefault(s["group_key"], {
                "group_key": s["group_key"], "group_name": s.get("group_name"),
                "is_standard": s.get("is_standard", False), "image": None, "by_level": {}})
            g["by_level"][str(s["level"])] = s["image"]
            # representative: prefer level 0 (any), else the lowest level
            if g["image"] is None or s["level"] == 0:
                g["image"] = s["image"]
        # every business always has its BASE skin = the building of the city map (or the admin's replacement)
        groups.pop(STANDARD_GROUP, None)
        if business_type:
            to_sprite = {"chip_factory": "chips_factory", "logistics": "logistics_hub", "repair_zone": "repair_shop", "cold_storage": "hydro_cooling"}
            st = to_sprite.get(business_type, business_type)
            cs = await db.admin_settings.find_one({"type": "city_sprites"}, {"_id": 0, "overrides": 1}) or {}
            ov = (cs.get("overrides") or {}).get(st) or {}
            def _url(stage):
                return (ov.get(str(stage)) or {}).get("url") or f"/sprites/city/{st}/stage{stage}.webp"
            by_level = {str(lv): _url(1 if lv <= 3 else 2 if lv <= 6 else 3) for lv in range(0, 11)}
            groups[STANDARD_GROUP] = {"group_key": STANDARD_GROUP, "group_name": "Базовый", "is_standard": True,
                                      "image": by_level["0"], "by_level": by_level}
        out = sorted(groups.values(), key=lambda x: (not x["is_standard"], x["group_key"]))
        return {"skins": out}

    @router.post("/apply")
    async def apply_skin(data: ApplySkin, current_user=Depends(get_current_user)):
        user_doc = await _full_user(current_user)
        uid = user_doc.get("id")
        owned = set(user_doc.get("available_skins") or [])
        owned.add(STANDARD_GROUP)
        if data.group_key not in owned:
            raise HTTPException(status_code=403, detail="У вас нет этого скина")
        # Verify a skin exists for this group + business type
        biz = await db.businesses.find_one({"id": data.business_id}, {"_id": 0})
        from rental import assert_not_rented as _anr
        _anr(biz)                            # a rented business keeps its skin
        if not biz:
            raise HTTPException(status_code=404, detail="Бизнес не найден")
        owner_keys = {biz.get("owner"), biz.get("owner_wallet"), biz.get("owner_id")}
        if uid not in owner_keys and user_doc.get("wallet_address") not in owner_keys and user_doc.get("email") not in owner_keys:
            raise HTTPException(status_code=403, detail="Это не ваш бизнес")
        if data.group_key != STANDARD_GROUP:
            has = await db.business_skins.find_one(
                {"group_key": data.group_key,
                 "business_type": {"$in": _type_variants(biz.get("business_type"))}})
            if not has:
                raise HTTPException(status_code=400, detail="Для этого бизнеса нет такого скина")
        await db.businesses.update_one({"id": data.business_id}, {"$set": {"skin_group": data.group_key}})
        return {"status": "applied", "business_id": data.business_id, "skin_group": data.group_key}

    return router
