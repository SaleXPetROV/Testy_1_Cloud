import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import {
  Wallet, ArrowDownToLine, ArrowUpFromLine, Landmark, History, Store,
  Trophy, MessageCircle, Settings, Shield, Headphones, BookOpen, ChevronRight,
  AlertCircle, Link2, Map, Lightbulb,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { DepositModal, WithdrawModal } from '@/components/BalanceModals';
import SupportModal from '@/components/SupportModal';
import IdeaModal from '@/components/IdeaModal';
import SmartAvatar from '@/components/SmartAvatar';
import { useTranslation } from '@/lib/translations';
import { useLanguage } from '@/context/LanguageContext';
import { tonToCity, formatCity, formatTon } from '@/lib/currency';
import { getGameMode, showDemoBlockedToast } from '@/lib/gameMode';
import { ADMIN_PATH } from '@/lib/adminPath';
import { hapticSelection } from '@/lib/telegramHaptic';
import NotificationCenter, { useNotificationsCount, NotificationBellIcon } from '@/components/NotificationCenter';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api`;

const SECTIONS = {
  finance:   { ru: 'Финансы и экономика', en: 'Finance & Economy',   es: 'Finanzas',    zh: '财务与经济', fr: 'Finances',    de: 'Finanzen',    ja: '金融',       ko: '금융',      id: 'Keuangan' },
  gameplay:  { ru: 'Геймплей и сообщество', en: 'Gameplay & Community', es: 'Juego',     zh: '游戏与社区', fr: 'Jeu',         de: 'Gameplay',    ja: 'ゲームプレイ', ko: '게임플레이', id: 'Permainan' },
  account:   { ru: 'Аккаунт и настройки', en: 'Account & Settings',   es: 'Cuenta',      zh: '账户与设置', fr: 'Compte',      de: 'Konto',       ja: 'アカウント', ko: '계정',      id: 'Akun' },
  help:      { ru: 'Помощь',              en: 'Help',                 es: 'Ayuda',       zh: '帮助',       fr: 'Aide',        de: 'Hilfe',       ja: 'ヘルプ',     ko: '도움말',    id: 'Bantuan' },
};
const RULES_LABEL = { ru: 'FAQ / Правила игры', en: 'FAQ / Game rules', es: 'FAQ / Reglas', zh: 'FAQ / 游戏规则', fr: 'FAQ / Règles', de: 'FAQ / Regeln', ja: 'FAQ / ルール', ko: 'FAQ / 규칙', id: 'FAQ / Aturan' };
const ROADMAP_LABEL = { ru: 'Дорожная карта', en: 'Roadmap', es: 'Hoja de ruta', zh: '路线图', fr: 'Feuille de route', de: 'Roadmap', ja: 'ロードマップ', ko: '로드맵', id: 'Peta jalan' };
const IDEA_LABEL = { ru: 'Предложить идею', en: 'Suggest an idea', es: 'Sugerir una idea', zh: '提出想法', fr: 'Proposer une idée', de: 'Idee vorschlagen', ja: 'アイデアを提案', ko: '아이디어 제안', id: 'Sarankan ide' };
const MORE_TITLE = { ru: 'Ещё', en: 'More', es: 'Más', zh: '更多', fr: 'Plus', de: 'Mehr', ja: 'その他', ko: '더보기', id: 'Lainnya' };

const GridIcon = ({ icon: Icon, label, color, onClick, testid, disabled }) => (
  <button
    onClick={onClick}
    disabled={disabled}
    data-testid={testid}
    className={`flex flex-col items-center gap-2 group ${disabled ? 'opacity-40' : ''}`}
  >
    <div
      className="w-[62px] h-[62px] rounded-[20px] flex items-center justify-center shadow-lg transition-transform duration-200 group-active:scale-90"
      style={{ background: color }}
    >
      <Icon className="w-7 h-7 text-white" strokeWidth={2} />
    </div>
    <span className="text-[11px] text-text-muted font-medium text-center leading-tight">{label}</span>
  </button>
);

const SectionHeader = ({ children }) => (
  <p className="text-xs uppercase tracking-widest text-text-muted/70 font-semibold mb-4 mt-7 px-1">{children}</p>
);

export default function MorePage({ user, refreshBalance }) {
  const navigate = useNavigate();
  const { language: lang } = useLanguage();
  const { t } = useTranslation(lang);
  const S = (k) => SECTIONS[k][lang] || SECTIONS[k].ru;

  const [showDeposit, setShowDeposit] = useState(false);
  const [showWithdraw, setShowWithdraw] = useState(false);
  const [showSupport, setShowSupport] = useState(false);
  const [showIdea, setShowIdea] = useState(false);
  const [depositAddress, setDepositAddress] = useState('');
  const [walletWarn, setWalletWarn] = useState('');

  const isDemo = getGameMode() === 'demo';
  const displayCity = tonToCity((user?.balance_ton || 0) + Number(user?.bonus_balance || 0));
  const displayTon = (user?.balance_ton || 0) + Number(user?.bonus_balance || 0);

  const notifState = useNotificationsCount(user);
  const [showNotifications, setShowNotifications] = useState(false);
  const BAL_MAIN_LABEL = { ru: 'Основной', en: 'Main', es: 'Principal', zh: '主要', fr: 'Principal', de: 'Haupt', ja: 'メイン', ko: '기본', id: 'Utama' };
  const BAL_BONUS_LABEL = { ru: 'Бонусы', en: 'Bonus', es: 'Bono', zh: '奖励', fr: 'Bonus', de: 'Bonus', ja: 'ボーナス', ko: '보너스', id: 'Bonus' };
  const mainLabel = BAL_MAIN_LABEL[lang] || BAL_MAIN_LABEL.ru;
  const bonusLabel = BAL_BONUS_LABEL[lang] || BAL_BONUS_LABEL.ru;

  useEffect(() => {
    fetch(`${API}/config`).then((r) => r.json()).then((d) => {
      if (d.deposit_address) setDepositAddress(d.deposit_address);
    }).catch(() => {});
  }, []);

  if (!user) return null;

  const nav = (to, blockedInDemo = false) => {
    hapticSelection();
    if (blockedInDemo && isDemo) { showDemoBlockedToast(); return; }
    navigate(to);
  };

  const openDeposit = () => { if (user.wallet_address) setShowDeposit(true); else setWalletWarn('deposit'); };
  const openWithdraw = () => { if (user.wallet_address) setShowWithdraw(true); else setWalletWarn('withdraw'); };

  return (
    <div className="min-h-screen bg-void" data-testid="more-page">
      <div
        className="max-w-xl mx-auto px-4 pb-28 min-h-screen flex flex-col"
        style={{ paddingTop: 'calc(env(safe-area-inset-top, 0px) + 1.25rem)' }}
      >
        <h1 className="font-unbounded text-2xl font-bold text-text-main mb-5">{MORE_TITLE[lang] || MORE_TITLE.ru}</h1>

        {/* Profile + balance header */}
        <motion.div
          initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}
          className="relative p-4 rounded-2xl bg-gradient-to-br from-cyber-cyan/10 to-neon-purple/10 border border-cyber-cyan/20"
        >
          <div className="absolute top-3 right-3 z-10">
            <NotificationBellIcon
              count={notifState.count}
              hasCritical={notifState.hasCritical}
              shake={notifState.shake}
              onClick={() => setShowNotifications(true)}
              dataTestid="more-notif-bell"
            />
          </div>
          <div className="flex items-center gap-3 pr-12">
            <SmartAvatar
              avatar={user.avatar}
              name={user.display_name || user.username}
              className="w-12 h-12 rounded-full border-2 border-cyber-cyan flex-shrink-0 text-lg"
            />
            <div className="min-w-0">
              <p className="text-base font-bold text-white truncate">{user.display_name || user.username}</p>
              <p className="text-xs text-text-muted truncate">{user.email || ''}</p>
            </div>
          </div>

          <div className="mt-4 p-3 rounded-xl bg-black/30">
            <div className="flex items-center gap-2 mb-1">
              <Wallet className="w-4 h-4 text-cyber-cyan" />
              <span className="text-xs uppercase tracking-wide text-text-muted">{t('balance') || 'Баланс'}</span>
            </div>
            <div className="text-2xl font-bold text-white" data-testid="more-balance-city">
              {formatCity(displayCity)} <span className="text-yellow-400 text-sm">$CITY</span>
            </div>
            <div className="text-xs text-text-muted mt-0.5">≈ {formatTon(displayTon)} TON</div>
            {!isDemo && (
              <>
                <div className="text-xs text-text-muted mt-0.5" data-testid="more-balance-main">
                  {mainLabel}: {formatCity(tonToCity(user?.balance_ton || 0))} $CITY ({formatTon(user?.balance_ton || 0)} TON)
                </div>
                <div className="text-xs text-text-muted mt-0.5" data-testid="more-balance-bonus">
                  {bonusLabel}: {formatCity(tonToCity(Number(user?.bonus_balance || 0)))} $CITY ({formatTon(Number(user?.bonus_balance || 0))} TON)
                </div>
              </>
            )}
          </div>

          {!isDemo && (
            <div className="grid grid-cols-2 gap-2 mt-3">
              <Button className="bg-green-600 hover:bg-green-700 h-11" onClick={openDeposit} data-testid="more-deposit-btn">
                <ArrowDownToLine className="w-4 h-4 mr-2" />{t('deposit') || 'Пополнить'}
              </Button>
              <Button className="bg-orange-600 hover:bg-orange-700 h-11" onClick={openWithdraw} data-testid="more-withdraw-btn">
                <ArrowUpFromLine className="w-4 h-4 mr-2" />{t('withdraw') || 'Вывести'}
              </Button>
            </div>
          )}

          {walletWarn && (
            <div className="mt-2 p-3 rounded-xl bg-red-900/30 border border-red-700/50">
              <div className="flex items-start gap-2">
                <AlertCircle className="w-5 h-5 text-red-400 shrink-0 mt-0.5" />
                <div>
                  <p className="text-sm text-red-300">{t('walletRequiredFor') || 'Для этой операции нужно привязать TON-кошелёк'}</p>
                  <Button size="sm" className="mt-2 bg-blue-600 hover:bg-blue-700 h-8" onClick={() => { setWalletWarn(''); navigate('/settings'); }}>
                    <Link2 className="w-3 h-3 mr-1" />{t('linkWallet') || 'Привязать кошелёк'}
                  </Button>
                </div>
              </div>
            </div>
          )}
        </motion.div>

        {/* Finance */}
        <SectionHeader>{S('finance')}</SectionHeader>
        <div className="grid grid-cols-4 gap-4">
          <GridIcon icon={Landmark} label={t('menuCredits') || t('credits') || 'Кредиты'} color="linear-gradient(135deg,#8b5cf6,#6d28d9)" onClick={() => nav('/credit', true)} testid="more-credit" />
          <GridIcon icon={History} label={t('transactionHistory') || t('menuHistory') || 'История'} color="linear-gradient(135deg,#3b82f6,#1d4ed8)" onClick={() => nav('/history')} testid="more-history" />
          <GridIcon icon={Store} label={t('marketplace') || 'Маркетплейс'} color="linear-gradient(135deg,#f59e0b,#d97706)" onClick={() => nav('/marketplace', true)} testid="more-marketplace" />
        </div>

        {/* Gameplay */}
        <SectionHeader>{S('gameplay')}</SectionHeader>
        <div className="grid grid-cols-4 gap-4">
          <GridIcon icon={Trophy} label={t('leaderboard') || 'Рейтинг'} color="linear-gradient(135deg,#eab308,#ca8a04)" onClick={() => nav('/leaderboard', true)} testid="more-leaderboard" />
          <GridIcon icon={MessageCircle} label={t('chat') || 'Чат'} color="linear-gradient(135deg,#06b6d4,#0891b2)" onClick={() => nav('/chat')} testid="more-chat" />
        </div>

        {/* Account */}
        <SectionHeader>{S('account')}</SectionHeader>
        <div className="grid grid-cols-4 gap-4">
          <GridIcon icon={Settings} label={t('settings') || 'Настройки'} color="linear-gradient(135deg,#64748b,#475569)" onClick={() => nav('/settings')} testid="more-settings" />
          {user?.is_admin && (
            <GridIcon icon={Shield} label={t('adminPanel') || 'Админ-панель'} color="linear-gradient(135deg,#ef4444,#b91c1c)" onClick={() => nav(ADMIN_PATH)} testid="more-admin" />
          )}
        </div>

        {/* Help — text rows */}
        <SectionHeader>{S('help')}</SectionHeader>
        <div className="rounded-2xl border border-white/10 bg-white/[0.02] overflow-hidden">
          <button
            onClick={() => { hapticSelection(); setShowSupport(true); }}
            data-testid="more-support"
            className="w-full flex items-center gap-3 p-4 hover:bg-white/5 transition-colors border-b border-white/10"
          >
            <div className="w-9 h-9 rounded-full bg-white/10 flex items-center justify-center flex-shrink-0">
              <Headphones className="w-5 h-5 text-cyan-300" />
            </div>
            <span className="flex-1 text-left text-sm font-semibold text-text-main">{t('support') || 'Написать в поддержку'}</span>
            <ChevronRight className="w-4 h-4 text-text-muted" />
          </button>
          <button
            onClick={() => nav('/rules')}
            data-testid="more-rules"
            className="w-full flex items-center gap-3 p-4 hover:bg-white/5 transition-colors border-b border-white/10"
          >
            <div className="w-9 h-9 rounded-full bg-white/10 flex items-center justify-center flex-shrink-0">
              <BookOpen className="w-5 h-5 text-cyan-300" />
            </div>
            <span className="flex-1 text-left text-sm font-semibold text-text-main">{RULES_LABEL[lang] || RULES_LABEL.ru}</span>
            <ChevronRight className="w-4 h-4 text-text-muted" />
          </button>
          <button
            onClick={() => nav('/roadmap')}
            data-testid="more-roadmap"
            className="w-full flex items-center gap-3 p-4 hover:bg-white/5 transition-colors border-b border-white/10"
          >
            <div className="w-9 h-9 rounded-full bg-white/10 flex items-center justify-center flex-shrink-0">
              <Map className="w-5 h-5 text-cyan-300" />
            </div>
            <span className="flex-1 text-left text-sm font-semibold text-text-main">{ROADMAP_LABEL[lang] || ROADMAP_LABEL.ru}</span>
            <ChevronRight className="w-4 h-4 text-text-muted" />
          </button>
          <button
            onClick={() => { hapticSelection(); setShowIdea(true); }}
            data-testid="more-idea"
            className="w-full flex items-center gap-3 p-4 hover:bg-white/5 transition-colors"
          >
            <div className="w-9 h-9 rounded-full bg-yellow-400/15 flex items-center justify-center flex-shrink-0">
              <Lightbulb className="w-5 h-5 text-yellow-400" />
            </div>
            <span className="flex-1 text-left text-sm font-semibold text-text-main">{IDEA_LABEL[lang] || IDEA_LABEL.ru}</span>
            <ChevronRight className="w-4 h-4 text-text-muted" />
          </button>
        </div>

        <p className="text-[10px] text-text-muted/60 uppercase tracking-widest text-center mt-auto pt-6">GRAM City Builder © 2026</p>
      </div>

      <DepositModal
        isOpen={showDeposit}
        onClose={() => setShowDeposit(false)}
        onSuccess={async () => { setShowDeposit(false); if (refreshBalance) await refreshBalance(); }}
        receiverAddress={depositAddress}
        updateBalance={() => { if (refreshBalance) refreshBalance(); }}
      />
      <WithdrawModal
        isOpen={showWithdraw}
        onClose={() => setShowWithdraw(false)}
        onSuccess={async () => { setShowWithdraw(false); if (refreshBalance) await refreshBalance(); }}
        currentBalance={user?.balance_ton || 0}
        userWallet={user?.wallet_address}
        updateBalance={() => { if (refreshBalance) refreshBalance(); }}
      />
      <SupportModal open={showSupport} onOpenChange={setShowSupport} language={lang} currentUser={user} />
      <IdeaModal open={showIdea} onOpenChange={setShowIdea} language={lang} />
      <NotificationCenter open={showNotifications} onClose={() => setShowNotifications(false)} user={user} />
    </div>
  );
}
