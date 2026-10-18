import { formatErrorDetail } from '@/lib/apiErrors';
import { subscribeUserSocket } from '@/lib/userSocket';
import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Building2, Package, Coins, TrendingUp, RefreshCw, 
  Settings2, Wrench, Zap, ArrowUp, ChevronRight,
  Play, Pause, Check, X, AlertCircle, Shield, Heart,
  Crown, Users, Warehouse, Clock, Loader2, Tag,
  FileText, HandshakeIcon, ChevronDown, Scroll, Target, ChevronLeft,
  Info, ArrowUpFromLine, Store, MessageCircle
} from 'lucide-react';
import { useChatUnreadCount } from '@/components/NotificationCenter';
import PageHeader from '@/components/PageHeader';
import BusinessProfileHeader from '@/components/BusinessProfileHeader';
import ShiftButton from '@/components/ShiftButton';
import EventBanner from '@/components/EventBanner';
import { buffTimeLeft } from '@/components/BusinessBuffs';
// icons of the tier-3 buffs (same as backend/routes/buffs.py RESOURCE_BUFFS) — used when the stored buff has none
const BUFF_ICON = { neuro_core: '🔮', gold_bill: '📜', license_token: '🎫', luck_chip: '🎲', war_protocol: '⚔️', bio_module: '🧬', gateway_code: '🔑' };
import useQuestReadyCount from '@/hooks/useQuestReadyCount';
import SkinPicker from '@/components/SkinPicker';
import { BusinessRentalControls } from '@/components/RentalDialogs';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from '@/components/ui/dialog';
import { Progress } from '@/components/ui/progress';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { toast } from 'sonner';
import Sidebar from '@/components/Sidebar';
import { useTranslation } from '@/lib/translations';
import { useLanguage } from '@/context/LanguageContext';
import { useTutorial } from '@/context/TutorialContext';
import { tBusiness, tResource, tBuff, tResourceBuff, tContract } from '@/lib/translationsExtra';
import { tonToCity, formatCity } from '@/lib/currency';
import { getGameMode } from '@/lib/gameMode';
import { getResource, getAllResources, getResourceName } from '@/lib/resourceConfig';
import { fetchSkinsIndex, resolveSkinUrl } from '@/lib/skins';
import { citySpriteUrl } from '@/lib/citySprites';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api`;

// Tier colors
const CONTRACT_TYPES = {
  tax_haven: {
    name: 'Налоговая Гавань',
    description: 'Вассал платит 10% с каждой продажи ресурсов на маркетплейсе',
    vassal_note: '10% с каждой продажи в TON',
    patron_note: '10% от выручки вассала при продаже',
    icon: '🏝️',
    color: 'text-amber-400',
    bg: 'bg-amber-500/10',
    border: 'border-amber-500/30',
    penalty: 500,
  },
  raw_material: {
    name: 'Сырьевой Придаток',
    description: 'Вассал отдаёт 15% произведённых товаров Патрону',
    vassal_note: '15% товаров уходит Патрону каждый тик',
    patron_note: 'Получаете 15% ресурсов вассала',
    icon: '⚙️',
    color: 'text-blue-400',
    bg: 'bg-blue-500/10',
    border: 'border-blue-500/30',
    penalty: 750,
  },
  tech_umbrella: {
    name: 'Технологический Зонтик',
    description: 'Вассал экономит 30% на ремонтных комплектах и платит ренту',
    vassal_note: '100 $CITY/день ренты + -30% ремонт',
    patron_note: 'Фиксированная рента 100 $CITY/день',
    icon: '🛡️',
    color: 'text-green-400',
    bg: 'bg-green-500/10',
    border: 'border-green-500/30',
    penalty: 300,
  },
};

const TIER_COLORS = {
  1: 'bg-green-500/20 text-green-400 border-green-500/30',
  2: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  3: 'bg-purple-500/20 text-purple-400 border-purple-500/30',
};

// Level-0 (застолблённый) → Level-1 upgrade note — localized (all 9 project languages).
const ZERO_UNLOCK_I18N = {
  en: 'Unlock of the MAIN ACCOUNT',
  ru: 'Разблокировка ОСНОВНОГО СЧЁТА',
  es: 'Desbloqueo de la CUENTA PRINCIPAL',
  zh: '解锁主账户',
  fr: 'Déblocage du COMPTE PRINCIPAL',
  de: 'Freischaltung des HAUPTKONTOS',
  ja: 'メインアカウントのロック解除',
  ko: '메인 계정 잠금 해제',
  id: 'Membuka AKUN UTAMA',
};

// Resource icons - V2.0
const resourceIcons = {
  energy: '⚡',
  cu: '🖥️',
  quartz: '💎',
  traffic: '📡',
  cooling: '❄️',
  biomass: '🌿',
  scrap: '🗑️',
  chips: '🔲',
  nft: '🎨',
  neurocode: '🧠',
  logistics: '🚚',
  repair_kits: '🔧',
  vr_experience: '🥽',
  profit_ton: '💰',
  shares: '📈',
  ton: '💎',
  // Backward compat
  food: '🌿',
  algo: '🧠',
  iron: '🔧',
};

// Live countdown to the end of a level-0 business 3-day lease. Shown at the
// bottom of each leased business card. When it reaches zero the backend
// `process_zero_lease` job removes the business and reclaims the T3 lease bonus.
function ZeroLeaseTimer({ expiresAt, t }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  // t() returns the key itself when a translation is missing, so fall back explicitly.
  const tx = (key, fallback) => { const v = t(key); return (!v || v === key) ? fallback : v; };
  const end = expiresAt ? new Date(expiresAt).getTime() : 0;
  if (!end || Number.isNaN(end)) return null;
  const ms = end - now;
  const expired = ms <= 0;
  const totalSec = Math.max(0, Math.floor(ms / 1000));
  const d = Math.floor(totalSec / 86400);
  const h = Math.floor((totalSec % 86400) / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  const pad = (n) => String(n).padStart(2, '0');
  const label = d > 0 ? `${d}${tx('dShort', 'д')} ${pad(h)}:${pad(m)}:${pad(s)}` : `${pad(h)}:${pad(m)}:${pad(s)}`;
  const urgent = ms <= 12 * 3600 * 1000;
  return (
    <div
      data-testid="zero-lease-timer"
      className={`mt-3 pt-3 border-t border-white/10 flex items-center justify-between text-xs ${expired ? 'text-red-400' : urgent ? 'text-yellow-400' : 'text-cyan-300'}`}
    >
      <span className="flex items-center gap-1 text-text-muted">
        <Clock className="w-3.5 h-3.5" /> {tx('leaseEndsIn', 'Аренда истекает через')}
      </span>
      <span className="font-mono font-bold" data-testid="zero-lease-timer-value">
        {expired ? tx('leaseExpired', 'Истекла') : label}
      </span>
    </div>
  );
}


const MISSING_HINT_LABELS = {
  title: { en: 'Not enough resources to work', ru: 'Не хватает ресурсов для работы', es: 'Faltan recursos para trabajar', zh: '缺少生产所需资源', fr: 'Ressources insuffisantes pour travailler', de: 'Nicht genug Ressourcen zum Arbeiten', ja: '稼働に必要な資源が足りません', ko: '작동에 필요한 자원이 부족합니다', id: 'Sumber daya kurang untuk bekerja' },
  text: { en: 'The business is idle until the resource is in your warehouse. Buy it on the market — the business will start on the next tick.', ru: 'Бизнес простаивает, пока ресурса нет на складе. Купите его на рынке — бизнес заработает на следующем такте.', es: 'El negocio está parado hasta que el recurso esté en tu almacén. Cómpralo en el mercado y empezará en el siguiente ciclo.', zh: '仓库中没有该资源时企业会停工。到市场购买后，企业将在下一个周期开始运转。', fr: 'L’entreprise est à l’arrêt tant que la ressource n’est pas en stock. Achetez-la sur le marché — elle redémarrera au prochain cycle.', de: 'Das Business steht still, bis die Ressource im Lager ist. Kaufe sie auf dem Markt – es startet beim nächsten Takt.', ja: '資源が倉庫に入るまでビジネスは停止します。マーケットで購入すると次のサイクルで稼働します。', ko: '자원이 창고에 들어올 때까지 사업이 멈춥니다. 마켓에서 구매하면 다음 주기에 작동합니다.', id: 'Bisnis berhenti sampai sumber daya ada di gudang. Beli di pasar — bisnis akan jalan pada siklus berikutnya.' },
  need: { en: 'Needed per day', ru: 'Нужно в сутки', es: 'Necesario al día', zh: '每天需要', fr: 'Requis par jour', de: 'Bedarf pro Tag', ja: '1日の必要量', ko: '하루 필요량', id: 'Dibutuhkan per hari' },
  left: { en: 'Left in the warehouse', ru: 'Осталось на складе', es: 'Queda en el almacén', zh: '仓库剩余', fr: 'Reste en stock', de: 'Im Lager übrig', ja: '倉庫の残り', ko: '창고 잔량', id: 'Sisa di gudang' },
  buy: { en: 'Buy', ru: 'Купить', es: 'Comprar', zh: '购买', fr: 'Acheter', de: 'Kaufen', ja: '購入', ko: '구매', id: 'Beli' },
  close: { en: 'Close', ru: 'Закрыть', es: 'Cerrar', zh: '关闭', fr: 'Fermer', de: 'Schließen', ja: '閉じる', ko: '닫기', id: 'Tutup' },
};

// Opened by the blinking red «consumption per day» chip when the business lacks an input:
// how much is needed per day, how much is left, and «Купить» → the market filtered by that resource.
function ShortageModal({ items, lang, onBuy, onClose }) {
  const lbl = (k) => MISSING_HINT_LABELS[k][lang] || MISSING_HINT_LABELS[k].en;
  const nf = (n) => Number(n || 0).toLocaleString('ru-RU', { maximumFractionDigits: 2 });
  return (
    <div className="fixed inset-0 z-[90] bg-black/70 flex items-end sm:items-center justify-center p-4" onClick={onClose} data-testid="shortage-modal">
      <div className="w-full max-w-sm rounded-2xl border border-red-400/40 bg-[#0b1020] p-4 space-y-3 mb-[var(--bottom-nav-h,0px)] sm:mb-0 shadow-[0_0_30px_rgba(248,113,113,0.2)]" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2 text-white font-bold"><AlertCircle className="w-5 h-5 text-red-400 shrink-0" />{lbl('title')}</div>
          <button type="button" onClick={onClose} className="text-white/60" aria-label={lbl('close')}><X className="w-5 h-5" /></button>
        </div>
        <p className="text-xs text-white/70">{lbl('text')}</p>
        {items.map((m) => {
          const r = getResource(m.resource, lang);
          return (
            <div key={m.resource} className="rounded-xl border border-white/10 bg-white/5 p-3 space-y-2" data-testid={`shortage-row-${m.resource}`}>
              <div className="flex items-center gap-2 text-white font-semibold"><span className="text-xl">{r.icon}</span>{r.name}</div>
              <div className="grid grid-cols-2 gap-2 text-center">
                <div className="rounded-lg bg-black/30 py-1.5"><div className="text-[10px] text-text-muted">{lbl('need')}</div><div className="text-sky-300 font-bold">{nf(m.needed_per_day ?? (m.needed_per_hour || 0) * 24)}</div></div>
                <div className="rounded-lg bg-black/30 py-1.5"><div className="text-[10px] text-text-muted">{lbl('left')}</div><div className="text-red-300 font-bold">{nf(m.available)}</div></div>
              </div>
              <button type="button" onClick={() => onBuy(m.resource)} data-testid={`shortage-buy-${m.resource}`}
                className="w-full h-10 rounded-xl bg-gradient-to-r from-yellow-400 to-amber-500 text-black font-bold">{lbl('buy')} {r.icon}</button>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function MyBusinessesPage({ user, refreshBalance, updateBalance }) {
  const navigate = useNavigate();
  const { count: chatUnread } = useChatUnreadCount(user);
  
  // Get language from context
  const { language: lang } = useLanguage();
  // Completed quests waiting to be claimed → badge on the «Задания» button.
  const questReady = useQuestReadyCount(user);
  const { t } = useTranslation(lang);

  // Tutorial state — used to disable destructive / detail-opening actions
  // while the user is in the onboarding flow. The tutorial intentionally
  // walks them through the page read-only (steps `explain_idle` and
  // `explain_t3_buff`) and any deviation breaks the sandbox flow.
  const tutorial = useTutorial();
  const isTutorialActive = !!tutorial?.active;
  const blockedTutorialToast = () => {
    try {
      toast.info(
        t('tutorial_action_blocked')
          && t('tutorial_action_blocked') !== 'tutorial_action_blocked'
            ? t('tutorial_action_blocked')
            : 'Это действие недоступно во время обучения. Заверши тур, и оно откроется.',
      );
    } catch (e) { /* noop */ }
  };
  
  const [businesses, setBusinesses] = useState([]);
  const [shortageFor, setShortageFor] = useState(null);   // missing inputs shown in the shortage modal
  // Индекс скинов бизнесов (картинки, которые отображаются на карте) —
  // используется для большого изображения на карточке бизнеса.
  const [skinsIndex, setSkinsIndex] = useState({});
  useEffect(() => {
    let on = true;
    fetchSkinsIndex().then((idx) => { if (on) setSkinsIndex(idx || {}); });
    const onSkinsUpdated = () => fetchSkinsIndex(true).then((idx) => { if (on) setSkinsIndex(idx || {}); });
    window.addEventListener('skinsUpdated', onSkinsUpdated);
    return () => { on = false; window.removeEventListener('skinsUpdated', onSkinsUpdated); };
  }, []);
  // Mobile swipe-carousel state for the business cards (desktop keeps the grid).
  const bizCarouselRef = useRef(null);
  const [activeBizIndex, setActiveBizIndex] = useState(0);
  const handleBizScroll = () => {
    const el = bizCarouselRef.current;
    if (!el) return;
    const center = el.scrollLeft + el.clientWidth / 2;
    let best = 0, bestDist = Infinity;
    Array.from(el.children).forEach((ch, i) => {
      const c = ch.offsetLeft + ch.clientWidth / 2;
      const d = Math.abs(c - center);
      if (d < bestDist) { bestDist = d; best = i; }
    });
    setActiveBizIndex(best);
  };
  const [summary, setSummary] = useState({});
  const [resourcesFromBusinesses, setResourcesFromBusinesses] = useState({});
  const [isLoading, setIsLoading] = useState(true);
  const [selectedBusiness, setSelectedBusiness] = useState(null);
  const [patrons, setPatrons] = useState([]);
  const [lastUpdate, setLastUpdate] = useState(new Date());
  const [myPlots, setMyPlots] = useState([]);
  
  // Modals
  const [showUpgradeModal, setShowUpgradeModal] = useState(false);
  const [showAllResources, setShowAllResources] = useState(false);
  const [showRepairModal, setShowRepairModal] = useState(false);
  const [showPatronModal, setShowPatronModal] = useState(false);
  const [showBuffModal, setShowBuffModal] = useState(false);
  const [availableBuffs, setAvailableBuffs] = useState([]);
  const [buffBusiness, setBuffBusiness] = useState(null);

  // ==== T3 Resource Buffs (subscription-style) ====
  // IDs of T3 resources that can be activated as buffs
  const T3_BUFF_RESOURCE_IDS = ['neuro_core', 'gold_bill', 'license_token', 'luck_chip', 'war_protocol', 'bio_module', 'gateway_code'];
  const [resourceBuffsData, setResourceBuffsData] = useState({ buffs: [], active: [] });
  const [activeBuffMults, setActiveBuffMults] = useState({ trade_tax_reduction: 0.0, trade_fee_multiplier: 1.0 });
  const [showResourceBuffModal, setShowResourceBuffModal] = useState(false);
  const [selectedBuffResource, setSelectedBuffResource] = useState(null);
  const [isActivatingBuff, setIsActivatingBuff] = useState(false);
  const [vassals, setVassals] = useState([]);
  const [showVassalsModal, setShowVassalsModal] = useState(false);
  const [showDetailsModal, setShowDetailsModal] = useState(false);
  const [showSellModal, setShowSellModal] = useState(false);
  const [sellPrice, setSellPrice] = useState('');
  const [sellTaxInfo, setSellTaxInfo] = useState(null);
  const [isCancelingSale, setIsCancelingSale] = useState(false);
  
  // Loading states
  const [isCollecting, setIsCollecting] = useState(false);
  const [isUpgrading, setIsUpgrading] = useState(false);
  const [isRepairing, setIsRepairing] = useState(false);
  const [isSelling, setIsSelling] = useState(false);
  
  // Contract state
  const [contracts, setContracts] = useState({ as_patron: [], as_vassal: [] });
  const [showContractProposalModal, setShowContractProposalModal] = useState(false);
  const [contractTarget, setContractTarget] = useState(null);
  const [proposalType, setProposalType] = useState('tax_haven');
  const [proposalBuff, setProposalBuff] = useState('');
  const [proposalDuration, setProposalDuration] = useState(30);
  const [proposalAutoRenew, setProposalAutoRenew] = useState(false);
  const [isProposing, setIsProposing] = useState(false);
  const [showContractDetailsModal, setShowContractDetailsModal] = useState(false);
  const [selectedContract, setSelectedContract] = useState(null);
  
  // Alliance offers state
  const [allianceOffers, setAllianceOffers] = useState([]);
  const [showAllOffersModal, setShowAllOffersModal] = useState(false);
  const [showPublishOfferModal, setShowPublishOfferModal] = useState(false);
  const [offerBuff, setOfferBuff] = useState('');
  const [offerType, setOfferType] = useState('tax_haven');
  const [offerDuration, setOfferDuration] = useState(30);
  const [isPublishing, setIsPublishing] = useState(false);
  
  // Alliance offers browsing (paginated)
  const [offersPage, setOffersPage] = useState(0);
  const OFFERS_PER_PAGE = 3;
  
  const token = localStorage.getItem('token');

  // ===== Bank owner settings (Block A) =====
  const [showBankSettingsModal, setShowBankSettingsModal] = useState(false);
  const [bankSettings, setBankSettings] = useState({ interest_rate_percent: '', instant_fee_percent: '' });
  const [bankSettingsLoading, setBankSettingsLoading] = useState(false);
  const [bankSettingsSaving, setBankSettingsSaving] = useState(false);
  const isBankBusiness = (biz) =>
    !!biz && (biz.business_type === 'gram_bank' || biz.config?.instant_withdrawal === true);

  const loadBankSettings = async (businessId) => {
    setBankSettingsLoading(true);
    try {
      const res = await fetch(`${API}/bank/settings/${businessId}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setBankSettings({
          interest_rate_percent: String(data.interest_rate_percent ?? ''),
          instant_fee_percent: String(data.instant_fee_percent ?? ''),
        });
      }
    } catch (e) {
      /* non-blocking */
    } finally {
      setBankSettingsLoading(false);
    }
  };

  // Sanitize numeric input: digits only, clamp to [0, max], strip leading zeros.
  const sanitizeIntField = (raw, max) => {
    const digits = String(raw).replace(/[^0-9]/g, '');
    if (digits === '') return '';
    let n = parseInt(digits, 10);
    if (Number.isNaN(n)) return '';
    if (n > max) n = max;
    return String(n);
  };

  const saveBankSettings = async () => {
    if (!selectedBusiness) return;
    const interest = parseInt(bankSettings.interest_rate_percent || '0', 10);
    const instant = parseInt(bankSettings.instant_fee_percent || '0', 10);
    setBankSettingsSaving(true);
    try {
      const res = await fetch(`${API}/bank/settings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          business_id: selectedBusiness.id,
          interest_rate_percent: interest,
          instant_fee_percent: instant,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(formatErrorDetail(data.detail) || 'Ошибка сохранения');
      setBankSettings({
        interest_rate_percent: String(data.interest_rate_percent),
        instant_fee_percent: String(data.instant_fee_percent),
      });
      toast.success(t('bankSettingsSaved') || 'Настройки банка сохранены');
      setShowBankSettingsModal(false);
    } catch (e) {
      toast.error(e.message || 'Ошибка сохранения');
    } finally {
      setBankSettingsSaving(false);
    }
  };

  // Fetch alliance offers
  const fetchAllianceOffers = async () => {
    try {
      const res = await fetch(`${API}/alliances/offers`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setAllianceOffers(data.offers || []);
      }
    } catch (e) {
      console.error('Failed to fetch alliance offers:', e);
    }
  };

  // Publish offer handler
  const handlePublishOffer = async () => {
    if (!offerBuff || !offerType) {
      toast.error(t('selectBuffAndContractErr') || 'Select a buff and contract type');
      return;
    }
    setIsPublishing(true);
    try {
      const res = await fetch(`${API}/alliances/publish-offer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          buff_id: offerBuff,
          contract_type: offerType,
          duration_days: offerDuration,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(formatErrorDetail(data.detail) || 'Ошибка');
      toast.success(t('offerPublishedSuccess') || 'Offer published! Vassals will be able to see it.');
      setShowPublishOfferModal(false);
      setOfferBuff('');
      setOfferType('tax_haven');
      setOfferDuration(30);
      fetchAllianceOffers();
    } catch (e) {
      toast.error(e.message);
    } finally {
      setIsPublishing(false);
    }
  };

  // Accept offer handler
  const handleAcceptOffer = async (offerId, vassalBusinessId) => {
    try {
      const url = vassalBusinessId
        ? `${API}/alliances/accept/${offerId}?vassal_business_id=${vassalBusinessId}`
        : `${API}/alliances/accept/${offerId}`;
      const res = await fetch(url, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      if (!res.ok) throw new Error(formatErrorDetail(data.detail) || 'Ошибка');
      toast.success(data.message || 'Альянс заключён!');
      fetchAllianceOffers();
      fetchContracts();
      fetchData();
    } catch (e) {
      toast.error(e.message);
    }
  };

  // Cancel own offer
  const handleCancelOffer = async (offerId) => {
    try {
      const res = await fetch(`${API}/alliances/cancel-offer/${offerId}`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      if (!res.ok) throw new Error(formatErrorDetail(data.detail) || 'Ошибка');
      toast.success(t('offerCancelledSuccess') || 'Offer cancelled');
      fetchAllianceOffers();
    } catch (e) {
      toast.error(e.message);
    }
  };

  // Helper: get color class for consumed resource based on hours remaining
  const getConsumeColor = (resource, dailyAmount) => {
    if (!dailyAmount || dailyAmount <= 0) return 'text-text-muted';
    const available = resourcesFromBusinesses[resource] || 0;
    if (available === 0) return 'text-red-400';
    const hoursRemaining = (available / dailyAmount) * 24;
    if (hoursRemaining <= (5 / 60)) return 'text-red-400';  // ≤ 5 min
    if (hoursRemaining <= 4) return 'text-yellow-400';       // ≤ 4 hours
    return 'text-green-400';                                  // > 4 hours
  };

  // Форматирование адреса кошелька
  const formatWalletAddress = (address) => {
    if (!address) return 'Не привязан';
    if (address.length <= 15) return address;
    return `${address.slice(0, 6)}...${address.slice(-4)}`;
  };

  // Расчет налога при продаже
  const calculateSaleTax = async (price) => {
    try {
      const res = await fetch(`${API}/business/calculate-sale-tax`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ price: parseFloat(price), business_id: selectedBusiness?.id })
      });
      if (res.ok) {
        const data = await res.json();
        setSellTaxInfo(data);
      }
    } catch (error) {
      console.error('Failed to calculate tax:', error);
    }
  };

  // Продажа бизнеса
  const handleSellBusiness = async () => {
    if (!selectedBusiness || !sellPrice) return;
    
    setIsSelling(true);
    try {
      const res = await fetch(`${API}/business/${selectedBusiness.id}/sell`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({
          business_id: selectedBusiness.id,
          price: parseFloat(sellPrice) / 1000  // Convert $CITY to TON for backend
        })
      });
      
      if (!res.ok) {
        const err = await res.json();
        throw new Error(formatErrorDetail(err.detail) || 'Failed to list business');
      }
      
      const data = await res.json();
      toast.success((t('listedSuccess') || 'Business listed for sale! You will receive {amount} $CITY').replace('{amount}', formatCity(tonToCity(data.listing.seller_receives))));
      setShowSellModal(false);
      setSellPrice('');
      setSellTaxInfo(null);
      fetchData();
    } catch (error) {
      toast.error(error.message);
    } finally {
      setIsSelling(false);
    }
  };

  // Снять бизнес с продажи
  const handleCancelSale = async () => {
    if (!selectedBusiness) {
      toast.error(t('businessNotSelectedErr') || 'No business selected');
      return;
    }
    
    setIsCancelingSale(true);
    try {
      // Сначала найдём листинг по plot_id или business_id
      const listingsRes = await fetch(`${API}/market/land/listings`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      const listingsData = await listingsRes.json();
      
      // Ищем листинг этого бизнеса
      const listing = (listingsData.listings || []).find(l => 
        l.plot_id === selectedBusiness.plot_id || 
        l.business_id === selectedBusiness.id ||
        (l.business && l.business.id === selectedBusiness.id)
      );
      
      if (!listing) {
        toast.error(t('listingNotFoundErr') || 'Listing not found');
        setIsCancelingSale(false);
        return;
      }
      
      // Используем тот же эндпоинт DELETE как на маркетплейсе
      const res = await fetch(`${API}/market/land/listing/${listing.id}`, {
        method: 'DELETE',
        headers: {
          Authorization: `Bearer ${token}`
        }
      });
      
      if (!res.ok) {
        const err = await res.json();
        if (err.detail === 'SEIZED_CONTACT_SUPPORT') {
          throw new Error(t('seizedContactSupport') || 'To delist a business, please contact support.');
        }
        throw new Error(formatErrorDetail(err.detail) || 'Не удалось снять с продажи');
      }
      
      toast.success(t('unlistedSuccess') || 'Business removed from sale');
      setShowDetailsModal(false);
      fetchData();
    } catch (error) {
      toast.error(error.message);
    } finally {
      setIsCancelingSale(false);
    }
  };

  const fetchData = async () => {
    setIsLoading(true);
    try {
      // Demo (Sandbox): show ONLY the demo business + demo resources, fetched
      // from the isolated demo endpoints (never the real ones).
      if (getGameMode() === 'demo') {
        const [demoBiz, demoState] = await Promise.all([
          fetch(`${API}/demo/my-businesses`, { headers: { Authorization: `Bearer ${token}` } }).then(r => r.json()).catch(() => ({ businesses: [], summary: {} })),
          fetch(`${API}/demo/state`, { headers: { Authorization: `Bearer ${token}` } }).then(r => r.json()).catch(() => ({ profile: {} })),
        ]);
        const dbz = demoBiz.businesses || [];
        setBusinesses(dbz);
        setSummary(demoBiz.summary || {});
        setSelectedBusiness((prev) => prev ? (dbz.find((b) => b.id === prev.id) || dbz[0] || null) : prev);
        setResourcesFromBusinesses((demoState.profile && demoState.profile.demo_resources) || {});
        setPatrons([]);
        setMyPlots([]);
        setResourceBuffsData({ buffs: [], active: [] });
        setLastUpdate(new Date());
        setIsLoading(false);
        return;
      }
      const [bizRes, patronsRes, resourcesRes, plotsRes, buffsRes, buffMultsRes] = await Promise.all([
        fetch(`${API}/my/businesses`, { headers: { Authorization: `Bearer ${token}` } }).then(async (r) => {
          const data = await r.json().catch(() => ({}));
          if (!r.ok) {
            // Surface the SPECIFIC backend error (status + detail) instead of
            // silently showing an empty "My Businesses" list.
            const detail = (data && (data.detail || data.message)) || '';
            const e = new Error(`GET /api/my/businesses — status ${r.status}${detail ? `: ${detail}` : ''}`);
            e.__where = '/api/my/businesses';
            throw e;
          }
          return data;
        }),
        fetch(`${API}/patrons`).then(r => r.json()),
        fetch(`${API}/my/resources`, { headers: { Authorization: `Bearer ${token}` } }).then(r => r.json()).catch(() => ({ resources: {} })),
        fetch(`${API}/users/me/plots`, { headers: { Authorization: `Bearer ${token}` } }).then(r => r.json()).catch(() => ({ plots: [] })),
        fetch(`${API}/resource-buffs/available`, { headers: { Authorization: `Bearer ${token}` } }).then(r => r.json()).catch(() => ({ buffs: [], active: [] })),
        fetch(`${API}/my/active-buff-multipliers`, { headers: { Authorization: `Bearer ${token}` } }).then(r => r.json()).catch(() => null),
      ]);

      setBusinesses(bizRes.businesses || []);
      setSummary(bizRes.summary || {});
      // Re-sync currently selected business/buff modal targets so any nested
      // detail dialogs (patron buff, upgrade, repair) refresh in-place when
      // server-side data changes (e.g. patron updates its T3 buff via WS).
      const fresh = bizRes.businesses || [];
      setSelectedBusiness((prev) => prev ? (fresh.find((b) => b.id === prev.id) || prev) : prev);
      setBuffBusiness((prev) => prev ? (fresh.find((b) => b.id === prev.id) || prev) : prev);
      setPatrons(patronsRes.patrons || []);
      setResourcesFromBusinesses(resourcesRes.resources || {});
      setMyPlots(plotsRes.plots || []);
      setResourceBuffsData(buffsRes || { buffs: [], active: [] });
      if (buffMultsRes) {
        setActiveBuffMults({ ...(buffMultsRes.multipliers || {}), ...(buffMultsRes.reductions || {}) });
      }
      setLastUpdate(new Date());
    } catch (error) {
      
      const _msg = (error && error.message) ? error.message : (t('loadDataErr') || 'Failed to load data');
      toast.error(`${t('loadDataErr') || 'Failed to load data'}: ${_msg}`, { duration: 10000 });
    } finally {
      setIsLoading(false);
    }
  };

  // Silent refresh: re-fetch businesses + resources WITHOUT the loading spinner.
  // Used by the auto-refresh tick so the work-status badge updates on its own
  // (e.g. after the user buys input resources and the next economic tick flips
  // the business back to "working").
  const refreshBusinessesSilently = async () => {
    if (!token) return;
    if (getGameMode() === 'demo') { fetchData(); return; }
    try {
      const [bizRes, resourcesRes] = await Promise.all([
        fetch(`${API}/my/businesses`, { headers: { Authorization: `Bearer ${token}` } }).then(r => r.json()),
        fetch(`${API}/my/resources`, { headers: { Authorization: `Bearer ${token}` } }).then(r => r.json()).catch(() => null),
      ]);
      if (bizRes?.businesses) {
        const fresh = bizRes.businesses;
        setBusinesses(fresh);
        setSummary(bizRes.summary || {});
        setSelectedBusiness((prev) => prev ? (fresh.find((b) => b.id === prev.id) || prev) : prev);
        setBuffBusiness((prev) => prev ? (fresh.find((b) => b.id === prev.id) || prev) : prev);
      }
      if (resourcesRes?.resources) setResourcesFromBusinesses(resourcesRes.resources);
      setLastUpdate(new Date());
    } catch (_e) { /* keep last good state on transient errors */ }
  };

  // Activate a T3 resource as a buff (consumes 1 unit, lasts N days)
  const handleActivateResourceBuff = async (resourceId) => {
    {
      const base = String(resourceId).replace(/_tutorial$/, '');
      const act = (resourceBuffsData?.active || []).map((a) => String(a.resource_id || a.resource || '').replace(/_tutorial$/, ''));
      if (act.includes(base)) { toast.info(t('boostAlreadyActive')); return; }       // no request -> no 400
      if (act.length >= 2) { toast.info(t('boostMaxTwo')); return; }
    }
    if (!resourceId) return;
    // v2.1.5: client-side guard — block activation when the user has no real
    // (non-tutorial) business. Mirrors the backend gate so the user gets an
    // instant, localized message instead of a server round-trip.
    const realBizCount = (businesses || []).filter((b) => !b.tutorial).length;
    if (realBizCount === 0) {
      toast.error(t('tutorial_buff_needs_business') || 'Для активации T3-баффа требуется активный бизнес. Приобретите свой первый участок, чтобы применить этот ускоритель.');
      return;
    }
    setIsActivatingBuff(true);
    try {
      const res = await fetch(`${API}/resource-buffs/activate/${resourceId}`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` }
      });
      const text = await res.text();
      let data;
      try { data = JSON.parse(text); } catch { data = { detail: text || 'Ошибка активации' }; }
      if (!res.ok) {
        // Translate known error codes (server now returns i18n keys, not RU strings)
        const code = data.detail;
        if (code === 'tutorial_buff_needs_business') {
          throw new Error(t('tutorial_buff_needs_business') || 'Для активации T3-баффа требуется активный бизнес. Приобретите свой первый участок, чтобы применить этот ускоритель.');
        }
        if (code === 'boosters_limit') throw new Error(t('boostMaxTwo'));
        throw new Error(formatErrorDetail(data.detail) || 'Ошибка активации');
      }
      toast.success(data.message || 'Баф активирован');
      setShowResourceBuffModal(false);
      setSelectedBuffResource(null);
      fetchData();
    } catch (error) {
      toast.error(error.message);
    } finally {
      setIsActivatingBuff(false);
    }
  };

  const fetchContracts = async () => {
    try {
      const res = await fetch(`${API}/contracts/my`, { headers: { Authorization: `Bearer ${token}` } });
      if (res.ok) {
        const data = await res.json();
        setContracts(data);
      }
    } catch {}
  };

  useEffect(() => {
    if (!token) {
      navigate('/auth?mode=login');
      return;
    }
    fetchData();
    fetchContracts();
    fetchAllianceOffers();

    // Auto-refresh tick: silently re-sync business status every 60s so the
    // work-status badge ("Простаивает" → "Активен") updates on its own once
    // the conditions are met, without the user reloading the page.
    // Skipped in demo/sandbox mode — the demo economy is static and the
    // periodic re-fetch was perceived as an annoying "page refresh every minute".
    const statusTick = getGameMode() === 'demo'
      ? null
      : setInterval(() => { refreshBusinessesSilently(); }, 60000);
    
    // (Vassal/buff system removed) — Tier 3 purchases no longer auto-open a buff modal.
    
    // ─── WebSocket: realtime patron buff updates ────────────────────────────
    // Server emits {type: 'patron_buff_changed', patron_business_id, buff} to:
    //   • the patron owner (so its T3 details refresh without "обновить")
    //   • each vassal owner (so their business details show the new buff instantly)
    // We connect once, refresh the businesses list on each event, and close on unmount.
    const userKey = user?.id || user?.email || user?.wallet_address || user?.username;
    const unsubscribe = subscribeUserSocket(userKey, (data) => {          // one shared socket (lib/userSocket.js)
      if (data?.type === 'patron_buff_changed') {
        fetchData();
        if (data?.buff?.name) {
          toast.message('Бафф патрона обновлён', { description: `${data.buff.icon || ''} ${data.buff.name}` });
        }
      }
    });
    return () => { unsubscribe(); if (statusTick) clearInterval(statusTick); };
  }, [user?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Collect all income
  const handleCollectAll = async () => {
    setIsCollecting(true);
    try {
      const res = await fetch(`${API}/my/collect-all`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` }
      });
      
      if (!res.ok) throw new Error('Ошибка сбора');
      
      const data = await res.json();
      
      // Мгновенное отображение начисления
      toast.success(
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2">
            <span className="text-2xl animate-bounce">💰</span>
            <span className="text-lg font-bold text-green-400">+{formatCity(tonToCity(data.total_player_income))} $CITY</span>
          </div>
          <div className="text-xs text-gray-400">Собрано с {data.businesses_collected} бизнесов</div>
          <div className="text-xs text-amber-400">Налог: -{formatCity(tonToCity(data.total_tax_paid))} $CITY</div>
        </div>,
        { duration: 5000 }
      );
      
      // Update global balance
      if (refreshBalance) refreshBalance();
      if (updateBalance && data.new_balance !== undefined) {
        updateBalance(data.new_balance);
      }
      
      setLastUpdate(new Date());
      fetchData();
    } catch (error) {
      toast.error(error.message);
    } finally {
      setIsCollecting(false);
    }
  };

  // Collect single business
  const handleCollect = async (businessId) => {
    try {
      const res = await fetch(`${API}/business/${businessId}/collect`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` }
      });
      
      if (!res.ok) {
        const err = await res.json();
        throw new Error(formatErrorDetail(err.detail) || 'Ошибка сбора');
      }
      
      const data = await res.json();
      
      // Мгновенное визуальное начисление
      toast.success(
        <div className="flex items-center gap-2">
          <span className="text-xl animate-bounce">💰</span>
          <span className="font-bold text-green-400">+{formatCity(tonToCity(data.player_receives))} $CITY</span>
        </div>,
        { duration: 3000 }
      );
      
      fetchData();
    } catch (error) {
      toast.error(error.message);
    }
  };

  // Upgrade business
  const handleUpgrade = async () => {
    if (!selectedBusiness) return;
    setIsUpgrading(true);

    try {
      // Demo mode: upgrade is applied against demo_balance_city + demo_resources
      // via the isolated demo endpoint (same cost table as real mode).
      if (getGameMode() === 'demo') {
        const res = await fetch(`${API}/demo/business/upgrade`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
        });
        const data = await res.json().catch(() => ({}));
        if (data.status === 'upgraded') {
          toast.success((t('upgradeSuccess') || 'Upgraded to level {level}!').replace('{level}', data.new_level));
          setShowUpgradeModal(false);
          fetchData();
        } else if (data.status === 'insufficient_city') {
          toast.error(`${t('upgradeError') || 'Ошибка улучшения'}: $CITY ${Math.ceil(data.need_city)} / ${Math.floor(data.have_city)}`);
        } else if (data.status === 'insufficient_resource') {
          const resName = getResourceName(data.resource, lang) || data.resource;
          const msg = (t('insufficientResourceUpgrade') || 'Insufficient {res}: need {need}, have {have}')
            .replace('{res}', resName)
            .replace('{need}', data.need)
            .replace('{have}', data.have);
          toast.error(msg);
        } else if (data.status === 'max_level') {
          toast.info(t('upgradeMaxLevel') || 'Достигнут максимальный уровень');
        } else {
          toast.error(t('upgradeError') || 'Ошибка улучшения');
        }
        setIsUpgrading(false);
        return;
      }

      const res = await fetch(`${API}/business/${selectedBusiness.id}/upgrade`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` }
      });
      
      if (!res.ok) {
        const err = await res.json();
        const d = err.detail;
        // Structured "insufficient resource" error → localize into user's language.
        if (d && typeof d === 'object' && d.code === 'insufficient_resource') {
          const resName = getResourceName(d.resource, lang) || d.resource;
          const msg = (t('insufficientResourceUpgrade') || 'Insufficient {res}: need {need}, have {have}')
            .replace('{res}', resName)
            .replace('{need}', d.need)
            .replace('{have}', d.have);
          throw new Error(msg);
        }
        throw new Error((typeof d === 'string' && d) || d?.message || t('upgradeError') || 'Ошибка улучшения');
      }
      
      const data = await res.json();
      toast.success((t('upgradeSuccess') || 'Upgraded to level {level}!').replace('{level}', data.new_level));
      setShowUpgradeModal(false);
      if (refreshBalance) refreshBalance();
      fetchData();
    } catch (error) {
      toast.error(error.message);
    } finally {
      setIsUpgrading(false);
    }
  };

  // Repair business
  const handleRepair = async () => {
    if (!selectedBusiness) return;
    setIsRepairing(true);

    try {
      // Demo mode: repair is paid in demo $CITY via the isolated demo endpoint.
      if (getGameMode() === 'demo') {
        const res = await fetch(`${API}/demo/business/repair`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
        });
        const data = await res.json().catch(() => ({}));
        if (data.status === 'repaired') {
          toast.success((t('repairSuccess') || 'Repaired! Paid: {amount} $CITY').replace('{amount}', formatCity(data.paid_city ?? data.cost_city)));
        } else if (data.status === 'insufficient') {
          toast.error((t('repairInsufficientCity') || 'Not enough $CITY: need {need}').replace('{need}', formatCity(data.need)));
        } else if (data.status === 'already_full') {
          toast.info(t('repairAlreadyFull') || 'Durability is already full');
        }
        setShowRepairModal(false);
        fetchData();
        setIsRepairing(false);
        return;
      }

      const res = await fetch(`${API}/business/${selectedBusiness.id}/repair`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` }
      });

      // Safe JSON parsing: backend may return HTML/plain on 500
      const text = await res.text();
      let data;
      try { data = JSON.parse(text); } catch {
        data = { detail: res.status === 500 ? 'Ошибка сервера при ремонте. Попробуйте позже.' : (text || 'Ошибка ремонта') };
      }

      if (!res.ok) {
        throw new Error(formatErrorDetail(data.detail) || 'Ошибка ремонта');
      }

      const cost = data.cost_city ?? (data.cost_paid ? tonToCity(data.cost_paid) : 0);
      toast.success((t('repairSuccess') || 'Repaired! Paid: {amount} $CITY').replace('{amount}', formatCity(cost)));

      // Instantly update global balance so UI reflects payment without page reload
      if (updateBalance && data.new_balance !== undefined) {
        updateBalance(data.new_balance);
      }
      if (refreshBalance) refreshBalance();

      setShowRepairModal(false);
      fetchData();
    } catch (error) {
      toast.error(error.message);
    } finally {
      setIsRepairing(false);
    }
  };

  // Set patron
  const handleSetPatron = async (patronId) => {
    if (!selectedBusiness) return;
    
    try {
      const url = patronId 
        ? `${API}/business/${selectedBusiness.id}/set-patron?patron_id=${patronId}`
        : `${API}/business/${selectedBusiness.id}/set-patron`;
        
      const res = await fetch(url, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` }
      });
      
      if (!res.ok) {
        const err = await res.json();
        throw new Error(formatErrorDetail(err.detail) || 'Ошибка назначения патрона');
      }
      
      toast.success(patronId ? (t('patronAssigned') || 'Patron assigned!') : (t('patronRemoved') || 'Patron removed'));
      setShowPatronModal(false);
      fetchData();
    } catch (error) {
      toast.error(error.message);
    }
  };

  // Open buff selection for Tier 3 business
  const openBuffModal = async (biz) => {
    setBuffBusiness(biz);
    try {
      const res = await fetch(`${API}/tier3/buffs`, { headers: { Authorization: `Bearer ${token}` } });
      const data = await res.json();
      setAvailableBuffs(data.buffs || []);
    } catch {
      setAvailableBuffs([]);
    }
    setShowBuffModal(true);
  };

  const handleSetBuff = async (buffId) => {
    if (!buffBusiness) return;
    try {
      const res = await fetch(`${API}/business/${buffBusiness.id}/set-buff`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ buff_id: buffId })
      });
      if (!res.ok) { const e = await res.json(); throw new Error(formatErrorDetail(e.detail) || 'Ошибка'); }
      toast.success(t('buffSelectedToast'));
      setShowBuffModal(false);
      fetchData();
    } catch (e) { toast.error(e.message); }
  };

  const openVassalsModal = async (biz) => {
    setSelectedBusiness(biz);
    try {
      const res = await fetch(`${API}/business/${biz.id}/vassals`, { headers: { Authorization: `Bearer ${token}` } });
      const data = await res.json();
      setVassals(data.vassals || []);
    } catch { setVassals([]); }
    setShowVassalsModal(true);
  };

  // Open business details
  const openDetails = async (biz) => {
    // Reset bank settings fields; load fresh if this is a bank.
    setBankSettings({ interest_rate_percent: '', instant_fee_percent: '' });
    // Demo mode: never hit the real /business/{id} endpoint — use the demo
    // business object we already have from /api/demo/my-businesses.
    if (getGameMode() === 'demo') {
      setSelectedBusiness(biz);
      setShowDetailsModal(true);
      return;
    }
    try {
      const res = await fetch(`${API}/business/${biz.id}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      const data = await res.json();
      const merged = { ...biz, ...data };
      setSelectedBusiness(merged);
      setShowDetailsModal(true);
      if (isBankBusiness(merged)) loadBankSettings(merged.id);
    } catch (error) {
      setSelectedBusiness(biz);
      setShowDetailsModal(true);
      if (isBankBusiness(biz)) loadBankSettings(biz.id);
    }
  };

  // Get durability color
  const getDurabilityColor = (durability) => {
    if (durability >= 70) return 'bg-green-500';
    if (durability >= 40) return 'bg-yellow-500';
    return 'bg-red-500';
  };

  // ── Действия нижнего ряда карточки (РЕМОНТ / АПГРЕЙД) ────────────────────
  // Открыть модалку апгрейда для конкретного бизнеса (данные подгружаются с API).
  const openUpgradeFor = async (biz) => {
    if (isTutorialActive) { blockedTutorialToast(); return; }
    setSelectedBusiness(biz);
    setShowUpgradeModal(true);
    try {
      const url = getGameMode() === 'demo'
        ? `${API}/demo/business/upgrade-cost`
        : `${API}/business/${biz.id}/upgrade-cost`;
      const res = await fetch(url, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setSelectedBusiness(prev => ({ ...prev, upgrade_cost_data: data }));
      }
    } catch (e) { console.error('Failed to fetch upgrade cost', e); }
  };

  // Открыть модалку ремонта для конкретного бизнеса (стоимость подгружается с API).
  const openRepairFor = async (biz) => {
    if (isTutorialActive) { blockedTutorialToast(); return; }
    setSelectedBusiness(biz);
    setShowRepairModal(true);
    // Demo mode: fetch the $CITY repair quote from the isolated demo endpoint
    // (same shape as real mode's repair_cost_data) so the modal shows the cost
    // instead of an endless "Loading…".
    if (getGameMode() === 'demo') {
      try {
        const dres = await fetch(`${API}/demo/business/repair-cost`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        if (dres.ok) {
          const dq = await dres.json();
          if (dq && dq.status === 'ok') {
            setSelectedBusiness(prev => ({ ...prev, repair_cost_data: {
              cost_city: dq.cost_city,
              base_cost_city: dq.base_cost_city,
              cost_per_pct: dq.cost_per_pct,
              missing_pct: dq.missing_pct,
            }}));
          }
        }
      } catch (e) { console.error('Failed to fetch demo repair cost', e); }
      return;
    }
    // Fetch accurate repair cost from backend
    try {
      const res = await fetch(`${API}/business/${biz.id}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setSelectedBusiness(prev => ({ ...prev, repair_cost_data: data.repair }));
      }
    } catch (e) { console.error('Failed to fetch repair cost', e); }
  };

  // Contract handlers
  const openContractProposal = async (vassalInfo) => {
    setContractTarget(vassalInfo);
    setProposalType('tax_haven');
    setProposalBuff('');
    // Load buffs if not already loaded
    if (availableBuffs.length === 0) {
      try {
        const res = await fetch(`${API}/tier3/buffs`, { headers: { Authorization: `Bearer ${token}` } });
        const data = await res.json();
        setAvailableBuffs(data.buffs || []);
      } catch {}
    }
    setShowContractProposalModal(true);
  };

  const handleProposeContract = async () => {
    if (!contractTarget || !proposalType || !proposalBuff) {
      toast.error(t('selectBuffAndContractErr') || 'Select a buff and contract type');
      return;
    }
    setIsProposing(true);
    try {
      const res = await fetch(`${API}/contracts/propose`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          type: proposalType,
          vassal_business_id: contractTarget.business_id,
          patron_buff: proposalBuff,
          duration_days: proposalDuration,
          auto_renew: proposalAutoRenew,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(formatErrorDetail(data.detail) || 'Ошибка');
      toast.success(t('contractOfferSentSuccess') || 'Contract offer sent!');
      setShowContractProposalModal(false);
      fetchContracts();
    } catch (e) {
      toast.error(e.message);
    } finally {
      setIsProposing(false);
    }
  };

  const handleContractAction = async (contractId, action) => {
    try {
      const res = await fetch(`${API}/contracts/${contractId}/${action}`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      if (!res.ok) throw new Error(formatErrorDetail(data.detail) || 'Ошибка');
      toast.success(data.message || 'Готово');
      fetchContracts();
      fetchData();
    } catch (e) {
      toast.error(e.message);
    }
  };

  if (isLoading) {
    return (
      <div className="flex h-[100dvh] bg-void">
        <Sidebar user={user} />
        <div className="flex-1 flex items-center justify-center">
          <Loader2 className="w-12 h-12 text-cyber-cyan animate-spin" />
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-[100dvh] bg-void">
      <Sidebar user={user} />
      
      <div className="flex-1 overflow-hidden lg:ml-16 flex flex-col justify-between pb-[calc(68px+env(safe-area-inset-bottom,0px))] lg:pb-0">
        <div className="flex-1 min-h-0 overflow-hidden lg:overflow-y-auto scrollbar-hide">
          <div className="p-4 lg:px-6 lg:pt-2 pt-0 pb-3 lg:pb-6 h-full lg:min-h-full flex flex-col gap-[clamp(4px,1.5vh,16px)] lg:gap-6">
            {/* Redesigned top block: profile header (avatar, username, alliance,
                $CITY balance) + referrals / notifications / burger + City Pass */}
            <div className="shrink-0" data-testid="biz-header">
              <BusinessProfileHeader user={user} refreshBalance={refreshBalance} />
            </div>

            {/* T3 Active Buffs banner moved into the business-details modal
                (see showDetailsModal) so it no longer occupies vertical space
                on the main «Business» screen. */}

            {/* Businesses List. The Trial Center card now lives INSIDE this
                same grid so it appears ALONGSIDE the real business cards
                (not on its own row above them). It is hidden while the
                tutorial is running and only appears once onboarding is done. */}
            <div className="flex-1 flex min-h-0 w-full" data-testid="biz-central-wrap">
            {businesses.length === 0 ? (
              <div className="flex items-stretch gap-2 sm:gap-3 w-[calc(100vw-2rem)] lg:w-full max-w-full overflow-hidden flex-1 min-h-0 pb-3 -mb-3 lg:pb-0 lg:mb-0">
                {/* LEFT: компактная кнопка ЗАДАНИЯ (padding: the pulsing glow is not clipped by the row's overflow) */}
                <div className="flex flex-col gap-2 shrink-0 self-start pt-2.5 pl-2.5">
                  <button
                    type="button"
                    onClick={() => navigate('/tasks')}
                    data-testid="biz-side-tasks"
                    className={`relative w-14 h-14 sm:w-16 sm:h-16 rounded-xl bg-gradient-to-b from-cyber-cyan/15 to-neon-purple/10 border border-cyber-cyan/30 flex flex-col items-center justify-center gap-0.5 text-cyber-cyan hover:brightness-110 active:scale-95 transition-all ${questReady > 0 ? 'tasks-calm-pulse' : ''}`}
                    aria-label={questReady > 0 ? `${t('tasksReadyBadge')}: ${questReady}` : undefined}
                  >
                    {questReady > 0 && (
                      <span className="absolute -top-1.5 -right-1.5 min-w-[18px] h-[18px] px-1 rounded-full bg-red-500 text-white text-[10px] font-bold leading-[18px] text-center shadow-[0_0_6px_rgba(239,68,68,0.6)]"
                        data-testid="biz-side-tasks-badge">
                        {questReady > 9 ? '9+' : questReady}
                      </span>
                    )}
                    <Target className="w-5 h-5" />
                    <span className="text-[8px] sm:text-[9px] font-bold uppercase tracking-wide text-center leading-tight">{({ru:'Задания',en:'Tasks',es:'Tareas',zh:'任务',fr:'Tâches',de:'Aufgaben',ja:'タスク',ko:'작업',id:'Tugas'}[lang] || 'Задания')}</span>
                  </button>
                  {/* mini-game event — same button as «Задания», only while the event runs */}
                  <EventBanner />
                </div>

                {/* CENTER: «Открыть бизнес» — компактная светящаяся кнопка,
                    заменяет название/арт/статус, ведёт на карту (/maps) */}
                <div className="flex-1 min-w-0 basis-0 self-stretch min-h-0 flex items-center justify-center px-2">
                  <div className="biz-open-glow rounded-3xl">
                    <button
                      type="button"
                      onClick={() => navigate('/maps')}
                      data-testid="acquire-business-btn"
                      className="w-[min(58vw,190px)] rounded-3xl bg-gradient-to-br from-cyber-cyan/20 to-neon-purple/20 border border-cyber-cyan/50 flex flex-col items-center justify-center gap-2.5 py-6 px-4 text-white hover:brightness-125 active:scale-95 transition-all"
                    >
                      <Building2 className="w-9 h-9 text-cyber-cyan" />
                      <span className="text-sm font-extrabold uppercase tracking-wide text-center leading-tight">{({ru:'Открыть бизнес',en:'Open business',es:'Abrir negocio',zh:'开设企业',fr:'Ouvrir un business',de:'Business eröffnen',ja:'ビジネスを開く',ko:'사업 열기',id:'Buka bisnis'}[lang] || 'Открыть бизнес')}</span>
                    </button>
                  </div>
                </div>

                {/* RIGHT: компактная кнопка МАРКЕТПЛЕЙС */}
                <div className="flex flex-col gap-2 shrink-0 self-stretch pt-2.5 pr-2.5 pb-0 lg:pb-2.5">
                  <button
                    type="button"
                    onClick={() => navigate('/marketplace')}
                    data-testid="biz-side-marketplace"
                    className="w-14 h-14 sm:w-16 sm:h-16 rounded-xl bg-gradient-to-b from-amber-500/15 to-orange-500/10 border border-amber-400/30 flex flex-col items-center justify-center gap-0.5 text-amber-300 hover:brightness-110 active:scale-95 transition-all"
                  >
                    <Store className="w-5 h-5" />
                    <span className="text-[8px] sm:text-[9px] font-bold uppercase tracking-wide text-center leading-tight">{({ru:'Маркет',en:'Market',es:'Mercado',zh:'市场',fr:'Marché',de:'Markt',ja:'市場',ko:'마켓',id:'Pasar'}[lang] || 'Маркет')}</span>
                  </button>
                  {/* «Чат» — in the Маркет column, under it (same look as «Задания», unread count 99+).
                      The row clips (carousel); its pb-3/-mb-3 gives the glow room below the button on phones
                      without moving the button, so the blink shows on all four sides. */}
                  <button
                    type="button"
                    onClick={() => navigate('/chat')}
                    data-testid="biz-side-chat"
                    className={`relative mt-auto mb-0 lg:mb-6 w-14 h-14 sm:w-16 sm:h-16 rounded-xl bg-gradient-to-b from-fuchsia-500/15 to-cyber-cyan/10 border border-fuchsia-400/30 flex flex-col items-center justify-center gap-0.5 text-fuchsia-200 hover:brightness-110 active:scale-95 transition-all ${chatUnread > 0 ? 'tasks-calm-pulse' : ''}`}
                  >
                    {chatUnread > 0 && (
                      <span className="absolute -top-1.5 -right-1.5 min-w-[18px] h-[18px] px-1 rounded-full bg-red-500 text-white text-[10px] font-bold leading-[18px] text-center shadow-[0_0_6px_rgba(239,68,68,0.6)]"
                        data-testid="biz-side-chat-badge">
                        {chatUnread > 99 ? '99+' : chatUnread}
                      </span>
                    )}
                    <MessageCircle className="w-5 h-5" />
                    <span className="text-[8px] sm:text-[9px] font-bold uppercase tracking-wide text-center leading-tight">{({ru:'Чат',en:'Chat',es:'Chat',zh:'聊天',fr:'Chat',de:'Chat',ja:'チャット',ko:'채팅',id:'Obrolan'}[lang] || 'Чат')}</span>
                  </button>
                </div>
              </div>
            ) : (
              <>
              <div className="flex flex-col w-full flex-1 min-h-0 self-stretch">
              <div className="flex items-stretch gap-2 sm:gap-3 w-[calc(100vw-2rem)] lg:w-full max-w-full overflow-hidden flex-1 min-h-0 pb-3 -mb-3 lg:pb-0 lg:mb-0">
                {/* LEFT: компактная кнопка ЗАДАНИЯ (padding: the pulsing glow is not clipped by the row's overflow) */}
                <div className="flex flex-col gap-2 shrink-0 self-start pt-2.5 pl-2.5">
                  <button
                    type="button"
                    onClick={() => navigate('/tasks')}
                    data-testid="biz-side-tasks"
                    className={`relative w-14 h-14 sm:w-16 sm:h-16 rounded-xl bg-gradient-to-b from-cyber-cyan/15 to-neon-purple/10 border border-cyber-cyan/30 flex flex-col items-center justify-center gap-0.5 text-cyber-cyan hover:brightness-110 active:scale-95 transition-all ${questReady > 0 ? 'tasks-calm-pulse' : ''}`}
                    aria-label={questReady > 0 ? `${t('tasksReadyBadge')}: ${questReady}` : undefined}
                  >
                    {questReady > 0 && (
                      <span className="absolute -top-1.5 -right-1.5 min-w-[18px] h-[18px] px-1 rounded-full bg-red-500 text-white text-[10px] font-bold leading-[18px] text-center shadow-[0_0_6px_rgba(239,68,68,0.6)]"
                        data-testid="biz-side-tasks-badge">
                        {questReady > 9 ? '9+' : questReady}
                      </span>
                    )}
                    <Target className="w-5 h-5" />
                    <span className="text-[8px] sm:text-[9px] font-bold uppercase tracking-wide text-center leading-tight">{({ru:'Задания',en:'Tasks',es:'Tareas',zh:'任务',fr:'Tâches',de:'Aufgaben',ja:'タスク',ko:'작업',id:'Tugas'}[lang] || 'Задания')}</span>
                  </button>
                  {/* mini-game event — same button as «Задания», only while the event runs */}
                  <EventBanner />
                </div>

                {/* CENTER: business skin carousel (swipe только скин) */}
                <div className="flex-1 min-w-0 basis-0 min-h-0 flex flex-col self-stretch">
                  {/* Название активного бизнеса — на верхней линии, на одном
                      уровне с боковыми кнопками ЗАДАНИЯ/МАРКЕТ, по центру. */}
                  {(() => {
                    const _ab = businesses[activeBizIndex] || businesses[0];
                    const _abName = _ab
                      ? (_ab.config?.name?.[lang] || _ab.config?.name?.en || _ab.config?.name?.ru || tBusiness(_ab.business_type, lang))
                      : '';
                    return (
                      <motion.h3
                        key={`title-${_ab?.id || 'none'}`}
                        initial={{ opacity: 0, y: -6 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ duration: 0.3, ease: 'easeOut' }}
                        className="shrink-0 w-full text-center font-extrabold text-white text-[clamp(1rem,4.6vw,1.45rem)] uppercase tracking-wide leading-tight px-2 pt-1 min-h-14 sm:min-h-16 flex items-center justify-center break-words"
                        data-testid="active-business-name"
                      >
                        {_abName}
                      </motion.h3>
                    );
                  })()}
                  <div className="relative flex-1 min-h-0 flex">
                  <div
                    ref={bizCarouselRef}
                    onScroll={handleBizScroll}
                    className="flex gap-4 w-full h-full min-w-0 overflow-x-auto snap-x snap-mandatory scroll-smooth scrollbar-hide"
                  >
                {businesses.map((biz) => {
                  // ── Данные для скина ─────────────────────────────────────
                  // the player's chosen skin -> otherwise the building as on the city map -> otherwise a standard skin
                  const chosenSkin = biz.skin_group && biz.skin_group !== 'standard'
                    ? resolveSkinUrl(skinsIndex, biz.skin_group, biz.business_type, biz.level) : null;
                  const skinUrl = chosenSkin || citySpriteUrl(biz.business_type, biz.level || 0)
                    || resolveSkinUrl(skinsIndex, biz.skin_group, biz.business_type, biz.level);
                  const bizName = biz.config?.name?.[lang] || biz.config?.name?.en || biz.config?.name?.ru || tBusiness(biz.business_type, lang);
                  const bizIcon = biz.config?.icon || '🏢';
                  // Статус бизнеса (для индикатора под скином)
                  let _bizStatus = 'working';
                  if (biz.level === 0 || biz.is_zero_business) {
                    _bizStatus = biz.durability <= 0 ? 'stopped' : (biz.work_status === 'idle' ? 'idle' : 'working');
                  } else if (biz.is_seized) {
                    _bizStatus = 'seized';
                  } else if (biz.on_sale) {
                    _bizStatus = 'on_sale';
                  } else if (biz.durability <= 0) {
                    _bizStatus = 'stopped';
                  } else if (biz.work_status === 'idle') {
                    _bizStatus = 'idle';
                  } else if (biz.work_status === 'stopped' || biz.work_status === 'halted') {
                    _bizStatus = 'stopped';
                  }
                  return (
                  <motion.div
                    key={biz.id}
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="group shrink-0 w-full snap-start h-full flex flex-col items-center justify-center gap-[clamp(6px,2vh,16px)] px-2"
                    data-testid={biz.tutorial ? 'tutorial-business-card' : `business-card-${biz.id}`}
                  >
                    {/* ── СКИН БИЗНЕСА (клик → модалка с инфо) ─────────────── */}
                    <button
                      type="button"
                      onClick={() => {
                        if (isTutorialActive) { blockedTutorialToast(); return; }
                        openDetails(biz);
                      }}
                      disabled={isTutorialActive}
                      aria-label={bizName}
                      className="relative flex items-center justify-center w-full flex-1 min-h-0 overflow-hidden focus:outline-none active:scale-[0.98] transition-transform disabled:cursor-not-allowed"
                      data-testid={`business-image-${biz.id}`}
                    >
                      {/* hidden testid to keep tier/level info reachable for tests */}
                      <span className="sr-only" data-testid={`business-tier-level-${biz.id}`}>
                        {t('tierLabel')} {biz.config?.tier || 1} • {t('levelLabel')} {biz.level ?? 1}
                      </span>

                      {skinUrl && (
                        <img
                          src={skinUrl}
                          alt={bizName}
                          className="biz-skin-img biz-art-float drop-shadow-[0_10px_20px_rgba(0,0,0,0.55)] pointer-events-none"
                          loading="lazy"
                          onError={(e) => {
                            e.currentTarget.style.display = 'none';
                            const fb = e.currentTarget.nextSibling;
                            if (fb) fb.style.display = 'block';
                          }}
                        />
                      )}
                      <span className="biz-art-float leading-none pointer-events-none text-[clamp(3rem,18vh,5rem)]" style={{ display: skinUrl ? 'none' : 'block' }}>{bizIcon}</span>
                    </button>

                    {/* ── Статус бизнеса ПОД скином ────────────────────────── */}
                    <div className="flex justify-center shrink-0 -mt-1">
                      <Badge data-testid={`work-status-${biz.id}`} className={
                        _bizStatus === 'working' ? 'bg-green-500/20 text-green-400'
                        : _bizStatus === 'on_sale' ? 'bg-amber-500/20 text-amber-400'
                        : _bizStatus === 'seized' ? 'bg-red-600/30 text-red-300 border border-red-500/40'
                        : _bizStatus === 'idle' ? 'bg-yellow-500/20 text-yellow-400'
                        : 'bg-red-500/20 text-red-400'
                      }>
                        {_bizStatus === 'working' ? t('active')
                         : _bizStatus === 'on_sale' ? t('onSale')
                         : _bizStatus === 'seized' ? (t('seizedStatus') || 'For sale (Seized)')
                         : _bizStatus === 'idle' ? (t('idle') || 'Idle') : t('stopped')}
                      </Badge>
                    </div>
                    {/* only the status under the picture; a missing input makes the «per day» chip blink red */}
                  </motion.div>
                  );
                })}
              </div>
              </div>{/* end relative carousel wrapper */}
              {/* Точки-карусель ПОД скином (фиксированы, не свайпаются) */}
              {businesses.length > 1 && (
                <div className="flex justify-center gap-2 pt-2 shrink-0" data-testid="biz-carousel-dots">
                  {businesses.map((_, i) => (
                    <button
                      key={i}
                      type="button"
                      aria-label={`Бизнес ${i + 1}`}
                      onClick={() => {
                        const el = bizCarouselRef.current;
                        const ch = el && el.children ? el.children[i] : null;
                        if (ch) ch.scrollIntoView({ behavior: 'smooth', inline: 'start', block: 'nearest' });
                      }}
                      data-testid={`biz-carousel-dot-${i}`}
                      className={`h-2 rounded-full transition-all duration-300 ${i === activeBizIndex ? 'w-6 bg-cyber-cyan' : 'w-2 bg-white/30'}`}
                    />
                  ))}
                </div>
              )}
                </div>{/* end center column (карусель + точки) */}

                {/* RIGHT: компактная кнопка МАРКЕТПЛЕЙС */}
                <div className="flex flex-col gap-2 shrink-0 self-stretch pt-2.5 pr-2.5 pb-0 lg:pb-2.5">
                  <button
                    type="button"
                    onClick={() => navigate('/marketplace')}
                    data-testid="biz-side-marketplace"
                    className="w-14 h-14 sm:w-16 sm:h-16 rounded-xl bg-gradient-to-b from-amber-500/15 to-orange-500/10 border border-amber-400/30 flex flex-col items-center justify-center gap-0.5 text-amber-300 hover:brightness-110 active:scale-95 transition-all"
                  >
                    <Store className="w-5 h-5" />
                    <span className="text-[8px] sm:text-[9px] font-bold uppercase tracking-wide text-center leading-tight">{({ru:'Маркет',en:'Market',es:'Mercado',zh:'市场',fr:'Marché',de:'Markt',ja:'市場',ko:'마켓',id:'Pasar'}[lang] || 'Маркет')}</span>
                  </button>
                  {/* «Чат» — in the Маркет column, under it (same look as «Задания», unread count 99+).
                      The row clips (carousel); its pb-3/-mb-3 gives the glow room below the button on phones
                      without moving the button, so the blink shows on all four sides. */}
                  <button
                    type="button"
                    onClick={() => navigate('/chat')}
                    data-testid="biz-side-chat"
                    className={`relative mt-auto mb-0 lg:mb-6 w-14 h-14 sm:w-16 sm:h-16 rounded-xl bg-gradient-to-b from-fuchsia-500/15 to-cyber-cyan/10 border border-fuchsia-400/30 flex flex-col items-center justify-center gap-0.5 text-fuchsia-200 hover:brightness-110 active:scale-95 transition-all ${chatUnread > 0 ? 'tasks-calm-pulse' : ''}`}
                  >
                    {chatUnread > 0 && (
                      <span className="absolute -top-1.5 -right-1.5 min-w-[18px] h-[18px] px-1 rounded-full bg-red-500 text-white text-[10px] font-bold leading-[18px] text-center shadow-[0_0_6px_rgba(239,68,68,0.6)]"
                        data-testid="biz-side-chat-badge">
                        {chatUnread > 99 ? '99+' : chatUnread}
                      </span>
                    )}
                    <MessageCircle className="w-5 h-5" />
                    <span className="text-[8px] sm:text-[9px] font-bold uppercase tracking-wide text-center leading-tight">{({ru:'Чат',en:'Chat',es:'Chat',zh:'聊天',fr:'Chat',de:'Chat',ja:'チャット',ko:'채팅',id:'Obrolan'}[lang] || 'Чат')}</span>
                  </button>
                </div>
              </div>{/* end central block flex row */}
              </div>{/* end flex-col wrapper (карусель) */}
              {/* Панели активного бизнеса вынесены в закреплённый нижний блок
                  (над кнопками действий) — см. блок ниже. */}
              </>
            )}
            </div>{/* end biz-central-wrap */}


          </div>
        </div>

        {/* Нижний ряд действий — на ВСЮ ширину экрана, закреплён внизу над
            BottomNav, поэтому виден всегда, на любой высоте экрана:
            РЕМОНТ | НАЧАТЬ СМЕНУ (8 ч) | АПГРЕЙД. У каждой карточки — свои
            данные: действия применяются к видимому бизнесу. */}
        {!isLoading && (
          <div
            className="shrink-0 px-4 lg:px-6 pt-1.5 pb-[calc(env(safe-area-inset-bottom,0px)+0.5rem)] lg:pb-4 bg-transparent"
            data-testid="biz-action-row-pinned"
          >
          {/* ── ФИКСИРОВАННЫЕ панели активного бизнеса (НЕ перелистываются,
                 прикреплены к кнопкам действий с небольшим отступом). Когда
                 бизнеса ещё нет — панели показываются с заглушками (0 / —). ── */}
          {(() => {
            const abiz = businesses[activeBizIndex] || businesses[0] || null;
            // Authoritative economics come from the backend `production` object
            // (durability × patron × buff already applied). We do NOT recompute
            // locally anymore — that caused wrong /h and /day figures.
            const _prod = abiz?.production || {};
            const _perDay = Number(_prod.production ?? 0);
            const _hourlyRaw = _perDay / 24;
            const _hourly = (_hourlyRaw > 0 && _hourlyRaw < 100)
              ? Number(_hourlyRaw.toFixed(2))
              : Math.round(_hourlyRaw);
            // Per-resource consumption PER DAY (buffed), authoritative.
            const _consumeSrc = (_prod.consumption_breakdown && Object.keys(_prod.consumption_breakdown).length)
              ? _prod.consumption_breakdown
              : (_prod.consumption || {});
            const _consumeEntries = Object.entries(_consumeSrc)
              .filter(([, v]) => Number(v) > 0)
              .map(([r, v]) => [r, Number(v) < 100 ? Number(Number(v).toFixed(2)) : Math.round(Number(v))]);
            const _produceResId = _prod.produces_resource || abiz?.config?.produces;
            const _produceIcon = _produceResId
              ? (getResource(_produceResId, lang)?.icon || resourceIcons[_produceResId] || '📦')
              : '📦';
            const _consumeIcon = _consumeEntries.length
              ? (getResource(_consumeEntries[0][0], lang)?.icon || resourceIcons[_consumeEntries[0][0]] || '📦')
              : '📦';
            const HOUR_SHORT = { ru: 'ч', en: 'h', es: 'h', zh: '时', fr: 'h', de: 'Std.', ja: '時', ko: '시', id: 'j' };
            const DAY_SHORT = { ru: 'сут', en: 'day', es: 'día', zh: '天', fr: 'j', de: 'Tag', ja: '日', ko: '일', id: 'hr' };
            const hourShort = HOUR_SHORT[lang] || HOUR_SHORT.ru;
            const dayShort = DAY_SHORT[lang] || DAY_SHORT.ru;
            // Placeholder-friendly display values (empty state shows 0 / —).
            const _idSuffix = abiz?.id || 'empty';
            const _dur = abiz ? (abiz.durability ?? 0) : 0;
            const _hasStorage = !!(abiz && abiz.storage_info && abiz.storage_info.capacity > 0);
            const _storageText = _hasStorage ? `${abiz.storage_info.used}/${abiz.storage_info.capacity}` : '— / —';
            const _incomeText = abiz ? `+${_hourly}/${hourShort}` : '0';
            const _hasConsume = !!(abiz && _consumeEntries.length > 0);
            const _shortage = (abiz && !abiz.tutorial && Array.isArray(abiz.missing_resources)) ? abiz.missing_resources : [];
            const _expenseText = _hasConsume ? `−${_consumeEntries[0][1]}/${dayShort}` : '0';
            return (
              <motion.div
                key={`panels-${_idSuffix}`}
                initial={{ opacity: 0.35, scale: 0.985, y: 4 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                transition={{ duration: 0.32, ease: 'easeOut' }}
                className="w-full max-w-[29rem] mx-auto flex flex-col gap-[clamp(4px,1vh,8px)] mb-[clamp(6px,1.5vh,12px)]"
                data-testid="biz-fixed-panels"
              >
                {/* Прочность */}
                <div className="rounded-2xl bg-black/40 border border-cyber-cyan/30 shadow-[0_0_18px_rgba(34,211,238,0.12)] px-4 py-2.5">
                  <div className="flex justify-between items-center mb-1.5">
                    <span className="text-white/80 flex items-center gap-2 font-semibold text-sm">
                      <Wrench className="w-4 h-4 text-cyber-cyan" /> {t('durabilityLabel')}:
                    </span>
                    <span className={`font-extrabold text-base ${_dur < 30 ? 'text-red-400' : 'text-white'}`} data-testid={`durability-value-${_idSuffix}`}>
                      {_dur.toFixed(1)}%
                    </span>
                  </div>
                  <Progress value={_dur} className="h-2.5" />
                  {abiz && _dur < 30 && (
                    <div className="flex items-center gap-1 text-red-400 text-xs mt-1.5">
                      <AlertCircle className="w-3 h-3" />
                      {t('needsRepair')}
                    </div>
                  )}
                </div>

                {/* Склад — показывается всегда; без бизнеса пишет «— / —» */}
                <div className="rounded-2xl bg-black/40 border border-cyber-cyan/30 shadow-[0_0_18px_rgba(34,211,238,0.12)] px-4 py-2.5 flex items-center justify-center gap-2" data-testid={`storage-panel-${_idSuffix}`}>
                  <Package className="w-5 h-5 text-amber-400 shrink-0" />
                  <span className="text-white font-extrabold text-sm uppercase tracking-wide">
                    {t('warehouseLabel')}: {_storageText}
                  </span>
                </div>
                {abiz?.storage_info?.is_full && (
                  <div className="text-red-400 text-xs flex items-center gap-1 justify-center">
                    <AlertCircle className="w-3 h-3" />
                    {t('warehouseFullMsg')}
                  </div>
                )}

                {/* Чипы выпуска/потребления — показываются всегда; без бизнеса «0» */}
                <div className="flex gap-2">
                  <div className="flex-1 min-w-0 rounded-2xl bg-black/40 border border-green-400/30 shadow-[0_0_14px_rgba(74,222,128,0.12)] px-3 py-2.5 flex items-center justify-center gap-2" data-testid={`income-chip-${_idSuffix}`}>
                    <span className="text-lg leading-none">{_produceIcon}</span>
                    <span className="text-green-400 font-extrabold text-base whitespace-nowrap">{_incomeText}</span>
                  </div>
                  {_shortage.length > 0 ? (
                    <button type="button" onClick={() => setShortageFor(_shortage)} aria-label={MISSING_HINT_LABELS.title[lang] || MISSING_HINT_LABELS.title.en}
                      className="res-shortage flex-1 min-w-0 rounded-2xl bg-black/40 border px-3 py-2.5 flex items-center justify-center gap-2 active:scale-95 transition-transform" data-testid={`expense-chip-${_idSuffix}`}>
                      <span className="text-lg leading-none">{getResource(_shortage[0].resource, lang)?.icon || _consumeIcon}</span>
                      <span className="text-red-300 font-extrabold text-base whitespace-nowrap">{_expenseText}</span>
                      <AlertCircle className="w-4 h-4 text-red-400 shrink-0" />
                    </button>
                  ) : (
                  <div className="flex-1 min-w-0 rounded-2xl bg-black/40 border border-sky-400/30 shadow-[0_0_14px_rgba(56,189,248,0.12)] px-3 py-2.5 flex items-center justify-center gap-2" data-testid={`expense-chip-${_idSuffix}`}>
                    <span className="text-lg leading-none">{_consumeIcon}</span>
                    <span className="text-sky-400 font-extrabold text-base whitespace-nowrap">{_expenseText}</span>
                  </div>
                  )}
                </div>

                {/* Level-0 lease countdown */}
                {abiz && abiz.level === 0 && abiz.expires_at && (
                  <ZeroLeaseTimer expiresAt={abiz.expires_at} t={t} />
                )}
              </motion.div>
            );
          })()}
          {(businesses[activeBizIndex] || businesses[0]) && (() => {
            const activeBiz = businesses[activeBizIndex] || businesses[0];
            // Кнопка «Ремонт» всегда активна (кроме обучения) — выполняет ту же
            // логику, что и прежняя кнопка ремонта в карточке (openRepairFor).
            const repairDisabled = isTutorialActive;
            const upgradeDisabled = isTutorialActive || (activeBiz.level ?? 1) >= 10 || !!activeBiz.rental_id;   // a rented business can't be upgraded
            const ACTION_LABELS = {
              repair: { ru: 'Ремонт', en: 'Repair', es: 'Reparar', zh: '修理', fr: 'Réparer', de: 'Reparieren', ja: '修理', ko: '수리', id: 'Perbaiki' },
              upgrade: { ru: 'Апгрейд', en: 'Upgrade', es: 'Mejorar', zh: '升级', fr: 'Améliorer', de: 'Upgrade', ja: '強化', ko: '업그레이드', id: 'Tingkatkan' },
            };
            const al = (k) => (ACTION_LABELS[k][lang] || ACTION_LABELS[k].ru);
            return (
              <div className="flex items-stretch gap-2" data-testid="biz-action-row">
                {/* РЕМОНТ */}
                <button
                  type="button"
                  onClick={() => openRepairFor(activeBiz)}
                  disabled={repairDisabled}
                  data-testid={`action-repair-${activeBiz.id}`}
                  className="w-16 sm:w-20 shrink-0 min-h-[3.25rem] rounded-xl bg-indigo-500/15 border border-indigo-400/30 flex flex-col items-center justify-center gap-0.5 text-indigo-300 hover:brightness-110 active:scale-95 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  <Wrench className="w-4 h-4" />
                  <span className="text-[8px] sm:text-[10px] font-bold uppercase tracking-wide leading-tight">{al('repair')}</span>
                </button>

                {/* НАЧАТЬ СМЕНУ (8 ч) — центральная CTA-кнопка */}
                <ShiftButton
                  business={activeBiz}
                  onChanged={refreshBusinessesSilently}
                  inline
                />

                {/* АПГРЕЙД */}
                <button
                  type="button"
                  onClick={() => openUpgradeFor(activeBiz)}
                  disabled={upgradeDisabled}
                  data-testid={`action-upgrade-${activeBiz.id}`}
                  className="w-16 sm:w-20 shrink-0 min-h-[3.25rem] rounded-xl bg-amber-500/15 border border-amber-400/30 flex flex-col items-center justify-center gap-0.5 text-amber-300 hover:brightness-110 active:scale-95 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  <ArrowUpFromLine className="w-4 h-4" />
                  <span className="text-[8px] sm:text-[10px] font-bold uppercase tracking-wide leading-tight">{al('upgrade')}</span>
                </button>
              </div>
            );
          })()}
          </div>
        )}
      </div>

      {/* Upgrade Modal */}
      <Dialog open={showUpgradeModal} onOpenChange={setShowUpgradeModal}>
        <DialogContent className="bg-void border-white/10">
          <DialogHeader>
            <DialogTitle className="text-white flex items-center gap-2">
              <ArrowUp className="w-5 h-5 text-blue-400" />
              {t('upgradeBusinessTitle')}
            </DialogTitle>
          </DialogHeader>
          
          {selectedBusiness && (
            <div className="space-y-4">
              <div className="flex items-center gap-3 p-4 bg-white/5 rounded-xl">
                <span className="text-3xl">{selectedBusiness.config?.icon}</span>
                <div>
                  <div className="text-white font-bold">
                    {tBusiness(selectedBusiness.business_type, lang) || selectedBusiness.config?.name?.[lang] || selectedBusiness.config?.name?.en || selectedBusiness.business_type}
                  </div>
                  <div className="text-text-muted text-sm">
                    {t('levelLabel')} {selectedBusiness.level} → {selectedBusiness.level + 1}
                  </div>
                </div>
              </div>
              
              <div className="space-y-2">
                {/* Production */}
                <div className="flex justify-between text-sm">
                  <span className="text-text-muted">{t('upgradeProduction')}:</span>
                  <span className="text-green-400">
                    {selectedBusiness.upgrade_cost_data?.current_production || '?'} → {selectedBusiness.upgrade_cost_data?.next_production || '?'} {t('unitsShort') || 'ед.'}
                  </span>
                </div>
                {/* Consumption */}
                {selectedBusiness.upgrade_cost_data?.next_consumption && Object.entries(selectedBusiness.upgrade_cost_data.next_consumption).map(([res, amt]) => (
                  <div key={res} className="flex justify-between text-sm">
                    <span className="text-text-muted">{t('upgradeConsumes')} {getResource(res, lang)?.icon} {tResource(res, lang)}:</span>
                    <span className="text-red-400">{amt} {t('unitsPerDayShort')}</span>
                  </div>
                ))}
                {/* Storage */}
                <div className="flex justify-between text-sm">
                  <span className="text-text-muted">{t('upgradeStorage')}:</span>
                  <span className="text-white">
                    {selectedBusiness.upgrade_cost_data?.current_storage || '?'} → {selectedBusiness.upgrade_cost_data?.next_storage || '?'}
                  </span>
                </div>
              </div>
              
              <div className="p-3 bg-blue-500/10 rounded-lg space-y-2">
                <div className="text-xs text-text-muted mb-1">{t('upgradeCostLabel')}:</div>
                <div className="flex justify-between items-center">
                  <span className="text-text-muted text-sm">$CITY:</span>
                  <span className="text-xl font-bold text-blue-400">
                    {formatCity(selectedBusiness.upgrade_cost_data?.cost?.city || 0)} $CITY
                  </span>
                </div>
                {/* Resource requirements */}
                {selectedBusiness.upgrade_cost_data?.resource_meta && (
                  <div className="flex justify-between items-center border-t border-white/10 pt-2">
                    <span className="text-text-muted text-sm">
                      {selectedBusiness.upgrade_cost_data.resource_meta.icon} {tResource(selectedBusiness.upgrade_cost_data.cost?.resource_type, lang) || selectedBusiness.upgrade_cost_data.resource_meta.name_ru}:
                    </span>
                    <span className="font-bold text-amber-400">
                      {selectedBusiness.upgrade_cost_data.cost?.resource_amount || 0} {t('piecesShort')}
                    </span>
                  </div>
                )}
                {/* Level-0 → Level-1: MAIN ACCOUNT unlock note (localized, 9 langs) */}
                {selectedBusiness.upgrade_cost_data?.zero_to_one && (
                  <div className="border-t border-white/10 pt-2 text-center text-sm font-bold text-yellow-400 uppercase tracking-wide" data-testid="zero-unlock-note">
                    {ZERO_UNLOCK_I18N[lang] || ZERO_UNLOCK_I18N.en}
                  </div>
                )}
              </div>
            </div>
          )}
          
          <DialogFooter className="flex-col sm:flex-row gap-2">
            <Button 
              onClick={handleUpgrade} 
              className="bg-blue-600 w-full"
              disabled={isUpgrading}
            >
              {isUpgrading ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : null}
              {t('upgradeAction')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Repair Modal */}
      <Dialog open={showRepairModal} onOpenChange={setShowRepairModal}>
        <DialogContent className="bg-void border-white/10">
          <DialogHeader>
            <DialogTitle className="text-white flex items-center gap-2">
              <Wrench className="w-5 h-5 text-yellow-400" />
              {t('repairBusinessTitle')}
            </DialogTitle>
          </DialogHeader>
          
          {selectedBusiness && (
            <div className="space-y-4">
              <div className="flex items-center gap-3 p-4 bg-white/5 rounded-xl">
                <span className="text-3xl">{selectedBusiness.config?.icon}</span>
                <div>
                  <div className="text-white font-bold">
                    {tBusiness(selectedBusiness.business_type, lang) || selectedBusiness.config?.name?.[lang] || selectedBusiness.config?.name?.en || selectedBusiness.business_type}
                  </div>
                  <div className="text-red-400 text-sm">
                    {t('durabilityLabel') || 'Прочность'}: {selectedBusiness.durability?.toFixed(1)}%
                  </div>
                </div>
              </div>
              
              <div className="p-3 bg-yellow-500/10 rounded-lg">
                <div className="flex justify-between text-sm mb-2">
                  <span className="text-text-muted">{t('currentDurability')}:</span>
                  <span className="text-yellow-400">{selectedBusiness.durability?.toFixed(1)}%</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-text-muted">{t('afterRepair')}:</span>
                  <span className="text-green-400">100%</span>
                </div>
              </div>
              
              <div className="p-3 bg-white/5 rounded-lg">
                <div className="text-xs text-text-muted mb-1">{t('repairCostLabel')}:</div>
                {selectedBusiness.repair_cost_data?.cost_city !== undefined ? (
                  <>
                    {selectedBusiness.repair_cost_data?.base_cost_city !== undefined
                      && Math.abs(selectedBusiness.repair_cost_data.base_cost_city - selectedBusiness.repair_cost_data.cost_city) > 0.005 ? (
                      <div className="flex items-baseline gap-2" data-testid="repair-cost-display">
                        <span className="text-sm line-through text-text-muted/70" data-testid="repair-cost-base">
                          {formatCity(selectedBusiness.repair_cost_data.base_cost_city, selectedBusiness.repair_cost_data.base_cost_city < 100 ? 2 : 0)} $CITY
                        </span>
                        <span className="text-xl font-bold text-green-400" data-testid="repair-cost-final">
                          {formatCity(selectedBusiness.repair_cost_data.cost_city, selectedBusiness.repair_cost_data.cost_city < 100 ? 2 : 0)} $CITY
                        </span>
                      </div>
                    ) : (
                      <div className="text-xl font-bold text-yellow-400" data-testid="repair-cost-display">
                        {formatCity(selectedBusiness.repair_cost_data.cost_city, selectedBusiness.repair_cost_data.cost_city < 100 ? 2 : 0)} $CITY
                      </div>
                    )}
                  </>
                ) : (
                  <span className="text-sm text-text-muted">{t('loading') || 'Loading...'}</span>
                )}
                {selectedBusiness.repair_cost_data?.cost_per_pct !== undefined && (
                  <div className="text-xs text-text-muted mt-1">
                    {selectedBusiness.repair_cost_data.cost_per_pct} $CITY × {selectedBusiness.repair_cost_data.missing_pct}%
                  </div>
                )}
                {Array.isArray(selectedBusiness.repair_cost_data?.applied_buffs)
                  && selectedBusiness.repair_cost_data.applied_buffs.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1" data-testid="repair-applied-buffs">
                    {selectedBusiness.repair_cost_data.applied_buffs.map((b, i) => {
                      const localizedName =
                        tBuff(b.id, 'name', lang) ||
                        tResourceBuff(b.id, 'name', lang) ||
                        tContract(b.id, 'name', lang) ||
                        b.name;
                      return (
                      <span
                        key={b.id || i}
                        className="text-[11px] px-2 py-0.5 rounded bg-cyber-cyan/10 text-cyber-cyan border border-cyber-cyan/20"
                      >
                        {b.icon} {localizedName} −{b.percent}%
                      </span>
                    );})}
                  </div>
                )}
              </div>
              
              <p className="text-xs text-text-muted">
                {t('repairProductionStops')}
              </p>
            </div>
          )}
          
          <DialogFooter className="flex-col gap-2">
            {(() => {
              const durability = selectedBusiness?.durability ?? 100;
              const missingPct = selectedBusiness?.repair_cost_data?.missing_pct ?? (100 - durability);
              // Ремонт запрещён, если недостающая прочность меньше 1%
              const repairTooSmall = missingPct < 1;
              const tooSmallMsg = ({
                ru: 'Ремонт доступен при износе от 1%',
                en: 'Repair is available from 1% wear',
                es: 'Reparación disponible desde 1% de desgaste',
                zh: '磨损达到 1% 才能维修',
                fr: 'Réparation possible à partir de 1% d’usure',
                de: 'Reparatur ab 1% Abnutzung möglich',
                ja: '摩耗1%から修理できます',
                ko: '마모 1%부터 수리할 수 있습니다',
                id: 'Perbaikan tersedia mulai dari keausan 1%',
              }[lang] || 'Ремонт доступен при износе от 1%');
              return (
                <>
                  {repairTooSmall && (
                    <p className="text-xs text-amber-400 text-center w-full" data-testid="repair-too-small-note">
                      {tooSmallMsg}
                    </p>
                  )}
                  <Button
                    onClick={handleRepair}
                    className="bg-yellow-600 w-full"
                    disabled={isRepairing || repairTooSmall}
                    data-testid="repair-confirm-btn"
                  >
                    {isRepairing ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : null}
                    {t('repairAction') || 'Отремонтировать'}
                  </Button>
                </>
              );
            })()}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Patron modal removed — vassal/patron selection system has been removed. */}

      {/* Details Modal */}
      <Dialog open={showDetailsModal} onOpenChange={setShowDetailsModal}>
        <DialogContent className="bg-void border-white/10 max-w-lg">
          <DialogHeader>
            <DialogTitle className="text-white flex items-center gap-2">
              <Settings2 className="w-5 h-5 text-cyber-cyan" />
              {t('businessDetailsTitle')}
            </DialogTitle>
          </DialogHeader>
          
          {selectedBusiness && (
            <div className="space-y-4">
              <div className="flex items-center gap-4 p-4 bg-white/5 rounded-xl">
                <span className="text-4xl">{selectedBusiness.config?.icon}</span>
                <div>
                  <h3 className="text-xl font-bold text-white">
                    {selectedBusiness.config?.name?.[lang] || selectedBusiness.config?.name?.en || selectedBusiness.config?.name?.ru || tBusiness(selectedBusiness.business_type, lang)}
                  </h3>
                  <div className="flex gap-2 mt-1">
                    <Badge className={TIER_COLORS[selectedBusiness.config?.tier || 1]}>
                      {t('tierLabel')} {selectedBusiness.config?.tier}
                    </Badge>
                    <Badge variant="outline">{t('levelLabel') || 'Уровень'} {selectedBusiness.level}</Badge>
                  </div>
                </div>
              </div>
              
              <div className="grid grid-cols-2 gap-3">
                <div className="p-3 bg-white/5 rounded-lg">
                  <div className="text-xs text-text-muted">{t('durabilityLabel')}</div>
                  <div className="text-lg font-bold text-white">
                    {selectedBusiness.durability?.toFixed(1)}%
                  </div>
                </div>
                <div className="p-3 bg-white/5 rounded-lg">
                  <div className="text-xs text-text-muted">{t('taxLabel') || t('tax') || 'Tax'}</div>
                  {(() => {
                    const baseTaxPct = (selectedBusiness.production?.tax_rate || 0.15) * 100;
                    const reductionPct = (activeBuffMults?.trade_tax_reduction ?? 0) * 100;
                    const feeMult = activeBuffMults?.trade_fee_multiplier ?? 1.0;
                    const reduced = Math.max(0, baseTaxPct - reductionPct);
                    const effectivePct = reduced * feeMult;
                    const hasBuff = Math.abs(effectivePct - baseTaxPct) > 0.0001;
                    if (!hasBuff) {
                      return (
                        <div className="text-lg font-bold text-yellow-400" data-testid="biz-tax-display">
                          {baseTaxPct.toFixed(0)}%
                        </div>
                      );
                    }
                    return (
                      <div className="flex items-baseline gap-2" data-testid="biz-tax-display">
                        <span className="text-sm line-through text-text-muted/60">{baseTaxPct.toFixed(0)}%</span>
                        <span className="text-lg font-bold text-emerald-400">{effectivePct.toFixed(2)}%</span>
                      </div>
                    );
                  })()}
                </div>
                <div className="p-3 bg-white/5 rounded-lg col-span-2">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-xs text-text-muted">{t('warehouseLabel')}</div>
                      <div className="text-lg font-bold text-white">
                        {selectedBusiness.storage_info?.used || 0} / {selectedBusiness.storage_info?.capacity || selectedBusiness.storage?.capacity || 0}
                      </div>
                    </div>
                    {!selectedBusiness.rental_id && <SkinPicker
                      business={selectedBusiness}
                      lang={lang}
                      token={token}
                      onApplied={(g) => {
                        // Мгновенно обновляем скин: и в открытой модалке, и в
                        // массиве карточек — картинка на карточке меняется сразу.
                        setSelectedBusiness((b) => b ? { ...b, skin_group: g } : b);
                        setBusinesses((prev) => prev.map((b) =>
                          b.id === selectedBusiness.id ? { ...b, skin_group: g } : b
                        ));
                      }}
                    />}
                  </div>
                </div>
              </div>

              {/* === T3 Active Buffs (moved here from the main screen) === */}
              {((resourceBuffsData.active || []).length > 0 || (selectedBusiness.active_buffs || []).some((x) => x.kind !== 'resource')) && (
                <div data-testid="active-buffs-banner">
                  <div className="rounded-xl border border-purple-500/30 bg-purple-500/5 p-4">
                    <div className="flex items-center gap-2 mb-3">
                      <Shield className="w-5 h-5 text-purple-400" />
                      <h3 className="text-sm font-bold text-white uppercase tracking-wider">{t('activeBuffsTitle') || 'Активные бафы'}</h3>
                      <Badge className="bg-purple-500/20 text-purple-300 border-purple-500/30 ml-auto">
                        {(resourceBuffsData.active || []).length} / 2
                      </Badge>
                    </div>
                    <div className="grid grid-cols-1 gap-3">
                      {/* account boosters + contract buff (auto-start of shifts, warehouse protection, …) */}
                      {(selectedBusiness.active_buffs || []).filter((x) => x.kind !== 'resource' && (!x.until || new Date(x.until) > new Date())).map((x, i) => (
                        <div key={`bst-${i}`} className="flex items-center gap-3 p-3 rounded-lg bg-white/5 border border-purple-500/20" data-testid={`active-booster-${x.kind}`}>
                          <div className="text-2xl">{x.icon}</div>
                          <div className="flex-1 min-w-0">
                            <div className="font-bold text-white text-sm">{x.kind === 'auto_shift' ? t('buff_auto_shift') : x.kind === 'warehouse_guard' ? t('buff_guard') : (x.name || t('buff_business'))}</div>
                          </div>
                          {x.until && (
                            <div className="text-right">
                              <div className="text-xs text-purple-300 font-mono font-bold">{buffTimeLeft(x.until, t)}</div>
                              <div className="text-[10px] text-text-muted">{t('remainingShort') || 'осталось'}</div>
                            </div>
                          )}
                        </div>
                      ))}
                      {resourceBuffsData.active.map((b) => (
                        <div
                          key={b.resource_id}
                          className="flex items-center gap-3 p-3 rounded-lg bg-white/5 border border-purple-500/20"
                          data-testid={`active-buff-${b.resource_id}`}
                        >
                          <div className="text-2xl">{b.buff_icon || b.icon || BUFF_ICON[String(b.resource_id || b.resource || '').replace(/_tutorial$/, '')] || '💎'}</div>
                          <div className="flex-1 min-w-0">
                            <div className="font-bold text-white text-sm">{tResourceBuff(b.resource_id, 'name', lang) || b.buff_name}</div>
                            <div className="text-xs text-text-muted line-clamp-1">{tResourceBuff(b.resource_id, 'description', lang) || b.buff_description}</div>
                          </div>
                          <div className="text-right">
                            <div className="text-xs text-purple-300 font-mono font-bold" data-testid={`buff-time-${b.resource_id}`}>
                              {b.remaining_label || (b.days_remaining != null ? `${b.days_remaining}д` : '—')}
                            </div>
                            <div className="text-[10px] text-text-muted">{t('remainingShort') || 'осталось'}</div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {/* Patron block intentionally removed per UX request — patron is set/changed
                  from the business card "Choose Patron" button, no need to repeat in details. */}

              {/* Bank owner: open commission settings in a dedicated modal (Block A) */}
              {isBankBusiness(selectedBusiness) && (
                <Button
                  variant="outline"
                  size="sm"
                  data-testid="open-bank-settings-btn"
                  className="w-full border-cyber-cyan/30 text-cyber-cyan hover:bg-cyber-cyan/10"
                  onClick={() => {
                    loadBankSettings(selectedBusiness.id);
                    setShowBankSettingsModal(true);
                  }}
                >
                  <Settings2 className="w-4 h-4 mr-2" />
                  {t('bankCommissionSettingsBtn') || 'Настройки комиссий'}
                </Button>
              )}

              {/* (Vassal/buff system removed) — "Баф для вассалов" block and
                  "Посмотреть вассалов" button were removed from T3 details. */}

              {/* Tier 3: Active alliance offers shortcut */}
              {(selectedBusiness.config?.tier || selectedBusiness.tier || 1) === 3 && (
                <>
                  {/* Active contracts → navigate to Trading → Offers → Active */}
                  <Button
                    variant="outline"
                    size="sm"
                    data-testid={`active-contracts-link-${selectedBusiness.id}`}
                    className="w-full border-purple-500/30 text-purple-400 hover:bg-purple-500/10"
                    onClick={() => {
                      setShowDetailsModal(false);
                      try { localStorage.setItem('tradingTab', 'offers'); } catch {}
                      try { localStorage.setItem('offersSubTab', 'active'); } catch {}
                      navigate('/trading?tab=offers&sub=active');
                    }}
                  >
                    <Scroll className="w-4 h-4 mr-2" />
                    Активные контракты {(selectedBusiness.active_alliances_count ?? 0)}/{selectedBusiness.max_alliances ?? 25}
                  </Button>
                </>
              )}

              {/* Vassal contract info */}
              {selectedBusiness.contract_id && selectedBusiness.contract_buff_data && (
                <div className="p-3 bg-purple-500/10 rounded-lg border border-purple-500/20">
                  <div className="flex items-center gap-2 mb-2">
                    <Scroll className="w-4 h-4 text-purple-400" />
                    <span className="text-purple-400 font-medium text-sm">Активный контракт</span>
                  </div>
                  {(() => {
                    const contractInfo = contracts.as_vassal.find(c => c.id === selectedBusiness.contract_id);
                    const buff = selectedBusiness.contract_buff_data || {};
                    const buffDesc = buff.description || buff.desc || '';
                    const buffEffect = buff.effect || {};
                    // Human-friendly effect summary for what the vassal RECEIVES
                    const effectLabels = {
                      production_multiplier: (v) => `+${Math.round((Number(v) - 1) * 100)}% к производству`,
                      consumption_multiplier: (v) => `−${Math.round((1 - Number(v)) * 100)}% потребление сырья`,
                      storage_multiplier: (v) => `+${Math.round((Number(v) - 1) * 100)}% к складу`,
                      withdrawal_fee_multiplier: (v) => `−${Math.round((1 - Number(v)) * 100)}% комиссии вывода`,
                      trade_fee_multiplier: (v) => `−${Math.round((1 - Number(v)) * 100)}% торговой комиссии`,
                      trade_tax_reduction: (v) => `−${(Number(v) * 100).toFixed(1)} п.п. налога продажи`,
                      repair_cost_multiplier: (v) => `−${Math.round((1 - Number(v)) * 100)}% стоимости ремонта`,
                      wear_reduction: (v) => `−${Math.round((1 - Number(v)) * 100)}% износа`,
                      free_cycle_chance: (v) => `${(Number(v) * 100).toFixed(1)}% шанс бесплатного цикла`,
                      crit_chance_bonus: (v) => `+${(Number(v) * 100).toFixed(1)}% шанс крита`,
                      trade_slots_bonus: (v) => `+${Math.round(Number(v))} торговый слот`,
                    };
                    const effectSummary = effectLabels[buffEffect.type] ? effectLabels[buffEffect.type](buffEffect.value) : null;
                    return contractInfo ? (
                      <div className="text-xs space-y-1.5">
                        <p className="text-white font-medium">{CONTRACT_TYPES[contractInfo.type]?.icon} {CONTRACT_TYPES[contractInfo.type]?.name}</p>
                        <div className="text-text-muted">
                          <span className="text-red-300">Вы отдаёте: </span>
                          {CONTRACT_TYPES[contractInfo.type]?.vassal_note || CONTRACT_TYPES[contractInfo.type]?.description}
                        </div>
                        <div className="text-text-muted">
                          <span className="text-emerald-300">Вы получаете: </span>
                          <span className="text-yellow-300 font-medium">{buff.icon} {buff.name}</span>
                          {effectSummary && (
                            <span className="text-emerald-300"> — {effectSummary}</span>
                          )}
                        </div>
                        {buffDesc && (
                          <p className="text-text-muted text-[11px] italic">«{buffDesc}»</p>
                        )}
                        <p className="text-text-muted">Патрон: {contractInfo.patron_username}</p>
                      </div>
                    ) : (
                      <div className="text-xs space-y-1">
                        <div className="text-emerald-300">
                          Вы получаете: <span className="text-yellow-300 font-medium">{buff.icon} {buff.name}</span>
                          {effectSummary && <span> — {effectSummary}</span>}
                        </div>
                        {buffDesc && <p className="text-text-muted text-[11px] italic">«{buffDesc}»</p>}
                      </div>
                    );
                  })()}
                </div>
              )}
              
              <div className="text-xs text-text-muted">
                ID: {selectedBusiness.id}
              </div>
              
              {/* rent out (above) — the sale button is the LAST thing in this window */}
              <BusinessRentalControls business={selectedBusiness} lang={lang} onChanged={refreshBusinessesSilently} />

              {/* Кнопка продажи или снятия с продажи — скрыто в демо-режиме */}
              {getGameMode() !== 'demo' && (selectedBusiness.on_sale ? (
                <Button 
                  onClick={handleCancelSale}
                  data-testid="cancel-sale-btn"
                  disabled={isCancelingSale}
                  className="w-full bg-green-500/20 text-green-400 hover:bg-green-500/30 border border-green-500/30"
                >
                  {isCancelingSale ? (
                    <>
                      <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-green-400 mr-2"></div>
                      {t('cancellingSaleStatus')}
                    </>
                  ) : (
                    <>
                      <Tag className="w-4 h-4 mr-2" />
                      {t('cancelSaleAction')}
                    </>
                  )}
                </Button>
              ) : selectedBusiness.rental_id ? null : (
                <Button 
                  onClick={() => {
                    setShowDetailsModal(false);
                    setSellPrice('');
                    setSellTaxInfo(null);
                    setShowSellModal(true);
                    // P1.7: prefetch the minimum price (returns min_price + min_price_city)
                    // so the user sees the minimum upfront in both TON and $CITY.
                    calculateSaleTax(0);
                  }}
                  className="w-full bg-red-500/20 text-red-400 hover:bg-red-500/30 border border-red-500/30"
                >
                  <Tag className="w-4 h-4 mr-2" />
                  {t('listForSaleAction')}
                </Button>
              ))}
            </div>
          )}
          
        </DialogContent>
      </Dialog>

      {/* Bank commission settings modal (Block A) */}
      <Dialog open={showBankSettingsModal} onOpenChange={setShowBankSettingsModal}>
        <DialogContent className="bg-void border-cyber-cyan/20 max-w-md" data-testid="bank-settings-modal">
          <DialogHeader>
            <DialogTitle className="text-white flex items-center gap-2">
              <Settings2 className="w-5 h-5 text-cyber-cyan" />
              {t('bankCommissionSettingsTitle') || 'Настройки комиссий банка'}
            </DialogTitle>
            <DialogDescription className="text-text-muted">
              {t('bankCommissionSettingsDesc') || 'Задайте проценты для своего банка. Только целые числа.'}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div>
              <Label className="text-xs text-text-muted">
                {t('bankInterestLabel') || 'Процент по кредиту (макс. 40%)'}
              </Label>
              <div className="relative mt-1">
                <Input
                  type="text"
                  inputMode="numeric"
                  data-testid="bank-interest-input"
                  className="bg-white/5 border-white/10 text-white pr-8 no-spinner"
                  placeholder="0"
                  value={bankSettings.interest_rate_percent}
                  onChange={(e) => setBankSettings((s) => ({ ...s, interest_rate_percent: sanitizeIntField(e.target.value, 40) }))}
                  disabled={bankSettingsLoading || bankSettingsSaving}
                />
                <span className="absolute right-3 top-1/2 -translate-y-1/2 text-text-muted text-sm">%</span>
              </div>
            </div>

            <div>
              <Label className="text-xs text-text-muted">
                {t('bankInstantFeeLabel') || 'Комиссия за мгновенный вывод (макс. 5%)'}
              </Label>
              <div className="relative mt-1">
                <Input
                  type="text"
                  inputMode="numeric"
                  data-testid="bank-instant-fee-input"
                  className="bg-white/5 border-white/10 text-white pr-8 no-spinner"
                  placeholder="0"
                  value={bankSettings.instant_fee_percent}
                  onChange={(e) => setBankSettings((s) => ({ ...s, instant_fee_percent: sanitizeIntField(e.target.value, 5) }))}
                  disabled={bankSettingsLoading || bankSettingsSaving}
                />
                <span className="absolute right-3 top-1/2 -translate-y-1/2 text-text-muted text-sm">%</span>
              </div>
            </div>
          </div>

          <DialogFooter>
            <Button
              onClick={saveBankSettings}
              disabled={bankSettingsLoading || bankSettingsSaving}
              data-testid="bank-settings-save-btn"
              className="w-full bg-cyber-cyan/20 text-cyber-cyan hover:bg-cyber-cyan/30 border border-cyber-cyan/30"
            >
              {bankSettingsSaving ? (t('savingStatus') || 'Сохранение...') : (t('saveBankSettingsBtn') || 'Сохранить настройки')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>


      {/* Sell Modal */}
      <Dialog open={showSellModal} onOpenChange={setShowSellModal}>
        <DialogContent className="bg-void border-red-500/20">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-white">
              <Tag className="w-5 h-5 text-red-400" />
              {t('sellBusinessTitle') || 'Sell business'}
            </DialogTitle>
            <DialogDescription className="text-text-muted">
              {t('sellBusinessDesc') || 'The business will be sold together with the land. Set your price.'}
            </DialogDescription>
          </DialogHeader>
          
          {selectedBusiness && (() => {
            // Find plot for this business
            const businessPlot = myPlots.find(p => p.id === selectedBusiness.plot_id);
            const cityName = businessPlot?.island_id === 'ton_island' ? 'GRAM Island' : 
              (typeof businessPlot?.city_name === 'object' ? (businessPlot?.city_name?.ru || businessPlot?.city_name?.en || 'GRAM Island') : (businessPlot?.city_name || 'GRAM Island'));
            const plotPrice = businessPlot?.price || 0;
            const businessCost = selectedBusiness.base_cost_ton || selectedBusiness.config?.base_cost_ton || 0;
            const totalInvested = plotPrice + businessCost;
            const coordinates = selectedBusiness.x !== undefined && selectedBusiness.y !== undefined 
              ? `[${selectedBusiness.x}, ${selectedBusiness.y}]` 
              : (businessPlot ? `[${businessPlot.x}, ${businessPlot.y}]` : 'Неизвестно');
            const businessName = selectedBusiness.config?.name?.[lang] || selectedBusiness.config?.name?.en || selectedBusiness.config?.name?.ru || tBusiness(selectedBusiness.business_type, lang);
            
            return (
            <div className="space-y-4">
              <div className="flex items-center gap-4 p-4 bg-white/5 rounded-xl">
                <span className="text-4xl">{selectedBusiness.config?.icon}</span>
                <div>
                  <h3 className="text-lg font-bold text-white">
                    {businessName}
                  </h3>
                  <Badge variant="outline">{t('levelLabel')} {selectedBusiness.level}</Badge>
                </div>
              </div>
              
              {/* Detailed plot and business info like in MarketplacePage */}
              <div className="p-3 bg-white/5 rounded-lg border border-white/10 space-y-2">
                <div className="flex justify-between text-sm">
                  <span className="text-text-muted">{t('cityFieldLabel') || t('city') || 'City'}:</span>
                  <span className="text-amber-400">{cityName}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-text-muted">{t('coordinatesLabel')}:</span>
                  <span className="text-white">{coordinates}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-text-muted">{t('bizOnPlotLabel') || t('business') || 'Business'}:</span>
                  <span className="text-green-400">{businessName}</span>
                </div>
                {businessCost > 0 && (
                  <div className="flex justify-between text-sm">
                    <span className="text-text-muted">{t('bizCostLabel') || 'Business cost'}:</span>
                    <span className="text-white font-mono">{formatCity(tonToCity(businessCost))} $CITY</span>
                  </div>
                )}
                <div className="flex justify-between text-sm">
                  <span className="text-text-muted">{t('produces')}:</span>
                  <span className="text-cyan-400">
                    {getResource(selectedBusiness.config?.produces, lang)?.icon} {getResource(selectedBusiness.config?.produces, lang)?.name || selectedBusiness.config?.produces}
                  </span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-text-muted">{t('outputPerDay')}:</span>
                  <span className="text-green-400 font-mono">
                    {(() => { const base = selectedBusiness.production?.base_production || 100; const dur = selectedBusiness.durability ?? 100; const m = dur <= 0 ? 0 : dur < 50 ? 0.8 : 1.0; return Math.round(base * m); })()} {t('unitsShort')}
                  </span>
                </div>
              </div>
              
              <div className="space-y-2">
                <Label className="text-white">{t('salePriceLabel') || 'Sale price'} ($CITY)</Label>
                <Input
                  type="number"
                  step="0.01"
                  min="0.1"
                  value={sellPrice}
                  onChange={(e) => {
                    setSellPrice(e.target.value);
                    if (e.target.value) calculateSaleTax(e.target.value);
                  }}
                  placeholder={t('salePricePlaceholder') || 'e.g. 10.00'}
                  className="bg-white/5 border-white/10"
                />
                {/* P1.7: minimum price shown in BOTH $CITY and TON (1 TON = 1000 $CITY) */}
                {sellTaxInfo?.min_price != null && (() => {
                  const priceNum = parseFloat(sellPrice) || 0;
                  const belowMin = priceNum > 0 && priceNum < (sellTaxInfo.min_price_city || 0);
                  return (
                    <div
                      className={`text-xs ${belowMin ? 'text-red-400' : 'text-amber-400'}`}
                      data-testid="sell-min-price-hint"
                    >
                      {belowMin
                        ? (lang === 'ru'
                            ? `Цена ниже минимума: ${formatCity(sellTaxInfo.min_price_city)} $CITY (${sellTaxInfo.min_price.toFixed(2)} TON)`
                            : `Price below minimum: ${formatCity(sellTaxInfo.min_price_city)} $CITY (${sellTaxInfo.min_price.toFixed(2)} TON)`)
                        : `${(lang === 'ru' ? 'Минимальная цена' : 'Minimum price')}: ${formatCity(sellTaxInfo.min_price_city)} $CITY (${sellTaxInfo.min_price.toFixed(2)} TON)`}
                    </div>
                  );
                })()}
              </div>
              
              {sellTaxInfo && sellPrice && parseFloat(sellPrice) > 0 && (
                <div className="p-4 bg-white/5 rounded-xl space-y-2">
                  <div className="flex justify-between text-sm">
                    <span className="text-text-muted">Цена продажи:</span>
                    <span className="text-white font-mono">{formatCity(sellTaxInfo.price)} $CITY</span>
                  </div>
                  <div className="flex justify-between text-sm">
                    <span className="text-text-muted">Налог ({sellTaxInfo.tax_rate_percent}, Tier {sellTaxInfo.tier || 1}):</span>
                    <span className="text-red-400 font-mono">−{formatCity(sellTaxInfo.tax_amount)} $CITY</span>
                  </div>
                  <div className="h-px bg-white/10 my-1" />
                  <div className="flex justify-between font-bold">
                    <span className="text-white">Чистая прибыль:</span>
                    <span className="text-green-400 text-lg font-mono">{formatCity(sellTaxInfo.seller_receives)} $CITY</span>
                  </div>
                </div>
              )}
            </div>
            );
          })()}
          
          <DialogFooter className="flex-col sm:flex-row gap-2">
            <Button 
              onClick={handleSellBusiness}
              disabled={
                !sellPrice ||
                isSelling ||
                (sellTaxInfo?.min_price_city != null &&
                  parseFloat(sellPrice) < sellTaxInfo.min_price_city)
              }
              data-testid="sell-business-submit-btn"
              className="bg-red-500 text-white hover:bg-red-600 w-full sm:w-auto disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isSelling ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <Tag className="w-4 h-4 mr-2" />}
              {t('listForSaleAction') || 'List for sale'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Buff selection modal & Vassals modal removed — vassal/buff system has been removed. */}

      {/* Contract Proposal Modal */}
      <Dialog open={showContractProposalModal} onOpenChange={setShowContractProposalModal}>
        <DialogContent className="bg-void border-purple-500/30 max-w-lg">
          <DialogHeader>
            <DialogTitle className="text-white flex items-center gap-2">
              <Scroll className="w-5 h-5 text-purple-400" />
              Заключить контракт
            </DialogTitle>
            <DialogDescription className="text-text-muted">
              {contractTarget && `Вассал: ${contractTarget.owner_username} · ${contractTarget.business_icon} ${contractTarget.business_name}`}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            {/* Contract type selection */}
            <div>
              <Label className="text-white mb-2 block">Тип контракта</Label>
              <div className="space-y-2">
                {Object.entries(CONTRACT_TYPES).map(([id, ct]) => (
                  <button key={id} onClick={() => setProposalType(id)}
                    data-testid={`contract-type-${id}`}
                    className={`w-full text-left p-3 rounded-lg border transition-all ${
                      proposalType === id
                        ? `${ct.border} ${ct.bg}`
                        : 'border-white/10 bg-white/5 hover:border-white/20'
                    }`}>
                    <div className="flex items-center gap-2">
                      <span className="text-xl">{ct.icon}</span>
                      <div className="flex-1">
                        <div className={`text-sm font-bold ${proposalType === id ? ct.color : 'text-white'}`}>{ct.name}</div>
                        <div className="text-xs text-text-muted">{ct.description}</div>
                        {proposalType === id && (
                          <div className="flex gap-3 mt-1">
                            <span className="text-[10px] text-green-400">Вассал: {ct.vassal_note}</span>
                            <span className="text-[10px] text-purple-400">Патрон: {ct.patron_note}</span>
                          </div>
                        )}
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            </div>

            {/* V2: Duration selection */}
            <div>
              <Label className="text-white mb-2 block">Длительность контракта</Label>
              <div className="flex gap-2">
                {[7, 14, 30, 60, 90].map(d => (
                  <button key={d} onClick={() => setProposalDuration(d)}
                    className={`flex-1 py-2 text-sm rounded-lg border transition-all ${
                      proposalDuration === d
                        ? 'border-purple-500 bg-purple-500/20 text-purple-300 font-bold'
                        : 'border-white/10 bg-white/5 text-text-muted hover:border-white/20'
                    }`}>
                    {d} дн.
                  </button>
                ))}
              </div>
              <div className="flex items-center gap-2 mt-2">
                <input type="checkbox" checked={proposalAutoRenew}
                  onChange={e => setProposalAutoRenew(e.target.checked)}
                  className="rounded border-gray-600 bg-gray-800 text-purple-500" />
                <span className="text-xs text-text-muted">Автопродление после истечения</span>
              </div>
            </div>

            {/* Buff selection */}
            <div>
              <Label className="text-white mb-2 block">Баф для вассала</Label>
              <div className="space-y-1.5 max-h-44 overflow-y-auto pr-1">
                {availableBuffs.length === 0 ? (
                  <p className="text-xs text-text-muted">Загрузка бафов...</p>
                ) : availableBuffs.map(buff => (
                  <button key={buff.id} onClick={() => setProposalBuff(buff.id)}
                    data-testid={`proposal-buff-${buff.id}`}
                    className={`w-full text-left p-2.5 rounded-lg border transition-all ${
                      proposalBuff === buff.id
                        ? 'border-yellow-500 bg-yellow-500/15'
                        : 'border-white/10 bg-white/5 hover:border-yellow-500/40'
                    }`}>
                    <div className="flex items-center gap-2">
                      <span>{buff.icon}</span>
                      <div>
                        <div className="text-xs font-bold text-white">{buff.name}</div>
                        <div className="text-xs text-text-muted">{buff.description}</div>
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            </div>

            {/* V2: Contract summary */}
            {proposalBuff && (
              <div className="p-3 rounded-lg bg-white/5 border border-white/10">
                <div className="text-xs font-medium text-white mb-1">Итого по контракту:</div>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div className="text-text-muted">Тип: <span className="text-white">{CONTRACT_TYPES[proposalType]?.name}</span></div>
                  <div className="text-text-muted">Срок: <span className="text-white">{proposalDuration} дней</span></div>
                  <div className="text-text-muted col-span-2">Штраф при досрочном расторжении: <span className="text-red-400 font-mono">{(proposalDuration * 100).toLocaleString()} $CITY</span></div>
                </div>
              </div>
            )}
          </div>

          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setShowContractProposalModal(false)} className="border-white/10">
              Отмена
            </Button>
            <Button onClick={handleProposeContract} disabled={isProposing || !proposalBuff}
              className="bg-purple-600 hover:bg-purple-700" data-testid="submit-contract-proposal">
              {isProposing ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <Scroll className="w-4 h-4 mr-2" />}
              Предложить контракт
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* === T3 Resource Buff Activation Modal === */}
      {/* Safety net: never render the buff modal in demo mode — T3 resources
          in the sandbox are plain upgrade materials, not buff activators. */}
      <Dialog open={showResourceBuffModal && getGameMode() !== 'demo'} onOpenChange={setShowResourceBuffModal}>
        <DialogContent className="glass-panel border-purple-500/30 bg-void max-w-md !rounded-2xl" data-testid="resource-buff-modal">
          <DialogHeader>
            <DialogTitle className="text-white flex items-center gap-2">
              <Shield className="w-5 h-5 text-purple-400" />
              {tResourceBuff(selectedBuffResource?.resource_id, 'name', lang) || selectedBuffResource?.buff?.buff_name || tResource(selectedBuffResource?.resource_id, lang)}
            </DialogTitle>
          </DialogHeader>

          {selectedBuffResource && selectedBuffResource.buff && (() => {
            const b = selectedBuffResource.buff;
            const qty = selectedBuffResource.quantity || 0;
            const isActive = selectedBuffResource.isActive;
            const activeCount = (resourceBuffsData.active || []).length;
            const limitReached = activeCount >= 2 && !isActive;
            // v2.1.5: cannot activate without an active (non-tutorial) business
            const noRealBusiness = (businesses || []).filter((bz) => !bz.tutorial).length === 0;
            const canActivate = qty >= 1 && !isActive && !limitReached && !noRealBusiness;
            const localizedName = tResourceBuff(selectedBuffResource.resource_id, 'name', lang) || b.buff_name;
            const localizedDescription = tResourceBuff(selectedBuffResource.resource_id, 'description', lang) || b.buff_description;
            const localizedResourceName = tResource(selectedBuffResource.resource_id, lang) || b.resource_name;

            return (
              <div className="space-y-4">
                <div className="p-4 rounded-lg bg-purple-500/10 border border-purple-500/30">
                  <div className="flex items-center gap-3 mb-2">
                    <div className="text-4xl">{b.buff_icon}</div>
                    <div>
                      <div className="font-bold text-white text-lg">{localizedName}</div>
                      <div className="text-xs text-purple-300">{localizedResourceName} · {qty} {t('unitsShort')} {t('inStockLabel') || ''}</div>
                    </div>
                  </div>
                  <div className="text-sm text-white/90 mt-2">{localizedDescription}</div>
                  <div className="mt-3 flex items-center justify-between text-xs">
                    <span className="text-text-muted">{t('durationLabel') || 'Duration'}:</span>
                    <span className="font-bold text-purple-300">{b.duration_days} {t('daysShort')} ({b.duration_days * 24}{t('hoursShort') || 'h'})</span>
                  </div>
                  <div className="mt-1 flex items-center justify-between text-xs">
                    <span className="text-text-muted">{t('expenseLabel')}:</span>
                    <span className="font-bold text-amber-300">{t('oneUnitOnce')}</span>
                  </div>
                </div>

                <div className="text-xs text-text-muted space-y-1">
                  <div>• {t('max2BuffsActive').replace('{n}', '2')}</div>
                  <div>• {t('sameBuffsBlocked')}</div>
                  <div>• {t('currentlyActiveLabel')}: <b className="text-white">{activeCount}</b> / 2.</div>
                </div>

                {isActive && (
                  <div className="text-xs text-green-400 p-2 rounded bg-green-500/10 border border-green-500/30">
                    {t('alreadyActivatedMsg')}
                  </div>
                )}
                {limitReached && (
                  <div className="text-xs text-red-400 p-2 rounded bg-red-500/10 border border-red-500/30">
                    {t('limitReachedWarning')}
                  </div>
                )}
                {qty < 1 && !isActive && (
                  <div className="text-xs text-yellow-400 p-2 rounded bg-yellow-500/10 border border-yellow-500/30">
                    {t('noResourceInStockMsg')}
                  </div>
                )}
                {noRealBusiness && (
                  <div
                    className="text-xs text-amber-300 p-2 rounded bg-amber-500/10 border border-amber-500/30"
                    data-testid="buff-needs-business-warning"
                  >
                    {t('tutorial_buff_needs_business') || 'Для активации T3-баффа требуется активный бизнес. Приобретите свой первый участок, чтобы применить этот ускоритель.'}
                  </div>
                )}
                {selectedBuffResource?.isTutorialReward && (
                  <div
                    className="text-xs text-amber-300 p-2 rounded bg-amber-500/10 border border-amber-500/30"
                    data-testid="tutorial-reward-not-for-sale"
                  >
                    {t('tutorialResourceNotForSale') || 'Этот ресурс получен за обучение — его нельзя выставить на продажу, но вы можете активировать его как баф.'}
                  </div>
                )}

                <DialogFooter className="flex flex-col gap-2">
                  <Button
                    onClick={() => handleActivateResourceBuff(selectedBuffResource.resource_id)}
                    disabled={!canActivate || isActivatingBuff}
                    className="bg-purple-600 hover:bg-purple-700 disabled:opacity-40 w-full"
                    data-testid="resource-buff-activate"
                  >
                    {isActivatingBuff ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <Shield className="w-4 h-4 mr-2" />}
                    {t('activateBtn')} ({b.duration_days}{t('daysShort')})
                  </Button>
                </DialogFooter>
              </div>
            );
          })()}
        </DialogContent>
      </Dialog>
      {shortageFor && shortageFor.length > 0 && (
        <ShortageModal items={shortageFor} lang={lang} onClose={() => setShortageFor(null)}
          onBuy={(res) => { setShortageFor(null); navigate(`/trading?tab=buy&resource=${encodeURIComponent(res)}`); }} />
      )}
    </div>
  );
}
