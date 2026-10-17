"""City Market (backend/market_maker.py).

The seller-side money (tax, credits, referrals) is server._admin_buyout_apply_sale
and is covered by the live check; here a fake records what it would be asked.

    cd backend && python -m pytest tests/test_market_maker.py -q
"""
import asyncio
import datetime as dt

import pytest

mongomock_motor = pytest.importorskip("mongomock_motor")
import market_maker as mm  # noqa: E402


def run(c):
    return asyncio.run(c)


def ago(minutes):
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=minutes)).isoformat()


class FakeSale:
    def __init__(self):
        self.calls = []

    async def __call__(self, listing, units, buyer_nick, admin_name, **kw):
        self.calls.append({"listing": listing["id"], "units": units, **kw})
        return {"seller_received_ton": round(units * listing["price_per_unit"] * 0.9, 6)}


BASE_ENERGY = mm._base_ton("energy")          # 0.003 TON


async def _world(cfg=None, level=1, sellers=("s1",)):
    db = mongomock_motor.AsyncMongoMockClient()["mm"]
    for sid in sellers:
        await db.users.insert_one({"id": sid, "email": f"{sid}@x.io", "username": sid})
        await db.businesses.insert_one({"id": f"b-{sid}", "owner": sid, "level": level})
    await mm.save_config(db, {"newbie_buy_enabled": True, "real_buy_enabled": True, "daily_budget_ton": 1.0, **(cfg or {})})
    return db


async def _lot(db, lid, seller="s1", units=100, price_pct=70, age=60, res="energy"):
    await db.market_listings.insert_one({"id": lid, "seller_id": seller, "resource_type": res, "amount": units,
                                         "price_per_unit": round(mm._base_ton(res) * price_pct / 100, 6),
                                         "status": "active", "created_at": ago(age)})


def test_disabled_does_nothing():
    async def go():
        db = await _world()
        await mm.save_config(db, {"newbie_buy_enabled": False, "real_buy_enabled": False})
        await _lot(db, "l1")
        sale = FakeSale()
        out = await mm.run_buy_side(db, sale)
        assert sale.calls == [] and out["skipped"].get("disabled")
    run(go())


def test_buys_aged_cheap_lot_with_real_payout_for_level1_seller():
    async def go():
        db = await _world(level=1)
        await _lot(db, "l1", units=100, price_pct=70, age=60)
        sale = FakeSale()
        out = await mm.run_buy_side(db, sale)
        assert out["bought"] == 1 and sale.calls[0]["payout"] == "real"
        assert sale.calls[0]["skip_listing_update"] is True and sale.calls[0]["city_market"] is True
        lot = await db.market_listings.find_one({"id": "l1"})
        assert lot["status"] == "sold" and lot["sold_via"] == "city_market"
        inv = await mm.stock(db)
        assert inv["energy"]["amount"] == 100
        t = await db.mm_trades.find_one({"side": "buy"})
        assert t["reason"] == "aged_lot" and t["payout"] == "real"
    run(go())


def test_level0_only_seller_gets_bonus_payout():
    async def go():
        db = await _world(level=0)
        await _lot(db, "l1")
        sale = FakeSale()
        await mm.run_buy_side(db, sale)
        assert sale.calls[0]["payout"] == "bonus"
    run(go())


def test_mixed_level0_and_level1_is_real_owner_rule():
    async def go():
        db = await _world(level=0)
        await db.businesses.insert_one({"id": "b-up", "owner": "s1", "level": 2})
        await _lot(db, "l1")
        sale = FakeSale()
        await mm.run_buy_side(db, sale)
        assert sale.calls[0]["payout"] == "real"
    run(go())


def test_does_not_buy_young_or_expensive_lots():
    async def go():
        db = await _world()
        await db.transactions.insert_one({"tx_type": "market_purchase", "seller_id": "s1"})  # not a newbie
        await _lot(db, "young", age=5, price_pct=70)
        await _lot(db, "pricey", age=120, price_pct=95)
        sale = FakeSale()
        await mm.run_buy_side(db, sale)
        assert sale.calls == []
    run(go())


def test_newbie_first_lot_is_bought_quickly_up_to_10_units():
    async def go():
        db = await _world(level=0)
        await _lot(db, "first", units=40, price_pct=100, age=3)   # at table price, 3 minutes old
        sale = FakeSale()
        out = await mm.run_buy_side(db, sale)
        assert out["newbie"] == 1 and sale.calls[0]["units"] == 10
        lot = await db.market_listings.find_one({"id": "first"})
        assert lot["amount"] == 30 and lot["status"] == "active"   # rest stays for players
        # second lot of the same player is no longer a "first sale"
        await _lot(db, "second", units=5, price_pct=100, age=3)
        sale2 = FakeSale()
        await mm.run_buy_side(db, sale2)
        assert all(c["listing"] != "second" for c in sale2.calls)
    run(go())


def test_daily_budget_limits_real_payouts():
    async def go():
        # budget 0.06 TON at 0.0021/unit -> 28 units max
        db = await _world({"daily_budget_ton": 0.06})
        await _lot(db, "l1", units=100)
        sale = FakeSale()
        await mm.run_buy_side(db, sale)
        assert sale.calls[0]["units"] == 28
        sale2 = FakeSale()
        await mm.run_buy_side(db, sale2)                       # budget spent for today
        assert sale2.calls == []
    run(go())


def test_player_cap_counts_linked_accounts_as_one():
    async def go():
        db = await _world({"player_daily_cap_units": 50}, sellers=("a", "b"))
        await db.fingerprints.insert_many([{"user_id": "a", "visitor_id": "dev"}, {"user_id": "b", "visitor_id": "dev"}])
        await _lot(db, "la", seller="a", units=40)
        await _lot(db, "lb", seller="b", units=40)
        sale = FakeSale()
        await mm.run_buy_side(db, sale)
        assert sum(c["units"] for c in sale.calls) == 50       # one device -> one cap
    run(go())


def test_stock_cap():
    async def go():
        db = await _world({"inventory_cap_units": 30})
        await _lot(db, "l1", units=100)
        sale = FakeSale()
        await mm.run_buy_side(db, sale)
        assert sale.calls[0]["units"] == 30
    run(go())


def test_one_player_share_limit():
    async def go():
        db = await _world({"max_player_share_pct": 50, "share_min_volume_ton": 0.0}, sellers=("big", "small"))
        await db.transactions.insert_many([{"tx_type": "market_purchase", "seller_id": s} for s in ("big", "small")])
        await _lot(db, "lbig", seller="big", units=100)
        await _lot(db, "lsmall", seller="small", units=10, age=30.5)
        sale = FakeSale()
        out = await mm.run_buy_side(db, sale)
        # the first (only) seller of the day would be 100 % -> skipped by the share rule
        assert out["skipped"].get("player_share", 0) >= 1
    run(go())


def test_sell_side_lists_only_own_stock_at_markup_and_tracks_player_buys():
    async def go():
        db = await _world({"sell_markup_pct": 30})
        await mm._stock_add(db, "energy", 80, 0.168)
        out = await mm.run_sell_side(db)
        assert out["created"] == 1
        lot = await db.market_listings.find_one({"seller_id": mm.CITY_MARKET_ID})
        assert lot["amount"] == 80 and lot["is_city_market"] and lot["is_bot"]       # whole stock listed
        assert abs(lot["price_per_unit"] - BASE_ENERGY * 1.3) < 1e-12
        # a player buys 20 from it
        await db.market_listings.update_one({"id": lot["id"]}, {"$inc": {"amount": -20}})
        await mm.on_player_bought(db, lot, 20, 20 * lot["price_per_unit"], "buyer1")
        assert (await mm.stock(db))["energy"]["amount"] == 60
        await mm.run_sell_side(db)
        assert (await db.market_listings.find_one({"id": lot["id"]}))["amount"] == 60
        # no stock -> lot removed
        await mm._stock_remove(db, "energy", 60)
        await mm.run_sell_side(db)
        assert (await db.market_listings.find_one({"id": lot["id"]}))["status"] == "cancelled"
    run(go())


def test_never_buys_its_own_or_admin_bot_lots():
    async def go():
        db = await _world()
        await db.market_listings.insert_many([
            {"id": "own", "seller_id": mm.CITY_MARKET_ID, "is_bot": True, "resource_type": "energy", "amount": 10,
             "price_per_unit": 0.001, "status": "active", "created_at": ago(999)},
            {"id": "admin", "seller_id": "BOT_ADMIN", "is_bot": True, "resource_type": "energy", "amount": 10,
             "price_per_unit": 0.001, "status": "active", "created_at": ago(999)}])
        sale = FakeSale()
        await mm.run_buy_side(db, sale)
        assert sale.calls == []
    run(go())


def test_config_validation():
    async def go():
        db = await _world()
        for bad in ({"buy_discount_pct": 120}, {"daily_budget_ton": -1}, {"resources": ["unobtainium"]},
                    {"nope": 1}, {"price_overrides": {"energy": {"buy_city": 9, "sell_city": 4}}},
                    {"price_overrides": {"energy": {"buy_city": -1}}}):
            with pytest.raises(Exception):
                await mm.save_config(db, bad)
    run(go())


def test_analytics_shape_and_numbers():
    async def go():
        db = await _world()
        await _lot(db, "l1", units=100)
        await mm.run_buy_side(db, FakeSale())
        await mm.run_sell_side(db)
        lot = await db.market_listings.find_one({"seller_id": mm.CITY_MARKET_ID})
        await mm.on_player_bought(db, lot, 10, 10 * lot["price_per_unit"], "buyer1")
        a = await mm.analytics(db, 7)
        t = a["totals"]
        assert t["bought_units"] == 100 and t["sold_units"] == 10
        assert t["unique_sellers"] == 1 and t["unique_buyers"] == 1
        assert a["liquidity"]["current"]["sold_to_city"] == 1
        assert any(r["resource"] == "energy" and r["stock_units"] == 90 for r in a["resources"])
        assert len(a["series"]) == 7
    run(go())


# ───────────── seller types (level-0 sellers cannot choose a price) ─────────────
def test_level0_seller_later_lots_bought_at_system_price_to_bonus():
    async def go():
        db = await _world(level=0)
        await db.transactions.insert_one({"tx_type": "market_purchase", "seller_id": "s1"})   # already sold once
        await _lot(db, "auto", units=40, price_pct=100, age=35)        # system price = table price, 35 min old
        sale = FakeSale()
        out = await mm.run_buy_side(db, sale)
        assert out.get("auto_price") == 1 and sale.calls[0]["payout"] == "bonus"
        assert sale.calls[0]["units"] == 40                              # whole lot, not the newbie 10
        t = await db.mm_trades.find_one({"side": "buy"})
        assert t["reason"] == "auto_price"
    run(go())


def test_level0_auto_price_waits_for_players_first():
    async def go():
        db = await _world(level=0)
        await db.transactions.insert_one({"tx_type": "market_purchase", "seller_id": "s1"})
        await _lot(db, "young", units=40, price_pct=100, age=10)        # < auto_price_delay_min (30)
        sale = FakeSale()
        await mm.run_buy_side(db, sale)
        assert sale.calls == []
    run(go())


def test_mixed_seller_at_forced_price_is_not_bought_after_first_sale():
    """Level 0 + level 1+: price is forced to the system price but the payout would
    be real money — the City Market must not buy at 100 %."""
    async def go():
        db = await _world(level=0)
        await db.businesses.insert_one({"id": "b-up", "owner": "s1", "level": 1})
        await db.transactions.insert_one({"tx_type": "market_purchase", "seller_id": "s1"})
        await _lot(db, "forced", units=40, price_pct=100, age=120)
        sale = FakeSale()
        await mm.run_buy_side(db, sale)
        assert sale.calls == []
    run(go())


def test_level1_seller_is_never_bought_at_full_price():
    async def go():
        db = await _world(level=1)
        await db.transactions.insert_one({"tx_type": "market_purchase", "seller_id": "s1"})
        await _lot(db, "full", units=40, price_pct=100, age=120)
        sale = FakeSale()
        await mm.run_buy_side(db, sale)
        assert sale.calls == []
    run(go())


def test_newbie_guarantee_follows_the_admin_system_price():
    """If the admin raises the market price, a level-0 lot at that system price
    still counts — the rule uses core/pricing.py, not the table price."""
    async def go():
        db = await _world(level=0)
        await db.market_prices.insert_one({"type": "current", "prices": {"energy": 4.0}})   # table = 3.0
        await db.market_listings.insert_one({"id": "up", "seller_id": "s1", "resource_type": "energy", "amount": 10,
                                             "price_per_unit": 0.004, "status": "active", "created_at": ago(5)})
        sale = FakeSale()
        out = await mm.run_buy_side(db, sale)
        assert out["newbie"] == 1
    run(go())


# ───────────── which resources are bought / sold ─────────────
def test_buy_list_controls_what_is_bought():
    async def go():
        db = await _world({"buy_resources": ["biomass"]})
        await _lot(db, "e", res="energy")
        await _lot(db, "b", res="biomass")
        sale = FakeSale()
        await mm.run_buy_side(db, sale)
        assert [c["listing"] for c in sale.calls] == ["b"]
    run(go())


def test_sell_list_controls_what_is_listed():
    async def go():
        db = await _world({"sell_resources": ["biomass"]})
        await mm._stock_add(db, "energy", 50, 0.1)
        await mm._stock_add(db, "biomass", 50, 0.1)
        await mm.run_sell_side(db)
        listed = {l["resource_type"] async for l in db.market_listings.find({"seller_id": mm.CITY_MARKET_ID, "status": "active"})}
        assert listed == {"biomass"}
        # removing a resource from the sell list takes its lot down
        await mm.save_config(db, {"sell_resources": []})
        await mm.run_sell_side(db)
        assert await db.market_listings.count_documents({"seller_id": mm.CITY_MARKET_ID, "status": "active"}) == 0
    run(go())


def test_any_resource_tier_can_be_enabled_and_lists_are_validated():
    async def go():
        db = await _world()
        cfg = await mm.save_config(db, {"buy_resources": ["energy", "neuro_core"], "sell_resources": ["energy"]})
        assert cfg["buy_resources"] == ["energy", "neuro_core"]
        with pytest.raises(Exception):
            await mm.save_config(db, {"buy_resources": ["nope"]})
    run(go())


def test_legacy_shared_resources_setting_still_works():
    async def go():
        db = mongomock_motor.AsyncMongoMockClient()["mm_legacy"]
        await db.admin_settings.insert_one({"type": "market_maker", "resources": ["quartz"]})
        cfg = await mm.get_config(db)
        assert cfg["buy_resources"] == ["quartz"] and cfg["sell_resources"] == ["quartz"]
    run(go())



# ───────────── switches, prices, newbie cap ─────────────
def test_newbie_switch_off_keeps_real_buys():
    async def go():
        db = await _world({"newbie_buy_enabled": False}, level=0)
        await _lot(db, "n", units=10, price_pct=100, age=60)
        sale = FakeSale()
        await mm.run_buy_side(db, sale)
        assert sale.calls == []                                   # level-0 lots not bought
    run(go())


def test_real_switch_off_keeps_newbie_buys():
    async def go():
        db = await _world({"real_buy_enabled": False}, level=1)
        await db.transactions.insert_one({"tx_type": "market_purchase", "seller_id": "s1"})
        await _lot(db, "r", units=10, price_pct=60, age=60)
        sale = FakeSale()
        await mm.run_buy_side(db, sale)
        assert sale.calls == []                                   # level 1+ lots not bought
    run(go())


def test_prices_from_static_table_price_and_manual_override():
    async def go():
        db = await _world({"buy_discount_pct": 20, "sell_markup_pct": 50})
        cfg = await mm.get_config(db)
        assert mm.prices_city(cfg, "energy") == (2.4, 4.5)        # table 3.0 → −20 % / +50 %
        cfg = await mm.save_config(db, {"price_overrides": {"energy": {"buy_city": 2.7}}})
        assert mm.prices_city(cfg, "energy") == (2.7, 4.5)        # manual buy price, auto sell
        # a level 1+ lot at 2.7 $CITY is now cheap enough
        await db.transactions.insert_one({"tx_type": "market_purchase", "seller_id": "s1"})
        await _lot(db, "p", units=10, price_pct=90, age=60)       # 2.7 $CITY
        sale = FakeSale()
        await mm.run_buy_side(db, sale)
        assert len(sale.calls) == 1
    run(go())


def test_per_newbie_daily_cap():
    async def go():
        # 0.0030 TON/unit at system price; cap 30 $CITY = 0.03 TON -> 10 units
        db = await _world({"per_newbie_daily_cap_city": 30}, level=0)
        await db.transactions.insert_one({"tx_type": "market_purchase", "seller_id": "s1"})
        await _lot(db, "big", units=100, price_pct=100, age=60)
        sale = FakeSale()
        await mm.run_buy_side(db, sale)
        assert sale.calls[0]["units"] == 10
        sale2 = FakeSale()
        await _lot(db, "more", units=100, price_pct=100, age=60)
        await mm.run_buy_side(db, sale2)
        assert sale2.calls == []                                  # this newbie's cap is used up
    run(go())


def test_legacy_percent_settings_are_converted():
    async def go():
        db = mongomock_motor.AsyncMongoMockClient()["mm_legacy2"]
        await db.admin_settings.insert_one({"type": "market_maker", "buy_price_pct": 70, "sell_price_pct": 140, "enabled": True})
        cfg = await mm.get_config(db)
        assert cfg["buy_discount_pct"] == 30 and cfg["sell_markup_pct"] == 40 and cfg["real_buy_enabled"] is True
    run(go())
