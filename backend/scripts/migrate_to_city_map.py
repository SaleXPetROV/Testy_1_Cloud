"""Move every existing business onto the new city map (backend/data/city_layout_v1.json).

    cd backend
    python -m scripts.migrate_to_city_map                 # DRY RUN (default): plan + report, nothing changes
    python -m scripts.migrate_to_city_map --apply         # do it (backup first, then move, then verify)
    python -m scripts.migrate_to_city_map --rollback TAG  # restore everything from the backup TAG

Rules
  • Every business keeps its `id`, level, durability, warehouse, income history, lease (level 0),
    skin and everything else — only its place on the map changes (x, y, plot_id, city fields).
  • Each business goes to a slot made for the SAME business type, first in District 1 (Central Core).
    A player's businesses are placed next to each other (closest free slot of the right type).
    If the Core has no free slot of that type left, the nearest other district is used.
  • A player gets exactly as many businesses as before. Nothing is ever deleted: a business that
    cannot be placed (more owners of a type than slots of that type on the whole map) is listed
    in the report and left untouched — the script refuses --apply until that list is empty
    (use --allow-unplaced to move the rest anyway).
  • Old plots are kept with archived=True; new plots are created for every slot of the new map
    (owned or free) so the new map has one plot per slot.
  • Plot listings (land_listings) follow their business to the new plot.
  • Idempotent: a finished migration is recorded in admin_settings(type=city_map_migration);
    running --apply again does nothing unless --force.

Env: MONGO_URL, DB_NAME (same as the server).
"""
import argparse
import asyncio
import json
import math
import os
import sys
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

LAYOUT = HERE.parent / "data" / "city_layout_v1.json"
ISLAND_ID = "ton_island"          # the game addresses the map by this id
LEGACY_ID = "ton_island_legacy"   # the old diamond map is kept under this id
TYPE_ALIASES = {"cold_storage": "hydro_cooling", "chip_factory": "chips_factory", "logistics": "logistics_hub",
                "repair_zone": "repair_shop", "solar": "helios", "data_center": "nano_dc", "quartz": "quartz_mine",
                "traffic_tower": "signal_tower", "bank": "gram_bank"}
DISTRICT_ORDER = [1, 2, 3, 4]          # Core first, then the others


def now():
    return datetime.now(timezone.utc).isoformat()


def canon_type(t):
    try:
        from business_config import BUSINESS_KEY_MAP
        t = BUSINESS_KEY_MAP.get(t, t)
    except Exception:
        pass
    return TYPE_ALIASES.get(t, t)


def slot_center(s):
    return (s["x"] + s["w"] / 2, s["y"] + s["h"] / 2)


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


async def owner_user_id(db, owner, cache):
    """businesses.owner may be a user id, a wallet or an e-mail: resolve to the user id."""
    if owner in cache:
        return cache[owner]
    u = await db.users.find_one({"$or": [{"id": owner}, {"wallet_address": owner}, {"email": owner}]},
                                {"_id": 0, "id": 1, "username": 1, "avatar": 1})
    cache[owner] = u
    return u


def plan(slots, businesses_by_user, layout_center):
    """Assign each business a slot of its type: Core first, close to the player's other businesses."""
    free = defaultdict(list)                                 # (district, type) -> slots
    for s in slots:
        free[(s["district"], s["business_type"])].append(s)
    core_center = layout_center
    # big owners first, so their quarter is compact; then the oldest players
    order = sorted(businesses_by_user.items(), key=lambda kv: (-len(kv[1]), kv[1][0].get("created_at") or kv[1][0].get("built_at") or ""))
    moves, unplaced = [], []
    for uid, bizs in order:
        anchor = None
        # place rare / big types first (they decide where the player's quarter is)
        bizs = sorted(bizs, key=lambda b: -b["_size_rank"])
        for b in bizs:
            t = b["_type"]
            chosen = None
            for d in DISTRICT_ORDER:
                cand = free.get((d, t)) or []
                if not cand:
                    continue
                ref = anchor or core_center
                chosen = min(cand, key=lambda s: (dist(slot_center(s), ref), s["slot_id"]))
                cand.remove(chosen)
                break
            if not chosen:
                unplaced.append(b); continue
            if anchor is None:
                anchor = slot_center(chosen)
            moves.append((uid, b, chosen))
    return moves, unplaced


async def run(args, db=None):
    # the server passes its own database object (it decrypts personal data when PII encryption is on)
    if db is None:
        db = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))[os.environ.get("DB_NAME", "ton_city")]
    if args.rollback:
        return await rollback(db, args.rollback)
    layout = json.loads(Path(args.layout).read_text(encoding="utf-8"))
    slots = layout["slots"]
    size_rank = {"3x3": 3, "2x2": 2, "1x2": 1, "1x1": 0}
    done = await db.admin_settings.find_one({"type": "city_map_migration"}, {"_id": 0})
    if done and args.apply and not args.force:
        print(f"Already migrated ({done.get('tag')} at {done.get('done_at')}). Use --force to run again.")
        return 1

    # 1) every real business that sits on the map
    q = {"is_trial": {"$ne": True}, "tutorial": {"$ne": True}, "owner": {"$nin": [None, ""]}}
    if done and args.force:
        q["city_island_id"] = {"$ne": "city_v1"}
    bizs = await db.businesses.find(q, {"_id": 0}).to_list(None)
    cache, by_user, skipped = {}, defaultdict(list), []
    slot_types = {s["business_type"] for s in slots}
    for b in bizs:
        u = await owner_user_id(db, b["owner"], cache)
        t = canon_type(b.get("business_type"))
        if not u:
            skipped.append({"id": b["id"], "reason": "owner not found", "owner": b["owner"]}); continue
        if t not in slot_types:
            skipped.append({"id": b["id"], "reason": f"type {t} has no slot on the new map"}); continue
        size = next(s["size"] for s in slots if s["business_type"] == t)
        b["_type"], b["_size_rank"], b["_user"] = t, size_rank[size], u
        by_user[u["id"]].append(b)

    # 2) plan — never into a lot where a business already stands (a forced re-run on the new map)
    occupied = {b.get("city_slot_id") async for b in db.businesses.aggregate([
        {"$match": {"city_island_id": "city_v1", "owner": {"$nin": [None, ""]}}}, {"$project": {"_id": 0, "city_slot_id": 1}}])}
    moves, unplaced = plan([s for s in slots if s["slot_id"] not in occupied], by_user, tuple(layout["districts"][0]["center"]))
    report = {
        "generated_at": now(), "mode": "apply" if args.apply else "dry-run",
        "businesses_found": len(bizs), "players": len(by_user), "to_move": len(moves),
        "unplaced": [{"id": b["id"], "type": b["_type"], "owner": b["_user"]["id"]} for b in unplaced],
        "skipped": skipped,
        "by_district": {str(d): sum(1 for _, _, s in moves if s["district"] == d) for d in DISTRICT_ORDER},
        "demand_vs_slots": {}, "players_detail": [],
    }
    demand = defaultdict(int)
    for bl in by_user.values():
        for b in bl:
            demand[b["_type"]] += 1
    for t in sorted(slot_types):
        report["demand_vs_slots"][t] = {"businesses": demand[t], "core_slots": sum(1 for s in slots if s["business_type"] == t and s["district"] == 1),
                                        "all_slots": sum(1 for s in slots if s["business_type"] == t)}
    per_user = defaultdict(list)
    for uid, b, s in moves:
        per_user[uid].append({"business_id": b["id"], "type": b["_type"], "level": b.get("level"),
                              "old": {"x": b.get("x"), "y": b.get("y"), "plot_id": b.get("plot_id")},
                              "new": {"slot_id": s["slot_id"], "district": s["district"], "x": s["x"], "y": s["y"], "w": s["w"], "h": s["h"]}})
    for uid, items in per_user.items():
        report["players_detail"].append({"user_id": uid, "before": len(by_user[uid]), "after": len(items), "businesses": items})
    out = Path(args.report); out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"businesses found: {len(bizs)} | players: {len(by_user)} | will move: {len(moves)} | "
          f"unplaced: {len(unplaced)} | skipped: {len(skipped)}")
    print("by district:", report["by_district"])
    short = [t for t, v in report["demand_vs_slots"].items() if v["businesses"] > v["core_slots"]]
    if short:
        print("types that do not fit into the Core (overflow to other districts):", ", ".join(short))
    print(f"report: {out}")
    if not args.apply:
        print("DRY RUN — nothing was changed. Run with --apply to migrate.")
        return 0
    if unplaced and not args.allow_unplaced:
        print("Refusing to apply: some businesses have no slot (see report.unplaced).")
        return 2

    # 3) backup
    tag = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    bk = db[f"migration_backup_{tag}"]
    await bk.insert_many([{"kind": "business", "doc": b} for b in await db.businesses.find(q, {"_id": 0}).to_list(None)] or [{"kind": "empty"}])
    old_island = await db.islands.find_one({"id": ISLAND_ID}, {"_id": 0})
    if old_island:
        await bk.insert_one({"kind": "island", "doc": old_island})
    plots_all = await db.plots.find({}, {"_id": 0}).to_list(None)
    if plots_all:
        await bk.insert_many([{"kind": "plot", "doc": p} for p in plots_all])
    lst = await db.land_listings.find({}, {"_id": 0}).to_list(None)
    if lst:
        await bk.insert_many([{"kind": "land_listing", "doc": d} for d in lst])
    print(f"backup: collection migration_backup_{tag}")

    try:
        return await _apply(db, tag, slots, moves, unplaced, by_user)
    except Exception as e:                       # never leave the base half-migrated
        print(f"ERROR during migration: {e!r} — rolling back from {tag}")
        await rollback(db, tag)
        return 4


async def _apply(db, tag, slots, moves, unplaced, by_user):
    old_island = await db.islands.find_one({"id": ISLAND_ID}, {"_id": 0})
    # 4) the new map replaces the old one: old island + plots -> legacy, new island document
    await db.plots.update_many({"island_id": ISLAND_ID, "city_slot_id": {"$exists": False}},
                               {"$set": {"island_id": LEGACY_ID, "archived": True, "archived_at": now()}})
    from city_island import build_city_island
    if old_island and old_island.get("version") != "city_v1":
        old_island["id"] = LEGACY_ID
        await db.islands.replace_one({"id": LEGACY_ID}, old_island, upsert=True)
    new_island = build_city_island()
    await db.islands.replace_one({"id": ISLAND_ID}, new_island, upsert=True)
    taken = {s["slot_id"]: (uid, b) for uid, b, s in moves}
    try:
        from map_config import get_plot_price
    except Exception:
        get_plot_price = None
    existing = {p["id"]: p async for p in db.plots.find({"island_id": ISLAND_ID, "city_slot_id": {"$exists": True}}, {"_id": 0})}
    new_plots = []
    for s in slots:
        pid = f"city_v1-{s['slot_id']}"
        price = None
        if get_plot_price:
            try:
                rev = {v: k for k, v in TYPE_ALIASES.items()}
                price = get_plot_price(rev.get(s["business_type"], s["business_type"]))
            except Exception:
                price = None
        doc = {"id": pid, "island_id": ISLAND_ID, "city_slot_id": s["slot_id"], "slot_id": s["slot_id"], "district": s["district"], "size": s["size"],
               "x": s["x"], "y": s["y"], "w": s["w"], "h": s["h"], "business_type": s["business_type"],
               "price_ton": (price or {}).get("ton"), "price_city": (price or {}).get("city"),
               "owner": None, "business_id": None, "is_empty": False, "warehouses": [], "created_at": now()}
        prev = existing.get(pid)
        if s["slot_id"] not in taken and prev and isinstance(prev.get("owner"), str):
            # a lot that already has its owner keeps it (a forced re-run used to make every such lot free)
            doc.update({k: prev.get(k) for k in ("owner", "owner_username", "owner_avatar", "business_id", "business", "purchased_at", "listing_id") if k in prev})
        if s["slot_id"] in taken:
            uid, b = taken[s["slot_id"]]; u = b["_user"]
            doc.update({"owner": uid, "owner_username": u.get("username"), "owner_avatar": u.get("avatar"),
                        "business_id": b["id"], "purchased_at": b.get("built_at") or b.get("created_at") or now()})
        new_plots.append(doc)
    await db.plots.delete_many({"island_id": ISLAND_ID, "city_slot_id": {"$exists": True}})   # re-runs with --force start clean
    await db.plots.insert_many(new_plots)

    # 5) move the businesses (id unchanged)
    for uid, b, s in moves:
        pid = f"city_v1-{s['slot_id']}"
        await db.businesses.update_one({"id": b["id"]}, {"$set": {
            "plot_id": pid, "x": s["x"], "y": s["y"], "island_id": ISLAND_ID, "city_island_id": "city_v1", "city_slot_id": s["slot_id"],
            "district_id": s["district"], "footprint": {"w": s["w"], "h": s["h"]},
            "pre_migration": {"plot_id": b.get("plot_id"), "x": b.get("x"), "y": b.get("y")}, "migrated_at": now()}})
        await db.land_listings.update_many({"business_id": b["id"]}, {"$set": {"plot_id": pid, "x": s["x"], "y": s["y"], "island_id": ISLAND_ID}})

    # 6) verify
    errors = []
    for uid, bl in by_user.items():
        ids = [b["id"] for b in bl if b not in unplaced]
        n = await db.businesses.count_documents({"id": {"$in": ids}, "city_island_id": "city_v1"})
        if n != len(ids):
            errors.append(f"user {uid}: {n}/{len(ids)} moved")
    dup = len(new_plots) - len({p["id"] for p in new_plots})
    if dup:
        errors.append(f"{dup} duplicate plot ids")
    await db.admin_settings.update_one({"type": "city_map_migration"}, {"$set": {
        "type": "city_map_migration", "tag": tag, "done_at": now(), "moved": len(moves), "players": len(by_user),
        "unplaced": len(unplaced), "errors": errors}}, upsert=True)
    print("verify:", "OK" if not errors else errors)
    print(f"done. rollback: python -m scripts.migrate_to_city_map --rollback {tag}")
    return 0 if not errors else 3


async def rollback(db, tag):
    bk = db[f"migration_backup_{tag}"]
    if await bk.count_documents({}) == 0:
        print("backup not found:", tag); return 1
    async for row in bk.find({"kind": "business"}):
        d = row["doc"]
        await db.businesses.replace_one({"id": d["id"]}, d, upsert=True)
    await db.plots.delete_many({})
    isl = await bk.find_one({"kind": "island"})
    if isl:
        await db.islands.replace_one({"id": ISLAND_ID}, isl["doc"], upsert=True)
        await db.islands.delete_one({"id": LEGACY_ID})
    plots = [row["doc"] async for row in bk.find({"kind": "plot"})]
    if plots:
        await db.plots.insert_many(plots)
    await db.land_listings.delete_many({})
    lst = [row["doc"] async for row in bk.find({"kind": "land_listing"})]
    if lst:
        await db.land_listings.insert_many(lst)
    await db.admin_settings.delete_one({"type": "city_map_migration"})
    print("rolled back from", tag); return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="really migrate (default is a dry run)")
    ap.add_argument("--force", action="store_true", help="run again although a migration is recorded")
    ap.add_argument("--allow-unplaced", action="store_true", help="apply even if some businesses have no slot")
    ap.add_argument("--rollback", metavar="TAG", help="restore from migration_backup_TAG")
    ap.add_argument("--layout", default=str(LAYOUT))
    ap.add_argument("--report", default="city_map_migration_report.json")
    sys.exit(asyncio.run(run(ap.parse_args())))


if __name__ == "__main__":
    main()
