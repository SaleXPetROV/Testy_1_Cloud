"""Тексты Telegram-бота на 9 языках для блоков, которые раньше были только ru/en."""
from core.notif_i18n import norm_lang

T = {
    "welcome_linked": {
        "en": "🏙️ <b>GRAM City</b>\n\nWelcome back, <b>{name}!</b>\n\n💰 Balance: <b>{ton} TON</b> ({city} $CITY){ref}",
        "ru": "🏙️ <b>GRAM City</b>\n\nДобро пожаловать, <b>{name}!</b>\n\n💰 Баланс: <b>{ton} TON</b> ({city} $CITY){ref}",
        "es": "🏙️ <b>GRAM City</b>\n\n¡Bienvenido de nuevo, <b>{name}!</b>\n\n💰 Saldo: <b>{ton} TON</b> ({city} $CITY){ref}",
        "zh": "🏙️ <b>GRAM City</b>\n\n欢迎回来，<b>{name}!</b>\n\n💰 余额：<b>{ton} TON</b>（{city} $CITY）{ref}",
        "fr": "🏙️ <b>GRAM City</b>\n\nBon retour, <b>{name} !</b>\n\n💰 Solde : <b>{ton} TON</b> ({city} $CITY){ref}",
        "de": "🏙️ <b>GRAM City</b>\n\nWillkommen zurück, <b>{name}!</b>\n\n💰 Guthaben: <b>{ton} TON</b> ({city} $CITY){ref}",
        "ja": "🏙️ <b>GRAM City</b>\n\nおかえりなさい、<b>{name}!</b>\n\n💰 残高：<b>{ton} TON</b>（{city} $CITY）{ref}",
        "ko": "🏙️ <b>GRAM City</b>\n\n다시 오신 것을 환영합니다, <b>{name}!</b>\n\n💰 잔액: <b>{ton} TON</b> ({city} $CITY){ref}",
        "id": "🏙️ <b>GRAM City</b>\n\nSelamat datang kembali, <b>{name}!</b>\n\n💰 Saldo: <b>{ton} TON</b> ({city} $CITY){ref}",
    },
    "welcome_new": {
        "en": "🌆 <b>Welcome to Gram City!</b>\n\nHi, <b>{name}</b>! I'm your personal in-game assistant.\n\nTo start building your empire and receive notifications about profit, business and important events, take two simple steps:\n\n1️⃣ <b>Sign up on the website</b>\n2️⃣ <b>Link Telegram:</b> Dashboard → Settings → Telegram\n\nOnce you do this, I'll send you income reports and important game alerts right here! 🚀",
        "ru": "🌆 <b>Добро пожаловать в Gram City!</b>\n\nПривет, <b>{name}</b>! Я — твой персональный помощник в игре.\n\nЧтобы начать строить свою империю и получать уведомления о прибыли, бизнесе и важных событиях, сделай два простых шага:\n\n1️⃣ <b>Зарегистрируйся на сайте</b>\n2️⃣ <b>Привяжи Telegram:</b> Личный кабинет → «Настройки» → «Telegram»\n\nКак только ты это сделаешь, я буду присылать тебе отчёты о доходах и важные игровые оповещения прямо сюда! 🚀",
        "es": "🌆 <b>¡Bienvenido a Gram City!</b>\n\n¡Hola, <b>{name}</b>! Soy tu asistente personal en el juego.\n\nPara empezar a construir tu imperio y recibir notificaciones sobre ganancias, negocios y eventos importantes, sigue dos pasos:\n\n1️⃣ <b>Regístrate en el sitio web</b>\n2️⃣ <b>Vincula Telegram:</b> Panel → Ajustes → Telegram\n\n¡Después te enviaré informes de ingresos y alertas importantes del juego aquí mismo! 🚀",
        "zh": "🌆 <b>欢迎来到 Gram City！</b>\n\n你好，<b>{name}</b>！我是你的游戏私人助手。\n\n要开始建立你的帝国并接收关于收益、企业和重要事件的通知，只需两步：\n\n1️⃣ <b>在网站注册</b>\n2️⃣ <b>绑定 Telegram：</b>个人中心 → 设置 → Telegram\n\n完成后，我会在这里向你发送收入报告和重要游戏提醒！🚀",
        "fr": "🌆 <b>Bienvenue à Gram City !</b>\n\nSalut, <b>{name}</b> ! Je suis ton assistant personnel dans le jeu.\n\nPour commencer à bâtir ton empire et recevoir des notifications sur les profits, les entreprises et les événements importants, fais deux étapes simples :\n\n1️⃣ <b>Inscris-toi sur le site</b>\n2️⃣ <b>Lie Telegram :</b> Tableau de bord → Paramètres → Telegram\n\nEnsuite je t'enverrai ici les rapports de revenus et les alertes importantes ! 🚀",
        "de": "🌆 <b>Willkommen in Gram City!</b>\n\nHallo, <b>{name}</b>! Ich bin dein persönlicher Assistent im Spiel.\n\nUm dein Imperium aufzubauen und Benachrichtigungen über Gewinne, Unternehmen und wichtige Ereignisse zu erhalten, mach zwei einfache Schritte:\n\n1️⃣ <b>Registriere dich auf der Website</b>\n2️⃣ <b>Verknüpfe Telegram:</b> Dashboard → Einstellungen → Telegram\n\nDanach schicke ich dir Einnahmenberichte und wichtige Spiel-Hinweise direkt hierher! 🚀",
        "ja": "🌆 <b>Gram City へようこそ！</b>\n\nこんにちは、<b>{name}</b>！私はゲーム内のパーソナルアシスタントです。\n\n帝国の建設を始め、収益・ビジネス・重要イベントの通知を受け取るには、2つの簡単なステップを行ってください：\n\n1️⃣ <b>サイトで登録</b>\n2️⃣ <b>Telegram を連携：</b>ダッシュボード → 設定 → Telegram\n\n完了すると、収入レポートと重要なゲーム通知をここに送ります！🚀",
        "ko": "🌆 <b>Gram City에 오신 것을 환영합니다!</b>\n\n안녕하세요, <b>{name}</b>! 저는 게임 내 개인 도우미입니다.\n\n제국을 건설하고 수익, 사업, 중요한 이벤트 알림을 받으려면 두 단계를 진행하세요:\n\n1️⃣ <b>웹사이트에서 가입</b>\n2️⃣ <b>Telegram 연결:</b> 대시보드 → 설정 → Telegram\n\n완료하면 수입 보고서와 중요한 게임 알림을 여기로 보내드립니다! 🚀",
        "id": "🌆 <b>Selamat datang di Gram City!</b>\n\nHai, <b>{name}</b>! Saya asisten pribadi Anda di dalam game.\n\nUntuk mulai membangun kerajaan Anda dan menerima notifikasi tentang keuntungan, bisnis, dan acara penting, lakukan dua langkah mudah:\n\n1️⃣ <b>Daftar di situs web</b>\n2️⃣ <b>Hubungkan Telegram:</b> Dasbor → Pengaturan → Telegram\n\nSetelah itu saya akan mengirim laporan pendapatan dan peringatan penting langsung ke sini! 🚀",
    },
    "friend": {"en": "friend", "ru": "друг", "es": "amigo", "zh": "朋友", "fr": "ami", "de": "Freund", "ja": "友達", "ko": "친구", "id": "teman"},
    "btn_settings": {"en": "⚙️ Settings", "ru": "⚙️ Настройки", "es": "⚙️ Ajustes", "zh": "⚙️ 设置", "fr": "⚙️ Paramètres", "de": "⚙️ Einstellungen", "ja": "⚙️ 設定", "ko": "⚙️ 설정", "id": "⚙️ Pengaturan"},
    "btn_help": {"en": "❓ Help", "ru": "❓ Помощь", "es": "❓ Ayuda", "zh": "❓ 帮助", "fr": "❓ Aide", "de": "❓ Hilfe", "ja": "❓ ヘルプ", "ko": "❓ 도움말", "id": "❓ Bantuan"},
    "btn_open_game": {"en": "🎮 Open Game", "ru": "🎮 Открыть игру", "es": "🎮 Abrir juego", "zh": "🎮 打开游戏", "fr": "🎮 Ouvrir le jeu", "de": "🎮 Spiel öffnen", "ja": "🎮 ゲームを開く", "ko": "🎮 게임 열기", "id": "🎮 Buka game"},
    "btn_back": {"en": "◀️ Back", "ru": "◀️ Назад", "es": "◀️ Atrás", "zh": "◀️ 返回", "fr": "◀️ Retour", "de": "◀️ Zurück", "ja": "◀️ 戻る", "ko": "◀️ 뒤로", "id": "◀️ Kembali"},
    "how_to_link": {
        "en": "🔗 <b>How to link Telegram to your GRAM City account:</b>\n\n1️⃣ Go to the GRAM City website\n2️⃣ Log in to your account\n3️⃣ Open <b>Settings</b> → <b>Telegram</b>\n4️⃣ Tap <b>«Link Telegram»</b>\n5️⃣ This bot opens — done!\n\nAfter linking you will receive notifications about:\n• 💰 Deposits and withdrawals\n• 🏢 Business income\n• 📢 Important announcements",
        "ru": "🔗 <b>Как привязать Telegram к аккаунту GRAM City:</b>\n\n1️⃣ Зайдите на сайт GRAM City\n2️⃣ Войдите в свой аккаунт\n3️⃣ Откройте <b>Настройки</b> → <b>Telegram</b>\n4️⃣ Нажмите <b>«Привязать Telegram»</b>\n5️⃣ Откроется этот бот — готово!\n\nПосле привязки вы будете получать уведомления о:\n• 💰 Пополнениях и выводах\n• 🏢 Доходах от бизнесов\n• 📢 Важных объявлениях",
        "es": "🔗 <b>Cómo vincular Telegram a tu cuenta de GRAM City:</b>\n\n1️⃣ Entra en el sitio de GRAM City\n2️⃣ Inicia sesión\n3️⃣ Abre <b>Ajustes</b> → <b>Telegram</b>\n4️⃣ Pulsa <b>«Vincular Telegram»</b>\n5️⃣ Se abrirá este bot — ¡listo!\n\nDespués recibirás notificaciones sobre:\n• 💰 Depósitos y retiros\n• 🏢 Ingresos de negocios\n• 📢 Anuncios importantes",
        "zh": "🔗 <b>如何将 Telegram 绑定到 GRAM City 账号：</b>\n\n1️⃣ 打开 GRAM City 网站\n2️⃣ 登录账号\n3️⃣ 打开<b>设置</b> → <b>Telegram</b>\n4️⃣ 点击<b>«绑定 Telegram»</b>\n5️⃣ 会打开此机器人 — 完成！\n\n绑定后您将收到以下通知：\n• 💰 充值与提现\n• 🏢 企业收入\n• 📢 重要公告",
        "fr": "🔗 <b>Comment lier Telegram à votre compte GRAM City :</b>\n\n1️⃣ Allez sur le site GRAM City\n2️⃣ Connectez-vous\n3️⃣ Ouvrez <b>Paramètres</b> → <b>Telegram</b>\n4️⃣ Appuyez sur <b>«Lier Telegram»</b>\n5️⃣ Ce bot s'ouvre — c'est fait !\n\nAprès la liaison vous recevrez des notifications sur :\n• 💰 Dépôts et retraits\n• 🏢 Revenus des entreprises\n• 📢 Annonces importantes",
        "de": "🔗 <b>So verknüpfst du Telegram mit deinem GRAM-City-Konto:</b>\n\n1️⃣ Öffne die GRAM-City-Website\n2️⃣ Melde dich an\n3️⃣ Öffne <b>Einstellungen</b> → <b>Telegram</b>\n4️⃣ Tippe auf <b>«Telegram verknüpfen»</b>\n5️⃣ Dieser Bot öffnet sich — fertig!\n\nDanach erhältst du Benachrichtigungen über:\n• 💰 Ein- und Auszahlungen\n• 🏢 Unternehmenseinnahmen\n• 📢 Wichtige Ankündigungen",
        "ja": "🔗 <b>Telegram を GRAM City アカウントに連携する方法：</b>\n\n1️⃣ GRAM City のサイトを開く\n2️⃣ ログイン\n3️⃣ <b>設定</b> → <b>Telegram</b> を開く\n4️⃣ <b>«Telegram を連携»</b> をタップ\n5️⃣ このボットが開きます — 完了！\n\n連携後、次の通知を受け取れます：\n• 💰 入金と出金\n• 🏢 ビジネス収入\n• 📢 重要なお知らせ",
        "ko": "🔗 <b>Telegram을 GRAM City 계정에 연결하는 방법:</b>\n\n1️⃣ GRAM City 웹사이트 접속\n2️⃣ 로그인\n3️⃣ <b>설정</b> → <b>Telegram</b> 열기\n4️⃣ <b>«Telegram 연결»</b> 누르기\n5️⃣ 이 봇이 열립니다 — 완료!\n\n연결 후 다음 알림을 받습니다:\n• 💰 입금 및 출금\n• 🏢 사업 수입\n• 📢 중요 공지",
        "id": "🔗 <b>Cara menghubungkan Telegram ke akun GRAM City:</b>\n\n1️⃣ Buka situs GRAM City\n2️⃣ Masuk ke akun Anda\n3️⃣ Buka <b>Pengaturan</b> → <b>Telegram</b>\n4️⃣ Ketuk <b>«Hubungkan Telegram»</b>\n5️⃣ Bot ini akan terbuka — selesai!\n\nSetelah terhubung Anda akan menerima notifikasi tentang:\n• 💰 Deposit dan penarikan\n• 🏢 Pendapatan bisnis\n• 📢 Pengumuman penting",
    },
    "section_not_found": {"en": "Section not found", "ru": "Раздел не найден", "es": "Sección no encontrada", "zh": "未找到该部分", "fr": "Section introuvable", "de": "Abschnitt nicht gefunden", "ja": "セクションが見つかりません", "ko": "섹션을 찾을 수 없습니다", "id": "Bagian tidak ditemukan"},
    "help_plots": {"en": "Plots & auction", "ru": "Участки и аукцион", "es": "Parcelas y subasta", "zh": "地块与拍卖", "fr": "Parcelles et enchères", "de": "Grundstücke & Auktion", "ja": "区画とオークション", "ko": "부지 및 경매", "id": "Lahan & lelang"},
    "help_businesses": {"en": "My businesses", "ru": "Мои бизнесы", "es": "Mis negocios", "zh": "我的企业", "fr": "Mes entreprises", "de": "Meine Unternehmen", "ja": "マイビジネス", "ko": "내 사업", "id": "Bisnis saya"},
    "help_market": {"en": "Market & prices", "ru": "Рынок и цены", "es": "Mercado y precios", "zh": "市场与价格", "fr": "Marché et prix", "de": "Markt & Preise", "ja": "マーケットと価格", "ko": "마켓 및 가격", "id": "Pasar & harga"},
    "help_alliances": {"en": "Alliances & patrons", "ru": "Альянсы и патроны", "es": "Alianzas y patrones", "zh": "联盟与赞助人", "fr": "Alliances et patrons", "de": "Allianzen & Patrone", "ja": "同盟とパトロン", "ko": "동맹 및 패트론", "id": "Aliansi & patron"},
    "help_buffs": {"en": "Tier-3 buffs", "ru": "Баффы T3", "es": "Mejoras Tier-3", "zh": "三级增益", "fr": "Buffs Tier-3", "de": "Tier-3-Buffs", "ja": "Tier-3 バフ", "ko": "3티어 버프", "id": "Buff Tier-3"},
    "help_wallet": {"en": "Wallet & withdrawals", "ru": "Кошелёк и вывод", "es": "Cartera y retiros", "zh": "钱包与提现", "fr": "Portefeuille et retraits", "de": "Wallet & Auszahlungen", "ja": "ウォレットと出金", "ko": "지갑 및 출금", "id": "Dompet & penarikan"},
    "help_settings": {"en": "Settings & Telegram", "ru": "Настройки и Telegram", "es": "Ajustes y Telegram", "zh": "设置与 Telegram", "fr": "Paramètres et Telegram", "de": "Einstellungen & Telegram", "ja": "設定と Telegram", "ko": "설정 및 Telegram", "id": "Pengaturan & Telegram"},
    "help_admin": {"en": "Admin panel", "ru": "Админ-панель", "es": "Panel de admin", "zh": "管理面板", "fr": "Panneau admin", "de": "Admin-Panel", "ja": "管理パネル", "ko": "관리자 패널", "id": "Panel admin"},
}


def bt(key: str, lang: str, **vars_) -> str:
    d = T.get(key, {})
    s = d.get(norm_lang(lang)) or d.get("en") or key
    if vars_:
        try:
            s = s.format(**vars_)
        except (KeyError, IndexError, ValueError):
            for k, v in vars_.items():
                s = s.replace("{" + k + "}", str(v))
    return s
