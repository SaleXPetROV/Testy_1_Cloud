import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Check, Palette, X, Loader2 } from 'lucide-react';
import { fetchSkinsIndex, getCachedSkinsIndex, resolveSkinUrl } from '@/lib/skins';
import { useTranslation } from '@/lib/translations';
import { useLanguage } from '@/context/LanguageContext';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api`;

// "Skins" modal title in every project language
const SKINS_TITLE = {
  en: 'Skins', ru: 'Скины', es: 'Skins', zh: '皮肤',
  fr: 'Skins', de: 'Skins', ja: 'スキン', ko: '스킨',
};
const APPLIED = {
  en: 'Skin applied', ru: 'Скин применён', es: 'Skin aplicado', zh: '皮肤已应用',
  fr: 'Skin appliqué', de: 'Skin angewendet', ja: 'スキンを適用しました', ko: '스킨 적용됨',
};

/**
 * Skin picker button + modal for a single business.
 * The button shows the currently applied skin; clicking opens the "Skins" modal
 * with all skins the player owns for this business type (3 per row).
 */
export default function SkinPicker({ business, lang = 'ru', token, onApplied }) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [skins, setSkins] = useState([]);
  const [current, setCurrent] = useState(business?.skin_group || 'standard');
  const [applying, setApplying] = useState(null);
  const [index, setIndex] = useState(getCachedSkinsIndex());

  const bizType = business?.business_type;
  const bizLevel = business?.level || 1;

  const { language: _lang } = useLanguage();
  const { t: tt } = useTranslation(_lang);
  useEffect(() => { fetchSkinsIndex().then(setIndex); }, []);
  useEffect(() => { setCurrent(business?.skin_group || 'standard'); }, [business?.skin_group]);

  const currentImg = resolveSkinUrl(index, current, bizType, bizLevel);

  const loadSkins = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/skins/my?business_type=${bizType}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      setSkins(data.skins || []);
    } catch (e) {
      toast.error('Ошибка загрузки скинов');
    } finally {
      setLoading(false);
    }
  };

  const openModal = () => { setOpen(true); loadSkins(); };

  const apply = async (groupKey) => {
    setApplying(groupKey);
    try {
      const res = await fetch(`${API}/skins/apply`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ business_id: business.id, group_key: groupKey }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || 'error');
      }
      setCurrent(groupKey);
      toast.success(APPLIED[lang] || APPLIED.en);
      try { window.dispatchEvent(new CustomEvent('gc-skin-applied', { detail: { business_id: business.id, group_key: groupKey } })); } catch (_) {}
      onApplied && onApplied(groupKey);
      setOpen(false);
    } catch (e) {
      toast.error(typeof e.message === 'string' ? e.message : 'Ошибка');
    } finally {
      setApplying(null);
    }
  };

  const title = SKINS_TITLE[lang] || SKINS_TITLE.en;

  return (
    <>
      <button
        onClick={openModal}
        title={title}
        data-testid={`skin-picker-btn-${business?.id}`}
        className="shrink-0 w-10 h-10 rounded-lg border border-cyan-400/40 bg-black/40 hover:border-cyan-300 hover:bg-cyan-500/10 transition-colors flex items-center justify-center overflow-hidden relative group"
      >
        {currentImg ? (
          <img src={currentImg} alt="skin" className="w-8 h-8 object-contain" />
        ) : (
          <Palette className="w-4 h-4 text-cyan-300" />
        )}
        <span className="absolute -bottom-0.5 -right-0.5 bg-cyan-500 rounded-full p-0.5">
          <Palette className="w-2.5 h-2.5 text-white" />
        </span>
      </button>

      {open && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/75 p-4" data-testid="skins-modal" onClick={() => setOpen(false)}>
          <div className="bg-[#12121f] border border-white/10 rounded-2xl w-full max-w-md max-h-[85vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between p-4 border-b border-white/10">
              <h3 className="text-white font-bold flex items-center gap-2">
                <Palette className="w-5 h-5 text-cyan-300" /> {title}
              </h3>
              <button onClick={() => setOpen(false)} className="p-1.5 hover:bg-white/10 rounded" data-testid="skins-modal-close">
                <X className="w-4 h-4 text-white/70" />
              </button>
            </div>
            <div className="p-4 overflow-y-auto">
              {loading ? (
                <div className="flex justify-center py-10"><Loader2 className="w-6 h-6 animate-spin text-cyan-300" /></div>
              ) : skins.length === 0 ? (
                <div className="text-center text-white/40 py-10" data-testid="skins-empty">—</div>
              ) : (
                <div className="grid grid-cols-3 gap-3" data-testid="skins-grid">
                  {skins.map((s) => {
                    const raw = s.by_level?.[String(bizLevel)] || s.by_level?.['0'] || s.image;
                    const img = raw && raw.startsWith('/api/') ? `${process.env.REACT_APP_BACKEND_URL || ''}${raw}` : raw;
                    const selected = current === s.group_key;
                    return (
                      <button
                        key={s.group_key}
                        onClick={() => apply(s.group_key)}
                        disabled={applying === s.group_key}
                        data-testid={`skin-card-${s.group_key}`}
                        className={`relative rounded-xl border-2 p-2 flex flex-col items-center gap-1 transition-all ${selected ? 'border-emerald-400 bg-emerald-500/10' : 'border-white/10 bg-white/5 hover:border-cyan-400/50'}`}
                      >
                        {selected && (
                          <span className="absolute top-1.5 right-1.5 bg-emerald-500 rounded-full p-0.5 shadow-lg shadow-emerald-500/40" data-testid={`skin-selected-${s.group_key}`}>
                            <Check className="w-3.5 h-3.5 text-white" strokeWidth={3} />
                          </span>
                        )}
                        <div className="w-full aspect-square rounded-lg bg-black/30 flex items-center justify-center overflow-hidden">
                          {img ? <img src={img} alt={s.group_name} className="w-full h-full object-contain" />
                               : <Palette className="w-6 h-6 text-white/30" />}
                        </div>
                        <span className="text-[11px] text-white/80 text-center leading-tight line-clamp-2">{s.is_standard ? (tt('skin_base') || s.group_name) : s.group_name}</span>
                        {applying === s.group_key && <Loader2 className="w-4 h-4 animate-spin text-cyan-300 absolute inset-0 m-auto" />}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
