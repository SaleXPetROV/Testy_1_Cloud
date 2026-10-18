"""GRAM City — in-game quests ("Путь новичка", daily & weekly goals).

Separate from ``routes/tasks.py`` (marketing / external tasks), which is left
untouched. This module adds *automatic* in-game quests:

  • onboarding  — one-time chain for new players ("Путь новичка")
  • daily       — 3 goals per day (easy / medium / good), picked per player
  • weekly      — 3 goals per week

How a quest is completed
------------------------
There is no "Complete" button. Game code reports what the player did via
``fire(user, event, amount)``; progress grows by itself. When the target is
reached the quest becomes ``ready`` and the player presses "Claim", which is
atomic (a double click can never pay twice).

Rewards
-------
* ``reward_city`` goes to ``bonus_balance`` (spendable in-game, NOT withdrawable)
  so quests cannot be farmed into withdrawals. A per-day cap limits it.
* ``reward_xp`` goes to ``users.xp``.

Day / week boundaries use Moscow time (UTC+3), like the rest of the economy.
"""
from __future__ import annotations

import asyncio
import logging
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))
CITY_PER_TON = 1000.0

# Max bonus $CITY a player can receive from quests per MSK day (admin-overridable
# via db.tasks_config {key: "quest_limits", daily_bonus_cap_city: N}).
DEFAULT_DAILY_BONUS_CAP_CITY = 300

# ─────────────────────────── default quest catalogue ───────────────────────────
# `event`   : name reported by game code through fire()
# `state`   : alternative to events — a condition evaluated from the DB
# `requires_business` : daily/weekly goals are only handed out to players that
#                       own a business (so a goal is never impossible)
QUEST_DEFAULTS: List[Dict[str, Any]] = [
    # ── onboarding ("Путь новичка") ──
    {"id": "ob_open_business", "kind": "onboarding", "order": 1, "state": "has_business", "target": 1,
     "reward_city": 20, "reward_xp": 10, "deep_link": "/maps",
     "title": {"en": "Open your first business", "ru": "Откройте первый бизнес"},
     "description": {"en": "Pick a free plot on the map and claim a business.", "ru": "Выберите свободный участок на карте и откройте бизнес."}},
    {"id": "ob_first_shift", "kind": "onboarding", "order": 2, "event": "shift_start", "target": 1,
     "reward_city": 10, "reward_xp": 30, "deep_link": "/my-businesses",
     "title": {"en": "Start your first shift", "ru": "Запустите первую смену"},
     "description": {"en": "Open My Business and press Start shift.", "ru": "Откройте «Мой бизнес» и нажмите «Запустить смену»."}},
    {"id": "ob_first_buy", "kind": "onboarding", "order": 3, "event": "market_buy", "target": 1,
     "reward_city": 15, "reward_xp": 20, "deep_link": "/trading",
     "title": {"en": "Buy a resource on the market", "ru": "Купите ресурс на рынке"},
     "description": {"en": "Most businesses need raw materials. Buy at least 1 unit.", "ru": "Большинству бизнесов нужно сырьё. Купите хотя бы 1 единицу."}},
    # Production lands in the warehouse automatically every minute, so there is
    # nothing to "collect" — the player learns to put it on the market instead.
    {"id": "ob_first_list", "kind": "onboarding", "order": 4, "event": "market_list", "target": 1,
     "reward_city": 15, "reward_xp": 20, "deep_link": "/trading",
     "title": {"en": "Put a resource up for sale", "ru": "Выставьте ресурс на продажу"},
     "description": {"en": "Your business fills the warehouse by itself. List some of it on the market.",
                     "ru": "Бизнес сам пополняет склад. Выставьте часть продукции на рынок."}},
    {"id": "ob_first_sale", "kind": "onboarding", "order": 5, "event": "market_sell", "target": 1,
     "reward_city": 25, "reward_xp": 30, "deep_link": "/trading",
     "title": {"en": "Sell a resource", "ru": "Продайте ресурс"},
     "description": {"en": "List your product on the market and sell it.", "ru": "Выставите свою продукцию на рынок и продайте её."}},
    {"id": "ob_first_repair", "kind": "onboarding", "order": 6, "event": "repair", "target": 1,
     "reward_city": 10, "reward_xp": 20, "deep_link": "/my-businesses",
     "title": {"en": "Repair a building", "ru": "Отремонтируйте здание"},
     "description": {"en": "Buildings wear out. Repair keeps production at full speed.", "ru": "Здания изнашиваются. Ремонт сохраняет полную скорость производства."}},
    {"id": "ob_first_upgrade", "kind": "onboarding", "order": 7, "event": "upgrade", "target": 1,
     "reward_city": 100, "reward_xp": 100, "deep_link": "/my-businesses",
     "title": {"en": "Upgrade your business", "ru": "Улучшите бизнес"},
     "description": {"en": "Raise your business one level.", "ru": "Повысьте уровень бизнеса на один."}},

    # ── daily: easy ──
    {"id": "d_shift", "kind": "daily", "difficulty": "easy", "event": "shift_start", "target": 1,
     "reward_city": 5, "reward_xp": 10, "deep_link": "/my-businesses", "requires_business": True,
     "title": {"en": "Start a shift", "ru": "Запустите смену"},
     "description": {"en": "Start a shift at any of your businesses.", "ru": "Запустите смену на любом из ваших бизнесов."}},
    {"id": "d_buy1", "kind": "daily", "difficulty": "easy", "event": "market_buy", "target": 1,
     "reward_city": 5, "reward_xp": 10, "deep_link": "/trading", "requires_business": True,
     "title": {"en": "Buy any resource", "ru": "Купите любой ресурс"},
     "description": {"en": "Buy at least 1 unit of any resource on the market.",
                     "ru": "Купите на рынке хотя бы 1 единицу любого ресурса."}},
    # ── daily: medium ──
    {"id": "d_sell20", "kind": "daily", "difficulty": "medium", "event": "market_sell", "target": 20,
     "reward_city": 10, "reward_xp": 20, "deep_link": "/trading", "requires_business": True,
     "title": {"en": "Sell 20 units", "ru": "Продайте 20 единиц"},
     "description": {"en": "Sell 20 units of resources on the market.", "ru": "Продайте 20 единиц ресурсов на рынке."}},
    {"id": "d_repair", "kind": "daily", "difficulty": "medium", "event": "repair", "target": 1,
     "reward_city": 10, "reward_xp": 20, "deep_link": "/my-businesses", "requires_business": True,
     "title": {"en": "Repair a building", "ru": "Отремонтируйте здание"},
     "description": {"en": "Restore a building's durability.", "ru": "Восстановите прочность здания."}},
    {"id": "d_buy20", "kind": "daily", "difficulty": "medium", "event": "market_buy", "target": 20,
     "reward_city": 10, "reward_xp": 20, "deep_link": "/trading", "requires_business": True,
     "title": {"en": "Buy 20 units", "ru": "Купите 20 единиц"},
     "description": {"en": "Buy 20 units of resources on the market.", "ru": "Купите 20 единиц ресурсов на рынке."}},
    # ── daily: good ──
    {"id": "d_list_lot", "kind": "daily", "difficulty": "good", "event": "market_list", "target": 1,
     "reward_city": 15, "reward_xp": 30, "deep_link": "/trading", "requires_business": True,
     "title": {"en": "Create a market lot", "ru": "Выставите лот на рынок"},
     "description": {"en": "List resources for sale on the market.", "ru": "Выставите ресурсы на продажу на рынке."}},
    {"id": "d_sell50", "kind": "daily", "difficulty": "good", "event": "market_sell", "target": 50,
     "reward_city": 15, "reward_xp": 30, "deep_link": "/trading", "requires_business": True,
     "title": {"en": "Sell 50 units", "ru": "Продайте 50 единиц"},
     "description": {"en": "Sell 50 units of resources on the market.", "ru": "Продайте 50 единиц ресурсов на рынке."}},

    # ── weekly ──
    {"id": "w_sell300", "kind": "weekly", "event": "market_sell", "target": 300,
     "reward_city": 60, "reward_xp": 100, "deep_link": "/trading", "requires_business": True,
     "title": {"en": "Sell 300 units this week", "ru": "Продайте 300 единиц за неделю"},
     "description": {"en": "Sell 300 units of resources on the market.", "ru": "Продайте 300 единиц ресурсов на рынке."}},
    {"id": "w_maintain3", "kind": "weekly", "event": "maintain", "target": 3,
     "reward_city": 40, "reward_xp": 60, "deep_link": "/my-businesses", "requires_business": True,
     "title": {"en": "3 repairs or upgrades", "ru": "3 ремонта или улучшения"},
     "description": {"en": "Repair or upgrade buildings three times.", "ru": "Отремонтируйте или улучшите здания три раза."}},
    {"id": "w_shifts7", "kind": "weekly", "event": "shift_start", "target": 7,
     "reward_city": 50, "reward_xp": 80, "deep_link": "/my-businesses", "requires_business": True,
     "title": {"en": "Start 7 shifts", "ru": "Запустите 7 смен"},
     "description": {"en": "Start shifts seven times during the week.", "ru": "Запустите смены семь раз за неделю."}},
]

# Quests removed from the game. Existing databases still hold them (templates
# are seeded with $setOnInsert so admin edits survive) — they are switched off.
RETIRED_QUESTS = {"ob_first_collect", "d_collect"}

_DB = None
_tpl_cache: Dict[str, Any] = {"ts": 0.0, "items": []}
_seeded = False
_indexes_ready = False
_bg: set = set()


def init(db) -> None:
    """Bind the Motor database (called once from server.py)."""
    global _DB
    _DB = db


# ───────────────────────────── time helpers ─────────────────────────────
def _now_msk() -> datetime:
    return datetime.now(timezone.utc).astimezone(MSK)


def period_key(kind: str, now: Optional[datetime] = None) -> str:
    n = now or _now_msk()
    if kind == "daily":
        return n.date().isoformat()
    if kind == "weekly":
        iso = n.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    return "once"


def period_end_iso(kind: str, now: Optional[datetime] = None) -> Optional[str]:
    n = now or _now_msk()
    if kind == "daily":
        end = (n + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    elif kind == "weekly":
        end = (n + timedelta(days=7 - n.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        return None
    return end.astimezone(timezone.utc).isoformat()


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ───────────────────────────── storage helpers ─────────────────────────────
async def _ensure_indexes() -> None:
    global _indexes_ready
    if _indexes_ready or _DB is None:
        return
    _indexes_ready = True
    try:
        await _DB.user_quests.create_index([("user_id", 1), ("quest_id", 1), ("period_key", 1)], unique=True)
        await _DB.user_quests.create_index([("user_id", 1), ("kind", 1), ("period_key", 1)])
        await _DB.quest_assignments.create_index([("user_id", 1), ("kind", 1), ("period_key", 1)], unique=True)
        await _DB.quest_event_log.create_index([("user_id", 1), ("unique", 1)], unique=True)
        await _DB.quest_templates.create_index("id", unique=True)
    except Exception as e:  # indexes are an optimisation + dedupe guard, never fatal
        logger.warning(f"quests: index creation failed: {e}")


async def get_templates(force: bool = False) -> List[Dict[str, Any]]:
    """Templates from DB (seeded from QUEST_DEFAULTS, admin edits preserved)."""
    global _seeded
    now = asyncio.get_event_loop().time()
    if not force and _tpl_cache["items"] and now - _tpl_cache["ts"] < 30:
        return _tpl_cache["items"]
    await _ensure_indexes()
    if not _seeded:
        for d in QUEST_DEFAULTS:
            try:
                insert = {k: v for k, v in d.items() if k != "order"}
                upd: Dict[str, Any] = {"$setOnInsert": {**insert, "active": True}}
                if "order" in d:          # ordering is owned by the code, not the admin
                    upd["$set"] = {"order": d["order"]}
                await _DB.quest_templates.update_one({"id": d["id"]}, upd, upsert=True)
            except Exception as e:
                logger.warning(f"quests: seeding {d['id']} failed: {e}")
        try:
            await _DB.quest_templates.update_many({"id": {"$in": list(RETIRED_QUESTS)}}, {"$set": {"active": False}})
        except Exception as e:
            logger.warning(f"quests: retiring old templates failed: {e}")
        _seeded = True
        global _warmup_started
        if not _warmup_started and _lt_configured():
            _warmup_started = True
            _schedule_translation(None)  # translate all templates into all languages in the background
    items = await _DB.quest_templates.find({}, {"_id": 0}).to_list(500)
    _tpl_cache["items"] = items
    _tpl_cache["ts"] = now
    return items


def _loc(d: Any, lang: str) -> str:
    if isinstance(d, dict):
        return d.get(lang) or d.get("en") or next(iter(d.values()), "")
    return str(d or "")


async def _resolve_uid(ref: Any) -> Optional[str]:
    if ref is None:
        return None
    if isinstance(ref, dict) and ref.get("id"):
        return ref["id"]
    ids: List[str] = []
    if isinstance(ref, dict):
        ids = [x for x in (ref.get("wallet_address"), ref.get("email")) if x]
    elif isinstance(ref, (list, tuple, set)):
        ids = [x for x in ref if x]
    elif isinstance(ref, str):
        ids = [ref]
    if not ids:
        return None
    q = {"$or": [{"id": x} for x in ids] + [{"wallet_address": x} for x in ids]}
    u = await _DB.users.find_one(q, {"_id": 0, "id": 1})
    return (u or {}).get("id")


async def _owner_ids(uid: str) -> List[str]:
    """Every identifier the player's businesses may be stored under (shared rule)."""
    from core.helpers import resolve_owner_keys
    return await resolve_owner_keys(_DB, uid)


async def _has_business(uid: str) -> bool:
    from core.helpers import owner_businesses_query
    keys = await _owner_ids(uid)
    if not keys:
        return False
    return await _DB.businesses.count_documents(owner_businesses_query(keys), limit=1) > 0


# ───────────────────────────── assignment ─────────────────────────────
async def ensure_assignment(uid: str, kind: str, has_business: Optional[bool] = None) -> List[str]:
    """Quest ids handed to the player for the current day/week (created lazily)."""
    pk = period_key(kind)
    flt = {"user_id": uid, "kind": kind, "period_key": pk}
    doc = await _DB.quest_assignments.find_one(flt, {"_id": 0})
    if doc:
        ids = doc.get("quest_ids", [])
        tmap = {t["id"]: t for t in await get_templates()}
        stale = [i for i in ids if not (tmap.get(i) or {}).get("active", True) or i not in tmap]
        if not stale:
            return ids
        # replace each retired quest with an active one of the same difficulty
        fixed = []
        for i in ids:
            if i not in stale:
                fixed.append(i)
                continue
            diff = (tmap.get(i) or {}).get("difficulty")
            pool = sorted([t["id"] for t in tmap.values() if t.get("kind") == kind and t.get("active", True)
                           and t["id"] not in ids and t["id"] not in fixed
                           and (diff is None or t.get("difficulty") == diff)])
            if pool:
                fixed.append(random.Random(f"{uid}:{kind}:{pk}:{i}").choice(pool))
        await _DB.quest_assignments.update_one(flt, {"$set": {"quest_ids": fixed}})
        return fixed
    if has_business is None:
        has_business = await _has_business(uid)
    tpls = [t for t in await get_templates() if t.get("kind") == kind and t.get("active", True)]
    tpls = [t for t in tpls if has_business or not t.get("requires_business")]
    if not tpls:
        return []  # nothing eligible yet — do not persist, retry once they own a business
    rng = random.Random(f"{uid}:{kind}:{pk}")
    if kind == "daily":
        chosen: List[str] = []
        for diff in ("easy", "medium", "good"):
            pool = sorted([t for t in tpls if t.get("difficulty") == diff], key=lambda t: t["id"])
            if pool:
                chosen.append(rng.choice(pool)["id"])
    else:
        chosen = [t["id"] for t in sorted(tpls, key=lambda t: t["id"])]
    try:
        await _DB.quest_assignments.insert_one({**flt, "quest_ids": chosen, "created_at": _iso_now()})
    except DuplicateKeyError:
        doc = await _DB.quest_assignments.find_one(flt, {"_id": 0})
        return (doc or {}).get("quest_ids", chosen)
    return chosen


# ───────────────────────────── progress ─────────────────────────────
async def _bump(uid: str, t: Dict[str, Any], amount: int) -> None:
    pk = period_key(t["kind"])
    flt = {"user_id": uid, "quest_id": t["id"], "period_key": pk}
    doc = await _DB.user_quests.find_one(flt, {"_id": 0, "status": 1})
    if doc and doc.get("status") != "active":
        return
    if not doc:
        try:
            await _DB.user_quests.insert_one({**flt, "kind": t["kind"], "progress": 0, "status": "active",
                                              "created_at": _iso_now(), "updated_at": _iso_now()})
        except DuplicateKeyError:
            pass
    res = await _DB.user_quests.find_one_and_update(
        {**flt, "status": "active"},
        {"$inc": {"progress": int(amount)}, "$set": {"updated_at": _iso_now()}},
        return_document=ReturnDocument.AFTER,
    )
    target = int(t.get("target", 1) or 1)
    if res and int(res.get("progress", 0)) >= target:
        await _DB.user_quests.update_one(
            {**flt, "status": "active"},
            {"$set": {"status": "ready", "progress": target, "ready_at": _iso_now()}},
        )


async def _set_ready(uid: str, t: Dict[str, Any]) -> None:
    pk = period_key(t["kind"])
    flt = {"user_id": uid, "quest_id": t["id"], "period_key": pk}
    target = int(t.get("target", 1) or 1)
    try:
        await _DB.user_quests.insert_one({**flt, "kind": t["kind"], "progress": target, "status": "ready",
                                          "created_at": _iso_now(), "updated_at": _iso_now(), "ready_at": _iso_now()})
    except DuplicateKeyError:
        await _DB.user_quests.update_one({**flt, "status": "active"},
                                         {"$set": {"status": "ready", "progress": target, "ready_at": _iso_now()}})


async def sync_state(uid: str) -> None:
    """Complete state-based quests (conditions read from the DB, not events)."""
    pending = [t for t in await get_templates() if t.get("state") and t.get("active", True)]
    for t in pending:
        pk = period_key(t["kind"])
        doc = await _DB.user_quests.find_one({"user_id": uid, "quest_id": t["id"], "period_key": pk}, {"_id": 0, "status": 1})
        if doc and doc.get("status") != "active":
            continue
        ok = False
        if t["state"] == "has_business":
            ok = await _has_business(uid)
        if ok:
            await _set_ready(uid, t)
            if t.get("state") == "has_business":
                try:
                    import analytics
                    if not await _DB.analytics_events.find_one({"user_id": uid, "event": "first_business"}, {"_id": 1}):
                        await analytics.track(uid, "first_business")
                except Exception:
                    pass


async def quest_event(user_ref: Any, event: str, amount: int = 1, unique: Optional[str] = None) -> None:
    """Report a player action. Idempotent when ``unique`` is given."""
    if _DB is None:
        return
    amount = int(amount or 0)
    if amount <= 0:
        return
    uid = await _resolve_uid(user_ref)
    if not uid:
        return
    await _ensure_indexes()
    if unique:
        try:
            await _DB.quest_event_log.insert_one({"user_id": uid, "unique": str(unique), "created_at": _iso_now()})
        except DuplicateKeyError:
            return
    # Retention funnel milestones (analytics.py): fire once per user. mark_active
    # records that the user did something today for cohort retention.
    try:
        import analytics
        analytics.mark_active_bg(uid)
        _milestone = {"shift_start": "first_shift", "market_sell": "first_sale", "collect": "first_collect"}.get(event)
        if _milestone:
            async def _once(u=uid, m=_milestone):
                try:
                    if not await _DB.analytics_events.find_one({"user_id": u, "event": m}, {"_id": 1}):
                        await analytics.track(u, m)
                except Exception:
                    pass
            t = asyncio.get_event_loop().create_task(_once())
            _bg.add(t); t.add_done_callback(_bg.discard)
    except Exception:
        pass
    # Leagues: activity points (shift / repair) — counted once per unique event
    if event in ("shift_start", "repair"):
        try:
            import leagues
            import city_pass
            leagues.activity_bg(uid, event, amount)
            city_pass.xp_bg(uid, event, amount)
        except Exception:
            pass
    events = [event]
    if event in ("repair", "upgrade"):
        events.append("maintain")  # weekly "3 repairs or upgrades"
    tpls = [t for t in await get_templates() if t.get("event") in events and t.get("active", True)]
    if not tpls:
        return
    has_biz: Optional[bool] = None
    assigned: Dict[str, List[str]] = {}
    for t in tpls:
        kind = t["kind"]
        if kind in ("daily", "weekly"):
            if kind not in assigned:
                if has_biz is None:
                    has_biz = await _has_business(uid)
                assigned[kind] = await ensure_assignment(uid, kind, has_biz)
            if t["id"] not in assigned[kind]:
                continue
        await _bump(uid, t, amount)


async def accounts_linked(uid_a: Optional[str], uid_b: Optional[str]) -> bool:
    """True if two accounts share a device fingerprint (antifraud `fingerprints`).
    Sales between linked accounts never count towards quests."""
    if _DB is None or not uid_a or not uid_b or uid_a == uid_b:
        return bool(uid_a and uid_a == uid_b)
    try:
        va = set(await _DB.fingerprints.distinct("visitor_id", {"user_id": uid_a, "visitor_id": {"$ne": None}}))
        if not va:
            return False
        return await _DB.fingerprints.count_documents(
            {"user_id": uid_b, "visitor_id": {"$in": list(va)}}, limit=1) > 0
    except Exception as e:
        logger.debug(f"quests: linked-accounts check failed: {e}")
        return False


async def sale_event(seller_ref: Any, buyer_ref: Any, amount: int, unique: Optional[str] = None,
                     ton: Optional[float] = None) -> None:
    """A real sale to another player (counts for `market_sell` quests).
    `ton` = the sale's value; given only for sales to PLAYERS (the City Market
    passes none), it feeds the league ratings «units sold» / «TON sold»."""
    s_uid = await _resolve_uid(seller_ref)
    b_uid = await _resolve_uid(buyer_ref)
    if not s_uid or (b_uid and await accounts_linked(s_uid, b_uid)):
        return
    await quest_event(s_uid, "market_sell", amount, unique)
    if ton is not None and b_uid:
        try:
            import leagues
            import city_pass
            leagues.sale_bg(s_uid, int(amount), float(ton))
            city_pass.sale_bg(s_uid, float(ton))
        except Exception:
            pass


async def _safe_sale(seller_ref, buyer_ref, amount, unique, ton=None):
    try:
        await sale_event(seller_ref, buyer_ref, amount, unique, ton)
    except Exception as e:
        logger.warning(f"quests: sale event failed: {e}")


def fire_sale(seller_ref: Any, buyer_ref: Any, amount: int, unique: Optional[str] = None,
              ton: Optional[float] = None) -> None:
    """Fire-and-forget version of sale_event."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(_safe_sale(seller_ref, buyer_ref, amount, unique, ton))
    _bg.add(task)
    task.add_done_callback(_bg.discard)


async def _safe_event(user_ref, event, amount, unique):
    try:
        await quest_event(user_ref, event, amount, unique)
    except Exception as e:  # quests must NEVER break a game action
        logger.warning(f"quests: event {event} failed: {e}")


def fire(user_ref: Any, event: str, amount: int = 1, unique: Optional[str] = None) -> None:
    """Fire-and-forget version of quest_event for use inside request handlers."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(_safe_event(user_ref, event, amount, unique))
    _bg.add(task)
    task.add_done_callback(_bg.discard)


async def has_daily_done(uid: str) -> bool:
    """True if the player finished (ready or claimed) at least one daily goal today.
    Used by the daily-login reward as an alternative to the old buy/sell gate."""
    if _DB is None:
        return False
    n = await _DB.user_quests.count_documents({
        "user_id": uid, "kind": "daily", "period_key": period_key("daily"),
        "status": {"$in": ["ready", "claimed"]},
    })
    return n > 0


# ───────────────────────────── onboarding mode (A/B) ─────────────────────────────
import hashlib
import os

T3_REWARD_RESOURCES = ["neuro_core", "gold_bill", "license_token", "luck_chip",
                       "war_protocol", "bio_module", "gateway_code"]


def onboarding_mode() -> str:
    """ONBOARDING_MODE env: "tutorial" (old 15-step tour for everyone),
    "quests" (new players get the quest chain instead), "ab" (50/50 split)."""
    m = (os.environ.get("ONBOARDING_MODE") or "ab").strip().lower()
    return m if m in ("tutorial", "quests", "ab") else "ab"


def _ab_bucket(uid: str) -> str:
    h = int(hashlib.sha256(f"onboarding:{uid}".encode()).hexdigest(), 16)
    return "quests" if h % 2 == 0 else "tutorial"


async def track(uid: str, event: str, **props) -> None:
    """Minimal analytics sink (no secrets/wallets): analytics_events."""
    if _DB is None or not uid:
        return
    try:
        await _DB.analytics_events.insert_one({"user_id": uid, "event": event, "props": props, "ts": _iso_now()})
    except Exception as e:
        logger.debug(f"analytics track failed: {e}")


async def onboarding_group(db, user: Dict[str, Any]) -> str:
    """Which onboarding a player gets. Stored once in users.onboarding_group.

    Players that already started / finished / were rewarded by the old tutorial
    are "legacy" and keep the old behaviour. Only fresh players are split.
    """
    if not user:
        return "tutorial"
    g = user.get("onboarding_group")
    if g:
        return g
    uid = user.get("id")
    if not uid:
        return "tutorial"
    if user.get("tutorial_completed") or user.get("tutorial_active") or user.get("tutorial_t3_reward_granted"):
        group = "legacy"
    else:
        mode = onboarding_mode()
        group = _ab_bucket(uid) if mode == "ab" else mode
    res = await db.users.update_one({"id": uid, "onboarding_group": {"$exists": False}},
                                    {"$set": {"onboarding_group": group, "onboarding_group_at": _iso_now()}})
    if res.modified_count:
        if _DB is None:
            init(db)
        await track(uid, "onboarding_group", group=group, mode=onboarding_mode())
        return group
    doc = await db.users.find_one({"id": uid}, {"_id": 0, "onboarding_group": 1}) or {}
    return doc.get("onboarding_group") or group


async def grant_onboarding_reward(uid: str, choice: str, lang: str = "en") -> Dict[str, Any]:
    """Final reward of "Путь новичка": the same one-shot T3 resource the old
    tutorial gave (stored as `<res>_tutorial`, unsellable). Never paid twice —
    shares the `tutorial_t3_reward_granted` flag with the tutorial."""
    if choice not in T3_REWARD_RESOURCES:
        raise HTTPException(status_code=400, detail=await msg("bad_choice", lang))
    tpls = [t for t in await get_templates() if t["kind"] == "onboarding" and t.get("active", True)]
    claimed = await _DB.user_quests.count_documents({"user_id": uid, "kind": "onboarding", "status": "claimed",
                                                     "quest_id": {"$in": [t["id"] for t in tpls]}})
    if not tpls or claimed < len(tpls):
        raise HTTPException(status_code=400, detail=await msg("finish_first", lang))
    res = await _DB.users.update_one(
        {"id": uid, "tutorial_t3_reward_granted": {"$ne": True}},
        {"$set": {"tutorial_t3_reward_granted": True, "tutorial_t3_reward_choice": choice,
                  "tutorial_t3_reward_granted_at": _iso_now(), "tutorial_pending_t3_auto_activate": choice,
                  "onboarding_completed_at": _iso_now()},
         "$inc": {f"resources.{choice}_tutorial": 1}},
    )
    if res.modified_count == 0:
        raise HTTPException(status_code=409, detail=await msg("received", lang))
    await track(uid, "onboarding_completed", reward=choice)
    return {"ok": True, "reward": choice}


async def onboarding_stats() -> Dict[str, Any]:
    """A/B comparison for the admin: funnel per onboarding group."""
    out: Dict[str, Any] = {"mode": onboarding_mode(), "groups": {}}
    for g in ("quests", "tutorial", "legacy"):
        users = await _DB.users.find({"onboarding_group": g}, {"_id": 0, "id": 1, "wallet_address": 1, "email": 1}).to_list(100000)
        ids = [u["id"] for u in users if u.get("id")]
        n = len(ids)
        if not n:
            out["groups"][g] = {"users": 0}
            continue
        owner_keys = [k for u in users for k in (u.get("id"), u.get("wallet_address"), u.get("email")) if k]
        with_biz = len(set(await _DB.businesses.distinct("owner", {"owner": {"$in": owner_keys}})))

        async def reached(qid: str) -> int:
            return len(set(await _DB.user_quests.distinct("user_id", {"user_id": {"$in": ids}, "quest_id": qid,
                                                                      "status": {"$in": ["ready", "claimed"]}})))
        first_sale = await reached("ob_first_sale")
        completed = await _DB.users.count_documents({"id": {"$in": ids}, "onboarding_completed_at": {"$exists": True}})
        out["groups"][g] = {
            "users": n,
            "has_business_pct": round(100.0 * min(with_biz, n) / n, 1),
            "first_sale_pct": round(100.0 * first_sale / n, 1),
            "onboarding_completed_pct": round(100.0 * completed / n, 1),
        }
    return out


# ───────────────────────────── translations (LibreTranslate) ─────────────────────────────
# Quest texts are written by hand in English and Russian. Every other project
# language (es, zh, fr, de, ja, ko, id) is translated from English through
# LibreTranslate and SAVED in the template itself:
#     quest_templates.title.<lang>, quest_templates.description.<lang>
#     quest_templates.i18n_auto.<field>.<lang> = true   (machine-made marker)
# Machine translations never overwrite a text an admin typed by hand, and they
# are dropped (re-made) when the English source changes.
PROJECT_LANGS = ["en", "ru", "es", "zh", "fr", "de", "ja", "ko", "id"]
MANUAL_LANGS = ("en", "ru")
AUTO_LANGS = [l for l in PROJECT_LANGS if l not in MANUAL_LANGS]
TEXT_FIELDS = ("title", "description")
_inflight: Dict[str, "asyncio.Task"] = {}
_warmup_started = False


def _lt_configured() -> bool:
    try:
        from translation_service import libretranslate_configured
        return libretranslate_configured()
    except Exception:
        return False


async def translate_templates(langs: Optional[List[str]] = None, ids: Optional[List[str]] = None,
                              force: bool = False) -> Dict[str, Any]:
    """Translate missing quest texts into `langs` (default: all auto languages)
    via LibreTranslate and store them in quest_templates. Safe to call often:
    only empty slots (or, with force, machine-made ones) are translated."""
    stats = {"translated": 0, "failed": 0, "skipped": 0, "errors": []}
    if not _lt_configured():
        stats["errors"].append("LIBRETRANSLATE_URL is not set")
        return stats
    from translation_service import translate_libre_protected
    langs = [l for l in (langs or AUTO_LANGS) if l in AUTO_LANGS]
    tpls = await get_templates(force=True)
    changed = False
    for t in tpls:
        if ids and t["id"] not in ids:
            continue
        auto = t.get("i18n_auto") or {}
        for field in TEXT_FIELDS:
            val = t.get(field) or {}
            if not isinstance(val, dict):
                continue
            src = val.get("en") or val.get("ru")
            src_lang = "en" if val.get("en") else "ru"
            if not src:
                continue
            for lang in langs:
                is_auto = bool((auto.get(field) or {}).get(lang))
                if val.get(lang) and not (force and is_auto):
                    stats["skipped"] += 1
                    continue
                try:
                    out = await asyncio.wait_for(translate_libre_protected(src, lang, src_lang), timeout=20)
                except Exception as e:  # keep English for now, retry next time
                    stats["failed"] += 1
                    if len(stats["errors"]) < 5:
                        stats["errors"].append(f"{t['id']}.{field}.{lang}: {e}")
                    continue
                # do not clobber a manual text written meanwhile
                res = await _DB.quest_templates.update_one(
                    {"id": t["id"], "$or": [{f"{field}.{lang}": {"$exists": False}},
                                            {f"{field}.{lang}": ""},
                                            {f"i18n_auto.{field}.{lang}": True}]},
                    {"$set": {f"{field}.{lang}": out, f"i18n_auto.{field}.{lang}": True,
                              f"i18n_src.{field}": src}},
                )
                if res.modified_count:
                    stats["translated"] += 1
                    changed = True
    if changed:
        _tpl_cache["items"] = []
    return stats


def _schedule_translation(langs: Optional[List[str]] = None) -> "asyncio.Task":
    """One background translation job per language set (deduplicated)."""
    key = ",".join(sorted(langs)) if langs else "*"
    task = _inflight.get(key)
    if task and not task.done():
        return task

    async def _run():
        try:
            st = await translate_templates(langs)
            if st["translated"] or st["failed"]:
                logger.info(f"quests: LibreTranslate {key}: {st}")
        except Exception as e:
            logger.warning(f"quests: translation job failed: {e}")

    task = asyncio.get_event_loop().create_task(_run())
    _inflight[key] = task
    _bg.add(task)
    task.add_done_callback(_bg.discard)
    return task


async def ensure_lang(lang: str, tpls: List[Dict[str, Any]], wait_s: float = 5.0) -> bool:
    """Make sure the shown quests have texts in `lang`. Waits briefly for
    LibreTranslate; on timeout the job keeps running in the background and the
    player sees English this one time. Returns True if templates changed."""
    if lang not in AUTO_LANGS or not _lt_configured():
        return False
    if all(isinstance(t.get(f), dict) and t[f].get(lang) for t in tpls for f in TEXT_FIELDS if t.get(f)):
        return False
    task = _schedule_translation([lang])
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=wait_s)
    except asyncio.TimeoutError:
        return False
    return True


# Small set of player-facing errors: en/ru by hand, the rest via LibreTranslate
# (cached in translation_cache by translation_service.translate_cached).
_MSG = {
    "not_found": ("Quest not found", "Задание не найдено"),
    "not_ready": ("Quest is not completed yet", "Задание ещё не выполнено"),
    "already": ("Reward already claimed", "Награда уже получена"),
    "finish_first": ("Finish all onboarding quests first", "Сначала пройдите весь «Путь новичка»"),
    "bad_choice": ("Invalid reward choice", "Неверный выбор награды"),
    "received": ("Reward already received", "Награда уже получена"),
    "user": ("User not found", "Пользователь не найден"),
}


async def msg(key: str, lang: str) -> str:
    en, ru = _MSG.get(key, (key, key))
    if lang == "ru":
        return ru
    if lang == "en" or lang not in AUTO_LANGS or _DB is None or not _lt_configured():
        return en
    try:
        from translation_service import translate_cached
        return await asyncio.wait_for(translate_cached(_DB, en, lang, "en"), timeout=5)
    except Exception:
        return en


# ───────────────────────────── presentation ─────────────────────────────
def _serialize(t: Dict[str, Any], uq: Optional[Dict[str, Any]], lang: str) -> Dict[str, Any]:
    target = int(t.get("target", 1) or 1)
    progress = min(int((uq or {}).get("progress", 0) or 0), target)
    return {
        "id": t["id"], "kind": t["kind"], "difficulty": t.get("difficulty"),
        "title": _loc(t.get("title"), lang), "description": _loc(t.get("description"), lang),
        "progress": progress, "target": target,
        "status": (uq or {}).get("status", "active"),
        "reward": {"city": int(t.get("reward_city", 0) or 0), "xp": int(t.get("reward_xp", 0) or 0)},
        "deep_link": t.get("deep_link"),
        "event": t.get("event"),        # lets the app highlight the button that does the job
    }


async def _daily_cap(uid: str) -> Dict[str, int]:
    cfg = await _DB.tasks_config.find_one({"key": "quest_limits"}, {"_id": 0}) or {}
    cap = int(cfg.get("daily_bonus_cap_city", DEFAULT_DAILY_BONUS_CAP_CITY) or 0)
    u = await _DB.users.find_one({"id": uid}, {"_id": 0, "quest_bonus_today": 1}) or {}
    qb = u.get("quest_bonus_today") or {}
    used = int(qb.get("city", 0) or 0) if qb.get("date") == period_key("daily") else 0
    return {"cap_city": cap, "used_city": used}


async def build_overview(uid: str, lang: str) -> Dict[str, Any]:
    await sync_state(uid)
    _all = await get_templates()
    if await ensure_lang(lang, _all):
        _all = await get_templates(force=True)
    tpls = {t["id"]: t for t in _all}
    has_biz = await _has_business(uid)

    async def user_docs(kind: str) -> Dict[str, Dict[str, Any]]:
        rows = await _DB.user_quests.find({"user_id": uid, "kind": kind, "period_key": period_key(kind)}, {"_id": 0}).to_list(100)
        return {r["quest_id"]: r for r in rows}

    ob_docs = await user_docs("onboarding")
    onboarding = [_serialize(t, ob_docs.get(t["id"]), lang)
                  for t in sorted([t for t in tpls.values() if t["kind"] == "onboarding" and t.get("active", True)],
                                  key=lambda x: x.get("order", 0))]
    out: Dict[str, Any] = {}
    for kind in ("daily", "weekly"):
        ids = await ensure_assignment(uid, kind, has_biz)
        docs = await user_docs(kind)
        items = [_serialize(tpls[i], docs.get(i), lang) for i in ids if i in tpls and tpls[i].get("active", True)]
        out[kind] = {"items": items, "ends_at": period_end_iso(kind),
                     "all_claimed": bool(items) and all(x["status"] == "claimed" for x in items)}
    ob_done = sum(1 for x in onboarding if x["status"] == "claimed")
    ready = [x for x in onboarding + out["daily"]["items"] + out["weekly"]["items"] if x["status"] == "ready"]
    # "what to do next": claim something > next onboarding step > an active daily goal
    nxt = None
    if ready:
        nxt = {**ready[0], "action": "claim"}
    else:
        cand = next((x for x in onboarding if x["status"] == "active"), None) or \
               next((x for x in out["daily"]["items"] if x["status"] == "active"), None)
        if cand:
            nxt = {**cand, "action": "go"}
    u = await _DB.users.find_one({"id": uid}, {"_id": 0, "tutorial_t3_reward_granted": 1, "onboarding_group": 1}) or {}
    ob_completed = bool(onboarding) and ob_done == len(onboarding)
    return {
        "onboarding": {"items": onboarding, "done": ob_done, "total": len(onboarding),
                       "completed": ob_completed,
                       "reward": {"options": T3_REWARD_RESOURCES,
                                  "received": bool(u.get("tutorial_t3_reward_granted")),
                                  "available": ob_completed and not u.get("tutorial_t3_reward_granted")}},
        "onboarding_group": u.get("onboarding_group"),
        "daily": out["daily"], "weekly": out["weekly"],
        "ready_count": len(ready), "next": nxt,
        "has_business": has_biz,
        "bonus_cap": await _daily_cap(uid),
    }


async def claim(uid: str, quest_id: str, lang: str) -> Dict[str, Any]:
    t = next((x for x in await get_templates() if x["id"] == quest_id), None)
    if not t:
        raise HTTPException(status_code=404, detail=await msg("not_found", lang))
    pk = period_key(t["kind"])
    flt = {"user_id": uid, "quest_id": quest_id, "period_key": pk}
    # Atomic guard: only one request can flip ready -> claimed.
    res = await _DB.user_quests.update_one({**flt, "status": "ready"},
                                           {"$set": {"status": "claimed", "claimed_at": _iso_now(), "updated_at": _iso_now()}})
    if res.modified_count == 0:
        doc = await _DB.user_quests.find_one(flt, {"_id": 0, "status": 1})
        if doc and doc.get("status") == "claimed":
            raise HTTPException(status_code=409, detail=await msg("already", lang))
        raise HTTPException(status_code=400, detail=await msg("not_ready", lang))

    want_city = int(t.get("reward_city", 0) or 0)
    xp = int(t.get("reward_xp", 0) or 0)
    cap = await _daily_cap(uid)
    allowed = max(0, cap["cap_city"] - cap["used_city"])
    city = min(want_city, allowed)
    capped = city < want_city
    inc: Dict[str, Any] = {}
    tax = 0.0
    if city > 0:
        try:                                      # the alliance tax (0 without an alliance) goes to its treasury
            import alliances as _al
            tax = await _al.take_tax(_DB, uid, city, "quest")
        except Exception:
            tax = 0.0
        await _DB.users.update_one({"id": uid, "bonus_balance": None}, {"$set": {"bonus_balance": 0.0}})
        inc["bonus_balance"] = (city - tax) / CITY_PER_TON
    if xp > 0:
        await _DB.users.update_one({"id": uid, "xp": None}, {"$set": {"xp": 0}})
        inc["xp"] = xp
    if inc:
        await _DB.users.update_one({"id": uid}, {"$inc": inc})
    if city > 0:
        today = period_key("daily")
        await _DB.users.update_one({"id": uid}, {"$set": {"quest_bonus_today": {"date": today, "city": cap["used_city"] + city}}})
        try:
            await _DB.transactions.insert_one({
                "id": str(uuid.uuid4()), "tx_type": "quest_reward", "type": "quest_reward", "user_id": uid,
                "amount": (city - tax) / CITY_PER_TON, "amount_ton": (city - tax) / CITY_PER_TON, "reward_city": city,
                "alliance_tax_city": tax,
                "description": f"Quest reward ({quest_id}): +{city} $CITY (bonus)" + (f", alliance tax {tax:g}" if tax else ""), "status": "completed",
                "created_at": _iso_now(), "completed_at": _iso_now(),
            })
        except Exception as e:
            logger.warning(f"quests: tx log failed: {e}")
    await track(uid, "quest_claimed", quest_id=quest_id, kind=t["kind"], city=city, xp=xp)
    try:   # leagues: a claimed daily / weekly goal = activity points
        import leagues
        import city_pass
        if t["kind"] in ("daily", "weekly"):
            _act = "daily_goal" if t["kind"] == "daily" else "weekly_goal"
            leagues.activity_bg(uid, _act, 1)
        # City Pass gets EXACTLY the XP written on the quest card (newbie, daily and weekly alike),
        # right now — not in the background — so the app shows it at once
        if xp > 0:
            await city_pass.add_xp(_DB, uid, "quest", xp)
    except Exception as _xe:
        logger.debug(f"quests: city pass xp failed: {_xe}")
    shield_granted = False
    if t["kind"] == "weekly":
        shield_granted = await _maybe_weekly_shield(uid)
    return {"ok": True, "quest_id": quest_id,
            "granted": {"city": city, "xp": xp, "capped": capped, "shield": shield_granted}}


async def _maybe_weekly_shield(uid: str) -> bool:
    """All weekly quests claimed -> +1 streak shield, at most once per week."""
    pk = period_key("weekly")
    ids = await ensure_assignment(uid, "weekly")
    if not ids:
        return False
    claimed = await _DB.user_quests.count_documents(
        {"user_id": uid, "kind": "weekly", "period_key": pk, "quest_id": {"$in": ids}, "status": "claimed"})
    if claimed < len(ids):
        return False
    # once per week (atomic)
    res = await _DB.users.update_one({"id": uid, "shield_week": {"$ne": pk}}, {"$set": {"shield_week": pk}})
    if res.modified_count == 0:
        return False
    try:
        import comeback
        comeback.init(_DB) if comeback._DB is None else None
        await comeback.add_shields(uid, 1)
        await track(uid, "streak_shield_earned", source="weekly")
        return True
    except Exception as e:
        logger.warning(f"quests: weekly shield grant failed: {e}")
        return False


# ───────────────────────────── routers ─────────────────────────────
class TemplatePatch(BaseModel):
    # texts: {"en": "...", "ru": "...", "id": "..."} — any language; a language
    # given here is treated as hand-written and never machine-overwritten.
    title: Optional[Dict[str, str]] = None
    description: Optional[Dict[str, str]] = None
    reward_city: Optional[int] = None
    reward_xp: Optional[int] = None
    target: Optional[int] = None
    active: Optional[bool] = None


def create_quests_router(db, get_current_user, get_current_admin) -> APIRouter:
    init(db)
    router = APIRouter(prefix="/api/quests", tags=["quests"])
    admin = APIRouter(prefix="/api/admin/quests", tags=["quests-admin"])

    async def _uid_lang(current_user) -> tuple:
        keys = [k for k in (getattr(current_user, "id", None), getattr(current_user, "wallet_address", None),
                            getattr(current_user, "email", None)) if k]
        u = await db.users.find_one({"$or": [{"id": k} for k in keys] + [{"wallet_address": k} for k in keys]
                                     + [{"email": k} for k in keys]}, {"_id": 0, "id": 1, "language": 1}) if keys else None
        if not u:
            raise HTTPException(status_code=404, detail="User not found")
        return u["id"], (u.get("language") or "en")

    @router.get("")
    async def my_quests(current_user=Depends(get_current_user)):
        uid, lang = await _uid_lang(current_user)
        return await build_overview(uid, lang)

    @router.get("/next")
    async def next_quest(current_user=Depends(get_current_user)):
        uid, lang = await _uid_lang(current_user)
        return {"next": (await build_overview(uid, lang)).get("next")}

    @router.get("/ready-count")
    async def ready_count(current_user=Depends(get_current_user)):
        """Cheap counter for the red dot on the «Задания» menu item."""
        uid, _lang = await _uid_lang(current_user)
        await sync_state(uid)
        n = await db.user_quests.count_documents({"user_id": uid, "status": "ready", "$or": [
            {"kind": "onboarding"},
            {"kind": "daily", "period_key": period_key("daily")},
            {"kind": "weekly", "period_key": period_key("weekly")},
        ]})
        # + ordinary tasks (subscribe / link / partner …) whose reward is waiting
        from core.ttl_cache import cached as _cached
        active_task_ids = await _cached("tasks:active_ids", 60, lambda: db.tasks.distinct("id", {"active": True}), owner=db)
        t = await db.user_task_status.count_documents(
            {"user_id": uid, "status": "ready_to_claim", "task_id": {"$in": active_task_ids}}) if active_task_ids else 0
        return {"ready": n + t, "quests": n, "tasks": t}

    @router.post("/{quest_id}/claim")
    async def claim_quest(quest_id: str, current_user=Depends(get_current_user)):
        uid, lang = await _uid_lang(current_user)
        return await claim(uid, quest_id, lang)

    class RewardChoice(BaseModel):
        choice: str

    @router.post("/onboarding/reward")
    async def onboarding_reward(body: RewardChoice, current_user=Depends(get_current_user)):
        uid, lang = await _uid_lang(current_user)
        return await grant_onboarding_reward(uid, body.choice, lang)

    @admin.get("/onboarding-stats")
    async def admin_onboarding_stats(_=Depends(get_current_admin)):
        return await onboarding_stats()

    @admin.get("/templates")
    async def admin_templates(_=Depends(get_current_admin)):
        return {"templates": await get_templates(force=True)}

    @admin.put("/templates/{quest_id}")
    async def admin_update_template(quest_id: str, patch: TemplatePatch, _=Depends(get_current_admin)):
        raw = {k: v for k, v in patch.model_dump().items() if v is not None}
        if not raw:
            raise HTTPException(status_code=400, detail="Nothing to update")
        await get_templates()  # make sure defaults are seeded
        cur = await db.quest_templates.find_one({"id": quest_id}, {"_id": 0})
        if not cur:
            raise HTTPException(status_code=404, detail="Quest not found")
        upd: Dict[str, Any] = {}
        unset: Dict[str, str] = {}
        retranslate = False
        for field in TEXT_FIELDS:
            texts = raw.pop(field, None)
            if not texts:
                continue
            for lang, txt in texts.items():
                if lang not in PROJECT_LANGS or not isinstance(txt, str) or not txt.strip():
                    raise HTTPException(status_code=400, detail=f"Invalid {field}.{lang}")
                upd[f"{field}.{lang}"] = txt.strip()
                unset[f"i18n_auto.{field}.{lang}"] = ""          # now hand-written
            if "en" in texts and texts["en"].strip() != ((cur.get(field) or {}).get("en") or ""):
                # English source changed -> drop machine translations so they are re-made
                for lang, is_auto in ((cur.get("i18n_auto") or {}).get(field) or {}).items():
                    if is_auto and lang not in texts:
                        unset[f"{field}.{lang}"] = ""
                        unset[f"i18n_auto.{field}.{lang}"] = ""
                retranslate = True
        upd.update(raw)
        for k in ("reward_city", "reward_xp", "target"):
            if k in upd and upd[k] < (1 if k == "target" else 0):
                raise HTTPException(status_code=400, detail=f"Invalid {k}")
        op: Dict[str, Any] = {}
        if upd:
            op["$set"] = upd
        if unset:
            op["$unset"] = {k: v for k, v in unset.items() if k not in upd}
        r = await db.quest_templates.update_one({"id": quest_id}, op)
        if r.matched_count == 0:
            raise HTTPException(status_code=404, detail="Quest not found")
        _tpl_cache["items"] = []
        if retranslate and _lt_configured():
            _schedule_translation(None)
        return {"ok": True, "retranslating": bool(retranslate and _lt_configured())}

    @admin.post("/translate")
    async def admin_translate(force: bool = False, lang: Optional[str] = None, _=Depends(get_current_admin)):
        """Translate quest texts via LibreTranslate now (all languages or one)."""
        if lang and lang not in AUTO_LANGS:
            raise HTTPException(status_code=400, detail=f"lang must be one of {AUTO_LANGS}")
        return await translate_templates([lang] if lang else None, force=force)

    @admin.put("/limits")
    async def admin_limits(daily_bonus_cap_city: int, _=Depends(get_current_admin)):
        if daily_bonus_cap_city < 0:
            raise HTTPException(status_code=400, detail="Invalid cap")
        await db.tasks_config.update_one({"key": "quest_limits"},
                                         {"$set": {"key": "quest_limits", "daily_bonus_cap_city": int(daily_bonus_cap_city)}},
                                         upsert=True)
        return {"ok": True}

    # One include_router call in server.py wires both (no extra prefix).
    root = APIRouter()
    root.include_router(router)
    root.include_router(admin)
    return root
