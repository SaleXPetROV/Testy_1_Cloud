"""
GRAM-City Background Tasks V2.0 - Complete Economic Tick Engine
Handles: Auto-collection, Midnight Decay, Durability Wear,
NPC Interventions, Price Updates, Bankruptcy Checks, Events

TICK ORDER:
1. Production
2. Resource purchasing (consumption)
3. Maintenance deduction
4. Profit calculation
5. Income tax
6. Turnover tax
7. NPC consumption
8. Price updates
9. Monopoly check
10. Inflation
11. Bankruptcy check
12. Events
13. Save snapshot

DURABILITY RULES:
- 50-100%: 100% production
- 1-50%: 80% production
- 0%: Business stops
"""
import asyncio
import logging
import random
import uuid
from datetime import datetime, timezone, timedelta
from core.dtutils import to_aware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import UpdateOne
from pymongo.errors import BulkWriteError
import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / '.env')

from business_config import (
    BUSINESSES, BUSINESS_KEY_MAP, TIER_TAXES, MAINTENANCE_COSTS, RESOURCE_TYPES,
    BUSINESS_LEVELS, MIDNIGHT_DECAY_RATE,
    NPC_PRICE_FLOOR, NPC_PRICE_CEILING, MONOPOLY_THRESHOLD,
    get_production, get_consumption, get_consumption_breakdown,
    calculate_effective_production, get_daily_wear, get_storage_capacity,
    TIER3_BUFFS, get_warehouse_weight,
)
from game_systems import (
    BusinessEconomics, TaxSystem, NPCMarketSystem, WarehouseSystem,
    InflationSystem, BankruptcySystem, EventsSystem, EconomicTickEngine,
    IncomeCollector, resolve_business_buff, buff_multiplier, _is_contract_active,
)

# Resource name translations for notifications
RESOURCE_NAMES = {
    "energy": "Энергия", "cu": "Вычисления", "quartz": "Кварц", 
    "traffic": "Трафик", "cooling": "Охлаждение", "biomass": "Биомасса", "scrap": "Металлолом",
    "chips": "Микросхемы", "nft": "NFT-арт", "neurocode": "Нейрокод",
    "logistics": "Топливо", "repair_kits": "Ремкомплект", "vr_experience": "VR-опыт",
    "profit_ton": "Кибер-фуд",
    "neuro_core": "Нейро-ядро", "gold_bill": "Золотой вексель", "license_token": "Лицензия",
    "luck_chip": "Фишка удачи", "war_protocol": "Боевой протокол", 
    "bio_module": "Био-модуль", "gateway_code": "Код шлюза",
}

logger = logging.getLogger(__name__)

# Telegram Bot API base (override via TELEGRAM_API_BASE to route through a proxy).
TELEGRAM_API_BASE = os.environ.get(
    "TELEGRAM_API_BASE", "https://api.telegram.org"
).rstrip("/")


# MongoDB connection
mongo_url = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
db_name = os.environ.get('DB_NAME', 'ton_city')

# ── Shared MongoDB client for ALL background jobs ─────────────────────────
# Previously every scheduled job created its OWN `AsyncIOMotorClient` on each
# invocation. With ~11 jobs (some running every minute) that produced a
# continuous stream of new connection pools — the driver's pool cleanup and
# GC lag caused thousands of open connections to accumulate on the mongod
# server. On restart the leaking process still held them open while the new
# process opened another full set, which is enough to knock over a modest
# MongoDB instance (or hit the 'too many open files' ulimit).
#
# We now keep exactly ONE shared client per Python process. All jobs read
# `_get_shared_db()` and every previous `client.close()` inside a job is now
# a no-op (the pool lives for the whole process lifetime).
_shared_client: AsyncIOMotorClient | None = None
_shared_db = None


def _get_shared_db():
    """Return the process-wide shared Motor database, creating the client once."""
    global _shared_client, _shared_db
    if _shared_client is None:
        _shared_client = AsyncIOMotorClient(
            mongo_url,
            maxPoolSize=100,
            minPoolSize=5,
            maxIdleTimeMS=60000,
            waitQueueTimeoutMS=10000,
            serverSelectionTimeoutMS=10000,
            connectTimeoutMS=10000,
            retryWrites=True,
        )
        _shared_db = _shared_client[db_name]
    return _shared_db


def _close_shared_client():
    """Close the shared background-tasks client on interpreter shutdown."""
    global _shared_client, _shared_db
    if _shared_client is not None:
        try:
            _shared_client.close()
        except Exception:
            pass
        _shared_client = None
        _shared_db = None


import atexit
atexit.register(_close_shared_client)

# Global scheduler
scheduler: AsyncIOScheduler = None

# Import telegram notifications
try:
    from telegram_notifications import (
        notify_low_durability, notify_critical_durability, notify_business_stopped,
        notify_resources_full, get_user_telegram_chat_id, should_notify, clear_notification_state,
        notify_durability_warning_20,
        RESOURCE_NOTIFICATION_THRESHOLD
    )
    TELEGRAM_ENABLED = True
except ImportError:
    TELEGRAM_ENABLED = False
    logger.warning("Telegram notifications not available")

# Alliance notifications (in-app + telegram bridge, 8 langs)
try:
    from alliance_notifications import send_alliance_notification
except ImportError:
    async def send_alliance_notification(*args, **kwargs):  # noqa: D401
        return None


def get_durability_multiplier(durability: float) -> float:
    """
    Get production multiplier based on durability.
    50-100%: 100% production
    5-50%: 80% production
    0%: 0% production (stopped)
    """
    if durability <= 0:
        return 0.0
    elif durability < 50:
        return 0.8
    else:
        return 1.0


# The shift rule lives in core/business_rules.py (one copy for the whole game).
from core.business_rules import shift_is_active  # noqa: E402,F401  (re-exported)



async def _ensure_economic_tick_indexes(db) -> None:
    """Create the indexes economic_tick relies on. Idempotent — safe to call
    on every startup. Missing indexes turn every per-tick lookup/update into a
    full collection scan, which is the #1 reason a 1000-business tick takes
    75+ seconds instead of ~200 ms."""
    try:
        # businesses.id is used by every update_one filter.
        # (the UNIQUE index on id is made by core/plots.ensure_business_ids — don't add a 2nd one on the same key)
        try:
            _ix = [i async for i in db.businesses.list_indexes()]
            if not any(list((i.get("key") or {}).keys()) == ["id"] for i in _ix):
                await db.businesses.create_index("id", background=True)
        except Exception:
            pass
        # businesses.owner drives the group-by-user pass over storage.
        await db.businesses.create_index("owner", background=True)
        # Fast filter for the initial tick query and expiration checks.
        await db.businesses.create_index("paused_reason", background=True)
        # users.id / users.wallet_address are used as bulk_write filter keys.
        await db.users.create_index("id", background=True)
        await db.users.create_index("wallet_address", background=True)
        # Contract lookup by vassal + status (used by prefetch and per-biz).
        await db.contracts.create_index(
            [("vassal_business_id", 1), ("status", 1)], background=True
        )
        await db.contracts.create_index("id", background=True)
        # notifications.user_id for pending-notification scans. Uses the
        # unified `telegram_sent` field (previously the low-resource batch
        # used a separate `tg_sent` field which caused duplicate deliveries).
        await db.notifications.create_index(
            [("user_id", 1), ("type", 1), ("telegram_sent", 1)], background=True
        )
        # Supply contracts by status.
        await db.supply_contracts.create_index("status", background=True)
        logger.info("✅ Economic tick indexes ensured")
    except Exception as e:
        logger.warning(f"[economic-tick] index creation failed (non-fatal): {e}")


# ==================== MAIN ECONOMIC TICK ====================

async def economic_tick():
    """
    Main economic tick - runs every hour.
    Processes all active businesses through the 13-step pipeline.
    """
    try:
        logger.info("⚙️ === ECONOMIC TICK STARTED ===")
        
        db = _get_shared_db()
        
        now = datetime.now(timezone.utc)
        
        # Get ALL businesses (except bankrupt). is_active is re-evaluated each tick.
        # Trial Centers have their OWN wear/production model (routes/trial_center.py
        # _accrue, exactly 50%/day) — exclude them here to avoid double wear.
        businesses = await db.businesses.find({"paused_reason": {"$ne": "bankruptcy"}, "is_trial": {"$ne": True}}).to_list(length=None)
        
        if not businesses:
            logger.info("📊 No active businesses - tick skipped")
            # (shared client — no per-job close)
            pass
            return
        
        # Get current market prices — FIXED to configured base prices (the
        # pricing table). Always use base so business income and market use the
        # same fixed per-unit values.
        market_prices = {r: d["base_price"] for r, d in RESOURCE_TYPES.items()}
        await db.market_prices.update_one(
            {"type": "current"},
            {"$set": {"prices": market_prices, "updated_at": now.isoformat()}},
            upsert=True
        )
        
        # Get all users - index by both id AND wallet_address
        users = {}
        users_cursor = db.users.find({})
        async for user in users_cursor:
            uid = user.get("id")
            wallet = user.get("wallet_address")
            if uid:
                users[uid] = user
            if wallet:
                users[wallet] = user
            _em = user.get("email")
            if _em and _em not in users:
                users[_em] = user

        # === PERFORMANCE: BULK WRITE ACCUMULATORS ==========================
        # Every per-business/per-user Mongo write below is appended to these
        # lists and then flushed in ONE bulk_write per collection at the end
        # of the tick. Previous implementation did 3–6 round-trips PER
        # business (=> N+1 explosion at ~1k businesses -> 75 s ticks). Now
        # the entire tick is bounded by O(businesses) CPU work + O(1)
        # network I/O.
        businesses_bulk: list = []
        users_bulk: list = []
        notifications_batch: list = []
        contracts_bulk: list = []
        pending_tg_tasks: list = []  # (coroutine_factory,) — fired at end

        def _schedule_tg(coro_fn):
            """Queue a Telegram/HTTP side-effect to run AFTER the tick
            writes so slow network calls never block the DB pass."""
            try:
                pending_tg_tasks.append(coro_fn)
            except Exception:
                pass

        def _user_filter(owner_key):
            """Prefer the fast primary-key filter when we know it, otherwise
            fall back to the legacy $or. `users` was prefetched above by
            both `id` and `wallet_address`, so we can pick whichever field
            the owner string actually indexes into."""
            u = users.get(owner_key)
            if u is not None:
                # Native _id is the fastest single-field index in Mongo.
                if "_id" in u:
                    return {"_id": u["_id"]}
                if u.get("id") == owner_key:
                    return {"id": owner_key}
                if u.get("wallet_address") == owner_key:
                    return {"wallet_address": owner_key}
            return {"$or": [{"wallet_address": owner_key}, {"id": owner_key}]}

        
        # Track totals
        total_tax_collected = 0
        total_maintenance_collected = 0
        total_production = {}
        total_consumption = {}
        tick_results = []
        businesses_processed = 0
        wear_applied_count = 0

        # === PER-USER RESOURCE BUFFS ===
        # Pre-compute active resource buffs per user (production_multiplier, consumption_multiplier, crit_chance_bonus)
        # These are user-activated T3 resource buffs; apply on top of patron/contract buffs.
        def _compute_user_resource_buffs(user_doc):
            prod_m, cons_m, crit_p = 1.0, 1.0, 0.0
            if not user_doc:
                return prod_m, cons_m, crit_p
            for rb in (user_doc.get("active_resource_buffs") or []):
                if not isinstance(rb, dict):
                    continue
                et = rb.get("effect_type")
                ev = rb.get("effect_value")
                if et is None or ev is None:
                    continue
                exp_raw = rb.get("expires_at")
                if exp_raw:
                    try:
                        exp_dt = datetime.fromisoformat(str(exp_raw).replace('Z', '+00:00'))
                        if exp_dt <= now:
                            continue
                    except (ValueError, TypeError):
                        continue
                try:
                    fv = float(ev)
                except (TypeError, ValueError):
                    continue
                if et == "production_multiplier":
                    prod_m *= fv
                elif et == "consumption_multiplier":
                    cons_m *= fv
                elif et == "crit_chance_bonus":
                    crit_p = max(crit_p, fv)  # keep the best single chance
            return prod_m, cons_m, crit_p

        user_resource_buffs = {}  # owner_id -> (prod_m, cons_m, crit_p)

        # === PRE-COMPUTE PER-USER STORAGE FULLNESS ===
        # If a user's total warehouse (personal resources + business storage) is full,
        # all their businesses go idle until space frees up.
        # We also track *running* used/cap per user so that within a tick we can
        # detect overflow caused by THIS tick's production and block the next
        # business in line — preventing any over-cap accumulation (fix #5).
        user_storage_full = {}
        user_storage_used = {}
        user_storage_cap = {}
        user_businesses_map = {}

        def _canon(owner_key):
            """One key per player. A player's businesses may be owned by id,
            wallet or e-mail (legacy data); grouping by the raw string split
            one warehouse into several and under-counted capacity/usage."""
            if not owner_key:
                return owner_key
            return (users.get(owner_key) or {}).get("id") or owner_key

        for biz in businesses:
            owner = biz.get("owner")
            if owner:
                user_businesses_map.setdefault(_canon(owner), []).append(biz)

        # Pre-fetch active contracts for all vassal businesses (one query).
        biz_ids = [b["id"] for b in businesses if b.get("id")]
        active_contracts_by_biz = {}
        if biz_ids:
            async for c in db.contracts.find(
                {"vassal_business_id": {"$in": biz_ids}, "status": "active"}, {"_id": 0}
            ):
                active_contracts_by_biz[c["vassal_business_id"]] = c

        # Cache patron businesses lookups
        patron_biz_cache = {}

        async def _get_patron_biz(pid):
            if not pid:
                return None
            if pid in patron_biz_cache:
                return patron_biz_cache[pid]
            doc = await db.businesses.find_one({"id": pid}, {"_id": 0})
            patron_biz_cache[pid] = doc
            return doc

        # Resolve active buff for each business
        biz_buff_map = {}
        for biz in businesses:
            contract_doc = active_contracts_by_biz.get(biz.get("id"))
            patron_doc = await _get_patron_biz(biz.get("patron_id")) if biz.get("patron_id") else None
            biz_buff_map[biz["id"]] = resolve_business_buff(biz, contract_doc, patron_doc)

        # Resources listed on the market still occupy the warehouse until they
        # are sold or the lot is cancelled. The UI (/my/businesses) and
        # /market/buy count them; the tick did not, so it thought there was
        # free space and kept businesses producing over a full warehouse.
        listed_weight = {}
        from core import warehouse as _wh
        try:
            async for _lst in db.market_listings.find(
                {"status": "active", "is_bot": {"$ne": True}},
                {"_id": 0, "seller_id": 1, "seller_email": 1, "resource_type": 1, "amount": 1},
            ):
                _w = _wh.used_by_listing(_lst)
                if _w <= 0:
                    continue
                _u = users.get(_lst.get("seller_id")) or users.get(_lst.get("seller_email"))
                if not _u or not _u.get("id"):
                    continue
                listed_weight[_u["id"]] = listed_weight.get(_u["id"], 0) + _w
        except Exception as _le:
            logger.warning(f"tick: could not load market listings for warehouse usage: {_le}")

        for owner, owner_bizs in user_businesses_map.items():
            user = users.get(owner, {})
            # Personal resources count
            user_resources = user.get("resources", {})
            # Same rule as the UI and the market (core/warehouse.py)
            personal_used = _wh.used_by_resources(user_resources)
            # Business storage items are NOT added here — they're already in user.resources.
            # Active market listings DO occupy space (same as the UI).
            total_biz_used = listed_weight.get(user.get("id") or owner, 0)
            total_used = personal_used + total_biz_used
            # Total capacity: buffed storage of all the player's businesses (min 50)
            total_cap = _wh.total_capacity(owner_bizs, biz_buff_map)
            # Storage is full if used >= capacity (and capacity > 0)
            user_storage_full[owner] = (total_cap > 0 and total_used >= total_cap)
            user_storage_used[owner] = total_used
            user_storage_cap[owner] = total_cap
            if user_storage_full[owner]:
                logger.info(f"⏸️ User {owner[:12]}... storage full ({total_used}/{total_cap}) - all businesses idle")

        # === SMART NOTIFICATIONS: warehouse almost full / full (state machine) ===
        # Fires on UPWARD transitions only (ok -> almost -> full), deduplicated in
        # users.smart_state.warehouse, so the player hears about it once per fill.
        smart_events = []
        try:
            import smart_notify as _sn
            for _owner, _bizs in user_businesses_map.items():
                _u = users.get(_owner)
                if not _u or not _u.get("id"):
                    continue
                _running = sum(1 for _b in _bizs if shift_is_active(_b, now))
                _new_state, _kind = _sn.warehouse_event(
                    _u, user_storage_used.get(_owner, 0), user_storage_cap.get(_owner, 0), _running)
                if _new_state != (_u.get("smart_state") or {}).get("warehouse", "ok"):
                    await db.users.update_one({"id": _u["id"]}, {"$set": {"smart_state.warehouse": _new_state}})
                    _u.setdefault("smart_state", {})["warehouse"] = _new_state
                if _kind:
                    _cap = user_storage_cap.get(_owner, 0) or 1
                    smart_events.append((_u, _kind, {
                        "count": _running,
                        "pct": int(min(100, round(100.0 * user_storage_used.get(_owner, 0) / _cap))),
                    }, "warehouse"))
        except Exception as _se:
            logger.warning(f"smart warehouse notifications skipped: {_se}")

        # === SMART NOTIFICATIONS: shift finished → "come back and start a shift" ===
        # One message per player for all businesses whose shift ended since the
        # last tick (persistent dedupe: businesses.shift_end_notified = the
        # shift_ends_at already reported). Shifts that ended long ago (e.g. on
        # first deploy) are only marked, never notified.
        # === AUTO-SHIFT (booster from the City Pass) ===
        # While users.auto_shift_until is in the future the shift follows the
        # business's ability to work:
        #   • it can work (inputs for at least an hour, warehouse not full,
        #     durability > 0)  -> a finished shift starts again right away;
        #   • it cannot      -> no shift is started, and a shift that was
        #     auto-started is stopped, so the business idles WITHOUT wearing
        #     down; `auto_wait_reason` tells the player why. As soon as the
        #     problem is fixed, the next tick (1 min) starts the shift.
        # The business dicts are shared with the loop below.
        auto_owners = set()
        try:
            from boosters import auto_shift_active as _auto_on
            from core.business_rules import SHIFT_DURATION_HOURS as _SHIFT_H
            _auto_ops = []
            for _owner, _bizs in user_businesses_map.items():
                _u = users.get(_owner)
                if not _u or not _auto_on(_u, now):
                    continue
                auto_owners.add(_owner)
                _res = (_u.get("resources") or {})
                _full = bool(user_storage_full.get(_owner))
                for _b in _bizs:
                    if (_b.get("on_sale") or _b.get("status") == "on_sale") and not _b.get("is_zero_business"):
                        continue
                    if _b.get("tutorial") or _b.get("is_trial"):
                        continue
                    # the auto-shift booster works on EVERY business of the player, level 0 included
                    # (without the booster a level-0 business starts only by «Начать смену»)
                    _reason = None
                    if float(_b.get("durability", 100) or 0) <= 0:
                        _reason = "durability_zero"
                    elif _full:
                        _reason = "storage_full"
                    else:
                        _ct = BUSINESS_KEY_MAP.get(_b.get("business_type"), _b.get("business_type"))
                        for _inp, _per_day in (get_consumption_breakdown(_ct, _b.get("level", 1)) or {}).items():
                            if float(_res.get(_inp, 0) or 0) < float(_per_day) / 24.0:
                                _reason = "no_resources"
                                break
                    _running = shift_is_active(_b, now)
                    _set = {}
                    if _reason:
                        if _running and _b.get("shift_auto_started"):
                            _b["shift_ends_at"] = now.isoformat()        # stop: idle without wear
                            _set["shift_ends_at"] = now.isoformat()
                        if _b.get("auto_wait_reason") != _reason:
                            _set["auto_wait_reason"] = _reason
                        _b["auto_wait_reason"] = _reason
                    else:
                        if not _running:
                            _ns, _ne = now.isoformat(), (now + timedelta(hours=_SHIFT_H)).isoformat()
                            _b["shift_started_at"], _b["shift_ends_at"] = _ns, _ne
                            _b["shift_auto_started"] = True
                            _set.update({"shift_started_at": _ns, "shift_ends_at": _ne, "shift_auto_started": True})
                        if _b.get("auto_wait_reason"):
                            _set["auto_wait_reason"] = None
                        _b["auto_wait_reason"] = None
                    if _set:
                        _auto_ops.append(UpdateOne({"id": _b.get("id")}, {"$set": _set}))
            if _auto_ops:
                await db.businesses.bulk_write(_auto_ops, ordered=False)
        except Exception as _ase:
            logger.warning(f"auto-shift skipped: {_ase}")

        try:
            from core.business_rules import auto_operates as _auto_op
            from business_config import BUSINESSES as _BIZ_CFG
            from core.notif_i18n import user_lang as _ulang2
            _mark_ops = []
            for _owner, _bizs in user_businesses_map.items():
                _u = users.get(_owner)
                if not _u or not _u.get("id") or _owner in auto_owners:
                    continue
                _fresh, _ids, _latest = [], [], ""
                for _b in _bizs:
                    _se_at = _b.get("shift_ends_at")
                    if not _se_at or _auto_op(_b) or _b.get("shift_end_notified") == _se_at:
                        continue
                    try:
                        _se_dt = datetime.fromisoformat(str(_se_at).replace("Z", "+00:00"))
                        if _se_dt.tzinfo is None:
                            _se_dt = _se_dt.replace(tzinfo=timezone.utc)
                    except ValueError:
                        continue
                    if _se_dt > now:
                        continue                     # shift still running
                    _mark_ops.append(UpdateOne({"id": _b.get("id")}, {"$set": {"shift_end_notified": _se_at}}))
                    if (now - _se_dt).total_seconds() > 2 * 3600:
                        continue                     # ended long ago: mark only
                    _lang2 = _ulang2(_u)
                    _nm = (_BIZ_CFG.get(_b.get("business_type"), {}) or {}).get("name", {}) or {}
                    _fresh.append(_nm.get(_lang2) or _nm.get("en") or _b.get("business_type") or "?")
                    _ids.append(_b.get("id"))
                    _latest = max(_latest, str(_se_at))
                if _fresh:
                    smart_events.append((_u, "shift_ended", {
                        "names": ", ".join(_fresh[:5]) + ("…" if len(_fresh) > 5 else ""),
                        "count": len(_fresh), "business_ids": ",".join(_ids),
                    }, f"shift:{_latest}"))
            if _mark_ops:
                await db.businesses.bulk_write(_mark_ops, ordered=False)
        except Exception as _she:
            logger.warning(f"shift-ended notifications skipped: {_she}")
        
        # === PROCESS EACH BUSINESS (Steps 1-6) ===
        for business in businesses:
            try:
                business_id = business.get("id")
                owner = business.get("owner")
                business_type = business.get("business_type")
                level = business.get("level", 1)
                durability = business.get("durability", 100)
                
                # Пропускаем бизнес, выставленный на продажу — без производства и износа.
                # ИСКЛЮЧЕНИЕ: арендованный бизнес 0-го уровня (is_zero_business) с
                # действующей арендой продолжает производить ресурсы, пока владелец
                # им владеет. Он авто-листится на маркетплейсе с рождения, но это не
                # должно останавливать его производство до конца аренды/выкупа/изъятия.
                _zero_active_lease = (
                    business.get("is_zero_business")
                    and int(business.get("level", 1) or 0) == 0
                    and not business.get("is_seized")
                )
                if (business.get("on_sale") or business.get("status") == "on_sale") and not _zero_active_lease:
                    continue

                # === WORK SHIFT GATE (8h) ===
                # If the business's shift is not running it is idle: no
                # production and NO durability wear. We advance the wear/tick
                # clocks to `now` so restarting the shift never triggers a
                # backlogged wear/production burst.
                if not shift_is_active(business, now):
                    businesses_bulk.append(UpdateOne(
                        {"id": business_id},
                        {"$set": {
                            "is_active": False,
                            "work_status": "idle",
                            "work_status_reason": business.get("auto_wait_reason") or "shift_ended",
                            "last_wear_update": now.isoformat(),
                            "last_tick": now.isoformat(),
                        }}
                    ))
                    continue

                # Resolve alias (e.g. cold_storage → hydro_cooling)
                canonical_type = BUSINESS_KEY_MAP.get(business_type, business_type)
                config = BUSINESSES.get(canonical_type, {})
                tier = config.get("tier", 1)
                
                # === STEP 1: DURABILITY WEAR (independent timer) ===
                # Wear MUST use its own clock (last_wear_update), NOT last_tick/
                # last_collection — those are reset by income-collection endpoints,
                # which previously caused some businesses (e.g. quartz_mine on the
                # island) to never wear. Fallback to legacy timers only on first run.
                wear_ref = (business.get("last_wear_update")
                            or business.get("last_tick")
                            or business.get("last_collection"))
                wear_hours = 1.0
                if wear_ref:
                    try:
                        wref_dt = datetime.fromisoformat(str(wear_ref).replace('Z', '+00:00'))
                        wear_hours = max(0.0, (now - wref_dt).total_seconds() / 3600)
                    except (ValueError, TypeError):
                        wear_hours = 1.0 / 1440
                old_durability = business.get("durability", 100)
                wear_result = BusinessEconomics.apply_wear(business, wear_hours)
                new_durability = wear_result["durability"]
                wear_applied_count += 1
                
                # Unknown/legacy business types: still apply wear, then skip production.
                if not business_type or (business_type not in BUSINESSES and business_type not in BUSINESS_KEY_MAP):
                    businesses_bulk.append(UpdateOne(
                        {"id": business_id},
                        {"$set": {"durability": new_durability, "last_wear_update": now.isoformat()}}
                    ))
                    continue
                
                # Calculate time since last tick (PRODUCTION timer)
                last_tick = business.get("last_tick") or business.get("last_collection")
                hours_passed = 1.0  # Default to 1 hour
                if last_tick:
                    try:
                        last_dt = datetime.fromisoformat(str(last_tick).replace('Z', '+00:00'))
                        hours_passed = (now - last_dt).total_seconds() / 3600
                    except (ValueError, TypeError):
                        hours_passed = 1.0 / 1440  # fallback: 1 minute
                
                # Skip PRODUCTION if less than 30 seconds since last tick,
                # but STILL persist the wear computed above.
                if hours_passed < 0.008:  # ~30 seconds
                    businesses_bulk.append(UpdateOne(
                        {"id": business_id},
                        {"$set": {"durability": new_durability, "last_wear_update": now.isoformat()}}
                    ))
                    continue
                
                # Skip production if user's total warehouse is full
                storage_blocked = user_storage_full.get(_canon(owner), False)
                
                # --- DURABILITY NOTIFICATIONS (smart: in-app + Telegram) ---
                # One alert when a business drops below 20%, one when it stops
                # at 0%; re-armed after repair (>= 50%). Flags are stored on the
                # business (persistent — survives restarts, unlike the old
                # in-memory Telegram-only alerts at 50/20/10/0%). Delivery,
                # daily cap and quiet hours are handled by smart_notify.
                _smart_flags = None
                try:
                    import smart_notify as _sn
                    _dkind, _dflags = _sn.durability_event(business, old_durability, new_durability)
                    if _dflags != (business.get("smart_notified") or {}):
                        _smart_flags = _dflags
                    if _dkind:
                        _cached_user = users.get(owner) or {}
                        from core.notif_i18n import user_lang as _ulang
                        _lang = _ulang(_cached_user)
                        _names = config.get("name", {}) or {}
                        biz_name = _names.get(_lang) or _names.get("en") or _names.get("ru") or business_type
                        if _cached_user.get("id"):
                            smart_events.append((_cached_user, _dkind,
                                                 {"name": biz_name, "pct": int(max(0, new_durability))}, business_id))
                except Exception as _de:
                    logger.debug(f"smart durability notify skipped: {_de}")

                # --- Get durability multiplier ---
                durability_mult = get_durability_multiplier(new_durability)
                
                # If business is stopped (0% durability), skip production
                if durability_mult == 0:
                    # Update only durability, no production. Stamp when durability
                    # first hit 0 so the seizure job can enforce the 7-day rule.
                    _zero_set = {"durability": 0, "status": "stopped",
                                 "work_status": "stopped", "work_status_reason": "durability_zero",
                                 "is_active": False,
                                 "last_tick": now.isoformat(), "last_wear_update": now.isoformat()}
                    if not business.get("zero_durability_since"):
                        _zero_set["zero_durability_since"] = now.isoformat()
                    if _smart_flags is not None:
                        _zero_set["smart_notified"] = _smart_flags
                    businesses_bulk.append(UpdateOne({"id": business_id}, {"$set": _zero_set}))
                    continue
                
                # --- Step 1b: Production ---
                business_copy = {**business, "durability": new_durability}
                # Legacy patron-type bonus (Bank +5%, Validator +5..15%) disabled per spec.
                # The only patron value comes from the chosen TIER3_BUFFS (Стахановец etc.).
                patron_bonus = 1.0

                # Resolve active buff (contract_buff if contract is still active; else patron's patron_buff)
                active_buff = biz_buff_map.get(business_id, {}) or {}
                buff_effect = active_buff.get("effect", {}) if active_buff else {}
                buff_type = buff_effect.get("type", "")
                buff_value = buff_effect.get("value", 1.0)
                
                effective_prod = calculate_effective_production(
                    canonical_type, level, new_durability, patron_bonus
                )
                produces = config.get("produces")
                
                # Apply Стахановец buff (+7% production) from patron/contract
                if buff_type == "production_multiplier":
                    effective_prod = effective_prod * buff_value

                # === USER RESOURCE BUFFS (owner-level) ===
                if owner not in user_resource_buffs:
                    user_resource_buffs[owner] = _compute_user_resource_buffs(users.get(owner))
                u_prod_m, u_cons_m, u_crit_p = user_resource_buffs[owner]

                # Разгон системы (neuro_core +8%)
                if u_prod_m != 1.0:
                    effective_prod = effective_prod * u_prod_m

                # Apply Сенсорный контроль (patron crit_chance_bonus) + Фортуна (resource crit_chance_bonus)
                # Independent chances. If either succeeds, production x2 once.
                # F21: use CSPRNG (SystemRandom) so a player with local access
                # can't predict/replay crit rolls that produce free resources.
                import secrets as _secrets_crit
                _rng_crit = _secrets_crit.SystemRandom()
                patron_crit_p = buff_value if buff_type == "crit_chance_bonus" else 0.0
                crit_hit = False
                if patron_crit_p > 0 and _rng_crit.random() < patron_crit_p:
                    crit_hit = True
                if not crit_hit and u_crit_p > 0 and _rng_crit.random() < u_crit_p:
                    crit_hit = True
                if crit_hit:
                    effective_prod = effective_prod * 2.0
                    logger.info(f"🎯 CRIT! Business {business_id}: x2 production (patron_p={patron_crit_p}, resource_p={u_crit_p})")

                # Scale production by hours passed (production values are per-tick/day)
                hourly_fraction = hours_passed / 24.0
                actual_production = effective_prod * hourly_fraction
                
                # --- Step 2: Consumption ---
                # Formula: daily_consumption / 24 / 60 * minutes_passed
                # = daily_consumption * hours_passed / 24
                # Keeps 6 decimal places to avoid rounding error (e.g. 25/1440 = 0.017361, not 0.02)
                consumption_breakdown = get_consumption_breakdown(canonical_type, level)
                # Apply consumption multipliers: patron (lean_production -5%) × resource (bio_module -10%)
                patron_cons_mult = buff_value if buff_type == "consumption_multiplier" else 1.0
                consumption_multiplier = patron_cons_mult * u_cons_m
                scaled_consumption = {}
                for r, daily_amount in consumption_breakdown.items():
                    fractional = round(daily_amount * hourly_fraction * consumption_multiplier, 6)
                    scaled_consumption[r] = fractional
                
                # Check user's resource inventory
                user = users.get(owner, {})
                user_resources = user.get("resources", {})
                
                # Второй шанс: 2% chance to skip resource consumption.
                # F21: CSPRNG for money-relevant probability.
                import secrets as _secrets_free
                _rng_free = _secrets_free.SystemRandom()
                free_cycle = False
                if buff_type == "free_cycle_chance" and _rng_free.random() < buff_value:
                    free_cycle = True
                
                can_operate = True
                if consumption_breakdown and not free_cycle:
                    for resource, required in scaled_consumption.items():
                        available = user_resources.get(resource, 0)
                        if required > 0 and available < required:
                            can_operate = False
                            logger.info(f"⛔ {business_id} ({business_type}): need {required:.4f} {resource}, have {available:.2f}")
                            break
                
                if not can_operate:
                    actual_production = 0
                    # Apply 3x total durability loss when idle (extra 2x on top of normal wear)
                    from game_systems import get_daily_wear
                    daily_wear = get_daily_wear(canonical_type, level)
                    # Idle (insufficient resources): total 45%/day = 30% base
                    # + 0.5× extra. (spec: active 30%/day, idle 45%/day)
                    extra_wear = daily_wear * 100 * (hours_passed / 24.0) * 0.5
                    new_durability = max(0, new_durability - extra_wear)
                    logger.info(f"⛔ Business {business_id} ({business_type}) idle - insufficient resources, extra wear={extra_wear:.2f}%")
                
                # If storage is full - production blocked regardless
                if storage_blocked:
                    actual_production = 0
                    can_operate = False
                    logger.info(f"📦 Business {business_id} ({business_type}) idle - storage full")

                # Running cap check (fix #5): even if pre-tick snapshot said
                # there's space, this tick's accumulating production from
                # earlier businesses could push the user over capacity. Block
                # this business's production+consumption when adding the
                # produced units would exceed the user's total warehouse cap.
                if (not storage_blocked) and can_operate and actual_production > 0 and produces and produces != "ton":
                    import math as _math
                    _ck = _canon(owner)
                    cap_for_owner = user_storage_cap.get(_ck, 0)
                    used_for_owner = user_storage_used.get(_ck, 0)
                    weight_per_unit = get_warehouse_weight(produces)
                    # Round the weighted contribution UP. Per-tick production is
                    # fractional (<1 unit) on a 1-minute tick, so the previous
                    # int() floored it to 0 and the check was a no-op — letting
                    # every business overflow the warehouse a little each tick.
                    # ceil() guarantees a full warehouse blocks the business
                    # instead of silently over-filling it.
                    incoming_weight = _math.ceil(actual_production * weight_per_unit)
                    if cap_for_owner > 0 and (used_for_owner + incoming_weight) > cap_for_owner:
                        actual_production = 0
                        can_operate = False
                        storage_blocked = True
                        user_storage_full[_ck] = True
                        logger.info(
                            f"📦 Business {business_id} ({business_type}) idle - "
                            f"would overflow storage ({used_for_owner}+{incoming_weight} > {cap_for_owner})"
                        )
                    else:
                        # Reserve the slots so subsequent businesses for this
                        # owner see the running used.
                        user_storage_used[_ck] = used_for_owner + incoming_weight
                
                # --- Step 3: Maintenance ---
                maintenance = MAINTENANCE_COSTS.get(tier, {}).get(level, 0.05)
                maintenance_cost = maintenance * hourly_fraction
                
                # --- Step 4: Profit ---
                if produces in ("ton", "profit_ton"):
                    gross_profit = actual_production * 0.01
                elif produces and produces in market_prices:
                    gross_profit = actual_production * max(0.01, market_prices.get(produces, 0.01))
                else:
                    gross_profit = 0
                
                # --- Step 5: Income tax ---
                tax_rate = TIER_TAXES.get(tier, 0.15)
                income_tax = gross_profit * tax_rate
                
                # --- Step 6: Patron tax ---
                has_patron = business.get("patron_id") is not None
                patron_tax = (gross_profit - income_tax) * 0.01 if has_patron else 0
                
                # Net income to player
                net_income = gross_profit - income_tax - patron_tax - maintenance_cost
                
                # --- Update business in DB ---
                # Surface a precise work status so the UI can show why a business
                # is idle. When the warehouse is 100% full ALL businesses go idle:
                # they produce nothing AND consume nothing (consumption below is
                # guarded by `can_operate`, which storage_blocked forces False).
                if storage_blocked:
                    _work_status, _work_reason = "idle", "storage_full"
                elif not can_operate:
                    _work_status, _work_reason = "idle", "no_resources"
                else:
                    _work_status, _work_reason = "active", None
                update_ops = {
                    "$set": {
                        "durability": new_durability,
                        "last_tick": now.isoformat(),
                        "last_collection": now.isoformat(),
                        "last_wear_update": now.isoformat(),
                        "work_status": _work_status,
                        "work_status_reason": _work_reason,
                        "is_active": can_operate and not storage_blocked,
                    }
                }
                # Durability recovered above 0 → cancel the 7-day seizure timer.
                if new_durability > 0 and business.get("zero_durability_since"):
                    update_ops["$set"]["zero_durability_since"] = None
                if _smart_flags is not None:
                    update_ops["$set"]["smart_notified"] = _smart_flags
                
                # Lifetime production statistic of the business. (The real stock lives in
                # user.resources; the old storage.items counter only ever grew and other
                # code mistook it for available resources.)
                if actual_production > 0 and produces and produces != "ton" and can_operate:
                    update_ops.setdefault("$inc", {})
                    update_ops["$inc"][f"produced_total.{produces}"] = round(actual_production, 2)
                    
                businesses_bulk.append(UpdateOne({"id": business_id}, update_ops))
                
                # --- Update user ---
                user_update = {"$inc": {}}
                
                # НЕ добавляем деньги автоматически - только ресурсы!
                # Деньги получаются только при продаже ресурсов на маркетплейсе
                
                # Add produced resources to inventory
                if can_operate and actual_production > 0 and produces and produces != "ton":
                    user_update["$inc"][f"resources.{produces}"] = round(actual_production, 2)
                    # Debug-per-business production log demoted to DEBUG to slash
                    # log I/O at scale — turn on with LOG_LEVEL=DEBUG when needed.
                    logger.debug(f"📦 Business {business_id} produced {round(actual_production, 2)} {produces} for {owner}")
                
                # Deduct consumed resources
                if can_operate:
                    for resource, amount in scaled_consumption.items():
                        if amount > 0:
                            user_update["$inc"][f"resources.{resource}"] = -amount
                
                if user_update["$inc"]:
                    users_bulk.append(UpdateOne(_user_filter(owner), user_update))
                
                # Track totals
                total_tax_collected += income_tax + patron_tax
                total_maintenance_collected += maintenance_cost
                
                if produces and actual_production > 0:
                    total_production[produces] = total_production.get(produces, 0) + actual_production
                for r, a in scaled_consumption.items():
                    if can_operate:
                        total_consumption[r] = total_consumption.get(r, 0) + a
                
                tick_results.append({
                    "business_id": business_id,
                    "type": business_type,
                    "owner": owner,
                    "net_income": round(net_income, 6),
                    "production": round(actual_production, 2),
                    "produces": produces,
                    "maintenance": round(maintenance_cost, 6),
                    "tax": round(income_tax, 6),
                    "durability": new_durability,
                })
                
                businesses_processed += 1

                # === CONTRACT EXECUTION ===
                # Tax Haven is enforced on market sale (server.py) only — NOT per tick (fix #1: no double-charging).
                # Raw Material transfers a frozen share of produced goods to the patron every tick.
                # Tech Umbrella has no per-tick action (daily rent in midnight_decay).
                if can_operate and actual_production > 0:
                    # Perf: use the already prefetched map instead of a per-biz
                    # `contracts.find_one`. Falls back to a single query only
                    # if the map genuinely misses (shouldn't happen at scale).
                    active_contract = active_contracts_by_biz.get(business_id)
                    if active_contract:
                        contract_type = active_contract.get("type")
                        contract_patron_id = active_contract.get("patron_id")
                        today_str = now.strftime("%Y-%m-%d")
                        contract_violation = False
                        violation_reason_key = None

                        if contract_type == "raw_material":
                            # Frozen-at-signing share (fix #8); fallback to 15% for legacy contracts.
                            share = float(active_contract.get("material_share", 0.15))
                            if produces and produces != "ton":
                                transfer = round(actual_production * share, 2)
                                if transfer > 0:
                                    users_bulk.append(UpdateOne(
                                        _user_filter(owner),
                                        {"$inc": {f"resources.{produces}": -transfer}}
                                    ))
                                    users_bulk.append(UpdateOne(
                                        _user_filter(contract_patron_id),
                                        {"$inc": {f"resources.{produces}": transfer}}
                                    ))
                                    # Track patron's accumulated raw-material take (units)
                                    contracts_bulk.append(UpdateOne(
                                        {"id": active_contract["id"]},
                                        {"$inc": {"total_patron_income": transfer}},
                                    ))
                                else:
                                    contract_violation = True
                                    violation_reason_key = "_reason_no_production"
                            # produces == "ton" or empty → biz physically can't deliver material,
                            # but it ran legitimately → do NOT punish (fix #2).

                        # tech_umbrella & tax_haven: no per-tick action

                        if contract_violation:
                            v_days = list(active_contract.get("violation_days", []))
                            if today_str not in v_days:
                                v_days.append(today_str)
                                recent = sorted(v_days)[-3:]
                                auto_cancel = False
                                if len(recent) >= 3:
                                    from datetime import date as _date
                                    parsed = [_date.fromisoformat(d) for d in recent]
                                    # Check if last 3 days are consecutive
                                    if all((parsed[i + 1] - parsed[i]).days <= 1 for i in range(len(parsed) - 1)):
                                        auto_cancel = True
                                ct_meta = {
                                    "raw_material": {"icon": "⚙️", "name_ru": "Сырьевой Придаток",
                                                     "name_en": "Raw Material"},
                                    "tax_haven": {"icon": "🏝️", "name_ru": "Налоговая Гавань",
                                                  "name_en": "Tax Haven"},
                                    "tech_umbrella": {"icon": "🛡️", "name_ru": "Технологический Зонтик",
                                                      "name_en": "Tech Umbrella"},
                                }.get(contract_type, {"icon": "🤝", "name_ru": "Контракт", "name_en": "Contract"})
                                if auto_cancel:
                                    contracts_bulk.append(UpdateOne(
                                        {"id": active_contract["id"]},
                                        {"$set": {"status": "cancelled", "cancelled_by": "system",
                                                  "cancelled_at": now.isoformat(), "violation_days": v_days,
                                                  "auto_cancel_reason": "violations_streak"}}
                                    ))
                                    businesses_bulk.append(UpdateOne(
                                        {"id": business_id},
                                        {"$unset": {"contract_buff": "", "contract_id": ""}}
                                    ))
                                    # Alliance auto-cancel notifs — deferred so
                                    # slow WS/http side-effects don't block DB.
                                    _cached_v = users.get(owner) or {}
                                    _vassal_name = _cached_v.get("username") or "?"
                                    _contract_id = active_contract["id"]
                                    _cp_id = contract_patron_id
                                    _o = owner
                                    _cm = ct_meta
                                    _schedule_tg(lambda:
                                        send_alliance_notification(
                                            db, _cp_id,
                                            "alliance_auto_cancelled_patron",
                                            {"contract_icon": _cm["icon"],
                                             "contract_name": _cm["name_ru"],
                                             "vassal_name": _vassal_name},
                                            extra_fields={"contract_id": _contract_id},
                                        ))
                                    _schedule_tg(lambda:
                                        send_alliance_notification(
                                            db, _o,
                                            "alliance_auto_cancelled_vassal",
                                            {"contract_icon": _cm["icon"],
                                             "contract_name": _cm["name_ru"]},
                                            extra_fields={"contract_id": _contract_id},
                                        ))
                                else:
                                    contracts_bulk.append(UpdateOne(
                                        {"id": active_contract["id"]},
                                        {"$set": {"violation_days": v_days}}
                                    ))
                                    # Strike warning to vassal (1st/2nd day)
                                    _o = owner
                                    _cm = ct_meta
                                    _contract_id = active_contract["id"]
                                    _streak = len(recent)
                                    _reason_key = violation_reason_key or "_reason_no_production"
                                    _schedule_tg(lambda:
                                        send_alliance_notification(
                                            db, _o,
                                            "alliance_violation_vassal",
                                            {"contract_icon": _cm["icon"],
                                             "contract_name": _cm["name_ru"],
                                             "streak": _streak,
                                             "reason_key": _reason_key},
                                            extra_fields={"contract_id": _contract_id},
                                        ))

                # Per-resource low-stock alerts. Thresholds (in order of severity):
                #   idx 0 → 12h, idx 1 → 3h, idx 2 → 30 min, idx 3 → business STOPPED
                # We persist the last-sent index PER (business, resource) on the
                # business document so each threshold fires AT MOST ONCE per
                # depletion cycle. The index is reset when the resource is
                # replenished (hours_left > 12).
                #
                # Per product spec a user must never receive more than 4 alerts
                # per (business × resource) per depletion cycle: 12h → 3h →
                # 30 min → stopped.
                #
                # Languages: in-app notifications are stored once with both
                # `title` and `message` rendered in the user's preferred
                # language (RU/EN). The Telegram mirror picks the same text up.
                if consumption_breakdown:
                    # Perf: use pre-fetched user snapshot instead of a fresh
                    # `db.users.find_one` per business. Note: `users` was
                    # loaded at the top of the tick; we accept a slightly
                    # stale `resources` view here (alert thresholds only —
                    # they're already best-effort/eventually-consistent).
                    user_lang_doc = users.get(owner)
                    if user_lang_doc:
                        user_res = user_lang_doc.get("resources", {})
                        from core.notif_i18n import user_lang as _norm_ulang, render as _render_n, fmt_hours_left as _fmt_hl
                        user_lang = _norm_ulang(user_lang_doc)

                        biz_name_obj = config.get("name", {})
                        if isinstance(biz_name_obj, dict):
                            biz_name_str = biz_name_obj.get(user_lang) or biz_name_obj.get("en") or biz_name_obj.get("ru") or business_type
                        else:
                            biz_name_str = str(biz_name_obj)

                        # Resource display name in user language
                        def _res_name(rkey: str) -> str:
                            try:
                                from business_config import RESOURCE_TYPES as _RT
                                meta = _RT.get(rkey, {})
                                return meta.get(f"name_{user_lang}") or meta.get("name_en") or meta.get("name_ru") or rkey
                            except Exception:
                                return rkey

                        # Title / template strings.
                        # Below-1h messages now spell out the exact 30-min
                        # threshold so users aren't surprised that the
                        # business stopped just minutes after a "less than 1h"
                        # banner.
                        # Existing alert state on the business doc
                        last_alerts: dict = dict(business.get("low_res_alerts", {}) or {})
                        updated_alerts = dict(last_alerts)

                        for resource, daily_amount in consumption_breakdown.items():
                            if daily_amount <= 0:
                                continue
                            current = float(user_res.get(resource, 0) or 0)
                            hours_left = (current / daily_amount) * 24.0

                            # Determine current threshold index.
                            #   idx 3 — business COULDN'T operate this tick AND this resource was insufficient → STOPPED
                            #   idx 2 — ≤ 30 min remaining
                            #   idx 1 — ≤ 3 h remaining
                            #   idx 0 — ≤ 12 h remaining
                            new_idx = -1
                            if (not can_operate) and current < scaled_consumption.get(resource, 0):
                                new_idx = 3
                            elif hours_left <= 0.5:
                                new_idx = 2
                            elif hours_left <= 3:
                                new_idx = 1
                            elif hours_left <= 12:
                                new_idx = 0

                            # Replenishment: drop the per-resource counter
                            if new_idx < 0 or hours_left > 12:
                                if resource in updated_alerts:
                                    updated_alerts.pop(resource, None)
                                continue

                            last_idx = int(last_alerts.get(resource, -1))
                            if new_idx <= last_idx:
                                # already notified at this (or deeper) severity
                                continue

                            # Helper to render "Xч Yм" / "Xh Ym" for the
                            # `hl` placeholder (exact time-left).
                            hl_str = _fmt_hl(hours_left, user_lang)

                            # Build the message text
                            _hrs = 3 if new_idx == 1 else 12
                            _i18n_key = "low_res_stopped" if new_idx == 3 else ("low_res_hours_1" if new_idx == 2 else "low_res_hours_n")
                            _i18n_vars = {"biz": biz_name_str, "res": _res_name(resource), "h": _hrs, "hl": hl_str}
                            title, msg = _render_n(_i18n_key, user_lang, **_i18n_vars)

                            notifications_batch.append({
                                "id": str(uuid.uuid4()),
                                "user_id": owner,
                                "type": "low_resource",
                                "priority": "warning" if new_idx < 3 else "error",
                                "title": title,
                                "message": msg,
                                "payload": {"i18n_key": _i18n_key, "i18n_vars": _i18n_vars},
                                "resource": resource,
                                "business_id": business_id,
                                "threshold_idx": new_idx,
                                "read": False,
                                "created_at": now.isoformat(),
                            })
                            updated_alerts[resource] = new_idx

                        if updated_alerts != last_alerts:
                            businesses_bulk.append(UpdateOne(
                                {"id": business_id},
                                {"$set": {"low_res_alerts": updated_alerts}}
                            ))
                
            except Exception as e:
                logger.error(f"❌ Tick error for business {business.get('id')}: {e}")
                continue

        # === FLUSH BULK WRITES (Businesses/Users/Contracts/Notifications) ===
        # This is the primary optimization. Prior versions performed 3–6 Mongo
        # round-trips PER business inside the loop; at ~1000 businesses that
        # turned each tick into ~75 s of sequential round-trips. Sending a
        # single bulk_write per collection collapses all of that to ~1 RTT
        # per collection (ordered=False keeps ops running concurrently).
        # Smart notifications collected during the tick (warehouse + durability).
        # Delivered in the background so slow Telegram never delays the tick.
        try:
            if smart_events:
                import smart_notify as _sn
                if _sn._DB is None:
                    _sn.init(db)
                for _u, _kind, _vars, _ref in smart_events:
                    _sn.send_bg(_u, _kind, _vars, ref=_ref)
                logger.info(f"🔔 smart notifications queued: {len(smart_events)}")
        except Exception as _sne:
            logger.warning(f"smart notifications dispatch failed: {_sne}")

        try:
            _flush_ts = datetime.now(timezone.utc)
            if businesses_bulk:
                try:
                    await db.businesses.bulk_write(businesses_bulk, ordered=False)
                except BulkWriteError as bwe:
                    logger.warning(f"[tick] businesses bulk_write partial: {bwe.details.get('writeErrors', [])[:3]}")
            if users_bulk:
                try:
                    await db.users.bulk_write(users_bulk, ordered=False)
                except BulkWriteError as bwe:
                    logger.warning(f"[tick] users bulk_write partial: {bwe.details.get('writeErrors', [])[:3]}")
            if contracts_bulk:
                try:
                    await db.contracts.bulk_write(contracts_bulk, ordered=False)
                except BulkWriteError as bwe:
                    logger.warning(f"[tick] contracts bulk_write partial: {bwe.details.get('writeErrors', [])[:3]}")
            if notifications_batch:
                try:
                    await db.notifications.insert_many(notifications_batch, ordered=False)
                except Exception as ie:
                    logger.warning(f"[tick] notifications insert_many failed: {ie}")
            _flush_ms = (datetime.now(timezone.utc) - _flush_ts).total_seconds() * 1000
            logger.info(
                f"⚡ Tick bulk flush: biz={len(businesses_bulk)} "
                f"users={len(users_bulk)} contracts={len(contracts_bulk)} "
                f"notifs={len(notifications_batch)} in {_flush_ms:.0f}ms"
            )
        except Exception as e:
            logger.error(f"[tick] bulk flush failed: {e}")
        
        # === SUPPLY CONTRACTS EXECUTION (Alliance auto-delivery) ===
        try:
            active_supply = await db.supply_contracts.find({"status": "active"}).to_list(100)
            supply_executed = 0
            for sc in active_supply:
                try:
                    seller_id = sc.get("seller_id")
                    buyer_id = sc.get("buyer_id")
                    resource = sc.get("resource_type")
                    daily_amount = sc.get("amount_per_day", 0)
                    price_per_10 = sc.get("price_per_10", 0)
                    
                    if not seller_id or not buyer_id or not resource or daily_amount <= 0:
                        continue
                    
                    # Calculate per-tick delivery (1 tick per minute = 1/1440 of daily)
                    tick_amount = round(daily_amount / 1440.0, 6)
                    tick_cost_city = round(tick_amount * price_per_10 / 10.0, 6)
                    tick_cost_ton = tick_cost_city / 1000.0
                    
                    if tick_amount < 0.0001:
                        continue
                    
                    # Check seller has resources
                    seller = await db.users.find_one(
                        {"$or": [{"id": seller_id}, {"wallet_address": seller_id}]},
                        {"_id": 0, "resources": 1, "balance_ton": 1}
                    )
                    seller_has = (seller or {}).get("resources", {}).get(resource, 0)
                    
                    if seller_has < tick_amount:
                        # Violation: seller can't deliver
                        v_days = list(sc.get("violation_days", []))
                        today_str = now.strftime("%Y-%m-%d")
                        if today_str not in v_days:
                            v_days.append(today_str)
                            if len(v_days) >= 3:
                                await db.supply_contracts.update_one(
                                    {"id": sc["id"]},
                                    {"$set": {"status": "cancelled", "cancelled_by": "system", "cancelled_at": now.isoformat()}}
                                )
                                logger.info(f"📦❌ Supply contract {sc['id']} auto-cancelled: 3 violations")
                            else:
                                await db.supply_contracts.update_one(
                                    {"id": sc["id"]},
                                    {"$set": {"violation_days": v_days}}
                                )
                        continue
                    
                    # Check buyer has funds
                    buyer = await db.users.find_one(
                        {"$or": [{"id": buyer_id}, {"wallet_address": buyer_id}]},
                        {"_id": 0, "balance_ton": 1}
                    )
                    buyer_balance = (buyer or {}).get("balance_ton", 0)
                    
                    if buyer_balance < tick_cost_ton:
                        continue  # Skip but no violation for buyer
                    
                    # Execute transfer: resources seller → buyer, money buyer → seller
                    await db.users.update_one(
                        {"$or": [{"id": seller_id}, {"wallet_address": seller_id}]},
                        {"$inc": {f"resources.{resource}": -tick_amount, "balance_ton": tick_cost_ton}}
                    )
                    await db.users.update_one(
                        {"$or": [{"id": buyer_id}, {"wallet_address": buyer_id}]},
                        {"$inc": {f"resources.{resource}": tick_amount, "balance_ton": -tick_cost_ton}}
                    )
                    
                    # Track cumulative delivery
                    await db.supply_contracts.update_one(
                        {"id": sc["id"]},
                        {"$inc": {"total_delivered": tick_amount, "total_paid_city": tick_cost_city}}
                    )
                    
                    supply_executed += 1
                    
                    # Check expiry
                    expires_at = sc.get("expires_at")
                    if expires_at:
                        exp_dt = to_aware(expires_at)
                        if exp_dt and now >= exp_dt:
                            await db.supply_contracts.update_one(
                                {"id": sc["id"]},
                                {"$set": {"status": "completed", "completed_at": now.isoformat()}}
                            )
                            logger.info(f"📦✅ Supply contract {sc['id']} completed (expired)")
                    
                except Exception as sce:
                    logger.error(f"❌ Supply contract error {sc.get('id')}: {sce}")
            
            if supply_executed > 0:
                logger.info(f"📦 Supply contracts executed: {supply_executed}")
        except Exception as e:
            logger.error(f"❌ Supply contracts batch error: {e}")
        
        # === GLOBAL STEPS (7-13) ===
        
        # Step 7: NPC consumption
        total_supply = {}
        supply_cursor = db.users.aggregate([
            {"$project": {"resources": 1}},
        ])
        async for doc in supply_cursor:
            for r, a in doc.get("resources", {}).items():
                total_supply[r] = total_supply.get(r, 0) + a
        
        npc_consumed = NPCMarketSystem.calculate_npc_consumption(total_supply)
        
        # Step 8: Prices are FIXED to the configured per-unit base prices
        # (see RESOURCE_TYPES / the pricing table). Dynamic NPC interventions
        # and inflation-based drift are intentionally disabled so prices never
        # deviate from the table.
        interventions = []
        market_prices = {r: d["base_price"] for r, d in RESOURCE_TYPES.items()}
        inflation_factor = 1.0
        
        # Save fixed prices
        await db.market_prices.update_one(
            {"type": "current"},
            {"$set": {"prices": market_prices, "updated_at": now.isoformat()}},
            upsert=True
        )
        
        # Step 11: Bankruptcy checks
        bankruptcies = []
        async for user in db.users.find({"balance_ton": {"$lt": -10}}):
            bankruptcy = BankruptcySystem.check_bankruptcy(user)
            if bankruptcy["is_bankrupt"]:
                bankruptcies.append({
                    "user": user.get("wallet_address") or user.get("id"),
                    "balance": user.get("balance_ton"),
                    "reason": bankruptcy["reason"],
                })
                # Pause all their businesses
                await db.businesses.update_many(
                    {"owner": user.get("wallet_address") or user.get("id")},
                    {"$set": {"is_active": False, "paused_reason": "bankruptcy"}}
                )
        
        # Step 12: Events
        events = EventsSystem.roll_events()
        
        # Step 13: Save snapshot
        await db.admin_stats.update_one(
            {"type": "treasury"},
            {"$inc": {
                "total_tax": total_tax_collected,
                "total_maintenance": total_maintenance_collected,
            }},
            upsert=True
        )
        
        snapshot = {
            "type": "tick_snapshot",
            "timestamp": now.isoformat(),
            "businesses_processed": businesses_processed,
            "total_tax_collected": round(total_tax_collected, 4),
            "total_maintenance_collected": round(total_maintenance_collected, 4),
            "total_production": {k: round(v, 2) for k, v in total_production.items()},
            "total_consumption": {k: round(v, 2) for k, v in total_consumption.items()},
            "npc_consumed": npc_consumed,
            "npc_interventions": len(interventions),
            "inflation_factor": round(inflation_factor, 6),
            "bankruptcies": len(bankruptcies),
            "events": [e.get("id") for e in events],
            "market_prices": market_prices,
        }
        
        await db.economic_snapshots.insert_one(snapshot)
        
        # Log summary
        logger.info("✅ TICK COMPLETE:")
        logger.info(f"   📊 Businesses: {businesses_processed}")
        logger.info(f"   🩹 Wear applied to: {wear_applied_count} businesses")
        logger.info(f"   💰 Tax: {total_tax_collected:.4f} TON")
        logger.info(f"   🔧 Maintenance: {total_maintenance_collected:.4f} TON")
        logger.info(f"   📈 Inflation: {inflation_factor:.4f}x")
        logger.info(f"   ⚠️ Bankruptcies: {len(bankruptcies)}")
        logger.info(f"   🎲 Events: {len(events)}")
        
        # Send consolidated Telegram notifications for low resources.
        # Dedup key: `telegram_sent` — unified across the codebase (previous
        # implementation used a separate `tg_sent` field which caused the
        # generic sender to re-deliver each alert without the inline "💎"
        # button). This block is spawned as a background task so the tick
        # returns immediately after the DB flush.
        async def _send_low_resource_tg_batch():
            try:
                pending_notifs = await db.notifications.find(
                    {"type": "low_resource", "telegram_sent": {"$ne": True}},
                    {"_id": 0}
                ).sort("created_at", 1).to_list(200)

                _public_base = os.environ.get("PUBLIC_APP_URL", "https://gramcity.games").rstrip("/")
                _app_url = f"{_public_base}/trading"

                user_notifs: dict = {}
                for n in pending_notifs:
                    uid = n.get("user_id", "")
                    if uid not in user_notifs:
                        user_notifs[uid] = []
                    user_notifs[uid].append(n)

                for uid, notifs in user_notifs.items():
                    chat_id = await get_user_telegram_chat_id(db, uid)
                    if not chat_id:
                        # Still mark them so we don't keep scanning forever
                        _mark_ops = [UpdateOne({"id": n["id"]}, {"$set": {"telegram_sent": True}}) for n in notifs]
                        if _mark_ops:
                            try:
                                await db.notifications.bulk_write(_mark_ops, ordered=False)
                            except Exception:
                                pass
                        continue

                    # Pick language from the first notification's user record so the
                    # bot heading matches the in-app banner. Reuse the tick's
                    # cached user snapshot when available to avoid an extra RTT.
                    _cached = users.get(uid) if isinstance(users, dict) else None
                    if _cached is not None:
                        ulang = ((_cached.get("language") or "en") or "en").lower()
                    else:
                        user_doc = await db.users.find_one(
                            {"$or": [{"id": uid}, {"wallet_address": uid}]},
                            {"_id": 0, "language": 1},
                        )
                        ulang = ((user_doc or {}).get("language") or "en").lower()
                    from core.notif_i18n import label as _lbl, norm_lang as _nl
                    ulang = _nl(ulang)
                    heading = _lbl("low_res_heading", ulang)
                    btn_text = _lbl("buy_resources", ulang)
                    lines = [heading]
                    for n in notifs:
                        lines.append(f"• {n.get('message', '')}")
                    lines.append(_lbl("low_res_footer", ulang))
                    try:
                        from telegram_bot import get_telegram_bot
                        tg_bot = get_telegram_bot()
                        if tg_bot:
                            keyboard = {"inline_keyboard": [[{"text": btn_text, "url": _app_url}]]}
                            await tg_bot.send_message(chat_id, "\n".join(lines), reply_markup=keyboard)
                            _mark_ops = [UpdateOne({"id": n["id"]}, {"$set": {"telegram_sent": True}}) for n in notifs]
                            if _mark_ops:
                                try:
                                    await db.notifications.bulk_write(_mark_ops, ordered=False)
                                except Exception:
                                    pass
                    except Exception as tg_err:
                        logger.debug(f"TG notification failed: {tg_err}")
            except Exception as e:
                logger.debug(f"TG notifications batch: {e}")

        try:
            asyncio.create_task(_send_low_resource_tg_batch())
        except Exception:
            pass

        # Fire any per-business Telegram/alliance side-effects that were
        # queued during the loop, all concurrently. Wrapping in `create_task`
        # so this whole tick returns immediately — no HTTP retries or slow
        # WS pushes contribute to the reported tick duration.
        if pending_tg_tasks:
            async def _run_pending_tg():
                try:
                    coros = []
                    for fn in pending_tg_tasks:
                        try:
                            r = fn()
                            if asyncio.iscoroutine(r):
                                coros.append(r)
                        except Exception:
                            pass
                    if coros:
                        await asyncio.gather(*coros, return_exceptions=True)
                except Exception as e:
                    logger.debug(f"[tick] pending TG batch failed: {e}")
            try:
                asyncio.create_task(_run_pending_tg())
            except Exception:
                pass
        
        # (shared client — no per-job close)
        pass
        
    except Exception as e:
        logger.error(f"❌ ECONOMIC TICK FAILED: {e}")
        import traceback
        logger.error(traceback.format_exc())


# ==================== MIDNIGHT DECAY ====================

async def midnight_decay():
    """
    Apply 10% decay to all inventories at 00:00 MSK (21:00 UTC).
    Stimulates daily sales and market activity.
    """
    try:
        logger.info("🌙 === MIDNIGHT DECAY STARTED ===")
        
        db = _get_shared_db()
        
        users_cursor = db.users.find({"resources": {"$exists": True}})
        decayed_count = 0
        total_lost = {}
        
        try:
            from comeback import decay_protected as _decay_protected
        except Exception:
            _decay_protected = lambda _u: False  # noqa: E731
        protected_count = 0
        async for user in users_cursor:
            resources = user.get("resources", {})
            if not resources:
                continue
            # Comeback bonus: a returning player's warehouse is safe for a while.
            if _decay_protected(user):
                protected_count += 1
                continue
            
            new_resources = {}
            for resource, amount in resources.items():
                if isinstance(amount, (int, float)) and amount > 0:
                    lost = int(amount * MIDNIGHT_DECAY_RATE)
                    new_resources[resource] = max(0, amount - lost)
                    total_lost[resource] = total_lost.get(resource, 0) + lost
                else:
                    new_resources[resource] = amount
            
            await db.users.update_one(
                {"_id": user["_id"]},
                {"$set": {"resources": new_resources}}
            )
            decayed_count += 1
        
        # Log
        logger.info(f"🌙 Decay applied to {decayed_count} users ({protected_count} protected by comeback bonus)")
        for r, lost in total_lost.items():
            if lost > 0:
                logger.info(f"   🔻 {r}: -{lost}")
        
        # Save decay event
        await db.system_events.insert_one({
            "type": "midnight_decay",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "users_affected": decayed_count,
            "resources_lost": total_lost,
        })
        
        # === TECH UMBRELLA DAILY RENT (frozen on contract, default 100 $CITY/day) ===
        try:
            tech_contracts = await db.contracts.find({"type": "tech_umbrella", "status": "active"}).to_list(100)
            rent_processed = 0
            ct_meta_umbrella = {"icon": "🛡️", "name_ru": "Технологический Зонтик"}
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            for tc in tech_contracts:
                vassal_id = tc.get("vassal_id")
                patron_id = tc.get("patron_id")
                if not vassal_id or not patron_id:
                    continue
                rent_city = float(tc.get("daily_rent_city", 100))  # fix #8: frozen rate
                rent_ton = rent_city / 1000.0

                # Deduct from vassal
                vassal = await db.users.find_one(
                    {"$or": [{"id": vassal_id}, {"wallet_address": vassal_id}]},
                    {"_id": 0, "balance_ton": 1}
                )
                if vassal and vassal.get("balance_ton", 0) >= rent_ton:
                    await db.users.update_one(
                        {"$or": [{"id": vassal_id}, {"wallet_address": vassal_id}]},
                        {"$inc": {"balance_ton": -rent_ton}}
                    )
                    await db.users.update_one(
                        {"$or": [{"id": patron_id}, {"wallet_address": patron_id}]},
                        {"$inc": {"balance_ton": rent_ton}}
                    )
                    await db.contracts.update_one(
                        {"id": tc["id"]},
                        {"$inc": {"total_patron_income": rent_city}}
                    )
                    # Tx-history for both sides (Tech Umbrella rent)
                    try:
                        import uuid as _uuid
                        now_iso = datetime.now(timezone.utc).isoformat()
                        patron_username = tc.get("patron_username") or ""
                        vassal_username = tc.get("vassal_username") or ""
                        base = {
                            "contract_id": tc["id"],
                            "contract_type": "tech_umbrella",
                            "rent_city": rent_city,
                            "created_at": now_iso,
                        }
                        await db.transactions.insert_one({
                            **base,
                            "id": str(_uuid.uuid4()),
                            "user_id": vassal_id,
                            "type": "contract_payment_out",
                            "tx_type": "contract_payment_out",
                            "amount_ton": -rent_ton,
                            "counterparty_id": patron_id,
                            "counterparty_username": patron_username,
                            "description": f"Технологический Зонтик: −{rent_city} $CITY → {patron_username or 'patron'}",
                        })
                        await db.transactions.insert_one({
                            **base,
                            "id": str(_uuid.uuid4()),
                            "user_id": patron_id,
                            "type": "contract_payment_in",
                            "tx_type": "contract_payment_in",
                            "amount_ton": rent_ton,
                            "counterparty_id": vassal_id,
                            "counterparty_username": vassal_username,
                            "description": f"Технологический Зонтик: +{rent_city} $CITY от {vassal_username or 'vassal'}",
                        })
                    except Exception as _tx_e:
                        logger.warning(f"tech_umbrella tx-history failed: {_tx_e}")
                    rent_processed += 1
                else:
                    # Violation - can't pay rent (fix #7: notify + auto-cancel on streak)
                    v_days = list(tc.get("violation_days", []))
                    if today_str in v_days:
                        continue
                    v_days.append(today_str)
                    recent = sorted(v_days)[-3:]
                    auto_cancel = False
                    if len(recent) >= 3:
                        from datetime import date as _date
                        try:
                            parsed = [_date.fromisoformat(d) for d in recent]
                            if all((parsed[i + 1] - parsed[i]).days <= 1 for i in range(len(parsed) - 1)):
                                auto_cancel = True
                        except Exception:
                            pass

                    if auto_cancel:
                        await db.contracts.update_one(
                            {"id": tc["id"]},
                            {"$set": {"status": "cancelled", "cancelled_by": "system",
                                      "cancelled_at": datetime.now(timezone.utc).isoformat(),
                                      "violation_days": v_days,
                                      "auto_cancel_reason": "rent_unpaid"}}
                        )
                        if tc.get("vassal_business_id"):
                            await db.businesses.update_one(
                                {"id": tc["vassal_business_id"]},
                                {"$unset": {"contract_buff": "", "contract_id": ""}}
                            )
                        try:
                            vassal_doc = await db.users.find_one(
                                {"$or": [{"id": vassal_id}, {"wallet_address": vassal_id}]},
                                {"_id": 0, "username": 1},
                            )
                            vassal_name = (vassal_doc or {}).get("username") or "?"
                            await send_alliance_notification(
                                db, patron_id, "alliance_auto_cancelled_patron",
                                {"contract_icon": ct_meta_umbrella["icon"],
                                 "contract_name": ct_meta_umbrella["name_ru"],
                                 "vassal_name": vassal_name},
                                extra_fields={"contract_id": tc["id"]},
                            )
                            await send_alliance_notification(
                                db, vassal_id, "alliance_auto_cancelled_vassal",
                                {"contract_icon": ct_meta_umbrella["icon"],
                                 "contract_name": ct_meta_umbrella["name_ru"]},
                                extra_fields={"contract_id": tc["id"]},
                            )
                        except Exception as _e:
                            logger.warning(f"tech umbrella auto-cancel notif failed: {_e}")
                    else:
                        await db.contracts.update_one(
                            {"id": tc["id"]},
                            {"$set": {"violation_days": v_days}}
                        )
                        try:
                            await send_alliance_notification(
                                db, vassal_id, "alliance_violation_vassal",
                                {"contract_icon": ct_meta_umbrella["icon"],
                                 "contract_name": ct_meta_umbrella["name_ru"],
                                 "streak": len(recent),
                                 "reason_key": "_reason_insufficient_rent"},
                                extra_fields={"contract_id": tc["id"]},
                            )
                        except Exception as _e:
                            logger.warning(f"tech umbrella violation notif failed: {_e}")

            if rent_processed > 0:
                logger.info(f"🛡️ Tech Umbrella rent: {rent_processed} contracts processed")
        except Exception as e:
            logger.error(f"❌ Tech Umbrella rent error: {e}")
        
        # (shared client — no per-job close)
        pass
        
    except Exception as e:
        logger.error(f"❌ MIDNIGHT DECAY FAILED: {e}")


# ==================== DURABILITY WEAR ====================

async def apply_global_durability_wear():
    """Apply durability wear to ALL businesses in a single global tick.
    V4: Applies T3 resource buff (wear_reduction) per owner.
    """
    try:
        logger.info("🔧 Applying global durability wear...")
        
        db = _get_shared_db()
        now = datetime.now(timezone.utc)
        
        businesses = await db.businesses.find(
            {"paused_reason": {"$ne": "bankruptcy"}, "durability": {"$gt": 0}, "is_trial": {"$ne": True}},
            {"_id": 0, "id": 1, "business_type": 1, "level": 1, "durability": 1, "owner": 1, "last_wear_update": 1, "last_tick": 1, "shift_ends_at": 1, "tutorial": 1, "is_trial": 1, "is_zero_business": 1}
        ).to_list(length=None)
        
        # Cache owner wear reduction buffs
        owner_wear_mult = {}
        
        async def get_owner_wear_mult(owner_id):
            if owner_id in owner_wear_mult:
                return owner_wear_mult[owner_id]
            user = await db.users.find_one(
                {"$or": [{"id": owner_id}, {"wallet_address": owner_id}]},
                {"_id": 0, "active_resource_buffs": 1}
            )
            mult = 1.0
            if user:
                for b in (user.get("active_resource_buffs") or []):
                    if b.get("effect_type") == "wear_reduction" and b.get("expires_at"):
                        try:
                            exp = datetime.fromisoformat(b["expires_at"].replace('Z', '+00:00'))
                            if exp > now:
                                mult = min(mult, b["effect_value"])  # e.g. 0.75
                        except (ValueError, TypeError):
                            pass
            owner_wear_mult[owner_id] = mult
            return mult
        
        updates = []
        for biz in businesses:
            btype = biz.get("business_type", "")
            level = biz.get("level", 1)
            cur = biz.get("durability", 100)
            if cur <= 0:
                continue

            # Shift gate: idle businesses (shift ended / not started) do NOT wear.
            if not shift_is_active(biz, now):
                continue
            
            last_update = biz.get("last_wear_update") or biz.get("last_tick")
            hours_passed = 1.0
            if last_update:
                try:
                    last_dt = datetime.fromisoformat(str(last_update).replace('Z', '+00:00'))
                    hours_passed = (now - last_dt).total_seconds() / 3600
                except (ValueError, TypeError):
                    hours_passed = 1.0
            
            canonical = BUSINESS_KEY_MAP.get(btype, btype)
            if canonical not in BUSINESSES and btype not in BUSINESSES:
                continue
            
            daily_wear = get_daily_wear(canonical, level)
            wear = daily_wear * 100 * (hours_passed / 24.0)
            
            # Apply owner's wear reduction buff
            owner = biz.get("owner", "")
            if owner:
                wmult = await get_owner_wear_mult(owner)
                wear *= wmult
            
            new_dur = max(0, cur - wear)
            updates.append({"id": biz["id"], "durability": round(new_dur, 2)})
        
        # Bulk write
        if updates:
            from pymongo import UpdateOne
            ops = [UpdateOne({"id": u["id"]}, {"$set": {"durability": u["durability"], "last_wear_update": now.isoformat()}}) for u in updates]
            await db.businesses.bulk_write(ops)
        
        logger.info(f"🔧 Global wear: {len(updates)} businesses updated (cached {len(owner_wear_mult)} owners)")
        # (shared client — no per-job close)
        pass
        
    except Exception as e:
        logger.error(f"❌ Durability wear failed: {e}")


# ==================== BACKWARD COMPATIBLE FUNCTIONS ====================

async def calculate_business_income(business_type: str, level: int, connections: int) -> dict:
    """Backward compatible income calculation using new data"""
    production = get_production(business_type, level)
    consumption = get_consumption(business_type, level)
    config = BUSINESSES.get(business_type, {})
    tier = config.get("tier", 1)
    
    connection_mult = 1 + connections * 0.1
    
    # Base market price for the produced resource
    produces = config.get("produces", "")
    from business_config import RESOURCE_TYPES as RT
    base_price = RT.get(produces, {}).get("base_price", 0.01)
    
    gross_value = production * base_price * connection_mult
    tax_rate = TIER_TAXES.get(tier, 0.15)
    maintenance = MAINTENANCE_COSTS.get(tier, {}).get(level, 0.05)
    
    net = gross_value * (1 - tax_rate) - maintenance
    
    return {
        "gross": round(gross_value, 4),
        "operating_cost": round(maintenance, 4),
        "tax": round(gross_value * tax_rate, 4),
        "net": round(net, 4),
    }


async def auto_collect_income():
    """Run the full economic tick (backward compatible wrapper)"""
    await economic_tick()


# ==================== SCHEDULER ====================

# ==================== CREDIT PROCESSING ====================

async def process_credits():
    """
    Daily credit processing:
    1. Deduct salary percentage from income for active credits
    2. Detect overdue credits (no payment in specified days)
    3. Double rate for overdue credits
    4. Seize businesses after 7 days of non-payment
    """
    try:
        db = _get_shared_db()
        
        now = datetime.now(timezone.utc)
        active_credits = await db.credits.find(
            {"status": {"$in": ["active", "overdue"]}},
            {"_id": 0}
        ).to_list(500)
        
        logger.info(f"💰 Processing {len(active_credits)} active credits...")
        
        for credit in active_credits:
            credit_id = credit["id"]
            borrower_id = credit.get("borrower_id", "")
            borrower_wallet = credit.get("borrower_wallet", "")
            remaining = credit.get("remaining", 0)
            deduction_pct = credit.get("salary_deduction_percent", 0.10)
            
            if remaining <= 0:
                await db.credits.update_one({"id": credit_id}, {"$set": {"status": "paid", "remaining": 0}})
                continue
            
            # Find borrower
            borrower = await db.users.find_one(
                {"$or": [{"id": borrower_id}, {"wallet_address": borrower_wallet}]},
                {"_id": 0}
            )
            if not borrower:
                continue
            
            # Calculate daily payment from income
            balance = borrower.get("balance_ton", 0)
            daily_income = borrower.get("total_income", 0) / max(1, (now - (to_aware(borrower.get("created_at")) or now)).days or 1)
            
            # Calculate payment amount
            payment = round(daily_income * deduction_pct, 4)
            
            # If overdue and doubled rate active, double the payment
            if credit.get("is_doubled_rate"):
                payment *= 2
            
            # Limit payment to available balance and remaining debt
            payment = min(payment, balance, remaining)
            
            if payment > 0.0001:
                # Deduct from borrower
                user_filter = {"id": borrower_id} if borrower_id else {"wallet_address": borrower_wallet}
                await db.users.update_one(user_filter, {"$inc": {"balance_ton": -payment}})
                
                new_remaining = round(remaining - payment, 4)
                new_paid = round(credit.get("paid", 0) + payment, 4)
                
                update_set = {
                    "remaining": max(0, new_remaining),
                    "paid": new_paid,
                    "last_payment": now.isoformat(),
                }
                
                if new_remaining <= 0:
                    update_set["status"] = "paid"
                    update_set["remaining"] = 0
                
                await db.credits.update_one({"id": credit_id}, {"$set": update_set})
                
                # Pay to lender if bank
                if credit.get("lender_type") == "bank" and credit.get("lender_id"):
                    await db.users.update_one(
                        {"$or": [{"id": credit["lender_id"]}, {"wallet_address": credit["lender_id"]}]},
                        {"$inc": {"balance_ton": payment}}
                    )
                
                logger.info(f"  Credit {credit_id[:8]}: payment {payment:.4f} TON, remaining {new_remaining:.2f}")
            
            # Check overdue status
            last_payment = credit.get("last_payment")
            overdue_days = credit.get("overdue_penalty_days", 3)
            
            if last_payment:
                try:
                    lp = datetime.fromisoformat(last_payment.replace("Z", "+00:00"))
                    days_since = (now - lp).days
                except Exception:
                    days_since = 0
            else:
                created = credit.get("created_at", now.isoformat())
                try:
                    cr = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    days_since = (now - cr).days
                except Exception:
                    days_since = 0
            
            # Activate doubled rate after overdue_penalty_days
            if days_since >= overdue_days and not credit.get("is_doubled_rate") and payment < 0.0001:
                await db.credits.update_one({"id": credit_id}, {"$set": {
                    "status": "overdue",
                    "is_doubled_rate": True,
                    "overdue_since": credit.get("overdue_since") or now.isoformat(),
                }})
                logger.warning(f"  ⚠️ Credit {credit_id[:8]}: OVERDUE - doubled rate activated")
                
                # Send notification
                from core.notify import notify_user as _nu
                await _nu(db, borrower_id, title="Кредит просрочен",
                          message=f"Кредит просрочен! Ставка удвоена. Погасите долг {remaining:.2f} TON.",
                          type_key="credit_overdue", priority="warning",
                          i18n_key="credit_overdue", i18n_vars={"remaining": f"{remaining:.2f}"})
            
            # Seize business after 7 days of non-payment
            overdue_since = credit.get("overdue_since")
            if overdue_since:
                try:
                    os_dt = datetime.fromisoformat(overdue_since.replace("Z", "+00:00"))
                    overdue_total_days = (now - os_dt).days
                except Exception:
                    overdue_total_days = 0
                
                if overdue_total_days >= 7 and credit.get("status") == "overdue":
                    # SEIZE BUSINESS
                    biz_id = credit.get("collateral_business_id")
                    business = await db.businesses.find_one({"id": biz_id}, {"_id": 0})
                    
                    if business:
                        lender_type = credit.get("lender_type", "government")
                        lender_id = credit.get("lender_id", "government")
                        lender_name = credit.get("lender_name") or ("Государство" if lender_type == "government" else "Банк")
                        biz_plot_id = business.get("plot_id")
                        biz_x = business.get("plot_x") if business.get("plot_x") is not None else business.get("x")
                        biz_y = business.get("plot_y") if business.get("plot_y") is not None else business.get("y")
                        biz_island_id = business.get("island_id") or business.get("city_id") or "ton_island"

                        # Block D: seizure ALWAYS goes to the government and the
                        # business is auto-listed on the marketplace at −20% of
                        # `collateral_value`. The bank receives NOTHING from a
                        # default (only interest from regular repayments).
                        collateral_value = credit.get("collateral_value", 0)
                        sale_price = round(collateral_value * 0.80, 2)

                        await db.businesses.update_one({"id": biz_id}, {"$set": {
                            "owner": "government",
                            "owner_wallet": "government",
                            "owner_username": "Государство",
                            "for_sale": True,
                            "sale_price": sale_price,
                            "seized_from": borrower_id,
                            "seized_at": now.isoformat(),
                            "seized_credit_id": credit.get("id"),
                            "seized_original_lender_type": lender_type,
                            "seized_original_lender_name": lender_name,
                        }})

                        # Also list on land marketplace if plot exists
                        plot_id = biz_plot_id
                        if plot_id:
                            plot = await db.plots.find_one({"id": plot_id}, {"_id": 0})
                            if plot:
                                listing_id = str(uuid.uuid4())
                                listing = {
                                    "id": listing_id,
                                    "plot_id": plot_id,
                                    "city_id": plot.get("island_id", "ton_island"),
                                    "city_name": "GRAM Island",
                                    "x": plot.get("x", 0),
                                    "y": plot.get("y", 0),
                                    "seller_id": "government",
                                    "seller_wallet": "government",
                                    "seller_username": "Государство",
                                    "price": sale_price,
                                    "business": {
                                        "id": biz_id,
                                        "type": business.get("type") or business.get("business_type"),
                                        "level": business.get("level", 1),
                                        "tier": business.get("tier", 1)
                                    },
                                    "status": "active",
                                    "is_seized": True,
                                    "seized_from": borrower_id,
                                    "created_at": now.isoformat()
                                }
                                await db.land_listings.insert_one(listing)

                                # Update plot owner to government
                                await db.plots.update_one({"id": plot_id}, {"$set": {
                                    "owner": "government",
                                    "owner_wallet": "government",
                                    "owner_username": "Государство",
                                    "seized_from": borrower_id,
                                    "on_sale": True,
                                    "listing_id": listing_id,
                                }})

                                logger.warning(f"  📢 Land listing created for seized business at {sale_price} TON")

                        # Mirror ownership on the TON-Island cell so the map
                        # reflects the new owner instantly.
                        if biz_x is not None and biz_y is not None:
                            await db.islands.update_one(
                                {"id": biz_island_id, "cells.x": biz_x, "cells.y": biz_y},
                                {"$set": {
                                    "cells.$.owner": "government",
                                    "cells.$.owner_username": "Государство",
                                    "cells.$.on_sale": True,
                                    "cells.$.seized_from": borrower_id,
                                }}
                            )

                        logger.warning(f"  🏛️ Business {biz_id[:8]} SEIZED by government (orig lender: {lender_name}), listed at {sale_price} TON")

                        # Log seizure in the borrower's transaction history so
                        # they can see what happened (and which business went).
                        try:
                            seize_tx = {
                                "id": str(uuid.uuid4()),
                                "user_id": borrower_id,
                                "type": "business_seized",
                                "tx_type": "business_seized",
                                "amount": 0,
                                "amount_ton": 0,
                                "status": "completed",
                                "created_at": now.isoformat(),
                                "credit_id": credit.get("id"),
                                "details": {
                                    "lender_type": lender_type,
                                    "lender_name": lender_name,
                                    "business_id": biz_id,
                                    "business_type": business.get("type") or business.get("business_type"),
                                    "x": biz_x,
                                    "y": biz_y,
                                    "remaining_debt": credit.get("remaining", 0),
                                },
                            }
                            await db.transactions.insert_one(seize_tx)
                        except Exception as _seize_e:
                            logger.warning(f"seize tx insert failed: {_seize_e}")

                        # Mark credit as seized
                        await db.credits.update_one({"id": credit_id}, {"$set": {
                            "status": "seized",
                            "remaining": 0,
                            "seized_at": now.isoformat(),
                        }})
                        
                        # Notify borrower
                        from core.notify import notify_user as _nu
                        await _nu(db, borrower_id, title="Бизнес конфискован",
                                  message=f"Ваш бизнес конфискован за неуплату кредита! Кредитор: {lender_name}.",
                                  type_key="business_seized", priority="error",
                                  i18n_key="business_seized", i18n_vars={"lender": lender_name})
        
        logger.info("✅ Credit processing complete")
        # (shared client — no per-job close)
        pass
        
    except Exception as e:
        logger.error(f"❌ Credit processing error: {e}")


# ==================== WAREHOUSE SPOILAGE ====================

async def process_warehouse_spoilage():
    """
    Daily warehouse spoilage:
    If user's total warehouse usage exceeds capacity,
    50% of the overflow is destroyed each day.
    """
    try:
        db = _get_shared_db()
        
        now = datetime.now(timezone.utc)
        
        # Get all users with businesses
        users = await db.users.find({}, {"_id": 0, "id": 1, "wallet_address": 1, "username": 1}).to_list(1000)
        
        spoiled_count = 0
        
        for user in users:
            uid = user.get("id", "")
            wallet = user.get("wallet_address", "")

            # Get businesses
            or_q = [{"owner": uid}]
            if wallet:
                or_q.append({"owner": wallet})

            businesses = await db.businesses.find({"$or": or_q}, {"_id": 0}).to_list(50)
            if not businesses:
                continue

            # Capacity = sum of business storage capacity (same basis as display).
            total_capacity = 0
            for biz in businesses:
                total_capacity += biz.get("storage", {}).get("capacity", 0)

            # Used = WEIGHTED sum of the user's resources. This is the canonical
            # warehouse store (server.py /my/businesses computes used from
            # user.resources and explicitly does NOT count business.storage.items
            # — they are already mirrored into user.resources). Reading
            # business.storage.items here previously produced FALSE overflow /
            # spoilage even when the displayed usage was well under capacity.
            fresh_user = await db.users.find_one({"id": uid}, {"_id": 0, "resources": 1}) or {}
            user_resources = fresh_user.get("resources", {}) or {}
            total_used = 0
            res_items = []  # [(resource, weighted_amount, raw_amount)]
            for resource, amount in user_resources.items():
                raw = int(float(amount))
                if raw > 0:
                    w = raw * get_warehouse_weight(resource)
                    total_used += w
                    res_items.append((resource, w, raw))

            overflow = total_used - total_capacity
            if overflow <= 0:
                continue

            # 50% of the (weighted) overflow is destroyed.
            spoilage = int(overflow * 0.5)
            if spoilage <= 0:
                continue

            # Distribute spoilage proportionally across the user's resources,
            # destroying from the canonical user.resources store. `spoilage` is in
            # weighted units, so convert back to raw units per resource by weight.
            remaining_spoil = spoilage
            for resource, weighted_amt, raw_amt in sorted(res_items, key=lambda x: -x[1]):
                if remaining_spoil <= 0:
                    break
                w = get_warehouse_weight(resource) or 1
                destroy_raw = min(raw_amt, max(1, int(remaining_spoil / w)))
                if destroy_raw <= 0:
                    continue
                await db.users.update_one(
                    {"id": uid},
                    {"$inc": {f"resources.{resource}": -destroy_raw}}
                )
                remaining_spoil -= destroy_raw * w

            spoiled_count += 1
            logger.info(f"  🗑️ User {user.get('username', uid[:8])}: spoiled {spoilage} units (used {total_used}/{total_capacity})")

            # Notify user
            from core.notify import notify_user as _nu
            await _nu(db, uid, title="Склад переполнен",
                      message=f"Склад переполнен! Испорчено {spoilage} единиц товара.",
                      type_key="warehouse_spoilage", priority="warning",
                      i18n_key="warehouse_spoilage", i18n_vars={"spoilage": spoilage})
        
        logger.info(f"✅ Warehouse spoilage: {spoiled_count} users affected")
        # (shared client — no per-job close)
        pass
    except Exception as e:
        logger.error(f"❌ Warehouse spoilage error: {e}")



# ==================== NOTIFICATIONS SENDER ====================

async def send_pending_notifications():
    """Send pending notifications via Telegram (generic sender).
    
    i18n: message wrapper (heading and inline home button) is rendered in
    the user's preferred language (`users.language`, ru/en supported —
    everything else falls back to en). The per-notification `title` and
    `message` fields are sent verbatim — callers are expected to have
    stored them already localised (see `notify_user` in core/notify.py).
    """
    try:
        db = _get_shared_db()
        
        # Unified flag: `telegram_sent`. `low_resource` is excluded because
        # the dedicated `_send_low_resource_tg_batch` sender inside
        # `economic_tick` composes a consolidated message with an inline
        # "💎 Купить ресурсы / Buy resources" keyboard. Both senders now
        # use the same `telegram_sent` field for dedup; the type filter
        # here is defence-in-depth against ordering races between the two.
        notifications = await db.notifications.find(
            {
                "read": False,
                "telegram_sent": {"$ne": True},
                "type": {"$ne": "low_resource"},
            },
            {"_id": 0}
        ).sort("created_at", -1).to_list(100)
        
        if not notifications:
            return
        
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if not bot_token:
            return

        # i18n: labels for the generic sender. Sub-keys are keyed by user
        # language; unknown languages fall back to English. Extend here to
        # add more locales in the future.
        _I18N = {
            "en": {
                "brand_line": "🏙️ <b>GRAM City</b>",
                "home_button": "🏠 Main menu",
            },
            "ru": {
                "brand_line": "🏙️ <b>GRAM City</b>",
                "home_button": "🏠 На главную",
            },
        }
        
        import aiohttp
        
        async with aiohttp.ClientSession() as session:
            for notif in notifications:
                user_id = notif.get("user_id", "")
                user = await db.users.find_one(
                    {"$or": [{"id": user_id}, {"wallet_address": user_id}]},
                    {"_id": 0}
                )
                if not user:
                    continue

                # Resolve Telegram chat_id: prefer the user's own
                # `telegram_chat_id`; only fall back to the username→chat
                # mapping when the modern field is missing. Skipping users
                # who have neither.
                chat_id = user.get("telegram_chat_id")
                if not chat_id and user.get("telegram_username"):
                    tg_mapping = await db.telegram_mappings.find_one(
                        {"username": user.get("telegram_username")},
                        {"_id": 0}
                    )
                    chat_id = (tg_mapping or {}).get("chat_id")
                if not chat_id:
                    continue

                # Language pick (ru/en, default en). Same rule as
                # _send_low_resource_tg_batch above.
                from core.notif_i18n import norm_lang as _nl2, label as _lbl2
                ulang = _nl2(user.get("language"))
                labels = {"brand_line": "🏙️ <b>GRAM City</b>", "home_button": _lbl2("home_button", ulang)}

                title_txt = notif.get("title") or ""
                body_txt = notif.get("message", "")
                # Layout: brand line → bold title → body. `title` is only
                # included when present so old-style notifications (body
                # only) still render cleanly.
                parts = [labels["brand_line"]]
                if title_txt:
                    parts.append(f"<b>{title_txt}</b>")
                parts.append(body_txt)
                message = "\n\n".join(p for p in parts if p)

                reply_markup = {
                    "inline_keyboard": [
                        [{"text": labels["home_button"], "callback_data": "back_to_menu"}]
                    ]
                }

                try:
                    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage"
                    await session.post(url, json={
                        "chat_id": chat_id,
                        "text": message,
                        "parse_mode": "HTML",
                        "reply_markup": reply_markup,
                    })
                    
                    await db.notifications.update_one(
                        {"user_id": user_id, "created_at": notif["created_at"]},
                        {"$set": {"telegram_sent": True}}
                    )
                except Exception as e:
                    logger.error(f"Telegram send error: {e}")
        
    except Exception as e:
        logger.error(f"❌ Notification sender error: {e}")


async def send_withdrawal_unlock_notifications():
    """Send Telegram notifications when withdrawal lock expires"""
    try:
        db = _get_shared_db()
        
        now = datetime.now(timezone.utc)
        
        # Find scheduled notifications that are due and not sent
        scheduled = await db.scheduled_notifications.find({
            "type": "withdrawal_unlocked",
            "sent": False,
            "scheduled_at": {"$lte": now.isoformat()}
        }).to_list(100)
        
        if not scheduled:
            # (shared client — no per-job close)
            pass
            return
        
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if not bot_token:
            logger.warning("TELEGRAM_BOT_TOKEN not set, skipping withdrawal unlock notifications")
            # (shared client — no per-job close)
            pass
            return
        
        import aiohttp
        
        async with aiohttp.ClientSession() as session:
            for notif in scheduled:
                user_id = notif.get("user_id")
                user = await db.users.find_one(
                    {"$or": [{"id": user_id}, {"wallet_address": user_id}]},
                    {"_id": 0}
                )
                
                if not user:
                    await db.scheduled_notifications.update_one(
                        {"_id": notif.get("_id")},
                        {"$set": {"sent": True, "error": "user_not_found"}}
                    )
                    continue
                
                # Get telegram chat_id
                tg_username = user.get("telegram_username")
                if not tg_username:
                    await db.scheduled_notifications.update_one(
                        {"_id": notif.get("_id")},
                        {"$set": {"sent": True, "error": "no_telegram"}}
                    )
                    continue
                
                tg_mapping = await db.telegram_mappings.find_one(
                    {"username": tg_username},
                    {"_id": 0}
                )
                
                if not tg_mapping or not tg_mapping.get("chat_id"):
                    await db.scheduled_notifications.update_one(
                        {"_id": notif.get("_id")},
                        {"$set": {"sent": True, "error": "no_chat_id"}}
                    )
                    continue
                
                chat_id = tg_mapping["chat_id"]
                message = "🔓 <b>Вывод средств разблокирован!</b>\n\nБлокировка после изменения настроек 2FA снята. Теперь вы можете выводить средства."
                
                try:
                    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage"
                    resp = await session.post(url, json={
                        "chat_id": chat_id,
                        "text": message,
                        "parse_mode": "HTML"
                    })
                    
                    await db.scheduled_notifications.update_one(
                        {"_id": notif.get("_id")},
                        {"$set": {"sent": True, "sent_at": now.isoformat()}}
                    )
                    
                    logger.info(f"✅ Withdrawal unlock notification sent to user {user_id}")
                    
                except Exception as e:
                    logger.error(f"Failed to send withdrawal unlock notification: {e}")
                    await db.scheduled_notifications.update_one(
                        {"_id": notif.get("_id")},
                        {"$set": {"error": str(e)}}
                    )
        
        # (shared client — no per-job close)
        pass
        
    except Exception as e:
        logger.error(f"❌ Withdrawal unlock notification error: {e}")


# ==================== ALLIANCE CONTRACT EXPIRATION ====================

async def expire_alliance_contracts():
    """
    Mark alliance contracts (collection: `contracts`) as 'expired' once
    their `expires_at` has passed, and strip `contract_buff`/`contract_id`
    (and `patron_id` if this contract created the patron linkage) from
    the vassal's business so buffs stop taking effect immediately.
    """
    try:
        db = _get_shared_db()
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        # Active contracts whose expires_at has passed
        due = await db.contracts.find(
            {"status": "active", "expires_at": {"$lte": now_iso}},
            {"_id": 0},
        ).to_list(length=None)

        expired_count = 0
        for c in due:
            # Mark as expired
            await db.contracts.update_one(
                {"id": c["id"]},
                {"$set": {"status": "expired", "expires_at_actual": now_iso}},
            )
            # Detach contract_buff/contract_id from the vassal's business.
            # NOTE: patron_id stays — patron relationship has its own 7-day cooldown rule
            # and is not automatically dissolved when the alliance contract ends.
            vbid = c.get("vassal_business_id")
            if vbid:
                await db.businesses.update_one(
                    {"id": vbid, "contract_id": c["id"]},
                    {"$unset": {"contract_buff": "", "contract_id": ""}},
                )
            expired_count += 1

        if expired_count:
            logger.info(f"⏳ Alliance contracts expired: {expired_count}")

        # (shared client — no per-job close)
        pass
    except Exception as e:
        logger.error(f"❌ expire_alliance_contracts error: {e}")


async def publish_scheduled_announcements():
    """Publish announcements whose scheduled_at time has arrived."""
    try:
        import server as _srv
        # Serialize with manual broadcasts: if a fan-out is already running,
        # skip this tick and retry on the next one (leave items 'scheduled').
        if getattr(_srv, "_broadcast_active", False):
            return
        db = _get_shared_db()
        now_iso = datetime.now(timezone.utc).isoformat()
        due = await db.announcements.find(
            {"status": "scheduled", "scheduled_at": {"$lte": now_iso}}, {"_id": 0}
        ).to_list(100)
        if not due:
            return
        from server import _publish_announcement  # lazy import to avoid circular import
        _srv._broadcast_active = True
        try:
            for ann in due:
                # Atomically claim so we don't double-publish on overlapping runs.
                claimed = await db.announcements.update_one(
                    {"id": ann["id"], "status": "scheduled"},
                    {"$set": {"status": "published", "published_at": datetime.now(timezone.utc).isoformat()}},
                )
                if claimed.modified_count == 0:
                    continue
                try:
                    await _publish_announcement(ann)
                    logger.info(f"Published scheduled announcement: {ann.get('title')}")
                except Exception as e:
                    logger.error(f"Failed to publish scheduled announcement {ann.get('id')}: {e}")
        finally:
            _srv._broadcast_active = False
    except Exception as e:
        logger.error(f"publish_scheduled_announcements error: {e}")


async def auto_complete_expired_tutorials_job():
    """Auto-finish tutorials idle for >20 min (grants a random T3 on the
    user's FIRST completion only). See routes.tutorial for the core logic."""
    try:
        db = _get_shared_db()
        from routes.tutorial import auto_complete_expired_tutorials
        n = await auto_complete_expired_tutorials(db, timeout_minutes=20)
        if n:
            logger.info(f"⏱️ Auto-completed {n} expired tutorial(s)")
    except Exception as e:
        logger.error(f"auto_complete_expired_tutorials_job error: {e}")


async def seize_inactive_businesses_job():
    """Ежедневно изымает бизнесы у неактивных на рынке пользователей."""
    try:
        _db = _get_shared_db()
        from inactivity import seize_inactive_businesses
        res = await seize_inactive_businesses(_db)
        logger.info(f"🏛️ Inactivity seizure job: {res}")
    except Exception as e:
        logger.error(f"seize_inactive_businesses_job error: {e}")


async def smart_price_watch_job():
    try:
        import smart_notify as _sn
        if _sn._DB is None:
            _sn.init(_get_shared_db())
        res = await _sn.price_watch()
        if res.get("alerts"):
            logger.info(f"📈 smart price alerts: {res}")
    except Exception as e:
        logger.warning(f"smart_price_watch_job failed: {e}")


async def smart_queue_flush_job():
    try:
        import smart_notify as _sn
        if _sn._DB is None:
            _sn.init(_get_shared_db())
        res = await _sn.flush_queue()
        if res.get("sent") or res.get("dropped"):
            logger.info(f"🌙 smart quiet-hours queue: {res}")
    except Exception as e:
        logger.warning(f"smart_queue_flush_job failed: {e}")


def init_scheduler():
    """Initialize APScheduler with all background tasks"""
    global scheduler
    
    # one run at a time per job, missed runs are merged into one (no overlap, no burst)
    scheduler = AsyncIOScheduler(job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 60})
    # Main economic tick - every minute.
    # coalesce=True → if we fell behind for any reason (long DB latency, host
    #   pause, deploy), collapse the missed runs into a single one instead of
    #   trying to catch up N ticks in a row.
    # max_instances=1 → default, but explicit for clarity.
    # misfire_grace_time=30 → APScheduler still fires the tick even if it
    #   arrives up to 30 s late, but never queues additional ones behind it.
    scheduler.add_job(
        economic_tick,
        trigger=IntervalTrigger(minutes=1),
        id="economic_tick",
        name="Economic Tick (Every Minute)",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=30,
    )
    
    # Smart notifications: market price watch (hourly) + quiet-hours Telegram queue (every 10 min)
    scheduler.add_job(
        smart_price_watch_job,
        trigger=IntervalTrigger(hours=1),
        id="smart_price_watch",
        name="Smart notifications: market price watch (hourly)",
        replace_existing=True, coalesce=True, max_instances=1,
    )
    scheduler.add_job(
        smart_queue_flush_job,
        trigger=IntervalTrigger(minutes=10),
        id="smart_queue_flush",
        name="Smart notifications: deliver after quiet hours",
        replace_existing=True, coalesce=True, max_instances=1,
    )

    # Midnight decay - daily at 21:00 UTC (00:00 MSK)
    scheduler.add_job(
        midnight_decay,
        trigger=CronTrigger(hour=21, minute=0),
        id="midnight_decay",
        name="Midnight Decay (00:00 MSK)",
        replace_existing=True,
    )

    # Daily seizure of inactive users' businesses (market activity check).
    scheduler.add_job(
        seize_inactive_businesses_job,
        trigger=CronTrigger(hour=22, minute=30),
        id="seize_inactive_businesses",
        name="Seize inactive users' businesses (daily)",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )

    # Forced seizure sweep - daily at 21:15 UTC. Seizes businesses that sat at 0%
    # durability for 7 days and collateral of defaulted credits (GRAM CITY resale).
    async def _seizure_job():
        try:
            from core.seizure import process_seizures
            await process_seizures(_get_shared_db())
        except Exception as e:
            logger.error(f"seizure job failed: {e}")
    scheduler.add_job(
        _seizure_job,
        trigger=CronTrigger(hour=21, minute=15),
        id="forced_seizure_sweep",
        name="Forced Seizure Sweep (daily)",
        replace_existing=True,
    )

    # Level-0 (test) business 3-day lease — every 10 min: warn 12h before expiry,
    # remove the business + free the plot at expiry, cancel its market lots.
    async def _zero_lease_job():
        try:
            from zero_lease import process_zero_lease
            await process_zero_lease(_get_shared_db())
        except Exception as e:
            logger.error(f"zero-lease job failed: {e}")
    scheduler.add_job(
        _zero_lease_job,
        trigger=IntervalTrigger(minutes=10),
        id="zero_lease_sweep",
        name="Level-0 lease sweep (every 10 min)",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )

    # Market resource lots that sit unsold for 48h — every 15 min: auto-cancel
    # and return the resources to the seller with a localized tip.
    async def _market_lot_expiry_job():
        try:
            from zero_lease import process_market_lot_expiry
            await process_market_lot_expiry(_get_shared_db())
        except Exception as e:
            logger.error(f"market-lot expiry job failed: {e}")
    scheduler.add_job(
        _market_lot_expiry_job,
        trigger=IntervalTrigger(minutes=15),
        id="market_lot_expiry",
        name="Market lot 48h expiry (every 15 min)",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )

    # (The old 24h auto-buyback of level-0 lots was removed: the City Market
    #  buys them after 30 minutes, with tax, limits and a journal — market_maker.py.)

    # Durability wear - every 6 hours (as backup, main wear happens in tick)
    scheduler.add_job(
        apply_global_durability_wear,
        trigger=IntervalTrigger(hours=6),
        id="durability_wear",
        name="Durability Wear Check",
        replace_existing=True,
    )
    
    # Credit processing - daily at 22:00 UTC (01:00 MSK)
    scheduler.add_job(
        process_credits,
        trigger=CronTrigger(hour=22, minute=0),
        id="credit_processing",
        name="Credit Processing Daily",
        replace_existing=True,
    )
    
    # Warehouse spoilage - daily at 21:30 UTC (00:30 MSK)
    scheduler.add_job(
        process_warehouse_spoilage,
        trigger=CronTrigger(hour=21, minute=30),
        id="warehouse_spoilage",
        name="Warehouse Spoilage Daily",
        replace_existing=True,
    )
    
    # Notification sender - every 5 minutes
    scheduler.add_job(
        send_pending_notifications,
        trigger=IntervalTrigger(minutes=5),
        id="notification_sender",
        name="Notification Sender",
        replace_existing=True,
    )
    
    # Withdrawal unlock notifications - every 1 minute (for testing)
    scheduler.add_job(
        send_withdrawal_unlock_notifications,
        trigger=IntervalTrigger(minutes=5),
        id="withdrawal_unlock_notifications",
        name="Withdrawal Unlock Notifications",
        replace_existing=True,
    )
    
    # Auto-withdrawal processor - every 10 minutes
    scheduler.add_job(
        process_auto_withdrawals,
        trigger=IntervalTrigger(minutes=10),
        id="auto_withdrawal_processor",
        name="Auto Withdrawal Processor",
        replace_existing=True,
    )

    # Alliance contract expiration - every minute
    scheduler.add_job(
        expire_alliance_contracts,
        trigger=IntervalTrigger(minutes=5),
        id="alliance_contract_expiration",
        name="Alliance Contract Expiration",
        replace_existing=True,
    )

    # Scheduled announcements publisher - every minute
    scheduler.add_job(
        publish_scheduled_announcements,
        trigger=IntervalTrigger(minutes=1),
        id="scheduled_announcements",
        name="Scheduled Announcements Publisher",
        replace_existing=True,
        coalesce=True,
    )

    # Tutorial auto-complete — every minute; finishes tutorials idle >20 min
    scheduler.add_job(
        auto_complete_expired_tutorials_job,
        trigger=IntervalTrigger(minutes=5),
        id="tutorial_auto_complete",
        name="Tutorial Auto-Complete (20m timeout)",
        replace_existing=True,
        coalesce=True,
    )

    # Tender (B2B) clearing — every 5 minutes (with catch-up logic for missed hours).
    # The previous CronTrigger(minute=0) was fragile: if backend was down or restarted
    # at HH:00 UTC, the entire hourly clearing was missed. Now we run every 5 min and
    # run_tender_clearing() picks up overdue contracts even if their HH:00 was missed.
    try:
        from routes.tenders import run_tender_clearing as _tender_clearing
        scheduler.add_job(
            _tender_clearing,
            trigger=IntervalTrigger(minutes=5),
            id="tender_clearing",
            name="Tender B2B Clearing (every 5 min + catch-up)",
            replace_existing=True,
            misfire_grace_time=3600,  # tolerate up to 1h of scheduler downtime
            coalesce=True,
        )
        logger.info("📅 Tender Clearing: Every 5 minutes (catch-up enabled, misfire_grace=1h)")
    except Exception as _e:
        logger.warning("tender clearing job not registered: %s", _e)

    # ==== Referral Rally promo jobs ====
    try:
        from promo_scheduler import (
            referral_rally_freeze_job, referral_rally_reminder_job,
        )
        # Freeze check — every minute
        scheduler.add_job(
            referral_rally_freeze_job,
            trigger=IntervalTrigger(minutes=1),
            id="referral_rally_freeze",
            name="Referral Rally Freeze Check (every minute)",
            replace_existing=True,
            coalesce=True,
        )
        # Smart reminder push — every 5 minutes.
        # Fires "day_before" (≤24h to end) and "final_hour" (≤60min to end)
        # broadcasts, each at most once per campaign.
        scheduler.add_job(
            referral_rally_reminder_job,
            trigger=IntervalTrigger(minutes=5),
            id="referral_rally_reminder",
            name="Referral Rally Reminder Push (24h & final-hour)",
            replace_existing=True,
            misfire_grace_time=600,
            coalesce=True,
        )
        # NOTE: the automatic daily 10:00 MSK broadcast was removed — the promo
        # broadcast is now triggered MANUALLY by the admin via the "Разослать"
        # button in the promo panel (POST /api/admin/promo/referral-rally/broadcast).
        logger.info("📅 Referral Rally: freeze/minute + reminder push every 5 min")
    except Exception as _e:
        logger.warning("referral rally jobs not registered: %s", _e)
    
    # Daily user-ideas digest — every day at 07:00 UTC (10:00 MSK).
    # Collects all un-sent ideas into a Russian .txt and sends it as a Telegram
    # document to every admin with a connected Telegram chat.
    async def _ideas_digest_job():
        try:
            from routes.roadmap import send_daily_ideas_digest
            await send_daily_ideas_digest(_get_shared_db())
        except Exception as e:
            logger.error(f"ideas digest job failed: {e}")
    scheduler.add_job(
        _ideas_digest_job,
        trigger=CronTrigger(hour=7, minute=0),
        id="daily_ideas_digest",
        name="Daily User Ideas Digest (10:00 MSK)",
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
    )
    logger.info("📅 Ideas Digest: Daily at 07:00 UTC (10:00 MSK)")

    logger.info("✅ Scheduler initialized with V2.0 economic engine")
    logger.info("📅 Economic Tick: Every 1 minute")
    logger.info("📅 Midnight Decay: Daily at 21:00 UTC (00:00 MSK)")
    logger.info("📅 Durability Wear: Every 6 hours")
    logger.info("📅 Credit Processing: Daily at 22:00 UTC")
    logger.info("📅 Warehouse Spoilage: Daily at 21:30 UTC")
    logger.info("📅 Notifications: Every 5 minutes")
    logger.info("📅 Auto Withdrawals: Every 10 minutes")
    
    return scheduler


def start_scheduler():
    """Start the scheduler"""
    global scheduler
    if scheduler is None:
        init_scheduler()
    if not scheduler.running:
        scheduler.start()
        logger.info("🚀 Scheduler started")
        # Ensure economic-tick indexes exist as soon as the leader starts.
        # `bulk_write` filters on {"id": ...} explode without them; the
        # per-collection create_index calls are idempotent and cheap.
        try:
            asyncio.create_task(_ensure_economic_tick_indexes(_get_shared_db()))
        except Exception as _e:
            logger.warning(f"[scheduler] index bootstrap task failed: {_e}")
        # Immediately run a tender clearing pass on startup to catch up on any
        # contracts that became overdue while the backend was offline.
        try:
            from routes.tenders import run_tender_clearing as _tender_clearing
            asyncio.create_task(_tender_clearing())
            logger.info("⚡ Startup tender clearing catch-up scheduled")
        except Exception as _e:
            logger.warning("startup tender catch-up failed: %s", _e)


def shutdown_scheduler():
    """Shutdown the scheduler"""
    global scheduler
    if scheduler and scheduler.running:
        scheduler.shutdown()
        logger.info("🛑 Scheduler stopped")


async def trigger_auto_collection_now():
    """Manually trigger economic tick"""
    logger.info("🔧 Manual economic tick triggered...")
    await economic_tick()


async def process_auto_withdrawals():
    """
    Auto-process withdrawals:
    1. Instant withdrawals: process immediately when pending
    2. Standard withdrawals: auto-approve after 24 hours if admin hasn't acted
    """
    try:
        logger.info("💸 === AUTO WITHDRAWAL PROCESSOR STARTED ===")
        
        db = _get_shared_db()
        
        now = datetime.now(timezone.utc)
        hours_24_ago = now - timedelta(hours=24)
        
        # Get withdrawal wallet mnemonic. F2: mnemonics are stored encrypted
        # (Fernet, prefix `enc::`), so we MUST decrypt before passing to the
        # TON SDK. Without this, `Wallets.from_mnemonics(...)` fails because
        # it receives ciphertext.
        from mnemonic_crypto import decrypt_mnemonic

        withdrawal_wallet = await db.admin_settings.find_one({"type": "withdrawal_wallet"}, {"_id": 0})
        seed = decrypt_mnemonic(withdrawal_wallet.get("mnemonic")) if withdrawal_wallet else None

        if not seed:
            sender_wallet = await db.admin_settings.find_one({"type": "sender_wallet"}, {"_id": 0})
            seed = decrypt_mnemonic(sender_wallet.get("mnemonic")) if sender_wallet else None

        if not seed:
            seed = os.environ.get("TON_WALLET_MNEMONIC")
        
        if not seed:
            logger.warning("💸 No withdrawal wallet configured - skipping auto withdrawals")
            # (shared client — no per-job close)
            pass
            return
        
        # 1. Process instant withdrawals (process immediately)
        instant_pending = await db.transactions.find({
            "tx_type": "instant_withdrawal",
            "status": "pending"
        }, {"_id": 0}).to_list(50)
        
        logger.info(f"💸 Found {len(instant_pending)} instant withdrawals to process")
        
        for tx in instant_pending:
            await process_single_withdrawal(db, tx, seed)
        
        # 2. Process standard withdrawals older than 24 hours
        standard_pending = await db.transactions.find({
            "tx_type": {"$in": ["withdrawal", None]},
            "type": "withdrawal",
            "status": "pending",
            "created_at": {"$lte": hours_24_ago.isoformat()}
        }, {"_id": 0}).to_list(50)
        
        logger.info(f"💸 Found {len(standard_pending)} standard withdrawals older than 24h")
        
        for tx in standard_pending:
            await process_single_withdrawal(db, tx, seed)
        
        # (shared client — no per-job close)
        pass
        logger.info("💸 === AUTO WITHDRAWAL PROCESSOR COMPLETED ===")
        
    except Exception as e:
        logger.error(f"❌ Error in auto withdrawal processor: {e}")


async def process_single_withdrawal(db, tx: dict, seed: str):
    """Process a single withdrawal with double-send protection"""
    tx_id = tx.get("id")
    
    try:
        # Atomic lock to prevent double processing
        result = await db.transactions.find_one_and_update(
            {"id": tx_id, "status": "pending"},
            {"$set": {"status": "processing", "auto_processing_started": datetime.now(timezone.utc).isoformat()}},
            return_document=True
        )
        
        if not result:
            logger.info(f"💸 Withdrawal {tx_id} already being processed or completed")
            return
        
        user_wallet = tx.get("user_wallet")
        from core.helpers import find_user
        user = await find_user(db, user_id=tx.get("user_id"), wallet=user_wallet)
        
        # Determine destination address
        destination = None
        if user:
            destination = user.get("raw_address") or user.get("wallet_address")
        if not destination:
            destination = tx.get("user_raw_address") or tx.get("to_address") or user_wallet
        
        if not destination:
            logger.error(f"❌ No destination address for withdrawal {tx_id}")
            await db.transactions.update_one({"id": tx_id}, {"$set": {"status": "failed", "error": "No destination"}})
            return
        
        net_amount = float(tx.get("net_amount", 0))
        commission = float(tx.get("commission", 0))
        amount_ton_original = float(tx.get("amount_ton", 0)) or (net_amount + commission)
        
        user_username = user.get("username", "") if user else ""
        
        # Import ton_integration dynamically
        try:
            from ton_integration import TonIntegration
            ton_client = TonIntegration()
            
            tx_hash = await ton_client.send_ton_payout(
                dest_address=destination,
                amount_ton=net_amount,
                mnemonics=seed,
                user_username=user_username
            )
            
            # Success
            now_iso = datetime.now(timezone.utc).isoformat()
            await db.transactions.update_one(
                {"id": tx_id},
                {"$set": {
                    "status": "completed",
                    "completed_at": now_iso,
                    "blockchain_hash": tx_hash,
                    "auto_processed": True
                }}
            )
            
            # Block B: pay the bank fee to the bank owner ONLY on success
            # (held by the platform/admin until the payout completes).
            bank_fee = float(tx.get("bank_fee", 0) or 0)
            bank_owner = tx.get("bank_owner")
            if bank_fee > 0 and bank_owner:
                await db.users.update_one(
                    {"$or": [{"id": bank_owner}, {"wallet_address": bank_owner}]},
                    {"$inc": {"balance_ton": bank_fee, "total_income": bank_fee}}
                )
                await db.transactions.insert_one({
                    "id": str(uuid.uuid4()),
                    "type": "bank_fee_income",
                    "user_id": bank_owner,
                    "amount": bank_fee,
                    "amount_ton": bank_fee,
                    "description": f"Комиссия банка за мгновенный вывод +{bank_fee:.4f} TON",
                    "related_withdrawal_id": tx_id,
                    "status": "completed",
                    "created_at": now_iso,
                    "completed_at": now_iso,
                })
            
            # Update stats
            commission = float(tx.get("platform_commission", 0) or tx.get("commission", 0) or 0)
            await db.admin_stats.update_one(
                {"type": "treasury"},
                {"$inc": {"withdrawal_fees": commission, "total_withdrawals": net_amount, "total_withdrawals_count": 1}},
                upsert=True
            )
            
            logger.info(f"✅ Auto-withdrawal {tx_id} completed: {net_amount} TON to {destination[:20]}...")
            
        except Exception as e:
            logger.error(f"❌ Blockchain error for withdrawal {tx_id}: {e}")
            # Return funds
            await db.users.update_one(
                {"wallet_address": user_wallet},
                {"$inc": {"balance_ton": amount_ton_original}}
            )
            await db.transactions.update_one(
                {"id": tx_id},
                {"$set": {"status": "failed", "error": str(e), "auto_processed": True}}
            )
            
    except Exception as e:
        logger.error(f"❌ Error processing withdrawal {tx_id}: {e}")
