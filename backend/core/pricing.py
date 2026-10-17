"""ONE rule for the fixed system price of level-0 sellers.

Players who own a level-0 business cannot type a price: their lots go up at
this system price. It is the admin-configured market price (market_prices
"current", in $CITY) falling back to the table price, rounded so the UI shows
whole numbers: tier 1 per 10 units, tier 2/3 per unit. Used by the market
(server.py) and by the City Market (market_maker.py) — previously only
server.py knew it.
"""
from business_config import RESOURCE_TYPES


def round_level0_city(resource_type: str, price_city: float) -> float:
    meta = RESOURCE_TYPES.get(resource_type, {})
    try:
        tier = int(meta.get("tier", 1) or 1)
    except (TypeError, ValueError):
        tier = 1
    if tier == 1:
        return max(1, round(price_city * 10.0)) / 10.0      # whole per-10 price
    return float(max(1, round(price_city)))                 # whole per-unit price


async def level0_price_ton(db, resource_type: str) -> float:
    prices_doc = await db.market_prices.find_one({"type": "current"}, {"_id": 0, "prices": 1})
    stored = (prices_doc or {}).get("prices", {}) if prices_doc else {}
    base_city = RESOURCE_TYPES.get(resource_type, {}).get("base_price", 0.01)
    price_city = float(stored.get(resource_type, base_city) or base_city)
    return max(0.0001, round(round_level0_city(resource_type, price_city) / 1000.0, 6))
