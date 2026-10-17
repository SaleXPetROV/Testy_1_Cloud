import React, { useEffect, useState, useCallback } from 'react';
import { Loader2, ArrowUpRight, ArrowDownLeft } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { toast } from '@/components/ui/sonner';
import { useLanguage } from '@/context/LanguageContext';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api`;
const TON_TO_CITY = 1; // resource prices are shown as-is (admin NPC price)

// Compact localized strings (all 8 project languages).
const I18N = {
  title: { en: 'Quick Sell / Buy', ru: 'Быстрый сбыт / Закуп', es: 'Venta / Compra rápida', zh: '快速买卖', fr: 'Vente / Achat rapide', de: 'Schnell Verkauf / Kauf', ja: 'クイック売買', ko: '빠른 판매/구매' },
  hint: { en: 'Instant trade with the system bot at the current NPC price.', ru: 'Мгновенная сделка с системным ботом по текущему NPC-прайсу.', es: 'Operación instantánea con el bot del sistema al precio NPC actual.', zh: '按当前NPC价格与系统机器人即时交易。', fr: 'Échange instantané avec le bot système au prix NPC actuel.', de: 'Sofortiger Handel mit dem System-Bot zum aktuellen NPC-Preis.', ja: '現在のNPC価格でシステムボットと即時取引。', ko: '현재 NPC 가격으로 시스템 봇과 즉시 거래.' },
  sell: { en: 'Sell', ru: 'Продать', es: 'Vender', zh: '出售', fr: 'Vendre', de: 'Verkaufen', ja: '売却', ko: '판매' },
  buy: { en: 'Buy', ru: 'Купить', es: 'Comprar', zh: '购买', fr: 'Acheter', de: 'Kaufen', ja: '購入', ko: '구매' },
  sellAll: { en: 'Sell all', ru: 'Продать всё', es: 'Vender todo', zh: '全部出售', fr: 'Tout vendre', de: 'Alles verkaufen', ja: 'すべて売却', ko: '전체 판매' },
  balance: { en: 'Demo balance', ru: 'Демо-баланс', es: 'Saldo demo', zh: '演示余额', fr: 'Solde démo', de: 'Demo-Guthaben', ja: 'デモ残高', ko: '데모 잔액' },
  price: { en: 'price', ru: 'цена', es: 'precio', zh: '价格', fr: 'prix', de: 'Preis', ja: '価格', ko: '가격' },
  receive: { en: 'You receive', ru: 'К получению', es: 'Recibirás', zh: '您将获得', fr: 'Vous recevez', de: 'Sie erhalten', ja: '受取額', ko: '받는 금액' },
  noRes: { en: 'No resources to sell yet — collect production on your business.', ru: 'Пока нет ресурсов для продажи — соберите производство на бизнесе.', es: 'Aún no hay recursos para vender: recoge la producción de tu negocio.', zh: '暂无可出售资源——请在您的企业收取产出。', fr: "Aucune ressource à vendre — récoltez la production de votre entreprise.", de: 'Noch keine Ressourcen zum Verkauf – sammle die Produktion deines Unternehmens.', ja: '売却できる資源がありません — 事業で生産を回収してください。', ko: '판매할 자원이 없습니다 — 사업에서 생산물을 수집하세요.' },
  amount: { en: 'Amount', ru: 'Количество', es: 'Cantidad', zh: '数量', fr: 'Quantité', de: 'Menge', ja: '数量', ko: '수량' },
};

export default function DemoQuickTrade() {
  const { language: lang } = useLanguage();
  const tt = (k) => (I18N[k] && (I18N[k][lang] || I18N[k].en)) || k;

  const [loading, setLoading] = useState(true);
  const [balance, setBalance] = useState(0);
  const [resources, setResources] = useState({});
  const [prices, setPrices] = useState({});
  const [meta, setMeta] = useState({});
  const [buyRes, setBuyRes] = useState('');
  const [buyAmt, setBuyAmt] = useState('');
  const [busy, setBusy] = useState(false);

  const token = () => localStorage.getItem('token');

  const load = useCallback(async () => {
    try {
      const [st, mp] = await Promise.all([
        fetch(`${API}/demo/state`, { headers: { Authorization: `Bearer ${token()}` } }).then(r => r.json()),
        fetch(`${API}/demo/market-prices`, { headers: { Authorization: `Bearer ${token()}` } }).then(r => r.json()),
      ]);
      setBalance(Number(st?.profile?.demo_balance_city ?? 0));
      setResources(st?.profile?.demo_resources || {});
      setPrices(mp?.prices || {});
      setMeta(mp?.meta || {});
      if (!buyRes && mp?.prices) setBuyRes(Object.keys(mp.prices)[0] || '');
    } catch (e) { /* ignore */ } finally { setLoading(false); }
  }, [buyRes]);

  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const resName = (r) => (meta[r] && (meta[r][lang] || meta[r].en || meta[r].ru)) || r;
  const resIcon = (r) => (meta[r] && meta[r].icon) || '📦';
  const resTier = (r) => (meta[r] && Number(meta[r].tier)) || 1;
  // Tier-1 resources trade in whole tens; tier 2/3 may trade per single unit.
  const normAmt = (r, v) => (resTier(r) === 1 ? Math.floor(Number(v) || 0) : Math.round((Number(v) || 0) * 10) / 10);

  const doSell = async (res, amount) => {
    if (busy || !amount || amount <= 0) return;
    setBusy(true);
    try {
      const r = await fetch(`${API}/demo/trade/sell`, {
        method: 'POST', headers: { Authorization: `Bearer ${token()}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ resource: res, amount }),
      });
      const d = await r.json();
      if (d.status === 'sold') {
        toast.success(`+${Math.round(d.proceeds_city).toLocaleString()} $CITY`);
        window.dispatchEvent(new CustomEvent('demoBalanceUpdate'));
        await load();
      } else {
        toast.error(tt('noRes'));
      }
    } catch (e) { /* ignore */ } finally { setBusy(false); }
  };

  const doBuy = async () => {
    const amount = parseFloat(buyAmt);
    if (busy || !buyRes || !amount || amount <= 0) return;
    setBusy(true);
    try {
      const r = await fetch(`${API}/demo/trade/buy`, {
        method: 'POST', headers: { Authorization: `Bearer ${token()}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ resource: buyRes, amount }),
      });
      const d = await r.json();
      if (d.status === 'bought') {
        toast.success(`-${Math.round(d.cost_city).toLocaleString()} $CITY`);
        window.dispatchEvent(new CustomEvent('demoBalanceUpdate'));
        setBuyAmt('');
        await load();
      } else if (d.status === 'insufficient_balance') {
        toast.error(`${tt('balance')}: ${Math.round(balance).toLocaleString()} $CITY`);
      }
    } catch (e) { /* ignore */ } finally { setBusy(false); }
  };

  if (loading) {
    return <div className="flex items-center justify-center py-20"><Loader2 className="w-7 h-7 animate-spin text-cyber-cyan" /></div>;
  }

  const owned = Object.entries(resources).map(([k, v]) => [k, normAmt(k, v)]).filter(([, v]) => v > 0);
  const buyPrice = prices[buyRes] || 0;
  const buyCost = (parseFloat(buyAmt) || 0) * buyPrice * TON_TO_CITY;

  return (
    <div data-testid="demo-quick-trade" className="space-y-5">
      <div className="rounded-2xl border border-cyber-cyan/25 bg-cyber-cyan/5 p-4">
        <div className="text-sm text-cyber-cyan/80">{tt('hint')}</div>
        <div className="mt-2 text-2xl font-extrabold text-white">
          {Math.round(balance).toLocaleString()} <span className="text-yellow-400 text-base">$CITY</span>
        </div>
        <div className="text-xs text-text-muted">{tt('balance')}</div>
      </div>

      {/* Quick SELL */}
      <div className="rounded-2xl border border-white/10 bg-black/30 p-4">
        <div className="flex items-center gap-2 mb-3 text-emerald-400 font-bold uppercase tracking-wide text-sm">
          <ArrowUpRight className="w-4 h-4" /> {tt('sell')}
        </div>
        {owned.length === 0 ? (
          <div className="text-sm text-text-muted" data-testid="demo-no-resources">{tt('noRes')}</div>
        ) : (
          <div className="space-y-2">
            {owned.map(([res, amt]) => {
              const p = prices[res] || 0;
              const receive = Number(amt) * p * TON_TO_CITY;
              return (
                <div key={res} className="flex items-center justify-between gap-3 rounded-xl bg-white/5 px-3 py-2" data-testid={`demo-sell-row-${res}`}>
                  <div className="min-w-0">
                    <div className="text-white font-semibold">{resIcon(res)} {resName(res)} <span className="text-text-muted text-sm">× {Number(amt)}</span></div>
                    <div className="text-xs text-text-muted">{tt('receive')}: {Math.round(receive).toLocaleString()} $CITY</div>
                  </div>
                  <Button size="sm" disabled={busy} onClick={() => doSell(res, Number(amt))} className="bg-emerald-600 hover:bg-emerald-500 text-white" data-testid={`demo-sell-btn-${res}`}>
                    {tt('sellAll')}
                  </Button>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Quick BUY */}
      <div className="rounded-2xl border border-white/10 bg-black/30 p-4">
        <div className="flex items-center gap-2 mb-3 text-cyan-400 font-bold uppercase tracking-wide text-sm">
          <ArrowDownLeft className="w-4 h-4" /> {tt('buy')}
        </div>
        <div className="flex flex-col sm:flex-row gap-2">
          <Select value={buyRes} onValueChange={setBuyRes}>
            <SelectTrigger
              data-testid="demo-buy-resource"
              className="flex-1 bg-white/5 border-white/10 text-white text-sm rounded-xl focus:ring-cyber-cyan/40 focus:border-cyber-cyan/40"
            >
              <SelectValue>
                {buyRes ? (
                  <span className="flex items-center gap-2">
                    <span className="text-lg leading-none">{resIcon(buyRes)}</span>
                    <span className="text-white">{resName(buyRes)}</span>
                    <span className="text-text-muted">— {(prices[buyRes] * TON_TO_CITY).toLocaleString()} $CITY</span>
                  </span>
                ) : null}
              </SelectValue>
            </SelectTrigger>
            <SelectContent
              className="bg-[#0b1220] border border-white/10 text-white max-h-72"
              data-testid="demo-buy-resource-menu"
            >
              {Object.keys(prices).map((r) => (
                <SelectItem
                  key={r}
                  value={r}
                  className="focus:bg-cyber-cyan/10 focus:text-white data-[state=checked]:text-cyber-cyan"
                  data-testid={`demo-buy-option-${r}`}
                >
                  <span className="flex items-center gap-2">
                    <span className="text-lg leading-none">{resIcon(r)}</span>
                    <span>{resName(r)}</span>
                    <span className="text-text-muted">— {(prices[r] * TON_TO_CITY).toLocaleString()} $CITY</span>
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Input
            type="number" min="0" placeholder={tt('amount')} value={buyAmt}
            onChange={(e) => setBuyAmt(e.target.value)}
            className="bg-white/5 border-white/10 text-white sm:w-32" data-testid="demo-buy-amount"
          />
          <Button disabled={busy} onClick={doBuy} className="bg-cyber-cyan text-black hover:bg-cyber-cyan/80 font-bold" data-testid="demo-buy-btn">
            {tt('buy')}
          </Button>
        </div>
        {buyCost > 0 && (
          <div className="text-xs text-text-muted mt-2" data-testid="demo-buy-cost">≈ {Math.round(buyCost).toLocaleString()} $CITY</div>
        )}
      </div>
    </div>
  );
}
