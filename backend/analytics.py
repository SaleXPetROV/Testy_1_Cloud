"""GRAM City — retention analytics.

Answers the question the retention plan starts with: *are the new quests and
onboarding actually keeping players?* It records two cheap things and computes
cohort retention (D1/D7/D30), the newcomer funnel and DAU from them.

What is recorded
----------------
1. `analytics_events` — discrete events (register, first_shift, first_sale, …).
   `quests.track()` already writes here; this module adds the auth events and a
   helper to read them back.
2. `user_active_days` — one small row per (user, MSK day) the user was active,
   written at most once per day per user (idempotent upsert). This is what
   cohort retention is computed from — far cheaper than scanning every event.

Nothing sensitive is stored: no passwords, wallet addresses, IPs or tokens —
only a user id, an event name and coarse props (onboarding group, channel).

Day boundaries use Moscow time (UTC+3), like the rest of the project.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))

_DB = None
_indexes_ready = False

# Newcomer funnel, in order. Event names match quests.fire()/quests.track().
FUNNEL = [
    ("register", "Регистрация"),
    ("first_business", "Открыл бизнес"),
    ("first_shift", "Запустил смену"),
    ("first_sale", "Первая продажа"),
    ("onboarding_completed", "Прошёл «Путь новичка»"),
]


def init(db) -> None:
    global _DB
    _DB = db


def _now_msk() -> datetime:
    return datetime.now(timezone.utc).astimezone(MSK)


def _day(dt: Optional[datetime] = None) -> str:
    return (dt or _now_msk()).date().isoformat()


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_msk_day(value: Any) -> Optional[str]:
    """Coerce a stored created_at/last_login (datetime or ISO string) to an MSK day."""
    if not value:
        return None
    dt = value
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(MSK).date().isoformat()


async def _ensure_indexes() -> None:
    global _indexes_ready
    if _indexes_ready or _DB is None:
        return
    _indexes_ready = True
    try:
        await _DB.user_active_days.create_index([("user_id", 1), ("day", 1)], unique=True)
        await _DB.user_active_days.create_index("day")
        await _DB.analytics_events.create_index([("event", 1), ("ts", 1)])
        await _DB.analytics_events.create_index([("user_id", 1), ("event", 1)])
    except Exception as e:
        logger.warning(f"analytics: index creation failed: {e}")


# ───────────────────────────── recording ─────────────────────────────
async def mark_active(user_id: str) -> None:
    """Record that `user_id` was active today (idempotent, one row per day)."""
    if _DB is None or not user_id:
        return
    await _ensure_indexes()
    day = _day()
    try:
        await _DB.user_active_days.update_one(
            {"user_id": user_id, "day": day},
            {"$setOnInsert": {"user_id": user_id, "day": day, "ts": _iso_now()}},
            upsert=True,
        )
    except Exception as e:
        logger.debug(f"analytics.mark_active failed: {e}")


def mark_active_bg(user_id: str) -> None:
    """Fire-and-forget mark_active for request handlers (never blocks the response)."""
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(mark_active(user_id))


async def track(user_id: str, event: str, **props) -> None:
    if _DB is None or not user_id:
        return
    await _ensure_indexes()
    try:
        await _DB.analytics_events.insert_one({"user_id": user_id, "event": event, "props": props, "ts": _iso_now()})
    except Exception as e:
        logger.debug(f"analytics.track failed: {e}")


# ───────────────────────────── reporting ─────────────────────────────
async def _registrations_by_day(start: str, group: Optional[str]) -> Dict[str, List[str]]:
    """{ msk_day: [user_id, …] } for users created in [start, today]."""
    q: Dict[str, Any] = {}
    if group and group != "all":
        q["onboarding_group"] = group
    users = await _DB.users.find(q, {"_id": 0, "id": 1, "created_at": 1}).to_list(200000)
    out: Dict[str, List[str]] = {}
    for u in users:
        d = _to_msk_day(u.get("created_at"))
        if d and d >= start and u.get("id"):
            out.setdefault(d, []).append(u["id"])
    return out


async def cohort_retention(days_back: int = 30, group: Optional[str] = None) -> Dict[str, Any]:
    """D1/D7/D30 retention per registration-day cohort.

    Retained on day N = the user has a `user_active_days` row N days after the
    day they registered. Login writes today's active-day row, so "registered and
    came back" is captured without extra plumbing.
    """
    await _ensure_indexes()
    today = _now_msk().date()
    start = (today - timedelta(days=days_back)).isoformat()
    cohorts = await _registrations_by_day(start, group)

    # active days per user, once, for everyone in scope
    all_ids = [uid for ids in cohorts.values() for uid in ids]
    active: Dict[str, set] = {}
    if all_ids:
        rows = await _DB.user_active_days.find(
            {"user_id": {"$in": all_ids}}, {"_id": 0, "user_id": 1, "day": 1}
        ).to_list(1000000)
        for r in rows:
            active.setdefault(r["user_id"], set()).add(r["day"])

    def retained(uids: List[str], reg_day: str, offset: int) -> int:
        target = (datetime.fromisoformat(reg_day).date() + timedelta(days=offset)).isoformat()
        return sum(1 for uid in uids if target in active.get(uid, set()))

    out_days = []
    totals = {"users": 0, "d1": 0, "d7": 0, "d30": 0, "d1_elig": 0, "d7_elig": 0, "d30_elig": 0}
    for day in sorted(cohorts.keys()):
        uids = cohorts[day]
        n = len(uids)
        reg = datetime.fromisoformat(day).date()
        age = (today - reg).days
        row: Dict[str, Any] = {"date": day, "users": n}
        for off, key in ((1, "d1"), (7, "d7"), (30, "d30")):
            if age >= off:                       # cohort is old enough to measure
                r = retained(uids, day, off)
                row[key] = r
                row[f"{key}_pct"] = round(100.0 * r / n, 1) if n else 0.0
                totals[key] += r
                totals[f"{key}_elig"] += n
            else:
                row[key] = None
                row[f"{key}_pct"] = None
        totals["users"] += n
        out_days.append(row)

    def pct(num: str, den: str) -> Optional[float]:
        d = totals[den]
        return round(100.0 * totals[num] / d, 1) if d else None

    return {
        "group": group or "all",
        "range_days": days_back,
        "cohorts": out_days,
        "overall": {
            "users": totals["users"],
            "d1_pct": pct("d1", "d1_elig"), "d7_pct": pct("d7", "d7_elig"), "d30_pct": pct("d30", "d30_elig"),
            "d1_n": totals["d1_elig"], "d7_n": totals["d7_elig"], "d30_n": totals["d30_elig"],
        },
    }


async def funnel(days_back: int = 30, group: Optional[str] = None) -> Dict[str, Any]:
    """Newcomer funnel for users registered in the window.

    "register" = users created in the window (from the users collection, so it
    works even for players who registered before analytics events existed). The
    later steps are counted from analytics_events / user state.
    """
    await _ensure_indexes()
    today = _now_msk().date()
    start = (today - timedelta(days=days_back)).isoformat()
    cohorts = await _registrations_by_day(start, group)
    ids = [uid for v in cohorts.values() for uid in v]
    n = len(ids)
    steps = [{"event": "register", "label": "Регистрация", "users": n,
              "pct": 100.0 if n else 0.0, "pct_prev": 100.0 if n else 0.0}]
    if not n:
        return {"group": group or "all", "range_days": days_back, "total": 0, "steps": steps}

    # business ownership is a state, the rest are events
    owners = set()
    if ids:
        id_set = set(ids)
        # businesses.owner may hold id / wallet / email; map any of them back to ids
        # same ownership rule as everywhere: owner OR owner_wallet may hold
        # the id, wallet, e-mail or username (core/helpers.owner_businesses_query)
        users = await _DB.users.find({"id": {"$in": ids}},
                                     {"_id": 0, "id": 1, "wallet_address": 1, "email": 1, "username": 1}).to_list(200000)
        key_to_id = {}
        for u in users:
            for k in (u.get("id"), u.get("wallet_address"), u.get("email"), u.get("username")):
                if k:
                    key_to_id[k] = u["id"]
        keys = list(key_to_id)
        for field in ("owner", "owner_wallet"):
            for val in await _DB.businesses.distinct(field, {field: {"$in": keys}}):
                mapped = key_to_id.get(val)
                if mapped in id_set:
                    owners.add(mapped)

    async def event_users(event: str) -> int:
        return len(set(await _DB.analytics_events.distinct("user_id", {"user_id": {"$in": ids}, "event": event})))

    prev = n
    for event, label in FUNNEL[1:]:
        if event == "first_business":
            c = len(owners)
        else:
            c = await event_users(event)
        steps.append({
            "event": event, "label": label, "users": c,
            "pct": round(100.0 * c / n, 1),
            "pct_prev": round(100.0 * c / prev, 1) if prev else 0.0,
        })
        prev = c or prev
    return {"group": group or "all", "range_days": days_back, "total": n, "steps": steps}


async def active_users(days_back: int = 14) -> Dict[str, Any]:
    await _ensure_indexes()
    today = _now_msk().date()
    start = (today - timedelta(days=days_back - 1)).isoformat()
    rows = await _DB.user_active_days.find({"day": {"$gte": start}}, {"_id": 0, "user_id": 1, "day": 1}).to_list(1000000)
    per_day: Dict[str, set] = {}
    for r in rows:
        per_day.setdefault(r["day"], set()).add(r["user_id"])
    series = [{"date": (today - timedelta(days=i)).isoformat(),
               "dau": len(per_day.get((today - timedelta(days=i)).isoformat(), set()))}
              for i in range(days_back - 1, -1, -1)]
    return {"range_days": days_back, "series": series, "today": series[-1]["dau"] if series else 0}


def create_analytics_router(db, get_current_admin) -> APIRouter:
    init(db)
    router = APIRouter(prefix="/api/admin/analytics", tags=["analytics"])

    @router.get("/retention")
    async def retention(days: int = 30, group: Optional[str] = None, _=Depends(get_current_admin)):
        if days < 1 or days > 120:
            raise HTTPException(status_code=400, detail="days must be 1..120")
        return await cohort_retention(days, group)

    @router.get("/funnel")
    async def get_funnel(days: int = 30, group: Optional[str] = None, _=Depends(get_current_admin)):
        if days < 1 or days > 120:
            raise HTTPException(status_code=400, detail="days must be 1..120")
        return await funnel(days, group)

    @router.get("/active")
    async def get_active(days: int = 14, _=Depends(get_current_admin)):
        if days < 1 or days > 90:
            raise HTTPException(status_code=400, detail="days must be 1..90")
        return await active_users(days)

    @router.get("/overview")
    async def overview(days: int = 30, group: Optional[str] = None, _=Depends(get_current_admin)):
        return {
            "retention": await cohort_retention(days, group),
            "funnel": await funnel(days, group),
            "active": await active_users(min(days, 14)),
        }

    return router
