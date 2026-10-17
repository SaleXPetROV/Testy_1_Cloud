/**
 * CityPassPage — seasonal pass (backend/city_pass.py).
 * Season header + level/XP, premium purchase (real balance), the 30 levels with
 * a free reward on every level and premium extras on 1/5/10/15/20/25/30.
 * A reward is taken only by pressing «Забрать» once its level is reached.
 * Rewards are items (boosters) shown later on Resources → «Усилители».
 */
import { onProgress } from '@/lib/progressBus';
import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { toast } from 'sonner';
import { Ticket, Crown, Lock, Check, Gift, Clock, Sparkles, X } from 'lucide-react';
import Sidebar from '@/components/Sidebar';
import PageHeader from '@/components/PageHeader';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { useLanguage } from '@/context/LanguageContext';
import { useTranslation } from '@/lib/translations';
import { getResource } from '@/lib/resourceConfig';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api/pass`;
const auth = () => ({ headers: { Authorization: `Bearer ${localStorage.getItem('token') || localStorage.getItem('ton_city_token')}` } });

const fmtCity = (v) => Number(v || 0).toLocaleString('ru-RU', { maximumFractionDigits: 2 });

const XP_LABEL = {
  daily_goal: 'leagueActDailyGoal', weekly_goal: 'leagueActWeeklyGoal', shift_start: 'leagueActShift',
  repair: 'leagueActRepair', sale_per_0_01_ton: 'leagueActSale', streak_day: 'leagueActStreak', league_top: 'passXpLeagueTop',
};

export function rewardLabel(r, t, lang) {
  const n = r.count > 1 ? ` ×${r.count}` : '';
  switch (r.type) {
    case 'auto_shift': return { icon: '🔁', text: (t('passRwAutoShift') || 'Auto-shift {h}h').replace('{h}', r.hours) + n };
    case 'warehouse_guard': return { icon: '🛡️', text: (t('passRwGuard') || 'Warehouse guard {h}h').replace('{h}', r.hours) + n };
    case 'repair_all': return { icon: '🔧', text: (t('passRwRepair') || 'Repair all businesses') + n };
    case 'streak_shield': return { icon: '🔰', text: (t('passRwShield') || 'Streak shield') + n };
    case 't3': {
      const res = getResource(r.resource, lang);
      return { icon: res?.icon || '💎', text: `${res?.name || r.resource}${n}`, sub: t('passRwT3Note') };
    }
    default: return { icon: '🎁', text: r.type };
  }
}

function ClaimState({ cell, onClaim, busy, t, premium }) {
  const st = cell.state;
  if (st === 'claimable') return (
    <Button size="sm" className={`h-7 px-3 text-[11px] font-bold ${premium ? 'bg-yellow-400 hover:bg-yellow-300' : 'bg-emerald-500 hover:bg-emerald-400'} text-black`} disabled={busy} onClick={onClaim}>
      <Gift className="w-3 h-3 mr-1" />{t('passClaim')}
    </Button>
  );
  if (st === 'claimed') return <span className="text-[11px] text-emerald-400 flex items-center gap-1"><Check className="w-3.5 h-3.5" />{t('passClaimed')}</span>;
  if (st === 'need_premium') return <span className="text-[11px] text-yellow-300/90 flex items-center gap-1"><Crown className="w-3.5 h-3.5" />{t('passNeedPremium')}</span>;
  return <span className="text-[11px] text-white/35 flex items-center gap-1"><Lock className="w-3.5 h-3.5" />{t('passLocked')}</span>;
}

function RewardLine({ rewards, t, lang, big }) {
  return (
    <div className="flex items-center gap-2.5 min-w-0">
      <div className={`flex-shrink-0 rounded-xl bg-black/30 border border-white/10 flex items-center justify-center ${big ? 'w-12 h-12 text-2xl' : 'w-10 h-10 text-xl'}`}>
        {rewardLabel(rewards[0], t, lang).icon}
      </div>
      <div className="min-w-0 space-y-0.5">
        {rewards.map((r, i) => {
          const l = rewardLabel(r, t, lang);
          return <div key={i} className={`text-white leading-tight truncate ${big ? 'text-[13px] font-semibold' : 'text-xs'}`}>{i > 0 ? `${l.icon} ` : ''}{l.text}</div>;
        })}
      </div>
    </div>
  );
}

/** One level on the road: free reward always, premium section only on premium levels. */
function LevelCard({ row, reached, current, isLast, t, lang, busy, onClaim }) {
  const prem = row.premium;
  const milestone = !!prem;
  const free = row.free;
  const done = free && free.state === 'claimed' && (!prem || prem.state === 'claimed' || prem.state === 'need_premium');
  return (
    <div className="flex gap-3" data-testid={`pass-level-${row.level}`}>
      {/* rail */}
      <div className="relative w-10 flex-shrink-0 flex flex-col items-center">
        <div className={`absolute top-0 bottom-0 w-1 ${reached ? 'bg-gradient-to-b from-indigo-400 to-indigo-500' : 'bg-white/10'} ${isLast ? 'h-1/2' : ''}`} />
        <div className={`relative z-10 mt-3 w-10 h-10 rounded-full flex flex-col items-center justify-center text-xs font-extrabold border-2 ${
          current ? 'bg-yellow-400 text-black border-yellow-200 shadow-[0_0_18px_rgba(250,204,21,0.8)] animate-pulse'
            : reached ? 'bg-indigo-500 text-white border-indigo-300 shadow-[0_0_12px_rgba(129,140,248,0.6)]'
              : 'bg-[#0b0b12] text-white/50 border-white/15'}`}>
          {row.level}
        </div>
        <span className="relative z-10 mt-0.5 text-[8px] text-white/45">{row.xp_cost} XP</span>
      </div>
      {/* card */}
      <div className={`flex-1 min-w-0 my-1.5 rounded-2xl border overflow-hidden ${milestone
        ? 'border-yellow-400/40 bg-gradient-to-br from-yellow-400/10 via-white/[0.03] to-indigo-500/10 shadow-[0_0_24px_rgba(250,204,21,0.08)]'
        : 'border-white/10 bg-white/[0.04]'} ${done ? 'opacity-60' : ''}`}>
        {free && (
          <div className="flex items-center justify-between gap-2 p-2.5">
            <RewardLine rewards={free.rewards} t={t} lang={lang} big={milestone} />
            <div className="flex-shrink-0"><ClaimState cell={free} busy={busy} t={t} onClaim={() => onClaim(row.level, 'free')} /></div>
          </div>
        )}
        {prem && (
          <div className="flex items-center justify-between gap-2 px-2.5 py-2 border-t border-yellow-400/25 bg-yellow-400/[0.07]">
            <div className="min-w-0">
              <div className="text-[9px] font-extrabold tracking-widest text-yellow-300 flex items-center gap-1 mb-1"><Crown className="w-3 h-3" />{t('passTrackPremium')}</div>
              <RewardLine rewards={prem.rewards} t={t} lang={lang} />
            </div>
            <div className="flex-shrink-0"><ClaimState cell={prem} premium busy={busy} t={t} onClaim={() => onClaim(row.level, 'premium')} /></div>
          </div>
        )}
      </div>
    </div>
  );
}

export default function CityPassPage({ user, refreshBalance }) {
  const navigate = useNavigate();
  const { language: lang } = useLanguage();
  const { t } = useTranslation(lang);
  const [d, setD] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try { const r = await axios.get(`${API}/me`, auth()); setD(r.data); }
    catch (e) { toast.error(e?.response?.data?.detail || 'Error'); }
  }, []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => onProgress(() => load()), []); // eslint-disable-line react-hooks/exhaustive-deps

  const call = async (fn, ok) => {
    setBusy(true);
    try { await fn(); toast.success(ok); await load(); refreshBalance && refreshBalance(); }
    catch (e) { toast.error(e?.response?.data?.detail || 'Error'); }
    finally { setBusy(false); }
  };
  const claim = (level, track) => call(() => axios.post(`${API}/claim`, { level, track }, auth()), t('passGotIt'));
  const claimAll = () => call(() => axios.post(`${API}/claim-all`, {}, auth()), t('passGotIt'));
  const buy = () => {
    if (!window.confirm((t('passBuyConfirm') || 'Buy premium for {p} $CITY?').replace('{p}', fmtCity(d.premium_price_city)))) return;
    (async () => {
      setBusy(true);
      try {
        const r = await axios.post(`${API}/premium`, {}, auth());
        const n = (r.data.unlocked_levels || []).length;
        toast.success(n > 0
          ? (t('passPremiumOnN') || 'Premium is on: {n} rewards are ready — press «Claim all»').replace('{n}', n)
          : t('passPremiumOn'), { duration: 6000 });
        toast.info(t('pass_paid_real'));                     // paid from the REAL balance (bonus can't be used)
        await load();
        refreshBalance && refreshBalance();
        window.scrollTo && window.scrollTo({ top: 0, behavior: 'smooth' });
      } catch (e) {
        const det = e?.response?.data?.detail;
        // not enough REAL balance: say it in the player's language
        if (e?.response?.status === 400 && /баланс|balance/i.test(String(det || ''))) toast.error(t('pass_needs_real'));
        else toast.error(det || 'Error');
      }
      finally { setBusy(false); }
    })();
  };

  const daysLeft = d ? Math.max(0, Math.ceil((new Date(d.ends_at) - Date.now()) / 86400000)) : 0;

  return (
    <div className="flex h-screen bg-void">
      <Sidebar user={user} refreshBalance={refreshBalance} />
      <div className="flex-1 overflow-hidden lg:ml-16">
        <ScrollArea className="h-full">
          <div className="p-4 lg:px-6 lg:pt-2 lg:pb-24 pt-0 pb-28 space-y-4 max-w-3xl mx-auto w-full min-w-0">
            <PageHeader icon={<Ticket className="w-6 h-6 text-indigo-300" />} title="City Pass" subtitle={d?.season_name || ''}
              closeButton={<Button variant="outline" size="icon" className="border-white/10 h-8 w-8 sm:h-10 sm:w-10" title={t('page_close')} aria-label={t('page_close')}
                  data-testid="page-close-btn" onClick={() => (window.history.length > 1 ? navigate(-1) : navigate('/my-businesses'))}>
                  <X className="w-4 h-4" />
                </Button>} />
            {!d ? <div className="text-center text-text-muted py-10">…</div> : !d.enabled ? (
              <div className="text-center text-text-muted py-10">{t('passDisabled')}</div>
            ) : (
              <>
                <Card className="glass-panel border-indigo-400/30 bg-gradient-to-br from-indigo-500/15 to-purple-500/10" data-testid="pass-header">
                  <CardContent className="p-4 space-y-3">
                    <div className="flex items-center gap-3">
                      <div className="w-14 h-14 rounded-2xl bg-indigo-500/30 border border-indigo-300/40 flex flex-col items-center justify-center">
                        <span className="text-[9px] text-white/70">LV</span>
                        <span className="text-xl font-extrabold text-white leading-none">{d.level}</span>
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex justify-between text-xs text-white/80">
                          <span>{d.level < d.levels ? `${d.xp_in_level} / ${d.xp_per_level} XP` : t('passMaxLevel')}</span>
                          <span className="flex items-center gap-1"><Clock className="w-3 h-3" />{(t('passDaysLeft') || '{n} days left').replace('{n}', daysLeft)}</span>
                        </div>
                        <div className="h-2 mt-1 rounded-full bg-black/30 overflow-hidden">
                          <div className="h-full bg-gradient-to-r from-yellow-300 to-amber-400" style={{ width: `${Math.min(100, (d.xp_in_level / d.xp_per_level) * 100)}%` }} />
                        </div>
                      </div>
                    </div>
                    {d.claimable > 0 && (
                      <Button className="w-full bg-emerald-500 hover:bg-emerald-400 text-black font-bold" disabled={busy} onClick={claimAll} data-testid="pass-claim-all">
                        <Gift className="w-4 h-4 mr-1.5" />{(t('passClaimAll') || 'Claim all ({n})').replace('{n}', d.claimable)}
                      </Button>
                    )}
                  </CardContent>
                </Card>

                <Card className={`glass-panel ${d.premium ? 'border-yellow-400/40' : 'border-yellow-400/25'}`} data-testid="pass-premium">
                  <CardContent className="p-4 flex items-center gap-3">
                    <Crown className="w-8 h-8 text-yellow-300 flex-shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-bold text-white">{d.premium ? t('passPremiumActive') : t('passPremiumTitle')}</div>
                      <div className="text-[11px] text-text-muted">{t('passPremiumDesc')}</div>
                    </div>
                    {!d.premium && d.premium_price_ton && (
                      <Button className="bg-yellow-400 hover:bg-yellow-300 text-black font-bold" disabled={busy} onClick={buy} data-testid="pass-buy-premium">
                        {fmtCity(d.premium_price_city)} $CITY
                      </Button>
                    )}
                    {!d.premium && !d.premium_price_ton && (
                      <span className="text-[11px] text-yellow-300/80 font-semibold" data-testid="pass-premium-soon">{t('passPremiumSoon')}</span>
                    )}
                  </CardContent>
                </Card>

                <div className="space-y-1" data-testid="pass-levels">
                  {[0, 1, 2].map((tier) => {
                    const per = Math.ceil(d.levels / 3);
                    const rows = d.rows.slice(tier * per, (tier + 1) * per);
                    if (!rows.length) return null;
                    return (
                      <div key={tier}>
                        <div className="flex items-center gap-2 mt-3 mb-1 px-1">
                          <span className="text-[11px] font-extrabold tracking-wider text-indigo-200 uppercase">
                            {(t('passTier') || 'Levels {a}–{b}').replace('{a}', rows[0].level).replace('{b}', rows[rows.length - 1].level)}
                          </span>
                          <span className="text-[10px] text-white/45">· {rows[0].xp_cost} XP</span>
                          <span className="flex-1 h-px bg-white/10" />
                        </div>
                        {rows.map((row) => (
                          <LevelCard key={row.level} row={row} reached={row.level <= d.level} current={row.level === d.level + 1}
                            isLast={row.level === d.levels} t={t} lang={lang} busy={busy} onClaim={claim} />
                        ))}
                      </div>
                    );
                  })}
                </div>

                <Card className="glass-panel border-white/10">
                  <CardContent className="p-4 space-y-2">
                    <div className="text-sm font-bold text-white flex items-center gap-1.5"><Sparkles className="w-4 h-4 text-yellow-300" />{t('passHowXp')}</div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5 text-xs">
                      {Object.entries(d.xp_table).filter(([k]) => k !== 'daily_goal' && k !== 'weekly_goal').map(([k, v]) => v > 0 && (
                        <div key={k} className="flex justify-between rounded-lg bg-white/5 px-2.5 py-1.5">
                          <span className="text-white/80">{t(XP_LABEL[k])}</span><span className="text-yellow-300 font-semibold">+{v} XP</span>
                        </div>
                      ))}
                    </div>
                    <div className="flex justify-between rounded-lg bg-white/5 px-2.5 py-1.5 text-xs" data-testid="pass-xp-quests">
                      <span className="text-white/80">{t('passXpQuests')}</span><span className="text-yellow-300 font-semibold">{t('passXpAsOnCard')}</span>
                    </div>
                    <p className="text-[11px] text-text-muted">{t('passXpNoteNoCap')}</p>
                    <Button variant="outline" size="sm" className="text-xs" onClick={() => navigate('/resources?tab=boosters')}>{t('passOpenBoosters')}</Button>
                  </CardContent>
                </Card>
              </>
            )}
          </div>
        </ScrollArea>
      </div>
    </div>
  );
}
