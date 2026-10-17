const T1 = '#00F0FF', T2 = '#B36BFF', T3 = '#FFD84D';
const B = {};
B.helios = () => {                                       // solar station: tilted panels + tower
  let s = plinth(T1);
  for (const [px, py] of [[-3.2, -3.2], [0.3, -3.2], [-3.2, 0.3]]) {
    s += box(px + 1.2, py + 1.2, 1.15, 0.4, 0.4, 0.9, '#3a4458');
    const a = P(px, py + 2.7, 2.1), b = P(px + 2.8, py + 2.7, 2.1), c = P(px + 2.8, py, 3.1), d = P(px, py, 3.1);
    s += poly([a, b, c, d], grad([[0, '#0d4a7a'], [0.5, '#1d7ec4'], [1, '#0a2f55']], 0, 0, 1, 1), { stroke: '#7fd8ff', sw: 1.4 });
    for (let k = 1; k < 4; k++) { const t = k / 4; s += line([a[0] + (d[0] - a[0]) * t, a[1] + (d[1] - a[1]) * t], [b[0] + (c[0] - b[0]) * t, b[1] + (c[1] - b[1]) * t], '#7fd8ff', 0.8); }
    s += line(d, c, T1, 2, true);
  }
  s += box(1.3, 1.3, 1.15, 1.9, 1.9, 3.6, '#39445a') + winL(1.3, 1.3, 1.15, 1.9, 1.9, 3.6, 2, 3, T1) + winR(1.3, 1.3, 1.15, 1.9, 1.9, 3.6, 2, 3, T1);
  s += cyl(2.25, 2.25, 4.75, 0.55, 0.7, '#4a5670') + dot(P(2.25, 2.25, 5.6), 9, '#FFE27A');
  s += `<circle cx="${P(2.25, 2.25, 5.6)[0]}" cy="${P(2.25, 2.25, 5.6)[1]}" r="22" fill="#FFD84D" opacity=".25" filter="url(#glow)"/>`;
  return wrap(s);
};
B.quartz_mine = () => {                                  // mine building + big crystal cluster + drill
  let s = plinth(T1);
  s += box(-3.5, -0.2, 1.15, 3.0, 3.6, 2.2, '#3b4256') + winL(-3.5, -0.2, 1.15, 3.0, 3.6, 2.2, 3, 2, T1) + rim(-3.5, -0.2, 3.35, 3.0, 3.6, T1, 1.6);
  const cl = [[1.7, 1.2, 4.6, 1.25, '#9BF3FF'], [2.9, 2.6, 3.4, 1.0, '#C9A6FF'], [0.4, 2.8, 3.0, 0.9, '#7DE8FF'], [2.9, -0.4, 2.6, 0.85, '#B8F7FF'], [1.0, -1.6, 2.0, 0.7, '#DCC6FF']];
  for (const [x, y, h, r, c] of cl) {
    const base = P(x, y, 1.15), tip = P(x, y, 1.15 + h), l = [base[0] - r * 26, base[1] - 4], rr = [base[0] + r * 26, base[1] - 4], m = [base[0], base[1] + r * 14];
    s += `<circle cx="${tip[0]}" cy="${(tip[1] + base[1]) / 2}" r="${30 * r}" fill="${c}" opacity=".28" filter="url(#glow)"/>`;
    s += poly([l, tip, m], grad([[0, '#ffffff'], [0.4, c], [1, shade(c, -0.5)]], 0, 0, 1, 1), { stroke: '#f2feff', sw: 1.2 });
    s += poly([m, tip, rr], grad([[0, shade(c, -0.2)], [1, shade(c, -0.7)]], 0, 0, 1, 1), { stroke: '#f2feff', sw: 1.2 });
  }
  const f = [P(-3.2, 0.1, 3.35), P(-0.8, 0.1, 3.35), P(-0.8, 3.1, 3.35), P(-3.2, 3.1, 3.35)], top = P(-2.0, 1.6, 7.0);
  for (const c of f) s += line(c, top, '#9aa6bd', 3);
  for (let k = 1; k < 4; k++) { const t = k / 4; s += line([f[0][0] + (top[0] - f[0][0]) * t, f[0][1] + (top[1] - f[0][1]) * t], [f[1][0] + (top[0] - f[1][0]) * t, f[1][1] + (top[1] - f[1][1]) * t], '#7c879c', 1.6); }
  s += line(P(-2.0, 1.6, 3.35), P(-2.0, 1.6, 7.0), T1, 3, true) + dot(top, 7, T1);
  return wrap(s);
};
B.gram_bank = () => {                                    // columns, golden roof, vault
  let s = plinth(T3);
  s += box(-3.3, -3.3, 1.15, 6.6, 6.6, 0.5, '#e8e2cf', { stroke: '#8d846a' });
  s += box(-2.8, -2.8, 1.65, 5.6, 5.6, 3.2, '#2f3a50') + winR(-2.8, -2.8, 1.65, 5.6, 5.6, 3.2, 4, 2, T3, .6);
  for (let i = 0; i < 5; i++) s += cyl(-2.6 + i * 1.3, 2.95, 1.65, 0.28, 3.2, '#f2ecd8');
  s += box(-3.1, -3.1, 4.85, 6.2, 6.2, 0.45, '#f4eedb', { stroke: '#8d846a' });
  const a = P(-3.1, 3.1, 5.3), b = P(3.1, 3.1, 5.3), c = P(3.1, -3.1, 5.3), ap = P(0, 0, 7.3);
  s += poly([a, b, ap], grad([[0, '#FFE58A'], [1, '#C9971F']], 0, 0, 1, 1), { stroke: '#8a6510', sw: 1.4 });
  s += poly([b, c, ap], grad([[0, '#D9A92E'], [1, '#8f6a14']], 0, 0, 1, 1), { stroke: '#8a6510', sw: 1.4 });
  s += line(a, b, T3, 2.5, true) + line(b, c, T3, 2.5, true);
  const coin = P(0, 3.15, 5.55);
  s += `<circle cx="${coin[0]}" cy="${coin[1] - 14}" r="13" fill="#FFD84D" stroke="#8a6510" stroke-width="2" filter="url(#glowS)"/><text x="${coin[0]}" y="${coin[1] - 9}" font-size="15" font-weight="900" text-anchor="middle" fill="#6b4b00" font-family="Arial">G</text>`;
  return wrap(s);
};

B.nano_dc = () => {                                      // data centre: server blocks + LED strips + dish
  let s = plinth(T1);
  s += box(-3.3, -3.3, 1.15, 6.6, 6.6, 3.6, '#2b3446') + rim(-3.3, -3.3, 4.75, 6.6, 6.6, T1);
  for (let k = 0; k < 6; k++) {
    s += line(P(-3.3 + 0.4 + k * 1.05, 3.3, 1.5), P(-3.3 + 0.4 + k * 1.05, 3.3, 4.4), k % 2 ? T1 : '#4dff9b', 3, true);
    s += line(P(3.3, -3.3 + 0.4 + k * 1.05, 1.5), P(3.3, -3.3 + 0.4 + k * 1.05, 4.4), k % 2 ? '#4dff9b' : T1, 2.4, true);
  }
  s += box(-2.4, -2.4, 4.75, 2.4, 2.4, 0.9, '#3a465c') + box(0.6, 0.6, 4.75, 2.0, 2.0, 0.6, '#3a465c');
  const c = P(1.6, -1.4, 5.6); s += line(P(1.6, -1.4, 4.75), c, '#9aa6bd', 3);
  s += `<ellipse cx="${c[0]}" cy="${c[1] - 6}" rx="26" ry="15" fill="${grad([[0, '#dfe8f5'], [1, '#7a879c']])}" stroke="#55627a" stroke-width="1.5" transform="rotate(-25 ${c[0]} ${c[1] - 6})"/>` + dot([c[0] + 4, c[1] - 14], 4, T1);
  return wrap(s);
};
B.signal_tower = () => {                                 // lattice tower + antennas + signal rings
  let s = plinth(T1) + box(-3.2, 0.8, 1.15, 2.6, 2.6, 1.6, '#39445a') + winL(-3.2, 0.8, 1.15, 2.6, 2.6, 1.6, 2, 1, T1);
  const legs = [[0.3, -1.7], [2.7, -1.7], [2.7, 0.7], [0.3, 0.7]], top = P(1.5, -0.5, 9.0);
  for (const [x, y] of legs) s += line(P(x, y, 1.15), top, '#a6b2c9', 3.2);
  for (let z = 2.2; z < 8.6; z += 1.3) { const t = (z - 1.15) / (9 - 1.15); const q = legs.map(([x, y]) => P(x + (1.5 - x) * t, y + (-0.5 - y) * t, z)); s += `<polygon points="${pts(q)}" fill="none" stroke="#7d899f" stroke-width="1.6"/>`; }
  for (const r of [26, 44, 62]) s += `<path d="M${top[0] - r},${top[1] - r * .2} A${r},${r * .7} 0 0 1 ${top[0] + r},${top[1] - r * .2}" fill="none" stroke="${T1}" stroke-width="2.5" opacity="${1 - r / 90}" filter="url(#glow)"/>`;
  s += dot(top, 8, '#ff5d7a');
  return wrap(s);
};
B.hydro_cooling = () => {                                // cooling towers + frost + pipes
  let s = plinth(T1) + box(-3.4, 0.6, 1.15, 3.0, 2.8, 2.0, '#3d4a60') + winL(-3.4, 0.6, 1.15, 3.0, 2.8, 2.0, 3, 1, '#9EE7FF');
  for (const [x, y, h] of [[1.4, -1.4, 4.4], [1.6, 2.0, 3.6]]) {
    s += cyl(x, y, 1.15, 1.35, h, '#c9d7e8', { top: '#1a2433' });
    s += ring(x, y, 1.15 + h * 0.62, 1.38, '#9EE7FF', 2.4);
    const t = P(x, y, 1.15 + h); for (let k = 0; k < 3; k++) s += `<ellipse cx="${t[0] + (k - 1) * 14}" cy="${t[1] - 22 - k * 16}" rx="${22 + k * 6}" ry="${12 + k * 3}" fill="#e9f7ff" opacity="${.5 - k * .12}" filter="url(#glow)"/>`;
  }
  s += line(P(-0.4, 1.8, 2.2), P(0.4, 1.8, 2.2), '#9aa6bd', 5) + line(P(-0.4, -0.6, 2.6), P(0.2, -1.2, 2.6), '#9aa6bd', 5);
  return wrap(s);
};
B.bio_farm = () => {                                     // glass dome with glowing plants
  let s = plinth('#4dff9b') + box(-3.0, -3.0, 1.15, 6.0, 6.0, 1.0, '#3b4658') + rim(-3.0, -3.0, 2.15, 6.0, 6.0, '#4dff9b');
  for (const [x, y, h, c] of [[-1, 0.5, 1.6, '#4dff9b'], [0.6, -0.6, 2.2, '#7dffb5'], [1.0, 1.3, 1.3, '#b6ff6b'], [-0.5, -1.5, 1.8, '#4dff9b']]) {
    const b0 = P(x, y, 2.15), t = P(x, y, 2.15 + h);
    s += line(b0, t, '#2bbf6a', 3) + `<ellipse cx="${t[0]}" cy="${t[1]}" rx="12" ry="9" fill="${c}" filter="url(#glowS)"/>`;
  }
  s += dome(0, 0, 2.15, 3.2, '#8fe8ff', .45);
  return wrap(s);
};
B.scrap_yard = () => {                                   // scrap piles + crane + compactor
  let s = plinth('#ffb347');
  for (const [x, y, w, d, h, c] of [[-3.3, 0.6, 2.4, 2.6, 1.2, '#6f5b47'], [-1.0, 1.6, 1.6, 1.8, 0.8, '#5a6372'], [0.9, 1.9, 1.4, 1.4, 1.0, '#7b4e3a'], [-2.6, -1.5, 1.4, 1.6, 0.9, '#55606f']])
    s += box(x, y, 1.15, w, d, h, c);
  s += box(0.9, -3.2, 1.15, 2.4, 2.4, 2.2, '#3d475a') + winL(0.9, -3.2, 1.15, 2.4, 2.4, 2.2, 2, 2, '#ffb347');
  const base = P(2.1, -2.0, 3.35), mast = P(2.1, -2.0, 7.4), arm = P(-2.4, 0.6, 7.0);
  s += line(base, mast, '#f2b84b', 6) + line(mast, arm, '#f2b84b', 5) + line(arm, P(-2.4, 0.6, 4.4), '#9aa6bd', 2) + box(-2.8, 0.2, 3.9, 0.8, 0.8, 0.5, '#7a7f8a') + dot(mast, 6, '#ff5d5d');
  return wrap(s);
};
B.chips_factory = () => {                                // factory hall + saw roof + chimneys + chip emblem
  let s = plinth(T2) + box(-3.4, -3.0, 1.15, 6.8, 6.0, 2.6, '#323a50') + winL(-3.4, -3.0, 1.15, 6.8, 6.0, 2.6, 5, 2, T2) + winR(-3.4, -3.0, 1.15, 6.8, 6.0, 2.6, 4, 2, T2);
  for (let k = 0; k < 3; k++) { const x = -3.4 + k * 2.27, a = P(x, 3.0, 3.75), b = P(x + 2.27, 3.0, 3.75), c = P(x + 2.27, 3.0, 4.9); s += poly([a, b, c], '#4b5670', { stroke: '#1d2230' }) + line(b, c, T2, 2.2, true); }
  for (const [x, y] of [[-2.4, -2.2], [-0.6, -2.2]]) { s += cyl(x, y, 3.75, 0.45, 2.6, '#5a647a'); const t = P(x, y, 6.6); s += `<ellipse cx="${t[0]}" cy="${t[1] - 16}" rx="16" ry="10" fill="#c9b6ff" opacity=".35" filter="url(#glow)"/>`; }
  const e = P(2.2, 1.6, 3.8); s += `<rect x="${e[0] - 18}" y="${e[1] - 30}" width="36" height="36" rx="5" fill="#1b1430" stroke="${T2}" stroke-width="3" filter="url(#glowS)"/>`;
  return wrap(s);
};
B.nft_studio = () => {                                   // studio with big neon frame and art panels
  let s = plinth(T2) + box(-3.2, -3.2, 1.15, 6.4, 6.4, 3.4, '#2e2a44') + rim(-3.2, -3.2, 4.55, 6.4, 6.4, T2);
  const fr = [P(-2.6, 3.2, 1.6), P(2.6, 3.2, 1.6), P(2.6, 3.2, 4.1), P(-2.6, 3.2, 4.1)];
  s += poly(fr, grad([[0, '#ff4fd8'], [0.5, '#7b5cff'], [1, '#00e5ff']], 0, 0, 1, 1), { stroke: '#fff', sw: 2, glow: true, op: .9 });
  const pr = [P(3.2, -2.4, 1.8), P(3.2, 1.0, 1.8), P(3.2, 1.0, 3.9), P(3.2, -2.4, 3.9)];
  s += poly(pr, grad([[0, '#ffd84d'], [1, '#ff6b6b']], 0, 0, 1, 1), { stroke: '#fff', sw: 1.5, op: .85 });
  s += box(-1.2, -1.2, 4.55, 2.4, 2.4, 1.2, '#3b3558') + dot(P(0, 0, 6.2), 9, '#ff4fd8');
  return wrap(s);
};
B.ai_lab = () => {                                       // lab with glass dome brain + flasks
  let s = plinth(T2) + box(-3.2, -3.2, 1.15, 6.4, 6.4, 2.4, '#2c3550') + winL(-3.2, -3.2, 1.15, 6.4, 6.4, 2.4, 5, 2, '#d6b8ff') + winR(-3.2, -3.2, 1.15, 6.4, 6.4, 2.4, 5, 2, '#d6b8ff');
  const c = P(0, 0, 3.55); s += `<circle cx="${c[0]}" cy="${c[1] - 34}" r="30" fill="#b36bff" opacity=".35" filter="url(#glow)"/>` +
    `<path d="M${c[0] - 18},${c[1] - 34} q0,-22 18,-22 q18,0 18,22 q0,16 -18,18 q-18,-2 -18,-18z" fill="#e2c9ff" stroke="#b36bff" stroke-width="3" filter="url(#glowS)"/>`;
  s += dome(0, 0, 3.55, 2.6, '#c7a6ff', .45);
  for (const [x, y, col] of [[2.4, 2.4, '#4dff9b'], [-2.3, 2.5, '#ff4fd8']]) { const b = P(x, y, 3.55); s += `<path d="M${b[0] - 6},${b[1] - 34} v14 l-10,16 h32 l-10,-16 v-14z" fill="${col}" opacity=".85" stroke="#fff" stroke-width="1.5" filter="url(#glowS)"/>`; }
  return wrap(s);
};
B.logistics_hub = () => {                                // hangar + helipad + drone + containers
  let s = plinth(T2) + box(-3.4, -0.8, 1.15, 4.0, 4.2, 2.4, '#38425a');
  const a = P(-3.4, 3.4, 3.55), b = P(0.6, 3.4, 3.55), c = P(0.6, -0.8, 3.55), m1 = P(-1.4, 3.4, 4.9), m2 = P(-1.4, -0.8, 4.9);
  s += poly([a, b, m1], '#55607a') + poly([b, c, m2, m1], grad([[0, '#6b7690'], [1, '#3e4860']]));
  s += poly([P(-2.9, 3.4, 1.4), P(-0.1, 3.4, 1.4), P(-0.1, 3.4, 3.2), P(-2.9, 3.4, 3.2)], '#1a2030', { stroke: T2, sw: 2, glow: true });
  for (const [x, y, col] of [[1.4, 1.2, '#d9534f'], [1.4, 2.4, '#3a8fd9'], [2.6, 1.2, '#f0ad4e']]) s += box(x, y, 1.15, 1.1, 1.1, 0.9, col);
  s += box(1.0, -3.4, 1.15, 2.4, 2.4, 0.3, '#2b3242') + ring(2.2, -2.2, 1.5, 0.9, '#ffd84d', 2.5);
  const d = P(2.2, -2.2, 4.6); s += line([d[0] - 26, d[1]], [d[0] + 26, d[1]], '#9aa6bd', 3) + dot([d[0] - 26, d[1] - 3], 5, T2) + dot([d[0] + 26, d[1] - 3], 5, T2) + `<rect x="${d[0] - 9}" y="${d[1] - 6}" width="18" height="10" rx="3" fill="#cfd6e3"/>`;
  return wrap(s);
};
B.cyber_cafe = () => {                                   // cafe with awning, neon cup sign, tables
  let s = plinth(T2) + box(-3.0, -3.0, 1.15, 5.0, 5.4, 2.8, '#3a3048') + winL(-3.0, -3.0, 1.15, 5.0, 5.4, 2.8, 3, 1, '#ffcf8a', 1) + winR(-3.0, -3.0, 1.15, 5.0, 5.4, 2.8, 3, 1, '#ffcf8a', 1);
  const aw = [P(-3.0, 2.4, 3.4), P(2.0, 2.4, 3.4), P(2.0, 3.4, 2.9), P(-3.0, 3.4, 2.9)];
  s += poly(aw, grad([[0, '#ff4fd8'], [1, '#9b2fb5']], 0, 0, 1, 0), { stroke: '#fff', sw: 1 });
  const cup = P(-0.5, 0, 4.4); s += `<path d="M${cup[0] - 20},${cup[1] - 30} h34 v18 a14,12 0 0 1 -14,12 h-6 a14,12 0 0 1 -14,-12z M${cup[0] + 14},${cup[1] - 26} a8,8 0 0 1 0,14" fill="none" stroke="#ff4fd8" stroke-width="4" filter="url(#glow)"/>` +
    `<path d="M${cup[0] - 10},${cup[1] - 38} q6,-8 0,-16 M${cup[0] + 2},${cup[1] - 38} q6,-8 0,-16" fill="none" stroke="#ffcf8a" stroke-width="2.5" filter="url(#glowS)"/>`;
  for (const [x, y] of [[2.9, 0.4], [2.9, 2.6]]) s += cyl(x, y, 1.15, 0.45, 0.7, '#6d5a7d') + line(P(x, y, 1.85), P(x, y, 2.9), '#9aa6bd', 2) + `<ellipse cx="${P(x, y, 2.9)[0]}" cy="${P(x, y, 2.9)[1]}" rx="16" ry="7" fill="#ffcf8a" opacity=".9"/>`;
  return wrap(s);
};
B.repair_shop = () => {                                  // garage with roller door, wrench sign, tool rack
  let s = plinth(T2) + box(-3.2, -3.2, 1.15, 6.4, 6.0, 2.8, '#3a4156') + rim(-3.2, -3.2, 3.95, 6.4, 6.0, T2);
  const door = [P(-2.4, 2.8, 1.15), P(0.8, 2.8, 1.15), P(0.8, 2.8, 3.2), P(-2.4, 2.8, 3.2)]; s += poly(door, grad([[0, '#8792a8'], [1, '#4c566b']]), { stroke: '#2a3040', sw: 1.5 });
  for (let k = 1; k < 7; k++) { const z = 1.15 + k * 0.3; s += line(P(-2.4, 2.8, z), P(0.8, 2.8, z), '#3d4558', 1.2); }
  const w = P(2.0, 2.8, 4.6); s += `<g filter="url(#glow)"><g transform="translate(${w[0]},${w[1] - 18}) rotate(-35)"><rect x="-26" y="-5" width="40" height="10" rx="4" fill="${T2}"/><circle cx="20" cy="0" r="11" fill="none" stroke="${T2}" stroke-width="7"/></g></g>`;
  s += box(2.0, -2.6, 3.95, 1.4, 1.4, 1.2, '#4a536a') + dot(P(2.7, -1.9, 5.3), 5, '#ffd84d');
  return wrap(s);
};
B.vr_club = () => {                                      // club with giant VR headset on the roof
  let s = plinth(T2) + box(-3.2, -3.2, 1.15, 6.4, 6.4, 3.0, '#2a2442') + winL(-3.2, -3.2, 1.15, 6.4, 6.4, 3.0, 6, 1, '#ff4fd8', .8) + winR(-3.2, -3.2, 1.15, 6.4, 6.4, 3.0, 6, 1, '#00e5ff', .8);
  const h = P(0, 0, 4.15); s += `<rect x="${h[0] - 70}" y="${h[1] - 70}" width="140" height="58" rx="26" fill="${grad([[0, '#3d3566'], [1, '#1c1733']])}" stroke="${T2}" stroke-width="4" filter="url(#glowS)"/>` +
    `<rect x="${h[0] - 58}" y="${h[1] - 60}" width="116" height="34" rx="16" fill="${grad([[0, '#ff4fd8'], [0.5, '#7b5cff'], [1, '#00e5ff']], 0, 0, 1, 0)}" filter="url(#glow)" opacity=".9"/>` +
    `<path d="M${h[0] - 70},${h[1] - 44} q-24,4 -26,30 M${h[0] + 70},${h[1] - 44} q24,4 26,30" fill="none" stroke="#4b4380" stroke-width="7"/>`;
  return wrap(s);
};
B.validator = () => {                                    // monolith node + shield + pylons
  let s = plinth(T3) + box(-1.4, -1.4, 1.15, 2.8, 2.8, 5.6, '#232a3c') + rim(-1.4, -1.4, 6.75, 2.8, 2.8, T3);
  s += line(P(-1.4, 1.4, 1.6), P(-1.4, 1.4, 6.4), T3, 3, true) + line(P(1.4, -1.4, 1.6), P(1.4, -1.4, 6.4), T3, 3, true) + line(P(1.4, 1.4, 1.6), P(1.4, 1.4, 6.4), '#ffe9a3', 2, true);
  const sh = P(0, 1.4, 4.4); s += `<path d="M${sh[0]},${sh[1] - 50} l26,10 v20 q0,26 -26,38 q-26,-12 -26,-38 v-20z" fill="${grad([[0, '#ffe58a'], [1, '#c9971f']])}" stroke="#fff3c4" stroke-width="2" filter="url(#glowS)"/>` +
    `<path d="M${sh[0] - 11},${sh[1] - 22} l8,8 l15,-17" fill="none" stroke="#5a3d00" stroke-width="5" stroke-linecap="round"/>`;
  for (const [x, y] of [[-3.2, -3.2], [3.0, -3.2], [-3.2, 3.0], [3.0, 3.0]]) s += box(x, y, 1.15, 0.5, 0.5, 2.0, '#3a4458') + dot(P(x + .25, y + .25, 3.3), 5, T3);
  return wrap(s);
};
B.dex = () => {                                          // exchange tower with chart screens + ticker
  let s = plinth(T3) + box(-2.6, -2.6, 1.15, 5.2, 5.2, 4.6, '#26304a') + rim(-2.6, -2.6, 5.75, 5.2, 5.2, T3);
  const sc = [P(-2.2, 2.6, 2.0), P(2.2, 2.6, 2.0), P(2.2, 2.6, 5.2), P(-2.2, 2.6, 5.2)]; s += poly(sc, '#08121f', { stroke: '#2d6a8f', sw: 1.5 });
  const chart = [[-1.9, 2.6], [-1.0, 3.3], [-0.3, 2.9], [0.6, 4.2], [1.3, 3.8], [1.9, 4.9]].map(([x, z]) => P(x, 2.6, z));
  s += `<polyline points="${pts(chart)}" fill="none" stroke="#4dff9b" stroke-width="3.5" filter="url(#glow)"/>`;
  for (let k = 0; k < 5; k++) { const x = -2.2 + k * 1.0, h = [1.2, 2.0, 1.4, 2.6, 1.8][k]; s += poly([P(2.6, x, 2.0), P(2.6, x + 0.6, 2.0), P(2.6, x + 0.6, 2.0 + h), P(2.6, x, 2.0 + h)], k % 2 ? '#ff5d7a' : '#4dff9b', { op: .85 }); }
  s += box(-1.0, -1.0, 5.75, 2.0, 2.0, 1.4, '#323d5a') + dot(P(0, 0, 7.4), 8, T3);
  return wrap(s);
};
B.casino = () => {                                       // casino with neon marquee, dice and coins
  let s = plinth(T3) + box(-3.2, -3.0, 1.15, 6.4, 6.0, 3.2, '#3a1f3f') + winR(-3.2, -3.0, 1.15, 6.4, 6.0, 3.2, 5, 2, '#ffd84d', .9);
  const m = [P(-3.0, 3.0, 3.0), P(3.0, 3.0, 3.0), P(3.0, 3.0, 5.4), P(-3.0, 3.0, 5.4)]; s += poly(m, grad([[0, '#ff2d75'], [1, '#7a0d39']]), { stroke: T3, sw: 3, glow: true });
  for (let k = 0; k < 9; k++) s += dot(P(-2.8 + k * 0.7, 3.0, 5.25), 3.5, k % 2 ? '#fff6c2' : T3);
  // "777" laid on the marquee plane (front-left face: x axis -> (cos30, sin30) on screen)
  const c = P(0, 3.0, 3.95); s += `<g filter="url(#glowS)"><g transform="matrix(0.866,0.5,0,1,${c[0]},${c[1]})"><text x="0" y="12" font-family="DejaVu Sans,Arial" font-weight="900" font-size="38" text-anchor="middle" fill="#FFD84D">777</text></g></g>`;
  s += box(-0.9, -0.9, 4.35, 1.8, 1.8, 1.8, '#f4f4f4', { stroke: '#999' });
  for (const [dx, dy] of [[-16, -6], [0, -2], [16, 2]]) { const t = P(0, 0, 6.15); s += dot([t[0] + dx, t[1] + dy], 3.5, '#222', false); }
  return wrap(s);
};
B.arena = () => {                                        // oval stadium with lights
  let s = plinth(T3);
  const c = P(0, 0, 1.15), rx = 150, ry = 76;
  s += `<path d="M${c[0] - rx},${c[1]} v-60 a${rx},${ry} 0 0 1 ${2 * rx},0 v60 a${rx},${ry} 0 0 1 ${-2 * rx},0z" fill="${grad([[0, '#4a5470'], [1, '#262d40']], 0, 0, 1, 0)}" stroke="#1a1f2c" stroke-width="2"/>`;
  s += `<ellipse cx="${c[0]}" cy="${c[1] - 60}" rx="${rx}" ry="${ry}" fill="#2f3850" stroke="${T3}" stroke-width="3" filter="url(#glowS)"/>`;
  s += `<ellipse cx="${c[0]}" cy="${c[1] - 52}" rx="${rx * .62}" ry="${ry * .58}" fill="${grad([[0, '#3fbf6a'], [1, '#1e7a40']])}"/>`;
  s += `<line x1="${c[0]}" y1="${c[1] - 52 - ry * .58}" x2="${c[0]}" y2="${c[1] - 52 + ry * .58}" stroke="#d9ffe5" stroke-width="2" opacity=".7"/><ellipse cx="${c[0]}" cy="${c[1] - 52}" rx="16" ry="8" fill="none" stroke="#d9ffe5" stroke-width="2" opacity=".7"/>`;
  for (let k = 0; k < 14; k++) { const a = k / 14 * 2 * Math.PI; s += line([c[0] + Math.cos(a) * rx, c[1] - 60 + Math.sin(a) * ry], [c[0] + Math.cos(a) * rx * .82, c[1] - 60 + Math.sin(a) * ry * .82], '#59647e', 2); }
  for (const [dx, dy] of [[-rx, -60], [rx, -60], [0, -60 - ry], [0, -60 + ry]]) { const p = [c[0] + dx, c[1] + dy]; s += line(p, [p[0], p[1] - 55], '#9aa6bd', 3) + dot([p[0], p[1] - 58], 7, '#fff3c4'); }
  return wrap(s);
};
B.incubator = () => {                                    // greenhouse with glowing egg pods
  let s = plinth(T3) + box(-3.2, -3.2, 1.15, 6.4, 6.4, 0.9, '#3a4458') + rim(-3.2, -3.2, 2.05, 6.4, 6.4, T3);
  for (const [x, y, r, col] of [[-1.5, 1.4, 1.1, '#ffe58a'], [1.2, 1.6, 0.95, '#7dffb5'], [1.4, -1.4, 1.2, '#ffcf8a'], [-1.4, -1.5, 0.9, '#c9a6ff']]) {
    const b = P(x, y, 2.05), rx = r * 30;
    s += `<ellipse cx="${b[0]}" cy="${b[1] - rx * 1.05}" rx="${rx}" ry="${rx * 1.25}" fill="${col}" opacity=".55" filter="url(#glow)"/>` +
      `<ellipse cx="${b[0]}" cy="${b[1] - rx * 1.05}" rx="${rx * .82}" ry="${rx * 1.08}" fill="${grad([[0, '#ffffff'], [0.4, col], [1, shade(col, -0.45)]], 0.3, 0, 0.7, 1)}" stroke="#fff" stroke-width="1.5"/>` +
      `<ellipse cx="${b[0]}" cy="${b[1]}" rx="${rx * .9}" ry="${rx * .38}" fill="#2a3242" stroke="${T3}" stroke-width="1.5"/>`;
  }
  return wrap(s);
};
B.bridge = () => {                                       // cable-stayed bridge: deck, two pylons, fan cables
  let s = plinth(T3);
  s += box(-4.1, -1.1, 1.15, 8.2, 2.2, 0.7, '#4a5470') + line(P(-4.1, 1.1, 1.85), P(4.1, 1.1, 1.85), T3, 3, true) + line(P(4.1, -1.1, 1.85), P(4.1, 1.1, 1.85), T3, 2, true);
  for (const k of [-3.2, -1.6, 0, 1.6, 3.2]) s += dot(P(k, 1.1, 2.05), 3.5, '#fff3c4');
  for (const x of [-2.2, 2.2]) {
    s += box(x - 0.4, -0.4, 1.85, 0.8, 0.8, 5.6, '#3a4560') + rim(x - 0.4, -0.4, 7.45, 0.8, 0.8, T3, 1.6) + dot(P(x, 0, 7.7), 6, T3);
    const top = P(x, 0.4, 7.2);
    for (const dx of [-1.8, -1.2, -0.6, 0.6, 1.2, 1.8]) s += line(top, P(x + dx, 1.1, 1.85), '#e6cf7a', 1.6);
  }
  return wrap(s);
};
