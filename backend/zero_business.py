"""Level-0 (застолблённый) business onboarding mechanic — shared helpers.

Lifecycle:
  * A user with ZERO real businesses AND `has_graduated_zero != True` may claim
    ("застолбить") exactly ONE business from the map for 0 TON at level 0.
  * While a level-0 business is held, the user cannot buy/build anything else,
    cannot take credit, and resource-sale proceeds go to `bonus_balance`.
  * Upgrading level 0 -> 1 costs the current map price in $CITY paid strictly
    from the REAL balance, removes the auto marketplace lot, and sets
    `has_graduated_zero = True` (permanent — no more level-0 claims ever).
  * The claimed business is auto-listed on the marketplace at map_price * 1.2.
    Proceeds from that lot go to the ADMIN, not the claimer. The lot cannot be
    delisted. When bought, the buyer receives a normal level-1 business (empty
    storage), the old owner loses it (and can claim again), and gets a notice.
"""

ZERO_PRICE_MULTIPLIER = 1.2
CITY_PER_TON = 1000


def owner_query(user_ids):
    ids = [i for i in user_ids if i]
    return {"owner": {"$in": ids}} if ids else {"owner": "__no_such_owner__"}


async def _real_businesses(db, user_ids):
    ids = [i for i in (user_ids or []) if i]
    docs = await db.businesses.find(
        {"$or": [owner_query(user_ids), {"rental_owner": {"$in": ids}}], "is_trial": {"$ne": True}},
        {"_id": 0, "id": 1, "level": 1, "is_zero_business": 1},
    ).to_list(200)
    return docs


async def count_real_businesses(db, user_ids) -> int:
    return len(await _real_businesses(db, user_ids))


async def get_zero_business(db, user_ids):
    """Return the user's level-0 business doc (full) or None."""
    return await db.businesses.find_one(
        {**owner_query(user_ids), "level": 0, "is_trial": {"$ne": True}},
        {"_id": 0},
    )


async def has_zero_business(db, user_ids) -> bool:
    return (await get_zero_business(db, user_ids)) is not None


async def can_stake_zero(db, user_doc, user_ids) -> bool:
    """Eligible to claim a level-0 business: exactly 0 real businesses AND never
    graduated (never upgraded a level-0 to level-1)."""
    if user_doc and user_doc.get("has_graduated_zero"):
        return False
    return (await count_real_businesses(db, user_ids)) == 0


async def should_credit_bonus(db, user_ids) -> bool:
    """Resource-sale proceeds go to bonus_balance when the seller has NO
    businesses at all, OR holds at least one level-0 business."""
    docs = await _real_businesses(db, user_ids)
    if len(docs) == 0:
        return True
    return any((d.get("level", 1) == 0) for d in docs)


async def city_market_payout_is_real(db, user_ids) -> bool:
    """City Market (market maker) payout rule, set by the project owner:
    REAL balance if the seller owns at least one business of level 1+,
    otherwise (only level-0 businesses, or none) the BONUS balance.

    Note: ordinary player-to-player sales use should_credit_bonus() above,
    which sends proceeds to bonus as soon as the seller holds ANY level-0
    business. The two rules differ only for sellers who own both.
    """
    docs = await _real_businesses(db, user_ids)
    return any(int(d.get("level", 1) or 0) >= 1 for d in docs)


async def create_zero_listing(db, business, seller_user_id, seller_username, uuid_mod, datetime_mod, timezone_mod):
    """Auto-create the marketplace lot for a freshly claimed level-0 business.
    Price is FIXED at map_price * 1.2 at claim time. Returns the listing id.
    The `business` payload mirrors a normal sale listing (translated name,
    icon, tier, produces + production/day, consumes) so buyers see full data."""
    from business_config import get_production, get_consumption_breakdown
    try:
        from core.helpers import resolve_business_config
    except Exception:
        resolve_business_config = None
    map_price = float(business.get("zero_map_price", 0) or 0)
    price = round(map_price * ZERO_PRICE_MULTIPLIER, 6)
    listing_id = str(uuid_mod.uuid4())
    _bt = business.get("business_type")
    _cfg = (resolve_business_config(_bt) if resolve_business_config else {}) or {}
    _biz_payload = {
        "type": _bt,
        "level": 1,  # shown to buyers as a normal level-1 business
        "durability": 100,
        "xp": 0,
        "connections": 0,
        "icon": _cfg.get("icon", business.get("icon", "")),
        "name": _cfg.get("name", business.get("name", {})),
        "tier": _cfg.get("tier", business.get("tier", 1)),
        "produces": _cfg.get("produces", ""),
        "production_per_day": get_production(_bt, 1),
        "consumes": get_consumption_breakdown(_bt, 1),
    }
    listing = {
        "id": listing_id,
        "plot_id": business.get("plot_id"),
        "city_id": business.get("island_id") or business.get("city_id") or "ton_island",
        "city_name": "GRAM Island",
        "x": business.get("x"),
        "y": business.get("y"),
        "seller_id": seller_user_id,
        "seller_user_id": seller_user_id,
        "seller_username": seller_username or "Anonymous",
        "business_id": business.get("id"),
        "price": price,
        "original_price": map_price,
        "tax_amount": 0.0,
        "seller_receives": 0.0,
        "is_zero_business": True,
        "admin_proceeds": True,
        "locked_delist": True,
        "business": _biz_payload,
        "status": "active",
        "created_at": datetime_mod.now(timezone_mod.utc).isoformat(),
    }
    await db.land_listings.insert_one(listing.copy())
    return listing_id, price


# Tier-3 lease welcome bonus (credited to bonus_balance on claiming a level-0
# tier-3 business; reclaimed on lease end / seizure if it is NOT bought out).
LEASE_TON_BONUS = 5.0


def _business_tier(business_type) -> int:
    from business_config import BUSINESSES, BUSINESS_KEY_MAP
    mapped = BUSINESS_KEY_MAP.get(business_type, business_type)
    cfg = BUSINESSES.get(mapped) or BUSINESSES.get(business_type) or {}
    try:
        return int(cfg.get("tier", 1) or 1)
    except (TypeError, ValueError):
        return 1


async def grant_zero_consumption(db, user_id, business_type, business_id=None):
    """On claiming a level-0 business, credit the user the business's DAILY
    consumption norm of EVERY resource it needs (tier-2/3 businesses consume 2
    resource types -> both daily norms are granted) so it can run immediately.
    TON-denominated pseudo lines (e.g. profit_ton) are excluded.

    Tier-3 businesses additionally receive a +5 TON welcome bonus on the bonus
    balance; the amount is recorded on the business so it can be reclaimed if the
    lease ends without the user buying the business out to level 1."""
    from business_config import get_consumption_breakdown
    _EXCLUDED = {"profit_ton", "ton", "city", "gram"}
    breakdown = get_consumption_breakdown(business_type, 1) or {}
    inc = {f"resources.{res}": amt for res, amt in breakdown.items() if amt and res not in _EXCLUDED}
    if inc:
        await db.users.update_one({"id": user_id}, {"$inc": inc})
    # Tier-3 lease bonus: +5 TON to bonus balance.
    if _business_tier(business_type) == 3:
        await db.users.update_one({"id": user_id}, {"$inc": {"bonus_balance": LEASE_TON_BONUS}})
        if business_id:
            await db.businesses.update_one(
                {"id": business_id}, {"$set": {"lease_ton_bonus": LEASE_TON_BONUS}}
            )
    return breakdown


async def clawback_lease_bonus(db, owner_key, business) -> float:
    """Reclaim the tier-3 lease welcome bonus from the owner's bonus balance when
    a leased (level-0) business leaves them WITHOUT a buyout (lease expiry /
    seizure / bought by another player). Takes up to `lease_ton_bonus` TON; if the
    bonus balance holds less, it takes whatever is there (never below 0).
    Returns the amount reclaimed."""
    amt = float((business or {}).get("lease_ton_bonus", 0) or 0)
    if amt <= 0 or not owner_key:
        return 0.0
    user = await db.users.find_one(
        {"$or": [{"id": owner_key}, {"wallet_address": owner_key}, {"email": owner_key}]},
        {"_id": 0, "id": 1, "bonus_balance": 1},
    )
    if not user:
        return 0.0
    cur = float(user.get("bonus_balance", 0) or 0)
    take = min(amt, max(0.0, cur))
    if take > 0:
        await db.users.update_one({"id": user["id"]}, {"$inc": {"bonus_balance": -take}})
    return take


# ─── Localized notification: "your level-0 business was bought on the market" ──
ZERO_BOUGHT_NOTIF = {
    "en": {
        "title": "🏢 Business bought on the Marketplace",
        "message": "Your level-0 business was purchased by another player on the Marketplace. You can now claim a new free business on the map.",
    },
    "ru": {
        "title": "🏢 Бизнес выкуплен на Маркетплейсе",
        "message": "Ваш бизнес нулевого уровня был выкуплен другим игроком на Маркетплейсе. Теперь вы можете снова застолбить бесплатный бизнес на карте.",
    },
    "es": {
        "title": "🏢 Negocio comprado en el Mercado",
        "message": "Otro jugador compró tu negocio de nivel 0 en el Mercado. Ahora puedes reclamar un nuevo negocio gratis en el mapa.",
    },
    "zh": {
        "title": "🏢 企业在市场上被买走",
        "message": "您的0级企业被其他玩家在市场上买走了。您现在可以在地图上重新认领一个免费企业。",
    },
    "fr": {
        "title": "🏢 Entreprise achetée sur le Marché",
        "message": "Votre entreprise de niveau 0 a été achetée par un autre joueur sur le Marché. Vous pouvez maintenant réclamer une nouvelle entreprise gratuite sur la carte.",
    },
    "de": {
        "title": "🏢 Unternehmen auf dem Marktplatz gekauft",
        "message": "Dein Level-0-Unternehmen wurde von einem anderen Spieler auf dem Marktplatz gekauft. Du kannst jetzt ein neues kostenloses Unternehmen auf der Karte beanspruchen.",
    },
    "ja": {
        "title": "🏢 ビジネスがマーケットで購入されました",
        "message": "あなたのレベル0ビジネスが他のプレイヤーにマーケットプレイスで購入されました。マップで新しい無料ビジネスを再び取得できます。",
    },
    "ko": {
        "title": "🏢 마켓에서 비즈니스가 판매됨",
        "message": "당신의 레벨 0 비즈니스가 마켓플레이스에서 다른 플레이어에게 구매되었습니다. 이제 지도에서 새로운 무료 비즈니스를 다시 선점할 수 있습니다.",
    },
    "id": {
        "title": "🏢 Bisnis dibeli di Marketplace",
        "message": "Bisnis level-0 Anda dibeli oleh pemain lain di Marketplace. Sekarang Anda dapat mengklaim bisnis gratis baru di peta.",
    },
}


async def notify_zero_bought(db, owner_user, uuid_mod, datetime_mod, timezone_mod, manager=None):
    """Insert a localized notification for the former owner + WS push."""
    if not owner_user:
        return
    lang = (owner_user.get("language") or "en")
    if lang not in ZERO_BOUGHT_NOTIF:
        lang = "en"
    txt = ZERO_BOUGHT_NOTIF[lang]
    from core.notify import notify_user
    await notify_user(db, owner_user, title=txt["title"], message=txt["message"],
                      type_key="zero_business_bought", priority="high")
