"""
GRAM City Builder API - Main Server
=================================

Модульная структура:
- core/          - Базовые компоненты (database, models, constants, helpers, dependencies)
- routes/        - API роутеры (withdrawal.py и др.)
- security/      - 2FA, Passkeys, безопасность

Основные разделы этого файла:
- Строки 1-100:     Импорты и инициализация
- Строки 100-450:   Константы и конфигурации
- Строки 450-660:   Модели данных
- Строки 660-940:   Auth Routes
- Строки 940-1410:  GRAM Island Routes  
- Строки 1410-1900: Business & Patronage Routes
- Строки 1900-2150: Banking Routes (2FA защита!)
- Строки 2150-3000: Cities & Plots Routes
- Строки 3000-4700: Trade & Marketplace Routes
- Строки 4700-4840: Withdrawal Routes (2FA защита!)
- Строки 4840-6100: Admin Routes
- Строки 6100-8000: Contract Deployer & Additional Routes
- Строки 8000-8610: Telegram & App Events

Смотрите ARCHITECTURE.md для полной документации.
"""

from fastapi import FastAPI, APIRouter, HTTPException, Depends, BackgroundTasks, WebSocket, WebSocketDisconnect, Request, Header, UploadFile, File, Body
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from pymongo import ReturnDocument
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict, ValidationError
from typing import List, Optional, Dict, Any, Union
import uuid
from datetime import datetime, timezone, timedelta
from core.dtutils import to_aware
import jwt  # PyJWT (python-jose: unpatched CVEs and not in requirements)
from jwt import PyJWTError as JWTError
import math
import asyncio
import json
from tonsdk.utils import Address

# Import TON integration and background tasks
from ton_integration import ton_client, init_ton_client, close_ton_client, validate_ton_address
from background_tasks import (
    init_scheduler, start_scheduler, shutdown_scheduler, 
    trigger_auto_collection_now
)
from payment_monitor import init_payment_monitor, stop_payment_monitor
from contract_deployer import get_contract_deployer
from scheduler_leader import start_leader_loop as _start_leader_loop, shutdown_leader as _shutdown_leader, is_leader as _is_scheduler_leader

# Import new business system V2.0
from business_config import (
    BUSINESSES, TIER_TAXES, PATRON_BONUSES, RESOURCE_WEIGHTS, RESOURCE_TYPES,
    WAREHOUSE_CONFIG, PATRON_TAX_RATE, INSTANT_WITHDRAWAL_FEE, TURNOVER_TAX_RATE,
    MAINTENANCE_COSTS, BUSINESS_LEVELS, MIDNIGHT_DECAY_RATE, MIN_PRICE_TON,
    NPC_PRICE_FLOOR, NPC_PRICE_CEILING, MONOPOLY_THRESHOLD,
    ESTIMATED_DAILY_INCOME, PATRONAGE_EFFECTS, UPGRADE_COST_MULTIPLIER,
    calculate_upgrade_cost, get_production, get_consumption, get_consumption_breakdown,
    calculate_effective_production, calculate_effective_income,
    get_daily_wear, get_storage_capacity, get_expansion_slot_capacity,
    get_patron_bonus, check_resource_requirements, calculate_repair_cost,
    get_business_full_stats, get_all_businesses_summary,
    get_estimated_daily_income, get_patron_effect,
    BUSINESS_KEY_MAP, TIER3_BUFFS, get_warehouse_weight,
)
from game_systems import (
    PatronageSystem, BusinessEconomics, WarehouseSystem,
    TaxSystem, NPCMarketSystem, InflationSystem, BankruptcySystem,
    EventsSystem, EconomicTickEngine, IncomeCollector, BankingSystem,
    get_user_production_buff, resolve_business_buff, buff_multiplier,
    _is_contract_active,
)
from ton_island import generate_ton_island_map, get_cell_at, get_neighbors, ZONES

# Import business financial model
from business_model import (
    get_production_at_level, get_requirements_at_level, get_upgrade_cost,
    get_business_tier, get_tax_rate_for_business, get_all_levels_info,
    BUSINESS_TIERS, BUSINESS_NAMES_RU, TIER_NAMES,
    BASE_PRODUCTION, BASE_REQUIREMENTS, LEVEL_MULTIPLIERS, UPGRADE_COSTS
)

# Import chat handler
from chat_handler import chat_router, set_db as set_chat_db, chat_websocket_handler

# Import support handler
import support_handler
from support_handler import (
    support_router,
    support_agent_router,
    support_admin_router,
    init_support,
    support_user_ws_handler,
    support_agent_ws_handler,
    auto_reclaim_inactive_chats,
    auto_close_user_inactive_chats,
    cleanup_empty_chats,
)
from core.helpers import find_user, available_balance_ton, resolve_owner_keys, owner_businesses_query, nz_or, owner_key
from core.helpers import get_businesses_query, is_owner, get_user_identifiers as _helpers_get_user_identifiers
from core.credit_repayment import apply_credit_deduction, estimate_credit_deduction

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
# Pool sizing is env-configurable so a small single-node deployment can cap the
# socket count and avoid overwhelming (OOM-crashing) mongod. Defaults are sane
# for a modest VPS; raise MONGO_MAX_POOL_SIZE for high-concurrency clusters.
import quests as quest_engine  # in-game quests (Путь новичка, daily/weekly goals)
from core import warehouse as warehouse_rules  # ONE warehouse rule (used/capacity/free/full)
import analytics  # retention analytics (cohorts, funnel, DAU)
import comeback  # comeback bonus + streak shields
import smart_notify  # smart notifications (warehouse/durability/price), in-app + Telegram
import market_maker  # the City Market (system market maker)
import leagues  # weekly leagues (page «Общение»)
import reconciliation  # payments reconciliation («Сверка»)
import boosters  # «Усилители»: non-tradable items (auto-shift, guard, repair, T3)
import city_pass  # City Pass (seasonal pass)
import city_sprites  # admin fine-tuning of the city-map building sprites
mongo_url = os.environ['MONGO_URL']
_MONGO_MAX_POOL = int(os.environ.get('MONGO_MAX_POOL_SIZE', '100'))
_MONGO_MIN_POOL = int(os.environ.get('MONGO_MIN_POOL_SIZE', '5'))
_MONGO_SRV_TIMEOUT = int(os.environ.get('MONGO_SERVER_SELECTION_TIMEOUT_MS', '5000'))
client = AsyncIOMotorClient(
    mongo_url,
    maxPoolSize=_MONGO_MAX_POOL,
    minPoolSize=_MONGO_MIN_POOL,
    maxIdleTimeMS=60000,
    waitQueueTimeoutMS=10000,
    serverSelectionTimeoutMS=_MONGO_SRV_TIMEOUT,
    connectTimeoutMS=10000,
    retryWrites=True,
    compressors=os.environ.get('MONGO_COMPRESSORS', 'zlib') or None,
    zlibCompressionLevel=int(os.environ.get('MONGO_ZLIB_LEVEL', '6')),
)
db = client[os.environ['DB_NAME']]
from core.pii_crypto import wrap_database as _wrap_pii
db = _wrap_pii(db)   # personal data encrypted at rest when PII_ENC_KEY / PII_INDEX_KEY are set

# JWT Configuration
from security_middleware import (
    get_or_generate_jwt_secret, SecurityHeadersMiddleware, limiter,
    check_login_lockout, record_login_failure, record_login_success,
    validate_password_strength, init_lockout_store,
)
SECRET_KEY = get_or_generate_jwt_secret()
ADMIN_SECRET = os.environ.get('ADMIN_SECRET', '')  # no public default; see startup_security_check()

# Security guard: block startup in production with missing/known-default secrets.
try:
    from security_checks import startup_security_check
    startup_security_check(admin_secret=ADMIN_SECRET, jwt_secret=SECRET_KEY)
except RuntimeError:
    raise
except Exception as _sc_e:  # never let the check itself crash a dev start
    logging.getLogger(__name__).warning(f"startup_security_check skipped: {_sc_e}")
ADMIN_WALLET = os.environ.get('ADMIN_WALLET_ADDRESS') or os.environ.get('ADMIN_WALLET') or None
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = int(os.environ.get("ACCESS_TOKEN_EXPIRE_DAYS", "7"))  # F25: default 7d (was 30d)

# Create the main app
try:                                   # orjson: several times faster JSON encoding than the stdlib
    from fastapi.responses import ORJSONResponse as _DefaultResponse
    import orjson as _orjson  # noqa: F401
except Exception:                      # pragma: no cover - fallback when orjson is missing
    from fastapi.responses import JSONResponse as _DefaultResponse
app = FastAPI(title="GRAM City Builder API", default_response_class=_DefaultResponse)
# compress every response >= 1 KB (JSON shrinks 4-10x); websockets are not affected
from starlette.middleware.gzip import GZipMiddleware as _GZip
app.add_middleware(_GZip, minimum_size=1024, compresslevel=5)


@app.middleware("http")
async def _reject_revoked_tokens(request, call_next):
    """A token issued before users.tokens_valid_after is refused for every /api route."""
    path = request.url.path
    if path.startswith("/api/") and not path.startswith("/api/auth/login"):
        tok = None
        h = request.headers.get("authorization") or ""
        if h.lower().startswith("bearer "):
            tok = h.split(" ", 1)[1].strip()
        elif request.cookies.get("access_token"):
            tok = request.cookies.get("access_token")
        if tok:
            try:
                _p = jwt.decode(tok, SECRET_KEY, algorithms=[ALGORITHM])
            except Exception:
                _p = None                       # invalid / expired tokens are handled by the handlers
            if _p:
                from core.token_revocation import is_revoked as _is_revoked
                if await _is_revoked(db, _p):
                    from fastapi.responses import JSONResponse as _JR
                    return _JR({"detail": "Сессия завершена — войдите снова"}, status_code=401)
    return await call_next(request)
from core.injection_guard import InjectionGuard as _InjectionGuard
app.add_middleware(_InjectionGuard)   # no MongoDB operators in JSON bodies
api_router = APIRouter(prefix="/api")
admin_router = APIRouter(prefix="/api/admin")
public_router = APIRouter(prefix="/api/public")  # Public endpoints without auth
from auth_cookie import CookieOrBearer
security = CookieOrBearer(auto_error=False)
oauth2_scheme = CookieOrBearer(auto_error=True)


# ---- TON Connect manifest (dynamic) ----
# Wallets fetch this URL to get app metadata. We respond with the origin
# derived from the actual request, so it works on any preview/production host.
_TC_METHODS = ["GET", "HEAD"]


@app.api_route("/api/tonconnect-manifest.json", methods=_TC_METHODS)
@app.api_route("/api/tonconnect-manifest-v2.json", methods=_TC_METHODS)
@app.api_route("/api/tonconnect-manifest-v3.json", methods=_TC_METHODS)
@app.api_route("/api/tonconnect-manifest-v4.json", methods=_TC_METHODS)
@app.api_route("/api/tonconnect-manifest-v5.json", methods=_TC_METHODS)
@app.api_route("/api/tonconnect-manifest-v6.json", methods=_TC_METHODS)
async def tonconnect_manifest(request: Request):
    """Return TON Connect manifest with origin matched to the requesting host."""
    # Determine outward-facing origin (respect proxy headers like X-Forwarded-Proto/Host)
    forwarded_proto = request.headers.get("x-forwarded-proto")
    forwarded_host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    scheme = forwarded_proto or request.url.scheme or "https"
    host = forwarded_host or request.url.netloc
    origin = f"{scheme}://{host}"
    # Wallets render iconUrl directly. Spec requires:
    # • PNG/JPG (no SVG/ICO) • ≥ 180×180 • square • no alpha transparency.
    # • Edge-to-edge content — wallets apply their own rounded-corner mask, so
    #   any dark margins in the PNG show up as ugly black corners on top of
    #   their preview circle.
    # `tonconnect-icon-v2.png` is the cleaned-up 1024×1024 RGB version with
    # the gradient filling all four corners.
    # Serve the icon from the backend `/api/` path (guaranteed to route to the
    # backend on every deployment). Relying on the frontend static host for
    # `/tonconnect-icon-v2.png` was fragile — some SPA/nginx setups answered
    # that path with `index.html`, so the wallet saw a broken image. The
    # backend endpoint below always returns the real PNG with the right
    # content-type, so the project icon shows up in the TON Connect dialog.
    # Telegram Wallet pre-validates iconUrl with a HEAD request — the manifest
    # and icon routes therefore accept both GET and HEAD (405 on HEAD made the
    # wallet render a broken image while OKX/Tonkeeper, which only GET, worked).
    from fastapi.responses import JSONResponse
    return JSONResponse(
        {
            "url": origin,
            "name": "GRAM CITY",
            "iconUrl": f"{origin}/api/tonconnect-icon-v3.png",
            "termsOfUseUrl": f"{origin}/terms",
            "privacyPolicyUrl": f"{origin}/privacy",
        },
        headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=300"},
    )


@app.api_route("/api/tonconnect-icon.png", methods=_TC_METHODS)
@app.api_route("/api/tonconnect-icon-v2.png", methods=_TC_METHODS)
@app.api_route("/api/tonconnect-icon-v3.png", methods=_TC_METHODS)
async def tonconnect_icon():
    """Serve the TON Connect project icon (favicon_512.png, 512×512 RGB) directly
    from the backend. Supports HEAD so wallets that pre-validate the asset
    (Telegram Wallet) accept it."""
    from fastapi.responses import FileResponse
    base = os.path.dirname(os.path.abspath(__file__))
    for name in ("tonconnect-icon-gramcity.png", "favicon_512.png", "tonconnect-icon-favicon.png", "tonconnect-icon.png"):
        p = os.path.join(base, "static", name)
        if os.path.exists(p):
            return FileResponse(
                p,
                media_type="image/png",
                headers={
                    "Cache-Control": "public, max-age=86400",
                    "Access-Control-Allow-Origin": "*",
                    "Cross-Origin-Resource-Policy": "cross-origin",
                },
            )
    # Last-resort: the copy shipped with the frontend build.
    fp = os.path.join(base, "..", "frontend", "public", "favicon_512.png")
    return FileResponse(fp, media_type="image/png", headers={"Access-Control-Allow-Origin": "*"})


# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Alliance notifications (in-app + telegram bridge, 8 languages)
try:
    from alliance_notifications import send_alliance_notification
except ImportError:  # pragma: no cover
    async def send_alliance_notification(*args, **kwargs):  # type: ignore
        return None

# Online users tracking
online_users = set()
last_activity = {}

# WebSocket Connection Manager — shared singleton from core.websocket so that
# any module (routes/tenders._notify_user, ws_manager.send_personal, etc.) sends
# to the SAME connection map as the @app.websocket("/api/ws/{user_id}") endpoint
# accepts into. Previously there were two unrelated instances which silently
# dropped every push notification (broken: #7 — no notification sound).
from core.websocket import manager as _shared_ws_manager, ConnectionManager  # noqa: E402

manager = _shared_ws_manager

# TON address helper functions
def to_raw(address_str):
    """Convert TON address to raw format"""
    try:
        return Address(address_str).to_string(is_user_friendly=False)
    except Exception:
        return address_str

def to_user_friendly(raw_address):
    """Convert raw TON address to user-friendly format (UQ format for mainnet)"""
    try:
        # UQ format = user_friendly=True, bounceable=True, testnet=False (mainnet)
        return Address(raw_address).to_string(is_user_friendly=True, is_bounceable=True, is_testnet=False)
    except Exception:
        return raw_address


# Reverse mapping: CITY_BUSINESSES key -> BUSINESSES key
REVERSE_KEY_MAP = {v: k for k, v in BUSINESS_KEY_MAP.items()}

def resolve_business_config(business_type: str) -> dict:
    """Get BUSINESSES config for a business type, handling key mismatches"""
    config = BUSINESSES.get(business_type)
    if config:
        return config
    # Try mapped key
    mapped = BUSINESS_KEY_MAP.get(business_type, business_type)
    return BUSINESSES.get(mapped, {})


# ==================== GAME CONSTANTS ====================

# Tier-1 (1st-echelon) resources — used for the per-account starter resource
# assignment and the Trial Center business.
TIER1_RESOURCES = ["energy", "scrap", "quartz", "cu", "traffic", "cooling", "biomass"]

RESALE_COMMISSION = 0.15  # 15% tax on resale to prevent speculation
DEMOLISH_COST = 0.05  # 5% of business cost to demolish

# ==================== OWNERSHIP HELPER ====================
async def get_user_identifiers(current_user) -> dict:
    """Thin wrapper: the one implementation is core.helpers.get_user_identifiers."""
    return await _helpers_get_user_identifiers(db, current_user)

# is_owner: single implementation in core/helpers.py (imported above)

def get_user_filter(user: dict) -> dict:
    """Get MongoDB filter to find user by best available identifier"""
    if user.get("email"):
        return {"email": user["email"]}
    if user.get("wallet_address"):
        return {"wallet_address": user["wallet_address"]}
    return {"id": user.get("id")}


# Mongo projection that hides ALL credential/secret fields from any user
# document returned to the client (even admins must never receive these).
USER_SECRET_PROJECTION = {
    "_id": 0, "hashed_password": 0, "password": 0, "password_hash": 0,
    "two_factor_secret": 0, "totp_secret": 0, "backup_codes": 0,
}



async def debit_user_split(match: dict, amount: float, **kw):
    """Списание: сначала бонусный баланс, затем реальный (см. core.balance)."""
    from core.balance import debit_user_split as _split
    return await _split(db, match, amount, **kw)


async def _insufficient_funds(user_doc, need_ton: float):
    """HTTP 400 «Недостаточно средств» на языке пользователя (бонус + реальный)."""
    from core.balance import insufficient_detail, total_available_ton
    from core.notif_i18n import user_lang
    return HTTPException(status_code=400, detail=insufficient_detail(user_lang(user_doc), need_ton, total_available_ton(user_doc)))


async def credit_user_balance(match: dict, amount: float, to_bonus: bool):
    """Credit TON to either bonus_balance (locked) or balance_ton (real)."""
    amount = float(amount or 0)
    if amount <= 0:
        return
    field = "bonus_balance" if to_bonus else "balance_ton"
    inc = {field: amount}
    if not to_bonus:
        inc["total_income"] = amount
    await db.users.update_one(match, {"$inc": inc})


# Daily activity thresholds for the daily-reward gate (buy AND sell any resource).
DAILY_BUY_REQUIRED = 30
DAILY_SELL_REQUIRED = 95


async def bump_daily_trade(user_identifiers, bought: int = 0, sold: int = 0):
    """Track a user's daily resource-trade activity (units bought / sold today).

    Resets counters when the calendar day (UTC) changes, then increments.
    `user_identifiers` may be a user dict, a single id/wallet string, or a list
    of identifiers (id and/or wallet_address).
    """
    try:
        bought = int(bought or 0)
        sold = int(sold or 0)
        if bought <= 0 and sold <= 0:
            return
        # Resolve identifiers into an $or match.
        ids = []
        if isinstance(user_identifiers, dict):
            for f in ("id", "wallet_address"):
                if user_identifiers.get(f):
                    ids.append(user_identifiers[f])
        elif isinstance(user_identifiers, (list, tuple, set)):
            ids = [x for x in user_identifiers if x]
        elif user_identifiers:
            ids = [user_identifiers]
        if not ids:
            return
        match = {"$or": [{"id": x} for x in ids] + [{"wallet_address": x} for x in ids]}
        from core.timeutil import msk_today_str
        today = msk_today_str()          # game day = Moscow time (same as the daily reward)
        # Reset stale counters first (only when the stored date is not today).
        await db.users.update_one(
            {"$and": [match, {"daily_trade.date": {"$ne": today}}]},
            {"$set": {"daily_trade": {"date": today, "bought": 0, "sold": 0}}},
        )
        await db.users.update_one(
            match,
            {"$set": {"daily_trade.date": today},
             "$inc": {"daily_trade.bought": bought, "daily_trade.sold": sold}},
        )
        if bought > 0:
            quest_engine.fire(ids, "market_buy", bought)
    except Exception as _e:
        logger.debug(f"bump_daily_trade failed: {_e}")


# Translate resource codes to localized names
RESOURCE_NAMES = {
    "energy": "Энергия", "cu": "Вычисления", "quartz": "Кварц", 
    "traffic": "Трафик", "cooling": "Охлаждение", "biomass": "Биомасса", "scrap": "Металлолом",
    "chips": "Микросхемы", "nft": "NFT-арт", "neurocode": "Нейрокод",
    "logistics": "Логистика", "repair_kits": "Ремкомплект", "vr_experience": "VR-опыт",
    "profit_ton": "TON-прибыль",
    "neuro_core": "Нейро-ядро", "gold_bill": "Золотой вексель", "license_token": "Лицензия",
    "luck_chip": "Фишка удачи", "war_protocol": "Боевой протокол", 
    "bio_module": "Био-модуль", "gateway_code": "Код шлюза",
}
def translate_resource_name(resource_code: str) -> str:
    return RESOURCE_NAMES.get(resource_code, resource_code)


# get_businesses_query: single implementation in core/helpers.py (imported above)
TRADE_COMMISSION = 0.0  # No trade commission - income tax applies when user receives money
RENTAL_COMMISSION = 0.10
WITHDRAWAL_COMMISSION = 0.03
MIN_WITHDRAWAL = 1.0
BASE_TAX_RATE = 0.10
PROGRESSIVE_TAX = {
    0.05: 0.12,
    0.10: 0.15,
    0.15: 0.18,
    0.20: 0.22,
    0.25: 0.25,
}

# Level system multipliers
LEVEL_CONFIG = {
    1: {"xp_required": 0, "income_mult": 1.0, "speed_mult": 1.0, "bonus": None, "upgrade_cost": 0},
    2: {"xp_required": 100, "income_mult": 1.2, "speed_mult": 1.1, "bonus": "upgrades", "upgrade_cost": 5},
    3: {"xp_required": 300, "income_mult": 1.5, "speed_mult": 1.2, "bonus": "discount_5", "upgrade_cost": 10},
    4: {"xp_required": 600, "income_mult": 1.8, "speed_mult": 1.3, "bonus": "storage", "upgrade_cost": 20},
    5: {"xp_required": 1000, "income_mult": 2.2, "speed_mult": 1.5, "bonus": "automation_1", "upgrade_cost": 35},
    6: {"xp_required": 1500, "income_mult": 2.7, "speed_mult": 1.7, "bonus": "discount_10", "upgrade_cost": 50},
    7: {"xp_required": 2200, "income_mult": 3.3, "speed_mult": 2.0, "bonus": "automation_2", "upgrade_cost": 75},
    8: {"xp_required": 3000, "income_mult": 4.0, "speed_mult": 2.3, "bonus": "vip", "upgrade_cost": 100},
    9: {"xp_required": 4000, "income_mult": 5.0, "speed_mult": 2.7, "bonus": "franchise", "upgrade_cost": 150},
    10: {"xp_required": 5500, "income_mult": 6.5, "speed_mult": 3.0, "bonus": "corporation", "upgrade_cost": 200},
}

# Player levels
PLAYER_LEVELS = {
    "novice": {"min_turnover": 0, "max_plots": 3, "max_market_share": 0.05},
    "entrepreneur": {"min_turnover": 100, "max_plots": 7, "max_market_share": 0.10},
    "businessman": {"min_turnover": 500, "max_plots": 15, "max_market_share": 0.15},
    "magnate": {"min_turnover": 2000, "max_plots": 30, "max_market_share": 0.20},
    "oligarch": {"min_turnover": 10000, "max_plots": 50, "max_market_share": 0.25},
    1: {"min_turnover": 0, "max_plots": 3, "max_market_share": 0.05},
    2: {"min_turnover": 50, "max_plots": 5, "max_market_share": 0.07},
    3: {"min_turnover": 100, "max_plots": 7, "max_market_share": 0.10},
    4: {"min_turnover": 250, "max_plots": 10, "max_market_share": 0.12},
    5: {"min_turnover": 500, "max_plots": 15, "max_market_share": 0.15},
}

# Zone configuration
ZONES = {  # noqa: F811
    "center": {"radius_max": 10, "plot_limit": 3, "price_mult": 1.0},
    "business": {"radius_max": 25, "plot_limit": 10, "price_mult": 0.7},
    "residential": {"radius_max": 40, "plot_limit": 15, "price_mult": 0.45},
    "industrial": {"radius_max": 50, "plot_limit": 20, "price_mult": 0.25},
    "outskirts": {"radius_max": 100, "plot_limit": 30, "price_mult": 0.12},
}

# Business types with full configuration
BUSINESS_TYPES = {
    "farm": {
        "name": {"en": "Farm", "ru": "Ферма", "zh": "农场"},
        "icon": "🌾",
        "sector": "primary",
        "cost": 5,
        "build_time_hours": 2,
        "materials_required": 50,
        "energy_consumption": 10,
        "produces": "crops",
        "production_rate": 100,
        "requires": None,
        "base_income": 2.4,
        "operating_cost": 0.3,
        "allowed_zones": ["residential", "industrial", "outskirts"],
        "max_per_player": 10,
        "min_builders": 1,
    },
    "power_plant": {
        "name": {"en": "Power Plant", "ru": "Электростанция", "zh": "发电厂"},
        "icon": "⚡",
        "sector": "primary",
        "cost": 20,
        "build_time_hours": 8,
        "materials_required": 300,
        "energy_consumption": 0,
        "produces": "energy",
        "production_rate": 500,
        "requires": None,
        "base_income": 2.4,
        "operating_cost": 0.8,
        "allowed_zones": ["industrial", "outskirts"],
        "max_per_player": 3,
        "min_builders": 2,
    },
    "quarry": {
        "name": {"en": "Quarry", "ru": "Карьер", "zh": "采石场"},
        "icon": "⛏️",
        "sector": "primary",
        "cost": 25,
        "build_time_hours": 10,
        "materials_required": 200,
        "energy_consumption": 80,
        "produces": "materials",
        "production_rate": 50,
        "requires": None,
        "base_income": 6.0,
        "operating_cost": 1.5,
        "allowed_zones": ["industrial", "outskirts"],
        "max_per_player": 5,
        "min_builders": 2,
    },
    "factory": {
        "name": {"en": "Factory", "ru": "Завод", "zh": "工厂"},
        "icon": "🏭",
        "sector": "secondary",
        "cost": 15,
        "build_time_hours": 6,
        "materials_required": 150,
        "energy_consumption": 50,
        "produces": "goods",
        "production_rate": 30,
        "requires": "crops",
        "consumption_rate": 50,
        "base_income": 2.88,
        "operating_cost": 1.44,
        "allowed_zones": ["business", "industrial"],
        "max_per_player": 8,
        "min_builders": 2,
    },
    "shop": {
        "name": {"en": "Shop", "ru": "Магазин", "zh": "商店"},
        "icon": "🏪",
        "sector": "tertiary",
        "cost": 10,
        "build_time_hours": 4,
        "materials_required": 100,
        "energy_consumption": 20,
        "produces": "retail",
        "production_rate": 0,
        "requires": "goods",
        "consumption_rate": 30,
        "base_income": 4.8,
        "operating_cost": 0.5,
        "allowed_zones": ["center", "business", "residential"],
        "max_per_player": 15,
        "min_builders": 1,
        "customer_flow": {"center": 100, "business": 60, "residential": 40},
    },
    "restaurant": {
        "name": {"en": "Restaurant", "ru": "Ресторан", "zh": "餐厅"},
        "icon": "🍽️",
        "sector": "tertiary",
        "cost": 12,
        "build_time_hours": 5,
        "materials_required": 120,
        "energy_consumption": 30,
        "produces": "food_service",
        "production_rate": 30,
        "requires": "crops",
        "consumption_rate": 30,
        "base_income": 5.4,
        "operating_cost": 0.86,
        "allowed_zones": ["center", "business", "residential"],
        "max_per_player": 10,
        "min_builders": 1,
    },
    "bank": {
        "name": {"en": "Bank", "ru": "Банк", "zh": "银行"},
        "icon": "🏦",
        "sector": "quaternary",
        "cost": 50,
        "build_time_hours": 24,
        "materials_required": 500,
        "energy_consumption": 40,
        "produces": "finance",
        "production_rate": 0,
        "requires": None,
        "base_income": 4.5,
        "operating_cost": 0.6,
        "allowed_zones": ["center", "business"],
        "max_per_player": 1,
        "min_builders": 3,
    },
}

# Resource prices (base) - V2.0: All prices >= MIN_PRICE_TON (0.01)
RESOURCE_PRICES = {
    "crops": 0.01,
    "energy": 0.01,
    "materials": 0.01,
    "fuel": 0.01,
    "ore": 0.01,
    "goods": 0.01,
    "refined_fuel": 0.015,
    "steel": 0.012,
    "textiles": 0.01,
    # New V2.0 resources
    "cu": 0.02,
    "quartz": 0.015,
    "traffic": 0.012,
    "cooling": 0.02,
    "biomass": 0.018,
    "scrap": 0.01,
    "chips": 0.10,
    "nft": 0.15,
    "neurocode": 0.20,
    "logistics": 0.05,
    "repair_kits": 0.08,
    "vr_experience": 0.12,
    "shares": 0.50,
}

# ==================== HELPER FUNCTIONS ====================

def calculate_plot_price(x: int, y: int) -> tuple:
    """Calculate plot price and zone based on distance from center"""
    center_x, center_y = 50, 50
    distance = math.sqrt((x - center_x)**2 + (y - center_y)**2)
    
    zone = "outskirts"
    for zone_name, config in ZONES.items():
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
    zone_mult = ZONES.get(zone, {}).get("price_mult", 0.5)
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

# Translation helper
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

# ==================== MODELS ====================

class WithdrawRequest(BaseModel):
    amount: float
    totp_code: Optional[str] = None  # 2FA code required
    withdraw_pk_token: Optional[str] = None  # Required when user has at least one passkey registered
    # Telegram Mini App biometric confirmation token (Face ID / fingerprint
    # inside the TG WebView). Alternative to `withdraw_pk_token` for users on
    # mobile Telegram where WebAuthn is not available.
    tg_biometry_token: Optional[str] = None
    # Telegram Desktop PC (или другая PC/веб-версия Telegram): WebAuthn/Passkey
    # в TG WebView недоступен, BiometricManager тоже. Клиент передаёт свежий
    # initData; сервер валидирует HMAC + связку с аккаунтом и разрешает вывод
    # только по 2FA, минуя passkey.
    tg_init_data: Optional[str] = None
    # Optional anti-fraud fields (kept optional so existing clients keep working)
    visitor_id: Optional[str] = None
    turnstile_token: Optional[str] = None

class User(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    username: Optional[str] = None
    email: Optional[str] = None
    wallet_address: Optional[str] = None
    raw_address: Optional[str] = None
    display_name: Optional[str] = None
    language: str = "en"
    level: Union[str, int] = "novice"  # Поддержка и str и int
    xp: int = 0
    balance_ton: float = 0.0
    bonus_balance: float = 0.0  # Bonus TON: spendable in-game (split-payment), NOT withdrawable
    is_active_investor: bool = False  # True only after buying a real business with real funds
    produced_resource_id: Optional[str] = None  # random Tier-1 resource assigned at account creation
    consumed_resource_id: Optional[str] = None  # random Tier-1 resource (distinct from produced)
    total_turnover: float = 0.0
    total_income: float = 0.0
    plots_owned: List[str] = []
    businesses_owned: List[str] = []
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_login: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_admin: bool = False
    roles: List[str] = []  # F17 RBAC: ["support","finance","moderation","superadmin"]

class Plot(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    x: int
    y: int
    zone: str = "outskirts"
    price: float = 10.0
    owner: Optional[str] = None
    business_id: Optional[str] = None
    is_available: bool = True
    is_rented: bool = False
    rent_price: Optional[float] = None
    renter: Optional[str] = None
    purchased_at: Optional[datetime] = None

class Business(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    plot_id: str
    owner: str
    business_type: str
    level: int = 1
    xp: int = 0
    income_rate: float = 0.0
    production_rate: float = 0.0
    storage: Dict[str, float] = {}
    connected_businesses: List[str] = []
    is_active: bool = True
    last_collection: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    building_progress: float = 100.0  # 0-100%
    builders: List[str] = []

class Transaction(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tx_type: str
    from_address: str
    to_address: Optional[str] = None
    amount_ton: float
    commission: float = 0.0
    tax: float = 0.0
    plot_id: Optional[str] = None
    business_id: Optional[str] = None
    resource_type: Optional[str] = None
    resource_amount: Optional[float] = None
    status: str = "pending"
    blockchain_hash: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None

class Contract(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    seller_id: str
    buyer_id: str
    seller_business_id: str
    buyer_business_id: str
    resource_type: str
    amount_per_hour: float
    price_per_unit: float
    is_active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None

class BuildOrder(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    plot_id: str
    owner: str
    business_type: str
    status: str = "pending"  # pending, in_progress, completed
    materials_paid: bool = False
    builders: List[str] = []
    builder_payments: Dict[str, float] = {}
    progress: float = 0.0
    estimated_completion: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

# Request models
class PurchasePlotRequest(BaseModel):
    plot_x: int
    plot_y: int

class ResalePlotRequest(BaseModel):
    plot_id: str
    resale_price: float

class BuildBusinessRequest(BaseModel):
    plot_id: str
    business_type: str

class CreateContractRequest(BaseModel):
    seller_business_id: str
    buyer_business_id: str
    resource_type: str
    amount_per_hour: float
    price_per_unit: float

class TradeResourceRequest(BaseModel):
    seller_business_id: str
    buyer_id: str
    resource_type: str
    amount: float
    price_per_unit: float

    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

# Request models
class WalletVerifyRequest(BaseModel):
    address: str
    proof: Optional[Dict[str, Any]] = None
    language: str = "en"
    username: Optional[str] = None
    email: Optional[str] = None     
    password: Optional[str] = None 

class ConfirmTransactionRequest(BaseModel):
    transaction_id: str
    blockchain_hash: Optional[str] = None

class RentPlotRequest(BaseModel):
    plot_id: str
    rent_price: float

class AcceptRentRequest(BaseModel):
    plot_id: str

# ========================== AUTH ===========================

class EmailRegister(BaseModel):
    email: str
    password: str
    username: str

class WalletAuth(BaseModel):
    address: str
    public_key: Optional[str] = None
    username: Optional[str] = None

def _coerce_user_doc(doc: dict) -> dict:
    """Coerce drifted Mongo values to the types the `User` model expects.

    Long-lived accounts accumulate slightly "off" values (xp stored as a float,
    balance_ton as '' or a non-numeric string, a list field stored as None…).
    `User(**doc)` would then raise `ValidationError` INSIDE get_current_user —
    which is not a JWTError, so it escaped the handler and surfaced as a generic
    HTTP 500 'internal error' on EVERY authenticated endpoint (e.g.
    /api/my/businesses). Sanitizing here makes auth resilient for all accounts.
    """
    d = dict(doc)

    def _f(v, default=0.0):
        try:
            if v is None or v == "":
                return default
            return float(v)
        except (ValueError, TypeError):
            return default

    def _i(v, default=0):
        try:
            if v is None or v == "":
                return default
            return int(float(v))
        except (ValueError, TypeError):
            return default

    for k in ("balance_ton", "bonus_balance", "total_turnover", "total_income"):
        if k in d:
            d[k] = _f(d.get(k), 0.0)
    if "xp" in d:
        d["xp"] = _i(d.get("xp"), 0)
    for k in ("plots_owned", "businesses_owned", "roles"):
        if k in d and not isinstance(d.get(k), list):
            d[k] = []
    if d.get("is_active_investor") is not None and not isinstance(d.get("is_active_investor"), bool):
        d["is_active_investor"] = bool(d.get("is_active_investor"))
    # datetime fields: drop unparseable values so the model default applies.
    for k in ("created_at", "last_login"):
        v = d.get(k)
        if v is not None and not isinstance(v, (str, datetime)):
            d.pop(k, None)
    return d


async def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        identifier: str = payload.get("sub")
        if not identifier:
            raise HTTPException(status_code=401, detail="Invalid token")
        token_sid = payload.get("sid")
        
        # Ищем пользователя по разным полям (wallet_address, email, username)
        user_doc = await db.users.find_one({
            "$or": [
                {"wallet_address": identifier},
                {"email": identifier},
                {"username": identifier}
            ]
        })
        
        if not user_doc:
            raise HTTPException(status_code=404, detail="Пользователь не найден")

        # Backfill composite-balance / starter fields for every account (idempotent).
        # Spec: at account creation assign a random produced Tier-1 resource and a
        # DISTINCT consumed Tier-1 resource, and initialise bonus/investor fields.
        _starter_set = {}
        if not user_doc.get("id"):
            # Legacy wallet/Telegram drafts were created without a stable uuid
            # `id`. Backfill one so business.owner (=id) always maps back to the
            # account — otherwise trial accrual & other id-keyed lookups fail.
            import uuid as _uuid_bf
            _starter_set["id"] = str(_uuid_bf.uuid4())
            user_doc["id"] = _starter_set["id"]
        if user_doc.get("bonus_balance") is None:
            _starter_set["bonus_balance"] = 0.0
        if user_doc.get("is_active_investor") is None:
            _starter_set["is_active_investor"] = False
        if not user_doc.get("produced_resource_id") or not user_doc.get("consumed_resource_id"):
            import random as _rnd
            prod = _rnd.choice(TIER1_RESOURCES)
            cons = _rnd.choice([r for r in TIER1_RESOURCES if r != prod])
            _starter_set["produced_resource_id"] = prod
            _starter_set["consumed_resource_id"] = cons
            user_doc["produced_resource_id"] = prod
            user_doc["consumed_resource_id"] = cons
        if _starter_set:
            await db.users.update_one({"_id": user_doc["_id"]}, {"$set": _starter_set})
            user_doc.update({k: v for k, v in _starter_set.items()})
        
        # NOTE: single-session enforcement intentionally DISABLED — a token
        # keeps working until the user explicitly logs out (no self-kick when
        # another login rotates session_id). See core/dependencies.py.
        current_sid = user_doc.get("session_id")
        if token_sid and not current_sid:
            # User has no recorded session — adopt this one (first request after deploy)
            await db.users.update_one({"_id": user_doc["_id"]}, {"$set": {"session_id": token_sid}})
        
        # Normalize is_admin field to boolean
        if "is_admin" in user_doc:
            if isinstance(user_doc["is_admin"], str):
                user_doc["is_admin"] = user_doc["is_admin"].lower() in ("true", "1", "yes")
            elif not isinstance(user_doc["is_admin"], bool):
                user_doc["is_admin"] = False
        else:
            user_doc["is_admin"] = False
        
        # Auto-grant admin if wallet matches ADMIN_WALLET_ADDRESS from env
        wallet_addr = user_doc.get("wallet_address", "") or user_doc.get("wallet_address_raw", "")
        if ADMIN_WALLET and wallet_addr and (wallet_addr == ADMIN_WALLET or wallet_addr.lower() == ADMIN_WALLET.lower()):
            user_doc["is_admin"] = True
        
        return User(**_coerce_user_doc(user_doc))
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    except ValidationError as ve:
        # Coercion above covers known drift; if the doc is still invalid, log the
        # exact field and fail with a clear message instead of a cryptic 500 that
        # blocks the whole app.
        logger.error("[AUTH] User model still invalid after coercion for %s: %s",
                     locals().get("identifier"), ve)
        raise HTTPException(status_code=422, detail="account data invalid")
    
async def get_current_admin(current_user: User = Depends(get_current_user)):
    # V4: Strict admin check - require is_admin flag OR valid ADMIN_WALLET match
    # S5: Do NOT leak admin-route existence — generic 'Forbidden' message
    if current_user.is_admin:
        return current_user
    if ADMIN_WALLET and current_user.wallet_address and current_user.wallet_address == ADMIN_WALLET:
        return current_user
    raise HTTPException(status_code=403, detail="Forbidden")


# S8: Admin 2FA enforcement for dangerous actions
async def get_current_admin_with_2fa(
    request: Request,
    admin: User = Depends(get_current_admin)
):
    admin_doc = await db.users.find_one({"id": admin.id}, {"_id": 0})
    if not admin_doc and admin.email:
        admin_doc = await db.users.find_one({"email": admin.email}, {"_id": 0})
    if admin_doc and admin_doc.get("is_2fa_enabled") and admin_doc.get("two_factor_secret"):
        code = request.headers.get("X-Admin-TOTP") or request.headers.get("x-admin-totp")
        if not code:
            raise HTTPException(status_code=401, detail="TOTP required for this admin action")
        try:
            import pyotp
            from security.totp_crypto import decrypt_secret
            totp = pyotp.TOTP(decrypt_secret(admin_doc["two_factor_secret"]))
            if not totp.verify(str(code), valid_window=1):
                raise HTTPException(status_code=401, detail="Invalid TOTP code")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid TOTP code")
    return admin

# Alias for compatibility
get_admin_user = get_current_admin


# ==================== F17: RBAC (role-based access control) ====================
# Scopes: "support", "finance", "moderation", "superadmin".
# Backward-compat: a legacy admin (is_admin=true with no explicit roles) is
# treated as "superadmin" so existing accounts keep full access. Granular
# admins get only their assigned scopes.
VALID_SCOPES = {"support", "finance", "moderation", "superadmin"}


async def _resolve_admin_scopes(admin: "User") -> set:
    admin_doc = await db.users.find_one(
        {"id": admin.id}, {"_id": 0, "roles": 1, "is_admin": 1}
    )
    if not admin_doc and admin.email:
        admin_doc = await db.users.find_one(
            {"email": admin.email}, {"_id": 0, "roles": 1, "is_admin": 1}
        )
    roles = set((admin_doc or {}).get("roles") or [])
    # Legacy admin without explicit roles → full access.
    if (admin.is_admin or (admin_doc or {}).get("is_admin")) and not roles:
        roles = {"superadmin"}
    return roles


def require_scope(scope: str):
    """Dependency factory enforcing an RBAC scope on top of admin + 2FA gate.

    Keeps the existing 2FA soft-mode behaviour (via get_current_admin_with_2fa)
    and additionally checks that the admin holds `scope` (or "superadmin").
    """
    async def _dep(admin: "User" = Depends(get_current_admin_with_2fa)) -> "User":
        roles = await _resolve_admin_scopes(admin)
        if "superadmin" in roles or scope in roles:
            return admin
        raise HTTPException(status_code=403, detail="Forbidden")
    return _dep



@api_router.get("/patrons")
async def get_available_patrons(authorization: Optional[str] = Header(None)):
    """Get all available patron businesses (Tier 3) — excludes own T3 businesses for the requester."""
    from auth_handler import SECRET_KEY, ALGORITHM
    import jwt as _jwt
    from jwt import PyJWTError as _JWTError

    # Best-effort: identify caller to skip their own T3 patrons.
    caller_user = None
    if authorization and authorization.startswith("Bearer "):
        try:
            payload = _jwt.decode(authorization.split(" ", 1)[1], SECRET_KEY, algorithms=[ALGORITHM])
            sub = payload.get("sub")
            if sub:
                caller_user = await db.users.find_one(
                    {"$or": [{"email": sub}, {"username": sub}, {"wallet_address": sub}]},
                    {"_id": 0, "id": 1, "email": 1, "username": 1, "wallet_address": 1},
                )
        except _JWTError:
            caller_user = None

    caller_owner_keys = set()
    if caller_user:
        for k in ("id", "email", "username", "wallet_address"):
            v = caller_user.get(k)
            if v:
                caller_owner_keys.add(v)

    patrons = await db.businesses.find(
        {"business_type": {"$in": ["validator", "gram_bank", "dex", "casino", "arena", "incubator", "bridge"]}},
        {"_id": 0}
    ).to_list(100)

    from business_config import TIER3_BUFFS as _T3_BUFFS_LOCAL

    result = []
    for p in patrons:
        # Skip own T3 businesses — you can't be your own patron
        if p.get("owner") in caller_owner_keys:
            continue

        config = BUSINESSES.get(p.get("business_type"), {})
        patron_type = config.get("patron_type")
        bonus_info = PATRON_BONUSES.get(patron_type, {})

        owner = await db.users.find_one(
            {"$or": [
                {"id": p.get("owner")},
                {"wallet_address": p.get("owner")},
                {"email": p.get("owner")},
                {"username": p.get("owner")},
            ]},
            {"_id": 0, "username": 1, "display_name": 1, "email": 1},
        )

        # Currently selected buff metadata (the one this patron grants by default to its vassals)
        pb_id = p.get("patron_buff")
        patron_buff = None
        if pb_id and pb_id in _T3_BUFFS_LOCAL:
            buff_def = _T3_BUFFS_LOCAL[pb_id]
            patron_buff = {
                "id": buff_def.get("id"),
                "name": buff_def.get("name"),
                "icon": buff_def.get("icon"),
                "description": buff_def.get("description"),
                "effect": buff_def.get("effect"),
            }

        result.append({
            "id": p["id"],
            "type": p["business_type"],
            "patron_type": patron_type,
            "level": p.get("level", 1),
            "durability": p.get("durability", 100),
            "owner": p.get("owner"),
            "owner_name": (owner.get("display_name") or owner.get("username") or owner.get("email")) if owner else "Unknown",
            "bonus_type": bonus_info.get("type"),
            "bonus_range": bonus_info.get("multiplier_range"),
            "current_bonus": PatronageSystem.get_patron_bonus_multiplier(patron_type, p.get("level", 1), bonus_info.get("type", "income")),
            "icon": config.get("icon"),
            "name": config.get("name"),
            "patron_buff": patron_buff,
            "on_sale": bool(p.get("on_sale")),
        })

    return {"patrons": result}

@api_router.post("/partner/bind")
async def partner_bind(payload: dict = Body(default={}), current_user: User = Depends(get_current_user)):
    """Bind an EXISTING (already registered) user to a partner if they opened the
    app via that partner's referral link AND are not yet bound to ANY partner.
    New users are bound automatically at registration; this covers users who were
    already in the project. Marked partner_is_new=False so they do NOT inflate the
    'new users' (Перешло по ссылке) metric. Returns the (possibly updated) binding."""
    ref = (payload.get("ref") or payload.get("ref_code") or payload.get("start_param") or "").strip()
    from routes.partner_programs import parse_ref_user_id, is_partner_referrer, check_partner_conditions
    ref = parse_ref_user_id(ref) if ref else None
    user = await db.users.find_one({"id": current_user.id}, {"_id": 0})
    bound = False
    if ref and user and not user.get("partner_ref_id") and str(ref) != str(current_user.id):
        program = await is_partner_referrer(db, ref)
        if program:
            await db.users.update_one({"id": current_user.id}, {"$set": {
                "partner_ref_id": str(ref),
                # Cutoff for partner-task progress = the moment they (re)joined
                # via the partner link, NOT their original registration date, so
                # land/spend earned BEFORE joining does not count.
                "partner_joined_at": datetime.now(timezone.utc).isoformat(),
                "partner_is_new": False,
                "partner_task_completed": bool(user.get("partner_task_completed", False)),
            }})
            bound = True
            try:
                await check_partner_conditions(db, current_user.id)
            except Exception:
                pass
    return {"ok": True, "bound": bound}



@api_router.post("/business/{business_id}/set-patron")
async def set_business_patron(business_id: str, patron_id: Optional[str] = None, current_user: User = Depends(get_current_user)):
    """Set or remove patron for a business"""
    business = await db.businesses.find_one({"id": business_id}, {"_id": 0})
    if not business:
        raise HTTPException(status_code=404, detail="Бизнес не найден")
    
    ui = await get_user_identifiers(current_user)
    if not ui["user"] or not is_owner(business, ui["ids"]):
        raise HTTPException(status_code=403, detail="Это не ваш бизнес")
    
    # Check cooldown
    can_change, days_remaining = PatronageSystem.can_change_patron(business.get("last_patron_change"))
    if not can_change:
        raise HTTPException(
            status_code=400, 
            detail=f"Смена патрона доступна через {days_remaining} дней"
        )
    
    # If removing patron
    if not patron_id:
        await db.businesses.update_one(
            {"id": business_id},
            {"$set": {
                "patron_id": None,
                "last_patron_change": datetime.now(timezone.utc).isoformat()
            }}
        )
        return {"status": "patron_removed"}
    
    # Verify patron exists and is valid
    patron = await db.businesses.find_one({"id": patron_id}, {"_id": 0})
    if not patron:
        raise HTTPException(status_code=404, detail="Патрон не найден")
    
    if not PatronageSystem.can_be_patron(patron.get("business_type")):
        raise HTTPException(status_code=400, detail="Этот бизнес не может быть патроном")
    
    # Cannot be own patron — check ALL identifiers (id, email, username, wallet_address)
    if patron.get("owner") in ui["ids"]:
        raise HTTPException(status_code=400, detail="Нельзя назначить свой собственный T3 бизнес патроном")
    
    await db.businesses.update_one(
        {"id": business_id},
        {"$set": {
            "patron_id": patron_id,
            "last_patron_change": datetime.now(timezone.utc).isoformat()
        }}
    )
    
    patron_config = BUSINESSES.get(patron.get("business_type"), {})
    
    return {
        "status": "patron_set",
        "patron": {
            "id": patron_id,
            "type": patron.get("business_type"),
            "level": patron.get("level", 1),
            "owner": patron.get("owner"),
            "bonus_type": patron_config.get("patron_type")
        }
    }

# ==================== WAREHOUSE ROUTES ====================

@api_router.get("/warehouses/rentals")
async def get_warehouse_rentals():
    """Get available warehouse rentals"""
    rentals = await db.warehouse_rentals.find(
        {"status": "available"},
        {"_id": 0}
    ).to_list(50)
    
    result = []
    for r in rentals:
        owner = await find_user(db, r.get("owner_id"), projection={"_id": 0, "username": 1})
        result.append({
            **r,
            "owner_name": owner.get("username") if owner else "Unknown"
        })
    
    return {"rentals": result}

@api_router.post("/warehouses/create-rental")
async def create_warehouse_rental(
    slots: int,
    price_per_slot: float,
    current_user: User = Depends(get_current_user)
):
    """Create warehouse rental listing"""
    if slots <= 0 or price_per_slot <= 0:
        raise HTTPException(status_code=400, detail="Некорректные параметры")
    
    # Check user has warehouse capacity
    _wh_owner_keys = await resolve_owner_keys(db, current_user.wallet_address or current_user.id)
    user_businesses = await db.businesses.find(
        owner_businesses_query(_wh_owner_keys),
        {"_id": 0}
    ).to_list(50)
    
    total_capacity = sum(b.get("storage", {}).get("capacity", 0) for b in user_businesses)
    total_used = sum(
        sum(b.get("storage", {}).get("items", {}).values()) 
        for b in user_businesses
    )
    
    available = total_capacity - total_used
    
    if slots > available:
        raise HTTPException(
            status_code=400, 
            detail=f"Недостаточно свободного места: доступно {available}, запрошено {slots}"
        )
    
    rental = WarehouseSystem.create_rental_offer(
        current_user.wallet_address,
        f"warehouse_{current_user.wallet_address}",
        slots,
        price_per_slot
    )
    
    await db.warehouse_rentals.insert_one(rental.copy())
    
    return {"status": "created", "rental": rental}

@api_router.post("/warehouses/rent/{rental_id}")
async def rent_warehouse(rental_id: str, days: int = 7, current_user: User = Depends(get_current_user)):
    """Rent warehouse space"""
    rental = await db.warehouse_rentals.find_one({"id": rental_id}, {"_id": 0})
    if not rental:
        raise HTTPException(status_code=404, detail="Аренда не найдена")
    
    if rental["status"] != "available":
        raise HTTPException(status_code=400, detail="Аренда недоступна")
    
    if rental["owner_id"] == current_user.wallet_address:
        raise HTTPException(status_code=400, detail="Нельзя арендовать у себя")
    
    # Calculate cost
    cost_info = WarehouseSystem.calculate_rental_cost(
        rental["slots_available"],
        rental["price_per_slot_per_day"],
        days
    )
    
    # Check balance (bonus + real)
    user = await db.users.find_one({"id": current_user.id}, {"_id": 0})
    _avail_wr = float(user.get("bonus_balance", 0) or 0) + float(user.get("balance_ton", 0) or 0)
    if _avail_wr < cost_info["total"]:
        raise HTTPException(status_code=400, detail="Недостаточно средств")
    
    # Process payment
    owner_receives = cost_info["base_cost"]
    
    # Bonus funds first, then real balance (atomic split debit).
    _wr_upd = await debit_user_split({"id": current_user.id}, cost_info["total"])
    if not _wr_upd.get("ok"):
        raise HTTPException(status_code=400, detail="Недостаточно средств")
    
    await db.users.update_one(
        {"wallet_address": rental["owner_id"]},
        {"$inc": {"balance_ton": owner_receives}}
    )
    
    # Treasury tax
    await db.admin_stats.update_one(
        {"type": "treasury"},
        {"$inc": {"rental_tax": cost_info["tax"], "total_tax": cost_info["tax"]}},
        upsert=True
    )
    
    # Update rental
    expires_at = datetime.now(timezone.utc) + timedelta(days=days)
    await db.warehouse_rentals.update_one(
        {"id": rental_id},
        {"$set": {
            "status": "rented",
            "renter_id": owner_key(current_user),
            "rented_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": expires_at.isoformat()
        }}
    )
    
    return {
        "status": "rented",
        "cost": cost_info,
        "expires_at": expires_at.isoformat(),
        "slots": rental["slots_available"]
    }

# ==================== BANKING ROUTES ====================

@api_router.get("/banks")
async def get_available_banks():
    """Get banks available for instant withdrawal"""
    banks = await db.businesses.find(
        {"business_type": "gram_bank", "durability": {"$gte": 50}},
        {"_id": 0}
    ).to_list(20)
    
    result = BankingSystem.get_available_banks(banks)
    # Override fee_rate with each bank's owner-configured value (Block A/B).
    for b in result:
        settings = await db.credit_bank_settings.find_one({"bank_id": b.get("id")}, {"_id": 0})
        if settings and settings.get("instant_fee") is not None:
            b["fee_rate"] = round(min(float(settings["instant_fee"]), 0.05), 4)
    return {"banks": result}

class InstantWithdrawRequest(BaseModel):
    amount: float
    bank_id: str
    totp_code: Optional[str] = None
    withdraw_pk_token: Optional[str] = None  # Required when user has at least one passkey registered
    tg_biometry_token: Optional[str] = None  # Telegram Mini App biometric token
    tg_init_data: Optional[str] = None  # Telegram PC: раз валидирован → passkey не требуется
    visitor_id: Optional[str] = None
    turnstile_token: Optional[str] = None

@api_router.post("/withdraw/instant")
async def instant_withdrawal(
    data: InstantWithdrawRequest,
    current_user: User = Depends(get_current_user)
):
    """Create instant withdrawal via bank"""
    amount = data.amount
    bank_id = data.bank_id
    totp_code = data.totp_code
    
    from core.i18n_messages import wmsg
    _lang = getattr(current_user, "language", None) or "en"

    if amount < MIN_WITHDRAWAL:
        raise HTTPException(status_code=400, detail=wmsg(_lang, "min_withdrawal", min_amount=MIN_WITHDRAWAL))
    
    ui = await get_user_identifiers(current_user)
    if not ui["user"]:
        raise HTTPException(status_code=400, detail=wmsg(_lang, "user_not_found"))
    user = ui["user"]
    _lang = user.get("language") or _lang
    
    # Check if withdrawal is admin-blocked
    blocked_until = user.get("withdrawal_blocked_until") or user.get("withdraw_lock_until")
    if blocked_until:
        try:
            if isinstance(blocked_until, str):
                bu = datetime.fromisoformat(blocked_until.replace("Z", "+00:00"))
            else:
                bu = blocked_until
            if bu.tzinfo is None:
                bu = bu.replace(tzinfo=timezone.utc)
            if bu > datetime.now(timezone.utc):
                raise HTTPException(status_code=403, detail=wmsg(_lang, "withdrawal_blocked"))
        except HTTPException:
            raise
        except Exception:
            pass
    
    # Check 2FA requirement
    totp_secret = user.get("two_factor_secret") or user.get("totp_secret")
    is_2fa_enabled = user.get("is_2fa_enabled", False)
    passkey_count = await db.passkeys.count_documents({"user_id": user.get("id")})
    has_passkey = passkey_count > 0
    has_tg_biometry = bool(user.get("tg_biometry_tokens") and len(user.get("tg_biometry_tokens", [])) > 0)

    if not is_2fa_enabled and not has_passkey and not has_tg_biometry:
        raise HTTPException(status_code=400, detail=wmsg(_lang, "enable_2fa"))

    # Telegram Mini App biometric path — Face ID / fingerprint inside TG.
    tg_bio_ok = False
    if has_tg_biometry and getattr(data, "tg_biometry_token", None):
        from routes.tg_biometry import verify_withdraw_biometry_token
        tg_bio_ok = verify_withdraw_biometry_token(
            data.tg_biometry_token, user.get("id"), SECRET_KEY, ALGORITHM
        )

    # Telegram PC / Desktop / Web: WebAuthn passkey недоступен в WebView. По
    # ТЗ разрешаем вывод по одному лишь 2FA, если клиент передал свежий
    # initData, подпись валидна и telegram_id совпадает со связанным.
    tg_pc_verified = False
    if getattr(data, "tg_init_data", None):
        try:
            from auth_handler import verify_telegram_init_data
            _bot_token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
            if _bot_token:
                _tg_user = verify_telegram_init_data(data.tg_init_data, _bot_token)
                _linked = str(user.get("telegram_id") or user.get("telegram_user_id") or "")
                if _tg_user and _linked and str(_tg_user.get("id")) == _linked:
                    tg_pc_verified = True
        except Exception:
            tg_pc_verified = False

    # When the user has a passkey registered, /withdraw/instant additionally
    # requires a fresh passkey assertion (see /withdraw description) — unless
    # they authenticated via Telegram biometry OR come from Telegram PC.
    if has_passkey and not tg_bio_ok and not tg_pc_verified:
        if not data.withdraw_pk_token:
            raise HTTPException(status_code=400, detail="passkey_required")
        wpk = await db.withdraw_pk_tokens.find_one_and_delete({"_id": data.withdraw_pk_token})
        if not wpk:
            raise HTTPException(status_code=401, detail="passkey_token_invalid")
        if wpk.get("user_id") != user.get("id"):
            raise HTTPException(status_code=403, detail="passkey_token_user_mismatch")
        exp = wpk.get("expires_at")
        if exp:
            if isinstance(exp, str):
                try:
                    exp = datetime.fromisoformat(exp.replace("Z", "+00:00"))
                except Exception:
                    exp = None
            if exp and exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp and exp < datetime.now(timezone.utc):
                raise HTTPException(status_code=401, detail="passkey_token_expired")

    # Verify 2FA code if user has TOTP enabled AND biometry did not authorize.
    if is_2fa_enabled and totp_secret and not tg_bio_ok:
        if not totp_code:
            raise HTTPException(status_code=400, detail=wmsg(_lang, "enter_2fa"))

        import pyotp
        from security.totp_crypto import decrypt_secret
        totp = pyotp.TOTP(decrypt_secret(totp_secret))
        # Увеличен valid_window до 3 для мобильных устройств с возможной рассинхронизацией времени
        if not totp.verify(totp_code.strip(), valid_window=3):
            raise HTTPException(status_code=400, detail=wmsg(_lang, "invalid_2fa"))
    
    # Check if user has wallet connected
    wallet_address = user.get("wallet_address")
    if not wallet_address:
        raise HTTPException(status_code=400, detail=wmsg(_lang, "connect_wallet"))
    
    balance = user.get("balance_ton", 0)
    if balance < amount:
        raise HTTPException(status_code=400, detail=wmsg(_lang, "insufficient_simple"))
    
    # Subtract tender escrow (frozen $CITY converted to TON). Uses the
    # reconciled value so a drifted counter with no active contracts reads 0.
    from frozen_tenders import effective_frozen_city
    frozen_city = await effective_frozen_city(db, user)
    frozen_ton_locked = frozen_city / 1000.0

    # Check credit restriction
    or_conds = [{"borrower_id": uid} for uid in ui["ids"]]
    or_conds.extend([{"borrower_wallet": uid} for uid in ui["ids"]])
    active_credits = await db.credits.find(
        {"$or": or_conds, "status": {"$in": ["active", "overdue"]}},
        {"_id": 0}
    ).to_list(20)
    
    total_debt = sum(c.get("remaining_amount") or c.get("remaining") or 0 for c in active_credits)
    available = balance - total_debt - frozen_ton_locked
    
    if available < amount:
        parts = [f"баланс {balance:.2f}"]
        if total_debt > 0:
            parts.append(f"долг {total_debt:.2f}")
        if frozen_ton_locked > 0:
            parts.append(f"заморожено в контрактах {frozen_ton_locked:.4f}")
        breakdown = " − ".join(parts)
        if available <= 0:
            raise HTTPException(status_code=400, detail=f"Вывод заблокирован: доступно 0 TON ({breakdown}).")
        raise HTTPException(status_code=400, detail=f"Максимальная сумма вывода: {available:.4f} TON ({breakdown})")
    
    # Verify bank
    bank = await db.businesses.find_one({"id": bank_id}, {"_id": 0})
    can_process, reason = BankingSystem.can_process_instant(bank, amount)
    
    if not can_process:
        error_msgs = {
            "no_bank_selected": wmsg(_lang, "bank_not_selected"),
            "not_a_bank": wmsg(_lang, "not_a_bank"),
            "bank_durability_low": wmsg(_lang, "bank_durability_low"),
        }
        raise HTTPException(status_code=400, detail=error_msgs.get(reason, wmsg(_lang, "bank_error")))
    
    # Read the bank's configurable instant-withdrawal fee (Block A/B), capped 5%.
    bank_settings = await db.credit_bank_settings.find_one({"bank_id": bank_id}, {"_id": 0})
    instant_fee_rate = min(
        (bank_settings.get("instant_fee", BankingSystem.INSTANT_FEE) if bank_settings else BankingSystem.INSTANT_FEE),
        0.05,
    )

    # Create withdrawal
    withdrawal = BankingSystem.create_withdrawal_request(
        wallet_address,
        amount,
        "instant",
        instant_fee_rate=instant_fee_rate,
    )
    withdrawal["bank_id"] = bank_id
    withdrawal["bank_owner"] = bank.get("owner")
    withdrawal["bank_owner_username"] = bank.get("owner_username")
    withdrawal["bank_fee_rate"] = instant_fee_rate
    withdrawal["type"] = "withdrawal"  # For transaction history
    withdrawal["amount"] = -amount  # Negative - money leaving
    withdrawal["description"] = f"Мгновенный вывод {amount} TON через банк"
    
    # F10 hardening: atomic compare-and-decrement to prevent race-conditions
    # where two parallel /withdraw/instant calls both pass the balance check
    # and both deduct, driving balance below zero. `$gte: available` here uses
    # the SAME derived `available` value we validated above; if another
    # transaction consumed the balance in the meantime, this returns None
    # (no match) and we raise the "insufficient" error without deducting.
    user_filter = get_user_filter(user)
    updated_user = await db.users.find_one_and_update(
        {**user_filter, "balance_ton": {"$gte": amount}},
        {"$inc": {"balance_ton": -amount}},
        return_document=ReturnDocument.AFTER,
        projection={"_id": 0, "balance_ton": 1},
    )
    if not updated_user:
        raise HTTPException(status_code=400, detail="Недостаточно средств")
    new_balance = updated_user.get("balance_ton", 0)
    
    # NOTE (Block B): the bank fee is NOT paid here. It is held by the platform
    # (admin) and only transferred to the bank owner once the on-chain payout
    # succeeds (see process_instant_withdrawal_async). On failure the full
    # amount is refunded to the user and the bank receives nothing.
    bank_fee = withdrawal["bank_fee"]
    
    # Store withdrawal with instant type and user info
    withdrawal_doc = {
        **withdrawal, 
        "tx_type": "instant_withdrawal",
        "user_id": user.get("id"),
        "user_username": user.get("username") or user.get("display_name") or "Unknown",
        "user_raw_address": user.get("raw_address") or user.get("wallet_address") or ""
    }
    await db.transactions.insert_one(withdrawal_doc)
    
    # Try to process instantly in background
    asyncio.create_task(process_instant_withdrawal_async(withdrawal["id"]))
    
    return {
        "status": "pending",
        "withdrawal_id": withdrawal["id"],
        "type": "instant",
        "amount": amount,
        "net_amount": withdrawal["net_amount"],
        "bank_fee": bank_fee,
        "platform_commission": withdrawal["platform_commission"],
        "new_balance": new_balance,
        "message": "Вывод обрабатывается автоматически"
    }

async def process_instant_withdrawal_async(withdrawal_id: str):
    """Background task to process instant withdrawal"""
    try:
        await asyncio.sleep(2)  # Small delay

        from mnemonic_crypto import decrypt_mnemonic

        # Get withdrawal wallet
        withdrawal_wallet = await db.admin_settings.find_one({"type": "withdrawal_wallet"}, {"_id": 0})
        seed = decrypt_mnemonic(withdrawal_wallet.get("mnemonic")) if withdrawal_wallet else None

        if not seed:
            sender_wallet = await db.admin_settings.find_one({"type": "sender_wallet"}, {"_id": 0})
            seed = decrypt_mnemonic(sender_wallet.get("mnemonic")) if sender_wallet else None
        
        if not seed:
            seed = os.getenv("TON_WALLET_MNEMONIC")
        
        if not seed:
            logger.warning(f"No withdrawal wallet for instant withdrawal {withdrawal_id}")
            return
        
        # Atomic lock
        tx = await db.transactions.find_one_and_update(
            {"id": withdrawal_id, "status": "pending"},
            {"$set": {"status": "processing"}},
            return_document=True
        )
        
        if not tx:
            return
        
        user_wallet = tx.get("user_wallet")
        user = await find_user(db, user_id=tx.get("user_id"), wallet=user_wallet)
        
        destination = None
        if user:
            destination = user.get("raw_address") or user.get("wallet_address")
        if not destination:
            destination = tx.get("user_raw_address") or tx.get("to_address") or user_wallet
        
        if not destination:
            await db.transactions.update_one({"id": withdrawal_id}, {"$set": {"status": "failed", "error": "No address"}})
            return
        
        net_amount = float(tx.get("net_amount", 0))
        commission = float(tx.get("commission", 0))
        amount_ton_original = float(tx.get("amount_ton", 0)) or (net_amount + commission)
        user_username = user.get("username", "") if user else ""
        
        try:
            tx_hash = await ton_client.send_ton_payout(
                dest_address=destination,
                amount_ton=net_amount,
                mnemonics=seed,
                user_username=user_username
            )
            
            await db.transactions.update_one(
                {"id": withdrawal_id},
                {"$set": {
                    "status": "completed",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "blockchain_hash": tx_hash,
                    "auto_processed": True
                }}
            )
            
            # Block B: pay the bank fee to the bank owner ONLY now that the
            # payout succeeded (until now it was held by the platform/admin).
            bank_fee = float(tx.get("bank_fee", 0) or 0)
            bank_owner = tx.get("bank_owner")
            if bank_fee > 0 and bank_owner:
                await db.users.update_one(
                    {"$or": [{"id": bank_owner}, {"wallet_address": bank_owner}]},
                    {"$inc": {"balance_ton": bank_fee, "total_income": bank_fee}}
                )
                await db.transactions.insert_one({
                    "id": str(uuid.uuid4()),
                    "type": "bank_fee_income",
                    "user_id": bank_owner,
                    "amount": bank_fee,
                    "amount_ton": bank_fee,
                    "description": f"Комиссия банка за мгновенный вывод +{bank_fee:.4f} TON",
                    "related_withdrawal_id": withdrawal_id,
                    "status": "completed",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                })
            
            commission = float(tx.get("platform_commission", 0) or tx.get("commission", 0) or 0)
            await db.admin_stats.update_one(
                {"type": "treasury"},
                {"$inc": {"withdrawal_fees": commission, "total_withdrawals": net_amount, "total_withdrawals_count": 1}},
                upsert=True
            )
            
            logger.info(f"✅ Instant withdrawal {withdrawal_id} completed: {net_amount} TON")
            
        except Exception as e:
            logger.error(f"❌ Instant withdrawal error: {e}")
            # Block B: refund full amount to the user and DO NOT pay the bank
            # fee (it was held by the platform — released only on success).
            await db.users.update_one({"id": user["id"]} if user else {"wallet_address": user_wallet}, {"$inc": {"balance_ton": amount_ton_original}})
            await db.transactions.update_one(
                {"id": withdrawal_id},
                {"$set": {
                    "status": "failed",
                    "error": str(e),
                    "bank_fee_refunded": True,  # audit: bank did NOT receive the fee
                }},
            )
            
    except Exception as e:
        logger.error(f"Error in instant withdrawal task: {e}")

@api_router.get("/withdrawals/queue")
async def get_withdrawal_queue(current_user: User = Depends(get_current_user)):
    """Get user's withdrawal queue"""
    withdrawals = await db.transactions.find(
        {
            "$or": nz_or([{"user_wallet": current_user.wallet_address}, {"user_id": current_user.id}]),
            "tx_type": {"$in": ["withdrawal", "instant_withdrawal"]}
        },
        {"_id": 0}
    ).sort("created_at", -1).to_list(20)
    
    return {"withdrawals": withdrawals}

# ==================== MY BUSINESSES ROUTES ====================

async def get_user_active_buff(user_id: str) -> dict:
    """Get the highest-priority active TIER3 buff for a user.

    Considers both:
      • per-business `contract_buff` on the user's businesses (active + non-expired contract)
      • patron's `patron_buff` via `patron_id` linkage
    Returns the first matching buff dict (TIER3_BUFFS entry) or {}.
    """
    if not user_id:
        return {}
    # Pull all of the user's businesses + their active contracts in two queries.
    owner_keys = await resolve_owner_keys(db, user_id)
    user_bizs = await db.businesses.find(owner_businesses_query(owner_keys), {"_id": 0}).to_list(50)
    biz_ids = [b.get("id") for b in user_bizs if b.get("id")]
    contracts_by_biz = {}
    if biz_ids:
        async for c in db.contracts.find(
            {"vassal_business_id": {"$in": biz_ids}, "status": "active"}, {"_id": 0}
        ):
            contracts_by_biz[c["vassal_business_id"]] = c

    for biz in user_bizs:
        contract = contracts_by_biz.get(biz.get("id"))
        patron_doc = None
        if biz.get("patron_id"):
            patron_doc = await db.businesses.find_one({"id": biz["patron_id"]}, {"_id": 0})
        buff = resolve_business_buff(biz, contract, patron_doc)
        if buff:
            return buff
    return {}


async def get_user_active_buffs_all(user_id: str) -> list:
    """Return list of all active buffs across user's businesses (deduped by id).

    Includes BOTH sources:
      • patron/contract (TIER3_BUFFS entries via resolve_business_buff)
      • user-activated T3 resource buffs (active_resource_buffs with effect_type)

    Each item has shape: {"id", "name", "effect": {"type", "value"}, "source": "patron"|"resource"}
    """
    if not user_id:
        return []
    owner_keys = await resolve_owner_keys(db, user_id)
    user_bizs = await db.businesses.find(owner_businesses_query(owner_keys), {"_id": 0}).to_list(50)
    biz_ids = [b.get("id") for b in user_bizs if b.get("id")]
    contracts_by_biz = {}
    if biz_ids:
        async for c in db.contracts.find(
            {"vassal_business_id": {"$in": biz_ids}, "status": "active"}, {"_id": 0}
        ):
            contracts_by_biz[c["vassal_business_id"]] = c
    seen, out = set(), []
    for biz in user_bizs:
        contract = contracts_by_biz.get(biz.get("id"))
        patron_doc = None
        if biz.get("patron_id"):
            patron_doc = await db.businesses.find_one({"id": biz["patron_id"]}, {"_id": 0})
        buff = resolve_business_buff(biz, contract, patron_doc)
        if buff and buff.get("id") and buff["id"] not in seen:
            seen.add(buff["id"])
            out.append({**buff, "source": "patron"})

    # Include user-activated T3 resource buffs
    user_doc = await db.users.find_one(
        {"$or": [{"id": user_id}, {"wallet_address": user_id}, {"email": user_id}]},
        {"_id": 0, "active_resource_buffs": 1},
    )
    if user_doc:
        from datetime import datetime as _dt, timezone as _tz
        now_u = _dt.now(_tz.utc)
        for rb in (user_doc.get("active_resource_buffs") or []):
            if not isinstance(rb, dict):
                continue
            effect_type = rb.get("effect_type")
            effect_value = rb.get("effect_value")
            if not effect_type or effect_value is None:
                continue
            exp_raw = rb.get("expires_at")
            if exp_raw:
                try:
                    exp_dt = _dt.fromisoformat(str(exp_raw).replace('Z', '+00:00'))
                    if exp_dt <= now_u:
                        continue
                except (ValueError, TypeError):
                    continue
            rid = rb.get("resource_id") or f"res_{effect_type}"
            if rid in seen:
                continue
            seen.add(rid)
            out.append({
                "id": rid,
                "name": rb.get("buff_name") or rid,
                "icon": rb.get("buff_icon", ""),
                "description": rb.get("buff_description", ""),
                "effect": {"type": effect_type, "value": float(effect_value)},
                "source": "resource",
            })
    return out


def _buff_value_for(buffs, effect_type, default=1.0):
    """Find the strongest matching effect among the list of buffs.

    For additive reductions (e.g. trade_tax_reduction) we sum across multiple sources
    (patron + resource buffs stacking) instead of picking a single best.
    """
    additive_types = ("trade_tax_reduction",)
    if effect_type in additive_types:
        total = 0.0
        found = False
        for b in buffs or []:
            eff = (b or {}).get("effect") or {}
            if eff.get("type") != effect_type:
                continue
            try:
                total += float(eff.get("value", 0.0))
                found = True
            except (TypeError, ValueError):
                continue
        return total if found else default

    best = None
    for b in buffs or []:
        eff = (b or {}).get("effect") or {}
        if eff.get("type") != effect_type:
            continue
        try:
            v = float(eff.get("value", default))
        except (TypeError, ValueError):
            continue
        if best is None:
            best = v
        else:
            # For multipliers like 0.70 (smaller = better) keep the best for the user;
            # For bonuses like trade_slots_bonus (additive, larger = better) keep max.
            if effect_type in ("trade_slots_bonus", "crit_chance_bonus", "free_cycle_chance"):
                best = max(best, v)
            else:
                best = min(best, v) if v < 1.0 else max(best, v)
    return best if best is not None else default


@api_router.get("/my/active-buff-multipliers")
async def my_active_buff_multipliers(current_user: User = Depends(get_current_user)):
    """Aggregated multipliers from currently active buffs (patron+resource), used by UI for previews
    (sale tax, withdrawal fee, repair cost, trade slots, etc.). Stacking is multiplicative for
    *_multiplier types and additive (max) for *_bonus types — matching the actual server math.
    """
    ui = await get_user_identifiers(current_user)
    primary = ui.get("primary_id")
    buffs = await get_user_active_buffs_all(primary) if primary else []

    mult_types = {
        "repair_cost_multiplier",
        "consumption_multiplier",
        "production_multiplier",
        "trade_fee_multiplier",
        "withdrawal_fee_multiplier",
        "wear_reduction",
        "storage_multiplier",
    }
    add_types = {"trade_slots_bonus", "crit_chance_bonus", "free_cycle_chance"}
    # Additive percentage-point reductions on tax rate.
    reduction_types = {"trade_tax_reduction"}

    multipliers = {t: 1.0 for t in mult_types}
    bonuses = {t: 0.0 for t in add_types}
    reductions = {t: 0.0 for t in reduction_types}

    contributing = {t: [] for t in (mult_types | add_types | reduction_types)}

    for b in buffs:
        eff = (b or {}).get("effect") or {}
        et = eff.get("type")
        try:
            v = float(eff.get("value"))
        except (TypeError, ValueError):
            continue
        item = {
            "id": b.get("id"),
            "name": b.get("name"),
            "icon": b.get("icon"),
            "value": v,
            "source": b.get("source", "patron"),
        }
        if et in mult_types:
            multipliers[et] *= v
            contributing[et].append(item)
        elif et in add_types:
            bonuses[et] = max(bonuses[et], v)
            contributing[et].append(item)
        elif et in reduction_types:
            reductions[et] += v
            contributing[et].append(item)

    return {
        "multipliers": {k: round(v, 4) for k, v in multipliers.items()},
        "bonuses": {k: round(v, 4) for k, v in bonuses.items()},
        "reductions": {k: round(v, 4) for k, v in reductions.items()},
        "contributing": contributing,
    }




@api_router.get("/my/businesses")
async def get_my_businesses_full(current_user: User = Depends(get_current_user)):
    """Thin wrapper that surfaces the SPECIFIC failure to the client.

    The global exception handler masks any unexpected error as a generic
    'internal error', which hides WHY the "My Businesses" page failed to load.
    Here we log the full traceback (tag [MYBIZ]) and return the concrete error
    type + message in the 500 detail so the UI notification can show exactly
    what broke."""
    try:
        return await _get_my_businesses_full_impl(current_user)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[MYBIZ] /api/my/businesses FAILED for user=%s",
                         getattr(current_user, "id", None))
        raise HTTPException(
            status_code=500,
            detail=f"/api/my/businesses failed: {type(e).__name__}: {e}",
        )


async def _get_my_businesses_full_impl(current_user: User):
    """Get all user's businesses with full details"""
    # Search using unified helper
    ui = await get_user_identifiers(current_user)
    if not ui["user"]:
        return {"businesses": [], "summary": {"total_businesses": 0, "total_pending_income": 0, "total_hourly_income": 0, "total_daily_income": 0}}
    
    query = get_businesses_query(ui["ids"])
    # Trial Center feature has been removed. Any legacy is_trial docs left in the
    # DB must NOT appear here (nor count toward the 3-business/plot limits).
    query = {"$and": [query, {"is_trial": {"$ne": True}}]}
    businesses = await db.businesses.find(query, {"_id": 0}).to_list(50)

    # ── DRIFT-TOLERANT SANITIZATION ─────────────────────────────────────────
    # Long-lived accounts can accumulate slightly "off" numeric values in Mongo
    # (a resource amount, storage capacity, durability or level stored as None
    # or a non-numeric string). The heavy income/warehouse math below calls
    # float()/int()/comparisons on those values and would raise → HTTP 500 →
    # the "My Businesses" page shows NOTHING and the app throws a load error.
    # We coerce every numeric field back to a safe number up-front so EVERY
    # account renders its real businesses. (This mirrors the User-model
    # coercion that fixed the endless-99% /auth/me crash.)
    def _num(v, default=0.0):
        try:
            if v is None or v == "":
                return default
            return float(v)
        except (ValueError, TypeError):
            return default

    def _sanitize_resource_map(m):
        if not isinstance(m, dict):
            return {}
        return {k: _num(v, 0.0) for k, v in m.items()}

    if isinstance(ui.get("user"), dict):
        ui["user"]["resources"] = _sanitize_resource_map(ui["user"].get("resources", {}))

    for _b in businesses:
        if not isinstance(_b, dict):
            continue
        _st = _b.get("storage")
        if isinstance(_st, dict):
            _st["capacity"] = _num(_st.get("capacity", 0), 0.0)
            _st["items"] = _sanitize_resource_map(_st.get("items", {}))
        else:
            _b["storage"] = {"capacity": 0.0, "items": {}}
        # durability / level / xp used in comparisons & arithmetic below.
        _b["durability"] = _num(_b.get("durability", 100), 100.0)
        _lvl = _b.get("level", 1)
        try:
            _b["level"] = int(float(_lvl)) if _lvl not in (None, "") else 1
        except (ValueError, TypeError):
            _b["level"] = 1
        _b["xp"] = _num(_b.get("xp", 0), 0.0)
    # ─────────────────────────────────────────────────────────────────────────

    # Active resource-buff multiplier (e.g. neuro_core +8%) applies to all owner's businesses
    user_buff_mult = get_user_production_buff(ui["user"])

    # Resource-buff consumption multiplier (e.g. bio_module -10%). Stacks with patron's (e.g. lean_production -5%).
    user_cons_mult = 1.0
    try:
        now_u = datetime.now(timezone.utc)
        for rb in (ui["user"].get("active_resource_buffs") or []):
            if not isinstance(rb, dict):
                continue
            if rb.get("effect_type") != "consumption_multiplier":
                continue
            exp_raw = rb.get("expires_at")
            if exp_raw:
                try:
                    exp_dt = datetime.fromisoformat(str(exp_raw).replace('Z', '+00:00'))
                    if exp_dt <= now_u:
                        continue
                except (ValueError, TypeError):
                    continue
            try:
                user_cons_mult *= float(rb.get("effect_value", 1.0))
            except (TypeError, ValueError):
                pass
    except Exception:
        user_cons_mult = 1.0

    # Pre-fetch alliance/contract buffs for all vassal businesses (avoid N+1).
    # Map: vassal_business_id -> active buff dict (TIER3_BUFFS entry) or {} if none.
    biz_buff_map: dict[str, dict] = {}
    biz_ids = [b["id"] for b in businesses if b.get("id")]
    active_contracts_by_biz: dict[str, dict] = {}
    if biz_ids:
        async for c in db.contracts.find(
            {"vassal_business_id": {"$in": biz_ids}, "status": "active"},
            {"_id": 0},
        ):
            active_contracts_by_biz[c["vassal_business_id"]] = c

    # Cache patron business docs (lookup by id)
    patron_biz_cache: dict[str, dict] = {}

    async def _get_patron_biz(pid: str):
        if not pid:
            return None
        if pid in patron_biz_cache:
            return patron_biz_cache[pid]
        doc = await db.businesses.find_one({"id": pid}, {"_id": 0})
        patron_biz_cache[pid] = doc
        return doc

    for _biz in businesses:
        contract_doc = active_contracts_by_biz.get(_biz.get("id"))
        patron_doc = await _get_patron_biz(_biz.get("patron_id")) if _biz.get("patron_id") else None
        biz_buff_map[_biz["id"]] = resolve_business_buff(_biz, contract_doc, patron_doc)

    # Calculate global weighted warehouse totals (personal + business storage)
    try:
        from boosters import auto_shift_active as _auto_shift_active
        _auto_shift_on = _auto_shift_active(ui["user"])
    except Exception:
        _auto_shift_on = False
    # Boosters / buffs in force, shown in the business info with the time left.
    # Account-wide ones act on EVERY business of the player (level 0 included).
    _acct_buffs = []
    try:
        _u = ui["user"] or {}
        _nowb = datetime.now(timezone.utc)
        def _future(ts):
            try:
                _d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                _d = _d if _d.tzinfo else _d.replace(tzinfo=timezone.utc)
                return _d.isoformat() if _d > _nowb else None
            except Exception:
                return None
        if _future(_u.get("auto_shift_until")):
            _acct_buffs.append({"kind": "auto_shift", "icon": "🔁", "until": _future(_u.get("auto_shift_until"))})
        if _future(_u.get("decay_protected_until")):
            _acct_buffs.append({"kind": "warehouse_guard", "icon": "🛡️", "until": _future(_u.get("decay_protected_until"))})
        for _rb in (_u.get("active_resource_buffs") or []):
            if isinstance(_rb, dict) and _future(_rb.get("expires_at")):
                from routes.buffs import RESOURCE_BUFFS as _RB
                _rid = str(_rb.get("resource_id") or "").replace("_tutorial", "")
                _cfg = _RB.get(_rid, {})
                _acct_buffs.append({"kind": "resource", "resource": _rid, "icon": _rb.get("icon") or _cfg.get("icon") or "💎",
                                    "name": _rb.get("name") or _cfg.get("name"),
                                    "effect_type": _rb.get("effect_type") or _cfg.get("effect_type"),
                                    "effect_value": _rb.get("effect_value") if _rb.get("effect_value") is not None else _cfg.get("effect_value"),
                                    "until": _future(_rb.get("expires_at"))})
    except Exception as _be:
        logger.debug(f"active buffs: {_be}")
    # ONE warehouse rule for the whole game (core/warehouse.py): weighted
    # resources + active market lots vs. buffed business storage (min 50).
    _wh = await warehouse_rules.user_warehouse(db, ui["user"], businesses=businesses, buff_map=biz_buff_map)
    total_warehouse_used = _wh["used"]
    total_warehouse_capacity = _wh["capacity"]

    # Pre-fetch active alliance counts per T3 business owned by the user (for "n/25" badge)
    t3_biz_ids = [
        b["id"] for b in businesses
        if b.get("id") and BUSINESSES.get(b.get("business_type", ""), {}).get("tier", 1) == 3
    ]
    active_alliances_per_biz: dict = {}
    if t3_biz_ids:
        for tid in t3_biz_ids:
            active_alliances_per_biz[tid] = await db.contracts.count_documents(
                {"patron_business_id": tid, "status": {"$in": ["active", "proposed"]}}
            )

    result = []
    total_pending = 0
    total_hourly = 0
    
    for biz in businesses:
        try:
            config = resolve_business_config(biz.get("business_type"))

            # Resolve alliance/contract buff for this business (storage/production/consumption)
            biz_buff = biz_buff_map.get(biz.get("id"), {})
            prod_mult_from_buff = buff_multiplier(biz_buff, "production_multiplier", 1.0)
            cons_mult_from_buff = buff_multiplier(biz_buff, "consumption_multiplier", 1.0)
            storage_mult_from_buff = buff_multiplier(biz_buff, "storage_multiplier", 1.0)

            # Get patron info if exists (NOTE: legacy PATRONAGE_EFFECTS production bonus disabled per spec —
            # patron value comes from the chosen TIER3_BUFFS only, not from the T3-type's auto +5..15%).
            patron_bonus = 1.0
            patron_info = None
            if biz.get("patron_id"):
                patron = await _get_patron_biz(biz["patron_id"])
                if patron:
                    patron_type = PatronageSystem.get_patron_type(patron.get("business_type"))
                    # patron_bonus intentionally left at 1.0 — disabled by design.
                    patron_config_info = resolve_business_config(patron.get("business_type"))
                    # Surface the patron's currently-chosen buff so the UI can show it
                    # even when no alliance contract is active for this vassal yet.
                    pb_id = patron.get("patron_buff")
                    pb_data = TIER3_BUFFS.get(pb_id) if pb_id else None
                    patron_info = {
                        "id": patron["id"],
                        "type": patron_type,
                        "name": patron_config_info.get("name", {}),
                        "icon": patron_config_info.get("icon", ""),
                        "level": patron.get("level", 1),
                        "patron_buff": {
                            "id": pb_data.get("id"),
                            "name": pb_data.get("name"),
                            "icon": pb_data.get("icon"),
                            "description": pb_data.get("description"),
                            "effect": pb_data.get("effect"),
                        } if pb_data else None,
                    }

            # Calculate production — fold alliance buff's production_multiplier into user_buff_mult
            biz_type = biz.get("business_type", "")
            biz_level = biz.get("level", 1)
            effective_user_buff = user_buff_mult * prod_mult_from_buff
            production = BusinessEconomics.calculate_effective_production(biz, patron_bonus, effective_user_buff)
            production["base_production"] = get_production(biz_type, biz_level)
            # Show buffed consumption breakdown (patron × user resource buff, e.g. lean_production × bio_module)
            _raw_consumption = get_consumption_breakdown(biz_type, biz_level) or {}
            total_cons_mult = cons_mult_from_buff * user_cons_mult
            if total_cons_mult != 1.0:
                production["consumption_breakdown"] = {
                    r: round(v * total_cons_mult, 4) for r, v in _raw_consumption.items()
                }
            else:
                production["consumption_breakdown"] = _raw_consumption
            production["consumption_multiplier"] = total_cons_mult
            production["consumption_multiplier_patron"] = cons_mult_from_buff
            production["consumption_multiplier_resource"] = user_cons_mult
            # Attach buff info for UI transparency
            production["alliance_buff"] = {
                "id": biz_buff.get("id"),
                "name": biz_buff.get("name"),
                "icon": biz_buff.get("icon"),
                "description": biz_buff.get("description"),
                "effect": biz_buff.get("effect"),
            } if biz_buff else None
            pending = IncomeCollector.calculate_pending_income(
                biz, patron_bonus=patron_bonus, user_buff_multiplier=effective_user_buff
            )

            total_pending += pending.get("pending", 0)
            total_hourly += production.get("income_after_tax", 0)

            # Storage info — apply Глубокие закрома (storage_multiplier) from active buff
            storage = biz.get("storage", {})
            capacity = storage.get("capacity", 0)
            if storage_mult_from_buff != 1.0:
                capacity = int(capacity * storage_mult_from_buff)
            items = storage.get("items", {})
            # business.storage.items are NOT added to total_warehouse_used (already in user.resources)
            biz_items_used = sum(float(v) * get_warehouse_weight(res) for res, v in items.items() if v > 0)

            # Working/Idle status
            # Local fullness: this business's produced items fill its own capacity
            is_storage_full = (biz_items_used >= capacity) if capacity > 0 else False
            # Global fullness: total weighted city warehouse is full
            is_global_full = total_warehouse_capacity > 0 and total_warehouse_used >= total_warehouse_capacity
            durability = biz.get("durability", 100)

            # Determine WHY a business would be idle (used only for the label).
            consumption = get_consumption_breakdown(biz_type, biz_level)
            user_resources = ui["user"].get("resources", {}) if ui.get("user") else {}
            has_resources = True
            # [quests/onboarding] names + shortfall of every missing input, used by
            # the "your business is idle — buy X on the market" hint in the UI.
            missing_resources = []
            _total_cons = cons_mult_from_buff * user_cons_mult
            if consumption:
                for resource, daily_amount in consumption.items():
                    needed_for_tick = (daily_amount * _total_cons) / 24.0
                    available = user_resources.get(resource, 0)
                    if needed_for_tick > 0 and available < needed_for_tick:
                        has_resources = False
                        try:
                            missing_resources.append({
                                "resource": resource,
                                "available": round(float(available or 0), 2),
                                "needed_per_hour": round(float(needed_for_tick), 2),
                            })
                        except (TypeError, ValueError):
                            missing_resources.append({"resource": resource})

            # Source of truth = the economic tick. The tick (background_tasks) is what
            # ACTUALLY produces/consumes and writes `is_active`/`work_status` every
            # minute, accounting for resources AND the running storage cap. Trusting it
            # here keeps the displayed badge consistent with real production (fixes the
            # "business is clearly working but shows Простаивает" desync). We fall back
            # to a live computation only when the business has never ticked yet.
            stored_active = biz.get("is_active")
            if durability <= 0:
                work_status = "stopped"
                work_status_reason = "durability_zero"
            elif stored_active is True:
                work_status = "working"
                work_status_reason = None
            elif stored_active is False:
                work_status = "idle"
                if not has_resources:
                    work_status_reason = "no_resources"
                elif is_storage_full or is_global_full:
                    work_status_reason = "storage_full"
                else:
                    # Tick idled it but resources/space look fine now — likely a
                    # transient supply-chain gap; surface the generic reason.
                    work_status_reason = "no_resources"
            else:
                # Never ticked → live fallback.
                if is_storage_full or is_global_full:
                    work_status = "idle"
                    work_status_reason = "storage_full"
                elif not has_resources:
                    work_status = "idle"
                    work_status_reason = "no_resources"
                else:
                    work_status = "working"
                    work_status_reason = None

            # ── LIVE WAREHOUSE overlay ──────────────────────────────────
            # The player's WHOLE warehouse (resources + active market lots) is
            # the rule: when it is full, every business is idle; as soon as space
            # frees up, a business with a running shift and inputs works again.
            # The tick applies this to production every minute; here we apply it
            # to the badge immediately, so it never shows "working" over a full
            # warehouse or keeps "idle" after the player made room.
            if durability > 0:
                if is_global_full:
                    work_status = "idle"
                    work_status_reason = "storage_full"
                elif (stored_active is False and biz.get("work_status_reason") == "storage_full"
                      and has_resources):
                    work_status = "working"
                    work_status_reason = None

            # ── WORK SHIFT (8h) overlay ─────────────────────────────────
            # A business only "works" while its 8h shift is running. When the
            # shift is over it is idle (простаивает) regardless of resources,
            # and it stops wearing until the owner starts a new shift.
            _shift_active = _shift_is_active(biz)
            _shift_ends_at = biz.get("shift_ends_at")
            _shift_remaining = 0
            if _shift_active and _shift_ends_at:
                try:
                    _end_dt = datetime.fromisoformat(str(_shift_ends_at).replace("Z", "+00:00"))
                    if _end_dt.tzinfo is None:
                        _end_dt = _end_dt.replace(tzinfo=timezone.utc)
                    _shift_remaining = max(0, int((_end_dt - datetime.now(timezone.utc)).total_seconds()))
                except (ValueError, TypeError):
                    _shift_remaining = 0
            if not _shift_active and durability > 0:
                work_status = "idle"
                # auto-shift on: the business waits for inputs / free space and
                # restarts by itself — show that reason instead of «shift ended»
                if _auto_shift_on and biz.get("auto_wait_reason") in ("no_resources", "storage_full"):
                    work_status_reason = biz.get("auto_wait_reason")
                else:
                    work_status_reason = "shift_ended"

            result.append({
                **biz,
                "config": {
                    "name": config.get("name"),
                    "tier": config.get("tier"),
                    "icon": config.get("icon"),
                    "produces": config.get("produces"),
                    "base_cost_ton": config.get("base_cost_ton"),
                },
                "production": production,
                "pending_income": pending.get("pending", 0),
                "patron": patron_info,
                "patron_buff": biz.get("patron_buff"),
                "patron_buff_data": TIER3_BUFFS.get(biz.get("patron_buff"), {}) if biz.get("patron_buff") else None,
                "contract_buff": biz.get("contract_buff"),
                "contract_id": biz.get("contract_id"),
                "contract_buff_data": TIER3_BUFFS.get(biz.get("contract_buff"), {}) if biz.get("contract_buff") else None,
                "active_buff": biz_buff or None,
                # everything that acts on this business now, with the end time (shown in the business info)
                "active_buffs": _acct_buffs + ([{
                    "kind": "business", "icon": "🤝", "name": (biz_buff or {}).get("name"),
                    "effect_type": ((biz_buff or {}).get("effect") or {}).get("type"),
                    "effect_value": ((biz_buff or {}).get("effect") or {}).get("value"),
                    "until": (active_contracts_by_biz.get(biz.get("id")) or {}).get("expires_at"),
                }] if biz_buff else []),
                "shift_active": _shift_active,
                "shift_ends_at": _shift_ends_at,
                # the frontend uses this instead of re-implementing the shift rule
                "auto_operates": _auto_operates(biz),
                "shift_started_at": biz.get("shift_started_at"),
                "shift_remaining_seconds": _shift_remaining,
                "shift_duration_hours": SHIFT_DURATION_HOURS,
                "storage_info": {
                    "capacity": int(capacity),
                    # Proportional share of global weighted usage — floor integer, capped at capacity
                    "used": min(
                        int(total_warehouse_used * capacity / total_warehouse_capacity) if total_warehouse_capacity > 0 and capacity > 0 else int(biz_items_used),
                        int(capacity)
                    ),
                    "items": {k: int(v) for k, v in items.items() if int(v) > 0},
                    "items_used_weighted": int(biz_items_used),
                    "is_full": is_global_full,
                },
                "work_status": work_status,
                "work_status_reason": work_status_reason,
                # Also filled when the shift ended: a player can't START a shift
                # without inputs, so the hint must explain that too.
                "missing_resources": missing_resources if not has_resources else [],
                "active_alliances_count": active_alliances_per_biz.get(biz.get("id"), 0) if biz.get("id") in t3_biz_ids else None,
                "max_alliances": 25 if biz.get("id") in t3_biz_ids else None,
            })
    
        except Exception as _be:
            # One malformed business must NOT blow up the whole page with a
            # 500 (the 'My Businesses shows nothing' bug). Log the concrete
            # cause (tag [MYBIZ]) and render this business in a minimal safe
            # form so every OTHER business still loads.
            logger.exception("[MYBIZ] per-business render FAILED id=%s type=%s",
                             biz.get("id"), biz.get("business_type"))
            _cfg_fb = resolve_business_config(biz.get("business_type")) or {}
            result.append({
                **biz,
                "config": {
                    "name": _cfg_fb.get("name"),
                    "tier": _cfg_fb.get("tier"),
                    "icon": _cfg_fb.get("icon"),
                    "produces": _cfg_fb.get("produces"),
                    "base_cost_ton": _cfg_fb.get("base_cost_ton"),
                },
                "production": {},
                "pending_income": 0,
                "patron": None,
                "active_buff": None,
                "storage_info": {"capacity": 0, "used": 0, "items": {}, "items_used_weighted": 0, "is_full": False},
                "work_status": "idle",
                "work_status_reason": "render_error",
                "render_error": f"{type(_be).__name__}: {_be}",
            })
            continue
    return {
        "businesses": result,
        "summary": {
            "total_businesses": len(result),
            "total_pending_income": round(total_pending, 4),
            "total_hourly_income": round(total_hourly, 6),
            "total_daily_income": round(total_hourly * 24, 4),
            "total_warehouse_capacity": int(total_warehouse_capacity),
            "total_warehouse_used": int(total_warehouse_used),
        },
        # Surface user-activated T3 resource buffs so the per-business UI can show every
        # buff source (alliance, patron, user-resource buff) in one place.
        "active_resource_buffs": [
            {
                "id": rb.get("id") or rb.get("resource_id"),
                "resource_id": rb.get("resource_id"),
                "name": rb.get("name"),
                "icon": rb.get("icon"),
                "description": rb.get("description"),
                "effect_type": rb.get("effect_type"),
                "effect_value": rb.get("effect_value"),
                "expires_at": rb.get("expires_at"),
            }
            for rb in (ui["user"].get("active_resource_buffs") or [])
            if isinstance(rb, dict)
        ],
    }

@api_router.post("/my/collect-all")
async def collect_all_income(current_user: User = Depends(get_current_user)):
    """Collect income from all businesses"""
    # Search by ALL user identifiers (id, wallet_address, email, username) so we don't miss
    # businesses created under a different auth flow.
    _collect_keys = await resolve_owner_keys(db, current_user.id) or [current_user.id]
    if current_user.wallet_address:
        _collect_keys = list(set(_collect_keys + [current_user.wallet_address]))
    query = owner_businesses_query(_collect_keys)

    businesses = await db.businesses.find(query, {"_id": 0}).to_list(50)
    
    total_collected = 0
    total_tax = 0
    total_patron = 0
    collected_count = 0
    
    for biz in businesses:
        patron_wallet = None
        if biz.get("patron_id"):
            patron = await db.businesses.find_one({"id": biz["patron_id"]}, {"_id": 0})
            if patron:
                patron_wallet = patron.get("owner")
        
        collection = IncomeCollector.collect_income(biz, patron_wallet)
        
        if collection.get("halted") or collection["collected"] <= 0:
            continue
        
        total_collected += collection["player_receives"]
        total_tax += collection["treasury_receives"]
        total_patron += collection["patron_receives"]
        collected_count += 1
        
        # Update business
        await db.businesses.update_one(
            {"id": biz["id"]},
            {"$set": {"last_collection": datetime.now(timezone.utc).isoformat()}}
        )
        
        # Pay patron
        if patron_wallet and collection["patron_receives"] > 0:
            await db.users.update_one(
                {"wallet_address": patron_wallet},
                {"$inc": {"balance_ton": collection["patron_receives"]}}
            )
    
    # Update user - search by id or wallet_address
    if total_collected > 0:
        user_query = {"$or": [{"id": current_user.id}]}
        if current_user.wallet_address:
            user_query["$or"].append({"wallet_address": current_user.wallet_address})
        await db.users.update_one(
            user_query,
            {"$inc": {"balance_ton": total_collected, "total_income": total_collected}}
        )
    
    # Update treasury
    if total_tax > 0:
        await db.admin_stats.update_one(
            {"type": "treasury"},
            {"$inc": {"business_tax": total_tax, "total_tax": total_tax}},
            upsert=True
        )
    
    return {
        "status": "collected",
        "businesses_collected": collected_count,
        "total_player_income": round(total_collected, 4),
        "total_tax_paid": round(total_tax, 4),
        "total_patron_fees": round(total_patron, 4)
    }

# ==================== CITIES ROUTES ====================

from city_generator import create_demo_cities, calculate_plot_price_in_city

@api_router.get("/cities")
async def get_all_cities():
    """Get all cities with basic info for map view"""
    cities = await db.cities.find({}, {"_id": 0}).to_list(100)
    
    if not cities:
        # Seed demo cities if none exist
        demo_cities = create_demo_cities()
        for city in demo_cities:
            await db.cities.insert_one(city.copy())
        cities = demo_cities
    
    # Return lightweight version for list view
    result = []
    for city in cities:
        # Update stats from actual data
        owned_plots = await db.plots.count_documents({"city_id": city["id"], "owner": {"$ne": None}})
        total_businesses = await db.businesses.count_documents({"city_id": city["id"]})
        
        # Handle localized name - convert to string
        city_name = city.get("name", "Unknown")
        if isinstance(city_name, dict):
            city_name = city_name.get("ru") or city_name.get("en") or "Unknown"
        
        city_desc = city.get("description", "")
        if isinstance(city_desc, dict):
            city_desc = city_desc.get("ru") or city_desc.get("en") or ""
        
        result.append({
            "id": city["id"],
            "name": city_name,
            "description": city_desc,
            "style": city["style"],
            "base_price": city["base_price"],
            "grid_preview": city["grid"],  # For silhouette rendering
            "stats": {
                "total_plots": city["stats"]["total_plots"],
                "owned_plots": owned_plots,
                "total_businesses": total_businesses,
                "monthly_volume": city["stats"].get("monthly_volume", 0),
                "active_players": city["stats"].get("active_players", 0)
            }
        })
    
    return {"cities": result, "total": len(result)}

@api_router.get("/cities/{city_id}")
async def get_city(city_id: str):
    """Get full city data including grid"""
    city = await db.cities.find_one({"id": city_id}, {"_id": 0})
    
    if not city:
        raise HTTPException(status_code=404, detail="Город не найден")
    
    return city

@api_router.get("/cities/{city_id}/plots")
async def get_city_plots(city_id: str):
    """Get all plots for a specific city"""
    city = await db.cities.find_one({"id": city_id}, {"_id": 0})
    if not city:
        raise HTTPException(status_code=404, detail="Город не найден")
    
    # Get existing plots
    plots = await db.plots.find({"city_id": city_id}, {"_id": 0}).to_list(10000)
    plots_map = {f"{p['x']}_{p['y']}": p for p in plots}
    
    # Get businesses
    businesses = await db.businesses.find({"city_id": city_id}, {"_id": 0}).to_list(10000)
    business_map = {b["plot_id"]: b for b in businesses}
    
    # Generate full plot list from grid
    grid = city["grid"]
    result = []
    
    for y, row in enumerate(grid):
        for x, cell in enumerate(row):
            if cell == 1:  # Land cell
                plot_key = f"{x}_{y}"
                existing_plot = plots_map.get(plot_key)
                
                if existing_plot:
                    business = business_map.get(existing_plot.get("id"))
                    bt = BUSINESS_TYPES.get(business["business_type"]) if business else None
                    result.append({
                        "id": existing_plot["id"],
                        "x": x,
                        "y": y,
                        "city_id": city_id,
                        "owner": existing_plot.get("owner"),
                        "price": existing_plot.get("price", calculate_plot_price_in_city(city, x, y)),
                        "is_available": existing_plot.get("is_available", True),
                        "business_id": existing_plot.get("business_id"),
                        "business_type": business["business_type"] if business else None,
                        "business_icon": bt["icon"] if bt else None,
                        "business_level": business.get("level", 1) if business else None
                    })
                else:
                    # Plot doesn't exist yet in DB - create virtual entry
                    result.append({
                        "id": None,
                        "x": x,
                        "y": y,
                        "city_id": city_id,
                        "owner": None,
                        "price": calculate_plot_price_in_city(city, x, y),
                        "is_available": True,
                        "business_id": None,
                        "business_type": None,
                        "business_icon": None,
                        "business_level": None
                    })
    
    return {"plots": result, "total": len(result), "city": {"id": city_id, "name": city["name"], "style": city["style"]}}

@api_router.post("/cities/{city_id}/plots/{x}/{y}/buy")
async def buy_city_plot(city_id: str, x: int, y: int, current_user: User = Depends(get_current_user)):
    """Buy a plot in a specific city"""
    city = await db.cities.find_one({"id": city_id}, {"_id": 0})
    if not city:
        raise HTTPException(status_code=404, detail="Город не найден")
    
    # Check if coordinates are valid (within grid and is land)
    grid = city["grid"]
    if y < 0 or y >= len(grid) or x < 0 or x >= len(grid[0]) or grid[y][x] != 1:
        raise HTTPException(status_code=400, detail="Неверные координаты участка")
    
    # Check if plot already owned
    existing_plot = await db.plots.find_one({"city_id": city_id, "x": x, "y": y})
    if existing_plot and existing_plot.get("owner"):
        raise HTTPException(status_code=400, detail="Участок уже куплен другим игроком")
    
    # Get user
    user = await db.users.find_one({"id": current_user.id})
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    # Check plot limit - 3 plots max for regular users, unlimited for admins and banks
    is_admin = user.get("is_admin", False) or user.get("role") == "ADMIN"
    is_bank = user.get("is_bank", False) or user.get("role") == "BANK"
    
    if not is_admin and not is_bank:
        user_plots = len(user.get("plots_owned", []))
        max_plots = 3  # Fixed limit of 3 plots for all regular users
        if user_plots >= max_plots:
            raise HTTPException(status_code=400, detail=t("max_plots_reached", user.get("language", "en")))
    
    # Calculate price
    price = calculate_plot_price_in_city(city, x, y)
    
    # Проверка: бонусный + доступный реальный баланс (без заморозки по контрактам)
    from core.balance import total_available_ton as _tat
    if _tat(user) + 1e-9 < price:
        raise await _insufficient_funds(user, price)
    
    # Create or update plot
    plot_id = f"{city_id}_{x}_{y}"
    # Используем user.id как основной идентификатор
    user_id = user.get("id", str(user.get("_id")))
    
    plot_data = {
        "id": plot_id,
        "city_id": city_id,
        "x": x,
        "y": y,
        "price": price,
        "owner": user_id,
        "owner_username": user.get("username"),
        "owner_avatar": user.get("avatar"),
        "is_available": False,
        "purchased_at": datetime.now(timezone.utc).isoformat()
    }
    
    await db.plots.update_one(
        {"city_id": city_id, "x": x, "y": y},
        {"$set": plot_data},
        upsert=True
    )
    
    # Update user by id field.
    # F10 hardening: atomic compare-and-set — if two parallel plot-buy calls
    # both pass the balance check above, only one debit is applied. The other
    # gets 400.
    # Списание: сначала бонус, затем реальный (атомарно)
    upd = await debit_user_split({"id": user_id}, price, extra_update={"$push": {"plots_owned": plot_id}})
    if not upd.get("ok"):
        # Roll back the plot upsert we just did.
        await db.plots.delete_one({"city_id": city_id, "x": x, "y": y})
        raise await _insufficient_funds(user, price)
    new_balance = upd.get("balance_ton", 0)

    # Referral Rally: pay 1.5 TON bonus to referrer if active campaign & first plot
    try:
        from promo_service import maybe_pay_activation_bonus
        await maybe_pay_activation_bonus(db, user_id)
    except Exception as _e:
        logger.debug(f"promo activation bonus (city buy) failed: {_e}")
    
    # Record transaction in history
    import uuid as uuid_module
    history_tx = {
        "id": str(uuid_module.uuid4()),
        "user_id": user_id,
        "type": "land_purchase",
        "amount": -price,
        "details": {
            "plot_id": plot_id,
            "city_id": city_id,
            "x": x,
            "y": y,
            "price": price
        },
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.transactions.insert_one(history_tx)
    
    # B2B partner land-sale commission (credit the buyer's partner, if any)
    try:
        from b2b_partners import credit_land_sale
        await credit_land_sale(db, user_id, price)
    except Exception as _e:
        logger.debug(f"b2b land-sale credit (city buy) failed: {_e}")
    
    # In-app + telegram notification
    try:
        from core.notify import notify_user
        await notify_user(
            db, user,
            title="Участок куплен",
            message=f"Вы приобрели участок ({x}, {y}) за {price:.2f} TON. Теперь можно построить бизнес.",
            type_key="land_purchase",
            priority="success",
            payload={"plot_id": plot_id, "city_id": city_id, "x": x, "y": y, "price": price},
            i18n_key="land_purchase",
            i18n_vars={"x": x, "y": y, "price": f"{price:.2f}"},
        )
    except Exception as _e:
        logger.warning(f"land_purchase notify failed: {_e}")
    
    return {"status": "success", "plot": plot_data, "new_balance": new_balance}

@api_router.post("/cities/{city_id}/plots/{x}/{y}/build")
async def build_business_in_city(city_id: str, x: int, y: int, request: dict, current_user: User = Depends(get_current_user)):
    """Build a business on owned plot in a city"""
    business_type = request.get("business_type")
    
    if not business_type or business_type not in BUSINESS_TYPES:
        raise HTTPException(status_code=400, detail="Неверный тип бизнеса")
    
    bt = BUSINESS_TYPES[business_type]
    
    # Find the plot
    plot = await db.plots.find_one({"city_id": city_id, "x": x, "y": y})
    if not plot:
        raise HTTPException(status_code=404, detail="Участок не найден")
    
    # Get user
    user = await db.users.find_one({"id": current_user.id})
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    # Check ownership - use consistent user ID logic
    user_id = user.get("id", str(user.get("_id")))
    if plot.get("owner") != user_id:
        raise HTTPException(status_code=403, detail="You don't own this plot")
    
    # Check if business already exists
    if plot.get("business_id"):
        raise HTTPException(status_code=400, detail="Бизнес уже существует на этом участке")
    
    # Check balance (excluding frozen tender escrow)
    build_cost = bt["cost"]
    from core.balance import total_available_ton as _tat
    if _tat(user) + 1e-9 < build_cost:
        raise await _insufficient_funds(user, build_cost)
    
    # Create business
    business_id = f"biz_{city_id}_{x}_{y}"
    business_data = {
        "id": business_id,
        "city_id": city_id,
        "plot_id": plot["id"],
        "plot_x": x,
        "plot_y": y,
        "business_type": business_type,
        "owner": user_id,  # Use consistent user ID
        "owner_username": user.get("username"),
        "level": 1,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "last_collection": datetime.now(timezone.utc).isoformat(),
        "total_income": 0,
        "status": "active"
    }
    
    await db.businesses.insert_one(business_data.copy())
    
    # Update plot
    await db.plots.update_one(
        {"city_id": city_id, "x": x, "y": y},
        {"$set": {"business_id": business_id, "business_type": business_type}}
    )
    
    # Update user — F10 atomic debit; roll back the business/plot on failure.
    _build_upd = await debit_user_split({"id": user_id}, build_cost, extra_update={"$push": {"businesses_owned": business_id}})
    if not _build_upd.get("ok"):
        await db.businesses.delete_one({"id": business_id})
        await db.plots.update_one(
            {"city_id": city_id, "x": x, "y": y},
            {"$unset": {"business_id": "", "business_type": ""}}
        )
        raise await _insufficient_funds(user, build_cost)
    
    # In-app + telegram notification
    try:
        from core.notify import notify_user
        await notify_user(
            db, user,
            title="Бизнес построен",
            message=f"Вы построили «{bt.get('name', business_type)}» на участке ({x}, {y}). Бизнес начнёт приносить доход.",
            type_key="business_build",
            priority="success",
            payload={"business_id": business_id, "business_type": business_type, "x": x, "y": y, "city_id": city_id},
            i18n_key="business_build",
            i18n_vars={"name": bt.get('name', business_type), "x": x, "y": y},
        )
    except Exception as _e:
        logger.warning(f"business_build notify failed: {_e}")
    
    return {
        "status": "success", 
        "business": {
            "id": business_id,
            "type": business_type,
            "icon": bt["icon"],
            "name": bt["name"]
        },
        "new_balance": user.get("balance_ton", 0) - build_cost
    }

# ==================== PLOTS ROUTES (Legacy) ====================

@api_router.get("/plots")
async def get_all_plots():
    """Get all plots with ownership info"""
    plots = await db.plots.find({}, {"_id": 0}).to_list(10000)
    businesses = await db.businesses.find({}, {"_id": 0}).to_list(10000)
    business_map = {b["plot_id"]: b for b in businesses}
    
    result = []
    for plot in plots:
        business = business_map.get(plot["id"])
        bt = BUSINESS_TYPES.get(business["business_type"]) if business else None
        result.append({
            "id": plot["id"],
            "x": plot["x"],
            "y": plot["y"],
            "zone": plot.get("zone", "outskirts"),
            "owner": plot.get("owner"),
            "price": plot["price"],
            "is_available": plot.get("is_available", True),
            "is_rented": plot.get("is_rented", False),
            "rent_price": plot.get("rent_price"),
            "business_id": plot.get("business_id"),
            "business_type": business["business_type"] if business else None,
            "business_icon": bt["icon"] if bt else None,
            "business_level": business.get("level", 1) if business else None
        })
    
    return {"plots": result, "total": len(result)}

@api_router.get("/plots/coords/{x}/{y}")
async def get_plot_by_coords(x: int, y: int):
    """Get plot by coordinates with owner info"""
    plot = await db.plots.find_one({"x": x, "y": y}, {"_id": 0})
    
    if not plot:
        price, zone = calculate_plot_price(x, y)
        new_plot = Plot(x=x, y=y, price=price, zone=zone)
        plot_dict = new_plot.model_dump()
        await db.plots.insert_one(plot_dict.copy())
        plot = await db.plots.find_one({"x": x, "y": y}, {"_id": 0})
    
    business = None
    if plot.get("business_id"):
        business = await db.businesses.find_one({"id": plot["business_id"]}, {"_id": 0})
    
    # Get owner info if plot is owned
    owner_info = None
    if plot.get("owner"):
        owner = await db.users.find_one(
            {"$or": [{"wallet_address": plot["owner"]}, {"id": plot.get("owner_id")}]},
            {"_id": 0, "hashed_password": 0, "two_factor_secret": 0, "backup_codes": 0}
        )
        if owner:
            owner_info = {
                "id": owner.get("id"),
                "username": owner.get("username"),
                "display_name": owner.get("display_name") or owner.get("username"),
                "avatar": owner.get("avatar"),
                "level": owner.get("level", 1)
            }
    
    return {
        **plot,
        "business": business,
        "business_info": BUSINESS_TYPES.get(business["business_type"]) if business else None,
        "owner_info": owner_info
    }

@api_router.post("/plots/purchase")
async def purchase_plot(request: PurchasePlotRequest, current_user: User = Depends(get_current_user)):
    """Purchase plot using internal balance"""
    x, y = request.plot_x, request.plot_y
    lang = current_user.language
    
    # Check player limits
    # Check plot limit - 3 plots max for regular users, unlimited for admins and banks
    is_admin = current_user.is_admin or current_user.role == "ADMIN"
    is_bank = getattr(current_user, 'is_bank', False) or current_user.role == "BANK"
    
    if not is_admin and not is_bank:
        max_plots = 3  # Fixed limit of 3 plots for all regular users
        if len(current_user.plots_owned) >= max_plots:
            raise HTTPException(status_code=400, detail=t("max_plots_reached", lang))
    
    plot = await db.plots.find_one({"x": x, "y": y}, {"_id": 0})
    
    if not plot:
        price, zone = calculate_plot_price(x, y)
        new_plot = Plot(x=x, y=y, price=price, zone=zone)
        plot_dict = new_plot.model_dump()
        await db.plots.insert_one(plot_dict.copy())
        plot = await db.plots.find_one({"x": x, "y": y}, {"_id": 0})
    
    if not plot.get("is_available", True):
        raise HTTPException(status_code=400, detail=t("plot_not_available", lang))
    
    # Check balance (excluding frozen tender escrow)
    plot_price = plot["price"]
    buyer_doc_for_check = await db.users.find_one({"id": current_user.id}, {"_id": 0}) \
        or await db.users.find_one({"id": current_user.id}, {"_id": 0}) if (current_user.wallet_address or current_user.email) else None
    from core.balance import total_available_ton as _tat
    avail = _tat(buyer_doc_for_check) if buyer_doc_for_check else float(current_user.balance_ton or 0)
    if avail + 1e-9 < plot_price:
        raise await _insufficient_funds(buyer_doc_for_check, plot_price)
    
    # Check zone limits
    zone = plot.get("zone", "outskirts")
    zone_limit = ZONES.get(zone, {}).get("plot_limit", 30)
    user_plots_in_zone = await db.plots.count_documents({
        "owner": owner_key(current_user),
        "zone": zone
    })
    if user_plots_in_zone >= zone_limit:
        raise HTTPException(status_code=400, detail=f"Zone limit reached for {zone}")
    
    # Deduct from internal balance.
    # F10 hardening: atomic compare-and-set to prevent double-buy race.
    _upd = await debit_user_split({"id": current_user.id}, plot_price)
    if not _upd.get("ok"):
        raise await _insufficient_funds(buyer_doc_for_check, plot_price)
    
    # Update plot owner
    await db.plots.update_one(
        {"id": plot["id"]},
        {
            "$set": {
                "owner": owner_key(current_user),
                "owner_id": current_user.id,
                "owner_avatar": current_user.avatar,
                "owner_username": current_user.username,
                "is_available": False,
                "purchased_at": datetime.now(timezone.utc).isoformat()
            }
        }
    )
    
    # Update user plots
    await db.users.update_one(
        {"id": current_user.id},
        {"$push": {"plots_owned": plot["id"]}}
    )

    # Referral Rally: pay 1.5 TON bonus to referrer if active campaign & first plot
    try:
        from promo_service import maybe_pay_activation_bonus
        await maybe_pay_activation_bonus(db, current_user.id)
    except Exception as _e:
        logger.debug(f"promo activation bonus (plot purchase) failed: {_e}")
    
    # Record transaction
    tx = Transaction(
        tx_type="purchase_plot",
        from_address=current_user.wallet_address,
        to_address="admin_treasury",
        amount_ton=plot_price,
        plot_id=plot["id"],
        status="completed"
    )
    tx_dict = tx.model_dump()
    tx_dict['created_at'] = tx_dict['created_at'].isoformat()
    await db.transactions.insert_one(tx_dict.copy())
    
    # Record in user transaction history
    import uuid as uuid_module
    history_tx = {
        "id": str(uuid_module.uuid4()),
        "user_id": current_user.id,
        "type": "land_purchase",
        "amount": -plot_price,
        "details": {
            "plot_id": plot["id"],
            "plot_x": x,
            "plot_y": y,
            "zone": zone,
            "price": plot_price
        },
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.transactions.insert_one(history_tx)
    
    # B2B partner land-sale commission (credit the buyer's partner, if any)
    try:
        from b2b_partners import credit_land_sale
        await credit_land_sale(db, current_user.id, plot_price)
    except Exception as _e:
        logger.debug(f"b2b land-sale credit (plot purchase) failed: {_e}")

    # Partner task tracking: a land purchase may complete the partner conditions.
    try:
        from routes.partner_programs import check_partner_conditions
        await check_partner_conditions(db, current_user.id)
    except Exception as _e:
        logger.debug(f"check_partner_conditions (plot purchase) failed: {_e}")
    
    # Record admin income
    await db.admin_stats.update_one(
        {"type": "treasury"},
        {
            "$inc": {
                "plot_sales_income": plot_price,
                "total_plot_sales": 1
            }
        },
        upsert=True
    )
    
    logger.info(f"Plot ({x}, {y}) purchased by {current_user.wallet_address} for {plot_price} TON")
    
    return {
        "success": True,
        "plot_id": plot["id"],
        "amount_paid": plot_price,
        "new_balance": current_user.balance_ton - plot_price,
        "message": f"Plot ({x}, {y}) purchased successfully!"
    }

@api_router.post("/plots/confirm-purchase")
async def confirm_plot_purchase(request: ConfirmTransactionRequest, current_user: User = Depends(get_current_user)):
    """Confirm plot purchase"""
    tx = await db.transactions.find_one({"id": request.transaction_id}, {"_id": 0})
    
    if not tx or tx["from_address"] != current_user.wallet_address:
        raise HTTPException(status_code=404, detail="Транзакция не найдена")
    
    if tx["status"] == "completed":
        raise HTTPException(status_code=400, detail="Транзакция уже завершена")
    
    # Update transaction
    await db.transactions.update_one(
        {"id": request.transaction_id},
        {"$set": {"status": "completed", "blockchain_hash": request.blockchain_hash, 
                  "completed_at": datetime.now(timezone.utc).isoformat()}}
    )
    
    # Update plot
    await db.plots.update_one(
        {"id": tx["plot_id"]},
        {"$set": {"owner": owner_key(current_user), "is_available": False,
                  "purchased_at": datetime.now(timezone.utc).isoformat()}}
    )
    
    # Update user
    await db.users.update_one(
        {"id": current_user.id},
        {"$push": {"plots_owned": tx["plot_id"]},
         "$inc": {"total_turnover": tx["amount_ton"]}}
    )

    # Referral Rally: pay 1.5 TON bonus to referrer if active campaign & first plot
    try:
        from promo_service import maybe_pay_activation_bonus
        await maybe_pay_activation_bonus(db, current_user.id)
    except Exception as _e:
        logger.debug(f"promo activation bonus (confirm) failed: {_e}")
    
    # Update admin stats
    await db.admin_stats.update_one(
        {"type": "treasury"},
        {"$inc": {"total_plot_sales": tx["amount_ton"], "total_income": tx["amount_ton"]}},
        upsert=True
    )
    
    # Broadcast update
    await manager.broadcast({"type": "plot_sold", "plot_id": tx["plot_id"], "owner": owner_key(current_user)})
    
    return {"status": "completed", "plot_id": tx["plot_id"], "message": t("plot_purchased", current_user.language)}

@api_router.post("/plots/resale")
async def resale_plot(request: ResalePlotRequest, current_user: User = Depends(get_current_user)):
    """List plot for resale with minimum price rules"""
    plot = await db.plots.find_one({"id": request.plot_id}, {"_id": 0})
    
    if not plot or plot.get("owner") != current_user.wallet_address:
        raise HTTPException(status_code=404, detail="Plot not found or not owned")
    
    # Calculate original plot price
    original_price = calculate_plot_price(plot["x"], plot["y"])
    min_plot_price = original_price * 0.5  # 50% of original
    
    # If plot has business, cannot sell (must demolish first or include in price)
    business = None
    if plot.get("business_id"):
        business = await db.businesses.find_one({"id": plot["business_id"]}, {"_id": 0})
        if business:
            # Get business cost
            business_config = BUSINESS_TYPES.get(business["business_type"], {})
            business_cost = business_config.get("cost", 0)
            level = business.get("level", 1)
            
            # Calculate total business investment
            total_business_cost = business_cost
            for lvl in range(2, level + 1):
                upgrade_cost = LEVEL_CONFIG.get(lvl, {}).get("upgrade_cost", 0)
                total_business_cost += upgrade_cost
            
            # Minimum price = plot price + half of business value
            min_plot_price = original_price + (total_business_cost * 0.5)
    
    # Check minimum price
    if request.price < min_plot_price:
        raise HTTPException(
            status_code=400, 
            detail=f"Price too low. Minimum price: {min_plot_price} TON (50% of original value{' + half of business value' if business else ''})"
        )
    
    await db.plots.update_one(
        {"id": request.plot_id},
        {"$set": {
            "is_available": True, 
            "price": request.price, 
            "is_resale": True,
            "original_price": original_price,
            "has_business": bool(business)
        }}
    )
    
    # Record transaction for listing the plot for sale
    ui = await get_user_identifiers(current_user)
    if ui["user"]:
        tx = {
            "id": str(uuid.uuid4()),
            "type": "land_sale_listing",
            "user_id": ui["user"].get("id", ""),
            "amount_ton": 0,
            "amount_city": 0,
            "plot_id": request.plot_id,
            "plot_coords": f"[{plot['x']}, {plot['y']}]",
            "description": f"Участок [{plot['x']}, {plot['y']}] выставлен на продажу за {request.price * 1000:.0f} $CITY",
            "status": "completed",
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await db.transactions.insert_one(tx)
    
    return {
        "status": "listed", 
        "plot_id": request.plot_id, 
        "price": request.price,
        "min_price": min_plot_price,
        "has_business": bool(business)
    }

@api_router.post("/plots/buy-resale/{plot_id}")
async def buy_resale_plot(plot_id: str, current_user: User = Depends(get_current_user)):
    """Buy a resale plot with 15% tax"""
    plot = await db.plots.find_one({"id": plot_id}, {"_id": 0})
    
    if not plot or not plot.get("is_resale"):
        raise HTTPException(status_code=404, detail="Участок не выставлен на продажу")
    
    if plot["owner"] == current_user.wallet_address:
        raise HTTPException(status_code=400, detail="Нельзя купить свой собственный участок")
    
    seller_address = plot["owner"]
    price = plot["price"]
    commission = price * RESALE_COMMISSION  # 15% tax
    seller_amount = price - commission
    
    # Check buyer balance (excluding frozen tender escrow)
    buyer = await db.users.find_one({"id": current_user.id}, {"_id": 0})
    from core.balance import total_available_ton as _tat
    if _tat(buyer) + 1e-9 < price:
        raise await _insufficient_funds(buyer, price)
    
    # Transfer ownership
    await db.plots.update_one(
        {"id": plot_id},
        {"$set": {
            "owner": owner_key(current_user),
            "is_available": False,
            "is_resale": False,
            "price": plot.get("original_price", price)  # Reset to original price
        }}
    )
    
    # Update buyer balance — F10 atomic debit; restore the plot on failure.
    _resale_upd = await debit_user_split({"id": current_user.id}, price,
                                         extra_update={"$push": {"plots_owned": f"{plot['x']},{plot['y']}"}})
    if not _resale_upd.get("ok"):
        await db.plots.update_one(
            {"id": plot_id},
            {"$set": {"owner": seller_address, "is_available": False, "is_resale": True, "price": price}}
        )
        raise await _insufficient_funds(buyer, price)

    # Referral Rally: pay 1.5 TON bonus to referrer if active campaign & first plot
    try:
        from promo_service import maybe_pay_activation_bonus
        await maybe_pay_activation_bonus(db, current_user.id)
    except Exception as _e:
        logger.debug(f"promo activation bonus (resale) failed: {_e}")
    
    # Update seller balance — the seller found by id (the plot's owner field)
    _seller = await find_user(db, seller_address, projection={"_id": 0, "id": 1})
    _seller_q = {"id": _seller["id"]} if _seller else {"wallet_address": seller_address}
    await db.users.update_one(
        _seller_q,
        {"$inc": {"balance_ton": seller_amount}, "$pull": {"plots_owned": f"{plot['x']},{plot['y']}"}}
    )
    
    # If plot has business, transfer it too
    if plot.get("business_id"):
        await db.businesses.update_one(
            {"id": plot["business_id"]},
            {"$set": {"owner": owner_key(current_user)}}
        )
        
        # Update business ownership lists
        await db.users.update_one(
            _seller_q,
            {"$pull": {"businesses_owned": plot["business_id"]}}
        )
        await db.users.update_one(
            {"id": current_user.id},
            {"$push": {"businesses_owned": plot["business_id"]}}
        )
    
    # Add commission to treasury
    await db.admin_stats.update_one(
        {"type": "treasury"},
        {"$inc": {"resale_tax": commission, "total_income": commission}},
        upsert=True
    )
    
    # Record transaction
    tx = Transaction(
        tx_type="resale_plot",
        from_address=current_user.wallet_address,
        to_address=seller_address,
        amount_ton=price,
        commission=commission,
        plot_id=plot_id
    )
    tx_dict = tx.model_dump()
    tx_dict['created_at'] = tx_dict['created_at'].isoformat()
    await db.transactions.insert_one(tx_dict.copy())
    
    logger.info(f"Plot resale: {plot_id} from {seller_address} to {current_user.wallet_address} for {price} TON")
    
    return {
        "transaction_id": tx.id,
        "plot_id": plot_id,
        "amount_ton": price,
        "commission": commission,
        "seller_receives": seller_amount,
        "business_transferred": bool(plot.get("business_id"))
    }

# ==================== BUSINESS ROUTES ====================

@api_router.get("/businesses/types")
async def get_business_types(lang: str = "ru"):
    """Get all available business types from the new system"""
    result = {}
    for key, bt in BUSINESSES.items():
        # Get localized name
        name = bt.get("name", {})
        if isinstance(name, dict):
            name_str = name.get(lang) or name.get("ru") or name.get("en") or key
        else:
            name_str = str(name)
        
        result[key] = {
            "name": name_str,
            "tier": bt.get("tier", 1),
            "icon": bt.get("icon", "🏢"),
            "produces": bt.get("produces"),
            "consumes": bt.get("consumes", []),
            "base_production": bt.get("base_production", 0),
            "base_income": bt.get("base_income", 0),
            "base_cost_ton": bt.get("base_cost_ton", 10),
            "daily_wear": bt.get("daily_wear", 0.03),
            "description": bt.get("description", {}).get(lang) or bt.get("description", {}).get("ru") or "",
            "is_patron": bt.get("is_patron", False),
            "patron_type": bt.get("patron_type"),
        }
    return {"business_types": result}

@api_router.get("/businesses")
async def get_all_businesses():
    """Get all businesses"""
    # Trial Centers are virtual (no plot) and must never appear in the global
    # map/business list — exclude them to avoid KeyError on `plot_id`.
    businesses = await db.businesses.find({"is_trial": {"$ne": True}}, {"_id": 0}).to_list(10000)
    
    # Batch load all plots to avoid N+1 query
    plot_ids = [b.get("plot_id") for b in businesses if b.get("plot_id")]
    plots = await db.plots.find({"id": {"$in": plot_ids}}, {"_id": 0}).to_list(10000)
    plots_map = {p["id"]: p for p in plots}
    
    result = []
    for b in businesses:
        plot = plots_map.get(b.get("plot_id"))
        bt = BUSINESS_TYPES.get(b["business_type"], {})
        income = calculate_business_income(
            b["business_type"], 
            b.get("level", 1), 
            plot.get("zone", "outskirts") if plot else "outskirts",
            len(b.get("connected_businesses", []))
        )
        result.append({
            "id": b["id"],
            "plot_id": b["plot_id"],
            "owner": b["owner"],
            "business_type": b["business_type"],
            "business_name": bt.get("name", {}).get("en", "Unknown"),
            "business_icon": bt.get("icon", "❓"),
            "level": b.get("level", 1),
            "xp": b.get("xp", 0),
            "income": income,
            "storage": b.get("storage", {}),
            "connected_businesses": b.get("connected_businesses", []),
            "is_active": b.get("is_active", True),
            "building_progress": b.get("building_progress", 100),
            "x": plot["x"] if plot else 0,
            "y": plot["y"] if plot else 0,
            "zone": plot.get("zone", "outskirts") if plot else "outskirts"
        })
    
    return {"businesses": result}

@api_router.post("/businesses/build")
async def build_business(request: BuildBusinessRequest, current_user: User = Depends(get_current_user)):
    """Build business using internal balance"""
    lang = current_user.language
    
    plot = await db.plots.find_one({"id": request.plot_id}, {"_id": 0})
    if not plot or plot.get("owner") != current_user.wallet_address:
        raise HTTPException(status_code=404, detail="Plot not found or not owned")
    
    if plot.get("business_id"):
        raise HTTPException(status_code=400, detail="Plot already has a business")
    
    if request.business_type not in BUSINESS_TYPES:
        raise HTTPException(status_code=400, detail="Неверный тип бизнеса")
    
    bt = BUSINESS_TYPES[request.business_type]
    zone = plot.get("zone", "outskirts")
    
    # Check zone restrictions
    if zone not in bt.get("allowed_zones", []):
        raise HTTPException(status_code=400, detail=t("invalid_zone", lang))
    
    # Check per-player limits
    user_biz_count = await db.businesses.count_documents({
        "owner": owner_key(current_user),
        "business_type": request.business_type
    })
    if user_biz_count >= bt.get("max_per_player", 999):
        raise HTTPException(status_code=400, detail="Maximum businesses of this type reached")
    
    # Check global limits
    if "max_total" in bt:
        total_count = await db.businesses.count_documents({"business_type": request.business_type})
        if total_count >= bt["max_total"]:
            raise HTTPException(status_code=400, detail="Maximum total businesses of this type reached")
    
    # Calculate costs
    materials_cost = bt["materials_required"] * RESOURCE_PRICES.get("materials", 0.005)
    total_cost = bt["cost"] + materials_cost
    
    # Check balance (bonus + real)
    _u_bd = await db.users.find_one({"id": current_user.id}, {"_id": 0, "bonus_balance": 1, "balance_ton": 1})
    _avail = float((_u_bd or {}).get("bonus_balance", 0) or 0) + float((_u_bd or {}).get("balance_ton", 0) or 0)
    if _avail < total_cost:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient balance. Need {total_cost} TON, have {_avail} TON"
        )
    
    # Deduct from internal balance — bonus funds first, then real balance.
    _deb = await debit_user_split({"id": current_user.id}, total_cost)
    if not _deb.get("ok"):
        raise HTTPException(status_code=400, detail="Недостаточно средств")
    
    # Create business
    business = Business(
        plot_id=request.plot_id,
        owner=current_user.wallet_address,
        business_type=request.business_type,
        level=1,
        building_progress=100,  # Instant build for now
        is_active=True,
        last_collection=datetime.now(timezone.utc).isoformat()
    )
    business_dict = business.model_dump()
    business_dict['created_at'] = business_dict['created_at'].isoformat()
    business_dict['last_collection'] = business_dict['last_collection']
    await db.businesses.insert_one(business_dict.copy())
    
    # Update plot
    await db.plots.update_one(
        {"id": request.plot_id},
        {"$set": {"business_id": business.id}}
    )
    
    # Update user
    await db.users.update_one(
        {"id": current_user.id},
        {"$push": {"businesses_owned": business.id},
         # Buying a real business with real funds marks the user as an active
         # investor (spec §P2P). Trial Center does NOT set this flag.
         "$set": {"is_active_investor": True}}
    )
    
    # Record transaction
    tx = Transaction(
        tx_type="build_business",
        from_address=current_user.wallet_address,
        to_address="construction_pool",
        amount_ton=total_cost,
        plot_id=request.plot_id,
        status="completed"
    )
    tx_dict = tx.model_dump()
    tx_dict['created_at'] = tx_dict['created_at'].isoformat()
    await db.transactions.insert_one(tx_dict.copy())
    
    # Record admin income
    await db.admin_stats.update_one(
        {"type": "treasury"},
        {
            "$inc": {
                "building_sales_income": total_cost,
                "total_buildings_sold": 1
            }
        },
        upsert=True
    )
    
    logger.info(f"Business {request.business_type} built by {current_user.wallet_address} for {total_cost} TON")
    
    return {
        "success": True,
        "business_id": business.id,
        "business_type": request.business_type,
        "amount_paid": total_cost,
        "new_balance": current_user.balance_ton - total_cost,
        "message": f"{bt['name']['en']} built successfully!"
    }

@api_router.post("/businesses/confirm-build")
async def confirm_business_build(request: ConfirmTransactionRequest, current_user: User = Depends(get_current_user)):
    """Confirm business building after payment"""
    tx = await db.transactions.find_one({"id": request.transaction_id}, {"_id": 0})
    
    if not tx or tx["from_address"] != current_user.wallet_address:
        raise HTTPException(status_code=404, detail="Транзакция не найдена")
    
    if tx["status"] == "completed":
        raise HTTPException(status_code=400, detail="Транзакция уже завершена")
    
    plot = await db.plots.find_one({"id": tx["plot_id"]}, {"_id": 0})
    _bo_keys = await resolve_owner_keys(db, current_user.wallet_address or current_user.id)
    build_order = await db.build_orders.find_one(
        {"plot_id": tx["plot_id"], "status": "pending", **owner_businesses_query(_bo_keys)},
        {"_id": 0},
    )
    
    if not build_order:
        raise HTTPException(status_code=404, detail="Build order not found")
    
    bt = BUSINESS_TYPES.get(build_order["business_type"])
    zone = plot.get("zone", "outskirts") if plot else "outskirts"
    
    # Create business (starts building)
    business = Business(
        plot_id=tx["plot_id"],
        owner=current_user.wallet_address,
        business_type=build_order["business_type"],
        income_rate=bt["base_income"],
        production_rate=bt.get("production_rate", 0),
        building_progress=0  # Will be updated by construction companies or time
    )
    business_dict = business.model_dump()
    business_dict['created_at'] = business_dict['created_at'].isoformat()
    business_dict['last_collection'] = business_dict['last_collection'].isoformat()
    await db.businesses.insert_one(business_dict.copy())
    
    # Update plot
    await db.plots.update_one(
        {"id": tx["plot_id"]},
        {"$set": {"business_id": business.id}}
    )
    
    # Update transaction
    await db.transactions.update_one(
        {"id": request.transaction_id},
        {"$set": {"status": "completed", "business_id": business.id, "blockchain_hash": request.blockchain_hash,
                  "completed_at": datetime.now(timezone.utc).isoformat()}}
    )
    
    # Update build order
    await db.build_orders.update_one(
        {"id": build_order["id"]},
        {"$set": {"status": "in_progress", "started_at": datetime.now(timezone.utc).isoformat(),
                  "estimated_completion": (datetime.now(timezone.utc) + timedelta(hours=bt["build_time_hours"])).isoformat()}}
    )
    
    # Update user
    await db.users.update_one(
        {"id": current_user.id},
        {"$push": {"businesses_owned": business.id},
         "$inc": {"total_turnover": tx["amount_ton"]}}
    )
    
    # Find and connect related businesses
    await connect_businesses(business.id, build_order["business_type"], plot["x"], plot["y"])
    
    # Broadcast update
    await manager.broadcast({"type": "business_built", "business_id": business.id, "plot_id": tx["plot_id"]})
    
    return {
        "status": "building",
        "business_id": business.id,
        "business_type": build_order["business_type"],
        "build_time_hours": bt["build_time_hours"],
        "message": t("business_built", current_user.language)
    }


@api_router.post("/businesses/demolish/{business_id}")
async def demolish_business(business_id: str, current_user: User = Depends(get_current_user)):
    """Demolish business for 5% of its cost"""
    business = await db.businesses.find_one({"id": business_id}, {"_id": 0})
    
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")
    
    if business["owner"] != current_user.wallet_address:
        raise HTTPException(status_code=403, detail="Not your business")
    if int(business.get("level", 1) or 0) == 0:
        raise HTTPException(status_code=403, detail="Бизнес нулевого уровня нельзя снести. Прокачайте его до 1 уровня.")
    
    # Calculate demolish cost (5% of total investment)
    business_config = BUSINESS_TYPES.get(business["business_type"], {})
    base_cost = business_config.get("cost", 0)
    level = business.get("level", 1)
    
    # Calculate total investment
    total_investment = base_cost
    for lvl in range(2, level + 1):
        upgrade_cost = LEVEL_CONFIG.get(lvl, {}).get("upgrade_cost", 0)
        total_investment += upgrade_cost
    
    demolish_cost = total_investment * DEMOLISH_COST  # 5%
    
    # Check balance
    user = await db.users.find_one({"id": current_user.id}, {"_id": 0})
    # Списание: бонус → реальный (атомарно)
    _demo_upd = await debit_user_split({"id": current_user.id}, demolish_cost)
    if not _demo_upd.get("ok"):
        raise await _insufficient_funds(user, demolish_cost)
    
    # Remove business from plot
    plot = await db.plots.find_one({"business_id": business_id}, {"_id": 0})
    if plot:
        await db.plots.update_one(
            {"id": plot["id"]},
            {"$set": {"business_id": None}}
        )
    
    # Delete business
    await db.businesses.delete_one({"id": business_id})
    
    # Remove from user's businesses list
    await db.users.update_one(
        {"id": current_user.id},
        {"$pull": {"businesses_owned": business_id}}
    )
    
    # Add to treasury
    await db.admin_stats.update_one(
        {"type": "treasury"},
        {"$inc": {"demolish_fees": demolish_cost, "total_income": demolish_cost}},
        upsert=True
    )
    
    # Record transaction
    tx = Transaction(
        tx_type="demolish_business",
        from_address=current_user.wallet_address,
        to_address="treasury",
        amount_ton=demolish_cost,
        commission=0,
        metadata={"business_id": business_id, "business_type": business["business_type"], "level": level}
    )
    tx_dict = tx.model_dump()
    tx_dict['created_at'] = tx_dict['created_at'].isoformat()
    await db.transactions.insert_one(tx_dict)
    
    logger.info(f"Business demolished: {business_id} by {current_user.wallet_address} for {demolish_cost} TON")
    
    return {
        "status": "demolished",
        "business_id": business_id,
        "demolish_cost": demolish_cost,
        "plot_freed": bool(plot)
    }

async def connect_businesses(business_id: str, business_type: str, x: int, y: int):
    """Connect business with nearby compatible businesses"""
    bt = BUSINESS_TYPES.get(business_type, {})
    requires = bt.get("requires")
    produces = bt.get("produces")
    
    # Find nearby businesses (within 5 tiles)
    nearby_plots = await db.plots.find({
        "business_id": {"$exists": True, "$ne": None},
        "x": {"$gte": x - 5, "$lte": x + 5},
        "y": {"$gte": y - 5, "$lte": y + 5}
    }, {"_id": 0}).to_list(100)
    
    connections = []
    for plot in nearby_plots:
        if plot.get("business_id") == business_id:
            continue
        
        nearby_business = await db.businesses.find_one({"id": plot["business_id"]}, {"_id": 0})
        if not nearby_business:
            continue
        
        nearby_bt = BUSINESS_TYPES.get(nearby_business["business_type"], {})
        
        if requires and nearby_bt.get("produces") == requires:
            connections.append(nearby_business["id"])
            await db.businesses.update_one(
                {"id": nearby_business["id"]},
                {"$addToSet": {"connected_businesses": business_id}}
            )
        
        if produces and nearby_bt.get("requires") == produces:
            connections.append(nearby_business["id"])
            await db.businesses.update_one(
                {"id": nearby_business["id"]},
                {"$addToSet": {"connected_businesses": business_id}}
            )
    
    if connections:
        await db.businesses.update_one(
            {"id": business_id},
            {"$set": {"connected_businesses": connections}}
        )

@api_router.post("/businesses/collect/{business_id}")
async def collect_income(business_id: str, current_user: User = Depends(get_current_user)):
    """Collect accumulated resources from business (NOT money - resources go to warehouse)"""
    business = await db.businesses.find_one({"id": business_id}, {"_id": 0})
    
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")
    
    # Check ownership using consistent user ID logic
    user = await db.users.find_one({"id": current_user.id})
    
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    user_id = user.get("id", str(user.get("_id")))
    
    if business["owner"] != user_id and business["owner"] != current_user.wallet_address:
        raise HTTPException(status_code=404, detail="Business not found")
    
    if business.get("building_progress", 100) < 100:
        raise HTTPException(status_code=400, detail="Business still under construction")
    
    # Get business config
    business_type = business.get("business_type")
    config = BUSINESSES.get(business_type, {})
    produces = config.get("produces", "")
    production_rate = config.get("production_rate", 10)  # per hour
    
    # Calculate resources produced since last collection
    last_collection = to_aware(business.get("last_collection")) or datetime.now(timezone.utc)
    hours_passed = (datetime.now(timezone.utc) - last_collection).total_seconds() / 3600
    
    level = business.get("level", 1)
    level_mult = LEVEL_CONFIG.get(level, {}).get("income_mult", 1.0)
    
    # Calculate actual production (resources, NOT money)
    base_production = production_rate * hours_passed
    actual_production = base_production * level_mult
    
    # Check warehouse capacity — use the SAME weighted calculation as /market/buy
    # (sum of business storage capacities, tier-weighted usage) instead of the
    # legacy `user.warehouse.capacity` field which no longer exists.
    buyer_free_units = await _get_buyer_free_warehouse(user)
    weight_per_unit = get_warehouse_weight(produces) or 1
    max_collectible_units = buyer_free_units / weight_per_unit if weight_per_unit > 0 else 0
    collected_resources = min(actual_production, max_collectible_units)
    
    if collected_resources <= 0:
        raise HTTPException(status_code=400, detail="Склад заполнен! Продайте ресурсы или улучшите склад.")
    available_space = buyer_free_units
    
    # Update business
    await db.businesses.update_one(
        {"id": business_id},
        {"$set": {"last_collection": datetime.now(timezone.utc).isoformat()},
         "$inc": {"xp": int(collected_resources * 2)}}
    )
    
    # Add resources to user (NOT money!)
    if produces and produces not in ("ton", "profit_ton"):
        await db.users.update_one(
            {"id": user_id},
            {"$inc": {f"resources.{produces}": round(collected_resources, 2)}}
        )
    
    # Check level up
    business = await db.businesses.find_one({"id": business_id}, {"_id": 0})
    new_level = 1
    for level_num, config in sorted(LEVEL_CONFIG.items(), reverse=True):
        if business.get("xp", 0) >= config["xp_required"]:
            new_level = level_num
            break
    
    if new_level > business.get("level", 1):
        await db.businesses.update_one({"id": business_id}, {"$set": {"level": new_level}})
    
    quest_engine.fire(user.get("id") or current_user.id, "collect", 1)
    return {
        "collected_resource": produces,
        "collected_amount": round(collected_resources, 2),
        "hours_passed": round(hours_passed, 2),
        "production_rate": production_rate,
        "warehouse_space_left": round(available_space - collected_resources, 2),
        "new_xp": business.get("xp", 0),
        "level": new_level,
        "message": f"Собрано {round(collected_resources, 2)} {produces} на склад"
    }

# ==================== TRADE ROUTES ====================

@api_router.post("/trade/contract")
async def create_contract(request: CreateContractRequest, current_user: User = Depends(get_current_user)):
    """Create a resource supply contract"""
    seller_biz = await db.businesses.find_one({"id": request.seller_business_id}, {"_id": 0})
    buyer_biz = await db.businesses.find_one({"id": request.buyer_business_id}, {"_id": 0})
    
    if not seller_biz or seller_biz["owner"] != current_user.wallet_address:
        raise HTTPException(status_code=404, detail="Seller business not found")
    
    if not buyer_biz:
        raise HTTPException(status_code=404, detail="Buyer business not found")
    
    seller_bt = BUSINESS_TYPES.get(seller_biz["business_type"], {})
    buyer_bt = BUSINESS_TYPES.get(buyer_biz["business_type"], {})
    
    if seller_bt.get("produces") != request.resource_type:
        raise HTTPException(status_code=400, detail="Seller doesn't produce this resource")
    
    if buyer_bt.get("requires") != request.resource_type:
        raise HTTPException(status_code=400, detail="Buyer doesn't need this resource")
    
    contract = Contract(
        seller_id=current_user.wallet_address,
        buyer_id=buyer_biz["owner"],
        seller_business_id=request.seller_business_id,
        buyer_business_id=request.buyer_business_id,
        resource_type=request.resource_type,
        amount_per_hour=request.amount_per_hour,
        price_per_unit=request.price_per_unit,
        expires_at=(datetime.now(timezone.utc) + timedelta(days=request.duration_days)).isoformat()
    )
    contract_dict = contract.model_dump()
    contract_dict['created_at'] = contract_dict['created_at'].isoformat()
    await db.contracts.insert_one(contract_dict.copy())
    
    return {"contract_id": contract.id, "status": "pending_acceptance"}

@api_router.post("/trade/contract/accept/{contract_id}")
async def accept_contract(contract_id: str, current_user: User = Depends(get_current_user)):
    """Accept a supply contract"""
    contract = await db.contracts.find_one({"id": contract_id}, {"_id": 0})
    
    if not contract or contract["buyer_id"] != current_user.wallet_address:
        raise HTTPException(status_code=404, detail="Contract not found")
    
    await db.contracts.update_one(
        {"id": contract_id},
        {"$set": {"is_active": True}}
    )
    
    return {"status": "accepted", "contract_id": contract_id}


# ==================== COOPERATION CONTRACTS ====================

class CoopContractCreate(BaseModel):
    resource_type: str
    amount_per_day: float
    price_per_unit: float  # Price per 10 units for Tier 1, per 1 unit for Tier 2/3
    duration_days: int = 30

@api_router.post("/cooperation/create")
async def create_coop_contract(data: CoopContractCreate, current_user: User = Depends(get_current_user)):
    """Create a public cooperation contract offering daily resource supply"""
    ui = await get_user_identifiers(current_user)
    if not ui["user"]:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    user = ui["user"]
    
    if data.amount_per_day <= 0 or data.price_per_unit <= 0 or data.duration_days <= 0:
        raise HTTPException(status_code=400, detail="Некорректные параметры контракта")
    if data.duration_days > 90:
        raise HTTPException(status_code=400, detail="Максимальная длительность 90 дней")
    
    # Determine resource tier
    tier1_resources = ["energy", "scrap", "quartz", "cu", "traffic", "cooling", "biomass"]
    tier3_resources = ["neuro_core", "gold_bill", "license_token", "luck_chip", "war_protocol", "bio_module", "gateway_code"]
    
    resource_tier = 1 if data.resource_type in tier1_resources else (3 if data.resource_type in tier3_resources else 2)
    
    # Tier 1: amount must be divisible by 10
    if resource_tier == 1 and int(data.amount_per_day) % 10 != 0:
        raise HTTPException(status_code=400, detail="Для товаров первого эшелона количество должно быть кратно 10")
    
    # Check user has this resource for first delivery (contract executes immediately)
    user_id = user.get("id", "")
    user_amount = user.get("resources", {}).get(data.resource_type, 0)
    if user_amount < data.amount_per_day:
        res_name = translate_resource_name(data.resource_type)
        raise HTTPException(status_code=400, detail=f"Недостаточно {res_name} для первой поставки. Доступно: {int(user_amount)}")
    
    contract = {
        "id": str(uuid.uuid4()),
        "seller_id": user_id,
        "seller_username": user.get("username"),
        "seller_avatar": user.get("avatar"),
        "resource_type": data.resource_type,
        "resource_tier": resource_tier,
        "amount_per_day": data.amount_per_day,
        "price_per_unit": data.price_per_unit,
        "duration_days": data.duration_days,
        "days_remaining": data.duration_days,
        "buyer_id": None,
        "buyer_username": None,
        "status": "open",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "started_at": None,
        "expires_at": None,
    }
    
    await db.coop_contracts.insert_one(contract.copy())
    return {"status": "created", "contract_id": contract["id"]}


@api_router.get("/cooperation/list")
async def list_coop_contracts(current_user: User = Depends(get_current_user)):
    """Get all open cooperation contracts, filtering hidden ones"""
    ui = await get_user_identifiers(current_user)
    user_doc = ui.get("user") or {}
    hidden_contracts = set(user_doc.get("hidden_contracts", []))
    
    contracts = await db.coop_contracts.find(
        {"status": {"$in": ["open", "active"]}},
        {"_id": 0}
    ).sort("created_at", -1).to_list(50)
    
    # Enrich active contracts with progress info
    now = datetime.now(timezone.utc)
    for c in contracts:
        if c.get("status") == "active" and c.get("started_at"):
            try:
                started = datetime.fromisoformat(str(c["started_at"]).replace('Z', '+00:00'))
                days_elapsed = (now - started).days
                duration = c.get("duration_days", 30)
                c["days_elapsed"] = days_elapsed
                c["days_remaining"] = max(0, duration - days_elapsed)
            except (ValueError, TypeError):
                pass
    
    visible = [c for c in contracts if c.get("id") not in hidden_contracts]
    
    return {"contracts": visible, "total": len(contracts), "hidden_count": len(contracts) - len(visible)}


@api_router.post("/cooperation/accept/{contract_id}")
async def accept_coop_contract(contract_id: str, current_user: User = Depends(get_current_user)):
    """Accept a cooperation contract as buyer"""
    ui = await get_user_identifiers(current_user)
    if not ui["user"]:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    user = ui["user"]
    
    contract = await db.coop_contracts.find_one({"id": contract_id, "status": "open"}, {"_id": 0})
    if not contract:
        raise HTTPException(status_code=404, detail="Контракт не найден или уже принят")
    
    if contract["seller_id"] == user.get("id"):
        raise HTTPException(status_code=400, detail="Нельзя принять свой контракт")
    
    # Calculate first day cost
    daily_cost = (contract["amount_per_day"] / 10) * contract["price_per_10"]
    daily_cost_ton = daily_cost / 1000  # Convert $CITY to TON
    
    from core.balance import total_available_ton as _tat
    if _tat(user) + 1e-9 < daily_cost_ton:
        raise await _insufficient_funds(user, daily_cost_ton)
    
    now = datetime.now(timezone.utc)
    await db.coop_contracts.update_one(
        {"id": contract_id},
        {"$set": {
            "buyer_id": user.get("id"),
            "buyer_username": user.get("username"),
            "status": "active",
            "started_at": now.isoformat(),
            "expires_at": (now + timedelta(days=contract["duration_days"])).isoformat(),
        }}
    )
    
    return {"status": "accepted", "contract_id": contract_id}


@api_router.post("/cooperation/cancel/{contract_id}")
async def cancel_coop_contract(contract_id: str, current_user: User = Depends(get_current_user)):
    """Cancel own open contract"""
    ui = await get_user_identifiers(current_user)
    if not ui["user"]:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    
    contract = await db.coop_contracts.find_one({"id": contract_id}, {"_id": 0})
    if not contract:
        raise HTTPException(status_code=404, detail="Контракт не найден")
    
    if contract["seller_id"] != ui["user"].get("id"):
        raise HTTPException(status_code=403, detail="Это не ваш контракт")
    
    if contract["status"] not in ["open"]:
        raise HTTPException(status_code=400, detail="Можно отменить только открытый контракт")
    
    await db.coop_contracts.update_one(
        {"id": contract_id},
        {"$set": {"status": "cancelled"}}
    )
    
    return {"status": "cancelled"}


@api_router.post("/trade/spot")
async def spot_trade(request: TradeResourceRequest, current_user: User = Depends(get_current_user)):
    """DISABLED. The old direct business-to-business trade let the owner of EITHER
    side start a deal, so a seller could pick someone else's business as the buyer
    and debit that player's balance without consent; it moved money but no
    resources, and matched owners by wallet only (players with e-mail accounts
    could not use it at all). The app trades through the market (listings);
    the old page that called this endpoint is no longer routed."""
    raise HTTPException(status_code=410, detail="Прямая сделка между бизнесами отключена — используйте рынок")


@api_router.get("/trade/contracts")
async def get_user_contracts(current_user: User = Depends(get_current_user)):
    """Get user's contracts"""
    contracts = await db.contracts.find({
        "$or": nz_or([
            {"seller_id": owner_key(current_user)},
            {"buyer_id": current_user.wallet_address},
            {"seller_id": current_user.id},
            {"buyer_id": current_user.id},
        ])
    }, {"_id": 0}).to_list(100)
    
    return {"contracts": contracts}

# ==================== MARKETPLACE ====================

class MarketListing(BaseModel):
    resource_type: str
    amount: float
    price_per_unit: float  # Цена устанавливается продавцом
    business_id: str

class BuyFromMarketRequest(BaseModel):
    listing_id: str
    amount: float

async def _system_level0_price_ton(resource_type: str) -> float:
    """Fixed system price (TON/unit) for level-0 sellers — single rule in core/pricing.py."""
    from core.pricing import level0_price_ton
    return await level0_price_ton(db, resource_type)


@api_router.get("/market/level0-price/{resource_type}")
async def get_level0_price(resource_type: str, current_user: User = Depends(get_current_user)):
    """Return whether the current user is a level-0 seller and the fixed
    system price (in $CITY/unit) they must sell this resource at."""
    import zero_business as _zb
    ui = await get_user_identifiers(current_user)
    is_zero = await _zb.has_zero_business(db, ui["ids"]) if ui.get("ids") else False
    price_ton = await _system_level0_price_ton(resource_type)
    return {"is_level0_seller": bool(is_zero), "price_ton": price_ton,
            "price_city": round(price_ton * 1000.0, 2)}


@api_router.post("/market/list")
async def create_market_listing(data: MarketListing, current_user: User = Depends(get_current_user)):
    """Выставить ресурсы на продажу с собственной ценой"""
    # Tutorial-reward variants (e.g. `neuro_core_tutorial`) are not sellable
    if isinstance(data.resource_type, str) and data.resource_type.endswith("_tutorial"):
        raise HTTPException(
            status_code=400,
            detail="Этот ресурс получен за обучение и не подлежит продаже",
        )
    # Проверяем что бизнес принадлежит пользователю
    business = await db.businesses.find_one({"id": data.business_id}, {"_id": 0})
    
    # Get user from database
    user = None
    if current_user.wallet_address:
        user = await db.users.find_one({"id": current_user.id}, {"_id": 0})
    if not user and current_user.email:
        user = await db.users.find_one({"id": current_user.id}, {"_id": 0})
    
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    user_id = user.get("id", str(user.get("_id")))
    
    # Check business ownership by user_id or wallet
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")
    
    if business["owner"] != user_id and business["owner"] != current_user.wallet_address:
        raise HTTPException(status_code=403, detail="Not your business")
    
    # Use BUSINESSES config from business_config.py (not BUSINESS_TYPES)
    bt = BUSINESSES.get(business["business_type"], {})
    business_produces = bt.get("produces")
    
    # If not in BUSINESSES, check BUSINESS_TYPES as fallback
    if not bt:
        bt = BUSINESS_TYPES.get(business["business_type"], {})
        business_produces = bt.get("produces")
    
    if business_produces != data.resource_type:
        raise HTTPException(status_code=400, detail=f"This business doesn't produce {data.resource_type}. It produces: {business_produces}")
    
    # V4: Base = 1 slot per user-owned REAL business (tutorial businesses
    # excluded); +1 per business whose active buff is "Торговый атташе"
    # (trade_attache). v2.2: no min-1 — a user with zero real businesses
    # can't create real market lots (tutorial lots go through the dedicated
    # /api/tutorial/create-lot endpoint that bypasses this).
    _trade_owner_keys = await resolve_owner_keys(db, user_id)
    user_businesses = await db.businesses.find(
        owner_businesses_query(_trade_owner_keys),
        {"_id": 0, "id": 1, "patron_id": 1, "contract_id": 1, "contract_buff": 1, "tutorial": 1},
    ).to_list(100)
    real_businesses = [b for b in user_businesses if not b.get("tutorial")]
    business_count = len(real_businesses)
    trade_attache_bonus = 0
    for biz in real_businesses:
        contract_doc = None
        if biz.get("contract_id"):
            contract_doc = await db.contracts.find_one(
                {"id": biz["contract_id"], "status": "active"}, {"_id": 0}
            )
        patron_doc = None
        if biz.get("patron_id"):
            patron_doc = await db.businesses.find_one({"id": biz["patron_id"]}, {"_id": 0})
        buff = resolve_business_buff(biz, contract_doc, patron_doc)
        if buff and buff.get("id") == "trade_attache":
            trade_attache_bonus += 1
    max_listings = business_count + trade_attache_bonus
    # No-business players get exactly 1 selling slot.
    if max_listings < 1:
        max_listings = 1
    existing_listings = await db.market_listings.count_documents({"seller_id": user_id, "status": "active"})
    if existing_listings >= max_listings:
        raise HTTPException(
            status_code=400,
            detail=f"Лимит: {max_listings} активных листингов на продажу ресурсов. "
                   "Снимите текущий листинг перед созданием нового."
        )
    
    # Level-0 (test-business) sellers can ONLY sell at the fixed system price
    # (admin-configured market price). The frontend value is ignored.
    import zero_business as _zb
    _seller_keys_l = await resolve_owner_keys(db, user_id)
    _is_zero_seller = await _zb.has_zero_business(db, _seller_keys_l)
    if _is_zero_seller:
        data.price_per_unit = await _system_level0_price_ton(data.resource_type)

    # Проверяем минимальную цену (не ниже 50% от базовой) — для игроков с
    # бизнесом 0 уровня цена системная, проверку пропускаем.
    if not _is_zero_seller:
        base_price = RESOURCE_PRICES.get(data.resource_type, 0.01)
        min_price = base_price * 0.5
        if data.price_per_unit < min_price:
            raise HTTPException(status_code=400, detail=f"Price too low. Minimum: {min_price} TON")
    
    listing = {
        "id": str(uuid.uuid4()),
        "seller_id": user_id,  # Use user_id instead of wallet_address
        "seller_email": user.get("email"),
        "seller_username": user.get("username") or current_user.display_name,
        "business_id": data.business_id,
        "resource_type": data.resource_type,
        "amount": data.amount,
        "price_per_unit": data.price_per_unit,
        "total_price": data.amount * data.price_per_unit,
        "status": "active",
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    await db.market_listings.insert_one(listing.copy())
    
    logger.info(f"Market listing created: {data.amount} {data.resource_type} @ {data.price_per_unit} TON by {user.get('username')}")
    
    quest_engine.fire(current_user.id, "market_list", 1, unique=f"lot:{listing.get('id')}")
    return {"status": "listed", "listing": listing}

async def _enrich_seller_usernames(listings, id_field: str = "seller_id", name_field: str = "seller_username"):
    """Resolve the *current* username from the users collection for denormalized
    listing records, so a user who renames themselves in Settings always shows
    their latest name on the marketplace / trading pages."""
    if not listings:
        return listings
    ids = list({l.get(id_field) for l in listings if l.get(id_field)})
    if not ids:
        return listings
    names = {}
    async for u in db.users.find({"id": {"$in": ids}}, {"_id": 0, "id": 1, "username": 1, "display_name": 1}):
        nm = u.get("username") or u.get("display_name")
        if nm:
            names[u["id"]] = nm
    for l in listings:
        nm = names.get(l.get(id_field))
        if nm:
            l[name_field] = nm
    return listings


@api_router.get("/market/listings")
async def get_market_listings(resource_type: str = None, sort_by: str = "price"):
    """Получить все активные предложения на рынке (скрываем туториальные лоты)"""
    query = {"status": "active", "tutorial": {"$ne": True}}
    if resource_type:
        query["resource_type"] = resource_type
    
    sort_field = "price_per_unit" if sort_by == "price" else "created_at"
    sort_order = 1 if sort_by == "price" else -1
    
    listings = await db.market_listings.find(query, {"_id": 0}).sort(sort_field, sort_order).to_list(100)
    await _enrich_seller_usernames(listings)
    
    return {"listings": listings, "total": len(listings)}

async def _get_buyer_free_warehouse(buyer: dict) -> int:
    """Free weighted warehouse space of a player (core/warehouse.py rule)."""
    if not buyer:
        return 0
    return (await warehouse_rules.user_warehouse(db, buyer))["free"]


@api_router.post("/market/buy")
async def buy_from_market(data: BuyFromMarketRequest, current_user: User = Depends(get_current_user)):
    """Купить ресурсы с рынка"""
    listing = await db.market_listings.find_one({"id": data.listing_id, "status": "active"}, {"_id": 0})
    
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found or no longer active")
    
    # Get buyer from database
    buyer = None
    if current_user.wallet_address:
        buyer = await db.users.find_one({"id": current_user.id}, {"_id": 0})
    if not buyer and current_user.email:
        buyer = await db.users.find_one({"id": current_user.id}, {"_id": 0})
    
    if not buyer:
        raise HTTPException(status_code=404, detail="Buyer not found")
    
    buyer_id = buyer.get("id", str(buyer.get("_id")))

    # P2P read-only gate (spec §2): resources can only be VIEWED until the user
    # owns at least one real business. Then buying unlocks.
    _buyer_keys = {buyer.get("id"), buyer.get("wallet_address"), buyer.get("email")}
    _buyer_keys.discard(None)
    _owns_real = await db.businesses.count_documents({**get_businesses_query(_buyer_keys), "is_trial": {"$ne": True}}) if _buyer_keys else 0
    if _owns_real == 0:
        raise HTTPException(status_code=403, detail="Рынок ресурсов пока доступен только для просмотра. Купите бизнес, чтобы покупать ресурсы.")

    # Check not buying own listing
    if listing["seller_id"] == buyer_id or listing.get("seller_email") == buyer.get("email"):
        raise HTTPException(status_code=400, detail="Cannot buy your own listing")
    
    if data.amount > listing["amount"]:
        raise HTTPException(status_code=409, detail="RESOURCE_UNAVAILABLE")
    
    # Tier 1 resources: only multiples of 10
    tier1_resources = ["energy", "scrap", "quartz", "cu", "traffic", "cooling", "biomass"]
    resource_type = listing.get("resource_type", "")
    if resource_type in tier1_resources and data.amount % 10 != 0:
        raise HTTPException(status_code=400, detail="Ресурсы первого эшелона покупаются только десятками (10, 20, 30...)")

    # Warehouse capacity check (weighted) — buyer must have enough free space.
    buyer_free_units = await _get_buyer_free_warehouse(buyer)
    weight_per_unit = get_warehouse_weight(resource_type)
    needed_weight = int(data.amount) * weight_per_unit
    if needed_weight > buyer_free_units:
        max_buyable = buyer_free_units // weight_per_unit if weight_per_unit > 0 else 0
        if resource_type in tier1_resources:
            max_buyable = (max_buyable // 10) * 10
        raise HTTPException(
            status_code=400,
            detail=(
                f"Недостаточно места на складе. Свободно: {buyer_free_units} слотов, "
                f"нужно: {needed_weight}. Можно купить максимум: {max_buyable}"
            ),
        )
    
    # Рассчитываем стоимость
    total_cost = data.amount * listing["price_per_unit"]
    
    # Проверяем баланс покупателя: бонусные средства + доступные реальные
    # (исключая заморозку по контрактам). Ресурсы можно покупать за бонусы.
    from core.balance import total_available_ton as _tat
    if _tat(buyer) + 1e-9 < total_cost:
        raise await _insufficient_funds(buyer, total_cost)
    
    # Налог с продавца — по тиру ресурса (Tier1→small_business_tax, Tier2→medium, Tier3→large)
    tax_settings = await db.admin_settings.find_one({"type": "tax_settings"}, {"_id": 0})
    resource_info = RESOURCE_TYPES.get(listing.get("resource_type", ""), {})
    resource_tier = resource_info.get("tier", 1)
    tax_rate = await get_business_sale_tax_rate(tax_settings, resource_tier)
    # Seller buffs: Оффшорная зона (patron, trade_tax_reduction, additive pp) +
    # Лицензия оптовика (resource, trade_fee_multiplier, multiplicative).
    # Offshore zone subtracts percentage points from tax_rate; license multiplies the remaining tax.
    seller_buffs_all = await get_user_active_buffs_all(listing["seller_id"])
    tax_reduction = _buff_value_for(seller_buffs_all, "trade_tax_reduction", 0.0)
    license_mult = _buff_value_for(seller_buffs_all, "trade_fee_multiplier", 1.0)
    effective_tax_rate = max(0.0, tax_rate - tax_reduction)
    seller_tax = total_cost * effective_tax_rate * license_mult
    seller_receives = total_cost - seller_tax
    
    # Find seller for balance update
    seller_filter = {"id": listing["seller_id"]}
    if listing.get("seller_email"):
        seller_filter = {"email": listing["seller_email"]}
    
    # ── Race-safe stock claim (atomic): the first buyer wins the units. If two
    # buyers hit at the same moment and there isn't enough for the requested
    # amount, the later one gets RESOURCE_UNAVAILABLE and must refresh. ──
    _stock = await db.market_listings.find_one_and_update(
        {"id": data.listing_id, "status": "active", "amount": {"$gte": data.amount}},
        {"$inc": {"amount": -data.amount}},
        return_document=ReturnDocument.AFTER,
    )
    if not _stock:
        raise HTTPException(status_code=409, detail="RESOURCE_UNAVAILABLE")

    # Обновляем баланс покупателя: сначала списываем бонусные средства, затем
    # реальные (заморозка учтена в pre-check выше). Так игрок может покупать
    # ресурсы за бонусный баланс.
    buyer_filter = {"email": buyer.get("email")} if buyer.get("email") else {"id": buyer_id}
    try:
        _mkt_upd = await debit_user_split(buyer_filter, total_cost)
    except Exception:
        # DB error while debiting: give the reserved units back before failing,
        # otherwise the seller's lot silently shrinks without a sale.
        await db.market_listings.update_one(
            {"id": data.listing_id},
            {"$inc": {"amount": data.amount}, "$set": {"status": "active"}},
        )
        raise
    if not _mkt_upd.get("ok"):
        # roll back the atomic stock claim so the units aren't lost
        await db.market_listings.update_one(
            {"id": data.listing_id},
            {"$inc": {"amount": data.amount}, "$set": {"status": "active"}},
        )
        raise await _insufficient_funds(buyer, total_cost)
    
    # Добавляем купленные ресурсы покупателю
    await db.users.update_one(
        buyer_filter,
        {"$inc": {f"resources.{listing['resource_type']}": data.amount}}
    )
    
    # Обновляем баланс продавца.
    # Revenue routing: обычно на реальный balance_ton. НО если у продавца нет
    # бизнесов вообще ИЛИ есть бизнес 0 уровня — зачисляем на bonus_balance.
    import zero_business as _zb
    _seller_ids = {listing.get("seller_id"), listing.get("seller_user_id"), listing.get("seller_email"), listing.get("seller_wallet")}
    _seller_field = "bonus_balance" if await _zb.should_credit_bonus(db, _seller_ids) else "balance_ton"
    await db.users.update_one(
        seller_filter,
        {"$inc": {_seller_field: seller_receives, "total_income": seller_receives}}
    )

    # B2B partner yield commission (credit the seller's B2B partner, if any)
    try:
        from b2b_partners import credit_yield
        _sid = listing.get("seller_id") or listing.get("seller_user_id")
        if _sid:
            await credit_yield(db, _sid, seller_receives)
    except Exception as _e:
        logger.debug(f"b2b yield credit (resource sale) failed: {_e}")

    # === CREDIT REPAYMENT: withhold seller's configured % per active credit ===
    # Runs *after* the seller is credited so we work off the post-tax income.
    seller_id_for_credit = listing.get("seller_id") or listing.get("seller_user_id")
    credit_total_deducted, credit_details = await apply_credit_deduction(
        db,
        seller_id_for_credit,
        seller_receives,
        seller_wallet=listing.get("seller_wallet"),
        source="resource_sale",
        context={
            "listing_id": data.listing_id,
            "resource": listing.get("resource_type"),
            "sale_amount_units": data.amount,
            "sale_amount_ton": seller_receives,
        },
    )
    
    # === ALLIANCE: Tax Haven (10% of seller's TON income to patron) ===
    try:
        seller_user = await db.users.find_one(seller_filter, {"_id": 0, "id": 1, "balance_ton": 1})
        if seller_user:
            seller_uid = seller_user.get("id", "")
            # Check if seller's business has an active tax_haven contract
            seller_biz = await db.businesses.find_one({"id": listing.get("business_id")}, {"_id": 0})
            if seller_biz and seller_biz.get("contract_id"):
                active_contract = await db.contracts.find_one(
                    {"id": seller_biz["contract_id"], "status": "active", "type": "tax_haven"},
                    {"_id": 0}
                )
                if active_contract:
                    # Frozen tax rate (fix #8); fallback to 10% for legacy contracts
                    rate = float(active_contract.get("tax_rate", 0.10) or 0.10)
                    patron_share = round(seller_receives * rate, 6)
                    # Fix #9: cap to available balance so we never push seller below 0
                    available = float(seller_user.get("balance_ton", 0) or 0)
                    if patron_share > available:
                        patron_share = round(max(0.0, available), 6)
                    if patron_share > 0:
                        patron_id = active_contract.get("patron_id")
                        # Deduct from seller, add to patron
                        await db.users.update_one(seller_filter, {"$inc": {"balance_ton": -patron_share}})
                        await db.users.update_one(
                            {"$or": [{"id": patron_id}, {"wallet_address": patron_id}]},
                            {"$inc": {"balance_ton": patron_share}}
                        )
                        # Fix #6: keep patron-income stats consistent
                        await db.contracts.update_one(
                            {"id": active_contract["id"]},
                            {"$inc": {"total_patron_income": patron_share}}
                        )
                        # Tx-history: log both legs (vassal -> patron) so the contract
                        # cashflow shows up in /api/transactions for both parties.
                        try:
                            now_iso = datetime.now(timezone.utc).isoformat()
                            patron_username = active_contract.get("patron_username") or ""
                            seller_username = seller_user.get("username") or ""
                            base = {
                                "contract_id": active_contract["id"],
                                "contract_type": "tax_haven",
                                "contract_rate": rate,
                                "listing_id": listing.get("id"),
                                "resource_type": listing.get("resource_type"),
                                "amount_resource": data.amount,
                                "sale_total_ton": seller_receives,
                                "created_at": now_iso,
                            }
                            await db.transactions.insert_one({
                                **base,
                                "id": str(uuid.uuid4()),
                                "user_id": seller_uid,
                                "type": "contract_payment_out",
                                "tx_type": "contract_payment_out",
                                "amount_ton": -patron_share,
                                "counterparty_id": patron_id,
                                "counterparty_username": patron_username,
                                "description": f"Налоговая Гавань: −{round(patron_share*1000, 2)} $CITY → {patron_username or 'patron'}",
                            })
                            await db.transactions.insert_one({
                                **base,
                                "id": str(uuid.uuid4()),
                                "user_id": patron_id,
                                "type": "contract_payment_in",
                                "tx_type": "contract_payment_in",
                                "amount_ton": patron_share,
                                "counterparty_id": seller_uid,
                                "counterparty_username": seller_username,
                                "description": f"Налоговая Гавань: +{round(patron_share*1000, 2)} $CITY от {seller_username or 'vassal'}",
                            })
                        except Exception as _tx_e:
                            logger.warning(f"tax_haven tx-history insert failed: {_tx_e}")
    except Exception as e:
        logger.error(f"Tax haven processing error: {e}")
    
    # Обновляем листинг — количество уже списано атомарно выше (_stock).
    # Закрываем листинг, если он опустел, иначе пересчитываем total_price.
    if _stock.get("amount", 0) <= 0:
        await db.market_listings.update_one(
            {"id": data.listing_id},
            {"$set": {"status": "sold", "sold_at": datetime.now(timezone.utc).isoformat()}}
        )
    else:
        await db.market_listings.update_one(
            {"id": data.listing_id},
            {"$set": {"total_price": _stock["amount"] * listing["price_per_unit"]}}
        )
    
    # === REFERRAL SPLIT: divert 5% of the trade total to seller's referrer (if any) ===
    # Destination (real vs bonus balance) depends on the level of the seller's
    # SOURCE business (the one whose resource is sold) — see apply_referral_tax_split.
    _seller_ref_doc = await db.users.find_one(seller_filter, {"_id": 0, "id": 1, "referrerId": 1, "username": 1})
    admin_tax, referral_amount, referrer_id, ref_to_bonus = await apply_referral_tax_split(
        _seller_ref_doc, total_cost, seller_tax, listing.get("business_id"))
    if referral_amount > 0 and referrer_id:
        # Track how much this seller contributed to their referrer (for the list UI).
        await db.users.update_one(seller_filter, {"$inc": {"contributedToReferrer": referral_amount}})
        _bal_ru = "бонусный баланс" if ref_to_bonus else "реальный баланс"
        try:
            await db.transactions.insert_one({
                "id": str(uuid.uuid4()),
                "tx_type": "referral_income",
                "type": "referral_income",
                "user_id": referrer_id,
                "amount_ton": referral_amount,
                "to_balance": "bonus" if ref_to_bonus else "real",
                "counterparty_id": (_seller_ref_doc or {}).get("id"),
                "counterparty_username": (_seller_ref_doc or {}).get("username", ""),
                "description": f"Реферальный доход: +{round(referral_amount * 1000, 2)} $CITY от {(_seller_ref_doc or {}).get('username', '')} (на {_bal_ru})",
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as _re:
            logger.warning(f"referral tx insert failed: {_re}")

    # Налог в казну (за вычетом реферальной доли).
    # Также пишем в resource_sales_tax / resource_sales_count — именно эти поля
    # читает админ-аналитика ("Налоги с продажи ресурсов").
    await db.admin_stats.update_one(
        {"type": "treasury"},
        {"$inc": {
            "market_tax": admin_tax,
            "resource_sales_tax": admin_tax,
            "resource_sales_count": 1,
            "total_tax": admin_tax,
        }},
        upsert=True
    )
    
    # Записываем транзакцию (buyer_id/seller_id always set so history endpoint matches
    # both email- and wallet-authenticated users).
    seller_net_after_credit = round(seller_receives - credit_total_deducted, 6)
    tx = {
        "id": str(uuid.uuid4()),
        "tx_type": "market_purchase",
        "from_address": current_user.wallet_address or buyer_id,
        "to_address": listing["seller_id"],
        "buyer_id": buyer_id,
        "seller_id": listing["seller_id"],
        "amount_ton": total_cost,
        "tax": seller_tax,
        "credit_deducted": credit_total_deducted,  # auto-paid to active credits
        "seller_net_after_credit": seller_net_after_credit,
        "resource_type": listing["resource_type"],
        "resource_amount": data.amount,
        "listing_id": data.listing_id,
        "status": "completed",
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.transactions.insert_one(tx)
    
    logger.info(f"Market purchase: {data.amount} {listing['resource_type']} for {total_cost} TON")
    # Daily activity: buyer bought units (seller is credited at listing time).
    await bump_daily_trade(buyer_id, bought=data.amount)
    quest_engine.fire_sale(listing.get("seller_id"), buyer_id, data.amount, ton=total_cost)
    if listing.get("seller_id") == market_maker.CITY_MARKET_ID:
        try:
            await market_maker.on_player_bought(db, listing, data.amount, total_cost, buyer_id)
        except Exception as _mm_e:
            logger.warning(f"city market sell bookkeeping failed: {_mm_e}")
    
    # Partner task tracking: a P2P market purchase may complete partner conditions.
    try:
        from routes.partner_programs import check_partner_conditions
        await check_partner_conditions(db, buyer_id)
    except Exception as _e:
        logger.debug(f"check_partner_conditions (market purchase) failed: {_e}")
    
    # Notify seller (a buyer just took their resources)
    try:
        from core.notify import notify_user
        from business_config import RESOURCE_TYPES as _RES_CFG
        seller_doc = await find_user(db, listing.get("seller_id"))
        if seller_doc:
            seller_lang = (seller_doc.get("language") or "en").lower()
            if seller_lang not in ("ru", "en"):
                seller_lang = "en"
            res_key = listing["resource_type"]
            res_cfg = _RES_CFG.get(res_key, {})
            res_name = res_cfg.get(f"name_{seller_lang}") or res_cfg.get("name_en") or res_key

            ton_received = seller_net_after_credit
            city_received = round(ton_received * 1000, 2)
            credit_city = round(credit_total_deducted * 1000, 2)

            # Title (i18n)
            title_map = {
                "ru": "Ресурсы проданы на маркете",
                "en": "Resources sold on the market",
            }
            # Body
            if seller_lang == "ru":
                if credit_total_deducted > 0:
                    msg = (
                        f"Покупатель купил {data.amount} ед. «{res_name}» за {total_cost:.4f} TON ({round(total_cost*1000,2)} $CITY).\n"
                        f"После налога и удержания по кредиту вам начислено: "
                        f"{ton_received:.4f} TON ({city_received} $CITY).\n"
                        f"На погашение кредита направлено: {credit_total_deducted:.4f} TON ({credit_city} $CITY)."
                    )
                else:
                    msg = (
                        f"Покупатель купил {data.amount} ед. «{res_name}» за {total_cost:.4f} TON ({round(total_cost*1000,2)} $CITY).\n"
                        f"Вам начислено после налога: {ton_received:.4f} TON ({city_received} $CITY)."
                    )
            else:
                if credit_total_deducted > 0:
                    msg = (
                        f"A buyer purchased {data.amount} × {res_name} for {total_cost:.4f} TON ({round(total_cost*1000,2)} $CITY).\n"
                        f"You received after tax and credit deduction: "
                        f"{ton_received:.4f} TON ({city_received} $CITY).\n"
                        f"Auto-paid to your credit: {credit_total_deducted:.4f} TON ({credit_city} $CITY)."
                    )
                else:
                    msg = (
                        f"A buyer purchased {data.amount} × {res_name} for {total_cost:.4f} TON ({round(total_cost*1000,2)} $CITY).\n"
                        f"You received after tax: {ton_received:.4f} TON ({city_received} $CITY)."
                    )
            await notify_user(
                db, seller_doc,
                title=title_map.get(seller_lang, title_map["en"]),
                message=msg,
                type_key="market_sold",
                priority="success",
                payload={
                    "resource_type": res_key,
                    "resource_name": res_name,
                    "amount": data.amount,
                    "received_ton": ton_received,
                    "received_city": city_received,
                    "credit_deducted_ton": credit_total_deducted,
                    "credit_deducted_city": credit_city,
                    "gross_ton": total_cost,
                    "tax_ton": seller_tax,
                },
            )
    except Exception as _e:
        logger.warning(f"market_purchase seller-notify failed: {_e}")
    
    # Get updated buyer balance
    updated_buyer = await db.users.find_one(buyer_filter, {"_id": 0, "balance_ton": 1, "bonus_balance": 1})
    
    return {
        "status": "purchased",
        "paid_from_bonus": _mkt_upd.get("from_bonus", 0.0),
        "paid_from_real": _mkt_upd.get("from_real", 0.0),
        "new_bonus_balance": (updated_buyer or {}).get("bonus_balance", 0),
        "amount": data.amount,
        "resource_type": listing["resource_type"],
        "total_paid": total_cost,
        "seller_received": seller_receives,
        "seller_net_after_credit": round(seller_receives - credit_total_deducted, 6),
        "credit_deducted": credit_total_deducted,
        "credit_details": credit_details,
        "tax": seller_tax,
        "new_balance": updated_buyer.get("balance_ton", 0) if updated_buyer else None
    }

@api_router.delete("/market/listing/{listing_id}")
async def cancel_market_listing(listing_id: str, current_user: User = Depends(get_current_user)):
    """Отменить свой листинг и вернуть ресурсы"""
    listing = await db.market_listings.find_one({"id": listing_id, "status": "active"}, {"_id": 0})
    
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    
    # Get user from database (support both wallet and email auth)
    user = None
    if current_user.wallet_address:
        user = await db.users.find_one({"id": current_user.id}, {"_id": 0})
    if not user and current_user.email:
        user = await db.users.find_one({"id": current_user.id}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    user_id = user.get("id", str(user.get("_id")))
    
    # Check ownership
    if listing.get("seller_id") != user_id and listing.get("seller_email") != user.get("email"):
        raise HTTPException(status_code=403, detail="Not your listing")
    
    # Return resources to user's global resources (listings from /market/list-resource deduct from user.resources)
    resource_type = listing.get("resource_type")
    amount = listing.get("amount", 0)
    if resource_type and amount > 0:
        await db.users.update_one(
            get_user_filter(user),
            {"$inc": {f"resources.{resource_type}": amount}}
        )
    
    await db.market_listings.update_one(
        {"id": listing_id},
        {"$set": {"status": "cancelled", "cancelled_at": datetime.now(timezone.utc).isoformat()}}
    )
    
    return {"status": "cancelled", "listing_id": listing_id}

@api_router.get("/market/my-listings")
async def get_my_listings(current_user: User = Depends(get_current_user)):
    """Получить свои листинги + лимит слотов (для UI)."""
    # Search by user_id or email
    user = None
    if current_user.wallet_address:
        user = await db.users.find_one({"id": current_user.id}, {"_id": 0})
    if not user and current_user.email:
        user = await db.users.find_one({"id": current_user.id}, {"_id": 0})
    
    if not user:
        return {"listings": [], "slot_info": {"used": 0, "max": 0, "business_count": 0, "trade_attache_bonus": 0}}
    
    user_id = user.get("id", str(user.get("_id")))
    
    listings = await db.market_listings.find(
        {"$or": nz_or([{"seller_id": user_id}, {"seller_id": owner_key(current_user)}, {"seller_email": user.get("email")}]), "status": "active"},
        {"_id": 0}
    ).sort("created_at", -1).to_list(50)
    await _enrich_seller_usernames(listings)

    # Slot calculation matches /market/list-resource enforcement.
    # v2.2: tutorial-flagged businesses do NOT count toward the slot limit —
    # they are fake placeholders created via /api/tutorial/fake-buy-plot. A
    # user with 0 real businesses must see "0/0" slots (not "0/1") unless they
    # are currently on the tutorial `create_lot` step, in which case we grant
    # exactly one slot so the tutorial flow works.
    _list_owner_keys = await resolve_owner_keys(db, user_id)
    user_businesses = await db.businesses.find(
        owner_businesses_query(_list_owner_keys),
        {"_id": 0, "id": 1, "patron_id": 1, "contract_id": 1, "contract_buff": 1, "tutorial": 1},
    ).to_list(100)
    real_businesses = [b for b in user_businesses if not b.get("tutorial")]
    business_count = len(real_businesses)
    trade_attache_bonus = 0
    for biz in real_businesses:
        contract_doc = None
        if biz.get("contract_id"):
            contract_doc = await db.contracts.find_one(
                {"id": biz["contract_id"], "status": "active"}, {"_id": 0}
            )
        patron_doc = None
        if biz.get("patron_id"):
            patron_doc = await db.businesses.find_one({"id": biz["patron_id"]}, {"_id": 0})
        buff = resolve_business_buff(biz, contract_doc, patron_doc)
        if buff and buff.get("id") == "trade_attache":
            trade_attache_bonus += 1
    max_listings = business_count + trade_attache_bonus
    # Tutorial override: while on `create_lot` step, force max to at least 1.
    if user.get("tutorial_active") and user.get("tutorial_current_step") == "create_lot":
        max_listings = max(1, max_listings)
    # No-business players get exactly 1 selling slot (sell from personal warehouse).
    if max_listings < 1:
        max_listings = 1

    return {
        "listings": listings,
        "slot_info": {
            "used": len(listings),
            "max": max_listings,
            "business_count": business_count,
            "trade_attache_bonus": trade_attache_bonus,
        },
    }


@api_router.get("/tier3/buffs")
async def get_tier3_buffs():
    """Get list of all available Tier 3 patron buffs"""
    return {"buffs": list(TIER3_BUFFS.values())}


@api_router.post("/business/{business_id}/set-buff")
async def set_business_buff(business_id: str, request: Request, current_user: User = Depends(get_current_user)):
    """Select a buff for a Tier 3 business to grant to vassals"""
    data = await request.json()
    ui = await get_user_identifiers(current_user)
    business = await db.businesses.find_one({"id": business_id}, {"_id": 0})
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")
    
    # Verify ownership
    if business.get("owner") not in ui["ids"]:
        raise HTTPException(status_code=403, detail="Not your business")
    
    # Verify Tier 3
    biz_config = BUSINESSES.get(business.get("business_type"), {})
    if biz_config.get("tier", 1) != 3:
        raise HTTPException(status_code=400, detail="Only Tier 3 businesses can grant buffs")
    
    buff_id = data.get("buff_id")
    if buff_id not in TIER3_BUFFS:
        raise HTTPException(status_code=400, detail="Invalid buff ID")
    
    await db.businesses.update_one(
        {"id": business_id},
        {"$set": {"patron_buff": buff_id}}
    )
    
    # Notify all vassals (and the patron itself) so the UI auto-refreshes
    # without needing the «обновить информацию» button. We push via WebSocket
    # to the patron owner + every vassal owner; clients handle the message
    # by reloading their `/api/my/businesses` view.
    try:
        buff_data = TIER3_BUFFS[buff_id]
        # Patron owner — refresh so the chosen buff card updates instantly
        patron_owner = business.get("owner")
        recipients = set()
        if patron_owner:
            recipients.add(patron_owner)
        # Find all vassals (any business with this patron_id) — broadcast to their owners
        async for v in db.businesses.find({"patron_id": business_id}, {"_id": 0, "owner": 1}):
            if v.get("owner"):
                recipients.add(v["owner"])
        msg = {
            "type": "patron_buff_changed",
            "patron_business_id": business_id,
            "buff": {
                "id": buff_data.get("id"),
                "name": buff_data.get("name"),
                "icon": buff_data.get("icon"),
                "description": buff_data.get("description"),
                "effect": buff_data.get("effect"),
            },
        }
        for uid in recipients:
            try:
                await manager.send_personal(msg, uid)
            except Exception:
                pass
        # Persistent notification for vassal owners (so they see something
        # even if WS is offline at the moment)
        async for v in db.businesses.find({"patron_id": business_id}, {"_id": 0, "owner": 1}):
            uid = v.get("owner")
            if not uid or uid == patron_owner:
                continue
            try:
                from core.notify import notify_user as _nu_pb
                _buff_txt = f"{buff_data.get('icon','')} {buff_data.get('name','')} — {buff_data.get('description','')}"
                await _nu_pb(db, uid, title="Патрон обновил бафф", message=_buff_txt,
                             type_key="patron_buff_update", priority="info",
                             i18n_key="patron_buff_update", i18n_vars={"buff": _buff_txt})
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"patron_buff_changed broadcast error: {e}")
    
    return {"success": True, "buff": TIER3_BUFFS[buff_id]}


@api_router.get("/business/{business_id}/vassals")
async def get_business_vassals(business_id: str, current_user: User = Depends(get_current_user)):
    """Get list of vassals for a Tier 3 patron business"""
    ui = await get_user_identifiers(current_user)
    business = await db.businesses.find_one({"id": business_id}, {"_id": 0})
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")
    if business.get("owner") not in ui["ids"]:
        raise HTTPException(status_code=403, detail="Not your business")
    
    # Find all businesses with this patron
    vassal_businesses = await db.businesses.find(
        {"patron_id": business_id}, {"_id": 0}
    ).to_list(100)
    
    # Group by owner
    owner_ids = list(set(b["owner"] for b in vassal_businesses))
    users = await db.users.find(
        {"$or": [{"id": {"$in": owner_ids}}, {"wallet_address": {"$in": owner_ids}}]},
        {"_id": 0, "id": 1, "username": 1, "avatar": 1, "wallet_address": 1}
    ).to_list(100)
    users_map = {u.get("id", u.get("wallet_address")): u for u in users}
    
    result = []
    for b in vassal_businesses:
        owner = users_map.get(b["owner"], {})
        biz_config = BUSINESSES.get(b.get("business_type"), {})
        result.append({
            "business_id": b["id"],
            "business_type": b.get("business_type"),
            "business_name": biz_config.get("name", {}),
            "business_icon": biz_config.get("icon", "🏢"),
            "business_tier": biz_config.get("tier", 1),
            "owner_id": b["owner"],
            "owner_username": owner.get("username", "Unknown"),
            "owner_avatar": owner.get("avatar"),
        })
    
    return {"vassals": result, "count": len(result)}


# ==================== CONTRACT SYSTEM V2: ALLIANCES ====================

class ContractProposal(BaseModel):
    type: str          # "tax_haven" | "raw_material" | "tech_umbrella"
    vassal_business_id: str
    patron_buff: str   # buff key from TIER3_BUFFS
    duration_days: int = 30  # V2: contract duration
    auto_renew: bool = False  # V2: auto-renewal option


CONTRACT_TYPES = {
    "tax_haven": {
        "name_ru": "Налоговая Гавань",
        "name_en": "Tax Haven",
        "description_ru": "Вассал платит 10% с каждой продажи ресурсов на маркетплейсе.",
        "vassal_benefit": "Выбранный Патроном баф",
        "patron_benefit": "10% от выручки вассала при продаже",
        "icon": "🏝️",
        "color": "#f59e0b",
        "penalty_city": 500,
        # Frozen on offer/contract (fix #8): vassal pays this share of each TON sale
        "tax_rate": 0.10,
    },
    "raw_material": {
        "name_ru": "Сырьевой Придаток",
        "name_en": "Raw Material",
        "description_ru": "Вассал отдаёт 15% произведённых товаров Патрону.",
        "vassal_benefit": "Выбранный Патроном баф",
        "patron_benefit": "15% ресурсов вассала",
        "icon": "⚙️",
        "color": "#3b82f6",
        "penalty_city": 750,
        "material_share": 0.15,
    },
    "tech_umbrella": {
        "name_ru": "Технологический Зонтик",
        "name_en": "Tech Umbrella",
        "description_ru": "Вассал тратит на 30% меньше ремонтных комплектов.",
        "vassal_benefit": "-30% стоимость ремонта + баф Патрона",
        "patron_benefit": "Фиксированная рента 100 $CITY/день",
        "icon": "🛡️",
        "color": "#22c55e",
        "penalty_city": 300,
        "daily_rent_city": 100,
    },
    "resource_supply": {
        "name_ru": "Поставка ресурсов",
        "name_en": "Resource Supply",
        "description_ru": "Продавец обязуется поставлять ресурсы покупателю ежедневно по фиксированной цене.",
        "vassal_benefit": "Гарантированные поставки ресурсов по сниженной цене",
        "patron_benefit": "Стабильный покупатель и гарантированный доход",
        "icon": "📦",
        "color": "#8b5cf6",
        "penalty_city": 200,
    },
}


class ResourceContractCreate(BaseModel):
    """Contract that any user can create - resource supply"""
    resource_type: str
    amount_per_day: float
    price_per_10: float  # Price per 10 units
    duration_days: int = 30
    business_id: str  # Seller's business that produces the resource


@api_router.post("/contracts/create-supply")
async def create_supply_contract(data: ResourceContractCreate, current_user: User = Depends(get_current_user)):
    """Any user can create a resource supply contract (open for anyone to accept)"""
    ui = await get_user_identifiers(current_user)
    if not ui["user"]:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    user = ui["user"]
    
    if data.amount_per_day <= 0 or data.price_per_10 <= 0:
        raise HTTPException(status_code=400, detail="Некорректные параметры контракта")
    if data.duration_days < 7 or data.duration_days > 90:
        raise HTTPException(status_code=400, detail="Длительность: от 7 до 90 дней")
    
    # Verify business ownership
    business = await db.businesses.find_one({"id": data.business_id}, {"_id": 0})
    if not business or business.get("owner") not in ui["ids"]:
        raise HTTPException(status_code=403, detail="Бизнес не найден или не ваш")
    
    biz_cfg = resolve_business_config(business.get("business_type", ""))
    produces = biz_cfg.get("produces", "")
    if produces != data.resource_type:
        raise HTTPException(status_code=400, detail=f"Этот бизнес производит {translate_resource_name(produces)}, а не {translate_resource_name(data.resource_type)}")
    
    user_id = user.get("id", "")
    daily_income = data.amount_per_day * data.price_per_10 / 10
    
    contract = {
        "id": str(uuid.uuid4()),
        "type": "resource_supply",
        "seller_id": user_id,
        "seller_username": user.get("username"),
        "seller_business_id": data.business_id,
        "seller_business_type": business.get("business_type"),
        "resource_type": data.resource_type,
        "resource_name": translate_resource_name(data.resource_type),
        "amount_per_day": data.amount_per_day,
        "price_per_10": data.price_per_10,
        "daily_income_city": round(daily_income, 2),
        "duration_days": data.duration_days,
        "buyer_id": None,
        "buyer_username": None,
        "buyer_business_id": None,
        "status": "open",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "accepted_at": None,
        "expires_at": None,
    }
    
    await db.supply_contracts.insert_one(contract.copy())
    return {"success": True, "contract_id": contract["id"], "message": f"Контракт создан: {int(data.amount_per_day)} {translate_resource_name(data.resource_type)}/день"}


@api_router.get("/contracts/supply-market")
async def get_supply_market(current_user: User = Depends(get_current_user)):
    """Get all open supply contracts (marketplace for resource contracts)"""
    contracts = await db.supply_contracts.find(
        {"status": "open"},
        {"_id": 0}
    ).sort("created_at", -1).to_list(50)
    
    # Enrich with business info
    for c in contracts:
        biz = await db.businesses.find_one({"id": c.get("seller_business_id")}, {"_id": 0, "business_type": 1})
        biz_cfg = BUSINESSES.get((biz or {}).get("business_type", ""), {})
        c["seller_business_name"] = biz_cfg.get("name", {}).get("ru", "?")
        c["seller_business_icon"] = biz_cfg.get("icon", "📦")
        c["resource_icon"] = RESOURCE_NAMES.get(c.get("resource_type", ""), c.get("resource_type", ""))
    
    return {"contracts": contracts}


@api_router.post("/contracts/supply/{contract_id}/accept")
async def accept_supply_contract(contract_id: str, buyer_business_id: str = None, current_user: User = Depends(get_current_user)):
    """Accept a resource supply contract as buyer"""
    ui = await get_user_identifiers(current_user)
    if not ui["user"]:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    user = ui["user"]
    
    contract = await db.supply_contracts.find_one({"id": contract_id, "status": "open"}, {"_id": 0})
    if not contract:
        raise HTTPException(status_code=404, detail="Контракт не найден или уже принят")
    
    user_id = user.get("id", "")
    if contract["seller_id"] == user_id:
        raise HTTPException(status_code=400, detail="Нельзя принять свой контракт")
    
    now = datetime.now(timezone.utc)
    duration = contract.get("duration_days", 30)
    
    await db.supply_contracts.update_one(
        {"id": contract_id},
        {"$set": {
            "buyer_id": user_id,
            "buyer_username": user.get("username"),
            "buyer_business_id": buyer_business_id,
            "status": "active",
            "accepted_at": now.isoformat(),
            "expires_at": (now + timedelta(days=duration)).isoformat(),
        }}
    )
    
    # Notification for seller
    notif = {
        "id": str(uuid.uuid4()),
        "user_id": contract["seller_id"],
        "type": "supply_contract_accepted",
        "title": f"📦 Контракт принят: {contract.get('resource_name', '')}",
        "message": (
            f"{user.get('username', '?')} принял ваш контракт на поставку.\n"
            f"Ресурс: {contract.get('resource_name', '')} — {int(contract.get('amount_per_day', 0))} ед./день\n"
            f"Цена: {contract.get('price_per_10', 0)} $CITY за 10 ед.\n"
            f"Ваш доход: ~{contract.get('daily_income_city', 0)} $CITY/день\n"
            f"Срок: {duration} дней"
        ),
        "contract_id": contract_id,
        "read": False,
        "created_at": now.isoformat(),
    }
    try:
        from core.notify import notify_user as _nu_generic
        await _nu_generic(db, notif.get("user_id"), title=notif.get("title", ""), message=notif.get("message", ""),
                          type_key=notif.get("type", "system"), priority=notif.get("priority", "info"),
                          payload={k: v for k, v in notif.items() if k not in ("id", "user_id", "title", "message", "type", "priority", "read", "created_at")})
    except Exception as _e:
        logger.warning(f"notify failed: {_e}")
    
    return {"success": True, "message": f"Контракт принят! Поставки начнутся автоматически."}


@api_router.post("/contracts/supply/{contract_id}/cancel")
async def cancel_supply_contract(contract_id: str, current_user: User = Depends(get_current_user)):
    """Cancel own supply contract"""
    ui = await get_user_identifiers(current_user)
    if not ui["user"]:
        raise HTTPException(status_code=401)
    
    contract = await db.supply_contracts.find_one({"id": contract_id}, {"_id": 0})
    if not contract:
        raise HTTPException(status_code=404, detail="Контракт не найден")
    
    user_id = ui["user"].get("id", "")
    is_seller = contract["seller_id"] == user_id
    is_buyer = contract.get("buyer_id") == user_id
    
    if not is_seller and not is_buyer:
        raise HTTPException(status_code=403, detail="Это не ваш контракт")
    
    if contract["status"] == "open" and is_seller:
        await db.supply_contracts.update_one({"id": contract_id}, {"$set": {"status": "cancelled"}})
        return {"success": True, "message": "Контракт отменён"}
    
    if contract["status"] == "active":
        await db.supply_contracts.update_one(
            {"id": contract_id},
            {"$set": {"status": "cancelled", "cancelled_at": datetime.now(timezone.utc).isoformat()}}
        )
        return {"success": True, "message": "Контракт расторгнут"}
    
    raise HTTPException(status_code=400, detail="Контракт нельзя отменить в текущем статусе")


@api_router.get("/contracts/types")
async def get_contract_types():
    """Get available contract types"""
    return {"types": [{"id": k, **v} for k, v in CONTRACT_TYPES.items()]}


# === PATRON OFFER SYSTEM (Alliance Offers) ===

class PatronOfferCreate(BaseModel):
    buff_id: str          # from TIER3_BUFFS
    contract_type: str    # "tax_haven" | "raw_material" | "tech_umbrella"
    duration_days: int = 30


@api_router.post("/alliances/publish-offer")
async def publish_patron_offer(data: PatronOfferCreate, current_user: User = Depends(get_current_user)):
    """Patron publishes a public offer for vassals to browse and accept"""
    ui = await get_user_identifiers(current_user)
    if not ui["user"]:
        raise HTTPException(status_code=401)
    
    if data.buff_id not in TIER3_BUFFS:
        raise HTTPException(status_code=400, detail="Неверный баф")
    if data.contract_type not in CONTRACT_TYPES:
        raise HTTPException(status_code=400, detail="Неверный тип контракта")
    if data.duration_days < 7 or data.duration_days > 90:
        raise HTTPException(status_code=400, detail="Длительность: от 7 до 90 дней")
    
    # Find patron's Tier 3 business
    patron_biz = None
    all_bizs = await db.businesses.find({"owner": {"$in": list(ui["ids"])}}, {"_id": 0}).to_list(100)
    for b in all_bizs:
        bc = BUSINESSES.get(b.get("business_type", ""), {})
        if bc.get("tier", 1) == 3:
            patron_biz = b
            break
    if not patron_biz:
        raise HTTPException(status_code=403, detail="Нужен бизнес Эшелона 3")
    
    # V4: Limit 5 published offers + reject if patron's specific T3 business already at 25 active contracts
    active_offers_count = await db.alliance_offers.count_documents(
        {"patron_business_id": patron_biz["id"], "status": "open"}
    )
    if active_offers_count >= 5:
        raise HTTPException(status_code=400, detail="Лимит: 5 опубликованных офферов. Отмените старые, чтобы создать новые.")
    active_alliances_as_patron = await db.contracts.count_documents({
        "patron_business_id": patron_biz["id"], "status": {"$in": ["active", "proposed"]}
    })
    if active_alliances_as_patron >= 25:
        raise HTTPException(status_code=400, detail="У этого T3-бизнеса уже 25 активных альянсов — расторгните или дождитесь окончания одного, чтобы публиковать новые офферы.")
    
    patron_biz_cfg = BUSINESSES.get(patron_biz.get("business_type", ""), {})
    buff_info = TIER3_BUFFS[data.buff_id]
    ct_info = CONTRACT_TYPES[data.contract_type]
    user = ui["user"]
    
    offer = {
        "id": str(uuid.uuid4()),
        "patron_id": ui["primary_id"],
        "patron_username": user.get("username"),
        "patron_business_id": patron_biz["id"],
        "patron_business_type": patron_biz.get("business_type"),
        "patron_business_name": patron_biz_cfg.get("name", {}).get("ru", "?"),
        "patron_business_icon": patron_biz_cfg.get("icon", "🏢"),
        "patron_level": patron_biz.get("level", 1),
        "buff_id": data.buff_id,
        "buff_name": buff_info.get("name", ""),
        "buff_icon": buff_info.get("icon", ""),
        "buff_description": buff_info.get("description", ""),
        "contract_type": data.contract_type,
        "contract_type_name": ct_info.get("name_ru", ""),
        "contract_type_icon": ct_info.get("icon", ""),
        "vassal_pays": ct_info.get("patron_benefit", ""),
        "cancel_fee_city": data.duration_days * 100,
        "duration_days": data.duration_days,
        # Frozen-at-publish rates (fix #8): used by execution engine, immune to config drift
        "tax_rate": float(ct_info.get("tax_rate", 0)),
        "material_share": float(ct_info.get("material_share", 0)),
        "daily_rent_city": float(ct_info.get("daily_rent_city", 0)),
        "status": "open",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    
    await db.alliance_offers.insert_one(offer.copy())
    return {"success": True, "offer_id": offer["id"], "message": "Оффер опубликован!"}


@api_router.post("/alliances/accept/{offer_id}")
async def accept_alliance_offer(offer_id: str, vassal_business_id: str = None, current_user: User = Depends(get_current_user)):
    """Vassal accepts a patron's public offer → creates active contract + sets patron"""
    ui = await get_user_identifiers(current_user)
    if not ui["user"]:
        raise HTTPException(status_code=401)
    
    offer = await db.alliance_offers.find_one({"id": offer_id, "status": "open"}, {"_id": 0})
    if not offer:
        raise HTTPException(status_code=404, detail="Оффер не найден или уже принят")
    
    vassal_id = ui["primary_id"]
    if offer["patron_id"] == vassal_id:
        raise HTTPException(status_code=400, detail="Нельзя принять свой оффер")
    
    # Find vassal's business
    user_businesses = await db.businesses.find({"owner": {"$in": list(ui["ids"])}}, {"_id": 0}).to_list(50)
    if not user_businesses:
        raise HTTPException(status_code=404, detail="У вас нет бизнеса")

    if vassal_business_id:
        vassal_biz = next((b for b in user_businesses if b.get("id") == vassal_business_id), None)
        if not vassal_biz:
            raise HTTPException(status_code=404, detail="Бизнес не найден")
    elif len(user_businesses) == 1:
        vassal_biz = user_businesses[0]
    else:
        raise HTTPException(
            status_code=400,
            detail="У вас несколько бизнесов — выберите, какой будет работать по этому офферу.",
        )
    
    # V3: Prevent self-contract (own businesses)
    patron_owner = None
    patron_biz_doc = await db.businesses.find_one({"id": offer.get("patron_business_id")}, {"_id": 0, "owner": 1})
    if patron_biz_doc:
        patron_owner = patron_biz_doc.get("owner")
    if patron_owner and patron_owner in ui["ids"]:
        raise HTTPException(status_code=400, detail="Нельзя заключить контракт со своим бизнесом")
    
    # V5: Per-vassal-business limit:
    #   • Non-T3 business: max 1 active alliance contract.
    #   • T3 business as vassal: no limit (it has its own role as patron with 25-cap).
    vassal_biz_cfg_check = BUSINESSES.get(vassal_biz.get("business_type", ""), {})
    if vassal_biz_cfg_check.get("tier", 1) != 3:
        _active_count = await db.contracts.count_documents({
            "vassal_business_id": vassal_biz["id"],
            "status": {"$in": ["active", "proposed"]},
        })
        if _active_count >= 1:
            raise HTTPException(
                status_code=400,
                detail="Лимит: один бизнес (не Эшелон 3) может состоять только в одном альянсе одновременно."
            )
    
    # V4: Patron must have <25 active alliances (as patron of this specific T3 business). Beyond that, offers are paused.
    patron_active_alliances = await db.contracts.count_documents({
        "patron_business_id": offer["patron_business_id"], "status": {"$in": ["active", "proposed"]}
    })
    if patron_active_alliances >= 25:
        raise HTTPException(status_code=400, detail="У этого T3-бизнеса уже 25 активных альянсов — оффер временно недоступен.")

    # V4: Check duplicate — same patron + vassal pair already in active contract
    dup = await db.contracts.find_one({
        "patron_id": offer["patron_id"],
        "vassal_id": vassal_id,
        "vassal_business_id": vassal_biz["id"],
        "status": {"$in": ["active", "proposed"]},
    })
    if dup:
        raise HTTPException(status_code=400, detail="Вы уже состоите в активном альянсе с этим патроном по этому бизнесу.")

    vassal_biz_cfg = BUSINESSES.get(vassal_biz.get("business_type", ""), {})
    now = datetime.now(timezone.utc)
    duration = offer.get("duration_days", 30)

    # V4: Decide if vassal becomes a "real vassal" (patron_id linkage) or just gets the buff.
    # Vassal joins under patron only if BOTH conditions hold:
    #  (a) vassal's business has no current patron_id, AND
    #  (b) patron has fewer than 25 vassals (count of businesses with patron_id == patron's t3 business)
    patron_business_id = offer["patron_business_id"]
    current_patron_id = vassal_biz.get("patron_id")
    patron_vassals_count = await db.businesses.count_documents({"patron_id": patron_business_id})
    will_set_patron = (not current_patron_id) and (patron_vassals_count < 25)

    # Create active contract
    contract = {
        "id": str(uuid.uuid4()),
        "type": offer["contract_type"],
        "patron_id": offer["patron_id"],
        "vassal_id": vassal_id,
        "patron_business_id": offer["patron_business_id"],
        "vassal_business_id": vassal_biz["id"],
        "patron_buff": offer["buff_id"],
        "status": "active",
        "duration_days": duration,
        "auto_renew": False,
        "days_elapsed": 0,
        "proposed_at": offer.get("created_at"),
        "accepted_at": now.isoformat(),
        "expires_at": (now + timedelta(days=duration)).isoformat(),
        "cancelled_at": None,
        "cancelled_by": None,
        "violation_days": [],
        "penalty_paid": False,
        "total_patron_income": 0,
        "total_vassal_savings": 0,
        "patron_linkage": will_set_patron,  # marker so we know to clear patron_id on cancel
        "from_offer_id": offer_id,
        # Frozen rates copied from offer (fix #8) so config drift can't change live contracts
        "tax_rate": float(offer.get("tax_rate", CONTRACT_TYPES.get(offer["contract_type"], {}).get("tax_rate", 0))),
        "material_share": float(offer.get("material_share", CONTRACT_TYPES.get(offer["contract_type"], {}).get("material_share", 0))),
        "daily_rent_city": float(offer.get("daily_rent_city", CONTRACT_TYPES.get(offer["contract_type"], {}).get("daily_rent_city", 0))),
    }
    await db.contracts.insert_one(contract.copy())

    # Apply buff (always) and patron_id (only if will_set_patron). Stamp last_patron_change
    # so the 7-day cooldown protects the freshly-set patron until then.
    biz_update = {
        "contract_id": contract["id"],
        "contract_buff": offer["buff_id"],
    }
    if will_set_patron:
        biz_update["patron_id"] = patron_business_id
        biz_update["last_patron_change"] = now.isoformat()
    await db.businesses.update_one({"id": vassal_biz["id"]}, {"$set": biz_update})

    # V4: Track acceptances on offer but DO NOT close it — offer stays "open" so other vassals can also accept.
    await db.alliance_offers.update_one(
        {"id": offer_id},
        {
            "$inc": {"acceptances_count": 1},
            "$push": {"acceptances": {"vassal_id": vassal_id, "vassal_business_id": vassal_biz["id"], "accepted_at": now.isoformat()}},
        },
    )

    # V4: If patron-business now hit 25 active alliances, auto-pause its open offers
    new_alliance_count = patron_active_alliances + 1
    if new_alliance_count >= 25:
        await db.alliance_offers.update_many(
            {"patron_business_id": offer["patron_business_id"], "status": "open"},
            {"$set": {"status": "paused", "paused_reason": "limit_25_alliances", "paused_at": now.isoformat()}},
        )
        # Fix #10: notify patron about auto-pause
        try:
            await send_alliance_notification(
                db, offer["patron_id"], "offers_paused_limit", {},
                extra_fields={"patron_business_id": offer["patron_business_id"]},
            )
        except Exception as _e:
            logger.warning(f"offers_paused_limit notif failed: {_e}")
    
    # Notification for patron
    ct_info = CONTRACT_TYPES.get(offer["contract_type"], {})
    notif = {
        "id": str(uuid.uuid4()),
        "user_id": offer["patron_id"],
        "type": "alliance_accepted",
        "title": f"Альянс принят: {ct_info.get('icon', '')} {ct_info.get('name_ru', '')}",
        "message": (
            f"{ui['user'].get('username', '?')} вступил в альянс.\n"
            f"Бизнес: {vassal_biz_cfg.get('icon', '')} {vassal_biz_cfg.get('name', {}).get('ru', '')}\n"
            f"Вы получаете: {ct_info.get('patron_benefit', '')}\n"
            f"Срок: {duration} дней"
        ),
        "contract_id": contract["id"],
        "read": False,
        "created_at": now.isoformat(),
    }
    try:
        from core.notify import notify_user as _nu_generic
        await _nu_generic(db, notif.get("user_id"), title=notif.get("title", ""), message=notif.get("message", ""),
                          type_key=notif.get("type", "system"), priority=notif.get("priority", "info"),
                          payload={k: v for k, v in notif.items() if k not in ("id", "user_id", "title", "message", "type", "priority", "read", "created_at")})
    except Exception as _e:
        logger.warning(f"notify failed: {_e}")
    
    return {"success": True, "message": f"Альянс заключён! Покровительство и баф активированы."}


@api_router.get("/contracts/my")
async def get_patron_contracts(current_user: User = Depends(get_current_user)):
    """Get all contracts for current user (as patron and vassal)"""
    ui = await get_user_identifiers(current_user)
    user_ids = list(ui["ids"])
    hidden = set((ui.get("user") or {}).get("hidden_contracts", []))

    contracts_as_patron = await db.contracts.find(
        {"patron_id": {"$in": user_ids}}, {"_id": 0}
    ).to_list(100)

    contracts_as_vassal = await db.contracts.find(
        {"vassal_id": {"$in": user_ids}}, {"_id": 0}
    ).to_list(100)
    
    # Filter hidden
    contracts_as_patron = [c for c in contracts_as_patron if c.get("id") not in hidden]
    contracts_as_vassal = [c for c in contracts_as_vassal if c.get("id") not in hidden]

    async def enrich(contracts):
        result = []
        now = datetime.now(timezone.utc)
        for c in contracts:
            pbiz = await db.businesses.find_one({"id": c.get("patron_business_id")}, {"_id": 0, "business_type": 1})
            vbiz = await db.businesses.find_one({"id": c.get("vassal_business_id")}, {"_id": 0, "business_type": 1})
            pu = await db.users.find_one({"$or": [{"id": c.get("patron_id")}, {"wallet_address": c.get("patron_id")}]}, {"_id": 0, "username": 1})
            vu = await db.users.find_one({"$or": [{"id": c.get("vassal_id")}, {"wallet_address": c.get("vassal_id")}]}, {"_id": 0, "username": 1})
            pbiz_cfg = BUSINESSES.get((pbiz or {}).get("business_type", ""), {})
            vbiz_cfg = BUSINESSES.get((vbiz or {}).get("business_type", ""), {})
            
            # V2: Calculate progress
            duration = c.get("duration_days", 30)
            accepted_at = c.get("accepted_at")
            expires_at = c.get("expires_at")
            days_elapsed = 0
            days_remaining = duration
            progress_pct = 0
            
            if accepted_at and c.get("status") == "active":
                accepted_dt = to_aware(accepted_at)
                days_elapsed = (now - accepted_dt).days if accepted_dt else 0
                days_remaining = max(0, duration - days_elapsed)
                progress_pct = min(100, round((days_elapsed / duration) * 100, 1))
            
            contract_type = CONTRACT_TYPES.get(c.get("type", ""), {})
            
            result.append({
                **c,
                "patron_username": (pu or {}).get("username", "?"),
                "vassal_username": (vu or {}).get("username", "?"),
                "patron_business_name": pbiz_cfg.get("name", {}).get("ru", "?"),
                "patron_business_icon": pbiz_cfg.get("icon", "🏢"),
                "patron_business_level": (pbiz or {}).get("level", 1),
                "vassal_business_name": vbiz_cfg.get("name", {}).get("ru", "?"),
                "vassal_business_icon": vbiz_cfg.get("icon", "🏢"),
                "vassal_business_level": (vbiz or {}).get("level", 1),
                "buff_data": TIER3_BUFFS.get(c.get("patron_buff", ""), {}),
                "contract_type_data": contract_type,
                # V2 fields
                "days_elapsed": days_elapsed,
                "days_remaining": days_remaining,
                "progress_pct": progress_pct,
                "patron_benefit_text": contract_type.get("patron_benefit", ""),
                "vassal_benefit_text": contract_type.get("vassal_benefit", ""),
                "cancel_fee_city": int(duration) * 100,
            })
        return result

    return {
        "as_patron": await enrich(contracts_as_patron),
        "as_vassal": await enrich(contracts_as_vassal),
    }


@api_router.get("/contracts/history")
async def get_contracts_history(current_user: User = Depends(get_current_user)):
    """V2: Get completed/cancelled contract history"""
    ui = await get_user_identifiers(current_user)
    user_ids = list(ui["ids"])

    history = await db.contracts.find(
        {
            "$or": [
                {"patron_id": {"$in": user_ids}},
                {"vassal_id": {"$in": user_ids}},
            ],
            "status": {"$in": ["cancelled", "completed", "expired", "rejected"]},
        },
        {"_id": 0}
    ).sort("cancelled_at", -1).to_list(50)

    result = []
    for c in history:
        contract_type = CONTRACT_TYPES.get(c.get("type", ""), {})
        pu = await db.users.find_one({"$or": [{"id": c.get("patron_id")}, {"wallet_address": c.get("patron_id")}]}, {"_id": 0, "username": 1})
        vu = await db.users.find_one({"$or": [{"id": c.get("vassal_id")}, {"wallet_address": c.get("vassal_id")}]}, {"_id": 0, "username": 1})
        
        is_patron = c.get("patron_id") in ui["ids"]
        role = "patron" if is_patron else "vassal"
        
        result.append({
            **c,
            "role": role,
            "patron_username": (pu or {}).get("username", "?"),
            "vassal_username": (vu or {}).get("username", "?"),
            "contract_type_data": contract_type,
            "buff_data": TIER3_BUFFS.get(c.get("patron_buff", ""), {}),
        })

    return {"history": result}


@api_router.post("/contracts/propose")
async def propose_contract(data: ContractProposal, current_user: User = Depends(get_current_user)):
    """Patron proposes a contract to a vassal"""
    ui = await get_user_identifiers(current_user)
    patron_id = ui["primary_id"]

    valid_types = list(CONTRACT_TYPES.keys())
    if data.type not in valid_types:
        raise HTTPException(status_code=400, detail="Неверный тип контракта")
    if data.patron_buff not in TIER3_BUFFS:
        raise HTTPException(status_code=400, detail="Неверный ID бафа")

    # Find patron's Tier 3 business
    patron_biz = None
    all_bizs = await db.businesses.find({"owner": {"$in": list(ui["ids"])}}, {"_id": 0}).to_list(100)
    for b in all_bizs:
        bc = BUSINESSES.get(b.get("business_type", ""), {})
        if bc.get("tier", 1) == 3:
            patron_biz = b
            break
    if not patron_biz:
        raise HTTPException(status_code=403, detail="Нужен бизнес Эшелона 3 для заключения контрактов")

    # Find vassal's business
    vassal_biz = await db.businesses.find_one({"id": data.vassal_business_id}, {"_id": 0})
    if not vassal_biz:
        raise HTTPException(status_code=404, detail="Бизнес вассала не найден")

    vassal_id = vassal_biz["owner"]
    if vassal_id in ui["ids"]:
        raise HTTPException(status_code=400, detail="Нельзя заключить контракт с самим собой")

    # Check for existing active/proposed contract
    existing = await db.contracts.find_one({
        "patron_business_id": patron_biz["id"],
        "vassal_business_id": data.vassal_business_id,
        "status": {"$in": ["proposed", "active"]},
    })
    if existing:
        raise HTTPException(status_code=400, detail="Контракт уже существует или ожидает принятия")

    # V2: Validate duration
    if data.duration_days < 7 or data.duration_days > 90:
        raise HTTPException(status_code=400, detail="Длительность контракта: от 7 до 90 дней")

    contract = {
        "id": str(uuid.uuid4()),
        "type": data.type,
        "patron_id": patron_id,
        "vassal_id": vassal_id,
        "patron_business_id": patron_biz["id"],
        "vassal_business_id": data.vassal_business_id,
        "patron_buff": data.patron_buff,
        "status": "proposed",
        "duration_days": data.duration_days,
        "auto_renew": data.auto_renew,
        "days_elapsed": 0,
        "proposed_at": datetime.now(timezone.utc).isoformat(),
        "accepted_at": None,
        "expires_at": None,
        "cancelled_at": None,
        "cancelled_by": None,
        "violation_days": [],
        "penalty_paid": False,
        "total_patron_income": 0,
        "total_vassal_savings": 0,
        "patron_rating_change": 0,
        "vassal_rating_change": 0,
    }
    await db.contracts.insert_one(contract)
    del contract["_id"]
    
    # V2: Create notification for vassal
    patron_user = ui["user"]
    patron_biz_cfg = BUSINESSES.get(patron_biz.get("business_type", ""), {})
    vassal_biz_cfg = BUSINESSES.get(vassal_biz.get("business_type", ""), {})
    contract_type_info = CONTRACT_TYPES.get(data.type, {})
    buff_info = TIER3_BUFFS.get(data.patron_buff, {})
    
    notif = {
        "id": str(uuid.uuid4()),
        "user_id": vassal_id,
        "type": "contract_proposal",
        "title": f"Новый контракт: {contract_type_info.get('icon', '')} {contract_type_info.get('name_ru', data.type)}",
        "message": (
            f"{patron_user.get('username', '?')} ({patron_biz_cfg.get('icon', '')} {patron_biz_cfg.get('name', {}).get('ru', '')}) "
            f"предлагает контракт на {data.duration_days} дн.\n"
            f"Ваш бизнес: {vassal_biz_cfg.get('icon', '')} {vassal_biz_cfg.get('name', {}).get('ru', '')}\n"
            f"Вы получаете баф: {buff_info.get('icon', '')} {buff_info.get('name', '')} — {buff_info.get('description', '')}\n"
            f"Вы отдаёте: {contract_type_info.get('patron_benefit', '')}\n"
            f"Штраф за досрочное расторжение: {data.duration_days * 100} $CITY (срок × 100)"
        ),
        "contract_id": contract["id"],
        "read": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        from core.notify import notify_user as _nu_generic
        await _nu_generic(db, notif.get("user_id"), title=notif.get("title", ""), message=notif.get("message", ""),
                          type_key=notif.get("type", "system"), priority=notif.get("priority", "info"),
                          payload={k: v for k, v in notif.items() if k not in ("id", "user_id", "title", "message", "type", "priority", "read", "created_at")})
    except Exception as _e:
        logger.warning(f"notify failed: {_e}")
    
    return {"success": True, "contract_id": contract["id"], "message": "Предложение контракта отправлено"}


@api_router.post("/contracts/{contract_id}/accept")
async def patron_accept_contract(contract_id: str, current_user: User = Depends(get_current_user)):
    """Vassal accepts a contract proposal"""
    ui = await get_user_identifiers(current_user)
    contract = await db.contracts.find_one({"id": contract_id}, {"_id": 0})
    if not contract:
        raise HTTPException(status_code=404, detail="Контракт не найден")
    if contract.get("vassal_id") not in ui["ids"]:
        raise HTTPException(status_code=403, detail="Это не ваш контракт")
    if contract.get("status") != "proposed":
        raise HTTPException(status_code=400, detail="Контракт уже не в статусе предложения")

    # V2: Set expiry based on duration
    duration = contract.get("duration_days", 30)
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(days=duration)).isoformat()
    
    # V2: Set contract buff AND patron_id on vassal's business (patronage through contract)
    # Only set patron_id if the vassal's business has no patron yet (respect 7-day rule).
    vassal_biz_pre = await db.businesses.find_one(
        {"id": contract["vassal_business_id"]}, {"_id": 0, "patron_id": 1, "last_patron_change": 1}
    ) or {}
    biz_set = {
        "contract_buff": contract["patron_buff"],
        "contract_id": contract["id"],
    }
    if not vassal_biz_pre.get("patron_id"):
        biz_set["patron_id"] = contract["patron_business_id"]
        biz_set["last_patron_change"] = now.isoformat()
    await db.businesses.update_one(
        {"id": contract["vassal_business_id"]},
        {"$set": biz_set}
    )
    await db.contracts.update_one(
        {"id": contract_id},
        {"$set": {
            "status": "active",
            "accepted_at": now.isoformat(),
            "expires_at": expires_at,
        }}
    )
    
    # V2: Notification for patron that contract was accepted
    vassal_user = await db.users.find_one(
        {"$or": [{"id": contract["vassal_id"]}, {"wallet_address": contract["vassal_id"]}]},
        {"_id": 0, "username": 1}
    )
    vassal_biz = await db.businesses.find_one({"id": contract["vassal_business_id"]}, {"_id": 0})
    vassal_biz_cfg = BUSINESSES.get((vassal_biz or {}).get("business_type", ""), {})
    contract_type_info = CONTRACT_TYPES.get(contract.get("type", ""), {})
    
    notif = {
        "id": str(uuid.uuid4()),
        "user_id": contract["patron_id"],
        "type": "contract_accepted",
        "title": f"Контракт принят: {contract_type_info.get('icon', '')} {contract_type_info.get('name_ru', '')}",
        "message": (
            f"{(vassal_user or {}).get('username', '?')} принял ваш контракт «{contract_type_info.get('name_ru', '')}».\n"
            f"Бизнес вассала: {vassal_biz_cfg.get('icon', '')} {vassal_biz_cfg.get('name', {}).get('ru', '')}\n"
            f"Вы получаете: {contract_type_info.get('patron_benefit', '')}\n"
            f"Срок: {duration} дней"
        ),
        "contract_id": contract["id"],
        "read": False,
        "created_at": now.isoformat(),
    }
    try:
        from core.notify import notify_user as _nu_generic
        await _nu_generic(db, notif.get("user_id"), title=notif.get("title", ""), message=notif.get("message", ""),
                          type_key=notif.get("type", "system"), priority=notif.get("priority", "info"),
                          payload={k: v for k, v in notif.items() if k not in ("id", "user_id", "title", "message", "type", "priority", "read", "created_at")})
    except Exception as _e:
        logger.warning(f"notify failed: {_e}")
    
    return {"success": True, "message": "Контракт принят! Покровительство и баф активированы."}


@api_router.post("/contracts/{contract_id}/reject")
async def patron_reject_contract(contract_id: str, current_user: User = Depends(get_current_user)):
    """Vassal rejects a contract proposal"""
    ui = await get_user_identifiers(current_user)
    contract = await db.contracts.find_one({"id": contract_id}, {"_id": 0})
    if not contract:
        raise HTTPException(status_code=404, detail="Контракт не найден")
    if contract.get("vassal_id") not in ui["ids"]:
        raise HTTPException(status_code=403, detail="Это не ваш контракт")
    if contract.get("status") != "proposed":
        raise HTTPException(status_code=400, detail="Нельзя отклонить уже принятый контракт")

    await db.contracts.update_one(
        {"id": contract_id},
        {"$set": {"status": "rejected", "cancelled_at": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(), "cancelled_by": "vassal"}}
    )
    return {"success": True, "message": "Контракт отклонён"}


@api_router.post("/contracts/{contract_id}/cancel")
async def patron_cancel_contract(contract_id: str, current_user: User = Depends(get_current_user)):
    """Cancel a contract. Either side pays a fixed fee = duration_days * 100 $CITY."""
    ui = await get_user_identifiers(current_user)
    contract = await db.contracts.find_one({"id": contract_id}, {"_id": 0})
    if not contract:
        raise HTTPException(status_code=404, detail="Контракт не найден")

    is_patron = contract.get("patron_id") in ui["ids"]
    is_vassal = contract.get("vassal_id") in ui["ids"]
    if not is_patron and not is_vassal:
        raise HTTPException(status_code=403, detail="У вас нет доступа к этому контракту")
    if contract.get("status") not in ["proposed", "active"]:
        raise HTTPException(status_code=400, detail="Контракт уже не активен")

    now = datetime.now(timezone.utc)
    duration_days = int(contract.get("duration_days", 30))
    # Fixed fee schedule: 100 $CITY per day of contract duration
    penalty_amount = duration_days * 100

    # V6: Grace period — if the contract has been paused/inactive for ≥3 days
    # (e.g. patron is on sale, terms-violation pause), the side that wants to
    # break the alliance pays no penalty.
    inactive_since_raw = contract.get("inactive_since")
    if inactive_since_raw:
        try:
            inactive_since = datetime.fromisoformat(str(inactive_since_raw).replace('Z', '+00:00'))
            if (now - inactive_since).days >= 3:
                penalty_amount = 0
        except (ValueError, TypeError):
            pass

    # Apply fee only for active (already accepted) contracts. Proposals can be withdrawn for free.
    if contract.get("status") == "active" and penalty_amount > 0:
        canceller_user_id_or_wallet = contract["patron_id"] if is_patron else contract["vassal_id"]
        counterparty_user_id_or_wallet = contract["vassal_id"] if is_patron else contract["patron_id"]

        canceller = await db.users.find_one(
            {"$or": [{"id": canceller_user_id_or_wallet}, {"wallet_address": canceller_user_id_or_wallet}]},
            {"_id": 0, "balance_ton": 1}
        )
        canceller_balance_city = (canceller or {}).get("balance_ton", 0) * 1000
        if canceller_balance_city < penalty_amount:
            raise HTTPException(
                status_code=400,
                detail=f"Недостаточно $CITY для расторжения. Нужно {penalty_amount} $CITY (срок {duration_days} дн. × 100)."
            )
        # Charge canceller, pay counterparty
        await db.users.update_one(
            {"$or": [{"id": canceller_user_id_or_wallet}, {"wallet_address": canceller_user_id_or_wallet}]},
            {"$inc": {"balance_ton": -penalty_amount / 1000}}
        )
        await db.users.update_one(
            {"$or": [{"id": counterparty_user_id_or_wallet}, {"wallet_address": counterparty_user_id_or_wallet}]},
            {"$inc": {"balance_ton": penalty_amount / 1000}}
        )

    # Detach buff/contract from vassal's business — patron_id stays (patron change has 7-day cooldown rule)
    biz_unset = {"contract_buff": "", "contract_id": ""}
    await db.businesses.update_one(
        {"id": contract.get("vassal_business_id")},
        {"$unset": biz_unset}
    )
    cancelled_by = "patron" if is_patron else "vassal"

    rating_change = -1 if penalty_amount > 0 else 0

    await db.contracts.update_one(
        {"id": contract_id},
        {"$set": {
            "status": "cancelled",
            "cancelled_at": now.isoformat(),
            "cancelled_by": cancelled_by,
            "penalty_paid": penalty_amount > 0 and contract.get("status") == "active",
            "penalty_amount": penalty_amount if contract.get("status") == "active" else 0,
        }}
    )

    # V4: Unpause patron's offers if they fall below 25 active alliances
    patron_id_for_offers = contract.get("patron_id")
    if patron_id_for_offers:
        remaining = await db.contracts.count_documents({
            "patron_id": patron_id_for_offers, "status": {"$in": ["active", "proposed"]}
        })
        if remaining < 25:
            await db.alliance_offers.update_many(
                {"patron_id": patron_id_for_offers, "status": "paused", "paused_reason": "limit_25_alliances"},
                {"$set": {"status": "open"}, "$unset": {"paused_reason": "", "paused_at": ""}},
            )

    # Notifications for BOTH sides
    contract_type_info = CONTRACT_TYPES.get(contract.get("type", ""), {})
    canceller_name = (ui["user"] or {}).get("username", "?")
    canceller_role_ru = "Патрон" if is_patron else "Вассал"
    title = f"Контракт расторгнут: {contract_type_info.get('icon', '')} {contract_type_info.get('name_ru', '')}"

    # Counterparty notification
    if contract.get("status") == "proposed":
        counterparty_msg = f"{canceller_role_ru} {canceller_name} отозвал предложение контракта."
        canceller_msg = "Вы отозвали предложение контракта без штрафа."
    else:
        counterparty_msg = (
            f"{canceller_role_ru} {canceller_name} расторгнул контракт.\n"
            f"Срок был: {duration_days} дн.\n"
            f"Вы получили компенсацию: {penalty_amount} $CITY"
        )
        canceller_msg = (
            f"Вы расторгли контракт ({duration_days} дн.).\n"
            f"С вашего баланса списано {penalty_amount} $CITY (штраф = срок × 100)."
        )

    counterparty_id = contract["vassal_id"] if is_patron else contract["patron_id"]
    canceller_id = contract["patron_id"] if is_patron else contract["vassal_id"]

    notif_counterparty = {
        "id": str(uuid.uuid4()),
        "user_id": counterparty_id,
        "type": "contract_cancelled",
        "title": title,
        "message": counterparty_msg,
        "contract_id": contract_id,
        "read": False,
        "created_at": now.isoformat(),
    }
    notif_canceller = {
        "id": str(uuid.uuid4()),
        "user_id": canceller_id,
        "type": "contract_cancelled_self",
        "title": title,
        "message": canceller_msg,
        "contract_id": contract_id,
        "read": False,
        "created_at": now.isoformat(),
    }
    await db.notifications.insert_many([notif_counterparty, notif_canceller])

    msg = (
        f"Контракт расторгнут. Штраф {penalty_amount} $CITY списан."
        if penalty_amount > 0 and contract.get("status") == "active"
        else "Контракт расторгнут без штрафа."
    )
    return {"success": True, "message": msg, "penalty": penalty_amount if contract.get("status") == "active" else 0}


@api_router.get("/contracts/{contract_id}")
async def get_patron_contract(contract_id: str, current_user: User = Depends(get_current_user)):
    """Get contract details"""
    ui = await get_user_identifiers(current_user)
    contract = await db.contracts.find_one({"id": contract_id}, {"_id": 0})
    if not contract:
        raise HTTPException(status_code=404, detail="Контракт не найден")
    if contract.get("patron_id") not in ui["ids"] and contract.get("vassal_id") not in ui["ids"]:
        raise HTTPException(status_code=403, detail="Нет доступа")
    buff_data = TIER3_BUFFS.get(contract.get("patron_buff", ""), {})
    type_data = CONTRACT_TYPES.get(contract.get("type", ""), {})
    return {**contract, "buff_data": buff_data, "contract_type_data": type_data}


# ==================== HIDE OFFERS/CONTRACTS ====================

@api_router.post("/alliances/hide/{offer_id}")
async def hide_alliance_offer(offer_id: str, current_user: User = Depends(get_current_user)):
    """Hide an alliance offer for current user"""
    ui = await get_user_identifiers(current_user)
    if not ui["user"]:
        raise HTTPException(status_code=401)
    user_id = ui["primary_id"]
    await db.users.update_one(
        {"id": user_id},
        {"$addToSet": {"hidden_offers": offer_id}}
    )
    return {"success": True, "message": "Оффер скрыт"}


@api_router.post("/contracts/hide/{contract_id}")
async def hide_contract(contract_id: str, current_user: User = Depends(get_current_user)):
    """Hide a contract proposal for current user"""
    ui = await get_user_identifiers(current_user)
    if not ui["user"]:
        raise HTTPException(status_code=401)
    user_id = ui["primary_id"]
    await db.users.update_one(
        {"id": user_id},
        {"$addToSet": {"hidden_contracts": contract_id}}
    )
    return {"success": True, "message": "Контракт скрыт"}


@api_router.get("/alliances/offers")
async def list_alliance_offers_v2(current_user: User = Depends(get_current_user)):
    """List actual open patron offers from OTHER players, excluding hidden / already-accepted."""
    ui = await get_user_identifiers(current_user)
    user_ids = list(ui["ids"])

    user_doc = ui["user"] or {}
    hidden = set(user_doc.get("hidden_offers", []))

    # Offers user is already in active contract for (any business of his)
    my_active_contracts = await db.contracts.find(
        {"vassal_id": {"$in": user_ids}, "status": {"$in": ["active", "proposed"]}, "from_offer_id": {"$exists": True, "$ne": None}},
        {"_id": 0, "from_offer_id": 1, "vassal_business_id": 1}
    ).to_list(500)
    # Map offer_id -> set of vassal_business_ids that already accepted
    accepted_offer_biz = {}
    for c in my_active_contracts:
        oid = c.get("from_offer_id")
        if oid:
            accepted_offer_biz.setdefault(oid, set()).add(c.get("vassal_business_id"))

    # Number of user's businesses (Tier 1+ only — businesses can be vassal)
    my_businesses_count = await db.businesses.count_documents({"owner": {"$in": user_ids}})

    offers = await db.alliance_offers.find(
        {"status": "open", "patron_id": {"$nin": user_ids}},
        {"_id": 0}
    ).sort("created_at", -1).to_list(200)

    visible = []
    for o in offers:
        if o.get("id") in hidden:
            continue
        # Hide offer if ALL of user's businesses already accepted this offer
        accepted_count_for_offer = len(accepted_offer_biz.get(o.get("id"), set()))
        if my_businesses_count > 0 and accepted_count_for_offer >= my_businesses_count:
            continue
        if "cancel_fee_city" not in o:
            o["cancel_fee_city"] = int(o.get("duration_days", 30)) * 100
        o.pop("penalty_city", None)
        o["acceptances_count"] = o.get("acceptances_count", 0)
        # Pass to client which of my businesses already accepted (so UI can grey them out in selector)
        o["already_accepted_business_ids"] = list(accepted_offer_biz.get(o.get("id"), set()))
        visible.append(o)

    await _enrich_seller_usernames(visible, id_field="patron_id", name_field="patron_username")
    return {"offers": visible, "total": len(offers), "hidden_count": len(offers) - len(visible)}


@api_router.get("/alliances/my-offers")
async def list_my_alliance_offers(current_user: User = Depends(get_current_user)):
    """List current user's published offers (only Tier-3 owners have any)."""
    ui = await get_user_identifiers(current_user)
    user_ids = list(ui["ids"])

    has_tier3 = False
    for b in await db.businesses.find({"owner": {"$in": user_ids}}, {"_id": 0, "business_type": 1}).to_list(100):
        if BUSINESSES.get(b.get("business_type", ""), {}).get("tier", 1) == 3:
            has_tier3 = True
            break

    offers = await db.alliance_offers.find(
        {"patron_id": {"$in": user_ids}, "status": {"$in": ["open", "paused"]}},
        {"_id": 0}
    ).sort("created_at", -1).to_list(50)

    for o in offers:
        if "cancel_fee_city" not in o:
            o["cancel_fee_city"] = int(o.get("duration_days", 30)) * 100
        o.pop("penalty_city", None)
        o["acceptances_count"] = o.get("acceptances_count", 0)

    active_alliances_count = await db.contracts.count_documents({
        "patron_id": ui["primary_id"], "status": {"$in": ["active", "proposed"]}
    })

    # Per-T3-business active alliances count (for "n/25" display)
    per_business_counts: dict = {}
    async for biz in db.businesses.find(
        {"owner": {"$in": list(ui["ids"])}}, {"_id": 0, "id": 1, "business_type": 1}
    ):
        if BUSINESSES.get(biz.get("business_type", ""), {}).get("tier", 1) != 3:
            continue
        bid = biz.get("id")
        if not bid:
            continue
        per_business_counts[bid] = await db.contracts.count_documents(
            {"patron_business_id": bid, "status": {"$in": ["active", "proposed"]}}
        )

    await _enrich_seller_usernames(offers, id_field="patron_id", name_field="patron_username")
    return {
        "offers": offers,
        "has_tier3": has_tier3,
        "active_alliances": active_alliances_count,
        "max_published": 5,
        "max_alliances": 25,
        "per_business_alliances": per_business_counts,
    }


@api_router.post("/alliances/cancel-offer/{offer_id}")
async def cancel_my_alliance_offer(offer_id: str, current_user: User = Depends(get_current_user)):
    """Patron removes one of their own offers (open or paused). Existing contracts are NOT affected."""
    ui = await get_user_identifiers(current_user)
    user_ids = list(ui["ids"])
    offer = await db.alliance_offers.find_one({"id": offer_id}, {"_id": 0})
    if not offer:
        raise HTTPException(status_code=404, detail="Оффер не найден")
    if offer.get("patron_id") not in user_ids:
        raise HTTPException(status_code=403, detail="Это не ваш оффер")
    if offer.get("status") not in ("open", "paused"):
        raise HTTPException(status_code=400, detail="Оффер уже закрыт")
    await db.alliance_offers.update_one(
        {"id": offer_id},
        {"$set": {"status": "cancelled", "cancelled_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"success": True, "message": "Оффер снят с публикации."}


# ==================== COUNTER-OFFER (Встречное предложение) ====================

class CounterOfferCreate(BaseModel):
    offer_id: str
    contract_type: str       # vassal's preferred payment type
    duration_days: int = 30  # vassal's preferred duration
    comment: Optional[str] = None
    vassal_business_id: Optional[str] = None  # fix #4: vassal picks which business
    buff_id: Optional[str] = None             # fix #5: vassal may propose alternate T3 buff


@api_router.post("/alliances/counter-offer")
async def create_counter_offer(data: CounterOfferCreate, current_user: User = Depends(get_current_user)):
    """Vassal creates counter-offer for an existing patron offer"""
    ui = await get_user_identifiers(current_user)
    if not ui["user"]:
        raise HTTPException(status_code=401)
    
    vassal_id = ui["primary_id"]
    
    # Validate
    if data.contract_type not in CONTRACT_TYPES:
        raise HTTPException(status_code=400, detail="Неверный тип контракта")
    if data.duration_days < 7 or data.duration_days > 90:
        raise HTTPException(status_code=400, detail="Срок: от 7 до 90 дней")
    if data.buff_id and data.buff_id not in TIER3_BUFFS:
        raise HTTPException(status_code=400, detail="Неверный баф")
    
    # Find original offer
    offer = await db.alliance_offers.find_one({"id": data.offer_id, "status": "open"}, {"_id": 0})
    if not offer:
        raise HTTPException(status_code=404, detail="Оффер не найден")
    if offer["patron_id"] == vassal_id:
        raise HTTPException(status_code=400, detail="Нельзя отправить встречное на свой оффер")
    
    # Check limits for non-Tier3
    has_tier3 = False
    user_bizs = await db.businesses.find({"owner": {"$in": list(ui["ids"])}}, {"_id": 0, "business_type": 1, "id": 1}).to_list(100)
    for b in user_bizs:
        bc = BUSINESSES.get(b.get("business_type", ""), {})
        if bc.get("tier", 1) == 3:
            has_tier3 = True
            break
    
    if not has_tier3:
        # Count active contracts + offers
        active_contracts = await db.contracts.count_documents({
            "$or": [{"patron_id": {"$in": list(ui["ids"])}}, {"vassal_id": {"$in": list(ui["ids"])}}],
            "status": {"$in": ["active", "proposed"]}
        })
        active_counters = await db.counter_offers.count_documents({"vassal_id": vassal_id, "status": "pending"})
        if active_contracts + active_counters >= 3:
            raise HTTPException(status_code=400, detail="Лимит: 3 контракта/оффера для обычных пользователей")
    
    # Fix #4: explicit choice of vassal business; require it when multiple bizs exist
    user_bizs_full = await db.businesses.find({"owner": {"$in": list(ui["ids"])}}, {"_id": 0}).to_list(100)
    if not user_bizs_full:
        raise HTTPException(status_code=404, detail="У вас нет бизнеса")
    if data.vassal_business_id:
        vassal_biz = next((b for b in user_bizs_full if b.get("id") == data.vassal_business_id), None)
        if not vassal_biz:
            raise HTTPException(status_code=404, detail="Бизнес не найден")
    elif len(user_bizs_full) == 1:
        vassal_biz = user_bizs_full[0]
    else:
        raise HTTPException(
            status_code=400,
            detail="У вас несколько бизнесов — укажите vassal_business_id для встречного предложения.",
        )
    
    vassal_biz_cfg = BUSINESSES.get(vassal_biz.get("business_type", ""), {})
    ct_info = CONTRACT_TYPES[data.contract_type]
    user = ui["user"]

    # Fix #5: vassal may propose alternate buff; if not provided, keep patron's pick
    effective_buff_id = data.buff_id or offer.get("buff_id")
    effective_buff = TIER3_BUFFS.get(effective_buff_id, {})
    buff_is_custom = bool(data.buff_id and data.buff_id != offer.get("buff_id"))

    counter = {
        "id": str(uuid.uuid4()),
        "original_offer_id": data.offer_id,
        "patron_id": offer["patron_id"],
        "patron_username": offer.get("patron_username"),
        "patron_business_id": offer.get("patron_business_id"),
        "patron_business_name": offer.get("patron_business_name"),
        "patron_business_icon": offer.get("patron_business_icon"),
        "vassal_id": vassal_id,
        "vassal_username": user.get("username"),
        "vassal_business_id": vassal_biz["id"],
        "vassal_business_name": vassal_biz_cfg.get("name", {}).get("ru", "?"),
        "vassal_business_icon": vassal_biz_cfg.get("icon", "🏢"),
        "buff_id": effective_buff_id,
        "buff_name": effective_buff.get("name", offer.get("buff_name", "")),
        "buff_icon": effective_buff.get("icon", offer.get("buff_icon", "")),
        "buff_description": effective_buff.get("description", offer.get("buff_description", "")),
        "buff_is_custom": buff_is_custom,
        "original_buff_id": offer.get("buff_id"),
        "original_contract_type": offer.get("contract_type"),
        "proposed_contract_type": data.contract_type,
        "proposed_contract_type_name": ct_info.get("name_ru", ""),
        "proposed_contract_type_icon": ct_info.get("icon", ""),
        "proposed_vassal_pays": ct_info.get("patron_benefit", ""),
        "original_duration": offer.get("duration_days", 30),
        "proposed_duration": data.duration_days,
        # Frozen rates for the proposed contract type (fix #8)
        "tax_rate": float(ct_info.get("tax_rate", 0)),
        "material_share": float(ct_info.get("material_share", 0)),
        "daily_rent_city": float(ct_info.get("daily_rent_city", 0)),
        "comment": (data.comment or "")[:200],
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.counter_offers.insert_one(counter.copy())

    # Build rich payload so the bell shows full offer card (с принять/отклонить)
    counter_payload = {
        "kind": "counter_offer",
        "counter_offer_id": counter["id"],
        "original_offer_id": data.offer_id,
        "vassal_username": counter["vassal_username"],
        "vassal_business_name": counter["vassal_business_name"],
        "vassal_business_icon": counter["vassal_business_icon"],
        "patron_business_name": counter["patron_business_name"],
        "patron_business_icon": counter["patron_business_icon"],
        "buff_id": counter["buff_id"],
        "buff_name": counter["buff_name"],
        "buff_icon": counter["buff_icon"],
        "buff_description": counter["buff_description"],
        "buff_is_custom": counter["buff_is_custom"],
        "original_buff_id": counter["original_buff_id"],
        "original_contract_type": counter["original_contract_type"],
        "proposed_contract_type": counter["proposed_contract_type"],
        "proposed_contract_type_name": counter["proposed_contract_type_name"],
        "proposed_contract_type_icon": counter["proposed_contract_type_icon"],
        "proposed_vassal_pays": counter["proposed_vassal_pays"],
        "original_duration": counter["original_duration"],
        "proposed_duration": counter["proposed_duration"],
        "comment": counter["comment"],
    }

    # Notify patron via shared notify_user so WS push fires (bell shake) and
    # payload is delivered for rich card rendering on the frontend.
    try:
        from core.notify import notify_user as _notify_user
        patron_doc = await db.users.find_one({"id": offer["patron_id"]}, {"_id": 0})
        await _notify_user(
            db,
            patron_doc or offer["patron_id"],
            f"Встречное предложение от {user.get('username', '?')}",
            (
                f"{user.get('username', '?')} предлагает: "
                f"{ct_info.get('icon', '')} {ct_info.get('name_ru', '')} на {data.duration_days} дн. "
                f"Баф: {counter['buff_icon']} {counter['buff_name']}."
                + (f" Комментарий: {counter['comment']}" if counter["comment"] else "")
            ),
            type_key="counter_offer",
            priority="info",
            payload=counter_payload,
        )
    except Exception as _e:
        logger.warning(f"counter_offer notify failed: {_e}")

    return {"success": True, "message": "Встречное предложение отправлено!", "counter_offer_id": counter["id"]}


@api_router.get("/alliances/counter-offers")
async def get_counter_offers(current_user: User = Depends(get_current_user)):
    """Get counter-offers for current user (as patron or vassal)"""
    ui = await get_user_identifiers(current_user)
    user_ids = list(ui["ids"])
    
    as_patron = await db.counter_offers.find(
        {"patron_id": {"$in": user_ids}, "status": "pending"}, {"_id": 0}
    ).to_list(50)
    
    as_vassal = await db.counter_offers.find(
        {"vassal_id": {"$in": user_ids}}, {"_id": 0}
    ).to_list(50)
    for _grp in (as_patron, as_vassal):
        await _enrich_seller_usernames(_grp, id_field="patron_id", name_field="patron_username")
        await _enrich_seller_usernames(_grp, id_field="vassal_id", name_field="vassal_username")
    return {"as_patron": as_patron, "as_vassal": as_vassal}


@api_router.post("/alliances/counter-offer/{counter_id}/accept")
async def accept_counter_offer(counter_id: str, current_user: User = Depends(get_current_user)):
    """Patron accepts a vassal's counter-offer → creates active contract"""
    ui = await get_user_identifiers(current_user)
    counter = await db.counter_offers.find_one({"id": counter_id, "status": "pending"}, {"_id": 0})
    if not counter:
        raise HTTPException(status_code=404, detail="Встречное предложение не найдено")
    if counter["patron_id"] not in ui["ids"]:
        raise HTTPException(status_code=403, detail="Только Патрон может принять встречное предложение")
    
    now = datetime.now(timezone.utc)
    duration = counter["proposed_duration"]
    
    contract = {
        "id": str(uuid.uuid4()),
        "type": counter["proposed_contract_type"],
        "patron_id": counter["patron_id"],
        "vassal_id": counter["vassal_id"],
        "patron_business_id": counter["patron_business_id"],
        "vassal_business_id": counter["vassal_business_id"],
        "patron_buff": counter["buff_id"],
        "status": "active",
        "duration_days": duration,
        "auto_renew": False,
        "days_elapsed": 0,
        "proposed_at": counter.get("created_at"),
        "accepted_at": now.isoformat(),
        "expires_at": (now + timedelta(days=duration)).isoformat(),
        "cancelled_at": None,
        "cancelled_by": None,
        "violation_days": [],
        "penalty_paid": False,
        "total_patron_income": 0,
        "total_vassal_savings": 0,
        "from_counter_offer": True,
        # Frozen rates carried from counter (fix #8)
        "tax_rate": float(counter.get("tax_rate", CONTRACT_TYPES.get(counter["proposed_contract_type"], {}).get("tax_rate", 0))),
        "material_share": float(counter.get("material_share", CONTRACT_TYPES.get(counter["proposed_contract_type"], {}).get("material_share", 0))),
        "daily_rent_city": float(counter.get("daily_rent_city", CONTRACT_TYPES.get(counter["proposed_contract_type"], {}).get("daily_rent_city", 0))),
    }
    await db.contracts.insert_one(contract.copy())
    
    # Set patron + buff on vassal business
    await db.businesses.update_one(
        {"id": counter["vassal_business_id"]},
        {"$set": {
            "patron_id": counter["patron_business_id"],
            "contract_id": contract["id"],
            "contract_buff": counter["buff_id"],
        }}
    )
    
    # Update counter-offer status
    await db.counter_offers.update_one({"id": counter_id}, {"$set": {"status": "accepted", "accepted_at": now.isoformat()}})

    # Notify vassal that counter-offer was accepted and alliance is active
    try:
        from core.notify import notify_user as _notify_user
        vassal_doc = await db.users.find_one({"id": counter["vassal_id"]}, {"_id": 0})
        await _notify_user(
            db,
            vassal_doc or counter["vassal_id"],
            "Встречное предложение принято",
            (
                f"@{counter.get('patron_username') or current_user.username or 'Patron'} принял ваше встречное предложение. "
                f"Альянс заключён: {counter.get('proposed_contract_type_icon','')} {counter.get('proposed_contract_type_name','')} "
                f"на {duration} дн., баф: {counter.get('buff_icon','')} {counter.get('buff_name','')}."
            ),
            type_key="counter_offer_accepted",
            priority="success",
            payload={
                "kind": "counter_offer_accepted",
                "counter_offer_id": counter_id,
                "contract_id": contract["id"],
            },
        )
    except Exception as _e:
        logger.warning(f"counter_offer accepted notify failed: {_e}")

    return {"success": True, "message": "Встречное предложение принято! Альянс заключён."}


@api_router.post("/alliances/counter-offer/{counter_id}/reject")
async def reject_counter_offer(counter_id: str, current_user: User = Depends(get_current_user)):
    """Patron rejects a counter-offer"""
    ui = await get_user_identifiers(current_user)
    counter = await db.counter_offers.find_one({"id": counter_id, "status": "pending"}, {"_id": 0})
    if not counter:
        raise HTTPException(status_code=404, detail="Не найдено")
    if counter["patron_id"] not in ui["ids"]:
        raise HTTPException(status_code=403)
    await db.counter_offers.update_one({"id": counter_id}, {"$set": {"status": "rejected", "rejected_at": datetime.now(timezone.utc).isoformat()}})

    # Notify vassal that their counter-offer was rejected
    try:
        from core.notify import notify_user as _notify_user
        vassal_doc = await db.users.find_one({"id": counter["vassal_id"]}, {"_id": 0})
        await _notify_user(
            db,
            vassal_doc or counter["vassal_id"],
            "Встречное предложение отклонено",
            (
                f"@{counter.get('patron_username') or current_user.username or 'Patron'} отклонил ваше встречное предложение "
                f"({counter.get('proposed_contract_type_icon','')} {counter.get('proposed_contract_type_name','')}, "
                f"{counter.get('proposed_duration', 30)} дн.)."
            ),
            type_key="counter_offer_rejected",
            priority="warning",
            payload={
                "kind": "counter_offer_rejected",
                "counter_offer_id": counter_id,
                "original_offer_id": counter.get("original_offer_id"),
            },
        )
    except Exception as _e:
        logger.warning(f"counter_offer rejected notify failed: {_e}")

    return {"success": True, "message": "Встречное предложение отклонено"}


@api_router.post("/alliances/counter-offer/{counter_id}/hide")
async def hide_counter_offer(counter_id: str, current_user: User = Depends(get_current_user)):
    """Hide a counter-offer (patron can hide instead of reject)"""
    ui = await get_user_identifiers(current_user)
    user_id = ui["primary_id"]
    await db.users.update_one({"id": user_id}, {"$addToSet": {"hidden_counter_offers": counter_id}})
    return {"success": True, "message": "Скрыто"}



# ==================== TRADE OPERATIONS (COOPERATION) ====================

@api_router.get("/my/trade-operations")
async def get_my_trade_operations(current_user: User = Depends(get_current_user)):
    """Get user's trade operations history + shared warehouse info"""
    ui = await get_user_identifiers(current_user)
    if not ui["user"]:
        return {"operations": {"bought": {}, "sold": {}}, "warehouse": {"capacity": 0, "used": 0, "items": {}}}
    
    user = ui["user"]
    user_id = user.get("id", str(user.get("_id")))
    
    # Get all businesses to calculate shared warehouse
    businesses = await db.businesses.find(
        get_businesses_query(ui["ids"]),
        {"_id": 0}
    ).to_list(100)
    
    # Calculate shared warehouse
    total_capacity = 0
    total_used = 0
    all_items = {}
    
    # ONE warehouse rule (core/warehouse.py): the player's real stock + active listings
    from core import warehouse as _wh
    _w = await _wh.user_warehouse(db, user, businesses=businesses)
    total_capacity, total_used = int(_w["capacity"]), int(_w["used"])
    all_items = {k: int(float(v)) for k, v in (user.get("resources") or {}).items() if float(v or 0) >= 1}
    
    # Get purchase/sale transactions
    user_ids_list = list(ui["ids"])
    
    bought = {}
    sold = {}
    
    # Purchases (buyer)
    buy_txs = await db.transactions.find(
        {"tx_type": "market_purchase", "$or": [{"from_address": {"$in": user_ids_list}}, {"buyer_id": {"$in": user_ids_list}}]},
        {"_id": 0}
    ).sort("created_at", -1).to_list(200)
    
    for tx in buy_txs:
        rt = tx.get("resource_type", "unknown")
        bought[rt] = bought.get(rt, 0) + int(tx.get("resource_amount", 0))
    
    # Sales (seller)
    sell_txs = await db.transactions.find(
        {"tx_type": "market_purchase", "$or": [{"to_address": {"$in": user_ids_list}}, {"seller_id": {"$in": user_ids_list}}]},
        {"_id": 0}
    ).sort("created_at", -1).to_list(200)
    
    for tx in sell_txs:
        rt = tx.get("resource_type", "unknown")
        sold[rt] = sold.get(rt, 0) + int(tx.get("resource_amount", 0))
    
    # Also count from market listings
    sold_listings = await db.market_listings.find(
        {"seller_id": {"$in": user_ids_list}, "status": "sold"},
        {"_id": 0}
    ).to_list(200)
    
    for listing in sold_listings:
        rt = listing.get("resource_type", "unknown")
        # Only count if not already counted in transactions
        if rt not in sold:
            sold[rt] = 0
    
    # Calculate overflow
    overflow = max(0, total_used - total_capacity)
    spoilage_per_day = int(overflow * 0.5) if overflow > 0 else 0
    
    return {
        "operations": {
            "bought": bought,
            "sold": sold,
        },
        "warehouse": {
            "capacity": total_capacity,
            "used": total_used,
            "items": all_items,
            "overflow": overflow,
            "spoilage_per_day": spoilage_per_day,
            "is_overflowing": overflow > 0,
        }
    }


class ResourceListingRequest(BaseModel):
    resource_type: str
    amount: int  # Must be integer
    price_per_unit: float


@api_router.post("/market/list-resource")
async def list_resource_for_sale(data: ResourceListingRequest, current_user: User = Depends(get_current_user)):
    """Выставить ресурсы на продажу (из ресурсов пользователя)"""
    # Tutorial-reward variants (`<res>_tutorial`) are never sellable.
    if isinstance(data.resource_type, str) and data.resource_type.endswith("_tutorial"):
        raise HTTPException(
            status_code=400,
            detail="Этот ресурс получен за обучение и не подлежит продаже",
        )

    # Validate integer amount
    amount = int(data.amount)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Количество должно быть больше 0")
    
    # Tier 1 resources: only multiples of 10
    tier1_resources = ["energy", "scrap", "quartz", "cu", "traffic", "cooling", "biomass"]
    if data.resource_type in tier1_resources and amount % 10 != 0:
        raise HTTPException(status_code=400, detail="Ресурсы первого эшелона продаются только десятками (10, 20, 30...)")

    # Note: T3 resources are tradable (v2.3). The only unit that cannot be
    # sold is the tutorial-reward one, which lives under `<res>_tutorial` and
    # is filtered out at the top of this handler.

    # Validate price
    price = round(data.price_per_unit, 6)
    if price < 0.0001:
        raise HTTPException(status_code=400, detail="Слишком низкая цена")
    
    # Get user
    ui = await get_user_identifiers(current_user)
    user = ui["user"]
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    # No-business players CAN sell resources (v2.3): T3 tutorial-reward lives
    # in a separate `<res>_tutorial` slot and is not counted here, so the
    # sellable pool is naturally the non-tutorial stock.

    user_id = user.get("id", str(user.get("_id")))

    # Level-0 (test-business) sellers can ONLY sell at the fixed system price.
    import zero_business as _zb
    _lr_keys = await resolve_owner_keys(db, user_id)
    if await _zb.has_zero_business(db, _lr_keys):
        price = await _system_level0_price_ton(data.resource_type)

    # V4: Slot limit = real-business count + trade_attache bonus. Tutorial
    # businesses excluded (they are not real). No-business players get 1 slot.
    _list_create_keys = await resolve_owner_keys(db, user_id)
    _list_create_query = owner_businesses_query(_list_create_keys)
    user_businesses = await db.businesses.find(
        _list_create_query,
        {"_id": 0, "id": 1, "patron_id": 1, "contract_id": 1, "contract_buff": 1, "tutorial": 1},
    ).to_list(100)
    real_businesses = [b for b in user_businesses if not b.get("tutorial")]
    business_count = len(real_businesses)
    trade_attache_bonus = 0
    for biz in real_businesses:
        contract_doc = None
        if biz.get("contract_id"):
            contract_doc = await db.contracts.find_one(
                {"id": biz["contract_id"], "status": "active"}, {"_id": 0}
            )
        patron_doc = None
        if biz.get("patron_id"):
            patron_doc = await db.businesses.find_one({"id": biz["patron_id"]}, {"_id": 0})
        buff = resolve_business_buff(biz, contract_doc, patron_doc)
        if buff and buff.get("id") == "trade_attache":
            trade_attache_bonus += 1
    max_listings = business_count + trade_attache_bonus
    # v2.3: guarantee at least 1 listing slot even for no-business sellers
    # (so T3 traders and trash-pile drop sellers can list a lot).
    if max_listings < 1:
        max_listings = 1
    existing_listings = await db.market_listings.count_documents({"seller_id": user_id, "status": "active"})
    if existing_listings >= max_listings:
        raise HTTPException(
            status_code=400,
            detail=f"Лимит: {max_listings} активных листингов на продажу ресурсов. "
                   "Снимите текущий листинг перед созданием нового."
        )

    # Check user's global resources (tutorial-reward slot `<res>_tutorial`
    # lives under a separate key and is intentionally NOT counted here).
    user_resources = user.get("resources", {})
    total_available = int(user_resources.get(data.resource_type, 0))
    
    if total_available < amount:
        # Translate resource name for error message
        res_name = data.resource_type
        for biz_key, biz_val in BUSINESSES.items():
            if biz_val.get("produces") == data.resource_type:
                name_obj = biz_val.get("name", {})
                if isinstance(name_obj, dict):
                    res_name = name_obj.get("ru", data.resource_type)
                break
        raise HTTPException(status_code=400, detail=f"Недостаточно ресурсов. Доступно: {total_available}")

    # Attribute the listing to one of seller's businesses that produces this resource
    # (run BEFORE deducting resources so we never deduct on a failed flow).
    # Priority: business with an active tax_haven contract (so the patron levy is
    # actually applied on sale and matches UI). Falls back to any matching business.
    attributed_biz_id = None
    try:
        matching_bizs = await db.businesses.find(
            _list_create_query,
            {"_id": 0, "id": 1, "business_type": 1, "contract_id": 1}
        ).to_list(100)
        candidates = []
        for biz in matching_bizs:
            bt_cfg = resolve_business_config(biz.get("business_type", "")) or {}
            if bt_cfg.get("produces") == data.resource_type:
                candidates.append(biz)
        for biz in candidates:
            if biz.get("contract_id"):
                c = await db.contracts.find_one(
                    {"id": biz["contract_id"], "status": "active", "type": "tax_haven"},
                    {"_id": 0, "id": 1},
                )
                if c:
                    attributed_biz_id = biz["id"]
                    break
        if not attributed_biz_id and candidates:
            attributed_biz_id = candidates[0]["id"]
    except Exception as e:
        logger.warning(f"list-resource attribution failed: {e}")
        attributed_biz_id = None
    
    # Deduct resources from user (they remain "on listing" — still occupy warehouse slots
    # via active-listing aggregation in /my/businesses, but no longer show on business page).
    await db.users.update_one(
        get_user_filter(user),
        {"$inc": {f"resources.{data.resource_type}": -amount}}
    )

    # Create listing
    listing = {
        "id": str(uuid.uuid4()),
        "seller_id": user_id,
        "seller_email": user.get("email"),
        "seller_username": user.get("username") or current_user.display_name,
        "business_id": attributed_biz_id,
        "resource_type": data.resource_type,
        "amount": amount,
        "price_per_unit": price,
        "total_price": round(amount * price, 2),
        "status": "active",
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    await db.market_listings.insert_one(listing.copy())
    
    logger.info(f"Resource listing created: {amount} {data.resource_type} @ {price} TON by {user.get('username')}")
    # Daily activity: listing resources for sale counts as the seller's sell action.
    await bump_daily_trade(user, sold=amount)

    # Estimate how much of this potential sale would be withheld for credit
    # repayment, so the frontend can warn the seller.
    credit_estimate = await estimate_credit_deduction(
        db,
        user_id,
        listing["total_price"],
        seller_wallet=user.get("wallet_address"),
    )

    quest_engine.fire(user_id, "market_list", 1, unique=f"lot:{listing.get('id')}")
    return {"status": "listed", "listing": listing, "credit_estimate": credit_estimate}


@api_router.post("/market/cancel/{listing_id}")
async def cancel_listing(listing_id: str, current_user: User = Depends(get_current_user)):
    """Отменить листинг и вернуть ресурсы"""
    listing = await db.market_listings.find_one({"id": listing_id, "status": "active"}, {"_id": 0})
    
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    
    # Get user
    user = None
    if current_user.wallet_address:
        user = await db.users.find_one({"id": current_user.id}, {"_id": 0})
    if not user and current_user.email:
        user = await db.users.find_one({"id": current_user.id}, {"_id": 0})
    
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    user_id = user.get("id", str(user.get("_id")))
    
    # Check ownership
    if listing.get("seller_id") != user_id and listing.get("seller_email") != user.get("email"):
        raise HTTPException(status_code=403, detail="Not your listing")
    
    # Return resources to user's global resources (resources were deducted at listing time)
    resource_type = listing.get("resource_type")
    amount = listing.get("amount", 0)
    if resource_type and amount > 0:
        await db.users.update_one(
            get_user_filter(user),
            {"$inc": {f"resources.{resource_type}": amount}}
        )
    
    # Mark as cancelled
    await db.market_listings.update_one(
        {"id": listing_id},
        {"$set": {"status": "cancelled", "cancelled_at": datetime.now(timezone.utc).isoformat()}}
    )
    
    return {"status": "cancelled", "listing_id": listing_id}


# ==================== LAND MARKETPLACE ====================

class LandListingRequest(BaseModel):
    plot_id: str
    price: float  # Цена устанавливается продавцом

class BuyLandRequest(BaseModel):
    listing_id: str

@api_router.post("/market/land/list")
async def create_land_listing(data: LandListingRequest, current_user: User = Depends(get_current_user)):
    """Выставить участок земли на продажу"""
    # Получаем участок
    plot = await db.plots.find_one({"id": data.plot_id}, {"_id": 0})
    
    if not plot:
        raise HTTPException(status_code=404, detail="Участок не найден")
    
    # Проверяем владельца (по user.id)
    user = await db.users.find_one({"id": current_user.id}, {"_id": 0})
    user_id = user.get("id", str(user.get("_id")))
    
    if plot.get("owner") != user_id and plot.get("owner") != current_user.wallet_address:
        raise HTTPException(status_code=403, detail="You don't own this plot")
    
    # Проверяем что участок не уже на продаже
    # a business that is rented out can't be listed (the plot stays the owner's during the rental)
    _biz_on_plot = await db.businesses.find_one({"$or": [{"plot_id": data.plot_id}, {"id": plot.get("business_id")}]},
                                                {"_id": 0, "rental_id": 1}) if plot else None
    from rental import assert_not_rented as _anr
    _anr(_biz_on_plot)
    existing = await db.land_listings.find_one({"plot_id": data.plot_id, "status": "active"})
    if existing:
        raise HTTPException(status_code=400, detail="Этот участок уже выставлен на продажу. Сначала отмените текущий листинг.")
    
    # Минимальная цена - 50% от изначальной
    min_price = plot.get("price", 0.1) * 0.5
    if data.price < min_price:
        raise HTTPException(status_code=400, detail=f"Price too low. Minimum: {min_price:.4f} TON")
    
    # Получаем информацию о городе/острова
    city_id = plot.get("city_id") or plot.get("island_id") or "ton_island"
    city = await db.cities.find_one({"id": city_id}, {"_id": 0, "name": 1})
    
    # Handle localized name - default to GRAM Island for island plots
    city_name = "GRAM Island"
    if city:
        name = city.get("name")
        if isinstance(name, dict):
            city_name = name.get("ru") or name.get("en") or "GRAM Island"
        elif isinstance(name, str):
            city_name = name
    elif city_id == "ton_island":
        city_name = "GRAM Island"
    
    # Получаем бизнес на участке (если есть). Учитываем разные схемы хранения координат:
    #   • Плоты-острова (GRAM Island) хранят бизнес с полями `x`/`y` и `island_id`.
    #   • Плоты-города хранят бизнес с полями `plot_x`/`plot_y` и `city_id`.
    #   • Также поддерживаем прямую ссылку через plot.business_id.
    plot_city_id = plot.get("city_id") or plot.get("island_id") or "ton_island"
    business_search_or = [
        {"city_id": plot_city_id, "plot_x": plot.get("x"), "plot_y": plot.get("y")},
        {"island_id": plot_city_id, "plot_x": plot.get("x"), "plot_y": plot.get("y")},
        {"city_id": plot_city_id, "x": plot.get("x"), "y": plot.get("y")},
        {"island_id": plot_city_id, "x": plot.get("x"), "y": plot.get("y")},
        {"plot_id": plot.get("id")},
    ]
    if plot.get("business_id"):
        business_search_or.append({"id": plot.get("business_id")})
    business = await db.businesses.find_one({"$or": business_search_or}, {"_id": 0})
    
    business_info = None
    if business:
        # Считаем связи
        connections_count = len(business.get("connected_businesses", []))
        business_info = {
            "type": business.get("business_type"),
            "level": business.get("level", 1),
            "connections": connections_count,
            "xp": business.get("xp", 0)
        }
    
    listing = {
        "id": str(uuid.uuid4()),
        "plot_id": data.plot_id,
        "city_id": plot.get("city_id") or plot.get("island_id") or "ton_island",
        "city_name": city_name,
        "x": plot.get("x"),
        "y": plot.get("y"),
        "seller_id": user.get("id") or current_user.id,
        "seller_wallet": current_user.wallet_address,
        "seller_username": user.get("username") or user.get("display_name", "Anonymous"),
        "original_price": plot.get("price", 0),
        "price": data.price,
        "business": business_info,
        "status": "active",
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    await db.land_listings.insert_one(listing.copy())
    
    # Mark plot as on_sale
    await db.plots.update_one(
        {"id": data.plot_id},
        {"$set": {"on_sale": True, "listing_id": listing["id"]}}
    )
    
    # If there's a business, mark it as on_sale too
    if business:
        await db.businesses.update_one(
            {"id": business.get("id")},
            {"$set": {"on_sale": True, "listing_id": listing["id"], "status": "on_sale"}}
        )
        # V6: T3 on sale → pause its open alliance offers (vassals lose the buff via on_sale check)
        biz_cfg_for_pause = BUSINESSES.get(business.get("business_type", ""), {})
        if biz_cfg_for_pause.get("tier", 1) == 3:
            await db.alliance_offers.update_many(
                {"patron_business_id": business.get("id"), "status": "open"},
                {"$set": {
                    "status": "paused",
                    "paused_reason": "patron_on_sale",
                    "paused_at": datetime.now(timezone.utc).isoformat(),
                }}
            )
    
    logger.info(f"Land listing created: plot {data.plot_id} @ {data.price} TON by {current_user.username}")

    # Estimate credit deduction for this prospective sale (post-tax estimate)
    credit_estimate = await estimate_credit_deduction(
        db,
        user.get("id"),
        data.price,
        seller_wallet=current_user.wallet_address,
    )

    return {"status": "listed", "listing": listing, "credit_estimate": credit_estimate}

@api_router.get("/market/land/listings")
async def get_land_listings(city_id: str = None, sort_by: str = "price", has_business: bool = None):
    """Получить все активные предложения земли"""
    query = {"status": "active"}
    
    if city_id:
        query["city_id"] = city_id
    
    if has_business is not None:
        if has_business:
            query["business"] = {"$ne": None}
        else:
            query["business"] = None
    
    sort_field = "price" if sort_by == "price" else "created_at"
    sort_order = 1 if sort_by == "price" else -1
    
    listings = await db.land_listings.find(query, {"_id": 0}).sort(sort_field, sort_order).to_list(100)
    await _enrich_seller_usernames(listings)
    
    return {"listings": listings, "total": len(listings)}

@api_router.post("/market/land/buy")
async def buy_land_from_market(data: BuyLandRequest, current_user: User = Depends(get_current_user)):
    """Купить участок земли с маркетплейса"""
    listing = await db.land_listings.find_one({"id": data.listing_id, "status": "active"}, {"_id": 0})
    
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found or no longer active")
    
    # Check if buyer is trying to buy their own listing (compare by user ID)
    buyer = await db.users.find_one({"$or": [
        {"wallet_address": current_user.wallet_address} if current_user.wallet_address else {"_id": None},
        {"id": current_user.id}
    ]}, {"_id": 0})
    
    if not buyer:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    buyer_id = buyer.get("id") or current_user.id
    
    # Check both seller_id and seller_user_id (for backward compatibility)
    seller_id = listing.get("seller_id") or listing.get("seller_user_id")
    if seller_id == buyer_id or (current_user.wallet_address and seller_id == current_user.wallet_address):
        raise HTTPException(status_code=400, detail="Нельзя купить свой собственный листинг")

    # ── Level-0 (застолблённый) business lot ──────────────────────────────
    # Buyer pays real TON → ADMIN, receives a normal level-1 business (empty
    # storage). Old owner loses it (can claim again) and gets a localized notice.
    if listing.get("is_zero_business"):
        import zero_business as _zb
        _buyer_ids = {buyer.get("id"), buyer.get("wallet_address"), buyer.get("email")}
        if await _zb.has_zero_business(db, _buyer_ids):
            raise HTTPException(status_code=423, detail="Пока у вас есть бизнес 0 уровня, покупки недоступны. Прокачайте его до 1 уровня.")
        price = float(listing.get("price", 0) or 0)
        # ── Race-safe: claim the listing atomically (active→processing) so two
        # buyers can't both take the same Level-0 lot. ──
        _claim = await db.land_listings.find_one_and_update(
            {"id": data.listing_id, "status": "active"},
            {"$set": {"status": "processing"}},
        )
        if not _claim:
            raise HTTPException(status_code=409, detail="LISTING_SOLD")
        _upd_b = await db.users.find_one_and_update(
            {"id": buyer_id, "balance_ton": {"$gte": price}},
            {"$inc": {"balance_ton": -price}},
            return_document=ReturnDocument.AFTER,
            projection={"_id": 0, "balance_ton": 1},
        )
        if not _upd_b:
            await db.land_listings.update_one({"id": data.listing_id}, {"$set": {"status": "active"}})
            raise HTTPException(status_code=400, detail="Недостаточно средств")
        biz_id = listing.get("business_id")
        # Atomically take the business ONLY while it is still Level-0. If the
        # staker upgraded it 0→1 at the same moment, this returns None → the
        # staker wins, the buyer is refunded and told the lot is already sold.
        biz = await db.businesses.find_one_and_update(
            {"id": biz_id, "level": 0},
            {"$set": {"owner": buyer_id, "owner_wallet": current_user.wallet_address,
                      "owner_username": buyer.get("username"), "level": 1, "on_sale": False},
             "$unset": {"is_zero_business": "", "zero_map_price": "", "zero_listing_id": "", "listing_id": "", "lease_ton_bonus": ""}},
        )
        if not biz:
            await db.users.update_one({"id": buyer_id}, {"$inc": {"balance_ton": price}})
            await db.land_listings.update_one({"id": data.listing_id}, {"$set": {"status": "active"}})
            raise HTTPException(status_code=409, detail="LISTING_SOLD")
        old_owner_id = biz.get("owner")
        old_owner = await db.users.find_one(
            {"$or": [{"id": old_owner_id}, {"wallet_address": old_owner_id}]}, {"_id": 0}
        )
        # Reclaim the tier-3 lease welcome bonus from the former owner — the lease
        # ended (bought by another player) without them buying it out to level 1.
        try:
            await _zb.clawback_lease_bonus(db, old_owner_id, biz)
        except Exception:
            pass
        from business_config import get_storage_capacity as _gsc
        await db.businesses.update_one(
            {"id": biz_id},
            {"$set": {"owner": buyer_id, "owner_wallet": current_user.wallet_address,
                      "owner_username": buyer.get("username"), "level": 1,
                      "storage.items": {}, "storage.capacity": _gsc(biz.get("business_type"), 1), "on_sale": False},
             "$unset": {"is_zero_business": "", "zero_map_price": "", "zero_listing_id": "", "listing_id": "", "lease_ton_bonus": ""}}
        )
        await db.plots.update_one(
            {"id": listing.get("plot_id")},
            {"$set": {"owner": buyer_id, "owner_username": buyer.get("username"),
                      "business.level": 1, "business.owner": buyer_id},
             "$unset": {"on_sale": "", "listing_id": "", "business.is_zero_business": "", "business.zero_listing_id": ""}}
        )
        if old_owner_id:
            await db.users.update_one(
                {"$or": [{"id": old_owner_id}, {"wallet_address": old_owner_id}]},
                {"$pull": {"plots_owned": listing.get("plot_id"), "businesses_owned": biz_id}},
            )
        await db.users.update_one(
            {"id": buyer_id},
            {"$addToSet": {"plots_owned": listing.get("plot_id"), "businesses_owned": biz_id},
             "$set": {"is_active_investor": True}},
        )
        await db.admin_stats.update_one(
            {"type": "treasury"},
            {"$inc": {"zero_business_income": price}}, upsert=True,
        )
        await db.land_listings.update_one(
            {"id": data.listing_id},
            {"$set": {"status": "sold", "buyer_id": buyer_id, "sold_at": datetime.now(timezone.utc).isoformat()}},
        )
        await _zb.notify_zero_bought(db, old_owner, uuid, datetime, timezone, manager)
        return {"status": "purchased", "plot_id": listing.get("plot_id"),
                "total_paid": price, "level": 1, "is_zero_business": True,
                "new_balance": _upd_b.get("balance_ton", 0)}
    
    # Проверяем баланс покупателя (исключая заморозку по контрактам)
    from core.balance import total_available_ton as _tat
    if _tat(buyer) + 1e-9 < listing["price"]:
        raise await _insufficient_funds(buyer, listing["price"])
    
    # Проверяем лимит участков (максимум 3)
    buyer_ids = [buyer_id]
    if current_user.wallet_address:
        buyer_ids.append(current_user.wallet_address)
    
    # Determine privileges: only admins bypass limits
    is_admin = bool(buyer.get("is_admin", False)) or buyer.get("role") == "ADMIN"
    
    # Count owned plots
    owned_plots_count = await db.plots.count_documents({
        "$or": [{"owner": uid} for uid in buyer_ids],
        "on_sale": {"$ne": True}
    })
    
    # Also count from island cells
    island = await db.islands.find_one({"id": "ton_island"})
    if island and 'cells' in island:
        for cell in island['cells']:
            if cell.get('owner') in buyer_ids and not cell.get('on_sale'):
                owned_plots_count += 1
    
    MAX_PLOTS_PER_USER = 3
    if not is_admin and owned_plots_count >= MAX_PLOTS_PER_USER:
        raise HTTPException(status_code=400, detail=f"У вас уже лимит участков ({MAX_PLOTS_PER_USER}). Продайте один из участков чтобы купить новый.")
    
    # Business-specific limits: max 3 total, max 1 Tier-3 (admins bypass)
    listing_business = listing.get("business") or {}
    listing_business_type = listing_business.get("type") if isinstance(listing_business, dict) else None
    if listing_business_type:
        from core.helpers import check_business_purchase_limits as _cbpl
        ok, err = await _cbpl(db, buyer, set(buyer_ids), listing_business_type)
        if not ok:
            raise HTTPException(status_code=400, detail=err)
    
    # Налог с продавца - используем сохранённую сумму из листинга (рассчитана по тиру при листинге)
    # Fallback: если listing.tax_amount не задан, считаем по тиру из текущих настроек
    if listing.get("tax_amount") is not None and listing.get("seller_receives") is not None:
        seller_tax = listing["tax_amount"]
        seller_receives = listing["seller_receives"]
    else:
        tax_settings = await db.admin_settings.find_one({"type": "tax_settings"}, {"_id": 0})
        biz_info = listing.get("business", {})
        biz_type = biz_info.get("type") if biz_info else None
        biz_tier = 1
        if biz_type:
            cfg = resolve_business_config(biz_type)
            biz_tier = cfg.get("tier", 1)
        tax_rate = await get_business_sale_tax_rate(tax_settings, biz_tier)
        seller_tax = listing["price"] * tax_rate
        seller_receives = listing["price"] - seller_tax
    
    # ── Правило бонусных средств для покупки БИЗНЕСА ─────────────────────────
    # Бонусным балансом (bonus_balance) можно оплачивать покупку бизнеса на
    # маркетплейсе ТОЛЬКО если у покупателя есть хотя бы 1 бизнес 1-го уровня.
    # Иначе бонус для этой покупки не используется — нужен реальный TON.
    is_business_listing = listing.get("business") is not None
    allow_bonus = True
    if is_business_listing:
        has_level1_business = await db.businesses.count_documents({
            "$or": [{"owner": uid} for uid in buyer_ids],
            "level": {"$gte": 1},
            "is_zero_business": {"$ne": True},
        }) > 0
        if not has_level1_business:
            allow_bonus = False
            from core.balance import total_available_ton as _tat_real
            real_available = _tat_real({**buyer, "bonus_balance": 0.0})
            if real_available + 1e-9 < listing["price"]:
                raise HTTPException(
                    status_code=403,
                    detail="Покупка бизнеса за бонусные средства доступна только игрокам, у которых есть хотя бы один бизнес 1 уровня. Пополните реальный баланс или прокачайте бизнес до 1 уровня.",
                )

    # ── Race-safe: claim the listing atomically (active→processing) FIRST so two
    # buyers can't both purchase the same plot/business. Loser gets LISTING_SOLD. ──
    _land_claim = await db.land_listings.find_one_and_update(
        {"id": data.listing_id, "status": "active"},
        {"$set": {"status": "processing"}},
    )
    if not _land_claim:
        raise HTTPException(status_code=409, detail="LISTING_SOLD")
    # Обновляем баланс покупателя (по id). Atomic compare-and-set.
    # use_bonus зависит от правила выше: без бизнеса 1 ур. бонус не тратится.
    _upd_buyer = await debit_user_split({"id": buyer_id}, listing["price"], use_bonus=allow_bonus)
    if not _upd_buyer.get("ok"):
        await db.land_listings.update_one({"id": data.listing_id}, {"$set": {"status": "active"}})
        raise await _insufficient_funds(buyer, listing["price"])
    new_buyer_balance = _upd_buyer.get("balance_ton", 0)
    
    # Обновляем баланс продавца (по seller_id или seller_user_id).
    # For a SEIZED business the marketplace seller is "GRAM CITY"; the sale
    # proceeds actually belong to the FORMER owner. For a credit-default seizure
    # the outstanding debt is repaid first and only the remainder reaches them.
    is_seized_listing = bool(listing.get("is_seized"))
    seizure_reason = listing.get("seizure_reason")
    former_owner_id = listing.get("former_owner_id")
    seller_id = listing.get("seller_id") or listing.get("seller_user_id")
    seizure_debt_repaid = 0.0
    if is_seized_listing:
        proceeds = seller_receives
        if seizure_reason == "inactivity":
            # Изъятие за неактивность: нулевой бизнес → 100% государству,
            # бизнес 1+ уровня → 30% бывшему владельцу, остальное государству.
            former_level = int(listing.get("former_level", 1) or 0)
            owner_share = 0.0 if former_level <= 0 else round(seller_receives * 0.30, 6)
            state_share = round(max(0.0, seller_receives - owner_share), 6)
            if state_share > 0:
                await db.admin_stats.update_one(
                    {"type": "treasury"},
                    {"$inc": {"seized_inactivity_income": state_share, "total_tax": state_share}},
                    upsert=True,
                )
            if former_owner_id and owner_share > 0:
                await db.users.update_one(
                    {"$or": [{"id": former_owner_id}, {"wallet_address": former_owner_id}]},
                    {"$inc": {"balance_ton": owner_share, "total_income": owner_share}},
                )
        else:
            if seizure_reason == "credit_default" and listing.get("credit_id"):
                _cr = await db.credits.find_one({"id": listing["credit_id"]}, {"_id": 0})
                if _cr:
                    remaining = float(_cr.get("remaining", 0) or 0)
                    repay = min(remaining, proceeds)
                    if repay > 0:
                        await db.credits.update_one({"id": listing["credit_id"]}, {"$set": {
                            "remaining": round(remaining - repay, 6),
                            "paid": round(float(_cr.get("paid", 0) or 0) + repay, 6),
                            "status": "paid" if (remaining - repay) <= 1e-9 else "defaulted",
                        }})
                        seizure_debt_repaid = round(repay, 6)
                        proceeds = round(proceeds - repay, 6)
            if former_owner_id and proceeds > 0:
                await db.users.update_one(
                    {"$or": [{"id": former_owner_id}, {"wallet_address": former_owner_id}]},
                    {"$inc": {"balance_ton": proceeds, "total_income": proceeds}},
                )
    else:
        if seller_id:
            await db.users.update_one(
                {"$or": [{"id": seller_id}, {"wallet_address": seller_id}]},
                {"$inc": {"balance_ton": seller_receives, "total_income": seller_receives}}
            )

    # B2B partner yield commission (credit the seller's B2B partner, if any)
    try:
        from b2b_partners import credit_yield
        if seller_id:
            await credit_yield(db, seller_id, seller_receives)
    except Exception as _e:
        logger.debug(f"b2b yield credit (business/plot sale) failed: {_e}")

    # === CREDIT REPAYMENT: withhold seller's configured % from this sale ===
    # Skipped for seized listings — their proceeds/debt were handled above.
    has_business = listing.get("business") is not None
    credit_total_deducted, credit_details = (0.0, [])
    if not is_seized_listing:
        credit_total_deducted, credit_details = await apply_credit_deduction(
        db,
        seller_id,
        seller_receives,
        seller_wallet=listing.get("seller_wallet"),
        source="business_sale" if has_business else "land_sale",
        context={
            "listing_id": data.listing_id,
            "plot_id": listing.get("plot_id"),
            "x": listing.get("x"),
            "y": listing.get("y"),
            "sale_amount_ton": seller_receives,
        },
    )
    
    # Передаём владение участком
    await db.plots.update_one(
        {"id": listing.get("plot_id")},
        {"$set": {
            "owner": buyer_id,
            "owner_username": buyer.get("username"),
            "owner_avatar": buyer.get("avatar"),
            "purchased_at": datetime.now(timezone.utc).isoformat(),
            "price": listing["price"]
        },
        "$unset": {"on_sale": "", "listing_id": ""}}
    )
    
    # Если есть бизнес - передаём его тоже
    if listing.get("business"):
        plot_city_id = listing.get("city_id") or listing.get("island_id") or "ton_island"
        _biz_set = {
            "owner": buyer_id,
            "owner_wallet": current_user.wallet_address,
            "owner_username": buyer.get("username"),
            # Сбрасываем состояние "на продаже", иначе экономический тик
            # пропускает бизнес (см. background_tasks.py: status == "on_sale")
            # и купленный бизнес не производит и не потребляет ресурсы.
            "status": "active",
            "is_active": True,
            "work_status": "idle",
            "work_status_reason": None,
        }
        _biz_unset = {"on_sale": "", "listing_id": ""}
        # A seized business is sold "restored": durability back to full, seizure
        # flags cleared, idle timer reset (same visible result as a normal sale).
        if is_seized_listing:
            _biz_set.update({
                "durability": 100,
                "work_status": "idle",
                "work_status_reason": None,
                "is_active": True,
                "status": "active",
                "is_seized": False,
                "zero_durability_since": None,
            })
            _biz_unset.update({
                "seizure_reason": "", "seized_at": "", "seizure_price": "", "former_owner": "",
            })
        _biz_match_or = [
            {"city_id": plot_city_id, "plot_x": listing.get("x"), "plot_y": listing.get("y")},
            {"island_id": plot_city_id, "plot_x": listing.get("x"), "plot_y": listing.get("y")},
            {"city_id": plot_city_id, "x": listing.get("x"), "y": listing.get("y")},
            {"island_id": plot_city_id, "x": listing.get("x"), "y": listing.get("y")},
            {"plot_id": listing.get("plot_id")},
        ]
        if listing.get("business_id"):
            _biz_match_or.append({"id": listing.get("business_id")})
        await db.businesses.update_one(
            {"$or": _biz_match_or},
            {"$set": _biz_set, "$unset": _biz_unset}
        )
    
    # Закрываем листинг
    await db.land_listings.update_one(
        {"id": data.listing_id},
        {"$set": {
            "status": "sold",
            "buyer_id": buyer_id,
            "buyer_username": buyer.get("username"),
            "sold_at": datetime.now(timezone.utc).isoformat()
        }}
    )
    
    # Налог в казну
    await db.admin_stats.update_one(
        {"type": "treasury"},
        {"$inc": {"land_market_tax": seller_tax, "total_tax": seller_tax}},
        upsert=True
    )
    
    # Получаем city_name как строку (может быть объектом с en/ru)
    city_name_raw = listing.get("city_name", "GRAM Island")
    if isinstance(city_name_raw, dict):
        city_name_str = city_name_raw.get("ru") or city_name_raw.get("en") or "GRAM Island"
    else:
        city_name_str = city_name_raw or "GRAM Island"
    
    # Determine transaction type based on whether it has business
    tx_type_buyer = "business_purchase" if has_business else "land_purchase"
    tx_type_seller = "business_sale" if has_business else "land_sale"
    
    # Description with business name if applicable
    if has_business:
        business_name = listing.get("business", {}).get("name", "Бизнес")
        description_buyer = f"Покупка бизнеса «{business_name}» на {city_name_str}"
        description_seller = f"Продажа бизнеса «{business_name}» на {city_name_str}"
    else:
        description_buyer = f"Покупка участка [{listing.get('x','?')}, {listing.get('y','?')}] на {city_name_str}"
        description_seller = f"Продажа участка [{listing.get('x','?')}, {listing.get('y','?')}] на {city_name_str}"
    
    # Записываем транзакцию покупателя (отрицательная сумма - расход)
    tx = {
        "id": str(uuid.uuid4()),
        "type": tx_type_buyer,
        "user_id": buyer_id,
        "from_user_id": buyer_id,
        "to_user_id": listing["seller_id"],
        "from_address": current_user.wallet_address,
        "to_address": listing.get("seller_wallet"),
        "amount": -listing["price"],  # Negative - buyer spent money
        "amount_ton": listing["price"],
        "tax": seller_tax,
        "plot_id": listing.get("plot_id"),
        "city_id": listing.get("city_id"),
        "listing_id": data.listing_id,
        "description": description_buyer,
        "status": "completed",
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.transactions.insert_one(tx)
    
    # Also create transaction for seller (положительная сумма - доход)
    seller_tx = {
        "id": str(uuid.uuid4()),
        "type": tx_type_seller,
        "user_id": listing["seller_id"],
        "from_user_id": buyer_id,
        "to_user_id": listing["seller_id"],
        "amount": seller_receives,  # Positive - seller received money
        "amount_ton": seller_receives,
        "tax": seller_tax,
        "plot_id": listing.get("plot_id"),
        "city_id": listing.get("city_id"),
        "listing_id": data.listing_id,
        "description": description_seller,
        "status": "completed",
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.transactions.insert_one(seller_tx)
    
    logger.info(f"Land purchase: plot {listing.get('plot_id')} for {listing['price']} TON")
    
    return {
        "status": "purchased",
        "plot_id": listing.get("plot_id"),
        "city_name": city_name_str,
        "total_paid": listing["price"],
        "seller_received": seller_receives,
        "seller_net_after_credit": round(seller_receives - credit_total_deducted, 6),
        "credit_deducted": credit_total_deducted,
        "credit_details": credit_details,
        "tax": seller_tax,
        "has_business": listing.get("business") is not None,
        "new_balance": new_buyer_balance
    }

@api_router.delete("/market/land/listing/{listing_id}")
async def cancel_land_listing(listing_id: str, current_user: User = Depends(get_current_user)):
    """Отменить листинг земли"""
    listing = await db.land_listings.find_one({"id": listing_id}, {"_id": 0})
    
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    # Seized businesses are force-listed by GRAM CITY — the (former) owner may
    # not delist them from anywhere. Only admin/support can return them.
    if listing.get("is_seized"):
        raise HTTPException(status_code=403, detail="SEIZED_CONTACT_SUPPORT")

    # Level-0 (застолблённый) lots are force-listed and cannot be delisted.
    if listing.get("is_zero_business") or listing.get("locked_delist"):
        raise HTTPException(status_code=403, detail="ZERO_BUSINESS_LOCKED")
    
    user = None
    if current_user.wallet_address:
        user = await db.users.find_one({"id": current_user.id}, {"_id": 0})
    if not user and current_user.email:
        user = await db.users.find_one({"id": current_user.id}, {"_id": 0})
    if not user:
        user = await db.users.find_one({"id": current_user.id}, {"_id": 0})
    
    user_id = user.get("id") if user else current_user.id
    
    # Проверяем владение по всем возможным идентификаторам
    seller_id = listing.get("seller_id")
    seller_wallet = listing.get("seller_wallet")
    seller_user_id = listing.get("seller_user_id")
    
    is_owner = (
        seller_id == user_id or 
        seller_wallet == current_user.wallet_address or
        seller_user_id == user_id or
        seller_id == current_user.wallet_address
    )
    
    if not is_owner:
        raise HTTPException(status_code=403, detail="Not your listing")
    
    await db.land_listings.update_one(
        {"id": listing_id},
        {"$set": {"status": "cancelled", "cancelled_at": datetime.now(timezone.utc).isoformat()}}
    )
    
    # Remove on_sale mark from plot (works in db.plots and in GRAM Island cells)
    await db.plots.update_one(
        {"id": listing.get("plot_id")},
        {"$unset": {"on_sale": "", "listing_id": ""}}
    )
    # Also clear it from the island cell, in case the plot lives only there
    listing_x = listing.get("x")
    listing_y = listing.get("y")
    listing_island_id = listing.get("city_id") or listing.get("island_id") or "ton_island"
    if listing_x is not None and listing_y is not None:
        await db.islands.update_one(
            {"id": listing_island_id, "cells.x": listing_x, "cells.y": listing_y},
            {"$unset": {"cells.$.on_sale": "", "cells.$.listing_id": ""}}
        )
    
    # Remove on_sale mark from business if exists
    if listing.get("business"):
        # Try to find business by business_id first
        business_id = listing.get("business_id")
        if business_id:
            await db.businesses.update_one(
                {"id": business_id},
                {"$unset": {"on_sale": "", "listing_id": ""}, "$set": {"status": "working"}}
            )
            # V6: resume previously paused alliance offers (only those paused for on_sale)
            await db.alliance_offers.update_many(
                {
                    "patron_business_id": business_id,
                    "status": "paused",
                    "paused_reason": "patron_on_sale",
                },
                {"$set": {"status": "open"}, "$unset": {"paused_reason": "", "paused_at": ""}}
            )
        else:
            # Fallback to coordinates
            plot_city_id = listing.get("city_id") or "ton_island"
            await db.businesses.update_one(
                {"$or": [
                    {"city_id": plot_city_id, "x": listing.get("x"), "y": listing.get("y")},
                    {"island_id": plot_city_id, "x": listing.get("x"), "y": listing.get("y")}
                ]},
                {"$unset": {"on_sale": "", "listing_id": ""}, "$set": {"status": "working"}}
            )
    
    return {"status": "cancelled", "listing_id": listing_id}

@api_router.get("/market/land/my-listings")
async def get_my_land_listings(current_user: User = Depends(get_current_user)):
    """Получить свои листинги земли"""
    # Находим пользователя по разным идентификаторам
    user = None
    if current_user.wallet_address:
        user = await db.users.find_one({"id": current_user.id}, {"_id": 0})
    if not user and current_user.email:
        user = await db.users.find_one({"id": current_user.id}, {"_id": 0})
    if not user:
        user = await db.users.find_one({"id": current_user.id}, {"_id": 0})
    
    user_id = user.get("id") if user else current_user.id
    
    # Ищем листинги по всем возможным идентификаторам продавца
    or_conditions = [{"seller_id": user_id}]
    if current_user.wallet_address:
        or_conditions.append({"seller_id": owner_key(current_user)})
        or_conditions.append({"seller_wallet": current_user.wallet_address})
    if user and user.get("id"):
        or_conditions.append({"seller_user_id": user.get("id")})
    
    listings = await db.land_listings.find(
        {"$or": or_conditions},
        {"_id": 0}
    ).sort("created_at", -1).to_list(50)
    await _enrich_seller_usernames(listings)
    
    return {"listings": listings}


# ==================== BUSINESS SALE API ====================

class SellBusinessRequest(BaseModel):
    price: float  # Цена устанавливается продавцом

class CalculateSaleTaxRequest(BaseModel):
    price: float
    business_id: Optional[str] = None

async def get_business_sale_tax_rate(tax_settings: dict, tier: int) -> float:
    """Возвращает ставку налога по тиру бизнеса из настроек админа"""
    if not tax_settings:
        return 0.10
    if tier == 1:
        return tax_settings.get("small_business_tax", 15) / 100
    elif tier == 2:
        return tax_settings.get("medium_business_tax", 23) / 100
    elif tier == 3:
        return tax_settings.get("large_business_tax", 30) / 100
    return tax_settings.get("land_business_sale_tax", 10) / 100


REFERRAL_RATE = 0.05  # 5% of the trade total is diverted to the seller's referrer


async def _resolve_referral_source_to_bonus(source_business_id):
    """Decide the destination balance for a referral cut based on the level of
    the SELLER's (referral's) source business — the one whose resource was sold.
      • level 0 (staked / not upgraded) OR business missing → BONUS balance
      • level >= 1                                          → REAL balance
    The referrer's own business level is irrelevant. Returns True when the cut
    must go to the referrer's BONUS balance."""
    src_level = None
    if source_business_id:
        try:
            _biz = await db.businesses.find_one({"id": source_business_id}, {"_id": 0, "level": 1})
            if _biz is not None:
                src_level = int(_biz.get("level", 0) or 0)
        except Exception:
            src_level = 0
    # No business found → bonus (per product rule).
    return (src_level is None) or (src_level <= 0)


async def apply_referral_tax_split(seller_doc, total_cost, seller_tax, source_business_id=None):
    """If the seller has a referrer, divert 5% of the trade total (capped to the
    collected tax) to the referrer. The DESTINATION depends on the level of the
    seller's (referral's) SOURCE business (see _resolve_referral_source_to_bonus):
      • level 0 / no business → referrer's BONUS balance (bonus_balance)
      • level >= 1            → referrer's REAL balance (balance_ton)
    The same rule applies to B2B partner referrers.
    Returns (admin_tax, referral_amount, referrer_id, to_bonus)."""
    try:
        referrer_id = (seller_doc or {}).get("referrerId")
        if not referrer_id or seller_tax <= 0:
            return seller_tax, 0.0, None, False

        to_bonus = await _resolve_referral_source_to_bonus(source_business_id)
        balance_field = "bonus_balance" if to_bonus else "balance_ton"
        # Real earnings keep feeding the historical counter; bonus earnings are
        # tracked separately so the two never get mixed up in stats/UI.
        earned_counter = "totalReferralBonusEarned" if to_bonus else "totalEarnedFromReferrals"

        # Point 5: if the referrer is a B2B partner, credit the admin-configured
        # income_percent of the trade to the partner (capped to the collected
        # tax). Same bonus/real destination rule applies.
        try:
            from routes.partner_programs import is_partner_referrer
            program = await is_partner_referrer(db, referrer_id)
        except Exception:
            program = None
        if program:
            pct = float(program.get("income_percent") or 0) / 100.0
            if pct <= 0:
                return seller_tax, 0.0, None, False
            partner_amount = round(min(total_cost * pct, seller_tax), 6)
            if partner_amount <= 0:
                return seller_tax, 0.0, None, False
            upd = await db.users.update_one(
                {"id": referrer_id},
                {"$inc": {balance_field: partner_amount,
                          earned_counter: partner_amount,
                          "b2b_earned_city": partner_amount * 1000.0}},
            )
            if upd.matched_count == 0:
                return seller_tax, 0.0, None, False
            return round(seller_tax - partner_amount, 6), partner_amount, referrer_id, to_bonus
        referral_amount = round(min(total_cost * REFERRAL_RATE, seller_tax), 6)
        if referral_amount <= 0:
            return seller_tax, 0.0, None, False
        upd = await db.users.update_one(
            {"id": referrer_id},
            {"$inc": {balance_field: referral_amount, earned_counter: referral_amount}},
        )
        if upd.matched_count == 0:
            # Referrer no longer exists → the whole tax goes to the admin treasury.
            return seller_tax, 0.0, None, False
        admin_tax = round(seller_tax - referral_amount, 6)
        return admin_tax, referral_amount, referrer_id, to_bonus
    except Exception as e:
        logger.error(f"referral tax split error: {e}")
        return seller_tax, 0.0, None, False


@api_router.post("/business/calculate-sale-tax")
async def calculate_sale_tax(data: CalculateSaleTaxRequest):
    """Рассчитать налог с продажи (показать пользователю перед продажей)"""
    tax_settings = await db.admin_settings.find_one({"type": "tax_settings"}, {"_id": 0})
    
    # Определяем тир бизнеса для корректного налога
    tier = 1
    if data.business_id:
        biz = await db.businesses.find_one({"id": data.business_id}, {"_id": 0, "business_type": 1})
        if biz:
            biz_cfg = resolve_business_config(biz.get("business_type", ""))
            tier = biz_cfg.get("tier", 1)
    
    tax_rate = await get_business_sale_tax_rate(tax_settings, tier)
    
    tax_amount = data.price * tax_rate
    seller_receives = data.price - tax_amount

    # P1.7: compute the minimum allowed price so the UI can show it in both
    # TON and $CITY (1 TON = 1000 $CITY). Mirrors the rule enforced in
    # /business/{id}/sell: min = base_value*0.5 + plot_price*0.5.
    min_price = None
    if data.business_id:
        biz_full = await db.businesses.find_one({"id": data.business_id}, {"_id": 0})
        if biz_full:
            biz_cfg2 = resolve_business_config(biz_full.get("business_type", ""))
            base_value = biz_cfg2.get("base_cost_ton", 5) * biz_full.get("level", 1)
            plot_price = 0.0
            plot_doc = await db.plots.find_one({"id": biz_full.get("plot_id")}, {"_id": 0, "price": 1})
            if plot_doc:
                plot_price = float(plot_doc.get("price", 0) or 0)
            else:
                biz_x = biz_full.get("x") if biz_full.get("x") is not None else biz_full.get("plot_x")
                biz_y = biz_full.get("y") if biz_full.get("y") is not None else biz_full.get("plot_y")
                biz_island = biz_full.get("island_id") or biz_full.get("city_id") or "ton_island"
                if biz_x is not None and biz_y is not None:
                    island_doc = await db.islands.find_one({"id": biz_island}, {"_id": 0, "cells": 1})
                    if island_doc:
                        for c in island_doc.get("cells", []) or []:
                            if c.get("x") == biz_x and c.get("y") == biz_y:
                                plot_price = float(c.get("price_ton") or c.get("price") or 0)
                                break
            min_price = round(base_value * 0.5 + plot_price * 0.5, 4)

    return {
        "price": data.price,
        "tax_rate": tax_rate,
        "tax_rate_percent": f"{tax_rate * 100:.0f}%",
        "tax_amount": round(tax_amount, 4),
        "seller_receives": round(seller_receives, 4),
        "tier": tier,
        "min_price": min_price,
        "min_price_city": round(min_price * 1000, 0) if min_price is not None else None,
    }

@api_router.post("/business/{business_id}/sell")
async def sell_business(business_id: str, data: SellBusinessRequest, current_user: User = Depends(get_current_user)):
    """Выставить бизнес с землёй на продажу"""
    # Получаем бизнес
    business = await db.businesses.find_one({"id": business_id}, {"_id": 0})
    from rental import assert_not_rented as _anr
    _anr(business)                         # a rented business can't be sold
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")
    if int(business.get("level", 1) or 0) == 0:
        raise HTTPException(status_code=403, detail="Бизнес нулевого уровня нельзя продать. Прокачайте его до 1 уровня.")
    
    # Получаем пользователя и все его идентификаторы
    ui = await get_user_identifiers(current_user)
    if not ui["user"]:
        raise HTTPException(status_code=401, detail="User not found")
    
    user = ui["user"]
    user_ids = ui["ids"]
    
    # Проверяем владельца - по всем возможным идентификаторам
    biz_owner = business.get("owner")
    biz_owner_wallet = business.get("owner_wallet")
    
    is_owner = (
        biz_owner in user_ids or
        biz_owner_wallet in user_ids or
        (biz_owner_wallet and biz_owner_wallet == current_user.wallet_address)
    )
    
    if not is_owner:
        raise HTTPException(status_code=403, detail="Это не ваш бизнес")
    
    # Получаем участок: ищем сначала в db.plots, затем в db.islands.cells (GRAM Island)
    plot = await db.plots.find_one({"id": business.get("plot_id")}, {"_id": 0})
    if not plot:
        biz_x = business.get("x") if business.get("x") is not None else business.get("plot_x")
        biz_y = business.get("y") if business.get("y") is not None else business.get("plot_y")
        biz_island = business.get("island_id") or business.get("city_id") or "ton_island"
        if biz_x is not None and biz_y is not None:
            island_doc = await db.islands.find_one({"id": biz_island}, {"_id": 0})
            if island_doc:
                for c in island_doc.get("cells", []) or []:
                    if c.get("x") == biz_x and c.get("y") == biz_y:
                        plot = {
                            "id": business.get("plot_id") or f"island:{biz_island}:{biz_x}:{biz_y}",
                            "x": biz_x,
                            "y": biz_y,
                            "city_id": biz_island,
                            "island_id": biz_island,
                            "owner": c.get("owner"),
                            "price": c.get("price_ton") or c.get("price") or 0,
                            "_island_cell": True,
                        }
                        break
    if not plot:
        raise HTTPException(status_code=404, detail="Участок не найден")
    
    user_id = user.get("id")
    
    # Проверяем что нет активного кредита под залог этого бизнеса
    active_credit = await db.credits.find_one({
        "collateral_business_id": business_id,
        "status": {"$in": ["active", "overdue"]}
    })
    if active_credit:
        raise HTTPException(status_code=400, detail="Нельзя выставить на продажу — сначала погасите кредит по этому бизнесу")
    
    # Проверяем что не на продаже
    existing = await db.land_listings.find_one({
        "plot_id": plot["id"],
        "status": "active"
    })
    if existing:
        raise HTTPException(status_code=400, detail="This property is already listed for sale")
    
    # Минимальная цена
    biz_config = resolve_business_config(business.get("business_type"))
    base_value = biz_config.get("base_cost_ton", 5) * business.get("level", 1)
    min_price = base_value * 0.5 + (plot.get("price", 0) * 0.5)
    
    if data.price < min_price:
        # P1.7: show the minimum in BOTH currencies (1 TON = 1000 $CITY)
        raise HTTPException(
            status_code=400,
            detail=f"Минимальная цена: {min_price:.2f} TON ({min_price * 1000:,.0f} $CITY)".replace(",", " "),
        )
    
    # Рассчитываем налог из админ настроек по тиру бизнеса
    tax_settings = await db.admin_settings.find_one({"type": "tax_settings"}, {"_id": 0})
    biz_tier = biz_config.get("tier", 1)
    tax_rate = await get_business_sale_tax_rate(tax_settings, biz_tier)
    
    tax = data.price * tax_rate
    seller_receives = data.price - tax
    
    # Получаем город
    city = await db.cities.find_one({"id": plot.get("city_id")}, {"_id": 0, "name": 1})
    
    # Handle city name - default to GRAM Island for island plots
    city_name = "GRAM Island"
    if city:
        name = city.get("name")
        if isinstance(name, dict):
            city_name = name.get("ru") or name.get("en") or "GRAM Island"
        elif isinstance(name, str):
            city_name = name
    elif plot.get("city_id") == "ton_island" or plot.get("island_id") == "ton_island":
        city_name = "GRAM Island"
    
    # Создаём листинг
    listing = {
        "id": str(uuid.uuid4()),
        "plot_id": plot["id"],
        "business_id": business_id,
        "city_id": plot.get("city_id") or plot.get("island_id") or "ton_island",
        "city_name": city_name,
        "x": plot.get("x"),
        "y": plot.get("y"),
        "seller_id": owner_key(current_user),
        "seller_user_id": user_id,
        "seller_username": user.get("username", "Anonymous"),
        "price": data.price,
        "tax_amount": round(tax, 4),
        "seller_receives": round(seller_receives, 4),
        "business": {
            "type": business.get("business_type"),
            "level": business.get("level", 1),
            "durability": business.get("durability", 100),
            "xp": business.get("xp", 0),
            "icon": biz_config.get("icon", ""),
            "name": biz_config.get("name", {}),
            "tier": biz_config.get("tier", 1),
            "produces": biz_config.get("produces", ""),
            "production_per_day": get_production(business.get("business_type", ""), business.get("level", 1)),
            "consumes": get_consumption_breakdown(business.get("business_type", ""), business.get("level", 1))
        },
        "original_plot_price": plot.get("price", 0),
        "status": "active",
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    await db.land_listings.insert_one(listing.copy())
    
    # Mark business as on_sale
    await db.businesses.update_one(
        {"id": business_id},
        {"$set": {"on_sale": True, "listing_id": listing["id"], "status": "on_sale"}}
    )
    
    # Mark plot as on_sale (in db.plots if exists, else in island cell)
    if not plot.get("_island_cell"):
        await db.plots.update_one(
            {"id": plot["id"]},
            {"$set": {"on_sale": True, "listing_id": listing["id"]}}
        )
    else:
        await db.islands.update_one(
            {"id": plot.get("island_id") or "ton_island", "cells.x": plot["x"], "cells.y": plot["y"]},
            {"$set": {"cells.$.on_sale": True, "cells.$.listing_id": listing["id"]}}
        )
    
    logger.info(f"Business sale listing created: {business_id} @ {data.price} TON")
    
    return {
        "status": "listed",
        "listing": listing,
        "message": f"После продажи вы получите {seller_receives:.4f} TON (налог {tax:.4f} TON)"
    }


@api_router.get("/business/{business_id}/resource-status")
async def _owner_stock(business: dict) -> dict:
    """The REAL stock of a business owner (user.resources) — the per-business
    storage.items counter is a legacy tally that only grew."""
    owner = business.get("owner")
    if not owner:
        return {}
    u = await db.users.find_one({"$or": [{"id": owner}, {"wallet_address": owner}, {"email": owner}]}, {"_id": 0, "resources": 1})
    return {k: float(v or 0) for k, v in ((u or {}).get("resources") or {}).items()}


async def check_business_resources(business_id: str, current_user: User = Depends(get_current_user)):
    """Проверить статус ресурсов бизнеса"""
    business = await db.businesses.find_one({"id": business_id}, {"_id": 0})
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")
    
    biz_type = business.get("business_type")
    level = business.get("level", 1)
    
    # Доступные ресурсы — настоящий склад владельца (user.resources)
    available_resources = await _owner_stock(business)
    
    # Проверяем требования
    status = check_resource_requirements(biz_type, level, available_resources)
    
    config = BUSINESSES.get(biz_type, {})
    
    return {
        "business_id": business_id,
        "business_type": biz_type,
        "level": level,
        "consumes": config.get("consumes", []),
        "can_operate": status["can_operate"],
        "missing_resources": status["missing"],
        "reason": status["reason"],
        "storage": available_resources
    }


# ==================== WITHDRAWAL ROUTES ====================

@api_router.post("/withdraw")
async def create_withdraw(
    data: WithdrawRequest,
    current_user: User = Depends(get_current_user)
):
    # Search user by wallet_address or email
    user = None
    if current_user.wallet_address:
        user = await db.users.find_one({"id": current_user.id})
    if not user and current_user.email:
        user = await db.users.find_one({"id": current_user.id})
    if not user:
        user = await db.users.find_one({"id": current_user.id})

    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    from core.i18n_messages import wmsg
    _lang = user.get("language") or "en"

    # Check if withdrawal is admin-blocked
    blocked_until = user.get("withdrawal_blocked_until") or user.get("withdraw_lock_until")
    if blocked_until:
        try:
            if isinstance(blocked_until, str):
                bu = datetime.fromisoformat(blocked_until.replace("Z", "+00:00"))
            else:
                bu = blocked_until
            if bu.tzinfo is None:
                bu = bu.replace(tzinfo=timezone.utc)
            if bu > datetime.now(timezone.utc):
                raise HTTPException(status_code=403, detail=wmsg(_lang, "withdrawal_blocked"))
        except HTTPException:
            raise
        except Exception:
            pass
    
    # Check 2FA requirement
    totp_secret = user.get("two_factor_secret") or user.get("totp_secret")
    is_2fa_enabled = user.get("is_2fa_enabled", False)
    # Discover passkeys in the dedicated collection (the `passkeys` array on
    # the user doc is unused by the new security flow).
    passkey_count = await db.passkeys.count_documents({"user_id": user["id"]})
    has_passkey = passkey_count > 0
    has_tg_biometry = bool(user.get("tg_biometry_tokens") and len(user.get("tg_biometry_tokens", [])) > 0)

    if not is_2fa_enabled and not has_passkey and not has_tg_biometry:
        raise HTTPException(status_code=400, detail=wmsg(_lang, "enable_2fa"))

    # Telegram Mini App biometric path — Face ID / fingerprint inside TG.
    # If the client sent a fresh `tg_biometry_token`, verify it. On success
    # we skip the WebAuthn passkey assertion AND the TOTP prompt (biometry
    # already re-authenticated the user on their device).
    tg_bio_ok = False
    if has_tg_biometry and getattr(data, "tg_biometry_token", None):
        from routes.tg_biometry import verify_withdraw_biometry_token
        tg_bio_ok = verify_withdraw_biometry_token(
            data.tg_biometry_token, user["id"], SECRET_KEY, ALGORITHM
        )

    # Telegram PC / Desktop / Web: WebAuthn passkey недоступен в WebView. По
    # ТЗ разрешаем вывод по одному лишь 2FA, если клиент передал свежий
    # initData, подпись валидна и telegram_id совпадает со связанным.
    tg_pc_verified = False
    if getattr(data, "tg_init_data", None):
        try:
            from auth_handler import verify_telegram_init_data
            _bot_token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
            if _bot_token:
                _tg_user = verify_telegram_init_data(data.tg_init_data, _bot_token)
                _linked = str(user.get("telegram_id") or user.get("telegram_user_id") or "")
                if _tg_user and _linked and str(_tg_user.get("id")) == _linked:
                    tg_pc_verified = True
        except Exception:
            tg_pc_verified = False

    # If user has a passkey registered, withdrawal requires a fresh passkey
    # assertion IN ADDITION to the TOTP code (when 2FA on). The frontend
    # obtains `withdraw_pk_token` via /api/security/passkey/withdraw/start
    # and .../verify, and passes it here.
    if has_passkey and not tg_bio_ok and not tg_pc_verified:
        if not data.withdraw_pk_token:
            raise HTTPException(status_code=400, detail="passkey_required")
        # Single-use: pop and check expiry atomically.
        wpk = await db.withdraw_pk_tokens.find_one_and_delete({"_id": data.withdraw_pk_token})
        if not wpk:
            raise HTTPException(status_code=401, detail="passkey_token_invalid")
        if wpk.get("user_id") != user["id"]:
            raise HTTPException(status_code=403, detail="passkey_token_user_mismatch")
        exp = wpk.get("expires_at")
        if exp:
            if isinstance(exp, str):
                try:
                    exp = datetime.fromisoformat(exp.replace("Z", "+00:00"))
                except Exception:
                    exp = None
            if exp and exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp and exp < datetime.now(timezone.utc):
                raise HTTPException(status_code=401, detail="passkey_token_expired")

    # Verify 2FA code if user has TOTP enabled AND biometry did not authorize.
    if is_2fa_enabled and totp_secret and not tg_bio_ok:
        if not data.totp_code:
            raise HTTPException(status_code=400, detail=wmsg(_lang, "enter_2fa"))

        import pyotp
        from security.totp_crypto import decrypt_secret
        totp = pyotp.TOTP(decrypt_secret(totp_secret))
        # Увеличен valid_window до 3 для мобильных устройств с возможной рассинхронизацией времени
        if not totp.verify(data.totp_code.strip() if data.totp_code else "", valid_window=3):
            raise HTTPException(status_code=400, detail=wmsg(_lang, "invalid_2fa"))
    
    # Check if user has a wallet connected
    wallet_address = user.get("wallet_address")
    if not wallet_address:
        raise HTTPException(status_code=400, detail=wmsg(_lang, "connect_wallet"))

    if data.amount <= 0:
        raise HTTPException(status_code=400, detail=wmsg(_lang, "invalid_amount"))

    from frozen_tenders import effective_frozen_city
    frozen_city = await effective_frozen_city(db, user)
    frozen_ton = frozen_city / 1000.0
    balance_ton = float(user.get("balance_ton", 0) or 0)
    available_for_withdraw = max(0.0, balance_ton - frozen_ton)
    if data.amount > available_for_withdraw + 1e-9:
        raise HTTPException(
            status_code=400,
            detail=wmsg(_lang, "insufficient_funds", balance=balance_ton, frozen=frozen_ton, available=available_for_withdraw),
        )

    commission_rate = WITHDRAWAL_COMMISSION
    # Apply withdrawal fee buffs: tax_break (patron, 0.83) × gateway_code (resource, 0.75) — MULTIPLICATIVE
    # Combo: 3% × 0.83 × 0.75 = 1.87% ; solo patron = 2.49% ; solo resource = 2.25%.
    try:
        user_buffs = await get_user_active_buffs_all(user.get("id") or user.get("_id"))
        for b in user_buffs:
            eff = (b or {}).get("effect") or {}
            if eff.get("type") == "withdrawal_fee_multiplier":
                try:
                    commission_rate *= float(eff.get("value", 1.0))
                except (TypeError, ValueError):
                    pass
    except Exception as _e:
        logger.warning(f"withdrawal: buff lookup failed: {_e}")
    commission = round(data.amount * commission_rate, 6)
    net_amount = round(data.amount - commission, 6)

    # Преобразуем адрес в friendly формат для отображения
    raw_address = user.get("raw_address") or wallet_address
    display_address = to_user_friendly(wallet_address) if wallet_address else wallet_address

    withdrawal = {
        "id": str(uuid.uuid4()),
        "type": "withdrawal",  # Correct type for transaction history
        "tx_type": "withdrawal",
        "user_id": user.get("id"),
        "user_username": user.get("username"),
        "user_wallet": wallet_address,
        "user_raw_address": raw_address,
        "to_address": raw_address,
        "to_address_display": display_address,
        "from_address_display": display_address,
        "amount": -data.amount,  # Negative - money leaving account
        "amount_ton": data.amount,
        "commission": commission,
        "net_amount": net_amount,
        "description": f"Вывод {data.amount} TON на {display_address[:12]}...",
        "status": "pending",
        "tx_hash": None,
        "created_at": datetime.now(timezone.utc).isoformat()
    }

    # 🔒 F10 hardening: atomic compare-and-decrement — prevents race-conditions
    # where two parallel /withdraw calls both pass the balance check above.
    # `data.amount` is used both to gate and to decrement, so if another
    # transaction consumed the balance in between, the query returns None
    # and we refuse the withdrawal without deducting anything.
    user_filter = get_user_filter(user)
    updated_user = await db.users.find_one_and_update(
        {**user_filter, "balance_ton": {"$gte": data.amount}},
        {"$inc": {"balance_ton": -data.amount}},
        return_document=ReturnDocument.AFTER,
        projection={"_id": 0, "balance_ton": 1},
    )
    if not updated_user:
        raise HTTPException(status_code=400, detail="Недостаточно средств")
    new_balance = updated_user.get("balance_ton", 0)

    await db.transactions.insert_one({**withdrawal, "tx_type": "withdrawal"})
    
    # Уведомить админа о новой заявке через Telegram
    try:
        bot = get_telegram_bot()
        if bot:
            await bot.notify_admin_new_withdrawal({
                **withdrawal,
                "user_username": user.get("username", "Unknown")
            })
    except Exception as e:
        logger.warning(f"Failed to notify admin about new withdrawal: {e}")
    
    # In-app + telegram notification (user receives confirmation)
    try:
        from core.notify import notify_user
        await notify_user(
            db, user,
            title="📤 Заявка на вывод создана",
            message=(
                f"✅ Ваша заявка на вывод <b>{data.amount:.4f} TON</b> принята.\n\n"
                f"⏳ Вы получите уведомление после обработки администратором."
            ),
            type_key="withdrawal_pending",
            priority="info",
            payload={"tx_id": withdrawal.get("id"), "amount": data.amount},
            add_home_button=True,
            i18n_key="withdrawal_pending",
            i18n_vars={"amount": f"{data.amount:.4f}"},
        )
    except Exception as _e:
        logger.warning(f"withdrawal_pending notify failed: {_e}")

    return {
        "status": "pending",
        "withdrawal_id": withdrawal["id"],
        "net_amount": net_amount,
        "to_address": display_address,
        "to_address_raw": raw_address,
        "new_balance": new_balance
    }

@api_router.post("/admin/withdrawals/{withdraw_id}/reject")
async def reject_withdrawal(
    withdraw_id: str, 
    admin: User = Depends(get_current_admin)
):
    # 1. Ищем заявку
    withdrawal = await db.withdrawals.find_one({"id": withdraw_id})
    
    if not withdrawal:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    
    if withdrawal["status"] != "pending":
        raise HTTPException(status_code=400, detail="Можно отклонить только заявку в статусе pending")

    # 2. ВОЗВРАЩАЕМ ДЕНЬГИ ПОЛЬЗОВАТЕЛЮ
    # Важно: используем поле balance_ton и полную сумму (amount)
    await db.users.update_one(
        {"wallet_address": withdrawal["user_wallet"]},
        {"$inc": {"balance_ton": withdrawal["amount"]}}
    )

    # 3. Обновляем статус заявки
    await db.withdrawals.update_one(
        {"id": withdraw_id},
        {
            "$set": {
                "status": "rejected",
                "rejected_at": datetime.now(timezone.utc).isoformat(),
                "admin_id": str(admin.id)
            }
        }
    )

    # 4. Также обновляем в коллекции транзакций (если используешь её для истории)
    await db.transactions.update_one(
        {"id": withdraw_id},
        {"$set": {"status": "rejected"}}
    )

    return {"status": "success", "msg": "Заявка отклонена, средства возвращены пользователю"}




# ==================== BUSINESS RESOURCE CHECK ====================

@api_router.post("/businesses/check-resources")
async def check_all_business_resources():
    """
    Check all businesses for resource requirements and stop those without resources.
    This should be called by a scheduled task.
    """
    businesses = await db.businesses.find({}, {"_id": 0}).to_list(1000)
    
    stopped = []
    warnings = []
    
    for biz in businesses:
        biz_type = biz.get("business_type")
        level = biz.get("level", 1)
        available = await _owner_stock(biz)                    # the owner's real warehouse
        
        status = check_resource_requirements(biz_type, level, available)
        
        if not status["can_operate"]:
            # Stop the business
            await db.businesses.update_one(
                {"id": biz["id"]},
                {"$set": {
                    "is_active": False,
                    "stopped_reason": "missing_resources",
                    "stopped_at": datetime.now(timezone.utc).isoformat(),
                    "missing_resources": status["missing"]
                }}
            )
            stopped.append({
                "business_id": biz["id"],
                "type": biz_type,
                "missing": status["missing"]
            })
        elif status["missing"]:
            warnings.append({
                "business_id": biz["id"],
                "type": biz_type,
                "low_resources": status["missing"]
            })
    
    return {
        "checked": len(businesses),
        "stopped": len(stopped),
        "warnings": len(warnings),
        "stopped_businesses": stopped,
        "warning_businesses": warnings
    }

@api_router.post("/business/{business_id}/restart")
async def restart_business(business_id: str, current_user: User = Depends(get_current_user)):
    """Restart a stopped business after resources are added"""
    business = await db.businesses.find_one({"id": business_id}, {"_id": 0})
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")
    
    # Check ownership
    user = await db.users.find_one({"id": current_user.id}, {"_id": 0})
    user_id = user.get("id")
    
    if business.get("owner") != user_id and business.get("owner") != current_user.wallet_address:
        raise HTTPException(status_code=403, detail="Not your business")
    
    # Check resources again — the owner's real warehouse
    available = await _owner_stock(business)
    status = check_resource_requirements(business.get("business_type"), business.get("level", 1), available)
    
    if not status["can_operate"]:
        raise HTTPException(status_code=400, detail=f"Still missing resources: {status['missing']}")
    
    # Restart
    await db.businesses.update_one(
        {"id": business_id},
        {"$set": {
            "is_active": True,
            "stopped_reason": None,
            "stopped_at": None,
            "missing_resources": None,
            "restarted_at": datetime.now(timezone.utc).isoformat()
        }}
    )
    
    return {"status": "restarted", "business_id": business_id}


# ==================== WORK SHIFT (8h) ====================
from core.business_rules import SHIFT_DURATION_HOURS  # noqa: E402  (one value for the game)


# The shift rule lives in core/business_rules.py (one copy for the whole game).
from core.business_rules import shift_is_active as _shift_is_active, auto_operates as _auto_operates  # noqa: E402


@api_router.post("/business/{business_id}/start-shift")
async def start_business_shift(business_id: str, current_user: User = Depends(get_current_user)):
    """Start an 8-hour work shift for a single business.

    Fixes the shift start time and begins a countdown. While the shift runs the
    business has status 'active' and produces/wears as usual. Once the timer
    expires the business becomes 'idle' (простаивает) and stops wearing until
    the owner starts a new shift."""
    business = await db.businesses.find_one({"id": business_id}, {"_id": 0})
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    # Only non-empty identifiers: {"wallet_address": None} would match ANY
    # wallet-less user and break the shift for every email-only player.
    _ss_or = [{"id": current_user.id}] + ([{"wallet_address": current_user.wallet_address}] if current_user.wallet_address else [])
    user = await db.users.find_one({"$or": _ss_or}, {"_id": 0})
    user_id = user.get("id") if user else current_user.id

    if business.get("owner") != user_id and business.get("owner") != current_user.wallet_address:
        raise HTTPException(status_code=403, detail="Not your business")

    durability = business.get("durability", 100)
    try:
        durability = float(durability)
    except (ValueError, TypeError):
        durability = 100.0
    if durability <= 0:
        # Frontend maps this code to a localized message.
        raise HTTPException(status_code=400, detail="durability_zero")

    # Resource availability check: a shift cannot start if the owner lacks the
    # input resources the business consumes.
    try:
        biz_type = business.get("business_type", "")
        biz_level = business.get("level", 1)
        consumption = get_consumption_breakdown(biz_type, biz_level) or {}
        user_resources = (user or {}).get("resources", {}) or {}
        for resource, daily_amount in consumption.items():
            needed_for_tick = (float(daily_amount) / 24.0)
            if needed_for_tick > 0 and float(user_resources.get(resource, 0)) < needed_for_tick:
                raise HTTPException(status_code=400, detail="no_resources")
    except HTTPException:
        raise
    except Exception:
        pass

    now = datetime.now(timezone.utc)
    ends_at = now + timedelta(hours=SHIFT_DURATION_HOURS)
    await db.businesses.update_one(
        {"id": business_id},
        {"$set": {
            "shift_started_at": now.isoformat(),
            "shift_ends_at": ends_at.isoformat(),
            # Reset the production / wear clocks so a business that has been idle
            # for a while doesn't get a huge production/wear burst on restart.
            "last_tick": now.isoformat(),
            "last_wear_update": now.isoformat(),
            "is_active": True,
            "work_status": "working",
            "work_status_reason": None,
        }}
    )
    quest_engine.fire(user or current_user.id, "shift_start", 1, unique=f"shift:{business_id}:{now.isoformat()}")
    return {
        "status": "started",
        "business_id": business_id,
        "shift_started_at": now.isoformat(),
        "shift_ends_at": ends_at.isoformat(),
        "shift_active": True,
        "shift_remaining_seconds": SHIFT_DURATION_HOURS * 3600,
        "shift_duration_hours": SHIFT_DURATION_HOURS,
    }


@api_router.get("/i18n/dev-notice")
async def get_dev_notice(lang: str = "ru"):
    """Return the localized 'feature in development' notice.

    Uses the shared translation service (LibreTranslate when configured, with an
    LLM fallback) and caches the result in Mongo so repeat calls are instant."""
    base = "Функция в разработке"
    if not lang or lang == "ru":
        return {"text": base, "lang": "ru"}
    try:
        from translation_service import translate_cached
        text = await translate_cached(db, base, lang, "ru")
    except Exception:
        text = base
    return {"text": text or base, "lang": lang}


# ==================== V2.0 ECONOMIC ENDPOINTS ====================

@api_router.get("/economy/config")
async def get_economy_config():
    """Get full economy configuration for frontend"""
    return {
        "businesses": {
            biz_type: {
                "name": config.get("name", {}),
                "tier": config.get("tier", 1),
                "produces": config.get("produces"),
                "consumes": config.get("consumes", {}),
                "icon": config.get("icon", "🏢"),
                "description": config.get("description", {}),
                "base_cost_ton": config.get("base_cost_ton", 5),
                "is_patron": config.get("is_patron", False),
                "patron_type": config.get("patron_type"),
            }
            for biz_type, config in BUSINESSES.items()
        },
        "resources": RESOURCE_TYPES,
        "resource_types": RESOURCE_TYPES,
        "tier_taxes": TIER_TAXES,
        "turnover_tax": TURNOVER_TAX_RATE,
        "patron_tax": PATRON_TAX_RATE,
        "maintenance_costs": MAINTENANCE_COSTS,
        "warehouse": WAREHOUSE_CONFIG,
        "midnight_decay_rate": MIDNIGHT_DECAY_RATE,
        "npc_price_floor": NPC_PRICE_FLOOR,
        "npc_price_ceiling": NPC_PRICE_CEILING,
        "monopoly_threshold": MONOPOLY_THRESHOLD,
    }


@api_router.get("/economy/business-levels/{business_type}")
async def get_business_levels(business_type: str, lang: str = "ru"):
    """Get production/consumption data for all 10 levels of a business"""
    if business_type not in BUSINESSES:
        raise HTTPException(status_code=404, detail="Business type not found")
    
    config = BUSINESSES[business_type]
    levels_data = BUSINESS_LEVELS.get(business_type, {})
    
    result = {
        "business_type": business_type,
        "name": config.get("name", {}).get(lang, config.get("name", {}).get("en", business_type)),
        "tier": config.get("tier", 1),
        "produces": config.get("produces"),
        "consumes": config.get("consumes", {}),
        "icon": config.get("icon"),
        "levels": {}
    }
    
    for level in range(1, 11):
        stats = get_business_full_stats(business_type, level)
        if stats:
            result["levels"][level] = stats
    
    return result


@api_router.get("/economy/market-prices")
async def get_market_prices():
    """Get current market prices for all resources"""
    prices_doc = await db.market_prices.find_one({"type": "current"})
    if prices_doc:
        return {
            "prices": prices_doc.get("prices", {}),
            "updated_at": prices_doc.get("updated_at"),
        }
    
    # Return base prices if no market data
    base_prices = {r: d["base_price"] for r, d in RESOURCE_TYPES.items()}
    return {"prices": base_prices, "updated_at": None}


@api_router.get("/economy/snapshots")
async def get_economy_snapshots(limit: int = 24):
    """Get recent economic tick snapshots"""
    snapshots = await db.economic_snapshots.find(
        {"type": "tick_snapshot"},
        {"_id": 0}
    ).sort("timestamp", -1).limit(limit).to_list(length=limit)
    return {"snapshots": snapshots}


@api_router.get("/economy/my-resources")
async def get_my_resources(current_user: User = Depends(get_current_user)):
    """Get player's resource inventory"""
    user = await db.users.find_one(
        {"id": current_user.id},
        {"_id": 0}
    )
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    resources = user.get("resources", {})
    balance = user.get("balance_ton", 0)
    
    # Enrich with resource metadata
    enriched = {}
    for resource_type, amount in resources.items():
        meta = RESOURCE_TYPES.get(resource_type, {})
        floored = int(amount)
        if floored <= 0:
            continue
        enriched[resource_type] = {
            "amount": floored,  # floor: only whole units shown to user
            "name_ru": meta.get("name_ru", resource_type),
            "name_en": meta.get("name_en", resource_type),
            "icon": meta.get("icon", "📦"),
            "tier": meta.get("tier", 0),
        }
    
    return {
        "resources": enriched,
        "balance_ton": balance,
        "total_income": user.get("total_income", 0),
    }


@api_router.post("/economy/trade")
async def trade_resource(
    resource: str,
    amount: int,
    price_per_unit: float,
    action: str = "sell",  # "sell" or "buy"
    current_user: User = Depends(get_current_user)
):
    """Trade resources on the market with turnover tax"""
    if resource not in RESOURCE_TYPES:
        raise HTTPException(status_code=400, detail="Invalid resource type")
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")
    if price_per_unit <= 0:
        raise HTTPException(status_code=400, detail="Price must be positive")
    
    user = await db.users.find_one(
        {"id": current_user.id},
        {"_id": 0}
    )
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    total_value = amount * price_per_unit
    turnover_tax = TaxSystem.calculate_turnover_tax(total_value)
    
    if action == "sell":
        # Check if user has enough resources
        current_amount = user.get("resources", {}).get(resource, 0)
        if current_amount < amount:
            raise HTTPException(status_code=400, detail=f"Not enough {resource}: have {current_amount}, need {amount}")
        
        # Check monopoly
        total_on_market = await db.market_orders.count_documents({"resource": resource, "action": "sell"})
        user_orders = await db.market_orders.count_documents({"resource": resource, "action": "sell", "seller": user.get("id") or user.get("wallet_address")})
        market_share = user_orders / max(total_on_market + 1, 1)
        
        monopoly = NPCMarketSystem.check_monopoly(market_share)
        
        # Create sell order
        order = {
            "id": str(uuid.uuid4()),
            "type": "sell",
            "resource": resource,
            "amount": amount,
            "price_per_unit": price_per_unit,
            "total_value": total_value,
            "turnover_tax": turnover_tax["tax"],
            "net_value": turnover_tax["net_amount"],
            "seller": user.get("wallet_address") or user.get("id"),
            "is_monopolist": monopoly["is_monopolist"],
            "market_share": monopoly["market_share"],
            "status": "open",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        
        # Deduct resources from seller
        await db.users.update_one(
            {"_id": user["_id"]},
            {"$inc": {f"resources.{resource}": -amount}}
        )
        
        await db.market_orders.insert_one(order)
        
        # Daily activity: user sold units on the market.
        await bump_daily_trade(user, sold=amount)
        return {
            "order": {k: v for k, v in order.items() if k != "_id"},
            "turnover_tax": turnover_tax,
            "monopoly_warning": monopoly["is_monopolist"],
        }
    
    elif action == "buy":
        # Check balance
        total_cost = total_value + turnover_tax["tax"]
        from core.balance import total_available_ton as _tat
        if _tat(user) + 1e-9 < total_cost:
            raise await _insufficient_funds(user, total_cost)
        
        # Find matching sell orders
        sell_orders = await db.market_orders.find({
            "resource": resource,
            "type": "sell",
            "status": "open",
            "price_per_unit": {"$lte": price_per_unit},
        }).sort("price_per_unit", 1).to_list(10)
        
        bought = 0
        total_spent = 0
        
        for order in sell_orders:
            if bought >= amount:
                break
            
            can_buy = min(amount - bought, order["amount"])
            cost = can_buy * order["price_per_unit"]
            
            bought += can_buy
            total_spent += cost
            
            # Update order
            remaining = order["amount"] - can_buy
            if remaining <= 0:
                await db.market_orders.update_one(
                    {"id": order["id"]},
                    {"$set": {"status": "filled", "filled_at": datetime.now(timezone.utc).isoformat()}}
                )
            else:
                await db.market_orders.update_one(
                    {"id": order["id"]},
                    {"$set": {"amount": remaining}}
                )
            
            # Credit seller
            await db.users.update_one(
                {"$or": [{"wallet_address": order["seller"]}, {"id": order["seller"]}]},
                {"$inc": {"balance_ton": cost * (1 - TURNOVER_TAX_RATE)}}
            )
        
        if bought > 0:
            # Deduct from buyer and add resources
            tax_on_purchase = total_spent * TURNOVER_TAX_RATE
            # F10 hardening: atomic compare-and-set on the buyer debit.
            _rmkt_upd = await debit_user_split({"_id": user["_id"]}, total_spent + tax_on_purchase,
                                               extra_update={"$inc": {f"resources.{resource}": bought}})
            if not _rmkt_upd.get("ok"):
                raise await _insufficient_funds(user, total_spent + tax_on_purchase)
            
            # Treasury gets taxes
            await db.admin_stats.update_one(
                {"type": "treasury"},
                {"$inc": {"total_turnover_tax": tax_on_purchase}},
                upsert=True
            )
            # Daily activity: buyer bought units.
            await bump_daily_trade(user, bought=bought)
        
        return {
            "bought": bought,
            "total_spent": round(total_spent, 6),
            "turnover_tax_paid": round(total_spent * TURNOVER_TAX_RATE, 6),
            "remaining_needed": amount - bought,
        }
    
    raise HTTPException(status_code=400, detail="Invalid action: use 'sell' or 'buy'")


@api_router.get("/economy/npc-status")
async def get_npc_status():
    """Get NPC intervention status and current market health"""
    prices_doc = await db.market_prices.find_one({"type": "current"})
    market_prices = prices_doc.get("prices", {}) if prices_doc else {}
    
    if not market_prices:
        market_prices = {r: d["base_price"] for r, d in RESOURCE_TYPES.items()}
    
    interventions = []
    for resource, price in market_prices.items():
        intervention = NPCMarketSystem.check_price_intervention(resource, price)
        if intervention:
            interventions.append(intervention)
    
    return {
        "market_prices": market_prices,
        "active_interventions": interventions,
        "price_floor": NPC_PRICE_FLOOR,
        "price_ceiling": NPC_PRICE_CEILING,
    }




async def get_income_table(lang: str = "en"):
    """Get income table for all 21 businesses at all 10 levels (V2.0)
    Uses ESTIMATED_DAILY_INCOME for guaranteed profitable display.
    Tier 1 < Tier 2 < Tier 3 guaranteed.
    """
    result = {}
    
    for biz_type, config in BUSINESSES.items():
        name_dict = config.get("name", {})
        biz_name = name_dict.get(lang, name_dict.get("en", biz_type))
        produces = config.get("produces", "")
        tier = config.get("tier", 1)
        tax_rate = TIER_TAXES.get(tier, 0.15)
        
        # Patronage info
        patron_type = config.get("patron_type")
        patron_effect = get_patron_effect(patron_type, 5) if patron_type else None
        
        result[biz_type] = {
            "name": biz_name,
            "icon": config.get("icon", "🏢"),
            "tier": tier,
            "produces": produces,
            "consumes": list(config.get("consumes", {}).keys()),
            "cost": config.get("base_cost_ton", 5),
            "is_patron": config.get("is_patron", False),
            "patron_type": patron_type,
            "patron_effect": patron_effect,
            "levels": {}
        }
        
        for level in range(1, 11):
            stats = get_business_full_stats(biz_type, level)
            if not stats:
                continue
            
            production = stats["production"]["raw"]
            consumption_total = stats["consumption"]["total"]
            consumption_breakdown = stats["consumption"]["breakdown"]
            maintenance = stats["costs"]["maintenance_daily_ton"]
            
            # Use estimated daily income (guaranteed profitable)
            net_daily = get_estimated_daily_income(biz_type, level)
            
            # Reverse-calculate gross and tax from net
            daily_gross = round(net_daily / (1 - tax_rate) + maintenance, 4)
            daily_tax = round(daily_gross * tax_rate, 4)
            monthly = round(net_daily * 30, 2)
            
            # ROI
            build_cost = config.get("base_cost_ton", 5) * (UPGRADE_COST_MULTIPLIER ** (level - 1))
            roi_days = round(build_cost / net_daily, 1) if net_daily > 0 else 999
            
            result[biz_type]["levels"][f"L{level}"] = {
                "level": level,
                "production": production,
                "consumption_total": consumption_total,
                "consumption_breakdown": consumption_breakdown,
                "gross_daily_ton": round(daily_gross, 4),
                "tax_daily_ton": round(daily_tax, 4),
                "maintenance_daily_ton": maintenance,
                "net_daily_ton": round(net_daily, 4),
                "monthly_ton": monthly,
                "roi_days": roi_days,
                "upgrade_cost": stats["costs"]["upgrade"],
                "storage_capacity": stats["storage_capacity"],
                "daily_wear_pct": round(stats["daily_wear"] * 100, 2),
            }
    
    return {"income_table": result}

@api_router.get("/stats/income-table")
async def get_income_table_endpoint(lang: str = "en"):
    """Get income table for all 21 businesses at all 10 levels (V2.0)"""
    return await get_income_table(lang)

# (leaderboard moved to routes/leaderboard.py)


@api_router.get("/wallet-settings/public")
async def get_public_wallet_settings():
    """Get public wallet settings (receiver address for deposits)"""
    settings = await db.game_settings.find_one({"type": "ton_wallet"}, {"_id": 0})
    if not settings:
        return {
            "network": "testnet",
            "receiver_address": "",
            "configured": False
        }
    stored_raw = settings.get("receiver_address", "") or ""
    display = to_user_friendly(stored_raw) or stored_raw
    return {
        "network": settings.get("network", "testnet"),
        "receiver_address": display,
        "receiver_address_raw": stored_raw,
        "configured": bool(stored_raw)
    }

# ==================== TON BLOCKCHAIN ROUTES ====================

@api_router.get("/ton/balance/{address}")
async def get_ton_balance(address: str):
    """Get TON balance for an address"""
    if not validate_ton_address(address):
        raise HTTPException(status_code=400, detail="Invalid TON address")
    
    try:
        balance = await ton_client.get_balance(address)
        return {
            "address": address,
            "balance_ton": balance,
            "balance_nano": int(balance * 1e9)
        }
    except Exception as e:
        logger.error(f"Failed to get balance: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch balance")

@api_router.post("/ton/verify-transaction")
async def verify_ton_transaction(
    tx_hash: str,
    expected_amount: float,
    to_address: str,
    current_user: User = Depends(get_current_user)
):
    """Verify a TON transaction on blockchain"""
    try:
        is_valid = await ton_client.verify_transaction(tx_hash, expected_amount, to_address)
        
        if not is_valid:
            raise HTTPException(status_code=400, detail="Transaction verification failed")
        
        return {
            "valid": True,
            "tx_hash": tx_hash,
            "amount": expected_amount,
            "to_address": to_address,
            "verified_at": datetime.now(timezone.utc).isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Transaction verification error: {e}")
        raise HTTPException(status_code=500, detail="Verification failed")

@api_router.get("/ton/transaction-history/{address}")
async def get_ton_transaction_history(address: str, limit: int = 10):
    """Get transaction history for TON address"""
    if not validate_ton_address(address):
        raise HTTPException(status_code=400, detail="Invalid TON address")
    
    try:
        history = await ton_client.get_transaction_history(address, limit)
        return {"address": address, "transactions": history}
    except Exception as e:
        logger.error(f"Failed to get transaction history: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch history")

# ==================== INCOME COLLECTION ROUTES ====================

@api_router.post("/income/collect-all")
async def collect_all_income(current_user: User = Depends(get_current_user)):  # noqa: F811
    """Collect income from all user's businesses"""
    try:
        businesses = await db.businesses.find({
            "owner": owner_key(current_user),
            "is_active": True,
            "building_progress": {"$gte": 100}
        }).to_list(100)
        
        total_collected = 0
        collected_businesses = []
        
        for business in businesses:
            business_id = business["id"]
            business_type = business["business_type"]
            level = business.get("level", 1)
            connections = len(business.get("connected_businesses", []))
            
            # Get last collection
            last_collection_str = business.get("last_collection")
            last_collection = to_aware(last_collection_str) or datetime.now(timezone.utc)
            
            # Calculate income
            hours_passed = (datetime.now(timezone.utc) - last_collection).total_seconds() / 3600
            days_passed = hours_passed / 24
            
            # Skip if less than 1 hour
            if hours_passed < 1:
                continue
            
            # Get plot zone
            plot = await db.plots.find_one({"id": business["plot_id"]}, {"_id": 0})
            zone = plot.get("zone", "outskirts") if plot else "outskirts"
            
            income_data = calculate_business_income(business_type, level, zone, connections)
            
            gross_income = income_data["gross"] * days_passed
            tax = income_data["tax"] * days_passed
            net_income = income_data["net"] * days_passed
            
            # Update business
            await db.businesses.update_one(
                {"id": business_id},
                {
                    "$set": {"last_collection": datetime.now(timezone.utc).isoformat()},
                    "$inc": {"xp": int(gross_income * 10)}
                }
            )
            
            total_collected += net_income
            collected_businesses.append({
                "business_id": business_id,
                "business_type": business_type,
                "collected": round(net_income, 4),
                "hours_passed": round(hours_passed, 2)
            })
        
        # Update user balance
        if total_collected > 0:
            await db.users.update_one(
                {"id": current_user.id},
                {
                    "$inc": {
                        "balance_ton": total_collected,
                        "total_income": total_collected
                    }
                }
            )
        
        return {
            "total_collected": round(total_collected, 4),
            "businesses_count": len(collected_businesses),
            "businesses": collected_businesses
        }
    except Exception as e:
        logger.error(f"Failed to collect income: {e}")
        raise HTTPException(status_code=500, detail="Failed to collect income")

@api_router.get("/income/pending")
async def get_pending_income(current_user: User = Depends(get_current_user)):
    """Get pending income from all user's businesses without collecting"""
    try:
        businesses = await db.businesses.find({
            "owner": owner_key(current_user),
            "is_active": True,
            "building_progress": {"$gte": 100}
        }).to_list(100)
        
        total_pending = 0
        pending_businesses = []
        
        for business in businesses:
            business_type = business["business_type"]
            level = business.get("level", 1)
            connections = len(business.get("connected_businesses", []))
            
            # Get last collection
            last_collection_str = business.get("last_collection")
            last_collection = to_aware(last_collection_str) or datetime.now(timezone.utc)
            
            # Calculate pending income
            hours_passed = (datetime.now(timezone.utc) - last_collection).total_seconds() / 3600
            days_passed = hours_passed / 24
            
            # Get plot zone
            plot = await db.plots.find_one({"id": business["plot_id"]}, {"_id": 0})
            zone = plot.get("zone", "outskirts") if plot else "outskirts"
            
            income_data = calculate_business_income(business_type, level, zone, connections)
            pending = income_data["net"] * days_passed
            
            total_pending += pending
            pending_businesses.append({
                "business_id": business["id"],
                "business_type": business_type,
                "pending": round(pending, 4),
                "hours_passed": round(hours_passed, 2),
                "income_per_day": income_data["net"]
            })
        
        return {
            "total_pending": round(total_pending, 4),
            "businesses_count": len(pending_businesses),
            "businesses": pending_businesses
        }
    except Exception as e:
        logger.error(f"Failed to get pending income: {e}")
        raise HTTPException(status_code=500, detail="Failed to get pending income")


# ==================== ADMIN ROUTES ====================

# System settings (stored in DB)
async def get_system_settings():
    """Get current system settings from DB"""
    settings = await db.system_settings.find_one({"type": "fees"}, {"_id": 0})
    if not settings:
        # Default settings
        settings = {
            "type": "fees",
            "income_tax": 0.10,  # 10% подоходный налог
            "withdrawal_fee": 0.03,  # 3% комиссия вывода
            "resale_commission": 0.15,  # 15% при перепродаже
            "trade_commission": 0.0,  # 0% торговая комиссия (отменена)
            "min_withdrawal": 1.0
        }
        await db.system_settings.insert_one(settings)
        # Strip Mongo-injected _id so the response stays JSON-serialisable.
        settings.pop("_id", None)
    return settings

class FeeSettingsUpdate(BaseModel):
    income_tax: float = None
    withdrawal_fee: float = None
    resale_commission: float = None
    trade_commission: float = None
    min_withdrawal: float = None

@admin_router.get("/settings/email-2fa")
async def admin_get_email_2fa_setting(admin: User = Depends(get_admin_user)):
    """Read the global email-2FA enforcement flag.

    When `force_all=True`, /api/auth/login will require an email verification code
    for EVERY user regardless of their per-account `is_email_2fa_enabled` flag.
    """
    doc = await db.admin_settings.find_one({"type": "auth_settings"}, {"_id": 0})
    return {"force_all": bool((doc or {}).get("email_2fa_force_all", False))}


class Email2FAToggle(BaseModel):
    force_all: bool


@admin_router.post("/settings/email-2fa")
async def admin_set_email_2fa_setting(
    data: Email2FAToggle, admin: User = Depends(get_admin_user)
):
    """Flip the global email-2FA enforcement flag without code redeploy."""
    await db.admin_settings.update_one(
        {"type": "auth_settings"},
        {"$set": {"email_2fa_force_all": bool(data.force_all)}},
        upsert=True,
    )
    logger.info(
        "Admin %s set email_2fa_force_all = %s",
        admin.username or admin.email,
        data.force_all,
    )
    return {"status": "updated", "force_all": bool(data.force_all)}


@admin_router.get("/settings/telegram-registration")
async def admin_get_tg_registration_setting(admin: User = Depends(get_admin_user)):
    """Read the global Telegram Mini App registration-choice flag.

    When `choice_enabled=True` (default) an unlinked Telegram identity opening
    the Mini App is shown the create/link choice modal. When False the Mini App
    silently registers a fresh account (as if the user tapped "Create new")."""
    doc = await db.admin_settings.find_one({"type": "telegram_registration"}, {"_id": 0})
    enabled = False if not doc or doc.get("choice_enabled") is None else bool(doc.get("choice_enabled"))
    return {"choice_enabled": enabled}


class TgRegistrationToggle(BaseModel):
    choice_enabled: bool


@admin_router.post("/settings/telegram-registration")
async def admin_set_tg_registration_setting(
    data: TgRegistrationToggle, admin: User = Depends(get_admin_user)
):
    """Flip the global Telegram Mini App registration-choice modal on/off."""
    await db.admin_settings.update_one(
        {"type": "telegram_registration"},
        {"$set": {"choice_enabled": bool(data.choice_enabled)}},
        upsert=True,
    )
    logger.info(
        "Admin %s set telegram_registration.choice_enabled = %s",
        admin.username or admin.email, data.choice_enabled,
    )
    return {"status": "updated", "choice_enabled": bool(data.choice_enabled)}
async def admin_get_fee_settings(admin: User = Depends(get_admin_user)):
    """Получить настройки комиссий"""
    settings = await get_system_settings()
    return settings

@admin_router.post("/settings/fees")
async def admin_update_fee_settings(data: FeeSettingsUpdate, admin: User = Depends(get_admin_user)):
    """Обновить настройки комиссий"""
    update_data = {}
    
    if data.income_tax is not None:
        if data.income_tax < 0 or data.income_tax > 0.5:
            raise HTTPException(status_code=400, detail="Налог должен быть от 0% до 50%")
        update_data["income_tax"] = data.income_tax
        
    if data.withdrawal_fee is not None:
        if data.withdrawal_fee < 0 or data.withdrawal_fee > 0.2:
            raise HTTPException(status_code=400, detail="Комиссия вывода должна быть от 0% до 20%")
        update_data["withdrawal_fee"] = data.withdrawal_fee
        
    if data.resale_commission is not None:
        if data.resale_commission < 0 or data.resale_commission > 0.5:
            raise HTTPException(status_code=400, detail="Комиссия перепродажи должна быть от 0% до 50%")
        update_data["resale_commission"] = data.resale_commission
        
    if data.trade_commission is not None:
        if data.trade_commission < 0 or data.trade_commission > 0.2:
            raise HTTPException(status_code=400, detail="Торговая комиссия должна быть от 0% до 20%")
        update_data["trade_commission"] = data.trade_commission
        
    if data.min_withdrawal is not None:
        if data.min_withdrawal < 0.1 or data.min_withdrawal > 100:
            raise HTTPException(status_code=400, detail="Минимальный вывод от 0.1 до 100 TON")
        update_data["min_withdrawal"] = data.min_withdrawal
    
    if update_data:
        await db.system_settings.update_one(
            {"type": "fees"},
            {"$set": update_data},
            upsert=True
        )
        logger.info(f"Admin {admin.username} updated fee settings: {update_data}")
    
    settings = await get_system_settings()
    return {"status": "updated", "settings": settings}

@admin_router.get("/stats")
async def admin_get_stats(admin: User = Depends(get_admin_user)):
    """Get admin statistics"""
    stats = await db.admin_stats.find_one({"type": "treasury"}, {"_id": 0})
    
    # Count by status
    pending_withdrawals = await db.transactions.count_documents({"tx_type": "withdrawal", "status": "pending"})
    total_users = await db.users.count_documents({})
    active_users = await db.users.count_documents({"last_login": {"$gte": (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()}})
    
    # Revenue breakdown
    pipeline = [
        {"$match": {"status": "completed"}},
        {"$group": {
            "_id": "$tx_type",
            "total": {"$sum": "$amount_ton"},
            "count": {"$sum": 1}
        }}
    ]
    revenue_breakdown = await db.transactions.aggregate(pipeline).to_list(20)

    # ---- Online now: users active in the last 5 minutes (web + Telegram) ----
    # Accurate presence is tracked in db.online_presence via the frontend
    # heartbeat (source = 'web' | 'telegram'), plus: live WebSocket connections
    # (web) and Telegram BOT interactions (telegram_mappings.last_activity_at).
    # We keep SEPARATE web/telegram sets and a deduped TOTAL (a user online in
    # both counts once in the total).
    now = datetime.now(timezone.utc)
    online_threshold = now - timedelta(minutes=5)
    online_threshold_iso = online_threshold.isoformat()

    web_users = set()
    tg_users = set()

    # 1) Heartbeat presence (canonical user_id) split by source.
    try:
        async for _p in db.online_presence.find(
            {"last_seen": {"$gte": online_threshold_iso}},
            {"_id": 0, "user_id": 1, "source": 1},
        ):
            _uidp = _p.get("user_id")
            if not _uidp:
                continue
            if _p.get("source") == "telegram":
                tg_users.add(_uidp)
            else:
                web_users.add(_uidp)
    except Exception as _e:
        logger.warning(f"online: presence query failed: {_e}")

    # 2) Live WebSocket connections + legacy in-memory heartbeat → web.
    try:
        web_users.update(manager.active_connections.keys())
    except Exception:
        pass
    _stale = []
    for _uid_key, _last_time in list(last_activity.items()):
        lt = _last_time
        if isinstance(lt, str):
            try:
                lt = datetime.fromisoformat(lt.replace('Z', '+00:00'))
            except Exception:
                _stale.append(_uid_key); continue
        if getattr(lt, 'tzinfo', None) is None:
            lt = lt.replace(tzinfo=timezone.utc)
        if lt > online_threshold:
            web_users.add(_uid_key)
        else:
            _stale.append(_uid_key)
    for _k in _stale:
        online_users.discard(_k)
        last_activity.pop(_k, None)

    # 3) Telegram BOT activity in the last 5 min → telegram, resolved to the
    #    linked account id so it dedupes against web/heartbeat presence.
    tg_chat_ids = set()
    try:
        async for _m in db.telegram_mappings.find(
            {"last_activity_at": {"$gte": online_threshold_iso}},
            {"_id": 0, "chat_id": 1},
        ):
            _cid = _m.get("chat_id")
            if _cid is not None:
                tg_chat_ids.add(str(_cid))
    except Exception as _e:
        logger.warning(f"online: telegram activity query failed: {_e}")
    if tg_chat_ids:
        linked = {}
        try:
            async for _u in db.users.find(
                {"telegram_chat_id": {"$in": list(tg_chat_ids)}},
                {"_id": 0, "id": 1, "telegram_chat_id": 1, "email": 1, "wallet_address": 1, "username": 1},
            ):
                linked[str(_u.get("telegram_chat_id"))] = _u
        except Exception as _e:
            logger.warning(f"online: telegram->user resolve failed: {_e}")
        for _cid in tg_chat_ids:
            _u = linked.get(_cid)
            if _u:
                _canon = _u.get("id") or _u.get("email") or _u.get("wallet_address") or _u.get("username")
                tg_users.add(_canon or f"tg:{_cid}")
            else:
                tg_users.add(f"tg:{_cid}")

    online_web = len(web_users)
    online_telegram = len(tg_users)
    online_now = len(web_users | tg_users)  # deduped total

    # Активные/неактивные пользователи по активности на рынке
    # (куплено ≥40 ИЛИ продано ≥100 ед. товара за 7 дней).
    try:
        from inactivity import get_activity_stats
        _act = await get_activity_stats(db)
    except Exception as _e:
        logger.warning(f"activity stats failed: {_e}")
        _act = {}

    return {
        "treasury": stats or {},
        "pending_withdrawals": pending_withdrawals,
        "total_users": total_users,
        "active_users_7d": active_users,
        "online_now": online_now,
        "online_web": online_web,
        "online_telegram": online_telegram,
        "market_active_users": _act.get("active", 0),
        "market_inactive_users": _act.get("inactive", 0),
        "market_activity": _act,
        "revenue_breakdown": {r["_id"]: {"total": r["total"], "count": r["count"]} for r in revenue_breakdown}
    }


@admin_router.get("/inactivity/stats")
async def admin_inactivity_stats(admin: User = Depends(get_admin_user)):
    """Активность пользователей на рынке (активные/неактивные)."""
    from inactivity import get_activity_stats
    return await get_activity_stats(db)


@admin_router.post("/inactivity/seize")
async def admin_inactivity_seize(admin: User = Depends(get_admin_user)):
    """Вручную запустить изъятие бизнесов у неактивных пользователей."""
    from inactivity import seize_inactive_businesses
    result = await seize_inactive_businesses(db)
    return {"ok": True, **result}


@admin_router.get("/users")
async def admin_get_users(skip: int = 0, limit: int = 50, q: str = "", admin: User = Depends(get_admin_user)):
    """Users for the admin, 50 at a time (newest first), with a server-side search
    over username / e-mail / wallet / id so the whole base is searchable."""
    import re as _re
    limit = max(1, min(50, int(limit))); skip = max(0, int(skip))
    flt: dict = {}
    q = (q or "").strip()
    if q:
        rx = {"$regex": _re.escape(q[:64]), "$options": "i"}
        flt = {"$or": [{"id": q}, {"username": rx}, {"email": rx}, {"wallet_address": rx}, {"display_name": rx}]}
    cur = db.users.find(flt, USER_SECRET_PROJECTION).sort([("created_at", -1), ("id", 1)]).skip(skip).limit(limit)
    users = await cur.to_list(limit)
    total = await db.users.count_documents(flt)
    return {"users": users, "total": total, "skip": skip, "limit": limit, "has_more": skip + len(users) < total}

@admin_router.get("/user/{user_id}")
async def admin_get_user_detail(user_id: str, admin: User = Depends(get_admin_user)):
    """Get detailed user info for admin"""
    user = await db.users.find_one({"id": user_id}, USER_SECRET_PROJECTION)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Get businesses
    _owner_keys_admin = await resolve_owner_keys(db, user_id)
    businesses = await db.businesses.find(owner_businesses_query(_owner_keys_admin), {"_id": 0}).to_list(100)
    
    # Get credits
    credits = await db.credit_loans.find({"borrower_id": user_id}, {"_id": 0}).to_list(100)
    
    # Calculate debt
    active_debt = sum(c.get("remaining_amount", 0) for c in credits if c.get("status") in ["active", "overdue"])
    
    # Business value
    total_business_value = sum(
        BUSINESS_TYPES.get(b.get("business_type"), {}).get("base_price", 0) * (1 + 0.5 * (b.get("level", 1) - 1))
        for b in businesses
    )
    
    return {
        **user,
        "businesses": [{"id": b["id"], "type": b["business_type"], "level": b.get("level", 1)} for b in businesses],
        "businesses_count": len(businesses),
        "credits": credits,
        "active_debt": active_debt,
        "total_business_value": total_business_value,
        "available_withdrawal": max(0, user.get("balance_ton", 0) - active_debt)
    }

@admin_router.post("/user/{user_id}/unblock-withdrawal")
async def admin_unblock_user_withdrawal(user_id: str, admin: User = Depends(get_admin_user)):
    """Remove withdrawal block for user"""
    result = await db.users.update_one(
        {"id": user_id},
        {"$unset": {"withdrawal_blocked_until": "", "withdraw_lock_until": ""}}
    )
    
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="User not found or no block to remove")
    
    logger.info(f"Admin {admin.username} unblocked withdrawal for user {user_id}")
    return {"status": "success", "message": "Withdrawal block removed"}


@admin_router.get("/multi-accounts")
async def admin_detect_multi_accounts(admin: User = Depends(get_admin_user)):
    """Detect multi-accounting using FingerprintJS visitor_id + Cloudflare Turnstile."""
    from antifraud import build_admin_report
    return await build_admin_report(db, limit=100)


class MultiAccountCleanup(BaseModel):
    mode: str = "older_than"   # older_than | failed_only | by_ids | all
    older_than_days: Optional[int] = 30
    event_ids: Optional[List[str]] = None
    failed_only: bool = False


@admin_router.post("/multi-accounts/cleanup")
async def admin_multi_accounts_cleanup(
    data: MultiAccountCleanup,
    admin: User = Depends(get_admin_user)
):
    """Delete anti-fraud events. Supports per-row, bulk failed, older_than, all."""
    from antifraud import cleanup_events
    return await cleanup_events(
        db,
        mode=data.mode,
        older_than_days=data.older_than_days,
        event_ids=data.event_ids,
        failed_only=data.failed_only,
    )


@admin_router.get("/transactions")
async def admin_get_transactions(
    skip: int = 0, 
    limit: int = 100, 
    tx_type: str = None,
    status: str = None,
    search: str = None,
    lang: str = "ru",
    admin: User = Depends(get_admin_user)
):
    """Get all transactions for admin with filters.

    `lang` controls description / type_name language. Supported: ru (default), en.
    Other languages fall back to en.

    `search` scopes the result to a SINGLE user — matched by user id, username
    (case-insensitive, exact or substring), email or wallet address. Every
    operation the user took part in (as owner, payer, payee, buyer or seller)
    is returned.
    """
    import re as _re
    and_conditions = []
    if tx_type:
        # Match either legacy `tx_type` or new `type`
        and_conditions.append({"$or": [{"tx_type": tx_type}, {"type": tx_type}]})
    if status:
        and_conditions.append({"status": status})
    if search and str(search).strip():
        s = str(search).strip()
        # Resolve every user matching the search term, then collect ALL their
        # identifiers so we can find transactions keyed by any of them.
        user_or = [
            {"id": s}, {"email": s}, {"wallet_address": s}, {"raw_address": s},
            {"username": {"$regex": f"^{_re.escape(s)}$", "$options": "i"}},
            {"username": {"$regex": _re.escape(s), "$options": "i"}},
        ]
        ids = {s}
        async for u in db.users.find(
            {"$or": user_or},
            {"_id": 0, "id": 1, "wallet_address": 1, "raw_address": 1, "email": 1, "username": 1},
        ):
            for f in ("id", "wallet_address", "raw_address", "email", "username"):
                if u.get(f):
                    ids.add(u[f])
        ids = list(ids)
        # Every field a transaction may store a user reference under.
        TX_USER_FIELDS = [
            "user_id", "user_wallet", "user_username", "username",
            "from_address", "to_address",
            "buyer_id", "buyer_user_id", "buyer_wallet", "buyer_email", "buyer_username",
            "seller_id", "seller_user_id", "seller_wallet", "seller_email", "seller_username",
        ]
        and_conditions.append({"$or": [{f: {"$in": ids}} for f in TX_USER_FIELDS]})

    query = {"$and": and_conditions} if and_conditions else {}
    
    transactions = await db.transactions.find(query, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    total = await db.transactions.count_documents(query)
    
    # Import transaction type metadata
    try:
        from transaction_history import TRANSACTION_TYPES
    except Exception:
        TRANSACTION_TYPES = {}

    # Normalize lang
    L = (lang or "ru").lower()
    if L not in ("ru", "en"):
        L = "en"

    # i18n labels for transaction types
    TYPE_NAME_I18N = {
        "deposit":            {"ru": "Пополнение",                "en": "Deposit"},
        "withdrawal":         {"ru": "Вывод",                     "en": "Withdrawal"},
        "instant_withdrawal": {"ru": "Мгновенный вывод",          "en": "Instant withdrawal"},
        "land_purchase":      {"ru": "Покупка земли",             "en": "Land purchase"},
        "land_sale":          {"ru": "Продажа земли",             "en": "Land sale"},
        "land_sale_listing":  {"ru": "Выставление земли на продажу", "en": "Land listing"},
        "plot_purchase":      {"ru": "Покупка участка",           "en": "Plot purchase"},
        "business_build":     {"ru": "Строительство бизнеса",     "en": "Business build"},
        "business_upgrade":   {"ru": "Улучшение бизнеса",         "en": "Business upgrade"},
        "business_purchase":  {"ru": "Покупка бизнеса",           "en": "Business purchase"},
        "business_sale":      {"ru": "Продажа бизнеса",           "en": "Business sale"},
        "resource_sale":      {"ru": "Продажа ресурсов",          "en": "Resource sale"},
        "resource_purchase":  {"ru": "Покупка ресурсов",          "en": "Resource purchase"},
        "patron_fee":         {"ru": "Плата покровителю",         "en": "Patron fee"},
        "warehouse_purchase": {"ru": "Покупка склада",            "en": "Warehouse purchase"},
        "warehouse_upgrade":  {"ru": "Улучшение склада",          "en": "Warehouse upgrade"},
        "tax":                {"ru": "Налог",                     "en": "Tax"},
        "reward":             {"ru": "Награда",                   "en": "Reward"},
        "trade":              {"ru": "Торговля",                  "en": "Trade"},
        "repair":             {"ru": "Ремонт",                    "en": "Repair"},
        "credit_taken":       {"ru": "Получение кредита",         "en": "Credit taken"},
        "credit_payment":     {"ru": "Погашение кредита",         "en": "Credit payment"},
        "referral_bonus":     {"ru": "Реферальный бонус",         "en": "Referral bonus"},
        "income_collection":  {"ru": "Сбор дохода",               "en": "Income collection"},
        "promo_activation":   {"ru": "Активация промокода",       "en": "Promo activation"},
        "market_purchase":    {"ru": "Покупка на рынке",          "en": "Market purchase"},
        "market_sale":        {"ru": "Продажа на рынке",          "en": "Market sale"},
        "resource_buy":       {"ru": "Покупка ресурсов",          "en": "Resource purchase"},
        "resource_sell":      {"ru": "Продажа ресурсов",          "en": "Resource sale"},
        "task_reward":        {"ru": "Награда за задание",         "en": "Task reward"},
        "daily_reward":       {"ru": "Ежедневная награда",         "en": "Daily reward"},
        "referral_income":    {"ru": "Реферальный доход",          "en": "Referral income"},
        "income":             {"ru": "Доход",                     "en": "Income"},
        "fee":                {"ru": "Комиссия",                   "en": "Fee"},
        "transfer":           {"ru": "Перевод",                    "en": "Transfer"},
        "admin_buyout":       {"ru": "Выкуп администрацией",       "en": "Admin buyout"},
        "contract_payment":   {"ru": "Оплата по контракту",       "en": "Contract payment"},
        "contract_payout":    {"ru": "Выплата по контракту",      "en": "Contract payout"},
        "patron_bonus":       {"ru": "Бонус патрона",             "en": "Patron bonus"},
        "alliance_payout":    {"ru": "Выплата альянса",           "en": "Alliance payout"},
        "business_seized":    {"ru": "Конфискация бизнеса",        "en": "Business seizure"},
    }

    # Resource code → human name, RU/EN
    _RES_NAMES = {
        "energy":     {"ru": "Энергия",     "en": "Energy"},
        "cu":         {"ru": "Вычисления",  "en": "CU"},
        "quartz":     {"ru": "Кварц",       "en": "Quartz"},
        "traffic":    {"ru": "Трафик",      "en": "Traffic"},
        "cooling":    {"ru": "Охлаждение",  "en": "Cooling"},
        "biomass":    {"ru": "Биомасса",    "en": "Biomass"},
        "scrap":      {"ru": "Металлолом",  "en": "Scrap"},
        "chips":      {"ru": "Микросхемы",  "en": "Chips"},
        "nft":        {"ru": "NFT-арт",     "en": "NFT art"},
        "neurocode":  {"ru": "Нейрокод",    "en": "Neurocode"},
        "logistics":  {"ru": "Логистика",   "en": "Logistics"},
        "repair_kits":{"ru": "Ремкомплект", "en": "Repair kit"},
        "vr_experience": {"ru": "VR-опыт",  "en": "VR experience"},
        "crops":      {"ru": "Урожай",      "en": "Crops"},
        "materials":  {"ru": "Материалы",   "en": "Materials"},
        "goods":      {"ru": "Товары",      "en": "Goods"},
    }

    def _biz_name(btype):
        cfg = BUSINESSES.get(btype) or BUSINESSES.get(BUSINESS_KEY_MAP.get(btype, btype), {})
        nm = cfg.get("name") if cfg else None
        if isinstance(nm, dict):
            return nm.get(L) or nm.get("en") or nm.get("ru") or btype
        return nm or btype

    def _res_name(rt):
        return _RES_NAMES.get(rt, {}).get(L, rt)

    # Localized description templates
    def _build_description(ttype, tx, details):
        if ttype == "repair":
            # Always resolve business name fresh by type so language is correct;
            # fall back to stored business_name only if type is missing.
            btype = details.get("business_type") or tx.get("business_type")
            bn = _biz_name(btype) if btype else (details.get("business_name") or "")
            lvl = details.get("level")
            miss = details.get("missing_pct")
            if L == "ru":
                desc = f"Ремонт бизнеса «{bn}»"
                if lvl:
                    desc += f" (ур. {lvl})"
                if miss is not None:
                    desc += f" на {miss}%"
            else:
                desc = f"Repair of «{bn}» business"
                if lvl:
                    desc += f" (lvl {lvl})"
                if miss is not None:
                    desc += f", {miss}%"
            return desc
        if ttype == "business_build":
            btype = details.get("business_type") or tx.get("business_type")
            return (f"Строительство: {_biz_name(btype)}" if L == "ru" else f"Build: {_biz_name(btype)}") if btype else (
                "Строительство бизнеса" if L == "ru" else "Business build")
        if ttype == "business_purchase":
            btype = details.get("business_type") or tx.get("business_type")
            return (f"Покупка бизнеса: {_biz_name(btype)}" if L == "ru" else f"Business purchase: {_biz_name(btype)}") if btype else (
                "Покупка бизнеса" if L == "ru" else "Business purchase")
        if ttype == "business_sale":
            btype = details.get("business_type") or tx.get("business_type")
            return (f"Продажа бизнеса: {_biz_name(btype)}" if L == "ru" else f"Business sale: {_biz_name(btype)}") if btype else (
                "Продажа бизнеса" if L == "ru" else "Business sale")
        if ttype == "business_upgrade":
            btype = details.get("business_type") or tx.get("business_type")
            lvl = details.get("new_level")
            if btype:
                if L == "ru":
                    s = f"Улучшение «{_biz_name(btype)}»"
                    if lvl:
                        s += f" → ур. {lvl}"
                else:
                    s = f"Upgrade «{_biz_name(btype)}»"
                    if lvl:
                        s += f" → lvl {lvl}"
                return s
            return "Улучшение бизнеса" if L == "ru" else "Business upgrade"
        if ttype == "land_purchase":
            x = details.get("x") if "x" in details else details.get("plot_x")
            y = details.get("y") if "y" in details else details.get("plot_y")
            cid = details.get("city_id") or tx.get("city_id") or tx.get("island_id")
            # Fallback: parse "plot_coords" like "[9, 16]" or [9,16]
            if (x is None or y is None) and tx.get("plot_coords"):
                pc = tx.get("plot_coords")
                try:
                    if isinstance(pc, str):
                        import json as _json
                        parsed = _json.loads(pc)
                    else:
                        parsed = pc
                    if isinstance(parsed, (list, tuple)) and len(parsed) >= 2:
                        x, y = parsed[0], parsed[1]
                except Exception:
                    pass
            biz_label = _plot_business_label(details, tx)
            if L == "ru":
                parts = ["Покупка участка"]
                if x is not None and y is not None:
                    parts.append(f"({x}, {y})")
                if cid:
                    parts.append(f"в {cid}")
                base = " ".join(parts)
                if biz_label:
                    return f"{base} — на участке: {biz_label}"
                return f"{base} (пустой участок)"
            else:
                parts = ["Plot purchase"]
                if x is not None and y is not None:
                    parts.append(f"({x}, {y})")
                if cid:
                    parts.append(f"in {cid}")
                base = " ".join(parts)
                if biz_label:
                    return f"{base} — on plot: {biz_label}"
                return f"{base} (empty plot)"
        if ttype == "land_sale":
            x = details.get("x") if "x" in details else details.get("plot_x")
            y = details.get("y") if "y" in details else details.get("plot_y")
            cid = details.get("city_id") or tx.get("city_id") or tx.get("island_id")
            if (x is None or y is None) and tx.get("plot_coords"):
                pc = tx.get("plot_coords")
                try:
                    if isinstance(pc, str):
                        import json as _json
                        parsed = _json.loads(pc)
                    else:
                        parsed = pc
                    if isinstance(parsed, (list, tuple)) and len(parsed) >= 2:
                        x, y = parsed[0], parsed[1]
                except Exception:
                    pass
            biz_label = _plot_business_label(details, tx)
            if L == "ru":
                base = "Продажа участка"
                if x is not None and y is not None:
                    base += f" ({x}, {y})"
                if cid:
                    base += f" в {cid}"
                if biz_label:
                    base += f" — на участке: {biz_label}"
                return base
            else:
                base = "Plot sale"
                if x is not None and y is not None:
                    base += f" ({x}, {y})"
                if cid:
                    base += f" in {cid}"
                if biz_label:
                    base += f" — on plot: {biz_label}"
                return base
        if ttype == "land_sale_listing":
            return "Выставление участка на продажу" if L == "ru" else "Plot listed for sale"
        if ttype == "deposit":
            return "Пополнение баланса" if L == "ru" else "Balance deposit"
        if ttype in ("withdrawal", "instant_withdrawal"):
            if L == "ru":
                return "Вывод средств" + (" (мгновенный)" if ttype == "instant_withdrawal" else "")
            return "Withdrawal" + (" (instant)" if ttype == "instant_withdrawal" else "")
        if ttype in ("resource_sale", "resource_purchase", "market_purchase", "market_sale", "resource_buy", "resource_sell"):
            rt = details.get("resource_type") or tx.get("resource_type")
            amt = details.get("amount") or tx.get("resource_amount")
            rname = _res_name(rt) if rt else None
            is_sale = ttype in ("resource_sale", "market_sale", "resource_sell")
            if L == "ru":
                action = "Продажа" if is_sale else "Покупка"
                if rname:
                    s = f"{action} ресурса: {rname}"
                    if amt:
                        s += f" × {amt}"
                    return s
                return f"{action} ресурсов"
            else:
                action = "Sale" if is_sale else "Purchase"
                if rname:
                    s = f"{action} of resource: {rname}"
                    if amt:
                        s += f" × {amt}"
                    return s
                return f"{action} of resources"
        if ttype == "credit_taken":
            return "Получение кредита" if L == "ru" else "Credit taken"
        if ttype == "credit_payment":
            return "Погашение кредита" if L == "ru" else "Credit payment"
        if ttype == "patron_fee":
            return "Плата покровителю" if L == "ru" else "Patron fee"
        if ttype == "income_collection":
            return "Сбор дохода с бизнесов" if L == "ru" else "Business income collected"
        if ttype == "promo_activation":
            code = details.get("promo_code") or details.get("code")
            if L == "ru":
                return f"Активация промокода {code}" if code else "Активация промокода"
            return f"Promo activation {code}" if code else "Promo activation"
        if ttype == "warehouse_purchase":
            return "Покупка склада" if L == "ru" else "Warehouse purchase"
        if ttype == "warehouse_upgrade":
            return "Улучшение склада" if L == "ru" else "Warehouse upgrade"
        # Fallback
        return TYPE_NAME_I18N.get(ttype, {}).get(L) or ttype

    # Cache user lookups
    _user_cache = {}
    async def _resolve_username(ref):
        """Resolve a user id / wallet / email → display username (cached)."""
        if not ref:
            return None
        if ref in _user_cache:
            return _user_cache[ref]
        u = await db.users.find_one({
            "$or": [{"id": ref}, {"wallet_address": ref}, {"email": ref}, {"username": ref}]
        }, {"_id": 0, "username": 1, "display_name": 1, "email": 1})
        label = (u or {}).get("username") or (u or {}).get("display_name") or (u or {}).get("email") or ref
        _user_cache[ref] = label
        return label

    async def _user_label(tx):
        # Prefer existing fields
        label = tx.get("user_username") or tx.get("username") or tx.get("user_display_name")
        if label:
            return label
        uid = tx.get("user_id") or tx.get("user_wallet") or tx.get("from_address")
        if not uid:
            return None
        if uid in _user_cache:
            return _user_cache[uid]
        u = await db.users.find_one({
            "$or": [{"id": uid}, {"wallet_address": uid}, {"email": uid}, {"username": uid}]
        }, {"_id": 0, "username": 1, "display_name": 1, "email": 1})
        label = (u or {}).get("username") or (u or {}).get("display_name") or (u or {}).get("email") or uid
        _user_cache[uid] = label
        return label

    # Status display per language
    STATUS_I18N = {
        "pending":    {"ru": "В ожидании",   "en": "Pending"},
        "processing": {"ru": "Обрабатывается","en": "Processing"},
        "completed":  {"ru": "Выполнено",    "en": "Completed"},
        "failed":     {"ru": "Ошибка",       "en": "Failed"},
        "rejected":   {"ru": "Отклонено",    "en": "Rejected"},
    }

    # ---- Pre-batch: resolve plot info & businesses on those plots ----
    # Collect all plot_id / x,y references
    plot_ids = set()
    coord_refs = []  # list of (city_id, x, y) tuples
    for tx in transactions:
        d = tx.get("details") or {}
        pid = d.get("plot_id") or tx.get("plot_id")
        if pid:
            plot_ids.add(pid)
        cid = d.get("city_id") or tx.get("city_id") or tx.get("island_id")
        x = d.get("x") if "x" in d else d.get("plot_x")
        y = d.get("y") if "y" in d else d.get("plot_y")
        # Fallback: top-level plot_coords
        if (x is None or y is None) and tx.get("plot_coords"):
            try:
                pc = tx.get("plot_coords")
                if isinstance(pc, str):
                    import json as _json
                    pc = _json.loads(pc)
                if isinstance(pc, (list, tuple)) and len(pc) >= 2:
                    x, y = pc[0], pc[1]
            except Exception:
                pass
        if cid is not None and x is not None and y is not None:
            coord_refs.append((cid, x, y))

    # Lookup plots
    plots_by_id = {}
    if plot_ids:
        async for p in db.plots.find({"id": {"$in": list(plot_ids)}}, {"_id": 0}):
            plots_by_id[p["id"]] = p
    plots_by_coord = {}
    if coord_refs:
        # Normalize as $or on city_id+x+y
        or_clauses = [{"city_id": c, "x": x, "y": y} for (c, x, y) in coord_refs]
        async for p in db.plots.find({"$or": or_clauses}, {"_id": 0}):
            key = (p.get("city_id"), p.get("x"), p.get("y"))
            plots_by_coord[key] = p
            if p.get("id"):
                plots_by_id[p["id"]] = p

    # Lookup businesses on those plots
    biz_by_plot_id = {}
    biz_by_coord = {}
    if plots_by_id or plots_by_coord:
        ids = [pid for pid in plots_by_id.keys() if pid]
        if ids:
            async for b in db.businesses.find({"plot_id": {"$in": ids}}, {"_id": 0}):
                biz_by_plot_id[b.get("plot_id")] = b
        # Also try matching by coord
        if coord_refs:
            or_clauses = [{"city_id": c, "x": x, "y": y} for (c, x, y) in coord_refs]
            async for b in db.businesses.find({"$or": or_clauses}, {"_id": 0}):
                biz_by_coord[(b.get("city_id"), b.get("x"), b.get("y"))] = b

    def _plot_business_label(details, tx):
        """Return human-readable label of what is on the plot, or None."""
        pid = details.get("plot_id") or tx.get("plot_id")
        biz = None
        if pid and pid in biz_by_plot_id:
            biz = biz_by_plot_id[pid]
        if not biz:
            cid = details.get("city_id") or tx.get("city_id") or tx.get("island_id")
            x = details.get("x") if "x" in details else details.get("plot_x")
            y = details.get("y") if "y" in details else details.get("plot_y")
            if (x is None or y is None) and tx.get("plot_coords"):
                try:
                    import json as _json
                    pc = tx.get("plot_coords")
                    if isinstance(pc, str):
                        pc = _json.loads(pc)
                    if isinstance(pc, (list, tuple)) and len(pc) >= 2:
                        x, y = pc[0], pc[1]
                except Exception:
                    pass
            if cid is not None and x is not None and y is not None:
                biz = biz_by_coord.get((cid, x, y))
        if not biz:
            return None
        bn = _biz_name(biz.get("business_type", ""))
        lvl = biz.get("level")
        if L == "ru":
            return f"{bn}" + (f" (ур. {lvl})" if lvl else "")
        return f"{bn}" + (f" (lvl {lvl})" if lvl else "")

    # Enrich each transaction
    for tx in transactions:
        # Status display
        st = tx.get("status")
        tx["status_display"] = STATUS_I18N.get(st, {}).get(L, st or "")
        
        # Resolve canonical type
        ttype = tx.get("type") or tx.get("tx_type") or "trade"
        if ttype == "purchase_plot":
            ttype = "land_purchase"
        elif ttype == "build_business":
            ttype = "business_build"
        elif ttype == "demolish_business":
            ttype = "business_sale"
        elif ttype == "trade_resource":
            ttype = "resource_purchase"
        elif ttype == "resale_plot":
            ttype = "land_sale_listing"
        
        type_info = TRANSACTION_TYPES.get(ttype, {"name": ttype, "icon": "💱", "color": "gray"})
        i18n_name = TYPE_NAME_I18N.get(ttype, {}).get(L)
        tx["type_name"] = i18n_name or type_info.get("name", ttype)
        tx["type_icon"] = type_info.get("icon", "💱")
        tx["type_color"] = type_info.get("color", "gray")
        # Normalize tx_type for frontend filter
        if not tx.get("tx_type"):
            tx["tx_type"] = ttype
        
        # Always (re)build description in requested language so it's localized,
        # even if a stored description from earlier exists in another language.
        details = tx.get("details") or {}
        tx["description"] = _build_description(ttype, tx, details)
        
        # Ensure user_username is set
        if not tx.get("user_username"):
            try:
                tx["user_username"] = await _user_label(tx)
            except Exception:
                pass

        # Resolve buyer / seller usernames so the admin can see who bought and
        # who sold in a trade. Only use explicit buyer_id/seller_id fields so we
        # never mislabel deposit/withdrawal wallet addresses as buyer/seller.
        try:
            buyer_ref = tx.get("buyer_id")
            seller_ref = tx.get("seller_id")
            if buyer_ref:
                tx["buyer_username"] = tx.get("buyer_username") or await _resolve_username(buyer_ref)
            if seller_ref:
                tx["seller_username"] = tx.get("seller_username") or await _resolve_username(seller_ref)
        except Exception:
            pass

    return {"transactions": transactions, "total": total}


@admin_router.post("/transactions/export-csv")
async def admin_export_transactions_csv(
    payload: dict,
    lang: str = "ru",
    admin: User = Depends(get_admin_user)
):
    """
    Export selected (or filtered) transactions as CSV.
    Body:
      { "ids": ["tx1","tx2", ...]  }            -> export only those IDs
      { "filters": {"tx_type":"...", "status":"...", "limit":1000} } -> export by filter
    """
    from fastapi.responses import StreamingResponse
    import csv
    import io
    
    ids = payload.get("ids") or []
    filters = payload.get("filters") or {}
    
    if ids:
        query = {"id": {"$in": ids}}
    else:
        query = {}
        if filters.get("tx_type"):
            query["$or"] = [{"tx_type": filters["tx_type"]}, {"type": filters["tx_type"]}]
        if filters.get("status"):
            query["status"] = filters["status"]
    
    limit = int(filters.get("limit") or 5000)
    cursor = db.transactions.find(query, {"_id": 0}).sort("created_at", -1).limit(limit)
    rows = await cursor.to_list(limit)
    
    # Reuse same enrichment by calling admin_get_transactions logic in inline fashion.
    # Simplest: call the GET endpoint but that returns paginated list — easier to inline reuse via subquery:
    # We just do minimum here to add description + type_name based on TRANSACTION_TYPES + business name resolution.
    try:
        from transaction_history import TRANSACTION_TYPES
    except Exception:
        TRANSACTION_TYPES = {}
    
    L = (lang or "ru").lower()
    if L not in ("ru", "en"):
        L = "en"
    
    def _bn(btype):
        cfg = BUSINESSES.get(btype) or BUSINESSES.get(BUSINESS_KEY_MAP.get(btype, btype), {})
        nm = cfg.get("name") if cfg else None
        if isinstance(nm, dict):
            return nm.get(L) or nm.get("en") or btype
        return nm or btype
    
    # Build CSV with an Excel-friendly preamble:
    # • UTF-8 BOM so Cyrillic renders correctly in Excel/Numbers.
    # • `sep=,` hint on the first line — Excel (especially localised RU/DE
    #   builds where the list separator defaults to `;`) uses this to pick
    #   the correct delimiter and put each field into its own column.
    output = io.StringIO()
    output.write("\ufeff")            # UTF-8 BOM
    output.write("sep=,\r\n")         # Excel delimiter hint
    writer = csv.writer(output, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    
    headers = [
        "ID", "Date", "Type", "Status", "User", "Wallet/Email",
        "Amount TON", "Amount $CITY", "Business", "Plot", "Description"
    ]
    writer.writerow(headers)
    
    for tx in rows:
        details = tx.get("details") or {}
        ttype = tx.get("type") or tx.get("tx_type") or ""
        ti = TRANSACTION_TYPES.get(ttype, {})
        type_name = ti.get("name", ttype)
        biz = details.get("business_name") or (_bn(details.get("business_type") or "") if details.get("business_type") else "")
        plot = ""
        x = details.get("x") if "x" in details else details.get("plot_x")
        y = details.get("y") if "y" in details else details.get("plot_y")
        cid = details.get("city_id") or tx.get("city_id") or tx.get("island_id")
        # Fallback: top-level plot_coords
        if (x is None or y is None) and tx.get("plot_coords"):
            try:
                import json as _json
                pc = tx.get("plot_coords")
                if isinstance(pc, str):
                    pc = _json.loads(pc)
                if isinstance(pc, (list, tuple)) and len(pc) >= 2:
                    x, y = pc[0], pc[1]
            except Exception:
                pass
        if x is not None and y is not None:
            plot = f"({x}, {y})"
            if cid:
                plot += f" {cid}"
        amt_ton = tx.get("amount_ton") or tx.get("amount") or 0
        amt_city = tx.get("amount_city") or 0
        writer.writerow([
            tx.get("id", ""),
            tx.get("created_at", ""),
            type_name,
            tx.get("status", ""),
            tx.get("user_username", "") or "",
            tx.get("user_wallet", "") or tx.get("from_address", "") or "",
            amt_ton,
            amt_city,
            biz,
            plot,
            tx.get("description", "") or "",
        ])
    
    output.seek(0)
    filename = f"transactions_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "Cache-Control": "no-store",
        }
    )

@admin_router.post("/withdrawal/approve/{tx_id}")
async def admin_approve_withdrawal(tx_id: str, admin: User = Depends(require_scope("finance"))):
    import time as _time
    _t0 = _time.monotonic()
    # 1. Поиск транзакции с атомарной блокировкой
    tx = await db.transactions.find_one_and_update(
        {"id": tx_id, "status": "pending"},
        {"$set": {"status": "processing", "processing_started": datetime.now(timezone.utc).isoformat()}},
        return_document=True
    )
    
    if not tx:
        # Проверяем существование транзакции
        existing_tx = await db.transactions.find_one({"id": tx_id})
        if not existing_tx:
            raise HTTPException(status_code=404, detail="Заявка не найдена")
        if existing_tx.get("status") == "processing":
            raise HTTPException(status_code=400, detail="Заявка уже обрабатывается, дождитесь завершения")
        if existing_tx.get("status") == "completed":
            raise HTTPException(status_code=400, detail="Заявка уже одобрена и выполнена")
        if existing_tx.get("status") == "rejected":
            raise HTTPException(status_code=400, detail="Заявка была отклонена ранее")
        raise HTTPException(status_code=400, detail=f"Заявка уже обработана (статус: {existing_tx.get('status')})")

    # 2. Поиск пользователя для получения RAW адреса
    user_wallet = tx.get("user_wallet")
    user = await find_user(db, user_id=tx.get("user_id"), wallet=user_wallet)
    
    # Если нет raw_address, попробуем конвертировать user-friendly адрес
    destination_address = None
    if user:
        destination_address = user.get("raw_address")
        if not destination_address and user.get("wallet_address"):
            destination_address = user.get("wallet_address")
    
    if not destination_address:
        destination_address = tx.get("user_raw_address") or tx.get("to_address") or user_wallet
    
    if not destination_address:
        # Откатываем статус при ошибке
        await db.transactions.update_one({"id": tx_id}, {"$set": {"status": "pending"}})
        raise HTTPException(status_code=400, detail="Адрес получателя не найден")

    # 3. Получить мнемонику из кошелька для вывода (withdrawal_wallet)
    from mnemonic_crypto import decrypt_mnemonic
    withdrawal_wallet = await db.admin_settings.find_one({"type": "withdrawal_wallet"}, {"_id": 0})
    seed = decrypt_mnemonic(withdrawal_wallet.get("mnemonic")) if withdrawal_wallet else None

    # Fallback to sender_wallet if withdrawal_wallet not configured
    if not seed:
        sender_wallet = await db.admin_settings.find_one({"type": "sender_wallet"}, {"_id": 0})
        seed = decrypt_mnemonic(sender_wallet.get("mnemonic")) if sender_wallet else None
    
    # Fallback to .env if not in admin settings
    if not seed:
        seed = os.getenv("TON_WALLET_MNEMONIC")
    
    if not seed:
        await db.transactions.update_one({"id": tx_id}, {"$set": {"status": "pending"}})
        raise HTTPException(status_code=500, detail="Кошелёк для вывода не настроен. Настройте его в разделе 'Контракт' в админке.")

    # 4. Подготовка данных для отправки
    net_amount = float(tx.get("net_amount", 0))
    commission = float(tx.get("commission", 0))
    amount_ton_original = float(tx.get("amount_ton", 0))
    if amount_ton_original <= 0:
        amount_ton_original = net_amount + commission

    logger.info(f"📤 Одобрение вывода: net={net_amount}, commission={commission}, original={amount_ton_original}")
    logger.info(f"📍 Отправка на адрес: {destination_address}")
    
    # Получаем username пользователя для комментария
    user_username = ""
    if user:
        user_username = user.get("username", "")

    try:
        # 5. ВЫЗОВ НОВОГО МЕТОДА ИЗ ton_integration
        _t_pay = _time.monotonic()
        tx_hash = await ton_client.send_ton_payout(
            dest_address=destination_address,
            amount_ton=net_amount,
            mnemonics=seed,
            user_username=user_username
        )
        # From here on the TON has LEFT the wallet: an error in the bookkeeping
        # below must never refund the user (that would pay them twice).
        _payout_sent = tx_hash
        logger.info(f"⏱ withdrawal {tx_id}: prepare {(_t_pay - _t0):.2f}s, TON payout {(_time.monotonic() - _t_pay):.2f}s")
        
        # 6. Успешное завершение
        now_iso = datetime.now(timezone.utc).isoformat()
        await db.transactions.update_one(
            {"id": tx_id},
            {"$set": {
                "status": "completed", 
                "completed_at": now_iso, 
                "blockchain_hash": tx_hash,
                "from_address": "Система",
                "to_address": user_wallet
            }}
        )
        
        # Статистика
        await db.admin_stats.update_one(
            {"type": "treasury"},
            {"$inc": {"withdrawal_fees": commission, "total_withdrawals": net_amount, "total_withdrawals_count": 1}},
            upsert=True
        )
        
        # Telegram + in-app + WS notification (single fan-out via notify_user).
        # `notify_user` already mirrors the message to Telegram when the user has
        # linked their account, so we DO NOT call bot.notify_withdrawal_approved
        # separately — that would deliver two Telegram messages for one payout.
        # We also make the on-chain hash user-friendly: show the full hash if
        # available, otherwise omit the "TX:" line entirely (never show the
        # legacy 'sent_success' placeholder).
        # Delivered in the background: the admin no longer waits for Telegram/WS.
        try:
            from core.notify import notify_user_background
            notify_user_background(
                db, tx.get("user_id"),
                title="✅ Вывод одобрен",
                message=f"💸 Ваш запрос на вывод <b>{net_amount:.4f} TON</b> одобрен и отправлен на ваш кошелёк.",
                type_key="withdrawal_approved",
                priority="success",
                payload={"tx_id": tx_id, "amount": net_amount, "hash": tx_hash},
                i18n_key="withdrawal_approved",
                i18n_vars={"amount": f"{net_amount:.4f}"},
                tx_hash=tx_hash,
            )
        except Exception as _e:
            logger.warning(f"withdrawal_approved notify failed: {_e}")

        logger.info(f"⏱ withdrawal {tx_id}: total {(_time.monotonic() - _t0):.2f}s")
        return {"status": "completed", "hash": tx_hash}

    except Exception as e:
        logger.error(f"❌ Ошибка в роуте Approve: {e}")
        try:
            from ton_integration import PayoutAmbiguous as _PayoutAmbiguous
        except Exception:
            _PayoutAmbiguous = ()
        if _PayoutAmbiguous and isinstance(e, _PayoutAmbiguous):
            # The network may have taken the payout (lost response / seqno used):
            # never refund on a guess — flag for the reconciliation screen.
            logger.critical(f"🚨 withdrawal {tx_id}: payout outcome UNKNOWN ({e}); hash={e.msg_hash}")
            await db.transactions.update_one({"id": tx_id}, {"$set": {
                "status": "needs_review", "blockchain_hash": e.msg_hash or None,
                "error": str(e), "needs_review_at": datetime.now(timezone.utc).isoformat()}})
            raise HTTPException(status_code=502, detail="Сеть TON не ответила — выплата могла уйти. Заявка помечена для проверки в «Сверке», повторно не одобряйте.")
        if locals().get("_payout_sent"):
            # Payout already broadcast — NO refund. Leave a flagged record for
            # the reconciliation report / manual check instead.
            logger.critical(f"🚨 withdrawal {tx_id}: payout SENT ({_payout_sent}) but bookkeeping failed: {e}")
            try:
                await db.transactions.update_one({"id": tx_id}, {"$set": {
                    "status": "needs_review", "blockchain_hash": _payout_sent,
                    "error": f"payout sent, bookkeeping failed: {e}",
                    "needs_review_at": datetime.now(timezone.utc).isoformat()}})
            except Exception:
                pass
            raise HTTPException(status_code=500, detail="Выплата отправлена, но запись не сохранилась — заявка помечена для проверки, повторно не одобряйте.")
        # ВОЗВРАТ СРЕДСТВ ПРИ ОШИБКЕ БЛОКЧЕЙНА — ищем пользователя по всем
        # возможным идентификаторам (как в reject), чтобы возврат не потерялся,
        # если wallet_address пуст/не совпадает.
        refund_or = []
        _uid = tx.get("user_id")
        if _uid:
            refund_or.append({"id": _uid})
        if user_wallet:
            refund_or.append({"wallet_address": user_wallet})
            refund_or.append({"raw_address": user_wallet})
        _raw = tx.get("user_raw_address") or (user.get("raw_address") if user else None)
        if _raw:
            refund_or.append({"raw_address": _raw})
        if refund_or:
            await db.users.update_one(
                {"$or": refund_or},
                {"$inc": {"balance_ton": amount_ton_original}}
            )
        else:
            logger.error(f"❌ Не удалось определить пользователя для возврата по tx {tx_id}")
        await db.transactions.update_one(
            {"id": tx_id},
            {"$set": {"status": "failed", "error": str(e)}}
        )
        raise HTTPException(status_code=502, detail=f"Ошибка сети TON: {str(e)}")
    
@admin_router.post("/withdrawal/reject/{tx_id}")
async def admin_reject_withdrawal(tx_id: str, admin: User = Depends(require_scope("finance"))):
    """Отклонение заявки с гарантированным возвратом на balance_ton"""
    # 1. Ищем саму транзакцию
    tx = await db.transactions.find_one({"id": tx_id})
    if not tx:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    
    current_status = tx.get("status")
    if current_status == "rejected":
        raise HTTPException(status_code=400, detail="Заявка уже была отклонена ранее")
    if current_status == "completed":
        raise HTTPException(status_code=400, detail="Заявка уже одобрена и выполнена")
    if current_status == "processing":
        raise HTTPException(status_code=400, detail="Заявка уже обрабатывается, дождитесь завершения")
    if current_status != "pending":
        raise HTTPException(status_code=400, detail=f"Невозможно отклонить заявку со статусом: {current_status}")

    # Получаем данные из транзакции - поддерживаем оба поля amount и amount_ton
    user_address = tx.get("user_wallet") or tx.get("from_address")
    user_id = tx.get("user_id")
    amount_to_return = float(tx.get("amount_ton") or tx.get("amount", 0))

    if amount_to_return <= 0:
        raise HTTPException(status_code=400, detail="Сумма для возврата не указана")

    # 2. ВОЗВРАТ: Ищем пользователя по всем возможным идентификаторам
    or_conditions = []
    if user_id:
        or_conditions.append({"id": user_id})
    if user_address:
        or_conditions.append({"wallet_address": user_address})
        or_conditions.append({"raw_address": user_address})
    
    # Также пробуем по raw_address если он есть отдельным полем
    raw_addr = tx.get("user_raw_address")
    if raw_addr:
        or_conditions.append({"raw_address": raw_addr})
    
    if not or_conditions:
        raise HTTPException(status_code=400, detail="Не найдены идентификаторы пользователя в транзакции")
    
    update_result = await db.users.update_one(
        {"$or": or_conditions},
        {"$inc": {"balance_ton": amount_to_return}}
    )

    # 3. Фиксируем результат в базе
    if update_result.modified_count > 0:
        await db.transactions.update_one(
            {"id": tx_id},
            {
                "$set": {
                    "status": "rejected",
                    "rejected_at": datetime.now(timezone.utc).isoformat(),
                    "admin_note": f"Возвращено {amount_to_return} TON на balance_ton"
                }
            }
        )
        
        # Telegram + in-app notification (single fan-out via core.notify —
        # notify_user already mirrors the message to Telegram, so we do NOT
        # call bot.notify_withdrawal_rejected separately or the user would get
        # two Telegram messages for one rejection).
        try:
            from core.notify import notify_user_background
            notify_user_background(
                db, user_id,
                title="❌ Вывод отклонён",
                message=(
                    f"💰 Ваш запрос на вывод <b>{amount_to_return:.4f} TON</b> отклонён администратором.\n\n"
                    f"↩️ Средства возвращены на ваш баланс."
                ),
                type_key="withdrawal_rejected",
                priority="warning",
                payload={"tx_id": tx_id, "amount": amount_to_return},
                add_home_button=True,
                i18n_key="withdrawal_rejected",
                i18n_vars={"amount": f"{amount_to_return:.4f}"},
            )
        except Exception as _e:
            logger.warning(f"withdrawal_rejected notify failed: {_e}")
        
        return {"status": "success", "message": f"Возвращено {amount_to_return} TON"}
    else:
        raise HTTPException(status_code=404, detail="Пользователь не найден в базе для возврата")


# Tax Settings
class TaxSettings(BaseModel):
    small_business_tax: float = 5
    medium_business_tax: float = 8
    large_business_tax: float = 10
    land_business_sale_tax: float = 10

@admin_router.get("/settings/tax")
async def get_tax_settings(admin: User = Depends(get_admin_user)):
    """Get tax settings"""
    settings = await db.admin_settings.find_one({"type": "tax_settings"}, {"_id": 0})
    if not settings:
        return {
            "small_business_tax": 5,
            "medium_business_tax": 8,
            "large_business_tax": 10,
            "land_business_sale_tax": 10,
            "resource_market_tax": 13
        }
    return settings

@admin_router.post("/settings/tax")
async def save_tax_settings(data: TaxSettings, admin: User = Depends(get_admin_user)):
    """Save tax settings"""
    await db.admin_settings.update_one(
        {"type": "tax_settings"},
        {"$set": {
            "type": "tax_settings",
            "small_business_tax": data.small_business_tax,
            "medium_business_tax": data.medium_business_tax,
            "large_business_tax": data.large_business_tax,
            "land_business_sale_tax": data.land_business_sale_tax,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }},
        upsert=True
    )
    return {"status": "success"}

# Admin Wallets for deposits
class AdminWallet(BaseModel):
    address: str
    percentage: float = 100
    mnemonic: str = ""

# Distribution Contract Address
class DistributionContract(BaseModel):
    contract_address: str

@admin_router.get("/wallets")
async def get_admin_wallets(admin: User = Depends(get_admin_user)):
    """Get admin wallets for distribution"""
    wallets = await db.admin_wallets.find({}, {"_id": 0, "mnemonic": 0}).to_list(100)
    total_percent = sum(w.get("percentage", 0) for w in wallets)
    return {"wallets": wallets, "total_percent": total_percent, "max_wallets": 5}

@admin_router.post("/wallets")
async def add_admin_wallet(data: AdminWallet, admin: User = Depends(get_current_admin_with_2fa)):
    """Add admin wallet for distribution"""
    # Check max 5 wallets
    count = await db.admin_wallets.count_documents({})
    if count >= 5:
        raise HTTPException(status_code=400, detail="Максимум 5 кошельков для распределения")
    
    # Check total percent doesn't exceed 100
    wallets = await db.admin_wallets.find({}, {"_id": 0}).to_list(100)
    current_total = sum(w.get("percentage", 0) for w in wallets)
    if current_total + data.percentage > 100:
        raise HTTPException(status_code=400, detail=f"Общий процент превышает 100%. Доступно: {100 - current_total}%")
    
    wallet_id = str(uuid.uuid4())
    from mnemonic_crypto import encrypt_mnemonic
    wallet = {
        "id": wallet_id,
        "address": data.address,
        "percentage": data.percentage,
        "mnemonic": encrypt_mnemonic(data.mnemonic),
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.admin_wallets.insert_one(wallet)
    return {"wallet": {"id": wallet_id, "address": data.address, "percentage": data.percentage}}

@admin_router.put("/wallets/{wallet_id}")
async def update_admin_wallet(wallet_id: str, data: AdminWallet, admin: User = Depends(get_current_admin_with_2fa)):
    """Update admin wallet percentage"""
    wallet = await db.admin_wallets.find_one({"id": wallet_id}, {"_id": 0})
    if not wallet:
        raise HTTPException(status_code=404, detail="Кошелёк не найден")
    
    # Calculate new total excluding this wallet
    wallets = await db.admin_wallets.find({"id": {"$ne": wallet_id}}, {"_id": 0}).to_list(100)
    other_total = sum(w.get("percentage", 0) for w in wallets)
    
    if other_total + data.percentage > 100:
        raise HTTPException(status_code=400, detail=f"Общий процент превышает 100%. Доступно: {100 - other_total}%")
    
    await db.admin_wallets.update_one(
        {"id": wallet_id},
        {"$set": {"percentage": data.percentage, "address": data.address}}
    )
    return {"status": "updated"}

@admin_router.delete("/wallets/{wallet_id}")
async def delete_admin_wallet(wallet_id: str, admin: User = Depends(get_current_admin_with_2fa)):
    """Delete admin wallet"""
    await db.admin_wallets.delete_one({"id": wallet_id})
    return {"status": "deleted"}

# Distribution Contract Address
@admin_router.get("/distribution-contract")
async def get_distribution_contract(admin: User = Depends(get_admin_user)):
    """Get distribution smart contract address"""
    settings = await db.admin_settings.find_one({"type": "distribution_contract"}, {"_id": 0})
    if not settings:
        return {"contract_address": "", "configured": False}
    return {
        "contract_address": settings.get("contract_address", ""),
        "configured": bool(settings.get("contract_address"))
    }

@admin_router.post("/distribution-contract")
async def save_distribution_contract(data: DistributionContract, admin: User = Depends(get_admin_user)):
    """Save distribution smart contract address"""
    await db.admin_settings.update_one(
        {"type": "distribution_contract"},
        {"$set": {
            "type": "distribution_contract",
            "contract_address": data.contract_address,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }},
        upsert=True
    )
    return {"status": "success", "contract_address": data.contract_address}

# ==================== CONTRACT DEPLOYER ====================

class DeployerWalletData(BaseModel):
    mnemonic: str
    network: str = "mainnet"

class AddContractWalletData(BaseModel):
    wallet_address: str
    percent: int

@admin_router.get("/contract-deployer")
async def get_contract_deployer_info(admin: User = Depends(get_admin_user)):
    """Get contract deployer wallet info"""
    deployer = get_contract_deployer(db)
    settings = await deployer.get_deployer_wallet()
    
    if not settings:
        return {"configured": False}
    
    address = settings.get("address", "")
    network = settings.get("network", "mainnet")
    
    # Get balance
    balance = 0.0
    if address:
        try:
            balance = await deployer.get_wallet_balance(address, network)
        except Exception:
            pass
    
    return {
        "configured": True,
        "address": address,
        "network": network,
        "balance": balance,
        "has_mnemonic": bool(settings.get("mnemonic"))
    }

@admin_router.post("/contract-deployer")
async def save_contract_deployer(data: DeployerWalletData, admin: User = Depends(get_current_admin_with_2fa)):
    """Save contract deployer wallet mnemonic"""
    deployer = get_contract_deployer(db)
    
    try:
        result = await deployer.save_deployer_wallet(data.mnemonic, data.network)
        return {"status": "success", **result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@admin_router.delete("/contract-deployer")
async def delete_contract_deployer(admin: User = Depends(get_current_admin_with_2fa)):
    """Delete contract deployer wallet configuration"""
    deployer = get_contract_deployer(db)
    result = await deployer.delete_deployer_wallet()
    return result

@admin_router.post("/contract-deployer/deploy")
async def deploy_distribution_contract(admin: User = Depends(require_scope("finance"))):
    """Deploy the FundDistributor smart contract"""
    deployer = get_contract_deployer(db)
    
    try:
        result = await deployer.deploy_contract()
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Deploy error: {e}")
        raise HTTPException(status_code=500, detail=f"Deploy failed: {str(e)}")

class SaveContractAddressData(BaseModel):
    contract_address: str

@admin_router.post("/contract-deployer/save-address")
async def save_deployed_contract_address(data: SaveContractAddressData, admin: User = Depends(get_admin_user)):
    """Save deployed contract address (after manual deploy)"""
    deployer = get_contract_deployer(db)
    
    try:
        result = await deployer.save_contract_address(data.contract_address)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@admin_router.get("/contract-info")
async def get_contract_full_info(admin: User = Depends(get_admin_user)):
    """Get full distribution contract information"""
    deployer = get_contract_deployer(db)
    
    try:
        info = await deployer.get_contract_info()
        return info
    except Exception as e:
        logger.error(f"Error getting contract info: {e}")
        return {"configured": False, "error": str(e)}

@admin_router.post("/contract/add-wallet")
async def add_wallet_to_distribution_contract(data: AddContractWalletData, admin: User = Depends(get_admin_user)):
    """Add wallet to distribution contract on-chain"""
    deployer = get_contract_deployer(db)
    
    try:
        result = await deployer.add_wallet_to_contract(data.wallet_address, data.percent)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error adding wallet to contract: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@admin_router.post("/contract/add-wallet-onchain")
async def add_wallet_to_contract_onchain(data: AddContractWalletData, admin: User = Depends(get_admin_user)):
    """Add wallet to distribution contract ON-CHAIN via blockchain transaction"""
    deployer = get_contract_deployer(db)
    
    try:
        result = await deployer.add_wallet_onchain(data.wallet_address, data.percent)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error adding wallet on-chain: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class BuildPayloadsRequest(BaseModel):
    wallets: list

@admin_router.post("/contract/build-add-wallet-payloads")
async def build_add_wallet_payloads(data: BuildPayloadsRequest, admin: User = Depends(get_admin_user)):
    """Build AddWallet message payloads for TonConnect"""
    from tonsdk.boc import begin_cell
    from tonsdk.utils import Address
    import base64
    from contract_opcodes import get_opcode
    
    # Get opcode from contract_opcodes
    add_wallet_op = get_opcode("AddWallet")
    
    logger.info(f"Building AddWallet payloads with opcode: {hex(add_wallet_op)} ({add_wallet_op})")
    
    payloads = []
    for wallet_data in data.wallets:
        try:
            addr = Address(wallet_data["address"])
            percent = int(wallet_data["percent"])
            
            # Build AddWallet message cell
            # Tact format: op (32 bits) + address + percent (8 bits)
            cell = begin_cell()
            cell.store_uint(add_wallet_op, 32)  # op code from compiled contract
            cell.store_address(addr)             # address
            cell.store_uint(percent, 8)          # percent as uint8
            cell = cell.end_cell()
            
            # Convert to base64 BOC
            boc_bytes = cell.to_boc()
            payload_b64 = base64.b64encode(boc_bytes).decode()
            
            logger.info(f"Built payload for {wallet_data['address'][:20]}..., percent={percent}, opcode={hex(add_wallet_op)}")
            
            payloads.append({
                "address": wallet_data["address"],
                "percent": percent,
                "payload": payload_b64,
                "opcode": hex(add_wallet_op)
            })
        except Exception as e:
            logger.error(f"Error building payload for {wallet_data}: {e}")
            raise HTTPException(status_code=400, detail=f"Invalid wallet address: {wallet_data.get('address')}")
    
    return {"payloads": payloads, "opcode_used": hex(add_wallet_op)}

# Build single AddWallet payload
class SingleWalletRequest(BaseModel):
    address: str
    percent: int

@admin_router.post("/contract/build-add-wallet-payload")
async def build_single_add_wallet_payload(data: SingleWalletRequest, admin: User = Depends(get_admin_user)):
    """Build single AddWallet message payload"""
    from tonsdk.boc import begin_cell
    from tonsdk.utils import Address
    import base64
    from contract_opcodes import get_opcode
    
    # AddWallet opcode from contract
    add_wallet_op = get_opcode("AddWallet")
    
    try:
        addr = Address(data.address)
        cell = begin_cell()
        cell.store_uint(add_wallet_op, 32)
        cell.store_address(addr)
        cell.store_uint(data.percent, 8)
        cell = cell.end_cell()
        
        payload_b64 = base64.b64encode(cell.to_boc()).decode()
        return {"payload": payload_b64, "opcode": hex(add_wallet_op)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# Build RemoveWallet payload
@admin_router.post("/contract/build-remove-wallet-payload")
async def build_remove_wallet_payload(data: SingleWalletRequest, admin: User = Depends(get_admin_user)):
    """Build RemoveWallet message payload"""
    from tonsdk.boc import begin_cell
    from tonsdk.utils import Address
    import base64
    from contract_opcodes import get_opcode
    
    # RemoveWallet opcode from contract
    remove_wallet_op = get_opcode("RemoveWallet")
    
    try:
        addr = Address(data.address)
        cell = begin_cell()
        cell.store_uint(remove_wallet_op, 32)
        cell.store_address(addr)
        cell = cell.end_cell()
        
        payload_b64 = base64.b64encode(cell.to_boc()).decode()
        return {"payload": payload_b64, "opcode": hex(remove_wallet_op)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# Build UpdateWalletPercent payload
@admin_router.post("/contract/build-update-wallet-payload")
async def build_update_wallet_payload(data: SingleWalletRequest, admin: User = Depends(get_admin_user)):
    """Build UpdateWalletPercent message payload"""
    from tonsdk.boc import begin_cell
    from tonsdk.utils import Address
    import base64
    from contract_opcodes import get_opcode
    
    # UpdateWalletPercent opcode from contract
    update_wallet_op = get_opcode("UpdateWalletPercent")
    
    try:
        addr = Address(data.address)
        cell = begin_cell()
        cell.store_uint(update_wallet_op, 32)
        cell.store_address(addr)
        cell.store_uint(data.percent, 8)  # newPercent
        cell = cell.end_cell()
        
        payload_b64 = base64.b64encode(cell.to_boc()).decode()
        return {"payload": payload_b64, "opcode": hex(update_wallet_op)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# Simple text comment payload (for testing)
@admin_router.post("/contract/build-simple-payload")
async def build_simple_payload(admin: User = Depends(get_admin_user)):
    """Build simple text comment payload for testing"""
    from tonsdk.boc import begin_cell
    import base64
    
    # Simple text comment
    cell = begin_cell()
    cell.store_uint(0, 32)  # op=0 means text comment
    cell.store_string("Test message")
    cell = cell.end_cell()
    
    payload_b64 = base64.b64encode(cell.to_boc()).decode()
    return {"payload": payload_b64, "type": "text_comment"}

class OwnerWithdrawRequest(BaseModel):
    to_address: str
    amount: float  # Amount in TON to withdraw (0 = all)

@admin_router.post("/contract/build-owner-withdraw-payload")
async def build_owner_withdraw_payload(data: OwnerWithdrawRequest, admin: User = Depends(get_admin_user)):
    """Build WithdrawEmergency message payload to withdraw funds from contract"""
    from tonsdk.boc import begin_cell
    from tonsdk.utils import Address, to_nano
    import base64
    from contract_opcodes import get_opcode
    
    # Use correct opcode from contract
    withdraw_op = get_opcode("WithdrawEmergency")  # 0xBF8D989E = 3214380190
    
    try:
        dest_addr = Address(data.to_address)
        amount_nano = to_nano(data.amount, "ton") if data.amount > 0 else 0
        
        cell = begin_cell()
        cell.store_uint(withdraw_op, 32)  # op code
        cell.store_address(dest_addr)  # destination address
        cell.store_coins(amount_nano)  # amount (0 = withdraw all)
        cell = cell.end_cell()
        
        payload_b64 = base64.b64encode(cell.to_boc()).decode()
        return {
            "payload": payload_b64,
            "to_address": data.to_address,
            "amount_ton": data.amount,
            "opcode": hex(withdraw_op)
        }
    except Exception as e:
        logger.error(f"Error building WithdrawEmergency payload: {e}")
        raise HTTPException(status_code=400, detail=str(e))

# Commission endpoint removed per user request

class OwnerDistributeRequest(BaseModel):
    total_amount: float  # in TON
    wallets: list  # [{address, percent}, ...]

@admin_router.post("/contract/build-owner-distribute-payload")
async def build_owner_distribute_payload(data: OwnerDistributeRequest, admin: User = Depends(get_admin_user)):
    """Build OwnerDistribute message payload for manual distribution by owner"""
    from tonsdk.boc import begin_cell
    from tonsdk.utils import Address, to_nano
    import base64
    
    if len(data.wallets) < 1 or len(data.wallets) > 5:
        raise HTTPException(status_code=400, detail="Must have 1-5 wallets")
    
    total_percent = sum(w.get("percent", 0) for w in data.wallets)
    if total_percent != 100:
        raise HTTPException(status_code=400, detail=f"Percents must sum to 100, got {total_percent}")
    
    # Correct opcode from compiled Tact contract
    # OwnerDistribute: 3235229450 (0xC0D4730A)
    owner_distribute_op = 3235229450
    
    try:
        # Convert TON to nanotons
        total_amount_nano = to_nano(data.total_amount, "ton")
        
        # Build message cell
        cell = begin_cell()
        cell.store_uint(owner_distribute_op, 32)  # op code
        cell.store_coins(total_amount_nano)  # totalAmount
        cell.store_uint(len(data.wallets), 8)  # count
        
        # Pad wallets to 5 (with null addresses for unused slots)
        wallets_padded = data.wallets + [{"address": None, "percent": 0}] * (5 - len(data.wallets))
        
        for i, w in enumerate(wallets_padded):
            if w.get("address"):
                addr = Address(w["address"])
                cell.store_address(addr)
            else:
                # Store null address (addr_none)
                cell.store_uint(0, 2)  # addr_none tag
            cell.store_uint(w.get("percent", 0), 8)
        
        cell = cell.end_cell()
        payload_b64 = base64.b64encode(cell.to_boc()).decode()
        
        return {
            "payload": payload_b64,
            "total_amount_ton": data.total_amount,
            "wallets_count": len(data.wallets),
            "opcode": hex(owner_distribute_op)
        }
        
    except Exception as e:
        logger.error(f"Error building OwnerDistribute payload: {e}")
        raise HTTPException(status_code=400, detail=str(e))

# Cache for on-chain state to avoid rate limiting
_onchain_state_cache = {"data": None, "timestamp": None}

@admin_router.get("/contract/onchain-state")
async def get_contract_onchain_state(admin: User = Depends(get_admin_user)):
    """Get current on-chain state of the smart contract including wallets"""
    import httpx
    from tonsdk.utils import Address
    global _onchain_state_cache
    
    # Check cache (valid for 30 seconds)
    if _onchain_state_cache["data"] and _onchain_state_cache["timestamp"]:
        cache_age = (datetime.now(timezone.utc) - _onchain_state_cache["timestamp"]).total_seconds()
        if cache_age < 30:
            logger.info(f"Returning cached on-chain state (age: {cache_age:.1f}s)")
            return _onchain_state_cache["data"]
    
    # Get contract address
    contract = await db.admin_settings.find_one({"type": "distribution_contract"})
    if not contract or not contract.get("contract_address"):
        return {"configured": False, "error": "Contract not deployed"}
    
    contract_address = contract["contract_address"]
    
    try:
        import asyncio
        
        async with httpx.AsyncClient(timeout=30) as client:
            # 1. Get wallet count
            wallet_count_resp = await client.post(
                "https://toncenter.com/api/v2/runGetMethod",
                json={
                    "address": contract_address,
                    "method": "getWalletCount",
                    "stack": []
                }
            )
            wallet_count_data = wallet_count_resp.json()
            wallet_count = 0
            if wallet_count_data.get("ok") and isinstance(wallet_count_data.get("result"), dict) and wallet_count_data.get("result", {}).get("exit_code") == 0:
                stack = wallet_count_data.get("result", {}).get("stack", [])
                if stack and len(stack) > 0:
                    wallet_count = int(stack[0][1], 16) if stack[0][0] == "num" else 0
            
            await asyncio.sleep(0.5)  # Delay to avoid rate limit
            
            # 2. Get total percent
            total_percent_resp = await client.post(
                "https://toncenter.com/api/v2/runGetMethod",
                json={
                    "address": contract_address,
                    "method": "getTotalPercent",
                    "stack": []
                }
            )
            total_percent_data = total_percent_resp.json()
            total_percent = 0
            if total_percent_data.get("ok") and isinstance(total_percent_data.get("result"), dict) and total_percent_data.get("result", {}).get("exit_code") == 0:
                stack = total_percent_data.get("result", {}).get("stack", [])
                if stack and len(stack) > 0:
                    total_percent = int(stack[0][1], 16) if stack[0][0] == "num" else 0
            
            await asyncio.sleep(0.5)  # Delay to avoid rate limit
            
            # 3. Get balance
            balance_resp = await client.get(
                f"https://toncenter.com/api/v2/getAddressBalance?address={contract_address}"
            )
            balance_data = balance_resp.json()
            balance = int(balance_data.get("result", 0)) / 1e9 if balance_data.get("ok") else 0
            
            await asyncio.sleep(0.5)  # Delay to avoid rate limit
            
            # 4. Try to get all wallets using getAllWallets
            wallets = []
            try:
                all_wallets_resp = await client.post(
                    "https://toncenter.com/api/v2/runGetMethod",
                    json={
                        "address": contract_address,
                        "method": "getAllWallets",
                        "stack": []
                    }
                )
                all_wallets_data = all_wallets_resp.json()
                
                if all_wallets_data.get("ok") and all_wallets_data.get("result", {}).get("exit_code") == 0:
                    stack = all_wallets_data.get("result", {}).get("stack", [])
                    # Parse tuple/list of wallets
                    if stack:
                        logger.info(f"getAllWallets response stack: {stack}")
            except Exception as e:
                logger.warning(f"getAllWallets not available: {e}")
            
            # 5. Fallback - get wallets by index
            # Add delay between requests to avoid rate limiting
            import asyncio
            
            for i in range(min(wallet_count, 10)):  # Limit to 10 for safety
                max_retries = 3
                for retry in range(max_retries):
                    try:
                        # Add delay to avoid rate limit
                        if i > 0 or retry > 0:
                            await asyncio.sleep(0.5 + retry * 0.5)
                        
                        wallet_resp = await client.post(
                            "https://toncenter.com/api/v2/runGetMethod",
                            json={
                                "address": contract_address,
                                "method": "getWalletByIndex",
                                "stack": [["num", hex(i)]]
                            }
                        )
                        wallet_data = wallet_resp.json()
                        
                        # Check for rate limit
                        if wallet_data.get("code") == 429 or wallet_data.get("result") == "Ratelimit exceed":
                            logger.warning(f"Rate limit hit for wallet {i}, retry {retry+1}/{max_retries}")
                            if retry < max_retries - 1:
                                continue
                            else:
                                break
                        
                        if wallet_data.get("ok") and isinstance(wallet_data.get("result"), dict) and wallet_data.get("result", {}).get("exit_code") == 0:
                            stack = wallet_data.get("result", {}).get("stack", [])
                            logger.info(f"Wallet {i} raw stack: {stack}")
                            
                            wallet_info = {"index": i}
                            
                            # Parse stack data
                            for item in stack:
                                if item[0] == "num":
                                    val = int(item[1], 16)
                                    if 1 <= val <= 100 and "percent" not in wallet_info:
                                        wallet_info["percent"] = val
                                elif item[0] == "cell":
                                    # Try to parse address from cell
                                    cell_data = item[1]
                                    if isinstance(cell_data, dict):
                                        # New format with object
                                        obj = cell_data.get("object", {})
                                        data = obj.get("data", {})
                                        b64_data = data.get("b64", "")
                                        if b64_data:
                                            try:
                                                import base64
                                                raw_bytes = base64.b64decode(b64_data)
                                                logger.info(f"Raw address bytes (len={len(raw_bytes)}): {raw_bytes[:40].hex()}")
                                                
                                                if len(raw_bytes) >= 34:
                                                    first_byte = raw_bytes[0]
                                                    wc = 0  # Default basechain
                                                    if first_byte >= 0x80 and first_byte < 0xC0:
                                                        wc = 0
                                                    elif first_byte >= 0xC0:
                                                        wc = -1
                                                    
                                                    addr_hash = raw_bytes[1:33]
                                                    
                                                    try:
                                                        from tonsdk.utils import Address
                                                        addr_hex = f"{wc}:{addr_hash.hex()}"
                                                        addr = Address(addr_hex)
                                                        friendly_addr = addr.to_string(is_user_friendly=True, is_bounceable=False, is_url_safe=True)
                                                        wallet_info["address"] = friendly_addr
                                                        logger.info(f"Converted to friendly address: {friendly_addr}")
                                                    except Exception as addr_err:
                                                        logger.warning(f"Could not convert to friendly address: {addr_err}")
                                                        wallet_info["address_hash"] = addr_hash.hex()[:16] + "..." + addr_hash.hex()[-8:]
                                                    
                                                    wallet_info["workchain"] = wc
                                            except Exception as parse_err:
                                                logger.warning(f"Error parsing cell address: {parse_err}")
                                        wallet_info["cell_raw"] = cell_data.get("bytes", "")[:40] + "..."
                                    else:
                                        wallet_info["cell_data"] = str(cell_data)[:60]
                                elif item[0] == "slice":
                                    try:
                                        slice_data = item[1]
                                        if len(str(slice_data)) > 40:
                                            wallet_info["cell_data"] = f"slice:{str(slice_data)[:50]}..."
                                    except Exception:
                                        pass
                            
                            # If we didn't get percent from stack, try getWalletPercent
                            if "percent" not in wallet_info:
                                await asyncio.sleep(0.3)
                                try:
                                    percent_resp = await client.post(
                                        "https://toncenter.com/api/v2/runGetMethod",
                                        json={
                                            "address": contract_address,
                                            "method": "getWalletPercent", 
                                            "stack": [["num", hex(i)]]
                                        }
                                    )
                                    percent_data = percent_resp.json()
                                    if percent_data.get("ok") and isinstance(percent_data.get("result"), dict) and percent_data.get("result", {}).get("exit_code") == 0:
                                        pstack = percent_data.get("result", {}).get("stack", [])
                                        if pstack and pstack[0][0] == "num":
                                            wallet_info["percent"] = int(pstack[0][1], 16)
                                except Exception as pe:
                                    logger.warning(f"getWalletPercent error: {pe}")
                            
                            wallets.append(wallet_info)
                            break  # Success - exit retry loop
                        elif wallet_data.get("ok") and isinstance(wallet_data.get("result"), dict):
                            logger.warning(f"getWalletByIndex({i}) failed: exit_code={wallet_data.get('result', {}).get('exit_code')}")
                            break  # Don't retry on contract errors
                    except Exception as e:
                        logger.warning(f"Error getting wallet {i} (retry {retry+1}): {e}")
                        if retry >= max_retries - 1:
                            break
            
            result = {
                "configured": True,
                "contract_address": contract_address,
                "onchain_data": {
                    "wallet_count": wallet_count,
                    "total_percent": total_percent,
                    "balance_ton": balance,
                    "wallets": wallets
                }
            }
            
            # Cache the result
            _onchain_state_cache["data"] = result
            _onchain_state_cache["timestamp"] = datetime.now(timezone.utc)
            
            return result
            
    except Exception as e:
        logger.error(f"Error fetching on-chain state: {e}")
        # Return cached data if available
        if _onchain_state_cache["data"]:
            logger.info("Returning cached data after error")
            return _onchain_state_cache["data"]
        return {
            "configured": True,
            "contract_address": contract_address,
            "error": str(e)
        }

# Sender Wallet (for withdrawals)
class SenderWalletData(BaseModel):
    address: str
    mnemonic: Optional[str] = None

@admin_router.get("/sender-wallet")
async def get_sender_wallet(admin: User = Depends(get_admin_user)):
    """Get sender wallet for withdrawals"""
    wallet = await db.admin_settings.find_one({"type": "sender_wallet"}, {"_id": 0})
    if not wallet:
        return {"address": "", "has_mnemonic": False}
    return {
        "address": wallet.get("address", ""),
        "has_mnemonic": bool(wallet.get("mnemonic"))
    }

@admin_router.post("/sender-wallet")
async def save_sender_wallet(data: SenderWalletData, admin: User = Depends(require_scope("finance"))):
    """Save sender wallet for withdrawals"""
    update_data = {
        "type": "sender_wallet",
        "address": data.address,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    
    # Only update mnemonic if provided
    if data.mnemonic:
        update_data["mnemonic"] = data.mnemonic
    
    await db.admin_settings.update_one(
        {"type": "sender_wallet"},
        {"$set": update_data},
        upsert=True
    )
    
    return {"status": "success"}

# User resource management
class UserResourcesUpdate(BaseModel):
    resources: dict

@admin_router.post("/users/{user_id}/resources")
async def update_user_resources(user_id: str, data: UserResourcesUpdate, admin: User = Depends(get_admin_user)):
    """Update user resources"""
    await db.users.update_one(
        {"id": user_id},
        {"$set": {"resources": data.resources, "resources_updated_at": datetime.now(timezone.utc).isoformat()}}
    )
    return {"status": "success"}

class PromoCreateRequest(BaseModel):
    name: str
    code: str = ""
    amount: float
    max_uses: int = 100

@admin_router.post("/promo/create")
async def admin_create_promo(data: PromoCreateRequest, admin: User = Depends(get_admin_user)):
    """Create promo code"""
    code = data.code.upper().strip() if data.code else data.name.upper().replace(" ", "")
    promo = {
        "id": str(uuid.uuid4()),
        "name": data.name,
        "code": code,
        "amount": data.amount,
        "max_uses": data.max_uses,
        "current_uses": 0,
        "is_active": True,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.promos.insert_one(promo)
    promo.pop("_id", None)
    return promo

@admin_router.get("/promos")
async def admin_get_promos(admin: User = Depends(get_admin_user)):
    """Get all promo codes"""
    promos = await db.promos.find({}, {"_id": 0}).to_list(100)
    return {"promos": promos}

@admin_router.delete("/promo/{promo_id}")
async def admin_delete_promo(promo_id: str, admin: User = Depends(get_admin_user)):
    """Delete a promo code"""
    result = await db.promos.delete_one({"id": promo_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Промокод не найден")
    # Also delete usage records
    await db.promo_uses.delete_many({"promo_id": promo_id})
    return {"status": "deleted", "promo_id": promo_id}

class AnnouncementButton(BaseModel):
    text: str
    url: str

class AnnouncementTranslation(BaseModel):
    title: Optional[str] = ""
    message: str
    image_url: Optional[str] = None
    buttons: List[AnnouncementButton] = []

class AnnouncementPayload(BaseModel):
    title: Optional[str] = ""
    # `message` is optional at the top level so that admins can broadcast in
    # multi-language mode (`translations`) without also providing a fallback
    # top-level message. When `translations` is empty the handler will still
    # enforce that `message` is non-empty (returns 400).
    message: Optional[str] = ""
    lang: str = "all"
    image_url: Optional[str] = None  # Optional image (URL or data: URI)
    buttons: List[AnnouncementButton] = []
    # Optional scheduled publish time (ISO UTC). If set and in the future, the
    # announcement is stored as "scheduled" and published by the background job.
    scheduled_at: Optional[str] = None
    # Multi-language broadcast (optional): if provided, each user receives the
    # variant matching their preferred language. Recognised languages are the
    # 8 languages supported across the project + bot:
    # gb (English), ru, es, cn (Chinese), fr, de, jp (Japanese), kr (Korean).
    translations: Optional[Dict[str, AnnouncementTranslation]] = None


# Maps used to route per-user variants. The project's user profile uses ISO-ish
# codes (`en`, `zh`, `ja`, `ko`); the admin broadcast form uses the aliases
# from the user requirement (`gb`, `cn`, `jp`, `kr`). Both sides agree on
# ru/es/fr/de. The maps below are the single source of truth.
BROADCAST_LANG_ALIASES = {
    "gb": "en", "cn": "zh", "jp": "ja", "kr": "ko",
    # identity mappings for the rest so lookup never fails
    "en": "en", "ru": "ru", "es": "es", "zh": "zh",
    "fr": "fr", "de": "de", "ja": "ja", "ko": "ko",
}


def _normalize_broadcast_lang(code: str) -> str:
    if not code:
        return "en"
    c = str(code).lower().strip()
    return BROADCAST_LANG_ALIASES.get(c, c)


def _pick_translation(translations: dict, target_lang: str) -> dict:
    """Return the best variant for the requested target language.
    Falls back to English → Russian → first available."""
    if not translations:
        return {}
    # Normalise keys once — accept both `gb` and `en` variants transparently.
    norm = {}
    for k, v in translations.items():
        norm[_normalize_broadcast_lang(k)] = v
    tl = _normalize_broadcast_lang(target_lang)
    if tl in norm:
        return norm[tl]
    for fallback in ("en", "ru"):
        if fallback in norm:
            return norm[fallback]
    # last resort — return the first entry
    for v in norm.values():
        return v
    return {}


# ── HTML sanitization for Telegram ────────────────────────────────────────
# Telegram's parse_mode="HTML" only accepts a specific whitelist of tags. If
# the admin's message (which supports rich HTML for the in-app notification —
# <br>, <p>, <span>, <strong>, <em>, etc.) contains anything outside that
# whitelist, Telegram rejects the WHOLE message with HTTP 400 and the user
# never receives it. This was the reported bug: multi-language announcements
# reached the in-app notification center but disappeared from the bot AND the
# admin channel.
#
# Telegram accepts (per https://core.telegram.org/bots/api#html-style):
#   <b>, <strong>, <i>, <em>, <u>, <ins>, <s>, <strike>, <del>,
#   <a href="...">, <code>, <pre>, <tg-spoiler>, <span class="tg-spoiler">,
#   <blockquote>, <blockquote expandable>
# Everything else is stripped (tags removed, INNER TEXT kept). <br> family is
# translated to a real newline. Common block-level tags (<p>, <div>) get a
# trailing newline so the rendered text keeps its visual paragraphing.

_TG_ALLOWED_TAGS = {
    "b", "strong", "i", "em", "u", "ins", "s", "strike", "del",
    "a", "code", "pre", "blockquote", "tg-spoiler",
}


def sanitize_html_for_telegram(text: str) -> str:
    """Return `text` reduced to tags Telegram's HTML parse mode accepts.

    - <br>, <br/>, <br /> → newline.
    - <p>...</p>, <div>...</div> → keep content + append newline on close.
    - <span> that isn't the tg-spoiler class → stripped (content kept).
    - <a href=".."> keeps only the `href` attribute.
    - All other tags → stripped (content kept).
    - Bracketed sequences that don't look like a real tag are left alone,
      so plain text like "2 < 3" is preserved.
    """
    import re
    if not text:
        return ""
    s = str(text)
    # 1) <br> family → newline
    s = re.sub(r"<\s*br\s*/?\s*>", "\n", s, flags=re.IGNORECASE)
    # 2) </p> and </div> → newline (paragraph breaks preserved visually)
    s = re.sub(r"</\s*(p|div)\s*>", "\n", s, flags=re.IGNORECASE)

    def _clean(match: "re.Match") -> str:
        raw = match.group(0)
        closing = match.group(1) == "/"
        tag = match.group(2).lower()
        attrs = match.group(3) or ""

        # tg-spoiler via <span class="tg-spoiler">…</span> is the ONE <span>
        # variant Telegram accepts; rewrite it to the canonical <tg-spoiler>.
        if tag == "span":
            if closing:
                return "</tg-spoiler>" if "tg-spoiler" in raw else ""
            if re.search(r'class\s*=\s*[\"\']?[^\"\'>]*tg-spoiler', attrs, flags=re.IGNORECASE):
                return "<tg-spoiler>"
            return ""

        if tag not in _TG_ALLOWED_TAGS:
            return ""  # unknown/unsupported tag → drop, keep inner text

        if closing:
            return f"</{tag}>"

        # For <a>, keep only href="..."; strip everything else.
        if tag == "a":
            m = re.search(r"""href\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", attrs, flags=re.IGNORECASE)
            href = (m.group(1) or m.group(2) or m.group(3)) if m else ""
            if not href:
                return ""  # anchor without href → drop tag, keep content
            # Escape the href minimally so it can't break the attribute
            safe = href.replace('"', "%22")
            return f'<a href="{safe}">'

        # For every other allowed tag: drop attributes to stay safe.
        return f"<{tag}>"

    # Matches: <tag ...>, </tag> — capture (closing?, tag, rest)
    tag_re = re.compile(r"<\s*(/?)\s*([a-zA-Z][a-zA-Z0-9-]*)([^>]*)>")
    s = tag_re.sub(_clean, s)

    # Collapse 3+ blank lines to 2 (Telegram doesn't render more anyway).
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s


def _strip_all_html(text: str) -> str:
    """Remove ALL HTML tags, leaving only the inner text. Used as a plain-text
    fallback when Telegram rejects an HTML payload (400) so the channel/user
    still receives the announcement text."""
    import re
    if not text:
        return ""
    return re.sub(r"<[^>]+>", "", str(text)).strip()


# Telegram caption cap for sendPhoto. A caption longer than this is rejected
# (or must be clipped, which can break an HTML tag and get the whole sendPhoto
# rejected with HTTP 400).
_TG_PHOTO_CAPTION_LIMIT = 1024


async def _tg_send_announcement(tg_bot, chat_id, caption: str, image, reply_markup=None) -> bool:
    """Deliver ONE announcement to ONE Telegram chat, ALWAYS keeping the photo
    TOGETHER with the text.

    Telegram's photo *caption* is capped at 1024 chars; the old code clipped it
    (often mid-HTML-tag), Telegram rejected the whole sendPhoto (HTTP 400), and
    the code fell back to a text-only sendMessage — dropping the image (the
    reported bug). Strategy that keeps image+text together:
      • no image             → sendMessage (plain-text retry on 400).
      • image, caption≤1024  → sendPhoto WITH caption (image+text, one message);
                               plain-caption retry on failure.
      • image, caption>1024  → for an HTTP(S) image, ONE sendMessage with the
                               image shown as a LARGE PREVIEW ABOVE the full
                               text (no 1024 cap) — image+text stay together.
      • data: URI or preview fails → sendPhoto(no caption) + full text so both
                               still arrive.
    Returns True if anything was delivered."""
    caption = caption or ""
    is_url_image = isinstance(image, str) and image.startswith("http")

    async def _text(txt, markup, link_preview=None):
        ok = await tg_bot.send_message(chat_id, txt, reply_markup=markup, link_preview_options=link_preview)
        if ok is False:
            ok = await tg_bot.send_message(chat_id, _strip_all_html(txt), parse_mode="", reply_markup=markup, link_preview_options=link_preview)
        return ok

    def _preview(url):
        # Large image rendered ABOVE the message text (Bot API 7.0+).
        return {"url": url, "prefer_large_media": True, "show_above_text": True}

    if not image:
        return await _text(caption, reply_markup)

    if len(caption) <= _TG_PHOTO_CAPTION_LIMIT:
        # Fits in a photo caption → image + text in a SINGLE photo message.
        ok = await tg_bot.send_photo(chat_id, image, caption=caption, reply_markup=reply_markup)
        if ok is False:
            ok = await tg_bot.send_photo(chat_id, image, caption=_strip_all_html(caption), parse_mode="", reply_markup=reply_markup)
        if ok is False and is_url_image:
            # Keep them together via a large preview above the text.
            ok = await _text(caption, reply_markup, link_preview=_preview(image))
        if ok is False:
            # Last resort — deliver the photo, then the text (both, never lost).
            ok_photo = await tg_bot.send_photo(chat_id, image, caption="")
            ok_text = await _text(caption, reply_markup)
            ok = bool(ok_photo or ok_text)
        return ok

    # Caption too long for a photo caption. Keep image+text TOGETHER in ONE
    # message using a large preview above the text (works for public URLs).
    if is_url_image:
        ok = await _text(caption, reply_markup, link_preview=_preview(image))
        if ok is not False:
            return ok
    # data: URI (no link preview) or preview failed → photo + full text.
    ok_photo = await tg_bot.send_photo(chat_id, image, caption="")
    ok_text = await _text(caption, reply_markup)
    return bool(ok_photo or ok_text)


# Only ONE broadcast fan-out may run at a time. A second «Отправить» click (or a
# scheduled publish overlapping a manual one) would otherwise spawn a parallel
# fan-out and multiply DB + Telegram load — the reported "server went down".
_broadcast_active = False


async def _run_announcement_guarded(announcement: dict):
    """Wrap the fan-out so a background exception is logged (never a silent
    'Task exception was never retrieved') and the active-flag is always reset."""
    global _broadcast_active
    try:
        await _publish_announcement(announcement)
    except Exception as e:
        logger.error(f"Announcement fan-out crashed: {e}", exc_info=True)
    finally:
        _broadcast_active = False


async def _publish_announcement(announcement: dict):
    """Side-effects of publishing an announcement: WebSocket broadcast,
    per-user notifications and Telegram fan-out. Reused by the create endpoint
    (publish-now) and by the scheduler (scheduled publish).

    Users are streamed in chunks of `USER_CHUNK` so a broadcast to 10 000+
    accounts doesn't blow up memory or block the event loop. Notifications are
    inserted per-chunk (`insert_many`) and Telegram fan-out is throttled to
    ~25 sends/sec — well under Bot API's 30 msg/sec global limit.

    If `announcement["translations"]` is present, each recipient receives the
    variant matching their language (project user.language for in-app, and
    telegram_mappings.language for Telegram). Otherwise the top-level fields
    are used for everyone (single-language broadcast).
    """
    default_title = announcement.get("title") or ""
    default_message = announcement.get("message") or ""
    default_image = announcement.get("image_url")
    default_buttons = announcement.get("buttons") or []
    translations = announcement.get("translations") or None

    # Broadcast via WebSocket (raw announcement; clients pick their translation).
    await manager.broadcast({"type": "announcement", "data": announcement})

    def _variant_for(lang: str):
        """Resolve (title, message, image_url, buttons) for a given user lang."""
        if translations:
            v = _pick_translation(translations, lang)
            return (
                (v.get("title") or "").strip() or default_title,
                v.get("message") or default_message,
                v.get("image_url") or default_image,
                v.get("buttons") or default_buttons,
            )
        return (default_title, default_message, default_image, default_buttons)

    # Try to lazy-import the bot here so we set it up once for the whole fan-out.
    tg_bot = None
    try:
        from telegram_bot import get_telegram_bot
        tg_bot = get_telegram_bot()
    except Exception:
        tg_bot = None

    # ── Channel post ───────────────────────────────────────────────────────
    # Besides the per-user fan-out, also publish the announcement ONCE into the
    # admin-configured Telegram channel (Промо → Телеграм бот → «Канал»).
    #
    # Per product requirement: the CHANNEL post is always in ENGLISH — we
    # pass "en" explicitly so `_variant_for` returns the English translation
    # when the admin provided one. When no English variant is available (only
    # Russian, etc.), `_pick_translation` still falls back to en → ru →
    # first, so we never silently skip the post.
    #
    # The message body is passed through `sanitize_html_for_telegram` so the
    # same rich formatting the admin typed for the in-app notification (bold,
    # italic, links, line breaks) reaches Telegram — previously any tag
    # outside Telegram's HTML whitelist (e.g. <br>, <p>, <span style>) caused
    # Telegram to reject the message with HTTP 400 and the channel would
    # receive nothing.
    try:
        _tg_settings = await db.admin_settings.find_one({"type": "telegram_bot"}, {"_id": 0}) or {}
        channel_id = (_tg_settings.get("channel_id") or "").strip()
        if not channel_id:
            _gs = await db.game_settings.find_one({"type": "telegram_settings"}, {"_id": 0}) or {}
            channel_id = (_gs.get("channel_id") or "").strip()
        if tg_bot and channel_id:
            # Force English variant for the channel.
            c_title, c_message, c_image, c_buttons = _variant_for("en")
            c_title = sanitize_html_for_telegram(c_title or "")
            c_message = sanitize_html_for_telegram(c_message or "")
            c_caption = f"<b>{c_title}</b>\n\n{c_message}" if c_title else c_message
            c_markup = None
            if c_buttons:
                c_markup = {"inline_keyboard": [[{"text": b["text"], "url": b["url"]}] for b in c_buttons]}
            try:
                # Robust delivery: keeps the photo even when the caption is long
                # or its HTML is rejected (see _tg_send_announcement).
                ok = await _tg_send_announcement(tg_bot, channel_id, c_caption, c_image, c_markup)
                if ok:
                    logger.info(f"Announcement posted to channel {channel_id}")
                else:
                    logger.warning(f"Channel post to {channel_id} returned falsy (bot not admin / invalid channel_id?)")
            except Exception as e:
                logger.warning(f"Failed to post announcement to channel {channel_id}: {e}")
    except Exception as e:
        logger.warning(f"Channel-post step skipped: {e}")

    USER_CHUNK = 500                 # DB read + Mongo insert batch
    # Sending rate is admin/env-configurable. Default 1200 msg/min (=20/s),
    # comfortably under Telegram Bot API's ~30/s global cap. We pace EACH send
    # by a fixed delay (smooth, not bursty) and also hard-cap at 25/s.
    try:
        _rate_per_min = int(os.environ.get("BROADCAST_RATE_PER_MIN", "1200"))
    except Exception:
        _rate_per_min = 1200
    _rate_per_min = max(1, min(_rate_per_min, 1500))  # sanity: 1..1500/min
    _per_msg_delay = max(60.0 / _rate_per_min, 1.0 / 25.0)  # never faster than 25/s
    now_iso = datetime.now(timezone.utc).isoformat()

    total_notifications = 0
    total_tg_sent = 0
    tg_batch: list = []              # (chat_id, user_lang) waiting to be sent

    # ---- delivery statistics, visible in the admin while the broadcast runs ----
    ann_id = announcement.get("id")
    stats = {"telegram_total": 0, "sent": 0, "blocked": 0, "not_found": 0, "failed": 0, "in_app": 0,
             "status": "running", "started_at": now_iso, "finished_at": None}
    try:
        stats["telegram_total"] = await db.users.count_documents({"telegram_chat_id": {"$nin": [None, ""]}}) if tg_bot else 0
    except Exception:
        pass

    async def _save_stats():
        if ann_id:
            try:
                await db.announcements.update_one({"id": ann_id}, {"$set": {"delivery": dict(stats)}})
            except Exception as _e:
                logger.debug(f"announcement stats save failed: {_e}")

    await _save_stats()
    _stop_reporter = asyncio.Event()

    async def _reporter():                              # flush counters to the DB once a second
        _t0 = asyncio.get_event_loop().time()
        while not _stop_reporter.is_set() and asyncio.get_event_loop().time() - _t0 < 6 * 3600:
            try:
                await asyncio.wait_for(_stop_reporter.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                await _save_stats()
    _reporter_task = asyncio.create_task(_reporter())

    # concurrent sending with a global pace: up to 20 requests in flight, a new one
    # starts every _per_msg_delay seconds (Telegram allows ~30 msg/s for a bot)
    _sem = asyncio.Semaphore(20)
    _pace = {"next": 0.0}
    _pace_lock = asyncio.Lock()

    async def _send_one(cid, fallback_lang, tg_lang_map):
        nonlocal total_tg_sent
        target_lang = tg_lang_map.get(str(cid)) or fallback_lang or "en"
        v_title, v_message, v_image, v_buttons = _variant_for(target_lang)
        v_title = sanitize_html_for_telegram(v_title or "")
        v_message = sanitize_html_for_telegram(v_message or "")
        tg_caption = f"<b>{v_title}</b>\n\n{v_message}" if v_title else v_message
        reply_markup = None
        if v_buttons:
            reply_markup = {"inline_keyboard": [[{"text": b["text"], "url": b["url"]}] for b in v_buttons]}
        async with _pace_lock:                          # global pace
            loop_now = asyncio.get_event_loop().time()
            wait = _pace["next"] - loop_now
            _pace["next"] = max(loop_now, _pace["next"]) + _per_msg_delay
        if wait > 0:
            await asyncio.sleep(wait)
        async with _sem:
            try:
                ok = await _tg_send_announcement(tg_bot, cid, tg_caption, v_image, reply_markup)
            except Exception as e:
                logger.warning(f"Failed to send announcement to {cid}: {e}")
                ok = False
        if ok:
            total_tg_sent += 1; stats["sent"] += 1
        else:
            kind = getattr(tg_bot, "last_failure", {}).get(str(cid), "error")
            stats["blocked" if kind == "blocked" else "not_found" if kind == "not_found" else "failed"] += 1

    async def _flush_tg(batch: list):
        """Send a batch of Telegram messages concurrently, respecting the pace."""
        if not tg_bot or not batch:
            return
        chat_ids_only = [c for (c, _l) in batch]
        tg_lang_map: dict = {}
        async for m in db.telegram_mappings.find(
            {"chat_id": {"$in": chat_ids_only}},
            {"_id": 0, "chat_id": 1, "language": 1, "tg_language_code": 1},
        ):
            tg_lang_map[str(m.get("chat_id"))] = (m.get("language") or m.get("tg_language_code") or "")
        await asyncio.gather(*[_send_one(cid, lang, tg_lang_map) for (cid, lang) in batch])

    # Stream users in chunks. Each Mongo document is small (id + telegram_chat_id
    # + language), so 500 docs ≈ few KB.
    cursor = db.users.find(
        {}, {"_id": 0, "id": 1, "telegram_chat_id": 1, "language": 1}
    ).batch_size(USER_CHUNK)

    chunk_users: list = []
    async for user in cursor:
        chunk_users.append(user)
        if len(chunk_users) < USER_CHUNK:
            continue
        # Process this chunk
        await _process_announcement_chunk(chunk_users, _variant_for, now_iso, tg_batch)
        total_notifications += len(chunk_users)
        stats["in_app"] = total_notifications
        chunk_users = []
        # Flush TG batch when it fills up to keep memory bounded.
        if len(tg_batch) >= USER_CHUNK:
            await _flush_tg(tg_batch)
            tg_batch = []

    # Tail
    if chunk_users:
        await _process_announcement_chunk(chunk_users, _variant_for, now_iso, tg_batch)
        total_notifications += len(chunk_users)

    if tg_batch:
        await _flush_tg(tg_batch)

    stats["in_app"] = total_notifications
    stats["status"] = "done"
    stats["finished_at"] = datetime.now(timezone.utc).isoformat()
    _stop_reporter.set()
    try:
        await _reporter_task
    except Exception:
        pass
    await _save_stats()
    logger.info(
        f"Announcement fan-out complete: {total_notifications} notifications, "
        f"{total_tg_sent}/{stats['telegram_total']} Telegram messages "
        f"(blocked {stats['blocked']}, not found {stats['not_found']}, failed {stats['failed']})"
    )


async def _process_announcement_chunk(chunk_users, variant_for, now_iso, tg_batch):
    """Insert notifications for one chunk of users and push WS events.
    Appends telegram recipients to `tg_batch` for the caller to flush."""
    notifications = []
    for user in chunk_users:
        user_id = user.get("id")
        if not user_id:
            continue
        user_lang = user.get("language") or "en"
        t_title, t_message, t_image, t_buttons = variant_for(user_lang)
        notifications.append({
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "title": t_title,
            "message": t_message,
            "type": "announcement",
            "priority": "info",
            "image_url": t_image,
            "buttons": t_buttons,
            "read": False,
            "telegram_sent": True,
            "created_at": now_iso,
        })
        chat_id = user.get("telegram_chat_id")
        if chat_id:
            tg_batch.append((chat_id, user_lang))

    if notifications:
        await db.notifications.insert_many(notifications)
        # Push WS notification per recipient — best-effort, ignore failures.
        for n in notifications:
            try:
                await manager.send_personal({"type": "notification_new", "notification": n}, n["user_id"])
            except Exception:
                pass


@admin_router.post("/announcement")
async def admin_create_announcement(
    payload: AnnouncementPayload,
    admin: User = Depends(get_admin_user),
):
    """Create announcement. Either publishes immediately (default) or schedules
    it for a future MSK time via `scheduled_at` (ISO UTC).

    Supports single-language mode (top-level `title`/`message`/`image_url`/
    `buttons`) or multi-language mode (a dict of language variants under
    `translations`, each with the same shape). Multi-language mode delivers the
    matching variant to each user based on their profile / bot language.
    """
    title = (payload.title or "").strip()
    message = (payload.message or "").strip()

    # Validate translations first so we don't require a top-level `message`
    # when the admin only filled per-language variants.
    translations_out: Optional[Dict[str, dict]] = None
    if payload.translations:
        translations_out = {}
        for lang_code, tr in payload.translations.items():
            norm_code = _normalize_broadcast_lang(lang_code)
            t_title = (tr.title or "").strip()
            t_msg = (tr.message or "").strip()
            if not t_msg:
                raise HTTPException(status_code=400, detail=f"Message is required for language {lang_code}")
            t_img = (tr.image_url or "").strip() or None
            t_buttons = []
            for b in (tr.buttons or [])[:8]:
                bt = (b.text or "").strip()
                bu = (b.url or "").strip()
                if bt and bu:
                    t_buttons.append({"text": bt[:60], "url": bu[:200]})
            translations_out[norm_code] = {
                "title": t_title,
                "message": t_msg,
                "image_url": t_img,
                "buttons": t_buttons,
            }
        # Use the first variant as the top-level default (for legacy consumers
        # and for the admin list view that shows one preview per announcement).
        if not message:
            first = next(iter(translations_out.values()))
            message = first.get("message") or ""
            if not title:
                title = first.get("title") or ""

    if not message:
        raise HTTPException(status_code=400, detail="Message is required")

    image_url = (payload.image_url or "").strip() or None
    # Sanitize buttons — drop empty rows, cap at 8 to keep the keyboard sane.
    buttons = []
    for b in (payload.buttons or [])[:8]:
        bt = (b.text or "").strip()
        bu = (b.url or "").strip()
        if bt and bu:
            buttons.append({"text": bt[:60], "url": bu[:200]})

    # Determine if this is a scheduled publish (future time) or publish-now.
    scheduled_at = None
    is_scheduled = False
    if payload.scheduled_at:
        try:
            sched_dt = datetime.fromisoformat(payload.scheduled_at.replace("Z", "+00:00"))
            if sched_dt.tzinfo is None:
                sched_dt = sched_dt.replace(tzinfo=timezone.utc)
            if sched_dt > datetime.now(timezone.utc):
                is_scheduled = True
                scheduled_at = sched_dt.astimezone(timezone.utc).isoformat()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid scheduled_at")

    announcement_id = str(uuid.uuid4())
    announcement = {
        "id": announcement_id,
        "title": title,
        "message": message,
        "lang": payload.lang or "all",
        "image_url": image_url,
        "buttons": buttons,
        "translations": translations_out,
        "status": "scheduled" if is_scheduled else "published",
        "scheduled_at": scheduled_at,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    # Insert a copy so Mongo doesn't mutate `_id` into the response object.
    await db.announcements.insert_one(announcement.copy())

    if not is_scheduled:
        # Run the fan-out in the BACKGROUND. For a large audience the Telegram
        # send is throttled (per-minute rate), so awaiting it here would keep the
        # HTTP request open for minutes — the reverse proxy (nginx/Cloudflare)
        # then kills the connection mid-fan-out and only some users get
        # delivered. Returning immediately lets the fan-out finish server-side.
        #
        # Guard: refuse to start a second fan-out while one is already running
        # (repeated clicks / scheduler overlap) — this is what previously piled
        # up load and took the server down. The check-and-set is atomic on the
        # single-threaded event loop (no await between them).
        global _broadcast_active
        if _broadcast_active:
            raise HTTPException(
                status_code=409,
                detail="Рассылка уже выполняется — дождитесь её завершения перед отправкой новой.",
            )
        _broadcast_active = True
        asyncio.create_task(_run_announcement_guarded(announcement.copy()))

    return announcement


@admin_router.delete("/announcement/{announcement_id}")
async def admin_delete_announcement(announcement_id: str, admin: User = Depends(get_admin_user)):
    """Delete an announcement. Used to cancel a scheduled (unpublished) one."""
    res = await db.announcements.delete_one({"id": announcement_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")
    return {"success": True}


# ─────────────────────────── Trading schedule (per-zone) ───────────────────────────
TRADING_ZONES = ["core", "center", "middle", "outer"]


class TradingSchedulePayload(BaseModel):
    zones: Dict[str, Optional[str]] = {}


@api_router.get("/trading-schedule")
async def get_trading_schedule():
    """Public: per-zone trading open times (ISO UTC strings or null)."""
    doc = await db.admin_settings.find_one({"type": "trading_schedule"}, {"_id": 0})
    zones = (doc or {}).get("zones") or {}
    return {"zones": {z: zones.get(z) for z in TRADING_ZONES}}


@admin_router.post("/trading-schedule")
async def set_trading_schedule(payload: TradingSchedulePayload, admin: User = Depends(get_admin_user)):
    """Admin: set per-zone trading open times. Accepts ISO UTC strings or null."""
    zones = {}
    for z in TRADING_ZONES:
        val = (payload.zones or {}).get(z)
        if not val:
            zones[z] = None
            continue
        try:
            dt = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            zones[z] = dt.astimezone(timezone.utc).isoformat()
        except Exception:
            raise HTTPException(status_code=400, detail=f"Invalid datetime for zone {z}")
    await db.admin_settings.update_one(
        {"type": "trading_schedule"},
        {"$set": {"zones": zones, "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    return {"zones": zones}


# ─────────────────────────── Presale (admin-curated first-sale lot) ───────────────────────────
# The presale flow lets admins hand-pick a set of plots on a map that will be
# offered for sale at a scheduled time. All OTHER cells that still carry a
# `pre_business` (i.e. would normally show a "Buy" button) get their button
# replaced with a labelled placeholder — `coming_epoch_2` / `sold_out` /
# `unavailable` — while the presale is active.
#
# Persistence: single doc in `admin_settings` with `type="presale"`.
# {
#   "type": "presale",
#   "map_id": "ton_island",
#   "businesses": [{"type":"helios","count":5}, ...]      # admin's draft
#   "selected_plots": [{"x":3,"y":2,"business_type":"helios"}, ...],
#   "unavailable_label": "coming_epoch_2"|"sold_out"|"unavailable",
#   "opens_at": ISO UTC | null,
#   "active": bool,
#   "approved_at": ISO | null,
#   "updated_at": ISO,
# }

PRESALE_LABELS = {"coming_epoch_2", "sold_out", "unavailable"}


class PresaleBusinessItem(BaseModel):
    type: str
    count: int


class PresaleSelectPayload(BaseModel):
    map_id: str = "ton_island"
    businesses: List[PresaleBusinessItem] = []


class PresaleApprovePayload(BaseModel):
    opens_at: Optional[str] = None
    unavailable_label: str = "coming_epoch_2"
    map_id: str = "ton_island"


async def _presale_get_doc():
    return await db.admin_settings.find_one({"type": "presale"}, {"_id": 0})


def _presale_public_view(doc: Optional[dict]) -> dict:
    # `buy_button_text` is always exposed (even when the presale is inactive)
    # because the map needs it to replace the Buy button on non-presale plots.
    btn = ((doc or {}).get("buy_button_text") or "")
    if not doc or not doc.get("active"):
        return {"active": False, "buy_button_text": btn}
    return {
        "active": True,
        "map_id": doc.get("map_id") or "ton_island",
        "opens_at": doc.get("opens_at"),
        "unavailable_label": doc.get("unavailable_label") or "coming_epoch_2",
        "selected_plots": doc.get("selected_plots") or [],
        "buy_button_text": btn,
    }


@api_router.get("/presale/config")
async def get_presale_config_public():
    """Public: current active presale config used by the map to render
    selected plots with a gold tint + countdown, and to swap the Buy button
    for the admin-picked placeholder on all other cells."""
    doc = await _presale_get_doc()
    return _presale_public_view(doc)


@admin_router.get("/presale")
async def admin_get_presale(admin: User = Depends(get_admin_user)):
    doc = await _presale_get_doc() or {}
    return {
        "map_id": doc.get("map_id") or "ton_island",
        "businesses": doc.get("businesses") or [],
        "selected_plots": doc.get("selected_plots") or [],
        "unavailable_label": doc.get("unavailable_label") or "coming_epoch_2",
        "opens_at": doc.get("opens_at"),
        "active": bool(doc.get("active")),
        "approved_at": doc.get("approved_at"),
        "buy_button_text": doc.get("buy_button_text") or "",
    }


@admin_router.get("/presale/ready-buyers")
async def admin_presale_ready_buyers(admin: User = Depends(get_admin_user)):
    """Count of users whose in-app balance is ≥ 5 TON (i.e. topped up and
    ready to buy a plot). Shown in the admin panel as
    'Пополненных балансов: N'."""
    count = await db.users.count_documents({"balance_ton": {"$gte": 5}})
    return {"count": int(count)}


@admin_router.post("/presale/select-plots")
async def admin_presale_select_plots(payload: PresaleSelectPayload, admin: User = Depends(get_admin_user)):
    """Randomly pick, on the requested map, exactly `count` free cells for
    each requested business type. Persists the picks as the draft
    `selected_plots` list. Overwrites any previous selection.

    A cell counts as free only if:
      • it has a `pre_business` and is not `is_empty`,
      • no user has purchased it (checked against the `plots` collection —
        island cell docs don't track ownership themselves),
      • it is not already in the current draft's `selected_plots` (guards
        against duplicate picks within the same request).

    Additionally, the same business type cannot be requested twice in a
    single payload, and `count` cannot exceed the available free supply.
    """
    map_id = (payload.map_id or "ton_island").strip() or "ton_island"
    island = await db.islands.find_one({"id": map_id}, {"_id": 0, "cells": 1})
    if not island or not island.get("cells"):
        raise HTTPException(status_code=404, detail=f"Map '{map_id}' not found")

    # Load coords of every cell that has been purchased by a real user.
    purchased_coords: set = set()
    async for p in db.plots.find(
        {"island_id": map_id, "owner": {"$type": "string"}},
        {"_id": 0, "x": 1, "y": 1},
    ):
        purchased_coords.add((p.get("x"), p.get("y")))

    # Group free cells by pre_business type. A cell is free if it has NO
    # purchased plot record AND is NOT flagged empty.
    free_by_type: Dict[str, List[Dict[str, int]]] = {}
    for cell in island["cells"]:
        if cell.get("is_empty"):
            continue
        biz = cell.get("pre_business")
        if not biz:
            continue
        if (cell.get("x"), cell.get("y")) in purchased_coords:
            continue
        free_by_type.setdefault(biz, []).append({"x": cell["x"], "y": cell["y"]})

    # Enforce: no duplicate business type in a single request.
    seen_types: set = set()
    for item in payload.businesses:
        if not item.type:
            continue
        if item.type in seen_types:
            raise HTTPException(
                status_code=400,
                detail=f"Вид бизнеса '{item.type}' указан несколько раз — уберите дубликаты",
            )
        seen_types.add(item.type)

    # Enforce: count ≤ available free supply for each business type.
    for item in payload.businesses:
        want = max(0, int(item.count or 0))
        if want <= 0:
            continue
        available = len(free_by_type.get(item.type, []))
        if want > available:
            raise HTTPException(
                status_code=400,
                detail=f"'{item.type}': доступно только {available} свободных полей, запрошено {want}",
            )

    selected: List[Dict[str, Any]] = []
    errors: List[str] = []
    import random as _random
    for item in payload.businesses:
        want = max(0, int(item.count or 0))
        if want <= 0:
            continue
        pool = free_by_type.get(item.type, [])
        take = _random.sample(pool, want)
        for c in take:
            selected.append({"x": c["x"], "y": c["y"], "business_type": item.type})

    now_iso = datetime.now(timezone.utc).isoformat()
    await db.admin_settings.update_one(
        {"type": "presale"},
        {"$set": {
            "map_id": map_id,
            "businesses": [item.dict() for item in payload.businesses],
            "selected_plots": selected,
            "updated_at": now_iso,
        }},
        upsert=True,
    )
    return {"ok": True, "selected_plots": selected, "warnings": errors}


@admin_router.post("/presale/approve")
async def admin_presale_approve(payload: PresaleApprovePayload, admin: User = Depends(get_admin_user)):
    """Activate the presale: locks in the previously-selected plots, saves
    `opens_at` (ISO UTC) and the label to show on all other cells."""
    label = payload.unavailable_label
    if label not in PRESALE_LABELS:
        raise HTTPException(status_code=400, detail=f"unavailable_label must be one of {sorted(PRESALE_LABELS)}")
    opens_iso: Optional[str] = None
    if payload.opens_at:
        try:
            dt = datetime.fromisoformat(str(payload.opens_at).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            opens_iso = dt.astimezone(timezone.utc).isoformat()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid opens_at datetime")
    doc = await _presale_get_doc() or {}
    if not doc.get("selected_plots"):
        raise HTTPException(status_code=400, detail="Сначала нажмите «Выбрать поля» — выбранных полей нет")
    now_iso = datetime.now(timezone.utc).isoformat()
    await db.admin_settings.update_one(
        {"type": "presale"},
        {"$set": {
            "map_id": payload.map_id or doc.get("map_id") or "ton_island",
            "opens_at": opens_iso,
            "unavailable_label": label,
            "active": True,
            "approved_at": now_iso,
            "updated_at": now_iso,
        }},
        upsert=True,
    )
    return {"ok": True}


@admin_router.get("/presale/inventory")
async def admin_presale_inventory(map_id: str = "ton_island", admin: User = Depends(get_admin_user)):
    """Per-business inventory on the requested map: how many free cells of
    each pre_business type are available for presale. Frontend uses this to
    populate the business dropdown and show max-available hints.

    A cell counts as free only if it hasn't been purchased by a real user
    (checked via the `plots` collection — island cell docs themselves don't
    persist ownership)."""
    from ton_island import CITY_BUSINESSES as _CB
    island = await db.islands.find_one({"id": map_id}, {"_id": 0, "cells": 1})
    if not island or not island.get("cells"):
        raise HTTPException(status_code=404, detail=f"Map '{map_id}' not found")

    # Coords of every purchased plot on this map (with a real owner).
    purchased_coords: set = set()
    async for p in db.plots.find(
        {"island_id": map_id, "owner": {"$type": "string"}},
        {"_id": 0, "x": 1, "y": 1},
    ):
        purchased_coords.add((p.get("x"), p.get("y")))

    free: Dict[str, int] = {}
    total: Dict[str, int] = {}
    for cell in island["cells"]:
        biz = cell.get("pre_business")
        if not biz:
            continue
        total[biz] = total.get(biz, 0) + 1
        if (cell.get("x"), cell.get("y")) in purchased_coords:
            continue
        free[biz] = free.get(biz, 0) + 1
    items = []
    for biz_type, meta in _CB.items():
        items.append({
            "type": biz_type,
            "name_ru": (meta.get("name") or {}).get("ru", biz_type),
            "name_en": (meta.get("name") or {}).get("en", biz_type),
            "icon": meta.get("icon", "🏢"),
            "tier": meta.get("tier", 1),
            "free": free.get(biz_type, 0),
            "total": total.get(biz_type, 0),
        })
    # Only expose types that actually exist on the map
    items = [i for i in items if i["total"] > 0]
    items.sort(key=lambda i: (i["tier"], i["type"]))
    return {"map_id": map_id, "businesses": items}


@admin_router.post("/presale/reset")
async def admin_presale_reset(admin: User = Depends(get_admin_user)):
    """Wipe the presale config (draft + active state). The GLOBAL custom
    Buy-button text is preserved because it's an independent setting, not part
    of the presale draft."""
    await db.admin_settings.update_one(
        {"type": "presale"},
        {"$unset": {
            "map_id": "", "businesses": "", "selected_plots": "",
            "unavailable_label": "", "opens_at": "", "active": "",
            "approved_at": "", "updated_at": "",
        }},
    )
    return {"ok": True}


class PresaleButtonTextPayload(BaseModel):
    buy_button_text: str = ""


@admin_router.post("/presale/button-text")
async def admin_presale_set_button_text(payload: PresaleButtonTextPayload, admin: User = Depends(get_admin_user)):
    """Set the ONE global custom replacement text for the map's "Купить" button.
    Stored verbatim (no i18n). Empty value => default "Купить" is shown."""
    text = (payload.buy_button_text or "").strip()
    now_iso = datetime.now(timezone.utc).isoformat()
    await db.admin_settings.update_one(
        {"type": "presale"},
        {"$set": {"buy_button_text": text, "updated_at": now_iso}},
        upsert=True,
    )
    return {"ok": True, "buy_button_text": text}


# Lightweight image upload endpoint — admin-only. Stores as data URI in DB
# (or returns a static URL if S3 is configured). Keeps things simple: announcements
# accept either an `image_url` produced by this endpoint or any external URL.
@admin_router.post("/announcement/upload-image")
async def admin_upload_announcement_image(
    file: UploadFile = File(...),
    admin: User = Depends(get_admin_user),
):
    """Upload an image and return a public-ish URL/data-URI usable as announcement image.
    Accepts multipart/form-data with field `file`. ≤ 2 MB. Returns `{url}`.

    F11 hardening: verify magic-bytes to reject files whose content doesn't
    match the declared image/* content-type.
    """
    import base64 as _b64
    if not file:
        raise HTTPException(status_code=400, detail="file is required (multipart)")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty file")
    if len(data) > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image must be ≤ 2 MB")
    ctype = (file.content_type or "image/png").lower()
    if not ctype.startswith("image/"):
        raise HTTPException(status_code=400, detail=f"Only image/* uploads are allowed (got {ctype})")
    # F11: magic-byte check. Accept PNG, JPEG, WEBP, GIF.
    head = data[:12]
    is_image = (
        head.startswith(b"\x89PNG\r\n\x1a\n")
        or head[:3] == b"\xff\xd8\xff"
        or head[:6] in (b"GIF87a", b"GIF89a")
        or (head[:4] == b"RIFF" and head[8:12] == b"WEBP")
    )
    if not is_image:
        raise HTTPException(
            status_code=400,
            detail="Файл не является изображением (проверка сигнатуры)",
        )
    b64 = _b64.b64encode(data).decode("ascii")
    return {"url": f"data:{ctype};base64,{b64}", "size": len(data), "content_type": ctype}



@admin_router.get("/announcements")
async def admin_get_announcements(limit: int = 50, skip: int = 0, admin: User = Depends(get_admin_user)):
    """List announcements (newest first), paginated.

    The admin list only needs title/message/status/dates, so we EXCLUDE the
    heavy per-language ``translations`` blob from the payload — this is what made
    the response slow to load. ``total`` lets the UI show a "показать все" button
    without pulling every document up front (the panel loads just the latest one).
    """
    limit = max(1, min(int(limit or 50), 100))
    skip = max(0, int(skip or 0))
    total = await db.announcements.count_documents({})
    announcements = (
        await db.announcements
        .find({}, {"_id": 0, "translations": 0})
        .sort("created_at", -1)
        .skip(skip)
        .limit(limit)
        .to_list(limit)
    )
    return {"announcements": announcements, "total": total}


@admin_router.get("/telegram-bot-stats")
async def admin_telegram_bot_stats(admin: User = Depends(get_admin_user)):
    """Statistics for Telegram bot users.

    Returns:
      • total, premium_count, non_premium_count — aggregate counters over
        all `telegram_mappings` (i.e. everyone who has interacted with the bot).
      • users — per-bot-user detail: telegram username, is_premium,
        first_activity_at, last_activity_at, bot language, and — if the bot
        chat has been linked to a project account via /link (or the deep-link
        flow) — the corresponding project username/email.
    """
    mappings = await db.telegram_mappings.find({}, {"_id": 0}).sort("last_activity_at", -1).to_list(5000)

    chat_ids = [m.get("chat_id") for m in mappings if m.get("chat_id")]
    linked_users = {}
    if chat_ids:
        async for u in db.users.find(
            {"$or": [
                {"telegram_chat_id": {"$in": chat_ids}},
                {"telegram_id": {"$in": chat_ids}},
            ]},
            {"_id": 0, "id": 1, "username": 1, "email": 1, "display_name": 1,
             "telegram_chat_id": 1, "telegram_id": 1},
        ):
            key = u.get("telegram_chat_id") or u.get("telegram_id")
            if key:
                linked_users[str(key)] = u

    total = len(mappings)
    premium_count = sum(1 for m in mappings if m.get("is_premium"))
    non_premium_count = total - premium_count

    users_out = []
    for m in mappings:
        cid = str(m.get("chat_id") or "")
        linked = linked_users.get(cid)
        users_out.append({
            "chat_id": cid,
            "telegram_user_id": m.get("telegram_user_id") or "",
            "username": m.get("username") or "",
            "first_name": m.get("first_name") or "",
            "is_premium": bool(m.get("is_premium", False)),
            "language": m.get("language") or m.get("tg_language_code") or "",
            # Return raw values only — no silent fallback to updated_at, which
            # would make "first activity" tick forward on every bot ping and
            # always look identical to "last activity". A missing value means
            # the row predates the migration and hasn't had a new hit yet.
            "first_activity_at": m.get("first_activity_at") or "",
            "last_activity_at": m.get("last_activity_at") or m.get("updated_at") or "",
            "linked_account": ({
                "id": linked.get("id"),
                "username": linked.get("username"),
                "email": linked.get("email"),
                "display_name": linked.get("display_name"),
            } if linked else None),
        })

    return {
        "total": total,
        "premium_count": premium_count,
        "non_premium_count": non_premium_count,
        "users": users_out,
    }


@admin_router.get("/telegram-bot-stats/export-csv")
async def admin_telegram_bot_stats_export(admin: User = Depends(get_admin_user)):
    """CSV export of the Telegram-bot user statistics table.

    One column per field — opens correctly in Excel/Numbers/Google Sheets
    regardless of the machine's list separator (we emit UTF-8 BOM + a
    `sep=,` hint on the first line for Russian/German Excel locales).
    """
    from fastapi.responses import StreamingResponse
    import csv
    import io

    data = await admin_telegram_bot_stats(admin=admin)
    users = data.get("users", [])

    output = io.StringIO()
    output.write("\ufeff")          # UTF-8 BOM for Excel
    output.write("sep=,\r\n")       # Excel delimiter hint
    writer = csv.writer(output, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    writer.writerow([
        "Chat ID", "Telegram User ID", "Username", "First Name",
        "Is Premium", "Bot Language", "First Activity", "Last Activity",
        "Linked Project ID", "Linked Username", "Linked Email", "Linked Display Name",
    ])
    for u in users:
        linked = u.get("linked_account") or {}
        writer.writerow([
            u.get("chat_id", "") or "",
            u.get("telegram_user_id", "") or "",
            u.get("username", "") or "",
            u.get("first_name", "") or "",
            "Yes" if u.get("is_premium") else "No",
            u.get("language", "") or "",
            u.get("first_activity_at", "") or "",
            u.get("last_activity_at", "") or "",
            linked.get("id", "") or "",
            linked.get("username", "") or "",
            linked.get("email", "") or "",
            linked.get("display_name", "") or "",
        ])

    output.seek(0)
    filename = f"telegram_bot_users_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "Cache-Control": "no-store",
        },
    )


@admin_router.get("/load-stats")
async def admin_load_stats(admin: User = Depends(get_admin_user)):
    """Aggregate production / consumption per resource across all active businesses.
    
    For each resource type, computes:
      • produced — sum of base hourly production across all businesses (level + buffs ignored,
        baseline view; matches what businesses *would* output at current level)
      • consumed — sum of hourly consumption across all businesses that require this resource
      • load — `consumed / produced * 100` rounded to 1 decimal (0% if produced == 0;
        capped at 100% display when consumption exceeds production)
    
    Used by Admin → Данные → Нагрузка subsection to spot bottleneck resources.
    """
    bizs = await db.businesses.find({}, {"_id": 0, "business_type": 1, "level": 1, "is_active": 1}).to_list(10000)
    produced: Dict[str, float] = {}
    consumed: Dict[str, float] = {}
    
    for b in bizs:
        bt = b.get("business_type") or ""
        lvl = int(b.get("level") or 1)
        cfg = BUSINESSES.get(bt) or BUSINESSES.get(BUSINESS_KEY_MAP.get(bt, bt)) or {}
        produces_resource = cfg.get("produces")
        # production
        if produces_resource:
            try:
                produced[produces_resource] = produced.get(produces_resource, 0.0) + float(get_production(bt, lvl) or 0)
            except Exception:
                pass
        # consumption breakdown — covers multi-resource recipes
        try:
            breakdown = get_consumption_breakdown(bt, lvl) or {}
            for res, amt in breakdown.items():
                consumed[res] = consumed.get(res, 0.0) + float(amt or 0)
        except Exception:
            pass
    
    # Total holdings per resource across ALL users' warehouses (user.resources
    # already aggregates business storage). Floored to whole units to match UI.
    available: Dict[str, float] = {}
    async for u in db.users.find({}, {"_id": 0, "resources": 1}):
        for res, amt in (u.get("resources") or {}).items():
            try:
                available[res] = available.get(res, 0.0) + int(float(amt or 0))
            except (TypeError, ValueError):
                continue

    # Выкуп за текущий день (UTC): сколько единиц каждого ресурса выкупили
    # (все рыночные покупки + админ-выкуп, они записываются как market_purchase).
    bought_today: Dict[str, float] = {}
    _today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    async for tx in db.transactions.find(
        {"tx_type": "market_purchase", "created_at": {"$gte": _today_start}},
        {"_id": 0, "resource_type": 1, "resource_amount": 1},
    ):
        rt = tx.get("resource_type")
        if not rt:
            continue
        try:
            bought_today[rt] = bought_today.get(rt, 0.0) + float(tx.get("resource_amount", 0) or 0)
        except (TypeError, ValueError):
            continue

    # Build response: include all known resources for completeness, sorted by tier+name.
    result = []
    for code, meta in RESOURCE_TYPES.items():
        prod = round(produced.get(code, 0.0), 4)
        cons = round(consumed.get(code, 0.0), 4)
        load_pct = (cons / prod * 100.0) if prod > 0 else (100.0 if cons > 0 else 0.0)
        result.append({
            "code": code,
            "name_ru": meta.get("name_ru", code),
            "name_en": meta.get("name_en", code),
            "icon": meta.get("icon", ""),
            "tier": meta.get("tier", 1),
            "available": int(available.get(code, 0)),
            "produced": prod,
            "consumed": cons,
            "load_pct": round(load_pct, 1),
            "bought_today": int(bought_today.get(code, 0)),
        })
    # sort tier asc, then by produced desc so the most active resources surface first
    result.sort(key=lambda r: (r["tier"], -r["produced"], r["code"]))
    return {"resources": result, "businesses_count": len(bizs)}


@admin_router.post("/trigger-auto-collection")
async def admin_trigger_auto_collection(admin: User = Depends(get_admin_user)):
    """Manually trigger automatic income collection (for testing)"""
    try:
        await trigger_auto_collection_now()
        return {
            "status": "completed",
            "message": "Auto-collection triggered successfully",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        logger.error(f"Failed to trigger auto-collection: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to trigger auto-collection: {str(e)}")

@admin_router.get("/system-events")
async def admin_get_system_events(limit: int = 50, admin: User = Depends(get_admin_user)):
    """Get system events (auto-collections, etc.)"""
    events = await db.system_events.find({}, {"_id": 0}).sort("timestamp", -1).limit(limit).to_list(limit)
    return {"events": events, "total": len(events)}

@admin_router.get("/withdrawals")
async def admin_get_withdrawals(skip: int = 0, limit: int = 100, status: str = None, admin: User = Depends(get_admin_user)):
    """Get withdrawal requests for admin"""
    query = {"tx_type": "withdrawal"}
    if status:
        query["status"] = status
    
    withdrawals = await db.transactions.find(query, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    total = await db.transactions.count_documents(query)
    
    settings = await db.game_settings.find_one({"type": "ton_wallet"}, {"_id": 0})
    treasury_wallet = settings.get("receiver_address_display", "") if settings else ""
    
    if not treasury_wallet:
        stored_raw = settings.get("receiver_address", "") if settings else ""
        treasury_wallet = stored_raw or ""
    
    for w in withdrawals:
        w["from_address"] = treasury_wallet
        w["from_address_display"] = treasury_wallet
        if "to_address_display" not in w or not w["to_address_display"]:
            # Convert user_wallet to user-friendly format (UQ...)
            user_wallet = w.get("user_wallet")
            if user_wallet:
                w["to_address_display"] = to_user_friendly(user_wallet) or user_wallet
            else:
                w["to_address_display"] = w.get("to_address_display") or ""
    
    return {
        "withdrawals": withdrawals, 
        "total": total, 
        "skip": skip, 
        "limit": limit, 
        "treasury_wallet": treasury_wallet
    }

@admin_router.get("/wallet-settings")
async def admin_get_wallet_settings(admin: User = Depends(get_admin_user)):
    """Get current wallet settings for admin panel"""
    settings = await db.game_settings.find_one({"type": "ton_wallet"}, {"_id": 0})
    if not settings:
        return {
            "network": "testnet",
            "receiver_address": "",
            "receiver_address_display": "",
            "configured": False
        }
    raw = settings.get("receiver_address", "") or ""
    display = settings.get("receiver_address_display", raw)
    return {
        "network": settings.get("network", "testnet"),
        "receiver_address": raw,
        "receiver_address_display": display,
        "configured": bool(raw),
    }

@admin_router.post("/wallet-settings")
async def admin_update_wallet_settings(
    network: str,
    receiver_address: Optional[str] = None,
    admin: User = Depends(get_admin_user)
):
    """Update TON wallet settings"""
    if network not in ["testnet", "mainnet"]:
        raise HTTPException(status_code=400, detail="Network must be 'testnet' or 'mainnet'")
    
    # Get current settings to preserve receiver_address if not provided
    current = await db.game_settings.find_one({"type": "ton_wallet"})
    
    raw_addr = ""
    display_addr = ""
    
    if receiver_address:
        if not validate_ton_address(receiver_address):
            raise HTTPException(status_code=400, detail="Invalid TON address")
        
        # Normalize: store canonical raw, compute display
        raw_addr = to_raw(receiver_address)
        display_addr = to_user_friendly(raw_addr) or receiver_address if raw_addr else ""
        
        if not raw_addr:
            raise HTTPException(status_code=400, detail="Failed to parse wallet address")
    elif current:
        # Keep existing address
        raw_addr = current.get("receiver_address", "")
        display_addr = current.get("receiver_address_display", "")
    
    await db.game_settings.update_one(
        {"type": "ton_wallet"},
        {
            "$set": {
                "network": network,
                "receiver_address": raw_addr,
                "receiver_address_display": display_addr,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
        },
        upsert=True
    )
    
    logger.info(f"✅ Wallet settings updated: {network}")
    
    return {
        "status": "success",
        "network": network,
        "receiver_address": display_addr,
        "receiver_address_raw": raw_addr
    }

@admin_router.get("/deposits")
async def admin_get_deposits(
    limit: int = 50,
    status: Optional[str] = None,
    admin: User = Depends(get_admin_user)
):
    """Get deposit history"""
    query = {}
    if status:
        query["status"] = status
    
    deposits = await db.deposits.find(query, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(limit)
    
    # Get stats
    total_deposits = await db.admin_stats.find_one({"type": "treasury"}, {"_id": 0})
    
    return {
        "deposits": deposits,
        "total": len(deposits),
        "stats": total_deposits or {}
    }

@admin_router.post("/deposits/{tx_hash}/credit")
async def admin_manual_credit_deposit(
    tx_hash: str,
    wallet_address: str,
    amount_ton: float,
    admin: User = Depends(get_admin_user)
):
    """Manually credit a deposit (for pending deposits)"""
    # Check if already processed
    existing = await db.deposits.find_one({"tx_hash": tx_hash})
    if existing and existing.get("status") == "completed":
        raise HTTPException(status_code=400, detail="Deposit already credited")
    
    # Find user
    user = await db.users.find_one({"wallet_address": wallet_address})
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    # Credit balance
    await db.users.update_one(
        {"wallet_address": wallet_address},
        {
            "$inc": {
                "balance_ton": amount_ton,
                "total_deposited": amount_ton
            }
        }
    )
    
    # Update or create deposit record
    if existing:
        await db.deposits.update_one(
            {"tx_hash": tx_hash},
            {
                "$set": {
                    "status": "completed",
                    "credited_at": datetime.now(timezone.utc).isoformat(),
                    "credited_by": admin.wallet_address
                }
            }
        )
    else:
        await db.deposits.insert_one({
            "tx_hash": tx_hash,
            "user_id": user["id"],
            "wallet_address": wallet_address,
            "amount_ton": amount_ton,
            "status": "completed",
            "credited_at": datetime.now(timezone.utc).isoformat(),
            "credited_by": admin.wallet_address,
            "created_at": datetime.now(timezone.utc).isoformat()
        })
    
    logger.info(f"✅ Admin credited {amount_ton} TON to {wallet_address[:8]}...")
    
    return {
        "status": "success",
        "credited": amount_ton,
        "user": wallet_address
    }


@admin_router.get("/revenue-stats")
async def admin_get_revenue_stats(admin: User = Depends(get_admin_user)):
    """Get admin revenue statistics"""
    stats = await db.admin_stats.find_one({"type": "treasury"}, {"_id": 0})
    
    if not stats:
        # Return empty stats
        return {
            "plot_sales_income": 0,
            "total_plot_sales": 0,
            "building_sales_income": 0,
            "total_buildings_sold": 0,
            "withdrawal_fees": 0,
            "total_withdrawals": 0,
            "resource_sales_tax": 0,
            "resource_sales_count": 0,
            "total_deposits": 0,
            "deposits_count": 0
        }
    
    return {
        "plot_sales_income": stats.get("plot_sales_income", 0),
        "total_plot_sales": stats.get("total_plot_sales", 0),
        "building_sales_income": stats.get("building_sales_income", 0),
        "total_buildings_sold": stats.get("total_buildings_sold", 0),
        "withdrawal_fees": stats.get("withdrawal_fees", 0),
        "total_withdrawals": stats.get("total_withdrawals", 0),
        "resource_sales_tax": stats.get("resource_sales_tax", 0),
        "resource_sales_count": stats.get("resource_sales_count", 0),
        "total_deposits": stats.get("total_deposits", 0),
        "deposits_count": stats.get("deposits_count", 0)
    }


# ==================== WEBSOCKET ====================

@app.websocket("/api/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    await manager.connect(websocket, user_id)
    # Track online user
    online_users.add(user_id)
    last_activity[user_id] = datetime.now(timezone.utc)
    try:
        while True:
            data = await websocket.receive_json()
            
            if data.get("type") == "ping":
                # Update activity
                last_activity[user_id] = datetime.now(timezone.utc)
                await manager.send_personal({"type": "pong"}, user_id)
            
            elif data.get("type") == "subscribe_plot":
                # Subscribe to plot updates
                pass
            
    except WebSocketDisconnect:
        manager.disconnect(user_id)
        online_users.discard(user_id)

# ==================== ONLINE STATS ====================

@api_router.get("/stats/online")
async def get_online_stats():
    """Get online users count (users active in last 5 minutes)"""
    now = datetime.now(timezone.utc)
    threshold = now - timedelta(minutes=5)
    
    # Clean up old entries and count active
    active_count = 0
    to_remove = []
    for user_id, last_time in last_activity.items():
        last_time = to_aware(last_time)
        if last_time and last_time > threshold:
            active_count += 1
        else:
            to_remove.append(user_id)
    
    for user_id in to_remove:
        online_users.discard(user_id)
        last_activity.pop(user_id, None)
    
    return {"online_count": active_count}

@api_router.post("/stats/heartbeat")
async def heartbeat(payload: dict = Body(default=None), current_user: User = Depends(get_current_user)):
    """Update user's presence. Accepts optional body {"source": "web"|"telegram"}
    so the admin online counter can split web vs Telegram mini-app users."""
    src = "web"
    try:
        if payload and str(payload.get("source", "")).lower() == "telegram":
            src = "telegram"
    except Exception:
        src = "web"
    # Canonical user key (prefer stable uuid id).
    uid = getattr(current_user, "id", None) or getattr(current_user, "wallet_address", None) \
        or getattr(current_user, "email", None) or getattr(current_user, "username", None)
    now = datetime.now(timezone.utc)
    # Legacy in-memory (kept for /stats/online).
    if getattr(current_user, "wallet_address", None):
        online_users.add(current_user.wallet_address)
        last_activity[current_user.wallet_address] = now
    if uid:
        last_activity[uid] = now
        try:
            await db.online_presence.update_one(
                {"user_id": uid},
                {"$set": {"user_id": uid, "source": src, "last_seen": now.isoformat(),
                          "telegram_chat_id": getattr(current_user, "telegram_chat_id", None)}},
                upsert=True,
            )
        except Exception as _e:
            logger.warning(f"heartbeat: presence upsert failed: {_e}")
    return {"status": "ok", "source": src}

# ==================== TREASURY STATS ====================

@admin_router.get("/treasury-health")
async def get_treasury_health(admin: User = Depends(get_admin_user)):
    """Get detailed treasury health for warnings"""
    stats = await db.admin_stats.find_one({"type": "treasury"}, {"_id": 0})
    
    # Get pending withdrawals amount
    pending_withdrawals = await db.transactions.find({
        "tx_type": "withdrawal",
        "status": "pending"
    }, {"_id": 0, "amount_ton": 1}).to_list(100)
    
    pending_amount = sum(w.get("amount_ton", 0) for w in pending_withdrawals)
    
    # Get first transaction date to calculate days active
    first_tx = await db.transactions.find_one({}, {"_id": 0, "created_at": 1}, sort=[("created_at", 1)])
    days_active = 1
    if first_tx and first_tx.get("created_at"):
        try:
            first_date = datetime.fromisoformat(first_tx["created_at"].replace('Z', '+00:00'))
            days_active = max(1, (datetime.now(timezone.utc) - first_date).days)
        except Exception:
            pass
    
    return {
        "plot_sales_income": stats.get("plot_sales_income", 0) if stats else 0,
        "building_sales_income": stats.get("building_sales_income", 0) if stats else 0,
        "total_tax": stats.get("total_tax", 0) if stats else 0,
        "withdrawal_fees": stats.get("withdrawal_fees", 0) if stats else 0,
        "total_withdrawals": stats.get("total_withdrawals", 0) if stats else 0,
        "total_deposits": stats.get("total_deposits", 0) if stats else 0,
        "pending_withdrawals_amount": pending_amount,
        "pending_withdrawals_count": len(pending_withdrawals),
        "days_active": days_active
    }

# ==================== MAINTENANCE MODE ====================

class MaintenanceRequest(BaseModel):
    enabled: bool
    scheduled_at: Optional[str] = None  # ISO datetime string for scheduled maintenance

@admin_router.get("/maintenance")
async def get_maintenance_status():
    """Get current maintenance status - public endpoint"""
    maintenance = await db.admin_stats.find_one({"type": "maintenance"}, {"_id": 0})
    if not maintenance:
        return {"enabled": False, "scheduled_at": None, "started_at": None}
    return {
        "enabled": maintenance.get("enabled", False),
        "scheduled_at": maintenance.get("scheduled_at"),
        "started_at": maintenance.get("started_at"),
        "message": maintenance.get("message", "Технические работы")
    }

@admin_router.post("/maintenance")
async def set_maintenance_mode(request: MaintenanceRequest, admin: User = Depends(get_admin_user)):
    """Enable/disable maintenance mode"""
    now = datetime.now(timezone.utc).isoformat()
    
    update_data = {
        "type": "maintenance",
        "enabled": request.enabled,
        "updated_at": now,
        "updated_by": admin.wallet_address or admin.email
    }
    
    if request.enabled:
        if request.scheduled_at:
            update_data["scheduled_at"] = request.scheduled_at
            update_data["started_at"] = None
            logger.info(f"Maintenance scheduled for {request.scheduled_at} by {admin.username}")
        else:
            update_data["scheduled_at"] = None
            update_data["started_at"] = now
            logger.info(f"Maintenance started NOW by {admin.username}")
    else:
        update_data["scheduled_at"] = None
        update_data["started_at"] = None
        update_data["ended_at"] = now
        logger.info(f"Maintenance ended by {admin.username}")
    
    await db.admin_stats.update_one(
        {"type": "maintenance"},
        {"$set": update_data},
        upsert=True
    )
    
    return {"status": "ok", "maintenance": update_data}


# ==================== ADMIN DATA PANEL ====================

@admin_router.get("/players/search")
async def admin_search_players(query: str = "", admin: User = Depends(get_admin_user)):
    """Search players by ID, wallet, username, email"""
    filter_q = {}
    if query:
        filter_q = {"$or": [
            {"id": {"$regex": query, "$options": "i"}},
            {"wallet_address": {"$regex": query, "$options": "i"}},
            {"username": {"$regex": query, "$options": "i"}},
            {"display_name": {"$regex": query, "$options": "i"}},
            {"email": {"$regex": query, "$options": "i"}},
        ]}
    
    # Return ALL matching players (no 50-cap), newest registrations first.
    users_list = await db.users.find(filter_q, USER_SECRET_PROJECTION).sort("created_at", -1).to_list(length=None)
    return {"players": users_list, "total": len(users_list)}


@admin_router.get("/players/{player_id}")
async def admin_get_player_details(player_id: str, admin: User = Depends(get_admin_user)):
    """Get FULL player data including businesses, plots, wallet, devices"""
    user = await db.users.find_one(
        {"$or": [
            {"id": player_id},
            {"wallet_address": player_id},
            {"username": player_id},
            {"email": player_id},
        ]},
        {"_id": 0}
    )
    if not user:
        raise HTTPException(status_code=404, detail="Player not found")
    
    # Never leak credential material off the server, even to admins.
    for _secret in ("hashed_password", "password", "password_hash",
                    "totp_secret", "two_factor_secret"):
        user.pop(_secret, None)

    uid = user.get("id") or user.get("wallet_address")
    
    # Get player's businesses
    businesses = await db.businesses.find(
        {"owner": uid}, {"_id": 0}
    ).to_list(50)

    # Enrich each business with its production/consumption breakdown (per day),
    # so the admin panel can show WHAT and HOW MUCH each business produces and
    # consumes when a business row is expanded.
    def _res_entry(rid, amount):
        return {
            "resource": rid,
            "name": translate_resource_name(rid) if rid else rid,
            "per_day": round(float(amount or 0), 3),
        }

    for _b in businesses:
        try:
            _btype = _b.get("business_type", "") or ""
            _lvl = int(_b.get("level", 1) or 1)
            _cfg = resolve_business_config(_btype) or {}
            _prod_res = _cfg.get("produces")
            _prod_amt = get_production(_btype, _lvl)
            _b["produces_detail"] = [_res_entry(_prod_res, _prod_amt)] if _prod_res else []
            _cons_bd = get_consumption_breakdown(_btype, _lvl) or {}
            _b["consumes_detail"] = [_res_entry(r, a) for r, a in _cons_bd.items()]
        except Exception as _e:
            logger.warning(f"admin player details: production enrich failed for biz {_b.get('id')}: {_e}")
            _b.setdefault("produces_detail", [])
            _b.setdefault("consumes_detail", [])
    
    # Get player's plots
    plots = await db.plots.find(
        {"owner": uid}, {"_id": 0}
    ).to_list(50)
    
    # Get player's device info
    device_fp = user.get("device_fingerprint", "")
    same_device_accounts = []
    is_multi = False
    
    if device_fp:
        same_device = await db.users.find(
            {"device_fingerprint": device_fp, "id": {"$ne": uid}},
            {"_id": 0, "id": 1, "username": 1, "display_name": 1, "wallet_address": 1, "created_at": 1}
        ).to_list(20)
        same_device_accounts = same_device
        is_multi = len(same_device) > 0
    
    # Transactions
    recent_txs = await db.transactions.find(
        {"$or": [{"user_wallet": uid}, {"user_id": uid}]},
        {"_id": 0}
    ).sort("created_at", -1).limit(20).to_list(20)

    # Referral count (users referred by this player) — across all referral fields
    referral_count = await db.users.count_documents(_referrer_match(uid))

    # Who referred THIS player (if anyone). Read any of the referral fields.
    referrer_info = None
    _my_referrer_id = (user.get("referrerId") or user.get("partner_ref_id")
                       or user.get("ref_by"))
    if _my_referrer_id:
        _ref_doc = await db.users.find_one(
            {"id": str(_my_referrer_id)},
            {"_id": 0, "id": 1, "username": 1, "display_name": 1, "email": 1, "wallet_address": 1},
        )
        if _ref_doc:
            referrer_info = {
                "id": _ref_doc.get("id"),
                "username": _ref_doc.get("username"),
                "display_name": _ref_doc.get("display_name") or _ref_doc.get("username"),
                "email": _ref_doc.get("email"),
                "wallet_address": _ref_doc.get("wallet_address"),
            }
        else:
            # Referrer id stored but user no longer exists — still surface the id.
            referrer_info = {"id": str(_my_referrer_id), "username": None, "display_name": None}

    # Telegram binding info + telegram language (from telegram_mappings)
    tg_chat_id = user.get("telegram_chat_id") or user.get("telegram_id")
    telegram_linked = bool(tg_chat_id)
    telegram_language = None
    if tg_chat_id:
        mapping = await db.telegram_mappings.find_one(
            {"chat_id": str(tg_chat_id)},
            {"_id": 0, "language": 1, "tg_language_code": 1},
        )
        if mapping:
            telegram_language = mapping.get("language") or mapping.get("tg_language_code")

    return {
        "user": user,
        "businesses": businesses,
        "businesses_count": len(businesses),
        "plots": plots,
        "plots_count": len(plots),
        "recent_transactions": recent_txs,
        "device_fingerprint": device_fp,
        "same_device_accounts": same_device_accounts,
        "is_multi_account": is_multi,
        "multi_account_warning": "МУЛЬТИАККАУНТ!!!" if is_multi else None,
        # --- Added for admin panel: referrals + language + telegram ---
        "referral_count": referral_count,
        "referrer": referrer_info,
        "language": user.get("language") or "—",
        "telegram_linked": telegram_linked,
        "telegram_chat_id": str(tg_chat_id) if tg_chat_id else None,
        "telegram_language": telegram_language,
    }


def _infer_registration_method(user: dict) -> str:
    """Determine how a user registered.
    Uses the stored `registration_method` when present, otherwise infers it
    from the account shape (Google id / wallet without password / email)."""
    method = user.get("registration_method")
    if method in ("email", "google", "ton", "telegram"):
        return method
    if user.get("google_id"):
        return "google"
    if user.get("telegram_id") or user.get("telegram_user_id") or user.get("telegram_chat_id"):
        return "telegram"
    if user.get("wallet_address") and not user.get("hashed_password"):
        return "ton"
    return "email"


@admin_router.get("/registrations")
async def admin_registrations(admin: User = Depends(get_admin_user)):
    """Registration report: overall stats by method + per-user rows.

    Also returns `language_stats`: for every project language, how many users
    have it set. Counts BOTH the in-app language (users.language) AND the
    language chosen inside the Telegram bot (telegram_mappings.language, with a
    fallback to the client's tg_language_code)."""
    users_list = await db.users.find(
        {},
        {
            "_id": 0, "id": 1, "username": 1, "display_name": 1, "email": 1,
            "wallet_address": 1, "google_id": 1, "hashed_password": 1,
            "registration_method": 1, "created_at": 1, "language": 1,
            "telegram_id": 1, "telegram_user_id": 1, "telegram_chat_id": 1,
            "last_ip": 1, "last_device": 1, "last_browser": 1,
        },
    ).sort("created_at", -1).to_list(2000)

    stats = {"email": 0, "google": 0, "ton": 0, "telegram": 0, "total": 0}
    rows = []
    # language_stats[code] = {"app": <in-app users>, "bot": <telegram-bot users>}
    language_stats: dict = {}

    def _norm_lang(code):
        if not code:
            return None
        base = str(code).strip().lower().split("-")[0]
        return base or None

    def _bump(code, bucket):
        code = _norm_lang(code) or "unknown"
        language_stats.setdefault(code, {"app": 0, "bot": 0})
        language_stats[code][bucket] += 1

    for u in users_list:
        method = _infer_registration_method(u)
        stats[method] = stats.get(method, 0) + 1
        stats["total"] += 1
        _bump(u.get("language"), "app")
        rows.append({
            "id": u.get("id"),
            "username": u.get("username"),
            "display_name": u.get("display_name") or u.get("username"),
            "email": u.get("email"),
            "wallet_address": u.get("wallet_address"),
            "method": method,
            "created_at": u.get("created_at"),
            "ip": u.get("last_ip") or "Не определено",
            "device": u.get("last_device") or "Не определено",
            "browser": u.get("last_browser") or "Не определено",
        })

    # Telegram bot users — language chosen in the bot, or the client locale.
    try:
        async for m in db.telegram_mappings.find(
            {}, {"_id": 0, "language": 1, "tg_language_code": 1}
        ):
            _bump(m.get("language") or m.get("tg_language_code"), "bot")
    except Exception as e:
        logger.warning(f"language_stats: telegram_mappings scan failed: {e}")

    return {"stats": stats, "registrations": rows, "language_stats": language_stats}


def _referrer_match(user_id: str) -> dict:
    """Match every user attributed to `user_id` via ANY referral field. Telegram
    signups historically stored only `ref_by`/`partner_ref_id` while email/Google
    signups store `referrerId`; counting all of them keeps referral totals right."""
    rid = str(user_id)
    return {"$or": [{f: rid} for f in ("referrerId", "partner_ref_id", "ref_by")]}


async def _build_referral_list(user_id: str):
    """Return (count, total_earned_ton, [{username, earned_ton}]) for a referrer id."""
    referred = await db.users.find(
        _referrer_match(user_id),
        {"_id": 0, "username": 1, "display_name": 1, "contributedToReferrer": 1},
    ).sort("contributedToReferrer", -1).to_list(1000)
    rows = [
        {
            "username": r.get("display_name") or r.get("username") or "—",
            "earned_ton": float(r.get("contributedToReferrer", 0) or 0),
            "earned_city": round(float(r.get("contributedToReferrer", 0) or 0) * 1000, 2),
        }
        for r in referred
    ]
    total_earned = round(sum(r["earned_ton"] for r in rows), 6)
    return len(rows), total_earned, rows


@api_router.get("/referrals/me")
async def get_my_referrals(current_user: User = Depends(get_current_user)):
    """Player-facing referral summary: my referral id/link data + list of invitees."""
    # Build an $or of ONLY non-empty identifiers — a null wallet_address/email
    # would otherwise match unrelated docs (e.g. the first email-only user).
    _id_or = []
    if getattr(current_user, "id", None):
        _id_or.append({"id": current_user.id})
    if getattr(current_user, "email", None):
        _id_or.append({"email": current_user.email})
    if getattr(current_user, "wallet_address", None):
        _id_or.append({"wallet_address": current_user.wallet_address})
    if not _id_or:
        raise HTTPException(status_code=404, detail="User not found")
    me = await db.users.find_one(
        {"$or": _id_or},
        {"_id": 0, "id": 1, "totalEarnedFromReferrals": 1},
    )
    if not me:
        raise HTTPException(status_code=404, detail="User not found")

    my_id = me.get("id")
    count, total_earned_ton, rows = await _build_referral_list(my_id)

    return {
        "referral_id": my_id,
        "referral_path": f"/?ref={my_id}",
        "count": count,
        "total_earned_ton": total_earned_ton,
        "total_earned_city": round(total_earned_ton * 1000, 2),
        "referrals": rows,
    }


@admin_router.get("/players/{player_id}/referrals")
async def admin_get_player_referrals(player_id: str, admin: User = Depends(get_admin_user)):
    """Admin view of a player's referral data: count, referral link id + invitees."""
    user = await db.users.find_one(
        {"$or": [
            {"id": player_id},
            {"wallet_address": player_id},
            {"username": player_id},
            {"email": player_id},
        ]},
        {"_id": 0, "id": 1, "username": 1, "totalEarnedFromReferrals": 1},
    )
    if not user:
        raise HTTPException(status_code=404, detail="Player not found")

    uid = user.get("id")
    count, total_earned_ton, rows = await _build_referral_list(uid)

    return {
        "referral_id": uid,
        "referral_path": f"/?ref={uid}",
        "count": count,
        "total_earned_ton": total_earned_ton,
        "total_earned_city": round(total_earned_ton * 1000, 2),
        "referrals": rows,
    }


class SetReferrerRequest(BaseModel):
    referrer_id: str


@admin_router.post("/players/{player_id}/referrer")
async def admin_set_player_referrer(
    player_id: str, data: SetReferrerRequest, admin: User = Depends(get_admin_user)
):
    """Assign or change the referrer of a player.

    Sets `referrerId`, `partner_ref_id` and `ref_by` on the target user so the
    referral is attributed to the new referrer EVERYWHERE (player referral list,
    admin referrals data section, partner metrics). Changing automatically moves
    the referral off the previous referrer, since all counts are computed by
    querying these fields."""
    user = await db.users.find_one(
        {"$or": [
            {"id": player_id},
            {"wallet_address": player_id},
            {"username": player_id},
            {"email": player_id},
        ]},
        {"_id": 0, "id": 1, "username": 1},
    )
    if not user:
        raise HTTPException(status_code=404, detail="Игрок не найден")
    target_id = user.get("id")

    new_ref_id = (data.referrer_id or "").strip()
    if not new_ref_id:
        raise HTTPException(status_code=400, detail="Не указан реферер")
    if new_ref_id == target_id:
        raise HTTPException(status_code=400, detail="Пользователь не может быть реферером самому себе")

    referrer = await db.users.find_one(
        {"id": new_ref_id}, {"_id": 0, "id": 1, "username": 1, "display_name": 1}
    )
    if not referrer:
        raise HTTPException(status_code=404, detail="Реферер не найден")

    set_fields = {
        "referrerId": new_ref_id,
        "partner_ref_id": new_ref_id,
        "ref_by": new_ref_id,
    }
    # Anchor partner join moment if this is the first attribution.
    if not user.get("partner_joined_at"):
        set_fields["partner_joined_at"] = datetime.now(timezone.utc).isoformat()
    await db.users.update_one({"id": target_id}, {"$set": set_fields})

    # Keep the referral rally / admin leaderboard cache fresh.
    try:
        from promo_service import invalidate_leaderboard_cache
        invalidate_leaderboard_cache()
    except Exception:
        pass

    logger.info(
        "Admin %s set referrer of %s -> %s",
        admin.username or admin.email, target_id, new_ref_id,
    )
    return {
        "status": "ok",
        "player_id": target_id,
        "referrer": {
            "id": referrer.get("id"),
            "username": referrer.get("username"),
            "display_name": referrer.get("display_name") or referrer.get("username"),
        },
    }




@admin_router.post("/players/{player_id}/update")
async def admin_update_player(player_id: str, updates: dict, admin: User = Depends(get_admin_user)):
    """Update player data (admin override)"""
    allowed_fields = ["balance_ton", "bonus_balance", "display_name", "level", "experience", "is_banned", "resources"]
    
    update_data = {}
    for key, value in updates.items():
        if key in allowed_fields:
            update_data[key] = value
    
    if not update_data:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    
    update_data["admin_modified_at"] = datetime.now(timezone.utc).isoformat()
    update_data["admin_modified_by"] = admin.username or admin.email
    
    result = await db.users.update_one(
        {"$or": [{"id": player_id}, {"wallet_address": player_id}]},
        {"$set": update_data}
    )
    
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Player not found")
    
    # Log admin action
    await db.admin_logs.insert_one({
        "action": "player_update",
        "player_id": player_id,
        "changes": update_data,
        "admin": admin.username or admin.email,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    
    return {"status": "updated", "changes": update_data}


# ==================== ADMIN: PLAYER BUSINESS / RESOURCE / WITHDRAW MANAGEMENT ====================

async def _admin_find_player(player_id: str):
    """Helper: look up a player by id, wallet, username or email."""
    return await db.users.find_one(
        {"$or": [
            {"id": player_id},
            {"wallet_address": player_id},
            {"username": player_id},
            {"email": player_id},
        ]},
        {"_id": 0},
    )


@admin_router.delete("/players/{player_id}/business/{business_id}")
async def admin_delete_player_business(
    player_id: str,
    business_id: str,
    admin: User = Depends(get_admin_user),
):
    """Delete a player's business with FULL cascade cleanup.

    Side-effects:
      • Removes the business doc.
      • FREES the plot entirely — owner is cleared, plot becomes available again
        on the map. No refund (admin action is moderation, not a sale).
      • Pulls the plot id from `user.plots_owned`.
      • Cancels every contract / tender_contract where this business is a party.
      • Cancels active market listings attributed to this business (and refunds
        the listed resource units back to the seller's `resources` bucket — these
        are the seller's own goods that were just sitting in escrow).
      • Removes pending build_orders for the plot.
      • Unlinks `patron_id` (and `contract_buff`) from any vassal business that
        pointed at the deleted one.
      • Pulls the business id from the user's `businesses_owned`.

    Money is NOT refunded.
    """
    user = await _admin_find_player(player_id)
    if not user:
        raise HTTPException(status_code=404, detail="Player not found")
    uid = user.get("id") or user.get("wallet_address")

    # Match the business against ALL of the user's identifiers.
    owner_keys = await resolve_owner_keys(db, uid)
    biz = await db.businesses.find_one(
        {"id": business_id, **owner_businesses_query(owner_keys)},
        {"_id": 0},
    )
    if not biz:
        raise HTTPException(status_code=404, detail="Business not found for this player")

    plot_id = biz.get("plot_id")

    # 1) Remove the business itself
    await db.businesses.delete_one({"id": business_id})

    # 2) Free the plot completely (owner cleared, available again, no business).
    #    Reset EVERY occupancy field, including the denormalised ones some map
    #    renderers read directly off the plot (is_occupied / owner_id /
    #    business_type / building) — otherwise the plot stays visually occupied
    #    and locked on the map even though the business doc is gone.
    plot_update = {"$set": {
        "business_id": None,
        "business": None,
        "building": None,
        "business_type": None,
        "owner": None,
        "owner_id": None,
        "owner_username": None,
        "owner_avatar": None,
        "is_occupied": False,
        "is_available": True,
        "is_rented": False,
        "renter": None,
        "rent_price": None,
        "is_empty": True,
    }}
    plots_touched = 0
    plot_ids_to_pull: list = []
    if plot_id:
        r = await db.plots.update_one({"id": plot_id}, plot_update)
        plots_touched = r.modified_count
        plot_ids_to_pull.append(plot_id)
    # Defence-in-depth: any plot that still points at this business by id
    async for p in db.plots.find({"business_id": business_id}, {"_id": 0, "id": 1}):
        if p.get("id") and p["id"] not in plot_ids_to_pull:
            plot_ids_to_pull.append(p["id"])
    if plot_ids_to_pull:
        r2 = await db.plots.update_many({"id": {"$in": plot_ids_to_pull}}, plot_update)
        plots_touched = max(plots_touched, r2.modified_count)

    # 3) Cancel legacy patronage contracts where this biz is patron OR vassal
    legacy_contracts = await db.contracts.update_many(
        {
            "status": {"$in": ["active", "proposed", "pending"]},
            "$or": [
                {"patron_business_id": business_id},
                {"vassal_business_id": business_id},
            ],
        },
        {"$set": {"status": "broken_by_admin", "broken_at": datetime.now(timezone.utc).isoformat()}},
    )

    # 4) Cancel tender_contracts where this biz is buyer/seller
    tender_contracts = await db.tender_contracts.update_many(
        {
            "status": {"$in": ["ACTIVE", "PENDING_FUNDS", "PENDING_RESOURCES", "PROPOSED"]},
            "$or": [
                {"seller_business_id": business_id},
                {"buyer_business_id": business_id},
            ],
        },
        {"$set": {"status": "BROKEN_BY_ADMIN", "broken_at": datetime.now(timezone.utc).isoformat(), "broken_by": "admin"}},
    )

    # 5) Cancel market listings attributed to this business, refund resources
    listings = await db.market_listings.find(
        {"attributed_business_id": business_id, "status": "active"},
        {"_id": 0, "id": 1, "resource_type": 1, "amount": 1, "seller_id": 1},
    ).to_list(100)
    listings_cancelled = 0
    for lst in listings:
        await db.market_listings.update_one(
            {"id": lst["id"]},
            {"$set": {"status": "cancelled", "cancelled_at": datetime.now(timezone.utc).isoformat(), "cancelled_reason": "admin_business_delete"}},
        )
        if lst.get("seller_id") and lst.get("resource_type") and lst.get("amount"):
            seller_keys = await resolve_owner_keys(db, lst["seller_id"])
            seller_user = await db.users.find_one(
                {"$or": [{"id": k} for k in seller_keys] + [{"email": k} for k in seller_keys] + [{"wallet_address": k} for k in seller_keys]},
                {"_id": 1},
            )
            if seller_user:
                await db.users.update_one(
                    {"_id": seller_user["_id"]},
                    {"$inc": {f"resources.{lst['resource_type']}": int(lst["amount"])}},
                )
        listings_cancelled += 1

    # 5b) Also cancel any LAND/BUSINESS-sale listings (db.land_listings) where
    # this business is the subject. Without this the listing stays "active"
    # and the on_sale business keeps phantom-counting toward the user's cap.
    land_listings_cancelled = await db.land_listings.update_many(
        {
            "status": "active",
            "$or": [
                {"business_id": business_id},
                {"business.id": business_id},
            ],
        },
        {"$set": {"status": "cancelled", "cancelled_at": datetime.now(timezone.utc).isoformat(), "cancelled_reason": "admin_business_delete"}},
    )

    # 5c) And just in case the original /sell flow stored the business id on
    # the listing root, drop those too.
    await db.land_listings.delete_many({"business_id_orphan_marker": business_id})

    # 6) Remove pending build orders for this plot
    build_orders_removed = 0
    if plot_id:
        r = await db.build_orders.delete_many({"plot_id": plot_id, "status": "pending"})
        build_orders_removed = r.deleted_count

    # 7) Unlink patron_id from vassal businesses that pointed at this one
    vassals_unlinked = await db.businesses.update_many(
        {"patron_id": business_id},
        {"$unset": {"patron_id": "", "contract_buff": "", "contract_id": ""}},
    )

    # 8) Pull from user.businesses_owned AND user.plots_owned
    user_updates: dict = {"businesses_owned": business_id}
    if plot_ids_to_pull:
        user_updates["plots_owned"] = {"$in": plot_ids_to_pull}
    await db.users.update_one(
        {"id": user["id"]},
        {"$pull": user_updates},
    )

    # 9) Live map refresh — broadcast that each freed plot is now empty so open
    #    clients update the Konva grid immediately without a server restart.
    try:
        async for fp in db.plots.find(
            {"id": {"$in": plot_ids_to_pull}} if plot_ids_to_pull else {"id": None},
            {"_id": 0, "id": 1, "x": 1, "y": 1},
        ):
            await manager.broadcast({
                "type": "cell_update",
                "cell": {
                    "id": fp.get("id"),
                    "x": fp.get("x"),
                    "y": fp.get("y"),
                    "business_id": None,
                    "business_type": None,
                    "building": None,
                    "owner": None,
                    "owner_id": None,
                    "is_occupied": False,
                    "is_available": True,
                    "is_empty": True,
                },
            })
            await manager.broadcast({
                "type": "plot_freed",
                "plot_id": fp.get("id"),
                "x": fp.get("x"),
                "y": fp.get("y"),
                "business_id": business_id,
            })
    except Exception as e:
        logger.warning(f"admin business delete: map broadcast failed: {e}")

    await db.admin_logs.insert_one({
        "action": "player_business_delete",
        "player_id": uid,
        "business_id": business_id,
        "business_type": biz.get("business_type"),
        "plot_id": plot_id,
        "plot_freed": bool(plot_ids_to_pull),
        "cascade": {
            "plots_touched": plots_touched,
            "legacy_contracts_broken": legacy_contracts.modified_count,
            "tender_contracts_broken": tender_contracts.modified_count,
            "listings_cancelled": listings_cancelled,
            "build_orders_removed": build_orders_removed,
            "vassals_unlinked": vassals_unlinked.modified_count,
        },
        "admin": admin.username or admin.email,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    return {
        "status": "deleted",
        "business_id": business_id,
        "plot_freed": bool(plot_ids_to_pull),
        "cascade": {
            "plots_touched": plots_touched,
            "legacy_contracts_broken": legacy_contracts.modified_count,
            "tender_contracts_broken": tender_contracts.modified_count,
            "listings_cancelled": listings_cancelled,
            "build_orders_removed": build_orders_removed,
            "vassals_unlinked": vassals_unlinked.modified_count,
        },
    }


class AdminBusinessUpdate(BaseModel):
    level: Optional[int] = None
    durability: Optional[float] = None
    is_active: Optional[bool] = None


@admin_router.post("/players/{player_id}/business/{business_id}/update")
async def admin_update_player_business(
    player_id: str,
    business_id: str,
    data: AdminBusinessUpdate,
    admin: User = Depends(get_admin_user),
):
    """Update level / durability / activity of a player's business."""
    user = await _admin_find_player(player_id)
    if not user:
        raise HTTPException(status_code=404, detail="Player not found")
    uid = user.get("id") or user.get("wallet_address")

    biz = await db.businesses.find_one(
        {"id": business_id, "$or": nz_or([{"owner": uid}, {"owner": user.get("wallet_address")}])},
        {"_id": 0},
    )
    if not biz:
        raise HTTPException(status_code=404, detail="Business not found for this player")

    update_data = {}
    if data.level is not None:
        update_data["level"] = max(1, int(data.level))
    if data.durability is not None:
        update_data["durability"] = max(0.0, min(100.0, float(data.durability)))
    if data.is_active is not None:
        update_data["is_active"] = bool(data.is_active)

    if not update_data:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    update_data["admin_modified_at"] = datetime.now(timezone.utc).isoformat()
    update_data["admin_modified_by"] = admin.username or admin.email

    await db.businesses.update_one({"id": business_id}, {"$set": update_data})
    await db.admin_logs.insert_one({
        "action": "player_business_update",
        "player_id": uid,
        "business_id": business_id,
        "changes": update_data,
        "admin": admin.username or admin.email,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    return {"status": "updated", "changes": update_data}


class AdminResourcesUpdate(BaseModel):
    resources: dict


@admin_router.post("/players/{player_id}/resources")
async def admin_update_player_resources(
    player_id: str,
    data: AdminResourcesUpdate,
    admin: User = Depends(get_admin_user),
):
    """Replace player's resources dict."""
    user = await _admin_find_player(player_id)
    if not user:
        raise HTTPException(status_code=404, detail="Player not found")
    clean = {}
    for k, v in (data.resources or {}).items():
        try:
            clean[str(k)] = max(0, float(v))
        except (TypeError, ValueError):
            continue
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {
            "resources": clean,
            "resources_updated_at": datetime.now(timezone.utc).isoformat(),
        }},
    )
    await db.admin_logs.insert_one({
        "action": "player_resources_update",
        "player_id": user["id"],
        "resources": clean,
        "admin": admin.username or admin.email,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    return {"status": "updated", "resources": clean}


class AdminBlockWithdraw(BaseModel):
    hours: int = 24
    reason: Optional[str] = ""


@admin_router.post("/players/{player_id}/block-withdrawal")
async def admin_block_player_withdrawal(
    player_id: str,
    data: AdminBlockWithdraw,
    admin: User = Depends(get_admin_user),
):
    """Block user's withdrawals for N hours. Frontend will show 'обратитесь в поддержку'."""
    user = await _admin_find_player(player_id)
    if not user:
        raise HTTPException(status_code=404, detail="Player not found")
    hours = max(1, int(data.hours or 24))
    until = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {
            "withdrawal_blocked_until": until,
            "withdraw_lock_until": until,
            "withdrawal_block_reason": data.reason or "Admin block",
        }},
    )
    await db.admin_logs.insert_one({
        "action": "player_block_withdrawal",
        "player_id": user["id"],
        "until": until,
        "reason": data.reason,
        "admin": admin.username or admin.email,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    return {"status": "blocked", "until": until}


@admin_router.post("/players/{player_id}/unblock-withdrawal")
async def admin_unblock_player_withdrawal(
    player_id: str,
    admin: User = Depends(get_admin_user),
):
    """Unblock user's withdrawals."""
    user = await _admin_find_player(player_id)
    if not user:
        raise HTTPException(status_code=404, detail="Player not found")
    await db.users.update_one(
        {"id": user["id"]},
        {"$unset": {
            "withdrawal_blocked_until": "",
            "withdraw_lock_until": "",
            "withdrawal_block_reason": "",
        }},
    )
    await db.admin_logs.insert_one({
        "action": "player_unblock_withdrawal",
        "player_id": user["id"],
        "admin": admin.username or admin.email,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    return {"status": "unblocked"}


@admin_router.get("/market/prices")
async def admin_get_market_prices(admin: User = Depends(get_admin_user)):
    """Get all resource prices for admin management — always returns full RESOURCE_TYPES list."""
    prices_doc = await db.market_prices.find_one({"type": "current"})
    stored_prices = prices_doc.get("prices", {}) if prices_doc else {}

    enriched = {}
    # Iterate over ALL RESOURCE_TYPES (21+) so admin sees the full list, not only what's stored.
    for resource, meta in RESOURCE_TYPES.items():
        # Skip system-level "ton" pseudo-resource if present
        if resource == "ton":
            continue
        price = stored_prices.get(resource, meta.get("base_price", 0.01))
        enriched[resource] = {
            "current_price": price,
            "base_price": meta.get("base_price", 0.01),
            "name_ru": meta.get("name_ru", resource),
            "icon": meta.get("icon", "📦"),
            "tier": meta.get("tier", 0),
            "min_price": MIN_PRICE_TON,
        }

    return {"prices": enriched}


@admin_router.post("/market/prices/update")
async def admin_update_prices(price_updates: dict, admin: User = Depends(get_admin_user)):
    """Admin manually set resource prices"""
    prices_doc = await db.market_prices.find_one({"type": "current"})
    prices = prices_doc.get("prices", {}) if prices_doc else {}
    
    for resource, new_price in price_updates.items():
        if resource in RESOURCE_TYPES:
            prices[resource] = max(MIN_PRICE_TON, float(new_price))
    
    await db.market_prices.update_one(
        {"type": "current"},
        {"$set": {"prices": prices, "updated_at": datetime.now(timezone.utc).isoformat(), "admin_override": True}},
        upsert=True
    )
    
    await db.admin_logs.insert_one({
        "action": "price_update",
        "changes": price_updates,
        "admin": admin.username or admin.email,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    
    return {"status": "prices_updated", "prices": prices}


@admin_router.post("/market/stabilize")
async def admin_stabilize_market(resource: str, target_price: float, admin: User = Depends(get_admin_user)):
    """Deploy NPC stabilizer bot for a resource"""
    if resource not in RESOURCE_TYPES:
        raise HTTPException(status_code=400, detail="Invalid resource")
    
    target_price = max(MIN_PRICE_TON, target_price)
    
    # Create stabilizer bot order
    bot_order = {
        "id": str(uuid.uuid4()),
        "type": "sell",
        "resource": resource,
        "amount": 1000,
        "price_per_unit": target_price * 1.02,  # Slightly above target
        "seller": "NPC_STABILIZER",
        "seller_name": "GRAM-City Market",
        "is_npc": True,
        "status": "open",
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=40)).isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    
    await db.market_orders.insert_one(bot_order)
    
    return {
        "status": "stabilizer_deployed",
        "resource": resource,
        "target_price": target_price,
        "sell_price": target_price * 1.02,
        "expires_in_minutes": 40,
    }


@admin_router.post("/market/bot-listing")
async def admin_bot_listing(data: dict, admin: User = Depends(get_admin_user)):
    """Admin bot: list resource for sale at specified price and amount"""
    resource = data.get("resource_type")
    amount = int(data.get("amount", 100))
    price = float(data.get("price_per_unit", 0))
    # Input is in $CITY from admin panel; convert to TON for storage (same as user listings)
    price_ton = price / 1000 if price > 0 else 0
    
    if resource not in RESOURCE_TYPES:
        raise HTTPException(status_code=400, detail="Invalid resource type")
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be > 0")
    
    # Default price from RESOURCE_TYPES if not specified (in $CITY → convert to TON)
    if price_ton <= 0:
        price_ton = RESOURCE_TYPES[resource]["base_price"] / 1000
    
    # Pick a random plausible nickname so the lot looks like a regular player's
    # (admin requirement: ordinary users should NOT see "GRAM-City Bot").
    from core.admin_market_names import pick_admin_market_nick
    public_nick = pick_admin_market_nick()
    listing_id = str(uuid.uuid4())
    listing = {
        "id": listing_id,
        "resource_type": resource,
        "amount": amount,
        "price_per_unit": price_ton,  # stored in TON (like regular user listings)
        "seller_id": "BOT_ADMIN",
        "seller_username": public_nick,
        "seller_email": "bot@toncity.com",
        "is_bot": True,            # internal flag (admin filter / cleanup)
        "is_admin_listing": True,  # alias for clarity
        "admin_nick": public_nick, # remembered for admin panel display
        "status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    
    await db.market_listings.insert_one(listing)
    
    meta = RESOURCE_TYPES.get(resource, {})
    return {
        "status": "listed",
        "listing_id": listing_id,
        "resource": resource,
        "resource_name": meta.get("name_ru", resource),
        "icon": meta.get("icon", "📦"),
        "amount": amount,
        "price_per_unit": round(price_ton * 1000, 2),  # return in $CITY for UI display
    }


@admin_router.get("/market/bot-listings")
async def admin_get_bot_listings(admin: User = Depends(get_admin_user)):
    """Get all active bot listings"""
    listings = await db.market_listings.find(
        {"is_bot": True, "status": "active"},
        {"_id": 0}
    ).to_list(100)
    return {"listings": listings}


@admin_router.delete("/market/bot-listing/{listing_id}")
async def admin_delete_bot_listing(listing_id: str, admin: User = Depends(get_admin_user)):
    """Remove a bot listing"""
    result = await db.market_listings.update_one(
        {"id": listing_id, "is_bot": True},
        {"$set": {"status": "cancelled"}}
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Bot listing not found")
    return {"status": "removed", "listing_id": listing_id}


# ==================== ADMIN BUYOUT (Выкук ресурсов «под левым именем») ====================

async def _admin_buyout_warehouse(user: dict, active_listings_amount_weighted: int = 0):
    """(used, capacity) of a player's warehouse for the admin buyout view.

    Same rule as everywhere (core/warehouse.py). The caller passes the weighted
    amount of the player's active lots it already aggregated. Storage buffs are
    now applied too (this copy used to ignore them)."""
    if not user:
        return 0, 0
    bizs = await warehouse_rules.user_businesses(db, user)
    capacity = warehouse_rules.total_capacity(bizs, await warehouse_rules.buff_map_for(db, bizs))
    used = warehouse_rules.used_by_resources(user.get("resources")) + int(active_listings_amount_weighted or 0)
    return int(used), int(capacity)


async def _admin_buyout_apply_sale(listing: dict, amount: int, buyer_nick: str, admin_name: str,
                                   *, payout: str = None, skip_listing_update: bool = False,
                                   city_market: bool = False):
    """Execute the seller-side of a P2P sale for an admin buyout.

    Replicates /market/buy seller economics (tier tax + seller buffs + credit
    deduction + tax haven + referral split + treasury tax). There is NO buyer
    balance (the buyer is a masked bot; no treasury balance is tracked)."""
    resource_type = listing["resource_type"]
    price_per_unit = float(listing["price_per_unit"])
    total_cost = round(amount * price_per_unit, 6)

    tax_settings = await db.admin_settings.find_one({"type": "tax_settings"}, {"_id": 0})
    resource_info = RESOURCE_TYPES.get(resource_type, {})
    resource_tier = resource_info.get("tier", 1)
    tax_rate = await get_business_sale_tax_rate(tax_settings, resource_tier)
    seller_buffs_all = await get_user_active_buffs_all(listing["seller_id"])
    tax_reduction = _buff_value_for(seller_buffs_all, "trade_tax_reduction", 0.0)
    license_mult = _buff_value_for(seller_buffs_all, "trade_fee_multiplier", 1.0)
    effective_tax_rate = max(0.0, tax_rate - tax_reduction)
    seller_tax = round(total_cost * effective_tax_rate * license_mult, 6)
    seller_receives = round(total_cost - seller_tax, 6)

    seller_filter = {"id": listing["seller_id"]}
    if listing.get("seller_email"):
        seller_filter = {"email": listing["seller_email"]}

    # Credit the seller (post-tax proceeds). Обычно на реальный balance_ton, но
    # для продавца без бизнесов / с бизнесом 0 уровня — на bonus_balance.
    import zero_business as _zb
    _ab_seller_ids = {listing.get("seller_id"), listing.get("seller_user_id"), listing.get("seller_email")}
    if payout in ("real", "bonus"):
        _ab_field = "balance_ton" if payout == "real" else "bonus_balance"
        if _ab_field == "bonus_balance":
            await db.users.update_one({**seller_filter, "bonus_balance": None}, {"$set": {"bonus_balance": 0.0}})
    else:
        _ab_field = "bonus_balance" if await _zb.should_credit_bonus(db, _ab_seller_ids) else "balance_ton"
    await db.users.update_one(
        seller_filter,
        {"$inc": {_ab_field: seller_receives, "total_income": seller_receives}},
    )

    # B2B partner yield commission (credit the seller's B2B partner, if any)
    try:
        from b2b_partners import credit_yield
        _sid = listing.get("seller_id") or listing.get("seller_user_id")
        if _sid:
            await credit_yield(db, _sid, seller_receives)
    except Exception as _e:
        logger.debug(f"b2b yield credit (admin buyout) failed: {_e}")

    # Credit repayment (withhold seller's configured % per active credit)
    credit_total_deducted, credit_details = await apply_credit_deduction(
        db,
        listing.get("seller_id") or listing.get("seller_user_id"),
        seller_receives,
        seller_wallet=listing.get("seller_wallet"),
        source="resource_sale",
        context={
            "listing_id": listing.get("id"),
            "resource": resource_type,
            "sale_amount_units": amount,
            "sale_amount_ton": seller_receives,
            "admin_buyout": True,
        },
    )

    # Alliance: Tax Haven (patron levy on seller's TON income)
    try:
        seller_user = await db.users.find_one(seller_filter, {"_id": 0, "id": 1, "balance_ton": 1})
        if seller_user and listing.get("business_id"):
            seller_biz = await db.businesses.find_one({"id": listing.get("business_id")}, {"_id": 0})
            if seller_biz and seller_biz.get("contract_id"):
                active_contract = await db.contracts.find_one(
                    {"id": seller_biz["contract_id"], "status": "active", "type": "tax_haven"},
                    {"_id": 0},
                )
                if active_contract:
                    rate = float(active_contract.get("tax_rate", 0.10) or 0.10)
                    patron_share = round(seller_receives * rate, 6)
                    available = float(seller_user.get("balance_ton", 0) or 0)
                    if patron_share > available:
                        patron_share = round(max(0.0, available), 6)
                    if patron_share > 0:
                        patron_id = active_contract.get("patron_id")
                        await db.users.update_one(seller_filter, {"$inc": {"balance_ton": -patron_share}})
                        await db.users.update_one(
                            {"$or": [{"id": patron_id}, {"wallet_address": patron_id}]},
                            {"$inc": {"balance_ton": patron_share}},
                        )
                        await db.contracts.update_one(
                            {"id": active_contract["id"]},
                            {"$inc": {"total_patron_income": patron_share}},
                        )
    except Exception as e:
        logger.error(f"admin buyout tax haven error: {e}")

    # Update the listing (partial or fully sold). Skipped when the caller
    # (City Market) already reserved the units atomically.
    if not skip_listing_update:
        new_amount = listing["amount"] - amount
        if new_amount <= 0:
            await db.market_listings.update_one(
                {"id": listing["id"]},
                {"$set": {"status": "sold", "sold_at": datetime.now(timezone.utc).isoformat(),
                          "sold_via": "city_market" if city_market else "admin_buyout"}},
            )
        else:
            await db.market_listings.update_one(
                {"id": listing["id"]},
                {"$set": {"amount": new_amount, "total_price": round(new_amount * price_per_unit, 6)}},
            )

    # Referral split + treasury tax
    # Destination (real vs bonus) depends on the seller's SOURCE business level.
    _seller_ref_doc = await db.users.find_one(seller_filter, {"_id": 0, "id": 1, "referrerId": 1, "username": 1})
    admin_tax, referral_amount, referrer_id, ref_to_bonus = await apply_referral_tax_split(
        _seller_ref_doc, total_cost, seller_tax, listing.get("business_id"))
    if referral_amount > 0 and referrer_id:
        await db.users.update_one(seller_filter, {"$inc": {"contributedToReferrer": referral_amount}})
        _bal_ru = "бонусный баланс" if ref_to_bonus else "реальный баланс"
        try:
            await db.transactions.insert_one({
                "id": str(uuid.uuid4()),
                "tx_type": "referral_income",
                "type": "referral_income",
                "user_id": referrer_id,
                "amount_ton": referral_amount,
                "to_balance": "bonus" if ref_to_bonus else "real",
                "counterparty_id": (_seller_ref_doc or {}).get("id"),
                "counterparty_username": (_seller_ref_doc or {}).get("username", ""),
                "description": f"Реферальный доход: +{round(referral_amount * 1000, 2)} $CITY от {(_seller_ref_doc or {}).get('username', '')} (на {_bal_ru})",
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as _re:
            logger.warning(f"admin buyout referral tx insert failed: {_re}")

    await db.admin_stats.update_one(
        {"type": "treasury"},
        {"$inc": {
            "market_tax": admin_tax,
            "resource_sales_tax": admin_tax,
            "resource_sales_count": 1,
            "total_tax": admin_tax,
        }},
        upsert=True,
    )

    # Transaction record — recorded as a normal market sale (`market_purchase`)
    # so the seller sees it in history as "Продажа ресурсов" with the NET amount
    # (post-tax). The buyer is a masked bot nick (not a real user account).
    seller_net_after_credit = round(seller_receives - credit_total_deducted, 6)
    tx = {
        "id": str(uuid.uuid4()),
        "tx_type": "market_purchase",
        "type": "market_purchase",
        "from_address": buyer_nick,
        "to_address": listing["seller_id"],
        "buyer_id": buyer_nick,
        "buyer_username": buyer_nick,
        "seller_id": listing["seller_id"],
        "amount_ton": total_cost,
        "amount": total_cost,
        "tax": seller_tax,
        "credit_deducted": credit_total_deducted,
        "seller_net_after_credit": seller_net_after_credit,
        "resource_type": resource_type,
        "resource_amount": amount,
        "listing_id": listing.get("id"),
        # Internal flags (not shown to players) — used by the admin buyout logs.
        "is_admin_buyout": not city_market,
        "is_city_market": city_market,
        "to_balance": "bonus" if _ab_field == "bonus_balance" else "real",
        "admin_nick": buyer_nick,
        "admin_executor": admin_name,
        "status": "completed",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.transactions.insert_one(tx)

    # Notify the seller (same UX as a normal market sale)
    try:
        from core.notify import notify_user_background
        seller_doc = await db.users.find_one(seller_filter, {"_id": 0})
        if seller_doc:
            seller_lang = (seller_doc.get("language") or "en").lower()
            if seller_lang not in ("ru", "en"):
                seller_lang = "en"
            res_name = resource_info.get(f"name_{seller_lang}") or resource_info.get("name_en") or resource_type
            city_received = round(seller_net_after_credit * 1000, 2)
            _to_bonus = _ab_field == "bonus_balance"
            if seller_lang == "ru":
                title = "Городской рынок купил ваш лот" if city_market else "Ресурсы проданы на маркете"
                who = "Городской рынок купил" if city_market else "Покупатель купил"
                msg = (
                    f"{who} {amount} ед. «{res_name}» за {total_cost:.4f} TON ({round(total_cost*1000,2)} $CITY).\n"
                    f"Вам начислено после налога: {seller_net_after_credit:.4f} TON ({city_received} $CITY)"
                    + (" на бонусный баланс." if _to_bonus else ".")
                )
            else:
                title = "The City Market bought your lot" if city_market else "Resources sold on the market"
                who = "The City Market bought" if city_market else "A buyer purchased"
                msg = (
                    f"{who} {amount} × {res_name} for {total_cost:.4f} TON ({round(total_cost*1000,2)} $CITY).\n"
                    f"You received after tax: {seller_net_after_credit:.4f} TON ({city_received} $CITY)"
                    + (" to your bonus balance." if _to_bonus else ".")
                )
            # background: a buyout of N lots must not wait N Telegram round-trips
            notify_user_background(
                db, seller_doc, title=title, message=msg,
                type_key="market_sold", priority="success",
                payload={"resource_type": resource_type, "amount": amount,
                         "received_ton": seller_net_after_credit, "gross_ton": total_cost},
            )
    except Exception as _e:
        logger.warning(f"admin buyout seller-notify failed: {_e}")

    return {
        "listing_id": listing.get("id"),
        "seller_id": listing["seller_id"],
        "seller_username": listing.get("seller_username"),
        "resource_type": resource_type,
        "amount": amount,
        "total_cost_ton": total_cost,
        "tax_ton": seller_tax,
        "seller_received_ton": seller_receives,
        "buyer_nick": buyer_nick,
        "to_balance": "bonus" if _ab_field == "bonus_balance" else "real",
    }


@admin_router.get("/buyout/nicks")
async def admin_buyout_nicks(admin: User = Depends(get_admin_user)):
    """Return the pool of 50 masked buyer nicknames for the buyout UI."""
    from core.admin_buyout_names import ADMIN_BUYOUT_NICKS
    return {"nicks": ADMIN_BUYOUT_NICKS}


@admin_router.get("/buyout/overview")
async def admin_buyout_overview(
    admin: User = Depends(get_admin_user),
    search: str = "",
    resource: str = "all",
    status: str = "all",   # all | with_lots
    sort: str = "units_desc",
):
    """Business owners overview for the buyout panel.

    Returns per-player rows (buildings, warehouse fill, active P2P lots, units
    available to buy) plus top-line statistics. Only resources actively listed
    on the P2P market are buyable (owners without lots show 0)."""
    # Active, non-bot player listings
    listing_query = {"status": "active", "is_bot": {"$ne": True}, "seller_id": {"$ne": "BOT_ADMIN"}}
    all_listings = await db.market_listings.find(listing_query, {"_id": 0}).to_list(100000)

    # Group listings by seller_id
    listings_by_seller = {}
    for lst in all_listings:
        sid = lst.get("seller_id")
        if not sid:
            continue
        listings_by_seller.setdefault(sid, []).append(lst)

    # All users owning at least one business
    owner_ids = await db.businesses.distinct("owner")
    owner_wallets = await db.businesses.distinct("owner_wallet")
    id_pool = list({*[o for o in owner_ids if o], *[w for w in owner_wallets if w]})
    users = await db.users.find(
        {"$or": [{"id": {"$in": id_pool}}, {"wallet_address": {"$in": id_pool}}]},
        {"_id": 0, "id": 1, "username": 1, "display_name": 1, "email": 1,
         "wallet_address": 1, "resources": 1, "balance_ton": 1},
    ).to_list(100000)

    total_businesses = await db.businesses.count_documents({})

    rows = []
    total_units_on_market = 0
    for user in users:
        uid = user.get("id")
        seller_lots = listings_by_seller.get(uid, [])
        # match by email too (some listings are email-keyed)
        if user.get("email"):
            for lst in all_listings:
                if lst.get("seller_email") == user.get("email") and lst.get("seller_id") != uid:
                    seller_lots.append(lst)

        # Resource filter for lots
        if resource and resource != "all":
            filtered_lots = [l for l in seller_lots if l.get("resource_type") == resource]
        else:
            filtered_lots = seller_lots

        lots = []
        weighted_listed = 0
        units_available = 0
        for lst in seller_lots:
            weighted_listed += int(lst.get("amount") or 0) * get_warehouse_weight(lst.get("resource_type"))
        for lst in filtered_lots:
            rt = lst.get("resource_type")
            meta = RESOURCE_TYPES.get(rt, {})
            amt = int(lst.get("amount") or 0)
            ppu = float(lst.get("price_per_unit") or 0)
            units_available += amt
            lots.append({
                "listing_id": lst.get("id"),
                "resource_type": rt,
                "resource_name": meta.get("name_ru", rt),
                "icon": meta.get("icon", "📦"),
                "tier": meta.get("tier", 1),
                "amount": amt,
                "price_per_unit_ton": ppu,
                "price_per_unit_city": round(ppu * 1000, 2),
                "total_city": round(amt * ppu * 1000, 2),
            })

        # Building count
        owner_keys = await resolve_owner_keys(db, uid)
        buildings = await db.businesses.count_documents(owner_businesses_query(owner_keys))
        used, capacity = await _admin_buyout_warehouse(user, weighted_listed)
        fill_pct = int(round(used / capacity * 100)) if capacity > 0 else 0

        row = {
            "player_id": uid,
            "username": user.get("username") or user.get("display_name") or "Anonymous",
            "display_name": user.get("display_name") or user.get("username") or "",
            "email": user.get("email"),
            "balance_ton": round(float(user.get("balance_ton") or 0), 4),
            "buildings": buildings,
            "warehouse_used": used,
            "warehouse_capacity": capacity,
            "warehouse_pct": fill_pct,
            "lots": lots,
            "lots_count": len(lots),
            "units_available": units_available,
            "has_lots": len(lots) > 0,
        }
        total_units_on_market += units_available
        rows.append(row)

    # Status filter
    if status == "with_lots":
        rows = [r for r in rows if r["has_lots"]]

    # Search filter
    if search:
        q = search.strip().lower()
        rows = [r for r in rows if q in (r["username"] or "").lower()
                or q in (r["display_name"] or "").lower()
                or q in (r["email"] or "").lower()
                or q in (r["player_id"] or "").lower()]

    # Sort
    if sort == "units_desc":
        rows.sort(key=lambda r: r["units_available"], reverse=True)
    elif sort == "warehouse_desc":
        rows.sort(key=lambda r: r["warehouse_pct"], reverse=True)
    elif sort == "buildings_desc":
        rows.sort(key=lambda r: r["buildings"], reverse=True)
    elif sort == "username_asc":
        rows.sort(key=lambda r: (r["username"] or "").lower())

    return {
        "stats": {
            "total_businesses": total_businesses,
            "total_owners": len(rows) if status != "with_lots" else len([r for r in rows]),
            "total_units_on_market": total_units_on_market,
            "resource_filter": resource,
        },
        "rows": rows,
    }


class AdminBuyoutItem(BaseModel):
    listing_id: str
    amount: int


class AdminBuyoutExecute(BaseModel):
    items: List[AdminBuyoutItem]
    mask_mode: str = "auto"          # auto | specific
    bot_username: Optional[str] = None


@admin_router.post("/buyout/execute")
async def admin_buyout_execute(data: AdminBuyoutExecute, admin: User = Depends(get_admin_user)):
    """Buy out selected P2P lots under a masked bot nickname.

    Each lot's seller is paid exactly as in a normal market sale (post-tax,
    with credit/tax-haven/referral applied). No treasury balance is enforced."""
    from core.admin_buyout_names import pick_buyout_nick, ADMIN_BUYOUT_NICKS

    if not data.items:
        raise HTTPException(status_code=400, detail="Не выбрано ни одного лота")

    if data.mask_mode == "specific":
        if not data.bot_username or data.bot_username not in ADMIN_BUYOUT_NICKS:
            raise HTTPException(status_code=400, detail="Выберите корректного бота из пула")

    import time as _time
    _t0 = _time.monotonic()
    admin_name = admin.username or admin.email or "admin"
    results = []
    total_units = 0
    total_cost_ton = 0.0
    total_tax_ton = 0.0
    per_resource = {}

    for item in data.items:
        if item.amount <= 0:
            continue
        listing = await db.market_listings.find_one(
            {"id": item.listing_id, "status": "active", "is_bot": {"$ne": True}},
            {"_id": 0},
        )
        if not listing:
            continue
        amount = min(int(item.amount), int(listing.get("amount") or 0))
        if amount <= 0:
            continue
        buyer_nick = data.bot_username if data.mask_mode == "specific" else pick_buyout_nick()
        res = await _admin_buyout_apply_sale(listing, amount, buyer_nick, admin_name)
        results.append(res)
        total_units += res["amount"]
        total_cost_ton += res["total_cost_ton"]
        total_tax_ton += res["tax_ton"]
        rt = res["resource_type"]
        meta = RESOURCE_TYPES.get(rt, {})
        if rt not in per_resource:
            per_resource[rt] = {"resource_name": meta.get("name_ru", rt), "icon": meta.get("icon", "📦"), "units": 0, "cost_city": 0.0}
        per_resource[rt]["units"] += res["amount"]
        per_resource[rt]["cost_city"] += round(res["total_cost_ton"] * 1000, 2)

    if not results:
        raise HTTPException(status_code=400, detail="Нет активных лотов для выкупа (возможно, уже проданы)")

    await db.admin_logs.insert_one({
        "action": "admin_buyout",
        "admin": admin_name,
        "mask_mode": data.mask_mode,
        "bot_username": data.bot_username if data.mask_mode == "specific" else "auto",
        "purchased_count": len(results),
        "total_units": total_units,
        "total_cost_ton": round(total_cost_ton, 6),
        "total_tax_ton": round(total_tax_ton, 6),
        "details": results,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    logger.info(f"⏱ admin buyout: {len(results)} lots in {(_time.monotonic() - _t0):.2f}s")

    return {
        "status": "completed",
        "purchased_count": len(results),
        "total_units": total_units,
        "total_cost_ton": round(total_cost_ton, 6),
        "total_cost_city": round(total_cost_ton * 1000, 2),
        "total_tax_ton": round(total_tax_ton, 6),
        "total_tax_city": round(total_tax_ton * 1000, 2),
        "per_resource": per_resource,
        "details": results,
    }


@admin_router.get("/buyout/logs/{player_id}")
async def admin_buyout_logs(player_id: str, admin: User = Depends(get_admin_user)):
    """Recent sale / buyout transactions for a player (Логи button in the table)."""
    txs = await db.transactions.find(
        {"$or": [{"seller_id": player_id}, {"user_id": player_id}],
         "tx_type": {"$in": ["admin_buyout", "market_purchase", "resource_sale"]}},
        {"_id": 0},
    ).sort("created_at", -1).to_list(50)
    for tx in txs:
        # Display net (post-tax) amount for sales, like the history page does.
        if tx.get("seller_net_after_credit") is not None:
            tx["display_amount_ton"] = tx["seller_net_after_credit"]
        else:
            tx["display_amount_ton"] = round(float(tx.get("amount_ton", 0) or 0) - float(tx.get("tax", 0) or 0), 6)
    return {"player_id": player_id, "logs": txs}


@admin_router.get("/market/all-listings")
async def admin_all_market_listings(
    resource: str = "all", search: str = "", admin: User = Depends(get_admin_user)
):
    """Торги: все активные объявления на продажу ресурсов (для админ-модерации)."""
    query = {"status": "active", "is_bot": {"$ne": True}, "tutorial": {"$ne": True}}
    if resource and resource != "all":
        query["resource_type"] = resource
    listings = await db.market_listings.find(query, {"_id": 0}).sort("created_at", -1).to_list(1000)
    s = (search or "").strip().lower()
    rows = []
    for l in listings:
        seller_name = l.get("seller_username") or ""
        seller_id = l.get("seller_id") or ""
        if s and s not in seller_name.lower() and s not in str(seller_id).lower():
            continue
        rt = l.get("resource_type")
        meta = RESOURCE_TYPES.get(rt, {})
        ppu_ton = float(l.get("price_per_unit", 0) or 0)
        rows.append({
            "listing_id": l.get("id"),
            "seller_id": seller_id,
            "seller_username": seller_name,
            "resource_type": rt,
            "resource_name": meta.get("name_ru", rt),
            "icon": meta.get("icon", "📦"),
            "tier": meta.get("tier", 1),
            "amount": int(l.get("amount", 0) or 0),
            "price_per_unit_city": round(ppu_ton * 1000, 2),
            "total_city": round(float(l.get("total_price", 0) or 0) * 1000, 2),
            "created_at": l.get("created_at"),
        })
    return {"listings": rows, "total": len(rows)}


@admin_router.delete("/market/listing/{listing_id}")
async def admin_delete_market_listing(listing_id: str, admin: User = Depends(get_admin_user)):
    """Торги: удалить (снять) объявление о продаже. Ресурсы возвращаются продавцу на склад."""
    listing = await db.market_listings.find_one({"id": listing_id, "status": "active"}, {"_id": 0})
    if not listing:
        raise HTTPException(status_code=404, detail="Объявление не найдено или уже неактивно")
    rtype = listing.get("resource_type")
    amount = int(listing.get("amount", 0) or 0)
    seller_id = listing.get("seller_id")
    seller_email = listing.get("seller_email")
    seller_filter = {"$or": [{"id": seller_id}, {"email": seller_email}, {"wallet_address": seller_id}]}
    if rtype and amount > 0:
        await db.users.update_one(seller_filter, {"$inc": {f"resources.{rtype}": amount}})
    await db.market_listings.update_one(
        {"id": listing_id},
        {"$set": {"status": "cancelled", "cancelled_at": datetime.now(timezone.utc).isoformat(),
                  "cancelled_reason": "admin_removed", "cancelled_by": admin.username or admin.email}},
    )
    await db.admin_logs.insert_one({
        "action": "market_listing_removed",
        "listing_id": listing_id,
        "resource_type": rtype,
        "amount_returned": amount,
        "seller_id": seller_id,
        "admin": admin.username or admin.email,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    # Notify the seller (localized) that admin removed the lot and returned goods.
    try:
        from core.notify import notify_user, notify_user_background
        from core.notif_i18n import user_lang
        seller_doc = await db.users.find_one(seller_filter, {"_id": 0})
        if seller_doc and rtype and amount > 0:
            lang = user_lang(seller_doc)
            meta = RESOURCE_TYPES.get(rtype, {})
            res_name = meta.get(f"name_{lang}") or meta.get("name_en") or meta.get("name_ru") or rtype
            notify_user_background(
                db, seller_doc, title=None, message=None,
                type_key="market_lot_returned", priority="info",
                i18n_key="market_lot_returned",
                i18n_vars={"res": res_name, "amount": amount},
            )
    except Exception as _e:
        logger.warning(f"admin_delete_market_listing notify failed: {_e}")
    return {"status": "removed", "listing_id": listing_id, "returned": {"resource": rtype, "amount": amount}}


# ==================== TELEGRAM BOT WEBHOOK ====================

from telegram_bot import TelegramBot, init_telegram_bot, get_telegram_bot

# Base URL for the Telegram Bot API (override via TELEGRAM_API_BASE env to route
# through a proxy / Cloudflare Worker on Telegram-blocked servers).
TELEGRAM_API_BASE = os.environ.get(
    "TELEGRAM_API_BASE", "https://api.telegram.org"
).rstrip("/")

class TelegramUpdate(BaseModel):
    update_id: int = 0
    message: dict = None
    callback_query: dict = None


def _detect_backend_url(request: Optional[Request] = None) -> str:
    """Detect the publicly-reachable backend URL. Priority: BACKEND_URL env →
    PUBLIC_APP_URL env → X-Forwarded headers → REACT_APP_BACKEND_URL from
    frontend/.env. Returns '' if none can be determined.
    """
    backend_url = (
        os.environ.get("BACKEND_URL", "").strip()
        or os.environ.get("PUBLIC_APP_URL", "").strip()
    )
    if not backend_url and request is not None:
        scheme = request.headers.get("x-forwarded-proto") or request.url.scheme or "https"
        host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
        if host:
            backend_url = f"{scheme}://{host}"
    if not backend_url:
        for env_path in ("/var/www/gramcity/frontend/.env", "/app/frontend/.env"):
            try:
                if os.path.exists(env_path):
                    with open(env_path, "r") as f:
                        for line in f:
                            if line.startswith("REACT_APP_BACKEND_URL="):
                                backend_url = line.split("=", 1)[1].strip().strip('"').strip("'")
                                break
                    if backend_url:
                        break
            except Exception:
                pass
    return backend_url.rstrip("/") if backend_url else ""


def _proxy_hint() -> str:
    """Warn when TELEGRAM_PROXY_URL is set to something that is NOT a real
    forward proxy (the #1 cause of '400 Bad Request, url=...workers.dev' — every
    Telegram API call is routed through it and fails)."""
    try:
        p = os.environ.get("TELEGRAM_PROXY_URL", "").strip().lower()
        if not p:
            return ""
        if "workers.dev" in p or not p.startswith(("http://", "https://", "socks4://", "socks5://")):
            return (
                " — ПОДСКАЗКА: TELEGRAM_PROXY_URL указывает на НЕ-прокси "
                f"({p}). Все запросы к api.telegram.org идут через него и падают. "
                "Cloudflare Worker (*.workers.dev) прокси не является. Удалите "
                "TELEGRAM_PROXY_URL из backend/.env (сервер обычно достаёт "
                "Telegram напрямую) и перезапустите backend."
            )
    except Exception:
        pass
    return ""


def _webhook_url_hint(webhook_url: str) -> str:
    """Return an actionable hint when the webhook URL looks misconfigured.
    The #1 real-world failure is a STALE `TELEGRAM_WEBHOOK_URL` env pointing at an
    old proxy (e.g. a *.workers.dev Cloudflare Worker that no longer exists), which
    Telegram rejects with a generic 400 Bad Request."""
    try:
        u = (webhook_url or "").lower()
        env_override = os.environ.get("TELEGRAM_WEBHOOK_URL", "").strip()
        backend_url = _detect_backend_url()
        expected = f"{backend_url}/api/telegram/webhook" if backend_url else ""
        if env_override and ("workers.dev" in u or (backend_url and not u.startswith(backend_url.lower()))):
            msg = (
                " — ПОДСКАЗКА: webhook берётся из переменной окружения "
                "TELEGRAM_WEBHOOK_URL и указывает на посторонний/устаревший адрес. "
                "Удалите TELEGRAM_WEBHOOK_URL из backend/.env (тогда адрес соберётся "
                "автоматически)"
            )
            if expected:
                msg += f", либо задайте TELEGRAM_WEBHOOK_URL={expected}"
            return msg + ", и перезапустите backend."
        if not u.startswith("https://"):
            return " — ПОДСКАЗКА: Telegram требует HTTPS-URL для webhook."
    except Exception:
        pass
    return ""


async def _register_telegram_webhook(bot_token: str, request: Optional[Request] = None) -> dict:
    """Register (or re-register) the Telegram webhook with a fresh secret_token.

    Persists bot_token + webhook_url + webhook_secret_token in
    game_settings.telegram_settings. Returns {ok, url, error?}.
    """
    import aiohttp as _aiohttp
    import secrets as _secrets

    # TELEGRAM_WEBHOOK_URL (env) overrides domain auto-detection. This lets ops
    # point Telegram's webhook at a proxy (e.g. a Cloudflare Worker) instead of
    # the server's own — possibly network-blocked — domain. When unset we fall
    # back to deriving it from the detected backend URL.
    webhook_url = os.environ.get("TELEGRAM_WEBHOOK_URL", "").strip()
    # Guard against copy-paste junk in .env (trailing '>', quotes, angle brackets,
    # whitespace) that would make Telegram reject the URL with a generic 400.
    webhook_url = webhook_url.strip().strip("<>").strip().strip('"').strip("'").strip()
    if not webhook_url:
        backend_url = _detect_backend_url(request)
        if not backend_url:
            return {"ok": False, "error": (
                "BACKEND_URL не определён. Пропишите PUBLIC_APP_URL или "
                "TELEGRAM_WEBHOOK_URL в backend/.env или откройте админку по "
                "публичному домену."
            )}
        webhook_url = f"{backend_url}/api/telegram/webhook"
    secret_token = _secrets.token_urlsafe(32)

    # Optional outbound proxy for servers where Telegram is network-blocked.
    # NOTE: this MUST be a real HTTP/SOCKS forward proxy. A Cloudflare Worker
    # (*.workers.dev) is NOT a proxy and will make EVERY Telegram call fail with
    # "400 Bad Request, url=<worker>". _proxy_hint() surfaces this clearly.
    _tg_proxy = os.environ.get("TELEGRAM_PROXY_URL", "").strip() or None

    async with _aiohttp.ClientSession(trust_env=True) as session:
        try:
            await session.post(
                f"{TELEGRAM_API_BASE}/bot{bot_token}/deleteWebhook",
                timeout=_aiohttp.ClientTimeout(total=15),
                proxy=_tg_proxy,
            )
        except Exception:
            pass
        try:
            res = await session.post(
                f"{TELEGRAM_API_BASE}/bot{bot_token}/setWebhook",
                json={"url": webhook_url, "secret_token": secret_token},
                timeout=_aiohttp.ClientTimeout(total=25),
                proxy=_tg_proxy,
            )
            data = await res.json()
        except TimeoutError:
            return {"ok": False, "error": (
                "не удалось подключиться к api.telegram.org (таймаут). "
                "Сервер не может достучаться до Telegram — проверьте сетевой "
                "доступ/файрвол или задайте TELEGRAM_PROXY_URL в backend/.env."
            )}
        except Exception as e:
            detail = str(e) or type(e).__name__
            return {"ok": False, "error": f"Telegram API error: {detail}{_proxy_hint()}{_webhook_url_hint(webhook_url)}"}

    if not data.get("ok"):
        desc = data.get("description", "Unknown error")
        return {"ok": False, "error": f"{desc} (webhook_url={webhook_url}){_proxy_hint()}{_webhook_url_hint(webhook_url)}"}

    await db.game_settings.update_one(
        {"type": "telegram_settings"},
        {"$set": {
            "type": "telegram_settings",
            "bot_token": bot_token,
            "webhook_url": webhook_url,
            "webhook_secret_token": secret_token,
        }},
        upsert=True,
    )
    os.environ["TELEGRAM_BOT_TOKEN"] = bot_token
    await _notify_bot_reload_token()
    return {"ok": True, "url": webhook_url}


# ── Independent bot process (bot_webhook_server.py) ──
# server.py acts ONLY as a mailbox: it receives the Telegram webhook, verifies
# it, and forwards the raw update to a SEPARATE OS process that runs all bot
# logic. Because the two processes have independent event loops and sockets,
# heavy game-API traffic can never delay/interrupt bot button handling (and
# vice-versa). Endpoint + timeout are overridable via env for other setups.
BOT_INTERNAL_URL = os.environ.get(
    "BOT_INTERNAL_URL", "http://127.0.0.1:8002/internal/telegram/update"
)
# Endpoint on the bot process to force a token reload after an admin token change.
BOT_RELOAD_TOKEN_URL = os.environ.get(
    "BOT_RELOAD_TOKEN_URL", "http://127.0.0.1:8002/internal/reload-token"
)
_bot_forward_client = None


def _get_bot_forward_client():
    """Lazily-created shared httpx client for forwarding updates to the bot
    process (reused across requests to avoid per-update socket churn at scale)."""
    global _bot_forward_client
    if _bot_forward_client is None:
        import httpx
        _bot_forward_client = httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.0))
    return _bot_forward_client


async def _notify_bot_reload_token():
    """Tell the independent bot process to drop its cached token and re-read the
    DB. Called after the admin saves/changes the bot token so /start replies
    from the NEW bot immediately (fire-and-forget, never blocks the response)."""
    try:
        client = _get_bot_forward_client()
        await client.post(BOT_RELOAD_TOKEN_URL)
    except Exception as e:
        logger.warning(f"Failed to notify bot process to reload token: {e}")


async def _forward_update_to_bot(update: dict):
    """Process a raw Telegram update.

    Runs in a BackgroundTask so it never blocks the webhook 200 OK to Telegram.
    Prefers the in-process bot (no external bot_webhook_server needed); falls
    back to BOT_INTERNAL_URL if it is reachable.
    """
    # Preferred path: process in-process.
    try:
        bot = get_telegram_bot()
    except Exception:
        bot = None
    if bot is not None:
        try:
            await bot.process_webhook(update)
            return
        except Exception as e:
            logger.warning(f"in-process bot update failed: {e}")
    # Fallback: independent bot_webhook_server.
    try:
        client = _get_bot_forward_client()
        await client.post(BOT_INTERNAL_URL, json=update)
    except Exception as e:
        logger.warning(f"Failed to forward Telegram update to bot process: {e}")


@api_router.post("/telegram/webhook")
@limiter.limit("120/minute")
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    """Telegram webhook — MAILBOX ONLY.

    F34: verify X-Telegram-Bot-Api-Secret-Token header against the secret we
    passed to Telegram at setWebhook time. If we have a stored secret_token
    but the incoming header doesn't match, drop silently.
    F36: rate-limited to 120 req/min per IP.

    This endpoint does NOT process bot logic. It verifies the request, grabs
    the JSON, and forwards it to the independent `bot_webhook_server.py` process
    (see BOT_INTERNAL_URL), then returns 200 OK to Telegram in ~1-2 ms.
    """
    try:
        settings = await db.game_settings.find_one({"type": "telegram_settings"}, {"_id": 0})
        expected_secret = (settings or {}).get("webhook_secret_token")
        if expected_secret:
            incoming = request.headers.get("x-telegram-bot-api-secret-token", "")
            import hmac as _hmac
            if not incoming or not _hmac.compare_digest(incoming, expected_secret):
                logger.warning("Telegram webhook: secret_token mismatch (dropped)")
                return {"ok": True}
    except Exception as _e:
        logger.warning(f"Telegram webhook secret verification error: {_e}")

    try:
        update = await request.json()
    except Exception as e:
        logger.warning(f"Telegram webhook: bad JSON body: {e}")
        return {"ok": True}

    # Hand the update to the independent bot process and ack Telegram instantly.
    background_tasks.add_task(_forward_update_to_bot, update)
    return {"ok": True}


@api_router.get("/telegram/webhook")
async def telegram_webhook_diagnostics():
    """Public diagnostic endpoint — helps debug 'bot doesn't reply on /start'.
    Safe to expose: returns only booleans and Telegram's own webhook status
    (no secrets). Anyone can query it, but nothing sensitive leaks.
    """
    diag = {
        "endpoint_reachable": True,
        "bot_token_loaded": False,
        "bot_initialized": False,
        "webhook_from_telegram": None,
    }
    try:
        bot = get_telegram_bot()
        diag["bot_initialized"] = bool(bot)
        if bot:
            tok = await bot.get_bot_token()
            diag["bot_token_loaded"] = bool(tok)
            if tok:
                import aiohttp as _aio
                async with _aio.ClientSession() as _s:
                    r = await _s.get(
                        f"{TELEGRAM_API_BASE}/bot{tok}/getWebhookInfo",
                        timeout=_aio.ClientTimeout(total=5),
                    )
                    if r.status == 200:
                        j = await r.json()
                        diag["webhook_from_telegram"] = j.get("result")
    except Exception as e:
        diag["error"] = str(e)[:200]
    return diag


@admin_router.post("/telegram/set-webhook")
async def admin_set_telegram_webhook(bot_token: str, request: Request, admin: User = Depends(get_current_admin_with_2fa)):
    """Set Telegram bot webhook.

    F34: uses shared _register_telegram_webhook() which rotates a fresh
    secret_token on every call.
    """
    result = await _register_telegram_webhook(bot_token, request)
    if result.get("ok"):
        return {"status": "webhook_set", "url": result["url"]}
    raise HTTPException(status_code=400, detail=f"Ошибка: {result.get('error', 'Unknown')}")


# ==================== STARTUP TELEGRAM BOT TOKEN ====================

@app.on_event("startup")
async def ensure_hot_query_indexes():
    """Indexes for the hot queries (core/db_indexes.py), in the background."""
    import asyncio as _asyncio
    from core.db_indexes import ensure_all as _ensure_all

    async def _run():
        try:
            await _ensure_all(db)
        except Exception as _e:
            logger.warning(f"index setup failed: {_e}")
    _asyncio.get_event_loop().create_task(_run())


@app.on_event("startup")
async def warm_smart_notification_translations():
    """Translate smart-notification templates into all languages via
    LibreTranslate in the background (cached in smart_notif_i18n)."""
    if not os.environ.get("LIBRETRANSLATE_URL"):
        return
    import asyncio as _asyncio

    async def _warm():
        try:
            res = await smart_notify.warm_translations()
            logger.info(f"smart_notify: LibreTranslate templates ready {res}")
        except Exception as _e:
            logger.warning(f"smart_notify warm-up failed: {_e}")
    _asyncio.get_event_loop().create_task(_warm())


@app.on_event("startup")
async def load_telegram_token():
    """Load Telegram bot token from DB on startup and initialize the bot.

    Reads from BOTH collections — some admin flows save the token in
    admin_settings.telegram_bot, others in game_settings.telegram_settings.
    We want it visible in os.environ regardless of which flow was used.

    The bot runs INSIDE this API process via webhook: incoming updates hit the
    `/api/telegram/webhook` endpoint, which acks Telegram instantly and does the
    heavy handling in a BackgroundTask. If a webhook URL is already stored, we
    re-register it here so the bot keeps working across restarts.
    """
    try:
        settings = await db.game_settings.find_one({"type": "telegram_settings"}, {"_id": 0})
        token_from_db = (settings or {}).get("bot_token")
        if not token_from_db:
            alt = await db.admin_settings.find_one({"type": "telegram_bot"}, {"_id": 0})
            token_from_db = (alt or {}).get("bot_token")
        # `TELEGRAM_BOT_TOKEN` from the env file takes priority over the DB
        # value — this lets ops rotate the token without having to log into
        # the admin panel. DB value is used only as a fallback for legacy
        # deployments that stored it via the admin UI.
        env_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        if env_token:
            logger.info("✅ Telegram bot token loaded from env")
        elif token_from_db:
            os.environ["TELEGRAM_BOT_TOKEN"] = token_from_db
            logger.info("✅ Telegram bot token loaded from DB")

        # Initialize Telegram bot
        bot = await init_telegram_bot(db)
        logger.info("✅ Telegram bot initialized")

        # Auto-setup webhook if we have the URL AND a secret_token stored
        # (fresh path). Fall back to legacy no-secret setup only if the token
        # was never registered here.
        # Auto-setup webhook on startup. TELEGRAM_WEBHOOK_URL (env) takes
        # priority over the value stored in the DB — this lets ops repoint the
        # webhook at a proxy (Cloudflare Worker) without touching the admin UI,
        # and prevents a stale DB URL (e.g. the server's blocked domain) from
        # being re-applied on every boot.
        env_webhook = os.environ.get("TELEGRAM_WEBHOOK_URL", "").strip()
        stored_webhook = settings.get("webhook_url") if settings else None
        webhook_to_set = env_webhook or stored_webhook
        if webhook_to_set:
            secret_token = (settings or {}).get("webhook_secret_token")
            result = await bot.setup_webhook(webhook_to_set, secret_token=secret_token)
            if result.get("success"):
                logger.info(f"✅ Telegram webhook auto-configured: {webhook_to_set}")
                # Persist the env-provided URL so the rest of the app (and the
                # admin panel) reflects what is actually registered.
                if env_webhook and env_webhook != stored_webhook:
                    await db.game_settings.update_one(
                        {"type": "telegram_settings"},
                        {"$set": {"type": "telegram_settings", "webhook_url": env_webhook}},
                        upsert=True,
                    )
            else:
                logger.warning(f"⚠️ Telegram webhook setup failed: {result.get('error')}")

    except Exception as e:
        logger.error(f"Failed to init telegram: {e}")


# ==================== ADMIN WALLET CONFIGURATION ====================

class SenderWalletConfig(BaseModel):
    mnemonic: str
    address: Optional[str] = None

class DepositWalletConfig(BaseModel):
    address: str
    name: Optional[str] = "Основной"

@admin_router.get("/settings/sender-wallet")
async def get_sender_wallet_config(admin: User = Depends(get_admin_user)):
    """Get sender wallet configuration (without mnemonic)"""
    wallet = await db.admin_settings.find_one({"type": "sender_wallet"}, {"_id": 0})
    if not wallet:
        return {"configured": False, "address": None}
    
    return {
        "configured": bool(wallet.get("mnemonic")),
        "address": wallet.get("address"),
        "updated_at": wallet.get("updated_at")
    }

@admin_router.post("/settings/sender-wallet")
async def set_sender_wallet_config(data: SenderWalletConfig, admin: User = Depends(require_scope("finance"))):
    """Configure sender wallet mnemonic for withdrawals"""
    # Validate mnemonic
    words = data.mnemonic.strip().split()
    if len(words) not in [12, 24]:
        raise HTTPException(status_code=400, detail="Мнемоника должна содержать 12 или 24 слова")
    
    # Try to derive address from mnemonic
    address = data.address
    if not address:
        try:
            from tonsdk.contract.wallet import WalletVersionEnum, Wallets
            mnemonics = data.mnemonic.strip().split()
            _, _, _, wallet = Wallets.from_mnemonics(mnemonics, WalletVersionEnum.v4r2, workchain=0)
            # Use mainnet UQ format: user_friendly=True, bounceable=True, testnet=False
            address = wallet.address.to_string(True, True, False)
        except Exception as e:
            logger.warning(f"Could not derive address from mnemonic: {e}")
    
    from mnemonic_crypto import encrypt_mnemonic
    await db.admin_settings.update_one(
        {"type": "sender_wallet"},
        {"$set": {
            "type": "sender_wallet",
            "mnemonic": encrypt_mnemonic(data.mnemonic.strip()),
            "address": address,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }},
        upsert=True
    )
    
    return {"status": "success", "address": address}

@admin_router.get("/settings/deposit-address")
async def get_deposit_address_config(admin: User = Depends(get_admin_user)):
    """Get deposit address configuration"""
    wallet = await db.admin_wallets.find_one({}, {"_id": 0, "mnemonic": 0})
    if not wallet:
        return {"configured": False, "address": None}
    
    return {
        "configured": True,
        "address": wallet.get("address"),
        "name": wallet.get("name", "Основной")
    }

@admin_router.post("/settings/deposit-address")
async def set_deposit_address_config(data: DepositWalletConfig, admin: User = Depends(get_current_admin_with_2fa)):
    """Configure main deposit address"""
    # Validate address format
    if not data.address or len(data.address) < 40:
        raise HTTPException(status_code=400, detail="Некорректный адрес кошелька")
    
    # Check if we already have wallets
    existing = await db.admin_wallets.find_one({}, {"_id": 0})
    
    if existing:
        # Update the first wallet
        await db.admin_wallets.update_one(
            {"id": existing.get("id")},
            {"$set": {
                "address": data.address,
                "name": data.name or "Основной",
                "updated_at": datetime.now(timezone.utc).isoformat()
            }}
        )
    else:
        # Create new wallet entry
        await db.admin_wallets.insert_one({
            "id": str(uuid.uuid4()),
            "address": data.address,
            "name": data.name or "Основной",
            "percentage": 100,
            "created_at": datetime.now(timezone.utc).isoformat()
        })
    
    return {"status": "success", "address": data.address}

@admin_router.get("/settings/telegram-bot")
async def get_telegram_bot_config(admin: User = Depends(get_admin_user)):
    """Get telegram bot configuration"""
    settings = await db.game_settings.find_one({"type": "telegram_settings"}, {"_id": 0})
    admin_settings = await db.admin_settings.find_one({"type": "telegram_bot"}, {"_id": 0})
    
    return {
        "bot_configured": bool(settings and settings.get("bot_token")),
        "webhook_url": settings.get("webhook_url") if settings else None,
        "admin_telegram_id": admin_settings.get("admin_telegram_id") if admin_settings else None,
        "bot_username": admin_settings.get("bot_username") if admin_settings else None,
        "channel_id": (admin_settings.get("channel_id") if admin_settings else None) or "",
        # Block 1: URL used as the "Open app" button under every Telegram
        # notification (low-resource alerts, etc.). Admin-configurable.
        "app_url": (settings.get("app_url") if settings else None) or "",
    }


class TelegramAppUrlRequest(BaseModel):
    app_url: str


@admin_router.post("/settings/telegram-app-url")
async def set_telegram_app_url(data: TelegramAppUrlRequest, admin: User = Depends(get_admin_user)):
    """Update the URL behind the «Open app» inline button used in Telegram
    notifications. Must be an http(s) URL — basic validation only."""
    url = (data.app_url or "").strip()
    if url and not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(status_code=400, detail="URL должен начинаться с http:// или https://")
    await db.game_settings.update_one(
        {"type": "telegram_settings"},
        {"$set": {"type": "telegram_settings", "app_url": url}},
        upsert=True,
    )
    return {"status": "ok", "app_url": url}

@admin_router.post("/settings/telegram-admin-id")
async def set_telegram_admin_id(admin: User = Depends(get_admin_user), admin_telegram_id: str = ""):
    """Set admin telegram ID for notifications"""
    if not admin_telegram_id:
        raise HTTPException(status_code=400, detail="Telegram ID обязателен")
    
    await db.admin_settings.update_one(
        {"type": "telegram_bot"},
        {"$set": {
            "type": "telegram_bot",
            "admin_telegram_id": admin_telegram_id.strip(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }},
        upsert=True
    )
    
    return {"status": "success", "admin_telegram_id": admin_telegram_id}

@admin_router.post("/settings/telegram-webhook")
async def setup_telegram_webhook_admin(request: Request, admin: User = Depends(get_current_admin_with_2fa)):
    """Setup telegram webhook using current backend URL.

    F34: routed through the shared _register_telegram_webhook() helper so the
    secret_token is rotated on every re-run. Requires a bot_token to already
    be saved (from either save_telegram_settings or admin_set_telegram_webhook).
    """
    settings = await db.game_settings.find_one({"type": "telegram_settings"}, {"_id": 0})
    bot_token = (settings or {}).get("bot_token")
    if not bot_token:
        alt = await db.admin_settings.find_one({"type": "telegram_bot"}, {"_id": 0})
        bot_token = (alt or {}).get("bot_token")
    if not bot_token:
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not bot_token:
        raise HTTPException(status_code=400, detail="Bot token не настроен")

    result = await _register_telegram_webhook(bot_token, request)
    if result.get("ok"):
        return {"status": "success", "webhook_url": result["url"]}
    raise HTTPException(status_code=500, detail=result.get("error", "Unknown error"))

class TelegramBotTokenRequest(BaseModel):
    bot_token: str


@admin_router.post("/settings/telegram-bot-token")
async def set_telegram_bot_token(data: TelegramBotTokenRequest, admin: User = Depends(get_admin_user)):
    """Persist the Telegram bot token WITHOUT registering a webhook.

    Fix for 'нажимаю сохранить — ничего не происходит': previously the only
    way to save a token was via set-webhook, which fails (and drops the token)
    whenever Telegram can't reach the webhook URL. Saving the token and
    activating the webhook are now two independent steps.
    """
    bot_token = (data.bot_token or "").strip()
    if not bot_token or ":" not in bot_token:
        raise HTTPException(status_code=400, detail="Некорректный токен бота")

    now = datetime.now(timezone.utc).isoformat()
    # Canonical location used by the bot runtime + webhook helper.
    await db.game_settings.update_one(
        {"type": "telegram_settings"},
        {"$set": {"type": "telegram_settings", "bot_token": bot_token, "updated_at": now}},
        upsert=True,
    )
    # Mirror into admin_settings (used by other admin reads).
    await db.admin_settings.update_one(
        {"type": "telegram_bot"},
        {"$set": {"type": "telegram_bot", "bot_token": bot_token, "updated_at": now}},
        upsert=True,
    )
    os.environ["TELEGRAM_BOT_TOKEN"] = bot_token
    # Re-init the in-process bot so notifications work immediately.
    try:
        await init_telegram_bot(db)
    except Exception as e:
        logger.warning(f"telegram bot re-init after token save failed: {e}")
    # Tell the independent bot process to pick up the new token right away.
    await _notify_bot_reload_token()
    return {"status": "success", "bot_configured": True}


class TelegramChannelRequest(BaseModel):
    channel_id: str


@admin_router.post("/settings/telegram-channel")
async def set_telegram_channel(data: TelegramChannelRequest, admin: User = Depends(get_admin_user)):
    """Persist the Telegram CHANNEL that published announcements are mirrored to.

    Accepts a public channel @username (with or without the leading @) or a
    numeric channel id like -1001234567890. The bot must be an ADMIN of that
    channel to be able to post. Announcements published via the admin panel are
    then posted into this channel, formatted exactly like the bot's messages.
    """
    raw = (data.channel_id or "").strip()
    channel_id = ""
    if raw:
        if raw.lstrip("-").isdigit():
            channel_id = raw                       # numeric id, e.g. -1001234567890
        else:
            channel_id = "@" + raw.lstrip("@")     # public @username
    await db.admin_settings.update_one(
        {"type": "telegram_bot"},
        {"$set": {
            "type": "telegram_bot",
            "channel_id": channel_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )
    return {"status": "success", "channel_id": channel_id}


@admin_router.post("/settings/telegram-bot-username")
async def set_telegram_bot_username(data: dict, admin: User = Depends(get_admin_user)):
    """Set telegram bot username for public display"""
    username = data.get("username", "").strip().replace("@", "")
    if not username:
        raise HTTPException(status_code=400, detail="Username обязателен")
    
    await db.admin_settings.update_one(
        {"type": "telegram_bot"},
        {"$set": {
            "bot_username": username,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }},
        upsert=True
    )
    
    return {"status": "success", "bot_username": username}

@admin_router.get("/settings/withdrawal-wallet")
async def get_withdrawal_wallet_config(admin: User = Depends(get_admin_user)):
    """Get withdrawal wallet configuration (without mnemonic) with balance"""
    wallet = await db.admin_settings.find_one({"type": "withdrawal_wallet"}, {"_id": 0})
    if not wallet:
        return {"configured": False, "address": None, "balance": 0}
    
    address = wallet.get("address")
    balance = 0

    # Fetch balance via the SAME reliable endpoint the deployer-wallet card uses
    # (toncenter getAddressBalance). The previous getWalletInformation call was
    # heavier and got rate-limited (HTTP 429) without an API key, so the card
    # always showed 0.0000 TON even though the wallet was funded.
    if address:
        try:
            deployer = get_contract_deployer(db)
            network = wallet.get("network") or "mainnet"
            balance = await deployer.get_wallet_balance(address, network)
        except Exception as e:
            logger.warning(f"Could not fetch withdrawal wallet balance: {e}")

    return {
        "configured": bool(wallet.get("mnemonic")),
        "address": address,
        "balance": round(balance, 4),
        "updated_at": wallet.get("updated_at")
    }

@admin_router.post("/settings/withdrawal-wallet")
async def set_withdrawal_wallet_config(data: dict, admin: User = Depends(require_scope("finance"))):
    """Configure withdrawal wallet mnemonic for automatic withdrawals"""
    mnemonic = data.get("mnemonic", "").strip()
    if not mnemonic:
        raise HTTPException(status_code=400, detail="Мнемоника обязательна")
    
    words = mnemonic.split()
    if len(words) not in [12, 24]:
        raise HTTPException(status_code=400, detail="Мнемоника должна содержать 12 или 24 слова")
    
    # Try to derive address from mnemonic
    address = None
    try:
        from tonsdk.contract.wallet import WalletVersionEnum, Wallets
        mnemonics = mnemonic.split()
        _, _, _, wallet = Wallets.from_mnemonics(mnemonics, WalletVersionEnum.v4r2, workchain=0)
        # Use mainnet UQ format: user_friendly=True, bounceable=True, testnet=False
        address = wallet.address.to_string(True, True, False)
    except Exception as e:
        logger.warning(f"Could not derive address from mnemonic: {e}")
    
    from mnemonic_crypto import encrypt_mnemonic
    await db.admin_settings.update_one(
        {"type": "withdrawal_wallet"},
        {"$set": {
            "type": "withdrawal_wallet",
            "mnemonic": encrypt_mnemonic(mnemonic),
            "address": address,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }},
        upsert=True
    )
    
    return {"status": "success", "address": address}

@admin_router.get("/patronage-info")
async def admin_get_patronage_info(admin: User = Depends(get_admin_user)):
    """Get patronage system info"""
    return {"patronage_effects": PATRONAGE_EFFECTS}


# ==================== CREDIT / LENDING SYSTEM ====================

class CreditSystemRequest(BaseModel):
    collateral_business_id: str
    amount: float
    salary_deduction_percent: float
    lender_type: str = "government"  # "government" or bank_business_id

@api_router.get("/credit/calculate/{business_id}")
async def calculate_max_credit(business_id: str, current_user: User = Depends(get_current_user)):
    """Calculate max credit for a business as collateral"""
    business = await db.businesses.find_one({"id": business_id}, {"_id": 0})
    if not business:
        raise HTTPException(status_code=404, detail="Бизнес не найден")
    
    ui = await get_user_identifiers(current_user)
    if not ui["user"] or not is_owner(business, ui["ids"]):
        raise HTTPException(status_code=403, detail="Это не ваш бизнес")
    import zero_business as _zb
    if int(business.get("level", 1) or 0) == 0 or await _zb.has_zero_business(db, ui["ids"]):
        raise HTTPException(status_code=403, detail="Кредит доступен только для бизнеса 1 уровня и выше.")
    
    # Check if already in collateral
    existing = await db.credits.find_one({
        "collateral_business_id": business_id,
        "status": {"$in": ["active", "overdue"]}
    })
    if existing:
        raise HTTPException(status_code=400, detail="Этот бизнес уже в залоге")
    
    # Calculate business value - use actual stored cost or config
    biz_type = business.get("business_type", "")
    level = business.get("level", 1)
    
    # Always get config for business name display
    config = BUSINESSES.get(biz_type, {})
    
    # Get base cost from business record or config
    base_cost = business.get("base_cost_ton")
    if not base_cost:
        base_cost = config.get("base_cost_ton", 5)
    
    upgrade_mult = UPGRADE_COST_MULTIPLIER
    
    # Calculate business value (only purchase cost + upgrades, NOT plot value)
    # Note: base_cost already defined above, use it directly
    upgrade_cost = 0
    for lvl in range(2, level + 1):
        upgrade_cost += base_cost * (upgrade_mult ** (lvl - 1))
    total_value = base_cost + upgrade_cost
    # Note: plot_value is NOT included - only business cost matters for collateral
    plot_value = 0  # Explicitly set to 0 as plot is not used for collateral
    
    max_credit = round(total_value * 0.30, 2)
    
    # Get government and bank rates
    gov_settings = await db.game_settings.find_one({"type": "credit_settings"}, {"_id": 0})
    gov_rate = gov_settings.get("government_interest_rate", 0.15) if gov_settings else 0.15
    
    # Get available banks for lending
    banks = await db.businesses.find(
        {"business_type": {"$in": ["gram_bank"]}, "durability": {"$gte": 50}},
        {"_id": 0}
    ).to_list(20)
    
    bank_options = []
    for bank in banks:
        bank_owner = bank.get("owner", "")
        if bank_owner in ui["ids"]:
            continue  # Can't borrow from own bank
        bank_settings = await db.credit_bank_settings.find_one({"bank_id": bank["id"]}, {"_id": 0})
        interest = bank_settings.get("interest_rate", 0.20) if bank_settings else 0.20
        overdue_days = bank_settings.get("overdue_penalty_days", 3) if bank_settings else 3
        bank_options.append({
            "bank_id": bank["id"],
            "bank_name": config.get("name", {}).get("ru", "Банк"),
            "owner": bank_owner,
            "level": bank.get("level", 1),
            "interest_rate": min(interest, 0.40),
            "overdue_penalty_days": overdue_days,
            "max_salary_deduction": 0.40,
        })
    
    return {
        "business_id": business_id,
        "business_type": biz_type,
        "business_level": level,
        "business_value": round(total_value, 2),
        "plot_value": plot_value,
        "max_credit": max_credit,
        "government": {
            "interest_rate": gov_rate,
            "max_salary_deduction": 0.40,
        },
        "banks": bank_options,
    }


@api_router.post("/credit/apply")
async def apply_for_credit(data: CreditSystemRequest, current_user: User = Depends(get_current_user)):
    """Apply for a credit/loan"""
    ui = await get_user_identifiers(current_user)
    if not ui["user"]:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    user = ui["user"]
    
    # Check existing active loans
    active_loans = await db.credits.count_documents({
        "$or": [{"borrower_id": uid} for uid in ui["ids"]],
        "status": {"$in": ["active", "overdue"]}
    })
    if active_loans >= 3:
        raise HTTPException(status_code=400, detail="Максимум 3 активных кредита")
    
    # Verify collateral business
    business = await db.businesses.find_one({"id": data.collateral_business_id}, {"_id": 0})
    if not business:
        raise HTTPException(status_code=404, detail="Бизнес не найден")
    if not is_owner(business, ui["ids"]):
        raise HTTPException(status_code=403, detail="Это не ваш бизнес")
    import zero_business as _zb
    if int(business.get("level", 1) or 0) == 0 or await _zb.has_zero_business(db, ui["ids"]):
        raise HTTPException(status_code=403, detail="Кредит доступен только для бизнеса 1 уровня и выше. Прокачайте бизнес нулевого уровня.")
    
    existing_collateral = await db.credits.find_one({
        "collateral_business_id": data.collateral_business_id,
        "status": {"$in": ["active", "overdue"]}
    })
    if existing_collateral:
        raise HTTPException(status_code=400, detail="Этот бизнес уже в залоге")
    
    # Cannot take credit if business is currently on sale
    if business.get("on_sale") or business.get("status") == "on_sale":
        raise HTTPException(status_code=400, detail="Бизнес на продаже — снимите с продажи, чтобы оформить кредит")
    
    # Calculate business value and max credit (same logic as calculate_max_credit)
    biz_type = business.get("business_type", "")
    level = business.get("level", 1)
    
    # Always get config for fallback
    config = BUSINESSES.get(biz_type, {})
    
    # Get base cost from business record or config
    base_cost = business.get("base_cost_ton")
    if not base_cost:
        base_cost = config.get("base_cost_ton", 5)
    
    total_value = base_cost
    for lvl in range(2, level + 1):
        total_value += base_cost * (UPGRADE_COST_MULTIPLIER ** (lvl - 1))
    
    # Add plot value - get actual plot price (same logic as calculate_max_credit)
    plot = await db.plots.find_one({"id": business.get("plot_id")}, {"_id": 0})
    if not plot:
        plot = await db.plots.find_one({"business_id": data.collateral_business_id}, {"_id": 0})
    plot_value = plot.get("price", 0) if plot else 0
    
    # If plot has no price stored, calculate based on zone
    if plot_value == 0:
        zone = business.get("zone", "outer")
        if plot:
            zone = plot.get("zone", zone)
        zone_prices = {"core": 100, "center": 50, "middle": 25, "outer": 10}
        plot_value = zone_prices.get(zone, 10)
    
    total_value += plot_value
    
    max_credit = total_value * 0.30
    
    if data.amount <= 0 or data.amount > max_credit:
        raise HTTPException(status_code=400, detail=f"Сумма должна быть от 0.01 до {max_credit:.2f} TON")
    
    # Determine lender type
    is_bank = data.lender_type != "government"
    
    if is_bank:
        bank = await db.businesses.find_one({"id": data.lender_type}, {"_id": 0})
        if not bank or "bank" not in bank.get("business_type", ""):
            raise HTTPException(status_code=400, detail="Указанный банк не найден")
        
        bank_settings = await db.credit_bank_settings.find_one({"bank_id": data.lender_type}, {"_id": 0})
        interest_rate = min(bank_settings.get("interest_rate", 0.20) if bank_settings else 0.20, 0.40)
        overdue_days = bank_settings.get("overdue_penalty_days", 3) if bank_settings else 3
        max_deduction = 0.40  # Changed from 0.25 to 0.40 (40%)
        lender_id = bank.get("owner", "")
        lender_name = f"Банк (Ур. {bank.get('level', 1)})"
    else:
        gov_settings = await db.game_settings.find_one({"type": "credit_settings"}, {"_id": 0})
        interest_rate = gov_settings.get("government_interest_rate", 0.15) if gov_settings else 0.15
        overdue_days = 7
        max_deduction = 0.40  # 40%
        lender_id = "government"
        lender_name = "Государство"
    
    if data.salary_deduction_percent <= 0 or data.salary_deduction_percent > max_deduction * 100:
        raise HTTPException(status_code=400, detail=f"Процент с зарплаты должен быть от 1% до {int(max_deduction*100)}%")
    
    total_debt = round(data.amount * (1 + interest_rate), 2)
    
    credit = {
        "id": str(uuid.uuid4()),
        "borrower_id": user.get("id", ""),
        "borrower_wallet": user.get("wallet_address", ""),
        "lender_type": "bank" if is_bank else "government",
        "lender_id": lender_id,
        "lender_bank_id": data.lender_type if is_bank else None,
        "lender_name": lender_name,
        "collateral_business_id": data.collateral_business_id,
        "collateral_business_type": biz_type,
        "collateral_value": round(total_value, 2),
        "amount": round(data.amount, 2),
        "interest_rate": interest_rate,
        "total_debt": total_debt,
        "paid": 0.0,
        "remaining": total_debt,
        "salary_deduction_percent": data.salary_deduction_percent / 100,
        "overdue_penalty_days": overdue_days,
        "is_doubled_rate": False,
        "overdue_since": None,
        "status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_payment": None,
        "next_payment_due": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    }
    
    await db.credits.insert_one(credit)
    
    # Credit the amount to borrower
    await db.users.update_one(
        get_user_filter(user),
        {"$inc": {"balance_ton": data.amount}}
    )
    
    # Record credit transaction in history
    credit_tx = {
        "id": str(uuid.uuid4()),
        "type": "credit_taken",
        "user_id": user.get("id", ""),
        "amount_ton": data.amount,
        "amount_city": data.amount * 1000,
        "description": f"Получение кредита от {lender_name}. Залог: {biz_type}",
        "credit_id": credit["id"],
        "lender_name": lender_name,
        "interest_rate": interest_rate,
        "total_debt": total_debt,
        "status": "completed",
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.transactions.insert_one(credit_tx)
    
    logger.info(f"Credit issued: {data.amount} TON to {user.get('username')} from {lender_name}")
    
    return {
        "status": "approved",
        "credit_id": credit["id"],
        "amount": credit["amount"],
        "total_debt": credit["total_debt"],
        "interest_rate": interest_rate,
        "salary_deduction": data.salary_deduction_percent,
        "collateral": biz_type,
    }


@api_router.get("/credit/my-loans")
async def get_my_loans(current_user: User = Depends(get_current_user)):
    """Get user's active and past loans"""
    ui = await get_user_identifiers(current_user)
    if not ui["user"]:
        return {"loans": [], "total_debt": 0}
    
    or_conds = [{"borrower_id": uid} for uid in ui["ids"]]
    or_conds.extend([{"borrower_wallet": uid} for uid in ui["ids"]])
    
    loans = await db.credits.find(
        {"$or": or_conds},
        {"_id": 0}
    ).sort("created_at", -1).to_list(50)
    
    total_debt = sum(l.get("remaining", 0) for l in loans if l.get("status") in ["active", "overdue"])
    
    return {
        "loans": loans,
        "total_debt": round(total_debt, 2),
        "active_count": sum(1 for l in loans if l.get("status") in ["active", "overdue"]),
    }


@api_router.get("/credit/sale-deduction-estimate")
async def credit_sale_deduction_estimate(
    amount: float,
    current_user: User = Depends(get_current_user),
):
    """
    Lightweight estimator the UI calls before confirming a listing.

    Given a prospective sale amount (after taxes), returns how much would
    be withheld for credit repayment per active credit. Used by the listing
    forms to display: "X% from this sale (~Y TON) will go to credit repayment".
    """
    ui = await get_user_identifiers(current_user)
    user = ui.get("user") or {}
    return await estimate_credit_deduction(
        db,
        user.get("id"),
        max(0.0, float(amount or 0)),
        seller_wallet=user.get("wallet_address"),
    )


@api_router.post("/credit/repay/{credit_id}")
async def repay_credit(credit_id: str, amount: float = 0, current_user: User = Depends(get_current_user)):
    """Early repayment of credit"""
    ui = await get_user_identifiers(current_user)
    if not ui["user"]:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    user = ui["user"]
    
    credit = await db.credits.find_one({"id": credit_id, "status": {"$in": ["active", "overdue"]}}, {"_id": 0})
    if not credit:
        raise HTTPException(status_code=404, detail="Кредит не найден")
    
    if credit.get("borrower_id") not in ui["ids"] and credit.get("borrower_wallet") not in ui["ids"]:
        raise HTTPException(status_code=403, detail="Это не ваш кредит")
    
    remaining = credit.get("remaining", 0)
    pay_amount = min(amount if amount > 0 else remaining, remaining)
    
    if user.get("balance_ton", 0) < pay_amount:
        raise HTTPException(status_code=400, detail="Недостаточно средств")
    
    # Deduct from user — F10 atomic compare-and-set.
    _credit_upd = await db.users.find_one_and_update(
        {**get_user_filter(user), "balance_ton": {"$gte": pay_amount}},
        {"$inc": {"balance_ton": -pay_amount}},
        return_document=ReturnDocument.AFTER,
    )
    if not _credit_upd:
        raise HTTPException(status_code=400, detail="Недостаточно средств")
    
    new_remaining = round(remaining - pay_amount, 2)
    new_paid = round(credit.get("paid", 0) + pay_amount, 2)
    
    update = {
        "$set": {
            "remaining": new_remaining,
            "paid": new_paid,
            "last_payment": datetime.now(timezone.utc).isoformat(),
        }
    }
    
    if new_remaining <= 0:
        update["$set"]["status"] = "paid"
        update["$set"]["remaining"] = 0
    
    await db.credits.update_one({"id": credit_id}, update)

    # Block C: split repayment — interest first to the bank owner, then the
    # principal to the government (sink).
    interest_total = round(float(credit.get("amount") or 0) * float(credit.get("interest_rate") or 0), 6)
    interest_paid_so_far = float(credit.get("paid") or 0)  # paid BEFORE this txn
    interest_remaining = max(0.0, interest_total - interest_paid_so_far)
    interest_part = round(min(interest_remaining, pay_amount), 6)
    principal_part = round(max(0.0, pay_amount - interest_part), 6)

    # Record repayment transaction in history
    repay_tx = {
        "id": str(uuid.uuid4()),
        "type": "credit_payment",
        "user_id": user.get("id", ""),
        "amount_ton": -pay_amount,
        "amount_city": -pay_amount * 1000,
        "description": f"Погашение кредита ({credit.get('lender_name', '')})",
        "credit_id": credit_id,
        "status": "completed",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "details": {
            "lender_type": credit.get("lender_type"),
            "lender_name": credit.get("lender_name") or "",
            "credit_remaining_after": max(0.0, new_remaining),
        },
    }
    await db.transactions.insert_one(repay_tx)

    # If bank loan, ONLY the interest portion goes to the bank owner.
    # The principal portion is a sink (i.e. goes to the government / treasury).
    if credit.get("lender_type") == "bank" and credit.get("lender_id") and interest_part > 0:
        await db.users.update_one(
            {"$or": [{"id": credit["lender_id"]}, {"wallet_address": credit["lender_id"]}]},
            {"$inc": {"balance_ton": interest_part}}
        )
    
    return {
        "status": "paid" if new_remaining <= 0 else "partial",
        "paid_amount": pay_amount,
        "remaining": max(0, new_remaining),
    }


@api_router.get("/credit/available-banks")
async def get_credit_banks(current_user: User = Depends(get_current_user)):
    """Get banks available for credit"""
    banks = await db.businesses.find(
        {"business_type": {"$regex": "bank"}, "durability": {"$gte": 50}},
        {"_id": 0}
    ).to_list(20)
    
    result = []
    for bank in banks:
        settings = await db.credit_bank_settings.find_one({"bank_id": bank["id"]}, {"_id": 0})
        result.append({
            "bank_id": bank["id"],
            "owner": bank.get("owner", ""),
            "level": bank.get("level", 1),
            "interest_rate": min(settings.get("interest_rate", 0.20) if settings else 0.20, 0.40),
            "overdue_penalty_days": settings.get("overdue_penalty_days", 3) if settings else 3,
        })
    
    return {"banks": result}


# ==================== BANK OWNER SETTINGS (Block A) ====================

class BankSettingsRequest(BaseModel):
    business_id: str
    interest_rate_percent: int  # credit interest, integer 0-40 (%)
    instant_fee_percent: int    # instant-withdrawal fee, integer 0-5 (%)


def _is_bank_business(business: dict) -> bool:
    """True if the business is a bank (supports instant withdrawal / credit)."""
    if not business:
        return False
    cfg = BUSINESSES.get(business.get("business_type"), {})
    return bool(cfg.get("instant_withdrawal")) or business.get("business_type") == "gram_bank"


@api_router.get("/bank/settings/{business_id}")
async def get_bank_settings(business_id: str, current_user: User = Depends(get_current_user)):
    """Return the owner-configurable settings for a bank business."""
    ui = await get_user_identifiers(current_user)
    if not ui["user"]:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    bank = await db.businesses.find_one({"id": business_id}, {"_id": 0})
    if not bank:
        raise HTTPException(status_code=404, detail="Бизнес не найден")
    if not is_owner(bank, ui["ids"]):
        raise HTTPException(status_code=403, detail="Это не ваш бизнес")
    if not _is_bank_business(bank):
        raise HTTPException(status_code=400, detail="Это не банк")

    settings = await db.credit_bank_settings.find_one({"bank_id": business_id}, {"_id": 0})
    interest_rate = settings.get("interest_rate", 0.20) if settings else 0.20
    instant_fee = settings.get("instant_fee", BankingSystem.INSTANT_FEE) if settings else BankingSystem.INSTANT_FEE
    return {
        "business_id": business_id,
        "interest_rate_percent": int(round(min(max(interest_rate, 0), 0.40) * 100)),
        "instant_fee_percent": int(round(min(max(instant_fee, 0), 0.05) * 100)),
        "max_interest_percent": 40,
        "max_instant_fee_percent": 5,
    }


@api_router.post("/bank/settings")
async def set_bank_settings(data: BankSettingsRequest, current_user: User = Depends(get_current_user)):
    """Owner of a bank sets credit interest (0-40%) and instant-withdrawal fee (0-5%)."""
    ui = await get_user_identifiers(current_user)
    if not ui["user"]:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    bank = await db.businesses.find_one({"id": data.business_id}, {"_id": 0})
    if not bank:
        raise HTTPException(status_code=404, detail="Бизнес не найден")
    if not is_owner(bank, ui["ids"]):
        raise HTTPException(status_code=403, detail="Это не ваш бизнес")
    if not _is_bank_business(bank):
        raise HTTPException(status_code=400, detail="Это не банк")

    try:
        interest_pct = int(data.interest_rate_percent)
        instant_pct = int(data.instant_fee_percent)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Проценты должны быть целыми числами")

    if interest_pct < 0 or interest_pct > 40:
        raise HTTPException(status_code=400, detail="Процент по кредиту должен быть от 0 до 40")
    if instant_pct < 0 or instant_pct > 5:
        raise HTTPException(status_code=400, detail="Комиссия за мгновенный вывод должна быть от 0 до 5")

    await db.credit_bank_settings.update_one(
        {"bank_id": data.business_id},
        {"$set": {
            "bank_id": data.business_id,
            "owner_id": ui["primary_id"],
            "interest_rate": round(interest_pct / 100.0, 4),
            "instant_fee": round(instant_pct / 100.0, 4),
            "overdue_penalty_days": (await db.credit_bank_settings.find_one({"bank_id": data.business_id}, {"_id": 0}) or {}).get("overdue_penalty_days", 3),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )
    return {
        "status": "ok",
        "interest_rate_percent": interest_pct,
        "instant_fee_percent": instant_pct,
    }



# ==================== PROMO CODE ACTIVATION ====================

class PromoActivateRequest(BaseModel):
    code: str

@api_router.post("/promo/activate")
async def activate_promo_code(
    data: Optional[PromoActivateRequest] = None,
    code: Optional[str] = None,
    current_user: User = Depends(get_current_user)
):
    """Activate a promo code and add balance. Accepts code in body or query parameter."""
    # Support both body and query parameter
    promo_code = code
    if data and data.code:
        promo_code = data.code
    if not promo_code:
        raise HTTPException(status_code=400, detail="Код промокода обязателен")
    ui = await get_user_identifiers(current_user)
    if not ui["user"]:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    
    promo = await db.promos.find_one({"code": promo_code.upper().strip(), "is_active": True})
    if not promo:
        raise HTTPException(status_code=404, detail="Промокод не найден или неактивен")
    
    if promo.get("current_uses", 0) >= promo.get("max_uses", 1):
        raise HTTPException(status_code=400, detail="Промокод уже использован максимальное количество раз")
    
    # Check if user already used this promo
    user_id = ui["user"].get("id", "")
    used = await db.promo_uses.find_one({"promo_id": promo["id"], "user_id": user_id})
    if used:
        raise HTTPException(status_code=400, detail="Вы уже использовали этот промокод")
    
    amount = promo.get("amount", 0)
    
    # Credit user
    await db.users.update_one(
        get_user_filter(ui["user"]),
        {"$inc": {"balance_ton": amount}}
    )
    
    # Record usage
    await db.promo_uses.insert_one({
        "promo_id": promo["id"],
        "user_id": user_id,
        "amount": amount,
        "used_at": datetime.now(timezone.utc).isoformat()
    })
    
    # Increment usage counter
    await db.promos.update_one(
        {"id": promo["id"]},
        {"$inc": {"current_uses": 1}}
    )
    
    # Log transaction
    await db.transactions.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "type": "promo_activation",
        "amount": amount,  # Positive - user received money
        "details": {
            "promo_code": promo_code.upper(),
            "promo_name": promo.get("name", "")
        },
        "created_at": datetime.now(timezone.utc).isoformat()
    })
    
    # Get new balance
    updated_user = await db.users.find_one(get_user_filter(ui["user"]), {"_id": 0, "balance_ton": 1})
    new_balance = updated_user.get("balance_ton", 0) if updated_user else 0
    
    return {
        "status": "activated",
        "amount": amount,
        "promo_name": promo.get("name", ""),
        "new_balance": new_balance
    }


# ==================== TELEGRAM BINDING ====================

@api_router.post("/auth/link-telegram")
async def link_telegram(telegram_username: str, current_user: User = Depends(get_current_user)):
    """Link Telegram account for notifications"""
    ui = await get_user_identifiers(current_user)
    if not ui["user"]:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    
    clean_username = telegram_username.strip().lstrip("@")
    if not clean_username:
        raise HTTPException(status_code=400, detail="Укажите username Telegram")
    
    await db.users.update_one(
        get_user_filter(ui["user"]),
        {"$set": {"telegram_username": clean_username, "telegram_notifications": True}}
    )
    
    return {"status": "linked", "telegram_username": clean_username}


@api_router.post("/auth/unlink-telegram")
async def unlink_telegram(current_user: User = Depends(get_current_user)):
    """Unlink Telegram account — clears ALL telegram-related fields so the UI
    doesn't show the account as still linked after a page refresh.

    Refuses if Telegram is the user's ONLY authentication method (no password,
    no wallet, no Google) — otherwise they'd lose access to their account.
    """
    ui = await get_user_identifiers(current_user)
    if not ui["user"]:
        raise HTTPException(status_code=401, detail="Пользователь не найден")

    user_doc = ui["user"]
    has_password = bool(user_doc.get("hashed_password"))
    has_wallet = bool(user_doc.get("wallet_address") or user_doc.get("raw_address"))
    has_google = bool(user_doc.get("google_id")) or user_doc.get("registration_method") == "google"
    if not (has_password or has_wallet or has_google):
        raise HTTPException(
            status_code=400,
            detail="telegram_only_auth_cannot_unlink",
        )

    # Remember the chat_id so we can send a "Telegram unlinked" notification
    # AFTER the DB write, before returning.
    _chat_id = str(user_doc.get("telegram_chat_id") or user_doc.get("telegram_id") or "").strip()

    await db.users.update_one(
        get_user_filter(ui["user"]),
        {"$unset": {
            "telegram_id": "",
            "telegram_user_id": "",
            "telegram_chat_id": "",
            "telegram_username": "",
            "telegram_verified": "",
            "telegram_notifications": "",
        }}
    )

    try:
        if _chat_id:
            from routes.telegram_notifications import notify_link_event as _notify_link_event
            import asyncio as _asyncio
            _asyncio.create_task(_notify_link_event(db, _chat_id, "unlinked"))
    except Exception:
        pass

    return {"status": "unlinked"}


# ==================== ADMIN CREDIT MANAGEMENT ====================

@admin_router.get("/credits")
async def admin_get_credits(status: str = None, admin: User = Depends(get_admin_user)):
    """Get all credits/loans with seized building info"""
    query = {}
    if status:
        query["status"] = status
    
    credits = await db.credits.find(query, {"_id": 0}).sort("created_at", -1).to_list(200)
    
    # Enrich with seized building info
    for credit in credits:
        if credit.get("status") in ["overdue", "seized"]:
            biz_id = credit.get("collateral_business_id")
            if biz_id:
                business = await db.businesses.find_one({"id": biz_id}, {"_id": 0})
                if business:
                    credit["seized_building"] = {
                        "id": biz_id,
                        "type": business.get("type"),
                        "level": business.get("level", 1),
                        "for_sale": business.get("for_sale", False),
                        "sale_price": business.get("sale_price", 0),
                        "current_owner": business.get("owner")
                    }
    
    total_active_debt = sum(c.get("remaining", 0) for c in credits if c.get("status") in ["active", "overdue"])
    total_issued = sum(c.get("amount", 0) for c in credits)
    seized_count = sum(1 for c in credits if c.get("status") == "seized")
    
    return {
        "credits": credits,
        "total_active_debt": round(total_active_debt, 2),
        "total_issued": round(total_issued, 2),
        "active_count": sum(1 for c in credits if c.get("status") in ["active", "overdue"]),
        "seized_count": seized_count,
    }


@admin_router.get("/credits/collateral")
async def admin_get_collateral_businesses(admin: User = Depends(get_admin_user)):
    """
    List every business currently held as collateral for an active/overdue
    credit. Used by the admin "Залоговые бизнесы" panel to show:
      • which businesses are at risk
      • who owns them (the borrower)
      • how much credit is left
      • how many days remain before the business is auto-seized by the
        government (after 7 days of overdue status)
    """
    credits = await db.credits.find(
        {"status": {"$in": ["active", "overdue"]}},
        {"_id": 0},
    ).sort("created_at", -1).to_list(500)

    now = datetime.now(timezone.utc)
    rows = []
    for c in credits:
        biz_id = c.get("collateral_business_id")
        if not biz_id:
            continue
        business = await db.businesses.find_one({"id": biz_id}, {"_id": 0})
        if not business:
            continue

        # Resolve borrower nickname
        borrower_id = c.get("borrower_id") or ""
        borrower_username = ""
        if borrower_id:
            b_user = await db.users.find_one(
                {"$or": [{"id": borrower_id}, {"wallet_address": borrower_id}]},
                {"_id": 0, "username": 1, "display_name": 1, "email": 1},
            )
            if b_user:
                borrower_username = b_user.get("username") or b_user.get("display_name") or b_user.get("email") or ""

        # Days until seizure (only meaningful when overdue)
        days_until_seizure = None
        overdue_since = c.get("overdue_since")
        if overdue_since:
            try:
                os_dt = datetime.fromisoformat(overdue_since.replace("Z", "+00:00"))
                if os_dt.tzinfo is None:
                    os_dt = os_dt.replace(tzinfo=timezone.utc)
                days_passed = (now - os_dt).days
                days_until_seizure = max(0, 7 - days_passed)
            except Exception:
                days_until_seizure = None

        rows.append({
            "credit_id": c.get("id"),
            "business_id": biz_id,
            "business_type": business.get("type") or business.get("business_type") or "unknown",
            "business_level": business.get("level", 1),
            "borrower_id": borrower_id,
            "borrower_username": borrower_username,
            "owner_username": business.get("owner_username") or borrower_username,
            "amount": c.get("amount", 0),
            "total_debt": c.get("total_debt", 0),
            "remaining": c.get("remaining", 0),
            "collateral_value": c.get("collateral_value", 0),
            "lender_type": c.get("lender_type"),
            "lender_name": c.get("lender_name"),
            "status": c.get("status"),
            "overdue_since": overdue_since,
            "days_until_seizure": days_until_seizure,
            "created_at": c.get("created_at"),
        })

    return {"collateral": rows, "count": len(rows)}


class SeizedPriceRequest(BaseModel):
    price: float


@admin_router.get("/credits/seized")
async def admin_get_seized_businesses(admin: User = Depends(get_admin_user)):
    """Admin «Кредиты → Изъятые»: every business repossessed by GRAM CITY
    (durability_zero or credit_default), active listing or already sold."""
    from core.seizure import list_seized
    rows = await list_seized(db)
    return {"seized": rows, "count": len(rows)}


@admin_router.post("/credits/seized/{listing_id}/price")
async def admin_set_seized_price(listing_id: str, data: SeizedPriceRequest,
                                 admin: User = Depends(get_admin_user)):
    from core.seizure import set_seized_price
    res = await set_seized_price(db, listing_id, data.price)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("reason", "error"))
    return res


@admin_router.post("/credits/seized/{listing_id}/return")
async def admin_return_seized(listing_id: str, admin: User = Depends(get_admin_user)):
    """Cancel a seized listing and return the business to its former owner."""
    from core.seizure import return_seized
    res = await return_seized(db, listing_id)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("reason", "error"))
    return res



@admin_router.get("/credit-settings")
async def admin_get_credit_settings(admin: User = Depends(get_admin_user)):
    """Get credit system settings"""
    settings = await db.game_settings.find_one({"type": "credit_settings"}, {"_id": 0})
    return settings or {"type": "credit_settings", "government_interest_rate": 0.15}


@admin_router.post("/credit-settings")
async def admin_update_credit_settings(government_interest_rate: float, admin: User = Depends(get_admin_user)):
    """Update government credit settings"""
    if government_interest_rate < 0.01 or government_interest_rate > 1.0:
        raise HTTPException(status_code=400, detail="Ставка должна быть от 1% до 100%")
    
    await db.game_settings.update_one(
        {"type": "credit_settings"},
        {"$set": {
            "type": "credit_settings",
            "government_interest_rate": government_interest_rate,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True
    )
    
    return {"status": "updated", "government_interest_rate": government_interest_rate}


@admin_router.get("/user-details/{user_id}")
async def admin_get_user_details(user_id: str, admin: User = Depends(get_admin_user)):
    """Get detailed user info: credits, balance, business value"""
    user = await db.users.find_one(
        {"$or": [{"id": user_id}, {"wallet_address": user_id}, {"email": user_id}]},
        {"_id": 0, "hashed_password": 0}
    )
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    uid = user.get("id", "")
    wallet = user.get("wallet_address", "")
    
    # Get businesses
    biz_query = {"$or": [{"owner": uid}]}
    if wallet:
        biz_query["$or"].append({"owner": wallet})
    businesses = await db.businesses.find(biz_query, {"_id": 0}).to_list(50)
    
    total_biz_value = 0
    for biz in businesses:
        biz_type = biz.get("business_type", "")
        level = biz.get("level", 1)
        cfg = BUSINESSES.get(biz_type, {})
        base_cost = cfg.get("base_cost_ton", 5)
        val = base_cost
        for lvl in range(2, level + 1):
            val += base_cost * (UPGRADE_COST_MULTIPLIER ** (lvl - 1))
        total_biz_value += val
    
    # Get credits
    credit_query = {"$or": [{"borrower_id": uid}]}
    if wallet:
        credit_query["$or"].append({"borrower_wallet": wallet})
    credits = await db.credits.find(credit_query, {"_id": 0}).to_list(20)
    
    active_debt = sum(c.get("remaining", 0) for c in credits if c.get("status") in ["active", "overdue"])
    
    return {
        "user": user,
        "balance": user.get("balance_ton", 0),
        "total_business_value": round(total_biz_value, 2),
        "businesses_count": len(businesses),
        "businesses": [{
            "id": b["id"],
            "type": b.get("business_type"),
            "level": b.get("level", 1),
        } for b in businesses],
        "credits": credits,
        "active_debt": round(active_debt, 2),
        "available_withdrawal": max(0, round(user.get("balance_ton", 0) - active_debt, 2)),
        "id": uid,
        "multi_account_warning": await check_multi_account(user) if user.get("last_ip") else None
    }


@admin_router.get("/transaction/{tx_id}")
async def admin_get_transaction(tx_id: str, admin: User = Depends(get_admin_user)):
    """Get transaction by ID"""
    tx = await db.transactions.find_one({"id": tx_id}, {"_id": 0})
    if not tx:
        raise HTTPException(status_code=404, detail="Операция не найдена")
    
    # Get user info if available
    user_id = tx.get("user_id") or tx.get("owner")
    if user_id:
        user = await db.users.find_one({"$or": [{"id": user_id}, {"wallet_address": user_id}]}, {"username": 1, "_id": 0})
        if user:
            tx["user_username"] = user.get("username")
    
    return tx


@admin_router.post("/user/{user_id}/block")
async def admin_block_user(user_id: str, data: dict, admin: User = Depends(get_admin_user)):
    """Block a user"""
    reason = data.get("reason", "Нарушение правил")
    
    result = await db.users.update_one(
        {"$or": [{"id": user_id}, {"wallet_address": user_id}, {"email": user_id}]},
        {"$set": {
            "is_blocked": True,
            "block_reason": reason,
            "blocked_at": datetime.now(timezone.utc).isoformat(),
            "blocked_by": admin.email
        }}
    )
    
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    return {"success": True, "message": "Пользователь заблокирован"}


@admin_router.post("/user/{user_id}/unblock")
async def admin_unblock_user(user_id: str, admin: User = Depends(get_admin_user)):
    """Unblock a user"""
    result = await db.users.update_one(
        {"$or": [{"id": user_id}, {"wallet_address": user_id}, {"email": user_id}]},
        {"$set": {
            "is_blocked": False,
            "block_reason": None,
            "unblocked_at": datetime.now(timezone.utc).isoformat(),
            "unblocked_by": admin.email
        }}
    )
    
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    return {"success": True, "message": "Пользователь разблокирован"}


async def check_multi_account(user: dict) -> str:
    """Check for multi-accounting based on IP and device"""
    ip = user.get("last_ip")
    device = user.get("last_device")
    user_id = user.get("id")
    
    if not ip and not device:
        return None
    
    query = {"id": {"$ne": user_id}}
    conditions = []
    if ip:
        conditions.append({"last_ip": ip})
    if device:
        conditions.append({"last_device": device})
    
    if conditions:
        query["$or"] = conditions
    
    matching_users = await db.users.find(query, {"username": 1, "email": 1, "_id": 0}).to_list(5)
    
    if matching_users:
        usernames = [u.get("username") or u.get("email") for u in matching_users]
        return f"Совпадение с: {', '.join(usernames[:3])}"
    
    return None


# ==================== BUSINESS RECOMMENDATION API ====================

@api_router.get("/recommendations/build")
async def get_build_recommendations(current_user: User = Depends(get_current_user)):
    """Analyze the map and recommend the most demanded business to build.
    Based on supply/demand analysis of existing businesses on the map."""
    
    # Count existing businesses by type
    pipeline = [
        {"$group": {"_id": "$business_type", "count": {"$sum": 1}}}
    ]
    biz_counts_raw = await db.businesses.aggregate(pipeline).to_list(100)
    biz_counts = {item["_id"]: item["count"] for item in biz_counts_raw if item["_id"]}
    
    # Analyze supply/demand for each resource
    resource_supply = {}  # How much is produced
    resource_demand = {}  # How much is consumed
    
    for biz_type, config in BUSINESSES.items():
        count = biz_counts.get(biz_type, 0)
        if count == 0:
            continue
        
        produces = config.get("produces", "")
        consumes = config.get("consumes", {})
        
        # Base production at level 1
        base_prod = BUSINESS_LEVELS.get(biz_type, {}).get("production", {}).get(1, 0)
        resource_supply[produces] = resource_supply.get(produces, 0) + base_prod * count
        
        # Consumption
        base_cons = BUSINESS_LEVELS.get(biz_type, {}).get("consumption", {}).get(1, {})
        if isinstance(base_cons, dict):
            for res_name, amount in base_cons.items():
                resource_demand[res_name] = resource_demand.get(res_name, 0) + amount * count
        else:
            for res_name, ratio in consumes.items():
                resource_demand[res_name] = resource_demand.get(res_name, 0) + base_cons * ratio * count
    
    # Find deficits (demand > supply)
    deficits = {}
    for resource in set(list(resource_supply.keys()) + list(resource_demand.keys())):
        supply = resource_supply.get(resource, 0)
        demand = resource_demand.get(resource, 0)
        deficit = demand - supply
        if deficit > 0:
            deficits[resource] = deficit
    
    # Recommend businesses that produce deficit resources
    recommendations = []
    for biz_type, config in BUSINESSES.items():
        produces = config.get("produces", "")
        tier = config.get("tier", 1)
        existing = biz_counts.get(biz_type, 0)
        
        score = 0
        reason = ""
        
        if produces in deficits:
            score = deficits[produces] * (1 + tier * 0.5)
            reason = f"Дефицит {produces}: спрос превышает предложение"
        elif existing == 0:
            score = 50 * tier
            reason = "Нет ни одного на карте"
        else:
            score = max(0, 10 - existing) * tier
            reason = f"Мало на карте ({existing} шт.)"
        
        if score > 0:
            name_ru = config.get("name", {}).get("ru", biz_type)
            income_l1 = ESTIMATED_DAILY_INCOME.get(biz_type, {}).get(1, 0)
            recommendations.append({
                "business_type": biz_type,
                "name": name_ru,
                "icon": config.get("icon", ""),
                "tier": tier,
                "score": round(score, 1),
                "reason": reason,
                "cost_ton": config.get("base_cost_ton", 0),
                "estimated_daily_income": income_l1,
                "existing_count": existing,
            })
    
    recommendations.sort(key=lambda x: x["score"], reverse=True)
    
    return {
        "recommendations": recommendations[:5],
        "total_businesses_on_map": sum(biz_counts.values()),
        "deficits": deficits,
    }

# Public endpoint for users to check maintenance
@api_router.get("/maintenance-status")
async def get_public_maintenance_status():
    """Get maintenance status for users"""
    maintenance = await db.admin_stats.find_one({"type": "maintenance"}, {"_id": 0})
    if not maintenance:
        return {"enabled": False}
    
    enabled = maintenance.get("enabled", False)
    scheduled_at = maintenance.get("scheduled_at")
    started_at = maintenance.get("started_at")
    
    # Check if scheduled maintenance should start
    if enabled and scheduled_at and not started_at:
        try:
            scheduled_time = datetime.fromisoformat(scheduled_at.replace('Z', '+00:00'))
            if datetime.now(timezone.utc) >= scheduled_time:
                # Auto-start scheduled maintenance
                await db.admin_stats.update_one(
                    {"type": "maintenance"},
                    {"$set": {"started_at": datetime.now(timezone.utc).isoformat()}}
                )
                return {"enabled": True, "scheduled_at": scheduled_at, "started_at": datetime.now(timezone.utc).isoformat()}
            else:
                return {"enabled": False, "scheduled_at": scheduled_at}
        except Exception:
            pass
    
    return {
        "enabled": enabled and started_at is not None,
        "scheduled_at": scheduled_at,
        "started_at": started_at,
        "message": maintenance.get("message", "Технические работы")
    }


# ==================== PUBLIC TAX SETTINGS ====================

@public_router.get("/tax-settings")
async def get_public_tax_settings():
    """Получить публичные настройки налогов"""
    settings = await db.admin_settings.find_one({"type": "tax_settings"}, {"_id": 0})
    if not settings:
        return {
            "small_business_tax": 5,
            "medium_business_tax": 8,
            "large_business_tax": 10,
            "land_business_sale_tax": 10
        }
    return {
        "small_business_tax": settings.get("small_business_tax", 5),
        "medium_business_tax": settings.get("medium_business_tax", 8),
        "large_business_tax": settings.get("large_business_tax", 10),
        "land_business_sale_tax": settings.get("land_business_sale_tax", 10)
    }

# ==================== BUSINESS FINANCIAL MODEL (PUBLIC) ====================

@public_router.get("/business/financial-model")
async def get_business_financial_model():
    """Получить полную финансовую модель всех бизнесов"""
    result = {
        "businesses": {},
        "tier_names": TIER_NAMES,
        "level_multipliers": LEVEL_MULTIPLIERS
    }
    
    for business_type, tier in BUSINESS_TIERS.items():
        result["businesses"][business_type] = {
            "name_ru": BUSINESS_NAMES_RU.get(business_type, business_type),
            "tier": tier,
            "tier_name": TIER_NAMES.get(tier, ""),
            "levels": get_all_levels_info(business_type)
        }
    
    return result

@public_router.get("/business/financial-model/{business_type}")
async def get_business_model_by_type(business_type: str):
    """Получить финансовую модель конкретного бизнеса"""
    if business_type not in BUSINESS_TIERS:
        raise HTTPException(status_code=404, detail="Бизнес не найден")
    
    tier = get_business_tier(business_type)
    
    return {
        "business_type": business_type,
        "name_ru": BUSINESS_NAMES_RU.get(business_type, business_type),
        "tier": tier,
        "tier_name": TIER_NAMES.get(tier, ""),
        "levels": get_all_levels_info(business_type)
    }


# ==================== TELEGRAM INTEGRATION ====================

# Store for telegram linking tokens (in production use Redis)
telegram_link_tokens: Dict[str, Dict] = {}

# Telegram Admin Settings
class TelegramBotSettings(BaseModel):
    bot_username: str
    bot_token: Optional[str] = None
    admin_telegram_id: str

@admin_router.get("/telegram-settings")
async def get_telegram_settings(admin: User = Depends(get_admin_user)):
    """Get Telegram bot settings"""
    settings = await db.admin_settings.find_one({"type": "telegram_bot"}, {"_id": 0})
    if not settings:
        return {
            "bot_username": os.environ.get("TELEGRAM_BOT_USERNAME", "sale2x_bot"),
            "admin_telegram_id": os.environ.get("TELEGRAM_ADMIN_ID", ""),
            "has_bot_token": bool(os.environ.get("TELEGRAM_BOT_TOKEN"))
        }
    return {
        "bot_username": settings.get("bot_username", ""),
        "admin_telegram_id": settings.get("admin_telegram_id", ""),
        "has_bot_token": bool(settings.get("bot_token"))
    }

@admin_router.post("/telegram-settings")
async def save_telegram_settings(data: TelegramBotSettings, request: Request, admin: User = Depends(get_current_admin_with_2fa)):
    """Save Telegram bot settings.

    Fix for 'bot doesn't work on server after entering token via admin panel':
    when a new `bot_token` is provided, we now automatically register the
    webhook with Telegram (with a fresh secret_token, F34). Previously this
    endpoint only persisted the token to admin_settings and never called
    Telegram's setWebhook — so the bot would appear silent to the user until
    they discovered the separate 'Set Webhook' button in AdminPage.
    """
    update_data = {
        "type": "telegram_bot",
        "bot_username": data.bot_username.lstrip("@"),
        "admin_telegram_id": data.admin_telegram_id,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }

    if data.bot_token:
        update_data["bot_token"] = data.bot_token

    await db.admin_settings.update_one(
        {"type": "telegram_bot"},
        {"$set": update_data},
        upsert=True
    )

    response = {"status": "success"}

    # When the admin supplies a bot token here, mirror the token into the
    # canonical `game_settings.telegram_settings` doc AND register the webhook.
    if data.bot_token:
        os.environ["TELEGRAM_BOT_TOKEN"] = data.bot_token
        # Mirror into the canonical game_settings doc up-front so the bot uses
        # the NEW token even if webhook registration below fails (get_bot_token
        # reads game_settings first). Then notify the bot process to reload.
        await db.game_settings.update_one(
            {"type": "telegram_settings"},
            {"$set": {"type": "telegram_settings", "bot_token": data.bot_token,
                      "updated_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
        await _notify_bot_reload_token()
        try:
            reg = await _register_telegram_webhook(data.bot_token, request)
            if reg.get("ok"):
                response["webhook_set"] = True
                response["webhook_url"] = reg["url"]
            else:
                response["webhook_set"] = False
                response["webhook_error"] = reg.get("error", "unknown")
                logger.warning(f"Auto-setup webhook failed via /admin/telegram-settings: {reg.get('error')}")
        except Exception as e:
            response["webhook_set"] = False
            response["webhook_error"] = str(e)
            logger.warning(f"Auto-setup webhook exception via /admin/telegram-settings: {e}")

    return response

@api_router.post("/telegram/generate-link-token")
async def generate_telegram_link_token(current_user: User = Depends(get_current_user)):
    """Generate a unique token for linking Telegram via Deep Link"""
    ui = await get_user_identifiers(current_user)
    if not ui["user"]:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    
    # Generate unique token
    link_token = str(uuid.uuid4())[:16].replace("-", "").upper()

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=10)
    token_doc = {
        "user_id": ui["user"].get("id"),
        "user_filter": get_user_filter(ui["user"]),
        "created_at": now,
        "expires_at": expires_at,
    }

    # Store token BOTH in memory (fast path for same-process /start) AND in MongoDB
    # (survives supervisor/systemd restart between "generate link" click on the
    # website and the user actually opening the link in Telegram — that gap is
    # 10 minutes and prod backends restart on deploy far more often than that,
    # which is why linking silently failed previously).
    telegram_link_tokens[link_token] = token_doc
    try:
        await db.telegram_link_tokens.update_one(
            {"_id": link_token},
            {"$set": {**token_doc, "_id": link_token}},
            upsert=True,
        )
        # Best-effort TTL cleanup — sweep expired docs so the collection stays small.
        await db.telegram_link_tokens.delete_many({"expires_at": {"$lt": now}})
    except Exception as _e:
        logger.warning(f"telegram_link_tokens persist failed (falling back to memory): {_e}")

    # Clean up expired tokens in memory too
    expired = [k for k, v in telegram_link_tokens.items() if v["expires_at"] < now]
    for k in expired:
        del telegram_link_tokens[k]
    
    # Get bot username from env or admin settings
    bot_username = os.environ.get("TELEGRAM_BOT_USERNAME", "")
    if not bot_username:
        bot_settings = await db.admin_settings.find_one({"type": "telegram_bot"}, {"_id": 0})
        bot_username = bot_settings.get("bot_username", "sale2x_bot") if bot_settings else "sale2x_bot"
    
    return {
        "token": link_token,
        "expires_in": 600,  # 10 minutes
        "bot_link": f"https://telegram.me/{bot_username}?start={link_token}"
    }

@api_router.post("/telegram/link-callback")
async def telegram_link_callback(token: str, telegram_id: str, telegram_username: str = None):
    """Callback from Telegram bot to complete account linking"""
    if token not in telegram_link_tokens:
        raise HTTPException(status_code=400, detail="Недействительный или истёкший токен")
    
    token_data = telegram_link_tokens[token]
    
    # Check if token expired
    if datetime.now(timezone.utc) > token_data["expires_at"]:
        del telegram_link_tokens[token]
        raise HTTPException(status_code=400, detail="Токен истёк. Сгенерируйте новый.")
    
    # Link Telegram to user account
    update_data = {
        "telegram_chat_id": telegram_id,
        "telegram_notifications": True
    }
    if telegram_username:
        update_data["telegram_username"] = telegram_username.lstrip("@")
    
    await db.users.update_one(
        {"id": token_data["user_id"]},
        {"$set": update_data}
    )
    
    # Remove used token
    del telegram_link_tokens[token]
    
    return {"status": "linked", "telegram_id": telegram_id}

@api_router.get("/telegram/check-link")
async def check_telegram_link(current_user: User = Depends(get_current_user)):
    """Check if user has linked Telegram"""
    ui = await get_user_identifiers(current_user)
    if not ui["user"]:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    
    user = ui["user"]
    return {
        "is_linked": bool(user.get("telegram_chat_id")),
        "telegram_id": user.get("telegram_chat_id"),
        "telegram_username": user.get("telegram_username")
    }

@api_router.post("/user/link-telegram")
async def link_telegram(chat_id: str, current_user: User = Depends(get_current_user)):  # noqa: F811
    """Link Telegram chat_id to user account for notifications"""
    ui = await get_user_identifiers(current_user)
    if not ui["user"]:
        raise HTTPException(status_code=401, detail="User not found")
    
    await db.users.update_one(
        get_user_filter(ui["user"]),
        {"$set": {"telegram_chat_id": chat_id}}
    )
    
    return {"status": "linked", "chat_id": chat_id}

@api_router.delete("/user/unlink-telegram")
async def unlink_telegram(current_user: User = Depends(get_current_user)):  # noqa: F811
    """Unlink Telegram from user account — clears ALL telegram-related fields."""
    ui = await get_user_identifiers(current_user)
    if not ui["user"]:
        raise HTTPException(status_code=401, detail="User not found")
    
    await db.users.update_one(
        get_user_filter(ui["user"]),
        {"$unset": {
            "telegram_id": "",
            "telegram_chat_id": "",
            "telegram_username": "",
            "telegram_notifications": "",
        }}
    )
    
    return {"status": "unlinked"}


# Import auth router
from auth_handler import auth_router

# Import security router for 2FA and Passkey
from security.security_router import create_security_router
security_router = create_security_router(db)


# ==================== ADMIN: BUSINESS PRODUCTION / CONSUMPTION EDITOR ====================
# View & edit how much each business TYPE produces / consumes per level (1..10).
# Reads from the SAME business_config source the live businesses use, and edits
# apply to EVERY business of that type immediately. Overrides are persisted in
# db.business_config_overrides and re-applied on startup.

@admin_router.get("/business-config")
async def admin_get_business_config(admin: User = Depends(get_admin_user)):
    """Return the full production/consumption matrix for every business type."""
    from business_config import get_business_config_matrix
    return {"businesses": get_business_config_matrix()}


@admin_router.put("/business-config/{business_type}")
async def admin_update_business_config(
    business_type: str,
    payload: dict = Body(default={}),
    admin: User = Depends(get_admin_user),
):
    """Edit per-level production/consumption for ONE business type and apply it
    to ALL businesses of that type (they share this config).
    Body: {"production": {"1": 110, ...}, "consumption": {"1": {"biomass": 26}, ...}}
    """
    from business_config import (
        apply_config_override, get_business_config_entry, BUSINESS_KEY_MAP,
        BUSINESS_LEVELS, UPGRADE_COSTS_TABLE,
    )
    production = payload.get("production") or {}
    consumption = payload.get("consumption") or {}
    storage = payload.get("storage") or {}
    upgrade = payload.get("upgrade") or {}

    ok = apply_config_override(business_type, production, consumption, storage, upgrade)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Unknown business type: {business_type}")
    # durability: shifts that wear 100% + $CITY per 1% of repair (decimals like 0.3 allowed; empty = default)
    from business_config import apply_durability_override, DURABILITY_OVERRIDES
    dur = payload.get("durability") if isinstance(payload.get("durability"), dict) else None
    if dur is not None:
        def _num(v, lo, hi, name):
            if v in (None, ""):
                return None
            try:
                f = float(str(v).replace(",", "."))
            except ValueError:
                raise HTTPException(status_code=400, detail=f"{name}: нужно число")
            if not (lo < f <= hi):
                raise HTTPException(status_code=400, detail=f"{name}: от {lo} до {hi}")
            return round(f, 4)
        apply_durability_override(business_type,
                                  _num(dur.get("shifts_per_100"), 0, 10000, "Смен на 100% прочности"),
                                  _num(dur.get("repair_cost_per_pct_city"), -0.0001, 1000000, "Стоимость 1% прочности"))

    mapped = BUSINESS_KEY_MAP.get(business_type, business_type)
    # Persist the CURRENT (post-merge) tables so the change survives restarts.
    cur = BUSINESS_LEVELS.get(mapped, {})
    prod_doc = {str(k): int(v) for k, v in (cur.get("production") or {}).items()}
    stor_doc = {str(k): int(v) for k, v in (cur.get("storage") or {}).items()}
    cons_doc = {
        str(k): {rid: int(a) for rid, a in (v or {}).items()}
        for k, v in (cur.get("consumption") or {}).items()
        if isinstance(v, dict)
    }
    upg_doc = {
        str(k): {
            "city": int((v or {}).get("city", 0) or 0),
            "resource": (v or {}).get("resource"),
            "qty": int((v or {}).get("qty", 0) or 0),
        }
        for k, v in (UPGRADE_COSTS_TABLE.get(mapped) or {}).items()
        if isinstance(v, dict)
    }
    await db.business_config_overrides.update_one(
        {"business_type": mapped},
        {"$set": {
            "business_type": mapped,
            "production": prod_doc,
            "consumption": cons_doc,
            "storage": stor_doc,
            "upgrade": upg_doc,
            "durability": DURABILITY_OVERRIDES.get(mapped) or {},
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_by": getattr(admin, "id", None),
        }},
        upsert=True,
    )
    return {"success": True, "business": get_business_config_entry(mapped)}


@app.on_event("startup")
async def load_business_config_overrides():
    """Re-apply admin production/consumption overrides from DB on startup so
    edits persist across restarts (BUSINESS_LEVELS is otherwise code-defined)."""
    try:
        from business_config import apply_config_override
        applied = 0
        async for doc in db.business_config_overrides.find({}):
            try:                                       # durability settings saved from the admin
                from business_config import apply_durability_override as _ado
                _d = doc.get("durability") or {}
                if _d:
                    _ado(doc.get("business_type"), _d.get("shifts_per_100"), _d.get("repair_cost_per_pct_city"))
            except Exception:
                pass
            if apply_config_override(
                doc.get("business_type"),
                doc.get("production") or {},
                doc.get("consumption") or {},
                doc.get("storage") or {},
                doc.get("upgrade") or {},
            ):
                applied += 1
        if applied:
            logger.info(f"[business-config] re-applied {applied} override(s) from DB")
    except Exception as e:
        logger.warning(f"[business-config] override load skipped: {e}")


# Import business and history routers
from business_system import create_business_router
from transaction_history import create_history_router
business_router = create_business_router(db)
history_router = create_history_router(db)

# Include routers
app.include_router(api_router)
app.include_router(admin_router)
app.include_router(public_router)  # Public endpoints (no auth required)
app.include_router(auth_router, prefix="/api")  # Auth endpoints (/api/auth/...)
app.include_router(chat_router, prefix="/api")  # Chat endpoints (/api/chat/...)
app.include_router(security_router)  # Security endpoints (/api/security/...)
app.include_router(business_router)  # Business system endpoints
app.include_router(history_router)  # Transaction history endpoints

# ===== Domain routers (split from server.py for maintainability) =====
from routes.buffs import create_buffs_router
from routes.repair import create_repair_router
from routes.stats import create_stats_router
from routes.sprites import create_sprites_router
from routes.health import create_health_router
from routes.leaderboard import create_leaderboard_router
from routes.notifications import create_notifications_router
from routes.business_mgmt import create_business_mgmt_router
from routes.ton_island import create_ton_island_router
from routes.auth_wallet import create_auth_wallet_router
from routes.tutorial import create_tutorial_router
from routes.tenders import tenders_router, run_tender_clearing
from routes.trash import create_trash_router, refill_trash_piles as _refill_trash_piles
from tutorial_guard import TutorialGuardMiddleware

app.include_router(create_buffs_router(db))
app.include_router(create_repair_router(db))
from b2b_partners import create_b2b_router
app.include_router(create_b2b_router(db, get_current_admin))
# B2B Partner Programs (incoming verification: partner brings users, we verify
# land + market spend + referral attribution and return HTTP 200).
from routes.partner_programs import create_partner_admin_router, create_partner_public_router
_partner_backend_url = os.environ.get("APP_URL", "")
app.include_router(create_partner_admin_router(db, get_current_admin, _partner_backend_url))
app.include_router(create_partner_public_router(db))
# Business skins (map re-texturing): admin CRUD + user picker + map index.
from routes.skins import create_skins_admin_router, create_skins_user_router, seed_default_skins
app.include_router(create_skins_admin_router(db, get_current_admin))
app.include_router(create_skins_user_router(db, get_current_user))
app.include_router(create_stats_router(db))
app.include_router(create_sprites_router())
app.include_router(create_health_router())
app.include_router(create_leaderboard_router(db))
app.include_router(create_notifications_router(db))
app.include_router(create_business_mgmt_router(db))
app.include_router(create_ton_island_router(db))
app.include_router(create_auth_wallet_router(db))
app.include_router(create_tutorial_router(db, SECRET_KEY, ALGORITHM))
app.include_router(tenders_router, prefix="/api")  # B2B tender marketplace
app.include_router(create_trash_router(db))  # Trash piles (resource drops on empty GRAM-City plots)
from routes.tasks import create_tasks_router  # Tasks board (Задания) + daily login reward
_tasks_user_router, _tasks_admin_router, _tasks_v1_router, _tasks_v1_admin_router = create_tasks_router(db, get_current_user, get_admin_user)
app.include_router(_tasks_user_router)
app.include_router(quest_engine.create_quests_router(db, get_current_user, get_current_admin))  # /api/quests
app.include_router(analytics.create_analytics_router(db, get_current_admin))  # /api/admin/analytics
app.include_router(comeback.create_comeback_router(db, get_current_user, get_current_admin))  # /api/comeback
app.include_router(smart_notify.create_smart_notify_router(db, get_current_user, get_current_admin))  # /api/notifications/smart
app.include_router(market_maker.create_market_maker_router(db, get_current_admin, _admin_buyout_apply_sale))  # /api/admin/market-maker
app.include_router(leagues.create_leagues_router(db, get_current_user, get_current_admin))  # /api/leagues
app.include_router(reconciliation.create_reconciliation_router(db, get_current_admin))  # /api/admin/reconciliation
app.include_router(boosters.create_boosters_router(db, get_current_user))  # /api/boosters
app.include_router(city_pass.create_city_pass_router(db, get_current_user, get_current_admin))  # /api/pass
app.include_router(city_sprites.create_city_sprites_router(db, get_current_admin))  # /api/city-sprites
import city_districts  # districts of the new city map (open / lots on sale)
app.include_router(city_districts.create_city_districts_router(db, get_current_admin))
import rental as _rental  # renting businesses out
app.include_router(_rental.create_rental_router(db, get_current_user, get_current_admin))
import minigames as _minigames  # the first mini-game, run as a promotion
async def _optional_user(request):
    try:
        auth = request.headers.get("authorization") or ""
        if not auth.lower().startswith("bearer "):
            return None
        from fastapi.security import HTTPAuthorizationCredentials as _HAC
        return await get_current_user(_HAC(scheme="Bearer", credentials=auth.split(" ", 1)[1]))
    except Exception:
        return None
app.include_router(_minigames.create_minigames_router(db, get_current_user, get_current_admin, _optional_user))
import minigame_rewards_routes as _mg_rewards_routes  # thresholds, chests, NFT puzzles, boosters, NFT warehouse
app.include_router(_mg_rewards_routes.create_minigame_rewards_router(db, get_current_user, get_current_admin, _minigames.get_config))
app.include_router(_tasks_admin_router)
app.include_router(_tasks_v1_router)
app.include_router(_tasks_v1_admin_router)
from routes.honeytokens import honeytokens_router  # F37: canary endpoints
app.include_router(honeytokens_router)
# Referral Rally promo (user + admin endpoints)
from routes.promo import create_promo_router, create_promo_admin_router
app.include_router(create_promo_router(db))
app.include_router(create_promo_admin_router(db))
from routes.demo import create_demo_router
app.include_router(create_demo_router(db))
# Game Rules (Правила игры) — admin-authored, user-translated via LibreTranslate
from routes.rules import create_rules_router
app.include_router(create_rules_router(db))

from routes.roadmap import create_roadmap_router
app.include_router(create_roadmap_router(db))
# Telegram Mini App biometric authentication for withdrawals
from routes.tg_biometry import create_tg_biometry_router
app.include_router(create_tg_biometry_router(db, get_current_user, SECRET_KEY, ALGORITHM))

# Telegram authentication (seamless Mini App auto-login, Login Widget, unlink, step-up)
from routes.telegram_auth import create_telegram_auth_router
app.include_router(create_telegram_auth_router(get_current_user))
# Telegram deeplink login (universal — works in browser without /setdomain)
from routes.telegram_login_link import create_telegram_login_link_router
app.include_router(create_telegram_login_link_router(db))
# Tutorial guard middleware — blocks disallowed API calls while tutorial is active
app.add_middleware(TutorialGuardMiddleware, db=db, secret_key=SECRET_KEY, algorithm=ALGORITHM)
from demo_guard import DemoGuardMiddleware
app.add_middleware(DemoGuardMiddleware)

# Initialize chat handler with db
set_chat_db(db)

# Initialize support handler with db + dependencies. `dir()` inside a lambda
# returns the lambda's local scope (empty) — so the previous condition always
# short-circuited to None and no Telegram push ever left the server. Import
# `get_telegram_bot` directly and pass it verbatim.
try:
    from telegram_bot import get_telegram_bot as _get_tg_bot  # type: ignore
except Exception:  # pragma: no cover
    _get_tg_bot = None

init_support(
    database=db,
    get_current_user=get_current_user,
    get_admin_user=get_current_admin,
    telegram_bot_getter=_get_tg_bot,
)
app.include_router(support_router)
app.include_router(support_agent_router)
app.include_router(support_admin_router)


# F36: per-IP concurrent WebSocket connection limit. Protects against a client
# opening thousands of WS connections to exhaust FDs/memory. In-memory only —
# resets on backend restart (acceptable for anti-abuse).
_WS_MAX_PER_IP = int(os.environ.get("WS_MAX_PER_IP", "50"))
_ws_ip_counter: dict = {}


def _ws_client_ip(websocket: WebSocket) -> str:
    xff = websocket.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return (websocket.client.host if websocket.client else "unknown")


async def _ws_accept_or_reject(websocket: WebSocket) -> bool:
    ip = _ws_client_ip(websocket)
    current = _ws_ip_counter.get(ip, 0)
    if current >= _WS_MAX_PER_IP:
        try:
            await websocket.close(code=1013, reason="too many connections")
        except Exception:
            pass
        logger.warning(f"[WS] rejected {ip}: {current} active >= {_WS_MAX_PER_IP}")
        return False
    _ws_ip_counter[ip] = current + 1
    return True


def _ws_release(websocket: WebSocket) -> None:
    ip = _ws_client_ip(websocket)
    current = _ws_ip_counter.get(ip, 0)
    if current <= 1:
        _ws_ip_counter.pop(ip, None)
    else:
        _ws_ip_counter[ip] = current - 1


async def _ws_token_from_first_message(websocket: WebSocket):
    """F8: accept the socket and read the auth token from the first frame
    ({"action":"auth","token":"..."}) instead of the query string, so the JWT
    never lands in nginx access logs / browser history / Referer.
    Returns the token string, or None (socket already closed) on failure.
    """
    await websocket.accept()
    try:
        raw = await asyncio.wait_for(websocket.receive_json(), timeout=10)
    except Exception:
        try:
            await websocket.close(code=4001, reason="auth timeout")
        except Exception:
            pass
        return None
    if isinstance(raw, dict) and raw.get("action") == "auth" and raw.get("token"):
        return raw.get("token")
    try:
        await websocket.close(code=4001, reason="auth frame required")
    except Exception:
        pass
    return None


@app.websocket("/api/support/ws/user")
async def support_user_ws(websocket: WebSocket, token: str = None):
    if not await _ws_accept_or_reject(websocket):
        return
    pre_accepted = False
    if not token:
        token = await _ws_token_from_first_message(websocket)
        if not token:
            _ws_release(websocket)
            return
        pre_accepted = True
    try:
        await support_user_ws_handler(websocket, token, pre_accepted=pre_accepted)
    finally:
        _ws_release(websocket)


@app.websocket("/api/support/ws/agent")
async def support_agent_ws(websocket: WebSocket, token: str = None):
    if not await _ws_accept_or_reject(websocket):
        return
    pre_accepted = False
    if not token:
        token = await _ws_token_from_first_message(websocket)
        if not token:
            _ws_release(websocket)
            return
        pre_accepted = True
    try:
        await support_agent_ws_handler(websocket, token, pre_accepted=pre_accepted)
    finally:
        _ws_release(websocket)


# Alias endpoints under /api/ws/* — production nginx commonly only enables
# the WebSocket Upgrade headers on `location /api/ws/` (because that's the
# canonical path of the legacy game WS). The new support WebSocket lives
# at /api/support/ws/* and is silently downgraded to HTTP, which makes
# FastAPI's WS endpoint return 404 to the browser. These aliases let the
# frontend pick a path that nginx ALREADY upgrades, so the support panel
# works on existing VPS installations without nginx edits.
@app.websocket("/api/ws/support/user")
async def support_user_ws_alias(websocket: WebSocket, token: str = None):
    if not await _ws_accept_or_reject(websocket):
        return
    pre_accepted = False
    if not token:
        token = await _ws_token_from_first_message(websocket)
        if not token:
            _ws_release(websocket)
            return
        pre_accepted = True
    try:
        await support_user_ws_handler(websocket, token, pre_accepted=pre_accepted)
    finally:
        _ws_release(websocket)


@app.websocket("/api/ws/support/agent")
async def support_agent_ws_alias(websocket: WebSocket, token: str = None):
    if not await _ws_accept_or_reject(websocket):
        return
    pre_accepted = False
    if not token:
        token = await _ws_token_from_first_message(websocket)
        if not token:
            _ws_release(websocket)
            return
        pre_accepted = True
    try:
        await support_agent_ws_handler(websocket, token, pre_accepted=pre_accepted)
    finally:
        _ws_release(websocket)


# WebSocket endpoint for chat
@app.websocket("/api/ws/chat")
async def websocket_chat_endpoint(websocket: WebSocket, token: str = None):
    """WebSocket endpoint for real-time chat.

    F8: token may be supplied either via the (legacy) query string or, if
    absent, via the first {"action":"auth","token":"..."} frame.
    """
    if not await _ws_accept_or_reject(websocket):
        return
    pre_accepted = False
    if not token:
        token = await _ws_token_from_first_message(websocket)
        if not token:
            _ws_release(websocket)
            return
        pre_accepted = True
    try:
        await chat_websocket_handler(websocket, token, pre_accepted=pre_accepted)
    finally:
        _ws_release(websocket)


# Route-priority fix: Starlette matches WebSocket routes in registration order,
# and the parametrized `/api/ws/{user_id}` game socket (defined earlier) also
# matches `/api/ws/chat` (user_id="chat"), silently swallowing chat/auth frames.
# Reorder so the specific chat route is evaluated before the catch-all.
def _prioritize_ws_routes():
    routes = app.router.routes
    try:
        catchall_idx = next(
            i for i, r in enumerate(routes)
            if getattr(r, "path", "") == "/api/ws/{user_id}"
        )
    except StopIteration:
        return
    for specific in ("/api/ws/chat",):
        spec_route = next(
            (r for r in routes if getattr(r, "path", "") == specific), None
        )
        if spec_route is not None and routes.index(spec_route) > catchall_idx:
            routes.remove(spec_route)
            routes.insert(catchall_idx, spec_route)
            catchall_idx += 1


_prioritize_ws_routes()

# CORS (S2 / F5): strict origins list, NO wildcard fallback.
# Order of preference: explicit CORS_ORIGINS -> FRONTEND_URL -> PUBLIC_APP_URL -> localhost dev.
# If nothing is configured, we still allow only localhost dev origins (never '*'),
# which forces a proper prod configuration but doesn't break local development.
_cors_raw = os.environ.get('CORS_ORIGINS', '').strip()
if _cors_raw and _cors_raw != '*':
    _cors_origins = [o.strip() for o in _cors_raw.split(',') if o.strip() and o.strip() != '*']
else:
    _frontend = os.environ.get('FRONTEND_URL', '').strip()
    _public_app = os.environ.get('PUBLIC_APP_URL', '').strip()
    _cors_origins = [o for o in [_frontend, _public_app, 'http://localhost:3000', 'http://127.0.0.1:3000'] if o]
    # De-duplicate while preserving order
    _seen = set()
    _cors_origins = [o for o in _cors_origins if not (o in _seen or _seen.add(o))]
if not _cors_origins:
    # Absolute last resort: refuse wildcard, keep dev localhost only.
    _cors_origins = ['http://localhost:3000']
    logger.error("[SECURITY] CORS_ORIGINS not configured. Refusing wildcard '*'. "
                 "Falling back to localhost only — configure CORS_ORIGINS or FRONTEND_URL in production!")
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
logger.info(f"[SECURITY] CORS origins: {_cors_origins}")

# Security headers (S7)
app.add_middleware(SecurityHeadersMiddleware)

# Rate limiter (S3) — slowapi
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.responses import JSONResponse as _SAJSONResponse

app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request, exc):
    return _SAJSONResponse(
        status_code=429,
        content={"detail": "Слишком много запросов. Попробуйте чуть позже."},
    )


# Graceful DB-outage handling: when MongoDB is unreachable (mongod down,
# connection refused, pool exhausted, replica-set election, …) return a clean
# 503 instead of letting a ServerSelectionTimeoutError/AutoReconnect bubble up
# as an unhandled ASGI 500. This keeps workers stable during transient outages.
from pymongo.errors import PyMongoError as _PyMongoError

@app.exception_handler(_PyMongoError)
async def _mongo_error_handler(request, exc):
    logger.error(f"MongoDB unavailable ({type(exc).__name__}): {exc}")
    return _SAJSONResponse(
        status_code=503,
        content={"detail": "База данных временно недоступна. Повторите попытку через несколько секунд."},
    )


# F12: admin audit log middleware. Persists every mutating call to admin_router
# to `admin_audit_log` (append-only from the app's PoV — we never update or
# delete). Reads (GET) are ignored to keep the collection small. Response
# status is captured so we can distinguish successful actions from 403/500.
class AdminAuditLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path or ""
        method = request.method
        # Only mutating admin calls are audited.
        if not path.startswith("/api/admin/") or method in ("GET", "HEAD", "OPTIONS"):
            return await call_next(request)
        response = await call_next(request)
        try:
            # Resolve who made the call (best-effort — we only decode if a
            # bearer token is present; we don't want to fail the request if
            # decoding fails).
            admin_id = None
            admin_email = None
            auth = request.headers.get("authorization", "")
            if auth.lower().startswith("bearer "):
                try:
                    payload = jwt.decode(auth.split(" ", 1)[1], SECRET_KEY, algorithms=[ALGORITHM])
                    admin_email = payload.get("sub")
                except Exception:
                    pass
            if admin_email:
                udoc = await db.users.find_one({"email": admin_email}, {"_id": 0, "id": 1, "is_admin": 1})
                if udoc:
                    admin_id = udoc.get("id")
                    if not udoc.get("is_admin"):
                        # Non-admin call to admin route — still worth logging.
                        pass

            client_ip = (
                request.headers.get("cf-connecting-ip")
                or (request.headers.get("x-forwarded-for", "").split(",")[0].strip() if request.headers.get("x-forwarded-for") else None)
                or (request.client.host if request.client else "unknown")
            )
            entry = {
                "path": path,
                "method": method,
                "status": getattr(response, "status_code", None),
                "admin_id": admin_id,
                "admin_email": admin_email,
                "ip": client_ip,
                "user_agent": (request.headers.get("user-agent", "") or "")[:200],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            # Fire-and-forget — never block the request on audit-log write.
            # Wrap in a guarded coroutine so a failing insert (e.g. Mongo down)
            # can't surface as an un-retrieved task exception in the event loop.
            async def _safe_audit_insert(_entry):
                try:
                    await db.admin_audit_log.insert_one(_entry)
                except Exception as _ie:
                    logger.warning(f"[audit] insert failed: {_ie}")
            asyncio.create_task(_safe_audit_insert(entry))
        except Exception as _e:
            # Audit-log failures must never break the actual request.
            logger.warning(f"[audit] failed to log admin call: {_e}")
        return response


app.add_middleware(AdminAuditLogMiddleware)


# F13 (global soft-mode 2FA): enforce TOTP on every mutating call to
# admin_router. Soft-mode = only enforced when the admin has both
# `is_2fa_enabled=true` AND `two_factor_secret` set. If not, this is a no-op.
# GETs are exempt (viewing data doesn't need a fresh factor). Whitelist covers
# the auth flow itself so an admin can log in and set up 2FA before the gate
# becomes active.
_ADMIN_2FA_WHITELIST_PREFIXES = (
    "/api/auth/",  # login/logout/verify are on api_router, not admin_router
    "/api/security/2fa/",  # 2FA setup/verify endpoints
    "/api/security/passkey/",
    # Support-agent management is a low-risk admin task (adds/removes staff
    # accounts, no financial actions) — do not gate it behind TOTP so the
    # admin can manage the support team from the panel without a fresh 2FA
    # each time. Financial-scope endpoints (withdraw etc) keep the gate.
    "/api/admin/support/",
)

# Explicit exact-path exemptions for POST endpoints that are semantically
# READ-ONLY (they only accept a body because filter/id lists don't fit in a
# query string). Exports never mutate state, so gating them behind a fresh
# TOTP just breaks CSV download flows without adding security value.
_ADMIN_2FA_WHITELIST_EXACT_POSTS = (
    "/api/admin/transactions/export-csv",
    "/api/admin/telegram-bot-stats/export-csv",  # currently GET, kept for parity
)


class Admin2FAGateMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path or ""
        method = request.method
        # Only mutating admin_router calls need the gate.
        if not path.startswith("/api/admin/") or method in ("GET", "HEAD", "OPTIONS"):
            return await call_next(request)
        # Whitelist bypass
        for prefix in _ADMIN_2FA_WHITELIST_PREFIXES:
            if path.startswith(prefix):
                return await call_next(request)
        if path in _ADMIN_2FA_WHITELIST_EXACT_POSTS:
            return await call_next(request)

        # Decode JWT (best-effort) — if there's no valid bearer token the
        # downstream Depends(get_current_user) will reject the request with a
        # proper 401 anyway; we shouldn't preempt that with a confusing error.
        auth = request.headers.get("authorization", "")
        _tok = None
        if auth.lower().startswith("bearer "):
            _tok = auth.split(" ", 1)[1]
        else:
            # F7: also accept the httpOnly cookie session
            _ck = request.cookies.get("access_token")
            if _ck and _ck not in ("null", "undefined", ""):
                _tok = _ck
        if not _tok:
            return await call_next(request)
        try:
            payload = jwt.decode(_tok, SECRET_KEY, algorithms=[ALGORITHM])
        except Exception:
            return await call_next(request)  # bad token → let the route reject

        admin_email = payload.get("sub")
        if not admin_email:
            return await call_next(request)
        admin_doc = await db.users.find_one(
            {"$or": [{"email": admin_email}, {"username": admin_email}]},
            {"_id": 0, "is_admin": 1, "is_2fa_enabled": 1, "two_factor_secret": 1},
        )
        # Soft-mode: only enforce when the account is admin AND has TOTP set up.
        if not admin_doc or not admin_doc.get("is_admin"):
            return await call_next(request)
        if not (admin_doc.get("is_2fa_enabled") and admin_doc.get("two_factor_secret")):
            # F13 hard-mode (opt-in): when ADMIN_2FA_REQUIRED=true, an admin WITHOUT
            # 2FA cannot perform mutating admin actions and is told to enable it first
            # (the enable-2FA endpoint is NOT under /api/admin/, so this never locks
            # them out). Default OFF so a fresh deploy can't accidentally brick admins.
            if os.environ.get("ADMIN_2FA_REQUIRED", "false").strip().lower() in ("1", "true", "yes"):
                return _SAJSONResponse(
                    status_code=403,
                    content={"detail": "Enable 2FA (TOTP) in your profile to perform admin actions."},
                )
            return await call_next(request)

        # TOTP required — verify header.
        totp_code = request.headers.get("X-Admin-TOTP") or request.headers.get("x-admin-totp")
        if not totp_code:
            return _SAJSONResponse(
                status_code=401,
                content={"detail": "TOTP required for this admin action"},
            )
        try:
            import pyotp as _pyotp
            from security.totp_crypto import decrypt_secret as _decrypt_totp
            _totp = _pyotp.TOTP(_decrypt_totp(admin_doc["two_factor_secret"]))
            if not _totp.verify(str(totp_code), valid_window=1):
                return _SAJSONResponse(
                    status_code=401,
                    content={"detail": "Invalid TOTP code"},
                )
        except Exception:
            return _SAJSONResponse(
                status_code=401,
                content={"detail": "Invalid TOTP code"},
            )
        return await call_next(request)


app.add_middleware(Admin2FAGateMiddleware)


# ── F7: set httpOnly session cookie on successful auth responses ───────────
# Centralized so we don't have to edit ~12 token-issuing endpoints. Whenever a
# POST to /api/auth/* returns 200 with a top-level "token", we mirror it into an
# httpOnly `access_token` cookie (+ readable csrf_token). The JSON token stays
# for Bearer/mobile/Telegram fallback.
from starlette.responses import Response as _StarletteResponse
from auth_cookie import set_auth_cookies as _set_auth_cookies, clear_auth_cookies as _clear_auth_cookies, extract_token as _extract_token, CSRF_COOKIE as _CSRF_COOKIE

_AUTH_COOKIE_PATHS = (
    "/api/auth/login", "/api/auth/register", "/api/auth/register/verify",
    "/api/auth/login-verify-email", "/api/auth/login-2fa", "/api/auth/google",
    "/api/auth/google/callback", "/api/auth/telegram-link", "/api/auth/wallet-check",
)


class AuthCookieMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # Fast path: this middleware only touches successful auth POSTs. Do NOT
        # consume `response.body_iterator` on any other path — once the iterator
        # is drained the wrapping middlewares can't stream the body downstream
        # and Starlette raises `RuntimeError("No response returned.")`.
        path = request.url.path or ""
        should_intercept = (
            request.method == "POST"
            and getattr(response, "status_code", 0) == 200
            and any(path == p or path.startswith(p) for p in _AUTH_COOKIE_PATHS)
        )
        if not should_intercept:
            return response

        # From here on we MUST rebuild the response: `body_iterator` is about
        # to be consumed, so returning the original `response` would leave a
        # dead iterator behind (this was the source of the recurring
        # `RuntimeError: No response returned.` on 500s).
        try:
            body = b""
            async for chunk in response.body_iterator:
                body += chunk
        except Exception as _e:
            logger.warning(f"AuthCookieMiddleware: body drain failed for {path}: {_e}")
            # We can't recover a partially-drained iterator; hand back an
            # explicit 500 so the outer middlewares always see a real response
            # (never a "no response" situation).
            return _SAJSONResponse(status_code=500, content={"detail": "internal error"})

        new_resp = _StarletteResponse(
            content=body,
            status_code=response.status_code,
            media_type=response.media_type,
        )
        for k, v in response.headers.items():
            if k.lower() not in ("content-length",):
                new_resp.headers[k] = v
        try:
            data = json.loads(body)
            token = data.get("token") if isinstance(data, dict) else None
            if token and isinstance(token, str):
                _set_auth_cookies(new_resp, token)
        except Exception as _e:
            # Body isn't JSON or lacks `token` — that's fine, just don't set the cookie.
            logger.debug(f"AuthCookieMiddleware: token extraction skipped for {path}: {_e}")
        return new_resp


# ── F16: CSRF double-submit for cookie-authenticated mutating requests ─────
# Rule: mutating (POST/PUT/PATCH/DELETE) /api requests that authenticate via the
# httpOnly cookie AND carry no Authorization header must present a matching
# X-CSRF-Token header (== csrf_token cookie). Bearer-authenticated requests are
# skipped (a browser can't forge the Authorization header cross-site), as are
# the auth endpoints themselves (login/register set the cookie in the first place).
_CSRF_SAFE_METHODS = ("GET", "HEAD", "OPTIONS", "TRACE")
_CSRF_EXEMPT_PREFIXES = (
    "/api/auth/",       # login/register/logout bootstrap the session
    "/api/public/",
    "/api/telegram/",   # Telegram webhook (server-to-server)
    "/api/webhooks/",
)


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        method = request.method.upper()
        path = request.url.path or ""
        if method in _CSRF_SAFE_METHODS or not path.startswith("/api/"):
            return await call_next(request)
        for p in _CSRF_EXEMPT_PREFIXES:
            if path.startswith(p):
                return await call_next(request)
        # If a Bearer header is present, the request is not CSRF-able → allow.
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            return await call_next(request)
        # Cookie-based auth path: require valid double-submit CSRF token.
        cookie_token = request.cookies.get("access_token")
        if cookie_token and cookie_token not in ("null", "undefined", ""):
            csrf_cookie = request.cookies.get(_CSRF_COOKIE)
            csrf_header = request.headers.get("X-CSRF-Token") or request.headers.get("x-csrf-token")
            if not csrf_cookie or not csrf_header or csrf_cookie != csrf_header:
                return _SAJSONResponse(status_code=403, content={"detail": "CSRF token missing or invalid"})
        return await call_next(request)


app.add_middleware(AuthCookieMiddleware)
app.add_middleware(CSRFMiddleware)


# ── Outermost guard: swallow spurious "No response returned." on disconnect ──
# On Python 3.12 + anyio, a stack of BaseHTTPMiddleware can raise
# RuntimeError("No response returned.") when the client (or the CDN/proxy in
# front — e.g. Cloudflare) drops the connection mid-request. The client is
# already gone, so this is harmless, but it floods the logs with giant
# ExceptionGroup tracebacks and looks like the server is crashing. We swallow it
# ONLY when the request is genuinely disconnected; any other RuntimeError is
# re-raised so real bugs still surface as 500s. Registered LAST → outermost.
class ClientDisconnectGuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except RuntimeError as exc:
            if str(exc) == "No response returned.":
                try:
                    disconnected = await request.is_disconnected()
                except Exception:
                    disconnected = True
                if disconnected:
                    # DEBUG (not INFO): this is a benign, high-frequency event
                    # (users closing tabs, mobile networks, Cloudflare timeouts).
                    # The client is already gone and the request handled fine —
                    # keep it out of the normal INFO log to avoid noise, but keep
                    # it available when explicitly debugging at DEBUG level.
                    logger.debug(
                        "Client disconnected mid-request (suppressed 'No response returned')",
                        extra={"path": str(request.url.path), "method": request.method},
                    )
                    return _StarletteResponse(status_code=204)
            raise


app.add_middleware(ClientDisconnectGuardMiddleware)


# F33: global exception handler — hide stack traces from clients while still
# logging them server-side. HTTPException is handled by FastAPI natively and
# preserves its own detail message; anything else becomes a generic 500.
@app.exception_handler(Exception)
async def _generic_exception_handler(request: Request, exc: Exception):
    # IMPORTANT: never `raise` from inside an exception handler. Under Python
    # 3.12 + anyio, re-raising here propagates back through the BaseHTTPMiddleware
    # stack (AuthCookie/CSRF/Admin2FA/…) as an ExceptionGroup, which corrupts the
    # response iterator and surfaces a misleading `RuntimeError: No response
    # returned`. Instead we always return a valid Response.
    from fastapi import HTTPException as _HTTPException
    from starlette.exceptions import HTTPException as _SHTTPException
    if isinstance(exc, (_HTTPException, _SHTTPException)):
        # Preserve the original status code / detail / headers of the HTTPException.
        detail = getattr(exc, "detail", None)
        if detail is None:
            detail = "error"
        return _SAJSONResponse(
            status_code=exc.status_code,
            content={"detail": detail},
            headers=getattr(exc, "headers", None) or None,
        )
    logger.exception(
        "Unhandled exception",
        extra={"path": str(request.url.path), "method": request.method},
    )
    return _SAJSONResponse(
        status_code=500,
        content={"detail": "internal error"},
    )

async def _migrate_dedupe_plots() -> dict:
    """One-shot migration to remove duplicate owned plots at the same (island, x, y).

    Caused by a historic race in `/api/island/buy/{x}/{y}` where two simultaneous
    POSTs could both pass the "already owned?" check and both insert a plot doc.
    Strategy: keep the earliest by `purchased_at`, then for every later duplicate:
      • refund `price_ton` to its owner's `balance_ton`
      • delete the associated business doc (if any)
      • delete the duplicate plot
    Returns counters for logging. Idempotent — safe to call on every startup.
    """
    pipeline = [
        {"$match": {"owner": {"$type": "string"}, "island_id": {"$ne": None}}},
        {"$group": {
            "_id": {"island_id": "$island_id", "x": "$x", "y": "$y"},
            "docs": {"$push": {
                "id": "$id", "owner": "$owner", "purchased_at": "$purchased_at",
                "business_id": "$business_id", "price_ton": "$price_ton",
            }},
            "count": {"$sum": 1},
        }},
        {"$match": {"count": {"$gt": 1}}},
    ]
    refunded = 0
    plots_deleted = 0
    businesses_deleted = 0
    async for group in db.plots.aggregate(pipeline):
        docs = sorted(
            group["docs"],
            key=lambda d: d.get("purchased_at") or "",
        )
        # Keep first (earliest); drop the rest.
        keep, drops = docs[0], docs[1:]
        for d in drops:
            price = float(d.get("price_ton") or 0)
            if price > 0 and d.get("owner"):
                owner_keys = await resolve_owner_keys(db, d["owner"])
                u = await db.users.find_one(
                    {"$or": [{"id": k} for k in owner_keys]
                            + [{"email": k} for k in owner_keys]
                            + [{"wallet_address": k} for k in owner_keys]},
                    {"_id": 1},
                )
                if u:
                    await db.users.update_one({"_id": u["_id"]}, {"$inc": {"balance_ton": price}})
                    refunded += 1
            if d.get("business_id"):
                r = await db.businesses.delete_one({"id": d["business_id"]})
                businesses_deleted += r.deleted_count
            r2 = await db.plots.delete_one({"id": d["id"]})
            plots_deleted += r2.deleted_count
        logger.warning(
            "[plot-dedupe] kept %s at (%s,%s,%s); dropped %s duplicates",
            keep.get("id"), group["_id"].get("island_id"),
            group["_id"].get("x"), group["_id"].get("y"), len(drops),
        )
    if plots_deleted or businesses_deleted or refunded:
        logger.warning(
            "[plot-dedupe] migration done: %s duplicate plots removed, %s businesses cleared, %s refunds",
            plots_deleted, businesses_deleted, refunded,
        )
    return {"plots_deleted": plots_deleted, "businesses_deleted": businesses_deleted, "refunded": refunded}


@app.on_event("startup")
async def startup_event():
    """Initialize services on startup"""
    logger.info("🚀 Starting GRAM City Builder API...")

    # Email delivery config diagnostics (secret-free). Surfaces the #1 prod
    # email failure — an unverified SENDER_EMAIL domain — directly in the boot
    # logs so it can be spotted without triggering a real password reset.
    try:
        from email_service import email_startup_diagnostics
        email_startup_diagnostics()
    except Exception as _e:
        logger.warning(f"email diagnostics failed: {_e}")

    # S3: initialize MongoDB-backed brute-force lockout store + indexes
    init_lockout_store(db)

    # Business skins: ensure indexes + seed default (standard + crazy) bio_farm skins
    try:
        await seed_default_skins(db)
    except Exception as _e:
        logger.warning(f"seed_default_skins failed: {_e}")

    # F12: TTL index on admin_audit_log — auto-expire entries after 90 days
    # so the collection can't grow unbounded.
    try:
        await db.admin_audit_log.create_index("timestamp", expireAfterSeconds=60 * 60 * 24 * 90)
    except Exception as _e:
        logger.warning(f"admin_audit_log TTL index setup: {_e}")

    # Telegram lookup indexes — WITHOUT these, every bot click/message does a
    # full collection scan on users / telegram_mappings, which at ~20k users
    # blocks handlers for 10-14s and causes "Answer callback error". Idempotent.
    try:
        await db.telegram_mappings.create_index("chat_id")
        await db.users.create_index("telegram_chat_id")
        logger.info("✅ Telegram lookup indexes ensured")
    except Exception as _e:
        logger.warning(f"telegram index setup: {_e}")

    # Security (Part 4): atomic "1 wallet → 1 account" guarantee. A partial
    # UNIQUE index on raw_address (only for string values, so many null/absent
    # rows are allowed) makes it impossible to bind the same wallet to two
    # accounts even under a race — the second insert/update fails at the DB.
    try:
        await db.users.create_index(
            "raw_address",
            unique=True,
            partialFilterExpression={"raw_address": {"$type": "string"}},
            name="uniq_wallet_raw_address",
        )
        logger.info("✅ Users: unique index on raw_address is active")
    except Exception as _e:
        logger.warning(f"raw_address unique index setup: {_e}")
    
    # Initialize TON client
    try:
        await init_ton_client()
        logger.info("✅ TON Mainnet client initialized")
    except Exception as e:
        logger.error(f"❌ Failed to initialize TON client: {e}")
    
    # Initialize and start scheduler — ONLY ON THE LEADER WORKER.
    # gunicorn -w N spawns N processes; without leader election every worker
    # ran the scheduler independently and produced N duplicate side-effects
    # (4× low-resource Telegram notifications, 4× tender clearings, etc.).
    # `start_leader_loop` polls a Mongo lock; the winner runs the scheduler,
    # losers wait until the leader dies or yields.
    async def _start_scheduler_on_lead():
        try:
            init_scheduler()
            start_scheduler()
            try:
                from background_tasks import scheduler as _bgsched
                from apscheduler.triggers.interval import IntervalTrigger as _IT
                if _bgsched:
                    _bgsched.add_job(auto_reclaim_inactive_chats, _IT(minutes=5), id="support_auto_reclaim", replace_existing=True)

                    async def _city_market_cycle():
                        try:
                            await market_maker.run_cycle(db, _admin_buyout_apply_sale)
                        except Exception as _mme:
                            logger.warning(f"city market cycle failed: {_mme}")
                    _bgsched.add_job(_city_market_cycle, _IT(minutes=5), id="city_market_cycle",
                                     replace_existing=True, coalesce=True, max_instances=1)

                    async def _league_finalize():
                        try:
                            await leagues.finalize_due(db)
                        except Exception as _le:
                            logger.warning(f"league finalize failed: {_le}")
                    async def _ensure_new_city_map():
                        try:
                            from city_switch import ensure_new_city_map
                            await ensure_new_city_map(db, wait=False)
                        except Exception as _me:
                            logger.error(f"new city map migration failed: {_me}")
                    asyncio.create_task(_ensure_new_city_map())

                    async def _normalize_owners():
                        """owner / seller references stored as wallet or e-mail -> user id (once, idempotent)"""
                        try:
                            from scripts import normalize_owner_ids as _no
                            await _no.run(True, db)
                        except Exception as _ne:
                            logger.warning(f"owner id normalization skipped: {_ne}")
                    asyncio.create_task(_normalize_owners())

                    async def _minigame_finalize():
                        try:
                            import minigames as _mg
                            await _mg.finalize(db)
                        except Exception as _mge:
                            logger.warning(f"minigame finalize failed: {_mge}")
                    _bgsched.add_job(_minigame_finalize, _IT(minutes=10), id="minigame_finalize", replace_existing=True)

                    async def _minigame_rewards_setup():
                        try:
                            import minigame_rewards as _mr
                            await _mr.ensure_indexes(db)
                            made = await _mr.seed_defaults(db)
                            if any(made.values()):
                                logger.info(f"minigame rewards: starting set created {made}")
                        except Exception as _mse:
                            logger.warning(f"minigame rewards setup failed: {_mse}")
                    asyncio.create_task(_minigame_rewards_setup())

                    async def _minigame_boosters_expire():
                        try:
                            import minigame_rewards as _mr
                            await _mr.expire_boosters(db)
                        except Exception as _mbe:
                            logger.warning(f"minigame boosters expiry failed: {_mbe}")
                    _bgsched.add_job(_minigame_boosters_expire, _IT(minutes=10), id="minigame_boosters_expire", replace_existing=True)

                    async def _minigame_nft_queue():
                        try:
                            import minigame_rewards as _mr
                            r = await _mr.process_nft_queue(db)
                            if any(r.values()):
                                logger.info(f"minigame NFT queue: {r}")
                        except Exception as _mne:
                            logger.warning(f"minigame NFT queue failed: {_mne}")
                    _bgsched.add_job(_minigame_nft_queue, _IT(minutes=5), id="minigame_nft_queue", replace_existing=True)

                    async def _rental_settle():
                        try:
                            import rental as _r
                            await _r.settle(db)
                        except Exception as _re:
                            logger.warning(f"rental settle failed: {_re}")
                    _bgsched.add_job(_rental_settle, _IT(minutes=15), id="rental_settle", replace_existing=True)
                    _bgsched.add_job(_league_finalize, _IT(minutes=10), id="league_finalize",
                                     replace_existing=True, coalesce=True, max_instances=1)

                    async def _reconciliation_daily():
                        try:
                            await reconciliation.daily_check(db)
                        except Exception as _re:
                            logger.warning(f"reconciliation daily check failed: {_re}")
                    _bgsched.add_job(_reconciliation_daily, _IT(hours=24), id="reconciliation_daily",
                                     replace_existing=True, coalesce=True, max_instances=1)
                    _bgsched.add_job(auto_close_user_inactive_chats, _IT(minutes=5), id="support_auto_close_user_inactive", replace_existing=True)
                    logger.info("✅ Support auto-reclaim job scheduled (every 5 min)")
                    logger.info("✅ Support auto-close-user-inactive job scheduled (every 5 min, threshold 20 min)")

                    # Trash piles: refill every 4h48m. `next_run_time=now` triggers
                    # an immediate first run so the map has piles from the moment
                    # the leader takes over (or on cold start).
                    async def _trash_tick():
                        try:
                            await _refill_trash_piles(db)
                        except Exception as _e:
                            logger.warning(f"trash-spawn tick failed: {_e}")
                    from datetime import datetime as _dt, timezone as _tz
                    _bgsched.add_job(
                        _trash_tick,
                        _IT(hours=4, minutes=48),
                        id="trash_spawn",
                        replace_existing=True,
                        next_run_time=_dt.now(_tz.utc),
                        misfire_grace_time=3600,
                        coalesce=True,
                        jitter=1080,
                    )
                    logger.info("✅ Trash-pile spawn job scheduled (every 4h48m ±18m jitter, first run: now)")

                    # Repost-story tasks: auto-credit the reward once the 23h
                    # timer elapses — fully server-side, even if the user never
                    # reopens the app.
                    async def _story_autocredit_tick():
                        try:
                            from routes.tasks import process_expired_story_tasks
                            n = await process_expired_story_tasks(db)
                            if n:
                                logger.info(f"repost-story auto-credit: {n} task(s) rewarded")
                        except Exception as _e:
                            logger.warning(f"repost-story auto-credit tick failed: {_e}")
                    _bgsched.add_job(
                        _story_autocredit_tick,
                        _IT(minutes=5),
                        id="repost_story_autocredit",
                        replace_existing=True,
                        next_run_time=_dt.now(_tz.utc),
                        coalesce=True,
                        misfire_grace_time=300,
                    )
                    logger.info("✅ Repost-story auto-credit job scheduled (every 1 min)")
            except Exception as _e:
                logger.warning(f"Could not schedule support auto-reclaim: {_e}")
            try:
                removed = await cleanup_empty_chats()
                if removed:
                    logger.info(f"✅ Cleaned up {removed} empty support chats on startup")
            except Exception as _e:
                logger.warning(f"Could not cleanup empty support chats: {_e}")
            logger.info("✅ Background task scheduler started (leader)")
        except Exception as e:
            logger.error(f"❌ Failed to start scheduler: {e}")

    def _stop_scheduler_on_lose():
        try:
            shutdown_scheduler()
            logger.info("⏸ Background task scheduler stopped (leader lost)")
        except Exception as e:
            logger.error(f"❌ Failed to stop scheduler: {e}")

    try:
        _start_leader_loop(db, _start_scheduler_on_lead, _stop_scheduler_on_lose)
        logger.info("✅ Scheduler leader-election loop started")
    except Exception as e:
        logger.error(f"❌ Failed to start scheduler leader loop: {e}")
    
    # Initialize payment monitor
    try:
        await init_payment_monitor(db)
        logger.info("✅ TON Payment Monitor started")
    except Exception as e:
        logger.error(f"❌ Failed to start payment monitor: {e}")

    # Anti-fraud: TTL index на fingerprints (auto-delete после 30 дней)
    try:
        from antifraud import ensure_ttl_index
        await ensure_ttl_index(db, ttl_days=30)
    except Exception as e:
        logger.error(f"❌ Failed to create antifraud TTL index: {e}")

    # Mnemonic encryption: migrate legacy plaintext → Fernet-encrypted
    try:
        from mnemonic_crypto import migrate_plaintext_to_encrypted
        stats = await migrate_plaintext_to_encrypted(db)
        if stats.get("status") == "done":
            logger.info(
                "✅ Mnemonic encryption migration: %s admin_settings, %s admin_wallets",
                stats.get("admin_settings", 0), stats.get("admin_wallets", 0)
            )
        elif stats.get("status") == "skipped":
            logger.info("ℹ Mnemonic encryption skipped: %s", stats.get("reason"))
    except Exception as e:
        logger.error(f"❌ Mnemonic encryption migration failed: {e}")

    # Plot uniqueness — guard against race-condition double-purchases
    # (two users buying the same (island, x, y) at the same instant).
    try:
        await _migrate_dedupe_plots()
        await db.plots.create_index(
            [("island_id", 1), ("x", 1), ("y", 1)],
            unique=True,
            partialFilterExpression={"owner": {"$type": "string"}},
            name="uniq_island_xy_owned",
        )
        logger.info("✅ Plots: unique index on (island_id, x, y) for owned plots is active")
    except Exception as e:
        logger.error(f"❌ Failed to create plot unique index: {e}")

    # One-time migration: existing Google users have `avatar_uploaded=True`
    # because the old signup code set that flag for ANY Google picture. That
    # flag was supposed to mean "user manually uploaded a custom photo" and
    # is now correctly named `custom_avatar_uploaded`. We backfill the new
    # field as False for Google users so their picture refreshes on next
    # login, and True for non-Google users who had genuinely uploaded.
    try:
        # Google users: was True only because of the bug → mark as NOT
        # custom-uploaded so future Google logins refresh the avatar.
        await db.users.update_many(
            {
                "google_id": {"$exists": True, "$ne": None},
                "custom_avatar_uploaded": {"$exists": False},
            },
            {"$set": {"custom_avatar_uploaded": False}},
        )
        # Non-Google users with avatar_uploaded=True → they used the explicit
        # /upload-avatar endpoint, so preserve that.
        await db.users.update_many(
            {
                "google_id": {"$in": [None]},
                "avatar_uploaded": True,
                "custom_avatar_uploaded": {"$exists": False},
            },
            {"$set": {"custom_avatar_uploaded": True}},
        )
        logger.info("✅ Avatar flag migration: custom_avatar_uploaded backfilled")
    except Exception as e:
        logger.error(f"❌ Avatar flag migration failed: {e}")

    # ── One-time backfill: telegram_mappings.first_activity_at ────────────
    # Legacy rows (created before this feature) don't have first_activity_at,
    # which made the admin TG-bot stats show first==last activity because the
    # endpoint fell back to updated_at. Backfill from updated_at once so the
    # UI shows a stable "first activity" from the moment we have data for.
    try:
        res = await db.telegram_mappings.update_many(
            {"first_activity_at": {"$exists": False}},
            [{"$set": {"first_activity_at": {"$ifNull": ["$updated_at", None]}}}],
        )
        if getattr(res, "modified_count", 0):
            logger.info(f"✅ telegram_mappings backfill: first_activity_at set on {res.modified_count} rows")
    except Exception as e:
        logger.error(f"❌ telegram_mappings first_activity_at backfill failed: {e}")

    # Test-user auto-seeding has been removed. Test accounts are never created
    # automatically on startup. Use `python -m scripts.seed_test_users` manually
    # if you need the QA accounts in a dev/preview environment.

    # ── Разовая починка при старте: вернуть в работу арендованные бизнесы ──
    # 0-го уровня, которые были ошибочно изъяты/остановлены (старым джобом
    # неактивности), но срок их 3-дневной аренды ещё не истёк. Снимает флаги
    # изъятия с бизнеса и его листинга и снова запускает производство.
    try:
        from zero_lease import restore_wrongly_seized_zero_leases
        _restored = await restore_wrongly_seized_zero_leases(db)
        if _restored:
            logger.info(f"✅ Восстановлено арендованных бизнесов 0-го уровня: {_restored}")
    except Exception as e:
        logger.error(f"❌ Восстановление арендованных бизнесов 0-го уровня не удалось: {e}")

    # ── Разовый бэкфилл 3-дневной аренды для бизнесов 0-го уровня, ──────────
    # купленных ДО введения аренды (у них нет expires_at, поэтому в «Мои
    # бизнесы» не показывался таймер). Проставляем срок аренды ОТ ТЕКУЩЕГО
    # момента (now + 3 дня) ТОЛЬКО тем, у кого expires_at отсутствует/пуст.
    # Операция идемпотентна: раз выставленный expires_at больше не трогается,
    # поэтому при каждом новом деплое аренда НЕ продлевается заново.
    try:
        from zero_lease import compute_expires_at
        _now_iso = datetime.now(timezone.utc).isoformat()
        _exp_iso = compute_expires_at()
        _backfilled = 0
        _cur = db.businesses.find({
            "level": 0,
            "is_zero_business": True,
            "is_trial": {"$ne": True},
            "$or": [{"expires_at": {"$exists": False}}, {"expires_at": None}],
        }, {"_id": 0, "id": 1, "plot_id": 1})
        async for _b in _cur:
            _bid = _b.get("id")
            if not _bid:
                continue
            await db.businesses.update_one(
                {"id": _bid, "$or": [{"expires_at": {"$exists": False}}, {"expires_at": None}]},
                {"$set": {"expires_at": _exp_iso, "zero_lease_backfilled_at": _now_iso}},
            )
            # Держим встроенную в участок копию бизнеса в согласованном виде.
            if _b.get("plot_id"):
                await db.plots.update_one(
                    {"id": _b["plot_id"]}, {"$set": {"business.expires_at": _exp_iso}}
                )
            else:
                await db.plots.update_many(
                    {"business_id": _bid}, {"$set": {"business.expires_at": _exp_iso}}
                )
            _backfilled += 1
        if _backfilled:
            logger.info(f"✅ Бэкфилл аренды 0-го уровня: expires_at проставлен {_backfilled} бизнесам (до {_exp_iso})")
    except Exception as e:
        logger.error(f"❌ Бэкфилл аренды для бизнесов 0-го уровня не удался: {e}")

    # ── Чистка устаревших флагов «изъятия» с листингов бизнесов 0-го уровня. ─
    # Арендованные бизнесы никогда не должны быть «изъятыми»: старый джоб
    # неактивности мог пометить их is_seized — снимаем эти флаги, чтобы они не
    # висели в админке и корректно обрабатывались при выкупе.
    try:
        _res = await db.land_listings.update_many(
            {"is_zero_business": True, "is_seized": True},
            {"$unset": {"is_seized": "", "seizure_reason": "",
                        "former_owner_id": "", "former_level": ""}},
        )
        if getattr(_res, "modified_count", 0):
            logger.info(f"✅ Снят флаг is_seized с {_res.modified_count} листингов бизнесов 0-го уровня")
    except Exception as e:
        logger.error(f"❌ Чистка флагов изъятия с листингов 0-го уровня не удалась: {e}")

    # Повторное восстановление после бэкфилла: теперь у ранее изъятых бизнесов
    # 0-го уровня есть expires_at, поэтому restore-джоб сможет вернуть их в работу.
    try:
        from zero_lease import restore_wrongly_seized_zero_leases as _restore2
        _r2 = await _restore2(db)
        if _r2:
            logger.info(f"✅ Повторно восстановлено арендованных бизнесов 0-го уровня после бэкфилла: {_r2}")
    except Exception as e:
        logger.error(f"❌ Повторное восстановление бизнесов 0-го уровня не удалось: {e}")



@app.on_event("shutdown")
async def shutdown_db_client():
    """Cleanup on shutdown"""
    logger.info("🛑 Shutting down GRAM City Builder API...")
    
    # Stop payment monitor
    try:
        await stop_payment_monitor()
        logger.info("✅ Payment monitor stopped")
    except Exception as e:
        logger.error(f"❌ Error stopping payment monitor: {e}")
    
    # Close TON client
    try:
        await close_ton_client()
        logger.info("✅ TON client closed")
    except Exception as e:
        logger.error(f"❌ Error closing TON client: {e}")
    
    # Shutdown scheduler
    try:
        shutdown_scheduler()
        logger.info("✅ Scheduler stopped")
    except Exception as e:
        logger.error(f"❌ Error stopping scheduler: {e}")

    # Release the leader lock so the next-restarting worker grabs it instantly
    try:
        await _shutdown_leader()
    except Exception as e:
        logger.error(f"❌ Error releasing scheduler-leader lock: {e}")
    
    # Close MongoDB
    client.close()
    logger.info("✅ MongoDB connection closed")
