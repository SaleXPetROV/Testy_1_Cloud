/**
 * MarketMakerPanel — admin analytics + controls for the City Market
 * (backend/market_maker.py, /api/admin/market-maker/*).
 *
 * Top: alerts, KPIs, today's budget. Then the liquidity effect (the reason the
 * City Market exists), daily volume, per-resource table, top sellers (abuse
 * watch), recent trades, and the settings form with a kill switch.
 */
import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { toast } from 'sonner';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { Input } from '@/components/ui/input';
import { AlertTriangle, Building2, Clock, Play, RefreshCw, ShieldAlert, TrendingUp } from 'lucide-react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api/admin/market-maker`;

const ton = (v) => (v === null || v === undefined ? '—' : `${Number(v).toFixed(4)} TON`);
const city = (v) => (v === null || v === undefined ? '—' : `${(Number(v) * 1000).toLocaleString('ru-RU', { maximumFractionDigits: 2 })} $CITY`);
const mins = (v) => (v === null || v === undefined ? '—' : v >= 120 ? `${(v / 60).toFixed(1)} ч` : `${Math.round(v)} мин`);

function Kpi({ label, value, sub, tone = 'text-white' }) {
  return (
    <div className="rounded-xl bg-white/5 border border-white/10 p-3">
      <div className="text-[11px] uppercase tracking-wide text-text-muted">{label}</div>
      <div className={`text-xl font-bold mt-1 ${tone}`}>{value}</div>
      {sub && <div className="text-[11px] text-text-muted mt-0.5">{sub}</div>}
    </div>
  );
}

function Gauge({ label, used, cap }) {
  const pct = cap > 0 ? Math.min(100, Math.round((used / cap) * 100)) : 0;
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs"><span className="text-white">{label}</span>
        <span className="text-text-muted">{ton(used)} / {cap > 0 ? ton(cap) : 'не задан'}</span></div>
      <div className="h-2 rounded-full bg-white/10 overflow-hidden">
        <div className={`h-full ${pct >= 100 ? 'bg-red-500' : pct >= 80 ? 'bg-yellow-400' : 'bg-emerald-400'}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function DailyBars({ series }) {
  const max = Math.max(1e-9, ...series.map((d) => Math.max(d.bought_ton, d.sold_ton)));
  return (
    <div className="space-y-2">
      <div className="flex items-stretch gap-1.5 h-32" data-testid="mm-daily-bars">
        {series.map((d) => (
          <div key={d.date} className="flex-1 h-full flex flex-col items-center justify-end gap-1" title={`${d.date}: куплено ${ton(d.bought_ton)}, продано ${ton(d.sold_ton)}`}>
            <div className="w-full flex items-end gap-0.5 flex-1 min-h-0">
              <div className="flex-1 rounded-t bg-cyan-400/70" style={{ height: `${(d.bought_ton / max) * 100}%`, minHeight: d.bought_ton ? 3 : 0 }} />
              <div className="flex-1 rounded-t bg-purple-400/70" style={{ height: `${(d.sold_ton / max) * 100}%`, minHeight: d.sold_ton ? 3 : 0 }} />
            </div>
            <div className="text-[9px] text-text-muted">{d.date.slice(5)}</div>
          </div>
        ))}
      </div>
      <div className="flex gap-4 text-[11px] text-text-muted">
        <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-sm bg-cyan-400/70" />куплено у игроков</span>
        <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-sm bg-purple-400/70" />продано игрокам</span>
      </div>
    </div>
  );
}

const FIELDS = [
  { key: 'daily_budget_ton', label: 'Дневной бюджет выкупа за реальные деньги (TON)', step: '0.1' },
  { key: 'bonus_daily_cap_city', label: 'Лимит бонусных выплат всем новичкам в день ($CITY)', step: '100' },
  { key: 'per_newbie_daily_cap_city', label: 'Лимит бонусных выплат одному новичку в день ($CITY)', step: '10' },
  { key: 'buy_discount_pct', label: 'Выкуп: дешевле базовой цены на (%)', step: '1' },
  { key: 'sell_markup_pct', label: 'Продажа: дороже базовой цены на (%)', step: '1' },
  { key: 'min_lot_age_min', label: 'Лоты игроков 1+: ждать покупателя (мин)', step: '1' },
  { key: 'newbie_delay_min', label: 'Первая продажа новичка: выкуп через (мин)', step: '1' },
  { key: 'newbie_max_units', label: 'Первая продажа новичка: до (ед.)', step: '1' },
  { key: 'auto_price_delay_min', label: 'Следующие лоты новичка: выкуп через (мин)', step: '1' },
  { key: 'player_daily_cap_ton', label: 'Лимит на игрока 1+ в день (TON)', step: '0.1' },
  { key: 'player_daily_cap_units', label: 'Лимит на игрока в день (ед.)', step: '10' },
  { key: 'inventory_cap_units', label: 'Макс. запас города на ресурс (ед.)', step: '100' },
  { key: 'max_player_share_pct', label: 'Макс. доля одного игрока в выкупе дня (%)', step: '1' },
];

export default function MarketMakerPanel({ token }) {
  const [days, setDays] = useState(7);
  const [data, setData] = useState(null);
  const [form, setForm] = useState(null);
  const [trades, setTrades] = useState([]);
  const [catalog, setCatalog] = useState([]);
  const [busy, setBusy] = useState(false);
  const headers = { headers: { Authorization: `Bearer ${token}` } };

  const load = useCallback(async () => {
    try {
      const [a, tr, cat] = await Promise.all([
        axios.get(`${API}/analytics?days=${days}`, headers),
        axios.get(`${API}/trades?limit=30`, headers),
        axios.get(`${API}/catalog`, headers),
      ]);
      setData(a.data);
      setForm((f) => f || a.data.config);
      setTrades(tr.data.trades || []);
      setCatalog(cat.data.resources || []);
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Не удалось загрузить данные Городского рынка');
    }
  }, [days, token]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { load(); }, [load]);

  const save = async (patch) => {
    setBusy(true);
    try {
      const r = await axios.put(`${API}/config`, patch, headers);
      setForm(r.data);
      toast.success('Настройки Городского рынка сохранены');
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Ошибка сохранения');
    } finally {
      setBusy(false);
    }
  };

  const runNow = async () => {
    setBusy(true);
    try {
      const r = await axios.post(`${API}/run`, {}, headers);
      const b = r.data.buy || {};
      toast.success(`Цикл выполнен: выкуплено лотов ${b.bought || 0}, из них новичкам ${b.newbie || 0}`);
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Ошибка запуска');
    } finally {
      setBusy(false);
    }
  };

  if (!data || !form) return <div className="text-sm text-text-muted">Загрузка…</div>;
  const t = data.totals;
  const lc = data.liquidity.current;
  const lp = data.liquidity.previous;
  const faster = lc.median_minutes != null && lp.median_minutes != null ? lp.median_minutes - lc.median_minutes : null;

  return (
    <div className="space-y-4" data-testid="market-maker-panel">
      {/* header + kill switch */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <Building2 className="w-5 h-5 text-cyber-cyan" />
          <span className="font-bold text-white">Городской рынок</span>
        </div>
        {[['newbie_buy_enabled', 'Выкуп у новичков', 'mm-newbie-switch'],
          ['real_buy_enabled', 'Выкуп за реальные деньги', 'mm-real-switch'],
          ['sell_enabled', 'Продажа из запаса', 'mm-sell-switch']].map(([key, label, tid]) => (
          <label key={key} className="flex items-center gap-2 text-sm">
            <Switch checked={!!form[key]} disabled={busy} onCheckedChange={(v) => save({ [key]: v })} data-testid={tid} />
            <span className={form[key] ? 'text-emerald-400' : 'text-text-muted'}>{label}</span>
          </label>
        ))}
        <div className="flex gap-1 ml-auto">
          {[1, 7, 30].map((d) => (
            <Button key={d} size="sm" variant={days === d ? 'default' : 'outline'} className="h-8 text-xs" onClick={() => setDays(d)}>{d} дн.</Button>
          ))}
          <Button size="sm" variant="outline" className="h-8 text-xs" onClick={load} disabled={busy}><RefreshCw className="w-3.5 h-3.5" /></Button>
          <Button size="sm" className="h-8 text-xs" onClick={runNow} disabled={busy || (!form.newbie_buy_enabled && !form.real_buy_enabled && !form.sell_enabled)} data-testid="mm-run-now"><Play className="w-3.5 h-3.5 mr-1" />Запустить цикл</Button>
        </div>
      </div>

      {data.alerts.length > 0 && (
        <div className="space-y-1.5" data-testid="mm-alerts">
          {data.alerts.map((a, i) => (
            <div key={i} className={`flex items-center gap-2 rounded-lg px-3 py-2 text-xs border ${a.level === 'warning' ? 'border-yellow-400/40 bg-yellow-500/10 text-yellow-200' : 'border-white/10 bg-white/5 text-text-muted'}`}>
              <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />{a.text}
            </div>
          ))}
        </div>
      )}

      {/* KPIs */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
        <Kpi label="Выкуплено городом" value={ton(t.bought_ton)} sub={`${t.bought_units} ед. · реальн. ${ton(t.bought_real_ton)} · бонус ${ton(t.bought_bonus_ton)}`} />
        <Kpi label="Продано городом" value={ton(t.sold_ton)} sub={`${t.sold_units} ед.`} />
        <Kpi label="Результат с учётом запаса" value={ton(t.result_incl_stock_ton)}
          tone={t.result_incl_stock_ton >= 0 ? 'text-emerald-400' : 'text-red-400'}
          sub={`деньгами ${ton(t.net_cash_ton)} + запас ${ton(t.stock_value_ton)}`} />
        <Kpi label="Помог игрокам" value={`${t.unique_sellers} / ${t.unique_buyers}`}
          sub={`продавцов / покупателей · первая продажа: ${t.newbie_sales} · лоты новичков: ${t.auto_price_sales} · дешёвые лоты: ${t.aged_lot_sales}`} />
      </div>

      {/* today's budget */}
      <Card className="glass-panel border-white/10">
        <CardHeader className="pb-2"><CardTitle className="text-sm">Сегодня</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="grid grid-cols-2 gap-2" data-testid="mm-today-totals">
            <Kpi label="Выкуплено городом сегодня" value={ton(data.today.bought_ton)} sub={`${data.today.bought_units} ед.`} />
            <Kpi label="Продано городом сегодня" value={ton(data.today.sold_ton)} sub={`${data.today.sold_units} ед.`} />
          </div>
          <Gauge label="Реальные выплаты" used={data.today.real_spent_ton} cap={data.today.budget_ton} />
          <Gauge label="Бонусные выплаты" used={data.today.bonus_spent_ton} cap={data.today.bonus_cap_ton} />
          {data.today.skipped_share > 0 && <div className="text-[11px] text-yellow-300">Пропущено из-за лимита доли одного игрока: {data.today.skipped_share}</div>}
        </CardContent>
      </Card>

      {/* liquidity — the reason the City Market exists */}
      <Card className="glass-panel border-white/10">
        <CardHeader className="pb-2"><CardTitle className="text-sm flex items-center gap-2"><Clock className="w-4 h-4 text-yellow-400" />Ликвидность: время продажи лота игрока</CardTitle></CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-2" data-testid="mm-liquidity">
            <Kpi label={`Медиана, последние ${days} дн.`} value={mins(lc.median_minutes)}
              sub={faster != null ? (faster > 0 ? `быстрее на ${mins(faster)}` : faster < 0 ? `медленнее на ${mins(-faster)}` : 'без изменений') : 'нет данных для сравнения'}
              tone={faster > 0 ? 'text-emerald-400' : 'text-white'} />
            <Kpi label={`Медиана, предыдущие ${days} дн.`} value={mins(lp.median_minutes)} sub={`лотов продано: ${lp.lots_sold}`} />
            <Kpi label="Продано лотов" value={lc.lots_sold} sub={`игрокам ${lc.sold_to_players} · рынку ${lc.sold_to_city}`} />
            <Kpi label="Доля Городского рынка" value={lc.city_share_pct == null ? '—' : `${lc.city_share_pct}%`} sub="чем ниже, тем живее рынок игроков" />
          </div>
        </CardContent>
      </Card>

      <Card className="glass-panel border-white/10">
        <CardHeader className="pb-2"><CardTitle className="text-sm flex items-center gap-2"><TrendingUp className="w-4 h-4 text-cyan-400" />Объём по дням</CardTitle></CardHeader>
        <CardContent><DailyBars series={data.series} /></CardContent>
      </Card>

      {/* per resource */}
      <Card className="glass-panel border-white/10">
        <CardHeader className="pb-2"><CardTitle className="text-sm">По ресурсам</CardTitle></CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full text-xs" data-testid="mm-resources">
            <thead><tr className="text-text-muted text-left">
              <th className="py-1 pr-3">Ресурс</th><th className="py-1 pr-3">Куплено</th><th className="py-1 pr-3">Ср. цена покупки</th>
              <th className="py-1 pr-3">Продано</th><th className="py-1 pr-3">Ср. цена продажи</th><th className="py-1 pr-3">Запас</th><th className="py-1 pr-3">Хватит на</th>
            </tr></thead>
            <tbody>
              {data.resources.map((r) => (
                <tr key={r.resource} className="border-t border-white/5">
                  <td className="py-1 pr-3 text-white">{r.name}</td>
                  <td className="py-1 pr-3">{r.bought_units} ед.</td>
                  <td className="py-1 pr-3">{city(r.avg_buy_price_ton)}</td>
                  <td className="py-1 pr-3">{r.sold_units} ед.</td>
                  <td className="py-1 pr-3">{city(r.avg_sell_price_ton)}</td>
                  <td className="py-1 pr-3">{r.stock_units} ед. · {ton(r.stock_value_ton)}</td>
                  <td className="py-1 pr-3">{r.days_of_cover == null ? '—' : `${r.days_of_cover} дн.`}</td>
                </tr>
              ))}
              {!data.resources.length && <tr><td colSpan={7} className="py-2 text-text-muted">Сделок пока нет.</td></tr>}
            </tbody>
          </table>
        </CardContent>
      </Card>

      {/* abuse watch */}
      <Card className="glass-panel border-white/10">
        <CardHeader className="pb-2"><CardTitle className="text-sm flex items-center gap-2"><ShieldAlert className="w-4 h-4 text-red-400" />Кто больше всех продаёт рынку</CardTitle></CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full text-xs" data-testid="mm-top-sellers">
            <thead><tr className="text-text-muted text-left">
              <th className="py-1 pr-3">Игрок</th><th className="py-1 pr-3">Аккаунтов на устройстве</th><th className="py-1 pr-3">Сумма</th><th className="py-1 pr-3">Ед.</th><th className="py-1 pr-3">Доля</th>
            </tr></thead>
            <tbody>
              {data.top_sellers.map((s) => (
                <tr key={s.group} className={`border-t border-white/5 ${s.flag ? 'text-yellow-200' : ''}`}>
                  <td className="py-1 pr-3">{s.flag && '⚠ '}{s.username}</td>
                  <td className="py-1 pr-3">{s.accounts}</td>
                  <td className="py-1 pr-3">{ton(s.ton)}</td>
                  <td className="py-1 pr-3">{s.units}</td>
                  <td className="py-1 pr-3">{s.share_pct}%</td>
                </tr>
              ))}
              {!data.top_sellers.length && <tr><td colSpan={5} className="py-2 text-text-muted">Нет продаж рынку за период.</td></tr>}
            </tbody>
          </table>
        </CardContent>
      </Card>

      {/* recent trades */}
      <Card className="glass-panel border-white/10">
        <CardHeader className="pb-2"><CardTitle className="text-sm">Последние сделки</CardTitle></CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full text-xs" data-testid="mm-trades">
            <thead><tr className="text-text-muted text-left">
              <th className="py-1 pr-3">Время</th><th className="py-1 pr-3">Сторона</th><th className="py-1 pr-3">Ресурс</th><th className="py-1 pr-3">Ед.</th><th className="py-1 pr-3">Сумма</th><th className="py-1 pr-3">Выплата</th><th className="py-1 pr-3">Причина</th>
            </tr></thead>
            <tbody>
              {trades.map((x) => (
                <tr key={x.id} className="border-t border-white/5">
                  <td className="py-1 pr-3">{new Date(x.ts).toLocaleString('ru-RU')}</td>
                  <td className="py-1 pr-3">{x.side === 'buy' ? 'купил у игрока' : 'продал игроку'}</td>
                  <td className="py-1 pr-3">{x.resource}</td>
                  <td className="py-1 pr-3">{x.units}</td>
                  <td className="py-1 pr-3">{ton(x.total_ton)}</td>
                  <td className="py-1 pr-3">{x.side === 'buy' ? (x.payout === 'real' ? 'реальный' : 'бонусный') : '—'}</td>
                  <td className="py-1 pr-3">{{ newbie: 'первая продажа новичка', auto_price: 'лот новичка (системная цена)', aged_lot: 'дешёвый лот без покупателя' }[x.reason] || '—'}</td>
                </tr>
              ))}
              {!trades.length && <tr><td colSpan={7} className="py-2 text-text-muted">Сделок пока нет.</td></tr>}
            </tbody>
          </table>
        </CardContent>
      </Card>

      {/* settings */}
      <Card className="glass-panel border-white/10">
        <CardHeader className="pb-2"><CardTitle className="text-sm">Настройки</CardTitle></CardHeader>
        <CardContent className="space-y-3" data-testid="mm-settings">
          <div className="grid sm:grid-cols-2 gap-3">
            {FIELDS.map((f) => (
              <label key={f.key} className="text-xs space-y-1">
                <span className="text-text-muted">{f.label}</span>
                <Input type="number" min="0" step={f.step} value={form[f.key] ?? ''} className="bg-black/40 border-white/10 h-9"
                  onChange={(e) => setForm((s) => ({ ...s, [f.key]: e.target.value }))} data-testid={`mm-${f.key}`} />
              </label>
            ))}
          </div>
          <div className="flex flex-wrap gap-4 text-xs">
            <span className="text-text-muted">Выключатели выкупа и продажи — вверху вкладки.</span>
          </div>
          <div className="text-xs space-y-1" data-testid="mm-resource-table">
            <div className="flex items-center justify-between">
              <span className="text-text-muted">Какие ресурсы выкупает и продаёт рынок</span>
              <span className="flex gap-1">
                {[['Выкупать все тир 1', 'buy_resources', 1], ['Продавать все тир 1', 'sell_resources', 1]].map(([lbl, key, tier]) => (
                  <button key={key} type="button" className="px-2 py-0.5 rounded border border-white/10 bg-white/5 text-[11px]"
                    onClick={() => setForm((s) => ({ ...s, [key]: Array.from(new Set([...(s[key] || []), ...catalog.filter((r) => r.tier === tier).map((r) => r.id)])) }))}>{lbl}</button>
                ))}
              </span>
            </div>
            <div className="overflow-x-auto rounded-lg border border-white/10">
              <table className="w-full text-xs">
                <thead><tr className="text-text-muted text-left bg-white/5">
                  <th className="py-1.5 px-2">Ресурс</th><th className="py-1.5 px-2">Тир</th>
                  <th className="py-1.5 px-2" title="Статичная цена из таблицы игры — от неё считаются проценты">Базовая цена</th>
                  <th className="py-1.5 px-2">Цена выкупа ($CITY)</th><th className="py-1.5 px-2">Цена продажи ($CITY)</th>
                  <th className="py-1.5 px-2 text-center">Выкупать</th><th className="py-1.5 px-2 text-center">Продавать</th>
                </tr></thead>
                <tbody>
                  {catalog.map((r) => {
                    const toggle = (key) => setForm((s) => {
                      const list = s[key] || [];
                      return { ...s, [key]: list.includes(r.id) ? list.filter((x) => x !== r.id) : [...list, r.id] };
                    });
                    return (
                      <tr key={r.id} className="border-t border-white/5" data-testid={`mm-res-${r.id}`}>
                        <td className="py-1 px-2 text-white">{r.icon} {r.name}</td>
                        <td className="py-1 px-2">{r.tier}</td>
                        <td className="py-1 px-2 text-white/80">{r.base_price_city}</td>
                        {['buy_city', 'sell_city'].map((side) => {
                          const auto = side === 'buy_city'
                            ? +(r.base_price_city * (100 - Number(form.buy_discount_pct || 0)) / 100).toFixed(4)
                            : +(r.base_price_city * (100 + Number(form.sell_markup_pct || 0)) / 100).toFixed(4);
                          const manual = ((form.price_overrides || {})[r.id] || {})[side];
                          return (
                            <td key={side} className="py-1 px-2">
                              <Input type="number" min="0" step="0.01" placeholder={`${auto} авто`}
                                value={manual ?? ''} className={`h-7 w-28 bg-black/40 border-white/10 text-xs ${manual ? 'text-yellow-300' : ''}`}
                                data-testid={`mm-${side}-${r.id}`}
                                onChange={(e) => setForm((s) => {
                                  const ov = { ...(s.price_overrides || {}) };
                                  const row = { ...(ov[r.id] || {}) };
                                  if (e.target.value === '') delete row[side]; else row[side] = e.target.value;
                                  if (Object.keys(row).length) ov[r.id] = row; else delete ov[r.id];
                                  return { ...s, price_overrides: ov };
                                })} />
                            </td>
                          );
                        })}
                        <td className="py-1 px-2 text-center"><Switch checked={(form.buy_resources || []).includes(r.id)} onCheckedChange={() => toggle('buy_resources')} data-testid={`mm-buy-${r.id}`} /></td>
                        <td className="py-1 px-2 text-center"><Switch checked={(form.sell_resources || []).includes(r.id)} onCheckedChange={() => toggle('sell_resources')} data-testid={`mm-sell-${r.id}`} /></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
          <div className="rounded-lg border border-white/10 bg-white/5 p-3 text-[11px] text-text-muted space-y-1">
            <div className="text-white font-semibold">Как считаются цены и кого выкупает рынок</div>
            <div>• Цены считаются от <b className="text-white">статичной базовой цены</b> ресурса: выкуп — дешевле на заданный %, продажа — дороже на заданный %. Чтобы задать свою цену для ресурса, впишите её в таблицу; пустое поле — автоматическая цена. Цена выкупа всегда должна быть ниже цены продажи.</div>
            <div>• Всё, что город выкупил, <b className="text-white">автоматически выставляется на продажу</b> целиком по цене продажи.</div>
            <div>• <b className="text-white">Новичок (бизнес уровня 0)</b> — цену не выбирает, лоты идут по системной цене. Первая продажа выкупается быстро, следующие лоты — через заданное время, по его цене. Выплата на бонусный баланс в пределах лимитов (выключатель «Выкуп у новичков»).</div>
            <div>• <b className="text-white">Игрок с бизнесом уровня 1+</b> — пишет цену сам. Рынок выкупает его лот, только если цена не выше цены выкупа города. Выплата на реальный баланс из дневного бюджета (выключатель «Выкуп за реальные деньги»).</div>
          </div>
          <div className="text-[11px] text-text-muted">
            Выплата продавцу: бизнес уровня 1+ — на реальный баланс, бизнес уровня 0 — на бонусный.
          </div>
          <Button size="sm" disabled={busy} data-testid="mm-save"
            onClick={() => {
              const patch = {};
              FIELDS.forEach((f) => { patch[f.key] = Number(form[f.key]); });
              patch.buy_resources = form.buy_resources || [];
              patch.price_overrides = form.price_overrides || {};
              patch.sell_resources = form.sell_resources || [];
              save(patch);
            }}>Сохранить настройки</Button>
        </CardContent>
      </Card>
    </div>
  );
}
