"""Probe: can a zero-stake claim be made on an EXPENSIVE map cell (price > balance)?
Backend charges 0 for the zero stake, so it must succeed regardless of price.
The frontend blocks it with an 'Insufficient funds' modal (bug)."""
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

fe = dotenv_values("/app/frontend/.env")
be = dotenv_values("/app/backend/.env")
API = fe["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
db = MongoClient(be["MONGO_URL"])[be["DB_NAME"]]

EMAIL, PWD = "testuser@example.com", "Test1234!"
u = db.users.find_one({"email": EMAIL})
ids = [v for v in (u.get("id"), u.get("wallet_address"), u.get("email")) if v]
db.businesses.delete_many({"owner": {"$in": ids}})
db.plots.delete_many({"owner": {"$in": ids}})
db.land_listings.delete_many({"seller_id": {"$in": ids}})
db.users.update_one({"email": EMAIL}, {"$set": {"balance_ton": 100.0, "bonus_balance": 0.0,
                                                "businesses_owned": [], "plots_owned": [], "resources": {}},
                                       "$unset": {"has_graduated_zero": ""}})

_lr = requests.post(f"{API}/auth/login", json={"email": EMAIL, "password": PWD})
print("login", _lr.status_code, list(_lr.json().keys())[:6])
_j = _lr.json()
tok = _j.get("access_token") or _j.get("token")
h = {"Authorization": f"Bearer {tok}"}

# arena cell at (16,16) — map price 294.5 TON, user has 100 TON
r = requests.post(f"{API}/island/buy/16/16", headers=h, timeout=60)
print("status", r.status_code, r.text[:300])
u2 = db.users.find_one({"email": EMAIL}, {"_id": 0, "balance_ton": 1, "resources": 1})
print("balance after:", u2["balance_ton"], "resources:", u2.get("resources"))
biz = db.businesses.find_one({"x": 16, "y": 16}, {"_id": 0, "level": 1, "is_zero_business": 1, "zero_map_price": 1})
print("biz:", biz)
lot = db.land_listings.find_one({"x": 16, "y": 16}, {"_id": 0, "price": 1, "business": 1})
print("lot price:", lot and lot["price"], "| name:", lot and lot["business"].get("name"),
      "| consumes:", lot and lot["business"].get("consumes"))
