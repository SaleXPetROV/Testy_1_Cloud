"""API of the promotion rewards (player + admin). Logic: minigame_rewards.py.

Player (login required)
  GET  /api/minigames/rewards/me        everything for the «Награды» page        (synonym GET /api/rewards)
  GET  /api/minigames/containers        my chests                                 (synonym GET /api/containers)
  POST /api/minigames/containers/{id}/open                                        (synonym POST /api/containers/{id}/open)
  GET  /api/minigames/boosters          my boosters;  POST /api/minigames/boosters/{id}/activate
  GET  /api/minigames/puzzles           my puzzles                                (synonym GET /api/puzzles)
  POST /api/minigames/puzzles/{id}/assemble -> {need_wallet} or the NFT grant     (synonym POST /api/puzzles/{id}/assemble)
Public
  GET  /api/minigames/img/{file}        uploaded pictures (puzzle pieces are served one by one)
  GET  /api/nft-meta/{nft_id}/{index}.json   metadata of an SBT copy (name, description, image, attributes)
Admin (Russian UI, no translations): rewards, containers, boosters, NFT definitions + warehouse, puzzles,
  players (manual grant / reset), threshold check for all, statistics, anomalies.
"""
from __future__ import annotations

import io
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

import minigame_rewards as mr

IMG_RE = re.compile(r"^[A-Za-z0-9_\-]+\.(webp|png|jpg)$")


def img_dir() -> Path:
    root = Path(os.environ.get("UPLOADS_ROOT") or (Path(__file__).resolve().parent / "uploads"))
    d = root / "minigames"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _err(e: Exception, code: int = 400):
    raise HTTPException(status_code=code, detail=str(e))


def _bool(v, default=True) -> bool:
    return default if v is None else bool(v)


def _i18n(v) -> Dict[str, str]:
    if not isinstance(v, dict):
        return {}
    return {k: str(t)[:120] for k, t in v.items() if k in mr.LANGS and str(t).strip()}


def create_minigame_rewards_router(db, get_current_user, get_current_admin, get_config) -> APIRouter:
    r = APIRouter()

    # ───────────────────────── player ─────────────────────────
    async def _me_rewards(user):
        return await mr.my_rewards(db, user.id, await get_config(db))

    @r.get("/api/minigames/rewards/me")
    async def me(current_user=Depends(get_current_user)):
        return await _me_rewards(current_user)

    @r.get("/api/rewards")
    async def me_alias(current_user=Depends(get_current_user)):
        return await _me_rewards(current_user)

    async def _containers(uid):
        d = await mr.my_rewards(db, uid, await get_config(db))
        return {"unopened": [c for c in d["containers"] if c["status"] == "unopened"],
                "opened": [c for c in d["containers"] if c["status"] == "opened"]}

    @r.get("/api/minigames/containers")
    async def containers(current_user=Depends(get_current_user)):
        return await _containers(current_user.id)

    @r.get("/api/containers")
    async def containers_alias(current_user=Depends(get_current_user)):
        return await _containers(current_user.id)

    async def _open(cid, uid):
        try:
            return await mr.open_container(db, uid, cid)
        except mr.NoSpace as e:
            raise HTTPException(status_code=409, detail={"code": "no_space", "need": e.need})
        except ValueError as e:
            raise HTTPException(status_code=404 if str(e) == "not_found" else 409, detail=str(e))

    @r.post("/api/minigames/containers/{cid}/open")
    async def open_c(cid: str, current_user=Depends(get_current_user)):
        return await _open(cid, current_user.id)

    @r.post("/api/containers/{cid}/open")
    async def open_c_alias(cid: str, current_user=Depends(get_current_user)):
        return await _open(cid, current_user.id)

    @r.get("/api/minigames/boosters")
    async def boosters(current_user=Depends(get_current_user)):
        return (await mr.my_rewards(db, current_user.id, await get_config(db)))["boosters"]

    @r.post("/api/minigames/boosters/{bid}/activate")
    async def activate(bid: str, current_user=Depends(get_current_user)):
        try:
            return await mr.activate_booster(db, current_user.id, bid)
        except ValueError as e:
            raise HTTPException(status_code=404 if str(e) == "not_found" else 409, detail=str(e))

    @r.get("/api/minigames/puzzles")
    async def puzzles(current_user=Depends(get_current_user)):
        return await mr.my_puzzles(db, current_user.id)

    @r.get("/api/puzzles")
    async def puzzles_alias(current_user=Depends(get_current_user)):
        return await mr.my_puzzles(db, current_user.id)

    async def _assemble(pid, uid):
        try:
            return await mr.assemble_puzzle(db, uid, pid)
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e))

    @r.post("/api/minigames/puzzles/{pid}/assemble")
    async def assemble(pid: str, current_user=Depends(get_current_user)):
        return await _assemble(pid, current_user.id)

    @r.post("/api/puzzles/{pid}/assemble")
    async def assemble_alias(pid: str, current_user=Depends(get_current_user)):
        return await _assemble(pid, current_user.id)

    @r.get("/api/minigames/img/{name}")
    async def img(name: str):
        if not IMG_RE.match(name):
            raise HTTPException(status_code=404)
        p = img_dir() / name
        if not p.exists():
            raise HTTPException(status_code=404)
        return FileResponse(p, headers={"Cache-Control": "public, max-age=86400"})

    @r.get("/api/nft-meta/{nft_id}/{index}.json")
    async def nft_meta(nft_id: str, index: int, request: Request):
        nft = await mr._find(db, "mg_nfts", {"id": nft_id})
        if not nft or index < 0 or index >= int(nft.get("next_index") or 0):
            raise HTTPException(status_code=404)
        img = nft.get("image_url") or ""
        if img.startswith("/"):
            # wallets (Tonkeeper, GetGems) fetch the picture from outside: a public https origin, never the
            # internal address the app server sees behind nginx. NFT_META_BASE_URL wins, then the proxy headers.
            base = (os.environ.get("NFT_META_BASE_URL") or "").strip()
            if base:
                from urllib.parse import urlsplit
                u = urlsplit(base)
                origin = f"{u.scheme}://{u.netloc}"
            else:
                proto = (request.headers.get("x-forwarded-proto") or request.url.scheme).split(",")[0].strip()
                host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc).split(",")[0].strip()
                origin = f"{proto}://{host}"
            img = origin + img
        return JSONResponse({"name": f"{nft.get('name')} #{index + 1}", "description": nft.get("description") or "",
                             "image": img, "attributes": nft.get("attributes") or []})

    # ───────────────────────── admin: uploads ─────────────────────────
    async def _save_image(file: UploadFile, prefix: str) -> str:
        from PIL import Image
        raw = await file.read()
        if len(raw) > 8 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Файл больше 8 МБ")
        try:
            im = Image.open(io.BytesIO(raw)); im.load()
        except Exception:
            raise HTTPException(status_code=400, detail="Это не картинка")
        im = im.convert("RGBA")
        im.thumbnail((1024, 1024))
        name = f"{prefix}_{uuid.uuid4().hex[:10]}.webp"
        im.save(img_dir() / name, "WEBP", quality=90)
        return f"/api/minigames/img/{name}"

    @r.post("/api/admin/minigames/upload")
    async def upload(file: UploadFile = File(...), _=Depends(get_current_admin)):
        return {"url": await _save_image(file, "img")}

    # ───────────────────────── admin: rewards ─────────────────────────
    async def _clean_reward(body: Dict, rid: Optional[str]) -> Dict:
        typ, cat = body.get("type"), body.get("category")
        if typ not in mr.REWARD_TYPES or cat not in mr.REWARD_CATEGORIES:
            raise HTTPException(status_code=400, detail="Тип или категория неверны")
        th = int(body.get("threshold") or 0)
        if th <= 0:
            raise HTTPException(status_code=400, detail="Порог должен быть больше 0")
        code = (body.get("code") or "").strip() or f"r_{uuid.uuid4().hex[:6]}"
        dup = await db.mg_rewards.find_one({"code": code, "id": {"$ne": rid}})
        if dup:
            raise HTTPException(status_code=400, detail="Код награды уже занят")
        out = {"code": code, "type": typ, "category": cat, "threshold": th, "name": (body.get("name") or "").strip()[:80],
               "name_i18n": _i18n(body.get("name_i18n")), "description": (body.get("description") or "")[:300],
               "image_url": body.get("image_url") or "", "is_active": _bool(body.get("is_active")),
               "container_id": None, "booster_id": None, "frame_code": None, "nft_id": None}
        if not out["name"]:
            raise HTTPException(status_code=400, detail="Нужно название")
        link = {"container": ("container_id", "mg_containers"), "booster": ("booster_id", "mg_boosters"), "nft": ("nft_id", "mg_nfts")}.get(typ)
        if link:
            if not await db[link[1]].find_one({"id": body.get(link[0])}):
                raise HTTPException(status_code=400, detail="Не выбран объект награды")
            out[link[0]] = body.get(link[0])
        if typ == "frame":
            out["frame_code"] = (body.get("frame_code") or "neon").strip()[:30]
        return out

    @r.get("/api/admin/minigames/rewards")
    async def a_rewards(_=Depends(get_current_admin)):
        rows = await mr._all(db, "mg_rewards", {}, sort=[("category", 1), ("threshold", 1)])
        for x in rows:
            x["given"] = await db.mg_user_rewards.count_documents({"reward_id": x["id"]})
        return rows

    @r.post("/api/admin/minigames/rewards")
    async def a_reward_new(body: Dict[str, Any], _=Depends(get_current_admin)):
        doc = {"id": f"r_{uuid.uuid4().hex[:10]}", **await _clean_reward(body, None), "created_at": mr._iso()}
        await db.mg_rewards.insert_one(dict(doc))
        return doc

    @r.put("/api/admin/minigames/rewards/{rid}")
    async def a_reward_put(rid: str, body: Dict[str, Any], _=Depends(get_current_admin)):
        if not await db.mg_rewards.find_one({"id": rid}):
            raise HTTPException(status_code=404)
        await db.mg_rewards.update_one({"id": rid}, {"$set": await _clean_reward(body, rid)})
        return await mr._find(db, "mg_rewards", {"id": rid})

    @r.delete("/api/admin/minigames/rewards/{rid}")
    async def a_reward_off(rid: str, _=Depends(get_current_admin)):
        await db.mg_rewards.update_one({"id": rid}, {"$set": {"is_active": False}})
        return {"ok": True}

    @r.post("/api/admin/minigames/rewards/check-all")
    async def a_check_all(_=Depends(get_current_admin)):
        cfg = await get_config(db)
        cid = cfg["event_id"]
        ids = set(await db.minigame_points.distinct("user_id", {"campaign_id": cid}))
        ids |= set(u["id"] for u in await db.users.find({"mg_best_score": {"$gt": 0}}, {"_id": 0, "id": 1}).to_list(None))
        n = 0
        for uid in ids:
            n += len(await mr.check_thresholds(db, uid, cid))
        return {"players": len(ids), "given": n}

    # ───────────────────────── admin: containers ─────────────────────────
    def _clean_container(body: Dict) -> Dict:
        try:
            c = mr.validate_container({"rolls": body.get("rolls"), "rows": body.get("rows")})
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        name = (body.get("name") or "").strip()[:80]
        if not name:
            raise HTTPException(status_code=400, detail="Нужно название")
        return {"name": name, "name_i18n": _i18n(body.get("name_i18n")), "description": (body.get("description") or "")[:300],
                "image_url": body.get("image_url") or "", "is_active": _bool(body.get("is_active")), **c}

    @r.get("/api/admin/minigames/containers")
    async def a_containers(_=Depends(get_current_admin)):
        rows = await mr._all(db, "mg_containers", {})
        for c in rows:
            total = sum(float(x.get("weight") or 0) for x in c.get("rows") or []) or 1
            for x in c.get("rows") or []:
                x["chance"] = round(float(x.get("weight") or 0) * 100 / total, 2)
            c["given"] = await db.mg_user_containers.count_documents({"container_id": c["id"]})
            c["opened"] = await db.mg_user_containers.count_documents({"container_id": c["id"], "status": "opened"})
        return {"containers": rows, "resources": mr.produced_resources()}

    @r.post("/api/admin/minigames/containers")
    async def a_container_new(body: Dict[str, Any], _=Depends(get_current_admin)):
        doc = {"id": f"c_{uuid.uuid4().hex[:10]}", **_clean_container(body), "created_at": mr._iso()}
        await db.mg_containers.insert_one(dict(doc))
        return doc

    @r.put("/api/admin/minigames/containers/{cid}")
    async def a_container_put(cid: str, body: Dict[str, Any], _=Depends(get_current_admin)):
        if not await db.mg_containers.find_one({"id": cid}):
            raise HTTPException(status_code=404)
        await db.mg_containers.update_one({"id": cid}, {"$set": _clean_container(body)})
        return await mr._find(db, "mg_containers", {"id": cid})

    # ───────────────────────── admin: boosters ─────────────────────────
    def _clean_booster(body: Dict) -> Dict:
        eff = body.get("effect")
        if eff not in mr.BOOSTER_EFFECTS:
            raise HTTPException(status_code=400, detail="Эффект: auto_shift / warehouse_guard / xp_x2")
        h = int(body.get("duration_hours") or 0)
        if not 1 <= h <= 720:
            raise HTTPException(status_code=400, detail="Длительность: от 1 до 720 часов")
        name = (body.get("name") or "").strip()[:80]
        if not name:
            raise HTTPException(status_code=400, detail="Нужно название")
        return {"code": (body.get("code") or f"{eff}_{h}").strip()[:40], "name": name, "name_i18n": _i18n(body.get("name_i18n")),
                "description": (body.get("description") or "")[:300], "effect": eff, "duration_hours": h,
                "is_active": _bool(body.get("is_active"))}

    @r.get("/api/admin/minigames/boosters")
    async def a_boosters(_=Depends(get_current_admin)):
        rows = await mr._all(db, "mg_boosters", {})
        for b in rows:
            b["active_now"] = await db.mg_user_boosters.count_documents({"booster_id": b["id"], "status": "active"})
            b["available"] = await db.mg_user_boosters.count_documents({"booster_id": b["id"], "status": "available"})
        return rows

    @r.post("/api/admin/minigames/boosters")
    async def a_booster_new(body: Dict[str, Any], _=Depends(get_current_admin)):
        doc = {"id": f"b_{uuid.uuid4().hex[:10]}", **_clean_booster(body), "created_at": mr._iso()}
        if await db.mg_boosters.find_one({"code": doc["code"]}):
            raise HTTPException(status_code=400, detail="Код уже занят")
        await db.mg_boosters.insert_one(dict(doc))
        return doc

    @r.put("/api/admin/minigames/boosters/{bid}")
    async def a_booster_put(bid: str, body: Dict[str, Any], _=Depends(get_current_admin)):
        if not await db.mg_boosters.find_one({"id": bid}):
            raise HTTPException(status_code=404)
        clean = _clean_booster(body)
        if await db.mg_boosters.find_one({"code": clean["code"], "id": {"$ne": bid}}):
            raise HTTPException(status_code=400, detail="Код уже занят")
        await db.mg_boosters.update_one({"id": bid}, {"$set": clean})
        return await mr._find(db, "mg_boosters", {"id": bid})

    # ───────────────────────── admin: NFT definitions + warehouse ─────────────────────────
    async def _nft_with_stats(n: Dict) -> Dict:
        items = await mr._all(db, "mg_nft_items", {"nft_id": n["id"]})
        grants = await mr._all(db, "mg_nft_grants", {"nft_id": n["id"]})
        return {**n, "stats": mr.nft_stats_doc(n, items, grants)}

    @r.get("/api/admin/minigames/nfts")
    async def a_nfts(_=Depends(get_current_admin)):
        out = [await _nft_with_stats(n) for n in await mr._all(db, "mg_nfts", {})]
        st = await mr.nft_settings(db)
        wallet = None
        try:
            import nft_sender
            await nft_sender.load_mnemonic(db)
            wallet = await nft_sender.wallet_state(st["network"])
        except Exception as e:
            wallet = {"error": str(e)[:200]}
        queue = {s: await db.mg_nft_grants.count_documents({"status": s}) for s in
                 ("waiting_stock", "reserved", "sending", "delivered", "failed", )}
        return {"nfts": out, "settings": st, "wallet": wallet, "queue": queue}

    def _clean_nft(body: Dict, granted: int = 0, loaded: int = 0) -> Dict:
        kind = body.get("kind")
        if kind not in mr.NFT_KINDS:
            raise HTTPException(status_code=400, detail="Тип: tradable (передаваемый) или sbt")
        supply = int(body.get("supply_total") or 0)
        if supply < 1:
            raise HTTPException(status_code=400, detail="Тираж должен быть не меньше 1")
        if supply < max(granted, loaded):
            raise HTTPException(status_code=400, detail=f"Тираж не может быть меньше уже выданных ({granted}) или загруженных ({loaded})")
        name = (body.get("name") or "").strip()[:80]
        if not name:
            raise HTTPException(status_code=400, detail="Нужно название")
        attrs = [a for a in (body.get("attributes") or []) if isinstance(a, dict) and a.get("trait_type")][:20]
        return {"name": name, "kind": kind, "supply_total": supply, "description": (body.get("description") or "")[:500],
                "image_url": body.get("image_url") or "", "collection_address": (body.get("collection_address") or "").strip(),
                "content_template": (body.get("content_template") or "{nft_id}/{index}.json").strip(),
                "attributes": [{"trait_type": str(a["trait_type"])[:40], "value": str(a.get("value", ""))[:60]} for a in attrs],
                "low_stock_alert": max(0, int(body.get("low_stock_alert") or 10)), "is_active": _bool(body.get("is_active"))}

    @r.post("/api/admin/minigames/nfts")
    async def a_nft_new(body: Dict[str, Any], _=Depends(get_current_admin)):
        doc = {"id": f"n_{uuid.uuid4().hex[:10]}", **_clean_nft(body), "granted": 0, "next_index": 0, "created_at": mr._iso()}
        await db.mg_nfts.insert_one(dict(doc))
        return doc

    @r.put("/api/admin/minigames/nfts/{nid}")
    async def a_nft_put(nid: str, body: Dict[str, Any], _=Depends(get_current_admin)):
        n = await mr._find(db, "mg_nfts", {"id": nid})
        if not n:
            raise HTTPException(status_code=404)
        loaded = await db.mg_nft_items.count_documents({"nft_id": nid, "kind": {"$ne": "sbt"}})
        clean = _clean_nft(body, int(n.get("granted") or 0), loaded)
        if clean["kind"] != n.get("kind") and (int(n.get("granted") or 0) or loaded):
            raise HTTPException(status_code=400, detail="Тип нельзя менять после выдачи или загрузки")
        await db.mg_nfts.update_one({"id": nid}, {"$set": clean})
        await mr.assign_waiting(db)
        return await _nft_with_stats(await mr._find(db, "mg_nfts", {"id": nid}))

    @r.get("/api/admin/minigames/nfts/{nid}/items")
    async def a_nft_items(nid: str, _=Depends(get_current_admin)):
        items = await mr._all(db, "mg_nft_items", {"nft_id": nid}, sort=[("created_at", -1)], limit=500)
        uids = list({i["user_id"] for i in items if i.get("user_id")})
        names = {u["id"]: u.get("username") for u in await db.users.find({"id": {"$in": uids}}, {"_id": 0, "id": 1, "username": 1}).to_list(None)}
        for i in items:
            i["username"] = names.get(i.get("user_id"))
        return items

    async def _add_items(nid: str, found: list) -> Dict:
        n = await mr._find(db, "mg_nfts", {"id": nid})
        if not n or n.get("kind") != "tradable":
            raise HTTPException(status_code=400, detail="Импорт — только для передаваемых NFT")
        loaded = await db.mg_nft_items.count_documents({"nft_id": nid})
        room = int(n["supply_total"]) - loaded
        added, skipped = 0, 0
        for it in found:
            if added >= room:
                skipped += 1
                continue
            addr = it.get("nft_address")
            if not addr or await db.mg_nft_items.find_one({"nft_address": addr}):
                skipped += 1
                continue
            try:
                await db.mg_nft_items.insert_one({"id": str(uuid.uuid4()), "nft_id": nid, "kind": "tradable", "nft_address": addr,
                                                  "index": it.get("index"), "name": it.get("name") or n["name"],
                                                  "image_url": it.get("image_url") or n.get("image_url"), "status": "free",
                                                  "user_id": None, "grant_id": None, "created_at": mr._iso()})
                added += 1
            except Exception:
                skipped += 1
        assigned = await mr.assign_waiting(db)
        await mr._low_stock_check(db, nid)
        loaded += added
        return {"added": added, "skipped": skipped, "loaded": loaded, "supply_total": n["supply_total"],
                "note": f"загружено {loaded} из тиража {n['supply_total']}", "assigned_to_waiting": assigned}

    @r.post("/api/admin/minigames/nfts/{nid}/import")
    async def a_nft_import(nid: str, body: Dict[str, Any], _=Depends(get_current_admin)):
        """{collection_address} — all NFTs of the collection on the project wallet; or {nft_address} — one NFT."""
        import nft_sender
        st = await mr.nft_settings(db)
        await nft_sender.load_mnemonic(db)
        try:
            if body.get("nft_address"):
                it = await nft_sender.single_item(st["network"], body["nft_address"].strip())
                if not it:
                    raise HTTPException(status_code=404, detail="NFT не найден в сети")
                _w, wallet = nft_sender.project_wallet(st["network"])
                if nft_sender.raw(it.get("owner") or "") != nft_sender.raw(wallet):
                    raise HTTPException(status_code=400, detail="Этот NFT не на кошельке проекта")
                found = [it]
            elif body.get("collection_address"):
                found = await nft_sender.collection_items_on_wallet(st["network"], body["collection_address"].strip())
            else:
                raise HTTPException(status_code=400, detail="Укажите адрес коллекции или NFT")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Сеть TON недоступна: {str(e)[:200]}")
        return await _add_items(nid, found)

    @r.post("/api/admin/minigames/nft-grants/{gid}/retry")
    async def a_retry(gid: str, _=Depends(get_current_admin)):
        g = await mr._find(db, "mg_nft_grants", {"id": gid})
        if not g or g.get("status") != "failed":
            raise HTTPException(status_code=400, detail="Повторить можно только выдачу с ошибкой")
        await db.mg_nft_grants.update_one({"id": gid, "status": "failed"},
                                          {"$set": {"status": "reserved", "attempts": 0, "next_try_at": None, "error": None}})
        return {"ok": True}

    @r.get("/api/admin/minigames/nft-grants")
    async def a_grants(status: Optional[str] = None, _=Depends(get_current_admin)):
        q = {"status": status} if status else {}
        rows = await mr._all(db, "mg_nft_grants", q, sort=[("created_at", -1)], limit=300)
        uids = list({g["user_id"] for g in rows})
        names = {u["id"]: u.get("username") for u in await db.users.find({"id": {"$in": uids}}, {"_id": 0, "id": 1, "username": 1}).to_list(None)}
        nfts = {n["id"]: n.get("name") for n in await mr._all(db, "mg_nfts", {})}
        for g in rows:
            g["username"], g["nft_name"] = names.get(g["user_id"]), nfts.get(g["nft_id"])
        return rows

    @r.put("/api/admin/minigames/nft-settings")
    async def a_nft_settings(body: Dict[str, Any], _=Depends(get_current_admin)):
        upd = {}
        if "network" in body:
            if body["network"] not in ("testnet", "mainnet"):
                raise HTTPException(status_code=400, detail="Сеть: testnet или mainnet")
            upd["network"] = body["network"]
        if "sending_enabled" in body:
            upd["sending_enabled"] = bool(body["sending_enabled"])
        if "meta_base_url" in body:
            upd["meta_base_url"] = str(body["meta_base_url"] or "")[:200]
        await db.admin_settings.update_one({"type": "minigame_nft"}, {"$set": {"type": "minigame_nft", **upd}}, upsert=True)
        return await mr.nft_settings(db)

    # ───────────────────────── admin: puzzles ─────────────────────────
    async def _cut_puzzle(pid: str, image_url: str) -> bool:
        """Cut the picture into 9 pieces 3×3 (served one by one, only the pieces a player has)."""
        from PIL import Image
        name = (image_url or "").rsplit("/", 1)[-1]
        src = img_dir() / name
        if not name or not src.exists():
            return False
        im = Image.open(src).convert("RGBA")
        side = min(im.size)
        im = im.crop(((im.width - side) // 2, (im.height - side) // 2, (im.width - side) // 2 + side, (im.height - side) // 2 + side))
        im = im.resize((600, 600))
        for n in range(1, 10):
            row, col = (n - 1) // 3, (n - 1) % 3
            im.crop((col * 200, row * 200, col * 200 + 200, row * 200 + 200)).save(img_dir() / f"puzzle_{pid}_{n}.webp", "WEBP", quality=88)
        return True

    async def _clean_puzzle(body: Dict) -> Dict:
        name = (body.get("name") or "").strip()[:80]
        if not name:
            raise HTTPException(status_code=400, detail="Нужно название")
        if not await db.mg_nfts.find_one({"id": body.get("nft_id")}):
            raise HTTPException(status_code=400, detail="Выберите NFT для собравшего")
        return {"name": name, "name_i18n": _i18n(body.get("name_i18n")), "nft_id": body["nft_id"],
                "image_url": body.get("image_url") or "", "repeatable": bool(body.get("repeatable", False)),
                "is_active": _bool(body.get("is_active"))}

    @r.get("/api/admin/minigames/puzzles")
    async def a_puzzles(_=Depends(get_current_admin)):
        rows = await mr._all(db, "mg_puzzles", {})
        for p in rows:
            p["collecting"] = await db.mg_user_puzzles.count_documents({"puzzle_id": p["id"], "status": {"$in": ["collecting", "complete"]}})
            p["assembled"] = await db.mg_user_puzzles.count_documents({"puzzle_id": p["id"], "status": "assembled"})
        return rows

    @r.post("/api/admin/minigames/puzzles")
    async def a_puzzle_new(body: Dict[str, Any], _=Depends(get_current_admin)):
        pid = f"p_{uuid.uuid4().hex[:10]}"
        doc = {"id": pid, **await _clean_puzzle(body), "created_at": mr._iso()}
        doc["has_pieces"] = await _cut_puzzle(pid, doc["image_url"])
        await db.mg_puzzles.insert_one(dict(doc))
        return doc

    @r.put("/api/admin/minigames/puzzles/{pid}")
    async def a_puzzle_put(pid: str, body: Dict[str, Any], _=Depends(get_current_admin)):
        old = await mr._find(db, "mg_puzzles", {"id": pid})
        if not old:
            raise HTTPException(status_code=404)
        clean = await _clean_puzzle(body)
        if clean["image_url"] != old.get("image_url") or not old.get("has_pieces"):
            clean["has_pieces"] = await _cut_puzzle(pid, clean["image_url"])
        await db.mg_puzzles.update_one({"id": pid}, {"$set": clean})
        return await mr._find(db, "mg_puzzles", {"id": pid})

    # ───────────────────────── admin: players ─────────────────────────
    @r.get("/api/admin/minigames/players")
    async def a_players(q: str = "", _=Depends(get_current_admin)):
        cfg = await get_config(db)
        if q.strip():
            rx = {"$regex": re.escape(q.strip()), "$options": "i"}
            users = await db.users.find({"$or": [{"username": rx}, {"id": q.strip()}]},
                                        {"_id": 0, "id": 1, "username": 1, "mg_best_score": 1}).limit(30).to_list(30)
        else:
            pts = await db.minigame_points.find({"campaign_id": cfg["event_id"]}, {"_id": 0}).sort("points", -1).limit(30).to_list(30)
            users = await db.users.find({"id": {"$in": [p["user_id"] for p in pts]}}, {"_id": 0, "id": 1, "username": 1, "mg_best_score": 1}).to_list(None)
        for u in users:
            u["campaign_points"] = await mr.campaign_points(db, u["id"], cfg["event_id"])
        return sorted(users, key=lambda u: -u["campaign_points"])

    @r.get("/api/admin/minigames/players/{uid}")
    async def a_player(uid: str, _=Depends(get_current_admin)):
        cfg = await get_config(db)
        u = await db.users.find_one({"id": uid}, {"_id": 0, "id": 1, "username": 1, "wallet_address": 1, "mg_best_score": 1})
        if not u:
            raise HTTPException(status_code=404)
        games = await db.minigame_sessions.find({"user_id": uid, "status": "done"},
                                                {"_id": 0, "actions": 0}).sort("finished_at", -1).limit(30).to_list(30)
        return {"user": u, "rewards": await mr.my_rewards(db, uid, cfg), "games": games,
                "anomalies": await mr._all(db, "mg_anomalies", {"user_id": uid}, sort=[("created_at", -1)], limit=50)}

    @r.post("/api/admin/minigames/players/{uid}/grant")
    async def a_grant(uid: str, body: Dict[str, Any], _=Depends(get_current_admin)):
        if not await db.users.find_one({"id": uid}):
            raise HTTPException(status_code=404)
        kind, ref = body.get("kind"), body.get("ref_id")
        ref_tag = f"admin:{uuid.uuid4().hex[:8]}"
        if kind == "reward":
            rw = await mr._find(db, "mg_rewards", {"id": ref})
            if not rw:
                raise HTTPException(status_code=400, detail="Нет такой награды")
            got = await mr.grant_reward(db, uid, rw, ref_tag, source="admin")
        elif kind == "container":
            got = await mr.grant_container(db, uid, ref, "admin", ref_tag)
        elif kind == "booster":
            got = await mr.grant_booster(db, uid, ref, "admin", ref_tag)
        elif kind == "nft":
            got = await mr.grant_nft(db, uid, ref, "admin", ref_tag)
            if got is None:
                raise HTTPException(status_code=400, detail="Тираж этого NFT исчерпан")
        else:
            raise HTTPException(status_code=400, detail="Что выдать: reward / container / booster / nft")
        if not got:
            raise HTTPException(status_code=400, detail="Не выдано (объект не найден)")
        return {"ok": True}

    @r.post("/api/admin/minigames/players/{uid}/reset")
    async def a_reset(uid: str, body: Dict[str, Any], _=Depends(get_current_admin)):
        what = body.get("what")
        if not body.get("confirm"):
            raise HTTPException(status_code=400, detail="Нужно подтверждение")
        if what == "points":
            cfg = await get_config(db)
            await db.minigame_points.delete_one({"campaign_id": cfg["event_id"], "user_id": uid})
        elif what == "best":
            await db.users.update_one({"id": uid}, {"$set": {"mg_best_score": 0}})
        else:
            raise HTTPException(status_code=400, detail="Что сбросить: points / best")
        return {"ok": True}

    # ───────────────────────── admin: statistics + anomalies ─────────────────────────
    @r.get("/api/admin/minigames/reward-stats")
    async def a_reward_stats(_=Depends(get_current_admin)):
        cfg = await get_config(db)
        rewards = {r_["id"]: r_ for r_ in await mr._all(db, "mg_rewards", {})}
        by_type: Dict[str, int] = {}
        for ur in await mr._all(db, "mg_user_rewards", {}):
            t = (rewards.get(ur["reward_id"]) or {}).get("type") or "?"
            by_type[t] = by_type.get(t, 0) + 1
        res_total: Dict[str, int] = {}
        res_campaign: Dict[str, int] = {}
        pieces = 0
        start = cfg.get("starts_at") or ""
        for uc in await mr._all(db, "mg_user_containers", {"status": "opened"}):
            for x in uc.get("results") or []:
                if x.get("kind") == "resource":
                    res_total[x["resource"]] = res_total.get(x["resource"], 0) + int(x["amount"])
                    if (uc.get("opened_at") or "") >= start:
                        res_campaign[x["resource"]] = res_campaign.get(x["resource"], 0) + int(x["amount"])
                elif x.get("kind") == "puzzle":
                    pieces += 1
        top_points = (await mr.leaderboard(db, cfg["event_id"], limit=10))["rows"]
        top_best = await db.users.find({"mg_best_score": {"$gt": 0}}, {"_id": 0, "id": 1, "username": 1, "mg_best_score": 1}) \
            .sort("mg_best_score", -1).limit(10).to_list(10)
        return {"rewards_by_type": by_type,
                "containers": {"given": await db.mg_user_containers.count_documents({}),
                               "opened": await db.mg_user_containers.count_documents({"status": "opened"}),
                               "game_chests_today": await db.mg_user_containers.count_documents({"source": "game", "day": mr.msk_day()})},
                "resources_total": res_total, "resources_campaign": res_campaign, "puzzle_pieces": pieces,
                "boosters_active": await db.mg_user_boosters.count_documents({"status": "active"}),
                "nft": {s: await db.mg_nft_grants.count_documents({"status": s}) for s in ("waiting_stock", "reserved", "sending", "delivered", "failed")},
                "top_points": top_points, "top_best": top_best}

    @r.get("/api/admin/minigames/anomalies")
    async def a_anomalies(user: str = "", reason: str = "", _=Depends(get_current_admin)):
        q: Dict[str, Any] = {}
        if user:
            q["user_id"] = user
        if reason:
            q["reason"] = reason
        rows = await mr._all(db, "mg_anomalies", q, sort=[("created_at", -1)], limit=300)
        uids = list({a["user_id"] for a in rows})
        names = {u["id"]: u.get("username") for u in await db.users.find({"id": {"$in": uids}}, {"_id": 0, "id": 1, "username": 1}).to_list(None)}
        for a in rows:
            a["username"] = names.get(a["user_id"])
        return rows

    return r
