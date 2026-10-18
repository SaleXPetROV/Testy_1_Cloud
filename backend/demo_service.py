"""
Demo (Sandbox) mode service.
=============================
Phase 1 core: fully-isolated demo profiles kept in the `demo_profiles`
collection. A demo profile NEVER touches the user's real balance / resources /
businesses. On first entry the user is granted ONE Tier-1 business (chosen by a
"dynamic deficit balancing" algorithm over the REAL map) plus 5000 demo $CITY.

The demo business always lives on the single virtual demo plot at [13, 12].
"""
import logging
import math
import random
import uuid
from datetime import datetime, timezone
from core.dtutils import to_aware

from ton_island import CITY_BUSINESSES

try:
    from business_config import (
        BUSINESSES as _BIZ_CFG, RESOURCE_TYPES as _RES_CFG,
        get_production as _get_production, get_storage_capacity as _get_storage_capacity,
        get_consumption_breakdown as _get_consumption_breakdown,
        calculate_upgrade_cost as _calculate_upgrade_cost,
        get_warehouse_weight as _get_warehouse_weight,
        BUSINESS_KEY_MAP as _BIZ_KEY_MAP,
    )
except Exception:  # pragma: no cover
    _BIZ_CFG, _RES_CFG, _BIZ_KEY_MAP = {}, {}, {}
    def _get_production(t, l):
        return 100
    def _get_storage_capacity(t, l):
        return 360
    def _get_consumption_breakdown(t, l):
        return {}
    def _calculate_upgrade_cost(t, l):
        return None
    def _get_warehouse_weight(rt):
        return 1


def _weighted_storage(resources: dict) -> tuple[dict, int]:
    """Convert a raw resource dict into (items_map_in_slots, total_slots_used).
    The TOTAL comes from the one warehouse rule of the whole game
    (core/warehouse.used_by_resources), so demo and real mode can never drift."""
    from core.warehouse import used_by_resources
    items_slots: dict[str, int] = {}
    for res, qty in (resources or {}).items():
        q = int(qty or 0)
        if q > 0:
            items_slots[res] = q * int(_get_warehouse_weight(res) or 1)
    return items_slots, int(used_by_resources(resources))


def _resolve_cfg(biz_type: str) -> dict:
    """Resolve BUSINESSES config using BUSINESS_KEY_MAP so ton_island keys
    like ``cold_storage`` map to their real ``hydro_cooling`` config."""
    if biz_type in _BIZ_CFG:
        return _BIZ_CFG[biz_type]
    mapped = _BIZ_KEY_MAP.get(biz_type, biz_type)
    return _BIZ_CFG.get(mapped, {})


# The demo economy runs without any production buff — 1:1 with the real base
# production table. If the design ever wants to demonstrate the buff in the
# sandbox again, raise this above 1.0 and both the visible number AND the
# accrual math in demo_collect will pick it up automatically.
DEMO_TEST_BUFF_MULTIPLIER = 1.0

logger = logging.getLogger(__name__)

DEMO_START_CITY = 5000.0
DEMO_PLOT_COORDS = [13, 12]
DEMO_REFERRAL_BONUS = 5000.0  # +5 000 $CITY on the demo balance per referral
# Demo durability loss (% per day) fallback when config lacks a wear range.
DEMO_WEAR_PER_DAY_DEFAULT = 2.5


# Tier-1 business keys (source of truth = ton_island.CITY_BUSINESSES).
TIER1_KEYS = [k for k, v in CITY_BUSINESSES.items() if v.get("tier") == 1]


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


async def pick_deficit_tier1_business(db) -> str:
    """Dynamic Deficit Balancing.

    Pick the Tier-1 business type that has been REALLY purchased the least on
    the island map. Ties → random among the least-bought. Tier 2/3 are only
    considered once Tier-1 reaches parity, which by construction means the
    minimum count is shared by every Tier-1 type — we still return a Tier-1
    type (the demo always starts on Tier 1).
    """
    counts = {k: 0 for k in TIER1_KEYS}
    try:
        pipeline = [
            {"$match": {"business_type": {"$in": TIER1_KEYS}}},
            {"$group": {"_id": "$business_type", "n": {"$sum": 1}}},
        ]
        async for row in db.businesses.aggregate(pipeline):
            if row.get("_id") in counts:
                counts[row["_id"]] = int(row.get("n", 0))
    except Exception as e:  # pragma: no cover
        logger.warning(f"[demo] deficit count failed: {e}")

    if not counts:
        return random.choice(TIER1_KEYS) if TIER1_KEYS else "helios"

    min_count = min(counts.values())
    least = [k for k, n in counts.items() if n == min_count]
    return random.choice(least)


def _build_demo_business(biz_type: str) -> dict:
    cfg = CITY_BUSINESSES.get(biz_type, {})
    return {
        "id": str(uuid.uuid4()),
        "type": biz_type,
        "name": cfg.get("name", {"en": biz_type, "ru": biz_type}),
        "icon": cfg.get("icon", "🏢"),
        "tier": cfg.get("tier", 1),
        "level": 1,
        "durability": 100,
        "monthly_income_ton": cfg.get("monthly_income_ton", 0),
        "monthly_income_city": cfg.get("monthly_income_ton", 0) * 1000,
        "storage": {},
        "x": DEMO_PLOT_COORDS[0],
        "y": DEMO_PLOT_COORDS[1],
        "built_at": _now_iso(),
        "last_collection": _now_iso(),
    }


def _serialize(profile: dict) -> dict:
    if not profile:
        return None
    profile.pop("_id", None)
    return profile


async def get_or_create_demo_profile(db, user_id: str) -> dict:
    """Return the user's demo profile, creating it (with a granted Tier-1
    business + 5000 demo $CITY) on first access. Idempotent."""
    existing = await db.demo_profiles.find_one({"user_id": user_id})
    if existing:
        return _serialize(existing)

    biz_type = await pick_deficit_tier1_business(db)
    demo_biz = _build_demo_business(biz_type)
    # Per spec: the user starts with ONLY the demo business + 5 000 $CITY.
    # No starter input resources — mirrors real mode (players must buy inputs
    # via the demo NPC market before the business begins to produce).
    profile = {
        "user_id": user_id,
        "demo_balance_city": DEMO_START_CITY,
        "demo_resources": {},
        "demo_business": demo_biz,
        "demo_business_coords": DEMO_PLOT_COORDS,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    try:
        await db.demo_profiles.insert_one(dict(profile))
    except Exception as e:
        logger.error(f"[demo] create profile failed: {e}")
        # Re-read in case of a concurrent insert race.
        existing = await db.demo_profiles.find_one({"user_id": user_id})
        if existing:
            return _serialize(existing)
        raise
    logger.info(f"[demo] created demo profile for {user_id} with business {biz_type}")
    return _serialize(profile)



# ──────────────────────────────────────────────────────────────────────────
# Phase 2 — demo economy (production + wear + repair, quick trade, referral).
# All operations are confined to the demo_profiles document. Nothing here
# touches real balances / resources / businesses.
# ──────────────────────────────────────────────────────────────────────────

def _res_meta(res: str) -> dict:
    return _RES_CFG.get(res, {})


def resource_name(res: str) -> dict:
    m = _res_meta(res)
    return {"en": m.get("name_en", res), "ru": m.get("name_ru", res), "icon": m.get("icon", "📦"), "tier": int(m.get("tier", 1) or 1)}


async def get_npc_prices(db) -> dict:
    """Current NPC market prices (in TON per unit). Uses the live real-market
    prices when present, otherwise the resource base price."""
    prices = {}
    try:
        doc = await db.market_prices.find_one({"type": "current"})
        if doc and isinstance(doc.get("prices"), dict):
            prices = {k: float(v) for k, v in doc["prices"].items()}
    except Exception:
        prices = {}
    out = {}
    for res, meta in _RES_CFG.items():
        out[res] = float(prices.get(res, meta.get("base_price", 1.0)))
    return out


def _biz_tier(biz: dict) -> int:
    return int(biz.get("tier", 1) or 1)


def _wear_per_day(biz_type: str) -> float:
    cfg = _resolve_cfg(biz_type)
    rng = cfg.get("daily_wear_range")
    if isinstance(rng, (list, tuple)) and len(rng) == 2:
        return ((float(rng[0]) + float(rng[1])) / 2.0) * 100.0
    return DEMO_WEAR_PER_DAY_DEFAULT


async def _save_profile(db, user_id: str, set_doc: dict):
    set_doc["updated_at"] = _now_iso()
    await db.demo_profiles.update_one({"user_id": user_id}, {"$set": set_doc})


async def demo_collect(db, user_id: str) -> dict:
    """Produce & bank resources from the demo business since last collection,
    applying durability wear. Consumes required inputs from demo_resources."""
    profile = await get_or_create_demo_profile(db, user_id)
    biz = dict(profile.get("demo_business") or {})
    if not biz:
        return {"status": "no_business"}

    biz_type = biz.get("type")
    cfg = _resolve_cfg(biz_type)
    produces = cfg.get("produces")
    consumes = cfg.get("consumes") or {}

    last = biz.get("last_collection") or biz.get("built_at") or _now_iso()
    last_dt = to_aware(last) or datetime.now(timezone.utc)
    hours = max(0.0, (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600.0)

    durability = float(biz.get("durability", 100))
    if durability <= 0:
        return {"status": "halted", "reason": "needs_repair", "durability": 0}

    resources = dict(profile.get("demo_resources") or {})
    level = int(biz.get("level", 1) or 1)
    # Real per-day production for this business/level (same as the live game).
    per_day_base = float(_get_production(biz_type, level) or 0)
    # Apply durability multiplier + demo test buff, mirroring the real economy.
    dur_mult = 0.0 if durability <= 0 else (0.8 if durability < 50 else 1.0)
    per_day = per_day_base * dur_mult * DEMO_TEST_BUFF_MULTIPLIER
    capacity = float(_get_storage_capacity(biz_type, level) or 0) or 360.0
    produced = per_day * (hours / 24.0)

    # Consumption uses the SAME leveled table as real mode (daily amount per
    # produced unit derived from consumption_breakdown / base_production).
    breakdown = _get_consumption_breakdown(biz_type, level) or {}
    if produces and breakdown:
        for in_res, daily_need in breakdown.items():
            per_unit = float(daily_need or 0) / float(per_day_base or 1)
            need = produced * per_unit
            have = float(resources.get(in_res, 0))
            if need > have and per_unit > 0:
                produced = min(produced, have / per_unit)
        for in_res, daily_need in breakdown.items():
            per_unit = float(daily_need or 0) / float(per_day_base or 1)
            spent = produced * per_unit
            if spent > 0:
                resources[in_res] = max(0.0, float(resources.get(in_res, 0)) - spent)

    collected = 0.0
    if produces and produces not in ("ton", "profit_ton"):
        # Weight the free slots in the warehouse (T1=1, T2=5, T3=20). The
        # produced resource is always the business' output tier; convert the
        # remaining capacity into units of the output resource before capping.
        _, used_slots = _weighted_storage(resources)
        prod_weight = int(_get_warehouse_weight(produces) or 1)
        free_slots = max(0.0, capacity - used_slots)
        free_units = free_slots / prod_weight if prod_weight > 0 else free_slots
        cur = float(resources.get(produces, 0))
        collected = round(min(produced, max(0.0, free_units)), 2)
        resources[produces] = round(cur + collected, 2)

    # Durability wear over the elapsed time.
    new_dur = round(max(0.0, durability - _wear_per_day(biz_type) * (hours / 24.0)), 2)
    biz["durability"] = new_dur
    biz["last_collection"] = _now_iso()

    await _save_profile(db, user_id, {"demo_resources": resources, "demo_business": biz})
    return {
        "status": "collected" if collected > 0 else "nothing",
        "produces": produces,
        "collected": collected,
        "hours": round(hours, 3),
        "durability": new_dur,
        "resources": resources,
    }


_REPAIR_COST_PER_PCT = {1: 1, 2: 5, 3: 20}  # flat $CITY per 1% durability, by tier


def _demo_repair_quote(biz: dict) -> dict:
    """Compute the demo repair quote in $CITY (mirrors real mode:
    cost_per_pct(tier) × missing%)."""
    durability = float(biz.get("durability", 100))
    missing = max(0.0, 100.0 - durability)
    tier = _biz_tier(biz)
    from business_config import repair_cost_per_pct_city as _rcp
    cost_per_pct = _rcp(biz.get("business_type") or "", tier, biz.get("level") or 1)       # same price as the real repair
    cost_city = round(cost_per_pct * missing, 2)
    return {
        "cost_city": cost_city,
        "base_cost_city": round(cost_per_pct * missing, 2),
        "cost_per_pct": cost_per_pct,
        "missing_pct": round(missing, 1),
        "durability": durability,
        "tier": tier,
    }


async def demo_repair_cost(db, user_id: str) -> dict:
    """Repair quote for the current demo business, priced in demo $CITY."""
    profile = await get_or_create_demo_profile(db, user_id)
    biz = dict(profile.get("demo_business") or {})
    if not biz:
        return {"status": "no_business"}
    quote = _demo_repair_quote(biz)
    quote["status"] = "ok"
    quote["demo_balance_city"] = round(float(profile.get("demo_balance_city", 0)), 2)
    return quote


async def demo_repair(db, user_id: str) -> dict:
    """Repair the demo business to 100% durability, paid in demo $CITY
    (same pricing model as real mode: cost_per_pct(tier) × missing%)."""
    profile = await get_or_create_demo_profile(db, user_id)
    biz = dict(profile.get("demo_business") or {})
    if not biz:
        return {"status": "no_business"}
    durability = float(biz.get("durability", 100))
    missing = max(0.0, 100.0 - durability)
    if missing <= 0.5:
        return {"status": "already_full", "durability": durability}

    quote = _demo_repair_quote(biz)
    cost_city = quote["cost_city"]
    balance = round(float(profile.get("demo_balance_city", 0)), 2)
    if balance < cost_city:
        return {"status": "insufficient", "need": cost_city, "have": balance, "currency": "city"}

    new_balance = round(balance - cost_city, 2)
    biz["durability"] = 100.0
    await _save_profile(db, user_id, {"demo_balance_city": new_balance, "demo_business": biz})
    return {
        "status": "repaired", "durability": 100.0,
        "paid_city": cost_city, "cost_city": cost_city,
        "demo_balance_city": new_balance,
    }


async def demo_quick_sell(db, user_id: str, resource: str, amount: float) -> dict:
    """Instantly sell demo resources to the system bot at the current NPC
    price. Proceeds credited to the demo $CITY balance. No history / notices."""
    amount = float(amount or 0)
    if amount <= 0:
        return {"status": "invalid_amount"}
    if resource not in _RES_CFG:
        return {"status": "unknown_resource"}
    profile = await get_or_create_demo_profile(db, user_id)
    resources = dict(profile.get("demo_resources") or {})
    have = float(resources.get(resource, 0))
    if have < amount:
        return {"status": "insufficient", "have": have}

    prices = await get_npc_prices(db)
    price = float(prices.get(resource, _res_meta(resource).get("base_price", 1.0)))
    proceeds_city = round(amount * price, 2)

    resources[resource] = round(have - amount, 2)
    new_balance = round(float(profile.get("demo_balance_city", 0)) + proceeds_city, 2)
    await _save_profile(db, user_id, {"demo_resources": resources, "demo_balance_city": new_balance})
    return {
        "status": "sold", "resource": resource, "amount": amount,
        "price_ton": price, "proceeds_city": proceeds_city,
        "demo_balance_city": new_balance, "resources": resources,
    }


async def demo_quick_buy(db, user_id: str, resource: str, amount: float) -> dict:
    """Instantly buy resources from the system bot at the current NPC price,
    paid from the demo $CITY balance."""
    amount = float(amount or 0)
    if amount <= 0:
        return {"status": "invalid_amount"}
    if resource not in _RES_CFG:
        return {"status": "unknown_resource"}
    profile = await get_or_create_demo_profile(db, user_id)
    prices = await get_npc_prices(db)
    price = float(prices.get(resource, _res_meta(resource).get("base_price", 1.0)))
    cost_city = round(amount * price, 2)
    balance = float(profile.get("demo_balance_city", 0))
    if balance < cost_city:
        return {"status": "insufficient_balance", "need": cost_city, "have": balance}

    resources = dict(profile.get("demo_resources") or {})
    resources[resource] = round(float(resources.get(resource, 0)) + amount, 2)
    new_balance = round(balance - cost_city, 2)
    await _save_profile(db, user_id, {"demo_resources": resources, "demo_balance_city": new_balance})
    return {
        "status": "bought", "resource": resource, "amount": amount,
        "price_ton": price, "cost_city": cost_city,
        "demo_balance_city": new_balance, "resources": resources,
    }


async def credit_demo_referral(db, referrer_user_id: str) -> dict:
    """Credit +5 000 $CITY to a referrer's DEMO balance for a new referral.
    Safe no-op if the referrer has no demo profile yet (it will be created)."""
    if not referrer_user_id:
        return {"status": "skipped"}
    profile = await get_or_create_demo_profile(db, referrer_user_id)
    new_balance = round(float(profile.get("demo_balance_city", 0)) + DEMO_REFERRAL_BONUS, 2)
    await _save_profile(db, referrer_user_id, {"demo_balance_city": new_balance})
    logger.info(f"[demo] +{DEMO_REFERRAL_BONUS} $CITY demo referral bonus → {referrer_user_id}")
    return {"status": "credited", "bonus": DEMO_REFERRAL_BONUS, "demo_balance_city": new_balance}


async def demo_my_businesses(db, user_id: str) -> dict:
    """Return the demo business in the SAME shape as GET /api/my/businesses so
    the existing MyBusinesses UI can render it unchanged. Accrues production
    (via demo_collect) first so the warehouse fills up the same way as real."""
    try:
        await demo_collect(db, user_id)
    except Exception:
        pass
    profile = await get_or_create_demo_profile(db, user_id)
    biz = dict(profile.get("demo_business") or {})
    btype = biz.get("type")
    cfg = _resolve_cfg(btype)
    resources = dict(profile.get("demo_resources") or {})
    produces = cfg.get("produces")
    consumes = cfg.get("consumes") or {}
    durability = float(biz.get("durability", 100))

    items_slots, used = _weighted_storage(resources)
    # Also expose the raw unit counts for the resource inventory UI so the
    # user sees "3 neuro_core" not "60 neuro_core" (their weighted slot count).
    items_units = {k: int(v) for k, v in resources.items() if int(v or 0) > 0}
    tier = int(biz.get("tier", 1) or 1)
    level = int(biz.get("level", 1) or 1)
    per_day_base = float(_get_production(btype, level) or 0)
    capacity = int(_get_storage_capacity(btype, level) or 360)
    consumption_breakdown = _get_consumption_breakdown(btype, level) or dict(consumes)

    # Durability multiplier + fixed demo test buff (mirrors real economy).
    dur_mult = 0.0 if durability <= 0 else (0.8 if durability < 50 else 1.0)
    buff_mult = DEMO_TEST_BUFF_MULTIPLIER
    per_day_effective = per_day_base * dur_mult * buff_mult
    hourly = per_day_effective / 24.0

    # Determine work status: mirror real mode (idle when inputs missing OR
    # warehouse full, stopped when durability hit zero).
    work_status = "working"
    work_status_reason = None
    if durability <= 0:
        work_status = "stopped"
        work_status_reason = "durability_zero"
    elif used >= capacity and capacity > 0:
        work_status = "idle"
        work_status_reason = "storage_full"
    elif consumption_breakdown:
        for res, daily_need in consumption_breakdown.items():
            need_per_tick = (float(daily_need or 0)) / 24.0
            have = float(resources.get(res, 0))
            if need_per_tick > 0 and have < need_per_tick:
                work_status = "idle"
                work_status_reason = "no_resources"
                break

    result_biz = {
        "id": biz.get("id"),
        "business_type": btype,
        "name": biz.get("name"),
        "icon": biz.get("icon"),
        "tier": tier,
        "level": level,
        "durability": durability,
        "x": biz.get("x"), "y": biz.get("y"),
        "tutorial": False,
        "is_demo": True,
        "on_sale": False,
        "config": {
            "name": cfg.get("name") or biz.get("name"),
            "tier": cfg.get("tier", tier),
            "icon": cfg.get("icon") or biz.get("icon"),
            "produces": produces,
            "consumes": consumes,
            "base_cost_ton": cfg.get("base_cost_ton", 0),
        },
        "production": {
            "produces": produces,
            "amount": round(per_day_effective, 2),
            "base_production": round(per_day_base, 2),
            "hourly": round(hourly, 2),
            "consumes": consumes,
            "consumption_breakdown": consumption_breakdown,
            "user_buff_multiplier": buff_mult,
            "tax_rate": 0.0,
        },
        "pending_income": 0,
        "patron": None,
        "storage_info": {
            "capacity": capacity,
            "used": int(min(used, capacity)),
            "items": items_units,
            "items_slots": items_slots,
            "items_used_weighted": int(used),
            "is_full": used >= capacity,
        },
        "work_status": work_status,
        "work_status_reason": work_status_reason,
    }
    return {
        "businesses": [result_biz],
        "summary": {
            "total_businesses": 1,
            "total_pending_income": 0,
            "total_hourly_income": 0,
            "total_daily_income": 0,
            "total_warehouse_capacity": capacity,
            "total_warehouse_used": int(min(used, capacity)),
        },
        "active_resource_buffs": [],
    }



async def demo_upgrade_cost(db, user_id: str) -> dict:
    """Return the full upgrade-cost payload for the demo business (identical
    shape to the real /business/{id}/upgrade-cost route so the UI can reuse
    its modal unchanged)."""
    profile = await get_or_create_demo_profile(db, user_id)
    biz = dict(profile.get("demo_business") or {})
    if not biz:
        return {"can_upgrade": False}
    biz_type = biz.get("type")
    current_level = int(biz.get("level", 1) or 1)
    max_level = 10
    can_upgrade = current_level < max_level
    cost = _calculate_upgrade_cost(biz_type, current_level) if can_upgrade else None
    next_level = current_level + 1 if can_upgrade else None
    resource_meta = None
    if cost and cost.get("resource_type"):
        rt = cost["resource_type"]
        meta = _RES_CFG.get(rt, {})
        resource_meta = {
            "id": rt,
            "name_ru": meta.get("name_ru", rt),
            "name_en": meta.get("name_en", rt),
            "icon": meta.get("icon", "📦"),
        }
    return {
        "can_upgrade": can_upgrade,
        "current_level": current_level,
        "next_level": next_level,
        "cost": cost,
        "resource_meta": resource_meta,
        "current_production": _get_production(biz_type, current_level),
        "next_production": _get_production(biz_type, next_level) if next_level else None,
        "current_storage": _get_storage_capacity(biz_type, current_level),
        "next_storage": _get_storage_capacity(biz_type, next_level) if next_level else None,
        "current_consumption": _get_consumption_breakdown(biz_type, current_level),
        "next_consumption": _get_consumption_breakdown(biz_type, next_level) if next_level else None,
    }


async def demo_upgrade(db, user_id: str) -> dict:
    """Apply a level upgrade to the demo business — spending demo $CITY and,
    if required, a T3 resource from the user's demo inventory. Mirrors the
    real /business/{id}/upgrade cost logic (same table via calculate_upgrade_cost)."""
    profile = await get_or_create_demo_profile(db, user_id)
    biz = dict(profile.get("demo_business") or {})
    if not biz:
        return {"status": "no_business"}
    current_level = int(biz.get("level", 1) or 1)
    if current_level >= 10:
        return {"status": "max_level"}
    biz_type = biz.get("type")
    cost = _calculate_upgrade_cost(biz_type, current_level)
    if not cost:
        return {"status": "no_upgrade_available"}

    city_cost = float(cost.get("city", 0) or 0)
    balance = float(profile.get("demo_balance_city", 0))
    if balance < city_cost:
        return {"status": "insufficient_city", "need_city": city_cost, "have_city": balance}

    resources = dict(profile.get("demo_resources") or {})
    res_type = cost.get("resource_type")
    res_amount = float(cost.get("resource_amount", 0) or 0)
    if res_type and res_amount > 0:
        have = float(resources.get(res_type, 0))
        if have < res_amount:
            return {
                "status": "insufficient_resource",
                "resource": res_type,
                "need": res_amount,
                "have": have,
            }
        resources[res_type] = round(have - res_amount, 4)

    new_level = current_level + 1
    biz["level"] = new_level
    biz["upgraded_at"] = _now_iso()
    new_balance = round(balance - city_cost, 2)
    await _save_profile(db, user_id, {
        "demo_business": biz,
        "demo_balance_city": new_balance,
        "demo_resources": resources,
    })
    return {
        "status": "upgraded",
        "new_level": new_level,
        "paid_city": city_cost,
        "paid_resource": res_type,
        "paid_resource_amount": res_amount,
        "demo_balance_city": new_balance,
        "resources": resources,
    }
