/**
 * CitySpritesPanel — fine-tune how each building sprite sits on its lot on the city map.
 * Auto-fit comes from /sprites/city/manifest.json (anchor, footprint_width, top); here the admin
 * adds scale and shift per business type and growth stage (backend/city_sprites.py).
 * The preview uses exactly the same placement math as the map. Park pictures (1x1 / 2x2 squares) are edited here
 * too: size, replace, add new ones. «На карте» shows the sprite in its real place on the city map.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import axios from 'axios';
import { toast } from 'sonner';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Building2, RotateCcw, Trees, Plus } from 'lucide-react';
import SpriteMapPreview from '@/components/admin/SpriteMapPreview';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const SPR = '/sprites/city/';
const FOOT = { '1x1': [1, 1], '1x2': [1, 2], '2x2': [2, 2], '3x3': [3, 3] };
const TW = 64;                                           // preview tile half-width (px)

function spriteBox(meta, fm, tune, lot, displayScale, origin) {
  const [w, h] = lot;                                    // lot size in tiles (x, y)
  const iso = (gx, gy) => [origin[0] + (gx - gy) * TW, origin[1] + (gx + gy) * TW / 2];
  const [cx, cy] = iso(w / 2, h / 2);
  const slotW = (w + h) * TW;
  const size = fm.size || [320, 400];
  const base = slotW * displayScale / fm.footprint_width * (tune.scale || 1);
  const dw = base * (tune.sx || 1), dh = base * size[1] / size[0] * (tune.sy || 1);   // width / height on their own
  const lotLong = w === h ? null : (h > w ? 'y' : 'x');
  const mirror = !!(fm.long_axis && lotLong && fm.long_axis !== lotLong);
  const ox = (tune.dx || 0) * slotW, oy = (tune.dy || 0) * slotW;
  return { x: cx - dw * fm.anchor[0] + ox, y: cy - dh * fm.anchor[1] + oy, dw, dh, cx: cx + ox, mirror, iso };
}

const DISTRICTS = [[1, 'Central Core', 121], [2, 'North Hub', 119], [3, 'West District', 119], [4, 'East District', 119]];

/** Districts of the new map: open / closed and how many lots of each are on sale. */
export function DistrictsCard({ token }) {
  const [cfg, setCfg] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { axios.get(`${BACKEND_URL}/api/city/districts`).then((r) => setCfg(r.data)).catch(() => {}); }, []);
  // which businesses the open lots of a district are, and how many of them are still free
  const [lots, setLots] = useState(null);
  useEffect(() => {
    axios.get(`${BACKEND_URL}/api/admin/city/districts/lots`, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => setLots(r.data)).catch(() => {});
  }, [token]);
  const breakdown = (d, n) => {
    const list = ((lots?.districts || {})[String(d)] || []).slice(0, n);
    const by = {};
    list.forEach((l) => { const x = (by[l.type] = by[l.type] || { n: 0, free: 0 }); x.n += 1; if (!l.owned) x.free += 1; });
    const rows = Object.entries(by).sort((a, b) => ((lots.types[b[0]]?.tier || 1) - (lots.types[a[0]]?.tier || 1)) || b[1].n - a[1].n);
    return { rows, free: list.filter((l) => !l.owned).length, sold: list.filter((l) => l.owned).length };
  };
  if (!cfg) return null;
  const save = async () => {
    setBusy(true);
    try {
      const r = await axios.put(`${BACKEND_URL}/api/admin/city/districts`, cfg, { headers: { Authorization: `Bearer ${token}` } });
      setCfg(r.data); toast.success('Районы сохранены');
    } catch (e) { toast.error(e?.response?.data?.detail || 'Ошибка'); } finally { setBusy(false); }
  };
  return (
    <Card className="glass-panel border-white/10" data-testid="city-districts-card">
      <CardHeader className="pb-2"><CardTitle className="text-sm">Районы карты</CardTitle></CardHeader>
      <CardContent className="space-y-2">
        <div className="text-[11px] text-text-muted">Закрытый район затемнён на карте, купить в нём нельзя. «Мест в продаже» — сколько участков района доступно (сначала крупные).</div>
        {DISTRICTS.map(([d, name, total]) => (
          <div key={d} className="flex flex-wrap items-center gap-3 rounded-lg border border-white/10 px-3 py-2">
            <span className="flex-1 min-w-[140px] text-sm text-white">Район {d} · {name}</span>
            <label className="flex items-center gap-2 text-xs text-text-muted">
              <input type="checkbox" checked={cfg.unlocked[String(d)] !== false} data-testid={`district-open-${d}`}
                onChange={(e) => setCfg((c) => ({ ...c, unlocked: { ...c.unlocked, [String(d)]: e.target.checked } }))} /> открыт
            </label>
            <label className="flex items-center gap-2 text-xs text-text-muted">
              мест в продаже
              <input type="number" min={0} max={total} value={cfg.open_count[String(d)] ?? total}
                onChange={(e) => setCfg((c) => ({ ...c, open_count: { ...c.open_count, [String(d)]: Math.max(0, Math.min(total, Number(e.target.value) || 0)) } }))}
                className="w-20 rounded bg-black/40 border border-white/10 px-2 py-1 text-white" /> / {total}
            </label>
            {lots && (() => {
              const n = cfg.open_count[String(d)] ?? total;
              const b = breakdown(d, n);
              return (
                <div className="basis-full text-[11px] text-text-muted" data-testid={`district-breakdown-${d}`}>
                  {n === 0 ? 'Ничего не выставлено.' : (
                    <>
                      <span className="text-white/80">В продаже {n}: свободно <b className="text-emerald-300">{b.free}</b>{b.sold ? <>, уже куплено <b className="text-white/70">{b.sold}</b></> : null}.</span>{' '}
                      {b.rows.map(([k, v]) => (
                        <span key={k} className="inline-block mr-2 whitespace-nowrap">{lots.types[k]?.icon} {lots.types[k]?.name} ×{v.n}{v.free !== v.n ? ` (своб. ${v.free})` : ''}</span>
                      ))}
                    </>
                  )}
                </div>
              );
            })()}
          </div>
        ))}
        <Button size="sm" disabled={busy} onClick={save} data-testid="districts-save">Сохранить районы</Button>
      </CardContent>
    </Card>
  );
}

const STAGE_LVL = { 1: 0, 2: 4, 3: 7 };                 // the first level of each growth stage
const absB = (u) => (u && u.startsWith('/api/') ? `${BACKEND_URL}${u}` : u);

/** group = 'standard' → the buildings of the city map; any other group (Crazy, …) → that group's skins,
 *  edited the same way: business list, preview on the lot and on the map, sliders, upload per stage. */
export default function CitySpritesPanel({ token, group = 'standard', groupName = '' }) {
  const isGroup = group !== 'standard';
  const [gskins, setGskins] = useState({});             // group mode: {type: {stage: skin doc}}
  const [manifest, setManifest] = useState(null);
  const [parkManifest, setParkManifest] = useState({ parks: {} });
  const [tuning, setTuning] = useState({});
  const [overrides, setOverrides] = useState({ overrides: {}, overrides_alt: {} });   // sprites replaced by the admin
  const [parks, setParks] = useState({ park_tuning: {}, park_overrides: {}, park_extra: {} });
  const fileRef = useRef(null);
  const [type, setType] = useState('helios');
  const [park, setPark] = useState(null);                // id of the park picture being edited (null = a building)
  const [stage, setStage] = useState('1');
  const [vals, setVals] = useState({ scale: 1, sx: 1, sy: 1, dx: 0, dy: 0 });
  const [flip, setFlip] = useState(false);              // 1x2 lots: show the other orientation (2x1)
  const [busy, setBusy] = useState(false);
  const cv = useRef(null);
  const imgs = useRef({});
  const headers = { headers: { Authorization: `Bearer ${token}` } };

  const applyData = (d) => {
    setTuning(d.tuning || {});
    setOverrides({ overrides: d.overrides || {}, overrides_alt: d.overrides_alt || {} });
    setParks({ park_tuning: d.park_tuning || {}, park_overrides: d.park_overrides || {}, park_extra: d.park_extra || {} });
  };
  const load = useCallback(async () => {
    try {
      const [m, t, pm] = await Promise.all([fetch(SPR + 'manifest.json').then(r => r.json()), axios.get(`${BACKEND_URL}/api/city-sprites/tuning`),
        fetch(SPR + 'parks/manifest.json').then((r) => (r.ok ? r.json() : { parks: {} })).catch(() => ({ parks: {} }))]);
      setManifest(m); setParkManifest(pm || { parks: {} }); applyData(t.data);
    } catch (e) { toast.error('Не удалось загрузить спрайты'); }
  }, []);
  useEffect(() => { load(); }, [load]);
  const loadGroup = useCallback(async () => {
    if (!isGroup) return;
    try {
      const r = await axios.get(`${BACKEND_URL}/api/admin/skins`, { headers: { Authorization: `Bearer ${token}` }, params: { group_key: group } });
      const m = {};
      (r.data.skins || []).forEach((sk) => {
        Object.entries(STAGE_LVL).forEach(([st, lvl]) => {
          if (Number(sk.level) === lvl) (m[sk.business_type] = m[sk.business_type] || {})[st] = sk;
        });
      });
      setGskins(m);
    } catch (e) { setGskins({}); }
  }, [isGroup, group, token]);
  useEffect(() => { loadGroup(); }, [loadGroup]);
  const gSkin = isGroup ? ((gskins[type] || {})[stage] || null) : null;

  // park pictures: built-in (parks/manifest.json, maybe replaced) + added by the admin
  const parkList = (() => {
    const out = [];
    ['1x1', '2x2'].forEach((sz) => {
      ((parkManifest.parks || {})[sz] || []).forEach((fm) => {
        const id = fm.file.replace(/\.webp$/, ''), ov = parks.park_overrides[id];
        out.push({ id, size: sz, fm: ov || fm, src: ov ? `${BACKEND_URL}${ov.url}` : `${SPR}parks/${fm.file}`, replaced: !!ov, extra: false });
      });
      Object.entries(parks.park_extra).filter(([, e]) => e.size_key === sz).sort((a, b) => a[0].localeCompare(b[0]))
        .forEach(([id, e]) => out.push({ id, size: sz, fm: e, src: `${BACKEND_URL}${e.url}`, replaced: false, extra: true }));
    });
    return out;
  })();
  const PARK_NAMES = { trees: 'Деревья', fountain: 'Фонтан', sakura: 'Сакура', pond: 'Пруд', playground: 'Детская площадка', monument: 'Монумент' };
  const parkName = (id) => { const k = id.replace(/^park[12]_/, ''); return PARK_NAMES[k] || (k.startsWith('custom_') ? 'Свой парк' : k); };
  const curPark = park ? parkList.find((p) => p.id === park) : null;

  useEffect(() => {
    if (park) setVals({ scale: 1, sx: 1, sy: 1, dx: 0, dy: 0, ...(parks.park_tuning[park] || {}) });
    else if (isGroup) setVals({ scale: 1, sx: 1, sy: 1, dx: 0, dy: 0, ...(((gskins[type] || {})[stage] || {}).tune || {}) });
    else setVals({ scale: 1, sx: 1, sy: 1, dx: 0, dy: 0, ...(((tuning[type] || {})[stage]) || {}) });
  }, [type, stage, tuning, park, parks, isGroup, gskins]);

  const getImg = (src) => new Promise((res) => {
    if (imgs.current[src]) return res(imgs.current[src]);
    const im = new Image(); im.onload = () => { imgs.current[src] = im; res(im); }; im.onerror = () => res(null); im.src = src;
  });

  // draw the preview: the lot grid + the sprite + a 1x1 reference building next to it
  useEffect(() => {
    if (!manifest || !cv.current) return;
    const meta = manifest.types[type]; if (!meta && !park) return;
    let lot, fm, src, ds;
    if (park) {
      if (!curPark) return;
      const n = curPark.size === '2x2' ? 2 : 1;
      lot = [n, n]; fm = { ...curPark.fm, footprint_width: curPark.fm.footprint_width || 0.94 }; src = curPark.src; ds = 1;
    } else {
      lot = FOOT[meta.footprint] || [1, 1]; if (meta.footprint === '1x2' && flip) lot = [2, 1];
      // the view whose long axis matches the lot (1x2 buildings have a second view, files_alt)
      fm = (meta.files_meta || {})[stage] || meta; let file = `${type}/stage${stage}.webp`;
      const lotLong = lot[0] === lot[1] ? null : (lot[1] > lot[0] ? 'y' : 'x');
      const alt = (meta.files_alt || {})[stage];
      src = `${SPR}${type}/stage${stage}.webp`;
      const ov = ((overrides.overrides || {})[type] || {})[stage];
      if (ov) { fm = ov; src = `${BACKEND_URL}${ov.url}`; }
      if (lotLong && fm.long_axis && fm.long_axis !== lotLong) {
        const ova = ((overrides.overrides_alt || {})[type] || {})[stage];
        if (ova) { fm = ova; src = `${BACKEND_URL}${ova.url}`; } else if (alt && !ov) { fm = alt; file = alt.file; src = `${SPR}${file}`; }
      }
      ds = (manifest.display_scale || {})[meta.footprint] || 1;
      if (isGroup) {                                     // the group's picture (processed like a building)
        lot = FOOT[meta.footprint] || [1, 1];
        if (gSkin && gSkin.image) { fm = { ...(gSkin.meta || {}), footprint_width: (gSkin.meta || {}).footprint_width || 0.9, anchor: (gSkin.meta || {}).anchor || [0.5, 0.75] }; src = absB(gSkin.image); }
        else src = null;
      }
    }
    const c = cv.current;
    // crisp on high-DPI screens: the canvas has as many pixels as the screen shows
    const dpr = Math.min(window.devicePixelRatio || 1, 3), cssW = c.clientWidth || 720, cssH = Math.round(cssW * 460 / 720);
    if (c.width !== Math.round(cssW * dpr)) { c.width = Math.round(cssW * dpr); c.height = Math.round(cssH * dpr); }
    const g = c.getContext('2d'); g.setTransform(dpr * cssW / 720, 0, 0, dpr * cssW / 720, 0, 0);
    g.imageSmoothingEnabled = true; g.imageSmoothingQuality = 'high';
    const W = 720, H = 460;
    (async () => {
      const im = src ? await getImg(src) : null;
      const refMeta = manifest.types.helios, refFm = (refMeta.files_meta || {})['1'] || refMeta;
      const ref = await getImg(`${SPR}helios/stage1.webp`);
      g.clearRect(0, 0, W, H); g.fillStyle = '#0b1220'; g.fillRect(0, 0, W, H);
      const origin = [W / 2 - 30, H * 0.52 - (lot[0] + lot[1]) * TW / 4];
      const box = spriteBox(meta || {}, fm, vals, lot, ds, origin);
      // ground tiles around + the lot
      for (let gx = -2; gx < lot[0] + 3; gx++) for (let gy = -2; gy < lot[1] + 2; gy++) {
        const p = [box.iso(gx, gy), box.iso(gx + 1, gy), box.iso(gx + 1, gy + 1), box.iso(gx, gy + 1)];
        const inLot = gx >= 0 && gy >= 0 && gx < lot[0] && gy < lot[1];
        g.beginPath(); p.forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y))); g.closePath();
        g.fillStyle = inLot ? '#3f4b6a' : '#1d2336'; g.fill(); g.strokeStyle = inLot ? 'rgba(57,255,136,0.55)' : 'rgba(255,255,255,0.06)'; g.lineWidth = 1; g.stroke();
      }
      const lp = [box.iso(0, 0), box.iso(lot[0], 0), box.iso(lot[0], lot[1]), box.iso(0, lot[1])];
      g.beginPath(); lp.forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y))); g.closePath(); g.strokeStyle = '#39ff88'; g.lineWidth = 2.5; g.stroke();
      // 1x1 reference building on the tile to the right of the lot
      if (ref) {
        const rb = spriteBox(refMeta, refFm, ((tuning.helios || {})['1']) || {}, [1, 1], (manifest.display_scale || {})['1x1'] || 1,
          box.iso(lot[0] + 1, -1));
        g.globalAlpha = 0.9; g.drawImage(ref, rb.x, rb.y, rb.dw, rb.dh); g.globalAlpha = 1;
      }
      if (im) {
        g.save(); if (box.mirror && !isGroup) { g.translate(box.cx, 0); g.scale(-1, 1); g.translate(-box.cx, 0); }
        g.drawImage(im, box.x, box.y, box.dw, box.dh); g.restore();
      } else if (isGroup) {
        g.fillStyle = 'rgba(255,255,255,0.75)'; g.font = '600 18px sans-serif'; g.textAlign = 'center';
        g.fillText(`Нет картинки для стадии ${stage} — загрузите её ниже`, W / 2, 40);
      }
    })();
  }, [manifest, type, stage, vals, flip, tuning, overrides, park, curPark && curPark.src, isGroup, gSkin && gSkin.image]); // eslint-disable-line react-hooks/exhaustive-deps
  const previewSkin = useMemo(() => (isGroup && gSkin && gSkin.image ? { url: absB(gSkin.image), meta: gSkin.meta || {} } : null),
    [isGroup, gSkin && gSkin.image]); // eslint-disable-line react-hooks/exhaustive-deps

  const spriteData = useMemo(() => ({ tuning, ...overrides, ...parks }), [tuning, overrides, parks]);

  const save = async (allStages) => {
    setBusy(true);
    try {
      if (isGroup) {
        await axios.put(`${BACKEND_URL}/api/admin/skins/tune`, { group_key: group, business_type: type, stage: allStages ? 'all' : stage, ...vals }, headers);
        await loadGroup(); toast.success(allStages ? 'Сохранено для всех стадий' : 'Сохранено');
      } else if (park) {
        const r = await axios.put(`${BACKEND_URL}/api/admin/city-sprites/park-tuning`, { id: park, ...vals }, headers);
        setParks((x) => ({ ...x, ...r.data })); toast.success('Сохранено');
      } else {
        const r = await axios.put(`${BACKEND_URL}/api/admin/city-sprites/tuning`, { type, stage: allStages ? 'all' : stage, ...vals }, headers);
        setTuning(r.data.tuning || {}); toast.success(allStages ? 'Сохранено для всех стадий' : 'Сохранено');
      }
    } catch (e) { toast.error(e?.response?.data?.detail || 'Ошибка сохранения'); }
    finally { setBusy(false); }
  };
  const upload = async (file, allStages) => {
    if (!file) return;
    setBusy(true);
    try {
      const fd = new FormData();
      const mode = fileRef.current?.dataset.mode || '';
      if (isGroup) {
        fd.append('group_key', group); fd.append('group_name', groupName || ''); fd.append('business_type', type);
        fd.append('stage', allStages ? 'all' : stage); fd.append('file', file);
        await axios.post(`${BACKEND_URL}/api/admin/skins/upload`, fd, headers);
        await loadGroup(); toast.success('Картинка загружена — она уже на карте у игроков с этим скином');
      } else if (mode.startsWith('newpark:')) {
        fd.append('size', mode.slice(8)); fd.append('file', file);
        const r = await axios.post(`${BACKEND_URL}/api/admin/city-sprites/park-upload`, fd, headers);
        setParks({ park_tuning: r.data.park_tuning || {}, park_overrides: r.data.park_overrides || {}, park_extra: r.data.park_extra || {} });
        setPark(r.data.id); toast.success('Парк добавлен — он уже на карте');
      } else if (park) {
        fd.append('id', park); fd.append('file', file);
        const r = await axios.post(`${BACKEND_URL}/api/admin/city-sprites/park-upload`, fd, headers);
        setParks({ park_tuning: r.data.park_tuning || {}, park_overrides: r.data.park_overrides || {}, park_extra: r.data.park_extra || {} });
        toast.success('Картинка парка заменена — она уже на карте');
      } else {
        const meta = manifest.types[type];
        fd.append('type', type); fd.append('stage', allStages ? 'all' : stage);
        fd.append('view', meta.footprint === '1x2' && flip ? 'alt' : 'main'); fd.append('file', file);
        const r = await axios.post(`${BACKEND_URL}/api/admin/city-sprites/upload`, fd, headers);
        setOverrides({ overrides: r.data.overrides || {}, overrides_alt: r.data.overrides_alt || {} });
        toast.success('Спрайт заменён — он уже на карте');
      }
    } catch (e) { toast.error(e?.response?.data?.detail || 'Не удалось загрузить'); }
    finally { setBusy(false); if (fileRef.current) { fileRef.current.value = ''; fileRef.current.dataset.mode = ''; } }
  };
  const pickFile = (all, mode = '') => { fileRef.current.dataset.all = all ? '1' : '0'; fileRef.current.dataset.mode = mode; fileRef.current.click(); };
  const resetSprite = async () => {
    setBusy(true);
    try {
      if (isGroup) {
        await axios.delete(`${BACKEND_URL}/api/admin/skins/stage/${group}/${type}/${stage}`, headers);
        await loadGroup(); toast.success('Картинка стадии удалена');
      } else if (park) {
        const was = curPark;
        const r = await axios.delete(`${BACKEND_URL}/api/admin/city-sprites/park/${park}`, headers);
        setParks({ park_tuning: r.data.park_tuning || {}, park_overrides: r.data.park_overrides || {}, park_extra: r.data.park_extra || {} });
        if (was && was.extra) setPark(null);
        toast.success(was && was.extra ? 'Парк удалён' : 'Стандартная картинка возвращена');
      } else {
        const meta = manifest.types[type];
        const r = await axios.delete(`${BACKEND_URL}/api/admin/city-sprites/override/${type}/${stage}`, { ...headers, params: { view: meta.footprint === '1x2' && flip ? 'alt' : 'main' } });
        setOverrides({ overrides: r.data.overrides || {}, overrides_alt: r.data.overrides_alt || {} });
        toast.success('Стандартный спрайт возвращён');
      }
    } catch (e) { toast.error('Ошибка'); } finally { setBusy(false); }
  };
  const reset = async () => {
    setBusy(true);
    try {
      if (isGroup) {
        await axios.delete(`${BACKEND_URL}/api/admin/skins/tune/${group}/${type}/${stage}`, headers);
        await loadGroup();
      } else if (park) {
        const r = await axios.delete(`${BACKEND_URL}/api/admin/city-sprites/park-tuning/${park}`, headers);
        setParks((x) => ({ ...x, ...r.data }));
      } else {
        const r = await axios.delete(`${BACKEND_URL}/api/admin/city-sprites/tuning/${type}/${stage}`, headers);
        setTuning(r.data.tuning || {});
      }
      toast.success('Сброшено к автоподгонке');
    } catch (e) { toast.error('Ошибка'); } finally { setBusy(false); }
  };

  if (!manifest) return <div className="text-sm text-text-muted">Загрузка…</div>;
  const types = Object.entries(manifest.types).sort((a, b) => a[1].tier - b[1].tier || a[1].footprint.localeCompare(b[1].footprint));
  const meta = manifest.types[type];
  const tuned = (t) => (isGroup ? Object.values(gskins[t] || {}).some((x) => x && x.tune) : Object.keys(tuning[t] || {}).length > 0);
  const thumbOf = (k) => (isGroup ? absB((((gskins[k] || {})['1']) || ((gskins[k] || {})['2']) || ((gskins[k] || {})['3']) || {}).image) : `${SPR}${k}/stage1.webp`);
  // a slider + «−1» / «+1» buttons: one step = 1 % (values are fractions, 0.01 = 1 %)
  const bump = (key, d, min, max) => setVals((v) => ({ ...v, [key]: Math.round(Math.min(max, Math.max(min, (Number(v[key]) || 0) + d)) * 1000) / 1000 }));
  const slider = (key, label, min, max, step, fmt) => (
    <div className="block text-xs space-y-1">
      <span className="flex justify-between text-text-muted"><span>{label}</span><b className="text-white">{fmt(vals[key])}</b></span>
      <div className="flex items-center gap-2">
        <button type="button" onClick={() => bump(key, -0.01, min, max)} aria-label={`${label}: −1%`} data-testid={`cs-${key}-minus`}
          className="shrink-0 w-8 h-8 rounded-lg border border-white/15 bg-white/5 text-white font-bold leading-none hover:bg-white/10 active:scale-95">−</button>
        <input type="range" min={min} max={max} step={step} value={vals[key]} className="w-full accent-cyan-400" aria-label={label}
          onChange={(e) => setVals((v) => ({ ...v, [key]: Number(e.target.value) }))} data-testid={`cs-${key}`} />
        <button type="button" onClick={() => bump(key, 0.01, min, max)} aria-label={`${label}: +1%`} data-testid={`cs-${key}-plus`}
          className="shrink-0 w-8 h-8 rounded-lg border border-white/15 bg-white/5 text-white font-bold leading-none hover:bg-white/10 active:scale-95">+</button>
      </div>
    </div>
  );
  const replacedHere = isGroup ? !!gSkin : park ? (curPark && (curPark.replaced || curPark.extra))
    : (((overrides[(meta.footprint === '1x2' && flip) ? 'overrides_alt' : 'overrides'] || {})[type] || {})[stage]);

  return (
    <div className="space-y-4" data-testid="city-sprites-panel">
      <div className="flex items-center gap-2"><Building2 className="w-5 h-5 text-cyan-300" /><span className="font-bold text-white">{isGroup ? `Скины группы «${groupName || group}» на карте` : 'Спрайты зданий и парков на карте'}</span></div>
      <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" className="hidden" data-testid="cs-file"
        onChange={(e) => upload(e.target.files?.[0], fileRef.current?.dataset.all === '1')} />
      <div className="grid lg:grid-cols-[260px_1fr] gap-4">
        <Card className="glass-panel border-white/10">
          <CardHeader className="pb-2"><CardTitle className="text-sm">Бизнес</CardTitle></CardHeader>
          <CardContent className="space-y-1 max-h-[760px] overflow-y-auto">
            {types.map(([k, t]) => (
              <button key={k} type="button" onClick={() => { setPark(null); setType(k); }} data-testid={`cs-type-${k}`}
                className={`w-full flex items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs border ${!park && type === k ? 'border-cyan-400/60 bg-cyan-400/10' : 'border-transparent hover:bg-white/5'}`}>
                {thumbOf(k) ? <img src={thumbOf(k)} alt="" className="w-9 h-9 object-contain" /> : <span className="w-9 h-9 flex items-center justify-center text-text-muted">—</span>}
                <span className="flex-1 text-white">{t.name_ru}<span className="block text-[10px] text-text-muted">тир {t.tier} · {t.footprint}{isGroup ? ` · ${Object.keys(gskins[k] || {}).length}/3 стадий` : ''}</span></span>
                {tuned(k) && <span className="text-[10px] text-yellow-300">изм.</span>}
              </button>
            ))}
            {!isGroup && (<>
            <div className="pt-3 pb-1 flex items-center gap-1.5 text-xs font-bold text-emerald-300"><Trees className="w-4 h-4" />Парки</div>
            {parkList.map((p) => (
              <button key={p.id} type="button" onClick={() => setPark(p.id)} data-testid={`cs-park-${p.id}`}
                className={`w-full flex items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs border ${park === p.id ? 'border-emerald-400/60 bg-emerald-400/10' : 'border-transparent hover:bg-white/5'}`}>
                <img src={p.src} alt="" className="w-9 h-9 object-contain" />
                <span className="flex-1 text-white">{parkName(p.id)}<span className="block text-[10px] text-text-muted">парк · {p.size.replace('x', '×')}{p.extra ? ' · добавлен' : ''}</span></span>
                {(parks.park_tuning[p.id] || p.replaced) && <span className="text-[10px] text-yellow-300">изм.</span>}
              </button>
            ))}
            <div className="grid grid-cols-2 gap-1.5 pt-1">
              <Button size="sm" variant="outline" className="h-7 text-[11px]" disabled={busy} onClick={() => pickFile(false, 'newpark:1x1')} data-testid="cs-park-add-1x1"><Plus className="w-3 h-3 mr-1" />Парк 1×1</Button>
              <Button size="sm" variant="outline" className="h-7 text-[11px]" disabled={busy} onClick={() => pickFile(false, 'newpark:2x2')} data-testid="cs-park-add-2x2"><Plus className="w-3 h-3 mr-1" />Парк 2×2</Button>
            </div>
            </>)}
          </CardContent>
        </Card>
        <Card className="glass-panel border-white/10">
          <CardHeader className="pb-2"><CardTitle className="text-sm">
            {park ? `Парк · ${parkName(park)} · участок ${(curPark?.size || '1x1').replace('x', '×')}` : `${meta.name_ru} · участок ${meta.footprint}`}
          </CardTitle></CardHeader>
          <CardContent className="space-y-3">
            {!park && (
              <div className="flex flex-wrap gap-1.5">
                {['1', '2', '3'].map((s) => (
                  <Button key={s} size="sm" variant={stage === s ? 'default' : 'outline'} className="h-8 text-xs" onClick={() => setStage(s)}>
                    Стадия {s} · ур. {s === '1' ? '0–3' : s === '2' ? '4–6' : '7–10'}
                  </Button>
                ))}
                {meta.footprint === '1x2' && !isGroup && (
                  <Button size="sm" variant="outline" className="h-8 text-xs ml-auto" onClick={() => setFlip((f) => !f)}>Участок {flip ? '2×1' : '1×2'} ↻</Button>
                )}
              </div>
            )}
            <div className="grid xl:grid-cols-2 gap-3">
              <div className="space-y-1">
                <canvas ref={cv} width={720} height={460} className="w-full rounded-xl border border-white/10" data-testid="cs-preview" />
                <div className="text-[11px] text-text-muted">Зелёный контур — участок. Справа для сравнения — Солнечная станция 1×1.</div>
              </div>
              <SpriteMapPreview kind={park ? 'park' : 'building'} id={park || type} stage={stage} tune={vals} spriteData={spriteData} skin={previewSkin} />
            </div>
            <div className="grid sm:grid-cols-3 gap-4">
              {slider('scale', 'Масштаб', 0.3, 3, 0.01, (v) => `${Math.round(v * 100)}%`)}
              {slider('sx', 'Ширина', 0.3, 3, 0.01, (v) => `${Math.round(v * 100)}%`)}
              {slider('sy', 'Высота', 0.3, 3, 0.01, (v) => `${Math.round(v * 100)}%`)}
              {slider('dx', 'Сдвиг по горизонтали', -0.5, 0.5, 0.005, (v) => `${Math.round(v * 100)}%`)}
              {slider('dy', 'Сдвиг по вертикали', -0.5, 0.5, 0.005, (v) => `${Math.round(v * 100)}%`)}
            </div>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" disabled={busy || (isGroup && !gSkin)} onClick={() => save(false)} data-testid="cs-save">{park ? 'Сохранить' : `Сохранить для стадии ${stage}`}</Button>
              {!park && <Button size="sm" variant="outline" disabled={busy || (isGroup && !gSkin)} onClick={() => save(true)}>Применить ко всем стадиям</Button>}
              <Button size="sm" variant="outline" disabled={busy} onClick={reset}><RotateCcw className="w-3.5 h-3.5 mr-1" />Сбросить</Button>
            </div>
            <div className="rounded-xl border border-white/10 bg-white/5 p-3 space-y-2" data-testid="cs-replace">
              <div className="text-sm font-bold text-white">{isGroup ? 'Картинка группы' : park ? 'Заменить картинку парка' : 'Заменить спрайт'}</div>
              <div className="text-[11px] text-text-muted">PNG/JPG/WEBP до 12 МБ. Тёмный фон вырезается автоматически; картинка с прозрачным фоном берётся как есть. {park ? 'Земля парка сама встаёт на квадрат.' : 'Фундамент сам встаёт на участок.'}{!park && meta.footprint === '1x2' ? ' Для участка 2×1 (кнопка «Участок … ↻») загружается вторая ориентация.' : ''}</div>
              <div className="flex flex-wrap gap-2">
                <Button size="sm" disabled={busy} onClick={() => pickFile(false)} data-testid="cs-upload">{park ? 'Загрузить картинку' : `Для стадии ${stage}`}</Button>
                {!park && <Button size="sm" variant="outline" disabled={busy} onClick={() => pickFile(true)}>Для всех стадий</Button>}
                {replacedHere && (
                  <Button size="sm" variant="outline" disabled={busy} onClick={resetSprite} data-testid="cs-unreplace">{isGroup ? `Удалить картинку стадии ${stage}` : park && curPark?.extra ? 'Удалить этот парк' : 'Вернуть стандартный'}</Button>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
