/**
 * ComebackPanel — admin settings + stats for the comeback bonus (backend/comeback.py).
 * Small gift after N days away, big gift after M days away: $CITY (bonus balance),
 * warehouse decay protection (hours) and streak shields for the big one.
 */
import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { toast } from 'sonner';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Gift, RefreshCw } from 'lucide-react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api/admin/comeback`;

const GROUPS = [
  { title: 'Малый подарок', fields: [
    { key: 'small_after_days', label: 'Не заходил дней (от)' },
    { key: 'small_city', label: 'Бонусные $CITY' },
    { key: 'small_protect_hours', label: 'Защита склада (часов)' },
  ] },
  { title: 'Большой подарок', fields: [
    { key: 'big_after_days', label: 'Не заходил дней (от)' },
    { key: 'big_city', label: 'Бонусные $CITY' },
    { key: 'big_protect_hours', label: 'Защита склада (часов)' },
    { key: 'big_shields', label: 'Щитов серии' },
  ] },
];

function Kpi({ label, value, sub }) {
  return (
    <div className="rounded-xl bg-white/5 border border-white/10 p-3">
      <div className="text-[11px] uppercase tracking-wide text-text-muted">{label}</div>
      <div className="text-xl font-bold mt-1 text-white">{value}</div>
      {sub && <div className="text-[11px] text-text-muted mt-0.5">{sub}</div>}
    </div>
  );
}

export default function ComebackPanel({ token }) {
  const [days, setDays] = useState(30);
  const [stats, setStats] = useState(null);
  const [form, setForm] = useState(null);
  const [busy, setBusy] = useState(false);
  const headers = { headers: { Authorization: `Bearer ${token}` } };

  const load = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/stats?days=${days}`, headers);
      setStats(r.data);
      setForm((f) => f || r.data.config);
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Не удалось загрузить данные');
    }
  }, [days, token]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setBusy(true);
    try {
      const patch = {};
      GROUPS.forEach((g) => g.fields.forEach((f) => { patch[f.key] = Math.max(0, parseInt(form[f.key], 10) || 0); }));
      const r = await axios.put(`${API}/config`, patch, headers);
      setForm(r.data.config);
      toast.success('Бонус возвращения сохранён');
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Ошибка сохранения');
    } finally {
      setBusy(false);
    }
  };

  if (!stats || !form) return <div className="text-sm text-text-muted">Загрузка…</div>;

  return (
    <div className="space-y-4" data-testid="comeback-panel">
      <div className="flex flex-wrap items-center gap-2">
        <Gift className="w-5 h-5 text-purple-300" />
        <span className="font-bold text-white">Бонус возвращения</span>
        <div className="flex gap-1 ml-auto">
          {[7, 30, 90].map((d) => (
            <Button key={d} size="sm" variant={days === d ? 'default' : 'outline'} className="h-8 text-xs" onClick={() => setDays(d)}>{d} дн.</Button>
          ))}
          <Button size="sm" variant="outline" className="h-8 text-xs" onClick={load}><RefreshCw className="w-3.5 h-3.5" /></Button>
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-2" data-testid="comeback-stats">
        <Kpi label="Подарков выдано" value={stats.claims} sub={`малых ${stats.by_tier.small} · больших ${stats.by_tier.big}`} />
        <Kpi label="Игроков вернулось" value={stats.players} sub={stats.avg_away_days != null ? `в среднем не было ${stats.avg_away_days} дн.` : ''} />
        <Kpi label="Выплачено" value={`${stats.city_paid} $CITY`} sub="на бонусный баланс" />
        <Kpi label="Сейчас" value={stats.protected_now} sub={`склад защищён · со щитами: ${stats.players_with_shields}`} />
      </div>

      <Card className="glass-panel border-white/10">
        <CardHeader className="pb-2"><CardTitle className="text-sm">Сроки и награды</CardTitle></CardHeader>
        <CardContent className="space-y-4" data-testid="comeback-settings">
          {GROUPS.map((g) => (
            <div key={g.title} className="space-y-2">
              <div className="text-xs font-semibold text-white">{g.title}</div>
              <div className="grid sm:grid-cols-4 gap-3">
                {g.fields.map((f) => (
                  <label key={f.key} className="text-xs space-y-1">
                    <span className="text-text-muted">{f.label}</span>
                    <Input type="number" min="0" step="1" value={form[f.key] ?? ''} className="bg-black/40 border-white/10 h-9"
                      onChange={(e) => setForm((s) => ({ ...s, [f.key]: e.target.value }))} data-testid={`cb-${f.key}`} />
                  </label>
                ))}
              </div>
            </div>
          ))}
          <p className="text-[11px] text-text-muted">
            Подарок выдаётся один раз за каждое возвращение. «Защита склада» отменяет полуночную потерю 10% склада на заданное число часов.
            Щит серии сохраняет серию ежедневного входа при пропуске дня (у игрока не больше 2).
          </p>
          <Button size="sm" disabled={busy} onClick={save} data-testid="cb-save">Сохранить</Button>
        </CardContent>
      </Card>
    </div>
  );
}
