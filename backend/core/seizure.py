"""Forced-seizure engine (GRAM CITY repossession).

A business is repossessed and force-listed on the marketplace when either:
  • its durability sat at 0 for >= 7 days (reason='durability_zero'), or
  • a collateral credit defaulted past its grace period (reason='credit_default').

The former owner CANNOT delist a seized business (support only). On purchase the
business durability is fully restored and the seizure flags cleared. Proceeds go
to the former owner's REAL balance minus tax; for credit defaults the outstanding
debt is repaid first and only the remainder reaches the owner.

Pricing is FROZEN at seizure time so later price-balance changes never move it:
    price(TON) = base_cost_ton
               + Σ(upgrade.city / 1000)                      # $CITY → TON
               + Σ(upgrade.resource_qty × resource_price_ton)  # admin resource price
for every upgrade from level 2 up to the current level.
"""
import uuid
import logging
from datetime import datetime, timezone, timedelta

from business_config import (
    BUSINESSES,
    UPGRADE_COSTS_TABLE,
    RESOURCE_TYPES,
    BUSINESS_KEY_MAP,
)

logger = logging.getLogger(__name__)

SEIZURE_SYSTEM_SELLER = "GRAM CITY"
ZERO_DURABILITY_SEIZE_DAYS = 7
CREDIT_DEFAULT_GRACE_DAYS = 7  # after next_payment_due before we seize collateral


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(v):
    if not v:
        return None
    try:
        s = str(v).replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


async def _resource_price_ton(db, resource_type: str) -> float:
    """Current admin/market resource price converted to TON. Resource prices in
    RESOURCE_TYPES.base_price and the market_prices doc are denominated in $CITY
    (1 TON = 1000 $CITY), so divide by 1000."""
    meta = RESOURCE_TYPES.get(resource_type, {}) or {}
    base_city = float(meta.get("base_price", 0.01) or 0.01)
    doc = await db.admin_settings.find_one({"type": "market_prices"}, {"_id": 0, "prices": 1})
    if not doc:
        doc = await db.market_prices.find_one({}, {"_id": 0, "prices": 1})
    stored = (doc or {}).get("prices", {}) if doc else {}
    price_city = float(stored.get(resource_type, base_city) or base_city)
    return price_city / 1000.0


async def compute_seizure_price(db, business: dict) -> float:
    """Frozen list price (TON) = base build cost + all upgrade costs (city +
    resources at current admin prices) up to the current level."""
    btype = business.get("business_type")
    mapped = BUSINESS_KEY_MAP.get(btype, btype)
    cfg = BUSINESSES.get(mapped) or BUSINESSES.get(btype) or {}
    total = float(cfg.get("base_cost_ton", 5) or 5)

    level = int(business.get("level", 1) or 1)
    costs = UPGRADE_COSTS_TABLE.get(mapped) or UPGRADE_COSTS_TABLE.get(btype) or {}
    for lvl in range(2, level + 1):
        step = costs.get(lvl)
        if not step:
            continue
        total += float(step.get("city", 0) or 0) / 1000.0  # $CITY → TON
        res = step.get("resource")
        qty = float(step.get("qty", 0) or 0)
        if res and qty > 0:
            total += qty * await _resource_price_ton(db, res)
    return round(total, 6)


def _business_summary(business: dict) -> dict:
    mapped = BUSINESS_KEY_MAP.get(business.get("business_type"), business.get("business_type"))
    cfg = BUSINESSES.get(mapped) or BUSINESSES.get(business.get("business_type")) or {}
    return {
        "type": business.get("business_type"),
        "level": business.get("level", 1),
        "durability": business.get("durability", 0),
        "xp": business.get("xp", 0),
        "name": cfg.get("name", {}),
        "icon": cfg.get("icon", ""),
        "tier": cfg.get("tier", 1),
        "produces": cfg.get("produces", ""),
    }


async def seize_business(db, business: dict, reason: str) -> dict:
    """Repossess a business and force-list it under GRAM CITY. Idempotent."""
    business_id = business.get("id")
    if not business_id or business.get("is_seized"):
        return None
    # Бизнесы 0-го уровня (арендованные) НЕ изымаются со статусом «изъят».
    # Их жизненный цикл — только аренда: по истечении срока они удаляются
    # отовсюду (см. zero_lease._expire_zero_business), а не выставляются как «изъятые».
    if business.get("is_zero_business") or int(business.get("level", 1) or 0) == 0:
        return None

    plot = await db.plots.find_one({"id": business.get("plot_id")}, {"_id": 0})
    if not plot:
        plot = await db.plots.find_one({"business_id": business_id}, {"_id": 0})

    price = await compute_seizure_price(db, business)
    former_owner = business.get("owner")
    former_owner_username = business.get("owner_username")
    city_id = (plot or {}).get("city_id") or (plot or {}).get("island_id") \
        or business.get("city_id") or business.get("island_id") or "ton_island"

    listing = {
        "id": str(uuid.uuid4()),
        "plot_id": (plot or {}).get("id") or business.get("plot_id"),
        "business_id": business_id,
        "city_id": city_id,
        "city_name": "GRAM Island",
        "x": (plot or {}).get("x", business.get("plot_x")),
        "y": (plot or {}).get("y", business.get("plot_y")),
        # Seller is the system, NOT the former owner.
        "seller_id": SEIZURE_SYSTEM_SELLER,
        "seller_user_id": SEIZURE_SYSTEM_SELLER,
        "seller_username": SEIZURE_SYSTEM_SELLER,
        "price": price,
        "business": _business_summary(business),
        "original_plot_price": (plot or {}).get("price", 0),
        # Seizure metadata
        "is_seized": True,
        "seizure_reason": reason,
        "seized_at": _now_iso(),
        "former_owner_id": former_owner,
        "former_owner_username": former_owner_username,
        "status": "active",
        "created_at": _now_iso(),
    }
    await db.land_listings.insert_one(listing.copy())

    await db.businesses.update_one({"id": business_id}, {"$set": {
        "is_seized": True,
        "seizure_reason": reason,
        "seized_at": listing["seized_at"],
        "seizure_price": price,
        "former_owner": former_owner,
        "on_sale": True,
        "listing_id": listing["id"],
        "status": "on_sale",
        "work_status": "seized",
        "is_active": False,
    }})

    if plot:
        await db.plots.update_one({"id": plot["id"]},
                                  {"$set": {"on_sale": True, "listing_id": listing["id"]}})

    # Уведомляем бывшего владельца о реальном изъятии с указанием причины
    # (только credit_default / durability_zero — задача пользователя).
    try:
        await _notify_seizure(db, former_owner, business, reason, price)
    except Exception as e:
        logger.error(f"seize_business notify failed for {business_id}: {e}")

    logger.info(f"⚖️ SEIZED business {business_id} ({reason}) → listed under GRAM CITY at {price} TON")
    return listing


def _seized_biz_name(business: dict, lang: str) -> str:
    mapped = BUSINESS_KEY_MAP.get(business.get("business_type"), business.get("business_type"))
    cfg = BUSINESSES.get(mapped) or BUSINESSES.get(business.get("business_type")) or {}
    names = cfg.get("name", {}) or {}
    if isinstance(names, dict):
        return names.get(lang) or names.get("en") or names.get("ru") or (business.get("business_type") or "business")
    return str(names or business.get("business_type") or "business")


async def _notify_seizure(db, former_owner, business: dict, reason: str, price: float) -> None:
    """Локализованное уведомление бывшему владельцу о причине изъятия."""
    if not former_owner or reason not in ("credit_default", "durability_zero"):
        return
    user = await db.users.find_one(
        {"$or": [{"id": former_owner}, {"wallet_address": former_owner}, {"email": former_owner}]},
        {"_id": 0},
    )
    if not user:
        return
    from core.notify import notify_user
    from core.notif_i18n import user_lang
    lang = user_lang(user)
    key = "business_seized_credit" if reason == "credit_default" else "business_seized_durability"
    await notify_user(
        db, user, title=None, message=None,
        type_key="business_seized", priority="high",
        i18n_key=key,
        i18n_vars={"biz": _seized_biz_name(business, lang), "price": round(float(price or 0), 4)},
    )


async def process_seizures(db) -> dict:
    """Daily job: seize businesses dead 7d + collateral of defaulted credits."""
    seized_durability = 0
    seized_credit = 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=ZERO_DURABILITY_SEIZE_DAYS)

    # 1) Durability sat at 0 for >= 7 days
    async for biz in db.businesses.find({
        "is_seized": {"$ne": True},
        "zero_durability_since": {"$ne": None},
        # Бизнесы 0-го уровня (арендованные) НЕ изымаются со статусом «изъят»:
        # у них своя механика аренды — по истечении они просто удаляются отовсюду.
        "is_zero_business": {"$ne": True},
        "level": {"$ne": 0},
    }, {"_id": 0}):
        since = _parse_iso(biz.get("zero_durability_since"))
        if since and since <= cutoff and float(biz.get("durability", 0) or 0) <= 0:
            if await seize_business(db, biz, "durability_zero"):
                seized_durability += 1

    # 2) Credit default (overdue past grace period)
    grace_cutoff = datetime.now(timezone.utc) - timedelta(days=CREDIT_DEFAULT_GRACE_DAYS)
    async for credit in db.credits.find({
        "status": {"$in": ["active", "overdue"]},
        "collateral_business_id": {"$ne": None},
    }, {"_id": 0}):
        due = _parse_iso(credit.get("next_payment_due"))
        if not due or due > grace_cutoff:
            continue
        if float(credit.get("remaining", 0) or 0) <= 0:
            continue
        biz = await db.businesses.find_one(
            {"id": credit["collateral_business_id"], "is_seized": {"$ne": True}}, {"_id": 0})
        if biz:
            listing = await seize_business(db, biz, "credit_default")
            if listing:
                await db.land_listings.update_one(
                    {"id": listing["id"]},
                    {"$set": {"credit_id": credit.get("id"),
                              "credit_remaining_at_seizure": float(credit.get("remaining", 0) or 0)}})
                await db.credits.update_one({"id": credit.get("id")},
                                            {"$set": {"status": "defaulted",
                                                      "collateral_seized": True,
                                                      "seized_listing_id": listing["id"]}})
                seized_credit += 1

    if seized_durability or seized_credit:
        logger.info(f"process_seizures: durability={seized_durability}, credit_default={seized_credit}")
    return {"seized_durability": seized_durability, "seized_credit": seized_credit}


# ─────────────────────── admin / support management ────────────────────────

async def list_seized(db) -> list:
    """Admin «Кредиты → Изъятые».

    Показываем ТОЛЬКО бизнесы, реально изъятые государством по двум причинам:
      • неуплата кредита (credit_default);
      • прочность держалась на 0 в течение 7 дней (durability_zero).

    Бизнесы 0-го уровня (арендованные) сюда НЕ попадают — у них своя механика
    аренды, они лишь стоят на Маркетплейсе, но не считаются «изъятыми».
    Изъятия за неактивность (inactivity) и любые иные причины здесь тоже не
    отображаются. Если бизнес вернули владельцу (return_seized → status
    'cancelled' / returned_to_owner), он тоже исчезает из списка."""
    out = []
    async for lst in db.land_listings.find(
        {
            "is_seized": True,
            "seizure_reason": {"$in": ["credit_default", "durability_zero"]},
            "is_zero_business": {"$ne": True},
            "returned_to_owner": {"$ne": True},
            "status": {"$ne": "cancelled"},
        },
        {"_id": 0},
    ).sort("seized_at", -1):
        # Двойная страховка: пропускаем листинги, чей бизнес по факту нулевого
        # уровня (на случай устаревших данных без флага is_zero_business).
        _b = lst.get("business") or {}
        try:
            _lvl = int(_b.get("level", 1)) if _b.get("level", 1) is not None else 1
        except (TypeError, ValueError):
            _lvl = 1
        if _b.get("is_zero_business") or _lvl == 0:
            continue
        biz = await db.businesses.find_one({"id": lst.get("business_id")}, {"_id": 0}) or {}
        out.append({
            "listing_id": lst.get("id"),
            "business_id": lst.get("business_id"),
            "business": lst.get("business") or _business_summary(biz),
            "business_full": {k: v for k, v in biz.items()
                              if k not in ("_id",)} if biz else None,
            "seizure_reason": lst.get("seizure_reason"),
            "seized_at": lst.get("seized_at"),
            "price": lst.get("price"),
            "status": lst.get("status"),
            "former_owner_id": lst.get("former_owner_id"),
            "former_owner_username": lst.get("former_owner_username"),
            "buyer_id": lst.get("buyer_id"),
            "buyer_username": lst.get("buyer_username"),
            "sold_at": lst.get("sold_at"),
            "credit_id": lst.get("credit_id"),
            "x": lst.get("x"), "y": lst.get("y"),
            "plot_id": lst.get("plot_id"),
            "sold": lst.get("status") == "sold",
        })
    return out


async def set_seized_price(db, listing_id: str, price: float) -> dict:
    """Admin/support edits the resale price of a not-yet-sold seized business."""
    lst = await db.land_listings.find_one({"id": listing_id, "is_seized": True}, {"_id": 0})
    if not lst:
        return {"ok": False, "reason": "not_found"}
    if lst.get("status") != "active":
        return {"ok": False, "reason": "already_sold"}
    price = round(float(price), 6)
    if price <= 0:
        return {"ok": False, "reason": "invalid_price"}
    await db.land_listings.update_one({"id": listing_id}, {"$set": {"price": price}})
    await db.businesses.update_one({"id": lst.get("business_id")}, {"$set": {"seizure_price": price}})
    return {"ok": True, "price": price}


async def return_seized(db, listing_id: str) -> dict:
    """Cancel a seized listing and return the business to its former owner
    (only if not sold). Clears all seizure flags and restores durability."""
    lst = await db.land_listings.find_one({"id": listing_id, "is_seized": True}, {"_id": 0})
    if not lst:
        return {"ok": False, "reason": "not_found"}
    if lst.get("status") != "active":
        return {"ok": False, "reason": "already_sold"}
    business_id = lst.get("business_id")
    former = lst.get("former_owner_id")
    await db.land_listings.update_one({"id": listing_id},
                                      {"$set": {"status": "cancelled",
                                                "cancelled_at": _now_iso(),
                                                "returned_to_owner": True}})
    await db.businesses.update_one({"id": business_id}, {
        "$set": {"owner": former, "durability": 100, "work_status": "idle",
                 "work_status_reason": None, "is_active": True, "status": "active",
                 "is_seized": False, "zero_durability_since": None},
        "$unset": {"on_sale": "", "listing_id": "", "seizure_reason": "",
                   "seized_at": "", "seizure_price": "", "former_owner": ""},
    })
    plot_id = lst.get("plot_id")
    if plot_id:
        await db.plots.update_one({"id": plot_id}, {"$unset": {"on_sale": "", "listing_id": ""}})
    return {"ok": True, "business_id": business_id, "returned_to": former}
