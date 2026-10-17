"""Level-0 (test) business 3-day lease + 48h market-lot soft-expiration.

Lifecycle additions on top of ``zero_business.py``:
  * A claimed level-0 business carries ``expires_at`` = claim_time + 3 days.
  * 12h before expiry the owner gets a localized "lease expiring" notice.
  * At expiry the business is removed, its plot becomes free again, the auto
    marketplace lot is delisted and all the owner's active resource orders tied
    to it are cancelled (resources returned). The owner then gets a notice.
  * Any resource lot that sits unsold on the market for >= 48h is auto-cancelled
    and its resources returned to the seller with a "goods returned" notice.
"""
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

ZERO_LEASE_DAYS = 3
# Пороги напоминаний об окончании аренды (в часах до истечения): за 24ч, 12ч и 3ч.
ZERO_LEASE_WARN_THRESHOLDS = [24, 12, 3]
ZERO_LEASE_WARN_HOURS = 12  # для обратной совместимости (текст/старые вызовы)
MARKET_LOT_MAX_HOURS = 48


def _now():
    return datetime.now(timezone.utc)


def _parse_iso(v):
    if not v:
        return None
    try:
        s = str(v).replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def compute_expires_at(now=None) -> str:
    now = now or _now()
    return (now + timedelta(days=ZERO_LEASE_DAYS)).isoformat()


def _biz_name(business: dict, lang: str) -> str:
    from business_config import BUSINESSES, BUSINESS_KEY_MAP
    bt = business.get("business_type")
    cfg = BUSINESSES.get(BUSINESS_KEY_MAP.get(bt, bt)) or BUSINESSES.get(bt) or {}
    names = cfg.get("name", {}) or {}
    return names.get(lang) or names.get("en") or names.get("ru") or bt


def _res_name(resource: str, lang: str) -> str:
    from business_config import RESOURCE_TYPES
    meta = RESOURCE_TYPES.get(resource, {}) or {}
    return meta.get(f"name_{lang}") or meta.get("name_en") or meta.get("name_ru") or resource


async def _find_owner_user(db, business: dict):
    owner = business.get("owner")
    if not owner:
        return None
    return await db.users.find_one(
        {"$or": [{"id": owner}, {"wallet_address": owner}]}, {"_id": 0}
    )


# ─────────────────────────── 3-day lease job ────────────────────────────────

def zero_upgrade_cost_ton(business: dict) -> float:
    """Price of upgrading a level-0 business to level 1 (paid from the REAL
    balance) — same formula as routes/business_mgmt.py upgrade."""
    try:
        from business_config import BUSINESSES
        cfg = BUSINESSES.get(business.get("business_type"), {})
    except Exception:
        cfg = {}
    return round(float(business.get("zero_map_price") or cfg.get("base_cost_ton") or cfg.get("price_ton") or 0), 4)


UPGRADE_BUTTON = {
    "en": "⬆️ Upgrade to level 1 for {cost} TON",
    "ru": "⬆️ Улучшить до 1 уровня за {cost} TON",
}


async def _upgrade_button(db, lang: str, cost_ton: float):
    """Inline Telegram button that opens the app on the upgrade offer.
    en/ru by hand; other languages via LibreTranslate (cached), else English."""
    try:
        from core.notify import resolve_miniapp_url
        url = await resolve_miniapp_url(db)
    except Exception:
        url = None
    if not url:
        return None
    tpl = UPGRADE_BUTTON.get(lang)
    if not tpl:
        tpl = UPGRADE_BUTTON["en"]
        try:
            import smart_notify
            if smart_notify._DB is None:
                smart_notify.init(db)
            # cached per language in smart_notif_i18n; {cost} is protected
            tpl = await smart_notify._translate_word(UPGRADE_BUTTON["en"], lang) or tpl
            if "{cost}" not in tpl:
                tpl = UPGRADE_BUTTON["en"]
        except Exception:
            pass
    sep = "&" if "?" in url else "?"
    return {"inline_keyboard": [[{"text": tpl.format(cost=cost_ton), "url": f"{url}{sep}startapp=my_businesses"}]]}


async def process_zero_lease(db) -> dict:
    """Напоминания за 24ч/12ч/3ч до конца аренды; удаление бизнеса + освобождение
    участка по истечении. Перед проходом возвращает в работу ошибочно изъятые,
    но ещё арендованные бизнесы 0-го уровня."""
    now = _now()
    warned = 0
    expired = 0

    # 0) Восстановить в работу бизнесы 0-го уровня, которые были ошибочно изъяты
    #    (например, старым джобом неактивности), но аренда ещё действует.
    restored = await restore_wrongly_seized_zero_leases(db)

    cursor = db.businesses.find({
        "level": 0,
        "is_zero_business": True,
        "is_trial": {"$ne": True},
        "expires_at": {"$ne": None},
    })
    async for biz in cursor:
        exp = _parse_iso(biz.get("expires_at"))
        if not exp:
            continue
        if exp <= now:
            try:
                await _expire_zero_business(db, biz)
                expired += 1
            except Exception as e:
                logger.error(f"process_zero_lease expire failed for {biz.get('id')}: {e}")
            continue
        # Напоминания на порогах 24ч / 12ч / 3ч. Каждый порог отправляется один раз;
        # уже отправленные пороги храним в массиве zero_lease_warns.
        try:
            sent = set(int(h) for h in (biz.get("zero_lease_warns") or []))
        except (TypeError, ValueError):
            sent = set()
        hours_left = (exp - now).total_seconds() / 3600.0
        due = [h for h in ZERO_LEASE_WARN_THRESHOLDS if h not in sent and hours_left <= h]
        if not due:
            continue
        # Отправляем только САМЫЙ близкий подходящий порог (наименьший),
        # остальные пройденные пороги помечаем отправленными без дублей.
        threshold = min(due)
        try:
            from core.notify import notify_user
            from core.notif_i18n import user_lang
            user = await _find_owner_user(db, biz)
            if user:
                lang = user_lang(user)
                cost_ton = zero_upgrade_cost_ton(biz)
                have_ton = round(float(user.get("balance_ton", 0) or 0), 4)
                await notify_user(
                    db, user, title=None, message=None,
                    type_key="zero_lease_expiring", priority="high",
                    i18n_key="zero_lease_expiring",
                    i18n_vars={"biz": _biz_name(biz, lang), "hours": threshold},
                    # in-app: «Улучшить за X TON» button (NotificationCenter)
                    payload={"kind": "zero_lease_upgrade", "business_id": biz.get("id"),
                             "upgrade_cost_ton": cost_ton, "balance_ton": have_ton,
                             "hours_left": threshold},
                    # Telegram: the same offer as an inline button into the app
                    reply_markup=await _upgrade_button(db, lang, cost_ton),
                )
            await db.businesses.update_one(
                {"id": biz["id"]},
                {"$set": {"zero_lease_warned": True},
                 "$addToSet": {"zero_lease_warns": {"$each": list(due)}}},
            )
            warned += 1
        except Exception as e:
            logger.error(f"process_zero_lease warn failed for {biz.get('id')}: {e}")
    if warned or expired or restored:
        logger.info(f"process_zero_lease: warned={warned}, expired={expired}, restored={restored}")
    return {"warned": warned, "expired": expired, "restored": restored}


async def restore_wrongly_seized_zero_leases(db) -> int:
    """Вернуть в работу бизнесы 0-го уровня, которые были помечены изъятыми/на
    продаже (is_seized/on_sale/status=on_sale/is_active=False), но срок аренды
    ещё не истёк. Снимаем флаги изъятия с бизнеса и с его листинга (сам листинг
    остаётся активным — арендованный бизнес всегда стоит на маркетплейсе)."""
    now = _now()
    restored = 0
    cursor = db.businesses.find({
        "level": 0,
        "is_zero_business": True,
        "is_trial": {"$ne": True},
        "expires_at": {"$ne": None},
        "$or": [
            {"is_seized": True},
            {"on_sale": True},
            {"status": "on_sale"},
            {"is_active": False},
        ],
    })
    async for biz in cursor:
        exp = _parse_iso(biz.get("expires_at"))
        if not exp or exp <= now:
            # Аренда истекла — восстановлением не занимаемся, это сделает expiry.
            continue
        biz_id = biz.get("id")
        await db.businesses.update_one(
            {"id": biz_id},
            {
                "$set": {"is_active": True, "on_sale": False, "status": "active",
                         "work_status": "idle", "work_status_reason": None},
                "$unset": {"is_seized": "", "seizure_reason": "", "seized_at": "",
                           "former_owner": "", "former_level": ""},
            },
        )
        # Снимаем флаги изъятия с авто-листинга (он должен остаться активным).
        await db.land_listings.update_many(
            {"business_id": biz_id},
            {"$unset": {"is_seized": "", "seizure_reason": "",
                        "former_owner_id": "", "former_level": ""}},
        )
        restored += 1
    if restored:
        logger.info(f"restore_wrongly_seized_zero_leases: восстановлено {restored} арендованных бизнесов 0-го уровня")
    return restored


async def _expire_zero_business(db, biz: dict) -> None:
    """Remove an expired level-0 business, free its plot, cancel its lots."""
    business_id = biz.get("id")
    owner = biz.get("owner")
    plot_id = biz.get("plot_id")
    produces = None
    try:
        from business_config import BUSINESSES, BUSINESS_KEY_MAP
        bt = biz.get("business_type")
        cfg = BUSINESSES.get(BUSINESS_KEY_MAP.get(bt, bt)) or BUSINESSES.get(bt) or {}
        produces = cfg.get("produces")
    except Exception:
        produces = None

    user = await _find_owner_user(db, biz)

    # Reclaim the tier-3 lease welcome bonus (if any): the lease ended without the
    # user buying the business out to level 1, so the +5 TON is taken back from the
    # bonus balance (or whatever is left if it holds less than 5 TON).
    try:
        import zero_business as _zb
        await _zb.clawback_lease_bonus(db, owner, biz)
    except Exception as e:
        logger.error(f"_expire_zero_business clawback failed for {business_id}: {e}")

    # 1) Delist the auto level-0 marketplace lot(s) for this business.
    await db.land_listings.delete_many({"business_id": business_id})

    # 2) Cancel the owner's active resource sale orders tied to this business /
    #    the resource it produced — return the reserved resources to the owner.
    if owner:
        q = {"seller_id": owner, "status": "active"}
        or_terms = [{"business_id": business_id}]
        if produces:
            or_terms.append({"resource_type": produces})
        q["$or"] = or_terms
        async for lot in db.market_listings.find(q, {"_id": 0}):
            rtype = lot.get("resource_type")
            amt = lot.get("amount", 0) or 0
            if user and rtype and amt > 0:
                await db.users.update_one(
                    {"$or": [{"id": owner}, {"wallet_address": owner}]},
                    {"$inc": {f"resources.{rtype}": amt}},
                )
            await db.market_listings.update_one(
                {"id": lot["id"]},
                {"$set": {"status": "cancelled", "cancelled_at": _now().isoformat(),
                          "cancelled_reason": "zero_lease_expired"}},
            )

    # 3) Remove the business and free the plot (cell becomes "Свободно").
    await db.businesses.delete_one({"id": business_id})
    if plot_id:
        await db.plots.delete_one({"id": plot_id})
    else:
        await db.plots.delete_many({"business_id": business_id})

    # 4) Drop it from the user's owned-businesses list.
    if owner:
        await db.users.update_one(
            {"$or": [{"id": owner}, {"wallet_address": owner}]},
            {"$pull": {"businesses_owned": business_id}},
        )

    # 5) Notify the former owner (localized, on-screen + Telegram + mini-app link).
    try:
        from core.notify import notify_user
        from core.notif_i18n import user_lang
        if user:
            lang = user_lang(user)
            await notify_user(
                db, user, title=None, message=None,
                type_key="zero_lease_expired", priority="high",
                i18n_key="zero_lease_expired",
                i18n_vars={"biz": _biz_name(biz, lang)},
            )
    except Exception as e:
        logger.error(f"_expire_zero_business notify failed for {business_id}: {e}")

    logger.info(f"⏳ zero-lease expired: removed business {business_id}, freed plot {plot_id}")


# ──────────────────────── 48h market-lot expiry job ─────────────────────────

async def process_market_lot_expiry(db) -> dict:
    """Auto-cancel resource lots older than 48h and return resources to seller."""
    now = _now()
    cutoff = now - timedelta(hours=MARKET_LOT_MAX_HOURS)
    returned = 0
    cursor = db.market_listings.find({"status": "active"})
    async for lot in cursor:
        # Skip system / bot / tutorial lots — only real player resource lots expire.
        if lot.get("is_bot") or lot.get("tutorial"):
            continue
        created = _parse_iso(lot.get("created_at"))
        if not created or created > cutoff:
            continue
        rtype = lot.get("resource_type")
        amount = lot.get("amount", 0) or 0
        seller_id = lot.get("seller_id")
        # Return the reserved resources to the seller's warehouse.
        if seller_id and rtype and amount > 0:
            seller = await db.users.find_one(
                {"$or": [{"id": seller_id}, {"email": lot.get("seller_email")},
                         {"wallet_address": seller_id}]}, {"_id": 0},
            )
            if seller:
                filt = {"id": seller_id}
                if not seller.get("id") == seller_id and seller.get("email"):
                    filt = {"email": seller.get("email")}
                await db.users.update_one(
                    {"$or": [{"id": seller_id}, {"email": lot.get("seller_email")},
                             {"wallet_address": seller_id}]},
                    {"$inc": {f"resources.{rtype}": amount}},
                )
        await db.market_listings.update_one(
            {"id": lot["id"]},
            {"$set": {"status": "cancelled", "cancelled_at": now.isoformat(),
                      "cancelled_reason": "expired_48h"}},
        )
        returned += 1
        # Notify the seller (localized "goods returned" tip).
        try:
            from core.notify import notify_user
            from core.notif_i18n import user_lang
            seller_doc = await db.users.find_one(
                {"$or": [{"id": seller_id}, {"email": lot.get("seller_email")},
                         {"wallet_address": seller_id}]}, {"_id": 0},
            )
            if seller_doc:
                lang = user_lang(seller_doc)
                await notify_user(
                    db, seller_doc, title=None, message=None,
                    type_key="market_lot_returned", priority="info",
                    i18n_key="market_lot_returned",
                    i18n_vars={"res": _res_name(rtype, lang), "amount": int(amount)},
                )
        except Exception as e:
            logger.error(f"process_market_lot_expiry notify failed for {lot.get('id')}: {e}")
    if returned:
        logger.info(f"process_market_lot_expiry: returned {returned} lots (>48h)")
    return {"returned": returned}



# ───────────────── Level-0 seller auto-buyback (24h) ─────────────────────────

# process_zero_level_buyback (24h auto-buyback of level-0 lots) was removed —
# the City Market (market_maker.py) buys these lots after 30 minutes instead.
