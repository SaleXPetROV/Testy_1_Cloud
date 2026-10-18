/**
 * BoostersPanel — Resources → «Усилители» (backend/boosters.py).
 * Active effects (auto-shift, warehouse guard, tier-3 buffs) with time left,
 * and the player's non-tradable items with an «Активировать» button.
 * Tier-3 items (`<res>_tutorial`) are activated through the existing
 * /api/resource-buffs/activate endpoint (max 2 tier-3 buffs at once).
 */
import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { toast } from 'sonner';
import { Zap } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { getResource } from '@/lib/resourceConfig';
import { buffTexts } from '@/lib/buffText';
import { fill, fmtLeft } from '@/lib/translationsMore';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const auth = () => ({ headers: { Authorization: `Bearer ${localStorage.getItem('token') || localStorage.getItem('ton_city_token')}` } });

const left = (iso, t) => fmtLeft(iso, t);          // «2д 5ч 13мин»: days, hours AND minutes

export default function BoostersPanel({ t, lang, onChanged }) {
  const [d, setD] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try { const r = await axios.get(`${BACKEND_URL}/api/boosters`, auth()); setD(r.data); }
    catch { setD({ items: [], t3_items: [], active: [], streak_shields: 0 }); }
  }, []);
  useEffect(() => { load(); }, [load]);
  const [, setTick] = useState(0);                     // re-render every 30 s: the minutes left keep moving
  useEffect(() => { const id = setInterval(() => setTick((x) => x + 1), 30000); return () => clearInterval(id); }, []);

  const activate = async (url) => {
    setBusy(true);
    try { await axios.post(url, {}, auth()); toast.success(t('boostActivated')); await load(); onChanged && onChanged(); }
    catch (e) {
      const det = e?.response?.data?.detail;
      toast.error(det === 'tutorial_buff_needs_business' ? t('boostNeedsBusiness') : det === 'boosters_limit' ? t('boostMaxTwo') : (det || 'Error'));
    } finally { setBusy(false); }
  };

  if (!d) return <div className="text-center text-text-muted py-8">…</div>;
  const label = (kind, hours) => ({
    auto_shift: { icon: '🔁', title: (t('passRwAutoShift') || '').replace('{h}', hours), desc: t('boostAutoShiftDesc') },
    warehouse_guard: { icon: '🛡️', title: (t('passRwGuard') || '').replace('{h}', hours), desc: t('boostGuardDesc') },
    repair_all: { icon: '🔧', title: t('passRwRepair'), desc: t('boostRepairDesc') },
    xp_x2: { icon: '✨', title: `×2 XP · ${(t('bs_hours') || '{n} h').replace('{n}', hours)}`, desc: t('bs_eff_xp_x2') },
  }[kind] || { icon: '🎁', title: kind, desc: '' });
  const activeName = (a) => a.kind === 'auto_shift' ? `🔁 ${t('boostAutoShiftOn')}`
    : a.kind === 'warehouse_guard' ? `🛡️ ${t('boostGuardOn')}`
    : a.kind === 'xp_x2' ? `✨ ${t('bs_eff_xp_x2')}`
      : (() => { const x = buffTexts(a, t); return `${a.icon || '💎'} ${x.name}${x.effect ? ` · ${x.effect}` : ''}`; })();
  const empty = !d.items.length && !d.t3_items.length;
  // not more than 2 effects at once: boosters and tier-3 buffs together (backend core/effects.py)
  const full = d.active.length >= 2;
  const running = (kind) => d.active.some((a) => a.kind === kind);

  return (
    <div className="space-y-4" data-testid="boosters-panel">
      <Card className="glass-panel border-white/10">
        <CardContent className="p-3 sm:p-4 space-y-2">
          <div className="text-sm font-bold text-white flex items-center gap-1.5"><Zap className="w-4 h-4 text-yellow-300" />{t('boostActiveTitle')}</div>
          {d.active.length === 0 && d.streak_shields === 0 && <div className="text-xs text-text-muted">{t('boostNoneActive')}</div>}
          {d.active.map((a, i) => (
            <div key={i} className="flex justify-between items-center rounded-lg bg-emerald-500/10 border border-emerald-400/20 px-3 py-2 text-xs" data-testid={`boost-active-${a.kind}`}>
              <span className="text-white">{activeName(a)}</span>
              <span className="text-emerald-300 font-mono">{left(a.until, t)}</span>
            </div>
          ))}
          {d.streak_shields > 0 && (
            <div className="flex justify-between items-center rounded-lg bg-cyan-500/10 border border-cyan-400/20 px-3 py-2 text-xs">
              <span className="text-white">🔰 {t('passRwShield')}</span><span className="text-cyan-300 font-bold">×{d.streak_shields}</span>
            </div>
          )}
        </CardContent>
      </Card>

      <div className="space-y-2" data-testid="boosters-items">
        {empty && <div className="text-center text-text-muted text-sm py-6">{t('boostEmpty')}</div>}
        {d.items.map((it) => {
          const l = label(it.kind, it.hours);
          return (
            <div key={it.key} className="flex items-center gap-3 rounded-xl border border-white/10 bg-white/5 p-3" data-testid={`boost-item-${it.key}`}>
              <div className="text-2xl">{l.icon}</div>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-semibold text-white">{l.title} <span className="text-text-muted font-normal">×{it.count}</span></div>
                <div className="text-[11px] text-text-muted">{l.desc}</div>
              </div>
              <Button size="sm" disabled={busy || (full && it.kind !== 'repair_all' && !running(it.kind))} title={full ? t('boostMaxTwo') : ''}
                onClick={() => activate(`${BACKEND_URL}/api/boosters/activate/${it.key}`)} data-testid={`boost-activate-${it.key}`}>{t('boostActivate')}</Button>
            </div>
          );
        })}
        {d.t3_items.map((it) => {
          const res = getResource(it.resource, lang);
          return (
            <div key={it.key} className="flex items-center gap-3 rounded-xl res-legendary p-3" data-testid={`boost-item-${it.key}`}>
              <div className="text-2xl">{res?.icon || it.icon || '💎'}</div>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-semibold text-white">{res?.name || it.resource} <span className="text-text-muted font-normal">×{it.count}</span></div>
                {(() => {                                   // the bonus it gives when activated (+ for how long)
                  const x = buffTexts(it, t);
                  return <div className="text-[11px] text-amber-100/90" data-testid={`boost-t3-effect-${it.key}`}>{x.name}{x.effect ? ` · ${x.effect}` : ''}{it.duration_days ? ` · ${fill(t('res_info_days'), { n: it.duration_days })}` : ''}</div>;
                })()}
              </div>
              {(() => {
                // never send a request the server is sure to refuse (no 400 in the console)
                const base = String(it.key).replace(/_tutorial$/, '');
                const act = d.active.find((a) => a.kind === 't3_buff' && String(a.resource || '').replace(/_tutorial$/, '') === base);
                if (act) return <span className="text-[11px] text-emerald-300 text-right" data-testid={`boost-active-${it.key}`}>{t('boostAlreadyActive')}</span>;
                return <Button size="sm" disabled={busy || full} title={full ? t('boostMaxTwo') : ''} onClick={() => activate(`${BACKEND_URL}/api/resource-buffs/activate/${it.key}`)} data-testid={`boost-activate-${it.key}`}>{t('boostActivate')}</Button>;
              })()}
            </div>
          );
        })}
      </div>
      {full && <div className="text-[11px] text-center text-amber-200/80" data-testid="boost-limit-note">{t('boostMaxTwo')}</div>}
    </div>
  );
}
