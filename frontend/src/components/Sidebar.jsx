import { useState, useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { MessagesSquare, 
  Settings, Map, Store, Trophy, 
  GraduationCap, Building2, MessageCircle, ShoppingBag,
  ArrowDownToLine, ArrowUpFromLine, Wallet, Landmark, History,
  Shield, User, LayoutDashboard, ListChecks
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { DepositModal, WithdrawModal } from './BalanceModals';
import SupportModal from './SupportModal';
import NotificationCenter, { NotificationBellButton, useNotificationsCount, useChatUnreadCount, formatBadgeCount } from './NotificationCenter';
import { useTranslation } from '@/lib/translations';
import { useLanguage } from '@/context/LanguageContext';
import { useTutorial } from '@/context/TutorialContext';
import { tonToCity, formatCity, formatTon } from '@/lib/currency';
import { getGameMode, showDemoBlockedToast } from '@/lib/gameMode';
import axios from 'axios';
import { ADMIN_PATH } from '@/lib/adminPath';
import useQuestReadyCount from '@/hooks/useQuestReadyCount';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api`;

export default function Sidebar({ user, onBalanceUpdate, refreshBalance }) {
  const location = useLocation();
  const navigate = useNavigate();
  const isHomePage = location.pathname === '/';
  const [isHovered, setIsHovered] = useState(false);
  const [supportLink, setSupportLink] = useState('https://telegram.me/support');
  const [showSupportModal, setShowSupportModal] = useState(false);

  // Auto-open support modal when arriving via Telegram link with ?support=open
  // (also reads sessionStorage flag set by App.js magic-link handler)
  useEffect(() => {
    try {
      const params = new URLSearchParams(window.location.search);
      const flagFromUrl = params.get('support') === 'open';
      const flagFromStorage = sessionStorage.getItem('open_support_modal') === '1';
      if (flagFromUrl || flagFromStorage) {
        setShowSupportModal(true);
        sessionStorage.removeItem('open_support_modal');
        if (flagFromUrl) {
          params.delete('support');
          const qs = params.toString();
          const newUrl = window.location.pathname + (qs ? `?${qs}` : '') + window.location.hash;
          window.history.replaceState({}, '', newUrl);
        }
      }
    } catch (e) { /* ignore */ }
  }, []);
  const [showDepositModal, setShowDepositModal] = useState(false);
  const [showWithdrawModal, setShowWithdrawModal] = useState(false);
  const [showNotifications, setShowNotifications] = useState(false);
  const notifState = useNotificationsCount(user);
  const chatUnread = useChatUnreadCount(user);
  const questReady = useQuestReadyCount(user);
  const [balanceTon, setBalanceTon] = useState(user?.balance_ton || 0);
  const [depositAddress, setDepositAddress] = useState('');
  
  // Calculate $CITY balance
  const balanceCity = tonToCity(balanceTon);

  // Demo mode uses a fully separate virtual balance (demo_balance_city).
  const isDemoMode = getGameMode() === 'demo';
  const [demoBalanceCity, setDemoBalanceCity] = useState(null);
  useEffect(() => {
    if (!isDemoMode) { setDemoBalanceCity(null); return; }
    let cancelled = false;
    const loadDemoBalance = async () => {
      try {
        const tok = localStorage.getItem('token');
        const r = await fetch(`${API}/demo/state`, { headers: tok ? { Authorization: `Bearer ${tok}` } : {} });
        if (!r.ok) return;
        const d = await r.json();
        if (!cancelled) setDemoBalanceCity(Number(d?.profile?.demo_balance_city ?? 0));
      } catch (e) { /* ignore */ }
    };
    loadDemoBalance();
    const onDemoBal = () => loadDemoBalance();
    window.addEventListener('demoBalanceUpdate', onDemoBal);
    return () => { cancelled = true; window.removeEventListener('demoBalanceUpdate', onDemoBal); };
  }, [isDemoMode]);

  // What the sidebar actually shows: real balance + bonus balance (spec:
  // Total Balance = bonus_balance + real_balance). Bonus is spendable in-game.
  const bonusTon = Number(user?.bonus_balance || 0);
  const displayCity = isDemoMode ? (demoBalanceCity ?? 0) : tonToCity(balanceTon + bonusTon);
  const displayTon = isDemoMode ? (displayCity / 1000) : (balanceTon + bonusTon);
  
  // Get language from context
  const { language: lang } = useLanguage();
  const { t } = useTranslation(lang);

  // Labels for the "Main"/"Bonus" balance breakdown (shown under the TON total).
  const BAL_MAIN_LABEL = { ru: 'Основной', en: 'Main', es: 'Principal', zh: '主要', fr: 'Principal', de: 'Haupt', ja: 'メイン', ko: '기본', id: 'Utama' };
  const BAL_BONUS_LABEL = { ru: 'Бонусы', en: 'Bonus', es: 'Bono', zh: '奖励', fr: 'Bonus', de: 'Bonus', ja: 'ボーナス', ko: '보너스', id: 'Bonus' };
  const mainLabel = BAL_MAIN_LABEL[lang] || BAL_MAIN_LABEL.ru;
  const bonusLabel = BAL_BONUS_LABEL[lang] || BAL_BONUS_LABEL.ru;

  // Tutorial gating
  const tutorial = useTutorial();
  const isTutorialActive = !!tutorial?.active;
  const allowedRoute = tutorial?.getAllowedRoute ? tutorial.getAllowedRoute() : null;
  // If tutorial targets a sidebar element, force sidebar expanded — but ONLY
  // until the user reaches the target route. Once they're on the destination
  // page, the sidebar collapses so the user can read the tutorial card +
  // explore the page without the panel getting in the way.
  const tutorialTargetSelector = tutorial?.currentStep?.target_selector;
  const tutorialTargetRoute    = tutorial?.currentStep?.target_route;
  const isAlreadyOnTarget = !!tutorialTargetRoute
    && (location.pathname === tutorialTargetRoute
        || (tutorialTargetRoute === '/island' && ['/ton-island', '/island', '/map', '/game'].includes(location.pathname)));
  const shouldForceExpand = isTutorialActive
    && !isAlreadyOnTarget
    && typeof tutorialTargetSelector === 'string'
    && (tutorialTargetSelector === 'sidebar-logo' || tutorialTargetSelector.startsWith('sidebar-nav-'));

  useEffect(() => {
    // Fetch support link and deposit address from config
    fetch(`${API}/config`)
      .then(r => r.json())
      .then(data => {
        if (data.support_telegram) {
          setSupportLink(data.support_telegram);
        }
        if (data.deposit_address) {
          setDepositAddress(data.deposit_address);
        }
      })
      .catch(() => {});
  }, []);

  // Update balance when user changes
  useEffect(() => {
    if (user?.balance_ton !== undefined) {
      setBalanceTon(user.balance_ton);
    }
  }, [user?.balance_ton]);

  // Balance is updated via props from App.js, no auto-refresh needed

  const handleDepositSuccess = async () => {
    // Немедленно обновляем баланс из БД
    try {
      const token = localStorage.getItem('token') || localStorage.getItem('ton_city_token');
      if (!token) return;
      const response = await axios.get(`${API}/auth/me`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      const newBalance = response.data.balance_ton || 0;
      setBalanceTon(newBalance);
      if (onBalanceUpdate) onBalanceUpdate(newBalance);
      // Dispatch global event so App.js updates user state immediately
      window.dispatchEvent(new CustomEvent('balanceUpdate', { detail: { balance: newBalance } }));
    } catch (error) {
      console.error('Error refreshing balance:', error);
    }
  };

  const handleWithdrawSuccess = async () => {
    // Немедленно обновляем баланс из БД
    try {
      const token = localStorage.getItem('token') || localStorage.getItem('ton_city_token');
      if (!token) return;
      const response = await axios.get(`${API}/auth/me`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      const newBalance = response.data.balance_ton || 0;
      setBalanceTon(newBalance);
      if (onBalanceUpdate) onBalanceUpdate(newBalance);
      // Dispatch global event so App.js updates user state immediately
      window.dispatchEvent(new CustomEvent('balanceUpdate', { detail: { balance: newBalance } }));
    } catch (error) {
      console.error('Error refreshing balance:', error);
    }
  };

  // Sidebar открыт только при наведении (на всех страницах включая главную).
  // Во время туториала ховер-разворот ОТКЛЮЧЁН — открыть сайдбар можно
  // только если шаг туториала явно подсвечивает sidebar-элемент
  // (тогда `shouldForceExpand` принудительно разворачивает панель).
  const isExpanded = shouldForceExpand || (!isTutorialActive && isHovered);

  // Текст лейблов появляется ПОСЛЕ раскрытия сайдбара (с задержкой),
  // а при закрытии скрывается ДО начала сворачивания панели.
  // Это устраняет "вылет" текста за край свёрнутого сайдбара.
  const [showLabels, setShowLabels] = useState(false);
  useEffect(() => {
    if (isExpanded) {
      const t = setTimeout(() => setShowLabels(true), 180);
      return () => clearTimeout(t);
    }
    setShowLabels(false);
  }, [isExpanded]);

  // Если юзер не залогинен, не показываем меню вообще
  if (!user) return null;

  return (
    <>
      <motion.div
        initial={{ x: -100, opacity: 0 }}
        animate={{ x: 0, opacity: 1 }}
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => setIsHovered(false)}
        style={{ top: 'var(--tg-safe-top, 0px)' }}
        className={`fixed left-0 z-40 hidden lg:flex flex-col
          transition-all duration-300 ${isExpanded ? 'w-64' : 'w-[68px]'}`}
      >
        <div className="flex flex-col gap-1.5 p-2 bg-gradient-to-b from-[#1a1a2e] to-[#0f0f1a] backdrop-blur-xl border border-cyber-cyan/20 rounded-2xl shadow-2xl shadow-cyber-cyan/10">
          
          {/* Logo - always visible, links to home */}
          {(() => {
            const logoDisabled = isTutorialActive && allowedRoute && allowedRoute !== '/';
            const isLogoHighlighted = isTutorialActive && tutorialTargetSelector === 'sidebar-logo';
            return (
              <div
                className={`flex items-center gap-2 p-2 rounded-xl transition-colors mb-1
                  ${isExpanded ? '' : 'justify-center'}
                  ${logoDisabled ? 'opacity-30 cursor-not-allowed pointer-events-none' : 'cursor-pointer hover:bg-white/5'}
                  ${isLogoHighlighted ? 'ring-2 ring-cyber-cyan' : ''}`}
                onClick={() => { if (!logoDisabled) navigate('/'); }}
                onKeyDown={(e) => { if ((e.key === 'Enter' || e.key === ' ') && !logoDisabled) { e.preventDefault(); navigate('/'); } }}
                data-testid="sidebar-logo"
                role="link"
                tabIndex={logoDisabled ? -1 : 0}
                aria-label="GRAM City — home"
                title="GRAM City"
              >
                <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyber-cyan to-neon-purple flex items-center justify-center shadow-lg shadow-cyber-cyan/20 flex-shrink-0">
                  <Building2 className="w-5 h-5 text-black" />
                </div>
                {isExpanded && (
                  <span className="font-unbounded text-sm font-bold text-text-main tracking-tighter whitespace-nowrap">
                    GRAM <span className="text-cyber-cyan">CITY</span>
                  </span>
                )}
              </div>
            );
          })()}

          {/* Balance Section */}
          <div className={`p-3 bg-gradient-to-r from-cyber-cyan/10 to-purple-500/10 rounded-xl border border-cyber-cyan/20 mb-2 ${!(isExpanded && showLabels) ? 'hidden' : ''}`}>
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <Wallet className="w-4 h-4 text-cyber-cyan" />
                <span className="text-xs text-text-muted uppercase tracking-wider">{t('sidebarBalance')}</span>
              </div>
              <div className="flex items-center gap-1">
                <Button
                  size="icon"
                  variant="ghost"
                  onClick={() => navigate('/history')}
                  className="w-6 h-6 text-text-muted hover:text-white hover:bg-white/10"
                  title={t('transactionHistory')}
                >
                  <History className="w-4 h-4" />
                </Button>
                <Button
                  size="icon"
                  variant="ghost"
                  onClick={() => navigate('/settings')}
                  data-testid="sidebar-settings-btn"
                  className="w-6 h-6 text-text-muted hover:text-white hover:bg-white/10"
                  title={t('settings')}
                >
                  <Settings className="w-4 h-4" />
                </Button>
              </div>
            </div>
            {/* Balance display: $CITY primary, TON secondary */}
            <div className="mb-3">
              <div className="text-xl font-bold text-white" data-testid="sidebar-balance-city">
                {formatCity(displayCity)} <span className="text-yellow-400 text-sm">$CITY</span>
              </div>
              <div className="text-xs text-text-muted mt-0.5">
                ≈ {formatTon(displayTon)} TON
              </div>
              {!isDemoMode && (
                <>
                  <div className="text-xs text-text-muted mt-0.5" data-testid="sidebar-balance-main">
                    {mainLabel}: {formatCity(tonToCity(balanceTon))} $CITY ({formatTon(balanceTon)} TON)
                  </div>
                  <div className="text-xs text-text-muted mt-0.5" data-testid="sidebar-balance-bonus">
                    {bonusLabel}: {formatCity(tonToCity(bonusTon))} $CITY ({formatTon(bonusTon)} TON)
                  </div>
                </>
              )}
            </div>
            <div className="grid grid-cols-2 gap-2">
              {!isDemoMode && (
                <Button
                  size="sm"
                  onClick={() => { if (!isTutorialActive) setShowDepositModal(true); }}
                  disabled={isTutorialActive}
                  className="w-full bg-green-600 hover:bg-green-700 text-xs h-9 px-2 disabled:opacity-50 disabled:cursor-not-allowed"
                  data-testid="sidebar-deposit-btn"
                >
                  <ArrowDownToLine className="w-4 h-4 mr-1 flex-shrink-0" />
                  {t('sidebarDeposit')}
                </Button>
              )}
              {!isDemoMode && (
                <Button
                  size="sm"
                  onClick={() => { if (!isTutorialActive) setShowWithdrawModal(true); }}
                  disabled={isTutorialActive}
                  className="w-full bg-orange-600 hover:bg-orange-700 text-xs h-9 px-2 disabled:opacity-50 disabled:cursor-not-allowed"
                  data-testid="sidebar-withdraw-btn"
                >
                  <ArrowUpFromLine className="w-4 h-4 mr-1 flex-shrink-0" />
                  {t('sidebarWithdraw')}
                </Button>
              )}
            </div>
          </div>
          
          {/* Compact balance for collapsed state */}
          {!(isExpanded && showLabels) && (
            <div 
              className={`p-2 bg-cyber-cyan/10 rounded-xl text-center transition-colors mb-2 ${
                isDemoMode ? '' : (isTutorialActive ? 'opacity-60 cursor-not-allowed' : 'cursor-pointer hover:bg-cyber-cyan/20')
              }`}
              onClick={() => { if (isDemoMode || isTutorialActive) return; setShowDepositModal(true); }}
              onKeyDown={(e) => {
                if (isDemoMode || isTutorialActive) return;
                if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setShowDepositModal(true); }
              }}
              role={isDemoMode ? undefined : 'button'}
              tabIndex={isDemoMode || isTutorialActive ? -1 : 0}
              aria-disabled={isTutorialActive}
              aria-label={`${t('sidebarBalance')}: ${displayTon.toFixed(1)} TON${isDemoMode ? '' : '. ' + t('sidebarDeposit')}`}
              title={`${t('sidebarBalance')}: ${displayTon.toFixed(1)} TON`}
              data-testid="sidebar-balance-compact"
            >
              <Wallet className="w-5 h-5 text-cyber-cyan mx-auto" />
              <div className="text-xs text-cyber-cyan mt-1 font-bold">{displayTon.toFixed(1)}</div>
            </div>
          )}
          
          <NavItem icon={<Map className="w-5 h-5" />} label={t('sidebarMap')} path="/maps" isExpanded={isExpanded} testId="sidebar-nav-map" />
          <NavItem icon={<Building2 className="w-5 h-5" />} label={t('sidebarMyBusinesses')} path="/my-businesses" isExpanded={isExpanded} testId="sidebar-nav-my-businesses" />
          <NavItem icon={<Store className="w-5 h-5" />} label={t('sidebarMarketplace')} path="/marketplace" isExpanded={isExpanded} testId="sidebar-nav-marketplace" blockedInDemo />
          <NavItem icon={<ShoppingBag className="w-5 h-5" />} label={t('sidebarTrading')} path="/trading" isExpanded={isExpanded} testId="sidebar-nav-trading" />
          <NavItem icon={<ListChecks className="w-5 h-5 text-yellow-400" />} label={<span className="gold-blink">{t('sidebarTasks')}</span>} path="/tasks" isExpanded={isExpanded} testId="sidebar-nav-tasks" badgeCount={questReady} />
          <NavItem icon={<Landmark className="w-5 h-5" />} label={t('sidebarCredits')} path="/credit" isExpanded={isExpanded} testId="sidebar-nav-credit" blockedInDemo />
          <NavItem icon={<Trophy className="w-5 h-5" />} label={t('sidebarLeaderboard')} path="/leaderboard" isExpanded={isExpanded} testId="sidebar-nav-leaderboard" blockedInDemo />
          <NavItem icon={<MessagesSquare className="w-5 h-5 text-cyber-cyan" />} label={t('navCommunity')} path="/community" isExpanded={isExpanded} testId="sidebar-nav-community" />
          <NavItem icon={<MessageCircle className="w-5 h-5" />} label={t('sidebarChat')} path="/chat" isExpanded={isExpanded} testId="sidebar-nav-chat" badgeCount={chatUnread.count} />
          <div data-testid="sidebar-nav-notifications">
            <NotificationBellButton
              count={notifState.count}
              hasCritical={notifState.hasCritical}
              shake={notifState.shake}
              onClick={() => { if (!isTutorialActive) setShowNotifications(true); }}
              label={t('sidebarNotifications') || 'Уведомления'}
              isExpanded={isExpanded && showLabels}
              dataTestid="sidebar-notif-btn"
              disabled={isTutorialActive}
            />
          </div>
          
          {/* Admin Panel Button - only for admins */}
          {user?.is_admin && (
            <>
              <div className="h-px bg-red-500/20 mx-2 my-1" />
              <NavItem 
                icon={<Shield className="w-5 h-5" />} 
                label={t('sidebarAdminPanel')} 
                path={ADMIN_PATH} 
                isExpanded={isExpanded}
                isAdmin={true}
                testId="sidebar-nav-admin"
              />
            </>
          )}
          
          <div className="h-px bg-cyber-cyan/20 mx-2 my-1" />
          <button 
            type="button"
            onClick={() => setShowSupportModal(true)}
            data-testid="sidebar-support-btn"
            className={`w-full flex items-center gap-3 p-3 rounded-xl cursor-pointer transition-all text-green-400 hover:bg-green-500/10 border border-transparent text-left ${isExpanded ? '' : 'justify-center'}`}
          >
            <div className="min-w-[20px] flex items-center justify-center">
              <MessageCircle className="w-5 h-5" />
            </div>
            {isExpanded && showLabels && (
              <span className="font-bold text-xs uppercase tracking-widest whitespace-nowrap">
                {t('sidebarSupport')}
              </span>
            )}
          </button>
        </div>
      </motion.div>

      {/* Modals */}
      <SupportModal
        open={showSupportModal}
        onOpenChange={setShowSupportModal}
        language={lang}
        currentUser={user}
      />
      <DepositModal
        isOpen={showDepositModal}
        onClose={() => setShowDepositModal(false)}
        onSuccess={handleDepositSuccess}
        receiverAddress={depositAddress}
        updateBalance={(newBal) => {
          setBalanceTon(newBal);
          if (onBalanceUpdate) onBalanceUpdate(newBal);
        }}
      />
      
      <WithdrawModal
        isOpen={showWithdrawModal}
        onClose={() => setShowWithdrawModal(false)}
        onSuccess={handleWithdrawSuccess}
        currentBalance={balanceTon}
        userWallet={user?.wallet_address}
        updateBalance={(newBal) => {
          setBalanceTon(newBal);
          if (onBalanceUpdate) onBalanceUpdate(newBal);
        }}
      />

      <NotificationCenter
        open={showNotifications}
        onClose={() => setShowNotifications(false)}
        user={user}
      />
    </>
  );

  function NavItem({ icon, label, path, isExpanded, isAdmin = false, testId, onClick, disabled = false, badgeCount = 0, blockedInDemo = false }) {
    const isActive = path ? location.pathname === path : false;
    // Normalize map/island/game to same path for tutorial matching
    const normalizedAllowed = allowedRoute === '/island' ? ['/ton-island', '/island', '/map', '/game'] : (allowedRoute ? [allowedRoute] : []);
    const isDisabledByTutorial = (isTutorialActive && allowedRoute && path && !normalizedAllowed.includes(path)) || disabled;
    const isBlockedDemo = blockedInDemo && isDemoMode;

    const handleClick = () => {
      if (isDisabledByTutorial) return;
      if (isBlockedDemo) { showDemoBlockedToast(); return; }
      if (onClick) { onClick(); return; }
      if (path) navigate(path);
    };

    return (
      <div
        onClick={handleClick}
        onKeyDown={(e) => { if ((e.key === 'Enter' || e.key === ' ') && !isDisabledByTutorial) { e.preventDefault(); handleClick(); } }}
        data-testid={testId}
        role="link"
        tabIndex={isDisabledByTutorial ? -1 : 0}
        aria-label={typeof label === 'string' ? label : undefined}
        aria-current={isActive ? 'page' : undefined}
        aria-disabled={isDisabledByTutorial || undefined}
        title={typeof label === 'string' ? label : undefined}
        className={`relative flex items-center gap-3 p-3 rounded-xl transition-all
          outline-none focus-visible:ring-2 focus-visible:ring-cyber-cyan/60
          ${isExpanded ? '' : 'justify-center'}
          ${isDisabledByTutorial ? 'opacity-30 cursor-not-allowed pointer-events-none' : 'cursor-pointer'}
          ${isBlockedDemo ? 'opacity-60' : ''}
          ${isActive 
            ? isAdmin
              ? 'text-red-400 bg-red-500/20 border border-red-500/30 shadow-lg shadow-red-500/10'
              : 'text-cyber-cyan bg-cyber-cyan/20 border border-cyber-cyan/30 shadow-lg shadow-cyber-cyan/10' 
            : isAdmin
              ? 'text-red-400/70 hover:bg-red-500/10 hover:text-red-400 border border-transparent'
              : 'text-white/70 hover:bg-white/10 hover:text-white border border-transparent'
          }`}
      >
        <div className="min-w-[20px] flex items-center justify-center relative">
          {icon}
          {badgeCount > 0 && (
            <span
              data-testid={testId ? `${testId}-badge` : 'nav-badge'}
              className="absolute -top-1.5 -right-2 min-w-[17px] h-[17px] px-1 rounded-full text-[10px] font-bold flex items-center justify-center bg-cyber-cyan text-black"
            >
              {formatBadgeCount(badgeCount)}
            </span>
          )}
        </div>
        {isExpanded && showLabels && (
          <span className="font-bold text-xs uppercase tracking-widest whitespace-nowrap">
            {label}
          </span>
        )}
      </div>
    );
  }
}
