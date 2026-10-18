"""Admin fine-tuning of the city-map building sprites.

The sprites in frontend/public/sprites/city/ are auto-fitted to their lot
(manifest.json: anchor, footprint_width, top). The admin can correct any
business type / growth stage: scale (x0.3 .. x3), width and height on their own
(sx, sy: x0.3 .. x3) and shift (dx, dy as a fraction of the lot width). The map applies these on top of the auto-fit.

    GET  /api/city-sprites/tuning                      (public, cached by the client)
    PUT  /api/admin/city-sprites/tuning                {type, stage|"all", scale, dx, dy}
    DELETE /api/admin/city-sprites/tuning/{type}/{stage|all}

Parks (pictures of the park squares, 1x1 and 2x2; the built-in set is frontend/public/sprites/city/parks/manifest.json):
    PUT    /api/admin/city-sprites/park-tuning          {id, scale, sx, sy, dx, dy}
    DELETE /api/admin/city-sprites/park-tuning/{id}
    POST   /api/admin/city-sprites/park-upload          form: file + id (replace that picture) or size 1x1|2x2 (add a new one)
    DELETE /api/admin/city-sprites/park/{id}            back to the built-in picture / remove an added one
A park id is the file name without .webp (park1_trees, park2_pond, …); added ones are park1_custom_<time>.
"""
import os
import re
import time
from pathlib import Path
from typing import Any, Dict
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

TIER = {"helios": 1, "nano_dc": 1, "quartz_mine": 1, "signal_tower": 1, "hydro_cooling": 1, "bio_farm": 1, "scrap_yard": 1,
        "chips_factory": 2, "nft_studio": 2, "ai_lab": 2, "logistics_hub": 2, "cyber_cafe": 2, "repair_shop": 2, "vr_club": 2,
        "validator": 3, "gram_bank": 3, "dex": 3, "casino": 3, "arena": 3, "incubator": 3, "bridge": 3}
ALT_TYPES = {"cyber_cafe", "repair_shop", "vr_club", "chips_factory", "nft_studio", "ai_lab", "logistics_hub"}   # tier 2: a second view for the other lot orientation
MAX_UPLOAD = 12 * 1024 * 1024


def sprites_dir() -> Path:
    root = Path(os.environ.get("UPLOADS_ROOT") or (Path(__file__).resolve().parent / "uploads"))
    d = root / "city_sprites"
    d.mkdir(parents=True, exist_ok=True)
    return d

TYPES = {"helios", "nano_dc", "quartz_mine", "signal_tower", "hydro_cooling", "bio_farm", "scrap_yard",
         "chips_factory", "nft_studio", "ai_lab", "logistics_hub", "cyber_cafe", "repair_shop", "vr_club",
         "validator", "gram_bank", "dex", "casino", "arena", "incubator", "bridge"}
STAGES = ("1", "2", "3")


async def get_tuning(db) -> Dict[str, Any]:
    doc = await db.admin_settings.find_one({"type": "city_sprites"}, {"_id": 0}) or {}
    return doc.get("tuning") or {}


PARK_ID = re.compile(r"^park[12]_[a-z0-9_]{1,40}$")


async def get_parks(db) -> Dict[str, Any]:
    doc = await db.admin_settings.find_one({"type": "city_sprites"}, {"_id": 0, "park_tuning": 1, "park_overrides": 1, "park_extra": 1}) or {}
    return {"park_tuning": doc.get("park_tuning") or {}, "park_overrides": doc.get("park_overrides") or {},
            "park_extra": doc.get("park_extra") or {}}


async def get_overrides(db) -> Dict[str, Any]:
    doc = await db.admin_settings.find_one({"type": "city_sprites"}, {"_id": 0, "overrides": 1, "overrides_alt": 1}) or {}
    return {"overrides": doc.get("overrides") or {}, "overrides_alt": doc.get("overrides_alt") or {}}


def _clean(body: Dict[str, Any]) -> Dict[str, float]:
    try:
        scale = float(body.get("scale", 1)); dx = float(body.get("dx", 0)); dy = float(body.get("dy", 0))
        sx = float(body.get("sx", 1)); sy = float(body.get("sy", 1))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="scale, sx, sy, dx, dy must be numbers")
    if not 0.3 <= scale <= 3:
        raise HTTPException(status_code=400, detail="scale must be 0.3 .. 3")
    if not (0.3 <= sx <= 3 and 0.3 <= sy <= 3):
        raise HTTPException(status_code=400, detail="width / height must be 0.3 .. 3")
    if not (-0.5 <= dx <= 0.5 and -0.5 <= dy <= 0.5):
        raise HTTPException(status_code=400, detail="dx / dy must be -0.5 .. 0.5 (fraction of the lot width)")
    return {"scale": round(scale, 3), "sx": round(sx, 3), "sy": round(sy, 3), "dx": round(dx, 4), "dy": round(dy, 4)}


def create_city_sprites_router(db, get_current_admin) -> APIRouter:
    root = APIRouter()
    pub = APIRouter(prefix="/api/city-sprites", tags=["city-sprites"])
    adm = APIRouter(prefix="/api/admin/city-sprites", tags=["city-sprites-admin"])

    @pub.get("/tuning")
    async def r_get():
        # sprite size tuning + sprites replaced by the admin (both read by the map, the admin preview, «Мои бизнесы»)
        return {"tuning": await get_tuning(db), **(await get_overrides(db)), **(await get_parks(db))}

    @pub.get("/file/{sprite_type}/{name}")
    async def r_file(sprite_type: str, name: str):
        if (sprite_type not in TYPES and sprite_type != "parks") or "/" in name or ".." in name or not name.endswith(".webp"):
            raise HTTPException(status_code=404, detail="not found")
        f = sprites_dir() / sprite_type / name
        if not f.is_file():
            raise HTTPException(status_code=404, detail="not found")
        return FileResponse(f, media_type="image/webp", headers={"Cache-Control": "public, max-age=31536000, immutable"})

    @adm.post("/upload")
    async def r_upload(type: str = Form(...), stage: str = Form("all"), view: str = Form("main"),
                       file: UploadFile = File(...), _=Depends(get_current_admin)):
        """Replace a building sprite. A dark opaque background is cut out automatically; a PNG with a
        transparent background is taken as is. The foundation is placed like every other sprite."""
        if type not in TYPES:
            raise HTTPException(status_code=400, detail="unknown business type")
        if stage != "all" and stage not in STAGES:
            raise HTTPException(status_code=400, detail="stage must be 1, 2, 3 or all")
        if view not in ("main", "alt") or (view == "alt" and type not in ALT_TYPES):
            raise HTTPException(status_code=400, detail="the second view exists only for 1x2 businesses")
        raw = await file.read()
        if not raw or len(raw) > MAX_UPLOAD:
            raise HTTPException(status_code=400, detail="file is empty or larger than 12 MB")
        try:
            from core.sprite_art import make_sprite
            webp, meta = make_sprite(raw, TIER[type], type)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"cannot process the image: {e}")
        d = sprites_dir() / type; d.mkdir(parents=True, exist_ok=True)
        name = f"{view}_{stage}_{int(time.time())}.webp"          # new name = no stale browser cache
        (d / name).write_bytes(webp)
        entry = {**meta, "url": f"/api/city-sprites/file/{type}/{name}", "source": file.filename or "upload"}
        field = "overrides_alt" if view == "alt" else "overrides"
        upd = {f"{field}.{type}.{s_}": entry for s_ in (STAGES if stage == "all" else (stage,))}
        await db.admin_settings.update_one({"type": "city_sprites"}, {"$set": {"type": "city_sprites", **upd}}, upsert=True)
        return {"ok": True, "sprite": entry, **(await get_overrides(db))}

    @adm.delete("/override/{t}/{st}")
    async def r_unoverride(t: str, st: str, view: str = "main", _=Depends(get_current_admin)):
        if t not in TYPES or (st != "all" and st not in STAGES):
            raise HTTPException(status_code=400, detail="bad type / stage")
        field = "overrides_alt" if view == "alt" else "overrides"
        await db.admin_settings.update_one({"type": "city_sprites"},
                                           {"$unset": {f"{field}.{t}.{s_}": "" for s_ in (STAGES if st == "all" else (st,))}})
        return await get_overrides(db)

    @adm.put("/tuning")
    async def r_put(body: Dict[str, Any], _=Depends(get_current_admin)):
        t = body.get("type"); st = str(body.get("stage", "all"))
        if t not in TYPES:
            raise HTTPException(status_code=400, detail="unknown business type")
        if st != "all" and st not in STAGES:
            raise HTTPException(status_code=400, detail="stage must be 1, 2, 3 or all")
        vals = _clean(body)
        upd = {f"tuning.{t}.{s}": vals for s in (STAGES if st == "all" else (st,))}
        await db.admin_settings.update_one({"type": "city_sprites"}, {"$set": {"type": "city_sprites", **upd}}, upsert=True)
        return {"tuning": await get_tuning(db)}

    @adm.delete("/tuning/{t}/{st}")
    async def r_reset(t: str, st: str, _=Depends(get_current_admin)):
        if t not in TYPES or (st != "all" and st not in STAGES):
            raise HTTPException(status_code=400, detail="bad type / stage")
        unset = {f"tuning.{t}.{s}": "" for s in (STAGES if st == "all" else (st,))}
        await db.admin_settings.update_one({"type": "city_sprites"}, {"$unset": unset})
        return {"tuning": await get_tuning(db)}

    # ── parks ────────────────────────────────────────────────────────────────
    def _park_id(pid: str) -> str:
        if not PARK_ID.match(pid or ""):
            raise HTTPException(status_code=400, detail="bad park id")
        return pid

    @adm.put("/park-tuning")
    async def r_park_put(body: Dict[str, Any], _=Depends(get_current_admin)):
        pid = _park_id(str(body.get("id") or ""))
        await db.admin_settings.update_one({"type": "city_sprites"}, {"$set": {"type": "city_sprites", f"park_tuning.{pid}": _clean(body)}}, upsert=True)
        return await get_parks(db)

    @adm.delete("/park-tuning/{pid}")
    async def r_park_reset(pid: str, _=Depends(get_current_admin)):
        await db.admin_settings.update_one({"type": "city_sprites"}, {"$unset": {f"park_tuning.{_park_id(pid)}": ""}})
        return await get_parks(db)

    @adm.post("/park-upload")
    async def r_park_upload(file: UploadFile = File(...), id: str = Form(""), size: str = Form(""), _=Depends(get_current_admin)):
        """Replace a park picture (id) or add a new one of the given size (1x1 / 2x2). Processed like the buildings:
        a dark background is cut out, a transparent PNG is taken as is, the ground is placed on the square."""
        if id:
            pid = _park_id(id); sz = "2x2" if pid.startswith("park2_") else "1x1"
        elif size in ("1x1", "2x2"):
            sz = size; pid = f"park{size[0]}_custom_{int(time.time())}"
        else:
            raise HTTPException(status_code=400, detail="id or size (1x1 / 2x2) is required")
        raw = await file.read()
        if not raw or len(raw) > MAX_UPLOAD:
            raise HTTPException(status_code=400, detail="file is empty or larger than 12 MB")
        try:
            from core.sprite_art import make_sprite
            webp, meta = make_sprite(raw, f"park{sz[0]}", "park")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"cannot process the image: {e}")
        d = sprites_dir() / "parks"; d.mkdir(parents=True, exist_ok=True)
        name = f"{pid}_{int(time.time())}.webp"
        (d / name).write_bytes(webp)
        entry = {**{k: v for k, v in meta.items() if k != "long_axis"}, "url": f"/api/city-sprites/file/parks/{name}",
                 "source": file.filename or "upload", "size_key": sz}
        cur = await get_parks(db)
        field = "park_overrides" if (id and pid not in cur["park_extra"]) else "park_extra"
        await db.admin_settings.update_one({"type": "city_sprites"}, {"$set": {"type": "city_sprites", f"{field}.{pid}": entry}}, upsert=True)
        return {"ok": True, "id": pid, **(await get_parks(db))}

    @adm.delete("/park/{pid}")
    async def r_park_remove(pid: str, _=Depends(get_current_admin)):
        pid = _park_id(pid)
        await db.admin_settings.update_one({"type": "city_sprites"},
                                           {"$unset": {f"park_overrides.{pid}": "", f"park_extra.{pid}": "", f"park_tuning.{pid}": ""}})
        return await get_parks(db)

    root.include_router(pub); root.include_router(adm)
    return root
