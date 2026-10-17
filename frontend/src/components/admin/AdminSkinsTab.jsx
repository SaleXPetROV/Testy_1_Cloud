import { useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import { toast } from 'sonner';
import { Plus, Trash2, RefreshCw, UploadCloud, Check, AlertTriangle, Image as ImageIcon, Layers, Settings } from 'lucide-react';
import { BUSINESSES } from '@/lib/buildingSprites';
import { getBusinessName } from '@/lib/businessNames';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api`;

const BIZ_OPTIONS = Object.keys(BUSINESSES);
const LEVELS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10];

function slugify(s) {
  return (s || '').toString().trim().toLowerCase()
    .replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '') || '';
}

export default function AdminSkinsTab({ lang = 'ru' }) {
  const token = localStorage.getItem('token');
  const hdr = useMemo(() => ({ headers: { Authorization: `Bearer ${token}` } }), [token]);

  const [groups, setGroups] = useState([]);
  const [skins, setSkins] = useState([]);
  const [loading, setLoading] = useState(false);

  // form
  const [groupMode, setGroupMode] = useState('existing'); // existing | new
  const [groupKey, setGroupKey] = useState('');
  const [newGroupName, setNewGroupName] = useState('');
  const [newGroupKey, setNewGroupKey] = useState('');
  const [bizType, setBizType] = useState('bio_farm');
  const [level, setLevel] = useState(0);
  const [imageData, setImageData] = useState('');
  const [exists, setExists] = useState(null); // existing skin if any
  const [saving, setSaving] = useState(false);

  // browser filters
  const [fGroup, setFGroup] = useState('');
  const [fBiz, setFBiz] = useState('');
  const [fLevel, setFLevel] = useState('');

  // per-skin size editor modal
  const [sizeEditor, setSizeEditor] = useState(null); // skin object being edited
  const [hInput, setHInput] = useState(100);
  const [wInput, setWInput] = useState(100);
  const [savingSize, setSavingSize] = useState(false);

  const openSizeEditor = (s) => {
    setSizeEditor(s);
    setHInput(Number(s.height_pct ?? 100));
    setWInput(Number(s.width_pct ?? 100));
  };

  const saveSize = async () => {
    if (!sizeEditor) return;
    const h = Math.max(10, Math.min(400, Number(hInput) || 100));
    const w = Math.max(10, Math.min(400, Number(wInput) || 100));
    setSavingSize(true);
    try {
      await axios.patch(`${API}/admin/skins/${sizeEditor.id}/size`, { height_pct: h, width_pct: w }, hdr);
      toast.success('Размер сохранён');
      setSizeEditor(null);
      await fetchSkins();
    } catch (e) {
      toast.error('Ошибка сохранения размера');
    } finally { setSavingSize(false); }
  };

  const fetchGroups = async () => {
    try {
      const res = await axios.get(`${API}/admin/skins/groups`, hdr);
      setGroups(res.data.groups || []);
      if (!groupKey && res.data.groups?.length) setGroupKey(res.data.groups[0].group_key);
    } catch (e) { /* ignore */ }
  };

  const fetchSkins = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (fGroup) params.set('group_key', fGroup);
      if (fBiz) params.set('business_type', fBiz);
      if (fLevel !== '') params.set('level', fLevel);
      const res = await axios.get(`${API}/admin/skins?${params.toString()}`, hdr);
      setSkins(res.data.skins || []);
    } catch (e) {
      toast.error('Ошибка загрузки скинов');
    } finally { setLoading(false); }
  };

  useEffect(() => { fetchGroups(); }, []);
  useEffect(() => { fetchSkins(); }, [fGroup, fBiz, fLevel]);

  const effectiveGroupKey = groupMode === 'new' ? (newGroupKey || slugify(newGroupName)) : groupKey;

  // exists-check whenever group/type/level changes
  useEffect(() => {
    const gk = effectiveGroupKey;
    if (!gk || !bizType) { setExists(null); return; }
    let cancelled = false;
    (async () => {
      try {
        const res = await axios.get(`${API}/admin/skins/exists?group_key=${gk}&business_type=${bizType}&level=${level}`, hdr);
        if (!cancelled) setExists(res.data.exists ? res.data.skin : null);
      } catch { if (!cancelled) setExists(null); }
    })();
    return () => { cancelled = true; };
  }, [effectiveGroupKey, bizType, level]);

  const onFile = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!/\.webp$/i.test(file.name) && file.type !== 'image/webp') {
      toast.error('Только WEBP файлы'); return;
    }
    if (file.size > 1.5 * 1024 * 1024) {
      toast.error('Файл слишком большой (макс. 1.5 МБ)'); return;
    }
    const reader = new FileReader();
    reader.onload = () => setImageData(reader.result);
    reader.readAsDataURL(file);
  };

  const addSkin = async () => {
    if (groupMode === 'new' && !newGroupName.trim()) return toast.error('Введите название новой группы');
    if (!effectiveGroupKey) return toast.error('Укажите группу');
    if (!bizType) return toast.error('Выберите бизнес');
    if (!imageData) return toast.error('Загрузите WEBP изображение');
    if (exists) return toast.error('Скин для этого уровня и группы уже существует');
    setSaving(true);
    try {
      const groupName = groupMode === 'new'
        ? newGroupName.trim()
        : (groups.find(g => g.group_key === groupKey)?.group_name || effectiveGroupKey);
      await axios.post(`${API}/admin/skins`, {
        group_key: effectiveGroupKey,
        group_name: groupName,
        business_type: bizType,
        level: Number(level),
        image: imageData,
        is_standard: effectiveGroupKey === 'standard',
      }, hdr);
      toast.success('Скин успешно добавлен');
      setImageData('');
      // if it was a new group, switch to existing selection of it
      if (groupMode === 'new') {
        setGroupMode('existing');
        setGroupKey(effectiveGroupKey);
        setNewGroupName(''); setNewGroupKey('');
      }
      await fetchGroups();
      await fetchSkins();
    } catch (e) {
      const d = e.response?.data?.detail;
      toast.error(typeof d === 'object' ? (d.message || 'Уже существует') : (d || 'Ошибка добавления'));
    } finally { setSaving(false); }
  };

  const deleteSkin = async (s) => {
    if (!window.confirm(`Удалить скин «${s.group_name}» (${s.business_type} lvl ${s.level})?`)) return;
    try {
      await axios.delete(`${API}/admin/skins/${s.id}`, hdr);
      toast.success('Удалено');
      fetchGroups(); fetchSkins();
    } catch { toast.error('Ошибка удаления'); }
  };

  const bizLabel = (k) => getBusinessName(k, lang);

  return (
    <div className="space-y-6" data-testid="admin-skins-tab">
      {/* ── Add skin ─────────────────────────────────────────────── */}
      <div className="bg-white/5 border border-white/10 rounded-2xl p-4">
        <h2 className="text-lg font-bold text-white flex items-center gap-2 mb-3">
          <UploadCloud className="w-5 h-5 text-fuchsia-400" /> Добавить скин (WEBP)
        </h2>

        {/* group selector */}
        <div className="flex items-center gap-4 mb-3 text-sm">
          <label className="flex items-center gap-1.5 cursor-pointer text-white/80">
            <input type="radio" checked={groupMode === 'existing'} onChange={() => setGroupMode('existing')} data-testid="skin-group-existing" />
            В существующую группу
          </label>
          <label className="flex items-center gap-1.5 cursor-pointer text-white/80">
            <input type="radio" checked={groupMode === 'new'} onChange={() => setGroupMode('new')} data-testid="skin-group-new" />
            Создать новую группу
          </label>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          {groupMode === 'existing' ? (
            <div>
              <label className="text-[11px] text-white/50">Группа (название скина)</label>
              <select value={groupKey} onChange={(e) => setGroupKey(e.target.value)}
                className="w-full bg-black/40 border border-white/15 rounded-lg px-3 py-2 text-sm text-white" data-testid="skin-group-select">
                {groups.length === 0 && <option value="">— нет групп —</option>}
                {groups.map(g => <option key={g.group_key} value={g.group_key}>{g.group_name} ({g.group_key})</option>)}
              </select>
            </div>
          ) : (
            <>
              <div>
                <label className="text-[11px] text-white/50">Название группы (видят игроки)</label>
                <input value={newGroupName} onChange={(e) => setNewGroupName(e.target.value)}
                  placeholder="Напр.: Crazy Bio Farm" className="w-full bg-black/40 border border-white/15 rounded-lg px-3 py-2 text-sm text-white placeholder-white/30" data-testid="skin-new-group-name" />
              </div>
              <div>
                <label className="text-[11px] text-white/50">Ключ группы (латиница)</label>
                <input value={newGroupKey} onChange={(e) => setNewGroupKey(slugify(e.target.value))}
                  placeholder={slugify(newGroupName) || 'auto'} className="w-full bg-black/40 border border-white/15 rounded-lg px-3 py-2 text-sm text-white placeholder-white/30" data-testid="skin-new-group-key" />
              </div>
            </>
          )}

          <div>
            <label className="text-[11px] text-white/50">Бизнес</label>
            <select value={bizType} onChange={(e) => setBizType(e.target.value)}
              className="w-full bg-black/40 border border-white/15 rounded-lg px-3 py-2 text-sm text-white" data-testid="skin-biz-select">
              {BIZ_OPTIONS.map(k => <option key={k} value={k}>{bizLabel(k)} ({k})</option>)}
            </select>
          </div>
          <div>
            <label className="text-[11px] text-white/50">Уровень (0 = все уровни)</label>
            <select value={level} onChange={(e) => setLevel(Number(e.target.value))}
              className="w-full bg-black/40 border border-white/15 rounded-lg px-3 py-2 text-sm text-white" data-testid="skin-level-select">
              {LEVELS.map(l => <option key={l} value={l}>{l === 0 ? 'Все уровни' : `Уровень ${l}`}</option>)}
            </select>
          </div>
        </div>

        {exists && (
          <div className="mt-3 flex items-center gap-3 rounded-lg border border-amber-400/40 bg-amber-500/10 p-2.5" data-testid="skin-exists-warning">
            <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0" />
            <span className="text-xs text-amber-200">Скин для этой группы/бизнеса/уровня уже есть:</span>
            <img src={exists.image} alt="existing" className="w-10 h-10 object-contain rounded bg-black/30" />
          </div>
        )}

        <div className="mt-3 flex flex-wrap items-center gap-3">
          <label className="px-3 py-2 bg-white/5 hover:bg-white/10 border border-white/15 rounded-lg text-sm text-white/80 cursor-pointer flex items-center gap-2" data-testid="skin-file-label">
            <ImageIcon className="w-4 h-4" /> Выбрать WEBP
            <input type="file" accept=".webp,image/webp" className="hidden" onChange={onFile} data-testid="skin-file-input" />
          </label>
          {imageData && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-white/50">Предпросмотр:</span>
              <img src={imageData} alt="preview" className="w-14 h-14 object-contain rounded-lg bg-black/30 border border-white/10" data-testid="skin-preview" />
            </div>
          )}
          <button onClick={addSkin} disabled={saving || !!exists}
            className="ml-auto px-4 py-2 bg-fuchsia-500 hover:bg-fuchsia-400 disabled:opacity-40 text-white rounded-lg text-sm font-semibold flex items-center gap-2" data-testid="skin-add-submit">
            <Plus className="w-4 h-4" /> {saving ? 'Сохранение…' : 'Добавить скин'}
          </button>
        </div>
        <p className="text-[10px] text-white/40 mt-2">Название группы = название скина, которое видят все игроки. Можно добавлять несколько скинов подряд (по уровням/бизнесам).</p>
      </div>

      {/* ── Browser ─────────────────────────────────────────────── */}
      <div className="bg-white/5 border border-white/10 rounded-2xl p-4">
        <div className="flex items-center justify-between flex-wrap gap-3 mb-3">
          <h2 className="text-lg font-bold text-white flex items-center gap-2">
            <Layers className="w-5 h-5 text-cyan-300" /> Все скины проекта
          </h2>
          <button onClick={fetchSkins} className="px-3 py-1.5 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-xs text-white/70 flex items-center gap-1.5" data-testid="skins-refresh">
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> Обновить
          </button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
          <select value={fGroup} onChange={(e) => setFGroup(e.target.value)} className="bg-black/40 border border-white/15 rounded-lg px-3 py-2 text-sm text-white" data-testid="skin-filter-group">
            <option value="">Все группы</option>
            {groups.map(g => <option key={g.group_key} value={g.group_key}>{g.group_name}</option>)}
          </select>
          <select value={fBiz} onChange={(e) => setFBiz(e.target.value)} className="bg-black/40 border border-white/15 rounded-lg px-3 py-2 text-sm text-white" data-testid="skin-filter-biz">
            <option value="">Все бизнесы</option>
            {BIZ_OPTIONS.map(k => <option key={k} value={k}>{bizLabel(k)}</option>)}
          </select>
          <select value={fLevel} onChange={(e) => setFLevel(e.target.value)} className="bg-black/40 border border-white/15 rounded-lg px-3 py-2 text-sm text-white" data-testid="skin-filter-level">
            <option value="">Все уровни</option>
            {LEVELS.map(l => <option key={l} value={l}>{l === 0 ? 'Все уровни' : `Уровень ${l}`}</option>)}
          </select>
        </div>

        {skins.length === 0 ? (
          <div className="text-center text-white/40 py-8" data-testid="skins-browser-empty">Скинов нет</div>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3" data-testid="skins-browser-grid">
            {skins.map(s => (
              <div key={s.id} className="relative rounded-xl border border-white/10 bg-white/5 p-2 flex flex-col items-center gap-1" data-testid={`skin-item-${s.id}`}>
                <div className="w-full aspect-square rounded-lg bg-black/30 flex items-center justify-center overflow-hidden">
                  <img src={s.image} alt={s.group_name} className="w-full h-full object-contain" />
                </div>
                <span className="text-[11px] text-white/80 text-center leading-tight line-clamp-1">{s.group_name}{s.is_standard ? ' ★' : ''}</span>
                <span className="text-[10px] text-white/40 text-center leading-tight">{bizLabel(s.business_type)} · {s.level === 0 ? 'все ур.' : `ур.${s.level}`}</span>
                {(s.height_pct != null || s.width_pct != null) && (
                  <span className="text-[9px] text-cyan-300/70 text-center leading-tight">В {Math.round(s.height_pct ?? 100)}% · Ш {Math.round(s.width_pct ?? 100)}%</span>
                )}
                <button onClick={() => openSizeEditor(s)} className="absolute top-1 left-1 p-1 bg-cyan-500/20 hover:bg-cyan-500/40 text-cyan-200 rounded" data-testid={`skin-settings-${s.id}`} title="Настройки размера">
                  <Settings className="w-3 h-3" />
                </button>
                <button onClick={() => deleteSkin(s)} className="absolute top-1 right-1 p-1 bg-red-500/20 hover:bg-red-500/40 text-red-300 rounded" data-testid={`skin-delete-${s.id}`}>
                  <Trash2 className="w-3 h-3" />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── Per-skin size editor modal ──────────────────────────── */}
      {sizeEditor && (
        <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/70 p-4" data-testid="skin-size-modal" onClick={() => setSizeEditor(null)}>
          <div className="w-full max-w-sm bg-[#0d0f17] border border-white/15 rounded-2xl p-5 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-base font-bold text-white flex items-center gap-2 mb-1">
              <Settings className="w-4 h-4 text-cyan-300" /> Размер скина
            </h3>
            <p className="text-[11px] text-white/50 mb-4">{sizeEditor.group_name} · {bizLabel(sizeEditor.business_type)} · {sizeEditor.level === 0 ? 'все ур.' : `ур.${sizeEditor.level}`}</p>

            <div className="flex justify-center mb-4">
              <img src={sizeEditor.image} alt={sizeEditor.group_name} className="w-20 h-20 object-contain rounded-lg bg-black/30 border border-white/10" />
            </div>

            <div className="space-y-3">
              <div>
                <label className="text-xs text-white/70">По высоте, % от оригинала</label>
                <input type="number" min={10} max={400} value={hInput}
                  onChange={(e) => setHInput(e.target.value)}
                  className="w-full mt-1 bg-black/40 border border-white/15 rounded-lg px-3 py-2 text-sm text-white" data-testid="skin-size-height" />
              </div>
              <div>
                <label className="text-xs text-white/70">По ширине, % от оригинала</label>
                <input type="number" min={10} max={400} value={wInput}
                  onChange={(e) => setWInput(e.target.value)}
                  className="w-full mt-1 bg-black/40 border border-white/15 rounded-lg px-3 py-2 text-sm text-white" data-testid="skin-size-width" />
              </div>
            </div>

            <div className="mt-5 flex items-center gap-2">
              <button onClick={() => setSizeEditor(null)} className="flex-1 px-4 py-2 bg-white/5 hover:bg-white/10 border border-white/15 rounded-lg text-sm text-white/70">
                Отмена
              </button>
              <button onClick={saveSize} disabled={savingSize}
                className="flex-1 px-4 py-2 bg-cyan-500 hover:bg-cyan-400 disabled:opacity-40 text-black font-semibold rounded-lg text-sm flex items-center justify-center gap-2" data-testid="skin-size-apply">
                <Check className="w-4 h-4" /> {savingSize ? 'Сохранение…' : 'Применить'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
