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

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const auth = () => ({ headers: { Authorization: `Bearer ${localStorage.getItem('token') || localStorage.getItem('ton_city_token')}` } });

function left(iso, t) {
  const ms = Math.max(0, new Date(iso).getTime() - Date.now());
  const d = Math.floor(ms / 86400000), h = Math.floor((ms % 86400000) / 3600000), m = Math.floor((ms % 3600000) / 60000);
  return d > 0 ? `${d}${t('unitDay')} ${h}${t('unitHour')}` : `${h}${t('unitHour')} ${m}${t('unitMin')}`;
}

export default function BoostersPanel({ t, lang, onChanged }) {
  const [d, setD] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try { const r = await axios.get(`${BACKEND_URL}/api/boosters`, auth()); setD(r.data); }
    catch { setD({ items: [], t3_items: [], active: [], streak_shields: 0 }); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const activate = async (url) => {
    setBusy(true);
    try { await axios.post(url, {}, auth()); toast.success(t('boostActivated')); await load(); onChanged && onChanged(); }
    catch (e) {
      const det = e?.response?.data?.detail;
      toast.error(det === 'tutorial_buff_needs_business' ? t('boostNeedsBusiness') : (det || 'Error'));
    } finally { setBusy(false); }
  };

  if (!d) return <div className="text-center text-text-muted py-8">…</div>;
  const label = (kind, hours) => ({
    auto_shift: { icon: '🔁', title: (t('passRwAutoShift') || '').replace('{h}', hours), desc: t('boostAutoShiftDesc') },
    warehouse_guard: { icon: '🛡️', title: (t('passRwGuard') || '').replace('{h}', hours), desc: t('boostGuardDesc') },
    repair_all: { icon: '🔧', title: t('passRwRepair'), desc: t('boostRepairDesc') },
  }[kind] || { icon: '🎁', title: kind, desc: '' });
  const activeName = (a) => a.kind === 'auto_shift' ? `🔁 ${t('boostAutoShiftOn')}`
    : a.kind === 'warehouse_guard' ? `🛡️ ${t('boostGuardOn')}`
      : (() => { const x = buffTexts(a, t); return `${a.icon || '💎'} ${x.name}${x.effect ? ` · ${x.effect}` : ''}`; })();
  const empty = !d.items.length && !d.t3_items.length;

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
              <Button size="sm" disabled={busy} onClick={() => activate(`${BACKEND_URL}/api/boosters/activate/${it.key}`)} data-testid={`boost-activate-${it.key}`}>{t('boostActivate')}</Button>
            </div>
          );
        })}
        {d.t3_items.map((it) => {
          const res = getResource(it.resource, lang);
          return (
            <div key={it.key} className="flex items-center gap-3 rounded-xl border border-fuchsia-400/20 bg-fuchsia-500/5 p-3" data-testid={`boost-item-${it.key}`}>
              <div className="text-2xl">{res?.icon || it.icon || '💎'}</div>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-semibold text-white">{res?.name || it.resource} <span className="text-text-muted font-normal">×{it.count}</span></div>
                <div className="text-[11px] text-text-muted">{t('passRwT3Note')}</div>
              </div>
              {(() => {
                // never send a request the server is sure to refuse (no 400 in the console)
                const base = String(it.key).replace(/_tutorial$/, '');
                const act = d.active.find((a) => a.kind === 't3_buff' && String(a.resource || '').replace(/_tutorial$/, '') === base);
                const full = d.active.filter((a) => a.kind === 't3_buff').length >= 2;
                if (act) return <span className="text-[11px] text-emerald-300 text-right" data-testid={`boost-active-${it.key}`}>{t('boostAlreadyActive')}</span>;
                return <Button size="sm" disabled={busy || full} title={full ? t('boostMaxTwo') : ''} onClick={() => activate(`${BACKEND_URL}/api/resource-buffs/activate/${it.key}`)} data-testid={`boost-activate-${it.key}`}>{t('boostActivate')}</Button>;
              })()}
            </div>
          );
        })}
      </div>
    </div>
  );
}
