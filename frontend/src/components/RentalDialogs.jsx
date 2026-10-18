/**
 * Renting businesses: «Сдать в аренду» (owner), «Арендовать» (renter), the «Аренда» tab.
 * Server: backend/rental.py. All texts are in lib/translationsMore.js (9 languages).
 */
import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useTranslation } from '@/lib/translations';
import { fill } from '@/lib/translationsMore';
import { citySpriteUrl } from '@/lib/citySprites';

const API = `${process.env.REACT_APP_BACKEND_URL || ''}/api`;
const auth = () => ({ Authorization: `Bearer ${localStorage.getItem('token') || localStorage.getItem('ton_city_token') || ''}` });
const n = (v) => Math.round(Number(v || 0)).toLocaleString('ru-RU');
const date = (s) => (s ? new Date(s).toLocaleString(undefined, { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '');

async function call(path, opts = {}) {
  const r = await fetch(`${API}${path}`, { ...opts, headers: { 'Content-Type': 'application/json', ...auth(), ...(opts.headers || {}) } });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'Error');
  return d;
}

/** Economics of one day (3 shifts) + contracts — shown before confirming. */
export function RentalEstimate({ data, rentCity, lang }) {
  const { t } = useTranslation(lang);
  if (!data) return <div className="text-xs text-text-muted">…</div>;
  const e = data.estimate;
  const row = (label, v, cls = 'text-white') => (
    <div className="flex justify-between text-sm"><span className="text-text-muted">{label}</span><span className={`font-semibold ${cls}`}>{v}</span></div>
  );
  const renter = rentCity != null ? e.net_city - rentCity : null;
  return (
    <div className="space-y-2" data-testid="rental-estimate">
      <div className="rounded-xl border border-white/10 bg-white/5 p-3 space-y-1.5">
        <div className="text-[11px] uppercase tracking-wider text-cyan-300">{t('rt_per_day_calc')}</div>
        {row(t('rt_production'), `${n(e.units_per_day)} · +${n(e.income_city)} $CITY`, 'text-emerald-300')}
        {row(t('rt_inputs'), `−${n(e.inputs_city)} $CITY`, 'text-red-300')}
        {row(t('rt_repair'), `−${n(e.repair_city)} $CITY`, 'text-red-300')}
        {row(t('rt_tax'), `−${n(e.tax_city)} $CITY`, 'text-red-300')}
        <div className="border-t border-white/10 pt-1.5">{row(t('rt_net'), `${n(e.net_city)} $CITY`, 'text-white')}</div>
        {rentCity != null && row(t('rt_rent_per_day'), `−${n(rentCity)} $CITY`, 'text-amber-300')}
        {renter != null && row(t('rt_renter_profit'), `${renter >= 0 ? '+' : ''}${n(renter)} $CITY`, renter >= 0 ? 'text-emerald-300' : 'text-red-400')}
        <div className="text-[10px] text-text-muted">{t('rt_estimate_note')}</div>
      </div>
      <div className="rounded-xl border border-white/10 bg-white/5 p-3 space-y-1">
        <div className="text-[11px] uppercase tracking-wider text-cyan-300">{t('rt_contracts')}</div>
        {(data.contracts || []).length === 0 && <div className="text-xs text-text-muted">{t('rt_no_contracts')}</div>}
        {(data.contracts || []).map((c) => (
          <div key={c.id} className="text-xs text-white">
            {c.role === 'поставляет' ? t('rt_role_supplies') : t('rt_role_receives')} {c.resource} · {n(c.amount_per_day)}{t('rt_per_day_short')}
            {c.partner ? ` · @${c.partner}` : ''} · {fill(t('rt_until'), { date: date(c.expires_at) })}
          </div>
        ))}
      </div>
    </div>
  );
}

/** Owner: «Сдать в аренду». */
export function RentOutDialog({ business, open, onOpenChange, onDone, lang }) {
  const { t } = useTranslation(lang);
  const [data, setData] = useState(null);
  const [price, setPrice] = useState('');
  const [minD, setMinD] = useState(1); const [maxD, setMaxD] = useState(7);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!open || !business) return;
    setData(null);
    call(`/rental/estimate/${business.id}`).then((d) => {
      setData(d); setPrice(String(Math.round((d.bounds.min_city + d.bounds.max_city) / 2)));
      setMinD(d.limits.min_days); setMaxD(Math.min(7, d.limits.max_days));
    }).catch((e) => toast.error(e.message));
  }, [open, business]);
  const submit = async () => {
    setBusy(true);
    try {
      await call('/rental/offers', { method: 'POST', body: JSON.stringify({ business_id: business.id, price_per_day_city: Number(price), min_days: Number(minD), max_days: Number(maxD) }) });
      toast.success(t('rt_success_offer')); onOpenChange(false); onDone && onDone();
    } catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="glass-panel border-white/10 max-w-md max-h-[90vh] overflow-y-auto" data-testid="rent-out-dialog">
        <DialogHeader><DialogTitle>{t('rt_rent_out_title')}</DialogTitle></DialogHeader>
        <RentalEstimate data={data} rentCity={price === '' ? null : Number(price)} lang={lang} />
        {data && (
          <div className="space-y-3">
            <label className="block text-xs text-text-muted space-y-1">
              <span>{t('rt_price_per_day')}</span>
              <Input type="number" value={price} onChange={(e) => setPrice(e.target.value)} className="bg-black/40 border-white/10" data-testid="rent-out-price" />
              <span className="block text-[11px]">{fill(t('rt_price_range'), { a: n(data.bounds.min_city), b: n(data.bounds.max_city) })}</span>
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label className="text-xs text-text-muted space-y-1"><span>{t('rt_min_days')}</span>
                <Input type="number" value={minD} min={data.limits.min_days} max={data.limits.max_days} onChange={(e) => setMinD(e.target.value)} className="bg-black/40 border-white/10" /></label>
              <label className="text-xs text-text-muted space-y-1"><span>{t('rt_max_days')}</span>
                <Input type="number" value={maxD} min={data.limits.min_days} max={data.limits.max_days} onChange={(e) => setMaxD(e.target.value)} className="bg-black/40 border-white/10" /></label>
            </div>
            <div className="text-[11px] text-text-muted">{fill(t('rt_commission_note'), { p: data.limits.commission_pct })}</div>
            <Button className="w-full bg-cyan-500 hover:bg-cyan-400 text-black font-bold" disabled={busy} onClick={submit} data-testid="rent-out-submit">{t('rt_publish')}</Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

/** Renter: «Арендовать». */
export function RentDialog({ offer, open, onOpenChange, onDone, lang }) {
  const { t } = useTranslation(lang);
  const [data, setData] = useState(null);
  const [days, setDays] = useState(1);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!open || !offer) return;
    setData(null); setDays(offer.min_days);
    call(`/rental/estimate/${offer.business_id}`).then(setData).catch((e) => toast.error(e.message));
  }, [open, offer]);
  if (!offer) return null;
  const dep = data ? offer.price_per_day_city * (data.limits.deposit_days || 1) : 0;
  const rent = offer.price_per_day_city * Number(days || 0);
  const submit = async () => {
    setBusy(true);
    try {
      await call(`/rental/offers/${offer.id}/rent`, { method: 'POST', body: JSON.stringify({ days: Number(days) }) });
      toast.success(t('rt_success_rent')); onOpenChange(false); onDone && onDone();
    } catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="glass-panel border-white/10 max-w-md max-h-[90vh] overflow-y-auto" data-testid="rent-dialog">
        <DialogHeader>
          <DialogTitle>{t('rt_rent_title')}</DialogTitle>
          <DialogDescription>{t('rt_owner')}: @{offer.owner_username || '—'} · {fill(t('rt_offer_active'), { p: n(offer.price_per_day_city) })}</DialogDescription>
        </DialogHeader>
        <RentalEstimate data={data} rentCity={offer.price_per_day_city} lang={lang} />
        <label className="block text-xs text-text-muted space-y-1">
          <span>{t('rt_days')} ({offer.min_days}–{offer.max_days})</span>
          <Input type="number" value={days} min={offer.min_days} max={offer.max_days} onChange={(e) => setDays(e.target.value)} className="bg-black/40 border-white/10" data-testid="rent-days" />
        </label>
        <div className="rounded-xl border border-amber-400/30 bg-amber-500/10 p-3 text-xs text-amber-100 space-y-1">
          <div className="font-bold">{fill(t('rt_total_frozen'), { total: n(rent + dep), rent: n(rent), dep: n(dep) })}</div>
          <div>{t('rt_frozen_note')}</div>
          <div className="text-amber-200/80">{t('rt_rules_note')}</div>
        </div>
        <Button className="w-full bg-cyan-500 hover:bg-cyan-400 text-black font-bold" disabled={busy || !data} onClick={submit} data-testid="rent-submit">{t('rt_rent')}</Button>
      </DialogContent>
    </Dialog>
  );
}

/** The «Аренда» tab: businesses for rent + my rentals. */
export function RentalMarket({ lang, user }) {
  const { t } = useTranslation(lang);
  const [offers, setOffers] = useState([]); const [my, setMy] = useState(null);
  const [pick, setPick] = useState(null);
  const load = useCallback(async () => {
    try {
      const [o, m] = await Promise.all([call('/rental/offers'), call('/rental/my').catch(() => null)]);
      setOffers(o.offers || []); setMy(m);
    } catch (e) { /* ignore */ }
  }, []);
  useEffect(() => { load(); }, [load]);
  const end = async (r) => {
    if (!window.confirm(t('rt_end_early_confirm'))) return;
    try { await call(`/rental/${r.id}/end`, { method: 'POST' }); toast.success(t('rt_ended')); load(); } catch (e) { toast.error(e.message); }
  };
  const others = offers.filter((o) => o.owner_id !== user?.id);
  return (
    <div className="space-y-4" data-testid="rental-market">
      {my && (my.renting.length > 0 || my.rented_out.length > 0) && (
        <div className="rounded-xl border border-white/10 bg-white/5 p-3 space-y-2">
          <div className="text-sm font-bold text-white">{t('rt_my_rentals')}</div>
          {my.renting.map((r) => (
            <div key={r.id} className="flex items-center justify-between gap-2 text-xs">
              <span className="text-cyan-200">{t('rt_renting')} · {fill(t('rt_until'), { date: date(r.ends_at) })}</span>
              <Button size="sm" variant="outline" className="h-7 text-[11px]" onClick={() => end(r)}>{t('rt_end_early')}</Button>
            </div>
          ))}
          {my.rented_out.map((r) => (
            <div key={r.id} className="text-xs text-emerald-200">{t('rt_rented_out')} · @{r.renter_username} · {fill(t('rt_until'), { date: date(r.ends_at) })}</div>
          ))}
        </div>
      )}
      {others.length === 0 && <div className="text-center text-sm text-text-muted py-8">{t('rt_no_offers')}</div>}
      <div className="grid gap-3">
        {others.map((o) => (
          <div key={o.id} className="rounded-xl border border-white/10 bg-white/5 p-3 flex items-center gap-3">
            <img src={citySpriteUrl(o.business_type, o.level) || ''} alt="" className="w-14 h-14 object-contain" />
            <div className="flex-1 min-w-0">
              <div className="text-sm font-bold text-white truncate">{o.business_type} · Lv {o.level}</div>
              <div className="text-xs text-text-muted">{t('rt_owner')}: @{o.owner_username || '—'} · {o.min_days}–{o.max_days} {t('rt_per_day_short').replace('/', '')}</div>
              <div className="text-sm font-bold text-cyan-300">{n(o.price_per_day_city)} $CITY{t('rt_per_day_short')}</div>
            </div>
            <Button size="sm" className="bg-cyan-500 hover:bg-cyan-400 text-black font-bold" onClick={() => setPick(o)} data-testid={`rent-offer-${o.id}`}>{t('rt_rent')}</Button>
          </div>
        ))}
      </div>
      <RentDialog offer={pick} open={!!pick} onOpenChange={(v) => !v && setPick(null)} onDone={load} lang={lang} />
    </div>
  );
}

/** Rental block in the business info: rented state / active offer / «Сдать в аренду». */
export function BusinessRentalControls({ business, lang, onChanged }) {
  const { t } = useTranslation(lang);
  const [offer, setOffer] = useState(null); const [open, setOpen] = useState(false);
  const load = useCallback(async () => {
    try { const m = await call('/rental/my'); setOffer((m.offers || []).find((o) => o.business_id === business.id) || null); } catch (e) { setOffer(null); }
  }, [business.id]);
  useEffect(() => { load(); }, [load]);
  if (business.rental_id) {                     // the player RENTS this business
    const end = async () => {
      if (!window.confirm(t('rt_end_early_confirm'))) return;
      try { await call(`/rental/${business.rental_id}/end`, { method: 'POST' }); toast.success(t('rt_ended')); onChanged && onChanged(); } catch (e) { toast.error(e.message); }
    };
    return (
      <div className="rounded-xl border border-cyan-400/30 bg-cyan-500/10 p-3 space-y-2" data-testid="biz-rented-block">
        <div className="text-sm text-cyan-100">{fill(t('rt_rented_until'), { date: date(business.rented_until) })}</div>
        <Button variant="outline" className="w-full" onClick={end}>{t('rt_end_early')}</Button>
      </div>
    );
  }
  if ((business.level || 0) < 1 || business.is_zero_business || business.on_sale) return null;   // level 0 / on sale: no rent-out
  if (offer) {
    const cancel = async () => {
      try { await call(`/rental/offers/${offer.id}`, { method: 'DELETE' }); load(); onChanged && onChanged(); } catch (e) { toast.error(e.message); }
    };
    return (
      <div className="rounded-xl border border-cyan-400/30 bg-cyan-500/10 p-3 space-y-2" data-testid="biz-rent-offer-block">
        <div className="text-sm text-cyan-100">{fill(t('rt_offer_active'), { p: n(offer.price_per_day_city) })}</div>
        <Button variant="outline" className="w-full" onClick={cancel}>{t('rt_cancel_offer')}</Button>
      </div>
    );
  }
  return (
    <>
      <Button className="w-full bg-cyan-500/20 text-cyan-200 hover:bg-cyan-500/30 border border-cyan-400/30" onClick={() => setOpen(true)} data-testid="biz-rent-out-btn">
        {t('rt_rent_out')}
      </Button>
      <RentOutDialog business={business} open={open} onOpenChange={setOpen} onDone={() => { load(); onChanged && onChanged(); }} lang={lang} />
    </>
  );
}
