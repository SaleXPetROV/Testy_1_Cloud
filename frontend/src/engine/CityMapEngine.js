/**
 * CityMapEngine — the new city map (districts, lots of 1x1 / 1x2 / 2x2 / 3x3, roads, parks).
 *
 * Same public interface as the old IsometricMapEngine, so TonIslandPage keeps all its
 * panels, buy / level-0 / tutorial flows:  new CityMapEngine(container, {width, height,
 * onCellClick, onCellHover}) · init() · destroy() · resize(w, h) · zoomIn() · zoomOut() ·
 * resetCamera() · applyInitialView() · setNightMode(on).  Data comes from mapStore.
 *
 * Light by design: plain Canvas 2D (no WebGL scene kept in memory), the frame is redrawn
 * ONLY when something changed (camera, data, an image finished loading), and only what
 * is on screen is drawn.
 */
import { mapStore } from './IsometricMapEngine';

const TW = 32, TH = 16;                                // tile half-size at zoom 1
const MIN_Z = 0.35, MAX_Z = 3.2;
const SPR = '/sprites/city/';
const TO_SPRITE = { chip_factory: 'chips_factory', logistics: 'logistics_hub', repair_zone: 'repair_shop', cold_storage: 'hydro_cooling' };
const DCOL = { 1: '#ff2bd6', 2: '#00f0ff', 3: '#ffd84d', 4: '#39ff88' };
const DISPLAY = { '1x1': 0.92, '1x2': 0.94, '2x2': 0.8, '3x3': 0.72 };
const fmt = (v) => Math.round(v || 0).toLocaleString('ru-RU');
const stageOf = (lvl) => (lvl <= 3 ? 1 : lvl <= 6 ? 2 : 3);
const hexA = (hex, a) => { const n = parseInt(hex.slice(1), 16); return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`; };

export class CityMapEngine {
  constructor(container, opts = {}) {
    this.container = container;
    this.opts = opts;
    this.w = opts.width || container.clientWidth || 360;
    this.h = opts.height || container.clientHeight || 640;
    this.cam = { x: 0, y: 0, z: 1 };
    this.night = false;
    this.images = new Map();                           // url -> HTMLImageElement
    this.manifest = null; this.tuning = {};
    this.dirty = true; this.raf = 0;
    this._down = null; this._pointers = new Map(); this._pinch = null;
  }

  // ───────────────────────── lifecycle ─────────────────────────
  async init() {
    const c = document.createElement('canvas');
    c.style.cssText = 'width:100%;height:100%;display:block;touch-action:none;cursor:grab';
    this.container.appendChild(c);
    this.canvas = c; this.ctx = c.getContext('2d');
    this._applySize();
    this._bind();
    this._unsub = mapStore.subscribe(() => this._invalidate());
    try {
      const [m, t] = await Promise.all([
        fetch(SPR + 'manifest.json').then((r) => r.json()),
        fetch(`${process.env.REACT_APP_BACKEND_URL || ''}/api/city-sprites/tuning`).then((r) => (r.ok ? r.json() : { tuning: {} })),
      ]);
      this.manifest = m; this.tuning = t.tuning || {};
      this.overrides = t.overrides || {}; this.overridesAlt = t.overrides_alt || {};   // sprites replaced by the admin
    } catch (e) { this.manifest = { types: {} }; }
    this.applyInitialView();
    this._invalidate();
  }

  destroy() {
    cancelAnimationFrame(this.raf);
    if (this._unsub) this._unsub();
    this._unbind();
    if (this.canvas && this.canvas.parentNode) this.canvas.parentNode.removeChild(this.canvas);
    this.images.clear();
  }

  resize(w, h) { this.w = w; this.h = h; this._applySize(); this._invalidate(); }
  setNightMode(on) { this.night = !!on; this._invalidate(); }
  zoomIn() { this._zoomAt(this.w / 2, this.h / 2, 1.25); }
  zoomOut() { this._zoomAt(this.w / 2, this.h / 2, 0.8); }
  resetCamera() { this.applyInitialView(); }

  /** Fly to the next own building (cycles); returns how many the player has. */
  focusNextMine() {
    const mine = this._model().cells.filter((c) => this._mine(c)).sort((a, b) => (a.slotId ?? 0) - (b.slotId ?? 0));
    if (!mine.length) return 0;
    this._mineIdx = ((this._mineIdx ?? -1) + 1) % mine.length;
    const c = mine[this._mineIdx];
    const [x, y] = this._iso(c.q + (c.w || 1) / 2, c.r + (c.h || 1) / 2);
    this._flyTo(x, y - 20, Math.max(this.cam.z, 1.6));
    return mine.length;
  }

  /** «%»: a marker with the price over every building on sale — by the city AND on the marketplace. */
  setSaleFilter(on) { this.saleOnly = !!on; this._invalidate(); }

  _flyTo(x, y, z) {                                    // short smooth camera flight
    const from = { ...this.cam }, t0 = performance.now(), dur = 450;
    const step = (t) => {
      const k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 3);
      this.cam = { x: from.x + (x - from.x) * e, y: from.y + (y - from.y) * e, z: from.z + (z - from.z) * e };
      this._invalidate(); if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  applyInitialView() {
    const b = this._bounds();
    if (!b) { this._viewPending = true; return; }       // no cells yet: frame the city when they arrive
    this._viewPending = false;
    // the whole island fits the screen; the camera looks at the Central Core
    const fit = Math.min(this.w / (b.maxX - b.minX + 40), (this.h - 140) / (b.maxY - b.minY + 120));
    const core = this._model().centers[1];
    const [cx, cy] = core ? this._iso(core.x / core.n, core.y / core.n) : [(b.minX + b.maxX) / 2, (b.minY + b.maxY) / 2];
    this.cam = { x: cx, y: cy - 30, z: Math.max(MIN_Z, Math.min(MAX_Z, fit * 1.9)) };
    this._invalidate();
  }

  _applySize() {
    if (!this.canvas) return;
    this.dpr = Math.min(window.devicePixelRatio || 1, 2);
    this.canvas.width = Math.round(this.w * this.dpr); this.canvas.height = Math.round(this.h * this.dpr);
  }

  // ───────────────────────── data ─────────────────────────
  _state() { return mapStore.getState(); }

  _model() {                                           // cells + derived geometry, rebuilt when the cells change
    const st = this._state();
    if (this._modelCells === st.cellsVersion && this._modelVer === st.layoutVersion && this._m) return this._m;
    const cells = [...st.cells.values()];
    const grid = (st.layout && st.layout.width) || 39;
    const cover = new Map();                            // "x,y" of every covered tile -> cell
    for (const c of cells) {
      const w = c.w || 1, h = c.h || 1;
      for (let i = 0; i < w; i++) for (let j = 0; j < h; j++) cover.set(`${c.q + i},${c.r + j}`, c);
    }
    const parks = new Set(((st.layout && st.layout.parks) || []).map((p) => (Array.isArray(p) ? `${p[0]},${p[1]}` : String(p))));
    // district rank of every lot (big first, as the server orders them)
    const rank = new Map(), seen = {};
    [...cells].filter((c) => c.slotId != null).sort((a, b) => a.slotId - b.slotId)
      .forEach((c) => { const d = c.district; rank.set(c, seen[d] = (seen[d] ?? -1) + 1); });
    const centers = {};
    for (const c of cells) {
      if (!c.district) continue;
      const k = (centers[c.district] = centers[c.district] || { x: 0, y: 0, n: 0 });
      k.x += c.q + (c.w || 1) / 2; k.y += c.r + (c.h || 1) / 2; k.n++;
    }
    this._m = { cells, grid, cover, parks, rank, centers, hasLayout: !!(st.layout && st.layout.parks) };
    this._modelCells = st.cellsVersion; this._modelVer = st.layoutVersion;
    return this._m;
  }

  _bounds() {
    const m = this._model(); if (!m.cells.length) return null;
    const n = m.hasLayout ? m.grid : Math.max(...m.cells.map((c) => Math.max(c.q, c.r))) + 2;
    const pts = [this._iso(0, 0), this._iso(n, 0), this._iso(n, n), this._iso(0, n)];
    return { minX: Math.min(...pts.map((p) => p[0])), maxX: Math.max(...pts.map((p) => p[0])),
             minY: Math.min(...pts.map((p) => p[1])), maxY: Math.max(...pts.map((p) => p[1])) };
  }

  _iso(gx, gy) { return [(gx - gy) * TW, (gx + gy) * TH]; }
  _toScreen(wx, wy) { return [(wx - this.cam.x) * this.cam.z + this.w / 2, (wy - this.cam.y) * this.cam.z + this.h / 2]; }
  _toWorld(sx, sy) { return [(sx - this.w / 2) / this.cam.z + this.cam.x, (sy - this.h / 2) / this.cam.z + this.cam.y]; }

  _img(url) {
    let im = this.images.get(url);
    if (!im) {
      im = new Image(); im.decoding = 'async';
      im.onload = () => this._invalidate();
      im.src = url; this.images.set(url, im);
    }
    return im.complete && im.naturalWidth ? im : null;
  }

  // is a free lot open for sale (zone schedule + district settings)?
  _closed(c) {                                      // a district closed by the admin: nothing is shown there
    const d = this._state().districts;
    return !!(c.district && d && d.unlocked && d.unlocked[String(c.district)] === false);
  }

  _available(c) {
    if (c.owner || c.isEmptyPlot || this._closed(c)) return false;
    const st = this._state();
    // a plot chosen in the admin «Пресейл» is on sale too
    if (st.presaleSet && st.presaleSet.has && st.presaleSet.has(`${c.q},${c.r}`)) return true;
    const open = st.trading && st.trading[c.zone];
    if (open && Date.now() < new Date(open).getTime()) return false;
    const d = st.districts;
    if (c.district) {                                   // new map: only lots the admin put on sale
      if (!d) return false;
      if (d.unlocked && d.unlocked[String(c.district)] === false) return false;
      const n = Number((d.open_count || {})[String(c.district)] || 0);
      if ((this._model().rank.get(c) ?? 0) >= n) return false;
    }
    return true;
  }

  _listing(c) {                                      // marketplace lot of another player on this cell
    const l = this._state().listings; if (!l || this._closed(c)) return null;
    const x = l[`${c.q},${c.r}`]; return x && !this._mine(c) ? x : null;
  }

  _mine(c) {
    const st = this._state();
    return !!c.owner && (c.owner === st.userId || (st.userWallet && c.owner === st.userWallet));
  }

  // sprite placement — the same math as the admin preview (CitySpritesPanel)
  _sprite(c) {
    const b = c.building; if (!b || !this.manifest) return null;
    const w = c.w || 1, h = c.h || 1;
    const size = w === h ? `${w}x${h}` : '1x2';
    const slotW = (w + h) * TW;
    const [cx, cy] = this._iso(c.q + w / 2, c.r + h / 2);
    if (b.skinUrl && b.skinGroup && b.skinGroup !== 'standard' && b.skinMeta) {   // processed skin: placed like a building
      const im = this._img(b.skinUrl); if (!im) return { pending: true };
      const fm = b.skinMeta, sz = fm.size || [400, 500];
      const dw = slotW * (DISPLAY[size] || 0.9) / fm.footprint_width, dh = dw * sz[1] / sz[0];
      const x = cx - dw * fm.anchor[0], y = cy - dh * fm.anchor[1];
      return { im, x, y, dw, dh, cx, top: y + dh * (fm.top ?? 0.1), mirror: false };
    }
    if (b.skinUrl && b.skinGroup && b.skinGroup !== 'standard') {          // the player's chosen skin
      const im = this._img(b.skinUrl); if (!im) return { pending: true };
      const dw = slotW * (DISPLAY[size] || 0.9) / 0.86 * ((b.skinWidthPct || 100) / 100);
      const dh = dw * im.naturalHeight / im.naturalWidth * ((b.skinHeightPct || 100) / 100);
      const bottom = cy + (w + h) * TH / 2 - (w + h) * TH * 0.08;
      return { im, x: cx - dw / 2, y: bottom - dh, dw, dh, cx, top: bottom - dh, mirror: false };
    }
    const type = TO_SPRITE[b.type] || b.type;
    const meta = this.manifest.types && this.manifest.types[type]; if (!meta) return null;
    const stage = String(b.isPreview ? 1 : stageOf(b.level || 0));
    let fm = (meta.files_meta || {})[stage] || meta, file = `${type}/stage${stage}.webp`;
    const lotLong = w === h ? null : (h > w ? 'y' : 'x');
    const alt = (meta.files_alt || {})[stage];
    let url = SPR + file;
    const ov = ((this.overrides || {})[type] || {})[stage];
    if (ov) { fm = ov; url = (process.env.REACT_APP_BACKEND_URL || '') + ov.url; }          // admin replaced this sprite
    if (lotLong && fm.long_axis && fm.long_axis !== lotLong) {
      const ova = ((this.overridesAlt || {})[type] || {})[stage];
      if (ova) { fm = ova; url = (process.env.REACT_APP_BACKEND_URL || '') + ova.url; }
      else if (alt && !ov) { fm = alt; url = SPR + alt.file; }
    }
    const im = this._img(url); if (!im) return { pending: true };
    const t = ((this.tuning[type] || {})[stage]) || {};
    const sz = fm.size || [320, 400];
    const base = slotW * (DISPLAY[size] || 0.9) / fm.footprint_width * (t.scale || 1);
    const dw = base * (t.sx || 1), dh = base * sz[1] / sz[0] * (t.sy || 1);
    const ox = (t.dx || 0) * slotW, oy = (t.dy || 0) * slotW;
    const x = cx - dw * fm.anchor[0] + ox, y = cy - dh * fm.anchor[1] + oy;
    return { im, x, y, dw, dh, cx: cx + ox, top: y + dh * (fm.top ?? 0.1), mirror: false };
  }

  // ───────────────────────── drawing ─────────────────────────
  _invalidate() {
    if (this._viewPending && this._state().cells.size) this.applyInitialView();
    this.dirty = true; if (!this.raf) this.raf = requestAnimationFrame(() => { this.raf = 0; if (this.dirty) this._draw(); }); }

  _poly(pts, fill, stroke, lw = 1) {
    const g = this.ctx; g.beginPath(); g.moveTo(pts[0][0], pts[0][1]);
    for (let i = 1; i < pts.length; i++) g.lineTo(pts[i][0], pts[i][1]);
    g.closePath(); if (fill) { g.fillStyle = fill; g.fill(); } if (stroke) { g.strokeStyle = stroke; g.lineWidth = lw; g.stroke(); }
  }
  _lot(c, inset = 0) {
    const w = c.w || 1, h = c.h || 1;
    return [this._iso(c.q + inset, c.r + inset), this._iso(c.q + w - inset, c.r + inset), this._iso(c.q + w - inset, c.r + h - inset), this._iso(c.q + inset, c.r + h - inset)];
  }

  _draw() {
    this.dirty = false;
    const g = this.ctx, m = this._model(), st = this._state(), z = this.cam.z;
    g.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    const sea = g.createLinearGradient(0, 0, 0, this.h);
    sea.addColorStop(0, '#0a3f63'); sea.addColorStop(1, '#041a2e');
    g.fillStyle = sea; g.fillRect(0, 0, this.w, this.h);
    g.save();
    g.translate(this.w / 2, this.h / 2); g.scale(z, z); g.translate(-this.cam.x, -this.cam.y);
    // visible world rectangle (+ margin for tall buildings)
    const [vx0, vy0] = this._toWorld(-60, -200), [vx1, vy1] = this._toWorld(this.w + 60, this.h + 60);
    const vis = (x, y) => x > vx0 - 140 && x < vx1 + 140 && y > vy0 - 40 && y < vy1 + 260;

    // 1) ground: lots, roads, parks (tiles drawn directly, culled)
    const n = m.hasLayout ? m.grid : 0;
    if (n) {
      for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
        const [px, py] = this._iso(x + 0.5, y + 0.5); if (!vis(px, py)) continue;
        const key = `${x},${y}`, lot = m.cover.get(key);
        const pts = [this._iso(x, y), this._iso(x + 1, y), this._iso(x + 1, y + 1), this._iso(x, y + 1)];
        if (lot) this._poly(pts, (x + y) % 2 ? '#434f6e' : '#3f4a68', '#353f5c');
        else if (m.parks.has(key)) this._poly(pts, (x * 7 + y * 3) % 3 ? '#2f7d55' : '#2c744f', '#28684a');
        else this._poly(pts, '#2a3044', null);           // asphalt
      }
      // street details (only when close enough to read them)
      const isRoad = (x, y) => x >= 0 && y >= 0 && x < n && y < n && !m.cover.has(`${x},${y}`) && !m.parks.has(`${x},${y}`);
      for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
        if (!isRoad(x, y)) continue;
        const [px, py] = this._iso(x + 0.5, y + 0.5); if (!vis(px, py)) continue;
        const ex = isRoad(x - 1, y) || isRoad(x + 1, y), ey = isRoad(x, y - 1) || isRoad(x, y + 1);
        // curbs: a light edge where the road meets a lot or a park
        g.strokeStyle = 'rgba(190,205,230,0.55)'; g.lineWidth = 1.4 / Math.max(z, 0.5); g.beginPath();
        const edge = (ax, ay, bx, by) => { const p1 = this._iso(ax, ay), p2 = this._iso(bx, by); g.moveTo(p1[0], p1[1]); g.lineTo(p2[0], p2[1]); };
        if (!isRoad(x, y - 1)) edge(x, y, x + 1, y);
        if (!isRoad(x + 1, y)) edge(x + 1, y, x + 1, y + 1);
        if (!isRoad(x, y + 1)) edge(x, y + 1, x + 1, y + 1);
        if (!isRoad(x - 1, y)) edge(x, y, x, y + 1);
        g.stroke();
        if (z < 0.6) continue;
        if (ex && ey) {                                  // crossing: zebra + lamp
          g.fillStyle = 'rgba(235,240,250,0.55)';
          for (let k = 0; k < 3; k++) { const a = this._iso(x + 0.2 + k * 0.25, y + 0.06), b = this._iso(x + 0.3 + k * 0.25, y + 0.06); g.fillRect(a[0] - 1, a[1] - 1, Math.max(2, b[0] - a[0]), 2.2); }
          g.strokeStyle = '#8590a8'; g.lineWidth = 1.5; g.beginPath(); g.moveTo(px, py); g.lineTo(px, py - 16); g.stroke();
          g.fillStyle = '#fff2b0'; g.beginPath(); g.arc(px, py - 17, 2.2, 0, 7); g.fill();
        } else {                                         // dashed yellow centre line
          g.strokeStyle = 'rgba(255,214,90,0.75)'; g.lineWidth = 1.3 / Math.max(z, 0.7); g.setLineDash([4, 4]); g.beginPath();
          const a = ex ? this._iso(x, y + 0.5) : this._iso(x + 0.5, y), b = ex ? this._iso(x + 1, y + 0.5) : this._iso(x + 0.5, y + 1);
          g.moveTo(a[0], a[1]); g.lineTo(b[0], b[1]); g.stroke(); g.setLineDash([]);
        }
      }
      // island edge (raised)
      const e = [this._iso(0, n), this._iso(n, n), this._iso(n, 0)];
      g.strokeStyle = 'rgba(0,240,255,0.6)'; g.lineWidth = 2 / z;
      g.beginPath(); g.moveTo(e[0][0], e[0][1] + 10); g.lineTo(e[1][0], e[1][1] + 10); g.lineTo(e[2][0], e[2][1] + 10); g.stroke();
    } else {
      for (const c of m.cells) this._poly(this._lot(c), '#3f4a68', '#353f5c');
    }

    // 2) lot outlines: mine (orange), for sale (green)
    for (const c of m.cells) {
      const [px, py] = this._iso(c.q + (c.w || 1) / 2, c.r + (c.h || 1) / 2); if (!vis(px, py)) continue;
      if (this._mine(c)) this._poly(this._lot(c, 0.05), 'rgba(255,138,0,0.22)', '#ffb347', 2.5 / Math.max(z, 0.6));
      else if (this._available(c)) this._poly(this._lot(c, 0.06), null, 'rgba(57,255,136,0.85)', 2 / Math.max(z, 0.6));
    }

    // 3) park trees (only when close enough to see them)
    if (n && z > 0.55) {
      for (const key of m.parks) {
        const [x, y] = key.split(',').map(Number); const [px, py] = this._iso(x + 0.5, y + 0.5);
        if (!vis(px, py)) continue;
        g.fillStyle = 'rgba(0,0,0,0.25)'; g.beginPath(); g.ellipse(px + 2, py, 8, 4, 0, 0, 7); g.fill();
        g.fillStyle = '#4a3a3a'; g.fillRect(px - 1.5, py - 10, 3, 10);
        g.fillStyle = (x + y) % 2 ? '#2fae6a' : '#3fd08a'; g.beginPath(); g.arc(px, py - 15, 9, 0, 7); g.fill();
      }
    }

    // 4) buildings, depth-sorted (front corner), culled
    const order = m.cells.filter((c) => c.building).map((c) => ({ c, k: c.q + (c.w || 1) + c.r + (c.h || 1), x: c.q }))
      .sort((a, b) => a.k - b.k || a.x - b.x);
    this._hit = [];
    for (const { c } of order) {
      const s = this._sprite(c); if (!s || s.pending) continue;
      if (!(s.x + s.dw > vx0 - 50 && s.x < vx1 + 50 && s.y + s.dh > vy0 - 50 && s.y < vy1 + 50)) continue;
      g.drawImage(s.im, s.x, s.y, s.dw, s.dh);
      this._hit.push({ c, x: s.x, y: s.top, w: s.dw, h: s.y + s.dh - s.top, cx: s.cx, top: s.top });
    }

    // 5) locked districts
    if (st.districts && st.districts.unlocked) {
      for (const [d, open] of Object.entries(st.districts.unlocked)) {
        if (open !== false) continue;
        for (const c of m.cells) if (String(c.district) === d) this._poly(this._lot(c), 'rgba(4,6,14,0.62)');
      }
    }
    if (this.night) { g.fillStyle = 'rgba(0,4,30,0.32)'; g.fillRect(vx0 - 500, vy0 - 500, vx1 - vx0 + 1000, vy1 - vy0 + 1000); }
    g.restore();

    // 6) screen-space overlay: tags, district plaques, locks
    this._drawTags(m, st);
    this._drawDistricts(m, st);
    this._drawMinimap(m);
  }

  _pill(cx, cy, text, bg, fg, border, font = '800 12px "Segoe UI", Arial') {
    const g = this.ctx; g.font = font;
    const w = g.measureText(text).width + 18, h = 22;
    g.fillStyle = bg; this._rr(cx - w / 2, cy - h, w, h, 11); g.fill();
    if (border) { g.strokeStyle = border; g.lineWidth = 1.5; g.stroke(); }
    g.beginPath(); g.moveTo(cx - 5, cy); g.lineTo(cx + 5, cy); g.lineTo(cx, cy + 6); g.closePath(); g.fill();
    g.fillStyle = fg; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(text, cx, cy - h / 2 + 1);
    return { x: cx - w / 2 - 3, y: cy - h - 3, w: w + 6, h: h + 10 };
  }
  _rr(x, y, w, h, r) { const g = this.ctx; g.beginPath(); g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r); g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath(); }

  _drawTags(m, st) {
    const g = this.ctx, near = this.cam.z >= 1.05, viewer = st.viewer || 'level1';
    const L = { you: 'Вы · ур.', lvl0: 'ур. 0 · 3 дня', rent: 'Аренда {p} $CITY/сут', ...(st.labels || {}) };
    const placed = [], hit = (b) => placed.some((p) => b.x < p.x + p.w && b.x + b.w > p.x && b.y < p.y + p.h && b.y + b.h > p.y);
    const short = (v) => (v >= 1e6 ? `${(v / 1e6).toFixed(1).replace('.', ',')}M` : v >= 1e3 ? `${(v / 1e3).toFixed(1).replace('.', ',').replace(',0', '')}K` : fmt(v));
    // a full pill if it fits, otherwise a compact one, otherwise nothing (it appears when zooming in)
    const tryPill = (sx, sy, full, compact, bg, fg, border) => {
      for (const [text, font] of [[full, '800 12px "Segoe UI", Arial'], [compact, '800 10px "Segoe UI", Arial']]) {
        if (!text) continue;
        g.font = font; const w = g.measureText(text).width + 16, h = font.startsWith('800 12') ? 22 : 18;
        const box = { x: sx - w / 2 - 2, y: sy - h - 2, w: w + 4, h: h + 8 };
        if (hit(box)) continue;
        placed.push(this._pill(sx, sy, text, bg, fg, border, font)); return true;
      }
      return false;
    };
    const rentOf = (c) => (st.rentOffers && !this._mine(c) && !this._closed(c) ? st.rentOffers[`${c.q},${c.r}`] : null);
    const size = (c) => (c.w || 1) * (c.h || 1);
    const items = (this._hit || []).filter((h) => this._mine(h.c) || this._available(h.c) || (this.saleOnly && (this._listing(h.c) || rentOf(h.c))))
      .sort((a, b) => (this._mine(b.c) - this._mine(a.c)) || (size(b.c) - size(a.c)));
    for (const h of items) {
      const [sx, sy] = this._toScreen(h.cx, h.top - 4);
      if (sx < -80 || sx > this.w + 80 || sy < -40 || sy > this.h + 40) continue;
      const c = h.c;
      if (this._mine(c)) {
        const lvl = c.building?.level ?? 0;
        if (tryPill(sx, sy, `★ ${L.you} ${lvl}`, `★ ${lvl}`, '#ff8a00', '#1a0d00', '#ffd9a0')) {
          const pb = placed[placed.length - 1];
          this._statusIcons(c).forEach((ic, i) => {
            const bx = pb.x + pb.w + 9 + i * 20, by = sy - 11;
            g.fillStyle = 'rgba(8,12,24,0.92)'; g.beginPath(); g.arc(bx, by, 9, 0, 7); g.fill();
            g.strokeStyle = '#ffb347'; g.lineWidth = 1.2; g.stroke(); this._icon(ic, bx, by);
          });
        }
        continue;
      }
      if (this.saleOnly) {                             // «%»: city (green), marketplace (orange), rent (teal)
        const lot = this._listing(c), ro = !lot && rentOf(c), city = !lot && !ro && this._available(c);
        if (lot) tryPill(sx, sy, `% ${fmt(lot.price_city)} $CITY`, `% ${short(lot.price_city)}`, '#ffb347', '#2a1500', '#ffe0b0');
        else if (ro) tryPill(sx, sy, L.rent.replace('{p}', fmt(ro.price_city)), `⟳ ${short(ro.price_city)}`, '#22d3ee', '#022a33', '#a5f3fc');
        else if (city) tryPill(sx, sy, `% ${fmt(c.price || 0)} $CITY`, `% ${short(c.price || 0)}`, '#1fd17a', '#032313', '#a6ffd0');
        continue;
      }
      if (!near) continue;                             // far away: the green lot outline is enough
      const full = c.price || 0;
      if (viewer === 'newbie') {                       // crossed upgrade price + level-0 price
        g.font = '800 12px "Segoe UI", Arial';
        const a = fmt(full), b = '0 $CITY', wa = g.measureText(a).width, wb = g.measureText(b).width;
        const w = wa + wb + 26, box = { x: sx - w / 2 - 3, y: sy - 36, w: w + 6, h: 42 };
        if (hit(box)) { tryPill(sx, sy, null, `0 $CITY`, '#0d2a1d', '#39ff88', '#39ff88'); continue; }
        placed.push(box);
        g.fillStyle = '#0d2a1d'; this._rr(sx - w / 2, sy - 33, w, 33, 10); g.fill(); g.strokeStyle = '#39ff88'; g.lineWidth = 1.5; g.stroke();
        g.textBaseline = 'middle'; g.textAlign = 'left';
        const x0 = sx - (wa + wb + 8) / 2;
        g.fillStyle = '#8fa8a0'; g.fillText(a, x0, sy - 22);
        g.strokeStyle = '#ff5d7a'; g.lineWidth = 1.6; g.beginPath(); g.moveTo(x0 - 1, sy - 22); g.lineTo(x0 + wa + 1, sy - 22); g.stroke();
        g.fillStyle = '#39ff88'; g.fillText(b, x0 + wa + 8, sy - 22);
        g.font = '700 9px "Segoe UI", Arial'; g.fillStyle = '#bff8d6'; g.textAlign = 'center'; g.fillText(L.lvl0, sx, sy - 9);
        continue;
      }
      if (viewer === 'zero') tryPill(sx, sy, `🔒 ${fmt(full)} $CITY`, `🔒 ${short(full)}`, '#3a4256', '#c3cbe0', '#6b7590');
      else tryPill(sx, sy, `${fmt(full)} $CITY`, short(full), '#1fd17a', '#032313', '#a6ffd0');
    }
  }

  _icon(kind, x, y) {                                  // drawn (not emoji): works without an emoji font
    const g = this.ctx;
    if (kind === '⏸') { g.fillStyle = '#ffd84d'; g.fillRect(x - 3.5, y - 4, 2.6, 8); g.fillRect(x + 0.9, y - 4, 2.6, 8); }
    else if (kind === '📦') { g.strokeStyle = '#7fe8ff'; g.lineWidth = 1.6; g.strokeRect(x - 4, y - 3, 8, 7); g.beginPath(); g.moveTo(x - 4, y); g.lineTo(x + 4, y); g.stroke(); }
    else { g.fillStyle = '#ff5d7a'; g.font = '900 11px "Segoe UI", Arial'; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText('!', x, y + 1); }
  }

  _statusIcons(c) {                                    // ⏸ shift over · 📦 warehouse full · 🔧 needs repair
    const b = c.building || {}, out = [];
    const ends = b.shiftEndsAt ? new Date(b.shiftEndsAt).getTime() : 0;
    if (!ends || ends < Date.now()) out.push('⏸');
    if (b.workReason === 'storage_full') out.push('📦');
    if ((b.durability ?? 100) < 20) out.push('🔧');
    return out;
  }

  // mini-map (bottom-left): island, own lots, lots on sale, the visible area; tap = jump
  _drawMinimap(m) {
    if (!m.hasLayout) return;
    const g = this.ctx, n = m.grid, W = 112, H = 58, x0 = 10, y0 = this.h - H - 96;
    this._mm = { x0, y0, W, H, n };
    const P = (gx, gy) => [x0 + W / 2 + (gx - gy) * (W / 2 / n), y0 + (gx + gy) * (H / 2 / n)];
    g.fillStyle = 'rgba(5,10,22,0.78)'; this._rr(x0 - 4, y0 - 4, W + 8, H + 8, 8); g.fill();
    g.strokeStyle = 'rgba(0,240,255,0.35)'; g.lineWidth = 1; g.stroke();
    const d = [P(0, 0), P(n, 0), P(n, n), P(0, n)];
    g.beginPath(); d.forEach(([a, b], i) => (i ? g.lineTo(a, b) : g.moveTo(a, b))); g.closePath();
    g.fillStyle = '#26304a'; g.fill();
    for (const c of m.cells) {
      const mine = this._mine(c), sale = !mine && (this._available(c) || !!this._listing(c) || !!(this._state().rentOffers || {})[`${c.q},${c.r}`]);
      if (!mine && !sale) continue;
      const [a, b] = P(c.q + (c.w || 1) / 2, c.r + (c.h || 1) / 2);
      g.fillStyle = mine ? '#ff8a00' : '#39ff88'; g.fillRect(a - 1.2, b - 1.2, mine ? 3 : 2.4, mine ? 3 : 2.4);
    }
    // visible area
    const [wx0, wy0] = this._toWorld(0, 0), [wx1, wy1] = this._toWorld(this.w, this.h);
    const toMM = (wx, wy) => { const gx = (wx / TW + wy / TH) / 2, gy = (wy / TH - wx / TW) / 2; return P(gx, gy); };
    const c4 = [toMM(wx0, wy0), toMM(wx1, wy0), toMM(wx1, wy1), toMM(wx0, wy1)];
    g.save(); this._rr(x0 - 4, y0 - 4, W + 8, H + 8, 8); g.clip();
    g.strokeStyle = '#ffffff'; g.lineWidth = 1.2; g.beginPath(); c4.forEach(([a, b], i) => (i ? g.lineTo(a, b) : g.moveTo(a, b))); g.closePath(); g.stroke();
    g.restore();
  }

  _miniTap(sx, sy) {                                  // tap inside the mini-map -> move the camera there
    const mm = this._mm; if (!mm) return false;
    if (sx < mm.x0 - 4 || sx > mm.x0 + mm.W + 4 || sy < mm.y0 - 4 || sy > mm.y0 + mm.H + 4) return false;
    const u = (sx - mm.x0 - mm.W / 2) / (mm.W / 2 / mm.n), v = (sy - mm.y0) / (mm.H / 2 / mm.n);   // u = gx-gy, v = gx+gy
    const gx = (u + v) / 2, gy = (v - u) / 2, [wx, wy] = this._iso(gx, gy);
    this._flyTo(wx, wy, this.cam.z); return true;
  }

  _drawDistricts(m, st) {                            // names / numbers are admin-only: the map shows just the lock
    const g = this.ctx;
    const label = (st.labels && st.labels.closed) || 'СЕКТОР ЗАКРЫТ';
    // screen areas covered by the page UI: the right button column and the mini-map.
    // A lock whose plaque would land there is skipped, so it never sits under the buttons.
    const safeR = this.opts.safeRight ?? 76, safeB = this.w < 768 ? 96 : 8, mm = this._mm;   // phones: bottom menu
    const blocked = (x0, y0, x1, y1) =>
      x1 > this.w - safeR || x0 < 4 || y0 < 4 || y1 > this.h - safeB ||
      (mm && x0 < mm.x0 + mm.W + 8 && y1 > mm.y0 - 8);
    for (const [d, k] of Object.entries(m.centers)) {
      const locked = st.districts && st.districts.unlocked && st.districts.unlocked[d] === false;
      if (!locked) continue;
      const [wx, wy] = this._iso(k.x / k.n, k.y / k.n), [sx, sy] = this._toScreen(wx, wy);
      g.font = '900 12px "Segoe UI", Arial';
      const half = g.measureText(label).width / 2 + 10;
      if (blocked(sx - half, sy - 32, sx + half, sy + 24)) continue;
      g.textAlign = 'center'; g.textBaseline = 'middle';
      g.font = '28px sans-serif'; g.fillText('🔒', sx, sy - 14);
      g.font = '900 12px "Segoe UI", Arial';
      g.fillStyle = 'rgba(10,6,16,0.82)'; this._rr(sx - half, sy + 2, half * 2, 22, 11); g.fill();
      g.strokeStyle = 'rgba(255,93,122,0.45)'; g.lineWidth = 1.5; g.stroke();
      g.fillStyle = '#ff5d7a'; g.fillText(label, sx, sy + 13);
    }
  }

  // ───────────────────────── input ─────────────────────────
  _bind() {
    const c = this.canvas;
    this._h = {
      down: (e) => {
        c.setPointerCapture?.(e.pointerId); this._pointers.set(e.pointerId, [e.clientX, e.clientY]);
        if (this._pointers.size === 1) this._down = { x: e.clientX, y: e.clientY, cx: this.cam.x, cy: this.cam.y, moved: false };
        if (this._pointers.size === 2) { const [a, b] = [...this._pointers.values()]; this._pinch = { d: Math.hypot(a[0] - b[0], a[1] - b[1]), z: this.cam.z }; this._down = null; }
      },
      move: (e) => {
        if (this._pointers.has(e.pointerId)) this._pointers.set(e.pointerId, [e.clientX, e.clientY]);
        const r = c.getBoundingClientRect();
        if (this._pinch && this._pointers.size === 2) {
          const [a, b] = [...this._pointers.values()];
          const f = (this._pinch.z * Math.hypot(a[0] - b[0], a[1] - b[1]) / this._pinch.d) / this.cam.z;
          this._zoomAt((a[0] + b[0]) / 2 - r.left, (a[1] + b[1]) / 2 - r.top, f); return;
        }
        if (this._down) {
          const dx = e.clientX - this._down.x, dy = e.clientY - this._down.y;
          if (Math.abs(dx) + Math.abs(dy) > 6) this._down.moved = true;
          if (this._down.moved) { this.cam.x = this._down.cx - dx / this.cam.z; this.cam.y = this._down.cy - dy / this.cam.z; this._clamp(); this._invalidate(); }
        } else if (e.pointerType === 'mouse' && this.opts.onCellHover) {
          this.opts.onCellHover(this._pick(e.clientX - r.left, e.clientY - r.top));
        }
      },
      up: (e) => {
        this._pointers.delete(e.pointerId);
        if (this._pointers.size < 2) this._pinch = null;
        if (this._down && !this._down.moved && e.type === 'pointerup') {
          const r = c.getBoundingClientRect();
          if (this._miniTap(e.clientX - r.left, e.clientY - r.top)) { this._down = null; return; }
          const cell = this._pick(e.clientX - r.left, e.clientY - r.top);
          if (cell && this.opts.onCellClick) { mapStore.dispatch({ type: 'SET_SELECTED', cell }); this.opts.onCellClick(cell); }
        }
        if (this._pointers.size === 0) this._down = null;
      },
      wheel: (e) => { e.preventDefault(); const r = c.getBoundingClientRect(); this._zoomAt(e.clientX - r.left, e.clientY - r.top, Math.exp(-e.deltaY * 0.0015)); },
    };
    c.addEventListener('pointerdown', this._h.down); c.addEventListener('pointermove', this._h.move);
    c.addEventListener('pointerup', this._h.up); c.addEventListener('pointercancel', this._h.up);
    c.addEventListener('wheel', this._h.wheel, { passive: false });
  }
  _unbind() {
    const c = this.canvas; if (!c || !this._h) return;
    c.removeEventListener('pointerdown', this._h.down); c.removeEventListener('pointermove', this._h.move);
    c.removeEventListener('pointerup', this._h.up); c.removeEventListener('pointercancel', this._h.up);
    c.removeEventListener('wheel', this._h.wheel);
  }

  _zoomAt(sx, sy, f) {
    const [wx, wy] = this._toWorld(sx, sy);
    this.cam.z = Math.max(MIN_Z, Math.min(MAX_Z, this.cam.z * f));
    this.cam.x = wx - (sx - this.w / 2) / this.cam.z; this.cam.y = wy - (sy - this.h / 2) / this.cam.z;
    this._clamp(); this._invalidate();
  }
  _clamp() {
    const b = this._bounds(); if (!b) return;
    this.cam.x = Math.max(b.minX, Math.min(b.maxX, this.cam.x)); this.cam.y = Math.max(b.minY - 100, Math.min(b.maxY, this.cam.y));
  }

  _pick(sx, sy) {                                      // building sprite first (front to back), then the ground tile
    const [wx, wy] = this._toWorld(sx, sy);
    for (let i = (this._hit || []).length - 1; i >= 0; i--) {
      const h = this._hit[i];
      if (wx >= h.x + h.w * 0.15 && wx <= h.x + h.w * 0.85 && wy >= h.y && wy <= h.y + h.h) return h.c;
    }
    const gx = Math.floor((wx / TW + wy / TH) / 2), gy = Math.floor((wy / TH - wx / TW) / 2);
    return this._model().cover.get(`${gx},${gy}`) || null;
  }
}

export default CityMapEngine;
