"""GRAM Island routes — map, plots, buildings.

Split from server.py (was `# ==================== GRAM ISLAND ROUTES ====================`
section at lines 1041-1581, ~540 lines).
"""
from datetime import datetime, timezone
from core.dtutils import to_aware
import logging
import os
import uuid

from fastapi import APIRouter, HTTPException, Depends

from core.dependencies import get_current_user
from core.models import User
from core.helpers import (
    get_user_identifiers as _helper_gui,
    is_owner,
    get_user_filter,
    resolve_business_config,
)
from business_config import BUSINESSES, PATRON_BONUSES, TIER_TAXES, RESOURCE_WEIGHTS, RESOURCE_TYPES
from ton_island import generate_ton_island_map, ZONES
from game_systems import get_production, get_consumption_breakdown, get_storage_capacity

logger = logging.getLogger(__name__)



async def _list_zero_business(db, full_business, user_id, user, business_id, plot_id):
    """Auto-list a freshly claimed level-0 business (map_price × 1.2). The buyer
    pays real TON and gets it as a normal level-1 business; the claimer loses it
    (they were warned when claiming). Never breaks the claim itself."""
    try:
        import zero_business as _zb2
        listing_id, _price = await _zb2.create_zero_listing(
            db, full_business, user_id, (user or {}).get("username"), uuid, datetime, timezone)
        await db.businesses.update_one({"id": business_id}, {"$set": {"zero_listing_id": listing_id}})
        await db.plots.update_one({"id": plot_id}, {"$set": {"listing_id": listing_id, "business.zero_listing_id": listing_id}})
    except Exception as e:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(f"zero business auto-listing failed: {e}")

def create_ton_island_router(db):
    router = APIRouter(prefix="/api", tags=["ton-island"])

    async def get_user_identifiers(current_user):
        return await _helper_gui(db, current_user)

    # ---------- v2.1.5: tutorial-T3 auto-activation hook ----------
    async def _maybe_auto_activate_tutorial_t3(user_id, user_email, user_wallet):
        """One-shot auto-activation of the T3 reward chosen at the end of the
        tutorial. Triggered after a successful first business purchase.

        Idempotency:
          • Looks at user.tutorial_pending_t3_auto_activate — bails out if unset.
          • Counts REAL businesses for this user (tutorial!=true). If >1 the
            flag is cleared anyway (race-safety) but no buff is granted —
            this hook fires only on the FIRST real business.
        """
        try:
            from core.helpers import resolve_owner_keys, owner_businesses_query, get_user_filter
            from business_config import RESOURCE_TYPES
            from datetime import timedelta

            # Reload the user fresh to read the flag.
            u_query = {"$or": []}
            if user_id:
                u_query["$or"].append({"id": user_id})
            if user_email:
                u_query["$or"].append({"email": user_email})
            if user_wallet:
                u_query["$or"].append({"wallet_address": user_wallet})
            if not u_query["$or"]:
                return
            u = await db.users.find_one(u_query, {"_id": 0})
            if not u:
                return
            pending = u.get("tutorial_pending_t3_auto_activate")
            if not pending:
                return

            # Count real (non-tutorial) businesses. Auto-activation fires on the
            # purchase of ANY business (not just the first) as long as the
            # tutorial-reward T3 is still pending in inventory.
            keys = await resolve_owner_keys(db, u.get("id") or u.get("wallet_address") or u.get("email"))
            biz_q = {**owner_businesses_query(keys), "tutorial": {"$ne": True}}
            biz_count = await db.businesses.count_documents(biz_q)
            if biz_count < 1:
                # No real business yet — keep the flag pending for the next purchase.
                return

            resources = u.get("resources", {}) or {}
            # Tutorial reward is stored in a SEPARATE key `<base>_tutorial`
            # (see routes/tutorial.py::_grant_t3_reward). Consume from that
            # slot so regular T3 inventory (sellable) stays untouched.
            tut_key = f"{pending}_tutorial"
            if int(resources.get(tut_key, 0) or 0) < 1:
                # User somehow no longer has the T3 — drop the flag silently.
                await db.users.update_one(get_user_filter(u), {"$unset": {"tutorial_pending_t3_auto_activate": ""}})
                return

            # Build the buff doc from RESOURCE_BUFFS catalog (same shape used by
            # the manual activate endpoint).
            from routes.buffs import RESOURCE_BUFFS  # local import to avoid circular
            buff = RESOURCE_BUFFS.get(pending)
            if not buff:
                await db.users.update_one(get_user_filter(u), {"$unset": {"tutorial_pending_t3_auto_activate": ""}})
                return

            now = datetime.now(timezone.utc)
            expires = now + timedelta(days=buff["duration_days"])
            new_buff = {
                "resource_id": pending,
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
            # Drop expired
            active_buffs = [
                b for b in active_buffs
                if b.get("expires_at") and (to_aware(b["expires_at"]) or now) > now
            ]
            # If the user already has this exact T3 active (corner-case), don't double up.
            if any(b.get("resource_id") == pending for b in active_buffs):
                await db.users.update_one(get_user_filter(u), {"$unset": {"tutorial_pending_t3_auto_activate": ""}})
                return
            active_buffs.append(new_buff)

            await db.users.update_one(
                get_user_filter(u),
                {
                    "$inc": {f"resources.{pending}_tutorial": -1},
                    "$set": {"active_resource_buffs": active_buffs},
                    "$unset": {"tutorial_pending_t3_auto_activate": ""},
                },
            )
            logger.info(f"Tutorial T3 auto-activated for user {u.get('username')}: {pending}")
        except Exception as e:
            logger.warning(f"_maybe_auto_activate_tutorial_t3 failed: {e}")


    @router.get("/config")
    async def get_app_config():
        """Get application configuration"""
        deposit_address = ""

        # PRIORITY 1: Check distribution smart contract address first
        contract_settings = await db.admin_settings.find_one({"type": "distribution_contract"}, {"_id": 0})
        if contract_settings and contract_settings.get("contract_address"):
            deposit_address = contract_settings.get("contract_address", "")

        # PRIORITY 2: Fallback to admin_wallets (direct wallet addresses)
        if not deposit_address:
            admin_wallet = await db.admin_wallets.find_one({}, {"_id": 0, "address": 1})
            deposit_address = admin_wallet.get("address", "") if admin_wallet else ""

        # PRIORITY 3: Fallback to game_settings
        if not deposit_address:
            game_settings = await db.game_settings.find_one({"type": "ton_wallet"}, {"_id": 0})
            if game_settings:
                deposit_address = game_settings.get("receiver_address", "") or game_settings.get("receiver_address_display", "")

        return {
            "support_telegram": os.environ.get("SUPPORT_TELEGRAM", "https://telegram.me/support"),
            "deposit_address": deposit_address,
            "businesses": {k: {
                "name": v["name"],
                "tier": v["tier"],
                "icon": v["icon"],
                "produces": v["produces"],
                "consumes": get_consumption_breakdown(k, 1),
                "is_patron": v.get("is_patron", False),
                "patron_type": v.get("patron_type"),
                "description": v["description"],
                "base_production": get_production(k, 1),
            } for k, v in BUSINESSES.items()},
            "tier_taxes": TIER_TAXES,
            "resource_weights": RESOURCE_WEIGHTS,
            "zones": ZONES,
            "patron_bonuses": PATRON_BONUSES,
        }

    @router.get("/island")
    async def get_ton_island():
        """Get GRAM Island map data"""
        # The game runs on the NEW city map: if the database still has the old island,
        # switch right now (once, locked across processes) before answering.
        try:
            from city_switch import ensure_new_city_map
            await ensure_new_city_map(db)
        except Exception as _se:
            logger.error(f"city map switch: {_se}")
        # Check if island exists in DB
        island = await db.islands.find_one({"id": "ton_island"}, {"_id": 0})

        if not island:
            # Generate and store — a fresh database starts with the NEW city map
            from city_island import build_city_island
            island = build_city_island()
            await db.islands.insert_one(island.copy())

        # Merge ownership data from plots collection
        plots = await db.plots.find({"island_id": "ton_island", "archived": {"$ne": True}}, {"_id": 0}).to_list(None)
        from core.plots import prefer_owned
        plots_map = prefer_owned(plots)                     # a cell with 2 records: the owned one wins

        # Merge businesses data
        businesses = await db.businesses.find({"island_id": "ton_island"}, {"_id": 0, "storage": 0, "produced_total": 0}).to_list(None)
        businesses_map = {(b["x"], b["y"]): b for b in businesses}

        cells = island.get("cells", [])

        # Collect unique owner IDs to batch load avatars
        owner_ids = set()
        for cell in cells:
            x, y = cell["x"], cell["y"]
            plot = plots_map.get((x, y))
            if plot and plot.get("owner"):
                owner_ids.add(plot.get("owner"))

        # Load user avatars
        users_with_avatars = {}
        if owner_ids:
            users = await db.users.find(
                {"$or": [{"id": {"$in": list(owner_ids)}}, {"wallet_address": {"$in": list(owner_ids)}}]},
                {"_id": 0, "id": 1, "wallet_address": 1, "avatar": 1, "username": 1, "alliance_tag": 1}
            ).to_list(None)                       # every owner (was capped at 100 -> missing names)
            for u in users:
                users_with_avatars[u.get("id")] = u
                if u.get("wallet_address"):
                    users_with_avatars[u.get("wallet_address")] = u

        for cell in cells:
            x, y = cell["x"], cell["y"]
            plot = plots_map.get((x, y))
            if plot:
                cell["owner"] = plot.get("owner")
                # ALWAYS resolve the CURRENT username/avatar from user data so a
                # player who renames themselves in Settings shows their latest
                # name on the map (falls back to the denormalized value).
                owner_user = users_with_avatars.get(plot.get("owner"))
                cell["owner_username"] = (owner_user.get("username") if owner_user else None) or plot.get("owner_username")
                cell["owner_avatar"] = owner_user.get("avatar") if owner_user else plot.get("owner_avatar")
                cell["owner_alliance_tag"] = (owner_user or {}).get("alliance_tag")

            business = businesses_map.get((x, y))
            if business:
                biz_type = business.get("business_type", "")
                biz_level = business.get("level", 1)
                biz_config = resolve_business_config(biz_type)
                cell["business"] = {
                    "id": business.get("id"),
                    "type": biz_type,
                    "level": biz_level,
                    "tier": biz_config.get("tier", 1),
                    "icon": biz_config.get("icon", "🏢"),
                    "produces": biz_config.get("produces"),
                    "base_production": get_production(biz_type, biz_level),
                    "skin_group": business.get("skin_group") or "standard",
                    # state for the owner's status icons on the map
                    "durability": business.get("durability", 100),
                    "shift_ends_at": business.get("shift_ends_at"),
                    "work_status_reason": business.get("work_status_reason"),
                    "is_zero_business": bool(business.get("is_zero_business")),
                }

        # Count statistics
        owned = sum(1 for c in cells if c.get("owner"))
        with_business = sum(1 for c in cells if c.get("business"))

        island["stats"] = {
            "total_cells": len(cells),
            "owned_cells": owned,
            "available_cells": len(cells) - owned,
            "businesses": with_business,
        }

        return island

    @router.get("/island/cell/{x}/{y}")
    async def get_island_cell(x: int, y: int):
        """Get fresh data for a specific cell on GRAM Island"""
        # Get island
        island = await db.islands.find_one({"id": "ton_island"}, {"_id": 0})
        if not island:
            island = generate_ton_island_map()
            await db.islands.insert_one(island.copy())

        # Find cell
        cell = None
        for c in island["cells"]:
            if c["x"] == x and c["y"] == y:
                cell = c.copy()
                break

        if not cell:
            raise HTTPException(status_code=404, detail="Cell not found")

        # Get ownership data
        from core.plots import cell_plot
        plot = await cell_plot(db, "ton_island", x, y)        # the owned record first (never a stale free one)
        if plot and plot.get("owner"):
            cell["owner"] = plot.get("owner")
            cell["is_available"] = False  # Cell is owned, not available for purchase
            # Get fresh username + avatar from the user (settings name wins)
            owner_user = await db.users.find_one(
                {"$or": [{"id": plot.get("owner")}, {"wallet_address": plot.get("owner")}]},
                {"_id": 0, "avatar": 1, "username": 1, "alliance_tag": 1}
            )
            cell["owner_username"] = (owner_user.get("username") if owner_user else None) or plot.get("owner_username")
            cell["owner_avatar"] = owner_user.get("avatar") if owner_user else plot.get("owner_avatar")
            cell["owner_alliance_tag"] = (owner_user or {}).get("alliance_tag")

        # Get business data
        business = await db.businesses.find_one({"island_id": "ton_island", "x": x, "y": y}, {"_id": 0})
        if business:
            biz_type = business.get("business_type", "")
            biz_level = business.get("level", 1)
            biz_config = resolve_business_config(biz_type)
            cell["business"] = {
                "id": business.get("id"),
                "type": biz_type,
                "level": biz_level,
                "tier": biz_config.get("tier", 1),
                "icon": biz_config.get("icon", "🏢"),
                "produces": biz_config.get("produces"),
                "consumes": get_consumption_breakdown(biz_type, biz_level),
                "base_production": get_production(biz_type, biz_level),
            }
            # Level-0 (застолблённый) business: expose owner + marketplace lot so
            # other players can buy it directly from the map cell.
            if biz_level == 0 or business.get("is_zero_business"):
                cell["business"]["is_zero_business"] = True
                cell["business"]["owner_id"] = business.get("owner")
                _biz_owner_fresh = cell.get("owner_username") if (plot and business.get("owner") == plot.get("owner")) else None
                cell["business"]["owner_username"] = _biz_owner_fresh or business.get("owner_username") or cell.get("owner_username")
                _zlot = await db.land_listings.find_one(
                    {"business_id": business.get("id"), "is_zero_business": True, "status": "active"},
                    {"_id": 0, "id": 1, "price": 1},
                )
                if _zlot:
                    cell["business"]["zero_listing_id"] = _zlot.get("id")
                    cell["business"]["zero_price_ton"] = _zlot.get("price")
                    cell["business"]["zero_price_city"] = round(float(_zlot.get("price", 0) or 0) * 1000, 2)
        elif cell.get("pre_business"):
            # For pre-assigned businesses that haven't been purchased yet
            biz_type = cell["pre_business"]
            biz_config = resolve_business_config(biz_type)
            cell["business"] = {
                "type": biz_type,
                "level": 1,
                "tier": biz_config.get("tier", 1),
                "icon": biz_config.get("icon", "🏢"),
                "produces": biz_config.get("produces"),
                "consumes": get_consumption_breakdown(biz_type, 1),
                "base_production": get_production(biz_type, 1),
                "name": biz_config.get("name"),
            }

        return cell

    @router.post("/island/buy/{x}/{y}")
    async def buy_island_plot(x: int, y: int, current_user: User = Depends(get_current_user)):
        """
        Buy a plot on GRAM Island.
        Most plots come with pre-assigned businesses.
        Only empty plots (50 total) allow building later.

        Race-condition guard:
          • Cheap pre-checks (balance, limits) first to give clean error UX.
          • Plot insert is the ATOMIC CLAIM step — uses a unique partial index on
            (island_id, x, y) where owner is set. Two simultaneous buyers cannot
            both insert; the loser gets a DuplicateKeyError and a 409.
          • Funds are deducted ONLY after the claim succeeds. If any post-claim
            step fails we roll back the plot (and any inserted business).
        """
        # Get island
        island = await db.islands.find_one({"id": "ton_island"}, {"_id": 0})
        if not island:
            island = generate_ton_island_map()
            await db.islands.insert_one(island.copy())

        # Find cell
        cell = None
        for c in island["cells"]:
            if c["x"] == x and c["y"] == y:
                cell = c
                break

        if not cell:
            raise HTTPException(status_code=404, detail="Участок не найден")

        # Cheap pre-check (UX): if a doc already exists with an owner, bail early.
        # This is NOT the race guard — the unique index is. It just shortcuts the
        # common case so we don't even try to claim a sold plot.
        existing = await db.plots.find_one({"island_id": "ton_island", "x": x, "y": y, "owner": {"$type": "string"}})
        if existing:
            raise HTTPException(status_code=400, detail="Участок уже куплен")

        # Get user - primary lookup by id (Telegram Mini App users have neither
        # wallet_address nor email), with wallet/email as fallbacks.
        user = await db.users.find_one({"id": current_user.id}, {"_id": 0})
        if not user and current_user.wallet_address:
            user = await db.users.find_one({"id": current_user.id}, {"_id": 0})
        if not user and current_user.email:
            user = await db.users.find_one({"id": current_user.id}, {"_id": 0})

        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")

        # Tutorial gate: while the tutorial is active, ONLY the reserved tutorial
        # plot may be purchased. Any other plot is rejected. The fake_buy_plot
        # step uses a separate /tutorial/fake-buy-plot endpoint, so this check
        # blocks the real /island/buy path entirely during tutorial.
        if user.get("tutorial_active"):
            raise HTTPException(
                status_code=403,
                detail="Во время обучения покупка обычных участков недоступна. Завершите обучение и попробуйте снова.",
            )

        # ── Presale gate (source of truth) — applied BEFORE the Level-0 flow ──
        # A plot may be bought/staked ONLY if it belongs to the active presale
        # allowlist. Empty/absent presale => nothing buyable. Admins bypass.
        import presale_gate as _pg
        _is_admin_pg = bool(user.get("is_admin") or user.get("role") == "ADMIN")
        _allowed_pg, _btn_pg = await _pg.presale_allows(db, "ton_island", x, y, _is_admin_pg)
        if not _allowed_pg:
            raise HTTPException(status_code=423, detail={
                "code": "presale_locked",
                "message": _btn_pg or "Покупка недоступна",
                "button_text": _btn_pg,
            })

        # ── Level-0 onboarding gate (buy path) ──
        import zero_business as _zb
        _uids_buy = {user.get("id"), current_user.wallet_address, user.get("email")}
        if await _zb.has_zero_business(db, _uids_buy):
            raise HTTPException(status_code=423, detail={"code": "zero_locked", "message": "Для покупки новых бизнесов прокачайте свой бизнес до уровня 1"})
        _zero_stake_buy = bool(cell.get("pre_business")) and not cell.get("is_empty", False) and await _zb.can_stake_zero(db, user, _uids_buy)

        # Check plot limit - 3 plots max for regular users, unlimited for admins
        is_admin = user.get("is_admin", False) or user.get("role") == "ADMIN"

        # Per-zone trading schedule: block buying before the zone's open time.
        # Admins bypass so they can test/manage at any time.
        if not is_admin:
            sched_doc = await db.admin_settings.find_one({"type": "trading_schedule"}, {"_id": 0})
            zone_open = ((sched_doc or {}).get("zones") or {}).get(cell.get("zone"))
            if zone_open:
                try:
                    open_dt = datetime.fromisoformat(str(zone_open).replace("Z", "+00:00"))
                    if open_dt.tzinfo is None:
                        open_dt = open_dt.replace(tzinfo=timezone.utc)
                    if datetime.now(timezone.utc) < open_dt:
                        raise HTTPException(status_code=403, detail="trading_not_open")
                except HTTPException:
                    raise
                except Exception:
                    pass
            # New city map: the district must be open and the lot among those the admin put on sale
            # (the presale list above already decided WHICH lots are on sale; here only a closed district blocks)
            from city_districts import district_unlocked as _d_unlocked
            if not await _d_unlocked(db, cell):
                raise HTTPException(status_code=403, detail="district_closed")

        if not is_admin:
            # Count current plots owned by this user — skip None candidates so
            # legacy debris docs with owner:null don't inflate the count.
            user_id = user.get("id", str(user.get("_id")))
            owner_candidates = [v for v in (user_id, current_user.wallet_address, current_user.email) if v]
            current_plots = await db.plots.count_documents({
                "$or": [{"owner": v} for v in owner_candidates],
            }) if owner_candidates else 0
            # businesses per player: admin setting (owned + rented + rented out), default 3
            import rental as _rental
            max_plots = await _rental.max_businesses(db)
            current_plots = max(current_plots, await _rental.count_user_businesses(db, owner_candidates))
            if current_plots >= max_plots:
                raise HTTPException(status_code=400, detail="max_plots_reached")

        # Business limits (max 3 total, max 1 Tier-3) for non-admin buyers when cell has pre-business
        pre_business_check = cell.get("pre_business")
        is_empty_cell_check = cell.get("is_empty", False)
        if pre_business_check and not is_empty_cell_check:
            from core.helpers import check_business_purchase_limits as _cbpl_island
            buyer_ids_island = {user.get("id"), current_user.wallet_address, current_user.email}
            ok_b, err_b = await _cbpl_island(db, user, buyer_ids_island, pre_business_check)
            if not ok_b:
                raise HTTPException(status_code=400, detail=err_b)

        # Get price from cell (includes business price if pre-assigned)
        price_ton = cell.get("price_ton", cell.get("price", 5.0))
        price_city = cell.get("price_city", price_ton * 1000)  # 1 TON = 1000 $CITY
        if _zero_stake_buy:
            price_ton = 0.0
            price_city = 0.0

        # Balance is stored as balance_ton, convert to $CITY for comparison.
        # Spend BONUS funds first, then real balance.
        bonus_ton = float(user.get("bonus_balance", 0) or 0)
        real_ton = float(user.get("balance_ton", 0) or 0)
        from core.balance import total_available_ton as _tat, insufficient_detail as _insuf
        from core.notif_i18n import user_lang as _ul
        user_balance_city = _tat(user) * 1000

        if user_balance_city + 1e-6 < price_city:
            raise HTTPException(status_code=400, detail=_insuf(_ul(user), price_ton, _tat(user)))

        user_id = user.get("id", str(user.get("_id")))

        # Get pre-assigned business (if any)
        pre_business = cell.get("pre_business")
        is_empty = cell.get("is_empty", False)

        # ─── ATOMIC CLAIM: insert plot first; the unique index makes this race-safe ───
        plot_id = str(uuid.uuid4())
        plot = {
            "id": plot_id,
            "island_id": "ton_island",
            "x": x,
            "y": y,
            "zone": cell["zone"],
            "price_ton": price_ton,
            "price_city": price_city,
            "owner": user_id,
            "owner_username": user.get("username"),
            "owner_avatar": user.get("avatar"),
            "business": None,  # filled in after we (optionally) create the business
            "business_id": None,
            "is_empty": is_empty,
            "warehouses": [],
            "purchased_at": datetime.now(timezone.utc).isoformat()
        }
        # The city map keeps a FREE record for every slot: claim THAT record (a second record for the same cell
        # made the cell window answer «free» to its own owner — see core/plots.py). The conditional update is
        # the race guard here; the unique index on owned records still stands behind it.
        _free = await db.plots.find_one({"island_id": "ton_island", "x": x, "y": y, "owner": None,
                                         "archived": {"$ne": True}}, {"_id": 0, "id": 1})
        claimed_free = False
        if _free:
            plot_id = _free["id"]
            plot["id"] = plot_id
            try:
                _r = await db.plots.update_one({"id": plot_id, "owner": None}, {"$set": {k: v for k, v in plot.items() if k != "id"}})
            except Exception as e:
                from pymongo.errors import DuplicateKeyError
                if isinstance(e, DuplicateKeyError):
                    raise HTTPException(status_code=409, detail="Участок уже куплен")
                raise
            if not _r.modified_count:
                raise HTTPException(status_code=409, detail="Участок уже куплен")
            claimed_free = True
        else:
            try:
                await db.plots.insert_one(plot.copy())
            except Exception as e:
                # PyMongo raises DuplicateKeyError → wins-the-race semantics.
                from pymongo.errors import DuplicateKeyError
                if isinstance(e, DuplicateKeyError):
                    raise HTTPException(status_code=409, detail="Участок уже куплен")
                logger.error("plot claim insert failed for (%s,%s): %s", x, y, e)
                raise HTTPException(status_code=500, detail="Не удалось зарезервировать участок")

        async def _release_plot():
            """Undo the claim: a claimed free record becomes free again, an inserted one is deleted."""
            if claimed_free:
                await db.plots.update_one({"id": plot_id}, {"$set": {"owner": None, "owner_username": None, "owner_avatar": None,
                                                                    "business": None, "business_id": None},
                                                           "$unset": {"purchased_at": ""}})
            else:
                await db.plots.delete_one({"id": plot_id})

        business_data = None
        business_id = None
        try:
            # Create business if pre-assigned
            if pre_business and not is_empty:
                from ton_island import CITY_BUSINESSES
                biz_config = CITY_BUSINESSES.get(pre_business)
                if biz_config:
                    business_id = str(uuid.uuid4())
                    business_data = {
                        "id": business_id,
                        "type": pre_business,
                        "name": biz_config["name"],
                        "icon": biz_config["icon"],
                        "tier": biz_config["tier"],
                        "level": 1,
                        "monthly_income_ton": biz_config["monthly_income_ton"],
                        "monthly_income_city": biz_config["monthly_income_ton"] * 1000,
                        "built_at": datetime.now(timezone.utc).isoformat(),
                        "last_collection": datetime.now(timezone.utc).isoformat(),
                    }
                    full_business = {
                        "id": business_id,
                        "business_type": pre_business,
                        "name": biz_config["name"],
                        "icon": biz_config["icon"],
                        "tier": biz_config["tier"],
                        "level": 1,
                        "owner": user_id,
                        "owner_username": user.get("username"),
                        "plot_id": plot_id,
                        "island_id": "ton_island",
                        "x": x,
                        "y": y,
                        "zone": cell["zone"],
                        # its lot on the new city map (without it the old switch check re-ran the whole migration)
                        **({"city_island_id": "city_v1", "city_slot_id": cell["slot_id"], "district_id": cell.get("district"),
                            "footprint": {"w": cell.get("w", 1), "h": cell.get("h", 1)}} if cell.get("slot_id") is not None else {}),
                        # Auto-apply the STANDARD skin group on purchase. If the
                        # project has a standard skin for this business type it
                        # renders automatically (no manual selection needed).
                        "skin_group": "standard",
                        "durability": 100,
                        "is_active": True,
                        "pending_income": 0,
                        "total_income": 0,
                        "monthly_income_ton": biz_config["monthly_income_ton"],
                        "monthly_income_city": biz_config["monthly_income_ton"] * 1000,
                        "base_cost_ton": price_ton,
                        "storage": {"capacity": get_storage_capacity(pre_business, 1) or biz_config.get("storage_capacity", 100), "items": {}},
                        "workers": [],
                        "on_sale": False,
                        "built_at": datetime.now(timezone.utc).isoformat(),
                        "last_collection": datetime.now(timezone.utc).isoformat(),
                    }
                    if _zero_stake_buy:
                        from zero_lease import compute_expires_at as _cea
                        _exp = _cea()
                        full_business["level"] = 0
                        full_business["is_zero_business"] = True
                        full_business["zero_map_price"] = cell.get("price_ton", cell.get("price", 5.0))
                        full_business["expires_at"] = _exp
                        business_data["level"] = 0
                        business_data["is_zero_business"] = True
                        business_data["expires_at"] = _exp
                    await db.businesses.insert_one(full_business.copy())
                    # Embed business into plot doc and update its business_id
                    await db.plots.update_one(
                        {"id": plot_id},
                        {"$set": {"business": business_data, "business_id": business_id}},
                    )
                    # Keep user.businesses_owned consistent with db.businesses
                    await db.users.update_one({"id": user_id}, {"$addToSet": {"businesses_owned": business_id}, "$set": {"is_active_investor": True}})
                    if _zero_stake_buy:
                        # Level-0 (leased) business: mark it, grant its starter
                        # consumption, and put it up for sale at map_price × 1.2 —
                        # another player can buy it out until the owner upgrades
                        # it to level 1 (owner's decision; re-enabled after v2.3).
                        await db.plots.update_one({"id": plot_id}, {"$set": {"business.is_zero_business": True}})
                        await _zb.grant_zero_consumption(db, user_id, full_business.get("business_type"), business_id=business_id)
                        await _list_zero_business(db, full_business, user_id, user, business_id, plot_id)
        except Exception as e:
            # Rollback the plot claim on any business-creation failure so the
            # cell can be re-bought by someone else.
            logger.error("buy_island_plot post-claim failure (%s,%s): %s", x, y, e)
            try:
                if business_id:
                    await db.businesses.delete_one({"id": business_id})
                await _release_plot()
            except Exception:
                pass
            raise HTTPException(status_code=500, detail="Не удалось завершить покупку")

        # Deduct balance (only balance_ton, $CITY is derived) and record plot
        # ownership on the user document. Pushing to `plots_owned` is required
        # for the referral rally "active" flag and for promo activation bonus
        # detection (see promo_service.compute_referrals_leaderboard and
        # promo_service.maybe_pay_activation_bonus, both of which key off
        # `plots_owned` array length).
        # Deduct balance — bonus funds are spent FIRST, then real balance_ton.
        # ($CITY is derived from TON; 1 TON = 1000 $CITY.)
        user_filter = {"id": user.get("id") or current_user.id}
        from core.balance import debit_user_split as _split
        _deb = await _split(db, user_filter, price_ton, extra_update={"$push": {"plots_owned": plot_id}})
        if not _deb.get("ok"):
            # not enough money after all (spent in parallel): give the cell back, never keep it for free
            try:
                if business_id:
                    await db.businesses.delete_one({"id": business_id})
                    await db.users.update_one({"id": user_id}, {"$pull": {"businesses_owned": business_id}})
                await db.land_listings.delete_many({"business_id": business_id, "is_zero_business": True}) if business_id else None
                await _release_plot()
            except Exception:
                pass
            raise HTTPException(status_code=400, detail=_insuf(_ul(user), price_ton, _tat(user)))
        from_bonus, from_real = _deb["from_bonus"], _deb["from_real"]

        # Referral Rally: pay 1.5 TON bonus to referrer if active campaign & this
        # was the buyer's first plot. `maybe_pay_activation_bonus` is idempotent
        # (guarded by `referral_activation_paid` flag on the buyer).
        try:
            from promo_service import maybe_pay_activation_bonus
            await maybe_pay_activation_bonus(db, user_id)
        except Exception as _e:
            logger.debug(f"promo activation bonus (island buy) failed: {_e}")

        # Tax to treasury (5%)
        tax_ton = price_ton * 0.05
        tax_city = price_city * 0.05
        await db.admin_stats.update_one(
            {"type": "treasury"},
            {"$inc": {
                "land_tax": tax_ton, 
                "total_tax": tax_ton,
                "first_sale_revenue": price_ton,
                "total_plot_sales": 1,
                "plot_sales_income": price_ton
            }},
            upsert=True
        )

        # Record transaction for history
        business_name = ""
        if business_data:
            business_name = f" с бизнесом {business_data.get('icon', '')} {business_data.get('name', {}).get('ru', '')}"

        tx = {
            "id": str(uuid.uuid4()),
            "type": "land_purchase",
            "user_id": user_id,
            "amount_ton": -price_ton,
            "amount_city": -price_city,
            "tax_ton": tax_ton,
            "tax_city": tax_city,
            "plot_id": plot["id"],
            "plot_coords": f"[{x}, {y}]",
            "island_id": "ton_island",
            "description": f"Покупка участка [{x}, {y}]{business_name}",
            "status": "completed",
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await db.transactions.insert_one(tx)

        logger.info(f"Plot purchased: ({x},{y}) by {user.get('username')} for {price_ton} TON ({price_city} $CITY)")

        # Partner task tracking: a land/business purchase may complete conditions.
        try:
            from routes.partner_programs import check_partner_conditions
            await check_partner_conditions(db, user_id)
        except Exception as _e:
            logger.debug(f"check_partner_conditions (island buy) failed: {_e}")

        new_balance_city = user_balance_city - price_city
        new_balance_ton = new_balance_city / 1000

        # v2.1.5: post-purchase hook — auto-activate the tutorial-graduation
        # T3 buff (one-shot). Triggers only when:
        #   (a) the user has a pending T3 flagged by /tutorial/finish,
        #   (b) this purchase is their first REAL (non-tutorial) business,
        #   (c) they actually hold ≥1 of that T3 in inventory.
        # The flag is then unset so subsequent T3 purchases do NOT auto-activate.
        await _maybe_auto_activate_tutorial_t3(user_id, user.get("email"), current_user.wallet_address)

        return {
            "status": "purchased",
            "plot": plot,
            "business": business_data,
            "is_empty": is_empty,
            "is_zero_business": _zero_stake_buy,
            "new_balance_ton": new_balance_ton,
            "new_balance_city": new_balance_city
        }

    @router.post("/island/build/{x}/{y}")
    async def build_on_island(x: int, y: int, request: dict, current_user: User = Depends(get_current_user)):
        """
        Build a business on owned EMPTY plot only.
        Only Tier 1 and Tier 2 businesses can be built (Tier 3 zone is pre-filled).
        """
        business_type = request.get("business_type")
        if not business_type:
            raise HTTPException(status_code=400, detail="business_type is required")

        # Get plot
        from core.plots import cell_plot
        plot = await cell_plot(db, "ton_island", x, y)
        if not plot:
            raise HTTPException(status_code=404, detail="Участок не найден")

        # Check if plot is empty (only empty plots allow building)
        if not plot.get("is_empty", False):
            raise HTTPException(status_code=400, detail="На этом участке уже есть бизнес. Строительство разрешено только на пустых участках.")

        # Verify ownership — primary lookup by id (Telegram Mini App users have
        # neither wallet_address nor email), with wallet/email as fallbacks.
        user = await db.users.find_one({"id": current_user.id}, {"_id": 0})
        if not user and current_user.wallet_address:
            user = await db.users.find_one({"id": current_user.id}, {"_id": 0})
        if not user and current_user.email:
            user = await db.users.find_one({"id": current_user.id}, {"_id": 0})

        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")

        user_id = user.get("id", str(user.get("_id")))

        if plot["owner"] != user_id and plot["owner"] != current_user.wallet_address:
            raise HTTPException(status_code=403, detail="Это не ваш участок")

        if plot.get("business"):
            raise HTTPException(status_code=400, detail="На участке уже есть бизнес")

        # Get business config from new CITY_BUSINESSES
        from ton_island import CITY_BUSINESSES
        biz_config = CITY_BUSINESSES.get(business_type)
        if not biz_config:
            # Fallback to old BUSINESSES config
            biz_config = BUSINESSES.get(business_type)
            if not biz_config:
                raise HTTPException(status_code=400, detail="Неизвестный тип бизнеса")

        # Check tier - only Tier 1 and 2 allowed for building
        tier = biz_config.get("tier", 1)
        if tier == 3:
            raise HTTPException(
                status_code=400, 
                detail="Бизнесы Tier 3 нельзя строить. Все они уже размещены в зоне Ядро."
            )

        # Get build cost (same as purchase price for these businesses)
        build_cost_ton = biz_config.get("price_ton", biz_config.get("base_cost_ton", 10.0))
        build_cost_city = build_cost_ton * 1000

        # ── Presale gate (source of truth) — applied BEFORE the Level-0 flow ──
        import presale_gate as _pg
        _is_admin_pg = bool(user.get("is_admin") or user.get("role") == "ADMIN")
        _allowed_pg, _btn_pg = await _pg.presale_allows(db, "ton_island", x, y, _is_admin_pg)
        if not _allowed_pg:
            raise HTTPException(status_code=423, detail={
                "code": "presale_locked",
                "message": _btn_pg or "Покупка недоступна",
                "button_text": _btn_pg,
            })

        # ── Level-0 onboarding gate ──
        import zero_business as _zb
        _uids = {user_id, current_user.wallet_address, user.get("email")}
        if await _zb.has_zero_business(db, _uids):
            raise HTTPException(status_code=423, detail={"code": "zero_locked", "message": "Для покупки новых бизнесов прокачайте свой бизнес до уровня 1"})
        _zero_stake = await _zb.can_stake_zero(db, user, _uids)

        bonus_ton = float(user.get("bonus_balance", 0) or 0)
        real_ton = float(user.get("balance_ton", 0) or 0)

        if _zero_stake:
            build_level = 0
            paid_ton = 0.0
        else:
            build_level = 1
            paid_ton = build_cost_ton
            from core.balance import total_available_ton as _tat, insufficient_detail as _insuf
            from core.notif_i18n import user_lang as _ul
            if _tat(user) * 1000 + 1e-6 < build_cost_city:
                raise HTTPException(status_code=400, detail=_insuf(_ul(user), build_cost_ton, _tat(user)))

        business_id = str(uuid.uuid4())
        _biz_name = biz_config.get("name", {"en": business_type, "ru": business_type})
        _biz_icon = biz_config.get("icon", "🏢")
        _monthly_ton = biz_config.get("monthly_income_ton", 5.0)
        _now_iso = datetime.now(timezone.utc).isoformat()
        # Embedded plot summary
        business = {
            "id": business_id,
            "type": business_type,
            "name": _biz_name,
            "icon": _biz_icon,
            "tier": tier,
            "level": build_level,
            "monthly_income_ton": _monthly_ton,
            "monthly_income_city": _monthly_ton * 1000,
            "built_at": _now_iso,
            "last_collection": _now_iso,
        }
        # Authoritative business doc (db.businesses) — used by upgrade/market/income.
        full_business = {
            "id": business_id,
            "business_type": business_type,
            "name": _biz_name,
            "icon": _biz_icon,
            "tier": tier,
            "level": build_level,
            "owner": user_id,
            "owner_username": user.get("username"),
            "plot_id": plot["id"],
            "island_id": "ton_island",
            "x": x,
            "y": y,
            "zone": plot.get("zone", "residential"),
            "skin_group": "standard",
            "durability": 100,
            "is_active": True,
            "pending_income": 0,
            "total_income": 0,
            "monthly_income_ton": _monthly_ton,
            "monthly_income_city": _monthly_ton * 1000,
            "base_cost_ton": build_cost_ton,
            "storage": {"capacity": get_storage_capacity(business_type, max(1, build_level)) or biz_config.get("storage_capacity", 100), "items": {}},
            "workers": [],
            "on_sale": False,
            "built_at": _now_iso,
            "last_collection": _now_iso,
        }
        # its lot on the new city map (a record of the new map carries city_slot_id)
        if plot.get("city_slot_id") is not None:
            full_business.update({"city_island_id": "city_v1", "city_slot_id": plot["city_slot_id"],
                                  "district_id": plot.get("district"), "footprint": {"w": plot.get("w", 1), "h": plot.get("h", 1)}})
        if _zero_stake:
            from zero_lease import compute_expires_at as _cea
            _exp = _cea()
            full_business["is_zero_business"] = True
            full_business["zero_map_price"] = build_cost_ton
            full_business["expires_at"] = _exp
            business["is_zero_business"] = True
            business["expires_at"] = _exp
        await db.businesses.insert_one(full_business.copy())

        # Update plot with business
        await db.plots.update_one(
            {"id": plot["id"]},
            {"$set": {"business": business, "business_id": business_id, "is_empty": False}}
        )

        # Level-0 (leased) business: grant the daily consumption norm and put it
        # up for sale at map_price × 1.2 — another player can buy it out until the
        # owner upgrades it to level 1 (owner's decision; re-enabled after v2.3).
        if _zero_stake:
            await _zb.grant_zero_consumption(db, user_id, business_type, business_id=business_id)
            await _list_zero_business(db, full_business, user_id, user, business_id, plot["id"])

        # Deduct balance — bonus first, then real (skipped for a free level-0 claim)
        user_filter = {"id": user.get("id") or current_user.id}
        if paid_ton > 0:
            from core.balance import debit_user_split as _split
            _deb = await _split(db, user_filter, paid_ton)
            if not _deb.get("ok"):
                await db.businesses.delete_one({"id": business_id})
                raise HTTPException(status_code=400, detail=_insuf(_ul(user), paid_ton, _tat(user)))
        await db.users.update_one(user_filter, {"$addToSet": {"businesses_owned": business_id}, "$set": {"is_active_investor": True}})

        # Record transaction
        tx = {
            "id": str(uuid.uuid4()),
            "type": "business_build",
            "user_id": user_id,
            "amount_ton": -paid_ton,
            "amount_city": -paid_ton * 1000,
            "business_type": business_type,
            "plot_id": plot["id"],
            "plot_coords": f"[{x}, {y}]",
            "description": f"{'Застолбление' if _zero_stake else 'Строительство'} {_biz_icon} {_biz_name.get('ru', business_type)}",
            "status": "completed",
            "created_at": _now_iso
        }
        await db.transactions.insert_one(tx)

        new_balance_city = (bonus_ton + real_ton) * 1000 - paid_ton * 1000

        # Auto-activate the tutorial-graduation T3 buff (one-shot).
        await _maybe_auto_activate_tutorial_t3(user_id, user.get("email"), current_user.wallet_address)

        return {
            "status": "built",
            "business": business,
            "level": build_level,
            "is_zero_business": _zero_stake,
            "new_balance_ton": new_balance_city / 1000,
            "new_balance_city": new_balance_city
        }


    # Old build function removed, replaced with new one above
    @router.get("/island/buildable-businesses")
    async def get_buildable_businesses():
        """
        Get list of businesses that can be built on empty plots.
        Only Tier 1 and Tier 2 allowed (Tier 3 zone is fully occupied).
        """
        from ton_island import CITY_BUSINESSES, ton_to_city

        result = []
        for b_id, b in CITY_BUSINESSES.items():
            if b["tier"] in [1, 2]:  # Only Tier 1 and 2
                result.append({
                    "id": b_id,
                    "name": b["name"],
                    "icon": b["icon"],
                    "tier": b["tier"],
                    "price_ton": b["price_ton"],
                    "price_city": ton_to_city(b["price_ton"]),
                    "monthly_income_ton": b["monthly_income_ton"],
                    "monthly_income_city": ton_to_city(b["monthly_income_ton"]),
                })

        return {"businesses": result}



    return router
