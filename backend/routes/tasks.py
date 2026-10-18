"""
GRAM City — Tasks ("Задания") module
====================================
User-facing task board + admin CRUD + daily-login streak reward.

Task action types:
  • subscribe_channel / join_chat  — verified by the Telegram bot (getChatMember)
  • launch_app / visit_link / social_follow — trust-based (open link → verify)
  • referral_invite — completed once the user's referral_count >= required
  • ad_tiktok — user submits a TikTok video link (≤3), admin approves/rejects

Rewards are paid in $CITY. $CITY == TON * 1000, and the game stores the
balance as `balance_ton`, so reward_city is credited as balance_ton += reward/1000.
"""
import uuid
import logging
import re
import httpx
from datetime import datetime, timezone, date, timedelta
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


async def _fetch_tiktok_stats(url: str) -> dict:
    """Fetch TikTok video stats (views/likes) via the free tikwm.com API (no key)."""
    try:
        async with httpx.AsyncClient(timeout=25, headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True) as client:
            r = await client.get("https://www.tikwm.com/api/", params={"url": url, "hd": 0})
            j = r.json()
        if not isinstance(j, dict) or j.get("code") != 0:
            return {"ok": False, "error": (isinstance(j, dict) and j.get("msg")) or "fetch failed"}
        d = j.get("data") or {}
        return {
            "ok": True,
            "views": int(d.get("play_count") or 0),
            "likes": int(d.get("digg_count") or 0),
            "comments": int(d.get("comment_count") or 0),
            "shares": int(d.get("share_count") or 0),
            "author": (d.get("author") or {}).get("unique_id"),
            "title": d.get("title"),
        }
    except Exception as e:
        logger.warning(f"tiktok stats fetch failed: {e}")
        return {"ok": False, "error": str(e)}


def _fmt_num(v) -> str:
    """Показать число без лишних дробей: 3.0 → «3», 3.5 → «3.5»."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if f == int(f):
        return str(int(f))
    return (f"{f:.2f}").rstrip("0").rstrip(".")


def _effective_ad_payout(sub: dict, task: dict) -> int:
    """Amount to credit for an ad submission: manual override > views-based > base reward."""
    if sub.get("payout_override") is not None:
        return max(0, int(sub["payout_override"]))
    if sub.get("payout_city") is not None:
        return max(0, int(sub["payout_city"]))
    return max(0, int((task or {}).get("reward_city", 0) or 0))

async def credit_task_reward_bonus(db, uid: str, reward_city: float, reason: str, tx_type: str = "task_reward") -> None:
    """Every task / daily-login reward goes to the BONUS balance.

    bonus_balance is spent in the game first and can NOT be withdrawn, so task
    rewards cannot be farmed into withdrawals with multi-accounts. (They used to
    be credited to balance_ton, the withdrawable balance.)
    """
    try:
        reward_city = float(reward_city or 0)
    except (TypeError, ValueError):
        return
    if reward_city <= 0 or not uid:
        return
    tax = 0.0
    try:                                          # the alliance tax (0 without an alliance) goes to its treasury
        import alliances as _al
        tax = await _al.take_tax(db, uid, reward_city, tx_type)
    except Exception:
        tax = 0.0
    ton = (reward_city - tax) / 1000.0
    # legacy docs may store bonus_balance as null — $inc would fail on it
    await db.users.update_one({"id": uid, "bonus_balance": None}, {"$set": {"bonus_balance": 0.0}})
    await db.users.update_one({"id": uid}, {"$inc": {"bonus_balance": ton}})
    try:
        now = datetime.now(timezone.utc).isoformat()
        await db.transactions.insert_one({
            "id": str(uuid.uuid4()), "tx_type": tx_type, "type": tx_type, "user_id": uid,
            "amount": ton, "amount_ton": ton, "reward_city": reward_city, "balance": "bonus", "alliance_tax_city": tax,
            "description": f"{reason}: +{reward_city:g} $CITY (bonus)" + (f", alliance tax {tax:g}" if tax else ""), "status": "completed",
            "created_at": now, "completed_at": now,
        })
    except Exception as e:
        logger.warning(f"task reward tx log failed: {e}")


def task_category(task: dict) -> str:
    """'partner' for partner quests (checked through the partner's API), else 'system'."""
    if task.get("action_type") == "partner_quest" and (task.get("quest_kind") or "local") == "partner":
        return "partner"
    return "system"


BOT_VERIFIED_TYPES = {"subscribe_channel", "join_chat"}
TRUST_TYPES = {"launch_app", "visit_link", "social_follow"}
REFERRAL_TYPES = {"referral_invite", "referral_active"}
BOOST_TYPES = {"tg_channel_boost"}
STORY_TYPES = {"repost_story"}
# Partner / local quests: admin-defined "do a sequence of actions" tasks.
#   • quest_kind == "partner": verified against an external partner API URL.
#   • quest_kind == "local":  trust-based, completed on "Verify".
# Rewards can mix $CITY coins + warehouse resources + skins.
QUEST_TYPES = {"partner_quest"}
ALL_ACTION_TYPES = BOT_VERIFIED_TYPES | TRUST_TYPES | REFERRAL_TYPES | BOOST_TYPES | STORY_TYPES | QUEST_TYPES | {"ad_tiktok"}

# Repost-story delayed verification window (spec: 23 hours).
STORY_CHECK_HOURS = 23

DEFAULT_DAILY_REWARDS = [5, 10, 20, 35, 50, 75, 150]

# Daily-reward activity gate: user must buy AND sell resources today to claim.
DAILY_BUY_REQUIRED = 30
DAILY_SELL_REQUIRED = 95
MAX_AD_SUBMISSIONS = 3

SUPPORTED_LANGS = ["en", "ru", "es", "zh", "fr", "de", "ja", "ko", "id"]

# ── Localized user-facing messages (9 languages) ─────────────────────────────
TASK_MSG = {
    "link_telegram": {
        "en": "Link your Telegram account to complete this task.",
        "ru": "Привяжите Telegram-аккаунт, чтобы выполнить это задание.",
        "es": "Vincula tu cuenta de Telegram para completar esta tarea.",
        "zh": "请绑定您的 Telegram 账户以完成此任务。",
        "fr": "Liez votre compte Telegram pour accomplir cette tâche.",
        "de": "Verknüpfe dein Telegram-Konto, um diese Aufgabe abzuschließen.",
        "ja": "このタスクを完了するにはTelegramアカウントを連携してください。",
        "ko": "이 작업을 완료하려면 텔레그램 계정을 연결하세요.",
        "id": "Tautkan akun Telegram Anda untuk menyelesaikan tugas ini.",
    },
    "completed": {
        "en": "Task completed! Reward: +{reward} $CITY",
        "ru": "Задание выполнено! Награда: +{reward} $CITY",
        "es": "¡Tarea completada! Recompensa: +{reward} $CITY",
        "zh": "任务完成！奖励：+{reward} $CITY",
        "fr": "Tâche terminée ! Récompense : +{reward} $CITY",
        "de": "Aufgabe abgeschlossen! Belohnung: +{reward} $CITY",
        "ja": "タスク完了！報酬：+{reward} $CITY",
        "ko": "작업 완료! 보상: +{reward} $CITY",
        "id": "Tugas selesai! Hadiah: +{reward} $CITY",
    },
    "failed": {
        "en": "You have not completed this task yet. Please try again.",
        "ru": "Вы ещё не выполнили это задание. Попробуйте снова.",
        "es": "Aún no has completado esta tarea. Inténtalo de nuevo.",
        "zh": "您尚未完成此任务，请重试。",
        "fr": "Vous n'avez pas encore accompli cette tâche. Réessayez.",
        "de": "Du hast diese Aufgabe noch nicht abgeschlossen. Bitte versuche es erneut.",
        "ja": "このタスクはまだ完了していません。もう一度お試しください。",
        "ko": "아직 이 작업을 완료하지 않았습니다. 다시 시도하세요.",
        "id": "Anda belum menyelesaikan tugas ini. Silakan coba lagi.",
    },
    "partner_incomplete": {
        "en": "Quest conditions are not met yet. Make sure you completed all the required steps in the partner project, then try again.",
        "ru": "Условия квеста ещё не выполнены. Убедитесь, что вы выполнили все требуемые действия в проекте партнёра, и попробуйте снова.",
        "es": "Aún no se cumplen las condiciones de la misión. Asegúrate de haber completado todos los pasos requeridos en el proyecto del socio e inténtalo de nuevo.",
        "zh": "任务条件尚未满足。请确认您已在合作伙伴项目中完成所有要求的步骤，然后重试。",
        "fr": "Les conditions de la quête ne sont pas encore remplies. Assurez-vous d'avoir effectué toutes les étapes requises dans le projet partenaire, puis réessayez.",
        "de": "Die Quest-Bedingungen sind noch nicht erfüllt. Stelle sicher, dass du alle erforderlichen Schritte im Partnerprojekt abgeschlossen hast, und versuche es erneut.",
        "ja": "クエストの条件がまだ満たされていません。パートナープロジェクトで必要な手順をすべて完了したことを確認してから、もう一度お試しください。",
        "ko": "퀘스트 조건이 아직 충족되지 않았습니다. 파트너 프로젝트에서 필요한 모든 단계를 완료했는지 확인한 후 다시 시도하세요.",
        "id": "Syarat misi belum terpenuhi. Pastikan Anda telah menyelesaikan semua langkah yang diperlukan di proyek mitra, lalu coba lagi.",
    },
    "partner_progress": {
        "en": "Progress: {have} of {need}. Keep going and check again.",
        "ru": "Прогресс: {have} из {need}. Продолжайте и проверьте снова.",
        "es": "Progreso: {have} de {need}. Continúa y vuelve a comprobar.",
        "zh": "进度：{have}/{need}。继续努力后再检查。",
        "fr": "Progression : {have} sur {need}. Continuez et vérifiez à nouveau.",
        "de": "Fortschritt: {have} von {need}. Mach weiter und prüfe erneut.",
        "ja": "進捗：{need}中{have}。続けてからもう一度確認してください。",
        "ko": "진행: {need} 중 {have}. 계속한 후 다시 확인하세요.",
        "id": "Progres: {have} dari {need}. Lanjutkan dan periksa lagi.",
    },
    "quest_reward_unavailable": {
        "en": "Could not reach the partner service. Please try again in a moment.",        "ru": "Не удалось связаться с сервисом партнёра. Попробуйте ещё раз через минуту.",
        "es": "No se pudo contactar con el servicio del socio. Inténtalo de nuevo en un momento.",
        "zh": "无法连接到合作伙伴服务，请稍后再试。",
        "fr": "Impossible de joindre le service partenaire. Réessayez dans un instant.",
        "de": "Der Partnerdienst konnte nicht erreicht werden. Bitte versuche es gleich noch einmal.",
        "ja": "パートナーサービスに接続できませんでした。しばらくしてからもう一度お試しください。",
        "ko": "파트너 서비스에 연결할 수 없습니다. 잠시 후 다시 시도하세요.",
        "id": "Tidak dapat menghubungi layanan mitra. Silakan coba lagi sebentar lagi.",
    },
    "quest_completed": {
        "en": "Quest completed! Reward credited.",
        "ru": "Квест успешно выполнен! Награда зачислена.",
        "es": "¡Misión completada! Recompensa acreditada.",
        "zh": "任务完成！奖励已发放。",
        "fr": "Quête terminée ! Récompense créditée.",
        "de": "Quest abgeschlossen! Belohnung gutgeschrieben.",
        "ja": "クエスト完了！報酬が付与されました。",
        "ko": "퀘스트 완료! 보상이 지급되었습니다.",
        "id": "Misi selesai! Hadiah telah dikreditkan.",
    },
    "referral_progress": {
        "en": "Invited {have} of {need} friends. Keep going!",
        "ru": "Приглашено {have} из {need} друзей. Продолжайте!",
        "es": "Has invitado a {have} de {need} amigos. ¡Sigue así!",
        "zh": "已邀请 {have}/{need} 位好友，继续加油！",
        "fr": "{have} sur {need} amis invités. Continuez !",
        "de": "{have} von {need} Freunden eingeladen. Weiter so!",
        "ja": "{need}人中{have}人を招待しました。その調子！",
        "ko": "{need}명 중 {have}명 초대함. 계속하세요!",
        "id": "Mengundang {have} dari {need} teman. Lanjutkan!",
    },
    "referral_active_progress": {
        "en": "Invited {have} of {need} active friends. Keep going!",
        "ru": "Приглашено {have} из {need} активных друзей. Продолжайте!",
        "es": "Has invitado a {have} de {need} amigos activos. ¡Sigue así!",
        "zh": "已邀请 {have}/{need} 位活跃好友，继续加油！",
        "fr": "{have} sur {need} amis actifs invités. Continuez !",
        "de": "{have} von {need} aktiven Freunden eingeladen. Weiter so!",
        "ja": "{need}人中{have}人のアクティブな友達を招待しました。その調子！",
        "ko": "{need}명 중 {have}명의 활성 친구를 초대함. 계속하세요!",
        "id": "Mengundang {have} dari {need} teman aktif. Lanjutkan!",
    },
    "ad_approved_link": {
        "en": "Task completed via your link: {url} — Reward: +{reward} $CITY",
        "ru": "Задание выполнено по ссылке: {url} — Награда: +{reward} $CITY",
        "es": "Tarea completada con tu enlace: {url} — Recompensa: +{reward} $CITY",
        "zh": "已通过您的链接完成任务：{url} — 奖励：+{reward} $CITY",
        "fr": "Tâche accomplie via votre lien : {url} — Récompense : +{reward} $CITY",
        "de": "Aufgabe über deinen Link abgeschlossen: {url} — Belohnung: +{reward} $CITY",
        "ja": "あなたのリンクでタスク完了：{url} — 報酬：+{reward} $CITY",
        "ko": "링크로 작업 완료: {url} — 보상: +{reward} $CITY",
        "id": "Tugas selesai melalui tautan Anda: {url} — Hadiah: +{reward} $CITY",
    },
    "ad_submitted": {
        "en": "Your video link was submitted for review.",
        "ru": "Ваша ссылка на видео отправлена на проверку.",
        "es": "Tu enlace de video se envió para revisión.",
        "zh": "您的视频链接已提交审核。",
        "fr": "Votre lien vidéo a été soumis pour examen.",
        "de": "Dein Videolink wurde zur Prüfung eingereicht.",
        "ja": "動画リンクを審査のために送信しました。",
        "ko": "동영상 링크가 검토를 위해 제출되었습니다.",
        "id": "Tautan video Anda dikirim untuk ditinjau.",
    },
    "ad_approved": {
        "en": "Your video was approved! Reward: +{reward} $CITY",
        "ru": "Ваше видео одобрено! Награда: +{reward} $CITY",
        "es": "¡Tu video fue aprobado! Recompensa: +{reward} $CITY",
        "zh": "您的视频已通过！奖励：+{reward} $CITY",
        "fr": "Votre vidéo a été approuvée ! Récompense : +{reward} $CITY",
        "de": "Dein Video wurde genehmigt! Belohnung: +{reward} $CITY",
        "ja": "動画が承認されました！報酬：+{reward} $CITY",
        "ko": "동영상이 승인되었습니다! 보상: +{reward} $CITY",
        "id": "Video Anda disetujui! Hadiah: +{reward} $CITY",
    },
    "ad_rejected": {
        "en": "Your video submission was rejected. You may submit another link.",
        "ru": "Ваше видео отклонено. Вы можете отправить другую ссылку.",
        "es": "Tu video fue rechazado. Puedes enviar otro enlace.",
        "zh": "您的视频被拒绝。您可以提交另一个链接。",
        "fr": "Votre vidéo a été refusée. Vous pouvez soumettre un autre lien.",
        "de": "Dein Video wurde abgelehnt. Du kannst einen anderen Link einreichen.",
        "ja": "動画が却下されました。別のリンクを送信できます。",
        "ko": "동영상이 거부되었습니다. 다른 링크를 제출할 수 있습니다.",
        "id": "Video Anda ditolak. Anda dapat mengirim tautan lain.",
    },
    "daily_claimed": {
        "en": "Daily reward claimed: +{reward} $CITY (day {day})",
        "ru": "Ежедневная награда получена: +{reward} $CITY (день {day})",
        "es": "Recompensa diaria reclamada: +{reward} $CITY (día {day})",
        "zh": "已领取每日奖励：+{reward} $CITY（第 {day} 天）",
        "fr": "Récompense quotidienne réclamée : +{reward} $CITY (jour {day})",
        "de": "Tägliche Belohnung erhalten: +{reward} $CITY (Tag {day})",
        "ja": "デイリー報酬を受け取りました：+{reward} $CITY（{day}日目）",
        "ko": "일일 보상 수령: +{reward} $CITY ({day}일차)",
        "id": "Hadiah harian diklaim: +{reward} $CITY (hari {day})",
    },
    "daily_activity_required": {
        "en": "Complete daily activity first: buy {bought}/{buy_req} and sell {sold}/{sell_req} units of resources.",
        "ru": "Сначала выполните дневную активность: купите {bought}/{buy_req} и продайте {sold}/{sell_req} ед. ресурсов.",
        "es": "Completa la actividad diaria primero: compra {bought}/{buy_req} y vende {sold}/{sell_req} unidades de recursos.",
        "zh": "请先完成每日活动：购买 {bought}/{buy_req}，出售 {sold}/{sell_req} 单位资源。",
        "fr": "Terminez d'abord l'activité quotidienne : achetez {bought}/{buy_req} et vendez {sold}/{sell_req} unités de ressources.",
        "de": "Erledige zuerst die Tagesaktivität: kaufe {bought}/{buy_req} und verkaufe {sold}/{sell_req} Ressourceneinheiten.",
        "ja": "先にデイリー活動を完了してください：資源を{bought}/{buy_req}購入、{sold}/{sell_req}売却。",
        "ko": "먼저 일일 활동을 완료하세요: 자원 {bought}/{buy_req} 구매, {sold}/{sell_req} 판매.",
        "id": "Selesaikan aktivitas harian dulu: beli {bought}/{buy_req} dan jual {sold}/{sell_req} unit sumber daya.",
    },
    "verify_unavailable": {
        "en": "Subscription check is temporarily unavailable. Please try again in a moment.",
        "ru": "Проверка подписки временно недоступна. Попробуйте ещё раз чуть позже.",
        "es": "La verificación de suscripción no está disponible temporalmente. Inténtalo de nuevo en un momento.",
        "zh": "订阅检查暂时不可用，请稍后再试。",
        "fr": "La vérification de l'abonnement est temporairement indisponible. Réessayez dans un instant.",
        "de": "Die Abo-Prüfung ist vorübergehend nicht verfügbar. Bitte versuche es gleich erneut.",
        "ja": "購読確認は一時的に利用できません。しばらくしてからもう一度お試しください。",
        "ko": "구독 확인을 일시적으로 사용할 수 없습니다. 잠시 후 다시 시도하세요.",
        "id": "Pemeriksaan langganan tidak tersedia sementara. Silakan coba lagi sebentar lagi.",
    },
    "boost_success": {
        "en": "Task completed, reward credited!",
        "ru": "Задание выполнено, награда начислена!",
        "es": "¡Tarea completada, recompensa acreditada!",
        "zh": "任务完成，奖励已发放！",
        "fr": "Tâche terminée, récompense créditée !",
        "de": "Aufgabe abgeschlossen, Belohnung gutgeschrieben!",
        "ja": "タスク完了、報酬が付与されました！",
        "ko": "작업 완료, 보상이 지급되었습니다!",
        "id": "Tugas selesai, hadiah dikreditkan!",
    },
    "boost_not_found": {
        "en": "Boost not found. Please boost the channel and try again.",
        "ru": "Голос не найден. Пожалуйста, сбустите канал и попробуйте снова.",
        "es": "No se encontró el boost. Impulsa el canal e inténtalo de nuevo.",
        "zh": "未找到助力。请为频道助力后再试。",
        "fr": "Boost introuvable. Veuillez booster la chaîne et réessayer.",
        "de": "Boost nicht gefunden. Bitte booste den Kanal und versuche es erneut.",
        "ja": "ブーストが見つかりません。チャンネルをブーストしてもう一度お試しください。",
        "ko": "부스트를 찾을 수 없습니다. 채널을 부스트한 후 다시 시도하세요.",
        "id": "Boost tidak ditemukan. Silakan boost channel dan coba lagi.",
    },
    "boost_channel_unset": {
        "en": "The channel is not configured. Set it in the admin “Promo” section.",
        "ru": "Канал не настроен. Укажите его в разделе «Промо» в админке.",
        "es": "El canal no está configurado. Configúralo en la sección «Promo» del panel.",
        "zh": "尚未配置频道。请在管理后台“推广”部分设置。",
        "fr": "La chaîne n'est pas configurée. Définissez-la dans la section « Promo ».",
        "de": "Der Kanal ist nicht konfiguriert. Lege ihn im Admin-Bereich „Promo“ fest.",
        "ja": "チャンネルが未設定です。管理画面の「プロモ」で設定してください。",
        "ko": "채널이 설정되지 않았습니다. 관리자 ‘프로모’ 섹션에서 설정하세요.",
        "id": "Channel belum dikonfigurasi. Atur di bagian “Promo” admin.",
    },
    "boost_bot_not_admin": {
        "en": "Verification is unavailable: the bot must be an administrator of the channel.",
        "ru": "Проверка недоступна: бот должен быть администратором канала.",
        "es": "La verificación no está disponible: el bot debe ser administrador del canal.",
        "zh": "无法验证：机器人必须是该频道的管理员。",
        "fr": "Vérification indisponible : le bot doit être administrateur de la chaîne.",
        "de": "Überprüfung nicht verfügbar: Der Bot muss Administrator des Kanals sein.",
        "ja": "確認できません：ボットはチャンネルの管理者である必要があります。",
        "ko": "확인 불가: 봇이 채널의 관리자여야 합니다.",
        "id": "Verifikasi tidak tersedia: bot harus menjadi administrator channel.",
    },
    "boost_rate_limited": {
        "en": "Too many requests. Please try again in a moment.",
        "ru": "Слишком много запросов. Попробуйте ещё раз через мгновение.",
        "es": "Demasiadas solicitudes. Inténtalo de nuevo en un momento.",
        "zh": "请求过多，请稍后再试。",
        "fr": "Trop de requêtes. Réessayez dans un instant.",
        "de": "Zu viele Anfragen. Bitte versuche es gleich erneut.",
        "ja": "リクエストが多すぎます。しばらくしてからお試しください。",
        "ko": "요청이 너무 많습니다. 잠시 후 다시 시도하세요.",
        "id": "Terlalu banyak permintaan. Silakan coba lagi sebentar lagi.",
    },
    "story_check_started": {
        "en": "Verification started. Come back in {hours}h to claim your reward.",
        "ru": "Проверка запущена. Вернитесь через {hours} ч, чтобы забрать награду.",
        "es": "Verificación iniciada. Vuelve en {hours}h para reclamar tu recompensa.",
        "zh": "验证已开始。请在 {hours} 小时后回来领取奖励。",
        "fr": "Vérification lancée. Revenez dans {hours}h pour récupérer votre récompense.",
        "de": "Überprüfung gestartet. Komm in {hours} Std. zurück, um deine Belohnung abzuholen.",
        "ja": "確認を開始しました。{hours}時間後に報酬を受け取りに来てください。",
        "ko": "확인이 시작되었습니다. {hours}시간 후에 보상을 받으러 오세요.",
        "id": "Verifikasi dimulai. Kembali dalam {hours} jam untuk mengklaim hadiah.",
    },
    "story_not_ready": {
        "en": "The reward is not available yet. Please wait until the timer ends.",
        "ru": "Награда пока недоступна. Дождитесь окончания таймера.",
        "es": "La recompensa aún no está disponible. Espera a que termine el temporizador.",
        "zh": "奖励尚不可领取，请等待倒计时结束。",
        "fr": "La récompense n'est pas encore disponible. Attendez la fin du minuteur.",
        "de": "Die Belohnung ist noch nicht verfügbar. Warte, bis der Timer endet.",
        "ja": "報酬はまだ受け取れません。タイマー終了までお待ちください。",
        "ko": "보상을 아직 받을 수 없습니다. 타이머가 끝날 때까지 기다리세요.",
        "id": "Hadiah belum tersedia. Tunggu hingga penghitung waktu selesai.",
    },
}


def _msg(lang: str, key: str, **fmt) -> str:
    entry = TASK_MSG.get(key, {})
    l = (str(lang or "en")).lower()[:2]
    if l not in SUPPORTED_LANGS:
        l = "en"
    template = entry.get(l) or entry.get("en") or key
    try:
        return template.format(**fmt) if fmt else template
    except Exception:
        return template


def _clean_task(t: dict) -> dict:
    t = {k: v for k, v in (t or {}).items() if k != "_id"}
    return t


def _user_tg_id(user_doc: dict) -> Optional[str]:
    for k in ("telegram_id", "telegram_user_id", "telegram_chat_id"):
        v = user_doc.get(k)
        if v:
            return str(v)
    return None


def _substitute_url_placeholders(url: str, *, tg_id=None, internal_id=None, ref_id=None) -> str:
    """Replace {placeholder} tokens in a partner URL with real values.

    Partners embed the player's Telegram id directly in the URL, e.g.
      https://api.fc.gamepat.org/.../check?telegram_id={telegram_id}
      https://fishingeng.cryptocrazytoken.ru/api/?...&user={tg_id}&id=1
    We substitute those tokens (case-insensitive) so the request carries the
    real id. Unknown tokens are left untouched."""
    if not url or "{" not in url:
        return url
    from urllib.parse import quote
    tg = quote(str(tg_id)) if tg_id not in (None, "") else ""
    iid = quote(str(internal_id)) if internal_id not in (None, "") else ""
    ref = quote(str(ref_id)) if ref_id not in (None, "") else ""
    mapping = {
        "telegram_id": tg, "telegramid": tg, "tg_id": tg, "tgid": tg,
        "chat_id": tg, "chatid": tg, "user_id": tg, "userid": tg,
        "user": tg, "id": tg,
        "internal_user_id": iid, "internal_id": iid, "internalid": iid,
        "ref_id": ref, "refid": ref, "ref": ref,
    }

    def repl(m):
        key = m.group(1).strip().lower()
        return mapping.get(key, m.group(0))

    return re.sub(r"\{([^{}]+)\}", repl, url)


def _auto_completed_path(body) -> Optional[str]:
    """Auto-detect a boolean "completed" flag in a partner response when the
    admin didn't specify one. Checks the top level and one level under `data`
    (covers iTerra's {"data": {"completed": ...}} and GamePat's {"completed": ...})."""
    if isinstance(body, dict):
        if "completed" in body:
            return "completed"
        d = body.get("data")
        if isinstance(d, dict) and "completed" in d:
            return "data.completed"
    return None


# ── Request models ───────────────────────────────────────────────────────────
class TaskCreate(BaseModel):
    title: str
    # Reward is OPTIONAL. When omitted (None), the task grants no $CITY coins
    # and the amount is hidden on the task card.
    reward_city: Optional[int] = Field(default=None, ge=0)
    action_type: str
    # Quest-only: require a linked Telegram account before completion is allowed.
    require_telegram: Optional[bool] = None
    photo: Optional[str] = None
    icon: Optional[str] = None
    icon_url: Optional[str] = None
    channel_url: Optional[str] = None
    channel_id: Optional[str] = None
    target_url: Optional[str] = None
    required_referrals: Optional[int] = None
    views_rate: Optional[float] = None
    chat_id: Optional[str] = None
    boost_url: Optional[str] = None
    # ── Partner / local quest fields ─────────────────────────────────────────
    quest_kind: Optional[str] = None          # 'partner' | 'local'
    partner_url: Optional[str] = None         # partner API endpoint (partner quest)
    partner_ref_id: Optional[str] = None      # your partner/referral id
    partner_method: Optional[str] = None      # 'GET' | 'POST' (default GET)
    partner_api_key: Optional[str] = None     # sent as `x-api-key` header (partner quest)
    partner_user_param: Optional[str] = None  # query param name for the Telegram id (default user_id)
    partner_check_field: Optional[str] = None  # dot-path in JSON response to check (e.g. 'data.tradeVolume')
    partner_check_min: Optional[float] = None  # minimum numeric value required for the quest to count
    partner_completed_field: Optional[str] = None  # dot-path to a boolean "done" flag (e.g. 'completed')
    instructions: Optional[str] = None        # free-text steps shown to the user
    reward_description: Optional[str] = None   # free-text describing the reward (shown next to the skin)
    reward_resources: Optional[Dict[str, float]] = None  # {resource_type: amount}
    reward_skins: Optional[List[Dict[str, Any]]] = None  # [{id, name, image?}]  (id = skin group_key)
    reward_funds_amount: Optional[float] = None           # extra $CITY funds reward
    reward_funds_target: Optional[str] = None             # 'bonus' | 'real'
    # Partner quest visibility: when True (default) the task is shown to ALL
    # users. When False the partner's OWN referrals (users who came in via this
    # partner's ref link) do NOT see the task — everyone else still does.
    show_to_referrals: Optional[bool] = None


class DailyRewardsUpdate(BaseModel):
    rewards: List[int]


class ReorderPayload(BaseModel):
    ids: List[str]


class TestPartnerRequest(BaseModel):
    partner_url: str
    partner_method: Optional[str] = "GET"
    partner_api_key: Optional[str] = None
    partner_user_param: Optional[str] = None      # e.g. 'telegram_id' or 'chatId'
    partner_ref_id: Optional[str] = None
    partner_check_field: Optional[str] = None
    partner_check_min: Optional[float] = None
    partner_completed_field: Optional[str] = None
    test_user_id: str                             # telegram id / chatId to probe with


class ActiveToggle(BaseModel):
    active: bool


class AdSubmit(BaseModel):
    url: str


class PayoutUpdate(BaseModel):
    amount: int = Field(..., ge=0)


async def process_expired_story_tasks(db) -> int:
    """Scheduler job: auto-credit `repost_story` rewards once the 23h timer has
    elapsed — fully server-side, no user action required.

    Handles both `pending_check` and `ready_to_claim` (the status endpoint may
    promote a doc to ready_to_claim on read) so no timer can slip through.
    Uses an atomic status flip to guarantee each reward is credited once, even
    across multiple scheduler ticks / workers. Returns the number credited."""
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    credited = 0
    cursor = db.user_task_status.find({
        "status": {"$in": ["pending_check", "ready_to_claim"]},
        "reward_claimed": {"$ne": True},
        "check_available_at": {"$lte": now_iso},
    })
    async for st in cursor:
        uid = st.get("user_id")
        tid = st.get("task_id")
        if not uid or not tid:
            continue
        # Atomic claim: only ONE tick may flip this doc to completed.
        res = await db.user_task_status.update_one(
            {"user_id": uid, "task_id": tid,
             "status": {"$in": ["pending_check", "ready_to_claim"]},
             "reward_claimed": {"$ne": True}},
            {"$set": {"status": "completed", "reward_claimed": True,
                      "auto_credited": True, "updated_at": now_iso}},
        )
        if res.modified_count == 0:
            continue
        task = await db.tasks.find_one({"id": tid}, {"_id": 0})
        if not task:
            continue
        reward = int(task.get("reward_city", 0) or 0)
        if not await db.task_completions.find_one({"task_id": tid, "user_id": uid}):
            await db.task_completions.insert_one({
                "id": str(uuid.uuid4()), "task_id": tid, "user_id": uid,
                "completed_at": now_iso,
            })
        if reward > 0:
            await credit_task_reward_bonus(db, uid, reward, "Task reward (auto)")
        try:
            user_doc = await db.users.find_one({"id": uid}, {"_id": 0})
            if user_doc:
                from core.notify import notify_user
                lang = user_doc.get("language") or "en"
                await notify_user(db, user_doc, "GRAM City", _msg(lang, "completed", reward=reward),
                                  type_key="task", add_home_button=True)
        except Exception as e:
            logger.debug(f"story auto-credit notify failed: {e}")
        credited += 1
    return credited



def create_tasks_router(db, get_current_user, get_admin_user):
    """Build (user_router, admin_router) for the tasks module."""
    user_router = APIRouter(prefix="/api/tasks", tags=["Tasks"])
    admin_router = APIRouter(prefix="/api/admin/tasks", tags=["TasksAdmin"])

    async def _full_user(current_user) -> dict:
        doc = await db.users.find_one({"id": current_user.id}, {"_id": 0})
        if not doc and getattr(current_user, "email", None):
            doc = await db.users.find_one({"id": current_user.id}, {"_id": 0})
        return doc or {"id": current_user.id, "language": getattr(current_user, "language", "en")}

    async def _get_daily_rewards() -> list:
        cfg = await db.tasks_config.find_one({"key": "daily_rewards"}, {"_id": 0})
        if cfg and isinstance(cfg.get("rewards"), list) and cfg["rewards"]:
            return [int(x) for x in cfg["rewards"]]
        return list(DEFAULT_DAILY_REWARDS)

    def _daily_activity(user_doc: dict) -> dict:
        """Read the user's resource-trade activity for the current game day (MSK).

        The daily reward is gated on BOTH: buy >= DAILY_BUY_REQUIRED units AND
        sell >= DAILY_SELL_REQUIRED units of any resource(s) today.
        """
        from core.timeutil import msk_today_str
        today = msk_today_str()
        dt = user_doc.get("daily_trade") or {}
        bought = int(dt.get("bought", 0) or 0) if dt.get("date") == today else 0
        sold = int(dt.get("sold", 0) or 0) if dt.get("date") == today else 0
        met = bought >= DAILY_BUY_REQUIRED and sold >= DAILY_SELL_REQUIRED
        return {
            "activity_bought": bought,
            "activity_sold": sold,
            "activity_buy_required": DAILY_BUY_REQUIRED,
            "activity_sell_required": DAILY_SELL_REQUIRED,
            "activity_met": met,
        }

    _GOAL_REQUIRED = {
        "en": "Finish any one goal in «Today» on the Tasks page to claim the daily reward.",
        "ru": "Выполните любую цель из блока «Сегодня» на странице заданий, чтобы забрать ежедневную награду.",
    }

    async def _goal_required_msg(lang: str) -> str:
        """en/ru by hand; other languages via LibreTranslate (cached), English fallback."""
        if lang in _GOAL_REQUIRED:
            return _GOAL_REQUIRED[lang]
        src = _GOAL_REQUIRED["en"]
        try:
            cached = await db.translation_cache.find_one({"kind": "lt_msg", "src": src, "lang": lang}, {"_id": 0})
            if cached and cached.get("text"):
                return cached["text"]
            from translation_service import translate_libre_protected, libretranslate_configured
            if not libretranslate_configured():
                return src
            out = await translate_libre_protected(src, lang, "en")
            await db.translation_cache.update_one({"kind": "lt_msg", "src": src, "lang": lang},
                                                  {"$set": {"kind": "lt_msg", "src": src, "lang": lang, "text": out}},
                                                  upsert=True)
            return out
        except Exception:
            return src

    def _missed_days(last_claim, today_iso: str) -> int:
        """Whole days skipped between the last claim and today (0 if consecutive)."""
        if not last_claim:
            return 0
        try:
            gap = (date.fromisoformat(today_iso) - date.fromisoformat(str(last_claim)[:10])).days
        except ValueError:
            return 0
        return max(0, gap - 1)

    async def _with_quest_gate(user_doc: dict, activity: dict) -> dict:
        """Daily reward is unlocked by EITHER the old trade gate (buy 30 + sell 95)
        OR by finishing any one in-game daily quest (see quests.py). The second
        path is much friendlier for new players."""
        quest_done = False
        try:
            import quests as _quests
            quest_done = await _quests.has_daily_done(user_doc.get("id"))
        except Exception as _e:
            logger.debug(f"daily quest gate check failed: {_e}")
        # The old trade requirement (buy 30 + sell 95 units) is removed: the
        # daily reward is unlocked by finishing any one daily goal.
        return {**activity, "quest_goal_done": quest_done, "activity_met": quest_done}

    async def _credit_reward(user_doc: dict, reward_city: int, reason: str):
        """Credit a task / daily reward to the BONUS balance (non-withdrawable)."""
        await credit_task_reward_bonus(db, user_doc.get("id"), reward_city, reason)

    async def _grant_rewards(user_doc: dict, task: dict, reason: str) -> dict:
        """Grant ALL rewards attached to a task: $CITY coins + warehouse
        resources + skins. Returns a summary of what was credited.

        Skins model (how a skin is determined on the backend):
          • Every skin has a unique string `id` (e.g. "skin_cryptocrazy").
          • A user OWNS a skin when its id is present in `user.available_skins`
            (an array of skin ids, deduped with $addToSet).
          • The catalog `db.skins` maps id → {name, image} so the UI can resolve
            an owned id to a display name/preview. The admin defines the skin
            (id + name + image) right on the task; granting upserts it into the
            catalog and adds the id to the user's `available_skins`.
        """
        uid = user_doc.get("id")
        summary = {"reward_city": 0, "resources": {}, "skins": []}

        # 1) Coins ($CITY)
        reward_city = int(task.get("reward_city", 0) or 0)
        if reward_city > 0:
            await _credit_reward(user_doc, reward_city, reason)
            summary["reward_city"] = reward_city

        # 2) Warehouse resources
        res = task.get("reward_resources") or {}
        inc = {}
        for rtype, amount in res.items():
            try:
                amt = float(amount)
            except (TypeError, ValueError):
                continue
            if amt <= 0:
                continue
            inc[f"resources.{rtype}"] = amt
            summary["resources"][rtype] = amt
        if inc:
            await db.users.update_one({"id": uid}, {"$inc": inc})

        # 3) Skins → add ids to available_skins (dedup) + keep a catalog entry
        skins = task.get("reward_skins") or []
        skin_ids = []
        for sk in skins:
            sid = (sk or {}).get("id")
            if not sid:
                continue
            sid = str(sid).strip()
            if not sid:
                continue
            skin_ids.append(sid)
            summary["skins"].append({"id": sid, "name": sk.get("name") or sid, "image": sk.get("image")})
            try:
                await db.skins.update_one(
                    {"id": sid},
                    {"$set": {"id": sid, "name": sk.get("name") or sid, "image": sk.get("image")}},
                    upsert=True,
                )
            except Exception as e:
                logger.debug(f"skin catalog upsert failed: {e}")
        if skin_ids:
            await db.users.update_one({"id": uid}, {"$addToSet": {"available_skins": {"$each": skin_ids}}})

        # 4) Extra funds → bonus_balance or real balance_ton ($CITY = TON * 1000)
        funds = task.get("reward_funds_amount")
        try:
            funds = float(funds or 0)
        except (TypeError, ValueError):
            funds = 0
        if funds > 0:
            # All task rewards go to the bonus balance (the old "real" option is retired).
            await credit_task_reward_bonus(db, uid, funds, "Quest extra funds", tx_type="task_reward_funds")
            summary["funds"] = {"amount": funds, "target": "bonus"}

        return summary

    async def _do_partner_verify(user_doc: dict, task: dict) -> dict:
        """Call the partner's API to confirm the quest was completed.

        Completion is decided by (in order):
          1. an explicit boolean "completed" field (partner_completed_field);
          2. an explicit numeric threshold (partner_check_field ≥ partner_check_min);
          3. an auto-detected `completed` / `data.completed` boolean;
          4. otherwise HTTP 200 == success.
        The partner scopes progress itself (e.g. iTerra `since`), so we compare
        the RAW value against the threshold — no local baseline subtraction."""
        uid = user_doc.get("id")
        lang = user_doc.get("language") or "en"
        url = (task.get("partner_url") or "").strip()
        if not url:
            raise HTTPException(status_code=400, detail=_msg(lang, "quest_reward_unavailable"))
        try:
            status, body = await _partner_request(user_doc, task)
        except Exception as e:
            logger.warning(f"partner quest verify request failed for task {task.get('id')}: {e}")
            raise HTTPException(status_code=503, detail=_msg(lang, "quest_reward_unavailable"))
        if status != 200:
            logger.info(f"partner quest {task.get('id')} not completed for user {uid}: HTTP {status}")
            raise HTTPException(status_code=400, detail=_msg(lang, "partner_incomplete"))
        if not isinstance(body, dict):
            body = {}

        # 1) Explicit boolean completed field.
        completed_field = (task.get("partner_completed_field") or "").strip()
        if completed_field:
            if not _extract_bool_value(body, completed_field):
                logger.info(f"partner quest {task.get('id')} not completed for {uid}: {completed_field}=falsy")
                raise HTTPException(status_code=400, detail=_msg(lang, "partner_incomplete"))
            return {"ok": True}

        # 2) Explicit numeric threshold (raw value ≥ min). Falls through to the
        #    auto-completed flag when the configured field can't be resolved.
        check_field = (task.get("partner_check_field") or "").strip()
        check_min = task.get("partner_check_min")
        if check_field and check_min is not None:
            current = _extract_check_value(body, check_field)
            if current is not None:
                if float(current) < float(check_min):
                    logger.info(f"partner quest {task.get('id')} below threshold for {uid}: {current} < {check_min}")
                    raise HTTPException(status_code=400, detail=_msg(lang, "partner_progress",
                                                                     have=_fmt_num(current), need=_fmt_num(check_min)))
                return {"ok": True}

        # 3) Auto-detected completed flag (top-level or data.completed).
        auto = _auto_completed_path(body)
        if auto:
            if not _extract_bool_value(body, auto):
                logger.info(f"partner quest {task.get('id')} not completed for {uid}: {auto}=falsy")
                raise HTTPException(status_code=400, detail=_msg(lang, "partner_incomplete"))
            return {"ok": True}

        # 4) HTTP 200 with no checks configured → success.
        return {"ok": True}

    async def _localized_reward_text(task: dict, lang: str) -> str:
        """Return the task's reward description in the player's language, using
        the pre-translated i18n dict when available and falling back to the same
        translation engine as the chat (translate_cached)."""
        i18n = task.get("reward_description_i18n") or {}
        if isinstance(i18n, dict) and i18n.get(lang):
            return i18n[lang]
        text = (task.get("reward_description") or "").strip()
        if not text:
            return ""
        try:
            from translation_service import translate_cached, detect_language
            src = detect_language(text) or "auto"
            if src != lang:
                out = await translate_cached(db, text, lang, src)
                if out:
                    return out
        except Exception:
            pass
        return text

    async def _complete_quest(user_doc: dict, task: dict) -> dict:
        """Mark a quest completed for the user + grant every reward. Idempotent."""
        uid = user_doc.get("id")
        lang = user_doc.get("language") or "en"
        if await db.task_completions.find_one({"task_id": task.get("id"), "user_id": uid}):
            return {"status": "completed"}
        await db.task_completions.insert_one({
            "id": str(uuid.uuid4()),
            "task_id": task.get("id"),
            "user_id": uid,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        rewards = await _grant_rewards(user_doc, task, "Quest reward")
        # Append the translated reward text to the completion notification.
        msg = _msg(lang, "quest_completed")
        reward_text = await _localized_reward_text(task, lang)
        if reward_text:
            msg = f"{msg}\n{reward_text}"
        await _notify(user_doc, "GRAM City", msg)
        return {"status": "completed", "rewards": rewards, "reward_city": rewards.get("reward_city", 0)}

    async def _notify(user_doc: dict, title: str, message: str):
        try:
            from core.notify import notify_user
            await notify_user(db, user_doc, title, message, type_key="task", add_home_button=True)
        except Exception as e:
            logger.debug(f"task notify failed: {e}")

    async def _translate_title(title: str) -> dict:
        """Pre-translate the admin title into all 9 languages (LibreTranslate)."""
        return await _translate_text_all(title)

    async def _translate_text_all(text: str) -> dict:
        """Pre-translate any admin free-text into all 9 project languages.
        Falls back to the original text per-language on any failure so the
        field is never empty."""
        if not text or not text.strip():
            return {}
        out = {}
        try:
            from translation_service import translate_text
        except Exception:
            return {l: text for l in SUPPORTED_LANGS}
        for lang in SUPPORTED_LANGS:
            try:
                translated = await translate_text(text, lang, source_lang="auto")
                out[lang] = translated or text
            except Exception as e:
                logger.debug(f"text translate {lang} failed: {e}")
                out[lang] = text
        return out

    async def _referral_count(uid: str) -> int:
        try:
            return await db.users.count_documents({"referrerId": uid})
        except Exception:
            return 0

    async def _active_referral_count(uid: str) -> int:
        """Active referral = a referred user who owns at least one plot."""
        try:
            return await db.users.count_documents({
                "referrerId": uid,
                "plots_owned.0": {"$exists": True},
            })
        except Exception:
            return 0

    async def _current_ref_count(uid: str, action_type: str) -> int:
        if action_type == "referral_active":
            return await _active_referral_count(uid)
        return await _referral_count(uid)

    async def _ensure_baseline(uid: str, task: dict) -> int:
        """Capture (once) the user's referral count at the moment they first
        encounter a referral task. Progress is measured from this baseline so
        the user must invite `required_referrals` NEW friends after the task
        became available to them."""
        tid = task.get("id")
        at = task.get("action_type")
        current = await _current_ref_count(uid, at)
        try:
            await db.task_referral_baselines.update_one(
                {"user_id": uid, "task_id": tid},
                {"$setOnInsert": {
                    "user_id": uid,
                    "task_id": tid,
                    "baseline": current,
                    "kind": "active" if at == "referral_active" else "total",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }},
                upsert=True,
            )
            doc = await db.task_referral_baselines.find_one({"user_id": uid, "task_id": tid}, {"_id": 0, "baseline": 1})
            return int((doc or {}).get("baseline", current) or 0)
        except Exception:
            return current

    async def _referral_progress(uid: str, task: dict) -> tuple:
        """Return (have, need) where have is NEW referrals since baseline."""
        at = task.get("action_type")
        current = await _current_ref_count(uid, at)
        baseline = await _ensure_baseline(uid, task)
        have = max(0, current - baseline)
        need = int(task.get("required_referrals", 0) or 0)
        return have, need

    # ── Партнёрский квест: значение метрики, baseline и прогресс ─────────────
    async def _partner_request(user_doc: dict, task: dict):
        """Выполнить запрос к API партнёра. Возвращает (status_code, body|None).
        Сетевые ошибки пробрасываются наверх — их ловит вызывающий код."""
        uid = user_doc.get("id")
        url = (task.get("partner_url") or "").strip()
        if not url:
            return None, None
        method = (task.get("partner_method") or "GET").upper()
        if method not in ("GET", "POST"):
            method = "GET"
        user_param = (task.get("partner_user_param") or "user_id").strip() or "user_id"
        tg_value = _user_tg_id(user_doc) or uid
        ref_id = task.get("partner_ref_id") or ""
        # Substitute {telegram_id}/{tg_id}/… tokens the partner baked into the URL.
        url = _substitute_url_placeholders(url, tg_id=tg_value, internal_id=uid, ref_id=ref_id)
        payload = {
            user_param: tg_value,
            "internal_user_id": uid,
            "ref_id": ref_id,
        }
        headers = {"User-Agent": "GRAMCity-QuestVerifier/1.0"}
        api_key = (task.get("partner_api_key") or "").strip()
        if api_key:
            headers["x-api-key"] = api_key
        from urllib.parse import urlsplit, parse_qsl, urlunsplit
        parts = urlsplit(url)
        params = dict(parse_qsl(parts.query, keep_blank_values=True))
        params.update(payload)
        url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", parts.fragment))
        async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=headers) as client:
            if method == "POST":
                resp = await client.post(url, json=payload, params=params)
            else:
                resp = await client.get(url, params=params)
        try:
            body = resp.json()
        except Exception:
            body = None
        return resp.status_code, body

    def _extract_check_value(body, check_field: str):
        """Достать числовое значение по dot-path (например 'data.tradeVolume')."""
        if not body or not check_field:
            return None
        node = body
        for part in check_field.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        try:
            return float(node)
        except (TypeError, ValueError):
            return None

    def _extract_bool_value(body, field: str) -> bool:
        """Достать булев флаг завершения по dot-path (например 'completed').
        Truthy: True, 1, '1', 'true', 'yes', 'ok', 'done', 'completed'."""
        if not body or not field:
            return False
        node = body
        for part in field.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        if isinstance(node, bool):
            return node
        if isinstance(node, (int, float)):
            return node != 0
        if isinstance(node, str):
            return node.strip().lower() in ("1", "true", "yes", "ok", "done", "completed")
        return False

    async def _partner_metric_value(user_doc: dict, task: dict, max_age: int = 30):
        """Текущее значение метрики партнёра с коротким кэшем (по умолчанию 30 с),
        чтобы список заданий не дёргал API партнёра на каждый рендер."""
        check_field = (task.get("partner_check_field") or "").strip()
        if not check_field:
            return None
        uid = user_doc.get("id")
        tid = task.get("id")
        now = datetime.now(timezone.utc)
        doc = await db.task_partner_baselines.find_one({"user_id": uid, "task_id": tid}, {"_id": 0})
        if max_age > 0 and doc and doc.get("last_value") is not None and doc.get("last_value_at"):
            try:
                ts = datetime.fromisoformat(str(doc["last_value_at"]).replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if (now - ts).total_seconds() < max_age:
                    return float(doc["last_value"])
            except Exception:
                pass
        try:
            status, body = await _partner_request(user_doc, task)
        except Exception as e:
            logger.debug(f"partner metric fetch failed for {tid}: {e}")
            status, body = None, None
        val = _extract_check_value(body, check_field) if status == 200 else None
        if val is not None:
            await db.task_partner_baselines.update_one(
                {"user_id": uid, "task_id": tid},
                {"$set": {"last_value": val, "last_value_at": now.isoformat()},
                 "$setOnInsert": {"user_id": uid, "task_id": tid}},
                upsert=True,
            )
            return val
        # Fetch failed / no value right now — fall back to the last known value
        # (any age) so the card keeps showing real progress instead of an
        # endless "updating…" state.
        if doc and doc.get("last_value") is not None:
            try:
                return float(doc["last_value"])
            except (TypeError, ValueError):
                pass
        return None

    async def _ensure_partner_baseline(user_doc: dict, task: dict, current=None):
        """Зафиксировать (один раз) значение метрики партнёра в момент выдачи
        задания. Прирост считается ОТ этого baseline — старые сделки iTerra не
        засчитываются. Baseline пишется только когда значение реально получено."""
        if task.get("partner_check_min") is None:
            return None
        uid = user_doc.get("id")
        tid = task.get("id")
        doc = await db.task_partner_baselines.find_one({"user_id": uid, "task_id": tid}, {"_id": 0, "baseline": 1})
        if doc and doc.get("baseline") is not None:
            return float(doc["baseline"])
        if current is None:
            current = await _partner_metric_value(user_doc, task, max_age=0)
        if current is None:
            return None  # baseline пока не установить — попробуем в следующий раз
        # Гарантируем существование документа (его мог уже создать кэш last_value).
        await db.task_partner_baselines.update_one(
            {"user_id": uid, "task_id": tid},
            {"$setOnInsert": {"user_id": uid, "task_id": tid,
                              "created_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )
        # Проставляем baseline АТОМАРНО только если его ещё нет (нельзя полагаться
        # на $setOnInsert — документ уже мог быть создан кэшем метрики).
        await db.task_partner_baselines.update_one(
            {"user_id": uid, "task_id": tid, "baseline": {"$exists": False}},
            {"$set": {"baseline": float(current),
                      "baseline_at": datetime.now(timezone.utc).isoformat()}},
        )
        doc = await db.task_partner_baselines.find_one({"user_id": uid, "task_id": tid}, {"_id": 0, "baseline": 1})
        return float((doc or {}).get("baseline", current) or 0)

    async def _partner_progress(user_doc: dict, task: dict):
        """(have, need, metric, ready) для порогового партнёрского квеста.
        Партнёр сам ограничивает прогресс по времени (напр. iTerra `since`),
        поэтому показываем СЫРОЕ значение метрики без вычитания baseline."""
        check_min = task.get("partner_check_min")
        need = float(check_min) if check_min is not None else 0.0
        metric = None
        if task.get("partner_check_field"):
            metric = (task.get("partner_check_field") or "").split(".")[-1]
        current = await _partner_metric_value(user_doc, task)
        if current is None:
            return None, need, metric, False
        return float(current), need, metric, True


    async def _promo_channel_id() -> Optional[str]:
        """Channel id configured by the admin in the "Промо" section.
        Stored in admin_settings(type=telegram_bot).channel_id — either a
        public @username or a numeric -100... id."""
        s = await db.admin_settings.find_one({"type": "telegram_bot"}, {"_id": 0, "channel_id": 1})
        cid = (s or {}).get("channel_id") or ""
        return cid.strip() or None

    def _channel_links(channel_id: Optional[str]) -> dict:
        """Build open/boost t.me links from the channel id (per spec we derive
        the link from the id taken from the Promo section, not a hardcoded
        username)."""
        if not channel_id:
            return {"open_url": None, "boost_url": None}
        cid = channel_id.strip()
        if cid.startswith("@"):
            uname = cid[1:]
            return {
                "open_url": f"https://t.me/{uname}",
                "boost_url": f"https://t.me/boost/{uname}",
            }
        # numeric -100xxxxxxxxxx → private channel deep link (works for members)
        num = cid.lstrip("-")
        if num.startswith("100"):
            num = num[3:]
        return {
            "open_url": f"https://t.me/c/{num}",
            "boost_url": f"https://t.me/boost?c={num}",
        }

    async def _story_status_doc(uid: str, task_id: str) -> Optional[dict]:
        return await db.user_task_status.find_one({"user_id": uid, "task_id": task_id}, {"_id": 0})

    def _remaining_seconds(check_available_at: Optional[str]) -> int:
        if not check_available_at:
            return 0
        try:
            dt = datetime.fromisoformat(str(check_available_at).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            return 0
        delta = (dt - datetime.now(timezone.utc)).total_seconds()
        return max(0, int(delta))

    async def _resolve_story_status(uid: str, task_id: str) -> dict:
        """Return the effective story-task status, auto-promoting an expired
        pending_check to ready_to_claim. Never raises."""
        if await db.task_completions.find_one({"task_id": task_id, "user_id": uid}):
            return {"status": "completed", "remaining_seconds": 0, "check_available_at": None, "reward_claimed": True}
        st = await _story_status_doc(uid, task_id)
        if not st:
            return {"status": "not_started", "remaining_seconds": 0, "check_available_at": None, "reward_claimed": False}
        status = st.get("status") or "not_started"
        remaining = _remaining_seconds(st.get("check_available_at"))
        if status == "pending_check" and remaining <= 0:
            status = "ready_to_claim"
            await db.user_task_status.update_one(
                {"user_id": uid, "task_id": task_id}, {"$set": {"status": "ready_to_claim"}}
            )
        return {
            "status": status,
            "remaining_seconds": remaining if status == "pending_check" else 0,
            "check_available_at": st.get("check_available_at"),
            "reward_claimed": bool(st.get("reward_claimed")),
        }

    async def _do_boost_verify(user_doc: dict, task: dict) -> dict:
        """Shared boost verification. Returns dict for the endpoint response and
        credits the reward on success. Raises HTTPException on hard errors."""
        uid = user_doc.get("id")
        lang = user_doc.get("language") or "en"
        if await db.task_completions.find_one({"task_id": task.get("id"), "user_id": uid}):
            return {"success": True, "status": "completed", "message": _msg(lang, "boost_success")}
        tg_id = _user_tg_id(user_doc)
        if not tg_id:
            raise HTTPException(status_code=400, detail=_msg(lang, "link_telegram"))
        chat_id = ((task.get("action_data") or {}).get("chat_id")) or await _promo_channel_id()
        if not chat_id:
            raise HTTPException(status_code=400, detail=_msg(lang, "boost_channel_unset"))
        from telegram_bot import get_telegram_bot
        bot = get_telegram_bot()
        if bot is None:
            raise HTTPException(status_code=503, detail=_msg(lang, "verify_unavailable"))
        res = await bot.get_chat_boosts(chat_id, tg_id)
        if not res.get("ok"):
            code = res.get("error_code")
            err = (res.get("error") or "").lower()
            if code == 429 or "too many requests" in err:
                raise HTTPException(status_code=429, detail=_msg(lang, "boost_rate_limited"))
            if code in (400, 403) or "admin" in err or "not enough rights" in err or "chat not found" in err:
                raise HTTPException(status_code=503, detail=_msg(lang, "boost_bot_not_admin"))
            raise HTTPException(status_code=503, detail=_msg(lang, "verify_unavailable"))
        if len(res.get("boosts") or []) > 0:
            reward = int(task.get("reward_city", 0) or 0)
            await db.task_completions.insert_one({
                "id": str(uuid.uuid4()),
                "task_id": task.get("id"),
                "user_id": uid,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            })
            await _credit_reward(user_doc, reward, "Channel boost reward")
            await _notify(user_doc, "GRAM City", _msg(lang, "completed", reward=reward))
            return {"success": True, "status": "completed", "reward_city": reward, "message": _msg(lang, "boost_success")}
        return {"success": False, "status": "pending", "message": _msg(lang, "boost_not_found")}

    # ==================== USER ENDPOINTS ====================
    async def _localize_task(t: dict, target_lang: str) -> None:
        """Авто-перевод пользовательских текстов задания на язык игрока — через
        тот же движок, что и чат проекта (translation_service.translate_cached,
        с кэшем в Mongo). Заполняем *_i18n[target_lang]; фронт уже умеет их брать.
        Перевод пропускается, если язык совпадает с исходным или текст пуст."""
        try:
            from translation_service import translate_cached, detect_language, translation_configured
        except Exception:
            return
        if not translation_configured():
            return
        for base, i18n_key in (("title", "title_i18n"),
                                ("instructions", "instructions_i18n"),
                                ("reward_description", "reward_description_i18n")):
            text = (t.get(base) or "").strip()
            if not text:
                continue
            existing = t.get(i18n_key) or {}
            # Уже есть готовый перевод (заданный админом вручную) — не трогаем.
            if isinstance(existing, dict) and existing.get(target_lang):
                continue
            src = detect_language(text) or "auto"
            if src == target_lang:
                continue
            try:
                translated = await translate_cached(db, text, target_lang, src)
            except Exception:
                translated = None
            if translated and translated.strip() and translated.strip() != text:
                merged = dict(existing) if isinstance(existing, dict) else {}
                merged[target_lang] = translated.strip()
                t[i18n_key] = merged

    @user_router.get("")
    async def list_tasks(current_user=Depends(get_current_user)):
        user_doc = await _full_user(current_user)
        uid = user_doc.get("id")
        lang = (user_doc.get("language") or "en").split("-")[0]
        tasks = await db.tasks.find({"active": {"$ne": False}}, {"_id": 0}).sort([("order", 1), ("created_at", 1)]).to_list(200)
        completed_ids = set()
        async for c in db.task_completions.find({"user_id": uid}, {"_id": 0, "task_id": 1}):
            completed_ids.add(c["task_id"])
        # my ad submissions
        my_subs = {}
        async for s in db.task_ad_submissions.find({"user_id": uid}, {"_id": 0}):
            my_subs.setdefault(s["task_id"], []).append(s)

        ref_count = await _referral_count(uid)
        # Referrer ids recorded on this user — used to hide partner quests from
        # the partner's OWN referrals when the admin disabled `show_to_referrals`.
        try:
            from routes.partner_programs import user_referrer_ids
            my_referrer_ids = user_referrer_ids(user_doc)
        except Exception:
            my_referrer_ids = set()
        out = []
        for t in tasks:
            t = _clean_task(t)
            tid = t.get("id")
            at = t.get("action_type")
            # Partner-quest visibility: when show_to_referrals is False, hide the
            # task from users who came in via THIS partner's ref link (their
            # referrer id matches the task's partner_ref_id). Everyone else sees it.
            if at == "partner_quest" and t.get("show_to_referrals") is False:
                _pref = str(t.get("partner_ref_id") or "").strip()
                if _pref and _pref in my_referrer_ids:
                    continue
            # Прогресс партнёрского порогового квеста (напр. iTerra tradeVolume):
            # показываем «текущее из порога» с учётом baseline (прирост с момента
            # выдачи задания). Считаем ДО удаления партнёрских полей ниже.
            if (at == "partner_quest" and tid not in completed_ids
                    and t.get("partner_check_field") and t.get("partner_check_min") is not None):
                try:
                    _have, _need, _metric, _ready = await _partner_progress(user_doc, t)
                    t["partner_have"] = _fmt_num(_have) if _have is not None else None
                    t["partner_need"] = _fmt_num(_need)
                    t["partner_metric"] = _metric
                    t["partner_progress_ready"] = _ready
                except Exception as _e:
                    logger.debug(f"partner progress calc failed for {tid}: {_e}")
            # Tab on the Tasks page: «Партнёры» = quests verified through a
            # partner's API; everything else (incl. local quests) = «Система».
            t["category"] = task_category(t)
            # Never leak the partner endpoint / ref id to the client.
            t.pop("partner_url", None)
            t.pop("partner_ref_id", None)
            t.pop("partner_method", None)
            t.pop("partner_api_key", None)
            t.pop("partner_user_param", None)
            status = "pending"
            if tid in completed_ids:
                status = "completed"
            elif at == "ad_tiktok":
                # Repeatable task: only a PENDING submission puts it "under review".
                # We never surface the raw links back to the user.
                subs = my_subs.get(tid, [])
                if any(s.get("status") == "pending" for s in subs):
                    status = "submitted"
                else:
                    status = "pending"
            elif at in REFERRAL_TYPES:
                have, need = await _referral_progress(uid, t)
                t["referral_have"] = have
                t["referral_need"] = need
                if have >= need and need > 0:
                    status = "completed" if tid in completed_ids else "ready"
            elif at in BOOST_TYPES:
                links = _channel_links(await _promo_channel_id())
                t["boost_url"] = ((t.get("action_data") or {}).get("boost_url")) or links["boost_url"]
                t["open_url"] = links["open_url"]
            elif at in STORY_TYPES:
                links = _channel_links(await _promo_channel_id())
                t["open_url"] = links["open_url"]
                sr = await _resolve_story_status(uid, tid)
                status = sr["status"]
                t["remaining_seconds"] = sr["remaining_seconds"]
                t["check_available_at"] = sr["check_available_at"]
            t["status"] = status
            await _localize_task(t, lang)
            out.append(t)
        # completed tasks sink to the bottom
        out.sort(key=lambda x: 1 if x["status"] == "completed" else 0)
        return {"tasks": out, "referral_count": ref_count}

    @user_router.post("/{task_id}/verify")
    async def verify_task(task_id: str, current_user=Depends(get_current_user)):
        user_doc = await _full_user(current_user)
        uid = user_doc.get("id")
        lang = user_doc.get("language") or "en"
        task = await db.tasks.find_one({"id": task_id}, {"_id": 0})
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        if await db.task_completions.find_one({"task_id": task_id, "user_id": uid}):
            return {"status": "completed"}

        at = task.get("action_type")
        reward = int(task.get("reward_city", 0) or 0)

        if at in BOT_VERIFIED_TYPES:
            tg_id = _user_tg_id(user_doc)
            if not tg_id:
                raise HTTPException(status_code=400, detail=_msg(lang, "link_telegram"))
            from telegram_bot import get_telegram_bot
            bot = get_telegram_bot()
            subscribed = None
            if bot is not None:
                subscribed = await bot.is_subscribed(tg_id, task.get("channel_id"))
            # None → we genuinely could not verify (bot down / not admin yet):
            # do NOT credit — ask the user to retry rather than granting for free.
            if subscribed is None:
                raise HTTPException(status_code=503, detail=_msg(lang, "verify_unavailable"))
            if subscribed is False:
                await _notify(user_doc, "GRAM City", _msg(lang, "failed"))
                raise HTTPException(status_code=400, detail=_msg(lang, "failed"))
        elif at in REFERRAL_TYPES:
            have, need = await _referral_progress(uid, task)
            if have < need:
                key = "referral_active_progress" if at == "referral_active" else "referral_progress"
                raise HTTPException(status_code=400, detail=_msg(lang, key, have=have, need=need))
        elif at == "ad_tiktok":
            raise HTTPException(status_code=400, detail="Use submit-ad for advertising tasks")
        elif at in BOOST_TYPES:
            return await _do_boost_verify(user_doc, task)
        elif at in STORY_TYPES:
            raise HTTPException(status_code=400, detail="Use start-check / claim-reward for this task")
        elif at in QUEST_TYPES:
            # Optional gate: quest requires a linked Telegram account.
            if task.get("require_telegram") and not _user_tg_id(user_doc):
                raise HTTPException(status_code=400, detail=_msg(lang, "link_telegram"))
            kind = (task.get("quest_kind") or "local").lower()
            if kind == "partner":
                await _do_partner_verify(user_doc, task)
            # local quests are trust-based → accept immediately
            return await _complete_quest(user_doc, task)
        # TRUST_TYPES → accept immediately

        await db.task_completions.insert_one({
            "id": str(uuid.uuid4()),
            "task_id": task_id,
            "user_id": uid,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        await _credit_reward(user_doc, reward, "Task reward")
        await _notify(user_doc, "GRAM City", _msg(lang, "completed", reward=reward))
        return {"status": "completed", "reward_city": reward}

    @user_router.post("/{task_id}/submit-ad")
    async def submit_ad(task_id: str, data: AdSubmit, current_user=Depends(get_current_user)):
        user_doc = await _full_user(current_user)
        uid = user_doc.get("id")
        lang = user_doc.get("language") or "en"
        task = await db.tasks.find_one({"id": task_id}, {"_id": 0})
        if not task or task.get("action_type") != "ad_tiktok":
            raise HTTPException(status_code=404, detail="Task not found")

        url = (data.url or "").strip()
        low = url.lower()
        if not low.startswith("https://"):
            raise HTTPException(status_code=400, detail="URL must start with https://")
        from urllib.parse import urlparse
        host = (urlparse(url).netloc or "").lower().split(":")[0]
        if not (host == "tiktok.com" or host.endswith(".tiktok.com")):
            raise HTTPException(status_code=400, detail="Only TikTok video links are accepted")

        existing = await db.task_ad_submissions.find({"task_id": task_id, "user_id": uid}, {"_id": 0}).to_list(200)
        # Only ONE submission may be under review at a time. Once it's reviewed
        # (approved/rejected) the user may submit a fresh link again.
        if any(s.get("status") == "pending" for s in existing):
            raise HTTPException(status_code=400, detail=_msg(lang, "ad_submitted"))
        # No duplicate URL anywhere for this task
        if await db.task_ad_submissions.find_one({"task_id": task_id, "url": url}):
            raise HTTPException(status_code=400, detail="This link was already submitted")

        sub = {
            "id": str(uuid.uuid4()),
            "task_id": task_id,
            "user_id": uid,
            "username": user_doc.get("username") or user_doc.get("display_name") or "User",
            "url": url,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "reviewed_at": None,
        }
        await db.task_ad_submissions.insert_one(sub.copy())
        await _notify(user_doc, "GRAM City", _msg(lang, "ad_submitted"))
        return {"status": "submitted", "submission": _clean_task(sub)}

    @user_router.post("/{task_id}/verify-boost")
    async def verify_boost(task_id: str, current_user=Depends(get_current_user)):
        """Verify a Telegram channel boost (getUserChatBoosts) and credit."""
        user_doc = await _full_user(current_user)
        task = await db.tasks.find_one({"id": task_id}, {"_id": 0})
        if not task or task.get("action_type") not in BOOST_TYPES:
            raise HTTPException(status_code=404, detail="Task not found")
        return await _do_boost_verify(user_doc, task)

    @user_router.post("/{task_id}/start-check")
    async def start_check(task_id: str, current_user=Depends(get_current_user)):
        """Start the delayed (23h) verification timer for a repost-story task."""
        user_doc = await _full_user(current_user)
        uid = user_doc.get("id")
        lang = user_doc.get("language") or "en"
        task = await db.tasks.find_one({"id": task_id}, {"_id": 0})
        if not task or task.get("action_type") not in STORY_TYPES:
            raise HTTPException(status_code=404, detail="Task not found")
        sr = await _resolve_story_status(uid, task_id)
        # Idempotent: if a timer is already running (or finished), return current state.
        if sr["status"] == "completed":
            return {"success": True, "status": "completed", "remaining_seconds": 0}
        if sr["status"] in ("pending_check", "ready_to_claim"):
            return {
                "success": True,
                "status": sr["status"],
                "check_available_at": sr["check_available_at"],
                "remaining_seconds": sr["remaining_seconds"],
                "message": _msg(lang, "story_check_started", hours=STORY_CHECK_HOURS),
            }
        check_at = datetime.now(timezone.utc) + timedelta(hours=STORY_CHECK_HOURS)
        check_at_iso = check_at.isoformat()
        await db.user_task_status.update_one(
            {"user_id": uid, "task_id": task_id},
            {"$set": {
                "user_id": uid,
                "task_id": task_id,
                "status": "pending_check",
                "check_available_at": check_at_iso,
                "reward_claimed": False,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }},
            upsert=True,
        )
        return {
            "success": True,
            "status": "pending_check",
            "check_available_at": check_at_iso,
            "remaining_seconds": STORY_CHECK_HOURS * 3600,
            "message": _msg(lang, "story_check_started", hours=STORY_CHECK_HOURS),
        }

    @user_router.get("/{task_id}/status")
    async def task_status(task_id: str, current_user=Depends(get_current_user)):
        """Current status + remaining seconds for a repost-story task."""
        user_doc = await _full_user(current_user)
        uid = user_doc.get("id")
        task = await db.tasks.find_one({"id": task_id}, {"_id": 0})
        if not task or task.get("action_type") not in STORY_TYPES:
            raise HTTPException(status_code=404, detail="Task not found")
        sr = await _resolve_story_status(uid, task_id)
        return {"task_id": task_id, **sr}

    @user_router.post("/{task_id}/claim-reward")
    async def claim_reward(task_id: str, current_user=Depends(get_current_user)):
        """Claim the reward once the 23h timer has elapsed (repost-story task)."""
        user_doc = await _full_user(current_user)
        uid = user_doc.get("id")
        lang = user_doc.get("language") or "en"
        task = await db.tasks.find_one({"id": task_id}, {"_id": 0})
        if not task or task.get("action_type") not in STORY_TYPES:
            raise HTTPException(status_code=404, detail="Task not found")
        sr = await _resolve_story_status(uid, task_id)
        if sr["status"] == "completed":
            return {"success": True, "status": "completed", "message": _msg(lang, "boost_success")}
        if sr["status"] != "ready_to_claim":
            raise HTTPException(status_code=400, detail=_msg(lang, "story_not_ready"))
        # Atomic guard against a double-claim race.
        res = await db.user_task_status.update_one(
            {"user_id": uid, "task_id": task_id, "status": {"$ne": "completed"}, "reward_claimed": {"$ne": True}},
            {"$set": {"status": "completed", "reward_claimed": True, "updated_at": datetime.now(timezone.utc).isoformat()}},
        )
        if res.modified_count == 0:
            return {"success": True, "status": "completed", "message": _msg(lang, "boost_success")}
        reward = int(task.get("reward_city", 0) or 0)
        await db.task_completions.insert_one({
            "id": str(uuid.uuid4()),
            "task_id": task_id,
            "user_id": uid,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        await _credit_reward(user_doc, reward, "Repost story reward")
        await _notify(user_doc, "GRAM City", _msg(lang, "completed", reward=reward))
        return {"success": True, "status": "completed", "reward_city": reward, "message": _msg(lang, "boost_success")}

    @user_router.get("/daily")
    async def daily_state(current_user=Depends(get_current_user)):
        user_doc = await _full_user(current_user)
        rewards = await _get_daily_rewards()
        n = len(rewards)
        streak = int(user_doc.get("daily_streak", 0) or 0)  # last claimed day within the cycle (1..n)
        last = user_doc.get("daily_last_claim")
        from core.timeutil import msk_today
        today = msk_today().isoformat()                      # the game day is Moscow time everywhere
        yesterday = (msk_today() - timedelta(days=1)).isoformat()
        claimed_today = last == today
        shields = int(user_doc.get("streak_shields") or 0)
        missed = _missed_days(last, today)
        shield_use = 0
        # `cur` = number of days already claimed in the CURRENT cycle.
        # `next_day` = which day (1..n) the user will claim next.
        if last == today:
            cur = streak
            next_day = 1 if cur >= n else cur + 1
        elif last == yesterday and streak < n:
            # continuing an unfinished cycle
            cur = streak
            next_day = cur + 1
        elif 1 <= missed <= shields and streak < n:
            # missed day(s) covered by streak shields -> the cycle continues
            cur = streak
            next_day = cur + 1
            shield_use = missed
        else:
            # first claim ever, a missed day, OR the full cycle was completed
            # yesterday -> start a fresh cycle from day 1
            cur = 0
            next_day = 1
        idx = min(max(next_day, 1), n) - 1
        activity = _daily_activity(user_doc)
        activity = await _with_quest_gate(user_doc, activity)
        import ads as _ads
        ad_gate = await _ads.daily_gate(db, user_doc.get("id"))
        return {
            "ads": ad_gate,                                   # rewarded ads before the bonus (Monetag)
            "rewards": rewards,
            "current_streak": cur,
            "claimed_today": claimed_today,
            "next_day": next_day,
            "next_reward": rewards[idx],
            "shields": shields,
            "shield_will_be_used": shield_use,
            "missed_days": missed if not claimed_today else 0,
            **activity,
        }

    @user_router.post("/daily/claim")
    async def daily_claim(current_user=Depends(get_current_user)):
        user_doc = await _full_user(current_user)
        uid = user_doc.get("id")
        lang = user_doc.get("language") or "en"
        rewards = await _get_daily_rewards()
        n = len(rewards)
        from core.timeutil import msk_today
        today = msk_today().isoformat()                      # the game day is Moscow time everywhere
        yesterday = (msk_today() - timedelta(days=1)).isoformat()
        last = user_doc.get("daily_last_claim")
        streak = int(user_doc.get("daily_streak", 0) or 0)
        if last == today:
            raise HTTPException(status_code=400, detail="Already claimed today")
        # Activity gate: must buy >= 30 AND sell >= 95 units of resources today.
        activity = await _with_quest_gate(user_doc, _daily_activity(user_doc))
        if not activity["activity_met"]:
            raise HTTPException(status_code=400, detail=await _goal_required_msg(lang))
        import ads as _ads
        if not (await _ads.daily_gate(db, uid))["ok"]:
            raise HTTPException(status_code=400, detail="ads_required")   # watch the ads first
        # Continue the cycle only if yesterday's claim was NOT the final day.
        # Once the last reward was taken, the next day restarts from day 1.
        # Missed day(s) are forgiven if the player has enough streak shields.
        shields = int(user_doc.get("streak_shields") or 0)
        missed = _missed_days(last, today)
        shield_use = 0
        if last == yesterday and streak < n:
            new_day = streak + 1
        elif 1 <= missed <= shields and streak < n:
            new_day = streak + 1
            shield_use = missed
        else:
            new_day = 1
        idx = min(new_day, n) - 1
        reward = int(rewards[idx])
        # Atomic: only one request per day can pass (double-click / parallel
        # requests used to pay the daily reward twice), and shields are only
        # spent if the player still has them.
        _flt = {"id": uid, "daily_last_claim": {"$ne": today}}
        _upd = {"$set": {"daily_streak": new_day, "daily_last_claim": today}}
        if shield_use:
            _flt["streak_shields"] = {"$gte": shield_use}
            _upd["$inc"] = {"streak_shields": -shield_use}
        _res = await db.users.update_one(_flt, _upd)
        if _res.modified_count == 0:
            raise HTTPException(status_code=409, detail="Already claimed today")
        await _credit_reward(user_doc, reward, "Daily login reward")
        await _notify(user_doc, "GRAM City", _msg(lang, "daily_claimed", reward=reward, day=new_day))
        try:   # leagues: a streak day = activity points
            import leagues
            import city_pass
            leagues.activity_bg(uid, "streak_day", 1)
            city_pass.xp_bg(uid, "streak_day", 1)
        except Exception:
            pass
        return {"status": "claimed", "day": new_day, "reward_city": reward, "shields_used": shield_use}

    @user_router.get("/skins/my")
    async def my_skins(current_user=Depends(get_current_user)):
        """List skins the user owns (ids from available_skins → catalog metadata)."""
        user_doc = await _full_user(current_user)
        owned = user_doc.get("available_skins") or []
        out = []
        for sid in owned:
            meta = await db.skins.find_one({"id": sid}, {"_id": 0})
            out.append(meta or {"id": sid, "name": sid, "image": None})
        return {"skins": out}

    # ==================== ADMIN ENDPOINTS ====================
    @admin_router.get("")
    async def admin_list_tasks(admin=Depends(get_admin_user)):
        tasks = await db.tasks.find({}, {"_id": 0}).sort([("order", 1), ("created_at", 1)]).to_list(500)
        out = []
        for t in tasks:
            t = _clean_task(t)
            t["completions_count"] = await db.task_completions.count_documents({"task_id": t["id"]})
            if t.get("action_type") == "ad_tiktok":
                t["submissions_count"] = await db.task_ad_submissions.count_documents({"task_id": t["id"]})
            out.append(t)
        return {"tasks": out}

    async def _build_task_fields(data: TaskCreate):
        """Validate + normalize a TaskCreate into the stored task fields.
        Shared by create and update so both accept identical conditions.
        Returns (fields_dict, reward_skins_list). Excludes id/order/created_at/active."""
        if data.action_type not in ALL_ACTION_TYPES:
            raise HTTPException(status_code=400, detail="Invalid action_type")
        if data.action_type in BOT_VERIFIED_TYPES and not (data.channel_url and data.channel_id):
            raise HTTPException(status_code=400, detail="channel_url and channel_id are required")
        if data.action_type in TRUST_TYPES and not data.target_url:
            raise HTTPException(status_code=400, detail="target_url is required")
        if data.action_type in REFERRAL_TYPES and not (data.required_referrals and data.required_referrals > 0):
            raise HTTPException(status_code=400, detail="required_referrals must be > 0")
        if data.action_type == "ad_tiktok" and not (data.views_rate and data.views_rate > 0):
            raise HTTPException(status_code=400, detail="views_rate ($CITY per 1000 views) must be > 0")

        # ── Partner / local quest validation + normalization ────────────────
        quest_kind = None
        partner_url = partner_ref_id = partner_method = partner_api_key = partner_user_param = None
        partner_check_field = partner_check_min = None
        partner_completed_field = None
        reward_resources = None
        reward_skins = None
        if data.action_type in QUEST_TYPES:
            quest_kind = (data.quest_kind or "local").lower()
            if quest_kind not in ("partner", "local"):
                raise HTTPException(status_code=400, detail="quest_kind must be 'partner' or 'local'")
            if quest_kind == "partner":
                partner_url = (data.partner_url or "").strip()
                if not partner_url.lower().startswith(("http://", "https://")):
                    raise HTTPException(status_code=400, detail="partner_url must be a valid http(s) URL")
                partner_ref_id = (data.partner_ref_id or "").strip() or None
                partner_api_key = (data.partner_api_key or "").strip() or None
                partner_user_param = (data.partner_user_param or "").strip() or None
                if partner_user_param and not partner_user_param.replace("_", "").replace("-", "").isalnum():
                    raise HTTPException(status_code=400, detail="partner_user_param must be alphanumeric")
                partner_method = (data.partner_method or "GET").upper()
                if partner_method not in ("GET", "POST"):
                    partner_method = "GET"
                partner_check_field = (data.partner_check_field or "").strip() or None
                try:
                    partner_check_min = float(data.partner_check_min) if data.partner_check_min is not None else None
                except (TypeError, ValueError):
                    partner_check_min = None
                partner_completed_field = (data.partner_completed_field or "").strip() or None
            # Normalize resource rewards {resource_type: positive amount}
            if data.reward_resources:
                reward_resources = {}
                for rtype, amount in data.reward_resources.items():
                    try:
                        amt = float(amount)
                    except (TypeError, ValueError):
                        continue
                    if amt > 0:
                        reward_resources[str(rtype)] = amt
                reward_resources = reward_resources or None
            # Normalize skin rewards [{id, name, image?}]
            if data.reward_skins:
                reward_skins = []
                for sk in data.reward_skins:
                    sid = str((sk or {}).get("id") or "").strip()
                    if not sid:
                        continue
                    reward_skins.append({
                        "id": sid,
                        "name": (sk.get("name") or sid),
                        "image": sk.get("image") or None,
                    })
                reward_skins = reward_skins or None
            # Extra funds reward (bonus or real balance)
            reward_funds_amount = float(data.reward_funds_amount or 0)
            reward_funds_target = "bonus" if data.reward_funds_target == "bonus" else "real"
            if reward_funds_amount <= 0:
                reward_funds_amount = 0
            # A quest must grant SOMETHING
            if not (int(data.reward_city or 0) > 0 or reward_resources or reward_skins or reward_funds_amount > 0):
                raise HTTPException(status_code=400, detail="A quest must grant at least one reward (coins, funds, resources or a skin)")
        else:
            reward_funds_amount = 0
            reward_funds_target = "real"

        # tg_channel_boost / repost_story: the channel is taken from the admin
        # "Промо" section, so no channel fields are required here. Optional
        # chat_id/boost_url overrides are stored under action_data.
        action_data = None
        if data.action_type in BOOST_TYPES:
            action_data = {
                "chat_id": (data.chat_id or "").strip() or None,
                "boost_url": (data.boost_url or "").strip() or None,
            }

        title_i18n = await _translate_title(data.title)
        instructions_clean = (data.instructions or "").strip() or None
        instructions_i18n = await _translate_text_all(instructions_clean) if instructions_clean else None
        reward_desc_clean = (data.reward_description or "").strip() or None
        reward_description_i18n = await _translate_text_all(reward_desc_clean) if reward_desc_clean else None
        # Optional reward: keep None when the admin left it empty so the card
        # can hide the amount entirely.
        reward_city_val = int(data.reward_city) if data.reward_city else None
        # require_telegram only applies to quests.
        require_telegram = bool(data.require_telegram) if data.action_type in QUEST_TYPES else False
        fields = {
            "title": data.title,
            "title_i18n": title_i18n,
            "reward_city": reward_city_val,
            "action_type": data.action_type,
            "require_telegram": require_telegram,
            "photo": data.photo,
            "icon": data.icon,
            "icon_url": data.icon_url,
            "channel_url": data.channel_url,
            "channel_id": data.channel_id,
            "target_url": data.target_url,
            "required_referrals": data.required_referrals,
            "views_rate": float(data.views_rate) if data.views_rate else None,
            "action_data": action_data,
            "quest_kind": quest_kind,
            "partner_url": partner_url,
            "partner_ref_id": partner_ref_id,
            "partner_method": partner_method,
            "partner_api_key": partner_api_key,
            "partner_user_param": partner_user_param,
            "partner_check_field": partner_check_field,
            "partner_check_min": partner_check_min,
            "partner_completed_field": partner_completed_field,
            "instructions": (data.instructions or None),
            "instructions_i18n": instructions_i18n,
            "reward_description": reward_desc_clean,
            "reward_description_i18n": reward_description_i18n,
            "reward_resources": reward_resources,
            "reward_skins": reward_skins,
            "reward_funds_amount": reward_funds_amount or None,
            "reward_funds_target": reward_funds_target if reward_funds_amount else None,
            # Partner-quest visibility toggle (default True → shown to everyone).
            "show_to_referrals": (bool(data.show_to_referrals)
                                  if data.show_to_referrals is not None else True),
        }
        return fields, reward_skins

    @admin_router.post("/test-partner")
    async def admin_test_partner(data: TestPartnerRequest, admin=Depends(get_admin_user)):
        """Предпросмотр ответа сервера партнёра при создании/изменении задания.
        Делает реальный запрос с указанным test_user_id и возвращает сырой ответ
        и вердикт — ТА ЖЕ логика, что и реальная проверка пользователя."""
        url = (data.partner_url or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="partner_url must be a valid http(s) URL")
        method = (data.partner_method or "GET").upper()
        if method not in ("GET", "POST"):
            method = "GET"
        user_param = (data.partner_user_param or "user_id").strip() or "user_id"
        tg_value = str(data.test_user_id or "").strip()
        ref_id = data.partner_ref_id or ""
        # Подставляем {telegram_id}/{tg_id}/… из URL так же, как в реальном запросе.
        url = _substitute_url_placeholders(url, tg_id=tg_value, internal_id="preview", ref_id=ref_id)
        payload = {
            user_param: tg_value,
            "internal_user_id": "preview",
            "ref_id": ref_id,
        }
        headers = {"User-Agent": "GRAMCity-QuestVerifier/1.0"}
        if (data.partner_api_key or "").strip():
            headers["x-api-key"] = data.partner_api_key.strip()
        from urllib.parse import urlsplit, parse_qsl, urlunsplit, urlencode
        parts = urlsplit(url)
        params = dict(parse_qsl(parts.query, keep_blank_values=True))
        params.update(payload)
        clean_url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", parts.fragment))
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=headers) as client:
                if method == "POST":
                    resp = await client.post(clean_url, json=payload, params=params)
                else:
                    resp = await client.get(clean_url, params=params)
        except Exception as e:
            return {"ok": False, "reachable": False, "error": str(e),
                    "request_url": f"{clean_url}?{urlencode(params)}", "verdict": False,
                    "verdict_reason": "Не удалось связаться с сервером партнёра"}
        status = resp.status_code
        try:
            body = resp.json()
            raw = body
        except Exception:
            body = None
            raw = (resp.text or "")[:2000]
        # Вердикт — идентичен _do_partner_verify: явный флаг → явный порог →
        # авто-определённый completed → HTTP 200.
        completed_field = (data.partner_completed_field or "").strip()
        check_field = (data.partner_check_field or "").strip()
        extracted_value = None
        completed_value = None
        verdict = False
        reason = ""
        if status != 200:
            reason = f"HTTP {status} (ожидался 200)"
        elif completed_field:
            completed_value = _extract_bool_value(body, completed_field)
            verdict = bool(completed_value)
            reason = f"{completed_field} = {completed_value}"
        elif check_field and data.partner_check_min is not None and _extract_check_value(body, check_field) is not None:
            extracted_value = _extract_check_value(body, check_field)
            verdict = float(extracted_value) >= float(data.partner_check_min)
            reason = f"{check_field} = {extracted_value} (порог {data.partner_check_min})"
        else:
            auto = _auto_completed_path(body)
            if auto:
                completed_value = _extract_bool_value(body, auto)
                verdict = bool(completed_value)
                reason = f"{auto} = {completed_value} (поле определено автоматически)"
            elif check_field and data.partner_check_min is not None:
                reason = f"Поле «{check_field}» не найдено или не число"
            else:
                verdict = True
                reason = "HTTP 200 без доп. проверок — засчитывается сразу"
        return {
            "ok": True,
            "reachable": True,
            "request_url": f"{clean_url}?{urlencode(params)}",
            "sent_params": params,
            "status": status,
            "raw_response": raw,
            "extracted_value": extracted_value,
            "completed_value": completed_value,
            "verdict": verdict,
            "verdict_reason": reason,
        }

    @admin_router.post("")
    async def admin_create_task(data: TaskCreate, admin=Depends(get_admin_user)):
        fields, reward_skins = await _build_task_fields(data)
        order = await db.tasks.count_documents({})
        task = {
            "id": str(uuid.uuid4()),
            **fields,
            "active": True,
            "order": order,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.tasks.insert_one(task.copy())
        # Seed the skin catalog so owned ids resolve to a name/image later.
        for sk in (reward_skins or []):
            try:
                await db.skins.update_one({"id": sk["id"]}, {"$set": sk}, upsert=True)
            except Exception as e:
                logger.debug(f"skin catalog seed failed: {e}")
        return {"status": "created", "task": _clean_task(task)}

    @admin_router.put("/{task_id}/update")
    async def admin_update_task(task_id: str, data: TaskCreate, admin=Depends(get_admin_user)):
        """Edit an existing task's conditions. Preserves id, order, created_at,
        active state and completion history — only the content/conditions change."""
        existing = await db.tasks.find_one({"id": task_id}, {"_id": 0})
        if not existing:
            raise HTTPException(status_code=404, detail="Task not found")
        fields, reward_skins = await _build_task_fields(data)
        await db.tasks.update_one({"id": task_id}, {"$set": fields})
        # Сброс baseline при выдаче нового/обновлённого задания: старый прогресс
        # обнуляется, чтобы учёт метрики (iTerra tradeVolume и т.п.) начинался
        # заново с момента новой выдачи — прежние сделки не засчитываются.
        try:
            await db.task_partner_baselines.delete_many({"task_id": task_id})
        except Exception as e:
            logger.debug(f"reset partner baselines failed: {e}")
        for sk in (reward_skins or []):
            try:
                await db.skins.update_one({"id": sk["id"]}, {"$set": sk}, upsert=True)
            except Exception as e:
                logger.debug(f"skin catalog seed failed: {e}")
        updated = await db.tasks.find_one({"id": task_id}, {"_id": 0})
        return {"status": "updated", "task": _clean_task(updated)}

    @admin_router.put("/reorder")
    async def admin_reorder(data: ReorderPayload, admin=Depends(get_admin_user)):
        for idx, tid in enumerate(data.ids):
            await db.tasks.update_one({"id": tid}, {"$set": {"order": idx}})
        return {"status": "reordered"}

    @admin_router.patch("/{task_id}/active")
    async def admin_toggle_active(task_id: str, data: ActiveToggle, admin=Depends(get_admin_user)):
        res = await db.tasks.update_one({"id": task_id}, {"$set": {"active": bool(data.active)}})
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Task not found")
        return {"status": "updated", "active": bool(data.active)}

    @admin_router.post("/{task_id}/duplicate")
    async def admin_duplicate_task(task_id: str, admin=Depends(get_admin_user)):
        src = await db.tasks.find_one({"id": task_id}, {"_id": 0})
        if not src:
            raise HTTPException(status_code=404, detail="Task not found")
        new = dict(src)
        new["id"] = str(uuid.uuid4())
        new["order"] = await db.tasks.count_documents({})
        new["created_at"] = datetime.now(timezone.utc).isoformat()
        new["active"] = True
        await db.tasks.insert_one(new.copy())
        return {"status": "duplicated", "task": _clean_task(new)}

    @admin_router.delete("/{task_id}")
    async def admin_delete_task(task_id: str, admin=Depends(get_admin_user)):
        res = await db.tasks.delete_one({"id": task_id})
        if res.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Task not found")
        await db.task_completions.delete_many({"task_id": task_id})
        await db.task_ad_submissions.delete_many({"task_id": task_id})
        return {"status": "deleted"}

    @admin_router.get("/daily-rewards")
    async def admin_get_daily(admin=Depends(get_admin_user)):
        return {"rewards": await _get_daily_rewards()}

    @admin_router.put("/daily-rewards")
    async def admin_set_daily(data: DailyRewardsUpdate, admin=Depends(get_admin_user)):
        rewards = [int(x) for x in data.rewards if int(x) >= 0]
        if not rewards:
            raise HTTPException(status_code=400, detail="rewards cannot be empty")
        await db.tasks_config.update_one(
            {"key": "daily_rewards"}, {"$set": {"key": "daily_rewards", "rewards": rewards}}, upsert=True
        )
        return {"status": "saved", "rewards": rewards}

    @admin_router.get("/{task_id}/ad-submissions")
    async def admin_ad_submissions(task_id: str, search: str = "", admin=Depends(get_admin_user)):
        q = {"task_id": task_id}
        if search and search.strip():
            q["url"] = {"$regex": search.strip(), "$options": "i"}
        subs = await db.task_ad_submissions.find(q, {"_id": 0}).sort("created_at", -1).to_list(1000)
        task = await db.tasks.find_one({"id": task_id}, {"_id": 0})
        # Count how many times each URL appears WITHIN THIS TASK (duplicate detection)
        url_counts = {}
        for s in await db.task_ad_submissions.find({"task_id": task_id}, {"_id": 0, "url": 1}).to_list(5000):
            u = s.get("url")
            url_counts[u] = url_counts.get(u, 0) + 1
        for s in subs:
            s["url_count"] = url_counts.get(s.get("url"), 1)
            s["is_duplicate"] = s["url_count"] > 1
            s["effective_payout"] = _effective_ad_payout(s, task)
        return {"submissions": subs, "views_rate": (task or {}).get("views_rate")}

    @admin_router.post("/ad-submissions/{sub_id}/refresh-stats")
    async def admin_refresh_ad_stats(sub_id: str, admin=Depends(get_admin_user)):
        sub = await db.task_ad_submissions.find_one({"id": sub_id}, {"_id": 0})
        if not sub:
            raise HTTPException(status_code=404, detail="Submission not found")
        task = await db.tasks.find_one({"id": sub["task_id"]}, {"_id": 0})
        rate = float((task or {}).get("views_rate") or 0)
        stats = await _fetch_tiktok_stats(sub.get("url", ""))
        if not stats.get("ok"):
            raise HTTPException(status_code=502, detail=f"Не удалось получить статистику TikTok: {stats.get('error')}")
        views = stats["views"]
        likes = stats["likes"]
        payout_city = int(round(views / 1000.0 * rate)) if rate > 0 else 0
        upd = {
            "views": views,
            "likes": likes,
            "comments": stats.get("comments", 0),
            "payout_city": payout_city,
            "stats_fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.task_ad_submissions.update_one({"id": sub_id}, {"$set": upd})
        merged = {**sub, **upd}
        merged["effective_payout"] = _effective_ad_payout(merged, task)
        return {"status": "ok", **upd, "effective_payout": merged["effective_payout"]}

    @admin_router.post("/ad-submissions/{sub_id}/set-payout")
    async def admin_set_ad_payout(sub_id: str, data: PayoutUpdate, admin=Depends(get_admin_user)):
        sub = await db.task_ad_submissions.find_one({"id": sub_id}, {"_id": 0})
        if not sub:
            raise HTTPException(status_code=404, detail="Submission not found")
        await db.task_ad_submissions.update_one({"id": sub_id}, {"$set": {"payout_override": int(data.amount)}})
        return {"status": "ok", "effective_payout": int(data.amount)}

    @admin_router.post("/ad-submissions/{sub_id}/approve")
    async def admin_approve_ad(sub_id: str, admin=Depends(get_admin_user)):
        sub = await db.task_ad_submissions.find_one({"id": sub_id}, {"_id": 0})
        if not sub:
            raise HTTPException(status_code=404, detail="Submission not found")
        if sub.get("status") != "pending":
            raise HTTPException(status_code=400, detail="Already reviewed")
        task = await db.tasks.find_one({"id": sub["task_id"]}, {"_id": 0})
        reward = _effective_ad_payout(sub, task)
        await db.task_ad_submissions.update_one(
            {"id": sub_id}, {"$set": {"status": "approved", "reviewed_at": datetime.now(timezone.utc).isoformat(), "paid_city": reward}}
        )
        # Ad tasks are REPEATABLE: credit the reward for this approved link and
        # notify the user which link was accepted. The task stays available so
        # the user can post another video and submit a new link afterwards.
        user_doc = await db.users.find_one({"id": sub["user_id"]}, {"_id": 0})
        if user_doc:
            await _credit_reward(user_doc, reward, "Ad task reward")
            lang = user_doc.get("language") or "en"
            await _notify(user_doc, "GRAM City", _msg(lang, "ad_approved_link", reward=reward, url=sub.get("url", "")))
        return {"status": "approved", "paid_city": reward}

    @admin_router.post("/ad-submissions/{sub_id}/reject")
    async def admin_reject_ad(sub_id: str, admin=Depends(get_admin_user)):
        sub = await db.task_ad_submissions.find_one({"id": sub_id}, {"_id": 0})
        if not sub:
            raise HTTPException(status_code=404, detail="Submission not found")
        if sub.get("status") != "pending":
            raise HTTPException(status_code=400, detail="Already reviewed")
        await db.task_ad_submissions.update_one(
            {"id": sub_id}, {"$set": {"status": "rejected", "reviewed_at": datetime.now(timezone.utc).isoformat()}}
        )
        user_doc = await db.users.find_one({"id": sub["user_id"]}, {"_id": 0})
        if user_doc:
            lang = user_doc.get("language") or "en"
            await _notify(user_doc, "GRAM City", _msg(lang, "ad_rejected"))
        return {"status": "rejected"}

    # ==================== V1 ALIASES (spec-compliant paths) ====================
    # These mirror the exact endpoint paths from the task spec and reuse the
    # same underlying logic/handlers defined above.
    v1_router = APIRouter(prefix="/api/v1/tasks", tags=["TasksV1"])
    v1_admin_router = APIRouter(prefix="/api/v1/admin/tasks", tags=["TasksV1Admin"])

    class _TaskIdBody(BaseModel):
        task_id: str

    class _V1BoostCreate(BaseModel):
        title: str = "Boost Our Telegram Channel"
        chat_id: Optional[str] = None
        boost_url: Optional[str] = None
        reward: int = Field(0, ge=0)
        action_type: str = "tg_channel_boost"
        photo: Optional[str] = None
        icon: Optional[str] = None
        icon_url: Optional[str] = None

    @v1_router.post("/verify-boost")
    async def v1_verify_boost(body: _TaskIdBody, current_user=Depends(get_current_user)):
        user_doc = await _full_user(current_user)
        task = await db.tasks.find_one({"id": body.task_id}, {"_id": 0})
        if not task or task.get("action_type") not in BOOST_TYPES:
            raise HTTPException(status_code=404, detail="Task not found")
        return await _do_boost_verify(user_doc, task)

    @v1_router.post("/start-check")
    async def v1_start_check(body: _TaskIdBody, current_user=Depends(get_current_user)):
        return await start_check(body.task_id, current_user)

    @v1_router.get("/status/{task_id}")
    async def v1_status(task_id: str, current_user=Depends(get_current_user)):
        return await task_status(task_id, current_user)

    @v1_router.post("/claim-reward")
    async def v1_claim(body: _TaskIdBody, current_user=Depends(get_current_user)):
        return await claim_reward(body.task_id, current_user)

    @v1_admin_router.post("/create")
    async def v1_admin_create(body: _V1BoostCreate, admin=Depends(get_admin_user)):
        payload = TaskCreate(
            title=body.title,
            reward_city=int(body.reward),
            action_type=body.action_type,
            photo=body.photo,
            icon=body.icon,
            icon_url=body.icon_url,
            chat_id=body.chat_id,
            boost_url=body.boost_url,
        )
        return await admin_create_task(payload, admin)

    return user_router, admin_router, v1_router, v1_admin_router
