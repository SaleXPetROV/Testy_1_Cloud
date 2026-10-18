/** Admin → «Данные» → «Альянсы»: settings (every number of the system + the level table), the list of alliances,
 *  an alliance card (members, log), freeze payouts, rename / change the tag, disband. Russian only. */
import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';

const API = `${process.env.REACT_APP_BACKEND_URL || ''}/api/admin/alliances`;
const h = () => ({ headers: { Authorization: `Bearer ${localStorage.getItem('token') || ''}` } });
const inp = 'rounded bg-black/40 border border-white/10 px-2 py-1.5 text-white text-sm w-full';
const nf = (n) => Number(n || 0).toLocaleString('ru-RU', { maximumFractionDigits: 2 });
const errMsg = (e) => { const d = e?.response?.data?.detail; return typeof d === 'string' ? d : (d?.code || 'Ошибка'); };

const FIELDS = [
  ['create_cost_city', 'Цена создания, $CITY'], ['create_min_pass_level', 'Уровень City Pass для создания'],
  ['rejoin_cooldown_hours', 'Повторное вступление через, ч'], ['deputies_max', 'Заместителей, макс.'], ['officers_max', 'Офицеров, макс.'],
  ['tax_max_pct', 'Налог альянса, макс. %'], ['tax_change_days', 'Менять налог не чаще, дней'],
  ['deposit_min_city', 'Мин. взнос в казну, $CITY'], ['deposit_daily_cap_city', 'Взносы игрока в день, $CITY'],
  ['deputy_daily_payout_city', 'Выплаты заместителя в день, $CITY'], ['axp_share_pct', 'Доля XP City Pass → AXP, %'],
  ['axp_daily_cap_per_player', 'AXP от игрока в день, макс.'], ['request_expire_days', 'Заявки истекают через, дней'],
  ['inactive_leader_days', 'Смена неактивного лидера через, дней'], ['solo_disband_days', 'Роспуск альянса из 1 игрока через, дней'],
];
const KIND = { create: 'создание', join: 'вступил', leave: 'вышел', kick: 'исключён', deposit: 'взнос', tax: 'налог', payout: 'выплата',
  level_up: 'новый уровень', role: 'роль', leader: 'новый лидер', tax_set: 'налог изменён', disband: 'роспуск', admin_freeze: 'заморозка (админ)', admin_rename: 'переименование (админ)' };
const UNLOCK = { chat: 'чат', treasury: 'казна', tag: 'тег', bonus_warehouse: 'склад +5% (скоро)', drives: 'сборы ресурсов (скоро)',
  bonus_repair: 'ремонт −5% (скоро)', district_wars: 'войны районов (скоро)', weekly_chest: 'сундук раз в неделю (скоро)',
  bonus_market: 'комиссия рынка −1% (скоро)', research_slot2: '2-й слот исследований (скоро)', bonus_income3: 'доход +3% (скоро)',
  veteran_emblem: 'герб «Ветераны» (скоро)', hq: 'штаб на карте (скоро)', bonus_income5: 'доход +5% (скоро)' };
const ROLE = { leader: 'лидер', deputy: 'заместитель', officer: 'офицер', member: 'участник' };
const MODE = { open: 'открытое', request: 'по заявке', invite: 'по приглашению' };

function Config() {
  const [c, setC] = useState(null);
  useEffect(() => { axios.get(`${API}/config`, h()).then((r) => setC(r.data)).catch(() => {}); }, []);
  if (!c) return null;
  const save = async () => {
    try { const r = await axios.put(`${API}/config`, c, h()); setC(r.data); toast.success('Сохранено'); }
    catch (e) { toast.error(errMsg(e)); }
  };
  const setLv = (i, k, v) => setC((x) => ({ ...x, levels: x.levels.map((l, j) => (j === i ? { ...l, [k]: v } : l)) }));
  return (
    <div className="rounded-xl border border-fuchsia-400/30 bg-fuchsia-500/5 p-4 space-y-3" data-testid="admin-alliances-config">
      <div className="flex items-center justify-between gap-2">
        <div className="font-bold text-white">Настройки альянсов</div>
        <label className="flex items-center gap-2 text-sm text-white"><input type="checkbox" checked={!!c.enabled} onChange={(e) => setC({ ...c, enabled: e.target.checked })} /> Альянсы включены</label>
      </div>
      <label className="flex items-center gap-2 text-xs text-text-muted"><input type="checkbox" checked={!!c.create_requires_business} onChange={(e) => setC({ ...c, create_requires_business: e.target.checked })} /> Для создания нужен хотя бы один бизнес</label>
      <div className="grid md:grid-cols-3 gap-3 text-xs text-text-muted">
        {FIELDS.map(([k, label]) => (
          <label key={k} className="space-y-1"><span>{label}</span>
            <input className={inp} type="number" value={c[k]} onChange={(e) => setC({ ...c, [k]: e.target.value })} data-testid={`adm-al-${k}`} /></label>
        ))}
      </div>
      <div className="text-sm font-bold text-white pt-1">Уровни</div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead><tr className="text-text-muted text-left"><th className="p-1">Ур.</th><th className="p-1">AXP</th><th className="p-1">Взнос из казны, $CITY</th><th className="p-1">Мест</th><th className="p-1">Открывает</th></tr></thead>
          <tbody>
            {c.levels.map((l, i) => (
              <tr key={i} className="border-t border-white/5">
                <td className="p-1 text-white">{i + 1}</td>
                <td className="p-1"><input className={`${inp} w-28`} type="number" value={l.axp} disabled={i === 0} onChange={(e) => setLv(i, 'axp', e.target.value)} /></td>
                <td className="p-1"><input className={`${inp} w-28`} type="number" value={l.fee_city} disabled={i === 0} onChange={(e) => setLv(i, 'fee_city', e.target.value)} /></td>
                <td className="p-1"><input className={`${inp} w-20`} type="number" value={l.slots} onChange={(e) => setLv(i, 'slots', e.target.value)} /></td>
                <td className="p-1 text-text-muted">{(l.unlocks || []).map((u) => UNLOCK[u] || u).join(', ')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="text-[11px] text-text-muted">Сейчас работает этап 1: чат, казна, тег, места по уровням. Бонусы уровней (склад, ремонт, рынок, доход), сборы, исследования и соревнования показываются игрокам с пометкой «скоро».</div>
      <Button size="sm" onClick={save} data-testid="adm-al-save">Сохранить</Button>
    </div>
  );
}

function Detail({ id, onBack, onChanged }) {
  const [d, setD] = useState(null);
  const [name, setName] = useState('');
  const [tag, setTag] = useState('');
  const load = useCallback(async () => {
    try { const r = await axios.get(`${API}/${id}`, h()); setD(r.data); setName(r.data.alliance.name); setTag(r.data.alliance.tag); }
    catch (e) { toast.error(errMsg(e)); }
  }, [id]);
  useEffect(() => { load(); }, [load]);
  if (!d) return <div className="text-text-muted text-sm">Загрузка…</div>;
  const a = d.alliance;
  const act = async (fn, ok) => { try { await fn(); toast.success(ok); await load(); onChanged(); } catch (e) { toast.error(errMsg(e)); } };
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4 space-y-3" data-testid="admin-alliance-detail">
      <button type="button" onClick={onBack} className="text-xs text-cyan-300">← к списку</button>
      <div className="text-lg font-bold text-white">{a.emblem} [{a.tag}] {a.name} <span className="text-xs text-text-muted">· {a.status === 'active' ? 'активен' : 'распущен'}</span></div>
      <div className="grid md:grid-cols-4 gap-2 text-xs">
        <div className="rounded-lg bg-white/5 p-2">Уровень <b className="text-white">{a.level}</b> · AXP {nf(a.axp)}</div>
        <div className="rounded-lg bg-white/5 p-2">Казна <b className="text-amber-200">{nf(a.treasury_city)} $CITY</b></div>
        <div className="rounded-lg bg-white/5 p-2">Налог {a.tax_pct || 0}% · {MODE[a.join_mode] || a.join_mode}</div>
        <div className="rounded-lg bg-white/5 p-2">Выплаты: {a.frozen ? <b className="text-red-300">заморожены</b> : 'разрешены'}</div>
      </div>
      {a.status === 'active' && (
        <div className="flex flex-wrap gap-2 items-end">
          <label className="text-xs text-text-muted space-y-1"><span>Название</span><input className={`${inp} w-48`} value={name} onChange={(e) => setName(e.target.value)} /></label>
          <label className="text-xs text-text-muted space-y-1"><span>Тег</span><input className={`${inp} w-24 uppercase`} maxLength={4} value={tag} onChange={(e) => setTag(e.target.value.toUpperCase())} /></label>
          <Button size="sm" variant="outline" onClick={() => act(() => axios.post(`${API}/${id}/rename`, { name: name !== a.name ? name : undefined, tag: tag !== a.tag ? tag : undefined }, h()), 'Переименовано')}>Переименовать</Button>
          <Button size="sm" variant="outline" onClick={() => act(() => axios.post(`${API}/${id}/freeze`, { frozen: !a.frozen }, h()), a.frozen ? 'Выплаты разрешены' : 'Выплаты заморожены')}>
            {a.frozen ? 'Разморозить выплаты' : 'Заморозить выплаты'}</Button>
          <Button size="sm" variant="outline" className="border-red-400/50 text-red-300"
            onClick={() => { if (window.confirm(`Распустить «${a.name}»? Казна будет разделена между участниками по взносам за 30 дней.`)) act(() => axios.post(`${API}/${id}/disband`, {}, h()), 'Распущен'); }}>Распустить</Button>
        </div>
      )}
      <div className="grid md:grid-cols-2 gap-3">
        <div>
          <div className="text-sm font-bold text-white mb-1">Участники ({d.members.length})</div>
          <div className="max-h-80 overflow-y-auto divide-y divide-white/5 text-xs">
            {d.members.map((m, i) => <div key={i} className="py-1 flex justify-between"><span className="text-white">{m.username}</span><span className="text-text-muted">{ROLE[m.role]} · AXP {nf(m.axp_total)}</span></div>)}
          </div>
        </div>
        <div>
          <div className="text-sm font-bold text-white mb-1">Журнал</div>
          <div className="max-h-80 overflow-y-auto divide-y divide-white/5 text-xs">
            {d.log.map((x, i) => (
              <div key={i} className="py-1 flex justify-between gap-2">
                <span className="text-white/80 truncate">{KIND[x.kind] || x.kind}{x.username ? ` · ${x.username}` : ''}{x.meta?.role ? ` · ${ROLE[x.meta.role]}` : ''}{x.meta?.level ? ` · ${x.meta.level}` : ''}{x.meta?.pct !== undefined ? ` · ${x.meta.pct}%` : ''}</span>
                <span className="text-text-muted shrink-0">{x.amount_city ? `${nf(x.amount_city)} · ` : ''}{new Date(x.created_at).toLocaleString('ru-RU')}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function AlliancesPanel() {
  const [q, setQ] = useState('');
  const [status, setStatus] = useState('active');
  const [d, setD] = useState(null);
  const [open, setOpen] = useState(null);
  const load = useCallback(async () => {
    try { const r = await axios.get(API, { ...h(), params: { q, status } }); setD(r.data); } catch (e) { toast.error(errMsg(e)); }
  }, [q, status]);
  useEffect(() => { const id = setTimeout(load, 250); return () => clearTimeout(id); }, [load]);
  return (
    <div className="space-y-4" data-testid="admin-alliances">
      <Config />
      {open ? <Detail id={open} onBack={() => setOpen(null)} onChanged={load} /> : (
        <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="font-bold text-white mr-auto">Альянсы</div>
            {d && <div className="text-xs text-text-muted">Активных: <b className="text-white">{d.totals.active}</b> · игроков в альянсах: <b className="text-white">{d.totals.members}</b> · в казнах: <b className="text-amber-200">{nf(d.totals.treasury_city)} $CITY</b></div>}
          </div>
          <div className="flex flex-wrap gap-2">
            <input className={`${inp} max-w-xs`} placeholder="Поиск по названию или тегу" value={q} onChange={(e) => setQ(e.target.value)} />
            <select className={`${inp} w-40`} value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="active">Активные</option><option value="disbanded">Распущенные</option><option value="all">Все</option>
            </select>
            <Button size="sm" variant="outline" onClick={async () => { try { const r = await axios.post(`${API}/maintenance`, {}, h()); toast.success(`Заявок истекло: ${r.data.expired}, лидеров сменено: ${r.data.leaders}, распущено: ${r.data.disbanded}`); load(); } catch (e) { toast.error(errMsg(e)); } }}>Обслуживание сейчас</Button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs" data-testid="admin-alliances-table">
              <thead><tr className="text-text-muted text-left"><th className="p-1">Альянс</th><th className="p-1">Лидер</th><th className="p-1">Ур.</th><th className="p-1">Участники</th><th className="p-1">AXP за неделю</th><th className="p-1">Казна</th><th className="p-1">Налог</th><th className="p-1">Вступление</th><th className="p-1" /></tr></thead>
              <tbody>
                {(d?.alliances || []).map((a) => (
                  <tr key={a.id} className="border-t border-white/5 hover:bg-white/5 cursor-pointer" onClick={() => setOpen(a.id)}>
                    <td className="p-1 text-white">{a.emblem} [{a.tag}] {a.name}{a.status !== 'active' ? ' · распущен' : ''}</td>
                    <td className="p-1">{a.leader || '—'}</td><td className="p-1">{a.level}</td><td className="p-1">{a.members_count}/{a.slots}</td>
                    <td className="p-1">{nf(a.axp_week)}</td><td className="p-1 text-amber-200">{nf(a.treasury_city)}</td><td className="p-1">{a.tax_pct}%</td>
                    <td className="p-1">{MODE[a.join_mode]}</td><td className="p-1">{a.frozen ? <span className="text-red-300">заморожен</span> : ''}</td>
                  </tr>
                ))}
                {d && !d.alliances.length && <tr><td className="p-2 text-text-muted" colSpan={9}>Пока нет альянсов</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
