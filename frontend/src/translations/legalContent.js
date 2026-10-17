// Multilingual legal documents for GRAM-City (Privacy Policy & Terms of Use)
// Languages: en, ru, es, zh, fr, de, ja, ko
// Each text node is an object keyed by language. Rendering is done dynamically
// in PrivacyPage.jsx / TermsPage.jsx via the current UI language.

const LANG_MAP = {
  en: 'en', gb: 'en',
  ru: 'ru',
  es: 'es',
  cn: 'zh', zh: 'zh',
  fr: 'fr',
  de: 'de',
  jp: 'ja', ja: 'ja',
  kr: 'ko', ko: 'ko',
  id: 'id',
};

export const resolveLegalLang = (lang) => LANG_MAP[(lang || 'en').toLowerCase()] || 'en';

export const pickLegal = (node, lang) => {
  if (node == null) return '';
  const l = resolveLegalLang(lang);
  return node[l] != null ? node[l] : (node.en != null ? node.en : '');
};

// ---------------------------------------------------------------------------
// PRIVACY POLICY
// ---------------------------------------------------------------------------
export const privacyDoc = {
  title: {
    en: 'GRAM-City Privacy Policy', id: "Kebijakan Privasi GRAM-City",
    ru: 'Политика конфиденциальности GRAM-City',
    es: 'Política de Privacidad de GRAM-City',
    zh: 'GRAM-City 隐私政策',
    fr: 'Politique de confidentialité de GRAM-City',
    de: 'Datenschutzrichtlinie von GRAM-City',
    ja: 'GRAM-City プライバシーポリシー',
    ko: 'GRAM-City 개인정보 처리방침',
  },
  effectiveDate: {
    en: 'Effective date: March 27, 2026', id: "Tanggal berlaku: 27 Maret 2026",
    ru: 'Дата вступления в силу: 27 марта 2026 г.',
    es: 'Fecha de entrada en vigor: 27 de marzo de 2026',
    zh: '生效日期：2026年3月27日',
    fr: "Date d'entrée en vigueur : 27 mars 2026",
    de: 'Datum des Inkrafttretens: 27. März 2026',
    ja: '発効日：2026年3月27日',
    ko: '시행일: 2026년 3월 27일',
  },
  sections: [
    {
      heading: {
        en: '1. Introduction', id: "1. Pendahuluan", ru: '1. Введение', es: '1. Introducción', zh: '1. 引言',
        fr: '1. Introduction', de: '1. Einführung', ja: '1. はじめに', ko: '1. 소개',
      },
      blocks: [
        { type: 'p', text: {
          en: 'This Privacy Policy describes how GRAM-City (hereinafter "we", "us" or "our") collects, uses and protects the information you provide when using our platform.', id: "Kebijakan Privasi ini menjelaskan bagaimana GRAM-City (selanjutnya disebut \"kami\", \"kita\", atau \"milik kami\") mengumpulkan, menggunakan, dan melindungi informasi yang Anda berikan saat menggunakan platform kami.",
          ru: 'Настоящая Политика конфиденциальности описывает, как GRAM-City (далее — «мы», «нас» или «наш») собирает, использует и защищает информацию, которую вы предоставляете при использовании нашей платформы.',
          es: 'Esta Política de Privacidad describe cómo GRAM-City (en adelante, "nosotros") recopila, utiliza y protege la información que usted proporciona al usar nuestra plataforma.',
          zh: '本隐私政策说明 GRAM-City（以下简称"我们"）如何收集、使用和保护您在使用我们平台时提供的信息。',
          fr: "Cette Politique de confidentialité décrit comment GRAM-City (ci-après « nous ») collecte, utilise et protège les informations que vous fournissez lors de l'utilisation de notre plateforme.",
          de: 'Diese Datenschutzrichtlinie beschreibt, wie GRAM-City (nachfolgend „wir") die Informationen erfasst, verwendet und schützt, die Sie bei der Nutzung unserer Plattform bereitstellen.',
          ja: '本プライバシーポリシーは、GRAM-City（以下「当社」）が当社プラットフォームの利用時にお客様から提供された情報をどのように収集、使用、保護するかを説明します。',
          ko: '본 개인정보 처리방침은 GRAM-City(이하 "당사")가 귀하가 당사 플랫폼을 이용할 때 제공하는 정보를 수집, 사용 및 보호하는 방법을 설명합니다.',
        }},
      ],
    },
    {
      heading: {
        en: '2. Information We Collect', id: "2. Informasi yang Kami Kumpulkan", ru: '2. Собираемая информация', es: '2. Información que recopilamos', zh: '2. 我们收集的信息',
        fr: '2. Informations que nous collectons', de: '2. Erfasste Informationen', ja: '2. 収集する情報', ko: '2. 수집하는 정보',
      },
      blocks: [
        { type: 'p', text: {
          en: 'We may collect the following information:', id: "Kami dapat mengumpulkan informasi berikut:", ru: 'Мы можем собирать следующую информацию:', es: 'Podemos recopilar la siguiente información:', zh: '我们可能会收集以下信息：',
          fr: 'Nous pouvons collecter les informations suivantes :', de: 'Wir können die folgenden Informationen erfassen:', ja: '当社は以下の情報を収集する場合があります：', ko: '당사는 다음 정보를 수집할 수 있습니다:',
        }},
        { type: 'ul', items: [
          { en: 'Account data: email address, username, cryptocurrency wallet address.', id: "Data akun: alamat email, nama pengguna, alamat dompet cryptocurrency.", ru: 'Данные аккаунта: адрес электронной почты, имя пользователя, адрес криптовалютного кошелька.', es: 'Datos de la cuenta: correo electrónico, nombre de usuario, dirección de la billetera de criptomonedas.', zh: '账户数据：电子邮件地址、用户名、加密货币钱包地址。', fr: 'Données de compte : adresse e-mail, nom d\'utilisateur, adresse du portefeuille de cryptomonnaie.', de: 'Kontodaten: E-Mail-Adresse, Benutzername, Krypto-Wallet-Adresse.', ja: 'アカウントデータ：メールアドレス、ユーザー名、暗号通貨ウォレットアドレス。', ko: '계정 데이터: 이메일 주소, 사용자 이름, 암호화폐 지갑 주소.' },
          { en: 'Usage data: information about your actions on the platform, transaction history.', id: "Data penggunaan: informasi tentang tindakan Anda di platform, riwayat transaksi.", ru: 'Данные об использовании: информация о ваших действиях на платформе, история транзакций.', es: 'Datos de uso: información sobre sus acciones en la plataforma, historial de transacciones.', zh: '使用数据：您在平台上的操作信息、交易历史。', fr: "Données d'utilisation : informations sur vos actions sur la plateforme, historique des transactions.", de: 'Nutzungsdaten: Informationen über Ihre Aktivitäten auf der Plattform, Transaktionsverlauf.', ja: '利用データ：プラットフォーム上の操作情報、取引履歴。', ko: '사용 데이터: 플랫폼에서의 활동 정보, 거래 내역.' },
          { en: 'Technical data: IP address, browser type, device, operating system.', id: "Data teknis: alamat IP, jenis browser, perangkat, sistem operasi.", ru: 'Технические данные: IP-адрес, тип браузера, устройство, операционная система.', es: 'Datos técnicos: dirección IP, tipo de navegador, dispositivo, sistema operativo.', zh: '技术数据：IP 地址、浏览器类型、设备、操作系统。', fr: "Données techniques : adresse IP, type de navigateur, appareil, système d'exploitation.", de: 'Technische Daten: IP-Adresse, Browsertyp, Gerät, Betriebssystem.', ja: '技術データ：IPアドレス、ブラウザの種類、デバイス、オペレーティングシステム。', ko: '기술 데이터: IP 주소, 브라우저 유형, 기기, 운영 체제.' },
          { en: 'Security data: two-factor authentication information, login logs.', id: "Data keamanan: informasi otentikasi dua faktor, catatan login.", ru: 'Данные безопасности: информация о двухфакторной аутентификации, журналы входа.', es: 'Datos de seguridad: información de autenticación de dos factores, registros de inicio de sesión.', zh: '安全数据：双重身份验证信息、登录日志。', fr: "Données de sécurité : informations d'authentification à deux facteurs, journaux de connexion.", de: 'Sicherheitsdaten: Informationen zur Zwei-Faktor-Authentifizierung, Anmeldeprotokolle.', ja: 'セキュリティデータ：二要素認証情報、ログイン履歴。', ko: '보안 데이터: 2단계 인증 정보, 로그인 기록.' },
        ]},
      ],
    },
    {
      heading: {
        en: '3. How We Use Information', id: "3. Bagaimana Kami Menggunakan Informasi", ru: '3. Использование информации', es: '3. Uso de la información', zh: '3. 信息的使用',
        fr: '3. Utilisation des informations', de: '3. Verwendung der Informationen', ja: '3. 情報の使用', ko: '3. 정보 사용',
      },
      blocks: [
        { type: 'p', text: {
          en: 'The collected information is used to:', id: "Informasi yang dikumpulkan digunakan untuk:", ru: 'Собранная информация используется для:', es: 'La información recopilada se utiliza para:', zh: '收集的信息用于：',
          fr: 'Les informations collectées sont utilisées pour :', de: 'Die erfassten Informationen werden verwendet, um:', ja: '収集した情報は以下の目的で使用されます：', ko: '수집된 정보는 다음 용도로 사용됩니다:',
        }},
        { type: 'ul', items: [
          { en: 'Provide and improve our services.', id: "Memberikan dan meningkatkan layanan kami.", ru: 'Предоставления и улучшения наших услуг.', es: 'Proporcionar y mejorar nuestros servicios.', zh: '提供和改进我们的服务。', fr: 'Fournir et améliorer nos services.', de: 'Unsere Dienste bereitzustellen und zu verbessern.', ja: '当社のサービスを提供・改善するため。', ko: '당사 서비스를 제공하고 개선하기 위해.' },
          { en: 'Ensure the security of your account.', id: "Memastikan keamanan akun Anda.", ru: 'Обеспечения безопасности вашего аккаунта.', es: 'Garantizar la seguridad de su cuenta.', zh: '确保您账户的安全。', fr: 'Assurer la sécurité de votre compte.', de: 'Die Sicherheit Ihres Kontos zu gewährleisten.', ja: 'お客様のアカウントの安全性を確保するため。', ko: '귀하의 계정 보안을 보장하기 위해.' },
          { en: 'Communicate with you about platform-related matters.', id: "Berkomunikasi dengan Anda tentang hal-hal yang terkait dengan platform.", ru: 'Связи с вами по вопросам, связанным с платформой.', es: 'Comunicarnos con usted sobre asuntos relacionados con la plataforma.', zh: '就平台相关事宜与您沟通。', fr: 'Communiquer avec vous sur des questions liées à la plateforme.', de: 'Mit Ihnen über plattformbezogene Angelegenheiten zu kommunizieren.', ja: 'プラットフォームに関する事項についてお客様と連絡を取るため。', ko: '플랫폼 관련 사항에 대해 귀하와 소통하기 위해.' },
          { en: 'Prevent fraud and abuse.', id: "Mencegah penipuan dan penyalahgunaan.", ru: 'Предотвращения мошенничества и злоупотреблений.', es: 'Prevenir el fraude y el abuso.', zh: '防止欺诈和滥用。', fr: 'Prévenir la fraude et les abus.', de: 'Betrug und Missbrauch zu verhindern.', ja: '不正行為や悪用を防止するため。', ko: '사기 및 남용을 방지하기 위해.' },
          { en: 'Comply with legal requirements.', id: "Mematuhi persyaratan hukum.", ru: 'Выполнения требований законодательства.', es: 'Cumplir con los requisitos legales.', zh: '遵守法律要求。', fr: 'Respecter les exigences légales.', de: 'Gesetzliche Anforderungen zu erfüllen.', ja: '法的要件を遵守するため。', ko: '법적 요구사항을 준수하기 위해.' },
        ]},
      ],
    },
    {
      heading: {
        en: '4. Data Protection', id: "4. Perlindungan Data", ru: '4. Защита данных', es: '4. Protección de datos', zh: '4. 数据保护',
        fr: '4. Protection des données', de: '4. Datenschutz', ja: '4. データ保護', ko: '4. 데이터 보호',
      },
      blocks: [
        { type: 'p', text: {
          en: 'We apply technical and organizational measures to protect your information, including:', id: "Kami menerapkan langkah teknis dan organisasi untuk melindungi informasi Anda, termasuk:", ru: 'Мы применяем технические и организационные меры для защиты вашей информации, включая:', es: 'Aplicamos medidas técnicas y organizativas para proteger su información, incluyendo:', zh: '我们采取技术和组织措施来保护您的信息，包括：',
          fr: 'Nous appliquons des mesures techniques et organisationnelles pour protéger vos informations, notamment :', de: 'Wir wenden technische und organisatorische Maßnahmen zum Schutz Ihrer Informationen an, darunter:', ja: '当社はお客様の情報を保護するため、以下を含む技術的・組織的措置を講じています：', ko: '당사는 귀하의 정보를 보호하기 위해 다음을 포함한 기술적·조직적 조치를 적용합니다:',
        }},
        { type: 'ul', items: [
          { en: 'Encryption of data in transit (SSL/TLS).', id: "Enkripsi data dalam perjalanan (SSL/TLS).", ru: 'Шифрование данных при передаче (SSL/TLS).', es: 'Cifrado de datos en tránsito (SSL/TLS).', zh: '传输中数据的加密（SSL/TLS）。', fr: 'Chiffrement des données en transit (SSL/TLS).', de: 'Verschlüsselung von Daten während der Übertragung (SSL/TLS).', ja: '転送中のデータの暗号化（SSL/TLS）。', ko: '전송 중 데이터 암호화(SSL/TLS).' },
          { en: 'Hashing of passwords and secret keys.', id: "Hashing kata sandi dan kunci rahasia.", ru: 'Хеширование паролей и секретных ключей.', es: 'Hash de contraseñas y claves secretas.', zh: '密码和密钥的哈希处理。', fr: 'Hachage des mots de passe et des clés secrètes.', de: 'Hashing von Passwörtern und geheimen Schlüsseln.', ja: 'パスワードと秘密鍵のハッシュ化。', ko: '비밀번호 및 비밀 키 해싱.' },
          { en: 'Restricted access to personal data.', id: "Akses terbatas ke data pribadi.", ru: 'Ограниченный доступ к персональным данным.', es: 'Acceso restringido a los datos personales.', zh: '限制对个人数据的访问。', fr: 'Accès restreint aux données personnelles.', de: 'Eingeschränkter Zugriff auf personenbezogene Daten.', ja: '個人データへのアクセス制限。', ko: '개인 데이터에 대한 접근 제한.' },
        ]},
        { type: 'p', style: 'amber', text: {
          en: 'However, no method of data transmission or storage is completely secure. We cannot guarantee the absolute security of your data.', id: "Namun, tidak ada metode transmisi atau penyimpanan data yang sepenuhnya aman. Kami tidak dapat menjamin keamanan absolut data Anda.", ru: 'Однако ни один метод передачи или хранения данных не является полностью безопасным. Мы не можем гарантировать абсолютную безопасность ваших данных.', es: 'Sin embargo, ningún método de transmisión o almacenamiento de datos es completamente seguro. No podemos garantizar la seguridad absoluta de sus datos.', zh: '然而，没有任何数据传输或存储方法是完全安全的。我们无法保证您数据的绝对安全。',
          fr: "Cependant, aucune méthode de transmission ou de stockage de données n'est totalement sûre. Nous ne pouvons garantir la sécurité absolue de vos données.", de: 'Allerdings ist keine Methode der Datenübertragung oder -speicherung vollständig sicher. Wir können die absolute Sicherheit Ihrer Daten nicht garantieren.', ja: 'ただし、データの送信や保存の方法に完全に安全なものはありません。当社はお客様のデータの絶対的な安全性を保証することはできません。', ko: '그러나 데이터 전송 또는 저장 방법 중 완전히 안전한 것은 없습니다. 당사는 귀하 데이터의 절대적인 보안을 보장할 수 없습니다.',
        }},
      ],
    },
    {
      heading: {
        en: '5. Sharing Data with Third Parties', id: "5. Berbagi Data dengan Pihak Ketiga", ru: '5. Передача данных третьим лицам', es: '5. Compartir datos con terceros', zh: '5. 向第三方共享数据',
        fr: '5. Partage des données avec des tiers', de: '5. Weitergabe von Daten an Dritte', ja: '5. 第三者へのデータ提供', ko: '5. 제3자와의 데이터 공유',
      },
      blocks: [
        { type: 'p', text: {
          en: 'We do not sell or share your personal data with third parties, except when:', id: "Kami tidak menjual atau membagikan data pribadi Anda kepada pihak ketiga, kecuali ketika:", ru: 'Мы не продаём и не передаём ваши персональные данные третьим лицам, за исключением случаев:', es: 'No vendemos ni compartimos sus datos personales con terceros, excepto cuando:', zh: '我们不会出售或与第三方共享您的个人数据，除非：',
          fr: 'Nous ne vendons ni ne partageons vos données personnelles avec des tiers, sauf lorsque :', de: 'Wir verkaufen oder teilen Ihre personenbezogenen Daten nicht mit Dritten, außer wenn:', ja: '当社は、以下の場合を除き、お客様の個人データを第三者に販売・提供しません：', ko: '당사는 다음의 경우를 제외하고 귀하의 개인 데이터를 제3자에게 판매하거나 공유하지 않습니다:',
        }},
        { type: 'ul', items: [
          { en: 'It is necessary to provide services (e.g., payment processing).', id: "Diperlukan untuk menyediakan layanan (misalnya, pemrosesan pembayaran).", ru: 'Когда это необходимо для предоставления услуг (например, обработка платежей).', es: 'Es necesario para prestar servicios (por ejemplo, procesamiento de pagos).', zh: '为提供服务所必需（例如支付处理）。', fr: 'Cela est nécessaire pour fournir des services (par exemple, le traitement des paiements).', de: 'Es zur Erbringung von Diensten erforderlich ist (z. B. Zahlungsabwicklung).', ja: 'サービス提供に必要な場合（例：決済処理）。', ko: '서비스 제공에 필요한 경우(예: 결제 처리).' },
          { en: 'Required by law or judicial authorities.', id: "Diperlukan oleh hukum atau otoritas yudisial.", ru: 'По требованию законодательства или судебных органов.', es: 'Lo exige la ley o las autoridades judiciales.', zh: '法律或司法机关要求。', fr: 'Cela est exigé par la loi ou les autorités judiciaires.', de: 'Es gesetzlich oder von Justizbehörden vorgeschrieben ist.', ja: '法律または司法当局により要求された場合。', ko: '법률 또는 사법 당국의 요구가 있는 경우.' },
          { en: 'To protect our rights and the safety of users.', id: "Untuk melindungi hak-hak kami dan keamanan pengguna.", ru: 'Для защиты наших прав и безопасности пользователей.', es: 'Para proteger nuestros derechos y la seguridad de los usuarios.', zh: '为保护我们的权利和用户的安全。', fr: 'Pour protéger nos droits et la sécurité des utilisateurs.', de: 'Um unsere Rechte und die Sicherheit der Nutzer zu schützen.', ja: '当社の権利およびユーザーの安全を保護するため。', ko: '당사의 권리 및 사용자의 안전을 보호하기 위해.' },
        ]},
      ],
    },
    {
      heading: {
        en: '6. Your Rights', id: "6. Hak-Hak Anda", ru: '6. Ваши права', es: '6. Sus derechos', zh: '6. 您的权利',
        fr: '6. Vos droits', de: '6. Ihre Rechte', ja: '6. お客様の権利', ko: '6. 귀하의 권리',
      },
      blocks: [
        { type: 'p', text: {
          en: 'You have the right to:', id: "Anda memiliki hak untuk:", ru: 'Вы имеете право:', es: 'Usted tiene derecho a:', zh: '您有权：',
          fr: 'Vous avez le droit de :', de: 'Sie haben das Recht:', ja: 'お客様は以下の権利を有します：', ko: '귀하는 다음 권리를 가집니다:',
        }},
        { type: 'ul', items: [
          { en: 'Request access to your personal data.', id: "Meminta akses ke data pribadi Anda.", ru: 'Запросить доступ к своим персональным данным.', es: 'Solicitar acceso a sus datos personales.', zh: '请求访问您的个人数据。', fr: 'Demander l\'accès à vos données personnelles.', de: 'Zugang zu Ihren personenbezogenen Daten zu verlangen.', ja: 'ご自身の個人データへのアクセスを請求すること。', ko: '본인의 개인 데이터에 대한 접근을 요청할 권리.' },
          { en: 'Request correction of inaccurate data.', id: "Meminta perbaikan data yang tidak akurat.", ru: 'Запросить исправление неточных данных.', es: 'Solicitar la corrección de datos inexactos.', zh: '请求更正不准确的数据。', fr: 'Demander la rectification de données inexactes.', de: 'Die Berichtigung unrichtiger Daten zu verlangen.', ja: '不正確なデータの訂正を請求すること。', ko: '부정확한 데이터의 수정을 요청할 권리.' },
          { en: 'Request deletion of your data (subject to legal restrictions).', id: "Meminta penghapusan data Anda (tergantung pada batasan hukum).", ru: 'Запросить удаление ваших данных (с учётом законодательных ограничений).', es: 'Solicitar la eliminación de sus datos (sujeto a restricciones legales).', zh: '请求删除您的数据（受法律限制）。', fr: 'Demander la suppression de vos données (sous réserve des restrictions légales).', de: 'Die Löschung Ihrer Daten zu verlangen (vorbehaltlich gesetzlicher Einschränkungen).', ja: 'ご自身のデータの削除を請求すること（法的制限の範囲内）。', ko: '귀하 데이터의 삭제를 요청할 권리(법적 제한에 따름).' },
          { en: 'Withdraw consent to data processing.', id: "Mencabut persetujuan untuk pemrosesan data.", ru: 'Отозвать согласие на обработку данных.', es: 'Retirar el consentimiento para el procesamiento de datos.', zh: '撤回对数据处理的同意。', fr: 'Retirer votre consentement au traitement des données.', de: 'Ihre Einwilligung zur Datenverarbeitung zu widerrufen.', ja: 'データ処理への同意を撤回すること。', ko: '데이터 처리에 대한 동의를 철회할 권리.' },
        ]},
      ],
    },
    {
      heading: {
        en: '7. Data Retention', id: "7. Penyimpanan Data", ru: '7. Хранение данных', es: '7. Conservación de datos', zh: '7. 数据保留',
        fr: '7. Conservation des données', de: '7. Datenaufbewahrung', ja: '7. データの保持', ko: '7. 데이터 보관',
      },
      blocks: [
        { type: 'p', text: {
          en: 'We retain your data for as long as necessary to provide services or comply with legal requirements. After account deletion, data may be retained in backups for a limited time.', id: "Kami menyimpan data Anda selama diperlukan untuk menyediakan layanan atau mematuhi persyaratan hukum. Setelah penghapusan akun, data dapat disimpan dalam cadangan untuk waktu terbatas.", ru: 'Мы храним ваши данные столько, сколько необходимо для предоставления услуг или выполнения требований законодательства. После удаления аккаунта данные могут храниться в резервных копиях ограниченное время.', es: 'Conservamos sus datos durante el tiempo necesario para prestar servicios o cumplir con los requisitos legales. Tras la eliminación de la cuenta, los datos pueden conservarse en copias de seguridad durante un tiempo limitado.', zh: '我们会在提供服务或遵守法律要求所需的时间内保留您的数据。账户删除后，数据可能会在备份中保留有限的时间。',
          fr: 'Nous conservons vos données aussi longtemps que nécessaire pour fournir des services ou respecter les exigences légales. Après la suppression du compte, les données peuvent être conservées dans des sauvegardes pendant une durée limitée.', de: 'Wir bewahren Ihre Daten so lange auf, wie es zur Erbringung von Diensten oder zur Erfüllung gesetzlicher Anforderungen erforderlich ist. Nach der Kontolöschung können Daten für begrenzte Zeit in Backups gespeichert bleiben.', ja: '当社は、サービス提供または法的要件の遵守に必要な期間、お客様のデータを保持します。アカウント削除後も、データは限られた期間バックアップに保持される場合があります。', ko: '당사는 서비스 제공 또는 법적 요구사항 준수에 필요한 기간 동안 귀하의 데이터를 보관합니다. 계정 삭제 후에도 데이터는 제한된 기간 동안 백업에 보관될 수 있습니다.',
        }},
      ],
    },
    {
      heading: {
        en: '8. Cookies', id: "8. Cookies", ru: '8. Файлы cookie', es: '8. Cookies', zh: '8. Cookie 文件',
        fr: '8. Cookies', de: '8. Cookies', ja: '8. クッキー', ko: '8. 쿠키',
      },
      blocks: [
        { type: 'p', text: {
          en: 'We use cookies and similar technologies to:', id: "Kami menggunakan cookies dan teknologi serupa untuk:", ru: 'Мы используем файлы cookie и аналогичные технологии для:', es: 'Utilizamos cookies y tecnologías similares para:', zh: '我们使用 Cookie 和类似技术来：',
          fr: 'Nous utilisons des cookies et des technologies similaires pour :', de: 'Wir verwenden Cookies und ähnliche Technologien, um:', ja: '当社は、以下の目的でクッキーおよび類似技術を使用します：', ko: '당사는 다음 목적으로 쿠키 및 유사 기술을 사용합니다:',
        }},
        { type: 'ul', items: [
          { en: 'Maintain your authentication session.', id: "Mempertahankan sesi autentikasi Anda.", ru: 'Поддержания сессии авторизации.', es: 'Mantener su sesión de autenticación.', zh: '维持您的身份验证会话。', fr: 'Maintenir votre session d\'authentification.', de: 'Ihre Authentifizierungssitzung aufrechtzuerhalten.', ja: '認証セッションを維持するため。', ko: '인증 세션을 유지하기 위해.' },
          { en: 'Remember your settings.', id: "Mengingat pengaturan Anda.", ru: 'Запоминания ваших настроек.', es: 'Recordar su configuración.', zh: '记住您的设置。', fr: 'Mémoriser vos paramètres.', de: 'Ihre Einstellungen zu speichern.', ja: 'お客様の設定を記憶するため。', ko: '귀하의 설정을 기억하기 위해.' },
          { en: 'Analyze platform usage.', id: "Menganalisis penggunaan platform.", ru: 'Анализа использования платформы.', es: 'Analizar el uso de la plataforma.', zh: '分析平台使用情况。', fr: "Analyser l'utilisation de la plateforme.", de: 'Die Plattformnutzung zu analysieren.', ja: 'プラットフォームの利用状況を分析するため。', ko: '플랫폼 사용을 분석하기 위해.' },
        ]},
      ],
    },
    {
      heading: {
        en: '9. Changes to the Policy', id: "9. Perubahan pada Kebijakan", ru: '9. Изменения политики', es: '9. Cambios en la política', zh: '9. 政策变更',
        fr: '9. Modifications de la politique', de: '9. Änderungen der Richtlinie', ja: '9. ポリシーの変更', ko: '9. 정책 변경',
      },
      blocks: [
        { type: 'p', text: {
          en: 'We may update this Privacy Policy. We will notify you of material changes through the platform or by email.', id: "Kami dapat memperbarui Kebijakan Privasi ini. Kami akan memberi tahu Anda tentang perubahan material melalui platform atau melalui email.", ru: 'Мы можем обновлять настоящую Политику конфиденциальности. О существенных изменениях мы уведомим вас через платформу или по электронной почте.', es: 'Podemos actualizar esta Política de Privacidad. Le notificaremos los cambios importantes a través de la plataforma o por correo electrónico.', zh: '我们可能会更新本隐私政策。我们将通过平台或电子邮件通知您重大变更。',
          fr: 'Nous pouvons mettre à jour cette Politique de confidentialité. Nous vous informerons des modifications importantes via la plateforme ou par e-mail.', de: 'Wir können diese Datenschutzrichtlinie aktualisieren. Über wesentliche Änderungen informieren wir Sie über die Plattform oder per E-Mail.', ja: '当社は本プライバシーポリシーを更新する場合があります。重要な変更については、プラットフォームまたはメールでお知らせします。', ko: '당사는 본 개인정보 처리방침을 업데이트할 수 있습니다. 중요한 변경 사항은 플랫폼 또는 이메일을 통해 알려드립니다.',
        }},
      ],
    },
    {
      heading: {
        en: '10. Contact', id: "10. Kontak", ru: '10. Контакты', es: '10. Contacto', zh: '10. 联系方式',
        fr: '10. Contact', de: '10. Kontakt', ja: '10. お問い合わせ', ko: '10. 연락처',
      },
      blocks: [
        { type: 'p', text: {
          en: 'For privacy-related questions, please contact us through the support section on the platform.', id: "Untuk pertanyaan terkait privasi, silakan hubungi kami melalui bagian dukungan di platform.", ru: 'По вопросам, связанным с конфиденциальностью, обращайтесь через раздел поддержки на платформе.', es: 'Para preguntas relacionadas con la privacidad, contáctenos a través de la sección de soporte de la plataforma.', zh: '如有隐私相关问题，请通过平台上的支持部分与我们联系。',
          fr: 'Pour toute question relative à la confidentialité, contactez-nous via la section assistance de la plateforme.', de: 'Bei Fragen zum Datenschutz kontaktieren Sie uns bitte über den Support-Bereich der Plattform.', ja: 'プライバシーに関するご質問は、プラットフォームのサポートセクションからお問い合わせください。', ko: '개인정보 관련 문의는 플랫폼의 지원 섹션을 통해 연락해 주십시오.',
        }},
      ],
    },
  ],
  footer: {
    style: 'cyan',
    text: {
      en: 'By continuing to use the GRAM-City platform, you agree to the terms of this Privacy Policy.', id: "Dengan terus menggunakan platform GRAM-City, Anda setuju dengan ketentuan Kebijakan Privasi ini.", ru: 'Продолжая использовать платформу GRAM-City, вы соглашаетесь с условиями настоящей Политики конфиденциальности.', es: 'Al continuar usando la plataforma GRAM-City, usted acepta los términos de esta Política de Privacidad.', zh: '继续使用 GRAM-City 平台即表示您同意本隐私政策的条款。',
      fr: "En continuant à utiliser la plateforme GRAM-City, vous acceptez les termes de cette Politique de confidentialité.", de: 'Durch die weitere Nutzung der GRAM-City-Plattform stimmen Sie den Bedingungen dieser Datenschutzrichtlinie zu.', ja: 'GRAM-Cityプラットフォームの利用を継続することにより、お客様は本プライバシーポリシーの条件に同意したものとみなされます。', ko: 'GRAM-City 플랫폼을 계속 사용함으로써 귀하는 본 개인정보 처리방침의 조건에 동의하는 것입니다.',
    },
  },
};

// ---------------------------------------------------------------------------
// TERMS OF USE
// ---------------------------------------------------------------------------
export const termsDoc = {
  title: {
    en: 'GRAM-City Terms of Use', id: "Ketentuan Penggunaan GRAM-City",
    ru: 'Пользовательское соглашение GRAM-City',
    es: 'Términos de Uso de GRAM-City',
    zh: 'GRAM-City 用户协议',
    fr: "Conditions d'utilisation de GRAM-City",
    de: 'Nutzungsbedingungen von GRAM-City',
    ja: 'GRAM-City 利用規約',
    ko: 'GRAM-City 이용약관',
  },
  effectiveDate: privacyDoc.effectiveDate,
  sections: [
    {
      heading: {
        en: '1. General Provisions', id: "1. Ketentuan Umum", ru: '1. Общие положения', es: '1. Disposiciones generales', zh: '1. 总则',
        fr: '1. Dispositions générales', de: '1. Allgemeine Bestimmungen', ja: '1. 総則', ko: '1. 일반 조항',
      },
      blocks: [
        { type: 'p', text: {
          en: 'These Terms of Use (hereinafter "the Agreement") govern the relationship between the administration of the GRAM-City project (hereinafter "the Administration") and the user (hereinafter "the User") within the scope of using the GRAM-City platform.', id: "Ketentuan Penggunaan ini (selanjutnya disebut \"Perjanjian\") mengatur hubungan antara administrasi proyek GRAM-City (selanjutnya disebut \"Administrasi\") dan pengguna (selanjutnya disebut \"Pengguna\") dalam ruang lingkup penggunaan platform GRAM-City.", ru: 'Настоящее Пользовательское соглашение (далее — «Соглашение») регулирует отношения между администрацией проекта GRAM-City (далее — «Администрация») и пользователем (далее — «Пользователь») в рамках использования платформы GRAM-City.', es: 'Estos Términos de Uso (en adelante, "el Acuerdo") regulan la relación entre la administración del proyecto GRAM-City (en adelante, "la Administración") y el usuario (en adelante, "el Usuario") en el marco del uso de la plataforma GRAM-City.', zh: '本用户协议（以下简称"协议"）规范 GRAM-City 项目管理方（以下简称"管理方"）与用户（以下简称"用户"）在使用 GRAM-City 平台范围内的关系。',
          fr: "Les présentes Conditions d'utilisation (ci-après « l'Accord ») régissent la relation entre l'administration du projet GRAM-City (ci-après « l'Administration ») et l'utilisateur (ci-après « l'Utilisateur ») dans le cadre de l'utilisation de la plateforme GRAM-City.", de: 'Diese Nutzungsbedingungen (nachfolgend „die Vereinbarung") regeln das Verhältnis zwischen der Verwaltung des GRAM-City-Projekts (nachfolgend „die Verwaltung") und dem Nutzer (nachfolgend „der Nutzer") im Rahmen der Nutzung der GRAM-City-Plattform.', ja: '本利用規約（以下「本規約」）は、GRAM-Cityプロジェクトの運営者（以下「運営者」）とユーザー（以下「ユーザー」）との間の、GRAM-Cityプラットフォームの利用に関する関係を規定します。', ko: '본 이용약관(이하 "약관")은 GRAM-City 프로젝트 운영자(이하 "운영자")와 사용자(이하 "사용자") 간의 GRAM-City 플랫폼 이용에 관한 관계를 규율합니다.',
        }},
        { type: 'p', text: {
          en: 'By registering on the platform, the User confirms that they have fully reviewed the terms of this Agreement and accept them in full.', id: "Dengan mendaftar di platform, Pengguna mengkonfirmasi bahwa mereka telah meninjau sepenuhnya syarat-syarat dari Perjanjian ini dan menerimanya secara penuh.", ru: 'Регистрируясь на платформе, Пользователь подтверждает, что полностью ознакомился с условиями настоящего Соглашения и принимает их в полном объёме.', es: 'Al registrarse en la plataforma, el Usuario confirma que ha revisado por completo los términos de este Acuerdo y los acepta en su totalidad.', zh: '在平台注册即表示用户确认已完全阅读本协议条款并完全接受。',
          fr: "En s'inscrivant sur la plateforme, l'Utilisateur confirme avoir pris pleinement connaissance des conditions du présent Accord et les accepter intégralement.", de: 'Mit der Registrierung auf der Plattform bestätigt der Nutzer, dass er die Bedingungen dieser Vereinbarung vollständig zur Kenntnis genommen hat und sie vollumfänglich akzeptiert.', ja: 'プラットフォームに登録することにより、ユーザーは本規約の条件を完全に確認し、全面的に承諾したことを確認します。', ko: '플랫폼에 등록함으로써 사용자는 본 약관의 조건을 완전히 검토하였으며 이를 전적으로 수락함을 확인합니다.',
        }},
      ],
    },
    {
      heading: {
        en: '2. Platform Description', id: "2. Deskripsi Platform", ru: '2. Описание платформы', es: '2. Descripción de la plataforma', zh: '2. 平台说明',
        fr: '2. Description de la plateforme', de: '2. Beschreibung der Plattform', ja: '2. プラットフォームの説明', ko: '2. 플랫폼 설명',
      },
      blocks: [
        { type: 'p', text: {
          en: 'GRAM-City is an economic strategy game in which users can acquire virtual land, build businesses and interact with other platform participants.', id: "GRAM-City adalah permainan strategi ekonomi di mana pengguna dapat memperoleh tanah virtual, membangun bisnis, dan berinteraksi dengan peserta platform lainnya.", ru: 'GRAM-City — это экономическая стратегия, в которой пользователи могут приобретать виртуальную землю, строить бизнесы и взаимодействовать с другими участниками платформы.', es: 'GRAM-City es un juego de estrategia económica en el que los usuarios pueden adquirir tierras virtuales, construir negocios e interactuar con otros participantes de la plataforma.', zh: 'GRAM-City 是一款经济策略游戏，用户可以购买虚拟土地、建造企业并与其他平台参与者互动。',
          fr: 'GRAM-City est un jeu de stratégie économique dans lequel les utilisateurs peuvent acquérir des terrains virtuels, construire des entreprises et interagir avec d\'autres participants de la plateforme.', de: 'GRAM-City ist ein Wirtschaftsstrategiespiel, in dem Nutzer virtuelles Land erwerben, Unternehmen aufbauen und mit anderen Plattformteilnehmern interagieren können.', ja: 'GRAM-Cityは、ユーザーが仮想の土地を取得し、ビジネスを構築し、他のプラットフォーム参加者と交流できる経済戦略ゲームです。', ko: 'GRAM-City는 사용자가 가상 토지를 취득하고, 사업을 건설하며, 다른 플랫폼 참가자와 상호작용할 수 있는 경제 전략 게임입니다.',
        }},
        { type: 'p', style: 'amber', text: {
          en: 'IMPORTANT: GRAM-City is not an investment platform, a financial pyramid or a get-rich-quick scheme. The Administration does not promise or guarantee any income from using the platform.', id: "PENTING: GRAM-City bukanlah platform investasi, piramida finansial atau skema cepat kaya. Administrasi tidak menjanjikan atau menjamin penghasilan apapun dari penggunaan platform.", ru: 'ВАЖНО: GRAM-City не является инвестиционной платформой, финансовой пирамидой или схемой быстрого обогащения. Администрация не обещает и не гарантирует какого-либо дохода от использования платформы.', es: 'IMPORTANTE: GRAM-City no es una plataforma de inversión, un esquema piramidal ni un sistema para enriquecerse rápidamente. La Administración no promete ni garantiza ningún ingreso por el uso de la plataforma.', zh: '重要提示：GRAM-City 不是投资平台、金融传销或快速致富计划。管理方不承诺也不保证使用平台可获得任何收益。',
          fr: "IMPORTANT : GRAM-City n'est pas une plateforme d'investissement, une pyramide financière ou un système d'enrichissement rapide. L'Administration ne promet ni ne garantit aucun revenu lié à l'utilisation de la plateforme.", de: 'WICHTIG: GRAM-City ist keine Investitionsplattform, kein Schneeballsystem und kein Schnell-reich-werden-Schema. Die Verwaltung verspricht oder garantiert keinerlei Einkommen aus der Nutzung der Plattform.', ja: '重要：GRAM-Cityは投資プラットフォーム、ネズミ講、または一攫千金のスキームではありません。運営者はプラットフォームの利用による収益を約束または保証しません。', ko: '중요: GRAM-City는 투자 플랫폼, 금융 피라미드 또는 일확천금 계획이 아닙니다. 운영자는 플랫폼 이용을 통한 어떠한 수익도 약속하거나 보장하지 않습니다.',
        }},
      ],
    },
    {
      heading: {
        en: '3. Disclaimer', id: "3. Penafian", ru: '3. Отказ от ответственности', es: '3. Renuncia de responsabilidad', zh: '3. 免责声明',
        fr: '3. Clause de non-responsabilité', de: '3. Haftungsausschluss', ja: '3. 免責事項', ko: '3. 면책 조항',
      },
      blocks: [
        { type: 'ul', items: [
          { en: 'The Administration is not liable for any losses, loss of funds or lost profits arising from the use of the platform.', id: "Administrasi tidak bertanggung jawab atas kerugian, kehilangan dana atau keuntungan yang hilang yang timbul dari penggunaan platform.", ru: 'Администрация не несёт ответственности за любые убытки, потерю средств или упущенную выгоду, возникшие в результате использования платформы.', es: 'La Administración no se hace responsable de pérdidas, pérdida de fondos o lucro cesante derivados del uso de la plataforma.', zh: '管理方不对因使用平台而产生的任何损失、资金损失或利润损失承担责任。', fr: "L'Administration n'est pas responsable des pertes, de la perte de fonds ou du manque à gagner résultant de l'utilisation de la plateforme.", de: 'Die Verwaltung haftet nicht für Verluste, den Verlust von Geldern oder entgangene Gewinne, die aus der Nutzung der Plattform entstehen.', ja: '運営者は、プラットフォームの利用に起因するいかなる損失、資金の喪失、または逸失利益についても責任を負いません。', ko: '운영자는 플랫폼 이용으로 발생하는 손실, 자금 손실 또는 일실 이익에 대해 책임을 지지 않습니다.' },
          { en: 'The User understands and accepts all risks associated with using cryptocurrency and blockchain technologies.', id: "Pengguna memahami dan menerima semua risiko yang terkait dengan penggunaan cryptocurrency dan teknologi blockchain.", ru: 'Пользователь осознаёт и принимает все риски, связанные с использованием криптовалюты и блокчейн-технологий.', es: 'El Usuario comprende y acepta todos los riesgos asociados con el uso de criptomonedas y tecnologías blockchain.', zh: '用户理解并接受使用加密货币和区块链技术相关的所有风险。', fr: "L'Utilisateur comprend et accepte tous les risques liés à l'utilisation de la cryptomonnaie et des technologies blockchain.", de: 'Der Nutzer versteht und akzeptiert alle Risiken im Zusammenhang mit der Nutzung von Kryptowährungen und Blockchain-Technologien.', ja: 'ユーザーは、暗号通貨およびブロックチェーン技術の使用に関連するすべてのリスクを理解し、承諾します。', ko: '사용자는 암호화폐 및 블록체인 기술 사용과 관련된 모든 위험을 이해하고 수락합니다.' },
          { en: 'The Administration does not guarantee uninterrupted operation of the platform and is not liable for technical failures.', id: "Administrasi tidak menjamin operasi platform yang tidak terputus dan tidak bertanggung jawab atas kegagalan teknis.", ru: 'Администрация не гарантирует бесперебойную работу платформы и не несёт ответственности за технические сбои.', es: 'La Administración no garantiza el funcionamiento ininterrumpido de la plataforma y no se hace responsable de fallos técnicos.', zh: '管理方不保证平台不间断运行，也不对技术故障承担责任。', fr: "L'Administration ne garantit pas le fonctionnement ininterrompu de la plateforme et n'est pas responsable des défaillances techniques.", de: 'Die Verwaltung garantiert keinen unterbrechungsfreien Betrieb der Plattform und haftet nicht für technische Störungen.', ja: '運営者はプラットフォームの中断のない稼働を保証せず、技術的障害について責任を負いません。', ko: '운영자는 플랫폼의 중단 없는 운영을 보장하지 않으며 기술적 장애에 대해 책임을 지지 않습니다.' },
          { en: 'All cryptocurrency operations are carried out by the User at their own risk.', id: "Semua operasi cryptocurrency dilakukan oleh Pengguna atas risiko mereka sendiri.", ru: 'Все операции с криптовалютой осуществляются Пользователем на свой страх и риск.', es: 'Todas las operaciones con criptomonedas las realiza el Usuario bajo su propio riesgo.', zh: '所有加密货币操作均由用户自行承担风险。', fr: "Toutes les opérations en cryptomonnaie sont effectuées par l'Utilisateur à ses propres risques.", de: 'Alle Kryptowährungstransaktionen werden vom Nutzer auf eigenes Risiko durchgeführt.', ja: 'すべての暗号通貨取引は、ユーザー自身の責任において行われます。', ko: '모든 암호화폐 거래는 사용자 본인의 책임 하에 수행됩니다.' },
          { en: 'The Administration is not liable for loss of access to the wallet or account due to the User\'s fault.', id: "Administrasi tidak bertanggung jawab atas hilangnya akses ke dompet atau akun akibat kesalahan Pengguna.", ru: 'Администрация не несёт ответственности за утерю доступа к кошельку или аккаунту по вине Пользователя.', es: 'La Administración no se hace responsable de la pérdida de acceso a la billetera o cuenta por culpa del Usuario.', zh: '管理方不对因用户原因导致的钱包或账户访问丢失承担责任。', fr: "L'Administration n'est pas responsable de la perte d'accès au portefeuille ou au compte par la faute de l'Utilisateur.", de: 'Die Verwaltung haftet nicht für den Verlust des Zugangs zur Wallet oder zum Konto durch Verschulden des Nutzers.', ja: '運営者は、ユーザーの過失によるウォレットまたはアカウントへのアクセスの喪失について責任を負いません。', ko: '운영자는 사용자의 과실로 인한 지갑 또는 계정 접근 권한 상실에 대해 책임을 지지 않습니다.' },
        ]},
      ],
    },
    {
      heading: {
        en: '4. No Income Guarantee', id: "4. Tidak Ada Jaminan Pendapatan", ru: '4. Отсутствие гарантий дохода', es: '4. Sin garantía de ingresos', zh: '4. 不保证收益',
        fr: '4. Aucune garantie de revenu', de: '4. Keine Einkommensgarantie', ja: '4. 収益の保証なし', ko: '4. 수익 보장 없음',
      },
      blocks: [
        { type: 'p', style: 'red', text: {
          en: 'The Administration expressly states that:', id: "Administrasi dengan tegas menyatakan bahwa:", ru: 'Администрация прямо заявляет, что:', es: 'La Administración declara expresamente que:', zh: '管理方明确声明：',
          fr: "L'Administration déclare expressément que :", de: 'Die Verwaltung erklärt ausdrücklich, dass:', ja: '運営者は以下を明示的に表明します：', ko: '운영자는 다음을 명시적으로 선언합니다:',
        }},
        { type: 'ul', items: [
          { en: 'The platform does not promise or guarantee any income, profit or return on investment.', id: "Platform tidak menjanjikan atau menjamin pendapatan, keuntungan, atau pengembalian investasi.", ru: 'Платформа не обещает и не гарантирует какого-либо дохода, прибыли или возврата вложений.', es: 'La plataforma no promete ni garantiza ningún ingreso, beneficio o retorno de la inversión.', zh: '平台不承诺也不保证任何收入、利润或投资回报。', fr: "La plateforme ne promet ni ne garantit aucun revenu, profit ou retour sur investissement.", de: 'Die Plattform verspricht oder garantiert kein Einkommen, keinen Gewinn und keine Rendite.', ja: 'プラットフォームはいかなる収入、利益、または投資収益も約束・保証しません。', ko: '플랫폼은 어떠한 수입, 이익 또는 투자 수익도 약속하거나 보장하지 않습니다.' },
          { en: 'Virtual currency and assets on the platform may lose value or become unavailable.', id: "Mata uang virtual dan aset di platform dapat kehilangan nilai atau menjadi tidak tersedia.", ru: 'Виртуальная валюта и активы на платформе могут обесцениться или стать недоступными.', es: 'La moneda virtual y los activos en la plataforma pueden perder valor o quedar no disponibles.', zh: '平台上的虚拟货币和资产可能贬值或变得无法使用。', fr: 'La monnaie virtuelle et les actifs de la plateforme peuvent perdre de la valeur ou devenir indisponibles.', de: 'Virtuelle Währung und Vermögenswerte auf der Plattform können an Wert verlieren oder nicht mehr verfügbar sein.', ja: 'プラットフォーム上の仮想通貨や資産は、価値を失ったり利用できなくなったりする可能性があります。', ko: '플랫폼의 가상 화폐 및 자산은 가치가 하락하거나 이용할 수 없게 될 수 있습니다.' },
          { en: 'The User should only contribute funds they can afford to lose.', id: "Pengguna hanya harus menyumbangkan dana yang dapat mereka rugikan.", ru: 'Пользователь должен вносить только те средства, потерю которых он может себе позволить.', es: 'El Usuario solo debe aportar fondos cuya pérdida pueda permitirse.', zh: '用户应仅投入其能够承受损失的资金。', fr: "L'Utilisateur ne doit verser que des fonds dont il peut se permettre la perte.", de: 'Der Nutzer sollte nur Mittel einsetzen, deren Verlust er sich leisten kann.', ja: 'ユーザーは、失っても問題のない資金のみを拠出すべきです。', ko: '사용자는 손실을 감당할 수 있는 자금만 투입해야 합니다.' },
          { en: 'Past performance or examples of other users do not guarantee future results.', id: "Kinerja masa lalu atau contoh pengguna lain tidak menjamin hasil di masa depan.", ru: 'Прошлые показатели или примеры других пользователей не являются гарантией будущих результатов.', es: 'El rendimiento pasado o los ejemplos de otros usuarios no garantizan resultados futuros.', zh: '过去的表现或其他用户的示例并不保证未来的结果。', fr: "Les performances passées ou les exemples d'autres utilisateurs ne garantissent pas les résultats futurs.", de: 'Vergangene Leistungen oder Beispiele anderer Nutzer sind keine Garantie für zukünftige Ergebnisse.', ja: '過去の実績や他のユーザーの事例は、将来の結果を保証するものではありません。', ko: '과거 실적이나 다른 사용자의 사례는 미래의 결과를 보장하지 않습니다.' },
        ]},
      ],
    },
    {
      heading: {
        en: '5. Limitation of Liability', id: "5. Pembatasan Tanggung Jawab", ru: '5. Ограничение ответственности', es: '5. Limitación de responsabilidad', zh: '5. 责任限制',
        fr: '5. Limitation de responsabilité', de: '5. Haftungsbeschränkung', ja: '5. 責任の制限', ko: '5. 책임의 제한',
      },
      blocks: [
        { type: 'p', text: {
          en: 'To the maximum extent permitted by applicable law:', id: "Sebesar mungkin yang diizinkan oleh hukum yang berlaku:", ru: 'В максимальной степени, допустимой применимым законодательством:', es: 'En la máxima medida permitida por la ley aplicable:', zh: '在适用法律允许的最大范围内：',
          fr: 'Dans la mesure maximale permise par la loi applicable :', de: 'Soweit nach geltendem Recht zulässig:', ja: '適用法で認められる最大限の範囲において：', ko: '관련 법률이 허용하는 최대 범위에서:',
        }},
        { type: 'ul', items: [
          { en: "The Administration's total liability is limited to the amount actually paid by the User in the last 30 days.", id: "Kewajiban total Administrasi dibatasi pada jumlah yang benar-benar dibayarkan oleh Pengguna dalam 30 hari terakhir.", ru: 'Совокупная ответственность Администрации ограничена суммой, фактически уплаченной Пользователем за последние 30 дней.', es: 'La responsabilidad total de la Administración se limita al importe efectivamente pagado por el Usuario en los últimos 30 días.', zh: '管理方的总责任限于用户在过去30天内实际支付的金额。', fr: "La responsabilité totale de l'Administration est limitée au montant effectivement payé par l'Utilisateur au cours des 30 derniers jours.", de: 'Die Gesamthaftung der Verwaltung ist auf den Betrag begrenzt, den der Nutzer in den letzten 30 Tagen tatsächlich gezahlt hat.', ja: '運営者の総責任は、過去30日間にユーザーが実際に支払った金額に限定されます。', ko: '운영자의 총 책임은 사용자가 최근 30일 동안 실제로 지불한 금액으로 제한됩니다.' },
          { en: 'The Administration is not liable for indirect, incidental, punitive or consequential damages.', id: "Administrasi tidak bertanggung jawab atas kerugian tidak langsung, insidental, hukuman, atau konsekuensial.", ru: 'Администрация не несёт ответственности за косвенные, случайные, штрафные или последующие убытки.', es: 'La Administración no se hace responsable de daños indirectos, incidentales, punitivos o consecuentes.', zh: '管理方不对间接、附带、惩罚性或后果性损害承担责任。', fr: "L'Administration n'est pas responsable des dommages indirects, accessoires, punitifs ou consécutifs.", de: 'Die Verwaltung haftet nicht für indirekte, zufällige, Straf- oder Folgeschäden.', ja: '運営者は、間接的、付随的、懲罰的、または結果的損害について責任を負いません。', ko: '운영자는 간접적, 부수적, 징벌적 또는 결과적 손해에 대해 책임을 지지 않습니다.' },
        ]},
      ],
    },
    {
      heading: {
        en: '6. Intellectual Property Rights', id: "6. Hak Kekayaan Intelektual", ru: '6. Права интеллектуальной собственности', es: '6. Derechos de propiedad intelectual', zh: '6. 知识产权',
        fr: '6. Droits de propriété intellectuelle', de: '6. Rechte des geistigen Eigentums', ja: '6. 知的財産権', ko: '6. 지식재산권',
      },
      blocks: [
        { type: 'p', text: {
          en: 'All rights to the content, design, code and other materials of the platform belong to the Administration. The User is granted a limited, non-exclusive license to use the platform for personal purposes.', id: "Semua hak atas konten, desain, kode, dan materi lain dari platform adalah milik Administrasi. Pengguna diberikan lisensi terbatas, non-eksklusif untuk menggunakan platform untuk tujuan pribadi.", ru: 'Все права на контент, дизайн, код и другие материалы платформы принадлежат Администрации. Пользователю предоставляется ограниченная, неисключительная лицензия на использование платформы в личных целях.', es: 'Todos los derechos sobre el contenido, el diseño, el código y otros materiales de la plataforma pertenecen a la Administración. Se concede al Usuario una licencia limitada y no exclusiva para usar la plataforma con fines personales.', zh: '平台的内容、设计、代码和其他材料的所有权利归管理方所有。用户被授予有限的、非排他性的许可，可将平台用于个人目的。',
          fr: "Tous les droits sur le contenu, le design, le code et les autres éléments de la plateforme appartiennent à l'Administration. L'Utilisateur se voit accorder une licence limitée et non exclusive d'utilisation de la plateforme à des fins personnelles.", de: 'Alle Rechte an Inhalten, Design, Code und anderen Materialien der Plattform gehören der Verwaltung. Dem Nutzer wird eine eingeschränkte, nicht ausschließliche Lizenz zur Nutzung der Plattform für persönliche Zwecke gewährt.', ja: 'プラットフォームのコンテンツ、デザイン、コードおよびその他の素材に関するすべての権利は運営者に帰属します。ユーザーには、個人的な目的でプラットフォームを使用するための限定的かつ非独占的なライセンスが付与されます。', ko: '플랫폼의 콘텐츠, 디자인, 코드 및 기타 자료에 대한 모든 권리는 운영자에게 있습니다. 사용자에게는 개인적 목적으로 플랫폼을 사용할 수 있는 제한적이고 비독점적인 라이선스가 부여됩니다.',
        }},
      ],
    },
    {
      heading: {
        en: '7. Termination of Access', id: "7. Penghentian Akses", ru: '7. Прекращение доступа', es: '7. Terminación del acceso', zh: '7. 终止访问',
        fr: "7. Résiliation de l'accès", de: '7. Beendigung des Zugangs', ja: '7. アクセスの終了', ko: '7. 접근 종료',
      },
      blocks: [
        { type: 'p', text: {
          en: 'The Administration reserves the right, at any time and without explanation, to:', id: "Administrasi berhak, kapan saja dan tanpa penjelasan, untuk:", ru: 'Администрация оставляет за собой право в любое время и без объяснения причин:', es: 'La Administración se reserva el derecho, en cualquier momento y sin explicación, a:', zh: '管理方保留随时且无需解释的权利：',
          fr: "L'Administration se réserve le droit, à tout moment et sans explication, de :", de: 'Die Verwaltung behält sich das Recht vor, jederzeit und ohne Angabe von Gründen:', ja: '運営者は、いつでも理由を説明することなく、以下を行う権利を留保します：', ko: '운영자는 언제든지 이유 설명 없이 다음의 권리를 보유합니다:',
        }},
        { type: 'ul', items: [
          { en: "Block or delete the User's account.", id: "Memblokir atau menghapus akun Pengguna.", ru: 'Заблокировать или удалить аккаунт Пользователя.', es: 'Bloquear o eliminar la cuenta del Usuario.', zh: '封锁或删除用户账户。', fr: "Bloquer ou supprimer le compte de l'Utilisateur.", de: 'Das Konto des Nutzers zu sperren oder zu löschen.', ja: 'ユーザーのアカウントをブロックまたは削除すること。', ko: '사용자의 계정을 차단하거나 삭제할 권리.' },
          { en: 'Modify, suspend or discontinue the platform.', id: "Mengubah, menghentikan, atau menghentikan platform.", ru: 'Изменить, приостановить или прекратить работу платформы.', es: 'Modificar, suspender o descontinuar la plataforma.', zh: '修改、暂停或终止平台运行。', fr: 'Modifier, suspendre ou interrompre la plateforme.', de: 'Die Plattform zu ändern, auszusetzen oder einzustellen.', ja: 'プラットフォームを変更、停止、または終了すること。', ko: '플랫폼을 변경, 중단 또는 종료할 권리.' },
          { en: 'Change the terms of this Agreement.', id: "Mengubah ketentuan Perjanjian ini.", ru: 'Изменить условия настоящего Соглашения.', es: 'Cambiar los términos de este Acuerdo.', zh: '更改本协议的条款。', fr: "Modifier les termes du présent Accord.", de: 'Die Bedingungen dieser Vereinbarung zu ändern.', ja: '本規約の条件を変更すること。', ko: '본 약관의 조건을 변경할 권리.' },
        ]},
      ],
    },
    {
      heading: {
        en: '8. Governing Law', id: "8. Hukum yang Mengatur", ru: '8. Применимое право', es: '8. Ley aplicable', zh: '8. 适用法律',
        fr: '8. Droit applicable', de: '8. Anwendbares Recht', ja: '8. 準拠法', ko: '8. 준거법',
      },
      blocks: [
        { type: 'p', text: {
          en: 'This Agreement is governed by and construed in accordance with applicable law. Any disputes shall be resolved by the competent authorities at the location of the Administration.', id: "Perjanjian ini diatur dan ditafsirkan sesuai dengan hukum yang berlaku. Setiap sengketa akan diselesaikan oleh otoritas yang berwenang di lokasi Administrasi.", ru: 'Настоящее Соглашение регулируется и толкуется в соответствии с применимым законодательством. Любые споры подлежат разрешению в компетентных органах по месту нахождения Администрации.', es: 'Este Acuerdo se rige e interpreta de acuerdo con la ley aplicable. Cualquier disputa se resolverá ante las autoridades competentes en la ubicación de la Administración.', zh: '本协议受适用法律管辖并据其解释。任何争议应由管理方所在地的主管机关解决。',
          fr: "Le présent Accord est régi et interprété conformément à la loi applicable. Tout litige sera résolu par les autorités compétentes du lieu de l'Administration.", de: 'Diese Vereinbarung unterliegt dem geltenden Recht und wird entsprechend ausgelegt. Streitigkeiten werden von den zuständigen Behörden am Sitz der Verwaltung entschieden.', ja: '本規約は適用法に準拠し、これに従って解釈されます。あらゆる紛争は、運営者の所在地の管轄当局において解決されるものとします。', ko: '본 약관은 관련 법률에 따라 규율되고 해석됩니다. 모든 분쟁은 운영자 소재지의 관할 당국에서 해결됩니다.',
        }},
      ],
    },
  ],
  footer: {
    style: 'amber',
    text: {
      en: 'By using the GRAM-City platform, you confirm that you have read, understood and agree to all the terms of this Agreement.', id: "Dengan menggunakan platform GRAM-City, Anda mengonfirmasi bahwa Anda telah membaca, memahami, dan setuju dengan semua ketentuan Perjanjian ini.", ru: 'Используя платформу GRAM-City, вы подтверждаете, что прочитали, поняли и согласны со всеми условиями настоящего Соглашения.', es: 'Al usar la plataforma GRAM-City, usted confirma que ha leído, entendido y acepta todos los términos de este Acuerdo.', zh: '使用 GRAM-City 平台即表示您确认已阅读、理解并同意本协议的所有条款。',
      fr: "En utilisant la plateforme GRAM-City, vous confirmez avoir lu, compris et accepté toutes les conditions du présent Accord.", de: 'Durch die Nutzung der GRAM-City-Plattform bestätigen Sie, dass Sie alle Bedingungen dieser Vereinbarung gelesen, verstanden und akzeptiert haben.', ja: 'GRAM-Cityプラットフォームを利用することにより、お客様は本規約のすべての条件を読み、理解し、同意したことを確認します。', ko: 'GRAM-City 플랫폼을 사용함으로써 귀하는 본 약관의 모든 조건을 읽고 이해하였으며 이에 동의함을 확인합니다.',
    },
  },
};

// Shared UI string: Back button
export const backLabel = {
  en: 'Back', id: "Kembali", ru: 'Назад', es: 'Atrás', zh: '返回', fr: 'Retour', de: 'Zurück', ja: '戻る', ko: '뒤로',
};
