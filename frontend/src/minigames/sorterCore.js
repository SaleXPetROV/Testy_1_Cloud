/**
 * «Сортировщик» — ENDLESS solo mode, IDENTICAL to backend/minigames_sorter.py (the server replays the score).
 * Items come one by one, faster and faster; each goes to its bin (0 metal, 1 battery, 2 chip, 3 glass)
 * before its time window ends, a hazard ☢ must be PASSED (action -1). 3 lives: a wrong bin, a sorted
 * hazard or a missed item costs one. The game lasts as long as the player keeps lives.
 */
export const MAX_ITEMS = 400;          // safety cap (nobody gets there: windows end at 450 ms)
export const LIVES = 3;
export const GAP_MS = 250;            // pause between items
export const MIN_REACTION_MS = 150;   // faster than a human: the tap is ignored
export const BINS = 4;

function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1) >>> 0;
    t = (t ^ (t + (Math.imul(t ^ (t >>> 7), t | 61) >>> 0))) >>> 0;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Item i: its bin, hazard or not, its time window (1600 ms -> 450 ms at item 120). */
export function makeItems(seed, n = MAX_ITEMS) {
  const r = mulberry32(seed);
  const items = [];
  for (let i = 0; i < n; i++) {
    const type = Math.floor(r() * BINS);
    const hazard = r() < 0.08 + 0.22 * Math.min(1, i / 150);
    const window = Math.max(450, Math.round(1600 - 1150 * Math.min(1, i / 120)));
    items.push({ i, type, hazard, window });
  }
  return items;
}

/** Points of a right answer: 10 × streak multiplier (×1, ×2 from 5 in a row, ×3 from 10). */
export const mult = (combo) => Math.min(3, 1 + Math.floor(combo / 5));

/** Replays the actions [{i, b, t}] (b = bin 0..3 or -1 = pass, t = ms since start). */
export function score(seed, actions) {
  const items = makeItems(seed);
  const byItem = new Map();
  for (const a of actions || []) if (!byItem.has(a.i)) byItem.set(a.i, a);
  let at = 0, pts = 0, combo = 0, cleared = 0, best = 0, lives = LIVES, last = -1;
  for (const it of items) {
    if (lives <= 0) break;
    const a = byItem.get(it.i);
    const end = at + it.window;
    let resolved = end, ok;
    if (a && a.t >= at + MIN_REACTION_MS && a.t <= end) {
      resolved = a.t;
      ok = it.hazard ? a.b === -1 : a.b === it.type;
    } else {
      ok = it.hazard;                  // untouched hazard passes by itself; a missed item is a mistake
    }
    if (ok) { combo += 1; cleared += 1; pts += 10 * mult(combo); } else { lives -= 1; combo = 0; }
    best = Math.max(best, combo);
    last = it.i;
    at = resolved + GAP_MS;
  }
  return { points: pts, cleared, best_combo: best, lives_left: lives, last_item: last, duration_ms: at };
}

/** Stars by points (thresholds set in the admin). */
export function stars(points, th = [300, 1000, 2000]) {
  return points >= th[2] ? 3 : points >= th[1] ? 2 : points >= th[0] ? 1 : 0;
}
