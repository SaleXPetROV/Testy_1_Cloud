"""
Scheduler leader-election for multi-worker (gunicorn -w N) deployments.

Problem
-------
`background_tasks.economic_tick` (and other scheduled jobs) used to be started in
EVERY gunicorn worker independently. With `-w 4`, the same tick fired 4 times in
parallel, racing on the same business documents, which produced:

  * 4 identical low-resource Telegram notifications per business per threshold,
  * "stopped business" announcements duplicated 4×,
  * occasional double income / double tax on edge cases.

Solution
--------
Only the worker that holds a MongoDB lock document with `_id="scheduler_leader"`
is allowed to run the scheduler. Other workers idle.

The lock is renewed every 30 seconds; if the leader worker dies, the TTL index
expires the document after 90 seconds and the next worker that polls becomes the
new leader. So we trade a few seconds of background-task downtime on crash for a
guarantee that exactly ONE worker runs each tick.

Public API
----------
* `start_leader_loop(start_cb, stop_cb)` — call once at app startup.
  • Tries to grab the lock immediately. If we win, calls `start_cb()`.
  • Spawns a background task that re-grabs the lock every 30 s.
  • If we LOSE the lock (e.g. clock skew), `stop_cb()` is invoked.
* `is_leader()` — boolean, exposed for health endpoints.
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
import uuid
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

# In-process worker identity. Two gunicorn workers on the same host get
# different PIDs, so this is unique per worker.
_INSTANCE_ID = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"

# How often to renew / poll the lock. The TTL document expiry is 3×.
RENEW_SECONDS = 30
LOCK_TTL_SECONDS = 90

_db = None
_is_leader = False
_task: Optional[asyncio.Task] = None


def is_leader() -> bool:
    return _is_leader


async def _ensure_indexes(db) -> None:
    try:
        # TTL index on `expires_at` — Mongo auto-deletes a stale leader doc
        # within ~60 s of expiry, so the next poll can take over.
        await db.scheduler_locks.create_index("expires_at", expireAfterSeconds=0)
    except Exception as e:
        logger.warning(f"[scheduler-leader] could not create TTL index: {e}")


async def _try_acquire(db) -> bool:
    """Insert the lock doc or take it over if expired. Returns True if WE hold it."""
    now = datetime.now(timezone.utc)
    new_expiry = now + timedelta(seconds=LOCK_TTL_SECONDS)
    try:
        # Try to take the lock when it's missing OR expired OR already ours.
        res = await db.scheduler_locks.find_one_and_update(
            {
                "_id": "scheduler_leader",
                "$or": [
                    {"owner": _INSTANCE_ID},
                    {"expires_at": {"$lt": now}},
                ],
            },
            {"$set": {"owner": _INSTANCE_ID, "expires_at": new_expiry, "renewed_at": now}},
            upsert=False,
            return_document=False,
        )
        if res is not None:
            return True
        # Doc doesn't exist yet → try to insert atomically.
        try:
            await db.scheduler_locks.insert_one({
                "_id": "scheduler_leader",
                "owner": _INSTANCE_ID,
                "expires_at": new_expiry,
                "renewed_at": now,
            })
            return True
        except Exception:
            # Duplicate key → another worker beat us to it.
            return False
    except Exception as e:
        logger.warning(f"[scheduler-leader] acquire failed: {e}")
        return False


async def _release(db) -> None:
    try:
        await db.scheduler_locks.delete_one({"_id": "scheduler_leader", "owner": _INSTANCE_ID})
    except Exception:
        pass


async def _leader_loop(db, start_cb: Callable[[], Awaitable[None] | None],
                      stop_cb: Optional[Callable[[], Awaitable[None] | None]]):
    global _is_leader
    await _ensure_indexes(db)
    while True:
        try:
            won = await _try_acquire(db)
            if won and not _is_leader:
                _is_leader = True
                logger.info(f"[scheduler-leader] 👑 worker {_INSTANCE_ID} acquired lock — starting scheduler")
                try:
                    res = start_cb()
                    if asyncio.iscoroutine(res):
                        await res
                except Exception as e:
                    logger.error(f"[scheduler-leader] start_cb failed: {e}")
            elif not won and _is_leader:
                # We had it, but lost. Should be rare (e.g. paused for too long).
                _is_leader = False
                logger.warning(f"[scheduler-leader] ⚠ worker {_INSTANCE_ID} LOST lock — stopping scheduler")
                if stop_cb is not None:
                    try:
                        res = stop_cb()
                        if asyncio.iscoroutine(res):
                            await res
                    except Exception as e:
                        logger.error(f"[scheduler-leader] stop_cb failed: {e}")
        except Exception as e:
            logger.error(f"[scheduler-leader] loop error: {e}")
        await asyncio.sleep(RENEW_SECONDS)


def start_leader_loop(db, start_cb, stop_cb=None):
    """Kick off the leader-election loop. Safe to call multiple times — no-ops on subsequent calls."""
    global _db, _task
    if _task is not None:
        return
    _db = db
    _task = asyncio.create_task(_leader_loop(db, start_cb, stop_cb))


async def shutdown_leader():
    """Release the lock on graceful shutdown so the next worker can take over immediately."""
    if _db is not None and _is_leader:
        await _release(_db)
