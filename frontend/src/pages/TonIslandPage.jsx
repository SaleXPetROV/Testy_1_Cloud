import { formatErrorDetail } from '@/lib/apiErrors';
import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Loader2, ZoomIn, ZoomOut, Home, Info, Building2,
  Coins, MapPin, X, ChevronRight, AlertCircle, Crown,
  RefreshCw, Play, TrendingUp, Clock
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Progress } from '@/components/ui/progress';
import { toast } from 'sonner';
import Sidebar from '@/components/Sidebar';
import { useLanguage } from '@/context/LanguageContext';
import { useTranslation } from '@/lib/translations';
import { tonToCity, cityToTon, formatCity, formatTon } from '@/lib/currency';
import { getResource, getResourceName as getResourceNameLocalized } from '@/lib/resourceConfig';
import { tBusiness } from '@/lib/translationsExtra';
import { useTutorial } from '@/context/TutorialContext';
import T3RewardBanner from '@/components/T3RewardBanner';
import ReferralInvitePopup from '@/components/ReferralInvitePopup';
import LandPurchaseTopUpModal from '@/components/LandPurchaseTopUpModal';
import SmartAvatar from '@/components/SmartAvatar';
import { getGameMode, setGameMode } from '@/lib/gameMode';

// Import map engine
import { mapStore, getZone, GRID_COLS, GRID_ROWS, BUILDING_ICONS } from '@/engine/IsometricMapEngine';
import CityMapEngine from '@/engine/CityMapEngine';   // the new city map (same interface)
import { fill } from '@/lib/translationsMore';
import { fetchSkinsIndex, getCachedSkinsIndex, resolveSkinUrl, getCachedSkinSizes, resolveSkinSize, resolveSkinMeta } from '@/lib/skins';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api`;

// Helper function to get zone name with translations
const getZoneName = (zone, t) => {
  if (!zone || typeof zone !== 'string') return '—';
  const zoneKey = `zone${zone.charAt(0).toUpperCase() + zone.slice(1)}`;
  return t(zoneKey) || zone;
};

// Level-0 (застолблённый) business — localized strings (all 9 project languages).
const ZERO_I18N = {
  en: { locked: 'To buy new businesses, upgrade your business to level 1', lv0: 'Lv.0', buyBtn: 'Buy', ownerLabel: 'Owner', claimed: 'Business claimed (Lv.0)! ⚠️ Until you upgrade it to level 1, other players can buy it from the marketplace at any time. Resource-sale income goes only to your BONUS balance.', bought: 'Business purchased!' },
  ru: { locked: 'Для покупки новых бизнесов прокачайте свой бизнес до уровня 1', lv0: 'Ур.0', buyBtn: 'Купить', ownerLabel: 'Владелец', claimed: 'Бизнес застолблён (Ур.0)! ⚠️ Пока вы не прокачаете его до 1 уровня, другие игроки могут выкупить его на Маркетплейсе в любой момент. Доход с продажи ресурсов идёт только на БОНУСНЫЙ баланс.', bought: 'Бизнес куплен!' },
  es: { locked: 'Para comprar nuevos negocios, mejora tu negocio al nivel 1', lv0: 'Nv.0', buyBtn: 'Comprar', ownerLabel: 'Propietario', claimed: '¡Negocio reclamado (Nv.0)! ⚠️ Hasta que lo mejores al nivel 1, otros jugadores pueden comprarlo en el Mercado en cualquier momento. Los ingresos por venta de recursos van solo a tu saldo de BONO.', bought: '¡Negocio comprado!' },
  zh: { locked: '要购买新企业，请先将您的企业升级到1级', lv0: '0级', buyBtn: '购买', ownerLabel: '所有者', claimed: '已认领企业（0级）！⚠️ 在您升级到1级之前，其他玩家随时可以在市场上购买它。资源销售收入仅计入您的奖金余额。', bought: '企业已购买！' },
  fr: { locked: 'Pour acheter de nouvelles entreprises, améliorez votre entreprise au niveau 1', lv0: 'Niv.0', buyBtn: 'Acheter', ownerLabel: 'Propriétaire', claimed: 'Entreprise réclamée (Niv.0) ! ⚠️ Tant que vous ne l\'améliorez pas au niveau 1, d\'autres joueurs peuvent l\'acheter sur le Marché à tout moment. Les revenus de vente de ressources vont uniquement sur votre solde BONUS.', bought: 'Entreprise achetée !' },
  de: { locked: 'Um neue Unternehmen zu kaufen, bringe dein Unternehmen auf Stufe 1', lv0: 'St.0', buyBtn: 'Kaufen', ownerLabel: 'Besitzer', claimed: 'Unternehmen beansprucht (St.0)! ⚠️ Bis du es auf Stufe 1 bringst, können andere Spieler es jederzeit auf dem Marktplatz kaufen. Einnahmen aus Ressourcenverkäufen gehen nur auf dein BONUS-Guthaben.', bought: 'Unternehmen gekauft!' },
  ja: { locked: '新しいビジネスを購入するには、ビジネスをレベル1にアップグレードしてください', lv0: 'Lv.0', buyBtn: '購入', ownerLabel: 'オーナー', claimed: 'ビジネスを取得（Lv.0）！⚠️ レベル1にアップグレードするまで、他のプレイヤーがマーケットでいつでも購入できます。資源売却の収入はボーナス残高にのみ入ります。', bought: 'ビジネスを購入しました！' },
  ko: { locked: '새 비즈니스를 구매하려면 비즈니스를 레벨 1로 업그레이드하세요', lv0: 'Lv.0', buyBtn: '구매', ownerLabel: '소유자', claimed: '비즈니스 선점 (Lv.0)! ⚠️ 레벨 1로 업그레이드하기 전까지 다른 플레이어가 마켓에서 언제든지 구매할 수 있습니다. 자원 판매 수익은 보너스 잔액으로만 들어갑니다.', bought: '비즈니스를 구매했습니다!' },
  id: { locked: 'Untuk membeli bisnis baru, tingkatkan bisnis Anda ke level 1', lv0: 'Lv.0', buyBtn: 'Beli', ownerLabel: 'Pemilik', claimed: 'Bisnis diklaim (Lv.0)! ⚠️ Sampai Anda meningkatkannya ke level 1, pemain lain dapat membelinya di Marketplace kapan saja. Pendapatan penjualan sumber daya hanya masuk ke saldo BONUS Anda.', bought: 'Bisnis dibeli!' },
};


// Format a remaining-time gap (ms) into "Nd HH:MM:SS" countdown parts.
// `daysLabel` is the localized short suffix for "days" (e.g. д / d / 天 / 日).
const formatCountdown = (ms, daysLabel = 'д') => {
  if (ms <= 0) return null;
  const totalSec = Math.floor(ms / 1000);
  const days = Math.floor(totalSec / 86400);
  const hours = Math.floor((totalSec % 86400) / 3600);
  const minutes = Math.floor((totalSec % 3600) / 60);
  const seconds = totalSec % 60;
  const p = (n) => String(n).padStart(2, '0');
  return { days, hours, minutes, seconds, text: `${days}${daysLabel} ${p(hours)}:${p(minutes)}:${p(seconds)}` };
};

// Helper function to get resource name with translations.
// Uses the central RESOURCE_NAMES table from resourceConfig (handles multi-word
// ids like `gold_bill` → "Золотой вексель") and falls back to the old
// translations.js key only if the resource is unknown there.
const getResourceName = (resource, t, lang) => {
  if (!resource) return '';
  const fromConfig = getResourceNameLocalized(resource, lang);
  if (fromConfig && fromConfig !== resource) return fromConfig;
  const camel = resource
    .split('_')
    .map((s) => s.charAt(0).toUpperCase() + s.slice(1))
    .join('');
  const key = `resource${camel}`;
  const translated = t(key);
  return (translated && translated !== key) ? translated : resource;
};

// Tier colors
const TIER_STYLES = {
  1: 'bg-green-500/20 text-green-400 border-green-500/30',
  2: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  3: 'bg-purple-500/20 text-purple-400 border-purple-500/30',
};

// Helper to safely get business name from config (handles both object and string)
const getBusinessName = (config, fallback = '') => {
  if (!config?.name) return fallback;
  if (typeof config.name === 'string') return config.name;
  return config.name?.ru || config.name?.en || fallback;
};

/**
 * Trash-pile decoration layer for GRAM Island.
 *
 * Renders an animated trash.webp on every plot that currently has a
 * `trash_pile` on the server (list fetched from `/api/trash/list`).
 * PIXI cannot play multi-frame animated WebP as a texture, so each pile is
 * an absolutely-positioned HTML <img> on top of the canvas. Positions are
 * re-computed every animation frame from the engine's pan/zoom state.
 *
 * A "ready" pile also gets a pulsing 📦 badge above it so the player can
 * spot which pile is theirs to collect.
 */
function GramIslandTrashLayer({ engineRef, piles, onPileClick, currentUserId }) {
  const containerRef = useRef(null);
  const spriteRefs = useRef(new Map()); // pileId → { img, badge }
  const pileMapRef = useRef(new Map());
  useEffect(() => { pileMapRef.current = new Map(piles.map(p => [p.id, p])); }, [piles]);

  useEffect(() => {
    let rafId = 0;
    const tick = () => {
      const engine = engineRef.current;
      const parent = containerRef.current;
      if (engine && parent && typeof engine.getCellScreenPosition === 'function') {
        pileMapRef.current.forEach((pile, pileId) => {
          const p = engine.getCellScreenPosition(pile.x, pile.y);
          const refs = spriteRefs.current.get(pileId);
          if (!refs || !p) {
            if (refs) { refs.img.style.opacity = '0'; refs.badge.style.opacity = '0'; }
            return;
          }
          // Sized to FIT INSIDE the (inset) plot — matches SPRITE_FIT (0.66)
          // used for building sprites in the engine.
          const targetW = p.tileWidth * 0.66;
          const targetH = targetW * (167 / 178) * 0.85;
          // Vertical lift must scale with zoom, otherwise a fixed 5px screen
          // offset makes the pile drift UP when zooming out and DOWN when
          // zooming in. Match the engine's world-space building lift (5px at
          // base scale) by multiplying by the current zoom scale.
          const lift = 5 * p.scale;
          refs.img.style.width = `${targetW}px`;
          refs.img.style.height = `${targetH}px`;
          refs.img.style.left = `${p.x - targetW / 2}px`;
          refs.img.style.top = `${p.y - targetH - lift}px`;
          refs.img.style.opacity = '1';
          // Ready badge (mine, ready to collect) — pulses above the pile.
          // Compute readiness locally: a "processing" pile whose timer has
          // already elapsed is treated as ready immediately, without waiting
          // for the next server poll.
          let liveStatus = pile.status;
          if (liveStatus === 'processing' && pile.ready_at &&
              new Date(pile.ready_at).getTime() <= Date.now()) {
            liveStatus = 'ready';
          }
          const isMineReady = liveStatus === 'ready' && pile.scanned_by === currentUserId;
          if (isMineReady) {
            // Badge scales purely with zoom (targetW already tracks tile size);
            // no fixed 18px floor, otherwise it stays too large when zoomed out.
            const badgeSize = Math.max(8, Math.round(targetW * 0.42));
            refs.badge.style.width = `${badgeSize}px`;
            refs.badge.style.height = `${badgeSize}px`;
            refs.badge.style.left = `${p.x - badgeSize / 2}px`;
            refs.badge.style.top = `${p.y - targetH - lift - badgeSize * 0.7}px`;
            refs.badge.style.opacity = '1';
            refs.badge.style.fontSize = `${Math.round(badgeSize * 0.65)}px`;
          } else {
            refs.badge.style.opacity = '0';
          }
        });
      }
      rafId = requestAnimationFrame(tick);
    };
    rafId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId);
  }, [engineRef, currentUserId]);

  return (
    <div ref={containerRef} style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}>
      {piles.map(pile => (
        <React.Fragment key={pile.id}>
          <img
            ref={(el) => {
              const cur = spriteRefs.current.get(pile.id) || {};
              if (el) {
                cur.img = el;
                spriteRefs.current.set(pile.id, cur);
              }
            }}
            src="/trash.webp"
            alt="Trash pile"
            data-testid={`trash-pile-${pile.id}`}
            draggable={false}
            onClick={(e) => {
              // The outside-click watcher on TonIslandPage clears selectedCell
              // whenever a click lands outside the map container AND the info
              // panel. The trash layer is a sibling of both, so its clicks
              // would immediately close the panel we just opened → stop.
              e.stopPropagation();
              onPileClick && onPileClick(pile);
            }}
            style={{
              position: 'absolute',
              left: 0, top: 0, width: 0, height: 0,
              opacity: 0,
              userSelect: 'none',
              imageRendering: 'auto',
              zIndex: 15,
              pointerEvents: 'auto',
              cursor: 'pointer',
            }}
          />
          <div
            ref={(el) => {
              const cur = spriteRefs.current.get(pile.id) || {};
              if (el) {
                cur.badge = el;
                spriteRefs.current.set(pile.id, cur);
              }
            }}
            data-testid={`trash-ready-badge-${pile.id}`}
            style={{
              position: 'absolute',
              left: 0, top: 0, width: 0, height: 0,
              opacity: 0,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              background: 'radial-gradient(circle, rgba(34,197,94,0.95) 40%, rgba(22,163,74,0.7) 100%)',
              borderRadius: '50%',
              boxShadow: '0 0 12px rgba(34,197,94,0.9), 0 0 24px rgba(34,197,94,0.6)',
              animation: 'trashReadyPulse 1.4s ease-in-out infinite',
              zIndex: 16,
              pointerEvents: 'none',
              userSelect: 'none',
            }}
          >
            📦
          </div>
        </React.Fragment>
      ))}
      <style>{`@keyframes trashReadyPulse {
        0%, 100% { transform: scale(1); }
        50%      { transform: scale(1.18); }
      }`}</style>
    </div>
  );
}

export default function TonIslandPage({ user, refreshBalance, updateBalance }) {
  const navigate = useNavigate();
  const containerRef = useRef(null);
  const engineRef = useRef(null);
  const cellInfoRef = useRef(null);
  // Always-fresh refs for handlers passed into the imperative engine (engine
  // captures them only once on init — without a ref the closure goes stale
  // and tutorial state inside the handler is never the latest).
  const handleCellClickRef = useRef(() => {});
  const handleCellHoverRef = useRef(() => {});
  const tutorial = useTutorial();
  
  // Get language from context
  const { language: lang } = useLanguage();
  const { t } = useTranslation(lang);
  
  const [isLoading, setIsLoading] = useState(true);
  const [businessTypes, setBusinessTypes] = useState({});
  const [patrons, setPatrons] = useState([]);
  const [userBalance, setUserBalance] = useState(0);
  const [myBusinessesList, setMyBusinessesList] = useState([]);
  
  // Modals
  const [selectedCell, setSelectedCell] = useState(null);
  const [selectedSprite, setSelectedSprite] = useState(null);   // the building / skin picture drawn on the map
  const [showBuildModal, setShowBuildModal] = useState(false);
  const [selectedBusinessType, setSelectedBusinessType] = useState('');
  const [selectedPatron, setSelectedPatron] = useState('');
  
  // Loading states
  const [isPurchasing, setIsPurchasing] = useState(false);
  const [isBuilding, setIsBuilding] = useState(false);
  // Insufficient-funds top-up modal (opened when the user clicks Buy but the
  // balance is too low). Purchase then happens after a successful top-up.
  const [showTopUpModal, setShowTopUpModal] = useState(false);
  // Demo → Real conversion modal (opened when a demo user presses Buy on a plot)
  const [showDemoConvertModal, setShowDemoConvertModal] = useState(false);
  const [demoConvertCell, setDemoConvertCell] = useState(null);
  const [isConverting, setIsConverting] = useState(false);
  
  // Track mobile for slide direction
  const [isMobile, setIsMobile] = useState(window.innerWidth < 768);
  useEffect(() => {
    const handler = () => setIsMobile(window.innerWidth < 768);
    window.addEventListener('resize', handler);
    return () => window.removeEventListener('resize', handler);
  }, []);

  // ── Per-zone trading schedule + ticking clock ──
  // tradingSchedule: { core, center, middle, outer } → ISO UTC strings or null.
  // `nowTs` ticks every second so the Buy-button countdown updates live.
  const [tradingSchedule, setTradingSchedule] = useState({});
  const [saleOnly, setSaleOnly] = useState(false);       // new map: «%» — everything on sale
  const [landListings, setLandListings] = useState({});   // "x,y" -> marketplace lot
  const [buyingLot, setBuyingLot] = useState(false);
  const fetchLandListings = useCallback(async () => {
    try {
      const r = await fetch(`${API}/market/land/listings?city_id=ton_island&has_business=true`);
      if (!r.ok) return;
      const d = await r.json(), map = {};
      (d.listings || []).forEach((l) => { if (l.x != null && l.y != null) map[`${l.x},${l.y}`] = { id: l.id, price_city: tonToCity(l.price || 0), price_ton: l.price || 0, seller: l.seller_username, seller_id: l.seller_id }; });
      setLandListings(map); mapStore.dispatch({ type: 'SET_LISTINGS', listings: map });
      // businesses offered for rent (shown in the «%» mode)
      const ro = await fetch(`${API}/rental/offers`).then((x) => (x.ok ? x.json() : { offers: [] })).catch(() => ({ offers: [] }));
      const rmap = {};
      (ro.offers || []).forEach((o) => { if (o.x != null && o.y != null) rmap[`${o.x},${o.y}`] = { id: o.id, price_city: o.price_per_day_city }; });
      mapStore.dispatch({ type: 'SET_RENT_OFFERS', rentOffers: rmap });
    } catch (e) { /* marketplace lots are optional on the map */ }
  }, []);
  // translated texts drawn on the map canvas
  useEffect(() => {
    mapStore.dispatch({ type: 'SET_LABELS', labels: { you: t('map_you_lvl'), closed: t('map_sector_closed'), lvl0: t('map_lvl0_days'),
      rent: t('map_rent_per_day') } });
  }, [lang]); // eslint-disable-line react-hooks/exhaustive-deps
  const [nowTs, setNowTs] = useState(Date.now());
  // ── Presale config ──
  // Admin-curated first-sale lot. When active:
  //   • cells in `selected_plots` render with a gold aura and (before
  //     `opens_at`) show a countdown instead of the Buy button.
  //   • ALL OTHER cells that carry a `pre_business` (would normally show
  //     Buy) get their button swapped for the admin-picked placeholder
  //     text — coming_epoch_2 / sold_out / unavailable.
  const [presale, setPresale] = useState({ active: false, selected_plots: [], opens_at: null, unavailable_label: 'coming_epoch_2', map_id: 'ton_island' });
  const presaleKeySet = useMemo(() => {
    if (!presale?.active) return null;
    const s = new Set();
    (presale.selected_plots || []).forEach((p) => s.add(`${p.x},${p.y}`));
    return s;
  }, [presale]);
  // Push the presale gold-highlight set to the map engine whenever it
  // changes so the isometric renderer re-tints those tiles.
  useEffect(() => {
    try {
      mapStore.dispatch({ type: 'SET_PRESALE_SET', presaleSet: presaleKeySet });
    } catch (_) { /* engine not ready yet — will pick up on first fetch */ }
  }, [presaleKeySet]);

  // ── Trash Piles (Завалы) ──
  // Server-managed spawnable resource drops on empty GRAM-City plots.
  // We fetch the list every 15s and on scan/collect actions.
  const [trashPiles, setTrashPiles] = useState([]);
  const trashActionBusyRef = useRef(false);

  const fetchTrashPiles = useCallback(async () => {
    // Demo mode: trash piles (завалы) are never shown on the map.
    if (getGameMode() === 'demo') { setTrashPiles([]); return; }
    const tok = localStorage.getItem('token') || localStorage.getItem('ton_city_token');
    if (!tok) return;
    try {
      const res = await fetch(`${API}/trash/list`, { headers: { Authorization: `Bearer ${tok}` } });
      if (!res.ok) return;
      const data = await res.json();
      setTrashPiles(data.piles || []);
    } catch (_) { /* silent */ }
  }, []);

  useEffect(() => {
    fetchTrashPiles();
    const iv = setInterval(() => {
      fetchTrashPiles();
    }, 15000);
    return () => clearInterval(iv);
  }, [fetchTrashPiles]);

  // ── Demo (Sandbox) map overlay ──
  // In demo mode the user's demo business lives on a single fixed virtual plot
  // [13, 12]. It is rendered as if OWNED by the current user (so their avatar
  // shows on that cell — visible only to them, since it's an injected client
  // overlay). All other cells stay exactly as the real map returns them.
  const DEMO_PLOT = { x: 13, y: 12 };
  const isDemoMode = getGameMode() === 'demo';
  const demoProfileRef = useRef(null);
  const userRef = useRef(user);
  useEffect(() => { userRef.current = user; }, [user]);

  const fetchDemoProfile = useCallback(async () => {
    if (getGameMode() !== 'demo') { demoProfileRef.current = null; return; }
    const tok = localStorage.getItem('token') || localStorage.getItem('ton_city_token');
    if (!tok) return;
    try {
      const res = await fetch(`${API}/demo/state`, { headers: { Authorization: `Bearer ${tok}` } });
      if (!res.ok) return;
      const data = await res.json();
      demoProfileRef.current = data.profile || null;
    } catch (_) { /* silent */ }
  }, []);


  // Immediate refresh the moment a scanning pile's timer expires.
  // The server only reveals a pile's reward once it is "ready", so instead of
  // waiting up to 15s for the next poll we detect the expiry locally (via the
  // 1s `nowTs` ticker) and re-fetch right away — the reward + collect button
  // then appear the instant scanning finishes.
  const expiryFetchedRef = useRef(new Set());
  useEffect(() => {
    let due = false;
    for (const p of trashPiles) {
      if (p.status === 'processing' && p.ready_at) {
        const readyMs = new Date(p.ready_at).getTime();
        if (readyMs <= nowTs && !expiryFetchedRef.current.has(p.id)) {
          expiryFetchedRef.current.add(p.id);
          due = true;
        }
      }
    }
    if (due) fetchTrashPiles();
  }, [nowTs, trashPiles, fetchTrashPiles]);

  const handleTrashClick = useCallback((pile) => {
    // Show the pile in the info panel as a "Завал" cell.
    // Look up the real zone from the current mapStore so the header reads
    // "Zone: Outer" instead of "ZoneTrash".
    let zone = 'outer';
    try {
      const state = mapStore.getState();
      const cell = state?.cells?.get?.(`${pile.x},${pile.y}`);
      if (cell?.zone) zone = cell.zone;
    } catch (_) { /* fallback below */ }
    setSelectedCell({
      _trash: pile,                        // marker for the info panel
      q: pile.x, r: pile.y,
      x: pile.x, y: pile.y,
      zone,
      is_empty: true,
      owner: null,
    });
  }, []);

  const scanTrashPile = useCallback(async (pileId) => {
    if (trashActionBusyRef.current) return;
    trashActionBusyRef.current = true;
    const tok = localStorage.getItem('token') || localStorage.getItem('ton_city_token');
    try {
      const res = await fetch(`${API}/trash/${pileId}/scan`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${tok}` },
      });
      const data = await res.json();
      if (!res.ok) {
        const msg = res.status === 429 ? (t('trashDailyLimit') || 'Daily scan limit reached')
                  : res.status === 409 ? (t('trashUnavailable') || 'Pile is no longer available')
                  : (data?.detail || 'Scan failed');
        toast.error(msg);
        return;
      }
      toast.success(t('trashScanStarted') || 'Сканирование началось');
      await fetchTrashPiles();
      // Reflect the new pile state in the currently-open panel (incl. the
      // reward so it can be shown the moment the timer finishes).
      setSelectedCell((prev) => prev && prev._trash && prev._trash.id === pileId
        ? { ...prev, _trash: { ...prev._trash, status: 'processing', scan_duration_sec: data.scan_duration_sec, ready_at: data.ready_at, scanned_by: user?.id, reward_resource: data.reward_resource, reward_qty: data.reward_qty } }
        : prev);
    } catch (e) {
      toast.error(t('trashScanError') || 'Scan failed');
    } finally {
      trashActionBusyRef.current = false;
    }
  }, [t, fetchTrashPiles, user?.id]);

  const collectTrashPile = useCallback(async (pileId) => {
    if (trashActionBusyRef.current) return;
    trashActionBusyRef.current = true;
    const tok = localStorage.getItem('token') || localStorage.getItem('ton_city_token');
    try {
      const res = await fetch(`${API}/trash/${pileId}/collect`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${tok}` },
      });
      const data = await res.json();
      if (!res.ok) {
        const msg = res.status === 409 && data?.detail?.code === 'warehouse_full'
                  ? (t('trashWarehouseFull') || 'Personal warehouse is full')
                  : (data?.detail?.message || data?.detail || 'Collect failed');
        toast.error(typeof msg === 'string' ? msg : 'Collect failed');
        return;
      }
      const resName = getResourceName(data.resource, t, lang);
      toast.success(`+${data.qty} ${resName}`, {
        description: t('trashCollectedDesc') || 'Добавлено в ваши ресурсы',
      });
      await fetchTrashPiles();
      setSelectedCell(null);
    } catch (e) {
      toast.error(t('trashCollectError') || 'Collect failed');
    } finally {
      trashActionBusyRef.current = false;
    }
  }, [t, lang, fetchTrashPiles]);

  useEffect(() => {
    let active = true;
    const fetchSchedule = async () => {
      try {
        const res = await fetch(`${API}/trading-schedule`);
        if (!res.ok) return;
        const data = await res.json();
        if (active) { setTradingSchedule(data?.zones || {}); mapStore.dispatch({ type: 'SET_TRADING', trading: data?.zones || {} }); }
      } catch (_e) { /* ignore */ }
    };
    const fetchPresale = async () => {
      try {
        const res = await fetch(`${API}/presale/config`);
        if (!res.ok) return;
        const data = await res.json();
        if (active) setPresale(data || { active: false });
      } catch (_e) { /* ignore */ }
    };
    fetchSchedule();
    fetchPresale();
    // Refresh the schedule + presale every 60s in case admin updates it.
    const schedInterval = setInterval(() => { fetchSchedule(); fetchPresale(); }, 60000);
    const tickInterval = setInterval(() => setNowTs(Date.now()), 1000);
    return () => { active = false; clearInterval(schedInterval); clearInterval(tickInterval); };
  }, []);
  
  // Last user avatar for tracking changes
  const lastAvatarRef = useRef(user?.avatar);

  // ── Tutorial cleanup ──
  // When the tutorial transitions from active → inactive (finish/abandon/reset)
  // we MUST clear the stale `selectedCell` and re-fetch the island. Otherwise the
  // tutorial-only HELIOS overlay (`pre_business`, `business: {type:'helios'}`,
  // helios price) stays in the React state — including the Buy button — and
  // clicking Buy would purchase the underlying EMPTY GRAM-City cell without a
  // business attached, billing the user for an empty plot.
  const wasTutorialActiveRef = useRef(!!tutorial?.active);
  useEffect(() => {
    const wasActive = wasTutorialActiveRef.current;
    const isActive = !!tutorial?.active;
    if (wasActive && !isActive) {
      // Tutorial just ended → drop any tutorial-related cell/UI state.
      setSelectedCell(null);
      setShowBuildModal(false);
      // Re-fetch the island so the overlay (which is keyed off tutorial state)
      // is fully cleared from the rendered map as well.
      fetchIslandData(true);
    }
    wasTutorialActiveRef.current = isActive;
    // We intentionally do not include fetchIslandData in deps to avoid loops;
    // it is stable via useCallback and re-creating it doesn't matter here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tutorial?.active]);

  // v2.2.x: After leaving tutorial mode we show a one-time "legendary"
  // notification about the T3 reward — see <T3RewardBanner /> below.
  // The sessionStorage flag "tutorial_reward_banner" is set by the
  // TutorialContext on tutorial completion; the banner consumes it.

  // Track when modals close to delay outside-click detection
  const modalJustClosedRef = useRef(false);
  const pressInsideRef = useRef(false);
  
  // Close cell info panel when clicking/tapping outside the map area and info panel.
  // Guard: if the press STARTED inside the panel/map (mousedown/touchstart), do NOT
  // close on the following click — this prevents a mid-gesture re-render/remount from
  // dropping a button click and closing the panel instead (buy-button reliability).
  useEffect(() => {
    const isInside = (target) =>
      (cellInfoRef.current && cellInfoRef.current.contains(target)) ||
      (containerRef.current && containerRef.current.contains(target));
    const handlePressStart = (e) => { pressInsideRef.current = isInside(e.target); };
    const handleOutsideInteraction = (e) => {
      // Skip if a modal just closed (give time for info panel to appear)
      if (modalJustClosedRef.current) return;
      if (pressInsideRef.current) { pressInsideRef.current = false; return; }
      const target = e.target;
      if (selectedCell && 
          !showBuildModal &&
          cellInfoRef.current && !cellInfoRef.current.contains(target) &&
          containerRef.current && !containerRef.current.contains(target)) {
        setSelectedCell(null);
      }
    };
    document.addEventListener('mousedown', handlePressStart, true);
    document.addEventListener('touchstart', handlePressStart, { passive: true, capture: true });
    document.addEventListener('click', handleOutsideInteraction);
    document.addEventListener('touchend', handleOutsideInteraction, { passive: true });
    return () => {
      document.removeEventListener('mousedown', handlePressStart, true);
      document.removeEventListener('touchstart', handlePressStart, true);
      document.removeEventListener('click', handleOutsideInteraction);
      document.removeEventListener('touchend', handleOutsideInteraction);
    };
  }, [selectedCell, showBuildModal]);
  
  // When any modal closes, set a brief cooldown so info panel can appear
  useEffect(() => {
    if (!showBuildModal && selectedCell) {
      modalJustClosedRef.current = true;
      const timer = setTimeout(() => { modalJustClosedRef.current = false; }, 500);
      return () => clearTimeout(timer);
    }
  }, [showBuildModal]);
  
  const token = localStorage.getItem('token');

  // Generate hexagonal grid cells
  const generateCells = useCallback(() => {
    const cells = [];
    const centerQ = Math.floor(GRID_COLS / 2);
    const centerR = Math.floor(GRID_ROWS / 2);
    
    for (let r = 0; r < GRID_ROWS; r++) {
      for (let q = 0; q < GRID_COLS; q++) {
        // Offset for hexagonal shape (island form)
        const dist = Math.abs(q - centerQ) + Math.abs(r - centerR);
        if (dist > Math.min(GRID_COLS, GRID_ROWS) * 0.6) continue; // Island shape
        
        const zone = getZone(q, r, centerQ, centerR);
        const basePrice = { core: 50, inner: 30, middle: 15, outer: 5 }[zone] || 5;
        
        cells.push({
          q,
          r,
          zone,
          price: basePrice,
          owner: null,
          building: null,
        });
      }
    }
    
    return cells;
  }, []);

  // Fetch island data from server (silent mode for background refresh).
  //
  // Resilience: behind Cloudflare with aggressive rate-limit rules the very
  // first /api/island call right after a hard refresh can transiently return
  // 429/5xx — and the OLD code immediately fell back to `generateCells()`,
  // which paints a blank grid and effectively "loses" all businesses on the
  // map. Worse, the user-visible legend stayed because it's pure CSS. This
  // is precisely the symptom in screenshot #2.
  //
  // We now: (a) retry up to 3× with exponential backoff on 429/5xx, and
  // (b) never overwrite existing cells with the empty fallback grid — if the
  // request ultimately fails we just keep whatever was on screen and surface
  // a non-blocking toast so the user can hit refresh themselves.
  const fetchIslandData = useCallback(async (silent = false) => {
    const isTransient = (status) => status === 429 || (status >= 500 && status <= 599);
    const haveCellsAlready = () => {
      try { return (mapStore.getState?.()?.cells?.size || 0) > 0; } catch { return false; }
    };

    let res = null;
    let lastErr = null;
    for (let attempt = 0; attempt < 3; attempt += 1) {
      try {
        res = await fetch(`${API}/island`, { cache: 'no-store' });
        if (res.ok) break;
        if (!isTransient(res.status)) break;
      } catch (e) {
        lastErr = e;
      }
      const delay = 400 * Math.pow(2, attempt) + Math.floor(Math.random() * 200);
      await new Promise(r => setTimeout(r, delay));
    }

    if (res && res.ok) {
      try {
        const data = await res.json();
        // Ensure the skins index is loaded so businesses render with their skin.
        try { await fetchSkinsIndex(); } catch (_) {}
        const _skinsIdx = getCachedSkinsIndex();
        const _skinsSizes = getCachedSkinSizes();
        // v2.2.1: when the tutorial is active, overlay a HELIOS *preview*
        // on the user's reserved tutorial plot (an originally-empty GRAM-City
        // cell near the centre). This way the user sees the business they're
        // about to buy without us mutating any shared DB state.
        const tp = tutorial?.state?.tutorial_plot;
        const tutorialOverlayBiz = tp?.business_type || null;

        // Convert server data to our cell format
        mapStore.dispatch({ type: 'SET_LAYOUT', layout: data.parks ? { parks: data.parks, districts: data.districts, width: data.width } : null });
        fetch(`${API}/city/districts`).then((r) => (r.ok ? r.json() : null)).then((d) => d && mapStore.dispatch({ type: 'SET_DISTRICTS', districts: d })).catch(() => {});
        const cells = (data.cells || []).map(cell => {
          // Real (built) business takes priority; pre_business is just a "preview" icon
          // for unowned plots showing what kind of business CAN be built there.
          const hasRealBusiness = !!cell.business;
          // Tutorial overlay — only when the cell matches the reserved plot.
          const isTutorialPlot = tutorialOverlayBiz
            && tp && tp.x === cell.x && tp.y === cell.y
            && !hasRealBusiness && !cell.owner;
          const effectivePreBusiness = isTutorialPlot ? tutorialOverlayBiz : cell.pre_business;
          const hasPreviewBusiness = !hasRealBusiness && !!effectivePreBusiness && !cell.owner;
          const businessType = cell.business?.type || effectivePreBusiness;

          let building = null;
          if (hasRealBusiness) {
            const _skinGroup = cell.business?.skin_group || 'standard';
            const _lvl = cell.business?.level ?? 1;              // a level-0 (claimed) business stays level 0 (was `|| 1`)
            const _skinLvl = Math.max(1, _lvl);                 // its picture is the level-1 one
            building = {
              type: businessType,
              name: cell.business_name || data.businesses?.[businessType]?.name,
              icon: cell.business_icon || data.businesses?.[businessType]?.icon,
              level: _lvl,
              isZero: _lvl === 0 || !!cell.business?.is_zero_business,
              tier: cell.business_tier || cell.business?.tier || data.businesses?.[businessType]?.tier || 1,
              is_active: cell.business?.is_active !== false,
              durability: cell.business?.durability ?? 100,
              monthlyIncome: cell.monthly_income_city || 0,
              isPreview: false,
              shiftEndsAt: cell.business?.shift_ends_at || null,
              workReason: cell.business?.work_status_reason || null,
              skinGroup: _skinGroup,
              skinUrl: resolveSkinUrl(_skinsIdx, _skinGroup, businessType, _skinLvl),
              skinMeta: resolveSkinMeta(_skinGroup, businessType, _skinLvl),
              ...(() => { const _sz = resolveSkinSize(_skinsSizes, _skinGroup, businessType, _skinLvl); return { skinHeightPct: _sz.h, skinWidthPct: _sz.w }; })(),
            };
          } else if (hasPreviewBusiness) {
            building = {
              type: businessType,
              name: cell.business_name || data.businesses?.[businessType]?.name,
              icon: cell.business_icon || data.businesses?.[businessType]?.icon,
              level: 1,
              tier: cell.business_tier || data.businesses?.[businessType]?.tier || 1,
              is_active: true,
              durability: 100,
              monthlyIncome: cell.monthly_income_city || 0,
              isPreview: true,
            };
          }

          return {
            q: cell.x,
            r: cell.y,
            w: cell.w || 1, h: cell.h || 1,                    // lot size on the city map
            district: cell.district, slotId: cell.slot_id,
            zone: cell.zone,
            price: cell.price_city || cell.price || 0,
            priceTon: cell.price_ton || cell.price || 0,
            owner: cell.owner,
            ownerAvatar: cell.owner_avatar,
            ownerUsername: cell.owner_username,
            ownerAllianceTag: cell.owner_alliance_tag,
            // While the tutorial is overlaying a HELIOS preview on this cell
            // it should look like a buyable plot, not a "GRAM City" sign.
            isEmptyPlot: !isTutorialPlot && cell.is_empty === true,
            building,
          };
        });

        // Demo overlay: replace/insert the fixed demo plot [13,12] as an
        // owned cell carrying the user's avatar + their demo business.
        if (getGameMode() === 'demo') {
          const u = userRef.current || {};
          const dp = demoProfileRef.current;
          const db = dp && dp.demo_business;
          const demoCell = {
            q: DEMO_PLOT.x,
            r: DEMO_PLOT.y,
            zone: undefined,
            price: 0,
            priceTon: 0,
            owner: u.id || 'demo-self',
            ownerAvatar: u.avatar,
            ownerUsername: u.username || u.display_name || 'You',
            isEmptyPlot: false,
            building: db ? {
              type: db.type,
              name: db.name,
              icon: db.icon,
              level: db.level || 1,
              tier: db.tier || 1,
              is_active: true,
              durability: db.durability != null ? db.durability : 100,
              monthlyIncome: db.monthly_income_city || 0,
              isPreview: false,
            } : null,
          };
          const di = cells.findIndex(c => c.q === DEMO_PLOT.x && c.r === DEMO_PLOT.y);
          if (di >= 0) cells[di] = demoCell; else cells.push(demoCell);
        }

        // Store businesses config for reference
        if (data.businesses) {
          setBusinessTypes(data.businesses);
        }

        if (cells.length === 0 && !haveCellsAlready()) {
          // First-ever load with empty server response — show the placeholder
          // grid so the user isn't staring at a black screen.
          mapStore.dispatch({ type: 'SET_CELLS', cells: generateCells() });
        } else if (cells.length > 0) {
          mapStore.dispatch({ type: 'SET_CELLS', cells });
        }
        return;
      } catch (e) {
        lastErr = e;
      }
    }

    // ── Failure branch ──────────────────────────────────────────────────
    // CRITICAL: NEVER overwrite already-rendered cells with the empty grid.
    // That was the root cause of "refresh shows blank map" (screenshot #2).
    if (!silent) {
      console.error('Failed to fetch island after retries:', lastErr || res?.status);
    }
    if (!haveCellsAlready()) {
      // Only paint the placeholder grid if we have literally nothing on screen.
      mapStore.dispatch({ type: 'SET_CELLS', cells: generateCells() });
    }
    // Optional UX hint when the user-initiated refresh hits a wall.
    if (!silent && res && res.status === 429) {
      try {
        toast.error('Сервер временно ограничивает запросы. Попробуйте через несколько секунд.');
      } catch (_) { /* noop */ }
    }
  }, [generateCells, tutorial?.state?.tutorial_plot?.x, tutorial?.state?.tutorial_plot?.y, tutorial?.state?.tutorial_plot?.business_type]);

  // Instant map refresh when a player applies a new skin (from any page/modal)
  useEffect(() => {
    const onSkinApplied = () => {
      fetchSkinsIndex(true).then(() => fetchIslandData(true)).catch(() => {});
    };
    window.addEventListener('gc-skin-applied', onSkinApplied);
    return () => window.removeEventListener('gc-skin-applied', onSkinApplied);
  }, [fetchIslandData]);

  // Keep the map live: silently refetch every 20s and whenever the tab regains
  // focus, so plots/businesses changed by OTHER players appear without a manual
  // page refresh.
  useEffect(() => {
    const iv = setInterval(() => {
      if (document.visibilityState === 'visible') fetchIslandData(true);
    }, 20000);
    const onFocus = () => { if (document.visibilityState === 'visible') fetchIslandData(true); };
    document.addEventListener('visibilitychange', onFocus);
    window.addEventListener('focus', onFocus);
    return () => {
      clearInterval(iv);
      document.removeEventListener('visibilitychange', onFocus);
      window.removeEventListener('focus', onFocus);
    };
  }, [fetchIslandData]);


  // Fetch business types
  const fetchBusinessTypes = useCallback(async () => {
    try {
      const [typesRes, patronsRes] = await Promise.all([
        fetch(`${API}/businesses/types`).then(r => r.json()),
        fetch(`${API}/patrons`).then(r => r.json())
      ]);
      
      setBusinessTypes(typesRes.business_types || typesRes.businesses || typesRes || {});
      setPatrons(patronsRes.patrons || []);
    } catch (error) {
      console.error('Failed to fetch business types:', error);
    }
  }, []);

  // Fetch user's businesses (for limit checks on buy buttons)
  const fetchMyBusinesses = useCallback(async () => {
    if (!token) return;
    try {
      const res = await fetch(`${API}/users/me/businesses`, { headers: { Authorization: `Bearer ${token}` } });
      if (!res.ok) return;
      const data = await res.json();
      setMyBusinessesList(data.businesses || []);
      // how prices look on the map: a player without businesses takes a level-0 one,
      // a player with a level-0 business must upgrade first, others pay the normal price
      const list = data.businesses || [];
      const u = userRef.current || {};
      const viewer = list.length === 0 ? (u.has_graduated_zero ? 'level1' : 'newbie')
        : list.every((b) => (b.level || 0) === 0) ? 'zero' : 'level1';
      mapStore.dispatch({ type: 'SET_VIEWER', viewer });
    } catch (e) {
      console.error('Failed to fetch my businesses', e);
    }
  }, [token]);

  // Initialize map engine
  // IMPORTANT: depend ONLY on stable user IDENTITY fields, NOT the whole
  // `user` object. App.js mutates `user` on every balance update (refreshBalance,
  // balanceUpdate event, in-tutorial reward), creating a NEW object reference
  // each time. If we depend on `user`, the effect tears down and rebuilds the
  // PixiJS engine on every balance change, which races with in-flight texture
  // loads and produces the "first refresh: no icons → second refresh: wrong
  // map → third refresh: ok" symptom. Anchoring on `user?.id` keeps the engine
  // alive across balance updates; a separate effect below pushes balance/ID
  // changes into the map store without destroying anything.
  useEffect(() => {
    if (!containerRef.current) return;
    
    // Prevent double initialization in React Strict Mode
    let isMounted = true;
    
    const initEngine = async () => {
      if (!isMounted) return;
      
      setIsLoading(true);
      
      try {
        // Set user in store
        if (user) {
          mapStore.dispatch({
            type: 'SET_USER',
            userId: user.id,
            userWallet: user.wallet_address
          });
          setUserBalance((user.balance_ton || 0) + (user.bonus_balance || 0));
        }
        
        // Destroy existing engine if any
        if (engineRef.current) {
          engineRef.current.destroy();
          engineRef.current = null;
        }
        
        // Create engine
        const rect = containerRef.current.getBoundingClientRect();
        
        const engine = new CityMapEngine(containerRef.current, {
          width: rect.width,
          height: rect.height,
          // Stable thin wrappers — they delegate to refs so updates to the
          // React-side handleCellClick (e.g. when tutorial state changes)
          // take effect immediately without re-creating the engine.
          onCellClick: (cell) => handleCellClickRef.current?.(cell),
          onCellHover: (cell) => handleCellHoverRef.current?.(cell),
        });
        
        await engine.init();
        
        if (!isMounted) {
          engine.destroy();
          return;
        }
        
        engineRef.current = engine;
        
        // Now fetch data AFTER engine is initialized and subscribed
        await fetchDemoProfile();
        await fetchIslandData();
        fetchLandListings();
        await fetchBusinessTypes();
        await fetchMyBusinesses();
        
      } catch (error) {
        console.error('Error initializing map:', error);
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    };
    
    initEngine();
    
    return () => {
      isMounted = false;
      if (engineRef.current) {
        engineRef.current.destroy();
        engineRef.current = null;
      }
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id, user?.wallet_address]);

  // Push lightweight user-identity updates into the store WITHOUT recreating
  // the engine. We deliberately do NOT include balance here: the map only
  // cares about the userId/wallet (for owned-tile tint). Marking all cells
  // dirty on every balance update used to force a full setupAllTiles, which
  // was both wasteful and a source of the texture race.
  useEffect(() => {
    if (!engineRef.current || !user) return;
    mapStore.dispatch({
      type: 'SET_USER',
      userId: user.id,
      userWallet: user.wallet_address,
    });
  }, [user?.id, user?.wallet_address]);

  // Keep the local balance display in sync with the user prop (cheap update,
  // doesn't touch the map engine).
  useEffect(() => {
    if (user) setUserBalance((user.balance_ton || 0) + (user.bonus_balance || 0));
  }, [user?.balance_ton, user?.bonus_balance]);

  // Handle window resize
  useEffect(() => {
    const handleResize = () => {
      if (containerRef.current && engineRef.current) {
        const rect = containerRef.current.getBoundingClientRect();
        engineRef.current.resize(rect.width, rect.height);
      }
    };
    
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  // Tutorial: pulsating ring on the predetermined HELIOS plot during fake_buy_plot.
  // Auto-clears the moment the step changes / tutorial ends.
  // Also locks ALL camera input (drag/pinch/wheel-zoom) and centres the
  // highlighted plot on the screen so the user can't accidentally pan away.
  useEffect(() => {
    const eng = engineRef.current;
    if (!eng || typeof eng.setTutorialHighlight !== 'function') return;
    const onFakeBuy = tutorial?.active && tutorial?.currentStepId === 'fake_buy_plot';
    const tp = tutorial?.state?.tutorial_plot;
    if (onFakeBuy && tp && tp.x !== undefined && tp.y !== undefined) {
      eng.setTutorialHighlight({ x: tp.x, y: tp.y });
      // Pan the camera so the highlighted cell sits in the centre of the
      // map viewport. The tutorial card is now docked at the bottom of the
      // window (TutorialTour uses fixed bottom positioning), so the cell
      // stays visible above the card on every screen size.
      try {
        const rect = containerRef.current?.getBoundingClientRect?.();
        const sx = rect ? rect.width  / 2 : (window.innerWidth  / 2);
        const sy = rect ? rect.height * 0.45 : (window.innerHeight * 0.4);
        eng.panToCell?.(tp.x, tp.y, 1.6, sx, sy);
      } catch { /* noop */ }
      // Hard-lock pan/zoom — single click on the highlighted cell still works.
      eng.setInteractionLock?.(true);
    } else {
      eng.clearTutorialHighlight?.();
      eng.setInteractionLock?.(false);
    }
    return () => {
      eng?.clearTutorialHighlight?.();
      eng?.setInteractionLock?.(false);
    };
  }, [tutorial?.active, tutorial?.currentStepId, tutorial?.state?.tutorial_plot?.x, tutorial?.state?.tutorial_plot?.y, isLoading]);

  // Removed automatic refresh - data will be fetched on cell click instead
  // This prevents race conditions where multiple users might buy the same cell

  // Track avatar changes and refresh map when avatar changes
  useEffect(() => {
    if (user?.avatar && user.avatar !== lastAvatarRef.current) {
      lastAvatarRef.current = user.avatar;
      // Refresh map data silently when avatar changes
      if (engineRef.current) {
        fetchIslandData(true);
      }
    }
  }, [user?.avatar, fetchIslandData]);

  // Fetch fresh cell data from server before showing modal
  const fetchCellData = useCallback(async (cellX, cellY) => {
    try {
      const token = localStorage.getItem('token') || localStorage.getItem('ton_city_token');
      const response = await fetch(`${API}/island/cell/${cellX}/${cellY}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {}
      });
      if (response.ok) {
        return await response.json();
      }
    } catch (err) {
      console.error('Failed to fetch cell data:', err);
    }
    return null;
  }, []);

  // Handle cell click - fetch fresh data first
  const handleCellClick = useCallback(async (cell) => {
    if (!cell) return;
    try { setSelectedSprite(engineRef.current?.spriteUrl?.(cell) || null); } catch (_) { setSelectedSprite(null); }
    
    // Get coordinates (support both q/r and x/y formats)
    const cellX = cell.x !== undefined ? cell.x : (cell.q !== undefined ? cell.q : null);
    const cellY = cell.y !== undefined ? cell.y : (cell.r !== undefined ? cell.r : null);
    
    // Skip if no valid coordinates
    if (cellX === null || cellY === null) {
      console.warn('Cell click with invalid coordinates:', cell);
      return;
    }

    // ── Demo (Sandbox) mode ──
    // The fixed demo plot [13,12] shows the user's OWN demo business. Every
    // other cell behaves exactly like REAL mode (full info panel + Buy button)
    // — but pressing Buy opens the "leave demo & buy" conversion modal instead
    // of a real purchase (handled in handleBuyClick).
    if (getGameMode() === 'demo' && cellX === DEMO_PLOT.x && cellY === DEMO_PLOT.y) {
      const u = userRef.current || {};
      const db = demoProfileRef.current && demoProfileRef.current.demo_business;
      setSelectedCell({
        x: cellX, y: cellY, q: cellX, r: cellY,
        owner: u.id || 'demo-self',
        owner_username: u.username || u.display_name || 'You',
        ownerUsername: u.username || u.display_name || 'You',
        owner_avatar: u.avatar, ownerAvatar: u.avatar,
        is_empty: false,
        building: db ? { type: db.type, tier: db.tier || 1, level: db.level || 1 } : null,
        business: db ? { type: db.type, tier: db.tier || 1, level: db.level || 1 } : null,
        business_name: db && db.name, business_icon: db && db.icon,
        _demo: true,
      });
      return;
    }

    // Tutorial: during the WHOLE tutorial (any step), lock the user to the
    // predetermined HELIOS plot — clicking any other plot is a no-op (toast).
    // The buy/build UI for other plots is also hidden via `tutorialBlocksCell`
    // (see render below), but this is the belt-and-braces server-event guard.
    if (tutorial?.active) {
      const tp = tutorial?.state?.tutorial_plot;
      if (!tp || cellX !== tp.x || cellY !== tp.y) {
        toast.info('🎓 ' + (t('tutorialOnlyHelios') || 'Только подсвеченный участок с HELIOS доступен для покупки во время обучения.'));
        return;
      }
    }

    // Fetch fresh cell data from server to prevent race conditions
    const freshData = await fetchCellData(cellX, cellY);
    let cellToUse = freshData || cell;
    
    // Update cell in local state if we got fresh data
    if (freshData && engineRef.current) {
      // Convert API format (x,y) to engine format (q,r)
      const cellForEngine = {
        q: freshData.x,
        r: freshData.y,
        ...freshData,
        // the server's names → the map's names (the map reads ownerUsername / ownerAvatar / ownerAllianceTag)
        owner: freshData.owner || null,
        ownerUsername: freshData.owner_username,
        ownerAvatar: freshData.owner_avatar,
        ownerAllianceTag: freshData.owner_alliance_tag,
      };
      mapStore.dispatch({ type: 'UPDATE_CELL', cell: cellForEngine });
    }

    // Tutorial overlay: during fake_buy_plot the reserved GRAM-City-owned cell
    // must look like a buyable HELIOS plot (not the "owner: GRAM City" panel).
    // We override the selectedCell ONLY for the info panel — the real plot in
    // the DB stays unchanged and the map UPDATE_CELL above uses raw freshData.
    if (tutorial?.active && tutorial?.currentStepId === 'fake_buy_plot') {
      const tp = tutorial?.state?.tutorial_plot;
      if (tp && cellX === tp.x && cellY === tp.y) {
        const heliosCfg = businessTypes?.helios || {};
        const heliosPriceTon = heliosCfg.price_ton || 6.5;
        cellToUse = {
          ...cellToUse,
          x: cellX,
          y: cellY,
          is_empty: false,
          owner: null,
          owner_username: null,
          owner_avatar: null,
          ownerUsername: null,
          ownerAvatar: null,
          pre_business: 'helios',
          business: { type: 'helios', tier: 1, level: 1 },
          business_name: heliosCfg.name || { ru: 'Helios', en: 'Helios' },
          business_icon: heliosCfg.icon || '☀️',
          business_tier: 1,
          price_ton: heliosPriceTon,
          priceTon: heliosPriceTon,
          price_city: tonToCity(heliosPriceTon),
          monthly_income_city: tonToCity(heliosCfg.monthly_income_ton || heliosPriceTon),
        };
      }
    }

    setSelectedCell(cellToUse);
    
    // Priority: if no owner, show info panel with buy button
    if (!cellToUse.owner) {
      // info panel (with buy button) will show automatically via selectedCell state
    } else if (cellToUse.owner === user?.id || cellToUse.owner === user?.wallet_address) {
      // Own plot - show build modal if empty, info panel if has business
      if (cellToUse.building || cellToUse.pre_business) {
        // Info panel shows automatically via selectedCell state
      } else {
        // Suppress build modal during tutorial — user must stay on the tutorial flow.
        if (!tutorial?.active) {
          setShowBuildModal(true);
        }
      }
    } else {
      // Other player's cell - info panel shows business details automatically
      if (!cellToUse.building && !cellToUse.pre_business) {
        toast.info(t('plotBelongsToOther'));
      }
    }
  }, [user, fetchCellData, t, tutorial?.active, tutorial?.state?.tutorial_plot?.x, tutorial?.state?.tutorial_plot?.y, tutorial?.currentStepId, businessTypes]);

  // Handle cell hover
  const handleCellHover = useCallback((cell) => {
    // Optional: show tooltip or update UI
  }, []);

  // Keep imperative-engine handler refs fresh so the click handler always sees
  // the latest tutorial state (engine only reads onCellClick from its options).
  useEffect(() => {
    handleCellClickRef.current = handleCellClick;
    if (typeof window !== 'undefined') {
      // eslint-disable-next-line no-underscore-dangle
      window.__handleCellClick = handleCellClick;
    }
  }, [handleCellClick]);
  useEffect(() => {
    handleCellHoverRef.current = handleCellHover;
  }, [handleCellHover]);

  // After leaving demo via the conversion modal we reload into REAL mode with a
  // pending target cell — auto-open its info panel (with Buy) once loaded.
  useEffect(() => {
    if (isLoading) return;
    if (getGameMode() !== 'real') return;
    let raw = null;
    try { raw = localStorage.getItem('ton_city_pending_cell'); } catch (e) { return; }
    if (!raw) return;
    try { localStorage.removeItem('ton_city_pending_cell'); } catch (e) { /* ignore */ }
    let coords = null;
    try { coords = JSON.parse(raw); } catch (e) { return; }
    if (!coords || coords.x == null || coords.y == null) return;
    const timer = setTimeout(() => {
      handleCellClickRef.current?.({ q: coords.x, r: coords.y });
    }, 900);
    return () => clearTimeout(timer);
  }, [isLoading]);


  // Update local balance when user changes from App.js
  useEffect(() => {
    if (user?.balance_ton !== undefined) {
      setUserBalance((user.balance_ton || 0) + (user.bonus_balance || 0));
    }
  }, [user?.balance_ton, user?.bonus_balance]);

  // Refresh balance periodically and after actions
  const refreshUserBalance = useCallback(async () => {
    if (!token) return;
    try {
      const res = await fetch(`${API}/auth/me`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setUserBalance((data.balance_ton || 0) + (data.bonus_balance || 0));
      }
    } catch (error) {
      console.error('Failed to refresh balance:', error);
    }
  }, [token]);

  // Handle purchase with optimistic update + refresh
  const handlePurchase = async () => {
    if (!selectedCell || !token) return;
    
    const cellX = selectedCell.q !== undefined ? selectedCell.q : selectedCell.x;
    const cellY = selectedCell.r !== undefined ? selectedCell.r : selectedCell.y;
    
    // Tutorial fake buy plot: intercept during fake_buy_plot step
    if (tutorial?.active && tutorial?.currentStepId === 'fake_buy_plot') {
      setIsPurchasing(true);
      try {
        const zone = selectedCell.zone || 'outskirts';
        const biz_icon = selectedCell.business_icon || '🏭';
        const res = await tutorial.fakeBuyPlot({ x: cellX, y: cellY, zone, business_icon: biz_icon });
        if (!res.ok) {
          toast.error(res.error || 'Tutorial action failed');
        } else {
          toast.success('🎓 Tutorial plot acquired!');
          setSelectedCell(null);
        }
      } finally {
        setIsPurchasing(false);
      }
      return;
    }

    setIsPurchasing(true);
    try {
      await executePurchase();
    } catch (error) {
      toast.error(error.message);
      // Refresh balance to get actual value on error
      if (refreshBalance) refreshBalance();
    } finally {
      setIsPurchasing(false);
    }
  };

  // Actual plot purchase (network call + local state sync). Extracted so it can
  // be triggered both directly (sufficient balance) and after a successful
  // top-up from LandPurchaseTopUpModal. Accepts an explicit cell so the flow is
  // resilient to `selectedCell` being reset by re-renders during the top-up.
  // Throws on failure so callers can react.
  const executePurchase = async (cellArg) => {
    const targetCell = cellArg || selectedCell;
    if (!targetCell || !token) return;

    const cellX = targetCell.q !== undefined ? targetCell.q : targetCell.x;
    const cellY = targetCell.r !== undefined ? targetCell.r : targetCell.y;

    const res = await fetch(`${API}/island/buy/${cellX}/${cellY}`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` }
    });

    if (!res.ok) {
      const err = await res.json();
      if (res.status === 423 || err?.detail?.code === 'zero_locked') {
        throw new Error(ZERO_I18N[lang]?.locked || ZERO_I18N.en.locked);
      }
      const _d = err?.detail;
      throw new Error(formatErrorDetail(_d) || 'Purchase failed');
    }

    const data = await res.json();

    // Immediately update balance with server response (use TON for display, convert to CITY internally)
    const newBalanceTon = data.new_balance_ton !== undefined ? data.new_balance_ton : (userBalance - (targetCell.price_ton || targetCell.price || 0));
    setUserBalance(newBalanceTon);

    // Update global balance in App.js
    if (updateBalance) {
      updateBalance(newBalanceTon);
    }

    // Update local state map - mark cell as owned
    const _buyIdx = getCachedSkinsIndex();
    const _buySizes = getCachedSkinSizes();
    let _boughtBuilding = null;
    if (data.business) {
      const _bt = data.business.type || data.business.business_type;
      const _bg = data.business.skin_group || 'standard';
      const _buySz = resolveSkinSize(_buySizes, _bg, _bt, data.business.level ?? 1);
      _boughtBuilding = {
        ...data.business,
        type: _bt,
        level: data.business.level ?? 1,
        isPreview: false,
        skinGroup: _bg,
        skinUrl: resolveSkinUrl(_buyIdx, _bg, _bt, data.business.level ?? 1),
        skinHeightPct: _buySz.h,
        skinWidthPct: _buySz.w,
      };
    }
    mapStore.dispatch({
      type: 'UPDATE_CELL',
      cell: {
        q: cellX,
        r: cellY,
        ...targetCell,
        owner: user?.id,
        ownerUsername: user?.username,
        ownerAvatar: user?.avatar,
        building: _boughtBuilding
      }
    });

    // Refresh island data to ensure consistency
    await fetchIslandData(true);
    // Refresh local list of businesses for limit checks
    await fetchMyBusinesses();

    if (data.is_zero_business) {
      toast.warning(ZERO_I18N[lang]?.claimed || ZERO_I18N.en.claimed, { duration: 10000 });
    } else {
      toast.success(t('plotPurchased'));
    }

    setSelectedCell(null);
  };

  // Buy button click: proceed directly if the user can afford it, otherwise
  // open the top-up modal (which handles wallet linking + payment + purchase).
  const handleBuyClick = () => {
    // Level-0 gate: holding a Lv.0 business blocks buying anything else.
    const hasZeroBiz = (myBusinessesList || []).some(b => !b.is_trial && ((b.level ?? 1) === 0 || b.is_zero_business));
    if (hasZeroBiz && !user?.is_admin) {
      toast.error(ZERO_I18N[lang]?.locked || ZERO_I18N.en.locked);
      return;
    }
    // In demo mode, buying a real plot requires leaving the sandbox first.
    if (getGameMode() === 'demo') {
      setDemoConvertCell(selectedCell);
      setShowDemoConvertModal(true);
      return;
    }
    // Level-0 (застолблённый) claim is FREE (price 0): a brand-new user with a
    // low/zero balance must be able to claim regardless of the cell's map price.
    const canStakeZero = (myBusinessesList?.length || 0) === 0 && !user?.has_graduated_zero && !!(selectedCell?.pre_business || selectedCell?.business?.type);
    if (canStakeZero) {
      handlePurchase();
      return;
    }
    const priceTon = selectedCell?.priceTon || selectedCell?.price_ton || selectedCell?.price || 0;
    if ((userBalance || 0) < priceTon) {
      setShowTopUpModal(true);
    } else {
      handlePurchase();
    }
  };

  // Confirm "leave demo & buy this plot": exit demo, remember the target cell,
  // reload into REAL mode where the cell's info panel (with Buy) auto-opens.
  const confirmDemoConvert = async () => {
    const cell = demoConvertCell;
    const cx = cell?.q != null ? cell.q : cell?.x;
    const cy = cell?.r != null ? cell.r : cell?.y;
    setIsConverting(true);
    // Flip local mode + remember target FIRST so the reload always lands in
    // REAL mode even if the network call is slow/blocked.
    setGameMode('real');
    try {
      if (cx != null && cy != null) {
        localStorage.setItem('ton_city_pending_cell', JSON.stringify({ x: cx, y: cy }));
      }
      localStorage.setItem('ton_city_mode_toast', 'real');
    } catch (e) { /* ignore */ }
    const tok = localStorage.getItem('token');
    try {
      await Promise.race([
        fetch(`${API}/demo/exit`, { method: 'POST', headers: tok ? { Authorization: `Bearer ${tok}` } : {} }),
        new Promise((r) => setTimeout(r, 1500)),
      ]);
    } catch (e) { /* ignore — still exit locally */ }
    window.location.reload();
  };

  // Build business
  const handleBuild = async () => {
    if (!selectedCell || !selectedBusinessType || !token) return;
    
    setIsBuilding(true);
    try {
      const res = await fetch(`${API}/island/build/${selectedCell.q}/${selectedCell.r}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({
          business_type: selectedBusinessType,
          patron_id: selectedPatron === 'none' ? null : (selectedPatron || null)
        })
      });
      
      if (!res.ok) {
        const err = await res.json();
        if (res.status === 423 || err?.detail?.code === 'zero_locked') {
          throw new Error(ZERO_I18N[lang]?.locked || ZERO_I18N.en.locked);
        }
        const _d = err?.detail;
        throw new Error(formatErrorDetail(_d) || 'Build failed');
      }
      
      const data = await res.json();
      
      // Update balance with server response
      if (data.new_balance !== undefined) {
        setUserBalance(data.new_balance);
        if (updateBalance) updateBalance(data.new_balance);
      }
      
      // Update local state
      const bizConfig = businessTypes[selectedBusinessType];
      const _idx = getCachedSkinsIndex();
      const _bSz = resolveSkinSize(getCachedSkinSizes(), 'standard', selectedBusinessType, 1);
      mapStore.dispatch({
        type: 'UPDATE_CELL',
        cell: {
          ...selectedCell,
          building: {
            type: selectedBusinessType,
            level: 1,
            tier: bizConfig?.tier || 1,
            is_active: true,
            isPreview: false,
            // Resolve the skin immediately so the map shows the business sprite
            // right away instead of briefly flashing the owner avatar.
            skinGroup: 'standard',
            skinUrl: resolveSkinUrl(_idx, 'standard', selectedBusinessType, 1),
            skinHeightPct: _bSz.h,
            skinWidthPct: _bSz.w,
          }
        }
      });
      
      if (data.is_zero_business) {
        toast.warning(ZERO_I18N[lang]?.claimed || ZERO_I18N.en.claimed, { duration: 10000 });
      } else {
        toast.success(t('businessBuilt'));
      }
      setShowBuildModal(false);
      setSelectedBusinessType('');
      
    } catch (error) {
      toast.error(error.message);
      // Refresh balance on error
      if (refreshBalance) refreshBalance();
    } finally {
      setIsBuilding(false);
    }
  };

  // Zoom controls
  const handleZoomIn = () => {
    if (engineRef.current) {
      engineRef.current.zoomIn();
    }
  };

  const handleZoomOut = () => {
    if (engineRef.current) {
      engineRef.current.zoomOut();
    }
  };

  const handleResetCamera = () => {
    if (engineRef.current) {
      engineRef.current.resetCamera();
    }
  };

  // Refresh data
  const handleRefresh = async () => {
    setIsLoading(true);
    // P1 (zoom): re-arm the initial-view logic so after the data reloads the
    // camera shows the SAME zoom as a full site refresh (instead of resetting
    // to the plain auto-fit that subsequent refreshes used).
    if (engineRef.current) engineRef.current.applyInitialView();
    await fetchIslandData();
    await fetchBusinessTypes();
    setIsLoading(false);
    toast.success(t('dataRefreshed') || 'Data refreshed');
  };

  return (
    <div
      className="flex h-screen bg-void overflow-hidden"
      style={{ paddingTop: 'var(--tg-safe-top, 0px)' }}
    >
      <Sidebar user={user} />
      
      <div className="flex-1 flex flex-col lg:ml-16 overflow-hidden">
        {/* Header - Mobile Adapted.
            v2.2.X: on PC we tighten the top padding (lg:pt-1) so the
            header sits flush with the window controls of Telegram Desktop
            and gives the map more vertical real-estate. */}
        <div className="flex-shrink-0 p-4 pt-4 lg:pt-1 lg:pb-2 border-b border-white/10 bg-void/95 backdrop-blur-sm z-20">
          <div className="flex items-center justify-between">
            <div className="flex-1 min-w-0">
              <h1 className="font-unbounded text-lg lg:text-xl font-bold text-white flex items-center gap-2 truncate">
                <MapPin className="w-5 h-5 lg:w-6 lg:h-6 text-cyber-cyan flex-shrink-0" />
                <span className="truncate">{t('mapTitle')}</span>
              </h1>
              <p className="text-text-muted text-xs lg:text-sm truncate">
                {t('sidebarBalance')}: {formatCity(tonToCity(userBalance))} $CITY
              </p>
            </div>
            
            <div className="flex items-center gap-2 flex-shrink-0 lg:mr-32">
              <Button 
                onClick={handleRefresh} 
                variant="outline" 
                size="sm" 
                className="border-white/10 w-9 h-9 p-0"
                disabled={isLoading}
              >
                <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
              </Button>
              
              <Button
                data-testid="night-mode-toggle"
                onClick={() => {
                  const isNight = !mapStore.getState().isNight;
                  if (engineRef.current) engineRef.current.setNightMode(isNight);
                }}
                variant="outline"
                size="sm"
                className="border-white/10 bg-indigo-900/20 text-indigo-300 hover:bg-indigo-900/40 w-9 h-9 p-0"
              >
                🌙
              </Button>
            </div>
          </div>
        </div>

        {/* v2.2.x: one-time legendary reward notification, rendered DIRECTLY
            below the map header (used to overlap the top of the sidebar). */}
        <T3RewardBanner />

        {/* Legendary referral-invite popup — shown on first login after
            existing user auth (не при регистрации), а также после первого
            прохождения/пропуска обучения (сразу после бонуса T3). */}
        <ReferralInvitePopup user={user} />

        {/* Map Container */}
        <div className="flex-1 relative overflow-hidden">
          {/* Pixi.js Canvas Container */}
          <div 
            ref={containerRef} 
            className="w-full h-full"
            style={{ touchAction: 'none' }}
          />

          {/* Trash-pile layer: renders trash.webp on every server-side pile,
              pulses a 📦 badge on my ready ones, and opens the info panel on click. */}
          <GramIslandTrashLayer
            engineRef={engineRef}
            piles={trashPiles}
            onPileClick={handleTrashClick}
            currentUserId={user?.id}
          />
          
          {/* Loading Overlay */}
          {isLoading && (
            <div className="absolute inset-0 flex items-center justify-center bg-void/80 z-30">
              <div className="text-center">
                <Loader2 className="w-12 h-12 text-cyber-cyan animate-spin mx-auto mb-4" />
                <p className="text-white">{t('loadingMap')}</p>
              </div>
            </div>
          )}
          
          {/* Zoom Controls */}
          <div className="absolute bottom-[calc(var(--bottom-nav-h,50px)+16px)] md:bottom-4 right-4 flex flex-col gap-2 z-20">
            {/* new map: jump between own buildings · show only lots on sale */}
            <Button
              onClick={() => { const n = engineRef.current?.focusNextMine?.(); if (n === 0) toast.info(t('map_no_businesses')); }}
              variant="outline" size="icon" title={t('map_my_businesses')}
              className="bg-black/60 border-orange-400/50 hover:bg-black/80 text-orange-300 font-bold"
              data-testid="map-my-businesses"
            >★</Button>
            <Button
              onClick={() => setSaleOnly((v) => { const nv = !v; engineRef.current?.setSaleFilter?.(nv); if (nv) fetchLandListings(); return nv; })}
              variant="outline" size="icon" title={t('map_what_for_sale')}
              className={`border-white/20 hover:bg-black/80 font-bold ${saleOnly ? 'bg-emerald-500/30 text-emerald-200 border-emerald-400/60' : 'bg-black/60 text-white/70'}`}
              data-testid="map-sale-filter"
            >%</Button>

            <Button
              onClick={handleZoomIn}
              variant="outline"
              size="icon"
              className="bg-black/60 border-white/20 hover:bg-black/80"
            >
              <ZoomIn className="w-4 h-4" />
            </Button>
            <Button
              onClick={handleZoomOut}
              variant="outline"
              size="icon"
              className="bg-black/60 border-white/20 hover:bg-black/80"
            >
              <ZoomOut className="w-4 h-4" />
            </Button>
            <Button
              onClick={handleResetCamera}
              variant="outline"
              size="icon"
              className="bg-black/60 border-white/20 hover:bg-black/80"
            >
              <Home className="w-4 h-4" />
            </Button>
          </div>

          {/* Legend of the new map (desktop only; on phones the map has no room for it) */}
          <div className="absolute top-4 left-4 hidden lg:block bg-slate-900/90 backdrop-blur-md rounded-xl p-3 text-xs space-y-1.5 z-20 w-[200px] border border-slate-700/50 shadow-xl" data-testid="map-legend">
            <div className="font-bold text-white mb-1 flex items-center gap-2">
              <MapPin className="w-4 h-4 text-sky-400" />
              {t('legend') || 'Legend'}
            </div>
            {[
              { k: 'mine', el: <span className="px-1.5 rounded-full text-[10px] font-extrabold" style={{ background: '#ff8a00', color: '#1a0d00' }}>★</span>, txt: t('map_lg_mine') },
              { k: 'free', el: <span className="w-4 h-3 rounded-sm border-2" style={{ borderColor: '#39ff88', background: 'rgba(57,255,136,0.25)' }} />, txt: t('map_lg_free') },
              { k: 'closed', el: <span className="text-[12px] leading-none">🔒</span>, txt: t('map_lg_closed') },
            ].map((r) => (
              <div key={r.k} className="flex items-center gap-2"><span className="w-6 flex justify-center">{r.el}</span><span className="text-white/90">{r.txt}</span></div>
            ))}
            <div className="h-px bg-slate-600/50 my-1.5" />
            <div className="text-sky-400/90 text-[10px] font-semibold tracking-wide">{t('map_lg_sale_mode')}</div>
            {[
              { k: 'city', bg: '#1fd17a', fg: '#032313', sym: '%', txt: t('map_lg_city') },
              { k: 'market', bg: '#ffb347', fg: '#2a1500', sym: '%', txt: t('map_lg_market') },
              { k: 'rent', bg: '#22d3ee', fg: '#022a33', sym: '⟳', txt: t('map_lg_rent') },
            ].map((r) => (
              <div key={r.k} className="flex items-center gap-2">
                <span className="w-6 flex justify-center"><span className="px-1.5 rounded-full text-[10px] font-extrabold" style={{ background: r.bg, color: r.fg }}>{r.sym}</span></span>
                <span className="text-white/80">{r.txt}</span>
              </div>
            ))}
          </div>

          {/* Selected Cell Info - slides from right on desktop, up from bottom on mobile */}
          <AnimatePresence>
          {selectedCell && !showBuildModal && (
            <motion.div
              ref={cellInfoRef}
              key="cell-info-panel"
              initial={isMobile ? { y: "100%", opacity: 0 } : { x: "100%", opacity: 0 }}
              animate={isMobile ? { y: 0, opacity: 1 } : { x: 0, opacity: 1 }}
              exit={isMobile ? { y: "100%", opacity: 0 } : { x: "100%", opacity: 0 }}
              transition={{ type: "spring", damping: 28, stiffness: 320 }}
              className="absolute bottom-0 left-0 right-0 md:bottom-auto md:left-auto md:top-4 md:right-4 bg-black/90 backdrop-blur-sm rounded-t-2xl md:rounded-xl p-4 pb-[calc(var(--bottom-nav-h,96px)+16px)] md:pb-4 max-h-[calc(100dvh-var(--tg-safe-top,0px)-80px)] overflow-y-auto text-sm z-20 md:min-w-[280px] md:max-w-[320px] overflow-hidden"
            >
              <button 
                onClick={() => setSelectedCell(null)} 
                className="absolute top-2 right-2 text-gray-400 hover:text-white transition-colors"
                data-testid="close-cell-info"
              >
                <X className="w-5 h-5" />
              </button>
              <div className="text-cyber-cyan font-bold mb-2">
                {t('coordinates')}: [{selectedCell.q || selectedCell.x}, {selectedCell.r || selectedCell.y}]
              </div>
              <div className="space-y-1 text-white/80">
                <div>{t('zone')}: <span className="text-white capitalize">{getZoneName(selectedCell.zone, t)}</span></div>
                
                {/* Business info - show for any cell with business */}
                {(selectedCell.pre_business || selectedCell.business?.type) && (() => {
                  const bizType = selectedCell.pre_business || selectedCell.business?.type;
                  const bizLevel = selectedCell.business?.level ?? selectedCell.level ?? 1;
                  const bizTier = selectedCell.business_tier || selectedCell.business?.tier || 1;
                  const produces = selectedCell.business?.produces || (businessTypes?.[bizType]?.produces) || bizType;
                  const resInfo = produces ? getResource(produces, lang) : null;
                  const baseProduction = selectedCell.business?.base_production || selectedCell.building?.base_production || businessTypes?.[bizType]?.base_production || '';
                  return (
                  <div className="mt-2 pt-2 border-t border-white/20">
                    <div className="text-text-muted text-xs mb-1">{t('business') || 'Бизнес'}:</div>
                    <div className="flex items-center gap-2 mb-2">
                      {selectedSprite
                        ? <img src={selectedSprite} alt="" className="w-16 h-16 object-contain shrink-0 drop-shadow-[0_4px_10px_rgba(0,240,255,0.25)]" data-testid="cell-info-sprite" />
                        : <span className="text-2xl">{selectedCell.business_icon || selectedCell.business?.icon || '🏢'}</span>}
                      <div>
                        <div className="text-purple-400 font-bold">
                          {tBusiness(bizType, lang) || (typeof (selectedCell.business_name || selectedCell.business?.name) === 'object' 
                            ? ((selectedCell.business_name || selectedCell.business?.name)?.[lang] || (selectedCell.business_name || selectedCell.business?.name)?.ru || (selectedCell.business_name || selectedCell.business?.name)?.en) 
                            : (selectedCell.business_name || selectedCell.business?.name || selectedCell.pre_business || selectedCell.business?.type))}
                        </div>
                        <div className="flex items-center gap-2 text-xs text-gray-400">
                          <span>{t('tierLabel')} {bizTier}</span>
                          <span>•</span>
                          <span data-testid="biz-level-label">{bizLevel === 0 ? (ZERO_I18N[lang]?.lv0 || 'Lv.0') : `Lv. ${bizLevel}`}</span>
                        </div>
                      </div>
                    </div>
                    {resInfo && (
                      <div className="text-xs mt-1 space-y-0.5">
                        <div className="flex items-center gap-1">
                          <span className="text-text-muted">{t('produces') || 'Производит'}:</span>
                          <span>{resInfo.icon}</span>
                          <span className={resInfo.textColor}>{resInfo.name}</span>
                        </div>
                        {baseProduction && (
                          <div className="flex items-center gap-1">
                            <span className="text-text-muted">{t('quantity') || 'Количество'}:</span>
                            <span className="text-green-400">{baseProduction} {t('unitsPerDayShort') || 'ед./сутки'}</span>
                          </div>
                        )}
                        {/* Consumption info */}
                        {(() => {
                          const consumes = selectedCell.business?.consumes || businessTypes?.[bizType]?.consumes || {};
                          const entries = Array.isArray(consumes) 
                            ? consumes.map(c => [c.resource || c.type, c.amount || c.rate || 0])
                            : Object.entries(consumes);
                          return entries.length > 0 && entries.map(([res, amt], i) => {
                            const consumeRes = getResource(res, lang);
                            return (
                              <div key={i} className="flex items-center gap-1">
                                <span className="text-text-muted">{t('consumes') || 'Потребляет'}:</span>
                                <span>{consumeRes?.icon || '📦'}</span>
                                <span className="text-red-400">{consumeRes?.name || res} {amt} {t('unitsPerDayShort') || 'ед./сутки'}</span>
                              </div>
                            );
                          });
                        })()}
                      </div>
                    )}
                  </div>
                  );
                })()}
                
                {/* Level-0 (застолблённый) business owned by another player → buy it directly from the map cell */}
                {selectedCell.business?.is_zero_business && selectedCell.business?.owner_id && user?.id !== selectedCell.business?.owner_id && (
                  <div className="mt-2 pt-2 border-t border-white/20" data-testid="zero-business-buy-panel">
                    <div className="flex justify-between text-xs mb-3">
                      <span className="text-gray-400">{t('price')}:</span>
                      <span className="text-yellow-400 font-bold">{formatCity(selectedCell.business?.zero_price_city || 0)} $CITY</span>
                    </div>
                    <Button
                      onClick={async () => {
                        const lid = selectedCell.business?.zero_listing_id;
                        if (!lid || !token) return;
                        try {
                          const r = await fetch(`${API}/market/land/buy`, { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }, body: JSON.stringify({ listing_id: lid }) });
                          const d = await r.json();
                          if (!r.ok) {
                            if (r.status === 423) throw new Error(ZERO_I18N[lang]?.locked || ZERO_I18N.en.locked);
                            throw new Error(formatErrorDetail(d.detail) || 'Purchase failed');
                          }
                          toast.success(ZERO_I18N[lang]?.bought || ZERO_I18N.en.bought);
                          await fetchIslandData(true);
                          await fetchMyBusinesses();
                          if (refreshBalance) refreshBalance();
                          setSelectedCell(null);
                        } catch (e) { toast.error(e.message); }
                      }}
                      className="w-full bg-yellow-500 hover:bg-yellow-600 text-black font-bold"
                      data-testid="zero-business-buy-btn"
                    >
                      <Coins className="w-4 h-4 mr-2" />{t('buy')}
                    </Button>
                  </div>
                )}
                
                {/* Owner info or "Available" */}
                <div className="mt-2 pt-2 border-t border-white/20">
                  {(() => {
                    // If this cell has an active/processing/ready trash pile,
                    // show a special "Завал" section INSTEAD of the owner block.
                    const cx = selectedCell.q ?? selectedCell.x;
                    const cy = selectedCell.r ?? selectedCell.y;
                    // Prefer the freshest data from the polled list (it carries
                    // the reward once the pile is 'ready'), merged over the
                    // pile captured at click time so nothing is lost mid-scan.
                    const stale = selectedCell._trash;
                    const fresh = trashPiles.find(p => (stale && p.id === stale.id) || (p.x === cx && p.y === cy));
                    const pile = fresh ? { ...(stale || {}), ...fresh } : stale;
                    if (!pile) return null;
                    const isMine = !pile.scanned_by || pile.scanned_by === user?.id;
                    // Live-computed status: "processing" flips to "ready" once
                    // ready_at is past, even if the server hasn't updated yet.
                    let status = pile.status;
                    if (status === 'processing' && pile.ready_at) {
                      if (new Date(pile.ready_at).getTime() <= nowTs) status = 'ready';
                    }
                    const remainingMs = pile.ready_at ? Math.max(0, new Date(pile.ready_at).getTime() - nowTs) : 0;
                    const mm = String(Math.floor(remainingMs / 60000)).padStart(2, '0');
                    const ss = String(Math.floor((remainingMs % 60000) / 1000)).padStart(2, '0');
                    const rewardName = pile.reward_resource ? getResourceName(pile.reward_resource, t, lang) : '';
                    const rewardIcon = pile.reward_resource ? (getResource(pile.reward_resource, lang)?.icon || '📦') : '📦';
                    return (
                      <div data-testid="trash-panel">
                        <div className="text-text-muted text-xs mb-1">{t('owner')}:</div>
                        <div className="flex items-center gap-2">
                          <img src="/trash.webp" alt="Завал" className="w-8 h-8 rounded object-cover" />
                          <span className="text-amber-400 font-bold">{t('trashPile') || 'Завал'}</span>
                        </div>
                        {status === 'active' && (
                          <>
                            <div className="text-xs text-white/70 mt-2">{t('trashScanHint') || 'Ресурс скрыт до сканирования'}</div>
                            <Button
                              data-testid="trash-scan-btn"
                              onClick={() => scanTrashPile(pile.id)}
                              className="w-full mt-3 bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-600 hover:to-orange-600 text-black font-bold"
                            >
                              {t('trashScan') || 'Сканировать'}
                            </Button>
                          </>
                        )}
                        {status === 'processing' && (
                          <>
                            <div className="mt-2 text-white/80 text-xs">
                              {isMine
                                ? (t('trashScanning') || 'Разбирается')
                                : (t('trashBusy') || 'Занято другим игроком')}
                            </div>
                            <div className="mt-1 font-mono text-2xl text-cyber-cyan text-center" data-testid="trash-timer">
                              {mm}:{ss}
                            </div>
                            <Button disabled className="w-full mt-3 bg-slate-700 text-white/60">
                              {t('trashInProgress') || 'В процессе'}
                            </Button>
                          </>
                        )}
                        {status === 'ready' && isMine && (
                          <>
                            <div className="mt-2 flex items-center gap-2 text-white">
                              <span className="text-xl">{rewardIcon}</span>
                              <span className="font-semibold">{rewardName}</span>
                              <span className="text-green-400 font-bold">×{pile.reward_qty}</span>
                            </div>
                            <Button
                              data-testid="trash-collect-btn"
                              onClick={() => collectTrashPile(pile.id)}
                              className="w-full mt-3 bg-gradient-to-r from-green-500 to-emerald-500 hover:from-green-600 hover:to-emerald-600 text-black font-bold"
                            >
                              {t('trashCollect') || 'Собрать'}
                            </Button>
                          </>
                        )}
                        {status === 'ready' && !isMine && (
                          <div className="mt-2 text-xs text-white/60">
                            {t('trashBusy') || 'Занято другим игроком'}
                          </div>
                        )}
                      </div>
                    );
                  })()}
                  {/* Standard owner block — hidden when a trash pile is shown */}
                  {(() => {
                    const cx = selectedCell.q ?? selectedCell.x;
                    const cy = selectedCell.r ?? selectedCell.y;
                    const hasPile = !!(selectedCell._trash
                      || trashPiles.find(p => p.x === cx && p.y === cy));
                    if (hasPile) return null;
                    return (
                      <>
                        <div className="text-text-muted text-xs mb-1">{t('owner')}:</div>
                        {selectedCell.is_empty === true ? (
                          <div className="flex items-center gap-2">
                            <img src="/favicon.png" alt="GRAM City" className="w-6 h-6 rounded" />
                            <span className="text-cyber-cyan font-medium">GRAM City</span>
                          </div>
                        ) : selectedCell.owner ? (
                          <div className="flex items-center gap-2">
                            {(selectedCell.ownerAvatar || selectedCell.owner_avatar) && (
                              <SmartAvatar
                                avatar={selectedCell.ownerAvatar || selectedCell.owner_avatar}
                                name={selectedCell.ownerUsername || selectedCell.owner_username || ''}
                                className="w-6 h-6 rounded"
                                textClassName="text-[10px]"
                              />
                            )}
                            <span className="text-green-400 font-medium">
                              {(selectedCell.ownerAllianceTag || selectedCell.owner_alliance_tag) && (
                                <span className="text-fuchsia-300 font-bold mr-1" data-testid="cell-owner-alliance-tag">[{selectedCell.ownerAllianceTag || selectedCell.owner_alliance_tag}]</span>
                              )}
                              {selectedCell.ownerUsername || selectedCell.owner_username || t('player')}
                            </span>
                          </div>
                        ) : (
                          <div className="text-amber-400 font-medium">{t('available') || 'Свободно'}</div>
                        )}
                      </>
                    );
                  })()}
                </div>
                
                {/* Marketplace lot of another player: buy it right here (seller gets the money minus tax) */}
                {(() => {
                  const lot = landListings[`${selectedCell.q ?? selectedCell.x},${selectedCell.r ?? selectedCell.y}`];
                  if (!lot || !selectedCell.owner || lot.seller_id === user?.id) return null;
                  const buyLot = async () => {
                    setBuyingLot(true);
                    try {
                      const r = await fetch(`${API}/market/land/buy`, { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }, body: JSON.stringify({ listing_id: lot.id }) });
                      const d = await r.json().catch(() => ({}));
                      if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : t('map_buy'));
                      toast.success(t('map_bought'));
                      setSelectedCell(null);
                      await Promise.all([fetchIslandData(true), fetchLandListings(), fetchMyBusinesses()]);
                      refreshBalance && refreshBalance();
                    } catch (e) { toast.error(e.message); } finally { setBuyingLot(false); }
                  };
                  return (
                    <div className="mt-3 rounded-xl border border-orange-400/40 bg-orange-500/10 p-3 space-y-2" data-testid="map-marketplace-lot">
                      <div className="text-xs text-orange-200">{fill(t('map_sold_by_player'), { name: lot.seller ? `@${lot.seller}` : '' })}</div>
                      <div className="flex items-center justify-between">
                        <span className="text-text-muted text-sm">{t('map_price')}:</span>
                        <span className="font-bold text-orange-300">{formatCity(lot.price_city)} $CITY</span>
                      </div>
                      <Button className="w-full bg-orange-500 hover:bg-orange-400 text-black font-bold" disabled={buyingLot} onClick={buyLot} data-testid="map-buy-lot">
                        {buyingLot ? t('map_buying') : t('map_buy')}
                      </Button>
                    </div>
                  );
                })()}

                {/* Price - show only for available cells (not empty GRAM City plots) */}
                {!selectedCell.owner && selectedCell.is_empty !== true && (() => {
                  const isAdminTI = !!user?.is_admin;
                  const totalBiz = (myBusinessesList || []).length;
                  const tier3Biz = (myBusinessesList || []).filter(b => (b.tier || 1) >= 3).length;
                  // Level-0 gate: while the user holds a Lv.0 (застолблённый)
                  // business, no other business may be bought from the map.
                  const hasZeroBiz = (myBusinessesList || []).some(b => !b.is_trial && ((b.level ?? 1) === 0 || b.is_zero_business));
                  const cellBiz = selectedCell.business;
                  let canBuy = true;
                  if (cellBiz && !isAdminTI) {
                    if (totalBiz >= 3) canBuy = false;
                    else if ((cellBiz.tier || 1) >= 3 && tier3Biz >= 1) canBuy = false;
                  }
                  // Tutorial gate: during the whole tutorial only the
                  // predetermined tutorial plot may be purchased — hide the
                  // Buy button on any other plot.
                  if (tutorial?.active) {
                    const tp = tutorial?.state?.tutorial_plot;
                    const cellX = selectedCell.q ?? selectedCell.x;
                    const cellY = selectedCell.r ?? selectedCell.y;
                    if (!tp || cellX !== tp.x || cellY !== tp.y) {
                      canBuy = false;
                    }
                  }
                  // Per-zone trading schedule: if the cell's zone opens in the
                  // future, show a live countdown on the Buy button instead.
                  // Bypass rules (in strict order):
                  //   • Admins bypass everything (they can buy at any time).
                  //   • The tutorial-reserved plot bypasses ALL restrictions —
                  //     zone schedule AND presale — because the tutorial must
                  //     always be able to complete regardless of admin config.
                  //     Anywhere else (including other helios cells) MUST
                  //     respect the admin's presale/zone rules.
                  let countdown = null;
                  const zoneOpenIso = tradingSchedule?.[selectedCell.zone];
                  const tp = tutorial?.state?.tutorial_plot;
                  const cellX = selectedCell.q ?? selectedCell.x;
                  const cellY = selectedCell.r ?? selectedCell.y;
                  const isTutorialPlotCell =
                    !!tp && cellX === tp.x && cellY === tp.y;
                  const bypassCountdown = isAdminTI || isTutorialPlotCell;
                  if (zoneOpenIso && !bypassCountdown) {
                    const openMs = new Date(zoneOpenIso).getTime();
                    if (!isNaN(openMs) && openMs > nowTs) {
                      countdown = formatCountdown(openMs - nowTs, t('daysShort'));
                    }
                  }

                  // Presale overrides — only when a presale is active and
                  // the cell still carries a pre_business (would normally
                  // show Buy). Admins and the tutorial plot bypass entirely.
                  const isPresalePlot = !!(presaleKeySet && presaleKeySet.has(`${cellX},${cellY}`));
                  const presaleActive = !!presale?.active;
                  let presaleCountdown = null;
                  if (isPresalePlot && !bypassCountdown && presale?.opens_at) {
                    const openMs = new Date(presale.opens_at).getTime();
                    if (!isNaN(openMs) && openMs > nowTs) {
                      presaleCountdown = formatCountdown(openMs - nowTs, t('daysShort'));
                    }
                  }
                  // Placeholder for "other" (non-presale) cells while a
                  // presale is running. Only applies to cells that still
                  // have a pre_business (buyable), not to already-owned
                  // ones. The tutorial-reserved plot is always exempt.
                  // Presale is the source of truth: buying/staking is allowed
                  // ONLY on plots in the active presale allowlist. Everyone
                  // except admins / the tutorial plot is blocked elsewhere and
                  // sees the admin's global custom button text (or default
                  // "Купить" when empty). Empty/absent presale => blocked
                  // everywhere.
                  const presaleAllowedPlot = presaleActive && isPresalePlot;
                  const buyBlockedByPresale =
                    !isAdminTI && !isTutorialPlotCell && !presaleAllowedPlot;
                  const customBuyText = (presale?.buy_button_text || '').trim() || t('buy');
                  return (
                  <div className="mt-2 pt-2 border-t border-white/20">
                    {(() => {
                      const canStakeZero = (myBusinessesList?.length || 0) === 0 && !user?.has_graduated_zero && !!(selectedCell.pre_business || selectedCell.business?.type);
                      return (
                        <>
                        <div className="flex justify-between text-xs mb-3">
                          <span className="text-gray-400">{t('price')}:</span>
                          {canStakeZero ? (
                            <span className="text-emerald-400 font-bold" data-testid="zero-stake-price">0 $CITY · {ZERO_I18N[lang]?.lv0 || 'Lv.0'}</span>
                          ) : (
                            <span className="text-yellow-400 font-bold">{formatCity(selectedCell.price_city || 0)} $CITY</span>
                          )}
                        </div>
                        {canStakeZero && (
                          /* Before claiming: the level-0 business is a 3-day lease; to keep it
                             forever it must be upgraded to level 1 (paid from the real balance). */
                          <div className="mb-3 rounded-lg border border-yellow-400/40 bg-yellow-500/10 px-2.5 py-2 text-[11px] leading-snug text-yellow-100"
                            data-testid="zero-stake-warning">
                            ⚠️ {(t('zeroClaimWarning') || '').replace('{price}', `${formatCity(selectedCell.price_city || 0)} $CITY`)}
                          </div>
                        )}
                        </>
                      );
                    })()}
                    {selectedCell.business?.type ? (
                      hasZeroBiz && !isAdminTI ? (
                        <Button
                          disabled
                          className="w-full bg-white/5 border border-white/15 text-white/70 font-medium cursor-not-allowed disabled:opacity-100 whitespace-normal h-auto py-2 text-xs leading-snug"
                          data-testid="zero-locked-buy"
                        >
                          {ZERO_I18N[lang]?.locked || ZERO_I18N.en.locked}
                        </Button>
                      ) : buyBlockedByPresale ? (
                        <Button
                          disabled
                          className="w-full bg-white/5 border border-white/15 text-white/70 font-medium cursor-not-allowed disabled:opacity-100"
                          data-testid="presale-locked-buy"
                        >
                          {customBuyText}
                        </Button>
                      ) : presaleCountdown ? (
                        <Button
                          disabled
                          className="w-full bg-gradient-to-r from-amber-400 to-yellow-500 text-black font-bold cursor-not-allowed flex items-center justify-center gap-2 disabled:opacity-100"
                          data-testid="presale-countdown"
                          style={{ textShadow: '0 0 8px rgba(255,255,255,0.95), 0 0 16px rgba(255,255,255,0.6)' }}
                        >
                          <Clock className="w-4 h-4" style={{ filter: 'drop-shadow(0 0 6px rgba(255,255,255,0.9))' }} />
                          <span className="font-mono" data-testid="presale-countdown-timer">{presaleCountdown.text}</span>
                        </Button>
                      ) : countdown ? (
                        <Button
                          disabled
                          className="w-full bg-yellow-500 text-white font-bold cursor-not-allowed flex items-center justify-center gap-2 disabled:opacity-100"
                          data-testid="buy-plot-countdown"
                          style={{ textShadow: '0 0 8px rgba(255,255,255,0.95), 0 0 16px rgba(255,255,255,0.6)' }}
                        >
                          <Clock className="w-4 h-4" style={{ filter: 'drop-shadow(0 0 6px rgba(255,255,255,0.9))' }} />
                          <span className="font-mono" data-testid="buy-countdown-timer">{countdown.text}</span>
                        </Button>
                      ) : canBuy ? (
                        <Button
                          onClick={handleBuyClick}
                          disabled={isPurchasing}
                          className="w-full bg-yellow-500 hover:bg-yellow-600 text-black font-bold"
                          data-testid="buy-plot-btn"
                        >
                          {isPurchasing ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <Coins className="w-4 h-4 mr-2" />}
                          {t('buy')}
                        </Button>
                      ) : tutorial?.active ? (
                        <div
                          className="w-full text-center py-2 px-3 rounded-md bg-purple-500/10 border border-purple-500/30 text-purple-300 font-medium text-sm"
                          data-testid="tutorial-locked-buy"
                        >
                          🎓 {t('tutorialLockedBuy') || 'Покупка доступна только на участке обучения'}
                        </div>
                      ) : null
                    ) : (
                      <div
                        className="w-full text-center py-2 px-3 rounded-md bg-signal-amber/10 border border-signal-amber/30 text-signal-amber font-medium text-sm"
                        data-testid="plot-removed-from-sale"
                      >
                        {t('removedFromSale')}
                      </div>
                    )}
                  </div>
                  );
                })()}
              </div>
            </motion.div>
          )}
          </AnimatePresence>

        </div>
      </div>

      {/* Insufficient-funds top-up modal */}
      <LandPurchaseTopUpModal
        isOpen={showTopUpModal}
        onClose={() => setShowTopUpModal(false)}
        cell={selectedCell}
        userBalanceTon={userBalance}
        token={token}
        onConfirmPurchase={executePurchase}
      />

      {/* Demo → Real conversion modal */}
      <Dialog open={showDemoConvertModal} onOpenChange={(open) => { if (!open && !isConverting) setShowDemoConvertModal(false); }}>
        <DialogContent className="bg-void border-cyber-cyan/30 max-w-md" data-testid="demo-convert-modal">
          <DialogHeader>
            <DialogTitle className="text-cyber-cyan">{t('demoConvertTitle')}</DialogTitle>
            <DialogDescription className="text-white/70 pt-2">
              {t('demoConvertBody')}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="flex flex-row gap-2 sm:justify-end">
            <Button
              variant="outline"
              className="flex-1 sm:flex-none border-white/15"
              onClick={() => setShowDemoConvertModal(false)}
              disabled={isConverting}
              data-testid="demo-convert-cancel"
            >
              {t('demoConvertCancel')}
            </Button>
            <Button
              className="flex-1 sm:flex-none bg-cyber-cyan text-black hover:bg-cyber-cyan/80 font-bold"
              onClick={confirmDemoConvert}
              disabled={isConverting}
              data-testid="demo-convert-confirm"
            >
              {isConverting ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : null}
              {t('demoConvertConfirm')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>


      {/* Build Modal */}
      <Dialog open={showBuildModal} onOpenChange={(open) => { if (!open) setShowBuildModal(false); }} modal={true}>
        <DialogContent className="bg-void border-green-500/30 max-w-lg max-h-[85vh] flex flex-col overflow-hidden" data-testid="build-modal" onPointerDownOutside={(e) => e.preventDefault()} onInteractOutside={(e) => e.preventDefault()}>
          <DialogHeader className="flex-shrink-0">
            <DialogTitle className="text-white flex items-center gap-2">
              <Building2 className="w-5 h-5 text-green-400" />
              {t('buildBusiness')}
            </DialogTitle>
            <DialogDescription className="text-text-muted">
              {t('selectBusinessType')} [{selectedCell?.q}, {selectedCell?.r}]
            </DialogDescription>
          </DialogHeader>
          
          <div className="flex-1 overflow-y-auto min-h-0 pr-2" style={{maxHeight: '350px'}}>
            <div className="space-y-2">
              {Object.entries(businessTypes).map(([type, config]) => {
                // Handle name as object or string
                const displayName = typeof config.name === 'object' 
                  ? (config.name?.ru || config.name?.en || type)
                  : (config.name || type);
                // Handle produces as object or string
                const producesName = typeof config.produces === 'object'
                  ? (config.produces?.ru || config.produces?.en || 'TON')
                  : (getResourceName(config.produces || 'TON', t, lang));
                
                return (
                  <div
                    key={type}
                    data-testid={`build-biz-type-${type}`}
                    onClick={() => setSelectedBusinessType(type)}
                    className={`p-3 rounded-lg cursor-pointer transition-all border ${
                      selectedBusinessType === type
                        ? 'bg-green-500/20 border-green-500/50'
                        : 'bg-white/5 border-transparent hover:bg-white/10 hover:border-white/20'
                    }`}
                  >
                    <div className="flex items-center gap-3">
                      <span className="text-2xl">{config.icon || BUILDING_ICONS[type] || '🏢'}</span>
                      <div className="flex-1 min-w-0">
                        <div className="font-bold text-white truncate">
                          {displayName}
                        </div>
                        <div className="text-xs text-text-muted">
                          {config.base_cost_ton || config.cost || '?'} TON • {t('producesColon')} {producesName}
                        </div>
                      </div>
                      <Badge className={TIER_STYLES[config.tier] || TIER_STYLES[1]}>
                        T{config.tier}
                      </Badge>
                    </div>
                  </div>
                )})}
              </div>
            </div>
          
          {/* Show patron selection only for tier 1-2 businesses (not tier 3 large businesses) */}
          {selectedBusinessType && patrons.length > 0 && businessTypes[selectedBusinessType]?.tier !== 3 && (
            <div className="flex-shrink-0 space-y-2 pt-2 border-t border-white/10">
              <label className="text-sm text-text-muted">{t('selectPatronLabel')}</label>
              <Select value={selectedPatron} onValueChange={setSelectedPatron}>
                <SelectTrigger className="bg-white/5 border-white/10">
                  <SelectValue placeholder={t('noPatronLabel')} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">{t('noPatronLabel')}</SelectItem>
                  {patrons.map(p => (
                    <SelectItem key={p.id} value={p.id}>
                      {p.icon} {typeof p.name === 'object' ? (p.name?.ru || p.name?.en || p.id) : p.name} (Lvl {p.level})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
          
          <DialogFooter className="flex-shrink-0 pt-4 border-t border-white/10 gap-3">
            <Button variant="outline" onClick={() => setShowBuildModal(false)} className="border-white/10">
              {t('cancel')}
            </Button>
            <Button 
              onClick={handleBuild}
              data-testid="build-confirm-btn"
              disabled={isBuilding || !selectedBusinessType}
              className="bg-green-500 text-black hover:bg-green-600"
            >
              {isBuilding ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <Building2 className="w-4 h-4 mr-2" />}
              {t('buildBtn')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Business Info Modal removed - info shown in slide panel */}

    </div>
  );
}
