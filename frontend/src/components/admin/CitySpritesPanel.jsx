/**
 * CitySpritesPanel — fine-tune how each building sprite sits on its lot on the city map.
 * Auto-fit comes from /sprites/city/manifest.json (anchor, footprint_width, top); here the admin
 * adds scale and shift per business type and growth stage (backend/city_sprites.py).
 * The preview uses exactly the same placement math as the map.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { toast } from 'sonner';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Building2, RotateCcw } from 'lucide-react';

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
          </div>
        ))}
        <Button size="sm" disabled={busy} onClick={save} data-testid="districts-save">Сохранить районы</Button>
      </CardContent>
    </Card>
  );
}

export default function CitySpritesPanel({ token }) {
  const [manifest, setManifest] = useState(null);
  const [tuning, setTuning] = useState({});
  const [overrides, setOverrides] = useState({ overrides: {}, overrides_alt: {} });   // sprites replaced by the admin
  const fileRef = useRef(null);
  const [type, setType] = useState('helios');
  const [stage, setStage] = useState('1');
  const [vals, setVals] = useState({ scale: 1, sx: 1, sy: 1, dx: 0, dy: 0 });
  const [flip, setFlip] = useState(false);              // 1x2 lots: show the other orientation (2x1)
  const [busy, setBusy] = useState(false);
  const cv = useRef(null);
  const imgs = useRef({});
  const headers = { headers: { Authorization: `Bearer ${token}` } };

  const load = useCallback(async () => {
    try {
      const [m, t] = await Promise.all([fetch(SPR + 'manifest.json').then(r => r.json()), axios.get(`${BACKEND_URL}/api/city-sprites/tuning`)]);
      setManifest(m); setTuning(t.data.tuning || {});
      setOverrides({ overrides: t.data.overrides || {}, overrides_alt: t.data.overrides_alt || {} });
    } catch (e) { toast.error('Не удалось загрузить спрайты'); }
  }, []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { setVals({ scale: 1, sx: 1, sy: 1, dx: 0, dy: 0, ...(((tuning[type] || {})[stage]) || {}) }); }, [type, stage, tuning]);

  const getImg = (src) => new Promise((res) => {
    if (imgs.current[src]) return res(imgs.current[src]);
    const im = new Image(); im.onload = () => { imgs.current[src] = im; res(im); }; im.onerror = () => res(null); im.src = src;
  });

  // draw the preview: the lot grid + the sprite + a 1x1 reference building next to it
  useEffect(() => {
    if (!manifest || !cv.current) return;
    const meta = manifest.types[type]; if (!meta) return;
    let lot = FOOT[meta.footprint] || [1, 1]; if (meta.footprint === '1x2' && flip) lot = [2, 1];
    // the view whose long axis matches the lot (1x2 buildings have a second view, files_alt)
    let fm = (meta.files_meta || {})[stage] || meta, file = `${type}/stage${stage}.webp`;
    const lotLong = lot[0] === lot[1] ? null : (lot[1] > lot[0] ? 'y' : 'x');
    const alt = (meta.files_alt || {})[stage];
    let src = `${SPR}${type}/stage${stage}.webp`;
    const ov = ((overrides.overrides || {})[type] || {})[stage];
    if (ov) { fm = ov; src = `${BACKEND_URL}${ov.url}`; }
    if (lotLong && fm.long_axis && fm.long_axis !== lotLong) {
      const ova = ((overrides.overrides_alt || {})[type] || {})[stage];
      if (ova) { fm = ova; src = `${BACKEND_URL}${ova.url}`; } else if (alt && !ov) { fm = alt; file = alt.file; src = `${SPR}${file}`; }
    }
    const c = cv.current;
    // crisp on high-DPI screens: the canvas has as many pixels as the screen shows
    const dpr = Math.min(window.devicePixelRatio || 1, 3), cssW = c.clientWidth || 720, cssH = Math.round(cssW * 460 / 720);
    if (c.width !== Math.round(cssW * dpr)) { c.width = Math.round(cssW * dpr); c.height = Math.round(cssH * dpr); }
    const g = c.getContext('2d'); g.setTransform(dpr * cssW / 720, 0, 0, dpr * cssW / 720, 0, 0);
    g.imageSmoothingEnabled = true; g.imageSmoothingQuality = 'high';
    const W = 720, H = 460;
    (async () => {
      const im = await getImg(src);
      const refMeta = manifest.types.helios, refFm = (refMeta.files_meta || {})['1'] || refMeta;
      const ref = await getImg(`${SPR}helios/stage1.webp`);
      g.clearRect(0, 0, W, H); g.fillStyle = '#0b1220'; g.fillRect(0, 0, W, H);
      const origin = [W / 2 - 30, H * 0.52 - (lot[0] + lot[1]) * TW / 4];
      const box = spriteBox(meta, fm, vals, lot, (manifest.display_scale || {})[meta.footprint] || 1, origin);
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
        g.save(); if (box.mirror) { g.translate(box.cx, 0); g.scale(-1, 1); g.translate(-box.cx, 0); }
        g.drawImage(im, box.x, box.y, box.dw, box.dh); g.restore();
      }
    })();
  }, [manifest, type, stage, vals, flip, tuning, overrides]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = async (allStages) => {
    setBusy(true);
    try {
      const r = await axios.put(`${BACKEND_URL}/api/admin/city-sprites/tuning`, { type, stage: allStages ? 'all' : stage, ...vals }, headers);
      setTuning(r.data.tuning || {}); toast.success(allStages ? 'Сохранено для всех стадий' : 'Сохранено');
    } catch (e) { toast.error(e?.response?.data?.detail || 'Ошибка сохранения'); }
    finally { setBusy(false); }
  };
  const upload = async (file, allStages) => {
    if (!file) return;
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append('type', type); fd.append('stage', allStages ? 'all' : stage);
      fd.append('view', meta.footprint === '1x2' && flip ? 'alt' : 'main'); fd.append('file', file);
      const r = await axios.post(`${BACKEND_URL}/api/admin/city-sprites/upload`, fd, headers);
      setOverrides({ overrides: r.data.overrides || {}, overrides_alt: r.data.overrides_alt || {} });
      toast.success('Спрайт заменён — он уже на карте');
    } catch (e) { toast.error(e?.response?.data?.detail || 'Не удалось загрузить'); }
    finally { setBusy(false); if (fileRef.current) fileRef.current.value = ''; }
  };
  const resetSprite = async () => {
    setBusy(true);
    try {
      const r = await axios.delete(`${BACKEND_URL}/api/admin/city-sprites/override/${type}/${stage}`, { ...headers, params: { view: meta.footprint === '1x2' && flip ? 'alt' : 'main' } });
      setOverrides({ overrides: r.data.overrides || {}, overrides_alt: r.data.overrides_alt || {} });
      toast.success('Стандартный спрайт возвращён');
    } catch (e) { toast.error('Ошибка'); } finally { setBusy(false); }
  };
  const reset = async () => {
    setBusy(true);
    try {
      const r = await axios.delete(`${BACKEND_URL}/api/admin/city-sprites/tuning/${type}/${stage}`, headers);
      setTuning(r.data.tuning || {}); toast.success('Сброшено к автоподгонке');
    } catch (e) { toast.error('Ошибка'); } finally { setBusy(false); }
  };

  if (!manifest) return <div className="text-sm text-text-muted">Загрузка…</div>;
  const types = Object.entries(manifest.types).sort((a, b) => a[1].tier - b[1].tier || a[1].footprint.localeCompare(b[1].footprint));
  const meta = manifest.types[type];
  const tuned = (t) => Object.keys(tuning[t] || {}).length > 0;
  const slider = (key, label, min, max, step, fmt) => (
    <label className="block text-xs space-y-1">
      <span className="flex justify-between text-text-muted"><span>{label}</span><b className="text-white">{fmt(vals[key])}</b></span>
      <input type="range" min={min} max={max} step={step} value={vals[key]} className="w-full accent-cyan-400"
        onChange={(e) => setVals((v) => ({ ...v, [key]: Number(e.target.value) }))} data-testid={`cs-${key}`} />
    </label>
  );

  return (
    <div className="space-y-4" data-testid="city-sprites-panel">
      <div className="flex items-center gap-2"><Building2 className="w-5 h-5 text-cyan-300" /><span className="font-bold text-white">Спрайты зданий на карте</span></div>
      <div className="grid lg:grid-cols-[260px_1fr] gap-4">
        <Card className="glass-panel border-white/10">
          <CardHeader className="pb-2"><CardTitle className="text-sm">Бизнес</CardTitle></CardHeader>
          <CardContent className="space-y-1 max-h-[560px] overflow-y-auto">
            {types.map(([k, t]) => (
              <button key={k} type="button" onClick={() => setType(k)} data-testid={`cs-type-${k}`}
                className={`w-full flex items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs border ${type === k ? 'border-cyan-400/60 bg-cyan-400/10' : 'border-transparent hover:bg-white/5'}`}>
                <img src={`${SPR}${k}/stage1.webp`} alt="" className="w-9 h-9 object-contain" />
                <span className="flex-1 text-white">{t.name_ru}<span className="block text-[10px] text-text-muted">тир {t.tier} · {t.footprint}</span></span>
                {tuned(k) && <span className="text-[10px] text-yellow-300">изм.</span>}
              </button>
            ))}
          </CardContent>
        </Card>
        <Card className="glass-panel border-white/10">
          <CardHeader className="pb-2"><CardTitle className="text-sm">{meta.name_ru} · участок {meta.footprint}</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <div className="flex flex-wrap gap-1.5">
              {['1', '2', '3'].map((s) => (
                <Button key={s} size="sm" variant={stage === s ? 'default' : 'outline'} className="h-8 text-xs" onClick={() => setStage(s)}>
                  Стадия {s} · ур. {s === '1' ? '0–3' : s === '2' ? '4–6' : '7–10'}
                </Button>
              ))}
              {meta.footprint === '1x2' && (
                <Button size="sm" variant="outline" className="h-8 text-xs ml-auto" onClick={() => setFlip((f) => !f)}>Участок {flip ? '2×1' : '1×2'} ↻</Button>
              )}
            </div>
            <canvas ref={cv} width={720} height={460} className="w-full rounded-xl border border-white/10" data-testid="cs-preview" />
            <div className="text-[11px] text-text-muted">Зелёный контур — участок. Справа для сравнения — Солнечная станция 1×1.</div>
            <div className="grid sm:grid-cols-3 gap-4">
              {slider('scale', 'Масштаб', 0.3, 3, 0.01, (v) => `${Math.round(v * 100)}%`)}
              {slider('sx', 'Ширина', 0.3, 3, 0.01, (v) => `${Math.round(v * 100)}%`)}
              {slider('sy', 'Высота', 0.3, 3, 0.01, (v) => `${Math.round(v * 100)}%`)}
              {slider('dx', 'Сдвиг по горизонтали', -0.5, 0.5, 0.005, (v) => `${Math.round(v * 100)}%`)}
              {slider('dy', 'Сдвиг по вертикали', -0.5, 0.5, 0.005, (v) => `${Math.round(v * 100)}%`)}
            </div>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" disabled={busy} onClick={() => save(false)} data-testid="cs-save">Сохранить для стадии {stage}</Button>
              <Button size="sm" variant="outline" disabled={busy} onClick={() => save(true)}>Применить ко всем стадиям</Button>
              <Button size="sm" variant="outline" disabled={busy} onClick={reset}><RotateCcw className="w-3.5 h-3.5 mr-1" />Сбросить</Button>
            </div>
            <div className="rounded-xl border border-white/10 bg-white/5 p-3 space-y-2" data-testid="cs-replace">
              <div className="text-sm font-bold text-white">Заменить спрайт</div>
              <div className="text-[11px] text-text-muted">PNG/JPG/WEBP до 12 МБ. Тёмный фон вырезается автоматически; картинка с прозрачным фоном берётся как есть. Фундамент сам встаёт на участок.{meta.footprint === '1x2' ? ' Для участка 2×1 (кнопка «Участок … ↻») загружается вторая ориентация.' : ''}</div>
              <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" className="hidden" data-testid="cs-file"
                onChange={(e) => upload(e.target.files?.[0], fileRef.current?.dataset.all === '1')} />
              <div className="flex flex-wrap gap-2">
                <Button size="sm" disabled={busy} onClick={() => { fileRef.current.dataset.all = '0'; fileRef.current.click(); }}>Для стадии {stage}</Button>
                <Button size="sm" variant="outline" disabled={busy} onClick={() => { fileRef.current.dataset.all = '1'; fileRef.current.click(); }}>Для всех стадий</Button>
                {(((overrides[(meta.footprint === '1x2' && flip) ? 'overrides_alt' : 'overrides'] || {})[type] || {})[stage]) && (
                  <Button size="sm" variant="outline" disabled={busy} onClick={resetSprite}>Вернуть стандартный</Button>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
