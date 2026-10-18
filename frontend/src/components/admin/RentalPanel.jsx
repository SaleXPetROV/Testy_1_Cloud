/** Admin «Аренда»: settings, totals, charts (rent paid / commission per day), transactions. */
import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { toast } from 'sonner';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

const API = `${process.env.REACT_APP_BACKEND_URL || ''}/api`;
const n = (v) => Math.round(Number(v || 0)).toLocaleString('ru-RU');
const TX = { rental_freeze: 'Заморозка у арендатора', rental_charge: 'Списание за сутки', rental_payout: 'Выплата владельцу',
  rental_commission: 'Комиссия в казну', rental_unfreeze: 'Разморозка арендатору', rental_deposit_to_owner: 'Залог владельцу' };

function Bars({ data, field, color, title }) {                     // tiny SVG bar chart, no extra library
  const W = 560, H = 150, P = 24, max = Math.max(1, ...data.map((d) => d[field]));
  const bw = (W - P * 2) / Math.max(1, data.length);
  const total = data.reduce((a, d) => a + d[field], 0);
  return (
    <div>
      <div className="flex justify-between text-xs text-text-muted mb-1"><span>{title}</span><span className="text-white font-bold">{n(total)} $CITY</span></div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-36">
        <line x1={P} y1={H - P} x2={W - P} y2={H - P} stroke="rgba(255,255,255,0.15)" />
        {data.map((d, i) => {
          const h = (d[field] / max) * (H - P * 2);
          return <rect key={d.day} x={P + i * bw + 1} y={H - P - h} width={Math.max(1, bw - 2)} height={h} fill={color} rx="2"><title>{`${d.day}: ${n(d[field])} $CITY`}</title></rect>;
        })}
        <text x={P} y={H - 6} fill="rgba(255,255,255,0.45)" fontSize="10">{data[0]?.day?.slice(5)}</text>
        <text x={W - P} y={H - 6} fill="rgba(255,255,255,0.45)" fontSize="10" textAnchor="end">{data[data.length - 1]?.day?.slice(5)}</text>
        <text x={P} y={14} fill="rgba(255,255,255,0.45)" fontSize="10">{n(max)}</text>
      </svg>
    </div>
  );
}

export default function RentalPanel({ token }) {
  const [cfg, setCfg] = useState(null); const [st, setSt] = useState(null); const [days, setDays] = useState(30);
  const h = { headers: { Authorization: `Bearer ${token}` } };
  const load = useCallback(async () => {
    try {
      const [c, s] = await Promise.all([axios.get(`${API}/admin/rental/config`, h), axios.get(`${API}/admin/rental/stats`, { ...h, params: { days } })]);
      setCfg(c.data); setSt(s.data);
    } catch (e) { toast.error('Не удалось загрузить аренду'); }
  }, [days]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);
  const save = async () => {
    try { const r = await axios.put(`${API}/admin/rental/config`, cfg, h); setCfg(r.data); toast.success('Сохранено'); }
    catch (e) { toast.error(e?.response?.data?.detail || 'Ошибка'); }
  };
  if (!cfg || !st) return <div className="text-sm text-text-muted">Загрузка…</div>;
  const field = (k, label, step = 1) => (
    <label className="space-y-1 text-xs text-text-muted"><span>{label}</span>
      <Input type="number" step={step} value={cfg[k]} onChange={(e) => setCfg((c) => ({ ...c, [k]: e.target.value }))} className="bg-black/40 border-white/10 h-9" /></label>
  );
  const T = st.totals;
  return (
    <div className="space-y-4" data-testid="admin-rental-panel">
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {[['Выплачено владельцам', `${n(T.rent_paid_city)} $CITY`], ['Комиссия в казну', `${n(T.commission_city)} $CITY`], ['Заморожено сейчас', `${n(T.frozen_city)} $CITY`],
          ['Активных аренд', T.active], ['Предложений', T.offers]].map(([l, v]) => (
          <Card key={l} className="glass-panel border-white/10"><CardContent className="p-3"><div className="text-[11px] text-text-muted">{l}</div><div className="text-lg font-bold text-white">{v}</div></CardContent></Card>
        ))}
      </div>
      <Card className="glass-panel border-white/10">
        <CardHeader className="pb-2 flex-row items-center justify-between"><CardTitle className="text-sm">Доход с аренды по дням</CardTitle>
          <div className="flex gap-1">{[7, 30, 90].map((d) => <Button key={d} size="sm" variant={days === d ? 'default' : 'outline'} className="h-7 text-xs" onClick={() => setDays(d)}>{d} дн.</Button>)}</div>
        </CardHeader>
        <CardContent className="grid md:grid-cols-2 gap-4">
          <Bars data={st.chart} field="rent_city" color="#22d3ee" title="Выплачено владельцам" />
          <Bars data={st.chart} field="commission_city" color="#ffd84d" title="Комиссия в казну" />
        </CardContent>
      </Card>
      <Card className="glass-panel border-white/10">
        <CardHeader className="pb-2"><CardTitle className="text-sm">Настройки аренды</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <label className="flex items-center gap-2 text-sm text-white"><input type="checkbox" checked={!!cfg.enabled} onChange={(e) => setCfg((c) => ({ ...c, enabled: e.target.checked }))} /> Аренда включена</label>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {field('commission_pct', 'Комиссия в казну, %', 0.5)}
            {field('min_price_pct', 'Мин. цена, % от прибыли', 1)}
            {field('max_price_pct', 'Макс. цена, % от прибыли', 1)}
            {field('max_businesses_per_user', 'Бизнесов на игрока (с арендой)')}
            {field('min_days', 'Мин. срок, суток')}
            {field('max_days', 'Макс. срок, суток')}
            {field('deposit_days', 'Залог, суток')}
            {field('deposit_wear_points', 'Залог владельцу, если износ > пунктов')}
          </div>
          <Button size="sm" onClick={save} data-testid="rental-config-save">Сохранить</Button>
        </CardContent>
      </Card>
      <Card className="glass-panel border-white/10">
        <CardHeader className="pb-2"><CardTitle className="text-sm">Транзакции аренды</CardTitle></CardHeader>
        <CardContent className="max-h-80 overflow-y-auto">
          <table className="w-full text-xs">
            <thead className="text-text-muted"><tr><th className="text-left py-1">Время</th><th className="text-left">Операция</th><th className="text-left">Игрок</th><th className="text-right">Сумма</th></tr></thead>
            <tbody>
              {(st.transactions || []).map((t) => (
                <tr key={t.id} className="border-t border-white/5 text-white">
                  <td className="py-1">{new Date(t.created_at).toLocaleString()}</td><td>{TX[t.tx_type] || t.tx_type}</td>
                  <td className="text-text-muted">{t.user_id ? `@${t.username || t.user_id}` : 'казна'}</td><td className="text-right">{n(t.amount_ton * 1000)} $CITY</td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  );
}
