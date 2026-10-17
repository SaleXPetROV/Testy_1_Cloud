/* Isometric render of the approved district layout (layout_gen.js) with the city sprites. */
const TW = 48, TH = 24;                                  // half-size of a tile diamond
const MARGIN = 140, HEADROOM = 560;
let minX = 1e9, maxX = -1e9, minY = 1e9, maxY = -1e9;
for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) if (isLand(x, y)) {
  for (const [a, b] of [[x, y], [x + 1, y], [x, y + 1], [x + 1, y + 1]]) { const sx = (a - b) * TW, sy = (a + b) * TH;
    minX = Math.min(minX, sx); maxX = Math.max(maxX, sx); minY = Math.min(minY, sy); maxY = Math.max(maxY, sy); } }
const W = Math.ceil(maxX - minX + 2 * MARGIN), H = Math.ceil(maxY - minY + HEADROOM + MARGIN + 60);
const OX = MARGIN - minX, OY = HEADROOM - minY;
const iso = (gx, gy) => [OX + (gx - gy) * TW, OY + (gx + gy) * TH];
const DCOL = { 1: '#ff2bd6', 2: '#00f0ff', 3: '#ffd84d', 4: '#39ff88' };
const R2 = mulberry32(777);

const cv = document.getElementById('cv'); cv.width = W; cv.height = H;
const g = cv.getContext('2d');

function diamond(x, y) { return [iso(x, y), iso(x + 1, y), iso(x + 1, y + 1), iso(x, y + 1)]; }
function fillPoly(pts, fill, stroke, lw = 1) {
  g.beginPath(); g.moveTo(pts[0][0], pts[0][1]); for (const p of pts.slice(1)) g.lineTo(p[0], p[1]); g.closePath();
  if (fill) { g.fillStyle = fill; g.fill(); } if (stroke) { g.strokeStyle = stroke; g.lineWidth = lw; g.stroke(); }
}
function hexA(hex, a) { const n = parseInt(hex.slice(1), 16); return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`; }

/* ---------------- sea ---------------- */
function drawSea() {
  const gr = g.createRadialGradient(W / 2, H / 2, 200, W / 2, H / 2, W * 0.75);
  gr.addColorStop(0, '#0b3b63'); gr.addColorStop(0.55, '#072a4a'); gr.addColorStop(1, '#030d1c');
  g.fillStyle = gr; g.fillRect(0, 0, W, H);
  g.strokeStyle = 'rgba(120,220,255,0.10)'; g.lineWidth = 2;
  for (let k = 0; k < 420; k++) {                                   // little wave dashes
    const x = R2() * W, y = R2() * H, l = 14 + R2() * 26;
    g.beginPath(); g.moveTo(x, y); g.lineTo(x + l, y + l / 2); g.stroke();
  }
}

/* ---------------- island cliff (raised above the water) ---------------- */
function drawCliff() {
  const D = 34;                                                       // cliff height in px
  for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
    const c = grid[y][x]; if (!c.land) continue;
    const r = cell(x + 1, y), d = cell(x, y + 1);
    if (!d || !d.land) {                                              // front-left face
      const a = iso(x, y + 1), b = iso(x + 1, y + 1);
      fillPoly([a, b, [b[0], b[1] + D], [a[0], a[1] + D]], '#1a2340', '#0a0e1a', 1);
    }
    if (!r || !r.land) {                                              // front-right face
      const a = iso(x + 1, y), b = iso(x + 1, y + 1);
      fillPoly([a, b, [b[0], b[1] + D], [a[0], a[1] + D]], '#11182e', '#0a0e1a', 1);
    }
  }
  // neon water line along the base of the cliff
  g.strokeStyle = 'rgba(0,240,255,0.55)'; g.lineWidth = 3; g.shadowColor = '#00f0ff'; g.shadowBlur = 14;
  for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
    const c = grid[y][x]; if (!c.land) continue;
    const r = cell(x + 1, y), d = cell(x, y + 1);
    if (!d || !d.land) { const a = iso(x, y + 1), b = iso(x + 1, y + 1); g.beginPath(); g.moveTo(a[0], a[1] + 34); g.lineTo(b[0], b[1] + 34); g.stroke(); }
    if (!r || !r.land) { const a = iso(x + 1, y), b = iso(x + 1, y + 1); g.beginPath(); g.moveTo(a[0], a[1] + 34); g.lineTo(b[0], b[1] + 34); g.stroke(); }
  }
  g.shadowBlur = 0;
}

/* ---------------- ground ---------------- */
function drawGround() {
  for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
    const c = grid[y][x]; if (!c.land) continue;
    const pts = diamond(x, y);
    const coast = (typeof SQUARE !== 'undefined' ? Math.max(Math.abs(x - C), Math.abs(y - C)) : Math.abs(x - C) + Math.abs(y - C)) === R;
    if (c.road) fillPoly(pts, coast ? '#3a4766' : '#232a3f', '#1b2133', 1);
    else if (c.park) {
      fillPoly(pts, (x * 7 + y * 3) % 3 ? '#2f7d55' : '#2c744f', '#28684a', 1);
    } else {
      const b = c.building;
      const big = b && (b.type === '3x3' || b.type === '2x2');
      // lots: light paving (plazas of big lots are a bit warmer)
      fillPoly(pts, big ? ((x + y) % 2 ? '#4d5a7c' : '#485575') : ((x + y) % 2 ? '#434f6e' : '#3f4a68'), '#353f5c', 1);
    }
  }
  // plaza borders for big lots (tier colour, subtle)
  for (const b of buildings) {
    if (b.type === '1x1') continue;
    const col = b.type === '3x3' ? '#ffd84d' : '#b36bff';
    const pts = [iso(b.x + 0.08, b.y + 0.08), iso(b.x + b.width - 0.08, b.y + 0.08), iso(b.x + b.width - 0.08, b.y + b.height - 0.08), iso(b.x + 0.08, b.y + b.height - 0.08)];
    fillPoly(pts, null, hexA(col, 0.45), 2);
  }
  // lane markings + sidewalk edges
  g.lineWidth = 2;
  for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
    const c = grid[y][x]; if (!c.road) continue;
    const ctr = iso(x + 0.5, y + 0.5);
    const rr = cell(x + 1, y), dd = cell(x, y + 1);
    g.strokeStyle = 'rgba(255,214,90,0.32)'; g.setLineDash([6, 8]);
    if (rr && rr.road) { const e = iso(x + 1.5, y + 0.5); g.beginPath(); g.moveTo(ctr[0], ctr[1]); g.lineTo(e[0], e[1]); g.stroke(); }
    if (dd && dd.road) { const e = iso(x + 0.5, y + 1.5); g.beginPath(); g.moveTo(ctr[0], ctr[1]); g.lineTo(e[0], e[1]); g.stroke(); }
    g.setLineDash([]);
  }
  // coastal promenade railing
  g.strokeStyle = 'rgba(160,240,255,0.7)'; g.lineWidth = 2;
  for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
    const c = grid[y][x]; if (!c.land) continue;
    for (const [dx, dy, a, b] of [[1, 0, [x + 1, y], [x + 1, y + 1]], [0, 1, [x, y + 1], [x + 1, y + 1]], [-1, 0, [x, y], [x, y + 1]], [0, -1, [x, y], [x + 1, y]]]) {
      const o = cell(x + dx, y + dy);
      if (!o || !o.land) { const p = iso(...a), q = iso(...b); g.beginPath(); g.moveTo(p[0], p[1] - 4); g.lineTo(q[0], q[1] - 4); g.stroke(); }
    }
  }
  // district borders (glowing, on the ground)
  for (const d of DISTRICTS) {
    g.strokeStyle = hexA(d.color, 0.6); g.lineWidth = 2.5; g.shadowColor = d.color; g.shadowBlur = 10;
    g.beginPath();
    for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
      const c = grid[y][x]; if (c.district !== d.id) continue;
      for (const [dx, dy, a, b] of [[1, 0, [x + 1, y], [x + 1, y + 1]], [0, 1, [x, y + 1], [x + 1, y + 1]]]) {
        const o = cell(x + dx, y + dy);
        if (o && o.land && o.district && o.district !== d.id) { const p = iso(...a), q = iso(...b); g.moveTo(p[0], p[1]); g.lineTo(q[0], q[1]); }
      }
    }
    g.stroke(); g.shadowBlur = 0;
  }
}

/* ---------------- objects (depth-sorted) ---------------- */
const SPR = {};
function stageFor(id) { const r = mulberry32(id * 9301 + 49297)(); return r < 0.58 ? 1 : r < 0.87 ? 2 : 3; }
const TYPE_POOL = {
  '1x1': ['helios', 'nano_dc', 'quartz_mine', 'signal_tower', 'hydro_cooling', 'bio_farm', 'scrap_yard'],
  '2x2': ['chips_factory', 'nft_studio', 'ai_lab', 'logistics_hub'],
  '1x2': ['cyber_cafe', 'repair_shop', 'vr_club'],
  '3x3': ['validator', 'gram_bank', 'dex', 'casino', 'arena', 'incubator', 'bridge'],
};
// business type per slot: even mix inside each size class (deterministic)
const counters = {};
for (const b of buildings) {
  const pool = TYPE_POOL[b.type]; counters[b.type] = (counters[b.type] || 0) + 1;
  b.btype = pool[(counters[b.type] * 5 + b.districtId * 3) % pool.length];
  b.stage = stageFor(b.id);
}
function spriteBox(b, stage) {
  const meta = MANIFEST.types[b.btype], fm = (meta.files_meta || {})[stage] || meta;
  const tune = ((typeof TUNING !== 'undefined' && TUNING[b.btype]) || {})[stage] || {};
  const [cx, cy] = iso(b.x + b.width / 2, b.y + b.height / 2);
  const slotW = (b.width + b.height) * TW;
  const k = (MANIFEST.display_scale || {})[b.type] || 1;
  const size = fm.size || [320, 400];
  const dw = slotW * k / fm.footprint_width * (tune.scale || 1), dh = dw * size[1] / size[0];
  const lotLong = b.width === b.height ? null : (b.height > b.width ? 'y' : 'x');
  const mirror = !!(fm.long_axis && lotLong && fm.long_axis !== lotLong);
  const ox = (tune.dx || 0) * slotW, oy = (tune.dy || 0) * slotW;
  const x = cx - dw * fm.anchor[0] + ox, y = cy - dh * fm.anchor[1] + oy;
  return { x, y, dw, dh, cx: cx + ox, top: y + dh * (fm.top ?? 0.1), mirror };
}
function drawBuilding(b) {
  const stage = b.owner === 'none' ? 1 : b.stage;
  const img = SPR[`${b.btype}/stage${stage}`]; if (!img) return;
  const s = spriteBox(b, stage);
  if (b.owner === 'none' && b.available) {
    const pts = [iso(b.x + 0.06, b.y + 0.06), iso(b.x + b.width - 0.06, b.y + 0.06), iso(b.x + b.width - 0.06, b.y + b.height - 0.06), iso(b.x + 0.06, b.y + b.height - 0.06)];
    g.shadowColor = '#39ff88'; g.shadowBlur = 10; fillPoly(pts, null, 'rgba(57,255,136,0.85)', 2.5); g.shadowBlur = 0;
  }
  g.save();
  if (s.mirror) { g.translate(s.cx, 0); g.scale(-1, 1); g.translate(-s.cx, 0); }
  g.drawImage(img, s.x, s.y, s.dw, s.dh);
  g.restore();
}
function drawFreeLot(b) {                        // empty lot: holographic ghost of the future building
  const pts = [iso(b.x + 0.1, b.y + 0.1), iso(b.x + b.width - 0.1, b.y + 0.1), iso(b.x + b.width - 0.1, b.y + b.height - 0.1), iso(b.x + 0.1, b.y + b.height - 0.1)];
  const col = b.available ? '#39ff88' : '#7a86a6';
  g.setLineDash([8, 6]); fillPoly(pts, b.available ? 'rgba(57,255,136,0.10)' : 'rgba(122,134,166,0.08)', col, 2); g.setLineDash([]);
  const img = SPR[`${b.btype}/stage1`];
  if (img && b.available) {
    const meta = MANIFEST.types[b.btype], [cx, cy] = iso(b.x + b.width / 2, b.y + b.height / 2);
    const k = (MANIFEST.display_scale || {})[b.type] || 1, dw = (b.width + b.height) * TW * k / meta.footprint_width, dh = dw * 400 / 320;
    g.save(); g.globalAlpha = 0.28; g.filter = 'saturate(0.2) brightness(1.6)';
    g.drawImage(img, cx - dw / 2, cy - dh * meta.anchor[1], dw, dh); g.restore();
  }
}
function drawTree(x, y, k) {
  const [cx, cy] = iso(x, y), s = 0.55 + 0.35 * k;
  g.fillStyle = 'rgba(0,0,0,0.30)'; g.beginPath(); g.ellipse(cx + 3, cy, 11 * s, 5 * s, 0, 0, 7); g.fill();
  g.fillStyle = '#4a3a3a'; g.fillRect(cx - 2 * s, cy - 14 * s, 4 * s, 14 * s);
  if (k > 0.45) {                                                    // round tree
    const gr = g.createRadialGradient(cx - 6 * s, cy - 30 * s, 2, cx, cy - 24 * s, 18 * s);
    gr.addColorStop(0, '#8ff0b4'); gr.addColorStop(0.55, '#2fae6a'); gr.addColorStop(1, '#1d7046');
    g.fillStyle = gr; g.beginPath(); g.arc(cx, cy - 25 * s, 15 * s, 0, 7); g.fill();
    g.strokeStyle = '#123d29'; g.lineWidth = 1.5; g.stroke();
    g.fillStyle = 'rgba(0,240,255,0.55)'; g.beginPath(); g.arc(cx + 7 * s, cy - 31 * s, 2.2, 0, 7); g.fill();   // tiny neon fruit
  } else {                                                           // cone (pine)
    const gr = g.createLinearGradient(cx - 12 * s, 0, cx + 12 * s, 0);
    gr.addColorStop(0, '#3fd08a'); gr.addColorStop(1, '#1a6a44');
    g.fillStyle = gr; g.beginPath(); g.moveTo(cx, cy - 46 * s); g.lineTo(cx + 13 * s, cy - 10 * s); g.lineTo(cx - 13 * s, cy - 10 * s); g.closePath(); g.fill();
    g.strokeStyle = '#123d29'; g.lineWidth = 1.5; g.stroke();
  }
}
function drawLamp(x, y) {
  const [cx, cy] = iso(x, y);
  g.strokeStyle = '#8590a8'; g.lineWidth = 3; g.beginPath(); g.moveTo(cx, cy); g.lineTo(cx, cy - 44); g.stroke();
  g.fillStyle = '#fff2b0'; g.shadowColor = '#ffd84d'; g.shadowBlur = 12; g.beginPath(); g.arc(cx, cy - 46, 4, 0, 7); g.fill(); g.shadowBlur = 0;
  g.fillStyle = 'rgba(255,216,77,0.10)'; g.beginPath(); g.ellipse(cx, cy, 30, 15, 0, 0, 7); g.fill();
}
function drawCar(x, y, dir, col) {
  const [cx, cy] = iso(x, y);
  const ax = dir === 'x' ? [TW, TH] : [-TW, TH], len = 0.28, wid = 0.14;
  const fx = ax[0] / Math.hypot(...ax), fy = ax[1] / Math.hypot(...ax);
  const p = (a, b) => [cx + fx * a * 70 - fy * b * 70, cy + fy * a * 70 + fx * b * 70 * 0.5];
  fillPoly([p(-len, -wid), p(len, -wid), p(len, wid), p(-len, wid)], col, '#0a0d18', 2);
  g.fillStyle = '#ffffff'; g.shadowColor = '#fff'; g.shadowBlur = 10;
  const h = p(len, 0); g.beginPath(); g.arc(h[0], h[1], 3, 0, 7); g.fill(); g.shadowBlur = 0;
}
function drawSpire() {
  const [cx, cy] = iso(C + 0.5, C + 0.5), h = 300;
  g.fillStyle = 'rgba(0,0,0,0.4)'; g.beginPath(); g.ellipse(cx, cy, 70, 34, 0, 0, 7); g.fill();
  fillPoly([[cx - 34, cy - 4], [cx, cy + 14], [cx, cy - h], [cx - 7, cy - h + 30]], '#2a3358', '#05070d', 3);
  fillPoly([[cx + 34, cy - 4], [cx, cy + 14], [cx, cy - h], [cx + 7, cy - h + 30]], '#161d38', '#05070d', 3);
  g.strokeStyle = '#ff2bd6'; g.lineWidth = 4; g.shadowColor = '#ff2bd6'; g.shadowBlur = 26;
  g.beginPath(); g.moveTo(cx, cy + 14); g.lineTo(cx, cy - h + 6); g.stroke();
  for (let k = 1; k <= 3; k++) { const yy = cy - k * 80; g.beginPath(); g.ellipse(cx, yy, 46 - k * 7, 13 - k * 2, 0, 0, 7); g.strokeStyle = k % 2 ? '#00f0ff' : '#ff2bd6'; g.stroke(); }
  g.fillStyle = '#fff'; g.beginPath(); g.arc(cx, cy - h, 10, 0, 7); g.fill(); g.shadowBlur = 0;
}

function drawObjects() {
  const objs = [];
  for (const b of buildings) objs.push({ k: b.x + b.width - 1 + b.y + b.height - 1 + 0.5, x: b.x, f: () => drawBuilding(b) });
  for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
    const c = grid[y][x]; if (!c.land) continue;
    if (c.park) {
      const r = R2();
      objs.push({ k: x + y + 0.3, x, f: () => drawTree(x + 0.35 + R2() * 0.3, y + 0.35 + R2() * 0.3, r) });
      if (R2() < 0.3) objs.push({ k: x + y + 0.6, x, f: () => drawTree(x + 0.75, y + 0.75, R2()) });
    } else if (c.road) {
      const rr = cell(x + 1, y), ll = cell(x - 1, y), dd = cell(x, y + 1), uu = cell(x, y - 1);
      const crossing = rr && rr.road && ll && ll.road && dd && dd.road && uu && uu.road;
      if (crossing && !(x === C && y === C)) objs.push({ k: x + y + 0.9, x, f: () => drawLamp(x + 0.15, y + 0.15) });
      else if (!crossing && R2() < 0.07) {
        const dir = (rr && rr.road && ll && ll.road) ? 'x' : 'y';
        const col = ['#ff3b6b', '#00e5ff', '#ffd84d', '#ffffff', '#b36bff'][Math.floor(R2() * 5)];
        objs.push({ k: x + y + 0.5, x, f: () => drawCar(x + 0.5, y + 0.5, dir, col) });
      }
    }
  }
  for (const b of buildings) {
    if (b.type === '1x1' || b.type === '1x2') continue;
    const corners = [[b.x + 0.3, b.y + 0.3], [b.x + b.width - 0.3, b.y + 0.3], [b.x + 0.3, b.y + b.height - 0.3], [b.x + b.width - 0.3, b.y + b.height - 0.3]];
    corners.forEach(([tx, ty], i) => objs.push({ k: tx + ty, x: tx, f: () => (i % 3 === 0 ? drawLamp(tx, ty) : drawTree(tx, ty, (b.id * 7 + i) % 10 / 10)) }));
  }
  objs.sort((a, b) => a.k - b.k || a.x - b.x);
  for (const o of objs) o.f();
}

/* ---------------- game overlays ---------------- */
const MINE = new Set();
// slot state: 'owned' (somebody's business) | 'free'; a free slot is AVAILABLE only when its
// district is unlocked and the slot is within the number the admin opened for sale there.
function assignStates(opts) {
  const open = opts.open || { 1: 121, 2: 119, 3: 119, 4: 119 };
  const viewer = opts.viewer || 'level1';
  for (const d of DISTRICTS) {
    const list = buildings.filter(b => b.districtId === d.id);
    list.forEach((b, i) => {
      const r = mulberry32(b.id * 7919 + 13)();
      b.owner = r < 0.66 ? 'other' : 'none';
      b.returned = b.owner === 'none' && r > 0.95;
      b.available = b.owner === 'none' && opts.locked !== d.id && i < (open[d.id] ?? list.length);
      b.level = b.stage === 1 ? 1 + (b.id % 3) : b.stage === 2 ? 4 + (b.id % 3) : 7 + (b.id % 4);
    });
  }
  MINE.clear();
  const core = buildings.filter(b => b.districtId === 1 && b.owner === 'other');
  if (viewer === 'zero') {
    const b = core.find(q => q.type === '1x1'); b.owner = 'me'; b.level = 0; b.stage = 1; MINE.add(b.id);
  } else if (viewer === 'level1') {
    const a = core.filter(q => q.type === '1x1')[4], c = core.filter(q => q.type === '2x2')[0];
    for (const [b, lv] of [[a, 3], [c, 6]]) if (b) { b.owner = 'me'; b.level = lv; b.stage = lv <= 3 ? 1 : lv <= 6 ? 2 : 3; MINE.add(b.id); }
  }
}
function priceCity(b) { const p = PRICES[b.btype]; return p ? Math.round(p.city) : 0; }
const fmt = (v) => v.toLocaleString('ru-RU');

function _unused_pickOverlays() {
  const core = buildings.filter(b => b.districtId === 1);
  [11, 26, 40].forEach(i => core[i] && MINE.add(core[i].id));
  [15, 52].forEach((i, k) => core[i] && SALE.set(core[i].id, [7400, 12400][k]));
  for (const d of [2, 3]) buildings.filter(b => b.districtId === d).filter((_, i) => i % 41 === 9).forEach((b, k) => SALE.set(b.id, [3500, 6800, 9800][k % 3]));
}
function pill(cx, cy, text, bg, fg, border) {
  g.font = '800 18px "Segoe UI", Arial'; const w = g.measureText(text).width + 24, h = 30;
  g.fillStyle = 'rgba(0,0,0,0.45)'; roundRect(cx - w / 2 + 3, cy - h + 4, w, h, 18); g.fill();
  g.fillStyle = bg; roundRect(cx - w / 2, cy - h, w, h, 18); g.fill();
  if (border) { g.strokeStyle = border; g.lineWidth = 2.5; g.stroke(); }
  g.beginPath(); g.moveTo(cx - 9, cy); g.lineTo(cx + 9, cy); g.lineTo(cx, cy + 10); g.closePath(); g.fill();
  g.fillStyle = fg; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(text, cx, cy - h / 2 + 1);
}
function roundRect(x, y, w, h, r) { g.beginPath(); g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r); g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath(); }
function drawMineGround() {                       // the player's lots: glowing plate in the player's colour
  for (const b of buildings) {
    if (!MINE.has(b.id)) continue;
    const pts = [iso(b.x, b.y), iso(b.x + b.width, b.y), iso(b.x + b.width, b.y + b.height), iso(b.x, b.y + b.height)];
    g.shadowColor = '#ff8a00'; g.shadowBlur = 24; fillPoly(pts, 'rgba(255,138,0,0.28)', '#ffb347', 4); g.shadowBlur = 0;
  }
}
function tagTop(b) {
  const s = spriteBox(b, b.owner === 'none' ? 1 : b.stage);
  return [s.cx, s.top - 6];
}
function pricePill(cx, cy, b, viewer) {
  const full = priceCity(b);
  g.font = '800 15px "Segoe UI", Arial';
  if (viewer === 'newbie') {                         // crossed upgrade price + level-0 price
    const a = fmt(full), c = '0 $CITY', sub = 'ур. 0 · 3 дня';
    const wa = g.measureText(a).width, wc = g.measureText(c).width; g.font = '700 12px "Segoe UI", Arial';
    const ws = g.measureText(sub).width, w = Math.max(wa + wc + 12, ws) + 20, h = 40;
    g.fillStyle = 'rgba(0,0,0,0.45)'; roundRect(cx - w / 2 + 3, cy - h + 4, w, h, 14); g.fill();
    g.fillStyle = '#0d2a1d'; roundRect(cx - w / 2, cy - h, w, h, 14); g.fill(); g.strokeStyle = '#39ff88'; g.lineWidth = 2.5; g.stroke();
    g.beginPath(); g.moveTo(cx - 8, cy); g.lineTo(cx + 8, cy); g.lineTo(cx, cy + 9); g.closePath(); g.fillStyle = '#39ff88'; g.fill();
    g.font = '800 15px "Segoe UI", Arial'; g.textBaseline = 'middle'; g.textAlign = 'left';
    const x0 = cx - (wa + wc + 12) / 2, y0 = cy - h + 14;
    g.fillStyle = '#8fa8a0'; g.fillText(a, x0, y0);
    g.strokeStyle = '#ff5d7a'; g.lineWidth = 2.2; g.beginPath(); g.moveTo(x0 - 2, y0); g.lineTo(x0 + wa + 2, y0); g.stroke();
    g.fillStyle = '#39ff88'; g.fillText(c, x0 + wa + 12, y0);
    g.font = '700 11px "Segoe UI", Arial'; g.fillStyle = '#bff8d6'; g.textAlign = 'center'; g.fillText(sub, cx, cy - h + 30);
    return;
  }
  if (viewer === 'zero') { pill(cx, cy, '🔒 ' + fmt(full) + ' $CITY', '#3a4256', '#c3cbe0', '#6b7590'); return; }
  pill(cx, cy, fmt(full) + ' $CITY', '#1fd17a', '#032313', '#a6ffd0');
}
function tagSize(b, viewer) {
  const full = fmt(priceCity(b));
  if (viewer === 'newbie') { g.font = '800 15px "Segoe UI", Arial'; return [g.measureText(full).width + g.measureText('0 $CITY').width + 32, 40]; }
  g.font = '800 18px "Segoe UI", Arial'; return [g.measureText((viewer === 'zero' ? '🔒 ' : '') + full + ' $CITY').width + 24, 30];
}
function drawMarker(cx, top) {
  g.fillStyle = '#39ff88'; g.shadowColor = '#39ff88'; g.shadowBlur = 10;
  g.beginPath(); g.moveTo(cx, top - 14); g.lineTo(cx + 9, top - 4); g.lineTo(cx, top + 6); g.lineTo(cx - 9, top - 4); g.closePath(); g.fill(); g.shadowBlur = 0;
  g.strokeStyle = '#06301a'; g.lineWidth = 1.5; g.stroke();
}
function drawTags(opts) {
  const viewer = opts.viewer || 'level1', placed = [];
  const hit = (x, y, w, h) => placed.some(p => x < p.x + p.w && x + w > p.x && y < p.y + p.h && y + h > p.y);
  // my buildings first, then big lots, then returned, then the rest
  const order = buildings.filter(b => b.owner === 'me' || b.available)
    .sort((a, b) => (b.owner === 'me') - (a.owner === 'me') || ({ '3x3': 3, '2x2': 2, '1x2': 1, '1x1': 0 }[b.type] - { '3x3': 3, '2x2': 2, '1x2': 1, '1x1': 0 }[a.type]) || (b.returned - a.returned) || a.id - b.id);
  const markers = [];
  for (const b of order) {
    const [cx, top] = tagTop(b);
    if (b.owner === 'me') { pill(cx, top, '★ Вы · ур. ' + b.level, '#ff8a00', '#1a0d00', '#ffd9a0'); placed.push({ x: cx - 70, y: top - 32, w: 140, h: 42 }); continue; }
    if (opts.lod === 'far') { markers.push([cx, top]); continue; }
    const [w, h] = tagSize(b, viewer), extra = b.returned ? 16 : 0;
    const box = { x: cx - w / 2 - 4, y: top - h - extra - 4, w: w + 8, h: h + extra + 14 };
    if (hit(box.x, box.y, box.w, box.h)) { markers.push([cx, top]); continue; }
    placed.push(box);
    pricePill(cx, top, b, viewer);
    if (b.returned) { g.font = '800 12px "Segoe UI", Arial'; g.fillStyle = '#ffd84d'; g.textAlign = 'center'; g.fillText('снова в продаже', cx, top - h - 6); }
  }
  for (const [cx, top] of markers) if (!hit(cx - 10, top - 15, 20, 22)) drawMarker(cx, top);
}
function drawLocked(did) {
  for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) if (grid[y][x].district === did) fillPoly(diamond(x, y), 'rgba(4,6,14,0.62)');
  const d = DISTRICTS.find(q => q.id === did), [cx, cy] = iso(d.center.x + 0.5, d.center.y + 0.5);
  g.strokeStyle = hexA(d.color, 0.8); g.lineWidth = 3; g.shadowColor = d.color; g.shadowBlur = 30;
  g.beginPath(); g.ellipse(cx, cy - 40, 520, 300, 0, Math.PI, 2 * Math.PI); g.stroke(); g.shadowBlur = 0;
  g.font = '64px Segoe UI Emoji, Noto Color Emoji, sans-serif'; g.textAlign = 'center'; g.fillText('🔒', cx, cy - 120);
  g.font = '900 40px "Segoe UI", Arial'; g.fillStyle = '#ff5d7a'; g.fillText('СЕКТОР ЗАКРЫТ АДМИНИСТРАЦИЕЙ', cx, cy - 40);
  g.font = '700 28px "Segoe UI", Arial'; g.fillStyle = '#c7d3df'; g.fillText(d.name, cx, cy + 4);
}
function drawDistrictLabels() {
  for (const d of DISTRICTS) {
    const [cx, cy0] = iso(d.center.x + 0.5, d.center.y + 0.5), cy = cy0 - 140;
    g.font = '800 26px "Segoe UI", Arial'; const t = d.name, w = g.measureText(t).width + 34;
    g.fillStyle = 'rgba(8,12,24,0.82)'; roundRect(cx - w / 2, cy - 22, w, 44, 14); g.fill();
    g.strokeStyle = d.color; g.lineWidth = 2; g.stroke();
    g.fillStyle = d.color; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(t, cx, cy + 1);
  }
}

window.renderMap = async function (opts = {}) {
  const names = new Set(); for (const b of buildings) for (const s of [1, 2, 3]) names.add(`${b.btype}/stage${s}`);
  await Promise.all([...names].map(n => new Promise((res) => { const im = new Image(); im.onload = () => { SPR[n] = im; res(); }; im.onerror = res; im.src = SPRITES + n + '.webp'; })));
  assignStates(opts);
  drawSea(); drawCliff(); drawGround(); drawMineGround(); drawObjects();
  if (opts.locked) drawLocked(opts.locked);
  drawTags(opts);
  if (opts.labels) drawDistrictLabels();
  const v = g.createRadialGradient(W / 2, H / 2, Math.min(W, H) * 0.35, W / 2, H / 2, Math.max(W, H) * 0.75);
  v.addColorStop(0, 'rgba(0,0,0,0)'); v.addColorStop(1, 'rgba(2,6,16,0.55)'); g.fillStyle = v; g.fillRect(0, 0, W, H);
  const hz = g.createLinearGradient(0, 0, 0, H); hz.addColorStop(0, 'rgba(0,200,255,0.06)'); hz.addColorStop(1, 'rgba(120,0,255,0.05)');
  g.fillStyle = hz; g.fillRect(0, 0, W, H);
  return { W, H, buildings: buildings.length, sprites: Object.keys(SPR).length, iso: (x, y) => iso(x, y),
           centers: DISTRICTS.map(d => ({ id: d.id, p: iso(d.center.x + 0.5, d.center.y + 0.5) })) };
};
