import { useState, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { toast } from '@/components/ui/sonner';
import { Sparkles, Play, StopCircle, CheckCircle2, Clock, Trophy, RefreshCw, Send, Pencil, Search, X, Save, RotateCcw } from 'lucide-react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api/admin`;

function iso(dt) {
  try { return new Date(dt).toLocaleString('ru-RU', { timeZone: 'Europe/Moscow' }); }
  catch { return dt; }
}

function toIsoMskFromLocal(dtLocal) {
  // dtLocal is "YYYY-MM-DDTHH:mm" from <input type=datetime-local>, interpreted as MSK
  if (!dtLocal) return '';
  // Append +03:00 as the fixed MSK offset.
  return `${dtLocal}:00+03:00`;
}

export default function AdminPromoRally() {
  const [current, setCurrent] = useState(null);
  const [top10, setTop10] = useState([]);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);

  // start form
  const [endsAtLocal, setEndsAtLocal] = useState('');
  const [prize1, setPrize1] = useState(100);
  const [prize2, setPrize2] = useState(50);
  const [prize3, setPrize3] = useState(20);
  const [perActive, setPerActive] = useState(1.5);
  const [starting, setStarting] = useState(false);

  // broadcast confirmation modal
  const [broadcastPreview, setBroadcastPreview] = useState(null);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [broadcasting, setBroadcasting] = useState(false);

  // Referral override modal (admin: force set active/total referrals for a user)
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [overrideQuery, setOverrideQuery] = useState('');
  const [overrideSearching, setOverrideSearching] = useState(false);
  const [overrideResults, setOverrideResults] = useState([]);
  const [overrideSelected, setOverrideSelected] = useState(null);
  const [overrideActive, setOverrideActive] = useState('');
  const [overrideTotal, setOverrideTotal] = useState('');
  const [overrideSaving, setOverrideSaving] = useState(false);

  const token = () => localStorage.getItem('token');

  const fetchAll = useCallback(async () => {
    const t = token();
    if (!t) return;
    setLoading(true);
    try {
      const [curRes, histRes] = await Promise.all([
        fetch(`${API}/promo/referral-rally/current`, { headers: { Authorization: `Bearer ${t}` } }),
        fetch(`${API}/promo/referral-rally/history`, { headers: { Authorization: `Bearer ${t}` } }),
      ]);
      const cur = await curRes.json();
      const hist = await histRes.json();
      setCurrent(cur?.campaign || null);
      setTop10(cur?.top10 || []);
      setHistory(hist?.campaigns || []);
    } catch (e) {
      // silent
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  useEffect(() => {
    // Auto-refresh top10 every 60s if campaign is active
    if (!current) return;
    const iv = setInterval(fetchAll, 60 * 1000);
    return () => clearInterval(iv);
  }, [current, fetchAll]);

  const handleStart = async () => {
    if (!endsAtLocal) {
      toast.error('Укажите дату окончания');
      return;
    }
    setStarting(true);
    try {
      const res = await fetch(`${API}/promo/referral-rally/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token()}` },
        body: JSON.stringify({
          ends_at: toIsoMskFromLocal(endsAtLocal),
          prizes_ton: [Number(prize1), Number(prize2), Number(prize3)],
          per_active_ton: Number(perActive),
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        toast.error(data.detail || 'Ошибка запуска');
      } else {
        toast.success('Акция запущена. Первое TG-уведомление отправляется всем...');
        fetchAll();
      }
    } catch (e) {
      toast.error('Сеть недоступна');
    } finally {
      setStarting(false);
    }
  };

  const handleStop = async () => {
    if (!window.confirm('Остановить акцию БЕЗ фиксации победителей? Всё UI-состояние у пользователей пропадёт.')) return;
    try {
      const res = await fetch(`${API}/promo/referral-rally/stop`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token()}` },
      });
      if (res.ok) { toast.success('Акция остановлена'); fetchAll(); }
      else { toast.error('Ошибка'); }
    } catch (e) { toast.error('Сеть недоступна'); }
  };

  const handleFinalize = async () => {
    if (!window.confirm('Зафиксировать результат СЕЙЧАС? Победители получат приз (админ выплачивает вручную).')) return;
    try {
      const res = await fetch(`${API}/promo/referral-rally/finalize`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token()}` },
      });
      if (res.ok) { toast.success('Победители зафиксированы'); fetchAll(); }
      else { toast.error('Ошибка'); }
    } catch (e) { toast.error('Сеть недоступна'); }
  };

  const togglePaid = async (userId) => {
    try {
      const res = await fetch(`${API}/promo/referral-rally/winners/${userId}/toggle-paid`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token()}` },
      });
      if (res.ok) { fetchAll(); }
    } catch (e) { toast.error('Ошибка'); }
  };

  const openBroadcast = async () => {
    setLoadingPreview(true);
    try {
      const res = await fetch(`${API}/promo/referral-rally/broadcast-preview`, {
        headers: { Authorization: `Bearer ${token()}` },
      });
      const data = await res.json();
      if (!res.ok) { toast.error(data.detail || 'Не удалось получить предпросмотр'); return; }
      setBroadcastPreview(data.preview);
    } catch (e) { toast.error('Сеть недоступна'); }
    finally { setLoadingPreview(false); }
  };

  const confirmBroadcast = async () => {
    setBroadcasting(true);
    try {
      const res = await fetch(`${API}/promo/referral-rally/broadcast`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token()}` },
      });
      const data = await res.json();
      if (!res.ok) { toast.error(data.detail || 'Ошибка рассылки'); return; }
      toast.success(`Рассылка запущена (подписчиков: ${data.subscribers ?? 0})`);
      setBroadcastPreview(null);
    } catch (e) { toast.error('Сеть недоступна'); }
    finally { setBroadcasting(false); }
  };

  const previewHtml = (txt) => ({ __html: String(txt || '').replace(/\n/g, '<br/>') });

  // ==================== Referral override ====================

  const openOverride = () => {
    setOverrideOpen(true);
    setOverrideQuery('');
    setOverrideResults([]);
    setOverrideSelected(null);
    setOverrideActive('');
    setOverrideTotal('');
  };

  const searchOverrideUsers = async () => {
    const q = overrideQuery.trim();
    if (!q) { toast.error('Введите имя, email или ID'); return; }
    setOverrideSearching(true);
    try {
      const res = await fetch(
        `${API}/referrals/search-users?q=${encodeURIComponent(q)}&limit=20`,
        { headers: { Authorization: `Bearer ${token()}` } },
      );
      const data = await res.json();
      if (!res.ok) { toast.error(data.detail || 'Ошибка поиска'); return; }
      setOverrideResults(data.results || []);
      if ((data.results || []).length === 0) toast.info('Пользователи не найдены');
    } catch (e) { toast.error('Сеть недоступна'); }
    finally { setOverrideSearching(false); }
  };

  const pickOverrideUser = (u) => {
    setOverrideSelected(u);
    setOverrideActive(String(u.override_active ?? u.active ?? 0));
    setOverrideTotal(String(u.override_total ?? u.total ?? 0));
  };

  const saveOverride = async () => {
    if (!overrideSelected) return;
    const a = Number(overrideActive);
    const t = Number(overrideTotal);
    if (!Number.isFinite(a) || !Number.isFinite(t) || a < 0 || t < 0) {
      toast.error('Введите неотрицательные целые числа');
      return;
    }
    if (a > t) { toast.error('Активных не может быть больше, чем всего'); return; }
    setOverrideSaving(true);
    try {
      const res = await fetch(`${API}/referrals/override`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token()}` },
        body: JSON.stringify({
          user_id: overrideSelected.user_id,
          active: Math.floor(a),
          total: Math.floor(t),
        }),
      });
      const data = await res.json();
      if (!res.ok) { toast.error(data.detail || 'Ошибка сохранения'); return; }
      toast.success(`Данные обновлены для @${data.username || ''}`);
      setOverrideOpen(false);
      fetchAll();
    } catch (e) { toast.error('Сеть недоступна'); }
    finally { setOverrideSaving(false); }
  };

  const clearOverride = async () => {
    if (!overrideSelected) return;
    if (!window.confirm('Сбросить админ-переопределение и вернуть реальные значения?')) return;
    setOverrideSaving(true);
    try {
      const res = await fetch(`${API}/referrals/override/clear`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token()}` },
        body: JSON.stringify({ user_id: overrideSelected.user_id }),
      });
      const data = await res.json();
      if (!res.ok) { toast.error(data.detail || 'Ошибка'); return; }
      toast.success('Переопределение сброшено');
      setOverrideOpen(false);
      fetchAll();
    } catch (e) { toast.error('Сеть недоступна'); }
    finally { setOverrideSaving(false); }
  };

  if (loading) {
    return (
      <div className="glass-panel rounded-xl p-6 border border-white/10">
        <div className="flex items-center gap-2 text-text-muted"><RefreshCw className="w-4 h-4 animate-spin"/>Загрузка...</div>
      </div>
    );
  }

  const finishedCampaigns = history.filter(c => c.status === 'finished');

  return (
    <div className="glass-panel rounded-xl border border-pink-500/30" data-testid="admin-promo-rally-card">
      <div className="p-4 border-b border-white/10 flex items-center gap-2">
        <Sparkles className="w-5 h-5 text-pink-400" />
        <h3 className="font-unbounded text-base font-bold text-white">Акция «Рефералы»</h3>
      </div>

      <div className="p-4">
        {/* CURRENT STATE */}
        {current ? (
          <div className="space-y-4" data-testid="rally-active-panel">
            <div className="bg-pink-500/10 border border-pink-500/30 rounded-xl p-3">
              <div className="flex items-center justify-between mb-2">
                <div className="text-pink-300 font-bold flex items-center gap-2">
                  <Clock className="w-4 h-4" /> Акция идёт
                </div>
                <div className="text-xs text-text-muted">
                  Заканчивается: <span className="text-white font-mono">{iso(current.ends_at)}</span>
                </div>
              </div>
              <div className="text-xs text-text-muted">
                Призы: <span className="text-yellow-300 font-mono">{current.config.prizes_ton.join(' / ')} TON</span> ·
                за активного: <span className="text-yellow-300 font-mono ml-1">{current.config.per_active_ton} TON</span>
              </div>
            </div>

            {/* Top 10 leaderboard */}
            <div>
              <div className="text-xs uppercase tracking-wider text-text-muted mb-2">Текущий ТОП-10</div>
              {(() => {
                // Only rank users with at least one ACTIVE referral. Empty
                // "0 / N" rows are misleading pre-activation — the admin
                // asked for the leaderboard to reflect active referrals
                // only, and to fall back to a clear "no active refs yet"
                // notice when nobody has activated anyone.
                const activeTop = (top10 || [])
                  .map(r => ({ ...r, active: Number(r.active || 0), total: Number(r.total || 0) }))
                  .filter(r => r.active > 0)
                  .sort((a, b) => (b.active - a.active) || (b.total - a.total));
                if (activeTop.length === 0) {
                  return (
                    <div
                      className="bg-white/5 border border-white/10 rounded-lg px-3 py-3 text-sm text-text-muted text-center"
                      data-testid="rally-no-active-refs"
                    >
                      К сожалению, на данный момент нет активных рефералов!
                    </div>
                  );
                }
                return (
                  <div className="space-y-1">
                    {activeTop.map((r, i) => (
                      <div key={r.user_id} className="flex items-center justify-between bg-white/5 rounded-lg px-3 py-2">
                        <div className="flex items-center gap-2 min-w-0">
                          <span className="text-sm font-mono text-text-muted w-6">#{i + 1}</span>
                          <span className="text-white font-medium text-sm truncate">@{r.username || '—'}</span>
                        </div>
                        <div className="text-right text-xs font-mono">
                          <span className="text-green-300 font-bold">{r.active}</span>
                          <span className="text-text-muted"> / {r.total}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                );
              })()}
            </div>

            {/* Controls */}
            <div className="flex flex-wrap gap-2 pt-2 border-t border-white/10">
              <Button onClick={openBroadcast} disabled={loadingPreview}
                className="bg-pink-500 hover:bg-pink-400 text-white font-bold" data-testid="broadcast-referral-rally-btn">
                <Send className="w-4 h-4 mr-1" /> {loadingPreview ? 'Загрузка...' : 'Разослать'}
              </Button>
              <Button onClick={openOverride}
                className="bg-indigo-500 hover:bg-indigo-400 text-white font-bold"
                data-testid="edit-referral-data-btn">
                <Pencil className="w-4 h-4 mr-1" /> Изменить данные
              </Button>
              <Button onClick={handleFinalize} className="bg-yellow-500 hover:bg-yellow-400 text-black font-bold" data-testid="finalize-referral-rally-btn">
                <CheckCircle2 className="w-4 h-4 mr-1" /> Зафиксировать сейчас
              </Button>
              <Button onClick={handleStop} variant="outline" className="border-red-500/40 text-red-300 hover:bg-red-500/10" data-testid="stop-referral-rally-btn">
                <StopCircle className="w-4 h-4 mr-1" /> Остановить (без победителей)
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-3" data-testid="rally-start-panel">
            <div className="text-sm text-text-muted mb-2">Нет активной акции. Настройте параметры и запустите:</div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-text-muted">Дата окончания (МСК)</label>
                <Input
                  type="datetime-local"
                  value={endsAtLocal}
                  onChange={(e) => setEndsAtLocal(e.target.value)}
                  className="bg-white/5 border-white/10 text-white"
                  data-testid="rally-ends-at-input"
                />
              </div>
              <div>
                <label className="text-xs text-text-muted">Бонус за активного, TON</label>
                <Input type="number" step="0.1" value={perActive} onChange={(e) => setPerActive(e.target.value)}
                  className="bg-white/5 border-white/10 text-white" data-testid="rally-per-active-input" />
              </div>
              <div>
                <label className="text-xs text-text-muted">🥇 1 место, TON</label>
                <Input type="number" step="1" value={prize1} onChange={(e) => setPrize1(e.target.value)}
                  className="bg-white/5 border-white/10 text-white" data-testid="rally-prize1-input" />
              </div>
              <div>
                <label className="text-xs text-text-muted">🥈 2 место, TON</label>
                <Input type="number" step="1" value={prize2} onChange={(e) => setPrize2(e.target.value)}
                  className="bg-white/5 border-white/10 text-white" data-testid="rally-prize2-input" />
              </div>
              <div>
                <label className="text-xs text-text-muted">🥉 3 место, TON</label>
                <Input type="number" step="1" value={prize3} onChange={(e) => setPrize3(e.target.value)}
                  className="bg-white/5 border-white/10 text-white" data-testid="rally-prize3-input" />
              </div>
            </div>
            <Button onClick={handleStart} disabled={starting}
              className="bg-pink-500 hover:bg-pink-400 text-white font-bold w-full sm:w-auto"
              data-testid="start-referral-rally-btn">
              <Play className="w-4 h-4 mr-1" /> {starting ? 'Запуск...' : 'Включить акцию'}
            </Button>
            <div className="pt-2 border-t border-white/10">
              <Button onClick={openOverride}
                className="bg-indigo-500 hover:bg-indigo-400 text-white font-bold"
                data-testid="edit-referral-data-btn-inactive">
                <Pencil className="w-4 h-4 mr-1" /> Изменить данные рефералов
              </Button>
            </div>
          </div>
        )}

        {/* HISTORY / RESULTS */}
        {finishedCampaigns.length > 0 && (
          <div className="mt-6 pt-4 border-t border-white/10" data-testid="rally-history">
            <div className="text-xs uppercase tracking-wider text-text-muted mb-3 flex items-center gap-1">
              <Trophy className="w-3.5 h-3.5" /> История результатов
            </div>
            <Tabs defaultValue={finishedCampaigns[0].id}>
              <TabsList className="bg-white/5 border border-white/10 flex-wrap h-auto">
                {finishedCampaigns.slice(0, 10).map((c) => (
                  <TabsTrigger key={c.id} value={c.id} className="text-xs">
                    {iso(c.frozen_at || c.ends_at)}
                  </TabsTrigger>
                ))}
              </TabsList>
              {finishedCampaigns.slice(0, 10).map((c) => (
                <TabsContent key={c.id} value={c.id} className="mt-3">
                  <div className="space-y-2">
                    {(c.winners || []).map((w) => (
                      <div key={`${c.id}-${w.rank}`} className="flex items-center justify-between bg-white/5 rounded-lg px-3 py-2">
                        <div className="flex items-center gap-2 min-w-0">
                          <span className="text-xl">{w.rank === 1 ? '🥇' : w.rank === 2 ? '🥈' : '🥉'}</span>
                          <span className="text-white font-medium truncate">@{w.username || '—'}</span>
                          <span className="text-xs text-text-muted font-mono">({w.active_count} / {w.total_count} реф.)</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="text-yellow-300 font-mono font-bold">{w.prize_ton} TON</span>
                          <Button
                            size="sm"
                            variant={w.paid ? 'default' : 'outline'}
                            onClick={() => togglePaid(w.user_id)}
                            className={w.paid ? 'bg-green-500 hover:bg-green-400 text-black' : 'border-white/20 text-white'}
                            data-testid={`rally-paid-${c.id}-${w.rank}`}
                          >
                            {w.paid ? '✅ Выплачено' : '⏳ Ожидает'}
                          </Button>
                        </div>
                      </div>
                    ))}
                    {(c.winners || []).length === 0 && <div className="text-text-muted text-sm">Победителей нет</div>}
                  </div>
                </TabsContent>
              ))}
            </Tabs>
          </div>
        )}
      </div>

      {/* Broadcast confirmation modal */}
      {broadcastPreview && createPortal(
        <div
          className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/70 p-4"
          data-testid="broadcast-confirm-modal"
        >
          <div className="glass-panel w-full max-w-lg rounded-2xl border border-pink-500/40 bg-[#12101a] max-h-[85vh] overflow-hidden flex flex-col">
            <div className="p-4 border-b border-white/10 flex items-center gap-2">
              <Send className="w-5 h-5 text-pink-400" />
              <h3 className="font-unbounded text-base font-bold text-white">Разослать уведомление?</h3>
            </div>
            <div className="p-4 overflow-y-auto">
              <div className="text-xs text-text-muted mb-3">
                Будет отправлено всем подписчикам бота:{' '}
                <span className="text-white font-mono">{broadcastPreview.subscriber_count ?? 0}</span>.
                Сортировка призёров:{' '}
                <span className="text-white">{broadcastPreview.sort === 'total' ? 'по количеству' : 'по активным'}</span>.
              </div>
              {broadcastPreview.banner_url && (
                <img
                  src={broadcastPreview.banner_url}
                  alt="banner"
                  className="w-full rounded-lg mb-3 border border-white/10"
                  onError={(e) => { e.currentTarget.style.display = 'none'; }}
                />
              )}
              <div
                className="text-sm text-white/90 leading-relaxed bg-white/5 rounded-lg p-3 border border-white/10 whitespace-pre-wrap"
                data-testid="broadcast-preview-text"
                dangerouslySetInnerHTML={previewHtml(broadcastPreview.text)}
              />
            </div>
            <div className="p-4 border-t border-white/10 flex justify-end gap-2">
              <Button
                variant="outline"
                onClick={() => setBroadcastPreview(null)}
                disabled={broadcasting}
                className="border-white/20 text-white hover:bg-white/10"
                data-testid="broadcast-decline-btn"
              >
                Отклонить
              </Button>
              <Button
                onClick={confirmBroadcast}
                disabled={broadcasting}
                className="bg-pink-500 hover:bg-pink-400 text-white font-bold"
                data-testid="broadcast-confirm-btn"
              >
                <Send className="w-4 h-4 mr-1" /> {broadcasting ? 'Рассылка...' : 'Разослать'}
              </Button>
            </div>
          </div>
        </div>,
        document.body
      )}

      {/* Referral override modal */}
      {overrideOpen && createPortal(
        <div
          className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/70 p-4"
          data-testid="referral-override-modal"
        >
          <div className="glass-panel w-full max-w-2xl rounded-2xl border border-indigo-500/40 bg-[#12101a] max-h-[90vh] overflow-hidden flex flex-col">
            <div className="p-4 border-b border-white/10 flex items-center gap-2 justify-between">
              <div className="flex items-center gap-2">
                <Pencil className="w-5 h-5 text-indigo-400" />
                <h3 className="font-unbounded text-base font-bold text-white">Изменить данные рефералов</h3>
              </div>
              <button
                onClick={() => setOverrideOpen(false)}
                className="text-text-muted hover:text-white transition"
                data-testid="referral-override-close-btn"
                aria-label="Закрыть"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-4 overflow-y-auto space-y-4">
              {/* Search */}
              <div>
                <label className="text-xs text-text-muted">Имя, email или ID пользователя</label>
                <div className="flex gap-2 mt-1">
                  <Input
                    value={overrideQuery}
                    onChange={(e) => setOverrideQuery(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); searchOverrideUsers(); } }}
                    placeholder="напр. sanya, mail@x, uuid-..."
                    className="bg-white/5 border-white/10 text-white flex-1"
                    data-testid="referral-override-query-input"
                  />
                  <Button
                    onClick={searchOverrideUsers}
                    disabled={overrideSearching}
                    className="bg-indigo-500 hover:bg-indigo-400 text-white font-bold"
                    data-testid="referral-override-search-btn"
                  >
                    <Search className="w-4 h-4 mr-1" /> {overrideSearching ? 'Поиск...' : 'Найти'}
                  </Button>
                </div>
              </div>

              {/* Results */}
              {overrideResults.length > 0 && (
                <div className="space-y-1 max-h-56 overflow-y-auto pr-1" data-testid="referral-override-results">
                  {overrideResults.map((u) => {
                    const selected = overrideSelected && overrideSelected.user_id === u.user_id;
                    return (
                      <button
                        key={u.user_id}
                        onClick={() => pickOverrideUser(u)}
                        className={`w-full text-left flex items-center justify-between rounded-lg px-3 py-2 border transition ${
                          selected
                            ? 'bg-indigo-500/20 border-indigo-400/60'
                            : 'bg-white/5 border-white/10 hover:bg-white/10'
                        }`}
                        data-testid={`referral-override-result-${u.user_id}`}
                      >
                        <div className="flex items-center gap-2 min-w-0">
                          {u.avatar && (
                            <img src={u.avatar} alt="" className="w-8 h-8 rounded-full border border-white/10" />
                          )}
                          <div className="min-w-0">
                            <div className="text-white text-sm font-medium truncate">@{u.username || '—'}</div>
                            <div className="text-text-muted text-xs truncate">{u.email || u.user_id}</div>
                          </div>
                        </div>
                        <div className="text-right text-xs font-mono shrink-0">
                          <div>
                            <span className="text-green-300 font-bold">{u.active}</span>
                            <span className="text-text-muted"> / {u.total}</span>
                          </div>
                          {(u.override_active !== null && u.override_active !== undefined) && (
                            <div className="text-indigo-300 text-[10px] mt-0.5">override</div>
                          )}
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}

              {/* Edit form */}
              {overrideSelected && (
                <div className="bg-white/5 border border-indigo-500/30 rounded-xl p-3 space-y-3" data-testid="referral-override-form">
                  <div className="text-sm text-white">
                    Пользователь: <span className="font-bold">@{overrideSelected.username || '—'}</span>{' '}
                    <span className="text-text-muted text-xs">({overrideSelected.email || overrideSelected.user_id})</span>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="text-xs text-text-muted">Активных рефералов</label>
                      <Input
                        type="number"
                        min="0"
                        step="1"
                        value={overrideActive}
                        onChange={(e) => setOverrideActive(e.target.value)}
                        className="bg-white/5 border-white/10 text-white"
                        data-testid="referral-override-active-input"
                      />
                    </div>
                    <div>
                      <label className="text-xs text-text-muted">Всего рефералов</label>
                      <Input
                        type="number"
                        min="0"
                        step="1"
                        value={overrideTotal}
                        onChange={(e) => setOverrideTotal(e.target.value)}
                        className="bg-white/5 border-white/10 text-white"
                        data-testid="referral-override-total-input"
                      />
                    </div>
                  </div>
                  <div className="text-xs text-text-muted">
                    Эти значения ПЕРЕЗАПИШУТ реальные данные пользователя во всём приложении:
                    админ-топ, рейтинг рефералов, top-3 в рассылке, фиксация призёров.
                    Сохраняются в поля <code>referral_override_active</code> / <code>referral_override_total</code>{' '}
                    в коллекции <code>users</code> MongoDB.
                  </div>
                </div>
              )}
            </div>

            <div className="p-4 border-t border-white/10 flex justify-between gap-2 flex-wrap">
              <Button
                onClick={clearOverride}
                disabled={!overrideSelected || overrideSaving}
                variant="outline"
                className="border-red-500/40 text-red-300 hover:bg-red-500/10"
                data-testid="referral-override-clear-btn"
              >
                <RotateCcw className="w-4 h-4 mr-1" /> Сбросить override
              </Button>
              <div className="flex gap-2 ml-auto">
                <Button
                  variant="outline"
                  onClick={() => setOverrideOpen(false)}
                  disabled={overrideSaving}
                  className="border-white/20 text-white hover:bg-white/10"
                  data-testid="referral-override-cancel-btn"
                >
                  Отмена
                </Button>
                <Button
                  onClick={saveOverride}
                  disabled={!overrideSelected || overrideSaving}
                  className="bg-indigo-500 hover:bg-indigo-400 text-white font-bold"
                  data-testid="referral-override-save-btn"
                >
                  <Save className="w-4 h-4 mr-1" /> {overrideSaving ? 'Сохраняем...' : 'Сохранить'}
                </Button>
              </div>
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  );
}
