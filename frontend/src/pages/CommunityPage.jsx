/**
 * CommunityPage («Общение») — weekly leagues (backend/leagues.py) + a way to the chat.
 *
 * League view: division, time left in the week, three ratings inside the
 * player's group (activity points / units sold / TON sold — the admin can
 * switch each off), promotion and relegation zones, how points are earned,
 * rewards per place, and the last weeks' results.
 * Labels: translationsExtra (en/ru by hand, other languages via LibreTranslate).
 */
import { onProgress } from '@/lib/progressBus';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { toast } from 'sonner';
import { MessagesSquare, Trophy, Clock, ArrowUp, ArrowDown, Shield, MessageCircle } from 'lucide-react';
import Sidebar from '@/components/Sidebar';
import PageHeader from '@/components/PageHeader';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { useLanguage } from '@/context/LanguageContext';
import { useTranslation } from '@/lib/translations';
import AllianceView from '@/components/alliances/AllianceView';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api`;
const getToken = () => localStorage.getItem('token') || localStorage.getItem('ton_city_token');
const auth = () => ({ headers: { Authorization: `Bearer ${getToken()}` } });

const DIV_STYLE = [
  { key: 'leagueDivBronze', color: 'text-amber-600', ring: 'border-amber-600/50', emoji: '🥉' },
  { key: 'leagueDivSilver', color: 'text-slate-300', ring: 'border-slate-300/50', emoji: '🥈' },
  { key: 'leagueDivGold', color: 'text-yellow-400', ring: 'border-yellow-400/50', emoji: '🥇' },
  { key: 'leagueDivPlatinum', color: 'text-cyan-300', ring: 'border-cyan-300/50', emoji: '💠' },
  { key: 'leagueDivDiamond', color: 'text-fuchsia-300', ring: 'border-fuchsia-300/50', emoji: '💎' },
];
const BOARD_LABEL = { points: 'leagueBoardPoints', units_sold: 'leagueBoardUnits', ton_sold: 'leagueBoardTon' };
const ACTION_LABEL = {
  daily_goal: 'leagueActDailyGoal', weekly_goal: 'leagueActWeeklyGoal', shift_start: 'leagueActShift',
  repair: 'leagueActRepair', sale_per_0_01_ton: 'leagueActSale', streak_day: 'leagueActStreak',
};

function useCountdown(iso, t) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const id = setInterval(() => setNow(Date.now()), 30000); return () => clearInterval(id); }, []);
  if (!iso) return '';
  const ms = Math.max(0, new Date(iso).getTime() - now);
  const d = Math.floor(ms / 86400000), h = Math.floor((ms % 86400000) / 3600000), m = Math.floor((ms % 3600000) / 60000);
  const [ud, uh, um] = [t('unitDay') || 'd', t('unitHour') || 'h', t('unitMin') || 'm'];
  return d > 0 ? `${d}${ud} ${h}${uh}` : `${h}${uh} ${m}${um}`;
}

const fmtValue = (board, v) => (board === 'ton_sold' ? `${Number(v).toFixed(3)} TON` : Math.round(v).toLocaleString());

export default function CommunityPage({ user, refreshBalance, initialTab }) {
  const navigate = useNavigate();
  const { language: lang } = useLanguage();
  const { t } = useTranslation(lang);
  const [tab, setTab] = useState(() => initialTab || (new URLSearchParams(window.location.search).get('tab') === 'alliance' ? 'alliance' : 'leagues'));
  const [data, setData] = useState(null);
  const [board, setBoard] = useState('points');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/leagues/me`, auth());
      setData(r.data);
      setBoard((b) => (r.data.boards && r.data.boards[b] ? b : Object.keys(r.data.boards || {})[0] || 'points'));
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Error');
    }
  }, []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => onProgress(() => load()), [load]);   // league points refresh right after an action

  const join = async () => {
    setBusy(true);
    try { const r = await axios.post(`${API}/leagues/join`, {}, auth()); setData(r.data); }
    catch (e) { toast.error(e?.response?.data?.detail || 'Error'); }
    finally { setBusy(false); }
  };

  const left = useCountdown(data?.ends_at, t);
  const div = DIV_STYLE[data?.division || 0];
  const rows = (data?.standings || {})[board] || [];
  const isPromoBoard = board === data?.promotion_board;
  const rewards = ((data?.boards || {})[board] || {}).rewards_city || [];
  const zone = useMemo(() => (i, n) => {
    if (!isPromoBoard || !data) return '';
    if (i < data.promote_count && data.division < 4) return 'up';
    if (i >= n - data.relegate_count && n > data.promote_count && data.division > 0) return 'down';
    return '';
  }, [isPromoBoard, data]);

  return (
    <div className="flex h-screen bg-void">
      <Sidebar user={user} refreshBalance={refreshBalance} />
      <div className="flex-1 overflow-hidden lg:ml-16">
        <ScrollArea className="h-full">
          <div className="p-4 lg:px-6 lg:pt-2 lg:pb-24 pt-0 pb-28 space-y-4 max-w-3xl mx-auto w-full min-w-0">
            <PageHeader icon={<MessagesSquare className="w-6 h-6 text-cyber-cyan" />} title={t('communityTitle')} subtitle={t('communitySubtitle')} />

            {/* the chat moved to the «Чат» button on the «Бизнесы» page */}
            <div className="grid grid-cols-2 gap-2" role="tablist">
              <button type="button" role="tab" aria-selected={tab === 'leagues'} onClick={() => setTab('leagues')}
                className={`flex items-center justify-center gap-2 rounded-xl border px-3 py-3 text-sm font-bold uppercase tracking-wide ${tab === 'leagues' ? 'border-yellow-400/60 bg-yellow-400/15 text-yellow-300' : 'border-white/10 text-white/60'}`} data-testid="community-tab-leagues">
                <Trophy className="w-4 h-4" />{t('communityTabLeagues')}
              </button>
              <button type="button" role="tab" aria-selected={tab === 'alliance'} onClick={() => setTab('alliance')}
                className={`flex items-center justify-center gap-2 rounded-xl border px-3 py-3 text-sm font-bold uppercase tracking-wide ${tab === 'alliance' ? 'border-fuchsia-400/60 bg-fuchsia-400/15 text-fuchsia-200' : 'border-white/10 text-white/60'}`} data-testid="community-tab-alliance">
                <Shield className="w-4 h-4" />{t('al_tab')}
              </button>
            </div>

            {tab === 'alliance' ? <AllianceView user={user} lang={lang} t={t} refreshUser={refreshBalance} /> : !data ? <div className="text-center text-text-muted py-10">…</div> : !data.enabled ? (
              <div className="text-center text-text-muted py-10" data-testid="league-disabled">{t('leagueDisabled')}</div>
            ) : (
              <>
                {/* division + countdown */}
                <Card className={`glass-panel border ${div.ring}`} data-testid="league-header">
                  <CardContent className="p-4 flex items-center gap-4">
                    <div className="text-4xl">{div.emoji}</div>
                    <div className="flex-1 min-w-0">
                      <div className="text-[11px] uppercase tracking-wide text-text-muted">{t('leagueDivision')}</div>
                      <div className={`text-xl font-bold ${div.color}`}>{t(div.key)}</div>
                      <div className="text-[11px] text-text-muted flex items-center gap-1 mt-0.5"><Clock className="w-3 h-3" />{t('leagueEndsIn')} {left}</div>
                    </div>
                    {data.me && (
                      <div className="text-right">
                        <div className="text-[11px] text-text-muted">{t(BOARD_LABEL[data.promotion_board])}</div>
                        <div className="text-2xl font-bold text-white">#{data.me.ranks[data.promotion_board]}</div>
                      </div>
                    )}
                  </CardContent>
                </Card>

                {!data.joined ? (
                  <Card className="glass-panel border-white/10">
                    <CardContent className="p-4 text-center space-y-3">
                      <p className="text-sm text-text-muted">{t('leagueJoinHint')}</p>
                      <Button onClick={join} disabled={busy} data-testid="league-join">{t('leagueJoin')}</Button>
                    </CardContent>
                  </Card>
                ) : (
                  <>
                    {/* ratings */}
                    <div className="flex gap-1.5 overflow-x-auto" data-testid="league-boards">
                      {Object.keys(data.boards).map((b) => (
                        <button key={b} type="button" onClick={() => setBoard(b)} data-testid={`league-board-${b}`}
                          className={`flex-1 whitespace-nowrap rounded-lg border px-3 py-2 text-xs font-semibold ${board === b ? 'border-cyber-cyan/60 bg-cyber-cyan/15 text-cyber-cyan' : 'border-white/10 bg-white/5 text-white/70'}`}>
                          {t(BOARD_LABEL[b])}{data.me ? ` · #${data.me.ranks[b]}` : ''}
                        </button>
                      ))}
                    </div>

                    <Card className="glass-panel border-white/10">
                      <CardContent className="p-2 sm:p-3">
                        {isPromoBoard && (
                          <div className="flex gap-3 text-[11px] text-text-muted px-1 pb-2">
                            <span className="flex items-center gap-1 text-emerald-400"><ArrowUp className="w-3 h-3" />{t('leaguePromoZone')}</span>
                            <span className="flex items-center gap-1 text-red-400"><ArrowDown className="w-3 h-3" />{t('leagueRelegZone')}</span>
                          </div>
                        )}
                        <div className="divide-y divide-white/5" data-testid="league-table">
                          {rows.map((r, i) => {
                            const z = zone(i, rows.length);
                            const reward = rewards[i];
                            return (
                              <div key={r.user_id} className={`flex items-center gap-2 px-2 py-2 text-sm ${r.me ? 'bg-yellow-400/10 rounded-lg' : ''}`} data-testid={r.me ? 'league-row-me' : undefined}>
                                <span className={`w-7 text-center font-bold ${z === 'up' ? 'text-emerald-400' : z === 'down' ? 'text-red-400' : 'text-white/60'}`}>{r.rank}</span>
                                <span className={`flex-1 truncate ${r.me ? 'text-yellow-300 font-semibold' : 'text-white'}`}>{r.name}{r.me ? ` (${t('leagueYou')})` : ''}</span>
                                {reward > 0 && <span className="text-[10px] text-yellow-300/80">+{reward}</span>}
                                <span className="w-24 text-right font-mono text-white/90">{fmtValue(board, r.value)}</span>
                              </div>
                            );
                          })}
                        </div>
                      </CardContent>
                    </Card>
                  </>
                )}

                {/* how points are earned */}
                <Card className="glass-panel border-white/10">
                  <CardContent className="p-4 space-y-2">
                    <div className="text-sm font-bold text-white">{t('leagueHowPoints')}</div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5 text-xs">
                      {Object.entries(data.points_table).map(([k, v]) => v > 0 && (
                        <div key={k} className="flex justify-between rounded-lg bg-white/5 px-2.5 py-1.5">
                          <span className="text-white/80">{t(ACTION_LABEL[k])}</span>
                          <span className="text-cyber-cyan font-semibold">+{v}</span>
                        </div>
                      ))}
                    </div>
                    <p className="text-[11px] text-text-muted">{t('leagueDailyCap').replace('{n}', data.daily_points_cap)} {t('leagueSalesNote')}</p>
                    {data.shield_top_n > 0 && <p className="text-[11px] text-text-muted flex items-center gap-1"><Shield className="w-3 h-3" />{t('leagueShieldNote').replace('{n}', data.shield_top_n)}</p>}
                  </CardContent>
                </Card>

                {data.history?.length > 0 && (
                  <Card className="glass-panel border-white/10">
                    <CardContent className="p-4 space-y-1.5" data-testid="league-history">
                      <div className="text-sm font-bold text-white">{t('leagueHistory')}</div>
                      {data.history.map((h) => (
                        <div key={h.week} className="flex justify-between text-xs text-white/80">
                          <span>{h.week} · {t(DIV_STYLE[h.division].key)}</span>
                          <span>
                            {h.move === 'up' ? '⬆️' : h.move === 'down' ? '⬇️' : '•'} #{(h.ranks || {})[data.promotion_board] ?? '—'}
                            {h.reward_city > 0 ? ` · +${h.reward_city} $CITY` : ''}
                          </span>
                        </div>
                      ))}
                    </CardContent>
                  </Card>
                )}
              </>
            )}
          </div>
        </ScrollArea>
      </div>
    </div>
  );
}
