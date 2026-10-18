"""
Tutorial Routes
===============
Endpoints for the interactive sandbox tutorial.

All endpoints are under /api/tutorial/* and are always allowed (even during tutorial).
"""
import logging
import uuid
from datetime import datetime, timezone
from core.dtutils import to_aware
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt  # PyJWT (python-jose: unpatched CVEs and not in requirements)
from jwt import PyJWTError as JWTError
from pydantic import BaseModel, Field

from tutorial_steps import (
    TUTORIAL_STEPS,
    STEP_BY_ID,
    TUTORIAL_STEP_IDS,
    TOTAL_STEPS,
    get_step,
    get_next_step,
    get_step_by_index,
)
from ton_island import generate_ton_island_map

logger = logging.getLogger(__name__)

from auth_cookie import CookieOrBearer
security = CookieOrBearer(auto_error=False)


# ------------- Request models -------------
class AdvanceRequest(BaseModel):
    step_id: str
    # Optional: client's claim of what it did; server still enforces gates.
    reason: Optional[str] = None


class FakeBuyPlotRequest(BaseModel):
    x: int
    y: int
    zone: Optional[str] = "outskirts"
    business_icon: Optional[str] = None
    business_name: Optional[str] = None


class FakeGrantResourceRequest(BaseModel):
    resource_type: str = "neuro_core"
    amount: int = 10


class FinishRequest(BaseModel):
    confirm: bool = True
    t3_choice: Optional[str] = None  # v2.1.5: T3 resource picked as graduation reward


class CreateLotRequest(BaseModel):
    resource_type: str = "neuro_core"
    amount: int = 5
    price_per_unit: float = 1.0


# ------------- Helpers -------------
def _now():
    return datetime.now(timezone.utc).isoformat()


def _serialize_user(user_doc: Dict[str, Any]) -> Dict[str, Any]:
    d = dict(user_doc)
    d.pop("_id", None)
    d.pop("hashed_password", None)
    d.pop("password_hash", None)
    d.pop("two_factor_secret", None)
    return d


def _make_snapshot(user_doc: Dict[str, Any]) -> Dict[str, Any]:
    """Copy fields that may be mutated during tutorial, for later restore."""
    return {
        "balance_ton": user_doc.get("balance_ton", 0.0),
        "resources": dict(user_doc.get("resources", {}) or {}),
        "active_resource_buffs": list(user_doc.get("active_resource_buffs", []) or []),
        "level": user_doc.get("level", 1),
        "xp": user_doc.get("xp", 0),
        "total_turnover": user_doc.get("total_turnover", 0.0),
        "total_income": user_doc.get("total_income", 0.0),
        "plots_owned": list(user_doc.get("plots_owned", []) or []),
        "businesses_owned": list(user_doc.get("businesses_owned", []) or []),
    }


# T3 resources eligible as the one-shot graduation reward (shared with the
# tutorial router closure below — kept here so the background auto-complete
# job can grant a RANDOM one without importing the closure internals).
T3_REWARD_RESOURCES = {
    "neuro_core", "gold_bill", "license_token", "luck_chip",
    "war_protocol", "bio_module", "gateway_code",
}


def _compute_clean_resources(user: Dict[str, Any], snap: Dict[str, Any]) -> Dict[str, int]:
    """Return the resource dict the user should end up with after tutorial
    cleanup, GUARANTEEING that no resource granted DURING the tutorial leaks
    into normal play.

    Preferred path — snapshot restore:
      If the pre-tutorial ``snap["resources"]`` is present, we simply use it
      as-is. That's the "gold standard": we know exactly what the user had
      before starting the tutorial, so we reset to that baseline.

    Fallback path — grant clawback:
      If the snapshot is missing or has no ``resources`` key (corruption,
      partial state, an old bug etc.), we defensively subtract the amounts
      tracked in ``tutorial_state.granted_resources`` from the LIVE resources
      dict. Values are clamped at 0. This guarantees any resource we granted
      DURING the tutorial is undone even without a snapshot to fall back on.
    """
    if snap and isinstance(snap.get("resources"), dict):
        return dict(snap["resources"])
    # Defensive fallback: subtract tracked grants from the live doc.
    live = dict(user.get("resources") or {})
    tut_state = user.get("tutorial_state") or {}
    granted = tut_state.get("granted_resources") or {}
    for key, amount in granted.items():
        try:
            live[key] = max(0, int(live.get(key, 0) or 0) - int(amount or 0))
        except (TypeError, ValueError):
            continue
    return live


def _parse_iso(dt_str: str):
    """Parse an ISO datetime string to an aware datetime, or None."""
    if not dt_str:
        return None
    try:
        s = str(dt_str).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _tutorial_user_filter(user_doc: Dict[str, Any]) -> Dict[str, Any]:
    if user_doc.get("id"):
        return {"id": user_doc["id"]}
    if user_doc.get("email"):
        return {"email": user_doc["email"]}
    if user_doc.get("wallet_address"):
        return {"wallet_address": user_doc["wallet_address"]}
    return {"_id": user_doc["_id"]}


async def _finish_tutorial_for_user(db, user: Dict[str, Any], t3_choice: Optional[str] = None) -> Dict[str, Any]:
    """Core finish/rollback used by both the /finish endpoint path and the
    background auto-complete job.

    Cleans up all tutorial-scoped data, restores the pre-tutorial snapshot,
    marks the tutorial completed, and (optionally) grants one unit of the
    given T3 resource — but only if the user has never claimed the one-shot
    reward before. Returns a small result dict.
    """
    uid = user.get("id")
    already_claimed = bool(user.get("tutorial_t3_reward_granted"))

    # 1. Remove tutorial market listings (user-created + bot seed lots)
    for q in ({"seller_id": uid, "tutorial": True}, {"tutorial_seed_for": uid}):
        try:
            await db.market_listings.delete_many(q)
        except Exception as e:
            logger.warning(f"auto-finish: delete listings error: {e}")
    # 1b. Remove tutorial businesses
    try:
        await db.businesses.delete_many({"owner": uid, "tutorial": True})
    except Exception as e:
        logger.warning(f"auto-finish: delete businesses error: {e}")
    # 2. Remove tutorial transactions
    for q in ({"user_id": uid, "tutorial": True},
              {"from_address": user.get("wallet_address"), "tutorial": True}):
        try:
            await db.transactions.delete_many(q)
        except Exception:
            pass

    # 3. Restore snapshot
    snap = user.get("tutorial_snapshot") or {}
    set_doc: Dict[str, Any] = {
        "tutorial_active": False,
        "tutorial_completed": True,
        "tutorial_completed_at": _now(),
    }
    for key in ("balance_ton", "resources", "active_resource_buffs", "level", "xp",
                "total_turnover", "total_income", "plots_owned", "businesses_owned"):
        if key in snap:
            set_doc[key] = snap[key]

    granted = False
    # Compute the clean resource baseline. Prefers snapshot restore, falls
    # back to subtracting tracked grants from the live doc when the snapshot
    # is missing or corrupted. See ``_compute_clean_resources``.
    clean_resources = _compute_clean_resources(user, snap)
    if not already_claimed and t3_choice in T3_REWARD_RESOURCES:
        # v2.3.x atomic claim — race-safe against a concurrent manual /finish.
        # No `$inc resources` here: the reward unit is applied to
        # `clean_resources` and written by the final $set below.
        claim_res = await db.users.update_one(
            {**_tutorial_user_filter(user), "tutorial_t3_reward_granted": {"$ne": True}},
            {
                "$set": {
                    "tutorial_t3_reward_granted": True,
                    "tutorial_t3_reward_choice": t3_choice,
                    "tutorial_t3_reward_granted_at": _now(),
                    "tutorial_pending_t3_auto_activate": t3_choice,
                },
            },
        )
        granted = bool(claim_res.modified_count)

    effective_choice = t3_choice
    reward_present = granted or already_claimed
    if not reward_present:
        chk = await db.users.find_one(
            _tutorial_user_filter(user),
            {"_id": 0, "tutorial_t3_reward_granted": 1, "tutorial_t3_reward_choice": 1},
        )
        if chk and chk.get("tutorial_t3_reward_granted"):
            reward_present = True
            effective_choice = effective_choice or chk.get("tutorial_t3_reward_choice")
    if reward_present and effective_choice in T3_REWARD_RESOURCES:
        key = f"{effective_choice}_tutorial"
        clean_resources[key] = int(clean_resources.get(key, 0) or 0) + 1

    # Always overwrite resources with the clean baseline (+ reward) so no
    # tutorial-granted resource can survive graduation.
    set_doc["resources"] = clean_resources

    await db.users.update_one(
        _tutorial_user_filter(user),
        {
            "$set": set_doc,
            "$unset": {
                "tutorial_snapshot": "",
                "tutorial_state": "",
                "tutorial_current_step": "",
                "tutorial_started_at": "",
                "tutorial_bonus_ton": "",
            },
        },
    )

    # NOTE: the +0.5 TON welcome bonus is now granted ONCE at REGISTRATION for
    # every user (see core.welcome.ensure_welcome_bonus), not at tutorial
    # completion — previously it was only credited on the 20-min auto-complete
    # path, so users who finished/skipped the tutorial manually never got it.

    return {"ok": True, "t3_reward": t3_choice if granted else None, "t3_already_claimed": already_claimed}


async def auto_complete_expired_tutorials(db, timeout_minutes: int = 20) -> int:
    """Background job: auto-finish tutorials that have been active for longer
    than `timeout_minutes`.

    • First-ever completion → grant a RANDOM T3 resource (equiprobable).
    • Subsequent replays → finish only, no reward.
    Returns the number of tutorials auto-completed.
    """
    import random
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=timeout_minutes)
    completed = 0
    try:
        cursor = db.users.find({"tutorial_active": True})
        async for user in cursor:
            started = _parse_iso(user.get("tutorial_started_at"))
            # Skip only if the tutorial is still within its grace window. If the
            # start time is UNKNOWN (missing/unparseable), we DO finish it —
            # otherwise such a session would stay active forever and its
            # practice resources (the +5 Neuro Core "buy-lot" grant, etc.) would
            # never be rolled back, leaking into the user's real inventory.
            if started is not None and started > cutoff:
                continue
            # First run → random T3, otherwise no reward.
            already_claimed = bool(user.get("tutorial_t3_reward_granted"))
            t3_choice = None if already_claimed else random.choice(list(T3_REWARD_RESOURCES))
            try:
                res = await _finish_tutorial_for_user(db, user, t3_choice=t3_choice)
                completed += 1
                logger.info(
                    "⏱️ Tutorial auto-completed (20m timeout) for user=%s t3=%s",
                    user.get("username"), res.get("t3_reward"),
                )
            except Exception as e:
                logger.warning("auto_complete_expired_tutorials: finish failed for %s: %s",
                               user.get("username"), e)
    except Exception as e:
        logger.error("auto_complete_expired_tutorials job error: %s", e)
    return completed


def create_tutorial_router(db, secret_key: str, algorithm: str = "HS256") -> APIRouter:
    """Factory for the tutorial router."""
    router = APIRouter(prefix="/api/tutorial", tags=["tutorial"])

    async def _get_user(credentials: Optional[HTTPAuthorizationCredentials]) -> Dict[str, Any]:
        if not credentials:
            raise HTTPException(status_code=401, detail="Not authenticated")
        try:
            payload = jwt.decode(credentials.credentials, secret_key, algorithms=[algorithm])
            identifier = payload.get("sub")
        except JWTError:
            raise HTTPException(status_code=401, detail="Invalid token")
        if not identifier:
            raise HTTPException(status_code=401, detail="Invalid token")
        user_doc = await db.users.find_one({
            "$or": [
                {"wallet_address": identifier},
                {"email": identifier},
                {"username": identifier},
            ]
        })
        if not user_doc:
            raise HTTPException(status_code=404, detail="User not found")
        return user_doc

    def _user_filter(user_doc: Dict[str, Any]) -> Dict[str, Any]:
        if user_doc.get("id"):
            return {"id": user_doc["id"]}
        if user_doc.get("email"):
            return {"email": user_doc["email"]}
        if user_doc.get("wallet_address"):
            return {"wallet_address": user_doc["wallet_address"]}
        return {"_id": user_doc["_id"]}

    # -----------------------------------
    # GET /api/tutorial/status
    # -----------------------------------
    @router.get("/status")
    async def tutorial_status(credentials: HTTPAuthorizationCredentials = Depends(security)):
        user = await _get_user(credentials)
        # Auto-heal: if the user finished the tutorial but still has tracked
        # tutorial grants sitting in their doc (from an older buggy run or a
        # crash mid-cleanup), silently subtract them and drop the tracker.
        # This is idempotent and only fires when the flags are inconsistent.
        try:
            if not user.get("tutorial_active"):
                tut_state = user.get("tutorial_state") or {}
                granted = tut_state.get("granted_resources") or {}
                if granted:
                    live = dict(user.get("resources") or {})
                    for k, v in granted.items():
                        try:
                            live[k] = max(0, int(live.get(k, 0) or 0) - int(v or 0))
                        except (TypeError, ValueError):
                            continue
                    await db.users.update_one(
                        _user_filter(user),
                        {
                            "$set": {"resources": live},
                            "$unset": {
                                "tutorial_state.granted_resources": "",
                                "tutorial_snapshot": "",
                                "tutorial_state.fake_resources": "",
                            },
                        },
                    )
                    logger.info(
                        "Tutorial self-heal: purged leftover grants for user=%s: %s",
                        user.get("username"), granted,
                    )
                    user["resources"] = live
        except Exception as _e:
            logger.debug(f"tutorial self-heal skipped: {_e}")

        active = bool(user.get("tutorial_active"))
        current_step_id = user.get("tutorial_current_step") or "welcome"
        step = get_step(current_step_id) if active else None
        completed = bool(user.get("tutorial_completed"))
        # Onboarding A/B (see quests.py / ONBOARDING_MODE): players in the
        # "quests" group never get the forced tour — the client sees the tour
        # as done and shows the «Путь новичка» quest chain instead.
        onboarding_group = "tutorial"
        try:
            import quests as _quests
            onboarding_group = await _quests.onboarding_group(db, user)
        except Exception as _e:
            logger.debug(f"onboarding group resolve failed: {_e}")
        if onboarding_group == "quests" and not active:
            completed = True
        state = user.get("tutorial_state") or {"fake_plots": [], "fake_resources": {}, "fake_lot_id": None}
        return {
            "active": active,
            "completed": completed,
            "current_step_id": current_step_id if active else None,
            "current_step": step,
            "total_steps": TOTAL_STEPS,
            "step_ids": TUTORIAL_STEP_IDS,
            "steps": TUTORIAL_STEPS,
            "state": state,
            "onboarding_mode": "quests" if onboarding_group == "quests" else "tutorial",
            "onboarding_group": onboarding_group,
        }

    # -----------------------------------
    # POST /api/tutorial/start
    # -----------------------------------
    @router.post("/start")
    async def tutorial_start(credentials: HTTPAuthorizationCredentials = Depends(security)):
        user = await _get_user(credentials)
        if user.get("tutorial_active"):
            return {
                "ok": True,
                "already_active": True,
                "current_step_id": user.get("tutorial_current_step") or "welcome",
            }

        # v2.3.x — atomic re-entrancy guard. Two /start calls from the same
        # user (React StrictMode double-invoke, network retry, etc.) must
        # NOT both proceed: the second would take a corrupted snapshot AND
        # credit +50 TON practice balance a second time. `find_one_and_update`
        # with the filter "not currently active" wins for exactly one caller.
        _claim = await db.users.find_one_and_update(
            {**_user_filter(user), "tutorial_active": {"$ne": True}},
            {"$set": {"tutorial_active": True, "tutorial_started_at": _now()}},
            return_document=False,
        )
        if _claim is None:
            # Someone else won the race — return the current step so both
            # callers converge on the same UI state.
            fresh = await db.users.find_one(_user_filter(user), {"_id": 0, "tutorial_current_step": 1}) or {}
            return {
                "ok": True,
                "already_active": True,
                "current_step_id": fresh.get("tutorial_current_step") or "welcome",
            }
        snapshot = _make_snapshot(user)
        # Pick a deterministic tutorial plot. Per UX request (v2.2.1) we no
        # longer pick a pre-existing HELIOS cell on the outer ring — those are
        # far from the center and create a "jumping camera" feel. Instead we
        # pick the EMPTY cell (no pre_business, no owner) closest to the map
        # center and pretend it's HELIOS for the duration of the tutorial.
        # The frontend overlays the HELIOS preview icon on this cell when
        # `tutorial.state.tutorial_plot.business_type === 'helios'`.
        tutorial_plot = None
        try:
            owned_pairs = set()
            async for p in db.plots.find({}, {"x": 1, "y": 1, "_id": 0}):
                try:
                    owned_pairs.add((int(p["x"]), int(p["y"])))
                except Exception:
                    pass
            island = generate_ton_island_map()
            center_x = island.get("width", 0) // 2
            center_y = island.get("height", 0) // 2
            candidates = []
            for c in island.get("cells", []):
                # Only GRAM-City-owned (empty) cells, free of any owner.
                if not c.get("is_empty"):
                    continue
                if c.get("owner"):
                    continue
                if (int(c["x"]), int(c["y"])) in owned_pairs:
                    continue
                # Manhattan distance to map center — keeps the tutorial plot
                # comfortably visible in the default camera framing.
                d = abs(int(c["x"]) - center_x) + abs(int(c["y"]) - center_y)
                candidates.append((d, c))
            candidates.sort(key=lambda t: t[0])
            if candidates:
                _, c = candidates[0]
                tutorial_plot = {
                    "x": c["x"],
                    "y": c["y"],
                    "zone": c.get("zone", "outer"),
                    # Drives the frontend overlay — render as HELIOS preview.
                    "business_type": "helios",
                }
        except Exception as e:
            logger.warning(f"Tutorial: could not pick GRAM-City empty plot near center: {e}")
        if not tutorial_plot:
            # Safe fallback — any reasonable inner-zone coords (will still be
            # validated against the live map by the buy endpoint).
            tutorial_plot = {"x": 16, "y": 16, "zone": "core", "business_type": "helios"}

        initial_state = {
            "fake_plots": [],
            "fake_resources": {},
            "granted_resources": {},
            "fake_lot_id": None,
            "tutorial_plot": tutorial_plot,
        }
        # P1.2: Grant a VISIBLE practice balance for the duration of the
        # tutorial so the user can actually buy land (previously the balance
        # was 0 and the buy flow was blocked). We credit 50,000 $CITY, which
        # equals 50 TON (1 TON = 1000 $CITY). The pre-tutorial balance is
        # captured in `tutorial_snapshot` above and fully restored on
        # /finish, /reset and /abandon — so everything resets to the exact
        # state the user had before starting the tutorial.
        TUTORIAL_PRACTICE_CITY = 50000.0          # $CITY granted during tutorial
        TUTORIAL_HIDDEN_BUFFER = TUTORIAL_PRACTICE_CITY / 1000.0  # 50 TON
        await db.users.update_one(
            _user_filter(user),
            {
                "$set": {
                    "tutorial_active": True,
                    "tutorial_completed": False,
                    "tutorial_current_step": "welcome",
                    "tutorial_started_at": _now(),
                    "tutorial_snapshot": snapshot,
                    "tutorial_state": initial_state,
                    "tutorial_bonus_ton": TUTORIAL_HIDDEN_BUFFER,
                },
                "$inc": {"balance_ton": TUTORIAL_HIDDEN_BUFFER},
                "$unset": {
                    "tutorial_skipped": "",
                    "tutorial_skipped_at": "",
                    "tutorial_completed_at": "",
                },
            },
        )
        # Seed a hidden tutorial-bot market lot that only this user can see & buy from.
        # It will be consumed by /api/tutorial/buy-lot and cleaned up by /finish.
        uid = user.get("id")
        # Remove any stale seed lots for this user first
        try:
            await db.market_listings.delete_many({
                "tutorial_seed_for": uid,
            })
        except Exception:
            pass
        seed_lot = {
            "id": str(uuid.uuid4()),
            "seller_id": "tutorial_bot",
            "seller_email": None,
            "seller_username": "🤖 Tutorial Bot",
            "business_id": None,
            "resource_type": "neuro_core",
            "amount": 5,
            "price_per_unit": 0.5,
            "total_price": 2.5,
            "status": "active",
            "tutorial": True,
            "tutorial_seed_for": uid,
            "created_at": _now(),
        }
        try:
            await db.market_listings.insert_one(seed_lot.copy())
        except Exception as e:
            logger.warning(f"seed lot insert failed: {e}")
        logger.info(f"Tutorial started for user {user.get('username')}")
        return {
            "ok": True,
            "already_active": False,
            "current_step_id": "welcome",
            "state": initial_state,
        }

    # -----------------------------------
    # POST /api/tutorial/advance
    # -----------------------------------
    @router.post("/advance")
    async def tutorial_advance(
        data: AdvanceRequest,
        credentials: HTTPAuthorizationCredentials = Depends(security),
    ):
        user = await _get_user(credentials)
        if not user.get("tutorial_active"):
            raise HTTPException(status_code=400, detail="Tutorial is not active")

        current_id = user.get("tutorial_current_step") or "welcome"
        step = get_step(current_id)
        if not step:
            raise HTTPException(status_code=400, detail="Unknown tutorial step")

        # Only the current step can be advanced (or an optional step skip)
        if data.step_id != current_id:
            raise HTTPException(
                status_code=400,
                detail=f"step_id mismatch: current is {current_id}, got {data.step_id}",
            )

        # Gate checks
        gate = step.get("gate")
        if gate == "db_check" and current_id == "create_lot":
            count = await db.market_listings.count_documents({
                "seller_id": user.get("id"),
                "tutorial": True,
            })
            if count < 1:
                raise HTTPException(
                    status_code=400,
                    detail="tutorial_gate_failed: no tutorial lot found",
                )
        # Other gates (client_ack, page_visit, server_action) are satisfied by the
        # mere fact the client called advance — frontend enforces navigation first.

        # Compute next step id
        if current_id == "finish":
            raise HTTPException(status_code=400, detail="Use /api/tutorial/finish to complete")

        nxt = get_next_step(current_id)
        next_id = nxt["id"] if nxt else "finish"

        # Side-effects when advancing OUT of certain steps.
        # `explain_idle`: gift 50 biomass so the user's Helios actually starts producing.
        # The grant is wiped at /finish or /reset thanks to `tutorial_snapshot.resources`.
        if current_id == "explain_idle":
            await db.users.update_one(
                _user_filter(user),
                {"$inc": {
                    "resources.biomass": 50,
                    # Track the grant so cleanup can undo it even if the
                    # snapshot ever goes missing (belt-and-suspenders).
                    "tutorial_state.granted_resources.biomass": 50,
                }},
            )
            # Also push into the storage of the tutorial-flagged Helios business
            # so the in-game Warehouse view immediately shows fuel for the cycle.
            try:
                await db.businesses.update_one(
                    {"owner": user.get("id"), "tutorial": True, "business_type": "helios"},
                    {"$inc": {"storage.items.biomass": 50}},
                )
            except Exception as e:
                logger.warning(f"Tutorial: could not seed business biomass: {e}")

        await db.users.update_one(
            _user_filter(user),
            {"$set": {"tutorial_current_step": next_id}},
        )
        return {"ok": True, "previous_step_id": current_id, "current_step_id": next_id}

    # -----------------------------------
    # POST /api/tutorial/skip  (optional steps only)
    # -----------------------------------
    @router.post("/skip")
    async def tutorial_skip(
        data: AdvanceRequest,
        credentials: HTTPAuthorizationCredentials = Depends(security),
    ):
        user = await _get_user(credentials)
        if not user.get("tutorial_active"):
            raise HTTPException(status_code=400, detail="Tutorial is not active")
        current_id = user.get("tutorial_current_step") or "welcome"
        step = get_step(current_id)
        if data.step_id != current_id:
            raise HTTPException(
                status_code=400,
                detail=f"step_id mismatch: current is {current_id}, got {data.step_id}",
            )
        if not step or not step.get("optional"):
            raise HTTPException(status_code=400, detail="This step is not optional")
        nxt = get_next_step(current_id)
        next_id = nxt["id"] if nxt else "finish"
        await db.users.update_one(
            _user_filter(user),
            {"$set": {"tutorial_current_step": next_id}},
        )
        return {"ok": True, "skipped_step_id": current_id, "current_step_id": next_id}

    # -----------------------------------
    # POST /api/tutorial/fake-buy-plot
    # Creates a REAL tutorial business document (tutorial:true) so the user
    # actually sees it on the "My Businesses" page during the tutorial. On
    # finish/reset we delete everything tagged `tutorial:true`.
    # -----------------------------------
    @router.post("/fake-buy-plot")
    async def tutorial_fake_buy_plot(
        data: FakeBuyPlotRequest,
        credentials: HTTPAuthorizationCredentials = Depends(security),
    ):
        user = await _get_user(credentials)
        if not user.get("tutorial_active"):
            raise HTTPException(status_code=400, detail="Tutorial is not active")
        if user.get("tutorial_current_step") != "fake_buy_plot":
            raise HTTPException(status_code=400, detail="Not on fake_buy_plot step")

        # Restrict the purchase to the predetermined HELIOS plot only.
        tutorial_plot = (user.get("tutorial_state") or {}).get("tutorial_plot") or {}
        if (tutorial_plot.get("x") is not None and tutorial_plot.get("y") is not None
            and (data.x, data.y) != (tutorial_plot["x"], tutorial_plot["y"])):
            raise HTTPException(
                status_code=400,
                detail="tutorial_only_helios_plot: только подсвеченный участок с HELIOS доступен для покупки во время обучения.",
            )

        uid = user.get("id")
        fake_plots: List[Dict[str, Any]] = list(
            (user.get("tutorial_state") or {}).get("fake_plots", [])
        )
        fake_plots.append({
            "x": data.x,
            "y": data.y,
            "zone": data.zone or "outskirts",
            "business_icon": data.business_icon or "☀️",
            "business_name": data.business_name or "Helios Solar",
            "acquired_at": _now(),
        })

        # Also insert a REAL tutorial business doc so it shows on /my-businesses.
        # We pick `helios` — a simple T1 business with no resource consumption.
        biz_id = str(uuid.uuid4())
        tutorial_biz = {
            "id": biz_id,
            "plot_id": f"tutorial-plot-{uid}",
            "owner": uid,
            "owner_wallet": user.get("wallet_address"),
            "business_type": "helios",
            "level": 1,
            "building_progress": 100,
            "is_active": True,
            "last_collection": _now(),
            "created_at": _now(),
            "durability": 100,
            "storage": {"capacity": 100, "items": {}},
            "tutorial": True,
        }
        try:
            await db.businesses.insert_one(tutorial_biz.copy())
        except Exception as e:
            logger.warning(f"tutorial business insert failed: {e}")

        # Advance step to go_businesses
        nxt = get_next_step("fake_buy_plot")
        next_id = nxt["id"] if nxt else "finish"

        await db.users.update_one(
            _user_filter(user),
            {
                "$set": {
                    "tutorial_state.fake_plots": fake_plots,
                    "tutorial_state.fake_business_id": biz_id,
                    "tutorial_current_step": next_id,
                }
            },
        )
        return {"ok": True, "fake_plots": fake_plots, "business_id": biz_id, "current_step_id": next_id}

    # -----------------------------------
    # GET /api/tutorial/seed-lot
    # Returns the hidden tutorial-bot lot for the current user, if any.
    # Used by the Trading page to inject the bot lot into the public buy list
    # while tutorial is active.
    # -----------------------------------
    @router.get("/seed-lot")
    async def tutorial_seed_lot(credentials: HTTPAuthorizationCredentials = Depends(security)):
        user = await _get_user(credentials)
        uid = user.get("id")
        lot = await db.market_listings.find_one({"tutorial_seed_for": uid, "status": "active"})
        if not lot:
            return {"ok": True, "lot": None}
        lot.pop("_id", None)
        return {"ok": True, "lot": lot}

    # -----------------------------------
    # POST /api/tutorial/buy-lot
    # Buy (illusory) 5 units of Neuro Core from the tutorial-bot lot.
    # Adds to user's real resources (tracked in tutorial_state.fake_resources so
    # we can roll back on finish). Does NOT deduct balance.
    # -----------------------------------
    class BuyLotRequest(BaseModel):
        amount: int = 5

    @router.post("/buy-lot")
    async def tutorial_buy_lot(
        data: BuyLotRequest,
        credentials: HTTPAuthorizationCredentials = Depends(security),
    ):
        user = await _get_user(credentials)
        if not user.get("tutorial_active"):
            raise HTTPException(status_code=400, detail="Tutorial is not active")
        if user.get("tutorial_current_step") != "buy_lot":
            raise HTTPException(status_code=400, detail="Not on buy_lot step")

        amount = max(1, min(int(data.amount), 5))

        uid = user.get("id")
        # Delete the seed lot (consumed)
        await db.market_listings.delete_many({"tutorial_seed_for": uid})

        fake_resources = dict((user.get("tutorial_state") or {}).get("fake_resources", {}))
        fake_resources["neuro_core"] = int(fake_resources.get("neuro_core", 0)) + amount

        # Advance step
        nxt = get_next_step("buy_lot")
        next_id = nxt["id"] if nxt else "finish"

        await db.users.update_one(
            _user_filter(user),
            {
                "$set": {
                    "tutorial_state.fake_resources": fake_resources,
                    "tutorial_current_step": next_id,
                },
                "$inc": {
                    f"resources.neuro_core": amount,
                    "tutorial_state.granted_resources.neuro_core": amount,
                },
            },
        )
        return {"ok": True, "amount": amount, "current_step_id": next_id}

    # -----------------------------------
    # POST /api/tutorial/fake-grant-resource  (legacy, kept for compat)
    # -----------------------------------
    @router.post("/fake-grant-resource")
    async def tutorial_fake_grant_resource(
        data: FakeGrantResourceRequest,
        credentials: HTTPAuthorizationCredentials = Depends(security),
    ):
        user = await _get_user(credentials)
        if not user.get("tutorial_active"):
            raise HTTPException(status_code=400, detail="Tutorial is not active")
        if user.get("tutorial_current_step") != "fake_add_resources":
            raise HTTPException(status_code=400, detail="Not on fake_add_resources step")

        # Security: this legacy endpoint used to trust the client-supplied
        # `amount`/`resource_type`, which let a caller grant themselves an
        # arbitrary amount of any resource during the tutorial. The tutorial
        # only ever needs a small, fixed practice amount of Neuro Core, so we
        # hard-clamp both — mirroring the /buy-lot safeguard above.
        resource_type = "neuro_core"
        amount = max(1, min(int(data.amount), 10))

        fake_resources = dict((user.get("tutorial_state") or {}).get("fake_resources", {}))
        fake_resources[resource_type] = int(fake_resources.get(resource_type, 0)) + amount

        # Also add them to real user.resources so they appear naturally in trading flow.
        # They are tracked in tutorial_state.fake_resources so finish() can deduct them.
        await db.users.update_one(
            _user_filter(user),
            {
                "$set": {"tutorial_state.fake_resources": fake_resources},
                "$inc": {
                    f"resources.{resource_type}": amount,
                    f"tutorial_state.granted_resources.{resource_type}": amount,
                },
            },
        )

        # Advance step
        nxt = get_next_step("fake_add_resources")
        next_id = nxt["id"] if nxt else "finish"
        await db.users.update_one(
            _user_filter(user),
            {"$set": {"tutorial_current_step": next_id}},
        )

        return {"ok": True, "fake_resources": fake_resources, "current_step_id": next_id}

    # -----------------------------------
    # POST /api/tutorial/create-lot
    # Wrapper that creates a real tutorial market listing using the fake resources.
    # Keeps flow consistent: deducts from user.resources (which were granted), marks
    # listing with tutorial:true (hidden from others), and stores fake_lot_id.
    # -----------------------------------
    @router.post("/create-lot")
    async def tutorial_create_lot(
        data: CreateLotRequest,
        credentials: HTTPAuthorizationCredentials = Depends(security),
    ):
        user = await _get_user(credentials)
        if not user.get("tutorial_active"):
            raise HTTPException(status_code=400, detail="Tutorial is not active")
        if user.get("tutorial_current_step") != "create_lot":
            raise HTTPException(status_code=400, detail="Not on create_lot step")

        amount = int(data.amount)
        price = float(data.price_per_unit)
        if amount <= 0:
            raise HTTPException(status_code=400, detail="Amount must be > 0")
        if price <= 0:
            raise HTTPException(status_code=400, detail="Price must be > 0")

        # Deduct from user's resources (these were granted during fake_add_resources)
        user_resources = user.get("resources", {}) or {}
        have = int(user_resources.get(data.resource_type, 0))
        if have < amount:
            raise HTTPException(status_code=400, detail=f"Not enough {data.resource_type}")

        await db.users.update_one(
            _user_filter(user),
            {"$inc": {f"resources.{data.resource_type}": -amount}},
        )

        listing = {
            "id": str(uuid.uuid4()),
            "seller_id": user.get("id"),
            "seller_email": user.get("email"),
            "seller_username": user.get("username") or user.get("display_name") or "Tutorial",
            "business_id": None,
            "resource_type": data.resource_type,
            "amount": amount,
            "price_per_unit": round(price, 6),
            "total_price": round(amount * price, 2),
            "status": "active",
            "tutorial": True,  # critical: hide from public
            "created_at": _now(),
        }
        await db.market_listings.insert_one(listing.copy())

        # Advance step
        nxt = get_next_step("create_lot")
        next_id = nxt["id"] if nxt else "finish"

        await db.users.update_one(
            _user_filter(user),
            {
                "$set": {
                    "tutorial_state.fake_lot_id": listing["id"],
                    "tutorial_current_step": next_id,
                }
            },
        )
        listing.pop("_id", None)
        return {"ok": True, "listing": listing, "current_step_id": next_id}

    # -----------------------------------
    # POST /api/tutorial/finish
    # v2.1.5: grants 1 unit of a chosen T3 resource (picked in the finish
    # modal) and flags it for auto-activation on the user's first real
    # business purchase. The grant happens AFTER snapshot restore so it
    # survives the rollback. The flag `tutorial_pending_t3_auto_activate`
    # is consumed (one-shot) by the business-purchase hook.
    # -----------------------------------
    T3_REWARD_RESOURCES = {
        "neuro_core", "gold_bill", "license_token", "luck_chip",
        "war_protocol", "bio_module", "gateway_code",
    }

    @router.get("/t3-reward-status")
    async def tutorial_t3_status(
        credentials: HTTPAuthorizationCredentials = Depends(security),
    ):
        """Tells the UI whether the user still has the one-shot T3 reward
        pending. Used to decide if we need to show the reward picker on
        skip/finish, or just close the modal silently."""
        user = await _get_user(credentials)
        return {
            "claimed": bool(user.get("tutorial_t3_reward_granted")),
            "available": list(T3_REWARD_RESOURCES),
        }

    async def _grant_t3_reward(user: Dict[str, Any], t3_choice: str) -> bool:
        """Grant 1 unit of the chosen T3 to the user, exactly once per
        lifetime. Returns True if the reward was actually granted, False if
        the user had already claimed it.

        v2.3.x: race-safe — the update filter matches only when the reward
        flag has never been set, so concurrent callers cannot double-grant.
        """
        if t3_choice not in T3_REWARD_RESOURCES:
            return False
        claim_res = await db.users.update_one(
            {**_user_filter(user), "tutorial_t3_reward_granted": {"$ne": True}},
            {
                # Tutorial reward goes into a separate `<base>_tutorial` slot so
                # it shows as its own card in "My Resources" and cannot be sold.
                "$inc": {f"resources.{t3_choice}_tutorial": 1},
                "$set": {
                    "tutorial_t3_reward_granted": True,
                    "tutorial_t3_reward_choice": t3_choice,
                    "tutorial_t3_reward_granted_at": _now(),
                    # Flag consumed by business-purchase hook (auto-activate on
                    # first real business).
                    "tutorial_pending_t3_auto_activate": t3_choice,
                },
            },
        )
        return bool(claim_res.modified_count)

    async def _try_immediate_t3_activation(user: Dict[str, Any], t3_choice: str) -> bool:
        """If the user already owns at least one real (non-tutorial) business
        AT THIS MOMENT, activate the just-granted T3 reward as a buff right
        away instead of waiting for the next business purchase.

        Returns True if the buff was activated (the resource was consumed and
        the pending flag was cleared). Safe to call multiple times — no-op if
        prerequisites aren't met.
        """
        try:
            from core.helpers import resolve_owner_keys, owner_businesses_query
            from routes.buffs import RESOURCE_BUFFS  # local import to avoid circular
            from datetime import timedelta

            if not t3_choice:
                return False
            buff = RESOURCE_BUFFS.get(t3_choice)
            if not buff:
                return False

            # Reload user (fresh resources after grant)
            u = await db.users.find_one(_user_filter(user), {"_id": 0})
            if not u:
                return False

            # Need at least one real business
            keys = await resolve_owner_keys(db, u.get("id") or u.get("wallet_address") or u.get("email"))
            biz_q = {**owner_businesses_query(keys), "tutorial": {"$ne": True}}
            biz_count = await db.businesses.count_documents(biz_q)
            if biz_count < 1:
                return False

            # Need the resource in inventory — the tutorial-reward unit lives
            # in `resources[<base>_tutorial]` (see _grant_t3_reward). Consume
            # from that slot only.
            resources = u.get("resources", {}) or {}
            tut_key = f"{t3_choice}_tutorial"
            if int(resources.get(tut_key, 0) or 0) < 1:
                return False

            now = datetime.now(timezone.utc)
            expires = now + timedelta(days=buff["duration_days"])
            new_buff = {
                "resource_id": t3_choice,
                "buff_name": buff["name"],
                "buff_icon": buff["icon"],
                "buff_description": buff["description"],
                "effect_type": buff["effect_type"],
                "effect_value": buff["effect_value"],
                "activated_at": now.isoformat(),
                "expires_at": expires.isoformat(),
                "duration_days": buff["duration_days"],
                "active": True,
                "source": "tutorial_reward",
            }

            active_buffs = list(u.get("active_resource_buffs", []) or [])
            active_buffs = [
                b for b in active_buffs
                if b.get("expires_at") and (to_aware(b["expires_at"]) or now) > now
            ]
            # Skip if same T3 is already active
            if any(b.get("resource_id") == t3_choice for b in active_buffs):
                await db.users.update_one(
                    _user_filter(user),
                    {"$unset": {"tutorial_pending_t3_auto_activate": ""}},
                )
                return False
            active_buffs.append(new_buff)

            await db.users.update_one(
                _user_filter(user),
                {
                    "$inc": {f"resources.{t3_choice}_tutorial": -1},
                    "$set": {"active_resource_buffs": active_buffs},
                    "$unset": {"tutorial_pending_t3_auto_activate": ""},
                },
            )
            logger.info("Tutorial T3 auto-activated immediately for user %s: %s", u.get("username"), t3_choice)
            return True
        except Exception as e:
            logger.warning("_try_immediate_t3_activation failed: %s", e)
            return False

    @router.post("/finish")
    async def tutorial_finish(
        data: Optional[FinishRequest] = None,
        credentials: HTTPAuthorizationCredentials = Depends(security),
    ):
        user = await _get_user(credentials)
        if not user.get("tutorial_active"):
            # Idempotent
            return {"ok": True, "already_completed": bool(user.get("tutorial_completed"))}

        # v2.3.x — hardened against React double-invoke / concurrent /finish calls.
        # Instead of just reading `tutorial_t3_reward_granted`, we ATOMICALLY
        # claim the grant slot below (in the main $set). Here we only compute
        # the read-view of `already_claimed` for choice validation.
        already_claimed = bool(user.get("tutorial_t3_reward_granted"))
        # Validate T3 choice — but only if the user hasn't already claimed
        # the one-time reward in a previous run.
        t3_choice = (data.t3_choice if data else None) or None
        if not already_claimed:
            if not t3_choice or t3_choice not in T3_REWARD_RESOURCES:
                raise HTTPException(
                    status_code=400,
                    detail="tutorial_t3_choice_required",
                )

        uid = user.get("id")
        # 1. Remove tutorial market listings (user-created + bot seed lots)
        try:
            await db.market_listings.delete_many({"seller_id": uid, "tutorial": True})
        except Exception as e:
            logger.warning(f"finish: delete tutorial listings error: {e}")
        try:
            await db.market_listings.delete_many({"tutorial_seed_for": uid})
        except Exception as e:
            logger.warning(f"finish: delete seed lots error: {e}")
        # 1b. Remove tutorial businesses
        try:
            await db.businesses.delete_many({"owner": uid, "tutorial": True})
        except Exception as e:
            logger.warning(f"finish: delete tutorial businesses error: {e}")
        # 2. Remove tutorial transactions
        try:
            await db.transactions.delete_many({"user_id": uid, "tutorial": True})
        except Exception:
            pass
        try:
            await db.transactions.delete_many({"from_address": user.get("wallet_address"), "tutorial": True})
        except Exception:
            pass

        # 3. Restore snapshot
        snap = user.get("tutorial_snapshot") or {}
        set_doc = {
            "tutorial_active": False,
            "tutorial_completed": True,
            "tutorial_completed_at": _now(),
        }
        # Only restore keys that exist in the snapshot
        for key in ("balance_ton", "resources", "active_resource_buffs", "level", "xp",
                    "total_turnover", "total_income", "plots_owned", "businesses_owned"):
            if key in snap:
                set_doc[key] = snap[key]

        # Clean resource baseline. Uses snapshot restore when available;
        # falls back to tracked-grant clawback when the snapshot was lost
        # or corrupted. See ``_compute_clean_resources`` at module level.
        clean_resources = _compute_clean_resources(user, snap)

        granted = False
        if not already_claimed and t3_choice:
            # v2.3.x atomic claim — race-safe against concurrent /finish or
            # /mark-skipped calls. Only ONE call matches the filter
            # `tutorial_t3_reward_granted: {$ne: True}`, so the reward flag can
            # never be set twice. NOTE: no `$inc resources` here — the reward
            # unit is applied to `clean_resources` below and written via the
            # final $set, so it can't drag along any leaked tutorial resources.
            claim_res = await db.users.update_one(
                {**_user_filter(user), "tutorial_t3_reward_granted": {"$ne": True}},
                {
                    "$set": {
                        "tutorial_t3_reward_granted": True,
                        "tutorial_t3_reward_choice": t3_choice,
                        "tutorial_t3_reward_granted_at": _now(),
                        "tutorial_pending_t3_auto_activate": t3_choice,
                    },
                },
            )
            granted = bool(claim_res.modified_count)

        # Preserve the reward across the snapshot restore even if THIS call did
        # not win the atomic claim (a concurrent /finish granted it). Re-read
        # the flag so the reward is never wiped — and, because we SET (not inc)
        # from the clean snapshot, never duplicated either.
        effective_choice = t3_choice
        reward_present = granted or already_claimed
        if not reward_present:
            chk = await db.users.find_one(
                _user_filter(user),
                {"_id": 0, "tutorial_t3_reward_granted": 1, "tutorial_t3_reward_choice": 1},
            )
            if chk and chk.get("tutorial_t3_reward_granted"):
                reward_present = True
                effective_choice = effective_choice or chk.get("tutorial_t3_reward_choice")
        if reward_present and effective_choice in T3_REWARD_RESOURCES:
            key = f"{effective_choice}_tutorial"
            clean_resources[key] = int(clean_resources.get(key, 0) or 0) + 1

        # Always overwrite resources with the clean baseline (+ reward). This
        # guarantees NO tutorial-granted resource can survive graduation.
        set_doc["resources"] = clean_resources

        await db.users.update_one(
            _user_filter(user),
            {
                "$set": set_doc,
                "$unset": {
                    "tutorial_snapshot": "",
                    "tutorial_state": "",
                    "tutorial_current_step": "",
                    "tutorial_started_at": "",
                    "tutorial_bonus_ton": "",
                },
            },
        )
        logger.info(
            "Tutorial finished for user %s — t3_granted=%s choice=%s",
            user.get("username"), granted, t3_choice
        )
        # Task 4: if user already owns a business, immediately auto-activate
        # the T3 reward as a buff (no need to wait for next business purchase).
        if granted and t3_choice:
            await _try_immediate_t3_activation(user, t3_choice)
        return {
            "ok": True,
            "rolled_back": True,
            "t3_reward": t3_choice if granted else None,
            "t3_already_claimed": already_claimed,
        }

    # -----------------------------------
    # POST /api/tutorial/mark-skipped
    # User chose NOT to start the tutorial from the welcome modal.
    # We persist completed=true so the prompt never auto-opens again.
    # If the user passes a `t3_choice` AND hasn't claimed the one-shot
    # T3 reward yet, we grant 1 unit (skip → reward parity).
    # -----------------------------------
    class MarkSkippedRequest(BaseModel):
        t3_choice: Optional[str] = None

    @router.post("/mark-skipped")
    async def tutorial_mark_skipped(
        data: Optional[MarkSkippedRequest] = None,
        credentials: HTTPAuthorizationCredentials = Depends(security),
    ):
        user = await _get_user(credentials)
        # If tutorial is active, do nothing — user must finish/reset explicitly
        if user.get("tutorial_active"):
            return {"ok": True, "already_active": True}

        already_claimed = bool(user.get("tutorial_t3_reward_granted"))
        t3_choice = (data.t3_choice if data else None) or None

        update = {
            "tutorial_active": False,
            "tutorial_completed": True,
            "tutorial_skipped": True,
            "tutorial_skipped_at": _now(),
        }

        # Belt-and-suspenders: if there is any leftover tutorial state (an
        # aborted run, corrupted snapshot, etc.), we must clean it up NOW so
        # we never leak tutorial-granted resources when the user opts to skip.
        snap = user.get("tutorial_snapshot") or {}
        tut_state = user.get("tutorial_state") or {}
        has_leftover = bool(snap) or bool(tut_state.get("granted_resources"))

        # Atomic reward claim (race-safe). We DO NOT $inc `resources` here —
        # instead we set the flag atomically and, if has_leftover, merge the
        # reward into the follow-up $set below (mirrors /finish). This avoids
        # the leftover-cleanup $set wiping the reward we just credited.
        granted = False
        if not already_claimed and t3_choice in T3_REWARD_RESOURCES:
            reward_set: Dict[str, Any] = {
                "tutorial_t3_reward_granted": True,
                "tutorial_t3_reward_choice": t3_choice,
                "tutorial_t3_reward_granted_at": _now(),
                "tutorial_pending_t3_auto_activate": t3_choice,
            }
            reward_update: Dict[str, Any] = {"$set": reward_set}
            # If we are NOT doing a leftover-cleanup this call, credit the
            # reward directly via $inc — the follow-up $set won't touch
            # `resources`, so it's safe.
            if not has_leftover:
                reward_update["$inc"] = {f"resources.{t3_choice}_tutorial": 1}
            claim_res = await db.users.update_one(
                {**_user_filter(user), "tutorial_t3_reward_granted": {"$ne": True}},
                reward_update,
            )
            granted = bool(claim_res.modified_count)

        if has_leftover:
            # Compute the clean baseline (snapshot restore or fallback
            # clawback) and merge the just-granted reward into it BEFORE the
            # final $set — otherwise the $set would wipe the reward.
            clean_resources = _compute_clean_resources(user, snap)
            if granted and t3_choice in T3_REWARD_RESOURCES:
                key = f"{t3_choice}_tutorial"
                clean_resources[key] = int(clean_resources.get(key, 0) or 0) + 1
            update["resources"] = clean_resources
            for key in ("balance_ton", "active_resource_buffs", "level", "xp",
                        "total_turnover", "total_income", "plots_owned", "businesses_owned"):
                if key in snap:
                    update[key] = snap[key]

        mongo_update: Dict[str, Any] = {"$set": update}
        # If we cleaned leftover state, also drop the stale bookkeeping fields.
        if has_leftover:
            mongo_update["$unset"] = {
                "tutorial_snapshot": "",
                "tutorial_state": "",
                "tutorial_current_step": "",
                "tutorial_started_at": "",
                "tutorial_bonus_ton": "",
            }
        await db.users.update_one(_user_filter(user), mongo_update)
        logger.info(
            "Tutorial skipped for user %s — t3_granted=%s choice=%s",
            user.get("username"), granted, t3_choice
        )
        # Task 4: if user already owns a business, immediately auto-activate
        # the T3 reward (no need to wait for next business purchase).
        if granted and t3_choice:
            await _try_immediate_t3_activation(user, t3_choice)
        return {
            "ok": True,
            "marked_skipped": True,
            "t3_reward": t3_choice if granted else None,
            "t3_already_claimed": already_claimed,
        }

    # -----------------------------------
    # POST /api/tutorial/abandon
    # -----------------------------------
    # Called when the user clicks the X icon on the tutorial card mid-flow.
    # Behaviour: revert everything (snapshot rollback like /reset) AND mark the
    # tutorial as completed+skipped so the user is NOT auto-prompted again. No
    # T3 reward is granted — that's reserved for an explicit /finish call with
    # a chosen resource.
    @router.post("/abandon")
    async def tutorial_abandon(
        credentials: HTTPAuthorizationCredentials = Depends(security),
    ):
        user = await _get_user(credentials)
        uid = user.get("id")
        # Clean up tutorial-owned market listings & businesses regardless of
        # current state (idempotent).
        try:
            await db.market_listings.delete_many({"seller_id": uid, "tutorial": True})
        except Exception:
            pass
        try:
            await db.market_listings.delete_many({"tutorial_seed_for": uid})
        except Exception:
            pass
        try:
            await db.businesses.delete_many({"owner": uid, "tutorial": True})
        except Exception:
            pass
        snap = user.get("tutorial_snapshot") or {}
        set_doc: Dict[str, Any] = {
            "tutorial_active": False,
            "tutorial_completed": True,
            "tutorial_skipped": True,
            "tutorial_skipped_at": _now(),
        }
        for key in ("balance_ton", "active_resource_buffs", "level", "xp",
                    "total_turnover", "total_income", "plots_owned", "businesses_owned"):
            if key in snap:
                set_doc[key] = snap[key]
        # Always overwrite resources with the clean baseline so nothing granted
        # during tutorial can survive an abandon.
        set_doc["resources"] = _compute_clean_resources(user, snap)
        await db.users.update_one(
            _user_filter(user),
            {
                "$set": set_doc,
                "$unset": {
                    "tutorial_snapshot": "",
                    "tutorial_state": "",
                    "tutorial_current_step": "",
                    "tutorial_started_at": "",
                    "tutorial_bonus_ton": "",
                },
            },
        )
        logger.info("Tutorial abandoned (X-button) for user %s", user.get("username"))
        return {"ok": True, "abandoned": True}

    # -----------------------------------
    # POST /api/tutorial/reset  (admin/debug — allows replay)
    # -----------------------------------
    @router.post("/reset")
    async def tutorial_reset(
        credentials: HTTPAuthorizationCredentials = Depends(security),
    ):
        user = await _get_user(credentials)
        uid = user.get("id")
        # Clean up any tutorial-owned data regardless of current state
        try:
            await db.market_listings.delete_many({"seller_id": uid, "tutorial": True})
        except Exception:
            pass
        try:
            await db.market_listings.delete_many({"tutorial_seed_for": uid})
        except Exception:
            pass
        try:
            await db.businesses.delete_many({"owner": uid, "tutorial": True})
        except Exception:
            pass
        # Restore snapshot if we have one
        snap = user.get("tutorial_snapshot") or {}
        set_doc = {"tutorial_active": False, "tutorial_completed": False}
        for key in ("balance_ton", "active_resource_buffs", "level", "xp",
                    "total_turnover", "total_income", "plots_owned", "businesses_owned"):
            if key in snap:
                set_doc[key] = snap[key]
        # Always overwrite resources with the clean baseline (snapshot restore
        # OR tracked-grant clawback fallback).
        set_doc["resources"] = _compute_clean_resources(user, snap)
        await db.users.update_one(
            _user_filter(user),
            {
                "$set": set_doc,
                "$unset": {
                    "tutorial_snapshot": "",
                    "tutorial_state": "",
                    "tutorial_current_step": "",
                    "tutorial_started_at": "",
                    "tutorial_completed_at": "",
                    "tutorial_skipped": "",
                    "tutorial_skipped_at": "",
                    "tutorial_bonus_ton": "",
                },
            },
        )
        return {"ok": True, "reset": True}

    return router
