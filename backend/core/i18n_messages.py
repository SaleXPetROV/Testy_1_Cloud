"""Localized user-facing messages for withdrawal flows (9 project languages).

Usage:
    from core.i18n_messages import wmsg
    raise HTTPException(status_code=400, detail=wmsg(user_lang, "enable_2fa"))
    detail=wmsg(lang, "insufficient_funds", balance=1.23, frozen=0, available=1.23)

Falls back to English for unknown languages / keys.
"""
from typing import Any

SUPPORTED = ("en", "ru", "es", "zh", "fr", "de", "ja", "ko", "id")

WITHDRAW_MESSAGES = {
    "user_not_found": {
        "en": "User not found",
        "ru": "Пользователь не найден",
        "es": "Usuario no encontrado",
        "zh": "未找到用户",
        "fr": "Utilisateur introuvable",
        "de": "Benutzer nicht gefunden",
        "ja": "ユーザーが見つかりません",
        "ko": "사용자를 찾을 수 없습니다",
        "id": "Pengguna tidak ditemukan",
    },
    "withdrawal_blocked": {
        "en": "Withdrawals are blocked. Please contact support to resolve this.",
        "ru": "Вывод средств заблокирован. Для решения вопроса обратитесь в поддержку.",
        "es": "Los retiros están bloqueados. Contacta con soporte para resolverlo.",
        "zh": "提现已被冻结。请联系客服解决此问题。",
        "fr": "Les retraits sont bloqués. Veuillez contacter le support pour résoudre ce problème.",
        "de": "Auszahlungen sind gesperrt. Bitte wende dich an den Support.",
        "ja": "出金がブロックされています。解決するにはサポートにお問い合わせください。",
        "ko": "출금이 차단되었습니다. 해결하려면 고객지원에 문의하세요.",
        "id": "Penarikan diblokir. Silakan hubungi dukungan untuk menyelesaikannya.",
    },
    "enable_2fa": {
        "en": "To withdraw funds you must enable 2FA authentication in security settings",
        "ru": "Для вывода средств необходимо включить 2FA аутентификацию в настройках безопасности",
        "es": "Para retirar fondos debes activar la autenticación 2FA en los ajustes de seguridad",
        "zh": "提现前，请在安全设置中启用双重验证（2FA）",
        "fr": "Pour retirer des fonds, vous devez activer l'authentification 2FA dans les paramètres de sécurité",
        "de": "Um Geld abzuheben, musst du die 2FA-Authentifizierung in den Sicherheitseinstellungen aktivieren",
        "ja": "出金するには、セキュリティ設定で2FA認証を有効にする必要があります",
        "ko": "출금하려면 보안 설정에서 2FA 인증을 활성화해야 합니다",
        "id": "Untuk menarik dana, Anda harus mengaktifkan autentikasi 2FA di pengaturan keamanan",
    },
    "enter_2fa": {
        "en": "Enter the 2FA code to confirm the withdrawal",
        "ru": "Введите код 2FA для подтверждения вывода",
        "es": "Introduce el código 2FA para confirmar el retiro",
        "zh": "请输入 2FA 验证码以确认提现",
        "fr": "Saisissez le code 2FA pour confirmer le retrait",
        "de": "Gib den 2FA-Code ein, um die Auszahlung zu bestätigen",
        "ja": "出金を確認するには2FAコードを入力してください",
        "ko": "출금을 확인하려면 2FA 코드를 입력하세요",
        "id": "Masukkan kode 2FA untuk mengonfirmasi penarikan",
    },
    "invalid_2fa": {
        "en": "Invalid 2FA code",
        "ru": "Неверный код 2FA",
        "es": "Código 2FA incorrecto",
        "zh": "2FA 验证码错误",
        "fr": "Code 2FA invalide",
        "de": "Ungültiger 2FA-Code",
        "ja": "2FAコードが正しくありません",
        "ko": "잘못된 2FA 코드입니다",
        "id": "Kode 2FA tidak valid",
    },
    "connect_wallet": {
        "en": "Connect a wallet to withdraw funds",
        "ru": "Подключите кошелёк для вывода средств",
        "es": "Conecta una billetera para retirar fondos",
        "zh": "请连接钱包以提现",
        "fr": "Connectez un portefeuille pour retirer des fonds",
        "de": "Verbinde eine Wallet, um Geld abzuheben",
        "ja": "出金するにはウォレットを接続してください",
        "ko": "출금하려면 지갑을 연결하세요",
        "id": "Hubungkan dompet untuk menarik dana",
    },
    "invalid_amount": {
        "en": "Invalid amount",
        "ru": "Некорректная сумма",
        "es": "Cantidad no válida",
        "zh": "金额无效",
        "fr": "Montant invalide",
        "de": "Ungültiger Betrag",
        "ja": "金額が無効です",
        "ko": "잘못된 금액입니다",
        "id": "Jumlah tidak valid",
    },
    "insufficient_funds": {
        "en": "Insufficient funds. Balance: {balance:.4f} TON, frozen in contracts: {frozen:.4f} TON, available to withdraw: {available:.4f} TON",
        "ru": "Недостаточно средств. Баланс: {balance:.4f} TON, заморожено в контрактах: {frozen:.4f} TON, доступно к выводу: {available:.4f} TON",
        "es": "Fondos insuficientes. Saldo: {balance:.4f} TON, congelado en contratos: {frozen:.4f} TON, disponible para retirar: {available:.4f} TON",
        "zh": "余额不足。余额：{balance:.4f} TON，合约冻结：{frozen:.4f} TON，可提现：{available:.4f} TON",
        "fr": "Fonds insuffisants. Solde : {balance:.4f} TON, gelé dans les contrats : {frozen:.4f} TON, disponible au retrait : {available:.4f} TON",
        "de": "Unzureichendes Guthaben. Kontostand: {balance:.4f} TON, in Verträgen eingefroren: {frozen:.4f} TON, verfügbar zur Auszahlung: {available:.4f} TON",
        "ja": "残高が不足しています。残高：{balance:.4f} TON、契約でロック：{frozen:.4f} TON、出金可能：{available:.4f} TON",
        "ko": "잔액이 부족합니다. 잔액: {balance:.4f} TON, 계약에 잠김: {frozen:.4f} TON, 출금 가능: {available:.4f} TON",
        "id": "Dana tidak cukup. Saldo: {balance:.4f} TON, dibekukan dalam kontrak: {frozen:.4f} TON, tersedia untuk ditarik: {available:.4f} TON",
    },
    "min_withdrawal": {
        "en": "Minimum withdrawal amount: {min_amount} TON",
        "ru": "Минимальная сумма вывода: {min_amount} TON",
        "es": "Monto mínimo de retiro: {min_amount} TON",
        "zh": "最低提现金额：{min_amount} TON",
        "fr": "Montant minimum de retrait : {min_amount} TON",
        "de": "Mindestauszahlungsbetrag: {min_amount} TON",
        "ja": "最低出金額：{min_amount} TON",
        "ko": "최소 출금 금액: {min_amount} TON",
        "id": "Jumlah penarikan minimum: {min_amount} TON",
    },
    "insufficient_simple": {
        "en": "Insufficient funds",
        "ru": "Недостаточно средств",
        "es": "Fondos insuficientes",
        "zh": "余额不足",
        "fr": "Fonds insuffisants",
        "de": "Unzureichendes Guthaben",
        "ja": "残高が不足しています",
        "ko": "잔액이 부족합니다",
        "id": "Dana tidak cukup",
    },
    "bank_not_selected": {
        "en": "No bank selected",
        "ru": "Банк не выбран",
        "es": "No se ha seleccionado ningún banco",
        "zh": "未选择银行",
        "fr": "Aucune banque sélectionnée",
        "de": "Keine Bank ausgewählt",
        "ja": "銀行が選択されていません",
        "ko": "은행이 선택되지 않았습니다",
        "id": "Belum ada bank yang dipilih",
    },
    "not_a_bank": {
        "en": "This is not a bank",
        "ru": "Это не банк",
        "es": "Esto no es un banco",
        "zh": "这不是银行",
        "fr": "Ceci n'est pas une banque",
        "de": "Das ist keine Bank",
        "ja": "これは銀行ではありません",
        "ko": "은행이 아닙니다",
        "id": "Ini bukan bank",
    },
    "bank_durability_low": {
        "en": "Bank durability is below 50%",
        "ru": "Прочность банка ниже 50%",
        "es": "La durabilidad del banco es inferior al 50%",
        "zh": "银行耐久度低于 50%",
        "fr": "La durabilité de la banque est inférieure à 50 %",
        "de": "Die Haltbarkeit der Bank liegt unter 50 %",
        "ja": "銀行の耐久度が50%未満です",
        "ko": "은행 내구도가 50% 미만입니다",
        "id": "Ketahanan bank di bawah 50%",
    },
    "bank_error": {
        "en": "Bank error",
        "ru": "Ошибка банка",
        "es": "Error del banco",
        "zh": "银行错误",
        "fr": "Erreur de banque",
        "de": "Bankfehler",
        "ja": "銀行エラー",
        "ko": "은행 오류",
        "id": "Kesalahan bank",
    },
}


def _norm_lang(lang: Any) -> str:
    l = (str(lang or "en")).lower()[:2]
    return l if l in SUPPORTED else "en"


def wmsg(lang: Any, key: str, **fmt: Any) -> str:
    """Return a localized message for `key` in `lang`, formatted with **fmt."""
    entry = WITHDRAW_MESSAGES.get(key)
    if not entry:
        return key
    l = _norm_lang(lang)
    template = entry.get(l) or entry.get("en") or key
    if fmt:
        try:
            return template.format(**fmt)
        except Exception:
            return template
    return template
