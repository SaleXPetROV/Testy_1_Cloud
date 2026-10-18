/**
 * «Общение» → «Альянс». Without an alliance: invitations, own requests, the list / search, «Создать альянс».
 * In an alliance: header (emblem, [TAG], level, AXP to the next level, level-up), the pinned message, the alliance
 * chat button, and tabs Обзор / Участники / Казна / Заявки / Настройки. All texts: translationsAlliances.js (9 languages).
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { toast } from 'sonner';
import { Users, Crown, Shield, Coins, Settings, MessageCircle, Plus, Search, X, ChevronUp, Inbox, LogOut } from 'lucide-react';
import { fill } from '@/lib/translationsMore';
import SmartAvatar from '@/components/SmartAvatar';
import { getResource } from '@/lib/resourceConfig';
import { tBusiness } from '@/lib/translationsExtra';

const API = `${process.env.REACT_APP_BACKEND_URL || ''}/api`;
const auth = () => ({ headers: { Authorization: `Bearer ${localStorage.getItem('token') || localStorage.getItem('ton_city_token') || ''}` } });
const LANGS = { en: '🇬🇧 English', ru: '🇷🇺 Русский', es: '🇪🇸 Español', zh: '🇨🇳 中文', fr: '🇫🇷 Français', de: '🇩🇪 Deutsch', ja: '🇯🇵 日本語', ko: '🇰🇷 한국어', id: '🇮🇩 Indonesia' };
const FLAG = { en: '🇬🇧', ru: '🇷🇺', es: '🇪🇸', zh: '🇨🇳', fr: '🇫🇷', de: '🇩🇪', ja: '🇯🇵', ko: '🇰🇷', id: '🇮🇩' };
const ROLE_STYLE = { leader: 'text-amber-300 border-amber-400/50 bg-amber-400/10', deputy: 'text-fuchsia-300 border-fuchsia-400/40 bg-fuchsia-400/10',
  officer: 'text-cyan-300 border-cyan-400/40 bg-cyan-400/10', member: 'text-white/60 border-white/15 bg-white/5' };
const nf = (n, d = 0) => Number(n || 0).toLocaleString('ru-RU', { maximumFractionDigits: d });
const card = 'rounded-2xl border border-white/10 bg-white/[0.03] p-4';
const inp = 'w-full rounded-xl bg-black/40 border border-white/10 px-3 py-2 text-white text-sm outline-none focus:border-cyber-cyan/60';

function useErr(t) {
  return useCallback((e) => {
    const d = e?.response?.data?.detail;
    if (d && typeof d === 'object' && d.code) {
      const key = `al_err_${d.code}`, s = t(key);
      return s && s !== key ? fill(s, d) : t('al_err_generic');
    }
    return typeof d === 'string' ? d : t('al_err_generic');
  }, [t]);
}

function Modal({ title, onClose, children, testid }) {
  return (
    <div className="fixed inset-0 z-[90] bg-black/70 flex items-end sm:items-center justify-center p-4" onClick={onClose} data-testid={testid}>
      <div className="w-full max-w-md rounded-2xl border border-white/10 bg-[#0b1020] p-4 space-y-3 mb-[var(--bottom-nav-h,0px)] sm:mb-0 max-h-[calc(100dvh-var(--bottom-nav-h,90px)-40px)] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between gap-2">
          <div className="text-white font-bold">{title}</div>
          <button type="button" onClick={onClose} className="text-white/60" aria-label="close"><X className="w-5 h-5" /></button>
        </div>
        {children}
      </div>
    </div>
  );
}

function Confirm({ text, onYes, onNo, t, danger }) {
  return (
    <Modal title={text} onClose={onNo} testid="al-confirm">
      <div className="grid grid-cols-2 gap-2">
        <button type="button" onClick={onNo} className="h-11 rounded-xl border border-white/15 text-white/80">{t('al_cancel')}</button>
        <button type="button" onClick={onYes} data-testid="al-confirm-yes"
          className={`h-11 rounded-xl font-bold ${danger ? 'bg-red-500/80 text-white' : 'bg-cyber-cyan text-black'}`}>{t('al_ok')}</button>
      </div>
    </Modal>
  );
}

// emblem backgrounds (keys = alliances.EMBLEM_BGS); 'neon' is the original look
const EMBLEM_BG = {
  neon: ['#d946ef', '#06b6d4'], violet: ['#8b5cf6', '#4c1d95'], indigo: ['#6366f1', '#1e1b4b'], sky: ['#38bdf8', '#1e3a8a'],
  cyan: ['#22d3ee', '#0e7490'], teal: ['#2dd4bf', '#134e4a'], emerald: ['#34d399', '#065f46'], lime: ['#a3e635', '#3f6212'],
  gold: ['#fde047', '#b45309'], amber: ['#fbbf24', '#78350f'], orange: ['#fb923c', '#9a3412'], crimson: ['#f43f5e', '#7f1d1d'],
  rose: ['#fb7185', '#9f1239'], magenta: ['#f0abfc', '#86198f'], slate: ['#94a3b8', '#1e293b'], night: ['#334155', '#020617'],
};
const bgStyle = (k) => {
  const [c1, c2] = EMBLEM_BG[k] || EMBLEM_BG.neon;
  return { background: `linear-gradient(135deg, ${c1}, ${c2})`, borderColor: `${c1}aa`, boxShadow: `0 0 14px ${c1}40, inset 0 0 10px #ffffff22` };
};

function AllianceBadge({ a, size = 'md' }) {
  const cls = size === 'xl' ? 'w-20 h-20 text-5xl rounded-2xl' : size === 'lg' ? 'w-16 h-16 text-4xl rounded-xl' : 'w-11 h-11 text-2xl rounded-xl';
  return (
    <div className={`${cls} shrink-0 border flex items-center justify-center`} style={bgStyle(a.emblem_bg)} data-testid="al-badge">
      <span style={{ filter: 'drop-shadow(0 2px 3px rgba(0,0,0,.45))' }}>{a.emblem || '🛡️'}</span>
    </div>
  );
}

/** Emblem = picture + background colour, with a live preview of how the alliance will look. */
function EmblemPicker({ me, t, value, onChange, preview }) {
  const bgs = me.emblem_bgs?.length ? me.emblem_bgs : Object.keys(EMBLEM_BG);
  return (
    <div className="space-y-2 text-xs text-text-muted" data-testid="al-emblem-picker">
      <div className="flex items-center gap-3 rounded-xl border border-white/10 bg-black/30 p-3" data-testid="al-emblem-preview">
        <AllianceBadge a={value} size="xl" />
        <div className="min-w-0">
          <div className="text-[10px] uppercase tracking-wider text-text-muted">{t('al_preview')}</div>
          <div className="text-white font-bold truncate"><span className="text-fuchsia-300">[{preview.tag || 'TAG'}]</span> {preview.name || t('al_name')}</div>
          <div className="text-[11px] text-text-muted">{fill(t('al_level'), { n: preview.level || 1 })}</div>
        </div>
      </div>
      <span>{t('al_emblem_bg')}</span>
      <div className="grid grid-cols-8 gap-1.5">
        {bgs.map((k) => (
          <button key={k} type="button" onClick={() => onChange({ emblem_bg: k })} aria-label={k} data-testid={`al-bg-${k}`}
            className={`h-8 rounded-lg border-2 ${value.emblem_bg === k ? 'border-white' : 'border-transparent'}`}
            style={{ background: bgStyle(k).background }} />
        ))}
      </div>
      <span>{t('al_emblem')}</span>
      <div className="grid grid-cols-8 gap-1 max-h-[9.5rem] overflow-y-auto pr-0.5">
        {me.emblems.map((e) => (
          <button key={e} type="button" onClick={() => onChange({ emblem: e })}
            className={`h-9 rounded-lg text-xl ${value.emblem === e ? 'bg-fuchsia-500/30 border border-fuchsia-400/60' : 'bg-white/5 border border-transparent'}`}>{e}</button>
        ))}
      </div>
    </div>
  );
}

// ───────────────────────────── create ─────────────────────────────
function CreateModal({ me, t, onClose, onDone }) {
  const err = useErr(t);
  const [f, setF] = useState({ name: '', tag: '', emblem: me.emblems[0], emblem_bg: (me.emblem_bgs || [])[0] || 'neon', lang: 'ru', join_mode: 'request', description: '' });
  const [busy, setBusy] = useState(false);
  const set = (k, v) => setF((x) => ({ ...x, [k]: v }));
  const cfg = me.config;
  const submit = async () => {
    setBusy(true);
    try { await axios.post(`${API}/alliances`, f, auth()); toast.success(t('al_ok')); onDone(); }
    catch (e) { toast.error(err(e)); }
    finally { setBusy(false); }
  };
  return (
    <Modal title={t('al_create')} onClose={onClose} testid="al-create-modal">
      <div className="text-[11px] text-amber-200/90" data-testid="al-create-reqs">
        {fill(t('al_create_reqs'), { a: cfg.create_min_pass_level, b: cfg.create_requires_business ? t('al_create_biz') : '' })}
      </div>
      <label className="block space-y-1 text-xs text-text-muted"><span>{t('al_name')} · {t('al_name_hint')}</span>
        <input className={inp} maxLength={24} value={f.name} onChange={(e) => set('name', e.target.value)} data-testid="al-create-name" /></label>
      <label className="block space-y-1 text-xs text-text-muted"><span>{t('al_tag')} · {t('al_tag_hint')}</span>
        <input className={`${inp} uppercase font-mono`} maxLength={4} value={f.tag} onChange={(e) => set('tag', e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ''))} data-testid="al-create-tag" /></label>
      <EmblemPicker me={me} t={t} value={f} onChange={(v) => setF((x) => ({ ...x, ...v }))} preview={{ name: f.name, tag: f.tag, level: 1 }} />
      <div className="grid grid-cols-2 gap-2">
        <label className="block space-y-1 text-xs text-text-muted"><span>{t('al_lang')}</span>
          <select className={inp} value={f.lang} onChange={(e) => set('lang', e.target.value)}>
            {Object.entries(LANGS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select></label>
        <label className="block space-y-1 text-xs text-text-muted"><span>{t('al_join_mode')}</span>
          <select className={inp} value={f.join_mode} onChange={(e) => set('join_mode', e.target.value)} data-testid="al-create-mode">
            {['open', 'request', 'invite'].map((m) => <option key={m} value={m}>{t(`al_mode_${m}`)}</option>)}
          </select></label>
      </div>
      <label className="block space-y-1 text-xs text-text-muted"><span>{t('al_desc')}</span>
        <textarea className={inp} rows={2} maxLength={200} value={f.description} onChange={(e) => set('description', e.target.value)} /></label>
      <button type="button" disabled={busy || f.name.trim().length < 3 || f.tag.length < 3} onClick={submit} data-testid="al-create-submit"
        className="w-full h-11 rounded-xl bg-gradient-to-r from-fuchsia-500 to-cyan-500 text-white font-bold disabled:opacity-40">
        {t('al_create')} · {nf(cfg.create_cost_city)} $CITY</button>
    </Modal>
  );
}

// ───────────────────────────── no alliance ─────────────────────────────
function NoAlliance({ me, t, lang, reload }) {
  const err = useErr(t);
  const [q, setQ] = useState('');
  const [list, setList] = useState(null);
  const [create, setCreate] = useState(false);
  const loadList = useCallback(async () => {
    try { const r = await axios.get(`${API}/alliances`, { ...auth(), params: { q, lang } }); setList(r.data.alliances || []); }
    catch (_) { setList([]); }
  }, [q, lang]);
  useEffect(() => { const id = setTimeout(loadList, q ? 300 : 0); return () => clearTimeout(id); }, [loadList, q]);

  const act = async (fn, okMsg) => {
    try { const r = await fn(); if (okMsg) toast.success(okMsg(r?.data)); await reload(); await loadList(); }
    catch (e) { toast.error(err(e)); }
  };
  const join = (a) => act(() => axios.post(`${API}/alliances/${a.id}/join`, {}, auth()),
    (d) => (d?.status === 'joined' ? t('al_joined') : t('al_request_sent')));
  const cancel = (a) => act(() => axios.post(`${API}/alliances/${a.id}/cancel-request`, {}, auth()));
  const answer = (inv, ok) => act(() => axios.post(`${API}/alliances/invites/${inv.id}/${ok ? 'accept' : 'decline'}`, {}, auth()),
    () => (ok ? t('al_joined') : t('al_ok')));

  return (
    <div className="space-y-3" data-testid="al-none">
      <div className={`${card} space-y-2`}>
        <div className="flex items-center gap-2 text-white font-bold"><Shield className="w-5 h-5 text-fuchsia-300" />{t('al_none_title')}</div>
        <p className="text-sm text-white/70">{t('al_none_text')}</p>
        <button type="button" onClick={() => setCreate(true)} data-testid="al-create-btn"
          className="w-full h-11 rounded-xl bg-gradient-to-r from-fuchsia-500 to-cyan-500 text-white font-bold flex items-center justify-center gap-2">
          <Plus className="w-4 h-4" />{t('al_create')} · {nf(me.config.create_cost_city)} $CITY
        </button>
        <div className="text-[11px] text-text-muted">
          {fill(t('al_create_reqs'), { a: me.config.create_min_pass_level, b: me.config.create_requires_business ? t('al_create_biz') : '' })}
        </div>
      </div>

      {(me.invites || []).length > 0 && (
        <div className={`${card} space-y-2 border-fuchsia-400/40`} data-testid="al-invites">
          <div className="text-sm font-bold text-fuchsia-200">{t('al_invites')}</div>
          {me.invites.map((inv) => (
            <div key={inv.id} className="flex items-center gap-3">
              <AllianceBadge a={inv.alliance} />
              <div className="flex-1 min-w-0">
                <div className="text-white text-sm font-bold truncate"><span className="text-fuchsia-300">[{inv.alliance.tag}]</span> {inv.alliance.name}</div>
                <div className="text-[11px] text-text-muted">{fill(t('al_level'), { n: inv.alliance.level })} · {fill(t('al_members_n'), { a: inv.alliance.members_count, b: inv.alliance.slots })}</div>
              </div>
              <button type="button" onClick={() => answer(inv, true)} className="h-9 px-3 rounded-lg bg-emerald-500/80 text-white text-xs font-bold" data-testid="al-invite-accept">{t('al_accept')}</button>
              <button type="button" onClick={() => answer(inv, false)} className="h-9 px-3 rounded-lg border border-white/15 text-white/70 text-xs">{t('al_decline')}</button>
            </div>
          ))}
        </div>
      )}

      <div className={`${card} space-y-3`}>
        <div className="flex items-center justify-between gap-2">
          <div className="text-white font-bold">{t('al_list_title')}</div>
        </div>
        <div className="relative">
          <Search className="w-4 h-4 text-white/40 absolute left-3 top-1/2 -translate-y-1/2" />
          <input className={`${inp} pl-9`} placeholder={t('al_search')} value={q} onChange={(e) => setQ(e.target.value)} data-testid="al-search" />
        </div>
        {list === null ? <div className="text-center text-text-muted py-4">…</div> : list.length === 0 ? (
          <div className="text-center text-text-muted py-4 text-sm">{t('al_list_empty')}</div>
        ) : (
          <div className="divide-y divide-white/5" data-testid="al-list">
            {list.map((a) => {
              const full = a.members_count >= a.slots;
              return (
                <div key={a.id} className="py-2.5 flex items-center gap-3" data-testid={`al-row-${a.tag}`}>
                  <AllianceBadge a={a} />
                  <div className="flex-1 min-w-0">
                    <div className="text-white text-sm font-bold truncate"><span className="text-fuchsia-300">[{a.tag}]</span> {a.name}</div>
                    <div className="text-[11px] text-text-muted truncate">
                      {FLAG[a.lang] || ''} {fill(t('al_level'), { n: a.level })} · {fill(t('al_members_n'), { a: a.members_count, b: a.slots })}
                    </div>
                    {a.description && <div className="text-[11px] text-white/60 truncate">{a.description}</div>}
                  </div>
                  {a.requested ? (
                    <button type="button" onClick={() => cancel(a)} className="h-9 px-2.5 rounded-lg border border-white/15 text-white/60 text-[11px] max-w-[7.5rem] leading-tight">{t('al_requested')}</button>
                  ) : full ? (
                    <span className="text-[11px] text-white/40">{t('al_full')}</span>
                  ) : a.join_mode === 'invite' ? (
                    <span className="text-[11px] text-white/40 max-w-[6rem] text-right leading-tight">{t('al_invite_only')}</span>
                  ) : (
                    <button type="button" onClick={() => join(a)} data-testid={`al-join-${a.tag}`}
                      className="h-9 px-3 rounded-lg bg-cyber-cyan/90 text-black text-xs font-bold shrink-0">{a.join_mode === 'open' ? t('al_join') : t('al_apply')}</button>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
      {create && <CreateModal me={me} t={t} onClose={() => setCreate(false)} onDone={async () => { setCreate(false); await reload(); }} />}
    </div>
  );
}

// ───────────────────────────── in an alliance ─────────────────────────────
function LogLine({ x, t }) {
  const who = x.username || '';
  const amt = x.amount_city ? ` · ${nf(x.amount_city, 2)} $CITY` : '';
  const text = {
    create: `${who} ${t('al_log_create')}`, join: `${who} ${t('al_log_join')}`, leave: `${who} ${t('al_log_leave')}`,
    kick: `${who} ${t('al_log_kick')}`, deposit: `${who} ${t('al_log_deposit')}`, tax: `${t('al_log_tax')} · ${who}`,
    payout: `${t('al_log_payout')} ${who}`, level_up: fill(t('al_log_level_up'), { n: x.meta?.level }),
    role: `${who} · ${t('al_log_role')}: ${t(`al_role_${x.meta?.role || 'member'}`)}`, leader: `${who} ${t('al_log_leader')}`,
    tax_set: fill(t('al_log_tax_set'), { n: x.meta?.pct }),
  }[x.kind] || x.kind;
  const plus = x.kind === 'deposit' || x.kind === 'tax';
  const minus = x.kind === 'payout' || x.kind === 'level_up';
  return (
    <div className="flex items-center justify-between gap-2 py-1.5 text-xs">
      <span className="text-white/80 truncate min-w-0">{text}</span>
      <span className={`shrink-0 ${plus ? 'text-emerald-300' : minus ? 'text-red-300' : 'text-white/40'}`}>
        {amt ? `${plus ? '+' : minus ? '−' : ''}${nf(x.amount_city, 2)}` : ''}
        <span className="text-white/30 ml-2">{new Date(x.created_at).toLocaleDateString()}</span>
      </span>
    </div>
  );
}

function MyAlliance({ me, t, user, reload, lang }) {
  const navigate = useNavigate();
  const err = useErr(t);
  const a = me.alliance, my = me.me, can = my.can;
  const [tab, setTab] = useState('overview');
  const [confirm, setConfirm] = useState(null);
  const [openMember, setOpenMember] = useState(null);
  const [payTo, setPayTo] = useState(null);
  const [payAmt, setPayAmt] = useState('');
  const [dep, setDep] = useState('');
  const [inviteName, setInviteName] = useState('');
  const [pinned, setPinned] = useState(a.pinned || '');
  const [s, setS] = useState({ description: a.description, emblem: a.emblem, emblem_bg: a.emblem_bg, join_mode: a.join_mode, lang: a.lang, tax_pct: a.tax_pct });
  useEffect(() => { setPinned(a.pinned || ''); setS({ description: a.description, emblem: a.emblem, emblem_bg: a.emblem_bg, join_mode: a.join_mode, lang: a.lang, tax_pct: a.tax_pct }); }, [a]);

  const call = async (fn, okMsg) => {
    try { await fn(); if (okMsg) toast.success(okMsg); await reload(); return true; }
    catch (e) { toast.error(err(e)); return false; }
  };
  const nxt = a.next_level;
  const prevAxp = (me.levels[a.level - 1] || {}).axp || 0;
  const pct = nxt ? Math.max(0, Math.min(100, ((a.axp - prevAxp) / Math.max(1, nxt.axp - prevAxp)) * 100)) : 100;
  const ready = nxt && a.axp >= nxt.axp && a.treasury_city >= nxt.fee_city;
  const tabs = [['overview', Shield, t('al_tab_overview')], ['members', Users, t('al_tab_members')], ['treasury', Coins, t('al_tab_treasury')],
    ...(can.requests ? [['requests', Inbox, `${t('al_tab_requests')}${me.requests.length ? ` · ${me.requests.length}` : ''}`]] : []),
    ['settings', Settings, t('al_tab_settings')]];

  return (
    <div className="space-y-3" data-testid="al-mine">
      <div className={`${card} space-y-3 border-fuchsia-400/30 bg-gradient-to-br from-fuchsia-500/[0.07] to-cyan-500/[0.04]`}>
        <div className="flex items-center gap-3">
          <AllianceBadge a={a} size="lg" />
          <div className="flex-1 min-w-0">
            <div className="text-white text-lg font-bold truncate" data-testid="al-name"><span className="text-fuchsia-300">[{a.tag}]</span> {a.name}</div>
            <div className="text-xs text-text-muted">{FLAG[a.lang] || ''} {fill(t('al_level'), { n: a.level })} · {fill(t('al_members_n'), { a: a.members_count, b: a.slots })}</div>
            <div className={`inline-block mt-1 text-[10px] px-2 py-0.5 rounded-full border ${ROLE_STYLE[my.role]}`}>{t(`al_role_${my.role}`)}</div>
          </div>
        </div>
        <div className="space-y-1">
          <div className="flex justify-between text-[11px] text-white/70"><span>{t('al_axp')}</span><span>{nf(a.axp)}{nxt ? ` / ${nf(nxt.axp)}` : ''}</span></div>
          <div className="h-2 rounded-full bg-white/10 overflow-hidden"><div className="h-full bg-gradient-to-r from-fuchsia-500 to-cyan-400" style={{ width: `${pct}%` }} /></div>
          <div className="text-[11px] text-text-muted">{nxt ? fill(t('al_next_level'), { a: nf(nxt.axp), b: nf(nxt.fee_city) }) : t('al_max_level')}</div>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <button type="button" onClick={() => navigate('/chat?channel=alliance')} data-testid="al-chat-btn"
            className="h-10 rounded-xl border border-cyan-400/40 bg-cyan-500/10 text-cyan-200 text-sm font-bold flex items-center justify-center gap-2"><MessageCircle className="w-4 h-4" />{t('al_chat')}</button>
          {can.level_up && nxt ? (
            <button type="button" disabled={!ready} onClick={() => call(() => axios.post(`${API}/alliances/me/level-up`, {}, auth()), t('al_ok'))} data-testid="al-level-up"
              className="h-10 rounded-xl bg-gradient-to-r from-amber-400 to-orange-500 text-black text-sm font-bold flex items-center justify-center gap-1 disabled:opacity-40"><ChevronUp className="w-4 h-4" />{t('al_level_up')}</button>
          ) : (
            <div className="h-10 rounded-xl border border-white/10 text-white/60 text-xs flex flex-col items-center justify-center leading-tight">
              <span>{t('al_treasury_balance')}</span><span className="text-amber-200 font-bold">{nf(a.treasury_city, 2)} $CITY</span>
            </div>
          )}
        </div>
        {(a.pinned || can.pin) && (
          <div className="rounded-xl border border-amber-400/30 bg-amber-400/5 p-2.5 space-y-1.5" data-testid="al-pinned">
            <div className="text-[10px] uppercase tracking-wide text-amber-200/80">📌 {t('al_pinned')}</div>
            {can.pin ? (
              <div className="flex gap-2">
                <input className={inp} maxLength={300} value={pinned} onChange={(e) => setPinned(e.target.value)} />
                <button type="button" onClick={() => call(() => axios.put(`${API}/alliances/me/settings`, { pinned }, auth()), t('al_saved'))}
                  className="px-3 rounded-xl bg-amber-400/90 text-black text-xs font-bold shrink-0">{t('al_pin_save')}</button>
              </div>
            ) : <div className="text-sm text-white/90 whitespace-pre-wrap break-words">{a.pinned}</div>}
          </div>
        )}
      </div>

      <div className="flex flex-wrap gap-1.5" role="tablist">
        {tabs.map(([k, Icon, label]) => (
          <button key={k} type="button" role="tab" aria-selected={tab === k} onClick={() => setTab(k)} data-testid={`al-tab-${k}`}
            className={`shrink-0 h-9 px-3 rounded-xl border text-xs font-bold flex items-center gap-1.5 ${tab === k ? 'border-fuchsia-400/60 bg-fuchsia-400/15 text-fuchsia-200' : 'border-white/10 text-white/60'}`}>
            <Icon className="w-3.5 h-3.5" />{label}
          </button>
        ))}
      </div>

      {tab === 'overview' && (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-2">
            <div className={card}><div className="text-[11px] text-text-muted">{t('al_treasury_balance')}</div><div className="text-amber-200 font-bold">{nf(a.treasury_city, 2)} $CITY</div></div>
            <div className={card}><div className="text-[11px] text-text-muted">{t('al_week_axp')}</div><div className="text-cyan-200 font-bold">{nf(a.axp_week)}</div></div>
            <div className={card}><div className="text-[11px] text-text-muted">{t('al_tax')}</div><div className="text-white font-bold">{a.tax_pct}%</div></div>
            <div className={card}><div className="text-[11px] text-text-muted">{t('al_my_contrib')}</div><div className="text-white font-bold">{nf(my.deposited_city, 2)} $CITY</div></div>
          </div>
          {a.description && <div className={`${card} text-sm text-white/80 whitespace-pre-wrap break-words`}>{a.description}</div>}
          <div className={`${card} space-y-1 text-[11px] text-text-muted`}>
            <div>{fill(t('al_axp_hint'), { n: me.config.axp_share_pct, a: nf(me.config.axp_daily_cap_per_player) })}</div>
            <div>{fill(t('al_tax_hint'), { n: a.tax_pct, a: me.config.tax_change_days })}</div>
          </div>
          <div className={`${card} space-y-2`} data-testid="al-levels">
            <div className="text-sm font-bold text-white">{t('al_levels')}</div>
            {me.levels.map((lv) => (
              <div key={lv.level} className={`flex items-start gap-2 text-xs ${lv.level === a.level ? 'text-white' : lv.level < a.level ? 'text-white/50' : 'text-white/70'}`}>
                <span className={`w-6 h-6 shrink-0 rounded-lg flex items-center justify-center font-bold ${lv.level <= a.level ? 'bg-fuchsia-500/30 text-fuchsia-100' : 'bg-white/5'}`}>{lv.level}</span>
                <div className="flex-1 min-w-0">
                  <div>{fill(t('al_slots_n'), { n: lv.slots })}{lv.level > 1 ? ` · ${nf(lv.axp)} AXP · ${nf(lv.fee_city)} $CITY` : ''}</div>
                  <div className="flex flex-wrap gap-1 mt-0.5">
                    {(lv.unlocks || []).map((u) => (
                      <span key={u} className={`px-1.5 py-0.5 rounded border text-[10px] ${(lv.live || []).includes(u) ? 'border-emerald-400/40 text-emerald-200' : 'border-white/10 text-white/50'}`}>
                        {t(`al_u_${u}`)}{(lv.live || []).includes(u) ? '' : ` · ${t('al_soon')}`}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {tab === 'members' && (
        <div className={`${card} divide-y divide-white/5`} data-testid="al-members">
          {me.members.map((m) => {
            const mine = m.user_id === user?.id;
            const rankOf = { leader: 3, deputy: 2, officer: 1, member: 0 };
            const higher = rankOf[my.role] > rankOf[m.role];
            const canAct = !mine && (can.roles || can.kick || can.payout) && (higher || can.payout);
            return (
              <div key={m.user_id} className="py-2">
                <button type="button" disabled={!canAct} onClick={() => setOpenMember(openMember === m.user_id ? null : m.user_id)}
                  className="w-full flex items-center gap-2 text-left" data-testid={`al-member-${m.username}`}>
                  <SmartAvatar avatar={m.avatar} name={m.username} className="w-9 h-9 rounded-full shrink-0 overflow-hidden" textClassName="text-sm" />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-white truncate">{m.role === 'leader' && <Crown className="w-3.5 h-3.5 inline text-amber-300 mr-1" />}{m.username}{mine ? ' ·' : ''}</div>
                    <div className="text-[10px] text-text-muted">{fill(t('al_axp_total'), { n: nf(m.axp_total) })} · {fill(t('al_deposited'), { n: nf(m.deposited_city) })}</div>
                  </div>
                  <span className={`text-[10px] px-2 py-0.5 rounded-full border shrink-0 ${ROLE_STYLE[m.role]}`}>{t(`al_role_${m.role}`)}</span>
                </button>
                {openMember === m.user_id && canAct && (
                  <div className="mt-2 grid grid-cols-2 gap-1.5" data-testid="al-member-actions">
                    {can.roles && higher && ['deputy', 'officer', 'member'].filter((r) => r !== m.role && (my.role === 'leader' || r !== 'deputy')).map((r) => (
                      <button key={r} type="button" onClick={() => call(() => axios.post(`${API}/alliances/me/members/${m.user_id}/role`, { role: r }, auth()), t('al_ok'))}
                        className="h-8 rounded-lg border border-white/15 text-white/80 text-[11px]">{t(`al_make_${r}`)}</button>
                    ))}
                    {can.payout && (
                      <button type="button" onClick={() => { setPayTo(m); setPayAmt(''); }} className="h-8 rounded-lg border border-amber-400/40 text-amber-200 text-[11px]">{t('al_pay')}</button>
                    )}
                    {can.transfer && (
                      <button type="button" onClick={() => setConfirm({ text: fill(t('al_confirm_leader'), { name: m.username }), go: () => axios.post(`${API}/alliances/me/members/${m.user_id}/leader`, {}, auth()) })}
                        className="h-8 rounded-lg border border-amber-400/40 text-amber-200 text-[11px]">{t('al_make_leader')}</button>
                    )}
                    {can.kick && higher && (
                      <button type="button" onClick={() => setConfirm({ danger: true, text: fill(t('al_confirm_kick'), { name: m.username }), go: () => axios.post(`${API}/alliances/me/members/${m.user_id}/kick`, {}, auth()) })}
                        className="h-8 rounded-lg border border-red-400/40 text-red-300 text-[11px]">{t('al_kick')}</button>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {tab === 'treasury' && (
        <div className="space-y-3">
          <div className={`${card} space-y-2`}>
            <div className="flex items-baseline justify-between"><span className="text-sm text-white/80">{t('al_treasury_balance')}</span>
              <span className="text-xl text-amber-200 font-black" data-testid="al-treasury">{nf(a.treasury_city, 2)} $CITY</span></div>
            <div className="text-[11px] text-text-muted">{fill(t('al_deposit_hint'), { a: nf(me.config.deposit_min_city), b: nf(me.config.deposit_daily_cap_city) })}</div>
            <div className="flex gap-2">
              <input className={inp} inputMode="decimal" placeholder={t('al_amount')} value={dep} onChange={(e) => setDep(e.target.value.replace(/[^0-9.]/g, ''))} data-testid="al-deposit-input" />
              <button type="button" disabled={!Number(dep)} data-testid="al-deposit-btn"
                onClick={async () => { if (await call(() => axios.post(`${API}/alliances/me/deposit`, { amount_city: Number(dep) }, auth()), t('al_ok'))) setDep(''); }}
                className="px-4 rounded-xl bg-gradient-to-r from-green-500 to-emerald-600 text-white text-sm font-bold shrink-0 disabled:opacity-40">{t('al_deposit')}</button>
            </div>
          </div>
          <div className={`${card} divide-y divide-white/5`} data-testid="al-log">
            <div className="text-sm font-bold text-white pb-1">{t('al_log')}</div>
            {me.log.length === 0 ? <div className="text-xs text-text-muted py-2">{t('al_log_empty')}</div> : me.log.map((x, i) => <LogLine key={i} x={x} t={t} />)}
          </div>
        </div>
      )}

      {tab === 'requests' && can.requests && (
        <div className="space-y-3">
          <div className={`${card} space-y-2`}>
            <div className="text-sm font-bold text-white">{t('al_invite_user')}</div>
            <div className="flex gap-2">
              <input className={inp} placeholder={t('al_username')} value={inviteName} onChange={(e) => setInviteName(e.target.value)} data-testid="al-invite-input" />
              <button type="button" disabled={!inviteName.trim()} data-testid="al-invite-btn"
                onClick={async () => { if (await call(() => axios.post(`${API}/alliances/me/invite`, { username: inviteName }, auth()), t('al_invited'))) setInviteName(''); }}
                className="px-4 rounded-xl bg-cyber-cyan text-black text-sm font-bold shrink-0 disabled:opacity-40">{t('al_invite_btn')}</button>
            </div>
          </div>
          <div className={`${card} divide-y divide-white/5`} data-testid="al-requests">
            {me.requests.length === 0 ? <div className="text-xs text-text-muted">{t('al_requests_empty')}</div> : me.requests.map((r) => (
              <div key={r.id} className="py-2.5 space-y-2" data-testid={`al-request-${r.username}`}>
                <div className="flex items-center gap-2">
                  <div className="flex-1 min-w-0 text-sm text-white font-semibold truncate">{r.username}</div>
                  <button type="button" onClick={() => call(() => axios.post(`${API}/alliances/me/requests/${r.id}/accept`, {}, auth()), t('al_ok'))}
                    className="h-8 px-3 rounded-lg bg-emerald-500/80 text-white text-xs font-bold" data-testid="al-req-accept">{t('al_accept')}</button>
                  <button type="button" onClick={() => call(() => axios.post(`${API}/alliances/me/requests/${r.id}/decline`, {}, auth()))}
                    className="h-8 px-3 rounded-lg border border-white/15 text-white/70 text-xs">{t('al_decline')}</button>
                </div>
                {/* what the player has: businesses and what they produce per day */}
                {(r.businesses || []).length === 0 ? (
                  <div className="text-[11px] text-text-muted">{t('al_req_no_business')}</div>
                ) : (
                  <div className="space-y-1" data-testid="al-request-businesses">
                    {r.businesses.map((b, i) => {
                      const res = b.produces ? getResource(b.produces, lang) : null;
                      return (
                        <div key={i} className="flex items-center justify-between gap-2 rounded-lg bg-white/5 px-2 py-1 text-[11px]">
                          <span className="text-white/90 truncate min-w-0">{tBusiness(b.type, lang)} · {fill(t('al_level'), { n: b.level })}{b.active ? '' : ` · ${t('al_biz_idle')}`}</span>
                          {res && <span className="shrink-0 text-emerald-300">{res.icon} {res.name} {nf(b.per_day, 2)}/{t('al_per_day')}</span>}
                        </div>
                      );
                    })}
                    {Object.keys(r.produces_per_day || {}).length > 1 && (
                      <div className="text-[10px] text-text-muted pt-0.5">{t('al_req_total')}: {Object.entries(r.produces_per_day).map(([rid, v]) => `${getResource(rid, lang)?.icon || ''} ${nf(v, 2)}`).join(' · ')}</div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {tab === 'settings' && (
        <div className="space-y-3">
          {can.settings && (
            <div className={`${card} space-y-3`} data-testid="al-settings">
              <label className="block space-y-1 text-xs text-text-muted"><span>{t('al_desc')}</span>
                <textarea className={inp} rows={2} maxLength={200} value={s.description} onChange={(e) => setS({ ...s, description: e.target.value })} /></label>
              <EmblemPicker me={me} t={t} value={s} onChange={(v) => setS((x) => ({ ...x, ...v }))} preview={{ name: a.name, tag: a.tag, level: a.level }} />
              <div className="grid grid-cols-2 gap-2">
                <label className="block space-y-1 text-xs text-text-muted"><span>{t('al_join_mode')}</span>
                  <select className={inp} value={s.join_mode} onChange={(e) => setS({ ...s, join_mode: e.target.value })}>
                    {['open', 'request', 'invite'].map((m) => <option key={m} value={m}>{t(`al_mode_${m}`)}</option>)}
                  </select></label>
                <label className="block space-y-1 text-xs text-text-muted"><span>{t('al_lang')}</span>
                  <select className={inp} value={s.lang} onChange={(e) => setS({ ...s, lang: e.target.value })}>
                    {Object.entries(LANGS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select></label>
                {can.tax && (
                  <label className="block space-y-1 text-xs text-text-muted"><span>{t('al_tax')}, % (0–{me.config.tax_max_pct})</span>
                    <input className={inp} type="number" min={0} max={me.config.tax_max_pct} value={s.tax_pct} onChange={(e) => setS({ ...s, tax_pct: e.target.value })} data-testid="al-tax-input" /></label>
                )}
              </div>
              <button type="button" data-testid="al-settings-save"
                onClick={() => call(() => axios.put(`${API}/alliances/me/settings`, { ...s, tax_pct: Number(s.tax_pct || 0) }, auth()), t('al_saved'))}
                className="w-full h-10 rounded-xl bg-cyber-cyan text-black text-sm font-bold">{t('al_save')}</button>
            </div>
          )}
          <div className={`${card} space-y-2`}>
            {my.role !== 'leader' || a.members_count <= 1 ? (
              <button type="button" data-testid="al-leave"
                onClick={() => setConfirm({ danger: true, text: my.role === 'leader' ? t('al_confirm_disband') : fill(t('al_confirm_leave'), { n: me.config.rejoin_cooldown_hours }),
                  go: () => axios.post(`${API}/alliances/me/leave`, {}, auth()) })}
                className="w-full h-10 rounded-xl border border-red-400/40 text-red-300 text-sm font-bold flex items-center justify-center gap-2"><LogOut className="w-4 h-4" />{my.role === 'leader' ? t('al_disband') : t('al_leave')}</button>
            ) : (
              <button type="button" data-testid="al-disband"
                onClick={() => setConfirm({ danger: true, text: t('al_confirm_disband'), go: () => axios.post(`${API}/alliances/me/disband`, {}, auth()) })}
                className="w-full h-10 rounded-xl border border-red-400/40 text-red-300 text-sm font-bold">{t('al_disband')}</button>
            )}
          </div>
        </div>
      )}

      {payTo && (
        <Modal title={`${t('al_pay')} · ${payTo.username}`} onClose={() => setPayTo(null)} testid="al-pay-modal">
          <div className="text-[11px] text-text-muted">{t('al_treasury_balance')}: {nf(a.treasury_city, 2)} $CITY</div>
          <input className={inp} inputMode="decimal" placeholder={t('al_amount')} value={payAmt} onChange={(e) => setPayAmt(e.target.value.replace(/[^0-9.]/g, ''))} />
          <button type="button" disabled={!Number(payAmt)}
            onClick={async () => { if (await call(() => axios.post(`${API}/alliances/me/payout`, { user_id: payTo.user_id, amount_city: Number(payAmt) }, auth()), t('al_ok'))) setPayTo(null); }}
            className="w-full h-11 rounded-xl bg-gradient-to-r from-amber-400 to-orange-500 text-black font-bold disabled:opacity-40">{t('al_pay')}</button>
        </Modal>
      )}
      {confirm && (
        <Confirm t={t} text={confirm.text} danger={confirm.danger} onNo={() => setConfirm(null)}
          onYes={async () => { const c = confirm; setConfirm(null); setOpenMember(null); await call(c.go, t('al_ok')); }} />
      )}
    </div>
  );
}

export default function AllianceView({ user, lang, t, refreshUser }) {
  const [me, setMe] = useState(null);
  const load = useCallback(async () => {
    try { const r = await axios.get(`${API}/alliances/me`, auth()); setMe(r.data); }
    catch (_) { setMe((x) => x || { alliance: null, config: {}, levels: [], emblems: [] }); }
    if (refreshUser) refreshUser();
  }, [refreshUser]);
  useEffect(() => { load(); }, [load]);
  // the page's scroll area sizes itself by the widest line (Radix «display: table»): a definite width keeps
  // long names / logs truncated inside the screen instead of widening the whole page
  const box = 'w-[min(48rem,calc(100vw-2rem))] lg:w-[min(48rem,calc(100vw-7rem))] min-w-0';
  const view = useMemo(() => {
    if (!me) return <div className="text-center text-text-muted py-10">…</div>;
    if (me.config && me.config.enabled === false && !me.alliance) return <div className="text-center text-text-muted py-10">{t('al_err_disabled')}</div>;
    return me.alliance ? <MyAlliance me={me} t={t} user={user} reload={load} lang={lang} /> : <NoAlliance me={me} t={t} lang={lang} reload={load} />;
  }, [me, t, user, lang, load]);
  return <div className={box} data-testid="al-root">{view}</div>;
}
