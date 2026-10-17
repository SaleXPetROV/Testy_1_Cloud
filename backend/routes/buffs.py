"""T3 Resource Buffs router.

Endpoints:
  GET  /api/resource-buffs/available — list buffs user can activate + currently active
  POST /api/resource-buffs/activate/{resource_id} — activate buff (1 unit, N days)

Rules:
  • Max 2 active buffs at once
  • No duplicate active buffs
  • 1 unit consumed once, duration from RESOURCE_BUFFS map

Split out of server.py (was lines 5713-5883).
"""
from datetime import datetime, timezone, timedelta
from core.dtutils import to_aware
import logging

from fastapi import APIRouter, HTTPException, Depends

from core.dependencies import get_current_user
from core.models import User
from core.helpers import get_user_identifiers as _helper_get_user_identifiers, get_user_filter
from business_config import RESOURCE_TYPES

logger = logging.getLogger(__name__)


# ===== Buff catalog (single source of truth) =====
RESOURCE_BUFFS = {
    "neuro_core": {
        "name": "Разгон системы",
        "description": "+8% к производству всех бизнесов",
        "icon": "🔮",
        "duration_days": 7,
        "effect_type": "production_multiplier",
        "effect_value": 1.08,
    },
    "gold_bill": {
        "name": "Золотой стандарт",
        "description": "-20% к стоимости ремонта",
        "icon": "📜",
        "duration_days": 7,
        "effect_type": "repair_cost_multiplier",
        "effect_value": 0.80,
    },
    "license_token": {
        "name": "Лицензия оптовика",
        "description": "-15% к торговой комиссии",
        "icon": "🎫",
        "duration_days": 5,
        "effect_type": "trade_fee_multiplier",
        "effect_value": 0.85,
    },
    "luck_chip": {
        "name": "Фортуна",
        "description": "+5% шанс x2 производства",
        "icon": "🎲",
        "duration_days": 5,
        "effect_type": "crit_chance_bonus",
        "effect_value": 0.05,
    },
    "war_protocol": {
        "name": "Закалка",
        "description": "-25% к скорости износа зданий",
        "icon": "⚔️",
        "duration_days": 7,
        "effect_type": "wear_reduction",
        "effect_value": 0.75,
    },
    "bio_module": {
        "name": "Эволюция",
        "description": "-10% к потреблению ресурсов",
        "icon": "🧬",
        "duration_days": 5,
        "effect_type": "consumption_multiplier",
        "effect_value": 0.90,
    },
    "gateway_code": {
        "name": "Мост доверия",
        "description": "-25% к комиссии на вывод",
        "icon": "🔑",
        "duration_days": 7,
        "effect_type": "withdrawal_fee_multiplier",
        "effect_value": 0.75,
    },
}


def create_buffs_router(db):
    """Factory: returns an APIRouter bound to the given Motor database."""
    router = APIRouter(prefix="/api", tags=["buffs"])

    async def get_user_identifiers(current_user):
        # core.helpers variant takes (db, current_user); match server.py signature.
        return await _helper_get_user_identifiers(db, current_user)

    @router.get("/resource-buffs/available")
    async def get_available_resource_buffs(current_user: User = Depends(get_current_user)):
        """Get T3 resources that user has and can activate as buffs."""
        ui = await get_user_identifiers(current_user)
        if not ui["user"]:
            return {"buffs": [], "active": []}
        user = ui["user"]
        resources = user.get("resources", {})
        active_buffs = user.get("active_resource_buffs", [])

        now = datetime.now(timezone.utc)
        still_active = []
        for b in active_buffs:
            expires = b.get("expires_at", "")
            if not expires:
                continue
            try:
                exp_dt = datetime.fromisoformat(expires.replace('Z', '+00:00'))
                if exp_dt > now:
                    delta_sec = (exp_dt - now).total_seconds()
                    days = int(delta_sec // 86400)
                    hours = int((delta_sec % 86400) // 3600)
                    still_active.append({
                        **b,
                        "days_remaining": round(delta_sec / 86400, 2),
                        "hours_remaining": round(delta_sec / 3600, 1),
                        "remaining_days": days,
                        "remaining_hours": hours,
                        "remaining_label": f"{days}д {hours}ч" if days > 0 else f"{hours}ч",
                    })
            except (ValueError, TypeError):
                pass

        available = []
        for res_id, buff in RESOURCE_BUFFS.items():
            # Tutorial-reward unit lives under `<res>_tutorial` — count both
            # buckets so the UI shows a single "quantity" that reflects
            # everything the user can activate as a buff.
            qty_regular = int(resources.get(res_id, 0) or 0)
            qty_tutorial = int(resources.get(f"{res_id}_tutorial", 0) or 0)
            qty = qty_regular + qty_tutorial
            res_info = RESOURCE_TYPES.get(res_id, {})
            already_active = any(a["resource_id"] == res_id for a in still_active)
            available.append({
                "resource_id": res_id,
                "resource_name": res_info.get("name_ru", res_id),
                "resource_icon": res_info.get("icon", "?"),
                "quantity": qty,
                "quantity_tutorial": qty_tutorial,
                "quantity_regular": qty_regular,
                "buff_name": buff["name"],
                "buff_description": buff["description"],
                "buff_icon": buff["icon"],
                "duration_days": buff["duration_days"],
                "effect_type": buff["effect_type"],
                "effect_value": buff["effect_value"],
                "already_active": already_active,
                "can_activate": qty >= 1 and not already_active,
            })

        return {"buffs": available, "active": still_active}

    @router.post("/resource-buffs/activate/{resource_id}")
    async def activate_resource_buff(
        resource_id: str,
        current_user: User = Depends(get_current_user)
    ):
        """Activate a T3 resource as a buff. Consumes 1 unit, lasts X days.

        Accepts either the base T3 id (e.g. `neuro_core`) or the tutorial
        variant (`neuro_core_tutorial`). The tutorial-reward slot is spent
        FIRST so the sellable pool stays intact for the marketplace.
        """
        # Normalize tutorial variants to their base T3 id.
        base_resource_id = resource_id[:-len("_tutorial")] if resource_id.endswith("_tutorial") else resource_id
        if base_resource_id not in RESOURCE_BUFFS:
            raise HTTPException(status_code=400, detail="Этот ресурс нельзя использовать как баф")

        ui = await get_user_identifiers(current_user)
        if not ui["user"]:
            raise HTTPException(status_code=401, detail="Пользователь не найден")
        user = ui["user"]

        # v2.1.5 GATE: cannot activate a T3 buff without an active (non-tutorial) business
        from core.helpers import user_has_active_business
        if not await user_has_active_business(db, user):
            raise HTTPException(
                status_code=400,
                detail="tutorial_buff_needs_business",
            )

        resources = user.get("resources", {})
        tut_key = f"{base_resource_id}_tutorial"
        qty_tutorial = int(resources.get(tut_key, 0) or 0)
        qty_regular = int(resources.get(base_resource_id, 0) or 0)
        if (qty_tutorial + qty_regular) < 1:
            raise HTTPException(status_code=400, detail="Недостаточно ресурсов (нужна 1 ед.)")

        active_buffs = user.get("active_resource_buffs", []) or []
        now = datetime.now(timezone.utc)

        # Drop expired
        active_buffs = [
            b for b in active_buffs
            if b.get("expires_at") and
               (to_aware(b["expires_at"]) or now) > now
        ]

        if len(active_buffs) >= 2:
            raise HTTPException(
                status_code=400,
                detail="Максимум 2 активных бафа одновременно. Дождитесь окончания одного из них."
            )
        if any(b["resource_id"] == base_resource_id for b in active_buffs):
            raise HTTPException(status_code=400, detail="Этот баф уже активен")

        buff = RESOURCE_BUFFS[base_resource_id]
        expires = now + timedelta(days=buff["duration_days"])

        new_buff = {
            "resource_id": base_resource_id,
            "buff_name": buff["name"],
            "buff_icon": buff["icon"],
            "buff_description": buff["description"],
            "effect_type": buff["effect_type"],
            "effect_value": buff["effect_value"],
            "activated_at": now.isoformat(),
            "expires_at": expires.isoformat(),
            "duration_days": buff["duration_days"],
            "active": True,
        }
        active_buffs.append(new_buff)

        # Consume 1 unit — tutorial-reward slot first, then regular stock.
        inc_ops = {}
        if qty_tutorial > 0:
            inc_ops[f"resources.{tut_key}"] = -1
        else:
            inc_ops[f"resources.{base_resource_id}"] = -1

        await db.users.update_one(
            get_user_filter(user),
            {
                "$inc": inc_ops,
                "$set": {"active_resource_buffs": active_buffs},
            }
        )

        res_info = RESOURCE_TYPES.get(base_resource_id, {})
        return {
            "success": True,
            "message": f"Баф «{buff['name']}» активирован на {buff['duration_days']} дней!",
            "buff": new_buff,
            "resource_consumed": f"1 {res_info.get('name_ru', base_resource_id)}",
        }

    @router.get("/my/resources")
    async def get_my_resources(current_user: User = Depends(get_current_user)):
        """Return user's resources (filtered: only qty>=1, floored) + locked map."""
        ui = await get_user_identifiers(current_user)
        if not ui["user"]:
            return {"resources": {}, "locked": {}}
        user_resources = dict(ui["user"].get("resources", {}))
        resources = {k: int(v) for k, v in user_resources.items() if int(v) >= 1}
        from core.helpers import tutorial_locked_map
        return {"resources": resources, "locked": tutorial_locked_map(ui["user"])}

    return router
