"""GRAM City — smart notifications (in-app + Telegram).

Tells a player about things that need their attention, without spam:

    warehouse_full         warehouse 100% full -> ALL businesses stopped
    business_stopped       a business hit 0% durability and stopped
    durability_low         a business dropped below 20% durability
    warehouse_almost_full  warehouse >= 90% -> businesses will stop soon
    price_up               the market price of a resource you make/hold rose

Delivery rules
--------------
* In-app (bell + WebSocket) — ALWAYS delivered (silent, deduplicated).
* Telegram — at most `daily_limit` (1 or 2, player's choice; default 2) per MSK
  day. One slot is kept for the important kinds (warehouse_full,
  business_stopped), so a price tip can never use up the day's last push.
* Quiet hours (default 23:00–08:00 in the player's time zone) — Telegram is NOT
  sent; the message waits in `smart_tg_queue` and goes out when quiet hours end,
  only if it is still relevant (e.g. the warehouse is still full).
* Every kind can be switched off by the player.

Deduplication is persistent (stored in Mongo, not process memory), so restarts
never re-send: warehouse state lives in users.smart_state.warehouse, per-business
flags in businesses.smart_notified, price alerts in users.smart_price_day.

Texts
-----
Written by hand in English and Russian. Every other project language is
translated from English through LibreTranslate (translation_service.
translate_libre_protected: placeholders like {name} are protected) and cached in
`smart_notif_i18n`. Without LibreTranslate the player gets English.
"""
from __future__ import annotations

import asyncio
import logging
import statistics
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))
PROJECT_LANGS = ["en", "ru", "es", "zh", "fr", "de", "ja", "ko", "id"]

KINDS = ["warehouse_full", "business_stopped", "durability_low", "warehouse_almost_full", "price_up", "shift_ended"]
CRITICAL = {"warehouse_full", "business_stopped"}
# Kinds that do NOT use the daily Telegram limit (a shift ends up to 3× a day —
# counting it would eat the slots of the important alerts). Quiet hours still apply.
UNCAPPED = {"shift_ended"}
# preference group each kind belongs to (what the player toggles in settings)
GROUP = {
    "warehouse_full": "warehouse", "warehouse_almost_full": "warehouse",
    "business_stopped": "durability", "durability_low": "durability",
    "price_up": "price",
    "shift_ended": "shift",
}

ALMOST_PCT = 90      # warehouse "almost full" threshold
RESET_PCT = 80       # below this the warehouse is "ok" again (hysteresis)
DURABILITY_LOW = 20
DURABILITY_RESET = 50
PRICE_RISE_PCT = 15  # market price must rise at least this much vs 24 h ago
PRICE_MIN_LOTS = 3   # and be based on at least this many active lots
PRICE_HOLD_MIN = 20  # notify holders with at least this many units

DEFAULT_PREFS = {
    "warehouse": True, "durability": True, "price": True, "shift": True,
    "quiet_enabled": True, "quiet_start": 23, "quiet_end": 8,
    "daily_limit": 2,
}

# en / ru by hand; other languages via LibreTranslate (cached).
TEXTS = {
    "warehouse_full": {
        "en": ("📦 Warehouse full — businesses stopped",
               "Your warehouse is full, so all {count} of your businesses have stopped. "
               "Sell resources or cancel a market lot to free space and they will start again."),
        "ru": ("📦 Склад полон — бизнесы остановились",
               "Склад заполнен, поэтому все ваши бизнесы ({count}) остановились. "
               "Продайте ресурсы или снимите лот с рынка — как только появится место, они снова заработают."),
    },
    "warehouse_almost_full": {
        "en": ("📦 Warehouse almost full",
               "Your warehouse is {pct}% full. When it is full, your businesses will stop. "
               "Sell some resources to keep them working."),
        "ru": ("📦 Склад почти полон",
               "Склад заполнен на {pct}%. Когда он заполнится, бизнесы остановятся. "
               "Продайте часть ресурсов, чтобы они продолжали работать."),
    },
    "durability_low": {
        "en": ("🔧 {name}: durability {pct}%",
               "{name} is worn down to {pct}%. Repair it soon — at 0% it stops working."),
        "ru": ("🔧 {name}: прочность {pct}%",
               "Прочность «{name}» упала до {pct}%. Отремонтируйте его — при 0% он перестанет работать."),
    },
    "business_stopped": {
        "en": ("⛔ {name} stopped",
               "{name} has 0% durability and stopped working. Repair it to restart production."),
        "ru": ("⛔ {name} остановился",
               "Прочность «{name}» упала до 0%, бизнес остановился. Отремонтируйте его, чтобы возобновить производство."),
    },
    "shift_ended": {
        "en": ("⏰ Shift finished",
               "The shift has finished at: {names}. Open the game and start a new shift to keep your business working."),
        "ru": ("⏰ Смена закончилась",
               "Смена закончилась: {names}. Зайдите в игру и запустите новую смену, чтобы бизнес снова работал."),
    },
    "price_up": {
        "en": ("📈 {resource} price is up {change}%",
               "The market price of {resource} rose from {old} to {new} TON per unit over the last day. "
               "A good moment to sell."),
        "ru": ("📈 Цена на {resource} выросла на {change}%",
               "Рыночная цена {resource} выросла за сутки с {old} до {new} TON за единицу. "
               "Хороший момент для продажи."),
    },
}

# the other project languages, written by hand (no external translator needed)
for _k, _by_lang in {
    'warehouse_full': {
        'es': ('📦 Almacén lleno: los negocios se detuvieron',
               'Tu almacén está lleno, así que tus {count} negocios se detuvieron. Vende recursos o retira un lote del mercado para liberar espacio y volverán a funcionar.'),
        'zh': ('📦 仓库已满——企业已停工',
               '你的仓库已满，因此你的全部 {count} 个企业已停工。出售资源或撤下市场挂单以腾出空间，它们就会重新开工。'),
        'fr': ('📦 Entrepôt plein — entreprises arrêtées',
               'Votre entrepôt est plein : vos {count} entreprises se sont arrêtées. Vendez des ressources ou retirez une offre du marché pour libérer de la place et elles redémarreront.'),
        'de': ('📦 Lager voll – Unternehmen gestoppt',
               'Dein Lager ist voll, daher sind alle deine {count} Unternehmen gestoppt. Verkaufe Ressourcen oder nimm ein Marktangebot zurück, um Platz zu schaffen – dann laufen sie wieder.'),
        'ja': ('📦 倉庫が満杯 — ビジネスが停止',
               '倉庫が満杯のため、{count}件のビジネスがすべて停止しました。資源を売るかマーケットの出品を取り下げて空きを作ると再開します。'),
        'ko': ('📦 창고 가득 참 — 사업 중지',
               '창고가 가득 차서 {count}개 사업이 모두 멈췄습니다. 자원을 팔거나 시장 등록을 취소해 공간을 만들면 다시 가동됩니다.'),
        'id': ('📦 Gudang penuh — bisnis berhenti',
               'Gudang Anda penuh, jadi semua {count} bisnis Anda berhenti. Jual sumber daya atau batalkan lot di pasar untuk mengosongkan ruang, lalu bisnis akan berjalan lagi.'),
    },
    'warehouse_almost_full': {
        'es': ('📦 Almacén casi lleno',
               'Tu almacén está al {pct}%. Cuando se llene, tus negocios se detendrán. Vende algunos recursos para que sigan funcionando.'),
        'zh': ('📦 仓库快满了',
               '你的仓库已使用 {pct}%。仓库满了企业就会停工。出售一些资源让它们继续运转。'),
        'fr': ('📦 Entrepôt presque plein',
               'Votre entrepôt est rempli à {pct} %. Quand il sera plein, vos entreprises s’arrêteront. Vendez des ressources pour qu’elles continuent.'),
        'de': ('📦 Lager fast voll',
               'Dein Lager ist zu {pct} % gefüllt. Wenn es voll ist, stoppen deine Unternehmen. Verkaufe Ressourcen, damit sie weiterlaufen.'),
        'ja': ('📦 倉庫がもうすぐ満杯',
               '倉庫の使用率が{pct}%です。満杯になるとビジネスが止まります。資源を売って稼働を続けましょう。'),
        'ko': ('📦 창고가 거의 가득 참',
               '창고가 {pct}% 찼습니다. 가득 차면 사업이 멈춥니다. 자원을 조금 팔아 계속 가동하세요.'),
        'id': ('📦 Gudang hampir penuh',
               'Gudang Anda terisi {pct}%. Saat penuh, bisnis Anda akan berhenti. Jual sebagian sumber daya agar tetap berjalan.'),
    },
    'durability_low': {
        'es': ('🔧 {name}: durabilidad {pct}%',
               '{name} está desgastado al {pct}%. Repáralo pronto: al 0% deja de funcionar.'),
        'zh': ('🔧 {name}：耐久度 {pct}%',
               '{name} 的耐久度降至 {pct}%。请尽快维修——降到 0% 会停工。'),
        'fr': ('🔧 {name} : durabilité {pct} %',
               '{name} est usé à {pct} %. Réparez-le vite — à 0 % il s’arrête.'),
        'de': ('🔧 {name}: Haltbarkeit {pct} %',
               '{name} ist auf {pct} % abgenutzt. Repariere es bald – bei 0 % stoppt es.'),
        'ja': ('🔧 {name}：耐久度 {pct}%',
               '{name}の耐久度が{pct}%まで下がりました。早めに修理してください。0%で停止します。'),
        'ko': ('🔧 {name}: 내구도 {pct}%',
               '{name}의 내구도가 {pct}%로 떨어졌습니다. 곧 수리하세요 — 0%가 되면 멈춥니다.'),
        'id': ('🔧 {name}: daya tahan {pct}%',
               '{name} aus hingga {pct}%. Segera perbaiki — pada 0% bisnis berhenti.'),
    },
    'business_stopped': {
        'es': ('⛔ {name} se detuvo',
               '{name} tiene 0% de durabilidad y dejó de funcionar. Repáralo para reanudar la producción.'),
        'zh': ('⛔ {name} 已停工',
               '{name} 的耐久度为 0%，已停工。维修后即可恢复生产。'),
        'fr': ('⛔ {name} s’est arrêté',
               '{name} est à 0 % de durabilité et s’est arrêté. Réparez-le pour relancer la production.'),
        'de': ('⛔ {name} gestoppt',
               '{name} hat 0 % Haltbarkeit und arbeitet nicht mehr. Repariere es, um die Produktion fortzusetzen.'),
        'ja': ('⛔ {name}が停止',
               '{name}の耐久度が0%になり停止しました。修理すると生産が再開します。'),
        'ko': ('⛔ {name} 중지됨',
               '{name}의 내구도가 0%가 되어 멈췄습니다. 수리하면 생산이 재개됩니다.'),
        'id': ('⛔ {name} berhenti',
               'Daya tahan {name} 0% dan bisnis berhenti. Perbaiki untuk melanjutkan produksi.'),
    },
    'shift_ended': {
        'es': ('⏰ Turno terminado',
               'El turno terminó en: {names}. Abre el juego e inicia un nuevo turno para que tu negocio siga funcionando.'),
        'zh': ('⏰ 轮班结束',
               '以下企业的轮班已结束：{names}。打开游戏开始新的轮班，让企业继续运转。'),
        'fr': ('⏰ Quart terminé',
               'Le quart est terminé pour : {names}. Ouvrez le jeu et lancez un nouveau quart pour que l’entreprise continue.'),
        'de': ('⏰ Schicht beendet',
               'Die Schicht ist beendet bei: {names}. Öffne das Spiel und starte eine neue Schicht, damit dein Unternehmen weiterläuft.'),
        'ja': ('⏰ シフト終了',
               'シフトが終了しました：{names}。ゲームを開いて新しいシフトを開始し、ビジネスを稼働させましょう。'),
        'ko': ('⏰ 교대 종료',
               '교대가 끝났습니다: {names}. 게임을 열고 새 교대를 시작해 사업을 계속 가동하세요.'),
        'id': ('⏰ Shift selesai',
               'Shift selesai di: {names}. Buka game dan mulai shift baru agar bisnis Anda tetap berjalan.'),
    },
    'price_up': {
        'es': ('📈 El precio de {resource} subió un {change}%',
               'El precio de mercado de {resource} subió de {old} a {new} TON por unidad en el último día. Buen momento para vender.'),
        'zh': ('📈 {resource} 价格上涨 {change}%',
               '过去一天 {resource} 的市场价从每单位 {old} 涨到 {new} TON。正是出售的好时机。'),
        'fr': ('📈 Le prix de {resource} a augmenté de {change} %',
               'Le prix du marché de {resource} est passé de {old} à {new} TON l’unité en un jour. Bon moment pour vendre.'),
        'de': ('📈 Preis für {resource} um {change} % gestiegen',
               'Der Marktpreis für {resource} stieg am letzten Tag von {old} auf {new} TON pro Einheit. Ein guter Moment zum Verkaufen.'),
        'ja': ('📈 {resource}の価格が{change}%上昇',
               '{resource}の市場価格が直近1日で1単位あたり{old}から{new} TONに上昇しました。売り時です。'),
        'ko': ('📈 {resource} 가격 {change}% 상승',
               '지난 하루 동안 {resource}의 시장가가 단위당 {old}에서 {new} TON으로 올랐습니다. 판매하기 좋은 때입니다.'),
        'id': ('📈 Harga {resource} naik {change}%',
               'Harga pasar {resource} naik dari {old} menjadi {new} TON per unit dalam sehari terakhir. Saat yang tepat untuk menjual.'),
    },
}.items():
    TEXTS[_k].update(_by_lang)

_DB = None
_bg: set = set()


def init(db) -> None:
    global _DB
    _DB = db


def _spawn(coro) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    t = loop.create_task(coro)
    _bg.add(t)
    t.add_done_callback(_bg.discard)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _msk_day() -> str:
    return datetime.now(timezone.utc).astimezone(MSK).date().isoformat()


def _lang(user: Dict[str, Any]) -> str:
    lang = (user.get("language") or "en").lower()
    return lang if lang in PROJECT_LANGS else "en"


async def _tg_lang(user: Dict[str, Any]) -> str:
    """The language set in the player's Telegram (sent by Telegram with every message to the bot);
    the app language when it is unknown or not one of the project languages."""
    try:
        m = await _DB.telegram_mappings.find_one({"chat_id": str(user.get("telegram_chat_id"))}, {"_id": 0, "tg_language_code": 1}) \
            or await _DB.telegram_mappings.find_one({"chat_id": user.get("telegram_chat_id")}, {"_id": 0, "tg_language_code": 1})
        code = str((m or {}).get("tg_language_code") or "").lower().replace("_", "-").split("-")[0]
        code = {"in": "id"}.get(code, code)              # old Android code for Indonesian
        if code in PROJECT_LANGS:
            return code
    except Exception:
        pass
    return _lang(user)


# ───────────────────────────── preferences ─────────────────────────────
def prefs_of(user: Dict[str, Any]) -> Dict[str, Any]:
    saved = (user.get("notification_preferences") or {}).get("smart") or {}
    p = {**DEFAULT_PREFS, **{k: v for k, v in saved.items() if k in DEFAULT_PREFS}}
    p["daily_limit"] = 1 if int(p.get("daily_limit") or 2) <= 1 else 2
    return p


def _user_tz(user: Dict[str, Any]):
    name = user.get("timezone")
    if name:
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(name)
        except Exception:
            pass
    return MSK


def in_quiet_hours(user: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    p = prefs_of(user)
    if not p["quiet_enabled"]:
        return False
    h = (now or datetime.now(timezone.utc)).astimezone(_user_tz(user)).hour
    start, end = int(p["quiet_start"]) % 24, int(p["quiet_end"]) % 24
    if start == end:
        return False
    return (start <= h < end) if start < end else (h >= start or h < end)


def quiet_ends_at(user: Dict[str, Any], now: Optional[datetime] = None) -> datetime:
    """Next moment quiet hours end (UTC)."""
    now = now or datetime.now(timezone.utc)
    tz = _user_tz(user)
    local = now.astimezone(tz)
    end = int(prefs_of(user)["quiet_end"]) % 24
    target = local.replace(hour=end, minute=0, second=0, microsecond=0)
    if target <= local:
        target += timedelta(days=1)
    return target.astimezone(timezone.utc)


# ───────────────────────────── translation ─────────────────────────────
async def _translate(key: str, lang: str, title_en: str, message_en: str):
    """(title, message) template in `lang` — cached LibreTranslate result."""
    cached = await _DB.smart_notif_i18n.find_one({"key": key, "lang": lang}, {"_id": 0})
    if cached and cached.get("src") == title_en + "\n" + message_en:
        return cached["title"], cached["message"]
    try:
        from translation_service import translate_libre_protected, libretranslate_configured
        if not libretranslate_configured():
            return title_en, message_en
        title = await asyncio.wait_for(translate_libre_protected(title_en, lang, "en"), timeout=15)
        message = await asyncio.wait_for(translate_libre_protected(message_en, lang, "en"), timeout=15)
    except Exception as e:  # keep English, retry next time
        logger.debug(f"smart_notify: LibreTranslate {key}/{lang} failed: {e}")
        return title_en, message_en
    await _DB.smart_notif_i18n.update_one(
        {"key": key, "lang": lang},
        {"$set": {"key": key, "lang": lang, "title": title, "message": message,
                  "src": title_en + "\n" + message_en, "at": _iso_now()}},
        upsert=True,
    )
    return title, message


async def _translate_word(word: str, lang: str) -> str:
    """Translate a single name (resource) via LibreTranslate, cached."""
    if not word or lang in ("en",):
        return word
    key = "word:" + word
    cached = await _DB.smart_notif_i18n.find_one({"key": key, "lang": lang}, {"_id": 0})
    if cached:
        return cached.get("title") or word
    try:
        from translation_service import translate_libre_protected, libretranslate_configured
        if not libretranslate_configured():
            return word
        out = await asyncio.wait_for(translate_libre_protected(word, lang, "en"), timeout=10)
    except Exception:
        return word
    await _DB.smart_notif_i18n.update_one({"key": key, "lang": lang},
                                          {"$set": {"key": key, "lang": lang, "title": out, "message": "", "at": _iso_now()}},
                                          upsert=True)
    return out


async def render(kind: str, lang: str, vars_: Dict[str, Any]):
    tpl = TEXTS[kind]
    if lang in tpl:
        title, message = tpl[lang]
    else:
        title, message = await _translate(kind, lang, *tpl["en"])
    try:
        return title.format(**vars_), message.format(**vars_)
    except (KeyError, IndexError):  # a translation mangled a placeholder name
        t_en, m_en = tpl["en"]
        return t_en.format(**vars_), m_en.format(**vars_)


async def warm_translations() -> Dict[str, int]:
    """Translate every template into every language now (startup / admin)."""
    done = 0
    for kind, tpl in TEXTS.items():
        for lang in PROJECT_LANGS:
            if lang in tpl:
                continue
            await _translate(kind, lang, *tpl["en"])
            done += 1
    return {"templates": done}


# ───────────────────────────── delivery ─────────────────────────────
async def _telegram_allowed(user: Dict[str, Any], kind: str) -> bool:
    """Daily cap with one slot reserved for critical kinds."""
    limit = prefs_of(user)["daily_limit"]
    day = _msk_day()
    cur = user.get("smart_daily") or {}
    used = int(cur.get("count", 0) or 0) if cur.get("day") == day else 0
    allowed_upto = limit if kind in CRITICAL else max(0, limit - 1) if limit >= 2 else limit
    return used < allowed_upto


async def _consume_slot(user_id: str) -> None:
    day = _msk_day()
    res = await _DB.users.update_one({"id": user_id, "smart_daily.day": day}, {"$inc": {"smart_daily.count": 1}})
    if res.matched_count == 0:
        await _DB.users.update_one({"id": user_id}, {"$set": {"smart_daily": {"day": day, "count": 1}}})


async def send(user_or_id: Any, kind: str, vars_: Dict[str, Any], *, ref: Optional[str] = None) -> Dict[str, Any]:
    """Deliver one smart notification. Returns what happened (for logs/tests)."""
    if _DB is None or kind not in TEXTS:
        return {"sent": False, "reason": "not_ready"}
    user = user_or_id if isinstance(user_or_id, dict) else await _DB.users.find_one({"id": user_or_id}, {"_id": 0})
    if not user or not user.get("id"):
        return {"sent": False, "reason": "no_user"}
    prefs = prefs_of(user)
    if not prefs.get(GROUP[kind], True):
        return {"sent": False, "reason": "disabled"}

    lang = _lang(user)
    if "resource" in vars_ and lang != "en":
        vars_ = {**vars_, "resource": await _translate_word(str(vars_["resource"]), lang)}
    title, message = await render(kind, lang, vars_)
    payload = {"smart_kind": kind, "ref": ref, **{k: v for k, v in vars_.items() if isinstance(v, (int, float, str))}}
    priority = "warning" if kind in CRITICAL or kind == "durability_low" else "info"

    from core.notify import notify_user
    # 1) in-app: always (silent bell + WS push)
    await notify_user(_DB, user, title, message, type_key=f"smart_{kind}", priority=priority,
                      payload=payload, telegram=False, pretranslated=True)

    # 2) Telegram: preferences, cap, quiet hours
    if not user.get("telegram_chat_id") or not user.get("telegram_notifications", True):
        return {"sent": True, "telegram": "no_telegram"}
    tg_lang = await _tg_lang(user)
    if tg_lang != lang:                                  # Telegram copy in the player's Telegram language
        v_tg = vars_
        if "resource" in vars_ and tg_lang != "en":
            v_tg = {**vars_, "resource": await _translate_word(str(vars_["resource"]), tg_lang)}
        title, message = await render(kind, tg_lang, v_tg)
    if kind not in UNCAPPED and not await _telegram_allowed(user, kind):
        return {"sent": True, "telegram": "daily_limit"}
    if in_quiet_hours(user):
        await _DB.smart_tg_queue.update_one(
            {"user_id": user["id"], "kind": kind, "ref": ref},
            {"$set": {"user_id": user["id"], "kind": kind, "ref": ref, "title": title, "message": message,
                      "payload": payload, "deliver_after": quiet_ends_at(user).isoformat(), "created_at": _iso_now()}},
            upsert=True,
        )
        return {"sent": True, "telegram": "queued_quiet_hours"}
    if kind not in UNCAPPED:
        await _consume_slot(user["id"])
    await notify_user(_DB, user, title, message, type_key=f"smart_{kind}", priority=priority,
                      payload=payload, in_app=False, pretranslated=True, add_home_button=True)
    return {"sent": True, "telegram": "sent"}


def send_bg(user_or_id: Any, kind: str, vars_: Dict[str, Any], *, ref: Optional[str] = None) -> None:
    async def _run():
        try:
            await send(user_or_id, kind, vars_, ref=ref)
        except Exception as e:
            logger.warning(f"smart_notify.send {kind} failed: {e}")
    _spawn(_run())


async def _still_relevant(item: Dict[str, Any], user: Dict[str, Any]) -> bool:
    kind = item["kind"]
    if kind in ("warehouse_full", "warehouse_almost_full"):
        st = (user.get("smart_state") or {}).get("warehouse", "ok")
        return st == "full" if kind == "warehouse_full" else st in ("almost", "full")
    if kind in ("durability_low", "business_stopped") and item.get("ref"):
        b = await _DB.businesses.find_one({"id": item["ref"]}, {"_id": 0, "durability": 1})
        if not b:
            return False
        d = float(b.get("durability", 100) or 0)
        return d <= 0 if kind == "business_stopped" else d < DURABILITY_LOW
    if kind == "price_up":
        return item.get("created_at", "")[:10] >= (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
    if kind == "shift_ended":
        ids = [x for x in str((item.get("payload") or {}).get("business_ids", "")).split(",") if x]
        if not ids:
            return False
        now_iso = datetime.now(timezone.utc).isoformat()
        # relevant while at least one of those businesses still has no running shift
        idle = await _DB.businesses.count_documents({"id": {"$in": ids}, "$or": [
            {"shift_ends_at": {"$exists": False}}, {"shift_ends_at": None}, {"shift_ends_at": {"$lte": now_iso}}]})
        return idle > 0
    return True


async def flush_queue() -> Dict[str, int]:
    """Send Telegram messages held back by quiet hours (scheduled job)."""
    if _DB is None:
        return {"sent": 0}
    now = _iso_now()
    sent = dropped = 0
    async for item in _DB.smart_tg_queue.find({"deliver_after": {"$lte": now}}, {"_id": 0}):
        await _DB.smart_tg_queue.delete_one({"user_id": item["user_id"], "kind": item["kind"], "ref": item.get("ref")})
        user = await _DB.users.find_one({"id": item["user_id"]}, {"_id": 0})
        if not user or not await _still_relevant(item, user) or in_quiet_hours(user) \
                or (item["kind"] not in UNCAPPED and not await _telegram_allowed(user, item["kind"])):
            dropped += 1
            continue
        from core.notify import notify_user
        if item["kind"] not in UNCAPPED:
            await _consume_slot(user["id"])
        await notify_user(_DB, user, item["title"], item["message"], type_key=f"smart_{item['kind']}",
                          payload=item.get("payload") or {}, in_app=False, pretranslated=True, add_home_button=True)
        sent += 1
    return {"sent": sent, "dropped": dropped}


# ───────────────────────────── triggers ─────────────────────────────
def warehouse_event(user: Dict[str, Any], used: float, cap: float, running_businesses: int):
    """Decide (pure) whether the warehouse state changed upward.

    Returns (new_state, kind_to_send | None). Downward moves are silent; the
    80–90% band keeps the previous state so a warehouse hovering around 90%
    does not notify again and again.
    """
    prev = (user.get("smart_state") or {}).get("warehouse", "ok")
    if cap <= 0:
        return prev, None
    pct = 100.0 * used / cap
    if pct >= 100:
        new = "full"
    elif pct >= ALMOST_PCT:
        new = "full" if prev == "full" and pct >= 99 else "almost"
    elif pct < RESET_PCT:
        new = "ok"
    else:
        new = "almost" if prev in ("almost", "full") else "ok"
    kind = None
    if running_businesses > 0:
        if new == "full" and prev != "full":
            kind = "warehouse_full"
        elif new == "almost" and prev == "ok":
            kind = "warehouse_almost_full"
    return new, kind


def durability_event(business: Dict[str, Any], old: float, new: float):
    """(kind | None, flags_update). Flags make it fire once per wear-down."""
    flags = dict(business.get("smart_notified") or {})
    kind = None
    if new <= 0 < old and not flags.get("stopped"):
        kind, flags["stopped"] = "business_stopped", True
    elif new < DURABILITY_LOW <= old and not flags.get("low"):
        kind, flags["low"] = "durability_low", True
    if new >= DURABILITY_RESET:          # repaired -> arm again
        flags = {}
    return kind, flags


async def price_watch() -> Dict[str, Any]:
    """Hourly job: snapshot market prices; notify on a >=15% rise vs ~24 h ago."""
    if _DB is None:
        return {}
    by_res: Dict[str, List[float]] = {}
    async for lst in _DB.market_listings.find({"status": "active", "is_bot": {"$ne": True}},
                                              {"_id": 0, "resource_type": 1, "price_per_unit": 1}):
        p = lst.get("price_per_unit")
        if lst.get("resource_type") and isinstance(p, (int, float)) and p > 0:
            by_res.setdefault(lst["resource_type"], []).append(float(p))
    prices = {r: round(statistics.median(v), 6) for r, v in by_res.items() if len(v) >= PRICE_MIN_LOTS}
    now = datetime.now(timezone.utc)
    await _DB.market_price_snapshots.insert_one({"ts": now.isoformat(), "prices": prices})
    old_doc = await _DB.market_price_snapshots.find(
        {"ts": {"$lte": (now - timedelta(hours=23)).isoformat(),
                "$gte": (now - timedelta(hours=30)).isoformat()}}, {"_id": 0}
    ).sort("ts", -1).limit(1).to_list(1)
    if not old_doc:
        return {"snapshot": len(prices), "alerts": 0}
    old_prices = old_doc[0].get("prices") or {}
    risen = {r: (old_prices[r], p) for r, p in prices.items()
             if old_prices.get(r) and p >= old_prices[r] * (1 + PRICE_RISE_PCT / 100.0)}
    if not risen:
        return {"snapshot": len(prices), "alerts": 0}
    try:
        from business_config import BUSINESSES, RESOURCE_TYPES
    except Exception:
        BUSINESSES, RESOURCE_TYPES = {}, {}
    day = _msk_day()
    alerts = 0
    for res, (old_p, new_p) in risen.items():
        producers = [bt for bt, cfg in BUSINESSES.items() if cfg.get("produces") == res]
        owner_keys = set(await _DB.businesses.distinct("owner", {"business_type": {"$in": producers}})) if producers else set()
        q = {"$or": [{"id": {"$in": list(owner_keys)}}, {"wallet_address": {"$in": list(owner_keys)}},
                     {f"resources.{res}": {"$gte": PRICE_HOLD_MIN}}]}
        res_name = (RESOURCE_TYPES.get(res) or {}).get("name_en") or res
        change = int(round(100 * (new_p - old_p) / old_p))
        async for user in _DB.users.find(q, {"_id": 0}):
            if (user.get("smart_price_day") or {}).get(res) == day:
                continue
            await _DB.users.update_one({"id": user["id"]}, {"$set": {f"smart_price_day.{res}": day}})
            send_bg(user, "price_up", {"resource": res_name, "change": change,
                                       "old": round(old_p, 4), "new": round(new_p, 4)}, ref=res)
            alerts += 1
    # keep a week of snapshots
    await _DB.market_price_snapshots.delete_many({"ts": {"$lt": (now - timedelta(days=7)).isoformat()}})
    return {"snapshot": len(prices), "risen": list(risen), "alerts": alerts}


# ───────────────────────────── API ─────────────────────────────
def create_smart_notify_router(db, get_current_user, get_current_admin) -> APIRouter:
    init(db)
    root = APIRouter()
    router = APIRouter(prefix="/api/notifications/smart", tags=["smart-notifications"])
    admin = APIRouter(prefix="/api/admin/smart-notifications", tags=["smart-notifications-admin"])

    @router.get("")
    async def get_prefs(current_user=Depends(get_current_user)):
        u = await db.users.find_one({"id": current_user.id}, {"_id": 0}) or {}
        return {**prefs_of(u), "timezone": u.get("timezone"), "telegram_linked": bool(u.get("telegram_chat_id"))}

    @router.put("")
    async def put_prefs(patch: Dict[str, Any], current_user=Depends(get_current_user)):
        clean: Dict[str, Any] = {}
        for k, v in (patch or {}).items():
            if k in ("warehouse", "durability", "price", "shift", "quiet_enabled"):
                clean[k] = bool(v)
            elif k in ("quiet_start", "quiet_end"):
                if not isinstance(v, int) or not 0 <= v <= 23:
                    raise HTTPException(status_code=400, detail=f"{k} must be 0..23")
                clean[k] = v
            elif k == "daily_limit":
                if v not in (1, 2):
                    raise HTTPException(status_code=400, detail="daily_limit must be 1 or 2")
                clean[k] = v
        upd = {f"notification_preferences.smart.{k}": v for k, v in clean.items()}
        tz = (patch or {}).get("timezone")
        if isinstance(tz, str) and 0 < len(tz) <= 64:
            try:
                from zoneinfo import ZoneInfo
                ZoneInfo(tz)
                upd["timezone"] = tz
            except Exception:
                pass
        if upd:
            await db.users.update_one({"id": current_user.id}, {"$set": upd})
        u = await db.users.find_one({"id": current_user.id}, {"_id": 0}) or {}
        return {**prefs_of(u), "timezone": u.get("timezone")}

    @admin.post("/warm-translations")
    async def admin_warm(_=Depends(get_current_admin)):
        return await warm_translations()

    @admin.post("/test")
    async def admin_test(user_id: str, kind: str = "warehouse_almost_full", _=Depends(get_current_admin)):
        if kind not in TEXTS:
            raise HTTPException(status_code=400, detail=f"kind must be one of {list(TEXTS)}")
        demo = {"count": 3, "pct": 92, "name": "Helios", "resource": "Energy", "change": 18, "old": 0.003, "new": 0.0036,
                "names": "Helios", "business_ids": ""}
        return await send(user_id, kind, demo, ref="admin_test")

    root.include_router(router)
    root.include_router(admin)
    return root
