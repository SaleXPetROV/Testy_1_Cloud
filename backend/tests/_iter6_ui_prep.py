"""Reset users + list unowned pre_business cells for the UI run."""
import sys
from dotenv import dotenv_values
from pymongo import MongoClient

env = dotenv_values("/app/backend/.env")
db = MongoClient(env["MONGO_URL"])[env["DB_NAME"]]
EMAILS = {"testuser@example.com": 100.0, "sanyanazarov212@gmail.com": 1230.0}


def ids(email):
    u = db.users.find_one({"email": email}, {"_id": 0})
    return u, [v for v in (u.get("id"), u.get("wallet_address"), u.get("email")) if v]


def reset(email, balance):
    u, uid = ids(email)
    db.businesses.delete_many({"owner": {"$in": uid}})
    db.plots.delete_many({"owner": {"$in": uid}})
    db.land_listings.delete_many({"seller_id": {"$in": uid}})
    db.market_listings.delete_many({"seller_id": {"$in": uid}})
    db.notifications.delete_many({"user_id": u["id"], "type": "zero_business_bought"})
    db.users.update_one({"email": email}, {
        "$set": {"balance_ton": balance, "bonus_balance": 0.0, "businesses_owned": [],
                 "plots_owned": [], "tutorial_active": False, "tutorial_completed": True},
        "$unset": {"has_graduated_zero": ""}})


def pre_business_cells(n=6):
    island = db.islands.find_one({"id": "ton_island"}, {"_id": 0})
    taken = {(p.get("x"), p.get("y")) for p in db.plots.find({"island_id": "ton_island"}, {"_id": 0, "x": 1, "y": 1})}
    out = []
    for c in island["cells"]:
        if c.get("pre_business") and not c.get("owner") and (c["x"], c["y"]) not in taken:
            out.append((c["x"], c["y"], c.get("pre_business"), c.get("price_ton")))
            if len(out) >= n:
                break
    return out


def inspect():
    for e in EMAILS:
        u, uid = ids(e)
        print(e, "bal", u.get("balance_ton"), "bonus", u.get("bonus_balance"), "grad", u.get("has_graduated_zero"),
              "biz", list(db.businesses.find({"owner": {"$in": uid}},
                                             {"_id": 0, "id": 1, "level": 1, "x": 1, "y": 1, "is_zero_business": 1,
                                              "business_type": 1, "storage": 1})),
              "lots", list(db.land_listings.find({"seller_id": {"$in": uid}},
                                                 {"_id": 0, "id": 1, "price": 1, "status": 1, "is_zero_business": 1})))
        print("  notifs", db.notifications.count_documents({"user_id": u["id"], "type": "zero_business_bought"}))


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "reset"
    if mode == "reset":
        for e, b in EMAILS.items():
            reset(e, b)
    if mode in ("reset", "cells"):
        print("PRE_BUSINESS_CELLS", pre_business_cells())
    inspect()
