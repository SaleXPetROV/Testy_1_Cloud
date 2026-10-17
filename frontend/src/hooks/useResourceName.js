/**
 * useResourceName — single source of truth for localized resource names.
 *
 * Backed by `RESOURCE_NAMES` in `lib/resourceConfig.js` (the canonical
 * dictionary kept in sync with backend `business_config.RESOURCE_TYPES`).
 *
 * Usage:
 *   const { name, withTier, icon } = useResourceName();
 *   <span>{icon('energy')} {name('energy')}</span>
 *   <span>{withTier('scrap', 1)}</span>  // "Метал (T1)"
 *
 * `withTier` accepts either an explicit tier or — if omitted — reads the tier
 * from `RESOURCES[code].tier`.
 */
import { useCallback } from 'react';
import { useLanguage } from '@/context/LanguageContext';
import { RESOURCES, getResourceName } from '@/lib/resourceConfig';

export function useResourceName() {
  const { language } = useLanguage();

  const name = useCallback(
    (code) => (code ? getResourceName(code, language) : ''),
    [language],
  );

  const withTier = useCallback(
    (code, tier) => {
      if (!code) return '';
      const t = tier ?? RESOURCES[code]?.tier;
      const n = getResourceName(code, language);
      return t ? `${n} (T${t})` : n;
    },
    [language],
  );

  const icon = useCallback((code) => RESOURCES[code]?.icon || '📦', []);
  const tier = useCallback((code) => RESOURCES[code]?.tier, []);

  return { name, withTier, icon, tier, language };
}

export default useResourceName;
