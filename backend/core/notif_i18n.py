"""Локализация уведомлений (in-app + Telegram) на 9 языков проекта.

    from core.notif_i18n import user_lang, render, label
    title, message = render("deposit", lang, amount="1.2500")
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

LANGS = ("en", "ru", "es", "zh", "fr", "de", "ja", "ko", "id")
DEFAULT_LANG = "en"


def norm_lang(lang: Optional[str]) -> str:
    l = (lang or "").strip().lower()[:2]
    return l if l in LANGS else DEFAULT_LANG


def user_lang(user_doc: Optional[dict]) -> str:
    return norm_lang((user_doc or {}).get("language"))


# key -> lang -> (title, message). Плейсхолдеры подставляются через str.format.
NOTIF: Dict[str, Dict[str, Tuple[str, str]]] = {
    "land_purchase": {
        "en": ("Plot purchased", "You bought plot ({x}, {y}) for {price} TON. You can now build a business on it."),
        "ru": ("Участок куплен", "Вы приобрели участок ({x}, {y}) за {price} TON. Теперь можно построить бизнес."),
        "es": ("Parcela comprada", "Has comprado la parcela ({x}, {y}) por {price} TON. Ahora puedes construir un negocio."),
        "zh": ("地块已购买", "您以 {price} TON 购买了地块 ({x}, {y})。现在可以在上面建造企业。"),
        "fr": ("Parcelle achetée", "Vous avez acheté la parcelle ({x}, {y}) pour {price} TON. Vous pouvez maintenant y construire une entreprise."),
        "de": ("Grundstück gekauft", "Du hast das Grundstück ({x}, {y}) für {price} TON gekauft. Jetzt kannst du ein Unternehmen bauen."),
        "ja": ("区画を購入しました", "区画 ({x}, {y}) を {price} TON で購入しました。ビジネスを建設できます。"),
        "ko": ("부지 구매 완료", "부지 ({x}, {y})를 {price} TON에 구매했습니다. 이제 사업을 건설할 수 있습니다."),
        "id": ("Lahan dibeli", "Anda membeli lahan ({x}, {y}) seharga {price} TON. Sekarang Anda bisa membangun bisnis."),
    },
    "business_build": {
        "en": ("Business built", "You built «{name}» on plot ({x}, {y}). It will start generating income."),
        "ru": ("Бизнес построен", "Вы построили «{name}» на участке ({x}, {y}). Бизнес начнёт приносить доход."),
        "es": ("Negocio construido", "Has construido «{name}» en la parcela ({x}, {y}). Empezará a generar ingresos."),
        "zh": ("企业已建成", "您在地块 ({x}, {y}) 上建造了«{name}»。它将开始产生收入。"),
        "fr": ("Entreprise construite", "Vous avez construit «{name}» sur la parcelle ({x}, {y}). Elle commencera à générer des revenus."),
        "de": ("Unternehmen gebaut", "Du hast «{name}» auf Grundstück ({x}, {y}) gebaut. Es beginnt, Einnahmen zu erzielen."),
        "ja": ("ビジネスを建設しました", "区画 ({x}, {y}) に «{name}» を建設しました。収益を生み始めます。"),
        "ko": ("사업 건설 완료", "부지 ({x}, {y})에 «{name}»을(를) 건설했습니다. 수익이 발생하기 시작합니다."),
        "id": ("Bisnis dibangun", "Anda membangun «{name}» di lahan ({x}, {y}). Bisnis akan mulai menghasilkan."),
    },
    "withdrawal_pending": {
        "en": ("📤 Withdrawal request created", "✅ Your withdrawal request for <b>{amount} TON</b> has been accepted.\n\n⏳ You will be notified once it is processed by the administrator."),
        "ru": ("📤 Заявка на вывод создана", "✅ Ваша заявка на вывод <b>{amount} TON</b> принята.\n\n⏳ Вы получите уведомление после обработки администратором."),
        "es": ("📤 Solicitud de retiro creada", "✅ Tu solicitud de retiro de <b>{amount} TON</b> ha sido aceptada.\n\n⏳ Recibirás una notificación cuando el administrador la procese."),
        "zh": ("📤 提现申请已创建", "✅ 您的 <b>{amount} TON</b> 提现申请已受理。\n\n⏳ 管理员处理后您将收到通知。"),
        "fr": ("📤 Demande de retrait créée", "✅ Votre demande de retrait de <b>{amount} TON</b> a été acceptée.\n\n⏳ Vous serez notifié après traitement par l'administrateur."),
        "de": ("📤 Auszahlungsantrag erstellt", "✅ Dein Auszahlungsantrag über <b>{amount} TON</b> wurde angenommen.\n\n⏳ Du wirst benachrichtigt, sobald der Administrator ihn bearbeitet hat."),
        "ja": ("📤 出金申請を作成しました", "✅ <b>{amount} TON</b> の出金申請を受け付けました。\n\n⏳ 管理者の処理後に通知します。"),
        "ko": ("📤 출금 요청 생성됨", "✅ <b>{amount} TON</b> 출금 요청이 접수되었습니다.\n\n⏳ 관리자가 처리하면 알림을 받게 됩니다."),
        "id": ("📤 Permintaan penarikan dibuat", "✅ Permintaan penarikan <b>{amount} TON</b> Anda diterima.\n\n⏳ Anda akan diberi tahu setelah diproses oleh administrator."),
    },
    "withdrawal_approved": {
        "en": ("✅ Withdrawal approved", "💸 Your withdrawal request for <b>{amount} TON</b> has been approved and sent to your wallet.{tx_line}"),
        "ru": ("✅ Вывод одобрен", "💸 Ваш запрос на вывод <b>{amount} TON</b> одобрен и отправлен на ваш кошелёк.{tx_line}"),
        "es": ("✅ Retiro aprobado", "💸 Tu solicitud de retiro de <b>{amount} TON</b> fue aprobada y enviada a tu billetera.{tx_line}"),
        "zh": ("✅ 提现已批准", "💸 您的 <b>{amount} TON</b> 提现申请已批准并发送至您的钱包。{tx_line}"),
        "fr": ("✅ Retrait approuvé", "💸 Votre demande de retrait de <b>{amount} TON</b> a été approuvée et envoyée sur votre portefeuille.{tx_line}"),
        "de": ("✅ Auszahlung genehmigt", "💸 Dein Auszahlungsantrag über <b>{amount} TON</b> wurde genehmigt und an deine Wallet gesendet.{tx_line}"),
        "ja": ("✅ 出金が承認されました", "💸 <b>{amount} TON</b> の出金申請が承認され、ウォレットに送金されました。{tx_line}"),
        "ko": ("✅ 출금 승인됨", "💸 <b>{amount} TON</b> 출금 요청이 승인되어 지갑으로 전송되었습니다.{tx_line}"),
        "id": ("✅ Penarikan disetujui", "💸 Permintaan penarikan <b>{amount} TON</b> Anda disetujui dan dikirim ke dompet Anda.{tx_line}"),
    },
    "withdrawal_rejected": {
        "en": ("❌ Withdrawal rejected", "💰 Your withdrawal request for <b>{amount} TON</b> was rejected by the administrator.\n\n↩️ The funds have been returned to your balance."),
        "ru": ("❌ Вывод отклонён", "💰 Ваш запрос на вывод <b>{amount} TON</b> отклонён администратором.\n\n↩️ Средства возвращены на ваш баланс."),
        "es": ("❌ Retiro rechazado", "💰 Tu solicitud de retiro de <b>{amount} TON</b> fue rechazada por el administrador.\n\n↩️ Los fondos han sido devueltos a tu saldo."),
        "zh": ("❌ 提现被拒绝", "💰 您的 <b>{amount} TON</b> 提现申请已被管理员拒绝。\n\n↩️ 资金已退回您的余额。"),
        "fr": ("❌ Retrait refusé", "💰 Votre demande de retrait de <b>{amount} TON</b> a été refusée par l'administrateur.\n\n↩️ Les fonds ont été recrédités sur votre solde."),
        "de": ("❌ Auszahlung abgelehnt", "💰 Dein Auszahlungsantrag über <b>{amount} TON</b> wurde vom Administrator abgelehnt.\n\n↩️ Das Guthaben wurde deinem Konto zurückerstattet."),
        "ja": ("❌ 出金が拒否されました", "💰 <b>{amount} TON</b> の出金申請は管理者により拒否されました。\n\n↩️ 資金は残高に返却されました。"),
        "ko": ("❌ 출금 거부됨", "💰 <b>{amount} TON</b> 출금 요청이 관리자에 의해 거부되었습니다.\n\n↩️ 자금이 잔액으로 반환되었습니다."),
        "id": ("❌ Penarikan ditolak", "💰 Permintaan penarikan <b>{amount} TON</b> Anda ditolak oleh administrator.\n\n↩️ Dana telah dikembalikan ke saldo Anda."),
    },
    "deposit": {
        "en": ("💰 Balance topped up", "✅ <b>{amount} TON</b> has been credited to your balance.{tx_line}"),
        "ru": ("💰 Баланс пополнен", "✅ На ваш баланс зачислено <b>{amount} TON</b>.{tx_line}"),
        "es": ("💰 Saldo recargado", "✅ Se han acreditado <b>{amount} TON</b> en tu saldo.{tx_line}"),
        "zh": ("💰 余额已充值", "✅ <b>{amount} TON</b> 已存入您的余额。{tx_line}"),
        "fr": ("💰 Solde rechargé", "✅ <b>{amount} TON</b> ont été crédités sur votre solde.{tx_line}"),
        "de": ("💰 Guthaben aufgeladen", "✅ <b>{amount} TON</b> wurden deinem Guthaben gutgeschrieben.{tx_line}"),
        "ja": ("💰 残高が入金されました", "✅ <b>{amount} TON</b> が残高に入金されました。{tx_line}"),
        "ko": ("💰 잔액 충전 완료", "✅ <b>{amount} TON</b>이(가) 잔액에 입금되었습니다.{tx_line}"),
        "id": ("💰 Saldo terisi", "✅ <b>{amount} TON</b> telah dikreditkan ke saldo Anda.{tx_line}"),
    },
    "low_durability": {
        "en": ("⚠️ Business wear warning", "🏢 <b>{biz}</b>\n📉 Durability: <b>{durability}%</b>\n\nYour business now produces only <b>80%</b> of its output. Repair it to restore full performance.\n\n🔧 Open «My Businesses» → «Repair»"),
        "ru": ("⚠️ Внимание! Износ бизнеса", "🏢 <b>{biz}</b>\n📉 Прочность: <b>{durability}%</b>\n\nВаш бизнес производит только <b>80%</b> ресурсов! Проведите ремонт для восстановления производительности.\n\n🔧 Откройте «Мои бизнесы» → «Ремонт»"),
        "es": ("⚠️ Desgaste del negocio", "🏢 <b>{biz}</b>\n📉 Durabilidad: <b>{durability}%</b>\n\nTu negocio produce solo el <b>80%</b>. Repáralo para recuperar el rendimiento.\n\n🔧 Abre «Mis negocios» → «Reparar»"),
        "zh": ("⚠️ 企业磨损警告", "🏢 <b>{biz}</b>\n📉 耐久度：<b>{durability}%</b>\n\n您的企业目前只有 <b>80%</b> 的产量。请维修以恢复全部性能。\n\n🔧 打开«我的企业» → «维修»"),
        "fr": ("⚠️ Usure de l'entreprise", "🏢 <b>{biz}</b>\n📉 Durabilité : <b>{durability}%</b>\n\nVotre entreprise ne produit plus que <b>80%</b>. Réparez-la pour retrouver sa pleine performance.\n\n🔧 Ouvrez «Mes entreprises» → «Réparer»"),
        "de": ("⚠️ Verschleiß des Unternehmens", "🏢 <b>{biz}</b>\n📉 Haltbarkeit: <b>{durability}%</b>\n\nDein Unternehmen produziert nur noch <b>80%</b>. Repariere es, um die volle Leistung wiederherzustellen.\n\n🔧 Öffne «Meine Unternehmen» → «Reparieren»"),
        "ja": ("⚠️ ビジネスの劣化", "🏢 <b>{biz}</b>\n📉 耐久度：<b>{durability}%</b>\n\n生産量が <b>80%</b> に低下しています。修理して性能を回復してください。\n\n🔧 «マイビジネス» → «修理» を開く"),
        "ko": ("⚠️ 사업 마모 경고", "🏢 <b>{biz}</b>\n📉 내구도: <b>{durability}%</b>\n\n사업 생산량이 <b>80%</b>로 감소했습니다. 수리하여 성능을 회복하세요.\n\n🔧 «내 사업» → «수리» 열기"),
        "id": ("⚠️ Peringatan keausan bisnis", "🏢 <b>{biz}</b>\n📉 Ketahanan: <b>{durability}%</b>\n\nBisnis Anda hanya memproduksi <b>80%</b>. Perbaiki untuk memulihkan kinerja penuh.\n\n🔧 Buka «Bisnis Saya» → «Perbaiki»"),
    },
    "durability_20": {
        "en": ("⚠️ Durability below 20%!", "🏢 <b>{biz}</b>\n📉 Durability: <b>{durability}%</b>\n\nA little more and the business may <b>stop</b> (0% = full production halt). Urgent repair recommended.\n\n🔧 Open «My Businesses» → «Repair»"),
        "ru": ("⚠️ Прочность бизнеса ниже 20%!", "🏢 <b>{biz}</b>\n📉 Прочность: <b>{durability}%</b>\n\nЕщё немного — и бизнес может <b>остановиться</b> (0% = полная остановка). Рекомендуем <b>срочный ремонт</b>.\n\n🔧 Откройте «Мои бизнесы» → «Ремонт»"),
        "es": ("⚠️ ¡Durabilidad por debajo del 20%!", "🏢 <b>{biz}</b>\n📉 Durabilidad: <b>{durability}%</b>\n\nUn poco más y el negocio puede <b>detenerse</b> (0% = parada total). Se recomienda reparación urgente.\n\n🔧 Abre «Mis negocios» → «Reparar»"),
        "zh": ("⚠️ 耐久度低于 20%！", "🏢 <b>{biz}</b>\n📉 耐久度：<b>{durability}%</b>\n\n再降一点企业就可能<b>停产</b>（0% = 完全停止）。建议紧急维修。\n\n🔧 打开«我的企业» → «维修»"),
        "fr": ("⚠️ Durabilité sous 20% !", "🏢 <b>{biz}</b>\n📉 Durabilité : <b>{durability}%</b>\n\nEncore un peu et l'entreprise peut <b>s'arrêter</b> (0% = arrêt total). Réparation urgente recommandée.\n\n🔧 Ouvrez «Mes entreprises» → «Réparer»"),
        "de": ("⚠️ Haltbarkeit unter 20%!", "🏢 <b>{biz}</b>\n📉 Haltbarkeit: <b>{durability}%</b>\n\nBald könnte das Unternehmen <b>stillstehen</b> (0% = kompletter Stopp). Dringende Reparatur empfohlen.\n\n🔧 Öffne «Meine Unternehmen» → «Reparieren»"),
        "ja": ("⚠️ 耐久度が 20% 未満です！", "🏢 <b>{biz}</b>\n📉 耐久度：<b>{durability}%</b>\n\nこのままではビジネスが<b>停止</b>する恐れがあります（0% = 完全停止）。早急な修理をおすすめします。\n\n🔧 «マイビジネス» → «修理» を開く"),
        "ko": ("⚠️ 내구도 20% 미만!", "🏢 <b>{biz}</b>\n📉 내구도: <b>{durability}%</b>\n\n조금 더 떨어지면 사업이 <b>중단</b>될 수 있습니다 (0% = 완전 중단). 긴급 수리를 권장합니다.\n\n🔧 «내 사업» → «수리» 열기"),
        "id": ("⚠️ Ketahanan di bawah 20%!", "🏢 <b>{biz}</b>\n📉 Ketahanan: <b>{durability}%</b>\n\nSedikit lagi bisnis bisa <b>berhenti</b> (0% = berhenti total). Perbaikan segera disarankan.\n\n🔧 Buka «Bisnis Saya» → «Perbaiki»"),
    },
    "critical_durability": {
        "en": ("🚨 CRITICAL WEAR!", "🏢 <b>{biz}</b>\n📉 Durability: <b>{durability}%</b>\n\n⚠️ Your business is in critical condition!\n<b>Repair it immediately!</b>\n\n🔧 Open «My Businesses» → «Repair»"),
        "ru": ("🚨 КРИТИЧЕСКИЙ ИЗНОС!", "🏢 <b>{biz}</b>\n📉 Прочность: <b>{durability}%</b>\n\n⚠️ Ваш бизнес в критическом состоянии!\n<b>Срочно проведите ремонт!</b>\n\n🔧 Откройте «Мои бизнесы» → «Ремонт»"),
        "es": ("🚨 ¡DESGASTE CRÍTICO!", "🏢 <b>{biz}</b>\n📉 Durabilidad: <b>{durability}%</b>\n\n⚠️ ¡Tu negocio está en estado crítico!\n<b>¡Repáralo de inmediato!</b>\n\n🔧 Abre «Mis negocios» → «Reparar»"),
        "zh": ("🚨 严重磨损！", "🏢 <b>{biz}</b>\n📉 耐久度：<b>{durability}%</b>\n\n⚠️ 您的企业处于危急状态！\n<b>请立即维修！</b>\n\n🔧 打开«我的企业» → «维修»"),
        "fr": ("🚨 USURE CRITIQUE !", "🏢 <b>{biz}</b>\n📉 Durabilité : <b>{durability}%</b>\n\n⚠️ Votre entreprise est dans un état critique !\n<b>Réparez-la immédiatement !</b>\n\n🔧 Ouvrez «Mes entreprises» → «Réparer»"),
        "de": ("🚨 KRITISCHER VERSCHLEISS!", "🏢 <b>{biz}</b>\n📉 Haltbarkeit: <b>{durability}%</b>\n\n⚠️ Dein Unternehmen ist in kritischem Zustand!\n<b>Sofort reparieren!</b>\n\n🔧 Öffne «Meine Unternehmen» → «Reparieren»"),
        "ja": ("🚨 深刻な劣化！", "🏢 <b>{biz}</b>\n📉 耐久度：<b>{durability}%</b>\n\n⚠️ ビジネスが危機的状態です！\n<b>今すぐ修理してください！</b>\n\n🔧 «マイビジネス» → «修理» を開く"),
        "ko": ("🚨 심각한 마모!", "🏢 <b>{biz}</b>\n📉 내구도: <b>{durability}%</b>\n\n⚠️ 사업이 위험한 상태입니다!\n<b>즉시 수리하세요!</b>\n\n🔧 «내 사업» → «수리» 열기"),
        "id": ("🚨 KEAUSAN KRITIS!", "🏢 <b>{biz}</b>\n📉 Ketahanan: <b>{durability}%</b>\n\n⚠️ Bisnis Anda dalam kondisi kritis!\n<b>Segera perbaiki!</b>\n\n🔧 Buka «Bisnis Saya» → «Perbaiki»"),
    },
    "business_stopped": {
        "en": ("🛑 BUSINESS STOPPED", "🏢 <b>{biz}</b>\n📉 Durability: <b>0%</b>\n\n❌ Production has completely stopped!\nA <b>full repair</b> is required to resume.\n\n🔧 Open «My Businesses» → «Full repair»"),
        "ru": ("🛑 БИЗНЕС ПРИОСТАНОВЛЕН", "🏢 <b>{biz}</b>\n📉 Прочность: <b>0%</b>\n\n❌ Производство полностью остановлено!\nДля возобновления необходим <b>полный ремонт</b>.\n\n🔧 Откройте «Мои бизнесы» → «Полный ремонт»"),
        "es": ("🛑 NEGOCIO DETENIDO", "🏢 <b>{biz}</b>\n📉 Durabilidad: <b>0%</b>\n\n❌ ¡La producción se ha detenido por completo!\nSe requiere una <b>reparación completa</b>.\n\n🔧 Abre «Mis negocios» → «Reparación completa»"),
        "zh": ("🛑 企业已停产", "🏢 <b>{biz}</b>\n📉 耐久度：<b>0%</b>\n\n❌ 生产已完全停止！\n需要<b>全面维修</b>才能恢复。\n\n🔧 打开«我的企业» → «全面维修»"),
        "fr": ("🛑 ENTREPRISE ARRÊTÉE", "🏢 <b>{biz}</b>\n📉 Durabilité : <b>0%</b>\n\n❌ La production est totalement arrêtée !\nUne <b>réparation complète</b> est nécessaire.\n\n🔧 Ouvrez «Mes entreprises» → «Réparation complète»"),
        "de": ("🛑 UNTERNEHMEN GESTOPPT", "🏢 <b>{biz}</b>\n📉 Haltbarkeit: <b>0%</b>\n\n❌ Die Produktion ist vollständig gestoppt!\nEine <b>Komplettreparatur</b> ist erforderlich.\n\n🔧 Öffne «Meine Unternehmen» → «Komplettreparatur»"),
        "ja": ("🛑 ビジネス停止", "🏢 <b>{biz}</b>\n📉 耐久度：<b>0%</b>\n\n❌ 生産が完全に停止しました！\n再開には<b>完全修理</b>が必要です。\n\n🔧 «マイビジネス» → «完全修理» を開く"),
        "ko": ("🛑 사업 중단", "🏢 <b>{biz}</b>\n📉 내구도: <b>0%</b>\n\n❌ 생산이 완전히 중단되었습니다!\n재개하려면 <b>전체 수리</b>가 필요합니다.\n\n🔧 «내 사업» → «전체 수리» 열기"),
        "id": ("🛑 BISNIS BERHENTI", "🏢 <b>{biz}</b>\n📉 Ketahanan: <b>0%</b>\n\n❌ Produksi berhenti total!\nDiperlukan <b>perbaikan penuh</b> untuk melanjutkan.\n\n🔧 Buka «Bisnis Saya» → «Perbaikan penuh»"),
    },
    "resources_full": {
        "en": ("📦 Resources piled up!", "{res}: <b>{amount}</b> units.\n\n💡 Sell them on the marketplace while the price is good!\n\n🛒 Open «Marketplace» → «Sell resources»"),
        "ru": ("📦 Ресурсы накопились!", "{res}: <b>{amount}</b> ед.\n\n💡 Рекомендуем продать ресурсы на маркетплейсе, пока цена выгодная!\n\n🛒 Откройте «Маркетплейс» → «Продать ресурсы»"),
        "es": ("📦 ¡Recursos acumulados!", "{res}: <b>{amount}</b> unidades.\n\n💡 ¡Véndelos en el mercado mientras el precio es bueno!\n\n🛒 Abre «Mercado» → «Vender recursos»"),
        "zh": ("📦 资源已积累！", "{res}：<b>{amount}</b> 单位。\n\n💡 趁价格合适在市场上出售吧！\n\n🛒 打开«市场» → «出售资源»"),
        "fr": ("📦 Ressources accumulées !", "{res} : <b>{amount}</b> unités.\n\n💡 Vendez-les sur le marché pendant que le prix est bon !\n\n🛒 Ouvrez «Marché» → «Vendre des ressources»"),
        "de": ("📦 Ressourcen angesammelt!", "{res}: <b>{amount}</b> Einheiten.\n\n💡 Verkaufe sie auf dem Marktplatz, solange der Preis gut ist!\n\n🛒 Öffne «Marktplatz» → «Ressourcen verkaufen»"),
        "ja": ("📦 資源が溜まりました！", "{res}：<b>{amount}</b> 個。\n\n💡 価格が良いうちにマーケットで売却しましょう！\n\n🛒 «マーケット» → «資源を売る» を開く"),
        "ko": ("📦 자원이 쌓였습니다!", "{res}: <b>{amount}</b>개.\n\n💡 가격이 좋을 때 마켓에서 판매하세요!\n\n🛒 «마켓» → «자원 판매» 열기"),
        "id": ("📦 Sumber daya menumpuk!", "{res}: <b>{amount}</b> unit.\n\n💡 Jual di pasar selagi harganya bagus!\n\n🛒 Buka «Pasar» → «Jual sumber daya»"),
    },
    "business_sold": {
        "en": ("💰 Your business has been sold!", "🏢 <b>{biz}</b>\n\n💵 Received: <b>+{amount} TON</b>\n📋 Tax: {tax} TON\n\nThe funds have been credited to your balance."),
        "ru": ("💰 Ваш бизнес продан!", "🏢 <b>{biz}</b>\n\n💵 Получено: <b>+{amount} TON</b>\n📋 Налог: {tax} TON\n\nСредства зачислены на ваш баланс."),
        "es": ("💰 ¡Tu negocio se ha vendido!", "🏢 <b>{biz}</b>\n\n💵 Recibido: <b>+{amount} TON</b>\n📋 Impuesto: {tax} TON\n\nLos fondos se han acreditado en tu saldo."),
        "zh": ("💰 您的企业已售出！", "🏢 <b>{biz}</b>\n\n💵 收到：<b>+{amount} TON</b>\n📋 税费：{tax} TON\n\n资金已存入您的余额。"),
        "fr": ("💰 Votre entreprise a été vendue !", "🏢 <b>{biz}</b>\n\n💵 Reçu : <b>+{amount} TON</b>\n📋 Taxe : {tax} TON\n\nLes fonds ont été crédités sur votre solde."),
        "de": ("💰 Dein Unternehmen wurde verkauft!", "🏢 <b>{biz}</b>\n\n💵 Erhalten: <b>+{amount} TON</b>\n📋 Steuer: {tax} TON\n\nDas Guthaben wurde deinem Konto gutgeschrieben."),
        "ja": ("💰 ビジネスが売却されました！", "🏢 <b>{biz}</b>\n\n💵 受取：<b>+{amount} TON</b>\n📋 税：{tax} TON\n\n資金は残高に入金されました。"),
        "ko": ("💰 사업이 판매되었습니다!", "🏢 <b>{biz}</b>\n\n💵 수령: <b>+{amount} TON</b>\n📋 세금: {tax} TON\n\n자금이 잔액에 입금되었습니다."),
        "id": ("💰 Bisnis Anda terjual!", "🏢 <b>{biz}</b>\n\n💵 Diterima: <b>+{amount} TON</b>\n📋 Pajak: {tax} TON\n\nDana telah dikreditkan ke saldo Anda."),
    },
    "credit_overdue": {
        "en": ("Credit overdue", "Your credit is overdue! The rate has been doubled. Repay {remaining} TON."),
        "ru": ("Кредит просрочен", "Кредит просрочен! Ставка удвоена. Погасите долг {remaining} TON."),
        "es": ("Crédito vencido", "¡Tu crédito está vencido! La tasa se ha duplicado. Paga {remaining} TON."),
        "zh": ("贷款逾期", "您的贷款已逾期！利率已翻倍。请偿还 {remaining} TON。"),
        "fr": ("Crédit en retard", "Votre crédit est en retard ! Le taux a été doublé. Remboursez {remaining} TON."),
        "de": ("Kredit überfällig", "Dein Kredit ist überfällig! Der Zinssatz wurde verdoppelt. Zahle {remaining} TON zurück."),
        "ja": ("ローン延滞", "ローンが延滞しています！金利が2倍になりました。{remaining} TON を返済してください。"),
        "ko": ("대출 연체", "대출이 연체되었습니다! 이율이 두 배가 되었습니다. {remaining} TON을 상환하세요."),
        "id": ("Kredit jatuh tempo", "Kredit Anda jatuh tempo! Bunga digandakan. Bayar {remaining} TON."),
    },
    "business_seized": {
        "en": ("Business seized", "Your business has been seized for non-payment of the credit! Lender: {lender}."),
        "ru": ("Бизнес конфискован", "Ваш бизнес конфискован за неуплату кредита! Кредитор: {lender}."),
        "es": ("Negocio embargado", "¡Tu negocio ha sido embargado por impago del crédito! Prestamista: {lender}."),
        "zh": ("企业被没收", "您的企业因未偿还贷款被没收！贷款方：{lender}。"),
        "fr": ("Entreprise saisie", "Votre entreprise a été saisie pour non-remboursement du crédit ! Prêteur : {lender}."),
        "de": ("Unternehmen beschlagnahmt", "Dein Unternehmen wurde wegen nicht bezahltem Kredit beschlagnahmt! Kreditgeber: {lender}."),
        "ja": ("ビジネスが差し押さえられました", "ローン未払いのためビジネスが差し押さえられました！貸主：{lender}。"),
        "ko": ("사업 압류", "대출 미납으로 사업이 압류되었습니다! 대출자: {lender}."),
        "id": ("Bisnis disita", "Bisnis Anda disita karena kredit tidak dibayar! Pemberi pinjaman: {lender}."),
    },
    "warehouse_spoilage": {
        "en": ("Warehouse overflow", "Your warehouse is overflowing! {spoilage} units of goods were spoiled."),
        "ru": ("Склад переполнен", "Склад переполнен! Испорчено {spoilage} единиц товара."),
        "es": ("Almacén desbordado", "¡Tu almacén está desbordado! Se estropearon {spoilage} unidades."),
        "zh": ("仓库溢出", "您的仓库已满！{spoilage} 单位货物已损坏。"),
        "fr": ("Entrepôt saturé", "Votre entrepôt est saturé ! {spoilage} unités ont été perdues."),
        "de": ("Lager überfüllt", "Dein Lager ist überfüllt! {spoilage} Einheiten sind verdorben."),
        "ja": ("倉庫が満杯", "倉庫が満杯です！{spoilage} 個の商品が傷みました。"),
        "ko": ("창고 초과", "창고가 넘쳤습니다! {spoilage}개의 물품이 손상되었습니다."),
        "id": ("Gudang penuh", "Gudang Anda penuh! {spoilage} unit barang rusak."),
    },
    "patron_buff_update": {
        "en": ("Patron updated the buff", "{buff}"),
        "ru": ("Патрон обновил бафф", "{buff}"),
        "es": ("El patrón actualizó el buff", "{buff}"),
        "zh": ("赞助人更新了增益", "{buff}"),
        "fr": ("Le patron a mis à jour le buff", "{buff}"),
        "de": ("Patron hat den Buff aktualisiert", "{buff}"),
        "ja": ("パトロンがバフを更新しました", "{buff}"),
        "ko": ("패트론이 버프를 갱신했습니다", "{buff}"),
        "id": ("Patron memperbarui buff", "{buff}"),
    },
    "low_res_hours_n": {
        "en": ("Resources running low!", "⚠️ {biz}: «{res}» will last ~{h} h ({hl} left)"),
        "ru": ("Заканчиваются ресурсы!", "⚠️ {biz}: «{res}» хватит примерно на {h} ч (осталось {hl})"),
        "es": ("¡Se agotan los recursos!", "⚠️ {biz}: «{res}» durará ~{h} h (quedan {hl})"),
        "zh": ("资源即将耗尽！", "⚠️ {biz}：«{res}» 约可维持 {h} 小时（剩余 {hl}）"),
        "fr": ("Ressources presque épuisées !", "⚠️ {biz} : «{res}» durera ~{h} h (reste {hl})"),
        "de": ("Ressourcen werden knapp!", "⚠️ {biz}: «{res}» reicht noch ~{h} Std. ({hl} übrig)"),
        "ja": ("資源が不足しています！", "⚠️ {biz}：«{res}» は約 {h} 時間分（残り {hl}）"),
        "ko": ("자원이 부족합니다!", "⚠️ {biz}: «{res}» 약 {h}시간 남음 (잔여 {hl})"),
        "id": ("Sumber daya menipis!", "⚠️ {biz}: «{res}» cukup untuk ~{h} jam (sisa {hl})"),
    },
    "low_res_hours_1": {
        "en": ("Resources running low!", "⚠️ {biz}: «{res}» will last less than 30 minutes ({hl} left)"),
        "ru": ("Заканчиваются ресурсы!", "⚠️ {biz}: «{res}» хватит менее чем на 30 минут (осталось {hl})"),
        "es": ("¡Se agotan los recursos!", "⚠️ {biz}: «{res}» durará menos de 30 minutos (quedan {hl})"),
        "zh": ("资源即将耗尽！", "⚠️ {biz}：«{res}» 不足 30 分钟（剩余 {hl}）"),
        "fr": ("Ressources presque épuisées !", "⚠️ {biz} : «{res}» durera moins de 30 minutes (reste {hl})"),
        "de": ("Ressourcen werden knapp!", "⚠️ {biz}: «{res}» reicht weniger als 30 Minuten ({hl} übrig)"),
        "ja": ("資源が不足しています！", "⚠️ {biz}：«{res}» は30分未満（残り {hl}）"),
        "ko": ("자원이 부족합니다!", "⚠️ {biz}: «{res}» 30분 미만 남음 (잔여 {hl})"),
        "id": ("Sumber daya menipis!", "⚠️ {biz}: «{res}» kurang dari 30 menit (sisa {hl})"),
    },
    "low_res_stopped": {
        "en": ("Business stopped!", "🛑 {biz} stopped: out of «{res}»"),
        "ru": ("Бизнес остановлен!", "🛑 {biz} остановлен: закончился ресурс «{res}»"),
        "es": ("¡Negocio detenido!", "🛑 {biz} detenido: se agotó «{res}»"),
        "zh": ("企业已停产！", "🛑 {biz} 已停产：«{res}» 耗尽"),
        "fr": ("Entreprise arrêtée !", "🛑 {biz} arrêtée : plus de «{res}»"),
        "de": ("Unternehmen gestoppt!", "🛑 {biz} gestoppt: «{res}» aufgebraucht"),
        "ja": ("ビジネス停止！", "🛑 {biz} が停止：«{res}» が不足"),
        "ko": ("사업 중단!", "🛑 {biz} 중단: «{res}» 소진"),
        "id": ("Bisnis berhenti!", "🛑 {biz} berhenti: «{res}» habis"),
    },
    "zero_business_lost": {
        "en": ("Level-0 business bought out", "Your level-0 business «{biz}» was bought out by another player. You can claim a new one on the map."),
        "ru": ("Бизнес 0 уровня выкуплен", "Ваш бизнес 0 уровня «{biz}» выкупил другой игрок. Вы можете застолбить новый на карте."),
        "es": ("Negocio de nivel 0 comprado", "Otro jugador compró tu negocio de nivel 0 «{biz}». Puedes reclamar uno nuevo en el mapa."),
        "zh": ("0 级企业被买走", "您的 0 级企业«{biz}»被其他玩家买走。您可以在地图上领取新的。"),
        "fr": ("Entreprise niveau 0 rachetée", "Votre entreprise niveau 0 «{biz}» a été rachetée par un autre joueur. Vous pouvez en réclamer une nouvelle sur la carte."),
        "de": ("Level-0-Unternehmen aufgekauft", "Dein Level-0-Unternehmen «{biz}» wurde von einem anderen Spieler gekauft. Du kannst ein neues auf der Karte beanspruchen."),
        "ja": ("レベル0ビジネスが買収されました", "レベル0のビジネス «{biz}» が他のプレイヤーに買収されました。マップで新しいものを確保できます。"),
        "ko": ("0레벨 사업 매수됨", "0레벨 사업 «{biz}»이(가) 다른 플레이어에게 매수되었습니다. 지도에서 새로 확보할 수 있습니다."),
        "id": ("Bisnis level 0 dibeli", "Bisnis level 0 Anda «{biz}» dibeli pemain lain. Anda bisa mengklaim yang baru di peta."),
    },
    # ── Аренда тестового бизнеса 0-го уровня: предупреждение за 12 часов ──
    "zero_lease_expiring": {
        "en": ("⏳ Test business lease expires soon", "The lease of your test business «{biz}» expires in {hours} hours! Upgrade it to level 1 to keep it forever."),
        "ru": ("⏳ Срок аренды бизнеса истекает", "Срок аренды тестового бизнеса «{biz}» истекает через {hours} часов! Прокачайте бизнес до 1-го уровня, чтобы сохранить его навсегда."),
        "es": ("⏳ La prueba del negocio caduca pronto", "¡El alquiler de tu negocio de prueba «{biz}» caduca en {hours} horas! Mejóralo a nivel 1 para conservarlo para siempre."),
        "zh": ("⏳ 测试企业租期即将到期", "您的测试企业«{biz}»租期将在 {hours} 小时后到期！升级到 1 级即可永久保留。"),
        "fr": ("⏳ La location de l'entreprise expire bientôt", "La location de votre entreprise d'essai «{biz}» expire dans {hours} heures ! Améliorez-la au niveau 1 pour la garder pour toujours."),
        "de": ("⏳ Testunternehmen-Miete läuft bald ab", "Die Miete deines Testunternehmens «{biz}» läuft in {hours} Stunden ab! Bringe es auf Stufe 1, um es dauerhaft zu behalten."),
        "ja": ("⏳ お試しビジネスの期限が近づいています", "お試しビジネス «{biz}» の期限があと {hours} 時間で切れます！レベル1にアップグレードすると永久に保持できます。"),
        "ko": ("⏳ 체험 사업 임대 만료 임박", "체험 사업 «{biz}»의 임대가 {hours}시간 후 만료됩니다! 레벨 1로 업그레이드하면 영구히 보유할 수 있습니다."),
        "id": ("⏳ Sewa bisnis uji coba segera berakhir", "Sewa bisnis uji coba «{biz}» Anda berakhir dalam {hours} jam! Tingkatkan ke level 1 untuk menyimpannya selamanya."),
    },
    # ── Аренда тестового бизнеса завершена: поле снова свободно ──
    "zero_lease_expired": {
        "en": ("🏢 Business lease ended", "The lease of your test business «{biz}» has ended. The plot is free again."),
        "ru": ("🏢 Срок аренды бизнеса завершён", "Срок аренды тестового бизнеса «{biz}» завершён. Поле снова свободно."),
        "es": ("🏢 El alquiler del negocio ha terminado", "El alquiler de tu negocio de prueba «{biz}» ha terminado. La parcela está libre de nuevo."),
        "zh": ("🏢 企业租期已结束", "您的测试企业«{biz}»租期已结束。地块再次空闲。"),
        "fr": ("🏢 La location de l'entreprise est terminée", "La location de votre entreprise d'essai «{biz}» est terminée. La parcelle est de nouveau libre."),
        "de": ("🏢 Unternehmensmiete beendet", "Die Miete deines Testunternehmens «{biz}» ist beendet. Das Grundstück ist wieder frei."),
        "ja": ("🏢 ビジネスの期限が終了しました", "お試しビジネス «{biz}» の期限が終了しました。区画は再び空きになりました。"),
        "ko": ("🏢 사업 임대 종료", "체험 사업 «{biz}»의 임대가 종료되었습니다. 부지가 다시 비어 있습니다."),
        "id": ("🏢 Sewa bisnis berakhir", "Sewa bisnis uji coba «{biz}» Anda telah berakhir. Lahan kembali kosong."),
    },
    # ── Лот на рынке пролежал 48 часов → возврат на склад ──
    "market_lot_returned": {
        "en": ("📦 Your goods are back in storage!", "The lot «{res} (x{amount})» stayed on the market for 48 hours and found no buyer.\n💡 Tip from City Hall: the price may have been too high! Try listing it 10–15% cheaper to quickly get $CITY flowing."),
        "ru": ("📦 Ваш товар вернулся на склад!", "Лот «{res} (x{amount})» пролежал на рынке 48 часов и не нашёл покупателя.\n💡 Совет от мэрии: похоже, цена была слишком высока! Попробуйте выставить товар со скидкой 10–15% от прежней цены, чтобы быстро получить $CITY в оборот."),
        "es": ("📦 ¡Tus productos han vuelto al almacén!", "El lote «{res} (x{amount})» estuvo 48 horas en el mercado y no encontró comprador.\n💡 Consejo del ayuntamiento: ¡quizá el precio era muy alto! Prueba a listarlo un 10–15% más barato para conseguir $CITY rápido."),
        "zh": ("📦 您的商品已退回仓库！", "货物«{res} (x{amount})»在市场上停留了 48 小时仍未售出。\n💡 市政厅提示：价格可能太高了！试试降价 10–15% 出售，快速回笼 $CITY。"),
        "fr": ("📦 Vos marchandises sont de retour en stock !", "Le lot «{res} (x{amount})» est resté 48 heures sur le marché sans trouver d'acheteur.\n💡 Conseil de la mairie : le prix était peut-être trop élevé ! Essayez de le remettre 10–15 % moins cher pour récupérer du $CITY rapidement."),
        "de": ("📦 Deine Waren sind zurück im Lager!", "Das Los «{res} (x{amount})» lag 48 Stunden auf dem Markt und fand keinen Käufer.\n💡 Tipp vom Rathaus: Der Preis war vielleicht zu hoch! Versuche es 10–15 % günstiger, um schnell $CITY zu bekommen."),
        "ja": ("📦 商品が倉庫に戻りました！", "ロット «{res} (x{amount})» は48時間市場に出ていましたが買い手が見つかりませんでした。\n💡 市庁舎からの助言：価格が高すぎたかもしれません！10〜15%値下げして出品し、素早く $CITY を回しましょう。"),
        "ko": ("📦 상품이 창고로 돌아왔습니다!", "«{res} (x{amount})» 로트가 48시간 동안 시장에 있었지만 구매자를 찾지 못했습니다.\n💡 시청의 조언: 가격이 너무 높았을 수 있어요! 10~15% 저렴하게 다시 올려 빠르게 $CITY를 확보하세요."),
        "id": ("📦 Barang Anda kembali ke gudang!", "Lot «{res} (x{amount})» berada di pasar selama 48 jam dan tidak menemukan pembeli.\n💡 Saran dari balai kota: mungkin harganya terlalu tinggi! Coba pasang 10–15% lebih murah agar $CITY cepat berputar."),
    },
    # ── Бонус за завершение обучения ──
    "tutorial_bonus": {
        "en": ("🎁 Tutorial reward", "Congratulations on finishing the tutorial! We've credited <b>{amount} TON</b> to your bonus balance."),
        "ru": ("🎁 Награда за обучение", "Поздравляем с завершением обучения! Мы начислили <b>{amount} TON</b> на ваш бонусный баланс."),
        "es": ("🎁 Recompensa del tutorial", "¡Felicidades por terminar el tutorial! Hemos acreditado <b>{amount} TON</b> en tu saldo de bonificación."),
        "zh": ("🎁 教程奖励", "恭喜您完成教程！我们已向您的奖励余额发放 <b>{amount} TON</b>。"),
        "fr": ("🎁 Récompense du tutoriel", "Félicitations pour avoir terminé le tutoriel ! Nous avons crédité <b>{amount} TON</b> sur votre solde bonus."),
        "de": ("🎁 Tutorial-Belohnung", "Glückwunsch zum Abschluss des Tutorials! Wir haben <b>{amount} TON</b> deinem Bonusguthaben gutgeschrieben."),
        "ja": ("🎁 チュートリアル報酬", "チュートリアル完了おめでとうございます！ボーナス残高に <b>{amount} TON</b> を付与しました。"),
        "ko": ("🎁 튜토리얼 보상", "튜토리얼 완료를 축하합니다! 보너스 잔액에 <b>{amount} TON</b>을(를) 지급했습니다."),
        "id": ("🎁 Hadiah tutorial", "Selamat telah menyelesaikan tutorial! Kami telah mengkreditkan <b>{amount} TON</b> ke saldo bonus Anda."),
    },
    # ── Бизнес изъят за неуплату кредита ──
    "business_seized_credit": {
        "en": ("⚖️ Business seized for loan default", "Your business «{biz}» was seized by GRAM CITY due to an unpaid loan and put up for sale for {price} TON. The outstanding debt is repaid first from the sale; the rest goes to you."),
        "ru": ("⚖️ Бизнес изъят за неуплату кредита", "Ваш бизнес «{biz}» изъят GRAM CITY за непогашенный кредит и выставлен на продажу за {price} TON. Из вырученной суммы сначала погашается долг, остаток поступает вам."),
        "es": ("⚖️ Negocio embargado por impago del préstamo", "Tu negocio «{biz}» fue embargado por GRAM CITY por un préstamo impago y puesto a la venta por {price} TON. La deuda pendiente se paga primero; el resto es para ti."),
        "zh": ("⚖️ 因贷款违约企业被没收", "您的企业«{biz}»因未偿还贷款被 GRAM CITY 没收，并以 {price} TON 挂牌出售。出售款项先偿还欠款，余额归您。"),
        "fr": ("⚖️ Entreprise saisie pour défaut de prêt", "Votre entreprise «{biz}» a été saisie par GRAM CITY pour un prêt impayé et mise en vente pour {price} TON. La dette est d'abord remboursée ; le reste vous revient."),
        "de": ("⚖️ Unternehmen wegen Kreditausfalls beschlagnahmt", "Dein Unternehmen «{biz}» wurde von GRAM CITY wegen eines unbezahlten Kredits beschlagnahmt und für {price} TON zum Verkauf gestellt. Die Restschuld wird zuerst getilgt; der Rest geht an dich."),
        "ja": ("⚖️ ローン滞納によりビジネスが差し押さえられました", "あなたのビジネス «{biz}» は未払いローンのため GRAM CITY に差し押さえられ、{price} TON で売りに出されました。売却額はまず債務の返済に充てられ、残りはあなたに渡ります。"),
        "ko": ("⚖️ 대출 미상환으로 사업이 압류됨", "당신의 사업 «{biz}»이(가) 미상환 대출로 인해 GRAM CITY에 압류되어 {price} TON에 판매 등록되었습니다. 판매 대금은 먼저 부채 상환에 쓰이고 나머지는 당신에게 지급됩니다."),
        "id": ("⚖️ Bisnis disita karena gagal bayar pinjaman", "Bisnis «{biz}» Anda disita oleh GRAM CITY karena pinjaman belum dibayar dan dijual seharga {price} TON. Sisa utang dilunasi lebih dulu; sisanya untuk Anda."),
    },
    # ── Бизнес изъят: прочность держалась на 0 в течение 7 дней ──
    "business_seized_durability": {
        "en": ("⚖️ Business seized (durability at 0 for 7 days)", "Your business «{biz}» sat at 0 durability for 7 days and was seized by GRAM CITY, then put up for sale for {price} TON. Proceeds (minus tax) go to you."),
        "ru": ("⚖️ Бизнес изъят (прочность 0 в течение 7 дней)", "Ваш бизнес «{biz}» простоял с нулевой прочностью 7 дней и был изъят GRAM CITY, а затем выставлен на продажу за {price} TON. Вырученные средства (за вычетом налога) поступят вам."),
        "es": ("⚖️ Negocio embargado (durabilidad en 0 durante 7 días)", "Tu negocio «{biz}» estuvo con durabilidad 0 durante 7 días y fue embargado por GRAM CITY, luego puesto a la venta por {price} TON. Los ingresos (menos impuestos) son para ti."),
        "zh": ("⚖️ 企业被没收（耐久度为 0 达 7 天）", "您的企业«{biz}»耐久度为 0 持续 7 天，被 GRAM CITY 没收并以 {price} TON 挂牌出售。所得款项（扣税后）归您。"),
        "fr": ("⚖️ Entreprise saisie (durabilité à 0 pendant 7 jours)", "Votre entreprise «{biz}» est restée à 0 de durabilité pendant 7 jours et a été saisie par GRAM CITY, puis mise en vente pour {price} TON. Le produit (moins la taxe) vous revient."),
        "de": ("⚖️ Unternehmen beschlagnahmt (Haltbarkeit 7 Tage auf 0)", "Dein Unternehmen «{biz}» stand 7 Tage bei 0 Haltbarkeit und wurde von GRAM CITY beschlagnahmt und für {price} TON zum Verkauf gestellt. Der Erlös (abzüglich Steuer) geht an dich."),
        "ja": ("⚖️ ビジネスが差し押さえられました（耐久度0が7日間）", "あなたのビジネス «{biz}» は耐久度0のまま7日間放置され、GRAM CITY に差し押さえられて {price} TON で売りに出されました。売却額（税引後）はあなたに渡ります。"),
        "ko": ("⚖️ 사업 압류됨 (내구도 0으로 7일)", "당신의 사업 «{biz}»이(가) 내구도 0인 상태로 7일간 방치되어 GRAM CITY에 압류되고 {price} TON에 판매 등록되었습니다. 판매 대금(세금 제외)은 당신에게 지급됩니다."),
        "id": ("⚖️ Bisnis disita (daya tahan 0 selama 7 hari)", "Bisnis «{biz}» Anda berada pada daya tahan 0 selama 7 hari dan disita oleh GRAM CITY, lalu dijual seharga {price} TON. Hasilnya (dikurangi pajak) untuk Anda."),
    },
}

# Короткие подписи (кнопки, единицы, ошибки).
LABELS: Dict[str, Dict[str, str]] = {
    "home_button": {"en": "🏠 Main menu", "ru": "🏠 На главную", "es": "🏠 Menú principal", "zh": "🏠 主菜单", "fr": "🏠 Menu principal", "de": "🏠 Hauptmenü", "ja": "🏠 メインメニュー", "ko": "🏠 메인 메뉴", "id": "🏠 Menu utama"},
    "open_app": {"en": "🎮 Open the app", "ru": "🎮 Открыть приложение", "es": "🎮 Abrir la app", "zh": "🎮 打开应用", "fr": "🎮 Ouvrir l'application", "de": "🎮 App öffnen", "ja": "🎮 アプリを開く", "ko": "🎮 앱 열기", "id": "🎮 Buka aplikasi"},
    "tx_button": {"en": "🔗 Transaction", "ru": "🔗 Транзакция", "es": "🔗 Transacción", "zh": "🔗 交易", "fr": "🔗 Transaction", "de": "🔗 Transaktion", "ja": "🔗 トランザクション", "ko": "🔗 트랜잭션", "id": "🔗 Transaksi"},
    "tx_line": {"en": "\n\n🔗 Transaction: <code>{hash}</code>", "ru": "\n\n🔗 Транзакция: <code>{hash}</code>", "es": "\n\n🔗 Transacción: <code>{hash}</code>", "zh": "\n\n🔗 交易：<code>{hash}</code>", "fr": "\n\n🔗 Transaction : <code>{hash}</code>", "de": "\n\n🔗 Transaktion: <code>{hash}</code>", "ja": "\n\n🔗 トランザクション：<code>{hash}</code>", "ko": "\n\n🔗 트랜잭션: <code>{hash}</code>", "id": "\n\n🔗 Transaksi: <code>{hash}</code>"},
    "buy_resources": {"en": "💎 Buy resources", "ru": "💎 Купить ресурсы", "es": "💎 Comprar recursos", "zh": "💎 购买资源", "fr": "💎 Acheter des ressources", "de": "💎 Ressourcen kaufen", "ja": "💎 資源を購入", "ko": "💎 자원 구매", "id": "💎 Beli sumber daya"},
    "low_res_heading": {"en": "⚠️ <b>Resources running low!</b>\n", "ru": "⚠️ <b>Заканчиваются ресурсы!</b>\n", "es": "⚠️ <b>¡Se agotan los recursos!</b>\n", "zh": "⚠️ <b>资源即将耗尽！</b>\n", "fr": "⚠️ <b>Ressources presque épuisées !</b>\n", "de": "⚠️ <b>Ressourcen werden knapp!</b>\n", "ja": "⚠️ <b>資源が不足しています！</b>\n", "ko": "⚠️ <b>자원이 부족합니다!</b>\n", "id": "⚠️ <b>Sumber daya menipis!</b>\n"},
    "low_res_footer": {"en": "\nReplenish your stockpile on the marketplace!", "ru": "\nПополните запасы на маркетплейсе!", "es": "\n¡Repón tus reservas en el mercado!", "zh": "\n请在市场上补充库存！", "fr": "\nReconstituez vos stocks sur le marché !", "de": "\nFülle deine Vorräte auf dem Marktplatz auf!", "ja": "\nマーケットで在庫を補充しましょう！", "ko": "\n마켓에서 재고를 보충하세요!", "id": "\nIsi kembali stok Anda di pasar!"},
    "hour_short": {"en": "h", "ru": "ч", "es": "h", "zh": "小时", "fr": "h", "de": "Std.", "ja": "時間", "ko": "시간", "id": "j"},
    "min_short": {"en": "m", "ru": "мин", "es": "min", "zh": "分钟", "fr": "min", "de": "Min.", "ja": "分", "ko": "분", "id": "mnt"},
    "insufficient_funds": {"en": "Insufficient funds", "ru": "Недостаточно средств", "es": "Fondos insuficientes", "zh": "余额不足", "fr": "Fonds insuffisants", "de": "Unzureichendes Guthaben", "ja": "残高不足", "ko": "잔액 부족", "id": "Saldo tidak cukup"},
    "insufficient_funds_detail": {
        "en": "Insufficient funds: need {need} $CITY, available {have} $CITY (bonus + main balance)",
        "ru": "Недостаточно средств: нужно {need} $CITY, доступно {have} $CITY (бонусный + основной баланс)",
        "es": "Fondos insuficientes: se necesitan {need} $CITY, disponibles {have} $CITY (bono + saldo principal)",
        "zh": "余额不足：需要 {need} $CITY，可用 {have} $CITY（奖励 + 主余额）",
        "fr": "Fonds insuffisants : {need} $CITY requis, {have} $CITY disponibles (bonus + solde principal)",
        "de": "Unzureichendes Guthaben: {need} $CITY benötigt, {have} $CITY verfügbar (Bonus + Hauptguthaben)",
        "ja": "残高不足：必要 {need} $CITY、利用可能 {have} $CITY（ボーナス + メイン残高）",
        "ko": "잔액 부족: 필요 {need} $CITY, 사용 가능 {have} $CITY (보너스 + 기본 잔액)",
        "id": "Saldo tidak cukup: butuh {need} $CITY, tersedia {have} $CITY (bonus + saldo utama)",
    },
}


def label(key: str, lang: Optional[str]) -> str:
    d = LABELS.get(key, {})
    return d.get(norm_lang(lang)) or d.get(DEFAULT_LANG) or key


def _fmt(tpl: str, vars_: Dict[str, Any]) -> str:
    try:
        return tpl.format(**vars_)
    except (KeyError, IndexError, ValueError):
        out = tpl
        for k, v in vars_.items():
            out = out.replace("{" + k + "}", str(v))
        return out


def render(key: str, lang: Optional[str], **vars_: Any) -> Tuple[str, str]:
    """Вернуть (title, message) на языке пользователя. Неизвестный ключ → (key, '')."""
    entry = NOTIF.get(key)
    if not entry:
        return key, ""
    title, message = entry.get(norm_lang(lang)) or entry[DEFAULT_LANG]
    return _fmt(title, vars_), _fmt(message, vars_)


def fmt_hours_left(hours: float, lang: Optional[str]) -> str:
    """«2 ч 15 мин» / «2h 15m» по языку."""
    total_minutes = max(0, int(round(float(hours) * 60)))
    h, m = divmod(total_minutes, 60)
    hs, ms = label("hour_short", lang), label("min_short", lang)
    sep = "" if norm_lang(lang) in ("en", "zh", "ja") else " "
    if h > 0 and m > 0:
        return f"{h}{sep}{hs} {m}{sep}{ms}"
    if h > 0:
        return f"{h}{sep}{hs}"
    return f"{m}{sep}{ms}"
