"""Alliances, stage 1: create / join / roles / treasury / tax / AXP / levels / disband / maintenance."""
import asyncio
import datetime as dt

import pytest

mongomock_motor = pytest.importorskip("mongomock_motor")
from fastapi import FastAPI
from fastapi.testclient import TestClient

import alliances as al


class U:
    def __init__(self, uid): self.id = uid; self.language = "ru"


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def world(monkeypatch):
    db = mongomock_motor.AsyncMongoMockClient()["al"]
    who = {"u": "u1"}
    sent = []
    levels = {f"u{i}": 10 for i in range(1, 40)}
    monkeypatch.setattr(al, "_IDX_DONE", False)
    monkeypatch.setattr(al, "_notify", lambda _db, uid, key, **v: sent.append((uid, key, v)))
    monkeypatch.setattr(al, "_notify_role", lambda _db, uid, a, role: sent.append((uid, "alliance_role", {"role": role})))

    async def lvl(_db, uid):
        return levels.get(uid, 0)

    async def biz(_db, uid):
        return uid != "nobiz"
    monkeypatch.setattr(al, "pass_level", lvl)
    monkeypatch.setattr(al, "has_business", biz)
    run(db.users.insert_many([{"id": f"u{i}", "username": f"user{i}", "balance_ton": 50.0, "bonus_balance": 0.0} for i in range(1, 40)]
                             + [{"id": "nobiz", "username": "nobiz", "balance_ton": 50.0, "bonus_balance": 0.0}]))
    app = FastAPI()
    app.include_router(al.create_alliances_router(db, lambda: U(who["u"]), lambda: {"id": "adm"}))
    c = TestClient(app)

    def as_(uid):
        who["u"] = uid
        return c
    return db, as_, sent, levels


def make(as_, uid="u1", name="Neon Wolves", tag="NWLF", mode="open"):
    r = as_(uid).post("/api/alliances", json={"name": name, "tag": tag, "emblem": "🐺", "lang": "ru", "join_mode": mode})
    assert r.status_code == 200, r.text
    return r.json()


def code(r):
    d = r.json().get("detail")
    return d.get("code") if isinstance(d, dict) else d


def test_create_charges_and_makes_leader(world):
    db, as_, sent, _ = world
    a = make(as_)
    assert a["tag"] == "NWLF" and a["members_count"] == 1 and a["slots"] == 10
    u = run(db.users.find_one({"id": "u1"}))
    assert abs(u["balance_ton"] - 45.0) < 1e-9                                  # 5 000 $CITY = 5 TON
    assert u["alliance_tag"] == "NWLF" and u["alliance_name"] == "Neon Wolves"
    me = as_("u1").get("/api/alliances/me").json()
    assert me["me"]["role"] == "leader" and me["me"]["can"]["disband"] and me["alliance"]["treasury_city"] == 0
    # unique name / tag (case-insensitive), one alliance per player
    assert code(as_("u2").post("/api/alliances", json={"name": "neon wolves", "tag": "ABC"})) == "name_taken"
    assert code(as_("u2").post("/api/alliances", json={"name": "Other", "tag": "nwlf"})) == "tag_taken"
    assert code(as_("u1").post("/api/alliances", json={"name": "Second", "tag": "SEC"})) == "already_member"
    assert abs(run(db.users.find_one({"id": "u2"}))["balance_ton"] - 50.0) < 1e-9   # refused → nothing charged


def test_create_gates(world):
    db, as_, _, levels = world
    levels["u2"] = 3
    assert code(as_("u2").post("/api/alliances", json={"name": "Low Level", "tag": "LOW"})) == "pass_level_low"
    assert code(as_("nobiz").post("/api/alliances", json={"name": "No Biz", "tag": "NOB"})) in ("need_business", "pass_level_low")
    assert code(as_("u3").post("/api/alliances", json={"name": "ab", "tag": "OKK"})) == "bad_name"
    assert code(as_("u3").post("/api/alliances", json={"name": "Good name", "tag": "x!"})) == "bad_tag"
    run(db.users.update_one({"id": "u4"}, {"$set": {"balance_ton": 1.0}}))
    assert code(as_("u4").post("/api/alliances", json={"name": "Poor", "tag": "POOR"})) == "insufficient"


def test_join_modes_requests_invites(world):
    db, as_, sent, levels = world
    a = make(as_, mode="request")
    assert as_("u2").post(f"/api/alliances/{a['id']}/join").json()["status"] == "requested"
    assert any(k == "alliance_request_new" and uid == "u1" for uid, k, _ in sent)      # the leader is told
    reqs = as_("u1").get("/api/alliances/me").json()["requests"]
    assert len(reqs) == 1 and reqs[0]["username"] == "user2"
    assert reqs[0]["businesses"] == [] and "pass_level" not in reqs[0]                 # officers see the businesses
    assert code(as_("u3").post(f"/api/alliances/me/requests/{reqs[0]['id']}/accept")) == "not_member"   # not staff
    assert as_("u1").post(f"/api/alliances/me/requests/{reqs[0]['id']}/accept").json()["status"] == "accepted"
    assert run(db.users.find_one({"id": "u2"}))["alliance_tag"] == "NWLF"
    # invite only
    as_("u1").put("/api/alliances/me/settings", json={"join_mode": "invite"})
    assert code(as_("u3").post(f"/api/alliances/{a['id']}/join")) == "invite_only"
    assert as_("u1").post("/api/alliances/me/invite", json={"username": "@USER3"}).json()["status"] == "invited"
    inv = as_("u3").get("/api/alliances/me").json()["invites"]
    assert len(inv) == 1 and inv[0]["alliance"]["tag"] == "NWLF"
    assert as_("u3").post(f"/api/alliances/invites/{inv[0]['id']}/accept").json()["status"] == "joined"
    assert as_("u1").get("/api/alliances/me").json()["alliance"]["members_count"] == 3


def test_min_level_slots_cooldown_linked(world):
    db, as_, _, levels = world
    a = make(as_)
    levels["u2"] = 0                                                                # joining needs no City Pass level
    for i in range(2, 11):                                                          # 10 places on level 1
        assert as_(f"u{i}").post(f"/api/alliances/{a['id']}/join").json()["status"] == "joined"
    assert code(as_("u11").post(f"/api/alliances/{a['id']}/join")) == "full"
    # leave → 24 h before joining again
    assert as_("u10").post("/api/alliances/me/leave").json()["status"] == "left"
    assert code(as_("u10").post(f"/api/alliances/{a['id']}/join")) == "rejoin_cooldown"
    # linked accounts (one device) are never in one alliance
    run(db.fingerprints.insert_many([{"user_id": "u2", "visitor_id": "dev1"}, {"user_id": "u12", "visitor_id": "dev1"}]))
    assert code(as_("u12").post(f"/api/alliances/{a['id']}/join")) == "linked_account"


def test_roles_kick_transfer(world):
    db, as_, sent, _ = world
    a = make(as_)
    for i in range(2, 6):
        as_(f"u{i}").post(f"/api/alliances/{a['id']}/join")
    assert as_("u1").post("/api/alliances/me/members/u2/role", json={"role": "deputy"}).json()["status"] == "ok"
    assert as_("u1").post("/api/alliances/me/members/u3/role", json={"role": "deputy"}).json()["status"] == "ok"
    assert code(as_("u1").post("/api/alliances/me/members/u4/role", json={"role": "deputy"})) == "role_limit"   # max 2
    assert code(as_("u2").post("/api/alliances/me/members/u3/kick")) == "no_rights"         # deputy can't kick a deputy
    assert code(as_("u2").post("/api/alliances/me/members/u4/role", json={"role": "deputy"})) == "no_rights"
    assert code(as_("u2").post("/api/alliances/me/members/u4/role", json={"role": "officer"})) == "no_rights"   # only the leader gives statuses
    assert as_("u1").post("/api/alliances/me/members/u4/role", json={"role": "officer"}).json()["status"] == "ok"
    assert code(as_("u4").post("/api/alliances/me/members/u5/role", json={"role": "member"})) == "no_rights"
    assert as_("u2").post("/api/alliances/me/members/u5/kick").json()["status"] == "kicked"
    assert any(uid == "u5" and k == "alliance_kicked" for uid, k, _ in sent)
    assert "alliance_tag" not in run(db.users.find_one({"id": "u5"}))
    # the leader can't leave while others stay; transfers first
    assert code(as_("u1").post("/api/alliances/me/leave")) == "leader_must_transfer"
    assert as_("u1").post("/api/alliances/me/members/u4/leader").json()["status"] == "ok"
    me = as_("u4").get("/api/alliances/me").json()
    assert me["me"]["role"] == "leader" and me["alliance"]["leader_id"] == "u4"
    assert {m["user_id"]: m["role"] for m in me["members"]}["u1"] == "deputy"


def test_treasury_deposit_payout_tax(world):
    db, as_, sent, _ = world
    a = make(as_)
    as_("u2").post(f"/api/alliances/{a['id']}/join")
    # (bonus-first split payments are core.balance.debit_user_split, covered by its own tests; the in-memory
    #  test database can't run its two-field conditional update, so here the payment is from one balance)
    r = as_("u2").post("/api/alliances/me/deposit", json={"amount_city": 1500})
    assert r.status_code == 200 and r.json()["treasury_city"] == 1500
    assert abs(run(db.users.find_one({"id": "u2"}))["balance_ton"] - 48.5) < 1e-9
    assert code(as_("u2").post("/api/alliances/me/deposit", json={"amount_city": 19000})) == "deposit_cap"   # 20 000 a day
    assert code(as_("u2").post("/api/alliances/me/deposit", json={"amount_city": 5})) == "deposit_min"
    # tax: leader only, 0..5 %, once in 7 days
    assert code(as_("u2").put("/api/alliances/me/settings", json={"tax_pct": 3})) == "no_rights"
    assert code(as_("u1").put("/api/alliances/me/settings", json={"tax_pct": 9})) == "bad_tax"
    assert as_("u1").put("/api/alliances/me/settings", json={"tax_pct": 5}).status_code == 200
    assert code(as_("u1").put("/api/alliances/me/settings", json={"tax_pct": 4})) == "tax_cooldown"
    assert run(al.take_tax(db, "u2", 200, "task_reward")) == 10.0
    assert run(al.take_tax(db, "u30", 200, "task_reward")) == 0.0                     # no alliance — no tax
    me = as_("u1").get("/api/alliances/me").json()
    assert me["alliance"]["treasury_city"] == 1510
    assert any(x["kind"] == "tax" and x["amount_city"] == 10 for x in me["log"])
    # payouts → bonus balance of the member; a member can't pay out
    assert code(as_("u2").post("/api/alliances/me/payout", json={"user_id": "u2", "amount_city": 10})) == "no_rights"
    assert as_("u1").post("/api/alliances/me/payout", json={"user_id": "u2", "amount_city": 500}).json()["ok"]
    assert abs(run(db.users.find_one({"id": "u2"}))["bonus_balance"] - 0.5) < 1e-9      # 500 $CITY, bonus balance
    assert code(as_("u1").post("/api/alliances/me/payout", json={"user_id": "u2", "amount_city": 99999})) == "treasury_low"
    assert run(db.transactions.count_documents({"tx_type": "alliance_payout", "user_id": "u2"})) == 1


def test_task_reward_pays_the_tax(world, monkeypatch):
    db, as_, _, _ = world
    a = make(as_)
    as_("u2").post(f"/api/alliances/{a['id']}/join")
    as_("u1").put("/api/alliances/me/settings", json={"tax_pct": 4})
    from routes.tasks import credit_task_reward_bonus
    run(credit_task_reward_bonus(db, "u2", 1000, "Daily login", "daily_login"))
    u2 = run(db.users.find_one({"id": "u2"}))
    assert abs(u2["bonus_balance"] - 0.96) < 1e-9                                       # 1 000 − 4 % → 960 $CITY
    assert run(db.alliances.find_one({"id": a["id"]}))["treasury_city"] == 40
    tx = run(db.transactions.find_one({"user_id": "u2", "tx_type": "daily_login"}))
    assert tx["alliance_tax_city"] == 40 and tx["reward_city"] == 1000


def test_axp_share_cap_and_level_up(world):
    db, as_, sent, _ = world
    a = make(as_)
    as_("u2").post(f"/api/alliances/{a['id']}/join")
    assert run(al.add_axp(db, "u2", 1000)) == 100                                       # 10 %
    assert run(al.add_axp(db, "u2", 30000)) == 1900                                     # cap 2 000 a day per player
    assert run(al.add_axp(db, "u2", 500)) == 0
    assert run(al.add_axp(db, "u30", 5000)) == 0                                        # not in an alliance
    run(al.add_axp(db, "u1", 30000))
    assert code(as_("u1").post("/api/alliances/me/level-up")) == "axp_low"              # 4 000 of 5 000 AXP
    run(db.alliances.update_one({"id": a["id"]}, {"$set": {"axp": 5000}}))
    assert code(as_("u1").post("/api/alliances/me/level-up")) == "treasury_low"         # 2 000 $CITY fee missing
    run(db.alliances.update_one({"id": a["id"]}, {"$set": {"treasury_city": 2500}}))
    assert code(as_("u2").post("/api/alliances/me/level-up")) == "no_rights"
    r = as_("u1").post("/api/alliances/me/level-up").json()
    assert r["level"] == 2
    al_doc = run(db.alliances.find_one({"id": a["id"]}))
    assert al_doc["treasury_city"] == 500 and al_doc["level"] == 2
    assert as_("u1").get("/api/alliances/me").json()["alliance"]["slots"] == 12
    assert {uid for uid, k, _ in sent if k == "alliance_level_up"} == {"u1", "u2"}


def test_axp_low_blocks_level_up(world):
    db, as_, _, _ = world
    make(as_)
    run(db.alliances.update_one({}, {"$set": {"treasury_city": 99999}}))
    assert code(as_("u1").post("/api/alliances/me/level-up")) == "axp_low"


def test_disband_shares_treasury_by_deposits(world):
    db, as_, sent, _ = world
    a = make(as_)
    as_("u2").post(f"/api/alliances/{a['id']}/join")
    as_("u3").post(f"/api/alliances/{a['id']}/join")
    as_("u1").post("/api/alliances/me/deposit", json={"amount_city": 3000})
    as_("u2").post("/api/alliances/me/deposit", json={"amount_city": 1000})
    r = as_("u1").post("/api/alliances/me/disband").json()
    assert r["shares"] == {"u1": 3000.0, "u2": 1000.0, "u3": 0.0}
    assert abs(run(db.users.find_one({"id": "u1"}))["bonus_balance"] - 3.0) < 1e-9
    assert run(db.alliance_members.count_documents({})) == 0
    assert all("alliance_tag" not in run(db.users.find_one({"id": u})) for u in ("u1", "u2", "u3"))
    assert {uid for uid, k, _ in sent if k == "alliance_disbanded"} == {"u1", "u2", "u3"}
    # the name and the tag are free again
    make(as_, uid="u4", name="Neon Wolves", tag="NWLF")


def test_maintenance_solo_and_inactive_leader(world):
    db, as_, sent, _ = world
    a = make(as_)
    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=20)).isoformat()
    run(db.alliances.update_one({"id": a["id"]}, {"$set": {"solo_since": old}}))
    b = make(as_, uid="u5", name="Second", tag="SEC")
    as_("u6").post(f"/api/alliances/{b['id']}/join")
    as_("u7").post(f"/api/alliances/{b['id']}/join")
    as_("u5").post("/api/alliances/me/members/u7/role", json={"role": "officer"})
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    run(db.online_presence.insert_many([{"user_id": "u5", "last_seen": old}, {"user_id": "u6", "last_seen": old},
                                        {"user_id": "u7", "last_seen": now}]))
    r = run(al.maintenance(db))
    assert r["disbanded"] == 1 and r["leaders"] == 1
    assert run(db.alliances.find_one({"id": a["id"]}))["status"] == "disbanded"
    assert run(db.alliances.find_one({"id": b["id"]}))["leader_id"] == "u7"           # the active officer leads


def test_list_and_admin(world):
    db, as_, _, _ = world
    a = make(as_)
    make(as_, uid="u2", name="Berlin Builders", tag="BER")
    run(db.alliances.update_one({"tag": "BER"}, {"$set": {"lang": "de"}}))
    lst = as_("u3").get("/api/alliances?lang=de").json()["alliances"]
    assert lst[0]["tag"] == "BER" and len(lst) == 2                                     # the player's language first
    assert as_("u3").get("/api/alliances?q=wolv").json()["alliances"][0]["tag"] == "NWLF"
    adm = as_("u3").get("/api/admin/alliances").json()
    assert adm["totals"]["active"] == 2 and adm["totals"]["members"] == 2
    assert as_("u3").post(f"/api/admin/alliances/{a['id']}/rename", json={"tag": "WOLF"}).json()["ok"]
    assert run(db.users.find_one({"id": "u1"}))["alliance_tag"] == "WOLF"
    assert as_("u3").put("/api/admin/alliances/config", json={"create_cost_city": 7000}).json()["create_cost_city"] == 7000
    bad = as_("u3").put("/api/admin/alliances/config", json={"levels": [{"axp": 0, "slots": 10}, {"axp": 0, "slots": 12}]})
    assert bad.status_code == 400
    as_("u3").post(f"/api/admin/alliances/{a['id']}/freeze", json={"frozen": True})
    as_("u1").post("/api/alliances/me/deposit", json={"amount_city": 100})
    assert code(as_("u1").post("/api/alliances/me/payout", json={"user_id": "u1", "amount_city": 10})) == "frozen"


def test_request_shows_businesses_and_one_alliance_per_player(world, monkeypatch):
    db, as_, _, _ = world
    a = make(as_, mode="request")
    run(db.businesses.insert_many([
        {"id": "b1", "owner": "u2", "business_type": "helios", "level": 3, "durability": 100, "is_active": True},
        {"id": "b2", "owner": "u2", "business_type": "quartz_mine", "level": 1, "durability": 40, "is_active": False},
        {"id": "b3", "owner": "u2", "business_type": "helios", "level": 1, "tutorial": True},
    ]))
    as_("u2").post(f"/api/alliances/{a['id']}/join")
    r = as_("u1").get("/api/alliances/me").json()["requests"][0]
    types = sorted(b["type"] for b in r["businesses"])
    assert types == ["helios", "quartz_mine"]                                         # the tutorial business is not shown
    helios = next(b for b in r["businesses"] if b["type"] == "helios")
    from business_config import get_production
    assert helios["produces"] == "energy" and helios["per_day"] == get_production("helios", 3) and helios["level"] == 3
    quartz = next(b for b in r["businesses"] if b["type"] == "quartz_mine")
    assert quartz["per_day"] == round(get_production("quartz_mine", 1) * 0.8, 2) and quartz["active"] is False   # durability < 50 %
    assert r["produces_per_day"]["energy"] == helios["per_day"]
    # one alliance per player: a leader can't found a second one even if the membership row went missing
    run(db.alliance_members.delete_one({"user_id": "u1"}))
    assert code(as_("u1").post("/api/alliances", json={"name": "Second One", "tag": "SEC"})) == "already_leader"
