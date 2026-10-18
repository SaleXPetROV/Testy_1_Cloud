import { useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import { toast } from 'sonner';
import {
  Plus, Trash2, RefreshCw, Copy, Edit3, Save, X,
  Users, TrendingUp, Coins, ExternalLink, Link2,
  Handshake, ScrollText, CheckCircle2, XCircle, Power, Download,
} from 'lucide-react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api`;

const fmtTON = (v) => {
  const n = Number(v || 0);
  if (!isFinite(n)) return '0';
  if (n === 0) return '0';
  if (Math.abs(n) < 0.0001) return n.toExponential(2);
  return n.toFixed(n < 1 ? 4 : 2).replace(/\.?0+$/, '');
};

export default function B2BPartnersTab() {
  const [partners, setPartners] = useState([]);
  const [loading, setLoading] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [newUsername, setNewUsername] = useState('');
  const [newSalesPct, setNewSalesPct] = useState('');
  const [newYieldPct, setNewYieldPct] = useState('');
  const [newTgId, setNewTgId] = useState('');
  const [editId, setEditId] = useState(null);
  const [editData, setEditData] = useState({});
  const [expanded, setExpanded] = useState(new Set());

  const token = (typeof window !== 'undefined') ? localStorage.getItem('token') : null;
  const hdr = useMemo(() => ({ headers: { Authorization: `Bearer ${token}` } }), [token]);

  const fetchPartners = async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API}/admin/b2b/partners`, hdr);
      setPartners(res.data.partners || []);
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Ошибка загрузки');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchPartners(); }, []);

  const createPartner = async () => {
    const username = newUsername.trim().replace(/^@/, '');
    if (!username) { toast.error('Укажите username'); return; }
    const sp = parseFloat(newSalesPct || '0');
    const yp = parseFloat(newYieldPct || '0');
    if (isNaN(sp) || sp < 0 || sp > 100) { toast.error('sales % должен быть 0..100'); return; }
    if (isNaN(yp) || yp < 0 || yp > 100) { toast.error('yield % должен быть 0..100'); return; }
    try {
      await axios.post(`${API}/admin/b2b/partners`, {
        username,
        sales_percent: sp,
        yield_percent: yp,
        telegram_user_id: newTgId.trim() || null,
      }, hdr);
      toast.success('Партнёр создан');
      setNewUsername(''); setNewSalesPct(''); setNewYieldPct(''); setNewTgId('');
      setShowAdd(false);
      fetchPartners();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Ошибка создания');
    }
  };

  const startEdit = (p) => {
    setEditId(p.partner_id);
    setEditData({
      username: p.username || '',
      sales_percent: String(p.sales_percent ?? 0),
      yield_percent: String(p.yield_percent ?? 0),
      telegram_user_id: p.telegram_user_id || '',
    });
  };

  const saveEdit = async (partnerId) => {
    const sp = parseFloat(editData.sales_percent || '0');
    const yp = parseFloat(editData.yield_percent || '0');
    if (isNaN(sp) || sp < 0 || sp > 100) { toast.error('sales % должен быть 0..100'); return; }
    if (isNaN(yp) || yp < 0 || yp > 100) { toast.error('yield % должен быть 0..100'); return; }
    try {
      const payload = {
        username: editData.username.trim().replace(/^@/, '') || undefined,
        sales_percent: sp,
        yield_percent: yp,
        telegram_user_id: editData.telegram_user_id.trim() || null,
      };
      await axios.patch(`${API}/admin/b2b/partners/${partnerId}`, payload, hdr);
      toast.success('Сохранено');
      setEditId(null); setEditData({});
      fetchPartners();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Ошибка сохранения');
    }
  };

  const deletePartner = async (p) => {
    if (!window.confirm(`Удалить B2B партнёра @${p.username}?`)) return;
    try {
      await axios.delete(`${API}/admin/b2b/partners/${p.partner_id}`, hdr);
      toast.success('Партнёр удалён');
      fetchPartners();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Ошибка удаления');
    }
  };

  const copyLink = async (link) => {
    try {
      await navigator.clipboard.writeText(link);
      toast.success('Ссылка скопирована');
    } catch (e) {
      toast.error('Не удалось скопировать');
    }
  };

  const toggleExpand = (id) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  return (
    <div className="space-y-4" data-testid="admin-b2b-partners-tab">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-xl font-bold text-white">B2B партнёры</h2>
          <p className="text-xs text-white/50 mt-1">
            Партнёрам начисляются % с продажи земли и % с прибыли активных рефералов. Статистика видна партнёру в Telegram-боте.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={fetchPartners}
            disabled={loading}
            className="px-3 py-2 bg-white/5 hover:bg-white/10 border border-white/10 text-white/80 rounded-lg text-xs flex items-center gap-2 disabled:opacity-50"
            data-testid="b2b-refresh-btn"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> Обновить
          </button>
          <button
            onClick={() => setShowAdd((v) => !v)}
            className="px-4 py-2 bg-cyan-500 hover:bg-cyan-400 text-white rounded-lg text-sm font-semibold flex items-center gap-2"
            data-testid="b2b-add-partner-btn"
          >
            <Plus className="w-4 h-4" /> Добавить партнёра
          </button>
        </div>
      </div>

      {showAdd && (
        <div className="bg-cyan-500/10 border border-cyan-400/30 rounded-xl p-4 space-y-3" data-testid="b2b-add-form">
          <h3 className="text-sm font-bold text-white">Новый B2B партнёр</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-2">
            <input
              value={newUsername}
              onChange={(e) => setNewUsername(e.target.value)}
              placeholder="Telegram @username"
              className="bg-black/40 border border-white/15 rounded-lg px-3 py-2 text-sm text-white placeholder-white/30"
              data-testid="b2b-new-username"
            />
            <input
              value={newTgId}
              onChange={(e) => setNewTgId(e.target.value)}
              placeholder="Telegram user_id (необязательно)"
              className="bg-black/40 border border-white/15 rounded-lg px-3 py-2 text-sm text-white placeholder-white/30"
              data-testid="b2b-new-tgid"
            />
            <input
              value={newSalesPct}
              onChange={(e) => setNewSalesPct(e.target.value)}
              placeholder="Sales % (с продажи земли)"
              type="number"
              min="0" max="100" step="0.01"
              className="bg-black/40 border border-white/15 rounded-lg px-3 py-2 text-sm text-white placeholder-white/30"
              data-testid="b2b-new-sales-pct"
            />
            <input
              value={newYieldPct}
              onChange={(e) => setNewYieldPct(e.target.value)}
              placeholder="Yield % (с прибыли реферала)"
              type="number"
              min="0" max="100" step="0.01"
              className="bg-black/40 border border-white/15 rounded-lg px-3 py-2 text-sm text-white placeholder-white/30"
              data-testid="b2b-new-yield-pct"
            />
          </div>
          <div className="flex gap-2">
            <button onClick={createPartner} className="px-4 py-1.5 bg-emerald-500 hover:bg-emerald-400 text-white rounded text-xs font-semibold" data-testid="b2b-create-submit">
              Создать
            </button>
            <button onClick={() => setShowAdd(false)} className="px-3 py-1.5 bg-white/10 hover:bg-white/20 text-white rounded text-xs">
              Отмена
            </button>
          </div>
        </div>
      )}

      {/* Partners Table */}
      <div className="bg-white/5 border border-white/10 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-white/5 text-left text-xs text-white/60 uppercase">
              <tr>
                <th className="p-3">Партнёр</th>
                <th className="p-3">Реф. ссылка</th>
                <th className="p-3 text-right">Sales %</th>
                <th className="p-3 text-right">Yield %</th>
                <th className="p-3 text-right">Игроков</th>
                <th className="p-3 text-right" title="Пользователи, входившие в игру за последние 7 дней">Активных за 7 дней</th>
                <th className="p-3 text-right">Всего заработано</th>
                <th className="p-3 text-right">Действия</th>
              </tr>
            </thead>
            <tbody>
              {partners.length === 0 ? (
                <tr>
                  <td colSpan="8" className="text-center text-white/40 py-8" data-testid="b2b-empty">
                    Нет партнёров. Нажмите «Добавить партнёра».
                  </td>
                </tr>
              ) : partners.map((p) => {
                const isEdit = editId === p.partner_id;
                const isOpen = expanded.has(p.partner_id);
                return (
                  <>
                    <tr key={p.partner_id} className="border-t border-white/5 hover:bg-white/[0.03]" data-testid={`b2b-row-${p.partner_id}`}>
                      <td className="p-3">
                        {isEdit ? (
                          <input
                            value={editData.username}
                            onChange={(e) => setEditData((d) => ({ ...d, username: e.target.value }))}
                            className="bg-black/40 border border-white/15 rounded px-2 py-1 text-xs text-white w-32"
                            data-testid={`b2b-edit-username-${p.partner_id}`}
                          />
                        ) : (
                          <div>
                            <div className="text-white font-semibold flex items-center gap-1">
                              <a
                                href={`https://t.me/${p.username}`}
                                target="_blank"
                                rel="noreferrer"
                                className="hover:text-cyan-300 flex items-center gap-1"
                              >
                                @{p.username}
                                <ExternalLink className="w-3 h-3 opacity-60" />
                              </a>
                            </div>
                            <div className="text-[10px] text-white/40 font-mono">
                              code: {p.partner_code}
                            </div>
                          </div>
                        )}
                        {isEdit && (
                          <input
                            value={editData.telegram_user_id}
                            onChange={(e) => setEditData((d) => ({ ...d, telegram_user_id: e.target.value }))}
                            placeholder="tg_user_id"
                            className="bg-black/40 border border-white/15 rounded px-2 py-1 text-[10px] text-white w-32 mt-1"
                          />
                        )}
                      </td>
                      <td className="p-3">
                        <div className="flex items-center gap-1.5 max-w-[280px]">
                          <Link2 className="w-3 h-3 text-cyan-300 shrink-0" />
                          <span className="text-[11px] text-cyan-300 font-mono truncate" title={p.referral_link}>
                            {p.referral_link}
                          </span>
                          <button
                            onClick={() => copyLink(p.referral_link)}
                            className="p-1 hover:bg-white/10 rounded shrink-0"
                            title="Копировать"
                            data-testid={`b2b-copy-${p.partner_id}`}
                          >
                            <Copy className="w-3 h-3" />
                          </button>
                        </div>
                      </td>
                      <td className="p-3 text-right">
                        {isEdit ? (
                          <input
                            value={editData.sales_percent}
                            onChange={(e) => setEditData((d) => ({ ...d, sales_percent: e.target.value }))}
                            type="number" min="0" max="100" step="0.01"
                            className="bg-black/40 border border-white/15 rounded px-2 py-1 text-xs text-white w-20 text-right"
                            data-testid={`b2b-edit-sales-${p.partner_id}`}
                          />
                        ) : (
                          <span className="font-mono text-emerald-300">{p.sales_percent}%</span>
                        )}
                      </td>
                      <td className="p-3 text-right">
                        {isEdit ? (
                          <input
                            value={editData.yield_percent}
                            onChange={(e) => setEditData((d) => ({ ...d, yield_percent: e.target.value }))}
                            type="number" min="0" max="100" step="0.01"
                            className="bg-black/40 border border-white/15 rounded px-2 py-1 text-xs text-white w-20 text-right"
                            data-testid={`b2b-edit-yield-${p.partner_id}`}
                          />
                        ) : (
                          <span className="font-mono text-amber-300">{p.yield_percent}%</span>
                        )}
                      </td>
                      <td className="p-3 text-right font-mono text-white">{p.stats?.total_users ?? 0}</td>
                      <td className="p-3 text-right font-mono text-cyan-300">{p.stats?.active_users_7d ?? 0}</td>
                      <td className="p-3 text-right font-mono text-emerald-300">{fmtTON(p.stats?.earn_total)} TON</td>
                      <td className="p-3 text-right">
                        <div className="flex items-center justify-end gap-1">
                          {isEdit ? (
                            <>
                              <button
                                onClick={() => saveEdit(p.partner_id)}
                                className="p-1.5 bg-emerald-500/20 hover:bg-emerald-500/40 text-emerald-300 rounded"
                                title="Сохранить"
                                data-testid={`b2b-save-${p.partner_id}`}
                              >
                                <Save className="w-3.5 h-3.5" />
                              </button>
                              <button
                                onClick={() => { setEditId(null); setEditData({}); }}
                                className="p-1.5 bg-white/10 hover:bg-white/20 rounded"
                                title="Отмена"
                              >
                                <X className="w-3.5 h-3.5" />
                              </button>
                            </>
                          ) : (
                            <>
                              <button
                                onClick={() => toggleExpand(p.partner_id)}
                                className="p-1.5 bg-white/10 hover:bg-white/20 rounded text-white/80"
                                title="Подробная статистика"
                                data-testid={`b2b-expand-${p.partner_id}`}
                              >
                                <TrendingUp className="w-3.5 h-3.5" />
                              </button>
                              <button
                                onClick={() => startEdit(p)}
                                className="p-1.5 bg-white/10 hover:bg-white/20 rounded text-white/80"
                                title="Редактировать"
                                data-testid={`b2b-edit-${p.partner_id}`}
                              >
                                <Edit3 className="w-3.5 h-3.5" />
                              </button>
                              <button
                                onClick={() => deletePartner(p)}
                                className="p-1.5 bg-red-500/20 hover:bg-red-500/40 text-red-300 rounded"
                                title="Удалить"
                                data-testid={`b2b-delete-${p.partner_id}`}
                              >
                                <Trash2 className="w-3.5 h-3.5" />
                              </button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                    {isOpen && !isEdit && (
                      <tr key={`${p.partner_id}-details`} className="border-t border-white/5 bg-black/20">
                        <td colSpan="8" className="p-4">
                          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
                            <StatCard icon={<Users className="w-4 h-4" />} label="За 24ч" value={`+${p.stats?.users_24h ?? 0}`} tone="cyan" />
                            <StatCard icon={<Users className="w-4 h-4" />} label="За 7 дней" value={`+${p.stats?.users_7d ?? 0}`} tone="cyan" />
                            <StatCard icon={<Users className="w-4 h-4" />} label="За 30 дней" value={`+${p.stats?.users_30d ?? 0}`} tone="cyan" />
                            <StatCard icon={<Coins className="w-4 h-4" />} label="Сегодня" value={`${fmtTON(p.stats?.earn_today)} TON`} tone="emerald" />
                            <StatCard icon={<Coins className="w-4 h-4" />} label="За 7 дней" value={`${fmtTON(p.stats?.earn_7d)} TON`} tone="emerald" />
                            <StatCard icon={<Coins className="w-4 h-4" />} label="За 30 дней" value={`${fmtTON(p.stats?.earn_30d)} TON`} tone="emerald" />
                          </div>
                          <div className="mt-3 text-[11px] text-white/40 font-mono">
                            Partner ID: {p.partner_id}
                          </div>
                        </td>
                      </tr>
                    )}
                  </>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <PartnerProgramsSection />
    </div>
  );
}

function StatCard({ icon, label, value, tone = 'cyan' }) {
  const toneCls = tone === 'emerald' ? 'text-emerald-300' : 'text-cyan-300';
  return (
    <div className="bg-white/5 border border-white/10 rounded-lg p-3">
      <div className="flex items-center gap-1.5 text-[10px] uppercase text-white/50 mb-1">
        <span className={toneCls}>{icon}</span> {label}
      </div>
      <div className={`font-mono text-base font-bold ${toneCls}`}>{value}</div>
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════════════
// Partner Programs (incoming verification): admin pastes the partner's in-game
// ref link + conditions, gets a unique verify URL to hand to the partner, and
// can open a logs modal.
// ═══════════════════════════════════════════════════════════════════════════
const emptyProgram = {
  name: '', ref_link: '', require_land: true,
  min_market_spend_city: '100', per_active_user_city: '', income_percent: '',
  tma_base_url: 'https://t.me/GramCityBot/app',
  require_business_upgrade: false, upgrade_from_level: '0', upgrade_to_level: '1',
};

// Pure client-side generator (mirror of the backend). Kept for instant preview
// and reuse; the backend is the source of truth on create/save.
export function generateTmaRefLink(webUrl, tmaBaseUrl) {
  try {
    const parsed = new URL(webUrl);
    const refId = parsed.searchParams.get('ref')
      || parsed.searchParams.get('startapp')
      || parsed.searchParams.get('start');
    if (!refId) throw new Error('Параметр ?ref= (или startapp) не найден в веб-ссылке');
    let base = (tmaBaseUrl || '').trim();
    if (!base) throw new Error('Укажите базовую ссылку Telegram Mini App');
    if (!/:\/\//.test(base)) base = 'https://' + base;
    const b = new URL(base);
    b.searchParams.set('startapp', refId);
    if (b.pathname.length > 1 && b.pathname.endsWith('/')) b.pathname = b.pathname.slice(0, -1);
    return b.toString();
  } catch (e) {
    return null;
  }
}

function PartnerProgramsSection() {
  const [programs, setPrograms] = useState([]);
  const [loading, setLoading] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState(emptyProgram);
  const [creating, setCreating] = useState(false);
  const [logsFor, setLogsFor] = useState(null); // program object
  const [logs, setLogs] = useState([]);
  const [logsFilter, setLogsFilter] = useState('all');
  const [logsLoading, setLogsLoading] = useState(false);
  // Referred-players ("Логи") modal state
  const [playersFor, setPlayersFor] = useState(null);   // program object
  const [players, setPlayers] = useState([]);
  const [playersSearch, setPlayersSearch] = useState('');
  const [playersLoading, setPlayersLoading] = useState(false);
  const [playersMeta, setPlayersMeta] = useState({ clicks_count: 0, unique_users_count: 0, new_users_count: 0, completed_count: 0, min_market_spend_city: 0, require_land: true, require_business_upgrade: false, upgrade_from_level: 0, upgrade_to_level: 1 });
  const [chart, setChart] = useState(null);
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [genTma, setGenTma] = useState('');       // generated TMA link (create form)
  const [genLoading, setGenLoading] = useState(false);
  const [cardTmaBase, setCardTmaBase] = useState({}); // {programId: baseUrl}
  const [cardTmaLoading, setCardTmaLoading] = useState(null);
  const [editRates, setEditRates] = useState({});     // {programId: {per, income}}
  const [savingRates, setSavingRates] = useState(null);

  const token = (typeof window !== 'undefined') ? localStorage.getItem('token') : null;
  const hdr = useMemo(() => ({ headers: { Authorization: `Bearer ${token}` } }), [token]);

  const fullVerifyUrl = (p) => `${BACKEND_URL}${p.verify_path || `/api/partner/verify/${p.api_key}?user_id=USER_ID`}`;

  const fetchPrograms = async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API}/admin/partner-programs`, hdr);
      setPrograms(res.data.programs || []);
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Ошибка загрузки программ');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchPrograms(); }, []);

  const createProgram = async () => {
    if (!form.name.trim()) return toast.error('Укажите название партнёра');
    if (!/\?ref=|\/ref\/|=/.test(form.ref_link) && !form.ref_link.trim()) return toast.error('Вставьте реф-ссылку партнёра');
    if (!form.ref_link.trim()) return toast.error('Вставьте реф-ссылку партнёра');
    setCreating(true);
    try {
      const payload = {
        name: form.name.trim(),
        ref_link: form.ref_link.trim(),
        require_land: !!form.require_land,
        min_market_spend_city: parseFloat(form.min_market_spend_city) || 0,
        require_business_upgrade: !!form.require_business_upgrade,
        upgrade_from_level: parseInt(form.upgrade_from_level, 10) || 0,
        upgrade_to_level: parseInt(form.upgrade_to_level, 10) || 1,
        per_active_user_city: parseFloat(form.per_active_user_city) || 0,
        income_percent: parseFloat(form.income_percent) || 0,
        tma_base_url: (form.tma_base_url || '').trim() || null,
      };
      const res = await axios.post(`${API}/admin/partner-programs`, payload, hdr);
      toast.success('Партнёрская программа создана');
      setForm(emptyProgram);
      setGenTma('');
      setShowAdd(false);
      await fetchPrograms();
      // Copy the verify URL for convenience
      const created = res.data?.program;
      if (created) {
        try { await navigator.clipboard.writeText(fullVerifyUrl(created)); toast.success('URL проверки скопирован'); } catch {}
      }
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Ошибка создания');
    } finally {
      setCreating(false);
    }
  };

  // "Сгенерировать реф-ссылку" — build a direct Telegram Mini App link from the
  // pasted web ref link + the TMA base url (validated by the backend).
  const generateTma = async () => {
    if (!form.ref_link.trim()) return toast.error('Сначала вставьте реф-ссылку партнёра');
    if (!(form.tma_base_url || '').trim()) return toast.error('Укажите базовую ссылку Telegram Mini App');
    setGenLoading(true);
    try {
      const res = await axios.post(`${API}/admin/partner-programs/generate-tma-link`, {
        web_ref_url: form.ref_link.trim(),
        tma_base_url: form.tma_base_url.trim(),
      }, hdr);
      setGenTma(res.data?.tma_ref_url || '');
      toast.success('Реф-ссылка для Telegram Mini App сгенерирована');
    } catch (e) {
      setGenTma('');
      toast.error(e.response?.data?.detail || 'Ошибка генерации ссылки');
    } finally {
      setGenLoading(false);
    }
  };

  // Generate + SAVE a TMA link for an already-created program.
  const saveCardTma = async (p) => {
    const base = (cardTmaBase[p.id] ?? p.tma_base_url ?? 'https://t.me/GramCityBot/app').trim();
    if (!base) return toast.error('Укажите базовую ссылку Telegram Mini App');
    setCardTmaLoading(p.id);
    try {
      await axios.post(`${API}/admin/partner-programs/${p.id}/tma-link`, { tma_base_url: base }, hdr);
      toast.success('Реф-ссылка сгенерирована и сохранена');
      await fetchPrograms();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Ошибка генерации ссылки');
    } finally {
      setCardTmaLoading(null);
    }
  };

  const toggleActive = async (p) => {
    try {
      await axios.patch(`${API}/admin/partner-programs/${p.id}`, { active: !p.active }, hdr);
      fetchPrograms();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Ошибка');
    }
  };

  // Draft edits for the program conditions + payout rates. Falls back to the
  // saved program value for any field the admin hasn't touched yet. Lets the
  // admin change the task on the fly (e.g. switch "buy land" → "upgrade
  // business", or change levels / spend) WITHOUT deleting the program.
  const updateRateDraft = (p, key, val) => setEditRates((m) => {
    const base = {
      per: String(p.per_active_user_city ?? 0),
      income: String(p.income_percent ?? 0),
      require_land: !!p.require_land,
      min_market_spend_city: String(p.min_market_spend_city ?? 0),
      require_business_upgrade: !!p.require_business_upgrade,
      upgrade_from_level: String(p.upgrade_from_level ?? 0),
      upgrade_to_level: String(p.upgrade_to_level ?? 1),
    };
    return { ...m, [p.id]: { ...base, ...(m[p.id] || {}), [key]: val } };
  });

  const draftVal = (p, key, dflt) => {
    const v = editRates[p.id]?.[key];
    return v === undefined ? dflt : v;
  };

  // Save program conditions + payout rates. This PATCH never touches the
  // api_key / verify_path, so the partner's verification URL stays identical.
  const saveRates = async (p) => {
    const draft = editRates[p.id] || {};
    const perNum = parseFloat(draft.per ?? p.per_active_user_city ?? 0);
    const incNum = parseFloat(draft.income ?? p.income_percent ?? 0);
    if (Number.isNaN(perNum) || perNum < 0) return toast.error('Некорректное начисление за активного');
    if (Number.isNaN(incNum) || incNum < 0 || incNum > 100) return toast.error('% дохода должен быть от 0 до 100');
    const fromLvl = parseInt(draft.upgrade_from_level ?? p.upgrade_from_level ?? 0, 10) || 0;
    const toLvl = parseInt(draft.upgrade_to_level ?? p.upgrade_to_level ?? 1, 10) || 1;
    const wantsUpgrade = draft.require_business_upgrade ?? !!p.require_business_upgrade;
    if (wantsUpgrade && toLvl <= fromLvl) return toast.error('Уровень «до» должен быть больше «с»');
    setSavingRates(p.id);
    try {
      await axios.patch(`${API}/admin/partner-programs/${p.id}`, {
        per_active_user_city: perNum,
        income_percent: incNum,
        require_land: draft.require_land ?? !!p.require_land,
        min_market_spend_city: parseFloat(draft.min_market_spend_city ?? p.min_market_spend_city ?? 0) || 0,
        require_business_upgrade: wantsUpgrade,
        upgrade_from_level: fromLvl,
        upgrade_to_level: toLvl,
      }, hdr);
      toast.success('Условия обновлены — ссылка проверки не изменилась');
      setEditRates((m) => { const n = { ...m }; delete n[p.id]; return n; });
      await fetchPrograms();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Ошибка сохранения');
    } finally {
      setSavingRates(null);
    }
  };

  const deleteProgram = async (p) => {
    if (!window.confirm(`Удалить партнёрскую программу «${p.name}»?`)) return;
    try {
      await axios.delete(`${API}/admin/partner-programs/${p.id}`, hdr);
      toast.success('Удалено');
      fetchPrograms();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Ошибка удаления');
    }
  };

  const copy = async (text) => {
    try { await navigator.clipboard.writeText(text); toast.success('Скопировано'); }
    catch { toast.error('Не удалось скопировать'); }
  };

  const openLogs = async (p, search = '', from = dateFrom, to = dateTo) => {
    setLogsFor(p);
    setPlayersSearch(search);
    setLogsLoading(true);
    try {
      const q = search ? `?search=${encodeURIComponent(search)}` : '';
      const res = await axios.get(`${API}/admin/partner-programs/${p.id}/referred-users${q}`, hdr);
      setPlayers(res.data.users || []);
      setPlayersMeta({
        clicks_count: res.data.clicks_count ?? 0,
        unique_users_count: res.data.unique_users_count ?? 0,
        new_users_count: res.data.new_users_count ?? 0,
        completed_count: res.data.completed_count ?? 0,
        min_market_spend_city: res.data.min_market_spend_city ?? 0,
        require_land: res.data.require_land ?? true,
        require_business_upgrade: res.data.require_business_upgrade ?? false,
        upgrade_from_level: res.data.upgrade_from_level ?? 0,
        upgrade_to_level: res.data.upgrade_to_level ?? 1,
      });
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Ошибка загрузки логов');
      setPlayers([]);
    } finally {
      setLogsLoading(false);
    }
    try {
      const chartRange = (from || to)
        ? `${from ? `date_from=${from}` : ''}${(from && to) ? '&' : ''}${to ? `date_to=${to}` : ''}`
        : 'days=14';
      const c = await axios.get(`${API}/admin/partner-programs/${p.id}/chart?${chartRange}`, hdr);
      setChart(c.data);
    } catch { setChart(null); }
  };

  const downloadCsv = async (p, filter) => {
    const range = `${dateFrom ? `&date_from=${dateFrom}` : ''}${dateTo ? `&date_to=${dateTo}` : ''}`;
    try {
      const res = await axios.get(`${API}/admin/partner-programs/${p.id}/logs.csv?status=${filter}${range}`, {
        ...hdr, responseType: 'blob',
      });
      const url = window.URL.createObjectURL(new Blob([res.data], { type: 'text/csv' }));
      const a = document.createElement('a');
      a.href = url;
      a.download = `partner_logs_${(p.name || 'partner').replace(/[^a-zA-Z0-9-_]/g, '')}_${filter}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
      toast.success('CSV скачан');
    } catch (e) {
      toast.error('Не удалось скачать CSV');
    }
  };

  return (
    <div className="space-y-4 pt-4 mt-2 border-t border-white/10" data-testid="partner-programs-section">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-xl font-bold text-white flex items-center gap-2">
            <Handshake className="w-5 h-5 text-cyan-300" /> Партнёрские программы (проверка условий)
          </h2>
          <p className="text-xs text-white/50 mt-1 max-w-2xl">
            Партнёр приводит своих пользователей по вашей реф-ссылке. Вставьте ссылку партнёра и задайте условия
            (покупка земли, трата на рынке в $CITY). Вы получите <b>уникальный URL проверки</b> — отправьте его партнёру.
            Его сервер вызывает URL с <code>user_id</code>; если условия выполнены — ответ <b>HTTP 200</b>.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={fetchPrograms} disabled={loading}
            className="px-3 py-2 bg-white/5 hover:bg-white/10 border border-white/10 text-white/80 rounded-lg text-xs flex items-center gap-2 disabled:opacity-50"
            data-testid="pp-refresh-btn">
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> Обновить
          </button>
          <button onClick={() => setShowAdd(v => !v)}
            className="px-4 py-2 bg-cyan-500 hover:bg-cyan-400 text-white rounded-lg text-sm font-semibold flex items-center gap-2"
            data-testid="pp-add-btn">
            <Plus className="w-4 h-4" /> Создать программу
          </button>
        </div>
      </div>

      {showAdd && (
        <div className="bg-cyan-500/10 border border-cyan-400/30 rounded-xl p-4 space-y-3" data-testid="pp-add-form">
          <h3 className="text-sm font-bold text-white">Новая партнёрская программа</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            <div>
              <label className="text-[11px] text-white/50">Название партнёра</label>
              <input value={form.name} onChange={(e) => setForm(f => ({ ...f, name: e.target.value }))}
                placeholder="Напр.: CryptoCrazy" className="w-full bg-black/40 border border-white/15 rounded-lg px-3 py-2 text-sm text-white placeholder-white/30"
                data-testid="pp-name" />
            </div>
            <div>
              <label className="text-[11px] text-white/50">Реф-ссылка партнёра (из аккаунта на проекте)</label>
              <input value={form.ref_link} onChange={(e) => setForm(f => ({ ...f, ref_link: e.target.value }))}
                placeholder="https://…/?ref=USER_ID" className="w-full bg-black/40 border border-white/15 rounded-lg px-3 py-2 text-sm text-white placeholder-white/30"
                data-testid="pp-ref-link" />
            </div>
            <div>
              <label className="text-[11px] text-white/50">Мин. трата на рынке ($CITY) — 0 = не требуется</label>
              <input type="number" min="0" value={form.min_market_spend_city}
                onChange={(e) => setForm(f => ({ ...f, min_market_spend_city: e.target.value }))}
                placeholder="100" className="w-full bg-black/40 border border-white/15 rounded-lg px-3 py-2 text-sm text-white placeholder-white/30"
                data-testid="pp-market" />
            </div>
            <div className="flex items-end gap-2 pb-1">
              <label className="flex items-center gap-2 text-sm text-white/80 cursor-pointer" data-testid="pp-require-land">
                <input type="checkbox" checked={form.require_land}
                  onChange={(e) => setForm(f => ({ ...f, require_land: e.target.checked }))}
                  className="w-4 h-4 rounded border-white/20 bg-white/5" />
                Требуется покупка земли
              </label>
            </div>
            <div className="sm:col-span-2 rounded-lg border border-white/10 bg-white/[0.03] p-3 flex flex-col gap-2">
              <label className="flex items-center gap-2 text-sm text-white/80 cursor-pointer" data-testid="pp-require-upgrade">
                <input type="checkbox" checked={form.require_business_upgrade}
                  onChange={(e) => setForm(f => ({ ...f, require_business_upgrade: e.target.checked }))}
                  className="w-4 h-4 rounded border-white/20 bg-white/5" />
                Задание: улучшение бизнеса
              </label>
              {form.require_business_upgrade && (
                <div className="flex items-center gap-3 pl-6">
                  <div className="flex flex-col">
                    <label className="text-[11px] text-white/50">С уровня</label>
                    <input type="number" min="0" value={form.upgrade_from_level}
                      onChange={(e) => setForm(f => ({ ...f, upgrade_from_level: e.target.value }))}
                      className="w-20 bg-black/40 border border-white/15 rounded-lg px-3 py-2 text-sm text-white"
                      data-testid="pp-upgrade-from" />
                  </div>
                  <span className="text-white/40 pt-4">→</span>
                  <div className="flex flex-col">
                    <label className="text-[11px] text-white/50">До уровня</label>
                    <input type="number" min="1" value={form.upgrade_to_level}
                      onChange={(e) => setForm(f => ({ ...f, upgrade_to_level: e.target.value }))}
                      className="w-20 bg-black/40 border border-white/15 rounded-lg px-3 py-2 text-sm text-white"
                      data-testid="pp-upgrade-to" />
                  </div>
                </div>
              )}
            </div>
            <div>
              <label className="text-[11px] text-white/50">Сумма партнёру за активного пользователя ($CITY)</label>
              <input type="number" min="0" value={form.per_active_user_city}
                onChange={(e) => setForm(f => ({ ...f, per_active_user_city: e.target.value }))}
                placeholder="0" className="w-full bg-black/40 border border-white/15 rounded-lg px-3 py-2 text-sm text-white placeholder-white/30"
                data-testid="pp-per-active" />
            </div>
            <div>
              <label className="text-[11px] text-white/50">% партнёру с дохода пользователя (замена обычного реф. %)</label>
              <input type="number" min="0" max="100" value={form.income_percent}
                onChange={(e) => setForm(f => ({ ...f, income_percent: e.target.value }))}
                placeholder="0" className="w-full bg-black/40 border border-white/15 rounded-lg px-3 py-2 text-sm text-white placeholder-white/30"
                data-testid="pp-income-pct" />
            </div>
          </div>
          <div className="rounded-lg border border-cyan-400/20 bg-black/30 p-3 space-y-2" data-testid="pp-tma-block">
            <label className="text-[11px] text-white/50 block">
              Базовая ссылка Telegram Mini App (для прямой реф-ссылки)
            </label>
            <div className="flex flex-col sm:flex-row gap-2">
              <input value={form.tma_base_url} onChange={(e) => setForm(f => ({ ...f, tma_base_url: e.target.value }))}
                placeholder="https://t.me/GramCityBot/app"
                className="flex-1 bg-black/40 border border-white/15 rounded-lg px-3 py-2 text-sm text-white placeholder-white/30 font-mono"
                data-testid="pp-tma-base" />
              <button onClick={generateTma} disabled={genLoading}
                className="px-4 py-2 bg-cyan-500 hover:bg-cyan-400 text-white rounded-lg text-xs font-semibold flex items-center gap-2 disabled:opacity-50 shrink-0"
                data-testid="pp-generate-tma-btn">
                <Link2 className="w-4 h-4" /> {genLoading ? 'Генерация…' : 'Сгенерировать реф-ссылку'}
              </button>
            </div>
            {genTma && (
              <div data-testid="pp-tma-result">
                <label className="text-[10px] uppercase text-white/40">Реф-ссылка Telegram Mini App</label>
                <div className="flex items-center gap-1.5 bg-black/40 border border-emerald-400/40 rounded-lg px-2.5 py-2 mt-1">
                  <Link2 className="w-3.5 h-3.5 text-emerald-300 shrink-0" />
                  <input readOnly value={genTma}
                    className="text-[12px] text-emerald-300 font-mono bg-transparent border-0 outline-none flex-1"
                    data-testid="pp-tma-output" onFocus={(e) => e.target.select()} />
                  <button onClick={() => copy(genTma)} className="p-1 hover:bg-white/10 rounded shrink-0" title="Копировать"
                    data-testid="pp-tma-copy">
                    <Copy className="w-3.5 h-3.5" />
                  </button>
                </div>
                <p className="text-[10px] text-white/40 mt-1">
                  Ссылка также сохранится в базе при нажатии «Создать и получить URL».
                </p>
              </div>
            )}
          </div>
          <p className="text-[10px] text-white/40">
            Внимание: когда реф-ссылка становится партнёрской, её владелец больше не получает обычный бонус 1.5 TON за активного реферала и обычный % с покупок — вместо этого действуют условия и суммы выше.
          </p>
          <div className="flex gap-2">
            <button onClick={createProgram} disabled={creating}
              className="px-4 py-1.5 bg-emerald-500 hover:bg-emerald-400 text-white rounded text-xs font-semibold disabled:opacity-50"
              data-testid="pp-create-submit">
              {creating ? 'Создание…' : 'Создать и получить URL'}
            </button>
            <button onClick={() => setShowAdd(false)} className="px-3 py-1.5 bg-white/10 hover:bg-white/20 text-white rounded text-xs">Отмена</button>
          </div>
        </div>
      )}

      {programs.length === 0 ? (
        <div className="text-center text-white/40 py-6 border border-white/10 rounded-xl" data-testid="pp-empty">
          Пока нет партнёрских программ.
        </div>
      ) : (
        <div className="space-y-3" data-testid="pp-list">
          {programs.map((p) => (
            <div key={p.id} className={`bg-white/5 border rounded-xl p-4 ${p.active ? 'border-white/10' : 'border-white/5 opacity-60'}`} data-testid={`pp-card-${p.id}`}>
              <div className="flex items-start justify-between gap-3 flex-wrap">
                <div className="min-w-0">
                  <div className="text-white font-semibold flex items-center gap-2">
                    <Handshake className="w-4 h-4 text-cyan-300" /> {p.name}
                    {!p.active && <span className="text-[10px] px-1.5 py-0.5 rounded bg-white/10 text-white/60">выкл</span>}
                  </div>
                  <div className="text-[11px] text-white/40 font-mono mt-0.5 truncate">ref: {p.ref_link}</div>
                  <div className="flex flex-wrap gap-2 mt-2 text-[11px]">
                    <span className="px-2 py-0.5 rounded bg-white/5 text-white/70">Земля: {p.require_land ? 'да' : 'нет'}</span>
                    <span className="px-2 py-0.5 rounded bg-white/5 text-white/70">Рынок: {p.min_market_spend_city} $CITY</span>
                    {p.require_business_upgrade && (
                      <span className="px-2 py-0.5 rounded bg-cyan-500/10 text-cyan-300" data-testid="pp-badge-upgrade">Апгрейд: ур.{p.upgrade_from_level ?? 0}→{p.upgrade_to_level ?? 1}</span>
                    )}
                    <span className="px-2 py-0.5 rounded bg-white/5 text-emerald-300">За активного: {p.per_active_user_city} $CITY</span>
                    <span className="px-2 py-0.5 rounded bg-white/5 text-amber-300">% дохода: {p.income_percent}%</span>
                    <span className="px-2 py-0.5 rounded bg-white/5 text-indigo-300" data-testid={`pp-clicks-${p.id}`}>Клики: {p.clicks_count ?? 0}</span>
                    <span className="px-2 py-0.5 rounded bg-white/5 text-teal-300" data-testid={`pp-unique-${p.id}`}>Уникальные пользователи: {p.unique_users_count ?? 0}</span>
                    <span className="px-2 py-0.5 rounded bg-white/5 text-sky-300" data-testid={`pp-total-referred-${p.id}`}>Перешло по ссылке: {p.new_users_count ?? 0}</span>
                    <span className="px-2 py-0.5 rounded bg-white/5 text-cyan-300" data-testid={`pp-completed-${p.id}`}>Выполнили условия: {p.completed_count ?? 0}</span>
                    <span className="px-2 py-0.5 rounded bg-white/5 text-emerald-300">Выплачено: {p.stats?.paid_city ?? 0} $CITY</span>
                  </div>
                </div>
                <div className="flex items-center gap-1.5 shrink-0">
                  <button onClick={() => openLogs(p)} className="px-2.5 py-1.5 bg-white/10 hover:bg-white/20 rounded text-white/80 text-xs flex items-center gap-1" title="Логи приведённых игроков и активность" data-testid={`pp-logs-btn-${p.id}`}>
                    <ScrollText className="w-3.5 h-3.5" /> Проверки
                  </button>
                  <button onClick={() => toggleActive(p)} className="p-1.5 bg-white/10 hover:bg-white/20 rounded text-white/80" title={p.active ? 'Выключить' : 'Включить'} data-testid={`pp-toggle-${p.id}`}>
                    <Power className="w-3.5 h-3.5" />
                  </button>
                  <button onClick={() => deleteProgram(p)} className="p-1.5 bg-red-500/20 hover:bg-red-500/40 text-red-300 rounded" title="Удалить" data-testid={`pp-delete-${p.id}`}>
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
              {/* Editable conditions + payout rates — saving these does NOT change the verify URL.
                  Меняйте условия задания на лету, без удаления программы. */}
              <div className="mt-3 flex flex-col gap-3 bg-black/20 border border-white/10 rounded-lg p-3" data-testid={`pp-edit-rates-${p.id}`}>
                <div className="text-[10px] uppercase tracking-wide text-white/40">Условия задания (можно менять на лету)</div>
                <div className="flex flex-wrap items-center gap-4">
                  <label className="flex items-center gap-2 text-xs text-white/80 cursor-pointer" data-testid={`pp-edit-require-land-${p.id}`}>
                    <input type="checkbox"
                      checked={!!draftVal(p, 'require_land', !!p.require_land)}
                      onChange={(e) => updateRateDraft(p, 'require_land', e.target.checked)}
                      className="w-4 h-4 rounded border-white/20 bg-white/5" />
                    Требуется покупка бизнеса/земли
                  </label>
                  <div className="flex items-center gap-2">
                    <label className="text-[10px] uppercase text-white/40">Трата на рынке ($CITY)</label>
                    <input type="number" min="0" step="1"
                      value={draftVal(p, 'min_market_spend_city', String(p.min_market_spend_city ?? 0))}
                      onChange={(e) => updateRateDraft(p, 'min_market_spend_city', e.target.value)}
                      className="w-24 bg-black/40 border border-white/15 rounded-lg px-2 py-1.5 text-xs text-white font-mono"
                      data-testid={`pp-edit-market-${p.id}`} />
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-3">
                  <label className="flex items-center gap-2 text-xs text-white/80 cursor-pointer" data-testid={`pp-edit-require-upgrade-${p.id}`}>
                    <input type="checkbox"
                      checked={!!draftVal(p, 'require_business_upgrade', !!p.require_business_upgrade)}
                      onChange={(e) => updateRateDraft(p, 'require_business_upgrade', e.target.checked)}
                      className="w-4 h-4 rounded border-white/20 bg-white/5" />
                    Задание: улучшение бизнеса
                  </label>
                  {!!draftVal(p, 'require_business_upgrade', !!p.require_business_upgrade) && (
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] uppercase text-white/40">С уровня</span>
                      <input type="number" min="0"
                        value={draftVal(p, 'upgrade_from_level', String(p.upgrade_from_level ?? 0))}
                        onChange={(e) => updateRateDraft(p, 'upgrade_from_level', e.target.value)}
                        className="w-16 bg-black/40 border border-white/15 rounded-lg px-2 py-1.5 text-xs text-white font-mono"
                        data-testid={`pp-edit-upgrade-from-${p.id}`} />
                      <span className="text-white/40">→</span>
                      <span className="text-[10px] uppercase text-white/40">До уровня</span>
                      <input type="number" min="1"
                        value={draftVal(p, 'upgrade_to_level', String(p.upgrade_to_level ?? 1))}
                        onChange={(e) => updateRateDraft(p, 'upgrade_to_level', e.target.value)}
                        className="w-16 bg-black/40 border border-white/15 rounded-lg px-2 py-1.5 text-xs text-white font-mono"
                        data-testid={`pp-edit-upgrade-to-${p.id}`} />
                    </div>
                  )}
                </div>
                <div className="flex flex-wrap items-end gap-3 pt-1 border-t border-white/10">
                  <div>
                    <label className="text-[10px] uppercase text-white/40 block mb-1">Начисление за активного ($CITY)</label>
                    <input
                      type="number" min="0" step="0.01"
                      value={editRates[p.id]?.per ?? String(p.per_active_user_city ?? 0)}
                      onChange={(e) => updateRateDraft(p, 'per', e.target.value)}
                      className="w-32 bg-black/40 border border-white/15 rounded-lg px-3 py-1.5 text-xs text-white font-mono"
                      data-testid={`pp-edit-per-active-${p.id}`} />
                  </div>
                  <div>
                    <label className="text-[10px] uppercase text-white/40 block mb-1">% дохода реферала</label>
                    <input
                      type="number" min="0" max="100" step="0.1"
                      value={editRates[p.id]?.income ?? String(p.income_percent ?? 0)}
                      onChange={(e) => updateRateDraft(p, 'income', e.target.value)}
                      className="w-32 bg-black/40 border border-white/15 rounded-lg px-3 py-1.5 text-xs text-white font-mono"
                      data-testid={`pp-edit-income-${p.id}`} />
                  </div>
                  <button
                    onClick={() => saveRates(p)}
                    disabled={savingRates === p.id}
                    className="px-3 py-1.5 bg-emerald-500 hover:bg-emerald-400 text-white rounded-lg text-xs font-semibold flex items-center gap-1.5 disabled:opacity-50 shrink-0"
                    data-testid={`pp-save-rates-${p.id}`}>
                    <Save className="w-3.5 h-3.5" /> {savingRates === p.id ? 'Сохранение…' : 'Сохранить условия'}
                  </button>
                  <span className="text-[10px] text-white/40">Ссылка проверки останется прежней</span>
                </div>
              </div>
              {/* Verify URL */}
              <div className="mt-3">
                <label className="text-[10px] uppercase text-white/40">URL проверки (отправьте партнёру)</label>
                <div className="flex items-center gap-1.5 bg-black/40 border border-cyan-400/30 rounded-lg px-2.5 py-2 mt-1">
                  <Link2 className="w-3.5 h-3.5 text-cyan-300 shrink-0" />
                  <span className="text-[11px] text-cyan-300 font-mono break-all flex-1" title={fullVerifyUrl(p)} data-testid={`pp-verify-url-${p.id}`}>{fullVerifyUrl(p)}</span>
                  <button onClick={() => copy(fullVerifyUrl(p))} className="p-1 hover:bg-white/10 rounded shrink-0" title="Копировать" data-testid={`pp-copy-url-${p.id}`}>
                    <Copy className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
              {/* TMA referral link (direct Telegram Mini App link) */}
              <div className="mt-3">
                <label className="text-[10px] uppercase text-white/40">Реф-ссылка Telegram Mini App</label>
                {p.tma_ref_url ? (
                  <div className="flex items-center gap-1.5 bg-black/40 border border-emerald-400/40 rounded-lg px-2.5 py-2 mt-1">
                    <Link2 className="w-3.5 h-3.5 text-emerald-300 shrink-0" />
                    <span className="text-[11px] text-emerald-300 font-mono break-all flex-1" title={p.tma_ref_url} data-testid={`pp-tma-url-${p.id}`}>{p.tma_ref_url}</span>
                    <button onClick={() => copy(p.tma_ref_url)} className="p-1 hover:bg-white/10 rounded shrink-0" title="Копировать" data-testid={`pp-tma-copy-${p.id}`}>
                      <Copy className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ) : (
                  <div className="text-[11px] text-white/40 mt-1">Ещё не сгенерирована.</div>
                )}
                <div className="flex flex-col sm:flex-row gap-2 mt-2">
                  <input
                    value={cardTmaBase[p.id] ?? p.tma_base_url ?? 'https://t.me/GramCityBot/app'}
                    onChange={(e) => setCardTmaBase(m => ({ ...m, [p.id]: e.target.value }))}
                    placeholder="https://t.me/GramCityBot/app"
                    className="flex-1 bg-black/40 border border-white/15 rounded-lg px-3 py-1.5 text-xs text-white placeholder-white/30 font-mono"
                    data-testid={`pp-tma-base-${p.id}`} />
                  <button onClick={() => saveCardTma(p)} disabled={cardTmaLoading === p.id}
                    className="px-3 py-1.5 bg-cyan-500 hover:bg-cyan-400 text-white rounded-lg text-xs font-semibold flex items-center gap-1.5 disabled:opacity-50 shrink-0"
                    data-testid={`pp-tma-generate-${p.id}`}>
                    <Link2 className="w-3.5 h-3.5" /> {cardTmaLoading === p.id ? 'Генерация…' : (p.tma_ref_url ? 'Обновить' : 'Сгенерировать реф-ссылку')}
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Logs modal ("Проверки") — activity chart + referred players + search */}
      {logsFor && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" data-testid="pp-logs-modal" onClick={() => setLogsFor(null)}>
          <div className="bg-[#12121f] border border-white/10 rounded-2xl w-full max-w-4xl max-h-[85vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between p-4 border-b border-white/10">
              <div>
                <h3 className="text-white font-bold flex items-center gap-2"><ScrollText className="w-4 h-4 text-cyan-300" /> Проверки: {logsFor.name}</h3>
                <div className="text-[11px] text-white/50 mt-1 flex gap-3 flex-wrap">
                  <span data-testid="pp-players-clicks">Клики: <b className="text-indigo-300">{playersMeta.clicks_count}</b></span>
                  <span data-testid="pp-players-unique">Уникальные: <b className="text-teal-300">{playersMeta.unique_users_count}</b></span>
                  <span>Перешло по ссылке: <b className="text-sky-300">{playersMeta.new_users_count}</b></span>
                  <span data-testid="pp-players-completed">Выполнили условия: <b className="text-emerald-300">{playersMeta.completed_count}</b></span>
                  <span className="text-white/40">Условия: {playersMeta.require_land ? 'земля + ' : ''}рынок ≥ {playersMeta.min_market_spend_city} $CITY{playersMeta.require_business_upgrade ? ` + апгрейд ур.${playersMeta.upgrade_from_level}→${playersMeta.upgrade_to_level}` : ''}</span>
                </div>
              </div>
              <button onClick={() => setLogsFor(null)} className="p-1.5 hover:bg-white/10 rounded" data-testid="pp-players-close"><X className="w-4 h-4 text-white/70" /></button>
            </div>
            <div className="flex flex-col gap-2 px-4 py-2 border-b border-white/5">
              <div className="flex items-center gap-2">
                <input
                  value={playersSearch}
                  onChange={(e) => setPlayersSearch(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') openLogs(logsFor, playersSearch); }}
                  placeholder="Поиск по username / telegram_id…"
                  className="flex-1 bg-black/40 border border-white/15 rounded-lg px-3 py-2 text-sm text-white placeholder-white/30"
                  data-testid="pp-players-search" />
                <button onClick={() => openLogs(logsFor, playersSearch)} className="px-3 py-2 bg-cyan-500 hover:bg-cyan-400 text-white rounded-lg text-xs font-semibold" data-testid="pp-players-search-btn">Найти</button>
                {playersSearch && (
                  <button onClick={() => openLogs(logsFor, '')} className="px-3 py-2 bg-white/5 hover:bg-white/10 text-white/70 rounded-lg text-xs" data-testid="pp-players-reset">Сброс</button>
                )}
              </div>
              <div className="flex items-center gap-2 flex-wrap text-xs text-white/60">
                <span>График с</span>
                <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)}
                  className="bg-black/40 border border-white/10 rounded px-2 py-1 text-white [color-scheme:dark]" data-testid="pp-logs-date-from" />
                <span>по</span>
                <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)}
                  className="bg-black/40 border border-white/10 rounded px-2 py-1 text-white [color-scheme:dark]" data-testid="pp-logs-date-to" />
                <button onClick={() => openLogs(logsFor, playersSearch, dateFrom, dateTo)}
                  className="px-3 py-1 rounded bg-cyan-500/80 hover:bg-cyan-500 text-white" data-testid="pp-logs-apply-dates">Применить</button>
                {(dateFrom || dateTo) && (
                  <button onClick={() => { setDateFrom(''); setDateTo(''); openLogs(logsFor, playersSearch, '', ''); }}
                    className="px-3 py-1 rounded bg-white/5 hover:bg-white/10 text-white/70" data-testid="pp-logs-reset-dates">Сбросить</button>
                )}
              </div>
            </div>
            {/* Activity chart — hover a bar to see the exact user counts */}
            {chart && chart.labels && chart.labels.length > 0 && (() => {
              const maxV = Math.max(1, ...chart.referrals, ...chart.completions);
              const bw = 100 / chart.labels.length;
              return (
                <div className="mx-4 mt-3 mb-1 rounded-lg border border-white/10 bg-black/30 p-3 font-sans shrink-0" data-testid="pp-chart">
                  <div className="flex items-center gap-4 mb-2 text-[11px]">
                    <span className="flex items-center gap-1 text-sky-300"><span className="w-2.5 h-2.5 rounded-sm bg-sky-400 inline-block" /> Переходы</span>
                    <span className="flex items-center gap-1 text-emerald-300"><span className="w-2.5 h-2.5 rounded-sm bg-emerald-400 inline-block" /> Выполнили</span>
                    <span className="text-white/40 ml-auto">{(dateFrom || dateTo) ? `${chart.labels[0]} — ${chart.labels[chart.labels.length - 1]}` : 'за 14 дней'}</span>
                  </div>
                  <svg viewBox="0 0 100 34" preserveAspectRatio="none" className="w-full h-24" data-testid="pp-chart-svg">
                    {chart.labels.map((d, i) => {
                      const rH = (chart.referrals[i] / maxV) * 30;
                      const cH = (chart.completions[i] / maxV) * 30;
                      const x = i * bw;
                      const tip = `${d}\nПереходы: ${chart.referrals[i]}\nВыполнили: ${chart.completions[i]}`;
                      return (
                        <g key={d} data-testid={`pp-chart-bar-${i}`}>
                          {/* transparent full-height hover target for an easy tooltip */}
                          <rect x={x} y="0" width={bw} height="32" fill="transparent">
                            <title>{tip}</title>
                          </rect>
                          <rect x={x + bw * 0.15} y={32 - rH} width={bw * 0.32} height={rH} fill="#38bdf8" rx="0.3"><title>{tip}</title></rect>
                          <rect x={x + bw * 0.52} y={32 - cH} width={bw * 0.32} height={cH} fill="#34d399" rx="0.3"><title>{tip}</title></rect>
                        </g>
                      );
                    })}
                    <line x1="0" y1="32" x2="100" y2="32" stroke="rgba(255,255,255,0.15)" strokeWidth="0.3" />
                  </svg>
                  <div className="flex justify-between text-[9px] text-white/30 mt-1">
                    <span>{chart.labels[0]?.slice(5)}</span>
                    <span>{chart.labels[chart.labels.length - 1]?.slice(5)}</span>
                  </div>
                </div>
              );
            })()}
            {/* Referred-players table (scrollable) */}
            <div className="flex-1 min-h-0 overflow-y-auto p-4" data-testid="pp-players-scroll">
              {logsLoading ? (
                <div className="text-center text-white/40 py-8">Загрузка…</div>
              ) : players.length === 0 ? (
                <div className="text-center text-white/40 py-8" data-testid="pp-players-empty">Нет приведённых игроков</div>
              ) : (
                <table className="w-full text-[12px]">
                  <thead className="text-white/40 text-left sticky top-0 bg-[#12121f]">
                    <tr>
                      <th className="p-2">Username</th>
                      <th className="p-2">Telegram ID</th>
                      <th className="p-2">Присоединился</th>
                      <th className="p-2 text-right">Земля</th>
                      <th className="p-2 text-right">Потрачено ($CITY)</th>
                      {playersMeta.require_business_upgrade && <th className="p-2 text-right">Апгрейд</th>}
                      <th className="p-2 text-center">Статус</th>
                    </tr>
                  </thead>
                  <tbody className="font-mono">
                    {players.map((u) => (
                      <tr key={u.user_id} className="border-t border-white/5" data-testid={`pp-player-row-${u.user_id}`}>
                        <td className="p-2 text-white/90">{u.username || '—'} {u.is_new ? <span className="text-[9px] text-sky-400">новый</span> : <span className="text-[9px] text-white/30">был</span>}</td>
                        <td className="p-2 text-white/60">{u.telegram_id || '—'}</td>
                        <td className="p-2 text-white/50">{u.partner_joined_at ? new Date(u.partner_joined_at).toLocaleString() : '—'}</td>
                        <td className={`p-2 text-right ${u.land_ok ? 'text-emerald-300' : 'text-white/50'}`}>{u.land_count}</td>
                        <td className={`p-2 text-right ${u.market_ok ? 'text-emerald-300' : 'text-white/50'}`}>{u.market_spent_city}</td>
                        {playersMeta.require_business_upgrade && <td className={`p-2 text-right ${u.upgrade_ok ? 'text-emerald-300' : 'text-white/50'}`}>{u.upgrade_count ?? 0}</td>}
                        <td className="p-2 text-center">
                          {u.partner_task_completed
                            ? <span className="inline-flex items-center gap-1 text-emerald-300" data-testid={`pp-player-done-${u.user_id}`}><CheckCircle2 className="w-3.5 h-3.5" /> Выполнено</span>
                            : <span className="inline-flex items-center gap-1 text-white/40"><XCircle className="w-3.5 h-3.5" /> В процессе</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
