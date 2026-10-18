/**
 * Business skins helper (map re-texturing).
 * Fetches the skin index once and resolves a skin image URL for a given
 * (group, business_type, level) with graceful fallback to the standard group.
 */
const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api`;

let _indexCache = null;
let _sizesCache = null;
let _inflight = null;

export async function fetchSkinsIndex(force = false) {
  if (_indexCache && !force) return _indexCache;
  if (_inflight) return _inflight;
  _inflight = (async () => {
    try {
      const res = await fetch(`${API}/skins/index`, { cache: 'no-store' });
      const data = await res.json();
      // uploaded skins are served by the backend (/api/skins/file/…): make them absolute
      const abs = (u) => (typeof u === 'string' && u.startsWith('/api/') ? `${process.env.REACT_APP_BACKEND_URL || ''}${u}` : u);
      _indexCache = JSON.parse(JSON.stringify(data.index || {}), (k, v) => abs(v));
      _sizesCache = data.sizes || {};
      _metaCache = data.meta || {};
    } catch (e) {
      _indexCache = {};
      _sizesCache = {};
    } finally {
      _inflight = null;
    }
    return _indexCache;
  })();
  return _inflight;
}

let _metaCache = {};
/** Placement on the lot of a skin processed like the city buildings (null for old free-form skins). */
export function resolveSkinMeta(group, type, level) {
  const byType = ((_metaCache || {})[group] || {})[type];
  if (!byType) return null;
  return byType[String(level || 0)] || byType['0'] || null;
}

export function getCachedSkinsIndex() {
  return _indexCache || {};
}

export function getCachedSkinSizes() {
  return _sizesCache || {};
}

/**
 * Resolve the sprite image URL for a business.
 * Order: exact (group,type,level) → group any-level(0) → group first →
 *        standard(type,level) → standard any-level → null (engine falls back).
 *
 * Business-type aliases: the frontend building catalogue and the backend map
 * config historically use different keys for the same business (e.g. the
 * cold-storage / "Холодильник" is `cooler` in the FE catalogue but
 * `cold_storage` on the map). A skin saved under one key must still resolve
 * when the live business carries the other key, so we try both.
 */
const TYPE_ALIASES = {
  cold_storage: 'cooler', cooler: 'cold_storage',
  signal_tower: 'signal', signal: 'signal_tower',
  scrap_yard: 'scrap', scrap: 'scrap_yard',
};

export function resolveSkinUrl(index, group, type, level) {
  if (!index || !type) return null;
  const lvl = String(level || 1);
  const alias = TYPE_ALIASES[type];
  const pick = (byType) => (byType ? (byType[lvl] || byType['0'] || Object.values(byType)[0] || null) : null);
  const tryGroup = (g) => {
    if (!index[g]) return null;
    return pick(index[g][type]) || (alias ? pick(index[g][alias]) : null);
  };
  return tryGroup(group || 'standard') || (group !== 'standard' ? tryGroup('standard') : null);
}

/**
 * Resolve the admin-configured display size (percent of original) for a skin,
 * using the SAME fallback order as resolveSkinUrl. Returns { h, w } in percent
 * (100 = original) — defaults to 100/100 when nothing is configured.
 */
export function resolveSkinSize(sizes, group, type, level) {
  const def = { h: 100, w: 100 };
  if (!sizes || !type) return def;
  const lvl = String(level || 1);
  const alias = TYPE_ALIASES[type];
  const pick = (byType) => (byType ? (byType[lvl] || byType['0'] || Object.values(byType)[0] || null) : null);
  const tryGroup = (g) => {
    if (!sizes[g]) return null;
    return pick(sizes[g][type]) || (alias ? pick(sizes[g][alias]) : null);
  };
  const found = tryGroup(group || 'standard') || (group !== 'standard' ? tryGroup('standard') : null);
  return found ? { h: found.h ?? 100, w: found.w ?? 100 } : def;
}
