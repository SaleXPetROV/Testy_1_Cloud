import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { toast } from 'sonner';
import { Plus, Trash2, Gift, Users, Loader2, Search, Check, X, ChevronDown, GripVertical, Send, Music2, Twitter, Copy, ListChecks, Play, Link2, Megaphone, Rocket, Repeat, Handshake, Coins, Boxes, Sparkles, Pencil } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Card, CardContent } from '@/components/ui/card';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from '@/components/ui/dialog';
import {
  Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from '@/components/ui/select';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

// Skin images may be an absolute URL, a data: URI, or a backend /sprites path.
const skinImg = (img) => !img ? null : (/^(https?:|data:)/.test(img) ? img : `${BACKEND_URL}${img}`);
const headers = () => ({
  headers: { Authorization: `Bearer ${localStorage.getItem('token') || localStorage.getItem('ton_city_token')}` },
});

const ACTION_TYPES = [
  { value: 'subscribe_channel', label: 'Подписаться на канал' },
  { value: 'join_chat', label: 'Вступить в чат/группу' },
  { value: 'launch_app', label: 'Запустить приложение' },
  { value: 'visit_link', label: 'Перейти по ссылке' },
  { value: 'social_follow', label: 'Подписаться в соцсети' },
  { value: 'referral_invite', label: 'Пригласить друзей (все приглашённые)' },
  { value: 'referral_active', label: 'Пригласить активных рефералов' },
  { value: 'ad_tiktok', label: 'Реклама (TikTok)' },
  { value: 'tg_channel_boost', label: 'Буст (голос) Telegram-канала' },
  { value: 'repost_story', label: 'Репост истории канала (таймер 23ч)' },
  { value: 'partner_quest', label: 'Квест (партнёрский / локальный)' },
];
const typeLabel = (v) => ACTION_TYPES.find(a => a.value === v)?.label || v;

// Warehouse resource types (must match backend RESOURCE_PRICES keys)
const RESOURCE_TYPES = [
  'crops', 'energy', 'materials', 'fuel', 'ore', 'goods', 'refined_fuel',
  'steel', 'textiles', 'cu', 'quartz', 'traffic', 'cooling', 'biomass',
  'scrap', 'chips', 'nft', 'neurocode', 'logistics', 'repair_kits',
  'vr_experience', 'shares',
];

// Icon used on the task card in the user-facing list (fallback when no photo)
const ACTION_ICON = {
  subscribe_channel: Send,
  join_chat: Users,
  launch_app: Play,
  visit_link: Link2,
  social_follow: Users,
  referral_invite: Users,
  referral_active: Users,
  ad_tiktok: Megaphone,
  tg_channel_boost: Rocket,
  repost_story: Repeat,
  partner_quest: Handshake,
};

// Social icon options for a task (recognizable badge on the card)
export const SOCIAL_ICONS = {
  telegram: { Icon: Send, label: 'Telegram', color: 'text-sky-400', bg: 'bg-sky-500' },
  tiktok: { Icon: Music2, label: 'TikTok', color: 'text-pink-400', bg: 'bg-pink-500' },
  x: { Icon: Twitter, label: 'X (Twitter)', color: 'text-white', bg: 'bg-black' },
};
const ICON_OPTIONS = [
  { value: 'none', label: 'Без иконки' },
  { value: 'telegram', label: 'Telegram' },
  { value: 'tiktok', label: 'TikTok' },
  { value: 'x', label: 'X (Twitter)' },
  { value: 'custom', label: 'Свой логотип (загрузить)' },
];

const emptyForm = {
  title: '', reward_city: '', action_type: '', photo: '', icon: 'none', icon_url: '',
  channel_url: '', channel_id: '', target_url: '', required_referrals: '', views_rate: '',
  // Partner / local quest
  quest_kind: 'local', partner_url: '', partner_ref_id: '', partner_method: 'GET', partner_api_key: '', partner_user_param: '', partner_check_field: '', partner_check_min: '', partner_completed_field: '',
  show_to_referrals: true,   // partner quest: show to the partner's own referrals too
  instructions: '',
  reward_description: '',   // free-text describing the reward (shown next to the skin)
  require_telegram: false,   // quest: require linked Telegram before completing
  reward_resources: [],   // [{ type, amount }]
  reward_skin_groups: [], // [group_key, ...]  (skins granted as groups)
  reward_funds_amount: '',
  reward_funds_target: 'bonus', // task rewards always go to the bonus balance
};

export default function AdminTasksTab() {
  const [tasks, setTasks] = useState([]);
  const [rewards, setRewards] = useState([]);
  const [skinGroups, setSkinGroups] = useState([]);
  const [loading, setLoading] = useState(true);
  const [savingDaily, setSavingDaily] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [editingId, setEditingId] = useState(null);  // null = create mode; else task id being edited
  const [form, setForm] = useState(emptyForm);
  const [uploading, setUploading] = useState(false);
  const [uploadingIcon, setUploadingIcon] = useState(false);
  const [creating, setCreating] = useState(false);
  const [expanded, setExpanded] = useState({});     // taskId -> submissions[]
  const [search, setSearch] = useState({});         // taskId -> string
  const [dragIndex, setDragIndex] = useState(null);
  // Partner-quest response preview (test before create/update)
  const [partnerTestId, setPartnerTestId] = useState('');
  const [partnerTesting, setPartnerTesting] = useState(false);
  const [partnerTestResult, setPartnerTestResult] = useState(null);

  const testPartnerResponse = useCallback(async () => {
    const url = (form.partner_url || '').trim();
    if (!/^https?:\/\//i.test(url)) { toast.error('Сначала укажите корректный URL API партнёра'); return; }
    if (!String(partnerTestId).trim()) { toast.error('Введите тестовый telegram_id / chatId'); return; }
    setPartnerTesting(true);
    setPartnerTestResult(null);
    try {
      const cm = parseFloat(form.partner_check_min);
      const body = {
        partner_url: url,
        partner_method: form.partner_method || 'GET',
        partner_api_key: (form.partner_api_key || '').trim() || null,
        partner_user_param: (form.partner_user_param || '').trim() || null,
        partner_ref_id: (form.partner_ref_id || '').trim() || null,
        partner_check_field: (form.partner_check_field || '').trim() || null,
        partner_check_min: Number.isFinite(cm) ? cm : null,
        partner_completed_field: (form.partner_completed_field || '').trim() || null,
        test_user_id: String(partnerTestId).trim(),
      };
      const r = await axios.post(`${API}/admin/tasks/test-partner`, body, headers());
      setPartnerTestResult(r.data);
    } catch (e) {
      setPartnerTestResult({ ok: false, reachable: false, verdict: false,
        verdict_reason: e?.response?.data?.detail || e.message || 'Ошибка запроса' });
    } finally {
      setPartnerTesting(false);
    }
  }, [form, partnerTestId]);

  const fetchAll = useCallback(async () => {
    try {
      const [tRes, dRes] = await Promise.all([
        axios.get(`${API}/admin/tasks`, headers()),
        axios.get(`${API}/admin/tasks/daily-rewards`, headers()),
      ]);
      setTasks(tRes.data.tasks || []);
      setRewards(dRes.data.rewards || []);
      try {
        const gRes = await axios.get(`${API}/admin/skins/groups`, headers());
        setSkinGroups(gRes.data.groups || []);
      } catch (_) { /* ignore */ }
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Ошибка загрузки заданий');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const saveDaily = async () => {
    setSavingDaily(true);
    try {
      const clean = rewards.map(r => Math.max(0, parseInt(r) || 0));
      await axios.put(`${API}/admin/tasks/daily-rewards`, { rewards: clean }, headers());
      toast.success('Награды ежедневного входа сохранены');
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Ошибка');
    } finally {
      setSavingDaily(false);
    }
  };

  const onUpload = async (file) => {
    if (!file) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append('file', file);
      const r = await axios.post(`${API}/admin/announcement/upload-image`, fd, headers());
      setForm(f => ({ ...f, photo: r.data.url }));
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Ошибка загрузки фото');
    } finally {
      setUploading(false);
    }
  };

  const onUploadIcon = async (file) => {
    if (!file) return;
    setUploadingIcon(true);
    try {
      const fd = new FormData();
      fd.append('file', file);
      const r = await axios.post(`${API}/admin/announcement/upload-image`, fd, headers());
      setForm(f => ({ ...f, icon: 'custom', icon_url: r.data.url }));
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Ошибка загрузки иконки');
    } finally {
      setUploadingIcon(false);
    }
  };

  // Open the task form pre-filled with an existing task's conditions (edit mode).
  const openEdit = (task) => {
    setForm({
      title: task.title || '',
      reward_city: (task.reward_city === null || task.reward_city === undefined) ? '' : String(task.reward_city),
      action_type: task.action_type || '',
      photo: task.photo || '',
      icon: task.icon || 'none',
      icon_url: task.icon_url || '',
      channel_url: task.channel_url || '',
      channel_id: task.channel_id || '',
      target_url: task.target_url || '',
      required_referrals: (task.required_referrals === null || task.required_referrals === undefined) ? '' : String(task.required_referrals),
      views_rate: (task.views_rate === null || task.views_rate === undefined) ? '' : String(task.views_rate),
      quest_kind: task.quest_kind || 'local',
      partner_url: task.partner_url || '',
      partner_ref_id: task.partner_ref_id || '',
      partner_method: task.partner_method || 'GET',
      partner_api_key: task.partner_api_key || '',
      partner_user_param: task.partner_user_param || '',
      partner_check_field: task.partner_check_field || '',
      partner_check_min: (task.partner_check_min ?? '') === null ? '' : String(task.partner_check_min ?? ''),
      partner_completed_field: task.partner_completed_field || '',
      show_to_referrals: task.show_to_referrals !== false,
      instructions: task.instructions || '',
      reward_description: task.reward_description || '',
      require_telegram: !!task.require_telegram,
      reward_resources: task.reward_resources
        ? Object.entries(task.reward_resources).map(([type, amount]) => ({ type, amount: String(amount) }))
        : [],
      reward_skin_groups: Array.isArray(task.reward_skins) ? task.reward_skins.map((s) => s.id).filter(Boolean) : [],
      reward_funds_amount: (task.reward_funds_amount === null || task.reward_funds_amount === undefined) ? '' : String(task.reward_funds_amount),
      reward_funds_target: 'bonus',
    });
    setEditingId(task.id);
    setShowAdd(true);
  };

  const createTask = async () => {
    if (!form.title.trim()) return toast.error('Введите заголовок задания');
    if (!form.action_type) return toast.error('Выберите тип действия');
    const payload = {
      title: form.title.trim(),
      reward_city: form.reward_city === '' ? null : (parseInt(form.reward_city) || 0),
      action_type: form.action_type,
      photo: form.photo || null,
      icon: form.icon && form.icon !== 'none' ? form.icon : null,
      icon_url: form.icon === 'custom' ? (form.icon_url || null) : null,
    };
    if (form.icon === 'custom' && !form.icon_url) return toast.error('Загрузите свой логотип-иконку');
    if (['subscribe_channel', 'join_chat'].includes(form.action_type)) {
      if (!form.channel_url || !form.channel_id) return toast.error('Укажите ссылку и ID канала/чата');
      payload.channel_url = form.channel_url.trim();
      payload.channel_id = form.channel_id.trim();
    } else if (['launch_app', 'visit_link', 'social_follow'].includes(form.action_type)) {
      if (!form.target_url) return toast.error('Укажите ссылку');
      payload.target_url = form.target_url.trim();
    } else if (['referral_invite', 'referral_active'].includes(form.action_type)) {
      const n = parseInt(form.required_referrals) || 0;
      if (n <= 0) return toast.error('Укажите количество рефералов');
      payload.required_referrals = n;
    } else if (form.action_type === 'ad_tiktok') {
      const vr = parseFloat(form.views_rate);
      if (!vr || vr <= 0) return toast.error('Укажите ставку $CITY за 1000 просмотров');
      payload.views_rate = vr;
    } else if (form.action_type === 'partner_quest') {
      payload.quest_kind = form.quest_kind || 'local';
      if (payload.quest_kind === 'partner') {
        const url = (form.partner_url || '').trim();
        if (!/^https?:\/\//i.test(url)) return toast.error('Укажите корректный URL API партнёра (http/https)');
        payload.partner_url = url;
        payload.partner_ref_id = (form.partner_ref_id || '').trim() || null;
        payload.partner_method = form.partner_method || 'GET';
        payload.partner_api_key = (form.partner_api_key || '').trim() || null;
        payload.partner_user_param = (form.partner_user_param || '').trim() || null;
        payload.partner_check_field = (form.partner_check_field || '').trim() || null;
        {
          const cm = parseFloat(form.partner_check_min);
          payload.partner_check_min = Number.isFinite(cm) ? cm : null;
        }
        payload.partner_completed_field = (form.partner_completed_field || '').trim() || null;
      }
      payload.instructions = (form.instructions || '').trim() || null;
      payload.reward_description = (form.reward_description || '').trim() || null;
      payload.require_telegram = !!form.require_telegram;
      payload.show_to_referrals = !!form.show_to_referrals;
      payload.show_to_referrals = !!form.show_to_referrals;
      let visit = (form.target_url || '').trim();
      if (visit && !/^(https?:|tg:|ton:|tonkeeper:|mailto:)/i.test(visit)) {
        visit = `https://${visit.replace(/^\/+/, '')}`;
      }
      if (visit) payload.target_url = visit;
      // Resources → { type: amount }
      const res = {};
      (form.reward_resources || []).forEach(r => {
        const amt = parseFloat(r.amount);
        if (r.type && amt > 0) res[r.type] = amt;
      });
      if (Object.keys(res).length) payload.reward_resources = res;
      // Skins → [{ id: group_key, name: group_name }]
      const skins = (form.reward_skin_groups || [])
        .map(gk => {
          const g = skinGroups.find(x => x.group_key === gk);
          return { id: gk, name: g?.group_name || gk, image: g?.image || null };
        });
      if (skins.length) payload.reward_skins = skins;
      // Extra funds → bonus or real balance
      const funds = parseFloat(form.reward_funds_amount) || 0;
      if (funds > 0) {
        payload.reward_funds_amount = funds;
        payload.reward_funds_target = 'bonus';
      }
      const rc = parseInt(form.reward_city) || 0;
      if (rc <= 0 && !payload.reward_resources && !payload.reward_skins && !(funds > 0)) {
        return toast.error('Квест должен давать хотя бы одну награду: монеты, средства, ресурсы или скин');
      }
    }
    setCreating(true);
    try {
      if (editingId) {
        await axios.put(`${API}/admin/tasks/${editingId}/update`, payload, headers());
        toast.success('Задание обновлено');
      } else {
        await axios.post(`${API}/admin/tasks`, payload, headers());
        toast.success('Задание добавлено');
      }
      setShowAdd(false);
      setEditingId(null);
      setForm(emptyForm);
      fetchAll();
    } catch (e) {
      toast.error(e?.response?.data?.detail || (editingId ? 'Ошибка сохранения' : 'Ошибка создания'));
    } finally {
      setCreating(false);
    }
  };

  const deleteTask = async (id) => {
    if (!window.confirm('Удалить это задание у всех пользователей?')) return;
    try {
      await axios.delete(`${API}/admin/tasks/${id}`, headers());
      toast.success('Задание удалено');
      fetchAll();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Ошибка удаления');
    }
  };

  const duplicateTask = async (id) => {
    try {
      await axios.post(`${API}/admin/tasks/${id}/duplicate`, {}, headers());
      toast.success('Задание продублировано');
      fetchAll();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Ошибка дублирования');
    }
  };

  const toggleActive = async (task) => {
    const next = !(task.active !== false);
    setTasks(ts => ts.map(t => t.id === task.id ? { ...t, active: next } : t));
    try {
      await axios.patch(`${API}/admin/tasks/${task.id}/active`, { active: next }, headers());
    } catch (e) {
      toast.error('Ошибка переключения');
      fetchAll();
    }
  };

  const handleDrop = async (dropIndex) => {
    if (dragIndex === null || dragIndex === dropIndex) { setDragIndex(null); return; }
    const reordered = [...tasks];
    const [moved] = reordered.splice(dragIndex, 1);
    reordered.splice(dropIndex, 0, moved);
    setTasks(reordered);
    setDragIndex(null);
    try {
      await axios.put(`${API}/admin/tasks/reorder`, { ids: reordered.map(t => t.id) }, headers());
    } catch (e) {
      toast.error('Ошибка изменения порядка');
      fetchAll();
    }
  };

  const loadSubmissions = async (taskId) => {
    if (expanded[taskId]) {
      setExpanded(e => { const c = { ...e }; delete c[taskId]; return c; });
      return;
    }
    try {
      const r = await axios.get(`${API}/admin/tasks/${taskId}/ad-submissions?search=${encodeURIComponent(search[taskId] || '')}`, headers());
      setExpanded(e => ({ ...e, [taskId]: r.data.submissions || [] }));
    } catch (e) {
      toast.error('Ошибка загрузки заявок');
    }
  };

  const refreshSubmissions = async (taskId) => {
    const r = await axios.get(`${API}/admin/tasks/${taskId}/ad-submissions?search=${encodeURIComponent(search[taskId] || '')}`, headers());
    setExpanded(e => ({ ...e, [taskId]: r.data.submissions || [] }));
  };

  const reviewSub = async (taskId, subId, action) => {
    try {
      const r = await axios.post(`${API}/admin/tasks/ad-submissions/${subId}/${action}`, {}, headers());
      if (action === 'approve') {
        toast.success(`Начислено ${(r.data?.paid_city ?? 0).toLocaleString('ru-RU')} $CITY`);
      } else {
        toast.success('Отклонено');
      }
      await refreshSubmissions(taskId);
      fetchAll();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Ошибка');
    }
  };

  const [statsBusy, setStatsBusy] = useState({}); // subId -> true
  const refreshStats = async (taskId, subId) => {
    setStatsBusy(b => ({ ...b, [subId]: true }));
    try {
      await axios.post(`${API}/admin/tasks/ad-submissions/${subId}/refresh-stats`, {}, headers());
      toast.success('Статистика обновлена');
      await refreshSubmissions(taskId);
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Не удалось получить статистику');
    } finally {
      setStatsBusy(b => ({ ...b, [subId]: false }));
    }
  };

  const editPayout = async (taskId, sub) => {
    const cur = sub.effective_payout ?? 0;
    const val = window.prompt('Введите сумму выплаты в $CITY:', String(cur));
    if (val === null) return;
    const amount = parseInt(val, 10);
    if (Number.isNaN(amount) || amount < 0) return toast.error('Некорректная сумма');
    try {
      await axios.post(`${API}/admin/tasks/ad-submissions/${sub.id}/set-payout`, { amount }, headers());
      toast.success('Сумма выплаты обновлена');
      await refreshSubmissions(taskId);
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Ошибка');
    }
  };

  const fmtNum = (n) => (n ?? 0).toLocaleString('ru-RU');

  const at = form.action_type;

  return (
    <div className="space-y-5">
      {/* Daily login rewards editor */}
      <Card className="glass-panel border-yellow-500/30">
        <CardContent className="p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-bold text-white text-sm uppercase tracking-wide">Ежедневный вход (награды по дням, $CITY)</h3>
            <Button size="sm" disabled={savingDaily} onClick={saveDaily} className="bg-yellow-500 text-black hover:bg-yellow-400" data-testid="daily-rewards-save">
              {savingDaily ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Сохранить'}
            </Button>
          </div>
          <p className="text-xs text-text-muted mb-3">Пользователь получает награду за каждый день входа без пропусков. Пропуск дня → возврат к Дню 1.</p>
          <div className="flex flex-wrap gap-2 items-end">
            {rewards.map((r, i) => (
              <div key={i} className="flex flex-col">
                <span className="text-[10px] text-text-muted mb-1">День {i + 1}</span>
                <Input type="number" value={r} data-testid={`daily-reward-input-${i + 1}`}
                  onChange={(e) => setRewards(rw => rw.map((x, idx) => idx === i ? e.target.value : x))}
                  className="w-20 bg-black/40 border-white/10 h-9" />
              </div>
            ))}
            <div className="flex gap-1">
              <Button size="sm" variant="outline" onClick={() => setRewards(rw => [...rw, 0])}>+ День</Button>
              {rewards.length > 1 && (
                <Button size="sm" variant="outline" onClick={() => setRewards(rw => rw.slice(0, -1))}>− День</Button>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Header + add button */}
      <div className="flex items-center justify-between">
        <h3 className="font-bold text-white text-sm uppercase tracking-wide">Все задания ({tasks.length})</h3>
        <Button size="sm" onClick={() => setShowAdd(true)} className="bg-cyber-cyan text-black hover:bg-cyber-cyan/80 font-bold" data-testid="add-task-btn">
          <Plus className="w-4 h-4 mr-1" /> Добавить задание
        </Button>
      </div>

      {/* Task list */}
      {loading ? (
        <div className="text-center text-text-muted py-8"><Loader2 className="w-5 h-5 animate-spin inline" /></div>
      ) : tasks.length === 0 ? (
        <div className="text-center text-text-muted py-8">Заданий пока нет</div>
      ) : (
        <div className="space-y-3" data-testid="admin-tasks-list">
          {tasks.map((task, index) => (
            <Card key={task.id}
              draggable
              onDragStart={() => setDragIndex(index)}
              onDragOver={(e) => e.preventDefault()}
              onDrop={() => handleDrop(index)}
              className={`glass-panel border-white/10 ${dragIndex === index ? 'opacity-50' : ''} ${task.active === false ? 'opacity-60' : ''}`}
              data-testid={`admin-task-${task.id}`}>
              <CardContent className="p-3">
                <div className="flex items-center gap-2">
                  <div className="cursor-grab active:cursor-grabbing text-text-muted flex-shrink-0" title="Перетащите для изменения порядка" data-testid={`task-drag-${task.id}`}>
                    <GripVertical className="w-4 h-4" />
                  </div>
                  <div className="w-12 h-12 rounded-lg overflow-hidden flex-shrink-0 bg-white/5 flex items-center justify-center relative">
                    {task.photo ? <img src={task.photo} alt="" className="w-full h-full object-cover" /> : <Gift className="w-6 h-6 text-cyber-cyan" />}
                    {task.icon === 'custom' && task.icon_url ? (
                      <span className="absolute -bottom-1 -right-1 w-5 h-5 rounded-full overflow-hidden ring-2 ring-[#12121f] bg-white" data-testid={`task-social-icon-${task.id}`}>
                        <img src={task.icon_url} alt="" className="w-full h-full object-cover" />
                      </span>
                    ) : (task.icon && SOCIAL_ICONS[task.icon] && (() => {
                      const S = SOCIAL_ICONS[task.icon];
                      return (
                        <span className={`absolute -bottom-1 -right-1 w-5 h-5 rounded-full ${S.bg} flex items-center justify-center ring-2 ring-[#12121f]`} data-testid={`task-social-icon-${task.id}`}>
                          <S.Icon className="w-3 h-3 text-white" />
                        </span>
                      );
                    })())}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold text-white truncate">{task.title}</p>
                    <div className="flex items-center gap-2 text-xs mt-0.5 flex-wrap">
                      {task.reward_city > 0 && <span className="text-yellow-400 font-bold">+{task.reward_city} $CITY</span>}
                      <span className="inline-flex items-center gap-1 text-green-400" title="Выполнили">
                        <Users className="w-3.5 h-3.5" /> {task.completions_count ?? 0}
                      </span>
                      <span className="text-text-muted">· {typeLabel(task.action_type)}</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5 flex-shrink-0" title={task.active === false ? 'Выключено' : 'Включено'}>
                    <Switch checked={task.active !== false} onCheckedChange={() => toggleActive(task)} data-testid={`task-active-toggle-${task.id}`} />
                  </div>
                  {task.action_type === 'ad_tiktok' && (
                    <Button size="sm" variant="outline" onClick={() => loadSubmissions(task.id)} data-testid={`task-submissions-btn-${task.id}`}>
                      Заявки ({task.submissions_count ?? 0}) <ChevronDown className="w-3 h-3 ml-1" />
                    </Button>
                  )}
                  <Button size="icon" variant="ghost" onClick={() => openEdit(task)} className="text-amber-300 hover:bg-amber-400/10 flex-shrink-0" title="Изменить условия задания" data-testid={`edit-task-btn-${task.id}`}>
                    <Pencil className="w-4 h-4" />
                  </Button>
                  <Button size="icon" variant="ghost" onClick={() => duplicateTask(task.id)} className="text-cyber-cyan hover:bg-cyber-cyan/10 flex-shrink-0" title="Дублировать задание" data-testid={`duplicate-task-btn-${task.id}`}>
                    <Copy className="w-4 h-4" />
                  </Button>
                  <Button size="icon" variant="ghost" onClick={() => deleteTask(task.id)} className="text-red-400 hover:bg-red-500/10 flex-shrink-0" data-testid={`delete-task-btn-${task.id}`}>
                    <Trash2 className="w-4 h-4" />
                  </Button>
                </div>

                {/* Ad submissions panel */}
                {task.action_type === 'ad_tiktok' && expanded[task.id] && (
                  <div className="mt-3 border-t border-white/10 pt-3" data-testid={`submissions-panel-${task.id}`}>
                    <div className="flex items-center gap-2 mb-2">
                      <Search className="w-4 h-4 text-text-muted" />
                      <Input placeholder="Поиск по ссылке..." value={search[task.id] || ''}
                        onChange={(e) => setSearch(s => ({ ...s, [task.id]: e.target.value }))}
                        onKeyDown={(e) => { if (e.key === 'Enter') refreshSubmissions(task.id); }}
                        className="bg-black/40 border-white/10 h-8 text-sm" data-testid={`submissions-search-${task.id}`} />
                      <Button size="sm" variant="outline" onClick={() => refreshSubmissions(task.id)}>Найти</Button>
                    </div>
                    {expanded[task.id].length === 0 ? (
                      <p className="text-xs text-text-muted py-2">Нет заявок</p>
                    ) : (
                      <div className="space-y-2">
                        {expanded[task.id].map((s) => (
                          <div key={s.id} className="text-xs bg-black/30 rounded px-2 py-2" data-testid={`submission-${s.id}`}>
                            <div className="flex items-center gap-2">
                              <span className="text-text-muted w-20 truncate flex-shrink-0">{s.username}</span>
                              <a href={s.url} target="_blank" rel="noreferrer" className="text-cyber-cyan truncate flex-1 hover:underline">{s.url}</a>
                              {s.is_duplicate ? (
                                <span className="flex-shrink-0 px-1.5 py-0.5 rounded bg-red-500/20 text-red-300 border border-red-500/40" title="Такая ссылка уже есть в этом задании" data-testid={`dup-badge-${s.id}`}>
                                  Копия ×{s.url_count}
                                </span>
                              ) : (
                                <span className="flex-shrink-0 px-1.5 py-0.5 rounded bg-green-500/15 text-green-300 border border-green-500/30" data-testid={`unique-badge-${s.id}`}>
                                  Уникальна
                                </span>
                              )}
                            </div>

                            {/* Views / likes row */}
                            <div className="flex items-center gap-3 mt-1.5 pl-[88px] text-[11px]">
                              {typeof s.views === 'number' ? (
                                <>
                                  <span className="text-white" data-testid={`views-${s.id}`}>👁 {fmtNum(s.views)} просмотров</span>
                                  <span className="text-pink-300" data-testid={`likes-${s.id}`}>❤ {fmtNum(s.likes)} лайков</span>
                                </>
                              ) : (
                                <span className="text-text-muted">Статистика не загружена</span>
                              )}
                              <Button size="sm" variant="outline" disabled={statsBusy[s.id]} onClick={() => refreshStats(task.id, s.id)}
                                className="h-6 px-2 ml-auto" data-testid={`refresh-stats-${s.id}`}>
                                {statsBusy[s.id] ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Обновить статистику'}
                              </Button>
                            </div>

                            {/* Payout / actions row */}
                            <div className="flex items-center gap-1.5 mt-2 pl-[88px]">
                              {s.status === 'pending' ? (
                                <>
                                  <Button size="sm" onClick={() => reviewSub(task.id, s.id, 'approve')} className="h-7 bg-green-600 hover:bg-green-700" data-testid={`approve-${s.id}`}>
                                    <Check className="w-3 h-3 mr-1" /> Выплатить {fmtNum(s.effective_payout ?? 0)} $CITY
                                  </Button>
                                  <Button size="sm" variant="outline" onClick={() => editPayout(task.id, s)} className="h-7 px-2" data-testid={`edit-payout-${s.id}`}>
                                    Изменить
                                  </Button>
                                  <Button size="sm" onClick={() => reviewSub(task.id, s.id, 'reject')} className="h-7 bg-red-600 hover:bg-red-700 ml-auto" data-testid={`reject-${s.id}`}>
                                    <X className="w-3 h-3 mr-1" /> Отклонить
                                  </Button>
                                </>
                              ) : (
                                <span className={`font-bold ${s.status === 'approved' ? 'text-green-400' : 'text-red-400'}`}>
                                  {s.status === 'approved' ? `Начислено ${fmtNum(s.paid_city ?? s.effective_payout ?? 0)} $CITY` : 'Отклонено'}
                                </span>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Add task modal */}
      <Dialog open={showAdd} onOpenChange={(o) => { setShowAdd(o); if (!o) { setEditingId(null); setForm(emptyForm); } }}>
        <DialogContent className="bg-[#12121f] border-white/10 max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader><DialogTitle>{editingId ? 'Редактирование задания' : 'Новое задание'}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div>
              <Label className="text-xs">Тип действия</Label>
              <Select value={form.action_type} onValueChange={(v) => setForm(f => ({ ...f, action_type: v }))}>
                <SelectTrigger className="bg-black/40 border-white/10" data-testid="task-action-type-select"><SelectValue placeholder="Выберите тип" /></SelectTrigger>
                <SelectContent>
                  {ACTION_TYPES.map(a => <SelectItem key={a.value} value={a.value}>{a.label}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>

            <div>
              <Label className="text-xs">Заголовок задания</Label>
              <Input value={form.title} onChange={(e) => setForm(f => ({ ...f, title: e.target.value }))}
                placeholder="Например: Подпишитесь на наш канал" className="bg-black/40 border-white/10" data-testid="task-title-input" />
            </div>

            {at !== 'ad_tiktok' && (
              <div>
                <Label className="text-xs">Награда ($CITY) — необязательно</Label>
                <Input type="number" value={form.reward_city} onChange={(e) => setForm(f => ({ ...f, reward_city: e.target.value }))}
                  placeholder="Оставьте пустым — без монет" className="bg-black/40 border-white/10" data-testid="task-reward-input" />
                <p className="text-[10px] text-text-muted mt-1">Если не указать сумму, монеты $CITY не начисляются и не показываются в карточке.</p>
              </div>
            )}

            <div>
              <Label className="text-xs">Фото задания</Label>
              <input type="file" accept="image/*" onChange={(e) => onUpload(e.target.files?.[0])} className="text-xs text-text-muted" data-testid="task-photo-input" />
              {uploading && <span className="text-xs text-cyber-cyan ml-2">Загрузка...</span>}
              {form.photo && <img src={form.photo} alt="" className="w-16 h-16 rounded-lg object-cover mt-2" />}
            </div>

            <div>
              <Label className="text-xs">Иконка соцсети (для узнаваемости карточки)</Label>
              <Select value={form.icon} onValueChange={(v) => setForm(f => ({ ...f, icon: v, icon_url: v === 'custom' ? f.icon_url : '' }))}>
                <SelectTrigger className="bg-black/40 border-white/10" data-testid="task-icon-select"><SelectValue placeholder="Без иконки" /></SelectTrigger>
                <SelectContent>
                  {ICON_OPTIONS.map(o => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
                </SelectContent>
              </Select>
              {form.icon === 'custom' && (
                <div className="mt-2 flex items-center gap-2">
                  <input type="file" accept="image/*" onChange={(e) => onUploadIcon(e.target.files?.[0])} className="text-xs text-text-muted" data-testid="task-custom-icon-input" />
                  {uploadingIcon && <span className="text-xs text-cyber-cyan">Загрузка...</span>}
                  {form.icon_url && <img src={form.icon_url} alt="" className="w-8 h-8 rounded-full object-cover ring-1 ring-white/20" data-testid="task-custom-icon-preview" />}
                </div>
              )}
            </div>

            {/* Dynamic fields */}
            {['subscribe_channel', 'join_chat'].includes(at) && (
              <>
                <div>
                  <Label className="text-xs">Ссылка на канал/чат</Label>
                  <Input value={form.channel_url} onChange={(e) => setForm(f => ({ ...f, channel_url: e.target.value }))}
                    placeholder="https://t.me/yourchannel" className="bg-black/40 border-white/10" data-testid="task-channel-url-input" />
                </div>
                <div>
                  <Label className="text-xs">ID канала/чата (@username или -100...)</Label>
                  <Input value={form.channel_id} onChange={(e) => setForm(f => ({ ...f, channel_id: e.target.value }))}
                    placeholder="@yourchannel" className="bg-black/40 border-white/10" data-testid="task-channel-id-input" />
                  <p className="text-[10px] text-text-muted mt-1">Бот должен быть администратором этого канала/чата для проверки подписки.</p>
                </div>
              </>
            )}
            {['launch_app', 'visit_link', 'social_follow'].includes(at) && (
              <div>
                <Label className="text-xs">Ссылка</Label>
                <Input value={form.target_url} onChange={(e) => setForm(f => ({ ...f, target_url: e.target.value }))}
                  placeholder="https://..." className="bg-black/40 border-white/10" data-testid="task-target-url-input" />
              </div>
            )}
            {['referral_invite', 'referral_active'].includes(at) && (
              <div>
                <Label className="text-xs">
                  {at === 'referral_active' ? 'Сколько НОВЫХ активных рефералов нужно' : 'Сколько НОВЫХ рефералов нужно пригласить'}
                </Label>
                <Input type="number" value={form.required_referrals} onChange={(e) => setForm(f => ({ ...f, required_referrals: e.target.value }))}
                  placeholder="3" className="bg-black/40 border-white/10" data-testid="task-required-referrals-input" />
                <p className="text-[10px] text-text-muted mt-1">
                  {at === 'referral_active'
                    ? 'Активный реферал — приглашённый, купивший хотя бы один участок. Отсчёт идёт от текущего количества у каждого пользователя (было N → нужно N + это число).'
                    : 'Отсчёт идёт от текущего количества приглашённых у каждого пользователя (было N → нужно N + это число).'}
                </p>
              </div>
            )}
            {at === 'ad_tiktok' && (
              <>
                <div>
                  <Label className="text-xs">Ставка: $CITY за 1000 просмотров</Label>
                  <Input type="number" step="0.1" value={form.views_rate} onChange={(e) => setForm(f => ({ ...f, views_rate: e.target.value }))}
                    placeholder="Например: 5" className="bg-black/40 border-white/10" data-testid="task-views-rate-input" />
                  <p className="text-[10px] text-text-muted mt-1">Выплата = (просмотры ÷ 1000) × ставка. Сумму можно скорректировать вручную при проверке каждой ссылки.</p>
                </div>
                <p className="text-[11px] text-text-muted">Пользователь снимет видео в TikTok и пришлёт ссылку на проверку. Задание повторяемое. Просмотры и лайки подтягиваются автоматически по кнопке «Обновить статистику».</p>
              </>
            )}
            {at === 'tg_channel_boost' && (
              <div className="rounded-lg border border-cyber-cyan/30 bg-cyber-cyan/5 p-2.5" data-testid="boost-info">
                <p className="text-[11px] text-text-muted">
                  ID канала берётся из раздела <span className="text-cyber-cyan font-semibold">«Промо»</span>. Бот должен быть <b>администратором</b> канала — проверка идёт через Telegram Bot API (getUserChatBoosts). Награда начисляется, если пользователь отдал голос (буст) за канал.
                </p>
              </div>
            )}
            {at === 'repost_story' && (
              <div className="rounded-lg border border-cyber-cyan/30 bg-cyber-cyan/5 p-2.5" data-testid="repost-info">
                <p className="text-[11px] text-text-muted">
                  Ссылка на канал берётся из раздела <span className="text-cyber-cyan font-semibold">«Промо»</span> (по ID). После нажатия «Проверить» запускается таймер на <b>23 часа</b>; по его окончании награда начисляется автоматически на сервере — пользователю не нужно ничего нажимать.
                </p>
              </div>
            )}

            {at === 'partner_quest' && (
              <div className="space-y-3 rounded-lg border border-cyber-cyan/30 bg-cyber-cyan/5 p-3" data-testid="quest-fields">
                <div>
                  <Label className="text-xs">Тип квеста</Label>
                  <Select value={form.quest_kind} onValueChange={(v) => setForm(f => ({ ...f, quest_kind: v }))}>
                    <SelectTrigger className="bg-black/40 border-white/10" data-testid="quest-kind-select"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="partner">Партнёрский (проверка через API партнёра)</SelectItem>
                      <SelectItem value="local">Локальный (проверка без API — сразу засчитывается)</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                {form.quest_kind === 'partner' && (
                  <>
                    <div>
                      <Label className="text-xs">URL API партнёра</Label>
                      <Input value={form.partner_url} onChange={(e) => setForm(f => ({ ...f, partner_url: e.target.value }))}
                        placeholder="https://partner.example.com/api/check" className="bg-black/40 border-white/10" data-testid="quest-partner-url-input" />
                      <p className="text-[10px] text-text-muted mt-1">При нажатии «Проверить» отправим запрос с Telegram id игрока (имя параметра ниже, по умолчанию <b>user_id</b>) и <b>ref_id</b>; если указан API-ключ — добавим заголовок <b>x-api-key</b>. Ответ <b>HTTP 200</b> = квест выполнен, награда начисляется; иначе — сообщение «условия ещё не выполнены».</p>
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <Label className="text-xs">Имя параметра Telegram id</Label>
                        <Input value={form.partner_user_param} onChange={(e) => setForm(f => ({ ...f, partner_user_param: e.target.value }))}
                          placeholder="user_id (напр. chatId)" className="bg-black/40 border-white/10 font-mono text-xs" data-testid="quest-user-param-input" />
                      </div>
                      <div>
                        <Label className="text-xs">ref_id (в параметрах запроса)</Label>
                        <Input value={form.partner_ref_id} onChange={(e) => setForm(f => ({ ...f, partner_ref_id: e.target.value }))}
                          placeholder="необязательно" className="bg-black/40 border-white/10" data-testid="quest-ref-id-input" />
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <Label className="text-xs">API-ключ партнёра (заголовок x-api-key)</Label>
                        <Input value={form.partner_api_key} onChange={(e) => setForm(f => ({ ...f, partner_api_key: e.target.value }))}
                          placeholder="необязательно" className="bg-black/40 border-white/10 font-mono text-xs" data-testid="quest-api-key-input" autoComplete="off" />
                      </div>
                      <div>
                        <Label className="text-xs">Метод</Label>
                        <Select value={form.partner_method} onValueChange={(v) => setForm(f => ({ ...f, partner_method: v }))}>
                          <SelectTrigger className="bg-black/40 border-white/10" data-testid="quest-method-select"><SelectValue /></SelectTrigger>
                          <SelectContent>
                            <SelectItem value="GET">GET</SelectItem>
                            <SelectItem value="POST">POST</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <Label className="text-xs">Поле-показатель в ответе (dot-path)</Label>
                        <Input value={form.partner_check_field} onChange={(e) => setForm(f => ({ ...f, partner_check_field: e.target.value }))}
                          placeholder="напр.: data.tradeVolume" className="bg-black/40 border-white/10 font-mono text-xs" data-testid="quest-check-field-input" autoComplete="off" />
                      </div>
                      <div>
                        <Label className="text-xs">Минимальное значение (порог)</Label>
                        <Input type="number" value={form.partner_check_min} onChange={(e) => setForm(f => ({ ...f, partner_check_min: e.target.value }))}
                          placeholder="напр.: 5" className="bg-black/40 border-white/10 font-mono text-xs" data-testid="quest-check-min-input" />
                      </div>
                    </div>
                    <p className="text-[10px] text-text-muted">
                      Если оба поля заполнены — квест засчитывается только когда числовое значение из ответа партнёра ≥ порога
                      (напр. iTerra: <span className="font-mono">data.tradeVolume ≥ 5</span>). Пусто = достаточно ответа HTTP 200.
                    </p>
                    <div>
                      <Label className="text-xs">Поле-флаг «выполнено» (dot-path, булево)</Label>
                      <Input value={form.partner_completed_field} onChange={(e) => setForm(f => ({ ...f, partner_completed_field: e.target.value }))}
                        placeholder="напр.: completed" className="bg-black/40 border-white/10 font-mono text-xs" data-testid="quest-completed-field-input" autoComplete="off" />
                      <p className="text-[10px] text-text-muted mt-0.5">
                        Для заданий вида <span className="font-mono">{`{"completed": true}`}</span> (напр. five-battles). Если заполнено —
                        квест засчитывается, когда это поле в ответе истинно. Оставьте пустым для числового порога выше.
                      </p>
                    </div>

                    {/* Предпросмотр ответа сервера партнёра перед сохранением */}
                    <div className="rounded-lg border border-cyber-cyan/30 bg-black/30 p-3 space-y-2" data-testid="quest-partner-test-box">
                      <Label className="text-xs flex items-center gap-1"><Play className="w-3.5 h-3.5 text-cyber-cyan" /> Проверить ответ сервера партнёра</Label>
                      <div className="flex items-end gap-2">
                        <div className="flex-1">
                          <Label className="text-[10px] text-text-muted">Тестовый telegram_id / chatId</Label>
                          <Input value={partnerTestId} onChange={(e) => setPartnerTestId(e.target.value)}
                            placeholder="напр.: 128668539" className="bg-black/40 border-white/10 font-mono text-xs" data-testid="quest-partner-test-id-input" />
                        </div>
                        <Button type="button" onClick={testPartnerResponse} disabled={partnerTesting}
                          className="bg-cyber-cyan/20 border border-cyber-cyan/40 text-cyber-cyan hover:bg-cyber-cyan/30" data-testid="quest-partner-test-btn">
                          {partnerTesting ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Проверить'}
                        </Button>
                      </div>
                      {partnerTestResult && (
                        <div className="text-xs space-y-1" data-testid="quest-partner-test-result">
                          <div className={partnerTestResult.verdict ? 'text-emerald-400 font-bold' : 'text-red-400 font-bold'}>
                            {partnerTestResult.verdict ? '✓ Задание будет засчитано' : '✗ Задание НЕ будет засчитано'}
                          </div>
                          <div className="text-text-muted">{partnerTestResult.verdict_reason}</div>
                          {partnerTestResult.status != null && (
                            <div className="text-text-muted">HTTP статус: <span className="font-mono">{partnerTestResult.status}</span></div>
                          )}
                          {partnerTestResult.request_url && (
                            <div className="text-text-muted break-all">Запрос: <span className="font-mono">{partnerTestResult.request_url}</span></div>
                          )}
                          <div className="text-text-muted">Ответ партнёра:</div>
                          <pre className="bg-black/60 rounded p-2 overflow-x-auto text-[10px] font-mono text-white max-h-40" data-testid="quest-partner-test-raw">
{typeof partnerTestResult.raw_response === 'string' ? partnerTestResult.raw_response : JSON.stringify(partnerTestResult.raw_response, null, 2)}
                          </pre>
                        </div>
                      )}
                    </div>
                  </>
                )}

                <div>
                  <Label className="text-xs">Инструкция (порядок действий для пользователя)</Label>
                  <textarea value={form.instructions} onChange={(e) => setForm(f => ({ ...f, instructions: e.target.value }))}
                    placeholder="Напр.: Перейдите по ссылке, купите рыбака и соберите 4 улова, затем нажмите «Проверить»."
                    rows={3}
                    className="w-full rounded-md bg-black/40 border border-white/10 text-sm text-white p-2 resize-y" data-testid="quest-instructions-input" />
                </div>

                <div className="flex items-center justify-between rounded-lg border border-white/10 bg-black/30 px-3 py-2" data-testid="quest-require-telegram-row">
                  <div className="pr-3">
                    <Label className="text-xs flex items-center gap-1"><Send className="w-3.5 h-3.5 text-sky-400" /> Требовать привязанный Telegram</Label>
                    <p className="text-[10px] text-text-muted mt-0.5">Если включено — пользователь без привязанного Telegram увидит просьбу привязать его для выполнения квеста.</p>
                  </div>
                  <Switch checked={!!form.require_telegram} onCheckedChange={(v) => setForm(f => ({ ...f, require_telegram: v }))} data-testid="quest-require-telegram-switch" />
                </div>

                <div className="flex items-center justify-between rounded-lg border border-white/10 bg-black/30 px-3 py-2" data-testid="quest-show-referrals-row" style={{ display: form.quest_kind === 'partner' ? 'flex' : 'none' }}>
                  <div className="pr-3">
                    <Label className="text-xs flex items-center gap-1"><Handshake className="w-3.5 h-3.5 text-emerald-400" /> Показывать рефералам партнёра</Label>
                    <p className="text-[10px] text-text-muted mt-0.5">Включено — задание видят <b>все</b> пользователи. Выключено — пользователи, пришедшие по ссылке этого партнёра, задание <b>не увидят</b> (остальные увидят).</p>
                  </div>
                  <Switch checked={!!form.show_to_referrals} onCheckedChange={(v) => setForm(f => ({ ...f, show_to_referrals: v }))} data-testid="quest-show-referrals-switch" />
                </div>

                <div>
                  <Label className="text-xs">Ссылка для перехода (реф-ссылка, необязательно)</Label>
                  <Input value={form.target_url} onChange={(e) => setForm(f => ({ ...f, target_url: e.target.value }))}
                    placeholder="https://partner.example.com/?ref=myref123" className="bg-black/40 border-white/10" data-testid="quest-visit-url-input" />
                  <p className="text-[10px] text-text-muted mt-1">Открывается у пользователя по кнопке «Выполнить». Оставьте пустым, если переход не нужен.</p>
                </div>

                {/* Reward: resources */}
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <Label className="text-xs flex items-center gap-1"><Boxes className="w-3.5 h-3.5 text-cyber-cyan" /> Награда: ресурсы на склад</Label>
                    <Button type="button" size="sm" variant="outline" className="h-7 text-xs"
                      onClick={() => setForm(f => ({ ...f, reward_resources: [...f.reward_resources, { type: 'crops', amount: '' }] }))}
                      data-testid="quest-add-resource-btn">+ Ресурс</Button>
                  </div>
                  {(form.reward_resources || []).map((r, i) => (
                    <div key={i} className="flex items-center gap-2 mb-1.5" data-testid={`quest-resource-row-${i}`}>
                      <Select value={r.type} onValueChange={(v) => setForm(f => ({ ...f, reward_resources: f.reward_resources.map((x, idx) => idx === i ? { ...x, type: v } : x) }))}>
                        <SelectTrigger className="bg-black/40 border-white/10 h-8 flex-1"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          {RESOURCE_TYPES.map(rt => <SelectItem key={rt} value={rt}>{rt}</SelectItem>)}
                        </SelectContent>
                      </Select>
                      <Input type="number" value={r.amount} placeholder="кол-во"
                        onChange={(e) => setForm(f => ({ ...f, reward_resources: f.reward_resources.map((x, idx) => idx === i ? { ...x, amount: e.target.value } : x) }))}
                        className="bg-black/40 border-white/10 h-8 w-24" data-testid={`quest-resource-amount-${i}`} />
                      <Button type="button" size="sm" variant="ghost" className="h-8 w-8 p-0 text-red-400"
                        onClick={() => setForm(f => ({ ...f, reward_resources: f.reward_resources.filter((_, idx) => idx !== i) }))}><X className="w-4 h-4" /></Button>
                    </div>
                  ))}
                </div>

                {/* Reward: skins (choose skin GROUP) */}
                <div>
                  <Label className="text-xs flex items-center gap-1 mb-1"><Sparkles className="w-3.5 h-3.5 text-cyber-cyan" /> Награда: скины (группа)</Label>
                  {skinGroups.length === 0 ? (
                    <p className="text-[11px] text-text-muted">Нет групп скинов. Добавьте скины в разделе «Данные → Скины».</p>
                  ) : (
                    <div className="flex flex-wrap gap-2" data-testid="quest-skin-groups">
                      {skinGroups.map(g => {
                        const on = (form.reward_skin_groups || []).includes(g.group_key);
                        return (
                          <button type="button" key={g.group_key}
                            data-testid={`quest-skin-group-${g.group_key}`}
                            onClick={() => setForm(f => ({
                              ...f,
                              reward_skin_groups: on
                                ? f.reward_skin_groups.filter(x => x !== g.group_key)
                                : [...f.reward_skin_groups, g.group_key],
                            }))}
                            className={`flex items-center gap-2 pl-1.5 pr-3 py-1.5 rounded-lg text-xs border transition-colors ${on ? 'border-emerald-400 bg-emerald-500/15 text-emerald-200' : 'border-white/15 bg-black/40 text-white/70 hover:border-cyber-cyan/50'}`}>
                            <span className="w-7 h-7 rounded-md overflow-hidden bg-black/40 flex items-center justify-center flex-shrink-0">
                              {skinImg(g.image) ? <img src={skinImg(g.image)} alt="" className="w-full h-full object-contain" /> : <Sparkles className="w-3.5 h-3.5" />}
                            </span>
                            {on && <Check className="w-3 h-3" />}{g.group_name}
                          </button>
                        );
                      })}
                    </div>
                  )}
                  <p className="text-[10px] text-text-muted mt-1">Выбранные группы скинов добавятся игроку в <code>available_skins</code> при выполнении квеста.</p>
                </div>

                {/* Reward: free-text description shown to the RIGHT of the skin image */}
                <div>
                  <Label className="text-xs flex items-center gap-1 mb-1"><Sparkles className="w-3.5 h-3.5 text-cyber-cyan" /> Описание награды (текст справа от скина)</Label>
                  <textarea value={form.reward_description}
                    onChange={(e) => setForm(f => ({ ...f, reward_description: e.target.value }))}
                    rows={3} placeholder="Например: Вы получите весь набор скинов коллекции Crazy на все ваши бизнесы."
                    className="w-full rounded-md bg-black/40 border border-white/10 text-sm text-white p-2 resize-y" data-testid="quest-reward-description-input" />
                  <p className="text-[10px] text-text-muted mt-1">Текст переводится автоматически на все языки и показывается справа от картинки скина в задании.</p>
                </div>

                {/* Reward: extra funds (bonus or real balance) */}
                <div>
                  <Label className="text-xs flex items-center gap-1 mb-1"><Coins className="w-3.5 h-3.5 text-cyber-cyan" /> Награда: средства ($CITY)</Label>
                  <div className="flex items-center gap-2">
                    <Input type="number" min="0" value={form.reward_funds_amount} placeholder="0"
                      onChange={(e) => setForm(f => ({ ...f, reward_funds_amount: e.target.value }))}
                      className="bg-black/40 border-white/10 h-9 w-32" data-testid="quest-funds-amount" />
                    {/* All task rewards are credited to the bonus balance (server-side rule). */}
                    <span className="text-xs text-text-muted flex-1" data-testid="quest-funds-target">На бонусный баланс (нельзя вывести)</span>
                  </div>
                </div>
              </div>
            )}

            {/* Live preview */}
            {form.title && (
              <div data-testid="task-preview">
                <Label className="text-xs text-cyber-cyan">Предпросмотр карточки</Label>
                <Card className="glass-panel border-white/10 mt-1">
                  <CardContent className="p-3">
                    <div className="flex items-center gap-3">
                      <div className="w-14 h-14 rounded-xl overflow-hidden flex-shrink-0 bg-white/5 flex items-center justify-center relative">
                        {form.photo ? (
                          <img src={form.photo} alt="" className="w-full h-full object-cover" />
                        ) : (() => {
                          const PI = ACTION_ICON[form.action_type] || ListChecks;
                          return <PI className="w-7 h-7 text-cyber-cyan" />;
                        })()}
                        {form.icon === 'custom' && form.icon_url ? (
                          <span className="absolute -bottom-1 -right-1 w-5 h-5 rounded-full overflow-hidden ring-2 ring-[#12121f] bg-white">
                            <img src={form.icon_url} alt="" className="w-full h-full object-cover" />
                          </span>
                        ) : (form.icon && SOCIAL_ICONS[form.icon] && (() => {
                          const S = SOCIAL_ICONS[form.icon];
                          return (
                            <span className={`absolute -bottom-1 -right-1 w-5 h-5 rounded-full ${S.bg} flex items-center justify-center ring-2 ring-[#12121f]`}>
                              <S.Icon className="w-3 h-3 text-white" />
                            </span>
                          );
                        })())}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-semibold text-white leading-snug">{form.title}</p>
                        <div className="flex items-center gap-1 mt-1 flex-wrap">
                          {form.action_type === 'ad_tiktok' ? (
                            <>
                              <Gift className="w-4 h-4 text-yellow-400" />
                              <span className="text-yellow-400 font-bold text-sm" data-testid="preview-views-rate">1000 просмотров = {parseFloat(form.views_rate) || 0} $CITY</span>
                            </>
                          ) : (parseInt(form.reward_city) || 0) > 0 ? (
                            <>
                              <Gift className="w-4 h-4 text-yellow-400" />
                              <span className="text-yellow-400 font-bold text-sm">+{parseInt(form.reward_city) || 0} $CITY</span>
                            </>
                          ) : null}
                          {['referral_invite', 'referral_active'].includes(form.action_type) && form.required_referrals && (
                            <span className="text-[11px] text-text-muted ml-2">0/{parseInt(form.required_referrals) || 0} {form.action_type === 'referral_active' ? 'активных приглашено' : 'приглашено'}</span>
                          )}
                        </div>
                      </div>
                      <div className="flex-shrink-0">
                        {form.action_type === 'partner_quest' ? (
                          <div className="flex flex-col items-end gap-1" data-testid="preview-partner-reward">
                            {(form.reward_skin_groups || []).map(gk => {
                              const g = skinGroups.find(x => x.group_key === gk);
                              return (
                                <span key={gk} className="inline-flex items-center gap-1.5 text-[11px] font-semibold text-fuchsia-300 bg-fuchsia-500/10 border border-fuchsia-500/30 rounded-lg pl-1 pr-2 py-1 max-w-[160px]">
                                  <span className="w-6 h-6 rounded-md overflow-hidden bg-fuchsia-500/20 flex items-center justify-center flex-shrink-0">
                                    {skinImg(g?.image) ? <img src={skinImg(g?.image)} alt="" className="w-full h-full object-contain" /> : <Sparkles className="w-3.5 h-3.5" />}
                                  </span>
                                  <span className="truncate">{g?.group_name || gk}</span>
                                </span>
                              );
                            })}
                            {((parseInt(form.reward_city) || 0) + (parseFloat(form.reward_funds_amount) || 0)) > 0 && (
                              <span className="inline-flex items-center gap-1 text-[13px] font-bold text-yellow-400">
                                <Coins className="w-4 h-4" /> +{(parseInt(form.reward_city) || 0) + (parseFloat(form.reward_funds_amount) || 0)}
                              </span>
                            )}
                            {(form.reward_resources || []).filter(r => parseFloat(r.amount) > 0).map((r, i) => (
                              <span key={i} className="inline-flex items-center gap-1 text-[11px] font-semibold text-emerald-400">
                                <Boxes className="w-3.5 h-3.5" /> +{parseFloat(r.amount) || 0} {r.type}
                              </span>
                            ))}
                          </div>
                        ) : (
                          <span className="inline-block px-3 py-1.5 rounded-md bg-cyber-cyan text-black text-xs font-bold">
                            {form.action_type === 'referral_invite' || form.action_type === 'referral_active' ? 'Поделиться' : 'Выполнить'}
                          </span>
                        )}
                      </div>
                    </div>
                  </CardContent>
                </Card>
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => { setShowAdd(false); setEditingId(null); setForm(emptyForm); }}>Отмена</Button>
            <Button disabled={creating} onClick={createTask} className="bg-cyber-cyan text-black hover:bg-cyber-cyan/80 font-bold" data-testid="task-create-submit">
              {creating ? <Loader2 className="w-4 h-4 animate-spin" /> : (editingId ? 'Сохранить' : 'Создать')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
