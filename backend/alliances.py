"""GRAM City — alliances (teams of players).

Stage 1 of the alliances plan («GRAM City — План альянсов»): the team itself.
    • create (City Pass level ≥ 5, at least one real business, 5 000 $CITY — all set in the admin);
      name 3–24 characters (unique), tag 3–4 letters/digits (unique), emblem, language, description;
    • join: open / by request / by invitation only; the leader sets the minimum City Pass level;
      rejoin not earlier than 24 h after leaving; linked accounts (one device) never in one alliance;
    • roles: leader (1), deputies (≤ 2), officers (≤ 5), members; leadership transfer; kick;
    • treasury in $CITY with a log seen by everyone: voluntary deposits (≤ 20 000 $CITY a day per player,
      paid bonus balance first), the alliance tax 0–5 % of members' $CITY rewards (tasks, daily login,
      goals; changed not more often than once in 7 days), payouts to members (bonus balance, never
      withdrawable) and the level-up fees;
    • alliance XP (AXP): 10 % of every member's City Pass XP (≤ 2 000 a day per player, the player loses
      nothing); levels 1–10 (AXP + a fee from the treasury) open more places;
    • the alliance chat channel, the tag next to the name (chat, profile, map), notifications in 9 languages;
    • background: requests expire after 7 days, an inactive leader (14 days) is replaced by the most active
      deputy / officer, an alliance with one member for 14 days is disbanded (the treasury is shared out).

Not in stage 1 (see the plan): the bonuses of the levels (income, warehouse, repair, market), research,
resource drives, the weekly alliance league, district wars, seasons. The level table already lists them,
marked as coming later.

Collections: alliances, alliance_members (one row per player — unique user_id), alliance_requests,
alliance_log. Users carry a copy of alliance_id / alliance_name / alliance_tag for fast display.
Every number is editable in the admin (Данные → Альянсы), stored in admin_settings type=alliances.
"""
from __future__ import annotations

import asyncio
import logging
import math
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

logger = logging.getLogger(__name__)

CITY_PER_TON = 1000.0
ROLES = ("leader", "deputy", "officer", "member")
RANK = {"leader": 3, "deputy": 2, "officer": 1, "member": 0}
JOIN_MODES = ("open", "request", "invite")
LANGS = ("en", "ru", "es", "zh", "fr", "de", "ja", "ko", "id")
EMBLEMS = ("🛡️", "⚔️", "🦅", "🐺", "🦁", "🐉", "🔥", "⚡", "💎", "👑", "🚀", "🌐", "🏙️", "🧠", "🌙", "☀️",
           "🦊", "🐻", "🦈", "🎯",
           # more (the first 20 stay first: alliances made earlier keep theirs)
           "🐯", "🐼", "🐨", "🦉", "🐝", "🦂", "🦖", "🐙", "🦄", "🐲", "🦬", "🐆", "🦍", "🐍", "🦋", "🐬",
           "🏰", "🗼", "🏗️", "🏭", "⚓", "🛰️", "🛸", "✈️", "🚂", "⛵", "🏎️", "🗿",
           "⭐", "🌟", "☄️", "🌈", "❄️", "🌊", "🌋", "🍀", "🌹", "🌵",
           "💰", "🪙", "💠", "🔱", "⚜️", "🏆", "🎖️", "🧭", "⚙️", "🔮", "🗝️", "🎲", "🎮", "🧬", "☢️", "♾️")
# background of the emblem (the frontend maps each key to its gradient); the first one = the old default look
EMBLEM_BGS = ("neon", "violet", "indigo", "sky", "cyan", "teal", "emerald", "lime", "gold", "amber", "orange",
              "crimson", "rose", "magenta", "slate", "night")

# level table: AXP needed, fee from the treasury, places, what it opens (keys of the frontend texts);
# `soon` = arrives with a later stage of the plan (shown as «скоро»)
DEFAULT_LEVELS: List[Dict[str, Any]] = [
    {"level": 1, "axp": 0, "fee_city": 0, "slots": 10, "unlocks": ["chat", "treasury", "tag"]},
    {"level": 2, "axp": 5000, "fee_city": 2000, "slots": 12, "unlocks": ["bonus_warehouse"]},
    {"level": 3, "axp": 15000, "fee_city": 5000, "slots": 14, "unlocks": ["drives"]},
    {"level": 4, "axp": 35000, "fee_city": 10000, "slots": 16, "unlocks": ["bonus_repair"]},
    {"level": 5, "axp": 70000, "fee_city": 20000, "slots": 18, "unlocks": ["district_wars", "weekly_chest"]},
    {"level": 6, "axp": 120000, "fee_city": 35000, "slots": 20, "unlocks": ["bonus_market"]},
    {"level": 7, "axp": 200000, "fee_city": 50000, "slots": 23, "unlocks": ["research_slot2"]},
    {"level": 8, "axp": 320000, "fee_city": 75000, "slots": 26, "unlocks": ["bonus_income3"]},
    {"level": 9, "axp": 480000, "fee_city": 100000, "slots": 28, "unlocks": ["veteran_emblem"]},
    {"level": 10, "axp": 700000, "fee_city": 150000, "slots": 30, "unlocks": ["hq", "bonus_income5"]},
]
LIVE_UNLOCKS = {"chat", "treasury", "tag"}               # what stage 1 really gives

DEFAULT_CONFIG: Dict[str, Any] = {
    "enabled": True,
    "create_cost_city": 5000,
    "create_min_pass_level": 5,
    "create_requires_business": True,
    "rejoin_cooldown_hours": 24,
    "deputies_max": 2,
    "officers_max": 5,
    "tax_max_pct": 5,
    "tax_change_days": 7,
    "deposit_min_city": 10,
    "deposit_daily_cap_city": 20000,
    "deputy_daily_payout_city": 10000,
    "axp_share_pct": 10,
    "axp_daily_cap_per_player": 2000,
    "request_expire_days": 7,
    "inactive_leader_days": 14,
    "solo_disband_days": 14,
    "levels": DEFAULT_LEVELS,
}

NAME_RE = re.compile(r"^[\w .\-'&!]{3,24}$", re.UNICODE)
TAG_RE = re.compile(r"^[A-Z0-9]{3,4}$")


# ───────────────────────────── notifications (9 languages) ─────────────────────────────
ALLIANCE_NOTIF = {
    "alliance_request_new": {
        "en": ("New request to the alliance", "{user} wants to join «{name}». Open the alliance to accept or decline."),
        "ru": ("Новая заявка в альянс", "{user} хочет вступить в «{name}». Откройте альянс, чтобы принять или отклонить."),
        "es": ("Nueva solicitud a la alianza", "{user} quiere unirse a «{name}». Abre la alianza para aceptar o rechazar."),
        "zh": ("新的联盟申请", "{user} 想加入「{name}」。打开联盟以接受或拒绝。"),
        "fr": ("Nouvelle demande d’adhésion", "{user} veut rejoindre « {name} ». Ouvrez l’alliance pour accepter ou refuser."),
        "de": ("Neue Beitrittsanfrage", "{user} möchte „{name}“ beitreten. Öffne die Allianz, um anzunehmen oder abzulehnen."),
        "ja": ("同盟への新しい申請", "{user} が「{name}」への参加を希望しています。同盟を開いて承認または拒否してください。"),
        "ko": ("새 동맹 가입 신청", "{user}님이 «{name}»에 가입하려고 합니다. 동맹을 열어 수락하거나 거절하세요."),
        "id": ("Permintaan baru ke aliansi", "{user} ingin bergabung dengan «{name}». Buka aliansi untuk menerima atau menolak."),
    },
    "alliance_accepted": {
        "en": ("Welcome to the alliance!", "You are now a member of «{name}» [{tag}]."),
        "ru": ("Добро пожаловать в альянс!", "Теперь вы участник «{name}» [{tag}]."),
        "es": ("¡Bienvenido a la alianza!", "Ahora eres miembro de «{name}» [{tag}]."),
        "zh": ("欢迎加入联盟！", "你现在是「{name}」[{tag}] 的成员。"),
        "fr": ("Bienvenue dans l’alliance !", "Vous êtes maintenant membre de « {name} » [{tag}]."),
        "de": ("Willkommen in der Allianz!", "Du bist jetzt Mitglied von „{name}“ [{tag}]."),
        "ja": ("同盟へようこそ！", "あなたは「{name}」[{tag}] のメンバーになりました。"),
        "ko": ("동맹에 오신 것을 환영합니다!", "이제 «{name}» [{tag}]의 멤버입니다."),
        "id": ("Selamat datang di aliansi!", "Sekarang kamu anggota «{name}» [{tag}]."),
    },
    "alliance_declined": {
        "en": ("Request declined", "«{name}» declined your request."),
        "ru": ("Заявка отклонена", "«{name}» отклонил вашу заявку."),
        "es": ("Solicitud rechazada", "«{name}» rechazó tu solicitud."),
        "zh": ("申请被拒绝", "「{name}」拒绝了你的申请。"),
        "fr": ("Demande refusée", "« {name} » a refusé votre demande."),
        "de": ("Anfrage abgelehnt", "„{name}“ hat deine Anfrage abgelehnt."),
        "ja": ("申請が拒否されました", "「{name}」があなたの申請を拒否しました。"),
        "ko": ("신청 거절됨", "«{name}»이(가) 신청을 거절했습니다."),
        "id": ("Permintaan ditolak", "«{name}» menolak permintaanmu."),
    },
    "alliance_invite": {
        "en": ("Invitation to an alliance", "{user} invites you to «{name}» [{tag}]. Open «Alliances» to accept."),
        "ru": ("Приглашение в альянс", "{user} приглашает вас в «{name}» [{tag}]. Откройте «Альянсы», чтобы принять."),
        "es": ("Invitación a una alianza", "{user} te invita a «{name}» [{tag}]. Abre «Alianzas» para aceptar."),
        "zh": ("联盟邀请", "{user} 邀请你加入「{name}」[{tag}]。打开「联盟」接受邀请。"),
        "fr": ("Invitation dans une alliance", "{user} vous invite dans « {name} » [{tag}]. Ouvrez « Alliances » pour accepter."),
        "de": ("Einladung in eine Allianz", "{user} lädt dich in „{name}“ [{tag}] ein. Öffne „Allianzen“, um anzunehmen."),
        "ja": ("同盟への招待", "{user} があなたを「{name}」[{tag}] に招待しました。「同盟」を開いて承認してください。"),
        "ko": ("동맹 초대", "{user}님이 «{name}» [{tag}]에 초대했습니다. «동맹»을 열어 수락하세요."),
        "id": ("Undangan ke aliansi", "{user} mengundangmu ke «{name}» [{tag}]. Buka «Aliansi» untuk menerima."),
    },
    "alliance_kicked": {
        "en": ("You were removed from the alliance", "You are no longer a member of «{name}»."),
        "ru": ("Вас исключили из альянса", "Вы больше не участник «{name}»."),
        "es": ("Te expulsaron de la alianza", "Ya no eres miembro de «{name}»."),
        "zh": ("你已被移出联盟", "你不再是「{name}」的成员。"),
        "fr": ("Vous avez été exclu de l’alliance", "Vous n’êtes plus membre de « {name} »."),
        "de": ("Du wurdest aus der Allianz entfernt", "Du bist kein Mitglied von „{name}“ mehr."),
        "ja": ("同盟から除名されました", "あなたは「{name}」のメンバーではなくなりました。"),
        "ko": ("동맹에서 제외되었습니다", "더 이상 «{name}»의 멤버가 아닙니다."),
        "id": ("Kamu dikeluarkan dari aliansi", "Kamu bukan lagi anggota «{name}»."),
    },
    "alliance_role": {
        "en": ("New role in the alliance", "Your role in «{name}»: {role}."),
        "ru": ("Новая роль в альянсе", "Ваша роль в «{name}»: {role}."),
        "es": ("Nuevo rol en la alianza", "Tu rol en «{name}»: {role}."),
        "zh": ("联盟中的新角色", "你在「{name}」中的角色：{role}。"),
        "fr": ("Nouveau rôle dans l’alliance", "Votre rôle dans « {name} » : {role}."),
        "de": ("Neue Rolle in der Allianz", "Deine Rolle in „{name}“: {role}."),
        "ja": ("同盟での新しい役職", "「{name}」でのあなたの役職：{role}。"),
        "ko": ("동맹 내 새 역할", "«{name}»에서의 역할: {role}."),
        "id": ("Peran baru di aliansi", "Peranmu di «{name}»: {role}."),
    },
    "alliance_level_up": {
        "en": ("Alliance level up!", "«{name}» reached level {level}: now up to {slots} members."),
        "ru": ("Новый уровень альянса!", "«{name}» достиг уровня {level}: теперь до {slots} участников."),
        "es": ("¡La alianza sube de nivel!", "«{name}» alcanzó el nivel {level}: ahora hasta {slots} miembros."),
        "zh": ("联盟升级！", "「{name}」达到 {level} 级：现在最多 {slots} 名成员。"),
        "fr": ("L’alliance monte de niveau !", "« {name} » a atteint le niveau {level} : jusqu’à {slots} membres."),
        "de": ("Allianz-Levelaufstieg!", "„{name}“ hat Level {level} erreicht: jetzt bis zu {slots} Mitglieder."),
        "ja": ("同盟レベルアップ！", "「{name}」がレベル {level} に到達：最大 {slots} 人まで参加できます。"),
        "ko": ("동맹 레벨 업!", "«{name}»이(가) {level}레벨에 도달: 이제 최대 {slots}명."),
        "id": ("Aliansi naik level!", "«{name}» mencapai level {level}: kini hingga {slots} anggota."),
    },
    "alliance_disbanded": {
        "en": ("The alliance was disbanded", "«{name}» no longer exists. Your share of the treasury: {amount} $CITY (bonus balance)."),
        "ru": ("Альянс распущен", "«{name}» больше не существует. Ваша доля казны: {amount} $CITY (бонусный баланс)."),
        "es": ("La alianza se disolvió", "«{name}» ya no existe. Tu parte del tesoro: {amount} $CITY (saldo de bonificación)."),
        "zh": ("联盟已解散", "「{name}」已不存在。你分得的金库份额：{amount} $CITY（奖励余额）。"),
        "fr": ("L’alliance a été dissoute", "« {name} » n’existe plus. Votre part du trésor : {amount} $CITY (solde bonus)."),
        "de": ("Die Allianz wurde aufgelöst", "„{name}“ existiert nicht mehr. Dein Anteil an der Kasse: {amount} $CITY (Bonusguthaben)."),
        "ja": ("同盟が解散しました", "「{name}」は存在しなくなりました。金庫の分配額：{amount} $CITY（ボーナス残高）。"),
        "ko": ("동맹이 해산되었습니다", "«{name}»은(는) 더 이상 존재하지 않습니다. 금고 분배액: {amount} $CITY (보너스 잔액)."),
        "id": ("Aliansi dibubarkan", "«{name}» sudah tidak ada. Bagianmu dari kas: {amount} $CITY (saldo bonus)."),
    },
    "alliance_leader": {
        "en": ("You are the alliance leader", "You now lead «{name}» [{tag}]."),
        "ru": ("Вы — лидер альянса", "Теперь вы руководите «{name}» [{tag}]."),
        "es": ("Eres el líder de la alianza", "Ahora diriges «{name}» [{tag}]."),
        "zh": ("你是联盟首领", "你现在领导「{name}」[{tag}]。"),
        "fr": ("Vous êtes le chef de l’alliance", "Vous dirigez désormais « {name} » [{tag}]."),
        "de": ("Du bist Anführer der Allianz", "Du führst jetzt „{name}“ [{tag}]."),
        "ja": ("あなたは同盟のリーダーです", "あなたは「{name}」[{tag}] を率いることになりました。"),
        "ko": ("당신이 동맹의 리더입니다", "이제 «{name}» [{tag}]을(를) 이끕니다."),
        "id": ("Kamu pemimpin aliansi", "Sekarang kamu memimpin «{name}» [{tag}]."),
    },
    "alliance_payout": {
        "en": ("Payout from the alliance", "«{name}» paid you {amount} $CITY from the treasury (bonus balance)."),
        "ru": ("Выплата из казны альянса", "«{name}» выплатил вам {amount} $CITY из казны (бонусный баланс)."),
        "es": ("Pago de la alianza", "«{name}» te pagó {amount} $CITY del tesoro (saldo de bonificación)."),
        "zh": ("联盟发放", "「{name}」从金库向你发放了 {amount} $CITY（奖励余额）。"),
        "fr": ("Versement de l’alliance", "« {name} » vous a versé {amount} $CITY du trésor (solde bonus)."),
        "de": ("Auszahlung der Allianz", "„{name}“ hat dir {amount} $CITY aus der Kasse ausgezahlt (Bonusguthaben)."),
        "ja": ("同盟からの支給", "「{name}」が金庫から {amount} $CITY を支給しました（ボーナス残高）。"),
        "ko": ("동맹 지급", "«{name}»이(가) 금고에서 {amount} $CITY를 지급했습니다 (보너스 잔액)."),
        "id": ("Pembayaran dari aliansi", "«{name}» membayarmu {amount} $CITY dari kas (saldo bonus)."),
    },
}
ROLE_NAMES = {
    "leader": {"en": "leader", "ru": "лидер", "es": "líder", "zh": "首领", "fr": "chef", "de": "Anführer", "ja": "リーダー", "ko": "리더", "id": "pemimpin"},
    "deputy": {"en": "deputy", "ru": "заместитель", "es": "adjunto", "zh": "副首领", "fr": "adjoint", "de": "Stellvertreter", "ja": "副リーダー", "ko": "부리더", "id": "wakil"},
    "officer": {"en": "officer", "ru": "офицер", "es": "oficial", "zh": "军官", "fr": "officier", "de": "Offizier", "ja": "オフィサー", "ko": "장교", "id": "perwira"},
    "member": {"en": "member", "ru": "участник", "es": "miembro", "zh": "成员", "fr": "membre", "de": "Mitglied", "ja": "メンバー", "ko": "멤버", "id": "anggota"},
}

try:                                                    # notify_user renders i18n_key from this table
    from core.notif_i18n import NOTIF as _NOTIF
    _NOTIF.update(ALLIANCE_NOTIF)
except Exception:                                       # pragma: no cover
    pass


# ───────────────────────────── small helpers ─────────────────────────────
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime] = None) -> str:
    return (dt or _now()).isoformat()


def _uid() -> str:
    return str(uuid.uuid4())


def _day() -> str:
    from core.timeutil import msk_today
    return msk_today().isoformat()


def _week() -> str:
    d = _now() + timedelta(hours=3)
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _r2(x: float) -> float:
    return math.floor(float(x) * 100 + 1e-6) / 100.0


def err(code: str, status: int = 400, **extra) -> HTTPException:
    """Errors carry a code the app translates (detail={"code": …})."""
    return HTTPException(status_code=status, detail={"code": code, **extra})


_TASKS: set = set()


def _spawn(coro) -> None:
    try:
        t = asyncio.get_running_loop().create_task(coro)
        _TASKS.add(t)
        t.add_done_callback(_TASKS.discard)
    except RuntimeError:
        pass


# ───────────────────────────── config ─────────────────────────────
async def get_config(db) -> Dict[str, Any]:
    doc = await db.admin_settings.find_one({"type": "alliances"}, {"_id": 0}) or {}
    cfg = {**DEFAULT_CONFIG, **{k: v for k, v in doc.items() if k in DEFAULT_CONFIG}}
    if not isinstance(cfg.get("levels"), list) or not cfg["levels"]:
        cfg["levels"] = DEFAULT_LEVELS
    return cfg


async def save_config(db, patch: Dict[str, Any]) -> Dict[str, Any]:
    upd: Dict[str, Any] = {}
    for k, v in (patch or {}).items():
        if k not in DEFAULT_CONFIG:
            continue
        if k == "levels":
            rows, prev_axp, prev_slots = [], -1, 0
            for i, row in enumerate(v or []):
                lv = {"level": i + 1, "axp": int(row.get("axp") or 0), "fee_city": int(row.get("fee_city") or 0),
                      "slots": int(row.get("slots") or 0), "unlocks": list(row.get("unlocks") or [])}
                if lv["axp"] < 0 or lv["fee_city"] < 0 or not (2 <= lv["slots"] <= 200):
                    raise ValueError(f"Уровень {i + 1}: неверные числа")
                if lv["axp"] <= prev_axp and i > 0:
                    raise ValueError(f"Уровень {i + 1}: AXP должен расти от уровня к уровню")
                if lv["slots"] < prev_slots:
                    raise ValueError(f"Уровень {i + 1}: мест не может стать меньше")
                prev_axp, prev_slots = lv["axp"], lv["slots"]
                rows.append(lv)
            if not rows or rows[0]["axp"] != 0:
                raise ValueError("Уровень 1 должен начинаться с 0 AXP")
            upd[k] = rows
        elif isinstance(DEFAULT_CONFIG[k], bool):
            upd[k] = bool(v)
        else:
            n = float(v)
            if n < 0:
                raise ValueError(f"{k}: не может быть отрицательным")
            upd[k] = int(n) if isinstance(DEFAULT_CONFIG[k], int) else n
    if "tax_max_pct" in upd and upd["tax_max_pct"] > 20:
        raise ValueError("Налог: не больше 20 %")
    if "axp_share_pct" in upd and upd["axp_share_pct"] > 100:
        raise ValueError("Доля AXP: не больше 100 %")
    await db.admin_settings.update_one({"type": "alliances"}, {"$set": {"type": "alliances", **upd}}, upsert=True)
    return await get_config(db)


def level_row(cfg: Dict, level: int) -> Dict:
    lv = cfg["levels"]
    return lv[max(0, min(int(level or 1), len(lv)) - 1)]


def slots_of(cfg: Dict, level: int) -> int:
    return int(level_row(cfg, level)["slots"])


# ───────────────────────────── indexes ─────────────────────────────
_IDX_DONE = False


async def ensure_indexes(db) -> None:
    global _IDX_DONE
    if _IDX_DONE:
        return
    try:
        await db.alliances.create_index("id", unique=True)
        await db.alliances.create_index("name_lower", unique=True)
        await db.alliances.create_index("tag_lower", unique=True)
        await db.alliance_members.create_index("user_id", unique=True)      # one alliance per player
        await db.alliance_members.create_index("alliance_id")
        await db.alliance_requests.create_index([("alliance_id", 1), ("status", 1)])
        await db.alliance_requests.create_index([("user_id", 1), ("status", 1)])
        await db.alliance_log.create_index([("alliance_id", 1), ("created_at", -1)])
        _IDX_DONE = True
    except Exception as e:                              # pragma: no cover
        logger.warning("alliances indexes: %s", e)


# ───────────────────────────── reads ─────────────────────────────
async def member_of(db, uid: str) -> Optional[Dict]:
    return await db.alliance_members.find_one({"user_id": uid}, {"_id": 0})


async def alliance(db, aid: str) -> Optional[Dict]:
    return await db.alliances.find_one({"id": aid, "status": "active"}, {"_id": 0})


async def _require_member(db, uid: str, min_role: str = "member"):
    m = await member_of(db, uid)
    if not m:
        raise err("not_member", 403)
    a = await alliance(db, m["alliance_id"])
    if not a:
        raise err("not_found", 404)
    if RANK.get(m.get("role"), 0) < RANK[min_role]:
        raise err("no_rights", 403)
    return m, a


async def pass_level(db, uid: str) -> int:
    try:
        import city_pass as cp
        cfg = await cp.get_config(db)
        p = await cp._progress(db, uid, cfg)
        return int(cp._level(cfg, int(p.get("xp", 0) or 0)))
    except Exception as e:                              # pragma: no cover
        logger.debug("alliances pass level: %s", e)
        return 0


async def has_business(db, uid: str) -> bool:
    try:
        from core.helpers import resolve_owner_keys, owner_businesses_query
        q = owner_businesses_query(await resolve_owner_keys(db, uid))
        return await db.businesses.count_documents({**q, "tutorial": {"$ne": True}}, limit=1) > 0
    except Exception as e:                              # pragma: no cover
        logger.debug("alliances has_business: %s", e)
        return False


async def businesses_of(db, uid: str) -> List[Dict]:
    """The player's real businesses for the officers deciding on a request: type, level, the resource it
    produces and how much per day (durability applied), working or idle."""
    out: List[Dict] = []
    try:
        from core.helpers import resolve_owner_keys, owner_businesses_query
        from business_config import BUSINESSES, calculate_effective_production
        q = owner_businesses_query(await resolve_owner_keys(db, uid))
        async for b in db.businesses.find({**q, "tutorial": {"$ne": True}},
                                          {"_id": 0, "business_type": 1, "level": 1, "durability": 1, "is_active": 1}).limit(30):
            bt = b.get("business_type") or ""
            lvl = int(b.get("level") or 0)
            conf = BUSINESSES.get(bt) or {}
            try:
                per_day = float(calculate_effective_production(bt, max(1, lvl), float(b.get("durability", 100) or 0))) if lvl > 0 else 0.0
            except Exception:
                per_day = 0.0
            out.append({"type": bt, "level": lvl, "produces": conf.get("produces"), "per_day": round(per_day, 2),
                        "tier": conf.get("tier"), "active": bool(b.get("is_active", True))})
        out.sort(key=lambda x: (-(x.get("tier") or 0), -x["level"]))
    except Exception as e:                              # pragma: no cover
        logger.debug("alliances businesses_of: %s", e)
    return out


async def device_mates(db, uid: str) -> set:
    """Accounts that share a device fingerprint with this player (the same check as leagues / mini-game)."""
    try:
        visitors = await db.fingerprints.distinct("visitor_id", {"user_id": uid, "visitor_id": {"$ne": None}})
        if not visitors:
            return set()
        return set(await db.fingerprints.distinct("user_id", {"visitor_id": {"$in": visitors}})) - {uid}
    except Exception:
        return set()


def public_alliance(a: Dict, cfg: Dict) -> Dict:
    lv = int(a.get("level") or 1)
    return {"id": a["id"], "name": a["name"], "tag": a["tag"], "emblem": a.get("emblem") or "🛡️",
            "emblem_bg": a.get("emblem_bg") if a.get("emblem_bg") in EMBLEM_BGS else EMBLEM_BGS[0],
            "lang": a.get("lang") or "en", "description": a.get("description") or "", "level": lv,
            "members_count": int(a.get("members_count") or 0), "slots": slots_of(cfg, lv),
            "join_mode": a.get("join_mode") or "request",
            "axp": int(a.get("axp") or 0), "created_at": a.get("created_at")}


async def _sync_user(db, uid: str, a: Optional[Dict]) -> None:
    """Copy of the alliance on the player (header, chat, map read it without a join)."""
    if a:
        await db.users.update_one({"id": uid}, {"$set": {"alliance_id": a["id"], "alliance_name": a["name"],
                                                          "alliance_tag": a["tag"], "alliance_emblem": a.get("emblem")}})
    else:
        await db.users.update_one({"id": uid}, {"$unset": {"alliance_id": "", "alliance_name": "", "alliance_tag": "",
                                                            "alliance_emblem": ""}})


async def _log(db, aid: str, kind: str, uid: Optional[str] = None, amount_city: float = 0.0, **meta) -> None:
    try:
        await db.alliance_log.insert_one({"id": _uid(), "alliance_id": aid, "kind": kind, "user_id": uid,
                                          "amount_city": _r2(amount_city), "meta": meta, "created_at": _iso()})
    except Exception as e:                              # pragma: no cover
        logger.debug("alliance log: %s", e)


async def _username(db, uid: str) -> str:
    u = await db.users.find_one({"id": uid}, {"_id": 0, "username": 1, "display_name": 1}) or {}
    return u.get("username") or u.get("display_name") or "—"


def _notify(db, uid: str, key: str, **vars_) -> None:
    async def go():
        try:
            from core.notify import notify_user
            await notify_user(db, uid, "", "", type_key="alliance", priority="info", i18n_key=key, i18n_vars=vars_)
        except Exception as e:                          # pragma: no cover
            logger.debug("alliance notify: %s", e)
    _spawn(go())


def _notify_role(db, uid: str, a: Dict, role: str) -> None:
    async def go():
        try:
            from core.notify import notify_user
            from core.notif_i18n import user_lang
            u = await db.users.find_one({"id": uid}, {"_id": 0}) or {"id": uid}
            lang = user_lang(u)
            await notify_user(db, u, "", "", type_key="alliance", i18n_key="alliance_role",
                              i18n_vars={"name": a["name"], "role": ROLE_NAMES[role].get(lang, role)})
        except Exception as e:                          # pragma: no cover
            logger.debug("alliance role notify: %s", e)
    _spawn(go())


async def _staff_ids(db, aid: str, min_role: str = "officer") -> List[str]:
    roles = [r for r in ROLES if RANK[r] >= RANK[min_role]]
    return [m["user_id"] async for m in db.alliance_members.find({"alliance_id": aid, "role": {"$in": roles}}, {"_id": 0, "user_id": 1})]


# ───────────────────────────── membership ─────────────────────────────
async def _check_can_join(db, uid: str, a: Dict, cfg: Dict) -> None:
    if await member_of(db, uid):
        raise err("already_member", 409)
    u = await db.users.find_one({"id": uid}, {"_id": 0, "alliance_left_at": 1}) or {}
    left = u.get("alliance_left_at")
    if left:
        try:
            until = datetime.fromisoformat(str(left)) + timedelta(hours=int(cfg["rejoin_cooldown_hours"]))
            if until > _now():
                raise err("rejoin_cooldown", 400, until=until.isoformat())
        except HTTPException:
            raise
        except Exception:
            pass
    # joining has no City Pass requirement: the officers decide by the player's businesses (shown in the request)
    mates = await device_mates(db, uid)
    if mates and await db.alliance_members.count_documents({"alliance_id": a["id"], "user_id": {"$in": list(mates)}}, limit=1):
        raise err("linked_account", 400)


async def _add_member(db, uid: str, a: Dict, cfg: Dict, role: str = "member") -> Dict:
    """Take a place atomically (members_count < slots), then the unique row; give the place back on failure."""
    slots = slots_of(cfg, int(a.get("level") or 1))
    took = await db.alliances.update_one({"id": a["id"], "status": "active", "members_count": {"$lt": slots}},
                                         {"$inc": {"members_count": 1}, "$unset": {"solo_since": ""}})
    if not took.modified_count:
        raise err("full", 409)
    row = {"user_id": uid, "alliance_id": a["id"], "role": role, "joined_at": _iso(), "axp_total": 0,
           "deposited_city": 0.0, "tax_paid_city": 0.0, "axp_days": {}}
    try:
        await db.alliance_members.insert_one(dict(row))
    except Exception:
        await db.alliances.update_one({"id": a["id"]}, {"$inc": {"members_count": -1}})
        raise err("already_member", 409)
    await db.alliance_requests.update_many({"user_id": uid, "status": "pending"}, {"$set": {"status": "cancelled", "closed_at": _iso()}})
    await _sync_user(db, uid, a)
    await _log(db, a["id"], "join", uid)
    return row


async def _remove_member(db, uid: str, a: Dict, kind: str, by: Optional[str] = None) -> None:
    r = await db.alliance_members.delete_one({"user_id": uid, "alliance_id": a["id"]})
    if not r.deleted_count:
        return
    await db.alliances.update_one({"id": a["id"]}, {"$inc": {"members_count": -1}})
    after = await db.alliances.find_one({"id": a["id"]}, {"_id": 0, "members_count": 1}) or {}
    if int(after.get("members_count") or 0) == 1:
        await db.alliances.update_one({"id": a["id"]}, {"$set": {"solo_since": _iso()}})
    await db.users.update_one({"id": uid}, {"$set": {"alliance_left_at": _iso()}})
    await _sync_user(db, uid, None)
    await _log(db, a["id"], kind, uid, by=by)


async def create(db, uid: str, body: Dict) -> Dict:
    cfg = await get_config(db)
    if not cfg["enabled"]:
        raise err("disabled", 403)
    name = re.sub(r"\s+", " ", str(body.get("name") or "")).strip()
    tag = str(body.get("tag") or "").strip().upper()
    if not NAME_RE.match(name):
        raise err("bad_name")
    if not TAG_RE.match(tag):
        raise err("bad_tag")
    emblem = body.get("emblem") if body.get("emblem") in EMBLEMS else EMBLEMS[0]
    emblem_bg = body.get("emblem_bg") if body.get("emblem_bg") in EMBLEM_BGS else EMBLEM_BGS[0]
    lang = body.get("lang") if body.get("lang") in LANGS else "en"
    join_mode = body.get("join_mode") if body.get("join_mode") in JOIN_MODES else "request"
    desc = str(body.get("description") or "").strip()[:200]
    if await member_of(db, uid):
        raise err("already_member", 409)
    if await db.alliances.find_one({"status": "active", "$or": [{"leader_id": uid}, {"creator_id": uid}]}, {"_id": 1}):
        raise err("already_leader", 409)                # one alliance per player: created or led
    if await pass_level(db, uid) < int(cfg["create_min_pass_level"]):
        raise err("pass_level_low", 400, need=int(cfg["create_min_pass_level"]))
    if cfg["create_requires_business"] and not await has_business(db, uid):
        raise err("need_business")
    if await db.alliances.find_one({"name_lower": name.lower()}, {"_id": 1}):
        raise err("name_taken", 409)
    if await db.alliances.find_one({"tag_lower": tag.lower()}, {"_id": 1}):
        raise err("tag_taken", 409)
    cost = float(cfg["create_cost_city"])
    paid = {"from_bonus": 0.0, "from_real": 0.0}
    if cost > 0:
        from core.balance import debit_user_split
        paid = await debit_user_split(db, {"id": uid}, cost / CITY_PER_TON)
        if not paid.get("ok"):
            raise err("insufficient", 400, need=cost)
    a = {"id": _uid(), "name": name, "name_lower": name.lower(), "tag": tag, "tag_lower": tag.lower(), "emblem": emblem, "emblem_bg": emblem_bg,
         "lang": lang, "description": desc, "join_mode": join_mode, "min_pass_level": 0, "level": 1, "axp": 0,
         "axp_weeks": {}, "treasury_city": 0.0, "tax_pct": 0, "tax_changed_at": None, "leader_id": uid, "creator_id": uid,
         "members_count": 0, "status": "active", "frozen": False, "pinned": "", "created_at": _iso(), "solo_since": _iso()}

    async def refund():
        if cost > 0:
            from core.balance import refund_split
            await refund_split(db, {"id": uid}, paid.get("from_bonus", 0.0), paid.get("from_real", 0.0))
    try:
        await db.alliances.insert_one(dict(a))
    except Exception:
        await refund()
        taken_name = await db.alliances.find_one({"name_lower": name.lower()}, {"_id": 1})
        raise err("name_taken" if taken_name else "tag_taken", 409)
    try:
        await _add_member(db, uid, a, cfg, role="leader")
    except HTTPException:
        await db.alliances.delete_one({"id": a["id"]})
        await refund()
        raise
    await db.alliances.update_one({"id": a["id"]}, {"$set": {"solo_since": _iso()}})
    await _log(db, a["id"], "create", uid, cost)
    if cost > 0:
        await db.transactions.insert_one({"id": _uid(), "tx_type": "alliance_create", "type": "alliance_create", "user_id": uid,
                                          "amount": -cost / CITY_PER_TON, "amount_ton": -cost / CITY_PER_TON, "amount_city": cost,
                                          "status": "completed", "description": f"Alliance «{name}» [{tag}]", "created_at": _iso()})
    return public_alliance({**a, "members_count": 1}, cfg)


async def join(db, uid: str, aid: str) -> Dict:
    cfg = await get_config(db)
    a = await alliance(db, aid)
    if not a:
        raise err("not_found", 404)
    await _check_can_join(db, uid, a, cfg)
    mode = a.get("join_mode") or "request"
    if mode == "invite":
        inv = await db.alliance_requests.find_one({"alliance_id": aid, "user_id": uid, "kind": "invite", "status": "pending"}, {"_id": 0})
        if not inv:
            raise err("invite_only", 403)
    if mode == "open":
        await _add_member(db, uid, a, cfg)
        _notify(db, uid, "alliance_accepted", name=a["name"], tag=a["tag"])
        return {"status": "joined"}
    if mode == "request":
        if await db.alliance_requests.find_one({"alliance_id": aid, "user_id": uid, "kind": "request", "status": "pending"}, {"_id": 1}):
            return {"status": "requested"}
        if await db.alliance_requests.count_documents({"user_id": uid, "kind": "request", "status": "pending"}) >= 5:
            raise err("too_many_requests")
        await db.alliance_requests.insert_one({"id": _uid(), "alliance_id": aid, "user_id": uid, "kind": "request",
                                               "status": "pending", "by": uid, "created_at": _iso()})
        user = await _username(db, uid)
        for sid in await _staff_ids(db, aid):
            _notify(db, sid, "alliance_request_new", user=user, name=a["name"])
        return {"status": "requested"}
    return {"status": "invite_only"}


async def cancel_request(db, uid: str, aid: str) -> Dict:
    await db.alliance_requests.update_many({"alliance_id": aid, "user_id": uid, "kind": "request", "status": "pending"},
                                           {"$set": {"status": "cancelled", "closed_at": _iso()}})
    return {"ok": True}


async def answer_request(db, staff_uid: str, rid: str, accept: bool) -> Dict:
    m, a = await _require_member(db, staff_uid, "officer")
    req = await db.alliance_requests.find_one({"id": rid, "alliance_id": a["id"], "kind": "request", "status": "pending"}, {"_id": 0})
    if not req:
        raise err("request_not_found", 404)
    closed = await db.alliance_requests.update_one({"id": rid, "status": "pending"},
                                                   {"$set": {"status": "accepted" if accept else "declined", "closed_at": _iso(), "closed_by": staff_uid}})
    if not closed.modified_count:
        raise err("request_not_found", 404)
    if not accept:
        _notify(db, req["user_id"], "alliance_declined", name=a["name"])
        return {"status": "declined"}
    cfg = await get_config(db)
    try:
        await _check_can_join(db, req["user_id"], a, cfg)
        await _add_member(db, req["user_id"], a, cfg)
    except HTTPException:
        await db.alliance_requests.update_one({"id": rid}, {"$set": {"status": "pending"}, "$unset": {"closed_at": "", "closed_by": ""}})
        raise
    _notify(db, req["user_id"], "alliance_accepted", name=a["name"], tag=a["tag"])
    return {"status": "accepted"}


async def invite(db, staff_uid: str, username: str) -> Dict:
    m, a = await _require_member(db, staff_uid, "officer")
    uname = str(username or "").strip().lstrip("@")
    if not uname:
        raise err("user_not_found", 404)
    u = await db.users.find_one({"username": {"$regex": f"^{re.escape(uname)}$", "$options": "i"}}, {"_id": 0, "id": 1, "username": 1})
    if not u:
        raise err("user_not_found", 404)
    if await member_of(db, u["id"]):
        raise err("already_member", 409)
    if await db.alliance_requests.find_one({"alliance_id": a["id"], "user_id": u["id"], "kind": "invite", "status": "pending"}, {"_id": 1}):
        return {"status": "invited"}
    await db.alliance_requests.insert_one({"id": _uid(), "alliance_id": a["id"], "user_id": u["id"], "kind": "invite",
                                           "status": "pending", "by": staff_uid, "created_at": _iso()})
    _notify(db, u["id"], "alliance_invite", user=await _username(db, staff_uid), name=a["name"], tag=a["tag"])
    return {"status": "invited", "username": u["username"]}


async def answer_invite(db, uid: str, rid: str, accept: bool) -> Dict:
    inv = await db.alliance_requests.find_one({"id": rid, "user_id": uid, "kind": "invite", "status": "pending"}, {"_id": 0})
    if not inv:
        raise err("request_not_found", 404)
    a = await alliance(db, inv["alliance_id"])
    if not a:
        await db.alliance_requests.update_one({"id": rid}, {"$set": {"status": "expired"}})
        raise err("not_found", 404)
    if not accept:
        await db.alliance_requests.update_one({"id": rid}, {"$set": {"status": "declined", "closed_at": _iso()}})
        return {"status": "declined"}
    cfg = await get_config(db)
    await _check_can_join(db, uid, a, cfg)
    await _add_member(db, uid, a, cfg)
    await db.alliance_requests.update_one({"id": rid}, {"$set": {"status": "accepted", "closed_at": _iso()}})
    _notify(db, uid, "alliance_accepted", name=a["name"], tag=a["tag"])
    return {"status": "joined"}


async def leave(db, uid: str) -> Dict:
    m, a = await _require_member(db, uid)
    if m["role"] == "leader":
        if int(a.get("members_count") or 0) > 1:
            raise err("leader_must_transfer")
        return await disband(db, a, by=uid)
    await _remove_member(db, uid, a, "leave")
    return {"status": "left"}


async def kick(db, staff_uid: str, target_uid: str) -> Dict:
    m, a = await _require_member(db, staff_uid, "deputy")
    t = await db.alliance_members.find_one({"user_id": target_uid, "alliance_id": a["id"]}, {"_id": 0})
    if not t:
        raise err("not_member", 404)
    if RANK[t["role"]] >= RANK[m["role"]]:
        raise err("no_rights", 403)
    await _remove_member(db, target_uid, a, "kick", by=staff_uid)
    _notify(db, target_uid, "alliance_kicked", name=a["name"])
    return {"status": "kicked"}


async def set_role(db, staff_uid: str, target_uid: str, role: str) -> Dict:
    if role not in ("deputy", "officer", "member"):
        raise err("bad_role")
    # statuses (deputy / officer / member) are given ONLY by the leader — nobody else
    m, a = await _require_member(db, staff_uid, "leader")
    t = await db.alliance_members.find_one({"user_id": target_uid, "alliance_id": a["id"]}, {"_id": 0})
    if not t or target_uid == staff_uid:
        raise err("not_member", 404)
    cfg = await get_config(db)
    if role in ("deputy", "officer") and t["role"] != role:
        cap = int(cfg["deputies_max"] if role == "deputy" else cfg["officers_max"])
        if await db.alliance_members.count_documents({"alliance_id": a["id"], "role": role}) >= cap:
            raise err("role_limit", 400, max=cap)
    await db.alliance_members.update_one({"user_id": target_uid, "alliance_id": a["id"]}, {"$set": {"role": role}})
    await _log(db, a["id"], "role", target_uid, by=staff_uid, role=role)
    _notify_role(db, target_uid, a, role)
    return {"status": "ok"}


async def transfer_leader(db, leader_uid: str, target_uid: str, by: Optional[str] = None) -> Dict:
    m, a = await _require_member(db, leader_uid, "leader")
    t = await db.alliance_members.find_one({"user_id": target_uid, "alliance_id": a["id"]}, {"_id": 0})
    if not t or target_uid == leader_uid:
        raise err("not_member", 404)
    await db.alliance_members.update_one({"user_id": target_uid, "alliance_id": a["id"]}, {"$set": {"role": "leader"}})
    await db.alliance_members.update_one({"user_id": leader_uid, "alliance_id": a["id"]}, {"$set": {"role": "deputy"}})
    await db.alliances.update_one({"id": a["id"]}, {"$set": {"leader_id": target_uid}})
    await _log(db, a["id"], "leader", target_uid, by=by or leader_uid)
    _notify(db, target_uid, "alliance_leader", name=a["name"], tag=a["tag"])
    return {"status": "ok"}


async def update_settings(db, uid: str, body: Dict) -> Dict:
    m, a = await _require_member(db, uid, "officer")
    cfg = await get_config(db)
    upd: Dict[str, Any] = {}
    if "pinned" in body:                                          # officers may pin a message
        upd["pinned"] = str(body.get("pinned") or "").strip()[:300]
    if RANK[m["role"]] >= RANK["deputy"]:
        if "description" in body:
            upd["description"] = str(body.get("description") or "").strip()[:200]
        if body.get("emblem") in EMBLEMS:
            upd["emblem"] = body["emblem"]
        if body.get("emblem_bg") in EMBLEM_BGS:
            upd["emblem_bg"] = body["emblem_bg"]
        if body.get("join_mode") in JOIN_MODES:
            upd["join_mode"] = body["join_mode"]
        if body.get("lang") in LANGS:
            upd["lang"] = body["lang"]
    if "tax_pct" in body and int(body.get("tax_pct") or 0) != int(a.get("tax_pct") or 0):
        if m["role"] != "leader":
            raise err("no_rights", 403)
        pct = int(body.get("tax_pct") or 0)
        if not 0 <= pct <= int(cfg["tax_max_pct"]):
            raise err("bad_tax", 400, max=int(cfg["tax_max_pct"]))
        last = a.get("tax_changed_at")
        if last:
            nxt = datetime.fromisoformat(str(last)) + timedelta(days=int(cfg["tax_change_days"]))
            if nxt > _now():
                raise err("tax_cooldown", 400, until=nxt.isoformat())
        upd["tax_pct"] = pct
        upd["tax_changed_at"] = _iso()
        await _log(db, a["id"], "tax_set", uid, pct=pct)
    if upd:
        await db.alliances.update_one({"id": a["id"]}, {"$set": upd})
        if "emblem" in upd:
            await db.users.update_many({"alliance_id": a["id"]}, {"$set": {"alliance_emblem": upd["emblem"]}})
    return {"ok": True}


# ───────────────────────────── treasury ─────────────────────────────
async def deposit(db, uid: str, amount_city: float) -> Dict:
    m, a = await _require_member(db, uid)
    cfg = await get_config(db)
    amount = _r2(float(amount_city or 0))
    if amount < float(cfg["deposit_min_city"]):
        raise err("deposit_min", 400, min=cfg["deposit_min_city"])
    day = _day()
    today = float((m.get("deposit_days") or {}).get(day, 0) or 0)
    cap = float(cfg["deposit_daily_cap_city"])
    if today + amount > cap + 1e-9:
        raise err("deposit_cap", 400, left=_r2(max(0.0, cap - today)))
    from core.balance import debit_user_split
    paid = await debit_user_split(db, {"id": uid}, amount / CITY_PER_TON)
    if not paid.get("ok"):
        raise err("insufficient", 400, need=amount)
    await db.alliances.update_one({"id": a["id"]}, {"$inc": {"treasury_city": amount}})
    await db.alliance_members.update_one({"user_id": uid}, {"$inc": {"deposited_city": amount, f"deposit_days.{day}": amount}})
    await _log(db, a["id"], "deposit", uid, amount)
    await db.transactions.insert_one({"id": _uid(), "tx_type": "alliance_deposit", "type": "alliance_deposit", "user_id": uid,
                                      "amount": -amount / CITY_PER_TON, "amount_ton": -amount / CITY_PER_TON, "amount_city": amount,
                                      "status": "completed", "description": f"Alliance treasury [{a['tag']}]", "created_at": _iso()})
    return {"ok": True, "treasury_city": _r2(float(a.get("treasury_city") or 0) + amount)}


async def _credit_bonus(db, uid: str, amount_city: float, tx_type: str, desc: str) -> None:
    await db.users.update_one({"id": uid, "bonus_balance": None}, {"$set": {"bonus_balance": 0.0}})
    await db.users.update_one({"id": uid}, {"$inc": {"bonus_balance": amount_city / CITY_PER_TON}})
    await db.transactions.insert_one({"id": _uid(), "tx_type": tx_type, "type": tx_type, "user_id": uid,
                                      "amount": amount_city / CITY_PER_TON, "amount_ton": amount_city / CITY_PER_TON,
                                      "amount_city": amount_city, "balance": "bonus", "status": "completed",
                                      "description": desc, "created_at": _iso()})


async def payout(db, staff_uid: str, target_uid: str, amount_city: float) -> Dict:
    m, a = await _require_member(db, staff_uid, "deputy")
    if a.get("frozen"):
        raise err("frozen", 403)
    t = await db.alliance_members.find_one({"user_id": target_uid, "alliance_id": a["id"]}, {"_id": 0})
    if not t:
        raise err("not_member", 404)
    amount = _r2(float(amount_city or 0))
    if amount <= 0:
        raise err("bad_amount")
    cfg = await get_config(db)
    day = _day()
    if m["role"] == "deputy":
        spent = float((m.get("payout_days") or {}).get(day, 0) or 0)
        if spent + amount > float(cfg["deputy_daily_payout_city"]) + 1e-9:
            raise err("payout_cap", 400, left=_r2(max(0.0, float(cfg["deputy_daily_payout_city"]) - spent)))
    took = await db.alliances.update_one({"id": a["id"], "treasury_city": {"$gte": amount - 1e-9}}, {"$inc": {"treasury_city": -amount}})
    if not took.modified_count:
        raise err("treasury_low", 400)
    await db.alliance_members.update_one({"user_id": staff_uid}, {"$inc": {f"payout_days.{day}": amount}})
    await _credit_bonus(db, target_uid, amount, "alliance_payout", f"Alliance payout [{a['tag']}]")
    await _log(db, a["id"], "payout", target_uid, amount, by=staff_uid)
    _notify(db, target_uid, "alliance_payout", name=a["name"], amount=f"{amount:,.2f}".replace(",", " ").rstrip("0").rstrip("."))
    return {"ok": True}


async def take_tax(db, uid: str, income_city: float, source: str) -> float:
    """The alliance tax on a member's $CITY reward: returns the part that goes to the treasury
    (the caller credits only income − tax). 0 for players without an alliance or with tax 0."""
    try:
        income = float(income_city or 0)
        if income <= 0 or not uid:
            return 0.0
        m = await member_of(db, uid)
        if not m:
            return 0.0
        a = await db.alliances.find_one({"id": m["alliance_id"], "status": "active"}, {"_id": 0, "id": 1, "tax_pct": 1})
        pct = int((a or {}).get("tax_pct") or 0)
        if not a or pct <= 0:
            return 0.0
        tax = _r2(income * pct / 100.0)
        if tax <= 0:
            return 0.0
        await db.alliances.update_one({"id": a["id"]}, {"$inc": {"treasury_city": tax}})
        await db.alliance_members.update_one({"user_id": uid}, {"$inc": {"tax_paid_city": tax}})
        # one log row per member a day (no spam in the log)
        day = _day()
        await db.alliance_log.update_one({"id": f"tax:{a['id']}:{uid}:{day}"},
                                         {"$inc": {"amount_city": tax},
                                          "$setOnInsert": {"alliance_id": a["id"], "kind": "tax", "user_id": uid, "meta": {"day": day},
                                                           "created_at": _iso()}}, upsert=True)
        return tax
    except Exception as e:                              # pragma: no cover - the reward must never fail because of the tax
        logger.warning("alliance tax: %s", e)
        return 0.0


async def level_up(db, uid: str) -> Dict:
    m, a = await _require_member(db, uid, "deputy")
    cfg = await get_config(db)
    cur = int(a.get("level") or 1)
    if cur >= len(cfg["levels"]):
        raise err("max_level")
    nxt = level_row(cfg, cur + 1)
    need, fee = int(nxt["axp"]), float(nxt["fee_city"])
    if int(a.get("axp") or 0) < need:
        raise err("axp_low", 400, need=need)
    r = await db.alliances.update_one({"id": a["id"], "level": cur, "axp": {"$gte": need}, "treasury_city": {"$gte": fee - 1e-9}},
                                      {"$inc": {"level": 1, "treasury_city": -fee}})
    if not r.modified_count:
        raise err("treasury_low", 400, need=fee)
    await _log(db, a["id"], "level_up", uid, fee, level=cur + 1)
    async for mm in db.alliance_members.find({"alliance_id": a["id"]}, {"_id": 0, "user_id": 1}):
        _notify(db, mm["user_id"], "alliance_level_up", name=a["name"], level=cur + 1, slots=int(nxt["slots"]))
    return {"ok": True, "level": cur + 1}


# ───────────────────────────── alliance XP ─────────────────────────────
async def add_axp(db, uid: str, xp: int) -> int:
    """A share of a member's City Pass XP goes to the alliance (capped per player and day)."""
    try:
        if not uid or int(xp or 0) <= 0:
            return 0
        m = await member_of(db, uid)
        if not m:
            return 0
        cfg = await get_config(db)
        share = int(math.floor(int(xp) * float(cfg["axp_share_pct"]) / 100.0))
        day = _day()
        today = int((m.get("axp_days") or {}).get(day, 0) or 0)
        add = max(0, min(share, int(cfg["axp_daily_cap_per_player"]) - today))
        if add <= 0:
            return 0
        # keep only recent days on the row
        await db.alliance_members.update_one({"user_id": uid}, {"$inc": {f"axp_days.{day}": add, "axp_total": add}})
        await db.alliances.update_one({"id": m["alliance_id"]}, {"$inc": {"axp": add, f"axp_weeks.{_week()}": add}})
        return add
    except Exception as e:                              # pragma: no cover
        logger.debug("alliance axp: %s", e)
        return 0


def axp_bg(db, uid: str, xp: int) -> None:
    _spawn(add_axp(db, uid, xp))


# ───────────────────────────── disband / maintenance ─────────────────────────────
async def disband(db, a: Dict, by: Optional[str] = None, reason: str = "leader") -> Dict:
    """Close the alliance: the treasury is shared out to the members in proportion to their deposits of the last
    30 days (equally when nobody deposited), paid to the bonus balance."""
    claimed = await db.alliances.update_one({"id": a["id"], "status": "active"},
                                            {"$set": {"status": "disbanded", "disbanded_at": _iso(), "disband_reason": reason}})
    if not claimed.modified_count:
        raise err("not_found", 404)
    fresh = await db.alliances.find_one({"id": a["id"]}, {"_id": 0}) or a
    treasury = _r2(float(fresh.get("treasury_city") or 0))
    members = [mm async for mm in db.alliance_members.find({"alliance_id": a["id"]}, {"_id": 0, "user_id": 1})]
    ids = [mm["user_id"] for mm in members]
    since = _iso(_now() - timedelta(days=30))
    dep: Dict[str, float] = {}
    async for row in db.alliance_log.find({"alliance_id": a["id"], "kind": "deposit", "created_at": {"$gte": since}}, {"_id": 0, "user_id": 1, "amount_city": 1}):
        if row.get("user_id") in ids:
            dep[row["user_id"]] = dep.get(row["user_id"], 0.0) + float(row.get("amount_city") or 0)
    total = sum(dep.values())
    shares: Dict[str, float] = {}
    if treasury > 0 and ids:
        for u in ids:
            shares[u] = _r2(treasury * (dep.get(u, 0.0) / total if total > 0 else 1.0 / len(ids)))
    for u in ids:
        if shares.get(u, 0) > 0:
            await _credit_bonus(db, u, shares[u], "alliance_disband", f"Alliance [{a['tag']}] disbanded: share of the treasury")
        await _sync_user(db, u, None)
        _notify(db, u, "alliance_disbanded", name=a["name"], amount=f"{shares.get(u, 0):,.2f}".replace(",", " "))
    await db.alliance_members.delete_many({"alliance_id": a["id"]})
    await db.alliances.update_one({"id": a["id"]}, {"$set": {"treasury_city": 0.0, "members_count": 0,
                                                             # free the name and the tag for new alliances
                                                             "name_lower": f"__disbanded__{a['id']}", "tag_lower": f"__disbanded__{a['id']}"}})
    await db.alliance_requests.update_many({"alliance_id": a["id"], "status": "pending"}, {"$set": {"status": "expired"}})
    await _log(db, a["id"], "disband", by, treasury, reason=reason)
    return {"status": "disbanded", "shares": shares}


async def maintenance(db) -> Dict[str, int]:
    """Background job: expire old requests, replace inactive leaders, disband alliances left with one member."""
    cfg = await get_config(db)
    out = {"expired": 0, "leaders": 0, "disbanded": 0}
    old = _iso(_now() - timedelta(days=int(cfg["request_expire_days"])))
    r = await db.alliance_requests.update_many({"status": "pending", "created_at": {"$lt": old}}, {"$set": {"status": "expired"}})
    out["expired"] = r.modified_count
    lim_leader = _now() - timedelta(days=int(cfg["inactive_leader_days"]))
    lim_solo = _iso(_now() - timedelta(days=int(cfg["solo_disband_days"])))
    async for a in db.alliances.find({"status": "active"}, {"_id": 0}):
        try:
            if int(a.get("members_count") or 0) <= 1 and a.get("solo_since") and str(a["solo_since"]) < lim_solo:
                await disband(db, a, reason="solo")
                out["disbanded"] += 1
                continue
            seen = await db.online_presence.find_one({"user_id": a["leader_id"]}, {"_id": 0, "last_seen": 1})
            last = (seen or {}).get("last_seen")
            if not last or datetime.fromisoformat(str(last)) >= lim_leader:
                continue
            # the most active deputy, then officer, seen within the period
            for role in ("deputy", "officer", "member"):
                cands = [mm async for mm in db.alliance_members.find({"alliance_id": a["id"], "role": role}, {"_id": 0}).sort("axp_total", -1)]
                best = None
                for c in cands:
                    s = await db.online_presence.find_one({"user_id": c["user_id"]}, {"_id": 0, "last_seen": 1})
                    if s and s.get("last_seen") and datetime.fromisoformat(str(s["last_seen"])) >= lim_leader:
                        best = c
                        break
                if best:
                    await transfer_leader(db, a["leader_id"], best["user_id"], by="system")
                    out["leaders"] += 1
                    break
        except Exception as e:                          # pragma: no cover
            logger.warning("alliance maintenance %s: %s", a.get("id"), e)
    return out


# ───────────────────────────── views ─────────────────────────────
async def my_view(db, uid: str) -> Dict:
    cfg = await get_config(db)
    m = await member_of(db, uid)
    out: Dict[str, Any] = {"config": {k: cfg[k] for k in ("enabled", "create_cost_city", "create_min_pass_level", "create_requires_business",
                                                          "tax_max_pct", "tax_change_days", "deposit_min_city", "deposit_daily_cap_city",
                                                          "deputies_max", "officers_max", "axp_share_pct", "axp_daily_cap_per_player",
                                                          "rejoin_cooldown_hours")},
                           "levels": [{**lv, "live": [u for u in lv.get("unlocks", []) if u in LIVE_UNLOCKS]} for lv in cfg["levels"]],
                           "emblems": list(EMBLEMS), "emblem_bgs": list(EMBLEM_BGS), "alliance": None}
    if not m:
        invites, requests = [], []
        async for r in db.alliance_requests.find({"user_id": uid, "status": "pending"}, {"_id": 0}).sort("created_at", -1):
            a = await alliance(db, r["alliance_id"])
            if a:
                row = {"id": r["id"], "kind": r["kind"], "created_at": r["created_at"], "alliance": public_alliance(a, cfg)}
                (invites if r["kind"] == "invite" else requests).append(row)
        u = await db.users.find_one({"id": uid}, {"_id": 0, "alliance_left_at": 1}) or {}
        out.update(invites=invites, requests=requests, pass_level=await pass_level(db, uid),
                   has_business=await has_business(db, uid), left_at=u.get("alliance_left_at"))
        return out
    a = await alliance(db, m["alliance_id"])
    if not a:
        await db.alliance_members.delete_one({"user_id": uid})
        await _sync_user(db, uid, None)
        return await my_view(db, uid)
    rank = RANK[m["role"]]
    members = []
    rows = [mm async for mm in db.alliance_members.find({"alliance_id": a["id"]}, {"_id": 0})]
    ids = [r["user_id"] for r in rows]
    users = {u["id"]: u async for u in db.users.find({"id": {"$in": ids}}, {"_id": 0, "id": 1, "username": 1, "display_name": 1, "avatar": 1})}
    seen = {s["user_id"]: s.get("last_seen") async for s in db.online_presence.find({"user_id": {"$in": ids}}, {"_id": 0, "user_id": 1, "last_seen": 1})}
    day = _day()
    for r in rows:
        u = users.get(r["user_id"], {})
        members.append({"user_id": r["user_id"], "username": u.get("username") or u.get("display_name") or "—", "avatar": u.get("avatar"),
                        "role": r["role"], "joined_at": r.get("joined_at"), "axp_total": int(r.get("axp_total") or 0),
                        "axp_today": int((r.get("axp_days") or {}).get(day, 0) or 0),
                        "deposited_city": _r2(float(r.get("deposited_city") or 0)), "tax_paid_city": _r2(float(r.get("tax_paid_city") or 0)),
                        "last_seen": seen.get(r["user_id"])})
    members.sort(key=lambda x: (-RANK[x["role"]], -x["axp_total"]))
    log = []
    async for row in db.alliance_log.find({"alliance_id": a["id"]}, {"_id": 0}).sort("created_at", -1).limit(60):
        log.append({"kind": row.get("kind"), "user_id": row.get("user_id"), "username": users.get(row.get("user_id"), {}).get("username"),
                    "amount_city": _r2(float(row.get("amount_city") or 0)), "meta": row.get("meta") or {}, "created_at": row.get("created_at")})
    requests = []
    if rank >= RANK["officer"]:
        async for r in db.alliance_requests.find({"alliance_id": a["id"], "kind": "request", "status": "pending"}, {"_id": 0}).sort("created_at", 1):
            biz = await businesses_of(db, r["user_id"])
            produce: Dict[str, float] = {}
            for b in biz:
                if b.get("produces") and b["per_day"] > 0:
                    produce[b["produces"]] = round(produce.get(b["produces"], 0.0) + b["per_day"], 2)
            requests.append({"id": r["id"], "user_id": r["user_id"], "username": await _username(db, r["user_id"]),
                             "businesses": biz, "produces_per_day": produce, "created_at": r["created_at"]})
    lv = int(a.get("level") or 1)
    nxt = level_row(cfg, lv + 1) if lv < len(cfg["levels"]) else None
    tax_next = None
    if a.get("tax_changed_at"):
        tax_next = (datetime.fromisoformat(str(a["tax_changed_at"])) + timedelta(days=int(cfg["tax_change_days"]))).isoformat()
    out["alliance"] = {**public_alliance(a, cfg), "treasury_city": _r2(float(a.get("treasury_city") or 0)), "tax_pct": int(a.get("tax_pct") or 0),
                       "tax_next_change": tax_next, "pinned": a.get("pinned") or "", "leader_id": a.get("leader_id"),
                       "frozen": bool(a.get("frozen")), "axp_week": int((a.get("axp_weeks") or {}).get(_week(), 0) or 0),
                       "next_level": nxt}
    out.update(me={"role": m["role"], "deposited_city": _r2(float(m.get("deposited_city") or 0)),
                   "deposit_today": _r2(float((m.get("deposit_days") or {}).get(day, 0) or 0)),
                   "can": {"settings": rank >= RANK["deputy"], "tax": m["role"] == "leader", "requests": rank >= RANK["officer"],
                           "invite": rank >= RANK["officer"], "pin": rank >= RANK["officer"], "roles": m["role"] == "leader",
                           "kick": rank >= RANK["deputy"], "payout": rank >= RANK["deputy"], "level_up": rank >= RANK["deputy"],
                           "transfer": m["role"] == "leader", "disband": m["role"] == "leader"}},
               members=members, log=log, requests=requests)
    return out


async def list_alliances(db, uid: Optional[str], q: str = "", lang: str = "", limit: int = 50) -> Dict:
    cfg = await get_config(db)
    flt: Dict[str, Any] = {"status": "active"}
    q = (q or "").strip()
    if q:
        rx = {"$regex": re.escape(q.lower())}
        flt["$or"] = [{"name_lower": rx}, {"tag_lower": rx}]
    rows = [a async for a in db.alliances.find(flt, {"_id": 0}).sort([("level", -1), ("members_count", -1), ("axp", -1)]).limit(200)]
    lang = (lang or "").lower()[:2]
    rows.sort(key=lambda a: (0 if lang and a.get("lang") == lang else 1, -int(a.get("level") or 1), -int(a.get("members_count") or 0)))
    pending = set()
    if uid:
        pending = set(await db.alliance_requests.distinct("alliance_id", {"user_id": uid, "kind": "request", "status": "pending"}))
    return {"alliances": [{**public_alliance(a, cfg), "requested": a["id"] in pending} for a in rows[:max(1, min(limit, 100))]]}


async def public_view(db, aid: str) -> Dict:
    cfg = await get_config(db)
    a = await alliance(db, aid)
    if not a:
        raise err("not_found", 404)
    rows = [mm async for mm in db.alliance_members.find({"alliance_id": aid}, {"_id": 0, "user_id": 1, "role": 1, "axp_total": 1})]
    users = {u["id"]: u async for u in db.users.find({"id": {"$in": [r["user_id"] for r in rows]}}, {"_id": 0, "id": 1, "username": 1, "avatar": 1})}
    members = sorted([{"username": users.get(r["user_id"], {}).get("username") or "—", "avatar": users.get(r["user_id"], {}).get("avatar"),
                       "role": r["role"], "axp_total": int(r.get("axp_total") or 0)} for r in rows], key=lambda x: (-RANK[x["role"]], -x["axp_total"]))
    return {**public_alliance(a, cfg), "members": members}


async def tags_for(db, user_ids: List[str]) -> Dict[str, str]:
    """{user_id: tag} for showing «[TAG] name» (chat)."""
    if not user_ids:
        return {}
    return {u["id"]: u["alliance_tag"] async for u in db.users.find({"id": {"$in": list(user_ids)}, "alliance_tag": {"$exists": True}},
                                                                      {"_id": 0, "id": 1, "alliance_tag": 1}) if u.get("alliance_tag")}


async def member_ids(db, aid: str) -> List[str]:
    return [m["user_id"] async for m in db.alliance_members.find({"alliance_id": aid}, {"_id": 0, "user_id": 1})]


# ───────────────────────────── router ─────────────────────────────
def create_alliances_router(db, get_current_user, get_current_admin) -> APIRouter:
    root = APIRouter()
    r = APIRouter(prefix="/api/alliances", tags=["alliances"])
    adm = APIRouter(prefix="/api/admin/alliances", tags=["alliances-admin"])

    async def _idx():
        await ensure_indexes(db)

    @r.get("")
    async def r_list(q: str = "", lang: str = "", current_user=Depends(get_current_user)):
        await _idx()
        return await list_alliances(db, current_user.id, q, lang or getattr(current_user, "language", "") or "")

    @r.get("/me")
    async def r_me(current_user=Depends(get_current_user)):
        await _idx()
        return await my_view(db, current_user.id)

    @r.post("")
    async def r_create(body: Dict[str, Any], current_user=Depends(get_current_user)):
        await _idx()
        return await create(db, current_user.id, body)

    @r.get("/{aid}")
    async def r_one(aid: str, current_user=Depends(get_current_user)):
        return await public_view(db, aid)

    @r.post("/{aid}/join")
    async def r_join(aid: str, current_user=Depends(get_current_user)):
        await _idx()
        return await join(db, current_user.id, aid)

    @r.post("/{aid}/cancel-request")
    async def r_cancel(aid: str, current_user=Depends(get_current_user)):
        return await cancel_request(db, current_user.id, aid)

    @r.post("/me/leave")
    async def r_leave(current_user=Depends(get_current_user)):
        return await leave(db, current_user.id)

    @r.post("/me/requests/{rid}/{action}")
    async def r_answer(rid: str, action: str, current_user=Depends(get_current_user)):
        if action not in ("accept", "decline"):
            raise err("bad_action")
        return await answer_request(db, current_user.id, rid, action == "accept")

    @r.post("/invites/{rid}/{action}")
    async def r_invite_answer(rid: str, action: str, current_user=Depends(get_current_user)):
        if action not in ("accept", "decline"):
            raise err("bad_action")
        return await answer_invite(db, current_user.id, rid, action == "accept")

    @r.post("/me/invite")
    async def r_invite(body: Dict[str, Any], current_user=Depends(get_current_user)):
        return await invite(db, current_user.id, body.get("username"))

    @r.post("/me/members/{target}/role")
    async def r_role(target: str, body: Dict[str, Any], current_user=Depends(get_current_user)):
        return await set_role(db, current_user.id, target, str(body.get("role") or ""))

    @r.post("/me/members/{target}/kick")
    async def r_kick(target: str, current_user=Depends(get_current_user)):
        return await kick(db, current_user.id, target)

    @r.post("/me/members/{target}/leader")
    async def r_transfer(target: str, current_user=Depends(get_current_user)):
        return await transfer_leader(db, current_user.id, target)

    @r.put("/me/settings")
    async def r_settings(body: Dict[str, Any], current_user=Depends(get_current_user)):
        return await update_settings(db, current_user.id, body)

    @r.post("/me/deposit")
    async def r_deposit(body: Dict[str, Any], current_user=Depends(get_current_user)):
        return await deposit(db, current_user.id, body.get("amount_city"))

    @r.post("/me/payout")
    async def r_payout(body: Dict[str, Any], current_user=Depends(get_current_user)):
        return await payout(db, current_user.id, str(body.get("user_id") or ""), body.get("amount_city"))

    @r.post("/me/level-up")
    async def r_level(current_user=Depends(get_current_user)):
        return await level_up(db, current_user.id)

    @r.post("/me/disband")
    async def r_disband(current_user=Depends(get_current_user)):
        m, a = await _require_member(db, current_user.id, "leader")
        return await disband(db, a, by=current_user.id)

    # ── admin (Russian only) ──
    @adm.get("/config")
    async def a_cfg(_=Depends(get_current_admin)):
        return await get_config(db)

    @adm.put("/config")
    async def a_cfg_put(body: Dict[str, Any], _=Depends(get_current_admin)):
        try:
            return await save_config(db, body)
        except (ValueError, TypeError) as e:
            raise HTTPException(status_code=400, detail=str(e))

    @adm.get("")
    async def a_list(q: str = "", status: str = "active", _=Depends(get_current_admin)):
        cfg = await get_config(db)
        flt: Dict[str, Any] = {} if status == "all" else {"status": status}
        if q:
            flt["$or"] = [{"name": {"$regex": re.escape(q), "$options": "i"}}, {"tag": {"$regex": re.escape(q), "$options": "i"}}]
        rows = [a async for a in db.alliances.find(flt, {"_id": 0}).sort("created_at", -1).limit(500)]
        leaders = {u["id"]: u.get("username") async for u in db.users.find({"id": {"$in": [a.get("leader_id") for a in rows]}}, {"_id": 0, "id": 1, "username": 1})}
        week = _week()
        return {"alliances": [{**public_alliance(a, cfg), "status": a.get("status"), "treasury_city": _r2(float(a.get("treasury_city") or 0)),
                               "tax_pct": int(a.get("tax_pct") or 0), "frozen": bool(a.get("frozen")), "leader": leaders.get(a.get("leader_id")),
                               "axp_week": int((a.get("axp_weeks") or {}).get(week, 0) or 0)} for a in rows],
                "totals": {"active": await db.alliances.count_documents({"status": "active"}),
                           "members": await db.alliance_members.count_documents({}),
                           "treasury_city": _r2(sum(float(a.get("treasury_city") or 0) for a in rows if a.get("status") == "active"))}}

    @adm.get("/{aid}")
    async def a_one(aid: str, _=Depends(get_current_admin)):
        a = await db.alliances.find_one({"id": aid}, {"_id": 0})
        if not a:
            raise HTTPException(status_code=404)
        v = await public_view(db, aid) if a.get("status") == "active" else {"members": []}
        log = [x async for x in db.alliance_log.find({"alliance_id": aid}, {"_id": 0}).sort("created_at", -1).limit(200)]
        ids = list({x.get("user_id") for x in log if x.get("user_id")})
        names = {u["id"]: u.get("username") async for u in db.users.find({"id": {"$in": ids}}, {"_id": 0, "id": 1, "username": 1})}
        for x in log:
            x["username"] = names.get(x.get("user_id"))
        return {"alliance": a, "members": v.get("members", []), "log": log}

    @adm.post("/{aid}/freeze")
    async def a_freeze(aid: str, body: Dict[str, Any], _=Depends(get_current_admin)):
        await db.alliances.update_one({"id": aid}, {"$set": {"frozen": bool(body.get("frozen", True))}})
        await _log(db, aid, "admin_freeze", None, frozen=bool(body.get("frozen", True)))
        return {"ok": True}

    @adm.post("/{aid}/rename")
    async def a_rename(aid: str, body: Dict[str, Any], _=Depends(get_current_admin)):
        a = await alliance(db, aid)
        if not a:
            raise HTTPException(status_code=404)
        upd: Dict[str, Any] = {}
        if body.get("name"):
            name = re.sub(r"\s+", " ", str(body["name"])).strip()
            if not NAME_RE.match(name):
                raise HTTPException(status_code=400, detail="Название: 3–24 символа")
            upd.update(name=name, name_lower=name.lower())
        if body.get("tag"):
            tag = str(body["tag"]).strip().upper()
            if not TAG_RE.match(tag):
                raise HTTPException(status_code=400, detail="Тег: 3–4 латинские буквы или цифры")
            upd.update(tag=tag, tag_lower=tag.lower())
        try:
            await db.alliances.update_one({"id": aid}, {"$set": upd})
        except Exception:
            raise HTTPException(status_code=409, detail="Такое название или тег уже занято")
        fresh = await alliance(db, aid)
        for uid in await member_ids(db, aid):
            await _sync_user(db, uid, fresh)
        await _log(db, aid, "admin_rename", None, **{k: v for k, v in upd.items() if k in ("name", "tag")})
        return {"ok": True}

    @adm.post("/{aid}/disband")
    async def a_disband(aid: str, _=Depends(get_current_admin)):
        a = await alliance(db, aid)
        if not a:
            raise HTTPException(status_code=404)
        return await disband(db, a, by="admin", reason="admin")

    @adm.post("/maintenance")
    async def a_maint(_=Depends(get_current_admin)):
        return await maintenance(db)

    root.include_router(r)
    root.include_router(adm)
    return root
