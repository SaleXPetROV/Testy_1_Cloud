/**
 * CityPassPanel — admin for the City Pass (backend/city_pass.py).
 * Analytics (players by level, premium buyers, revenue, claims, retention),
 * season settings (XP per level = xp_ratio × days × daily cap / levels — the
 * last level needs 80 % of the season's maximum by default), the XP table and
 * a reward editor: free rewards on every level, premium extras on any level.
 */
import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { toast } from 'sonner';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { RefreshCw, Ticket, Plus, X } from 'lucide-react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api/admin/pass`;
const TYPES = { auto_shift: 'Автозапуск смен', warehouse_guard: 'Защита склада', repair_all: 'Ремонт всех', streak_shield: 'Щит серии', t3: 'Предмет тира 3' };
const T3 = ['neuro_core', 'gold_bill', 'license_token', 'luck_chip', 'war_protocol', 'bio_module', 'gateway_code'];
// daily / weekly goals give the XP written on the quest card (set in «Задания»), not a value here
const XP_RU = { shift_start: 'Запуск смены', repair: 'Ремонт', sale_per_0_01_ton: 'Продажа, за 0,01 TON', streak_day: 'День серии', league_top: 'Топ-5 недели в лиге' };

function Kpi({ label, value, sub }) {
  return (
    <div className="rounded-xl bg-white/5 border border-white/10 p-3">
      <div className="text-[11px] uppercase tracking-wide text-text-muted">{label}</div>
      <div className="text-xl font-bold mt-1 text-white">{value}</div>
      {sub && <div className="text-[11px] text-text-muted mt-0.5">{sub}</div>}
    </div>
  );
}

function RewardEditor({ list, onChange }) {
  const set = (i, patch) => onChange(list.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  return (
    <div className="space-y-1">
      {list.map((r, i) => (
        <div key={i} className="flex flex-wrap items-center gap-1">
          <select value={r.type} onChange={(e) => set(i, { type: e.target.value })} className="h-7 rounded bg-black/40 border border-white/10 text-[11px] text-white px-1">
            {Object.entries(TYPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          {(r.type === 'auto_shift' || r.type === 'warehouse_guard') && (
            <Input type="number" min="1" value={r.hours ?? 24} onChange={(e) => set(i, { hours: Number(e.target.value) })} className="h-7 w-16 bg-black/40 border-white/10 text-[11px]" title="часов" />
          )}
          {r.type === 't3' && (
            <select value={r.resource || T3[0]} onChange={(e) => set(i, { resource: e.target.value })} className="h-7 rounded bg-black/40 border border-white/10 text-[11px] text-white px-1">
              {T3.map((x) => <option key={x} value={x}>{x}</option>)}
            </select>
          )}
          <Input type="number" min="1" value={r.count ?? 1} onChange={(e) => set(i, { count: Number(e.target.value) })} className="h-7 w-12 bg-black/40 border-white/10 text-[11px]" title="количество" />
          <button type="button" onClick={() => onChange(list.filter((_, j) => j !== i))} className="text-white/50 hover:text-red-400"><X className="w-3.5 h-3.5" /></button>
        </div>
      ))}
      <button type="button" onClick={() => onChange([...list, { type: 'auto_shift', hours: 24, count: 1 }])} className="text-[11px] text-cyber-cyan flex items-center gap-0.5"><Plus className="w-3 h-3" />награда</button>
    </div>
  );
}

export default function CityPassPanel({ token }) {
  const [a, setA] = useState(null);
  const [f, setF] = useState(null);
  const [busy, setBusy] = useState(false);
  const headers = { headers: { Authorization: `Bearer ${token}` } };

  const load = useCallback(async () => {
    try { const r = await axios.get(`${API}/analytics`, headers); setA(r.data); setF((x) => x || JSON.parse(JSON.stringify(r.data.config))); }
    catch (e) { toast.error(e?.response?.data?.detail || 'Не удалось загрузить City Pass'); }
  }, [token]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setBusy(true);
    try {
      const patch = {};
      ['enabled', 'season_name', 'days', 'levels', 'daily_xp_cap', 'xp_ratio', 'claim_grace_days', 'xp', 'caps', 'rewards_free', 'rewards_premium']
        .forEach((k) => { patch[k] = f[k]; });
      patch.premium_price_ton = f.premium_price_ton === '' || f.premium_price_ton == null ? null : Number(f.premium_price_ton);
      patch.tier_weights = (f.tier_weights || [1.3, 1.6, 1.9]).map(Number);
      const r = await axios.put(`${API}/config`, patch, headers);
      setF(JSON.parse(JSON.stringify(r.data))); toast.success('City Pass сохранён'); load();
    } catch (e) { toast.error(e?.response?.data?.detail || 'Ошибка сохранения'); }
    finally { setBusy(false); }
  };
  const newSeason = async () => {
    const sid = window.prompt('ID нового сезона (например S2):'); if (!sid) return;
    const name = window.prompt('Название сезона:', '') || undefined;
    try { await axios.post(`${API}/new-season`, { season_id: sid, season_name: name }, headers); toast.success('Новый сезон начат'); setF(null); load(); }
    catch (e) { toast.error(e?.response?.data?.detail || 'Ошибка'); }
  };

  if (!a || !f) return <div className="text-sm text-text-muted">Загрузка…</div>;
  // preview of the tiered level costs (same formula as city_pass.level_costs)
  const maxXp = Number(f.days) * Number(f.daily_xp_cap);
  const total = Math.round(Number(f.xp_ratio) * maxXp);
  const w = (f.tier_weights || [1.3, 1.6, 1.9]).map((x) => Math.max(0.01, Number(x) || 0));
  const nLv = Number(f.levels) || 30;
  const tierOf = Array.from({ length: nLv }, (_, i) => Math.min(2, Math.floor((i * 3) / nLv)));
  const unit = total / tierOf.reduce((acc, ti) => acc + w[ti], 0);
  const tierCost = w.map((x) => Math.round(unit * x));
  const maxBy = Math.max(1, ...a.by_level.map((x) => x.players));
  const setNum = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }));

  return (
    <div className="space-y-4" data-testid="city-pass-panel">
      <div className="flex flex-wrap items-center gap-3">
        <Ticket className="w-5 h-5 text-indigo-300" />
        <span className="font-bold text-white">City Pass · {a.season_id} · {a.season_name}</span>
        <label className="flex items-center gap-2 text-sm"><Switch checked={!!f.enabled} onCheckedChange={(v) => setF((s) => ({ ...s, enabled: v }))} />{f.enabled ? 'Включён' : 'Выключен'}</label>
        <div className="flex gap-1 ml-auto">
          <Button size="sm" variant="outline" className="h-8 text-xs" onClick={load}><RefreshCw className="w-3.5 h-3.5" /></Button>
          <Button size="sm" variant="outline" className="h-8 text-xs" onClick={newSeason}>Начать новый сезон</Button>
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
        <Kpi label="Игроков в сезоне" value={a.players} sub={`наград забрано: ${a.claims}`} />
        <Kpi label="Премиум" value={a.premium} sub={`выручка ${a.revenue_ton} TON`} />
        <Kpi label="Возврат на 2-й неделе" value={a.retention_week2.pass_pct == null ? '—' : `${a.retention_week2.pass_pct}%`}
          sub={`игроки паса (${a.retention_week2.pass_n}) · без паса: ${a.retention_week2.others_pct ?? '—'}%`} />
        <Kpi label="XP за уровень (1–10 / 11–20 / 21–30)" value={tierCost.join(' / ')} sub={`весь пас = ${total} XP = ${Math.round((total / maxXp) * 100)}% от макс. ${maxXp} XP`} />
      </div>

      <Card className="glass-panel border-white/10">
        <CardHeader className="pb-2"><CardTitle className="text-sm">Игроки по уровням</CardTitle></CardHeader>
        <CardContent>
          <div className="flex items-end gap-0.5 h-24">
            {a.by_level.map((x) => (
              <div key={x.level} className="flex-1 h-full flex flex-col justify-end items-center" title={`ур. ${x.level}: ${x.players}`}>
                <div className="w-full rounded-t bg-indigo-400/70" style={{ height: `${(x.players / maxBy) * 100}%`, minHeight: x.players ? 2 : 0 }} />
                {x.level % 5 === 0 && <div className="text-[8px] text-text-muted">{x.level}</div>}
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card className="glass-panel border-white/10">
        <CardHeader className="pb-2"><CardTitle className="text-sm">Сезон</CardTitle></CardHeader>
        <CardContent className="grid sm:grid-cols-4 gap-3 text-xs">
          {[['season_name', 'Название', 'text'], ['days', 'Дней', 'number'], ['levels', 'Уровней', 'number'], ['daily_xp_cap', 'Расчётный XP в день (только для стоимости уровней — не лимит)', 'number'],
            ['xp_ratio', 'Доля XP на весь пас (0.8 = 80%)', 'number'], ['claim_grace_days', 'Дней забрать после конца', 'number'], ['premium_price_ton', `Цена премиума, TON (игрок видит ${f.premium_price_ton ? Math.round(Number(f.premium_price_ton) * 1000).toLocaleString('ru-RU') : '—'} $CITY; пусто = не продаётся)`, 'number']].map(([k, l, type]) => (
            <label key={k} className={`space-y-1 ${k === 'season_name' ? 'sm:col-span-2' : ''}`}>
              <span className="text-text-muted">{l}</span>
              <Input type={type} step="any" value={f[k] ?? ''} onChange={setNum(k)} className="bg-black/40 border-white/10 h-9" />
            </label>
          ))}
          {['Вес уровней 1–10', 'Вес уровней 11–20', 'Вес уровней 21–30'].map((l, i) => (
            <label key={l} className="space-y-1">
              <span className="text-text-muted">{l} → {tierCost[i]} XP</span>
              <Input type="number" step="0.05" min="0.05" value={(f.tier_weights || [1.3, 1.6, 1.9])[i]}
                onChange={(e) => setF((s) => { const tw = [...(s.tier_weights || [1.3, 1.6, 1.9])]; tw[i] = e.target.value; return { ...s, tier_weights: tw }; })}
                className="bg-black/40 border-white/10 h-9" data-testid={`pass-tier-${i}`} />
            </label>
          ))}
        </CardContent>
      </Card>

      <Card className="glass-panel border-white/10">
        <CardHeader className="pb-2"><CardTitle className="text-sm">XP за действия и лимиты в день</CardTitle></CardHeader>
        <CardContent className="grid sm:grid-cols-4 gap-3 text-xs">
          {Object.keys(XP_RU).map((k) => (
            <div key={k} className="space-y-1">
              <span className="text-text-muted">{XP_RU[k]}</span>
              <div className="flex gap-1">
                <Input type="number" value={f.xp[k] ?? 0} onChange={(e) => setF((s) => ({ ...s, xp: { ...s.xp, [k]: Number(e.target.value) } }))} className="bg-black/40 border-white/10 h-8" title="XP" />
                <Input type="number" value={f.caps[k === 'sale_per_0_01_ton' ? 'sale' : k] ?? 0}
                  onChange={(e) => { const ck = k === 'sale_per_0_01_ton' ? 'sale' : k; setF((s) => ({ ...s, caps: { ...s.caps, [ck]: Number(e.target.value) } })); }}
                  className="bg-black/40 border-white/10 h-8" title="лимит в день" />
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card className="glass-panel border-white/10">
        <CardHeader className="pb-2"><CardTitle className="text-sm">Награды по уровням (только предметы, без бонусного баланса)</CardTitle></CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full text-xs" data-testid="pass-rewards-editor">
            <thead><tr className="text-text-muted text-left"><th className="py-1 w-10">Ур.</th><th className="py-1">Бесплатно</th><th className="py-1">Премиум (доп.)</th></tr></thead>
            <tbody>
              {Array.from({ length: Number(f.levels) }, (_, i) => String(i + 1)).map((lvl) => (
                <tr key={lvl} className="border-t border-white/5 align-top">
                  <td className="py-1.5 font-bold text-white">{lvl}</td>
                  <td className="py-1.5 pr-2"><RewardEditor list={f.rewards_free[lvl] || []} onChange={(l) => setF((s) => ({ ...s, rewards_free: { ...s.rewards_free, [lvl]: l } }))} /></td>
                  <td className="py-1.5"><RewardEditor list={f.rewards_premium[lvl] || []} onChange={(l) => setF((s) => ({ ...s, rewards_premium: { ...s.rewards_premium, [lvl]: l } }))} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          <Button size="sm" className="mt-3" disabled={busy} onClick={save} data-testid="pass-save">Сохранить City Pass</Button>
        </CardContent>
      </Card>
    </div>
  );
}
