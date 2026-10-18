/**
 * One place for every building picture of the game.
 *  • «Стандарт» = the buildings of the city map (base skin of every player) — CitySpritesPanel.
 *  • Other groups (Crazy, Неон, …): the same editor (CitySpritesPanel group mode) — a picture per business and
 *    growth stage, processed like the buildings, with the same sliders and «На карте» preview.
 *  • «+ Новая группа»: name + key, then the first picture creates the group.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import CitySpritesPanel from '@/components/admin/CitySpritesPanel';

const BACKEND = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND}/api`;
const STAGES = [['1', 'ур. 0–3', 0], ['2', 'ур. 4–6', 4], ['3', 'ур. 7–10', 7]];
const abs = (u) => (u && u.startsWith('/api/') ? `${BACKEND}${u}` : u);

export default function SkinsStudio({ token }) {
  const h = { headers: { Authorization: `Bearer ${token}` } };
  const [manifest, setManifest] = useState(null);
  const [groups, setGroups] = useState([]);
  const [group, setGroup] = useState('standard');
  const [skins, setSkins] = useState([]);
  const [busy, setBusy] = useState(false);
  const [newKey, setNewKey] = useState(''); const [newName, setNewName] = useState('');
  const fileRef = useRef(null); const target = useRef(null);

  const load = useCallback(async () => {
    try {
      const [m, g] = await Promise.all([fetch('/sprites/city/manifest.json').then((r) => r.json()), axios.get(`${API}/admin/skins/groups`, h)]);
      setManifest(m); setGroups((g.data.groups || []).filter((x) => x.group_key !== 'standard'));
    } catch (e) { toast.error('Не удалось загрузить скины'); }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const loadSkins = useCallback(async (gk) => {
    if (!gk || gk === 'standard') return;
    try { const r = await axios.get(`${API}/admin/skins`, { ...h, params: { group_key: gk } }); setSkins(r.data.skins || []); }
    catch (e) { setSkins([]); }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);
  useEffect(() => { loadSkins(group); }, [group, loadSkins]);

  const pick = (type, stage) => { target.current = { type, stage }; fileRef.current.value = ''; fileRef.current.click(); };
  const upload = async (file) => {
    if (!file || !target.current) return;
    const gk = group === '__new' ? newKey.trim().toLowerCase() : group;
    const gname = group === '__new' ? newName.trim() : (groups.find((g) => g.group_key === group)?.group_name || '');
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append('group_key', gk); fd.append('group_name', gname); fd.append('business_type', target.current.type);
      fd.append('stage', target.current.stage); fd.append('file', file);
      await axios.post(`${API}/admin/skins/upload`, fd, h);
      toast.success('Скин загружен');
      if (group === '__new') { await load(); setGroup(gk); } else { loadSkins(gk); }
    } catch (e) { toast.error(e?.response?.data?.detail || 'Не удалось загрузить'); } finally { setBusy(false); }
  };
  const remove = async (type, stage) => {
    if (!window.confirm('Удалить картинку этой стадии?')) return;
    try { await axios.delete(`${API}/admin/skins/stage/${group}/${type}/${stage}`, h); loadSkins(group); }
    catch (e) { toast.error('Ошибка'); }
  };

  const types = manifest ? Object.entries(manifest.types).sort((a, b) => a[1].tier - b[1].tier || a[1].footprint.localeCompare(b[1].footprint)) : [];
  const imgOf = (type, lvl) => abs((skins.find((s) => s.business_type === type && Number(s.level) === lvl) || {}).image);
  const chip = (key, label) => (
    <button key={key} type="button" onClick={() => setGroup(key)} data-testid={`skins-group-${key}`}
      className={`rounded-lg border px-3 py-2 text-sm ${group === key ? 'border-cyan-400 bg-cyan-500/15 text-white' : 'border-white/10 bg-white/5 text-text-muted hover:text-white'}`}>{label}</button>
  );

  return (
    <div className="space-y-4" data-testid="skins-studio">
      <div className="text-xs text-text-muted">Все картинки зданий в одном месте. «Стандарт» — здания карты (базовый скин каждого игрока). Другие группы — скины, которые выдаются игрокам; у каждого бизнеса по картинке на стадию. Картинка обрабатывается автоматически: тёмный фон вырезается, фундамент встаёт на участок.</div>
      <div className="flex flex-wrap gap-2">
        {chip('standard', '⭐ Стандарт (здания карты)')}
        {groups.map((g) => chip(g.group_key, `${g.group_name || g.group_key} · ${g.count ?? ''}`))}
        {chip('__new', '+ Новая группа')}
      </div>

      {group === 'standard' && <CitySpritesPanel token={token} />}

      {/* a skin group: the same editor as the city buildings (list on the left, preview on the lot and on the map, sliders) */}
      {group !== 'standard' && group !== '__new' && (
        <CitySpritesPanel key={group} token={token} group={group} groupName={groups.find((g) => g.group_key === group)?.group_name || group} />
      )}

      {group === '__new' && (
        <div className="space-y-3">
          {group === '__new' && (
            <div className="grid sm:grid-cols-2 gap-3">
              <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="Название группы (например, Киберпанк)" className="rounded bg-black/40 border border-white/10 px-3 py-2 text-white text-sm" />
              <input value={newKey} onChange={(e) => setNewKey(e.target.value.replace(/[^a-z0-9_]/gi, '').toLowerCase())} placeholder="Ключ (латиница): cyberpunk" className="rounded bg-black/40 border border-white/10 px-3 py-2 text-white text-sm" data-testid="skins-new-key" />
              <div className="sm:col-span-2 text-[11px] text-text-muted">Загрузите первую картинку ниже — группа создастся.</div>
            </div>
          )}
          <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" className="hidden" onChange={(e) => upload(e.target.files?.[0])} data-testid="skins-file" />
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-text-muted"><tr><th className="text-left p-2">Бизнес</th>{STAGES.map(([st, label]) => <th key={st} className="p-2">{label}</th>)}<th className="p-2">Все стадии</th></tr></thead>
              <tbody>
                {types.map(([type, m]) => (
                  <tr key={type} className="border-t border-white/5">
                    <td className="p-2 text-white whitespace-nowrap">{m.name_ru}<span className="block text-[10px] text-text-muted">тир {m.tier} · {m.footprint}</span></td>
                    {STAGES.map(([st, , lvl]) => {
                      const img = group === '__new' ? null : imgOf(type, lvl);
                      return (
                        <td key={st} className="p-1.5 text-center">
                          <div className="mx-auto w-20 h-24 rounded-lg bg-black/30 border border-white/10 flex items-center justify-center overflow-hidden">
                            {img ? <img src={img} alt="" className="w-full h-full object-contain" /> : <span className="text-text-muted">—</span>}
                          </div>
                          <div className="mt-1 flex justify-center gap-1">
                            <Button size="sm" variant="outline" className="h-6 px-2 text-[10px]" disabled={busy || (group === '__new' && !newKey)} onClick={() => pick(type, st)} data-testid={`skins-up-${type}-${st}`}>Загрузить</Button>
                            {img && <Button size="sm" variant="outline" className="h-6 px-2 text-[10px] text-red-300" onClick={() => remove(type, st)}>✕</Button>}
                          </div>
                        </td>
                      );
                    })}
                    <td className="p-1.5 text-center"><Button size="sm" variant="outline" className="h-6 px-2 text-[10px]" disabled={busy || (group === '__new' && !newKey)} onClick={() => pick(type, 'all')}>Загрузить</Button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
