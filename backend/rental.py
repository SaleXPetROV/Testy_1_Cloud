"""Renting businesses out (player -> player).

Rules (agreed with the owner of the project):
  • An owner of a level 1+ business offers it «Сдать в аренду» with a price per day and
    the allowed number of days (inside the admin's limits). Level-0 businesses can't be rented.
  • The WHOLE term + a deposit of `deposit_days` days is FROZEN on the renter's account
    (users.frozen_ton), from the REAL balance only (otherwise a non-withdrawable bonus could
    become a withdrawable payment to the owner). Every day one day's rent is taken from the
    frozen money: the owner gets it minus the treasury commission (admin %), the treasury
    gets the commission. What is left is unfrozen at the end. Every movement is a transaction.
  • During the rental the business works for the renter: production, inputs and repairs
    are the renter's (business.owner = renter, business.rental_owner = the real owner).
    The owner gets the rent, never resources.
  • A rented business can't be sold, offered for rent, upgraded or re-skinned.
  • A player with a rented business can't claim a level-0 one (only buy level 1);
    a player holding a level-0 business can't rent.
  • Businesses per player (owned + rented + rented out) <= admin limit (default 3).
  • The renter may end early: used days + 1 day go to the owner, the rest is refunded.
  • Deposit: returned to the renter, unless the business lost more than
    `deposit_wear_points` durability during the rental — then it goes to the owner.
  • Supply contracts of the business keep working; during the rental the renter fulfils
    them and gets their income (they follow business.owner); shown before confirming.
"""
import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

from core.ttl_cache import cached, invalidate

CITY = 1000.0                                           # 1 TON = 1000 $CITY
RENTAL_TX = ["rental_freeze", "rental_charge", "rental_payout", "rental_commission", "rental_unfreeze", "rental_deposit_to_owner"]
DEFAULTS = {
    "enabled": True,
    "commission_pct": 10.0,          # % of the rent that goes to the treasury
    "min_price_pct": 20.0,           # rent per day >= this % of the estimated net profit per day
    "max_price_pct": 70.0,           # rent per day <= this % of the estimated net profit per day
    "min_days": 1, "max_days": 30,
    "deposit_days": 1,
    "deposit_wear_points": 20,       # durability points lost beyond which the deposit goes to the owner
    "max_businesses_per_user": 3,    # owned + rented + rented out
}


def _now():
    return datetime.now(timezone.utc)


def _iso(d):
    return d.isoformat()


def _parse(s):
    d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


async def get_config(db) -> Dict[str, Any]:
    async def load():
        doc = await db.admin_settings.find_one({"type": "rental"}, {"_id": 0}) or {}
        return {**DEFAULTS, **{k: v for k, v in doc.items() if k in DEFAULTS}}
    return dict(await cached(f"cfg:rental:{id(db)}", 30, load, owner=db))


# ───────────────────────── economics of one day (3 shifts = 24 h) ─────────────────────────
def estimate_business(biz: Dict[str, Any]) -> Dict[str, Any]:
    from business_config import (BUSINESS_KEY_MAP, BUSINESSES, RESOURCE_TYPES, get_production,
                                 get_consumption_breakdown, get_daily_wear, calculate_repair_cost)
    t = BUSINESS_KEY_MAP.get(biz.get("business_type"), biz.get("business_type"))
    lvl = int(biz.get("level", 1) or 1)
    cfg = BUSINESSES.get(t, {})
    produces = cfg.get("produces")
    price = lambda r: float((RESOURCE_TYPES.get(r) or {}).get("base_price", 0) or 0)   # $CITY per unit
    out_units = float(get_production(t, lvl) or 0)
    income = out_units * price(produces) if produces else 0.0
    inputs = {r: float(q) for r, q in (get_consumption_breakdown(t, lvl) or {}).items()}
    inputs_city = sum(q * price(r) for r, q in inputs.items())
    wear = float(get_daily_wear(t, lvl) or 0)
    repair_city = float(calculate_repair_cost(t, lvl, wear).get("ton", 0) or 0) * CITY
    tax_rate = 0.10
    tax_city = income * tax_rate
    net = income - inputs_city - repair_city - tax_city
    return {"business_type": t, "level": lvl, "produces": produces, "units_per_day": round(out_units, 2),
            "income_city": round(income, 2), "inputs": {r: round(q, 2) for r, q in inputs.items()},
            "inputs_city": round(inputs_city, 2), "wear_per_day": round(wear, 2), "repair_city": round(repair_city, 2),
            "tax_city": round(tax_city, 2), "net_city": round(net, 2), "shifts_per_day": 3,
            "note": "Оценка по базовым ценам ресурсов; цены рынка меняются."}


def price_bounds(cfg: Dict[str, Any], est: Dict[str, Any]) -> Dict[str, float]:
    net = max(0.0, est["net_city"])
    lo = round(net * cfg["min_price_pct"] / 100, 2)
    hi = round(max(lo, net * cfg["max_price_pct"] / 100), 2)
    return {"min_city": max(1.0, lo), "max_city": max(1.0, hi)}


async def contracts_of(db, business_id: str) -> List[Dict[str, Any]]:
    rows = await db.supply_contracts.find(
        {"$or": [{"seller_business_id": business_id}, {"buyer_business_id": business_id}],
         "status": {"$in": ["active", "accepted"]}}, {"_id": 0}).to_list(50)
    return [{"id": c.get("id"), "role": "поставляет" if c.get("seller_business_id") == business_id else "получает",
             "resource": c.get("resource_name") or c.get("resource_type"), "amount_per_day": c.get("amount_per_day"),
             "daily_income_city": c.get("daily_income_city"), "expires_at": c.get("expires_at"),
             "partner": c.get("buyer_username") if c.get("seller_business_id") == business_id else c.get("seller_username")}
            for c in rows]


# ───────────────────────── counting / rules shared with other code ─────────────────────────
async def count_user_businesses(db, user_ids: List[str]) -> int:
    """Owned + rented (business.owner) + rented out (business.rental_owner)."""
    ids = [i for i in user_ids if i]
    if not ids:
        return 0
    return await db.businesses.count_documents({"is_trial": {"$ne": True},
                                                "$or": [{"owner": {"$in": ids}}, {"rental_owner": {"$in": ids}}]})


async def max_businesses(db) -> int:
    return int((await get_config(db))["max_businesses_per_user"])


def assert_not_rented(biz: Optional[Dict[str, Any]]) -> None:
    """Guard for sell / list / upgrade / skin / offer endpoints."""
    if biz and biz.get("rental_id"):
        raise HTTPException(status_code=403, detail="Бизнес в аренде: продажа, сдача в аренду, улучшение и смена скина недоступны")


async def _ids(db, user) -> List[str]:
    return [v for v in (user.get("id"), user.get("wallet_address"), user.get("email")) if v]


# ───────────────────────── money movements ─────────────────────────
async def _tx(db, tx_type: str, user_id, amount_ton: float, r: Dict[str, Any], **extra) -> None:
    await db.transactions.insert_one({"id": str(uuid.uuid4()), "tx_type": tx_type, "user_id": user_id,
                                      "amount_ton": round(float(amount_ton), 9), "rental_id": r["id"],
                                      "business_id": r.get("business_id"), "status": "completed",
                                      "created_at": _iso(_now()), **extra})
async def _release(db, r: Dict[str, Any], days_due: int) -> float:
    """Pay the owner for `days_due` total days (idempotent: only the difference)."""
    days_due = min(int(r["days"]), max(0, int(days_due)))
    new = days_due - int(r.get("released_days", 0))
    if new <= 0:
        return 0.0
    # atomic step: only one settler can move released_days from N to N+new
    res = await db.rentals.update_one({"id": r["id"], "released_days": int(r.get("released_days", 0))},
                                      {"$set": {"released_days": days_due}})
    if not res.modified_count:
        return 0.0
    gross = round(new * r["price_per_day_ton"], 9)
    fee = round(gross * r["commission_pct"] / 100, 9)
    await db.users.update_one({"id": r["renter_id"]}, {"$inc": {"frozen_ton": -gross}})          # taken from the frozen money
    await db.users.update_one({"id": r["owner_id"]}, {"$inc": {"balance_ton": gross - fee, "total_income": gross - fee}})
    await db.admin_stats.update_one({"type": "treasury"}, {"$inc": {"rental_commission": fee, "total_tax": fee,
                                                                    "rental_paid_total": gross - fee}}, upsert=True)
    await db.rentals.update_one({"id": r["id"]}, {"$inc": {"released_ton": gross - fee, "commission_ton": fee}})
    await _tx(db, "rental_charge", r["renter_id"], gross, r, days=new)
    await _tx(db, "rental_payout", r["owner_id"], gross - fee, r, days=new)
    await _tx(db, "rental_commission", None, fee, r, days=new)
    r["released_days"] = days_due
    return gross


async def _finish(db, r: Dict[str, Any], reason: str) -> None:
    """Return the business to its owner, settle the deposit and any refund."""
    if (await db.rentals.update_one({"id": r["id"], "status": "active"}, {"$set": {"status": "finishing"}})).modified_count == 0:
        return
    biz = await db.businesses.find_one({"id": r["business_id"]}, {"_id": 0, "durability": 1}) or {}
    lost = float(r.get("start_durability", 100)) - float(biz.get("durability", 100) or 0)
    cfg_wear = float(r.get("deposit_wear_points", 20))
    refund_days = int(r["days"]) - int(r.get("released_days", 0))
    refund = round(max(0, refund_days) * r["price_per_day_ton"], 9)
    deposit = float(r.get("deposit_ton", 0))
    to_owner = deposit if lost > cfg_wear else 0.0
    to_renter = refund + (deposit - to_owner)
    # everything still frozen leaves the freeze: back to the renter (minus a deposit kept for heavy wear)
    await db.users.update_one({"id": r["renter_id"]}, {"$inc": {"frozen_ton": -(refund + deposit), "balance_ton": to_renter}})
    if to_renter > 0:
        await _tx(db, "rental_unfreeze", r["renter_id"], to_renter, r)
    if to_owner > 0:
        await db.users.update_one({"id": r["owner_id"]}, {"$inc": {"balance_ton": to_owner}})
        await _tx(db, "rental_deposit_to_owner", r["owner_id"], to_owner, r)
    await db.businesses.update_one({"id": r["business_id"]}, {
        "$set": {"owner": r["owner_id"]},
        "$unset": {"rental_id": "", "rental_owner": "", "rented_until": "", "rented_by": ""}})
    await db.rentals.update_one({"id": r["id"]}, {"$set": {
        "status": "ended", "ended_at": _iso(_now()), "end_reason": reason, "refund_ton": refund,
        "deposit_to_owner_ton": to_owner, "durability_lost": round(lost, 2)}})
    try:
        from core.notify import notify_user
        await notify_user(db, r["owner_id"], "rental_ended", "Аренда закончилась", "Ваш бизнес снова у вас.", {"rental_id": r["id"]})
        await notify_user(db, r["renter_id"], "rental_ended", "Аренда закончилась", "Арендованный бизнес вернулся владельцу.", {"rental_id": r["id"]})
    except Exception:
        pass


async def settle(db, now: Optional[datetime] = None) -> Dict[str, int]:
    """Scheduled: pay the owners day by day and return businesses whose term is over."""
    now = now or _now()
    paid = ended = 0
    async for r in db.rentals.find({"status": "active"}, {"_id": 0}):
        start, end = _parse(r["started_at"]), _parse(r["ends_at"])
        days_due = math.floor((min(now, end) - start).total_seconds() / 86400)
        if await _release(db, r, days_due):
            paid += 1
        if now >= end:
            await _release(db, r, int(r["days"]))
            await _finish(db, r, "term_over"); ended += 1
    return {"paid": paid, "ended": ended}


# ───────────────────────── API ─────────────────────────
def create_rental_router(db, get_current_user, get_current_admin) -> APIRouter:
    r = APIRouter()

    async def _me(current_user) -> Dict[str, Any]:
        u = await db.users.find_one({"id": current_user.id}, {"_id": 0})
        if not u:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        return u

    @r.get("/api/rental/estimate/{business_id}")
    async def r_estimate(business_id: str, current_user=Depends(get_current_user)):
        biz = await db.businesses.find_one({"id": business_id}, {"_id": 0})
        if not biz:
            raise HTTPException(status_code=404, detail="Бизнес не найден")
        cfg = await get_config(db); est = estimate_business(biz)
        return {"estimate": est, "bounds": price_bounds(cfg, est), "contracts": await contracts_of(db, business_id),
                "limits": {k: cfg[k] for k in ("min_days", "max_days", "deposit_days", "commission_pct")}}

    @r.post("/api/rental/offers")
    async def r_offer(body: Dict[str, Any], current_user=Depends(get_current_user)):
        cfg = await get_config(db)
        if not cfg["enabled"]:
            raise HTTPException(status_code=403, detail="Аренда сейчас выключена")
        me = await _me(current_user); ids = await _ids(db, me)
        biz = await db.businesses.find_one({"id": str(body.get("business_id") or "")}, {"_id": 0})
        if not biz or biz.get("owner") not in ids:
            raise HTTPException(status_code=403, detail="Это не ваш бизнес")
        assert_not_rented(biz)
        if int(biz.get("level", 0) or 0) < 1 or biz.get("is_zero_business"):
            raise HTTPException(status_code=400, detail="Бизнес уровня 0 нельзя сдать в аренду")
        if biz.get("on_sale") or biz.get("is_trial"):
            raise HTTPException(status_code=400, detail="Бизнес выставлен на продажу")
        if await db.rental_offers.find_one({"business_id": biz["id"], "status": "active"}):
            raise HTTPException(status_code=409, detail="Бизнес уже предлагается в аренду")
        est = estimate_business(biz); b = price_bounds(cfg, est)
        price_city = float(body.get("price_per_day_city", 0) or 0)
        if not b["min_city"] <= price_city <= b["max_city"]:
            raise HTTPException(status_code=400, detail=f"Цена за сутки: от {b['min_city']:g} до {b['max_city']:g} $CITY")
        dmin, dmax = int(body.get("min_days", cfg["min_days"])), int(body.get("max_days", cfg["max_days"]))
        if not cfg["min_days"] <= dmin <= dmax <= cfg["max_days"]:
            raise HTTPException(status_code=400, detail=f"Срок: от {cfg['min_days']} до {cfg['max_days']} суток")
        offer = {"id": str(uuid.uuid4()), "business_id": biz["id"], "owner_id": me["id"], "owner_username": me.get("username"),
                 "business_type": biz.get("business_type"), "level": biz.get("level"), "x": biz.get("x"), "y": biz.get("y"),
                 "price_per_day_ton": round(price_city / CITY, 9), "price_per_day_city": price_city,
                 "min_days": dmin, "max_days": dmax, "status": "active", "created_at": _iso(_now())}
        await db.rental_offers.insert_one(dict(offer)); offer.pop("_id", None)
        return offer

    @r.get("/api/rental/offers")
    async def r_offers():
        rows = await db.rental_offers.find({"status": "active"}, {"_id": 0}).sort("created_at", -1).to_list(200)
        return {"offers": rows}

    @r.delete("/api/rental/offers/{offer_id}")
    async def r_cancel(offer_id: str, current_user=Depends(get_current_user)):
        res = await db.rental_offers.update_one({"id": offer_id, "owner_id": current_user.id, "status": "active"},
                                                {"$set": {"status": "cancelled"}})
        if not res.modified_count:
            raise HTTPException(status_code=404, detail="Предложение не найдено")
        return {"ok": True}

    @r.post("/api/rental/offers/{offer_id}/rent")
    async def r_rent(offer_id: str, body: Dict[str, Any], current_user=Depends(get_current_user)):
        cfg = await get_config(db)
        if not cfg["enabled"]:
            raise HTTPException(status_code=403, detail="Аренда сейчас выключена")
        me = await _me(current_user); ids = await _ids(db, me)
        offer = await db.rental_offers.find_one({"id": offer_id, "status": "active"}, {"_id": 0})
        if not offer:
            raise HTTPException(status_code=404, detail="Предложение уже недоступно")
        if offer["owner_id"] in ids:
            raise HTTPException(status_code=400, detail="Нельзя арендовать свой бизнес")
        import zero_business as _zb
        if await _zb.has_zero_business(db, ids):
            raise HTTPException(status_code=423, detail="Пока у вас бизнес уровня 0, аренда недоступна")
        if await count_user_businesses(db, ids) >= int(cfg["max_businesses_per_user"]):
            raise HTTPException(status_code=400, detail=f"Не больше {cfg['max_businesses_per_user']} бизнесов, считая арендованные")
        days = int(body.get("days", offer["min_days"]))
        if not offer["min_days"] <= days <= offer["max_days"]:
            raise HTTPException(status_code=400, detail=f"Срок аренды: от {offer['min_days']} до {offer['max_days']} суток")
        biz = await db.businesses.find_one({"id": offer["business_id"]}, {"_id": 0})
        if not biz or biz.get("rental_id") or biz.get("owner") != offer["owner_id"] or biz.get("on_sale"):
            await db.rental_offers.update_one({"id": offer_id}, {"$set": {"status": "cancelled"}})
            raise HTTPException(status_code=409, detail="Бизнес больше не сдаётся")
        price = offer["price_per_day_ton"]; deposit = round(price * int(cfg["deposit_days"]), 9)
        total = round(price * days + deposit, 9)
        # 1) take the offer (only one renter wins)
        if not (await db.rental_offers.update_one({"id": offer_id, "status": "active"}, {"$set": {"status": "taken"}})).modified_count:
            raise HTTPException(status_code=409, detail="Бизнес только что арендовали")
        # 2) pay from the REAL balance (atomic)
        paid = await db.users.update_one({"id": me["id"], "balance_ton": {"$gte": total}},
                                         {"$inc": {"balance_ton": -total, "frozen_ton": total}})   # frozen, still the renter's
        if not paid.modified_count:
            await db.rental_offers.update_one({"id": offer_id}, {"$set": {"status": "active"}})
            raise HTTPException(status_code=400, detail=f"Нужно {total * CITY:,.0f} $CITY на реальном балансе (аренда + залог)".replace(",", " "))
        now = _now()
        rental = {"id": str(uuid.uuid4()), "offer_id": offer_id, "business_id": biz["id"], "owner_id": offer["owner_id"],
                  "renter_id": me["id"], "renter_username": me.get("username"), "price_per_day_ton": price, "days": days,
                  "deposit_ton": deposit, "paid_ton": total, "commission_pct": float(cfg["commission_pct"]),
                  "deposit_wear_points": float(cfg["deposit_wear_points"]), "released_days": 0, "released_ton": 0.0,
                  "commission_ton": 0.0, "start_durability": float(biz.get("durability", 100) or 0),
                  "started_at": _iso(now), "ends_at": _iso(now + timedelta(days=days)), "status": "active"}
        await db.rentals.insert_one(dict(rental))
        # 3) the business works for the renter until the end of the term
        await db.businesses.update_one({"id": biz["id"]}, {"$set": {
            "owner": me["id"], "rental_owner": offer["owner_id"], "rental_id": rental["id"], "rented_by": me["id"],
            "rented_until": rental["ends_at"]}})
        await _tx(db, "rental_freeze", me["id"], total, rental)
        try:
            from core.notify import notify_user
            await notify_user(db, offer["owner_id"], "rental_started", "Бизнес арендовали",
                              f"Срок {days} сут. Оплата поступает каждые сутки.", {"rental_id": rental["id"]})
        except Exception:
            pass
        rental.pop("_id", None)
        return rental

    @r.post("/api/rental/{rental_id}/end")
    async def r_end(rental_id: str, current_user=Depends(get_current_user)):
        rt = await db.rentals.find_one({"id": rental_id, "renter_id": current_user.id, "status": "active"}, {"_id": 0})
        if not rt:
            raise HTTPException(status_code=404, detail="Аренда не найдена")
        used = math.ceil((_now() - _parse(rt["started_at"])).total_seconds() / 86400)
        await _release(db, rt, min(int(rt["days"]), max(1, used) + 1))        # used days + 1 day to the owner
        await _finish(db, rt, "renter_ended")
        return {"ok": True}

    @r.get("/api/rental/my")
    async def r_my(current_user=Depends(get_current_user)):
        uid = current_user.id
        as_owner = await db.rentals.find({"owner_id": uid, "status": "active"}, {"_id": 0}).to_list(50)
        as_renter = await db.rentals.find({"renter_id": uid, "status": "active"}, {"_id": 0}).to_list(50)
        offers = await db.rental_offers.find({"owner_id": uid, "status": "active"}, {"_id": 0}).to_list(50)
        return {"rented_out": as_owner, "renting": as_renter, "offers": offers}

    @r.get("/api/admin/rental/config")
    async def a_get(_=Depends(get_current_admin)):
        return await get_config(db)

    @r.put("/api/admin/rental/config")
    async def a_put(body: Dict[str, Any], _=Depends(get_current_admin)):
        upd = {}
        for k, v in body.items():
            if k not in DEFAULTS:
                continue
            upd[k] = bool(v) if k == "enabled" else (int(v) if isinstance(DEFAULTS[k], int) and not isinstance(DEFAULTS[k], bool) else float(v))
        c = {**await get_config(db), **upd}
        if not (0 <= c["commission_pct"] <= 50 and 0 < c["min_price_pct"] <= c["max_price_pct"] <= 100
                and 1 <= c["min_days"] <= c["max_days"] <= 365 and c["max_businesses_per_user"] >= 1):
            raise HTTPException(status_code=400, detail="Проверьте значения: комиссия 0–50%, цены в %, сроки, лимит бизнесов")
        await db.admin_settings.update_one({"type": "rental"}, {"$set": {"type": "rental", **upd}}, upsert=True)
        invalidate("cfg:rental")
        return await get_config(db)

    @r.get("/api/admin/rental/stats")
    async def a_stats(days: int = 30, _=Depends(get_current_admin)):
        """Daily rent paid to owners and treasury commission (for the charts) + recent transactions."""
        days = max(1, min(180, int(days)))
        since = _iso(_now() - timedelta(days=days))
        series: Dict[str, Dict[str, float]] = {}
        async for t in db.transactions.find({"tx_type": {"$in": ["rental_payout", "rental_commission"]}, "created_at": {"$gte": since}},
                                            {"_id": 0, "tx_type": 1, "amount_ton": 1, "created_at": 1}):
            d = str(t["created_at"])[:10]
            row = series.setdefault(d, {"rent_city": 0.0, "commission_city": 0.0})
            row["rent_city" if t["tx_type"] == "rental_payout" else "commission_city"] += float(t["amount_ton"]) * CITY
        start = (_now() - timedelta(days=days - 1)).date()
        chart = []
        for i in range(days):
            d = (start + timedelta(days=i)).isoformat(); row = series.get(d, {"rent_city": 0.0, "commission_city": 0.0})
            chart.append({"day": d, "rent_city": round(row["rent_city"], 2), "commission_city": round(row["commission_city"], 2)})
        tre = await db.admin_stats.find_one({"type": "treasury"}, {"_id": 0}) or {}
        frozen = await db.users.aggregate([{"$group": {"_id": None, "s": {"$sum": "$frozen_ton"}}}]).to_list(1)
        recent = await db.transactions.find({"tx_type": {"$in": RENTAL_TX}}, {"_id": 0}).sort("created_at", -1).to_list(50)
        uids = list({t.get("user_id") for t in recent if t.get("user_id")})
        names = {u["id"]: u.get("username") for u in await db.users.find({"id": {"$in": uids}}, {"_id": 0, "id": 1, "username": 1}).to_list(None)}
        for t in recent:
            t["username"] = names.get(t.get("user_id"))
        return {"chart": chart,
                "totals": {"rent_paid_city": round(float(tre.get("rental_paid_total", 0) or 0) * CITY, 2),
                           "commission_city": round(float(tre.get("rental_commission", 0) or 0) * CITY, 2),
                           "frozen_city": round(float((frozen[0] if frozen else {}).get("s", 0) or 0) * CITY, 2),
                           "active": await db.rentals.count_documents({"status": "active"}),
                           "offers": await db.rental_offers.count_documents({"status": "active"})},
                "transactions": recent}

    @r.get("/api/admin/rental/list")
    async def a_list(status: str = "active", _=Depends(get_current_admin)):
        rows = await db.rentals.find({"status": status}, {"_id": 0}).sort("started_at", -1).to_list(200)
        held = sum(float(x["paid_ton"]) - float(x.get("released_ton", 0)) - float(x.get("commission_ton", 0)) for x in rows if x["status"] == "active")
        return {"rentals": rows, "held_ton": round(held, 6)}

    return r
