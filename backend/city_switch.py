"""Switch the game to the NEW city map — safely, once, from any process.

Called at startup (leader) AND by GET /api/island: whichever comes first moves every
business onto the new map (scripts/migrate_to_city_map: backup + auto-rollback, ids kept).
A lock document in the database makes sure only one process runs it; the others wait
for it to finish. Switch off with AUTO_CITY_MAP_MIGRATION=0.
"""
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)
_local = asyncio.Lock()
_done_cache = {"ok": False}


async def needs_switch(db) -> bool:
    # NB: the old island has NO "version" field -> this projection returns {} (falsy!), so test for None
    isl = await db.islands.find_one({"id": "ton_island"}, {"_id": 0, "id": 1, "version": 1})
    if isl is None:
        return False                     # a fresh database is created on the new map directly
    # Only the OLD map is a reason to migrate. On the new map a business without `city_slot_id` is just a lot
    # bought there before purchases recorded it: city_repair.link_unslotted links it to its slot. (Re-running the
    # migration for it moved businesses and wiped every other owner's lot — see city_repair.py.)
    return isl.get("version") != "city_v1"


async def ensure_new_city_map(db, wait: bool = True) -> bool:
    """True when the database is on the new map (after switching if needed)."""
    if os.environ.get("AUTO_CITY_MAP_MIGRATION", "1") == "0":
        return False
    if _done_cache["ok"]:
        return True
    async with _local:
        if not await needs_switch(db):
            _done_cache["ok"] = True
            return True
        now = datetime.now(timezone.utc)
        # cross-process lock: only the process that sets it runs the migration
        await db.admin_settings.update_one({"type": "city_map_switch_lock"}, {"$setOnInsert": {"type": "city_map_switch_lock", "until": ""}}, upsert=True)
        got = await db.admin_settings.update_one(
            {"type": "city_map_switch_lock", "$or": [{"until": ""}, {"until": {"$lt": now.isoformat()}}]},
            {"$set": {"until": (now + timedelta(minutes=10)).isoformat(), "pid": os.getpid()}})
        if got.modified_count:
            try:
                import argparse
                from scripts import migrate_to_city_map as mig
                logger.warning("🗺  Old map found — moving the city to the new map…")
                code = await mig.run(argparse.Namespace(apply=True, force=True, allow_unplaced=True, rollback=None,
                                                        layout=str(mig.LAYOUT), report="/tmp/city_map_migration_report.json"), db=db)
                logger.warning(f"🗺  New city map migration finished with code {code}")
            except Exception as e:
                logger.error(f"new city map migration failed: {e}")
            finally:
                await db.admin_settings.update_one({"type": "city_map_switch_lock"}, {"$set": {"until": ""}})
        elif wait:                                   # another process is switching: wait for it (max ~60 s)
            for _ in range(60):
                await asyncio.sleep(1)
                if not await needs_switch(db):
                    break
        ok = not await needs_switch(db)
        _done_cache["ok"] = ok
        return ok
