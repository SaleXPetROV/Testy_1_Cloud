import { useState, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { TonConnectButton, useTonConnectUI, useTonWallet } from '@/lib/tonconnect-lazy';
import { motion } from 'framer-motion';
import { 
  Building2, Coins, Users, TrendingUp, Zap, MapPin, 
  Calculator, Globe, GraduationCap, UserCircle, 
  Lock, LayoutDashboard, ShoppingBag, Settings,
  Wallet, BarChart3, Shield, Trophy, Sparkles, Package,
  X, MessageCircle, Radio, Send
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { getGameStats } from '@/lib/api';
import { runAfterFirstInteraction } from '@/lib/firstGesture';
import { useTranslation, languages } from '@/lib/translations';
import { useLanguage } from '@/context/LanguageContext';
import { formatCity, tonToCity } from '@/lib/currency';
import { toast } from 'sonner';
import { useMouseParallax } from '@/hooks/useMouseParallax';
import TutorialModal from '@/components/TutorialModal';
import Sidebar from '@/components/Sidebar';
import HowItWorksFlow from '@/components/HowItWorksFlow';
import { useTutorial } from '@/context/TutorialContext';
import { hapticImpact } from '@/lib/telegramHaptic';
import SmartAvatar from '@/components/SmartAvatar';

// GRAM Island public-facing total plots/fields. Kept in sync with the island
// card's «ВСЕГО» on the maps screen.
const GRAM_ISLAND_TOTAL_PLOTS = 525;
// Total purchasable business slots on the map (public-facing marketing number).
const GRAM_ISLAND_TOTAL_BUSINESSES = 478;

// Community Telegram destinations + localized labels for the footer chooser
// modal (all 8 project languages).
const TG_LINKS = {
  channel: 'https://t.me/gramcity_channel',
  chat: 'https://t.me/gramcity_chat',
  bot: 'https://t.me/gramcity_games_bot',
};
const TG_MODAL_I18N = {
  en: { title: 'GRAM CITY on Telegram', subtitle: 'Choose where to go', channel: 'Go to channel', chat: 'Go to chat', bot: 'Go to bot', close: 'Close' },
  ru: { title: 'GRAM CITY в Telegram', subtitle: 'Выберите, куда перейти', channel: 'Перейти в канал', chat: 'Перейти в чат', bot: 'Перейти в бота', close: 'Закрыть' },
  es: { title: 'GRAM CITY en Telegram', subtitle: 'Elige a dónde ir', channel: 'Ir al canal', chat: 'Ir al chat', bot: 'Ir al bot', close: 'Cerrar' },
  zh: { title: 'Telegram 上的 GRAM CITY', subtitle: '选择前往', channel: '前往频道', chat: '前往聊天', bot: '前往机器人', close: '关闭' },
  fr: { title: 'GRAM CITY sur Telegram', subtitle: 'Choisissez où aller', channel: 'Aller au canal', chat: 'Aller au chat', bot: 'Aller au bot', close: 'Fermer' },
  de: { title: 'GRAM CITY auf Telegram', subtitle: 'Wähle dein Ziel', channel: 'Zum Kanal', chat: 'Zum Chat', bot: 'Zum Bot', close: 'Schließen' },
  ja: { title: 'Telegram の GRAM CITY', subtitle: '移動先を選択', channel: 'チャンネルへ', chat: 'チャットへ', bot: 'ボットへ', close: '閉じる' },
  ko: { title: 'Telegram의 GRAM CITY', subtitle: '이동할 곳 선택', channel: '채널로 이동', chat: '채팅으로 이동', bot: '봇으로 이동', close: '닫기' },
};

export default function LandingPage({ user, setUser }) {
  const navigate = useNavigate();
  const wallet = useTonWallet();
  const [stats, setStats] = useState(null);
  const [showTutorial, setShowTutorial] = useState(false);
  const [myBusinessesCount, setMyBusinessesCount] = useState(0);
  const [myResourcesTotal, setMyResourcesTotal] = useState(0);
  const [showTgModal, setShowTgModal] = useState(false);
  const { language: lang, setLang } = useLanguage();
  const { t } = useTranslation(lang);
  const tutorial = useTutorial();
  const tiltRef = useMouseParallax({ max: 10, shift: 8, damp: 0.10 });

  // P0 (2026-02): Landing page must ALWAYS be accessible — authenticated
  // users (including inside a Telegram Mini App) land here on open. We do NOT
  // auto-redirect to the map list anymore: the user explicitly wants the
  // Mini App to open on the Home/landing page.

  // Memoise the heavy hologram SVG: it's purely decorative and depends on
  // nothing from the component state. Without this, every state change
  // (stats fetch, language switch, tutorial updates) re-rendered the entire
  // SVG tree (~80 nodes with filters/gradients), which made the animation
  // visibly judder. Memoising drops re-renders to zero.
  const hologramSvg = useMemo(() => (
    <svg viewBox="0 0 400 400" className="holo-svg" aria-hidden>
      <defs>
        <radialGradient id="globeFill" cx="40%" cy="40%" r="60%">
          <stop offset="0%"  stopColor="#22E2FF" stopOpacity="0.35" />
          <stop offset="60%" stopColor="#3B7BFF" stopOpacity="0.15" />
          <stop offset="100%" stopColor="#7A2EFF" stopOpacity="0.05" />
        </radialGradient>
        <linearGradient id="lineGrad" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%"   stopColor="#22E2FF" stopOpacity="0.0" />
          <stop offset="50%"  stopColor="#22E2FF" stopOpacity="0.9" />
          <stop offset="100%" stopColor="#22E2FF" stopOpacity="0.0" />
        </linearGradient>
        <filter id="hglow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="1.6" result="blur" />
          <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>
      </defs>

      {/* HUD frame corners */}
      <g fill="none" stroke="#22E2FF" strokeWidth="1" opacity="0.8">
        <path d="M20 20 L20 40 M20 20 L40 20" />
        <path d="M380 20 L380 40 M380 20 L360 20" />
        <path d="M20 380 L20 360 M20 380 L40 380" />
        <path d="M380 380 L380 360 M380 380 L360 380" />
      </g>
      <g fontFamily="JetBrains Mono, monospace" fontSize="8" fill="#22E2FF" opacity="0.7" letterSpacing="1.5">
        <text x="48" y="32">TON-NET.GLOBE</text>
        <text x="320" y="32">v2.1</text>
        <text x="48" y="376">NODES: 1428</text>
        <text x="298" y="376">SYNC OK</text>
      </g>

      {/* Orbits (counter-rotating rings) */}
      <g className="globe-orbit-slow" style={{ transformOrigin: '200px 200px' }}>
        <ellipse cx="200" cy="200" rx="170" ry="44" fill="none" stroke="#22E2FF" strokeWidth="0.8" opacity="0.5" />
      </g>
      <g className="globe-orbit-rev" style={{ transformOrigin: '200px 200px' }}>
        <ellipse cx="200" cy="200" rx="170" ry="44" fill="none" stroke="#7A2EFF" strokeWidth="0.8" opacity="0.45" transform="rotate(60 200 200)" />
      </g>
      <g className="globe-orbit-slow" style={{ transformOrigin: '200px 200px' }}>
        <ellipse cx="200" cy="200" rx="170" ry="44" fill="none" stroke="#22E2FF" strokeWidth="0.6" opacity="0.35" transform="rotate(-45 200 200)" />
      </g>

      {/* Wireframe globe */}
      <g className="globe-rotate" style={{ transformOrigin: '200px 200px' }}>
        <circle cx="200" cy="200" r="120" fill="url(#globeFill)" stroke="#22E2FF" strokeWidth="1" opacity="0.85" />
        <ellipse cx="200" cy="200" rx="120" ry="22"  fill="none" stroke="#22E2FF" strokeWidth="0.6" opacity="0.55" />
        <ellipse cx="200" cy="200" rx="120" ry="55"  fill="none" stroke="#22E2FF" strokeWidth="0.6" opacity="0.45" />
        <ellipse cx="200" cy="200" rx="120" ry="90"  fill="none" stroke="#22E2FF" strokeWidth="0.6" opacity="0.4" />
        <ellipse cx="200" cy="200" rx="120" ry="110" fill="none" stroke="#22E2FF" strokeWidth="0.5" opacity="0.3" />
        <ellipse cx="200" cy="200" rx="22"  ry="120" fill="none" stroke="#7A2EFF" strokeWidth="0.6" opacity="0.55" />
        <ellipse cx="200" cy="200" rx="55"  ry="120" fill="none" stroke="#7A2EFF" strokeWidth="0.6" opacity="0.45" />
        <ellipse cx="200" cy="200" rx="90"  ry="120" fill="none" stroke="#7A2EFF" strokeWidth="0.6" opacity="0.4" />
        <ellipse cx="200" cy="200" rx="110" ry="120" fill="none" stroke="#7A2EFF" strokeWidth="0.5" opacity="0.3" />
        <line x1="80" y1="200" x2="320" y2="200" stroke="#22E2FF" strokeWidth="1" opacity="0.7" />
        <circle cx="200" cy="80" r="3" fill="#22E2FF" className="holo-dot" filter="url(#hglow)" />
        <circle cx="200" cy="320" r="3" fill="#22E2FF" className="holo-dot" filter="url(#hglow)" />

        <g filter="url(#hglow)">
          <circle cx="156" cy="148" r="3.5" fill="#22E2FF" className="globe-pulse" />
          <circle cx="244" cy="170" r="3.5" fill="#7A2EFF" className="globe-pulse" style={{ animationDelay: '0.6s' }} />
          <circle cx="180" cy="240" r="3"   fill="#22E2FF" className="globe-pulse" style={{ animationDelay: '1.2s' }} />
          <circle cx="262" cy="232" r="3.5" fill="#22E2FF" className="globe-pulse" style={{ animationDelay: '0.3s' }} />
          <circle cx="138" cy="218" r="3"   fill="#7A2EFF" className="globe-pulse" style={{ animationDelay: '1.5s' }} />
          <circle cx="220" cy="124" r="3"   fill="#22E2FF" className="globe-pulse" style={{ animationDelay: '0.9s' }} />
        </g>

        <g fill="none" stroke="url(#lineGrad)" strokeWidth="1" opacity="0.85">
          <path d="M156 148 Q200 110 244 170" className="globe-link" />
          <path d="M180 240 Q210 200 262 232" className="globe-link" style={{ animationDelay: '0.7s' }} />
          <path d="M138 218 Q170 170 220 124" className="globe-link" style={{ animationDelay: '1.4s' }} />
        </g>
      </g>

      {/* Orbiting satellite */}
      <g className="sat-orbit" style={{ transformOrigin: '200px 200px' }}>
        <g transform="translate(200, 56)">
          <circle r="4" fill="#22E2FF" className="holo-dot" filter="url(#hglow)" />
          <circle r="9" fill="none" stroke="#22E2FF" strokeWidth="0.6" opacity="0.6" />
        </g>
      </g>
      <g className="sat-orbit-rev" style={{ transformOrigin: '200px 200px' }}>
        <g transform="translate(56, 200)">
          <circle r="3" fill="#7A2EFF" className="holo-dot" filter="url(#hglow)" />
        </g>
      </g>

      <line x1="60" y1="200" x2="340" y2="200" stroke="#22E2FF" strokeWidth="1.2" className="holo-scan" opacity="0.85" />
    </svg>
  ), []);

  // Features array
  const features = [
    {
      icon: Building2,
      title: t('buildCity'),
      description: t('buildCityDesc')
    },
    {
      icon: Coins,
      title: t('earnMoney'),
      description: t('earnMoneyDesc')
    },
    {
      icon: Users,
      title: t('trade'),
      description: t('tradeDesc')
    },
    {
      icon: TrendingUp,
      title: t('grow'),
      description: t('growDesc')
    }
  ];

  // Game mechanics for info section
  const gameMechanics = [
    {
      icon: MapPin,
      title: t('buyLand') || 'Buy Land',
      desc: t('buyLandDesc') || 'Purchase plots in different city zones - from the expensive center to affordable outskirts'
    },
    {
      icon: Building2,
      title: t('buildBusiness') || 'Build Business',
      desc: t('buildBusinessDesc') || 'Construct farms, factories, shops, restaurants, banks and more'
    },
    {
      icon: Zap,
      title: t('produceResources') || 'Produce Resources',
      desc: t('produceResourcesDesc') || 'Your businesses produce resources that can be sold or used by other businesses'
    },
    {
      icon: BarChart3,
      title: t('earnIncome') || 'Earn Income',
      desc: t('earnIncomeDesc') || 'Get real TON cryptocurrency from your businesses every day'
    },
    {
      icon: Shield,
      title: t('secureBlockchain') || 'Secure Blockchain',
      desc: t('secureBlockchainDesc') || 'All transactions are recorded on TON blockchain - your assets are truly yours'
    },
    {
      icon: Trophy,
      title: t('levelUp') || 'Level Up',
      desc: t('levelUpDesc') || 'Grow your business empire, unlock new opportunities and climb the rankings'
    }
  ];

  const changeLang = (newLang) => {
    setLang(newLang);
  };

  const loadStats = async () => {
    try {
      const data = await getGameStats();
      setStats(data);
    } catch (error) {
      console.error('Failed to load stats:', error);
    }
  };

  useEffect(() => {
    // Deferred: no /api/stats on cold start for a plain-browser guest / scanner.
    runAfterFirstInteraction(loadStats);
  }, []);

  // Load real per-user counters (businesses + total resources) for the "Your Stats" cards.
  // user.businesses_owned can be stale or empty for legacy accounts, so we fetch the
  // authoritative /my/businesses and /my/resources endpoints whenever user is logged in.
  useEffect(() => {
    if (!user) return;
    const token = localStorage.getItem('token') || localStorage.getItem('ton_city_token');
    if (!token) return;
    const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
    const API = `${BACKEND_URL}/api`;
    Promise.all([
      fetch(`${API}/my/businesses`, { headers: { Authorization: `Bearer ${token}` } })
        .then((r) => r.ok ? r.json() : { businesses: [] })
        .catch(() => ({ businesses: [] })),
      fetch(`${API}/my/resources`, { headers: { Authorization: `Bearer ${token}` } })
        .then((r) => r.ok ? r.json() : { resources: {} })
        .catch(() => ({ resources: {} })),
    ]).then(([bizRes, resRes]) => {
      setMyBusinessesCount((bizRes.businesses || []).length);
      const total = Object.values(resRes.resources || {}).reduce(
        (acc, v) => acc + (typeof v === 'number' ? v : Number(v) || 0),
        0,
      );
      setMyResourcesTotal(total);
    });
  }, [user]);

  return (
    <div className="min-h-screen bg-void relative overflow-hidden font-rajdhani">
      {/* Sidebar для авторизованных пользователей */}
      {user && <Sidebar user={user} />}

      {/* Hi-Tech Futurism background — base gradient renders instantly (lightweight, GPU-friendly).
          .tg-bleed-top extends this layer upward into Telegram's safe-area
          inside Mini Apps, so the gradient flows behind «Закрыть»/«˅»/«⋮». */}
      <div className="hero-futurism tg-bleed-top" aria-hidden />

      {/* Heavy decorative effects — lazy-loaded via opacity fade-in for better LCP */}
      <div className="bg-fx-lazy tg-bleed-top" aria-hidden>
        <div className="hero-grid" aria-hidden />
        <div className="bg-pulse-wave" aria-hidden />
        <div className="ambient-dots" aria-hidden />
        {/* Floating colored orbs — reduced from 6 to 3 for performance */}
        <div className="hero-glow-orb" style={{ top: '-100px', left: '-80px', width: 360, height: 360, background: 'rgba(122, 46, 255, 0.45)' }} aria-hidden />
        <div className="hero-glow-orb" style={{ top: '40%', right: '-120px', width: 380, height: 380, background: 'rgba(34, 226, 255, 0.38)' }} aria-hidden />
        <div className="hero-glow-orb" style={{ top: '85%', left: '20%', width: 360, height: 360, background: 'rgba(59, 123, 255, 0.32)' }} aria-hidden />
      </div>

      <div className="relative z-10">
        {/* HEADER — pads under Telegram's overlay chrome inside Mini Apps,
            and aligns its content row vertically with the fixed burger button
            via .tg-header-pad. When the visitor is NOT logged in we add an
            extra mobile top margin so the logo doesn't crowd «Закрыть». */}
        <header className={`container mx-auto px-4 sm:px-6 tg-header-pad ${user ? '' : 'mt-2 sm:mt-0'}`}>
          <nav className={`flex items-center justify-between ${user ? 'sm:pl-6 lg:pl-10' : 'pl-0'}`}>
            {/* Logo + Title */}
            <motion.div 
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              className="flex items-center gap-2 sm:gap-3 cursor-pointer"
              onClick={() => navigate('/')}
            >
              {/* Icon hidden on mobile when user is logged in */}
              <div className={`w-10 h-10 sm:w-12 sm:h-12 rounded-xl bg-gradient-to-br from-cyber-cyan to-neon-purple flex items-center justify-center shadow-lg shadow-cyber-cyan/30 ${user ? 'hidden sm:flex' : ''}`}>
                <Building2 className="w-6 h-6 sm:w-7 sm:h-7 text-black" />
              </div>
              <span className="font-unbounded text-xl sm:text-2xl font-bold text-text-main tracking-tight">
                GRAM<span className="text-cyber-cyan">CITY</span>
              </span>
            </motion.div>

            <motion.div
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              className="flex items-center gap-2 sm:gap-4"
            >
              {/* Language selector */}
              <Select value={lang} onValueChange={changeLang}>
                <SelectTrigger className="w-20 sm:w-32 bg-panel/30 border-white/10 text-text-main hover:border-cyber-cyan/50 transition-colors h-9 sm:h-10 text-xs sm:text-sm rounded-xl">
                  <Globe className="w-4 h-4 mr-1 sm:mr-2 text-cyber-cyan" />
                  <SelectValue>
                    {languages.find(l => l.code === lang)?.flag}
                    <span className="hidden sm:inline ml-1">{lang.toUpperCase()}</span>
                  </SelectValue>
                </SelectTrigger>
                <SelectContent className="bg-panel border-grid-border">
                  {languages.map(language => (
                    <SelectItem key={language.code} value={language.code}>
                      <span className="flex items-center gap-2">
                        <span>{language.flag}</span>
                        <span>{language.name}</span>
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              {/* User Avatar - only for logged in users */}
              {user && (
                <motion.div 
                  initial={{ scale: 0.8, opacity: 0 }}
                  animate={{ scale: 1, opacity: 1 }}
                  onClick={() => navigate('/settings')}
                  className="flex items-center gap-2 sm:gap-3 bg-white/5 p-1 sm:p-1.5 pr-2 sm:pr-4 rounded-full border border-white/10 cursor-pointer hover:bg-white/10 transition-all group"
                >
                  <SmartAvatar
                    avatar={user.avatar}
                    name={user.display_name || user.username}
                    className="w-8 h-8 sm:w-10 sm:h-10 rounded-full border-2 border-cyber-cyan shadow-[0_0_15px_rgba(0,255,243,0.3)] group-hover:shadow-cyber-cyan/50 transition-all text-sm"
                  />
                  <div className="text-left hidden sm:block">
                    <p className="text-sm font-bold text-white tracking-tight">
                      {user.display_name || user.username}
                    </p>
                  </div>
                </motion.div>
              )}
            </motion.div>
          </nav>
        </header>

        {/* HERO CONTENT */}
        <main className="container mx-auto px-4 sm:px-6 pt-8 sm:pt-12 pb-6 sm:pb-10">
          {/* Desktop (lg+): two-column layout — text + CTA on the LEFT,
              hologram on the RIGHT (per latest design feedback).
              Mobile (lg-): text-only, hologram hidden. */}
          <div className="hidden lg:grid lg:grid-cols-[1.1fr_1fr] gap-10 lg:gap-12 items-center max-w-6xl mx-auto mb-12 sm:mb-16">
            {/* LEFT — text + CTA */}
            <div className="text-left">
              <motion.h1
                initial={{ opacity: 0, y: 30 }}
                animate={{ opacity: 1, y: 0 }}
                className="font-unbounded text-3xl sm:text-4xl lg:text-6xl font-black text-text-main mb-4 sm:mb-6 leading-tight uppercase neon-title"
              >
                {t('title')}{' '}
                <span className="text-transparent bg-clip-text bg-gradient-to-r from-cyber-cyan to-neon-purple">
                  {t('subtitle')}
                </span>
              </motion.h1>
              <motion.p
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.2 }}
                className="text-base sm:text-lg text-text-muted mb-8 sm:mb-10 max-w-xl"
              >
                {t('description')}
              </motion.p>
              <div className="flex items-center justify-start gap-3 sm:gap-4">
                <Button
                  onClick={() => {
                    hapticImpact('medium');
                    user ? navigate('/maps') : navigate('/auth?mode=register');
                  }}
                  className="cta-pulse bg-cyber-cyan text-black px-6 sm:px-8 py-6 sm:py-7 font-unbounded text-sm font-bold rounded-2xl shadow-xl shadow-cyber-cyan/20 hover:scale-105 transition-transform"
                  data-testid="landing-start-btn-desktop"
                >
                  {user ? (t('toCity') || 'TO CITY') : (t('startBuilding') || 'START BUILDING')}
                </Button>
              </div>
            </div>

            {/* RIGHT — hologram */}
            <div className="flex justify-end">
              <div ref={tiltRef} className="holo-frame holo-tilt -mt-2 w-[420px]">
                {hologramSvg}
              </div>
            </div>
          </div>

          {/* Mobile only — original text-only layout, hologram hidden */}
          <div className="lg:hidden max-w-6xl mx-auto mb-12 sm:mb-16">
            <div className="text-center">
              <motion.h1
                initial={{ opacity: 0, y: 30 }}
                animate={{ opacity: 1, y: 0 }}
                className="font-unbounded text-3xl sm:text-4xl font-black text-text-main mb-4 leading-tight uppercase neon-title"
              >
                {t('title')}{' '}
                <span className="text-transparent bg-clip-text bg-gradient-to-r from-cyber-cyan to-neon-purple">
                  {t('subtitle')}
                </span>
              </motion.h1>
              <motion.p
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.2 }}
                className="text-base text-text-muted mb-8 max-w-2xl mx-auto px-4"
              >
                {t('description')}
              </motion.p>
              <div className="flex items-center justify-center gap-3 px-4">
                <Button
                  onClick={() => {
                    hapticImpact('medium');
                    user ? navigate('/maps') : navigate('/auth?mode=register');
                  }}
                  className="cta-pulse w-full sm:w-auto bg-cyber-cyan text-black px-6 py-6 font-unbounded text-sm font-bold rounded-2xl shadow-xl shadow-cyber-cyan/20 hover:scale-105 transition-transform"
                  data-testid="landing-start-btn"
                >
                  {user ? (t('toCity') || 'TO CITY') : (t('startBuilding') || 'START BUILDING')}
                </Button>
              </div>
            </div>
          </div>

          <div className="max-w-4xl mx-auto text-center">

            {/* СТАТИСТИКА ИГРЫ — 4 ключевые метрики: игроки / всего участков / куплено бизнесов / TON в обороте */}
            {stats && (
              <motion.div 
                initial={{ opacity: 0, y: 30 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.4 }}
                className="grid grid-cols-2 sm:grid-cols-4 gap-3 sm:gap-4 mb-16 sm:mb-20 max-w-4xl mx-auto"
              >
                {[
                  { label: t('players'), value: stats.total_players, color: 'text-cyber-cyan', isFloat: false },
                  // v2.2.1: total plots is shown as a fixed marketing number
                  // until the next map expansion. The dynamic value from
                  // /api/stats includes auxiliary cells (event maps, etc.)
                  // that aren't part of GRAM Island's public-facing inventory.
                  { label: t('totalPlots') || t('plotsBought'), value: GRAM_ISLAND_TOTAL_PLOTS, color: 'text-cyber-cyan', isFloat: false },
                  { label: t('businesses'), value: GRAM_ISLAND_TOTAL_BUSINESSES, color: 'text-cyber-cyan', isFloat: false },
                  { label: t('tonInCirculation') || 'TON в обороте', value: stats.total_volume_ton, color: 'text-signal-amber', isFloat: true },
                ].map((s, i) => {
                  const num = Number(s.value || 0);
                  const formatted = s.isFloat
                    ? num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
                    : num.toLocaleString('en-US');
                  // Auto-shrink font: tighter on mobile (cards are half-width)
                  // so even mid-size numbers don't overflow.
                  const len = formatted.length;
                  let sizeCls;
                  if (len > 14)      sizeCls = 'text-[10px] sm:text-base';
                  else if (len > 11) sizeCls = 'text-xs sm:text-lg';
                  else if (len > 9)  sizeCls = 'text-sm sm:text-xl';
                  else if (len > 7)  sizeCls = 'text-base sm:text-2xl';
                  else if (len > 5)  sizeCls = 'text-lg sm:text-2xl';
                  else               sizeCls = 'text-2xl sm:text-3xl';
                  return (
                    <div key={i} className="glass-panel rounded-xl sm:rounded-2xl p-3 sm:p-6 border border-white/5 bg-white/2 overflow-hidden min-w-0">
                      <div
                        className={`${sizeCls} font-mono ${s.color} font-bold mb-1 leading-tight whitespace-nowrap overflow-hidden text-ellipsis`}
                        data-testid={`landing-stat-${i}`}
                        title={formatted}
                      >
                        {formatted}
                      </div>
                      <div className="text-[9px] sm:text-[10px] text-text-muted uppercase tracking-[0.15em] sm:tracking-[0.2em] whitespace-nowrap overflow-hidden text-ellipsis">{s.label}</div>
                    </div>
                  );
                })}
              </motion.div>
            )}

            {/* ДАННЫЕ ПОЛЬЗОВАТЕЛЯ (если авторизован) */}
            {user && (
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.5 }}
                className="mb-16 sm:mb-20"
              >
                <h2 className="font-unbounded text-lg sm:text-xl font-bold text-white mb-6 uppercase tracking-wide">
                  {t('yourStats') || 'Your Stats'}
                </h2>
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4 max-w-3xl mx-auto">
                  {/* TON balance card */}
                  {(() => {
                    const tonVal = Number(user.balance_ton || 0).toFixed(2);
                    const len = tonVal.length;
                    const sizeCls = len > 11 ? 'text-xs sm:text-lg'
                      : len > 9 ? 'text-sm sm:text-xl'
                      : len > 7 ? 'text-base sm:text-2xl'
                      : 'text-xl sm:text-2xl';
                    return (
                      <div className="glass-panel rounded-xl p-4 sm:p-5 border border-cyber-cyan/20 bg-cyber-cyan/5 overflow-hidden min-w-0">
                        <Wallet className="w-5 h-5 text-cyber-cyan mb-2" />
                        <div
                          className={`${sizeCls} font-mono text-white font-bold whitespace-nowrap overflow-hidden text-ellipsis`}
                          title={tonVal}
                          data-testid="auth-stat-ton"
                        >
                          {tonVal}
                        </div>
                        <div className="text-[10px] text-text-muted uppercase tracking-wider">TON</div>
                      </div>
                    );
                  })()}

                  {/* $CITY balance card — value only, the "$CITY" header on top already
                      identifies the currency, so we don't repeat the suffix after the number. */}
                  {(() => {
                    const cityVal = formatCity(tonToCity(user.balance_ton || 0));
                    const len = cityVal.length;
                    const sizeCls = len > 11 ? 'text-sm sm:text-lg'
                      : len > 8  ? 'text-base sm:text-xl'
                      : 'text-lg sm:text-2xl';
                    return (
                      <div className="glass-panel rounded-xl p-4 sm:p-5 border border-neon-purple/20 bg-neon-purple/5 overflow-hidden min-w-0">
                        <div className="flex items-center gap-1 mb-2">
                          <span className="font-bold text-neon-purple text-sm leading-none">$</span>
                          <span className="font-bold text-neon-purple text-xs leading-none tracking-wider">CITY</span>
                        </div>
                        <div
                          className={`${sizeCls} font-mono text-white font-bold whitespace-nowrap overflow-hidden text-ellipsis`}
                          title={cityVal}
                          data-testid="auth-stat-city"
                        >
                          {cityVal}
                        </div>
                      </div>
                    );
                  })()}

                  <div className="glass-panel rounded-xl p-4 sm:p-5 border border-signal-amber/20 bg-signal-amber/5 overflow-hidden min-w-0">
                    <Building2 className="w-5 h-5 text-signal-amber mb-2" />
                    <div className="text-xl sm:text-2xl font-mono text-white font-bold whitespace-nowrap overflow-hidden text-ellipsis">
                      {myBusinessesCount}
                    </div>
                    <div className="text-[10px] text-text-muted uppercase tracking-wider">{t('businesses')}</div>
                  </div>
                  <div className="glass-panel rounded-xl p-4 sm:p-5 border border-emerald-500/20 bg-emerald-500/5 overflow-hidden min-w-0">
                    <Package className="w-5 h-5 text-emerald-400 mb-2" />
                    <div className="text-xl sm:text-2xl font-mono text-white font-bold whitespace-nowrap overflow-hidden text-ellipsis">
                      {Math.round(myResourcesTotal).toLocaleString('ru-RU')}
                    </div>
                    <div className="text-[10px] text-text-muted uppercase tracking-wider">{t('resources') || 'Ресурсы'}</div>
                  </div>
                </div>
              </motion.div>
            )}

            {/* QUICK ACCESS - New Features */}
            {user && (
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.6 }}
                className="mb-16 sm:mb-20"
              >
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 sm:gap-4 max-w-4xl mx-auto">
                  <button onClick={() => navigate('/trading')} className="glass-panel rounded-xl p-4 border border-green-500/20 bg-green-500/5 hover:bg-green-500/10 transition-all text-left group" data-testid="landing-card-p2p">
                    <TrendingUp className="w-5 h-5 text-green-400 mb-2 group-hover:scale-110 transition-transform" />
                    <div className="text-sm font-bold text-white">{t('p2pTradingCard')}</div>
                    <div className="text-[10px] text-text-muted">{t('p2pTradingDesc')}</div>
                  </button>
                  <button onClick={() => navigate('/my-businesses')} className="glass-panel rounded-xl p-4 border border-amber-500/20 bg-amber-500/5 hover:bg-amber-500/10 transition-all text-left group" data-testid="landing-card-mybusinesses">
                    <Building2 className="w-5 h-5 text-amber-400 mb-2 group-hover:scale-110 transition-transform" />
                    <div className="text-sm font-bold text-white">{t('myBusinessesCard')}</div>
                    <div className="text-[10px] text-text-muted">{t('myBusinessesDesc')}</div>
                  </button>
                  <button onClick={() => navigate('/leaderboard')} className="glass-panel rounded-xl p-4 border border-purple-500/20 bg-purple-500/5 hover:bg-purple-500/10 transition-all text-left group" data-testid="landing-card-leaderboard">
                    <Trophy className="w-5 h-5 text-purple-400 mb-2 group-hover:scale-110 transition-transform" />
                    <div className="text-sm font-bold text-white">{t('leaderboardCard')}</div>
                    <div className="text-[10px] text-text-muted">{t('leaderboardDesc')}</div>
                  </button>
                </div>
              </motion.div>
            )}
          </div>

          {/* КАРТОЧКИ ФУНКЦИЙ */}
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4 sm:gap-6 max-w-6xl mx-auto mb-16 sm:mb-20">
            {features.map((feature, index) => {
              const Icon = feature.icon;
              return (
                <motion.div
                  key={index}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.5 + index * 0.1 }}
                  className="glass-panel group hover:border-cyber-cyan/30 rounded-2xl sm:rounded-3xl p-6 sm:p-8 transition-all relative overflow-hidden"
                >
                  <div className="absolute top-0 right-0 p-4 opacity-5 group-hover:opacity-10 transition-opacity">
                    <Icon className="w-16 sm:w-20 h-16 sm:h-20 text-white" />
                  </div>
                  <div className="w-10 h-10 sm:w-12 sm:h-12 rounded-xl bg-cyber-cyan/10 flex items-center justify-center mb-4 sm:mb-6 border border-cyber-cyan/20">
                    <Icon className="w-5 h-5 sm:w-6 sm:h-6 text-cyber-cyan" />
                  </div>
                  <h3 className="font-unbounded text-base sm:text-lg font-bold text-white mb-2 sm:mb-3 uppercase tracking-tight">
                    {feature.title}
                  </h3>
                  <p className="text-text-muted text-sm leading-relaxed">
                    {feature.description}
                  </p>
                </motion.div>
              );
            })}
          </div>

          {/* КАК ЭТО РАБОТАЕТ - визуальный циклический поток (v2.1.5) */}
          <div className="max-w-6xl mx-auto mb-16 sm:mb-20">
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.8 }}
            >
              <h2 className="font-unbounded text-xl sm:text-2xl lg:text-3xl font-bold text-white text-center mb-4 uppercase tracking-tight">
                <Sparkles className="w-6 h-6 inline-block mr-2 text-cyber-cyan" />
                {t('howItWorks') || 'How It Works'}
              </h2>
              <p className="text-text-muted text-center mb-8 sm:mb-12 max-w-3xl mx-auto px-4">
                {t('howItWorksDesc') || 'Купи свой первый бизнес → закупай ресурсы → бизнес производит товар → продавай его на бирже → получай TON → прокачивай бизнес и начинай новый цикл с более крупной прибылью.'}
              </p>

              <HowItWorksFlow />
            </motion.div>
          </div>

          {/* БЛОКЧЕЙН ПРЕИМУЩЕСТВА */}
          <motion.div
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 1.2 }}
            className="max-w-4xl mx-auto text-center mb-6 sm:mb-8"
          >
            <div className="glass-panel rounded-2xl sm:rounded-3xl p-6 sm:p-10 border border-cyber-cyan/10 bg-gradient-to-br from-cyber-cyan/5 to-neon-purple/5">
              <h3 className="font-unbounded text-lg sm:text-xl font-bold text-white mb-4 uppercase">
                {t('poweredByTON') || 'Powered by TON Blockchain'}
              </h3>
              <p className="text-text-muted mb-6 text-sm sm:text-base">
                {t('tonAdvantages') || 'Lightning-fast transactions, minimal fees, and complete ownership of your in-game assets. Your progress and earnings are stored securely on the blockchain.'}
              </p>
              <div className="flex flex-wrap justify-center gap-4">
                <div className="bg-white/5 px-4 py-2 rounded-full text-xs sm:text-sm text-cyber-cyan border border-cyber-cyan/20">
                  ⚡ {t('fastTransactions') || 'Fast Transactions'}
                </div>
                <div className="bg-white/5 px-4 py-2 rounded-full text-xs sm:text-sm text-cyber-cyan border border-cyber-cyan/20">
                  💰 {t('lowFees') || 'Low Fees'}
                </div>
                <div className="bg-white/5 px-4 py-2 rounded-full text-xs sm:text-sm text-cyber-cyan border border-cyber-cyan/20">
                  🔒 {t('trueOwnership') || 'True Ownership'}
                </div>
              </div>
            </div>
          </motion.div>
        </main>

        <footer className="border-t border-white/5 py-5 sm:py-6 mt-2 bg-black/30 backdrop-blur-md">
          <div className="container mx-auto px-4 sm:px-6">
            <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
              {/* Brand */}
              <div className="flex items-center gap-2 opacity-70">
                <Building2 className="w-4 h-4 sm:w-5 sm:h-5 text-cyber-cyan" />
                <span className="font-unbounded text-[10px] sm:text-xs font-bold uppercase tracking-widest">Gram City Builder</span>
              </div>

              {/* Center links */}
              <div className="flex flex-wrap items-center justify-center gap-2 sm:gap-3">
                <button
                  onClick={() => navigate('/privacy')}
                  data-testid="footer-privacy-btn"
                  className="px-3 sm:px-4 py-1.5 rounded-full text-[10px] sm:text-xs font-orbitron uppercase tracking-widest text-text-muted bg-white/5 border border-white/10 hover:border-cyber-cyan/50 hover:text-cyber-cyan transition-colors"
                >
                  {t('privacy') || 'Политика'}
                </button>
                <button
                  onClick={() => navigate('/terms')}
                  data-testid="footer-terms-btn"
                  className="px-3 sm:px-4 py-1.5 rounded-full text-[10px] sm:text-xs font-orbitron uppercase tracking-widest text-text-muted bg-white/5 border border-white/10 hover:border-cyber-cyan/50 hover:text-cyber-cyan transition-colors"
                >
                  {t('terms') || 'Документы'}
                </button>
              </div>

              {/* Social — separate cluster of icon buttons */}
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setShowTgModal(true)}
                  data-testid="footer-telegram"
                  className="w-9 h-9 rounded-full flex items-center justify-center bg-white/5 border border-white/10 hover:border-cyber-cyan/60 hover:text-cyber-cyan text-text-muted transition-colors"
                  aria-label="Telegram"
                >
                  <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor"><path d="M9.04 15.5l-.36 4.27c.51 0 .73-.22 1.0-.48l2.4-2.3 4.97 3.64c.91.5 1.55.24 1.78-.85l3.23-15.13c.3-1.36-.49-1.9-1.38-1.57L1.32 9.5C0 10.04.02 10.78 1.1 11.1l5.16 1.6 11.99-7.55c.56-.34 1.07-.15.66.2L9.04 15.5z"/></svg>
                </button>
                <a
                  href="https://www.facebook.com/share/18riZnctui/"
                  target="_blank" rel="noreferrer"
                  data-testid="footer-facebook"
                  className="w-9 h-9 rounded-full flex items-center justify-center bg-white/5 border border-white/10 hover:border-cyber-cyan/60 hover:text-cyber-cyan text-text-muted transition-colors"
                  aria-label="Facebook"
                >
                  <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor"><path d="M22 12c0-5.523-4.477-10-10-10S2 6.477 2 12c0 4.991 3.657 9.128 8.438 9.878v-6.987h-2.54V12h2.54V9.797c0-2.506 1.492-3.89 3.777-3.89 1.094 0 2.238.195 2.238.195v2.46h-1.26c-1.243 0-1.63.771-1.63 1.562V12h2.773l-.443 2.89h-2.33v6.988C18.343 21.128 22 16.991 22 12z"/></svg>
                </a>
              </div>
            </div>

            <p className="text-text-muted text-[9px] sm:text-[10px] uppercase tracking-widest text-center mt-4">
              © 2026 Powered by TON Blockchain & Telegram Ecosystem
            </p>
          </div>
        </footer>
      </div>

      <TutorialModal 
        isOpen={showTutorial} 
        onClose={() => setShowTutorial(false)} 
        lang={lang}
      />

      {/* Telegram destinations chooser modal (channel / chat / bot) */}
      {showTgModal && (() => {
        const tg = TG_MODAL_I18N[lang] || TG_MODAL_I18N.en;
        const options = [
          { key: 'channel', href: TG_LINKS.channel, label: tg.channel, Icon: Radio, testid: 'tg-modal-channel' },
          { key: 'chat', href: TG_LINKS.chat, label: tg.chat, Icon: MessageCircle, testid: 'tg-modal-chat' },
          { key: 'bot', href: TG_LINKS.bot, label: tg.bot, Icon: Send, testid: 'tg-modal-bot' },
        ];
        return (
          <div
            className="fixed inset-0 z-[9998] flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm"
            data-testid="tg-modal-overlay"
            onClick={() => setShowTgModal(false)}
          >
            <div
              className="relative w-full max-w-sm rounded-2xl bg-[#0e1420] border border-cyber-cyan/25 shadow-2xl p-5 sm:p-6"
              data-testid="tg-modal"
              onClick={(e) => e.stopPropagation()}
            >
              <button
                type="button"
                onClick={() => setShowTgModal(false)}
                data-testid="tg-modal-close"
                aria-label={tg.close}
                className="absolute top-3 right-3 w-8 h-8 rounded-full flex items-center justify-center text-text-muted hover:text-white hover:bg-white/10 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>

              <div className="flex items-center gap-3 mb-1">
                <div className="w-10 h-10 rounded-xl bg-cyber-cyan/15 flex items-center justify-center shrink-0">
                  <svg className="w-5 h-5 text-cyber-cyan" viewBox="0 0 24 24" fill="currentColor"><path d="M9.04 15.5l-.36 4.27c.51 0 .73-.22 1.0-.48l2.4-2.3 4.97 3.64c.91.5 1.55.24 1.78-.85l3.23-15.13c.3-1.36-.49-1.9-1.38-1.57L1.32 9.5C0 10.04.02 10.78 1.1 11.1l5.16 1.6 11.99-7.55c.56-.34 1.07-.15.66.2L9.04 15.5z"/></svg>
                </div>
                <div>
                  <h3 className="text-white font-bold text-base leading-tight">{tg.title}</h3>
                  <p className="text-text-muted text-xs">{tg.subtitle}</p>
                </div>
              </div>

              <div className="mt-4 space-y-2.5">
                {options.map(({ key, href, label, Icon, testid }) => (
                  <a
                    key={key}
                    href={href}
                    target="_blank"
                    rel="noreferrer"
                    data-testid={testid}
                    onClick={() => setShowTgModal(false)}
                    className="flex items-center gap-3 w-full px-4 py-3 rounded-xl bg-white/5 border border-white/10 hover:border-cyber-cyan/60 hover:bg-cyber-cyan/10 text-white transition-colors group"
                  >
                    <Icon className="w-5 h-5 text-cyber-cyan shrink-0" />
                    <span className="font-medium text-sm flex-1">{label}</span>
                    <span className="text-text-muted group-hover:text-cyber-cyan transition-colors">→</span>
                  </a>
                ))}
              </div>
            </div>
          </div>
        );
      })()}
    </div>
  );
}
