/**
 * «Неделя Сортировщика» — the first mini-game, run as a promotion.
 * The app only draws the game and records the taps; the SERVER replays them (backend/minigames_sorter.py)
 * with the same rules (src/minigames/sorterCore.js) and decides the score, stars, XP and the chest.
 * Rules, chest conditions and prizes live in the «i» window next to the close button.
 * A won chest is opened by the server at once; it flies onto the screen right after the game and shows what dropped.
 * If the player leaves in the middle of a game, the game is finished in the background (fetch keepalive):
 * what was won is opened anyway and a notification (in-app + Telegram) shows it.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { X, Star, Gift, Info } from 'lucide-react';
import { useLanguage } from '@/context/LanguageContext';
import { useTranslation } from '@/lib/translations';
import { fill } from '@/lib/translationsMore';
import { makeItems, GAP_MS, MIN_REACTION_MS, LIVES, mult } from '@/minigames/sorterCore';
import { MgLeaderboard, PrizeBadge, nm, STARS, mgCall } from '@/components/minigames/mgShared';
import ChestReveal from '@/components/minigames/ChestReveal';

const BIN_ICON = ['⚙️', '🔋', '💾', '🧪'];
const BIN_KEY = ['mg_bin_metal', 'mg_bin_battery', 'mg_bin_chip', 'mg_bin_glass'];
const BIN_COLOR = ['#9fb3c8', '#39ff88', '#00f0ff', '#b36bff'];

function useCountdown(iso) {
  const [, tick] = useState(0);
  useEffect(() => { const id = setInterval(() => tick((x) => x + 1), 30000); return () => clearInterval(id); }, []);
  if (!iso) return null;
  const s = Math.max(0, (new Date(iso).getTime() - Date.now()) / 1000);
  return { d: Math.floor(s / 86400), h: Math.floor((s % 86400) / 3600), m: Math.floor((s % 3600) / 60) };
}

/** The game itself: one item at a time, 4 bins + «Skip»; the item's time bar is inside the item window (top). */
function SorterRound({ seed, onDone, t, actionsRef }) {
  const items = useRef(makeItems(seed)).current;
  const [idx, setIdx] = useState(0);
  const [score, setScore] = useState(0);
  const [combo, setCombo] = useState(0);
  const [lives, setLives] = useState(LIVES);
  const [cleared, setCleared] = useState(0);
  const [flash, setFlash] = useState(null);           // 'ok' | 'bad'
  const [resolving, setResolving] = useState(false);  // the pause between two items: the bar waits
  const [delayMs, setDelayMs] = useState(0);          // the bar starts when the item becomes active
  const st = useRef({ start: performance.now(), activeAt: 0, actions: [], busy: false, done: false });
  if (actionsRef) actionsRef.current = st.current;     // the page can finish the game if the player leaves

  const finish = useCallback(() => {
    if (st.current.done) return;
    st.current.done = true;
    onDone(st.current.actions);
  }, [onDone]);

  const resolve = useCallback((b) => {                  // b = bin 0..3, -1 = skip, null = time ran out
    const s = st.current;
    if (s.busy || s.done) return;
    s.busy = true;
    const it = items[idx];
    const now = performance.now() - s.start;
    // exactly the server's rules, so both timelines stay identical:
    if (b !== null && now < s.activeAt + MIN_REACTION_MS) { s.busy = false; return; }   // too early: ignored, item stays
    if (b !== null && now > s.activeAt + it.window) b = null;                          // too late: counts as time out
    if (b !== null) s.actions.push({ i: it.i, b, t: Math.round(now) });
    const ok = b === null ? it.hazard : (it.hazard ? b === -1 : b === it.type);
    let livesNow = lives;
    if (ok) { const c = combo + 1; setCombo(c); setCleared((x) => x + 1); setScore((x) => x + 10 * mult(c)); }
    else { setCombo(0); livesNow = lives - 1; setLives(livesNow); }        // a mistake costs a life
    setFlash(ok ? 'ok' : 'bad');
    setResolving(true);
    const resolvedAt = b === null ? s.activeAt + it.window : now;
    setTimeout(() => {
      setFlash(null);
      if (livesNow <= 0 || idx + 1 >= items.length) { finish(); return; }   // out of lives: game over
      s.activeAt = resolvedAt + GAP_MS;
      s.busy = false;
      setDelayMs(Math.max(0, s.activeAt - (performance.now() - s.start)));
      setResolving(false);
      setIdx(idx + 1);
    }, Math.max(0, resolvedAt + GAP_MS - (performance.now() - s.start)));
  }, [idx, items, combo, lives, finish]);

  useEffect(() => {                                      // time out of the current item (the bar itself is CSS)
    const s = st.current;
    const it = items[idx];
    const ms = Math.max(0, s.activeAt + it.window - (performance.now() - s.start));
    const id = setTimeout(() => { if (!st.current.busy) resolve(null); }, ms + 5);
    return () => clearTimeout(id);
  }, [idx, items, resolve]);

  const it = items[idx];
  return (
    <div className="space-y-4" data-testid="sorter-round">
      <div className="flex items-center justify-between text-sm">
        <div className="text-white font-bold" data-testid="sorter-score">{t('mg_score')}: {score}</div>
        <div className="text-cyan-300">{t('mg_combo')} ×{mult(combo)}</div>
        <div className="tracking-wider" data-testid="sorter-lives" aria-label={t('mg_lives')}>{'❤️'.repeat(Math.max(0, lives))}{'🖤'.repeat(Math.max(0, LIVES - lives))}</div>
      </div>
      <div className="text-center text-xs text-text-muted" data-testid="sorter-counter">{fill(t('mg_cleared'), { n: cleared })}</div>
      <div className={`relative h-52 rounded-2xl border overflow-hidden flex items-center justify-center transition-colors ${it.hazard ? 'border-red-500/70 bg-red-500/10' : 'border-white/10 bg-white/5'} ${flash === 'ok' ? 'ring-2 ring-emerald-400' : flash === 'bad' ? 'ring-2 ring-red-500' : ''}`}>
        <div className="absolute inset-x-0 bottom-6 h-3 bg-[repeating-linear-gradient(90deg,#1b2235_0_14px,#2a3352_14px_28px)] opacity-80" />
        <div className="text-7xl select-none" style={{ filter: it.hazard ? 'drop-shadow(0 0 14px #ff3b5c)' : `drop-shadow(0 0 12px ${BIN_COLOR[it.type]})` }} data-testid="sorter-item" data-idx={idx}>
          {it.hazard ? '☢️' : BIN_ICON[it.type]}
        </div>
        {/* the time for this item — inside the item's window. Always starts FULL (also during the pause between
            items); later items get less time, so the same full bar simply runs out faster. A CSS animation (GPU). */}
        <div className="absolute top-3 inset-x-4 h-2.5 rounded-full bg-black/55 border border-white/10 overflow-hidden" data-testid="sorter-timer">
          {resolving
            ? <div className="h-full w-full bg-[#39ff88]" data-testid="sorter-timer-full" />
            : <div key={idx} className="h-full w-full origin-left mg-timebar"
                style={{ animationDuration: `${it.window}ms`, animationDelay: `${delayMs}ms` }} />}
        </div>
        {it.hazard && <div className="absolute top-8 text-red-300 font-black text-sm tracking-widest">{t('mg_hazard')}</div>}
      </div>
      <div className="grid grid-cols-2 gap-2">
        {BIN_ICON.map((ic, b) => (
          <button key={b} type="button" onClick={() => resolve(b)} data-testid={`sorter-bin-${b}`}
            className="h-16 rounded-xl border bg-black/40 active:scale-95 transition flex items-center justify-center gap-2 text-white font-bold"
            style={{ borderColor: `${BIN_COLOR[b]}88`, boxShadow: `inset 0 0 18px ${BIN_COLOR[b]}22` }}>
            <span className="text-2xl">{ic}</span><span className="text-sm">{t(BIN_KEY[b])}</span>
          </button>
        ))}
      </div>
      <button type="button" onClick={() => resolve(-1)} data-testid="sorter-skip"
        className="w-full h-12 rounded-xl border border-red-500/50 bg-red-500/10 text-red-200 font-bold active:scale-95 transition">{t('mg_skip')}</button>
    </div>
  );
}

function InfoModal({ ev, t, lang, onClose }) {
  const BINS = BIN_ICON.map((ic, b) => ({ ic, label: t(BIN_KEY[b]) }));
  return (
    <div className="fixed inset-0 z-[90] bg-black/70 flex items-end sm:items-center justify-center p-4" onClick={onClose} data-testid="sorter-info-modal">
      <div className="w-full max-w-lg max-h-[calc(100dvh-var(--bottom-nav-h,90px)-40px)] overflow-y-auto rounded-2xl border border-white/10 bg-[#0b1020] p-4 space-y-4 mb-[var(--bottom-nav-h,0px)] sm:mb-0"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <div className="font-bold text-white flex items-center gap-2"><Info className="w-4 h-4 text-cyan-300" />{t('mg_info')}</div>
          <button type="button" onClick={onClose} className="text-white/60" aria-label={t('page_close')}><X className="w-5 h-5" /></button>
        </div>
        <div className="space-y-2 text-sm" data-testid="sorter-rules">
          <div className="font-bold text-white">{t('mg_rules_title')}</div>
          <div className="text-white/75 text-xs leading-relaxed">{t('mg_rules_endless')}</div>
          <div className="grid grid-cols-4 gap-1 text-center text-[11px] text-white/80">{BINS.map((x) => <div key={x.label} className="rounded bg-white/5 py-1">{x.ic}<div>{x.label}</div></div>)}</div>
          {ev?.star_points && <div className="text-xs text-text-muted">{t('mg_stars_points')}: ★ {ev.star_points[0]} · ★★ {ev.star_points[1]} · ★★★ {ev.star_points[2]}</div>}
          {ev?.xp_by_stars && <div className="text-xs text-text-muted">{t('mg_stars_xp')}: ★ {ev.xp_by_stars['1']} · ★★ {ev.xp_by_stars['2']} · ★★★ {ev.xp_by_stars['3']} XP</div>}
        </div>
        {ev?.chests_per_day > 0 && (
          <div className="rounded-xl border border-amber-400/25 bg-amber-500/5 p-3 space-y-1" data-testid="sorter-chest-rules">
            <div className="font-bold text-white text-sm">🎁 {t('cond_title')}</div>
            <div className="text-xs text-white/75 leading-relaxed">{fill(t('cond_text'), { s: STARS(ev.chest_min_stars), p: Number(ev.chest_min_points).toLocaleString('ru-RU'), n: ev.chests_per_day })}</div>
          </div>
        )}
        {(ev?.prizes || []).length > 0 && (
          <div className="space-y-1" data-testid="sorter-prizes">
            <div className="font-bold text-white text-sm">🏆 {t('lb_title')}</div>
            <div className="text-xs text-text-muted">{t('lb_prizes_note')}:</div>
            {ev.prizes.map((p) => (
              <div key={`${p.from}-${p.to}`} className="flex items-center justify-between gap-2 text-xs">
                <span className="text-white/80">{p.from === p.to ? fill(t('mg_place_one'), { a: p.from }) : fill(t('mg_places'), { a: p.from, b: p.to })}</span>
                <PrizeBadge prize={p} lang={lang} t={t} />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default function SorterGamePage({ user }) {
  const navigate = useNavigate();
  const { language: lang } = useLanguage();
  const { t } = useTranslation(lang);
  const [ev, setEv] = useState(null);
  const [session, setSession] = useState(null);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [lbKey, setLbKey] = useState(0);
  const [info, setInfo] = useState(false);
  const [chests, setChests] = useState(null);           // opened chests flying onto the screen
  const roundRef = useRef(null);                         // the running round (its actions)
  const sessionRef = useRef(null);
  const left = useCountdown(ev?.ends_at);

  const load = useCallback(async () => {
    try { const e = await mgCall('/minigames/event'); setEv(e); return e; } catch (e) { setEv({ active: false }); return null; }
  }, []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { sessionRef.current = session; }, [session]);

  // The player leaves in the middle of a game (closes the app, hides it, goes to another page): finish it in the
  // background so what was won is still given — the server opens the chest and sends a notification.
  const finishInBackground = useCallback(() => {
    const s = sessionRef.current, r = roundRef.current;
    if (!s || !r || r.done) return;
    r.done = true; sessionRef.current = null;
    try {
      const tok = localStorage.getItem('token') || localStorage.getItem('ton_city_token') || '';
      fetch(`${process.env.REACT_APP_BACKEND_URL || ''}/api/minigames/sorter/finish`, {
        method: 'POST', keepalive: true,
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${tok}` },
        body: JSON.stringify({ session_id: s.session_id, actions: r.actions, background: true }),
      }).catch(() => {});
    } catch (_) { /* nothing more to do */ }
  }, []);
  useEffect(() => {
    const onHide = () => { if (document.visibilityState === 'hidden' && sessionRef.current) { finishInBackground(); setSession(null); load(); } };
    const onLeave = () => finishInBackground();
    document.addEventListener('visibilitychange', onHide);
    window.addEventListener('pagehide', onLeave);
    return () => {
      document.removeEventListener('visibilitychange', onHide);
      window.removeEventListener('pagehide', onLeave);
      finishInBackground();                                // left the page inside the app
    };
  }, [finishInBackground, load]);

  const play = async () => {
    setBusy(true); setResult(null);
    try { setSession(await mgCall('/minigames/sorter/start', { method: 'POST' })); }
    catch (e) { toast.error(e.code === 'no_attempts_left' || e.code === 'daily_cap' ? t('mg_no_attempts') : e.code === 'event_not_active' ? t('mg_not_active') : e.message); }
    finally { setBusy(false); }
  };
  const done = useCallback(async (actions) => {
    try {
      const r = await mgCall('/minigames/sorter/finish', { method: 'POST', body: JSON.stringify({ session_id: session.session_id, actions }) });
      setResult(r); load(); setLbKey((k) => k + 1);
      const opened = (r.opened_chests || []).filter((c) => c && c.status === 'opened');
      if (opened.length) setChests(opened);                // already opened by the server: the opening is shown
    } catch (e) { toast.error(e.message); }
    finally { setSession(null); }
  }, [session, load]);

  const me = ev?.me;
  return (
    <div className="min-h-screen bg-transparent px-4 pt-4 pb-28 max-w-lg mx-auto" data-testid="sorter-page">
      <div className="flex items-start justify-between gap-3 mb-4">
        <div>
          <span className="inline-block rounded-full bg-amber-400/15 border border-amber-400/40 text-amber-200 text-[11px] font-bold px-2 py-0.5 mb-1">🎮 {t('mg_event_badge')}</span>
          <h1 className="font-unbounded text-xl font-bold text-white">{t('mg_sorter_title')}</h1>
          {left && <div className="text-xs text-text-muted">{t('mg_ends_in')}: {left.d}{t('buff_d')} {left.h}{t('buff_h')} {left.m}{t('buff_m')}</div>}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button type="button" onClick={() => setInfo(true)} className="p-2 rounded-full border border-cyan-400/40 bg-cyan-500/10 text-cyan-200"
            aria-label={t('mg_info')} data-testid="sorter-info-btn"><Info className="w-4 h-4" /></button>
          <button type="button" onClick={() => (window.history.length > 1 ? navigate(-1) : navigate('/my-businesses'))}
            className="p-2 rounded-lg border border-white/10 bg-black/40 text-white" aria-label={t('page_close')} data-testid="page-close-btn"><X className="w-4 h-4" /></button>
        </div>
      </div>

      {session ? (
        <SorterRound seed={session.seed} onDone={done} t={t} actionsRef={roundRef} />
      ) : (
        <div className="space-y-4">
          {result && (
            <div className="rounded-2xl border border-cyan-400/40 bg-cyan-500/10 p-4 text-center space-y-1" data-testid="sorter-result">
              <div className="text-xs uppercase tracking-wider text-cyan-300">{t('mg_result')}</div>
              <div className="text-xs text-red-300 font-bold">{t('mg_game_over')}</div>
              <div className="text-3xl font-black text-white">{result.points}</div>
              <div className="text-xs text-white/70">{fill(t('mg_cleared'), { n: result.cleared ?? 0 })} · {t('mg_combo')} {result.best_combo ?? 0}</div>
              <div className="flex justify-center gap-1">{[1, 2, 3].map((k) => <Star key={k} className={`w-6 h-6 ${k <= result.stars ? 'text-yellow-300 fill-yellow-300' : 'text-white/20'}`} />)}</div>
              {result.xp > 0 && <div className="text-emerald-300 font-bold">{fill(t('mg_reward_xp'), { n: result.xp })}</div>}
              {result.new_best && <div className="text-amber-300 font-bold">{t('mg_new_best')}</div>}
              {result.rejected && <div className="text-red-300 text-xs">{t('mg_rejected')}</div>}
              {result.chest && !result.rejected && (result.chest.reason === 'low_stars' || result.chest.reason === 'daily_limit') && (
                <div className="mt-2 rounded-xl px-3 py-2 text-sm font-bold bg-white/5 text-white/70 border border-white/10" data-testid="sorter-chest">
                  {result.chest.reason === 'daily_limit' ? fill(t('res_chest_limit'), { n: result.chests_per_day }) : fill(t('res_chest_low'), { s: STARS(ev?.chest_min_stars) })}
                </div>
              )}
              {(result.opened_chests || []).some((c) => c && c.status !== 'opened') && (
                <div className="mt-2 rounded-xl px-3 py-2 text-sm font-bold bg-amber-500/10 text-amber-200 border border-amber-400/30" data-testid="sorter-chest-wait">
                  📦 {t('ch_wait_space')}
                </div>
              )}
              {(result.new_rewards || []).map((r) => (
                <div key={r.id} className="text-sm font-bold text-fuchsia-200" data-testid="sorter-new-reward">🏅 {fill(t('res_new_reward'), { name: nm(r, lang) })}</div>
              ))}
            </div>
          )}
          <div className="rounded-2xl border border-white/10 bg-black/40 p-4 space-y-3">
            <div className="text-sm text-white/80">{t('mg_sorter_pitch')}</div>
            {ev?.active ? (
              <>
                {me && (
                  <div className="grid grid-cols-3 gap-1.5 text-center text-[11px]">
                    <div className="rounded-lg bg-white/5 p-2"><div className="text-text-muted leading-tight">{t('rw_campaign_points')}</div><div className="text-white font-bold text-sm">{(me.points || 0).toLocaleString('ru-RU')}</div></div>
                    <div className="rounded-lg bg-white/5 p-2"><div className="text-text-muted leading-tight">{t('mg_place')}</div><div className="text-white font-bold text-sm">{me.place || '—'}</div></div>
                    <div className="rounded-lg bg-white/5 p-2"><div className="text-text-muted leading-tight">{t('mg_my_best')}</div><div className="text-white font-bold text-sm">{(me.best || 0).toLocaleString('ru-RU')}</div></div>
                  </div>
                )}
                <button type="button" disabled={busy || (me && me.attempts_left === 0)} onClick={play} data-testid="sorter-play"
                  className="w-full h-14 rounded-xl bg-gradient-to-r from-amber-400 to-orange-500 text-black font-black text-lg disabled:opacity-40">
                  {result ? t('mg_play_again') : t('mg_play')}
                </button>
                {me && me.attempts_left === 0 && <div className="text-xs text-center text-text-muted">{t('mg_no_attempts')}</div>}
                <button type="button" onClick={() => navigate('/minigames/rewards')} data-testid="sorter-rewards-btn"
                  className="w-full h-11 rounded-xl border border-amber-400/40 bg-amber-400/10 text-amber-200 font-bold flex items-center justify-center gap-2">
                  <Gift className="w-4 h-4" />{t('rw_title')}
                </button>
              </>
            ) : (
              <div className="text-sm text-text-muted">{t('mg_not_active')}</div>
            )}
          </div>
          <div data-testid="sorter-top"><MgLeaderboard lang={lang} t={t} myId={user?.id} compact refreshKey={lbKey} /></div>
        </div>
      )}
      {info && <InfoModal ev={ev} t={t} lang={lang} onClose={() => setInfo(false)} />}
      {chests && chests.length > 0 && !session && (
        <ChestReveal chests={chests} lang={lang} t={t} onClose={() => setChests(null)} />
      )}
    </div>
  );
}
