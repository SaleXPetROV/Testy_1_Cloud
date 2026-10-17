"""Изъятие бизнесов за неактивность на рынке.

Пользователь считается АКТИВНЫМ, если за последние 7 дней выполнено хотя бы одно:
  • купил на рынке (P2P, tx_type="market_purchase") не менее 40 ед. товара, ИЛИ
  • продал на рынке не менее 100 ед. товара.

Если НИ ОДНО условие не выполнено — пользователь неактивен, и его бизнесы
изымаются: останавливаются (не производят и не потребляют) и выставляются на
Маркетплейс как бизнес 1-го уровня по рыночной цене клетки от имени GRAM CITY.

Распределение выручки при продаже изъятого бизнеса (см. server.py buyout):
  • бывший нулевой бизнес (level 0) → 100% государству (бывший владелец ничего);
  • бизнес 1+ уровня → 30% бывшему владельцу, остальное государству.

Нулевые бизнесы уже стоят на Маркетплейсе (создаются при застолблении), поэтому
повторно НЕ листятся — только меняется статус и бизнес останавливается.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Set, Tuple

logger = logging.getLogger(__name__)

WINDOW_DAYS = 7
MARKET_BUY_MIN = 40      # куплено ед. за 7 дней
MARKET_SELL_MIN = 100    # продано ед. за 7 дней
SYSTEM_SELLER_ID = "SYSTEM_GRAM_CITY"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _user_identifiers(u: Dict[str, Any]) -> Set[str]:
    ids = {u.get("id"), u.get("wallet_address"), u.get("email"), u.get("username")}
    ids.discard(None)
    ids.discard("")
    return ids


async def compute_active_user_ids(db) -> Tuple[Set[str], Dict[str, float], Dict[str, float]]:
    """Вернуть (множество активных идентификаторов, карта покупок, карта продаж).

    Идентификаторы берутся из транзакций (buyer_id/seller_id) — это могут быть
    user.id или wallet. Активность пользователя проверяется по пересечению его
    идентификаторов с этим множеством.
    """
    cutoff = (_now() - timedelta(days=WINDOW_DAYS)).isoformat()
    buy_map: Dict[str, float] = {}
    sell_map: Dict[str, float] = {}

    buy_pipeline = [
        {"$match": {"tx_type": "market_purchase", "created_at": {"$gte": cutoff}}},
        {"$group": {"_id": "$buyer_id", "units": {"$sum": "$resource_amount"}}},
    ]
    sell_pipeline = [
        {"$match": {"tx_type": "market_purchase", "created_at": {"$gte": cutoff}}},
        {"$group": {"_id": "$seller_id", "units": {"$sum": "$resource_amount"}}},
    ]

    active: Set[str] = set()
    async for row in db.transactions.aggregate(buy_pipeline):
        uid = row.get("_id")
        units = float(row.get("units") or 0)
        if uid:
            buy_map[uid] = units
            if units >= MARKET_BUY_MIN:
                active.add(uid)
    async for row in db.transactions.aggregate(sell_pipeline):
        uid = row.get("_id")
        units = float(row.get("units") or 0)
        if uid:
            sell_map[uid] = units
            if units >= MARKET_SELL_MIN:
                active.add(uid)
    return active, buy_map, sell_map


async def get_activity_stats(db) -> Dict[str, Any]:
    """Статистика для админки: сколько всего/активных/неактивных пользователей."""
    active_ids, _buy, _sell = await compute_active_user_ids(db)
    total = 0
    active = 0
    async for u in db.users.find({}, {"_id": 0, "id": 1, "wallet_address": 1, "email": 1, "username": 1}):
        total += 1
        if _user_identifiers(u) & active_ids:
            active += 1
    return {
        "total": total,
        "active": active,
        "inactive": max(0, total - active),
        "window_days": WINDOW_DAYS,
        "buy_threshold": MARKET_BUY_MIN,
        "sell_threshold": MARKET_SELL_MIN,
    }


async def _map_price_for_business(db, business: Dict[str, Any]) -> float:
    plot = None
    if business.get("plot_id"):
        plot = await db.plots.find_one({"id": business["plot_id"]}, {"_id": 0, "price": 1})
    if not plot and business.get("x") is not None:
        plot = await db.plots.find_one(
            {"x": business.get("x"), "y": business.get("y")}, {"_id": 0, "price": 1}
        )
    price = 0.0
    if plot:
        price = float(plot.get("price") or 0)
    if price <= 0:
        price = float(business.get("zero_map_price") or business.get("purchase_price") or 1.0)
    return round(max(price, 0.01), 6)


async def _notify_former_owner(db, owner: Dict[str, Any], biz_name: str):
    try:
        from core.notify import notify_user
        await notify_user(
            db,
            owner,
            "Бизнес изъят за неактивность",
            f"Ваш бизнес «{biz_name}» изъят за неактивность на рынке и выставлен на "
            f"Маркетплейс. Чтобы оставаться активным, покупайте не менее {MARKET_BUY_MIN} ед. "
            f"или продавайте не менее {MARKET_SELL_MIN} ед. товара за {WINDOW_DAYS} дней.",
            type_key="system",
            priority="warning",
        )
    except Exception as e:
        logger.debug(f"seizure notify failed: {e}")


async def seize_inactive_businesses(db) -> Dict[str, int]:
    """Изъять бизнесы у неактивных пользователей. Идемпотентно."""
    active_ids, _buy, _sell = await compute_active_user_ids(db)

    seized_zero = 0
    seized_regular = 0
    checked = 0

    # Кэш пользователей, чтобы не читать по многу раз.
    user_cache: Dict[str, Dict[str, Any]] = {}

    async def _resolve_owner(owner_key: str):
        if owner_key in user_cache:
            return user_cache[owner_key]
        u = await db.users.find_one(
            {"$or": [{"id": owner_key}, {"wallet_address": owner_key}, {"email": owner_key}]},
            {"_id": 0},
        )
        user_cache[owner_key] = u
        return u

    query = {
        "is_trial": {"$ne": True},
        "tutorial": {"$ne": True},
        "is_seized": {"$ne": True},
        "on_sale": {"$ne": True},
        "status": {"$ne": "on_sale"},
        "paused_reason": {"$ne": "bankruptcy"},
        # НЕ трогаем арендованные бизнесы 0-го уровня — у них своя механика
        # 3-дневной аренды (zero_lease.process_zero_lease). Иначе новый игрок
        # без рыночной активности сразу терял бы только что застолблённый бизнес.
        "is_zero_business": {"$ne": True},
        "level": {"$ne": 0},
    }

    async for biz in db.businesses.find(query):
        checked += 1
        owner_key = biz.get("owner") or biz.get("owner_wallet")
        if not owner_key:
            continue
        owner = await _resolve_owner(owner_key)
        if not owner:
            continue
        if owner.get("is_admin"):
            continue
        # Не изымаем у пользователей, всё ещё проходящих обучение.
        if owner.get("tutorial_active"):
            continue
        # Активен — пропускаем все его бизнесы.
        if _user_identifiers(owner) & active_ids:
            continue

        level = int(biz.get("level", 1) or 0)
        is_zero = bool(biz.get("is_zero_business")) or level == 0
        biz_id = biz.get("id")
        now_iso = _now().isoformat()
        cfg_name = biz.get("business_type", "business")

        base_set = {
            "on_sale": True,
            "status": "on_sale",
            "is_active": False,
            "is_seized": True,
            "seizure_reason": "inactivity",
            "seized_at": now_iso,
            "former_owner": owner_key,
            "former_level": level,
        }

        if is_zero:
            # Уже стоит на Маркетплейсе — повторно не листим, только останавливаем.
            await db.businesses.update_one({"id": biz_id}, {"$set": base_set})
            # Пометим существующий листинг, чтобы выкуп знал причину.
            await db.land_listings.update_many(
                {"business_id": biz_id, "status": "active"},
                {"$set": {
                    "is_seized": True,
                    "seizure_reason": "inactivity",
                    "former_owner_id": owner_key,
                    "former_level": 0,
                }},
            )
            seized_zero += 1
            try:
                import zero_business as _zb
                await _zb.clawback_lease_bonus(db, owner_key, biz)
                await db.businesses.update_one({"id": biz_id}, {"$unset": {"lease_ton_bonus": ""}})
            except Exception as e:
                logger.error(f"seize clawback failed for {biz_id}: {e}")
            await _notify_former_owner(db, owner, cfg_name)
            continue

        # Бизнес 1+ уровня: создаём листинг на Маркетплейсе как 1-й уровень.
        map_price = await _map_price_for_business(db, biz)
        listing_id = str(uuid.uuid4())
        city_id = biz.get("island_id") or biz.get("city_id") or "ton_island"
        listing = {
            "id": listing_id,
            "plot_id": biz.get("plot_id"),
            "city_id": city_id,
            "city_name": "GRAM Island",
            "x": biz.get("x"),
            "y": biz.get("y"),
            "seller_id": SYSTEM_SELLER_ID,
            "seller_username": "GRAM CITY",
            "business_id": biz_id,
            "price": map_price,
            "original_price": map_price,
            "tax_amount": 0.0,
            "seller_receives": map_price,
            "is_seized": True,
            "seizure_reason": "inactivity",
            "former_owner_id": owner_key,
            "former_level": level,
            "business": {
                "type": biz.get("business_type"),
                "level": 1,
                "connections": len(biz.get("connected_businesses", []) or []),
                "xp": 0,
            },
            "status": "active",
            "created_at": now_iso,
        }
        await db.land_listings.insert_one(listing.copy())

        set_doc = dict(base_set)
        set_doc.update({"level": 1, "listing_id": listing_id})
        await db.businesses.update_one({"id": biz_id}, {"$set": set_doc})
        if biz.get("plot_id"):
            await db.plots.update_one(
                {"id": biz["plot_id"]},
                {"$set": {"on_sale": True, "listing_id": listing_id}},
            )
        seized_regular += 1
        await _notify_former_owner(db, owner, cfg_name)

    result = {"seized_zero": seized_zero, "seized_regular": seized_regular, "checked": checked}
    logger.info(f"seize_inactive_businesses: {result}")
    return result
