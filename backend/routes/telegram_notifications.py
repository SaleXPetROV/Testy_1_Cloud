"""Localized Telegram-bot notifications for auth-related events (link,
unlink, login). Kept OUTSIDE the login-link and link handlers so a slow
Telegram Bot API call never blocks the HTTP response.

Language resolution order (per Telegram user):
  1. `telegram_mappings.language`  — what the user picked with /start
  2. `users.language`               — the account's site language
  3. `"en"`                         — default for a user who has never
                                      picked a bot language

Supported languages (kept in sync with `core.i18n_messages.SUPPORTED`):
    en, ru, es, zh, fr, de, ja, ko, id
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"

# Message catalogues -----------------------------------------------------------
# Keep messages short (single Telegram bubble). Only auth flows use them.
_MESSAGES = {
    "linked": {
        "en": "🔗 <b>Telegram linked</b>\n\nYour Telegram account is now linked to your GRAM City profile. You'll receive game notifications here.",
        "ru": "🔗 <b>Telegram привязан</b>\n\nВаш Telegram-аккаунт теперь привязан к профилю GRAM City. Здесь будут приходить игровые уведомления.",
        "es": "🔗 <b>Telegram vinculado</b>\n\nTu cuenta de Telegram está vinculada a tu perfil de GRAM City. Aquí recibirás las notificaciones del juego.",
        "zh": "🔗 <b>已绑定 Telegram</b>\n\n您的 Telegram 已与 GRAM City 账号绑定，游戏通知将发送到这里。",
        "fr": "🔗 <b>Telegram connecté</b>\n\nVotre compte Telegram est maintenant lié à votre profil GRAM City. Les notifications du jeu arriveront ici.",
        "de": "🔗 <b>Telegram verknüpft</b>\n\nDein Telegram-Konto ist jetzt mit deinem GRAM City-Profil verknüpft. Spielbenachrichtigungen erscheinen hier.",
        "ja": "🔗 <b>Telegram をリンクしました</b>\n\nGRAM City のアカウントに Telegram をリンクしました。ゲーム通知はこちらに届きます。",
        "ko": "🔗 <b>Telegram 연결됨</b>\n\n텔레그램 계정이 GRAM City 프로필과 연결되었습니다. 게임 알림이 여기로 전송됩니다.",
        "id": "🔗 <b>Telegram terhubung</b>\n\nAkun Telegram Anda kini terhubung dengan profil GRAM City. Notifikasi permainan akan dikirim ke sini.",
    },
    "unlinked": {
        "en": "🔌 <b>Telegram unlinked</b>\n\nThis Telegram is no longer linked to a GRAM City account. Game notifications are stopped.",
        "ru": "🔌 <b>Telegram отвязан</b>\n\nЭтот Telegram больше не привязан к аккаунту GRAM City. Игровые уведомления отключены.",
        "es": "🔌 <b>Telegram desvinculado</b>\n\nEste Telegram ya no está vinculado a una cuenta de GRAM City. Se detienen las notificaciones del juego.",
        "zh": "🔌 <b>已解除绑定</b>\n\n此 Telegram 已与 GRAM City 账号解除绑定，游戏通知已停止。",
        "fr": "🔌 <b>Telegram dissocié</b>\n\nCe Telegram n'est plus lié à un compte GRAM City. Les notifications du jeu sont arrêtées.",
        "de": "🔌 <b>Telegram getrennt</b>\n\nDieses Telegram ist nicht mehr mit einem GRAM City-Konto verknüpft. Spielbenachrichtigungen wurden gestoppt.",
        "ja": "🔌 <b>Telegram の連携を解除しました</b>\n\nこの Telegram は GRAM City のアカウントとリンクされなくなりました。ゲーム通知は停止しました。",
        "ko": "🔌 <b>Telegram 연결 해제</b>\n\n이 텔레그램은 더 이상 GRAM City 계정과 연결되어 있지 않습니다. 게임 알림이 중지되었습니다.",
        "id": "🔌 <b>Telegram diputus</b>\n\nTelegram ini tidak lagi terhubung ke akun GRAM City. Notifikasi permainan dihentikan.",
    },
    "login_new": {
        "en": "✅ <b>Account created!</b>\n\nGo back to your browser — you're now signed in.",
        "ru": "✅ <b>Аккаунт создан!</b>\n\nВернитесь в браузер — вы уже вошли.",
        "es": "✅ <b>¡Cuenta creada!</b>\n\nVuelve a tu navegador — ya has iniciado sesión.",
        "zh": "✅ <b>账号已创建！</b>\n\n请回到浏览器 — 您已成功登录。",
        "fr": "✅ <b>Compte créé !</b>\n\nRetournez dans votre navigateur — vous êtes connecté.",
        "de": "✅ <b>Konto erstellt!</b>\n\nZurück im Browser bist du angemeldet.",
        "ja": "✅ <b>アカウントを作成しました！</b>\n\nブラウザに戻ってください — もうログインしています。",
        "ko": "✅ <b>계정이 생성되었습니다!</b>\n\n브라우저로 돌아가세요 — 이미 로그인되어 있습니다.",
        "id": "✅ <b>Akun dibuat!</b>\n\nKembali ke browser — Anda sudah masuk.",
    },
    "login_existing": {
        "en": "✅ <b>Signed in!</b>\n\nGo back to your browser — you're already logged in.",
        "ru": "✅ <b>Вход выполнен!</b>\n\nВернитесь в браузер — вы уже вошли в аккаунт.",
        "es": "✅ <b>¡Sesión iniciada!</b>\n\nVuelve a tu navegador — ya estás dentro.",
        "zh": "✅ <b>登录成功！</b>\n\n请回到浏览器 — 您已登录。",
        "fr": "✅ <b>Connecté !</b>\n\nRetournez dans votre navigateur — vous êtes déjà connecté.",
        "de": "✅ <b>Angemeldet!</b>\n\nZurück im Browser bist du bereits eingeloggt.",
        "ja": "✅ <b>ログインしました！</b>\n\nブラウザに戻ってください — すでにログイン済みです。",
        "ko": "✅ <b>로그인되었습니다!</b>\n\n브라우저로 돌아가세요 — 이미 접속되어 있습니다.",
        "id": "✅ <b>Berhasil masuk!</b>\n\nKembali ke browser — Anda sudah masuk.",
    },
    "login_choose": {
        "en": "👀 <b>Almost there!</b>\n\nGo back to the app and choose: <b>create a new account</b> or <b>link this Telegram to an existing account</b>.",
        "ru": "👀 <b>Почти готово!</b>\n\nВернитесь в приложение и выберите: <b>создать новый аккаунт</b> или <b>привязать этот Telegram к существующему</b>.",
        "es": "👀 <b>¡Casi listo!</b>\n\nVuelve a la app y elige: <b>crear una cuenta nueva</b> o <b>vincular este Telegram a una cuenta existente</b>.",
        "zh": "👀 <b>就快好了！</b>\n\n请回到应用并选择：<b>创建新账号</b> 或 <b>将此 Telegram 绑定到现有账号</b>。",
        "fr": "👀 <b>Presque terminé !</b>\n\nRetournez dans l'application et choisissez : <b>créer un nouveau compte</b> ou <b>associer ce Telegram à un compte existant</b>.",
        "de": "👀 <b>Fast geschafft!</b>\n\nGeh zurück in die App und wähle: <b>neues Konto erstellen</b> oder <b>dieses Telegram mit einem bestehenden Konto verknüpfen</b>.",
        "ja": "👀 <b>あと少しです！</b>\n\nアプリに戻って選択してください：<b>新しいアカウントを作成</b> または <b>この Telegram を既存のアカウントに連携</b>。",
        "ko": "👀 <b>거의 다 됐어요!</b>\n\n앱으로 돌아가 선택하세요: <b>새 계정 만들기</b> 또는 <b>이 텔레그램을 기존 계정에 연결</b>.",
        "id": "👀 <b>Hampir selesai!</b>\n\nKembali ke aplikasi dan pilih: <b>buat akun baru</b> atau <b>tautkan Telegram ini ke akun yang sudah ada</b>.",
    },
    "login_link_invalid": {
        "en": "❌ Invalid or expired login link.",
        "ru": "❌ Некорректная или устаревшая ссылка входа.",
        "es": "❌ Enlace de inicio de sesión inválido o vencido.",
        "zh": "❌ 登录链接无效或已过期。",
        "fr": "❌ Lien de connexion invalide ou expiré.",
        "de": "❌ Ungültiger oder abgelaufener Login-Link.",
        "ja": "❌ 無効または期限切れのログインリンクです。",
        "ko": "❌ 유효하지 않거나 만료된 로그인 링크입니다.",
        "id": "❌ Tautan masuk tidak valid atau kedaluwarsa.",
    },
    "login_link_used": {
        "en": "✅ Already confirmed — go back to your browser.",
        "ru": "✅ Уже подтверждено — вернитесь в браузер.",
        "es": "✅ Ya confirmado — vuelve a tu navegador.",
        "zh": "✅ 已确认 — 请回到浏览器。",
        "fr": "✅ Déjà confirmé — retournez dans votre navigateur.",
        "de": "✅ Bereits bestätigt — zurück im Browser.",
        "ja": "✅ 既に確認済みです — ブラウザに戻ってください。",
        "ko": "✅ 이미 확인됨 — 브라우저로 돌아가세요.",
        "id": "✅ Sudah dikonfirmasi — kembali ke browser.",
    },
    "login_link_expired": {
        "en": "❌ Link expired. Please start the login again from the site.",
        "ru": "❌ Срок действия ссылки истёк. Попробуйте войти заново.",
        "es": "❌ El enlace ha caducado. Vuelve a iniciar sesión desde el sitio.",
        "zh": "❌ 链接已过期。请从网站重新登录。",
        "fr": "❌ Le lien a expiré. Veuillez recommencer la connexion depuis le site.",
        "de": "❌ Link abgelaufen. Bitte starte den Login erneut auf der Website.",
        "ja": "❌ リンクの期限が切れました。サイトから再度ログインしてください。",
        "ko": "❌ 링크가 만료되었습니다. 사이트에서 다시 로그인하세요.",
        "id": "❌ Tautan kedaluwarsa. Silakan mulai masuk lagi dari situs.",
    },
    "login_failed": {
        "en": "❌ Couldn't create the account — please try again.",
        "ru": "❌ Не удалось создать аккаунт — попробуйте ещё раз.",
        "es": "❌ No se pudo crear la cuenta — intenta de nuevo.",
        "zh": "❌ 无法创建账号 — 请重试。",
        "fr": "❌ Impossible de créer le compte — veuillez réessayer.",
        "de": "❌ Konto konnte nicht erstellt werden — bitte versuche es erneut.",
        "ja": "❌ アカウントを作成できませんでした — もう一度お試しください。",
        "ko": "❌ 계정을 만들 수 없습니다 — 다시 시도해 주세요.",
        "id": "❌ Tidak dapat membuat akun — silakan coba lagi.",
    },
    "login_confirm_failed": {
        "en": "❌ Couldn't confirm login. Please try again from the site.",
        "ru": "❌ Не удалось подтвердить вход. Попробуйте ещё раз с сайта.",
        "es": "❌ No se pudo confirmar el inicio de sesión. Intenta de nuevo desde el sitio.",
        "zh": "❌ 无法确认登录。请从网站重试。",
        "fr": "❌ Impossible de confirmer la connexion. Veuillez réessayer depuis le site.",
        "de": "❌ Anmeldung konnte nicht bestätigt werden. Bitte erneut auf der Website versuchen.",
        "ja": "❌ ログインを確認できませんでした。サイトからもう一度お試しください。",
        "ko": "❌ 로그인을 확인할 수 없습니다. 사이트에서 다시 시도해 주세요.",
        "id": "❌ Tidak dapat mengonfirmasi masuk. Silakan coba lagi dari situs.",
    },
}

_SUPPORTED = ("en", "ru", "es", "zh", "fr", "de", "ja", "ko", "id")


def tmsg(key: str, lang: str) -> str:
    """Return the localized message for the given key/lang. Falls back to EN."""
    lang = (lang or "en").lower()[:2]
    if lang not in _SUPPORTED:
        lang = "en"
    catalog = _MESSAGES.get(key) or {}
    return catalog.get(lang) or catalog.get("en") or ""


async def resolve_bot_language(db, chat_id: str) -> str:
    """Pick the best language for a bot message. Users who never chose one in
    the bot get English (per product spec)."""
    if not chat_id:
        return "en"
    try:
        tg_map = await db.telegram_mappings.find_one(
            {"chat_id": str(chat_id)}, {"language": 1, "_id": 0}
        )
        lang = (tg_map or {}).get("language")
        if lang in _SUPPORTED:
            return lang
    except Exception:
        pass
    # Fallback: the account's own site language (in case the user picked one
    # on the website but never opened the bot).
    try:
        user = await db.users.find_one(
            {
                "$or": [
                    {"telegram_chat_id": str(chat_id)},
                    {"telegram_id": str(chat_id)},
                ]
            },
            {"language": 1, "_id": 0},
        )
        ulang = (user or {}).get("language")
        if ulang in _SUPPORTED:
            return ulang
    except Exception:
        pass
    return "en"


async def send_bot_message(chat_id: str, text: str) -> bool:
    """Best-effort send. Never raises."""
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token or not chat_id or not text:
        return False
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                f"{TELEGRAM_API_BASE}/bot{token}/sendMessage",
                json={
                    "chat_id": str(chat_id),
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status == 200:
                    return True
                logger.warning("[tg_notify] sendMessage HTTP %s", r.status)
    except Exception as e:
        logger.warning("[tg_notify] sendMessage failed: %s", e)
    return False


async def notify_link_event(db, chat_id: str, event: str, lang: Optional[str] = None) -> bool:
    """Send a link/unlink notification to `chat_id`. `event` ∈ {"linked", "unlinked"}."""
    if not chat_id:
        return False
    _lang = lang or await resolve_bot_language(db, str(chat_id))
    text = tmsg(event, _lang)
    if not text:
        return False
    return await send_bot_message(str(chat_id), text)
