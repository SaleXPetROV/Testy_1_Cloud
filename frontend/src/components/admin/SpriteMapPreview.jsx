/**
 * Admin sprite editor → «На карте»: the real city map (same engine as the players' map) flown to a place
 * where the edited building / park picture stands, with the unsaved sliders applied live. The edited lot is
 * outlined in pink. If nothing of this kind stands on the map yet, it is shown on a free lot of its size.
 */
import { useEffect, useRef, useState } from 'react';
import { CityMapEngine } from '@/engine/CityMapEngine';
import { mapStore } from '@/engine/IsometricMapEngine';
import { Button } from '@/components/ui/button';
import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut } from 'lucide-react';

const B = process.env.REACT_APP_BACKEND_URL || '';

/** The admin page may be opened without the map: load the cells once (standard sprites, no player skins). */
async function ensureMapData() {
  if ((mapStore.getState().cells?.size || 0) > 0) return;
  const d = await fetch(`${B}/api/island`, { cache: 'no-store' }).then((r) => r.json());
  mapStore.dispatch({ type: 'SET_LAYOUT', layout: d.parks ? { parks: d.parks, districts: d.districts, width: d.width } : null });
  fetch(`${B}/api/city/districts`).then((r) => (r.ok ? r.json() : null)).then((x) => x && mapStore.dispatch({ type: 'SET_DISTRICTS', districts: x })).catch(() => {});
  const cells = (d.cells || []).map((c) => {
    const type = c.business?.type || (!c.owner ? c.pre_business : null);
    return {
      q: c.x, r: c.y, w: c.w || 1, h: c.h || 1, district: c.district, slotId: c.slot_id, zone: c.zone,
      price: c.price_city || 0, owner: c.owner, isEmptyPlot: c.is_empty === true,
      building: type ? { type, level: c.business?.level || 1, isPreview: !c.business, is_active: true, durability: 100 } : null,
    };
  });
  if (cells.length) mapStore.dispatch({ type: 'SET_CELLS', cells });
}

/** kind: 'building' | 'park'; id: business type or park id; stage: '1'..'3'; tune: unsaved slider values;
 *  spriteData: /api/city-sprites/tuning (reloaded by the parent after a save / upload). */
export default function SpriteMapPreview({ kind, id, stage, tune, spriteData, skin }) {
  const box = useRef(null);
  const eng = useRef(null);
  const [ready, setReady] = useState(false);
  const [spots, setSpots] = useState([]);
  const [idx, setIdx] = useState(0);

  useEffect(() => {
    let alive = true;
    const el = box.current;
    (async () => {
      try { await ensureMapData(); } catch (_) { /* the map just stays empty */ }
      if (!alive || !el) return;
      const e = new CityMapEngine(el, { width: el.clientWidth, height: el.clientHeight });
      await e.init();
      if (!alive) { e.destroy(); return; }
      eng.current = e; setReady(true);
    })();
    const ro = new ResizeObserver(() => { if (eng.current && el) eng.current.resize(el.clientWidth, el.clientHeight); });
    if (el) ro.observe(el);
    return () => { alive = false; ro.disconnect(); if (eng.current) { eng.current.destroy(); eng.current = null; } };
  }, []);

  useEffect(() => { if (ready && spriteData) eng.current.setSpriteData(spriteData); }, [ready, spriteData]);

  // a new building / park: find where it stands and fly there
  useEffect(() => {
    if (!ready) return;
    const list = eng.current.findPreviewSpots(kind, id);
    setSpots(list); setIdx(0);
  }, [ready, kind, id]);

  const spot = spots[idx] || null;
  useEffect(() => {
    if (!ready) return;
    // skin: {url, meta} — a picture of a skin group shown instead of the standard sprite
    eng.current.setPreview({ kind, type: id, id, stage, tune, key: spot ? spot.key : null, skin: skin || null });
  }, [ready, kind, id, stage, tune, spot, skin]);
  useEffect(() => { if (ready && spot) eng.current.focusSpot(spot, spot.w > 1 || spot.h > 1 ? 1.6 : 2.2); }, [ready, spot]);
  useEffect(() => () => { if (eng.current) eng.current.setPreview(null); }, []);

  const go = (d) => setIdx((i) => (spots.length ? (i + d + spots.length) % spots.length : 0));
  return (
    <div className="space-y-2" data-testid="sprite-map-preview">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-bold text-white">На карте</span>
        <span className="text-[11px] text-text-muted" data-testid="sprite-map-place">
          {spots.length ? `место ${idx + 1} из ${spots.length}${spot && spot.ghost ? ' · свободный участок такого же размера' : ''}` : 'загрузка карты…'}
        </span>
        <div className="ml-auto flex gap-1">
          <Button size="sm" variant="outline" className="h-7 px-2" disabled={spots.length < 2} onClick={() => go(-1)} aria-label="Предыдущее место"><ChevronLeft className="w-4 h-4" /></Button>
          <Button size="sm" variant="outline" className="h-7 px-2" disabled={spots.length < 2} onClick={() => go(1)} data-testid="sprite-map-next" aria-label="Следующее место"><ChevronRight className="w-4 h-4" /></Button>
          <Button size="sm" variant="outline" className="h-7 px-2" onClick={() => eng.current && eng.current.zoomIn()} aria-label="Приблизить"><ZoomIn className="w-4 h-4" /></Button>
          <Button size="sm" variant="outline" className="h-7 px-2" onClick={() => eng.current && eng.current.zoomOut()} aria-label="Отдалить"><ZoomOut className="w-4 h-4" /></Button>
        </div>
      </div>
      <div ref={box} className="w-full h-[380px] rounded-xl border border-white/10 overflow-hidden bg-[#0b1220]" />
      <div className="text-[11px] text-text-muted">Розовый контур — участок, где показан спрайт. Ползунки применяются сразу (до сохранения); остальные здания этого типа на карте тоже показаны в выбранной стадии. Карту можно двигать и масштабировать.</div>
    </div>
  );
}
