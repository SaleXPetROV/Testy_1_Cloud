/**
 * «Награды» of the mini-game promotion: event points + record with the next thresholds, rewards for points / record,
 * chests (opened automatically right when given), NFT puzzles 3×3 («Собрать» only with a linked wallet),
 * boosters, list of leaders. Everything is decided by the server (backend/minigame_rewards.py).
 */
import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { toast } from 'sonner';
import { X, Gift, Puzzle, Trophy, Wallet, Clock } from 'lucide-react';
import { useLanguage } from '@/context/LanguageContext';
import { useTranslation } from '@/lib/translations';
import { fill } from '@/lib/translationsMore';
import { onProgress } from '@/lib/progressBus';
import { mgCall, nm, imgUrl, MgLeaderboard, useLinkWallet, NFT_ST_KEY, tonviewer } from '@/components/minigames/mgShared';

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

export default function MinigameRewardsPage({ user }) {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const { language: lang } = useLanguage();
  const { t } = useTranslation(lang);
  const [d, setD] = useState(null);
  const [tab, setTab] = useState(['rewards', 'puzzles', 'leaders'].includes(params.get('tab')) ? params.get('tab') : 'rewards');
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

  const assemble = async (p) => {
    setBusy(true);
    try {
      const r = await mgCall(`/minigames/puzzles/${p.puzzle_id}/assemble`, { method: 'POST' });
      if (r.need_wallet) setNeedWallet(true);
      else { toast.success(t('pz_sent')); await load(); }
    } catch (e) { toast.error(e.message); }
    finally { setBusy(false); }
  };

  const daysLeft = ev?.ends_at ? Math.max(0, Math.floor((new Date(ev.ends_at) - Date.now()) / 86400000)) : null;
  const ptsRewards = (d?.rewards || []).filter((r) => r.category === 'points');
  const bestRewards = (d?.rewards || []).filter((r) => r.category === 'best');
  const prevTh = (list, cur) => Math.max(0, ...list.map((r) => r.threshold).filter((x) => x <= cur));
  const toNext = (cur, next, list) => (next ? ((cur - prevTh(list, cur)) / Math.max(1, next - prevTh(list, cur))) * 100 : 100);

  const TABS = [
    { id: 'rewards', label: t('rw_title'), Icon: Gift },
    { id: 'puzzles', label: t('rw_tab_puzzles'), Icon: Puzzle, count: (d?.puzzles || []).filter((p) => p.status === 'complete').length },
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

          <div className="grid grid-cols-3 gap-1.5" role="tablist" data-testid="rw-tabs">
            {TABS.map(({ id, label, Icon: TabIcon, count }) => (
              <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => selectTab(id)} data-testid={`rw-tab-${id}`}
                className={`relative justify-center flex items-center gap-1.5 rounded-xl border px-3 py-2 text-xs font-bold uppercase tracking-wide transition-all ${
                  tab === id ? 'border-yellow-400/60 bg-yellow-400/15 text-yellow-300 shadow-[0_0_16px_rgba(250,204,21,0.15)]' : 'border-white/10 bg-white/5 text-white/70 hover:border-white/20'}`}>
                <TabIcon className="w-3.5 h-3.5" /><span>{label}</span>
                {count > 0 && <span className={`min-w-[18px] h-[18px] px-1 rounded-full text-[10px] leading-[18px] ${tab === id ? 'bg-yellow-400 text-black' : 'bg-white/15 text-white'}`}>{count}</span>}
              </button>
            ))}
          </div>

          {tab === 'rewards' && (
            <div className="space-y-3">
              <div className="text-xs font-bold uppercase tracking-wide text-amber-200">{t('rw_section_points')}</div>
              <div className="space-y-2">{ptsRewards.map((r) => <RewardCard key={r.id} r={r} lang={lang} t={t} d={d} />)}</div>
              <div className="text-xs font-bold uppercase tracking-wide text-cyan-200 pt-1">{t('rw_section_best')}</div>
              <div className="space-y-2">{bestRewards.map((r) => <RewardCard key={r.id} r={r} lang={lang} t={t} d={d} />)}</div>
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
