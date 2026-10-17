"""
Helper functions for the application
"""
import math
from tonsdk.utils import Address
from .config import ZONES_LEGACY, BUSINESS_TYPES, LEVEL_CONFIG, BASE_TAX_RATE, PROGRESSIVE_TAX
from business_config import BUSINESSES, BUSINESS_KEY_MAP


# ==================== BUSINESS CONFIG RESOLVER ====================

def resolve_business_config(business_type: str) -> dict:
    """Get BUSINESSES config for a business type, handling key mismatches
    (e.g. CITY_BUSINESSES uses `chip_factory`, BUSINESSES uses `chips_factory`)."""
    config = BUSINESSES.get(business_type)
    if config:
        return config
    mapped = BUSINESS_KEY_MAP.get(business_type, business_type)
    return BUSINESSES.get(mapped, {})


RESOURCE_NAMES = {
    "chips": "Чипы", "energy": "Энергия", "gadgets": "Гаджеты", "tokens": "Токены",
    "data": "Данные", "algorithms": "Алгоритмы", "ai_prompts": "AI-промпты",
    "nft": "NFT", "art": "Искусство", "stakes": "Стейкинг", "loans": "Займы",
    "logistics": "Логистика", "repair_kits": "Ремкомплект", "vr_experience": "VR-опыт",
    "profit_ton": "TON-прибыль",
    "neuro_core": "Нейро-ядро", "gold_bill": "Золотой вексель", "license_token": "Лицензия",
    "luck_chip": "Фишка удачи", "war_protocol": "Боевой протокол",
    "bio_module": "Био-модуль", "gateway_code": "Код шлюза",
}


def translate_resource_name(resource_code: str) -> str:
    return RESOURCE_NAMES.get(resource_code, resource_code)


def available_balance_ton(user_doc: dict) -> float:
    """Returns user's spendable TON balance, excluding amounts frozen as
    tender escrow (which are not available for ANY operation — buy land,
    build, withdraw etc.).
    """
    if not user_doc:
        return 0.0
    bal = float(user_doc.get("balance_ton", 0) or 0)
    frozen_city = float(user_doc.get("frozen_city_for_tenders", 0) or 0)
    return max(0.0, bal - frozen_city / 1000.0)


# ==================== TON ADDRESS HELPERS ====================

def to_raw(address_str):
    """Convert TON address to raw format"""
    try:
        return Address(address_str).to_string(is_user_friendly=False)
    except Exception:
        return address_str


def to_user_friendly(raw_address):
    """Convert raw TON address to user-friendly format (UQ format for mainnet)"""
    try:
        return Address(raw_address).to_string(is_user_friendly=True, is_url_safe=True, is_bounceable=False, is_test_only=False)
    except Exception:
        return raw_address


def normalize_wallet(address_str):
    """Return the canonical (user_friendly, raw) TON address pair.

    `raw` (0:hex) is the single source of truth for identifying a wallet.
    Returns (None, None) if the address is invalid — callers MUST treat that
    as a hard error and never store/query a half-normalized value.
    """
    if not address_str:
        return None, None
    try:
        addr = Address(str(address_str).strip())
        raw = addr.to_string(is_user_friendly=False)
        # UQ format (non-bounceable) — this is what TON Connect returns for wallet
        # addresses. Store the canonical UQ form so that lookups always hit.
        uf = addr.to_string(is_user_friendly=True, is_url_safe=True, is_bounceable=False, is_test_only=False)
        if not raw or not uf:
            return None, None
        return uf, raw
    except Exception:
        return None, None


# ==================== OWNERSHIP HELPERS ====================

async def get_user_identifiers(db, current_user) -> dict:
    """All identifiers a player's records may be stored under (ownership checks).

    The player is looked up by the stable `id` (never by a possibly-empty
    wallet/e-mail: `{"wallet_address": None}` matches every wallet-less user).
    Returns {"user", "ids", "primary_id"}. This is the ONLY implementation —
    server.py used to keep its own, diverging copy.
    """
    user = await db.users.find_one({"id": current_user.id}, {"_id": 0}) if getattr(current_user, "id", None) else None
    if not user:
        return {"user": None, "ids": set(), "primary_id": None}
    user_id = user.get("id", str(user.get("_id", "")))
    ids = {user_id, getattr(current_user, "wallet_address", None), current_user.id}
    for k in ("wallet_address", "email", "username"):
        if user.get(k):
            ids.add(user.get(k))
    ids.discard(None)
    ids.discard("")
    return {"user": user, "ids": ids, "primary_id": user_id}


def nz_or(conditions: list) -> list:
    """Drop `$or` conditions whose value is empty.

    `{"wallet_address": None}` matches EVERY user without a wallet (every
    email-only player), so leaving it in an `$or` makes the query pick a random
    stranger. Use as `{"$or": nz_or([...])}`. If nothing is left, the returned
    condition matches no document instead of matching everybody.
    """
    kept = [c for c in conditions
            if isinstance(c, dict) and c and all(v is not None and v != "" for v in c.values())]
    return kept or [{"_id": "__no_match__"}]


def owner_key(current_user) -> str:
    """Value to store as a plot/business `owner`: the wallet if the player has
    one (legacy behaviour), otherwise the user id — never None."""
    return getattr(current_user, "wallet_address", None) or getattr(current_user, "id", None)


def is_owner(business: dict, user_ids: set) -> bool:
    """Check if business belongs to any of user's identifiers"""
    owner = business.get("owner", "")
    owner_wallet = business.get("owner_wallet", "")
    return owner in user_ids or owner_wallet in user_ids


def get_user_filter(user: dict) -> dict:
    """Get MongoDB filter to find user by best available identifier"""
    if user.get("email"):
        return {"email": user["email"]}
    if user.get("wallet_address"):
        return {"wallet_address": user["wallet_address"]}
    return {"id": user.get("id")}


def get_businesses_query(user_ids: set) -> dict:
    """Get MongoDB query to find businesses by any user identifier"""
    or_conditions = [{"owner": uid} for uid in user_ids]
    or_conditions.extend([{"owner_wallet": uid} for uid in user_ids])
    return {"$or": or_conditions}


async def resolve_owner_keys(db, user_id_or_field: str) -> list:
    """Given ANY user identifier (id / wallet_address / email / username), return
    every value that may have been stored in `business.owner` or `business.owner_wallet`
    for this user. Use with `owner_businesses_query` to build a multi-identifier match.

    Returns the original input if no matching user is found (so single-key callers
    still degrade gracefully instead of returning no businesses).
    """
    if not user_id_or_field:
        return []
    user = await db.users.find_one(
        {"$or": [
            {"id": user_id_or_field},
            {"wallet_address": user_id_or_field},
            {"email": user_id_or_field},
            {"username": user_id_or_field},
        ]},
        {"_id": 0, "id": 1, "wallet_address": 1, "email": 1, "username": 1},
    )
    keys = {user_id_or_field}
    if user:
        for k in ("id", "wallet_address", "email", "username"):
            v = user.get(k)
            if v:
                keys.add(v)
    return list(keys)


def owner_businesses_query(keys) -> dict:
    """Mongo $or to match a business whose owner OR owner_wallet equals
    any of the given identifiers.
    """
    if not keys:
        return {"owner": "__none__"}
    if isinstance(keys, (set, tuple)):
        keys = list(keys)
    conds = [{"owner": k} for k in keys]
    conds.extend([{"owner_wallet": k} for k in keys])
    return {"$or": conds}


# ==================== PRICE CALCULATION ====================

def calculate_plot_price(x: int, y: int) -> tuple:
    """Calculate plot price and zone based on distance from center"""
    center_x, center_y = 50, 50
    distance = math.sqrt((x - center_x)**2 + (y - center_y)**2)
    
    zone = "outskirts"
    for zone_name, config in ZONES_LEGACY.items():
        if distance <= config["radius_max"]:
            zone = zone_name
            break
    
    max_distance = math.sqrt(50**2 + 50**2)
    price = 10 + 90 * (1 - distance / max_distance)
    return round(price, 2), zone


def get_tax_rate(market_share: float) -> float:
    """Get progressive tax rate based on market share"""
    for threshold, rate in sorted(PROGRESSIVE_TAX.items(), reverse=True):
        if market_share >= threshold:
            return rate
    return BASE_TAX_RATE


def calculate_business_income(business_type: str, level: int, zone: str, connections: int) -> dict:
    """Calculate business income with all factors"""
    bt = BUSINESS_TYPES.get(business_type)
    if not bt:
        return {"gross": 0, "tax": 0, "net": 0}
    
    base = bt["base_income"]
    zone_mult = ZONES_LEGACY.get(zone, {}).get("price_mult", 0.5)
    level_mult = LEVEL_CONFIG.get(level, LEVEL_CONFIG[1])["income_mult"]
    conn_bonus = 1 + (connections * 0.05)
    
    gross = base * zone_mult * level_mult * conn_bonus
    tax = gross * BASE_TAX_RATE
    operating = bt.get("operating_cost", 0)
    net = gross - tax - operating
    
    return {
        "gross": round(gross, 4),
        "tax": round(tax, 4),
        "operating_cost": round(operating, 4),
        "net": round(max(0, net), 4)
    }


# ==================== TRANSLATION HELPER ====================

def t(key: str, lang: str = "en") -> str:
    """Simple translation helper"""
    translations = {
        "max_plots_reached": {"en": "Maximum plots reached for your level", "ru": "Достигнуто максимальное количество участков для вашего уровня"},
        "plot_not_available": {"en": "Plot not available", "ru": "Участок недоступен"},
        "invalid_zone": {"en": "Business not allowed in this zone", "ru": "Бизнес не разрешён в этой зоне"},
        "plot_purchased": {"en": "Plot purchased successfully", "ru": "Участок успешно приобретён"},
        "business_built": {"en": "Business built successfully", "ru": "Бизнес успешно построен"},
    }
    return translations.get(key, {}).get(lang, key)



# ==================== BUSINESS PURCHASE LIMITS ====================
MAX_BUSINESSES_PER_USER = 3
MAX_TIER3_BUSINESSES_PER_USER = 1


async def check_business_purchase_limits(db, user: dict, buyer_ids, business_type):
    """Validate business purchase against per-user limits.

    Rules (admins bypass everything):
      - Total active businesses (incl. on_sale listings) must stay under 3.
      - At most 1 Tier 3 business may be owned at a time.

    Notes:
      • Tutorial sandbox businesses (`tutorial: True`) are EXCLUDED from the
        count so users can't get stuck mid-tutorial. This matches what the
        marketplace UI shows.
      • Uses `resolve_owner_keys` so legacy docs with `owner = email/username`
        are still matched even if the caller only passed `id/wallet_address`.

    Returns (ok: bool, error_message: str | None).
    """
    if not business_type:
        return True, None

    is_admin = bool(user.get("is_admin", False)) or user.get("role") == "ADMIN"
    if is_admin:
        return True, None

    # Expand identifiers using resolve_owner_keys so we don't miss legacy docs
    # where the `owner` was stored as email/username instead of id/wallet.
    expanded_ids = set([uid for uid in (buyer_ids or []) if uid])
    for seed in (user.get("id"), user.get("wallet_address"), user.get("email"), user.get("username")):
        if seed:
            expanded_ids.add(seed)
            for k in await resolve_owner_keys(db, seed):
                if k:
                    expanded_ids.add(k)

    ids = list(expanded_ids)
    if not ids:
        return True, None

    or_conditions = [{"owner": uid} for uid in ids] + [{"owner_wallet": uid} for uid in ids]
    user_businesses = await db.businesses.find(
        {
            "$or": or_conditions,
            # Tutorial sandbox businesses don't count toward the cap.
            "tutorial": {"$ne": True},
        },
        {"_id": 0, "business_type": 1},
    ).to_list(100)

    total = len(user_businesses)
    if total >= MAX_BUSINESSES_PER_USER:
        return False, (
            f"У вас уже {MAX_BUSINESSES_PER_USER} бизнеса. "
            "Продайте один из них, чтобы купить новый."
        )

    biz_cfg = resolve_business_config(business_type) or {}
    biz_tier = biz_cfg.get("tier", 1)
    if biz_tier >= 3:
        tier3_count = sum(
            1 for b in user_businesses
            if (resolve_business_config(b.get("business_type")) or {}).get("tier", 1) >= 3
        )
        if tier3_count >= MAX_TIER3_BUSINESSES_PER_USER:
            return False, (
                "У вас уже есть бизнес 3-го эшелона. Можно иметь только один."
            )

    return True, None



# ==================== "Has real business?" GATE (iteration v2.1.5) ====================

async def user_has_active_business(db, user_doc: dict) -> bool:
    """Return True iff the user owns at least ONE real (non-tutorial) business.

    Used to gate market actions (create lot / buy lot / publish tender /
    submit offer) and the manual T3-buff activation. Tutorial businesses
    (`tutorial: true`) do NOT count — they're sandbox-only and get wiped on
    /tutorial/finish.
    """
    if not user_doc:
        return False
    owner_keys = await resolve_owner_keys(db, user_doc.get("id") or user_doc.get("wallet_address") or user_doc.get("email") or user_doc.get("username"))
    q = owner_businesses_query(owner_keys)
    # Exclude tutorial sandbox businesses.
    q = {**q, "tutorial": {"$ne": True}}
    count = await db.businesses.count_documents(q)
    return count > 0



# ==================== Tutorial-reward locking ====================
# The free Tier-3 resource granted at tutorial completion (1 unit) must NOT be
# sellable. Any ADDITIONAL units of the same resource (produced by a T3 business
# or bought on the market) ARE sellable. We track the locked count in
# `tutorial_reward_locked_qty` (int), set to 1 on grant and decremented to 0
# the moment that free unit is consumed by activating it as a buff.

def tutorial_locked_amount(user_doc: dict, resource_id: str) -> int:
    """How many units of `resource_id` are locked (free tutorial reward)."""
    if not user_doc or user_doc.get("tutorial_t3_reward_choice") != resource_id:
        return 0
    q = user_doc.get("tutorial_reward_locked_qty")
    if q is not None:
        try:
            return max(0, int(q))
        except (TypeError, ValueError):
            return 0
    # Backward-compat: while the free unit is still pending its (auto)activation
    # it sits unused in the inventory → lock 1.
    if user_doc.get("tutorial_t3_reward_granted") and \
       user_doc.get("tutorial_pending_t3_auto_activate") == resource_id:
        return 1
    return 0


def tutorial_locked_map(user_doc: dict) -> dict:
    """Return {resource_id: locked_qty} for the user's non-zero locked resources."""
    choice = (user_doc or {}).get("tutorial_t3_reward_choice")
    if not choice:
        return {}
    amt = tutorial_locked_amount(user_doc, choice)
    return {choice: amt} if amt > 0 else {}


async def find_user(db, ref=None, *, user_id=None, wallet=None, projection=None):
    """Find a user BY ID first (indexed, works for every account — e-mail players have no
    wallet). A wallet / e-mail is only a fallback for old records that still store one.
    `ref` = any stored reference (owner / seller / buyer field)."""
    proj = projection if projection is not None else {"_id": 0}
    for key in (user_id, ref):
        if key:
            u = await db.users.find_one({"id": key}, proj)
            if u:
                return u
    for key in (wallet, ref):
        if key:
            u = await db.users.find_one({"$or": [{"wallet_address": key}, {"email": key}]}, proj)
            if u:
                return u
    return None
