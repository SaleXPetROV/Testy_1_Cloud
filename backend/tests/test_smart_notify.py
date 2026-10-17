"""Smart notifications (backend/smart_notify.py).

    cd backend && python -m pytest tests/test_smart_notify.py -q
"""
import asyncio
import datetime as dt
import uuid

import pytest

mongomock_motor = pytest.importorskip("mongomock_motor")
import smart_notify as sn  # noqa: E402


def run(c):
    return asyncio.run(c)


class _Sent:
    """Captures notify_user calls instead of hitting Telegram/WS."""
    def __init__(self):
        self.calls = []

    async def __call__(self, db, user, title, message, **kw):
        self.calls.append({"title": title, "message": message, **kw})

    def tg(self):
        return [c for c in self.calls if c.get("in_app") is False]

    def app(self):
        return [c for c in self.calls if c.get("telegram") is False]


async def _db(monkeypatch, user_extra=None, quiet=False):
    db = mongomock_motor.AsyncMongoMockClient()["sn"]
    sn.init(db)
    sent = _Sent()
    import core.notify
    monkeypatch.setattr(core.notify, "notify_user", sent)
    prefs = {"smart": {"quiet_enabled": quiet}}
    await db.users.insert_one({"id": "u1", "language": "ru", "telegram_chat_id": "111",
                               "telegram_notifications": True, "notification_preferences": prefs,
                               **(user_extra or {})})
    return db, sent


# ───────────── pure decision logic ─────────────
def test_warehouse_state_machine_upward_only_with_hysteresis():
    u = {"smart_state": {"warehouse": "ok"}}
    assert sn.warehouse_event(u, 50, 100, 2) == ("ok", None)
    assert sn.warehouse_event(u, 92, 100, 2) == ("almost", "warehouse_almost_full")
    u = {"smart_state": {"warehouse": "almost"}}
    assert sn.warehouse_event(u, 95, 100, 2) == ("almost", None)            # no repeat
    assert sn.warehouse_event(u, 100, 100, 2) == ("full", "warehouse_full")
    u = {"smart_state": {"warehouse": "full"}}
    assert sn.warehouse_event(u, 85, 100, 2) == ("almost", None)            # down: silent
    u = {"smart_state": {"warehouse": "almost"}}
    assert sn.warehouse_event(u, 85, 100, 2) == ("almost", None)            # 80-90 band keeps state
    assert sn.warehouse_event(u, 70, 100, 2) == ("ok", None)                # re-armed
    # nothing running -> state tracked, but no alert
    assert sn.warehouse_event({"smart_state": {"warehouse": "ok"}}, 100, 100, 0) == ("full", None)


def test_durability_fires_once_and_rearms_after_repair():
    b = {}
    k, f = sn.durability_event(b, 25, 18)
    assert k == "durability_low" and f == {"low": True}
    k, f2 = sn.durability_event({"smart_notified": f}, 18, 12)
    assert k is None                                                        # already told
    k, f3 = sn.durability_event({"smart_notified": f2}, 5, 0)
    assert k == "business_stopped" and f3["stopped"]
    k, f4 = sn.durability_event({"smart_notified": f3}, 0, 100)             # repaired
    assert k is None and f4 == {}


def test_quiet_hours_wrap_midnight():
    u = {"notification_preferences": {"smart": {"quiet_start": 23, "quiet_end": 8}}, "timezone": "UTC"}
    at = lambda h: dt.datetime(2026, 1, 1, h, 0, tzinfo=dt.timezone.utc)  # noqa: E731
    assert sn.in_quiet_hours(u, at(23)) and sn.in_quiet_hours(u, at(3))
    assert not sn.in_quiet_hours(u, at(8)) and not sn.in_quiet_hours(u, at(15))
    u["notification_preferences"]["smart"]["quiet_enabled"] = False
    assert not sn.in_quiet_hours(u, at(3))


# ───────────── delivery ─────────────
def test_in_app_always_and_telegram_once(monkeypatch):
    async def go():
        db, sent = await _db(monkeypatch)
        r = await sn.send("u1", "warehouse_full", {"count": 3})
        assert r["telegram"] == "sent"
        assert len(sent.app()) == 1 and len(sent.tg()) == 1
        assert "Склад полон" in sent.app()[0]["title"]                       # Russian, by hand
        assert sent.app()[0]["pretranslated"] is True
    run(go())


def test_daily_limit_keeps_a_slot_for_critical(monkeypatch):
    async def go():
        db, sent = await _db(monkeypatch)                                    # default limit 2
        r1 = await sn.send("u1", "price_up", {"resource": "Energy", "change": 20, "old": 1, "new": 1.2})
        r2 = await sn.send("u1", "warehouse_almost_full", {"pct": 92})
        r3 = await sn.send("u1", "warehouse_full", {"count": 2})
        r4 = await sn.send("u1", "business_stopped", {"name": "Helios", "pct": 0})
        assert r1["telegram"] == "sent"
        assert r2["telegram"] == "daily_limit"          # non-critical can't take the last slot
        assert r3["telegram"] == "sent"                 # critical uses the reserved slot
        assert r4["telegram"] == "daily_limit"          # day's cap (2) reached
        assert len(sent.tg()) == 2 and len(sent.app()) == 4    # in-app always delivered
    run(go())


def test_limit_one(monkeypatch):
    async def go():
        db, sent = await _db(monkeypatch, {"notification_preferences": {"smart": {"daily_limit": 1, "quiet_enabled": False}}})
        assert (await sn.send("u1", "warehouse_full", {"count": 1}))["telegram"] == "sent"
        assert (await sn.send("u1", "business_stopped", {"name": "X", "pct": 0}))["telegram"] == "daily_limit"
    run(go())


def test_disabled_group_sends_nothing(monkeypatch):
    async def go():
        db, sent = await _db(monkeypatch, {"notification_preferences": {"smart": {"price": False, "quiet_enabled": False}}})
        r = await sn.send("u1", "price_up", {"resource": "Energy", "change": 20, "old": 1, "new": 1.2})
        assert r["reason"] == "disabled" and sent.calls == []
    run(go())


def test_quiet_hours_queue_then_flush_if_still_relevant(monkeypatch):
    async def go():
        db, sent = await _db(monkeypatch, {"timezone": "UTC",
                                            "notification_preferences": {"smart": {"quiet_enabled": True, "quiet_start": 0, "quiet_end": 23}},
                                            "smart_state": {"warehouse": "full"}})
        monkeypatch.setattr(sn, "in_quiet_hours", lambda u, now=None: True)
        r = await sn.send("u1", "warehouse_full", {"count": 2})
        assert r["telegram"] == "queued_quiet_hours" and len(sent.tg()) == 0 and len(sent.app()) == 1
        # quiet hours over, deliver_after passed, warehouse still full -> sent
        monkeypatch.setattr(sn, "in_quiet_hours", lambda u, now=None: False)
        await db.smart_tg_queue.update_many({}, {"$set": {"deliver_after": "2000-01-01T00:00:00+00:00"}})
        res = await sn.flush_queue()
        assert res["sent"] == 1 and len(sent.tg()) == 1
    run(go())


def test_queued_message_dropped_when_no_longer_relevant(monkeypatch):
    async def go():
        db, sent = await _db(monkeypatch, {"smart_state": {"warehouse": "full"}})
        monkeypatch.setattr(sn, "in_quiet_hours", lambda u, now=None: True)
        await sn.send("u1", "warehouse_full", {"count": 2})
        await db.users.update_one({"id": "u1"}, {"$set": {"smart_state.warehouse": "ok"}})   # player made room
        monkeypatch.setattr(sn, "in_quiet_hours", lambda u, now=None: False)
        await db.smart_tg_queue.update_many({}, {"$set": {"deliver_after": "2000-01-01T00:00:00+00:00"}})
        res = await sn.flush_queue()
        assert res == {"sent": 0, "dropped": 1} and len(sent.tg()) == 0
    run(go())


# ───────────── languages (all 9 written by hand, no external translator needed) ─────────────
def test_every_language_without_any_translator(monkeypatch):
    async def go():
        db, sent = await _db(monkeypatch, {"language": "id", "notification_preferences": {"smart": {"quiet_enabled": False}}})
        monkeypatch.delenv("LIBRETRANSLATE_URL", raising=False)
        await sn.send("u1", "warehouse_almost_full", {"pct": 93})
        assert sent.app()[0]["title"] == "📦 Gudang hampir penuh"
        assert "93%" in sent.app()[0]["message"]                             # placeholder filled
    run(go())


def test_japanese_is_japanese(monkeypatch):
    async def go():
        db, sent = await _db(monkeypatch, {"language": "ja", "notification_preferences": {"smart": {"quiet_enabled": False}}})
        await sn.send("u1", "warehouse_full", {"count": 4})
        assert sent.app()[0]["title"].startswith("📦 倉庫が満杯") and "4件" in sent.app()[0]["message"]
    run(go())


# ───────────── price watch ─────────────
def test_price_watch_alerts_producers_once_per_day(monkeypatch):
    async def go():
        db, sent = await _db(monkeypatch, {"notification_preferences": {"smart": {"quiet_enabled": False}}})
        await db.businesses.insert_one({"id": "b1", "owner": "u1", "business_type": "helios"})   # helios -> energy
        old_ts = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)).isoformat()
        await db.market_price_snapshots.insert_one({"ts": old_ts, "prices": {"energy": 0.0030}})
        for i in range(3):
            await db.market_listings.insert_one({"id": f"l{i}", "status": "active", "resource_type": "energy",
                                                 "price_per_unit": 0.0036, "seller_id": "x"})
        res = await sn.price_watch()
        await asyncio.sleep(0.05)
        assert res["alerts"] == 1 and "energy" in res["risen"]
        assert any("20%" in c["title"] or "20" in c["title"] for c in sent.app())
        res2 = await sn.price_watch()                                         # same day -> no repeat
        assert res2.get("alerts", 0) == 0
    run(go())


# ───────────── integration with the real economic_tick ─────────────
def _iso(h=0.0):
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=h)).isoformat()


async def _tick_world(monkeypatch, *, energy, durability=100):
    import background_tasks as bt
    db = mongomock_motor.AsyncMongoMockClient()["sn_tick"]
    monkeypatch.setattr(bt, "_get_shared_db", lambda: db)
    sn.init(db)
    events = []
    monkeypatch.setattr(sn, "send_bg", lambda u, k, v, ref=None: events.append((u.get("id"), k, v, ref)))
    await db.users.insert_one({"id": "p1", "language": "ru", "resources": {"energy": energy, "biomass": 50}})
    await db.businesses.insert_one({
        "id": "b1", "owner": "p1", "business_type": "helios", "level": 1, "durability": durability,
        "storage": {"capacity": 100, "items": {}}, "plot_id": "pl1",
        "last_tick": _iso(-1), "last_collection": _iso(-1), "last_wear_update": _iso(-1),
        "shift_started_at": _iso(-1), "shift_ends_at": _iso(7)})
    return bt, db, events


def test_tick_emits_warehouse_full_once(monkeypatch):
    async def go():
        bt, db, events = await _tick_world(monkeypatch, energy=50)          # 50+50 = 100/100 full
        await bt.economic_tick()
        assert [e[1] for e in events] == ["warehouse_full"]
        u = await db.users.find_one({"id": "p1"})
        assert u["smart_state"]["warehouse"] == "full"
        events.clear()
        await db.businesses.update_one({"id": "b1"}, {"$set": {"last_tick": _iso(-1)}})
        await bt.economic_tick()                                          # still full -> no repeat
        assert events == []
    asyncio.run(go())


def test_tick_emits_almost_full(monkeypatch):
    async def go():
        bt, db, events = await _tick_world(monkeypatch, energy=42)          # 92/100
        await bt.economic_tick()
        assert ("warehouse_almost_full" in [e[1] for e in events])
    asyncio.run(go())


def test_tick_emits_durability_low_once_and_persists_flag(monkeypatch):
    async def go():
        bt, db, events = await _tick_world(monkeypatch, energy=10, durability=20.5)
        await bt.economic_tick()                                          # wear pushes it below 20
        kinds = [e[1] for e in events]
        assert "durability_low" in kinds
        b = await db.businesses.find_one({"id": "b1"})
        assert b["smart_notified"].get("low") is True
        events.clear()
        await db.businesses.update_one({"id": "b1"}, {"$set": {"last_tick": _iso(-1)}})
        await bt.economic_tick()
        assert "durability_low" not in [e[1] for e in events]             # not again
    asyncio.run(go())


# ───────────── shift finished ─────────────
def test_shift_ended_is_sent_without_using_the_daily_limit(monkeypatch):
    async def go():
        db, sent = await _db(monkeypatch, {"notification_preferences": {"smart": {"daily_limit": 1, "quiet_enabled": False}}})
        assert (await sn.send("u1", "warehouse_full", {"count": 1}))["telegram"] == "sent"      # uses the only slot
        r = await sn.send("u1", "shift_ended", {"names": "Helios", "count": 1, "business_ids": "b1"}, ref="shift:x")
        assert r["telegram"] == "sent"                                                          # not capped
        assert "Смена закончилась" in sent.app()[-1]["title"]
    run(go())


def test_shift_ended_can_be_switched_off(monkeypatch):
    async def go():
        db, sent = await _db(monkeypatch, {"notification_preferences": {"smart": {"shift": False, "quiet_enabled": False}}})
        r = await sn.send("u1", "shift_ended", {"names": "Helios", "count": 1, "business_ids": "b1"})
        assert r["reason"] == "disabled" and sent.calls == []
    run(go())


def test_shift_ended_queued_at_night_dropped_if_restarted(monkeypatch):
    async def go():
        db, sent = await _db(monkeypatch)
        await db.businesses.insert_one({"id": "b1", "owner": "u1", "shift_ends_at": "2000-01-01T00:00:00+00:00"})
        monkeypatch.setattr(sn, "in_quiet_hours", lambda u, now=None: True)
        await sn.send("u1", "shift_ended", {"names": "Helios", "count": 1, "business_ids": "b1"}, ref="shift:a")
        # player restarted the shift before morning
        await db.businesses.update_one({"id": "b1"}, {"$set": {"shift_ends_at": _iso(5)}})
        monkeypatch.setattr(sn, "in_quiet_hours", lambda u, now=None: False)
        await db.smart_tg_queue.update_many({}, {"$set": {"deliver_after": "2000-01-01T00:00:00+00:00"}})
        assert await sn.flush_queue() == {"sent": 0, "dropped": 1}
    run(go())


def test_tick_emits_one_shift_ended_per_player_and_only_once(monkeypatch):
    async def go():
        import background_tasks as bt
        db = mongomock_motor.AsyncMongoMockClient()["sn_shift"]
        monkeypatch.setattr(bt, "_get_shared_db", lambda: db)
        sn.init(db)
        events = []
        monkeypatch.setattr(sn, "send_bg", lambda u, k, v, ref=None: events.append((u.get("id"), k, v, ref)))
        await db.users.insert_one({"id": "p1", "language": "ru", "resources": {"biomass": 50}})
        for bid, ended_h in (("b1", -0.5), ("b2", -0.2), ("b_old", -30)):
            await db.businesses.insert_one({"id": bid, "owner": "p1", "business_type": "helios", "level": 1,
                                            "durability": 100, "storage": {"capacity": 100, "items": {}}, "plot_id": "p" + bid,
                                            "last_tick": _iso(-1), "last_wear_update": _iso(-1), "shift_ends_at": _iso(ended_h)})
        await bt.economic_tick()
        shift = [e for e in events if e[1] == "shift_ended"]
        assert len(shift) == 1 and shift[0][2]["count"] == 2           # b1+b2 together, b_old ignored
        events.clear()
        await bt.economic_tick()
        assert not [e for e in events if e[1] == "shift_ended"]       # not again
    asyncio.run(go())


def test_telegram_copy_uses_the_language_of_the_players_telegram(monkeypatch):
    """App language ru, Telegram de: the bell gets Russian, Telegram gets German. Every language exists."""
    import asyncio
    import mongomock_motor
    import smart_notify as sn
    import core.notify as cn
    for kind, tpl in sn.TEXTS.items():
        assert set(sn.PROJECT_LANGS) <= set(tpl), kind                     # all 9 languages written by hand
    db = mongomock_motor.AsyncMongoMockClient()["sn_lang"]
    sn.init(db)
    sent = []
    async def fake_notify(_db, user, title, message, **kw):
        sent.append(("tg" if kw.get("in_app") is False else "app", title))
    monkeypatch.setattr(cn, "notify_user", fake_notify)
    async def go():
        await db.users.insert_one({"id": "u1", "language": "ru", "telegram_chat_id": "555", "telegram_notifications": True,
                                   "notification_preferences": {"smart": {"quiet_enabled": False}}})   # no quiet hours: not time-of-day dependent
        await db.telegram_mappings.insert_one({"chat_id": "555", "tg_language_code": "de-DE"})
        assert await sn._tg_lang(await db.users.find_one({"id": "u1"})) == "de"
        await sn.send("u1", "business_stopped", {"name": "Helios"}, ref="t1")
    asyncio.run(go())
    kinds = dict(sent)
    assert kinds["app"].startswith("⛔ Helios остановился")
    assert kinds["tg"].startswith("⛔ Helios gestoppt")
