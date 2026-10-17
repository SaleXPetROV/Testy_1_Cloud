/**
 * «Неделя Сортировщика» — the first mini-game, run as a promotion.
 * The app only draws the game and records the taps; the SERVER replays them (backend/minigames_sorter.py)
 * with the same rules (src/minigames/sorterCore.js) and decides the score, stars and XP.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { X, Star, Gift } from 'lucide-react';
import { useLanguage } from '@/context/LanguageContext';
import { useTranslation } from '@/lib/translations';
import { fill } from '@/lib/translationsMore';
import { makeItems, GAP_MS, MIN_REACTION_MS, LIVES, mult } from '@/minigames/sorterCore';
import { MgLeaderboard, ChestConditions, PrizeBadge, nm, STARS } from '@/components/minigames/mgShared';

const API = `${process.env.REACT_APP_BACKEND_URL || ''}/api`;
const auth = () => ({ Authorization: `Bearer ${localStorage.getItem('token') || localStorage.getItem('ton_city_token') || ''}` });
const BIN_ICON = ['⚙️', '🔋', '💾', '🧪'];
const BIN_KEY = ['mg_bin_metal', 'mg_bin_battery', 'mg_bin_chip', 'mg_bin_glass'];
const BIN_COLOR = ['#9fb3c8', '#39ff88', '#00f0ff', '#b36bff'];

async function call(path, opts = {}) {
  const r = await fetch(`${API}${path}`, { ...opts, headers: { 'Content-Type': 'application/json', ...auth(), ...(opts.headers || {}) } });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) { const e = new Error(typeof d.detail === 'string' ? d.detail : 'Error'); e.code = d.detail; e.status = r.status; throw e; }
  return d;
}

function useCountdown(iso) {
  const [, tick] = useState(0);
  useEffect(() => { const id = setInterval(() => tick((x) => x + 1), 30000); return () => clearInterval(id); }, []);
  if (!iso) return null;
  const s = Math.max(0, (new Date(iso).getTime() - Date.now()) / 1000);
  return { d: Math.floor(s / 86400), h: Math.floor((s % 86400) / 3600), m: Math.floor((s % 3600) / 60) };
}

/** The game itself: one item at a time, its time bar, 4 bins + «Skip». */
function SorterRound({ seed, onDone, t }) {
  const items = useRef(makeItems(seed)).current;
  const [idx, setIdx] = useState(0);
  const [score, setScore] = useState(0);
  const [combo, setCombo] = useState(0);
  const [lives, setLives] = useState(LIVES);
  const [cleared, setCleared] = useState(0);
  const [flash, setFlash] = useState(null);           // 'ok' | 'bad'
  const [left, setLeft] = useState(1);                 // part of the window left (0..1)
  const st = useRef({ start: performance.now(), activeAt: 0, actions: [], busy: false, done: false });

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
    const resolvedAt = b === null ? s.activeAt + it.window : now;
    setTimeout(() => {
      setFlash(null);
      if (livesNow <= 0 || idx + 1 >= items.length) { finish(); return; }   // out of lives: game over
      s.activeAt = resolvedAt + GAP_MS;
      s.busy = false;
      setIdx(idx + 1);
    }, Math.max(0, resolvedAt + GAP_MS - (performance.now() - s.start)));
  }, [idx, items, combo, lives, finish]);

  useEffect(() => {                                      // time bar of the current item
    let raf;
    const loop = () => {
      const s = st.current; if (s.done) return;
      const it = items[idx];
      const now = performance.now() - s.start;
      const k = 1 - (now - s.activeAt) / it.window;
      setLeft(Math.max(0, Math.min(1, k)));
      if (now >= s.activeAt + it.window && !s.busy) { resolve(null); return; }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
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
        <div className="absolute inset-x-0 bottom-10 h-3 bg-[repeating-linear-gradient(90deg,#1b2235_0_14px,#2a3352_14px_28px)] opacity-80" />
        <div className="text-7xl select-none" style={{ filter: it.hazard ? 'drop-shadow(0 0 14px #ff3b5c)' : `drop-shadow(0 0 12px ${BIN_COLOR[it.type]})` }} data-testid="sorter-item" data-idx={idx}>
          {it.hazard ? '☢️' : BIN_ICON[it.type]}
        </div>
        {it.hazard && <div className="absolute top-3 text-red-300 font-black text-sm tracking-widest">{t('mg_hazard')}</div>}
        <div className="absolute bottom-0 inset-x-0 h-2 bg-black/40">
          <div className="h-full transition-[width] duration-75" style={{ width: `${left * 100}%`, background: left > 0.4 ? '#39ff88' : left > 0.2 ? '#ffd84d' : '#ff3b5c' }} />
        </div>
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

export default function SorterGamePage({ user }) {
  const navigate = useNavigate();
  const { language: lang } = useLanguage();
  const { t } = useTranslation(lang);
  const [ev, setEv] = useState(null);
  const [session, setSession] = useState(null);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [lbKey, setLbKey] = useState(0);
  const left = useCountdown(ev?.ends_at);

  const load = useCallback(async () => { try { setEv(await call('/minigames/event')); } catch (e) { setEv({ active: false }); } }, []);
  useEffect(() => { load(); }, [load]);

  const play = async () => {
    setBusy(true); setResult(null);
    try { setSession(await call('/minigames/sorter/start', { method: 'POST' })); }
    catch (e) { toast.error(e.code === 'no_attempts_left' || e.code === 'daily_cap' ? t('mg_no_attempts') : e.code === 'event_not_active' ? t('mg_not_active') : e.message); }
    finally { setBusy(false); }
  };
  const done = useCallback(async (actions) => {
    try {
      const r = await call('/minigames/sorter/finish', { method: 'POST', body: JSON.stringify({ session_id: session.session_id, actions }) });
      setResult(r); load(); setLbKey((k) => k + 1);
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
        <button type="button" onClick={() => (window.history.length > 1 ? navigate(-1) : navigate('/my-businesses'))}
          className="p-2 rounded-lg border border-white/10 bg-black/40 text-white" aria-label={t('page_close')} data-testid="page-close-btn"><X className="w-4 h-4" /></button>
      </div>

      {session ? (
        <SorterRound seed={session.seed} onDone={done} t={t} />
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
              {result.chest && result.chest.reason !== 'disabled' && result.chest.reason !== 'inactive' && !result.rejected && (
                <div className={`mt-2 rounded-xl px-3 py-2 text-sm font-bold ${result.chest.given ? 'bg-amber-400/15 text-amber-200 border border-amber-400/40' : 'bg-white/5 text-white/70 border border-white/10'}`} data-testid="sorter-chest">
                  {result.chest.given ? `🎁 ${t('res_chest_got')}`
                    : result.chest.reason === 'daily_limit' ? fill(t('res_chest_limit'), { n: result.chests_per_day })
                    : fill(t('res_chest_low'), { s: STARS(ev?.chest_min_stars) })}
                  <div className="text-[11px] font-normal text-white/60">{fill(t('cond_today'), { a: result.chests_today ?? 0, b: result.chests_per_day ?? 0 })}</div>
                </div>
              )}
              {(result.new_rewards || []).map((r) => (
                <div key={r.id} className="text-sm font-bold text-fuchsia-200" data-testid="sorter-new-reward">🏅 {fill(t('res_new_reward'), { name: nm(r, lang) })}</div>
              ))}
              {(result.chest?.given || (result.new_rewards || []).length > 0) && (
                <button type="button" onClick={() => navigate('/minigames/rewards?tab=chests')} className="mt-1 text-xs underline text-cyan-300" data-testid="sorter-open-rewards">{t('res_open_rewards')}</button>
              )}
            </div>
          )}
          <div className="rounded-2xl border border-white/10 bg-black/40 p-4 space-y-3">
            <div className="text-sm text-white/80">{t('mg_sorter_pitch')}</div>
            {ev?.active ? (
              <>
                {me && (
                  <div className="grid grid-cols-4 gap-1.5 text-center text-[11px]">
                    <div className="rounded-lg bg-white/5 p-2"><div className="text-text-muted leading-tight">{t('rw_campaign_points')}</div><div className="text-white font-bold text-sm">{(me.points || 0).toLocaleString('ru-RU')}</div></div>
                    <div className="rounded-lg bg-white/5 p-2"><div className="text-text-muted leading-tight">{t('mg_place')}</div><div className="text-white font-bold text-sm">{me.place || '—'}</div></div>
                    <div className="rounded-lg bg-white/5 p-2"><div className="text-text-muted leading-tight">{t('mg_my_best')}</div><div className="text-white font-bold text-sm">{(me.best || 0).toLocaleString('ru-RU')}</div></div>
                    <div className="rounded-lg bg-white/5 p-2"><div className="text-text-muted leading-tight">{t('mg_chests_today')}</div><div className="text-white font-bold text-sm">{me.chests_today ?? 0}/{ev.chests_per_day}</div></div>
                  </div>
                )}
                <button type="button" disabled={busy || (me && me.attempts_left === 0)} onClick={play} data-testid="sorter-play"
                  className="w-full h-14 rounded-xl bg-gradient-to-r from-amber-400 to-orange-500 text-black font-black text-lg disabled:opacity-40">
                  {result ? t('mg_play_again') : t('mg_play')}
                </button>
                {me && me.attempts_left === 0 && <div className="text-xs text-center text-text-muted">{t('mg_no_attempts')}</div>}
                {me && me.attempts_left > 0 && <div className="text-xs text-center text-text-muted">{fill(t('mg_attempts_left'), { n: me.attempts_left })}</div>}
                <button type="button" onClick={() => navigate('/minigames/rewards')} data-testid="sorter-rewards-btn"
                  className="relative w-full h-11 rounded-xl border border-amber-400/40 bg-amber-400/10 text-amber-200 font-bold flex items-center justify-center gap-2">
                  <Gift className="w-4 h-4" />{t('rw_title')}
                  {me && (me.unopened > 0 || me.boosters_available > 0) && <span className="absolute top-2 right-3 w-2.5 h-2.5 rounded-full bg-amber-400 shadow-[0_0_6px_rgba(251,191,36,0.8)]" />}
                </button>
              </>
            ) : (
              <div className="text-sm text-text-muted">{t('mg_not_active')}</div>
            )}
          </div>
          {ev?.active && <ChestConditions t={t} minStars={ev.chest_min_stars} minPoints={ev.chest_min_points} perDay={ev.chests_per_day} today={me?.chests_today ?? 0} />}
          <div className="rounded-2xl border border-white/10 bg-black/40 p-4 space-y-2 text-sm">
            <div className="font-bold text-white">{t('mg_rules_title')}</div>
            <div className="text-white/75 text-xs leading-relaxed">{t('mg_rules_endless')}</div>
            <div className="grid grid-cols-4 gap-1 text-center text-[11px] text-white/80">{BIN_ICON.map((ic, b) => <div key={b} className="rounded bg-white/5 py-1">{ic}<div>{t(BIN_KEY[b])}</div></div>)}</div>
            {ev?.star_points && <div className="text-xs text-text-muted">{t('mg_stars_points')}: ★ {ev.star_points[0]} · ★★ {ev.star_points[1]} · ★★★ {ev.star_points[2]}</div>}
            {ev?.xp_by_stars && <div className="text-xs text-text-muted">{t('mg_stars_xp')}: ★ {ev.xp_by_stars['1']} · ★★ {ev.xp_by_stars['2']} · ★★★ {ev.xp_by_stars['3']} XP</div>}
            {(ev?.prizes || []).length > 0 && (
              <div className="space-y-1" data-testid="sorter-prizes">
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
          <div data-testid="sorter-top"><MgLeaderboard lang={lang} t={t} myId={user?.id} compact refreshKey={lbKey} /></div>
        </div>
      )}
    </div>
  );
}
