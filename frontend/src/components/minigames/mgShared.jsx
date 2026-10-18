/** Shared pieces of the mini-game rewards UI: API helper, names, prizes, the list of leaders, chest conditions,
 *  wallet linking (existing TON Connect + /api/auth/link-wallet). Built from the project's usual elements. */
import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import { Trophy } from 'lucide-react';
import { fill } from '@/lib/translationsMore';
import { useTonConnectUI, useTonWallet } from '@/lib/tonconnect-lazy';

const API = `${process.env.REACT_APP_BACKEND_URL || ''}/api`;
const BACKEND = process.env.REACT_APP_BACKEND_URL || '';
const token = () => localStorage.getItem('token') || localStorage.getItem('ton_city_token') || '';

export async function mgCall(path, opts = {}) {
  const r = await fetch(`${API}${path}`, { ...opts, headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token()}`, ...(opts.headers || {}) } });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) {
    const det = d.detail;
    const e = new Error(typeof det === 'string' ? det : (det?.code || 'Error'));
    e.code = typeof det === 'string' ? det : det?.code; e.data = det; e.status = r.status;
    throw e;
  }
  return d;
}

/** picture urls from the server are relative (/api/minigames/img/...) */
// /api/... is served by the backend; other root paths (e.g. /sprites/city/...) are static files of the app itself
export const imgUrl = (u) => (!u ? '' : u.startsWith('/api/') ? `${BACKEND}${u}` : u);

/** name in the player's language (the admin may fill name_i18n; otherwise the base name) */
export const nm = (o, lang) => (o?.name_i18n && (o.name_i18n[lang] || o.name_i18n.en)) || o?.name || '';

export const STARS = (n) => '★'.repeat(Math.max(1, Number(n) || 2));
const PRIZE_ICON = { city: '💰', nft: '💎', container: '🎁', booster: '⚡', reward: '🏅' };

export function prizeText(p, lang, t) {
  if (!p) return '';
  if (p.kind === 'city') return fill(t('lb_city'), { n: Math.round(p.city || 0).toLocaleString('ru-RU') });
  return nm(p, lang) || '—';
}

export function PrizeBadge({ prize, lang, t }) {
  if (!prize) return null;
  return (
    <span className="inline-flex items-center gap-1 max-w-[150px] truncate rounded-full bg-amber-400/10 border border-amber-400/30 px-2 py-0.5 text-[11px] text-amber-200" title={prizeText(prize, lang, t)}>
      <span>{PRIZE_ICON[prize.kind] || '🏅'}</span><span className="truncate">{prizeText(prize, lang, t)}</span>
    </span>
  );
}

function LeaderRow({ r, me, lang, t, rowRef }) {
  return (
    <div ref={rowRef} className={`flex items-center gap-2 text-sm py-1.5 px-2 rounded-lg ${me ? 'bg-cyan-500/15 border border-cyan-400/40' : 'border-t border-white/5'}`}
      data-testid={me ? 'lb-my-row' : 'lb-row'}>
      <b className={`w-8 shrink-0 text-right ${r.place <= 3 ? 'text-amber-300' : 'text-white'}`}>{r.place ?? '—'}</b>
      <span className="flex-1 min-w-0 truncate text-white/85">{me ? `${t('lb_you')} · ` : ''}@{r.username}</span>
      <PrizeBadge prize={r.prize} lang={lang} t={t} />
      <span className="w-16 text-right text-amber-200 font-bold">{(r.points ?? 0).toLocaleString('ru-RU')}</span>
    </div>
  );
}

/** List of leaders by event points; the player's own row is pinned to the bottom while it is not on screen. */
export function MgLeaderboard({ lang, t, myId, compact = false, refreshKey = 0 }) {
  const [data, setData] = useState(null);
  const myRef = useRef(null);
  const boxRef = useRef(null);
  const [myVisible, setMyVisible] = useState(false);

  useEffect(() => { mgCall('/minigames/leaderboard?limit=100').then(setData).catch(() => setData({ rows: [], me: null })); }, [refreshKey]);
  const rows = data?.rows || [];
  const me = data?.me;
  const mine = rows.find((r) => r.user_id === myId);

  useEffect(() => {
    if (!myRef.current || !boxRef.current || typeof IntersectionObserver === 'undefined') { setMyVisible(false); return undefined; }
    const io = new IntersectionObserver(([e]) => setMyVisible(e.isIntersecting), { root: boxRef.current, threshold: 0.6 });
    io.observe(myRef.current);
    return () => io.disconnect();
  }, [mine, rows.length]);

  return (
    <div className="rounded-2xl border border-white/10 bg-black/40 p-3" data-testid="mg-leaderboard">
      <div className="flex items-center gap-2 font-bold text-white mb-1"><Trophy className="w-4 h-4 text-amber-300" />{t('lb_title')}</div>
      {(data?.prizes || []).length > 0 && <div className="text-[11px] text-text-muted mb-2">{t('lb_prizes_note')}</div>}
      <div ref={boxRef} className={`relative overflow-y-auto ${compact ? 'max-h-72' : 'max-h-[max(220px,calc(100dvh-30rem))]'}`}>
        {data && rows.length === 0 && <div className="text-xs text-text-muted py-2">{t('lb_empty')}</div>}
        {rows.map((r) => <LeaderRow key={r.user_id} r={r} me={r.user_id === myId} lang={lang} t={t} rowRef={r.user_id === myId ? myRef : undefined} />)}
        {me && !myVisible && (
          <div className="sticky bottom-0 pt-1 bg-gradient-to-t from-[#070b16] via-[#070b16] to-transparent" data-testid="lb-pinned-me">
            {me.place
              ? <LeaderRow r={{ ...me, user_id: myId }} me lang={lang} t={t} />
              : <div className="text-xs text-center text-cyan-200 py-2 rounded-lg bg-cyan-500/10 border border-cyan-400/30">{t('lb_no_place')}</div>}
          </div>
        )}
      </div>
    </div>
  );
}

/** «Как получить сундук» + «Сундуков сегодня: N/4» */
export function ChestConditions({ t, minStars = 2, minPoints = 1000, perDay = 4, today = 0 }) {
  if (!perDay) return null;
  return (
    <div className="rounded-2xl border border-amber-400/25 bg-amber-500/5 p-3 space-y-1.5" data-testid="chest-conditions">
      <div className="flex items-center justify-between gap-2">
        <div className="font-bold text-white text-sm">🎁 {t('cond_title')}</div>
        <div className="text-xs font-bold text-amber-200" data-testid="chests-today">{fill(t('cond_today'), { a: Math.min(today, perDay), b: perDay })}</div>
      </div>
      <div className="text-xs text-white/75 leading-relaxed">{fill(t('cond_text'), { s: STARS(minStars), p: Number(minPoints).toLocaleString('ru-RU'), n: perDay })}</div>
      <div className="h-1.5 rounded-full bg-white/10 overflow-hidden"><div className="h-full bg-amber-400" style={{ width: `${Math.min(100, (today / perDay) * 100)}%` }} /></div>
    </div>
  );
}

/** Link the TON wallet to the account (existing TON Connect flow). */
export function useLinkWallet(t, onLinked) {
  const [tonConnectUI] = useTonConnectUI();
  const wallet = useTonWallet();
  const [busy, setBusy] = useState(false);
  const wanted = useRef(false);

  const persist = useCallback(async (addr) => {
    try {
      const r = await fetch(`${API}/auth/link-wallet`, { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token()}` },
        body: JSON.stringify({ wallet_address: addr }) });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) {
        try { await tonConnectUI?.disconnect(); } catch (_) { /* noop */ }
        throw new Error(d.detail === 'wallet_already_linked' ? t('rw_wallet_busy') : (d.detail || 'Error'));
      }
      toast.success(t('rw_wallet_linked'));
      onLinked && onLinked();
    } catch (e) { toast.error(e.message); }
    finally { setBusy(false); wanted.current = false; }
  }, [tonConnectUI, t, onLinked]);

  useEffect(() => {
    if (wanted.current && wallet?.account?.address) persist(wallet.account.address);
  }, [wallet, persist]);

  const link = useCallback(async () => {
    setBusy(true); wanted.current = true;
    if (wallet?.account?.address) { persist(wallet.account.address); return; }
    try { await tonConnectUI?.openModal(); } catch (_) { setBusy(false); wanted.current = false; }
  }, [wallet, tonConnectUI, persist]);

  return { link, busy };
}

export const NFT_ST_KEY = (g, walletLinked) => {
  if (!g) return null;
  if (g.status === 'reserved' && !walletLinked) return 'nft_st_wait_wallet';
  return { waiting_stock: 'nft_st_waiting_stock', reserved: 'nft_st_reserved', sending: 'nft_st_sending', delivered: 'nft_st_delivered', failed: 'nft_st_failed' }[g.status] || null;
};

export const tonviewer = (addr, net) => `https://${net === 'mainnet' ? '' : 'testnet.'}tonviewer.com/${addr}`;
