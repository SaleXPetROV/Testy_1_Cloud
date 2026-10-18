// URL of the city-map sprite for a business (same picture as on the map), by type and level.
// Sprites replaced by the admin («Спрайты и скины») win over the built-in ones.
const TO_SPRITE = { chip_factory: 'chips_factory', logistics: 'logistics_hub', repair_zone: 'repair_shop', cold_storage: 'hydro_cooling' };
const KNOWN = new Set(['helios', 'nano_dc', 'quartz_mine', 'signal_tower', 'hydro_cooling', 'bio_farm', 'scrap_yard',
  'chips_factory', 'nft_studio', 'ai_lab', 'logistics_hub', 'cyber_cafe', 'repair_shop', 'vr_club',
  'validator', 'gram_bank', 'dex', 'casino', 'arena', 'incubator', 'bridge']);
const BACKEND = process.env.REACT_APP_BACKEND_URL || '';
let OVERRIDES = {};
let loading = null;
export function loadCitySpriteOverrides() {
  if (!loading) {
    loading = fetch(`${BACKEND}/api/city-sprites/tuning`).then((r) => (r.ok ? r.json() : {}))
      .then((d) => { OVERRIDES = d.overrides || {}; return OVERRIDES; }).catch(() => OVERRIDES);
  }
  return loading;
}
loadCitySpriteOverrides();

export function citySpriteUrl(type, level = 0) {
  const t = TO_SPRITE[type] || type;
  if (!KNOWN.has(t)) return null;
  const stage = String(level <= 3 ? 1 : level <= 6 ? 2 : 3);
  const ov = (OVERRIDES[t] || {})[stage];
  return ov ? `${BACKEND}${ov.url}` : `/sprites/city/${t}/stage${stage}.webp`;
}
