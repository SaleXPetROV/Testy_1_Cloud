"""
Alliance notifications — i18n + Telegram bridge.

Single entrypoint: send_alliance_notification(db, user_id, notif_type, params)

It:
  • resolves user's language (default 'en') and telegram_chat_id
  • formats title/message from the i18n table
  • inserts notification into db.notifications (for in-app bell)
  • mirrors to Telegram if chat_id is set (HTML, best-effort, non-blocking)

Notification types live in NOTIF_I18N — same keys across all 8 languages
the frontend supports: en, ru, es, zh, fr, de, ja, ko.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

SUPPORTED_LANGS = ("en", "ru", "es", "zh", "fr", "de", "ja", "ko")
DEFAULT_LANG = "en"


# All alliance-related notification copy.
# {placeholders} are formatted via str.format(**params).
NOTIF_I18N: Dict[str, Dict[str, Dict[str, str]]] = {
    # ----- Auto-cancel because of 3 consecutive violation days -----
    "alliance_auto_cancelled_patron": {
        "en": {
            "title": "Alliance auto-cancelled: {contract_icon} {contract_name}",
            "message": "Vassal {vassal_name} broke contract terms 3 days in a row. The alliance was automatically terminated.",
        },
        "ru": {
            "title": "Альянс авто-расторгнут: {contract_icon} {contract_name}",
            "message": "Вассал {vassal_name} нарушал условия 3 дня подряд. Альянс автоматически расторгнут.",
        },
        "es": {
            "title": "Alianza auto-cancelada: {contract_icon} {contract_name}",
            "message": "El vasallo {vassal_name} incumplió las condiciones 3 días seguidos. La alianza fue cancelada automáticamente.",
        },
        "zh": {
            "title": "联盟自动解除：{contract_icon} {contract_name}",
            "message": "附庸 {vassal_name} 连续 3 天违反条款,联盟已被自动解除。",
        },
        "fr": {
            "title": "Alliance auto-annulée : {contract_icon} {contract_name}",
            "message": "Le vassal {vassal_name} a enfreint les conditions 3 jours d'affilée. L'alliance a été annulée automatiquement.",
        },
        "de": {
            "title": "Allianz automatisch beendet: {contract_icon} {contract_name}",
            "message": "Vasall {vassal_name} hat die Bedingungen 3 Tage in Folge verletzt. Die Allianz wurde automatisch aufgelöst.",
        },
        "ja": {
            "title": "同盟が自動解除: {contract_icon} {contract_name}",
            "message": "従属者 {vassal_name} が3日連続で条件違反。同盟は自動的に解除されました。",
        },
        "ko": {
            "title": "동맹 자동 해지: {contract_icon} {contract_name}",
            "message": "봉신 {vassal_name} 이(가) 3일 연속 조건을 위반했습니다. 동맹이 자동으로 해지되었습니다.",
        },
    },
    "alliance_auto_cancelled_vassal": {
        "en": {
            "title": "Alliance auto-cancelled: {contract_icon} {contract_name}",
            "message": "You violated contract terms 3 days in a row. The alliance was automatically terminated, the patron's buff has been removed.",
        },
        "ru": {
            "title": "Альянс авто-расторгнут: {contract_icon} {contract_name}",
            "message": "Вы нарушали условия 3 дня подряд. Альянс автоматически расторгнут, баф патрона снят.",
        },
        "es": {
            "title": "Alianza auto-cancelada: {contract_icon} {contract_name}",
            "message": "Incumpliste las condiciones 3 días seguidos. La alianza fue cancelada y el buff del patrón se ha eliminado.",
        },
        "zh": {
            "title": "联盟自动解除：{contract_icon} {contract_name}",
            "message": "您连续 3 天违反条款,联盟已自动解除,庇护者增益已移除。",
        },
        "fr": {
            "title": "Alliance auto-annulée : {contract_icon} {contract_name}",
            "message": "Vous avez enfreint les conditions 3 jours d'affilée. L'alliance a été annulée et le bonus du patron retiré.",
        },
        "de": {
            "title": "Allianz automatisch beendet: {contract_icon} {contract_name}",
            "message": "Sie haben die Bedingungen 3 Tage in Folge verletzt. Die Allianz wurde aufgelöst, der Patron-Buff entfernt.",
        },
        "ja": {
            "title": "同盟が自動解除: {contract_icon} {contract_name}",
            "message": "3日連続で条件違反。同盟は自動解除され、パトロンのバフが解除されました。",
        },
        "ko": {
            "title": "동맹 자동 해지: {contract_icon} {contract_name}",
            "message": "3일 연속 조건 위반으로 동맹이 자동 해지되고 패트론 버프가 제거되었습니다.",
        },
    },

    # ----- Violation warning (first/second strike) -----
    "alliance_violation_vassal": {
        "en": {
            "title": "⚠️ Alliance violation: {contract_icon} {contract_name}",
            "message": "Day {streak}/3 of contract violation. After 3 days in a row the alliance will be auto-cancelled. Reason: {reason}",
        },
        "ru": {
            "title": "⚠️ Нарушение альянса: {contract_icon} {contract_name}",
            "message": "День {streak}/3 нарушения. После 3 подряд альянс будет авто-расторгнут. Причина: {reason}",
        },
        "es": {
            "title": "⚠️ Incumplimiento de alianza: {contract_icon} {contract_name}",
            "message": "Día {streak}/3 de incumplimiento. Tras 3 días seguidos la alianza se cancelará automáticamente. Motivo: {reason}",
        },
        "zh": {
            "title": "⚠️ 联盟违约: {contract_icon} {contract_name}",
            "message": "违约第 {streak}/3 天。连续 3 天后将自动解除联盟。原因: {reason}",
        },
        "fr": {
            "title": "⚠️ Violation d'alliance : {contract_icon} {contract_name}",
            "message": "Jour {streak}/3 de violation. Après 3 jours consécutifs l'alliance sera annulée. Motif : {reason}",
        },
        "de": {
            "title": "⚠️ Allianz-Verstoß: {contract_icon} {contract_name}",
            "message": "Verstoß Tag {streak}/3. Nach 3 Tagen in Folge wird die Allianz automatisch aufgelöst. Grund: {reason}",
        },
        "ja": {
            "title": "⚠️ 同盟違反: {contract_icon} {contract_name}",
            "message": "違反 {streak}/3 日目。3 日連続で同盟は自動解除されます。理由: {reason}",
        },
        "ko": {
            "title": "⚠️ 동맹 위반: {contract_icon} {contract_name}",
            "message": "위반 {streak}/3일째. 3일 연속 시 동맹이 자동 해지됩니다. 사유: {reason}",
        },
    },

    # ----- Reasons -----
    "_reason_no_production": {
        "en": "business did not produce any goods this tick",
        "ru": "бизнес не произвёл товаров за тик",
        "es": "el negocio no produjo bienes este tick",
        "zh": "本周期未生产任何资源",
        "fr": "l'entreprise n'a rien produit ce tick",
        "de": "Betrieb hat in diesem Tick nichts produziert",
        "ja": "このティックで生産物がありませんでした",
        "ko": "이번 틱에 생산물이 없습니다",
    },
    "_reason_insufficient_funds_city": {
        "en": "not enough $CITY for the 10% Tax Haven payment",
        "ru": "не хватает $CITY для платежа Налоговой Гавани (10%)",
        "es": "$CITY insuficiente para el pago del 10% del Refugio Fiscal",
        "zh": "$CITY 不足以支付税收天堂 10% 费用",
        "fr": "pas assez de $CITY pour le paiement de 10 % du Paradis fiscal",
        "de": "Nicht genug $CITY für die 10%-Zahlung des Steuerparadieses",
        "ja": "タックスヘイブンの10%支払いに$CITYが不足",
        "ko": "택스 헤이븐 10% 지불을 위한 $CITY 부족",
    },
    "_reason_insufficient_rent": {
        "en": "not enough TON to pay the 100 $CITY daily rent",
        "ru": "не хватает TON для ежедневной ренты 100 $CITY",
        "es": "TON insuficiente para la renta diaria de 100 $CITY",
        "zh": "TON 不足以支付每日 100 $CITY 租金",
        "fr": "pas assez de TON pour le loyer quotidien de 100 $CITY",
        "de": "Nicht genug TON für die tägliche Miete von 100 $CITY",
        "ja": "毎日のレント100 $CITYの支払いにTONが不足",
        "ko": "일일 임대료 100 $CITY 지불을 위한 TON 부족",
    },

    # ----- Patron-side offers paused (hit 25 limit) -----
    "offers_paused_limit": {
        "en": {
            "title": "📛 Offers paused: 25 alliance limit",
            "message": "Your T3 business reached 25 active alliances. All published offers are paused until at least one alliance ends.",
        },
        "ru": {
            "title": "📛 Офферы на паузе: лимит 25 альянсов",
            "message": "Ваш T3-бизнес достиг 25 активных альянсов. Все опубликованные офферы поставлены на паузу, пока хотя бы один альянс не завершится.",
        },
        "es": {
            "title": "📛 Ofertas en pausa: límite de 25 alianzas",
            "message": "Tu negocio T3 alcanzó 25 alianzas activas. Las ofertas publicadas están en pausa hasta que termine al menos una.",
        },
        "zh": {
            "title": "📛 提议暂停：25 个联盟上限",
            "message": "您的 T3 业务已达 25 个活跃联盟。所有已发布提议暂停,直到至少一个联盟结束。",
        },
        "fr": {
            "title": "📛 Offres en pause : limite de 25 alliances",
            "message": "Votre entreprise T3 a atteint 25 alliances actives. Les offres publiées sont en pause jusqu'à la fin d'au moins une alliance.",
        },
        "de": {
            "title": "📛 Angebote pausiert: 25-Allianzen-Limit",
            "message": "Ihr T3-Betrieb hat 25 aktive Allianzen erreicht. Alle veröffentlichten Angebote sind pausiert, bis mindestens eine Allianz endet.",
        },
        "ja": {
            "title": "📛 オファー停止: 25 同盟の上限",
            "message": "T3 ビジネスがアクティブ同盟 25 件に達しました。少なくとも 1 つが終了するまで公開オファーは停止されます。",
        },
        "ko": {
            "title": "📛 제안 일시 중지: 동맹 25개 한도",
            "message": "T3 사업이 활성 동맹 25개에 도달했습니다. 하나 이상이 종료될 때까지 게시된 제안이 중지됩니다.",
        },
    },
}


def _resolve_text(notif_type: str, lang: str, params: Dict[str, Any]) -> Dict[str, str]:
    """Return {'title','message'} for notif_type / lang, with placeholders filled."""
    table = NOTIF_I18N.get(notif_type, {})
    bundle = table.get(lang) or table.get(DEFAULT_LANG) or {"title": notif_type, "message": ""}
    try:
        return {
            "title": bundle["title"].format(**params),
            "message": bundle["message"].format(**params),
        }
    except (KeyError, ValueError, IndexError):
        return {"title": bundle.get("title", notif_type), "message": bundle.get("message", "")}


def _resolve_reason(reason_key: str, lang: str) -> str:
    table = NOTIF_I18N.get(reason_key, {})
    return table.get(lang) or table.get(DEFAULT_LANG) or reason_key


async def send_alliance_notification(
    db,
    user_id: str,
    notif_type: str,
    params: Optional[Dict[str, Any]] = None,
    extra_fields: Optional[Dict[str, Any]] = None,
) -> None:
    """Persist in-app notification and mirror to Telegram (best-effort).

    `params` may include a special key `reason_key` referencing one of the
    `_reason_*` entries above; it will be resolved to localised text and
    placed into `params['reason']` for templating.
    """
    if not user_id:
        return
    params = dict(params or {})

    user = await db.users.find_one(
        {"$or": [{"id": user_id}, {"wallet_address": user_id}]},
        {"_id": 0, "id": 1, "language": 1, "telegram_chat_id": 1},
    )
    if not user:
        return

    lang = (user.get("language") or DEFAULT_LANG).lower()
    if lang not in SUPPORTED_LANGS:
        lang = DEFAULT_LANG

    # Resolve reason placeholder if requested
    reason_key = params.pop("reason_key", None)
    if reason_key:
        params.setdefault("reason", _resolve_reason(reason_key, lang))

    text = _resolve_text(notif_type, lang, params)

    notif = {
        "id": str(uuid.uuid4()),
        "user_id": user.get("id") or user_id,
        "type": notif_type,
        "title": text["title"],
        "message": text["message"],
        "read": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if extra_fields:
        notif.update(extra_fields)

    try:
        await db.notifications.insert_one(notif)
    except Exception as e:
        logger.warning(f"alliance notif insert failed: {e}")

    # Mirror to Telegram (best-effort; HTML-escape minimal entities)
    chat_id = user.get("telegram_chat_id")
    if chat_id:
        try:
            from telegram_notifications import send_telegram_message
            safe_title = (text["title"]
                          .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
            safe_msg = (text["message"]
                        .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
            tg_text = f"<b>{safe_title}</b>\n\n{safe_msg}"
            await send_telegram_message(str(chat_id), tg_text)
        except Exception as e:
            logger.warning(f"alliance telegram mirror failed: {e}")
