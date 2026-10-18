import { useState, useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Home, Map, ShoppingBag, Settings, MessageCircle, X,
  Building2, GraduationCap, Store, Wallet,
  ArrowDownToLine, ArrowUpFromLine, Shield, AlertCircle, Link2, Landmark, History, Headphones, Bell, ListChecks
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useTranslation } from '@/lib/translations';
import { DepositModal, WithdrawModal } from './BalanceModals';
import SupportModal from './SupportModal';
import NotificationCenter, { useNotificationsCount, NotificationBellIcon, useChatUnreadCount, formatBadgeCount } from './NotificationCenter';
import { tonToCity, formatCity, formatTon } from '@/lib/currency';
import { useTutorial } from '@/context/TutorialContext';
import { useLanguage } from '@/context/LanguageContext';
import { hapticImpact, hapticSelection } from '@/lib/telegramHaptic';
import { ADMIN_PATH } from '@/lib/adminPath';
import { getGameMode, showDemoBlockedToast } from '@/lib/gameMode';
import SmartAvatar from '@/components/SmartAvatar';
import { runAfterFirstInteraction } from '@/lib/firstGesture';
import useQuestReadyCount from '@/hooks/useQuestReadyCount';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

export default function MobileNav({ user, refreshBalance }) {
  const location = useLocation();
  const navigate = useNavigate();
  const tutorial = useTutorial();
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const [showDeposit, setShowDeposit] = useState(false);
  const [showWithdraw, setShowWithdraw] = useState(false);
  const [showWalletWarning, setShowWalletWarning] = useState('');
  const [depositAddress, setDepositAddress] = useState('');
  const [supportTelegram, setSupportTelegram] = useState('');
  const [showSupportModal, setShowSupportModal] = useState(false);
  const [showNotifications, setShowNotifications] = useState(false);
  const notifState = useNotificationsCount(user);
  const chatUnread = useChatUnreadCount(user);
  const questReady = useQuestReadyCount(user);
  // Use the shared language context so the burger menu re-renders when the
  // user changes language anywhere else in the app (Settings / Landing).
  const { language: lang } = useLanguage();
  const { t } = useTranslation(lang);

  // Labels for the "Main"/"Bonus" balance breakdown (shown under the TON total).
  const BAL_MAIN_LABEL = { ru: 'Основной', en: 'Main', es: 'Principal', zh: '主要', fr: 'Principal', de: 'Haupt', ja: 'メイン', ko: '기본', id: 'Utama' };
  const BAL_BONUS_LABEL = { ru: 'Бонусы', en: 'Bonus', es: 'Bono', zh: '奖励', fr: 'Bonus', de: 'Bonus', ja: 'ボーナス', ko: '보너스', id: 'Bonus' };
  const mainLabel = BAL_MAIN_LABEL[lang] || BAL_MAIN_LABEL.ru;
  const bonusLabel = BAL_BONUS_LABEL[lang] || BAL_BONUS_LABEL.ru;

  const isDemoMode = getGameMode() === 'demo';
  const [demoBalanceCity, setDemoBalanceCity] = useState(null);
  useEffect(() => {
    if (!isDemoMode) { setDemoBalanceCity(null); return; }
    let cancelled = false;
    const load = async () => {
      try {
        const tok = localStorage.getItem('token');
        const r = await fetch(`${BACKEND_URL}/api/demo/state`, { headers: tok ? { Authorization: `Bearer ${tok}` } : {} });
        if (!r.ok) return;
        const d = await r.json();
        if (!cancelled) setDemoBalanceCity(Number(d?.profile?.demo_balance_city ?? 0));
      } catch (e) { /* ignore */ }
    };
    load();
    const onBal = () => load();
    window.addEventListener('demoBalanceUpdate', onBal);
    return () => { cancelled = true; window.removeEventListener('demoBalanceUpdate', onBal); };
  }, [isDemoMode]);
  const displayCityMobile = isDemoMode ? (demoBalanceCity ?? 0) : tonToCity((user?.balance_ton || 0) + Number(user?.bonus_balance || 0));
  const displayTonMobile = isDemoMode ? (displayCityMobile / 1000) : ((user?.balance_ton || 0) + Number(user?.bonus_balance || 0));

  // Load config including deposit address (deferred so cold start is silent).
  useEffect(() => {
    runAfterFirstInteraction(() => {
      fetch(`${BACKEND_URL}/api/config`)
        .then(r => r.json())
        .then(data => {
          if (data.deposit_address) {
            setDepositAddress(data.deposit_address);
          }
          if (data.support_telegram) {
            setSupportTelegram(data.support_telegram);
          }
        })
        .catch(() => {});
    });
  }, []);

  // Listen for toggle events from PageHeader.
  // Во время туториала на «обычной» странице игнорируем — пусть пользователь
  // не выходит за пределы шага. Открыть burger-меню можно только если шаг
  // явно подсвечивает элемент внутри меню (mobile-menu-item-*).
  useEffect(() => {
    const handler = () => {
      const sel = tutorial?.currentStep?.mobile_target_selector || '';
      const tutorialAllowsBurger = !!sel && sel.startsWith('mobile-menu-item-');
      if (tutorial?.active && !tutorialAllowsBurger) return;
      setIsMenuOpen(prev => !prev);
    };
    window.addEventListener('toggle-mobile-menu', handler);
    return () => window.removeEventListener('toggle-mobile-menu', handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tutorial?.active, tutorial?.currentStep?.mobile_target_selector]);

  // Close menu on route change
  useEffect(() => {
    setIsMenuOpen(false);
  }, [location.pathname]);

  // Auto-open burger menu ONLY for tutorial steps that point at an item
  // INSIDE the burger menu (mobile_target_selector === "mobile-menu-item-*").
  // For on-page targets (e.g. a button on /trading, a resource card on
  // /my-businesses) we must NOT auto-open the drawer.
  useEffect(() => {
    if (!tutorial?.active) return;
    const sel = tutorial?.currentStep?.mobile_target_selector;
    if (!sel || !sel.startsWith('mobile-menu-item-')) return;
    setIsMenuOpen(true);
  }, [tutorial?.active, tutorial?.currentStep?.mobile_target_selector]);

  // Не показываем на странице авторизации
  if (location.pathname.startsWith('/auth')) return null;
  // Не показываем если нет пользователя
  if (!user) return null;

  const menuItems = [
    { icon: Home, label: t('menuHome') || t('home') || 'Home', path: '/' },
    { icon: Map, label: t('menuMap') || t('map') || 'Map', path: '/maps', testKey: 'map' },
    { icon: Building2, label: t('myBusinesses') || t('menuMyBusinesses') || 'My Businesses', path: '/my-businesses' },
    { icon: Store, label: t('marketplace') || t('menuMarket') || 'Marketplace', path: '/marketplace', blockedInDemo: true },
    { icon: ShoppingBag, label: t('trading') || t('menuTrading') || 'Trading', path: '/trading' },
    { icon: ListChecks, label: t('sidebarTasks') || 'Tasks', path: '/tasks', gold: true, testKey: 'tasks', badgeCount: questReady },
    { icon: Landmark, label: t('menuCredits') || t('credits') || 'Credits', path: '/credit', blockedInDemo: true },
    { icon: History, label: t('menuHistory') || t('transactionHistory') || 'History', path: '/history' },
    { icon: MessageCircle, label: t('chat') || 'Chat', path: '/chat', badgeCount: chatUnread.count },
    { icon: Settings, label: t('settings') || t('menuSettings') || 'Settings', path: '/settings' },
  ];

  // Если пользователь - админ, добавляем ссылку на админку (скрытый путь)
  if (user?.is_admin) {
    menuItems.push({ icon: Shield, label: t('menuAdmin') || t('adminPanel') || 'Admin', path: ADMIN_PATH });
  }

  const handleNavigation = (item) => {
    hapticSelection();
    if (item && item.blockedInDemo && isDemoMode) {
      showDemoBlockedToast();
      setIsMenuOpen(false);
      return;
    }
    if (item && item.action === 'tutorial') {
      if (tutorial?.launch) tutorial.launch();
      setIsMenuOpen(false);
      return;
    }
    if (item && item.action === 'notifications') {
      setIsMenuOpen(false);
      setShowNotifications(true);
      return;
    }
    const path = typeof item === 'string' ? item : item.path;
    if (path) navigate(path);
    setIsMenuOpen(false);
  };

  return (
    <>
      {/* Telegram safe-area top fill — paints a subtle dark blur strip
          exactly under the «Закрыть/˅/⋮» chrome so the burger button + page
          background never look "cut" against blank phone canvas. Invisible
          outside Telegram (height collapses to 0). */}
      <div className="tg-top-fill lg:hidden" aria-hidden />

      {/* Hamburger Button - Fixed, shown on all pages on mobile (only when menu is closed).
          Во время туториала кнопка бургера скрыта — пользователь должен оставаться
          в рамках текущей страницы и ничего не нажимать мимо туториала.
          Исключение: шаг, который явно указывает на пункт burger-меню (mobile-menu-item-*).
          v2.3.x: also hide the burger while the tutorial status is still
          loading — otherwise the button flickers for ~300ms during route
          transitions (e.g. /ton-island → /maps → pick_ton_island step)
          and lets the user accidentally break the tutorial flow.
       */}
      {!isMenuOpen && (() => {
        const sel = tutorial?.currentStep?.mobile_target_selector || '';
        const tutorialAllowsBurger = !!sel && sel.startsWith('mobile-menu-item-');
        // Treat "status not loaded yet" as "possibly active" so the burger
        // stays hidden until we KNOW the tutorial is inactive/completed.
        const tutorialActiveOrLoading = !!tutorial?.active
          || (tutorial && !tutorial.statusLoaded && !tutorial.completed);
        if (tutorialActiveOrLoading && !tutorialAllowsBurger) return null;
        // v2.3.x (Task 3): on the «Мои бизнесы» (go_businesses) and «Рейтинг»
        // (go_leaderboard) reading moments — i.e. once the user has ALREADY
        // navigated to the target page — the burger must be non-clickable so
        // the user can't accidentally open the menu and break the flow. Before
        // arrival it stays clickable (needed to navigate via the menu items).
        const _stepId = tutorial?.currentStep?.id || '';
        const _targetRoute = tutorial?.currentStep?.target_route || '';
        const burgerLocked = !!tutorial?.active
          && (_stepId === 'go_businesses' || _stepId === 'go_leaderboard')
          && !!_targetRoute && location.pathname === _targetRoute;
        return (
        <div
          className="lg:hidden fixed left-3 z-[60]"
          style={{ top: 'calc(var(--tg-safe-top, 0px) + 0.75rem)' }}
        >
          <Button
            data-testid="mobile-menu-toggle"
            onClick={() => { if (burgerLocked) return; hapticImpact('light'); setIsMenuOpen(true); }}
            disabled={burgerLocked}
            aria-disabled={burgerLocked}
            variant="ghost"
            size="icon"
            className={`w-10 h-10 rounded-xl bg-black/80 backdrop-blur-xl border border-white/10 text-white transition-all duration-300 ${burgerLocked ? 'opacity-40 cursor-not-allowed pointer-events-none' : 'hover:bg-white/10'}`}
          >
            <div className="flex flex-col items-center justify-center gap-[5px] w-5 h-5">
              <span className="block w-4 h-[2px] bg-current rounded-full" />
              <span className="block w-4 h-[2px] bg-current rounded-full" />
              <span className="block w-4 h-[2px] bg-current rounded-full" />
            </div>
          </Button>
        </div>
        );
      })()}

      {/* Fullscreen Menu Overlay */}
      <AnimatePresence>
        {isMenuOpen && (
          <motion.div
            data-testid="mobile-menu-overlay"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="lg:hidden fixed inset-0 z-50 bg-void/98 backdrop-blur-xl"
          >
            {/* Background Grid Effect */}
            <div className="absolute inset-0 opacity-5 pointer-events-none">
              <div 
                className="absolute inset-0"
                style={{
                  backgroundImage: `linear-gradient(rgba(0, 240, 255, 0.1) 1px, transparent 1px), linear-gradient(90deg, rgba(0, 240, 255, 0.1) 1px, transparent 1px)`,
                  backgroundSize: '40px 40px',
                }}
              />
            </div>

            {/* Menu Content */}
            <motion.div
              initial={{ y: 20, opacity: 0 }}
              animate={{ y: 0, opacity: 1 }}
              exit={{ y: 20, opacity: 0 }}
              transition={{ delay: 0.1, duration: 0.3 }}
              className="relative h-full flex flex-col px-4 pb-8 overflow-y-auto"
              style={{ paddingTop: 'calc(var(--tg-safe-top, 0px) + 1rem)' }}
            >
              {/* User Profile Card with Close Button */}
              <div className="mb-6 p-4 bg-gradient-to-r from-cyber-cyan/10 to-neon-purple/10 rounded-2xl border border-cyber-cyan/20">
                <div className="flex items-center gap-3">
                  <SmartAvatar
                    avatar={user.avatar}
                    name={user.display_name || user.username}
                    className="w-12 h-12 rounded-full border-2 border-cyber-cyan shadow-lg shadow-cyber-cyan/30 flex-shrink-0 text-lg"
                  />
                  <div className="flex-1 min-w-0">
                    <p className="text-base font-bold text-white truncate">{user.display_name || user.username}</p>
                  </div>
                  {/* Bell icon (mobile-only) + Close in profile card */}
                  <NotificationBellIcon
                    count={notifState.count}
                    hasCritical={notifState.hasCritical}
                    shake={notifState.shake}
                    onClick={() => { setIsMenuOpen(false); setShowNotifications(true); }}
                    dataTestid="mobile-notif-bell"
                  />
                  <Button
                    onClick={() => setIsMenuOpen(false)}
                    variant="ghost"
                    size="icon"
                    className="w-10 h-10 rounded-xl bg-cyber-cyan text-black hover:bg-cyber-cyan/80 flex-shrink-0"
                  >
                    <X className="w-5 h-5" />
                  </Button>
                </div>
                
                {/* Balance */}
                <div className="mt-4 p-3 bg-black/30 rounded-xl">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <Wallet className="w-4 h-4 text-cyber-cyan" />
                      <span className="text-xs text-text-muted uppercase">{t('balance') || 'Balance'}</span>
                    </div>
                  </div>
                  {/* Balance: $CITY primary, TON secondary */}
                  <div className="text-2xl font-bold text-white">
                    {formatCity(displayCityMobile)} <span className="text-yellow-400 text-sm">$CITY</span>
                  </div>
                  <div className="text-xs text-text-muted mt-0.5">
                    ≈ {formatTon(displayTonMobile)} TON
                  </div>
                  {!isDemoMode && (
                    <>
                      <div className="text-xs text-text-muted mt-0.5" data-testid="mobilenav-balance-main">
                        {mainLabel}: {formatCity(tonToCity(user?.balance_ton || 0))} $CITY ({formatTon(user?.balance_ton || 0)} TON)
                      </div>
                      <div className="text-xs text-text-muted mt-0.5" data-testid="mobilenav-balance-bonus">
                        {bonusLabel}: {formatCity(tonToCity(user?.bonus_balance || 0))} $CITY ({formatTon(user?.bonus_balance || 0)} TON)
                      </div>
                    </>
                  )}
                </div>

                {/* Quick Actions — hidden in demo mode (no deposit/withdraw) */}
                {!isDemoMode && (
                <div className="grid grid-cols-2 gap-2 mt-3">
                  <Button
                    size="sm"
                    className="bg-green-600 hover:bg-green-700 text-xs h-10"
                    onClick={() => {
                      if (user.wallet_address) {
                        setIsMenuOpen(false);
                        setShowDeposit(true);
                      } else {
                        setShowWalletWarning('deposit');
                      }
                    }}
                  >
                    <ArrowDownToLine className="w-4 h-4 mr-2" />
                    {t('deposit') || 'Deposit'}
                  </Button>
                  <Button
                    size="sm"
                    className="bg-orange-600 hover:bg-orange-700 text-xs h-10"
                    onClick={() => {
                      if (user.wallet_address) {
                        setIsMenuOpen(false);
                        setShowWithdraw(true);
                      } else {
                        setShowWalletWarning('withdraw');
                      }
                    }}
                  >
                    <ArrowUpFromLine className="w-4 h-4 mr-2" />
                    {t('withdraw') || 'Withdraw'}
                  </Button>
                </div>
                )}

                {/* Wallet Warning */}
                {showWalletWarning && (
                  <div className="mt-2 p-3 rounded-xl bg-red-900/30 border border-red-700/50">
                    <div className="flex items-start gap-2">
                      <AlertCircle className="w-5 h-5 text-red-400 shrink-0 mt-0.5" />
                      <div>
                        <p className="text-sm text-red-300 font-medium">
                          {t('walletRequiredFor') || (showWalletWarning === 'deposit' 
                            ? (t('walletRequiredDeposit') || 'To deposit, you need to link a TON wallet') 
                            : (t('walletRequiredWithdraw') || 'To withdraw, you need to link a TON wallet'))}
                        </p>
                        <Button
                          size="sm"
                          className="mt-2 bg-blue-600 hover:bg-blue-700 text-xs h-8"
                          onClick={() => {
                            setShowWalletWarning('');
                            handleNavigation('/settings');
                          }}
                        >
                          <Link2 className="w-3 h-3 mr-1" />
                          {t('linkWallet') || 'Link Wallet'}
                        </Button>
                      </div>
                    </div>
                  </div>
                )}
              </div>

              {/* Menu Items */}
              <nav className="flex-1 space-y-2">
                {menuItems.map((item, index) => {
                  const Icon = item.icon;
                  const isActive = item.path ? location.pathname === item.path : false;
                  const testKey = item.testKey || (item.path ? (item.path.replace('/', '') || 'home') : (item.action || 'action'));
                  const isBlockedDemo = !!item.blockedInDemo && isDemoMode;
                  
                  return (
                    <motion.button
                      key={item.path || item.action || item.label}
                      data-testid={`mobile-menu-item-${testKey}`}
                      initial={{ x: -20, opacity: 0 }}
                      animate={{ x: 0, opacity: isBlockedDemo ? 0.5 : 1 }}
                      transition={{ delay: 0.05 * index }}
                      onClick={() => handleNavigation(item)}
                      aria-disabled={isBlockedDemo || undefined}
                      className={`w-full flex items-center gap-4 p-4 rounded-xl transition-all ${
                        isBlockedDemo ? 'opacity-50' : ''
                      } ${
                        isActive 
                          ? 'bg-cyber-cyan/20 border border-cyber-cyan/30 text-cyber-cyan' 
                          : 'bg-white/5 border border-transparent text-white hover:bg-white/10 hover:border-white/10'
                      }`}
                    >
                      <div className={`w-10 h-10 rounded-lg flex items-center justify-center relative ${
                        isActive ? 'bg-cyber-cyan/20' : 'bg-white/5'
                      }`}>
                        <Icon className={`w-5 h-5 ${isActive ? 'text-cyber-cyan' : 'text-white/70'}`} />
                        {item.action === 'notifications' && notifState.count > 0 && (
                          <span className={`absolute -top-1 -right-1 min-w-[18px] h-[18px] px-1 rounded-full text-[10px] font-bold flex items-center justify-center text-white ${notifState.hasCritical ? 'bg-red-500' : 'bg-cyber-cyan text-black'}`}>
                            {notifState.count > 9 ? '9+' : notifState.count}
                          </span>
                        )}
                        {item.badgeCount > 0 && (
                          <span
                            data-testid={`mobile-menu-item-${testKey}-badge`}
                            className="absolute -top-1 -right-1 min-w-[18px] h-[18px] px-1 rounded-full text-[10px] font-bold flex items-center justify-center bg-cyber-cyan text-black"
                          >
                            {formatBadgeCount(item.badgeCount)}
                          </span>
                        )}
                      </div>
                      <span className={`text-base font-semibold uppercase tracking-wide ${item.gold ? 'gold-blink' : ''}`}>
                        {item.label}
                      </span>
                      {isActive && (
                        <div className="ml-auto w-2 h-2 rounded-full bg-cyber-cyan shadow-lg shadow-cyber-cyan/50" />
                      )}
                    </motion.button>
                  );
                })}
              </nav>

              {/* Support Button */}
              <div className="mt-4 pt-4 border-t border-white/10">
                <button
                  type="button"
                  onClick={() => { setIsMenuOpen(false); setShowSupportModal(true); }}
                  data-testid="mobile-nav-support-btn"
                  className="flex items-center justify-center gap-2 w-full py-3 rounded-xl bg-gradient-to-r from-blue-600/20 to-cyan-600/20 border border-blue-500/30 text-blue-400 hover:bg-blue-600/30 transition-all"
                >
                  <Headphones className="w-5 h-5" />
                  <span className="text-sm font-medium">{t('support') || 'Support'}</span>
                </button>
              </div>

              {/* Footer */}
              <div className="mt-6 pt-4 border-t border-white/10 text-center">
                <p className="text-[10px] text-text-muted uppercase tracking-widest">
                  GRAM City Builder © 2026
                </p>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Deposit Modal */}
      <DepositModal
        isOpen={showDeposit}
        onClose={() => setShowDeposit(false)}
        onSuccess={async () => { 
          setShowDeposit(false); 
          // Обновляем данные пользователя из БД после успешного депозита/промокода
          if (refreshBalance) await refreshBalance();
        }}
        receiverAddress={depositAddress}
        updateBalance={(newBal) => { 
          // Мгновенное локальное обновление + синхронизация с БД
          if (refreshBalance) refreshBalance(); 
        }}
      />

      {/* Withdraw Modal */}
      <WithdrawModal
        isOpen={showWithdraw}
        onClose={() => setShowWithdraw(false)}
        onSuccess={async () => { 
          setShowWithdraw(false); 
          if (refreshBalance) await refreshBalance();
        }}
        currentBalance={user?.balance_ton || 0}
        userWallet={user?.wallet_address}
        updateBalance={(newBal) => { 
          if (refreshBalance) refreshBalance(); 
        }}
      />

      {/* Support Modal */}
      <SupportModal
        open={showSupportModal}
        onOpenChange={setShowSupportModal}
        language={lang}
        currentUser={user}
      />

      <NotificationCenter
        open={showNotifications}
        onClose={() => setShowNotifications(false)}
        user={user}
      />
    </>
  );
}
