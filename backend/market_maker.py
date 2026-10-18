"""GRAM City — the City Market (system market maker).

A safety net for a thin market, not a competitor to players: it buys BELOW
and sells ABOVE the table price, so players always do better trading with
each other and the City Market only steps in when no player deal happens.
It is shown to players honestly as «Городской рынок» / "City Market".

Buy side (every cycle) — the rule depends on WHO sells, because level-0
players cannot choose a price (their lots use the fixed system price,
core/pricing.py) while level 1+ players type their own:
    • newbie lot      — the seller's FIRST sale, up to `newbie_max_units`, at
                        a price <= their system price, after `newbie_delay_min`
                        (the «Sell a resource» newbie step never gets stuck);
    • auto-price lot  — a seller with ONLY level-0 businesses: any later lot is
                        bought at its system price after `auto_price_delay_min`.
                        Paid to the bonus balance, so it costs no real money;
    • cheap lot       — a seller with a level 1+ business (sets own price): a
                        lot older than `min_lot_age_min` priced at or below the
                        City Market buy price is bought, paid to the real balance.
    (A player never owns level-0 and level 1+ businesses at the same time:
    level-0 owners cannot buy businesses, level 1+ owners cannot claim level 0.)

Prices (admin)
    The reference is the STATIC table price of each resource (business_config).
    buy  = table price − buy_discount_pct %   (or the admin's manual price)
    sell = table price + sell_markup_pct %    (or the admin's manual price)
    The buy price must stay below the sell price.
    Seller economics (tax, credits, referral split, tax haven, treasury) are
    exactly the normal ones — server._admin_buyout_apply_sale is reused.
    Payout rule (owner's decision): REAL balance if the seller owns a level 1+
    business, BONUS otherwise (zero_business.city_market_payout_is_real).

Sell side (every cycle)
    Everything the City Market bought is put up for sale automatically — one
    lot per resource holding the WHOLE stock, at the sell price. Nothing is
    created from thin air: it only resells what it bought.

Switches & limits (all in the admin)
    «Выкуп у новичков» (on by default) and «Выкуп за реальные деньги» (off by
    default, needs a daily budget); daily bonus cap for all newbies and per
    newbie; per-player caps (accounts on one device count as one player); stock
    cap per resource; max share of one player in a day's buys. Everything is
    journaled in `mm_trades`.
"""
from __future__ import annotations

import logging
import statistics
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))
CITY_MARKET_ID = "CITY_MARKET"
CITY_MARKET_NAME = "City Market"          # the UI shows a localized name (is_city_market flag)
TIER1_DEFAULT = ["energy", "biomass", "quartz", "cu", "traffic", "cooling", "scrap"]

DEFAULT_CONFIG: Dict[str, Any] = {
    "newbie_buy_enabled": True,       # buy lots of level-0 sellers (bonus payout, no real money)
    "real_buy_enabled": False,        # buy lots of level 1+ sellers (real payout, needs a budget)
    "daily_budget_ton": 0.0,          # real-money budget per MSK day (admin sets it)
    "bonus_daily_cap_city": 20000,    # all bonus payouts of the City Market per day ($CITY)
    "per_newbie_daily_cap_city": 500, # bonus payouts to ONE newbie (device group) per day ($CITY)
    "buy_discount_pct": 30,           # buy price  = table price − 30 % (unless overridden per resource)
    "sell_markup_pct": 30,            # sell price = table price + 30 % (unless overridden per resource)
    "min_lot_age_min": 30,            # a player lot must wait this long first
    "player_daily_cap_ton": 1.0,      # per player (device group) per day
    "player_daily_cap_units": 500,
    "inventory_cap_units": 1000,      # stock cap per resource
    "max_player_share_pct": 20,       # one player's max share of a day's buys
    "share_min_volume_ton": 1.0,      # share rule applies once the day passes this volume
    "newbie_max_units": 10,           # first-sale guarantee: up to N units
    "newbie_delay_min": 2,
    "auto_price_delay_min": 30,       # later lots of level-0 sellers: bought after N minutes
    "sell_enabled": True,             # everything bought is put up for sale automatically
    "buy_resources": TIER1_DEFAULT,   # resource types the City Market BUYS from players
    "sell_resources": TIER1_DEFAULT,  # resource types it SELLS from its stock
}
LIST_KEYS = ("buy_resources", "sell_resources")
# per-resource manual prices in $CITY: {"energy": {"buy_city": 2.0, "sell_city": 4.5}}
OVERRIDES_KEY = "price_overrides"
NUM_KEYS = {k for k, v in DEFAULT_CONFIG.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
BOOL_KEYS = {k for k, v in DEFAULT_CONFIG.items() if isinstance(v, bool)}

ApplySale = Callable[..., Awaitable[Dict[str, Any]]]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _day(dt: Optional[datetime] = None) -> str:
    return (dt or _now()).astimezone(MSK).date().isoformat()


def _parse(ts: Any) -> Optional[datetime]:
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _base_ton(resource: str) -> float:
    from business_config import RESOURCE_TYPES
    return float((RESOURCE_TYPES.get(resource) or {}).get("base_price", 0) or 0) / 1000.0


# ───────────────────────────── config ─────────────────────────────
async def get_config(db) -> Dict[str, Any]:
    from core.ttl_cache import cached
    import copy
    return copy.deepcopy(await cached(f"cfg:market_maker:{id(db)}", 30, lambda: _load_config(db), owner=db))


async def _load_config(db) -> Dict[str, Any]:
    doc = await db.admin_settings.find_one({"type": "market_maker"}, {"_id": 0}) or {}
    cfg = {**DEFAULT_CONFIG, **{k: v for k, v in doc.items() if k in DEFAULT_CONFIG}}
    cfg[OVERRIDES_KEY] = dict(doc.get(OVERRIDES_KEY) or {})
    # older settings stored "price as % of table" and one master switch
    if "buy_discount_pct" not in doc and "buy_price_pct" in doc:
        cfg["buy_discount_pct"] = max(0, 100 - int(doc["buy_price_pct"]))
    if "sell_markup_pct" not in doc and "sell_price_pct" in doc:
        cfg["sell_markup_pct"] = max(0, int(doc["sell_price_pct"]) - 100)
    if "real_buy_enabled" not in doc and doc.get("enabled") is True:
        cfg["real_buy_enabled"] = True
    # older settings had one shared "resources" list
    if "resources" in doc:
        for k in LIST_KEYS:
            if k not in doc:
                cfg[k] = list(doc["resources"])
    return cfg


async def save_config(db, patch: Dict[str, Any]) -> Dict[str, Any]:
    from business_config import RESOURCE_TYPES
    clean: Dict[str, Any] = {}
    for k, v in (patch or {}).items():
        if k in BOOL_KEYS:
            clean[k] = bool(v)
        elif k in NUM_KEYS:
            try:
                fv = float(v)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=f"{k} must be a number")
            if fv < 0:
                raise HTTPException(status_code=400, detail=f"{k} must be >= 0")
            if k == "buy_discount_pct" and fv >= 100:
                raise HTTPException(status_code=400, detail="buy_discount_pct must be < 100")
            if k == "max_player_share_pct" and fv > 100:
                raise HTTPException(status_code=400, detail="max_player_share_pct must be <= 100")
            clean[k] = fv if isinstance(DEFAULT_CONFIG[k], float) else int(fv)
        elif k == OVERRIDES_KEY:
            if not isinstance(v, dict):
                raise HTTPException(status_code=400, detail="price_overrides must be an object")
            ov = {}
            for rid, pr in v.items():
                if rid not in RESOURCE_TYPES or not isinstance(pr, dict):
                    raise HTTPException(status_code=400, detail=f"Unknown resource {rid}")
                row = {}
                for side in ("buy_city", "sell_city"):
                    val = pr.get(side)
                    if val in (None, ""):
                        continue
                    try:
                        fval = float(val)
                    except (TypeError, ValueError):
                        raise HTTPException(status_code=400, detail=f"{rid}.{side} must be a number")
                    if fval <= 0:
                        raise HTTPException(status_code=400, detail=f"{rid}.{side} must be > 0")
                    row[side] = round(fval, 6)
                if row:
                    ov[rid] = row
            clean[k] = ov
        elif k in LIST_KEYS:
            if not isinstance(v, list) or any(r not in RESOURCE_TYPES for r in v):
                raise HTTPException(status_code=400, detail=f"{k} must be a list of known resource ids")
            clean[k] = list(dict.fromkeys(v))
        else:
            raise HTTPException(status_code=400, detail=f"Unknown setting {k}")
    if clean.get("real_buy_enabled") is True or clean.get("newbie_buy_enabled") is True:
        clean["enabled_at"] = _now().isoformat()
    # never let the city buy for more than it sells (players could loop money through it)
    merged = {**(await get_config(db)), **clean}
    for rid in set(merged["buy_resources"]) | set(merged["sell_resources"]):
        b, sl = prices_city(merged, rid)
        if b >= sl:
            raise HTTPException(status_code=400,
                                detail=f"{rid}: цена выкупа ({b}) должна быть ниже цены продажи ({sl})")
    await db.admin_settings.update_one({"type": "market_maker"}, {"$set": {"type": "market_maker", **clean}}, upsert=True)
    from core.ttl_cache import invalidate
    invalidate("cfg:market_maker")
    return await get_config(db)


def base_city(resource: str) -> float:
    """The STATIC reference price of a resource ($CITY/unit, business_config)."""
    from business_config import RESOURCE_TYPES
    return float((RESOURCE_TYPES.get(resource) or {}).get("base_price", 0) or 0)


def prices_city(cfg: Dict[str, Any], resource: str) -> tuple:
    """(buy, sell) prices of the City Market in $CITY per unit: computed from the
    static table price and the admin percentages, or the admin's manual price."""
    base = base_city(resource)
    ov = (cfg.get(OVERRIDES_KEY) or {}).get(resource) or {}
    buy = ov.get("buy_city") or round(base * (100 - float(cfg["buy_discount_pct"])) / 100.0, 4)
    sell = ov.get("sell_city") or round(base * (100 + float(cfg["sell_markup_pct"])) / 100.0, 4)
    return float(buy), float(sell)


# ───────────────────────────── daily counters / stock ─────────────────────────────
async def _daily(db, day: Optional[str] = None) -> Dict[str, Any]:
    day = day or _day()
    doc = await db.mm_daily.find_one({"day": day}, {"_id": 0})
    return doc or {"day": day, "real_spent_ton": 0.0, "bonus_spent_ton": 0.0,
                   "bought_ton": 0.0, "bought_units": 0, "sold_ton": 0.0, "sold_units": 0,
                   "groups": {}, "skipped_share": 0, "budget_exhausted": False}


async def _inc_daily(db, inc: Dict[str, Any], set_: Optional[Dict[str, Any]] = None) -> None:
    upd: Dict[str, Any] = {"$inc": inc, "$setOnInsert": {"day": _day()}}
    if set_:
        upd["$set"] = set_
    await db.mm_daily.update_one({"day": _day()}, upd, upsert=True)


async def stock(db) -> Dict[str, Dict[str, float]]:
    rows = await db.mm_inventory.find({}, {"_id": 0}).to_list(500)
    return {r["resource"]: r for r in rows}


async def _stock_add(db, resource: str, units: int, cost_ton: float) -> None:
    await db.mm_inventory.update_one({"resource": resource},
                                     {"$inc": {"amount": units, "cost_ton": cost_ton},
                                      "$setOnInsert": {"resource": resource}}, upsert=True)


async def _stock_remove(db, resource: str, units: int) -> None:
    row = await db.mm_inventory.find_one({"resource": resource}, {"_id": 0}) or {}
    have = int(row.get("amount", 0) or 0)
    take = min(have, int(units))
    if take <= 0:
        return
    cost = float(row.get("cost_ton", 0) or 0)
    cost_out = cost * take / have if have else 0.0
    await db.mm_inventory.update_one({"resource": resource, "amount": {"$gte": take}},
                                     {"$inc": {"amount": -take, "cost_ton": -cost_out}})


# ───────────────────────────── players ─────────────────────────────
async def _seller_user(db, listing: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    sid = listing.get("seller_id") or listing.get("seller_user_id")
    if not sid:
        return None
    return await db.users.find_one({"$or": [{"id": sid}, {"wallet_address": sid}]}, {"_id": 0}) \
        or (await db.users.find_one({"email": listing.get("seller_email")}, {"_id": 0}) if listing.get("seller_email") else None)


async def device_group(db, uid: str, cache: Dict[str, str]) -> str:
    """Accounts sharing a device fingerprint count as ONE player for the caps."""
    if uid in cache:
        return cache[uid]
    visitors = await db.fingerprints.distinct("visitor_id", {"user_id": uid, "visitor_id": {"$ne": None}})
    members = {uid}
    if visitors:
        members |= set(await db.fingerprints.distinct("user_id", {"visitor_id": {"$in": visitors}}))
    gid = min(m for m in members if m)
    for m in members:
        cache[m] = gid
    return gid


async def _is_first_sale(db, user: Dict[str, Any]) -> bool:
    """The seller never sold anything before (to anybody)."""
    keys = [k for k in (user.get("id"), user.get("wallet_address"), user.get("email")) if k]
    if await db.transactions.count_documents({"tx_type": "market_purchase", "seller_id": {"$in": keys}}, limit=1):
        return False
    if await db.mm_trades.count_documents({"side": "buy", "user_id": user.get("id")}, limit=1):
        return False
    return True


async def payout_target(db, user: Dict[str, Any]) -> str:
    import zero_business as zb
    keys = {user.get("id"), user.get("wallet_address"), user.get("email"), user.get("username")} - {None, ""}
    return "real" if await zb.city_market_payout_is_real(db, keys) else "bonus"


# ───────────────────────────── buy side ─────────────────────────────
async def run_buy_side(db, apply_sale: ApplySale) -> Dict[str, Any]:
    cfg = await get_config(db)
    out = {"bought": 0, "newbie": 0, "skipped": {}, "spent_real_ton": 0.0, "spent_bonus_ton": 0.0}
    if not cfg["newbie_buy_enabled"] and not cfg["real_buy_enabled"]:
        out["skipped"]["disabled"] = 1
        return out

    def skip(reason: str):
        out["skipped"][reason] = out["skipped"].get(reason, 0) + 1

    daily = await _daily(db)
    real_left = max(0.0, float(cfg["daily_budget_ton"]) - float(daily.get("real_spent_ton", 0)))
    bonus_left = max(0.0, float(cfg["bonus_daily_cap_city"]) / 1000.0 - float(daily.get("bonus_spent_ton", 0)))
    groups: Dict[str, Dict[str, float]] = {g: dict(v) for g, v in (daily.get("groups") or {}).items()}
    day_total = float(daily.get("bought_ton", 0) or 0)
    inv = await stock(db)
    gcache: Dict[str, str] = {}
    now = _now()

    q = {"status": "active", "is_bot": {"$ne": True}, "tutorial": {"$ne": True},
         "seller_id": {"$nin": ["BOT_ADMIN", CITY_MARKET_ID]}, "resource_type": {"$in": list(cfg["buy_resources"])}}
    from core.pricing import level0_price_ton
    sys_price_cache: Dict[str, float] = {}
    # one cycle may see many lots of the same seller: look each seller up once
    seller_cache: Dict[str, Any] = {}
    target_cache: Dict[str, str] = {}
    first_sale_cache: Dict[str, bool] = {}
    async def _first_sale(seller):
        if seller["id"] not in first_sale_cache:
            first_sale_cache[seller["id"]] = await _is_first_sale(db, seller)
        return first_sale_cache[seller["id"]]

    async for lst in db.market_listings.find(q, {"_id": 0}).sort("created_at", 1).limit(300):
        res = lst["resource_type"]
        price = float(lst.get("price_per_unit") or 0)
        base = _base_ton(res)
        created = _parse(lst.get("created_at"))
        if price <= 0 or base <= 0 or not created:
            skip("bad_lot")
            continue
        age_min = (now - created).total_seconds() / 60.0
        _sk = lst.get("seller_id") or lst.get("seller_email") or ""
        if _sk not in seller_cache:
            seller_cache[_sk] = await _seller_user(db, lst)
        seller = seller_cache[_sk]
        if not seller or not seller.get("id"):
            skip("no_seller")
            continue

        if res not in sys_price_cache:
            sys_price_cache[res] = await level0_price_ton(db, res)
        sys_price = sys_price_cache[res]
        if seller["id"] not in target_cache:
            target_cache[seller["id"]] = await payout_target(db, seller)
        target = target_cache[seller["id"]]               # real = owns a level 1+ business

        # level-0 sellers (bonus payout) — «Выкуп у новичков»
        newbie_ok = bool(cfg["newbie_buy_enabled"]) and target == "bonus"
        # 1) first sale ever, at most the system price (what level-0 lots use)
        newbie = newbie_ok and age_min >= cfg["newbie_delay_min"] \
            and price <= sys_price + 1e-12 and await _first_sale(seller)
        # 2) later lots of a level-0 seller: bought at their system price
        auto = newbie_ok and age_min >= cfg["auto_price_delay_min"] and price <= sys_price + 1e-12
        # 3) level 1+ sellers set their own price — «Выкуп за реальные деньги»:
        #    bought if priced at or below the City Market buy price of the resource
        buy_city, _sell_city = prices_city(cfg, res)
        aged = bool(cfg["real_buy_enabled"]) and target == "real" and age_min >= cfg["min_lot_age_min"] \
            and price <= buy_city / 1000.0 + 1e-12
        if not (newbie or auto or aged):
            skip("price_or_age")
            continue
        reason = "aged_lot" if aged else ("auto_price" if auto and not newbie else "newbie")

        units = int(lst.get("amount") or 0)
        if reason == "newbie":
            units = min(units, int(cfg["newbie_max_units"]))
        room = int(cfg["inventory_cap_units"]) - int((inv.get(res) or {}).get("amount", 0) or 0)
        units = min(units, room)
        if units <= 0:
            skip("stock_full")
            continue

        gid = await device_group(db, seller["id"], gcache)
        g = groups.get(gid, {"ton": 0.0, "units": 0})
        units = min(units, int(cfg["player_daily_cap_units"]) - int(g.get("units", 0)))
        units = min(units, int((float(cfg["player_daily_cap_ton"]) - float(g.get("ton", 0)) + 1e-9) // price))
        left = real_left if target == "real" else bonus_left
        if target == "bonus":
            newbie_left = float(cfg["per_newbie_daily_cap_city"]) / 1000.0 - float(g.get("bonus_ton", 0) or 0)
            left = min(left, max(0.0, newbie_left))
        units = min(units, int((left + 1e-9) // price))   # tolerance: 0.03 / 0.003 must give 10, not 9
        if units <= 0:
            skip("budget" if left < price else "player_cap")
            if target == "real" and real_left < price:
                await _inc_daily(db, {}, {"budget_exhausted": True})
            continue

        cost = round(units * price, 6)
        share_vol = day_total + cost
        if share_vol >= cfg["share_min_volume_ton"] and \
                (float(g.get("ton", 0)) + cost) / share_vol * 100.0 > cfg["max_player_share_pct"] and reason != "newbie":
            skip("player_share")
            await _inc_daily(db, {"skipped_share": 1})
            continue

        # Reserve atomically so a player buying the same lot at the same time
        # can never get units the City Market already took.
        from pymongo import ReturnDocument
        before = await db.market_listings.find_one_and_update(
            {"id": lst["id"], "status": "active", "amount": {"$gte": units}},
            {"$inc": {"amount": -units}}, return_document=ReturnDocument.BEFORE)
        if not before:
            skip("race")
            continue
        remaining = int(before["amount"]) - units
        set_ = {"total_price": round(remaining * price, 6)} if remaining > 0 else \
            {"status": "sold", "sold_at": now.isoformat(), "sold_via": "city_market"}
        await db.market_listings.update_one({"id": lst["id"]}, {"$set": set_})

        try:
            res_sale = await apply_sale(before, units, CITY_MARKET_NAME, "city_market",
                                        payout=target, skip_listing_update=True, city_market=True)
        except Exception as e:
            # give the units back to the player's lot if the seller-side failed
            await db.market_listings.update_one({"id": lst["id"]},
                                                {"$inc": {"amount": units}, "$set": {"status": "active"}})
            logger.error(f"city market: sale failed for lot {lst['id']}: {e}")
            skip("error")
            continue

        await _stock_add(db, res, units, cost)
        inv.setdefault(res, {"amount": 0})["amount"] = int((inv.get(res) or {}).get("amount", 0) or 0) + units
        trade = {"id": str(uuid.uuid4()), "side": "buy", "resource": res, "units": units,
                 "price_ton": price, "total_ton": cost, "user_id": seller["id"], "group": gid,
                 "listing_id": lst["id"], "payout": target,
                 "seller_received_ton": float((res_sale or {}).get("seller_received_ton", 0) or 0),
                 "reason": reason,
                 "lot_age_min": round(age_min, 1), "ts": now.isoformat(), "day": _day(now)}
        await db.mm_trades.insert_one(dict(trade))
        spend_key = "real_spent_ton" if target == "real" else "bonus_spent_ton"
        await _inc_daily(db, {spend_key: cost, "bought_ton": cost, "bought_units": units,
                              f"groups.{gid}.ton": cost, f"groups.{gid}.units": units,
                              **({f"groups.{gid}.bonus_ton": cost} if target == "bonus" else {})})
        if target == "real":
            real_left -= cost
            out["spent_real_ton"] += cost
        else:
            bonus_left -= cost
            out["spent_bonus_ton"] += cost
        groups[gid] = {"ton": float(g.get("ton", 0)) + cost, "units": int(g.get("units", 0)) + units,
                       "bonus_ton": float(g.get("bonus_ton", 0) or 0) + (cost if target == "bonus" else 0.0)}
        day_total += cost
        out["bought"] += 1
        out["newbie"] += 1 if reason == "newbie" else 0
        first_sale_cache[seller["id"]] = False
        out["auto_price"] = out.get("auto_price", 0) + (1 if reason == "auto_price" else 0)

        # the newbie quest «Sell a resource» counts this sale
        try:
            import quests as _q
            _q.fire_sale(seller["id"], None, units, unique=f"mm:{trade['id']}")
        except Exception:
            pass
    return out


# ───────────────────────────── sell side ─────────────────────────────
async def run_sell_side(db) -> Dict[str, Any]:
    cfg = await get_config(db)
    out = {"created": 0, "updated": 0, "cancelled": 0}
    inv = await stock(db)
    active = {l["resource_type"]: l async for l in db.market_listings.find(
        {"seller_id": CITY_MARKET_ID, "status": "active"}, {"_id": 0})}
    for res in set(cfg["sell_resources"]) | set(active):
        have = int((inv.get(res) or {}).get("amount", 0) or 0)
        # everything the city bought goes up for sale
        want = have if (cfg["sell_enabled"] and res in cfg["sell_resources"]) else 0
        price = round(prices_city(cfg, res)[1] / 1000.0, 6)
        lst = active.get(res)
        if want <= 0:
            if lst:
                await db.market_listings.update_one({"id": lst["id"]}, {"$set": {"status": "cancelled"}})
                out["cancelled"] += 1
            continue
        if lst:
            if int(lst.get("amount") or 0) != want or abs(float(lst.get("price_per_unit") or 0) - price) > 1e-12:
                await db.market_listings.update_one({"id": lst["id"]}, {"$set": {
                    "amount": want, "price_per_unit": price, "total_price": round(want * price, 6)}})
                out["updated"] += 1
            continue
        await db.market_listings.insert_one({
            "id": str(uuid.uuid4()), "resource_type": res, "amount": want, "price_per_unit": price,
            "total_price": round(want * price, 6), "seller_id": CITY_MARKET_ID,
            "seller_username": CITY_MARKET_NAME, "seller_email": None,
            "is_bot": True, "is_city_market": True, "status": "active", "created_at": _now().isoformat(),
        })
        out["created"] += 1
    return out


async def on_player_bought(db, listing: Dict[str, Any], units: int, total_cost: float, buyer_id: Optional[str]) -> None:
    """Hook from /market/buy: a player bought from the City Market."""
    if listing.get("seller_id") != CITY_MARKET_ID:
        return
    res = listing.get("resource_type")
    await _stock_remove(db, res, int(units))
    now = _now()
    await db.mm_trades.insert_one({"id": str(uuid.uuid4()), "side": "sell", "resource": res, "units": int(units),
                                   "price_ton": float(listing.get("price_per_unit") or 0),
                                   "total_ton": round(float(total_cost), 6), "user_id": buyer_id,
                                   "listing_id": listing.get("id"), "ts": now.isoformat(), "day": _day(now)})
    await _inc_daily(db, {"sold_ton": round(float(total_cost), 6), "sold_units": int(units)})


async def run_cycle(db, apply_sale: ApplySale) -> Dict[str, Any]:
    buy = await run_buy_side(db, apply_sale)
    sell = await run_sell_side(db)
    if buy.get("bought") or sell.get("created") or sell.get("cancelled"):
        logger.info(f"🏙 City Market cycle: buy={buy} sell={sell}")
    return {"buy": buy, "sell": sell}


# ───────────────────────────── analytics ─────────────────────────────
def _median_min(pairs: List[tuple]) -> Optional[float]:
    vals = [(b - a).total_seconds() / 60.0 for a, b in pairs if a and b and b >= a]
    return round(statistics.median(vals), 1) if vals else None


async def _time_to_sell(db, start: datetime, end: datetime) -> Dict[str, Any]:
    q = {"status": "sold", "is_bot": {"$ne": True}, "tutorial": {"$ne": True},
         "sold_at": {"$gte": start.isoformat(), "$lt": end.isoformat()}}
    to_players, to_city = [], []
    async for l in db.market_listings.find(q, {"_id": 0, "created_at": 1, "sold_at": 1, "sold_via": 1}):
        pair = (_parse(l.get("created_at")), _parse(l.get("sold_at")))
        (to_city if l.get("sold_via") == "city_market" else to_players).append(pair)
    allp = to_players + to_city
    return {"lots_sold": len(allp), "sold_to_players": len(to_players), "sold_to_city": len(to_city),
            "city_share_pct": round(100.0 * len(to_city) / len(allp), 1) if allp else None,
            "median_minutes": _median_min(allp), "median_minutes_players_only": _median_min(to_players)}


async def analytics(db, days: int = 7) -> Dict[str, Any]:
    from business_config import RESOURCE_TYPES
    cfg = await get_config(db)
    now = _now()
    start = now - timedelta(days=days)
    prev_start = start - timedelta(days=days)
    trades = await db.mm_trades.find({"ts": {"$gte": start.isoformat()}}, {"_id": 0}).to_list(100000)
    buys = [t for t in trades if t["side"] == "buy"]
    sells = [t for t in trades if t["side"] == "sell"]
    s = lambda rows, k: round(sum(float(r.get(k, 0) or 0) for r in rows), 6)  # noqa: E731

    inv = await stock(db)
    per_res: Dict[str, Dict[str, Any]] = {}
    for t in trades:
        r = per_res.setdefault(t["resource"], {"bought_units": 0, "bought_ton": 0.0, "sold_units": 0, "sold_ton": 0.0})
        side = "bought" if t["side"] == "buy" else "sold"
        r[f"{side}_units"] += int(t.get("units", 0))
        r[f"{side}_ton"] = round(r[f"{side}_ton"] + float(t.get("total_ton", 0)), 6)
    resources = []
    for res in sorted(set(per_res) | set(inv)):
        p = per_res.get(res, {"bought_units": 0, "bought_ton": 0.0, "sold_units": 0, "sold_ton": 0.0})
        have = int((inv.get(res) or {}).get("amount", 0) or 0)
        daily_sold = p["sold_units"] / max(1, days)
        resources.append({
            "resource": res, "name": (RESOURCE_TYPES.get(res) or {}).get("name_ru") or res, **p,
            "avg_buy_price_ton": round(p["bought_ton"] / p["bought_units"], 6) if p["bought_units"] else None,
            "avg_sell_price_ton": round(p["sold_ton"] / p["sold_units"], 6) if p["sold_units"] else None,
            "stock_units": have, "stock_value_ton": round(have * _base_ton(res), 6),
            "days_of_cover": round(have / daily_sold, 1) if daily_sold > 0 else None,
        })

    series = []
    for i in range(days - 1, -1, -1):
        d = _day(now - timedelta(days=i))
        dd = [t for t in trades if t.get("day") == d]
        series.append({"date": d,
                       "bought_ton": s([t for t in dd if t["side"] == "buy"], "total_ton"),
                       "sold_ton": s([t for t in dd if t["side"] == "sell"], "total_ton")})

    total_buy = s(buys, "total_ton")
    by_group: Dict[str, Dict[str, Any]] = {}
    for t in buys:
        g = by_group.setdefault(t.get("group") or t["user_id"], {"ton": 0.0, "units": 0, "users": set()})
        g["ton"] += float(t["total_ton"])
        g["units"] += int(t["units"])
        g["users"].add(t["user_id"])
    top = []
    for gid, g in sorted(by_group.items(), key=lambda kv: -kv[1]["ton"])[:10]:
        u = await db.users.find_one({"id": gid}, {"_id": 0, "username": 1, "email": 1}) or {}
        share = round(100.0 * g["ton"] / total_buy, 1) if total_buy else 0.0
        # same threshold as the buy side: the share rule only means something
        # once the day/period has real volume
        over_share = total_buy >= float(cfg["share_min_volume_ton"]) and share > cfg["max_player_share_pct"]
        top.append({"group": gid, "username": u.get("username") or u.get("email") or gid,
                    "accounts": len(g["users"]), "ton": round(g["ton"], 6), "units": g["units"],
                    "share_pct": share, "over_share": over_share,
                    "flag": over_share or len(g["users"]) > 1})

    today = await _daily(db)
    stock_value = round(sum(r["stock_value_ton"] for r in resources), 6)
    alerts = []
    if not cfg["newbie_buy_enabled"]:
        alerts.append({"level": "info", "code": "newbie_off", "text": "Выкуп у новичков выключен."})
    if not cfg["real_buy_enabled"]:
        alerts.append({"level": "info", "code": "real_off", "text": "Выкуп за реальные деньги выключен."})
    elif float(cfg["daily_budget_ton"]) <= 0:
        alerts.append({"level": "warning", "code": "no_budget",
                       "text": "Выкуп за реальные деньги включён, но дневной бюджет 0 — он ничего не купит."})
    if today.get("budget_exhausted"):
        alerts.append({"level": "warning", "code": "budget_exhausted", "text": "Дневной бюджет на сегодня исчерпан."})
    for t in top:
        if t["over_share"]:
            alerts.append({"level": "warning", "code": "player_share",
                           "text": f"Игрок {t['username']}: {t['share_pct']}% всех покупок рынка."})
    return {
        "period_days": days, "config": cfg,
        "totals": {
            "bought_units": sum(int(t["units"]) for t in buys), "bought_ton": total_buy,
            "bought_real_ton": s([t for t in buys if t.get("payout") == "real"], "total_ton"),
            "bought_bonus_ton": s([t for t in buys if t.get("payout") == "bonus"], "total_ton"),
            "sold_units": sum(int(t["units"]) for t in sells), "sold_ton": s(sells, "total_ton"),
            "net_cash_ton": round(s(sells, "total_ton") - total_buy, 6),
            "stock_value_ton": stock_value,
            "result_incl_stock_ton": round(s(sells, "total_ton") - total_buy + stock_value, 6),
            "unique_sellers": len({t["user_id"] for t in buys}),
            "unique_buyers": len({t["user_id"] for t in sells if t.get("user_id")}),
            "newbie_sales": sum(1 for t in buys if t.get("reason") == "newbie"),
            "auto_price_sales": sum(1 for t in buys if t.get("reason") == "auto_price"),
            "aged_lot_sales": sum(1 for t in buys if t.get("reason") == "aged_lot"),
            "newbies_helped": len({t["user_id"] for t in buys if t.get("reason") == "newbie"}),
        },
        "today": {
            "budget_ton": float(cfg["daily_budget_ton"]), "real_spent_ton": round(float(today.get("real_spent_ton", 0)), 6),
            "bonus_cap_ton": float(cfg["bonus_daily_cap_city"]) / 1000.0,
            "bonus_spent_ton": round(float(today.get("bonus_spent_ton", 0)), 6),
            "skipped_share": int(today.get("skipped_share", 0) or 0),
            "bought_ton": round(float(today.get("bought_ton", 0) or 0), 6),
            "bought_units": int(today.get("bought_units", 0) or 0),
            "sold_ton": round(float(today.get("sold_ton", 0) or 0), 6),
            "sold_units": int(today.get("sold_units", 0) or 0),
        },
        "liquidity": {"current": await _time_to_sell(db, start, now),
                      "previous": await _time_to_sell(db, prev_start, start)},
        "resources": resources, "series": series, "top_sellers": top, "alerts": alerts,
    }


# ───────────────────────────── API ─────────────────────────────
def create_market_maker_router(db, get_current_admin, apply_sale: ApplySale) -> APIRouter:
    router = APIRouter(prefix="/api/admin/market-maker", tags=["market-maker"])

    @router.get("/config")
    async def r_get_config(_=Depends(get_current_admin)):
        return await get_config(db)

    @router.put("/config")
    async def r_put_config(patch: Dict[str, Any], _=Depends(get_current_admin)):
        cfg = await save_config(db, patch)
        await run_sell_side(db)              # apply on/off and prices to the lots right away
        return cfg

    @router.get("/catalog")
    async def r_catalog(_=Depends(get_current_admin)):
        """All resource types with tier, table price and the level-0 system price."""
        from business_config import RESOURCE_TYPES
        from core.pricing import level0_price_ton
        cfg = await get_config(db)
        rows = []
        for rid, m in RESOURCE_TYPES.items():
            rows.append({
                "id": rid, "name": m.get("name_ru") or m.get("name_en") or rid, "icon": m.get("icon", ""),
                "tier": int(m.get("tier", 1) or 1),
                "base_price_city": float(m.get("base_price", 0) or 0),
                "system_price_city": round(await level0_price_ton(db, rid) * 1000, 4),
                "buy": rid in cfg["buy_resources"], "sell": rid in cfg["sell_resources"],
                "auto_buy_city": round(base_city(rid) * (100 - float(cfg["buy_discount_pct"])) / 100.0, 4),
                "auto_sell_city": round(base_city(rid) * (100 + float(cfg["sell_markup_pct"])) / 100.0, 4),
                "buy_city": prices_city(cfg, rid)[0], "sell_city": prices_city(cfg, rid)[1],
                "override": (cfg.get(OVERRIDES_KEY) or {}).get(rid) or {},
            })
        rows.sort(key=lambda r: (r["tier"], r["name"]))
        return {"resources": rows}

    @router.get("/analytics")
    async def r_analytics(days: int = 7, _=Depends(get_current_admin)):
        if days < 1 or days > 90:
            raise HTTPException(status_code=400, detail="days must be 1..90")
        return await analytics(db, days)

    @router.get("/trades")
    async def r_trades(limit: int = 50, side: Optional[str] = None, _=Depends(get_current_admin)):
        q = {"side": side} if side in ("buy", "sell") else {}
        rows = await db.mm_trades.find(q, {"_id": 0}).sort("ts", -1).limit(max(1, min(limit, 500))).to_list(500)
        return {"trades": rows}

    @router.post("/run")
    async def r_run(_=Depends(get_current_admin)):
        return await run_cycle(db, apply_sale)

    return router


def create_city_prices_router(db) -> APIRouter:
    """Public: the City Market («государство») prices of every resource — what it pays (buy) and asks (sell)."""
    router = APIRouter(prefix="/api/city-market", tags=["city-market"])

    @router.get("/prices")
    async def r_prices():
        from business_config import RESOURCE_TYPES
        cfg = await get_config(db)
        out = {}
        for rid in RESOURCE_TYPES:
            if rid.endswith("_tutorial"):
                continue
            buy, sell = prices_city(cfg, rid)
            out[rid] = {"buy_city": buy, "sell_city": sell, "buys": rid in cfg["buy_resources"],
                        "base_city": base_city(rid)}
        return {"prices": out}

    return router
