/**
 * LeaguesPanel — admin analytics + settings for the weekly leagues (backend/leagues.py).
 * Three ratings (activity points / units sold / TON sold), each with its own
 * on-off switch and rewards per place; the points table and caps; promotion /
 * relegation rules; group size; finalize-now for testing.
 */
import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { toast } from 'sonner';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { RefreshCw, Trophy } from 'lucide-react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api/admin/leagues`;
const BOARD_RU = { points: 'Очки активности', units_sold: 'Продано единиц', ton_sold: 'Сумма продаж (TON)' };
const POINTS_RU = { daily_goal: 'Цель дня', weekly_goal: 'Цель недели', shift_start: 'Запуск смены', repair: 'Ремонт', sale_per_0_01_ton: 'Продажа игроку, за 0,01 TON', streak_day: 'День серии входов' };
const CAPS_RU = { daily_goal: 'Целей дня в день', weekly_goal: 'Целей недели в день', shift_start: 'Смен в день', repair: 'Ремонтов в день', sale: 'Очков за продажи в день', streak_day: 'Дней серии в день' };

function Kpi({ label, value, sub }) {
  return (
    <div className="rounded-xl bg-white/5 border border-white/10 p-3">
      <div className="text-[11px] uppercase tracking-wide text-text-muted">{label}</div>
      <div className="text-xl font-bold mt-1 text-white">{value}</div>
      {sub && <div className="text-[11px] text-text-muted mt-0.5">{sub}</div>}
    </div>
  );
}

function Num({ label, value, onChange, tid }) {
  return (
    <label className="text-xs space-y-1">
      <span className="text-text-muted">{label}</span>
      <Input type="number" min="0" step="1" value={value ?? ''} onChange={(e) => onChange(e.target.value)}
        className="bg-black/40 border-white/10 h-9" data-testid={tid} />
    </label>
  );
}

export default function LeaguesPanel({ token }) {
  const [a, setA] = useState(null);
  const [form, setForm] = useState(null);
  const [busy, setBusy] = useState(false);
  const headers = { headers: { Authorization: `Bearer ${token}` } };

  const load = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/analytics`, headers);
      setA(r.data);
      setForm((f) => f || JSON.parse(JSON.stringify(r.data.config)));
    } catch (e) { toast.error(e?.response?.data?.detail || 'Не удалось загрузить лиги'); }
  }, [token]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);

  const set = (path, value) => setForm((f) => {
    const n = JSON.parse(JSON.stringify(f));
    let o = n;
    path.slice(0, -1).forEach((k) => { o = o[k]; });
    o[path[path.length - 1]] = value;
    return n;
  });

  const save = async () => {
    setBusy(true);
    try {
      const patch = JSON.parse(JSON.stringify(form));
      Object.keys(patch.boards).forEach((b) => {
        const r = patch.boards[b].rewards_city;
        patch.boards[b].rewards_city = Array.isArray(r) ? r : String(r || '');
      });
      const r = await axios.put(`${API}/config`, patch, headers);
      setForm(JSON.parse(JSON.stringify(r.data)));
      toast.success('Настройки лиг сохранены');
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || 'Ошибка сохранения'); }
    finally { setBusy(false); }
  };

  const finalize = async () => {
    setBusy(true);
    try {
      const r = await axios.post(`${API}/finalize`, {}, headers);
      toast.success(`Итоги подведены: ${JSON.stringify(r.data)}`);
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || 'Ошибка'); }
    finally { setBusy(false); }
  };

  if (!a || !form) return <div className="text-sm text-text-muted">Загрузка…</div>;
  const rt = a.retention_prev_week;

  return (
    <div className="space-y-4" data-testid="leagues-panel">
      <div className="flex flex-wrap items-center gap-3">
        <Trophy className="w-5 h-5 text-yellow-400" />
        <span className="font-bold text-white">Лиги · неделя {a.week}</span>
        <label className="flex items-center gap-2 text-sm">
          <Switch checked={!!form.enabled} onCheckedChange={(v) => set(['enabled'], v)} data-testid="lg-enabled" />
          <span className={form.enabled ? 'text-emerald-400' : 'text-text-muted'}>{form.enabled ? 'Включены' : 'Выключены'}</span>
        </label>
        <div className="flex gap-1 ml-auto">
          <Button size="sm" variant="outline" className="h-8 text-xs" onClick={load}><RefreshCw className="w-3.5 h-3.5" /></Button>
          <Button size="sm" variant="outline" className="h-8 text-xs" onClick={finalize} disabled={busy}>Подвести итоги прошлых недель</Button>
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-2" data-testid="lg-kpis">
        <Kpi label="Участников на неделе" value={a.participants} sub={`групп: ${a.groups} · средние очки: ${a.avg_points}`} />
        <Kpi label="Продано участниками" value={`${a.units_sold} ед.`} sub={`${a.ton_sold} TON`} />
        <Kpi label="Возврат через неделю" value={rt.members_pct == null ? '—' : `${rt.members_pct}%`}
          sub={`участники лиги (${rt.members}) · без лиги: ${rt.non_members_pct == null ? '—' : rt.non_members_pct + '%'} (${rt.non_members})`} />
        <Kpi label="Наград выдано всего" value={`${a.rewards_city_total} $CITY`} sub="на бонусный баланс" />
      </div>

      <Card className="glass-panel border-white/10">
        <CardHeader className="pb-2"><CardTitle className="text-sm">По дивизионам</CardTitle></CardHeader>
        <CardContent className="flex flex-wrap gap-2 text-xs">
          {a.by_division.map((d) => <span key={d.division} className="rounded-lg bg-white/5 border border-white/10 px-3 py-1.5">{d.division}: <b className="text-white">{d.players}</b></span>)}
        </CardContent>
      </Card>

      <Card className="glass-panel border-white/10">
        <CardHeader className="pb-2"><CardTitle className="text-sm">Рейтинги и награды</CardTitle></CardHeader>
        <CardContent className="space-y-3" data-testid="lg-boards">
          {Object.keys(BOARD_RU).map((b) => (
            <div key={b} className="grid sm:grid-cols-[220px_1fr] gap-2 items-center">
              <label className="flex items-center gap-2 text-sm">
                <Switch checked={!!form.boards[b].enabled} onCheckedChange={(v) => set(['boards', b, 'enabled'], v)} data-testid={`lg-board-${b}`} />
                <span className="text-white">{BOARD_RU[b]}</span>
              </label>
              <label className="text-xs space-y-1">
                <span className="text-text-muted">Награда за места, $CITY через запятую (1-е, 2-е, …)</span>
                <Input value={Array.isArray(form.boards[b].rewards_city) ? form.boards[b].rewards_city.join(', ') : form.boards[b].rewards_city}
                  onChange={(e) => set(['boards', b, 'rewards_city'], e.target.value)} className="bg-black/40 border-white/10 h-9" data-testid={`lg-rewards-${b}`} />
              </label>
            </div>
          ))}
          <div className="grid sm:grid-cols-4 gap-3">
            <label className="text-xs space-y-1">
              <span className="text-text-muted">Повышение / вылет по рейтингу</span>
              <select value={form.promotion_board} onChange={(e) => set(['promotion_board'], e.target.value)}
                className="w-full h-9 rounded-md bg-black/40 border border-white/10 px-2 text-white" data-testid="lg-promo-board">
                {Object.keys(BOARD_RU).map((b) => <option key={b} value={b}>{BOARD_RU[b]}</option>)}
              </select>
            </label>
            <Num label="Поднимаются (топ N)" value={form.promote_count} onChange={(v) => set(['promote_count'], v)} tid="lg-promote" />
            <Num label="Опускаются (последние N)" value={form.relegate_count} onChange={(v) => set(['relegate_count'], v)} tid="lg-relegate" />
            <Num label="Размер группы" value={form.group_size} onChange={(v) => set(['group_size'], v)} tid="lg-group-size" />
            <Num label="Щит серии топ-N по очкам" value={form.shield_top_n} onChange={(v) => set(['shield_top_n'], v)} tid="lg-shield" />
            <Num label="Макс. очков в день" value={form.daily_points_cap} onChange={(v) => set(['daily_points_cap'], v)} tid="lg-daily-cap" />
          </div>
        </CardContent>
      </Card>

      <Card className="glass-panel border-white/10">
        <CardHeader className="pb-2"><CardTitle className="text-sm">Очки активности</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="grid sm:grid-cols-3 gap-3" data-testid="lg-points">
            {Object.keys(POINTS_RU).map((k) => <Num key={k} label={`${POINTS_RU[k]}: очков`} value={form.points[k]} onChange={(v) => set(['points', k], v)} tid={`lg-pt-${k}`} />)}
          </div>
          <div className="grid sm:grid-cols-3 gap-3" data-testid="lg-caps">
            {Object.keys(CAPS_RU).map((k) => <Num key={k} label={`Лимит: ${CAPS_RU[k]}`} value={form.caps[k]} onChange={(v) => set(['caps', k], v)} tid={`lg-cap-${k}`} />)}
          </div>
          <p className="text-[11px] text-text-muted">Продажи Городскому рынку и между аккаунтами с одного устройства не считаются ни в очки, ни в рейтинги продаж. Награды идут на бонусный баланс.</p>
          <Button size="sm" disabled={busy} onClick={save} data-testid="lg-save">Сохранить настройки лиг</Button>
        </CardContent>
      </Card>
    </div>
  );
}
