const R = 27;                 // rhombus "radius" in cells
const CORE_R = 13;            // radius of the central diamond (District 1)
const ROAD_STEP = 7;          // a road every 7 cells (blocks of 6x6 buildable cells)
const N = 2 * R + 1;          // grid size (N x N)
const C = R;                  // centre cell
const CELL = 22;              // world pixels per cell

const DISTRICTS = [
  { id: 1, key: 'core',  name: 'Район 1 · Central Core', short: 'Район 1', color: '#ff2bd6',
    quota: { '3x3': 7, '2x2': 8, '1x2': 6, '1x1': 100 } },
  { id: 2, key: 'north', name: 'Район 2 · North Hub',    short: 'Район 2', color: '#00f0ff',
    quota: { '3x3': 6, '2x2': 8, '1x2': 6, '1x1': 99 } },
  { id: 3, key: 'west',  name: 'Район 3 · West District', short: 'Район 3', color: '#ffd84d',
    quota: { '3x3': 6, '2x2': 8, '1x2': 6, '1x1': 99 } },
  { id: 4, key: 'east',  name: 'Район 4 · East District', short: 'Район 4', color: '#39ff88',
    quota: { '3x3': 6, '2x2': 8, '1x2': 6, '1x1': 99 } },
];
const TOTAL_EXPECTED = { all: 478, '3x3': 25, '2x2': 32, '1x2': 24, '1x1': 397 };
const TYPE_COLOR = { '3x3': '#ff2bd6', '2x2': '#00f0ff', '1x2': '#00f0ff', '1x1': '#ffd84d', park: '#39ff88' };

/* ---------- deterministic RNG (same map every time) ---------- */
function mulberry32(seed) {
  return function () {
    seed |= 0; seed = (seed + 0x6D2B79F5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const rand = mulberry32(20261005);

/* ---------- 1. terrain: land, districts, roads ---------- */
const isLand = (x, y) => Math.abs(x - C) + Math.abs(y - C) <= R;

function districtOf(x, y) {
  if (!isLand(x, y)) return 0;
  const dx = x - C, dy = y - C;
  if (Math.abs(dx) + Math.abs(dy) <= CORE_R) return 1;               // central diamond
  const a = Math.atan2(dy, dx) * 180 / Math.PI;                       // screen y points down
  if (a >= -150 && a < -30) return 2;                                 // North: upper 120°
  if (a >= -30 && a < 90) return 4;                                   // East: right / lower-right
  return 3;                                                           // West: left / lower-left
}

const grid = [];          // grid[y][x] = { land, district, road, building|null, park }
for (let y = 0; y < N; y++) {
  grid.push([]);
  for (let x = 0; x < N; x++) grid[y].push({ x, y, land: isLand(x, y), district: districtOf(x, y), road: false, building: null, park: false });
}
const cell = (x, y) => (x >= 0 && y >= 0 && x < N && y < N ? grid[y][x] : null);

for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
  const c = grid[y][x];
  if (!c.land) continue;
  // street grid through the centre
  if ((x - C) % ROAD_STEP === 0 || (y - C) % ROAD_STEP === 0) c.road = true;
  // roads on district borders (right / down neighbour in another district)
  const r = cell(x + 1, y), d = cell(x, y + 1);
  if ((r && r.land && r.district !== c.district) || (d && d.land && d.district !== c.district)) c.road = true;
}
// the outer ring of the rhombus is a coastal promenade
for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
  const c = grid[y][x];
  if (c.land && Math.abs(x - C) + Math.abs(y - C) === R) c.road = true;
}

/* ---------- 2. placement of buildings ---------- */
const buildings = [];
const FOOTPRINTS = { '3x3': [[3, 3]], '2x2': [[2, 2]], '1x2': [[2, 1], [1, 2]], '1x1': [[1, 1]] };

const NAME_PARTS = {
  '3x3': ['Нейро-Цитадель', 'Квантовый Шпиль', 'Мега-Реактор', 'Синдикат', 'Неон-Арена', 'Дата-Монолит', 'Кибер-Банк', 'Голо-Башня'],
  '2x2': ['Фабрика Чипов', 'ИИ-Лаборатория', 'Дрон-Ангар', 'NFT-Студия', 'VR-Клуб', 'Кибер-Кафе', 'Ремзона'],
  '1x2': ['Логистик-Хаб', 'Сервер-Блок', 'Голо-Маркет', 'Неон-Мастерская'],
  '1x1': ['Солнечная станция', 'Шахта кварца', 'Вышка трафика', 'Хладокомбинат', 'Био-ферма', 'Свалка', 'Дата-центр'],
};

function centroid(did) {
  let sx = 0, sy = 0, n = 0;
  for (const row of grid) for (const c of row) if (c.district === did && !c.road) { sx += c.x; sy += c.y; n++; }
  return { x: sx / n, y: sy / n };
}

function fits(did, x, y, w, h) {
  for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) {
    const c = cell(x + i, y + j);
    if (!c || !c.land || c.road || c.building || c.district !== did) return false;
  }
  return true;
}

// how snugly a footprint sits: perimeter cells that are road / built / outside
function snug(x, y, w, h) {
  let s = 0;
  for (let i = -1; i <= w; i++) for (let j = -1; j <= h; j++) {
    if (i >= 0 && i < w && j >= 0 && j < h) continue;
    if ((i === -1 || i === w) && (j === -1 || j === h)) continue;      // skip corners
    const c = cell(x + i, y + j);
    if (!c || !c.land || c.road || c.building) s++;
  }
  return s;
}

function place(did, type, count, ctr) {
  let placed = 0;
  while (placed < count) {
    let best = null;
    for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
      for (const [w, h] of FOOTPRINTS[type]) {
        if (!fits(did, x, y, w, h)) continue;
        const dist = Math.hypot(x + w / 2 - ctr.x, y + h / 2 - ctr.y);
        const perim = 2 * (w + h);
        // tight packing first (avoids fragmenting blocks), then closeness to the centre
        const score = (snug(x, y, w, h) / perim) * 10 - dist * (type === '1x1' ? 0.6 : 0.25) + rand() * 0.15;
        if (!best || score > best.score) best = { x, y, w, h, score };
      }
    }
    if (!best) return placed;                                    // no room left
    const names = NAME_PARTS[type];
    const b = {
      id: 0, districtId: did, type, status: 'active',
      x: best.x, y: best.y, width: best.w, height: best.h,
      name: names[Math.floor(rand() * names.length)],
    };
    buildings.push(b);
    for (let j = 0; j < b.height; j++) for (let i = 0; i < b.width; i++) grid[b.y + j][b.x + i].building = b;
    placed++;
  }
  return placed;
}

/* Parks are spread evenly BEFORE the 1x1 buildings are placed:
   free cells of a district = 1x1 quota + spare cells. The spare cells become
   small squares (2-4 cells) chosen by farthest-point sampling — every new
   square goes as far as possible from the squares already placed — so the
   greenery is scattered over the whole district instead of one corner. */
const PARK_CLUSTER = 4;
function spreadParks(did) {
  const free = [];
  for (const row of grid) for (const c of row) if (c.district === did && c.land && !c.road && !c.building) free.push(c);
  const spare = free.length - DISTRICTS.find(d => d.id === did).quota['1x1'];
  if (spare <= 0) return spare;
  const parks = [];
  const isFree = (c) => c && c.district === did && c.land && !c.road && !c.building && !c.park;
  const minDist2 = (c) => {
    let m = Infinity;
    for (const p of parks) { const dx = p.x - c.x, dy = p.y - c.y, d2 = dx * dx + dy * dy; if (d2 < m) m = d2; }
    return m;
  };
  while (parks.length < spare) {
    // seed: the free cell farthest from every existing park (small jitter breaks ties)
    let seed = null, best = -1;
    for (const c of free) {
      if (c.park) continue;
      const score = (parks.length ? minDist2(c) : 0) + rand() * 0.5;
      if (score > best) { best = score; seed = c; }
    }
    if (!seed) break;
    // grow a small square around the seed: prefer a 2x2 block
    const want = Math.min(PARK_CLUSTER, spare - parks.length);
    let cluster = [seed];
    for (const [ox, oy] of [[0, 0], [-1, 0], [0, -1], [-1, -1]]) {
      const sq = [cell(seed.x + ox, seed.y + oy), cell(seed.x + ox + 1, seed.y + oy), cell(seed.x + ox, seed.y + oy + 1), cell(seed.x + ox + 1, seed.y + oy + 1)];
      if (sq.every(isFree)) { cluster = sq; break; }
    }
    if (cluster.length === 1) {                                   // no 2x2 room: take free neighbours
      for (const [dx, dy] of [[1, 0], [0, 1], [-1, 0], [0, -1]]) { const n = cell(seed.x + dx, seed.y + dy); if (isFree(n)) cluster.push(n); }
    }
    for (const c of cluster.slice(0, want)) { c.park = true; parks.push(c); }
  }
  return spare;
}

const placementErrors = [];
for (const d of DISTRICTS) {
  const ctr = centroid(d.id);
  d.center = ctr;
  for (const type of ['3x3', '2x2', '1x2']) {
    const got = place(d.id, type, d.quota[type], ctr);
    if (got !== d.quota[type]) placementErrors.push(`${d.short}: ${type} — поставлено ${got} из ${d.quota[type]}`);
  }
  const spare = spreadParks(d.id);
  if (spare < 0) placementErrors.push(`${d.short}: не хватает ${-spare} клеток для 1x1`);
  // every remaining free cell of the district gets a 1x1 building
  let got = 0;
  const names = NAME_PARTS['1x1'];
  for (const row of grid) for (const c of row) {
    if (c.district !== d.id || !c.land || c.road || c.building || c.park) continue;
    const b = { id: 0, districtId: d.id, type: '1x1', status: 'active', x: c.x, y: c.y, width: 1, height: 1, name: names[Math.floor(rand() * names.length)] };
    buildings.push(b); c.building = b; got++;
  }
  if (got !== d.quota['1x1']) placementErrors.push(`${d.short}: 1x1 — поставлено ${got} из ${d.quota['1x1']}`);
}
// stable ids: district, then size, then reading order
const TYPE_ORDER = { '3x3': 0, '2x2': 1, '1x2': 2, '1x1': 3 };
buildings.sort((a, b) => a.districtId - b.districtId || TYPE_ORDER[a.type] - TYPE_ORDER[b.type] || a.y - b.y || a.x - b.x);
buildings.forEach((b, i) => { b.id = i + 1; b.name = `${b.name} #${b.id}`; });

// parks / green decor = the cells reserved by spreadParks()
let parkCount = 0;
for (const row of grid) for (const c of row) if (c.land && !c.road && !c.building) { c.park = true; parkCount++; }

