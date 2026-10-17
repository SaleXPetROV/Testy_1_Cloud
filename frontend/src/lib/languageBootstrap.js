// Synchronous-friendly language bootstrap.
// Resolves the user's preferred language BEFORE the React tree mounts,
// so the UI never renders in the wrong language and then flickers.

const SUPPORTED = ['en', 'ru', 'es', 'zh', 'fr', 'de', 'ja', 'ko', 'id'];

const COUNTRY_TO_LANG = {
  // Russian-speaking
  RU: 'ru', BY: 'ru', KZ: 'ru', KG: 'ru', TJ: 'ru', UZ: 'ru', AM: 'ru', AZ: 'ru', MD: 'ru',
  // Spanish-speaking
  ES: 'es', MX: 'es', AR: 'es', CO: 'es', CL: 'es', PE: 'es', VE: 'es', EC: 'es', GT: 'es',
  CU: 'es', DO: 'es', HN: 'es', SV: 'es', NI: 'es', CR: 'es', PA: 'es', PR: 'es', UY: 'es', PY: 'es', BO: 'es',
  // Chinese-speaking
  CN: 'zh', TW: 'zh', HK: 'zh', MO: 'zh', SG: 'zh',
  // French-speaking
  FR: 'fr', BE: 'fr', CH: 'fr', CA: 'fr', LU: 'fr', MC: 'fr',
  // German-speaking
  DE: 'de', AT: 'de',
  // Japanese
  JP: 'ja',
  // Korean
  KR: 'ko',
  // Indonesian
  ID: 'id',
  // English-speaking (default)
  US: 'en', GB: 'en', AU: 'en', NZ: 'en', IE: 'en', ZA: 'en', IN: 'en',
};

const STORAGE_KEY = 'ton_city_lang';
const EXPLICIT_KEY = 'ton_city_lang_explicit';   // set when the user picks a language manually
const DETECTED_FLAG = 'ton_city_lang_geo_v2';    // bumped to re-evaluate legacy browser-locale fallbacks

export const SUPPORTED_LANGS = SUPPORTED;

function withTimeout(promise, ms) {
  return new Promise((resolve) => {
    let done = false;
    const t = setTimeout(() => { if (!done) { done = true; resolve(null); } }, ms);
    promise.then(
      (val) => { if (!done) { done = true; clearTimeout(t); resolve(val); } },
      () => { if (!done) { done = true; clearTimeout(t); resolve(null); } }
    );
  });
}

async function fetchCountryCode() {
  // Try several free providers; return first country code we get.
  const providers = [
    async () => {
      const r = await fetch('https://ipapi.co/json/', { mode: 'cors' });
      if (!r.ok) return null;
      const d = await r.json();
      return d?.country_code || d?.country || null;
    },
    async () => {
      const r = await fetch('https://ipwho.is/');
      if (!r.ok) return null;
      const d = await r.json();
      return d?.country_code || null;
    },
  ];
  for (const p of providers) {
    const cc = await withTimeout(p().catch(() => null), 1500);
    if (cc) return cc;
  }
  return null;
}

/**
 * Resolve the language to use BEFORE first render and persist it to localStorage.
 * Policy (per product): the DEFAULT language is ENGLISH. We try to adapt to the
 * user's GEO (IP country) as a nice-to-have, but if geo can't be determined we
 * fall back to English — NOT the device/browser locale (so a Russian phone in
 * an unknown geo still starts in English).
 * Order:
 *   1) explicit manual choice (localStorage EXPLICIT_KEY) → always respected
 *   2) IP geolocation (one-time, cached via DETECTED_FLAG)
 *   3) 'en'
 */
export async function bootstrapLanguage() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    const explicit = localStorage.getItem(EXPLICIT_KEY) === '1';

    // Respect a manual choice forever.
    if (explicit && stored && SUPPORTED.includes(stored)) {
      return stored;
    }

    // Auto-detected value already cached under the current policy version.
    const alreadyDetected = localStorage.getItem(DETECTED_FLAG) === '1';
    if (alreadyDetected && stored && SUPPORTED.includes(stored)) {
      return stored;
    }

    // First-time (or policy bumped): try geo detection now.
    const cc = await fetchCountryCode();
    const detected = cc ? COUNTRY_TO_LANG[cc.toUpperCase()] : null;
    localStorage.setItem(DETECTED_FLAG, '1');
    const resolved = (detected && SUPPORTED.includes(detected)) ? detected : 'en';
    localStorage.setItem(STORAGE_KEY, resolved);
    return resolved;
  } catch {
    return 'en';
  }
}
