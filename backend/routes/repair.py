"""Business repair router.

Endpoint:
  POST /api/business/{business_id}/repair — restore durability to 100%

Pricing: $CITY per 1% missing durability, table -20% reduced from baseline:
  Tier1 L1: 4, Tier1 L10: 88
  Tier2 L1: 20, Tier2 L10: 440
  Tier3 L1: 96, Tier3 L10: 2080

Active modifiers (stacking multiplicatively):
  • Patron buff «Ремонтный допуск» (-25%)
  • T3 resource buff Gold Bill (-20%)
  • Tech Umbrella alliance contract (-30%)

Split out of server.py (was ~1856-1971). Wrapped in try/except so repair
NEVER returns HTML 500 — always JSON 4xx/5xx — fixing the
'Unexpected token I, Internal S...' frontend bug.
"""
from datetime import datetime, timezone
import logging
import uuid as uuid_mod

from fastapi import APIRouter, HTTPException, Depends

from core.dependencies import get_current_user
from core.models import User
from core.helpers import get_user_identifiers as _helper_gui, is_owner, get_user_filter
from business_config import BUSINESSES, TIER3_BUFFS, BUSINESS_KEY_MAP

logger = logging.getLogger(__name__)

# $CITY cost per 1% durability restored (already -20% from v3 baseline)
REPAIR_COST_PER_PCT = {
    # Flat $CITY cost per 1% durability, by business echelon (tier) — independent
    # of level: T1 = 1, T2 = 5, T3 = 20.
    1: 1,
    2: 5,
    3: 20,
}


def _resolve_business_config(business_type: str) -> dict:
    cfg = BUSINESSES.get(business_type)
    if cfg:
        return cfg
    mapped = BUSINESS_KEY_MAP.get(business_type, business_type)
    return BUSINESSES.get(mapped, {})


def create_repair_router(db):
    """Factory: build the repair router bound to the given Motor db."""
    router = APIRouter(prefix="/api", tags=["business-repair"])

    async def get_user_identifiers(current_user):
        return await _helper_gui(db, current_user)

    async def get_user_patron_buff(user_ids: set, target_business: dict = None) -> dict:
        """Return TIER3_BUFFS entry if any of user's businesses has an active
        patron giving a buff. If `target_business` is provided, prefer the
        buff from that specific business's active contract.
        Empty dict otherwise.
        """
        if not user_ids:
            return {}
        # Lazy import to avoid circular at module load
        from game_systems import resolve_business_buff

        # Priority 1: the specific business under repair
        if target_business is not None and target_business.get("id"):
            contract = await db.contracts.find_one(
                {"vassal_business_id": target_business["id"], "status": "active"},
                {"_id": 0},
            )
            patron_doc = None
            if target_business.get("patron_id"):
                patron_doc = await db.businesses.find_one(
                    {"id": target_business["patron_id"]}, {"_id": 0}
                )
            buff = resolve_business_buff(target_business, contract, patron_doc)
            if buff:
                return buff

        id_list = list(user_ids)
        # Fallback: any owned business with patron_buff/contract_buff
        async for biz in db.businesses.find({"owner": {"$in": id_list}}, {"_id": 0}):
            contract = await db.contracts.find_one(
                {"vassal_business_id": biz.get("id"), "status": "active"},
                {"_id": 0},
            )
            patron_doc = None
            if biz.get("patron_id"):
                patron_doc = await db.businesses.find_one(
                    {"id": biz["patron_id"]}, {"_id": 0}
                )
            buff = resolve_business_buff(biz, contract, patron_doc)
            if buff:
                return buff
        return {}

    @router.post("/business/{business_id}/repair")
    async def repair_business(business_id: str, current_user: User = Depends(get_current_user)):
        """Repair business to full durability. Cost in $CITY.

        NOTE: wrapped in try/except so any unexpected failure yields a
        JSON 500 with `detail` rather than an HTML Internal Server Error.
        """
        try:
            business = await db.businesses.find_one({"id": business_id}, {"_id": 0})
            if not business:
                raise HTTPException(status_code=404, detail="Бизнес не найден")

            ui = await get_user_identifiers(current_user)
            if not ui["user"] or not is_owner(business, ui["ids"]):
                raise HTTPException(status_code=403, detail="Это не ваш бизнес")
            user = ui["user"]

            try:
                current_dur = float(business.get("durability", 100))
            except (TypeError, ValueError):
                current_dur = 100.0
            if current_dur >= 100:
                raise HTTPException(status_code=400, detail="Бизнес не нуждается в ремонте")

            missing = 100 - current_dur
            btype = business.get("business_type", "") or ""
            try:
                level = int(business.get("level", 1) or 1)
            except (TypeError, ValueError):
                level = 1
            level = max(1, min(10, level))
            config = _resolve_business_config(btype) or {}
            tier = int(config.get("tier", 1) or 1)
            tier = max(1, min(3, tier))

            from business_config import repair_cost_per_pct_city as _rcp

            cost_per_pct = _rcp(btype, tier, level)            # admin value or tier default
            cost_city = round(cost_per_pct * missing, 2)   # 0.3 $CITY per 1% stays exact

            # Patron Tier3 buff (-25% repair) — prefer per-business contract buff
            try:
                owner_buff = await get_user_patron_buff(ui["ids"], target_business=business)
                if owner_buff.get("effect", {}).get("type") == "repair_cost_multiplier":
                    cost_city = round(cost_city * owner_buff["effect"]["value"])
            except Exception as e:
                logger.warning(f"repair: patron buff lookup failed: {e}")

            # T3 resource buff (Gold Bill -20%)
            try:
                now_utc = datetime.now(timezone.utc)
                for rb in (user.get("active_resource_buffs") or []):
                    if rb.get("effect_type") != "repair_cost_multiplier":
                        continue
                    expires = rb.get("expires_at") or ""
                    if expires:
                        try:
                            exp_dt = datetime.fromisoformat(expires.replace('Z', '+00:00'))
                            if exp_dt <= now_utc:
                                continue
                        except (ValueError, TypeError):
                            continue
                    cost_city = round(cost_city * float(rb.get("effect_value", 1.0)))
            except Exception as e:
                logger.warning(f"repair: resource buff calc failed: {e}")

            # Tech Umbrella contract (-30%)
            try:
                active_contract = await db.contracts.find_one(
                    {"vassal_business_id": business_id, "status": "active", "type": "tech_umbrella"},
                    {"_id": 0}
                )
                if active_contract:
                    cost_city = round(cost_city * 0.70)
            except Exception as e:
                logger.warning(f"repair: contract lookup failed: {e}")

            cost_ton = cost_city / 1000.0

            # Split payment: spend BONUS balance first, then REAL balance —
            # so regular businesses can be repaired with bonus funds (parity
            # with the Trial Center repair). Total = bonus + real must cover cost.
            bonus_bal = float(user.get("bonus_balance", 0) or 0)
            real_bal = float(user.get("balance_ton", 0) or 0)
            if bonus_bal + real_bal + 1e-9 < cost_ton:
                raise HTTPException(
                    status_code=400,
                    detail=f"Недостаточно средств. Нужно {cost_city} $CITY ({cost_ton:.3f} TON)"
                )
            from core.balance import debit_user_split as _split
            _deb = await _split(db, get_user_filter(user), cost_ton, respect_frozen=False)
            if not _deb.get("ok"):
                raise HTTPException(
                    status_code=400,
                    detail=f"Недостаточно средств. Нужно {cost_city} $CITY ({cost_ton:.3f} TON)"
                )
            from_bonus, from_real = _deb["from_bonus"], _deb["from_real"]

            await db.businesses.update_one(
                {"id": business_id},
                {"$set": {
                    "durability": 100,
                    "last_wear_update": datetime.now(timezone.utc).isoformat(),
                    "last_repair": datetime.now(timezone.utc).isoformat(),
                    "work_status": "active",
                    "is_active": True,
                }}
            )

            # Get fresh balances after deduction (so frontend can update instantly)
            updated_user = await db.users.find_one(
                get_user_filter(user), {"_id": 0, "balance_ton": 1, "bonus_balance": 1}
            )
            new_balance = float(updated_user.get("balance_ton", 0) or 0) if updated_user else max(0.0, real_bal - from_real)
            new_bonus_balance = float(updated_user.get("bonus_balance", 0) or 0) if updated_user else max(0.0, bonus_bal - from_bonus)

            # Record transaction in history (visible to user + admin)
            biz_config = _resolve_business_config(btype) or {}
            biz_name = biz_config.get("name", {})
            if isinstance(biz_name, dict):
                biz_name_ru = biz_name.get("ru") or biz_name.get("en") or btype
            else:
                biz_name_ru = str(biz_name) if biz_name else btype
            description = f"Ремонт бизнеса «{biz_name_ru}» (ур. {level}) на {round(missing, 1)}%"
            tx_doc = {
                "id": str(uuid_mod.uuid4()),
                "user_id": user.get("id"),
                "user_username": user.get("username") or user.get("display_name") or user.get("email") or "",
                "user_wallet": user.get("wallet_address"),
                "type": "repair",
                "tx_type": "repair",
                "amount": -cost_ton,
                "amount_ton": -cost_ton,
                "amount_city": -cost_city,
                "from_address": user.get("wallet_address") or user.get("email") or user.get("id"),
                "to_address": "admin_treasury",
                "business_id": business_id,
                "description": description,
                "status": "completed",
                "details": {
                    "business_id": business_id,
                    "business_type": btype,
                    "business_name": biz_name_ru,
                    "level": level,
                    "missing_pct": round(missing, 1),
                    "cost_city": cost_city,
                    "cost_ton": round(cost_ton, 6),
                },
                "created_at": datetime.now(timezone.utc).isoformat(),
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
            try:
                await db.transactions.insert_one(tx_doc.copy())
            except Exception as e:
                logger.warning(f"repair: failed to log transaction: {e}")

            logger.info(f"Business {business_id} repaired by {user.get('username')} for {cost_city} $CITY")

            try:
                import quests as _quests
                _quests.fire(user, "repair", 1)
            except Exception:
                pass
            return {
                "status": "repaired",
                "cost_city": cost_city,
                "cost_paid": cost_ton,
                "cost_ton": round(cost_ton, 4),
                "missing_pct": round(missing, 1),
                "cost_per_pct": cost_per_pct,
                "new_durability": 100,
                "new_balance": round(new_balance, 4),
                "new_bonus_balance": round(new_bonus_balance, 4),
                "spent": {"from_bonus": round(from_bonus, 6), "from_real": round(from_real, 6)},
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.exception(f"repair_business failed for {business_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Ошибка ремонта: {e}")

    return router
