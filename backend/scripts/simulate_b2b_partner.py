"""Simulate a B2B partner funnel for demo/QA.

Creates a demo B2B partner (@demo_b2b_partner) with sales_percent=10% and
yield_percent=5%. Then attaches 30 pseudo-users to that partner and simulates
that 3 of them purchased land (with one purchasing twice — so 4 land sales
total). Prints the resulting partner statistics so you can see them both in
the terminal and in the admin panel afterwards.

Usage:
    python -m scripts.simulate_b2b_partner  # from /app/backend
    OR
    python /app/backend/scripts/simulate_b2b_partner.py
"""
from __future__ import annotations

import os
import sys
import uuid
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(ROOT / ".env")

from b2b_partners import (  # noqa: E402
    compute_partner_stats,
    build_partner_panel_text,
    credit_land_sale,
)


PARTNER_USERNAME = "demo_b2b_partner"
PARTNER_TG_ID = "900000001"
SALES_PCT = 10.0     # 10% of every land sale
YIELD_PCT = 5.0      # 5% of every referral profit (not used in this sim)

TOTAL_USERS = 30
BUYERS = 3
LAND_PRICE_TON = 12.5  # simulated land price

MARKER = "b2b_sim"    # used to safely wipe previous demo data


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


async def _reset_previous(db):
    await db.b2b_earnings.delete_many({"kind": "land_sale", "user_id": {"$regex": f"^{MARKER}_"}})
    await db.users.delete_many({"id": {"$regex": f"^{MARKER}_"}})
    await db.users.delete_many({"username": PARTNER_USERNAME})
    await db.b2b_partners.delete_many({"username": PARTNER_USERNAME})


async def _upsert_partner(db) -> dict:
    code = uuid.uuid4().hex[:8]
    doc = {
        "id": str(uuid.uuid4()),
        "partner_code": code,
        "username": PARTNER_USERNAME,
        "telegram_user_id": PARTNER_TG_ID,
        "sales_percent": SALES_PCT,
        "yield_percent": YIELD_PCT,
        "earn_total": 0.0,
        "created_at": _iso(datetime.now(timezone.utc)),
    }
    await db.b2b_partners.insert_one(doc)
    # Also seed a player account for the partner so we can verify that this
    # account is EXCLUDED from the leaderboard / referral rally.
    partner_user_id = f"{MARKER}_partner_{uuid.uuid4().hex[:6]}"
    await db.users.insert_one({
        "id": partner_user_id,
        "username": PARTNER_USERNAME,
        "display_name": "Demo B2B Partner",
        "email": f"{partner_user_id}@sim.local",
        "balance_ton": 9999.0,
        "telegram_chat_id": PARTNER_TG_ID,
        "telegram_user_id": PARTNER_TG_ID,
        "telegram_username": PARTNER_USERNAME,
        "b2b_is_partner": True,
        "b2b_partner_ref_id": doc["id"],
        "total_income": 500.0,
        "plots_owned": [],
        "created_at": _iso(datetime.now(timezone.utc)),
        "last_login": _iso(datetime.now(timezone.utc)),
    })
    return doc


async def _seed_users(db, partner: dict) -> list[dict]:
    now = datetime.now(timezone.utc)
    users = []
    # Distribute join times across the last 30 days so the 24h / 7d / 30d
    # buckets have meaningful counts.
    #   - 5 users in the last 24h
    #   - +10 in the last 7 days (so 7d bucket = 15)
    #   - +15 in the last 30 days (so 30d bucket = 30)
    joined_offsets_hours = (
        [1, 3, 5, 12, 20] +
        [26, 40, 60, 80, 100, 120, 140, 155, 165, 168 - 1] +
        [24 * d for d in (8, 10, 12, 14, 16, 18, 20, 22, 24, 25, 26, 27, 28, 29, 29)]
    )[:TOTAL_USERS]

    for i in range(TOTAL_USERS):
        joined_at = now - timedelta(hours=joined_offsets_hours[i])
        uid = f"{MARKER}_{i:02d}_{uuid.uuid4().hex[:6]}"
        users.append({
            "id": uid,
            "username": f"sim_ref_{i:02d}",
            "display_name": f"Sim Referral #{i:02d}",
            "email": f"{uid}@sim.local",
            "balance_ton": 50.0,
            "b2b_partner_id": partner["id"],
            "b2b_partner_code": partner["partner_code"],
            "b2b_joined_at": _iso(joined_at),
            "last_login": _iso(joined_at),   # treated as "active" if within 7d
            "plots_owned": [],
            "total_income": 0,
            "created_at": _iso(joined_at),
        })
    await db.users.insert_many(users)
    return users


async def _simulate_land_sales(db, users: list[dict]) -> tuple[list[dict], float]:
    """3 users buy land; user #0 buys twice → 4 land sales total."""
    # buyer_index -> num_purchases
    buyer_plan = {0: 2, 1: 1, 2: 1}
    events = []
    total_credited = 0.0
    for idx, purchases in buyer_plan.items():
        buyer = users[idx]
        for n in range(purchases):
            price = LAND_PRICE_TON
            # Register the sale as a mock plot for the user
            await db.users.update_one(
                {"id": buyer["id"]},
                {
                    "$inc": {"total_plot_sales": price, "total_income": price},
                    "$push": {"plots_owned": f"sim_plot_{idx}_{n}"},
                },
            )
            credited = await credit_land_sale(db, buyer["id"], price)
            total_credited += credited
            events.append({
                "buyer_id": buyer["id"],
                "buyer_username": buyer["username"],
                "price_ton": price,
                "partner_share_ton": credited,
            })
    return events, total_credited


def _fmt_line(label: str, value: str, indent: int = 0) -> str:
    return f"{'  ' * indent}{label:<32} {value}"


async def main():
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    print("== B2B partner simulation ==")
    await _reset_previous(db)
    partner = await _upsert_partner(db)
    print(_fmt_line("Partner ID", partner["id"]))
    print(_fmt_line("Partner @username", "@" + partner["username"]))
    print(_fmt_line("Partner code", partner["partner_code"]))
    print(_fmt_line("Sales %", f"{partner['sales_percent']}%"))
    print(_fmt_line("Yield %", f"{partner['yield_percent']}%"))
    print(
        _fmt_line(
            "Referral link",
            f"https://t.me/gramcity_games_bot?start=p_{partner['partner_code']}",
        )
    )

    users = await _seed_users(db, partner)
    print(f"\nSeeded {len(users)} referral users (b2b_partner_id set).")

    events, total_credited = await _simulate_land_sales(db, users)
    print(f"\nSimulated {len(events)} land sales:")
    for ev in events:
        print(
            f"  - {ev['buyer_username']} bought land for {ev['price_ton']} TON"
            f" → +{ev['partner_share_ton']} TON to partner"
        )
    print(f"Total credited to partner: {round(total_credited, 6)} TON\n")

    partner_now = await db.b2b_partners.find_one({"id": partner["id"]}, {"_id": 0})
    stats = await compute_partner_stats(db, partner_now)

    print("== Partner statistics (as shown in admin + Telegram bot) ==")
    print(_fmt_line("Total referrals", str(stats["total_users"])))
    print(_fmt_line("Active (last 7d)", str(stats["active_users_7d"])))
    print(_fmt_line("New in last 24h", "+" + str(stats["users_24h"])))
    print(_fmt_line("New in last 7d", "+" + str(stats["users_7d"])))
    print(_fmt_line("New in last 30d", "+" + str(stats["users_30d"])))
    print(_fmt_line("Earned today (TON)", f"{stats['earn_today']}"))
    print(_fmt_line("Earned last 7d (TON)", f"{stats['earn_7d']}"))
    print(_fmt_line("Earned last 30d (TON)", f"{stats['earn_30d']}"))
    print(_fmt_line("Total earned (TON)", f"{stats['earn_total']}"))

    print("\n== Bot panel preview ==")
    print(build_partner_panel_text(partner_now, stats))

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
