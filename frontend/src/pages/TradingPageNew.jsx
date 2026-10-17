import { formatErrorDetail } from '@/lib/apiErrors';
import { useState, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import {
  ShoppingCart, Filter, Search, Plus, Minus, ArrowUpDown,
  Package, Coins, TrendingUp, AlertCircle, Loader2, X,
  Check, ChevronDown, Tag, RefreshCw, Handshake, Warehouse, ArrowDown, ArrowUp, ArrowRight, Building2,
  Crown, HandshakeIcon, Shield, Clock, Users, Scroll, EyeOff, MessageSquare, Sliders
} from 'lucide-react';
import PageHeader from '@/components/PageHeader';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { ScrollArea } from '@/components/ui/scroll-area';
import { toast } from 'sonner';
import Sidebar from '@/components/Sidebar';
import DemoQuickTrade from '@/components/DemoQuickTrade';
import { getGameMode } from '@/lib/gameMode';
import { useLanguage } from '@/context/LanguageContext';
import { useTranslation } from '@/lib/translations';
import { RESOURCES, getResource, getAllResources, formatPrice, formatAmount } from '@/lib/resourceConfig';
import { tonToCity, formatCity } from '@/lib/currency';
import { MAX_PRICE_VALUE, clampPriceValue } from '@/lib/priceLimits';
import { useTutorial } from '@/context/TutorialContext';
import { tContract, tBuff, tResource } from '@/lib/translationsExtra';
import TenderContractsTab from '@/components/TenderContractsTab';

// Contract types for alliance offers display
const OFFER_CONTRACT_TYPES = {
  tax_haven: {
    name: 'Налоговая Гавань',
    description: 'Вассал платит 10% с каждой продажи ресурсов на маркетплейсе',
    vassal_note: '10% с каждой продажи',
    patron_note: 'Получаете 10% от выручки вассала при продаже',
    icon: '🏝️',
    color: '#f59e0b',
    border: 'border-amber-500/30',
    bg: 'bg-amber-500/10',
    penalty: 500,
  },
  raw_material: {
    name: 'Сырьевой Придаток',
    description: 'Вассал отдаёт 15% произведённых ресурсов каждый тик',
    vassal_note: '15% произведённых ресурсов',
    patron_note: 'Получаете 15% ресурсов вассала',
    icon: '⚙️',
    color: '#3b82f6',
    border: 'border-blue-500/30',
    bg: 'bg-blue-500/10',
    penalty: 750,
  },
  tech_umbrella: {
    name: 'Технологический Зонтик',
    description: 'Фиксированная рента 100 $CITY/день',
    vassal_note: '100 $CITY/день',
    patron_note: 'Фиксированная рента 100 $CITY/день',
    icon: '🛡️',
    color: '#22c55e',
    border: 'border-green-500/30',
    bg: 'bg-green-500/10',
    penalty: 300,
  },
};

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api`;

export default function TradingPage({ user, refreshBalance, updateBalance }) {
  const navigate = useNavigate();
  const { language } = useLanguage();
  const { t } = useTranslation(language);
  const tutorial = useTutorial();
  const [listings, setListings] = useState([]);
  const [myListings, setMyListings] = useState([]);
  const [slotInfo, setSlotInfo] = useState({ used: 0, max: 0, business_count: 0, trade_attache_bonus: 0 });
  const [myResources, setMyResources] = useState({});
  const [isLoading, setIsLoading] = useState(true);
  const [activeTab, setActiveTab] = useState(() => {
    try {
      const sp = new URLSearchParams(window.location.search);
      const tab = sp.get('tab');
      if (tab && ['buy', 'my', 'operations'].includes(tab)) return tab;
    } catch {}
    return 'buy';
  });
  const [tierTaxes, setTierTaxes] = useState({ 1: 15, 2: 23, 3: 30 }); // tier → tax % from admin
  const [activeBuffMults, setActiveBuffMults] = useState({ trade_tax_reduction: 0.0, trade_fee_multiplier: 1.0 });
  const [contributingBuffs, setContributingBuffs] = useState({ trade_tax_reduction: [], trade_fee_multiplier: [] });
  
  // Operations (Cooperation) data
  const [coopContracts, setCoopContracts] = useState([]);
  const [operationsLoading, setOperationsLoading] = useState(false);
  const [showCreateContract, setShowCreateContract] = useState(false);
  const [contractResource, setContractResource] = useState('');
  const [contractAmount, setContractAmount] = useState('');
  const [contractPrice, setContractPrice] = useState('');
  const [contractDuration, setContractDuration] = useState('30');
  const [isCreatingContract, setIsCreatingContract] = useState(false);
  const [myProducedResources, setMyProducedResources] = useState([]);
  const [userHasBusinesses, setUserHasBusinesses] = useState(true);
  // Buyer-side warehouse free space (weighted units). Used to clamp Buy amount.
  const [warehouseInfo, setWarehouseInfo] = useState({ capacity: 0, used: 0 });
  
  // Alliance offers state
  const [allianceOffers, setAllianceOffers] = useState([]);
  const [showAllOffersModal, setShowAllOffersModal] = useState(false);
  const [showPublishOfferModal, setShowPublishOfferModal] = useState(false);
  const [offerBuff, setOfferBuff] = useState('');
  const [offerType, setOfferType] = useState('tax_haven');
  const [offerDuration, setOfferDuration] = useState(30);
  const [isPublishing, setIsPublishing] = useState(false);
  const [availableBuffs, setAvailableBuffs] = useState([]);
  const [hasTier3, setHasTier3] = useState(false);
  const OFFERS_PER_PAGE = 3;
  
  // Tab counts
  const [coopCount, setCoopCount] = useState(0);
  const [offersCount, setOffersCount] = useState(0);
  
  // Coop sub-tab
  const [coopSubTab, setCoopSubTab] = useState('available');

  // Offers sub-tab: 'actual' (others' offers) | 'mine' (my published) | 'active' (my active alliances)
  const [offersSubTab, setOffersSubTab] = useState(() => {
    try {
      const sp = new URLSearchParams(window.location.search);
      const sub = sp.get('sub');
      if (sub && ['actual', 'mine', 'active'].includes(sub)) return sub;
    } catch {}
    return 'actual';
  });
  const [myOffers, setMyOffers] = useState([]);
  const [myOffersStats, setMyOffersStats] = useState({ active_alliances: 0, max_published: 5, max_alliances: 25 });

  // Cancel-contract confirm modal
  const [cancelConfirmContract, setCancelConfirmContract] = useState(null);

  // Business picker modal (when accepting offer with multiple businesses)
  const [acceptOfferModal, setAcceptOfferModal] = useState(null);
  const [acceptPatronWarn, setAcceptPatronWarn] = useState(null); // { offer, vassalBusinessId }
  const [myBusinessesList, setMyBusinessesList] = useState([]);
  // v2.1.5: cannot trade (sell/buy/tender) without owning at least one real
  // (non-tutorial) business. Used to hide the relevant CTAs.
  // v2.2: during the tutorial `create_lot` step we explicitly allow the user
  // to list one resource even without owning a real business, so they can
  // complete the trading tutorial flow.
  const isTutorialCreateLotStep = !!(tutorial?.active && tutorial?.currentStepId === 'create_lot');
  const realBusinessCount = (myBusinessesList || []).filter(b => !b.tutorial).length;
  // Selling is available to everyone (no-business players sell trash-pile drops
  // from their personal warehouse — the backend caps them at 1 listing slot).
  const canTrade = true;
  
  // Contracts (alliance) state
  const [contracts, setContracts] = useState({ as_patron: [], as_vassal: [] });
  
  // Counter-offer state
  const [counterOffers, setCounterOffers] = useState({ as_patron: [], as_vassal: [] });
  const [showCounterModal, setShowCounterModal] = useState(false);
  const [counterTarget, setCounterTarget] = useState(null);
  const [counterType, setCounterType] = useState('tax_haven');
  const [counterDuration, setCounterDuration] = useState(30);
  const [counterComment, setCounterComment] = useState('');
  const [counterBusinessId, setCounterBusinessId] = useState('');  // fix #4
  const [counterBuffId, setCounterBuffId] = useState('');          // fix #5: '' = keep original
  const [isCountering, setIsCountering] = useState(false);
  
  // Filters
  const [filters, setFilters] = useState({
    // `?resource=<id>` pre-filters the Buy tab (used by the "missing input" hint
    // on the business screen and by quest deep links).
    resource: (() => {
      try {
        const r = new URLSearchParams(window.location.search).get('resource');
        return r && /^[a-z_]{2,40}$/.test(r) ? r : 'all';
      } catch { return 'all'; }
    })(),
    minPrice: '',
    maxPrice: '',
    minAmount: '',
    maxAmount: '',
    sortBy: 'price_asc'
  });
  const [showFilters, setShowFilters] = useState(false);
  
  // Sell modal
  const [showSellModal, setShowSellModal] = useState(false);
  const [sellResource, setSellResource] = useState('');
  const [sellAmount, setSellAmount] = useState('');
  const [sellPrice, setSellPrice] = useState('');
  const [isSelling, setIsSelling] = useState(false);
  // Level-0 (test business) seller: fixed system price, price field is read-only.
  const [level0Info, setLevel0Info] = useState({ is_level0_seller: false, price_city: 0 });
  useEffect(() => {
    if (!showSellModal || !sellResource) return;
    let cancelled = false;
    (async () => {
      try {
        const tk = localStorage.getItem('token');
        const res = await fetch(`${API}/market/level0-price/${sellResource}`, {
          headers: { Authorization: `Bearer ${tk}` },
        });
        if (!res.ok) return;
        const data = await res.json();
        if (cancelled) return;
        setLevel0Info(data);
        if (data.is_level0_seller) {
          const tier = getResource(sellResource)?.tier || 1;
          const display = tier === 1 ? (data.price_city * 10) : data.price_city;
          setSellPrice(String(Math.round(display)));
        }
      } catch (_) { /* noop */ }
    })();
    return () => { cancelled = true; };
  }, [showSellModal, sellResource]); // eslint-disable-line
  
  // Buy modal
  const [showBuyModal, setShowBuyModal] = useState(false);
  const [selectedListing, setSelectedListing] = useState(null);
  const [buyAmount, setBuyAmount] = useState('');
  const [isBuying, setIsBuying] = useState(false);

  // Active credits — used to surface the per-sale credit repayment notice
  // in the listing-confirmation panel. Total deduction percent is the sum
  // of all active credits' `salary_deduction_percent` (doubled if overdue).
  const [activeCredits, setActiveCredits] = useState([]);
  const totalCreditPct = useMemo(() => {
    return activeCredits.reduce((acc, c) => {
      const pct = (Number(c.salary_deduction_percent) || 0) * (c.is_doubled_rate ? 2 : 1);
      return acc + pct;
    }, 0);
  }, [activeCredits]);
  
  const token = localStorage.getItem('token');
  // Resource catalog (icon, name_ru, tier, ...) — used by TenderContractsTab.
  const [resourceCatalog, setResourceCatalog] = useState({});
  useEffect(() => {
    fetch(`${API}/economy/config`)
      .then((r) => r.json())
      .then((d) => setResourceCatalog(d.resource_types || {}))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!token) {
      navigate('/login');
      return;
    }
    fetchData();
  }, [token]);

  const fetchData = async () => {
    setIsLoading(true);
    try {
      const [listingsRes, myListingsRes, resourcesRes, taxRes, buffMultsRes, businessesRes, loansRes] = await Promise.all([
        fetch(`${API}/market/listings`),
        fetch(`${API}/market/my-listings`, { headers: { Authorization: `Bearer ${token}` } }),
        fetch(`${API}/my/resources`, { headers: { Authorization: `Bearer ${token}` } }),
        fetch(`${API}/public/tax-settings`).catch(() => null),
        fetch(`${API}/my/active-buff-multipliers`, { headers: { Authorization: `Bearer ${token}` } }).catch(() => null),
        fetch(`${API}/my/businesses`, { headers: { Authorization: `Bearer ${token}` } }).catch(() => null),
        fetch(`${API}/credit/my-loans`, { headers: { Authorization: `Bearer ${token}` } }).catch(() => null),
      ]);
      
      if (buffMultsRes && buffMultsRes.ok) {
        const bm = await buffMultsRes.json();
        // Combine multipliers + reductions into a single object so the
        // sell-modal preview can read both with a flat key lookup.
        setActiveBuffMults({ ...(bm.multipliers || {}), ...(bm.reductions || {}) });
        setContributingBuffs(bm.contributing || {});
      }
      
      if (taxRes && taxRes.ok) {
        const taxData = await taxRes.json();
        setTierTaxes({
          1: taxData.small_business_tax ?? 15,
          2: taxData.medium_business_tax ?? 23,
          3: taxData.large_business_tax ?? 30
        });
      }
      
      if (listingsRes.ok) {
        const data = await listingsRes.json();
        setListings(data.listings || []);
      }
      
      if (myListingsRes.ok) {
        const data = await myListingsRes.json();
        setMyListings(data.listings || []);
        if (data.slot_info) setSlotInfo(data.slot_info);
      }
      
      if (resourcesRes.ok) {
        const data = await resourcesRes.json();
        setMyResources(data.resources || {});
      }

      if (businessesRes && businessesRes.ok) {
        const bdata = await businessesRes.json();
        const summary = bdata.summary || {};
        setWarehouseInfo({
          capacity: summary.total_warehouse_capacity || 0,
          used: summary.total_warehouse_used || 0,
        });
        // Issue #3: populate the business list on the initial load (not only
        // when the «Offers» tab runs fetchAllianceOffers). Otherwise the «My»
        // tab shows "buy your first business" until a full page refresh even
        // though the user owns a business.
        const businesses = bdata.businesses || [];
        // Buying and selling are available to everyone now (no-business players
        // trade from their personal warehouse / trash-pile drops). Keep this
        // flag always-true so the old "buy your first business" gates never show.
        setUserHasBusinesses(true);
        setMyBusinessesList(businesses.map(b => ({
          id: b.id,
          name: b.config?.name?.[language] || b.config?.name?.ru || b.config?.name?.en || b.business_type || '?',
          business_name: b.config?.name?.[language] || b.config?.name?.ru || b.config?.name?.en || b.business_type || '?',
          icon: b.config?.icon || '🏢',
          level: b.level || 1,
          tier: b.config?.tier || 1,
          business_type: b.business_type,
          produces: b.config?.produces,
          contract_id: b.contract_id,
          tutorial: b.tutorial,
        })));
      }

      if (loansRes && loansRes.ok) {
        const ldata = await loansRes.json();
        const active = (ldata.loans || []).filter(l =>
          ['active', 'overdue'].includes(l.status) && (l.remaining || 0) > 0
        );
        setActiveCredits(active);
      }
    } catch (error) {
      console.error('Failed to load data:', error);
    } finally {
      setIsLoading(false);
    }
  };

  // Filter listings
  // Tutorial: fetch the hidden bot lot on tutorial buy_lot step and merge it
  const [seedLot, setSeedLot] = useState(null);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (tutorial?.active && ['buy_lot', 'go_trading_buy'].includes(tutorial?.currentStepId)) {
        const lot = tutorial?.getSeedLot ? await tutorial.getSeedLot() : null;
        if (!cancelled) setSeedLot(lot);
      } else {
        if (!cancelled) setSeedLot(null);
      }
    })();
    return () => { cancelled = true; };
  }, [tutorial?.active, tutorial?.currentStepId]);

  const filteredListings = useMemo(() => {
    let result = [...listings];
    // Prepend tutorial bot lot if visible for current step
    if (seedLot) {
      result = [seedLot, ...result.filter(l => l.id !== seedLot.id)];
    }
    
    // Exclude own listings - user should not see their own items
    if (user?.id) {
      result = result.filter(l => l.seller_id !== user.id);
    }
    
    // Filter by resource
    if (filters.resource !== 'all') {
      result = result.filter(l => l.resource_type === filters.resource);
    }
    
    // Filter by price
    if (filters.minPrice) {
      result = result.filter(l => l.price_per_unit >= parseFloat(filters.minPrice));
    }
    if (filters.maxPrice) {
      result = result.filter(l => l.price_per_unit <= parseFloat(filters.maxPrice));
    }
    
    // Filter by amount
    if (filters.minAmount) {
      result = result.filter(l => l.amount >= parseInt(filters.minAmount));
    }
    if (filters.maxAmount) {
      result = result.filter(l => l.amount <= parseInt(filters.maxAmount));
    }
    
    // Sort
    switch (filters.sortBy) {
      case 'price_asc':
        result.sort((a, b) => a.price_per_unit - b.price_per_unit);
        break;
      case 'price_desc':
        result.sort((a, b) => b.price_per_unit - a.price_per_unit);
        break;
      case 'amount_desc':
        result.sort((a, b) => b.amount - a.amount);
        break;
      case 'newest':
        result.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
        break;
    }
    
    return result;
  }, [listings, filters, seedLot, user?.id]);

  // Get available resources for selling. Tutorial-reward variants
  // (`<res>_tutorial`) are stored under a separate key in `resources` and are
  // NOT sellable, so we filter them out here. Regular T3 units (produced /
  // bought / dropped) DO show up so no-business players can trade them.
  const availableResources = useMemo(() => {
    const list = Object.entries(myResources)
      .filter(([id, amount]) => amount > 0 && !id.endsWith('_tutorial'))
      .map(([id, amount]) => ({ id, amount, ...getResource(id) }));
    // During the tutorial the user only practices selling Neuro Core, so we
    // hide every other resource from the selector until the tutorial is done.
    if (tutorial?.active) {
      return list.filter(r => r.id === 'neuro_core');
    }
    return list;
  }, [myResources, tutorial?.active]);

  // Helper: display price based on tier (Tier 1 = per 10, others = per 1)
  const tier1Resources = ['energy', 'scrap', 'quartz', 'cu', 'traffic', 'cooling', 'biomass'];
  const displayPrice = (listing) => {
    const isTier1 = tier1Resources.includes(listing.resource_type);
    const priceCity = tonToCity(listing.price_per_unit);
    if (isTier1) {
      return { price: formatCity(priceCity * 10), label: '/10' };
    }
    return { price: formatCity(priceCity), label: '/1' };
  };

  // Handle sell
  const handleSell = async () => {
    if (!sellResource || !sellAmount || !sellPrice) {
      toast.error(t('fillAllFieldsCredit'));
      return;
    }
    
    const amount = parseInt(sellAmount);
    const priceCity = parseFloat(sellPrice);
    const tier = getResource(sellResource)?.tier || 1;

    // Tutorial step `create_lot`: cap amount at (warehouse − 1) so the user
    // always keeps at least 1 unit of Neuro Core for the next «T3 = buff» step.
    // The amount input is already clamped on change, so we silently re-clamp
    // here without surfacing a toast.
    let amountFinal = amount;
    if (tutorial?.active && tutorial?.currentStepId === 'create_lot') {
      const have = Math.floor(myResources[sellResource] || 0);
      const maxAllowed = Math.max(0, have - 1);
      if (amountFinal > maxAllowed) {
        amountFinal = maxAllowed;
      }
    }
    
    // For Tier1: price is per 10 units in $CITY, convert to per-unit TON
    // For Tier2/3: price is per 1 unit in $CITY, convert to per-unit TON  
    const pricePerUnitTon = tier === 1 
      ? (priceCity / 10) / 1000   // $CITY per 10 -> TON per 1
      : priceCity / 1000;          // $CITY per 1 -> TON per 1
    
    if (amountFinal <= 0 || priceCity <= 0) {
      toast.error(t('loadingDataError'));
      return;
    }
    
    const available = myResources[sellResource] || 0;
    if (amountFinal > available) {
      toast.error(`Недостаточно ресурсов. Доступно: ${Math.floor(available)}`);
      return;
    }
    
    setIsSelling(true);
    try {
      // Tutorial: intercept create_lot step and use tutorial create-lot endpoint instead
      if (tutorial?.active && tutorial?.currentStepId === 'create_lot') {
        const res = await fetch(`${API}/tutorial/create-lot`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`
          },
          body: JSON.stringify({
            resource_type: sellResource,
            amount: amountFinal,
            price_per_unit: pricePerUnitTon
          })
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.detail || t('loadingDataError'));
        }
        toast.success('🎓 ' + t('resourcesListedMsg'));
        setShowSellModal(false);
        setSellResource('');
        setSellAmount('');
        setSellPrice('');
        if (tutorial?.refreshStatus) await tutorial.refreshStatus();
        refreshBalance?.();
        fetchData();
        setIsSelling(false);
        return;
      }

      const res = await fetch(`${API}/market/list-resource`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({
          resource_type: sellResource,
          amount: amountFinal,
          price_per_unit: pricePerUnitTon
        })
      });
      
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || t('loadingDataError'));
      }
      
      toast.success(t('resourcesListedMsg'));
      setShowSellModal(false);
      setSellResource('');
      setSellAmount('');
      setSellPrice('');
      refreshBalance?.();
      fetchData();
    } catch (error) {
      toast.error(error.message);
    } finally {
      setIsSelling(false);
    }
  };

  // Handle buy
  const handleBuy = async () => {
    if (!selectedListing || !buyAmount) {
      toast.error(t('loadingDataError'));
      return;
    }
    
    const amount = formatAmount(parseFloat(buyAmount));
    
    if (amount <= 0) {
      toast.error(t('loadingDataError'));
      return;
    }
    
    if (amount > selectedListing.amount) {
      toast.error(`Максимум: ${selectedListing.amount}`);
      return;
    }
    
    setIsBuying(true);
    try {
      // Tutorial buy_lot: intercept and call /api/tutorial/buy-lot
      if (tutorial?.active && tutorial?.currentStepId === 'buy_lot' && selectedListing?.tutorial) {
        const res = await tutorial.buyTutorialLot({ amount });
        if (!res.ok) {
          throw new Error(res.error || 'Tutorial buy failed');
        }
        toast.success('🎓 +' + amount + ' Neuro Core');
        setShowBuyModal(false);
        setSelectedListing(null);
        setBuyAmount('');
        setSeedLot(null);
        if (tutorial?.refreshStatus) await tutorial.refreshStatus();
        fetchData();
        setIsBuying(false);
        return;
      }

      const res = await fetch(`${API}/market/buy`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({
          listing_id: selectedListing.id,
          amount
        })
      });
      
      if (!res.ok) {
        let errDetail = t('loadingDataError');
        try {
          const err = await res.json();
          errDetail = formatErrorDetail(err.detail) || errDetail;
        } catch {}
        // 404 → listing fully sold/cancelled. Refresh listings and close modal.
        if (res.status === 404) {
          toast.error(t('listingSoldOut') || 'Этот лот уже выкуплен. Список обновлён.');
          setShowBuyModal(false);
          setBuyAmount('');
          setSelectedListing(null);
          fetchData();
          return;
        }
        // 400 with "Available: N" — someone bought part of it. Refresh so UI shows remainder.
        if (res.status === 400 && /Available:|Insufficient/.test(errDetail)) {
          fetchData();
        }
        throw new Error(errDetail);
      }
      
      const data = await res.json();
      toast.success(
        <div className="flex flex-col gap-1">
          <span className="font-bold">{t('purchaseSuccess') || 'Покупка успешна!'}</span>
          <span className="text-sm">{t('received') || 'Получено'}: {amount} {getResource(selectedListing.resource_type).name}</span>
          <span className="text-sm text-amber-400">{t('paid') || 'Оплачено'}: {formatCity(tonToCity(data.total_paid))} $CITY</span>
        </div>
      );
      setShowBuyModal(false);
      setBuyAmount('');
      setSelectedListing(null);
      // Update balance immediately
      if (data.new_balance !== undefined) {
        updateBalance?.(data.new_balance, data.new_bonus_balance);
      } else {
        refreshBalance?.();
      }
      fetchData();
    } catch (error) {
      toast.error(formatErrorDetail(error.message));
    } finally {
      setIsBuying(false);
    }
  };

  // Cancel listing
  const handleCancelListing = async (listingId) => {
    try {
      const res = await fetch(`${API}/market/cancel/${listingId}`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` }
      });
      
      if (!res.ok) throw new Error('Ошибка отмены');
      
      toast.success(t('listingCanceledMsg'));
      refreshBalance?.();
      fetchData();
    } catch (error) {
      toast.error(error.message);
    }
  };

  // Fetch cooperation contracts
  const fetchCoopContracts = async () => {
    setOperationsLoading(true);
    try {
      const [contractsRes, bizRes, configRes] = await Promise.all([
        fetch(`${API}/cooperation/list`, { headers: { Authorization: `Bearer ${token}` } }),
        fetch(`${API}/my/businesses`, { headers: { Authorization: `Bearer ${token}` } }),
        fetch(`${API}/config`, { headers: { Authorization: `Bearer ${token}` } }),
      ]);
      if (contractsRes.ok) {
        const data = await contractsRes.json();
        setCoopContracts(data.contracts || []);
        setCoopCount(data.contracts?.length || 0);
      }
      // Build list of resources produced by user's businesses
      if (bizRes.ok && configRes.ok) {
        const bizData = await bizRes.json();
        const cfgData = await configRes.json();
        const businessesList = bizData.businesses || [];
        // Keep buy/sell available for everyone (see canTrade). Do not reset the
        // flag to false for no-business players — it would resurrect the old
        // "no business" notices when switching tabs.
        setUserHasBusinesses(true);
        const businessConfig = cfgData.businesses || {};
        const produced = new Set();
        businessesList.forEach(biz => {
          const cfg = businessConfig[biz.business_type];
          if (cfg?.produces) produced.add(cfg.produces);
        });
        setMyProducedResources([...produced].map(id => getResource(id)));
      }
    } catch (error) {
      console.error('Failed to load contracts:', error);
    } finally {
      setOperationsLoading(false);
    }
  };

  const handleCreateContract = async () => {
    if (!contractResource || !contractAmount || !contractPrice) {
      toast.error('Заполните все поля');
      return;
    }
    setIsCreatingContract(true);
    try {
      const res = await fetch(`${API}/cooperation/create`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          resource_type: contractResource,
          amount_per_day: parseFloat(contractAmount),
          price_per_unit: parseFloat(contractPrice),
          duration_days: parseInt(contractDuration) || 30,
        })
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Error');
      }
      toast.success('Контракт создан!');
      setShowCreateContract(false);
      setContractResource('');
      setContractAmount('');
      setContractPrice('');
      fetchCoopContracts();
    } catch (e) { toast.error(e.message); }
    finally { setIsCreatingContract(false); }
  };

  const handleAcceptContract = async (contractId) => {
    try {
      const res = await fetch(`${API}/cooperation/accept/${contractId}`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` }
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Error');
      }
      toast.success('Контракт принят!');
      fetchCoopContracts();
    } catch (e) { toast.error(e.message); }
  };

  const handleCancelContract = async (contractId) => {
    try {
      const res = await fetch(`${API}/cooperation/cancel/${contractId}`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` }
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Error');
      }
      toast.success('Контракт отменён');
      fetchCoopContracts();
    } catch (e) { toast.error(e.message); }
  };

  // Fetch counts for tab badges on initial load
  useEffect(() => {
    const fetchCounts = async () => {
      try {
        const [coopRes, offersRes] = await Promise.all([
          fetch(`${API}/cooperation/list`, { headers: { Authorization: `Bearer ${token}` } }).catch(() => null),
          fetch(`${API}/alliances/offers`, { headers: { Authorization: `Bearer ${token}` } }).catch(() => null),
        ]);
        if (coopRes?.ok) { const d = await coopRes.json(); setCoopCount(d.contracts?.length || 0); setCoopContracts(d.contracts || []); }
        if (offersRes?.ok) { const d = await offersRes.json(); setOffersCount(d.total || 0); }
      } catch {}
    };
    fetchCounts();
  }, []);

  useEffect(() => {
    if (activeTab === 'operations' && coopContracts.length === 0) {
      fetchCoopContracts();
    }
    if (activeTab === 'offers') {
      fetchAllianceOffers();
      fetchContracts();
      fetchCounterOffers();
    }
  }, [activeTab]);

  // Auto-refresh trading offers + contracts + counter-offers every 5 seconds
  // while the user is on the Offers tab so newly-published offers appear
  // without manually navigating away and back. Silent — no spinner flicker.
  useEffect(() => {
    if (activeTab !== 'offers') return undefined;
    const id = setInterval(() => {
      fetchAllianceOffers();
      fetchContracts();
      fetchCounterOffers();
    }, 5000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab]);

  // Alliance offers functions
  const fetchAllianceOffers = async () => {
    try {
      const [offersRes, bizRes, myOffersRes] = await Promise.all([
        fetch(`${API}/alliances/offers`, { headers: { Authorization: `Bearer ${token}` } }),
        fetch(`${API}/my/businesses`, { headers: { Authorization: `Bearer ${token}` } }).catch(() => null),
        fetch(`${API}/alliances/my-offers`, { headers: { Authorization: `Bearer ${token}` } }).catch(() => null),
      ]);
      if (offersRes.ok) {
        const data = await offersRes.json();
        setAllianceOffers(data.offers || []);
        setOffersCount(data.total || 0);
      }
      if (bizRes && bizRes.ok) {
        const bizData = await bizRes.json();
        const businesses = bizData.businesses || [];
        setHasTier3(businesses.some(b => (b.config?.tier || 1) === 3));
        setMyBusinessesList(businesses.map(b => ({
          id: b.id,
          name: b.config?.name?.[language] || b.config?.name?.ru || b.config?.name?.en || b.business_type || '?',
          business_name: b.config?.name?.[language] || b.config?.name?.ru || b.config?.name?.en || b.business_type || '?',
          icon: b.config?.icon || '🏢',
          level: b.level || 1,
          tier: b.config?.tier || 1,
          business_type: b.business_type,
          produces: b.config?.produces,
          contract_id: b.contract_id,
        })));
      }
      if (myOffersRes && myOffersRes.ok) {
        const my = await myOffersRes.json();
        setMyOffers(my.offers || []);
        setMyOffersStats({
          active_alliances: my.active_alliances || 0,
          max_published: my.max_published || 5,
          max_alliances: my.max_alliances || 25,
        });
        if (typeof my.has_tier3 === 'boolean') setHasTier3(my.has_tier3);
      }
    } catch (e) {
      console.error('Failed to fetch alliance offers:', e);
    }
  };

  const handleCancelMyOffer = async (offerId) => {
    if (!window.confirm('Снять оффер с публикации? Активные контракты, заключённые по нему, останутся в силе.')) return;
    try {
      const res = await fetch(`${API}/alliances/cancel-offer/${offerId}`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Ошибка');
      toast.success(data.message || 'Оффер снят');
      fetchAllianceOffers();
    } catch (e) { toast.error(e.message); }
  };

  const handlePublishOffer = async () => {
    if (!offerBuff || !offerType) {
      toast.error('Выберите баф и тип контракта');
      return;
    }
    setIsPublishing(true);
    try {
      const res = await fetch(`${API}/alliances/publish-offer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ buff_id: offerBuff, contract_type: offerType, duration_days: offerDuration }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Ошибка');
      toast.success('Оффер опубликован!');
      setShowPublishOfferModal(false);
      setOfferBuff('');
      setOfferType('tax_haven');
      setOfferDuration(30);
      fetchAllianceOffers();
    } catch (e) { toast.error(e.message); }
    finally { setIsPublishing(false); }
  };

  const handleAcceptOffer = async (offer, vassalBusinessId = null, _confirmedPatron = false) => {
    // Determine offer object from arg (could be id string for backwards compatibility)
    const offerObj = typeof offer === 'string' ? allianceOffers.find(o => o.id === offer) : offer;
    if (!offerObj) {
      toast.error('Оффер не найден');
      return;
    }

    // Determine eligible businesses (exclude already-accepted ones)
    const alreadyAccepted = new Set(offerObj.already_accepted_business_ids || []);
    const eligible = (myBusinessesList || []).filter(b => !alreadyAccepted.has(b.id));

    let chosenId = vassalBusinessId;
    if (!chosenId) {
      if (eligible.length === 0) {
        toast.error('Нет доступного бизнеса для этого оффера');
        return;
      } else if (eligible.length === 1) {
        chosenId = eligible[0].id;
      } else {
        // Open business picker modal
        setAcceptOfferModal({ offer: offerObj, eligible });
        return;
      }
    }

    // Patron-on-accept warning modal removed per UX request — the entire
    // patronage assignment system is gone, so accept directly.

    try {
      const url = `${API}/alliances/accept/${offerObj.id}${chosenId ? `?vassal_business_id=${encodeURIComponent(chosenId)}` : ''}`;
      const res = await fetch(url, { method: 'POST', headers: { Authorization: `Bearer ${token}` } });
      const data = await res.json();
      if (!res.ok) {
        // Если оффера больше нет (404 или "Оффер не найден или уже принят") —
        // автоматически обновляем список и показываем актуальные офферы.
        const detail = String(data?.detail || '');
        const offerGone = res.status === 404 || detail.toLowerCase().includes('не найден') || detail.toLowerCase().includes('уже принят');
        if (offerGone) {
          toast.error(t('offerGoneRefresh') || 'Оффер больше не доступен — список обновлён');
          setAcceptOfferModal(null);
          setAcceptPatronWarn(null);
          fetchAllianceOffers();
          fetchContracts();
          return;
        }
        throw new Error(detail || 'Ошибка');
      }
      toast.success(data.message || 'Альянс заключён!');
      setAcceptOfferModal(null);
      setAcceptPatronWarn(null);
      fetchAllianceOffers();
      fetchContracts();
      refreshBalance?.();
    } catch (e) { toast.error(e.message); }
  };

  const handleCancelOffer = async (offerId) => {
    try {
      const res = await fetch(`${API}/alliances/cancel-offer/${offerId}`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Ошибка');
      toast.success('Оффер отменён');
      fetchAllianceOffers();
    } catch (e) { toast.error(e.message); }
  };

  // Fetch user contracts (alliances)
  const fetchContracts = async () => {
    try {
      const res = await fetch(`${API}/contracts/my`, { headers: { Authorization: `Bearer ${token}` } });
      if (res.ok) {
        const data = await res.json();
        setContracts(data);
      }
    } catch {}
  };

  // Contract action (accept/reject/cancel)
  const handleContractAction = async (contractId, action) => {
    try {
      const res = await fetch(`${API}/contracts/${contractId}/${action}`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Ошибка');
      toast.success(data.message || 'Готово');
      fetchContracts();
      fetchAllianceOffers();
      fetchCounterOffers();
      // Refresh balance everywhere (sidebar, header) — alliance break charges $CITY
      refreshBalance?.();
    } catch (e) { toast.error(e.message); }
  };

  // Hide offer / contract — OPTIMISTIC UI (instant removal)
  const handleHideOffer = async (offerId) => {
    // Instantly remove from UI
    setAllianceOffers(prev => prev.filter(o => o.id !== offerId));
    setOffersCount(prev => Math.max(0, prev - 1));
    try {
      const res = await fetch(`${API}/alliances/hide/${offerId}`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } });
      if (!res.ok) { fetchAllianceOffers(); throw new Error('Ошибка'); }
    } catch (e) { toast.error(e.message); }
  };

  const handleHideContract = async (contractId) => {
    // Instantly remove from UI
    setCoopContracts(prev => prev.filter(c => c.id !== contractId));
    setCoopCount(prev => Math.max(0, prev - 1));
    // Also remove from alliance contracts
    setContracts(prev => ({
      as_patron: prev.as_patron.filter(c => c.id !== contractId),
      as_vassal: prev.as_vassal.filter(c => c.id !== contractId),
    }));
    try {
      const res = await fetch(`${API}/contracts/hide/${contractId}`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } });
      if (!res.ok) { fetchCoopContracts(); fetchContracts(); throw new Error('Ошибка'); }
    } catch (e) { toast.error(e.message); }
  };

  // Counter-offers
  const fetchCounterOffers = async () => {
    try {
      const res = await fetch(`${API}/alliances/counter-offers`, { headers: { Authorization: `Bearer ${token}` } });
      if (res.ok) { const data = await res.json(); setCounterOffers(data); }
    } catch {}
  };

  const handleSubmitCounterOffer = async () => {
    if (!counterTarget) return;
    // Fix #4: require business pick if user has multiple
    const eligibleBizs = (myBusinessesList || []).filter(b => true);
    if (eligibleBizs.length > 1 && !counterBusinessId) {
      toast.error(t('pickVassalBusiness') || 'Выберите бизнес для встречного предложения');
      return;
    }
    const chosenBiz = counterBusinessId || (eligibleBizs[0] && eligibleBizs[0].id) || null;
    setIsCountering(true);
    try {
      const res = await fetch(`${API}/alliances/counter-offer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          offer_id: counterTarget.id,
          contract_type: counterType,
          duration_days: counterDuration,
          comment: counterComment,
          vassal_business_id: chosenBiz || undefined,
          buff_id: counterBuffId || undefined,  // fix #5: alternate buff (optional)
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Ошибка');
      toast.success(t('counterOfferSent') || 'Встречное предложение отправлено!');
      setShowCounterModal(false);
      setCounterComment('');
      setCounterBusinessId('');
      setCounterBuffId('');
      fetchAllianceOffers();
    } catch (e) { toast.error(e.message); }
    finally { setIsCountering(false); }
  };

  const handleCounterOfferAction = async (counterId, action) => {
    try {
      const res = await fetch(`${API}/alliances/counter-offer/${counterId}/${action}`, {
        method: 'POST', headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Ошибка');
      toast.success(data.message || 'Готово');
      fetchCounterOffers();
      fetchContracts();
    } catch (e) { toast.error(e.message); }
  };

  // Apply filters
  const applyFilters = () => {
    setShowFilters(false);
    toast.success(t('confirm'));
  };

  // Reset filters
  const resetFilters = () => {
    setFilters({
      resource: 'all',
      minPrice: '',
      maxPrice: '',
      minAmount: '',
      maxAmount: '',
      sortBy: 'price_asc'
    });
    toast.success(t('confirm'));
  };

  if (isLoading) {
    return (
      <div className="flex min-h-screen bg-void">
        <Sidebar user={user} />
        <div className="flex-1 flex items-center justify-center">
          <Loader2 className="w-8 h-8 animate-spin text-cyber-cyan" />
        </div>
      </div>
    );
  }

  // Demo (Sandbox): trading is limited to Quick Sell/Buy with the system bot.
  // The P2P tabs (Contracts / Offers / market listings) are hidden entirely.
  if (getGameMode() === 'demo') {
    return (
      <div className="flex min-h-screen bg-void">
        <Sidebar user={user} />
        <main className="flex-1 p-4 lg:px-6 lg:pt-2 lg:pb-6 pt-0 lg:ml-16">
          <div className="max-w-3xl mx-auto">
            <div className="flex items-center gap-3 mb-4 tg-header-pad">
              <ShoppingCart className="w-5 h-5 lg:w-6 lg:h-6 text-cyber-cyan" />
              <div>
                <h1 className="text-xl lg:text-2xl font-bold text-white uppercase tracking-tight">{t('tradingPageTitle')}</h1>
                <p className="text-text-muted text-sm">{t('buyAndSellResourcesDesc')}</p>
              </div>
            </div>
            <DemoQuickTrade />
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen bg-void">
      <Sidebar user={user} />

      <main className="flex-1 p-4 lg:px-6 lg:pt-2 lg:pb-6 pt-0 lg:ml-16">
        <div className="max-w-6xl mx-auto">
          {/* Header with refresh button on the right — aligned with burger menu in Mini Apps */}
          <div className="flex items-center justify-between mb-4 tg-header-pad">
            <div className="flex items-center gap-3">
              <ShoppingCart className="w-5 h-5 lg:w-6 lg:h-6 text-cyber-cyan" />
              <div>
                <h1 className="text-xl lg:text-2xl font-bold text-white uppercase tracking-tight">{t('tradingPageTitle')}</h1>
                <p className="text-text-muted text-sm">{t('buyAndSellResourcesDesc')}</p>
              </div>
            </div>
            <Button onClick={() => { fetchData(); fetchContracts(); fetchAllianceOffers(); fetchCounterOffers(); fetchCoopContracts(); }} variant="outline" size="sm" className="border-white/10">
              <RefreshCw className="w-4 h-4" />
            </Button>
          </div>

          {/* Tabs Row - responsive grid (вкладка «Офферы» убрана по запросу;
              «Контракты» на мобильной — на всю ширину) */}
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 mb-4 lg:mb-6">
              <Button
                onClick={() => {
                  setActiveTab('buy');
                  if (tutorial?.active && tutorial?.currentStepId === 'go_trading_buy') {
                    tutorial.advance(tutorial.currentStepId);
                  }
                }}
                variant={activeTab === 'buy' ? 'default' : 'outline'}
                className={activeTab === 'buy' ? 'bg-cyber-cyan text-black' : 'border-white/10'}
                data-testid="tutorial-trading-tab-buy"
              >
                <ShoppingCart className="w-4 h-4 mr-1.5" />
                {t('buyTab')} ({filteredListings.length})
              </Button>
              <Button
                onClick={() => {
                  setActiveTab('my');
                  if (tutorial?.active && tutorial?.currentStepId === 'go_trading_my') {
                    tutorial.advance(tutorial.currentStepId);
                  }
                }}
                variant={activeTab === 'my' ? 'default' : 'outline'}
                className={activeTab === 'my' ? 'bg-amber-500 text-black' : 'border-white/10'}
                data-testid="tutorial-trading-tab-my"
              >
                <Tag className="w-4 h-4 mr-1.5" />
                {t('myTab')} ({myListings.length})
              </Button>
            <Button
              data-testid="operations-tab"
              onClick={() => setActiveTab('operations')}
              variant={activeTab === 'operations' ? 'default' : 'outline'}
              className={`col-span-2 sm:col-span-1 ${activeTab === 'operations' ? 'bg-purple-500 text-white' : 'border-purple-500/30 text-purple-400 hover:bg-purple-500/10'}`}
            >
              <Handshake className="w-4 h-4 mr-1.5" />
              {t('contractsTab')}
              {coopCount > 0 && <Badge className="ml-1.5 bg-white/20 text-xs px-1.5 py-0">{coopCount}</Badge>}
            </Button>
          </div>
          
          {/* Filters section - shown on Buy tab */}
          {activeTab === 'buy' && (
            <div className="flex items-center justify-end mb-4">
              <Button
                onClick={() => setShowFilters(true)}
                variant="outline"
                className={`h-8 text-xs ${(filters.resource !== 'all' || filters.minPrice || filters.maxPrice || filters.minAmount || filters.maxAmount) ? 'border-cyan-400 text-cyan-300' : 'border-zinc-700 text-zinc-300'}`}
                data-testid="buy-filters-open"
              >
                <Sliders className="w-3.5 h-3.5 mr-1" /> {t('filtersBtn')}
                {(filters.resource !== 'all' || filters.minPrice || filters.maxPrice || filters.minAmount || filters.maxAmount) && (
                  <span className="ml-1 text-[10px] px-1 rounded-full bg-cyan-400 text-black font-bold">●</span>
                )}
              </Button>
            </div>
          )}

          {/* Active filters */}
          {(filters.resource !== 'all' || filters.minPrice || filters.maxPrice) && (
            <div className="flex flex-wrap gap-2 mb-4">
              {filters.resource !== 'all' && (
                <Badge variant="outline" className="bg-white/5">
                  {getResource(filters.resource, language).icon} {getResource(filters.resource, language).name}
                  <X 
                    className="w-3 h-3 ml-1 cursor-pointer" 
                    onClick={() => setFilters(f => ({ ...f, resource: 'all' }))}
                  />
                </Badge>
              )}
              {filters.minPrice && (
                <Badge variant="outline" className="bg-white/5">
                  {t('minPriceLabel')}: {filters.minPrice} $CITY
                  <X 
                    className="w-3 h-3 ml-1 cursor-pointer" 
                    onClick={() => setFilters(f => ({ ...f, minPrice: '' }))}
                  />
                </Badge>
              )}
              {filters.maxPrice && (
                <Badge variant="outline" className="bg-white/5">
                  {t('maxPriceLabel')}: {filters.maxPrice} $CITY
                  <X 
                    className="w-3 h-3 ml-1 cursor-pointer" 
                    onClick={() => setFilters(f => ({ ...f, maxPrice: '' }))}
                  />
                </Badge>
              )}
              <Button size="sm" variant="ghost" onClick={resetFilters}>
                <RefreshCw className="w-3 h-3 mr-1" /> {t('resetFilters')}
              </Button>
            </div>
          )}

          {/* Content */}
          {activeTab === 'buy' && (
            <>
              {!userHasBusinesses && (
                <div className="mb-4 p-3 bg-red-500/10 border border-red-500/30 rounded-lg flex items-center gap-3" data-testid="trading-buy-no-business-notice">
                  <Building2 className="w-5 h-5 text-red-400 shrink-0" />
                  <p className="text-red-300 text-sm">{t('cantBuyNoBusiness') || 'У вас нет бизнесов и складов — покупка ресурсов недоступна. Сначала постройте бизнес.'}</p>
                </div>
              )}

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {filteredListings.length === 0 ? (
                <div className="col-span-full text-center py-12 text-text-muted">
                  <Package className="w-12 h-12 mx-auto mb-3 opacity-50" />
                  <p>{t('noListingsFound')}</p>
                </div>
              ) : (
                filteredListings.map(listing => {
                  const resource = getResource(listing.resource_type);
                  const isTutorialLot = !!seedLot && listing.id === seedLot.id;
                  // Touch on a tutorial lot is always allowed (even without
                  // owning a real business), otherwise the buy_lot step is
                  // impossible to complete for a fresh user.
                  const canClickThisLot = userHasBusinesses || isTutorialLot;
                  return (
                    <Card 
                      key={listing.id} 
                      data-testid={isTutorialLot ? 'tutorial-buy-bot-lot-btn' : undefined}
                      className={`bg-void border ${resource.borderColor} hover:border-opacity-100 transition-all ${canClickThisLot ? 'cursor-pointer' : 'opacity-60 cursor-not-allowed'}`}
                      onClick={() => {
                        if (!canClickThisLot) return;
                        setSelectedListing(listing);
                        const isTier1 = resource.tier === 1;
                        const defaultAmount = isTier1 ? 10 : 1;
                        setBuyAmount(String(Math.min(listing.amount, defaultAmount)));
                        setShowBuyModal(true);
                      }}
                    >
                      <CardContent className="p-4">
                        {/* Resource header */}
                        <div className="flex items-center gap-3 mb-3">
                          <div className={`w-12 h-12 rounded-lg ${resource.bgColor} flex items-center justify-center text-2xl`}>
                            {resource.icon}
                          </div>
                          <div className="flex-1">
                            <div className={`font-bold ${resource.textColor}`}>{resource.name}</div>
                            <div className="text-xs text-text-muted">
                              {listing.is_city_market ? (
                                <span className="inline-flex items-center gap-1 text-cyber-cyan" data-testid={`city-market-seller-${listing.id}`}>🏙 {t('cityMarketName')}</span>
                              ) : listing.seller_username}
                            </div>
                          </div>
                        </div>
                        
                        {/* Price & Amount */}
                        <div className="grid grid-cols-2 gap-2 mb-3">
                          <div className="bg-white/5 rounded-lg p-2 text-center">
                            <div className="text-xs text-text-muted">{t('priceLabel')} {displayPrice(listing).label}</div>
                            <div className="font-bold text-cyber-cyan">{displayPrice(listing).price} $CITY</div>
                          </div>
                          <div className="bg-white/5 rounded-lg p-2 text-center">
                            <div className="text-xs text-text-muted">{t('amountLabel')}</div>
                            <div className="font-bold text-white">{formatAmount(listing.amount)}</div>
                          </div>
                        </div>
                        
                        {/* Total */}
                        <div className="text-sm text-right text-text-muted">
                          {t('totalPrice')}: <span className="text-white">{formatCity(tonToCity(listing.amount * listing.price_per_unit))} $CITY</span>
                        </div>
                      </CardContent>
                    </Card>
                  );
                })
              )}
            </div>
            </>
          )}

          {activeTab === 'my' && (
            <div className="space-y-4">
              {/* v2.2: «no business» warning hidden during tutorial `create_lot`
                  step — the user technically owns a tutorial plot and is
                  expected to list one lot via the dedicated endpoint. */}
              {!isLoading && !canTrade && !isTutorialCreateLotStep && (
                <div
                  className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 text-amber-200 text-sm"
                  data-testid="trading-need-business-notice"
                >
                  {t('cantSellNoBusiness') || 'Чтобы выставлять ресурсы на продажу, купите свой первый бизнес.'}
                </div>
              )}
              {(() => {
                // During the tutorial `create_lot` step we force-show the
                // Sell button even when the slot count is 0/0 — the dedicated
                // /api/tutorial/create-lot endpoint enforces its own (single
                // listing) limit. Outside tutorial: only show if there's a
                // free slot AND the user actually has a business.
                const showButton = isTutorialCreateLotStep
                  ? (slotInfo.used < Math.max(1, slotInfo.max))
                  : (canTrade && slotInfo.used < slotInfo.max);
                const sellButton = (
                  <Button
                    onClick={() => setShowSellModal(true)}
                    className="bg-green-600 hover:bg-green-700"
                    data-testid="tutorial-create-lot-btn"
                  >
                    <Plus className="w-4 h-4 mr-2" />
                    {t('sellResource')}
                  </Button>
                );
                const slotsLabel = (
                  <div className="text-xs text-text-muted text-center" data-testid="my-slots-info">
                    {t('slotsLabel') || 'Slots'}: <span className="text-white font-semibold">{slotInfo.used}/{slotInfo.max}</span>
                    {slotInfo.trade_attache_bonus > 0 && (
                      <span className="text-cyber-cyan/80"> · +{slotInfo.trade_attache_bonus} от Торгового атташе</span>
                    )}
                  </div>
                );

                if (myListings.length === 0) {
                  return (
                    <div className="flex flex-col items-center justify-center py-12 text-text-muted gap-4">
                      <Tag className="w-12 h-12 opacity-50" />
                      <p>{t('noMyListings')}</p>
                      {slotsLabel}
                      {showButton && sellButton}
                    </div>
                  );
                }
                return (
                  <>
                    {myListings.map(listing => {
                      const resource = getResource(listing.resource_type);
                      return (
                        <Card key={listing.id} className={`bg-void border ${resource.borderColor}`}>
                          <CardContent className="p-4 flex items-center gap-4">
                            <div className={`w-12 h-12 rounded-lg ${resource.bgColor} flex items-center justify-center text-2xl`}>
                              {resource.icon}
                            </div>
                            <div className="flex-1">
                              <div className={`font-bold ${resource.textColor}`}>{resource.name}</div>
                              <div className="text-sm text-text-muted">
                                {formatAmount(listing.amount)} × {displayPrice(listing).price} $CITY{displayPrice(listing).label}
                              </div>
                            </div>
                            <div className="text-right">
                              {(() => {
                                const tier = resource.tier || 1;
                                const baseTax = tierTaxes[tier] || 15;
                                // Apply seller's active buffs so the card matches sell-modal preview
                                const reductionPct = (activeBuffMults?.trade_tax_reduction ?? 0) * 100;
                                const feeMult = activeBuffMults?.trade_fee_multiplier ?? 1.0;
                                const effectiveTax = Math.max(0, baseTax - reductionPct) * feeMult;
                                const hasBuff = Math.abs(effectiveTax - baseTax) > 0.0001;
                                const gross = tonToCity(listing.amount * listing.price_per_unit);
                                const afterTax = gross * (1 - effectiveTax / 100);
                                // Credit auto-deduction (sum of all active credits, doubled if overdue)
                                const creditPct = totalCreditPct;
                                const net = afterTax * (1 - creditPct);
                                return (
                                  <>
                                    <div className="flex flex-col items-end gap-0.5">
                                      <span className="text-xs text-text-muted line-through">{formatCity(gross)} $CITY</span>
                                      <span className="text-lg font-bold text-green-400">{formatCity(net)} $CITY</span>
                                    </div>
                                    <div className="flex flex-col items-end text-xs mt-0.5">
                                      <span className="text-amber-500">
                                        {hasBuff ? (
                                          <>
                                            <span className="line-through text-text-muted/60 mr-1">−{baseTax}%</span>
                                            <span className="text-emerald-400">−{effectiveTax.toFixed(2)}%</span>{' '}налог
                                          </>
                                        ) : (
                                          <>−{baseTax}% налог</>
                                        )}
                                      </span>
                                      {creditPct > 0 && (
                                        <span className="text-rose-400" data-testid="listing-card-credit-pct">
                                          −{(creditPct * 100).toFixed(1)}% кредит
                                        </span>
                                      )}
                                    </div>
                                  </>
                                );
                              })()}
                              <Button
                                size="sm"
                                variant="outline"
                                className="mt-1 text-red-400 border-red-500/30"
                                onClick={() => handleCancelListing(listing.id)}
                              >
                                <X className="w-3 h-3 mr-1" /> {t('cancelAction')}
                              </Button>
                            </div>
                          </CardContent>
                        </Card>
                      );
                    })}
                    {showButton ? (
                      <div className="flex flex-col items-center gap-2 pt-2">
                        {slotsLabel}
                        {sellButton}
                      </div>
                    ) : (
                      <div className="flex flex-col items-center gap-1 pt-2">
                        {slotsLabel}
                        <div className="text-[11px] text-amber-400/80">
                          Достигнут лимит активных листингов
                        </div>
                      </div>
                    )}
                  </>
                );
              })()}
            </div>
          )}

          {/* Contracts (Tender B2B marketplace) Tab */}
          {activeTab === 'operations' && (
            <TenderContractsTab
              user={user}
              token={token}
              getResource={getResource}
              resourceCatalog={resourceCatalog}
              t={t}
            />
          )}

          {activeTab === 'offers' && (
            <div className="space-y-6" data-testid="offers-content">

              {/* Sub-tabs: Actual / Mine (Tier-3 only) / Active — full width, mobile-friendly */}
              <div className="grid gap-2 border-b border-white/5 pb-2" style={{ gridTemplateColumns: hasTier3 ? 'repeat(3, minmax(0, 1fr))' : 'repeat(2, minmax(0, 1fr))' }} data-testid="offers-sub-tabs">
                <Button
                  variant={offersSubTab === 'actual' ? 'default' : 'outline'}
                  className={`w-full h-8 flex flex-row items-center justify-center gap-1.5 px-2 text-xs whitespace-nowrap ${offersSubTab === 'actual' ? 'bg-amber-500 text-black hover:bg-amber-400' : 'border-amber-500/30 text-amber-400 hover:bg-amber-500/10'}`}
                  onClick={() => setOffersSubTab('actual')}
                  data-testid="offers-tab-actual"
                >
                  <Shield className="w-3.5 h-3.5 shrink-0" />
                  <span className="leading-none">{t('offersTabActual') || 'Актуальные'}</span>
                  <Badge className="bg-black/20 text-white text-[10px] px-1 py-0 h-4 leading-none">
                    {allianceOffers.filter(o => o.patron_username !== user?.username).length}
                  </Badge>
                </Button>
                {hasTier3 && (
                  <Button
                    variant={offersSubTab === 'mine' ? 'default' : 'outline'}
                    className={`w-full h-8 flex flex-row items-center justify-center gap-1.5 px-2 text-xs whitespace-nowrap ${offersSubTab === 'mine' ? 'bg-purple-600 text-white hover:bg-purple-500' : 'border-purple-500/30 text-purple-400 hover:bg-purple-500/10'}`}
                    onClick={() => setOffersSubTab('mine')}
                    data-testid="offers-tab-mine"
                  >
                    <Crown className="w-3.5 h-3.5 shrink-0" />
                    <span className="leading-none">{t('offersTabMine') || 'Мои'}</span>
                    <Badge className="bg-black/20 text-white text-[10px] px-1 py-0 h-4 leading-none">
                      {myOffers.length}/{myOffersStats.max_published}
                    </Badge>
                  </Button>
                )}
                <Button
                  variant={offersSubTab === 'active' ? 'default' : 'outline'}
                  className={`w-full h-8 flex flex-row items-center justify-center gap-1.5 px-2 text-xs whitespace-nowrap ${offersSubTab === 'active' ? 'bg-cyan-500 text-black hover:bg-cyan-400' : 'border-cyan-500/30 text-cyan-400 hover:bg-cyan-500/10'}`}
                  onClick={() => setOffersSubTab('active')}
                  data-testid="offers-tab-active"
                >
                  <HandshakeIcon className="w-3.5 h-3.5 shrink-0" />
                  <span className="leading-none">{t('offersTabActive') || 'Активные'}</span>
                  <Badge className="bg-black/20 text-white text-[10px] px-1 py-0 h-4 leading-none" data-testid="offers-active-count">
                    {(contracts.as_patron.filter(c => c.status === 'active').length + contracts.as_vassal.filter(c => c.status === 'active').length)}
                  </Badge>
                  {((counterOffers.as_patron?.filter(c => c.status === 'pending').length || 0) + (counterOffers.as_vassal?.filter(c => c.status === 'pending').length || 0)) > 0 && (
                    <Badge
                      className="bg-amber-500/90 text-black text-[10px] px-1 py-0 h-4 leading-none"
                      title={t('counterOffersLabel') || 'Встречные предложения'}
                      data-testid="counter-offers-count-badge"
                    >
                      +{((counterOffers.as_patron?.filter(c => c.status === 'pending').length || 0) + (counterOffers.as_vassal?.filter(c => c.status === 'pending').length || 0))} {t('counterOffersShort') || 'встр.'}
                    </Badge>
                  )}
                </Button>
              </div>

              {/* ═══════ SECTION 1: ОФФЕРЫ АЛЬЯНСОВ ═══════ */}
              {(offersSubTab === 'actual' || offersSubTab === 'mine') && (() => {
                const publishOfferBtn = hasTier3 ? (
                  <Button data-testid="publish-offer-btn"
                    onClick={async () => {
                      if (availableBuffs.length === 0) {
                        try {
                          const res = await fetch(`${API}/tier3/buffs`, { headers: { Authorization: `Bearer ${token}` } });
                          const data = await res.json();
                          setAvailableBuffs(data.buffs || []);
                        } catch {}
                      }
                      setShowPublishOfferModal(true);
                    }}
                    className="bg-purple-600 hover:bg-purple-700 text-white">
                    <Crown className="w-3.5 h-3.5 mr-1.5" />
                    {t('publishOfferShort')}
                  </Button>
                ) : null;
                return (
                  <div>
                    {/* Header: Мои офферы / Alliance offers — ONLY 'mine' tab shows publish btn here */}
                    {offersSubTab === 'mine' && (
                      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
                        <h3 className="text-lg font-bold text-white flex items-center gap-2">
                          <Crown className="w-5 h-5 text-purple-400" />
                          {t('myOffersHeader') || 'Мои офферы'}
                        </h3>
                        {/* Publish button next to header on desktop, full-width below on mobile */}
                        {publishOfferBtn && myOffers.length > 0 && (
                          <div className="w-full sm:w-auto">{publishOfferBtn}</div>
                        )}
                      </div>
                    )}
                    {offersSubTab === 'actual' && (
                      <div className="flex items-center justify-between mb-3">
                        <h3 className="text-lg font-bold text-white flex items-center gap-2">
                          <Shield className="w-5 h-5 text-amber-400" />
                          {t('allianceOffersHeader')}
                        </h3>
                      </div>
                    )}

                {/* My published offers (Tier-3 only) */}
                {offersSubTab === 'mine' && (
                  myOffers.length === 0 ? (
                    <Card className="bg-void border-purple-500/20 border-dashed">
                      <CardContent className="p-6 text-center">
                        <div className="w-12 h-12 mx-auto mb-2 rounded-full bg-purple-500/10 flex items-center justify-center">
                          <Crown className="w-6 h-6 text-purple-400" />
                        </div>
                        <p className="text-white font-medium text-sm mb-1">{t('noPublishedOffers')}</p>
                        <p className="text-text-muted text-xs mb-4">{t('activeAlliancesStat')}: {myOffersStats.active_alliances}/{myOffersStats.max_alliances}. {t('publishedOffersStat')}: 0/{myOffersStats.max_published}.</p>
                        {publishOfferBtn && <div className="flex justify-center">{publishOfferBtn}</div>}
                      </CardContent>
                    </Card>
                  ) : (
                    <div className="space-y-3">
                      <div className="text-[11px] text-text-muted">
                        {t('activeAlliancesStat')}: <span className="text-white font-mono">{myOffersStats.active_alliances}/{myOffersStats.max_alliances}</span> ·
                        &nbsp;{t('publishedOffersStat')}: <span className="text-white font-mono">{myOffers.length}/{myOffersStats.max_published}</span>
                      </div>
                      <div className="grid gap-3 lg:grid-cols-3">
                        {myOffers.map(offer => {
                          const ct = OFFER_CONTRACT_TYPES[offer.contract_type] || {};
                          const cancelFee = offer.cancel_fee_city ?? (offer.duration_days || 30) * 100;
                          const isPaused = offer.status === 'paused';
                          return (
                            <Card key={offer.id} className={`bg-void overflow-hidden flex flex-col ${isPaused ? 'border-orange-500/30' : 'border-purple-500/20'}`} data-testid={`my-offer-${offer.id}`}>
                              <div className="h-1" style={{ background: isPaused ? 'linear-gradient(90deg,#f97316,#f9731666)' : `linear-gradient(90deg, ${ct.color || '#a855f7'}, ${ct.color || '#a855f7'}66)` }} />
                              <CardContent className="p-3 flex flex-col gap-2 flex-1">
                                <div className="flex items-center gap-2 flex-wrap">
                                  <span className="text-lg">{offer.patron_business_icon}</span>
                                  <span className="font-bold text-white text-sm truncate">
                                    {offer.patron_business_name} <span className="text-text-muted font-normal">({t('levelShort')} {offer.patron_level || 1})</span>
                                  </span>
                                  {isPaused && <Badge className="bg-orange-500/20 text-orange-300 text-[10px]">{t('pausedAlliancesLabel')}</Badge>}
                                </div>
                                <div className="flex items-center gap-1.5 text-xs">
                                  <Clock className="w-3 h-3 text-amber-400 shrink-0" />
                                  <span className="text-text-muted">{t('termLabelShort')}:</span>
                                  <span className="text-white font-medium">{offer.duration_days} {t('daysShort')}</span>
                                </div>
                                <div className="flex items-center gap-1.5 text-xs">
                                  <AlertCircle className="w-3 h-3 text-red-400 shrink-0" />
                                  <span className="text-text-muted">{t('cancelFeeLabelShort')}:</span>
                                  <span className="text-red-300 font-mono">{cancelFee.toLocaleString()} $CITY</span>
                                </div>
                                <div className="flex items-center gap-1.5 text-xs">
                                  <Check className="w-3 h-3 text-emerald-400 shrink-0" />
                                  <span className="text-text-muted">{t('acceptedCountLabel')}:</span>
                                  <span className="text-emerald-300 font-mono">{offer.acceptances_count || 0}</span>
                                </div>
                                {/* Patron POV: vassal gives = GREEN (patron receives), vassal receives = RED (patron gives) */}
                                <div className="p-1.5 rounded bg-green-500/10 border border-green-500/20">
                                  <div className="text-[10px] text-green-400 font-medium mb-0.5">{t('vassalGivesLabel')}</div>
                                  <div className="text-xs text-white">{offer.vassal_pays || ct.vassal_note}</div>
                                </div>
                                <div className="p-1.5 rounded bg-red-500/10 border border-red-500/20">
                                  <div className="text-[10px] text-red-400 font-medium mb-0.5">{t('vassalReceivesLabel')}</div>
                                  <div className="text-xs text-white">{offer.buff_description || offer.buff_name}</div>
                                </div>
                                <div className="flex justify-end mt-auto pt-2">
                                  <Button size="sm" variant="outline" className="border-red-500/40 text-red-400 hover:bg-red-500/10 h-8 text-xs"
                                    data-testid={`cancel-my-offer-${offer.id}`} onClick={() => handleCancelMyOffer(offer.id)}>
                                    <X className="w-3 h-3 mr-1" /> {t('removeOfferBtn')}
                                  </Button>
                                </div>
                              </CardContent>
                            </Card>
                          );
                        })}
                      </div>
                    </div>
                  )
                )}

                {/* Browsable offers from other patrons */}
                {offersSubTab === 'actual' && (() => {
                  const otherOffers = allianceOffers.filter(o => o.patron_username !== user?.username);
                  const visibleOffers = otherOffers.slice(0, OFFERS_PER_PAGE);
                  const hasMore = otherOffers.length > OFFERS_PER_PAGE;
                  return otherOffers.length === 0 ? (
                    <Card className="bg-void border-amber-500/20 border-dashed">
                      <CardContent className="p-6 text-center">
                        <div className="w-12 h-12 mx-auto mb-2 rounded-full bg-amber-500/10 flex items-center justify-center">
                          <Shield className="w-6 h-6 text-amber-400" />
                        </div>
                        <p className="text-white font-medium text-sm mb-1">{t('noOffersAvailableTitle')}</p>
                        <p className="text-text-muted text-xs">{t('patronsWillPublishHint')}</p>
                      </CardContent>
                    </Card>
                  ) : (
                    <>
                      <div className="grid gap-3 lg:grid-cols-3">
                        {visibleOffers.map(offer => {
                          const ct = OFFER_CONTRACT_TYPES[offer.contract_type] || {};
                          return (
                            <motion.div key={offer.id} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
                              <Card className={`bg-void ${ct.border || 'border-white/10'} overflow-hidden flex flex-col h-full`} data-testid={`offer-card-${offer.id}`}>
                                <div className="h-1" style={{ background: `linear-gradient(90deg, ${ct.color || '#f59e0b'}, ${ct.color || '#f59e0b'}66)` }} />
                                <CardContent className="p-3 flex flex-col gap-2 flex-1">
                                  <div className="flex items-center gap-2 flex-wrap">
                                    <span className="text-lg">{offer.patron_business_icon}</span>
                                    <span className="font-bold text-white text-sm truncate">
                                      {offer.patron_business_name} <span className="text-text-muted font-normal">({t('levelShort')} {offer.patron_level || 1})</span>
                                    </span>
                                  </div>
                                  <div className="flex items-center gap-1.5 text-xs">
                                    <Crown className="w-3 h-3 text-purple-400 shrink-0" />
                                    <span className="text-text-muted">{t('ownerLabelShort')}:</span>
                                    <span className="text-purple-300 font-medium truncate">{offer.patron_username}</span>
                                  </div>
                                  <div className="flex items-center gap-1.5 text-xs">
                                    <Clock className="w-3 h-3 text-amber-400 shrink-0" />
                                    <span className="text-text-muted">{t('termLabelShort')}:</span>
                                    <span className="text-white font-medium">{offer.duration_days} {t('daysShort')}</span>
                                  </div>
                                  <div className="flex items-center gap-1.5 text-xs">
                                    <AlertCircle className="w-3 h-3 text-red-400 shrink-0" />
                                    <span className="text-text-muted">{t('cancelFeeLabelShort')}:</span>
                                    <span className="text-red-300 font-mono">{(offer.cancel_fee_city ?? offer.duration_days * 100).toLocaleString()} $CITY</span>
                                  </div>
                                  {/* Vassal POV: gives = RED (loses it), receives = GREEN (gains it) */}
                                  <div className="p-1.5 rounded bg-red-500/10 border border-red-500/20">
                                    <div className="text-[10px] text-red-400 font-medium mb-0.5 flex items-center gap-1">
                                      <ArrowRight className="w-3 h-3" /> {t('vassalGivesLabel')}
                                    </div>
                                    <div className="text-xs text-white">{offer.vassal_pays || ct.vassal_note}</div>
                                  </div>
                                  <div className="p-1.5 rounded bg-green-500/10 border border-green-500/20">
                                    <div className="text-[10px] text-green-400 font-medium mb-0.5 flex items-center gap-1">
                                      <Check className="w-3 h-3" /> {t('vassalReceivesLabel')}
                                    </div>
                                    <div className="text-xs text-white">{offer.buff_description || offer.buff_name}</div>
                                  </div>
                                  <div className="flex justify-end gap-1.5 mt-auto pt-2 flex-wrap">
                                    <Button size="sm" variant="outline" className="border-cyan-500/40 text-cyan-400 hover:bg-cyan-500/10 h-8 text-xs"
                                      data-testid={`counter-offer-${offer.id}`}
                                      onClick={async () => {
                                        setCounterTarget(offer);
                                        setCounterType(offer.contract_type || 'tax_haven');
                                        setCounterDuration(offer.duration_days || 30);
                                        setCounterBusinessId('');
                                        setCounterBuffId('');
                                        if (availableBuffs.length === 0) {
                                          try {
                                            const r = await fetch(`${API}/tier3/buffs`, { headers: { Authorization: `Bearer ${token}` } });
                                            if (r.ok) { const d = await r.json(); setAvailableBuffs(d.buffs || []); }
                                          } catch {}
                                        }
                                        setShowCounterModal(true);
                                      }}>
                                      <MessageSquare className="w-3 h-3 mr-1" /> {t('counterOfferBtn')}
                                    </Button>
                                    <Button size="sm" variant="ghost" className="text-text-muted hover:text-white border border-white/10 h-8 text-xs"
                                      data-testid={`hide-offer-${offer.id}`} onClick={() => handleHideOffer(offer.id)}>
                                      <EyeOff className="w-3 h-3 mr-1" /> {t('hideOfferBtn')}
                                    </Button>
                                    <Button size="sm" className="bg-green-600 hover:bg-green-700 text-white h-8 text-xs"
                                      data-testid={`accept-offer-${offer.id}`} onClick={() => handleAcceptOffer(offer)}>
                                      <Check className="w-3.5 h-3.5 mr-1" /> {t('acceptOfferBtn')}
                                    </Button>
                                  </div>
                                </CardContent>
                              </Card>
                            </motion.div>
                          );
                        })}
                      </div>
                      {hasMore && (
                        <div className="flex justify-center mt-3">
                          <Button variant="outline" onClick={() => setShowAllOffersModal(true)}
                            className="border-amber-500/30 text-amber-400 hover:bg-amber-500/10" data-testid="show-all-offers-btn">
                            <ChevronDown className="w-4 h-4 mr-2" /> {t('showAllShort') || 'Показать все'} ({otherOffers.length})
                          </Button>
                        </div>
                      )}
                    </>
                  );
                })()}
                  </div>
                );
              })()}

              {/* ═══════ SECTION 2: АКТИВНЫЕ АЛЬЯНСЫ ═══════ */}
              {offersSubTab === 'active' && (() => {
                const totalContracts = contracts.as_patron.length + contracts.as_vassal.length;
                const pendingVassal = contracts.as_vassal.filter(c => c.status === 'proposed').length;
                const activeContracts = [...contracts.as_patron, ...contracts.as_vassal].filter(c => c.status === 'active');
                const pendingSent = contracts.as_patron.filter(c => c.status === 'proposed');
                const incomingProposals = contracts.as_vassal.filter(c => c.status === 'proposed');

                return (
                  <div data-testid="alliances-section">
                    {/* Counter-offers received (patron side) */}
                    {counterOffers.as_patron.length > 0 && (
                      <div className="mb-4">
                        <div className="text-sm text-cyan-400 font-semibold mb-2 flex items-center gap-1.5">
                          <MessageSquare className="w-4 h-4" /> Встречные предложения ({counterOffers.as_patron.length})
                        </div>
                        <div className="space-y-2">
                          {counterOffers.as_patron.map(co => {
                            const ct = OFFER_CONTRACT_TYPES[co.proposed_contract_type] || {};
                            const origCt = OFFER_CONTRACT_TYPES[co.original_contract_type] || {};
                            const changed = co.proposed_contract_type !== co.original_contract_type || co.proposed_duration !== co.original_duration;
                            return (
                              <Card key={co.id} className="bg-void border-cyan-500/30 overflow-hidden" data-testid={`counter-offer-${co.id}`}>
                                <div className="h-1 bg-gradient-to-r from-cyan-500 to-blue-500" />
                                <CardContent className="p-3">
                                  <div className="flex items-start justify-between gap-3">
                                    <div className="flex-1 min-w-0">
                                      <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                                        <span className="text-sm font-bold text-white">{co.vassal_username}</span>
                                        <span className="text-xs text-text-muted">{co.vassal_business_icon} {co.vassal_business_name}</span>
                                      </div>
                                      {changed && (
                                        <div className="text-xs mb-1.5 space-y-0.5">
                                          <div className="text-text-muted">Было: {origCt.icon} {origCt.name}, {co.original_duration} дн.</div>
                                          <div className="text-cyan-400 font-medium">Предлагает: {ct.icon} {ct.name}, {co.proposed_duration} дн.</div>
                                        </div>
                                      )}
                                      {!changed && <div className="text-xs text-cyan-400 mb-1.5">Согласен с условиями, предлагает альянс</div>}
                                      {co.comment && <div className="text-xs text-text-muted italic bg-white/5 rounded p-1.5 mb-1.5">"{co.comment}"</div>}
                                      <div className="text-[10px] text-text-muted">Баф: {co.buff_icon} {co.buff_name}</div>
                                    </div>
                                    <div className="flex flex-col gap-1.5 shrink-0">
                                      <Button size="sm" className="bg-green-600 hover:bg-green-700 text-white h-7 text-xs"
                                        onClick={() => handleCounterOfferAction(co.id, 'accept')}>
                                        <Check className="w-3 h-3 mr-1" /> {t('acceptOffer')}
                                      </Button>
                                      <Button size="sm" variant="outline" className="border-red-500/40 text-red-400 h-7 text-xs"
                                        onClick={() => handleCounterOfferAction(co.id, 'reject')}>
                                        <X className="w-3 h-3 mr-1" /> {t('rejectOffer')}
                                      </Button>
                                      <Button size="sm" variant="ghost" className="text-text-muted h-7 text-xs"
                                        onClick={() => handleCounterOfferAction(co.id, 'hide')}>
                                        <EyeOff className="w-3 h-3 mr-1" /> {t('hideOffer')}
                                      </Button>
                                    </div>
                                  </div>
                                </CardContent>
                              </Card>
                            );
                          })}
                        </div>
                      </div>
                    )}

                    {/* Incoming proposals */}
                    {incomingProposals.length > 0 && (
                      <div className="mb-4">
                        <div className="text-sm text-amber-400 font-semibold mb-2 flex items-center gap-1.5">
                          <AlertCircle className="w-4 h-4" /> {t('incomingProposals')} ({incomingProposals.length})
                        </div>
                        <div className="space-y-2">
                          {incomingProposals.map(c => {
                            const ct = OFFER_CONTRACT_TYPES[c.type] || {};
                            return (
                            <motion.div key={c.id} initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }}>
                              <Card className="bg-void border-amber-500/30 overflow-hidden" data-testid={`proposal-card-${c.id}`}>
                                <div className="h-1 bg-gradient-to-r from-amber-500 to-orange-500" />
                                <CardContent className="p-3">
                                  <div className="flex items-start justify-between gap-3">
                                    <div className="flex-1 min-w-0">
                                      <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                                        <span className="text-xl">{ct.icon}</span>
                                        <span className="font-bold text-white text-sm">{ct.name}</span>
                                      </div>
                                      <div className="grid grid-cols-2 gap-2 mb-2">
                                        <div className="p-1.5 rounded bg-green-500/10 border border-green-500/20">
                                          <div className="text-[10px] text-green-400 font-medium">Вы получите баф</div>
                                          <div className="text-xs text-white">{c.buff_data?.icon} {c.buff_data?.name || 'Баф'}</div>
                                        </div>
                                        <div className="p-1.5 rounded bg-red-500/10 border border-red-500/20">
                                          <div className="text-[10px] text-red-400 font-medium">Вы отдаёте</div>
                                          <div className="text-xs text-white">{ct.vassal_note || c.contract_type_data?.patron_benefit}</div>
                                        </div>
                                      </div>
                                      <div className="flex items-center gap-3 text-xs text-text-muted flex-wrap">
                                        <span>Патрон: <span className="text-purple-300">{c.patron_username}</span></span>
                                        <span>{c.patron_business_icon} {c.patron_business_name}</span>
                                        <span>Срок: <span className="text-white">{c.duration_days || 30} дн.</span></span>
                                      </div>
                                    </div>
                                    <div className="flex flex-col gap-1.5 shrink-0">
                                      <Button size="sm" className="bg-green-600 hover:bg-green-700 text-white h-7 text-xs"
                                        data-testid={`accept-contract-${c.id}`} onClick={() => handleContractAction(c.id, 'accept')}>
                                        <Check className="w-3 h-3 mr-1" /> {t('acceptOffer')}
                                      </Button>
                                      <Button size="sm" variant="outline" className="border-red-500/40 text-red-400 h-7 text-xs"
                                        data-testid={`reject-contract-${c.id}`} onClick={() => handleContractAction(c.id, 'reject')}>
                                        <X className="w-3 h-3 mr-1" /> {t('rejectOffer')}
                                      </Button>
                                      <Button size="sm" variant="ghost" className="text-text-muted hover:text-white h-7 text-xs"
                                        onClick={() => handleHideContract(c.id)}>
                                        <EyeOff className="w-3 h-3 mr-1" /> Скрыть
                                      </Button>
                                    </div>
                                  </div>
                                </CardContent>
                              </Card>
                            </motion.div>
                            );
                          })}
                        </div>
                      </div>
                    )}

                    {/* Active contracts */}
                    {activeContracts.length > 0 && (
                      <div className="mb-4">
                        <div className="text-sm text-green-400 font-semibold mb-2 flex items-center gap-1.5">
                          <Check className="w-4 h-4" /> {t('activeAlliances')} ({activeContracts.length})
                        </div>
                        <div className="grid gap-3 lg:grid-cols-3">
                          {[...contracts.as_patron.filter(c => c.status === 'active').map(c => ({...c, role: 'patron'})),
                             ...contracts.as_vassal.filter(c => c.status === 'active').map(c => ({...c, role: 'vassal'}))].map(c => {
                            const progressPct = c.progress_pct || 0;
                            const daysLeft = c.days_remaining ?? (c.duration_days || 30);
                            const cancelFee = c.cancel_fee_city ?? (c.duration_days || 30) * 100;
                            const typeInfo = OFFER_CONTRACT_TYPES[c.type] || {};
                            const isPatron = c.role === 'patron';
                            // Color inversion based on role (patron POV: invert)
                            const givesColor = isPatron ? 'green' : 'red';
                            const receivesColor = isPatron ? 'red' : 'green';
                            return (
                              <Card key={c.id} className={`bg-void ${typeInfo.border || 'border-white/10'} overflow-hidden flex flex-col relative`} data-testid={`active-contract-${c.id}`}>
                                {/* Corner badge: days remaining until auto-cancel from violations (only when streak active) */}
                                {(() => {
                                  const vDays = Array.isArray(c.violation_days) ? c.violation_days : [];
                                  if (vDays.length === 0) return null;
                                  // Consecutive streak counted from latest day
                                  const sortedDays = [...vDays].sort();
                                  let streak = 1;
                                  for (let i = sortedDays.length - 1; i > 0; i--) {
                                    const a = new Date(sortedDays[i]); const b = new Date(sortedDays[i - 1]);
                                    if (Math.round((a - b) / 86400000) === 1) streak++;
                                    else break;
                                  }
                                  const daysUntilAutoCancel = Math.max(0, 3 - streak);
                                  const isPatronView = isPatron;
                                  const tone = daysUntilAutoCancel === 0
                                    ? 'bg-red-600 text-white animate-pulse'
                                    : daysUntilAutoCancel === 1
                                    ? 'bg-red-500/90 text-white'
                                    : 'bg-amber-500/90 text-black';
                                  return (
                                    <div className={`absolute top-2 right-2 z-10 px-2 py-1 rounded-md text-[10px] font-bold shadow ${tone}`}
                                      data-testid={`violation-corner-${c.id}`}
                                      title={isPatronView ? (t('autoCancelTooltipPatron') || 'Дней до авто-расторжения за нарушения вассала') : (t('autoCancelTooltipVassal') || 'Дней до авто-расторжения')}>
                                      <AlertCircle className="w-3 h-3 inline -mt-0.5 mr-1" />
                                      {daysUntilAutoCancel === 0
                                        ? (t('autoCancelImminent') || 'Авто-расторжение сегодня!')
                                        : `${daysUntilAutoCancel} ${t('daysShort') || 'дн.'} · ${t('toAutoCancel') || 'до авто-расторжения'}`}
                                    </div>
                                  );
                                })()}
                                <div className="h-1.5 bg-gray-700/50 relative">
                                  <div className="h-full rounded-r-full transition-all duration-1000"
                                    style={{ width: `${progressPct}%`, background: `linear-gradient(90deg, ${typeInfo.color || '#a855f7'}, ${typeInfo.color || '#a855f7'}88)` }} />
                                </div>
                                <CardContent className="p-3 flex flex-col gap-2 flex-1">
                                  <div className="flex items-center gap-2 flex-wrap">
                                    <span className="text-lg">{c.patron_business_icon}</span>
                                    <span className="font-bold text-white text-sm truncate">
                                      {c.patron_business_name} <span className="text-text-muted font-normal">({t('levelShort')} {c.patron_business_level || 1})</span>
                                    </span>
                                    <Badge className={`text-[10px] ${isPatron ? 'bg-purple-500/20 text-purple-400' : 'bg-cyan-500/20 text-cyan-400'}`}>
                                      {isPatron ? t('patronRoleShort') : t('vassalRoleShort')}
                                    </Badge>
                                  </div>
                                  <div className="flex items-center gap-1.5 text-xs">
                                    <Crown className="w-3 h-3 text-purple-400 shrink-0" />
                                    <span className="text-text-muted">{t('ownerLabelShort')}:</span>
                                    <span className="text-purple-300 font-medium truncate">{c.patron_username}</span>
                                  </div>
                                  <div className="flex items-center gap-1.5 text-xs">
                                    <Users className="w-3 h-3 text-cyan-400 shrink-0" />
                                    <span className="text-text-muted">{t('vassalRoleShort')}:</span>
                                    <span className="text-cyan-300 font-medium truncate">{c.vassal_username} · {c.vassal_business_icon} {c.vassal_business_name} ({t('levelShort')} {c.vassal_business_level || 1})</span>
                                  </div>
                                  <div className="flex items-center gap-1.5 text-xs">
                                    <Clock className="w-3 h-3 text-amber-400 shrink-0" />
                                    <span className="text-text-muted">{t('termLabelShort')}:</span>
                                    <span className="text-white font-medium">{daysLeft}/{c.duration_days || 30} {t('daysShort')}</span>
                                  </div>
                                  <div className="flex items-center gap-1.5 text-xs">
                                    <AlertCircle className="w-3 h-3 text-red-400 shrink-0" />
                                    <span className="text-text-muted">{t('cancelFeeLabelShort')}:</span>
                                    <span className="text-red-300 font-mono">{cancelFee.toLocaleString()} $CITY</span>
                                  </div>
                                  {(() => {
                                    const givesGreen = isPatron;
                                    return (
                                      <>
                                        <div className={`p-1.5 rounded ${givesGreen ? 'bg-green-500/10 border border-green-500/20' : 'bg-red-500/10 border border-red-500/20'}`}>
                                          <div className={`text-[10px] font-medium mb-0.5 ${givesGreen ? 'text-green-400' : 'text-red-400'}`}>{t('vassalGivesLabel')}</div>
                                          <div className="text-xs text-white">{c.vassal_pays || c.contract_type_data?.patron_benefit || c.patron_benefit_text}</div>
                                        </div>
                                        <div className={`p-1.5 rounded ${givesGreen ? 'bg-red-500/10 border border-red-500/20' : 'bg-green-500/10 border border-green-500/20'}`}>
                                          <div className={`text-[10px] font-medium mb-0.5 ${givesGreen ? 'text-red-400' : 'text-green-400'}`}>{t('vassalReceivesLabel')}</div>
                                          <div className="text-xs text-white">
                                            {c.buff_data?.description || c.buff_description || c.buff_data?.name || c.buff_name}
                                          </div>
                                        </div>
                                      </>
                                    );
                                  })()}
                                  {/* Violation history: 3-dot tracker + last-3 list */}
                                  {(() => {
                                    const vDays = Array.isArray(c.violation_days) ? c.violation_days : [];
                                    if (vDays.length === 0) return null;
                                    const sortedDays = [...vDays].sort();
                                    let streak = 1;
                                    for (let i = sortedDays.length - 1; i > 0; i--) {
                                      const a = new Date(sortedDays[i]); const b = new Date(sortedDays[i - 1]);
                                      if (Math.round((a - b) / 86400000) === 1) streak++;
                                      else break;
                                    }
                                    const dots = [0, 1, 2].map(i => i < streak);
                                    const recent3 = sortedDays.slice(-3);
                                    return (
                                      <div className="p-1.5 rounded bg-red-500/10 border border-red-500/20" data-testid={`violation-history-${c.id}`}>
                                        <div className="flex items-center justify-between gap-2">
                                          <div className="text-[10px] font-medium text-red-300 flex items-center gap-1">
                                            <AlertCircle className="w-3 h-3" />
                                            {t('violationsLabel') || 'Нарушения'} · {streak}/3
                                          </div>
                                          <div className="flex gap-1">
                                            {dots.map((on, i) => (
                                              <span key={i}
                                                data-testid={`violation-dot-${c.id}-${i}`}
                                                className={`w-2.5 h-2.5 rounded-full ${on ? 'bg-red-500' : 'bg-white/15'} ${on && i === streak - 1 ? 'ring-2 ring-red-300/60' : ''}`}/>
                                            ))}
                                          </div>
                                        </div>
                                        <div className="mt-1 text-[10px] text-text-muted font-mono">
                                          {recent3.join(' · ')}
                                        </div>
                                      </div>
                                    );
                                  })()}
                                  <div className="flex justify-end mt-auto pt-2">
                                    <Button size="sm" variant="outline" className="border-red-500/40 text-red-400 hover:bg-red-500/10 h-8 text-xs"
                                      data-testid={`cancel-contract-${c.id}`}
                                      onClick={() => setCancelConfirmContract(c)}>
                                      <X className="w-3 h-3 mr-1" /> {t('breakAllianceBtn')}
                                    </Button>
                                  </div>
                                </CardContent>
                              </Card>
                            );
                          })}
                        </div>
                      </div>
                    )}

                    {/* Pending sent proposals */}
                    {pendingSent.length > 0 && (
                      <div className="mb-4">
                        <div className="text-sm text-text-muted font-semibold mb-2 flex items-center gap-1.5">
                          <Clock className="w-4 h-4" /> Ожидают ответа ({pendingSent.length})
                        </div>
                        <div className="space-y-2">
                          {pendingSent.map(c => {
                            const ct = OFFER_CONTRACT_TYPES[c.type] || {};
                            return (
                            <Card key={c.id} className="bg-void border-white/10">
                              <CardContent className="p-3 flex items-center justify-between gap-3">
                                <div className="flex-1 min-w-0">
                                  <div className="flex items-center gap-2">
                                    <span>{ct.icon}</span>
                                    <span className="text-sm text-white truncate">{ct.name}</span>
                                    <div className="flex items-center gap-1"><div className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" /><span className="text-xs text-amber-400">Ожидание</span></div>
                                  </div>
                                  <p className="text-xs text-text-muted mt-0.5">
                                    → {c.vassal_username} ({c.vassal_business_icon} {c.vassal_business_name})
                                    <span className="ml-2 text-white/40">|</span><span className="ml-2">{c.duration_days || 30} дн.</span>
                                  </p>
                                </div>
                                <Button size="sm" variant="outline" className="border-red-500/30 text-red-400 shrink-0 h-7 text-xs"
                                  onClick={() => handleContractAction(c.id, 'cancel')}>Отозвать</Button>
                              </CardContent>
                            </Card>
                            );
                          })}
                        </div>
                      </div>
                    )}

                    {/* Empty state */}
                    {totalContracts === 0 && (
                      <Card className="bg-void border-purple-500/20 border-dashed">
                        <CardContent className="p-6 text-center">
                          <div className="w-12 h-12 mx-auto mb-2 rounded-full bg-purple-500/10 flex items-center justify-center">
                            <Scroll className="w-6 h-6 text-purple-400" />
                          </div>
                          <p className="text-white font-medium text-sm mb-1">{t('noActiveAlliancesTitle')}</p>
                          <p className="text-text-muted text-xs">{t('acceptOfferHint')}</p>
                        </CardContent>
                      </Card>
                    )}
                  </div>
                );
              })()}
            </div>
          )}

        </div>
      </main>

      {/* Create Contract Modal */}
      <Dialog open={showCreateContract} onOpenChange={setShowCreateContract}>
        <DialogContent className="bg-void border-purple-500/30 w-[calc(100%-2rem)] max-w-lg !rounded-2xl">
          <DialogHeader>
            <DialogTitle className="text-white flex items-center gap-2">
              <Handshake className="w-5 h-5 text-purple-400" />
              {t('createContract')}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label>{t('resourceToSupply')}</Label>
              <Select value={contractResource} onValueChange={(v) => { setContractResource(v); setContractAmount(''); }}>
                <SelectTrigger className="bg-white/5 border-white/10">
                  <SelectValue placeholder={t('selectResourcePlaceholder')} />
                </SelectTrigger>
                <SelectContent>
                  {availableResources.length > 0 ? availableResources.map(r => (
                    <SelectItem key={r.id} value={r.id}>
                      <div className="flex items-center gap-2">
                        <span>{r.icon}</span>
                        <span>{tResource(r.id, language) || r.name}</span>
                        <span className="text-xs text-text-muted">({Math.floor(myResources[r.id] || 0)} {t('unitsShort')})</span>
                      </div>
                    </SelectItem>
                  )) : (
                    <SelectItem value="none" disabled>{t('noResources')}</SelectItem>
                  )}
                </SelectContent>
              </Select>
            </div>
            {(() => {
              const selectedRes = contractResource ? getResource(contractResource, language) : null;
              const tier = selectedRes?.tier || 1;
              const isTier1 = tier === 1;
              const priceLabel = isTier1 ? t('pricePer10Label') : t('pricePer1Label');
              return (
                <>
                  {contractResource && isTier1 && (
                    <div className="text-xs text-amber-400 bg-amber-500/10 rounded p-2">
                      {t('tier1Hint')}
                    </div>
                  )}
                  {contractResource && !isTier1 && (
                    <div className="text-xs text-amber-400 bg-amber-500/10 rounded p-2">
                      {t('tierNHint').replace('{tier}', tier)}
                    </div>
                  )}
                  <div>
                    <Label>{t('amountPerDay')} {isTier1 && <span className="text-xs text-amber-400">({t('amountMultiple10')})</span>}</Label>
                    <Input
                      type="number" min={isTier1 ? "10" : "1"} step={isTier1 ? "10" : "1"} max={MAX_PRICE_VALUE}
                      value={contractAmount} onChange={(e) => setContractAmount(clampPriceValue(e.target.value))}
                      placeholder={isTier1 ? "10" : "1"}
                      className="bg-white/5 border-white/10"
                    />
                  </div>
                  <div>
                    <Label>{priceLabel}</Label>
                    <Input
                      type="number" min="1" step="1" max={MAX_PRICE_VALUE}
                      value={contractPrice} onChange={(e) => setContractPrice(clampPriceValue(e.target.value))}
                      placeholder="29"
                      className="bg-white/5 border-white/10"
                    />
                    {contractAmount && contractPrice && (
                      <div className="text-xs text-text-muted mt-1">
                        {t('dailyCostLabel')}: <span className="text-yellow-400 font-bold">
                          {formatCity(
                            tier === 1 
                              ? (parseFloat(contractAmount) / 10) * parseFloat(contractPrice)
                              : parseFloat(contractAmount) * parseFloat(contractPrice)
                          )} $CITY
                        </span>
                      </div>
                    )}
                  </div>
                </>
              );
            })()}
            <div>
              <Label>{t('contractDuration')}</Label>
              <Input
                type="number" min="1" max="90" step="1"
                value={contractDuration} onChange={(e) => setContractDuration(e.target.value)}
                placeholder="30"
                className="bg-white/5 border-white/10"
              />
            </div>
          </div>
          <DialogFooter className="flex-row gap-2 justify-end">
            <Button
              data-testid="submit-contract-btn"
              onClick={handleCreateContract}
              disabled={isCreatingContract || !contractResource || !contractAmount || !contractPrice}
              className="bg-purple-500 hover:bg-purple-600 w-full"
            >
              {isCreatingContract ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <Handshake className="w-4 h-4 mr-2" />}
              {t('createBtn') || 'Создать'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>


      {/* Filters Modal */}
      <Dialog open={showFilters} onOpenChange={setShowFilters}>
        <DialogContent className="bg-black border-white/10 !rounded-2xl">
          <DialogHeader>
            <DialogTitle className="text-white flex items-center gap-2">
              <Filter className="w-5 h-5 text-cyber-cyan" />
              {t('filtersBtn')}
            </DialogTitle>
          </DialogHeader>
          
          <div className="space-y-4">
            {/* Resource filter with icons */}
            <div>
              <Label>{t('resourceLabel')}</Label>
              <Select value={filters.resource} onValueChange={(v) => setFilters(f => ({ ...f, resource: v }))}>
                <SelectTrigger className="bg-white/5 border-white/10">
                  <SelectValue placeholder={t('allTypes')} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">
                    <div className="flex items-center gap-2">{t('allTypes')}</div>
                  </SelectItem>
                  {getAllResources().map(r => (
                    <SelectItem key={r.id} value={r.id}>
                      <div className="flex items-center gap-2">
                        <span>{r.icon}</span>
                        <span>{tResource(r.id, language) || r.name}</span>
                      </div>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            
            {/* Price range */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>{t('minPriceTon')}</Label>
                <Input
                  type="number"
                  step="1"
                  min="0"
                  placeholder="0"
                  value={filters.minPrice}
                  onChange={(e) => setFilters(f => ({ ...f, minPrice: e.target.value }))}
                  className="bg-white/5 border-white/10"
                />
              </div>
              <div>
                <Label>{t('maxPriceTon')}</Label>
                <Input
                  type="number"
                  step="1"
                  min="0"
                  placeholder="100000"
                  value={filters.maxPrice}
                  onChange={(e) => setFilters(f => ({ ...f, maxPrice: e.target.value }))}
                  className="bg-white/5 border-white/10"
                />
              </div>
            </div>
            
            {/* Amount range */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>{t('minAmountLabel')}</Label>
                <Input
                  type="number"
                  min="1"
                  step="1"
                  placeholder="1"
                  value={filters.minAmount}
                  onChange={(e) => setFilters(f => ({ ...f, minAmount: e.target.value }))}
                  className="bg-white/5 border-white/10"
                />
              </div>
              <div>
                <Label>{t('maxAmountLabel')}</Label>
                <Input
                  type="number"
                  min="1"
                  step="1"
                  placeholder="1000"
                  value={filters.maxAmount}
                  onChange={(e) => setFilters(f => ({ ...f, maxAmount: e.target.value }))}
                  className="bg-white/5 border-white/10"
                />
              </div>
            </div>
            
            {/* Sort */}
            <div>
              <Label>{t('sortLabel')}</Label>
              <Select value={filters.sortBy} onValueChange={(v) => setFilters(f => ({ ...f, sortBy: v }))}>
                <SelectTrigger className="bg-white/5 border-white/10">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="price_asc">{t('priceAscFull')}</SelectItem>
                  <SelectItem value="price_desc">{t('priceDescFull')}</SelectItem>
                  <SelectItem value="amount_desc">{t('amountDescFull')}</SelectItem>
                  <SelectItem value="newest">{t('newestFull')}</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          
          <DialogFooter>
            <Button variant="outline" onClick={resetFilters} className="border-white/10">
              {t('resetFilters')}
            </Button>
            <Button onClick={applyFilters} className="bg-cyber-cyan text-black">
              <Check className="w-4 h-4 mr-2" />
              {t('apply')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Sell Modal */}
      <Dialog open={showSellModal} onOpenChange={setShowSellModal}>
        <DialogContent
          className="bg-void border-green-500/30 !rounded-2xl"
          data-testid="sell-resource-modal"
          onPointerDownOutside={(e) => {
            // Lock modal open during tutorial create_lot step — user must complete
            // the highlighted resource → amount → price → confirm flow.
            if (tutorial?.active && tutorial?.currentStepId === 'create_lot') e.preventDefault();
          }}
          onEscapeKeyDown={(e) => {
            if (tutorial?.active && tutorial?.currentStepId === 'create_lot') e.preventDefault();
          }}
        >
          <DialogHeader>
            <DialogTitle className="text-white flex items-center gap-2">
              <Tag className="w-5 h-5 text-green-400" />
              {t('listForSale')}
            </DialogTitle>
          </DialogHeader>
          
          <div className="space-y-4">
            {availableResources.length === 0 ? (
              <div className="text-center py-6 text-text-muted">
                <Package className="w-12 h-12 mx-auto mb-3 opacity-50" />
                <p>{t('noResourcesForSale')}</p>
              </div>
            ) : (
              <>
                {/* Resource selection */}
                <div data-testid="sell-resource-select-wrap">
                  <Label>{t('selectResourcePlaceholder')}</Label>
                  <Select value={sellResource} onValueChange={setSellResource}>
                    <SelectTrigger className="bg-white/5 border-white/10 h-14" data-testid="sell-resource-select-trigger">
                      <SelectValue placeholder={t('selectResourcePlaceholder')} />
                    </SelectTrigger>
                    <SelectContent>
                      {availableResources.map(r => (
                        <SelectItem key={r.id} value={r.id} data-testid={`sell-resource-option-${r.id}`}>
                          <div className="flex items-center gap-3 py-1">
                            <span className="text-xl">{r.icon}</span>
                            <div>
                              <div className="font-medium">{r.name}</div>
                              <div className="text-xs text-text-muted">{t('availableLabel')}: {formatAmount(r.amount)}</div>
                            </div>
                          </div>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                
                {sellResource && (
                  <>
                    {getResource(sellResource).tier === 1 && (
                      <div className="text-xs text-amber-400 bg-amber-500/10 rounded p-2" data-testid="sell-tier1-hint">
                        {t('tier1Hint')}
                      </div>
                    )}

                    <div className="grid grid-cols-2 gap-3">
                      <div data-testid="sell-amount-wrap">
                        <Label>{getResource(sellResource).tier === 1 ? t('amountMultiple10') : t('amountPerUnit')}</Label>
                        <Input
                          type="number"
                          min={getResource(sellResource).tier === 1 ? "10" : "1"}
                          step={getResource(sellResource).tier === 1 ? "10" : "1"}
                          max={(() => {
                            const have = Math.floor(myResources[sellResource] || 0);
                            // During tutorial create_lot we silently cap the
                            // amount at (warehouse - 1) so the user always
                            // keeps at least 1 unit on hand.
                            const baseCap = (tutorial?.active && tutorial?.currentStepId === 'create_lot')
                              ? Math.max(0, have - 1)
                              : have;
                            return Math.min(MAX_PRICE_VALUE, baseCap || MAX_PRICE_VALUE);
                          })()}
                          placeholder={getResource(sellResource).tier === 1 ? "10" : "1"}
                          value={sellAmount}
                          onChange={(e) => {
                            const raw = clampPriceValue(e.target.value);
                            // Tutorial: silently clamp to (warehouse - 1) without toast.
                            if (tutorial?.active && tutorial?.currentStepId === 'create_lot') {
                              const have = Math.floor(myResources[sellResource] || 0);
                              const cap = Math.max(0, have - 1);
                              if (raw === '' || raw === '-') { setSellAmount(raw); return; }
                              const n = parseInt(raw, 10);
                              if (!Number.isFinite(n)) { setSellAmount(raw); return; }
                              setSellAmount(String(Math.min(n, cap)));
                              return;
                            }
                            setSellAmount(raw);
                          }}
                          className="bg-white/5 border-white/10"
                          data-testid="sell-amount-input"
                        />
                      </div>
                      <div data-testid="sell-price-wrap">
                        <Label>{getResource(sellResource).tier === 1 ? t('pricePer10') : t('pricePer1')}</Label>
                        <Input
                          type="number"
                          step="1"
                          min="1"
                          max={MAX_PRICE_VALUE}
                          placeholder="10"
                          value={sellPrice}
                          readOnly={level0Info.is_level0_seller}
                          onChange={(e) => { if (!level0Info.is_level0_seller) setSellPrice(clampPriceValue(e.target.value)); }}
                          className={`bg-white/5 border-white/10 ${level0Info.is_level0_seller ? 'opacity-70 cursor-not-allowed' : ''}`}
                          data-testid="sell-price-input"
                        />
                        {level0Info.is_level0_seller && (
                          <p className="text-[11px] text-amber-300 mt-1" data-testid="sell-price-level0-note">
                            🔒 Бизнес 0-го уровня: цена фиксирована по рынку проекта и не изменяется.
                          </p>
                        )}
                      </div>
                    </div>
                    
                    {sellAmount && sellPrice && (
                      <div className="bg-white/5 rounded-lg p-3 space-y-2">
                        {(() => {
                          const tier = getResource(sellResource).tier || 1;
                          const baseTaxPct = tierTaxes[tier] || 15;
                          // Apply buffs: offshore_zone (trade_tax_reduction, additive pp) ×
                          // license_token (trade_fee_multiplier, on remaining tax).
                          const taxReductionPct = (activeBuffMults?.trade_tax_reduction ?? 0) * 100;
                          const tradeFeeMult = activeBuffMults?.trade_fee_multiplier ?? 1.0;
                          const reducedTaxPct = Math.max(0, baseTaxPct - taxReductionPct);
                          const effectiveTaxPct = reducedTaxPct * tradeFeeMult;
                          const taxBuffsApplied = (contributingBuffs?.trade_tax_reduction || []).concat(contributingBuffs?.trade_fee_multiplier || []);
                          const hasTaxBuff = Math.abs(effectiveTaxPct - baseTaxPct) > 0.0001;
                          const qty = tier === 1 ? parseInt(sellAmount) / 10 : parseInt(sellAmount);
                          const gross = qty * parseFloat(sellPrice);
                          const taxAmt = gross * effectiveTaxPct / 100;
                          const afterCityTax = gross - taxAmt;
                          // Tax Haven preview: if the business producing this resource has
                          // an active tax_haven contract, the patron takes a frozen share
                          // of the seller's *TON* income (after city tax). Show it explicitly.
                          const taxHavenContract = (contracts?.as_vassal || []).find(c =>
                            c.type === 'tax_haven' && c.status === 'active'
                          ) || null;
                          let taxHavenRate = 0;
                          let taxHavenPatron = null;
                          if (taxHavenContract) {
                            const biz = (myBusinessesList || []).find(b => b.id === taxHavenContract.vassal_business_id);
                            if (biz && biz.produces === sellResource) {
                              taxHavenRate = Number(taxHavenContract.tax_rate ?? 0.10);
                              taxHavenPatron = taxHavenContract.patron_username || '?';
                            }
                          }
                          // Tax haven applies in TON, but UI shows $CITY equivalent so the
                          // user sees a single coherent breakdown.
                          const patronCutCity = afterCityTax * taxHavenRate;
                          const afterPatron = afterCityTax - patronCutCity;
                          // Credit repayment preview: every active credit takes
                          // `salary_deduction_percent` from the seller's net
                          // (post-tax, post-patron) income.
                          const creditPct = totalCreditPct; // already includes doubled rate
                          const creditCutCity = afterPatron * creditPct;
                          const net = afterPatron - creditCutCity;
                          return (
                            <>
                              <div className="flex justify-between text-sm">
                                <span className="text-text-muted">Сумма листинга:</span>
                                <span className="text-white font-mono">{formatCity(gross)} $CITY</span>
                              </div>
                              <div className="flex justify-between text-sm">
                                <span className="text-text-muted">
                                  Налог (
                                  {hasTaxBuff ? (
                                    <>
                                      <span className="line-through text-text-muted/60 mr-1">{baseTaxPct}%</span>
                                      <span className="text-emerald-400 font-medium">{effectiveTaxPct.toFixed(2)}%</span>
                                    </>
                                  ) : (
                                    <span>{baseTaxPct}%</span>
                                  )}
                                  , Tier {tier}):
                                </span>
                                <span className="text-red-400 font-mono">−{formatCity(taxAmt)} $CITY</span>
                              </div>
                              {hasTaxBuff && taxBuffsApplied.length > 0 && (
                                <div className="flex flex-wrap gap-1 -mt-1">
                                  {taxBuffsApplied.map((b, i) => (
                                    <span key={`${b.id}-${i}`} className="text-[10px] px-2 py-0.5 rounded bg-cyber-cyan/10 text-cyber-cyan border border-cyber-cyan/20" data-testid={`sell-tax-buff-${b.id}`}>
                                      {b.icon} {b.name}
                                    </span>
                                  ))}
                                </div>
                              )}
                              {taxHavenRate > 0 && (
                                <div className="flex justify-between text-sm" data-testid="sell-tax-haven-row">
                                  <span className="text-amber-300">
                                    {t('contractCutLabel') || 'Контракт'} ({(taxHavenRate * 100).toFixed(0)}%):
                                  </span>
                                  <span className="text-amber-400 font-mono">−{formatCity(patronCutCity)} $CITY</span>
                                </div>
                              )}
                              {creditPct > 0 && (
                                <div className="flex justify-between text-sm" data-testid="sell-credit-row">
                                  <span className="text-rose-300">
                                    🏦 {t('creditRepaymentLabel') || 'Кредит'} ({(creditPct * 100).toFixed(1)}%):
                                  </span>
                                  <span className="text-rose-400 font-mono">−{formatCity(creditCutCity)} $CITY</span>
                                </div>
                              )}
                              <div className="border-t border-white/10 pt-2 flex justify-between">
                                <span className="text-text-muted font-medium">{t('netIncomeLabel') || 'Чистая прибыль'}:</span>
                                <span className="text-green-400 font-bold text-lg font-mono">~{formatCity(net)} $CITY</span>
                              </div>
                            </>
                          );
                        })()}
                      </div>
                    )}
                  </>
                )}
              </>
            )}
          </div>
          
          <DialogFooter className="flex-row gap-2 justify-end pt-2">
            <Button 
              onClick={handleSell}
              disabled={isSelling || !sellResource || !sellAmount || !sellPrice}
              className="bg-green-500 hover:bg-green-600 w-full"
              data-testid="sell-confirm-btn"
            >
              {isSelling ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <Check className="w-4 h-4 mr-2" />}
              {t('listBtn')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Buy Modal */}
      <Dialog open={showBuyModal} onOpenChange={setShowBuyModal}>
        <DialogContent
          className="bg-void border-cyber-cyan/30 !rounded-2xl"
          data-testid="buy-resource-modal"
          onPointerDownOutside={(e) => {
            // Lock modal open during tutorial buy_lot step — user must complete
            // the highlighted Всё → Купить flow.
            if (tutorial?.active && tutorial?.currentStepId === 'buy_lot') e.preventDefault();
          }}
          onEscapeKeyDown={(e) => {
            if (tutorial?.active && tutorial?.currentStepId === 'buy_lot') e.preventDefault();
          }}
        >
          <DialogHeader>
            <DialogTitle className="text-white flex items-center gap-2">
              <ShoppingCart className="w-5 h-5 text-cyber-cyan" />
              {t('buyResourceTitle')}
            </DialogTitle>
          </DialogHeader>
          
          {selectedListing && (
            <div className="space-y-4">
              {/* Resource info */}
              <div className={`p-4 rounded-lg ${getResource(selectedListing.resource_type).bgColor} border ${getResource(selectedListing.resource_type).borderColor}`}>
                <div className="flex items-center gap-3">
                  <span className="text-3xl">{getResource(selectedListing.resource_type).icon}</span>
                  <div>
                    <div className={`font-bold text-lg ${getResource(selectedListing.resource_type).textColor}`}>
                      {getResource(selectedListing.resource_type).name}
                    </div>
                    <div className="text-sm text-text-muted">{t('sellerLabel')}: {selectedListing.is_city_market ? `🏙 ${t('cityMarketName')}` : selectedListing.seller_username}</div>
                    {selectedListing.is_city_market && (
                      <div className="text-[11px] text-cyber-cyan/80">{t('cityMarketHint')}</div>
                    )}
                  </div>
                </div>
              </div>
              
              {(() => {
                // Compute weighted free warehouse space and the max units the buyer
                // can fit. Tier-1 capped at multiple of 10.
                const tier = getResource(selectedListing.resource_type).tier || 1;
                const weight = tier === 1 ? 1 : tier === 2 ? 5 : 20;
                const freeWeighted = Math.max(0, (warehouseInfo.capacity || 0) - (warehouseInfo.used || 0));
                let maxByWarehouse = weight > 0 ? Math.floor(freeWeighted / weight) : 0;
                if (tier === 1) maxByWarehouse = Math.floor(maxByWarehouse / 10) * 10;
                // v2.2.X: during the tutorial `buy_lot` step a new user has
                // no businesses yet, so `freeWeighted` is 0 and the "Всё"
                // button would clamp the amount to 0, breaking the flow.
                // The tutorial bot lot bypasses real warehousing on the
                // backend (`/api/tutorial/buy-lot`), so we let the user
                // buy the full lot here regardless of capacity.
                const isTutorialBuy = !!(tutorial?.active
                  && tutorial?.currentStepId === 'buy_lot'
                  && selectedListing?.tutorial);
                let maxBuyable = isTutorialBuy
                  ? selectedListing.amount
                  : Math.max(0, Math.min(selectedListing.amount, maxByWarehouse));
                const step = tier === 1 ? 10 : 1;
                const stepMin = tier === 1 ? 10 : 1;
                const cantFit = isTutorialBuy ? false : (maxByWarehouse < stepMin);
                return (
                  <>
                    <div className="grid grid-cols-2 gap-3">
                      <div className="bg-white/5 rounded-lg p-3">
                        <div className="text-xs text-text-muted">{t('pricePerUnitShort')} {displayPrice(selectedListing).label}</div>
                        <div className="font-bold text-cyber-cyan">{displayPrice(selectedListing).price} $CITY</div>
                      </div>
                      <div className="bg-white/5 rounded-lg p-3">
                        <div className="text-xs text-text-muted">{t('availableAmountLabel')}</div>
                        <div className="font-bold text-white">{formatAmount(selectedListing.amount)}</div>
                      </div>
                    </div>

                    <div className="bg-white/5 rounded-lg p-3 text-xs" data-testid="buy-warehouse-info">
                      <div className="flex justify-between text-text-muted">
                        <span>{t('freeInWarehouseLabel') || 'Free in warehouse'}:</span>
                        <span className="text-white font-mono">{freeWeighted} {t('slotsUnit') || 'slots'}</span>
                      </div>
                      <div className="flex justify-between mt-1">
                        <span className="text-text-muted">{t('maxBuyableLabel') || 'Max you can buy'}:</span>
                        <span className={cantFit ? 'text-red-400 font-mono' : 'text-emerald-400 font-mono'}>
                          {maxBuyable} {t('unitsShortEd') || 'units'}
                        </span>
                      </div>
                    </div>

                    <div>
                      <Label>{t('howManyToBuy')}</Label>
                      <div className="flex items-center gap-2 mt-1">
                        <Button size="icon" variant="outline" onClick={() => {
                          setBuyAmount(String(Math.max(step, parseInt(buyAmount || 0) - step)));
                        }}>
                          <Minus className="w-4 h-4" />
                        </Button>
                        <Input
                          type="number"
                          min={String(stepMin)}
                          max={maxBuyable}
                          step={String(step)}
                          value={buyAmount}
                          onChange={(e) => {
                            const v = parseInt(e.target.value || '0', 10);
                            if (Number.isNaN(v)) { setBuyAmount(e.target.value); return; }
                            setBuyAmount(String(Math.min(maxBuyable, v)));
                          }}
                          className="bg-white/5 border-white/10 text-center"
                        />
                        <Button size="icon" variant="outline" onClick={() => {
                          setBuyAmount(String(Math.min(maxBuyable, parseInt(buyAmount || 0) + step)));
                        }}>  <Plus className="w-4 h-4" />
                        </Button>
                        <Button variant="outline" onClick={() => setBuyAmount(String(maxBuyable))} data-testid="tutorial-buy-all-btn">
                          {t('allBtn')}
                        </Button>
                      </div>
                      {cantFit && (
                        <div className="mt-2 text-xs text-red-400">
                          На складе нет места для этого ресурса. Освободите место или прокачайте бизнес.
                        </div>
                      )}
                    </div>
                    
                    {buyAmount && (
                      <div className="bg-cyber-cyan/10 rounded-lg p-4 text-center border border-cyber-cyan/30">
                        <div className="text-sm text-text-muted">{t('totalToPay')}</div>
                        <div className="text-2xl font-bold text-cyber-cyan">
                          {formatCity(tonToCity(parseInt(buyAmount) * selectedListing.price_per_unit))} $CITY
                        </div>
                      </div>
                    )}
                  </>
                );
              })()}
            </div>
          )}
          
          <DialogFooter className="pt-2">
            <Button 
              onClick={handleBuy}
              disabled={
                isBuying
                || !buyAmount
                || parseInt(buyAmount || '0', 10) <= 0
                || (!userHasBusinesses && !(tutorial?.active
                      && tutorial?.currentStepId === 'buy_lot'
                      && selectedListing?.tutorial))
              }
              className="bg-cyber-cyan text-black w-full"
              data-testid="tutorial-buy-confirm-btn"
            >
              {isBuying ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <ShoppingCart className="w-4 h-4 mr-2" />}
              {t('buyBtn')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* All Alliance Offers Modal */}
      <Dialog open={showAllOffersModal} onOpenChange={setShowAllOffersModal}>
        <DialogContent className="bg-void border-amber-500/30 max-w-lg max-h-[85vh] !rounded-2xl">
          <DialogHeader>
            <DialogTitle className="text-white flex items-center gap-2">
              <Shield className="w-5 h-5 text-amber-400" />
              Все доступные офферы
            </DialogTitle>
            <DialogDescription className="text-text-muted">
              Выберите оффер от Патрона для вступления в альянс
            </DialogDescription>
          </DialogHeader>
          <ScrollArea className="max-h-[55vh] pr-2">
            <div className="space-y-3">
              {allianceOffers.filter(o => o.patron_username !== user?.username).map(offer => {
                const ct = OFFER_CONTRACT_TYPES[offer.contract_type] || {};
                const cancelFee = offer.cancel_fee_city ?? (offer.duration_days || 30) * 100;
                return (
                  <Card key={offer.id} className={`bg-void ${ct.border || 'border-white/10'} overflow-hidden`} data-testid={`modal-offer-${offer.id}`}>
                    <div className="h-1" style={{ background: `linear-gradient(90deg, ${ct.color || '#f59e0b'}, ${ct.color || '#f59e0b'}66)` }} />
                    <CardContent className="p-3">
                      <div className="flex items-start gap-3">
                        <div className="flex-1 min-w-0 space-y-1.5">
                          <div className="flex items-center gap-2">
                            <span className="text-lg">{offer.patron_business_icon}</span>
                            <span className="font-bold text-white text-sm truncate">
                              {offer.patron_business_name} <span className="text-text-muted font-normal">(Ур. {offer.patron_level || 1})</span>
                            </span>
                          </div>
                          <div className="flex items-center gap-1.5 text-xs">
                            <Crown className="w-3 h-3 text-purple-400 shrink-0" />
                            <span className="text-text-muted">Владелец:</span>
                            <span className="text-purple-300 font-medium truncate">{offer.patron_username}</span>
                          </div>
                          <div className="flex items-center gap-1.5 text-xs flex-wrap">
                            <Clock className="w-3 h-3 text-amber-400 shrink-0" />
                            <span className="text-text-muted">Срок:</span>
                            <span className="text-white font-medium">{offer.duration_days} дн.</span>
                            <span className="text-text-muted/60">·</span>
                            <span className="text-red-300 font-mono text-[11px]">{cancelFee.toLocaleString()} $CITY штраф</span>
                          </div>
                          <div className="p-1.5 rounded bg-red-500/10 border border-red-500/20">
                            <div className="text-[10px] text-red-400 font-medium mb-0.5">Вассал отдаёт</div>
                            <div className="text-xs text-white">{offer.vassal_pays || ct.vassal_note}</div>
                          </div>
                          <div className="p-1.5 rounded bg-green-500/10 border border-green-500/20">
                            <div className="text-[10px] text-green-400 font-medium mb-0.5">Вассал получает</div>
                            <div className="text-xs text-white flex items-center gap-1">{offer.buff_icon} {offer.buff_name}</div>
                            {offer.buff_description && <div className="text-[10px] text-text-muted line-clamp-1">{offer.buff_description}</div>}
                          </div>
                          <div className="text-[10px] text-text-muted">{ct.icon} {ct.name}</div>
                        </div>
                        <div className="flex flex-col gap-1.5 shrink-0">
                          <Button size="sm" variant="outline" className="border-cyan-500/40 text-cyan-400 hover:bg-cyan-500/10 h-7 text-xs"
                            onClick={async () => {
                              setCounterTarget(offer);
                              setCounterType(offer.contract_type || 'tax_haven');
                              setCounterDuration(offer.duration_days || 30);
                              setCounterBusinessId('');
                              setCounterBuffId('');
                              if (availableBuffs.length === 0) {
                                try {
                                  const r = await fetch(`${API}/tier3/buffs`, { headers: { Authorization: `Bearer ${token}` } });
                                  if (r.ok) { const d = await r.json(); setAvailableBuffs(d.buffs || []); }
                                } catch {}
                              }
                              setShowCounterModal(true);
                              setShowAllOffersModal(false);
                            }}>
                            <MessageSquare className="w-3 h-3 mr-1" /> Встречное
                          </Button>
                          <Button size="sm" variant="ghost" className="text-text-muted hover:text-white border border-white/10 h-7 text-xs"
                            onClick={() => handleHideOffer(offer.id)}>
                            <EyeOff className="w-3 h-3 mr-1" /> Скрыть
                          </Button>
                          <Button size="sm" className="bg-green-600 hover:bg-green-700 text-white h-7 text-xs"
                            data-testid={`modal-accept-${offer.id}`}
                            onClick={() => { handleAcceptOffer(offer); setShowAllOffersModal(false); }}>
                            <Check className="w-3 h-3 mr-1" /> Принять
                          </Button>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                );
              })}
              {allianceOffers.filter(o => o.patron_username !== user?.username).length === 0 && (
                <div className="text-center py-8 text-text-muted">
                  <Shield className="w-10 h-10 mx-auto mb-3 opacity-50" />
                  <p>Нет доступных офферов</p>
                </div>
              )}
            </div>
          </ScrollArea>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowAllOffersModal(false)} className="border-white/10">Закрыть</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Publish Alliance Offer Modal */}
      <Dialog open={showPublishOfferModal} onOpenChange={setShowPublishOfferModal}>
        <DialogContent className="bg-void border-purple-500/30 max-w-lg">
          <DialogHeader>
            <DialogTitle className="text-white flex items-center gap-2">
              <Crown className="w-5 h-5 text-purple-400" />
              {t('publishAllianceOfferTitle')}
            </DialogTitle>
            <DialogDescription className="text-text-muted">
              {t('asPatronYouPublish')}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            {/* Contract type — dropdown (что хочет получить покровитель) */}
            <div>
              <Label className="text-white mb-2 block text-sm">{t('whatYouWantInExchange')}</Label>
              <Select value={offerType} onValueChange={setOfferType}>
                <SelectTrigger
                  data-testid="offer-type-select"
                  className="w-full bg-white/5 border-white/10 text-white focus:ring-teal-500"
                >
                  <SelectValue placeholder="—" />
                </SelectTrigger>
                <SelectContent className="bg-void border-white/10 text-white">
                  {Object.entries(OFFER_CONTRACT_TYPES).map(([id, ct]) => (
                    <SelectItem
                      key={id}
                      value={id}
                      data-testid={`offer-type-option-${id}`}
                      className="focus:bg-white/10 cursor-pointer py-2"
                    >
                      <span className="inline-flex items-center gap-2">
                        <span className="text-base leading-tight">{ct.icon}</span>
                        <span className="text-sm font-medium text-white">{tContract(id, 'name', language) || ct.name}</span>
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {offerType && (() => {
                const ct = OFFER_CONTRACT_TYPES[offerType];
                if (!ct) return null;
                return (
                  <div className={`mt-2 p-2.5 rounded-lg border ${ct.border} ${ct.bg}`}>
                    <div className="text-xs text-text-muted">
                      {tContract(offerType, 'description', language) || ct.description}
                    </div>
                    <div className="mt-1 text-[11px] text-teal-300 font-medium">
                      {t('youReceiveLabel')}: {tContract(offerType, 'patron_note', language) || ct.patron_note}
                    </div>
                  </div>
                );
              })()}
            </div>

            {/* Buff — dropdown (какой баф будет давать вассалу) */}
            <div>
              <Label className="text-white mb-2 block text-sm">{t('vassalBuffLabelShort')}</Label>
              <Select value={offerBuff} onValueChange={setOfferBuff}>
                <SelectTrigger
                  data-testid="offer-buff-select"
                  className="w-full bg-white/5 border-white/10 text-white focus:ring-yellow-500"
                >
                  <SelectValue placeholder={t('loadingBuffs') || '…'} />
                </SelectTrigger>
                <SelectContent className="bg-void border-white/10 text-white max-h-72">
                  {availableBuffs.length === 0 ? (
                    <div className="px-3 py-4 text-xs text-text-muted text-center">{t('loadingBuffs') || '…'}</div>
                  ) : (
                    availableBuffs.map(buff => (
                      <SelectItem
                        key={buff.id}
                        value={buff.id}
                        data-testid={`offer-buff-option-${buff.id}`}
                        className="focus:bg-yellow-500/10 cursor-pointer py-2"
                      >
                        <span className="inline-flex items-center gap-2">
                          <span className="text-base leading-tight">{buff.icon}</span>
                          <span className="text-sm font-medium text-white">{tBuff(buff.id, 'name', language) || buff.name}</span>
                        </span>
                      </SelectItem>
                    ))
                  )}
                </SelectContent>
              </Select>
              {offerBuff && (() => {
                const b = availableBuffs.find(x => x.id === offerBuff);
                if (!b) return null;
                return (
                  <div className="mt-2 p-2.5 rounded-lg border border-yellow-500/30 bg-yellow-500/10">
                    <div className="text-xs text-text-muted">
                      {tBuff(b.id, 'description', language) || b.description}
                    </div>
                  </div>
                );
              })()}
            </div>

            {/* Duration */}
            <div>
              <Label className="text-white mb-2 block text-sm">{t('contractDurationDaysLabel')}</Label>
              <div className="flex gap-2">
                {[7, 14, 30, 60, 90].map(d => (
                  <button key={d} onClick={() => setOfferDuration(d)}
                    data-testid={`offer-duration-${d}`}
                    className={`flex-1 py-2 text-sm rounded-lg border transition-all ${
                      offerDuration === d ? 'border-purple-500 bg-purple-500/20 text-purple-300 font-bold' : 'border-white/10 bg-white/5 text-text-muted hover:border-white/20'
                    }`}>{d} {t('daysShort') || 'd'}</button>
                ))}
              </div>
            </div>
            {/* Summary */}
            {offerBuff && offerType && (
              <div className="p-3 rounded-lg bg-white/5 border border-white/10">
                <div className="text-xs font-medium text-white mb-2">{t('summaryLabel') || 'Summary'}:</div>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div className="text-text-muted">{t('typeLabel') || 'Type'}: <span className="text-white">{tContract(offerType, 'name', language) || OFFER_CONTRACT_TYPES[offerType]?.name}</span></div>
                  <div className="text-text-muted">{t('durationLabel') || 'Duration'}: <span className="text-white">{offerDuration} {t('daysShort') || 'd'}</span></div>
                  <div className="text-text-muted">{t('buffLabel') || 'Buff'}: <span className="text-yellow-400">
                    {availableBuffs.find(b => b.id === offerBuff)?.icon} {tBuff(offerBuff, 'name', language) || availableBuffs.find(b => b.id === offerBuff)?.name}
                  </span></div>
                  <div className="text-text-muted">{t('penaltyLabel') || 'Penalty'}: <span className="text-red-400 font-mono">{(offerDuration * 100).toLocaleString()} $CITY</span></div>
                </div>
              </div>
            )}
          </div>
          <DialogFooter className="gap-2">
            <Button onClick={handlePublishOffer} disabled={isPublishing || !offerBuff || !offerType}
              className="bg-purple-600 hover:bg-purple-700 w-full" data-testid="submit-offer-btn">
              {isPublishing ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <Crown className="w-4 h-4 mr-2" />}
              {t('publishAction')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Counter-Offer Modal — compact, dropdown-based, mirrors publish offer modal */}
      <Dialog open={showCounterModal} onOpenChange={setShowCounterModal}>
        <DialogContent className="bg-void border-cyan-500/30 w-[calc(100%-2rem)] max-w-md max-h-[90vh] overflow-y-auto !rounded-2xl">
          <DialogHeader>
            <DialogTitle className="text-white flex items-center gap-2">
              <MessageSquare className="w-5 h-5 text-cyan-400" />
              {t('counterOfferTitle') || 'Встречное предложение'}
            </DialogTitle>
            <DialogDescription className="text-text-muted text-xs sm:text-sm break-words">
              {counterTarget && `${t('patronLabel') || 'Патрон'}: ${counterTarget.patron_username} · ${counterTarget.patron_business_icon} ${counterTarget.patron_business_name}`}
            </DialogDescription>
          </DialogHeader>
          {counterTarget && (
            <div className="space-y-3">
              {/* Vassal business selector — dropdown, only when user has >1 business */}
              {Array.isArray(myBusinessesList) && myBusinessesList.length > 1 && (
                <div>
                  <Label className="text-white mb-1.5 block text-sm">
                    {t('counterPickBusinessLabel') || 'Ваш бизнес для контракта'}
                  </Label>
                  <Select value={counterBusinessId} onValueChange={setCounterBusinessId}>
                    <SelectTrigger className="bg-white/5 border-white/10 text-white h-10" data-testid="counter-biz-select">
                      <SelectValue placeholder={t('pickVassalBusiness') || 'Выберите бизнес'} />
                    </SelectTrigger>
                    <SelectContent>
                      {myBusinessesList.map(b => (
                        <SelectItem key={b.id} value={b.id} data-testid={`counter-biz-opt-${b.id}`}>
                          {b.icon || '🏢'} {b.business_name || b.name || b.business_type} · Lvl {b.level || 1}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}

              {/* Buff selector — dropdown */}
              <div>
                <Label className="text-white mb-1.5 block text-sm">
                  {t('counterPickBuffLabel') || 'Желаемый баф от Патрона'}
                </Label>
                <Select value={counterBuffId || '__keep__'} onValueChange={v => setCounterBuffId(v === '__keep__' ? '' : v)}>
                  <SelectTrigger className="bg-white/5 border-white/10 text-white h-10" data-testid="counter-buff-select">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__keep__" data-testid="counter-buff-opt-keep">
                      {counterTarget.buff_icon} {tBuff(counterTarget.buff_id, 'name', language) || counterTarget.buff_name} · {t('counterBuffKeep') || 'как у патрона'}
                    </SelectItem>
                    {(availableBuffs || []).filter(b => b.id !== counterTarget.buff_id).map(b => (
                      <SelectItem key={b.id} value={b.id} data-testid={`counter-buff-opt-${b.id}`}>
                        {b.icon} {tBuff(b.id, 'name', language) || b.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {counterBuffId && (
                  <div className="text-[10px] text-text-muted mt-1 line-clamp-2">
                    {tBuff(counterBuffId, 'description', language) || (availableBuffs || []).find(b => b.id === counterBuffId)?.description}
                  </div>
                )}
              </div>

              {/* Proposed payment type — dropdown */}
              <div>
                <Label className="text-white mb-1.5 block text-sm">{t('counterPayTypeLabel') || 'Предлагаемый тип оплаты'}</Label>
                <Select value={counterType} onValueChange={setCounterType}>
                  <SelectTrigger className="bg-white/5 border-white/10 text-white h-10" data-testid="counter-type-select">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {Object.entries(OFFER_CONTRACT_TYPES).map(([id, ct]) => (
                      <SelectItem key={id} value={id} data-testid={`counter-type-opt-${id}`}>
                        {ct.icon} {tContract(id, 'name', language) || ct.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {OFFER_CONTRACT_TYPES[counterType] && (
                  <div className="text-[10px] text-text-muted mt-1 line-clamp-2">
                    {tContract(counterType, 'description', language) || OFFER_CONTRACT_TYPES[counterType].description}
                  </div>
                )}
              </div>

              {/* Duration */}
              <div>
                <Label className="text-white mb-1.5 block text-sm">{t('counterDurationLabel') || 'Предлагаемый срок (дни)'}</Label>
                <div className="flex gap-1.5 flex-wrap">
                  {[7, 14, 30, 60, 90].map(d => (
                    <button key={d} onClick={() => setCounterDuration(d)}
                      data-testid={`counter-duration-${d}`}
                      className={`flex-1 min-w-[52px] py-2 text-sm rounded-lg border transition-all ${
                        counterDuration === d ? 'border-cyan-500 bg-cyan-500/20 text-cyan-300 font-bold' : 'border-white/10 bg-white/5 text-text-muted'
                      }`}>{d}</button>
                  ))}
                </div>
              </div>

              {/* Comment */}
              <div>
                <Label className="text-white mb-1.5 block text-sm">{t('counterCommentLabel') || 'Комментарий (опционально)'}</Label>
                <Input value={counterComment} onChange={e => setCounterComment(e.target.value)}
                  placeholder={t('counterCommentPh') || 'Почему эти условия лучше...'}
                  maxLength={200} className="bg-white/5 border-white/10" />
              </div>
            </div>
          )}
          <DialogFooter>
            <Button onClick={handleSubmitCounterOffer} disabled={isCountering}
              className="bg-cyan-600 hover:bg-cyan-700 w-full" data-testid="submit-counter-btn">
              {isCountering ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <MessageSquare className="w-4 h-4 mr-2" />}
              {t('counterSendBtn') || 'Отправить'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Break Alliance Confirm Modal */}
      <Dialog open={!!cancelConfirmContract} onOpenChange={(o) => { if (!o) setCancelConfirmContract(null); }}>
        <DialogContent className="bg-void border-red-500/30 w-[calc(100%-2rem)] max-w-md !rounded-2xl" data-testid="break-alliance-modal">
          <DialogHeader>
            <DialogTitle className="text-white flex items-center gap-2">
              <AlertCircle className="w-5 h-5 text-red-400" />
              {t('breakConfirmTitle')}
            </DialogTitle>
            <DialogDescription className="text-text-muted">
              {t('breakConfirmWarning')}
            </DialogDescription>
          </DialogHeader>
          {cancelConfirmContract && (() => {
            const fee = cancelConfirmContract.cancel_fee_city ?? (cancelConfirmContract.duration_days || 30) * 100;
            return (
              <div className="text-sm text-white py-2">
                {t('breakConfirmMsg').replace('{fee}', fee.toLocaleString())}
              </div>
            );
          })()}
          <DialogFooter className="gap-2">
            <Button
              onClick={() => {
                if (cancelConfirmContract) {
                  handleContractAction(cancelConfirmContract.id, 'cancel');
                  setCancelConfirmContract(null);
                }
              }}
              className="bg-red-600 hover:bg-red-700 text-white w-full"
              data-testid="break-confirm-btn"
            >
              <X className="w-4 h-4 mr-2" /> {t('confirmBtnLbl')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Pick Business Modal (when accepting offer with multiple businesses) */}
      <Dialog open={!!acceptOfferModal} onOpenChange={(o) => { if (!o) setAcceptOfferModal(null); }}>
        <DialogContent className="bg-void border-amber-500/30 w-[calc(100%-2rem)] max-w-md !rounded-2xl" data-testid="pick-business-modal">
          <DialogHeader>
            <DialogTitle className="text-white flex items-center gap-2">
              <Building2 className="w-5 h-5 text-amber-400" />
              {t('pickBusinessTitle')}
            </DialogTitle>
            <DialogDescription className="text-text-muted">
              {t('pickBusinessMsg')}
            </DialogDescription>
          </DialogHeader>
          {acceptOfferModal && (
            <div className="space-y-2 py-1">
              {acceptOfferModal.eligible.map(b => (
                <Button
                  key={b.id}
                  variant="outline"
                  className="w-full justify-start border-white/10 hover:bg-amber-500/10 text-white h-auto py-2.5"
                  onClick={() => handleAcceptOffer(acceptOfferModal.offer, b.id)}
                  data-testid={`pick-biz-${b.id}`}
                >
                  <span className="text-lg mr-2">{b.icon}</span>
                  <span className="flex-1 text-left">
                    <span className="block text-sm font-medium">{b.name}</span>
                    <span className="block text-[11px] text-text-muted">{t('levelShort')} {b.level} · Tier {b.tier}</span>
                  </span>
                </Button>
              ))}
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setAcceptOfferModal(null)} className="border-white/10">
              {t('cancelBtnLbl')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Patron-on-Accept Warning Modal removed — patronage system has been removed. */}
    </div>
  );
}
