"""Leaderboard endpoint. Split out of server.py (aggregate version)."""
from fastapi import APIRouter, Query


# tx_type values that count as "trading activity" across all user businesses
TRADING_TX_TYPES = ["trade_resource", "market_purchase"]


async def _compute_trading_volumes(db, user_ids: list) -> dict:
    """
    Aggregate per-user trading volume (sum of buys + sells in TON) and trades
    count from the `transactions` collection, across ALL businesses owned by
    the user. A single trade contributes to both the buyer and the seller.

    Returns mapping: identifier (wallet_address or user.id) -> {volume, count}
    """
    pipeline = [
        {
            "$match": {
                "tx_type": {"$in": TRADING_TX_TYPES},
                "amount_ton": {"$gt": 0},
            }
        },
        {
            "$project": {
                "participants": ["$from_address", "$to_address"],
                "amount_ton": 1,
            }
        },
        {"$unwind": "$participants"},
        {"$match": {"participants": {"$nin": [None, ""]}}},
        {
            "$group": {
                "_id": "$participants",
                "trading_volume": {"$sum": "$amount_ton"},
                "trades_count": {"$sum": 1},
            }
        },
    ]
    agg = await db.transactions.aggregate(pipeline).to_list(10000)
    return {
        row["_id"]: {
            "trading_volume": round(row.get("trading_volume", 0), 4),
            "trades_count": int(row.get("trades_count", 0)),
        }
        for row in agg
    }


async def _compute_business_counts(db) -> dict:
    """Number of businesses each user owns, taken from the SAME source the
    admin panel uses (the `businesses` collection keyed by `owner`). `owner`
    may be a user id OR a wallet address, so we return counts keyed by both.
    Returns mapping: owner (id or wallet) -> count."""
    pipeline = [
        {"$match": {"owner": {"$nin": [None, ""]}}},
        {"$group": {"_id": "$owner", "count": {"$sum": 1}}},
    ]
    agg = await db.businesses.aggregate(pipeline).to_list(20000)
    return {row["_id"]: int(row.get("count", 0)) for row in agg}


def create_leaderboard_router(db):
    router = APIRouter(prefix="/api", tags=["leaderboard"])

    @router.get("/leaderboard")
    async def get_leaderboard(
        sort_by: str = Query(
            "balance", pattern="^(balance|income|businesses|plots|trading)$"
        ),
        limit: int = Query(20, ge=1, le=100),
        me_id: str = Query(None),
    ):
        """Get top players ordered by chosen criterion.

        sort_by:
          - balance     : by FULL TON balance (real balance_ton + bonus_balance)
          - income      : by total_income
          - businesses  : by number of owned businesses
          - plots       : by number of owned plots
          - trading     : by total trading volume (sum of buys + sells across
                          ALL businesses) computed from transactions.
        """
        sort_field_map = {
            "balance": "balance_ton",
            "income": "total_income",
            "businesses": "businesses_count",
            "plots": "plots_count",
            "trading": "trading_volume",
        }
        sort_field = sort_field_map[sort_by]

        pipeline = [
            # Exclude B2B partners — they should not compete on the leaderboard.
            {"$match": {"b2b_is_partner": {"$ne": True}}},
            {
                "$project": {
                    "_id": 0,
                    "id": 1,
                    "username": 1,
                    "display_name": 1,
                    "avatar": 1,
                    "wallet_address": 1,
                    "level": 1,
                    # FULL balance = real (withdrawable) + bonus (in-game) TON,
                    # matching the balance the admin panel shows for a player.
                    "balance_ton": {
                        "$add": [
                            {"$ifNull": ["$balance_ton", 0]},
                            {"$ifNull": ["$bonus_balance", 0]},
                        ]
                    },
                    "total_income": {"$ifNull": ["$total_income", 0]},
                    "total_turnover": {"$ifNull": ["$total_turnover", 0]},
                    "plots_count": {"$size": {"$ifNull": ["$plots_owned", []]}},
                }
            }
        ]
        users = await db.users.aggregate(pipeline).to_list(1000)

        # Enrich with trading metrics (sum of trades by wallet_address OR id)
        volumes = await _compute_trading_volumes(db, [])
        # Business counts from the `businesses` collection (same source as admin)
        biz_counts = await _compute_business_counts(db)
        for u in users:
            keys = [u.get("wallet_address"), u.get("id")]
            tv = 0.0
            tc = 0
            bc = 0
            for k in keys:
                if not k:
                    continue
                if k in volumes:
                    tv += volumes[k]["trading_volume"]
                    tc += volumes[k]["trades_count"]
                if k in biz_counts:
                    bc += biz_counts[k]
            u["trading_volume"] = round(tv, 4)
            u["trades_count"] = tc
            u["businesses_count"] = bc

        # Sort and slice
        users.sort(key=lambda u: u.get(sort_field, 0) or 0, reverse=True)
        # Assign a 1-based rank to every user across the FULL sorted list.
        for i, u in enumerate(users):
            u["rank"] = i + 1
        players = users[:limit]

        # Resolve the current user's own row + rank (so the UI can show a pinned
        # "your position" bar when they're outside the visible top slice).
        me = None
        if me_id:
            for u in users:
                if u.get("id") == me_id or (u.get("wallet_address") and u.get("wallet_address") == me_id):
                    me = u
                    break

        return {
            "players": players,
            "leaderboard": players,  # backward compat
            "sort_by": sort_by,
            "total": len(users),
            "me": me,
        }

    return router
