import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTonWallet } from '@/lib/tonconnect-lazy';
import { motion } from 'framer-motion';
import { 
  Users, Building2, DollarSign, TrendingUp, Settings, 
  CreditCard, Bell, Gift, RefreshCw, Check, X, ArrowLeft, Wallet, Copy,
  Wrench, Play, Clock, Home, Calendar, Map, Trash2, AlertCircle, Mail, Loader2
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import RetentionPanel from '@/components/admin/RetentionPanel';
import MarketMakerPanel from '@/components/admin/MarketMakerPanel';
import ComebackPanel from '@/components/admin/ComebackPanel';
import LeaguesPanel from '@/components/admin/LeaguesPanel';
import ReconciliationPanel from '@/components/admin/ReconciliationPanel';
import CityPassPanel from '@/components/admin/CityPassPanel';
import RentalPanel from '@/components/admin/RentalPanel';
import MinigamesPanel from '@/components/admin/MinigamesPanel';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter, DialogDescription } from '@/components/ui/dialog';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { useTranslation } from '@/lib/translations';
import { useLanguage } from '@/context/LanguageContext';
import { toast } from 'sonner';
import axios from 'axios';
import WalletSettings from '@/components/WalletSettings';
import RevenueAnalytics from '@/components/RevenueAnalytics';
import TreasuryWarning from '@/components/TreasuryWarning';
import AdminDataPanel from '@/components/AdminDataPanel';
import ContractDeployerPanel from '@/components/ContractDeployerPanel';
import SupportManagementTab from '@/components/admin/SupportManagementTab';
import AdminTasksTab from '@/components/admin/AdminTasksTab';
import AdminPromoRally from '@/components/admin/AdminPromoRally';
import AdminReferralsList from '@/components/admin/AdminReferralsList';
import AdminBusinessConfig from '@/components/admin/AdminBusinessConfig';
import AdminRulesSection from '@/components/admin/AdminRulesSection';
import AdminRoadmapSection from '@/components/admin/AdminRoadmapSection';
import { toUserFriendlyAddress } from '@/lib/tonAddress';
import { tonToCity, formatCity } from '@/lib/currency';
import { MAX_PRICE_VALUE, clampPriceValue } from '@/lib/priceLimits';
import { formatErrorDetail, getApiErrorMessage } from '@/lib/apiErrors';

// ── Admin panel loading progress ────────────────────────────────────────────
// The admin dashboard pulls a lot of data on mount. Instead of a blank/black
// screen while everything loads, we show a progress screen that lists each
// dataset and the overall % complete. Keys must match the steps in loadData().
const LOADER_STEP_KEYS = [
  'stats', 'users', 'transactions', 'promos', 'announcements', 'treasury',
  'credits', 'creditSettings', 'tax', 'wallets', 'multiAccounts', 'collateral',
  'seized', 'schedule', 'walletSettings',
];

const LOADER_I18N = {
  en: { title: 'Loading admin panel', subtitle: 'Preparing your data — this takes a few seconds', ready: 'complete', loadedOf: 'Loaded {done} of {total}',
    steps: { stats: 'Statistics', users: 'Users', transactions: 'Transactions', promos: 'Promo codes', announcements: 'Announcements', treasury: 'Treasury', credits: 'Credits', creditSettings: 'Credit settings', tax: 'Taxes', wallets: 'Wallets', multiAccounts: 'Multi-accounts', collateral: 'Collateral', seized: 'Seized assets', schedule: 'Trading schedule', walletSettings: 'Wallet settings' } },
  ru: { title: 'Загрузка панели администратора', subtitle: 'Готовим данные — это займёт несколько секунд', ready: 'готово', loadedOf: 'Загружено {done} из {total}',
    steps: { stats: 'Статистика', users: 'Пользователи', transactions: 'Транзакции', promos: 'Промокоды', announcements: 'Объявления', treasury: 'Казна', credits: 'Кредиты', creditSettings: 'Настройки кредитов', tax: 'Налоги', wallets: 'Кошельки', multiAccounts: 'Мультиаккаунты', collateral: 'Залоги', seized: 'Изъятые активы', schedule: 'Расписание торгов', walletSettings: 'Настройки кошелька' } },
  es: { title: 'Cargando el panel de administración', subtitle: 'Preparando tus datos: tardará unos segundos', ready: 'completado', loadedOf: 'Cargado {done} de {total}',
    steps: { stats: 'Estadísticas', users: 'Usuarios', transactions: 'Transacciones', promos: 'Códigos promo', announcements: 'Anuncios', treasury: 'Tesorería', credits: 'Créditos', creditSettings: 'Ajustes de crédito', tax: 'Impuestos', wallets: 'Billeteras', multiAccounts: 'Multicuentas', collateral: 'Garantías', seized: 'Activos incautados', schedule: 'Horario de trading', walletSettings: 'Ajustes de billetera' } },
  zh: { title: '正在加载管理面板', subtitle: '正在准备数据——需要几秒钟', ready: '完成', loadedOf: '已加载 {done} / {total}',
    steps: { stats: '统计', users: '用户', transactions: '交易', promos: '促销码', announcements: '公告', treasury: '金库', credits: '信贷', creditSettings: '信贷设置', tax: '税收', wallets: '钱包', multiAccounts: '多账户', collateral: '抵押', seized: '已扣押资产', schedule: '交易时间', walletSettings: '钱包设置' } },
  fr: { title: "Chargement du panneau d'administration", subtitle: 'Préparation de vos données — cela prend quelques secondes', ready: 'terminé', loadedOf: 'Chargé {done} sur {total}',
    steps: { stats: 'Statistiques', users: 'Utilisateurs', transactions: 'Transactions', promos: 'Codes promo', announcements: 'Annonces', treasury: 'Trésorerie', credits: 'Crédits', creditSettings: 'Paramètres de crédit', tax: 'Taxes', wallets: 'Portefeuilles', multiAccounts: 'Multicomptes', collateral: 'Garanties', seized: 'Actifs saisis', schedule: 'Horaires de trading', walletSettings: 'Paramètres du portefeuille' } },
  de: { title: 'Admin-Panel wird geladen', subtitle: 'Deine Daten werden vorbereitet — das dauert einige Sekunden', ready: 'geladen', loadedOf: '{done} von {total} geladen',
    steps: { stats: 'Statistiken', users: 'Benutzer', transactions: 'Transaktionen', promos: 'Promo-Codes', announcements: 'Ankündigungen', treasury: 'Schatzkammer', credits: 'Kredite', creditSettings: 'Kredit-Einstellungen', tax: 'Steuern', wallets: 'Wallets', multiAccounts: 'Multi-Konten', collateral: 'Sicherheiten', seized: 'Beschlagnahmte Vermögenswerte', schedule: 'Handelsplan', walletSettings: 'Wallet-Einstellungen' } },
  ja: { title: '管理パネルを読み込み中', subtitle: 'データを準備しています。数秒かかります', ready: '完了', loadedOf: '{total} 件中 {done} 件を読み込み',
    steps: { stats: '統計', users: 'ユーザー', transactions: '取引', promos: 'プロモコード', announcements: 'お知らせ', treasury: '財務', credits: 'クレジット', creditSettings: 'クレジット設定', tax: '税金', wallets: 'ウォレット', multiAccounts: 'マルチアカウント', collateral: '担保', seized: '差し押さえ資産', schedule: '取引スケジュール', walletSettings: 'ウォレット設定' } },
  ko: { title: '관리자 패널 로딩 중', subtitle: '데이터를 준비하는 중입니다. 몇 초 걸립니다', ready: '완료', loadedOf: '{total}개 중 {done}개 로드됨',
    steps: { stats: '통계', users: '사용자', transactions: '거래', promos: '프로모 코드', announcements: '공지', treasury: '재무', credits: '대출', creditSettings: '대출 설정', tax: '세금', wallets: '지갑', multiAccounts: '멀티계정', collateral: '담보', seized: '압류 자산', schedule: '거래 일정', walletSettings: '지갑 설정' } },
  id: { title: 'Memuat panel admin', subtitle: 'Menyiapkan data Anda — perlu beberapa detik', ready: 'selesai', loadedOf: 'Dimuat {done} dari {total}',
    steps: { stats: 'Statistik', users: 'Pengguna', transactions: 'Transaksi', promos: 'Kode promo', announcements: 'Pengumuman', treasury: 'Perbendaharaan', credits: 'Kredit', creditSettings: 'Pengaturan kredit', tax: 'Pajak', wallets: 'Dompet', multiAccounts: 'Multi-akun', collateral: 'Agunan', seized: 'Aset disita', schedule: 'Jadwal perdagangan', walletSettings: 'Pengaturan dompet' } },
};


const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const MSK_OFFSET_MIN = 180; // MSK = UTC+3

// Convert a datetime-local string (interpreted as MSK wall-clock) to UTC ISO.
const mskLocalToUtcIso = (localStr) => {
  if (!localStr) return null;
  const [datePart, timePart] = localStr.split('T');
  if (!datePart || !timePart) return null;
  const [y, m, d] = datePart.split('-').map(Number);
  const [hh, mm] = timePart.split(':').map(Number);
  const utcMs = Date.UTC(y, m - 1, d, hh, mm) - MSK_OFFSET_MIN * 60 * 1000;
  return new Date(utcMs).toISOString();
};

// Convert a UTC ISO string to a datetime-local string in MSK wall-clock.
const utcIsoToMskLocal = (iso) => {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '';
  const msk = new Date(d.getTime() + MSK_OFFSET_MIN * 60 * 1000);
  const p = (n) => String(n).padStart(2, '0');
  return `${msk.getUTCFullYear()}-${p(msk.getUTCMonth() + 1)}-${p(msk.getUTCDate())}T${p(msk.getUTCHours())}:${p(msk.getUTCMinutes())}`;
};

const ZONE_LABELS = { core: 'Ядро', center: 'Центр', middle: 'Средняя', outer: 'Окраина' };

export default function AdminPage({ user }) {
  const navigate = useNavigate();
  const wallet = useTonWallet();
  const { language: lang } = useLanguage();
  const { t } = useTranslation(lang);
  
  const [stats, setStats] = useState(null);
  const [treasuryHealth, setTreasuryHealth] = useState(null);
  const [users, setUsers] = useState([]);
  const [usersTotal, setUsersTotal] = useState(0);
  const [usersQuery, setUsersQuery] = useState('');
  const [usersLoading, setUsersLoading] = useState(false);
  // users are loaded 50 at a time (server-side search over the whole base)
  const loadUsers = useCallback(async (skip = 0, q = usersQuery) => {
    setUsersLoading(true);
    try {
      const token = localStorage.getItem('token') || localStorage.getItem('ton_city_token');
      const r = await axios.get(`${API}/admin/users`, { params: { skip, limit: 50, q }, headers: { Authorization: `Bearer ${token}` } });
      setUsers((prev) => (skip ? [...prev, ...(r.data.users || [])] : (r.data.users || [])));
      setUsersTotal(r.data.total || 0);
    } catch (e) { toast.error('Не удалось загрузить пользователей'); }
    finally { setUsersLoading(false); }
  }, [usersQuery]); // eslint-disable-line react-hooks/exhaustive-deps
  const [transactions, setTransactions] = useState([]);
  const [selectedTxIds, setSelectedTxIds] = useState(new Set());
  const [exportingCsv, setExportingCsv] = useState(false);
  const [promos, setPromos] = useState([]);
  const [announcements, setAnnouncements] = useState([]);
  const [announcementsTotal, setAnnouncementsTotal] = useState(0);      // total count on server
  const [announcementsAll, setAnnouncementsAll] = useState([]);          // full list (loaded on demand)
  const [announcementsExpanded, setAnnouncementsExpanded] = useState(false);
  const [announcementsLoadingAll, setAnnouncementsLoadingAll] = useState(false);
  // while a broadcast is running, refresh its delivery counters every 2 s
  useEffect(() => {
    const running = (announcementsExpanded ? announcementsAll : announcements).some((a) => a.delivery && a.delivery.status === 'running');
    if (!running) return undefined;
    const id = setInterval(async () => {
      try {
        const token = localStorage.getItem('token') || localStorage.getItem('ton_city_token');
        const r = await axios.get(`${API}/admin/announcements`, { params: { limit: announcementsExpanded ? 50 : 1 }, headers: { Authorization: `Bearer ${token}` } });
        if (announcementsExpanded) setAnnouncementsAll(r.data.announcements || []); else setAnnouncements(r.data.announcements || []);
      } catch (e) { /* ignore */ }
    }, 2000);
    return () => clearInterval(id);
  }, [announcements, announcementsAll, announcementsExpanded]); // eslint-disable-line react-hooks/exhaustive-deps
  const [isLoading, setIsLoading] = useState(true);
  const [seizing, setSeizing] = useState(false);
  const [loadSteps, setLoadSteps] = useState([]);  // admin-panel load progress
  const [isAdmin, setIsAdmin] = useState(false);
  
  // Maintenance states
  const [maintenanceEnabled, setMaintenanceEnabled] = useState(false);
  const [showMaintenanceDialog, setShowMaintenanceDialog] = useState(false);
  const [scheduledTime, setScheduledTime] = useState('');
  const [email2faForceAll, setEmail2faForceAll] = useState(false);
  const [savingEmail2fa, setSavingEmail2fa] = useState(false);
  
  // Form states
  const [promoName, setPromoName] = useState('');
  const [promoAmount, setPromoAmount] = useState('');
  const [promoMaxUses, setPromoMaxUses] = useState('');
  const [promoCode, setPromoCode] = useState('');
  const [announcementTitle, setAnnouncementTitle] = useState('');
  const [announcementMessage, setAnnouncementMessage] = useState('');
  const [announcementImageUrl, setAnnouncementImageUrl] = useState('');
  const [announcementButtons, setAnnouncementButtons] = useState([]);  // [{text, url}]
  const [announcementUploading, setAnnouncementUploading] = useState(false);
  // Announcement scheduling
  const [announcementMode, setAnnouncementMode] = useState('now'); // 'now' | 'scheduled'
  const [announcementScheduledAt, setAnnouncementScheduledAt] = useState(''); // MSK datetime-local
  // Multi-language broadcast state — when true, admin fills a variant per selected
  // language and each user receives the variant matching their profile/bot language.
  const [announcementMulti, setAnnouncementMulti] = useState(false);
  const [announcementLangs, setAnnouncementLangs] = useState([]); // ["ru","gb",...]
  const [announcementLangIdx, setAnnouncementLangIdx] = useState(0);
  // translations: { [langCode]: { title, message, image_url, buttons: [] } }
  const [announcementTranslations, setAnnouncementTranslations] = useState({});
  // Per-zone trading schedule (datetime-local strings in MSK)
  const [tradingSchedule, setTradingSchedule] = useState({ core: '', center: '', middle: '', outer: '' });
  const [savingSchedule, setSavingSchedule] = useState(false);
  
  // Credit admin states
  const [credits, setCredits] = useState([]);
  const [collateralList, setCollateralList] = useState([]);
  const [seizedList, setSeizedList] = useState([]);
  const [multiAccounts, setMultiAccounts] = useState(null);
  const [maCleanupBusy, setMaCleanupBusy] = useState(false);

  const reloadMultiAccounts = async () => {
    try {
      const token = localStorage.getItem('token') || localStorage.getItem('ton_city_token');
      const headers = { Authorization: `Bearer ${token}` };
      const r = await axios.get(`${API}/admin/multi-accounts`, { headers });
      setMultiAccounts(r.data);
    } catch (e) { /* silent */ }
  };

  const cleanupMultiAccounts = async (payload, confirmMsg) => {
    if (confirmMsg && !window.confirm(confirmMsg)) return;
    setMaCleanupBusy(true);
    try {
      const token = localStorage.getItem('token') || localStorage.getItem('ton_city_token');
      const headers = { Authorization: `Bearer ${token}` };
      const r = await axios.post(`${API}/admin/multi-accounts/cleanup`, payload, { headers });
      toast.success(`Удалено: ${r.data.deleted}`);
      await reloadMultiAccounts();
    } catch (e) {
      toast.error(getApiErrorMessage(e) || e.message || 'Ошибка очистки');
    } finally {
      setMaCleanupBusy(false);
    }
  };

  const [creditSettings, setCreditSettings] = useState({ government_interest_rate: 0.15 });
  const [govRate, setGovRate] = useState('15');
  
  // Withdrawal selection states
  const [selectedWithdrawals, setSelectedWithdrawals] = useState(new Set());
  const [selectAllWithdrawals, setSelectAllWithdrawals] = useState(false);
  
  // Admin wallet settings
  const [walletConfigs, setWalletConfigs] = useState([]);
  const [newWallet, setNewWallet] = useState({ address: '', percentage: 100, mnemonic: '' });
  const [showWalletModal, setShowWalletModal] = useState(false);
  
  // Tax settings
  const [taxSettings, setTaxSettings] = useState({
    small_business_tax: 5,
    medium_business_tax: 8,
    large_business_tax: 10,
    land_business_sale_tax: 10
  });
  
  // User details
  const [userDetailId, setUserDetailId] = useState('');
  const [userDetail, setUserDetail] = useState(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  
  // Transaction search and filtering
  const [txSearchId, setTxSearchId] = useState('');
  const [txSearchResult, setTxSearchResult] = useState(null);
  const [txFilter, setTxFilter] = useState('all');
  const [loadingTxSearch, setLoadingTxSearch] = useState(false);
  // Transactions infinite scroll (50 per page) + per-user search
  const TX_PAGE = 50;
  const [txTotal, setTxTotal] = useState(0);
  const [txHasMore, setTxHasMore] = useState(true);
  const [txLoadingMore, setTxLoadingMore] = useState(false);
  const [txUserSearchInput, setTxUserSearchInput] = useState('');
  const [txUserSearch, setTxUserSearch] = useState('');   // committed user search term
  // Per-user transactions modal
  const [userTxModalOpen, setUserTxModalOpen] = useState(false);
  const [userTxTarget, setUserTxTarget] = useState(null);
  const [userTxList, setUserTxList] = useState([]);
  const [userTxTotal, setUserTxTotal] = useState(0);
  const [userTxHasMore, setUserTxHasMore] = useState(true);
  const [userTxLoading, setUserTxLoading] = useState(false);
  
  // Telegram bot
  const [telegramBotToken, setTelegramBotToken] = useState('');
  const [telegramBotUsername, setTelegramBotUsername] = useState('');
  const [adminTelegramId, setAdminTelegramId] = useState('');
  const [telegramChannel, setTelegramChannel] = useState('');
  const [savingChannel, setSavingChannel] = useState(false);
  const [telegramAppUrl, setTelegramAppUrl] = useState('');
  const [savingAppUrl, setSavingAppUrl] = useState(false);
  const [settingWebhook, setSettingWebhook] = useState(false);
  
  // Wallet settings
  const [senderMnemonic, setSenderMnemonic] = useState('');
  const [senderWalletAddress, setSenderWalletAddress] = useState('');
  const [depositAddress, setDepositAddress] = useState('');
  
  const token = localStorage.getItem('ton_city_token') || localStorage.getItem('token');

  // S5 + UX: silent redirect — fire immediately before any UI is shown.
  // If user is not admin, navigate away synchronously so no spinner/error flashes.
  useEffect(() => {
    if (!token) {
      navigate('/', { replace: true });
      return;
    }
    // If we already have `user` prop from App.js, decide instantly without API call
    if (user && typeof user.is_admin !== 'undefined' && !user.is_admin) {
      navigate('/', { replace: true });
      return;
    }
    checkAdmin();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  // Load a page of project-wide transactions (50 at a time). `reset` starts
  // from the top (used on first load / language change / user-search change);
  // otherwise it appends the next page for infinite scroll.
  const loadTransactions = useCallback(async (reset = false) => {
    if (!isAdmin || !token) return;
    if (txLoadingMore) return;
    setTxLoadingMore(true);
    try {
      const headers = { Authorization: `Bearer ${token}` };
      const skip = reset ? 0 : transactions.length;
      const params = new URLSearchParams({ skip: String(skip), limit: String(TX_PAGE), lang: 'ru' });
      if (txUserSearch) params.set('search', txUserSearch);
      const res = await axios.get(`${API}/admin/transactions?${params.toString()}`, { headers });
      const batch = res.data.transactions || [];
      const total = res.data.total || 0;
      setTxTotal(total);
      setTransactions((prev) => {
        const merged = reset ? batch : [...prev, ...batch];
        setTxHasMore(batch.length === TX_PAGE && merged.length < total);
        return merged;
      });
    } catch (e) { /* noop */ }
    finally { setTxLoadingMore(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAdmin, token, transactions.length, txUserSearch, txLoadingMore]);

  // (Re)load the transactions list from the top whenever the admin becomes
  // available, the language changes, or the per-user search term changes.
  useEffect(() => {
    if (!isAdmin || !token) return;
    loadTransactions(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lang, txUserSearch, isAdmin]);

  const onTxScroll = (e) => {
    const el = e.currentTarget;
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 140 && txHasMore && !txLoadingMore) {
      loadTransactions(false);
    }
  };

  // Per-user transactions modal loaders (also 50 per page, infinite scroll).
  const loadUserTx = useCallback(async (target, reset = false, currentLen = 0) => {
    if (!token || !target) return;
    setUserTxLoading(true);
    try {
      const headers = { Authorization: `Bearer ${token}` };
      const ref = target.id || target.wallet_address || target.username || target.email;
      const skip = reset ? 0 : currentLen;
      const params = new URLSearchParams({ skip: String(skip), limit: String(TX_PAGE), lang: 'ru', search: String(ref) });
      const res = await axios.get(`${API}/admin/transactions?${params.toString()}`, { headers });
      const batch = res.data.transactions || [];
      const total = res.data.total || 0;
      setUserTxTotal(total);
      setUserTxList((prev) => {
        const merged = reset ? batch : [...prev, ...batch];
        setUserTxHasMore(batch.length === TX_PAGE && merged.length < total);
        return merged;
      });
    } catch (e) { /* noop */ }
    finally { setUserTxLoading(false); }
  }, [token]);

  const openUserTx = (target) => {
    setUserTxTarget(target);
    setUserTxList([]);
    setUserTxTotal(0);
    setUserTxHasMore(true);
    setUserTxModalOpen(true);
    loadUserTx(target, true, 0);
  };

  const onUserTxScroll = (e) => {
    const el = e.currentTarget;
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 140 && userTxHasMore && !userTxLoading) {
      loadUserTx(userTxTarget, false, userTxList.length);
    }
  };


  // Auto-refresh active-users / stats once per minute (lightweight — stats only)
  useEffect(() => {
    if (!isAdmin || !token) return;
    const headers = { Authorization: `Bearer ${token}` };
    const refreshStats = () => {
      axios.get(`${API}/admin/stats`, { headers })
        .then(res => setStats(res.data))
        .catch(() => {});
    };
    const intervalId = setInterval(refreshStats, 60000); // 60s = 1 minute
    return () => clearInterval(intervalId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAdmin, token]);

  const runSeize = async () => {
    if (seizing) return;
    if (!window.confirm(lang === 'ru'
      ? 'Изъять бизнесы у всех неактивных пользователей и выставить на Маркетплейс?'
      : 'Seize businesses of all inactive users and list them on the Marketplace?')) return;
    setSeizing(true);
    try {
      const headers = { Authorization: `Bearer ${token}` };
      const res = await axios.post(`${API}/admin/inactivity/seize`, {}, { headers });
      const d = res.data || {};
      toast.success((lang === 'ru' ? 'Изъятие выполнено: ' : 'Seizure done: ')
        + `zero=${d.seized_zero || 0}, 1+=${d.seized_regular || 0}`);
      const s = await axios.get(`${API}/admin/stats`, { headers });
      setStats(s.data);
    } catch (e) {
      toast.error(getApiErrorMessage(e) || 'Error');
    } finally {
      setSeizing(false);
    }
  };

  const checkAdmin = async () => {
    try {
      const response = await axios.get(`${API}/auth/me`, {
        headers: { Authorization: `Bearer ${token}` }
      });

      if (!response.data.is_admin) {
        // Silent redirect — no toast, no alert
        navigate('/', { replace: true });
        return;
      }

      setIsAdmin(true);
      loadData();
      loadMaintenanceStatus();
    } catch (error) {
      // Silent redirect even on error
      navigate('/', { replace: true });
    }
  };

  const loadMaintenanceStatus = async () => {
    try {
      const response = await axios.get(`${API}/admin/maintenance`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setMaintenanceEnabled(response.data.enabled || false);
    } catch (error) {
      console.error('Failed to load maintenance status:', error);
    }
    try {
      const r = await axios.get(`${API}/admin/settings/email-2fa`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setEmail2faForceAll(Boolean(r.data?.force_all));
    } catch (e) {
      console.error('Failed to load email-2fa setting:', e);
    }
  };

  const toggleEmail2faForceAll = async () => {
    const next = !email2faForceAll;
    setSavingEmail2fa(true);
    try {
      await axios.post(`${API}/admin/settings/email-2fa`, { force_all: next }, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setEmail2faForceAll(next);
      toast.success(next
        ? 'Email-2FA включена для всех пользователей'
        : 'Email-2FA отключена');
    } catch (e) {
      console.error('Failed to toggle email-2fa:', e);
      toast.error('Не удалось изменить настройку');
    } finally {
      setSavingEmail2fa(false);
    }
  };

  const toggleMaintenance = async (startNow = false, scheduledAt = null) => {
    try {
      const newState = !maintenanceEnabled;
      await axios.post(`${API}/admin/maintenance`, {
        enabled: newState,
        scheduled_at: startNow ? null : scheduledAt
      }, {
        headers: { Authorization: `Bearer ${token}` }
      });
      
      setMaintenanceEnabled(newState);
      setShowMaintenanceDialog(false);
      
      if (newState) {
        toast.success(startNow ? 'Технические работы начаты' : 'Технические работы запланированы');
      } else {
        toast.success('Технические работы завершены');
      }
    } catch (error) {
      console.error('Failed to toggle maintenance:', error);
      toast.error('Ошибка при изменении статуса');
    }
  };

  const loadData = async () => {
    setIsLoading(true);
    const headers = { Authorization: `Bearer ${token}` };
    // Initialize every step as pending so the loader lists them immediately.
    setLoadSteps(LOADER_STEP_KEYS.map((k) => ({ key: k, status: 'pending' })));

    const mark = (key, status) =>
      setLoadSteps((prev) => prev.map((s) => (s.key === key ? { ...s, status } : s)));

    // Run one dataset: flip to loading, fetch, apply, then mark done/error.
    // Every step settles independently so the % updates as data arrives.
    const step = async (key, run, apply) => {
      mark(key, 'loading');
      try {
        const res = await run();
        try { if (apply) apply(res); } catch (_) { /* apply errors shouldn't fail the step */ }
        mark(key, 'done');
      } catch (e) {
        mark(key, 'error');
      }
    };

    await Promise.allSettled([
      step('stats', () => axios.get(`${API}/admin/stats`, { headers }), (r) => setStats(r.data)),
      step('users', () => axios.get(`${API}/admin/users`, { params: { limit: 50 }, headers }), (r) => { setUsers(r.data.users || []); setUsersTotal(r.data.total || 0); }),
      step('transactions', () => axios.get(`${API}/admin/transactions?limit=${TX_PAGE}&lang=ru`, { headers }), (r) => { setTransactions(r.data.transactions || []); setTxTotal(r.data.total || 0); setTxHasMore((r.data.transactions || []).length === TX_PAGE && (r.data.transactions || []).length < (r.data.total || 0)); }),
      step('promos', () => axios.get(`${API}/admin/promos`, { headers }), (r) => setPromos(r.data.promos || [])),
      step('announcements', () => axios.get(`${API}/admin/announcements?limit=1`, { headers }), (r) => {
        setAnnouncements(r.data.announcements || []);
        setAnnouncementsTotal(r.data.total ?? (r.data.announcements || []).length);
        setAnnouncementsExpanded(false);
        setAnnouncementsAll([]);
      }),
      step('treasury', () => axios.get(`${API}/admin/treasury-health`, { headers }), (r) => setTreasuryHealth(r.data)),
      step('credits', () => axios.get(`${API}/admin/credits`, { headers }), (r) => setCredits(r.data.credits || [])),
      step('creditSettings', () => axios.get(`${API}/admin/credit-settings`, { headers }), (r) => {
        if (r.data) { setCreditSettings(r.data); setGovRate(((r.data.government_interest_rate || 0.15) * 100).toFixed(0)); }
      }),
      step('tax', () => axios.get(`${API}/admin/settings/tax`, { headers }), (r) => { if (r.data) setTaxSettings(r.data); }),
      step('wallets', () => axios.get(`${API}/admin/wallets`, { headers }), (r) => { if (r.data) setWalletConfigs(r.data.wallets || []); }),
      step('multiAccounts', () => axios.get(`${API}/admin/multi-accounts`, { headers }), (r) => setMultiAccounts(r.data)),
      step('collateral', () => axios.get(`${API}/admin/credits/collateral`, { headers }), (r) => setCollateralList(r.data.collateral || [])),
      step('seized', () => axios.get(`${API}/admin/credits/seized`, { headers }), (r) => setSeizedList(r.data.seized || [])),
      step('schedule', () => axios.get(`${API}/trading-schedule`), (r) => {
        const z = r.data?.zones || {};
        setTradingSchedule({
          core: utcIsoToMskLocal(z.core), center: utcIsoToMskLocal(z.center),
          middle: utcIsoToMskLocal(z.middle), outer: utcIsoToMskLocal(z.outer),
        });
      }),
      step('walletSettings', () => loadWalletSettings(), null),
    ]);

    setIsLoading(false);
  };

  const approveWithdrawal = async (txId) => {
    try {
      await axios.post(`${API}/admin/withdrawal/approve/${txId}`, {}, {
        headers: { Authorization: `Bearer ${token}` }
      });
      toast.success('Вывод одобрен и отправлен');
      // Remove from list - update transactions state
      setTransactions(prev => prev.filter(tx => tx.id !== txId));
      setSelectedWithdrawals(prev => {
        const newSet = new Set(prev);
        newSet.delete(txId);
        return newSet;
      });
    } catch (error) {
      const msg = getApiErrorMessage(error) || 'Ошибка при одобрении заявки';
      toast.error(msg);
    }
  };

  const rejectWithdrawal = async (txId) => {
    try {
      await axios.post(`${API}/admin/withdrawal/reject/${txId}`, {}, {
        headers: { Authorization: `Bearer ${token}` }
      });
      toast.success('Вывод отклонён, средства возвращены');
      // Remove from list - update transactions state
      setTransactions(prev => prev.filter(tx => tx.id !== txId));
      setSelectedWithdrawals(prev => {
        const newSet = new Set(prev);
        newSet.delete(txId);
        return newSet;
      });
    } catch (error) {
      const msg = getApiErrorMessage(error) || 'Ошибка при отклонении заявки';
      toast.error(msg);
    }
  };

  // Bulk withdrawal actions
  const handleSelectAllWithdrawals = (checked) => {
    setSelectAllWithdrawals(checked);
    if (checked) {
      setSelectedWithdrawals(new Set(pendingWithdrawals.map(tx => tx.id)));
    } else {
      setSelectedWithdrawals(new Set());
    }
  };

  const toggleWithdrawalSelection = (txId) => {
    setSelectedWithdrawals(prev => {
      const newSet = new Set(prev);
      if (newSet.has(txId)) {
        newSet.delete(txId);
      } else {
        newSet.add(txId);
      }
      return newSet;
    });
  };

  const bulkApproveWithdrawals = async () => {
    if (selectedWithdrawals.size === 0) {
      toast.error('Выберите заявки для одобрения');
      return;
    }

    // Admin 2FA gate: dangerous batch action — back-end /withdrawal/approve
    // and /reject endpoints are protected by get_current_admin_with_2fa,
    // which expects the TOTP code in the X-Admin-TOTP header. Without it
    // every single call returns 401 → user sees "Ошибок: N". Prompt once.
    let adminTotp = '';
    try {
      const me = await axios.get(`${API}/auth/me`, { headers: { Authorization: `Bearer ${token}` } }).then(r => r.data).catch(() => null);
      if (me?.is_2fa_enabled) {
        adminTotp = (window.prompt('Введите 6-значный код 2FA администратора') || '').trim();
        if (!adminTotp) { toast.error('Действие отменено'); return; }
      }
    } catch (_) { /* fall through; backend will reject if needed */ }

    let success = 0;
    let failed = 0;

    for (const txId of selectedWithdrawals) {
      try {
        await axios.post(`${API}/admin/withdrawal/approve/${txId}`, {}, {
          headers: {
            Authorization: `Bearer ${token}`,
            ...(adminTotp ? { 'X-Admin-TOTP': adminTotp } : {}),
          }
        });
        success++;
      } catch {
        failed++;
      }
    }

    toast.success(`Одобрено: ${success}, Ошибок: ${failed}`);
    setSelectedWithdrawals(new Set());
    setSelectAllWithdrawals(false);
    loadData();
  };

  const bulkRejectWithdrawals = async () => {
    if (selectedWithdrawals.size === 0) {
      toast.error('Выберите заявки для отклонения');
      return;
    }

    let adminTotp = '';
    try {
      const me = await axios.get(`${API}/auth/me`, { headers: { Authorization: `Bearer ${token}` } }).then(r => r.data).catch(() => null);
      if (me?.is_2fa_enabled) {
        adminTotp = (window.prompt('Введите 6-значный код 2FA администратора') || '').trim();
        if (!adminTotp) { toast.error('Действие отменено'); return; }
      }
    } catch (_) { /* noop */ }

    let success = 0;
    let failed = 0;

    for (const txId of selectedWithdrawals) {
      try {
        await axios.post(`${API}/admin/withdrawal/reject/${txId}`, {}, {
          headers: {
            Authorization: `Bearer ${token}`,
            ...(adminTotp ? { 'X-Admin-TOTP': adminTotp } : {}),
          }
        });
        success++;
      } catch {
        failed++;
      }
    }

    toast.success(`Отклонено и возвращено: ${success}, Ошибок: ${failed}`);
    setSelectedWithdrawals(new Set());
    setSelectAllWithdrawals(false);
    loadData();
  };

  // Tax settings
  const saveTaxSettings = async () => {
    try {
      await axios.post(`${API}/admin/settings/tax`, taxSettings, {
        headers: { Authorization: `Bearer ${token}` }
      });
      toast.success('Налоговые настройки сохранены');
    } catch (error) {
      toast.error('Ошибка сохранения налогов');
    }
  };

  // User resource update
  const updateUserResources = async (userId, resources) => {
    try {
      await axios.post(`${API}/admin/users/${userId}/resources`, { resources }, {
        headers: { Authorization: `Bearer ${token}` }
      });
      toast.success('Ресурсы пользователя обновлены');
    } catch (error) {
      toast.error('Ошибка обновления ресурсов');
    }
  };

  const createPromo = async () => {
    try {
      await axios.post(`${API}/admin/promo/create`, null, {
        params: { name: promoName, amount: parseFloat(promoAmount), max_uses: parseInt(promoMaxUses) },
        headers: { Authorization: `Bearer ${token}` }
      });
      toast.success('Promo created');
      setPromoName('');
      setPromoAmount('');
      setPromoMaxUses('');
      loadData();
    } catch (error) {
      toast.error('Failed to create promo');
    }
  };

  // Supported broadcast languages (aliases per user requirement).
  const BROADCAST_LANGS = [
    { code: 'gb', label: '🇬🇧 English' },
    { code: 'ru', label: '🇷🇺 Русский' },
    { code: 'es', label: '🇪🇸 Español' },
    { code: 'cn', label: '🇨🇳 中文' },
    { code: 'fr', label: '🇫🇷 Français' },
    { code: 'de', label: '🇩🇪 Deutsch' },
    { code: 'jp', label: '🇯🇵 日本語' },
    { code: 'kr', label: '🇰🇷 한국어' },
    { code: 'id', label: '🇮🇩 Indonesia' },
  ];

  const getTranslation = (lang) => announcementTranslations[lang] || { title: '', message: '', image_url: '', buttons: [], _uploading: false };

  const setTranslationField = (lang, field, value) => {
    setAnnouncementTranslations((prev) => ({
      ...prev,
      [lang]: { ...(prev[lang] || { title: '', message: '', image_url: '', buttons: [] }), [field]: value },
    }));
  };

  const uploadAnnouncementImageForLang = async (lang, file) => {
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) {
      toast.error('Изображение должно быть ≤ 2 МБ');
      return;
    }
    setTranslationField(lang, '_uploading', true);
    try {
      const fd = new FormData();
      fd.append('file', file);
      const res = await axios.post(`${API}/admin/announcement/upload-image`, fd, {
        headers: { Authorization: `Bearer ${token}` },
      });
      setTranslationField(lang, 'image_url', res.data?.url || '');
      toast.success('Изображение загружено');
    } catch (e) {
      toast.error('Не удалось загрузить: ' + (getApiErrorMessage(e) || e.message));
    } finally {
      setTranslationField(lang, '_uploading', false);
    }
  };

  const resetAnnouncementForm = () => {
    setAnnouncementTitle('');
    setAnnouncementMessage('');
    setAnnouncementImageUrl('');
    setAnnouncementButtons([]);
    setAnnouncementMode('now');
    setAnnouncementScheduledAt('');
    setAnnouncementMulti(false);
    setAnnouncementLangs([]);
    setAnnouncementLangIdx(0);
    setAnnouncementTranslations({});
  };

  const createAnnouncement = async () => {
    let scheduledAtIso = null;
    if (announcementMode === 'scheduled') {
      if (!announcementScheduledAt) {
        toast.error('Укажите дату и время публикации (МСК)');
        return;
      }
      scheduledAtIso = mskLocalToUtcIso(announcementScheduledAt);
      if (!scheduledAtIso || new Date(scheduledAtIso) <= new Date()) {
        toast.error('Дата публикации должна быть в будущем');
        return;
      }
    }

    // Multi-language broadcast branch
    if (announcementMulti) {
      if (!announcementLangs.length) {
        toast.error('Выберите хотя бы один язык рассылки');
        return;
      }
      const translations = {};
      for (const code of announcementLangs) {
        const tr = getTranslation(code);
        const msg = (tr.message || '').trim();
        if (!msg) {
          toast.error(`Заполните сообщение для языка ${code.toUpperCase()}`);
          setAnnouncementLangIdx(announcementLangs.indexOf(code));
          return;
        }
        translations[code] = {
          title: (tr.title || '').trim(),
          message: msg,
          image_url: (tr.image_url || '').trim() || null,
          buttons: (tr.buttons || []).filter((b) => (b?.text || '').trim() && (b?.url || '').trim()),
        };
      }
      try {
        // Backend requires top-level `message` — populate from the first variant.
        const firstCode = announcementLangs[0];
        const firstTr = translations[firstCode];
        await axios.post(`${API}/admin/announcement`,
          {
            title: firstTr.title || '',
            message: firstTr.message,
            lang: 'multi',
            image_url: firstTr.image_url || null,
            buttons: firstTr.buttons || [],
            translations,
            scheduled_at: scheduledAtIso,
          },
          { headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' } });
        toast.success(scheduledAtIso
          ? `Запланировано ${announcementLangs.length} публикаций`
          : `Опубликовано ${announcementLangs.length} постов`);
        resetAnnouncementForm();
        refreshAnnouncements();
      } catch (error) {
        toast.error('Не удалось опубликовать: ' + (formatErrorDetail(error?.response?.data?.detail) || error.message));
      }
      return;
    }

    // Single-language broadcast (legacy path)
    if (!announcementMessage.trim()) {
      toast.error('Заполните сообщение');
      return;
    }
    try {
      // Strip empty button rows so backend doesn't get blank entries.
      const cleanButtons = (announcementButtons || []).filter(b => (b?.text || '').trim() && (b?.url || '').trim());
      await axios.post(`${API}/admin/announcement`,
        {
          title: (announcementTitle || '').trim(),
          message: announcementMessage.trim(),
          lang: 'all',
          image_url: (announcementImageUrl || '').trim() || null,
          buttons: cleanButtons,
          scheduled_at: scheduledAtIso,
        },
        { headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' } });
      toast.success(scheduledAtIso ? 'Объявление запланировано' : 'Объявление опубликовано');
      resetAnnouncementForm();
      refreshAnnouncements();
    } catch (error) {
      toast.error('Не удалось опубликовать: ' + (formatErrorDetail(error?.response?.data?.detail) || error.message));
    }
  };

  // Refresh ONLY the announcements slice (keeps the admin on the current tab and
  // avoids re-running the full-screen loader). Re-pulls the expanded list too if open.
  const refreshAnnouncements = async () => {
    const headers = { Authorization: `Bearer ${token}` };
    try {
      const latest = await axios.get(`${API}/admin/announcements?limit=1`, { headers });
      setAnnouncements(latest.data.announcements || []);
      setAnnouncementsTotal(latest.data.total ?? (latest.data.announcements || []).length);
      if (announcementsExpanded) {
        const all = await axios.get(`${API}/admin/announcements?limit=100`, { headers });
        setAnnouncementsAll(all.data.announcements || []);
      }
    } catch (_) { /* non-fatal */ }
  };

  const deleteAnnouncement = async (id) => {
    try {
      await axios.delete(`${API}/admin/announcement/${id}`, { headers: { Authorization: `Bearer ${token}` } });
      toast.success('Объявление удалено');
      refreshAnnouncements();
    } catch (error) {
      toast.error('Не удалось удалить: ' + (formatErrorDetail(error?.response?.data?.detail) || error.message));
    }
  };

  // Lazy-load the FULL announcement list only when the admin taps "Показать все".
  // The panel initially loads just the latest one to stay fast.
  const loadAllAnnouncements = async () => {
    setAnnouncementsLoadingAll(true);
    try {
      const r = await axios.get(`${API}/admin/announcements?limit=100`, { headers: { Authorization: `Bearer ${token}` } });
      setAnnouncementsAll(r.data.announcements || []);
      setAnnouncementsTotal(r.data.total ?? (r.data.announcements || []).length);
      setAnnouncementsExpanded(true);
    } catch (error) {
      toast.error('Не удалось загрузить объявления');
    } finally {
      setAnnouncementsLoadingAll(false);
    }
  };

  const saveTradingSchedule = async () => {
    setSavingSchedule(true);
    try {
      const zones = {
        core: mskLocalToUtcIso(tradingSchedule.core),
        center: mskLocalToUtcIso(tradingSchedule.center),
        middle: mskLocalToUtcIso(tradingSchedule.middle),
        outer: mskLocalToUtcIso(tradingSchedule.outer),
      };
      await axios.post(`${API}/admin/trading-schedule`, { zones },
        { headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' } });
      toast.success('Расписание торгов сохранено');
    } catch (error) {
      toast.error('Не удалось сохранить: ' + (formatErrorDetail(error?.response?.data?.detail) || error.message));
    } finally {
      setSavingSchedule(false);
    }
  };

  const uploadAnnouncementImage = async (file) => {
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) {
      toast.error('Изображение должно быть ≤ 2 МБ');
      return;
    }
    setAnnouncementUploading(true);
    try {
      const fd = new FormData();
      fd.append('file', file);
      const res = await axios.post(`${API}/admin/announcement/upload-image`, fd, {
        headers: { Authorization: `Bearer ${token}` },
      });
      setAnnouncementImageUrl(res.data?.url || '');
      toast.success('Изображение загружено');
    } catch (e) {
      toast.error('Не удалось загрузить: ' + (getApiErrorMessage(e) || e.message));
    } finally {
      setAnnouncementUploading(false);
    }
  };

  const setUserAdmin = async (walletAddress, isAdminStatus) => {
    try {
      await axios.post(`${API}/admin/user/set-admin/${walletAddress}`, null, {
        params: { is_admin: isAdminStatus },
        headers: { Authorization: `Bearer ${token}` }
      });
      toast.success(`Admin status ${isAdminStatus ? 'granted' : 'revoked'}`);
      loadData();
    } catch (error) {
      toast.error('Failed to update admin status');
    }
  };

  // Credit admin actions
  const handleUpdateGovRate = async () => {
    try {
      const rate = parseFloat(govRate) / 100;
      await axios.post(`${API}/admin/credit-settings?government_interest_rate=${rate}`, {}, {
        headers: { Authorization: `Bearer ${token}` }
      });
      toast.success(`Ставка обновлена: ${govRate}%`);
      loadData();
    } catch (e) { toast.error('Ошибка обновления'); }
  };

  const handleCreatePromo = async () => {
    if (!promoName || !promoAmount) {
      toast.error('Заполните название и сумму');
      return;
    }
    try {
      await axios.post(`${API}/admin/promo/create`, {
        name: promoName,
        code: promoCode || promoName.toUpperCase().replace(/\s/g, ''),
        amount: parseFloat(promoAmount),
        max_uses: parseInt(promoMaxUses) || 100,
      }, { headers: { Authorization: `Bearer ${token}` } });
      toast.success('Промокод создан');
      setPromoName('');
      setPromoAmount('');
      setPromoMaxUses('');
      setPromoCode('');
      loadData();
    } catch (e) { toast.error(getApiErrorMessage(e) || 'Ошибка'); }
  };

  const handleDeletePromo = async (promoId) => {
    if (!window.confirm('Удалить этот промокод?')) return;
    try {
      await axios.delete(`${API}/admin/promo/${promoId}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      toast.success('Промокод удалён');
      setPromos(promos.filter(p => p.id !== promoId));
    } catch (e) { toast.error(getApiErrorMessage(e) || 'Ошибка удаления'); }
  };

  const handleLoadUserDetail = async () => {
    if (!userDetailId.trim()) return;
    setLoadingDetail(true);
    setUserDetail(null);
    try {
      const res = await axios.get(`${API}/admin/user-details/${encodeURIComponent(userDetailId.trim())}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setUserDetail(res.data);
    } catch (e) { toast.error(getApiErrorMessage(e) || 'Пользователь не найден'); }
    finally { setLoadingDetail(false); }
  };
  
  // Search transaction by ID
  const handleSearchTransaction = async () => {
    if (!txSearchId.trim()) return;
    setLoadingTxSearch(true);
    setTxSearchResult(null);
    try {
      const res = await axios.get(`${API}/admin/transaction/${encodeURIComponent(txSearchId.trim())}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setTxSearchResult(res.data);
    } catch (e) { 
      toast.error(getApiErrorMessage(e) || 'Операция не найдена'); 
    }
    finally { setLoadingTxSearch(false); }
  };
  
  // Block/unblock user
  const handleBlockUser = async (userId, reason) => {
    try {
      await axios.post(`${API}/admin/user/${userId}/block`, { reason }, {
        headers: { Authorization: `Bearer ${token}` }
      });
      toast.success('Пользователь заблокирован');
      if (userDetail?.id === userId) {
        handleLoadUserDetail();
      }
    } catch (e) { toast.error(getApiErrorMessage(e) || 'Ошибка блокировки'); }
  };
  
  const handleUnblockUser = async (userId) => {
    try {
      await axios.post(`${API}/admin/user/${userId}/unblock`, {}, {
        headers: { Authorization: `Bearer ${token}` }
      });
      toast.success('Пользователь разблокирован');
      if (userDetail?.id === userId) {
        handleLoadUserDetail();
      }
    } catch (e) { toast.error(getApiErrorMessage(e) || 'Ошибка разблокировки'); }
  };

  // Admin 2FA gate helper: every mutating /api/admin/* call goes through the
  // global Admin2FAGateMiddleware, which — when the admin has TOTP enabled —
  // requires a fresh 6-digit code in the X-Admin-TOTP header. Rather than guess
  // whether 2FA is on, we try the request; if the backend replies 401 asking
  // for a TOTP code, we prompt once, cache it (codes stay valid ~a minute) and
  // retry — so the admin enters the code a single time per burst of actions.
  const adminTotpCodeRef = useRef('');
  const adminPost = async (url, data = {}, config = {}) => {
    const attempt = (code) => axios.post(url, data, {
      ...config,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(config.headers || {}),
        ...(code ? { 'X-Admin-TOTP': code } : {}),
      },
    });
    try {
      return await attempt(adminTotpCodeRef.current);
    } catch (e) {
      const detail = String(e?.response?.data?.detail || '');
      if (e?.response?.status === 401 && /TOTP/i.test(detail)) {
        const code = (window.prompt('Введите 6-значный код 2FA администратора') || '').trim();
        if (!code) { const c = new Error('cancelled'); c.__cancelled = true; throw c; }
        adminTotpCodeRef.current = code;
        try {
          return await attempt(code);
        } catch (e2) {
          // Wrong/expired code — forget it so the next action re-prompts.
          adminTotpCodeRef.current = '';
          throw e2;
        }
      }
      throw e;
    }
  };

  const handleSetTelegramWebhook = async () => {
    if (!telegramBotToken.trim()) {
      toast.error('Введите токен бота');
      return;
    }
    setSettingWebhook(true);
    try {
      // Step 1: always persist the token first (works regardless of webhook).
      await adminPost(`${API}/admin/settings/telegram-bot-token`, {
        bot_token: telegramBotToken.trim()
      });
      toast.success('Токен бота сохранён');
      // Step 2: try to register the webhook (best-effort). May fail on
      // non-public URLs — that's fine, token is already saved.
      try {
        const res = await adminPost(`${API}/admin/telegram/set-webhook?bot_token=${encodeURIComponent(telegramBotToken.trim())}`, {});
        toast.success(`Webhook установлен: ${res.data.url}`);
      } catch (we) {
        if (we.__cancelled) { toast.error('Действие отменено'); }
        else toast.warning('Токен сохранён, но webhook не установлен: ' + (getApiErrorMessage(we) || 'проверьте публичный домен сервера'));
      }
    } catch (e) {
      if (e.__cancelled) toast.error('Действие отменено');
      else toast.error(getApiErrorMessage(e) || 'Ошибка сохранения токена');
    }
    finally { setSettingWebhook(false); }
  };

  const handleSetAdminTelegramId = async () => {
    if (!adminTelegramId.trim()) {
      toast.error('Введите Telegram ID');
      return;
    }
    try {
      await adminPost(`${API}/admin/settings/telegram-admin-id?admin_telegram_id=${encodeURIComponent(adminTelegramId.trim())}`, {});
      toast.success('Telegram ID админа сохранён');
    } catch (e) { toast.error(e.__cancelled ? 'Действие отменено' : (getApiErrorMessage(e) || 'Ошибка сохранения')); }
  };

  const handleAutoSetupWebhook = async () => {
    try {
      const res = await adminPost(`${API}/admin/settings/telegram-webhook`, {});
      toast.success(`Webhook автоматически настроен: ${res.data.webhook_url}`);
    } catch (e) { toast.error(e.__cancelled ? 'Действие отменено' : (getApiErrorMessage(e) || 'Ошибка автонастройки')); }
  };

  const handleSetTelegramAppUrl = async () => {
    const url = (telegramAppUrl || '').trim();
    if (url && !/^https?:\/\//i.test(url)) {
      toast.error('URL должен начинаться с http:// или https://');
      return;
    }
    setSavingAppUrl(true);
    try {
      await adminPost(`${API}/admin/settings/telegram-app-url`, { app_url: url });
      toast.success('URL для уведомлений сохранён');
    } catch (e) {
      toast.error(e.__cancelled ? 'Действие отменено' : (getApiErrorMessage(e) || 'Ошибка сохранения'));
    } finally {
      setSavingAppUrl(false);
    }
  };

  const handleSetTelegramBotUsername = async () => {
    if (!telegramBotUsername.trim()) {
      toast.error('Введите username бота');
      return;
    }
    try {
      await adminPost(`${API}/admin/settings/telegram-bot-username`, {
        username: telegramBotUsername.trim().replace('@', '')
      });
      toast.success('Username бота сохранён');
    } catch (e) { toast.error(e.__cancelled ? 'Действие отменено' : (getApiErrorMessage(e) || 'Ошибка сохранения')); }
  };

  const handleSetTelegramChannel = async () => {
    setSavingChannel(true);
    try {
      const res = await adminPost(`${API}/admin/settings/telegram-channel`, {
        channel_id: (telegramChannel || '').trim()
      });
      if (res?.data && typeof res.data.channel_id === 'string') {
        setTelegramChannel(res.data.channel_id);
      }
      toast.success('Канал для публикаций сохранён');
    } catch (e) {
      toast.error(e.__cancelled ? 'Действие отменено' : (getApiErrorMessage(e) || 'Ошибка сохранения'));
    } finally { setSavingChannel(false); }
  };

  const handleSetSenderWallet = async () => {
    if (!senderMnemonic.trim()) {
      toast.error('Введите мнемонику');
      return;
    }
    try {
      const res = await axios.post(`${API}/admin/settings/sender-wallet`, {
        mnemonic: senderMnemonic.trim()
      }, {
        headers: { Authorization: `Bearer ${token}` }
      });
      toast.success('Кошелёк отправителя сохранён');
      if (res.data.address) {
        setSenderWalletAddress(res.data.address);
      }
    } catch (e) { toast.error(getApiErrorMessage(e) || 'Ошибка сохранения'); }
  };

  const handleSetDepositAddress = async () => {
    if (!depositAddress.trim()) {
      toast.error('Введите адрес');
      return;
    }
    try {
      await axios.post(`${API}/admin/settings/deposit-address`, {
        address: depositAddress.trim()
      }, {
        headers: { Authorization: `Bearer ${token}` }
      });
      toast.success('Адрес для пополнений сохранён');
    } catch (e) { toast.error(getApiErrorMessage(e) || 'Ошибка сохранения'); }
  };

  const loadWalletSettings = async () => {
    try {
      // Load sender wallet config
      const senderRes = await axios.get(`${API}/admin/settings/sender-wallet`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (senderRes.data.address) {
        setSenderWalletAddress(senderRes.data.address);
      }
      
      // Load deposit address config
      const depositRes = await axios.get(`${API}/admin/settings/deposit-address`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (depositRes.data.address) {
        setDepositAddress(depositRes.data.address);
      }
      
      // Load telegram config
      const tgRes = await axios.get(`${API}/admin/settings/telegram-bot`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (tgRes.data.admin_telegram_id) {
        setAdminTelegramId(tgRes.data.admin_telegram_id);
      }
      if (tgRes.data.bot_username) {
        setTelegramBotUsername(tgRes.data.bot_username);
      }
      if (typeof tgRes.data.app_url === 'string') {
        setTelegramAppUrl(tgRes.data.app_url);
      }
      if (typeof tgRes.data.channel_id === 'string') {
        setTelegramChannel(tgRes.data.channel_id);
      }
    } catch (e) {
      console.error('Failed to load wallet settings:', e);
    }
  };

  const AddressDisplay = ({ address, short = false }) => {
    if (!address) return <span className="text-text-muted">-</span>;
  
    // Если адрес уже в user-friendly формате (UQ... или EQ...), используем его напрямую
    // Если это raw адрес (0:...), тогда преобразуем
    let displayAddress = address;
  
    // Проверяем, является ли это raw адресом
    if (address.startsWith('0:') || address.startsWith('-1:')) {
      // Только в этом случае преобразуем
      displayAddress = toUserFriendlyAddress(address);
    }
    // Иначе используем адрес как есть (он уже user-friendly из API)
  
    const copyToClipboard = () => {
      navigator.clipboard.writeText(displayAddress);
      toast.success('Адрес скопирован');
    };
  
    const shortAddress = short 
      ? `${displayAddress.slice(0, 8)}...${displayAddress.slice(-6)}` 
      : displayAddress;
  
    return (
      <div className="flex items-center gap-2 group">
        <span className="font-mono text-sm break-all" title={displayAddress}>
          {shortAddress}
        </span>
        <Button
          variant="ghost"
          size="icon"
          onClick={copyToClipboard}
          className="h-6 w-6 opacity-50 hover:opacity-100"
        >
          <Copy className="w-3 h-3" />
        </Button>
      </div>
    );
  };

  const formatAddress = (address) => {
    if (!address) return '-';
    const friendly = toUserFriendlyAddress(address);
    return `${friendly.slice(0, 8)}...${friendly.slice(-6)}`;
  };

  const formatDate = (dateStr) => {
    if (!dateStr) return '-';
    return new Date(dateStr).toLocaleString();
  };

  if (!isAdmin) {
    // S5: render nothing for non-admins (silent redirect already fired in useEffect)
    return null;
  }

  if (isLoading) {
    const L = LOADER_I18N[lang] || LOADER_I18N.en;
    const total = loadSteps.length || LOADER_STEP_KEYS.length;
    const done = loadSteps.filter((s) => s.status === 'done' || s.status === 'error').length;
    const percent = total ? Math.round((done / total) * 100) : 0;
    const stepIcon = (status) => {
      if (status === 'done') return <Check className="w-4 h-4 text-emerald-400" />;
      if (status === 'error') return <AlertCircle className="w-4 h-4 text-amber-400" />;
      if (status === 'loading') return <Loader2 className="w-4 h-4 text-cyan-400 animate-spin" />;
      return <span className="block w-2 h-2 rounded-full bg-white/20" />;
    };
    return (
      <div className="min-h-screen bg-void flex items-center justify-center px-4" data-testid="admin-loading-screen">
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          className="w-full max-w-lg glass-panel rounded-2xl border border-white/10 p-6 sm:p-8"
        >
          <div className="flex items-center gap-3 mb-1">
            <Loader2 className="w-6 h-6 text-cyan-400 animate-spin" />
            <h1 className="text-xl font-bold text-white">{L.title}</h1>
          </div>
          <p className="text-white/70 text-sm mb-6">{L.subtitle}</p>

          {/* Progress bar + percent */}
          <div className="mb-2 flex items-end justify-between">
            <span className="text-3xl font-extrabold text-cyan-400 tabular-nums" data-testid="admin-loading-percent">
              {percent}%
            </span>
            <span className="text-xs text-white/70">
              {L.loadedOf.replace('{done}', done).replace('{total}', total)}
            </span>
          </div>
          <div className="h-2.5 w-full rounded-full bg-white/10 overflow-hidden mb-6">
            <motion.div
              className="h-full rounded-full bg-gradient-to-r from-cyan-500 to-emerald-400"
              initial={{ width: 0 }}
              animate={{ width: `${percent}%` }}
              transition={{ ease: 'easeOut', duration: 0.4 }}
              data-testid="admin-loading-bar"
            />
          </div>

          {/* Per-dataset checklist */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
            {loadSteps.map((s) => (
              <div
                key={s.key}
                data-testid={`admin-loading-step-${s.key}`}
                data-status={s.status}
                className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ${
                  s.status === 'done' ? 'bg-emerald-500/5 text-white'
                    : s.status === 'loading' ? 'bg-cyan-500/10 text-white'
                    : s.status === 'error' ? 'bg-amber-500/5 text-amber-200'
                    : 'text-text-muted'
                }`}
              >
                <span className="w-4 h-4 flex items-center justify-center shrink-0">{stepIcon(s.status)}</span>
                <span className="flex-1">{L.steps[s.key] || s.key}</span>
              </div>
            ))}
          </div>
        </motion.div>
      </div>
    );
  }

  const pendingWithdrawals = transactions.filter(tx => tx.tx_type === 'withdrawal' && tx.status === 'pending');

  return (
    <div className="min-h-screen bg-void">
      {/* Header */}
      <header className="glass-panel border-b border-grid-border px-4 lg:px-6 py-4">
        <div className="container mx-auto flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-2 lg:gap-4">
            <Button
              data-testid="admin-go-to-user-ui"
              variant="ghost"
              size="sm"
              onClick={() => navigate('/')}
              className="text-text-muted hover:text-text-main"
            >
              <Home className="w-4 h-4 lg:mr-2" />
              <span className="hidden lg:inline">На сайт</span>
            </Button>
            <h1 className="font-unbounded text-lg lg:text-xl font-bold text-text-main flex items-center gap-2">
              <Settings className="w-5 h-5 text-cyber-cyan" />
              <span className="hidden sm:inline">{t('adminPanel')}</span>
              <span className="sm:hidden">Админ</span>
            </h1>
          </div>
          
          <div className="flex items-center gap-2 lg:gap-3">
            {/* Maintenance Button */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  data-testid="maintenance-toggle-btn"
                  variant="outline"
                  size="sm"
                  className={`transition-all ${
                    maintenanceEnabled 
                      ? 'bg-orange-500/20 border-orange-500 text-orange-400 hover:bg-orange-500/30' 
                      : 'border-grid-border hover:border-white/30'
                  }`}
                >
                  <Wrench className="w-4 h-4 lg:mr-2" />
                  <span className="hidden lg:inline">
                    {maintenanceEnabled ? 'Тех. работы (ВКЛ)' : 'Тех. работы'}
                  </span>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="bg-panel border-grid-border w-56">
                {!maintenanceEnabled ? (
                  <>
                    <DropdownMenuItem 
                      onClick={() => toggleMaintenance(true)}
                      className="cursor-pointer"
                    >
                      <Play className="w-4 h-4 mr-2 text-orange-400" />
                      Начать прямо сейчас
                    </DropdownMenuItem>
                    <DropdownMenuItem 
                      onClick={() => setShowMaintenanceDialog(true)}
                      className="cursor-pointer"
                    >
                      <Clock className="w-4 h-4 mr-2 text-blue-400" />
                      Установить время начала
                    </DropdownMenuItem>
                  </>
                ) : (
                  <DropdownMenuItem 
                    onClick={() => toggleMaintenance(false)}
                    className="cursor-pointer"
                  >
                    <Check className="w-4 h-4 mr-2 text-green-400" />
                    Закончить тех. работы
                  </DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>

            {/* Email-2FA force-all toggle */}
            <Button
              data-testid="email-2fa-toggle-btn"
              variant="outline"
              size="sm"
              onClick={toggleEmail2faForceAll}
              disabled={savingEmail2fa}
              className={`transition-all ${
                email2faForceAll
                  ? 'bg-cyber-cyan/15 border-cyber-cyan text-cyber-cyan hover:bg-cyber-cyan/25'
                  : 'border-grid-border hover:border-white/30'
              }`}
              title={email2faForceAll
                ? 'Email-2FA включена для всех — каждый вход требует код с почты'
                : 'Включить Email-2FA для всех пользователей'}
            >
              <Mail className="w-4 h-4 lg:mr-2" />
              <span className="hidden lg:inline">
                {email2faForceAll ? 'Email-2FA: ВКЛ' : 'Email-2FA: ВЫКЛ'}
              </span>
            </Button>
            
            <Button
              variant="outline"
              size="sm"
              onClick={loadData}
              className="border-grid-border"
            >
              <RefreshCw className="w-4 h-4 lg:mr-2" />
              <span className="hidden lg:inline">{t('refresh')}</span>
            </Button>
          </div>
        </div>
      </header>

      {/* Schedule Maintenance Dialog */}
      <Dialog open={showMaintenanceDialog} onOpenChange={setShowMaintenanceDialog}>
        <DialogContent className="glass-panel border-grid-border">
          <DialogHeader>
            <DialogTitle className="text-text-main flex items-center gap-2">
              <Calendar className="w-5 h-5 text-blue-400" />
              Запланировать технические работы
            </DialogTitle>
            <DialogDescription className="text-text-muted">
              Укажите дату и время начала технических работ
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <Input
              type="datetime-local"
              value={scheduledTime}
              onChange={(e) => setScheduledTime(e.target.value)}
              className="bg-panel border-grid-border text-text-main"
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowMaintenanceDialog(false)}>
              Отмена
            </Button>
            <Button 
              onClick={() => toggleMaintenance(false, scheduledTime ? new Date(scheduledTime).toISOString() : null)}
              className="bg-blue-600 hover:bg-blue-700"
              disabled={!scheduledTime}
            >
              Запланировать
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Content */}
      <main className="container mx-auto px-6 tg-header-pad sm:py-8">
        {/* Stats Cards - Only unique metrics */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="glass-panel rounded-2xl p-6"
          >
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-lg bg-purple-500/10 flex items-center justify-center">
                <Map className="w-5 h-5 text-purple-400" />
              </div>
              <span className="text-text-muted text-sm">Доход от продажи новой земли и бизнесов</span>
            </div>
            <div className="font-mono text-3xl text-purple-400">
              {formatCity(tonToCity((stats?.treasury?.first_sale_revenue || 0) + (stats?.treasury?.building_sales_income || 0)))} $CITY
            </div>
            <p className="text-xs text-text-muted mt-2">
              Земля: {formatCity(tonToCity(stats?.treasury?.first_sale_revenue || 0))} $CITY | 
              Бизнесы: {formatCity(tonToCity(stats?.treasury?.building_sales_income || 0))} $CITY
            </p>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 }}
            className="glass-panel rounded-2xl p-6"
          >
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-lg bg-error/10 flex items-center justify-center">
                <CreditCard className="w-5 h-5 text-error" />
              </div>
              <span className="text-text-muted text-sm">{t('pendingWithdrawals')}</span>
            </div>
            <div className="font-mono text-3xl text-error">
              {stats?.pending_withdrawals || 0}
            </div>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2 }}
            className="glass-panel rounded-2xl p-6"
          >
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-lg bg-emerald-500/10 flex items-center justify-center">
                <div className="relative">
                  <Users className="w-5 h-5 text-emerald-400" />
                  <span className="absolute -top-1 -right-1 w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                </div>
              </div>
              <span className="text-text-muted text-sm">{t('onlineNow') || 'Онлайн сейчас'}</span>
            </div>
            <div className="flex items-baseline gap-2">
              <span className="font-mono text-3xl text-emerald-400">{stats?.online_now || 0}</span>
              <span className="text-[11px] text-text-muted">{t('onlineTotal') || 'всего'}</span>
            </div>
            <div className="flex items-center gap-4 mt-2">
              <div className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-cyan-400" />
                <span className="text-xs text-text-muted">{t('onlineWeb') || 'Веб'}:</span>
                <span className="text-xs font-mono text-cyan-300">{stats?.online_web ?? 0}</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-sky-400" />
                <span className="text-xs text-text-muted">{t('onlineTelegram') || 'Telegram'}:</span>
                <span className="text-xs font-mono text-sky-300">{stats?.online_telegram ?? 0}</span>
              </div>
            </div>
            <div className="text-[10px] text-text-muted/70 mt-1">
              {t('onlineWindowHint') || 'активность за 5 мин'}
            </div>
          </motion.div>

          {/* Market activity: active/inactive users + manual seizure */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.25 }}
            className="glass-panel rounded-2xl p-6"
            data-testid="admin-activity-card"
          >
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-lg bg-amber-500/10 flex items-center justify-center">
                <AlertCircle className="w-5 h-5 text-amber-400" />
              </div>
              <span className="text-text-muted text-sm">{lang === 'ru' ? 'Активность на рынке' : 'Market activity'}</span>
            </div>
            <div className="flex items-center gap-6">
              <div>
                <div className="font-mono text-3xl text-emerald-400" data-testid="admin-active-users">{stats?.market_active_users ?? 0}</div>
                <div className="text-[11px] text-text-muted">{lang === 'ru' ? 'активные' : 'active'}</div>
              </div>
              <div>
                <div className="font-mono text-3xl text-rose-400" data-testid="admin-inactive-users">{stats?.market_inactive_users ?? 0}</div>
                <div className="text-[11px] text-text-muted">{lang === 'ru' ? 'неактивные' : 'inactive'}</div>
              </div>
            </div>
            <div className="text-[10px] text-text-muted/70 mt-1">
              {lang === 'ru'
                ? `актив: покупка ≥${stats?.market_activity?.buy_threshold ?? 40} или продажа ≥${stats?.market_activity?.sell_threshold ?? 100} ед. / ${stats?.market_activity?.window_days ?? 7} дн.`
                : `active: buy ≥${stats?.market_activity?.buy_threshold ?? 40} or sell ≥${stats?.market_activity?.sell_threshold ?? 100} units / ${stats?.market_activity?.window_days ?? 7}d`}
            </div>
            <Button
              onClick={runSeize}
              disabled={seizing}
              className="mt-3 w-full bg-amber-500/90 hover:bg-amber-500 text-black"
              data-testid="admin-seize-inactive-btn"
            >
              {seizing ? (lang === 'ru' ? 'Изъятие…' : 'Seizing…') : (lang === 'ru' ? 'Изъять неактивных' : 'Seize inactive')}
            </Button>
          </motion.div>
        </div>

        {/* Treasury Health Warning */}
        {treasuryHealth && (
          <TreasuryWarning treasuryStats={treasuryHealth} lang={lang} />
        )}

        {/* Tabs */}
        <Tabs defaultValue="revenue" className="space-y-6">
          <TabsList className="glass-panel border-grid-border flex-wrap">
            <TabsTrigger value="revenue" className="data-[state=active]:bg-cyber-cyan/10 data-[state=active]:text-cyber-cyan">
              <DollarSign className="w-4 h-4 mr-2" />
              Доходы
            </TabsTrigger>
            <TabsTrigger value="withdrawals" className="data-[state=active]:bg-cyber-cyan/10 data-[state=active]:text-cyber-cyan">
              Ожидающие выводы ({pendingWithdrawals.length})
            </TabsTrigger>
            <TabsTrigger value="transactions" className="data-[state=active]:bg-cyber-cyan/10 data-[state=active]:text-cyber-cyan">
              Транзакции
            </TabsTrigger>
            <TabsTrigger value="promos" className="data-[state=active]:bg-cyber-cyan/10 data-[state=active]:text-cyber-cyan">
              Промокоды
            </TabsTrigger>
            <TabsTrigger value="announcements" className="data-[state=active]:bg-cyber-cyan/10 data-[state=active]:text-cyber-cyan">
              Объявления
            </TabsTrigger>
            <TabsTrigger value="data" className="data-[state=active]:bg-amber-500/10 data-[state=active]:text-amber-400" data-testid="admin-tab-data">
              Данные
            </TabsTrigger>
            <TabsTrigger value="retention" className="data-[state=active]:bg-cyan-500/10 data-[state=active]:text-cyan-400" data-testid="admin-tab-retention">
              Удержание
            </TabsTrigger>
            <TabsTrigger value="market-maker" className="data-[state=active]:bg-cyan-500/10 data-[state=active]:text-cyan-400" data-testid="admin-tab-market-maker">
              Городской рынок
            </TabsTrigger>
            <TabsTrigger value="comeback" className="data-[state=active]:bg-purple-500/10 data-[state=active]:text-purple-300" data-testid="admin-tab-comeback">
              Бонус возвращения
            </TabsTrigger>
            <TabsTrigger value="leagues" className="data-[state=active]:bg-yellow-500/10 data-[state=active]:text-yellow-300" data-testid="admin-tab-leagues">
              Лиги
            </TabsTrigger>
            <TabsTrigger value="reconciliation" className="data-[state=active]:bg-emerald-500/10 data-[state=active]:text-emerald-300" data-testid="admin-tab-reconciliation">
              Сверка
            </TabsTrigger>
            <TabsTrigger value="city-pass" className="data-[state=active]:bg-indigo-500/10 data-[state=active]:text-indigo-300" data-testid="admin-tab-city-pass">
              City Pass
            </TabsTrigger>
            <TabsTrigger value="rental" className="data-[state=active]:bg-cyan-500/10 data-[state=active]:text-cyan-300" data-testid="admin-tab-rental">
              Аренда
            </TabsTrigger>
            <TabsTrigger value="minigames" className="data-[state=active]:bg-amber-500/10 data-[state=active]:text-amber-300" data-testid="admin-tab-minigames">
              Мини-игры
            </TabsTrigger>
            <TabsTrigger value="credits" className="data-[state=active]:bg-orange-500/10 data-[state=active]:text-orange-400" data-testid="admin-tab-credits">
              Кредиты
            </TabsTrigger>
            <TabsTrigger value="taxes" className="data-[state=active]:bg-red-500/10 data-[state=active]:text-red-400">
              Налоги
            </TabsTrigger>
            <TabsTrigger value="contract" className="data-[state=active]:bg-green-500/10 data-[state=active]:text-green-400">
              Контракт
            </TabsTrigger>
            <TabsTrigger value="multiaccounts" className="data-[state=active]:bg-red-500/10 data-[state=active]:text-red-400">
              Мульти-аккаунты
            </TabsTrigger>
            <TabsTrigger value="support" className="data-[state=active]:bg-cyan-500/10 data-[state=active]:text-cyan-400" data-testid="admin-tab-support">
              Поддержка
            </TabsTrigger>
            <TabsTrigger value="tasks" className="data-[state=active]:bg-yellow-500/10 data-[state=active]:text-yellow-400" data-testid="admin-tab-tasks">
              Задания
            </TabsTrigger>
            <TabsTrigger value="bizconfig" className="data-[state=active]:bg-emerald-500/10 data-[state=active]:text-emerald-400" data-testid="admin-tab-bizconfig">
              {lang === 'ru' ? 'Бизнесы' : 'Businesses'}
            </TabsTrigger>
          </TabsList>

          {/* Business economy (production/consumption) Tab */}
          <TabsContent value="bizconfig">
            <AdminBusinessConfig token={token} lang={lang} />
          </TabsContent>

          {/* Tasks Management Tab */}
          <TabsContent value="tasks">
            <AdminTasksTab lang={lang} />
          </TabsContent>

          {/* Support Management Tab */}
          <TabsContent value="support">
            <SupportManagementTab />
          </TabsContent>

          {/* Revenue Analytics Tab */}
          <TabsContent value="revenue">
            <RevenueAnalytics token={token} />
          </TabsContent>

          {/* Withdrawals Tab */}
          <TabsContent value="withdrawals">
            <div className="glass-panel rounded-2xl p-6">
              <div className="flex items-center justify-between mb-6">
                <h2 className="font-unbounded text-lg font-bold text-text-main">
                  {t('pendingWithdrawals')} ({pendingWithdrawals.length})
                </h2>
                
                {pendingWithdrawals.length > 0 && (
                  <div className="flex items-center gap-4">
                    <label className="flex items-center gap-2 text-sm text-text-muted cursor-pointer">
                      <input 
                        type="checkbox" 
                        checked={selectAllWithdrawals}
                        onChange={(e) => handleSelectAllWithdrawals(e.target.checked)}
                        className="w-4 h-4 rounded border-white/20 bg-white/5"
                      />
                      Выбрать все
                    </label>
                    
                    {selectedWithdrawals.size > 0 && (
                      <div className="flex gap-2">
                        <Button
                          size="sm"
                          onClick={bulkApproveWithdrawals}
                          className="bg-success hover:bg-success/80"
                        >
                          <Check className="w-4 h-4 mr-1" />
                          Одобрить ({selectedWithdrawals.size})
                        </Button>
                        <Button
                          size="sm"
                          variant="destructive"
                          onClick={bulkRejectWithdrawals}
                        >
                          <X className="w-4 h-4 mr-1" />
                          Отклонить ({selectedWithdrawals.size})
                        </Button>
                      </div>
                    )}
                  </div>
                )}
              </div>
              
              {pendingWithdrawals.length === 0 ? (
                <div className="text-center py-12 text-text-muted">
                  No pending withdrawals
                </div>
              ) : (
                <ScrollArea className="h-[500px]">
                  <div className="space-y-4">
                    {pendingWithdrawals.map((tx) => (
                      <div
                        key={tx.id}
                        className={`glass-panel rounded-lg p-4 transition-all ${selectedWithdrawals.has(tx.id) ? 'ring-2 ring-cyber-cyan' : ''}`}
                      >
                        <div className="flex items-start gap-4">
                          <input 
                            type="checkbox" 
                            checked={selectedWithdrawals.has(tx.id)}
                            onChange={() => toggleWithdrawalSelection(tx.id)}
                            className="w-5 h-5 mt-2 rounded border-white/20 bg-white/5 cursor-pointer"
                          />
                          <div className="flex-1 space-y-2">
                            <div>
                              <div className="text-xs text-text-muted mb-1">Пользователь:</div>
                              <div className="text-white text-sm">{tx.user_username || tx.user_id}</div>
                            </div>
                            <div>
                              <div className="text-xs text-text-muted mb-1">Куда (To):</div>
                              <AddressDisplay address={tx.to_address_display || tx.to_address} />
                            </div>
                            <div className="text-xs text-text-muted">
                              {formatDate(tx.created_at)}
                            </div>
                          </div>
                          <div className="text-right">
                            <div className="font-mono text-2xl text-signal-amber">
                              {formatCity(tonToCity(tx.amount_ton))} $CITY
                            </div>
                            <div className="text-sm text-text-muted">
                              Комиссия: {formatCity(tonToCity(tx.commission))} $CITY
                            </div>
                            <div className="text-sm text-success">
                              К выплате: {formatCity(tonToCity(tx.amount_ton - (tx.commission || 0)))} $CITY
                            </div>
                          </div>
                          <div className="flex flex-col gap-2">
                            <Button
                              size="sm"
                              onClick={() => approveWithdrawal(tx.id)}
                              className="bg-success hover:bg-success/80"
                            >
                              <Check className="w-4 h-4 mr-1" />
                              Одобрить
                            </Button>
                            <Button
                              size="sm"
                              variant="destructive"
                              onClick={() => rejectWithdrawal(tx.id)}
                            >
                              <X className="w-4 h-4 mr-1" />
                              Отклонить
                            </Button>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </ScrollArea>
              )}
            </div>
          </TabsContent>

          {/* Users Tab */}
          <TabsContent value="users">
            <div className="glass-panel rounded-2xl p-6">
              <div className="flex flex-wrap items-center gap-3 mb-4">
                <h2 className="font-unbounded text-lg font-bold text-text-main" data-testid="admin-users-count">
                  {t('users')} ({users.length} из {usersTotal})
                </h2>
                <input
                  value={usersQuery}
                  onChange={(e) => { const v = e.target.value; setUsersQuery(v); clearTimeout(window.__usersSearchT); window.__usersSearchT = setTimeout(() => loadUsers(0, v), 400); }}
                  placeholder="Поиск: ник, почта, кошелёк, ID"
                  className="ml-auto w-64 max-w-full rounded-lg bg-black/40 border border-white/10 px-3 py-2 text-sm text-white"
                  data-testid="admin-users-search"
                />
              </div>

              <ScrollArea className="h-[32rem]">
                <div className="space-y-3">
                  {users.map((user) => (
                    <div
                      key={user.id || user.wallet_address}
                      className="glass-panel rounded-lg p-4 flex items-center gap-4"
                    >
                      <div className="flex-1">
                        <div className="font-mono text-sm text-text-main flex items-center gap-2">
                          {formatAddress(user.wallet_address)}
                          {user.is_admin && (
                            <span className="px-2 py-0.5 bg-cyber-cyan/20 text-cyber-cyan text-xs rounded">
                              ADMIN
                            </span>
                          )}
                        </div>
                        <div className="text-xs text-text-muted">
                          Level: {user.level} | Plots: {user.plots_owned?.length || 0} | Businesses: {user.businesses_owned?.length || 0}
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="font-mono text-sm text-success">
                          {formatCity(tonToCity(user.total_income || 0))} $CITY income
                        </div>
                        <div className="text-xs text-text-muted" data-testid="admin-user-balance">
                          Balance: {formatCity(tonToCity((user.balance_ton || 0) + (user.bonus_balance || 0)))} $CITY
                        </div>
                        <div className="text-[10px] text-text-muted/70">
                          Реальный: {formatCity(tonToCity(user.balance_ton || 0))} · Бонус: {formatCity(tonToCity(user.bonus_balance || 0))} $CITY
                        </div>
                      </div>
                      <Button
                        size="sm"
                        variant="outline"
                        className="border-cyber-cyan/40 text-cyber-cyan hover:bg-cyber-cyan/10"
                        onClick={() => openUserTx(user)}
                        data-testid={`user-transactions-btn-${user.id || user.wallet_address}`}
                      >
                        Транзакции
                      </Button>
                      <Button
                        size="sm"
                        variant={user.is_admin ? "destructive" : "outline"}
                        onClick={() => setUserAdmin(user.wallet_address, !user.is_admin)}
                      >
                        {user.is_admin ? 'Remove Admin' : 'Make Admin'}
                      </Button>
                    </div>
                  ))}
                </div>
                  {users.length < usersTotal && (
                    <button type="button" onClick={() => loadUsers(users.length)} disabled={usersLoading} data-testid="admin-users-more"
                      className="w-full rounded-lg border border-white/10 bg-white/5 py-2.5 text-sm text-white hover:border-cyan-400/50 disabled:opacity-50">
                      {usersLoading ? 'Загрузка…' : `Показать ещё ${Math.min(50, usersTotal - users.length)}`}
                    </button>
                  )}
              </ScrollArea>
            </div>
          </TabsContent>

          {/* Transactions Tab */}
          <TabsContent value="transactions">
            <div className="glass-panel rounded-2xl p-6 space-y-4">
              {/* Search transaction by ID */}
              <div className="glass-panel rounded-xl p-4 border border-cyan-500/20">
                <h3 className="font-unbounded text-sm font-bold text-white mb-3">Поиск операции по ID</h3>
                <div className="flex gap-3">
                  <Input
                    data-testid="tx-search-input"
                    placeholder="ID операции"
                    value={txSearchId}
                    onChange={(e) => setTxSearchId(e.target.value)}
                    className="bg-white/5 border-white/10"
                    onKeyDown={(e) => e.key === 'Enter' && handleSearchTransaction()}
                  />
                  <Button onClick={handleSearchTransaction} disabled={loadingTxSearch} className="btn-cyber">
                    {loadingTxSearch ? <RefreshCw className="w-4 h-4 animate-spin" /> : 'Найти'}
                  </Button>
                </div>
                
                {/* Transaction search result */}
                {txSearchResult && (
                  <div className="mt-4 p-4 bg-white/5 rounded-lg space-y-3">
                    <div className="flex items-center justify-between flex-wrap gap-2">
                      <span className={`px-2 py-1 rounded text-xs ${
                        txSearchResult.status === 'completed' ? 'bg-success/20 text-success' :
                        txSearchResult.status === 'pending' ? 'bg-signal-amber/20 text-signal-amber' :
                        'bg-error/20 text-error'
                      }`}>
                        {txSearchResult.status_display || txSearchResult.status}
                      </span>
                      <span className="text-text-muted text-sm">{txSearchResult.type_name || txSearchResult.tx_type}</span>
                    </div>
                    
                    <div className="grid grid-cols-2 gap-3 text-sm">
                      <div>
                        <span className="text-text-muted">Сумма:</span>
                        <span className="text-white ml-2 font-mono">
                          {formatCity(tonToCity(txSearchResult.amount_ton || txSearchResult.amount || 0))} $CITY
                        </span>
                      </div>
                      <div>
                        <span className="text-text-muted">Дата:</span>
                        <span className="text-white ml-2">{formatDate(txSearchResult.created_at)}</span>
                      </div>
                      {txSearchResult.user_username && (
                        <div>
                          <span className="text-text-muted">Пользователь:</span>
                          <span className="text-cyber-cyan ml-2">{txSearchResult.user_username}</span>
                        </div>
                      )}
                      {txSearchResult.from_address && (
                        <div>
                          <span className="text-text-muted">От:</span>
                          <span className="text-white ml-2 font-mono">{formatAddress(txSearchResult.from_address)}</span>
                        </div>
                      )}
                      {txSearchResult.to_address && (
                        <div>
                          <span className="text-text-muted">Кому:</span>
                          <span className="text-white ml-2 font-mono">{formatAddress(txSearchResult.to_address)}</span>
                        </div>
                      )}
                    </div>
                    
                    <div className="pt-2 border-t border-white/10 text-xs">
                      <span className="text-text-muted">ID: </span>
                      <span className="font-mono text-white">{txSearchResult.id}</span>
                    </div>
                  </div>
                )}
              </div>

              {/* Search all operations of a specific user (by ID or username) */}
              <div className="glass-panel rounded-xl p-4 border border-purple-500/20">
                <h3 className="font-unbounded text-sm font-bold text-white mb-3">Поиск операций по пользователю (ID или имя)</h3>
                <div className="flex gap-3 flex-wrap">
                  <Input
                    data-testid="tx-user-search-input"
                    placeholder="ID пользователя или имя пользователя"
                    value={txUserSearchInput}
                    onChange={(e) => setTxUserSearchInput(e.target.value)}
                    className="bg-white/5 border-white/10 flex-1 min-w-[200px]"
                    onKeyDown={(e) => e.key === 'Enter' && setTxUserSearch(txUserSearchInput.trim())}
                  />
                  <Button
                    onClick={() => setTxUserSearch(txUserSearchInput.trim())}
                    className="btn-cyber"
                    data-testid="tx-user-search-btn"
                  >
                    Найти операции
                  </Button>
                  {txUserSearch && (
                    <Button
                      variant="outline"
                      className="border-white/10 text-white"
                      onClick={() => { setTxUserSearchInput(''); setTxUserSearch(''); }}
                      data-testid="tx-user-search-clear-btn"
                    >
                      Сбросить
                    </Button>
                  )}
                </div>
                {txUserSearch && (
                  <div className="mt-2 text-xs text-text-muted" data-testid="tx-user-search-active">
                    Показаны операции пользователя: <span className="text-cyber-cyan font-medium">{txUserSearch}</span> · всего найдено: {txTotal}
                  </div>
                )}
              </div>

              <div className="flex items-center justify-between flex-wrap gap-3">
                <h2 className="font-unbounded text-lg font-bold text-text-main">
                  {t('transactions')}
                </h2>
                
                {/* CSV Export */}
                <div className="flex items-center gap-2 ml-auto">
                  <span className="text-xs text-text-muted">
                    {selectedTxIds.size > 0 ? `${selectedTxIds.size} selected` : 'No selection — exports filtered list'}
                  </span>
                  {selectedTxIds.size > 0 && (
                    <Button
                      size="sm"
                      variant="outline"
                      className="border-white/10 text-white"
                      onClick={() => setSelectedTxIds(new Set())}
                      data-testid="clear-selection-btn"
                    >
                      Clear
                    </Button>
                  )}
                  <Button
                    size="sm"
                    className="bg-cyber-cyan text-black hover:bg-cyber-cyan/80"
                    disabled={exportingCsv}
                    data-testid="export-csv-btn"
                    onClick={async () => {
                      setExportingCsv(true);
                      try {
                        const token = localStorage.getItem('token') || localStorage.getItem('ton_city_token');
                        const body = selectedTxIds.size > 0
                          ? { ids: Array.from(selectedTxIds) }
                          : { filters: { tx_type: txFilter !== 'all' ? txFilter : undefined, limit: 5000 } };
                        const res = await axios.post(
                          `${API}/admin/transactions/export-csv?lang=ru`,
                          body,
                          { headers: { Authorization: `Bearer ${token}` }, responseType: 'blob' }
                        );
                        const blob = new Blob([res.data], { type: 'text/csv;charset=utf-8' });
                        const url = window.URL.createObjectURL(blob);
                        const a = document.createElement('a');
                        a.href = url;
                        a.download = `transactions_${new Date().toISOString().slice(0,19).replace(/[:T]/g,'')}.csv`;
                        document.body.appendChild(a);
                        a.click();
                        document.body.removeChild(a);
                        window.URL.revokeObjectURL(url);
                      } catch (e) {
                        // axios returns the error body as a Blob when responseType='blob';
                        // read it back as text so the user sees the real backend detail
                        // ("Session expired", "TOTP required", …) instead of the
                        // opaque "Request failed with status code 401".
                        let detail = e.message;
                        try {
                          if (e.response?.data instanceof Blob) {
                            const txt = await e.response.data.text();
                            try { detail = JSON.parse(txt).detail || txt || detail; }
                            catch { detail = txt || detail; }
                          } else if (e.response?.data?.detail) {
                            detail = e.response.data.detail;
                          }
                        } catch { /* keep e.message */ }
                        if (e.response?.status === 401) {
                          detail = 'Сессия истекла. Войдите в аккаунт заново и попробуйте снова.';
                        }
                        alert('Failed to export CSV: ' + detail);
                      } finally {
                        setExportingCsv(false);
                      }
                    }}
                  >
                    📥 Export CSV
                  </Button>
                </div>
                
                {/* Filter */}
                <div className="flex gap-2 flex-wrap">
                  {['all', 'deposit', 'withdrawal', 'land_purchase', 'business_purchase', 'other'].map(filter => (
                    <Button
                      key={filter}
                      size="sm"
                      variant={txFilter === filter ? 'default' : 'outline'}
                      onClick={() => setTxFilter(filter)}
                      className={txFilter === filter ? 'bg-cyber-cyan text-black' : 'border-white/10'}
                    >
                      {filter === 'all' ? 'Все' : 
                       filter === 'deposit' ? 'Пополнения' : 
                       filter === 'withdrawal' ? 'Выводы' : 
                       filter === 'land_purchase' ? 'Покупка земли' : 
                       filter === 'business_purchase' ? 'Покупка бизнеса' : 'Другое'}
                    </Button>
                  ))}
                </div>
              </div>
              
              <div className="h-96 overflow-y-auto pr-1" onScroll={onTxScroll} data-testid="tx-scroll-container">
                <div className="space-y-2">
                  {transactions
                    .filter(tx => {
                      if (txFilter === 'all') return true;
                      if (txFilter === 'deposit') return tx.tx_type === 'deposit';
                      if (txFilter === 'withdrawal') return tx.tx_type === 'withdrawal';
                      if (txFilter === 'land_purchase') return tx.tx_type === 'land_purchase' || tx.type === 'land_purchase';
                      if (txFilter === 'business_purchase') return tx.tx_type === 'business_purchase' || tx.type === 'business_purchase';
                      return !['deposit', 'withdrawal', 'land_purchase', 'business_purchase'].includes(tx.tx_type);
                    })
                    .map((tx) => {
                      const isDepositOrWithdraw = ['deposit', 'withdrawal'].includes(tx.tx_type);
                      const amount = tx.amount_ton || tx.amount || 0;
                      const isNegative = tx.tx_type === 'withdrawal' || amount < 0;
                      
                      return (
                        <div
                          key={tx.id}
                          className="glass-panel rounded-lg p-3 text-sm"
                        >
                          <div className="flex items-center gap-3 flex-wrap">
                            {/* Selection checkbox */}
                            <input
                              type="checkbox"
                              checked={selectedTxIds.has(tx.id)}
                              onChange={(e) => {
                                const next = new Set(selectedTxIds);
                                if (e.target.checked) next.add(tx.id); else next.delete(tx.id);
                                setSelectedTxIds(next);
                              }}
                              className="w-4 h-4 accent-cyber-cyan cursor-pointer"
                              data-testid={`select-tx-${tx.id}`}
                            />
                            
                            {/* Status */}
                            <span className={`px-2 py-0.5 rounded text-xs whitespace-nowrap ${
                              tx.status === 'completed' ? 'bg-success/20 text-success' :
                              tx.status === 'pending' ? 'bg-signal-amber/20 text-signal-amber' :
                              tx.status === 'processing' ? 'bg-blue-500/20 text-blue-400' :
                              'bg-error/20 text-error'
                            }`}>
                              {tx.status_display || tx.status}
                            </span>
                            
                            {/* Type */}
                            <span className="text-text-muted whitespace-nowrap">
                              {tx.type_icon ? `${tx.type_icon} ` : ''}{tx.type_name || tx.tx_type}
                            </span>
                            
                            {/* User / buyer / seller */}
                            {(tx.buyer_username || tx.seller_username) ? (
                              <span className="flex items-center gap-2 flex-wrap text-xs" data-testid={`tx-parties-${tx.id}`}>
                                {tx.buyer_username && (
                                  <span className="whitespace-nowrap">
                                    <span className="text-text-muted">Покупатель:</span>{' '}
                                    <span className="text-cyber-cyan font-medium">{tx.buyer_username}</span>
                                  </span>
                                )}
                                {tx.seller_username && (
                                  <span className="whitespace-nowrap">
                                    <span className="text-text-muted">Продавец:</span>{' '}
                                    <span className="text-amber-400 font-medium">{tx.seller_username}</span>
                                  </span>
                                )}
                              </span>
                            ) : (
                              tx.user_username && (
                                <span className="text-cyber-cyan font-medium">{tx.user_username}</span>
                              )
                            )}
                            
                            {/* Amount with correct sign */}
                            <span className={`font-mono whitespace-nowrap ml-auto ${isNegative ? 'text-red-400' : 'text-green-400'}`}>
                              {isNegative ? '-' : '+'}{formatCity(tonToCity(Math.abs(amount)))} $CITY
                            </span>
                            
                            {/* Date */}
                            <span className="text-text-muted text-xs whitespace-nowrap">
                              {formatDate(tx.created_at)}
                            </span>
                          </div>

                          {/* Description of what happened */}
                          {tx.description && (
                            <div className="mt-1 text-sm text-white" data-testid={`tx-description-${tx.id}`}>
                              {tx.description}
                            </div>
                          )}
                          
                          {/* Details row */}
                          <div className="mt-2 pt-2 border-t border-white/5 text-xs">
                            {isDepositOrWithdraw ? (
                              // For deposits/withdrawals - show wallets
                              <div className="flex flex-wrap gap-x-4 gap-y-1 text-text-muted">
                                {tx.from_address && (
                                  <span>От: <span className="font-mono text-white">{formatAddress(tx.from_address)}</span></span>
                                )}
                                {tx.to_address && (
                                  <span>Кому: <span className="font-mono text-white">{formatAddress(tx.to_address)}</span></span>
                                )}
                              </div>
                            ) : (
                              // For other operations - show transaction ID
                              <div className="flex items-center gap-2 text-text-muted">
                                <span>ID операции:</span>
                                <span className="font-mono text-white">{tx.id}</span>
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  className="h-5 w-5 p-0"
                                  onClick={() => {
                                    navigator.clipboard.writeText(tx.id);
                                    toast.success('ID скопирован');
                                  }}
                                >
                                  <Copy className="w-3 h-3" />
                                </Button>
                              </div>
                            )}
                          </div>
                        </div>
                      );
                    })}
                </div>
                {/* Infinite-scroll status footer */}
                <div className="py-4 text-center text-xs text-text-muted" data-testid="tx-load-more-status">
                  {txLoadingMore ? (
                    <span className="inline-flex items-center gap-2"><RefreshCw className="w-3 h-3 animate-spin" /> Загрузка…</span>
                  ) : txHasMore ? (
                    <button className="text-cyber-cyan hover:underline" onClick={() => loadTransactions(false)} data-testid="tx-load-more-btn">
                      Показать ещё
                    </button>
                  ) : (
                    <span>Загружено {transactions.length} из {txTotal}</span>
                  )}
                </div>
              </div>
            </div>
          </TabsContent>

          {/* Per-user transactions modal (opened from the Users tab) */}
          <Dialog open={userTxModalOpen} onOpenChange={setUserTxModalOpen}>
            <DialogContent className="bg-void border-white/10 max-w-2xl" data-testid="user-tx-modal">
              <DialogHeader>
                <DialogTitle className="text-white">
                  Транзакции пользователя
                  {userTxTarget && (
                    <span className="text-cyber-cyan ml-2">
                      {userTxTarget.username || userTxTarget.display_name || userTxTarget.email || formatAddress(userTxTarget.wallet_address)}
                    </span>
                  )}
                </DialogTitle>
                <DialogDescription className="text-text-muted text-xs">
                  {userTxTarget?.id && <span className="font-mono">ID: {userTxTarget.id}</span>}
                  <span className="ml-2">Всего операций: {userTxTotal}</span>
                </DialogDescription>
              </DialogHeader>
              <div className="h-[60vh] overflow-y-auto pr-1 space-y-2" onScroll={onUserTxScroll} data-testid="user-tx-scroll">
                {userTxList.length === 0 && !userTxLoading && (
                  <div className="text-center text-text-muted text-sm py-8" data-testid="user-tx-empty">
                    Операции не найдены
                  </div>
                )}
                {userTxList.map((tx) => {
                  const amount = tx.amount_ton || tx.amount || 0;
                  const isNegative = tx.tx_type === 'withdrawal' || amount < 0;
                  return (
                    <div key={tx.id} className="glass-panel rounded-lg p-3 text-sm" data-testid={`user-tx-row-${tx.id}`}>
                      <div className="flex items-center gap-3 flex-wrap">
                        <span className={`px-2 py-0.5 rounded text-xs whitespace-nowrap ${
                          tx.status === 'completed' ? 'bg-success/20 text-success' :
                          tx.status === 'pending' ? 'bg-signal-amber/20 text-signal-amber' :
                          tx.status === 'processing' ? 'bg-blue-500/20 text-blue-400' :
                          'bg-error/20 text-error'
                        }`}>
                          {tx.status_display || tx.status}
                        </span>
                        <span className="text-text-muted whitespace-nowrap">
                          {tx.type_icon ? `${tx.type_icon} ` : ''}{tx.type_name || tx.tx_type}
                        </span>
                        {(tx.buyer_username || tx.seller_username) && (
                          <span className="flex items-center gap-2 flex-wrap text-xs">
                            {tx.buyer_username && (
                              <span className="whitespace-nowrap"><span className="text-text-muted">Покупатель:</span>{' '}<span className="text-cyber-cyan font-medium">{tx.buyer_username}</span></span>
                            )}
                            {tx.seller_username && (
                              <span className="whitespace-nowrap"><span className="text-text-muted">Продавец:</span>{' '}<span className="text-amber-400 font-medium">{tx.seller_username}</span></span>
                            )}
                          </span>
                        )}
                        <span className={`font-mono whitespace-nowrap ml-auto ${isNegative ? 'text-red-400' : 'text-green-400'}`}>
                          {isNegative ? '-' : '+'}{formatCity(tonToCity(Math.abs(amount)))} $CITY
                        </span>
                        <span className="text-text-muted text-xs whitespace-nowrap">{formatDate(tx.created_at)}</span>
                      </div>
                      {tx.description && (
                        <div className="mt-1 text-sm text-white">{tx.description}</div>
                      )}
                      <div className="mt-2 pt-2 border-t border-white/5 text-xs flex items-center gap-2 text-text-muted">
                        <span>ID:</span>
                        <span className="font-mono text-white break-all">{tx.id}</span>
                      </div>
                    </div>
                  );
                })}
                <div className="py-3 text-center text-xs text-text-muted">
                  {userTxLoading ? (
                    <span className="inline-flex items-center gap-2"><RefreshCw className="w-3 h-3 animate-spin" /> Загрузка…</span>
                  ) : userTxHasMore ? (
                    <button className="text-cyber-cyan hover:underline" onClick={() => loadUserTx(userTxTarget, false, userTxList.length)} data-testid="user-tx-load-more-btn">
                      Показать ещё
                    </button>
                  ) : userTxList.length > 0 ? (
                    <span>Загружено {userTxList.length} из {userTxTotal}</span>
                  ) : null}
                </div>
              </div>
            </DialogContent>
          </Dialog>

          {/* Promos Tab */}
          <TabsContent value="promos">
            <div className="space-y-6">
              {/* Referral Rally campaign — new section */}
              <AdminPromoRally />

              {/* Promo code creation */}
              <div className="glass-panel rounded-xl p-4 border border-green-500/20">
                <h3 className="font-unbounded text-sm font-bold text-white mb-3">Создать промокод</h3>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
                  <Input
                    data-testid="promo-name-input"
                    placeholder="Название"
                    value={promoName}
                    onChange={(e) => setPromoName(e.target.value)}
                    className="bg-white/5 border-white/10"
                  />
                  <Input
                    data-testid="promo-code-input"
                    placeholder="Код (авто)"
                    value={promoCode}
                    onChange={(e) => setPromoCode(e.target.value)}
                    className="bg-white/5 border-white/10"
                  />
                  <Input
                    data-testid="promo-amount-input"
                    type="number"
                    step="0.01"
                    max={MAX_PRICE_VALUE}
                    placeholder="Сумма $CITY"
                    value={promoAmount}
                    onChange={(e) => setPromoAmount(clampPriceValue(e.target.value))}
                    className="bg-white/5 border-white/10"
                  />
                  <Input
                    type="number"
                    placeholder="Макс. использований"
                    value={promoMaxUses}
                    onChange={(e) => setPromoMaxUses(e.target.value)}
                    className="bg-white/5 border-white/10"
                  />
                </div>
                <Button data-testid="create-promo-btn" onClick={handleCreatePromo} className="btn-cyber">
                  <Gift className="w-4 h-4 mr-1" /> Создать промокод
                </Button>
              </div>

              {/* Existing promos */}
              <div className="glass-panel rounded-xl p-4 border border-white/10">
                <h3 className="font-unbounded text-sm font-bold text-white mb-3">Промокоды ({promos.length})</h3>
                <p className="text-xs text-text-muted mb-3">Каждый пользователь может использовать промокод только 1 раз</p>
                <div className="space-y-2 max-h-64 overflow-y-auto">
                  {promos.map(p => (
                    <div key={p.id} className="flex items-center justify-between p-3 bg-white/5 rounded-lg text-sm">
                      <div>
                        <div className="font-mono text-cyber-cyan font-bold">{p.code || p.name}</div>
                        <div className="text-text-muted text-xs">{p.name}</div>
                      </div>
                      <div className="flex items-center gap-3">
                        <div className="text-right">
                          <div className="text-signal-amber font-bold">{formatCity(tonToCity(p.amount))} $CITY</div>
                          <div className="text-xs text-text-muted">Использовано: {p.current_uses || 0}/{p.max_uses || '∞'}</div>
                        </div>
                        <Button
                          size="sm"
                          variant="destructive"
                          className="h-8 w-8 p-0"
                          onClick={() => handleDeletePromo(p.id)}
                          data-testid={`delete-promo-${p.id}`}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </div>
                  ))}
                  {promos.length === 0 && (
                    <p className="text-text-muted text-center py-4">Нет промокодов</p>
                  )}
                </div>
              </div>

              {/* Telegram Bot Settings */}
              <div className="glass-panel rounded-xl p-4 border border-[#26A5E4]/20">
                <h3 className="font-unbounded text-sm font-bold text-white mb-3">Telegram бот</h3>
                <p className="text-text-muted text-xs mb-3">Настройка бота для уведомлений о выводах и бизнесах</p>
                
                <div className="space-y-4">
                  {/* Bot Username */}
                  <div>
                    <label className="text-xs text-text-muted mb-1 block">Username бота (без @)</label>
                    <div className="flex gap-2">
                      <Input
                        data-testid="telegram-bot-username"
                        type="text"
                        placeholder="YourBotName_bot"
                        value={telegramBotUsername}
                        onChange={(e) => setTelegramBotUsername(e.target.value)}
                        className="bg-white/5 border-white/10"
                      />
                      <Button onClick={handleSetTelegramBotUsername} className="bg-[#26A5E4] text-white">
                        Сохранить
                      </Button>
                    </div>
                    <p className="text-xs text-text-muted mt-1">Username бота можно найти в @BotFather после создания</p>
                  </div>
                  
                  {/* Bot Token */}
                  <div>
                    <label className="text-xs text-text-muted mb-1 block">Токен бота (от @BotFather)</label>
                    <div className="flex gap-2">
                      <Input
                        data-testid="telegram-bot-token"
                        type="password"
                        placeholder="1234567890:ABCdefGHI..."
                        value={telegramBotToken}
                        onChange={(e) => setTelegramBotToken(e.target.value)}
                        className="bg-white/5 border-white/10"
                      />
                      <Button onClick={handleSetTelegramWebhook} disabled={settingWebhook} className="bg-[#26A5E4] text-white">
                        {settingWebhook ? <RefreshCw className="w-4 h-4 animate-spin" /> : 'Сохранить'}
                      </Button>
                    </div>
                  </div>
                  
                  {/* Admin Telegram ID */}
                  <div>
                    <label className="text-xs text-text-muted mb-1 block">Telegram ID админа (для уведомлений о выводах)</label>
                    <div className="flex gap-2">
                      <Input
                        data-testid="admin-telegram-id"
                        type="text"
                        placeholder="123456789"
                        value={adminTelegramId}
                        onChange={(e) => setAdminTelegramId(e.target.value)}
                        className="bg-white/5 border-white/10"
                      />
                      <Button onClick={handleSetAdminTelegramId} className="bg-[#26A5E4] text-white">
                        Сохранить
                      </Button>
                    </div>
                    <p className="text-xs text-text-muted mt-1">Узнать ID: напишите @userinfobot в Telegram</p>
                  </div>

                  {/* Канал для публикации уведомлений */}
                  <div>
                    <label className="text-xs text-text-muted mb-1 block">Канал для публикаций (уведомления дублируются сюда)</label>
                    <div className="flex gap-2">
                      <Input
                        data-testid="telegram-channel-id"
                        type="text"
                        placeholder="@my_channel или -1001234567890"
                        value={telegramChannel}
                        onChange={(e) => setTelegramChannel(e.target.value)}
                        className="bg-white/5 border-white/10"
                      />
                      <Button onClick={handleSetTelegramChannel} disabled={savingChannel} data-testid="telegram-channel-save" className="bg-[#26A5E4] text-white">
                        {savingChannel ? <RefreshCw className="w-4 h-4 animate-spin" /> : 'Сохранить'}
                      </Button>
                    </div>
                    <p className="text-xs text-text-muted mt-1">Бот должен быть <b>администратором</b> канала. Каждое опубликованное уведомление отправляется в этот канал в том же виде, что и в бот.</p>
                  </div>

                  {/* URL открытия приложения (Block 1: configurable button URL) */}
                  <div>
                    <label className="text-xs text-text-muted mb-1 block">URL открытия приложения</label>
                    <div className="flex gap-2">
                      <Input
                        data-testid="telegram-app-url"
                        type="text"
                        placeholder="https://gramcity.games/trading"
                        value={telegramAppUrl}
                        onChange={(e) => setTelegramAppUrl(e.target.value)}
                        className="bg-white/5 border-white/10"
                      />
                      <Button onClick={handleSetTelegramAppUrl} disabled={savingAppUrl} className="bg-[#26A5E4] text-white">
                        {savingAppUrl ? <RefreshCw className="w-4 h-4 animate-spin" /> : 'Сохранить'}
                      </Button>
                    </div>
                    <p className="text-xs text-text-muted mt-1">Адрес, на который ведёт кнопка «🎮 Открыть игру» под уведомлениями в боте.</p>
                  </div>
                  
                  {/* Auto Webhook Setup */}
                  <div className="pt-2 border-t border-white/10">
                    <Button onClick={handleAutoSetupWebhook} className="w-full bg-gradient-to-r from-[#26A5E4] to-[#0088cc] text-white">
                      🔄 Автонастройка Webhook
                    </Button>
                    <p className="text-xs text-text-muted mt-1 text-center">Автоматически настроит webhook для получения команд бота</p>
                  </div>
                </div>
              </div>
            </div>
          </TabsContent>

          {/* Announcements Tab */}
          <TabsContent value="announcements">
            <Tabs defaultValue="ann-announcements" className="w-full">
              <TabsList className="mb-4 bg-black/30">
                <TabsTrigger value="ann-announcements" data-testid="admin-subtab-announcements">Объявления</TabsTrigger>
                <TabsTrigger value="ann-faq" data-testid="admin-subtab-faq">FAQ</TabsTrigger>
                <TabsTrigger value="ann-roadmap" data-testid="admin-subtab-roadmap">Дорожная карта</TabsTrigger>
              </TabsList>
              <TabsContent value="ann-announcements">
            <div className="glass-panel rounded-2xl p-6">
              <div className="flex items-center justify-between mb-6">
                <h2 className="font-unbounded text-lg font-bold text-text-main">
                  {t('announcements')}
                </h2>
                
                <Dialog>
                  <DialogTrigger asChild>
                    <Button className="btn-cyber">
                      <Bell className="w-4 h-4 mr-2" />
                      {t('createAnnouncement')}
                    </Button>
                  </DialogTrigger>
                  <DialogContent className="glass-panel border-grid-border text-text-main max-w-lg max-h-[85vh] overflow-y-auto">
                    <DialogHeader>
                      <DialogTitle data-testid="announcement-dialog-title">
                        {announcementMulti && announcementLangs.length > 0
                          ? `Публикация · ${(BROADCAST_LANGS.find(l => l.code === announcementLangs[announcementLangIdx])?.label) || announcementLangs[announcementLangIdx]?.toUpperCase()} (${announcementLangIdx + 1}/${announcementLangs.length})`
                          : 'Создать объявление'}
                      </DialogTitle>
                    </DialogHeader>
                    <div className="space-y-4">
                      {/* Mode toggle: single vs multi-language */}
                      <div className="space-y-2 border border-white/10 rounded-lg p-3 bg-white/[0.02]">
                        <p className="text-xs uppercase tracking-widest text-text-muted">Языки публикации</p>
                        <div className="flex gap-2">
                          <Button
                            type="button"
                            size="sm"
                            variant={!announcementMulti ? 'default' : 'outline'}
                            className={!announcementMulti ? 'btn-cyber flex-1' : 'flex-1 border-grid-border'}
                            onClick={() => { setAnnouncementMulti(false); setAnnouncementLangIdx(0); }}
                            data-testid="announcement-mode-single"
                          >
                            Один язык
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant={announcementMulti ? 'default' : 'outline'}
                            className={announcementMulti ? 'btn-cyber flex-1' : 'flex-1 border-grid-border'}
                            onClick={() => { setAnnouncementMulti(true); setAnnouncementLangIdx(0); }}
                            data-testid="announcement-mode-multi"
                          >
                            Несколько языков
                          </Button>
                        </div>
                        {announcementMulti && (
                          <>
                            <p className="text-[11px] text-text-muted mt-2">
                              Выберите языки — пользователи получат публикацию на языке, выбранном ими в боте / в профиле.
                            </p>
                            <div className="flex flex-wrap gap-2">
                              {BROADCAST_LANGS.map((l) => {
                                const active = announcementLangs.includes(l.code);
                                return (
                                  <button
                                    key={l.code}
                                    type="button"
                                    data-testid={`announcement-lang-toggle-${l.code}`}
                                    onClick={() => {
                                      setAnnouncementLangs((prev) => {
                                        const next = prev.includes(l.code) ? prev.filter(x => x !== l.code) : [...prev, l.code];
                                        setAnnouncementLangIdx(0);
                                        return next;
                                      });
                                    }}
                                    className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-all ${active ? 'bg-cyan-500/20 text-cyan-300 border-cyan-500/50' : 'bg-gray-800/40 text-gray-400 border-gray-700 hover:border-white/20'}`}
                                  >
                                    {l.label}
                                  </button>
                                );
                              })}
                            </div>
                          </>
                        )}
                      </div>

                      {/* Multi-language per-language editor */}
                      {announcementMulti && announcementLangs.length > 0 && (
                        (() => {
                          const currentLang = announcementLangs[announcementLangIdx];
                          const currentTr = getTranslation(currentLang);
                          const isLast = announcementLangIdx === announcementLangs.length - 1;
                          return (
                            <>
                              <div className="rounded-lg border border-cyan-500/30 bg-cyan-500/[0.03] p-2 text-xs text-cyan-200 text-center" data-testid="announcement-current-lang-banner">
                                Публикация для: <b>{(BROADCAST_LANGS.find(l => l.code === currentLang)?.label) || currentLang}</b>
                                {' '}({announcementLangIdx + 1} из {announcementLangs.length})
                              </div>
                              <Input
                                placeholder="Заголовок (опционально)"
                                value={currentTr.title || ''}
                                onChange={(e) => setTranslationField(currentLang, 'title', e.target.value)}
                                className="bg-panel border-grid-border"
                                data-testid={`announcement-title-input-${currentLang}`}
                              />
                              <textarea
                                placeholder="Сообщение (поддерживается HTML: <b>, <i>, <a>)"
                                value={currentTr.message || ''}
                                onChange={(e) => setTranslationField(currentLang, 'message', e.target.value)}
                                className="w-full h-32 bg-panel border border-grid-border rounded-lg p-3 text-text-main"
                                data-testid={`announcement-message-input-${currentLang}`}
                              />
                              <div className="space-y-2 border border-white/10 rounded-lg p-3 bg-white/[0.02]">
                                <p className="text-xs uppercase tracking-widest text-text-muted">Изображение (опционально)</p>
                                <Input
                                  placeholder="https://… (URL картинки)"
                                  value={currentTr.image_url || ''}
                                  onChange={(e) => setTranslationField(currentLang, 'image_url', e.target.value)}
                                  className="bg-panel border-grid-border"
                                  data-testid={`announcement-image-url-${currentLang}`}
                                />
                                <div className="flex items-center gap-2">
                                  <label className="cursor-pointer text-xs px-3 py-1.5 rounded-lg bg-cyan-500/10 text-cyan-300 border border-cyan-500/30 hover:bg-cyan-500/20">
                                    {currentTr._uploading ? '…' : '📁 Или загрузить файл'}
                                    <input
                                      type="file"
                                      accept="image/*"
                                      className="hidden"
                                      data-testid={`announcement-image-upload-${currentLang}`}
                                      onChange={(e) => uploadAnnouncementImageForLang(currentLang, e.target.files?.[0])}
                                    />
                                  </label>
                                  {currentTr.image_url && (
                                    <Button variant="outline" size="sm" className="text-xs border-red-500/30 text-red-400 hover:bg-red-500/10" onClick={() => setTranslationField(currentLang, 'image_url', '')}>
                                      Убрать
                                    </Button>
                                  )}
                                </div>
                                {currentTr.image_url && (
                                  <img
                                    src={currentTr.image_url}
                                    alt="preview"
                                    className="max-h-32 rounded-lg border border-white/10 mt-1 object-cover"
                                  />
                                )}
                              </div>
                              {/* Inline buttons per-language */}
                              <div className="space-y-2 border border-white/10 rounded-lg p-3 bg-white/[0.02]">
                                <div className="flex items-center justify-between">
                                  <p className="text-xs uppercase tracking-widest text-text-muted">
                                    Inline-кнопки в Telegram (опционально)
                                  </p>
                                  <Button
                                    type="button"
                                    variant="outline"
                                    size="sm"
                                    className="text-xs border-cyan-500/30 text-cyan-300 hover:bg-cyan-500/10"
                                    onClick={() => setTranslationField(currentLang, 'buttons', [...(currentTr.buttons || []), { text: '', url: '' }])}
                                    disabled={(currentTr.buttons || []).length >= 8}
                                    data-testid={`announcement-add-button-${currentLang}`}
                                  >
                                    + Кнопка
                                  </Button>
                                </div>
                                {(currentTr.buttons || []).map((b, idx) => (
                                  <div key={idx} className="flex gap-2 items-center">
                                    <Input
                                      placeholder="Текст"
                                      value={b.text}
                                      onChange={(e) => {
                                        const next = [...(currentTr.buttons || [])];
                                        next[idx] = { ...next[idx], text: e.target.value };
                                        setTranslationField(currentLang, 'buttons', next);
                                      }}
                                      className="bg-panel border-grid-border flex-1"
                                    />
                                    <Input
                                      placeholder="https://…"
                                      value={b.url}
                                      onChange={(e) => {
                                        const next = [...(currentTr.buttons || [])];
                                        next[idx] = { ...next[idx], url: e.target.value };
                                        setTranslationField(currentLang, 'buttons', next);
                                      }}
                                      className="bg-panel border-grid-border flex-[2]"
                                    />
                                    <Button
                                      variant="outline"
                                      size="sm"
                                      className="text-xs border-red-500/30 text-red-400 hover:bg-red-500/10"
                                      onClick={() => setTranslationField(currentLang, 'buttons', (currentTr.buttons || []).filter((_, i) => i !== idx))}
                                    >
                                      ✕
                                    </Button>
                                  </div>
                                ))}
                              </div>
                              {/* Prev/Next nav for multi-language */}
                              <div className="flex gap-2">
                                <Button
                                  type="button"
                                  variant="outline"
                                  size="sm"
                                  className="border-grid-border"
                                  disabled={announcementLangIdx === 0}
                                  onClick={() => setAnnouncementLangIdx((i) => Math.max(0, i - 1))}
                                  data-testid="announcement-prev-lang"
                                >
                                  ◀ Назад
                                </Button>
                                {!isLast && (
                                  <Button
                                    type="button"
                                    className="btn-cyber flex-1"
                                    onClick={() => {
                                      const msg = (currentTr.message || '').trim();
                                      if (!msg) {
                                        toast.error('Заполните сообщение для этого языка');
                                        return;
                                      }
                                      setAnnouncementLangIdx((i) => Math.min(announcementLangs.length - 1, i + 1));
                                    }}
                                    data-testid="announcement-next-lang"
                                  >
                                    Дальше ▶
                                  </Button>
                                )}
                              </div>
                            </>
                          );
                        })()
                      )}

                      {/* Single-language editor (legacy) */}
                      {!announcementMulti && (
                        <>
                          <Input
                            placeholder="Заголовок (опционально)"
                            value={announcementTitle}
                            onChange={(e) => setAnnouncementTitle(e.target.value)}
                            className="bg-panel border-grid-border"
                            data-testid="announcement-title-input"
                          />
                          <textarea
                            placeholder="Сообщение (поддерживается HTML: <b>, <i>, <a>)"
                            value={announcementMessage}
                            onChange={(e) => setAnnouncementMessage(e.target.value)}
                            className="w-full h-32 bg-panel border border-grid-border rounded-lg p-3 text-text-main"
                            data-testid="announcement-message-input"
                          />
                          
                          {/* Image: URL or upload */}
                          <div className="space-y-2 border border-white/10 rounded-lg p-3 bg-white/[0.02]">
                            <p className="text-xs uppercase tracking-widest text-text-muted">Изображение (опционально)</p>
                            <Input
                              placeholder="https://… (URL картинки)"
                              value={announcementImageUrl}
                              onChange={(e) => setAnnouncementImageUrl(e.target.value)}
                              className="bg-panel border-grid-border"
                              data-testid="announcement-image-url"
                            />
                            <div className="flex items-center gap-2">
                              <label className="cursor-pointer text-xs px-3 py-1.5 rounded-lg bg-cyan-500/10 text-cyan-300 border border-cyan-500/30 hover:bg-cyan-500/20">
                                {announcementUploading ? '…' : '📁 Или загрузить файл'}
                                <input
                                  type="file"
                                  accept="image/*"
                                  className="hidden"
                                  data-testid="announcement-image-upload"
                                  onChange={(e) => uploadAnnouncementImage(e.target.files?.[0])}
                                />
                              </label>
                              {announcementImageUrl && (
                                <Button variant="outline" size="sm" className="text-xs border-red-500/30 text-red-400 hover:bg-red-500/10" onClick={() => setAnnouncementImageUrl('')}>
                                  Убрать
                                </Button>
                              )}
                            </div>
                            {announcementImageUrl && (
                              <img
                                src={announcementImageUrl}
                                alt="preview"
                                className="max-h-32 rounded-lg border border-white/10 mt-1 object-cover"
                              />
                            )}
                          </div>
                          
                          {/* Inline buttons */}
                          <div className="space-y-2 border border-white/10 rounded-lg p-3 bg-white/[0.02]">
                            <div className="flex items-center justify-between">
                              <p className="text-xs uppercase tracking-widest text-text-muted">
                                Inline-кнопки в Telegram (опционально)
                              </p>
                              <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                className="text-xs border-cyan-500/30 text-cyan-300 hover:bg-cyan-500/10"
                                onClick={() => setAnnouncementButtons([...(announcementButtons || []), { text: '', url: '' }])}
                                disabled={(announcementButtons || []).length >= 8}
                                data-testid="announcement-add-button"
                              >
                                + Кнопка
                              </Button>
                            </div>
                            {(announcementButtons || []).map((b, idx) => (
                              <div key={idx} className="flex gap-2 items-center" data-testid={`announcement-button-row-${idx}`}>
                                <Input
                                  placeholder="Текст"
                                  value={b.text}
                                  onChange={(e) => {
                                    const next = [...announcementButtons];
                                    next[idx] = { ...next[idx], text: e.target.value };
                                    setAnnouncementButtons(next);
                                  }}
                                  className="bg-panel border-grid-border flex-1"
                                />
                                <Input
                                  placeholder="https://…"
                                  value={b.url}
                                  onChange={(e) => {
                                    const next = [...announcementButtons];
                                    next[idx] = { ...next[idx], url: e.target.value };
                                    setAnnouncementButtons(next);
                                  }}
                                  className="bg-panel border-grid-border flex-[2]"
                                />
                                <Button
                                  variant="outline"
                                  size="sm"
                                  className="text-xs border-red-500/30 text-red-400 hover:bg-red-500/10"
                                  onClick={() => setAnnouncementButtons(announcementButtons.filter((_, i) => i !== idx))}
                                >
                                  ✕
                                </Button>
                              </div>
                            ))}
                          </div>
                        </>
                      )}
                      
                      {/* Publish timing: now or scheduled (MSK) */}
                      <div className="space-y-2 border border-white/10 rounded-lg p-3 bg-white/[0.02]">
                        <p className="text-xs uppercase tracking-widest text-text-muted">Время публикации</p>
                        <div className="flex gap-2">
                          <Button
                            type="button"
                            size="sm"
                            variant={announcementMode === 'now' ? 'default' : 'outline'}
                            className={announcementMode === 'now' ? 'btn-cyber flex-1' : 'flex-1 border-grid-border'}
                            onClick={() => setAnnouncementMode('now')}
                            data-testid="announcement-mode-now"
                          >
                            Сейчас
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant={announcementMode === 'scheduled' ? 'default' : 'outline'}
                            className={announcementMode === 'scheduled' ? 'btn-cyber flex-1' : 'flex-1 border-grid-border'}
                            onClick={() => setAnnouncementMode('scheduled')}
                            data-testid="announcement-mode-scheduled"
                          >
                            Запланировать
                          </Button>
                        </div>
                        {announcementMode === 'scheduled' && (
                          <Input
                            type="datetime-local"
                            value={announcementScheduledAt}
                            onChange={(e) => setAnnouncementScheduledAt(e.target.value)}
                            className="bg-panel border-grid-border"
                            data-testid="announcement-scheduled-at"
                          />
                        )}
                      </div>

                      {/* Publish button — text depends on mode & last-language state */}
                      {(() => {
                        const multi = announcementMulti && announcementLangs.length > 0;
                        const isLast = !multi || announcementLangIdx === announcementLangs.length - 1;
                        if (multi && !isLast) return null;
                        let label;
                        if (multi) {
                          label = announcementMode === 'scheduled'
                            ? `Запланировать ${announcementLangs.length} постов`
                            : `Опубликовать ${announcementLangs.length} постов`;
                        } else {
                          label = announcementMode === 'scheduled' ? 'Запланировать' : 'Опубликовать и разослать';
                        }
                        return (
                          <Button onClick={createAnnouncement} className="w-full btn-cyber" data-testid="announcement-publish-btn">
                            {label}
                          </Button>
                        );
                      })()}
                    </div>
                  </DialogContent>
                </Dialog>
              </div>
              
              <div className="space-y-3">
                {(announcementsExpanded ? announcementsAll : announcements.slice(0, 1)).map((ann) => (
                  <div
                    key={ann.id}
                    className="glass-panel rounded-lg p-4"
                    data-testid={`announcement-item-${ann.id}`}
                  >
                    <div className="flex items-start justify-between gap-3 mb-2">
                      <div className="font-unbounded text-text-main">
                        {ann.title}
                      </div>
                      {ann.status === 'scheduled' && (
                        <span className="text-xs px-2 py-1 rounded bg-amber-500/20 text-amber-400 font-bold whitespace-nowrap" data-testid="announcement-status-scheduled">
                          ⏳ Запланировано
                        </span>
                      )}
                    </div>
                    <div className="text-text-muted text-sm mb-2">
                      {ann.message}
                    </div>
                    {ann.delivery && (() => {
                      const d = ann.delivery, done = d.sent + d.blocked + d.not_found + d.failed;
                      const pct = d.telegram_total ? Math.min(100, Math.round((done / d.telegram_total) * 100)) : 100;
                      return (
                        <div className="mb-2 rounded-lg border border-white/10 bg-black/20 p-2.5 text-xs space-y-1.5" data-testid={`announcement-delivery-${ann.id}`}>
                          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                            <span className="font-bold text-white">Telegram: доставлено {d.sent} из {d.telegram_total}</span>
                            {d.status === 'running' && <span className="text-cyan-300">рассылка идёт… {pct}%</span>}
                            {d.status === 'done' && <span className="text-emerald-400">готово</span>}
                            <span className="text-text-muted">в приложении: {d.in_app}</span>
                          </div>
                          <div className="h-1.5 rounded-full bg-white/10 overflow-hidden">
                            <div className="h-full bg-emerald-400" style={{ width: `${d.telegram_total ? (d.sent / d.telegram_total) * 100 : 0}%` }} />
                          </div>
                          {(d.blocked + d.not_found + d.failed) > 0 && (
                            <div className="text-text-muted">заблокировали бота: {d.blocked} · чат не найден: {d.not_found} · ошибки: {d.failed}</div>
                          )}
                        </div>
                      );
                    })()}
                    <div className="flex items-center justify-between">
                      <div className="text-xs text-text-muted">
                        {ann.status === 'scheduled' && ann.scheduled_at
                          ? `Публикация: ${utcIsoToMskLocal(ann.scheduled_at).replace('T', ' ')} МСК`
                          : formatDate(ann.created_at)}
                      </div>
                      {ann.status === 'scheduled' && (
                        <Button
                          variant="outline"
                          size="sm"
                          className="text-xs border-red-500/30 text-red-400 hover:bg-red-500/10"
                          onClick={() => deleteAnnouncement(ann.id)}
                          data-testid={`announcement-cancel-${ann.id}`}
                        >
                          <Trash2 className="w-3 h-3 mr-1" /> Отменить
                        </Button>
                      )}
                    </div>
                  </div>
                ))}

                {announcements.length === 0 && (
                  <div className="text-center text-text-muted text-sm py-6" data-testid="announcements-empty">
                    Объявлений пока нет
                  </div>
                )}

                {/* Show-all / hide controls — only the latest is loaded by default */}
                {!announcementsExpanded && announcementsTotal > 1 && (
                  <Button
                    variant="outline"
                    className="w-full border-white/10 text-cyber-cyan hover:bg-cyber-cyan/10"
                    onClick={loadAllAnnouncements}
                    disabled={announcementsLoadingAll}
                    data-testid="announcements-show-all-btn"
                  >
                    {announcementsLoadingAll
                      ? <><Loader2 className="w-4 h-4 mr-2 animate-spin" /> Загрузка…</>
                      : <>Показать все ({announcementsTotal})</>}
                  </Button>
                )}
                {announcementsExpanded && (
                  <Button
                    variant="outline"
                    className="w-full border-white/10 text-text-muted hover:bg-white/5"
                    onClick={() => setAnnouncementsExpanded(false)}
                    data-testid="announcements-hide-btn"
                  >
                    Скрыть
                  </Button>
                )}
              </div>
            </div>
              </TabsContent>
              <TabsContent value="ann-faq">
                <AdminRulesSection />
              </TabsContent>
              <TabsContent value="ann-roadmap">
                <AdminRoadmapSection />
              </TabsContent>
            </Tabs>
          </TabsContent>

          {/* DATA TAB - Players & Prices */}
          <TabsContent value="minigames">
            <MinigamesPanel token={localStorage.getItem('token') || localStorage.getItem('ton_city_token')} />
          </TabsContent>

          <TabsContent value="rental">
            <RentalPanel token={localStorage.getItem('token') || localStorage.getItem('ton_city_token')} />
          </TabsContent>

          <TabsContent value="city-pass">
            <CityPassPanel token={localStorage.getItem('token') || localStorage.getItem('ton_city_token')} />
          </TabsContent>

          <TabsContent value="reconciliation">
            <ReconciliationPanel token={localStorage.getItem('token') || localStorage.getItem('ton_city_token')} />
          </TabsContent>

          <TabsContent value="leagues">
            <LeaguesPanel token={localStorage.getItem('token') || localStorage.getItem('ton_city_token')} />
          </TabsContent>

          <TabsContent value="comeback">
            <ComebackPanel token={localStorage.getItem('token') || localStorage.getItem('ton_city_token')} />
          </TabsContent>

          <TabsContent value="market-maker">
            <MarketMakerPanel token={localStorage.getItem('token') || localStorage.getItem('ton_city_token')} />
          </TabsContent>

          <TabsContent value="retention">
            <RetentionPanel token={localStorage.getItem('token') || localStorage.getItem('ton_city_token')} />
          </TabsContent>

          <TabsContent value="data">
            <AdminDataPanel token={token} />
          </TabsContent>

          {/* CREDITS TAB */}
          <TabsContent value="credits">
            <div className="space-y-6">
              {/* Government rate settings */}
              <div className="glass-panel rounded-xl p-4 border border-amber-500/20">
                <h3 className="font-unbounded text-sm font-bold text-white mb-3">Ставка государственного кредита</h3>
                <div className="flex items-center gap-3">
                  <Input
                    data-testid="gov-rate-input"
                    type="number"
                    min="1"
                    max="100"
                    value={govRate}
                    onChange={(e) => setGovRate(e.target.value)}
                    className="w-24 bg-white/5 border-white/10"
                    placeholder="%"
                  />
                  <span className="text-text-muted">%</span>
                  <Button onClick={handleUpdateGovRate} size="sm" className="btn-cyber">
                    <Check className="w-4 h-4 mr-1" /> Сохранить
                  </Button>
                  <span className="text-text-muted text-xs">Текущая: {(creditSettings.government_interest_rate * 100).toFixed(0)}%</span>
                </div>
              </div>

              {/* Active credits with FULL user ID */}
              <div className="glass-panel rounded-xl p-4 border border-white/10">
                <h3 className="font-unbounded text-sm font-bold text-white mb-3">
                  Активные кредиты ({credits.filter(c => ['active','overdue'].includes(c.status)).length})
                </h3>
                <div className="space-y-3 max-h-96 overflow-y-auto">
                  {credits.filter(c => ['active','overdue'].includes(c.status)).map(c => (
                    <div key={c.id} className={`p-4 bg-white/5 rounded-lg text-sm border ${c.status === 'overdue' ? 'border-red-500/30 bg-red-500/5' : 'border-white/10'}`}>
                      <div className="flex items-center justify-between mb-3">
                        <div className="flex items-center gap-2">
                          <span className={`text-xs px-2 py-1 rounded font-bold ${c.status === 'overdue' ? 'bg-red-500/20 text-red-400' : 'bg-amber-500/20 text-amber-400'}`}>
                            {c.status === 'overdue' ? '⚠️ ПРОСРОЧЕН' : '✓ Активный'}
                          </span>
                          <span className="text-text-muted">{c.lender_name}</span>
                        </div>
                        {c.status === 'overdue' && c.seized_building && (
                          <span className="text-xs px-2 py-1 bg-purple-500/20 text-purple-400 rounded">
                            🏢 Здание изъято
                          </span>
                        )}
                      </div>
                      
                      {/* Full borrower ID with copy */}
                      <div className="mb-3 flex items-center gap-2">
                        <span className="text-text-muted text-xs">ID заёмщика:</span>
                        <code 
                          className="text-white font-mono text-xs bg-white/10 px-2 py-1 rounded cursor-pointer hover:bg-white/20 transition-colors"
                          onClick={() => {
                            navigator.clipboard.writeText(c.borrower_id);
                            toast.success('ID скопирован!');
                          }}
                          title="Нажмите для копирования"
                        >
                          {c.borrower_id}
                        </code>
                      </div>
                      
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
                        <div className="bg-white/5 p-2 rounded">
                          <span className="text-text-muted block">Сумма</span>
                          <span className="text-white font-bold">{formatCity(tonToCity(c.amount))} $CITY</span>
                        </div>
                        <div className="bg-white/5 p-2 rounded">
                          <span className="text-text-muted block">Ставка</span>
                          <span className="text-white font-bold">{(c.interest_rate*100).toFixed(0)}%</span>
                        </div>
                        <div className="bg-white/5 p-2 rounded">
                          <span className="text-text-muted block">Остаток</span>
                          <span className="text-amber-400 font-bold">{formatCity(tonToCity(c.remaining || 0))} $CITY</span>
                        </div>
                        <div className="bg-white/5 p-2 rounded">
                          <span className="text-text-muted block">Удержание</span>
                          <span className="text-white font-bold">{(c.salary_deduction_percent*100).toFixed(0)}%</span>
                        </div>
                      </div>
                      
                      {/* Seized building info */}
                      {c.status === 'overdue' && c.seized_building && (
                        <div className="mt-3 p-2 bg-purple-500/10 border border-purple-500/20 rounded text-xs">
                          <span className="text-purple-400">Изъятое здание: </span>
                          <span className="text-white">{c.seized_building.type} (Level {c.seized_building.level})</span>
                          <span className="text-text-muted ml-2">→ Выставлено на торги</span>
                        </div>
                      )}
                    </div>
                  ))}
                  {credits.filter(c => ['active','overdue'].includes(c.status)).length === 0 && (
                    <p className="text-text-muted text-center py-8">Нет активных кредитов</p>
                  )}
                </div>
              </div>
              
              {/* Collateral businesses (Block 6) */}
              <div className="glass-panel rounded-xl p-4 border border-purple-500/20" data-testid="admin-collateral-section">
                <h3 className="font-unbounded text-sm font-bold text-white mb-3 flex items-center gap-2">
                  📋 Залоговые бизнесы
                  <span className="text-xs text-text-muted font-normal">({collateralList.length})</span>
                </h3>
                <p className="text-xs text-text-muted mb-3">
                  Бизнесы, заложенные под активные/просроченные кредиты. После 7 дней просрочки автоматически переходят государству и выставляются на продажу по 80% от залоговой стоимости.
                </p>

                {collateralList.length === 0 ? (
                  <p className="text-text-muted text-center py-6 text-sm">Залоговых бизнесов нет</p>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs" data-testid="admin-collateral-table">
                      <thead>
                        <tr className="border-b border-white/10 text-text-muted">
                          <th className="text-left py-2 px-2">Бизнес</th>
                          <th className="text-left py-2 px-2">Владелец</th>
                          <th className="text-left py-2 px-2">Кредитор</th>
                          <th className="text-right py-2 px-2">Остаток долга</th>
                          <th className="text-right py-2 px-2">До изъятия</th>
                          <th className="text-center py-2 px-2">Статус</th>
                        </tr>
                      </thead>
                      <tbody>
                        {collateralList.map((row) => {
                          const isOverdue = row.status === 'overdue';
                          const daysLeft = row.days_until_seizure;
                          return (
                            <tr key={row.credit_id} className="border-b border-white/5 hover:bg-white/5">
                              <td className="py-2 px-2">
                                <div className="text-white font-semibold">{row.business_type}</div>
                                <div className="text-text-muted">Ур. {row.business_level}</div>
                              </td>
                              <td className="py-2 px-2">
                                <div className="text-white">{row.borrower_username || '—'}</div>
                                <code
                                  className="text-text-muted text-[10px] cursor-pointer hover:text-cyber-cyan"
                                  onClick={() => {
                                    navigator.clipboard.writeText(row.borrower_id);
                                    toast.success('ID скопирован');
                                  }}
                                  title="Копировать ID"
                                >
                                  {row.borrower_id ? `${row.borrower_id.slice(0, 8)}…` : ''}
                                </code>
                              </td>
                              <td className="py-2 px-2 text-white">{row.lender_name || '—'}</td>
                              <td className="py-2 px-2 text-right">
                                <div className="text-amber-400 font-bold">{(row.remaining || 0).toFixed(2)} TON</div>
                                <div className="text-text-muted text-[10px]">из {(row.total_debt || 0).toFixed(2)}</div>
                              </td>
                              <td className="py-2 px-2 text-right">
                                {daysLeft === null || daysLeft === undefined ? (
                                  <span className="text-text-muted">—</span>
                                ) : daysLeft <= 0 ? (
                                  <span className="text-red-400 font-bold">Сегодня</span>
                                ) : (
                                  <span className={daysLeft <= 2 ? 'text-red-400 font-bold' : 'text-amber-400'}>
                                    {daysLeft} дн.
                                  </span>
                                )}
                              </td>
                              <td className="py-2 px-2 text-center">
                                <span className={`text-[10px] px-2 py-1 rounded font-bold ${
                                  isOverdue ? 'bg-red-500/20 text-red-400' : 'bg-emerald-500/20 text-emerald-400'
                                }`}>
                                  {isOverdue ? '⚠ ПРОСРОЧЕН' : '✓ АКТИВЕН'}
                                </span>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              {/* Seized businesses (Изъятые) */}
              <div className="glass-panel rounded-xl p-4 border border-red-500/20" data-testid="admin-seized-section">
                <h3 className="font-unbounded text-sm font-bold text-white mb-3 flex items-center gap-2">
                  ⚖️ Изъятые
                  <span className="text-xs text-text-muted font-normal">({seizedList.length})</span>
                </h3>
                <p className="text-xs text-text-muted mb-3">
                  Бизнесы, изъятые системой (прочность 0% 7 дней или дефолт по кредиту) и выставленные на маркетплейс от имени GRAM CITY. Владелец не может снять их с продажи. Цену можно изменить; если не продан — можно вернуть владельцу.
                </p>
                {seizedList.length === 0 ? (
                  <p className="text-text-muted text-center py-6 text-sm">Изъятых бизнесов нет</p>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs" data-testid="admin-seized-table">
                      <thead>
                        <tr className="border-b border-white/10 text-text-muted">
                          <th className="text-left py-2 px-2">Бизнес / ID</th>
                          <th className="text-left py-2 px-2">Причина</th>
                          <th className="text-left py-2 px-2">Дата изъятия</th>
                          <th className="text-left py-2 px-2">Бывший владелец</th>
                          <th className="text-right py-2 px-2">Цена (TON)</th>
                          <th className="text-center py-2 px-2">Статус / Покупатель</th>
                          <th className="text-center py-2 px-2">Действие</th>
                        </tr>
                      </thead>
                      <tbody>
                        {seizedList.map((row) => (
                          <tr key={row.listing_id} className="border-b border-white/5" data-testid={`seized-row-${row.business_id}`}>
                            <td className="py-2 px-2 text-white">
                              <div className="font-bold">{row.business?.name?.ru || row.business?.name?.en || row.business?.type || '—'} · Lv{row.business?.level || 1}</div>
                              <div className="text-text-muted text-[10px]">{row.business_id}</div>
                              <div className="text-text-muted text-[10px]">[{row.x}, {row.y}] · durability {row.business_full?.durability ?? '—'}%</div>
                            </td>
                            <td className="py-2 px-2">
                              <span className={`text-[10px] px-2 py-1 rounded font-bold ${row.seizure_reason === 'credit_default' ? 'bg-purple-500/20 text-purple-300' : 'bg-red-500/20 text-red-300'}`}>
                                {row.seizure_reason === 'credit_default' ? 'Кредит' : 'Прочность'}
                              </span>
                            </td>
                            <td className="py-2 px-2 text-text-muted">{row.seized_at ? new Date(row.seized_at).toLocaleString('ru-RU') : '—'}</td>
                            <td className="py-2 px-2 text-white">{row.former_owner_username || row.former_owner_id || '—'}</td>
                            <td className="py-2 px-2 text-right">
                              {row.sold ? (
                                <span className="text-amber-400 font-bold">{(row.price || 0).toFixed(2)}</span>
                              ) : (
                                <div className="flex items-center gap-1 justify-end">
                                  <input
                                    type="number" step="0.01" defaultValue={(row.price || 0).toFixed(2)}
                                    data-testid={`seized-price-input-${row.business_id}`}
                                    className="w-20 bg-black/40 border border-white/20 rounded px-1 py-0.5 text-right text-white"
                                    id={`seized-price-${row.listing_id}`}
                                  />
                                  <button
                                    data-testid={`seized-save-price-${row.business_id}`}
                                    className="text-[10px] px-2 py-1 rounded bg-cyber-cyan/20 text-cyber-cyan hover:bg-cyber-cyan/30"
                                    onClick={async () => {
                                      const val = parseFloat(document.getElementById(`seized-price-${row.listing_id}`).value);
                                      try {
                                        await axios.post(`${API}/admin/credits/seized/${row.listing_id}/price`, { price: val }, { headers: { Authorization: `Bearer ${token}` } });
                                        toast.success('Цена обновлена');
                                        loadData();
                                      } catch (e) { toast.error(e.response?.data?.detail || 'Ошибка'); }
                                    }}
                                  >✔</button>
                                </div>
                              )}
                            </td>
                            <td className="py-2 px-2 text-center">
                              {row.sold ? (
                                <span className="text-[10px] text-emerald-300">Куплен: <b>{row.buyer_username || row.buyer_id}</b></span>
                              ) : (
                                <span className="text-[10px] px-2 py-1 rounded bg-amber-500/20 text-amber-300 font-bold">НА ПРОДАЖЕ</span>
                              )}
                            </td>
                            <td className="py-2 px-2 text-center">
                              {row.sold ? (
                                <span className="text-text-muted text-[10px]">—</span>
                              ) : (
                                <button
                                  data-testid={`seized-return-${row.business_id}`}
                                  className="text-[10px] px-2 py-1 rounded bg-green-500/20 text-green-300 hover:bg-green-500/30"
                                  onClick={async () => {
                                    try {
                                      await axios.post(`${API}/admin/credits/seized/${row.listing_id}/return`, {}, { headers: { Authorization: `Bearer ${token}` } });
                                      toast.success('Бизнес возвращён владельцу');
                                      loadData();
                                    } catch (e) { toast.error(e.response?.data?.detail || 'Ошибка'); }
                                  }}
                                >Вернуть владельцу</button>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>


              {/* History of paid credits */}
              <div className="glass-panel rounded-xl p-4 border border-green-500/20">
                <h3 className="font-unbounded text-sm font-bold text-white mb-3">
                  Погашенные кредиты ({credits.filter(c => c.status === 'paid').length})
                </h3>
                <div className="space-y-2 max-h-48 overflow-y-auto">
                  {credits.filter(c => c.status === 'paid').map(c => (
                    <div key={c.id} className="p-2 bg-green-500/5 rounded-lg text-xs border border-green-500/20">
                      <div className="flex justify-between items-center">
                        <code 
                          className="text-white font-mono cursor-pointer hover:text-green-400"
                          onClick={() => {
                            navigator.clipboard.writeText(c.borrower_id);
                            toast.success('ID скопирован!');
                          }}
                        >
                          {c.borrower_id}
                        </code>
                        <span className="text-green-400">✓ {formatCity(tonToCity(c.amount))} $CITY погашено</span>
                      </div>
                    </div>
                  ))}
                  {credits.filter(c => c.status === 'paid').length === 0 && (
                    <p className="text-text-muted text-center py-4">Нет погашенных кредитов</p>
                  )}
                </div>
              </div>
            </div>
          </TabsContent>


          {/* Tax Settings Tab */}
          <TabsContent value="taxes">
            <div className="glass-panel rounded-2xl p-6">
              <h2 className="font-unbounded text-lg font-bold text-text-main mb-6">
                Налоговые настройки
              </h2>
              
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="space-y-2">
                  <label className="text-sm text-text-muted">Налог на продажу мелких бизнесов (Tier 1) %</label>
                  <Input 
                    type="number"
                    value={taxSettings.small_business_tax || 5}
                    onChange={(e) => setTaxSettings({...taxSettings, small_business_tax: parseFloat(e.target.value) || 0})}
                    className="bg-white/5 border-white/10"
                  />
                  <p className="text-xs text-text-muted">Применяется к бизнесам Tier 1</p>
                </div>
                <div className="space-y-2">
                  <label className="text-sm text-text-muted">Налог на продажу средних бизнесов (Tier 2) %</label>
                  <Input 
                    type="number"
                    value={taxSettings.medium_business_tax || 8}
                    onChange={(e) => setTaxSettings({...taxSettings, medium_business_tax: parseFloat(e.target.value) || 0})}
                    className="bg-white/5 border-white/10"
                  />
                  <p className="text-xs text-text-muted">Применяется к бизнесам Tier 2</p>
                </div>
                <div className="space-y-2">
                  <label className="text-sm text-text-muted">Налог на продажу крупных бизнесов (Tier 3) %</label>
                  <Input 
                    type="number"
                    value={taxSettings.large_business_tax || 10}
                    onChange={(e) => setTaxSettings({...taxSettings, large_business_tax: parseFloat(e.target.value) || 0})}
                    className="bg-white/5 border-white/10"
                  />
                  <p className="text-xs text-text-muted">Применяется к бизнесам Tier 3</p>
                </div>
                <div className="space-y-2">
                  <label className="text-sm text-text-muted">Налог на продажу земли с бизнесом %</label>
                  <Input 
                    type="number"
                    value={taxSettings.land_business_sale_tax || 10}
                    onChange={(e) => setTaxSettings({...taxSettings, land_business_sale_tax: parseFloat(e.target.value) || 0})}
                    className="bg-white/5 border-white/10"
                  />
                  <p className="text-xs text-text-muted">Применяется при продаже участка с бизнесом на маркетплейсе</p>
                </div>
              </div>
              
              <Button 
                onClick={saveTaxSettings}
                className="mt-6 bg-cyber-cyan text-black hover:bg-cyber-cyan/80"
              >
                Сохранить налоги
              </Button>
            </div>
          </TabsContent>

          {/* Contract Deployer Tab */}
          <TabsContent value="contract">
            <ContractDeployerPanel token={token} />
          </TabsContent>

          {/* Multi-Accounts Detection Tab */}
          <TabsContent value="multiaccounts">
            <Card className="bg-void border-red-500/30">
              <CardContent className="p-6">
                <div className="flex items-start justify-between gap-4 mb-4 flex-wrap">
                  <div>
                    <h3 className="text-xl font-bold text-white flex items-center gap-2">
                      <AlertCircle className="w-5 h-5 text-red-400" />
                      Обнаружение мульти-аккаунтов
                    </h3>
                    <p className="text-xs text-text-muted mt-1">
                      FingerprintJS (локальный отпечаток устройства) + Cloudflare Turnstile (анти-бот).
                      Авто-очистка событий старше <span className="text-cyber-cyan">30 дней</span> (MongoDB TTL).
                    </p>
                  </div>
                  {multiAccounts && (
                    <div className="flex items-center gap-2 text-xs flex-wrap">
                      <span className={`px-2 py-1 rounded ${multiAccounts.turnstile_enabled ? 'bg-green-500/20 text-green-400' : 'bg-amber-500/20 text-amber-400'}`} data-testid="turnstile-status">
                        Turnstile: {multiAccounts.turnstile_enabled ? 'enabled' : 'dry-run (no key)'}
                      </span>
                      <span className="px-2 py-1 rounded bg-cyber-cyan/20 text-cyber-cyan" data-testid="ma-total-events">
                        Events: {multiAccounts.total_events || 0}
                      </span>
                      {multiAccounts.turnstile_counters && (
                        <>
                          <span className="px-2 py-1 rounded bg-green-500/10 text-green-400">
                            ✓ {multiAccounts.turnstile_counters.passed || 0}
                          </span>
                          <span className="px-2 py-1 rounded bg-red-500/10 text-red-400">
                            ✗ {multiAccounts.turnstile_counters.failed || 0}
                          </span>
                        </>
                      )}
                    </div>
                  )}
                </div>

                {/* Cleanup controls */}
                <div className="flex items-center gap-2 flex-wrap mb-5 p-3 bg-white/[0.03] border border-white/10 rounded-lg">
                  <span className="text-xs text-text-muted uppercase tracking-wide">Очистка:</span>
                  <Button
                    data-testid="ma-cleanup-old"
                    variant="outline"
                    size="sm"
                    disabled={maCleanupBusy}
                    onClick={() => cleanupMultiAccounts(
                      { mode: 'older_than', older_than_days: 30 },
                      'Удалить все события старше 30 дней?'
                    )}
                    className="border-white/10 text-white/80 hover:bg-white/5 text-xs"
                  >
                    Старше 30 дней
                  </Button>
                  <Button
                    data-testid="ma-cleanup-7d"
                    variant="outline"
                    size="sm"
                    disabled={maCleanupBusy}
                    onClick={() => cleanupMultiAccounts(
                      { mode: 'older_than', older_than_days: 7 },
                      'Удалить все события старше 7 дней?'
                    )}
                    className="border-white/10 text-white/80 hover:bg-white/5 text-xs"
                  >
                    Старше 7 дней
                  </Button>
                  <Button
                    data-testid="ma-cleanup-failed"
                    variant="outline"
                    size="sm"
                    disabled={maCleanupBusy}
                    onClick={() => cleanupMultiAccounts(
                      { mode: 'failed_only' },
                      'Удалить все провалы Turnstile?'
                    )}
                    className="border-red-500/30 text-red-400 hover:bg-red-500/10 text-xs"
                  >
                    Только провалы
                  </Button>
                  <Button
                    data-testid="ma-cleanup-all"
                    variant="outline"
                    size="sm"
                    disabled={maCleanupBusy}
                    onClick={() => cleanupMultiAccounts(
                      { mode: 'all' },
                      '⚠️ Удалить ВСЕ события? Это сбросит все группы.'
                    )}
                    className="border-red-500/50 text-red-400 hover:bg-red-500/10 text-xs"
                  >
                    Всё
                  </Button>
                </div>

                {multiAccounts ? (
                  <div className="space-y-6">
                    {/* Visitor (device fingerprint) groups */}
                    <div>
                      <h4 className="text-lg font-bold text-amber-400 mb-3" data-testid="ma-visitor-title">
                        Устройства (одинаковый visitor_id) — {multiAccounts.totals?.visitor_groups || 0} групп
                      </h4>
                      {(multiAccounts.visitor_groups || []).length > 0 ? (
                        <div className="space-y-3">
                          {multiAccounts.visitor_groups.map((group, i) => (
                            <div key={i} className="bg-red-500/10 border border-red-500/30 rounded-lg p-4" data-testid={`ma-visitor-group-${i}`}>
                              <div className="flex items-center justify-between flex-wrap gap-2 mb-2">
                                <div className="text-red-400 font-mono text-xs break-all">visitor_id: {group.visitor_id}</div>
                                <div className="flex items-center gap-2 text-[11px]">
                                  <span className="text-text-muted">last IP: <span className="font-mono text-white">{group.last_ip || '—'}</span></span>
                                  <span className="text-text-muted">{group.unique_users} акк.</span>
                                  <span className="text-text-muted">{group.events_count} событий</span>
                                </div>
                              </div>
                              <div className="space-y-1">
                                {group.users.map((u, j) => (
                                  <div key={j} className="flex items-center gap-2 text-sm flex-wrap">
                                    <span className="text-white font-bold">{u.username || u.email}</span>
                                    <span className="text-text-muted text-xs">{u.email}</span>
                                    <span className="text-text-muted text-[10px]">id:{(u.user_id || '').slice(0, 8)}</span>
                                  </div>
                                ))}
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="text-green-400 text-sm">Совпадений по устройствам не обнаружено</div>
                      )}
                    </div>

                    {/* IP groups */}
                    <div>
                      <h4 className="text-lg font-bold text-amber-400 mb-3" data-testid="ma-ip-title">
                        Совпадения по IP — {multiAccounts.totals?.ip_groups || 0} групп
                      </h4>
                      {(multiAccounts.ip_groups || []).length > 0 ? (
                        <div className="space-y-3">
                          {multiAccounts.ip_groups.map((group, i) => (
                            <div key={i} className="bg-amber-500/10 border border-amber-500/30 rounded-lg p-4" data-testid={`ma-ip-group-${i}`}>
                              <div className="flex items-center justify-between flex-wrap gap-2 mb-2">
                                <div className="text-amber-400 font-mono text-sm">IP: {group.ip}</div>
                                <div className="flex items-center gap-2 text-[11px] flex-wrap">
                                  <span className="text-text-muted">{group.unique_users} акк.</span>
                                  <span className="text-text-muted">{group.unique_visitors} устр.</span>
                                </div>
                              </div>
                              <div className="space-y-1">
                                {group.users.map((u, j) => (
                                  <div key={j} className="flex items-center gap-2 text-sm flex-wrap">
                                    <span className="text-white font-bold">{u.username || u.email}</span>
                                    <span className="text-text-muted text-xs">{u.email}</span>
                                    <span className="text-text-muted text-[10px]">id:{(u.user_id || '').slice(0, 8)}</span>
                                  </div>
                                ))}
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="text-green-400 text-sm">Совпадений по IP не обнаружено</div>
                      )}
                    </div>

                    {/* Failed Turnstile challenges (bots) */}
                    <div>
                      <h4 className="text-lg font-bold text-red-400 mb-3" data-testid="ma-failed-title">
                        Провалы Turnstile (боты) — {multiAccounts.totals?.failed_challenges || 0} событий
                      </h4>
                      {(multiAccounts.failed_challenges || []).length > 0 ? (
                        <div className="space-y-2">
                          {multiAccounts.failed_challenges.map((ev, i) => (
                            <div key={ev._id || i} className="bg-white/5 border border-white/10 rounded-lg p-3 flex items-center justify-between flex-wrap gap-2" data-testid={`ma-failed-${i}`}>
                              <div className="flex items-center gap-2 flex-wrap">
                                <span className="px-1.5 py-0.5 rounded text-[10px] uppercase bg-red-500/20 text-red-400">bot</span>
                                <span className="text-white text-sm">{ev.username || ev.email || (ev.user_id || '').slice(0, 8)}</span>
                                <span className="text-text-muted text-[10px] uppercase">{ev.event_type}</span>
                                <span className="text-text-muted text-xs font-mono">{ev.ip}</span>
                              </div>
                              <div className="flex items-center gap-2 text-[11px] flex-wrap">
                                {(ev.turnstile?.error_codes || []).map((code, k) => (
                                  <span key={k} className="px-1.5 py-0.5 bg-red-500/10 rounded text-red-400 font-mono">{code}</span>
                                ))}
                                {ev._id && (
                                  <Button
                                    data-testid={`ma-failed-delete-${i}`}
                                    variant="ghost"
                                    size="sm"
                                    disabled={maCleanupBusy}
                                    onClick={() => cleanupMultiAccounts(
                                      { mode: 'by_ids', event_ids: [ev._id] },
                                      null
                                    )}
                                    className="h-6 px-2 text-red-400 hover:text-red-300 hover:bg-red-500/10"
                                    title="Удалить"
                                  >
                                    <Trash2 className="w-3 h-3" />
                                  </Button>
                                )}
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="text-green-400 text-sm">
                          {multiAccounts.turnstile_enabled ? 'Подозрительных событий не обнаружено' : 'Turnstile отключён — добавьте TURNSTILE_SECRET_KEY'}
                        </div>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="text-text-muted text-center py-8">Загрузка данных...</div>
                )}
              </CardContent>
            </Card>
          </TabsContent>

        </Tabs>
      </main>
    </div>
  );
}
