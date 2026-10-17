import { formatErrorDetail } from '@/lib/apiErrors';
import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Store, MapPin, Building2, Plus, ShoppingCart, Trash2,
  Filter, SortAsc, RefreshCw, Package, Coins, ArrowUpRight,
  ArrowDownRight, Search, X, Check, AlertCircle
} from 'lucide-react';
import PageHeader from '@/components/PageHeader';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { toast } from 'sonner';
import Sidebar from '@/components/Sidebar';
import { useLanguage } from '@/context/LanguageContext';
import { RentalMarket } from '@/components/RentalDialogs';
import { useResourceName } from '@/hooks/useResourceName';
import { useTranslation } from '@/lib/translations';
import { tBusiness } from '@/lib/translationsExtra';

import { formatCity, tonToCity } from '@/lib/currency';
import { MAX_PRICE_VALUE, clampPriceValue } from '@/lib/priceLimits';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api`;

const RESOURCE_INFO = {
  energy:       { nameKey: 'resourceEnergy',       icon: '⚡', color: 'text-amber-400',  tier: 1 },
  scrap:        { nameKey: 'resourceScrap',         icon: '🔩', color: 'text-slate-300',  tier: 1 },
  quartz:       { nameKey: 'resourceQuartz',        icon: '💠', color: 'text-violet-400', tier: 1 },
  cu:           { nameKey: 'resourceCu',            icon: '🔢', color: 'text-blue-400',   tier: 1 },
  traffic:      { nameKey: 'resourceTraffic',       icon: '📶', color: 'text-cyan-400',   tier: 1 },
  cooling:      { nameKey: 'resourceCooling',       icon: '🧊', color: 'text-sky-400',    tier: 1 },
  biomass:      { nameKey: 'resourceBiomass',       icon: '🍏', color: 'text-green-400',  tier: 1 },
  chips:        { nameKey: 'resourceChips',         icon: '💾', color: 'text-orange-400', tier: 2 },
  neurocode:    { nameKey: 'resourceNeurocode',     icon: '🧠', color: 'text-purple-400', tier: 2 },
  nft:          { nameKey: 'resourceNft',           icon: '🖼️', color: 'text-pink-400',   tier: 2 },
  vr_experience:{ nameKey: 'resourceVrExperience',  icon: '🎬', color: 'text-fuchsia-400',tier: 2 },
  logistics:    { nameKey: 'resourceLogistics',     icon: '⛽', color: 'text-teal-400',   tier: 2 },
  profit_ton:   { nameKey: 'resourceProfitTon',     icon: '🍱', color: 'text-yellow-400', tier: 2 },
  repair_kits:  { nameKey: 'resourceRepairKits',    icon: '🧰', color: 'text-gray-400',   tier: 2 },
  neuro_core:   { nameKey: 'resourceNeuroCore',     icon: '🔮', color: 'text-purple-300', tier: 3 },
  gold_bill:    { nameKey: 'resourceGoldBill',      icon: '📜', color: 'text-amber-300',  tier: 3 },
  license_token:{ nameKey: 'resourceLicense',       icon: '🎫', color: 'text-sky-300',    tier: 3 },
  luck_chip:    { nameKey: 'resourceLuckChip',      icon: '🎲', color: 'text-pink-300',   tier: 3 },
  war_protocol: { nameKey: 'resourceWarProtocol',   icon: '⚔️', color: 'text-red-400',    tier: 3 },
  bio_module:   { nameKey: 'resourceBioModule',     icon: '🧬', color: 'text-green-300',  tier: 3 },
  gateway_code: { nameKey: 'resourceGatewayCode',   icon: '🔑', color: 'text-yellow-300', tier: 3 },
};

const BUSINESS_ICONS = {
  farm: '🌾',
  factory: '🏭',
  shop: '🏪',
  restaurant: '🍽️',
  bank: '🏦',
  power_plant: '⚡',
  quarry: '⛏️',
};

export default function MarketplacePage({ user, refreshBalance, updateBalance }) {
  const navigate = useNavigate();
  const { language } = useLanguage();
  const lang = language;
  const { t } = useTranslation(language);
  
  // Localized resource name — single source of truth across the whole app.
  const { name: getResName } = useResourceName();
  const [activeTab, setActiveTab] = useState('land');
  const [isLoading, setIsLoading] = useState(true);
  
  // Tax settings from admin
  const [taxSettings, setTaxSettings] = useState({ land_business_sale_tax: 10 });
  
  // Data
  const [resourceListings, setResourceListings] = useState([]);
  const [landListings, setLandListings] = useState([]);
  const [myResourceListings, setMyResourceListings] = useState([]);
  const [myLandListings, setMyLandListings] = useState([]);
  const [myPlots, setMyPlots] = useState([]);
  const [myBusinesses, setMyBusinesses] = useState([]);
  const [myContractsAsVassal, setMyContractsAsVassal] = useState([]);
  const [cities, setCities] = useState([]);
  
  // Filters
  const [resourceFilter, setResourceFilter] = useState('all');
  const [businessTypeFilter, setBusinessTypeFilter] = useState('all');
  const [priceMin, setPriceMin] = useState('');
  const [priceMax, setPriceMax] = useState('');
  const [sortBy, setSortBy] = useState('price');
  
  // Modals
  const [showSellResourceModal, setShowSellResourceModal] = useState(false);
  const [showSellLandModal, setShowSellLandModal] = useState(false);
  const [showBuyModal, setShowBuyModal] = useState(false);
  const [showBuyLandModal, setShowBuyLandModal] = useState(false);
  const [showFilterModal, setShowFilterModal] = useState(false);
  const [selectedListing, setSelectedListing] = useState(null);
  const [selectedLandListing, setSelectedLandListing] = useState(null);
  
  // Forms
  const [sellResourceForm, setSellResourceForm] = useState({
    business_id: '',
    resource_type: '',
    amount: 0,
    price_per_unit: 0
  });
  
  const [sellLandForm, setSellLandForm] = useState({
    plot_id: '',
    price: ''
  });

  // Min price (in $CITY) for the currently selected plot's business, if any.
  // Empty plots have no enforced min — value stays null and validation is skipped.
  const [sellLandMinPriceCity, setSellLandMinPriceCity] = useState(null);
  const [sellLandMinPriceTon, setSellLandMinPriceTon] = useState(null);
  
  const [buyAmount, setBuyAmount] = useState(0);

  // Active credits for the seller — used to surface a per-sale repayment
  // notice in the "list land/business" confirmation panel.
  const [activeCredits, setActiveCredits] = useState([]);

  const token = localStorage.getItem('token');

  const fetchData = async () => {
    setIsLoading(true);
    try {
      // Fetch all listings and tax settings
      const [resListings, landList, myRes, myLand, citiesData, taxData] = await Promise.all([
        fetch(`${API}/market/listings`).then(r => r.json()),
        fetch(`${API}/market/land/listings`).then(r => r.json()),
        token ? fetch(`${API}/market/my-listings`, { headers: { Authorization: `Bearer ${token}` } }).then(r => r.json()) : { listings: [] },
        token ? fetch(`${API}/market/land/my-listings`, { headers: { Authorization: `Bearer ${token}` } }).then(r => r.json()) : { listings: [] },
        fetch(`${API}/cities`).then(r => r.json()),
        fetch(`${API}/public/tax-settings`).then(r => r.json()).catch(() => ({ land_business_sale_tax: 10 }))
      ]);
      
      setResourceListings(resListings.listings || []);
      setLandListings(landList.listings || []);
      setMyResourceListings(myRes.listings || []);
      setMyLandListings(myLand.listings || []);
      setCities(citiesData.cities || []);
      setTaxSettings(taxData);
      
      // Fetch user's plots and businesses for selling
      if (token && user) {
        const plotsRes = await fetch(`${API}/users/me/plots`, { headers: { Authorization: `Bearer ${token}` } }).then(r => r.json()).catch(() => ({ plots: [] }));
        const bizRes = await fetch(`${API}/users/me/businesses`, { headers: { Authorization: `Bearer ${token}` } }).then(r => r.json()).catch(() => ({ businesses: [] }));
        const contractsRes = await fetch(`${API}/contracts/my`, { headers: { Authorization: `Bearer ${token}` } }).then(r => r.json()).catch(() => ({ as_vassal: [] }));
        const loansRes = await fetch(`${API}/credit/my-loans`, { headers: { Authorization: `Bearer ${token}` } }).then(r => r.json()).catch(() => ({ loans: [] }));
        setMyPlots(plotsRes.plots || []);
        setMyBusinesses(bizRes.businesses || []);
        setMyContractsAsVassal(contractsRes.as_vassal || []);
        setActiveCredits((loansRes.loans || []).filter(l =>
          ['active', 'overdue'].includes(l.status) && (l.remaining || 0) > 0
        ));
      }
    } catch (error) {
      console.error('Failed to fetch marketplace data:', error);
    } finally {
      setIsLoading(false);
    }
  };

  // Light-weight auto-refresh of listings every 5 seconds so newly published
  // resource & land offers appear without the user navigating away and back.
  // Only the public listing endpoints are polled — we deliberately skip
  // the heavier "my plots/businesses/contracts" payloads here, those don't
  // need to be polled at 5-second cadence. setIsLoading is NOT toggled so
  // the spinner doesn't flicker during the refresh.
  const refreshListingsSilent = async () => {
    try {
      const [resListings, landList] = await Promise.all([
        fetch(`${API}/market/listings`).then(r => r.json()),
        fetch(`${API}/market/land/listings`).then(r => r.json()),
      ]);
      setResourceListings(resListings.listings || []);
      setLandListings(landList.listings || []);
      if (token) {
        const [myRes, myLand] = await Promise.all([
          fetch(`${API}/market/my-listings`, { headers: { Authorization: `Bearer ${token}` } }).then(r => r.json()).catch(() => ({ listings: myResourceListings })),
          fetch(`${API}/market/land/my-listings`, { headers: { Authorization: `Bearer ${token}` } }).then(r => r.json()).catch(() => ({ listings: myLandListings })),
        ]);
        setMyResourceListings(myRes.listings || []);
        setMyLandListings(myLand.listings || []);
      }
    } catch (_) { /* silent — initial fetchData will show the error if there's one */ }
  };

  useEffect(() => {
    fetchData();
  }, [user]);

  useEffect(() => {
    if (!user) return undefined;
    const id = setInterval(() => { refreshListingsSilent(); }, 5000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, token]);

  // Доступно к оплате: бонусный + реальный баланс. Выкуп бизнеса 0 уровня — только с реального.
  const spendableTon = selectedLandListing?.is_zero_business
    ? Number(user?.balance_ton || 0)
    : Number(user?.balance_ton || 0) + Number(user?.bonus_balance || 0);

  const handleBuyResource = async () => {
    if (!selectedListing || buyAmount <= 0) return;
    
    try {
      const res = await fetch(`${API}/market/buy`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({
          listing_id: selectedListing.id,
          amount: buyAmount
        })
      });
      
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        const d = err.detail;
        if (d === 'ZERO_BUSINESS_LOCKED') throw new Error(t('zeroBusinessLocked'));
        // Race lost (item just sold / not enough stock at the moment) — inform
        // the user and refresh the list. Backend may return 409 (atomic claim)
        // or 404 (pre-check), so handle both.
        if (res.status === 409 || res.status === 404 ||
            d === 'LISTING_SOLD' || d === 'RESOURCE_UNAVAILABLE') {
          const isRes = d === 'RESOURCE_UNAVAILABLE' ||
            (typeof d === 'string' && d.toLowerCase().includes('resource'));
          toast.error(isRes ? t('resourceUnavailableRefresh') : t('listingSoldRefresh'));
          setShowBuyModal(false);
          setShowBuyLandModal(false);
          fetchData();
          return;
        }
        throw new Error(formatErrorDetail(d) || 'Purchase failed');
      }
      
      const data = await res.json();
      toast.success(t('boughtResourcesMsg').replace('{amount}', buyAmount).replace('{name}', getResName(selectedListing.resource_type)).replace('{total}', data.total_paid.toFixed(2)));
      setShowBuyModal(false);
      setSelectedListing(null);
      setBuyAmount(0);
      
      // Update balance immediately (real + bonus)
      if (data.new_balance !== undefined) {
        updateBalance?.(data.new_balance, data.new_bonus_balance);
      } else {
        refreshBalance?.();
      }
      
      fetchData();
    } catch (error) {
      toast.error(formatErrorDetail(error.message));
    }
  };

  const MAX_PLOTS_PER_USER = 3;
  const MAX_BUSINESSES_PER_USER = 3;
  const MAX_TIER3_PER_USER = 1;

  // Privileges: only admins bypass business / tier-3 limits
  const isAdmin = !!user?.is_admin;
  // ALL of user's businesses (active + on_sale) — listed-for-sale still counts toward limit
  const allMyBusinesses = (myBusinesses || []);
  const ownedBusinessesCount = allMyBusinesses.length;
  const ownedTier3Count = allMyBusinesses.filter(b => (b.tier || 1) >= 3).length;

  /**
   * Determines visibility/state of the buy button for a single land/business listing.
   * Returns { hidden: bool, disabled: bool, label: string }.
   * Per spec: when the user cannot buy (own listing / business limit / tier-3 limit),
   * the button should be HIDDEN entirely (not shown disabled), except for "your listing".
   */
  const getListingBuyBlock = (listing) => {
    if (!user) return { hidden: true, disabled: true, label: '' };
    const sellerId = listing.seller_id || listing.seller_user_id;
    if (sellerId === user.id || sellerId === user.wallet_address) {
      return { hidden: false, disabled: true, label: t('yourListingLabel') };
    }
    if (isAdmin) {
      return { hidden: false, disabled: false, label: t('buyPlotBtnMarket') };
    }
    const biz = listing.business;
    if (biz) {
      if (ownedBusinessesCount >= MAX_BUSINESSES_PER_USER) {
        return { hidden: true, disabled: true, label: '' };
      }
      const tier = biz.tier || 1;
      if (tier >= 3 && ownedTier3Count >= MAX_TIER3_PER_USER) {
        return { hidden: true, disabled: true, label: '' };
      }
    } else {
      // Empty plot — limited by plot count
      const ownedPlotsCount = myPlots.filter(p => !p.on_sale).length;
      if (ownedPlotsCount >= MAX_PLOTS_PER_USER) {
        return { hidden: true, disabled: true, label: '' };
      }
    }
    return { hidden: false, disabled: false, label: t('buyPlotBtnMarket') };
  };
  
  const openBuyLandModal = (listing) => {
    const block = getListingBuyBlock(listing);
    if (block.hidden || block.disabled) {
      if (block.label === t('yourListingLabel')) {
        toast.error(t('cantBuyOwn'));
      }
      return;
    }
    setSelectedLandListing(listing);
    setShowBuyLandModal(true);
  };

  const handleBuyLand = async () => {
    if (!selectedLandListing) return;
    
    const listing = selectedLandListing;
    
    try {
      const res = await fetch(`${API}/market/land/buy`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({ listing_id: listing.id })
      });
      
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        const d = err.detail;
        if (d === 'ZERO_BUSINESS_LOCKED') throw new Error(t('zeroBusinessLocked'));
        // Race lost (item just sold / not enough stock at the moment) — inform
        // the user and refresh the list. Backend may return 409 (atomic claim)
        // or 404 (pre-check), so handle both.
        if (res.status === 409 || res.status === 404 ||
            d === 'LISTING_SOLD' || d === 'RESOURCE_UNAVAILABLE') {
          const isRes = d === 'RESOURCE_UNAVAILABLE' ||
            (typeof d === 'string' && d.toLowerCase().includes('resource'));
          toast.error(isRes ? t('resourceUnavailableRefresh') : t('listingSoldRefresh'));
          setShowBuyModal(false);
          setShowBuyLandModal(false);
          fetchData();
          return;
        }
        throw new Error(formatErrorDetail(d) || 'Purchase failed');
      }
      
      const data = await res.json();
      toast.success(`${t('plotBoughtMsg').replace('{total}', data.total_paid)} ${data.has_business ? t('withBusinessLabel') : ''}`);
      setShowBuyLandModal(false);
      setSelectedLandListing(null);
      
      // Update balance immediately (real + bonus)
      if (data.new_balance !== undefined) {
        updateBalance?.(data.new_balance, data.new_bonus_balance);
      } else {
        refreshBalance?.();
      }
      
      fetchData();
    } catch (error) {
      toast.error(formatErrorDetail(error.message));
    }
  };

  const handleSellResource = async () => {
    if (!sellResourceForm.business_id || sellResourceForm.amount <= 0 || sellResourceForm.price_per_unit <= 0) {
      toast.error(t('fillAllFieldsCredit'));
      return;
    }
    
    try {
      const res = await fetch(`${API}/market/list`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({
          ...sellResourceForm,
          price_per_unit: sellResourceForm.price_per_unit / 1000  // Convert $CITY to TON for backend
        })
      });
      
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Listing failed');
      }
      
      toast.success(t('resourcesListedMsg'));
      setShowSellResourceModal(false);
      setSellResourceForm({ business_id: '', resource_type: '', amount: 0, price_per_unit: 0 });
      fetchData();
    } catch (error) {
      toast.error(error.message);
    }
  };

  const handleSellLand = async () => {
    if (!sellLandForm.plot_id || sellLandForm.price <= 0) {
      toast.error(t('selectPlotAndPrice'));
      return;
    }
    
    try {
      const selectedPlot = myPlots.find(p => p.id === sellLandForm.plot_id);
      const businessId = selectedPlot?.business_id;
      
      let res;
      if (businessId) {
        // Plot has a business - use business sell endpoint (marks both business and plot as on_sale)
        res = await fetch(`${API}/business/${businessId}/sell`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`
          },
          body: JSON.stringify({
            price: sellLandForm.price / 1000  // Convert $CITY to TON for backend
          })
        });
      } else {
        // Empty plot - use land listing endpoint
        res = await fetch(`${API}/market/land/list`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`
          },
          body: JSON.stringify({
            plot_id: sellLandForm.plot_id,
            price: sellLandForm.price / 1000  // Convert $CITY to TON for backend
          })
        });
      }
      
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Listing failed');
      }
      
      toast.success(t('plotListedMsg'));
      setShowSellLandModal(false);
      setSellLandForm({ plot_id: '', price: 0 });
      setSellLandMinPriceCity(null);
      setSellLandMinPriceTon(null);
      fetchData();
    } catch (error) {
      toast.error(error.message);
    }
  };

  const handleCancelListing = async (type, listingId) => {
    const endpoint = type === 'resource' ? `/market/listing/${listingId}` : `/market/land/listing/${listingId}`;
    
    try {
      const res = await fetch(`${API}${endpoint}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` }
      });
      
      if (!res.ok) {
        let detail = '';
        try { detail = (await res.json()).detail; } catch (_) { /* ignore */ }
        if (detail === 'SEIZED_CONTACT_SUPPORT') {
          throw new Error(t('seizedContactSupport') || 'To delist a business, please contact support.');
        }
        throw new Error(detail || 'Failed to cancel');
      }
      
      toast.success(t('listingCanceledMsg'));
      refreshBalance?.();
      fetchData();
    } catch (error) {
      toast.error(error.message);
    }
  };

  const filteredResourceListings = resourceListings.filter(l => 
    resourceFilter === 'all' || l.resource_type === resourceFilter
  );

  const filteredLandListings = landListings.filter(l => {
    // Don't show user's own listings in main list (check both seller_id and seller_user_id)
    const sellerId = l.seller_id || l.seller_user_id;
    if (user && (sellerId === user.id || sellerId === user.wallet_address)) return false;
    // Filter by business type
    if (businessTypeFilter !== 'all') {
      if (!l.business || l.business.type !== businessTypeFilter) return false;
    }
    // Filter by price range
    if (priceMin && l.price < parseFloat(priceMin)) return false;
    if (priceMax && l.price > parseFloat(priceMax)) return false;
    return true;
  }).sort((a, b) => {
    if (sortBy === 'price') return a.price - b.price;
    if (sortBy === 'price_desc') return b.price - a.price;
    return 0;
  });

  return (
    <div className="flex h-screen bg-void">
      <Sidebar user={user} />
      
      <div className="flex-1 overflow-hidden lg:ml-16">
        <ScrollArea className="h-full">
          <div className="p-4 lg:px-6 lg:pt-2 lg:pb-6 pt-0 space-y-4 lg:space-y-6">
            {/* Header - Mobile Optimized */}
            <PageHeader 
              icon={<Store className="w-6 h-6 lg:w-8 lg:h-8 text-cyber-cyan" />}
              title={t('marketplaceHeader')}
              actionButtons={
                <Button 
                  onClick={fetchData} 
                  variant="outline" 
                  size="icon"
                  className="border-white/10 h-8 w-8 sm:h-10 sm:w-10"
                  disabled={isLoading}
                >
                  <RefreshCw className={`w-3.5 h-3.5 sm:w-4 sm:h-4 ${isLoading ? 'animate-spin' : ''}`} />
                </Button>
              }
              closeButton={<Button variant="outline" size="icon" className="border-white/10 h-8 w-8 sm:h-10 sm:w-10" title={t('page_close')} aria-label={t('page_close')}
                  data-testid="page-close-btn" onClick={() => (window.history.length > 1 ? navigate(-1) : navigate('/my-businesses'))}>
                  <X className="w-4 h-4" />
                </Button>}
            />

            {/* Stats — 2 cards in a row (businesses on sale + TON balance). $CITY of lands removed per user request. */}
            <div className="grid grid-cols-2 gap-2 lg:gap-4">
              <Card className="glass-panel border-white/10">
                <CardContent className="p-2 lg:p-4 flex items-center gap-1.5 lg:gap-3">
                  <Building2 className="w-5 h-5 lg:w-8 lg:h-8 text-cyber-cyan flex-shrink-0" />
                  <div className="min-w-0">
                    <div className="text-base lg:text-2xl font-bold text-white truncate">{landListings.filter(l => l.business).length}</div>
                    <div className="text-[9px] lg:text-xs text-text-muted truncate">{t('businessesOnSale') || 'Бизнесы на продаже'}</div>
                  </div>
                </CardContent>
              </Card>
              <Card className="glass-panel border-white/10">
                <CardContent className="p-2 lg:p-4 flex items-center gap-1.5 lg:gap-3">
                  <Coins className="w-5 h-5 lg:w-8 lg:h-8 text-yellow-400 flex-shrink-0" />
                  <div className="min-w-0">
                    <div className="text-base lg:text-2xl font-bold text-white truncate">{formatCity(tonToCity(user?.balance_ton || 0))}</div>
                    <div className="text-[9px] lg:text-xs text-text-muted truncate">{t('tonBalance')}</div>
                  </div>
                </CardContent>
              </Card>
            </div>

            {/* Tabs + filter icon — icon sits on the same horizontal level as the
                tabs but is OUTSIDE the TabsList block (separate sibling). */}
            <Tabs value={activeTab} onValueChange={setActiveTab}>
              <div className="flex items-center gap-2 w-full min-w-0">
                {/* one row that always fits the screen: Бизнесы · Мои листинги · Аренда */}
                <TabsList className="bg-white/5 border border-white/10 flex-1 min-w-0 grid grid-cols-3 h-auto p-1" data-testid="marketplace-tabs">
                  <TabsTrigger value="land" className="min-w-0 px-1.5 py-1.5 text-[11px] sm:text-sm data-[state=active]:bg-amber-500 data-[state=active]:text-black" data-testid="marketplace-businesses-tab">
                    <MapPin className="hidden sm:inline w-4 h-4 mr-1.5 shrink-0" />
                    <span className="truncate">{t('mp_tab_businesses')}</span>
                  </TabsTrigger>
                  <TabsTrigger value="my-listings" className="min-w-0 px-1.5 py-1.5 text-[11px] sm:text-sm data-[state=active]:bg-green-500 data-[state=active]:text-black">
                    <Store className="hidden sm:inline w-4 h-4 mr-1.5 shrink-0" />
                    <span className="truncate">{t('myListingsTab')}</span>
                  </TabsTrigger>
                  <TabsTrigger value="rent" className="min-w-0 px-1.5 py-1.5 text-[11px] sm:text-sm data-[state=active]:bg-cyan-500 data-[state=active]:text-black" data-testid="marketplace-rent-tab">
                    <span className="truncate">{t('rt_tab')}</span>
                  </TabsTrigger>
                </TabsList>
                {activeTab === 'land' && (
                  <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    onClick={() => setShowFilterModal(true)}
                    data-testid="marketplace-filter-btn"
                    aria-label={t('filterLabel') || 'Фильтры'}
                    title={t('filterLabel') || 'Фильтры'}
                    className="h-9 w-9 border-white/10 bg-white/5 text-white hover:bg-white/10 relative"
                  >
                    <Filter className="w-4 h-4" />
                    {(businessTypeFilter !== 'all' || sortBy !== 'price') && (
                      <span
                        className="absolute -top-1 -right-1 w-2.5 h-2.5 rounded-full bg-cyber-cyan border border-[#0a0a14]"
                        aria-hidden
                      />
                    )}
                  </Button>
                )}
              </div>

              {/* Land Tab */}
              <TabsContent value="land" className="mt-4">
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {filteredLandListings.length === 0 ? (
                    <div className="col-span-full text-center py-12 text-text-muted">
                      <MapPin className="w-12 h-12 mx-auto mb-4 opacity-50" />
                      <p>{t('noPlotsSale')}</p>
                    </div>
                  ) : (
                    filteredLandListings.map(listing => {
                      // Handle localized city_name - default to GRAM Island
                      let cityName = 'GRAM Island';
                      if (listing.city_name) {
                        if (typeof listing.city_name === 'object') {
                          cityName = listing.city_name?.ru || listing.city_name?.en || 'GRAM Island';
                        } else if (listing.city_name !== 'Unknown') {
                          cityName = listing.city_name;
                        }
                      }
                      const buyBlock = getListingBuyBlock(listing);
                      
                      return (
                        <Card key={listing.id} className="glass-panel border-white/10 hover:border-amber-500/50 transition-all">
                          <CardContent className="p-4">
                            {/* Title + price in a single line */}
                            <div className="flex justify-between items-baseline gap-2 mb-1">
                              <div className="font-bold text-white flex items-center gap-2 min-w-0">
                                <MapPin className="w-4 h-4 text-amber-400 shrink-0" />
                                <span className="truncate">Участок [{listing.x}, {listing.y}]</span>
                              </div>
                              <div className="text-xl font-bold text-amber-300 whitespace-nowrap">
                                {formatCity(tonToCity(listing.price || 0))} <span className="text-xs text-text-muted font-normal">$CITY</span>
                              </div>
                            </div>
                            <div className="text-xs text-amber-400 mb-1">{cityName}</div>
                            
                            {/* Seller close to header */}
                            <div className="text-xs flex items-center gap-1 mb-3">
                              <span className="text-text-muted">Продавец:</span>
                              <span className="text-white">{listing.seller_username || t('unknown')}</span>
                            </div>
                            
                            {listing.business && (
                              <div className="mb-3 p-3 bg-purple-500/10 border border-purple-500/20 rounded-lg space-y-2">
                                <div className="flex items-center gap-2 flex-wrap">
                                  <span className="font-bold text-purple-300 text-sm">
                                    {tBusiness(listing.business.type, lang)
                                      || (typeof listing.business.name === 'object'
                                        ? (listing.business.name?.[lang] || listing.business.name?.en || listing.business.name?.ru || listing.business.type)
                                        : (listing.business.name || listing.business.type))}
                                  </span>
                                  <span className="text-xs text-text-muted">Lv.{listing.business.level || 1}</span>
                                  {listing.business.tier && (
                                    <span className="text-xs px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-300">Tier {listing.business.tier}</span>
                                  )}
                                </div>
                                {/* Production / Consumption stacked vertically */}
                                <div className="space-y-1.5 text-xs">
                                  {listing.business.produces && (
                                    <div className="flex items-start gap-1.5">
                                      <span className="text-green-400 mt-0.5">▲</span>
                                      <div>
                                        <span className="text-text-muted">Произв.: </span>
                                        <span className="text-green-300 font-mono">
                                          {listing.business.production_per_day || '?'} {getResName(listing.business.produces) || listing.business.produces}/сут.
                                        </span>
                                      </div>
                                    </div>
                                  )}
                                  {listing.business.consumes && Object.keys(listing.business.consumes).length > 0 && (
                                    <div className="flex items-start gap-1.5">
                                      <span className="text-red-400 mt-0.5">▼</span>
                                      <div>
                                        <span className="text-text-muted">Потр.: </span>
                                        <span className="text-red-300 font-mono">
                                          {Object.entries(listing.business.consumes).map(([res, amt], idx, arr) => (
                                            <span key={res}>
                                              {Math.round(amt)} {getResName(res) || res}/сут.
                                              {idx < arr.length - 1 ? ', ' : ''}
                                            </span>
                                          ))}
                                        </span>
                                      </div>
                                    </div>
                                  )}
                                </div>
                              </div>
                            )}
                            
                            {!buyBlock.hidden && (
                              <Button 
                                onClick={() => openBuyLandModal(listing)}
                                className="w-full bg-amber-500 text-black hover:brightness-110"
                                disabled={buyBlock.disabled}
                                data-testid={`marketplace-buy-listing-${listing.id}`}
                              >
                                <ShoppingCart className="w-4 h-4 mr-2" />
                                {buyBlock.label}
                              </Button>
                            )}
                          </CardContent>
                        </Card>
                      );
                    })
                  )}
                </div>
              </TabsContent>

              {/* My Listings Tab */}
              <TabsContent value="rent" className="mt-4">
                <RentalMarket lang={lang} user={user} />
              </TabsContent>

              <TabsContent value="my-listings" className="mt-4">
                <div className="space-y-6">
                  {/* My Land Listings */}
                  <div>
                    <h3 className="font-bold text-white mb-4 flex items-center gap-2">
                      <MapPin className="w-5 h-5 text-amber-400" />
                      {t('myListings')}
                    </h3>
                    {(() => {
                      const activeListings = [...myLandListings, ...landListings.filter(l => {
                        const sellerId = l.seller_id || l.seller_user_id;
                        return (sellerId === user?.id || sellerId === user?.wallet_address) && !myLandListings.find(m => m.id === l.id);
                      })].filter(l => l.status === 'active');

                      const sellButton = (
                        <Button
                          onClick={() => setShowSellLandModal(true)}
                          className="bg-amber-500 hover:bg-amber-600 text-black"
                          disabled={myPlots.filter(p => !p.on_sale).length === 0}
                          data-testid="marketplace-sell-plot-btn"
                        >
                          <Plus className="w-4 h-4 mr-2" />
                          {t('sellPlot')}
                        </Button>
                      );

                      if (activeListings.length === 0) {
                        return (
                          <div className="flex flex-col items-center justify-center py-12 text-text-muted gap-4">
                            <MapPin className="w-8 h-8 opacity-50" />
                            <p className="text-sm">{t('noListings')}</p>
                            {sellButton}
                          </div>
                        );
                      }

                      return (
                        <>
                          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                            {activeListings.map(listing => {
                          const cityName = typeof listing.city_name === 'object' 
                            ? (listing.city_name?.ru || listing.city_name?.en || 'GRAM Island') 
                            : (listing.city_name || 'GRAM Island');
                          return (
                          <Card key={listing.id} className="glass-panel border-white/10 hover:border-amber-500/30 transition-all">
                            <CardContent className="p-4">
                              <div className="flex items-center justify-between mb-3">
                                <div>
                                  <div className="text-white font-medium flex items-center gap-2">
                                    <MapPin className="w-4 h-4 text-amber-400" />
                                    [{listing.x}, {listing.y}]
                                  </div>
                                  <div className="text-xs text-amber-400">{cityName}</div>
                                </div>
                                <Badge className="bg-green-500/20 text-green-400">{t('onSaleBadge')}</Badge>
                              </div>
                              <div className="mb-3">
                                {(() => {
                                  const taxPct = taxSettings.land_business_sale_tax || 20;
                                  const gross = tonToCity(listing.price || 0);
                                  const net = gross * (1 - taxPct / 100);
                                  return (
                                    <>
                                      <div className="text-xs text-text-muted line-through">{formatCity(gross)} $CITY</div>
                                      <div className="text-lg font-bold text-green-400">{formatCity(net)} $CITY</div>
                                      <div className="text-xs text-amber-500">−{taxPct}% {t('taxLabelShort')}</div>
                                    </>
                                  );
                                })()}
                              </div>
                              {listing.business && (
                                <div className="text-xs text-purple-400 mb-3 p-2 bg-purple-500/10 rounded-lg">
                                  🏢 {listing.business.icon} {
                                    tBusiness(listing.business.type, lang)
                                      || (typeof listing.business.name === 'object' 
                                        ? (listing.business.name?.[lang] || listing.business.name?.en || listing.business.name?.ru || listing.business.type)
                                        : (listing.business.name || listing.business.type))
                                  } ({t('levelLabel')} {listing.business.level || 1})
                                </div>
                              )}
                              <Button 
                                size="sm" 
                                variant="destructive"
                                className="w-full"
                                onClick={() => handleCancelListing('land', listing.id)}
                              >
                                <Trash2 className="w-4 h-4 mr-2" />
                                {t('cancelSaleAction')}
                              </Button>
                            </CardContent>
                          </Card>
                          );
                        })}
                          </div>
                          <div className="flex justify-center mt-6">
                            {sellButton}
                          </div>
                        </>
                      );
                    })()}
                  </div>
                </div>
              </TabsContent>
            </Tabs>
          </div>
        </ScrollArea>
      </div>

      {/* Buy Resource Modal */}
      <Dialog open={showBuyModal} onOpenChange={setShowBuyModal}>
        <DialogContent className="bg-void border-white/10 !rounded-2xl">
          <DialogHeader>
            <DialogTitle className="text-white flex items-center gap-2">
              <ShoppingCart className="w-5 h-5 text-cyber-cyan" />
              Купить ресурсы
            </DialogTitle>
          </DialogHeader>
          
          {selectedListing && (
            <div className="space-y-4">
              <div className="p-4 bg-white/5 rounded-xl">
                <div className="flex items-center gap-3 mb-3">
                  <span className="text-3xl">{RESOURCE_INFO[selectedListing.resource_type]?.icon}</span>
                  <div>
                    <div className="text-white font-bold">{getResName(selectedListing.resource_type)}</div>
                    <div className="text-sm text-text-muted">от {selectedListing.seller_username}</div>
                  </div>
                </div>
                <div className="text-sm text-text-muted">
                  Доступно: {selectedListing.amount} шт по {formatCity(tonToCity(selectedListing.price_per_unit))} $CITY
                </div>
              </div>
              
              <div>
                <Label className="text-white">Количество</Label>
                <Input 
                  type="number"
                  value={buyAmount}
                  onChange={(e) => setBuyAmount(Math.min(parseFloat(e.target.value) || 0, selectedListing.amount, MAX_PRICE_VALUE))}
                  max={Math.min(MAX_PRICE_VALUE, selectedListing.amount)}
                  className="bg-white/5 border-white/10 text-white"
                />
              </div>
              
              <div className="p-3 bg-cyber-cyan/10 border border-cyber-cyan/20 rounded-lg">
                <div className="flex justify-between text-sm">
                  <span className="text-text-muted">Итого к оплате:</span>
                  <span className="text-cyber-cyan font-bold font-mono">
                    {formatCity(tonToCity(buyAmount * selectedListing.price_per_unit))} $CITY
                  </span>
                </div>
              </div>
            </div>
          )}
          
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowBuyModal(false)} className="border-white/10">
              Отмена
            </Button>
            <Button onClick={handleBuyResource} className="bg-cyber-cyan text-black">
              <Check className="w-4 h-4 mr-2" />
              Подтвердить покупку
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Sell Resource Modal */}
      <Dialog open={showSellResourceModal} onOpenChange={setShowSellResourceModal}>
        <DialogContent className="bg-void border-white/10 !rounded-2xl">
          <DialogHeader>
            <DialogTitle className="text-white flex items-center gap-2">
              <ArrowUpRight className="w-5 h-5 text-green-400" />
              {t('sellResourcesTitle') || 'Продать ресурсы'}
            </DialogTitle>
          </DialogHeader>
          
          <div className="space-y-4">
            <div>
              <Label className="text-white">{t('selectBizSell')}</Label>
              <Select 
                value={sellResourceForm.business_id} 
                onValueChange={(v) => {
                  const biz = myBusinesses.find(b => b.id === v);
                  setSellResourceForm({
                    ...sellResourceForm,
                    business_id: v,
                    resource_type: biz?.produces || ''
                  });
                }}
              >
                <SelectTrigger className="bg-white/5 border-white/10">
                  <SelectValue placeholder={t('selectBizSell')} />
                </SelectTrigger>
                <SelectContent>
                  {myBusinesses.length === 0 ? (
                    <SelectItem value="none" disabled>{t('youHaveNoBusinesses') || 'У вас нет бизнесов'}</SelectItem>
                  ) : (
                    myBusinesses.map(biz => (
                      <SelectItem key={biz.id} value={biz.id}>
                        {BUSINESS_ICONS[biz.business_type]} {tBusiness(biz.business_type, lang) || biz.business_type} (Lv.{biz.level})
                      </SelectItem>
                    ))
                  )}
                </SelectContent>
              </Select>
            </div>
            
            <div>
              <Label className="text-white">{t('quantityLabel') || 'Количество'}</Label>
              <Input 
                type="number"
                max={MAX_PRICE_VALUE}
                value={sellResourceForm.amount}
                onChange={(e) => setSellResourceForm({...sellResourceForm, amount: Math.min(parseFloat(e.target.value) || 0, MAX_PRICE_VALUE)})}
                className="bg-white/5 border-white/10 text-white"
                data-testid="sell-resource-amount-input"
              />
            </div>
            
            <div>
              <Label className="text-white">{t('pricePerUnitCity') || 'Цена за единицу ($CITY)'}</Label>
              <Input 
                type="number"
                step="0.0001"
                max={MAX_PRICE_VALUE}
                value={sellResourceForm.price_per_unit}
                onChange={(e) => setSellResourceForm({...sellResourceForm, price_per_unit: Math.min(parseFloat(e.target.value) || 0, MAX_PRICE_VALUE)})}
                className="bg-white/5 border-white/10 text-white"
                data-testid="sell-resource-price-input"
              />
            </div>
            
            {sellResourceForm.amount > 0 && sellResourceForm.price_per_unit > 0 && (
              <div className="p-3 bg-green-500/10 border border-green-500/20 rounded-lg space-y-1">
                {(() => {
                  const rTier = RESOURCE_INFO[sellResourceForm.resource_type]?.tier || 1;
                  const taxPct = rTier === 1 ? taxSettings.small_business_tax
                               : rTier === 2 ? taxSettings.medium_business_tax
                               : taxSettings.large_business_tax;
                  const gross = sellResourceForm.amount * sellResourceForm.price_per_unit;
                  const taxAmt = gross * taxPct / 100;
                  const afterCityTax = gross - taxAmt;
                  // Tax-haven preview: if the currently-selected business is bound to an
                  // active tax_haven contract, the patron takes a frozen share of the
                  // seller's TON income. Show it as a $CITY-equivalent line.
                  const taxHavenContract = (myContractsAsVassal || []).find(c =>
                    c.type === 'tax_haven' &&
                    c.status === 'active' &&
                    c.vassal_business_id === sellResourceForm.business_id
                  ) || null;
                  const taxHavenRate = taxHavenContract ? Number(taxHavenContract.tax_rate ?? 0.10) : 0;
                  const patronCut = afterCityTax * taxHavenRate;
                  const net = afterCityTax - patronCut;
                  return (
                    <>
                      <div className="flex justify-between text-sm">
                        <span className="text-text-muted">{t('listingAmountLabel') || 'Сумма листинга'}:</span>
                        <span className="text-white font-mono">{formatCity(gross)} $CITY</span>
                      </div>
                      <div className="flex justify-between text-sm">
                        <span className="text-text-muted">{t('taxLabel') || 'Налог'} ({taxPct}%, Tier {rTier}):</span>
                        <span className="text-red-400 font-mono">−{formatCity(taxAmt)} $CITY</span>
                      </div>
                      {taxHavenRate > 0 && (
                        <div className="flex justify-between text-sm" data-testid="marketplace-sell-tax-haven-row">
                          <span className="text-amber-300 truncate pr-2">
                            {t('contractCutLabel') || 'Контракт'} ({(taxHavenRate * 100).toFixed(0)}%):
                          </span>
                          <span className="text-amber-400 font-mono">−{formatCity(patronCut)} $CITY</span>
                        </div>
                      )}
                      <div className="flex justify-between text-sm border-t border-white/10 pt-1">
                        <span className="text-white font-medium">{t('netProfitLabel2') || 'Чистая прибыль'}:</span>
                        <span className="text-green-400 font-bold font-mono">{formatCity(net)} $CITY</span>
                      </div>
                    </>
                  );
                })()}
              </div>
            )}
          </div>
          
          <DialogFooter>
            <Button onClick={handleSellResource} className="bg-green-600 w-full">
              <Plus className="w-4 h-4 mr-2" />
              {t('listForSale') || 'Выставить на продажу'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Sell Land Modal */}
      <Dialog open={showSellLandModal} onOpenChange={setShowSellLandModal}>
        <DialogContent className="bg-void border-white/10 !rounded-2xl">
          <DialogHeader>
            <DialogTitle className="text-white flex items-center gap-2">
              <MapPin className="w-5 h-5 text-amber-400" />
              {t('sellPlotTitle')}
            </DialogTitle>
          </DialogHeader>
          
          <div className="space-y-4">
            <div>
              <Label className="text-white">{t('selectPlotSell')}</Label>
              <Select 
                value={sellLandForm.plot_id} 
                onValueChange={(v) => {
                  setSellLandForm({
                    ...sellLandForm,
                    plot_id: v,
                    price: ''
                  });
                  // Prefetch business minimum sale price (in TON + $CITY) so we
                  // can block submission when the seller enters a price below
                  // the protocol-enforced minimum. Empty plots have no min.
                  setSellLandMinPriceCity(null);
                  setSellLandMinPriceTon(null);
                  const sel = myPlots.find(p => p.id === v);
                  const bizId = sel?.business_id;
                  if (bizId && token) {
                    fetch(`${API}/business/calculate-sale-tax`, {
                      method: 'POST',
                      headers: {
                        'Content-Type': 'application/json',
                        Authorization: `Bearer ${token}`,
                      },
                      // Probe with a token price; the endpoint returns
                      // min_price / min_price_city regardless of input price.
                      body: JSON.stringify({ price: 0.01, business_id: bizId }),
                    })
                      .then(r => (r.ok ? r.json() : null))
                      .then(data => {
                        if (!data) return;
                        if (data.min_price_city != null) setSellLandMinPriceCity(data.min_price_city);
                        if (data.min_price != null) setSellLandMinPriceTon(data.min_price);
                      })
                      .catch(() => {});
                  }
                }}
              >
                <SelectTrigger className="bg-white/5 border-white/10">
                  <SelectValue placeholder={t('selectPlotSell')} />
                </SelectTrigger>
                <SelectContent>
                  {myPlots.filter(p => !p.on_sale).length === 0 ? (
                    <SelectItem value="none" disabled>{t('noPlotsAvailable')}</SelectItem>
                  ) : (
                    myPlots.filter(p => !p.on_sale).map(plot => {
                      const cityName = plot.island_id === 'ton_island' ? 'GRAM Island' : 
                        (typeof plot.city_name === 'object' ? (plot.city_name?.ru || plot.city_name?.en || 'GRAM Island') : (plot.city_name || 'GRAM Island'));
                      return (
                        <SelectItem key={plot.id} value={plot.id}>
                          [{plot.x}, {plot.y}] - {cityName}
                        </SelectItem>
                      );
                    })
                  )}
                </SelectContent>
              </Select>
            </div>
            
            {/* Show selected plot details */}
            {sellLandForm.plot_id && (() => {
              const selectedPlot = myPlots.find(p => p.id === sellLandForm.plot_id);
              if (!selectedPlot) return null;
              const cityName = selectedPlot.island_id === 'ton_island' ? 'GRAM Island' : 
                (typeof selectedPlot.city_name === 'object' ? (selectedPlot.city_name?.ru || selectedPlot.city_name?.en || 'GRAM Island') : (selectedPlot.city_name || 'GRAM Island'));
              const businessName = selectedPlot.business_type 
                ? (typeof selectedPlot.business_name === 'object' ? (selectedPlot.business_name?.[language] || selectedPlot.business_name?.en || selectedPlot.business_name?.ru) : selectedPlot.business_name) || selectedPlot.business_type
                : null;
              const totalSpent = (selectedPlot.price || 0) + (selectedPlot.business_cost || 0);
              
              return (
                <div className="p-3 bg-white/5 rounded-lg border border-white/10 space-y-2">
                  <div className="flex justify-between text-sm">
                    <span className="text-text-muted">{t('cityFieldLabel')}:</span>
                    <span className="text-amber-400">{cityName}</span>
                  </div>
                  <div className="flex justify-between text-sm">
                    <span className="text-text-muted">{t('coordinatesLabel')}:</span>
                    <span className="text-white">[{selectedPlot.x}, {selectedPlot.y}]</span>
                  </div>
                  <div className="flex justify-between text-sm">
                    <span className="text-text-muted">{t('bizOnPlotLabel')}:</span>
                    {businessName ? (
                      <span className="text-green-400">{businessName}</span>
                    ) : (
                      <span className="text-gray-400 italic">{t('noBusinessPlaceholder')}</span>
                    )}
                  </div>
                  {selectedPlot.business_cost > 0 && (
                    <div className="flex justify-between text-sm">
                      <span className="text-text-muted">{t('bizCostLabel')}:</span>
                      <span className="text-white font-mono">{formatCity(tonToCity(selectedPlot.business_cost || 0))} $CITY</span>
                    </div>
                  )}
                </div>
              );
            })()}
            
            <div>
              <Label className="text-white">{t('salePriceLabel')} ($CITY)</Label>
              <Input 
                type="number"
                step="0.01"
                min="0"
                max={MAX_PRICE_VALUE}
                placeholder={t('enterPricePlaceholder')}
                value={sellLandForm.price || ''}
                onChange={(e) => setSellLandForm({...sellLandForm, price: Math.min(parseFloat(e.target.value) || 0, MAX_PRICE_VALUE)})}
                className="bg-white/5 border-white/10 text-white"
                data-testid="sell-land-price-input"
              />
              {sellLandMinPriceCity != null && (() => {
                const priceNum = parseFloat(sellLandForm.price) || 0;
                const belowMin = priceNum > 0 && priceNum < sellLandMinPriceCity;
                return (
                  <div
                    className={`text-xs mt-1 ${belowMin ? 'text-red-400' : 'text-amber-400'}`}
                    data-testid="sell-land-min-price-hint"
                  >
                    {belowMin
                      ? (lang === 'ru'
                          ? `Цена ниже минимума: ${formatCity(sellLandMinPriceCity)} $CITY${sellLandMinPriceTon != null ? ` (${sellLandMinPriceTon.toFixed(2)} TON)` : ''}`
                          : `Price below minimum: ${formatCity(sellLandMinPriceCity)} $CITY${sellLandMinPriceTon != null ? ` (${sellLandMinPriceTon.toFixed(2)} TON)` : ''}`)
                      : `${(lang === 'ru' ? 'Минимальная цена' : 'Minimum price')}: ${formatCity(sellLandMinPriceCity)} $CITY${sellLandMinPriceTon != null ? ` (${sellLandMinPriceTon.toFixed(2)} TON)` : ''}`}
                  </div>
                );
              })()}
            </div>
            
            {sellLandForm.price > 0 && (
              <div className="p-3 bg-amber-500/10 border border-amber-500/20 rounded-lg space-y-1">
                {(() => {
                  const taxPct = taxSettings.land_business_sale_tax || 20;
                  const gross = sellLandForm.price;
                  const taxAmt = gross * taxPct / 100;
                  const afterTax = gross - taxAmt;
                  const creditPct = activeCredits.reduce((acc, c) =>
                    acc + (Number(c.salary_deduction_percent) || 0) * (c.is_doubled_rate ? 2 : 1), 0
                  );
                  const creditCut = afterTax * creditPct;
                  const net = afterTax - creditCut;
                  return (
                    <>
                      <div className="flex justify-between text-sm">
                        <span className="text-text-muted">{t('salePriceLabel')}:</span>
                        <span className="text-white font-mono">{formatCity(gross)} $CITY</span>
                      </div>
                      <div className="flex justify-between text-sm">
                        <span className="text-text-muted">{t('taxLabel')} ({taxPct}%):</span>
                        <span className="text-red-400 font-mono">−{formatCity(taxAmt)} $CITY</span>
                      </div>
                      {creditPct > 0 && (
                        <div className="flex justify-between text-sm" data-testid="sell-land-credit-row">
                          <span className="text-rose-300">
                            🏦 {t('creditRepaymentLabel') || 'Кредит'} ({(creditPct * 100).toFixed(1)}%):
                          </span>
                          <span className="text-rose-400 font-mono">−{formatCity(creditCut)} $CITY</span>
                        </div>
                      )}
                      <div className="flex justify-between text-sm border-t border-white/10 pt-1">
                        <span className="text-white font-medium">{t('netProfitLabel')}:</span>
                        <span className="text-amber-400 font-bold font-mono">{formatCity(net)} $CITY</span>
                      </div>
                    </>
                  );
                })()}
              </div>
            )}
          </div>
          
          <DialogFooter className="flex-row gap-2 justify-end">
            <Button
              onClick={handleSellLand}
              disabled={
                !sellLandForm.plot_id ||
                !(parseFloat(sellLandForm.price) > 0) ||
                (sellLandMinPriceCity != null &&
                  parseFloat(sellLandForm.price) < sellLandMinPriceCity)
              }
              data-testid="sell-land-submit-btn"
              className="bg-amber-500 text-black w-full disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Plus className="w-4 h-4 mr-2" />
              {t('listForSale') || 'Выставить на продажу'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Buy Land Confirmation Modal */}
      <Dialog open={showBuyLandModal} onOpenChange={setShowBuyLandModal}>
        <DialogContent className="bg-void border-white/10 max-w-md !rounded-2xl">
          <DialogHeader>
            <DialogTitle className="text-white flex items-center gap-2">
              <ShoppingCart className="w-5 h-5 text-amber-400" />
              Подтверждение покупки
            </DialogTitle>
          </DialogHeader>
          
          {selectedLandListing && (
            <div className="space-y-4">
              {/* Location Info */}
              <div className="p-4 bg-white/5 rounded-lg border border-white/10">
                <h4 className="text-white font-bold mb-2">📍 Информация об участке</h4>
                <div className="space-y-1 text-sm">
                  <div className="flex justify-between">
                    <span className="text-text-muted">Координаты:</span>
                    <span className="text-white">[{selectedLandListing.x}, {selectedLandListing.y}]</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-text-muted">Расположение:</span>
                    <span className="text-white">{
                      typeof selectedLandListing.city_name === 'object' 
                        ? (selectedLandListing.city_name?.ru || selectedLandListing.city_name?.en || 'GRAM Island')
                        : (selectedLandListing.city_name || 'GRAM Island')
                    }</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-text-muted">Продавец:</span>
                    <span className="text-white">{selectedLandListing.seller_username || t('anonymous')}</span>
                  </div>
                </div>
              </div>
              
              {/* Business Info (if exists) */}
              {selectedLandListing.business && (
                <div className="p-4 bg-purple-500/10 rounded-lg border border-purple-500/20">
                  <h4 className="text-purple-400 font-bold mb-2">🏢 Бизнес на участке</h4>
                  <div className="space-y-1 text-sm">
                    <div className="flex justify-between">
                      <span className="text-text-muted">Тип:</span>
                      <span className="text-white">{selectedLandListing.business.icon} {tBusiness(selectedLandListing.business.type, lang) || (typeof selectedLandListing.business.name === 'object' ? (selectedLandListing.business.name?.[lang] || selectedLandListing.business.name?.en || selectedLandListing.business.name?.ru || selectedLandListing.business.type) : (selectedLandListing.business.name || selectedLandListing.business.type))}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-text-muted">Уровень:</span>
                      <span className="text-white">Ур. {selectedLandListing.business.level || 1}</span>
                    </div>
                    {selectedLandListing.business.tier && (
                      <div className="flex justify-between">
                        <span className="text-text-muted">Тир:</span>
                        <span className="text-white">Tier {selectedLandListing.business.tier}</span>
                      </div>
                    )}
                  </div>
                </div>
              )}
              
              {!selectedLandListing.business && (
                <div className="p-4 bg-gray-500/10 rounded-lg border border-gray-500/20">
                  <p className="text-text-muted text-sm text-center">
                    На участке нет построенного бизнеса
                  </p>
                </div>
              )}
              
              {/* Price */}
              <div className="p-4 bg-amber-500/10 rounded-lg border border-amber-500/20">
                <div className="flex justify-between items-center">
                  <span className="text-text-muted">Цена:</span>
                  <span className="text-2xl font-bold text-amber-400">{formatCity(tonToCity(selectedLandListing.price || 0))} $CITY</span>
                </div>
                <div className="flex justify-between items-center text-sm mt-2">
                  <span className="text-text-muted">{t('yourBalance') || 'Ваш баланс'}:</span>
                  <span className={`font-mono ${spendableTon >= selectedLandListing.price ? 'text-green-400' : 'text-red-400'}`} data-testid="land-buy-spendable-balance">
                    {formatCity(tonToCity(spendableTon))} $CITY
                  </span>
                </div>
              </div>
              
              {/* Warning if insufficient balance (bonus + real) */}
              {spendableTon < selectedLandListing.price && (
                <div className="p-3 bg-red-500/10 border border-red-500/20 rounded-lg" data-testid="land-buy-insufficient">
                  <p className="text-red-400 text-sm text-center">
                    ⚠️ {t('insufficientFunds') || 'Недостаточно средств'}
                  </p>
                </div>
              )}
            </div>
          )}
          
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setShowBuyLandModal(false)} className="border-white/10">
              Отмена
            </Button>
            <Button 
              onClick={handleBuyLand} 
              className="bg-amber-500 text-black hover:bg-amber-600"
              disabled={!user || spendableTon < (selectedLandListing?.price || 0)}
            >
              <ShoppingCart className="w-4 h-4 mr-2" />
              Подтвердить покупку
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Filter modal — replaces inline filters. Two controls: business type + sort. */}
      <Dialog open={showFilterModal} onOpenChange={setShowFilterModal}>
        <DialogContent className="bg-void border-white/10 !rounded-2xl max-w-md">
          <DialogHeader>
            <DialogTitle className="text-white flex items-center gap-2">
              <Filter className="w-5 h-5 text-cyber-cyan" />
              {t('filterLabel') || 'Фильтры'}
            </DialogTitle>
          </DialogHeader>

          <div className="space-y-4 py-2">
            {/* Business Type */}
            <div className="space-y-1.5">
              <Label className="text-text-muted text-xs uppercase tracking-wide">
                {t('allBusinessTypes') || 'Тип бизнеса'}
              </Label>
              <Select value={businessTypeFilter} onValueChange={setBusinessTypeFilter}>
                <SelectTrigger
                  data-testid="filter-modal-type-trigger"
                  className="w-full bg-white/5 border-white/10 text-sm"
                >
                  <Building2 className="w-4 h-4 mr-2 shrink-0" />
                  <SelectValue placeholder={t('allBusinessTypes')} />
                </SelectTrigger>
                <SelectContent className="max-h-80">
                  <SelectItem value="all">{t('allTypes')}</SelectItem>
                  {/* Tier 1 */}
                  <SelectItem value="helios">☀️ Helios</SelectItem>
                  <SelectItem value="scrap_yard">🏗️ Scrap Yard</SelectItem>
                  <SelectItem value="quartz_mine">💎 Quartz Mine</SelectItem>
                  <SelectItem value="nano_dc">🖥️ Nano DC</SelectItem>
                  <SelectItem value="signal_tower">📡 Signal Tower</SelectItem>
                  <SelectItem value="hydro_cooling">❄️ Cold Storage</SelectItem>
                  <SelectItem value="bio_farm">🌿 Bio Farm</SelectItem>
                  {/* Tier 2 */}
                  <SelectItem value="chips_factory">🏭 Chip Factory</SelectItem>
                  <SelectItem value="ai_lab">🧪 AI Lab</SelectItem>
                  <SelectItem value="nft_studio">🎨 NFT Studio</SelectItem>
                  <SelectItem value="vr_club">👓 VR Club</SelectItem>
                  <SelectItem value="logistics_hub">🚁 Logistics</SelectItem>
                  <SelectItem value="cyber_cafe">☕ Cyber Cafe</SelectItem>
                  <SelectItem value="repair_shop">🛠️ Repair Zone</SelectItem>
                  {/* Tier 3 */}
                  <SelectItem value="validator">🛡️ Validator</SelectItem>
                  <SelectItem value="gram_bank">🏦 Gram Bank</SelectItem>
                  <SelectItem value="dex">💹 DEX</SelectItem>
                  <SelectItem value="casino">🎰 Casino</SelectItem>
                  <SelectItem value="arena">🏟️ Arena</SelectItem>
                  <SelectItem value="incubator">🐣 Incubator</SelectItem>
                  <SelectItem value="bridge">🌉 Bridge</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* Sort direction (price asc / desc) */}
            <div className="space-y-1.5">
              <Label className="text-text-muted text-xs uppercase tracking-wide">
                {t('sortLabel') || 'Цена'}
              </Label>
              <Select value={sortBy} onValueChange={setSortBy}>
                <SelectTrigger
                  data-testid="filter-modal-sort-trigger"
                  className="w-full bg-white/5 border-white/10 text-sm"
                >
                  <SortAsc className="w-4 h-4 mr-2 shrink-0" />
                  <SelectValue placeholder={t('sortLabel')} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="price">{t('priceAsc')}</SelectItem>
                  <SelectItem value="price_desc">{t('priceDesc')}</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <DialogFooter className="gap-2">
            <Button
              variant="outline"
              onClick={() => {
                setBusinessTypeFilter('all');
                setSortBy('price');
              }}
              data-testid="filter-modal-reset"
              className="border-white/10"
            >
              {t('filterReset') || 'Сбросить'}
            </Button>
            <Button
              onClick={() => setShowFilterModal(false)}
              data-testid="filter-modal-apply"
              className="bg-cyber-cyan text-black hover:bg-cyber-cyan/80"
            >
              <Check className="w-4 h-4 mr-2" />
              {t('filterApply') || 'Применить'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
