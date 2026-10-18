"""Telegram profile photo as the avatar, unless the player set their own."""
import asyncio
import io

import pytest

mongomock_motor = pytest.importorskip("mongomock_motor")
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core import tg_avatar as ta


def run(c):
    return asyncio.run(c)


def png(color=(200, 30, 30), size=(400, 300)):
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", size, color).save(b, "PNG")
    return b.getvalue()


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("UPLOADS_ROOT", str(tmp_path))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:test")
    db = mongomock_motor.AsyncMongoMockClient()["av"]
    calls = {"bot": 0, "url": []}
    photo = {"bytes": png()}

    async def bot(tg_id):
        calls["bot"] += 1
        return photo["bytes"]

    async def url(u):
        calls["url"].append(u)
        return png((0, 0, 200)) if u else None
    monkeypatch.setattr(ta, "_bot_photo", bot)
    monkeypatch.setattr(ta, "_url_photo", url)
    return db, calls, photo, tmp_path


def test_telegram_photo_becomes_avatar_and_is_served(env):
    db, calls, _, tmp = env
    run(db.users.insert_one({"id": "u1", "telegram_id": 555001, "avatar": {"type": "initials", "initials": "U", "color": "#000"}}))
    url = run(ta.refresh(db, run(db.users.find_one({"id": "u1"}))))
    assert url and url.startswith("/api/avatars/tg_u1_") and url.endswith(".webp")
    u = run(db.users.find_one({"id": "u1"}))
    assert u["avatar"] == {"type": "url", "url": url} and u["avatar_source"] == "telegram"
    name = url.rsplit("/", 1)[-1]
    from PIL import Image
    im = Image.open(tmp / "avatars" / name)
    assert im.size == (256, 256) and im.format == "WEBP"                         # square crop, 256 px
    app = FastAPI(); app.include_router(ta.create_avatars_router())
    c = TestClient(app)
    r = c.get(url)
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp"
    assert c.get("/api/avatars/../../etc/passwd").status_code == 404
    assert c.get("/api/avatars/evil.webp").status_code == 404


def test_custom_avatar_is_never_replaced(env):
    db, calls, _, _ = env
    run(db.users.insert_one({"id": "u2", "telegram_id": "555002", "avatar": "data:image/png;base64,AAA", "custom_avatar_uploaded": True}))
    assert run(ta.refresh(db, run(db.users.find_one({"id": "u2"})), force=True)) is None
    assert run(db.users.find_one({"id": "u2"}))["avatar"] == "data:image/png;base64,AAA" and calls["bot"] == 0
    # a Google picture is left alone too; an old Telegram widget link is re-hosted
    assert ta.may_replace({"avatar": "https://lh3.googleusercontent.com/a/x"}) is False
    assert ta.may_replace({"avatar": {"type": "url", "url": "https://t.me/i/userpic/320/abc.jpg"}}) is True
    assert ta.may_replace({"avatar": None}) is True


def test_throttle_fallback_url_and_new_photo(env):
    db, calls, photo, tmp = env
    run(db.users.insert_one({"id": "u3", "telegram_chat_id": "555003", "avatar": None, "tg_photo_url": "https://t.me/i/userpic/320/x.jpg"}))
    first = run(ta.refresh(db, run(db.users.find_one({"id": "u3"}))))
    assert first
    assert run(ta.refresh(db, run(db.users.find_one({"id": "u3"})))) is None        # checked < 12 h ago
    # the bot can't see the photo (privacy) → the photo_url from the login is used
    photo["bytes"] = None
    second = run(ta.refresh(db, run(db.users.find_one({"id": "u3"})), force=True))
    assert second and second != first and calls["url"][-1] == "https://t.me/i/userpic/320/x.jpg"
    assert not (tmp / "avatars" / first.rsplit("/", 1)[-1]).exists()               # the old file is removed


def test_job_picks_players_without_own_avatar(env):
    db, calls, _, _ = env
    run(db.users.insert_many([
        {"id": "a", "telegram_id": 1001, "avatar": None},
        {"id": "b", "telegram_user_id": "1002", "avatar": "x", "custom_avatar_uploaded": True},
        {"id": "c", "email": "c@x", "avatar": None},                                  # no Telegram
    ]))
    r = run(ta.refresh_due(db))
    assert r == {"checked": 1, "updated": 1}
    assert run(db.users.find_one({"id": "a"}))["avatar"]["url"].startswith("/api/avatars/tg_a_")


def test_login_hook_saves_photo_url_and_refreshes(env, monkeypatch):
    db, calls, _, _ = env
    import routes.telegram_auth as tga

    async def tok(_db, user):
        return "token"
    monkeypatch.setattr(tga, "_issue_token_for", tok)
    run(db.users.insert_one({"id": "u9", "telegram_id": 555009, "username": "tg9", "avatar": {"type": "initials"}}))

    async def go():
        u = await db.users.find_one({"id": "u9"})
        r = await tga._login_or_2fa(db, u, photo_url="https://t.me/i/userpic/320/u9.jpg")
        await asyncio.sleep(0.05)                                                   # the refresh runs in the background
        for t in list(ta._TASKS):
            await t
        return r
    r = run(go())
    assert r["token"] == "token"
    u = run(db.users.find_one({"id": "u9"}))
    assert u["tg_photo_url"] == "https://t.me/i/userpic/320/u9.jpg" and u["avatar"]["url"].startswith("/api/avatars/tg_u9_")


def test_generated_initials_svg_is_replaced():
    assert ta.may_replace({"avatar": "data:image/svg+xml;base64,PHN2Zz4="}) is True
    assert ta.may_replace({"avatar": "data:image/png;base64,AAA"}) is False         # an uploaded photo without the flag
