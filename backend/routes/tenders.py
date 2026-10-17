"""
Tender (B2B daily-supply) marketplace.

Workflow:
    1. Buyer creates a Tender for X units/day of a resource.
    2. Seller submits an Offer (= tender_contract row with status=PROPOSED).
    3. Buyer reviews seller stats and either:
         a) Accept → freeze escrow on seller, status=ACTIVE
         b) Reject → status=REJECTED
    4. Cron clears every hour: for each ACTIVE contract whose payment_hour ==
       current_hour, transfer goods and $CITY (minus tier tax). If either side
       lacks funds/resources → PENDING_*. After 24h pending → BROKEN with
       penalty (100% daily cost, 50% to the other side, 50% burned).

Money model:
    user.balance_ton is the canonical balance in TON.
    Prices are quoted in $CITY ($CITY = 1000 × TON).
    user.frozen_city_for_tenders stores the escrow in $CITY units.

T1 resources are sold "per 10 units" by convention everywhere else in the
codebase — same here. The wire-format always stores price_per_unit (per 1),
and the UI multiplies by 10 in display only.
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, List
import uuid as uuid_mod
import logging

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from core.database import db
from core.dependencies import get_current_user
from core.models import User
from business_config import (
    BUSINESSES,
    RESOURCE_TYPES,
    TIER_TAXES,
    BUSINESS_LEVELS,
    BUSINESS_KEY_MAP,
)
from core.helpers import resolve_business_config, resolve_owner_keys, owner_businesses_query

logger = logging.getLogger(__name__)

tenders_router = APIRouter(prefix="/tenders", tags=["tenders"])

CITY_PER_TON = 1000.0
PENDING_TIMEOUT_HOURS = 24
PENALTY_TO_PARTNER_FRACTION = 0.5  # other 50% is burned to treasury

# Escrow model:
#  - Seller freezes 1 day worth of contract cost at accept (penalty reserve only).
#  - Buyer freezes 2 days worth at accept (1 day = next payment + 1 day = penalty reserve).
#  - At each successful clearing tick, buyer's frozen decreases by 1 day (payment),
#    then a top-up of 1 day moves from buyer.balance_ton → frozen (so reserve stays at 2 days).
#  - On break, remaining frozen is unfrozen back to the user's balance_ton.
BUYER_ESCROW_DAYS = 2
SELLER_ESCROW_DAYS = 1


async def _notify_user(user_doc: dict, title: str, message: str, type_key: str = "tender_alert", priority: str = "info", payload: dict = None, i18n_key: str = None, i18n_vars: dict = None) -> None:
    """In-app + Telegram + WS через core.notify (текст переводится на язык пользователя)."""
    if not user_doc:
        return
    try:
        from core.notify import notify_user
        await notify_user(db, user_doc, title=title, message=message, type_key=type_key,
                          priority=priority, payload=payload, i18n_key=i18n_key, i18n_vars=i18n_vars)
    except Exception as e:
        logger.warning(f"tender notify failed: {e}")


def _multiplicity_for_tier(tier: int) -> int:
    """T1 ресурсы продаются партиями по 10, T2/T3 — поштучно."""
    return 10 if int(tier) == 1 else 1


# ─────────────────────────── helpers ────────────────────────────


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _tier_of(resource_type: str) -> int:
    return int(RESOURCE_TYPES.get(resource_type, {}).get("tier", 1))


def _tier_tax(tier: int) -> float:
    """Tier tax fraction (0.15 / 0.23 / 0.30)."""
    raw = TIER_TAXES.get(tier, 15)
    return float(raw) / 100.0 if raw > 1 else float(raw)


def _daily_cost_city(daily_amount: float, price_per_unit_city: float) -> float:
    return round(float(daily_amount) * float(price_per_unit_city), 4)


async def _user_by_id(uid: str) -> Optional[dict]:
    if not uid:
        return None
    return await db.users.find_one(
        {"$or": [{"id": uid}, {"wallet_address": uid}, {"username": uid}, {"email": uid}]},
        {"_id": 0},
    )


async def _compute_seller_free_capacity(seller_id: str, resource_type: str) -> dict:
    """Return {'daily_production', 'committed', 'free'} for a seller/resource."""
    # Daily production: sum production_per_tick * 24 for all businesses producing this resource.
    owner_keys = await resolve_owner_keys(db, seller_id)
    biz_cursor = db.businesses.find(owner_businesses_query(owner_keys), {"_id": 0})
    produces_resource = []
    daily = 0.0
    async for biz in biz_cursor:
        btype = biz.get("business_type")
        cfg = resolve_business_config(btype) or {}
        if cfg.get("produces") != resource_type:
            continue
        produces_resource.append(biz)
        lvl = max(1, int(biz.get("level", 1)))
        # BUSINESS_LEVELS is keyed by the canonical business id (e.g. hydro_cooling),
        # but biz.business_type may be the CITY_BUSINESSES alias (e.g. cold_storage).
        mapped_btype = BUSINESS_KEY_MAP.get(btype, btype)
        lvls = BUSINESS_LEVELS.get(mapped_btype, {}).get("production", {})
        # BUSINESS_LEVELS["production"][lvl] is the DAILY output value (see
        # background_tasks.py "production values are per-tick/day", scaled by
        # hourly_fraction = hours_passed/24).  No multiplication needed.
        per_day = float(lvls.get(lvl, lvls.get(1, 0)))
        daily += per_day

    # Already committed in active/pending contracts (status ACTIVE or PENDING_*)
    committed = 0.0
    async for c in db.tender_contracts.find(
        {
            "seller_id": seller_id,
            "resource_type": resource_type,
            "status": {"$in": ["ACTIVE", "PENDING_FUNDS", "PENDING_RESOURCES"]},
        },
        {"_id": 0, "daily_amount": 1},
    ):
        committed += float(c.get("daily_amount", 0) or 0)
    free = max(0.0, daily - committed)
    return {
        "resource_type": resource_type,
        "daily_production": round(daily, 2),
        "committed": round(committed, 2),
        "free": round(free, 2),
        "businesses_count": len(produces_resource),
    }


async def _seller_stats(seller_id: str) -> dict:
    """Reliability stats over all of this seller's tender_contracts."""
    pipe = [
        {"$match": {"seller_id": seller_id}},
        {
            "$group": {
                "_id": None,
                "ticks_completed": {"$sum": "$ticks_completed"},
                "ticks_failed": {"$sum": "$ticks_failed"},
                "total": {"$sum": 1},
                "broken_by_seller": {
                    "$sum": {"$cond": [{"$eq": ["$broken_by", "seller"]}, 1, 0]}
                },
            }
        },
    ]
    agg = await db.tender_contracts.aggregate(pipe).to_list(1)
    if not agg:
        return {
            "ticks_completed": 0,
            "ticks_failed": 0,
            "total_contracts": 0,
            "broken_by_seller": 0,
            "reliability": 100.0,
            "stars": 5,
        }
    r = agg[0]
    completed = int(r.get("ticks_completed", 0))
    failed = int(r.get("ticks_failed", 0))
    rel = (completed / (completed + failed) * 100) if (completed + failed) > 0 else 100.0
    return {
        "ticks_completed": completed,
        "ticks_failed": failed,
        "total_contracts": int(r.get("total", 0)),
        "broken_by_seller": int(r.get("broken_by_seller", 0)),
        "reliability": round(rel, 1),
        "stars": max(0, min(5, round(rel / 20))),
    }


async def _seller_main_business_for(seller_id: str, resource_type: str) -> Optional[dict]:
    """Highest-level business owned by seller producing the resource."""
    best = None
    owner_keys = await resolve_owner_keys(db, seller_id)
    async for biz in db.businesses.find(owner_businesses_query(owner_keys), {"_id": 0}):
        cfg = resolve_business_config(biz.get("business_type")) or {}
        if cfg.get("produces") != resource_type:
            continue
        lvl = int(biz.get("level", 1))
        if best is None or lvl > best["level"]:
            best = {
                "id": biz.get("id"),
                "business_type": biz.get("business_type"),
                "level": lvl,
                "name_ru": cfg.get("name", {}).get("ru") if isinstance(cfg.get("name"), dict) else (cfg.get("name_ru") or biz.get("business_type")),
                "icon": cfg.get("icon", "🏭"),
            }
    return best


async def _emit_ws(user_id: str, payload: dict) -> None:
    """Best-effort WS broadcast to a single user. Errors are silenced."""
    try:
        from core.websocket import manager  # type: ignore
        await manager.send_to_user(user_id, payload)
    except Exception:
        pass


# ─────────────────────────── Pydantic ────────────────────────────


class TenderCreate(BaseModel):
    resource_type: str
    total_amount_needed: float = Field(gt=0)
    max_price_per_unit: float = Field(gt=0, description="In $CITY per 1 unit")
    payment_hour: int = Field(ge=0, le=23)


class TenderPatch(BaseModel):
    max_price_per_unit: Optional[float] = Field(default=None, gt=0)
    payment_hour: Optional[int] = Field(default=None, ge=0, le=23)


class OfferCreate(BaseModel):
    daily_amount: float = Field(gt=0)
    price_per_unit: float = Field(gt=0, description="In $CITY per 1 unit")


class BreakReason(BaseModel):
    reason: Optional[str] = ""


class BreakRequestData(BaseModel):
    reason: Optional[str] = ""


class AmendmentCreate(BaseModel):
    daily_amount: float = Field(gt=0)
    price_per_unit: float = Field(gt=0, description="In $CITY per 1 unit")


# ─────────────────────────── Tender endpoints ────────────────────────────


@tenders_router.post("")
async def create_tender(data: TenderCreate, current_user: User = Depends(get_current_user)):
    if data.resource_type not in RESOURCE_TYPES:
        raise HTTPException(status_code=400, detail="Unknown resource_type")

    # v2.1.5 GATE: cannot publish a tender without owning any real business
    from core.helpers import user_has_active_business
    me_doc = await _user_by_id(current_user.id)
    if not await user_has_active_business(db, me_doc):
        raise HTTPException(status_code=400, detail="no_business_required_for_action")

    tier = _tier_of(data.resource_type)
    mult = _multiplicity_for_tier(tier)
    amount_int = int(round(data.total_amount_needed))
    if amount_int <= 0 or amount_int != data.total_amount_needed or amount_int % mult != 0:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Количество должно быть кратно {mult} (T{tier}). "
                f"Введите целое число, кратное {mult}."
            ),
        )

    # Per-user limit: max 5 non-terminal tenders.
    active_count = await db.tenders.count_documents({
        "buyer_id": current_user.id,
        "status": {"$in": ["OPEN", "FILLED"]},
    })
    if active_count >= 5:
        raise HTTPException(
            status_code=400,
            detail="Достигнут лимит: одновременно может быть только 5 тендеров. Удалите неиспользуемые.",
        )

    tender = {
        "id": str(uuid_mod.uuid4()),
        "buyer_id": current_user.id,
        "buyer_username": current_user.display_name or current_user.username or "Buyer",
        "resource_type": data.resource_type,
        "tier": tier,
        "total_amount_needed": float(amount_int),
        "current_filled_amount": 0.0,
        "max_price_per_unit": float(data.max_price_per_unit),
        "payment_hour": int(data.payment_hour),
        "status": "OPEN",
        "created_at": _now().isoformat(),
        "updated_at": _now().isoformat(),
    }
    await db.tenders.insert_one(tender.copy())
    tender.pop("_id", None)
    return tender


@tenders_router.get("")
async def list_open_tenders(
    resource_type: Optional[str] = None,
    tier: Optional[int] = None,
    current_user: User = Depends(get_current_user),
):
    q: dict = {"status": "OPEN"}
    if resource_type:
        q["resource_type"] = resource_type
    if tier:
        q["tier"] = int(tier)
    items = await (
        db.tenders.find(q, {"_id": 0}).sort("created_at", -1).limit(200).to_list(200)
    )
    return {"tenders": items, "count": len(items)}


@tenders_router.get("/me/capacity")
async def my_free_capacity(resource: str, current_user: User = Depends(get_current_user)):
    if resource not in RESOURCE_TYPES:
        raise HTTPException(status_code=400, detail="Unknown resource")
    return await _compute_seller_free_capacity(current_user.id, resource)


@tenders_router.get("/me/purchases")
async def my_purchases(current_user: User = Depends(get_current_user)):
    """List MY tenders (newest first) with embedded contracts."""
    tenders = await (
        db.tenders.find({"buyer_id": current_user.id}, {"_id": 0})
        .sort("created_at", -1)
        .to_list(500)
    )
    for t in tenders:
        contracts = await (
            db.tender_contracts.find(
                {"tender_id": t["id"], "status": {"$ne": "REJECTED"}}, {"_id": 0}
            )
            .sort("created_at", -1)
            .to_list(200)
        )
        # enrich each contract with seller stats + main business + storage cover
        for c in contracts:
            seller = await _user_by_id(c["seller_id"])
            c["seller_stats"] = await _seller_stats(c["seller_id"])
            c["seller_main_business"] = await _seller_main_business_for(
                c["seller_id"], c["resource_type"]
            )
            # Daily production of THIS resource across all of seller's businesses
            cap = await _compute_seller_free_capacity(c["seller_id"], c["resource_type"])
            c["seller_daily_production"] = cap["daily_production"]
            c["seller_free_capacity"] = cap["free"]
            stock = float((seller or {}).get("resources", {}).get(c["resource_type"], 0) or 0)
            c["seller_stock_days"] = round(stock / c["daily_amount"], 1) if c["daily_amount"] > 0 else 0
        t["contracts"] = contracts
        t["proposals_count"] = sum(1 for c in contracts if c.get("status") == "PROPOSED")
    return {"tenders": tenders}


@tenders_router.get("/me/supplies")
async def my_supplies(current_user: User = Depends(get_current_user)):
    """All tender_contracts where I am the seller (newest first)."""
    contracts = await (
        db.tender_contracts.find(
            {"seller_id": current_user.id, "status": {"$ne": "REJECTED"}}, {"_id": 0}
        )
        .sort("created_at", -1)
        .to_list(500)
    )
    me = await _user_by_id(current_user.id)
    my_resources = (me or {}).get("resources", {}) if me else {}
    for c in contracts:
        stock = float(my_resources.get(c["resource_type"], 0) or 0)
        c["my_stock_days"] = round(stock / c["daily_amount"], 1) if c["daily_amount"] > 0 else 0
        # tender meta for context
        tender = await db.tenders.find_one({"id": c["tender_id"]}, {"_id": 0, "buyer_username": 1, "status": 1})
        c["buyer_username"] = (tender or {}).get("buyer_username")
    return {"contracts": contracts}


@tenders_router.get("/contracts/{contract_id}")
async def get_contract_details(contract_id: str, current_user: User = Depends(get_current_user)):
    """Return one enriched tender contract, with the same seller-stats/main-business/
    capacity/stock fields used in /me/purchases. Used by the notification card to
    render the full proposal preview when the user expands a proposal notification.
    """
    contract = await db.tender_contracts.find_one({"id": contract_id}, {"_id": 0})
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    # ACL: only the buyer or the seller may see it.
    if current_user.id not in (contract.get("buyer_id"), contract.get("seller_id")):
        raise HTTPException(status_code=403, detail="Not your contract")

    seller = await _user_by_id(contract["seller_id"])
    contract["seller_stats"] = await _seller_stats(contract["seller_id"])
    contract["seller_main_business"] = await _seller_main_business_for(
        contract["seller_id"], contract["resource_type"]
    )
    cap = await _compute_seller_free_capacity(contract["seller_id"], contract["resource_type"])
    contract["seller_daily_production"] = cap["daily_production"]
    contract["seller_free_capacity"] = cap["free"]
    stock = float((seller or {}).get("resources", {}).get(contract["resource_type"], 0) or 0)
    contract["seller_stock_days"] = round(stock / contract["daily_amount"], 1) if contract["daily_amount"] > 0 else 0

    tender = await db.tenders.find_one({"id": contract["tender_id"]}, {"_id": 0})
    if tender:
        contract["tender"] = {
            "id": tender["id"],
            "max_price_per_unit": tender.get("max_price_per_unit"),
            "payment_hour": tender.get("payment_hour"),
            "status": tender.get("status"),
            "buyer_username": tender.get("buyer_username"),
            "total_amount_needed": tender.get("total_amount_needed"),
            "current_filled_amount": tender.get("current_filled_amount"),
        }
    return contract


@tenders_router.get("/{tender_id}")
async def tender_details(tender_id: str, current_user: User = Depends(get_current_user)):
    tender = await db.tenders.find_one({"id": tender_id}, {"_id": 0})
    if not tender:
        raise HTTPException(status_code=404, detail="Tender not found")
    return tender


@tenders_router.patch("/{tender_id}")
async def patch_tender(
    tender_id: str, data: TenderPatch, current_user: User = Depends(get_current_user)
):
    tender = await db.tenders.find_one({"id": tender_id}, {"_id": 0})
    if not tender:
        raise HTTPException(status_code=404, detail="Tender not found")
    if tender["buyer_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="Not your tender")
    active = await db.tender_contracts.count_documents(
        {"tender_id": tender_id, "status": {"$in": ["ACTIVE", "PENDING_FUNDS", "PENDING_RESOURCES", "PROPOSED"]}}
    )
    if active > 0:
        raise HTTPException(
            status_code=400,
            detail="Сначала разорвите или отклоните все активные/предложенные контракты",
        )
    upd = {"updated_at": _now().isoformat()}
    if data.max_price_per_unit is not None:
        upd["max_price_per_unit"] = float(data.max_price_per_unit)
    if data.payment_hour is not None:
        upd["payment_hour"] = int(data.payment_hour)
    await db.tenders.update_one({"id": tender_id}, {"$set": upd})
    return {"status": "updated", **upd}


@tenders_router.delete("/{tender_id}")
async def delete_tender(tender_id: str, current_user: User = Depends(get_current_user)):
    tender = await db.tenders.find_one({"id": tender_id}, {"_id": 0})
    if not tender:
        raise HTTPException(status_code=404, detail="Tender not found")
    if tender["buyer_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="Not your tender")
    blocking = await db.tender_contracts.count_documents(
        {"tender_id": tender_id, "status": {"$in": ["ACTIVE", "PENDING_FUNDS", "PENDING_RESOURCES", "PROPOSED"]}}
    )
    if blocking > 0:
        raise HTTPException(
            status_code=400,
            detail="Сначала разорвите/отклоните все контракты по этому тендеру",
        )
    await db.tenders.delete_one({"id": tender_id})
    return {"status": "deleted"}


# ─────────────────────────── Offer / contract endpoints ────────────────────────────


@tenders_router.post("/{tender_id}/offer")
async def submit_offer(
    tender_id: str, data: OfferCreate, current_user: User = Depends(get_current_user)
):
    """Seller submits an offer. Creates a PROPOSED tender_contract pending buyer approval."""
    # v2.1.5 GATE: cannot offer on a tender without owning any real business
    from core.helpers import user_has_active_business
    me_doc = await _user_by_id(current_user.id)
    if not await user_has_active_business(db, me_doc):
        raise HTTPException(status_code=400, detail="no_business_required_for_action")

    tender = await db.tenders.find_one({"id": tender_id}, {"_id": 0})
    if not tender:
        raise HTTPException(status_code=404, detail="Tender not found")
    if tender["status"] != "OPEN":
        raise HTTPException(status_code=400, detail="Tender is not open")
    if tender["buyer_id"] == current_user.id:
        raise HTTPException(status_code=400, detail="Нельзя предлагать на собственный тендер")
    if data.price_per_unit > tender["max_price_per_unit"] + 1e-9:
        raise HTTPException(status_code=400, detail="Цена выше максимума тендера")

    tier = int(tender["tier"])
    mult = _multiplicity_for_tier(tier)
    amount_int = int(round(data.daily_amount))
    if amount_int <= 0 or amount_int != data.daily_amount or amount_int % mult != 0:
        raise HTTPException(
            status_code=400,
            detail=f"Количество должно быть целым и кратным {mult} (T{tier}).",
        )

    cap = await _compute_seller_free_capacity(current_user.id, tender["resource_type"])
    if amount_int > cap["free"] + 1e-9:
        raise HTTPException(
            status_code=400,
            detail=f"Превышена свободная мощность: доступно {cap['free']} ед./сутки",
        )

    # Deduplication: a seller may have at most ONE non-terminal offer per tender.
    # If they already have a PROPOSED or ACTIVE-stage contract on this tender,
    # they cannot submit another — they must withdraw / break it first.
    existing = await db.tender_contracts.find_one(
        {
            "tender_id": tender_id,
            "seller_id": current_user.id,
            "status": {"$in": ["PROPOSED", "ACTIVE", "PENDING_FUNDS", "PENDING_RESOURCES"]},
        },
        {"_id": 0, "id": 1, "status": 1},
    )
    if existing:
        if existing.get("status") == "PROPOSED":
            raise HTTPException(
                status_code=400,
                detail="У вас уже есть предложение по этому тендеру — дождитесь решения покупателя или отзовите его.",
            )
        raise HTTPException(
            status_code=400,
            detail="У вас уже есть активный контракт по этому тендеру.",
        )

    available_slot = tender["total_amount_needed"] - tender["current_filled_amount"]
    if amount_int > available_slot + 1e-9:
        raise HTTPException(
            status_code=400,
            detail=f"В тендере осталось места только на {available_slot} ед./сутки",
        )

    # Verify seller can afford the 1-day penalty reserve (frozen at accept).
    daily_cost_city = _daily_cost_city(amount_int, data.price_per_unit)
    seller_reserve_ton = (daily_cost_city * SELLER_ESCROW_DAYS) / CITY_PER_TON
    seller_doc = await _user_by_id(current_user.id)
    seller_balance = float((seller_doc or {}).get("balance_ton", 0) or 0)
    seller_frozen_city = float((seller_doc or {}).get("frozen_city_for_tenders", 0) or 0)
    seller_available_ton = seller_balance - (seller_frozen_city / CITY_PER_TON)
    if seller_available_ton < seller_reserve_ton - 1e-9:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Недостаточно средств для заключения контракта. "
                f"Требуется заморозить {seller_reserve_ton:.4f} TON ({daily_cost_city:.2f} $CITY × {SELLER_ESCROW_DAYS} дн.) — "
                f"резерв на случай разрыва. Пополните баланс."
            ),
        )

    contract = {
        "id": str(uuid_mod.uuid4()),
        "tender_id": tender_id,
        "buyer_id": tender["buyer_id"],
        "buyer_username": tender["buyer_username"],
        "seller_id": current_user.id,
        "seller_username": current_user.display_name or current_user.username or "Seller",
        "resource_type": tender["resource_type"],
        "tier": tier,
        "daily_amount": float(amount_int),
        "price_per_unit": float(data.price_per_unit),
        "tax_rate": _tier_tax(tier),
        "payment_hour": tender["payment_hour"],
        "status": "PROPOSED",
        "escrow_deposit": 0.0,
        "buyer_escrow_deposit": 0.0,
        "pending_since": None,
        "last_payout_at": None,
        "next_payout_at": None,
        "total_paid_city": 0.0,
        "total_delivered_units": 0.0,
        "ticks_completed": 0,
        "ticks_failed": 0,
        "break_reason": None,
        "broken_at": None,
        "broken_by": None,
        "created_at": _now().isoformat(),
    }
    await db.tender_contracts.insert_one(contract.copy())
    contract.pop("_id", None)

    await _emit_ws(tender["buyer_id"], {
        "type": "tender_proposal_new",
        "tender_id": tender_id,
        "contract_id": contract["id"],
    })

    # In-app + Telegram notification to the buyer (issue #1: tender proposal notifications)
    try:
        buyer_doc = await _user_by_id(tender["buyer_id"])
        seller_username = current_user.display_name or current_user.username or "Seller"
        resource_meta = RESOURCE_TYPES.get(tender["resource_type"], {})
        resource_name = (
            (resource_meta.get("name") or {}).get("ru")
            if isinstance(resource_meta.get("name"), dict)
            else resource_meta.get("name")
        ) or tender["resource_type"]
        title = "Новое предложение по тендеру"
        message = (
            f"@{seller_username} предложил поставку {int(amount_int)} ед./сутки "
            f"ресурса «{resource_name}» по цене {data.price_per_unit:.2f} $CITY за единицу "
            f"({daily_cost_city:.2f} $CITY/день). Откройте тендер, чтобы принять или отклонить."
        )
        i18n_vars = {
            "seller": seller_username,
            "amount": int(amount_int),
            "resource": tender["resource_type"],  # frontend resolves localized name via resourceCatalog
            "price": f"{data.price_per_unit:.2f}",
            "daily": f"{daily_cost_city:.2f}",
        }
        await _notify_user(
            buyer_doc,
            title,
            message,
            type_key="tender_proposal_new",
            priority="info",
            payload={
                "tender_id": tender_id,
                "contract_id": contract["id"],
                "seller_id": current_user.id,
                "seller_username": seller_username,
                "kind": "tender_proposal",
                "daily_amount": int(amount_int),
                "price_per_unit": float(data.price_per_unit),
                "daily_cost_city": float(daily_cost_city),
                "resource_type": tender["resource_type"],
                "tier": tier,
            },
            i18n_key="notifTenderProposalNew",
            i18n_vars=i18n_vars,
        )
    except Exception as e:
        logger.warning(f"tender proposal notification failed: {e}")

    return contract


@tenders_router.post("/contracts/{contract_id}/accept")
async def accept_offer(contract_id: str, current_user: User = Depends(get_current_user)):
    contract = await db.tender_contracts.find_one({"id": contract_id}, {"_id": 0})
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    if contract["buyer_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="Not your contract")
    if contract["status"] != "PROPOSED":
        raise HTTPException(status_code=400, detail="Уже не PROPOSED")

    daily_cost_city = _daily_cost_city(contract["daily_amount"], contract["price_per_unit"])
    seller_reserve_city = daily_cost_city * SELLER_ESCROW_DAYS
    seller_reserve_ton = seller_reserve_city / CITY_PER_TON
    buyer_reserve_city = daily_cost_city * BUYER_ESCROW_DAYS
    buyer_reserve_ton = buyer_reserve_city / CITY_PER_TON

    # Verify buyer has 2-day escrow
    buyer = await _user_by_id(current_user.id)
    buyer_balance = float((buyer or {}).get("balance_ton", 0) or 0)
    buyer_frozen_city = float((buyer or {}).get("frozen_city_for_tenders", 0) or 0)
    buyer_available_ton = buyer_balance - (buyer_frozen_city / CITY_PER_TON)
    if buyer_available_ton < buyer_reserve_ton - 1e-9:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Недостаточно средств для заключения контракта. "
                f"Требуется заморозить {buyer_reserve_ton:.4f} TON "
                f"({daily_cost_city:.2f} $CITY × {BUYER_ESCROW_DAYS} дн.: 1 день на оплату + 1 день резерва). "
                f"Пополните баланс."
            ),
        )

    # Verify seller has 1-day reserve still available
    seller = await _user_by_id(contract["seller_id"])
    if not seller:
        raise HTTPException(status_code=400, detail="Seller not found")
    seller_balance = float(seller.get("balance_ton", 0) or 0)
    seller_frozen_city = float(seller.get("frozen_city_for_tenders", 0) or 0)
    seller_available_ton = seller_balance - (seller_frozen_city / CITY_PER_TON)
    if seller_available_ton < seller_reserve_ton - 1e-9:
        # Seller insolvent at accept time → mark BROKEN (by seller) so the audit
        # trail is unambiguous, and bubble the error back to the buyer.
        await db.tender_contracts.update_one(
            {"id": contract_id},
            {"$set": {
                "status": "BROKEN",
                "broken_by": "seller",
                "break_reason": "seller_insufficient_escrow",
                "broken_at": _now().isoformat(),
            }},
        )
        raise HTTPException(status_code=400, detail="У продавца не хватает средств на эскроу")

    # Freeze on seller
    await db.users.update_one(
        {"id": seller["id"]},
        {"$inc": {"frozen_city_for_tenders": seller_reserve_city}},
    )
    # Freeze on buyer
    await db.users.update_one(
        {"id": buyer["id"]},
        {"$inc": {"frozen_city_for_tenders": buyer_reserve_city}},
    )

    # Activate contract + increase tender filled
    now_iso = _now().isoformat()
    await db.tender_contracts.update_one(
        {"id": contract_id},
        {"$set": {
            "status": "ACTIVE",
            "escrow_deposit": seller_reserve_city,
            "buyer_escrow_deposit": buyer_reserve_city,
            "next_payout_at": now_iso,  # will be processed on next clearing tick
        }},
    )
    await db.tenders.update_one(
        {"id": contract["tender_id"]},
        {"$inc": {"current_filled_amount": contract["daily_amount"]},
         "$set": {"updated_at": now_iso}},
    )
    tender = await db.tenders.find_one({"id": contract["tender_id"]}, {"_id": 0})
    if tender and tender["current_filled_amount"] + 1e-9 >= tender["total_amount_needed"]:
        await db.tenders.update_one({"id": tender["id"]}, {"$set": {"status": "FILLED"}})

    await _emit_ws(contract["seller_id"], {
        "type": "tender_contract_accepted",
        "contract_id": contract_id,
    })

    # Notify seller that their offer was accepted
    try:
        buyer_username = contract.get("buyer_username") or current_user.display_name or current_user.username or "Buyer"
        resource_meta = RESOURCE_TYPES.get(contract["resource_type"], {})
        resource_name = (
            (resource_meta.get("name") or {}).get("ru")
            if isinstance(resource_meta.get("name"), dict)
            else resource_meta.get("name")
        ) or contract["resource_type"]
        await _notify_user(
            seller,
            "Предложение принято",
            (
                f"@{buyer_username} принял ваше предложение на поставку "
                f"{int(contract['daily_amount'])} ед./сутки ресурса «{resource_name}». "
                f"Контракт активен — поставки будут проводиться ежедневно в {contract['payment_hour']:02d}:00 UTC."
            ),
            type_key="tender_contract_accepted",
            priority="info",
            payload={"contract_id": contract_id, "tender_id": contract.get("tender_id"), "kind": "tender_accept"},
        )
    except Exception as e:
        logger.warning(f"tender accept notification failed: {e}")

    return {
        "status": "accepted",
        "seller_escrow_city": seller_reserve_city,
        "buyer_escrow_city": buyer_reserve_city,
    }


@tenders_router.post("/contracts/{contract_id}/reject")
async def reject_offer(contract_id: str, current_user: User = Depends(get_current_user)):
    contract = await db.tender_contracts.find_one({"id": contract_id}, {"_id": 0})
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    if contract["buyer_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="Not your contract")
    if contract["status"] != "PROPOSED":
        raise HTTPException(status_code=400, detail="Уже не PROPOSED")
    await db.tender_contracts.update_one(
        {"id": contract_id},
        {"$set": {"status": "REJECTED", "broken_at": _now().isoformat()}},
    )
    await _emit_ws(contract["seller_id"], {
        "type": "tender_contract_rejected",
        "contract_id": contract_id,
    })

    # Notify seller that their offer was rejected
    try:
        seller_doc = await _user_by_id(contract["seller_id"])
        buyer_username = contract.get("buyer_username") or current_user.display_name or current_user.username or "Buyer"
        resource_meta = RESOURCE_TYPES.get(contract["resource_type"], {})
        resource_name = (
            (resource_meta.get("name") or {}).get("ru")
            if isinstance(resource_meta.get("name"), dict)
            else resource_meta.get("name")
        ) or contract["resource_type"]
        await _notify_user(
            seller_doc,
            "Предложение отклонено",
            f"@{buyer_username} отклонил ваше предложение по поставке «{resource_name}» ({int(contract['daily_amount'])} ед./сутки).",
            type_key="tender_contract_rejected",
            priority="info",
            payload={"contract_id": contract_id, "tender_id": contract.get("tender_id"), "kind": "tender_reject"},
        )
    except Exception as e:
        logger.warning(f"tender reject notification failed: {e}")

    return {"status": "rejected"}


@tenders_router.post("/contracts/{contract_id}/break")
async def break_contract(
    contract_id: str, data: BreakReason, current_user: User = Depends(get_current_user)
):
    contract = await db.tender_contracts.find_one({"id": contract_id}, {"_id": 0})
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    if current_user.id not in (contract["buyer_id"], contract["seller_id"]):
        raise HTTPException(status_code=403, detail="Not your contract")
    if contract["status"] not in ("ACTIVE", "PENDING_FUNDS", "PENDING_RESOURCES"):
        raise HTTPException(status_code=400, detail="Контракт уже не активен")
    who = "buyer" if current_user.id == contract["buyer_id"] else "seller"
    await _do_break(contract, broken_by=who, reason=data.reason or "manual")
    return {"status": "broken", "broken_by": who}


@tenders_router.post("/contracts/{contract_id}/break_request")
async def propose_mutual_break(
    contract_id: str, data: BreakRequestData, current_user: User = Depends(get_current_user)
):
    """Propose a mutual (no-penalty) contract termination to the other party.

    The other party must accept via /break_request/accept or reject via
    /break_request/reject. Until then, contract continues normally.
    """
    contract = await db.tender_contracts.find_one({"id": contract_id}, {"_id": 0})
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    if current_user.id not in (contract["buyer_id"], contract["seller_id"]):
        raise HTTPException(status_code=403, detail="Not your contract")
    if contract["status"] not in ("ACTIVE", "PENDING_FUNDS", "PENDING_RESOURCES"):
        raise HTTPException(status_code=400, detail="Контракт уже не активен")
    existing = contract.get("break_request")
    if existing and existing.get("status") == "PENDING":
        raise HTTPException(status_code=400, detail="Уже есть активный запрос на разрыв")

    who = "buyer" if current_user.id == contract["buyer_id"] else "seller"
    now_iso = _now().isoformat()
    request_doc = {
        "id": str(uuid_mod.uuid4()),
        "requested_by": who,
        "requested_by_id": current_user.id,
        "requested_at": now_iso,
        "reason": data.reason or "",
        "status": "PENDING",
    }
    await db.tender_contracts.update_one(
        {"id": contract_id},
        {"$set": {"break_request": request_doc}},
    )

    other_id = contract["seller_id"] if who == "buyer" else contract["buyer_id"]
    other = await _user_by_id(other_id)
    requester_username = contract.get("buyer_username") if who == "buyer" else contract.get("seller_username")
    daily_cost = _daily_cost_city(contract["daily_amount"], contract["price_per_unit"])
    title = "Предложение разорвать контракт"
    message = (
        f"@{requester_username} предлагает мирно разорвать контракт "
        f"#{contract_id[:8]} ({int(contract['daily_amount'])} ед./сутки, "
        f"{daily_cost:.2f} $CITY/день). Без штрафов — заморозка просто разблокируется."
    )
    await _notify_user(other, title, message, type_key="tender_break_request", priority="warning", payload={"contract_id": contract_id, "kind": "break_request"})

    await _emit_ws(other_id, {
        "type": "tender_break_request",
        "contract_id": contract_id,
        "requested_by": who,
    })
    return {"status": "requested", "break_request": request_doc}


# ─────────────────────────── Contract amendments (Обновить) ────────────────────────────


@tenders_router.post("/contracts/{contract_id}/amendments")
async def propose_amendment(
    contract_id: str, data: AmendmentCreate, current_user: User = Depends(get_current_user)
):
    """Propose new daily_amount / price_per_unit for an ACTIVE contract.

    Either the seller or the buyer can initiate. The amendment is stored as
    `pending_amendment` on the contract; the counterparty has to accept or
    reject it. If accepted, the contract terms are updated and the escrow is
    re-frozen to match the new daily turnover (delta is taken from balance).
    """
    contract = await db.tender_contracts.find_one({"id": contract_id}, {"_id": 0})
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    if current_user.id not in (contract["buyer_id"], contract["seller_id"]):
        raise HTTPException(status_code=403, detail="Not your contract")
    if contract["status"] not in ("ACTIVE", "PENDING_FUNDS", "PENDING_RESOURCES"):
        raise HTTPException(status_code=400, detail="Контракт уже не активен")

    pending = contract.get("pending_amendment")
    if pending and pending.get("status") == "PENDING":
        raise HTTPException(status_code=400, detail="Уже есть активный запрос на изменение контракта")

    tier = int(contract.get("tier", 1))
    mult = _multiplicity_for_tier(tier)
    amount_int = int(round(data.daily_amount))
    if amount_int <= 0 or amount_int != data.daily_amount or amount_int % mult != 0:
        raise HTTPException(
            status_code=400,
            detail=f"Количество должно быть целым и кратным {mult} (T{tier}).",
        )

    # Verify tender max price still holds
    tender = await db.tenders.find_one({"id": contract["tender_id"]}, {"_id": 0})
    if not tender:
        raise HTTPException(status_code=400, detail="Tender not found")
    if data.price_per_unit > tender["max_price_per_unit"] + 1e-9:
        raise HTTPException(status_code=400, detail="Цена выше максимума тендера")

    who = "buyer" if current_user.id == contract["buyer_id"] else "seller"

    # If the SELLER initiated, they must still have capacity for the new amount
    # (existing committed = current contract amount; freeing it out for the check).
    if who == "seller":
        cap = await _compute_seller_free_capacity(current_user.id, contract["resource_type"])
        free_after_release = cap["free"] + float(contract["daily_amount"])
        if amount_int > free_after_release + 1e-9:
            raise HTTPException(
                status_code=400,
                detail=f"Превышена свободная мощность: доступно {int(free_after_release)} ед./сутки",
            )

    old_daily_cost = _daily_cost_city(contract["daily_amount"], contract["price_per_unit"])
    new_daily_cost = _daily_cost_city(amount_int, data.price_per_unit)
    # Delta in escrow that the counterparty side will need to top up if accepted.
    # Buyer's escrow scales with BUYER_ESCROW_DAYS, seller's with SELLER_ESCROW_DAYS.
    buyer_delta_city = (new_daily_cost - old_daily_cost) * BUYER_ESCROW_DAYS
    seller_delta_city = (new_daily_cost - old_daily_cost) * SELLER_ESCROW_DAYS

    now_iso = _now().isoformat()
    amendment = {
        "id": str(uuid_mod.uuid4()),
        "proposed_by": who,
        "proposed_by_id": current_user.id,
        "proposed_at": now_iso,
        "status": "PENDING",
        "old_daily_amount": float(contract["daily_amount"]),
        "old_price_per_unit": float(contract["price_per_unit"]),
        "new_daily_amount": float(amount_int),
        "new_price_per_unit": float(data.price_per_unit),
        "old_daily_cost_city": old_daily_cost,
        "new_daily_cost_city": new_daily_cost,
        "buyer_delta_city": round(buyer_delta_city, 4),
        "seller_delta_city": round(seller_delta_city, 4),
    }
    await db.tender_contracts.update_one(
        {"id": contract_id},
        {"$set": {"pending_amendment": amendment}},
    )

    # Notify the counterparty
    other_id = contract["seller_id"] if who == "buyer" else contract["buyer_id"]
    other = await _user_by_id(other_id)
    requester_username = (contract.get("buyer_username") if who == "buyer" else contract.get("seller_username")) or "User"
    your_delta_city = seller_delta_city if who == "buyer" else buyer_delta_city  # other side's delta
    title = "Предложение об изменении контракта"
    delta_phrase = ""
    if abs(your_delta_city) > 1e-6:
        if your_delta_city > 0:
            delta_phrase = f" К текущей заморозке будет добавлено ~{your_delta_city:.2f} $CITY."
        else:
            delta_phrase = f" Будет разморожено ~{abs(your_delta_city):.2f} $CITY."
    message = (
        f"@{requester_username} предлагает изменить контракт #{contract_id[:8]}: "
        f"новые условия — {amount_int} ед./сутки по цене {data.price_per_unit:.2f} $CITY за единицу "
        f"({new_daily_cost:.2f} $CITY/день, было {old_daily_cost:.2f} $CITY/день).{delta_phrase}"
    )
    i18n_vars = {
        "requester": requester_username,
        "amount": int(amount_int),
        "price": f"{data.price_per_unit:.2f}",
        "new_daily": f"{new_daily_cost:.2f}",
        "old_daily": f"{old_daily_cost:.2f}",
        "your_delta": f"{your_delta_city:+.2f}",
        "your_delta_abs": f"{abs(your_delta_city):.2f}",
    }
    await _notify_user(
        other,
        title,
        message,
        type_key="tender_amendment_new",
        priority="warning",
        payload={
            "contract_id": contract_id,
            "amendment_id": amendment["id"],
            "kind": "tender_amendment",
            "new_daily_amount": amount_int,
            "new_price_per_unit": float(data.price_per_unit),
            "new_daily_cost_city": new_daily_cost,
            "old_daily_cost_city": old_daily_cost,
            "your_delta_city": round(your_delta_city, 4),
            "proposed_by": who,
        },
        i18n_key="notifTenderAmendmentNew",
        i18n_vars=i18n_vars,
    )

    await _emit_ws(other_id, {
        "type": "tender_amendment_new",
        "contract_id": contract_id,
        "amendment_id": amendment["id"],
    })
    return {"status": "proposed", "amendment": amendment}


@tenders_router.post("/contracts/{contract_id}/amendments/{amendment_id}/accept")
async def accept_amendment(
    contract_id: str, amendment_id: str, current_user: User = Depends(get_current_user)
):
    contract = await db.tender_contracts.find_one({"id": contract_id}, {"_id": 0})
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    if current_user.id not in (contract["buyer_id"], contract["seller_id"]):
        raise HTTPException(status_code=403, detail="Not your contract")
    amendment = contract.get("pending_amendment")
    if not amendment or amendment.get("id") != amendment_id or amendment.get("status") != "PENDING":
        raise HTTPException(status_code=400, detail="Запрос на изменение не найден")
    if amendment.get("proposed_by_id") == current_user.id:
        raise HTTPException(status_code=400, detail="Нельзя принять собственный запрос")

    new_daily_amount = float(amendment["new_daily_amount"])
    new_price = float(amendment["new_price_per_unit"])
    buyer_delta_city = float(amendment.get("buyer_delta_city", 0) or 0)
    seller_delta_city = float(amendment.get("seller_delta_city", 0) or 0)
    buyer_delta_ton = buyer_delta_city / CITY_PER_TON
    seller_delta_ton = seller_delta_city / CITY_PER_TON

    # Re-validate that both parties have funds for any positive delta (escrow top-up).
    buyer = await _user_by_id(contract["buyer_id"])
    seller = await _user_by_id(contract["seller_id"])
    if buyer_delta_city > 0:
        b_avail = float(buyer.get("balance_ton", 0) or 0) - (float(buyer.get("frozen_city_for_tenders", 0) or 0) / CITY_PER_TON)
        if b_avail < buyer_delta_ton - 1e-9:
            raise HTTPException(status_code=400, detail=f"У покупателя не хватает средств: требуется ещё {buyer_delta_ton:.4f} TON")
    if seller_delta_city > 0:
        s_avail = float(seller.get("balance_ton", 0) or 0) - (float(seller.get("frozen_city_for_tenders", 0) or 0) / CITY_PER_TON)
        if s_avail < seller_delta_ton - 1e-9:
            raise HTTPException(status_code=400, detail=f"У продавца не хватает средств: требуется ещё {seller_delta_ton:.4f} TON")

    # Apply delta to escrows (positive = freeze more, negative = release some)
    if abs(buyer_delta_city) > 1e-9:
        await db.users.update_one(
            {"id": contract["buyer_id"]},
            {"$inc": {"frozen_city_for_tenders": buyer_delta_city}},
        )
    if abs(seller_delta_city) > 1e-9:
        await db.users.update_one(
            {"id": contract["seller_id"]},
            {"$inc": {"frozen_city_for_tenders": seller_delta_city}},
        )

    # Apply new terms and stamp amendment as ACCEPTED.
    new_buyer_escrow = float(contract.get("buyer_escrow_deposit", 0) or 0) + buyer_delta_city
    new_seller_escrow = float(contract.get("escrow_deposit", 0) or 0) + seller_delta_city
    await db.tender_contracts.update_one(
        {"id": contract_id},
        {"$set": {
            "daily_amount": new_daily_amount,
            "price_per_unit": new_price,
            "buyer_escrow_deposit": round(new_buyer_escrow, 4),
            "escrow_deposit": round(new_seller_escrow, 4),
            "pending_amendment.status": "ACCEPTED",
            "pending_amendment.resolved_at": _now().isoformat(),
        }},
    )
    # Reflect new daily commitment on the parent tender (current_filled_amount).
    delta_units = new_daily_amount - float(amendment["old_daily_amount"])
    if abs(delta_units) > 1e-9:
        await db.tenders.update_one(
            {"id": contract["tender_id"]},
            {"$inc": {"current_filled_amount": delta_units},
             "$set": {"updated_at": _now().isoformat()}},
        )

    # Notify both parties of the accepted change.
    for uid in (contract["buyer_id"], contract["seller_id"]):
        u = await _user_by_id(uid)
        delta_for_u = buyer_delta_city if uid == contract["buyer_id"] else seller_delta_city
        delta_phrase = ""
        if abs(delta_for_u) > 1e-6:
            if delta_for_u > 0:
                delta_phrase = f" К вашей заморозке добавлено {delta_for_u:.2f} $CITY."
            else:
                delta_phrase = f" Разморожено {abs(delta_for_u):.2f} $CITY."
        await _notify_user(
            u,
            "Контракт обновлён",
            (
                f"Условия контракта #{contract_id[:8]} обновлены: "
                f"{int(new_daily_amount)} ед./сутки по {new_price:.2f} $CITY за единицу.{delta_phrase}"
            ),
            type_key="tender_amendment_accepted",
            priority="info",
            payload={"contract_id": contract_id, "amendment_id": amendment_id, "kind": "tender_amendment_resolved"},
            i18n_key="notifTenderAmendmentAccepted",
            i18n_vars={
                "amount": int(new_daily_amount),
                "price": f"{new_price:.2f}",
                "delta_signed": f"{delta_for_u:+.2f}",
                "delta_abs": f"{abs(delta_for_u):.2f}",
            },
        )

    await _emit_ws(contract["buyer_id"], {"type": "tender_amendment_accepted", "contract_id": contract_id, "amendment_id": amendment_id})
    await _emit_ws(contract["seller_id"], {"type": "tender_amendment_accepted", "contract_id": contract_id, "amendment_id": amendment_id})
    return {"status": "accepted", "new_daily_amount": new_daily_amount, "new_price_per_unit": new_price}


@tenders_router.post("/contracts/{contract_id}/amendments/{amendment_id}/reject")
async def reject_amendment(
    contract_id: str, amendment_id: str, current_user: User = Depends(get_current_user)
):
    contract = await db.tender_contracts.find_one({"id": contract_id}, {"_id": 0})
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    if current_user.id not in (contract["buyer_id"], contract["seller_id"]):
        raise HTTPException(status_code=403, detail="Not your contract")
    amendment = contract.get("pending_amendment")
    if not amendment or amendment.get("id") != amendment_id or amendment.get("status") != "PENDING":
        raise HTTPException(status_code=400, detail="Запрос на изменение не найден")
    if amendment.get("proposed_by_id") == current_user.id:
        raise HTTPException(status_code=400, detail="Нельзя отклонить собственный запрос")

    await db.tender_contracts.update_one(
        {"id": contract_id},
        {"$set": {"pending_amendment.status": "REJECTED",
                  "pending_amendment.resolved_at": _now().isoformat()}},
    )

    # Notify the original proposer
    proposer_id = amendment.get("proposed_by_id")
    proposer = await _user_by_id(proposer_id) if proposer_id else None
    rejector_name = current_user.username or current_user.display_name or "User"
    await _notify_user(
        proposer,
        "Изменение контракта отклонено",
        f"@{rejector_name} отклонил предложенные изменения контракта #{contract_id[:8]}.",
        type_key="tender_amendment_rejected",
        priority="info",
        payload={"contract_id": contract_id, "amendment_id": amendment_id, "kind": "tender_amendment_resolved"},
        i18n_key="notifTenderAmendmentRejected",
        i18n_vars={"user": rejector_name},
    )
    return {"status": "rejected"}


@tenders_router.post("/contracts/{contract_id}/break_request/accept")
async def accept_mutual_break(
    contract_id: str, current_user: User = Depends(get_current_user)
):
    contract = await db.tender_contracts.find_one({"id": contract_id}, {"_id": 0})
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    if current_user.id not in (contract["buyer_id"], contract["seller_id"]):
        raise HTTPException(status_code=403, detail="Not your contract")
    req = contract.get("break_request")
    if not req or req.get("status") != "PENDING":
        raise HTTPException(status_code=400, detail="Нет активного запроса")
    if req.get("requested_by_id") == current_user.id:
        raise HTTPException(status_code=400, detail="Нельзя принять собственный запрос")

    await _do_break(contract, broken_by="mutual", reason="mutual_agreement")
    await db.tender_contracts.update_one(
        {"id": contract_id},
        {"$set": {"break_request.status": "ACCEPTED",
                  "break_request.resolved_at": _now().isoformat()}},
    )

    # Notify both parties
    buyer = await _user_by_id(contract["buyer_id"])
    seller = await _user_by_id(contract["seller_id"])
    title = "Контракт разорван по соглашению сторон"
    message = (
        f"Контракт #{contract_id[:8]} был мирно разорван. "
        f"Замороженные средства разблокированы и доступны к выводу. Штрафов нет."
    )
    await _notify_user(buyer, title, message, type_key="tender_break_mutual", priority="info", payload={"contract_id": contract_id})
    await _notify_user(seller, title, message, type_key="tender_break_mutual", priority="info", payload={"contract_id": contract_id})

    return {"status": "broken_mutual"}


@tenders_router.post("/contracts/{contract_id}/break_request/reject")
async def reject_mutual_break(
    contract_id: str, current_user: User = Depends(get_current_user)
):
    contract = await db.tender_contracts.find_one({"id": contract_id}, {"_id": 0})
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    if current_user.id not in (contract["buyer_id"], contract["seller_id"]):
        raise HTTPException(status_code=403, detail="Not your contract")
    req = contract.get("break_request")
    if not req or req.get("status") != "PENDING":
        raise HTTPException(status_code=400, detail="Нет активного запроса")
    if req.get("requested_by_id") == current_user.id:
        raise HTTPException(status_code=400, detail="Нельзя отклонить собственный запрос")

    await db.tender_contracts.update_one(
        {"id": contract_id},
        {"$set": {"break_request.status": "REJECTED",
                  "break_request.resolved_at": _now().isoformat()}},
    )
    # Notify requester
    requester_id = req.get("requested_by_id")
    requester = await _user_by_id(requester_id) if requester_id else None
    other_username = current_user.username or ""
    await _notify_user(
        requester,
        "Предложение о мирном разрыве отклонено",
        f"@{other_username} отклонил(а) предложение мирно разорвать контракт #{contract_id[:8]}.",
        type_key="tender_break_request_rejected",
    )
    return {"status": "rejected"}


# ─────────────────────────── Clearing / Penalty internals ────────────────────────────


async def _do_break(contract: dict, broken_by: str, reason: str) -> None:
    """Penalize the party at fault (50% to partner, 50% burned), unfreeze escrow.

    Escrow semantics (NEW):
      • frozen_city_for_tenders is a *claim* against balance_ton (not a separate
        bucket). On accept we INCREMENT frozen; on break/clear we DECREMENT it.
      • balance_ton is never moved at accept — it just becomes partially
        un-withdrawable. So unfreezing is just decrementing the counter.
    """
    daily_cost_city = _daily_cost_city(contract["daily_amount"], contract["price_per_unit"])
    daily_cost_ton = daily_cost_city / CITY_PER_TON

    # Unfreeze seller reserve
    seller_id = contract["seller_id"]
    seller_escrow = float(contract.get("escrow_deposit", 0) or 0)
    if seller_escrow > 0:
        await db.users.update_one(
            {"id": seller_id},
            {"$inc": {"frozen_city_for_tenders": -seller_escrow}},
        )
    # Unfreeze buyer reserve
    buyer_id_local = contract["buyer_id"]
    buyer_escrow = float(contract.get("buyer_escrow_deposit", 0) or 0)
    if buyer_escrow > 0:
        await db.users.update_one(
            {"id": buyer_id_local},
            {"$inc": {"frozen_city_for_tenders": -buyer_escrow}},
        )

    # Charge penalty to the at-fault party (skip for mutual termination)
    paid = 0.0
    partner_share = 0.0
    burned_share = 0.0
    if broken_by != "mutual":
        culprit_id = seller_id if broken_by == "seller" else contract["buyer_id"]
        partner_id = contract["buyer_id"] if broken_by == "seller" else seller_id
        culprit = await _user_by_id(culprit_id)
        if culprit:
            bal = float(culprit.get("balance_ton", 0) or 0)
            paid = min(bal, daily_cost_ton)
            if paid > 0:
                await db.users.update_one({"id": culprit["id"]}, {"$inc": {"balance_ton": -paid}})
            debt = daily_cost_ton - paid
            if debt > 0:
                await db.users.update_one(
                    {"id": culprit["id"]}, {"$inc": {"tender_debt_ton": debt}}
                )

        # Distribute to partner and treasury
        partner_share = round(paid * PENALTY_TO_PARTNER_FRACTION, 6)
        burned_share = round(paid - partner_share, 6)
        if partner_share > 0:
            await db.users.update_one({"id": partner_id}, {"$inc": {"balance_ton": partner_share}})
        if burned_share > 0:
            await db.admin_stats.update_one(
                {"type": "treasury"},
                {"$inc": {"tender_penalty_burn_ton": burned_share, "total_tax": burned_share}},
                upsert=True,
            )

    # Update contract + tender
    now_iso = _now().isoformat()
    await db.tender_contracts.update_one(
        {"id": contract["id"]},
        {"$set": {
            "status": "BROKEN",
            "broken_by": broken_by,
            "broken_at": now_iso,
            "break_reason": reason,
            "escrow_deposit": 0.0,
            "buyer_escrow_deposit": 0.0,
        }},
    )
    await db.tenders.update_one(
        {"id": contract["tender_id"]},
        {"$inc": {"current_filled_amount": -float(contract["daily_amount"])},
         "$set": {"status": "OPEN", "updated_at": now_iso}},
    )

    await _emit_ws(contract["buyer_id"], {
        "type": "tender_contract_broken", "contract_id": contract["id"],
        "broken_by": broken_by, "penalty_ton_paid": paid,
        "partner_compensation_ton": partner_share if (broken_by == "seller") else 0,
    })
    await _emit_ws(contract["seller_id"], {
        "type": "tender_contract_broken", "contract_id": contract["id"],
        "broken_by": broken_by, "penalty_ton_paid": paid,
        "partner_compensation_ton": partner_share if (broken_by == "buyer") else 0,
    })

    # In-app + telegram notifications for unilateral break
    if broken_by in ("buyer", "seller"):
        buyer_doc = await _user_by_id(contract["buyer_id"])
        seller_doc = await _user_by_id(contract["seller_id"])
        culprit_doc = seller_doc if broken_by == "seller" else buyer_doc
        partner_doc = buyer_doc if broken_by == "seller" else seller_doc
        daily_cost_city = _daily_cost_city(contract["daily_amount"], contract["price_per_unit"])
        await _notify_user(
            culprit_doc,
            "Контракт разорван (штраф)",
            (f"Вы разорвали контракт #{contract['id'][:8]} в одностороннем порядке. "
             f"С вас списана суточная стоимость: {daily_cost_city:.2f} $CITY (штраф)."),
            type_key="tender_break_unilateral",
            priority="critical",
            payload={"contract_id": contract["id"]},
        )
        await _notify_user(
            partner_doc,
            "Контракт разорван другой стороной",
            (f"Контракт #{contract['id'][:8]} был расторгнут другой стороной. "
             f"Вы получили компенсацию: {(partner_share * CITY_PER_TON):.2f} $CITY. "
             f"Замороженные средства разблокированы."),
            type_key="tender_break_received",
            priority="warning",
            payload={"contract_id": contract["id"]},
        )


async def _process_tick(contract: dict) -> None:
    """One clearing pass for a single contract."""
    seller = await _user_by_id(contract["seller_id"])
    buyer = await _user_by_id(contract["buyer_id"])
    if not seller or not buyer:
        return
    daily_amount = float(contract["daily_amount"])
    gross_city = _daily_cost_city(daily_amount, contract["price_per_unit"])
    gross_ton = gross_city / CITY_PER_TON

    seller_stock = float((seller.get("resources") or {}).get(contract["resource_type"], 0) or 0)
    buyer_ton = float(buyer.get("balance_ton", 0) or 0)

    now = _now()
    if seller_stock < daily_amount or buyer_ton < gross_ton:
        # Set/keep pending
        new_status = "PENDING_RESOURCES" if seller_stock < daily_amount else "PENDING_FUNDS"
        was_active = contract.get("status") == "ACTIVE"
        pending_since = contract.get("pending_since") or now.isoformat()
        await db.tender_contracts.update_one(
            {"id": contract["id"]},
            {"$set": {"status": new_status, "pending_since": pending_since},
             "$inc": {"ticks_failed": 1}},
        )
        # Notify (in-app + telegram) once on transition into pending
        if was_active:
            r_name = contract.get("resource_type") or "ресурс"
            if new_status == "PENDING_RESOURCES":
                await _notify_user(
                    seller,
                    "Контракт под угрозой разрыва",
                    (f"Не хватает {r_name} для поставки по контракту "
                     f"#{contract['id'][:8]} ({int(daily_amount)} ед./сутки). "
                     f"Произведите/докупите ресурс, иначе контракт разорвётся через "
                     f"{PENDING_TIMEOUT_HOURS} ч."),
                    type_key="tender_pending_resources",
                )
                await _notify_user(
                    buyer,
                    "Поставщик не отгружает товар",
                    (f"У поставщика @{contract.get('seller_username')} нет {r_name} "
                     f"для исполнения контракта #{contract['id'][:8]}."),
                    type_key="tender_pending_resources",
                )
            else:
                await _notify_user(
                    buyer,
                    "Контракт под угрозой разрыва",
                    (f"Не хватает $CITY для оплаты контракта #{contract['id'][:8]} "
                     f"({gross_city:.2f} $CITY/сутки). Пополните баланс, иначе "
                     f"контракт разорвётся через {PENDING_TIMEOUT_HOURS} ч."),
                    type_key="tender_pending_funds",
                )
                await _notify_user(
                    seller,
                    "Покупатель не платит",
                    (f"У покупателя @{contract.get('buyer_username')} нет средств "
                     f"для оплаты контракта #{contract['id'][:8]}."),
                    type_key="tender_pending_funds",
                )
        # Auto-break after 24h pending
        try:
            since_dt = datetime.fromisoformat(pending_since.replace("Z", "+00:00"))
            if since_dt.tzinfo is None:
                since_dt = since_dt.replace(tzinfo=timezone.utc)
            if (now - since_dt) >= timedelta(hours=PENDING_TIMEOUT_HOURS):
                refreshed = await db.tender_contracts.find_one({"id": contract["id"]}, {"_id": 0})
                if refreshed:
                    blame = "seller" if seller_stock < daily_amount else "buyer"
                    await _do_break(refreshed, broken_by=blame, reason="pending_timeout")
        except Exception:
            pass
        await _emit_ws(contract["buyer_id"], {"type": "tender_contract_pending", "contract_id": contract["id"], "reason": new_status})
        await _emit_ws(contract["seller_id"], {"type": "tender_contract_pending", "contract_id": contract["id"], "reason": new_status})
        return

    # Successful tick — move goods and money
    tax_city = round(gross_city * float(contract["tax_rate"]), 4)
    net_city = round(gross_city - tax_city, 4)
    tax_ton = tax_city / CITY_PER_TON
    net_ton = net_city / CITY_PER_TON

    await db.users.update_one(
        {"id": seller["id"]},
        {"$inc": {f"resources.{contract['resource_type']}": -daily_amount, "balance_ton": net_ton}},
    )
    await db.users.update_one(
        {"id": buyer["id"]},
        {"$inc": {"balance_ton": -gross_ton, f"resources.{contract['resource_type']}": daily_amount}},
    )
    await db.admin_stats.update_one(
        {"type": "treasury"},
        {"$inc": {"tender_tax_ton": tax_ton, "total_tax": tax_ton}},
        upsert=True,
    )
    next_payout = (now + timedelta(hours=24)).isoformat()
    await db.tender_contracts.update_one(
        {"id": contract["id"]},
        {"$set": {
            "status": "ACTIVE",
            "pending_since": None,
            "last_payout_at": now.isoformat(),
            "next_payout_at": next_payout,
        },
         "$inc": {
             "ticks_completed": 1,
             "total_paid_city": gross_city,
             "total_delivered_units": daily_amount,
         }},
    )

    # Transaction trail — store TWO entries so each user sees the correct
    # amount in their own history:
    #   buyer: -gross_city (in TON), as "contract_payment_out"
    #   seller: +net_city  (in TON), as "contract_payment_in"
    tx_common = {
        "contract_id": contract["id"],
        "resource_type": contract["resource_type"],
        "resource_amount": daily_amount,
        "gross_city": gross_city,
        "tax_city": tax_city,
        "net_city": net_city,
        "tier": contract.get("tier"),
        "buyer_id": buyer["id"],
        "seller_id": seller["id"],
        "buyer_username": contract.get("buyer_username"),
        "seller_username": contract.get("seller_username"),
        "created_at": now.isoformat(),
        "status": "completed",
    }
    await db.transactions.insert_one({
        **tx_common,
        "id": str(uuid_mod.uuid4()),
        "type": "contract_payment_out",
        "user_id": buyer["id"],
        "amount": -gross_ton,
        "amount_ton": -gross_ton,
        "amount_city": -gross_city,
    })
    await db.transactions.insert_one({
        **tx_common,
        "id": str(uuid_mod.uuid4()),
        "type": "contract_payment_in",
        "user_id": seller["id"],
        "amount": net_ton,
        "amount_ton": net_ton,
        "amount_city": net_city,
        "tax": tax_ton,
    })

    await _emit_ws(contract["buyer_id"], {"type": "tender_contract_paid", "contract_id": contract["id"], "gross_city": gross_city})
    await _emit_ws(contract["seller_id"], {"type": "tender_contract_paid", "contract_id": contract["id"], "net_city": net_city})


async def run_tender_clearing(now: Optional[datetime] = None) -> dict:
    """Tender clearing job — runs every minute, but actually fires per contract
    only when due.

    A contract is due when:
      • status is ACTIVE / PENDING_FUNDS / PENDING_RESOURCES
      • AND its scheduled payout time has arrived. The schedule is derived from
        the contract's `payment_hour` field (UTC) and runs once per day. We
        track this with `last_payout_at`: a contract is due when at least
        ~23h 55min have passed since the previous payout AND the current UTC
        hour is >= payment_hour for that day; for the very first tick
        (no `last_payout_at` yet), it fires as soon as the current hour matches
        or has passed `payment_hour`.

    This catch-up logic makes us resilient to scheduler downtime — if the
    backend was offline at HH:00 UTC, the next tick after restart will still
    process the overdue contract.
    """
    now = now or _now()
    processed = 0
    overdue_threshold = now - timedelta(hours=23, minutes=55)

    # Stage 1: standard hourly run for contracts whose payment_hour matches now
    # and that either have never been paid or were last paid > 23h55m ago.
    hour_cursor = db.tender_contracts.find(
        {
            "payment_hour": now.hour,
            "status": {"$in": ["ACTIVE", "PENDING_FUNDS", "PENDING_RESOURCES"]},
            "$or": [
                {"last_payout_at": None},
                {"last_payout_at": {"$exists": False}},
                {"last_payout_at": {"$lte": overdue_threshold.isoformat()}},
            ],
        },
        {"_id": 0},
    )
    seen_ids = set()
    async for c in hour_cursor:
        cid = c.get("id")
        if cid in seen_ids:
            continue
        seen_ids.add(cid)
        try:
            await _process_tick(c)
            processed += 1
        except Exception as e:
            logger.exception("tender clearing failed for %s: %s", cid, e)

    # Stage 2: CATCH-UP — pick up any contract whose payout was missed
    # (e.g., scheduler downtime crossed an HH:00 boundary). We process them
    # in the next clearing run after the missed hour.
    catchup_cursor = db.tender_contracts.find(
        {
            "status": {"$in": ["ACTIVE", "PENDING_FUNDS", "PENDING_RESOURCES"]},
            "$or": [
                # Never been paid AND we're past the scheduled hour
                {
                    "$and": [
                        {"$or": [{"last_payout_at": None}, {"last_payout_at": {"$exists": False}}]},
                        {"payment_hour": {"$lte": now.hour}},
                    ]
                },
                # Last payout was more than ~25h ago — definitely overdue
                {"last_payout_at": {"$lte": (now - timedelta(hours=25)).isoformat()}},
            ],
        },
        {"_id": 0},
    )
    async for c in catchup_cursor:
        cid = c.get("id")
        if cid in seen_ids:
            continue
        seen_ids.add(cid)
        try:
            logger.info("tender clearing CATCH-UP for contract %s (payment_hour=%s)", cid, c.get("payment_hour"))
            await _process_tick(c)
            processed += 1
        except Exception as e:
            logger.exception("tender clearing catch-up failed for %s: %s", cid, e)

    # Stage 3: PENDING RETRY — re-check every PENDING contract every clearing
    # tick (not just at payment_hour). When the seller produces/stocks goods
    # or the buyer tops up $CITY, the contract should resume IMMEDIATELY
    # without waiting up to 24h for the next payment_hour slot. This is the
    # fix for issue #1: goods accumulating instead of being auto-delivered.
    pending_cursor = db.tender_contracts.find(
        {"status": {"$in": ["PENDING_FUNDS", "PENDING_RESOURCES"]}},
        {"_id": 0},
    )
    async for c in pending_cursor:
        cid = c.get("id")
        if cid in seen_ids:
            continue
        seen_ids.add(cid)
        try:
            logger.info("tender clearing PENDING-RETRY for contract %s (status=%s)", cid, c.get("status"))
            await _process_tick(c)
            processed += 1
        except Exception as e:
            logger.exception("tender clearing pending retry failed for %s: %s", cid, e)

    logger.info("tender clearing: processed %d contracts at %s UTC", processed, now.strftime("%H:%M"))
    return {"processed": processed, "hour": now.hour, "minute": now.minute}
