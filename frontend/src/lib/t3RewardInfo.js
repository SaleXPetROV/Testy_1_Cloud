/**
 * Static metadata for the 7 Tier-3 resources awarded as the tutorial-completion
 * (or tutorial-skip) reward. This file is the FRONTEND MIRROR of
 * `RESOURCE_BUFFS` in `/app/backend/routes/buffs.py` — the SAME buff card the
 * user sees when they click a T3 resource in "My Resources" (see picture 2 in
 * the bug report). Icons and effect descriptions MUST match RESOURCE_BUFFS.
 *
 * Whenever `RESOURCE_BUFFS` changes on the backend, this table must be
 * updated in lockstep to avoid the mismatch bug reported by the user.
 *
 * For every resource we provide:
 *   - icon: emoji used in selects / cards (kept in sync with backend)
 *   - fallback: bonus description per language (mirror of backend `description`)
 *
 * Picking a resource auto-activates the linked buff on the user's *first*
 * real business purchase (backend hook in `routes/tutorial.py`).
 */
export const T3_REWARD_INFO = {
  neuro_core: {
    icon: '🔮',
    fallback: {
      ru: '+8% к производству всех бизнесов',
      en: '+8% production for all businesses',
      es: '+8% de producción en todos los negocios',
      zh: '所有业务生产 +8%',
      fr: '+8% de production sur toutes les entreprises',
      de: '+8% Produktion für alle Unternehmen',
      ja: '全ビジネスの生産量 +8%',
      ko: '모든 비즈니스 생산량 +8%',
    },
  },
  gold_bill: {
    icon: '📜',
    fallback: {
      ru: '-20% к стоимости ремонта',
      en: '-20% repair cost',
      es: '-20% en el coste de reparación',
      zh: '维修费用 -20%',
      fr: '-20% sur les coûts de réparation',
      de: '-20% Reparaturkosten',
      ja: '修理費用 -20%',
      ko: '수리 비용 -20%',
    },
  },
  license_token: {
    icon: '🎫',
    fallback: {
      ru: '-15% к торговой комиссии',
      en: '-15% trading fee',
      es: '-15% en la comisión de comercio',
      zh: '交易手续费 -15%',
      fr: '-15% sur les frais de trade',
      de: '-15% Handelsgebühr',
      ja: '取引手数料 -15%',
      ko: '거래 수수료 -15%',
    },
  },
  luck_chip: {
    icon: '🎲',
    fallback: {
      ru: '+5% шанс x2 производства',
      en: '+5% chance of x2 production',
      es: '+5% de probabilidad de producción x2',
      zh: '双倍生产几率 +5%',
      fr: '+5% de chance de production x2',
      de: '+5% Chance auf x2 Produktion',
      ja: '生産x2の確率 +5%',
      ko: 'x2 생산 확률 +5%',
    },
  },
  war_protocol: {
    icon: '⚔️',
    fallback: {
      ru: '-25% к скорости износа зданий',
      en: '-25% building wear rate',
      es: '-25% en la tasa de desgaste de edificios',
      zh: '建筑磨损速度 -25%',
      fr: "-25% sur l'usure des bâtiments",
      de: '-25% Gebäudeverschleiß',
      ja: '建物の劣化速度 -25%',
      ko: '건물 마모 속도 -25%',
    },
  },
  bio_module: {
    icon: '🧬',
    fallback: {
      ru: '-10% к потреблению ресурсов',
      en: '-10% resource consumption',
      es: '-10% en el consumo de recursos',
      zh: '资源消耗 -10%',
      fr: '-10% de consommation de ressources',
      de: '-10% Ressourcenverbrauch',
      ja: 'リソース消費 -10%',
      ko: '자원 소비 -10%',
    },
  },
  gateway_code: {
    icon: '🔑',
    fallback: {
      ru: '-25% к комиссии на вывод',
      en: '-25% withdrawal fee',
      es: '-25% en la comisión de retiro',
      zh: '提现手续费 -25%',
      fr: '-25% sur les frais de retrait',
      de: '-25% Auszahlungsgebühr',
      ja: '出金手数料 -25%',
      ko: '출금 수수료 -25%',
    },
  },
};

export const T3_REWARD_OPTIONS = Object.keys(T3_REWARD_INFO);

/** Return the localized bonus description for a T3 resource id. */
export function getT3BonusDescription(resourceId, lang = 'en') {
  const info = T3_REWARD_INFO[resourceId];
  if (!info) return '';
  return info.fallback[lang] || info.fallback.en || info.fallback.ru || '';
}

export function getT3Icon(resourceId) {
  return T3_REWARD_INFO[resourceId]?.icon || '🎁';
}
