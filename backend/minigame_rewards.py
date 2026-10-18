"""Rewards of the «Сортировщик» promotion: thresholds, chests, NFT puzzles, boosters, the NFT warehouse.

Everything is decided on the server; every grant happens exactly once (unique indexes + atomic updates).

Collections
    minigame_points      {campaign_id, user_id, points, updated_at}            points of the CURRENT campaign
    mg_rewards           threshold rewards (category points | best), type frame | container | booster | nft
    mg_user_rewards      {user_id, reward_id, campaign_id}  unique  — a threshold reward given once
    mg_containers        chests: rolls 1..5, rows [{kind: resource, resource, min, max, weight} | {kind: puzzle, puzzle_id, weight}]
    mg_user_containers   a chest of a player: unopened -> opened, source game | threshold | leaderboard | admin, day (MSK)
    mg_chest_days        {user_id, day, n}  — «not more than N chests a day», counted atomically
    mg_boosters          booster templates: effect auto_shift | warehouse_guard | xp_x2, duration_hours
    mg_user_boosters     available -> active -> expired
    mg_nfts              NFT definitions: kind tradable | sbt, supply_total (hard limit), granted (counter)
    mg_nft_items         the warehouse: tradable NFTs imported from the project wallet, SBT copies minted on send
    mg_nft_grants        an NFT promised to a player: waiting_stock -> reserved -> sending -> delivered | failed | sold_out
    mg_puzzles           a 3×3 picture; 9 pieces drop from chests; «Собрать» sends the puzzle's NFT
    mg_user_puzzles      {user_id, puzzle_id, pieces[1..9], status collecting | complete | assembled}
    mg_anomalies         anti-cheat journal
    mg_campaigns         finished campaigns with their report
Users get: mg_best_score (all time), profile_frame, xp_x2_until (+ the existing auto_shift_until / decay_protected_until).
"""
from __future__ import annotations

import logging
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

LANGS = ("en", "ru", "es", "zh", "fr", "de", "ja", "ko", "id")
REWARD_TYPES = ("container", "booster", "nft")          # the profile frame reward was removed
REWARD_CATEGORIES = ("points", "best")
BOOSTER_EFFECTS = {"auto_shift": "auto_shift_until", "warehouse_guard": "decay_protected_until", "xp_x2": "xp_x2_until"}
NFT_KINDS = ("tradable", "sbt")
GRANT_OPEN = ("waiting_stock", "reserved", "sending", "failed")
MAX_SEND_ATTEMPTS = 3
_rng = random.SystemRandom()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: Optional[datetime] = None) -> str:
    return (d or _now()).isoformat()


def _parse(s) -> Optional[datetime]:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _uid() -> str:
    return str(uuid.uuid4())


def msk_day() -> str:
    from core.timeutil import msk_today_str
    return msk_today_str()


def produced_resources() -> List[str]:
    """Resources that businesses really produce (tutorial items and direct TON profit excluded)."""
    from business_config import BUSINESSES
    out = []
    for b in BUSINESSES.values():
        p = b.get("produces")
        if p and p != "profit_ton" and not str(p).endswith("_tutorial") and p not in out:
            out.append(p)
    return out


def _clean(doc: Optional[Dict]) -> Optional[Dict]:
    if doc:
        doc.pop("_id", None)
    return doc


async def _find(db, coll: str, q: Dict, proj: Optional[Dict] = None) -> Optional[Dict]:
    return _clean(await db[coll].find_one(q, {"_id": 0, **(proj or {})} if proj else {"_id": 0}))


async def _all(db, coll: str, q: Dict, sort=None, limit: int = 0) -> List[Dict]:
    cur = db[coll].find(q, {"_id": 0})
    if sort:
        cur = cur.sort(sort)
    if limit:
        cur = cur.limit(limit)
    return await cur.to_list(None)


# ───────────────────────────── setup ─────────────────────────────
async def ensure_indexes(db) -> None:
    specs = [
        ("minigame_points", [("campaign_id", 1), ("user_id", 1)], True),
        ("minigame_points", [("campaign_id", 1), ("points", -1), ("updated_at", 1)], False),
        ("mg_rewards", [("code", 1)], True),
        ("mg_user_rewards", [("user_id", 1), ("reward_id", 1), ("campaign_id", 1)], True),
        ("mg_user_containers", [("user_id", 1), ("status", 1)], False),
        ("mg_user_containers", [("source", 1), ("source_ref", 1)], False),
        ("mg_chest_days", [("user_id", 1), ("day", 1)], True),
        ("mg_boosters", [("code", 1)], True),
        ("mg_user_boosters", [("user_id", 1), ("status", 1)], False),
        ("mg_nft_items", [("nft_id", 1), ("status", 1)], False),
        ("mg_nft_grants", [("source", 1), ("source_ref", 1)], True),
        ("mg_nft_grants", [("status", 1)], False),
        ("mg_user_puzzles", [("user_id", 1), ("puzzle_id", 1), ("round", 1)], True),
        ("mg_anomalies", [("created_at", -1)], False),
    ]
    for coll, keys, unique in specs:
        try:
            await db[coll].create_index(keys, unique=unique)
        except Exception as e:  # an index that can't be built must not stop the server
            logger.warning("mg index %s %s: %s", coll, keys, e)
    try:  # one NFT address can be on the warehouse only once (imported tradable items)
        await db.mg_nft_items.create_index([("nft_address", 1)], unique=True,
                                           partialFilterExpression={"nft_address": {"$type": "string"}})
    except Exception as e:
        logger.warning("mg index nft_address: %s", e)


def _i18n(*names: str) -> Dict[str, str]:
    return dict(zip(LANGS, names))


async def seed_defaults(db) -> Dict[str, int]:
    """The starting set from the spec — only into EMPTY collections, so admin edits are never overwritten."""
    made = {"boosters": 0, "containers": 0, "nfts": 0, "rewards": 0}
    now = _iso()
    if not await db.mg_boosters.count_documents({}):
        await db.mg_boosters.insert_many([
            {"id": "b_auto_shift_24", "code": "auto_shift_24", "name": "Автозапуск смен 24 ч", "effect": "auto_shift", "duration_hours": 24,
             "name_i18n": _i18n("Auto shifts 24 h", "Автозапуск смен 24 ч", "Turnos automáticos 24 h", "自动班次 24 小时", "Équipes auto 24 h",
                                "Auto-Schichten 24 Std.", "自動シフト 24時間", "자동 교대 24시간", "Shift otomatis 24 jam"),
             "description": "Смены всех бизнесов перезапускаются сами", "is_active": True, "created_at": now},
            {"id": "b_xp_x2_12", "code": "xp_x2_12", "name": "×2 XP на 12 ч", "effect": "xp_x2", "duration_hours": 12,
             "name_i18n": _i18n("×2 XP for 12 h", "×2 XP на 12 ч", "×2 XP por 12 h", "双倍 XP 12 小时", "×2 XP pendant 12 h",
                                "×2 XP für 12 Std.", "XP×2 12時間", "XP ×2 12시간", "×2 XP selama 12 jam"),
             "description": "Весь XP в City Pass удваивается", "is_active": True, "created_at": now},
            {"id": "b_guard_24", "code": "warehouse_guard_24", "name": "Защита склада 24 ч", "effect": "warehouse_guard", "duration_hours": 24,
             "name_i18n": _i18n("Warehouse guard 24 h", "Защита склада 24 ч", "Protección del almacén 24 h", "仓库保护 24 小时",
                                "Protection d’entrepôt 24 h", "Lagerschutz 24 Std.", "倉庫保護 24時間", "창고 보호 24시간", "Perlindungan gudang 24 jam"),
             "description": "Склад не портится", "is_active": True, "created_at": now},
        ])
        made["boosters"] = 3
    if not await db.mg_containers.count_documents({}):
        await db.mg_containers.insert_one({
            "id": "c_sorter", "name": "Сундук Сортировщика",
            "name_i18n": _i18n("Sorter chest", "Сундук Сортировщика", "Cofre del Clasificador", "分拣员宝箱", "Coffre du Trieur",
                               "Sortierer-Truhe", "仕分け屋の宝箱", "분류기 상자", "Peti Penyortir"),
            "description": "Ресурсы бизнесов или кусочек пазла NFT", "image_url": "", "rolls": 2, "is_active": True, "created_at": now,
            "rows": [
                {"kind": "resource", "resource": "energy", "min": 20, "max": 60, "weight": 30},
                {"kind": "resource", "resource": "cu", "min": 20, "max": 60, "weight": 25},
                {"kind": "resource", "resource": "quartz", "min": 15, "max": 40, "weight": 20},
                {"kind": "resource", "resource": "chips", "min": 3, "max": 8, "weight": 10},
                {"kind": "resource", "resource": "logistics", "min": 3, "max": 8, "weight": 10},
                {"kind": "resource", "resource": "neuro_core", "min": 1, "max": 1, "weight": 5},
            ]})
        made["containers"] = 1
    if not await db.mg_nfts.count_documents({}):
        await db.mg_nfts.insert_many([
            {"id": "n_sorter_badge", "name": "Знак Сортировщика", "kind": "sbt", "supply_total": 1000, "granted": 0, "next_index": 0,
             "description": "Непередаваемый знак за 50 000 очков акции", "image_url": "", "collection_address": "",
             "content_template": "{nft_id}/{index}.json", "attributes": [], "low_stock_alert": 10, "is_active": True, "created_at": now},
            {"id": "n_sorter_master", "name": "Мастер сортировки", "kind": "sbt", "supply_total": 500, "granted": 0, "next_index": 0,
             "description": "Непередаваемый NFT за рекорд 3 500 очков", "image_url": "", "collection_address": "",
             "content_template": "{nft_id}/{index}.json", "attributes": [], "low_stock_alert": 10, "is_active": True, "created_at": now},
        ])
        made["nfts"] = 2
    if not await db.mg_rewards.count_documents({}):
        def rw(code, cat, th, typ, ru, names, **kw):
            return {"id": f"r_{code}", "code": code, "category": cat, "threshold": th, "type": typ, "name": ru, "name_i18n": names,
                    "description": "", "image_url": "", "is_active": True, "created_at": now,
                    "container_id": kw.get("container_id"), "booster_id": kw.get("booster_id"),
                    "frame_code": kw.get("frame_code"), "nft_id": kw.get("nft_id")}
        await db.mg_rewards.insert_many([
            rw("pts_chest", "points", 15000, "container", "Сундук Сортировщика", _i18n("Sorter chest", "Сундук Сортировщика",
               "Cofre del Clasificador", "分拣员宝箱", "Coffre du Trieur", "Sortierer-Truhe", "仕分け屋の宝箱", "분류기 상자", "Peti Penyortir"),
               container_id="c_sorter"),
            rw("pts_autoshift", "points", 30000, "booster", "Автозапуск смен 24 ч", _i18n("Auto shifts 24 h", "Автозапуск смен 24 ч",
               "Turnos automáticos 24 h", "自动班次 24 小时", "Équipes auto 24 h", "Auto-Schichten 24 Std.", "自動シフト 24時間", "자동 교대 24시간",
               "Shift otomatis 24 jam"), booster_id="b_auto_shift_24"),
            rw("pts_badge", "points", 50000, "nft", "NFT «Знак Сортировщика»", _i18n("NFT «Sorter badge»", "NFT «Знак Сортировщика»",
               "NFT «Insignia del Clasificador»", "NFT「分拣员徽章」", "NFT « Insigne du Trieur »", "NFT „Sortierer-Abzeichen“",
               "NFT「仕分け屋の証」", "NFT «분류기 배지»", "NFT «Lencana Penyortir»"), nft_id="n_sorter_badge"),
            rw("best_chest", "best", 1000, "container", "Сундук Сортировщика", _i18n("Sorter chest", "Сундук Сортировщика",
               "Cofre del Clasificador", "分拣员宝箱", "Coffre du Trieur", "Sortierer-Truhe", "仕分け屋の宝箱", "분류기 상자", "Peti Penyortir"),
               container_id="c_sorter"),
            rw("best_xp2", "best", 2000, "booster", "×2 XP на 12 ч", _i18n("×2 XP for 12 h", "×2 XP на 12 ч", "×2 XP por 12 h", "双倍 XP 12 小时",
               "×2 XP pendant 12 h", "×2 XP für 12 Std.", "XP×2 12時間", "XP ×2 12시간", "×2 XP selama 12 jam"), booster_id="b_xp_x2_12"),
            rw("best_master", "best", 3500, "nft", "NFT «Мастер сортировки»", _i18n("NFT «Sorting master»", "NFT «Мастер сортировки»",
               "NFT «Maestro clasificador»", "NFT「分拣大师」", "NFT « Maître du tri »", "NFT „Sortiermeister“", "NFT「仕分けマスター」",
               "NFT «분류 마스터»", "NFT «Master penyortir»"), nft_id="n_sorter_master"),
        ])
        made["rewards"] = 6
    # the profile-frame reward is gone: switch off any left in the database
    await db.mg_rewards.update_many({"type": "frame"}, {"$set": {"is_active": False}})
    return made


# ───────────────────────────── campaign points / best ─────────────────────────────
async def add_points(db, uid: str, campaign_id: str, points: int) -> int:
    if points <= 0:
        doc = await _find(db, "minigame_points", {"campaign_id": campaign_id, "user_id": uid})
        return int((doc or {}).get("points", 0))
    await db.minigame_points.update_one({"campaign_id": campaign_id, "user_id": uid},
                                        {"$inc": {"points": int(points)}, "$set": {"updated_at": _iso()},
                                         "$setOnInsert": {"campaign_id": campaign_id, "user_id": uid}}, upsert=True)
    doc = await _find(db, "minigame_points", {"campaign_id": campaign_id, "user_id": uid})
    return int((doc or {}).get("points", 0))


async def campaign_points(db, uid: str, campaign_id: str) -> int:
    doc = await _find(db, "minigame_points", {"campaign_id": campaign_id, "user_id": uid})
    return int((doc or {}).get("points", 0))


async def update_best(db, uid: str, score: int) -> Tuple[int, bool]:
    """All-time best score of one game (never reset). Returns (best, improved)."""
    r = await db.users.update_one({"id": uid, "$or": [{"mg_best_score": {"$lt": int(score)}}, {"mg_best_score": {"$exists": False}}]},
                                  {"$set": {"mg_best_score": int(score), "mg_best_at": _iso()}})
    u = await db.users.find_one({"id": uid}, {"_id": 0, "mg_best_score": 1}) or {}
    return int(u.get("mg_best_score") or 0), bool(r.modified_count)


# ───────────────────────────── boosters ─────────────────────────────
async def grant_booster(db, uid: str, booster_id: str, source: str, source_ref: str = "") -> Optional[Dict]:
    """A booster from the game is ACTIVATED AT ONCE. When 2 effects already run (core/effects.py), it goes to the
    player's boosters inventory (Resources → «Усилители») to be activated later."""
    b = await _find(db, "mg_boosters", {"id": booster_id})
    if not b:
        return None
    doc = {"id": _uid(), "user_id": uid, "booster_id": booster_id, "status": "available", "source": source, "source_ref": source_ref,
           "awarded_at": _iso(), "activated_at": None, "expires_at": None}
    await db.mg_user_boosters.insert_one(dict(doc))
    try:
        res = await activate_booster(db, uid, doc["id"])
        doc.update(status="active", expires_at=res["until"])
    except ValueError as e:
        if str(e) == "limit":
            key = f"{b['effect']}_{int(b.get('duration_hours') or 1)}h"
            await db.users.update_one({"id": uid}, {"$inc": {f"boosters.{key}": 1}})
            await db.mg_user_boosters.update_one({"id": doc["id"]}, {"$set": {"status": "stored", "inventory_key": key}})
            doc.update(status="stored", inventory_key=key)
    return doc


async def activate_booster(db, uid: str, user_booster_id: str) -> Dict:
    ub = await _find(db, "mg_user_boosters", {"id": user_booster_id, "user_id": uid})
    if not ub:
        raise ValueError("not_found")
    b = await _find(db, "mg_boosters", {"id": ub["booster_id"]})
    if not b or b.get("effect") not in BOOSTER_EFFECTS:
        raise ValueError("unknown_booster")
    now = _now()
    field = BOOSTER_EFFECTS[b["effect"]]
    u = await db.users.find_one({"id": uid}, {"_id": 0}) or {}
    from core.effects import can_activate
    if not can_activate(u, b["effect"], now):
        raise ValueError("limit")                        # not more than 2 effects at once
    claimed = await db.mg_user_boosters.update_one({"id": user_booster_id, "user_id": uid, "status": "available"},
                                                   {"$set": {"status": "active", "activated_at": _iso(now)}})
    if not claimed.modified_count:
        raise ValueError("not_available")
    base = max(now, _parse(u.get(field)) or now)                 # a running effect is EXTENDED, never reset
    until = base + timedelta(hours=int(b.get("duration_hours") or 1))
    await db.users.update_one({"id": uid}, {"$set": {field: _iso(until)}})
    await db.mg_user_boosters.update_one({"id": user_booster_id}, {"$set": {"expires_at": _iso(until)}})
    return {"ok": True, "effect": b["effect"], "until": _iso(until)}


async def expire_boosters(db, now: Optional[datetime] = None) -> int:
    now = now or _now()
    n = 0
    for ub in await _all(db, "mg_user_boosters", {"status": "active"}):
        t = _parse(ub.get("expires_at"))
        if t and t <= now:
            r = await db.mg_user_boosters.update_one({"id": ub["id"], "status": "active"}, {"$set": {"status": "expired"}})
            n += r.modified_count
    return n


def xp_multiplier(user_doc: Optional[Dict], now: Optional[datetime] = None) -> int:
    t = _parse((user_doc or {}).get("xp_x2_until"))
    return 2 if t and t > (now or _now()) else 1


# ───────────────────────────── NFT warehouse ─────────────────────────────
def nft_stats_doc(nft: Dict, items: List[Dict], grants: List[Dict]) -> Dict:
    by = lambda st: sum(1 for i in items if i.get("status") == st)
    supply = int(nft.get("supply_total") or 0)
    granted = int(nft.get("granted") or 0)
    out = {"supply_total": supply, "granted": granted, "left_to_grant": max(0, supply - granted),
           "loaded": len(items), "free": by("free"), "reserved": by("reserved"), "sending": by("sending"),
           "delivered": by("delivered"), "failed": by("failed"),
           "waiting_stock": sum(1 for g in grants if g.get("status") == "waiting_stock")}
    if nft.get("kind") == "sbt":                         # an SBT is minted on send: the «stock» is what's left of the supply
        out["free"] = max(0, supply - int(nft.get("next_index") or 0))
    return out


async def _assign_stock(db, grant: Dict) -> Dict:
    """Pin a concrete NFT of the warehouse to a waiting grant. Atomic: one NFT never goes to two players."""
    if grant.get("status") != "waiting_stock":
        return grant
    nft = await _find(db, "mg_nfts", {"id": grant["nft_id"]})
    if not nft:
        return grant
    item = None
    if nft.get("kind") == "sbt":
        for _ in range(5):                                # next_index is taken atomically, never above the supply
            cur = int((await _find(db, "mg_nfts", {"id": nft["id"]}) or {}).get("next_index") or 0)
            if cur >= int(nft.get("supply_total") or 0):
                break
            r = await db.mg_nfts.update_one({"id": nft["id"], "next_index": cur}, {"$inc": {"next_index": 1}})
            if r.modified_count:
                item = {"id": _uid(), "nft_id": nft["id"], "kind": "sbt", "index": cur, "nft_address": None,
                        "name": nft.get("name"), "image_url": nft.get("image_url"), "status": "reserved",
                        "user_id": grant["user_id"], "grant_id": grant["id"], "created_at": _iso()}
                await db.mg_nft_items.insert_one(dict(item))
                break
    else:
        item = await db.mg_nft_items.find_one_and_update(
            {"nft_id": nft["id"], "status": "free"},
            {"$set": {"status": "reserved", "user_id": grant["user_id"], "grant_id": grant["id"], "reserved_at": _iso()}})
        item = _clean(item)
    if not item:
        return grant
    await db.mg_nft_grants.update_one({"id": grant["id"], "status": "waiting_stock"},
                                      {"$set": {"status": "reserved", "item_id": item["id"], "reserved_at": _iso()}})
    return {**grant, "status": "reserved", "item_id": item["id"]}


async def grant_nft(db, uid: str, nft_id: str, source: str, source_ref: str) -> Optional[Dict]:
    """Promise one NFT of a definition to a player. Never above supply_total; idempotent per (source, source_ref).
    Returns the grant, or None when the supply is exhausted."""
    existing = await _find(db, "mg_nft_grants", {"source": source, "source_ref": source_ref})
    if existing:
        return existing
    nft = await _find(db, "mg_nfts", {"id": nft_id})
    if not nft:
        return None
    r = await db.mg_nfts.update_one({"id": nft_id, "granted": {"$lt": int(nft.get("supply_total") or 0)}}, {"$inc": {"granted": 1}})
    if not r.modified_count:
        return None                                       # the supply is the hard limit
    grant = {"id": _uid(), "user_id": uid, "nft_id": nft_id, "source": source, "source_ref": source_ref,
             "status": "waiting_stock", "item_id": None, "attempts": 0, "tx_hash": None, "nft_address": None,
             "created_at": _iso(), "delivered_at": None, "error": None}
    try:
        await db.mg_nft_grants.insert_one(dict(grant))
    except Exception:                                      # a concurrent duplicate: give the counter back
        await db.mg_nfts.update_one({"id": nft_id}, {"$inc": {"granted": -1}})
        return await _find(db, "mg_nft_grants", {"source": source, "source_ref": source_ref})
    grant = await _assign_stock(db, grant)
    await _low_stock_check(db, nft_id)
    return grant


async def assign_waiting(db) -> int:
    """After the admin adds NFTs, waiting grants get them (oldest first)."""
    n = 0
    for g in await _all(db, "mg_nft_grants", {"status": "waiting_stock"}, sort=[("created_at", 1)], limit=500):
        if (await _assign_stock(db, g)).get("status") == "reserved":
            n += 1
    return n


async def _low_stock_check(db, nft_id: str) -> None:
    try:
        nft = await _find(db, "mg_nfts", {"id": nft_id})
        if not nft:
            return
        items = await _all(db, "mg_nft_items", {"nft_id": nft_id})
        st = nft_stats_doc(nft, items, [])
        limit = int(nft.get("low_stock_alert") or 10)
        if st["free"] <= limit and st["left_to_grant"] > 0 and not nft.get("low_stock_notified"):
            await db.mg_nfts.update_one({"id": nft_id}, {"$set": {"low_stock_notified": True}})
            await notify_admin(db, f"⚠️ Склад NFT «{nft.get('name')}»: свободно {st['free']} (порог {limit}). Пополните склад в админке.")
        elif st["free"] > limit and nft.get("low_stock_notified"):
            await db.mg_nfts.update_one({"id": nft_id}, {"$set": {"low_stock_notified": False}})
    except Exception as e:
        logger.debug("low stock check: %s", e)


async def notify_admin(db, text: str) -> None:
    try:
        import os
        import httpx
        token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_ADMIN_ID")
        if token and chat:
            async with httpx.AsyncClient(timeout=10) as c:
                await c.post(f"https://api.telegram.org/bot{token}/sendMessage", data={"chat_id": chat, "text": text})
    except Exception as e:
        logger.warning("admin notify failed: %s", e)
    try:
        await db.admin_alerts.insert_one({"id": _uid(), "source": "minigames", "text": text, "created_at": _iso()})
    except Exception:
        pass


# ───────────────────────────── containers (chests) ─────────────────────────────
async def grant_container(db, uid: str, container_id: str, source: str, source_ref: str = "",
                          open_now: bool = True, notify: Optional[str] = "full") -> Optional[Dict]:
    """Give a chest and open it at once (chests are never left unopened). notify: "full" — in-app + Telegram
    (the player may not be looking), "app" — in-app only (the app shows the opening itself), None — nothing."""
    c = await _find(db, "mg_containers", {"id": container_id})
    if not c:
        return None
    doc = {"id": _uid(), "user_id": uid, "container_id": container_id, "status": "unopened", "source": source,
           "source_ref": source_ref, "day": msk_day(), "awarded_at": _iso(), "opened_at": None, "results": []}
    await db.mg_user_containers.insert_one(dict(doc))
    if open_now:
        doc = await auto_open(db, uid, doc, notify)
    return doc


async def auto_open(db, uid: str, uc: Dict, notify: Optional[str] = "full") -> Dict:
    """Open a chest now. No room in the warehouse → it waits (same roll) and opens by itself later
    (open_waiting_containers); the player is told once how many places to free."""
    from core import chest_notify as cn
    try:
        r = await open_container(db, uid, uc["id"])
        uc = {**uc, "status": "opened", "opened_at": _iso(), "results": r["results"]}
        if notify:
            cn.spawn(cn.notify_opened(db, uid, uc, r["results"], telegram=(notify == "full")))
    except NoSpace as e:
        uc = {**uc, "waiting_space": e.need}
        first = await db.mg_user_containers.update_one({"id": uc["id"], "space_notified": {"$ne": True}},
                                                       {"$set": {"waiting_space": e.need, "space_notified": True}})
        if notify and first.modified_count:
            cn.spawn(cn.notify_no_space(db, uid, uc, e.need, telegram=(notify == "full")))
    except ValueError:
        pass
    return uc


async def open_waiting_containers(db, limit: int = 300) -> Dict[str, int]:
    """Background job: open every chest still closed (no room before; chests from older versions)."""
    done = waiting = 0
    for uc in await _all(db, "mg_user_containers", {"status": "unopened"}, sort=[("awarded_at", 1)], limit=limit):
        r = await auto_open(db, uc["user_id"], uc, "full")
        if r.get("status") == "opened":
            done += 1
        else:
            waiting += 1
    return {"opened": done, "waiting": waiting}


async def public_chest(db, uc: Dict) -> Dict:
    """A given chest for the app: its name / picture and what dropped (the app plays the opening)."""
    c = await _find(db, "mg_containers", {"id": uc.get("container_id")}) or {}
    return {"id": uc.get("id"), "container_id": uc.get("container_id"), "name": c.get("name"), "name_i18n": c.get("name_i18n"),
            "image_url": c.get("image_url"), "status": uc.get("status"), "results": uc.get("results") or [],
            "waiting_space": uc.get("waiting_space")}


async def chests_today(db, uid: str) -> int:
    d = await _find(db, "mg_chest_days", {"user_id": uid, "day": msk_day()})
    return int((d or {}).get("n", 0))


async def take_chest_slot(db, uid: str, per_day: int) -> bool:
    """Atomically count one more chest today; False when all `per_day` are taken (MSK day)."""
    day = msk_day()
    await db.mg_chest_days.update_one({"user_id": uid, "day": day}, {"$setOnInsert": {"user_id": uid, "day": day, "n": 0}}, upsert=True)
    r = await db.mg_chest_days.update_one({"user_id": uid, "day": day, "n": {"$lt": int(per_day)}}, {"$inc": {"n": 1}})
    return bool(r.modified_count)


async def game_chest(db, uid: str, session_id: str, stars: int, cfg: Dict, notify: Optional[str] = "app") -> Dict:
    """A chest for one game: only with ★★+ and not more than chests_per_day per MSK day."""
    per_day = int(cfg.get("chests_per_day") or 0)
    cid = cfg.get("chest_container_id") or ""
    out = {"given": False, "reason": None, "user_container_id": None, "container_id": cid}
    if not cid or per_day <= 0 or not await _find(db, "mg_containers", {"id": cid, "is_active": True}):
        out["reason"] = "disabled"
    elif stars < int(cfg.get("chest_min_stars") or 2):
        out["reason"] = "low_stars"
    elif not await take_chest_slot(db, uid, per_day):
        out["reason"] = "daily_limit"
    else:
        uc = await grant_container(db, uid, cid, "game", session_id, notify=notify)
        out.update(given=True, user_container_id=uc["id"], opened=uc.get("status") == "opened", chest=await public_chest(db, uc))
    out["chests_today"] = await chests_today(db, uid)
    out["chests_per_day"] = per_day
    return out


def _roll_index(weights: List[float]) -> int:
    total = sum(weights)
    x = _rng.random() * total
    acc = 0.0
    for i, w in enumerate(weights):
        acc += w
        if x < acc:
            return i
    return len(weights) - 1


async def _puzzle_open_for(db, uid: str, puzzle: Dict) -> Tuple[bool, Optional[Dict]]:
    """Can a piece of this puzzle drop for the player? Returns (ok, the player's current puzzle doc)."""
    if not puzzle or not puzzle.get("is_active"):
        return False, None
    mine = await db.mg_user_puzzles.find({"user_id": uid, "puzzle_id": puzzle["id"]}, {"_id": 0}).sort("round", -1).to_list(1)
    cur = mine[0] if mine else None
    if cur and cur.get("status") == "collecting":
        return True, cur                                  # a started puzzle always finishes
    if cur and not puzzle.get("repeatable"):
        return False, cur                                 # complete / assembled: once
    if cur and cur.get("status") == "complete":
        return False, cur                                 # repeatable: first assemble the complete one
    nft = await _find(db, "mg_nfts", {"id": puzzle.get("nft_id")})
    if not nft:
        return False, cur
    left = int(nft.get("supply_total") or 0) - int(nft.get("granted") or 0)
    started = await db.mg_user_puzzles.count_documents({"puzzle_id": puzzle["id"], "status": {"$in": ["collecting", "complete"]}})
    return left > started, cur                            # every started player is guaranteed an NFT


async def _add_piece(db, uid: str, puzzle: Dict, cur: Optional[Dict]) -> Optional[Dict]:
    if cur is None or cur.get("status") != "collecting":
        rnd = (int(cur.get("round", 0)) + 1) if cur else 0
        cur = {"id": _uid(), "user_id": uid, "puzzle_id": puzzle["id"], "round": rnd, "pieces": [], "status": "collecting",
               "started_at": _iso(), "assembled_at": None, "grant_id": None}
        try:
            await db.mg_user_puzzles.insert_one(dict(cur))
        except Exception:
            cur = await _find(db, "mg_user_puzzles", {"user_id": uid, "puzzle_id": puzzle["id"], "round": rnd})
    for _ in range(9):
        fresh = await _find(db, "mg_user_puzzles", {"id": cur["id"]})
        missing = [p for p in range(1, 10) if p not in (fresh.get("pieces") or [])]
        if not missing:
            return None
        piece = _rng.choice(missing)                      # never a duplicate: only a missing piece
        r = await db.mg_user_puzzles.update_one({"id": cur["id"], "pieces": {"$ne": piece}}, {"$push": {"pieces": piece}})
        if r.modified_count:
            if len(missing) == 1:
                await db.mg_user_puzzles.update_one({"id": cur["id"]}, {"$set": {"status": "complete", "completed_at": _iso()}})
            return {"kind": "puzzle", "puzzle_id": puzzle["id"], "piece": piece, "have": 10 - len(missing)}
    return None


def validate_container(c: Dict) -> Dict:
    produced = set(produced_resources())
    rolls = int(c.get("rolls") or 1)
    if not 1 <= rolls <= 5:
        raise ValueError("Бросков: от 1 до 5")
    rows, total = [], 0.0
    for r in c.get("rows") or []:
        kind = r.get("kind") or "resource"
        w = float(r.get("weight") or 0)
        if w < 0:
            raise ValueError("Вес не может быть отрицательным")
        if kind == "resource":
            res = r.get("resource")
            if res not in produced:
                raise ValueError(f"«{res}» не производится бизнесами")
            lo, hi = int(r.get("min") or 0), int(r.get("max") or 0)
            if lo < 1 or hi < lo:
                raise ValueError(f"{res}: min ≥ 1 и max ≥ min")
            rows.append({"kind": "resource", "resource": res, "min": lo, "max": hi, "weight": w})
        elif kind == "puzzle":
            if not r.get("puzzle_id"):
                raise ValueError("Не выбран пазл")
            rows.append({"kind": "puzzle", "puzzle_id": r["puzzle_id"], "weight": w})
        else:
            raise ValueError(f"Неизвестный тип строки {kind}")
        total += w
    if total <= 0:
        raise ValueError("Сумма весов должна быть больше 0")
    return {**c, "rolls": rolls, "rows": rows}


async def open_container(db, uid: str, user_container_id: str) -> Dict:
    uc = await _find(db, "mg_user_containers", {"id": user_container_id})
    if not uc or uc.get("user_id") != uid:
        raise ValueError("not_found")
    if uc.get("status") != "unopened":
        raise ValueError("already_opened")
    cont = await _find(db, "mg_containers", {"id": uc["container_id"]}) or {}
    produced = set(produced_resources())
    rows = [r for r in (cont.get("rows") or []) if float(r.get("weight") or 0) > 0 and
            (r.get("kind") == "puzzle" or r.get("resource") in produced)]
    # roll ONCE: if the warehouse is full the same result waits (no rerolling by keeping the warehouse full)
    plan = uc.get("plan")
    if plan is None:
        plan = []
        puzzles = {r["puzzle_id"]: await _find(db, "mg_puzzles", {"id": r["puzzle_id"]}) for r in rows if r.get("kind") == "puzzle"}
        for _ in range(int(cont.get("rolls") or 1)):
            cand = []
            for r in rows:
                if r.get("kind") == "puzzle":
                    ok, _cur = await _puzzle_open_for(db, uid, puzzles.get(r["puzzle_id"]))
                    taken = sum(1 for p in plan if p.get("puzzle_id") == r["puzzle_id"])
                    if not ok or taken >= 9:
                        continue                          # its weight goes to the other rows
                cand.append(r)
            if not cand:
                break
            r = cand[_roll_index([float(x["weight"]) for x in cand])]
            if r.get("kind") == "puzzle":
                plan.append({"kind": "puzzle", "puzzle_id": r["puzzle_id"]})
            else:
                plan.append({"kind": "resource", "resource": r["resource"], "amount": _rng.randint(int(r["min"]), int(r["max"]))})
        await db.mg_user_containers.update_one({"id": uc["id"], "status": "unopened"}, {"$set": {"plan": plan}})
    res_sum: Dict[str, int] = {}
    for p in plan:
        if p["kind"] == "resource":
            res_sum[p["resource"]] = res_sum.get(p["resource"], 0) + int(p["amount"])
    if res_sum:
        from core import warehouse as wh
        user = await db.users.find_one({"id": uid}, {"_id": 0}) or {}
        state = await wh.user_warehouse(db, user)
        need = wh.used_by_resources(res_sum)
        if need > state["free"]:
            raise NoSpace(need - state["free"])
    claimed = await db.mg_user_containers.update_one({"id": uc["id"], "status": "unopened"},
                                                     {"$set": {"status": "opened", "opened_at": _iso()}})
    if not claimed.modified_count:
        raise ValueError("already_opened")
    results: List[Dict] = []
    if res_sum:
        await db.users.update_one({"id": uid}, {"$inc": {f"resources.{k}": v for k, v in res_sum.items()}})
    for p in plan:
        if p["kind"] == "resource":
            results.append({"kind": "resource", "resource": p["resource"], "amount": int(p["amount"]),
                            # the picture of the reward: the resource itself (frontend/public/sprites/resources/<id>.webp)
                            "image_url": resource_image(p["resource"])})
        else:
            puzzle = await _find(db, "mg_puzzles", {"id": p["puzzle_id"]})
            ok, cur = await _puzzle_open_for(db, uid, puzzle)
            got = await _add_piece(db, uid, puzzle, cur) if ok else None
            if got:
                got["name"], got["name_i18n"] = puzzle.get("name"), puzzle.get("name_i18n")
                # the picture of the piece that dropped (cut by the admin upload), not an emoji
                got["image_url"] = f"/api/minigames/img/puzzle_{puzzle['id']}_{got['piece']}.webp" if puzzle.get("has_pieces") else None
                results.append(got)
    await db.mg_user_containers.update_one({"id": uc["id"]}, {"$set": {"results": results}})
    await db.transactions.insert_one({"id": _uid(), "tx_type": "container_open", "user_id": uid, "amount": 0, "amount_ton": 0,
                                      "status": "completed", "container_id": uc["container_id"], "results": results,
                                      "created_at": _iso()})
    return {"ok": True, "results": results, "container_id": uc["container_id"]}


def resource_image(rid: str) -> Optional[str]:
    """Picture of a resource (3D icon, frontend/public/sprites/resources/<id>.webp); None if there is none."""
    return f"/sprites/resources/{rid}.webp" if rid in set(produced_resources()) else None


class NoSpace(Exception):
    def __init__(self, need: int):
        super().__init__(f"no_space:{need}")
        self.need = int(need)


# ───────────────────────────── puzzles ─────────────────────────────
async def assemble_puzzle(db, uid: str, puzzle_id: str) -> Dict:
    ups = await db.mg_user_puzzles.find({"user_id": uid, "puzzle_id": puzzle_id, "status": "complete"}, {"_id": 0}).to_list(1)
    if not ups:
        raise ValueError("not_complete")
    up = ups[0]
    if len(set(up.get("pieces") or [])) < 9:
        raise ValueError("not_complete")
    user = await db.users.find_one({"id": uid}, {"_id": 0, "wallet_address": 1}) or {}
    if not user.get("wallet_address"):
        return {"ok": False, "need_wallet": True}         # nothing changes: link the wallet and press again
    puzzle = await _find(db, "mg_puzzles", {"id": puzzle_id})
    if not puzzle:
        raise ValueError("not_found")
    claimed = await db.mg_user_puzzles.update_one({"id": up["id"], "status": "complete"},
                                                  {"$set": {"status": "assembled", "assembled_at": _iso()}})
    if not claimed.modified_count:
        raise ValueError("already_assembled")
    grant = await grant_nft(db, uid, puzzle["nft_id"], "puzzle", up["id"])
    if not grant:                                          # should not happen (drops stop before the supply ends)
        await db.mg_user_puzzles.update_one({"id": up["id"]}, {"$set": {"status": "complete", "assembled_at": None}})
        raise ValueError("sold_out")
    await db.mg_user_puzzles.update_one({"id": up["id"]}, {"$set": {"grant_id": grant["id"]}})
    return {"ok": True, "grant": public_grant(grant)}


def public_grant(g: Optional[Dict]) -> Optional[Dict]:
    if not g:
        return None
    return {k: g.get(k) for k in ("id", "nft_id", "status", "tx_hash", "nft_address", "source", "created_at", "delivered_at", "attempts")}


# ───────────────────────────── thresholds ─────────────────────────────
async def grant_reward(db, uid: str, reward: Dict, campaign_id: str, source: str = "threshold", notify: Optional[str] = "full") -> Optional[Dict]:
    """Give one reward. The unique (user, reward, campaign) index lets it through only once."""
    rec = {"id": _uid(), "user_id": uid, "reward_id": reward["id"], "campaign_id": campaign_id, "source": source,
           "awarded_at": _iso(), "grant_id": None, "user_container_id": None, "user_booster_id": None}
    try:
        await db.mg_user_rewards.insert_one(dict(rec))
    except Exception:
        return None                                       # already given
    t = reward.get("type")
    if t == "container" and reward.get("container_id"):
        uc = await grant_container(db, uid, reward["container_id"], source, rec["id"], notify=notify)
        rec["user_container_id"] = (uc or {}).get("id")
        rec["chest"] = await public_chest(db, uc) if uc else None
    elif t == "booster" and reward.get("booster_id"):
        ub = await grant_booster(db, uid, reward["booster_id"], source, rec["id"])
        rec["user_booster_id"] = (ub or {}).get("id")
    elif t == "nft" and reward.get("nft_id"):
        g = await grant_nft(db, uid, reward["nft_id"], "reward", rec["id"])
        rec["grant_id"] = (g or {}).get("id")
        rec["sold_out"] = g is None
    elif t == "frame" and reward.get("frame_code"):
        await db.users.update_one({"id": uid}, {"$set": {"profile_frame": reward["frame_code"]},
                                                "$addToSet": {"profile_frames": reward["frame_code"]}})
    await db.mg_user_rewards.update_one({"id": rec["id"]}, {"$set": {k: rec.get(k) for k in
                                                                     ("user_container_id", "user_booster_id", "grant_id", "sold_out")}})
    if rec.get("chest") is None:
        rec.pop("chest", None)
    return {**rec, "reward": public_reward(reward)}


def public_reward(r: Dict) -> Dict:
    return {k: r.get(k) for k in ("id", "code", "category", "threshold", "type", "name", "name_i18n", "description",
                                  "image_url", "container_id", "booster_id", "frame_code", "nft_id")}


async def check_thresholds(db, uid: str, campaign_id: str, points: Optional[int] = None, best: Optional[int] = None,
                           notify: Optional[str] = "full") -> List[Dict]:
    if points is None:
        points = await campaign_points(db, uid, campaign_id) if campaign_id else 0
    if best is None:
        best = int((await db.users.find_one({"id": uid}, {"_id": 0, "mg_best_score": 1}) or {}).get("mg_best_score") or 0)
    new = []
    for r in await _all(db, "mg_rewards", {"is_active": True, "type": {"$ne": "frame"}}, sort=[("threshold", 1)]):
        cat, th = r.get("category"), int(r.get("threshold") or 0)
        if cat == "points" and campaign_id and points >= th > 0:
            got = await grant_reward(db, uid, r, campaign_id, notify=notify)
        elif cat == "best" and best >= th > 0:
            got = await grant_reward(db, uid, r, "", notify=notify)      # a record reward: once for all time
        else:
            got = None
        if got:
            new.append(got)
    if new:
        await _notify_rewards(db, uid, new)
    return new


_REWARD_MSG = {
    "en": ("🎁 New reward", "«{n}» — open «Rewards» in the game «Sorter»."),
    "ru": ("🎁 Новая награда", "«{n}» — откройте «Награды» в игре «Сортировщик»."),
    "es": ("🎁 Nueva recompensa", "«{n}»: abre «Recompensas» en el juego «Clasificador»."),
    "zh": ("🎁 新奖励", "「{n}」— 在「分拣员」游戏中打开「奖励」。"),
    "fr": ("🎁 Nouvelle récompense", "« {n} » — ouvrez « Récompenses » dans le jeu « Trieur »."),
    "de": ("🎁 Neue Belohnung", "„{n}“ — öffne „Belohnungen“ im Spiel „Sortierer“."),
    "ja": ("🎁 新しい報酬", "「{n}」— ゲーム「仕分け屋」の「報酬」を開いてください。"),
    "ko": ("🎁 새 보상", "«{n}» — «분류기» 게임에서 «보상»을 여세요."),
    "id": ("🎁 Hadiah baru", "«{n}» — buka «Hadiah» di game «Penyortir»."),
}


async def _notify_rewards(db, uid: str, new: List[Dict]) -> None:
    try:
        from core.notify import notify_user_background
        u = await db.users.find_one({"id": uid}, {"_id": 0, "language": 1}) or {}
        lang = (u.get("language") or "en").lower()
        lang = lang if lang in _REWARD_MSG else "en"
        for rec in new:
            rw = rec.get("reward") or {}
            if rw.get("type") == "container":
                continue                                  # a chest is opened at once: its own notification shows what dropped
            name = (rw.get("name_i18n") or {}).get(lang) or rw.get("name") or ""
            title, msg = _REWARD_MSG[lang]
            notify_user_background(db, uid, title=title, message=msg.format(n=name), type_key="minigame_reward", priority="info")
    except Exception as e:
        logger.debug("reward notify: %s", e)


# ───────────────────────────── leaderboard / campaign end ─────────────────────────────
def prize_for(place: int, prizes: List[Dict]) -> Optional[Dict]:
    for p in prizes or []:
        if int(p.get("from", 0)) <= place <= int(p.get("to", 0)):
            return p
    return None


async def describe_prizes(db, prizes: List[Dict]) -> List[Dict]:
    """Prizes with the name / image of what they give (for the list of leaders)."""
    out = []
    for p in prizes or []:
        d = {"from": int(p.get("from", 0)), "to": int(p.get("to", 0)), "kind": p.get("kind") or "city",
             "ref_id": p.get("ref_id"), "city": float(p.get("city") or 0), "name": None, "name_i18n": None, "image_url": None}
        coll = {"reward": "mg_rewards", "container": "mg_containers", "booster": "mg_boosters", "nft": "mg_nfts"}.get(d["kind"])
        if coll and d["ref_id"]:
            doc = await _find(db, coll, {"id": d["ref_id"]}) or {}
            d.update(name=doc.get("name"), name_i18n=doc.get("name_i18n"), image_url=doc.get("image_url"))
        out.append(d)
    return out


async def leaderboard(db, campaign_id: str, uid: Optional[str] = None, limit: int = 100, prizes: Optional[List[Dict]] = None) -> Dict:
    rows = await db.minigame_points.find({"campaign_id": campaign_id, "points": {"$gt": 0}}, {"_id": 0}) \
        .sort([("points", -1), ("updated_at", 1)]).limit(limit).to_list(None)
    ids = [r["user_id"] for r in rows] + ([uid] if uid else [])
    users = {u["id"]: u for u in await db.users.find({"id": {"$in": ids}}, {"_id": 0, "id": 1, "username": 1, "profile_frame": 1}).to_list(None)}
    described = await describe_prizes(db, prizes or [])
    out = [{"place": i + 1, "user_id": r["user_id"], "username": (users.get(r["user_id"]) or {}).get("username") or "—",
            "frame": (users.get(r["user_id"]) or {}).get("profile_frame"),
            "points": int(r["points"]), "prize": prize_for(i + 1, described)} for i, r in enumerate(rows)]
    me = None
    if uid:
        mine = await _find(db, "minigame_points", {"campaign_id": campaign_id, "user_id": uid})
        pts = int((mine or {}).get("points", 0))
        if pts > 0:
            ahead = await db.minigame_points.count_documents({"campaign_id": campaign_id, "points": {"$gt": pts}})
            ties = await db.minigame_points.count_documents({"campaign_id": campaign_id, "points": pts,
                                                             "updated_at": {"$lt": mine.get("updated_at") or ""}})
            place = ahead + ties + 1
            me = {"place": place, "points": pts, "prize": prize_for(place, described),
                  "username": (users.get(uid) or {}).get("username") or "—"}
        else:
            me = {"place": None, "points": 0, "prize": None, "username": (users.get(uid) or {}).get("username") or "—"}
    return {"rows": out, "me": me, "prizes": described}


async def give_prize(db, uid: str, prize: Dict, campaign_id: str, place: int) -> Dict:
    kind, ref = prize.get("kind") or "city", prize.get("ref_id")
    src_ref = f"{campaign_id}:{place}"
    if kind == "city":
        city = float(prize.get("city") or 0)
        if city > 0:
            ton = city / 1000.0
            await db.users.update_one({"id": uid}, {"$inc": {"bonus_balance": ton}})
            await db.transactions.insert_one({"id": _uid(), "tx_type": "minigame_prize", "user_id": uid, "amount": ton,
                                              "amount_ton": ton, "status": "completed", "event_id": campaign_id, "place": place,
                                              "created_at": _iso(), "bonus": True})
        return {"kind": "city", "city": city}
    if kind == "reward":
        rw = await _find(db, "mg_rewards", {"id": ref})
        if rw:
            await grant_reward(db, uid, rw, f"lb:{campaign_id}", source="leaderboard")
        return {"kind": "reward", "ref_id": ref}
    if kind == "container":
        await grant_container(db, uid, ref, "leaderboard", src_ref)
        return {"kind": "container", "ref_id": ref}
    if kind == "booster":
        await grant_booster(db, uid, ref, "leaderboard", src_ref)
        return {"kind": "booster", "ref_id": ref}
    if kind == "nft":
        g = await grant_nft(db, uid, ref, "leaderboard", src_ref)
        return {"kind": "nft", "ref_id": ref, "sold_out": g is None}
    return {"kind": kind}


async def linked_winners(db, user_ids: List[str]) -> List[Dict]:
    """Prize winners who share a device fingerprint with another account (checked by the admin before the end)."""
    out = []
    if not user_ids:
        return out
    fps = await db.fingerprints.find({"user_id": {"$in": user_ids}, "visitor_id": {"$ne": None}}, {"_id": 0, "user_id": 1, "visitor_id": 1}).to_list(5000)
    vids = {}
    for f in fps:
        vids.setdefault(f["visitor_id"], set()).add(f["user_id"])
    for vid in list(vids):
        others = await db.fingerprints.distinct("user_id", {"visitor_id": vid})
        accounts = sorted({o for o in others if o})
        if len(accounts) > 1:
            for w in vids[vid]:
                out.append({"user_id": w, "visitor_id": vid, "accounts": accounts})
    return out


async def log_anomaly(db, uid: str, reason: str, session_id: str = "", details: Optional[Dict] = None) -> None:
    try:
        await db.mg_anomalies.insert_one({"id": _uid(), "user_id": uid, "reason": reason, "session_id": session_id,
                                          "details": details or {}, "created_at": _iso()})
    except Exception as e:
        logger.debug("anomaly log: %s", e)


# ───────────────────────────── player view ─────────────────────────────
async def my_rewards(db, uid: str, cfg: Dict) -> Dict:
    campaign_id = cfg.get("event_id") or ""
    pts = await campaign_points(db, uid, campaign_id)
    u = await db.users.find_one({"id": uid}, {"_id": 0, "mg_best_score": 1, "wallet_address": 1, "profile_frame": 1}) or {}
    best = int(u.get("mg_best_score") or 0)
    given = {(r["reward_id"], r["campaign_id"]): r for r in await _all(db, "mg_user_rewards", {"user_id": uid})}
    grants = {g["id"]: g for g in await _all(db, "mg_nft_grants", {"user_id": uid})}
    rewards = []
    for r in await _all(db, "mg_rewards", {"is_active": True, "type": {"$ne": "frame"}}, sort=[("threshold", 1)]):
        cat = r.get("category")
        cur = pts if cat == "points" else best
        rec = given.get((r["id"], campaign_id if cat == "points" else ""))
        g = grants.get((rec or {}).get("grant_id")) if rec else None
        th = int(r.get("threshold") or 0)
        rewards.append({**public_reward(r), "given": bool(rec), "progress": min(100, round(cur * 100 / th)) if th else 0,
                        "current": cur, "grant": public_grant(g), "sold_out": bool((rec or {}).get("sold_out"))})
    containers = await _all(db, "mg_user_containers", {"user_id": uid}, sort=[("awarded_at", -1)], limit=100)
    cdefs = {c["id"]: c for c in await _all(db, "mg_containers", {})}
    for c in containers:
        d = cdefs.get(c["container_id"]) or {}
        c.pop("plan", None)
        c.update(name=d.get("name"), name_i18n=d.get("name_i18n"), image_url=d.get("image_url"))
    boosters = await _all(db, "mg_user_boosters", {"user_id": uid}, sort=[("awarded_at", -1)], limit=100)
    bdefs = {b["id"]: b for b in await _all(db, "mg_boosters", {})}
    for b in boosters:
        d = bdefs.get(b["booster_id"]) or {}
        b.update(name=d.get("name"), name_i18n=d.get("name_i18n"), effect=d.get("effect"), duration_hours=d.get("duration_hours"))
    puzzles = await my_puzzles(db, uid)
    nfts = []
    ndefs = {n["id"]: n for n in await _all(db, "mg_nfts", {})}
    for g in sorted(grants.values(), key=lambda x: x.get("created_at") or "", reverse=True):
        d = ndefs.get(g["nft_id"]) or {}
        nfts.append({**public_grant(g), "name": d.get("name"), "image_url": d.get("image_url"), "kind": d.get("kind")})
    def nxt(cat, cur):
        ths = sorted(int(r["threshold"]) for r in rewards if r["category"] == cat and int(r["threshold"] or 0) > cur)
        return ths[0] if ths else None
    return {"campaign_id": campaign_id, "campaign_points": pts, "best_score": best,
            "next_points": nxt("points", pts), "next_best": nxt("best", best),
            "rewards": rewards, "containers": containers, "boosters": boosters, "puzzles": puzzles, "nfts": nfts,
            "wallet_linked": bool(u.get("wallet_address")), "profile_frame": u.get("profile_frame"),
            "nft_network": (await nft_settings(db))["network"],
            "chests_today": await chests_today(db, uid), "chests_per_day": int(cfg.get("chests_per_day") or 0),
            "chest_min_stars": int(cfg.get("chest_min_stars") or 2),
            "chest_min_points": int((cfg.get("star_points") or [300, 1000, 2000])[max(0, int(cfg.get("chest_min_stars") or 2) - 1)]),
            "nft_waiting_wallet": (not u.get("wallet_address")) and any(g.get("status") in ("reserved", "waiting_stock") for g in grants.values()),
            "unopened": sum(1 for c in containers if c.get("status") == "unopened"),
            "boosters_available": sum(1 for b in boosters if b.get("status") == "available")}


async def my_puzzles(db, uid: str) -> List[Dict]:
    out = []
    mine = {}
    for up in await _all(db, "mg_user_puzzles", {"user_id": uid}, sort=[("round", 1)]):
        mine[up["puzzle_id"]] = up                         # the latest round
    grants = {g["id"]: g for g in await _all(db, "mg_nft_grants", {"user_id": uid, "source": "puzzle"})}
    for p in await _all(db, "mg_puzzles", {}):
        up = mine.get(p["id"])
        if not p.get("is_active") and not up:
            continue
        pieces = sorted(set((up or {}).get("pieces") or []))
        out.append({"puzzle_id": p["id"], "name": p.get("name"), "name_i18n": p.get("name_i18n"), "nft_id": p.get("nft_id"),
                    "pieces": pieces, "have": len(pieces), "status": (up or {}).get("status") or "none",
                    "piece_urls": {str(n): f"/api/minigames/img/puzzle_{p['id']}_{n}.webp" for n in pieces} if p.get("has_pieces") else {},
                    "image_url": p.get("image_url") if (up or {}).get("status") == "assembled" else None,
                    "grant": public_grant(grants.get((up or {}).get("grant_id")))})
    return out


# ───────────────────────────── NFT delivery (background, every 5 min) ─────────────────────────────
async def nft_settings(db) -> Dict:
    d = await _find(db, "admin_settings", {"type": "minigame_nft"}) or {}
    return {"network": d.get("network") or "testnet", "sending_enabled": bool(d.get("sending_enabled", False)),
            "meta_base_url": d.get("meta_base_url") or ""}


_GRANT_MSG = {
    "en": ("💎 NFT in your wallet", "«{n}» has arrived in your wallet."),
    "ru": ("💎 NFT в кошельке", "«{n}» поступил на ваш кошелёк."),
    "es": ("💎 NFT en tu billetera", "«{n}» ha llegado a tu billetera."),
    "zh": ("💎 NFT 已到账", "「{n}」已到达您的钱包。"),
    "fr": ("💎 NFT dans votre portefeuille", "« {n} » est arrivé dans votre portefeuille."),
    "de": ("💎 NFT in deiner Wallet", "„{n}“ ist in deiner Wallet angekommen."),
    "ja": ("💎 NFTがウォレットに届きました", "「{n}」がウォレットに届きました。"),
    "ko": ("💎 지갑에 NFT 도착", "«{n}»이(가) 지갑에 도착했습니다."),
    "id": ("💎 NFT di dompet Anda", "«{n}» telah masuk ke dompet Anda."),
}


async def _grant_fail(db, g: Dict, err: str) -> None:
    attempts = int(g.get("attempts") or 0) + 1
    nxt = _now() + timedelta(hours=1)
    await db.mg_nft_grants.update_one({"id": g["id"]}, {"$set": {"status": "failed", "attempts": attempts, "error": err[:300],
                                                                 "next_try_at": _iso(nxt)}})
    if g.get("item_id"):
        await db.mg_nft_items.update_one({"id": g["item_id"]}, {"$set": {"status": "failed"}})
    if attempts >= MAX_SEND_ATTEMPTS:
        await notify_admin(db, f"❌ NFT не отправлен после {attempts} попыток (выдача {g['id'][:8]}, игрок {g['user_id'][:8]}): {err[:200]}. "
                               f"Повторите вручную в админке → Мини-игры → NFT.")


async def process_nft_queue(db, sender=None, limit: int = 20) -> Dict[str, int]:
    """waiting_stock -> reserved (stock added) · reserved/failed(<3) + linked wallet -> sending -> on chain · sending -> delivered."""
    import nft_sender as ns
    sender = sender or ns
    st = await nft_settings(db)
    out = {"assigned": await assign_waiting(db), "sent": 0, "delivered": 0, "failed": 0}
    if not st["sending_enabled"]:
        return out
    if sender is ns and not await ns.load_mnemonic(db):        # the admin's withdrawal wallet («Контракт»)
        return out
    net = st["network"]
    # 1) confirm what was sent
    for g in await _all(db, "mg_nft_grants", {"status": "sending"}, limit=100):
        item = await _find(db, "mg_nft_items", {"id": g.get("item_id")}) or {}
        nft = await _find(db, "mg_nfts", {"id": g["nft_id"]}) or {}
        u = await db.users.find_one({"id": g["user_id"]}, {"_id": 0, "wallet_address": 1, "language": 1}) or {}
        try:
            if item.get("kind") == "sbt":
                it = await sender.sbt_item(net, nft.get("collection_address"), int(item.get("index") or 0))
                owner, addr = (it or {}).get("owner_address"), (it or {}).get("address")
            else:
                addr = item.get("nft_address")
                owner = await sender.item_owner(net, addr)
        except Exception as e:
            logger.warning("nft confirm %s: %s", g["id"], e)
            continue
        if owner and sender.raw(owner) == sender.raw(g.get("to_wallet") or u.get("wallet_address") or ""):
            now = _iso()
            await db.mg_nft_grants.update_one({"id": g["id"], "status": "sending"},
                                              {"$set": {"status": "delivered", "delivered_at": now, "nft_address": addr}})
            await db.mg_nft_items.update_one({"id": item.get("id")}, {"$set": {"status": "delivered", "delivered_at": now, "nft_address": addr}})
            out["delivered"] += 1
            try:
                from core.notify import notify_user_background
                lang = (u.get("language") or "en").lower()
                title, msg = _GRANT_MSG.get(lang, _GRANT_MSG["en"])
                notify_user_background(db, g["user_id"], title=title, message=msg.format(n=nft.get("name") or "NFT"),
                                       type_key="minigame_nft", priority="info")
            except Exception:
                pass
        elif (_now() - (_parse(g.get("sent_at")) or _now())).total_seconds() > 1800:
            await _grant_fail(db, g, "не подтверждено в сети за 30 минут")
            out["failed"] += 1
    # 2) send the ready ones
    now = _now()
    ready = await _all(db, "mg_nft_grants", {"status": {"$in": ["reserved", "failed"]}}, sort=[("created_at", 1)], limit=200)
    for g in ready:
        if out["sent"] >= limit:
            break
        if g["status"] == "failed" and (int(g.get("attempts") or 0) >= MAX_SEND_ATTEMPTS or (_parse(g.get("next_try_at")) or now) > now):
            continue
        u = await db.users.find_one({"id": g["user_id"]}, {"_id": 0, "wallet_address": 1}) or {}
        wallet = u.get("wallet_address")
        if not wallet:
            continue                                       # waits for the wallet as long as needed
        claimed = await db.mg_nft_grants.update_one({"id": g["id"], "status": g["status"]},
                                                    {"$set": {"status": "sending", "to_wallet": wallet, "sent_at": _iso()}})
        if not claimed.modified_count:
            continue                                       # someone else took it: never sent twice
        item = await _find(db, "mg_nft_items", {"id": g.get("item_id")}) or {}
        nft = await _find(db, "mg_nfts", {"id": g["nft_id"]}) or {}
        await db.mg_nft_items.update_one({"id": item.get("id")}, {"$set": {"status": "sending"}})
        try:
            if item.get("kind") == "sbt":
                if not nft.get("collection_address"):
                    raise RuntimeError("у SBT не указан адрес коллекции")
                content = (nft.get("content_template") or "{nft_id}/{index}.json").format(nft_id=nft["id"], index=item.get("index"))
                h = await sender.mint_sbt(net, nft["collection_address"], int(item.get("index") or 0), wallet, content)
            else:
                h = await sender.transfer_nft(net, item["nft_address"], wallet)
            await db.mg_nft_grants.update_one({"id": g["id"]}, {"$set": {"tx_hash": h}})
            await db.mg_nft_items.update_one({"id": item.get("id")}, {"$set": {"tx_hash": h}})
            out["sent"] += 1
        except Exception as e:
            logger.warning("nft send %s: %s", g["id"], e)
            await _grant_fail(db, {**g, "item_id": item.get("id")}, str(e))
            out["failed"] += 1
    return out
