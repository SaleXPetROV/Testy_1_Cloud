"""Tests for the in-game quest engine (backend/quests.py).

Runs against an in-memory Mongo (mongomock-motor), no server needed:
    pip install mongomock-motor
    cd backend && python -m pytest tests/test_quests.py -q
"""
import asyncio

import pytest

mongomock_motor = pytest.importorskip("mongomock_motor")
from fastapi import HTTPException  # noqa: E402

import quests  # noqa: E402


def run(coro):
    return asyncio.run(coro)


async def _fresh_db(with_business=True, uid="u1"):
    db = mongomock_motor.AsyncMongoMockClient()["test_quests"]
    quests.init(db)
    quests._tpl_cache["items"] = []
    quests._seeded = False
    quests._indexes_ready = False
    await db.users.insert_one({"id": uid, "email": f"{uid}@x.io", "language": "ru",
                               "balance_ton": 1.0, "bonus_balance": 0.0, "xp": 0})
    if with_business:
        await db.businesses.insert_one({"id": f"b-{uid}", "owner": uid, "business_type": "helios", "level": 1})
    return db


def test_period_keys_are_msk_day_and_iso_week():
    assert quests.period_key("onboarding") == "once"
    assert len(quests.period_key("daily")) == 10
    assert "-W" in quests.period_key("weekly")


def test_event_progress_ready_and_atomic_claim():
    async def go():
        db = await _fresh_db()
        await quests.quest_event("u1", "market_list", 1)
        ov = await quests.build_overview("u1", "ru")
        ob = {x["id"]: x for x in ov["onboarding"]["items"]}
        assert ob["ob_open_business"]["status"] == "ready"      # state-based
        assert ob["ob_first_list"]["status"] == "ready"      # event-based
        assert ob["ob_first_sale"]["status"] == "active"
        assert ov["next"]["action"] == "claim"

        r = await quests.claim("u1", "ob_first_list", "ru")
        assert {k: r["granted"][k] for k in ("city", "xp", "capped")} == {"city": 15, "xp": 20, "capped": False}
        with pytest.raises(HTTPException) as e:
            await quests.claim("u1", "ob_first_list", "ru")
        assert e.value.status_code == 409
        with pytest.raises(HTTPException) as e:
            await quests.claim("u1", "ob_first_sale", "ru")
        assert e.value.status_code == 400

        u = await db.users.find_one({"id": "u1"})
        assert abs(u["bonus_balance"] - 0.015) < 1e-9   # bonus, not real balance
        assert u["balance_ton"] == 1.0
        assert u["xp"] == 20
        tx = await db.transactions.find_one({"user_id": "u1", "tx_type": "quest_reward"})
        assert tx and tx["reward_city"] == 15
    run(go())


def test_concurrent_claims_pay_once():
    async def go():
        db = await _fresh_db()
        await quests.quest_event("u1", "market_list", 1)
        await quests.build_overview("u1", "ru")
        res = await asyncio.gather(*[quests.claim("u1", "ob_first_list", "ru") for _ in range(5)],
                                   return_exceptions=True)
        assert sum(1 for x in res if isinstance(x, dict)) == 1
        u = await db.users.find_one({"id": "u1"})
        assert abs(u["bonus_balance"] - 0.015) < 1e-9
    run(go())


def test_unique_event_is_counted_once():
    async def go():
        await _fresh_db()
        for _ in range(3):
            await quests.quest_event("u1", "market_list", 1, unique="lot:42")
        ids = await quests.ensure_assignment("u1", "daily")
        if "d_list_lot" in ids:
            doc = await quests._DB.user_quests.find_one({"user_id": "u1", "quest_id": "d_list_lot"})
            assert doc["status"] == "ready"
        # the log keeps one row only
        assert await quests._DB.quest_event_log.count_documents({"user_id": "u1", "unique": "lot:42"}) == 1
    run(go())


def test_daily_goals_need_a_business_and_one_per_difficulty():
    async def go():
        await _fresh_db(with_business=False, uid="nobiz")
        assert await quests.ensure_assignment("nobiz", "daily") == []
        await _fresh_db(uid="biz")
        ids = await quests.ensure_assignment("biz", "daily")
        tpls = {t["id"]: t for t in await quests.get_templates()}
        assert sorted(tpls[i]["difficulty"] for i in ids) == ["easy", "good", "medium"]
        assert await quests.ensure_assignment("biz", "daily") == ids   # stable for the day
    run(go())


def test_daily_bonus_cap():
    async def go():
        db = await _fresh_db()
        await db.tasks_config.insert_one({"key": "quest_limits", "daily_bonus_cap_city": 25})
        await quests.build_overview("u1", "ru")
        r1 = await quests.claim("u1", "ob_open_business", "ru")      # 20
        await quests.quest_event("u1", "market_list", 1)
        r2 = await quests.claim("u1", "ob_first_list", "ru")      # 15 -> capped to 5
        assert r1["granted"]["city"] == 20
        assert r2["granted"]["city"] == 5 and r2["granted"]["capped"] is True
    run(go())


def test_sales_between_linked_accounts_do_not_count():
    async def go():
        db = await _fresh_db(uid="seller")
        await db.users.insert_one({"id": "twin", "email": "t@x.io"})
        await db.users.insert_one({"id": "stranger", "email": "s@x.io"})
        await db.fingerprints.insert_many([
            {"user_id": "seller", "visitor_id": "dev-1"},
            {"user_id": "twin", "visitor_id": "dev-1"},
            {"user_id": "stranger", "visitor_id": "dev-2"},
        ])
        await quests.sale_event("seller", "twin", 5)
        doc = await db.user_quests.find_one({"user_id": "seller", "quest_id": "ob_first_sale"})
        assert doc is None
        await quests.sale_event("seller", "stranger", 5)
        doc = await db.user_quests.find_one({"user_id": "seller", "quest_id": "ob_first_sale"})
        assert doc["status"] == "ready"
    run(go())


def test_onboarding_groups_and_final_reward(monkeypatch):
    async def go():
        db = await _fresh_db()
        monkeypatch.setenv("ONBOARDING_MODE", "quests")
        assert await quests.onboarding_group(db, await db.users.find_one({"id": "u1"})) == "quests"
        # an old player who already finished the tutorial stays "legacy"
        await db.users.insert_one({"id": "old", "tutorial_completed": True})
        assert await quests.onboarding_group(db, await db.users.find_one({"id": "old"})) == "legacy"
        # the group is sticky even if the mode changes
        monkeypatch.setenv("ONBOARDING_MODE", "tutorial")
        assert await quests.onboarding_group(db, await db.users.find_one({"id": "u1"})) == "quests"

        with pytest.raises(HTTPException):
            await quests.grant_onboarding_reward("u1", "neuro_core")    # chain not finished
        for ev in ("shift_start", "market_list", "market_buy", "repair", "upgrade"):
            await quests.quest_event("u1", ev, 1)
        await quests.sale_event("u1", None, 1)
        await db.tasks_config.insert_one({"key": "quest_limits", "daily_bonus_cap_city": 10000})
        ov = await quests.build_overview("u1", "ru")
        for x in ov["onboarding"]["items"]:
            await quests.claim("u1", x["id"], "ru")
        with pytest.raises(HTTPException):
            await quests.grant_onboarding_reward("u1", "not_a_resource")
        r = await quests.grant_onboarding_reward("u1", "gold_bill")
        assert r["reward"] == "gold_bill"
        with pytest.raises(HTTPException) as e:
            await quests.grant_onboarding_reward("u1", "gold_bill")
        assert e.value.status_code == 409
        u = await db.users.find_one({"id": "u1"})
        assert u["resources"]["gold_bill_tutorial"] == 1 and u["tutorial_t3_reward_granted"] is True
    run(go())


def test_has_daily_done_unlocks_daily_reward():
    async def go():
        await _fresh_db()
        assert await quests.has_daily_done("u1") is False
        ids = await quests.ensure_assignment("u1", "daily")
        tpls = {t["id"]: t for t in await quests.get_templates()}
        easy = next(i for i in ids if tpls[i]["difficulty"] == "easy")
        await quests.quest_event("u1", tpls[easy]["event"], tpls[easy]["target"])
        assert await quests.has_daily_done("u1") is True
    run(go())


# ───────────────────────── translations (LibreTranslate) ─────────────────────────
def _fake_lt(monkeypatch, fail_langs=()):
    import translation_service
    calls = []

    async def fake(text, target, source="en"):
        calls.append((target, text))
        if target in fail_langs:
            raise ValueError("placeholder lost in translation")
        return f"[{target}] {text}"
    monkeypatch.setenv("LIBRETRANSLATE_URL", "http://lt.test")
    monkeypatch.setattr(translation_service, "translate_libre_protected", fake)
    return calls


def test_quest_texts_translated_and_saved(monkeypatch):
    async def go():
        db = await _fresh_db()
        calls = _fake_lt(monkeypatch)
        st = await quests.translate_templates(["id"])
        assert st["translated"] > 0 and st["failed"] == 0
        t = await db.quest_templates.find_one({"id": "ob_first_sale"})
        assert t["title"]["id"] == "[id] Sell a resource"
        assert t["i18n_auto"]["title"]["id"] is True
        assert t["title"]["ru"] == "Продайте ресурс"            # hand-written untouched
        n = len(calls)
        await quests.translate_templates(["id"])               # saved -> no new calls
        assert len(calls) == n
        ov = await quests.build_overview("u1", "id")
        assert ov["onboarding"]["items"][0]["title"].startswith("[id] ")
    run(go())


def test_failed_translation_is_not_saved(monkeypatch):
    async def go():
        db = await _fresh_db()
        _fake_lt(monkeypatch, fail_langs=("ja",))
        st = await quests.translate_templates(["ja"])
        assert st["translated"] == 0 and st["failed"] > 0
        t = await db.quest_templates.find_one({"id": "ob_first_sale"})
        assert "ja" not in t["title"]
        ov = await quests.build_overview("u1", "ja")          # falls back to English
        assert ov["onboarding"]["items"][0]["title"] == "Open your first business"
    run(go())


def test_manual_text_wins_and_en_change_retranslates(monkeypatch):
    async def go():
        db = await _fresh_db()
        _fake_lt(monkeypatch)
        await quests.translate_templates(["id", "es"])
        # admin writes Indonesian by hand -> machine never overwrites it
        await db.quest_templates.update_one({"id": "ob_first_sale"},
                                            {"$set": {"title.id": "Jual sumber daya"},
                                             "$unset": {"i18n_auto.title.id": ""}})
        await quests.translate_templates(["id"], force=True)
        t = await db.quest_templates.find_one({"id": "ob_first_sale"})
        assert t["title"]["id"] == "Jual sumber daya"
        # force re-makes machine translations only
        assert t["title"]["es"].startswith("[es] ")
    run(go())


def test_without_libretranslate_nothing_breaks(monkeypatch):
    async def go():
        await _fresh_db()
        monkeypatch.delenv("LIBRETRANSLATE_URL", raising=False)
        st = await quests.translate_templates(["id"])
        assert st["translated"] == 0 and st["errors"]
        ov = await quests.build_overview("u1", "id")
        assert ov["onboarding"]["items"][0]["title"] == "Open your first business"
        assert await quests.msg("not_ready", "ru") == "Задание ещё не выполнено"
        assert await quests.msg("not_ready", "id") == "Quest is not completed yet"
    run(go())


def test_daily_reward_needs_no_trading_only_a_daily_goal(monkeypatch):
    """The old gate (buy 30 + sell 95) is gone: a finished daily goal unlocks it."""
    async def go():
        await _fresh_db()
        assert await quests.has_daily_done("u1") is False
        ids = await quests.ensure_assignment("u1", "daily")
        tpls = {t["id"]: t for t in await quests.get_templates()}
        easy = next(i for i in ids if tpls[i]["difficulty"] == "easy")
        await quests.quest_event("u1", tpls[easy]["event"], tpls[easy]["target"])
        assert await quests.has_daily_done("u1") is True     # no buy/sell needed
    run(go())


def test_collect_quests_retired_and_replaced():
    """Production is auto-collected, so 'collect' quests are switched off."""
    async def go():
        db = await _fresh_db()
        # an old database that still has the retired templates active
        await db.quest_templates.insert_one({"id": "ob_first_collect", "kind": "onboarding", "order": 3,
                                             "event": "collect", "target": 1, "active": True,
                                             "title": {"en": "Collect"}, "description": {"en": "x"}})
        await db.quest_templates.insert_one({"id": "d_collect", "kind": "daily", "difficulty": "easy",
                                             "event": "collect", "target": 1, "active": True, "requires_business": True,
                                             "title": {"en": "Collect"}, "description": {"en": "x"}})
        # today's assignment was made before the change and contains d_collect
        await db.quest_assignments.insert_one({"user_id": "u1", "kind": "daily",
                                               "period_key": quests.period_key("daily"),
                                               "quest_ids": ["d_collect", "d_sell20", "d_list_lot"]})
        ov = await quests.build_overview("u1", "ru")
        ob_ids = [x["id"] for x in ov["onboarding"]["items"]]
        assert "ob_first_collect" not in ob_ids and "ob_first_list" in ob_ids
        assert ob_ids.index("ob_first_buy") < ob_ids.index("ob_first_list") < ob_ids.index("ob_first_sale")
        daily_ids = [x["id"] for x in ov["daily"]["items"]]
        assert "d_collect" not in daily_ids and len(daily_ids) == 3          # swapped, still 3 goals
        tpls = {t["id"]: t for t in await quests.get_templates()}
        assert all(tpls[i]["event"] != "collect" for i in daily_ids)
    run(go())
