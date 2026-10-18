/** The running mini-game event as a side button — same look and size as «Задания».
 *  Shown only while the event runs. Chests open by themselves, so there is no «unopened» badge. */
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Gamepad2 } from 'lucide-react';
import { useLanguage } from '@/context/LanguageContext';
import { useTranslation } from '@/lib/translations';
import { onProgress } from '@/lib/progressBus';

const API = `${process.env.REACT_APP_BACKEND_URL || ''}/api`;

export default function EventBanner() {
  const navigate = useNavigate();
  const { language: lang } = useLanguage();
  const { t } = useTranslation(lang);
  const [ev, setEv] = useState(null);
  useEffect(() => {
    const load = () => {
      const tok = localStorage.getItem('token') || localStorage.getItem('ton_city_token');
      fetch(`${API}/minigames/event`, { headers: tok ? { Authorization: `Bearer ${tok}` } : {} })
        .then((r) => (r.ok ? r.json() : null)).then(setEv).catch(() => {});
    };
    load();
    return onProgress(load);
  }, []);
  if (!ev || !ev.active) return null;
  return (
    <button type="button" onClick={() => navigate('/minigames/sorter')} data-testid="biz-side-game"
      className={`relative w-14 h-14 sm:w-16 sm:h-16 rounded-xl bg-gradient-to-b from-amber-400/20 to-orange-500/10 border border-amber-400/40 flex flex-col items-center justify-center gap-0.5 text-amber-300 hover:brightness-110 active:scale-95 transition-all`}
      aria-label={t('mg_sorter_title')}>
      <Gamepad2 className="w-5 h-5" />
      <span className="text-[8px] sm:text-[9px] font-bold uppercase tracking-wide text-center leading-tight">{t('mg_side_label')}</span>
    </button>
  );
}
