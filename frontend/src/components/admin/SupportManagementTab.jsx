import { useEffect, useState } from 'react';
import axios from 'axios';
import { toast } from 'sonner';
import { Star, Plus, Edit2, Trash2, Activity, Eye, Upload, Headphones, Handshake } from 'lucide-react';
import B2BPartnersTab from './B2BPartnersTab';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api`;

export default function SupportManagementTab() {
  const [subTab, setSubTab] = useState('agents');
  return (
    <div className="space-y-4">
      <div className="inline-flex items-center gap-1 bg-white/5 border border-white/10 rounded-xl p-1" data-testid="support-subtabs">
        <button
          onClick={() => setSubTab('agents')}
          className={`px-4 py-2 rounded-lg text-xs font-semibold flex items-center gap-2 transition-colors ${
            subTab === 'agents' ? 'bg-cyan-500 text-white' : 'text-white/60 hover:text-white hover:bg-white/5'
          }`}
          data-testid="support-subtab-agents"
        >
          <Headphones className="w-3.5 h-3.5" /> Управление поддержкой
        </button>
        <button
          onClick={() => setSubTab('b2b')}
          className={`px-4 py-2 rounded-lg text-xs font-semibold flex items-center gap-2 transition-colors ${
            subTab === 'b2b' ? 'bg-cyan-500 text-white' : 'text-white/60 hover:text-white hover:bg-white/5'
          }`}
          data-testid="support-subtab-b2b"
        >
          <Handshake className="w-3.5 h-3.5" /> B2B партнёры
        </button>
      </div>
      {subTab === 'agents' ? <SupportAgentsPanel /> : <B2BPartnersTab />}
    </div>
  );
}

function SupportAgentsPanel() {
  const [agents, setAgents] = useState([]);
  const [loading, setLoading] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [newTgId, setNewTgId] = useState('');
  const [newName, setNewName] = useState('');
  const [editAgent, setEditAgent] = useState(null);
  const [editName, setEditName] = useState('');
  const [accessLogAgent, setAccessLogAgent] = useState(null);
  const [accessLog, setAccessLog] = useState([]);
  const [hiddenPath, setHiddenPath] = useState('');
  const [publicUrl, setPublicUrl] = useState('');
  const [publicUrlDraft, setPublicUrlDraft] = useState('');
  const [savingPublicUrl, setSavingPublicUrl] = useState(false);

  const token = (typeof window !== 'undefined') ? localStorage.getItem('token') : null;
  const hdr = { headers: { Authorization: `Bearer ${token}` } };

  const fetchAgents = async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API}/admin/support/agents`, hdr);
      setAgents(res.data.agents || []);
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Error');
    } finally {
      setLoading(false);
    }
  };

  const fetchSettings = async () => {
    try {
      const res = await axios.get(`${API}/admin/support/settings`, hdr);
      setHiddenPath(res.data.hidden_path || '');
      setPublicUrl(res.data.public_url || '');
      setPublicUrlDraft(res.data.public_url || '');
    } catch (e) { /* ignore */ }
  };

  const savePublicUrl = async () => {
    setSavingPublicUrl(true);
    try {
      const v = publicUrlDraft.trim().replace(/\/+$/, '');
      await axios.patch(`${API}/admin/support/settings`, { public_url: v }, hdr);
      setPublicUrl(v);
      toast.success(v ? 'Публичный URL сохранён' : 'Публичный URL сброшен (автоопределение)');
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Ошибка сохранения');
    } finally {
      setSavingPublicUrl(false);
    }
  };

  useEffect(() => { fetchAgents(); fetchSettings(); }, []);

  const addAgent = async () => {
    if (!newTgId.trim() || !newName.trim()) return;
    try {
      await axios.post(`${API}/admin/support/agents`, { telegram_id: newTgId.trim(), display_name: newName.trim() }, hdr);
      toast.success('Агент добавлен');
      setNewTgId(''); setNewName(''); setShowAdd(false);
      fetchAgents();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Error');
    }
  };

  const saveEditAgent = async () => {
    if (!editAgent) return;
    try {
      await axios.patch(`${API}/admin/support/agents/${editAgent.id}`, { display_name: editName }, hdr);
      toast.success('Сохранено');
      setEditAgent(null);
      fetchAgents();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Error');
    }
  };

  const removeAgent = async (id) => {
    if (!window.confirm('Удалить агента?')) return;
    try {
      await axios.delete(`${API}/admin/support/agents/${id}`, hdr);
      toast.success('Удалён');
      fetchAgents();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Error');
    }
  };

  const uploadAvatar = async (agentId, file) => {
    if (!file) return;
    const fd = new FormData();
    fd.append('file', file);
    try {
      await axios.post(`${API}/admin/support/agents/${agentId}/avatar`, fd, {
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'multipart/form-data' },
      });
      toast.success('Аватар обновлён');
      fetchAgents();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Error');
    }
  };

  const viewAccessLog = async (agentTgId) => {
    try {
      const res = await axios.get(`${API}/admin/support/agents/${agentTgId}/access-log`, hdr);
      setAccessLog(res.data.logs || []);
      setAccessLogAgent(agentTgId);
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Error');
    }
  };

  const fmtSec = (s) => {
    if (s == null) return '—';
    if (s < 60) return `${s.toFixed(0)}с`;
    return `${(s / 60).toFixed(1)}мин`;
  };

  const StatusBadge = ({ s }) => {
    const colors = { online: 'bg-emerald-500/20 text-emerald-300', busy: 'bg-amber-500/20 text-amber-300', offline: 'bg-white/10 text-white/40' };
    const labels = { online: 'В сети', busy: 'Занят', offline: 'Офлайн' };
    return <span className={`text-[10px] px-2 py-0.5 rounded-full ${colors[s]}`}>{labels[s]}</span>;
  };

  return (
    <div className="space-y-4" data-testid="admin-support-tab">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-xl font-bold text-white">Управление поддержкой</h2>
          {hiddenPath && (
            <div className="text-xs text-white/50 mt-1">
              Скрытый URL: <span className="font-mono text-cyan-300">/{hiddenPath}</span>
            </div>
          )}
          <div className="mt-3 flex items-center gap-2 flex-wrap" data-testid="public-url-row">
            <span className="text-xs text-white/50 shrink-0">Публичный URL бота:</span>
            <input
              value={publicUrlDraft}
              onChange={(e) => setPublicUrlDraft(e.target.value)}
              placeholder="https://gramcity.games"
              className="bg-black/40 border border-white/15 rounded-lg px-3 py-1.5 text-xs text-white font-mono min-w-[260px]"
              data-testid="public-url-input"
            />
            <button
              onClick={savePublicUrl}
              disabled={savingPublicUrl || publicUrlDraft === publicUrl}
              className="px-3 py-1.5 bg-emerald-500/90 hover:bg-emerald-500 disabled:opacity-40 text-white rounded text-xs"
              data-testid="public-url-save-btn"
            >
              {savingPublicUrl ? '...' : 'Сохранить'}
            </button>
            {!publicUrl && (
              <span className="text-[10px] text-amber-300">авто-определяется из webhook</span>
            )}
          </div>
          <div className="text-[10px] text-white/40 mt-1 max-w-md">
            Используется ботом при построении ссылок для агентов. Если пусто — бот возьмёт URL из переменной окружения <code>REACT_APP_BACKEND_URL</code> либо автоматически из <code>getWebhookInfo</code>.
          </div>
        </div>
        <button onClick={() => setShowAdd(true)} className="px-4 py-2 bg-cyan-500 text-white rounded-lg text-sm font-semibold flex items-center gap-2" data-testid="admin-add-agent-btn">
          <Plus className="w-4 h-4" /> Добавить агента
        </button>
      </div>

      {showAdd && (
        <div className="bg-cyan-500/10 border border-cyan-400/30 rounded-xl p-4 space-y-3" data-testid="admin-add-agent-form">
          <h3 className="text-sm font-bold text-white">Новый агент</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            <input value={newTgId} onChange={(e) => setNewTgId(e.target.value)} placeholder="Telegram ID" className="bg-black/40 border border-white/15 rounded-lg px-3 py-2 text-sm text-white" data-testid="admin-add-agent-tg" />
            <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="Имя агента" className="bg-black/40 border border-white/15 rounded-lg px-3 py-2 text-sm text-white" data-testid="admin-add-agent-name" />
          </div>
          <div className="flex gap-2">
            <button onClick={addAgent} className="px-3 py-1.5 bg-emerald-500 text-white rounded text-xs">Сохранить</button>
            <button onClick={() => setShowAdd(false)} className="px-3 py-1.5 bg-white/10 text-white rounded text-xs">Отмена</button>
          </div>
        </div>
      )}

      {/* Agents Table */}
      <div className="bg-white/5 border border-white/10 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-white/5 text-left text-xs text-white/60 uppercase">
            <tr>
              <th className="p-3">Агент</th>
              <th className="p-3">Статус</th>
              <th className="p-3">Нагрузка</th>
              <th className="p-3">Рейтинг</th>
              <th className="p-3">Всего</th>
              <th className="p-3">Ответ</th>
              <th className="p-3">Длительность</th>
              <th className="p-3">Действия</th>
            </tr>
          </thead>
          <tbody>
            {agents.length === 0 ? (
              <tr><td colSpan="8" className="text-center text-white/40 py-6">Нет агентов</td></tr>
            ) : agents.map((a) => (
              <tr key={a.id} className="border-t border-white/5" data-testid={`agent-row-${a.id}`}>
                <td className="p-3">
                  <div className="flex items-center gap-2">
                    {a.avatar_url ? (
                      <img src={`${BACKEND_URL}${a.avatar_url}`} alt="" className="w-8 h-8 rounded-full object-cover" />
                    ) : (
                      <div className="w-8 h-8 rounded-full bg-cyan-500/30 flex items-center justify-center text-xs">{(a.display_name || '?').slice(0, 2)}</div>
                    )}
                    <div>
                      <div className="text-white font-semibold">{a.display_name}</div>
                      <div className="text-[10px] text-white/40 font-mono">TG: {a.telegram_id}</div>
                    </div>
                  </div>
                </td>
                <td className="p-3"><StatusBadge s={a.status} /></td>
                <td className="p-3 font-mono text-cyan-300">{a.active_chats}/{a.max_chats}</td>
                <td className="p-3">
                  <div className="flex items-center gap-1">
                    <Star className="w-3 h-3 fill-yellow-400 text-yellow-400" />
                    <span className="font-bold">{a.avg_rating || '—'}</span>
                    <span className="text-[10px] text-white/40">({a.rating_count})</span>
                  </div>
                  {a.rating_dist && Object.keys(a.rating_dist).length > 0 && (
                    <div className="text-[9px] text-white/30 mt-1">
                      {[5, 4, 3, 2, 1].map((n) => (
                        <span key={n} className="mr-1">{n}★:{a.rating_dist[`s${n}`] || 0}</span>
                      ))}
                    </div>
                  )}
                </td>
                <td className="p-3">{a.total_chats_closed}</td>
                <td className="p-3 text-xs">{fmtSec(a.avg_response_seconds)}</td>
                <td className="p-3 text-xs">{fmtSec(a.avg_duration_seconds)}</td>
                <td className="p-3">
                  <div className="flex items-center gap-1">
                    <button onClick={() => { setEditAgent(a); setEditName(a.display_name); }} className="p-1.5 bg-white/10 hover:bg-white/20 rounded" title="Редактировать" data-testid={`agent-edit-${a.id}`}>
                      <Edit2 className="w-3 h-3" />
                    </button>
                    <label className="p-1.5 bg-white/10 hover:bg-white/20 rounded cursor-pointer" title="Загрузить аватар">
                      <Upload className="w-3 h-3" />
                      <input type="file" accept="image/png,image/jpeg" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) uploadAvatar(a.id, f); }} />
                    </label>
                    <button onClick={() => viewAccessLog(a.telegram_id)} className="p-1.5 bg-white/10 hover:bg-white/20 rounded" title="Журнал просмотров" data-testid={`agent-logs-${a.id}`}>
                      <Activity className="w-3 h-3" />
                    </button>
                    <button onClick={() => removeAgent(a.id)} className="p-1.5 bg-red-500/20 hover:bg-red-500/40 text-red-300 rounded" title="Удалить" data-testid={`agent-remove-${a.id}`}>
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Edit modal */}
      {editAgent && (
        <div className="fixed inset-0 bg-black/60 z-[200] flex items-center justify-center p-4" onClick={() => setEditAgent(null)}>
          <div className="bg-void border border-white/15 rounded-xl p-5 max-w-sm w-full" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-white font-bold mb-3">Редактировать агента</h3>
            <input value={editName} onChange={(e) => setEditName(e.target.value)} className="w-full bg-black/40 border border-white/15 rounded-lg px-3 py-2 text-sm text-white mb-3" data-testid="admin-edit-agent-name" />
            <div className="flex gap-2">
              <button onClick={saveEditAgent} className="flex-1 py-2 bg-cyan-500 text-white rounded text-xs font-semibold">Сохранить</button>
              <button onClick={() => setEditAgent(null)} className="flex-1 py-2 bg-white/10 text-white rounded text-xs">Отмена</button>
            </div>
          </div>
        </div>
      )}

      {/* Access log modal */}
      {accessLogAgent && (
        <div className="fixed inset-0 bg-black/60 z-[200] flex items-center justify-center p-4" onClick={() => setAccessLogAgent(null)}>
          <div className="bg-void border border-white/15 rounded-xl p-5 max-w-2xl w-full max-h-[80vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-white font-bold mb-3">Журнал просмотров — TG {accessLogAgent}</h3>
            <div className="space-y-1">
              {accessLog.length === 0 ? (
                <div className="text-white/40 text-sm">Записей нет</div>
              ) : accessLog.map((l) => (
                <div key={l.id} className="bg-white/5 rounded p-2 text-xs">
                  <div className="flex justify-between">
                    <span className="text-cyan-300">{l.action}</span>
                    <span className="text-white/40">{new Date(l.viewed_at).toLocaleString('ru-RU')}</span>
                  </div>
                  <div className="text-white/60 mt-0.5">
                    {l.viewed_user_id && <span>User: <span className="font-mono">{l.viewed_user_id}</span></span>}
                    {l.viewed_user_email && <span className="ml-2">({l.viewed_user_email})</span>}
                    {l.operation_id && <span className="ml-2">TX: <span className="font-mono">{l.operation_id}</span></span>}
                  </div>
                </div>
              ))}
            </div>
            <button onClick={() => setAccessLogAgent(null)} className="mt-4 w-full py-2 bg-white/10 text-white rounded text-xs">Закрыть</button>
          </div>
        </div>
      )}
    </div>
  );
}
