import { useState, useEffect, useMemo, useCallback } from 'react';
import { Search, Zap, RefreshCw, Eye, X, ShieldCheck, Loader2, Package, Store } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { toast } from 'sonner';
import axios from 'axios';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const fmtCity = (n) => Number(n || 0).toLocaleString('ru-RU', { maximumFractionDigits: 2 });

export default function BuyoutPanel({ token }) {
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);

  const [loading, setLoading] = useState(false);
  const [data, setData] = useState({ stats: {}, rows: [] });
  const [resourceCatalog, setResourceCatalog] = useState({});
  const [nicks, setNicks] = useState([]);

  // filters
  const [search, setSearch] = useState('');
  const [resource, setResource] = useState('all');
  const [status, setStatus] = useState('with_lots');
  const [sort, setSort] = useState('units_desc');

  // per-LOT selection & amounts (keyed by listing_id) — admin chooses which lot/resource to buy
  const [lotSel, setLotSel] = useState({});   // {listing_id: true}
  const [lotAmt, setLotAmt] = useState({});    // {listing_id: number}

  // modals
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [maskMode, setMaskMode] = useState('auto');
  const [botUsername, setBotUsername] = useState('');
  const [executing, setExecuting] = useState(false);
  const [logsFor, setLogsFor] = useState(null);
  const [result, setResult] = useState(null);

  // Подразделы: 'buyout' (выкуп) | 'trades' (торги — модерация объявлений)
  const [view, setView] = useState('buyout');
  const [tradeRows, setTradeRows] = useState([]);
  const [tradeLoading, setTradeLoading] = useState(false);
  const [tradeResource, setTradeResource] = useState('all');
  const [tradeSearch, setTradeSearch] = useState('');
  const [deletingId, setDeletingId] = useState(null);

  const loadTrades = useCallback(async () => {
    setTradeLoading(true);
    try {
      const params = new URLSearchParams({ resource: tradeResource, search: tradeSearch });
      const res = await axios.get(`${API}/admin/market/all-listings?${params}`, { headers });
      setTradeRows(res.data?.listings || []);
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Ошибка загрузки торгов');
    } finally {
      setTradeLoading(false);
    }
  }, [headers, tradeResource, tradeSearch]);

  useEffect(() => { if (view === 'trades') loadTrades(); }, [view, loadTrades]);

  const deleteListing = async (listing_id) => {
    if (!window.confirm('Удалить объявление с торговли? Ресурсы вернутся продавцу на склад.')) return;
    setDeletingId(listing_id);
    try {
      const res = await axios.delete(`${API}/admin/market/listing/${listing_id}`, { headers });
      toast.success(`Объявление удалено, возвращено ${res.data?.returned?.amount || 0} ед. продавцу`);
      setTradeRows((prev) => prev.filter((r) => r.listing_id !== listing_id));
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Не удалось удалить объявление');
    } finally {
      setDeletingId(null);
    }
  };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ search, resource, status, sort });
      const res = await axios.get(`${API}/admin/buyout/overview?${params}`, { headers });
      setData(res.data || { stats: {}, rows: [] });
      // default per-lot buy amount = full lot amount; reset selection
      const nextAmt = {};
      (res.data?.rows || []).forEach((r) => (r.lots || []).forEach((l) => { nextAmt[l.listing_id] = l.amount; }));
      setLotAmt(nextAmt);
      setLotSel({});
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Ошибка загрузки выкупа');
    } finally {
      setLoading(false);
    }
  }, [headers, search, resource, status, sort]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    axios.get(`${API}/economy/config`)
      .then((r) => setResourceCatalog(r.data?.resource_types || r.data?.resources || {}))
      .catch(() => setResourceCatalog({}));
    axios.get(`${API}/admin/buyout/nicks`, { headers })
      .then((r) => { setNicks(r.data?.nicks || []); if (r.data?.nicks?.length) setBotUsername(r.data.nicks[0]); })
      .catch(() => setNicks([]));
  }, [headers]);

  const allLots = useMemo(() => data.rows.flatMap((r) => (r.lots || []).map((l) => ({ ...l, player_id: r.player_id }))), [data.rows]);
  const allSelected = allLots.length > 0 && allLots.every((l) => lotSel[l.listing_id]);
  const toggleSelectAll = (checked) => {
    const next = {};
    if (checked) allLots.forEach((l) => { next[l.listing_id] = true; });
    setLotSel(next);
  };

  const setAmount = (lid, val, max) => {
    let n = parseInt(val, 10);
    if (isNaN(n) || n < 0) n = 0;
    if (n > max) n = max;
    setLotAmt((prev) => ({ ...prev, [lid]: n }));
  };

  // Totals for the floating bar (only selected lots with a positive amount)
  const totals = useMemo(() => {
    let units = 0, cost = 0;
    const players = new Set();
    const payloadItems = [];
    for (const l of allLots) {
      if (!lotSel[l.listing_id]) continue;
      const amt = Math.min(Number(lotAmt[l.listing_id]) || 0, l.amount);
      if (amt > 0) {
        units += amt;
        cost += amt * l.price_per_unit_city;
        players.add(l.player_id);
        payloadItems.push({ listing_id: l.listing_id, amount: amt });
      }
    }
    return { people: players.size, units, cost, payloadItems };
  }, [allLots, lotSel, lotAmt]);

  const openConfirm = () => {
    if (totals.payloadItems.length === 0) { toast.error('Выберите лоты и укажите количество к выкупу'); return; }
    setConfirmOpen(true);
  };

  const doExecute = async () => {
    setExecuting(true);
    try {
      const body = { items: totals.payloadItems, mask_mode: maskMode, bot_username: maskMode === 'specific' ? botUsername : null };
      const res = await axios.post(`${API}/admin/buyout/execute`, body, { headers });
      setConfirmOpen(false);
      setResult(res.data);
      toast.success(`Выкуплено ${res.data.total_units} ед. на ${fmtCity(res.data.total_cost_city)} $CITY`);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Ошибка выкупа');
    } finally {
      setExecuting(false);
    }
  };

  const openLogs = async (row) => {
    try {
      const res = await axios.get(`${API}/admin/buyout/logs/${row.player_id}`, { headers });
      setLogsFor({ player: row, logs: res.data?.logs || [] });
    } catch (e) {
      toast.error('Не удалось загрузить логи');
    }
  };

  const whColor = (pct) => pct >= 100 ? 'text-red-400' : pct >= 70 ? 'text-amber-400' : 'text-emerald-400';
  const resourceOptions = useMemo(() => Object.entries(resourceCatalog).sort((a, b) => (a[1]?.tier || 1) - (b[1]?.tier || 1)), [resourceCatalog]);

  return (
    <div className="space-y-4 pb-28" data-testid="buyout-panel">
      {/* ── ПОДРАЗДЕЛЫ: Выкуп / Торги ─────────────────────── */}
      <div className="flex gap-2 border-b border-gray-800 pb-2">
        <button onClick={() => setView('buyout')} data-testid="buyout-subtab-buyout"
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${view === 'buyout' ? 'bg-amber-500/20 text-amber-400 border border-amber-500/50' : 'bg-gray-800/50 text-gray-400 border border-gray-700'}`}>
          ⚡ Выкуп
        </button>
        <button onClick={() => setView('trades')} data-testid="buyout-subtab-trades"
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${view === 'trades' ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/50' : 'bg-gray-800/50 text-gray-400 border border-gray-700'}`}>
          🛒 Торги
        </button>
      </div>

      {view === 'buyout' && (<>
      {/* ── ЗОНА 1: СТАТИСТИКА ─────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="p-4 rounded-xl bg-gray-900/60 border border-amber-500/30" data-testid="buyout-stat-businesses">
          <div className="text-xs text-gray-500 mb-1 flex items-center gap-1"><Store className="w-3.5 h-3.5" /> Всего бизнесов</div>
          <div className="text-2xl font-bold text-amber-300">{data.stats?.total_businesses ?? '—'}</div>
        </div>
        <div className="p-4 rounded-xl bg-gray-900/60 border border-cyan-500/30" data-testid="buyout-stat-units">
          <div className="text-xs text-gray-500 mb-1 flex items-center gap-1"><Package className="w-3.5 h-3.5" /> На рынке (ед.)</div>
          <div className="text-2xl font-bold text-cyan-300">{fmtCity(data.stats?.total_units_on_market)}</div>
        </div>
        <div className="p-4 rounded-xl bg-gray-900/60 border border-gray-700" data-testid="buyout-stat-owners">
          <div className="text-xs text-gray-500 mb-1">Показано владельцев</div>
          <div className="text-2xl font-bold text-white">{data.rows?.length ?? 0}</div>
        </div>
        <div className="p-4 rounded-xl bg-gray-900/60 border border-gray-700 flex items-center justify-center">
          <Button onClick={load} disabled={loading} variant="outline" size="sm" className="border-white/10" data-testid="buyout-refresh">
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4 mr-1" />} Обновить
          </Button>
        </div>
      </div>

      {/* ── ЗОНА 2: ФИЛЬТРЫ И РЕЖИМЫ ───────────────────────── */}
      <div className="rounded-xl border border-gray-700 bg-gray-900/40 p-3 space-y-3" data-testid="buyout-filters">
        <div className="flex flex-wrap gap-2 items-center">
          <div className="relative flex-1 min-w-[200px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
            <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Поиск: Username / ID"
              className="pl-10 bg-gray-900/50 border-gray-700 text-white h-9" data-testid="buyout-search" />
          </div>
          <select value={resource} onChange={(e) => setResource(e.target.value)}
            className="h-9 bg-gray-800 border border-gray-700 rounded-lg text-white text-sm px-2" data-testid="buyout-resource-filter">
            <option value="all">Ресурс: Все</option>
            {resourceOptions.map(([code, meta]) => (
              <option key={code} value={code}>{meta.icon || ''} {meta.name_ru || code} (T{meta.tier || 1})</option>
            ))}
          </select>
          <select value={status} onChange={(e) => setStatus(e.target.value)}
            className="h-9 bg-gray-800 border border-gray-700 rounded-lg text-white text-sm px-2" data-testid="buyout-status-filter">
            <option value="with_lots">Статус: только с активными лотами</option>
            <option value="all">Статус: показать всех владельцев</option>
          </select>
          <select value={sort} onChange={(e) => setSort(e.target.value)}
            className="h-9 bg-gray-800 border border-gray-700 rounded-lg text-white text-sm px-2" data-testid="buyout-sort">
            <option value="units_desc">Сортировка: по объёму лотов</option>
            <option value="warehouse_desc">по заполнению склада</option>
            <option value="buildings_desc">по числу зданий</option>
            <option value="username_asc">по имени (А-Я)</option>
          </select>
        </div>
        <div className="flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer">
            <input type="checkbox" checked={allSelected} onChange={(e) => toggleSelectAll(e.target.checked)}
              className="w-4 h-4 rounded" data-testid="buyout-select-all" />
            Выбрать все лоты
          </label>
          <Button size="sm" onClick={openConfirm} disabled={totals.payloadItems.length === 0}
            className="bg-amber-600 hover:bg-amber-700 h-8" data-testid="buyout-buy-selected-top">
            <Zap className="w-4 h-4 mr-1" /> Выкупить выделенное
          </Button>
        </div>
      </div>

      {/* ── ЗОНА 3: СМАРТ-ТАБЛИЦА (строка = отдельный лот) ──── */}
      <div className="overflow-x-auto rounded-xl border border-gray-700">
        <table className="w-full text-sm" data-testid="buyout-table">
          <thead>
            <tr className="bg-gray-900/80 text-gray-400 text-xs uppercase">
              <th className="px-2 py-2 w-8">
                <input type="checkbox" checked={allSelected} onChange={(e) => toggleSelectAll(e.target.checked)}
                  className="w-4 h-4 rounded" data-testid="buyout-header-checkbox" />
              </th>
              <th className="text-left px-3 py-2">Игрок</th>
              <th className="text-center px-3 py-2">Зданий</th>
              <th className="text-left px-3 py-2">Склад</th>
              <th className="text-left px-3 py-2">Лот на P2P</th>
              <th className="text-center px-3 py-2">К выкупу (ед.)</th>
              <th className="text-center px-3 py-2">Действия</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={7} className="text-center text-gray-500 py-8">Загрузка…</td></tr>
            ) : data.rows.length === 0 ? (
              <tr><td colSpan={7} className="text-center text-gray-500 py-8">Нет данных по фильтру</td></tr>
            ) : data.rows.map((row) => {
              const lots = row.lots || [];
              const span = Math.max(1, lots.length);
              const playerCell = (
                <>
                  <td className="px-3 py-2 align-top" rowSpan={span}>
                    <div className="text-white font-medium">@{row.username}</div>
                    <div className="text-[11px] text-gray-500 font-mono">{(row.player_id || '').slice(0, 10)}… · {fmtCity(row.balance_ton * 1000)} $CITY</div>
                  </td>
                  <td className="px-3 py-2 text-center text-white align-top" rowSpan={span}>{row.buildings}</td>
                  <td className="px-3 py-2 align-top" rowSpan={span}>
                    <span className="text-white">{row.warehouse_used} / {row.warehouse_capacity} ед.</span>
                    <span className={`ml-1 font-bold ${whColor(row.warehouse_pct)}`}>({row.warehouse_pct}%{row.warehouse_pct >= 100 ? '!' : ''})</span>
                  </td>
                </>
              );
              const actionCell = (
                <td className="px-3 py-2 text-center align-top" rowSpan={span}>
                  <button onClick={() => openLogs(row)} className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-xs bg-gray-800 text-gray-300 border border-gray-700 hover:bg-gray-700"
                    data-testid={`buyout-logs-${row.username}`}>
                    <Eye className="w-3 h-3" /> Логи
                  </button>
                </td>
              );

              if (lots.length === 0) {
                return (
                  <tr key={row.player_id} className="border-t border-gray-800 hover:bg-gray-800/30" data-testid={`buyout-row-${row.username}`}>
                    <td className="px-2 py-2 text-center"><input type="checkbox" disabled className="w-4 h-4 rounded opacity-30" /></td>
                    {playerCell}
                    <td className="px-3 py-2 text-gray-600">— (Нет лотов)</td>
                    <td className="px-3 py-2 text-center text-gray-600">—</td>
                    {actionCell}
                  </tr>
                );
              }

              return lots.map((lot, i) => (
                <tr key={lot.listing_id} className={`border-t border-gray-800 ${lotSel[lot.listing_id] ? 'bg-amber-500/5' : 'hover:bg-gray-800/30'}`}
                  data-testid={`buyout-row-${row.username}-${lot.resource_type}`}>
                  <td className="px-2 py-2 text-center align-top">
                    <input type="checkbox" checked={!!lotSel[lot.listing_id]}
                      onChange={(e) => setLotSel((prev) => ({ ...prev, [lot.listing_id]: e.target.checked }))}
                      className="w-4 h-4 rounded" data-testid={`buyout-checkbox-${row.username}-${lot.resource_type}`} />
                  </td>
                  {i === 0 && playerCell}
                  <td className="px-3 py-2">
                    <span className="text-gray-300">{lot.icon} {lot.amount} ед. {lot.resource_name}</span>
                    <span className="text-cyan-400"> ({fmtCity(lot.price_per_unit_city)} $CITY)</span>
                    <span className="ml-1 text-[10px] uppercase text-gray-500">T{lot.tier}</span>
                  </td>
                  <td className="px-3 py-2 text-center">
                    <Input type="number" min={0} max={lot.amount}
                      value={lotAmt[lot.listing_id] ?? 0}
                      onChange={(e) => setAmount(lot.listing_id, e.target.value, lot.amount)}
                      className="h-8 w-24 mx-auto bg-gray-800 border-gray-600 text-white text-center"
                      data-testid={`buyout-amount-${row.username}-${lot.resource_type}`} />
                  </td>
                  {i === 0 && actionCell}
                </tr>
              ));
            })}
          </tbody>
        </table>
      </div>

      {/* ── ПЛАВАЮЩАЯ ПЛАШКА ИТОГО ─────────────────────────── */}
      {totals.people > 0 && (
        <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-40 w-[min(96%,900px)]" data-testid="buyout-floating-bar">
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-amber-500/40 bg-gray-950/95 backdrop-blur px-4 py-3 shadow-2xl">
            <div className="text-sm text-gray-300 flex flex-wrap gap-x-4 gap-y-1">
              <span>Выбрано: <b className="text-white" data-testid="buyout-total-people">{totals.people}</b> чел.</span>
              <span>Ресурсов: <b className="text-cyan-300" data-testid="buyout-total-units">{fmtCity(totals.units)}</b> ед.</span>
              <span>Расход казны: <b className="text-amber-300" data-testid="buyout-total-cost">{fmtCity(totals.cost)}</b> $CITY</span>
            </div>
            <Button onClick={openConfirm} className="bg-amber-500 hover:bg-amber-600 text-black font-bold" data-testid="buyout-buy-btn">
              <Zap className="w-4 h-4 mr-1" /> ВЫКУПИТЬ
            </Button>
          </div>
        </div>
      )}
      </>)}

      {/* ── ПОДРАЗДЕЛ ТОРГИ: все объявления на продажу ресурсов ── */}
      {view === 'trades' && (
        <div className="space-y-3" data-testid="trades-panel">
          <div className="rounded-xl border border-gray-700 bg-gray-900/40 p-3 flex flex-wrap gap-2 items-center">
            <div className="relative flex-1 min-w-[200px]">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
              <Input value={tradeSearch} onChange={(e) => setTradeSearch(e.target.value)} placeholder="Поиск: продавец / ID"
                className="pl-10 bg-gray-900/50 border-gray-700 text-white h-9" data-testid="trades-search" />
            </div>
            <select value={tradeResource} onChange={(e) => setTradeResource(e.target.value)}
              className="h-9 bg-gray-800 border border-gray-700 rounded-lg text-white text-sm px-2" data-testid="trades-resource-filter">
              <option value="all">Ресурс: Все</option>
              {resourceOptions.map(([code, meta]) => (
                <option key={code} value={code}>{meta.icon || ''} {meta.name_ru || code} (T{meta.tier || 1})</option>
              ))}
            </select>
            <Button onClick={loadTrades} disabled={tradeLoading} variant="outline" size="sm" className="border-white/10" data-testid="trades-refresh">
              {tradeLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4 mr-1" />} Обновить
            </Button>
          </div>
          <div className="overflow-x-auto rounded-xl border border-gray-700">
            <table className="w-full text-sm" data-testid="trades-table">
              <thead>
                <tr className="bg-gray-900/80 text-gray-400 text-xs uppercase">
                  <th className="text-left px-3 py-2">Продавец</th>
                  <th className="text-left px-3 py-2">Ресурс</th>
                  <th className="text-center px-3 py-2">Кол-во</th>
                  <th className="text-center px-3 py-2">Цена/ед.</th>
                  <th className="text-center px-3 py-2">Сумма</th>
                  <th className="text-center px-3 py-2">Действия</th>
                </tr>
              </thead>
              <tbody>
                {tradeLoading ? (
                  <tr><td colSpan={6} className="text-center text-gray-500 py-8">Загрузка…</td></tr>
                ) : tradeRows.length === 0 ? (
                  <tr><td colSpan={6} className="text-center text-gray-500 py-8">Нет активных объявлений</td></tr>
                ) : tradeRows.map((row) => (
                  <tr key={row.listing_id} className="border-t border-gray-800 hover:bg-gray-800/30" data-testid={`trade-row-${row.listing_id}`}>
                    <td className="px-3 py-2">
                      <div className="text-white font-medium">@{row.seller_username || '—'}</div>
                      <div className="text-[11px] text-gray-500 font-mono">{(row.seller_id || '').slice(0, 10)}…</div>
                    </td>
                    <td className="px-3 py-2 text-gray-300">{row.icon} {row.resource_name} <span className="text-[10px] uppercase text-gray-500">T{row.tier}</span></td>
                    <td className="px-3 py-2 text-center text-white">{fmtCity(row.amount)} ед.</td>
                    <td className="px-3 py-2 text-center text-cyan-400">{fmtCity(row.price_per_unit_city)} $CITY</td>
                    <td className="px-3 py-2 text-center text-amber-300">{fmtCity(row.total_city)} $CITY</td>
                    <td className="px-3 py-2 text-center">
                      <button onClick={() => deleteListing(row.listing_id)} disabled={deletingId === row.listing_id}
                        className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-xs bg-red-600/20 text-red-300 border border-red-600/40 hover:bg-red-600/30 disabled:opacity-40"
                        data-testid={`trade-delete-${row.listing_id}`}>
                        {deletingId === row.listing_id ? <Loader2 className="w-3 h-3 animate-spin" /> : <X className="w-3 h-3" />} Удалить
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── МИКРО-МОДАЛКА ПОДТВЕРЖДЕНИЯ ────────────────────── */}
      {confirmOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" data-testid="buyout-confirm-modal">
          <div className="w-full max-w-md rounded-2xl border border-amber-500/40 bg-gray-950 p-5 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-bold text-white flex items-center gap-2"><ShieldCheck className="w-5 h-5 text-amber-400" /> Подтверждение скупки</h3>
              <button onClick={() => setConfirmOpen(false)} className="text-gray-400 hover:text-white"><X className="w-5 h-5" /></button>
            </div>
            <div className="rounded-xl bg-gray-900/60 border border-gray-700 p-3 text-sm space-y-1">
              <div className="text-gray-300">Будет выкуплено: <b className="text-cyan-300">{fmtCity(totals.units)}</b> ед. у <b className="text-white">{totals.people}</b> игроков</div>
              <div className="text-gray-300">Расход казны (сумма сделки): <b className="text-amber-300">{fmtCity(totals.cost)}</b> $CITY</div>
              <div className="text-[11px] text-gray-500">Налог удерживается с продавцов по их тарифу (как при обычной продаже).</div>
            </div>
            <div className="space-y-2">
              <div className="text-sm font-medium text-gray-300">🎭 Режим маскировки покупателя:</div>
              <label className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer p-2 rounded-lg hover:bg-gray-900/60">
                <input type="radio" name="mask" checked={maskMode === 'auto'} onChange={() => setMaskMode('auto')} data-testid="buyout-mask-auto" />
                Авто-распределение (случайные боты из пула) <span className="text-emerald-400 text-xs">Рекомендуется</span>
              </label>
              <label className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer p-2 rounded-lg hover:bg-gray-900/60">
                <input type="radio" name="mask" checked={maskMode === 'specific'} onChange={() => setMaskMode('specific')} data-testid="buyout-mask-specific" />
                Выбрать конкретного бота:
                <select value={botUsername} onChange={(e) => setBotUsername(e.target.value)} disabled={maskMode !== 'specific'}
                  className="h-8 bg-gray-800 border border-gray-700 rounded text-white text-sm px-2 disabled:opacity-40" data-testid="buyout-bot-select">
                  {nicks.map((n) => <option key={n} value={n}>{n}</option>)}
                </select>
              </label>
            </div>
            <div className="flex gap-2 justify-end pt-1">
              <Button variant="ghost" onClick={() => setConfirmOpen(false)} className="text-gray-400" data-testid="buyout-cancel">❌ Отмена</Button>
              <Button onClick={doExecute} disabled={executing} className="bg-amber-500 hover:bg-amber-600 text-black font-bold" data-testid="buyout-confirm">
                {executing ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : null} ✅ Утвердить и списать из казны
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* ── РЕЗУЛЬТАТ ──────────────────────────────────────── */}
      {result && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" data-testid="buyout-result-modal">
          <div className="w-full max-w-md rounded-2xl border border-emerald-500/40 bg-gray-950 p-5 space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-bold text-emerald-400">✅ Выкуп завершён</h3>
              <button onClick={() => setResult(null)} className="text-gray-400 hover:text-white"><X className="w-5 h-5" /></button>
            </div>
            <div className="text-sm text-gray-300 space-y-1">
              <div>Куплено единиц: <b className="text-cyan-300">{fmtCity(result.total_units)}</b></div>
              <div>Потрачено (сумма сделки): <b className="text-amber-300">{fmtCity(result.total_cost_city)}</b> $CITY</div>
              <div>Удержано налога с продавцов: <b className="text-white">{fmtCity(result.total_tax_city)}</b> $CITY</div>
            </div>
            <div className="rounded-lg bg-gray-900/60 border border-gray-700 p-2 space-y-1">
              {Object.entries(result.per_resource || {}).map(([code, r]) => (
                <div key={code} className="text-xs text-gray-300 flex justify-between">
                  <span>{r.icon} {r.resource_name}</span>
                  <span><b className="text-cyan-300">{fmtCity(r.units)}</b> ед. · {fmtCity(r.cost_city)} $CITY</span>
                </div>
              ))}
            </div>
            <Button onClick={() => setResult(null)} className="w-full bg-emerald-600 hover:bg-emerald-700" data-testid="buyout-result-close">Готово</Button>
          </div>
        </div>
      )}

      {/* ── ЛОГИ ИГРОКА ────────────────────────────────────── */}
      {logsFor && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" data-testid="buyout-logs-modal">
          <div className="w-full max-w-lg rounded-2xl border border-gray-700 bg-gray-950 p-5 space-y-3 max-h-[80vh] overflow-y-auto">
            <div className="flex items-center justify-between">
              <h3 className="text-base font-bold text-white">Логи сделок · @{logsFor.player.username}</h3>
              <button onClick={() => setLogsFor(null)} className="text-gray-400 hover:text-white"><X className="w-5 h-5" /></button>
            </div>
            {logsFor.logs.length === 0 ? (
              <p className="text-sm text-gray-500 py-4 text-center">Нет транзакций</p>
            ) : logsFor.logs.map((tx) => (
              <div key={tx.id} className="text-xs rounded-lg bg-gray-900/60 border border-gray-800 p-2">
                <div className="flex justify-between">
                  <span className="text-gray-300">Продажа ресурсов{tx.resource_amount ? ` · ${tx.resource_amount} ед.` : ''}</span>
                  <span className="text-emerald-400">+{fmtCity((tx.display_amount_ton ?? 0) * 1000)} $CITY</span>
                </div>
                <div className="text-[10px] text-gray-500">{tx.created_at ? new Date(tx.created_at).toLocaleString('ru-RU') : ''}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
