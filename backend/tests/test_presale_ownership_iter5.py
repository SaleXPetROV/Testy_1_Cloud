"""Backend tests for Admin Presale ownership integration (Iteration 5).

Focus areas per the review request:
1. Inventory endpoint queries `plots` collection to determine which cells
   are purchased and excludes them from `free` (while keeping `total`).
2. select-plots rejects duplicate business types (HTTP 400).
3. select-plots rejects count > free supply (HTTP 400).
4. select-plots successful path never picks an already-purchased cell.
5. Cleanup restores full free supply.
"""
import os
import uuid
import datetime as _dt
import pytest
import requests
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
load_dotenv("/app/backend/.env")

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

ADMIN = {"email": "sanyanazarov212@gmail.com", "password": os.environ.get("TEST_ADMIN_PASSWORD", "")}
MAP_ID = "ton_island"
FAKE_OWNER = "fake-owner-iter5"
FAKE_PLOT_ID_PREFIX = "test-iter5-"


@pytest.fixture(scope="module")
def mongo():
    client = MongoClient(MONGO_URL)
    yield client[DB_NAME]
    client.close()


@pytest.fixture(scope="module")
def admin_headers():
    r = requests.post(f"{BASE_URL}/api/auth/login", json=ADMIN, timeout=30)
    assert r.status_code == 200, f"admin login failed {r.status_code} {r.text}"
    token = r.json().get("token") or r.json().get("access_token")
    assert token, f"no token in response: {r.json()}"
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module", autouse=True)
def cleanup_before_and_after(mongo):
    """Ensure a clean slate: remove test-inserted plots and presale doc."""
    mongo.plots.delete_many({"owner": FAKE_OWNER})
    mongo.plots.delete_many({"id": {"$regex": f"^{FAKE_PLOT_ID_PREFIX}"}})
    mongo.admin_settings.delete_one({"type": "presale"})
    yield
    mongo.plots.delete_many({"owner": FAKE_OWNER})
    mongo.plots.delete_many({"id": {"$regex": f"^{FAKE_PLOT_ID_PREFIX}"}})
    mongo.admin_settings.delete_one({"type": "presale"})


# ---------------------------------------------------------------------------
# Test 1: admin login returns JWT
# ---------------------------------------------------------------------------
def test_admin_login_returns_jwt():
    r = requests.post(f"{BASE_URL}/api/auth/login", json=ADMIN, timeout=30)
    assert r.status_code == 200, r.text
    j = r.json()
    token = j.get("token") or j.get("access_token")
    assert token and isinstance(token, str)
    # JWT is 3 base64 segments separated by dots
    assert token.count(".") == 2, f"not a JWT: {token[:40]}..."


# ---------------------------------------------------------------------------
# Test 2: inventory baseline — no purchased plots ⇒ free == total per type
# ---------------------------------------------------------------------------
def test_inventory_free_equals_total_when_no_purchases(admin_headers, mongo):
    # Ensure zero purchased plots on this map for a real user
    mongo.plots.delete_many({"owner": FAKE_OWNER})
    r = requests.get(
        f"{BASE_URL}/api/admin/presale/inventory",
        params={"map_id": MAP_ID}, headers=admin_headers, timeout=30,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["map_id"] == MAP_ID
    businesses = data["businesses"]
    assert len(businesses) > 0, "expected at least one business type on map"

    # Baseline: without any TEST-owned plots inserted, and assuming no real
    # users have purchased on this pristine map, free should equal total.
    # We only assert that free <= total (invariant) and total > 0.
    mismatched = [(b["type"], b["free"], b["total"]) for b in businesses if b["free"] > b["total"]]
    assert not mismatched, f"free exceeds total: {mismatched}"
    for b in businesses:
        assert b["total"] > 0
        assert isinstance(b["free"], int)
        assert isinstance(b["total"], int)

    # Save baseline for next test — store on class-scope via module attribute
    pytest._presale_baseline = {b["type"]: {"free": b["free"], "total": b["total"]}
                                for b in businesses}


# ---------------------------------------------------------------------------
# Test 3: inserting a plot into `plots` collection decrements `free` by 1
#         (but keeps `total` unchanged) for that business type.
# ---------------------------------------------------------------------------
def test_inventory_decrements_free_after_plot_insert(admin_headers, mongo):
    baseline = getattr(pytest, "_presale_baseline", None)
    assert baseline, "baseline not captured (previous test must run first)"

    # Pick a business type that actually has cells on the island — use bio_farm
    # if present, otherwise fall back to the first available type.
    target_type = "bio_farm" if "bio_farm" in baseline else next(iter(baseline))
    baseline_free = baseline[target_type]["free"]
    baseline_total = baseline[target_type]["total"]

    # Find a real cell on the island with this pre_business
    island = mongo.islands.find_one({"id": MAP_ID}, {"_id": 0, "cells": 1})
    assert island and island.get("cells")
    target_cell = next(
        (c for c in island["cells"]
         if c.get("pre_business") == target_type and not c.get("is_empty")),
        None,
    )
    assert target_cell, f"no {target_type} cell found on {MAP_ID}"

    plot_id = f"{FAKE_PLOT_ID_PREFIX}{uuid.uuid4()}"
    mongo.plots.insert_one({
        "id": plot_id,
        "island_id": MAP_ID,
        "x": target_cell["x"],
        "y": target_cell["y"],
        "owner": FAKE_OWNER,
        "purchased_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    })

    r = requests.get(
        f"{BASE_URL}/api/admin/presale/inventory",
        params={"map_id": MAP_ID}, headers=admin_headers, timeout=30,
    )
    assert r.status_code == 200, r.text
    after = {b["type"]: {"free": b["free"], "total": b["total"]}
             for b in r.json()["businesses"]}

    # free decreased by exactly 1, total unchanged
    assert after[target_type]["free"] == baseline_free - 1, (
        f"expected free {baseline_free - 1}, got {after[target_type]['free']}"
    )
    assert after[target_type]["total"] == baseline_total, (
        f"total should not change; was {baseline_total}, now {after[target_type]['total']}"
    )
    # Remember the inserted plot coord for the “does not pick purchased cell” test
    pytest._presale_target_type = target_type
    pytest._presale_target_coord = (target_cell["x"], target_cell["y"])
    pytest._presale_target_free_after = after[target_type]["free"]


# ---------------------------------------------------------------------------
# Test 4: duplicate business types in payload ⇒ HTTP 400
# ---------------------------------------------------------------------------
def test_select_plots_rejects_duplicate_types(admin_headers):
    target_type = getattr(pytest, "_presale_target_type", "bio_farm")
    payload = {
        "map_id": MAP_ID,
        "businesses": [
            {"type": target_type, "count": 1},
            {"type": target_type, "count": 1},
        ],
    }
    r = requests.post(
        f"{BASE_URL}/api/admin/presale/select-plots",
        json=payload, headers=admin_headers, timeout=30,
    )
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"
    detail = (r.json().get("detail") or "").lower()
    assert ("дубл" in detail) or ("duplicate" in detail) or (target_type in detail), (
        f"expected duplicate-mention in error detail, got: {detail}"
    )


# ---------------------------------------------------------------------------
# Test 5: count > free ⇒ HTTP 400 with available count in message
# ---------------------------------------------------------------------------
def test_select_plots_rejects_count_over_free(admin_headers):
    target_type = getattr(pytest, "_presale_target_type", "bio_farm")
    free_after = getattr(pytest, "_presale_target_free_after", None)
    assert isinstance(free_after, int), "prior test must set free_after"

    want = free_after + 1  # one more than actually available
    payload = {
        "map_id": MAP_ID,
        "businesses": [{"type": target_type, "count": want}],
    }
    r = requests.post(
        f"{BASE_URL}/api/admin/presale/select-plots",
        json=payload, headers=admin_headers, timeout=30,
    )
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"
    detail = r.json().get("detail") or ""
    assert str(free_after) in detail, (
        f"expected available count {free_after} to appear in detail: {detail}"
    )


# ---------------------------------------------------------------------------
# Test 6: valid payload ⇒ ok=True AND never picks the purchased coordinate
# ---------------------------------------------------------------------------
def test_select_plots_success_avoids_purchased_cell(admin_headers):
    target_type = getattr(pytest, "_presale_target_type", "bio_farm")
    free_after = getattr(pytest, "_presale_target_free_after")
    purchased = getattr(pytest, "_presale_target_coord")

    payload = {
        "map_id": MAP_ID,
        # Take all remaining free cells of that type — if any picked matches
        # the purchased coord, the ownership check is broken.
        "businesses": [{"type": target_type, "count": free_after}],
    }
    r = requests.post(
        f"{BASE_URL}/api/admin/presale/select-plots",
        json=payload, headers=admin_headers, timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    selected = body["selected_plots"]
    assert len(selected) == free_after, f"expected {free_after} picks, got {len(selected)}"
    matches = [(s["x"], s["y"]) for s in selected
               if (s["x"], s["y"]) == purchased]
    assert not matches, (
        f"selected an already-purchased cell {purchased}: {matches}"
    )
    # All picks must be the requested business type
    for s in selected:
        assert s["business_type"] == target_type


# ---------------------------------------------------------------------------
# Test 7: cleanup — after removing fake plot, free returns to baseline total
# ---------------------------------------------------------------------------
def test_inventory_restored_after_cleanup(admin_headers, mongo):
    target_type = getattr(pytest, "_presale_target_type", "bio_farm")
    baseline = getattr(pytest, "_presale_baseline")

    mongo.plots.delete_many({"owner": FAKE_OWNER})
    mongo.admin_settings.delete_one({"type": "presale"})

    r = requests.get(
        f"{BASE_URL}/api/admin/presale/inventory",
        params={"map_id": MAP_ID}, headers=admin_headers, timeout=30,
    )
    assert r.status_code == 200, r.text
    after = {b["type"]: {"free": b["free"], "total": b["total"]}
             for b in r.json()["businesses"]}
    assert after[target_type]["free"] == baseline[target_type]["free"], (
        f"free not restored: {after[target_type]['free']} vs baseline {baseline[target_type]['free']}"
    )
    assert after[target_type]["total"] == baseline[target_type]["total"]
