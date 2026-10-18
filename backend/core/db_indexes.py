"""Indexes for the hot queries added with quests, analytics, City Market,
leagues, City Pass, smart notifications, reconciliation and the economic tick.

Called once at startup in the background. Each index is created separately and
errors (already exists with other options, FerretDB limits…) are only logged,
so one problem never blocks the rest or the server start.
"""
import logging

logger = logging.getLogger(__name__)

INDEXES = {
    # economic tick (warehouse usage), market, City Market buy side
    "market_listings": [[("status", 1), ("is_bot", 1)], [("seller_id", 1), ("status", 1)],
                        [("status", 1), ("resource_type", 1), ("created_at", 1)], [("sold_at", 1)]],
    "businesses": [[("owner", 1)], [("owner_wallet", 1)], [("business_type", 1)]],
    "transactions": [[("tx_type", 1), ("status", 1)], [("tx_type", 1), ("seller_id", 1)],
                     [("status", 1), ("needs_review_at", -1)], [("user_id", 1), ("created_at", -1)]],
    "deposits": [[("status", 1), ("created_at", 1)]],
    "fingerprints": [[("user_id", 1)], [("visitor_id", 1)]],
    "notifications": [[("user_id", 1), ("created_at", -1)], [("user_id", 1), ("type", 1)]],
    "user_task_status": [[("user_id", 1), ("status", 1)]],
    # City Market
    "mm_trades": [[("ts", -1)], [("side", 1), ("user_id", 1)], [("day", 1)]],
    "mm_daily": [[("day", 1)]],
    "mm_inventory": [[("resource", 1)]],
    # smart notifications
    "smart_tg_queue": [[("deliver_after", 1)], [("user_id", 1), ("kind", 1), ("ref", 1)]],
    "market_price_snapshots": [[("ts", 1)]],
    "smart_notif_i18n": [[("key", 1), ("lang", 1)]],
    # City Pass / reconciliation
    "city_pass_claims": [[("season_id", 1)], [("user_id", 1), ("season_id", 1)]],
    "reconciliation_runs": [[("at", -1)]],
}


async def ensure_all(db) -> dict:
    created, failed = 0, 0
    for coll, specs in INDEXES.items():
        for keys in specs:
            try:
                await db[coll].create_index(keys)
                created += 1
            except Exception as e:
                failed += 1
                logger.debug(f"index {coll} {keys}: {e}")
    logger.info(f"🗂 indexes ensured: {created} ok, {failed} skipped")
    return {"ok": created, "skipped": failed}
