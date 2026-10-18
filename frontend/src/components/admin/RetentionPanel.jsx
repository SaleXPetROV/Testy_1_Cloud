/**
 * RetentionPanel — admin analytics tab (backend/analytics.py).
 *
 * Cohort retention (D1/D7/D30), the newcomer funnel and DAU. A group filter
 * (all / quests / tutorial) compares the two onboarding variants of the A/B
 * test, so you can tell whether the quest onboarding keeps players better than
 * the old tutorial before switching ONBOARDING_MODE to "quests".
 */
import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Users, TrendingUp, Filter } from 'lucide-react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api`;

const GROUPS = [
  { id: 'all', label: 'Все' },
  { id: 'quests', label: 'Задания' },
  { id: 'tutorial', label: 'Обучение' },
];

const fmtPct = (v) => (v === null || v === undefined ? '—' : `${v}%`);

function Stat({ label, value, hint }) {
  return (
    <div className="rounded-xl bg-white/5 border border-white/10 p-3">
      <div className="text-[11px] uppercase tracking-wide text-text-muted">{label}</div>
      <div className="text-2xl font-bold text-white mt-1">{value}</div>
      {hint && <div className="text-[11px] text-text-muted mt-0.5">{hint}</div>}
    </div>
  );
}

function Bars({ series }) {
  const max = Math.max(1, ...series.map((s) => s.dau));
  return (
    <div className="flex items-end gap-1 h-28" data-testid="dau-bars">
      {series.map((s) => (
        <div key={s.date} className="flex-1 flex flex-col items-center justify-end gap-1" title={`${s.date}: ${s.dau}`}>
          <div className="w-full rounded-t bg-cyan-400/70" style={{ height: `${Math.round((s.dau / max) * 100)}%`, minHeight: s.dau ? 3 : 0 }} />
          <div className="text-[9px] text-text-muted">{s.date.slice(5)}</div>
        </div>
      ))}
    </div>
  );
}

export default function RetentionPanel({ token }) {
  const [group, setGroup] = useState('all');
  const [days, setDays] = useState(30);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await axios.get(`${API}/admin/analytics/overview?days=${days}&group=${group}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      setData(r.data);
    } catch (e) {
      setError(e?.response?.data?.detail || 'Не удалось загрузить аналитику');
    } finally {
      setLoading(false);
    }
  }, [token, group, days]);

  useEffect(() => { load(); }, [load]);

  const ret = data?.retention?.overall;
  const cohorts = data?.retention?.cohorts || [];
  const funnel = data?.funnel?.steps || [];
  const active = data?.active?.series || [];

  return (
    <div className="space-y-4" data-testid="retention-panel">
      <div className="flex flex-wrap items-center gap-2">
        <Filter className="w-4 h-4 text-text-muted" />
        {GROUPS.map((g) => (
          <Button key={g.id} size="sm" variant={group === g.id ? 'default' : 'outline'}
            className="h-8 text-xs" onClick={() => setGroup(g.id)} data-testid={`retention-group-${g.id}`}>
            {g.label}
          </Button>
        ))}
        <span className="mx-1 text-white/20">|</span>
        {[7, 30, 90].map((d) => (
          <Button key={d} size="sm" variant={days === d ? 'default' : 'outline'}
            className="h-8 text-xs" onClick={() => setDays(d)}>{d} дн.</Button>
        ))}
        <Button size="sm" variant="outline" className="h-8 text-xs ml-auto" onClick={load} disabled={loading}>
          {loading ? '…' : 'Обновить'}
        </Button>
      </div>

      {error && <div className="text-sm text-red-400">{error}</div>}

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <Stat label="Новых игроков" value={ret?.users ?? '—'} hint={`за ${days} дн.`} />
        <Stat label="Возврат D1" value={fmtPct(ret?.d1_pct)} hint={ret?.d1_n ? `из ${ret.d1_n}` : ''} />
        <Stat label="Возврат D7" value={fmtPct(ret?.d7_pct)} hint={ret?.d7_n ? `из ${ret.d7_n}` : ''} />
        <Stat label="Возврат D30" value={fmtPct(ret?.d30_pct)} hint={ret?.d30_n ? `из ${ret.d30_n}` : ''} />
      </div>

      <Card className="glass-panel border-white/10">
        <CardHeader className="pb-2"><CardTitle className="text-sm flex items-center gap-2"><TrendingUp className="w-4 h-4 text-yellow-400" />Воронка новичка</CardTitle></CardHeader>
        <CardContent className="space-y-2">
          {funnel.map((s) => (
            <div key={s.event} className="space-y-1" data-testid={`funnel-${s.event}`}>
              <div className="flex justify-between text-xs">
                <span className="text-white">{s.label}</span>
                <span className="text-text-muted">{s.users} · {s.pct}%{s.pct_prev !== undefined && s.event !== 'register' ? ` (шаг: ${s.pct_prev}%)` : ''}</span>
              </div>
              <div className="h-2 rounded-full bg-white/10 overflow-hidden">
                <div className="h-full bg-yellow-400" style={{ width: `${s.pct}%` }} />
              </div>
            </div>
          ))}
          {!funnel.length && <div className="text-xs text-text-muted">Нет данных за выбранный период.</div>}
        </CardContent>
      </Card>

      <Card className="glass-panel border-white/10">
        <CardHeader className="pb-2"><CardTitle className="text-sm flex items-center gap-2"><Users className="w-4 h-4 text-cyan-400" />Активные игроки по дням</CardTitle></CardHeader>
        <CardContent>{active.length ? <Bars series={active} /> : <div className="text-xs text-text-muted">Нет данных.</div>}</CardContent>
      </Card>

      <Card className="glass-panel border-white/10">
        <CardHeader className="pb-2"><CardTitle className="text-sm">Когорты по дню регистрации</CardTitle></CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-text-muted text-left">
                <th className="py-1 pr-3">Дата</th><th className="py-1 pr-3">Игроков</th>
                <th className="py-1 pr-3">D1</th><th className="py-1 pr-3">D7</th><th className="py-1 pr-3">D30</th>
              </tr>
            </thead>
            <tbody>
              {cohorts.slice().reverse().map((c) => (
                <tr key={c.date} className="border-t border-white/5">
                  <td className="py-1 pr-3 text-white">{c.date}</td>
                  <td className="py-1 pr-3">{c.users}</td>
                  <td className="py-1 pr-3">{fmtPct(c.d1_pct)}</td>
                  <td className="py-1 pr-3">{fmtPct(c.d7_pct)}</td>
                  <td className="py-1 pr-3">{fmtPct(c.d30_pct)}</td>
                </tr>
              ))}
              {!cohorts.length && <tr><td colSpan={5} className="py-2 text-text-muted">Нет данных.</td></tr>}
            </tbody>
          </table>
          <p className="text-[11px] text-text-muted mt-2">«—» означает, что когорта ещё слишком молода для этого показателя (например, D7 для тех, кто зарегистрировался 3 дня назад).</p>
        </CardContent>
      </Card>
    </div>
  );
}
