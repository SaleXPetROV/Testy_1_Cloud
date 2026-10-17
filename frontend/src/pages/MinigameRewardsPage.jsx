/**
 * «Награды» of the mini-game promotion: event points + record with the next thresholds, rewards for points / record,
 * chests (open → animation → resources or a puzzle piece), NFT puzzles 3×3 («Собрать» only with a linked wallet),
 * boosters, list of leaders. Everything is decided by the server (backend/minigame_rewards.py).
 */
import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { toast } from 'sonner';
import { X, Gift, Puzzle, Zap, Trophy, Star, Award, Wallet, Clock } from 'lucide-react';
import { useLanguage } from '@/context/LanguageContext';
import { useTranslation } from '@/lib/translations';
import { fill } from '@/lib/translationsMore';
import { getResource } from '@/lib/resourceConfig';
import { onProgress, emitProgress } from '@/lib/progressBus';
import { mgCall, nm, imgUrl, MgLeaderboard, ChestConditions, useLinkWallet, NFT_ST_KEY, tonviewer } from '@/components/minigames/mgShared';

const TYPE_ICON = { frame: '🖼️', container: '🎁', booster: '⚡', nft: '💎' };
const fmt = (n) => Number(n || 0).toLocaleString('ru-RU');
const dt = (iso, lang) => (iso ? new Date(iso).toLocaleString(lang === 'en' ? 'en-GB' : lang, { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '');

function Progress({ value, className = 'from-amber-300 to-orange-400' }) {
  return <div className="h-2 rounded-full bg-black/40 overflow-hidden"><div className={`h-full bg-gradient-to-r ${className}`} style={{ width: `${Math.max(0, Math.min(100, value))}%` }} /></div>;
}

function NftStatus({ grant, walletLinked, net, t }) {
  const k = NFT_ST_KEY(grant, walletLinked);
  if (!k) return null;
  const color = grant.status === 'delivered' ? 'text-emerald-300' : grant.status === 'failed' ? 'text-red-300' : 'text-cyan-200';
  return (
    <div className={`text-[11px] font-semibold ${color}`} data-testid="nft-status">
      {t(k)}
      {grant.status === 'delivered' && grant.nft_address && (
        <a className="ml-2 underline text-cyan-300" href={tonviewer(grant.nft_address, net)} target="_blank" rel="noreferrer">{t('rw_tonviewer')}</a>
      )}
    </div>
  );
}

function RewardCard({ r, lang, t, d }) {
  return (
    <div className={`rounded-xl border p-3 flex gap-3 ${r.given ? 'border-emerald-400/40 bg-emerald-500/10' : 'border-white/10 bg-white/5'}`} data-testid="reward-card">
      <div className="w-12 h-12 shrink-0 rounded-xl bg-black/40 border border-white/10 flex items-center justify-center text-2xl overflow-hidden">
        {r.image_url ? <img src={imgUrl(r.image_url)} alt="" className="w-full h-full object-cover" /> : TYPE_ICON[r.type]}
      </div>
      <div className="flex-1 min-w-0 space-y-1">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="text-white font-bold text-sm truncate">{nm(r, lang)}</div>
            <div className="text-[11px] text-text-muted">{t(`rw_type_${r.type}`)} · {fill(t('rw_from_points'), { n: fmt(r.threshold) })}</div>
          </div>
          <span className={`shrink-0 text-[10px] font-bold uppercase rounded-full px-2 py-0.5 ${r.given ? 'bg-emerald-400/20 text-emerald-200' : 'bg-white/10 text-white/70'}`}>
            {r.given ? t('rw_got') : t('rw_in_progress')}
          </span>
        </div>
        {!r.given && <Progress value={r.progress} />}
        {!r.given && <div className="text-[10px] text-text-muted">{fmt(r.current)} / {fmt(r.threshold)}</div>}
        {r.type === 'nft' && r.given && (r.sold_out ? <div className="text-[11px] text-red-300">{t('rw_sold_out')}</div>
          : <NftStatus grant={r.grant} walletLinked={d.wallet_linked} net={d.nft_network} t={t} />)}
      </div>
    </div>
  );
}

function ChestCard({ c, lang, t, onOpen, opening }) {
  return (
    <div className="rounded-xl border border-amber-400/30 bg-gradient-to-b from-amber-500/10 to-black/30 p-3 flex flex-col items-center gap-2 text-center" data-testid="chest-card">
      <div className={`w-16 h-16 flex items-center justify-center text-5xl ${opening ? 'animate-[wiggle_0.5s_ease-in-out_infinite]' : ''}`}>
        {c.image_url ? <img src={imgUrl(c.image_url)} alt="" className="w-full h-full object-contain" /> : '🎁'}
      </div>
      <div className="text-xs text-white font-bold leading-tight">{nm(c, lang)}</div>
      <button type="button" onClick={() => onOpen(c)} disabled={opening} data-testid="chest-open"
        className="w-full h-9 rounded-lg bg-gradient-to-r from-amber-400 to-orange-500 text-black text-sm font-black disabled:opacity-50">{t('ch_open')}</button>
    </div>
  );
}

function ResultItem({ x, lang, t, puzzles }) {
  if (x.kind === 'puzzle') {
    const p = puzzles.find((q) => q.puzzle_id === x.puzzle_id);
    return (
      <div className="rounded-xl border border-fuchsia-400/40 bg-fuchsia-500/10 p-2 text-center animate-[fadeIn_0.4s_ease-out]">
        <div className="text-2xl">🧩</div>
        <div className="text-[11px] text-white">{fill(t('ch_piece'), { name: nm(p, lang) || '—', n: x.have })}</div>
      </div>
    );
  }
  const r = getResource(x.resource, lang);
  return (
    <div className="rounded-xl border border-white/15 bg-white/5 p-2 text-center animate-[fadeIn_0.4s_ease-out]">
      <div className="text-2xl">{r.icon}</div>
      <div className="text-[11px] text-white/80 truncate">{r.name}</div>
      <div className="text-sm font-black text-emerald-300">+{fmt(x.amount)}</div>
    </div>
  );
}

function PuzzleCard({ p, lang, t, d, onAssemble, busy }) {
  const have = new Set(p.pieces || []);
  return (
    <div className="rounded-2xl border border-fuchsia-400/30 bg-black/40 p-3 space-y-2" data-testid="puzzle-card">
      <div className="flex items-center justify-between">
        <div className="text-white font-bold text-sm truncate">{nm(p, lang)}</div>
        <div className="text-xs font-bold text-fuchsia-200" data-testid="puzzle-count">{p.have}/9</div>
      </div>
      <div className="grid grid-cols-3 gap-0.5 rounded-xl overflow-hidden border border-white/10 aspect-square bg-black/60">
        {Array.from({ length: 9 }, (_, i) => i + 1).map((n) => {
          const url = p.piece_urls?.[String(n)];
          return (
            <div key={n} className={`relative flex items-center justify-center ${have.has(n) ? '' : 'bg-white/[0.04]'}`} data-testid={have.has(n) ? 'piece-have' : 'piece-missing'}>
              {have.has(n)
                ? (url ? <img src={imgUrl(url)} alt="" className="w-full h-full object-cover" /> : <span className="text-2xl">🧩</span>)
                : <span className="text-white/15 text-lg font-black">{n}</span>}
            </div>
          );
        })}
      </div>
      {p.status === 'complete' && (
        <button type="button" disabled={busy} onClick={() => onAssemble(p)} data-testid="puzzle-assemble"
          className="w-full h-10 rounded-xl bg-gradient-to-r from-fuchsia-500 to-cyan-400 text-black font-black disabled:opacity-50">{t('pz_assemble')}</button>
      )}
      {p.status === 'assembled' && (p.grant ? <NftStatus grant={p.grant} walletLinked={d.wallet_linked} net={d.nft_network} t={t} /> : null)}
    </div>
  );
}

function BoosterCard({ b, lang, t, onActivate, busy }) {
  const st = b.status;
  return (
    <div className={`rounded-xl border p-3 flex items-center gap-3 ${st === 'active' ? 'border-emerald-400/40 bg-emerald-500/10' : st === 'expired' ? 'border-white/5 bg-white/[0.02] opacity-60' : 'border-cyan-400/30 bg-cyan-500/5'}`} data-testid="booster-card">
      <div className="w-11 h-11 rounded-xl bg-black/40 border border-white/10 flex items-center justify-center text-xl">⚡</div>
      <div className="flex-1 min-w-0">
        <div className="text-white font-bold text-sm truncate">{nm(b, lang)}</div>
        <div className="text-[11px] text-text-muted">{t(`bs_eff_${b.effect}`)} · {fill(t('bs_hours'), { n: b.duration_hours })}</div>
        <div className="text-[11px] font-semibold mt-0.5 text-white/80">
          {st === 'available' && t('bs_available')}
          {st === 'active' && fill(t('bs_active_until'), { date: dt(b.expires_at, lang) })}
          {st === 'expired' && t('bs_expired')}
        </div>
      </div>
      {st === 'available' && (
        <button type="button" disabled={busy} onClick={() => onActivate(b)} data-testid="booster-activate"
          className="h-9 px-3 rounded-lg bg-cyan-400 text-black text-xs font-black disabled:opacity-50">{t('bs_activate')}</button>
      )}
    </div>
  );
}

export default function MinigameRewardsPage({ user }) {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const { language: lang } = useLanguage();
  const { t } = useTranslation(lang);
  const [d, setD] = useState(null);
  const [tab, setTab] = useState(params.get('tab') || 'points');
  const [opening, setOpening] = useState(null);
  const [opened, setOpened] = useState(null);           // last chest result
  const [busy, setBusy] = useState(false);
  const [needWallet, setNeedWallet] = useState(false);
  const [ev, setEv] = useState(null);

  const load = useCallback(async () => {
    try { setD(await mgCall('/minigames/rewards/me')); } catch (e) { toast.error(e.message); }
    mgCall('/minigames/event').then(setEv).catch(() => {});
  }, []);
  useEffect(() => { load(); return onProgress(load); }, [load]);
  const { link, busy: linking } = useLinkWallet(t, () => { setNeedWallet(false); load(); });

  const selectTab = (id) => { setTab(id); setParams((p) => { p.set('tab', id); return p; }, { replace: true }); };

  const openChest = async (c) => {
    setOpening(c.id); setOpened(null);
    const started = Date.now();
    try {
      const r = await mgCall(`/minigames/containers/${c.id}/open`, { method: 'POST' });
      await new Promise((res) => setTimeout(res, Math.max(0, 900 - (Date.now() - started))));   // the short shake
      setOpened(r); emitProgress && emitProgress();
      await load();
    } catch (e) {
      if (e.code === 'no_space') toast.error(fill(t('ch_no_space'), { n: e.data?.need ?? '' }));
      else toast.error(e.message);
    } finally { setOpening(null); }
  };

  const assemble = async (p) => {
    setBusy(true);
    try {
      const r = await mgCall(`/minigames/puzzles/${p.puzzle_id}/assemble`, { method: 'POST' });
      if (r.need_wallet) setNeedWallet(true);
      else { toast.success(t('pz_sent')); await load(); }
    } catch (e) { toast.error(e.message); }
    finally { setBusy(false); }
  };

  const activate = async (b) => {
    setBusy(true);
    try { await mgCall(`/minigames/boosters/${b.id}/activate`, { method: 'POST' }); toast.success(t('bs_activated')); await load(); }
    catch (e) { toast.error(e.message); }
    finally { setBusy(false); }
  };

  const daysLeft = ev?.ends_at ? Math.max(0, Math.floor((new Date(ev.ends_at) - Date.now()) / 86400000)) : null;
  const ptsRewards = (d?.rewards || []).filter((r) => r.category === 'points');
  const bestRewards = (d?.rewards || []).filter((r) => r.category === 'best');
  const unopened = (d?.containers || []).filter((c) => c.status === 'unopened');
  const history = (d?.containers || []).filter((c) => c.status === 'opened');
  const prevTh = (list, cur) => Math.max(0, ...list.map((r) => r.threshold).filter((x) => x <= cur));
  const toNext = (cur, next, list) => (next ? ((cur - prevTh(list, cur)) / Math.max(1, next - prevTh(list, cur))) * 100 : 100);

  const TABS = [
    { id: 'points', label: t('rw_tab_points'), Icon: Star },
    { id: 'best', label: t('rw_tab_best'), Icon: Award },
    { id: 'chests', label: t('rw_tab_chests'), Icon: Gift, count: d?.unopened },
    { id: 'puzzles', label: t('rw_tab_puzzles'), Icon: Puzzle, count: (d?.puzzles || []).filter((p) => p.status === 'complete').length },
    { id: 'boosters', label: t('rw_tab_boosters'), Icon: Zap, count: d?.boosters_available },
    { id: 'leaders', label: t('rw_tab_leaders'), Icon: Trophy },
  ];

  return (
    <div className="min-h-screen bg-transparent px-4 pt-4 pb-28 max-w-lg mx-auto space-y-3" data-testid="rewards-page">
      <div className="flex items-start justify-between gap-3">
        <div>
          <span className="inline-block rounded-full bg-amber-400/15 border border-amber-400/40 text-amber-200 text-[11px] font-bold px-2 py-0.5 mb-1">🎮 {t('mg_sorter_title')}</span>
          <h1 className="font-unbounded text-xl font-bold text-white">{t('rw_title')}</h1>
        </div>
        <button type="button" onClick={() => (window.history.length > 1 ? navigate(-1) : navigate('/minigames/sorter'))}
          className="p-2 rounded-lg border border-white/10 bg-black/40 text-white" aria-label={t('page_close')} data-testid="page-close-btn"><X className="w-4 h-4" /></button>
      </div>

      {!d ? <div className="text-center text-text-muted py-10">…</div> : (
        <>
          <div className="grid grid-cols-2 gap-2">
            <div className="rounded-2xl border border-amber-400/30 bg-gradient-to-br from-amber-500/15 to-orange-500/5 p-3 space-y-1.5" data-testid="rw-campaign">
              <div className="text-[11px] text-white/70 flex items-center justify-between">{t('rw_campaign_points')}{daysLeft !== null && <span className="flex items-center gap-1"><Clock className="w-3 h-3" />{fill(t('mg_days_left'), { n: daysLeft })}</span>}</div>
              <div className="text-2xl font-black text-white">{fmt(d.campaign_points)}</div>
              <Progress value={toNext(d.campaign_points, d.next_points, ptsRewards)} />
              <div className="text-[10px] text-text-muted">{d.next_points ? fill(t('rw_next'), { n: fmt(d.next_points) }) : t('rw_all_taken')}</div>
            </div>
            <div className="rounded-2xl border border-cyan-400/30 bg-gradient-to-br from-cyan-500/15 to-indigo-500/5 p-3 space-y-1.5" data-testid="rw-best">
              <div className="text-[11px] text-white/70">{t('rw_record')}</div>
              <div className="text-2xl font-black text-white">{fmt(d.best_score)}</div>
              <Progress value={toNext(d.best_score, d.next_best, bestRewards)} className="from-cyan-300 to-indigo-400" />
              <div className="text-[10px] text-text-muted">{d.next_best ? fill(t('rw_next'), { n: fmt(d.next_best) }) : t('rw_all_taken')}</div>
            </div>
          </div>

          {d.nft_waiting_wallet && (
            <div className="rounded-xl border border-cyan-400/40 bg-cyan-500/10 p-3 flex items-center gap-3" data-testid="wallet-banner">
              <Wallet className="w-5 h-5 text-cyan-300 shrink-0" />
              <div className="flex-1 text-xs text-white">{t('rw_link_banner')}</div>
              <button type="button" onClick={link} disabled={linking} className="h-8 px-3 rounded-lg bg-cyan-400 text-black text-xs font-black disabled:opacity-50">{t('rw_link_wallet')}</button>
            </div>
          )}

          <div className="flex gap-1.5 overflow-x-auto scrollbar-hide -mx-1 px-1 pb-1" role="tablist" data-testid="rw-tabs">
            {TABS.map(({ id, label, Icon: TabIcon, count }) => (
              <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => selectTab(id)} data-testid={`rw-tab-${id}`}
                className={`relative shrink-0 flex items-center gap-1.5 rounded-xl border px-3 py-2 text-xs font-bold uppercase tracking-wide transition-all ${
                  tab === id ? 'border-yellow-400/60 bg-yellow-400/15 text-yellow-300 shadow-[0_0_16px_rgba(250,204,21,0.15)]' : 'border-white/10 bg-white/5 text-white/70 hover:border-white/20'}`}>
                <TabIcon className="w-3.5 h-3.5" /><span>{label}</span>
                {count > 0 && <span className={`min-w-[18px] h-[18px] px-1 rounded-full text-[10px] leading-[18px] ${tab === id ? 'bg-yellow-400 text-black' : 'bg-white/15 text-white'}`}>{count}</span>}
              </button>
            ))}
          </div>

          {tab === 'points' && <div className="space-y-2">{ptsRewards.map((r) => <RewardCard key={r.id} r={r} lang={lang} t={t} d={d} />)}</div>}
          {tab === 'best' && <div className="space-y-2">{bestRewards.map((r) => <RewardCard key={r.id} r={r} lang={lang} t={t} d={d} />)}</div>}

          {tab === 'chests' && (
            <div className="space-y-3">
              <ChestConditions t={t} minStars={d.chest_min_stars} minPoints={d.chest_min_points} perDay={d.chests_per_day} today={d.chests_today} />
              {opened && (
                <div className="rounded-2xl border border-emerald-400/40 bg-emerald-500/10 p-3 space-y-2 animate-[fadeIn_0.3s_ease-out]" data-testid="chest-result">
                  <div className="text-sm font-bold text-emerald-200">✨ {t('ch_got')}</div>
                  {opened.results.length === 0 ? <div className="text-xs text-text-muted">{t('ch_empty_result')}</div> : (
                    <div className="grid grid-cols-3 gap-2">{opened.results.map((x, i) => <ResultItem key={i} x={x} lang={lang} t={t} puzzles={d.puzzles} />)}</div>
                  )}
                </div>
              )}
              {unopened.length === 0 ? <div className="text-xs text-text-muted text-center py-4">{t('ch_none')}</div> : (
                <div className="grid grid-cols-3 gap-2">{unopened.map((c) => <ChestCard key={c.id} c={c} lang={lang} t={t} onOpen={openChest} opening={opening === c.id} />)}</div>
              )}
              {history.length > 0 && (
                <div className="rounded-2xl border border-white/10 bg-black/40 p-3">
                  <div className="text-xs font-bold text-white mb-2">{t('ch_history')}</div>
                  {history.slice(0, 30).map((c) => (
                    <div key={c.id} className="flex items-center gap-2 py-1.5 border-t border-white/5 text-[11px]">
                      <span className="text-white/60 w-20 shrink-0">{dt(c.opened_at, lang)}</span>
                      <span className="flex-1 min-w-0 truncate text-white/85">
                        {(c.results || []).map((x) => (x.kind === 'puzzle' ? `🧩 ${x.have}/9` : `${getResource(x.resource, lang).icon} +${fmt(x.amount)}`)).join('  ')}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {tab === 'puzzles' && (
            <div className="space-y-3">
              {(d.puzzles || []).filter((p) => p.status !== 'none').length === 0 && <div className="text-xs text-text-muted text-center py-4">{t('pz_none')}</div>}
              <div className="grid grid-cols-2 gap-2">
                {(d.puzzles || []).filter((p) => p.status !== 'none').map((p) => <PuzzleCard key={p.puzzle_id} p={p} lang={lang} t={t} d={d} onAssemble={assemble} busy={busy} />)}
              </div>
            </div>
          )}

          {tab === 'boosters' && (
            <div className="space-y-2">
              {(d.boosters || []).length === 0 && <div className="text-xs text-text-muted text-center py-4">{t('bs_none')}</div>}
              {(d.boosters || []).map((b) => <BoosterCard key={b.id} b={b} lang={lang} t={t} onActivate={activate} busy={busy} />)}
            </div>
          )}

          {tab === 'leaders' && <MgLeaderboard lang={lang} t={t} myId={user?.id} />}
        </>
      )}

      {needWallet && (
        <div className="fixed inset-0 z-50 bg-black/70 flex items-end sm:items-center justify-center p-4" onClick={() => setNeedWallet(false)} data-testid="need-wallet">
          <div className="w-full max-w-sm rounded-2xl border border-cyan-400/40 bg-[#0b1020] p-4 space-y-3" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center gap-2 text-white font-bold"><Wallet className="w-5 h-5 text-cyan-300" />{t('pz_need_wallet_t')}</div>
            <div className="text-xs text-white/75">{t('pz_need_wallet')}</div>
            <button type="button" onClick={link} disabled={linking} className="w-full h-11 rounded-xl bg-cyan-400 text-black font-black disabled:opacity-50">{t('rw_link_wallet')}</button>
          </div>
        </div>
      )}
    </div>
  );
}
