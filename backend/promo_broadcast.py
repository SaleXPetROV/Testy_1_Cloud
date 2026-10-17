"""
Referral Rally Telegram broadcasts.

Locale-aware messages, batched to respect Telegram rate limits (25/second).
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

# Telegram Bot API base (override via TELEGRAM_API_BASE to route through a proxy).
TELEGRAM_API_BASE = os.environ.get(
    "TELEGRAM_API_BASE", "https://api.telegram.org"
).rstrip("/")


PROMO_LINK = "https://gramcity.games"

# Image attached to Telegram broadcasts and in-app notifications for the
# Referral Rally (both the initial marketing text and the reminders). The
# default is derived from `WEBAUTHN_ORIGIN` (the same public origin used by
# WebAuthn, e.g. `https://gramcity.games`), since the banner is served as a
# frontend static asset at `/promo/rally-banner.png`. Set `PROMO_BANNER_URL`
# explicitly to an absolute URL to override, or to an empty string to
# disable image attachment entirely.
_PUBLIC_ORIGIN = (os.environ.get("WEBAUTHN_ORIGIN") or "").rstrip("/")
PROMO_BANNER_URL = os.environ.get(
    "PROMO_BANNER_URL",
    f"{_PUBLIC_ORIGIN}/promo/rally-banner.png" if _PUBLIC_ORIGIN else "",
)

# Bot username used to build a deep-link back to the bot's own main menu
# (used by the "На главную" button inside the rally broadcast). If empty we
# fall back to the site URL. Resolved lazily via `getMe`, cached process-wide.
_BOT_USERNAME_CACHE: Optional[str] = None


async def _resolve_bot_username(db=None) -> str:
    """Return the bot's @username so we can build a `t.me/<username>` deep-link
    from the rally broadcast's "На главную" button (which must open the bot's
    main menu, not the website)."""
    global _BOT_USERNAME_CACHE
    if _BOT_USERNAME_CACHE:
        return _BOT_USERNAME_CACHE
    try:
        import os as _os
        import httpx
        token = _os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if not token:
            return ""
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{TELEGRAM_API_BASE}/bot{token}/getMe", timeout=8.0)
            if r.status_code == 200:
                data = r.json()
                uname = (data.get("result") or {}).get("username") or ""
                if uname:
                    _BOT_USERNAME_CACHE = uname
                    return uname
    except Exception as e:
        logger.debug(f"resolve_bot_username failed: {e}")
    return ""


# Fallback languages supported by the app (matches frontend translationsExtra.js)
SUPPORTED_LANGS = ("en", "ru", "es", "zh", "fr", "de", "ja", "ko")


def _get_lang(user_lang: Optional[str]) -> str:
    l = (user_lang or "ru").lower()
    return l if l in SUPPORTED_LANGS else "ru"


def _format_ends_at_display(ends_at_iso: str, lang: str = "ru") -> str:
    """Return `22.07 в 10:00 по МСК` style string in the given language."""
    from promo_service import to_msk
    try:
        ends = to_msk(ends_at_iso)
        # `22.07` — day.month
        dd_mm = f"{ends.day:02d}.{ends.month:02d}"
        hh_mm = ends.strftime("%H:%M")
        by_lang = {
            "ru": f"{dd_mm} в {hh_mm} по МСК",
            "en": f"{dd_mm} at {hh_mm} MSK",
            "es": f"{dd_mm} a las {hh_mm} MSK",
            "zh": f"{dd_mm} {hh_mm} MSK",
            "fr": f"{dd_mm} à {hh_mm} MSK",
            "de": f"{dd_mm} um {hh_mm} MSK",
            "ja": f"{dd_mm} {hh_mm} MSK",
            "ko": f"{dd_mm} {hh_mm} MSK",
        }
        return by_lang.get(lang, by_lang["en"])
    except Exception:
        return "—"


def _reminder_text(campaign: Dict[str, Any], top3: List[Dict[str, Any]], lang: str,
                    is_final_hour: bool = False, header: str = "auto") -> str:
    """Compose the SHORT reminder broadcast — mirrors the in-app modal:
    title, subtitle, prize fund, live top-3 leaders and countdown.

    `is_final_hour=True` prepends an urgency banner ("⚡ Последний час!").
    `header="none"` omits the time-pressure banner entirely (used by the manual
    admin broadcast, which may be sent at any time and must not claim "24h left").
    """
    prizes = campaign.get("config", {}).get("prizes_ton", [100, 50, 20])
    per_active = campaign.get("config", {}).get("per_active_ton", 1.5)
    p1, p2, p3 = (prizes + [0, 0, 0])[:3]
    ends_at = _format_ends_at_display(campaign.get("ends_at", ""), lang)

    medals = ["🥇", "🥈", "🥉"]
    T = {
        "ru": {
            "urgency": "⚡ <b>ПОСЛЕДНИЙ ЧАС АКЦИИ!</b> ⚡",
            "day_before": "⏰ <b>ДО КОНЦА АКЦИИ ОСТАЛОСЬ 24 ЧАСА!</b>",
            "hdr": "🔥 <b>МЕГА-РАЛЛИ РЕФЕРАЛОВ!</b>",
            "sub": f"Приглашай друзей, получай {per_active} TON за каждого активного игрока и забери главный куш!",
            "fund": "🏆 <b>ПРИЗОВОЙ ФОНД ТОП-3:</b>",
            "leaders": "📊 <b>ТЕКУЩИЕ ЛИДЕРЫ:</b>",
            "empty": "— пока никого —",
            "no_active": "К сожалению, на данный момент нет активных рефералов!",
            "left": f"⏱ До фиксации: <b>{ends_at}</b>",
            "refs": "реф.",
        },
        "en": {
            "urgency": "⚡ <b>FINAL HOUR OF THE CAMPAIGN!</b> ⚡",
            "day_before": "⏰ <b>ONLY 24 HOURS LEFT!</b>",
            "hdr": "🔥 <b>REFERRAL MEGA-RALLY!</b>",
            "sub": f"Invite friends, earn {per_active} TON per active player and grab the grand prize!",
            "fund": "🏆 <b>TOP-3 PRIZE POOL:</b>",
            "leaders": "📊 <b>CURRENT LEADERS:</b>",
            "empty": "— nobody yet —",
            "no_active": "Unfortunately, there are no active referrals at the moment!",
            "left": f"⏱ Time until freeze: <b>{ends_at}</b>",
            "refs": "refs",
        },
        "es": {
            "urgency": "⚡ <b>¡ÚLTIMA HORA DE LA CAMPAÑA!</b> ⚡",
            "day_before": "⏰ <b>¡SOLO QUEDAN 24 HORAS!</b>",
            "hdr": "🔥 <b>¡MEGA-RALLY DE REFERIDOS!</b>",
            "sub": f"Invita amigos, gana {per_active} TON por cada jugador activo y llévate el premio mayor.",
            "fund": "🏆 <b>PREMIOS TOP-3:</b>",
            "leaders": "📊 <b>LÍDERES ACTUALES:</b>",
            "empty": "— aún nadie —",
            "no_active": "Lamentablemente, ¡en este momento no hay referidos activos!",
            "left": f"⏱ Tiempo restante: <b>{ends_at}</b>",
            "refs": "refs",
        },
        "zh": {
            "urgency": "⚡ <b>活动最后一小时!</b> ⚡",
            "day_before": "⏰ <b>仅剩 24 小时!</b>",
            "hdr": "🔥 <b>推荐超级大赛!</b>",
            "sub": f"邀请好友,每位活跃玩家获得 {per_active} TON,赢取大奖!",
            "fund": "🏆 <b>前三名奖池:</b>",
            "leaders": "📊 <b>当前领先者:</b>",
            "empty": "— 暂无 —",
            "no_active": "很遗憾,目前还没有活跃的推荐人!",
            "left": f"⏱ 剩余时间: <b>{ends_at}</b>",
            "refs": "人",
        },
        "fr": {
            "urgency": "⚡ <b>DERNIÈRE HEURE DE LA CAMPAGNE !</b> ⚡",
            "day_before": "⏰ <b>PLUS QUE 24 HEURES !</b>",
            "hdr": "🔥 <b>MÉGA-RALLYE DES PARRAINAGES !</b>",
            "sub": f"Invitez vos amis, gagnez {per_active} TON par joueur actif et remportez le gros lot !",
            "fund": "🏆 <b>CAGNOTTE TOP-3 :</b>",
            "leaders": "📊 <b>LEADERS ACTUELS :</b>",
            "empty": "— personne pour l'instant —",
            "no_active": "Malheureusement, il n'y a aucun filleul actif pour le moment !",
            "left": f"⏱ Temps restant : <b>{ends_at}</b>",
            "refs": "réfs",
        },
        "de": {
            "urgency": "⚡ <b>LETZTE STUNDE DER KAMPAGNE!</b> ⚡",
            "day_before": "⏰ <b>NUR NOCH 24 STUNDEN!</b>",
            "hdr": "🔥 <b>MEGA-EMPFEHLUNGS-RALLY!</b>",
            "sub": f"Lade Freunde ein, verdiene {per_active} TON pro aktiven Spieler und hol dir den Hauptgewinn!",
            "fund": "🏆 <b>TOP-3 PREISPOOL:</b>",
            "leaders": "📊 <b>AKTUELLE FÜHRENDE:</b>",
            "empty": "— noch niemand —",
            "no_active": "Leider gibt es im Moment keine aktiven Empfehlungen!",
            "left": f"⏱ Verbleibende Zeit: <b>{ends_at}</b>",
            "refs": "Empf.",
        },
        "ja": {
            "urgency": "⚡ <b>キャンペーン最終 1 時間!</b> ⚡",
            "day_before": "⏰ <b>残り 24 時間!</b>",
            "hdr": "🔥 <b>紹介メガラリー!</b>",
            "sub": f"友達を招待して、アクティブプレイヤー 1 人につき {per_active} TON を獲得!",
            "fund": "🏆 <b>トップ 3 賞金:</b>",
            "leaders": "📊 <b>現在のリーダー:</b>",
            "empty": "— まだ誰もいません —",
            "no_active": "残念ながら、現在アクティブな紹介者はいません!",
            "left": f"⏱ 残り時間: <b>{ends_at}</b>",
            "refs": "紹介",
        },
        "ko": {
            "urgency": "⚡ <b>캠페인 마지막 한 시간!</b> ⚡",
            "day_before": "⏰ <b>24시간 남았습니다!</b>",
            "hdr": "🔥 <b>추천 메가 랠리!</b>",
            "sub": f"친구를 초대하고 활성 플레이어당 {per_active} TON을 획득하세요!",
            "fund": "🏆 <b>TOP-3 상금 풀:</b>",
            "leaders": "📊 <b>현재 리더:</b>",
            "empty": "— 아직 없음 —",
            "no_active": "아쉽게도 현재 활성 추천인이 없습니다!",
            "left": f"⏱ 남은 시간: <b>{ends_at}</b>",
            "refs": "추천",
        },
    }
    tr = T.get(lang, T["en"])

    lines: List[str] = []
    if header != "none":
        if is_final_hour:
            lines.append(tr["urgency"])
        else:
            lines.append(tr["day_before"])
        lines.append("")
    lines.extend([tr["hdr"], "", tr["sub"], "", tr["fund"],
                  f"🥇 1 — <b>{p1} TON</b>",
                  f"🥈 2 — <b>{p2} TON</b>",
                  f"🥉 3 — <b>{p3} TON</b>",
                  "", tr["leaders"]])
    # Only leaders with >=1 ACTIVE referral count. If nobody is active yet
    # we intentionally hide the "0/N total" placeholder rows and show a
    # single localized "no active referrals yet" line instead — the
    # placings on the announcement must reflect real active referrals,
    # not raw invite counts (which look misleading pre-activation).
    active_top = [r for r in (top3 or []) if int(r.get("active", 0) or 0) > 0]
    if not active_top:
        lines.append(tr["no_active"])
    else:
        for i in range(3):
            if i < len(active_top):
                r = active_top[i]
                uname = r.get("username") or "—"
                active = r.get("active", 0)
                total = r.get("total", 0)
                lines.append(f"{medals[i]} @{uname} — {active} / {total} {tr['refs']}")
            else:
                lines.append(f"{medals[i]} —")
    lines.extend(["", tr["left"]])
    return "\n".join(lines)


def _rally_text(campaign: Dict[str, Any], lang: str) -> str:
    """Compose the announcement body in the requested language.

    Uses the long marketing copy that mirrors the in-app announcement.
    Formatted with Telegram HTML (parse_mode=HTML).
    """
    prizes = campaign.get("config", {}).get("prizes_ton", [100, 50, 20])
    per_active = campaign.get("config", {}).get("per_active_ton", 1.5)
    ends_at = _format_ends_at_display(campaign.get("ends_at", ""), lang)
    p1, p2, p3 = (prizes + [0, 0, 0])[:3]

    T = {
        "ru": (
            f"🔥 <b>МЕГА-РАЛЛИ РЕФЕРАЛОВ В TON CITY: ЗАБЕРИ СВОИ TON!</b> 🔥\n\n"
            f"Нашему проекту нужна сильнейшая база предпринимателей. Мы объявляем масштабный недельный спринт с реальными выплатами в TON!\n\n"
            f"Полей на карте всего <b>478</b> и лучшие места разлетаются прямо сейчас. Время заявить о себе и заработать на приглашениях!\n\n"
            f"💰 <b>Условия для КАЖДОГО участника:</b>\n"
            f"За каждого активного реферала (который купит любой бизнес на карте) ты получаешь <b>{per_active} TON</b> прямо на свой баланс! Эти средства будут доступны для мгновенного вывода сразу по окончании акции.\n\n"
            f"🏆 <b>ГЛАВНЫЙ ПРИЗОВОЙ ФОНД ДЛЯ ТОП-РЕФОВОДОВ:</b>\n"
            f"Три лидера, которые приведут больше всего активных участников, разделят между собой дополнительный жирный куш:\n"
            f"🥇 1 место — <b>{p1} TON</b>\n"
            f"🥈 2 место — <b>{p2} TON</b>\n"
            f"🥉 3 место — <b>{p3} TON</b>\n\n"
            f"⏱ <b>Сроки проведения:</b>\n"
            f"Акция стартует прямо сейчас! Общий подсчет активных рефералов и начисление всех заработанных средств (включая призы ТОП-3) произойдет <b>{ends_at}</b>.\n\n"
            f"📈 Таблица лидеров обновляется в игре в реальном времени — следи за своими конкурентами и не дай им обойти тебя в последний момент!"
        ),
        "en": (
            f"🔥 <b>TON CITY REFERRAL MEGA-RALLY: TAKE YOUR TON!</b> 🔥\n\n"
            f"Our project needs the strongest base of entrepreneurs. We are launching a massive one-week sprint with real TON payouts!\n\n"
            f"There are only <b>478</b> plots on the map and the best spots are being taken right now. Time to make a name for yourself and earn on invites!\n\n"
            f"💰 <b>Rules for EVERY participant:</b>\n"
            f"For each active referral (who buys any business on the map) you get <b>{per_active} TON</b> straight to your balance! Funds are available for instant withdrawal right after the campaign ends.\n\n"
            f"🏆 <b>MAIN PRIZE POOL FOR TOP REFERRERS:</b>\n"
            f"Three leaders who bring the most active players will split an additional fat pot:\n"
            f"🥇 1st place — <b>{p1} TON</b>\n"
            f"🥈 2nd place — <b>{p2} TON</b>\n"
            f"🥉 3rd place — <b>{p3} TON</b>\n\n"
            f"⏱ <b>Timeline:</b>\n"
            f"The campaign starts right now! Final count of active referrals and payout of all earned funds (including TOP-3 prizes) will happen on <b>{ends_at}</b>.\n\n"
            f"📈 Leaderboard updates live in-game — watch your competitors and don't let them overtake you at the last moment!"
        ),
        "es": (
            f"🔥 <b>MEGA-RALLY DE REFERIDOS EN TON CITY: ¡RECLAMA TUS TON!</b> 🔥\n\n"
            f"Nuestro proyecto necesita la base más fuerte de emprendedores. ¡Lanzamos un sprint semanal masivo con pagos reales en TON!\n\n"
            f"En el mapa solo hay <b>478</b> parcelas y los mejores lugares se están agotando ahora mismo. ¡Es hora de destacar y ganar con las invitaciones!\n\n"
            f"💰 <b>Condiciones para CADA participante:</b>\n"
            f"Por cada referido activo (que compre cualquier negocio en el mapa) recibes <b>{per_active} TON</b> directamente a tu saldo. Estos fondos estarán disponibles para retiro instantáneo al terminar la campaña.\n\n"
            f"🏆 <b>FONDO PRINCIPAL PARA LOS TOP-REFERIDORES:</b>\n"
            f"Los tres líderes que traigan más participantes activos se repartirán un bote adicional:\n"
            f"🥇 1º lugar — <b>{p1} TON</b>\n"
            f"🥈 2º lugar — <b>{p2} TON</b>\n"
            f"🥉 3º lugar — <b>{p3} TON</b>\n\n"
            f"⏱ <b>Fechas:</b>\n"
            f"¡La campaña empieza ahora mismo! El conteo final y el pago de todos los fondos ganados (incluidos los premios TOP-3) se realizará el <b>{ends_at}</b>.\n\n"
            f"📈 La tabla de líderes se actualiza en vivo en el juego — vigila a tus competidores y no dejes que te superen en el último momento!"
        ),
        "zh": (
            f"🔥 <b>TON CITY 推荐大赛:领取你的 TON!</b> 🔥\n\n"
            f"我们的项目需要最强大的企业家基础。我们宣布一场为期一周、真实 TON 支付的大型冲刺!\n\n"
            f"地图上只有 <b>478</b> 块地,最好的位置正在被抢占。展现自己、通过邀请赚钱的时候到了!\n\n"
            f"💰 <b>每位参与者的条件:</b>\n"
            f"每邀请一位活跃推荐人(购买地图上任何业务),你将获得 <b>{per_active} TON</b> 直接到账户余额!活动结束后可立即提现。\n\n"
            f"🏆 <b>顶级推荐人主要奖池:</b>\n"
            f"带来最多活跃参与者的三位领先者将瓜分额外的丰厚奖金:\n"
            f"🥇 第 1 名 — <b>{p1} TON</b>\n"
            f"🥈 第 2 名 — <b>{p2} TON</b>\n"
            f"🥉 第 3 名 — <b>{p3} TON</b>\n\n"
            f"⏱ <b>时间:</b>\n"
            f"活动即刻开始!活跃推荐人的最终统计和所有奖金发放(包括前 3 名奖励)将于 <b>{ends_at}</b> 进行。\n\n"
            f"📈 排行榜在游戏内实时更新 — 密切关注对手,别让他们在最后一刻超越你!"
        ),
        "fr": (
            f"🔥 <b>MÉGA-RALLYE DES PARRAINAGES DANS TON CITY : RÉCUPÈRE TES TON !</b> 🔥\n\n"
            f"Notre projet a besoin de la meilleure base d'entrepreneurs. Nous lançons un grand sprint hebdomadaire avec de vrais paiements en TON !\n\n"
            f"Il n'y a que <b>478</b> parcelles sur la carte et les meilleures places partent en ce moment. Le moment est venu de te faire un nom et de gagner grâce aux invitations !\n\n"
            f"💰 <b>Conditions pour CHAQUE participant :</b>\n"
            f"Pour chaque filleul actif (qui achète n'importe quel business sur la carte), tu reçois <b>{per_active} TON</b> directement sur ton solde ! Ces fonds seront disponibles pour un retrait instantané dès la fin de la campagne.\n\n"
            f"🏆 <b>CAGNOTTE PRINCIPALE POUR LES TOP-PARRAINEURS :</b>\n"
            f"Les trois leaders qui apporteront le plus de participants actifs se partageront un pactole supplémentaire :\n"
            f"🥇 1ère place — <b>{p1} TON</b>\n"
            f"🥈 2ème place — <b>{p2} TON</b>\n"
            f"🥉 3ème place — <b>{p3} TON</b>\n\n"
            f"⏱ <b>Dates :</b>\n"
            f"La campagne démarre maintenant ! Le décompte final et le versement de tous les gains (y compris les prix TOP-3) auront lieu le <b>{ends_at}</b>.\n\n"
            f"📈 Le classement se met à jour en temps réel dans le jeu — surveille tes concurrents et ne les laisse pas te doubler au dernier moment !"
        ),
        "de": (
            f"🔥 <b>EMPFEHLUNGS-MEGA-RALLY IN TON CITY: HOL DIR DEINE TON!</b> 🔥\n\n"
            f"Unser Projekt braucht die stärkste Unternehmer-Basis. Wir starten einen massiven wöchentlichen Sprint mit echten TON-Auszahlungen!\n\n"
            f"Es gibt nur <b>478</b> Grundstücke auf der Karte und die besten Plätze werden jetzt gerade vergeben. Zeit, sich einen Namen zu machen und mit Einladungen zu verdienen!\n\n"
            f"💰 <b>Bedingungen für JEDEN Teilnehmer:</b>\n"
            f"Für jede aktive Empfehlung (die ein Business auf der Karte kauft) erhältst du <b>{per_active} TON</b> direkt auf dein Guthaben! Diese Mittel sind sofort nach Kampagnenende abhebbar.\n\n"
            f"🏆 <b>HAUPT-PREISPOOL FÜR TOP-EMPFEHLER:</b>\n"
            f"Die drei besten Empfehler teilen sich einen zusätzlichen Bonus-Pot:\n"
            f"🥇 1. Platz — <b>{p1} TON</b>\n"
            f"🥈 2. Platz — <b>{p2} TON</b>\n"
            f"🥉 3. Platz — <b>{p3} TON</b>\n\n"
            f"⏱ <b>Zeitplan:</b>\n"
            f"Die Kampagne startet jetzt! Die endgültige Auszählung und Auszahlung aller Gewinne (inkl. TOP-3-Preise) erfolgt am <b>{ends_at}</b>.\n\n"
            f"📈 Die Rangliste wird live im Spiel aktualisiert — behalte deine Konkurrenten im Auge und lass dich nicht überholen!"
        ),
        "ja": (
            f"🔥 <b>TON CITY 紹介メガラリー:あなたの TON を獲得しよう!</b> 🔥\n\n"
            f"プロジェクトには最強の起業家ベースが必要です。実際の TON 支払いを伴う 1 週間の大規模スプリントを開催します!\n\n"
            f"マップには <b>478</b> の区画しかなく、最高の場所は今すぐ埋まっています。名を上げて、招待で稼ぐ時です!\n\n"
            f"💰 <b>参加者全員の条件:</b>\n"
            f"アクティブな紹介 1 人につき(マップ上のビジネスを購入)、<b>{per_active} TON</b> が残高に直接入金されます!キャンペーン終了後すぐに引き出し可能です。\n\n"
            f"🏆 <b>トップ紹介者のメイン賞金プール:</b>\n"
            f"最も多くのアクティブ参加者を招待した 3 人のリーダーが追加の賞金を分け合います:\n"
            f"🥇 1 位 — <b>{p1} TON</b>\n"
            f"🥈 2 位 — <b>{p2} TON</b>\n"
            f"🥉 3 位 — <b>{p3} TON</b>\n\n"
            f"⏱ <b>期間:</b>\n"
            f"キャンペーンは今すぐ開始!最終集計と全報酬(TOP-3 を含む)の支払いは <b>{ends_at}</b> に行われます。\n\n"
            f"📈 リーダーボードはゲーム内でリアルタイム更新 — 競争相手を監視し、最後の瞬間に追い越されないように!"
        ),
        "ko": (
            f"🔥 <b>TON CITY 추천 메가 랠리:당신의 TON을 가져가세요!</b> 🔥\n\n"
            f"우리 프로젝트는 가장 강력한 기업가 기반이 필요합니다. 실제 TON 지급이 있는 대규모 1주 스프린트를 시작합니다!\n\n"
            f"지도에는 <b>478</b>개의 부지만 있으며 가장 좋은 자리들이 지금 사라지고 있습니다. 이름을 알리고 초대로 돈을 벌 시간입니다!\n\n"
            f"💰 <b>모든 참가자를 위한 조건:</b>\n"
            f"각 활성 추천인(지도의 아무 비즈니스를 구매)당 <b>{per_active} TON</b>이 잔액에 직접 지급됩니다! 캠페인 종료 후 즉시 출금 가능합니다.\n\n"
            f"🏆 <b>TOP 추천자를 위한 메인 상금 풀:</b>\n"
            f"가장 많은 활성 참가자를 데려온 세 명의 리더가 추가 상금을 나눠 갖습니다:\n"
            f"🥇 1위 — <b>{p1} TON</b>\n"
            f"🥈 2위 — <b>{p2} TON</b>\n"
            f"🥉 3위 — <b>{p3} TON</b>\n\n"
            f"⏱ <b>일정:</b>\n"
            f"캠페인은 지금 시작됩니다! 최종 집계와 모든 상금(TOP-3 포함) 지급은 <b>{ends_at}</b>에 진행됩니다.\n\n"
            f"📈 리더보드는 게임 내에서 실시간으로 업데이트됩니다 — 경쟁자를 주시하고 마지막 순간에 추월당하지 마세요!"
        ),
    }
    return T.get(lang, T["en"])


def _finished_text(campaign: Dict[str, Any], lang: str) -> str:
    winners = campaign.get("winners", [])
    T = {
        "ru": {"hdr": "🏁 <b>АКЦИЯ ЗАВЕРШЕНА!</b>", "results": "🏆 <b>ПОБЕДИТЕЛИ:</b>",
               "thanks": "Спасибо всем за участие!", "refs": "реф."},
        "en": {"hdr": "🏁 <b>CAMPAIGN FINISHED!</b>", "results": "🏆 <b>WINNERS:</b>",
               "thanks": "Thanks to everyone who participated!", "refs": "refs"},
    }
    tr = T.get(lang, T["en"])
    lines = [tr["hdr"], "", tr["results"]]
    medals = ["🥇", "🥈", "🥉"]
    for w in winners:
        m = medals[w.get("rank", 1) - 1] if w.get("rank", 1) <= 3 else "•"
        lines.append(f"{m} @{w.get('username', '—')} — {w.get('active_count', 0)} / {w.get('total_count', 0)} {tr['refs']} ({w.get('prize_ton', 0)} TON)")
    lines.extend(["", tr["thanks"], "", f'<a href="{PROMO_LINK}">GRAM CITY</a>'])
    return "\n".join(lines)


def _build_rally_keyboard(is_linked: bool, lang: str = "ru",
                          bot_home_url: str = "") -> Dict[str, Any]:
    """Build inline keyboard for the rally broadcast.

    Linked chat (associated with a GRAM CITY account):
      • "Пригласить друзей"  (URL — telegram share dialog with referral link)
      • "GRAM CITY"          (URL — deep link to the web app)
      • "На главную"         (URL — deep link back to the BOT's main menu, i.e.
                              `https://telegram.me/<bot_username>?start=menu`,
                              NOT the website)

    Unlinked chat (bot subscriber only):
      • "Получить ссылку"    (callback → same content as "Как привязать")
      • "На главную"         (URL — deep link back to the BOT's main menu)
    """
    labels = {
        "ru": {
            "invite": "🎁 Пригласить друзей",
            "gramcity": "🏙 GRAM CITY",
            "home": "🏠 На главную",
            "getlink": "🔗 Получить ссылку",
        },
        "en": {
            "invite": "🎁 Invite friends",
            "gramcity": "🏙 GRAM CITY",
            "home": "🏠 Home",
            "getlink": "🔗 Get link",
        },
        "es": {
            "invite": "🎁 Invitar amigos",
            "gramcity": "🏙 GRAM CITY",
            "home": "🏠 Inicio",
            "getlink": "🔗 Obtener enlace",
        },
        "zh": {
            "invite": "🎁 邀请好友",
            "gramcity": "🏙 GRAM CITY",
            "home": "🏠 主页",
            "getlink": "🔗 获取链接",
        },
        "fr": {
            "invite": "🎁 Inviter des amis",
            "gramcity": "🏙 GRAM CITY",
            "home": "🏠 Accueil",
            "getlink": "🔗 Obtenir le lien",
        },
        "de": {
            "invite": "🎁 Freunde einladen",
            "gramcity": "🏙 GRAM CITY",
            "home": "🏠 Startseite",
            "getlink": "🔗 Link erhalten",
        },
        "ja": {
            "invite": "🎁 友達を招待",
            "gramcity": "🏙 GRAM CITY",
            "home": "🏠 ホーム",
            "getlink": "🔗 リンクを取得",
        },
        "ko": {
            "invite": "🎁 친구 초대",
            "gramcity": "🏙 GRAM CITY",
            "home": "🏠 홈",
            "getlink": "🔗 링크 받기",
        },
    }
    L = labels.get(lang, labels["en"])

    # Share dialog with the referral link
    invite_body = {
        "ru": f"🔥 Присоединяйся к акции GRAM CITY «Мега-ралли рефералов» и забирай призы!\n\n{PROMO_LINK}",
        "en": f"🔥 Join the GRAM CITY Referral Mega-Rally and grab the prizes!\n\n{PROMO_LINK}",
    }.get(lang, f"🔥 Join the GRAM CITY Referral Mega-Rally!\n\n{PROMO_LINK}")
    invite_url = (
        f"https://telegram.me/share/url?url={PROMO_LINK}"
        f"&text={_urlencode(invite_body)}"
    )

    if is_linked:
        return {
            "inline_keyboard": [
                [{"text": L["invite"], "url": invite_url}],
                [{"text": L["gramcity"], "url": PROMO_LINK}],
                [{"text": L["home"], "callback_data": "back_to_menu"}],
            ]
        }
    return {
        "inline_keyboard": [
            [{"text": L["getlink"], "callback_data": "how_to_link"}],
            [{"text": L["home"], "callback_data": "back_to_menu"}],
        ]
    }


def _urlencode(s: str) -> str:
    import urllib.parse
    return urllib.parse.quote(s, safe="")


async def _create_in_app_announcement(db, campaign: Dict[str, Any]) -> int:
    """Insert an in-app 'promo_announcement' notification for EVERY registered
    user (whether their Telegram is linked or not). Uses `i18n_key` so the
    NotificationCenter renders the localized title/body based on the user's
    language selection at read time.

    Returns the number of users notified.
    """
    from promo_service import now_msk

    prizes = campaign.get("config", {}).get("prizes_ton", [100, 50, 20])
    per_active = campaign.get("config", {}).get("per_active_ton", 1.5)
    p1, p2, p3 = (prizes + [0, 0, 0])[:3]

    # Provide the exact same variables the front-end template will interpolate
    i18n_vars = {
        "per_active": per_active,
        "p1": p1,
        "p2": p2,
        "p3": p3,
        "ends_at_ru": _format_ends_at_display(campaign.get("ends_at", ""), "ru"),
        "ends_at_en": _format_ends_at_display(campaign.get("ends_at", ""), "en"),
    }
    banner_url = PROMO_BANNER_URL or None

    cursor = db.users.find({}, {"_id": 0, "id": 1})
    now_iso = now_msk().isoformat()
    docs: List[Dict[str, Any]] = []
    async for u in cursor:
        uid = u.get("id")
        if not uid:
            continue
        docs.append({
            "id": str(uuid.uuid4()),
            "user_id": uid,
            "type": "promo_announcement",
            "priority": "info",
            "title": "🔥 МЕГА-РАЛЛИ РЕФЕРАЛОВ В TON CITY: ЗАБЕРИ СВОИ TON!",
            "message": "",  # Rendered via i18n_key on the client
            "payload": {
                "i18n_key": "promoAnnouncement",
                "i18n_vars": i18n_vars,
                "campaign_id": campaign.get("id"),
                "image_url": banner_url,
            },
            "read": False,
            "created_at": now_iso,
        })
        # Bulk-insert in batches to avoid memory spikes on large user bases
        if len(docs) >= 500:
            try:
                await db.notifications.insert_many(docs, ordered=False)
            except Exception as e:
                logger.warning(f"notifications insert_many batch failed: {e}")
            docs = []
    if docs:
        try:
            await db.notifications.insert_many(docs, ordered=False)
        except Exception as e:
            logger.warning(f"notifications insert_many final batch failed: {e}")

    total = await db.notifications.count_documents({
        "type": "promo_announcement",
        "payload.campaign_id": campaign.get("id"),
    })
    logger.info(f"📣 In-app rally announcement inserted for {total} users")
    return total


async def maybe_insert_active_promo_notif_for_user(db, user_id: str) -> bool:
    """If there is an active referral rally campaign right now, insert a single
    `promo_announcement` in-app notification for the given user (idempotent —
    silently skips if the user already has one for that campaign).

    Called at registration time so users who sign up mid-campaign still get the
    in-app announcement in their notification center. Uses `i18n_key` so the
    NotificationCenter renders the message in the user's chosen language.
    """
    try:
        from promo_service import get_active_campaign, now_msk
    except Exception:
        return False
    try:
        campaign = await get_active_campaign(db)
        if not campaign:
            return False

        campaign_id = campaign.get("id")
        exists = await db.notifications.find_one({
            "user_id": user_id,
            "type": "promo_announcement",
            "payload.campaign_id": campaign_id,
        }, {"_id": 1})
        if exists:
            return False

        prizes = campaign.get("config", {}).get("prizes_ton", [100, 50, 20])
        per_active = campaign.get("config", {}).get("per_active_ton", 1.5)
        p1, p2, p3 = (prizes + [0, 0, 0])[:3]
        i18n_vars = {
            "per_active": per_active,
            "p1": p1,
            "p2": p2,
            "p3": p3,
            "ends_at_ru": _format_ends_at_display(campaign.get("ends_at", ""), "ru"),
            "ends_at_en": _format_ends_at_display(campaign.get("ends_at", ""), "en"),
        }
        await db.notifications.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "type": "promo_announcement",
            "priority": "info",
            "title": "🔥 МЕГА-РАЛЛИ РЕФЕРАЛОВ В TON CITY: ЗАБЕРИ СВОИ TON!",
            "message": "",
            "payload": {
                "i18n_key": "promoAnnouncement",
                "i18n_vars": i18n_vars,
                "campaign_id": campaign_id,
                "image_url": PROMO_BANNER_URL or None,
            },
            "read": False,
            "created_at": now_msk().isoformat(),
        })
        return True
    except Exception as e:
        logger.debug(f"maybe_insert_active_promo_notif_for_user failed: {e}")
        return False


async def broadcast_active_rally(db, campaign: Dict[str, Any]) -> int:
    """Broadcast the INITIAL long announcement to EVERY bot subscriber (from
    `telegram_mappings`), plus insert an in-app notification for EVERY
    registered site user. Chat_ids linked to a project account get
    "Пригласить друзей / GRAM CITY / На главную" buttons; unlinked
    chat_ids get "Получить ссылку / На главную" buttons.

    The Telegram message is sent with the promo banner image attached (via
    `sendPhoto`). Falls back to `sendMessage` if the image cannot be sent.

    Returns the number of Telegram messages actually sent.
    """
    from telegram_notifications import send_telegram_photo

    # 1) In-app notification for every site user (regardless of TG link)
    try:
        await _create_in_app_announcement(db, campaign)
    except Exception as e:
        logger.error(f"in-app announcement insert failed: {e}", exc_info=True)

    # 2) Build a set of linked chat_ids for O(1) lookup
    linked_chat_ids: set = set()
    async for u in db.users.find(
        {"telegram_chat_id": {"$exists": True, "$nin": [None, ""]}},
        {"_id": 0, "telegram_chat_id": 1},
    ):
        cid = u.get("telegram_chat_id")
        if cid:
            linked_chat_ids.add(str(cid))

    # 3) Build the bot deep-link once (for the "На главную" button)
    bot_username = await _resolve_bot_username(db)
    bot_home_url = f"https://telegram.me/{bot_username}?start=menu" if bot_username else PROMO_LINK

    # 4) Iterate over ALL bot subscribers (telegram_mappings)
    subs_cur = db.telegram_mappings.find(
        {},
        {"_id": 0, "chat_id": 1, "language": 1},
    )
    subs = await subs_cur.to_list(100000)
    sent = 0
    for i, sub in enumerate(subs):
        chat_id = str(sub.get("chat_id") or "")
        if not chat_id:
            continue
        lang = _get_lang(sub.get("language"))
        text = _rally_text(campaign, lang)
        is_linked = chat_id in linked_chat_ids
        reply_markup = _build_rally_keyboard(is_linked, lang, bot_home_url)
        try:
            from telegram_notifications import send_telegram_message
            # Single message with image preview above the text (Bot API 7.0+).
            # This avoids the 1024-char caption cap of `sendPhoto` and keeps
            # the whole marketing copy in ONE Telegram message.
            ok = await send_telegram_message(
                chat_id, text,
                reply_markup=reply_markup,
                preview_url=PROMO_BANNER_URL or None,
            )
            if ok:
                sent += 1
        except Exception as e:
            logger.debug(f"TG send failed for {chat_id}: {e}")
        # Rate limit: 25 per second
        if (i + 1) % 25 == 0:
            await asyncio.sleep(1.0)
    logger.info(f"📣 Rally TG broadcast complete: sent={sent}/{len(subs)} (linked={len(linked_chat_ids)})")
    return sent


async def broadcast_rally_reminder(db, campaign: Dict[str, Any],
                                    is_final_hour: bool = False) -> int:
    """Send a SHORT reminder push (24h-before or last-hour) to every bot
    subscriber with the LIVE leaderboard. Also inserts a mirroring in-app
    notification with the same short text for every registered user.

    `is_final_hour=True` produces an urgency-styled variant.

    Returns the number of Telegram messages actually sent.
    """
    from telegram_notifications import send_telegram_photo, send_telegram_message
    from promo_service import compute_referrals_leaderboard, now_msk, current_leaderboard_sort

    # Live top-3 leaders at broadcast time (by total before presale, active after)
    top3, _ = await compute_referrals_leaderboard(
        db, sort=current_leaderboard_sort(), offset=0, limit=3)

    # 1) In-app reminder for every registered user (short text with vars).
    try:
        prizes = campaign.get("config", {}).get("prizes_ton", [100, 50, 20])
        per_active = campaign.get("config", {}).get("per_active_ton", 1.5)
        p1, p2, p3 = (prizes + [0, 0, 0])[:3]
        i18n_vars = {
            "per_active": per_active,
            "p1": p1, "p2": p2, "p3": p3,
            "ends_at_ru": _format_ends_at_display(campaign.get("ends_at", ""), "ru"),
            "ends_at_en": _format_ends_at_display(campaign.get("ends_at", ""), "en"),
            "top3": [
                {"username": r.get("username"), "active": r.get("active", 0),
                 "total": r.get("total", 0)}
                for r in top3
            ],
        }
        i18n_key = "promoReminderFinalHour" if is_final_hour else "promoReminderDayBefore"
        now_iso = now_msk().isoformat()
        docs: List[Dict[str, Any]] = []
        async for u in db.users.find({}, {"_id": 0, "id": 1}):
            uid = u.get("id")
            if not uid:
                continue
            docs.append({
                "id": str(uuid.uuid4()),
                "user_id": uid,
                "type": "promo_announcement",
                "priority": "warning" if is_final_hour else "info",
                "title": "⚡ Последний час акции!" if is_final_hour else "⏰ 24 часа до конца акции",
                "message": "",
                "payload": {
                    "i18n_key": i18n_key,
                    "i18n_vars": i18n_vars,
                    "campaign_id": campaign.get("id"),
                    "reminder_stage": "final_hour" if is_final_hour else "day_before",
                    "image_url": PROMO_BANNER_URL or None,
                },
                "read": False,
                "created_at": now_iso,
            })
            if len(docs) >= 500:
                try:
                    await db.notifications.insert_many(docs, ordered=False)
                except Exception as e:
                    logger.warning(f"reminder notifications insert_many batch failed: {e}")
                docs = []
        if docs:
            try:
                await db.notifications.insert_many(docs, ordered=False)
            except Exception as e:
                logger.warning(f"reminder notifications insert_many final failed: {e}")
    except Exception as e:
        logger.error(f"reminder in-app insert failed: {e}", exc_info=True)

    # 2) Linked chat_ids
    linked_chat_ids: set = set()
    async for u in db.users.find(
        {"telegram_chat_id": {"$exists": True, "$nin": [None, ""]}},
        {"_id": 0, "telegram_chat_id": 1},
    ):
        cid = u.get("telegram_chat_id")
        if cid:
            linked_chat_ids.add(str(cid))

    bot_username = await _resolve_bot_username(db)
    bot_home_url = f"https://telegram.me/{bot_username}?start=menu" if bot_username else PROMO_LINK

    # 3) Send reminder to every bot subscriber
    subs = await db.telegram_mappings.find(
        {}, {"_id": 0, "chat_id": 1, "language": 1},
    ).to_list(100000)
    sent = 0
    for i, sub in enumerate(subs):
        chat_id = str(sub.get("chat_id") or "")
        if not chat_id:
            continue
        lang = _get_lang(sub.get("language"))
        text = _reminder_text(campaign, top3, lang, is_final_hour=is_final_hour)
        is_linked = chat_id in linked_chat_ids
        reply_markup = _build_rally_keyboard(is_linked, lang, bot_home_url)
        try:
            if PROMO_BANNER_URL and len(text) <= 1024:
                ok = await send_telegram_photo(
                    chat_id, PROMO_BANNER_URL, caption=text,
                    reply_markup=reply_markup,
                )
            else:
                ok = await send_telegram_message(chat_id, text, reply_markup=reply_markup)
            if ok:
                sent += 1
        except Exception as e:
            logger.debug(f"reminder TG send failed for {chat_id}: {e}")
        if (i + 1) % 25 == 0:
            await asyncio.sleep(1.0)
    stage = "final_hour" if is_final_hour else "day_before"
    logger.info(f"📣 Rally reminder ({stage}) sent={sent}/{len(subs)}")
    # Mark reminder as sent so it never re-fires for the same campaign
    try:
        await db.promo_campaigns.update_one(
            {"id": campaign.get("id")},
            {"$set": {f"reminders_sent.{stage}": now_msk().isoformat()}},
        )
    except Exception as e:
        logger.debug(f"marking reminder {stage} sent failed: {e}")
    return sent


async def broadcast_finished_rally(db, campaign: Dict[str, Any]) -> int:
    """Send the 'campaign finished' message to all users. Also DM each winner
    with a personalized 'you won X TON, admin will pay' message."""
    from telegram_notifications import send_telegram_message

    users_cur = db.users.find(
        {"telegram_chat_id": {"$exists": True, "$nin": [None, ""]}},
        {"_id": 0, "id": 1, "telegram_chat_id": 1, "language": 1},
    )
    users = await users_cur.to_list(50000)
    sent = 0
    for i, u in enumerate(users):
        chat_id = u.get("telegram_chat_id")
        if not chat_id:
            continue
        lang = _get_lang(u.get("language"))
        text = _finished_text(campaign, lang)
        try:
            ok = await send_telegram_message(str(chat_id), text)
            if ok:
                sent += 1
        except Exception:
            pass
        if (i + 1) % 25 == 0:
            await asyncio.sleep(1.0)

    # Personal DMs to winners
    winners = campaign.get("winners", [])
    for w in winners:
        uid = w.get("user_id")
        if not uid:
            continue
        udoc = await db.users.find_one(
            {"id": uid},
            {"_id": 0, "telegram_chat_id": 1, "language": 1},
        )
        if not udoc or not udoc.get("telegram_chat_id"):
            continue
        lang = _get_lang(udoc.get("language"))
        rank = w.get("rank", 0)
        prize = w.get("prize_ton", 0)
        if lang == "ru":
            text = (
                f"🎉 <b>Поздравляем!</b>\n\n"
                f"Вы заняли <b>{rank} место</b> в акции «Мега-ралли рефералов»!\n"
                f"Приз: <b>{prize} TON</b>\n\n"
                f"Администратор скоро свяжется с вами для выплаты.\n\n"
                f'<a href="{PROMO_LINK}">Открыть GRAM CITY</a>'
            )
        else:
            text = (
                f"🎉 <b>Congratulations!</b>\n\n"
                f"You took <b>place #{rank}</b> in the Referral Mega-Rally!\n"
                f"Prize: <b>{prize} TON</b>\n\n"
                f"The admin will contact you soon for the payout.\n\n"
                f'<a href="{PROMO_LINK}">Open GRAM CITY</a>'
            )
        try:
            await send_telegram_message(str(udoc["telegram_chat_id"]), text)
        except Exception:
            pass

    return sent


async def broadcast_rally_daily(db, campaign: Dict[str, Any]) -> int:
    """Manual admin broadcast ("Разослать") — sends a SHORT reminder to every
    bot subscriber with the LIVE top-3 (ordered by total invited before the
    presale, by active after) AND inserts a fresh in-app notification (same
    short text + banner image) for every registered site user, so the
    site-side notification center mirrors what went out on Telegram.

    Reuses the reminder text/keyboard; does NOT touch the 24h/final-hour
    `reminders_sent` flags.
    """
    from telegram_notifications import send_telegram_photo, send_telegram_message
    from promo_service import compute_referrals_leaderboard, now_msk, msk_today_str, current_leaderboard_sort

    today = msk_today_str()

    # Live top-3 (presale-aware sort)
    top3, _ = await compute_referrals_leaderboard(
        db, sort=current_leaderboard_sort(), offset=0, limit=3)

    # 1) In-app notification for every registered site user (same short text
    #    + banner as the Telegram broadcast). Uses `i18n_key` so the
    #    NotificationCenter renders it in each user's chosen language.
    try:
        prizes = campaign.get("config", {}).get("prizes_ton", [100, 50, 20])
        per_active = campaign.get("config", {}).get("per_active_ton", 1.5)
        p1, p2, p3 = (prizes + [0, 0, 0])[:3]
        i18n_vars = {
            "per_active": per_active,
            "p1": p1, "p2": p2, "p3": p3,
            "ends_at_ru": _format_ends_at_display(campaign.get("ends_at", ""), "ru"),
            "ends_at_en": _format_ends_at_display(campaign.get("ends_at", ""), "en"),
            "top3": [
                {"username": r.get("username"), "active": r.get("active", 0),
                 "total": r.get("total", 0)}
                for r in top3
            ],
        }
        now_iso = now_msk().isoformat()
        docs: List[Dict[str, Any]] = []
        async for u in db.users.find({}, {"_id": 0, "id": 1}):
            uid = u.get("id")
            if not uid:
                continue
            docs.append({
                "id": str(uuid.uuid4()),
                "user_id": uid,
                "type": "promo_announcement",
                "priority": "info",
                "title": "🔥 МЕГА-РАЛЛИ РЕФЕРАЛОВ: следите за таблицей!",
                "message": "",
                "payload": {
                    "i18n_key": "promoBroadcast",
                    "i18n_vars": i18n_vars,
                    "campaign_id": campaign.get("id"),
                    "broadcast_stage": "manual",
                    "image_url": PROMO_BANNER_URL or None,
                },
                "read": False,
                "created_at": now_iso,
            })
            if len(docs) >= 500:
                try:
                    await db.notifications.insert_many(docs, ordered=False)
                except Exception as e:
                    logger.warning(f"daily broadcast notifications insert_many batch failed: {e}")
                docs = []
        if docs:
            try:
                await db.notifications.insert_many(docs, ordered=False)
            except Exception as e:
                logger.warning(f"daily broadcast notifications insert_many final failed: {e}")

        # 1b) Push a real-time WebSocket event so users currently on the site
        #     see the bell shake / hear the notification sound immediately,
        #     without waiting for the 30s polling refresh.
        try:
            from core.websocket import manager as _ws_manager
            payload_ws = {
                "type": "notification_new",
                "notification": {
                    "type": "promo_announcement",
                    "priority": "info",
                    "title": "🔥 МЕГА-РАЛЛИ РЕФЕРАЛОВ: следите за таблицей!",
                    "payload": {
                        "i18n_key": "promoBroadcast",
                        "campaign_id": campaign.get("id"),
                    },
                },
            }
            await _ws_manager.broadcast(payload_ws)
        except Exception as _e:
            logger.debug(f"daily broadcast WS notify failed: {_e}")
    except Exception as e:
        logger.error(f"daily broadcast in-app insert failed: {e}", exc_info=True)

    linked_chat_ids: set = set()
    async for u in db.users.find(
        {"telegram_chat_id": {"$exists": True, "$nin": [None, ""]}},
        {"_id": 0, "telegram_chat_id": 1},
    ):
        cid = u.get("telegram_chat_id")
        if cid:
            linked_chat_ids.add(str(cid))

    bot_username = await _resolve_bot_username(db)
    bot_home_url = f"https://telegram.me/{bot_username}?start=menu" if bot_username else PROMO_LINK

    subs = await db.telegram_mappings.find(
        {}, {"_id": 0, "chat_id": 1, "language": 1},
    ).to_list(100000)
    sent = 0
    for i, sub in enumerate(subs):
        chat_id = str(sub.get("chat_id") or "")
        if not chat_id:
            continue
        lang = _get_lang(sub.get("language"))
        text = _reminder_text(campaign, top3, lang, is_final_hour=False, header="none")
        is_linked = chat_id in linked_chat_ids
        reply_markup = _build_rally_keyboard(is_linked, lang, bot_home_url)
        try:
            if PROMO_BANNER_URL and len(text) <= 1024:
                ok = await send_telegram_photo(
                    chat_id, PROMO_BANNER_URL, caption=text, reply_markup=reply_markup,
                )
            else:
                ok = await send_telegram_message(chat_id, text, reply_markup=reply_markup)
            if ok:
                sent += 1
        except Exception as e:
            logger.debug(f"daily rally TG send failed for {chat_id}: {e}")
        if (i + 1) % 25 == 0:
            await asyncio.sleep(1.0)

    logger.info(f"📣 Rally broadcast sent={sent}/{len(subs)} (date={today})")
    return sent


async def build_daily_broadcast_preview(db, campaign: Dict[str, Any], lang: str = "ru") -> Dict[str, Any]:
    """Build a preview of the broadcast the admin is about to send: the exact
    RU (default) message text with the live top-3 (presale-aware sort), plus the
    top-3 list and the number of bot subscribers that will receive it."""
    from promo_service import compute_referrals_leaderboard, current_leaderboard_sort

    sort = current_leaderboard_sort()
    top3, _ = await compute_referrals_leaderboard(db, sort=sort, offset=0, limit=3)
    text = _reminder_text(campaign, top3, _get_lang(lang), is_final_hour=False, header="none")
    subscriber_count = await db.telegram_mappings.count_documents({})
    return {
        "text": text,
        "sort": sort,
        "top3": [
            {"rank": i + 1, "username": r.get("username"),
             "active": r.get("active", 0), "total": r.get("total", 0)}
            for i, r in enumerate(top3)
        ],
        "subscriber_count": subscriber_count,
        "banner_url": PROMO_BANNER_URL or None,
    }
