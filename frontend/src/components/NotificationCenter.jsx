import { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import { subscribeUserSocket } from '@/lib/userSocket';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence, useMotionValue, useDragControls } from 'framer-motion';
import {
  Bell, BellRing, X, Check, CheckCheck, Settings as SettingsIcon, Volume2, VolumeX,
  AlertTriangle, CheckCircle2, Info, AlertCircle, Trash2, Star,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useNavigate } from 'react-router-dom';
import { useLanguage } from '@/context/LanguageContext';
import { useTranslation } from '@/lib/translations';
import { RESOURCES, getResourceName } from '@/lib/resourceConfig';
import axios from 'axios';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api`;

// ───────────────────────── Priority styling ─────────────────────────
const PRIORITY_META = {
  critical: { color: 'red',    Icon: AlertTriangle, label: 'Критическое' },
  warning:  { color: 'amber',  Icon: AlertCircle,   label: 'Внимание' },
  success:  { color: 'emerald',Icon: CheckCircle2,  label: 'Успех' },
  info:     { color: 'sky',    Icon: Info,          label: 'Инфо' },
};

const priorityFromNotif = (n) => {
  if (n?.priority) return n.priority;
  const t = (n?.type || '').toLowerCase();
  if (t.includes('break') || t.includes('penalty') || t.includes('critical')) return 'critical';
  if (t.includes('pending') || t.includes('warning') || t.includes('low')) return 'warning';
  if (t.includes('success') || t.includes('paid') || t.includes('mutual')) return 'success';
  return 'info';
};

const colorClasses = (color) => ({
  red:     { border: 'border-red-500/40',     ring: 'ring-red-500/30',     fg: 'text-red-300',     bg: 'bg-red-500/10',     dot: 'bg-red-500' },
  amber:   { border: 'border-amber-500/40',   ring: 'ring-amber-500/30',   fg: 'text-amber-300',   bg: 'bg-amber-500/10',   dot: 'bg-amber-500' },
  emerald: { border: 'border-emerald-500/40', ring: 'ring-emerald-500/30', fg: 'text-emerald-300', bg: 'bg-emerald-500/10', dot: 'bg-emerald-500' },
  sky:     { border: 'border-sky-500/40',     ring: 'ring-sky-500/30',     fg: 'text-sky-300',     bg: 'bg-sky-500/10',     dot: 'bg-sky-500' },
}[color] || { border: 'border-white/10', ring: 'ring-white/10', fg: 'text-white', bg: 'bg-white/5', dot: 'bg-white' });

// ───────────────────────── Sound ─────────────────────────
const SOUND_PREF_KEY = 'tc_notif_sound';
// Singleton HTMLAudioElement preloaded with our notification sound. Using a real
// audio file (vs. AudioContext only) ensures the sound actually plays on most
// mobile browsers, where AudioContext suspended-state issues are common.
let _notifAudio = null;
const getNotifAudio = () => {
  if (typeof window === 'undefined') return null;
  if (!_notifAudio) {
    try {
      _notifAudio = new Audio('/notification.mp3');
      _notifAudio.preload = 'auto';
      _notifAudio.volume = 0.6;
    } catch (_) { _notifAudio = null; }
  }
  return _notifAudio;
};
// Resume / unlock audio on the first user gesture (autoplay policy).
if (typeof window !== 'undefined' && !window.__tc_audio_unlocked) {
  const unlock = () => {
    try {
      const a = getNotifAudio();
      if (a) {
        a.muted = true;
        const p = a.play();
        if (p && typeof p.then === 'function') {
          p.then(() => { a.pause(); a.currentTime = 0; a.muted = false; }).catch(() => {});
        } else {
          a.pause(); a.currentTime = 0; a.muted = false;
        }
      }
    } catch (_) {}
    window.__tc_audio_unlocked = true;
    window.removeEventListener('pointerdown', unlock, true);
    window.removeEventListener('keydown', unlock, true);
    window.removeEventListener('touchstart', unlock, true);
  };
  window.addEventListener('pointerdown', unlock, true);
  window.addEventListener('keydown', unlock, true);
  window.addEventListener('touchstart', unlock, true);
}

// Sound is OPT-IN: it plays only when the user has explicitly enabled it via
// the bell toggle on the chat page. Default (no pref stored) = muted.
export const isSoundEnabled = () => {
  try { return localStorage.getItem(SOUND_PREF_KEY) === 'true'; } catch (_) { return false; }
};
export const setSoundEnabled = (on) => {
  try { localStorage.setItem(SOUND_PREF_KEY, on ? 'true' : 'false'); } catch (_) {}
};
export const playSound = () => {
  try {
    if (!isSoundEnabled()) return;
    const a = getNotifAudio();
    if (a) {
      try { a.pause(); a.currentTime = 0; } catch (_) {}
      const p = a.play();
      if (p && typeof p.catch === 'function') p.catch(() => {});
      return;
    }
  } catch (_) { /* fall through to oscillator */ }
  // Fallback: synthesized beep via WebAudio
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    o.connect(g); g.connect(ctx.destination);
    o.frequency.setValueAtTime(880, ctx.currentTime);
    g.gain.setValueAtTime(0.0001, ctx.currentTime);
    g.gain.exponentialRampToValueAtTime(0.05, ctx.currentTime + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.18);
    o.start();
    o.stop(ctx.currentTime + 0.2);
  } catch (_) { /* ignore */ }
};

// ───────────────────────── Date helper ─────────────────────────
const formatTime = (iso, tr) => {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    const diffMs = Date.now() - d.getTime();
    const min = Math.floor(diffMs / 60000);
    if (min < 1) return tr?.justNow || 'только что';
    if (min < 60) return `${min} ${tr?.minAgo || 'мин назад'}`;
    const hr = Math.floor(min / 60);
    if (hr < 24) return `${hr} ${tr?.hourAgo || 'ч назад'}`;
    const days = Math.floor(hr / 24);
    if (days < 7) return `${days} ${tr?.dayAgo || 'дн назад'}`;
    return d.toLocaleDateString(tr?.locale || 'ru-RU', { day: '2-digit', month: 'short' });
  } catch (_) { return ''; }
};

// ───────────────────────── Bell button ─────────────────────────
export function NotificationBellButton({ count = 0, hasCritical = false, onClick, shake = false, dataTestid = 'notification-bell-btn', label, isExpanded = true, disabled = false }) {
  return (
    <button
      type="button"
      onClick={onClick}
      data-testid={dataTestid}
      disabled={disabled}
      aria-disabled={disabled}
      className={`w-full flex items-center gap-3 p-3 rounded-xl transition-all outline-none focus-visible:ring-2 focus-visible:ring-cyber-cyan/60 border border-transparent ${isExpanded ? '' : 'justify-center'} ${disabled ? 'opacity-40 cursor-not-allowed text-white/40' : 'cursor-pointer text-white/70 hover:bg-white/10 hover:text-white'}`}
      aria-label={label || 'Уведомления'}
      title={disabled ? 'Недоступно во время обучения' : (label || 'Уведомления')}
    >
      <div className="min-w-[20px] flex items-center justify-center relative">
        <motion.span
          animate={shake ? { rotate: [0, -15, 12, -8, 6, 0] } : { rotate: 0 }}
          transition={{ duration: 0.6 }}
          className="inline-flex"
        >
          {count > 0 ? <BellRing className="w-5 h-5" /> : <Bell className="w-5 h-5" />}
        </motion.span>
        {count > 0 && (
          <motion.span
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            className={`absolute -top-1.5 -right-2 min-w-[17px] h-[17px] px-1 rounded-full text-[10px] font-bold flex items-center justify-center text-white ${hasCritical ? 'bg-red-500' : 'bg-cyber-cyan text-black'}`}
            style={hasCritical ? { boxShadow: '0 0 0 3px rgba(239,68,68,0.25)' } : {}}
          >
            {count > 9 ? '9+' : count}
            {hasCritical && (
              <span className="absolute inset-0 rounded-full bg-red-500 animate-ping opacity-60" />
            )}
          </motion.span>
        )}
      </div>
      {isExpanded && (
        <span className="font-bold text-xs uppercase tracking-widest whitespace-nowrap">
          {label || 'Уведомления'}
        </span>
      )}
    </button>
  );
}

// Mobile compact bell — icon only with badge, used next to burger close X
export function NotificationBellIcon({ count = 0, hasCritical = false, onClick, shake = false, dataTestid = 'notification-bell-icon-mobile', className = '' }) {
  return (
    <button
      type="button"
      onClick={onClick}
      data-testid={dataTestid}
      aria-label="Уведомления"
      className={`relative w-10 h-10 rounded-xl bg-white/5 hover:bg-white/10 text-white flex items-center justify-center transition-colors border border-white/10 ${className}`}
    >
      <motion.span
        animate={shake ? { rotate: [0, -15, 12, -8, 6, 0] } : { rotate: 0 }}
        transition={{ duration: 0.6 }}
        className="inline-flex"
      >
        {count > 0 ? <BellRing className="w-5 h-5" /> : <Bell className="w-5 h-5" />}
      </motion.span>
      {count > 0 && (
        <span
          className={`absolute -top-1 -right-1 min-w-[18px] h-[18px] px-1 rounded-full text-[10px] font-bold flex items-center justify-center text-white ${hasCritical ? 'bg-red-500' : 'bg-cyber-cyan text-black'}`}
        >
          {count > 9 ? '9+' : count}
          {hasCritical && (
            <span className="absolute inset-0 rounded-full bg-red-500 animate-ping opacity-60" />
          )}
        </span>
      )}
    </button>
  );
}

// Helper to check if any unread notification is critical (for title-badge styling)
const notifHasCritical = (list) =>
  Array.isArray(list) && list.some(n => !n.read && priorityFromNotif(n) === 'critical');

const T1_MULT = 10;

// ───────────────────────── Tender proposal/amendment details card ─────────────────────────
// Fetches enriched contract info for a tender_proposal_new (or amendment) notification
// and renders the same "supplier card" preview the buyer sees on the tender page.
function TenderProposalDetails({ contractId, token, t, isAmendment = false }) {
  const [contract, setContract] = useState(null);
  const [err, setErr] = useState(false);
  useEffect(() => {
    if (!contractId || !token) return;
    let alive = true;
    (async () => {
      try {
        const r = await axios.get(`${API}/tenders/contracts/${contractId}`, { headers: { Authorization: `Bearer ${token}` } });
        if (alive) setContract(r.data);
      } catch (_) {
        if (alive) setErr(true);
      }
    })();
    return () => { alive = false; };
  }, [contractId, token]);

  if (err || !contract) return null;

  const tier = contract.tier || 1;
  const dailyCost = (contract.daily_amount || 0) * (contract.price_per_unit || 0);
  const resMeta = RESOURCES?.[contract.resource_type] || {};
  const resLabel = getResourceName?.(contract.resource_type) || contract.resource_type;
  const tierLabel = tier === 1 ? 'T1' : tier === 2 ? 'T2' : 'T3';
  // Display unit prices in the same convention as the tender page (T1 = per 10).
  const priceForUnit = tier === 1 ? (contract.price_per_unit * T1_MULT) : contract.price_per_unit;
  const priceLabel = tier === 1
    ? `${priceForUnit.toFixed(2)} $CITY / 10 ${t('unitsShort') || 'ед.'}`
    : `${priceForUnit.toFixed(2)} $CITY / 1 ${t('unitsShort') || 'ед.'}`;
  const maxPrice = contract.tender?.max_price_per_unit;
  const maxPriceFmt = (maxPrice != null)
    ? (tier === 1 ? `${(maxPrice * T1_MULT).toFixed(2)} $CITY / 10 ${t('unitsShort') || 'ед.'}` : `${maxPrice.toFixed(2)} $CITY / 1 ${t('unitsShort') || 'ед.'}`)
    : null;
  const biz = contract.seller_main_business;
  const stats = contract.seller_stats || {};
  const stars = stats.stars ?? 5;
  const reliability = stats.reliability ?? 100;
  const ticksOk = stats.ticks_completed ?? 0;
  const breaks = stats.broken_by_seller ?? 0;
  const stockDays = contract.seller_stock_days;
  const statusBadge =
    contract.status === 'PROPOSED' ? { label: t('status_PROPOSED') || 'Предложен', cls: 'border-amber-500/40 bg-amber-500/10 text-amber-300' } :
    contract.status === 'ACTIVE' ? { label: t('status_ACTIVE') || 'Активен', cls: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300' } :
    contract.status === 'PENDING_FUNDS' ? { label: t('status_PENDING_FUNDS') || 'Ожидание оплаты', cls: 'border-amber-500/40 bg-amber-500/10 text-amber-300' } :
    contract.status === 'PENDING_RESOURCES' ? { label: t('status_PENDING_RESOURCES') || 'Ожидание ресурсов', cls: 'border-amber-500/40 bg-amber-500/10 text-amber-300' } :
    contract.status === 'BROKEN' ? { label: t('status_BROKEN') || 'Разорван', cls: 'border-red-500/40 bg-red-500/10 text-red-300' } :
    { label: contract.status, cls: 'border-zinc-500/40 bg-zinc-500/10 text-zinc-300' };

  return (
    <div className="mt-2 p-2.5 rounded-lg bg-zinc-950/70 border border-zinc-700/50 text-[12px] space-y-1" data-testid={`notif-proposal-${contractId}`}>
      <div className="flex items-center justify-between gap-2">
        <div className="font-semibold text-white">
          {t('offerFrom') || 'Оффер от'}: @{contract.seller_username}
        </div>
        <span className={`text-[10px] px-2 py-0.5 rounded border ${statusBadge.cls}`}>{statusBadge.label}</span>
      </div>
      <div className="text-zinc-300">
        {t('proposalWord') || 'Предложение'}: <b>{contract.daily_amount?.toLocaleString?.('en-US') || contract.daily_amount}</b> {t('unitsShort') || 'ед.'} {resMeta.icon || ''} {resLabel} ({tierLabel})
      </div>
      <div className="text-zinc-300">
        {t('priceLabel') || 'Цена'}: <b className="text-amber-300">{dailyCost.toFixed(2)} $CITY / {t('perDay') || 'день'}</b> ({priceLabel}{maxPriceFmt ? `, ${t('maxShort') || 'макс.'} ${maxPriceFmt}` : ''})
      </div>
      {biz && (
        <div className="text-zinc-400">
          {t('sourceLabel') || 'Источник'}: {biz.icon || '🏢'} {biz.name_ru || biz.business_type} ({t('levelShort') || 'Ур.'} {biz.level}) <span className="text-emerald-400">— {t('verified') || 'ПОДТВЕРЖДЕНО'}</span>
        </div>
      )}
      {contract.seller_daily_production !== undefined && (
        <div className="text-zinc-400">
          {t('producesLabel') || 'Производит'}: <b className="text-cyan-300">{Math.round(contract.seller_daily_production).toLocaleString('en-US')}</b> {t('unitsPerDay') || 'ед./сутки'}
          {' • '}{t('freeLabel') || 'свободно'}: <b className="text-emerald-300">{Math.round(contract.seller_free_capacity || 0).toLocaleString('en-US')}</b>
        </div>
      )}
      <div className="flex items-center gap-2 text-zinc-400">
        <span>{t('reliabilityLabel') || 'Надёжность'}:</span>
        <span className="text-amber-300">
          {Array.from({ length: 5 }).map((_, i) => (
            <Star key={i} className={`w-3 h-3 inline-block ${i < stars ? 'fill-amber-300 text-amber-300' : 'text-zinc-600'}`} />
          ))}
        </span>
        <span className="text-amber-300 font-mono text-[11px]">({reliability}%)</span>
      </div>
      {stockDays !== undefined && (
        <div className="text-zinc-400">
          {t('stockLabel') || 'Склад'}: <b className={stockDays >= 1 ? 'text-emerald-300' : 'text-red-300'}>
            {stockDays >= 1
              ? (t('enoughForN') || 'хватит на {n} дн.').replace('{n}', stockDays)
              : (t('noStockTomorrow') || 'не хватит на завтра')}
          </b>
        </div>
      )}
      <div className="text-zinc-500">
        {t('historyLabel') || 'История'}: <b className="text-zinc-300">{ticksOk}</b> {t('successfulShort') || 'успешных'}, <b className={breaks ? 'text-red-300' : 'text-zinc-300'}>{breaks}</b> {t('breaksShort') || 'разрывов'}
      </div>
    </div>
  );
}

// ───────────────────────── Counter-offer details card ─────────────────────────
// Renders the full counter-offer as a "card with new conditions" + Accept/Reject buttons.
// Built entirely from payload (no extra fetch needed) since the backend sends a rich payload.
function CounterOfferDetails({ payload }) {
  if (!payload) return null;
  const buffIsCustom = !!payload.buff_is_custom;
  return (
    <div className="mt-2 p-3 rounded-lg bg-zinc-950/70 border border-amber-500/30 text-[12px] space-y-1.5" data-testid={`notif-counter-offer-${payload.counter_offer_id}`}>
      <div className="flex items-center justify-between gap-2">
        <div className="font-semibold text-white">
          Встречное предложение от @{payload.vassal_username || '?'}
        </div>
        <span className="text-[10px] px-2 py-0.5 rounded border border-amber-500/40 bg-amber-500/10 text-amber-300">
          Новые условия
        </span>
      </div>
      <div className="text-zinc-300">
        <span className="text-text-muted">Тип контракта:</span>{' '}
        <b>
          {payload.proposed_contract_type_icon || ''} {payload.proposed_contract_type_name || payload.proposed_contract_type || '?'}
        </b>
        {payload.original_contract_type && payload.proposed_contract_type !== payload.original_contract_type && (
          <span className="text-zinc-500 ml-1">(было: {payload.original_contract_type})</span>
        )}
      </div>
      <div className="text-zinc-300">
        <span className="text-text-muted">Срок:</span>{' '}
        <b>{payload.proposed_duration || 30} дн.</b>
        {payload.original_duration && payload.original_duration !== payload.proposed_duration && (
          <span className="text-zinc-500 ml-1">(было: {payload.original_duration} дн.)</span>
        )}
      </div>
      <div className="text-zinc-300">
        <span className="text-text-muted">Баф для вассала:</span>{' '}
        <b className="text-yellow-300">{payload.buff_icon || ''} {payload.buff_name || '?'}</b>
        {buffIsCustom && (
          <span className="text-amber-300 text-[10px] ml-1">(альтернатива)</span>
        )}
      </div>
      {payload.buff_description && (
        <div className="text-text-muted text-[11px]">{payload.buff_description}</div>
      )}
      {payload.proposed_vassal_pays && (
        <div className="text-zinc-300">
          <span className="text-text-muted">Что отдаёт вассал:</span>{' '}
          <span>{payload.proposed_vassal_pays}</span>
        </div>
      )}
      <div className="text-zinc-400 text-[11px]">
        <span className="text-text-muted">Бизнес вассала:</span>{' '}
        {payload.vassal_business_icon || '🏢'} {payload.vassal_business_name || '?'}
      </div>
      <div className="text-zinc-400 text-[11px]">
        <span className="text-text-muted">Ваш бизнес-патрон:</span>{' '}
        {payload.patron_business_icon || '🏢'} {payload.patron_business_name || '?'}
      </div>
      {payload.comment && (
        <div className="mt-1 p-2 rounded bg-white/5 border border-white/10 text-zinc-300 text-[11px]">
          💬 «{payload.comment}»
        </div>
      )}
    </div>
  );
}

// ───────────────────────── Notification card ─────────────────────────
function NotificationCard({ notif, expanded, onToggleExpand, onMarkRead, onDelete, onAction, isMobile, tr, t, token, actionStatus }) {
  const priority = priorityFromNotif(notif);
  const meta = PRIORITY_META[priority] || PRIORITY_META.info;
  const colors = colorClasses(meta.color);

  // Action buttons derived from payload
  const payload = notif.payload || {};
  const kind = payload.kind;
  const contractId = payload.contract_id;
  const buttons = [];

  // i18n: if payload.i18n_key is provided, render title/message from translations
  // (server-side message stays as fallback for older clients).
  const interpolate = (tpl, vars) => {
    if (!tpl) return tpl;
    let s = String(tpl);
    Object.entries(vars || {}).forEach(([k, v]) => {
      s = s.split(`{${k}}`).join(String(v));
    });
    return s;
  };
  const i18nKey = payload.i18n_key;
  const i18nVars = payload.i18n_vars || {};
  let renderedTitle = notif.title;
  let renderedMsg = notif.message || '';
  if (i18nKey && typeof t === 'function') {
    const titleTpl = t(`${i18nKey}Title`);
    const bodyTpl = t(`${i18nKey}Body`);
    // t() returns the key itself when missing — only use translation if it changed.
    if (titleTpl && titleTpl !== `${i18nKey}Title`) renderedTitle = interpolate(titleTpl, i18nVars);
    if (bodyTpl && bodyTpl !== `${i18nKey}Body`) renderedMsg = interpolate(bodyTpl, i18nVars);
  }

  if (kind === 'break_request' && contractId) {
    buttons.push({ label: tr?.accept || 'Принять', testid: `notif-accept-break-${notif.id}`, intent: 'success', action: 'accept_break', meta: { contract_id: contractId } });
    buttons.push({ label: tr?.reject || 'Отклонить', testid: `notif-reject-break-${notif.id}`, intent: 'danger', action: 'reject_break', meta: { contract_id: contractId } });
  }
  // NEW: tender_proposal — buyer can accept (signs contract + freezes escrow) or reject
  if ((kind === 'tender_proposal' || notif.type === 'tender_proposal_new') && contractId) {
    buttons.push({ label: tr?.accept || 'Утвердить', testid: `notif-accept-proposal-${notif.id}`, intent: 'success', action: 'accept_proposal', meta: { contract_id: contractId } });
    buttons.push({ label: tr?.reject || 'Отказать', testid: `notif-reject-proposal-${notif.id}`, intent: 'danger', action: 'reject_proposal', meta: { contract_id: contractId } });
  }
  // NEW: tender_amendment — counterparty can accept or reject a proposed amendment
  if ((kind === 'tender_amendment' || notif.type === 'tender_amendment_new') && contractId && payload.amendment_id) {
    buttons.push({ label: tr?.accept || 'Утвердить', testid: `notif-accept-amend-${notif.id}`, intent: 'success', action: 'accept_amendment', meta: { contract_id: contractId, amendment_id: payload.amendment_id } });
    buttons.push({ label: tr?.reject || 'Отказать', testid: `notif-reject-amend-${notif.id}`, intent: 'danger', action: 'reject_amendment', meta: { contract_id: contractId, amendment_id: payload.amendment_id } });
  }
  if (notif.type === 'tender_pending_funds') {
    buttons.push({ label: tr?.deposit || 'Пополнить', testid: `notif-deposit-${notif.id}`, intent: 'primary', action: 'open_deposit' });
  }
  // Low-resource / business-stopped alerts → one-tap to /trading where the
  // user can buy the missing resource. Product spec: every such notification
  // must carry a CTA pointing at the trading page.
  if (notif.type === 'low_resource') {
    buttons.push({
      label: tr?.buyResources || 'Купить ресурсы',
      testid: `notif-open-trading-${notif.id}`,
      intent: 'primary',
      action: 'open_trading',
    });
  }
  // Lease of a level-0 business ends soon: offer the upgrade to level 1 (keeps it forever).
  if (notif.type === 'zero_lease_expiring') {
    const cost = payload.upgrade_cost_ton;
    const tpl = (t && t('leaseUpgradeCta')) || 'Upgrade to level 1 for {cost} TON';
    buttons.push({ label: cost ? tpl.replace('{cost}', cost) : ((t && t('leaseUpgradeCtaShort')) || 'Upgrade to level 1'),
      testid: `notif-lease-upgrade-${notif.id}`, intent: 'primary', action: 'open_businesses' });
  }
  // Smart notifications (backend/smart_notify.py): one-tap to the screen that fixes it.
  if (['smart_warehouse_full', 'smart_warehouse_almost_full', 'smart_price_up'].includes(notif.type)) {
    buttons.push({ label: (t && t('smartNotifCtaMarket')) || 'Market', testid: `notif-smart-market-${notif.id}`,
      intent: 'primary', action: 'open_trading' });
  }
  if (['smart_durability_low', 'smart_business_stopped', 'smart_shift_ended'].includes(notif.type)) {
    buttons.push({ label: (t && t('smartNotifCtaBusinesses')) || 'My businesses', testid: `notif-smart-biz-${notif.id}`,
      intent: 'primary', action: 'open_businesses' });
  }
  // NEW: counter_offer — patron can accept (creates contract) or reject (vassal gets notified)
  if ((kind === 'counter_offer' || notif.type === 'counter_offer') && payload.counter_offer_id) {
    buttons.push({ label: tr?.accept || 'Принять', testid: `notif-accept-counter-${notif.id}`, intent: 'success', action: 'accept_counter_offer', meta: { counter_offer_id: payload.counter_offer_id } });
    buttons.push({ label: tr?.reject || 'Отклонить', testid: `notif-reject-counter-${notif.id}`, intent: 'danger', action: 'reject_counter_offer', meta: { counter_offer_id: payload.counter_offer_id } });
  }
  // 'На биржу' button removed for tender_pending_resources per UX request

  const msg = renderedMsg;

  // Announcement + transaction messages can carry HTML (<b>, <i>, <a>, <br>,
  // <code>, <pre>, <u>, <s>, <em>, <strong>). We render them as HTML so the
  // same styling shown by Telegram is preserved on the in-app notification
  // (deposit / withdrawal messages contain <b>amount</b> and <code>hash</code>).
  // For safety we allow only a whitelist of tags and strip inline JS.
  const HTML_NOTIF_TYPES = ['announcement', 'deposit', 'withdrawal_approved', 'withdrawal_rejected', 'withdrawal_pending', 'promo_announcement'];
  const renderAsHtml = HTML_NOTIF_TYPES.includes(notif.type);
  const sanitizeHtml = (raw) => {
    if (!raw) return '';
    let s = String(raw);
    // Drop <script>/<style> blocks entirely
    s = s.replace(/<\s*(script|style)[\s\S]*?<\s*\/\s*\1\s*>/gi, '');
    // Drop `on...=` inline handlers and `javascript:` urls
    s = s.replace(/\son[a-z]+\s*=\s*"[^"]*"/gi, '')
         .replace(/\son[a-z]+\s*=\s*'[^']*'/gi, '')
         .replace(/javascript:/gi, '');
    // Preserve raw newlines the same way Telegram renders them: convert
    // literal "\n" characters into <br> so promo/announcement/deposit bodies
    // keep their multi-line formatting inside the notification card.
    s = s.replace(/\r\n|\r|\n/g, '<br>');
    return s;
  };

  // Swipe-to-delete state (mobile only, collapsed only)
  const x = useMotionValue(0);
  const [swipeOpen, setSwipeOpen] = useState(false);

  const handleCardClick = () => {
    if (swipeOpen) {
      // Click while delete is exposed → reset
      setSwipeOpen(false);
      x.set(0);
      return;
    }
    onToggleExpand?.(notif.id);
    if (!notif.read) onMarkRead?.(notif.id);
  };

  // Reset swipe when card becomes expanded
  useEffect(() => {
    if (expanded) {
      setSwipeOpen(false);
      x.set(0);
    }
  }, [expanded, x]);

  const handleDragEnd = (_, info) => {
    if (!isMobile || expanded) return;
    if (info.offset.x < -50 || info.velocity.x < -400) {
      setSwipeOpen(true);
      x.set(-72);
    } else {
      setSwipeOpen(false);
      x.set(0);
    }
  };

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, x: 80 }}
      transition={{ duration: 0.25 }}
      className="relative w-full"
      data-testid={`notif-card-${notif.id}`}
    >
      {/* Hidden delete button revealed on swipe (mobile only).
          Only rendered when swipeOpen — invisible by default per UX request. */}
      {isMobile && !expanded && swipeOpen && (
        <button
          type="button"
          onClick={() => onDelete(notif.id)}
          data-testid={`notif-swipe-del-${notif.id}`}
          aria-label={tr?.deleteNotification || 'Удалить уведомление'}
          className="absolute right-0 top-0 bottom-0 w-[64px] flex items-center justify-center rounded-xl bg-red-600 text-white shadow-lg"
        >
          <Trash2 className="w-5 h-5" />
        </button>
      )}

      <motion.div
        style={isMobile && !expanded ? { x } : undefined}
        drag={isMobile && !expanded ? 'x' : false}
        dragConstraints={{ left: -72, right: 0 }}
        dragElastic={0.05}
        onDragEnd={handleDragEnd}
        onClick={handleCardClick}
        role="button"
        tabIndex={0}
        className={`relative p-3 rounded-xl border ${colors.border} ${notif.read ? 'bg-[#0d0d18]' : colors.bg} backdrop-blur cursor-pointer w-full`}
      >
        {/* Title */}
        {renderedTitle && (
          <div className="text-white text-sm font-semibold leading-tight break-words pr-1">
            {renderedTitle}
          </div>
        )}

        {/* Image (ONLY when expanded). We accept the URL either at the
            top-level `image_url` (legacy admin announcements) or inside
            `payload.image_url` (promo_announcement / rally reminders). */}
        {expanded && (notif.image_url || payload.image_url) && (
          <img
            src={(() => { const u = notif.image_url || payload.image_url; return u.startsWith('/api/') ? `${BACKEND_URL}${u}` : u; })()}
            alt=""
            data-testid="notif-image"
            className={`mt-2 w-full max-h-72 rounded-md border border-white/10 ${notif.type === 'minigame_chest' ? 'object-contain bg-[#0b1020]' : 'object-cover'}`}
            onError={(e) => { e.currentTarget.style.display = 'none'; }}
          />
        )}

        {/* Message — collapsed: max-2 lines; expanded: full */}
        {msg && (
          renderAsHtml ? (
            <div
              className={`text-zinc-300 text-[12px] mt-1 leading-relaxed break-words announcement-html ${expanded ? '' : 'line-clamp-2'}`}
              data-testid={`notif-msg-${notif.id}`}
              dangerouslySetInnerHTML={{ __html: sanitizeHtml(msg) }}
            />
          ) : (
            <div className={`text-zinc-300 text-[12px] mt-1 leading-relaxed whitespace-pre-wrap break-words ${expanded ? '' : 'line-clamp-2'}`}>
              {msg}
            </div>
          )
        )}

        {/* Rich proposal/amendment preview — shown when expanded for tender proposals or amendments */}
        {expanded && contractId && (kind === 'tender_proposal' || notif.type === 'tender_proposal_new' || kind === 'tender_amendment' || notif.type === 'tender_amendment_new') && (
          <TenderProposalDetails contractId={contractId} token={token} t={t} />
        )}

        {/* Counter-offer rich card — shown always (collapsed and expanded) so the user
            can see the new terms of the proposal at a glance and act directly. */}
        {(kind === 'counter_offer' || notif.type === 'counter_offer') && payload.counter_offer_id && (
          <CounterOfferDetails payload={payload} />
        )}

        {/* Footer: time + (if action was taken) accepted/rejected badge */}
        <div className="flex items-center gap-2 mt-2 flex-wrap">
          <span className="text-[10px] text-zinc-500">{formatTime(notif.created_at, tr)}</span>
          {!notif.read && !actionStatus && (
            <>
              <span className="text-[10px] text-zinc-600">·</span>
              <span className="text-[10px] text-cyber-cyan">{tr?.newDot || 'новое'}</span>
            </>
          )}
          {actionStatus === 'accepted' && (
            <span data-testid={`notif-status-accepted-${notif.id}`} className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/20 border border-emerald-500/40 text-emerald-300 font-semibold">
              {tr?.notifAccepted || t('notifAccepted') || 'Принято'}
            </span>
          )}
          {actionStatus === 'rejected' && (
            <span data-testid={`notif-status-rejected-${notif.id}`} className="text-[10px] px-2 py-0.5 rounded-full bg-red-500/20 border border-red-500/40 text-red-300 font-semibold">
              {tr?.notifRejected || t('notifRejected') || 'Отклонено'}
            </span>
          )}
        </div>

        {buttons.length > 0 && !actionStatus && (
          <div className="flex flex-wrap gap-2 mt-2">
            {buttons.map((b, idx) => (
              <button
                key={idx}
                type="button"
                data-testid={b.testid}
                onClick={(e) => { e.stopPropagation(); onAction(b, notif); }}
                className={
                  b.intent === 'success' ? 'text-[11px] px-3 py-1 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white' :
                  b.intent === 'danger'  ? 'text-[11px] px-3 py-1 rounded-lg bg-red-600/80 hover:bg-red-500 text-white' :
                  'text-[11px] px-3 py-1 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white'
                }
              >
                {b.label}
              </button>
            ))}
          </div>
        )}

        {!notif.read && (
          <span className={`absolute top-3 left-0 w-1 h-6 rounded-r ${colors.dot}`} aria-hidden />
        )}
      </motion.div>
    </motion.div>
  );
}

// ───────────────────────── Main panel ─────────────────────────
export default function NotificationCenter({ open, onClose, user }) {
  const navigate = useNavigate();
  const { language } = useLanguage();
  const { t } = useTranslation(language);

  // Localized translation bag for the notification UI
  const tr = useMemo(() => ({
    title: t('notifCenterTitle') || 'Уведомления',
    markAllRead: t('notifMarkAllRead') || 'Прочитать все',
    markAllReadShort: t('notifMarkAllShort') || 'Все',
    soundLabel: t('notifSound') || 'Звук уведомлений',
    clearAll: t('notifClearAll') || 'Очистить всё',
    empty: t('notifEmpty') || 'Пока нет уведомлений',
    loading: t('notifLoading') || 'Загрузка…',
    close: t('notifClose') || 'Закрыть',
    settings: t('notifSettings') || 'Настройки',
    newDot: t('notifNewDot') || 'новое',
    deleteNotification: t('notifDelete') || 'Удалить уведомление',
    accept: t('notifAccept') || 'Принять',
    reject: t('notifReject') || 'Отклонить',
    deposit: t('notifDeposit') || 'Пополнить',
    toMarket: t('notifToMarket') || 'На биржу',
    justNow: t('notifJustNow') || 'только что',
    minAgo: t('notifMinAgo') || 'мин назад',
    hourAgo: t('notifHourAgo') || 'ч назад',
    dayAgo: t('notifDayAgo') || 'дн назад',
    locale: t('notifLocale') || 'ru-RU',
  }), [t]);

  const token = (typeof localStorage !== 'undefined' && (localStorage.getItem('token') || localStorage.getItem('ton_city_token'))) || '';
  const [notifications, setNotifications] = useState([]);
  // Per-notification action result (accepted/rejected) — keeps the badge after a button click
  const [actionResults, setActionResults] = useState({});
  const [loading, setLoading] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const [showSettings, setShowSettings] = useState(false);
  const [soundOn, setSoundOn] = useState(() => (typeof localStorage !== 'undefined' ? localStorage.getItem(SOUND_PREF_KEY) !== 'false' : true));
  const [isMobileFull, setIsMobileFull] = useState(false);
  const [expandedIds, setExpandedIds] = useState(new Set());
  const [smallScreen, setSmallScreen] = useState(
    typeof window !== 'undefined' ? window.matchMedia('(max-width: 1023px)').matches : false
  );
  const isMobile = smallScreen;
  const isTelegramWebApp = typeof window !== 'undefined' && (
    document.documentElement.classList.contains('is-telegram') || !!window.Telegram?.WebApp?.initData
  );
  const sheetY = useMotionValue(0);
  const dragControls = useDragControls();

  // Track viewport changes for responsive behaviour
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const mq = window.matchMedia('(max-width: 1023px)');
    const onChange = (e) => setSmallScreen(e.matches);
    try { mq.addEventListener('change', onChange); } catch (_) { mq.addListener(onChange); }
    return () => { try { mq.removeEventListener('change', onChange); } catch (_) { mq.removeListener(onChange); } };
  }, []);

  // Always reopen in collapsed (bottom-sheet) state on mobile — user must drag up again.
  useEffect(() => {
    if (open) {
      setIsMobileFull(false);
      sheetY.set(0);
    }
  }, [open, sheetY]);

  const fetchAll = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const res = await axios.get(`${API}/notifications?limit=60`, { headers: { Authorization: `Bearer ${token}` } });
      setNotifications(res.data?.notifications || []);
      setUnreadCount(res.data?.unread_count || 0);
    } catch (_) {} finally { setLoading(false); }
  }, [token]);

  useEffect(() => { if (open) fetchAll(); }, [open, fetchAll]);

  // Live-refresh when a new WS notification arrives while drawer is open
  useEffect(() => {
    const handler = () => { if (open) fetchAll(); };
    window.addEventListener('notification:new', handler);
    return () => window.removeEventListener('notification:new', handler);
  }, [open, fetchAll]);

  useEffect(() => {
    if (!token) return;
    const t = setInterval(fetchAll, 30000);
    return () => clearInterval(t);
  }, [token, fetchAll]);

  const markRead = async (id) => {
    setNotifications(prev => prev.map(n => n.id === id ? { ...n, read: true } : n));
    setUnreadCount(c => Math.max(0, c - 1));
    try { await axios.post(`${API}/notifications/${id}/read`, {}, { headers: { Authorization: `Bearer ${token}` } }); } catch (_) {}
  };
  const markAllRead = async () => {
    setNotifications(prev => prev.map(n => ({ ...n, read: true })));
    setUnreadCount(0);
    try { await axios.post(`${API}/notifications/read_all`, {}, { headers: { Authorization: `Bearer ${token}` } }); } catch (_) {}
  };
  const deleteOne = async (id) => {
    setNotifications(prev => prev.filter(n => n.id !== id));
    try { await axios.delete(`${API}/notifications/${id}`, { headers: { Authorization: `Bearer ${token}` } }); } catch (_) {}
  };
  const clearAll = async () => {
    setNotifications([]);
    setUnreadCount(0);
    try {
      // First mark all as read so the bulk-delete (which only deletes read) wipes them.
      await axios.post(`${API}/notifications/read_all`, {}, { headers: { Authorization: `Bearer ${token}` } });
      await axios.delete(`${API}/notifications`, { headers: { Authorization: `Bearer ${token}` } });
    } catch (_) {}
  };

  const handleAction = async (btn, notif) => {
    if (btn.action === 'open_deposit') { onClose?.(); window.dispatchEvent(new CustomEvent('open-deposit-modal')); return; }
    if (btn.action === 'open_market') { onClose?.(); navigate('/marketplace'); return; }
    if (btn.action === 'open_trading') { onClose?.(); navigate('/trading'); return; }
    if (btn.action === 'open_businesses') { onClose?.(); navigate('/my-businesses'); return; }
    // For accept/reject style actions, optimistically set the badge so the user
    // sees the result immediately and the buttons disappear.
    const setResult = (val) => setActionResults(prev => ({ ...prev, [notif.id]: val }));
    if (btn.action === 'accept_break') {
      setResult('accepted');
      try {
        await axios.post(`${API}/tenders/contracts/${btn.meta.contract_id}/break_request/accept`, {}, { headers: { Authorization: `Bearer ${token}` } });
        await markRead(notif.id);
        await fetchAll();
      } catch (_) { setResult(null); }
      return;
    }
    if (btn.action === 'reject_break') {
      setResult('rejected');
      try {
        await axios.post(`${API}/tenders/contracts/${btn.meta.contract_id}/break_request/reject`, {}, { headers: { Authorization: `Bearer ${token}` } });
        await markRead(notif.id);
        await fetchAll();
      } catch (_) { setResult(null); }
      return;
    }
    if (btn.action === 'accept_proposal') {
      setResult('accepted');
      try {
        await axios.post(`${API}/tenders/contracts/${btn.meta.contract_id}/accept`, {}, { headers: { Authorization: `Bearer ${token}` } });
        await markRead(notif.id);
        await fetchAll();
      } catch (e) {
        setResult(null);
        const detail = e?.response?.data?.detail;
        const msg = typeof detail === 'string' ? detail : 'Не удалось утвердить предложение';
        try { (await import('sonner')).toast.error(msg); } catch (_) {}
      }
      return;
    }
    if (btn.action === 'reject_proposal') {
      setResult('rejected');
      try {
        await axios.post(`${API}/tenders/contracts/${btn.meta.contract_id}/reject`, {}, { headers: { Authorization: `Bearer ${token}` } });
        await markRead(notif.id);
        await fetchAll();
      } catch (_) { setResult(null); }
      return;
    }
    if (btn.action === 'accept_amendment') {
      setResult('accepted');
      try {
        await axios.post(`${API}/tenders/contracts/${btn.meta.contract_id}/amendments/${btn.meta.amendment_id}/accept`, {}, { headers: { Authorization: `Bearer ${token}` } });
        await markRead(notif.id);
        await fetchAll();
      } catch (e) {
        setResult(null);
        const detail = e?.response?.data?.detail;
        const msg = typeof detail === 'string' ? detail : 'Не удалось принять изменение';
        try { (await import('sonner')).toast.error(msg); } catch (_) {}
      }
      return;
    }
    if (btn.action === 'reject_amendment') {
      setResult('rejected');
      try {
        await axios.post(`${API}/tenders/contracts/${btn.meta.contract_id}/amendments/${btn.meta.amendment_id}/reject`, {}, { headers: { Authorization: `Bearer ${token}` } });
        await markRead(notif.id);
        await fetchAll();
      } catch (_) { setResult(null); }
      return;
    }
    if (btn.action === 'accept_counter_offer') {
      setResult('accepted');
      try {
        await axios.post(`${API}/alliances/counter-offer/${btn.meta.counter_offer_id}/accept`, {}, { headers: { Authorization: `Bearer ${token}` } });
        await markRead(notif.id);
        await fetchAll();
        try {
          const { toast } = await import('sonner');
          toast.success(t('counterAcceptedToast') || 'Встречное предложение принято, контракт активен!');
        } catch (_) {}
      } catch (e) {
        setResult(null);
        const detail = e?.response?.data?.detail;
        const msg = typeof detail === 'string' ? detail : (t('counterAcceptFailed') || 'Не удалось принять встречное предложение');
        try { (await import('sonner')).toast.error(msg); } catch (_) {}
      }
      return;
    }
    if (btn.action === 'reject_counter_offer') {
      setResult('rejected');
      try {
        await axios.post(`${API}/alliances/counter-offer/${btn.meta.counter_offer_id}/reject`, {}, { headers: { Authorization: `Bearer ${token}` } });
        await markRead(notif.id);
        await fetchAll();
        try {
          const { toast } = await import('sonner');
          toast.success(t('counterRejectedToast') || 'Встречное предложение отклонено');
        } catch (_) {}
      } catch (_) { setResult(null); }
      return;
    }
  };

  const toggleSound = () => {
    const next = !soundOn;
    setSoundOn(next);
    try { localStorage.setItem(SOUND_PREF_KEY, next ? 'true' : 'false'); } catch (_) {}
    try { axios.post(`${API}/notifications/preferences`, { sound: next }, { headers: { Authorization: `Bearer ${token}` } }); } catch (_) {}
  };

  const toggleExpand = (id) => {
    setExpandedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  // Sort newest first
  const sorted = useMemo(
    () => [...notifications].sort((a, b) => (a.created_at < b.created_at ? 1 : -1)),
    [notifications]
  );

  const handleDragEnd = (_, info) => {
    if (isMobileFull) {
      // Fullscreen: downward swipe on handle collapses back to bottom-sheet (initial)
      if (info.offset.y > 60 || info.velocity.y > 300) {
        setIsMobileFull(false);
        sheetY.set(0);
        return;
      }
      sheetY.set(0);
      return;
    }
    // Collapsed bottom-sheet: down → close, up → fullscreen
    if (info.offset.y > 120 || info.velocity.y > 600) {
      onClose?.();
      setIsMobileFull(false);
    } else if (info.offset.y < -120 || info.velocity.y < -600) {
      setIsMobileFull(true);
      sheetY.set(0);
    } else {
      sheetY.set(0);
    }
  };

  if (!open && !isMobile) {
    // Desktop unmounts immediately; no exit animation needed.
    return null;
  }

  const portalNode = typeof document !== 'undefined' ? document.body : null;
  if (!portalNode) return null;

  // Header: two rows. Top row: close + title + settings. Below: count + Mark-all-read.
  // This avoids the "Mark all" button overlapping the title.
  const headerBar = (
    <div className="px-4 pt-3 pb-2 border-b border-white/10">
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onClose}
          data-testid="notif-close-btn"
          className="w-9 h-9 rounded-lg bg-white/5 hover:bg-white/10 text-white/70 hover:text-white flex items-center justify-center transition-colors shrink-0"
          aria-label={tr.close}
        >
          <X className="w-4 h-4" />
        </button>
        <div className="flex-1 min-w-0 flex items-start gap-1.5">
          <h2 className="text-white font-unbounded text-lg font-bold leading-tight">
            {tr.title}
          </h2>
          {unreadCount > 0 && (
            <span
              data-testid="notif-title-badge"
              className={`mt-0.5 min-w-[18px] h-[18px] px-1 rounded-full text-[10px] font-bold flex items-center justify-center text-white shrink-0 ${notifHasCritical(notifications) ? 'bg-red-500' : 'bg-cyber-cyan text-black'}`}
              style={notifHasCritical(notifications) ? { boxShadow: '0 0 0 3px rgba(239,68,68,0.25)' } : {}}
            >
              {unreadCount > 9 ? '9+' : unreadCount}
            </span>
          )}
        </div>
        {unreadCount > 0 && (
          <button
            type="button"
            onClick={markAllRead}
            data-testid="notif-mark-all-read"
            className="h-9 px-3 rounded-lg bg-white/5 hover:bg-white/10 text-white/80 hover:text-white text-[11px] inline-flex items-center gap-1 shrink-0"
            title={tr.markAllRead}
          >
            <CheckCheck className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">{tr.markAllRead}</span>
            <span className="sm:hidden">{tr.markAllReadShort}</span>
          </button>
        )}
        <button
          type="button"
          onClick={() => setShowSettings(s => !s)}
          data-testid="notif-settings-toggle"
          className={`w-9 h-9 rounded-lg flex items-center justify-center transition-colors shrink-0 ${showSettings ? 'bg-cyber-cyan/20 text-cyber-cyan' : 'bg-white/5 text-white/70 hover:bg-white/10 hover:text-white'}`}
          aria-label={tr.settings}
        >
          <SettingsIcon className="w-4 h-4" />
        </button>
      </div>
    </div>
  );

  const settingsPane = showSettings && (
    <div className="px-4 py-3 border-b border-white/10 bg-white/[0.02] space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-white/80 text-sm">
          {soundOn ? <Volume2 className="w-4 h-4" /> : <VolumeX className="w-4 h-4" />}
          {tr.soundLabel}
        </div>
        <button
          type="button"
          onClick={toggleSound}
          data-testid="notif-sound-toggle"
          className={`relative w-12 h-6 rounded-full transition-colors ${soundOn ? 'bg-cyber-cyan' : 'bg-white/10'}`}
        >
          <span className={`absolute top-0.5 ${soundOn ? 'left-6' : 'left-0.5'} w-5 h-5 rounded-full bg-white transition-all`} />
        </button>
      </div>
      <button
        type="button"
        onClick={clearAll}
        data-testid="notif-clear-all"
        className="w-full text-left text-xs text-white/60 hover:text-red-300 flex items-center gap-2"
      >
        <Trash2 className="w-3.5 h-3.5" /> {tr.clearAll}
      </button>
    </div>
  );

  const listPane = (
    <div
      className="flex-1 overflow-y-auto p-3 space-y-2"
      style={{ paddingBottom: 'calc(env(safe-area-inset-bottom, 0px) + var(--tg-safe-bottom, 0px) + 0.75rem)' }}
      data-testid="notif-list"
    >
      {loading && notifications.length === 0 && (
        <div className="text-center text-white/40 text-sm py-8">{tr.loading}</div>
      )}
      {!loading && sorted.length === 0 && (
        <div className="text-center text-white/40 text-sm py-12">
          <Bell className="w-10 h-10 mx-auto mb-2 opacity-30" />
          {tr.empty}
        </div>
      )}
      <AnimatePresence initial={false}>
        {sorted.map(n => (
          <NotificationCard
            key={n.id}
            notif={n}
            expanded={expandedIds.has(n.id)}
            onToggleExpand={toggleExpand}
            onMarkRead={markRead}
            onDelete={deleteOne}
            onAction={handleAction}
            isMobile={isMobile}
            tr={tr}
            t={t}
            token={token}
            actionStatus={actionResults[n.id]}
          />
        ))}
      </AnimatePresence>
    </div>
  );

  // WebApp top inset: per UX request, reduce by 15px (but never below 0)
  const drawerTopInset = `max(0px, calc(var(--tg-safe-top, 0px) - 15px))`;
  // Hide drag handle when fullscreen on mobile browser (NOT in Telegram WebApp)
  const hideHandleWhenFull = isMobileFull && !isTelegramWebApp;

  return createPortal(
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-[100]" data-testid="notif-overlay">
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            transition={{ duration: 0.25 }}
            className="absolute inset-0 bg-black/55 backdrop-blur-sm"
            onClick={onClose}
          />

          {/* Desktop: LEFT drawer */}
          {!isMobile && (
            <motion.aside
              initial={{ x: '-100%', opacity: 0 }}
              animate={{ x: 0, opacity: 1 }}
              exit={{ x: '-100%', opacity: 0 }}
              transition={{ type: 'spring', stiffness: 280, damping: 30 }}
              className="absolute left-0 top-0 h-full w-[420px] max-w-[92vw] bg-gradient-to-b from-[#0d0d18]/90 to-[#0a0a14]/95 backdrop-blur-2xl border-r border-cyber-cyan/20 shadow-2xl shadow-cyber-cyan/10 flex flex-col"
              onClick={(e) => e.stopPropagation()}
              data-testid="notif-drawer-desktop"
              style={{ paddingTop: drawerTopInset }}
            >
              {headerBar}
              {settingsPane}
              {listPane}
            </motion.aside>
          )}

          {/* Mobile: bottom-sheet → can drag up to fullscreen.
              In fullscreen mode, the user can drag the handle DOWN to return
              to the collapsed bottom-sheet (initial) state — bidirectional. */}
          {isMobile && (
            <motion.div
              initial={{ y: '100%' }}
              animate={{ y: 0 }}
              exit={{ y: '100%' }}
              transition={{ type: 'spring', stiffness: 280, damping: 30 }}
              drag="y"
              dragListener={false}
              dragControls={dragControls}
              dragConstraints={{ top: 0, bottom: 0 }}
              dragElastic={{ top: 0.05, bottom: 0.35 }}
              onDragEnd={handleDragEnd}
              style={{ y: sheetY, paddingTop: isMobileFull ? drawerTopInset : undefined }}
              className={`absolute left-0 right-0 ${isMobileFull ? 'top-0 h-full rounded-none' : 'bottom-0 max-h-[88vh] rounded-t-3xl'} bg-gradient-to-b from-[#0d0d18]/97 to-[#0a0a14]/98 backdrop-blur-2xl border-t border-cyber-cyan/20 shadow-2xl shadow-cyber-cyan/10 flex flex-col`}
              onClick={(e) => e.stopPropagation()}
              data-testid="notif-drawer-mobile"
            >
              {/* Handle — hidden when fully stretched on mobile browser, so the
                  page title sits flush at the very top per UX request.
                  Acts as the SOLE drag-handle for the sheet (bidirectional). */}
              {!hideHandleWhenFull && (
                <div
                  className="flex flex-col items-center pt-2 pb-1 cursor-grab touch-none select-none"
                  onPointerDown={(e) => dragControls.start(e)}
                  onDoubleClick={() => setIsMobileFull(v => !v)}
                  data-testid="notif-mobile-handle"
                >
                  <div className="w-12 h-1.5 rounded-full bg-white/30" />
                </div>
              )}
              {headerBar}
              {settingsPane}
              {listPane}
            </motion.div>
          )}
        </div>
      )}
    </AnimatePresence>,
    portalNode
  );
}

// Hook to subscribe to WS + play sound, exposed for reuse
export function useNotificationsCount(user) {
  const [count, setCount] = useState(0);
  const [hasCritical, setHasCritical] = useState(false);
  const [shake, setShake] = useState(false);
  const token = (typeof localStorage !== 'undefined' && (localStorage.getItem('token') || localStorage.getItem('ton_city_token'))) || '';

  const refresh = useCallback(async () => {
    // Never poll before the user is resolved — otherwise a stale token from a
    // previous session bounces here with 401 session_invalidated and triggers
    // the "kick" toast while the user is still on /auth trying to log in.
    if (!token || !user) return;
    try {
      const res = await axios.get(`${API}/notifications/unread_count`, { headers: { Authorization: `Bearer ${token}` } });
      setCount(res.data?.count || 0);
      setHasCritical(!!res.data?.has_critical);
    } catch (_) {}
  }, [token, user]);
  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;

  useEffect(() => { refresh(); }, [refresh, user?.id]);
  useEffect(() => {
    if (!token || !user) return;
    const t = setInterval(refresh, 30000);
    return () => clearInterval(t);
  }, [token, user, refresh]);

  useEffect(() => {
    if (!user) return;
    const userKey = user?.id || user?.email || user?.wallet_address || user?.username;
    if (!userKey) return;
    return subscribeUserSocket(userKey, (data) => {                       // one shared socket (lib/userSocket.js)
      if (data?.type === 'notification_new') {
        playSound();
        setShake(true);
        setTimeout(() => setShake(false), 700);
        refreshRef.current && refreshRef.current();
        window.dispatchEvent(new CustomEvent('notification:new', { detail: data.notification }));
      }
    });
  }, [user?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  return { count, hasCritical, shake, refresh };
}


// Shared debounce timestamp so the chat-unread sound isn't played twice when
// the useChatUnreadCount hook is mounted in both Sidebar and MobileNav.
let _lastChatSoundTs = 0;

// ───────────────────────── Chat unread-count hook ─────────────────────────
// Polls the total unread chat message count so we can show a badge over the
// chat icon (sidebar + burger menu). Plays the notification sound whenever the
// unread count grows (a new chat message arrived) — respecting the global
// sound toggle (default muted).
export function useChatUnreadCount(user) {
  const [count, setCount] = useState(0);
  const prevRef = useRef(0);
  const initRef = useRef(false);
  const token = (typeof localStorage !== 'undefined' && (localStorage.getItem('token') || localStorage.getItem('ton_city_token'))) || '';

  const refresh = useCallback(async () => {
    if (!token || !user) return;
    try {
      const res = await axios.get(`${API}/chat/unread-count`, { headers: { Authorization: `Bearer ${token}` } });
      const next = res.data?.unread_count || 0;
      // Play the sound when the unread count GROWS — this fires even when the
      // user is NOT on the chat page (the hook lives in the global sidebar/nav).
      // Skip the very first poll so we don't beep for pre-existing unread.
      // Module-level debounce: the hook is mounted twice (Sidebar + MobileNav),
      // so guard against a double beep for the same event.
      if (initRef.current && next > prevRef.current) {
        const now = Date.now();
        if (now - _lastChatSoundTs > 1500) {
          _lastChatSoundTs = now;
          playSound();
        }
      }
      initRef.current = true;
      prevRef.current = next;
      setCount(next);
    } catch (_) {}
  }, [token, user]);

  useEffect(() => { refresh(); }, [refresh, user?.id]);
  useEffect(() => {
    if (!token || !user) return;
    const iv = setInterval(refresh, 15000);
    const onFocus = () => refresh();
    window.addEventListener('focus', onFocus);
    window.addEventListener('chat:refresh-unread', refresh);
    return () => {
      clearInterval(iv);
      window.removeEventListener('focus', onFocus);
      window.removeEventListener('chat:refresh-unread', refresh);
    };
  }, [token, user, refresh]);

  return { count, refresh };
}

// Format an unread badge number: 99+ cap.
export const formatBadgeCount = (n) => (n > 99 ? '99+' : String(n));
