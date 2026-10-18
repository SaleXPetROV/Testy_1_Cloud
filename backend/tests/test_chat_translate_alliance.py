"""Translate button in the alliance chat: members only; no translator → 503 (not a crash)."""
import asyncio

import pytest

mongomock_motor = pytest.importorskip("mongomock_motor")
from fastapi import FastAPI
from fastapi.testclient import TestClient

import chat_handler as ch


@pytest.fixture
def client(monkeypatch):
    db = mongomock_motor.AsyncMongoMockClient()["tr"]
    ch.set_db(db)
    users = {"tok-a": {"id": "a"}, "tok-b": {"id": "b"}}

    async def who(tok):
        return users.get(tok)
    monkeypatch.setattr(ch, "get_current_user_from_token", who)
    import security.ws_rate_limit as rl
    monkeypatch.setattr(rl, "check_ws_msg_rate", lambda *_: True)
    state = {"fail": False}

    async def tr(text, lang):
        if state["fail"]:
            raise RuntimeError("no provider")
        return f"[{lang}] {text}"
    monkeypatch.setattr(ch, "translate_text", tr)
    asyncio.run(db.alliance_members.insert_one({"user_id": "a", "alliance_id": "al1"}))
    asyncio.run(db.chat_messages.insert_many([
        {"id": "m1", "chat_type": "alliance", "alliance_id": "al1", "content": "Hi team", "lang": "en", "sender_id": "a"},
        {"id": "m2", "chat_type": "global", "content": "Hello all", "lang": "en", "sender_id": "b"},
    ]))
    app = FastAPI(); app.include_router(ch.chat_router, prefix="/api")
    return TestClient(app), state


def post(c, tok, mid, lang="ru"):
    return c.post("/api/chat/translate", json={"message_id": mid, "target_lang": lang}, headers={"Authorization": f"Bearer {tok}"})


def test_member_translates_alliance_message(client):
    c, _ = client
    r = post(c, "tok-a", "m1")
    assert r.status_code == 200 and r.json()["translation"] == "[ru] Hi team"
    assert post(c, "tok-a", "m1", "id").status_code == 200          # Indonesian is supported


def test_outsider_cannot_translate_alliance_message(client):
    c, _ = client
    assert post(c, "tok-b", "m1").status_code == 404
    assert post(c, "tok-b", "m2").status_code == 200                # global stays open


def test_no_translator_is_503(client):
    c, state = client
    state["fail"] = True
    r = post(c, "tok-a", "m1", "de")
    assert r.status_code == 503 and r.json()["detail"]["code"] == "translation_unavailable"
