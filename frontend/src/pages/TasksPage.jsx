import { useState, useEffect, useCallback, useRef } from 'react';
import axios from 'axios';
import { toast } from 'sonner';
import { motion } from 'framer-motion';
import { ListChecks, Gift, CheckCircle2, Flame, Users, Play, Link2, Megaphone, Send, Music2, Twitter, Copy, Check, Rocket, Repeat, Clock, Trophy, Handshake, Boxes, Sparkles, Coins, X } from 'lucide-react';
import Sidebar from '@/components/Sidebar';
import PageHeader from '@/components/PageHeader';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent } from '@/components/ui/card';
import { useLanguage } from '@/context/LanguageContext';
import { useTranslation } from '@/lib/translations';
import QuestBoard from '@/components/QuestBoard';
import ComebackBanner from '@/components/ComebackBanner';
import { fill } from '@/lib/translationsMore';
import { showRewardedAd } from '@/lib/monetag';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api`;

// Skin images may be an absolute URL, a data: URI, or a backend /sprites path.
const skinImg = (img) => !img ? null : (/^(https?:|data:)/.test(img) ? img : `${BACKEND_URL}${img}`);

// Ensure an outbound link has a scheme so window.open navigates to the real
// site (a schemeless value like "example.com" would be treated as a relative
// path and keep the user inside the app).
const normalizeUrl = (u) => {
  if (!u) return '';
  const s = String(u).trim();
  if (!s) return '';
  if (/^(https?:|tg:|ton:|tonkeeper:|mailto:)/i.test(s)) return s;
  if (s.startsWith('//')) return `https:${s}`;
  return `https://${s.replace(/^\/+/, '')}`;
};

const getToken = () => localStorage.getItem('token') || localStorage.getItem('ton_city_token');
const authHeaders = () => ({ headers: { Authorization: `Bearer ${getToken()}` } });

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

// Local labels for the boost/story flows (project has many langs; keep RU + EN
// fallback here so the new statuses read correctly without a full i18n pass).
const LOCAL_LABELS = {
  crediting: { ru: 'Начисление награды…', en: 'Crediting reward…' },
  checking: { ru: 'На проверке', en: 'Under review' },
  boostFail: { ru: 'Голос не найден. Сбустите канал и попробуйте снова.', en: 'Boost not found. Please boost the channel and try again.' },
  skinWord: { en: 'Skin', ru: 'Скин', es: 'Skin', zh: '皮肤', fr: 'Skin', de: 'Skin', ja: 'スキン', ko: '스킨', id: 'Skin' },
  rewardWord: { en: 'Reward', ru: 'Награда', es: 'Recompensa', zh: '奖励', fr: 'Récompense', de: 'Belohnung', ja: '報酬', ko: '보상', id: 'Hadiah' },
  linkTelegramRequired: {
    en: 'Link your Telegram account in Settings to complete this task.',
    ru: 'Привяжите Telegram-аккаунт в настройках, чтобы выполнить это задание.',
    es: 'Vincula tu cuenta de Telegram en Ajustes para completar esta tarea.',
    zh: '请在设置中绑定您的 Telegram 账户以完成此任务。',
    fr: 'Liez votre compte Telegram dans les Paramètres pour accomplir cette tâche.',
    de: 'Verknüpfe dein Telegram-Konto in den Einstellungen, um diese Aufgabe abzuschließen.',
    ja: 'このタスクを完了するには、設定で Telegram アカウントを連携してください。',
    ko: '이 작업을 완료하려면 설정에서 Telegram 계정을 연결하세요.',
    id: 'Tautkan akun Telegram Anda di Pengaturan untuk menyelesaikan tugas ini.',
  },
};

// Repost-story timer length (must match backend STORY_CHECK_HOURS = 23h).
const STORY_TOTAL_SECONDS = 23 * 3600;

const SOCIAL_ICONS = {
  telegram: { Icon: Send, bg: 'bg-sky-500' },
  tiktok: { Icon: Music2, bg: 'bg-pink-500' },
  x: { Icon: Twitter, bg: 'bg-black' },
};

// "1000 views" translated for every project language (used on TikTok ad tasks)
const VIEWS_1000_LABEL = {
  en: '1000 views',
  ru: '1000 просмотров',
  es: '1000 visualizaciones',
  zh: '1000 次播放',
  fr: '1000 vues',
  de: '1000 Aufrufe',
  ja: '1000 回再生',
  ko: '조회수 1000회',
  id: '1000 tayangan',
};

export default function TasksPage({ user, refreshBalance }) {
  const { language: lang } = useLanguage();
  const { t } = useTranslation(lang);

  const [tasks, setTasks] = useState([]);
  const [daily, setDaily] = useState(null);
  const [loading, setLoading] = useState(true);
  const [started, setStarted] = useState({});      // taskId -> true (show "Check")
  const [adInput, setAdInput] = useState({});       // taskId -> string
  const [busy, setBusy] = useState({});             // taskId -> true
  const [refLink, setRefLink] = useState('');
  const [copied, setCopied] = useState(false);
  const [expandedId, setExpandedId] = useState(null);   // inline-expanded partner_quest id
  // «Система» / «Партнёры» tabs; ?tab=partners opens the partner tab directly.
  const [tab, setTab] = useState(() => {
    try { return new URLSearchParams(window.location.search).get('tab') === 'partners' ? 'partners' : 'system'; }
    catch { return 'system'; }
  });
  const selectTab = (next) => {
    setTab(next);
    try {
      const url = new URL(window.location.href);
      if (next === 'partners') url.searchParams.set('tab', 'partners'); else url.searchParams.delete('tab');
      window.history.replaceState(null, '', url.pathname + url.search + url.hash);
    } catch { /* ignore */ }
  };
  const daysRef = useRef(null);
  const [nowTs, setNowTs] = useState(Date.now());

  const ll = (k) => (LOCAL_LABELS[k]?.[lang] || LOCAL_LABELS[k]?.en || k);

  const computeRemaining = useCallback((task) => {
    if (task.check_available_at) {
      const target = new Date(task.check_available_at).getTime();
      return Math.max(0, Math.floor((target - nowTs) / 1000));
    }
    return task.remaining_seconds || 0;
  }, [nowTs]);

  const formatHM = (secs) => {
    const s = Math.max(0, secs | 0);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
  };

  const storyPct = useCallback((task) => {
    const rem = computeRemaining(task);
    return Math.min(100, Math.max(0, Math.round(((STORY_TOTAL_SECONDS - rem) / STORY_TOTAL_SECONDS) * 100)));
  }, [computeRemaining]);

  // 1s ticker for the repost-story countdown
  useEffect(() => {
    const id = setInterval(() => setNowTs(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  // Auto-scroll the daily-reward strip so the current/next day is at the left.
  // Keeps at least ~4 days visible; the scrollbar itself stays hidden.
  useEffect(() => {
    if (!daily || !daysRef.current) return;
    const c = daysRef.current;
    const gap = 6; // gap-1.5
    const itemW = (c.clientWidth - gap * 3) / 4; // 4 days visible per view
    const targetIndex = daily.claimed_today
      ? (daily.current_streak || 0)
      : Math.max(0, (daily.next_day || 1) - 1);
    const left = Math.max(0, targetIndex * (itemW + gap));
    c.scrollTo({ left, behavior: 'smooth' });
  }, [daily]);

  const copyRefLink = async () => {
    if (!refLink) return;
    try {
      await navigator.clipboard.writeText(refLink);
    } catch {
      const ta = document.createElement('textarea');
      ta.value = refLink; document.body.appendChild(ta); ta.select();
      try { document.execCommand('copy'); } catch {}
      document.body.removeChild(ta);
    }
    setCopied(true);
    toast.success(t('taskCopied'));
    setTimeout(() => setCopied(false), 2000);
  };

  const fetchTasks = useCallback(async () => {
    try {
      const [tRes, dRes] = await Promise.all([
        axios.get(`${API}/tasks`, authHeaders()),
        axios.get(`${API}/tasks/daily`, authHeaders()),
      ]);
      setTasks(tRes.data.tasks || []);
      setDaily(dRes.data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Error loading tasks');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchTasks(); }, [fetchTasks]);

  const isPartnerTask = (task) => (task.category
    ? task.category === 'partner'
    : task.action_type === 'partner_quest' && task.quest_kind === 'partner');
  const systemTasks = tasks.filter((task) => !isPartnerTask(task));
  const partnerTasks = tasks.filter(isPartnerTask);
  const openCount = (list) => list.filter((task) => task.status !== 'completed').length;
  const listedTasks = tab === 'partners' ? partnerTasks : systemTasks;

  // Once a repost-story countdown reaches 0 the server auto-credits the reward
  // within ~1 min. Poll (throttled) until the status flips to completed so the
  // card + balance update without a manual action.
  const lastPollRef = useRef(0);
  useEffect(() => {
    const hasExpiring = tasks.some(
      (task) => task.action_type === 'repost_story'
        && (task.status === 'pending_check' || task.status === 'ready_to_claim')
        && computeRemaining(task) <= 0
    );
    if (!hasExpiring) return;
    if (Date.now() - lastPollRef.current < 15000) return;
    lastPollRef.current = Date.now();
    fetchTasks();
    if (refreshBalance) refreshBalance();
  }, [nowTs, tasks, computeRemaining, fetchTasks, refreshBalance]);

  useEffect(() => {
    axios.get(`${API}/referrals/me`, authHeaders())
      .then(r => setRefLink(`${window.location.origin}${r.data.referral_path || ''}`))
      .catch(() => {});
  }, []);

  const title = (task) => (task.title_i18n && task.title_i18n[lang]) || task.title || '';
  const description = (task) => (task.instructions_i18n && task.instructions_i18n[lang]) || task.instructions || '';
  const rewardDesc = (task) => (task.reward_description_i18n && task.reward_description_i18n[lang]) || task.reward_description || '';

  // Daily bonus: first the rewarded ads (Monetag), then the claim
  const [adsOpen, setAdsOpen] = useState(false);
  // Russian plural of «реклама» for the ads text (other languages don't use {w})
  const ruAds = (n) => { const a = n % 10, b = n % 100; return (a === 1 && b !== 11) ? 'рекламу' : (a >= 2 && a <= 4 && (b < 12 || b > 14)) ? 'рекламы' : 'реклам'; };
  const [adBusy, setAdBusy] = useState(false);
  const onDailyClaim = () => {
    if (daily?.ads && !daily.ads.ok) { setAdsOpen(true); return; }
    claimDaily();
  };
  const watchAd = async () => {
    setAdBusy(true);
    try {
      const cfg = (await axios.get(`${API}/ads/config`)).data;
      await showRewardedAd(cfg, user?.id);
      let gate;
      try { gate = (await axios.post(`${API}/ads/daily/watched`, {}, authHeaders())).data; }
      catch (e) { if (e?.response?.data?.detail === 'ad_too_fast') { toast.error(t('ads_too_fast')); return; } throw e; }
      if (cfg.verify_postback) {                         // the ad network confirms the view a bit later
        toast.info(t('ads_wait_confirm'));
        for (let i = 0; i < 6 && !(gate && gate.ok); i += 1) {
          await new Promise((r) => setTimeout(r, 2500));
          gate = (await axios.get(`${API}/tasks/daily`, authHeaders())).data.ads;
        }
      }
      setDaily((d) => ({ ...d, ads: gate || d.ads }));
    } catch (e) {
      toast.error(t('ads_failed'));
    } finally { setAdBusy(false); }
  };

  const claimDaily = async () => {
    setAdsOpen(false);
    setBusy(b => ({ ...b, __daily: true }));
    try {
      const r = await axios.post(`${API}/tasks/daily/claim`, {}, authHeaders());
      toast.success(`+${r.data.reward_city} $CITY`);
      await fetchTasks();
      if (refreshBalance) refreshBalance();
    } catch (e) {
      if (e?.response?.data?.detail === 'ads_required') { await fetchTasks(); setAdsOpen(true); return; }
      toast.error(e?.response?.data?.detail || 'Error');
    } finally {
      setBusy(b => ({ ...b, __daily: false }));
    }
  };

  const handleStart = (task) => {
    if (task.action_type === 'referral_invite' || task.action_type === 'referral_active') {
      const text = 'Join GRAM City and build your digital city on TON!';
      if (navigator.share) {
        navigator.share({ title: 'GRAM City', text, url: refLink }).catch(() => {});
      } else {
        window.open(`https://t.me/share/url?url=${encodeURIComponent(refLink)}&text=${encodeURIComponent(text)}`, '_blank');
      }
    } else if (task.action_type === 'ad_tiktok') {
      // just reveal the input
    } else if (task.action_type === 'tg_channel_boost') {
      if (task.boost_url) window.open(task.boost_url, '_blank');
      else if (task.open_url) window.open(task.open_url, '_blank');
    } else if (task.action_type === 'repost_story') {
      if (task.open_url) window.open(task.open_url, '_blank');
    } else {
      const url = normalizeUrl(task.channel_url || task.target_url);
      if (url) window.open(url, '_blank', 'noopener,noreferrer');
    }
    setStarted(s => ({ ...s, [task.id]: true }));
  };

  const handleVerifyBoost = async (task) => {
    setBusy(b => ({ ...b, [task.id]: true }));
    try {
      const r = await axios.post(`${API}/tasks/${task.id}/verify-boost`, {}, authHeaders());
      if (r.data?.success) {
        toast.success(t('taskDone') + (r.data.reward_city ? ` +${r.data.reward_city} $CITY` : ''));
        await fetchTasks();
        if (refreshBalance) refreshBalance();
      } else {
        toast.error(r.data?.message || ll('boostFail'));
      }
    } catch (e) {
      toast.error(e?.response?.data?.detail || ll('boostFail'));
    } finally {
      setBusy(b => ({ ...b, [task.id]: false }));
    }
  };

  const handleStartCheck = async (task) => {
    setBusy(b => ({ ...b, [task.id]: true }));
    try {
      await axios.post(`${API}/tasks/${task.id}/start-check`, {}, authHeaders());
      await fetchTasks();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Error');
    } finally {
      setBusy(b => ({ ...b, [task.id]: false }));
    }
  };

  const handleVerify = async (task) => {
    setBusy(b => ({ ...b, [task.id]: true }));
    try {
      const r = await axios.post(`${API}/tasks/${task.id}/verify`, {}, authHeaders());
      const rc = r.data?.reward_city;
      toast.success(t('taskDone') + (rc ? ` +${rc} $CITY` : ''));
      await fetchTasks();
      if (refreshBalance) refreshBalance();
      return true;
    } catch (e) {
      toast.error(e?.response?.data?.detail || t('taskLinkInvalid'));
      return false;
    } finally {
      setBusy(b => ({ ...b, [task.id]: false }));
    }
  };

  // Partner-quest "Выполнить": open the partner project link the admin set,
  // then reveal the "Проверить" (check) button for this quest.
  const handleQuestGo = (task) => {
    // If the quest requires a linked Telegram account and the user hasn't
    // linked one, do NOT redirect — tell them to link it in Settings first.
    if (task.require_telegram && !user?.telegram_linked) {
      toast.error(ll('linkTelegramRequired'));
      return;
    }
    const url = normalizeUrl(task.target_url);
    if (url) {
      try { window.open(url, '_blank', 'noopener,noreferrer'); } catch {}
    }
    setStarted(s => ({ ...s, [task.id]: true }));
  };

  // Partner-quest "Проверить": auto-verify completion via the partner link.
  // On success collapse the card; on failure revert the button back to
  // "Выполнить" (started=false) so the user re-does the task and re-checks.
  const handleQuestCheck = async (task) => {
    const ok = await handleVerify(task);
    if (ok) {
      setExpandedId(null);
    } else {
      setStarted(s => ({ ...s, [task.id]: false }));
    }
  };

  const handleSubmitAd = async (task) => {
    const url = (adInput[task.id] || '').trim();
    setBusy(b => ({ ...b, [task.id]: true }));
    try {
      await axios.post(`${API}/tasks/${task.id}/submit-ad`, { url }, authHeaders());
      toast.success(t('taskSubmitted'));
      setAdInput(a => ({ ...a, [task.id]: '' }));
      setStarted(s => ({ ...s, [task.id]: false }));
      await fetchTasks();
    } catch (e) {
      toast.error(e?.response?.data?.detail || t('taskLinkInvalid'));
    } finally {
      setBusy(b => ({ ...b, [task.id]: false }));
    }
  };

  const renderAction = (task) => {
    if (task.status === 'completed') {
      return (
        <div className="flex items-center gap-1.5 text-green-400 font-bold text-xs sm:text-sm" data-testid={`task-status-done-${task.id}`}>
          <CheckCircle2 className="w-5 h-5" /> {t('taskDone')}
        </div>
      );
    }

    if (task.action_type === 'tg_channel_boost') {
      if (!started[task.id]) {
        return (
          <Button size="sm" onClick={() => handleStart(task)}
            className="bg-cyber-cyan text-black hover:bg-cyber-cyan/80 font-bold h-8 px-3 text-xs whitespace-nowrap" data-testid={`task-do-btn-${task.id}`}>
            {t('taskDo')}
          </Button>
        );
      }
      return (
        <Button size="sm" disabled={busy[task.id]} onClick={() => handleVerifyBoost(task)}
          className="bg-green-600 hover:bg-green-700 font-bold h-8 px-3 text-xs whitespace-nowrap" data-testid={`task-check-btn-${task.id}`}>
          {t('taskCheck')}
        </Button>
      );
    }

    if (task.action_type === 'repost_story') {
      if (task.status === 'ready_to_claim') {
        return (
          <div className="flex items-center gap-1.5 text-yellow-400 font-bold text-xs sm:text-sm animate-pulse" data-testid={`task-crediting-${task.id}`}>
            <Trophy className="w-4 h-4" /> {ll('crediting')}
          </div>
        );
      }
      if (task.status === 'pending_check') {
        return (
          <div className="flex items-center gap-1.5 text-cyber-cyan font-bold text-xs sm:text-sm tabular-nums" data-testid={`task-countdown-${task.id}`}>
            <Clock className="w-4 h-4" /> {formatHM(computeRemaining(task))}
          </div>
        );
      }
      if (!started[task.id]) {
        return (
          <Button size="sm" onClick={() => handleStart(task)}
            className="bg-cyber-cyan text-black hover:bg-cyber-cyan/80 font-bold h-8 px-3 text-xs whitespace-nowrap" data-testid={`task-do-btn-${task.id}`}>
            {t('taskDo')}
          </Button>
        );
      }
      return (
        <Button size="sm" disabled={busy[task.id]} onClick={() => handleStartCheck(task)}
          className="bg-green-600 hover:bg-green-700 font-bold h-8 px-3 text-xs whitespace-nowrap" data-testid={`task-check-btn-${task.id}`}>
          {t('taskCheck')}
        </Button>
      );
    }

    if (task.action_type === 'ad_tiktok') {
      if (task.status === 'submitted') {
        return <div className="text-yellow-400 font-bold text-xs sm:text-sm" data-testid={`task-status-review-${task.id}`}>{t('taskSubmitted')}</div>;
      }
      if (!started[task.id]) {
        return (
          <Button size="sm" onClick={() => handleStart(task)}
            className="bg-cyber-cyan text-black hover:bg-cyber-cyan/80 font-bold h-8 px-3 text-xs whitespace-nowrap" data-testid={`task-do-btn-${task.id}`}>
            {t('taskDo')}
          </Button>
        );
      }
      return null; // input rendered below the card body
    }

    const isReferral = task.action_type === 'referral_invite' || task.action_type === 'referral_active';
    if (isReferral && task.status === 'ready') {
      return (
        <Button size="sm" disabled={busy[task.id]} onClick={() => handleVerify(task)}
          className="bg-green-600 hover:bg-green-700 font-bold animate-pulse h-8 px-3 text-xs whitespace-nowrap" data-testid={`task-check-btn-${task.id}`}>
          {t('taskCheck')}
        </Button>
      );
    }

    if (!started[task.id]) {
      return (
        <Button size="sm" onClick={() => handleStart(task)}
          className="bg-cyber-cyan text-black hover:bg-cyber-cyan/80 font-bold h-8 px-3 text-xs whitespace-nowrap" data-testid={`task-do-btn-${task.id}`}>
          {isReferral ? t('taskShare') : t('taskDo')}
        </Button>
      );
    }
    return (
      <Button size="sm" disabled={busy[task.id]} onClick={() => handleVerify(task)}
        className="bg-green-600 hover:bg-green-700 font-bold h-8 px-3 text-xs whitespace-nowrap" data-testid={`task-check-btn-${task.id}`}>
        {t('taskCheck')}
      </Button>
    );
  };

  // ── Partner quest card: collapsed shows the reward/skin; clicking expands
  // the card in place (image left ~30% + full description right, reward centered
  // below with the skin image + name, then the Выполнить / Проверить buttons).
  const renderPartnerQuest = (task) => {
    const expanded = expandedId === task.id;
    const completed = task.status === 'completed';
    const Icon = ACTION_ICON[task.action_type] || Handshake;
    const coins = (task.reward_city || 0) + (task.reward_funds_amount || 0);
    const res = task.reward_resources ? Object.entries(task.reward_resources) : [];
    const skins = task.reward_skins || [];
    const hasReward = coins > 0 || res.length > 0 || skins.length > 0;

    const taskImg = task.photo
      ? <img src={task.photo} alt="" className="w-full h-full object-cover" />
      : <Icon className="w-1/2 h-1/2 text-cyber-cyan" />;

    return (
      <motion.div key={task.id} layout initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
        <Card
          className={`glass-panel overflow-hidden transition-colors ${completed ? 'opacity-70 border-green-500/30' : expanded ? 'border-cyber-cyan/50' : 'border-white/10 cursor-pointer hover:border-cyber-cyan/40'}`}
          onClick={!expanded && !completed ? () => setExpandedId(task.id) : undefined}
          data-testid={`task-card-${task.id}`}>

          {!expanded ? (
            /* ---------- COLLAPSED ---------- */
            <CardContent className="p-2.5 sm:p-3">
              <div className="flex items-center gap-2.5 sm:gap-3">
                <div className="w-12 h-12 sm:w-14 sm:h-14 rounded-xl overflow-hidden flex-shrink-0 bg-white/5 flex items-center justify-center">
                  {taskImg}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-[13px] sm:text-sm font-semibold text-white leading-snug break-words">{title(task)}</p>
                  {(task.instructions_i18n || task.instructions) && (
                    <p className="text-[11px] text-text-muted mt-0.5 leading-snug line-clamp-1" data-testid={`task-instructions-${task.id}`}>{description(task)}</p>
                  )}
                  {(task.partner_need != null && !completed) && (
                    <span className="inline-flex items-center gap-1 mt-1 text-[11px] font-semibold text-cyber-cyan" data-testid={`task-progress-badge-${task.id}`}>
                      {task.partner_progress_ready && task.partner_have != null ? task.partner_have : 0} {t('questProgressOf') || 'из'} {task.partner_need}
                    </span>
                  )}
                </div>
                {/* reward / skin shown here instead of a "Подробнее" button */}
                <div className="flex-shrink-0 flex flex-col items-end gap-1" data-testid={`task-reward-preview-${task.id}`}>
                  {completed ? (
                    <span className="flex items-center gap-1.5 text-green-400 font-bold text-xs sm:text-sm" data-testid={`task-status-done-${task.id}`}>
                      <CheckCircle2 className="w-5 h-5" /> {t('taskDone')}
                    </span>
                  ) : (
                    <>
                      {skins.map((s) => (
                        <span key={s.id} className="inline-flex items-center gap-1.5 text-[11px] font-semibold text-fuchsia-200 bg-fuchsia-500/10 border border-fuchsia-500/30 rounded-lg pl-1 pr-2 py-1 max-w-[100px] sm:max-w-[160px]" data-testid={`task-reward-skin-${task.id}-${s.id}`}>
                          <span className="w-7 h-7 rounded-md overflow-hidden bg-black/30 flex items-center justify-center flex-shrink-0">
                            {skinImg(s.image) ? <img src={skinImg(s.image)} alt="" className="w-full h-full object-contain" /> : <Sparkles className="w-3.5 h-3.5" />}
                          </span>
                          <span className="truncate">{s.name || s.id}</span>
                        </span>
                      ))}
                      {coins > 0 && (
                        <span className="inline-flex items-center gap-1 text-[13px] font-bold text-yellow-400" data-testid={`task-reward-coins-${task.id}`}>
                          <Coins className="w-4 h-4" /> +{coins}
                        </span>
                      )}
                      {res.map(([rt, amt]) => (
                        <span key={rt} className="inline-flex items-center gap-1 text-[11px] font-semibold text-emerald-400" data-testid={`task-reward-res-${task.id}-${rt}`}>
                          <Boxes className="w-3.5 h-3.5" /> +{amt} {rt}
                        </span>
                      ))}
                    </>
                  )}
                </div>
              </div>
            </CardContent>
          ) : (
            /* ---------- EXPANDED ---------- */
            <CardContent className="p-4" data-testid={`task-expanded-${task.id}`}>
              {/* title on top + collapse */}
              <div className="flex items-start justify-between gap-2 mb-3">
                <h3 className="text-base sm:text-lg font-bold text-white leading-snug" data-testid="quest-detail-title">{title(task)}</h3>
                <button onClick={(e) => { e.stopPropagation(); setExpandedId(null); }}
                  className="flex-shrink-0 w-8 h-8 rounded-lg flex items-center justify-center text-text-muted hover:text-white hover:bg-white/10 transition-colors"
                  aria-label="close" data-testid={`task-collapse-${task.id}`}>
                  <X className="w-5 h-5" />
                </button>
              </div>

              {/* image (~30%) left + full description right */}
              <div className="flex gap-3 sm:gap-4">
                <div className="w-[30%] flex-shrink-0">
                  <div className="w-full aspect-square rounded-xl overflow-hidden bg-white/5 flex items-center justify-center">
                    {taskImg}
                  </div>
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-[11px] uppercase tracking-wide text-text-muted mb-1.5">{t('questDescriptionLabel')}</p>
                  <p className="text-sm text-white/90 leading-relaxed whitespace-pre-line" data-testid="quest-detail-description">
                    {description(task) || t('questNoDescription')}
                  </p>
                </div>
              </div>

              {/* reward — centered, skin shows image left + name right */}
              {hasReward && (
                <div className="mt-4 pt-4 border-t border-white/10" data-testid="quest-detail-reward">
                  <p className="text-[11px] uppercase tracking-wide text-text-muted mb-2.5 text-center">{t('questRewardLabel')}</p>
                  <div className="flex flex-col items-center gap-2.5">
                    {skins.map((s) => (
                      <div key={s.id} className="flex items-start gap-3.5 w-full bg-gradient-to-r from-fuchsia-500/15 to-purple-500/10 border border-fuchsia-500/40 rounded-2xl p-3" data-testid={`quest-detail-reward-skin-${s.id}`}>
                        <div className="w-24 h-24 rounded-xl overflow-hidden bg-black/40 ring-1 ring-fuchsia-500/30 flex items-center justify-center flex-shrink-0">
                          {skinImg(s.image) ? <img src={skinImg(s.image)} alt={s.name || s.id} className="w-full h-full object-contain" /> : <Sparkles className="w-10 h-10 text-fuchsia-300" />}
                        </div>
                        <div className="text-left min-w-0 flex-1 pt-0.5">
                          <p className="text-[10px] uppercase tracking-widest text-fuchsia-300/70 mb-0.5">{ll('skinWord')}</p>
                          <p className="text-base font-extrabold text-white leading-tight break-words">{s.name || s.id}</p>
                          {rewardDesc(task) && (
                            <p className="text-[13px] text-white/80 leading-snug mt-1.5 whitespace-pre-line break-words" data-testid={`quest-detail-reward-text-${s.id}`}>{rewardDesc(task)}</p>
                          )}
                        </div>
                      </div>
                    ))}
                    {/* Reward description shown even when there is no skin image */}
                    {skins.length === 0 && rewardDesc(task) && (
                      <p className="text-[13px] text-white/80 leading-snug whitespace-pre-line break-words text-center max-w-[320px]" data-testid="quest-detail-reward-text">{rewardDesc(task)}</p>
                    )}
                    {coins > 0 && (
                      <div className="flex items-center gap-2 text-base font-bold text-yellow-400 bg-yellow-500/10 border border-yellow-500/25 rounded-xl px-4 py-2" data-testid="quest-detail-reward-coins">
                        <Coins className="w-5 h-5" /> +{coins} $CITY
                      </div>
                    )}
                    {res.map(([rt, amt]) => (
                      <div key={rt} className="flex items-center gap-2 text-sm font-semibold text-emerald-400 bg-emerald-500/10 border border-emerald-500/25 rounded-xl px-4 py-2" data-testid={`quest-detail-reward-res-${rt}`}>
                        <Boxes className="w-5 h-5" /> +{amt} {rt}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Прогресс порогового квеста (напр. iTerra tradeVolume): текущее
                  значение из порога с учётом baseline (прирост с момента выдачи). */}
              {(task.partner_need != null) && (() => {
                const need = Number(task.partner_need) || 0;
                const have = task.partner_have != null ? Number(task.partner_have) : null;
                const ready = task.partner_progress_ready;
                const pct = (ready && need > 0 && have != null)
                  ? Math.min(100, Math.round((have / need) * 100)) : 0;
                return (
                  <div className="mt-4 pt-4 border-t border-white/10" data-testid={`quest-progress-${task.id}`}>
                    <div className="flex items-center justify-between mb-1.5">
                      <span className="text-[11px] uppercase tracking-wide text-text-muted">
                        {t('questProgressLabel') || 'Прогресс'}
                      </span>
                      <span className="text-sm font-bold text-cyber-cyan" data-testid={`quest-progress-value-${task.id}`}>
                        {ready && have != null ? have : 0} {t('questProgressOf') || 'из'} {need}
                      </span>
                    </div>
                    <div className="w-full h-2 rounded-full bg-white/10 overflow-hidden">
                      <div className="h-full bg-cyber-cyan transition-all" style={{ width: `${pct}%` }} data-testid={`quest-progress-bar-${task.id}`} />
                    </div>
                    {!ready && (
                      <p className="text-[10px] text-text-muted mt-1">{t('questProgressPending') || 'Обновляется…'}</p>
                    )}
                  </div>
                );
              })()}

              {/* actions — single toggling button:
                  not started → "Выполнить" (opens the link);
                  started     → "Проверить" (verifies; reverts on failure). */}
              <div className="mt-4">
                {completed ? (
                  <div className="w-full flex items-center justify-center gap-1.5 text-green-400 font-bold py-2" data-testid="quest-detail-done">
                    <CheckCircle2 className="w-5 h-5" /> {t('taskDone')}
                  </div>
                ) : !started[task.id] ? (
                  <Button onClick={(e) => { e.stopPropagation(); handleQuestGo(task); }}
                    className="w-full bg-cyber-cyan text-black hover:bg-cyber-cyan/80 font-bold h-11 text-sm" data-testid="quest-detail-do-btn">
                    <Play className="w-4 h-4 mr-1.5" /> {t('questComplete')}
                  </Button>
                ) : (
                  <Button disabled={busy[task.id]} onClick={(e) => { e.stopPropagation(); handleQuestCheck(task); }}
                    className="w-full bg-green-600 hover:bg-green-700 font-bold h-11 text-sm disabled:opacity-60" data-testid="quest-detail-check-btn">
                    <CheckCircle2 className="w-4 h-4 mr-1.5" /> {t('taskCheck')}
                  </Button>
                )}
              </div>
            </CardContent>
          )}
        </Card>
      </motion.div>
    );
  };


  const rewards = daily?.rewards || [];

  return (
    <div className="flex h-screen bg-void">
      {adsOpen && daily?.ads && (
        <div className="fixed inset-0 z-[90] bg-black/70 flex items-end sm:items-center justify-center p-4" onClick={() => setAdsOpen(false)} data-testid="daily-ads-modal">
          <div className="w-full max-w-sm rounded-2xl border border-yellow-400/40 bg-[#0b1020] p-4 space-y-3 mb-[calc(var(--bottom-nav-h,60px)+env(safe-area-inset-bottom))] sm:mb-0" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-white font-bold"><Flame className="w-5 h-5 text-orange-400" />{t('ads_title')}</div>
              <button type="button" onClick={() => setAdsOpen(false)} className="text-white/60"><X className="w-5 h-5" /></button>
            </div>
            <div className="text-sm text-white/80">{fill(t('ads_text'), { n: daily.ads.required, w: ruAds(daily.ads.required) })}</div>
            <div className="flex gap-2">
              {Array.from({ length: daily.ads.required }, (_, i) => (
                <div key={i} className={`flex-1 h-2 rounded-full ${i < daily.ads.watched ? 'bg-yellow-400' : 'bg-white/10'}`} />
              ))}
            </div>
            <div className="text-xs text-text-muted" data-testid="daily-ads-progress">{fill(t('ads_progress'), { a: daily.ads.watched, b: daily.ads.required })}</div>
            {daily.ads.watched >= daily.ads.required ? (
              <Button className="w-full h-11 bg-yellow-500 text-black hover:bg-yellow-400 font-bold" onClick={claimDaily} data-testid="daily-ads-claim">{t('ads_claim')} +{daily.next_reward}</Button>
            ) : (
              <Button className="w-full h-11 bg-yellow-500 text-black hover:bg-yellow-400 font-bold disabled:opacity-60" disabled={adBusy} onClick={watchAd} data-testid="daily-ads-watch">
                <Play className="w-4 h-4 mr-1.5" />{adBusy ? '…' : t('ads_watch')}
              </Button>
            )}
          </div>
        </div>
      )}
      <Sidebar user={user} refreshBalance={refreshBalance} />
      <div className="flex-1 overflow-hidden lg:ml-16">
        <ScrollArea className="h-full tasks-scroll">
          <div className="p-4 lg:px-6 lg:pt-2 lg:pb-6 pt-0 space-y-4 lg:space-y-6 max-w-3xl mx-auto w-full min-w-0">
            <PageHeader
              icon={<ListChecks className="w-6 h-6 text-yellow-400" />}
              title={t('tasksPageTitle')}
              subtitle={t('tasksSubtitle')}
            />

            {/* Daily login reward card */}
            {daily && (
              <Card className="glass-panel border-yellow-500/30 bg-gradient-to-br from-yellow-500/10 to-orange-500/5" data-testid="daily-login-card">
                <CardContent className="p-3 sm:p-4">
                  <div className="flex items-center justify-between gap-2 mb-2 sm:mb-3">
                    <div className="flex items-center gap-2 min-w-0">
                      <Flame className="w-5 h-5 text-orange-400 flex-shrink-0" />
                      <span className="font-bold text-white uppercase text-xs sm:text-sm tracking-wide truncate">{t('tasksDailyTitle')}</span>
                    </div>
                    <Button size="sm" disabled={daily.claimed_today || busy.__daily || !daily.activity_met} onClick={onDailyClaim}
                      className="bg-yellow-500 text-black hover:bg-yellow-400 font-bold disabled:opacity-50 flex-shrink-0 h-8 px-3 text-xs sm:text-sm" data-testid="daily-claim-btn">
                      {daily.claimed_today ? t('tasksDailyClaimed') : t('tasksDailyClaim')}
                    </Button>
                  </div>
                  <p className="text-xs text-text-muted mb-3">{t('tasksDailyDesc')}</p>
                  {/* Daily reward requirement: finish any one goal in «Today» */}
                  {!daily.claimed_today && (
                    <div className={`mb-3 text-[11px] flex items-center gap-1 ${daily.quest_goal_done ? 'text-emerald-400' : 'text-yellow-300'}`} data-testid="daily-goal-requirement">
                      {daily.quest_goal_done && <CheckCircle2 className="w-3 h-3" />}
                      {t('dailyGoalRequirement')}
                    </div>
                  )}
                  <div ref={daysRef} className="flex gap-1.5 overflow-x-auto scrollbar-hide -mx-1 px-1 snap-x" data-testid="daily-days-strip">
                    {rewards.map((amt, i) => {
                      const dayNum = i + 1;
                      const done = daily.current_streak >= dayNum;
                      const isNext = !daily.claimed_today && daily.next_day === dayNum;
                      return (
                        <div key={i}
                          style={{ minWidth: 'calc((100% - 18px) / 4)' }}
                          className={`flex-shrink-0 snap-start rounded-lg p-1.5 text-center border ${
                            done ? 'bg-green-500/20 border-green-500/40'
                            : isNext ? 'bg-yellow-500/20 border-yellow-500/60 ring-1 ring-yellow-400'
                            : 'bg-white/5 border-white/10'}`}
                          data-testid={`daily-day-${dayNum}`}>
                          <div className="text-[9px] text-text-muted uppercase whitespace-nowrap">{t('tasksDailyDay')} {dayNum}</div>
                          <div className="text-xs font-bold text-yellow-400">+{amt}</div>
                        </div>
                      );
                    })}
                  </div>
                </CardContent>
              </Card>
            )}


            {/* «Система» / «Партнёры» */}
            <div className="grid grid-cols-2 gap-2" role="tablist" data-testid="tasks-tabs">
              {[
                { id: 'system', label: t('tasksTabSystem'), Icon: ListChecks, count: openCount(systemTasks) },
                { id: 'partners', label: t('tasksTabPartners'), Icon: Handshake, count: openCount(partnerTasks) },
              ].map(({ id, label, Icon: TabIcon, count }) => (
                <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => selectTab(id)}
                  data-testid={`tasks-tab-${id}`}
                  className={`relative flex items-center justify-center gap-2 rounded-xl border px-3 py-3 text-sm font-bold uppercase tracking-wide transition-all ${
                    tab === id
                      ? 'border-yellow-400/60 bg-yellow-400/15 text-yellow-300 shadow-[0_0_16px_rgba(250,204,21,0.15)]'
                      : 'border-white/10 bg-white/5 text-white/70 hover:border-white/20'}`}>
                  <TabIcon className="w-4 h-4" />
                  <span>{label}</span>
                  {count > 0 && (
                    <span className={`min-w-[20px] h-5 px-1.5 rounded-full text-[11px] leading-5 ${tab === id ? 'bg-yellow-400 text-black' : 'bg-white/15 text-white'}`}>{count}</span>
                  )}
                </button>
              ))}
            </div>
            <p className="text-[11px] text-text-muted -mt-2 px-1" data-testid="tasks-bonus-note">{t('tasksBonusNote')}</p>

            {tab === 'system' && (<>
            {/* In-game quests: «Путь новичка», «Сегодня», «Неделя» (backend/quests.py) */}
            <QuestBoard lang={lang} onChanged={() => { fetchTasks(); refreshBalance && refreshBalance(); }} />

            {/* Comeback bonus + streak shields (backend/comeback.py) */}
            <ComebackBanner lang={lang} onChanged={() => { fetchTasks(); refreshBalance && refreshBalance(); }} />

            </>)}

            {/* Task list of the selected tab */}
            {loading ? (
              <div className="text-center text-text-muted py-10">…</div>
            ) : listedTasks.length === 0 ? (tab === 'system' ? null :
              <div className="text-center text-text-muted py-10" data-testid="tasks-empty">
                {tab === 'partners' ? t('tasksPartnersEmpty') : t('tasksEmpty')}
              </div>
            ) : (
              <div className="space-y-2.5 sm:space-y-3" data-testid={`tasks-list-${tab}`}>
                {listedTasks.map((task) => {
                  if (task.action_type === 'partner_quest') return renderPartnerQuest(task);
                  const Icon = ACTION_ICON[task.action_type] || ListChecks;
                  const showAdInput = task.action_type === 'ad_tiktok' && started[task.id] && task.status !== 'completed' && task.status !== 'submitted';
                  const isReferral = task.action_type === 'referral_invite' || task.action_type === 'referral_active';
                  const refNeed = task.referral_need ?? task.required_referrals ?? 0;
                  const refHave = task.referral_have || 0;
                  const refPct = refNeed > 0 ? Math.min(100, Math.round((refHave / refNeed) * 100)) : 0;
                  return (
                    <motion.div key={task.id} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
                      <Card
                        className={`glass-panel ${task.status === 'completed' ? 'opacity-70 border-green-500/30' : 'border-white/10'}`}
                        data-testid={`task-card-${task.id}`}>
                        <CardContent className="p-2.5 sm:p-3">
                          <div className="flex items-center gap-2.5 sm:gap-3">
                            <div className="w-12 h-12 sm:w-14 sm:h-14 rounded-xl overflow-hidden flex-shrink-0 bg-white/5 flex items-center justify-center relative">
                              {task.photo ? (
                                <img src={task.photo} alt="" className="w-full h-full object-cover" />
                              ) : (
                                <Icon className="w-6 h-6 sm:w-7 sm:h-7 text-cyber-cyan" />
                              )}
                              {task.icon === 'custom' && task.icon_url ? (
                                <span className="absolute -bottom-1 -right-1 w-5 h-5 rounded-full overflow-hidden ring-2 ring-void bg-white" data-testid={`task-social-icon-${task.id}`}>
                                  <img src={task.icon_url} alt="" className="w-full h-full object-cover" />
                                </span>
                              ) : (task.icon && SOCIAL_ICONS[task.icon] && (() => {
                                const S = SOCIAL_ICONS[task.icon];
                                return (
                                  <span className={`absolute -bottom-1 -right-1 w-5 h-5 rounded-full ${S.bg} flex items-center justify-center ring-2 ring-void`} data-testid={`task-social-icon-${task.id}`}>
                                    <S.Icon className="w-3 h-3 text-white" />
                                  </span>
                                );
                              })())}
                            </div>
                            <div className="flex-1 min-w-0">
                              <p className="text-[13px] sm:text-sm font-semibold text-white leading-snug break-words">{title(task)}</p>
                              <div className="flex items-center gap-1 mt-1 flex-wrap">
                                {(task.action_type === 'ad_tiktok' && task.views_rate) ? (
                                  <>
                                    <Gift className="w-4 h-4 text-yellow-400" />
                                    <span className="text-yellow-400 font-bold text-[13px] sm:text-sm" data-testid={`task-views-rate-${task.id}`}>
                                      {VIEWS_1000_LABEL[lang] || VIEWS_1000_LABEL.en} = {task.views_rate} $CITY
                                    </span>
                                  </>
                                ) : (task.reward_city > 0) ? (
                                  <>
                                    <Gift className="w-4 h-4 text-yellow-400" />
                                    <span className="text-yellow-400 font-bold text-[13px] sm:text-sm">+{task.reward_city} $CITY</span>
                                  </>
                                ) : null}
                                {isReferral && (
                                  <span className="text-[11px] text-text-muted ml-1.5">
                                    {refHave}/{refNeed} {task.action_type === 'referral_active' ? t('taskActiveInvited') : t('taskInvited')}
                                  </span>
                                )}
                                {task.reward_resources && Object.entries(task.reward_resources).map(([rt, amt]) => (
                                  <span key={rt} className="inline-flex items-center gap-1 text-[11px] font-semibold text-emerald-400 bg-emerald-500/10 rounded px-1.5 py-0.5" data-testid={`task-reward-res-${task.id}-${rt}`}>
                                    <Boxes className="w-3 h-3" /> +{amt} {rt}
                                  </span>
                                ))}
                                {task.reward_skins && task.reward_skins.map((s) => (
                                  <span key={s.id} className="inline-flex items-center gap-1 text-[11px] font-semibold text-fuchsia-400 bg-fuchsia-500/10 rounded px-1.5 py-0.5" data-testid={`task-reward-skin-${task.id}-${s.id}`}>
                                    <Sparkles className="w-3 h-3" /> {s.name || s.id}
                                  </span>
                                ))}
                              </div>
                              {task.action_type === 'partner_quest' && (task.instructions_i18n || task.instructions) && (
                                <p className="text-[11px] text-text-muted mt-1 leading-snug line-clamp-1" data-testid={`task-instructions-${task.id}`}>{description(task)}</p>
                              )}
                            </div>
                            <div className="flex-shrink-0">{renderAction(task)}</div>
                          </div>

                          {/* Referral link + progress (invite / active-invite tasks) */}
                          {isReferral && task.status !== 'completed' && (
                            <div className="mt-2.5 space-y-2" data-testid={`task-referral-block-${task.id}`}>
                              <div className="h-1.5 w-full rounded-full bg-white/10 overflow-hidden">
                                <div className="h-full bg-gradient-to-r from-cyber-cyan to-green-400 transition-all" style={{ width: `${refPct}%` }} />
                              </div>
                              <div className="flex items-center gap-2">
                                <span className="text-[10px] uppercase tracking-wide text-text-muted flex-shrink-0 hidden sm:inline">{t('taskYourRefLink')}</span>
                                <div className="flex-1 min-w-0 flex items-center gap-1.5 bg-black/40 border border-white/10 rounded-lg px-2 py-1.5">
                                  <span className="truncate text-[11px] text-cyber-cyan font-mono" data-testid={`task-ref-link-${task.id}`}>{refLink}</span>
                                </div>
                                <Button size="sm" onClick={copyRefLink}
                                  className="bg-white/10 hover:bg-white/20 text-white flex-shrink-0 h-8 px-2.5" data-testid={`task-ref-copy-${task.id}`}>
                                  {copied ? <Check className="w-4 h-4 text-green-400" /> : <Copy className="w-4 h-4" />}
                                  <span className="ml-1 text-xs hidden sm:inline">{copied ? t('taskCopied') : t('taskCopy')}</span>
                                </Button>
                              </div>
                            </div>
                          )}

                          {/* Repost-story progress bar next to the countdown */}
                          {task.action_type === 'repost_story' && task.status === 'pending_check' && (
                            <div className="mt-2.5 space-y-1.5" data-testid={`task-story-progress-${task.id}`}>
                              <div className="flex items-center justify-between text-[11px]">
                                <span className="uppercase tracking-wide text-text-muted">{ll('checking')}</span>
                                <span className="flex items-center gap-1 text-cyber-cyan font-bold tabular-nums">
                                  <Clock className="w-3.5 h-3.5" /> {formatHM(computeRemaining(task))}
                                </span>
                              </div>
                              <div className="h-1.5 w-full rounded-full bg-white/10 overflow-hidden">
                                <div className="h-full bg-gradient-to-r from-cyber-cyan to-green-400 transition-all"
                                  style={{ width: `${storyPct(task)}%` }} data-testid={`task-story-bar-${task.id}`} />
                              </div>
                            </div>
                          )}

                          {/* TikTok link input (ad_tiktok) */}
                          {showAdInput && (
                            <div className="mt-3 flex items-center gap-2" data-testid={`task-ad-input-wrap-${task.id}`}>
                              <Input
                                value={adInput[task.id] || ''}
                                onChange={(e) => setAdInput(a => ({ ...a, [task.id]: e.target.value }))}
                                placeholder={t('taskEnterLink')}
                                className="bg-black/40 border-white/10 text-sm"
                                data-testid={`task-ad-input-${task.id}`}
                              />
                              <Button size="sm" disabled={busy[task.id]} onClick={() => handleSubmitAd(task)}
                                className="bg-green-600 hover:bg-green-700 flex-shrink-0" data-testid={`task-ad-submit-${task.id}`}>
                                <Send className="w-4 h-4" />
                              </Button>
                            </div>
                          )}
                        </CardContent>
                      </Card>
                    </motion.div>
                  );
                })}
              </div>
            )}
          </div>
        </ScrollArea>
      </div>
    </div>
  );
}
