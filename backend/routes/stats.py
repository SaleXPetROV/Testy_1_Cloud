"""Game-wide statistics endpoint.

Split out of server.py (was lines 6901-6948).
"""
from fastapi import APIRouter


def create_stats_router(db):
    router = APIRouter(prefix="/api", tags=["stats"])

    @router.get("/stats")
    async def get_game_stats():
        """Get overall game statistics (combined old collections + GRAM Island)."""
        owned_plots_old = await db.plots.count_documents({"is_available": False})
        total_businesses_old = await db.businesses.count_documents({})

        island = await db.islands.find_one({"id": "ton_island"})
        owned_plots_island = 0
        businesses_island = 0
        if island and 'cells' in island:
            for cell in island['cells']:
                if cell.get('owner'):
                    owned_plots_island += 1
                if cell.get('business'):
                    businesses_island += 1

        owned_plots = owned_plots_old + owned_plots_island
        total_businesses = total_businesses_old + businesses_island
        total_users = await db.users.count_documents({})

        pipeline = [
            {"$group": {"_id": None,
                        "real": {"$sum": {"$ifNull": ["$balance_ton", 0]}},
                        "bonus": {"$sum": {"$ifNull": ["$bonus_balance", 0]}}}},
        ]
        balance_result = await db.users.aggregate(pipeline).to_list(1)
        # TON in circulation = real balances + bonus TON balances.
        total_balance = 0
        if balance_result:
            total_balance = float(balance_result[0].get("real", 0) or 0) + float(balance_result[0].get("bonus", 0) or 0)

        admin_stats = await db.admin_stats.find_one({"type": "treasury"}, {"_id": 0})
        # Real number of plots = legacy `plots` collection + GRAM Island cells.
        # Previously this was `max(10000, …)` which forced the UI to always
        # display 10 000 even when only a few hundred plots existed.
        total_plots_old = await db.plots.count_documents({})
        island_cells_count = len(island.get('cells', [])) if island else 0
        total_plots = total_plots_old + island_cells_count

        return {
            "total_plots": total_plots,
            "owned_plots": owned_plots,
            "available_plots": total_plots - owned_plots,
            "total_businesses": total_businesses,
            "total_players": total_users,
            "total_volume_ton": max(0, round(total_balance, 2)),
            "treasury": admin_stats or {},
        }

    return router
