/** The running mini-game event as a side button — same look and size as «Задания».
 *  Shown only while the event runs; the badge = chests still possible today (or attempts, if the admin limits games);
 *  the dot = an unopened chest or an available booster waits in «Награды». */
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
  const me = ev.me || null;
  const left = !me ? null : (me.attempts_left ?? Math.max(0, (ev.chests_per_day || 0) - (me.chests_today || 0)));
  const dot = !!me && (me.unopened > 0 || me.boosters_available > 0);
  return (
    <button type="button" onClick={() => navigate('/minigames/sorter')} data-testid="biz-side-game"
      className={`relative w-14 h-14 sm:w-16 sm:h-16 rounded-xl bg-gradient-to-b from-amber-400/20 to-orange-500/10 border border-amber-400/40 flex flex-col items-center justify-center gap-0.5 text-amber-300 hover:brightness-110 active:scale-95 transition-all ${left > 0 ? 'tasks-calm-pulse' : ''}`}
      aria-label={t('mg_sorter_title')}>
      {left > 0 && (
        <span className="absolute -top-1.5 -right-1.5 min-w-[18px] h-[18px] px-1 rounded-full bg-amber-400 text-black text-[10px] font-bold leading-[18px] text-center shadow-[0_0_6px_rgba(251,191,36,0.6)]"
          data-testid="biz-side-game-badge">{left}</span>
      )}
      {dot && <span className="absolute -bottom-1 -right-1 w-3 h-3 rounded-full bg-fuchsia-400 border border-black shadow-[0_0_6px_rgba(232,121,249,0.8)]" data-testid="biz-side-game-dot" />}
      <Gamepad2 className="w-5 h-5" />
      <span className="text-[8px] sm:text-[9px] font-bold uppercase tracking-wide text-center leading-tight">{t('mg_side_label')}</span>
    </button>
  );
}
