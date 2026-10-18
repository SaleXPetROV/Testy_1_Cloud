// Isometric sprite kit: draws buildings as SVG strings (512x512, transparent).
const C30 = Math.cos(Math.PI / 6), S30 = 0.5;
let SC = 29, CX = 256, CY = 420;                   // scale & origin of the iso grid (canvas 512x640)
// growth stage: everything above the plinth (z > 1.15) is stretched by HS;
// SX/SY squeeze the footprint (1x2 lots use SY = 0.5)
let HS = 1, SX = 1, SY = 1, TINT = null, TINT_K = 0.24, BS = 1, BUILD = true, LIFT = 0.1;
const BASE = 0.5;                                   // top of the (thin) foundation   // BS: building scale vs. its plinth
const PLINTH_TOP = 1.15;
const P = (x, y, z) => {
  // building parts: designed on a 1.15 plinth -> moved down onto the thin foundation, stretched by stage & scale
  const zz = BUILD ? BASE + Math.max(0, z - PLINTH_TOP) * HS * BS : z;
  const s = BUILD ? BS : 1;
  const xx = x * SX * s, yy = y * SY * s;
  return [CX + (xx - yy) * C30 * SC, CY + (xx + yy) * S30 * SC - zz * SC];
};
const pts = (a) => a.map(p => p.map(v => v.toFixed(1)).join(',')).join(' ');
let DEFS = [], uid = 0;
function grad(stops, x1 = 0, y1 = 0, x2 = 0, y2 = 1) {
  const id = 'g' + (uid++);
  DEFS.push(`<linearGradient id="${id}" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}">${stops.map(([o, c]) => `<stop offset="${o}" stop-color="${c}"/>`).join('')}</linearGradient>`);
  return `url(#${id})`;
}
function mix(a, b, t) {
  const pa = parseInt(a.slice(1), 16), pb = parseInt(b.slice(1), 16);
  const ch = (p, s) => (p >> s) & 255, m = (s) => Math.round(ch(pa, s) * (1 - t) + ch(pb, s) * t);
  return '#' + ((1 << 24) + (m(16) << 16) + (m(8) << 8) + m(0)).toString(16).slice(1);
}
function tint(col) { col = shade(col, LIFT); return TINT ? mix(col, TINT, TINT_K) : col; }
function shade(hex, f) {                            // lighten (f>0) / darken (f<0)
  const n = parseInt(hex.slice(1), 16); let r = n >> 16, g = (n >> 8) & 255, b = n & 255;
  const t = f < 0 ? 0 : 255, p = Math.abs(f);
  r = Math.round((t - r) * p + r); g = Math.round((t - g) * p + g); b = Math.round((t - b) * p + b);
  return '#' + ((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1);
}
// a box with footprint [x,y,w,d] from z to z+h. faces: top, left (front-left), right (front-right)
function box(x, y, z, w, d, h, col, o = {}) {
  col = tint(col);
  const top = [P(x, y, z + h), P(x + w, y, z + h), P(x + w, y + d, z + h), P(x, y + d, z + h)];
  const left = [P(x, y + d, z), P(x + w, y + d, z), P(x + w, y + d, z + h), P(x, y + d, z + h)];
  const right = [P(x + w, y, z), P(x + w, y + d, z), P(x + w, y + d, z + h), P(x + w, y, z + h)];
  const st = o.stroke || shade(col, -0.72);
  const warm = mix(shade(col, 0.45), '#fff1d0', 0.25);
  const ao = Math.min(h, 0.7), aoG = grad([[0, 'rgba(0,0,0,0)'], [1, 'rgba(0,0,0,0.42)']]);
  let s = `<polygon points="${pts(left)}" fill="${o.lf || grad([[0, shade(col, 0.16)], [1, shade(col, -0.2)]])}" stroke="${st}" stroke-width="1.4" stroke-linejoin="round"/>` +
          `<polygon points="${pts([P(x, y + d, z), P(x + w, y + d, z), P(x + w, y + d, z + ao), P(x, y + d, z + ao)])}" fill="${aoG}"/>` +
          `<polygon points="${pts(right)}" fill="${o.rf || grad([[0, shade(col, -0.3)], [1, shade(col, -0.56)]])}" stroke="${st}" stroke-width="1.4" stroke-linejoin="round"/>` +
          `<polygon points="${pts([P(x + w, y, z), P(x + w, y + d, z), P(x + w, y + d, z + ao), P(x + w, y, z + ao)])}" fill="${aoG}"/>`;
  // panel seams on tall faces (metal plating) + rivets
  if (h > 0.9 && !o.plain) {
    const rows = Math.max(1, Math.round(h / 1.1));
    for (let r = 1; r < rows; r++) {
      const zz = z + h * r / rows;
      s += `<line x1="${P(x, y + d, zz)[0]}" y1="${P(x, y + d, zz)[1]}" x2="${P(x + w, y + d, zz)[0]}" y2="${P(x + w, y + d, zz)[1]}" stroke="${shade(col, -0.45)}" stroke-width="1.4" opacity=".7"/>`;
      s += `<line x1="${P(x + w, y, zz)[0]}" y1="${P(x + w, y, zz)[1]}" x2="${P(x + w, y + d, zz)[0]}" y2="${P(x + w, y + d, zz)[1]}" stroke="${shade(col, -0.7)}" stroke-width="1.4" opacity=".7"/>`;
    }
    for (const [px, pz] of [[x + 0.18, z + 0.2], [x + w - 0.18, z + 0.2], [x + 0.18, z + h - 0.25], [x + w - 0.18, z + h - 0.25]]) {
      const p = P(px, y + d, pz); s += `<circle cx="${p[0]}" cy="${p[1]}" r="1.8" fill="${shade(col, 0.5)}" stroke="${shade(col, -0.6)}" stroke-width=".6"/>`;
    }
  }
  // top with a rounded lip: darker outer ring + warm inner cap
  const ins = Math.min(0.22, w * 0.12, d * 0.12);
  const cap = [P(x + ins, y + ins, z + h), P(x + w - ins, y + ins, z + h), P(x + w - ins, y + d - ins, z + h), P(x + ins, y + d - ins, z + h)];
  s += `<polygon points="${pts(top)}" fill="${o.tf || shade(col, 0.12)}" stroke="${st}" stroke-width="1.4" stroke-linejoin="round"/>` +
       `<polygon points="${pts(cap)}" fill="${o.tf || grad([[0, warm], [1, shade(col, 0.2)]], 0, 0, 1, 1)}"/>` +
       `<polyline points="${pts([P(x, y + d, z + h), P(x + w, y + d, z + h)])}" fill="none" stroke="rgba(255,244,214,0.75)" stroke-width="2.4" stroke-linecap="round" transform="translate(0,1.6)"/>` +
       // coloured rim light on the right edge (neon bounce)
       `<line x1="${P(x + w, y, z + h)[0]}" y1="${P(x + w, y, z + h)[1] + 2}" x2="${P(x + w, y, z)[0]}" y2="${P(x + w, y, z)[1] - 2}" stroke="${TINT || '#7fe8ff'}" stroke-width="2" opacity=".55"/>`;
  return s;
}
// glowing edge line along a box's top rim
function rim(x, y, z, w, d, glow, wdt = 2.2) {
  const a = [P(x, y + d, z), P(x + w, y + d, z), P(x + w, y, z)];
  return `<polyline points="${pts(a)}" fill="none" stroke="${glow}" stroke-width="${wdt}" filter="url(#glow)" opacity=".95"/>`;
}
// windows on the left (y+d) face: cols x rows
function winL(x, y, z, w, d, h, cols, rows, glow, on = 0.75) {
  let s = ''; const mw = w / cols, mh = h / rows;
  for (let i = 0; i < cols; i++) for (let j = 0; j < rows; j++) {
    const x0 = x + i * mw + mw * .2, x1 = x + (i + 1) * mw - mw * .2, z0 = z + j * mh + mh * .25, z1 = z + (j + 1) * mh - mh * .2;
    const lit = ((i * 7 + j * 13) % 10) / 10 < on;
    s += `<polygon points="${pts([P(x0, y + d, z0), P(x1, y + d, z0), P(x1, y + d, z1), P(x0, y + d, z1)])}" fill="${lit ? glow : '#0b1018'}" opacity="${lit ? .9 : 1}" ${lit ? 'filter="url(#glowS)"' : ''}/>`;
  }
  return s;
}
function winR(x, y, z, w, d, h, cols, rows, glow, on = 0.7) {
  let s = ''; const md = d / cols, mh = h / rows;
  for (let i = 0; i < cols; i++) for (let j = 0; j < rows; j++) {
    const y0 = y + i * md + md * .2, y1 = y + (i + 1) * md - md * .2, z0 = z + j * mh + mh * .25, z1 = z + (j + 1) * mh - mh * .2;
    const lit = ((i * 11 + j * 5) % 10) / 10 < on;
    s += `<polygon points="${pts([P(x + w, y0, z0), P(x + w, y1, z0), P(x + w, y1, z1), P(x + w, y0, z1)])}" fill="${lit ? shade(glow, -0.25) : '#090d14'}" opacity="${lit ? .85 : 1}" ${lit ? 'filter="url(#glowS)"' : ''}/>`;
  }
  return s;
}
// vertical cylinder centred at (x,y), radius r (iso units), from z, height h
function cyl(x, y, z, r, h, col, o = {}) {
  const [bx, by] = P(x, y, z), [tx, ty] = P(x, y, z + h), rx = r * C30 * SC * 1.15 * Math.min(SX, SY) ** 0.5, ry = rx * 0.5;
  col = tint(col); const g = grad([[0, shade(col, -0.5)], [0.22, shade(col, 0.05)], [0.34, shade(col, 0.5)], [0.42, shade(col, 0.1)], [0.75, shade(col, -0.3)], [1, shade(col, -0.62)]], 0, 0, 1, 0);
  return `<path d="M${bx - rx},${by} L${tx - rx},${ty} A${rx},${ry} 0 0 1 ${tx + rx},${ty} L${bx + rx},${by} A${rx},${ry} 0 0 1 ${bx - rx},${by}Z" fill="${g}" stroke="#0a0d18" stroke-width="2.2"/>` +
         `<ellipse cx="${tx}" cy="${ty}" rx="${rx}" ry="${ry}" fill="${o.top || shade(col, 0.4)}" stroke="#0a0d18" stroke-width="2.2"/>`;
}
function ring(x, y, z, r, glow, w = 3) {
  const [cx, cy] = P(x, y, z), rx = r * C30 * SC * 1.15;
  return `<ellipse cx="${cx}" cy="${cy}" rx="${rx}" ry="${rx / 2}" fill="none" stroke="${glow}" stroke-width="${w}" filter="url(#glow)"/>`;
}
function dome(x, y, z, r, col, alpha = .55) {
  const [cx, cy] = P(x, y, z), rx = r * C30 * SC * 1.15;
  const g = grad([[0, shade(col, 0.55)], [1, shade(col, -0.2)]], 0.2, 0, 0.8, 1);
  return `<path d="M${cx - rx},${cy} A${rx},${rx * 1.05} 0 0 1 ${cx + rx},${cy} A${rx},${rx / 2} 0 0 1 ${cx - rx},${cy}Z" fill="${g}" opacity="${alpha}" stroke="${shade(col, 0.4)}" stroke-width="1.5"/>` +
         `<path d="M${cx - rx * .6},${cy - rx * .62} A${rx * .62},${rx * .62} 0 0 1 ${cx + rx * .05},${cy - rx * .98}" fill="none" stroke="#fff" stroke-width="6" stroke-linecap="round" opacity=".7"/>` +
         `<circle cx="${cx + rx * .35}" cy="${cy - rx * .62}" r="${rx * .08}" fill="#fff" opacity=".85"/>`;
}
function line(a, b, col, w = 2.5, glow = false) {
  return `<line x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}" stroke="${col}" stroke-width="${w}" stroke-linecap="round" ${glow ? 'filter="url(#glow)"' : ''}/>`;
}
function poly(a, fill, o = {}) { return `<polygon points="${pts(a)}" fill="${fill}" stroke="${o.stroke || 'none'}" stroke-width="${o.sw || 1}" ${o.glow ? 'filter="url(#glow)"' : ''} opacity="${o.op ?? 1}"/>`; }
function dot(p, r, col, glow = true) { return `<circle cx="${p[0]}" cy="${p[1]}" r="${r}" fill="${col}" ${glow ? 'filter="url(#glow)"' : ''}/>`; }
// standard plinth every building stands on (same footprint for all skins)
function plinth(glow) {
  const t = TINT, b = BUILD; TINT = null; BUILD = false;
  let s = box(-3.9, -3.9, 0, 7.8, 7.8, BASE, '#56658c', { plain: true });
  // two rows of foundation blocks on the visible sides
  for (let k2 = -3.9 + 1.3; k2 < 3.9; k2 += 1.3) {
    s += `<line x1="${P(k2, 3.9, 0)[0]}" y1="${P(k2, 3.9, 0)[1]}" x2="${P(k2, 3.9, BASE)[0]}" y2="${P(k2, 3.9, BASE)[1]}" stroke="#2c3655" stroke-width="1.3"/>`;
    s += `<line x1="${P(3.9, k2, 0)[0]}" y1="${P(3.9, k2, 0)[1]}" x2="${P(3.9, k2, BASE)[0]}" y2="${P(3.9, k2, BASE)[1]}" stroke="#1d2540" stroke-width="1.3"/>`;
  }
  s += rim(-3.9, -3.9, BASE, 7.8, 7.8, glow, 2.2);
  for (const [x, y] of [[-3.9, 3.9], [3.9, 3.9], [3.9, -3.9]]) s += dot(P(x, y, BASE), 3, glow);
  TINT = t; BUILD = b; return s;
}
function wrap(body) {
  const defs = `<defs><filter id="glow" filterUnits="userSpaceOnUse" x="0" y="0" width="512" height="640"><feGaussianBlur stdDeviation="3" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>` +
    `<filter id="toon" filterUnits="userSpaceOnUse" x="0" y="0" width="512" height="640"><feMorphology in="SourceAlpha" operator="dilate" radius="1.6" result="d"/><feFlood flood-color="#141b3a"/><feComposite in2="d" operator="in" result="o"/><feMerge><feMergeNode in="o"/><feMergeNode in="SourceGraphic"/></feMerge></filter><filter id="glowS" filterUnits="userSpaceOnUse" x="0" y="0" width="512" height="640"><feGaussianBlur stdDeviation="1.4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>${DEFS.join('')}</defs>`;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="512" height="640" viewBox="0 0 512 640">${defs}` +
    `<ellipse cx="256" cy="${CY + 8}" rx="${205 * (SX + SY) / 2}" ry="${98 * (SX + SY) / 2}" fill="#000" opacity=".28" filter="url(#shadowBlur)"/><g id="bld" filter="url(#toon)">${body}</g><g id="extras"></g></svg>`;
  DEFS = []; return svg.replace('<defs>', '<defs><filter id="shadowBlur"><feGaussianBlur stdDeviation="10"/></filter>');
}

// decorations of growth stages 2 and 3 (drawn on top of any building)
function stageExtras(stage, glow) {
  const bs = BS, bd = BUILD; BS = 1; BUILD = false;
  let s = '';
  if (stage >= 2) {                                   // neon lamp posts on the front corners of the lot
    for (const [x, y] of [[-3.7, 3.7], [3.7, -3.7], [3.7, 3.7]]) {
      const b = P(x, y, BASE), t = [b[0], b[1] - 30];
      s += line(b, t, '#8d98ae', 2.6) + dot(t, 5.5, glow) + `<circle cx="${t[0]}" cy="${t[1]}" r="14" fill="${glow}" opacity=".22" filter="url(#glow)"/>`;
    }
  }
  if (stage >= 3) {                                   // double neon trim of the plinth
    s += rim(-3.9, -3.9, BASE * 0.5, 7.8, 7.8, '#ffffff', 1.3);
  }
  BS = bs; BUILD = bd; return s;
}
