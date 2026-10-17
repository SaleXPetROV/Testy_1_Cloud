"""
Promo / Referral Rally service.

Handles:
- MSK date/time helpers (fixed +03:00 offset per spec)
- Active campaign lookup & CRUD helpers
- Aggregate leaderboard (referrals by total or active count)
- 1.5 TON activation bonus payment hook (only while campaign is active)
- Campaign freeze (winners snapshot)

Everything is designed to work with the existing Motor MongoDB driver
attached to `core.database.db`.
"""
from __future__ import annotations

import logging
import uuid
import time
from datetime import datetime, timezone, timedelta, date
from typing import Optional, List, Dict, Any, Tuple

logger = logging.getLogger(__name__)

# MSK is UTC+3, fixed year-round (Russia has no DST).
MSK_TZ = timezone(timedelta(hours=3))

CAMPAIGN_TYPE = "referral_rally"
COLLECTION = "promo_campaigns"

# In-process cache for leaderboard results.
# Key: (campaign_id, sort, offset, limit) -> {"ts": epoch, "data": {...}}
_leaderboard_cache: dict = {}
_LEADERBOARD_TTL = 60.0  # seconds — per spec, refresh every minute


# ==================== TIME HELPERS ====================

def now_msk() -> datetime:
    """Current time in MSK timezone (UTC+3)."""
    return datetime.now(MSK_TZ)


def to_msk(dt) -> datetime:
    """Coerce a datetime or ISO-string to an aware MSK datetime."""
    if isinstance(dt, str):
        # Handle Z suffix
        s = dt.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return now_msk()
    if dt.tzinfo is None:
        # Assume UTC if naive
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(MSK_TZ)


def msk_today_str() -> str:
    """Current date in MSK as YYYY-MM-DD (used for daily modal cooldown)."""
    return now_msk().date().isoformat()


# ==================== PRESALE SORT SWITCH ====================
# Before the presale the referral leaderboard (and the promo announcement /
# top-3) is ordered by TOTAL invited referrals ("по количеству"). From the
# presale onward — until the campaign ends — it is ordered by ACTIVE referrals.
PRESALE_MSK = datetime(2026, 7, 21, 15, 0, 0, tzinfo=MSK_TZ)


def is_before_presale() -> bool:
    """True while we are still before the presale moment (MSK)."""
    return now_msk() < PRESALE_MSK


def current_leaderboard_sort() -> str:
    """Sort mode for the referral leaderboard and every campaign broadcast:
    always ranks users by the number of ACTIVE referrals they brought in
    (i.e. referred users who already own at least one plot). Invitees who
    haven't activated yet do not count towards the rank — only real,
    game-participating referrals do. The presale flip-flop that used to
    switch this to `total` before 21 Jul 2026 has been removed per product
    request: the announcement must always reflect the number of active
    referrals so the placings and the "no active referrals yet" message
    stay consistent."""
    return "active"


# ==================== CAMPAIGN HELPERS ====================

async def get_active_campaign(db) -> Optional[Dict[str, Any]]:
    """Return the active referral_rally campaign or None."""
    doc = await db[COLLECTION].find_one(
        {"type": CAMPAIGN_TYPE, "status": "active"},
        {"_id": 0},
    )
    return doc


async def get_recent_finished_campaign(db, days: int = 7) -> Optional[Dict[str, Any]]:
    """Return the most recent finished campaign whose frozen_at is within `days`."""
    cutoff = now_msk() - timedelta(days=days)
    docs = await db[COLLECTION].find(
        {"type": CAMPAIGN_TYPE, "status": "finished"},
        {"_id": 0},
    ).sort("frozen_at", -1).limit(1).to_list(1)
    if not docs:
        return None
    doc = docs[0]
    frozen_at = doc.get("frozen_at")
    if not frozen_at:
        return None
    try:
        fa = to_msk(frozen_at)
        if fa >= cutoff:
            return doc
    except Exception:
        return None
    return None


async def get_campaign_history(db, limit: int = 50) -> List[Dict[str, Any]]:
    """All campaigns, most recent first (for admin history tab)."""
    docs = await db[COLLECTION].find(
        {"type": CAMPAIGN_TYPE},
        {"_id": 0},
    ).sort("created_at", -1).limit(limit).to_list(limit)
    return docs


async def create_campaign(
    db,
    admin_id: str,
    ends_at_iso_msk: str,
    prizes_ton: List[float],
    per_active_ton: float = 1.5,
) -> Dict[str, Any]:
    """Create a new active campaign. Only one can be active at a time."""
    existing = await get_active_campaign(db)
    if existing:
        raise ValueError("Активная акция уже существует")

    # Coerce ends_at to MSK (input may be ISO with/without tz)
    ends_at_msk = to_msk(ends_at_iso_msk)
    now = now_msk()
    if ends_at_msk <= now:
        raise ValueError("Дата окончания должна быть в будущем")

    # Normalise prizes to a list of 3 floats (top-3).
    prz = list(prizes_ton) if prizes_ton else [100.0, 50.0, 20.0]
    while len(prz) < 3:
        prz.append(0.0)
    prz = [float(p) for p in prz[:3]]

    campaign = {
        "id": str(uuid.uuid4()),
        "type": CAMPAIGN_TYPE,
        "status": "active",
        "starts_at": now.isoformat(),
        "ends_at": ends_at_msk.isoformat(),
        "frozen_at": None,
        "config": {
            "prizes_ton": prz,
            "per_active_ton": float(per_active_ton),
        },
        "winners": [],
        "created_by": admin_id,
        "created_at": now.isoformat(),
    }
    await db[COLLECTION].insert_one(dict(campaign))
    # New campaign starts — force everyone to see the modal at least once today
    try:
        await db.users.update_many({}, {"$unset": {"promo_last_seen_date_msk": ""}})
    except Exception as _e:
        logger.warning(f"reset promo_last_seen_date_msk failed: {_e}")
    _invalidate_leaderboard_cache()
    logger.info(f"📢 Referral rally created (id={campaign['id']}, ends_at={ends_at_msk.isoformat()})")
    return campaign


async def cancel_campaign(db, campaign_id: str, admin_id: str) -> bool:
    """Cancel an active campaign without picking winners."""
    now = now_msk()
    res = await db[COLLECTION].update_one(
        {"id": campaign_id, "status": "active"},
        {"$set": {
            "status": "cancelled",
            "frozen_at": None,
            "cancelled_at": now.isoformat(),
            "cancelled_by": admin_id,
        }},
    )
    _invalidate_leaderboard_cache()
    return res.modified_count > 0


# ==================== LEADERBOARD AGGREGATE ====================

async def compute_referrals_leaderboard(
    db,
    sort: str = "active",
    offset: int = 0,
    limit: int = 100,
    include_partners: bool = False,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Compute referral leaderboard over ALL registered users.
    Users with no referrals appear with total=0, active=0.
    sort: 'active' (default) or 'total'.
    include_partners: when True, B2B partner referrers are INCLUDED (used by the
      admin "Данные → Рефералы" data section — a partner is still a project user
      and their referrals must be counted). When False (default, referral rally
      competition) partners are excluded.
    Returns (rows, total_users_count).
    """
    sort_field = "active" if sort == "active" else "total"

    base_match = {} if include_partners else {"b2b_is_partner": {"$ne": True}}

    pipeline = [
        {"$match": base_match},
        # Left-join: find every user attributed to this user via ANY of the
        # referral fields (referrerId is the canonical one, but Telegram
        # signups historically stored only ref_by / partner_ref_id).
        {"$lookup": {
            "from": "users",
            "let": {"uid": "$id"},
            "pipeline": [
                {"$match": {"$expr": {"$or": [
                    {"$eq": ["$referrerId", "$$uid"]},
                    {"$eq": ["$partner_ref_id", "$$uid"]},
                    {"$eq": ["$ref_by", "$$uid"]},
                ]}}},
                {"$project": {"_id": 0, "plots_owned": 1}},
            ],
            "as": "_refs",
        }},
        {"$addFields": {
            # Admin override takes precedence over the real computed count.
            # Fields `referral_override_total` / `referral_override_active`
            # are set via POST /api/admin/referrals/override.
            "total": {
                "$ifNull": [
                    "$referral_override_total",
                    {"$size": "$_refs"},
                ]
            },
            "active": {
                "$ifNull": [
                    "$referral_override_active",
                    {"$size": {
                        "$filter": {
                            "input": "$_refs",
                            "as": "r",
                            "cond": {"$gt": [{"$size": {"$ifNull": ["$$r.plots_owned", []]}}, 0]},
                        }
                    }},
                ]
            },
        }},
        {"$sort": {sort_field: -1, "total": -1, "active": -1, "id": 1}},
        {"$skip": int(max(0, offset))},
        {"$limit": int(max(1, min(limit, 500)))},
        {"$project": {
            "_id": 0,
            "user_id": "$id",
            "username": 1,
            "avatar": 1,
            "created_at": 1,
            "wallet_address": 1,
            "total": 1,
            "active": 1,
        }},
    ]

    rows = await db.users.aggregate(pipeline).to_list(500)
    for i, r in enumerate(rows):
        r["rank"] = int(offset) + i + 1

    total_count = await db.users.count_documents(base_match)
    return rows, total_count


async def get_leaderboard_cached(
    db,
    sort: str = "active",
    offset: int = 0,
    limit: int = 100,
    campaign_id: str = "_global_",
) -> Tuple[List[Dict[str, Any]], int]:
    """Cached leaderboard (per-process, TTL=60s)."""
    key = (campaign_id, sort, int(offset), int(limit))
    entry = _leaderboard_cache.get(key)
    now = time.time()
    if entry and (now - entry["ts"] < _LEADERBOARD_TTL):
        return entry["rows"], entry["total"]

    rows, total = await compute_referrals_leaderboard(db, sort=sort, offset=offset, limit=limit)
    _leaderboard_cache[key] = {"ts": now, "rows": rows, "total": total}
    return rows, total


def _invalidate_leaderboard_cache():
    _leaderboard_cache.clear()


# Public alias for callers outside this module (e.g. b2b_partners).
def invalidate_leaderboard_cache():
    _invalidate_leaderboard_cache()


async def compute_user_referral_stats(db, user_id: str, sort: str = "active") -> Dict[str, Any]:
    """
    Return {rank, active, total} for the given user among ALL users.
    Rank is 1-based (users are sorted by score desc; ties broken by id).
    Even users without any referrals get a rank (they'll be at the bottom).
    """
    # Compute my score first
    my = await db.users.aggregate([
        {"$match": {"id": user_id}},
        {"$lookup": {
            "from": "users",
            "let": {"uid": "$id"},
            "pipeline": [
                {"$match": {"$expr": {"$eq": ["$referrerId", "$$uid"]}}},
                {"$project": {"_id": 0, "plots_owned": 1}},
            ],
            "as": "_refs",
        }},
        {"$project": {
            "_id": 0,
            "total": {
                "$ifNull": [
                    "$referral_override_total",
                    {"$size": "$_refs"},
                ]
            },
            "active": {
                "$ifNull": [
                    "$referral_override_active",
                    {"$size": {"$filter": {
                        "input": "$_refs", "as": "r",
                        "cond": {"$gt": [{"$size": {"$ifNull": ["$$r.plots_owned", []]}}, 0]},
                    }}},
                ]
            },
        }},
    ]).to_list(1)

    if not my:
        return {"rank": None, "active": 0, "total": 0}

    active = my[0]["active"]
    total = my[0]["total"]
    my_score = active if sort == "active" else total

    # Count users with a strictly better score.
    sort_field = "active" if sort == "active" else "total"
    better_pipeline = [
        {"$lookup": {
            "from": "users",
            "let": {"uid": "$id"},
            "pipeline": [
                {"$match": {"$expr": {"$eq": ["$referrerId", "$$uid"]}}},
                {"$project": {"_id": 0, "plots_owned": 1}},
            ],
            "as": "_refs",
        }},
        {"$addFields": {
            "total": {
                "$ifNull": [
                    "$referral_override_total",
                    {"$size": "$_refs"},
                ]
            },
            "active": {
                "$ifNull": [
                    "$referral_override_active",
                    {"$size": {"$filter": {
                        "input": "$_refs", "as": "r",
                        "cond": {"$gt": [{"$size": {"$ifNull": ["$$r.plots_owned", []]}}, 0]},
                    }}},
                ]
            },
        }},
        {"$match": {sort_field: {"$gt": my_score}}},
        {"$count": "n"},
    ]
    b = await db.users.aggregate(better_pipeline).to_list(1)
    better = b[0]["n"] if b else 0
    return {"rank": better + 1, "active": active, "total": total}


# ==================== ACTIVATION BONUS HOOK ====================

async def maybe_pay_activation_bonus(db, buyer_user_id: str) -> None:
    """
    Called after a user has just purchased their FIRST plot.
    If:
      - There is an active referral_rally campaign
      - The user has a referrerId
      - Bonus has not already been paid for this user
    then credit 1.5 TON (or configured amount) to the referrer.

    Idempotency: uses `referral_activation_paid` boolean on the referred user.
    """
    try:
        campaign = await get_active_campaign(db)
        if not campaign:
            return  # Bonus only during active campaign (Variant A)

        user_doc = await db.users.find_one(
            {"$or": [
                {"id": buyer_user_id},
                {"wallet_address": buyer_user_id},
                {"email": buyer_user_id},
            ]},
            {"_id": 0, "id": 1, "username": 1, "referrerId": 1,
             "plots_owned": 1, "referral_activation_paid": 1, "wallet_address": 1},
        )
        if not user_doc:
            return
        # Always operate on the canonical `id`. Different purchase endpoints
        # historically passed different identifier forms (uuid / wallet / email);
        # if the idempotency flag were written under one key and read under
        # another, the referrer could be paid MORE THAN ONCE for the same
        # invitee. Resolving to the canonical doc kills that race.
        canonical_id = user_doc.get("id")
        if not canonical_id:
            return
        if user_doc.get("referral_activation_paid"):
            return  # Already paid
        referrer_id = user_doc.get("referrerId")
        if not referrer_id:
            return
        # Point 5: if the referrer is a B2B partner (their ref link became a
        # partner link), the normal 1.5 TON activation bonus does NOT apply —
        # the partner is compensated by the admin-configured program terms.
        try:
            from routes.partner_programs import is_partner_referrer
            if await is_partner_referrer(db, referrer_id):
                return
        except Exception as _e:
            logger.debug(f"partner referrer check (activation bonus) failed: {_e}")
        # First plot means plots_owned length >= 1 (just pushed)
        if len(user_doc.get("plots_owned") or []) < 1:
            return

        # Belt-and-suspenders: even if the `referral_activation_paid` flag was
        # cleared by a data migration or manual DB edit, an existing activation
        # bonus transaction proves the reward was ALREADY paid for this invitee.
        # Never pay a second time.
        already_tx = await db.transactions.find_one(
            {"tx_type": "referral_activation_bonus", "referred_user_id": canonical_id},
            {"_id": 1},
        )
        if already_tx:
            await db.users.update_one(
                {"id": canonical_id},
                {"$set": {"referral_activation_paid": True}},
            )
            return

        bonus = float(campaign.get("config", {}).get("per_active_ton", 1.5))

        # Mark as paid FIRST (atomic idempotency guard, race-safe). If a
        # concurrent purchase already claimed it, modified_count is 0 → bail out
        # BEFORE crediting so the referrer is credited exactly once.
        upd = await db.users.update_one(
            {"id": canonical_id, "referral_activation_paid": {"$ne": True}},
            {"$set": {
                "referral_activation_paid": True,
                "referral_activation_paid_at": now_msk().isoformat(),
            }},
        )
        if upd.modified_count == 0:
            return

        # Credit the referrer
        await db.users.update_one(
            {"id": referrer_id},
            {"$inc": {"balance_ton": bonus, "referralBonusEarned": bonus}},
        )

        # Transaction record for both sides
        tx_id = str(uuid.uuid4())
        await db.transactions.insert_one({
            "id": tx_id,
            "tx_type": "referral_activation_bonus",
            "type": "referral_activation_bonus",
            "user_id": referrer_id,
            "amount_ton": bonus,
            "from_address": "system",
            "to_address": referrer_id,
            "status": "completed",
            "campaign_id": campaign["id"],
            "referred_user_id": canonical_id,
            "referred_username": user_doc.get("username"),
            "description": f"Реферальный бонус: +{bonus} TON — @{user_doc.get('username', '')} стал активным",
            "created_at": now_msk().isoformat(),
        })

        # In-app notification for the referrer (i18n-aware; frontend renders
        # from `promoReferralActivationBonusTitle/Body` per user's language).
        try:
            await db.notifications.insert_one({
                "id": str(uuid.uuid4()),
                "user_id": referrer_id,
                "type": "referral_activation_bonus",
                "priority": "success",
                "title": "Реферальный бонус!",  # Fallback for legacy clients
                "message": f"+{bonus} TON — ваш реферал @{user_doc.get('username', '')} стал активным",
                "payload": {
                    "i18n_key": "promoReferralActivationBonus",
                    "i18n_vars": {
                        "amount": bonus,
                        "username": user_doc.get("username", ""),
                    },
                },
                "amount_ton": bonus,
                "read": False,
                "created_at": now_msk().isoformat(),
            })
        except Exception as _e:
            logger.debug(f"referral bonus notif insert failed: {_e}")

        # Telegram push (best-effort, i18n by user language)
        try:
            from telegram_notifications import get_user_telegram_chat_id, send_telegram_message
            chat_id = await get_user_telegram_chat_id(db, referrer_id)
            if chat_id:
                ref_doc = await db.users.find_one({"id": referrer_id}, {"_id": 0, "language": 1}) or {}
                r_lang = (ref_doc.get("language") or "ru").lower()
                r_username = user_doc.get("username", "")
                tg_texts = {
                    "ru": (
                        f"💰 <b>Реферальный бонус!</b>\n\n"
                        f"+{bonus} TON — ваш реферал @{r_username} купил первый плот!\n\n"
                        f"Продолжайте приглашать друзей и попадите в ТОП-3 акции 🔥"
                    ),
                    "en": (
                        f"💰 <b>Referral bonus!</b>\n\n"
                        f"+{bonus} TON — your referral @{r_username} bought their first plot!\n\n"
                        f"Keep inviting friends and reach the TOP-3 of the rally 🔥"
                    ),
                    "es": (
                        f"💰 <b>¡Bono de referido!</b>\n\n"
                        f"+{bonus} TON — tu referido @{r_username} compró su primera parcela!\n\n"
                        f"Sigue invitando amigos y llega al TOP-3 del rally 🔥"
                    ),
                    "zh": (
                        f"💰 <b>推荐奖金!</b>\n\n"
                        f"+{bonus} TON — 你的推荐人 @{r_username} 购买了他们的第一块地!\n\n"
                        f"继续邀请朋友,冲入前 3 名 🔥"
                    ),
                    "fr": (
                        f"💰 <b>Bonus de parrainage !</b>\n\n"
                        f"+{bonus} TON — votre filleul @{r_username} a acheté sa première parcelle !\n\n"
                        f"Continuez à inviter des amis et atteignez le TOP-3 du rallye 🔥"
                    ),
                    "de": (
                        f"💰 <b>Empfehlungsbonus!</b>\n\n"
                        f"+{bonus} TON — deine Empfehlung @{r_username} hat das erste Grundstück gekauft!\n\n"
                        f"Lade weiterhin Freunde ein und erreiche die TOP-3 der Rally 🔥"
                    ),
                    "ja": (
                        f"💰 <b>紹介ボーナス!</b>\n\n"
                        f"+{bonus} TON — あなたの紹介 @{r_username} が最初の区画を購入しました!\n\n"
                        f"友達を招待し続けて、ラリーの TOP-3 を目指そう 🔥"
                    ),
                    "ko": (
                        f"💰 <b>추천 보너스!</b>\n\n"
                        f"+{bonus} TON — 당신의 추천 @{r_username}이(가) 첫 번째 부지를 구입했습니다!\n\n"
                        f"친구 초대를 계속하고 랠리 TOP-3에 도달하세요 🔥"
                    ),
                }
                text = tg_texts.get(r_lang, tg_texts["en"])
                await send_telegram_message(chat_id, text)
        except Exception as _e:
            logger.debug(f"referral bonus TG send failed: {_e}")

        logger.info(f"💰 Referral activation bonus paid: {bonus} TON to {referrer_id} for {buyer_user_id}")
        _invalidate_leaderboard_cache()

    except Exception as e:
        logger.error(f"maybe_pay_activation_bonus failed: {e}", exc_info=True)


# ==================== FREEZE / FINALIZATION ====================

async def freeze_campaign(db, campaign: Dict[str, Any]) -> Dict[str, Any]:
    """
    Take a snapshot of the top-3, persist as `winners`, mark campaign finished.
    Idempotent: returns existing winners if already finished.
    """
    if campaign.get("status") == "finished" and campaign.get("winners"):
        return campaign

    top_rows, _ = await compute_referrals_leaderboard(db, sort="active", offset=0, limit=3)
    prizes = campaign.get("config", {}).get("prizes_ton", [100.0, 50.0, 20.0])
    winners: List[Dict[str, Any]] = []
    for i, r in enumerate(top_rows[:3]):
        winners.append({
            "rank": i + 1,
            "user_id": r.get("user_id"),
            "username": r.get("username") or "",
            "active_count": r.get("active", 0),
            "total_count": r.get("total", 0),
            "prize_ton": float(prizes[i]) if i < len(prizes) else 0.0,
            "paid": False,
        })

    now = now_msk()
    res = await db[COLLECTION].update_one(
        {"id": campaign["id"], "status": "active"},
        {"$set": {
            "status": "finished",
            "frozen_at": now.isoformat(),
            "winners": winners,
        }},
    )
    _invalidate_leaderboard_cache()
    if res.modified_count == 0:
        # Someone else finished it — reload
        doc = await db[COLLECTION].find_one({"id": campaign["id"]}, {"_id": 0})
        return doc or campaign

    fresh = await db[COLLECTION].find_one({"id": campaign["id"]}, {"_id": 0})
    logger.info(f"🏁 Campaign {campaign['id']} frozen with {len(winners)} winners")
    return fresh or campaign
