"""
B2B Partners subsystem.

Admins register B2B partners (by Telegram @username) and set two commission
rates per partner:
  - sales_percent : % of every LAND SALE made to users who joined via the
                    partner's referral link (?start=p_<code>).
  - yield_percent : % of the PROFIT earned by the partner's active referrals
                    (credited on referral trade/earn events).

Earnings accrue to the partner record (`b2b_partners.earn_total`) and to an
append-only ledger (`b2b_earnings`) used for time-windowed stats. The same
stats power the partner's in-bot panel.
"""
import uuid
import secrets
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

logger = logging.getLogger(__name__)


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


def _clean_username(u: str) -> str:
    return (u or "").strip().lstrip("@")


# --------------------------------------------------------------------------
# Helpers used by the game backend (land-sale / yield hooks, registration tag)
# --------------------------------------------------------------------------
async def find_partner_by_code(db, code: str):
    if not code:
        return None
    return await db.b2b_partners.find_one({"partner_code": str(code).strip()}, {"_id": 0})


async def tag_user_with_partner(db, user_id: str, referral_code: str) -> bool:
    """If `referral_code` looks like a B2B partner code (`p_<code>` or `<code>`),
    attach the partner to the user. Returns True when a partner was attached."""
    if not user_id or not referral_code:
        return False
    code = str(referral_code).strip()
    if code.startswith("p_"):
        code = code[2:]
    partner = await find_partner_by_code(db, code)
    if not partner:
        return False
    await db.users.update_one(
        {"id": user_id},
        {"$set": {
            "b2b_partner_id": partner["id"],
            "b2b_partner_code": partner["partner_code"],
            "b2b_joined_at": _iso(_now()),
        }},
    )
    return True


async def _credit(db, partner_id: str, amount: float, kind: str, user_id: str = None):
    if not partner_id or not amount or amount <= 0:
        return 0.0
    amount = round(float(amount), 8)
    await db.b2b_partners.update_one(
        {"id": partner_id}, {"$inc": {"earn_total": amount}}
    )
    await db.b2b_earnings.insert_one({
        "id": str(uuid.uuid4()),
        "partner_id": partner_id,
        "amount": amount,
        "kind": kind,
        "user_id": user_id,
        "created_at": _iso(_now()),
    })
    return amount


async def credit_land_sale(db, buyer_user_id: str, sale_amount: float) -> float:
    """Credit the buyer's B2B partner `sales_percent` of a land sale. No-op if
    the buyer has no partner. Returns the credited TON amount."""
    try:
        if not buyer_user_id or not sale_amount or sale_amount <= 0:
            return 0.0
        user = await db.users.find_one({"id": buyer_user_id}, {"_id": 0, "b2b_partner_id": 1})
        pid = (user or {}).get("b2b_partner_id")
        if not pid:
            return 0.0
        partner = await db.b2b_partners.find_one({"id": pid}, {"_id": 0, "sales_percent": 1})
        if not partner:
            return 0.0
        pct = float(partner.get("sales_percent") or 0)
        if pct <= 0:
            return 0.0
        return await _credit(db, pid, sale_amount * pct / 100.0, "land_sale", buyer_user_id)
    except Exception as e:
        logger.warning(f"credit_land_sale failed: {e}")
        return 0.0


async def credit_yield(db, ref_user_id: str, profit_amount: float) -> float:
    """Credit the referral's B2B partner `yield_percent` of a profit event."""
    try:
        if not ref_user_id or not profit_amount or profit_amount <= 0:
            return 0.0
        user = await db.users.find_one({"id": ref_user_id}, {"_id": 0, "b2b_partner_id": 1})
        pid = (user or {}).get("b2b_partner_id")
        if not pid:
            return 0.0
        partner = await db.b2b_partners.find_one({"id": pid}, {"_id": 0, "yield_percent": 1})
        if not partner:
            return 0.0
        pct = float(partner.get("yield_percent") or 0)
        if pct <= 0:
            return 0.0
        return await _credit(db, pid, profit_amount * pct / 100.0, "yield", ref_user_id)
    except Exception as e:
        logger.warning(f"credit_yield failed: {e}")
        return 0.0


async def _sum_earn(db, partner_id: str, since_iso: str = None, kind: str = None) -> float:
    match = {"partner_id": partner_id}
    if since_iso:
        match["created_at"] = {"$gte": since_iso}
    if kind:
        match["kind"] = kind
    cur = db.b2b_earnings.aggregate([
        {"$match": match},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
    ])
    docs = await cur.to_list(length=1)
    return round(float(docs[0]["total"]), 8) if docs else 0.0


async def compute_partner_stats(db, partner: dict) -> dict:
    pid = partner["id"]
    now = _now()
    iso_24h = _iso(now - timedelta(hours=24))
    iso_7d = _iso(now - timedelta(days=7))
    iso_30d = _iso(now - timedelta(days=30))
    iso_today = _iso(now.replace(hour=0, minute=0, second=0, microsecond=0))

    total_users = await db.users.count_documents({"b2b_partner_id": pid})
    users_24h = await db.users.count_documents({"b2b_partner_id": pid, "b2b_joined_at": {"$gte": iso_24h}})
    users_7d = await db.users.count_documents({"b2b_partner_id": pid, "b2b_joined_at": {"$gte": iso_7d}})
    users_30d = await db.users.count_documents({"b2b_partner_id": pid, "b2b_joined_at": {"$gte": iso_30d}})
    active_users_7d = await db.users.count_documents({"b2b_partner_id": pid, "last_login": {"$gte": iso_7d}})

    earn_today = await _sum_earn(db, pid, iso_today)
    earn_7d = await _sum_earn(db, pid, iso_7d)
    earn_30d = await _sum_earn(db, pid, iso_30d)
    earn_total = round(float(partner.get("earn_total") or 0), 8)

    return {
        "total_users": total_users,
        "active_users_7d": active_users_7d,
        "users_24h": users_24h,
        "users_7d": users_7d,
        "users_30d": users_30d,
        "earn_today": earn_today,
        "earn_7d": earn_7d,
        "earn_30d": earn_30d,
        "earn_total": earn_total,
    }


def build_partner_panel_text(partner: dict, stats: dict, bot_username: str = "gramcity_games_bot") -> str:
    code = partner.get("partner_code", "")
    return (
        f"🤝 **Панель B2B-Партнера: {code}**\n"
        f"🔗 **Ваша реферальная ссылка:** `https://t.me/{bot_username}?start=p_{code}`\n\n"
        f"📊 **Аудитория и Активность:**\n"
        f"• Всего переходов/игроков: **{stats['total_users']}**\n"
        f"• Активных (за 7 дней): **{stats['active_users_7d']}**\n\n"
        f"👥 **Новые игроки:**\n"
        f"• За 24 часа: **+{stats['users_24h']}**\n"
        f"• За неделю: **+{stats['users_7d']}**\n"
        f"• За месяц: **+{stats['users_30d']}**\n\n"
        f"💰 **Ваш доход (RevShare {partner.get('sales_percent', 0)}% + "
        f"Yield {partner.get('yield_percent', 0)}%):**\n"
        f"• За сегодня: **{stats['earn_today']} TON**\n"
        f"• За неделю: **{stats['earn_7d']} TON**\n"
        f"• За месяц: **{stats['earn_30d']} TON**\n"
        f"💎 **Всего заработано: {stats['earn_total']} TON**\n\n"
        f"🆔 Ваш Partner ID: `{partner.get('id', '')}`"
    )


async def get_partner_for_telegram(db, telegram_user_id=None, username=None):
    """Match a Telegram user to a B2B partner (by telegram_user_id or @username)."""
    if telegram_user_id:
        p = await db.b2b_partners.find_one({"telegram_user_id": str(telegram_user_id)}, {"_id": 0})
        if p:
            return p
    uname = _clean_username(username)
    if uname:
        return await db.b2b_partners.find_one(
            {"username": {"$regex": f"^{uname}$", "$options": "i"}}, {"_id": 0}
        )
    return None


async def is_user_b2b_partner(db, user: dict) -> bool:
    """Return True if the given user document corresponds to a B2B partner
    (matched by telegram user id or username)."""
    if not user:
        return False
    if user.get("b2b_is_partner"):
        return True
    tg_id = user.get("telegram_chat_id") or user.get("telegram_user_id")
    uname = _clean_username(user.get("telegram_username") or user.get("username") or "")
    p = await get_partner_for_telegram(db, telegram_user_id=tg_id, username=uname)
    return p is not None


async def flag_partner_user(db, partner: dict) -> Optional[str]:
    """Find the user record that belongs to this partner (by tg_user_id or
    username) and set ``b2b_is_partner: True`` so leaderboards/rallies can
    exclude the partner from competitive lists. Returns the user id or None."""
    if not partner:
        return None
    filters = []
    tg = partner.get("telegram_user_id")
    if tg:
        filters.append({"telegram_chat_id": str(tg)})
    uname = _clean_username(partner.get("username") or "")
    if uname:
        filters.append({"telegram_username": {"$regex": f"^{uname}$", "$options": "i"}})
        filters.append({"username": {"$regex": f"^{uname}$", "$options": "i"}})
    if not filters:
        return None
    user = await db.users.find_one({"$or": filters}, {"_id": 0, "id": 1})
    if not user:
        return None
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"b2b_is_partner": True, "b2b_partner_ref_id": partner.get("id")}},
    )
    # Drop the referral rally leaderboard cache so the partner disappears
    # from /api/promo/referral-rally/leaderboard immediately (TTL is 60s).
    try:
        from promo_service import invalidate_leaderboard_cache
        invalidate_leaderboard_cache()
    except Exception:
        pass
    return user.get("id")


async def unflag_partner_user(db, partner_id: str):
    """Remove the b2b_is_partner flag when a partner is deleted."""
    if not partner_id:
        return
    await db.users.update_many(
        {"b2b_partner_ref_id": partner_id},
        {"$unset": {"b2b_is_partner": "", "b2b_partner_ref_id": ""}},
    )
    try:
        from promo_service import invalidate_leaderboard_cache
        invalidate_leaderboard_cache()
    except Exception:
        pass


# --------------------------------------------------------------------------
# Admin API
# --------------------------------------------------------------------------
class PartnerCreate(BaseModel):
    username: str
    sales_percent: float = 0.0
    yield_percent: float = 0.0
    telegram_user_id: Optional[str] = None


class PartnerUpdate(BaseModel):
    username: Optional[str] = None
    sales_percent: Optional[float] = None
    yield_percent: Optional[float] = None
    telegram_user_id: Optional[str] = None


def _validate_pct(v, field):
    if v is None:
        return None
    v = float(v)
    if v < 0 or v > 100:
        raise HTTPException(status_code=400, detail=f"{field} должен быть в диапазоне 0..100")
    return v


def create_b2b_router(db, admin_dependency):
    router = APIRouter(prefix="/api/admin/b2b", tags=["b2b-partners"])

    @router.get("/partners")
    async def list_partners(admin=Depends(admin_dependency)):
        partners = await db.b2b_partners.find({}, {"_id": 0}).sort("created_at", -1).to_list(length=1000)
        out = []
        for p in partners:
            stats = await compute_partner_stats(db, p)
            out.append({
                "partner_id": p["id"],
                "partner_code": p["partner_code"],
                "username": p.get("username", ""),
                "telegram_user_id": p.get("telegram_user_id"),
                "sales_percent": p.get("sales_percent", 0),
                "yield_percent": p.get("yield_percent", 0),
                "referral_link": f"https://t.me/gramcity_games_bot?start=p_{p['partner_code']}",
                "created_at": p.get("created_at"),
                "stats": stats,
            })
        return {"partners": out}

    @router.post("/partners")
    async def create_partner(data: PartnerCreate, admin=Depends(admin_dependency)):
        username = _clean_username(data.username)
        if not username:
            raise HTTPException(status_code=400, detail="Укажите username партнёра")
        _validate_pct(data.sales_percent, "sales_percent")
        _validate_pct(data.yield_percent, "yield_percent")
        # Unique-ish partner code
        code = secrets.token_hex(4)
        while await db.b2b_partners.find_one({"partner_code": code}):
            code = secrets.token_hex(4)
        doc = {
            "id": str(uuid.uuid4()),
            "partner_code": code,
            "username": username,
            "telegram_user_id": (str(data.telegram_user_id).strip() if data.telegram_user_id else None),
            "sales_percent": round(float(data.sales_percent or 0), 4),
            "yield_percent": round(float(data.yield_percent or 0), 4),
            "earn_total": 0.0,
            "created_at": _iso(_now()),
        }
        await db.b2b_partners.insert_one(doc.copy())
        # Flag matching user as a B2B partner so they don't show up in
        # leaderboard / referral rally lists.
        try:
            await flag_partner_user(db, doc)
        except Exception as _e:
            logger.debug(f"flag_partner_user (create) failed: {_e}")
        return {"status": "ok", "partner_id": doc["id"], "partner_code": code,
                "referral_link": f"https://t.me/gramcity_games_bot?start=p_{code}"}

    @router.patch("/partners/{partner_id}")
    async def update_partner(partner_id: str, data: PartnerUpdate, admin=Depends(admin_dependency)):
        updates = {}
        if data.username is not None:
            u = _clean_username(data.username)
            if not u:
                raise HTTPException(status_code=400, detail="username не может быть пустым")
            updates["username"] = u
        if data.sales_percent is not None:
            updates["sales_percent"] = round(_validate_pct(data.sales_percent, "sales_percent"), 4)
        if data.yield_percent is not None:
            updates["yield_percent"] = round(_validate_pct(data.yield_percent, "yield_percent"), 4)
        if data.telegram_user_id is not None:
            updates["telegram_user_id"] = str(data.telegram_user_id).strip() or None
        if not updates:
            raise HTTPException(status_code=400, detail="Нет полей для обновления")
        res = await db.b2b_partners.update_one({"id": partner_id}, {"$set": updates})
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Партнёр не найден")
        # If username/telegram_user_id changed, re-flag the matching user (may
        # be a different one now).
        if "username" in updates or "telegram_user_id" in updates:
            try:
                await unflag_partner_user(db, partner_id)
                p_now = await db.b2b_partners.find_one({"id": partner_id}, {"_id": 0})
                if p_now:
                    await flag_partner_user(db, p_now)
            except Exception as _e:
                logger.debug(f"re-flag partner user (patch) failed: {_e}")
        return {"status": "ok"}

    @router.delete("/partners/{partner_id}")
    async def delete_partner(partner_id: str, admin=Depends(admin_dependency)):
        res = await db.b2b_partners.delete_one({"id": partner_id})
        if res.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Партнёр не найден")
        # Detach users (keep their history but drop the link)
        await db.users.update_many(
            {"b2b_partner_id": partner_id},
            {"$unset": {"b2b_partner_id": "", "b2b_partner_code": ""}},
        )
        # Also remove the b2b_is_partner flag from the ex-partner's user record
        try:
            await unflag_partner_user(db, partner_id)
        except Exception as _e:
            logger.debug(f"unflag_partner_user (delete) failed: {_e}")
        return {"status": "ok"}

    @router.get("/partners/{partner_id}/panel")
    async def partner_panel(partner_id: str, admin=Depends(admin_dependency)):
        p = await db.b2b_partners.find_one({"id": partner_id}, {"_id": 0})
        if not p:
            raise HTTPException(status_code=404, detail="Партнёр не найден")
        stats = await compute_partner_stats(db, p)
        return {"panel_text": build_partner_panel_text(p, stats), "stats": stats}

    return router
