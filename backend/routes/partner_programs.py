"""
B2B Partner Programs — INCOMING verification (direction B).
===========================================================
We are the target project. A partner brings their users to OUR game via THEIR
own referral link (an in-game ref link `?ref=<user_id>`). The admin registers a
program by pasting that ref link and configuring the conditions a referred user
must meet INSIDE our game:

  • bought land (fact of a land purchase),
  • spent >= N $CITY on the marketplace,
  • (always) came in via the partner's referral link (attribution).

The admin receives ONE unique **verification URL** to hand to the partner:
    {BACKEND}/api/partner/verify/{api_key}?user_id=<our user id>
The partner's server calls it; HTTP 200 == all conditions met, otherwise 402.

Every call is logged (partner_verify_logs) and shown in an admin "Логи" modal.

Point 5 (handled in server.py / promo_service.py): a ref link that becomes a
partner link no longer earns the normal referral cut (5% on referral income) nor
the Referral-Rally activation bonus (1.5 TON). Instead the partner earns exactly
what the admin configured:
  • per_active_user_city — credited once when a user first passes verification,
  • income_percent       — % of the referred user's marketplace income.
"""
import uuid
import secrets
import logging
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse, parse_qs, parse_qsl, urlencode, urlunparse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
import csv
import io

logger = logging.getLogger(__name__)

_LAND_TX_MATCH = {
    "$or": [
        {"type": "land_purchase"},                                  # map buy (history record)
        {"tx_type": {"$in": ["purchase_plot", "land_purchase", "resale_plot"]}},  # map + marketplace/resale
    ]
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _created_at_range(date_from: Optional[str], date_to: Optional[str]) -> Optional[dict]:
    """Build a Mongo range filter on the ISO `created_at` string field.
    `date_from`/`date_to` are YYYY-MM-DD (inclusive). Returns None when both empty."""
    rng = {}
    df = (date_from or "").strip()
    dt = (date_to or "").strip()
    if df:
        rng["$gte"] = df[:10] + "T00:00:00"
    if dt:
        rng["$lte"] = dt[:10] + "T23:59:59.999999"
    return rng or None


def parse_ref_user_id(ref_link: str) -> Optional[str]:
    """Extract the referrer user id from a pasted in-game ref link.
    Accepts `https://site/?ref=<id>`, `?ref=<id>`, `.../ref/<id>`, or a raw id."""
    if not ref_link:
        return None
    s = str(ref_link).strip()
    try:
        parsed = urlparse(s if "://" in s else f"http://x/{s.lstrip('/')}")
        qs = parse_qs(parsed.query or "")
        for key in ("ref", "ref_code", "start", "startapp", "r"):
            if key in qs and qs[key]:
                val = qs[key][0].strip()
                if val.startswith("p_"):
                    val = val[2:]
                return val or None
        # path form .../ref/<id>
        parts = [p for p in (parsed.path or "").split("/") if p]
        if len(parts) >= 2 and parts[-2] == "ref":
            return parts[-1]
    except Exception:
        pass
    # raw token (no url, no query)
    if s and "/" not in s and "?" not in s and " " not in s:
        return s[2:] if s.startswith("p_") else s
    return None


# Every field a user document may use to record who referred them. Centralised
# so attribution (verify), audience metrics and reward checks all agree instead
# of each reading a different single field (the old code only read `referrerId`).
REFERRER_FIELDS = (
    "partner_ref_id", "referrer_id", "ref_by", "invited_by",
    "referrerId", "referrer", "start_param", "startParam",
)


def user_referrer_ids(user: Optional[dict]) -> set:
    """Collect every referrer id recorded on a user document, normalised the
    same way pasted ref-links / start_param values are (strips ?ref= / startapp=
    wrappers and a leading `p_`). Returns a set of candidate referrer user ids."""
    ids: set = set()
    if not user:
        return ids
    for f in REFERRER_FIELDS:
        v = user.get(f)
        if v in (None, ""):
            continue
        s = str(v).strip()
        if not s:
            continue
        ids.add(s)
        parsed = parse_ref_user_id(s)  # handles "p_<id>", "?startapp=<id>", etc.
        if parsed:
            ids.add(parsed)
    return ids


def build_tma_ref_url(web_ref_url: str, tma_base_url: str):
    """Turn a web referral link + a Telegram Mini App base link into a direct
    TMA referral link.

    Extracts the referral id from `web_ref_url` (?ref= / ?startapp= / ?start= …)
    and returns `(ref_id, "<tma_base>?startapp=<ref_id>")`.

    Works even when `web_ref_url` is ALREADY a Telegram Mini App link
    (e.g. https://t.me/Bot/app?startapp=<id>) — the id is read from startapp.
    Raises ValueError with a human message on invalid input.
    """
    ref_id = parse_ref_user_id(web_ref_url)
    if not ref_id:
        raise ValueError("Параметр ?ref= (или startapp) не найден в веб-ссылке")

    base = (tma_base_url or "").strip()
    if not base:
        raise ValueError("Укажите базовую ссылку Telegram Mini App")
    if "://" not in base:
        base = "https://" + base
    parsed = urlparse(base)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Некорректная базовая ссылка Telegram Mini App")

    # Preserve any existing query params on the base, but (re)set startapp.
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["startapp"] = ref_id
    new_query = urlencode(query)
    # Drop a trailing slash on the path so we don't get "/app/?startapp=".
    path = parsed.path[:-1] if parsed.path.endswith("/") and len(parsed.path) > 1 else parsed.path
    tma_ref_url = urlunparse((parsed.scheme, parsed.netloc, path, "", new_query, ""))
    return ref_id, tma_ref_url


async def resolve_user(db, user_id: str) -> Optional[dict]:
    if not user_id:
        return None
    doc = await db.users.find_one({"id": str(user_id)}, {"_id": 0})
    if doc:
        return doc
    for k in ("telegram_id", "telegram_user_id", "telegram_chat_id"):
        doc = await db.users.find_one({k: str(user_id)}, {"_id": 0})
        if doc:
            return doc
    return None


async def market_spend_city(db, uid: str, since: Optional[str] = None) -> float:
    """Total $CITY the user has spent on the marketplace (market_purchase).

    When `since` (an ISO `created_at` timestamp) is given, ONLY purchases made
    at/after that moment count — used so a user's spending BEFORE they joined
    via the partner does not satisfy the partner task."""
    match = {"tx_type": "market_purchase",
             "$or": [{"buyer_id": uid}, {"from_address": uid}]}
    if since:
        match["created_at"] = {"$gte": since}
    pipeline = [
        {"$match": match},
        {"$group": {"_id": None, "ton": {"$sum": {"$ifNull": ["$amount_ton", "$amount"]}}}},
    ]
    agg = await db.transactions.aggregate(pipeline).to_list(1)
    ton = float(agg[0]["ton"]) if agg else 0.0
    return round(ton * 1000.0, 2)  # $CITY = TON * 1000


async def land_purchase_count(db, uid: str, since: Optional[str] = None) -> int:
    """Number of REAL land-purchase events by the user (fact of purchase) from
    the MAP or the MARKETPLACE. Trial-center 'businesses' are NOT land purchases
    and are explicitly excluded.

    When `since` (an ISO `created_at` timestamp) is given, ONLY purchases made
    at/after that moment count — so land bought BEFORE the user joined via the
    partner does not satisfy the partner task."""
    and_conds = [
        _LAND_TX_MATCH,
        {"$or": [{"user_id": uid}, {"buyer_id": uid}, {"from_address": uid}]},
        {"is_trial": {"$ne": True}},
        {"business_type": {"$ne": "trial_center"}},
    ]
    if since:
        and_conds.append({"created_at": {"$gte": since}})
    q = {"$and": and_conds}
    try:
        return await db.transactions.count_documents(q)
    except Exception:
        return 0


async def business_upgrade_count(db, uid: str, to_level: int, since: Optional[str] = None) -> int:
    """Number of successful business upgrades by the user that REACHED
    `to_level` (i.e. the from_level → to_level transition, since upgrades move
    one level at a time). Read from the `business_upgrade` transaction records
    written by /business/{id}/upgrade.

    When `since` is given, only upgrades made at/after that moment count — so a
    user's pre-existing upgrades (before they joined via the partner) don't
    satisfy the task."""
    q = {"type": "business_upgrade",
         "user_id": str(uid),
         "details.new_level": int(to_level)}
    if since:
        q["created_at"] = {"$gte": since}
    try:
        return await db.transactions.count_documents(q)
    except Exception:
        return 0


async def is_partner_referrer(db, referrer_id: str) -> Optional[dict]:
    """Return the active partner program owned by this referrer (or None).
    Used to suppress the normal referral rewards for partner links."""
    if not referrer_id:
        return None
    return await db.partner_programs.find_one(
        {"referrer_user_id": str(referrer_id), "active": {"$ne": False}}, {"_id": 0}
    )


def _referred_users_filter(referrer_id: str) -> dict:
    """Match every user who joined via this referrer, honouring the new
    `partner_ref_id` binding as well as the legacy `referrerId` field and the
    other referral aliases stored on the user doc."""
    rid = str(referrer_id)
    return {"$or": [{f: rid} for f in
                    ("partner_ref_id", "referrer_id", "ref_by",
                     "invited_by", "referrerId")]}


async def partner_metrics(db, referrer_id: str) -> dict:
    """Live per-partner audience metrics computed from the users collection so
    the numbers can never drift:
      unique_users — distinct users bound to the partner (new OR existing)
      new_users    — of those, the ones who were NEW (registered via the link)
      completed    — of those, the ones who completed ALL conditions
    (Raw link 'clicks' are a separate stored counter on the program doc.)
    """
    if not referrer_id:
        return {"unique_users": 0, "new_users": 0, "completed": 0}
    flt = _referred_users_filter(referrer_id)
    unique = await db.users.count_documents(flt)
    new_users = await db.users.count_documents({"$and": [flt, {"partner_is_new": True}]})
    completed = await db.users.count_documents({"$and": [flt, {"partner_task_completed": True}]})
    return {"unique_users": unique, "new_users": new_users, "completed": completed}


async def check_partner_conditions(db, user_id: str) -> bool:
    """Evaluate a referred user's progress against their partner program's
    conditions. Flips `partner_task_completed` to True (once) and bumps the
    program's stored `completed_count` when ALL conditions are met.

    Conditions (from the program):
      • require_land       → user made >= 1 land/business purchase
      • min_market_spend_city → user spent >= N $CITY on the P2P marketplace

    Safe to call on every relevant game action — idempotent, never raises.
    Returns True when the user is (now or already) fully completed.
    """
    try:
        user = await db.users.find_one({"id": str(user_id)}, {"_id": 0})
        if not user:
            return False
        rid = (user.get("partner_ref_id") or user.get("referrer_id")
               or user.get("ref_by") or user.get("invited_by")
               or user.get("referrerId"))
        if not rid:
            return False
        program = await db.partner_programs.find_one(
            {"referrer_user_id": str(rid), "active": {"$ne": False}}, {"_id": 0})
        if not program:
            return False

        set_fields = {}
        # Backfill the new binding fields for legacy users. The join moment is
        # the CUTOFF: only land/spend AFTER it count. If missing, the user is
        # joining now → their pre-existing land/spend must not count, so we
        # anchor the cutoff to NOW (not their original created_at).
        if not user.get("partner_ref_id"):
            set_fields["partner_ref_id"] = str(rid)
        joined = user.get("partner_joined_at")
        if not joined:
            joined = _now_iso()
            set_fields["partner_joined_at"] = joined

        land = await land_purchase_count(db, str(user_id), since=joined)
        spent = await market_spend_city(db, str(user_id), since=joined)
        need = float(program.get("min_market_spend_city") or 0)
        land_ok = (not program.get("require_land", True)) or land >= 1
        market_ok = spent >= need
        # business_upgrade task: user must upgrade a business to `upgrade_to_level`
        # (from_level → to_level; default 0 → 1). One-shot, reuses the same
        # completion tracking as the land/market conditions.
        require_upgrade = bool(program.get("require_business_upgrade"))
        to_level = int(program.get("upgrade_to_level", 1) or 1)
        upg = await business_upgrade_count(db, str(user_id), to_level, since=joined) if require_upgrade else 0
        upgrade_ok = (not require_upgrade) or upg >= 1
        already = bool(user.get("partner_task_completed"))

        if land_ok and market_ok and upgrade_ok and not already:
            set_fields["partner_task_completed"] = True
        if set_fields:
            await db.users.update_one({"id": str(user_id)}, {"$set": set_fields})
        return (land_ok and market_ok and upgrade_ok) or already
    except Exception as e:
        logger.debug(f"check_partner_conditions failed for {user_id}: {e}")
        return False


# ── Request models ───────────────────────────────────────────────────────────
class ProgramCreate(BaseModel):
    name: str
    ref_link: str
    require_land: bool = True
    min_market_spend_city: float = Field(0, ge=0)
    per_active_user_city: float = Field(0, ge=0)
    income_percent: float = Field(0, ge=0, le=100)
    tma_base_url: Optional[str] = None
    require_business_upgrade: bool = False
    upgrade_from_level: int = Field(0, ge=0)
    upgrade_to_level: int = Field(1, ge=1)


class ProgramUpdate(BaseModel):
    name: Optional[str] = None
    ref_link: Optional[str] = None
    require_land: Optional[bool] = None
    min_market_spend_city: Optional[float] = None
    per_active_user_city: Optional[float] = None
    income_percent: Optional[float] = None
    active: Optional[bool] = None
    tma_base_url: Optional[str] = None
    require_business_upgrade: Optional[bool] = None
    upgrade_from_level: Optional[int] = None
    upgrade_to_level: Optional[int] = None


class TmaLinkRequest(BaseModel):
    web_ref_url: str
    tma_base_url: str


class TmaLinkSaveRequest(BaseModel):
    tma_base_url: str


def _public_program(p: dict, backend_url: str) -> dict:
    api_key = p["api_key"]
    verify_path = f"/api/partner/verify/{api_key}?user_id=USER_ID"
    base = (backend_url or "").rstrip("/")
    return {
        "id": p["id"],
        "name": p.get("name"),
        "api_key": api_key,
        "ref_link": p.get("ref_link"),
        "referrer_user_id": p.get("referrer_user_id"),
        "require_land": p.get("require_land", True),
        "min_market_spend_city": p.get("min_market_spend_city", 0),
        "require_business_upgrade": bool(p.get("require_business_upgrade", False)),
        "upgrade_from_level": int(p.get("upgrade_from_level", 0) or 0),
        "upgrade_to_level": int(p.get("upgrade_to_level", 1) or 1),
        "per_active_user_city": p.get("per_active_user_city", 0),
        "income_percent": p.get("income_percent", 0),
        "active": p.get("active", True),
        "created_at": p.get("created_at"),
        "tma_base_url": p.get("tma_base_url"),
        "tma_ref_url": p.get("tma_ref_url"),
        # Partner audience metrics:
        #   clicks_count    — raw link opens (stored, incremented on every open)
        #   unique_users    — distinct users bound to the partner (new + existing)
        #   new_users_count — of those, users who were NEW (registered via link)
        #   completed_count — of those, users who completed ALL conditions
        "clicks_count": int(p.get("clicks_count", 0) or 0),
        "unique_users_count": int(p.get("unique_users_count", 0) or 0),
        "new_users_count": int(p.get("new_users_count", 0) or 0),
        "completed_count": int(p.get("completed_count", 0) or 0),
        "verify_path": verify_path,
        "verify_url": f"{base}{verify_path}" if base else verify_path,
        "stats": {
            "active_users": p.get("active_users_count", 0),
            "completed_users": p.get("active_users_count", 0),
            "total_referred": p.get("total_referred_count", 0),
            "paid_city": p.get("paid_city_total", 0),
        },
    }


def create_partner_admin_router(db, admin_dependency, backend_url: str):
    router = APIRouter(prefix="/api/admin/partner-programs", tags=["partner-programs"])

    @router.get("")
    async def list_programs(admin=Depends(admin_dependency)):
        docs = await db.partner_programs.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)
        out = []
        for p in docs:
            p["active_users_count"] = await db.partner_program_progress.count_documents(
                {"program_id": p["id"], "activated": True})
            p["total_referred_count"] = await db.users.count_documents(
                _referred_users_filter(p.get("referrer_user_id")))
            m = await partner_metrics(db, p.get("referrer_user_id"))
            p["unique_users_count"] = m["unique_users"]
            p["new_users_count"] = m["new_users"]
            p["completed_count"] = m["completed"]
            # clicks_count stays the stored raw counter (do not overwrite)
            out.append(_public_program(p, backend_url))
        return {"programs": out}

    @router.post("")
    async def create_program(data: ProgramCreate, admin=Depends(admin_dependency)):
        referrer_id = parse_ref_user_id(data.ref_link)
        if not referrer_id:
            raise HTTPException(status_code=400, detail="Не удалось разобрать реф-ссылку (ожидается ?ref=<user_id>)")
        owner = await db.users.find_one({"id": referrer_id}, {"_id": 0, "id": 1, "username": 1})
        if not owner:
            raise HTTPException(status_code=400, detail="Пользователь из реф-ссылки не найден в проекте")
        if bool(data.require_business_upgrade) and int(data.upgrade_to_level or 1) <= int(data.upgrade_from_level or 0):
            raise HTTPException(status_code=400, detail="upgrade_to_level должен быть больше upgrade_from_level")
        api_key = secrets.token_urlsafe(16)
        while await db.partner_programs.find_one({"api_key": api_key}):
            api_key = secrets.token_urlsafe(16)
        doc = {
            "id": str(uuid.uuid4()),
            "api_key": api_key,
            "name": data.name.strip() or f"Партнёр {referrer_id[:6]}",
            "ref_link": data.ref_link.strip(),
            "referrer_user_id": referrer_id,
            "require_land": bool(data.require_land),
            "min_market_spend_city": float(data.min_market_spend_city or 0),
            "require_business_upgrade": bool(data.require_business_upgrade),
            "upgrade_from_level": int(data.upgrade_from_level or 0),
            "upgrade_to_level": int(data.upgrade_to_level or 1),
            "per_active_user_city": float(data.per_active_user_city or 0),
            "income_percent": float(data.income_percent or 0),
            "active": True,
            "paid_city_total": 0.0,
            "created_at": _now_iso(),
        }
        # Optionally generate + persist a direct Telegram Mini App referral link.
        if (data.tma_base_url or "").strip():
            try:
                _rid, tma_ref_url = build_tma_ref_url(data.ref_link, data.tma_base_url)
                doc["tma_base_url"] = data.tma_base_url.strip()
                doc["tma_ref_url"] = tma_ref_url
            except ValueError as ve:
                raise HTTPException(status_code=400, detail=str(ve))
        await db.partner_programs.insert_one(doc.copy())
        # Flag the referrer as a partner so they drop out of leaderboard/rally.
        try:
            await db.users.update_one({"id": referrer_id}, {"$set": {"b2b_is_partner": True}})
        except Exception as e:
            logger.debug(f"flag partner referrer failed: {e}")
        return {"status": "created", "program": _public_program(doc, backend_url)}

    @router.post("/generate-tma-link")
    async def generate_tma_link(data: TmaLinkRequest, admin=Depends(admin_dependency)):
        """Pure generation (no persistence): web ref link + TMA base → TMA ref link.
        Used by the 'Сгенерировать реф-ссылку' button before a program is saved."""
        try:
            ref_id, tma_ref_url = build_tma_ref_url(data.web_ref_url, data.tma_base_url)
        except ValueError as ve:
            raise HTTPException(status_code=400, detail=str(ve))
        return {"ref_id": ref_id, "tma_ref_url": tma_ref_url}

    @router.post("/{program_id}/tma-link")
    async def save_tma_link(program_id: str, data: TmaLinkSaveRequest, admin=Depends(admin_dependency)):
        """Generate the TMA ref link from an EXISTING program's ref_link and the
        given base URL, then persist tma_base_url + tma_ref_url on the program."""
        p = await db.partner_programs.find_one({"id": program_id}, {"_id": 0})
        if not p:
            raise HTTPException(status_code=404, detail="Программа не найдена")
        try:
            ref_id, tma_ref_url = build_tma_ref_url(p.get("ref_link", ""), data.tma_base_url)
        except ValueError as ve:
            raise HTTPException(status_code=400, detail=str(ve))
        await db.partner_programs.update_one(
            {"id": program_id},
            {"$set": {"tma_base_url": data.tma_base_url.strip(), "tma_ref_url": tma_ref_url}},
        )
        p = await db.partner_programs.find_one({"id": program_id}, {"_id": 0})
        return {"status": "ok", "ref_id": ref_id, "tma_ref_url": tma_ref_url,
                "program": _public_program(p, backend_url)}

    @router.patch("/{program_id}")
    async def update_program(program_id: str, data: ProgramUpdate, admin=Depends(admin_dependency)):
        p = await db.partner_programs.find_one({"id": program_id}, {"_id": 0})
        if not p:
            raise HTTPException(status_code=404, detail="Программа не найдена")
        upd = {}
        if data.name is not None:
            upd["name"] = data.name.strip()
        if data.ref_link is not None:
            rid = parse_ref_user_id(data.ref_link)
            if not rid:
                raise HTTPException(status_code=400, detail="Некорректная реф-ссылка")
            upd["ref_link"] = data.ref_link.strip()
            upd["referrer_user_id"] = rid
        if data.require_land is not None:
            upd["require_land"] = bool(data.require_land)
        if data.min_market_spend_city is not None:
            upd["min_market_spend_city"] = float(data.min_market_spend_city)
        if data.require_business_upgrade is not None:
            upd["require_business_upgrade"] = bool(data.require_business_upgrade)
        if data.upgrade_from_level is not None:
            upd["upgrade_from_level"] = max(0, int(data.upgrade_from_level))
        if data.upgrade_to_level is not None:
            upd["upgrade_to_level"] = max(1, int(data.upgrade_to_level))
        if data.per_active_user_city is not None:
            upd["per_active_user_city"] = float(data.per_active_user_city)
        if data.income_percent is not None:
            upd["income_percent"] = max(0.0, min(100.0, float(data.income_percent)))
        if data.active is not None:
            upd["active"] = bool(data.active)
        # (Re)generate the TMA ref link when the base URL and/or ref link change.
        if data.tma_base_url is not None:
            base = data.tma_base_url.strip()
            if base:
                ref_src = upd.get("ref_link", p.get("ref_link", ""))
                try:
                    _rid, tma_ref_url = build_tma_ref_url(ref_src, base)
                except ValueError as ve:
                    raise HTTPException(status_code=400, detail=str(ve))
                upd["tma_base_url"] = base
                upd["tma_ref_url"] = tma_ref_url
            else:
                upd["tma_base_url"] = None
                upd["tma_ref_url"] = None
        elif "ref_link" in upd and p.get("tma_base_url"):
            # ref link changed and a base was set before → refresh the TMA link.
            try:
                _rid, tma_ref_url = build_tma_ref_url(upd["ref_link"], p["tma_base_url"])
                upd["tma_ref_url"] = tma_ref_url
            except ValueError:
                pass
        if not upd:
            raise HTTPException(status_code=400, detail="Нет полей для обновления")
        # Guard: an upgrade task must climb at least one level (to > from).
        eff_req = upd.get("require_business_upgrade", p.get("require_business_upgrade", False))
        eff_from = int(upd.get("upgrade_from_level", p.get("upgrade_from_level", 0)) or 0)
        eff_to = int(upd.get("upgrade_to_level", p.get("upgrade_to_level", 1)) or 1)
        if eff_req and eff_to <= eff_from:
            raise HTTPException(status_code=400, detail="upgrade_to_level должен быть больше upgrade_from_level")
        await db.partner_programs.update_one({"id": program_id}, {"$set": upd})
        if "referrer_user_id" in upd:
            try:
                await db.users.update_one({"id": upd["referrer_user_id"]}, {"$set": {"b2b_is_partner": True}})
            except Exception:
                pass
        p = await db.partner_programs.find_one({"id": program_id}, {"_id": 0})
        return {"status": "ok", "program": _public_program(p, backend_url)}

    @router.delete("/{program_id}")
    async def delete_program(program_id: str, admin=Depends(admin_dependency)):
        p = await db.partner_programs.find_one({"id": program_id}, {"_id": 0})
        if not p:
            raise HTTPException(status_code=404, detail="Программа не найдена")
        await db.partner_programs.delete_one({"id": program_id})
        await db.partner_program_progress.delete_many({"program_id": program_id})
        # If this referrer has no other active program, remove the partner flag.
        rid = p.get("referrer_user_id")
        if rid and not await db.partner_programs.find_one({"referrer_user_id": rid}):
            try:
                await db.users.update_one({"id": rid}, {"$unset": {"b2b_is_partner": ""}})
            except Exception:
                pass
        return {"status": "deleted"}

    @router.get("/{program_id}/logs")
    async def program_logs(program_id: str, status: str = "all",
                           date_from: Optional[str] = None, date_to: Optional[str] = None,
                           admin=Depends(admin_dependency)):
        q = {"program_id": program_id}
        if status == "success":
            q["success"] = True
        elif status == "failed":
            q["success"] = False
        _range = _created_at_range(date_from, date_to)
        if _range:
            q["created_at"] = _range
        logs = await db.partner_verify_logs.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
        return {"logs": logs, "count": len(logs)}

    @router.get("/{program_id}/referred-users")
    async def referred_users(program_id: str, search: str = "", admin=Depends(admin_dependency)):
        """Detailed list of every user attracted by this partner, with live
        progress. Powers the admin 'Логи' (приведённые игроки) modal.

        Returns per user: telegram_id, username, partner_joined_at, land_count,
        market_spent_city, partner_task_completed.
        """
        program = await db.partner_programs.find_one({"id": program_id}, {"_id": 0})
        if not program:
            raise HTTPException(status_code=404, detail="Программа не найдена")
        rid = program.get("referrer_user_id")
        flt = _referred_users_filter(rid)

        s = (search or "").strip()
        if s:
            import re
            rx = {"$regex": re.escape(s), "$options": "i"}
            flt = {"$and": [flt, {"$or": [
                {"username": rx},
                {"telegram_id": rx},
                {"telegram_user_id": rx},
                {"telegram_chat_id": rx},
                {"id": rx},
            ]}]}

        users = await db.users.find(
            flt,
            {"_id": 0, "id": 1, "username": 1, "telegram_id": 1, "telegram_user_id": 1,
             "telegram_chat_id": 1, "partner_joined_at": 1, "created_at": 1,
             "partner_task_completed": 1, "partner_is_new": 1},
        ).sort("partner_joined_at", -1).to_list(1000)

        need = float(program.get("min_market_spend_city") or 0)
        require_land = bool(program.get("require_land", True))
        require_upgrade = bool(program.get("require_business_upgrade", False))
        to_level = int(program.get("upgrade_to_level", 1) or 1)
        from_level = int(program.get("upgrade_from_level", 0) or 0)
        rows = []
        completed = 0
        new_users = 0
        for u in users:
            uid = u.get("id")
            _since = u.get("partner_joined_at")
            land = await land_purchase_count(db, uid, since=_since)
            spent = await market_spend_city(db, uid, since=_since)
            upg = await business_upgrade_count(db, uid, to_level, since=_since) if require_upgrade else 0
            done = bool(u.get("partner_task_completed"))
            is_new = bool(u.get("partner_is_new"))
            if done:
                completed += 1
            if is_new:
                new_users += 1
            rows.append({
                "user_id": uid,
                "telegram_id": u.get("telegram_id") or u.get("telegram_user_id") or u.get("telegram_chat_id"),
                "username": u.get("username"),
                "partner_joined_at": u.get("partner_joined_at") or u.get("created_at"),
                "land_count": land,
                "market_spent_city": spent,
                "upgrade_count": upg,
                "partner_task_completed": done,
                "is_new": is_new,
                "land_ok": (not require_land) or land >= 1,
                "market_ok": spent >= need,
                "upgrade_ok": (not require_upgrade) or upg >= 1,
            })
        return {
            "program_id": program_id,
            "referrer_user_id": rid,
            "require_land": require_land,
            "min_market_spend_city": need,
            "require_business_upgrade": require_upgrade,
            "upgrade_from_level": from_level,
            "upgrade_to_level": to_level,
            "clicks_count": int(program.get("clicks_count", 0) or 0),
            "unique_users_count": len(users),
            "new_users_count": new_users,
            "completed_count": completed,
            "users": rows,
            "count": len(rows),
        }

    @router.get("/{program_id}/logs.csv")
    async def program_logs_csv(program_id: str, status: str = "all",
                               date_from: Optional[str] = None, date_to: Optional[str] = None,
                               admin=Depends(admin_dependency)):
        program = await db.partner_programs.find_one({"id": program_id}, {"_id": 0})
        if not program:
            raise HTTPException(status_code=404, detail="Программа не найдена")
        q = {"program_id": program_id}
        if status == "success":
            q["success"] = True
        elif status == "failed":
            q["success"] = False
        _range = _created_at_range(date_from, date_to)
        if _range:
            q["created_at"] = _range
        logs = await db.partner_verify_logs.find(q, {"_id": 0}).sort("created_at", -1).to_list(5000)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow([
            "timestamp", "user_id", "resolved_user_id", "username", "result_code",
            "success", "referral_ok", "land_ok", "land_count",
            "market_ok", "market_spent_city", "market_need_city", "credited_city", "ip",
        ])
        for l in logs:
            ch = l.get("checks") or {}
            land = ch.get("land") or {}
            market = ch.get("market") or {}
            w.writerow([
                l.get("created_at", ""), l.get("user_id", ""), l.get("resolved_user_id", ""),
                l.get("username", ""), l.get("result_code", ""), l.get("success", ""),
                (ch.get("referral") or {}).get("ok", ""),
                land.get("ok", ""), land.get("count", ""),
                market.get("ok", ""), market.get("spent_city", ""), market.get("need_city", ""),
                l.get("credited_city", 0), l.get("ip", ""),
            ])
        safe_name = "".join(c for c in (program.get("name") or "partner") if c.isalnum() or c in "-_") or "partner"
        fname = f"partner_logs_{safe_name}_{status}.csv"
        # BOM so Excel opens UTF-8 correctly
        content = "\ufeff" + buf.getvalue()
        return Response(
            content=content,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )

    @router.get("/{program_id}/chart")
    async def program_chart(program_id: str, days: int = 14,
                            date_from: Optional[str] = None, date_to: Optional[str] = None,
                            admin=Depends(admin_dependency)):
        """Daily buckets: referrals (users who joined via the partner link) vs
        completions (users who passed verification). Either a rolling window of
        `days` days OR an explicit [date_from, date_to] range (inclusive)."""
        program = await db.partner_programs.find_one({"id": program_id}, {"_id": 0})
        if not program:
            raise HTTPException(status_code=404, detail="Программа не найдена")
        from datetime import timedelta
        df = (date_from or "").strip()
        dt = (date_to or "").strip()
        if df or dt:
            try:
                end = datetime.fromisoformat(dt[:10]).date() if dt else datetime.now(timezone.utc).date()
                start = datetime.fromisoformat(df[:10]).date() if df else (end - timedelta(days=13))
            except ValueError:
                raise HTTPException(status_code=400, detail="Некорректный формат даты (ожидается YYYY-MM-DD)")
            if start > end:
                start, end = end, start
            span = (end - start).days + 1
            span = max(1, min(span, 366))
            labels = [(start + timedelta(days=i)).isoformat() for i in range(span)]
        else:
            days = max(1, min(60, int(days)))
            today = datetime.now(timezone.utc).date()
            labels = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
        ref_counts = {d: 0 for d in labels}
        comp_counts = {d: 0 for d in labels}
        # Referrals — users attributed to this partner, bucketed by join date
        async for u in db.users.find(
            {"referrerId": program["referrer_user_id"]},
            {"_id": 0, "created_at": 1, "createdAt": 1}):
            ca = u.get("created_at") or u.get("createdAt") or ""
            d = str(ca)[:10]
            if d in ref_counts:
                ref_counts[d] += 1
        # Completions — activated progress, bucketed by activation date
        async for p in db.partner_program_progress.find(
            {"program_id": program_id, "activated": True}, {"_id": 0, "activated_at": 1}):
            d = str(p.get("activated_at") or "")[:10]
            if d in comp_counts:
                comp_counts[d] += 1
        return {
            "labels": labels,
            "referrals": [ref_counts[d] for d in labels],
            "completions": [comp_counts[d] for d in labels],
        }

    return router


def create_partner_public_router(db):
    router = APIRouter(prefix="/api/partner", tags=["partner-public"])

    async def _verify(api_key: str, user_id: Optional[str], ip: str):
        program = await db.partner_programs.find_one({"api_key": api_key}, {"_id": 0})
        if not program:
            raise HTTPException(status_code=404, detail="Unknown partner key")
        if program.get("active") is False:
            raise HTTPException(status_code=403, detail="Program is inactive")
        if not user_id:
            raise HTTPException(status_code=400, detail="user_id is required")

        user = await resolve_user(db, user_id)
        checks = {}
        missing = []

        # 1) Attribution — the user must have joined via THIS partner's ref link.
        #    Read every referral field on the user doc (partner_ref_id /
        #    referrer_id / ref_by / invited_by / referrerId / start_param …) and
        #    match against the program's referrer, so new-style bindings and the
        #    legacy `referrerId` field are all honoured.
        attributed = bool(user and str(program["referrer_user_id"]) in user_referrer_ids(user))
        checks["referral"] = {"ok": attributed}
        if not attributed:
            missing.append("referral")

        uid = user.get("id") if user else str(user_id)

        # Only purchases made AFTER the user joined via THIS partner count
        # towards the conditions — a user's pre-existing land/spend (bought
        # before they came in through the partner link) must NOT satisfy the
        # task. `partner_joined_at` is that cutoff; if the user is attributed
        # but has no cutoff yet, anchor it to NOW and persist it.
        since = None
        if user:
            since = user.get("partner_joined_at")
            if attributed and not since:
                since = _now_iso()
                await db.users.update_one({"id": uid}, {"$set": {"partner_joined_at": since}})

        # 2) Land purchase (fact of purchase)
        if program.get("require_land"):
            cnt = await land_purchase_count(db, uid, since=since) if user else 0
            ok = cnt >= 1
            checks["land"] = {"ok": ok, "count": cnt}
            if not ok:
                missing.append("land")

        # 3) Marketplace spend threshold ($CITY)
        thr = float(program.get("min_market_spend_city") or 0)
        if thr > 0:
            spent = await market_spend_city(db, uid, since=since) if user else 0.0
            ok = spent >= thr
            checks["market"] = {"ok": ok, "spent_city": spent, "need_city": thr}
            if not ok:
                missing.append("market")

        # 4) Business upgrade (from_level → to_level, default 0 → 1)
        if program.get("require_business_upgrade"):
            to_lvl = int(program.get("upgrade_to_level", 1) or 1)
            from_lvl = int(program.get("upgrade_from_level", 0) or 0)
            cnt = await business_upgrade_count(db, uid, to_lvl, since=since) if user else 0
            ok = cnt >= 1
            checks["business_upgrade"] = {"ok": ok, "count": cnt,
                                          "from_level": from_lvl, "to_level": to_lvl}
            if not ok:
                missing.append("business_upgrade")

        success = len(missing) == 0
        result_code = 200 if success else 402

        # First-time activation → pay the partner the per-active-user reward.
        credited = 0.0
        if success:
            prog = await db.partner_program_progress.find_one(
                {"program_id": program["id"], "user_id": uid}, {"_id": 0})
            if not prog or not prog.get("activated"):
                res = await db.partner_program_progress.update_one(
                    {"program_id": program["id"], "user_id": uid, "activated": {"$ne": True}},
                    {"$set": {"program_id": program["id"], "user_id": uid,
                              "activated": True, "activated_at": _now_iso()}},
                    upsert=True,
                )
                if res.modified_count or res.upserted_id:
                    per = float(program.get("per_active_user_city") or 0)
                    if per > 0:
                        ton = per / 1000.0
                        await db.users.update_one(
                            {"id": program["referrer_user_id"]},
                            {"$inc": {"balance_ton": ton, "b2b_earned_city": per}},
                        )
                        await db.partner_programs.update_one(
                            {"id": program["id"]}, {"$inc": {"paid_city_total": per}})
                        credited = per

        # Log every call
        await db.partner_verify_logs.insert_one({
            "id": str(uuid.uuid4()),
            "program_id": program["id"],
            "api_key": api_key,
            "user_id": str(user_id),
            "resolved_user_id": uid if user else None,
            "username": (user or {}).get("username"),
            "success": success,
            "result_code": result_code,
            "checks": checks,
            "missing": missing,
            "credited_city": credited,
            "ip": ip,
            "created_at": _now_iso(),
        })

        body = {"status": "completed" if success else "incomplete", "checks": checks}
        if not success:
            body["missing"] = missing
        return JSONResponse(status_code=result_code, content=body)

    @router.post("/click")
    async def track_click(request: Request):
        """Count a RAW click/open of a partner referral link (anonymous & repeat
        opens included). The Mini App calls this on launch with the ref id from
        `startapp`. Increments the program's stored `clicks_count`."""
        ref = None
        try:
            body = await request.json()
            if isinstance(body, dict):
                ref = body.get("ref") or body.get("ref_id") or body.get("start_param")
        except Exception:
            pass
        if not ref:
            ref = request.query_params.get("ref")
        ref = parse_ref_user_id(ref) if ref else None
        if not ref:
            return {"ok": False, "counted": False}
        res = await db.partner_programs.update_one(
            {"referrer_user_id": str(ref), "active": {"$ne": False}},
            {"$inc": {"clicks_count": 1}})
        return {"ok": True, "counted": bool(res.modified_count)}

    @router.get("/verify/{api_key}")
    async def verify_get(api_key: str, request: Request, user_id: Optional[str] = None, ref_id: Optional[str] = None):
        ip = request.client.host if request.client else "?"
        return await _verify(api_key, user_id, ip)

    @router.post("/verify/{api_key}")
    async def verify_post(api_key: str, request: Request):
        ip = request.client.host if request.client else "?"
        user_id = None
        try:
            body = await request.json()
            if isinstance(body, dict):
                user_id = body.get("user_id")
        except Exception:
            pass
        if not user_id:
            qp = request.query_params
            user_id = qp.get("user_id")
        return await _verify(api_key, user_id, ip)

    return router
