"""A chest is always opened automatically (right after it is given: a game, a reward threshold, a leaderboard
prize, the admin). The player then gets a notification — in the app and in Telegram — with a PICTURE of what
dropped (the resources themselves, the puzzle piece itself) and the text in the player's language.

Texts are written for the 9 languages of the project. Names that exist only in some languages (resources in
Indonesian, chest / puzzle names the admin typed in one language) are translated with LibreTranslate
(translation_service.translate_cached, cached in the database); without it the English / original name is used.

If the warehouse has no room the chest waits (nothing is lost, no reroll) and opens by itself as soon as there is
room (background job every 10 minutes); the player is told once how many places to free.
"""
from __future__ import annotations

import asyncio
import base64
import html
import io
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

LANGS = ("en", "ru", "es", "zh", "fr", "de", "ja", "ko", "id")

# resource names in the languages of the app (from frontend/src/lib/resourceConfig.js)
RES_NAMES: Dict[str, Dict[str, str]] = {
 "energy": {
  "en": "Energy",
  "ru": "Энергия",
  "es": "Energía",
  "zh": "能源",
  "fr": "Énergie",
  "de": "Energie",
  "ja": "エネルギー",
  "ko": "에너지"
 },
 "scrap": {
  "en": "Metal",
  "ru": "Металл",
  "es": "Metal",
  "zh": "金属",
  "fr": "Métal",
  "de": "Metall",
  "ja": "金属",
  "ko": "금속"
 },
 "quartz": {
  "en": "Quartz",
  "ru": "Кварц",
  "es": "Cuarzo",
  "zh": "石英",
  "fr": "Quartz",
  "de": "Quarz",
  "ja": "クォーツ",
  "ko": "석영"
 },
 "cu": {
  "en": "Computing",
  "ru": "Вычисления",
  "es": "Cómputo",
  "zh": "算力",
  "fr": "Calcul",
  "de": "Berechnung",
  "ja": "計算",
  "ko": "컴퓨팅"
 },
 "traffic": {
  "en": "Traffic",
  "ru": "Трафик",
  "es": "Tráfico",
  "zh": "流量",
  "fr": "Trafic",
  "de": "Verkehr",
  "ja": "トラフィック",
  "ko": "트래픽"
 },
 "cooling": {
  "en": "Cooling",
  "ru": "Холод",
  "es": "Frío",
  "zh": "冷却",
  "fr": "Froid",
  "de": "Kühlung",
  "ja": "冷却",
  "ko": "냉각"
 },
 "biomass": {
  "en": "Biomass",
  "ru": "Биомасса",
  "es": "Biomasa",
  "zh": "生物质",
  "fr": "Biomasse",
  "de": "Biomasse",
  "ja": "バイオマス",
  "ko": "바이오매스"
 },
 "chips": {
  "en": "Chip",
  "ru": "Чип",
  "es": "Chip",
  "zh": "芯片",
  "fr": "Puce",
  "de": "Chip",
  "ja": "チップ",
  "ko": "칩"
 },
 "neurocode": {
  "en": "AI Model",
  "ru": "ИИ-Модель",
  "es": "Modelo IA",
  "zh": "AI模型",
  "fr": "Modèle IA",
  "de": "KI-Modell",
  "ja": "AIモデル",
  "ko": "AI 모델"
 },
 "nft": {
  "en": "NFT Art",
  "ru": "NFT-Арт",
  "es": "Arte NFT",
  "zh": "NFT艺术",
  "fr": "Art NFT",
  "de": "NFT-Kunst",
  "ja": "NFTアート",
  "ko": "NFT 아트"
 },
 "vr_experience": {
  "en": "VR Content",
  "ru": "VR-Контент",
  "es": "Contenido VR",
  "zh": "VR内容",
  "fr": "Contenu VR",
  "de": "VR-Inhalt",
  "ja": "VRコンテンツ",
  "ko": "VR 콘텐츠"
 },
 "logistics": {
  "en": "Fuel",
  "ru": "Топливо",
  "es": "Combustible",
  "zh": "燃料",
  "fr": "Carburant",
  "de": "Treibstoff",
  "ja": "燃料",
  "ko": "연료"
 },
 "profit_ton": {
  "en": "Cyber Food",
  "ru": "Кибер-фуд",
  "es": "Ciber-comida",
  "zh": "赛博食品",
  "fr": "Cyber-food",
  "de": "Cyber-Food",
  "ja": "サイバーフード",
  "ko": "사이버 푸드"
 },
 "repair_kits": {
  "en": "Repair Kit",
  "ru": "Ремкомплект",
  "es": "Kit de reparación",
  "zh": "维修包",
  "fr": "Kit de réparation",
  "de": "Reparaturset",
  "ja": "修理キット",
  "ko": "수리 키트"
 },
 "neuro_core": {
  "en": "Neuro Core",
  "ru": "Нейро-ядро",
  "es": "Núcleo Neural",
  "zh": "神经核心",
  "fr": "Noyau Neural",
  "de": "Neuro-Kern",
  "ja": "ニューロコア",
  "ko": "뉴로 코어"
 },
 "gold_bill": {
  "en": "Gold Bill",
  "ru": "Золотой вексель",
  "es": "Billete de Oro",
  "zh": "金票",
  "fr": "Billet d’Or",
  "de": "Goldschein",
  "ja": "ゴールドビル",
  "ko": "골드 빌"
 },
 "license_token": {
  "en": "License",
  "ru": "Лицензия",
  "es": "Licencia",
  "zh": "许可证",
  "fr": "Licence",
  "de": "Lizenz",
  "ja": "ライセンス",
  "ko": "라이선스"
 },
 "luck_chip": {
  "en": "Luck Chip",
  "ru": "Фишка удачи",
  "es": "Ficha de Suerte",
  "zh": "幸运筹码",
  "fr": "Jeton de Chance",
  "de": "Glückschip",
  "ja": "ラックチップ",
  "ko": "럭 칩"
 },
 "war_protocol": {
  "en": "War Protocol",
  "ru": "Боевой протокол",
  "es": "Protocolo de Guerra",
  "zh": "战争协议",
  "fr": "Protocole de Guerre",
  "de": "Kriegsprotokoll",
  "ja": "ウォープロトコル",
  "ko": "워 프로토콜"
 },
 "bio_module": {
  "en": "Bio Module",
  "ru": "Био-модуль",
  "es": "Módulo Bio",
  "zh": "生物模块",
  "fr": "Module Bio",
  "de": "Bio-Modul",
  "ja": "バイオモジュール",
  "ko": "바이오 모듈"
 },
 "gateway_code": {
  "en": "Gateway Code",
  "ru": "Код шлюза",
  "es": "Código de Portal",
  "zh": "网关代码",
  "fr": "Code Passerelle",
  "de": "Gateway-Code",
  "ja": "ゲートウェイコード",
  "ko": "게이트웨이 코드"
 }
}

TEXT = {
    "title": {"en": "🎁 Chest opened!", "ru": "🎁 Сундук открыт!", "es": "🎁 ¡Cofre abierto!", "zh": "🎁 宝箱已打开！",
              "fr": "🎁 Coffre ouvert !", "de": "🎁 Truhe geöffnet!", "ja": "🎁 宝箱が開きました！", "ko": "🎁 상자가 열렸습니다!",
              "id": "🎁 Peti dibuka!"},
    "intro": {"en": "«{c}» opened automatically. You got:", "ru": "«{c}» открылся автоматически. Выпало:",
              "es": "«{c}» se abrió automáticamente. Obtuviste:", "zh": "「{c}」已自动打开。获得：",
              "fr": "« {c} » s’est ouvert automatiquement. Vous avez obtenu :", "de": "„{c}“ wurde automatisch geöffnet. Du hast erhalten:",
              "ja": "「{c}」が自動で開きました。獲得：", "ko": "«{c}»이(가) 자동으로 열렸습니다. 획득:",
              "id": "«{c}» terbuka otomatis. Kamu mendapat:"},
    "piece": {"en": "Puzzle piece «{n}» ({k}/9)", "ru": "Кусочек пазла «{n}» ({k}/9)", "es": "Pieza del puzle «{n}» ({k}/9)",
              "zh": "拼图碎片「{n}」（{k}/9）", "fr": "Pièce du puzzle « {n} » ({k}/9)", "de": "Puzzleteil „{n}“ ({k}/9)",
              "ja": "パズルのピース「{n}」（{k}/9）", "ko": "퍼즐 조각 «{n}» ({k}/9)", "id": "Kepingan puzzle «{n}» ({k}/9)"},
    "empty": {"en": "Nothing dropped this time.", "ru": "В этот раз ничего не выпало.", "es": "Esta vez no salió nada.",
              "zh": "这次什么也没有。", "fr": "Rien cette fois.", "de": "Diesmal war nichts drin.", "ja": "今回は何も出ませんでした。",
              "ko": "이번에는 아무것도 나오지 않았습니다.", "id": "Kali ini tidak ada apa-apa."},
    "wait_title": {"en": "📦 The chest is waiting for space", "ru": "📦 Сундук ждёт места на складе", "es": "📦 El cofre espera espacio",
                   "zh": "📦 宝箱在等待仓库空间", "fr": "📦 Le coffre attend de la place", "de": "📦 Die Truhe wartet auf Platz",
                   "ja": "📦 宝箱は倉庫の空きを待っています", "ko": "📦 상자가 창고 공간을 기다립니다", "id": "📦 Peti menunggu ruang gudang"},
    "wait_text": {"en": "Free up {n} warehouse places — «{c}» will open by itself and you will get a notification.",
                  "ru": "Освободите {n} мест на складе — «{c}» откроется сам, и придёт уведомление.",
                  "es": "Libera {n} espacios del almacén: «{c}» se abrirá solo y recibirás un aviso.",
                  "zh": "请腾出 {n} 个仓库空间——「{c}」将自动打开并通知你。",
                  "fr": "Libérez {n} places dans l’entrepôt — « {c} » s’ouvrira tout seul et vous serez prévenu.",
                  "de": "Mach {n} Plätze im Lager frei — „{c}“ öffnet sich dann von selbst und du wirst benachrichtigt.",
                  "ja": "倉庫の空きを{n}つ作ってください。「{c}」は自動で開き、通知が届きます。",
                  "ko": "창고 공간 {n}칸을 비우세요. «{c}»이(가) 자동으로 열리고 알림이 옵니다.",
                  "id": "Kosongkan {n} ruang gudang — «{c}» akan terbuka sendiri dan kamu akan diberi tahu."},
    "chest": {"en": "Chest", "ru": "Сундук", "es": "Cofre", "zh": "宝箱", "fr": "Coffre", "de": "Truhe", "ja": "宝箱", "ko": "상자", "id": "Peti"},
}

_TASKS: set = set()


def spawn(coro) -> None:
    """Run a notification without delaying the API answer (kept referenced until done)."""
    try:
        t = asyncio.get_running_loop().create_task(coro)
        _TASKS.add(t)
        t.add_done_callback(_TASKS.discard)
    except RuntimeError:
        pass


def norm_lang(lang: Optional[str]) -> str:
    l = (lang or "en").lower().split("-")[0].split("_")[0]
    return {"in": "id"}.get(l, l) if l in LANGS or l == "in" else "en"


async def _tr(db, text: str, lang: str, src: str = "auto") -> str:
    """LibreTranslate (cached); the text itself when translation is not configured or fails."""
    if not text:
        return text
    try:
        from translation_service import translate_cached, translation_configured, script_language
        if not translation_configured():
            return text
        s = src if src != "auto" else (script_language(text) or "en")
        if s == lang:
            return text
        return (await translate_cached(db, text, lang, s)) or text
    except Exception as e:                                       # pragma: no cover - network
        logger.debug("chest notify translate: %s", e)
        return text


async def name_in(db, obj: Optional[Dict], lang: str, default: str = "") -> str:
    """name_i18n[lang] → name translated → name."""
    obj = obj or {}
    got = (obj.get("name_i18n") or {}).get(lang)
    if got:
        return got
    base = obj.get("name") or (obj.get("name_i18n") or {}).get("en") or default
    return await _tr(db, base, lang)


async def resource_name(db, rid: str, lang: str) -> str:
    n = RES_NAMES.get(rid) or {}
    return n.get(lang) or await _tr(db, n.get("en") or rid, lang, "en")


def _icon(rid: str) -> str:
    try:
        from business_config import RESOURCE_TYPES
        return (RESOURCE_TYPES.get(rid) or {}).get("icon") or "📦"
    except Exception:
        return "📦"


async def build_text(db, lang: str, container: Dict, results: List[Dict]) -> Tuple[str, str]:
    cname = await name_in(db, container, lang, TEXT["chest"][lang])
    lines = [TEXT["intro"][lang].format(c=cname)]
    for x in results:
        if x.get("kind") == "puzzle":
            lines.append("• 🧩 " + TEXT["piece"][lang].format(n=await name_in(db, x, lang), k=x.get("have", "?")))
        else:
            amt = f"{int(x.get('amount') or 0):,}".replace(",", " ")
            lines.append(f"• {_icon(x.get('resource'))} {await resource_name(db, x.get('resource'), lang)} +{amt}")
    if not results:
        lines.append(TEXT["empty"][lang])
    return TEXT["title"][lang], "\n".join(lines)


# ───────────────────────────── the picture ─────────────────────────────
def _font(size: int):
    from PIL import ImageFont
    for p in ("DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()


def _public_dirs() -> List[Path]:
    here = Path(__file__).resolve().parent.parent
    out = []
    if os.environ.get("FRONTEND_PUBLIC_DIR"):
        out.append(Path(os.environ["FRONTEND_PUBLIC_DIR"]))
    out += [here.parent / "frontend" / "public", here.parent / "frontend" / "build", Path("/app/frontend/public")]
    return out


async def _image_bytes(db, url: str) -> Optional[bytes]:
    if not url:
        return None
    try:
        if url.startswith("/api/minigames/img/"):
            from minigame_rewards_routes import img_dir
            p = img_dir() / url.rsplit("/", 1)[-1]
            return p.read_bytes() if p.is_file() else None
        if url.startswith("/sprites/city/"):
            parts = url.split("/")                                # ['', 'sprites', 'city', type, 'stageN.webp']
            if len(parts) == 5:
                st = parts[4].replace("stage", "").replace(".webp", "")
                doc = await db.admin_settings.find_one({"type": "city_sprites"}, {"_id": 0, "overrides": 1}) or {}
                ov = ((doc.get("overrides") or {}).get(parts[3]) or {}).get(st)
                if ov and ov.get("url"):                          # the admin replaced this building picture
                    from city_sprites import sprites_dir
                    p = sprites_dir() / parts[3] / ov["url"].rsplit("/", 1)[-1]
                    if p.is_file():
                        return p.read_bytes()
        if url.startswith("/sprites/") and ".." not in url:          # static pictures of the app (resources, buildings)
            for d in _public_dirs():
                p = d / url.lstrip("/")
                if p.is_file():
                    return p.read_bytes()
        base = (os.environ.get("PUBLIC_APP_URL") or os.environ.get("FRONTEND_URL") or "").rstrip("/")
        if base and url.startswith("/"):
            import httpx
            async with httpx.AsyncClient(timeout=6) as c:
                r = await c.get(base + url)
                if r.status_code == 200 and r.content:
                    return r.content
    except Exception as e:
        logger.debug("chest picture %s: %s", url, e)
    return None


async def build_image(db, results: List[Dict]) -> Optional[bytes]:
    """PNG card: a tile per reward (max 4) — its picture and the amount (+35 / 6/9)."""
    if not results:
        return None
    try:
        from PIL import Image, ImageDraw
        tiles = []
        for x in results[:4]:
            raw = await _image_bytes(db, x.get("image_url") or "")
            im = None
            if raw:
                try:
                    im = Image.open(io.BytesIO(raw)); im.load(); im = im.convert("RGBA")
                except Exception:
                    im = None
            tiles.append((x, im))
        if not any(im for _x, im in tiles):
            return None
        TW, TH, PAD = 300, 340, 24
        W, H = len(tiles) * TW + (len(tiles) + 1) * PAD, TH + 2 * PAD
        card = Image.new("RGBA", (W, H), (11, 16, 32, 255))
        dr = ImageDraw.Draw(card)
        f = _font(44)
        for i, (x, im) in enumerate(tiles):
            x0, y0 = PAD + i * (TW + PAD), PAD
            piece = x.get("kind") == "puzzle"
            border = (217, 70, 239, 255) if piece else (251, 191, 36, 220)
            dr.rounded_rectangle((x0, y0, x0 + TW, y0 + TH), radius=26, fill=(25, 22, 48, 255) if piece else (36, 30, 18, 255),
                                 outline=border, width=3)
            if im:
                im.thumbnail((240, 240), Image.LANCZOS)
                card.alpha_composite(im, (x0 + (TW - im.width) // 2, y0 + 16 + (240 - im.height) // 2))
            label = f"{x.get('have', '?')}/9" if piece else f"+{int(x.get('amount') or 0):,}".replace(",", " ")
            col = (245, 208, 254, 255) if piece else (110, 231, 183, 255)
            tw = dr.textlength(label, font=f)
            dr.text((x0 + (TW - tw) / 2, y0 + TH - 72), label, font=f, fill=col)
        buf = io.BytesIO(); card.convert("RGB").save(buf, "PNG", optimize=True)
        return buf.getvalue()
    except Exception as e:
        logger.debug("chest card: %s", e)
        return None


# ───────────────────────────── sending ─────────────────────────────
async def _telegram(db, user: Dict, lang: str, title: str, message: str, png: Optional[bytes]) -> None:
    chat_id = user.get("telegram_chat_id")
    if not chat_id or not user.get("telegram_notifications", True):
        return
    body = f"<b>{html.escape(title)}</b>\n\n{html.escape(message)}"
    markup = None
    try:
        from core.notify import augment_markup_with_miniapp
        markup = await augment_markup_with_miniapp(db, None, lang)
    except Exception:
        markup = None
    bot = None
    try:
        from telegram_bot import get_telegram_bot
        bot = get_telegram_bot()
    except Exception:
        bot = None
    try:
        if bot is not None and png:
            ok = await bot.send_photo(str(chat_id), "data:image/png;base64," + base64.b64encode(png).decode(), caption=body, reply_markup=markup)
            if ok is not False:
                return
        if bot is not None:
            await bot.send_message(str(chat_id), body, reply_markup=markup)
            return
        from telegram_notifications import send_telegram_message
        await send_telegram_message(str(chat_id), body, reply_markup=markup)
    except Exception as e:
        logger.debug("chest telegram: %s", e)


async def notify_opened(db, uid: str, uc: Dict, results: List[Dict], telegram: bool = True) -> None:
    try:
        user = await db.users.find_one({"id": uid}, {"_id": 0, "id": 1, "language": 1, "telegram_chat_id": 1, "telegram_notifications": 1}) or {}
        if not user:
            return
        lang = norm_lang(user.get("language"))
        cont = await db.mg_containers.find_one({"id": uc.get("container_id")}, {"_id": 0}) or {}
        title, message = await build_text(db, lang, cont, results)
        png = await build_image(db, results)
        image_url = None
        if png:
            try:
                from PIL import Image
                from minigame_rewards_routes import img_dir
                name = f"chest_{uc['id']}.webp"
                Image.open(io.BytesIO(png)).save(img_dir() / name, "WEBP", quality=88)
                image_url = f"/api/minigames/img/{name}"
            except Exception as e:
                logger.debug("chest card save: %s", e)
        from core.notify import notify_user
        await notify_user(db, uid, title, message, type_key="minigame_chest", priority="info", image_url=image_url,
                          payload={"rewards": results, "user_container_id": uc.get("id"), "image_url": image_url},
                          telegram=False, pretranslated=True)
        if telegram:
            await _telegram(db, user, lang, title, message, png)
    except Exception as e:
        logger.warning("chest notify failed: %s", e)


async def notify_no_space(db, uid: str, uc: Dict, need: int, telegram: bool = True) -> None:
    try:
        user = await db.users.find_one({"id": uid}, {"_id": 0, "id": 1, "language": 1, "telegram_chat_id": 1, "telegram_notifications": 1}) or {}
        if not user:
            return
        lang = norm_lang(user.get("language"))
        cont = await db.mg_containers.find_one({"id": uc.get("container_id")}, {"_id": 0}) or {}
        cname = await name_in(db, cont, lang, TEXT["chest"][lang])
        title, message = TEXT["wait_title"][lang], TEXT["wait_text"][lang].format(n=int(need), c=cname)
        from core.notify import notify_user
        await notify_user(db, uid, title, message, type_key="minigame_chest_wait", priority="warning", telegram=False, pretranslated=True)
        if telegram:
            await _telegram(db, user, lang, title, message, None)
    except Exception as e:
        logger.warning("chest wait notify failed: %s", e)
