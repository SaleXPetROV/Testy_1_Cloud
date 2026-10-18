/**
 * Resource window (Resources page → tap a resource): what it is (tier, which building makes it, a picture),
 * the price the state (City Market) pays for 1 unit, the bonus of a tier-3 resource with «Активировать бонус»
 * (same rules as «Усилители»: 1 unit, not more than 2 effects at once, needs a working business), and
 * «Выставить на продажу» → the usual sell window of the Trading page (same flow, /trading?tab=my&sell=<id>).
 */
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { X } from 'lucide-react';
import { fill, fmtLeft } from '@/lib/translationsMore';
import { toast } from 'sonner';
import { getResource } from '@/lib/resourceConfig';
import { tBusiness } from '@/lib/translationsExtra';
import { buffTexts } from '@/lib/buffText';

const API = `${process.env.REACT_APP_BACKEND_URL || ''}/api`;
// resource -> the building that produces it (the sprites of the city map)
const PRODUCER = {
  energy: 'helios', cu: 'nano_dc', quartz: 'quartz_mine', traffic: 'signal_tower', cooling: 'hydro_cooling', biomass: 'bio_farm',
  scrap: 'scrap_yard', chips: 'chips_factory', nft: 'nft_studio', neurocode: 'ai_lab', logistics: 'logistics_hub',
  repair_kits: 'repair_shop', vr_experience: 'vr_club', neuro_core: 'validator', gold_bill: 'gram_bank', license_token: 'dex',
  luck_chip: 'casino', war_protocol: 'arena', bio_module: 'incubator', gateway_code: 'bridge',
};

let pricesCache = null;

export default function ResourceInfoModal({ id, amount, lang, t, onClose, onChanged }) {
  const navigate = useNavigate();
  const [price, setPrice] = useState(pricesCache ? pricesCache[id] : undefined);
  const [buff, setBuff] = useState(null);
  const [active, setActive] = useState(null);          // this buff, if it runs now
  const [slotsFull, setSlotsFull] = useState(false);   // 2 effects already run (boosters + tier-3 buffs)
  const [busy, setBusy] = useState(false);
  const tok = () => localStorage.getItem('token') || localStorage.getItem('ton_city_token');
  const loadBuff = async () => {
    // fresh every time: quantity and active buffs change (the old code asked a non-existent /resource-buffs)
    const [b, inv] = await Promise.all([
      fetch(`${API}/resource-buffs/available`, { headers: { Authorization: `Bearer ${tok()}` } }).then((x) => x.json()),
      fetch(`${API}/boosters`, { headers: { Authorization: `Bearer ${tok()}` } }).then((x) => x.json()).catch(() => ({ active: [] })),
    ]);
    setBuff((b.buffs || []).find((x) => x.resource_id === id) || null);
    setActive((b.active || []).find((x) => x.resource_id === id) || null);
    setSlotsFull((inv.active || []).length >= 2);
  };
  const activate = async () => {
    setBusy(true);
    try {
      const r = await fetch(`${API}/resource-buffs/activate/${encodeURIComponent(id)}`, { method: 'POST', headers: { Authorization: `Bearer ${tok()}` } });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) {
        const det = j?.detail;
        toast.error(det === 'tutorial_buff_needs_business' ? t('boostNeedsBusiness') : det === 'boosters_limit' ? t('boostMaxTwo') : (r.status === 409 ? t('boostMaxTwo') : (typeof det === 'string' ? det : 'Error')));
      } else {
        toast.success(t('boostActivated'));
        onChanged && onChanged();
      }
      await loadBuff();
    } catch (_) { toast.error('Error'); }
    finally { setBusy(false); }
  };
  const r = getResource(id, lang);
  const tier = r?.tier || 1;
  const producer = PRODUCER[id];

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        if (!pricesCache) pricesCache = (await fetch(`${API}/city-market/prices`).then((x) => x.json())).prices || {};
        if (alive) setPrice(pricesCache[id] || null);
      } catch (_) { if (alive) setPrice(null); }
      if (tier === 3 && alive) {
        try { await loadBuff(); } catch (_) { /* no buff info */ }
      }
    })();
    return () => { alive = false; };
  }, [id, tier]); // eslint-disable-line react-hooks/exhaustive-deps

  const bt = buff ? buffTexts(buff, t) : null;
  return (
    <div className="fixed inset-0 z-[90] bg-black/70 flex items-end sm:items-center justify-center p-4" onClick={onClose} data-testid="resource-info-modal">
      <div className={`w-full max-w-sm rounded-2xl p-[1.5px] mb-[var(--bottom-nav-h,0px)] sm:mb-0 ${tier === 3 ? 'res-legendary-frame' : 'bg-white/10'}`} onClick={(e) => e.stopPropagation()}>
        <div className="rounded-2xl bg-[#0b1020] p-4 space-y-3 max-h-[calc(100dvh-var(--bottom-nav-h,90px)-40px)] overflow-y-auto">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-center gap-3 min-w-0">
              <div className={`w-14 h-14 rounded-xl flex items-center justify-center text-3xl shrink-0 ${tier === 3 ? 'res-legendary' : 'bg-white/5 border border-white/10'}`}>{r?.icon || '📦'}</div>
              <div className="min-w-0">
                <div className="text-white font-bold truncate">{r?.name || id}</div>
                <div className={`text-[11px] ${tier === 3 ? 'text-amber-200' : 'text-text-muted'}`}>
                  {tier === 3 ? `✦ ${t('res_info_legend')}` : fill(t('res_info_tier'), { n: tier })}
                </div>
                {amount != null && <div className="text-[11px] text-white/70">{fill(t('res_info_have'), { n: Math.floor(amount).toLocaleString('ru-RU') })}</div>}
              </div>
            </div>
            <button type="button" onClick={onClose} className="text-white/60" aria-label={t('page_close')}><X className="w-5 h-5" /></button>
          </div>

          {producer && (
            <div className="flex items-center gap-3 rounded-xl bg-white/5 border border-white/10 p-2">
              <img src={`/sprites/city/${producer}/stage2.webp`} alt="" className="w-16 h-16 object-contain shrink-0" />
              <div className="text-xs text-white/80">{fill(t('res_info_made_by'), { name: tBusiness(producer, lang) })}</div>
            </div>
          )}

          {tier === 3 && bt && (
            <div className="rounded-xl res-legendary p-3 space-y-0.5" data-testid="resource-info-buff">
              <div className="text-[11px] uppercase tracking-wide text-amber-100/80">{t('res_info_buff')}</div>
              <div className="text-sm font-bold text-white">{buff.buff_icon} {bt.name}</div>
              {bt.effect && <div className="text-xs text-white/90">{bt.effect} · {fill(t('res_info_days'), { n: buff.duration_days })}</div>}
              <div className="pt-2">
                {active ? (
                  <div className="text-xs font-semibold text-emerald-300" data-testid="resource-info-buff-on">✓ {fill(t('res_info_buff_on'), { t: fmtLeft(active.expires_at, t) })}</div>
                ) : buff.quantity < 1 ? (
                  <div className="text-[11px] text-white/60" data-testid="resource-info-buff-none">{t('res_info_buff_none')}</div>
                ) : (
                  <>
                    <button type="button" onClick={activate} disabled={busy || slotsFull} data-testid="resource-info-buff-activate"
                      className="w-full h-10 rounded-xl bg-gradient-to-r from-amber-400 to-fuchsia-500 text-black font-bold disabled:opacity-50">
                      {buff.buff_icon} {t('res_info_buff_act')}
                    </button>
                    <div className="mt-1 text-[10px] text-white/60 text-center">{slotsFull ? t('boostMaxTwo') : t('res_info_buff_cost')}</div>
                  </>
                )}
              </div>
            </div>
          )}

          <div className="rounded-xl bg-emerald-500/10 border border-emerald-400/25 p-3" data-testid="resource-info-state-price">
            {price === undefined ? <div className="text-xs text-text-muted">…</div>
              : price && price.buys ? (
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-xs text-white/80">{t('res_info_state')}</span>
                  <span className="text-emerald-300 font-black">{Number(price.buy_city).toLocaleString('ru-RU', { maximumFractionDigits: 2 })} $CITY <span className="text-[10px] font-normal text-white/60">{t('res_info_per_unit')}</span></span>
                </div>
              ) : <div className="text-xs text-white/70">{t('res_info_state_no')}</div>}
          </div>

          <button type="button" onClick={() => navigate(`/trading?tab=my&sell=${encodeURIComponent(id)}`)} disabled={!amount}
            className="w-full h-11 rounded-xl bg-gradient-to-r from-green-500 to-emerald-600 text-white font-bold disabled:opacity-40" data-testid="resource-info-sell">
            {t('res_info_sell')}
          </button>
        </div>
      </div>
    </div>
  );
}
