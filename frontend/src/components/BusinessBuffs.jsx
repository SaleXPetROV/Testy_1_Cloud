/** Boosters / buffs acting on a business, with a live «осталось …» countdown. */
import { useEffect, useState } from 'react';
import { useLanguage } from '@/context/LanguageContext';
import { useTranslation } from '@/lib/translations';
import { fill } from '@/lib/translationsMore';
import { buffTexts } from '@/lib/buffText';

/** «2д 23ч» — time left until `until` (translated units). */
export function buffTimeLeft(until, t) {
  const s = Math.max(0, Math.floor((new Date(until).getTime() - Date.now()) / 1000));
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return d ? `${d}${t('buff_d')} ${h}${t('buff_h')}` : h ? `${h}${t('buff_h')} ${m}${t('buff_m')}` : `${Math.max(1, m)}${t('buff_m')}`;
}

function left(until, t) {
  const s = Math.max(0, Math.floor((new Date(until).getTime() - Date.now()) / 1000));
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  const txt = d ? `${d}${t('buff_d')} ${h}${t('buff_h')}` : h ? `${h}${t('buff_h')} ${m}${t('buff_m')}` : `${Math.max(1, m)}${t('buff_m')}`;
  return s > 0 ? fill(t('buff_left'), { t: txt }) : null;
}

export default function BusinessBuffs({ business, compact = false }) {
  const { language: lang } = useLanguage();
  const { t } = useTranslation(lang);
  const [, tick] = useState(0);
  useEffect(() => { const id = setInterval(() => tick((x) => x + 1), 30000); return () => clearInterval(id); }, []);
  const buffs = (business?.active_buffs || []).filter((b) => !b.until || new Date(b.until).getTime() > Date.now());
  if (!buffs.length) return null;
  const name = (b) => (b.kind === 'auto_shift' ? t('buff_auto_shift') : b.kind === 'warehouse_guard' ? t('buff_guard')
    : b.kind === 'business' ? (b.name || t('buff_business')) : (() => { const x = buffTexts(b, t); return x.effect ? `${x.name} · ${x.effect}` : x.name; })());
  if (compact) {
    return (
      <div className="flex flex-wrap justify-center gap-1.5" data-testid={`biz-buffs-compact-${business.id}`}>
        {buffs.map((b, i) => (
          <span key={i} className="rounded-full border border-cyan-400/30 bg-cyan-500/10 px-2 py-0.5 text-[11px] text-cyan-100" title={name(b)}>
            {b.icon} {b.until ? left(b.until, t) : name(b)}
          </span>
        ))}
      </div>
    );
  }
  return (
    <div className="rounded-xl border border-cyan-400/30 bg-cyan-500/10 p-3 space-y-1.5" data-testid={`biz-buffs-${business.id}`}>
      <div className="text-[11px] uppercase tracking-wider text-cyan-300">{t('buff_title')}</div>
      {buffs.map((b, i) => (
        <div key={i} className="flex items-center justify-between gap-2 text-sm">
          <span className="text-white">{b.icon} {name(b)}</span>
          {b.until && <span className="text-cyan-200 text-xs whitespace-nowrap">{left(b.until, t)}</span>}
        </div>
      ))}
    </div>
  );
}
