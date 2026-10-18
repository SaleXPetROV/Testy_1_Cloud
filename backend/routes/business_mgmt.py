"""Business management routes (detail, upgrade, collect income).

Split from server.py — was `# ==================== BUSINESS MANAGEMENT ROUTES ====================`
section. Repair moved separately to `routes/repair.py`.
"""
from datetime import datetime, timedelta, timezone
import logging
import uuid as uuid_mod

from fastapi import APIRouter, HTTPException, Depends

from core.dependencies import get_current_user
from core.models import User
from core.helpers import (
    get_user_identifiers as _helper_gui,
    is_owner,
    get_user_filter,
    resolve_business_config,
    translate_resource_name,
)
from business_config import BUSINESSES, RESOURCE_TYPES, PATRON_BONUSES
from game_systems import (
    BusinessEconomics,
    IncomeCollector,
    PatronageSystem,
    get_production,
    get_consumption_breakdown,
    get_storage_capacity,
    get_user_production_buff,
)

logger = logging.getLogger(__name__)

REPAIR_COST_PER_PCT = {
    # Flat $CITY cost per 1% durability, by business echelon (tier) — independent
    # of level: T1 = 1, T2 = 5, T3 = 20.
    1: 1,
    2: 5,
    3: 20,
}


def create_business_mgmt_router(db):
    router = APIRouter(prefix="/api", tags=["business-mgmt"])

    async def get_user_identifiers(current_user):
        return await _helper_gui(db, current_user)

    @router.get("/business/{business_id}")
    async def get_business_details(business_id: str, current_user: User = Depends(get_current_user)):
        """Get detailed business information (config, production, patron, upgrade, repair cost)."""
        business = await db.businesses.find_one({"id": business_id}, {"_id": 0})
        if not business:
            raise HTTPException(status_code=404, detail="Бизнес не найден")

        # Patron info
        patron_info = None
        patron_bonus = 1.0
        if business.get("patron_id"):
            patron_biz = await db.businesses.find_one({"id": business["patron_id"]}, {"_id": 0})
            if patron_biz:
                patron_type = PatronageSystem.get_patron_type(patron_biz.get("business_type"))
                patron_config = resolve_business_config(patron_biz.get("business_type"))
                patron_info = {
                    "id": patron_biz["id"],
                    "owner": patron_biz.get("owner"),
                    "type": patron_type,
                    "name": patron_config.get("name", {}),
                    "icon": patron_config.get("icon", ""),
                    "level": patron_biz.get("level", 1),
                    "bonus_type": PATRON_BONUSES.get(patron_type, {}).get("type"),
                }
                patron_bonus = PatronageSystem.get_patron_bonus_multiplier(
                    patron_type, patron_biz.get("level", 1), "income"
                )

        # Active resource-buff multiplier from owner (+8% from neuro_core, etc.)
        owner_user = await db.users.find_one({"$or": [
            {"id": business.get("owner")},
            {"wallet_address": business.get("owner")},
            {"telegram_id": business.get("owner")},
            {"username": business.get("owner")},
            {"email": business.get("owner")},
        ]}, {"active_resource_buffs": 1, "_id": 0})
        user_buff_mult = get_user_production_buff(owner_user) if owner_user else 1.0

        # Production & pending income
        biz_type = business.get("business_type", "")
        biz_level = business.get("level", 1)
        production = BusinessEconomics.calculate_effective_production(business, patron_bonus, user_buff_mult)
        production["base_production"] = get_production(biz_type, biz_level)
        production["consumption_breakdown"] = get_consumption_breakdown(biz_type, biz_level)
        pending = IncomeCollector.calculate_pending_income(business, patron_bonus=patron_bonus, user_buff_multiplier=user_buff_mult)

        # Upgrade & repair
        can_upgrade, upgrade_cost = BusinessEconomics.can_upgrade(business)
        cur_dur = business.get("durability", 100)
        missing = 100 - cur_dur
        cfg = resolve_business_config(biz_type)
        tier = cfg.get("tier", 1)
        from business_config import repair_cost_per_pct_city as _rcp
        cost_per_pct = _rcp(biz_type, tier, biz_level)                       # admin value or tier default
        base_cost_city = cost_per_pct * missing  # keep precise float; frontend rounds for display

        # Collect applied repair discount buffs for transparency in UI.
        applied_repair_buffs = []
        repair_mult = 1.0
        # 1) Patron/contract buff (per-business): Ремонтный допуск (-25%)
        try:
            from business_config import TIER3_BUFFS as _T3
            from game_systems import resolve_business_buff as _rbb
            _contract = await db.contracts.find_one(
                {"vassal_business_id": business.get("id"), "status": "active"}, {"_id": 0}
            )
            _patron_doc = None
            if business.get("patron_id"):
                _patron_doc = await db.businesses.find_one({"id": business["patron_id"]}, {"_id": 0})
            _per_biz_buff = _rbb(business, _contract, _patron_doc)
            if _per_biz_buff and _per_biz_buff.get("effect", {}).get("type") == "repair_cost_multiplier":
                v = float(_per_biz_buff["effect"].get("value", 1.0))
                repair_mult *= v
                applied_repair_buffs.append({
                    "id": _per_biz_buff.get("id"),
                    "name": _per_biz_buff.get("name"),
                    "icon": _per_biz_buff.get("icon"),
                    "percent": round((1 - v) * 100, 1),
                    "source": "patron",
                })
        except Exception:
            pass
        # 2) T3 resource buff on owner: Золотой стандарт (-20%)
        try:
            if owner_user:
                from datetime import datetime as _dt, timezone as _tz
                now_u = _dt.now(_tz.utc)
                for rb in (owner_user.get("active_resource_buffs") or []):
                    if rb.get("effect_type") != "repair_cost_multiplier":
                        continue
                    exp_raw = rb.get("expires_at")
                    if exp_raw:
                        try:
                            exp_dt = _dt.fromisoformat(str(exp_raw).replace('Z', '+00:00'))
                            if exp_dt <= now_u:
                                continue
                        except (ValueError, TypeError):
                            continue
                    v = float(rb.get("effect_value", 1.0))
                    repair_mult *= v
                    applied_repair_buffs.append({
                        "id": rb.get("resource_id"),
                        "name": rb.get("buff_name"),
                        "icon": rb.get("buff_icon"),
                        "percent": round((1 - v) * 100, 1),
                        "source": "resource",
                    })
        except Exception:
            pass
        # 3) Tech Umbrella contract (-30%)
        try:
            _ta_contract = await db.contracts.find_one(
                {"vassal_business_id": business.get("id"), "status": "active", "type": "tech_umbrella"},
                {"_id": 0},
            )
            if _ta_contract:
                repair_mult *= 0.70
                applied_repair_buffs.append({
                    "id": "tech_umbrella",
                    "name": "Технический зонтик",
                    "icon": "🛡️",
                    "percent": 30.0,
                    "source": "contract",
                })
        except Exception:
            pass

        final_cost_city = round(base_cost_city * repair_mult, 2)
        repair_cost = {
            "cost_city": final_cost_city,
            "base_cost_city": round(base_cost_city, 2),
            "cost_per_pct": cost_per_pct,
            "missing_pct": round(missing, 1),
            "cost_ton": round(final_cost_city / 1000, 4),
            "discount_percent": round((1 - repair_mult) * 100, 1),
            "applied_buffs": applied_repair_buffs,
        }

        config = resolve_business_config(business.get("business_type"))

        return {
            "business": {
                **business,
                "config": {
                    "name": config.get("name"),
                    "tier": config.get("tier"),
                    "icon": config.get("icon"),
                    "produces": config.get("produces"),
                    "consumes": config.get("consumes", []),
                    "is_patron": config.get("is_patron", False),
                },
            },
            "patron": patron_info,
            "production": production,
            "pending_income": pending,
            "upgrade": {
                "can_upgrade": can_upgrade,
                "next_level": business.get("level", 1) + 1 if can_upgrade else None,
                "cost": upgrade_cost,
            },
            "repair": repair_cost,
        }

    @router.post("/business/{business_id}/upgrade")
    async def upgrade_business(business_id: str, current_user: User = Depends(get_current_user)):
        """Upgrade business to next level."""
        business = await db.businesses.find_one({"id": business_id}, {"_id": 0})
        from rental import assert_not_rented as _anr
        _anr(business)                     # a rented business can't be upgraded
        if not business:
            raise HTTPException(status_code=404, detail="Бизнес не найден")

        ui = await get_user_identifiers(current_user)
        if not ui["user"] or not is_owner(business, ui["ids"]):
            raise HTTPException(status_code=403, detail="Это не ваш бизнес")
        user = ui["user"]

        # ── Level-0 (застолблённый) → Level-1: paid strictly in $CITY from the
        # REAL balance (bonus forbidden); removes the auto market lot; marks the
        # user as graduated (no more level-0 claims ever). ──
        if int(business.get("level", 1) or 0) == 0:
            _cfg = BUSINESSES.get(business.get("business_type"), {})
            _map_price_ton = float(
                business.get("zero_map_price")
                or _cfg.get("base_cost_ton")
                or _cfg.get("price_ton")
                or 0
            )
            cost_city = round(_map_price_ton * 1000.0, 2)
            real_ton = float(user.get("balance_ton", 0) or 0)
            if real_ton * 1000.0 + 1e-6 < cost_city:
                raise HTTPException(status_code=400, detail={
                    "code": "zero_upgrade_need_real",
                    "message": "Для перехода 0→1 нужен реальный баланс $CITY (бонусный не принимается)",
                    "need_city": cost_city,
                    "have_city": round(real_ton * 1000.0, 2),
                })
            # The upgrade does not touch the shift: a running shift simply continues
            # at level 1, and an idle business stays idle until the player starts one.
            _res = await db.businesses.find_one_and_update(
                {"id": business_id, "level": 0},
                {"$set": {"level": 1, "on_sale": False},
                 "$unset": {"is_zero_business": "", "zero_map_price": "", "zero_listing_id": "", "listing_id": "", "expires_at": "", "zero_lease_warned": "", "lease_ton_bonus": ""}},
            )
            if not _res:
                raise HTTPException(status_code=409, detail="Бизнес больше недоступен для улучшения")
            await db.users.update_one(get_user_filter(user), {"$inc": {"balance_ton": -(cost_city / 1000.0)}})
            await db.users.update_one(get_user_filter(user), {"$set": {"has_graduated_zero": True}})
            _lid = business.get("zero_listing_id")
            if _lid:
                await db.land_listings.delete_one({"id": _lid})
            await db.land_listings.delete_many({"business_id": business_id, "is_zero_business": True})
            await db.plots.update_one(
                {"id": business.get("plot_id")},
                {"$unset": {"on_sale": "", "listing_id": ""}, "$set": {"business.level": 1}},
            )
            await db.admin_stats.update_one(
                {"type": "treasury"},
                {"$inc": {"upgrade_income": cost_city, "total_tax": cost_city * 0.1}},
                upsert=True,
            )
            try:
                await db.businesses.update_one(
                    {"id": business_id},
                    {"$set": {"storage.capacity": get_storage_capacity(business.get("business_type"), 1)}},
                )
            except Exception:
                pass
            tx = {
                "id": str(uuid_mod.uuid4()),
                "user_id": user.get("id"),
                "type": "business_upgrade",
                "amount": -(cost_city / 1000.0),
                "amount_city": -cost_city,
                "details": {
                    "business_id": business_id,
                    "business_type": business.get("business_type"),
                    "new_level": 1,
                    "cost_city": cost_city,
                    "zero_to_one": True,
                },
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            await db.transactions.insert_one(tx.copy())
            try:
                from routes.partner_programs import check_partner_conditions
                await check_partner_conditions(db, user.get("id"))
            except Exception as _e:
                logger.debug(f"check_partner_conditions (upgrade 0->1) failed: {_e}")
            try:
                import quests as _quests
                _quests.fire(user, "upgrade", 1)
            except Exception:
                pass
            return {
                "status": "upgraded",
                "new_level": 1,
                "shift_ends_at": business.get("shift_ends_at"),
                "cost_paid": {"city": cost_city},
                "new_balance": (real_ton - cost_city / 1000.0) * 1000,
            }

        can_upgrade, cost = BusinessEconomics.can_upgrade(business)
        if not can_upgrade:
            raise HTTPException(status_code=400, detail="Достигнут максимальный уровень")

        _up_bonus = float(user.get("bonus_balance", 0) or 0)
        _up_real = float(user.get("balance_ton", 0) or 0)
        if (_up_bonus + _up_real) * 1000 < cost.get("city", cost.get("ton", 0)):
            raise HTTPException(status_code=400, detail="Недостаточно $CITY для улучшения")

        if cost.get("resource_type") and cost.get("resource_amount", 0) > 0:
            current_resource = user.get("resources", {}).get(cost["resource_type"], 0)
            if current_resource < cost["resource_amount"]:
                res_name = translate_resource_name(cost["resource_type"])
                # Structured detail so the frontend can localize into the user's
                # selected language (resource name + need/have).
                raise HTTPException(
                    status_code=400,
                    detail={
                        "code": "insufficient_resource",
                        "resource": cost["resource_type"],
                        "need": cost["resource_amount"],
                        "have": int(current_resource),
                        "message": f"Недостаточно {res_name}: нужно {cost['resource_amount']}, есть {int(current_resource)}",
                    },
                )

        upgrade_data = BusinessEconomics.upgrade_business(business)
        await db.businesses.update_one({"id": business_id}, {"$set": upgrade_data})

        upgrade_city_cost = cost.get("city", cost.get("ton", 0))
        upgrade_ton_cost = upgrade_city_cost / 1000.0
        # Bonus funds first, then real balance.
        _up_from_bonus = min(_up_bonus, upgrade_ton_cost)
        _up_from_real = upgrade_ton_cost - _up_from_bonus
        await db.users.update_one(
            get_user_filter(user), {"$inc": {"bonus_balance": -_up_from_bonus, "balance_ton": -_up_from_real}}
        )

        if cost.get("resource_type") and cost.get("resource_amount", 0) > 0:
            await db.users.update_one(
                get_user_filter(user),
                {"$inc": {f"resources.{cost['resource_type']}": -cost["resource_amount"]}},
            )

        await db.admin_stats.update_one(
            {"type": "treasury"},
            {"$inc": {"upgrade_income": upgrade_city_cost, "total_tax": upgrade_city_cost * 0.1}},
            upsert=True,
        )

        logger.info(
            f"Business {business_id} upgraded to level {upgrade_data['level']} by {user.get('username')}"
        )

        tx = {
            "id": str(uuid_mod.uuid4()),
            "user_id": user.get("id"),
            "type": "business_upgrade",
            "amount": -upgrade_ton_cost,
            "amount_city": -upgrade_city_cost,
            "details": {
                "business_id": business_id,
                "business_type": business.get("business_type"),
                "new_level": upgrade_data["level"],
                "cost_city": upgrade_city_cost,
            },
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.transactions.insert_one(tx.copy())

        try:
            from routes.partner_programs import check_partner_conditions
            await check_partner_conditions(db, user.get("id"))
        except Exception as _e:
            logger.debug(f"check_partner_conditions (upgrade) failed: {_e}")

        try:
            import quests as _quests
            _quests.fire(user, "upgrade", 1)
        except Exception:
            pass
        return {
            "status": "upgraded",
            "new_level": upgrade_data["level"],
            "new_capacity": upgrade_data.get("storage.capacity", 0),
            "cost_paid": cost,
            "new_balance": (user.get("balance_ton", 0) - upgrade_ton_cost) * 1000,
        }

    @router.get("/business/{business_id}/upgrade-cost")
    async def get_upgrade_cost(business_id: str, current_user: User = Depends(get_current_user)):
        """Get upgrade cost details for a business (production/storage before & after)."""
        business = await db.businesses.find_one({"id": business_id}, {"_id": 0})
        if not business:
            raise HTTPException(status_code=404, detail="Бизнес не найден")

        # Level-0 (застолблённый) → Level-1 special case: cost = current map price
        # in $CITY (paid from real balance). Normal cost table starts at level 2.
        if int(business.get("level", 1) or 0) == 0:
            _cfg = BUSINESSES.get(business.get("business_type"), {})
            _map_ton = float(business.get("zero_map_price") or _cfg.get("base_cost_ton") or _cfg.get("price_ton") or 0)
            _bt0 = business.get("business_type", "")
            return {
                "can_upgrade": True,
                "current_level": 0,
                "next_level": 1,
                "cost": {"city": round(_map_ton * 1000.0, 2)},
                "resource_meta": None,
                "current_production": get_production(_bt0, 1),
                "next_production": get_production(_bt0, 1),
                "current_storage": get_storage_capacity(_bt0, 1),
                "next_storage": get_storage_capacity(_bt0, 1),
                "current_consumption": get_consumption_breakdown(_bt0, 1),
                "next_consumption": get_consumption_breakdown(_bt0, 1),
                "zero_to_one": True,
            }

        can_upgrade, cost = BusinessEconomics.can_upgrade(business)
        current_level = business.get("level", 1)
        biz_type = business.get("business_type", "")
        next_level = current_level + 1 if can_upgrade else None

        current_production = get_production(biz_type, current_level)
        next_production = get_production(biz_type, next_level) if next_level else None
        current_storage = get_storage_capacity(biz_type, current_level)
        next_storage = get_storage_capacity(biz_type, next_level) if next_level else None

        resource_meta = None
        if cost and cost.get("resource_type"):
            rt = cost["resource_type"]
            meta = RESOURCE_TYPES.get(rt, {})
            resource_meta = {
                "id": rt,
                "name_ru": meta.get("name_ru", rt),
                "name_en": meta.get("name_en", rt),
                "icon": meta.get("icon", "📦"),
            }

        current_consumption = get_consumption_breakdown(biz_type, current_level)
        next_consumption = get_consumption_breakdown(biz_type, next_level) if next_level else None

        return {
            "can_upgrade": can_upgrade,
            "current_level": current_level,
            "next_level": next_level,
            "cost": cost,
            "resource_meta": resource_meta,
            "current_production": current_production,
            "next_production": next_production,
            "current_storage": current_storage,
            "next_storage": next_storage,
            "current_consumption": current_consumption,
            "next_consumption": next_consumption,
        }

    @router.post("/business/{business_id}/collect")
    async def collect_business_income(business_id: str, current_user: User = Depends(get_current_user)):
        """Collect accumulated income from business."""
        business = await db.businesses.find_one({"id": business_id}, {"_id": 0})
        if not business:
            raise HTTPException(status_code=404, detail="Бизнес не найден")

        ui = await get_user_identifiers(current_user)
        if not ui["user"] or not is_owner(business, ui["ids"]):
            raise HTTPException(status_code=403, detail="Это не ваш бизнес")

        patron_wallet = None
        if business.get("patron_id"):
            patron_biz = await db.businesses.find_one({"id": business["patron_id"]}, {"_id": 0})
            if patron_biz:
                patron_wallet = patron_biz.get("owner")

        collection = IncomeCollector.collect_income(business, patron_wallet)

        if collection.get("halted"):
            raise HTTPException(status_code=400, detail="Производство остановлено - нужен ремонт")

        if collection["collected"] <= 0:
            return {"status": "nothing_to_collect", "hours": collection["hours"]}

        user_filter = get_user_filter(ui["user"])
        await db.users.update_one(
            user_filter,
            {"$inc": {
                "balance_ton": collection["player_receives"],
                "total_income": collection["player_receives"],
            }},
        )

        if patron_wallet and collection["patron_receives"] > 0:
            await db.users.update_one(
                {"wallet_address": patron_wallet},
                {"$inc": {
                    "balance_ton": collection["patron_receives"],
                    "total_income": collection["patron_receives"],
                }},
            )

        await db.admin_stats.update_one(
            {"type": "treasury"},
            {"$inc": {
                "business_tax": collection["treasury_receives"],
                "total_tax": collection["treasury_receives"],
            }},
            upsert=True,
        )

        await db.businesses.update_one(
            {"id": business_id},
            {"$set": {"last_collection": datetime.now(timezone.utc).isoformat()}},
        )

        logger.info(f"Collected {collection['collected']} TON from business {business_id}")

        try:
            import quests as _quests
            _quests.fire(ui["user"], "collect", 1)
        except Exception:
            pass
        return {
            "status": "collected",
            "gross_income": collection["collected"],
            "player_receives": collection["player_receives"],
            "treasury_tax": collection["treasury_receives"],
            "patron_tax": collection["patron_receives"],
            "hours_accumulated": collection["hours"],
        }

    return router
