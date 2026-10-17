/**
 * Tender contracts UI — B2B daily-supply marketplace.
 * Sub-tabs: Биржа (open tenders) / Закупки (mine as buyer) / Поставки (mine as seller).
 */
import { useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import { toast } from 'sonner';
import {
  ShoppingCart, Tag, Truck, X, Check, Trash2, AlertTriangle,
  Clock, Loader2, Sliders, FilePlus2, ChevronDown, Lock,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { useTranslation } from '@/lib/translations';
import { tBusiness } from '@/lib/translationsExtra';
import { useLanguage } from '@/context/LanguageContext';
import { useResourceName } from '@/hooks/useResourceName';
import { getResourceName } from '@/lib/resourceConfig';
import { formatErrorDetail, getApiErrorMessage } from '@/lib/apiErrors';
import { MAX_PRICE_VALUE } from '@/lib/priceLimits';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;
const T1_MULT = 10;
const MAX_TENDERS = 5;

// "цена за 1 ед" в БД; UI для T1 показывает "за 10 ед".
// Localized label: "макс. {amount} $CITY / {unit}" via t('maxPriceFmt').
const fmtPriceLabel = (pricePerUnit, tier, tt = (x) => x) => {
  const amount = (tier === 1 ? pricePerUnit * T1_MULT : pricePerUnit).toFixed(2);
  const unit = tier === 1 ? tt('priceUnitT1') : tt('priceUnitT23');
  return tt('maxPriceFmt').replace('{amount}', amount).replace('{unit}', unit);
};

const statusBadge = (s, tt = (x) => x) => ({
  PROPOSED:           { label: tt('statusProposed'),         cls: 'bg-amber-500/15 text-amber-300 border-amber-500/30' },
  ACTIVE:             { label: tt('statusActiveT'),          cls: 'bg-green-500/15 text-green-300 border-green-500/30' },
  PENDING_FUNDS:      { label: tt('statusPendingFunds'),     cls: 'bg-orange-500/15 text-orange-300 border-orange-500/30' },
  PENDING_RESOURCES:  { label: tt('statusPendingResources'), cls: 'bg-orange-500/15 text-orange-300 border-orange-500/30' },
  BROKEN:             { label: tt('statusBroken'),           cls: 'bg-red-500/15 text-red-300 border-red-500/30' },
  REJECTED:           { label: tt('statusRejected'),         cls: 'bg-zinc-500/15 text-zinc-300 border-zinc-500/30' },
}[s] || { label: s, cls: 'bg-zinc-500/15 text-zinc-300 border-zinc-500/30' });

const Stars = ({ value }) => (
  <span className="text-amber-300 tracking-wide" title={`${value}/5`}>
    {'★'.repeat(Math.max(0, Math.min(5, value)))}{'☆'.repeat(5 - Math.max(0, Math.min(5, value)))}
  </span>
);

// Integer-only input handler — strips dots, commas, "e", everything non-digit.
// Also caps the value at MAX_PRICE_VALUE (1_000_000_000) so users can't enter
// astronomically large amounts that overflow the formatter or trigger
// server-side range errors.
const onIntChange = (setter) => (e) => {
  let raw = String(e.target.value || '').replace(/[^\d]/g, '');
  if (raw && Number(raw) > MAX_PRICE_VALUE) {
    raw = String(MAX_PRICE_VALUE);
  }
  setter(raw);
};

// Custom resource picker — replaces native <select> with an icon-rich popover.
function ResourcePicker({ catalog, value, onChange, testId, language = 'ru' }) {
  const { t } = useTranslation(language);
  const [open, setOpen] = useState(false);
  const selected = value ? catalog?.[value] : null;
  const localizedName = (meta, code) => {
    const lng = (language || 'en').toLowerCase();
    // Single source of truth: getResourceName() from resourceConfig.
    return (
      getResourceName(code, lng) ||
      meta?.[`name_${lng}`] || meta?.name_ru || meta?.name_en || meta?.name || code
    );
  };
  const sorted = useMemo(() =>
    Object.entries(catalog || {}).sort((a, b) => (a[1]?.tier || 1) - (b[1]?.tier || 1)),
    [catalog]
  );
  return (
    <div className="relative" data-testid={testId}>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between gap-2 h-11 px-3 rounded-lg bg-zinc-900 border border-zinc-700 hover:border-cyan-500/50 text-white text-sm transition-colors"
      >
        <span className="flex items-center gap-2">
          {selected ? (
            <>
              <span className="text-xl">{selected.icon || '📦'}</span>
              <span className="font-medium">{localizedName(selected, value)}</span>
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-zinc-700 text-zinc-300">T{selected.tier}</span>
            </>
          ) : (
            <span className="text-zinc-500">{t('selectResourcePlaceholder') || '— Select resource —'}</span>
          )}
        </span>
        <ChevronDown className={`w-4 h-4 text-zinc-400 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div className="absolute z-50 mt-1 w-full max-h-72 overflow-y-auto rounded-lg bg-black border border-zinc-700 shadow-2xl">
          {[1, 2, 3].map(tier => {
            const items = sorted.filter(([, m]) => (m.tier || 1) === tier);
            if (items.length === 0) return null;
            return (
              <div key={tier}>
                <div className="px-3 py-1.5 text-[10px] uppercase tracking-wider text-zinc-500 bg-zinc-950 sticky top-0">
                  Тир {tier}
                </div>
                {items.map(([code, meta]) => (
                  <button
                    type="button"
                    key={code}
                    onClick={() => { onChange(code); setOpen(false); }}
                    className={`w-full flex items-center gap-3 px-3 py-2 text-left hover:bg-cyan-500/10 text-sm ${value === code ? 'bg-cyan-500/15 text-cyan-300' : 'text-zinc-200'}`}
                  >
                    <span className="text-xl">{meta.icon || '📦'}</span>
                    <span className="flex-1">{localizedName(meta, code)}</span>
                    {value === code && <Check className="w-4 h-4 text-cyan-400" />}
                  </button>
                ))}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function TenderContractsTab({ user, token, resourceCatalog }) {
  const { language } = useLanguage();
  const { t: tt } = useTranslation(language);
  const { withTier: rnameTier } = useResourceName();
  // Localized resource label "{Name} (T{tier})" — uses the central hook.
  const resLabel = (resourceType, tier) => rnameTier(resourceType, tier);
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);
  const [subTab, setSubTab] = useState('exchange');
  const [loading, setLoading] = useState(false);
  const [exchange, setExchange] = useState([]);
  const [purchases, setPurchases] = useState([]);
  const [supplies, setSupplies] = useState([]);
  // Set of resource_types the user produces (any business, any level). Used to
  // filter the marketplace so sellers only see tenders they can fulfil.
  const [producibleResources, setProducibleResources] = useState(null); // null = not loaded yet
  // v2.1.5: cannot publish a tender or submit an offer without owning at
  // least one real (non-tutorial) business. Populated from /my/businesses.
  const [hasRealBusiness, setHasRealBusiness] = useState(true);

  // Filters modal state
  const [showFilters, setShowFilters] = useState(false);
  const [filterRes, setFilterRes] = useState('');
  const [filterMin, setFilterMin] = useState('');
  const [filterMax, setFilterMax] = useState('');
  const [appliedFilters, setAppliedFilters] = useState({ res: '', min: '', max: '' });

  // Create-tender modal state
  const [showCreate, setShowCreate] = useState(false);
  const [createRes, setCreateRes] = useState('');
  const [createNeeded, setCreateNeeded] = useState('');
  const [createMaxPrice, setCreateMaxPrice] = useState('');
  const [createHour, setCreateHour] = useState(String(new Date().getUTCHours()));

  // Submit-offer modal (seller acts)
  const [offerForTender, setOfferForTender] = useState(null);
  const [offerAmount, setOfferAmount] = useState('');
  const [offerPrice, setOfferPrice] = useState('');
  const [offerCapacity, setOfferCapacity] = useState(null);

  // Tender-detail modal (buyer reviews suppliers)
  const [tenderDetail, setTenderDetail] = useState(null); // tender with .contracts

  // Break confirm
  const [breakTarget, setBreakTarget] = useState(null);
  const [breakMode, setBreakMode] = useState('choice'); // 'choice' | 'unilateral'
  // Accept-confirm modal (buyer confirms supplier with escrow info)
  const [acceptTarget, setAcceptTarget] = useState(null);

  // Amendment ("Обновить") modal — seller proposes new daily_amount / price
  const [amendTarget, setAmendTarget] = useState(null);
  const [amendAmount, setAmendAmount] = useState('');
  const [amendPrice, setAmendPrice] = useState('');

  // ── data ─────────────────────────────────────────────────────────────
  const reload = async () => {
    if (!token) return;
    setLoading(true);
    try {
      const [ex, my, sup, biz, types] = await Promise.all([
        axios.get(`${API}/tenders`, { headers }),
        axios.get(`${API}/tenders/me/purchases`, { headers }),
        axios.get(`${API}/tenders/me/supplies`, { headers }),
        // Used by issue #6 — filter tenders by resources the user actually produces.
        axios.get(`${API}/my/businesses`, { headers }).catch(() => ({ data: { businesses: [] } })),
        // BUSINESSES catalog is the authoritative source for produces (it's not
        // stored on the business doc itself — only business_type is).
        axios.get(`${API}/businesses/types`).catch(() => ({ data: { business_types: {} } })),
      ]);
      const bizList = biz?.data?.businesses || [];
      const typesMap = types?.data?.business_types || {};
      const produced = new Set();
      for (const b of bizList) {
        // Try the rare "produces" override first (in case schema ever lifts it onto the doc),
        // then the BUSINESSES catalog by business_type.
        const r = b?.produces || typesMap[b?.business_type]?.produces;
        if (r) produced.add(r);
      }
      setProducibleResources(produced);
      // v2.1.5: counts only real businesses (tutorial-sandbox flag excluded).
      setHasRealBusiness(bizList.some(b => !b.tutorial));
      setExchange((ex.data.tenders || []).filter(td => td.buyer_id !== user?.id));
      const myP = my.data.tenders || [];
      setPurchases(myP);
      setSupplies(sup.data.contracts || []);
      // Keep tenderDetail in-sync if it's open
      setTenderDetail((cur) => cur ? (myP.find(t => t.id === cur.id) || null) : null);
    } catch (e) {
      toast.error(getApiErrorMessage(e) || tt('errorLoadContracts'));
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { reload(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [token, user?.id]);

  const filteredExchange = useMemo(() => {
    let r = exchange;
    // Per user request: show ALL active tenders except the user's own
    // (own tenders are already filtered out in reload() by buyer_id).
    // We intentionally DO NOT restrict the list to resources the user
    // produces — the user must be able to see every open tender on the
    // exchange. (Whether they can actually respond is gated separately by
    // `hasRealBusiness` / free production capacity on the offer modal.)
    // Issue #4: hide tenders where seller already has a non-terminal contract.
    // The `supplies` list contains my own seller contracts.
    const occupiedTenderIds = new Set(
      (supplies || [])
        .filter(c => ['PROPOSED', 'ACTIVE', 'PENDING_FUNDS', 'PENDING_RESOURCES'].includes(c.status))
        .map(c => c.tender_id)
    );
    if (occupiedTenderIds.size > 0) {
      r = r.filter(t => !occupiedTenderIds.has(t.id));
    }
    if (appliedFilters.res) r = r.filter(t => t.resource_type === appliedFilters.res);
    if (appliedFilters.min !== '') {
      const minV = parseFloat(appliedFilters.min);
      r = r.filter(t => (resourceCatalog?.[t.resource_type]?.tier === 1 ? t.max_price_per_unit * T1_MULT : t.max_price_per_unit) >= minV);
    }
    if (appliedFilters.max !== '') {
      const maxV = parseFloat(appliedFilters.max);
      r = r.filter(t => (resourceCatalog?.[t.resource_type]?.tier === 1 ? t.max_price_per_unit * T1_MULT : t.max_price_per_unit) <= maxV);
    }
    return r;
  }, [exchange, appliedFilters, resourceCatalog, supplies]);

  // Issue #4: hide BROKEN contracts from the user's supplies/purchases lists.
  // (They're still kept in the DB so admin/audit can find them.)
  const visibleSupplies = useMemo(
    () => (supplies || []).filter(c => c.status !== 'BROKEN'),
    [supplies]
  );

  const hasActiveFilters = appliedFilters.res || appliedFilters.min || appliedFilters.max;

  // ── actions ──────────────────────────────────────────────────────────
  const doCreateTender = async () => {
    if (!createRes || !createNeeded || !createMaxPrice) {
      toast.error(tt('fillAllFields'));
      return;
    }
    if (purchases.length >= MAX_TENDERS) {
      toast.error(tt('tendersLimitMsg').replace('{n}', MAX_TENDERS));
      return;
    }
    const tier = resourceCatalog?.[createRes]?.tier || 1;
    const mult = tier === 1 ? 10 : 1;
    const amt = parseInt(createNeeded, 10);
    if (!amt || amt % mult !== 0) {
      toast.error(tt('amountMultipleErr').replace('{n}', mult));
      return;
    }
    const priceInput = parseInt(createMaxPrice, 10);
    const pricePerUnit = priceInput / (tier === 1 ? T1_MULT : 1);
    try {
      await axios.post(`${API}/tenders`, {
        resource_type: createRes,
        total_amount_needed: amt,
        max_price_per_unit: pricePerUnit,
        payment_hour: parseInt(createHour, 10) || 0,
      }, { headers });
      toast.success(tt('tenderCreated'));
      setShowCreate(false);
      setCreateRes(''); setCreateNeeded(''); setCreateMaxPrice('');
      reload();
    } catch (e) {
      toast.error(getApiErrorMessage(e) || tt('errorGeneric'));
    }
  };

  const openOffer = async (tender) => {
    setOfferForTender(tender);
    setOfferAmount(''); setOfferPrice('');
    try {
      const r = await axios.get(`${API}/tenders/me/capacity?resource=${tender.resource_type}`, { headers });
      setOfferCapacity(r.data);
    } catch {
      setOfferCapacity({ free: 0, daily_production: 0, committed: 0 });
    }
  };

  const doSubmitOffer = async () => {
    const tier = offerForTender.tier;
    const mult = tier === 1 ? 10 : 1;
    const amount = parseInt(offerAmount, 10);
    const priceInput = parseInt(offerPrice, 10);
    if (!amount || !priceInput) {
      toast.error(tt('fillIntegers'));
      return;
    }
    if (amount % mult !== 0) {
      toast.error(tt('amountMultipleErr').replace('{n}', mult));
      return;
    }
    const tenderFree = Math.max(0, (offerForTender.total_amount_needed || 0) - (offerForTender.current_filled_amount || 0));
    if (amount > tenderFree) {
      toast.error(tt('amountExceedsTender').replace('{n}', tenderFree));
      return;
    }
    if (offerCapacity && amount > Math.round(offerCapacity.free || 0)) {
      toast.error(tt('amountExceedsCapacity').replace('{n}', Math.round(offerCapacity.free || 0)));
      return;
    }
    const pricePerUnit = priceInput / (tier === 1 ? T1_MULT : 1);
    try {
      await axios.post(`${API}/tenders/${offerForTender.id}/offer`, {
        daily_amount: amount,
        price_per_unit: pricePerUnit,
      }, { headers });
      toast.success(tt('proposalSent'));
      setOfferForTender(null);
      reload();
    } catch (e) {
      toast.error(getApiErrorMessage(e) || tt('errorGeneric'));
    }
  };

  const doAccept = async (contract) => {
    try {
      await axios.post(`${API}/tenders/contracts/${contract.id}/accept`, {}, { headers });
      toast.success(tt('supplierConfirmed'));
      setAcceptTarget(null);
      reload();
    } catch (e) { toast.error(getApiErrorMessage(e) || tt('errorGeneric')); }
  };
  const doReject = async (contract) => {
    try {
      await axios.post(`${API}/tenders/contracts/${contract.id}/reject`, {}, { headers });
      toast.success(tt('proposalRejected'));
      reload();
    } catch (e) { toast.error(getApiErrorMessage(e) || tt('errorGeneric')); }
  };
  const doBreak = async () => {
    if (!breakTarget) return;
    try {
      await axios.post(`${API}/tenders/contracts/${breakTarget.id}/break`, { reason: 'manual' }, { headers });
      toast.success(tt('contractBroken'));
      setBreakTarget(null);
      setBreakMode('choice');
      reload();
    } catch (e) { toast.error(getApiErrorMessage(e) || tt('errorGeneric')); }
  };
  const proposeMutualBreak = async () => {
    if (!breakTarget) return;
    try {
      await axios.post(`${API}/tenders/contracts/${breakTarget.id}/break_request`, { reason: 'mutual' }, { headers });
      toast.success(tt('breakRequestSent') || 'Запрос на мирный разрыв отправлен');
      setBreakTarget(null);
      setBreakMode('choice');
      reload();
    } catch (e) { toast.error(getApiErrorMessage(e) || tt('errorGeneric')); }
  };
  const acceptBreakRequest = async (contract) => {
    try {
      await axios.post(`${API}/tenders/contracts/${contract.id}/break_request/accept`, {}, { headers });
      toast.success(tt('breakAcceptedMutual') || 'Контракт мирно разорван');
      reload();
    } catch (e) { toast.error(getApiErrorMessage(e) || tt('errorGeneric')); }
  };
  const rejectBreakRequest = async (contract) => {
    try {
      await axios.post(`${API}/tenders/contracts/${contract.id}/break_request/reject`, {}, { headers });
      toast.success(tt('breakRejectedMutual') || 'Запрос на разрыв отклонён');
      reload();
    } catch (e) { toast.error(getApiErrorMessage(e) || tt('errorGeneric')); }
  };
  const doDeleteTender = async (tender) => {
    if (!window.confirm(tt('deleteTenderConfirm'))) return;
    try {
      await axios.delete(`${API}/tenders/${tender.id}`, { headers });
      toast.success(tt('tenderDeleted'));
      setTenderDetail(null);
      reload();
    } catch (e) { toast.error(getApiErrorMessage(e) || tt('errorGeneric')); }
  };

  // Open amendment modal pre-filled with the current contract values, in the
  // same UX units as the rest of the page (T1 quotes prices per 10 units).
  const openAmendment = (contract) => {
    setAmendTarget(contract);
    const tier = contract.tier;
    setAmendAmount(String(Math.round(contract.daily_amount)));
    setAmendPrice(String(Math.round(tier === 1 ? contract.price_per_unit * T1_MULT : contract.price_per_unit)));
  };

  const doSubmitAmendment = async () => {
    if (!amendTarget) return;
    const tier = amendTarget.tier;
    const mult = tier === 1 ? 10 : 1;
    const amount = parseInt(amendAmount, 10);
    const priceInput = parseInt(amendPrice, 10);
    if (!amount || !priceInput) {
      toast.error(tt('fillIntegers'));
      return;
    }
    if (amount % mult !== 0) {
      toast.error(tt('amountMultipleErr').replace('{n}', mult));
      return;
    }
    const pricePerUnit = priceInput / (tier === 1 ? T1_MULT : 1);
    try {
      await axios.post(`${API}/tenders/contracts/${amendTarget.id}/amendments`, {
        daily_amount: amount,
        price_per_unit: pricePerUnit,
      }, { headers });
      toast.success(tt('amendmentSentToast') || 'Изменение отправлено — ожидается решение второй стороны');
      setAmendTarget(null);
      setAmendAmount(''); setAmendPrice('');
      reload();
    } catch (e) {
      toast.error(formatErrorDetail(e?.response?.data?.detail) || tt('errorGeneric'));
    }
  };

  // ── card renderers ───────────────────────────────────────────────────
  const renderTenderCard = (tender) => {
    const r = resourceCatalog?.[tender.resource_type] || {};
    const left = Math.max(0, tender.total_amount_needed - tender.current_filled_amount);
    const pct = Math.min(100, (tender.current_filled_amount / tender.total_amount_needed) * 100);
    return (
      <div key={tender.id} className="p-3 rounded-xl bg-zinc-900/60 border border-cyan-500/20 space-y-2" data-testid={`tender-card-${tender.id}`}>
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="text-2xl">{r.icon || '📦'}</span>
            <div>
              <div className="text-white font-bold text-sm">@{tender.buyer_username}</div>
              <div className="text-cyan-300 text-xs">
                {tt('isSeeking')} <b>{tender.total_amount_needed.toLocaleString('en-US')}</b> {tt('unitsShort')} {resLabel(tender.resource_type, tender.tier)}
              </div>
            </div>
          </div>
          <div className="text-right">
            <div className="text-amber-300 font-mono text-sm">{fmtPriceLabel(tender.max_price_per_unit, tender.tier, tt)}</div>
          </div>
        </div>
        <div className="h-1.5 rounded-full bg-zinc-800 overflow-hidden">
          <div className="h-full bg-gradient-to-r from-cyan-500 to-emerald-400" style={{ width: `${pct}%` }} />
        </div>
        <div className="flex items-center justify-between text-[11px] text-zinc-400">
          <span>{tt('filledLabel')} {Math.round(pct)}% • {tt('freeLabel')} {left.toLocaleString('en-US')} {tt('unitsPerDay')}</span>
          <span className="flex items-center gap-1"><Clock className="w-3 h-3" /> {tender.payment_hour}:00 UTC</span>
        </div>
        {hasRealBusiness ? (
          <Button
            onClick={() => openOffer(tender)}
            className="w-full bg-emerald-600 hover:bg-emerald-500 text-white h-8 text-xs"
            data-testid={`tender-offer-${tender.id}`}
          >
            {tt('respondBtn')}
          </Button>
        ) : (
          <div
            className="w-full text-center text-[10px] text-amber-300/80 px-2 py-1 rounded bg-amber-500/10 border border-amber-500/30"
            data-testid={`tender-offer-blocked-${tender.id}`}
          >
            {tt('cantBidNoBusiness') || 'Чтобы откликнуться на тендер, купите свой первый бизнес.'}
          </div>
        )}
      </div>
    );
  };

  const renderSupplierCard = (contract) => {
    const stats = contract.seller_stats || {};
    const biz = contract.seller_main_business;
    const dailyCost = contract.daily_amount * contract.price_per_unit;
    const stockDays = contract.seller_stock_days;
    const badge = statusBadge(contract.status, tt);
    return (
      <div key={contract.id} className="p-3 rounded-lg bg-zinc-950/70 border border-zinc-700/50 space-y-1.5 text-xs" data-testid={`proposal-${contract.id}`}>
        <div className="flex items-center justify-between">
          <div className="font-bold text-white">{tt('offerFrom')}: @{contract.seller_username}</div>
          <span className={`text-[10px] px-2 py-0.5 rounded border ${badge.cls}`}>{badge.label}</span>
        </div>
        <div className="text-zinc-300">{tt('proposalWord')}: <b>{contract.daily_amount.toLocaleString('en-US')}</b> {tt('unitsShort')} {resLabel(contract.resource_type, contract.tier)}</div>
        <div className="text-zinc-300">{tt('priceLabel')}: <b className="text-amber-300">{dailyCost.toFixed(2)} $CITY / {tt('perDay')}</b> ({fmtPriceLabel(contract.price_per_unit, contract.tier, tt)})</div>
        {biz && (
          <div className="text-zinc-400">{tt('sourceLabel')}: {biz.icon} {tBusiness(biz.business_type, language) || biz.name_ru} ({tt('levelShort')} {biz.level}) <span className="text-emerald-400">— {tt('verified')}</span></div>
        )}
        {contract.seller_daily_production !== undefined && (
          <div className="text-zinc-400">
            {tt('producesLabel')}: <b className="text-cyan-300">{Math.round(contract.seller_daily_production).toLocaleString('en-US')}</b> {tt('unitsPerDay')}
            {' • '}{tt('freeLabel')}: <b className="text-emerald-300">{Math.round(contract.seller_free_capacity || 0).toLocaleString('en-US')}</b>
          </div>
        )}
        <div className="flex items-center gap-2 text-zinc-400">
          <span>{tt('reliabilityLabel')}:</span> <Stars value={stats.stars ?? 5} /> <span className="text-amber-300 font-mono">({stats.reliability ?? 100}%)</span>
        </div>
        {stockDays !== undefined && (
          <div className="text-zinc-400">{tt('stockLabel')}: <b className={stockDays >= 1 ? 'text-emerald-300' : 'text-red-300'}>{stockDays >= 1 ? tt('enoughForN').replace('{n}', stockDays) : tt('noStockTomorrow')}</b></div>
        )}
        <div className="text-zinc-500">{tt('historyLabel')}: <b className="text-zinc-300">{stats.ticks_completed ?? 0}</b> {tt('successfulShort')}, <b className={stats.broken_by_seller ? 'text-red-300' : 'text-zinc-300'}>{stats.broken_by_seller ?? 0}</b> {tt('breaksShort')}</div>
        {contract.status === 'PROPOSED' && (
          <div className="flex gap-2 pt-1">
            <Button onClick={() => setAcceptTarget(contract)} className="flex-1 h-7 text-[11px] bg-emerald-600 hover:bg-emerald-500" data-testid={`proposal-accept-${contract.id}`}>
              <Check className="w-3 h-3 mr-1" /> {tt('chooseSupplier')}
            </Button>
            <Button onClick={() => doReject(contract)} variant="outline" className="h-7 text-[11px] border-red-500/40 text-red-300 hover:bg-red-500/10" data-testid={`proposal-reject-${contract.id}`}>
              <X className="w-3 h-3 mr-1" /> {tt('rejectBtn')}
            </Button>
          </div>
        )}
        {(contract.status === 'ACTIVE' || contract.status === 'PENDING_FUNDS' || contract.status === 'PENDING_RESOURCES') && (
          <div className="flex gap-2 mt-1">
            <Button onClick={() => openAmendment(contract)} variant="outline" className="flex-1 h-7 text-[11px] border-cyan-500/40 text-cyan-300 hover:bg-cyan-500/10" data-testid={`contract-amend-${contract.id}`}>
              <Sliders className="w-3 h-3 mr-1" /> {tt('updateBtn') || 'Обновить'}
            </Button>
            <Button onClick={() => { setBreakMode('choice'); setBreakTarget(contract); }} variant="outline" className="flex-1 h-7 text-[11px] border-red-500/40 text-red-300 hover:bg-red-500/10" data-testid={`contract-break-${contract.id}`}>
              <AlertTriangle className="w-3 h-3 mr-1" /> {tt('breakBtn')}
            </Button>
          </div>
        )}
        {/* Buyer-side amendment UI: shows incoming proposals from seller, or outgoing pending */}
        {contract.pending_amendment?.status === 'PENDING' && contract.pending_amendment?.proposed_by === 'seller' && (
          <div className="mt-1 p-2 rounded-lg border border-cyan-500/40 bg-cyan-500/5 space-y-1">
            <div className="text-cyan-300 text-[11px] font-semibold">
              {tt('amendmentModalTitle') || 'Предложение новых условий'}: {Math.round(contract.pending_amendment.new_daily_amount)} {tt('unitsShort') || 'ед'} × {contract.pending_amendment.new_price_per_unit?.toFixed?.(2)} $CITY
            </div>
            <div className="flex gap-2">
              <Button
                onClick={async () => {
                  try {
                    await axios.post(`${API}/tenders/contracts/${contract.id}/amendments/${contract.pending_amendment.id}/accept`, {}, { headers });
                    toast.success(tt('signContract') || 'Контракт обновлён');
                    reload();
                  } catch (e) { toast.error(formatErrorDetail(e?.response?.data?.detail) || tt('errorGeneric')); }
                }}
                className="flex-1 h-7 text-[11px] bg-emerald-600 hover:bg-emerald-500"
                data-testid={`b-amend-accept-${contract.id}`}
              >
                <Check className="w-3 h-3 mr-1" /> {tt('notifAccept') || 'Утвердить'}
              </Button>
              <Button
                onClick={async () => {
                  try {
                    await axios.post(`${API}/tenders/contracts/${contract.id}/amendments/${contract.pending_amendment.id}/reject`, {}, { headers });
                    toast.success(tt('proposalRejected') || 'Отклонено');
                    reload();
                  } catch (e) { toast.error(formatErrorDetail(e?.response?.data?.detail) || tt('errorGeneric')); }
                }}
                variant="outline"
                className="h-7 text-[11px] border-red-500/40 text-red-300 hover:bg-red-500/10"
                data-testid={`b-amend-reject-${contract.id}`}
              >
                <X className="w-3 h-3 mr-1" /> {tt('rejectBtn') || 'Отказать'}
              </Button>
            </div>
          </div>
        )}
        {contract.pending_amendment?.status === 'PENDING' && contract.pending_amendment?.proposed_by === 'buyer' && (
          <div className="mt-1 p-2 rounded-lg border border-amber-500/40 bg-amber-500/5 text-amber-200 text-[11px]">
            {tt('amendmentSentToast') || 'Изменение отправлено — ожидается решение второй стороны'}
          </div>
        )}
        {contract.break_request?.status === 'PENDING' && contract.break_request?.requested_by !== 'buyer' && (
          <div className="mt-1 p-2 rounded-lg border border-emerald-500/40 bg-emerald-500/5 space-y-1">
            <div className="text-emerald-300 text-[11px] font-semibold">{tt('breakRequestIncoming') || 'Поставщик предлагает мирный разрыв'}</div>
            <div className="flex gap-2">
              <Button onClick={() => acceptBreakRequest(contract)} className="flex-1 h-7 text-[11px] bg-emerald-600 hover:bg-emerald-500" data-testid={`br-accept-${contract.id}`}>
                <Check className="w-3 h-3 mr-1" /> {tt('breakRequestAccept') || 'Принять'}
              </Button>
              <Button onClick={() => rejectBreakRequest(contract)} variant="outline" className="h-7 text-[11px] border-red-500/40 text-red-300 hover:bg-red-500/10" data-testid={`br-reject-${contract.id}`}>
                <X className="w-3 h-3 mr-1" /> {tt('breakRequestReject') || 'Отклонить'}
              </Button>
            </div>
          </div>
        )}
        {contract.break_request?.status === 'PENDING' && contract.break_request?.requested_by === 'buyer' && (
          <div className="mt-1 p-2 rounded-lg border border-amber-500/40 bg-amber-500/5 text-amber-200 text-[11px]">
            {tt('breakRequestOutgoing') || 'Ваш запрос на мирный разрыв ждёт ответа поставщика.'}
          </div>
        )}
      </div>
    );
  };

  const renderMyTenderRow = (tender) => {
    const r = resourceCatalog?.[tender.resource_type] || {};
    const pct = Math.min(100, (tender.current_filled_amount / tender.total_amount_needed) * 100);
    const proposalsCount = (tender.contracts || []).filter(c => c.status === 'PROPOSED').length;
    const activeCount = (tender.contracts || []).filter(c => c.status === 'ACTIVE').length;
    return (
      <button
        type="button"
        key={tender.id}
        onClick={() => setTenderDetail(tender)}
        className="w-full p-3 rounded-xl bg-zinc-900/60 border border-purple-500/20 hover:border-purple-400/50 text-left transition-colors space-y-2"
        data-testid={`purchase-${tender.id}`}
      >
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="text-2xl">{r.icon || '📦'}</span>
            <div>
              <div className="text-white font-bold text-sm">{resLabel(tender.resource_type, tender.tier)}</div>
              <div className="text-zinc-400 text-xs">
                {tender.total_amount_needed.toLocaleString('en-US')} {tt('unitsPerDay')} • {fmtPriceLabel(tender.max_price_per_unit, tender.tier, tt)} • {tender.payment_hour}:00 UTC
              </div>
            </div>
          </div>
          <div className="flex flex-col items-end gap-1">
            <div className="flex items-center gap-1.5" data-testid={`tender-counters-${tender.id}`}>
              {activeCount > 0 && (
                <span
                  className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-green-500 text-zinc-950 text-[11px] font-bold shadow-[0_0_8px_rgba(34,197,94,0.45)]"
                  title={`${activeCount} ${tt('activeShort')}`}
                  data-testid={`tender-active-count-${tender.id}`}
                >
                  {activeCount}
                </span>
              )}
              {proposalsCount > 0 && (
                <span
                  className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-amber-400 text-zinc-950 text-[11px] font-bold shadow-[0_0_8px_rgba(251,191,36,0.45)]"
                  title={`${proposalsCount} ${tt('newProposals')}`}
                  data-testid={`tender-proposals-count-${tender.id}`}
                >
                  {proposalsCount}
                </span>
              )}
            </div>
          </div>
        </div>
        <div className="h-1.5 rounded-full bg-zinc-800 overflow-hidden">
          <div className="h-full bg-gradient-to-r from-purple-500 to-cyan-400" style={{ width: `${pct}%` }} />
        </div>
        <div className="text-[11px] text-zinc-400">{tt('filledLabel')} {Math.round(pct)}% ({tender.current_filled_amount}/{tender.total_amount_needed})</div>
      </button>
    );
  };

  // ── render ───────────────────────────────────────────────────────────
  return (
    <div className="space-y-4" data-testid="tenders-content">
      {/* Sub-tabs */}
      <div className="grid grid-cols-3 gap-2 border-b border-white/5 pb-2">
        <Button variant={subTab === 'exchange' ? 'default' : 'outline'} onClick={() => setSubTab('exchange')}
          className={`h-9 text-xs ${subTab === 'exchange' ? 'bg-cyan-500 text-black hover:bg-cyan-400' : 'border-cyan-500/30 text-cyan-300 hover:bg-cyan-500/10'}`}
          data-testid="tenders-tab-exchange">
          <ShoppingCart className="w-3.5 h-3.5 mr-1" /> {tt('subtabExchange')} ({exchange.length})
        </Button>
        <Button variant={subTab === 'purchases' ? 'default' : 'outline'} onClick={() => setSubTab('purchases')}
          className={`h-9 text-xs ${subTab === 'purchases' ? 'bg-purple-500 text-white hover:bg-purple-400' : 'border-purple-500/30 text-purple-300 hover:bg-purple-500/10'}`}
          data-testid="tenders-tab-purchases">
          <Tag className="w-3.5 h-3.5 mr-1" /> {tt('subtabPurchases')} ({purchases.length})
        </Button>
        <Button variant={subTab === 'supplies' ? 'default' : 'outline'} onClick={() => setSubTab('supplies')}
          className={`h-9 text-xs ${subTab === 'supplies' ? 'bg-emerald-500 text-black hover:bg-emerald-400' : 'border-emerald-500/30 text-emerald-300 hover:bg-emerald-500/10'}`}
          data-testid="tenders-tab-supplies">
          <Truck className="w-3.5 h-3.5 mr-1" /> {tt('subtabSupplies')} ({visibleSupplies.length})
        </Button>
      </div>

      {loading && (
        <div className="flex items-center justify-center py-8 text-zinc-400 text-xs">
          <Loader2 className="w-4 h-4 animate-spin mr-2" /> {tt('loading')}
        </div>
      )}

      {/* === Биржа === */}
      {subTab === 'exchange' && !loading && (
        <div className="space-y-3">
          <div className="flex items-center justify-end">
            <Button
              variant="outline"
              onClick={() => { setFilterRes(appliedFilters.res); setFilterMin(appliedFilters.min); setFilterMax(appliedFilters.max); setShowFilters(true); }}
              className={`h-8 text-xs ${hasActiveFilters ? 'border-cyan-400 text-cyan-300' : 'border-zinc-700 text-zinc-300'}`}
              data-testid="tenders-filters-open"
            >
              <Sliders className="w-3.5 h-3.5 mr-1" /> {tt('filtersBtn')}
              {hasActiveFilters && <span className="ml-1 text-[10px] px-1 rounded-full bg-cyan-400 text-black font-bold">●</span>}
            </Button>
          </div>
          {filteredExchange.length === 0 ? (
            <div className="min-h-[40vh] flex flex-col items-center justify-center text-center px-4 space-y-4" data-testid="exchange-empty">
              <ShoppingCart className="w-12 h-12 text-cyan-300/70" />
              <div className="text-zinc-300 text-base max-w-sm">
                {exchange.length === 0 ? tt('exchangeEmptyTitle') : tt('exchangeNoMatch')}<br />
                <span className="text-zinc-500 text-sm">{exchange.length === 0 ? tt('exchangeEmptyHint') : tt('exchangeNoMatchHint')}</span>
              </div>
            </div>
          ) : (
            <div className="grid gap-3 md:grid-cols-2">{filteredExchange.map(renderTenderCard)}</div>
          )}
        </div>
      )}

      {/* === Закупки === */}
      {subTab === 'purchases' && !loading && (
        <>
          {!hasRealBusiness && (
            <div
              className="mb-3 rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-amber-200 text-xs"
              data-testid="tenders-need-business-notice"
            >
              {tt('cantPublishTenderNoBusiness') || 'Чтобы публиковать тендеры, купите свой первый бизнес.'}
            </div>
          )}
          {purchases.length === 0 ? (
            <div className="min-h-[40vh] flex flex-col items-center justify-center text-center px-4 space-y-4" data-testid="purchases-empty">
              <FilePlus2 className="w-12 h-12 text-purple-300/70" />
              <div className="text-zinc-300 text-base max-w-sm">
                {tt('purchasesEmptyTitle')}<br /><span className="text-zinc-500 text-sm">{tt('purchasesEmptyHint')}</span>
              </div>
              {hasRealBusiness && (
                <Button onClick={() => setShowCreate(true)} className="h-10 px-5 bg-purple-600 hover:bg-purple-500" data-testid="tenders-create-empty-btn">
                  + {tt('newTenderBtn')}
                </Button>
              )}
            </div>
          ) : (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <div className="text-[11px] text-zinc-400">
                  {purchases.length} / {MAX_TENDERS} {tt('tendersWord')}
                </div>
                {hasRealBusiness && (
                  <Button
                    onClick={() => purchases.length >= MAX_TENDERS ? toast.error(tt('tendersLimitMsg').replace('{n}', MAX_TENDERS)) : setShowCreate(true)}
                    className={`h-8 text-xs ${purchases.length >= MAX_TENDERS ? 'bg-zinc-700 cursor-not-allowed' : 'bg-purple-600 hover:bg-purple-500'}`}
                    data-testid="tenders-create-btn"
                  >
                    + {tt('newTenderBtn')}
                  </Button>
                )}
              </div>
              {purchases.map(renderMyTenderRow)}
            </div>
          )}
        </>
      )}

      {/* === Поставки === */}
      {subTab === 'supplies' && !loading && (
        <div className="space-y-3">
          {visibleSupplies.length === 0 ? (
            <div className="min-h-[40vh] flex flex-col items-center justify-center text-center px-4 space-y-4" data-testid="supplies-empty">
              <Truck className="w-12 h-12 text-emerald-300/70" />
              <div className="text-zinc-300 text-base max-w-sm">
                {tt('suppliesEmptyTitle')}<br />
                <span className="text-zinc-500 text-sm">{tt('suppliesEmptyHint')}</span>
              </div>
            </div>
          ) : (
            visibleSupplies.map((c) => {
              const r = resourceCatalog?.[c.resource_type] || {};
              const dailyCost = c.daily_amount * c.price_per_unit;
              const net = dailyCost * (1 - c.tax_rate);
              const badge = statusBadge(c.status, tt);
              return (
                <div key={c.id} className="p-3 rounded-xl bg-zinc-900/60 border border-emerald-500/20 space-y-1.5" data-testid={`supply-${c.id}`}>
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className="text-2xl">{r.icon || '📦'}</span>
                      <div>
                        <div className="text-white font-bold text-sm">{tt('buyerLabel')}: @{c.buyer_username}</div>
                        <div className="text-zinc-300 text-xs">{c.daily_amount.toLocaleString('en-US')} {tt('unitsShort')} {resLabel(c.resource_type, c.tier)} / {tt('perDay')}</div>
                      </div>
                    </div>
                    <span className={`text-[10px] px-2 py-0.5 rounded border h-fit ${badge.cls}`}>{badge.label}</span>
                  </div>
                  <div className="grid grid-cols-3 gap-2 text-[11px]">
                    <div className="rounded bg-zinc-950/70 p-1.5">
                      <div className="text-zinc-500">{tt('grossLabel')}</div>
                      <div className="text-amber-300 font-mono">{dailyCost.toFixed(2)} $CITY</div>
                    </div>
                    <div className="rounded bg-zinc-950/70 p-1.5">
                      <div className="text-zinc-500">{tt('taxLabel')} {(c.tax_rate * 100).toFixed(0)}%</div>
                      <div className="text-red-300 font-mono">−{(dailyCost - net).toFixed(2)} $CITY</div>
                    </div>
                    <div className="rounded bg-zinc-950/70 p-1.5">
                      <div className="text-zinc-500">{tt('netLabel')}</div>
                      <div className="text-emerald-300 font-mono">{net.toFixed(2)} $CITY</div>
                    </div>
                  </div>
                  <div className="text-[11px] text-zinc-400">
                    {tt('stockLabel')}: {c.my_stock_days >= 1 ? <span className="text-emerald-300">{tt('enoughForN').replace('{n}', c.my_stock_days)}</span> : <span className="text-red-300">{tt('notEnoughTomorrow')}</span>}
                    {' '}• {tt('clearingAt')} {c.payment_hour}:00 UTC
                  </div>
                  <div className="text-[11px] text-zinc-500">
                    {tt('escrowSmall')}: <b>{c.escrow_deposit?.toFixed(2)} $CITY</b> • {tt('ticksLabel')}: <b>{c.ticks_completed}</b>
                  </div>
                  {(c.status === 'ACTIVE' || c.status === 'PENDING_FUNDS' || c.status === 'PENDING_RESOURCES') && (
                    <div className="flex gap-2">
                      <Button onClick={() => openAmendment(c)} variant="outline" className="flex-1 h-7 text-[11px] border-cyan-500/40 text-cyan-300 hover:bg-cyan-500/10" data-testid={`supply-amend-${c.id}`}>
                        <Sliders className="w-3 h-3 mr-1" /> {tt('updateBtn') || 'Обновить'}
                      </Button>
                      <Button onClick={() => { setBreakMode('choice'); setBreakTarget(c); }} variant="outline" className="flex-1 h-7 text-[11px] border-red-500/40 text-red-300 hover:bg-red-500/10" data-testid={`supply-break-${c.id}`}>
                        <AlertTriangle className="w-3 h-3 mr-1" /> {tt('breakBtn')}
                      </Button>
                    </div>
                  )}
                  {c.pending_amendment?.status === 'PENDING' && c.pending_amendment?.proposed_by === 'seller' && (
                    <div className="mt-1 p-2 rounded-lg border border-amber-500/40 bg-amber-500/5 text-amber-200 text-[11px]">
                      {tt('amendmentSentToast') || 'Изменение отправлено — ожидается решение второй стороны'}
                    </div>
                  )}
                  {c.pending_amendment?.status === 'PENDING' && c.pending_amendment?.proposed_by === 'buyer' && (
                    <div className="mt-1 p-2 rounded-lg border border-cyan-500/40 bg-cyan-500/5 space-y-1">
                      <div className="text-cyan-300 text-[11px] font-semibold">
                        {tt('amendmentModalTitle') || 'Предложение новых условий'}: {Math.round(c.pending_amendment.new_daily_amount)} {tt('unitsShort') || 'ед'} × {c.pending_amendment.new_price_per_unit?.toFixed?.(2)} $CITY
                      </div>
                      <div className="flex gap-2">
                        <Button
                          onClick={async () => {
                            try {
                              await axios.post(`${API}/tenders/contracts/${c.id}/amendments/${c.pending_amendment.id}/accept`, {}, { headers });
                              toast.success(tt('signContract') || 'Контракт обновлён');
                              reload();
                            } catch (e) { toast.error(formatErrorDetail(e?.response?.data?.detail) || tt('errorGeneric')); }
                          }}
                          className="flex-1 h-7 text-[11px] bg-emerald-600 hover:bg-emerald-500"
                          data-testid={`s-amend-accept-${c.id}`}
                        >
                          <Check className="w-3 h-3 mr-1" /> {tt('notifAccept') || 'Утвердить'}
                        </Button>
                        <Button
                          onClick={async () => {
                            try {
                              await axios.post(`${API}/tenders/contracts/${c.id}/amendments/${c.pending_amendment.id}/reject`, {}, { headers });
                              toast.success(tt('proposalRejected') || 'Отклонено');
                              reload();
                            } catch (e) { toast.error(formatErrorDetail(e?.response?.data?.detail) || tt('errorGeneric')); }
                          }}
                          variant="outline"
                          className="h-7 text-[11px] border-red-500/40 text-red-300 hover:bg-red-500/10"
                          data-testid={`s-amend-reject-${c.id}`}
                        >
                          <X className="w-3 h-3 mr-1" /> {tt('rejectBtn') || 'Отказать'}
                        </Button>
                      </div>
                    </div>
                  )}
                  {c.break_request?.status === 'PENDING' && c.break_request?.requested_by !== 'seller' && (
                    <div className="mt-1 p-2 rounded-lg border border-emerald-500/40 bg-emerald-500/5 space-y-1">
                      <div className="text-emerald-300 text-[11px] font-semibold">{tt('breakRequestIncomingS') || 'Покупатель предлагает мирный разрыв'}</div>
                      <div className="flex gap-2">
                        <Button onClick={() => acceptBreakRequest(c)} className="flex-1 h-7 text-[11px] bg-emerald-600 hover:bg-emerald-500" data-testid={`s-br-accept-${c.id}`}>
                          <Check className="w-3 h-3 mr-1" /> {tt('breakRequestAccept') || 'Принять'}
                        </Button>
                        <Button onClick={() => rejectBreakRequest(c)} variant="outline" className="h-7 text-[11px] border-red-500/40 text-red-300 hover:bg-red-500/10" data-testid={`s-br-reject-${c.id}`}>
                          <X className="w-3 h-3 mr-1" /> {tt('breakRequestReject') || 'Отклонить'}
                        </Button>
                      </div>
                    </div>
                  )}
                  {c.break_request?.status === 'PENDING' && c.break_request?.requested_by === 'seller' && (
                    <div className="mt-1 p-2 rounded-lg border border-amber-500/40 bg-amber-500/5 text-amber-200 text-[11px]">
                      {tt('breakRequestOutgoingS') || 'Ваш запрос на мирный разрыв ждёт ответа покупателя.'}
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      )}

      {/* ── Filters modal ── */}
      <Dialog open={showFilters} onOpenChange={setShowFilters}>
        <DialogContent className="bg-black border-cyan-500/30 text-white max-w-md">
          <DialogHeader>
            <DialogTitle>{tt('tendersFiltersTitle')}</DialogTitle>
            <DialogDescription className="text-zinc-400 text-xs">{tt('tendersFiltersDesc')}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <label className="text-xs text-zinc-400 mb-1.5 block">{tt('resourceLabel')}</label>
              <ResourcePicker catalog={resourceCatalog} value={filterRes} onChange={setFilterRes} testId="filter-res-picker" language={language} />
            </div>
            <div>
              <label className="text-xs text-zinc-400 mb-1.5 block">{tt('priceRangeCap')}</label>
              <div className="flex gap-2">
                <Input type="text" inputMode="numeric" placeholder={tt('fromLabel')} value={filterMin} onChange={onIntChange(setFilterMin)} className="bg-zinc-900 border-zinc-700 text-white" data-testid="filter-price-min" />
                <Input type="text" inputMode="numeric" placeholder={tt('toLabel')} value={filterMax} onChange={onIntChange(setFilterMax)} className="bg-zinc-900 border-zinc-700 text-white" data-testid="filter-price-max" />
              </div>
              <div className="text-[10px] text-zinc-500 mt-1">{tt('t1PriceHint')}</div>
            </div>
            <div className="flex gap-2 pt-2">
              <Button
                variant="outline"
                onClick={() => { setFilterRes(''); setFilterMin(''); setFilterMax(''); setAppliedFilters({ res: '', min: '', max: '' }); setShowFilters(false); }}
                className="flex-1 border-zinc-700 text-zinc-300 hover:bg-zinc-800"
                data-testid="filter-reset"
              >
                {tt('resetFilters')}
              </Button>
              <Button
                onClick={() => { setAppliedFilters({ res: filterRes, min: filterMin, max: filterMax }); setShowFilters(false); }}
                className="flex-1 bg-cyan-600 hover:bg-cyan-500"
                data-testid="filter-apply"
              >
                {tt('apply')}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* ── Create Tender modal ── */}
      <Dialog open={showCreate} onOpenChange={setShowCreate}>
        <DialogContent className="bg-black border-purple-500/30 text-white max-w-md">
          <DialogHeader>
            <DialogTitle>{tt('createTenderTitle')}</DialogTitle>
            <DialogDescription className="text-zinc-400 text-xs">{tt('createTenderDesc')}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <label className="text-xs text-zinc-400 mb-1.5 block">{tt('resourceLabel')}</label>
              <ResourcePicker catalog={resourceCatalog} value={createRes} onChange={setCreateRes} testId="create-res-picker" language={language} />
            </div>
            <div>
              <label className="text-xs text-zinc-400 mb-1.5 block">
                {tt('dailyNeededLabel')}
                {createRes && (resourceCatalog?.[createRes]?.tier === 1) && (
                  <span className="text-amber-400"> {tt('multipleOf10Hint')}</span>
                )}
              </label>
              <Input type="text" inputMode="numeric" value={createNeeded} onChange={onIntChange(setCreateNeeded)} className="bg-zinc-900 border-zinc-700 text-white" data-testid="create-tender-needed" />
            </div>
            <div>
              <label className="text-xs text-zinc-400 mb-1.5 block">
                {tt('maxPriceLabel')} ({(resourceCatalog?.[createRes]?.tier === 1) ? tt('per10Units') : tt('per1Unit')}), $CITY
              </label>
              <Input type="text" inputMode="numeric" value={createMaxPrice} onChange={onIntChange(setCreateMaxPrice)} className="bg-zinc-900 border-zinc-700 text-white" data-testid="create-tender-price" />
            </div>
            <div>
              <label className="text-xs text-zinc-400 mb-1.5 block">{tt('clearingHourLabel')}</label>
              <Input type="text" inputMode="numeric" value={createHour} onChange={onIntChange(setCreateHour)} className="bg-zinc-900 border-zinc-700 text-white" data-testid="create-tender-hour" />
            </div>
            <Button onClick={doCreateTender} className="w-full bg-purple-600 hover:bg-purple-500" data-testid="create-tender-submit">{tt('createBtn')}</Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* ── Submit Offer modal ── */}
      <Dialog open={!!offerForTender} onOpenChange={(o) => !o && setOfferForTender(null)}>
        <DialogContent className="bg-black border-emerald-500/30 text-white max-w-md">
          <DialogHeader>
            <DialogTitle>{tt('respondToTender')}</DialogTitle>
            {offerForTender && (
              <DialogDescription className="text-zinc-400 text-xs">
                @{offerForTender.buyer_username}: {tt('isSeeking')} {Math.round(offerForTender.total_amount_needed).toLocaleString('en-US')} {tt('unitsShort')} {resLabel(offerForTender.resource_type, offerForTender.tier)}, {fmtPriceLabel(offerForTender.max_price_per_unit, offerForTender.tier, tt)}.
              </DialogDescription>
            )}
          </DialogHeader>
          {offerForTender && (() => {
            const tier = offerForTender.tier;
            const mult = tier === 1 ? 10 : 1;
            const tenderFree = Math.max(0, (offerForTender.total_amount_needed || 0) - (offerForTender.current_filled_amount || 0));
            const capFree = Math.round(offerCapacity?.free ?? 0);
            const maxAllowedRaw = Math.min(capFree, tenderFree);
            const maxAllowed = Math.floor(maxAllowedRaw / mult) * mult;
            const amountNum = parseInt(offerAmount, 10) || 0;
            const priceNum = parseInt(offerPrice, 10) || 0;
            const priceCap = Math.round(tier === 1 ? offerForTender.max_price_per_unit * T1_MULT : offerForTender.max_price_per_unit);
            const dailyTurnover = amountNum && priceNum ? (amountNum * priceNum / (tier === 1 ? T1_MULT : 1)) : 0;
            const sellerLockTon = (dailyTurnover * 1) / 1000.0;
            return (
              <div className="space-y-3">
                {offerCapacity && (
                  <div className="text-xs p-2 bg-zinc-950 border border-zinc-700 rounded text-zinc-300">
                    {tt('freeCapacity')}: <b className="text-emerald-300">{capFree} {tt('unitsPerDay')}</b><br />
                    ({tt('production')} {Math.round(offerCapacity.daily_production)}, {tt('committed')} {Math.round(offerCapacity.committed)})
                  </div>
                )}
                <div>
                  <label className="text-xs text-zinc-400 mb-1.5 block">
                    {tt('dailyUnits')} (≤ {maxAllowed}{mult > 1 ? `, ${tt('multipleOfN').replace('{n}', mult)}` : ''})
                  </label>
                  <Input
                    type="text" inputMode="numeric" value={offerAmount}
                    onChange={(e) => {
                      const raw = String(e.target.value || '').replace(/[^\d]/g, '');
                      if (raw === '') { setOfferAmount(''); return; }
                      let v = parseInt(raw, 10);
                      if (v > maxAllowed) v = maxAllowed;
                      setOfferAmount(String(Math.max(0, v)));
                    }}
                    className="bg-zinc-900 border-zinc-700 text-white" data-testid="submit-offer-amount"
                  />
                </div>
                <div>
                  <label className="text-xs text-zinc-400 mb-1.5 block">
                    {tt('priceLabel')} {tier === 1 ? tt('per10Units') : tt('per1Unit')}, $CITY (≤ {priceCap})
                  </label>
                  <Input
                    type="text" inputMode="numeric" value={offerPrice}
                    onChange={(e) => {
                      const raw = String(e.target.value || '').replace(/[^\d]/g, '');
                      if (raw === '') { setOfferPrice(''); return; }
                      let v = parseInt(raw, 10);
                      if (v > priceCap) v = priceCap;
                      setOfferPrice(String(Math.max(0, v)));
                    }}
                    className="bg-zinc-900 border-zinc-700 text-white" data-testid="submit-offer-price"
                  />
                </div>
                {amountNum > 0 && priceNum > 0 && (
                  <>
                    <div className="text-[11px] text-zinc-400 p-2 rounded bg-zinc-950 border border-zinc-700">
                      {tt('dailyTurnover')}: <b className="text-amber-300">{dailyTurnover.toFixed(2)} $CITY</b>
                      {' • '}{tt('taxLabel')} {tierTaxPct(tier)}%
                    </div>
                    <div className="text-[11px] text-amber-300 p-2 rounded bg-amber-500/5 border border-amber-500/30 flex items-start gap-2">
                      <Lock className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                      <span>
                        {tt('sellerLockNotice')
                          .replace('{city}', dailyTurnover.toFixed(2))
                          .replace('{ton}', sellerLockTon.toFixed(4))}
                      </span>
                    </div>
                  </>
                )}
                <Button onClick={doSubmitOffer} className="w-full bg-emerald-600 hover:bg-emerald-500" data-testid="submit-offer-btn">{tt('sendProposal')}</Button>
              </div>
            );
          })()}
        </DialogContent>
      </Dialog>

      {/* ── Tender Detail (buyer reviews suppliers here) ── */}
      <Dialog open={!!tenderDetail} onOpenChange={(o) => !o && setTenderDetail(null)}>
        <DialogContent className="bg-black border-purple-500/30 text-white max-w-lg max-h-[85vh] overflow-y-auto">
          {tenderDetail && (() => {
            const r = resourceCatalog?.[tenderDetail.resource_type] || {};
            const pct = Math.min(100, (tenderDetail.current_filled_amount / tenderDetail.total_amount_needed) * 100);
            const proposals = (tenderDetail.contracts || []).filter(c => c.status === 'PROPOSED');
            // Issue #4: hide BROKEN contracts — both buyer and seller don't want to see them.
            const others = (tenderDetail.contracts || []).filter(c => c.status !== 'PROPOSED' && c.status !== 'BROKEN');
            return (
              <>
                <DialogHeader>
                  <DialogTitle className="flex items-center gap-2">
                    <span className="text-2xl">{r.icon || '📦'}</span>
                    {resLabel(tenderDetail.resource_type, tenderDetail.tier)}
                  </DialogTitle>
                  <DialogDescription className="text-zinc-400 text-xs">
                    {tenderDetail.total_amount_needed.toLocaleString('en-US')} {tt('unitsPerDay')} • {fmtPriceLabel(tenderDetail.max_price_per_unit, tenderDetail.tier, tt)} • {tt('clearingAt')} {tenderDetail.payment_hour}:00 UTC
                  </DialogDescription>
                </DialogHeader>
                <div className="h-1.5 rounded-full bg-zinc-800 overflow-hidden">
                  <div className="h-full bg-gradient-to-r from-purple-500 to-cyan-400" style={{ width: `${pct}%` }} />
                </div>
                <div className="text-[11px] text-zinc-400 mb-2">{tt('filledLabel')} {Math.round(pct)}% ({tenderDetail.current_filled_amount}/{tenderDetail.total_amount_needed})</div>

                {proposals.length > 0 && (
                  <div className="space-y-2">
                    <div className="text-amber-300 text-xs font-bold">{tt('newProposalsTitle')} ({proposals.length})</div>
                    {proposals.map(renderSupplierCard)}
                  </div>
                )}
                {others.length > 0 && (
                  <div className="space-y-2 pt-3">
                    <div className="text-zinc-400 text-xs font-bold">{tt('suppliersTitle')} ({others.length})</div>
                    {others.map(renderSupplierCard)}
                  </div>
                )}
                {(tenderDetail.contracts || []).length === 0 && (
                  <div className="p-4 text-center text-sm text-zinc-500">{tt('noResponsesYet')}</div>
                )}

                <div className="pt-3 border-t border-zinc-700 flex gap-2">
                  <Button
                    variant="outline"
                    onClick={() => doDeleteTender(tenderDetail)}
                    className="w-full border-red-500/40 text-red-300 hover:bg-red-500/10"
                    data-testid="tender-detail-delete"
                  >
                    <Trash2 className="w-3.5 h-3.5 mr-1" /> {tt('deleteTenderBtn')}
                  </Button>
                </div>
              </>
            );
          })()}
        </DialogContent>
      </Dialog>

      {/* ── Accept Confirm (buyer confirms supplier with escrow info) ── */}
      <Dialog open={!!acceptTarget} onOpenChange={(o) => !o && setAcceptTarget(null)}>
        <DialogContent className="bg-black border-emerald-500/30 text-white w-[calc(100vw-1.5rem)] sm:max-w-md overflow-x-hidden">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-emerald-300">
              <Check className="w-4 h-4 shrink-0" />
              <span className="break-words">{tt('confirmSupplierTitle')}</span>
            </DialogTitle>
            {acceptTarget && (() => {
              const dailyCost = (acceptTarget.daily_amount || 0) * (acceptTarget.price_per_unit || 0);
              const buyerLockCity = dailyCost * 2;
              const buyerLockTon = buyerLockCity / 1000;
              const sellerLockCity = dailyCost * 1;
              const sellerLockTon = sellerLockCity / 1000;
              return (
                <DialogDescription asChild>
                  <div className="text-zinc-300 text-sm space-y-2 break-words">
                    <div className="break-words">
                      {tt('aboutToHire')} <b className="text-white">@{acceptTarget.seller_username}</b> {tt('forDailySupply')}{' '}
                      <b className="text-cyan-300">{Math.round(acceptTarget.daily_amount).toLocaleString('en-US')} {tt('unitsShort')}</b>{' '}
                      {resLabel(acceptTarget.resource_type, acceptTarget.tier)}.
                    </div>
                    <div className="p-2 rounded bg-amber-500/5 border border-amber-500/30 text-amber-200 text-[12px] flex items-start gap-2">
                      <Lock className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                      <div className="space-y-1 min-w-0 break-words">
                        <div className="break-words">
                          {tt('yourEscrowLabel')} <b>{buyerLockCity.toFixed(2)} $CITY</b> (≈ {buyerLockTon.toFixed(4)} TON):
                          <br />
                          <span className="text-amber-100/70 text-[11px] break-words">{tt('buyerLockBreakdown').replace('{daily}', dailyCost.toFixed(2))}</span>
                        </div>
                        <div className="break-words">
                          {tt('sellerEscrowLabel')} <b>{sellerLockCity.toFixed(2)} $CITY</b> (≈ {sellerLockTon.toFixed(4)} TON) — {tt('sellerLockReason')}.
                        </div>
                      </div>
                    </div>
                    <div className="text-zinc-400 text-[11px] break-words">{tt('escrowWithdrawHint')}</div>
                  </div>
                </DialogDescription>
              );
            })()}
          </DialogHeader>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => setAcceptTarget(null)} className="flex-1 border-zinc-700 text-zinc-300 hover:bg-zinc-800" data-testid="accept-cancel">{tt('cancelBtn')}</Button>
            <Button onClick={() => acceptTarget && doAccept(acceptTarget)} className="flex-1 bg-emerald-600 hover:bg-emerald-500" data-testid="accept-confirm">{tt('signContract')}</Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* ── Amendment ("Обновить") modal — seller proposes new terms ── */}
      <Dialog open={!!amendTarget} onOpenChange={(o) => { if (!o) { setAmendTarget(null); setAmendAmount(''); setAmendPrice(''); } }}>
        <DialogContent className="bg-black border-cyan-500/30 text-white w-[calc(100vw-1.5rem)] sm:max-w-md overflow-x-hidden">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-cyan-300">
              <Sliders className="w-4 h-4 shrink-0" />
              <span className="break-words">{tt('amendmentModalTitle') || 'Предложить новые условия'}</span>
            </DialogTitle>
            <DialogDescription className="text-zinc-400 text-xs break-words">
              {tt('amendmentModalDesc') || 'Измените количество и цену. Вторая сторона должна утвердить изменения.'}
            </DialogDescription>
          </DialogHeader>
          {amendTarget && (() => {
            const tier = amendTarget.tier;
            const mult = tier === 1 ? 10 : 1;
            const amountNum = parseInt(amendAmount, 10) || 0;
            const priceNum = parseInt(amendPrice, 10) || 0;
            const pricePerUnit = priceNum / (tier === 1 ? T1_MULT : 1);
            const oldDailyCost = amendTarget.daily_amount * amendTarget.price_per_unit;
            const newDailyCost = amountNum * pricePerUnit;
            // The seller-side delta is +1 day's worth of the change (SELLER_ESCROW_DAYS=1).
            const sellerDeltaCity = newDailyCost - oldDailyCost;
            const sellerDeltaTon = sellerDeltaCity / 1000;
            return (
              <div className="space-y-3">
                <div className="text-[11px] text-zinc-400 p-2 rounded bg-zinc-950 border border-zinc-700">
                  {tt('currentTermsLabel') || 'Текущие условия'}: <b className="text-zinc-200">{Math.round(amendTarget.daily_amount)} {tt('unitsShort') || 'ед'} × {(tier === 1 ? amendTarget.price_per_unit * T1_MULT : amendTarget.price_per_unit).toFixed(2)} $CITY</b>
                  <span className="text-zinc-500"> ({oldDailyCost.toFixed(2)} $CITY/{tt('perDay') || 'день'})</span>
                </div>
                <div>
                  <label className="text-xs text-zinc-400 mb-1.5 block">
                    {tt('amendmentNewAmount') || 'Новое количество в сутки'}{mult > 1 ? ` (${tt('multipleOfN') ? tt('multipleOfN').replace('{n}', mult) : `× ${mult}`})` : ''}
                  </label>
                  <Input type="text" inputMode="numeric" value={amendAmount} onChange={onIntChange(setAmendAmount)} className="bg-zinc-900 border-zinc-700 text-white" data-testid="amend-amount" />
                </div>
                <div>
                  <label className="text-xs text-zinc-400 mb-1.5 block">
                    {tt('amendmentNewPrice') || 'Новая цена'} ({tier === 1 ? tt('per10Units') : tt('per1Unit')}), $CITY
                  </label>
                  <Input type="text" inputMode="numeric" value={amendPrice} onChange={onIntChange(setAmendPrice)} className="bg-zinc-900 border-zinc-700 text-white" data-testid="amend-price" />
                </div>
                {amountNum > 0 && priceNum > 0 && (
                  <div className="text-[11px] p-2 rounded bg-amber-500/5 border border-amber-500/30 text-amber-200 flex items-start gap-2">
                    <Lock className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                    <span className="break-words">
                      {sellerDeltaCity > 0.001
                        ? (tt('amendmentDeltaPositive') || 'К вашей заморозке будет добавлено {city} $CITY (≈ {ton} TON).')
                            .replace('{city}', sellerDeltaCity.toFixed(2))
                            .replace('{ton}', sellerDeltaTon.toFixed(4))
                        : sellerDeltaCity < -0.001
                        ? (tt('amendmentDeltaNegative') || 'Будет разморожено {city} $CITY (≈ {ton} TON) и возвращено в баланс.')
                            .replace('{city}', Math.abs(sellerDeltaCity).toFixed(2))
                            .replace('{ton}', Math.abs(sellerDeltaTon).toFixed(4))
                        : (tt('amendmentDeltaZero') || 'Сумма заморозки не изменится.')}
                    </span>
                  </div>
                )}
                <Button onClick={doSubmitAmendment} className="w-full bg-cyan-600 hover:bg-cyan-500" data-testid="amend-submit-btn">
                  {tt('amendmentSubmitBtn') || 'Предложить'}
                </Button>
              </div>
            );
          })()}
        </DialogContent>
      </Dialog>

      {/* ── Break Choice + Confirm ── */}
      <Dialog open={!!breakTarget} onOpenChange={(o) => { if (!o) { setBreakTarget(null); setBreakMode('choice'); } }}>
        <DialogContent className="bg-black border-red-500/30 text-white w-[calc(100vw-1.5rem)] sm:max-w-md overflow-x-hidden">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-red-300">
              <AlertTriangle className="w-4 h-4 shrink-0" />
              <span className="break-words">{tt('breakContractTitle')}</span>
            </DialogTitle>
            {breakTarget && breakMode === 'choice' && (
              <DialogDescription className="text-zinc-300 text-sm space-y-2 break-words">
                <span>{tt('breakChoiceDesc') || 'Выберите способ разрыва контракта:'}</span>
              </DialogDescription>
            )}
            {breakTarget && breakMode === 'unilateral' && (
              <DialogDescription className="text-zinc-300 text-sm break-words">
                {tt('breakPenaltyWarning')
                  .replace('{city}', (breakTarget.daily_amount * breakTarget.price_per_unit).toFixed(2))}
              </DialogDescription>
            )}
          </DialogHeader>

          {breakMode === 'choice' && breakTarget && (
            <div className="space-y-3">
              <button
                type="button"
                onClick={proposeMutualBreak}
                data-testid="break-propose-mutual"
                className="w-full text-left p-3 rounded-xl border border-emerald-500/40 bg-emerald-500/5 hover:bg-emerald-500/10 transition-colors"
              >
                <div className="flex items-start gap-2">
                  <Check className="w-4 h-4 text-emerald-300 mt-0.5 shrink-0" />
                  <div className="min-w-0">
                    <div className="text-emerald-200 font-semibold text-sm">{tt('breakProposeMutualTitle') || 'Предложить мирный разрыв'}</div>
                    <div className="text-zinc-400 text-[12px] mt-0.5 leading-relaxed">{tt('breakProposeMutualDesc') || 'Запрос отправится второй стороне. При согласии — без штрафов, замороженные средства разблокируются.'}</div>
                  </div>
                </div>
              </button>
              <button
                type="button"
                onClick={() => setBreakMode('unilateral')}
                data-testid="break-go-unilateral"
                className="w-full text-left p-3 rounded-xl border border-red-500/40 bg-red-500/5 hover:bg-red-500/10 transition-colors"
              >
                <div className="flex items-start gap-2">
                  <AlertTriangle className="w-4 h-4 text-red-300 mt-0.5 shrink-0" />
                  <div className="min-w-0">
                    <div className="text-red-200 font-semibold text-sm">{tt('breakUnilateralTitle') || 'Разорвать в одностороннем порядке'}</div>
                    <div className="text-zinc-400 text-[12px] mt-0.5 leading-relaxed">
                      {(tt('breakUnilateralDesc') || 'Виновник платит суточную издержку — {city} $CITY.').replace('{city}', (breakTarget.daily_amount * breakTarget.price_per_unit).toFixed(2))}
                    </div>
                  </div>
                </div>
              </button>
            </div>
          )}
          {breakMode === 'unilateral' && (
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => setBreakMode('choice')} className="flex-1 border-zinc-700 text-zinc-300 hover:bg-zinc-800" data-testid="break-back">{tt('backBtn') || 'Назад'}</Button>
              <Button onClick={doBreak} className="flex-1 bg-red-600 hover:bg-red-500" data-testid="break-confirm">{tt('breakConfirmBtn')}</Button>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

const tierTaxPct = (tier) => ({ 1: 15, 2: 23, 3: 30 }[tier] || 15);
