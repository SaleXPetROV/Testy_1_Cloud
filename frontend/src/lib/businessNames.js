/**
 * Business type translations across 8 languages.
 * Keys match backend `business_type` (lowercase snake_case).
 *
 * Used by the transaction-history detail view to render
 * human-friendly business names instead of raw keys
 * (e.g. "signal_tower" -> "Вышка Трафика" in ru).
 */
export const BUSINESS_NAMES = {
  // Tier 1 — resource base
  helios:        { en: 'Helios Solar',  ru: 'Солнечная станция', es: 'Helios Solar',   zh: '太阳能电站',     fr: 'Station Solaire',     de: 'Solarkraftwerk',     ja: '太陽光発電所',     ko: '태양광 발전소' },
  nano_dc:       { en: 'Nano DC',       ru: 'Дата-центр',        es: 'Centro de Datos', zh: '数据中心',     fr: 'Data Center',         de: 'Rechenzentrum',      ja: 'データセンター',   ko: '데이터 센터' },
  quartz_mine:   { en: 'Quartz Mine',   ru: 'Шахта Кварца',      es: 'Mina de Cuarzo', zh: '石英矿',         fr: 'Mine de Quartz',      de: 'Quarzmine',          ja: '石英鉱山',         ko: '석영 광산' },
  signal_tower:  { en: 'Signal Tower',  ru: 'Вышка Трафика',     es: 'Torre de Señal', zh: '信号塔',         fr: 'Tour de Signal',      de: 'Funkturm',           ja: '信号塔',           ko: '신호 송신탑' },
  hydro_cooling: { en: 'Cooler',        ru: 'Хладокомбинат',     es: 'Refrigerador',   zh: '冷却中心',       fr: 'Centre de Refroidissement', de: 'Kühlanlage',   ja: '冷却施設',         ko: '냉각 시설' },
  bio_farm:      { en: 'Bio Farm',      ru: 'Био-ферма',         es: 'Granja Bio',     zh: '生物农场',       fr: 'Bio Ferme',           de: 'Bio-Farm',           ja: 'バイオファーム',   ko: '바이오 농장' },
  scrap_yard:    { en: 'Scrap Yard',    ru: 'Свалка',            es: 'Chatarrería',    zh: '废料场',         fr: 'Casse',               de: 'Schrottplatz',       ja: 'スクラップ場',     ko: '고철장' },

  // Tier 2 — production
  chips_factory: { en: 'Chips Factory', ru: 'Завод Микросхем',   es: 'Fábrica de Chips', zh: '芯片工厂',     fr: 'Usine de Puces',      de: 'Chip-Fabrik',        ja: 'チップ工場',       ko: '칩 공장' },
  nft_studio:    { en: 'NFT Studio',    ru: 'NFT-Студия',        es: 'Estudio NFT',    zh: 'NFT 工作室',     fr: 'Studio NFT',          de: 'NFT-Studio',         ja: 'NFTスタジオ',      ko: 'NFT 스튜디오' },
  ai_lab:        { en: 'AI Lab',        ru: 'Лаборатория ИИ',    es: 'Laboratorio IA', zh: 'AI 实验室',      fr: 'Laboratoire IA',      de: 'KI-Labor',           ja: 'AIラボ',           ko: 'AI 연구소' },
  logistics_hub: { en: 'Logistics Hub', ru: 'Логистический Ангар', es: 'Centro Logístico', zh: '物流中心', fr: 'Hub Logistique',      de: 'Logistik-Hub',       ja: '物流ハブ',         ko: '물류 허브' },
  cyber_cafe:    { en: 'Cyber Cafe',    ru: 'Кибер-кафе',        es: 'Ciber Café',     zh: '网咖',           fr: 'Cyber Café',          de: 'Cyber-Café',         ja: 'サイバーカフェ',   ko: '사이버 카페' },
  repair_shop:   { en: 'Repair Shop',   ru: 'Ремзона',           es: 'Taller',         zh: '维修店',         fr: 'Atelier',             de: 'Reparaturwerkstatt', ja: '修理工房',         ko: '수리점' },
  vr_club:       { en: 'VR Club',       ru: 'VR-Клуб',           es: 'Club VR',        zh: 'VR 俱乐部',      fr: 'Club VR',             de: 'VR-Club',            ja: 'VRクラブ',         ko: 'VR 클럽' },

  // Tier 3 — financial
  validator:     { en: 'Validator',     ru: 'Валидатор',         es: 'Validador',      zh: '验证者',         fr: 'Validateur',          de: 'Validator',          ja: 'バリデータ',       ko: '검증자' },
  gram_bank:     { en: 'Gram Bank',     ru: 'Грам-банк',         es: 'Gram Bank',      zh: 'Gram 银行',      fr: 'Banque Gram',         de: 'Gram-Bank',          ja: 'グラムバンク',     ko: '그램 은행' },
  dex:           { en: 'DEX',           ru: 'DEX-биржа',         es: 'DEX',            zh: 'DEX 交易所',     fr: 'DEX',                 de: 'DEX',                ja: 'DEX',              ko: 'DEX' },
  casino:        { en: 'Casino',        ru: 'Казино',            es: 'Casino',         zh: '赌场',           fr: 'Casino',              de: 'Kasino',             ja: 'カジノ',           ko: '카지노' },
  arena:         { en: 'Arena',         ru: 'Арена',             es: 'Arena',          zh: '竞技场',         fr: 'Arène',               de: 'Arena',              ja: 'アリーナ',         ko: '아레나' },
  incubator:     { en: 'Incubator',     ru: 'Инкубатор',         es: 'Incubadora',     zh: '孵化器',         fr: 'Incubateur',          de: 'Inkubator',          ja: 'インキュベーター', ko: '인큐베이터' },
  bridge:        { en: 'Bridge',        ru: 'Мост',              es: 'Puente',         zh: '跨链桥',         fr: 'Pont',                de: 'Brücke',             ja: 'ブリッジ',         ko: '브리지' },
};

/**
 * Resolve a business-type key (or i18n object) to a localized string.
 * Accepts:
 *   - "signal_tower"            -> uses BUSINESS_NAMES map
 *   - { en: "...", ru: "..." }  -> picks current language with fallback to en
 *   - any other string          -> returned untouched
 */
export function getBusinessName(value, lang = 'en') {
  if (!value) return '';
  // Object form (already i18n)
  if (typeof value === 'object') {
    return value[lang] || value.en || value.ru || Object.values(value)[0] || '';
  }
  // String form (config key)
  if (typeof value === 'string') {
    const entry = BUSINESS_NAMES[value];
    if (entry) return entry[lang] || entry.en || value;
    // Fallback: humanize the key (signal_tower -> Signal Tower)
    return value
      .split('_')
      .map(w => w.charAt(0).toUpperCase() + w.slice(1))
      .join(' ');
  }
  return String(value);
}
