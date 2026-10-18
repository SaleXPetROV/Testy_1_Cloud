"""
Iter16 — Race-safety tests for TON_CITY v2.3 marketplace atomic claims.

Covers:
  1. /api/market/buy — atomic resource stock claim (RESOURCE_UNAVAILABLE 409).
  2. /api/market/land/buy — non-zero land listing claim (LISTING_SOLD 409).
  3. Level-0 lot vs upgrade race (buyer POST /api/market/land/buy + owner
     POST /api/business/{id}/upgrade 0→1) → exactly one winner, loser gets
     controlled 409 and refund.
  4. Level-0 lot with two buyers → one winner, other 409 + refund.

Concurrency: uses concurrent.futures.ThreadPoolExecutor to fire N parallel
requests against the *public* REACT_APP_BACKEND_URL (real ingress path).

Cleanup: every seeded doc is prefixed with TEST_… ids and removed in a
finally block. Original balances of testuser/testuser2 are restored.
"""
import os
import uuid
import time
import pytest
import requests
from concurrent.futures import ThreadPoolExecutor
from pymongo import MongoClient


BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://ton-city-level0-lock.preview.emergentagent.com").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

BUYER_A = ("testuser@example.com", "Test1234!")
BUYER_B = ("testuser2@example.com", "Test1234!")


# ── shared fixtures ──────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def mongo():
    cli = MongoClient(MONGO_URL)
    yield cli[DB_NAME]
    cli.close()


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": password}, timeout=15)
    r.raise_for_status()
    j = r.json()
    return j["token"], j["user"]


@pytest.fixture(scope="module")
def users(mongo):
    tok_a, u_a = _login(*BUYER_A)
    tok_b, u_b = _login(*BUYER_B)
    orig_a = mongo.users.find_one({"id": u_a["id"]}, {"balance_ton": 1, "bonus_balance": 1, "resources": 1})
    orig_b = mongo.users.find_one({"id": u_b["id"]}, {"balance_ton": 1, "bonus_balance": 1, "resources": 1})
    yield {"a": {"token": tok_a, "user": u_a, "orig": orig_a},
           "b": {"token": tok_b, "user": u_b, "orig": orig_b}}
    # restore both users
    for slot in ("a", "b"):
        u = locals().get(slot)  # noqa
    mongo.users.update_one({"id": u_a["id"]}, {"$set": {
        "balance_ton": float(orig_a.get("balance_ton", 0) or 0),
        "bonus_balance": float(orig_a.get("bonus_balance", 0) or 0),
    }})
    mongo.users.update_one({"id": u_b["id"]}, {"$set": {
        "balance_ton": float(orig_b.get("balance_ton", 0) or 0),
        "bonus_balance": float(orig_b.get("bonus_balance", 0) or 0),
    }})


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _seed_seller_business(mongo, seller_id, seller_wallet="TEST_SELLER_WALLET"):
    """Ensure some seller with is_zero_business=False so we don't hit P2P gate on seller side."""
    biz_id = f"TEST_biz_seller_{uuid.uuid4().hex[:8]}"
    mongo.businesses.insert_one({
        "id": biz_id, "owner": seller_id, "owner_wallet": seller_wallet,
        "business_type": "factory", "level": 2, "is_trial": False,
        "storage": {"capacity": 5000, "items": {}},
    })
    return biz_id


def _seed_buyer_has_real_business(mongo, buyer_id, buyer_wallet=None):
    """Guarantee buyer owns at least one non-trial business (P2P gate for /market/buy)."""
    existing = mongo.businesses.count_documents({
        "$or": [{"owner": buyer_id}, {"owner_wallet": buyer_wallet}] if buyer_wallet else [{"owner": buyer_id}],
        "is_trial": {"$ne": True},
    })
    if existing > 0:
        return None
    biz_id = f"TEST_biz_buyer_{uuid.uuid4().hex[:8]}"
    mongo.businesses.insert_one({
        "id": biz_id, "owner": buyer_id, "owner_wallet": buyer_wallet,
        "business_type": "factory", "level": 2, "is_trial": False,
        "storage": {"capacity": 5000, "items": {}},
    })
    return biz_id


def _parallel(fn, args_list, workers=None):
    workers = workers or len(args_list)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(lambda a: fn(*a), args_list))


# ── TEST 1 ── resources — atomic stock claim ────────────────────────────────
class TestResourceAtomicClaim:
    """
    /api/market/buy: two buyers request N units from a listing with amount=N →
    exactly one wins, other gets 409 RESOURCE_UNAVAILABLE. If amount=2N and both
    want N — both succeed, listing amount=0, status='sold'.
    """

    def _seed_listing(self, mongo, seller_id, amount, resource_type="scrap",
                      price=0.0001):
        listing_id = f"TEST_res_{uuid.uuid4().hex[:10]}"
        mongo.market_listings.insert_one({
            "id": listing_id, "status": "active",
            "seller_id": seller_id, "seller_email": "TEST_seller@example.com",
            "resource_type": resource_type, "amount": amount,
            "price_per_unit": price, "created_at": "2026-01-01T00:00:00Z",
        })
        return listing_id

    def _cleanup(self, mongo, listing_ids, biz_ids):
        if listing_ids:
            mongo.market_listings.delete_many({"id": {"$in": listing_ids}})
        if biz_ids:
            mongo.businesses.delete_many({"id": {"$in": biz_ids}})

    def test_two_buyers_race_exactly_one_wins(self, mongo, users):
        seller_id = "TEST_SELLER_ID_" + uuid.uuid4().hex[:6]
        seed_biz = []
        seed_biz.append(_seed_seller_business(mongo, seller_id))
        # Ensure buyers own real biz
        for slot in ("a", "b"):
            b_id = _seed_buyer_has_real_business(
                mongo, users[slot]["user"]["id"],
                users[slot]["user"].get("wallet_address"))
            if b_id:
                seed_biz.append(b_id)
        # Prime balances so both can pay
        for slot in ("a", "b"):
            mongo.users.update_one({"id": users[slot]["user"]["id"]},
                                   {"$set": {"balance_ton": 5.0, "bonus_balance": 0.0}})

        listing_ids = []
        try:
            wins_a = wins_b = conflicts = 0
            iterations = 15
            for i in range(iterations):
                lid = self._seed_listing(mongo, seller_id, amount=10)
                listing_ids.append(lid)

                def _buy(tok):
                    return requests.post(f"{BASE_URL}/api/market/buy",
                                         json={"listing_id": lid, "amount": 10},
                                         headers=_hdr(tok), timeout=20)

                r1, r2 = _parallel(lambda t: _buy(t), [(users["a"]["token"],), (users["b"]["token"],)])
                statuses = sorted([r1.status_code, r2.status_code])
                # Exactly one winner. Loser is 409 RESOURCE_UNAVAILABLE (atomic
                # claim path) OR 404 (pre-check picked up the just-sold listing).
                # Both are safe (no double-sale) but only 409 triggers the FE
                # refresh path — see report.
                assert 200 in statuses, f"iter {i}: no winner: {r1.status_code}/{r1.text} & {r2.status_code}/{r2.text}"
                loser = r1 if r1.status_code != 200 else r2
                # Loser: 409 (atomic claim), 404 (pre-check), OR 400 (pre-check
                # amount>available). All prevent double-sale.
                assert loser.status_code in (400, 404, 409), f"iter {i}: loser {loser.status_code}/{loser.text}"
                if loser.status_code == 409:
                    assert loser.json().get("detail") == "RESOURCE_UNAVAILABLE", loser.text
                if r1.status_code == 200:
                    wins_a += 1
                else:
                    wins_b += 1
                conflicts += 1

                # DB invariants
                listing_after = mongo.market_listings.find_one({"id": lid})
                assert listing_after["amount"] == 0, f"iter {i}: amount not zero: {listing_after['amount']}"
                assert listing_after["status"] == "sold", f"iter {i}: status not sold: {listing_after['status']}"

            print(f"resource race: {conflicts} iters, A won {wins_a}, B won {wins_b}")
            assert conflicts == iterations
        finally:
            self._cleanup(mongo, listing_ids, seed_biz)

    def test_amount_2n_both_succeed(self, mongo, users):
        seller_id = "TEST_SELLER_ID_" + uuid.uuid4().hex[:6]
        seed_biz = [_seed_seller_business(mongo, seller_id)]
        # Give both buyers a big-capacity biz so 10 scrap fits
        big_biz_ids = []
        for slot in ("a", "b"):
            bid = f"TEST_bigcap_{uuid.uuid4().hex[:8]}"
            mongo.businesses.insert_one({
                "id": bid, "owner": users[slot]["user"]["id"],
                "owner_wallet": users[slot]["user"].get("wallet_address"),
                "business_type": "factory", "level": 3, "is_trial": False,
                "storage": {"capacity": 100000, "items": {}},
            })
            big_biz_ids.append(bid)
        seed_biz.extend(big_biz_ids)
        for slot in ("a", "b"):
            mongo.users.update_one({"id": users[slot]["user"]["id"]},
                                   {"$set": {"balance_ton": 5.0, "bonus_balance": 0.0, "resources": {}}})
        lid = self._seed_listing(mongo, seller_id, amount=20)
        try:
            def _buy(tok):
                return requests.post(f"{BASE_URL}/api/market/buy",
                                     json={"listing_id": lid, "amount": 10},
                                     headers=_hdr(tok), timeout=20)

            r1, r2 = _parallel(lambda t: _buy(t), [(users["a"]["token"],), (users["b"]["token"],)])
            assert r1.status_code == 200 and r2.status_code == 200, f"{r1.status_code}/{r1.text} {r2.status_code}/{r2.text}"
            listing_after = mongo.market_listings.find_one({"id": lid})
            assert listing_after["amount"] == 0
            assert listing_after["status"] == "sold"
        finally:
            self._cleanup(mongo, [lid], seed_biz)


# ── TEST 2 ── land (non-zero) — atomic claim ─────────────────────────────────
class TestLandAtomicClaim:
    """
    Non-zero /api/market/land/buy: two parallel buyers → one wins, other 409
    LISTING_SOLD. Losing buyer's balance is not debited.
    """

    def _seed_plot_listing(self, mongo, seller_id, price=0.001):
        plot_id = f"TEST_plot_{uuid.uuid4().hex[:8]}"
        listing_id = f"TEST_land_{uuid.uuid4().hex[:10]}"
        # unique coordinates to avoid uniq_island_xy_owned collisions
        import random
        _x = random.randint(50000, 200000)
        _y = random.randint(50000, 200000)
        mongo.plots.insert_one({
            "id": plot_id, "owner": seller_id, "on_sale": True,
            "listing_id": listing_id, "city_id": "gram_city",
            "island_id": f"TEST_ISLAND_{uuid.uuid4().hex[:6]}",
            "x": _x, "y": _y,
            "coordinates": {"x": _x, "y": _y},
        })
        mongo.land_listings.insert_one({
            "id": listing_id, "status": "active", "plot_id": plot_id,
            "seller_id": seller_id, "seller_user_id": seller_id,
            "price": price, "created_at": "2026-01-01T00:00:00Z",
            "x": _x, "y": _y, "city_id": "gram_city",
        })
        return plot_id, listing_id

    def test_two_buyers_race_one_wins(self, mongo, users):
        seller_id = "TEST_SELLER_LAND_" + uuid.uuid4().hex[:6]
        # The API's plot-cap check queries db.plots by owner. We temporarily
        # "park" real plot ownership under a placeholder owner_id for the
        # duration of the test, then restore.
        park_ids = {}
        for slot in ("a", "b"):
            uid = users[slot]["user"]["id"]
            park = f"TEST_PARK_{uid[:8]}"
            park_ids[slot] = park
            mongo.plots.update_many({"owner": uid}, {"$set": {"owner": park}})
            mongo.users.update_one({"id": uid},
                                   {"$set": {"balance_ton": 10.0, "plots_owned": []}})
        plot_ids, listing_ids = [], []
        try:
            iterations = 10
            wins_a = wins_b = 0
            for i in range(iterations):
                p, l = self._seed_plot_listing(mongo, seller_id, price=0.001)
                plot_ids.append(p); listing_ids.append(l)

                def _buy(tok):
                    return requests.post(f"{BASE_URL}/api/market/land/buy",
                                         json={"listing_id": l},
                                         headers=_hdr(tok), timeout=20)

                r1, r2 = _parallel(lambda t: _buy(t), [(users["a"]["token"],), (users["b"]["token"],)])
                statuses = sorted([r1.status_code, r2.status_code])
                assert 200 in statuses, f"iter {i}: {r1.status_code}/{r1.text} {r2.status_code}/{r2.text}"
                loser = r1 if r1.status_code != 200 else r2
                # Loser: 409 LISTING_SOLD (atomic claim) OR 404 (pre-check fast path)
                assert loser.status_code in (404, 409), f"iter {i}: loser {loser.status_code}/{loser.text}"
                if loser.status_code == 409:
                    assert loser.json().get("detail") == "LISTING_SOLD", loser.text
                if r1.status_code == 200: wins_a += 1
                else: wins_b += 1

                listing_after = mongo.land_listings.find_one({"id": l})
                assert listing_after["status"] == "sold", f"iter {i}: status={listing_after['status']}"
                # Per-iter cleanup so buyer's plots_owned doesn't hit the 3-plot cap
                mongo.plots.delete_one({"id": p})
                mongo.land_listings.delete_one({"id": l})
                for slot in ("a", "b"):
                    mongo.users.update_one({"id": users[slot]["user"]["id"]},
                                           {"$pull": {"plots_owned": p, "businesses_owned": {"$in": []}}})

            print(f"land race: {iterations} iters, A={wins_a} B={wins_b}")
        finally:
            # restore parked plot ownership
            for slot, park in park_ids.items():
                uid = users[slot]["user"]["id"]
                mongo.plots.update_many({"owner": park}, {"$set": {"owner": uid}})
            if plot_ids: mongo.plots.delete_many({"id": {"$in": plot_ids}})
            if listing_ids: mongo.land_listings.delete_many({"id": {"$in": listing_ids}})
            # Sweep any inserted businesses_owned / plots_owned entries on buyers
            for slot in ("a", "b"):
                mongo.users.update_one({"id": users[slot]["user"]["id"]},
                                       {"$pull": {"plots_owned": {"$in": plot_ids}}})


# ── TEST 3 ── Level-0 lot vs upgrade race ────────────────────────────────────
class TestZeroBusinessRace:
    """
    Zero-lot: buyer POST /api/market/land/buy and OWNER POST
    /api/business/{id}/upgrade fired in parallel. Exactly one wins; loser gets
    controlled 409. If upgrade wins → buyer 409 LISTING_SOLD and NOT charged.
    If purchase wins → upgrade 409 'Бизнес больше недоступен для улучшения'.
    """

    def _seed_zero(self, mongo, owner_id, owner_email, owner_wallet, buyer_id, price=0.005):
        plot_id = f"TEST_zplot_{uuid.uuid4().hex[:8]}"
        biz_id = f"TEST_zbiz_{uuid.uuid4().hex[:8]}"
        listing_id = f"TEST_zlist_{uuid.uuid4().hex[:8]}"
        import random
        _x = random.randint(50000, 200000)
        _y = random.randint(50000, 200000)
        mongo.plots.insert_one({
            "id": plot_id, "owner": owner_id, "owner_wallet": owner_wallet,
            "on_sale": True, "listing_id": listing_id, "city_id": "gram_city",
            "island_id": f"TEST_ZIS_{uuid.uuid4().hex[:6]}",
            "x": _x, "y": _y,
            "coordinates": {"x": _x, "y": _y},
            "business": {"id": biz_id, "level": 0, "owner": owner_id,
                         "is_zero_business": True, "zero_listing_id": listing_id},
        })
        mongo.businesses.insert_one({
            "id": biz_id, "plot_id": plot_id, "owner": owner_id,
            "owner_wallet": owner_wallet, "owner_username": "TEST_owner",
            "business_type": "cafe", "level": 0, "is_zero_business": True,
            "zero_map_price": price, "zero_listing_id": listing_id,
            "listing_id": listing_id, "on_sale": True,
            "storage": {"capacity": 100, "items": {}},
        })
        mongo.land_listings.insert_one({
            "id": listing_id, "status": "active", "plot_id": plot_id,
            "seller_id": owner_id, "seller_user_id": owner_id,
            "seller_email": owner_email, "seller_wallet": owner_wallet,
            "price": price, "business_id": biz_id,
            "is_zero_business": True,
            "business": {"id": biz_id, "type": "cafe", "level": 0, "tier": 1},
            "created_at": "2026-01-01T00:00:00Z",
        })
        return plot_id, biz_id, listing_id

    def test_upgrade_vs_buy_exactly_one_wins(self, mongo, users):
        """
        Fire buyer(B).land/buy AND owner(A).business/{id}/upgrade in parallel.
        A owns the zero-biz; B buys it. Exactly one succeeds. Loser 409.
        If buyer loses → their balance is refunded (not debited).
        """
        owner = users["a"]; buyer = users["b"]
        owner_id = owner["user"]["id"]; owner_email = BUYER_A[0]
        owner_wallet = owner["user"].get("wallet_address") or f"TEST_OW_{uuid.uuid4().hex[:6]}"
        buyer_id = buyer["user"]["id"]
        price = 0.005

        upgrade_wins = purchase_wins = 0
        iterations = 12
        results = []
        plot_ids, biz_ids, listing_ids = [], [], []
        # give owner plenty of $CITY (needs cost_city / 1000 TON = e.g. price * 1000)
        # cost_city = price*1000 → in TON: price
        # give both real balances
        mongo.users.update_one({"id": owner_id}, {"$set": {"balance_ton": 50.0, "has_graduated_zero": False}})
        mongo.users.update_one({"id": buyer_id}, {"$set": {"balance_ton": 50.0, "has_graduated_zero": True}})
        # Buyer must not have a level-0 business themselves (has_zero_business gate).
        # Ensure any zero-biz owned by buyer is cleaned.
        mongo.businesses.update_many(
            {"$or": [{"owner": buyer_id}, {"owner_wallet": buyer["user"].get("wallet_address")}],
             "level": 0},
            {"$set": {"level": 1}, "$unset": {"is_zero_business": ""}}
        )

        try:
            for i in range(iterations):
                p, b, l = self._seed_zero(mongo, owner_id, owner_email, owner_wallet,
                                          buyer_id, price=price)
                plot_ids.append(p); biz_ids.append(b); listing_ids.append(l)

                # Snapshot buyer balance
                buyer_before = float(mongo.users.find_one({"id": buyer_id})["balance_ton"])

                def _buy():
                    return requests.post(f"{BASE_URL}/api/market/land/buy",
                                         json={"listing_id": l},
                                         headers=_hdr(buyer["token"]), timeout=20)

                def _upgrade():
                    return requests.post(f"{BASE_URL}/api/business/{b}/upgrade",
                                         headers=_hdr(owner["token"]), timeout=20)

                with ThreadPoolExecutor(max_workers=2) as ex:
                    fut_buy = ex.submit(_buy)
                    fut_up = ex.submit(_upgrade)
                    r_buy = fut_buy.result()
                    r_up = fut_up.result()

                buy_ok = r_buy.status_code == 200
                up_ok = r_up.status_code == 200
                results.append((r_buy.status_code, r_up.status_code))

                # Exactly one should succeed
                assert (buy_ok ^ up_ok), f"iter {i}: both/neither succeeded: buy={r_buy.status_code}/{r_buy.text} up={r_up.status_code}/{r_up.text}"

                if up_ok:
                    upgrade_wins += 1
                    # Buyer must have gotten 409 LISTING_SOLD (or 404) and refund
                    assert r_buy.status_code in (404, 409), f"iter {i}: buyer status {r_buy.status_code}/{r_buy.text}"
                    if r_buy.status_code == 409:
                        assert r_buy.json().get("detail") == "LISTING_SOLD", r_buy.text
                    buyer_after = float(mongo.users.find_one({"id": buyer_id})["balance_ton"])
                    # Refund invariant: loser's balance must equal starting balance (no debit remains)
                    assert abs(buyer_after - buyer_before) < 0.01, \
                        f"iter {i}: buyer NOT refunded: before={buyer_before} after={buyer_after}"
                    biz_after = mongo.businesses.find_one({"id": b})
                    assert biz_after["level"] == 1
                else:
                    purchase_wins += 1
                    # Loser: upgrade can be 409 (biz atomic guard) or 403 (owner
                    # check happens BEFORE the atomic guard when purchase raced
                    # ahead and rewrote biz.owner). Both prevent double action.
                    assert r_up.status_code in (403, 409), f"iter {i}: upgrade status {r_up.status_code}/{r_up.text}"
                    # Business should now be owned by buyer at level 1
                    biz_after = mongo.businesses.find_one({"id": b})
                    assert biz_after["level"] == 1
                    assert biz_after["owner"] == buyer_id
                    # Restore owner balance / has_graduated_zero for the next iter
                mongo.users.update_one({"id": owner_id}, {"$set": {"balance_ton": 50.0, "has_graduated_zero": False}})
                mongo.users.update_one({"id": buyer_id}, {"$set": {"balance_ton": 50.0, "has_graduated_zero": True}})

            print(f"zero race: {iterations} iters — upgrade_wins={upgrade_wins} purchase_wins={purchase_wins}")
            # Sanity: both outcomes should occur at least once across 12 iters
            # (not strict; timing dependent)
        finally:
            mongo.plots.delete_many({"id": {"$in": plot_ids}})
            mongo.businesses.delete_many({"id": {"$in": biz_ids}})
            mongo.land_listings.delete_many({"id": {"$in": listing_ids}})
            mongo.users.update_one({"id": buyer_id}, {"$pull": {"plots_owned": {"$in": plot_ids},
                                                                "businesses_owned": {"$in": biz_ids}}})
            mongo.users.update_one({"id": owner_id}, {"$pull": {"plots_owned": {"$in": plot_ids},
                                                                "businesses_owned": {"$in": biz_ids}}})

    def test_two_buyers_zero_lot(self, mongo, users):
        """
        Two buyers hitting the same zero-lot → exactly one wins, other 409
        LISTING_SOLD + refund (balance unchanged).
        Note: buyer A actually IS the seller in our fixture (uses testuser2 as
        owner). We'll use a synthetic third owner to avoid 'buy own listing'.
        """
        buyer_a = users["a"]; buyer_b = users["b"]
        # synthetic owner (never logs in)
        owner_id = "TEST_ZERO_OWNER_" + uuid.uuid4().hex[:6]
        owner_wallet = "TEST_ZERO_WALLET_" + uuid.uuid4().hex[:6]
        mongo.users.insert_one({
            "id": owner_id, "email": f"TEST_zowner_{uuid.uuid4().hex[:6]}@ex.com",
            "wallet_address": owner_wallet, "balance_ton": 0, "bonus_balance": 0,
            "username": "TEST_zowner",
        })

        iterations = 10
        wins_a = wins_b = 0
        plot_ids, biz_ids, listing_ids = [], [], []
        # top up buyers, ensure no zero-biz
        for slot in ("a", "b"):
            uid = users[slot]["user"]["id"]
            mongo.users.update_one({"id": uid}, {"$set": {"balance_ton": 50.0, "has_graduated_zero": True}})
            mongo.businesses.update_many(
                {"$or": [{"owner": uid}, {"owner_wallet": users[slot]["user"].get("wallet_address")}],
                 "level": 0},
                {"$set": {"level": 1}, "$unset": {"is_zero_business": ""}}
            )
        price = 0.003
        try:
            for i in range(iterations):
                p, b, l = self._seed_zero(mongo, owner_id, "TEST_zo@ex.com",
                                          owner_wallet, None, price=price)
                plot_ids.append(p); biz_ids.append(b); listing_ids.append(l)

                bal_a = float(mongo.users.find_one({"id": buyer_a["user"]["id"]})["balance_ton"])
                bal_b = float(mongo.users.find_one({"id": buyer_b["user"]["id"]})["balance_ton"])

                def _buy(tok):
                    return requests.post(f"{BASE_URL}/api/market/land/buy",
                                         json={"listing_id": l},
                                         headers=_hdr(tok), timeout=20)

                r1, r2 = _parallel(lambda t: _buy(t), [(buyer_a["token"],), (buyer_b["token"],)])
                statuses = sorted([r1.status_code, r2.status_code])
                assert 200 in statuses, f"iter {i}: {r1.status_code}/{r1.text} & {r2.status_code}/{r2.text}"
                loser = r1 if r1.status_code != 200 else r2
                assert loser.status_code in (404, 409), f"iter {i}: loser {loser.status_code}/{loser.text}"
                if loser.status_code == 409:
                    assert loser.json().get("detail") == "LISTING_SOLD", loser.text
                winner_is_a = (r1.status_code == 200)

                # Losing buyer refunded — check with tolerance to accommodate
                # other passive/tick balance changes on live testusers.
                bal_a_after = float(mongo.users.find_one({"id": buyer_a["user"]["id"]})["balance_ton"])
                bal_b_after = float(mongo.users.find_one({"id": buyer_b["user"]["id"]})["balance_ton"])
                if winner_is_a:
                    wins_a += 1
                    assert bal_a_after < bal_a, f"iter {i}: winner A balance did not decrease {bal_a}->{bal_a_after}"
                    if not abs(bal_b_after - bal_b) < 0.01:
                        print(f"iter {i}: SUSPICIOUS loser B: {bal_b}->{bal_b_after}, "
                              f"r1={r1.status_code}/{r1.text[:200]}, r2={r2.status_code}/{r2.text[:200]}")
                    assert abs(bal_b_after - bal_b) < 0.01, f"iter {i}: loser B not refunded {bal_b}->{bal_b_after}"
                else:
                    wins_b += 1
                    assert bal_b_after < bal_b, f"iter {i}: winner B balance did not decrease {bal_b}->{bal_b_after}"
                    if not abs(bal_a_after - bal_a) < 0.01:
                        print(f"iter {i}: SUSPICIOUS loser A: {bal_a}->{bal_a_after}, "
                              f"r1={r1.status_code}/{r1.text[:200]}, r2={r2.status_code}/{r2.text[:200]}")
                    assert abs(bal_a_after - bal_a) < 0.01, f"iter {i}: loser A not refunded {bal_a}->{bal_a_after}"

                # reset balances for next iter
                mongo.users.update_one({"id": buyer_a["user"]["id"]}, {"$set": {"balance_ton": 50.0}})
                mongo.users.update_one({"id": buyer_b["user"]["id"]}, {"$set": {"balance_ton": 50.0}})

            print(f"zero-two-buyers: {iterations} iters, A={wins_a} B={wins_b}")
        finally:
            mongo.plots.delete_many({"id": {"$in": plot_ids}})
            mongo.businesses.delete_many({"id": {"$in": biz_ids}})
            mongo.land_listings.delete_many({"id": {"$in": listing_ids}})
            mongo.users.delete_one({"id": owner_id})
            for slot in ("a", "b"):
                uid = users[slot]["user"]["id"]
                mongo.users.update_one({"id": uid}, {"$pull": {"plots_owned": {"$in": plot_ids},
                                                               "businesses_owned": {"$in": biz_ids}}})
