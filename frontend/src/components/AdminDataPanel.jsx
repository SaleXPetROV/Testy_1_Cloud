import { useState, useEffect } from 'react';
import AdsPanel from '@/components/admin/AdsPanel';
import AlliancesPanel from '@/components/admin/AlliancesPanel';
import { Search, User, Package, Edit2, Save, AlertTriangle, TrendingUp, Shield, X, Trash2, Lock, Unlock, ChevronUp, ChevronDown, ChevronRight, CalendarIcon } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Calendar } from '@/components/ui/calendar';
import { BarChart, Bar, XAxis, YAxis, Tooltip as RTooltip, ResponsiveContainer, Legend, CartesianGrid } from 'recharts';
import { toast } from 'sonner';
import axios from 'axios';
import { toUserFriendlyAddress, shortenAddress } from '@/lib/tonAddress';
import { formatErrorDetail, getApiErrorMessage } from '@/lib/apiErrors';
import { MAX_PRICE_VALUE } from '@/lib/priceLimits';
import AdminReferralsList from '@/components/admin/AdminReferralsList';
import PresalePanel from '@/components/admin/PresalePanel';
import BuyoutPanel from '@/components/admin/BuyoutPanel';
import SkinsStudio from '@/components/admin/SkinsStudio';
import { tonToCity, formatCity } from '@/lib/currency';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

export default function AdminDataPanel({ token }) {
  const [tab, setTab] = useState('players');
  const headers = { Authorization: `Bearer ${token}` };

  return (
    <div className="space-y-4">
      <div className="flex gap-2 flex-wrap">
        <button onClick={() => setTab('players')} data-testid="data-tab-players" className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${tab === 'players' ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/50' : 'bg-gray-800/50 text-gray-400 border border-gray-700'}`}>
          👤 Игроки
        </button>
        <button onClick={() => setTab('prices')} data-testid="data-tab-prices" className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${tab === 'prices' ? 'bg-amber-500/20 text-amber-400 border border-amber-500/50' : 'bg-gray-800/50 text-gray-400 border border-gray-700'}`}>
          💰 Цены товаров
        </button>
        <button onClick={() => setTab('load')} data-testid="data-tab-load" className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${tab === 'load' ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/50' : 'bg-gray-800/50 text-gray-400 border border-gray-700'}`}>
          📊 Нагрузка
        </button>
        <button onClick={() => setTab('tgbot')} data-testid="data-tab-tgbot" className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${tab === 'tgbot' ? 'bg-sky-500/20 text-sky-300 border border-sky-500/50' : 'bg-gray-800/50 text-gray-400 border border-gray-700'}`}>
          🤖 TG-бот
        </button>
        <button onClick={() => setTab('registrations')} data-testid="data-tab-registrations" className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${tab === 'registrations' ? 'bg-violet-500/20 text-violet-300 border border-violet-500/50' : 'bg-gray-800/50 text-gray-400 border border-gray-700'}`}>
          📝 Регистрация
        </button>
        <button onClick={() => setTab('referrals')} data-testid="data-tab-referrals" className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${tab === 'referrals' ? 'bg-pink-500/20 text-pink-300 border border-pink-500/50' : 'bg-gray-800/50 text-gray-400 border border-gray-700'}`}>
          🎯 Рефералы
        </button>
        <button onClick={() => setTab('presale')} data-testid="data-tab-presale" className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${tab === 'presale' ? 'bg-amber-500/20 text-amber-300 border border-amber-500/50' : 'bg-gray-800/50 text-gray-400 border border-gray-700'}`}>
          🚀 Пресейл
        </button>
        <button onClick={() => setTab('buyout')} data-testid="data-tab-buyout" className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${tab === 'buyout' ? 'bg-amber-500/20 text-amber-400 border border-amber-500/50' : 'bg-gray-800/50 text-gray-400 border border-gray-700'}`}>
          ⚡ Выкуп
        </button>
        <button onClick={() => setTab('skins')} data-testid="data-tab-skins" className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${tab === 'skins' ? 'bg-fuchsia-500/20 text-fuchsia-300 border border-fuchsia-500/50' : 'bg-gray-800/50 text-gray-400 border border-gray-700'}`}>
          🎨 Скины
        </button>
        <button onClick={() => setTab('monetag')} data-testid="data-tab-monetag" className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${tab === 'monetag' ? 'bg-yellow-500/20 text-yellow-300 border border-yellow-500/50' : 'bg-gray-800/50 text-gray-400 border border-gray-700'}`}>
          📺 Monetag
        </button>
        <button onClick={() => setTab('alliances')} data-testid="data-tab-alliances" className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${tab === 'alliances' ? 'bg-fuchsia-500/20 text-fuchsia-300 border border-fuchsia-500/50' : 'bg-gray-800/50 text-gray-400 border border-gray-700'}`}>
          🛡️ Альянсы
        </button>
      </div>

      {tab === 'players' && <PlayersTab token={token} headers={headers} />}
      {tab === 'prices' && <PricesTab token={token} headers={headers} />}
      {tab === 'load' && <LoadStatsTab headers={headers} />}
      {tab === 'tgbot' && <TgBotTab headers={headers} />}
      {tab === 'registrations' && <RegistrationsTab headers={headers} />}
      {tab === 'referrals' && <AdminReferralsList />}
      {tab === 'presale' && <PresalePanel token={token} />}
      {tab === 'buyout' && <BuyoutPanel token={token} />}
      {tab === 'skins' && <SkinsStudio token={token} />}
      {tab === 'monetag' && <AdsPanel />}
      {tab === 'alliances' && <AlliancesPanel />}
    </div>
  );
}

const REG_METHOD_META = {
  email: { label: 'Email', icon: '✉️', color: 'text-cyan-400', badge: 'bg-cyan-500/15 text-cyan-300 border-cyan-500/40' },
  google: { label: 'Google', icon: '🔵', color: 'text-amber-400', badge: 'bg-amber-500/15 text-amber-300 border-amber-500/40' },
  ton: { label: 'TON Connect', icon: '💎', color: 'text-blue-400', badge: 'bg-blue-500/15 text-blue-300 border-blue-500/40' },
  telegram: { label: 'Telegram', icon: '📨', color: 'text-sky-400', badge: 'bg-sky-500/15 text-sky-300 border-sky-500/40' },
};

// Human-friendly language label (shared across tabs)
const playerLangLabel = (code) => {
  if (!code) return '—';
  const map = { ru: '🇷🇺 RU', en: '🇬🇧 EN', es: '🇪🇸 ES', zh: '🇨🇳 CN', fr: '🇫🇷 FR', de: '🇩🇪 DE', ja: '🇯🇵 JP', ko: '🇰🇷 KR' };
  return map[code] || String(code).toUpperCase();
};

function RegistrationsTab({ headers }) {
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState({ email: 0, google: 0, ton: 0, telegram: 0, total: 0 });
  const [rows, setRows] = useState([]);
  const [langStats, setLangStats] = useState({});
  const [filter, setFilter] = useState('all');
  const [range, setRange] = useState(undefined); // { from: Date, to: Date }
  const [tgChoiceEnabled, setTgChoiceEnabled] = useState(true);
  const [tgToggleBusy, setTgToggleBusy] = useState(false);

  const loadTgSetting = async () => {
    try {
      const res = await axios.get(`${API}/admin/settings/telegram-registration`, { headers });
      setTgChoiceEnabled(!!res.data.choice_enabled);
    } catch (_) { /* silent */ }
  };

  const toggleTgChoice = async () => {
    const next = !tgChoiceEnabled;
    setTgToggleBusy(true);
    try {
      await axios.post(`${API}/admin/settings/telegram-registration`, { choice_enabled: next }, { headers });
      setTgChoiceEnabled(next);
      toast.success(next
        ? 'Окно регистрации Telegram включено'
        : 'Окно скрыто — вход через Telegram создаёт аккаунт автоматически');
    } catch (e) {
      toast.error(getApiErrorMessage(e) || 'Не удалось изменить настройку');
    } finally {
      setTgToggleBusy(false);
    }
  };

  const load = async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API}/admin/registrations`, { headers });
      setStats(res.data.stats || { email: 0, google: 0, ton: 0, telegram: 0, total: 0 });
      setRows(res.data.registrations || []);
      setLangStats(res.data.language_stats || {});
    } catch (e) {
      toast.error(getApiErrorMessage(e) || 'Не удалось загрузить регистрации');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); loadTgSetting(); /* eslint-disable-next-line */ }, []);

  const fmtDate = (d) => {
    if (!d) return '—';
    try { return new Date(d).toLocaleString('ru-RU'); } catch { return String(d); }
  };
  const fmtDay = (d) => {
    try { return new Date(d).toLocaleDateString('ru-RU'); } catch { return String(d); }
  };
  // Local day-key (YYYY-MM-DD) so grouping matches the user's timezone.
  const dayKey = (d) => {
    const x = new Date(d);
    if (isNaN(x)) return null;
    return `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`;
  };
  // Truncate long IPs (e.g. IPv6) so they don't squeeze the «Способ» column.
  const truncIp = (ip) => {
    if (!ip) return '—';
    const s = String(ip);
    return s.length > 25 ? s.slice(0, 25) + '…' : s;
  };

  // --- Period filter (by day, inclusive) ---
  const startOfDay = (d) => { const x = new Date(d); x.setHours(0, 0, 0, 0); return x; };
  const endOfDay = (d) => { const x = new Date(d); x.setHours(23, 59, 59, 999); return x; };
  const inRange = (created_at) => {
    if (!range?.from) return true;
    const t = new Date(created_at).getTime();
    if (isNaN(t)) return false;
    const from = startOfDay(range.from).getTime();
    const to = endOfDay(range.to || range.from).getTime();
    return t >= from && t <= to;
  };

  // Rows after BOTH period + method filters (table + period stats)
  const periodRows = rows.filter((r) => inRange(r.created_at));
  const visibleRows = (filter === 'all' ? periodRows : periodRows.filter((r) => r.method === filter));

  // Period stats (recomputed from the selected period, method-independent)
  const periodStats = periodRows.reduce((acc, r) => {
    acc.total += 1;
    acc[r.method] = (acc[r.method] || 0) + 1;
    return acc;
  }, { email: 0, google: 0, ton: 0, telegram: 0, total: 0 });

  // --- Chart data: per-day counts by method within the selected period ---
  const chartData = (() => {
    const byDay = {};
    for (const r of periodRows) {
      const k = dayKey(r.created_at);
      if (!k) continue;
      if (!byDay[k]) byDay[k] = { key: k, label: fmtDay(r.created_at), email: 0, google: 0, ton: 0, telegram: 0, total: 0 };
      byDay[k][r.method] = (byDay[k][r.method] || 0) + 1;
      byDay[k].total += 1;
    }
    return Object.values(byDay).sort((a, b) => a.key.localeCompare(b.key));
  })();

  const rangeLabel = range?.from
    ? (range.to && startOfDay(range.to).getTime() !== startOfDay(range.from).getTime()
        ? `${fmtDay(range.from)} — ${fmtDay(range.to)}`
        : fmtDay(range.from))
    : 'Весь период';

  // Language distribution (in-app users + Telegram bot users), sorted by total.
  const langEntries = Object.entries(langStats || {})
    .map(([code, v]) => {
      const app = (v && v.app) || 0;
      const bot = (v && v.bot) || 0;
      return { code, app, bot, total: app + bot };
    })
    .filter((e) => e.total > 0)
    .sort((a, b) => b.total - a.total);
  const langUsersTotal = langEntries.reduce((s, e) => s + e.total, 0);

  return (
    <div className="space-y-4" data-testid="registrations-tab">
      {/* Telegram Mini App registration-choice modal toggle */}
      <div className="p-4 rounded-xl bg-gray-900/60 border border-sky-700/40 flex items-center justify-between gap-4" data-testid="tg-registration-toggle-card">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-sky-300 flex items-center gap-2">🤖 Окно регистрации в Telegram Mini App</div>
          <div className="text-xs text-gray-400 mt-1">
            {tgChoiceEnabled
              ? 'Включено: новому пользователю показывается окно выбора «Создать / Привязать аккаунт».'
              : 'Выключено: при первом входе аккаунт создаётся автоматически, без окна.'}
          </div>
        </div>
        <button
          type="button"
          onClick={toggleTgChoice}
          disabled={tgToggleBusy}
          data-testid="tg-registration-toggle-btn"
          aria-label={tgChoiceEnabled ? 'Включено' : 'Выключено'}
          className={`flex items-center gap-2 shrink-0 disabled:opacity-60`}
        >
          <span className={`text-xs font-semibold w-16 text-right ${tgChoiceEnabled ? 'text-cyan-400' : 'text-gray-500'}`}>
            {tgChoiceEnabled ? 'Включено' : 'Выключено'}
          </span>
          <span className={`relative inline-flex h-7 w-14 items-center rounded-full transition-colors ${tgChoiceEnabled ? 'bg-cyan-500' : 'bg-gray-600'}`}>
            <span className={`inline-block h-5 w-5 transform rounded-full bg-white transition-transform ${tgChoiceEnabled ? 'translate-x-8' : 'translate-x-1'}`} />
          </span>
        </button>
      </div>

      {/* Overall stats — reflect the selected period */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="p-4 rounded-xl bg-gray-900/60 border border-gray-700" data-testid="reg-stat-total">
          <div className="text-xs text-gray-500 mb-1">Регистраций за период</div>
          <div className="text-2xl font-bold text-white">{periodStats.total}</div>
        </div>
        {['email', 'google', 'ton', 'telegram'].map((m) => {
          const meta = REG_METHOD_META[m];
          const pct = periodStats.total ? Math.round(((periodStats[m] || 0) / periodStats.total) * 100) : 0;
          return (
            <div key={m} className="p-4 rounded-xl bg-gray-900/60 border border-gray-700" data-testid={`reg-stat-${m}`}>
              <div className="text-xs text-gray-500 mb-1">{meta.icon} {meta.label}</div>
              <div className={`text-2xl font-bold ${meta.color}`}>{periodStats[m] || 0}</div>
              <div className="text-xs text-gray-600">{pct}%</div>
            </div>
          );
        })}
      </div>

      {/* Period picker */}
      <div className="flex gap-2 flex-wrap items-center">
        <span className="text-xs text-gray-500">Период:</span>
        <Popover>
          <PopoverTrigger asChild>
            <Button variant="outline" size="sm" data-testid="reg-date-trigger"
              className="h-8 bg-gray-900/50 border-gray-700 text-gray-200 hover:bg-gray-800 hover:text-white">
              <CalendarIcon className="w-3.5 h-3.5 mr-2 text-violet-300" />
              {rangeLabel}
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-auto p-0 bg-gray-900 border-gray-700" align="start">
            <Calendar
              mode="range"
              selected={range}
              onSelect={setRange}
              numberOfMonths={2}
              className="text-white"
            />
            <div className="flex justify-end gap-2 p-2 border-t border-gray-800">
              <Button size="sm" variant="ghost" data-testid="reg-date-clear"
                className="h-7 text-xs text-gray-400" onClick={() => setRange(undefined)}>
                Сбросить
              </Button>
            </div>
          </PopoverContent>
        </Popover>
        {range?.from && (
          <span className="text-xs text-violet-300" data-testid="reg-range-label">Выбрано: {rangeLabel}</span>
        )}

        {/* Language breakdown — to the RIGHT of the period button.
            Counts users by language across BOTH the web app and the Telegram bot. */}
        <div className="flex items-center gap-1.5 flex-wrap pl-2 ml-1 border-l border-gray-700"
          data-testid="reg-lang-stats">
          <span className="text-xs text-gray-500">Языки:</span>
          {langEntries.length === 0 ? (
            <span className="text-xs text-gray-600">нет данных</span>
          ) : (
            langEntries.map((e) => (
              <span
                key={e.code}
                data-testid={`reg-lang-${e.code}`}
                title={`Веб-приложение: ${e.app} · Telegram-бот: ${e.bot}`}
                className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-xs bg-gray-800/60 text-gray-200 border border-gray-700 hover:border-violet-500/50 transition-colors cursor-default"
              >
                <span>{playerLangLabel(e.code)}</span>
                <b className="text-violet-300" data-testid={`reg-lang-count-${e.code}`}>{e.total}</b>
              </span>
            ))
          )}
          {langEntries.length > 0 && (
            <span className="text-xs text-gray-500" data-testid="reg-lang-total">Σ {langUsersTotal}</span>
          )}
        </div>

        <button onClick={load} data-testid="reg-refresh" className="ml-auto px-3 py-1 rounded-lg text-xs bg-gray-800/50 text-gray-300 border border-gray-700 hover:bg-gray-700/50">↻ Обновить</button>
      </div>

      {/* Per-day chart — auto-adapts to the selected period */}
      {chartData.length > 0 && (
        <div className="rounded-xl border border-gray-700 bg-gray-900/40 p-3" data-testid="reg-chart">
          <div className="text-xs text-gray-400 mb-2">Регистрации по дням ({rangeLabel})</div>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={chartData} margin={{ top: 8, right: 8, left: -12, bottom: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" vertical={false} />
              <XAxis dataKey="label" tick={{ fill: '#9ca3af', fontSize: 11 }} stroke="#4b5563" />
              <YAxis allowDecimals={false} tick={{ fill: '#9ca3af', fontSize: 11 }} stroke="#4b5563" />
              <RTooltip contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 8, color: '#fff' }} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="email" stackId="a" name="Email" fill="#22d3ee" radius={[0, 0, 0, 0]} />
              <Bar dataKey="google" stackId="a" name="Google" fill="#f59e0b" radius={[0, 0, 0, 0]} />
              <Bar dataKey="ton" stackId="a" name="TON" fill="#3b82f6" radius={[0, 0, 0, 0]} />
              <Bar dataKey="telegram" stackId="a" name="Telegram" fill="#0ea5e9" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Method filter */}
      <div className="flex gap-2 flex-wrap items-center">
        <span className="text-xs text-gray-500">Фильтр:</span>
        {['all', 'email', 'google', 'ton', 'telegram'].map((m) => (
          <button
            key={m}
            onClick={() => setFilter(m)}
            data-testid={`reg-filter-${m}`}
            className={`px-3 py-1 rounded-lg text-xs font-medium border transition-all ${filter === m ? 'bg-violet-500/20 text-violet-300 border-violet-500/50' : 'bg-gray-800/50 text-gray-400 border-gray-700'}`}
          >
            {m === 'all' ? 'Все' : `${REG_METHOD_META[m].icon} ${REG_METHOD_META[m].label}`}
          </button>
        ))}
        <span className="ml-auto text-xs text-gray-500" data-testid="reg-found-count">Найдено: {visibleRows.length}</span>
      </div>

      {/* Table */}
      {loading ? (
        <div className="text-center text-gray-500 py-8">Загрузка…</div>
      ) : visibleRows.length === 0 ? (
        <div className="text-center text-gray-500 py-8">Нет данных</div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-gray-700">
          <table className="w-full text-sm" data-testid="reg-table">
            <thead>
              <tr className="bg-gray-900/80 text-gray-400 text-xs uppercase">
                <th className="text-left px-3 py-2">Пользователь</th>
                <th className="text-left px-3 py-2">Email / Кошелёк</th>
                <th className="text-left px-3 py-2 whitespace-nowrap">Способ</th>
                <th className="text-left px-3 py-2">Дата</th>
                <th className="text-left px-3 py-2">IP</th>
                <th className="text-left px-3 py-2">Устройство</th>
                <th className="text-left px-3 py-2">Браузер</th>
              </tr>
            </thead>
            <tbody>
              {visibleRows.map((r, i) => {
                const meta = REG_METHOD_META[r.method] || REG_METHOD_META.email;
                return (
                  <tr key={r.id || i} className="border-t border-gray-800 hover:bg-gray-800/30" data-testid={`reg-row-${i}`}>
                    <td className="px-3 py-2 text-white">{r.display_name || r.username || '—'}</td>
                    <td className="px-3 py-2 text-gray-400 font-mono text-xs">{r.email || (r.wallet_address ? shortenAddress(r.wallet_address) : '—')}</td>
                    <td className="px-3 py-2 whitespace-nowrap">
                      <span className={`px-2 py-0.5 rounded-full border text-xs whitespace-nowrap ${meta.badge}`}>{meta.icon} {meta.label}</span>
                    </td>
                    <td className="px-3 py-2 text-gray-400 text-xs whitespace-nowrap">{fmtDate(r.created_at)}</td>
                    <td className="px-3 py-2 text-gray-400 font-mono text-xs" title={r.ip || ''}>{truncIp(r.ip)}</td>
                    <td className="px-3 py-2 text-gray-400 text-xs">{r.device}</td>
                    <td className="px-3 py-2 text-gray-400 text-xs">{r.browser}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}


// ─── TG-Bot: user statistics of the Telegram bot ────────────────────────────
function TgBotTab({ headers }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('all'); // all | premium | non_premium | linked | unlinked

  const load = async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API}/admin/telegram-bot-stats`, { headers });
      setData(res.data);
    } catch (e) {
      toast.error('Ошибка загрузки статистики TG-бота');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []); // eslint-disable-line

  const fmtDate = (iso) => {
    if (!iso) return '—';
    try {
      const d = new Date(iso);
      return d.toLocaleString('ru-RU', {
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit',
      });
    } catch { return iso; }
  };

  const langLabel = (code) => {
    if (!code) return '—';
    const map = { ru: '🇷🇺 RU', en: '🇬🇧 EN', es: '🇪🇸 ES', zh: '🇨🇳 CN', fr: '🇫🇷 FR', de: '🇩🇪 DE', ja: '🇯🇵 JP', ko: '🇰🇷 KR' };
    return map[code] || code.toUpperCase();
  };

  const filtered = (data?.users || []).filter((u) => {
    if (filter === 'premium' && !u.is_premium) return false;
    if (filter === 'non_premium' && u.is_premium) return false;
    if (filter === 'linked' && !u.linked_account) return false;
    if (filter === 'unlinked' && u.linked_account) return false;
    if (search) {
      const q = search.toLowerCase();
      const hay = [
        u.username, u.first_name, u.telegram_user_id, u.chat_id,
        u.linked_account?.username, u.linked_account?.email, u.linked_account?.display_name,
      ].filter(Boolean).join(' ').toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  return (
    <div className="glass-panel rounded-xl p-4 border border-sky-500/20" data-testid="tgbot-stats-panel">
      <div className="flex items-center justify-between mb-3 flex-wrap gap-3">
        <div>
          <h3 className="font-unbounded text-sm font-bold text-white">Пользователи Telegram-бота</h3>
          <p className="text-[11px] text-text-muted mt-0.5">
            Все, кто когда-либо взаимодействовал с ботом (сохраняется при каждом сообщении/нажатии).
          </p>
        </div>
        <Button onClick={load} disabled={loading} variant="outline" size="sm" className="border-white/10" data-testid="tgbot-stats-refresh">
            {loading ? '...' : 'Обновить'}
          </Button>
          <Button
            onClick={async () => {
              try {
                const res = await axios.get(`${API}/admin/telegram-bot-stats/export-csv`, {
                  headers, responseType: 'blob',
                });
                const blob = new Blob([res.data], { type: 'text/csv;charset=utf-8' });
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `telegram_bot_users_${new Date().toISOString().slice(0,19).replace(/[:T]/g,'')}.csv`;
                document.body.appendChild(a);
                a.click();
                a.remove();
                window.URL.revokeObjectURL(url);
                toast.success('CSV скачан');
              } catch (e) {
                toast.error('Не удалось выгрузить CSV');
              }
            }}
            variant="outline"
            size="sm"
            className="border-emerald-500/40 text-emerald-300 hover:bg-emerald-500/10 ml-2"
            data-testid="tgbot-export-csv"
          >
            📥 Экспорт CSV
          </Button>
      </div>

      {/* Summary counters */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
        <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3" data-testid="tgbot-count-total">
          <div className="text-[10px] uppercase tracking-widest text-text-muted">Всего пользователей</div>
          <div className="text-2xl font-bold text-white">{data?.total ?? '—'}</div>
        </div>
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/[0.05] p-3" data-testid="tgbot-count-premium">
          <div className="text-[10px] uppercase tracking-widest text-amber-300">С Premium</div>
          <div className="text-2xl font-bold text-amber-300">{data?.premium_count ?? '—'}</div>
        </div>
        <div className="rounded-lg border border-sky-500/30 bg-sky-500/[0.05] p-3" data-testid="tgbot-count-nonpremium">
          <div className="text-[10px] uppercase tracking-widest text-sky-300">Без Premium</div>
          <div className="text-2xl font-bold text-sky-300">{data?.non_premium_count ?? '—'}</div>
        </div>
        <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/[0.05] p-3" data-testid="tgbot-count-linked">
          <div className="text-[10px] uppercase tracking-widest text-emerald-300">Привязано аккаунтов</div>
          <div className="text-2xl font-bold text-emerald-300">
            {data?.users?.filter((u) => u.linked_account).length ?? '—'}
          </div>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-2 mb-3">
        <Input
          placeholder="Поиск: username, ID, email…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="bg-panel border-grid-border max-w-xs"
          data-testid="tgbot-search-input"
        />
        {['all', 'premium', 'non_premium', 'linked', 'unlinked'].map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            data-testid={`tgbot-filter-${f}`}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-all ${filter === f ? 'bg-sky-500/20 text-sky-300 border-sky-500/50' : 'bg-gray-800/40 text-gray-400 border-gray-700 hover:border-white/20'}`}
          >
            {f === 'all' ? 'Все' : f === 'premium' ? '⭐ Premium' : f === 'non_premium' ? 'Без Premium' : f === 'linked' ? '🔗 С аккаунтом' : 'Без аккаунта'}
          </button>
        ))}
      </div>

      {/* Users table */}
      {!data ? (
        <p className="text-text-muted text-sm py-6 text-center">Загрузка…</p>
      ) : filtered.length === 0 ? (
        <p className="text-text-muted text-sm py-6 text-center">Нет пользователей по фильтру.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-text-muted text-xs border-b border-white/10">
                <th className="text-left py-2 px-2">Пользователь</th>
                <th className="text-left py-2 px-2">Premium</th>
                <th className="text-left py-2 px-2">Язык</th>
                <th className="text-left py-2 px-2">Привязанный аккаунт</th>
                <th className="text-left py-2 px-2">Первая активность</th>
                <th className="text-left py-2 px-2">Последняя активность</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((u) => (
                <tr key={u.chat_id} className="border-b border-white/5 hover:bg-white/[0.02]" data-testid={`tgbot-row-${u.chat_id}`}>
                  <td className="py-2 px-2">
                    <div className="font-medium text-white">{u.first_name || u.username || '—'}</div>
                    <div className="text-[11px] text-text-muted">
                      {u.username ? `@${u.username} · ` : ''}<span className="font-mono">id:{u.telegram_user_id || u.chat_id}</span>
                    </div>
                  </td>
                  <td className="py-2 px-2">
                    {u.is_premium
                      ? <span className="inline-block px-2 py-0.5 rounded text-xs bg-amber-500/20 text-amber-300 border border-amber-500/40">⭐ Premium</span>
                      : <span className="inline-block px-2 py-0.5 rounded text-xs bg-white/5 text-text-muted border border-white/10">—</span>}
                  </td>
                  <td className="py-2 px-2 text-white text-xs">{langLabel(u.language)}</td>
                  <td className="py-2 px-2 text-xs">
                    {u.linked_account
                      ? (
                        <div>
                          <div className="text-emerald-300 font-medium">
                            {u.linked_account.display_name || u.linked_account.username || '—'}
                          </div>
                          <div className="text-[11px] text-text-muted">
                            {u.linked_account.email || u.linked_account.username || u.linked_account.id}
                          </div>
                        </div>
                      )
                      : <span className="text-text-muted">Не привязан</span>}
                  </td>
                  <td className="py-2 px-2 text-text-muted text-xs font-mono whitespace-nowrap">{fmtDate(u.first_activity_at)}</td>
                  <td className="py-2 px-2 text-text-muted text-xs font-mono whitespace-nowrap">{fmtDate(u.last_activity_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ─── Нагрузка: production / consumption / % per resource ────────────────────
function LoadStatsTab({ headers }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API}/admin/load-stats`, { headers });
      setData(res.data);
    } catch (e) {
      toast.error('Ошибка загрузки нагрузки');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []); // eslint-disable-line

  const tierColor = (t) => t === 1 ? 'text-cyan-300' : t === 2 ? 'text-amber-300' : 'text-fuchsia-300';
  const loadColor = (pct) => pct >= 95 ? 'bg-red-500/30 text-red-300 border-red-500/50'
    : pct >= 70 ? 'bg-amber-500/20 text-amber-300 border-amber-500/40'
    : pct >= 30 ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
    : 'bg-white/5 text-text-muted border-white/10';

  return (
    <div className="glass-panel rounded-xl p-4 border border-emerald-500/20" data-testid="load-stats-panel">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="font-unbounded text-sm font-bold text-white">Нагрузка по ресурсам</h3>
          <p className="text-[11px] text-text-muted mt-0.5">
            Производство и потребление всеми бизнесами в час. Нагрузка = потребление / производство.
            {data && ` Бизнесов: ${data.businesses_count}.`}
          </p>
        </div>
        <Button onClick={load} disabled={loading} variant="outline" size="sm" className="border-white/10" data-testid="load-stats-refresh">
          {loading ? '...' : 'Обновить'}
        </Button>
      </div>
      {!data ? (
        <p className="text-text-muted text-sm py-6 text-center">Загрузка…</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-text-muted text-xs border-b border-white/10">
                <th className="text-left py-2 px-2">Ресурс</th>
                <th className="text-right py-2 px-2">Наличие</th>
                <th className="text-right py-2 px-2">Производится</th>
                <th className="text-right py-2 px-2">Потребляется</th>
                <th className="text-right py-2 px-2">Выкуп</th>
                <th className="text-right py-2 px-2">Нагрузка</th>
              </tr>
            </thead>
            <tbody>
              {data.resources.map((r) => (
                <tr key={r.code} className="border-b border-white/5 hover:bg-white/[0.02]" data-testid={`load-row-${r.code}`}>
                  <td className="py-2 px-2">
                    <span className="text-base mr-2">{r.icon}</span>
                    <span className="text-white">{r.name_ru}</span>
                    <span className={`ml-2 text-[10px] uppercase ${tierColor(r.tier)}`}>T{r.tier}</span>
                  </td>
                  <td className="py-2 px-2 text-right text-sky-300 font-mono" data-testid={`load-available-${r.code}`}>{(r.available ?? 0).toLocaleString('ru-RU')}</td>
                  <td className="py-2 px-2 text-right text-emerald-300 font-mono">{r.produced.toLocaleString('ru-RU')}</td>
                  <td className="py-2 px-2 text-right text-rose-300 font-mono">{r.consumed.toLocaleString('ru-RU')}</td>
                  <td className="py-2 px-2 text-right text-amber-300 font-mono" data-testid={`load-bought-${r.code}`}>{(r.bought_today ?? 0).toLocaleString('ru-RU')}</td>
                  <td className="py-2 px-2 text-right">
                    <span className={`inline-block px-2 py-0.5 rounded text-xs font-mono border ${loadColor(r.load_pct)}`}>
                      {r.load_pct}%
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function PlayersTab({ token, headers }) {
  const [query, setQuery] = useState('');
  const [players, setPlayers] = useState([]);
  const [selectedPlayer, setSelectedPlayer] = useState(null);
  const [playerDetails, setPlayerDetails] = useState(null);
  const [expandedBiz, setExpandedBiz] = useState(null); // business id whose prod/cons details are shown
  const [editMode, setEditMode] = useState(false);
  const [editData, setEditData] = useState({});
  const [loading, setLoading] = useState(false);
  // Resources editing
  const [resourcesEdit, setResourcesEdit] = useState(null); // { [name]: number } | null
  const [newResName, setNewResName] = useState('');
  const [newResAmount, setNewResAmount] = useState('');
  // Catalog of valid resource types loaded from backend (filled once)
  const [resourceCatalog, setResourceCatalog] = useState({}); // { code: {name_ru, icon, tier, ...} }
  // Block withdrawal
  const [blockHours, setBlockHours] = useState(24);
  const [blockReason, setBlockReason] = useState('');
  const [accBlockReason, setAccBlockReason] = useState('');
  // Referrals view
  const [referralInfo, setReferralInfo] = useState(null);
  const [showReferrals, setShowReferrals] = useState(false);
  // Referrer assign/change modal
  const [showReferrerModal, setShowReferrerModal] = useState(false);
  const [refSearch, setRefSearch] = useState('');
  const [refResults, setRefResults] = useState([]);
  const [refSearchLoading, setRefSearchLoading] = useState(false);
  const [refSaving, setRefSaving] = useState(false);
  // Transactions view (all operations tied to this player)
  const [showTx, setShowTx] = useState(false);
  const [txList, setTxList] = useState([]);
  const [txLoading, setTxLoading] = useState(false);

  const searchReferrerCandidates = async (q) => {
    setRefSearch(q);
    if (!q || q.trim().length < 1) { setRefResults([]); return; }
    setRefSearchLoading(true);
    try {
      const res = await axios.get(`${API}/admin/players/search?query=${encodeURIComponent(q.trim())}`, { headers });
      const me = playerDetails?.user?.id;
      setRefResults((res.data.players || []).filter((p) => p.id !== me).slice(0, 25));
    } catch (e) {
      setRefResults([]);
    } finally {
      setRefSearchLoading(false);
    }
  };

  const assignReferrer = async (referrerId) => {
    if (!selectedPlayer || !referrerId) return;
    setRefSaving(true);
    try {
      const res = await axios.post(`${API}/admin/players/${selectedPlayer}/referrer`, { referrer_id: referrerId }, { headers });
      toast.success(`Реферер назначен: @${res.data.referrer?.username || referrerId}`);
      setShowReferrerModal(false);
      setRefSearch(''); setRefResults([]);
      await loadPlayerDetails(selectedPlayer);
      if (showReferrals) await loadPlayerReferrals(selectedPlayer);
    } catch (e) {
      toast.error(getApiErrorMessage(e) || 'Не удалось назначить реферера');
    } finally {
      setRefSaving(false);
    }
  };

  const openReferrerModal = () => {
    setRefSearch(''); setRefResults([]);
    setShowReferrerModal(true);
  };

  const loadPlayerReferrals = async (playerId) => {
    try {
      const res = await axios.get(`${API}/admin/players/${playerId}/referrals`, { headers });
      setReferralInfo(res.data);
      setShowReferrals(true);
    } catch (e) {
      toast.error(getApiErrorMessage(e) || 'Не удалось загрузить рефералов');
    }
  };

  const loadPlayerTransactions = async (playerId) => {
    // Match every operation the user took part in (by id / wallet / email /
    // username) using the admin transactions search endpoint.
    const searchKey = playerDetails?.user?.id || playerId;
    setTxLoading(true);
    try {
      const res = await axios.get(
        `${API}/admin/transactions?search=${encodeURIComponent(searchKey)}&limit=300&lang=ru`,
        { headers }
      );
      setTxList(res.data.transactions || []);
      setShowTx(true);
    } catch (e) {
      toast.error(getApiErrorMessage(e) || 'Не удалось загрузить транзакции');
    } finally {
      setTxLoading(false);
    }
  };

  // Load resource catalog once for the dropdown
  useEffect(() => {
    axios.get(`${API}/economy/config`)
      .then((r) => setResourceCatalog(r.data?.resource_types || r.data?.resources || {}))
      .catch(() => setResourceCatalog({}));
  }, []);

  const searchPlayers = async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API}/admin/players/search?query=${encodeURIComponent(query)}`, { headers });
      setPlayers(res.data.players || []);
    } catch (e) {
      toast.error('Ошибка поиска');
    }
    setLoading(false);
  };

  const loadPlayerDetails = async (playerId) => {
    try {
      const res = await axios.get(`${API}/admin/players/${playerId}`, { headers });
      setPlayerDetails(res.data);
      setSelectedPlayer(playerId);
      setEditData({
        balance_ton: res.data.user?.balance_ton || 0,
        bonus_balance: res.data.user?.bonus_balance || 0,
        display_name: res.data.user?.display_name || '',
        is_banned: res.data.user?.is_banned || false,
      });
      setResourcesEdit(null);
      setShowReferrals(false);
      setReferralInfo(null);
      setShowTx(false);
      setTxList([]);
    } catch (e) {
      toast.error('Ошибка загрузки данных игрока');
    }
  };

  const savePlayerChanges = async () => {
    try {
      await axios.post(`${API}/admin/players/${selectedPlayer}/update`, editData, { headers });
      toast.success('Данные обновлены');
      setEditMode(false);
      loadPlayerDetails(selectedPlayer);
    } catch (e) {
      toast.error(getApiErrorMessage(e) || 'Ошибка сохранения');
    }
  };

  // ---- Business management ----
  const deleteBusiness = async (businessId, label) => {
    if (!window.confirm(`Удалить бизнес ${label}? Действие необратимо.`)) return;
    try {
      await axios.delete(`${API}/admin/players/${selectedPlayer}/business/${businessId}`, { headers });
      toast.success('Бизнес удалён');
      loadPlayerDetails(selectedPlayer);
    } catch (e) {
      toast.error(getApiErrorMessage(e) || 'Ошибка удаления');
    }
  };

  const changeBusinessLevel = async (businessId, currentLevel, delta) => {
    const newLevel = Math.max(1, (currentLevel || 1) + delta);
    try {
      await axios.post(
        `${API}/admin/players/${selectedPlayer}/business/${businessId}/update`,
        { level: newLevel },
        { headers }
      );
      toast.success(`Уровень бизнеса: ${newLevel}`);
      loadPlayerDetails(selectedPlayer);
    } catch (e) {
      toast.error(getApiErrorMessage(e) || 'Ошибка обновления');
    }
  };

  const repairBusiness = async (businessId) => {
    try {
      await axios.post(
        `${API}/admin/players/${selectedPlayer}/business/${businessId}/update`,
        { durability: 100.0 },
        { headers }
      );
      toast.success('Прочность восстановлена');
      loadPlayerDetails(selectedPlayer);
    } catch (e) {
      toast.error(getApiErrorMessage(e) || 'Ошибка');
    }
  };

  // ---- Resources management ----
  const startResourcesEdit = () => {
    setResourcesEdit({ ...(playerDetails?.user?.resources || {}) });
  };

  const saveResources = async () => {
    try {
      await axios.post(`${API}/admin/players/${selectedPlayer}/resources`, { resources: resourcesEdit || {} }, { headers });
      toast.success('Ресурсы обновлены');
      setResourcesEdit(null);
      loadPlayerDetails(selectedPlayer);
    } catch (e) {
      toast.error(getApiErrorMessage(e) || 'Ошибка');
    }
  };

  const addResource = () => {
    const name = (newResName || '').trim().toLowerCase();
    const amount = parseFloat(newResAmount);
    if (!name || isNaN(amount) || amount < 0) {
      toast.error('Выберите ресурс и укажите количество');
      return;
    }
    if (resourceCatalog && Object.keys(resourceCatalog).length > 0 && !resourceCatalog[name]) {
      toast.error('Этот ресурс не входит в каталог игры');
      return;
    }
    setResourcesEdit({ ...(resourcesEdit || {}), [name]: amount });
    setNewResName('');
    setNewResAmount('');
  };

  // ---- Блокировка / разблокировка аккаунта (не только вывода) ----
  const blockAccount = async () => {
    if (!selectedPlayer) return;
    try {
      await axios.post(
        `${API}/admin/user/${selectedPlayer}/block`,
        { reason: (accBlockReason || '').trim() || 'Нарушение правил' },
        { headers }
      );
      toast.success('Пользователь заблокирован');
      setAccBlockReason('');
      loadPlayerDetails(selectedPlayer);
    } catch (e) {
      toast.error(getApiErrorMessage(e) || 'Ошибка');
    }
  };

  const unblockAccount = async () => {
    if (!selectedPlayer) return;
    try {
      await axios.post(`${API}/admin/user/${selectedPlayer}/unblock`, {}, { headers });
      toast.success('Пользователь разблокирован');
      loadPlayerDetails(selectedPlayer);
    } catch (e) {
      toast.error(getApiErrorMessage(e) || 'Ошибка');
    }
  };

  // ---- Block / unblock withdrawals ----
  const blockWithdrawal = async () => {
    try {
      await axios.post(
        `${API}/admin/players/${selectedPlayer}/block-withdrawal`,
        { hours: parseInt(blockHours) || 24, reason: blockReason },
        { headers }
      );
      toast.success('Вывод заблокирован');
      loadPlayerDetails(selectedPlayer);
    } catch (e) {
      toast.error(getApiErrorMessage(e) || 'Ошибка');
    }
  };

  const unblockWithdrawal = async () => {
    try {
      await axios.post(`${API}/admin/players/${selectedPlayer}/unblock-withdrawal`, {}, { headers });
      toast.success('Вывод разблокирован');
      loadPlayerDetails(selectedPlayer);
    } catch (e) {
      toast.error(getApiErrorMessage(e) || 'Ошибка');
    }
  };

  useEffect(() => { searchPlayers(); }, []);

  return (
    <div className="space-y-4">
      {/* Search */}
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && searchPlayers()}
            placeholder="Поиск по ID, кошельку, имени, email..."
            className="pl-10 bg-gray-900/50 border-gray-700 text-white"
          />
        </div>
        <Button onClick={searchPlayers} className="bg-cyan-600 hover:bg-cyan-700">Найти</Button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Players List */}
        <div className="space-y-2 max-h-[600px] overflow-y-auto">
          <div className="text-xs text-gray-500 mb-1">Найдено: {players.length}</div>
          {players.map(p => {
            const pid = p.id || p.wallet_address;
            return (
              <button
                key={pid}
                onClick={() => loadPlayerDetails(pid)}
                className={`w-full text-left p-3 rounded-xl border transition-all ${selectedPlayer === pid ? 'bg-cyan-900/30 border-cyan-700/50' : 'bg-gray-800/30 border-gray-700/30 hover:bg-gray-800/60'}`}
              >
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm font-medium text-white">{p.display_name || p.username || 'Anonymous'}</div>
                    <div className="text-xs text-gray-500">{p.email || (p.wallet_address ? shortenAddress(toUserFriendlyAddress(p.wallet_address)) : pid?.slice(0, 12))}</div>
                  </div>
                  <div className="text-right">
                    <div className="text-sm font-mono text-green-400" data-testid="admin-list-total-balance">{((p.balance_ton || 0) + (p.bonus_balance || 0)).toFixed(2)} TON</div>
                    <div className="text-[10px] text-gray-500">реал {(p.balance_ton || 0).toFixed(2)} · бонус {(p.bonus_balance || 0).toFixed(2)}</div>
                    <div className="text-xs text-gray-500">{p.is_banned ? '🚫 Бан' : '✅'}</div>
                  </div>
                </div>
              </button>
            );
          })}
        </div>

        {/* Player Details */}
        {playerDetails && (
          <div className="p-4 rounded-2xl bg-gray-800/40 border border-gray-700/50 space-y-4 max-h-[600px] overflow-y-auto">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-bold text-white">
                {playerDetails.user?.display_name || 'Игрок'}
              </h3>
              <div className="flex gap-2">
                {editMode ? (
                  <>
                    <Button size="sm" onClick={savePlayerChanges} className="bg-green-600 hover:bg-green-700"><Save className="w-3 h-3 mr-1" /> Сохранить</Button>
                    <Button size="sm" variant="ghost" onClick={() => setEditMode(false)} className="text-gray-400"><X className="w-3 h-3" /></Button>
                  </>
                ) : (
                  <Button size="sm" onClick={() => setEditMode(true)} className="bg-amber-600 hover:bg-amber-700"><Edit2 className="w-3 h-3 mr-1" /> Редактировать</Button>
                )}
              </div>
            </div>

            {/* Basic Info */}
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div className="p-2 rounded-lg bg-gray-900/40">
                <div className="text-xs text-gray-500">ID</div>
                <div className="text-white font-mono text-xs break-all">{playerDetails.user?.id}</div>
              </div>
              <div className="p-2 rounded-lg bg-gray-900/40">
                <div className="text-xs text-gray-500">Email</div>
                <div className="text-white text-xs">{playerDetails.user?.email || '—'}</div>
              </div>
              <div className="p-2 rounded-lg bg-gray-900/40">
                <div className="text-xs text-gray-500">Реальный баланс TON</div>
                {editMode ? (
                  <Input type="number" step="0.01" value={editData.balance_ton} onChange={(e) => setEditData({...editData, balance_ton: parseFloat(e.target.value)})} className="h-7 bg-gray-800 border-gray-600 text-white text-xs" data-testid="admin-edit-balance-ton" />
                ) : (
                  <div className="text-cyan-400 font-bold" data-testid="admin-balance-ton">{(playerDetails.user?.balance_ton || 0).toFixed(4)} TON</div>
                )}
                <div className="text-[10px] text-gray-500 mt-0.5">{formatCity(tonToCity(playerDetails.user?.balance_ton || 0))} $CITY</div>
              </div>
              <div className="p-2 rounded-lg bg-gray-900/40">
                <div className="text-xs text-gray-500">Бонусный баланс TON</div>
                {editMode ? (
                  <Input type="number" step="0.01" value={editData.bonus_balance} onChange={(e) => setEditData({...editData, bonus_balance: parseFloat(e.target.value)})} className="h-7 bg-gray-800 border-gray-600 text-white text-xs" data-testid="admin-edit-bonus-balance" />
                ) : (
                  <div className="text-amber-400 font-bold" data-testid="admin-bonus-balance">{(playerDetails.user?.bonus_balance || 0).toFixed(4)} TON</div>
                )}
                <div className="text-[10px] text-gray-500 mt-0.5">{formatCity(tonToCity(playerDetails.user?.bonus_balance || 0))} $CITY</div>
              </div>
              <div className="p-2 rounded-lg bg-gray-900/40 col-span-2">
                <div className="text-xs text-gray-500">Суммарный баланс (реальный + бонусный)</div>
                <div className="text-green-400 font-bold" data-testid="admin-total-balance">
                  {((playerDetails.user?.balance_ton || 0) + (playerDetails.user?.bonus_balance || 0)).toFixed(4)} TON
                  <span className="text-gray-400 font-normal ml-2">= {formatCity(tonToCity((playerDetails.user?.balance_ton || 0) + (playerDetails.user?.bonus_balance || 0)))} $CITY</span>
                </div>
              </div>
              <div className="p-2 rounded-lg bg-gray-900/40">
                <div className="text-xs text-gray-500">Общий доход</div>
                <div className="text-green-400">{(playerDetails.user?.total_income || 0).toFixed(4)} TON</div>
              </div>
              <div className="p-2 rounded-lg bg-gray-900/40">
                <div className="text-xs text-gray-500">TON Кошелёк</div>
                <div className="text-white text-xs font-mono break-all">{playerDetails.user?.wallet_address ? toUserFriendlyAddress(playerDetails.user.wallet_address) : '—'}</div>
              </div>
              <div className="p-2 rounded-lg bg-gray-900/40">
                <div className="text-xs text-gray-500">Уровень</div>
                <div className="text-white">{playerDetails.user?.level || 'novice'} (XP: {playerDetails.user?.xp || 0})</div>
              </div>
              <div className="p-2 rounded-lg bg-gray-900/40">
                <div className="text-xs text-gray-500">Имя</div>
                {editMode ? (
                  <Input value={editData.display_name} onChange={(e) => setEditData({...editData, display_name: e.target.value})} className="h-7 bg-gray-800 border-gray-600 text-white text-xs" />
                ) : (
                  <div className="text-white">{playerDetails.user?.display_name}</div>
                )}
              </div>
              <div className="p-2 rounded-lg bg-gray-900/40">
                <div className="text-xs text-gray-500">Регистрация</div>
                <div className="text-white text-xs">{playerDetails.user?.created_at ? new Date(playerDetails.user.created_at).toLocaleDateString('ru') : '—'}</div>
              </div>
              <div className="p-2 rounded-lg bg-gray-900/40" data-testid="admin-player-language">
                <div className="text-xs text-gray-500">Язык в проекте</div>
                <div className="text-white text-xs">{playerLangLabel(playerDetails.language || playerDetails.user?.language)}</div>
              </div>
              <div className="p-2 rounded-lg bg-gray-900/40" data-testid="admin-player-telegram">
                <div className="text-xs text-gray-500">Telegram</div>
                {playerDetails.telegram_linked ? (
                  <div className="text-xs">
                    <span className="text-green-400 font-bold">✅ Привязан</span>
                    <span className="text-gray-400"> · язык: </span>
                    <span className="text-white">{playerLangLabel(playerDetails.telegram_language)}</span>
                  </div>
                ) : (
                  <div className="text-xs text-gray-400">🚫 Не привязан</div>
                )}
              </div>
            </div>

            {/* Блокировка аккаунта */}
            <div className="p-3 rounded-lg bg-gray-900/40 border border-red-500/20" data-testid="admin-account-block-section">
              <div className="text-xs font-bold text-gray-400 mb-2">🚫 Блокировка аккаунта</div>
              {playerDetails.user?.is_blocked ? (
                <div className="space-y-2">
                  <div className="text-xs text-red-300">
                    Заблокирован. Причина: <span className="text-white">{playerDetails.user?.block_reason || '—'}</span>
                  </div>
                  <Button size="sm" onClick={unblockAccount} data-testid="admin-unblock-account-btn" className="h-7 text-xs bg-green-600 hover:bg-green-700">
                    Разблокировать
                  </Button>
                </div>
              ) : (
                <div className="space-y-2">
                  <Input
                    value={accBlockReason}
                    onChange={(e) => setAccBlockReason(e.target.value)}
                    placeholder="Причина блокировки (на русском)"
                    data-testid="admin-block-reason-input"
                    className="h-8 bg-gray-800 border-gray-600 text-white text-xs"
                  />
                  <Button size="sm" onClick={blockAccount} data-testid="admin-block-account-btn" className="h-7 text-xs bg-red-600 hover:bg-red-700">
                    Заблокировать пользователя
                  </Button>
                </div>
              )}
            </div>

            {/* Resources */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <div className="text-xs font-bold text-gray-400">📦 Ресурсы</div>
                {resourcesEdit === null ? (
                  <Button size="sm" variant="ghost" onClick={startResourcesEdit} data-testid="admin-edit-resources-btn" className="h-6 text-xs text-amber-400 hover:bg-amber-500/10">
                    <Edit2 className="w-3 h-3 mr-1" /> Изменить
                  </Button>
                ) : (
                  <div className="flex gap-1">
                    <Button size="sm" onClick={saveResources} data-testid="admin-save-resources-btn" className="h-6 text-xs bg-green-600 hover:bg-green-700">
                      <Save className="w-3 h-3 mr-1" /> Сохранить
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setResourcesEdit(null)} className="h-6 text-xs text-gray-400">
                      <X className="w-3 h-3" />
                    </Button>
                  </div>
                )}
              </div>
              {resourcesEdit === null ? (
                Object.keys(playerDetails.user?.resources || {}).length > 0 ? (
                  <div className="grid grid-cols-3 gap-1">
                    {Object.entries(playerDetails.user.resources).map(([r, a]) => {
                      const meta = resourceCatalog[r] || {};
                      const label = meta.name_ru || r;
                      return (
                        <div key={r} className="p-1.5 rounded-lg bg-gray-900/30 text-xs" title={r}>
                          <span className="text-gray-500">{meta.icon || ''} {label}:</span> <span className="text-white font-mono">{typeof a === 'number' ? a.toFixed(0) : a}</span>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="text-xs text-gray-500">Нет ресурсов</div>
                )
              ) : (
                <div className="space-y-2">
                  <div className="grid grid-cols-2 gap-1 max-h-40 overflow-y-auto">
                    {Object.entries(resourcesEdit).map(([r, a]) => {
                      const meta = resourceCatalog[r] || {};
                      return (
                        <div key={r} className="flex items-center gap-1 p-1 rounded bg-gray-900/40">
                          <span className="text-xs text-gray-400 w-24 truncate" title={r}>{meta.icon || ''} {meta.name_ru || r}</span>
                          <Input
                            type="number"
                            value={a}
                            onChange={(e) => setResourcesEdit({ ...resourcesEdit, [r]: parseFloat(e.target.value) || 0 })}
                            className="h-6 bg-gray-800 border-gray-600 text-white text-xs flex-1"
                            data-testid={`admin-res-input-${r}`}
                          />
                          <button
                            type="button"
                            onClick={() => {
                              const { [r]: _, ...rest } = resourcesEdit;
                              setResourcesEdit(rest);
                            }}
                            className="text-red-400 hover:text-red-300 p-1"
                            title="Удалить ресурс"
                          >
                            <Trash2 className="w-3 h-3" />
                          </button>
                        </div>
                      );
                    })}
                  </div>
                  <div className="flex gap-1 pt-1">
                    <select
                      value={newResName}
                      onChange={(e) => setNewResName(e.target.value)}
                      className="h-7 bg-gray-800 border border-gray-600 rounded text-white text-xs flex-1 px-1"
                      data-testid="admin-new-res-select"
                    >
                      <option value="">— выбрать ресурс —</option>
                      {Object.entries(resourceCatalog)
                        .sort((a, b) => (a[1]?.tier || 1) - (b[1]?.tier || 1))
                        .map(([code, meta]) => (
                          <option key={code} value={code} disabled={resourcesEdit && Object.prototype.hasOwnProperty.call(resourcesEdit, code)}>
                            {meta.icon || ''} {meta.name_ru || code} (T{meta.tier || 1})
                          </option>
                        ))}
                    </select>
                    <Input
                      type="number"
                      placeholder="кол-во"
                      max={MAX_PRICE_VALUE}
                      value={newResAmount}
                      onChange={(e) => {
                        const v = e.target.value;
                        if (v === '') { setNewResAmount(''); return; }
                        const n = Number(v);
                        setNewResAmount(Number.isFinite(n) && n > MAX_PRICE_VALUE ? String(MAX_PRICE_VALUE) : v);
                      }}
                      className="h-7 bg-gray-800 border-gray-600 text-white text-xs w-20"
                      data-testid="admin-new-res-amount"
                    />
                    <Button size="sm" onClick={addResource} className="h-7 text-xs bg-cyan-600 hover:bg-cyan-700">+</Button>
                  </div>
                </div>
              )}
            </div>

            {/* Businesses */}
            <div>
              <div className="text-xs font-bold text-gray-400 mb-2">🏢 Бизнесы ({playerDetails.businesses_count})</div>
              <div className="space-y-1">
                {playerDetails.businesses?.map(b => (
                  <div key={b.id}>
                  <div
                    className="flex items-center justify-between p-2 rounded-lg bg-gray-900/30 hover:bg-gray-900/60 text-xs gap-2 cursor-pointer transition-colors"
                    data-testid={`admin-biz-row-${b.id}`}
                    onClick={() => setExpandedBiz(prev => prev === b.id ? null : b.id)}
                  >
                    <span className="text-white flex-1 truncate flex items-center gap-1">
                      {expandedBiz === b.id ? <ChevronDown className="w-3 h-3 text-gray-400" /> : <ChevronRight className="w-3 h-3 text-gray-400" />}
                      {b.business_type} L{b.level}
                    </span>
                    <span className="text-cyan-400 text-[10px]">💎 {b.durability?.toFixed(0)}%</span>
                    <div className="flex gap-0.5">
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); changeBusinessLevel(b.id, b.level, +1); }}
                        className="p-1 rounded hover:bg-green-500/20 text-green-400"
                        title="+1 уровень"
                        data-testid={`admin-biz-lvlup-${b.id}`}
                      >
                        <ChevronUp className="w-3 h-3" />
                      </button>
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); changeBusinessLevel(b.id, b.level, -1); }}
                        className="p-1 rounded hover:bg-amber-500/20 text-amber-400"
                        title="-1 уровень"
                        data-testid={`admin-biz-lvldown-${b.id}`}
                      >
                        <ChevronDown className="w-3 h-3" />
                      </button>
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); repairBusiness(b.id); }}
                        className="p-1 rounded hover:bg-cyan-500/20 text-cyan-400"
                        title="Восстановить прочность"
                        data-testid={`admin-biz-repair-${b.id}`}
                      >
                        <Shield className="w-3 h-3" />
                      </button>
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); deleteBusiness(b.id, `${b.business_type} L${b.level}`); }}
                        className="p-1 rounded hover:bg-red-500/20 text-red-400"
                        title="Удалить бизнес"
                        data-testid={`admin-biz-delete-${b.id}`}
                      >
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </div>
                  </div>
                  {expandedBiz === b.id && (
                    <div className="mt-1 mb-1 ml-4 p-2 rounded-lg bg-gray-950/60 border border-white/5 text-[11px] space-y-2" data-testid={`admin-biz-detail-${b.id}`}>
                      <div>
                        <div className="text-emerald-400 font-semibold mb-1">🟢 Производит (в сутки)</div>
                        {(b.produces_detail && b.produces_detail.length > 0) ? (
                          b.produces_detail.map((p, i) => (
                            <div key={i} className="flex justify-between text-gray-300 pl-2">
                              <span>{p.name || p.resource}</span>
                              <span className="font-mono text-emerald-300">+{Number(p.per_day).toLocaleString('ru-RU')}</span>
                            </div>
                          ))
                        ) : (
                          <div className="text-gray-500 pl-2">—</div>
                        )}
                      </div>
                      <div>
                        <div className="text-rose-400 font-semibold mb-1">🔴 Потребляет (в сутки)</div>
                        {(b.consumes_detail && b.consumes_detail.length > 0) ? (
                          b.consumes_detail.map((c, i) => (
                            <div key={i} className="flex justify-between text-gray-300 pl-2">
                              <span>{c.name || c.resource}</span>
                              <span className="font-mono text-rose-300">−{Number(c.per_day).toLocaleString('ru-RU')}</span>
                            </div>
                          ))
                        ) : (
                          <div className="text-gray-500 pl-2">Ничего не потребляет</div>
                        )}
                      </div>
                    </div>
                  )}
                  </div>
                ))}
                {playerDetails.businesses_count === 0 && <div className="text-xs text-gray-500">Нет бизнесов</div>}
              </div>
            </div>

            {/* Referrals */}
            <div className="p-3 rounded-xl bg-gray-900/50 border border-cyan-700/30 space-y-3">
              {/* Who referred THIS player + assign/change control */}
              <div className="flex items-center justify-between gap-2 pb-2 border-b border-white/5" data-testid="admin-referrer-row">
                <div className="text-xs min-w-0">
                  <span className="text-gray-500">Реферер: </span>
                  {playerDetails.referrer ? (
                    <span className="text-white font-bold truncate" data-testid="admin-referrer-name">
                      @{playerDetails.referrer.username || playerDetails.referrer.display_name || playerDetails.referrer.id}
                    </span>
                  ) : (
                    <span className="text-gray-500" data-testid="admin-referrer-none">не назначен</span>
                  )}
                </div>
                <button
                  type="button"
                  onClick={openReferrerModal}
                  data-testid="admin-referrer-assign-btn"
                  className="shrink-0 px-3 py-1.5 rounded-lg text-xs font-bold bg-violet-500/20 text-violet-300 border border-violet-500/40 hover:bg-violet-500/30 transition-all"
                >
                  {playerDetails.referrer ? 'Изменить' : 'Назначить'}
                </button>
              </div>
              <div className="flex items-center justify-between">
                <div className="text-xs font-bold text-cyan-400" data-testid="admin-referrals-badge">
                  🔗 Рефералы: <span className="text-white">{playerDetails.referral_count ?? 0}</span>
                </div>
                <button
                  type="button"
                  onClick={() => (showReferrals ? setShowReferrals(false) : loadPlayerReferrals(selectedPlayer))}
                  data-testid="admin-referrals-btn"
                  className="px-3 py-1.5 rounded-lg text-xs font-bold bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 hover:bg-cyan-500/30 transition-all"
                >
                  {showReferrals ? 'Скрыть' : 'Подробнее'}
                </button>
              </div>
              {showReferrals && referralInfo && (
                <div className="space-y-2" data-testid="admin-referrals-panel">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-gray-500">Приглашено пользователей:</span>
                    <span className="text-white font-bold" data-testid="admin-referrals-count">{referralInfo.count}</span>
                  </div>
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-gray-500">Доход от рефералов:</span>
                    <span className="text-cyan-400 font-bold">{(referralInfo.total_earned_city ?? 0).toLocaleString()} $CITY</span>
                  </div>
                  <div>
                    <div className="text-gray-500 text-xs mb-1">Персональная реф-ссылка:</div>
                    <div className="flex gap-1">
                      <code
                        className="flex-1 min-w-0 truncate text-cyan-300 text-[11px] font-mono bg-black/40 px-2 py-1.5 rounded border border-cyan-500/20"
                        data-testid="admin-referral-link"
                      >
                        {`${window.location.origin}${referralInfo.referral_path}`}
                      </code>
                      <button
                        type="button"
                        onClick={() => { navigator.clipboard.writeText(`${window.location.origin}${referralInfo.referral_path}`); toast.success('Ссылка скопирована!'); }}
                        className="shrink-0 px-2 rounded bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 hover:bg-cyan-500/30"
                        title="Копировать"
                      >
                        📋
                      </button>
                    </div>
                  </div>
                  {referralInfo.referrals?.length > 0 && (
                    <div className="max-h-48 overflow-y-auto space-y-1 pt-1">
                      {referralInfo.referrals.map((r, i) => (
                        <div key={i} className="flex items-center justify-between p-2 rounded-lg bg-gray-900/40 text-xs" data-testid={`admin-referral-row-${i}`}>
                          <span className="text-white truncate">{r.username}</span>
                          <span className="text-cyan-400 whitespace-nowrap">+{(r.earned_city ?? 0).toLocaleString()} $CITY</span>
                        </div>
                      ))}
                    </div>
                  )}
                  {referralInfo.count === 0 && <div className="text-xs text-gray-500">Нет приглашённых пользователей</div>}
                </div>
              )}
            </div>

            {/* Referrer assign/change modal */}
            {showReferrerModal && (
              <div
                className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm"
                data-testid="admin-referrer-modal"
                onClick={() => setShowReferrerModal(false)}
              >
                <div
                  className="w-full max-w-md rounded-2xl border border-violet-500/30 bg-[#0b0f17] p-5 shadow-2xl space-y-3"
                  onClick={(e) => e.stopPropagation()}
                >
                  <div className="flex items-center justify-between">
                    <h3 className="text-sm font-bold text-violet-300">
                      {playerDetails.referrer ? 'Изменить реферера' : 'Назначить реферера'}
                    </h3>
                    <button type="button" onClick={() => setShowReferrerModal(false)} className="p-1 rounded hover:bg-white/10 text-gray-400">
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                  <div className="text-xs text-gray-400">
                    Игрок: <span className="text-white font-semibold">@{playerDetails.user?.username}</span>
                  </div>
                  {playerDetails.referrer && (
                    <div className="text-xs p-2 rounded-lg bg-gray-900/50 border border-white/5">
                      <span className="text-gray-500">Текущий реферер: </span>
                      <span className="text-white font-bold" data-testid="admin-referrer-current">
                        @{playerDetails.referrer.username || playerDetails.referrer.display_name || playerDetails.referrer.id}
                      </span>
                    </div>
                  )}
                  <div>
                    <div className="text-[11px] text-gray-500 mb-1">Найти нового реферера (username / email / id)</div>
                    <div className="relative">
                      <Search className="w-4 h-4 absolute left-2 top-1/2 -translate-y-1/2 text-gray-500" />
                      <Input
                        autoFocus
                        placeholder="Введите имя пользователя..."
                        value={refSearch}
                        onChange={(e) => searchReferrerCandidates(e.target.value)}
                        className="bg-white/5 border-white/10 text-white pl-8 h-9 text-sm"
                        data-testid="admin-referrer-search-input"
                      />
                    </div>
                  </div>
                  <div className="max-h-64 overflow-y-auto space-y-1" data-testid="admin-referrer-results">
                    {refSearchLoading && <div className="text-xs text-gray-500 py-2 text-center">Поиск...</div>}
                    {!refSearchLoading && refSearch.trim() && refResults.length === 0 && (
                      <div className="text-xs text-gray-500 py-2 text-center">Ничего не найдено</div>
                    )}
                    {refResults.map((p) => (
                      <div
                        key={p.id}
                        className="flex items-center justify-between gap-2 p-2 rounded-lg bg-gray-900/40 hover:bg-gray-800/60 transition-colors"
                        data-testid={`admin-referrer-candidate-${p.id}`}
                      >
                        <div className="min-w-0">
                          <div className="text-white text-sm font-semibold truncate">@{p.username || '—'}</div>
                          <div className="text-[10px] text-gray-500 truncate">{p.email || p.id}</div>
                        </div>
                        <button
                          type="button"
                          disabled={refSaving}
                          onClick={() => assignReferrer(p.id)}
                          data-testid={`admin-referrer-pick-${p.id}`}
                          className="shrink-0 px-3 py-1.5 rounded-lg text-xs font-bold bg-violet-500/20 text-violet-300 border border-violet-500/40 hover:bg-violet-500/30 disabled:opacity-50 transition-all"
                        >
                          Назначить
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {/* Admin Withdraw / Block controls */}
            <div className="p-3 rounded-xl bg-gray-900/50 border border-amber-700/30 space-y-3">
              <div className="text-xs font-bold text-amber-400 flex items-center gap-1">
                <Lock className="w-3 h-3" /> Управление выводом средств
              </div>

              {/* Withdraw status */}
              {playerDetails.user?.withdrawal_blocked_until || playerDetails.user?.withdraw_lock_until ? (
                <div className="p-2 rounded bg-red-900/30 border border-red-700/40 text-xs text-red-300">
                  <div className="flex items-center gap-1 font-bold mb-1">
                    <Lock className="w-3 h-3" /> Вывод заблокирован
                  </div>
                  <div className="text-[11px]">
                    до {new Date(playerDetails.user.withdrawal_blocked_until || playerDetails.user.withdraw_lock_until).toLocaleString('ru-RU')}
                  </div>
                  {playerDetails.user?.withdrawal_block_reason && (
                    <div className="text-[11px] mt-1 text-gray-400">Причина: {playerDetails.user.withdrawal_block_reason}</div>
                  )}
                  <Button size="sm" onClick={unblockWithdrawal} data-testid="admin-unblock-withdraw-btn" className="h-7 text-xs mt-2 bg-emerald-600 hover:bg-emerald-700 w-full">
                    <Unlock className="w-3 h-3 mr-1" /> Разблокировать
                  </Button>
                </div>
              ) : (
                <div className="space-y-1">
                  <div className="text-[11px] text-gray-400">Заблокировать вывод</div>
                  <div className="flex gap-1">
                    <Input
                      type="number"
                      value={blockHours}
                      onChange={(e) => setBlockHours(e.target.value)}
                      placeholder="часов"
                      className="h-7 bg-gray-800 border-gray-600 text-white text-xs w-20"
                      data-testid="admin-block-hours"
                    />
                    <Input
                      value={blockReason}
                      onChange={(e) => setBlockReason(e.target.value)}
                      placeholder="причина (необязательно)"
                      className="h-7 bg-gray-800 border-gray-600 text-white text-xs flex-1"
                      data-testid="admin-block-reason"
                    />
                    <Button size="sm" onClick={blockWithdrawal} data-testid="admin-block-withdraw-btn" className="h-7 text-xs bg-red-600 hover:bg-red-700">
                      <Lock className="w-3 h-3 mr-1" />
                    </Button>
                  </div>
                </div>
              )}
            </div>

            {/* Plots */}
            <div>
              <div className="text-xs font-bold text-gray-400 mb-2">🗺️ Участки ({playerDetails.plots_count})</div>
              {playerDetails.plots_count === 0 && <div className="text-xs text-gray-500">Нет участков</div>}
            </div>

            {/* Device / Multi-account / Login History */}
            <div className="p-3 rounded-xl bg-gray-900/50 border border-gray-700/30">
              <div className="flex items-center justify-between mb-2">
                <div className="text-xs font-bold text-gray-400">📱 Устройство и IP</div>
                <button
                  type="button"
                  onClick={() => (showTx ? setShowTx(false) : loadPlayerTransactions(selectedPlayer))}
                  data-testid="admin-transactions-btn"
                  disabled={txLoading}
                  className="shrink-0 px-3 py-1.5 rounded-lg text-xs font-bold bg-amber-500/20 text-amber-300 border border-amber-500/40 hover:bg-amber-500/30 transition-all disabled:opacity-50"
                >
                  {txLoading ? 'Загрузка…' : (showTx ? 'Скрыть транзакции' : '💳 Транзакции')}
                </button>
              </div>
              <div className="space-y-1 text-xs">
                <div className="flex justify-between">
                  <span className="text-gray-500">IP:</span>
                  <span className="text-white font-mono">{playerDetails.user?.last_ip || 'Не определено'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-500">Браузер:</span>
                  <span className="text-white">{playerDetails.user?.last_browser || 'Не определено'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-500">Устройство:</span>
                  <span className="text-white">{playerDetails.user?.last_device || 'Не определено'}</span>
                </div>
              </div>

              {/* All transactions tied to this user */}
              {showTx && (
                <div className="mt-3" data-testid="admin-transactions-panel">
                  <div className="text-xs font-bold text-gray-400 mb-1">
                    💳 Транзакции пользователя ({txList.length}):
                  </div>
                  {txList.length === 0 ? (
                    <div className="text-xs text-gray-500">Транзакций не найдено</div>
                  ) : (
                    <div className="space-y-1 max-h-72 overflow-y-auto">
                      {txList.map((tx, i) => (
                        <div key={tx.id || i} className="p-2 rounded-lg bg-gray-800/50 text-xs" data-testid={`admin-tx-row-${i}`}>
                          <div className="flex items-center justify-between gap-2">
                            <span className="text-white font-semibold truncate">
                              {tx.type_icon || '💱'} {tx.type_name || tx.tx_type}
                            </span>
                            <span className={`font-mono whitespace-nowrap ${((tx.amount_ton ?? tx.amount) || 0) < 0 ? 'text-red-400' : 'text-green-400'}`}>
                              {((tx.amount_ton ?? tx.amount) || 0).toFixed(4)} TON
                            </span>
                          </div>
                          {tx.description && <div className="text-gray-400 mt-0.5">{tx.description}</div>}
                          <div className="flex items-center justify-between gap-2 mt-0.5 text-[10px] text-gray-500">
                            <span>
                              {tx.created_at ? new Date(tx.created_at).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' }) : ''}
                            </span>
                            {tx.status_display && <span>{tx.status_display}</span>}
                          </div>
                          {(tx.buyer_username || tx.seller_username) && (
                            <div className="text-[10px] text-gray-500 mt-0.5">
                              {tx.buyer_username && <span>Покупатель: <span className="text-cyan-400">{tx.buyer_username}</span> </span>}
                              {tx.seller_username && <span>Продавец: <span className="text-cyan-400">{tx.seller_username}</span></span>}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
              
              {/* Login history */}
              {playerDetails.user?.login_history?.length > 0 && (
                <div className="mt-3">
                  <div className="text-xs font-bold text-gray-400 mb-1">История входов (последние {playerDetails.user.login_history.length}):</div>
                  <div className="space-y-1 max-h-40 overflow-y-auto">
                    {[...playerDetails.user.login_history].reverse().map((entry, i) => (
                      <div key={i} className="p-1.5 rounded bg-gray-800/50 text-xs flex items-center gap-2">
                        <span className="text-gray-500 w-28 shrink-0">{new Date(entry.timestamp).toLocaleString('ru-RU', {day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'})}</span>
                        <span className="text-cyan-400 font-mono w-28 shrink-0">{entry.ip}</span>
                        <span className="text-white">{entry.browser}</span>
                        <span className="text-gray-500">{entry.device}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              
              {playerDetails.is_multi_account && (
                <div className="mt-3 p-2 rounded-lg bg-red-900/30 border border-red-700/50">
                  <div className="flex items-center gap-2 text-red-400 font-bold text-sm">
                    <AlertTriangle className="w-4 h-4" />
                    {playerDetails.multi_account_warning}
                  </div>
                </div>
              )}
              
              {playerDetails.same_device_accounts?.length > 0 && (
                <div className="mt-2 space-y-1">
                  <div className="text-xs text-gray-400">Аккаунты на этом устройстве:</div>
                  {playerDetails.same_device_accounts.map((a, i) => (
                    <div key={i} className="p-1.5 rounded-lg bg-red-900/20 text-xs flex justify-between">
                      <span className="text-white">{a.display_name || a.username || a.id?.slice(0, 12)}</span>
                      <span className="text-gray-500">{a.wallet_address ? shortenAddress(toUserFriendlyAddress(a.wallet_address)) : ''}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function PricesTab({ token, headers }) {
  const [prices, setPrices] = useState({});
  const [editPrices, setEditPrices] = useState({});
  const [loading, setLoading] = useState(true);
  const [botResource, setBotResource] = useState('');
  const [botAmount, setBotAmount] = useState(100);
  const [botPrice, setBotPrice] = useState(0);
  const [botListings, setBotListings] = useState([]);

  const loadPrices = async () => {
    try {
      const res = await axios.get(`${API}/admin/market/prices`, { headers });
      setPrices(res.data.prices || {});
      const edits = {};
      Object.entries(res.data.prices || {}).forEach(([r, d]) => {
        edits[r] = d.current_price;
      });
      setEditPrices(edits);
    } catch (e) {
      toast.error('Ошибка загрузки цен');
    }
    setLoading(false);
  };

  const loadBotListings = async () => {
    try {
      const res = await axios.get(`${API}/admin/market/bot-listings`, { headers });
      setBotListings(res.data.listings || []);
    } catch (e) {}
  };

  const savePrices = async () => {
    try {
      const updates = {};
      Object.entries(editPrices).forEach(([r, p]) => {
        if (prices[r] && Math.abs(p - prices[r].current_price) > 0.0001) {
          updates[r] = Math.max(0.01, p);
        }
      });
      if (Object.keys(updates).length === 0) {
        toast.info('Нет изменений');
        return;
      }
      await axios.post(`${API}/admin/market/prices/update`, updates, { headers });
      toast.success(`Обновлено ${Object.keys(updates).length} цен`);
      loadPrices();
    } catch (e) {
      toast.error('Ошибка сохранения');
    }
  };

  const stabilizeResource = async (resource) => {
    const target = editPrices[resource] || prices[resource]?.base_price;
    try {
      await axios.post(`${API}/admin/market/stabilize?resource=${resource}&target_price=${target}`, {}, { headers });
      toast.success(`Бот-стабилизатор запущен для ${resource}`);
    } catch (e) {
      toast.error('Ошибка запуска стабилизатора');
    }
  };

  const createBotListing = async () => {
    if (!botResource) { toast.error('Выберите ресурс'); return; }
    if (botAmount <= 0) { toast.error('Количество должно быть > 0'); return; }
    try {
      const res = await axios.post(`${API}/admin/market/bot-listing`, {
        resource_type: botResource,
        amount: botAmount,
        price_per_unit: botPrice > 0 ? botPrice : 0,
      }, { headers });
      toast.success(`Бот выставил ${res.data.amount} ${res.data.icon} ${res.data.resource_name} по ${res.data.price_per_unit} $CITY`);
      setBotResource('');
      setBotAmount(100);
      setBotPrice(0);
      loadBotListings();
    } catch (e) {
      toast.error('Ошибка создания листинга');
    }
  };

  const removeBotListing = async (id) => {
    try {
      await axios.delete(`${API}/admin/market/bot-listing/${id}`, { headers });
      toast.success('Листинг удалён');
      loadBotListings();
    } catch (e) {
      toast.error('Ошибка удаления');
    }
  };

  useEffect(() => { loadPrices(); loadBotListings(); }, []);

  if (loading) return <div className="text-gray-500 text-center py-8">Загрузка цен...</div>;

  return (
    <div className="space-y-6">
      {/* Section: Resource prices */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-bold text-gray-300">💰 Управление ценами ресурсов ($CITY)</h3>
          <Button onClick={savePrices} size="sm" className="bg-green-600 hover:bg-green-700">
            <Save className="w-3 h-3 mr-1" /> Сохранить
          </Button>
        </div>

        <div className="space-y-2">
          {Object.entries(prices).sort((a, b) => (a[1].tier || 0) - (b[1].tier || 0)).map(([resource, data]) => (
            <div key={resource} className="flex items-center gap-3 p-3 rounded-xl bg-gray-800/30 border border-gray-700/30">
              <span className="text-xl w-8 text-center">{data.icon}</span>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-white">{data.name_ru}</div>
                <div className="text-xs text-gray-500">Tier {data.tier} • Дефолт: {data.base_price} $CITY</div>
              </div>
              <div className="flex items-center gap-2">
                <Input
                  type="number"
                  step="0.1"
                  min="0.01"
                  max={MAX_PRICE_VALUE}
                  value={editPrices[resource] || 0}
                  onChange={(e) => setEditPrices({...editPrices, [resource]: Math.min(MAX_PRICE_VALUE, parseFloat(e.target.value) || 0.01)})}
                  className="w-24 h-8 bg-gray-900 border-gray-600 text-white text-xs text-right"
                />
                <span className="text-xs text-gray-500 w-12">$CITY</span>
                <Button size="sm" variant="ghost" onClick={() => stabilizeResource(resource)} className="text-amber-400 hover:bg-amber-900/20 text-xs h-8 px-2" title="Стабилизатор">
                  <Shield className="w-3 h-3 mr-1" /> Бот
                </Button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Section: Bot listings */}
      <div className="space-y-4">
        <h3 className="text-sm font-bold text-gray-300">🤖 Бот-листинг: выставить товар на торговлю</h3>
        <div className="p-4 rounded-xl bg-gray-800/30 border border-cyan-500/20 space-y-3">
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="text-xs text-text-muted block mb-1">Ресурс</label>
              <select
                value={botResource}
                onChange={(e) => {
                  setBotResource(e.target.value);
                  const base = prices[e.target.value]?.base_price || 0;
                  setBotPrice(base);
                }}
                className="w-full h-9 bg-gray-900 border border-gray-600 rounded-md text-white text-sm px-2"
              >
                <option value="">Выберите...</option>
                {Object.entries(prices).sort((a, b) => (a[1].tier || 0) - (b[1].tier || 0)).map(([r, d]) => (
                  <option key={r} value={r}>{d.icon} {d.name_ru}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs text-text-muted block mb-1">Количество</label>
              <Input
                type="number"
                min="1"
                max={MAX_PRICE_VALUE}
                value={botAmount}
                onChange={(e) => setBotAmount(Math.min(MAX_PRICE_VALUE, parseInt(e.target.value) || 0))}
                className="h-9 bg-gray-900 border-gray-600 text-white text-sm"
              />
            </div>
            <div>
              <label className="text-xs text-text-muted block mb-1">Цена за ед. ($CITY)</label>
              <Input
                type="number"
                step="0.1"
                min="0"
                max={MAX_PRICE_VALUE}
                value={botPrice}
                onChange={(e) => setBotPrice(Math.min(MAX_PRICE_VALUE, parseFloat(e.target.value) || 0))}
                className="h-9 bg-gray-900 border-gray-600 text-white text-sm"
                placeholder="0 = дефолт"
              />
            </div>
          </div>
          <Button onClick={createBotListing} size="sm" className="bg-cyan-600 hover:bg-cyan-700 w-full">
            Выставить от бота
          </Button>
        </div>

        {botListings.length > 0 && (
          <div className="space-y-2">
            <div className="text-xs text-text-muted">Активные бот-листинги ({botListings.length}):</div>
            {botListings.map(l => (
              <div key={l.id} className="flex items-center gap-3 p-2 rounded-lg bg-gray-800/20 border border-gray-700/30 text-sm">
                <span className="text-lg">{prices[l.resource_type]?.icon || '📦'}</span>
                <span className="text-white flex-1">{prices[l.resource_type]?.name_ru || l.resource_type}</span>
                <span className="text-cyan-400 font-mono">{l.amount} шт</span>
                <span className="text-amber-400 font-mono">{l.price_per_unit} $CITY</span>
                <Button size="sm" variant="ghost" onClick={() => removeBotListing(l.id)} className="text-red-400 hover:bg-red-900/20 h-7 px-2">
                  <Trash2 className="w-3 h-3" />
                </Button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
