/**
 * ReconciliationPanel («Сверка») — backend/reconciliation.py.
 * Can the project pay everyone (assets on-chain vs players' real balances +
 * pending withdrawals) and what needs a human decision (stuck deposits,
 * withdrawals whose payout may have gone out). Every action is atomic on the
 * server, so a double click never pays twice.
 */
import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { toast } from 'sonner';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { AlertTriangle, ExternalLink, RefreshCw, Scale } from 'lucide-react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api/admin/reconciliation`;
const ton = (v) => (v === null || v === undefined ? '—' : `${Number(v).toFixed(4)} TON`);
const when = (s) => (s ? new Date(s).toLocaleString('ru-RU') : '—');
const txLink = (h) => (h ? `https://tonviewer.com/transaction/${h}` : null);

function Kpi({ label, value, sub, tone = 'text-white' }) {
  return (
    <div className="rounded-xl bg-white/5 border border-white/10 p-3">
      <div className="text-[11px] uppercase tracking-wide text-text-muted">{label}</div>
      <div className={`text-xl font-bold mt-1 ${tone}`}>{value}</div>
      {sub && <div className="text-[11px] text-text-muted mt-0.5">{sub}</div>}
    </div>
  );
}

export default function ReconciliationPanel({ token }) {
  const [r, setR] = useState(null);
  const [busy, setBusy] = useState(false);
  const [wallets, setWallets] = useState('');
  const [threshold, setThreshold] = useState('0');
  const headers = { headers: { Authorization: `Bearer ${token}` } };

  const load = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/report`, headers);
      setR(res.data);
      setWallets((res.data.settings.wallets || []).join('\n'));
      setThreshold(String(res.data.settings.alert_coverage_ton ?? 0));
    } catch (e) { toast.error(e?.response?.data?.detail || 'Не удалось загрузить сверку'); }
  }, [token]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);

  const act = async (kind, id, action, confirmText) => {
    if (!window.confirm(confirmText)) return;
    setBusy(true);
    try {
      await axios.post(`${API}/${kind}/${id}/${action}`, {}, headers);
      toast.success('Готово');
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || 'Ошибка'); }
    finally { setBusy(false); }
  };

  const saveSettings = async () => {
    setBusy(true);
    try {
      await axios.put(`${API}/settings`, { wallets: wallets.split(/\s+/).filter(Boolean), alert_coverage_ton: Number(threshold) || 0 }, headers);
      toast.success('Настройки сверки сохранены');
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || 'Ошибка'); }
    finally { setBusy(false); }
  };

  if (!r) return <div className="text-sm text-text-muted">Загрузка…</div>;
  const rv = r.review;
  const cov = r.coverage_ton;

  return (
    <div className="space-y-4" data-testid="reconciliation-panel">
      <div className="flex flex-wrap items-center gap-2">
        <Scale className="w-5 h-5 text-emerald-300" />
        <span className="font-bold text-white">Сверка платежей</span>
        <span className="text-xs text-text-muted">на {when(r.at)}</span>
        <div className="flex gap-1 ml-auto">
          <Button size="sm" variant="outline" className="h-8 text-xs" onClick={load}><RefreshCw className="w-3.5 h-3.5" /></Button>
          <Button size="sm" variant="outline" className="h-8 text-xs" disabled={busy}
            onClick={async () => { setBusy(true); try { await axios.post(`${API}/run`, {}, headers); toast.success('Проверка выполнена, при проблемах админам ушло сообщение'); load(); } finally { setBusy(false); } }}>
            Проверить и уведомить
          </Button>
        </div>
      </div>

      {r.alerts.length > 0 && (
        <div className="space-y-1.5" data-testid="rc-alerts">
          {r.alerts.map((a, i) => (
            <div key={i} className={`flex items-center gap-2 rounded-lg px-3 py-2 text-xs border ${a.level === 'critical' ? 'border-red-400/50 bg-red-500/10 text-red-200' : 'border-yellow-400/40 bg-yellow-500/10 text-yellow-200'}`}>
              <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />{a.text}
            </div>
          ))}
        </div>
      )}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-2" data-testid="rc-kpis">
        <Kpi label="На кошельках проекта" value={ton(r.assets.total_ton)} sub={`кошельков: ${r.assets.wallets.length}`} />
        <Kpi label="Должны игрокам" value={ton(r.liabilities.total_ton)}
          sub={`реальные балансы ${ton(r.liabilities.real_balances_ton)} + выводы в очереди ${ton(r.liabilities.pending_withdrawals_ton)}`} />
        <Kpi label="Покрытие" value={ton(cov)} tone={cov == null ? 'text-white' : cov >= 0 ? 'text-emerald-400' : 'text-red-400'}
          sub="кошельки − обязательства" />
        <Kpi label="Бонусные балансы" value={ton(r.liabilities.bonus_balances_ton)} sub="не выводятся, в покрытие не входят" />
      </div>

      {[
        { title: 'Выводы, требующие проверки (выплата могла уйти)', rows: rv.withdrawals_needs_review, kind: 'withdrawals', id: 'rc-review',
          actions: [['confirm', 'Выплата ушла — подтвердить', 'Подтвердить: выплата ДОШЛА до игрока (проверено в блокчейне)? Денег игроку не вернётся.'],
                    ['refund', 'Не ушла — вернуть на баланс', 'Вернуть сумму на баланс игрока? Делайте это, только если в блокчейне выплаты НЕТ.']] },
        { title: `Выводы, зависшие в обработке (дольше 15 мин)`, rows: rv.withdrawals_processing, kind: 'withdrawals', id: 'rc-processing',
          actions: [['confirm', 'Выплата ушла — подтвердить', 'Подтвердить, что выплата дошла (проверено в блокчейне)?'],
                    ['refund', 'Не ушла — вернуть на баланс', 'Вернуть сумму на баланс игрока? Только если выплаты в блокчейне нет.']] },
        { title: 'Пополнения, зачисление которых не завершилось', rows: rv.deposits_crediting, kind: 'deposits', id: 'rc-crediting',
          actions: [['credit', 'Зачислить', 'Зачислить пополнение на баланс игрока? (проверьте, что баланс ещё не увеличен)'],
                    ['dismiss', 'Отклонить', 'Отклонить без зачисления?']] },
      ].map((sec) => (
        <Card key={sec.id} className="glass-panel border-white/10">
          <CardHeader className="pb-2"><CardTitle className="text-sm">{sec.title} · {sec.rows.length}</CardTitle></CardHeader>
          <CardContent className="overflow-x-auto">
            <table className="w-full text-xs" data-testid={sec.id}>
              <thead><tr className="text-text-muted text-left">
                <th className="py-1 pr-3">Когда</th><th className="py-1 pr-3">Игрок</th><th className="py-1 pr-3">Сумма</th>
                <th className="py-1 pr-3">Транзакция</th><th className="py-1 pr-3">Причина</th><th className="py-1 pr-3" />
              </tr></thead>
              <tbody>
                {sec.rows.map((x) => {
                  const h = x.blockchain_hash || x.tx_hash;
                  return (
                    <tr key={x.id} className="border-t border-white/5 align-top">
                      <td className="py-1 pr-3">{when(x.needs_review_at || x.processing_started || x.created_at)}</td>
                      <td className="py-1 pr-3">{x.user_id || '—'}</td>
                      <td className="py-1 pr-3">{ton(x.amount_ton ?? x.amount)}</td>
                      <td className="py-1 pr-3">{h ? <a href={txLink(h)} target="_blank" rel="noreferrer" className="text-cyber-cyan inline-flex items-center gap-1">{h.slice(0, 10)}…<ExternalLink className="w-3 h-3" /></a> : '—'}</td>
                      <td className="py-1 pr-3 max-w-[240px] text-text-muted">{x.error || x.status}</td>
                      <td className="py-1 pr-3 whitespace-nowrap">
                        {sec.actions.map(([a, label, confirmText]) => (
                          <Button key={a} size="sm" variant="outline" className="h-7 text-[11px] mr-1" disabled={busy}
                            onClick={() => act(sec.kind, x.id, a, confirmText)} data-testid={`rc-${a}-${x.id}`}>{label}</Button>
                        ))}
                      </td>
                    </tr>
                  );
                })}
                {!sec.rows.length && <tr><td colSpan={6} className="py-2 text-text-muted">Нет.</td></tr>}
              </tbody>
            </table>
          </CardContent>
        </Card>
      ))}

      <Card className="glass-panel border-white/10">
        <CardHeader className="pb-2"><CardTitle className="text-sm">Кошельки проекта и порог</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="text-xs space-y-1">
            {r.assets.wallets.map((w) => (
              <div key={w.address} className="flex justify-between gap-2"><span className="font-mono truncate">{w.address}</span><span>{ton(w.balance_ton)}</span></div>
            ))}
          </div>
          <label className="text-xs space-y-1 block">
            <span className="text-text-muted">Дополнительные адреса кошельков проекта (по одному в строке; адреса приёма платежей и кошельки распределения подтягиваются сами)</span>
            <textarea value={wallets} onChange={(e) => setWallets(e.target.value)} rows={3}
              className="w-full rounded-md bg-black/40 border border-white/10 p-2 font-mono text-xs text-white" data-testid="rc-wallets" />
          </label>
          <label className="text-xs space-y-1 block max-w-xs">
            <span className="text-text-muted">Предупреждать, если покрытие ниже (TON)</span>
            <Input type="number" step="0.1" value={threshold} onChange={(e) => setThreshold(e.target.value)} className="bg-black/40 border-white/10 h-9" />
          </label>
          <Button size="sm" disabled={busy} onClick={saveSettings}>Сохранить</Button>
        </CardContent>
      </Card>

      {r.history?.length > 0 && (
        <Card className="glass-panel border-white/10">
          <CardHeader className="pb-2"><CardTitle className="text-sm">Последние ежедневные проверки</CardTitle></CardHeader>
          <CardContent className="text-xs space-y-1">
            {r.history.map((h) => (
              <div key={h.at} className="flex justify-between gap-2"><span>{when(h.at)}</span><span>покрытие {ton(h.coverage_ton)} · замечаний: {(h.alerts || []).length}</span></div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
