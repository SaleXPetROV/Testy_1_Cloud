"""Chests are never left closed: opened right when given, the player is notified with a picture and text in
their language; no warehouse room → the chest waits (told once) and opens by itself later."""
import asyncio
import datetime as dt
import io

import pytest

mongomock_motor = pytest.importorskip("mongomock_motor")

import minigame_rewards as mr  # noqa: E402
from core import chest_notify as cn  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class Rec:
    """Records the notifications instead of sending them."""
    def __init__(self, monkeypatch):
        self.opened, self.wait = [], []

        async def opened(db, uid, uc, results, telegram=True):
            self.opened.append((uid, uc["id"], len(results), telegram))

        async def wait(db, uid, uc, need, telegram=True):
            self.wait.append((uid, uc["id"], need, telegram))
        monkeypatch.setattr(cn, "notify_opened", opened)
        monkeypatch.setattr(cn, "notify_no_space", wait)
        monkeypatch.setattr(cn, "spawn", lambda coro: asyncio.get_event_loop().create_task(coro))


def room(monkeypatch, free):
    import core.warehouse as wh

    async def fake(_db, _u, **k):
        return wh.state(0, free["n"])
    monkeypatch.setattr(wh, "user_warehouse", fake)


async def setup(db):
    await mr.ensure_indexes(db)
    await db.users.insert_one({"id": "p1", "language": "ru", "resources": {}})
    await db.mg_containers.insert_one({"id": "c1", "name": "Сундук", "rolls": 1, "is_active": True, "rows": [
        {"kind": "resource", "resource": "energy", "min": 10, "max": 10, "weight": 1}]})


def test_given_chest_is_opened_at_once_and_notified(monkeypatch):
    rec = Rec(monkeypatch); room(monkeypatch, {"n": 10 ** 6})
    db = mongomock_motor.AsyncMongoMockClient()["ca"]

    async def go():
        await setup(db)
        uc = await mr.grant_container(db, "p1", "c1", "admin", "x")
        await asyncio.sleep(0)
        doc = await db.mg_user_containers.find_one({"id": uc["id"]})
        u = await db.users.find_one({"id": "p1"})
        return uc, doc, u
    uc, doc, u = run(go())
    assert uc["status"] == "opened" and doc["status"] == "opened" and u["resources"]["energy"] == 10
    assert uc["results"][0]["image_url"] == f"/sprites/resources/{uc['results'][0]['resource']}.webp"   # the resource itself
    assert rec.opened == [("p1", uc["id"], 1, True)]          # admin grant → in-app + Telegram


def test_game_chest_in_app_only_and_returned_for_the_opening(monkeypatch):
    rec = Rec(monkeypatch); room(monkeypatch, {"n": 10 ** 6})
    db = mongomock_motor.AsyncMongoMockClient()["ca2"]

    async def go():
        await setup(db)
        cfg = {"chest_container_id": "c1", "chests_per_day": 4, "chest_min_stars": 2}
        out = await mr.game_chest(db, "p1", "s1", 3, cfg, notify="app")
        await asyncio.sleep(0)
        return out
    out = run(go())
    assert out["given"] and out["opened"] and out["chest"]["results"][0]["amount"] == 10
    assert rec.opened and rec.opened[0][3] is False             # the app shows it: no Telegram message


def test_no_room_waits_told_once_then_opens_by_itself(monkeypatch):
    rec = Rec(monkeypatch); free = {"n": 0}; room(monkeypatch, free)
    db = mongomock_motor.AsyncMongoMockClient()["ca3"]

    async def go():
        await setup(db)
        uc = await mr.grant_container(db, "p1", "c1", "game", "s1")
        await asyncio.sleep(0)
        r1 = await mr.open_waiting_containers(db)                # still no room: no second «free space» message
        await asyncio.sleep(0)
        free["n"] = 10 ** 6
        r2 = await mr.open_waiting_containers(db)
        await asyncio.sleep(0)
        doc = await db.mg_user_containers.find_one({"id": uc["id"]})
        return uc, r1, r2, doc
    uc, r1, r2, doc = run(go())
    assert uc["status"] == "unopened" and uc["waiting_space"] == 10
    assert r1 == {"opened": 0, "waiting": 1} and r2 == {"opened": 1, "waiting": 0}
    assert len(rec.wait) == 1 and doc["status"] == "opened"
    assert rec.opened == [("p1", uc["id"], 1, True)]             # opened in the background → Telegram too


def test_text_in_the_players_language_and_fallback_names(monkeypatch):
    monkeypatch.delenv("LIBRETRANSLATE_URL", raising=False)
    monkeypatch.delenv("EMERGENT_LLM_KEY", raising=False)
    db = mongomock_motor.AsyncMongoMockClient()["ca4"]
    res = [{"kind": "resource", "resource": "quartz", "amount": 35},
           {"kind": "puzzle", "name": "Neon island", "name_i18n": {"ru": "Неоновый остров"}, "have": 6}]
    t_ru, m_ru = run(cn.build_text(db, "ru", {"name": "Сундук Сортировщика"}, res))
    assert t_ru == "🎁 Сундук открыт!" and "Кварц +35" in m_ru and "Неоновый остров" in m_ru and "6/9" in m_ru
    t_id, m_id = run(cn.build_text(db, "id", {"name": "Sorter chest"}, res))   # no Indonesian name, no LibreTranslate → English
    assert t_id == "🎁 Peti dibuka!" and "Quartz +35" in m_id and "Neon island" in m_id
    assert cn.norm_lang("pt-BR") == "en" and cn.norm_lang("in") == "id"


def test_picture_of_what_dropped(monkeypatch, tmp_path):
    from PIL import Image
    monkeypatch.setenv("UPLOADS_ROOT", str(tmp_path))
    import minigame_rewards_routes as mrr
    Image.new("RGBA", (200, 200), (255, 0, 0, 255)).save(mrr.img_dir() / "puzzle_x_3.webp", "WEBP")
    db = mongomock_motor.AsyncMongoMockClient()["ca5"]
    png = run(cn.build_image(db, [{"kind": "puzzle", "have": 3, "image_url": "/api/minigames/img/puzzle_x_3.webp"},
                                  {"kind": "resource", "resource": "quartz", "amount": 35, "image_url": "/sprites/resources/quartz.webp"}]))
    im = Image.open(io.BytesIO(png))
    assert im.format == "PNG" and im.width > im.height                  # two tiles side by side


def test_notification_in_app_and_telegram_photo(monkeypatch, tmp_path):
    from PIL import Image
    monkeypatch.setenv("UPLOADS_ROOT", str(tmp_path))
    import minigame_rewards_routes as mrr
    import telegram_bot as tg
    Image.new("RGBA", (200, 200), (0, 255, 0, 255)).save(mrr.img_dir() / "puzzle_y_1.webp", "WEBP")
    sent = []

    class Bot:
        async def send_photo(self, chat_id, photo, caption="", parse_mode="HTML", reply_markup=None):
            sent.append(("photo", chat_id, photo[:22], caption)); return True

        async def send_message(self, chat_id, text, **k):
            sent.append(("msg", chat_id, text)); return True
    monkeypatch.setattr(tg, "telegram_bot", Bot())
    db = mongomock_motor.AsyncMongoMockClient()["ca6"]

    async def go():
        await db.users.insert_one({"id": "p9", "language": "de", "telegram_chat_id": "555"})
        await db.mg_containers.insert_one({"id": "c9", "name": "Truhe", "name_i18n": {"de": "Sortierer-Truhe"}})
        await cn.notify_opened(db, "p9", {"id": "uc9", "container_id": "c9"},
                               [{"kind": "puzzle", "name": "Insel", "have": 1, "image_url": "/api/minigames/img/puzzle_y_1.webp"}])
        return await db.notifications.find_one({"user_id": "p9"})
    n = run(go())
    assert n["title"] == "🎁 Truhe geöffnet!" and "„Sortierer-Truhe“" in n["message"] and "Puzzleteil" in n["message"]
    assert n["image_url"] == "/api/minigames/img/chest_uc9.webp" and (mrr.img_dir() / "chest_uc9.webp").is_file()
    assert sent and sent[0][0] == "photo" and sent[0][1] == "555" and sent[0][2].startswith("data:image/png;base64")
    assert "Truhe geöffnet" in sent[0][3]
