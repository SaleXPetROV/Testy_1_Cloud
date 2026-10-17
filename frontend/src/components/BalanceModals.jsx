import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { ArrowDownToLine, ArrowUpFromLine, AlertCircle, Info, Clock, Zap, Building2, Lock, Wallet, MessageCircle, Copy, Check } from 'lucide-react';
import { toast } from 'sonner';
import { useTonConnectUI, useTonWallet } from '@/lib/tonconnect-lazy';
import axios from 'axios';
import { toUserFriendlyAddress, normalizeAddressForTonConnect, isSameTonAddress } from '@/lib/tonAddress';
import { useLanguage } from '@/context/LanguageContext';
import { useTranslation } from '@/lib/translations';
import { tonToCity, cityToTon, formatCity, formatTon, CITY_RATE } from '@/lib/currency';
import { MAX_PRICE_VALUE, clampPriceValue } from '@/lib/priceLimits';
import SupportModal from './SupportModal';
import {
  isTelegramMiniApp,
  isBiometryPlatformSupported,
  getBiometryState,
  biometryConfirmWithdrawal,
} from '@/lib/telegramBiometry';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const WITHDRAWAL_FEE_PERCENT = 3;
const INSTANT_FEE_PERCENT = 1; // Bank fee

export function DepositModal({ isOpen, onClose, onSuccess, receiverAddress, updateBalance }) {
  const navigate = useNavigate();
  const [tonConnectUI] = useTonConnectUI();
  const wallet = useTonWallet();
  const { language } = useLanguage();
  const { t } = useTranslation(language);
  const [amount, setAmount] = useState('');
  const [isProcessing, setIsProcessing] = useState(false);
  const [activeDepositTab, setActiveDepositTab] = useState('ton');
  const [promoCode, setPromoCode] = useState('');
  const [isActivatingPromo, setIsActivatingPromo] = useState(false);
  const [userLinkedWallet, setUserLinkedWallet] = useState(null);
  const [walletMismatch, setWalletMismatch] = useState(false);
  const [copiedField, setCopiedField] = useState(null);

  // Скопировать текст в буфер обмена и показать визуальную галочку на 2 сек.
  // Нужен для ручного режима пополнения: пользователь копирует адрес/сумму
  // и отправляет TON из своего кошелька на другом устройстве вручную.
  const handleCopy = async (text, field) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedField(field);
      setTimeout(() => setCopiedField(null), 2000);
    } catch (_) {
      toast.error(t('copyFailed') || 'Не удалось скопировать');
    }
  };
  
  // Load user's linked wallet address
  useEffect(() => {
    if (isOpen) {
      const loadUserWallet = async () => {
        try {
          const token = localStorage.getItem('token');
          const res = await fetch(`${API}/auth/me`, {
            headers: { Authorization: `Bearer ${token}` }
          });
          if (res.ok) {
            const data = await res.json();
            setUserLinkedWallet(data.wallet_address);
          }
        } catch (e) { console.error('Failed to load user wallet:', e); }
      };
      loadUserWallet();
    }
  }, [isOpen]);
  
  // Check wallet match when wallet changes
  useEffect(() => {
    // Если у пользователя нет привязанного кошелька в БД - не проверяем совпадение
    if (!userLinkedWallet) {
      setWalletMismatch(false);
      return;
    }
    
    if (wallet && userLinkedWallet) {
      const connectedAddress = wallet.account?.address;
      if (connectedAddress) {
        // Canonical 32-byte hash compare: TonConnect returns raw "0:<64hex>"
        // while the DB stores user-friendly "UQ.../EQ..." base64. A naive
        // suffix compare always fails between the two formats. isSameTonAddress
        // parses both representations down to their hash and compares those.
        const same = isSameTonAddress(connectedAddress, userLinkedWallet);
        setWalletMismatch(!same);
      } else {
        setWalletMismatch(false);
      }
    } else {
      setWalletMismatch(false);
    }
  }, [wallet, userLinkedWallet]);

  // Mismatch toast on TonConnect handshake when connected wallet ≠ linked one.
  // Success toast intentionally removed — пользователь и так видит сменившийся
  // UI (кнопка "Подтвердить пополнение"), а раньше тост показывался 2 раза
  // подряд из-за двух апдейтов состояния TonConnect.
  const prevWalletRef = React.useRef(wallet);
  useEffect(() => {
    const before = prevWalletRef.current;
    if (!before && wallet) {
      const addr = wallet.account?.address;
      if (userLinkedWallet && addr && !isSameTonAddress(addr, userLinkedWallet)) {
        toast.error(
          t('walletMismatchToast') ||
          'Этот кошелёк не привязан к вашему аккаунту. Смените его в Настройках безопасности.'
        );
      }
    }
    prevWalletRef.current = wallet;
  }, [wallet, userLinkedWallet, t]);

  const handleConnectWallet = async () => {
    try {
      // Проверяем, не подключен ли уже кошелёк
      if (wallet) {
        // Кошелёк уже подключен, просто продолжаем
        return;
      }
      await tonConnectUI.openModal();
    } catch (error) {
      console.error('Connect error:', error);
      // Игнорируем ошибку если кошелёк уже подключен
      if (!error.message?.includes('already connected')) {
        toast.error(t('walletConnectionError'));
      }
    }
  };
  
  const handleChangeWallet = async () => {
    try {
      // Сначала отключаем текущий кошелёк
      if (wallet) {
        await tonConnectUI.disconnect();
        // Ждём пока состояние обновится
        await new Promise(resolve => setTimeout(resolve, 500));
      }
      // Затем открываем модалку для подключения нового
      await tonConnectUI.openModal();
    } catch (error) {
      console.error('Change wallet error:', error);
      // Игнорируем ошибку если кошелёк уже подключен
      if (!error.message?.includes('already connected')) {
        toast.error(t('changeWalletError'));
      }
    }
  };

  const handleDeposit = async () => {
    // Проверяем подключение кошелька
    if (!wallet) {
      toast.error(t('connectTonWalletFirst'));
      handleConnectWallet();
      return;
    }
    
    // Проверяем соответствие адреса кошелька
    if (walletMismatch) {
      toast.error(t('walletMismatchError'));
      return;
    }

    if (!amount || parseFloat(amount) <= 0) {
      toast.error(t('enterCorrectAmount'));
      return;
    }

    if (!receiverAddress || receiverAddress === 'EQDefault...' || receiverAddress === '') {
      toast.error(t('recipientNotConfigured'));
      return;
    }

    // Normalize address for TON Connect (convert URL-safe base64 to standard base64)
    const targetAddress = normalizeAddressForTonConnect(receiverAddress);

    setIsProcessing(true);
    try {
      // Amount in nanotons (without additional fee)
      const amountNano = Math.floor(parseFloat(amount) * 1e9);

      const transaction = {
        validUntil: Math.floor(Date.now() / 1000) + 600,
        messages: [
          {
            address: targetAddress,
            amount: amountNano.toString(),
          },
        ],
      };

      await tonConnectUI.sendTransaction(transaction);
      toast.success(t('transactionSent'));

      // Начинаем polling для мгновенного обновления баланса
      const token = localStorage.getItem('token');
      let attempts = 0;
      const maxAttempts = 12; // 60 секунд (каждые 5 сек)
      
      const pollBalance = setInterval(async () => {
        attempts++;
        try {
          const res = await fetch(`${API}/auth/me`, {
            headers: { Authorization: `Bearer ${token}` }
          });
          if (res.ok) {
            const data = await res.json();
            if (updateBalance) {
              updateBalance(data.balance_ton);
            }
            window.dispatchEvent(new CustomEvent('balanceUpdate', { detail: { balance: data.balance_ton } }));
          }
        } catch (e) { /* silent */ }
        
        if (attempts >= maxAttempts) {
          clearInterval(pollBalance);
        }
      }, 5000); // Каждые 5 секунд
      
      // Останавливаем polling через 60 секунд
      setTimeout(() => clearInterval(pollBalance), 60000);

      if (onSuccess) onSuccess();
      onClose();
      setAmount('');
    } catch (error) {
      console.error('Deposit failed:', error);
      const errorMessage = error?.message || String(error);
      if (errorMessage.includes('reject') || errorMessage.includes('cancel')) {
        toast.error(t('transactionCancelled'));
      } else if (errorMessage.includes('not enough')) {
        toast.error(t('insufficientWalletFunds'));
      } else {
        toast.error(`${t('depositError')} ${errorMessage.slice(0, 100)}`);
      }
    } finally {
      setIsProcessing(false);
    }
  };

  const handleActivatePromo = async () => {
    if (!promoCode.trim()) {
      toast.error(t('enterPromoCodeError'));
      return;
    }
    setIsActivatingPromo(true);
    try {
      const token = localStorage.getItem('token');
      const res = await fetch(`${API}/promo/activate?code=${encodeURIComponent(promoCode.trim())}`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` }
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Error');
      toast.success(`${t('promoActivated')} +${data.amount} TON`);
      setPromoCode('');
      
      // Мгновенно обновляем баланс локально
      if (data.new_balance !== undefined) {
        if (updateBalance) updateBalance(data.new_balance);
        window.dispatchEvent(new CustomEvent('balanceUpdate', { detail: { balance: data.new_balance } }));
      }
      // Вызываем onSuccess для полного обновления данных пользователя из БД
      if (onSuccess) onSuccess();
    } catch (e) { toast.error(e.message); }
    finally { setIsActivatingPromo(false); }
  };

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="bg-void border-white/10 text-white max-w-md" data-testid="deposit-modal">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-xl">
            <ArrowDownToLine className="w-5 h-5 text-green-500" />
            {t('depositBalance')}
          </DialogTitle>
        </DialogHeader>

        <Tabs value={activeDepositTab} onValueChange={setActiveDepositTab} className="mt-4">
          <TabsList className="w-full bg-white/5 border border-white/10">
            <TabsTrigger value="ton" className="flex-1 data-[state=active]:bg-green-500/20 data-[state=active]:text-green-400">
              {t('tonTransfer')}
            </TabsTrigger>
            <TabsTrigger value="promo" className="flex-1 data-[state=active]:bg-amber-500/20 data-[state=active]:text-amber-400" data-testid="promo-tab">
              {t('promoCode')}
            </TabsTrigger>
          </TabsList>

          <TabsContent value="ton" className="space-y-4 mt-4">
          <Alert className="bg-blue-500/10 border-blue-500/30">
            <Info className="h-4 w-4 text-blue-400" />
            <AlertDescription className="text-sm text-blue-300">
              {t('fundsArriveInfo')}
            </AlertDescription>
          </Alert>

          <div>
            <Label>{t('depositAmount')}</Label>
            <Input
              type="number"
              step="0.01"
              min="0.1"
              max={MAX_PRICE_VALUE}
              value={amount}
              onChange={(e) => setAmount(clampPriceValue(e.target.value))}
              placeholder="10"
              className="mt-2 text-lg [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
              data-testid="deposit-amount-input"
            />
          </div>

          {amount && parseFloat(amount) > 0 && (
            <div
              className="p-4 bg-white/5 rounded-lg text-sm"
              data-testid="deposit-summary"
            >
              {/* v2.2.x: simplified per UX — show only the final $CITY total,
                  no per-rate formula or multiplier. */}
              <div className="flex items-center justify-between gap-2 text-base">
                <span className="font-semibold text-white">
                  {parseFloat(amount).toFixed(2)} TON
                </span>
                <span className="text-gray-400">→</span>
                <span
                  className="font-bold text-yellow-400"
                  data-testid="deposit-total-city"
                >
                  {formatCity(tonToCity(parseFloat(amount)))} $CITY
                </span>
              </div>
            </div>
          )}

          {/* Когда у юзера НЕТ активной TonConnect-сессии в этом браузере —
              просто показываем стандартную "no wallet" подсказку и кнопку
              "Привязать кошелёк". Никаких manual-deposit-panel, ручных
              переводов и "пополните такой-то адрес" — это путало пользователей.
              Состояние БД с TonConnect-сессией синхронизируется через
              useUnlinkOnTonConnectDisconnect (см. App.js). */}

          {!wallet && (
            <Alert className="bg-yellow-500/10 border-yellow-500/30">
              <AlertCircle className="h-4 w-4 text-yellow-400" />
              <AlertDescription className="text-sm text-yellow-300">
                {userLinkedWallet ? t('walletLinkedConnectToDeposit') : t('connectTonWallet')}
              </AlertDescription>
            </Alert>
          )}
          
          {/* Показываем ошибку если подключён другой кошелёк */}
          {walletMismatch && (
            <Alert className="bg-red-500/10 border-red-500/30">
              <AlertCircle className="h-4 w-4 text-red-400" />
              <AlertDescription className="text-sm text-red-300">
                {t('reconnectWallet')}{' '}
                <a href="/security" className="underline font-bold text-red-200 hover:text-white">{t('securitySettings')}</a>
                {' '}{t('toChangeWallet')}
              </AlertDescription>
            </Alert>
          )}

          <div className="flex gap-3">
            <Button
              variant="outline"
              onClick={onClose}
              className="flex-1"
              disabled={isProcessing}
            >
              {t('cancel')}
            </Button>
            {!wallet ? (
              <Button
                onClick={() => {
                  if (userLinkedWallet) {
                    // Wallet is already linked in the DB (e.g. linked on phone) —
                    // the user only needs to CONNECT it in this browser session
                    // to send TON, not link a new one. Open TonConnect directly.
                    handleConnectWallet();
                  } else {
                    onClose();
                    navigate('/settings?tab=wallet');
                  }
                }}
                className="flex-1 bg-blue-600 hover:bg-blue-700"
                data-testid="link-wallet-btn"
              >
                <Wallet className="w-4 h-4 mr-2" />
                {userLinkedWallet ? t('connectWalletBtn') : t('linkWalletBtn')}
              </Button>
            ) : walletMismatch ? (
              <Button
                onClick={() => { onClose(); window.location.href = '/security'; }}
                className="flex-1 bg-orange-600 hover:bg-orange-700"
              >
                {t('goToSettings')}
              </Button>
            ) : (
              <Button
                onClick={handleDeposit}
                disabled={!amount || parseFloat(amount) <= 0 || isProcessing}
                className="flex-1 bg-green-600 hover:bg-green-700"
                data-testid="confirm-deposit-btn"
              >
                {isProcessing ? (
                  <>
                  <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></div>
                  {t('processing')}
                </>
              ) : (
                <>
                  <ArrowDownToLine className="w-4 h-4 mr-2" />
                  {t('deposit')}
                </>
              )}
            </Button>
            )}
          </div>
          </TabsContent>

          <TabsContent value="promo" className="space-y-4 mt-4">
            <Alert className="bg-amber-500/10 border-amber-500/30">
              <Info className="h-4 w-4 text-amber-400" />
              <AlertDescription className="text-sm text-amber-300">
                {t('enterPromoCode')}
              </AlertDescription>
            </Alert>

            <div>
              <Label>{t('promoCode')}</Label>
              <Input
                data-testid="promo-code-activate-input"
                type="text"
                value={promoCode}
                onChange={(e) => setPromoCode(e.target.value.toUpperCase())}
                placeholder={t('promoCodePlaceholder')}
                className="mt-2 text-lg uppercase tracking-wider placeholder:text-sm placeholder:text-white/30 placeholder:tracking-normal"
                onKeyDown={(e) => e.key === 'Enter' && handleActivatePromo()}
              />
            </div>

            <Button
              data-testid="activate-promo-btn"
              onClick={handleActivatePromo}
              disabled={!promoCode.trim() || isActivatingPromo}
              className="w-full bg-amber-500 hover:bg-amber-600 text-black"
            >
              {isActivatingPromo ? t('activating') : t('activatePromoBtn')}
            </Button>
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}

export function WithdrawModal({ isOpen, onClose, onSuccess, currentBalance = 0, userWallet, updateBalance }) {
  const { language } = useLanguage();
  const { t } = useTranslation(language);
  const [amount, setAmount] = useState('');
  const [isProcessing, setIsProcessing] = useState(false);
  const [userDisplayAddress, setUserDisplayAddress] = useState('');
  const [withdrawType, setWithdrawType] = useState('standard'); // 'standard' or 'instant'
  const [banks, setBanks] = useState([]);
  const [selectedBank, setSelectedBank] = useState(null);
  const [totalDebt, setTotalDebt] = useState(0);
  const [frozenTon, setFrozenTon] = useState(0);
  const [availableForWithdraw, setAvailableForWithdraw] = useState(0);
  const [balanceFromAPI, setBalanceFromAPI] = useState(0);
  
  // 2FA verification states
  const [requires2FA, setRequires2FA] = useState(false);
  const [show2FADialog, setShow2FADialog] = useState(false);
  const [totpCode, setTotpCode] = useState('');
  const [useBackupCodeWithdraw, setUseBackupCodeWithdraw] = useState(false);
  const [is2FAChecking, setIs2FAChecking] = useState(false);
  const [pendingWithdrawal, setPendingWithdrawal] = useState(null);
  const [withdrawalBlocked, setWithdrawalBlocked] = useState(null); // { blocked: bool, unblock_at: datetime }
  const [showSupport, setShowSupport] = useState(false);
  const [supportTelegram, setSupportTelegram] = useState('');
  // Passkey-for-withdrawal: if the user has at least one Passkey registered,
  // the backend will require a fresh assertion BEFORE the TOTP step.
  const [hasPasskey, setHasPasskey] = useState(false);
  // Telegram Mini App biometry state — alternative to WebAuthn for mobile TG.
  const [tgBiometry, setTgBiometry] = useState({
    supported: false,   // running inside TG mobile with BiometricManager
    available: false,   // device has enrolled fingerprint / Face ID
    enabled: false,     // user has registered biometry with the server
    tokenSaved: false,  // secret persisted in the device enclave
    biometricType: 'unknown',
  });

  useEffect(() => {
    if (isOpen) {
      const loadData = async () => {
        try {
          const token = localStorage.getItem('token') || localStorage.getItem('ton_city_token');
          const [userRes, banksRes, securityRes, creditsRes] = await Promise.all([
            axios.get(`${API}/auth/me`, { headers: { Authorization: `Bearer ${token}` } }),
            axios.get(`${API}/banks`),
            axios.get(`${API}/security/status`, { headers: { Authorization: `Bearer ${token}` } }).catch(() => ({ data: {} })),
            axios.get(`${API}/credit/my-loans`, { headers: { Authorization: `Bearer ${token}` } }).catch(() => ({ data: { loans: [] } }))
          ]);
          setUserDisplayAddress(userRes.data.wallet_address_display || userRes.data.wallet_address);
          setBanks(banksRes.data.banks || []);
          setRequires2FA(securityRes.data?.is_2fa_enabled || false);
          setHasPasskey(!!(securityRes.data?.has_passkeys || securityRes.data?.passkeys_count));

          // Telegram Mini App biometry (mobile only)
          try {
            if (isTelegramMiniApp() && isBiometryPlatformSupported()) {
              const [devState, srvState] = await Promise.all([
                getBiometryState(),
                fetch(`${API}/security/telegram-biometry/status`, { headers: { Authorization: `Bearer ${token}` } })
                  .then(r => r.ok ? r.json() : ({ enabled: false }))
                  .catch(() => ({ enabled: false })),
              ]);
              setTgBiometry({
                supported: !!devState.supported,
                available: !!devState.available,
                enabled: !!srvState.enabled,
                tokenSaved: !!devState.tokenSaved,
                biometricType: devState.biometricType || 'unknown',
              });
            }
          } catch { /* noop */ }
          
          // Check if withdrawal is blocked
          if (securityRes.data?.withdrawal_blocked_until) {
            const blockedUntil = new Date(securityRes.data.withdrawal_blocked_until);
            if (blockedUntil > new Date()) {
              setWithdrawalBlocked({ blocked: true, unblock_at: blockedUntil });
            } else {
              setWithdrawalBlocked(null);
            }
          } else {
            setWithdrawalBlocked(null);
          }
          
          // Calculate total debt from active credits
          const activeCredits = (creditsRes.data.loans || []).filter(c => c.status === 'active' || c.status === 'overdue');
          const debt = activeCredits.reduce((sum, c) => sum + (c.remaining_amount || c.remaining || 0), 0);
          setTotalDebt(debt);

          // Tender contract escrow (frozen TON across all active/pending tender contracts)
          const frozenForTenders = parseFloat(userRes.data.frozen_for_tenders_ton || 0) || 0;
          setFrozenTon(frozenForTenders);

          // Use balance from API
          const userBalance = userRes.data.balance_ton || currentBalance || 0;
          setBalanceFromAPI(userBalance);
          setAvailableForWithdraw(Math.max(0, userBalance - debt - frozenForTenders));
        } catch (error) {
          console.error('Failed to load data:', error);
          setUserDisplayAddress(toUserFriendlyAddress(userWallet) || userWallet);
          setBalanceFromAPI(currentBalance || 0);
          setAvailableForWithdraw(currentBalance || 0);
        }
      };
      loadData();
      // Also load support telegram
      fetch(`${API}/config`)
        .then(r => r.json())
        .then(data => { if (data.support_telegram) setSupportTelegram(data.support_telegram); })
        .catch(() => {});
    }
  }, [isOpen, userWallet, currentBalance]);
  
  // Performs the passkey assertion challenge required by /api/withdraw when
  // the user has at least one Passkey registered. Returns a short-lived
  // `withdraw_pk_token` string that must be sent alongside the TOTP code.
  // Throws on cancellation / failure so the caller can abort the wizard.
  const obtainWithdrawPasskeyToken = async () => {
    if (!window.PublicKeyCredential || !navigator.credentials || typeof navigator.credentials.get !== 'function') {
      const isTelegram = /Telegram/i.test(navigator.userAgent) || !!window.Telegram?.WebApp;
      throw new Error(
        isTelegram
          ? 'Telegram WebView не поддерживает Passkey. Откройте сайт в обычном браузере (Safari/Chrome).'
          : 'Этот браузер не поддерживает Passkey.'
      );
    }
    const token = localStorage.getItem('token') || localStorage.getItem('ton_city_token');

    const startRes = await axios.post(
      `${API}/security/passkey/withdraw/start`,
      {},
      { headers: { Authorization: `Bearer ${token}` } },
    );
    const { challenge_id, options } = startRes.data;

    const b64urlToBuf = (s) => {
      const pad = '='.repeat((4 - s.length % 4) % 4);
      const b64 = (s + pad).replace(/-/g, '+').replace(/_/g, '/');
      const raw = window.atob(b64);
      const arr = new Uint8Array(raw.length);
      for (let i = 0; i < raw.length; ++i) arr[i] = raw.charCodeAt(i);
      return arr.buffer;
    };
    const bufToB64url = (buf) => {
      const bytes = new Uint8Array(buf);
      let bin = '';
      for (let i = 0; i < bytes.byteLength; i++) bin += String.fromCharCode(bytes[i]);
      return window.btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
    };

    const assertion = await navigator.credentials.get({
      publicKey: {
        ...options,
        challenge: b64urlToBuf(options.challenge),
        allowCredentials: (options.allowCredentials || []).map((c) => ({
          ...c,
          id: b64urlToBuf(c.id),
        })),
      },
    });

    const credentialJSON = {
      id: assertion.id,
      rawId: bufToB64url(assertion.rawId),
      type: assertion.type,
      response: {
        authenticatorData: bufToB64url(assertion.response.authenticatorData),
        clientDataJSON: bufToB64url(assertion.response.clientDataJSON),
        signature: bufToB64url(assertion.response.signature),
        userHandle: assertion.response.userHandle ? bufToB64url(assertion.response.userHandle) : null,
      },
    };

    const verifyRes = await axios.post(
      `${API}/security/passkey/withdraw/verify`,
      { challenge_id, credential: credentialJSON },
      { headers: { Authorization: `Bearer ${token}` } },
    );
    return verifyRes.data.withdraw_pk_token;
  };

  // Handle 2FA verification for withdrawal
  const verify2FAAndWithdraw = async () => {
    const codeLength = useBackupCodeWithdraw ? 8 : 6;
    if (!totpCode || totpCode.length < codeLength) {
      toast.error(useBackupCodeWithdraw ? t('enter8DigitCode') : t('enter6DigitCode'));
      return;
    }
    
    setIs2FAChecking(true);
    try {
      // Execute withdrawal with 2FA code directly
      await executeWithdrawal(pendingWithdrawal, totpCode);
      setShow2FADialog(false);
      setTotpCode('');
      setUseBackupCodeWithdraw(false);
      setPendingWithdrawal(null);
    } catch (error) {
      console.error('2FA verification failed:', error);
      let errorMsg = t('invalid2FACode');
      if (error.response?.data?.detail) {
        if (typeof error.response.data.detail === 'string') {
          errorMsg = error.response.data.detail;
        }
      }
      toast.error(errorMsg);
    } finally {
      setIs2FAChecking(false);
    }
  };
  
  const executeWithdrawal = async (withdrawalData, totpCodeValue = null) => {
    const token = localStorage.getItem('token') || localStorage.getItem('ton_city_token');

    // FingerprintJS OSS + Cloudflare Turnstile (невидимые, анти-фрод)
    let visitorId = '';
    let turnstileToken = '';
    try {
      const [fp, ts] = await Promise.all([
        import('@/lib/fingerprint').then(m => m.getVisitorId()).catch(() => ''),
        import('@/lib/turnstile').then(m => m.getTurnstileToken('withdraw')).catch(() => ''),
      ]);
      visitorId = fp || '';
      turnstileToken = ts || '';
    } catch { /* noop */ }

    const passkeyToken = withdrawalData.withdraw_pk_token || null;
    const biometryToken = withdrawalData.tg_biometry_token || null;
    // Telegram Desktop / Web: pass the raw initData so the backend can verify
    // the caller and waive the WebAuthn passkey requirement (per spec).
    let tgInitDataPc = null;
    try {
      if (isTelegramMiniApp() && !isBiometryPlatformSupported()) {
        tgInitDataPc = window?.Telegram?.WebApp?.initData || null;
      }
    } catch { /* noop */ }

    if (withdrawalData.type === 'instant') {
      const response = await axios.post(
        `${API}/withdraw/instant`,
        {
          amount: withdrawalData.amount,
          bank_id: withdrawalData.bankId,
          totp_code: totpCodeValue,
          withdraw_pk_token: passkeyToken,
          tg_biometry_token: biometryToken,
          tg_init_data: tgInitDataPc,
          visitor_id: visitorId,
          turnstile_token: turnstileToken,
        },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      
      // Update balance immediately via prop and global event
      if (response.data.new_balance !== undefined) {
        if (updateBalance) updateBalance(response.data.new_balance);
        window.dispatchEvent(new CustomEvent('balanceUpdate', { detail: { balance: response.data.new_balance } }));
      }
      
      toast.success(t('instantWithdrawProcessing'));
    } else {
      const response = await axios.post(
        `${API}/withdraw`,
        {
          amount: withdrawalData.amount,
          to_address: userWallet,
          totp_code: totpCodeValue,
          withdraw_pk_token: passkeyToken,
          tg_biometry_token: biometryToken,
          tg_init_data: tgInitDataPc,
          visitor_id: visitorId,
          turnstile_token: turnstileToken,
        },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      
      // Update balance immediately via prop and global event
      if (response.data.new_balance !== undefined) {
        if (updateBalance) updateBalance(response.data.new_balance);
        window.dispatchEvent(new CustomEvent('balanceUpdate', { detail: { balance: response.data.new_balance } }));
      }
      
      toast.success(t('withdrawRequestCreated'));
    }
    
    if (onSuccess) onSuccess();
    onClose();
    setAmount('');
    setSelectedBank(null);
  };

  const handleWithdraw = async () => {
    if (parseFloat(amount) < 1) {
      toast.error(t('minWithdrawError'));
      return;
    }

    if (withdrawType === 'instant' && !selectedBank) {
      toast.error(t('selectBankError'));
      return;
    }
    
    // Check if 2FA is enabled - required for withdrawal
    if (!requires2FA) {
      toast.error(t('twoFARequired'));
      return;
    }
    
    const withdrawalData = {
      type: withdrawType,
      amount: parseFloat(amount),
      bankId: selectedBank?.id,
      withdraw_pk_token: null,
      tg_biometry_token: null,
    };

    // Telegram Mini App biometry path — Face ID / fingerprint inside TG.
    // If the user has biometry set up AND a token is persisted on this
    // device, prompt for a scan; on success we skip both the passkey and
    // the TOTP steps below.
    if (tgBiometry.supported && tgBiometry.enabled && tgBiometry.tokenSaved) {
      try {
        const tgToken = await biometryConfirmWithdrawal();
        if (tgToken) {
          withdrawalData.tg_biometry_token = tgToken;
          // Skip WebAuthn + 2FA — send withdrawal directly.
          try {
            await executeWithdrawal(withdrawalData, '');
          } catch (error) {
            console.error('Biometry withdrawal failed:', error);
            const msg = error.response?.data?.detail || error.message || (language === 'ru' ? 'Ошибка вывода' : 'Withdrawal error');
            toast.error(typeof msg === 'string' ? msg : t('invalid2FACode'));
          }
          return;
        }
      } catch (e) {
        toast.error(e?.message || (language === 'ru' ? 'Ошибка биометрии' : 'Biometry error'));
        return;
      }
    }

    // If we're in the Telegram Mini App on mobile AND the user has biometry
    // AVAILABLE on the device but NOT yet registered with the server, guide
    // them to the setup page. WebAuthn is not usable inside TG WebView, so
    // this bridge is what unlocks withdrawal confirmation via fingerprint.
    if (
      tgBiometry.supported &&
      tgBiometry.available &&
      !tgBiometry.enabled &&
      hasPasskey  // user relied on WebAuthn on the web — bridge them
    ) {
      toast.info(
        language === 'ru'
          ? 'Отпечаток пальца для этого Telegram ещё не настроен. Откройте «Безопасность» → «Биометрия Telegram», подтвердите пароль или 2FA и повторите вывод.'
          : 'Fingerprint is not yet set up for this Telegram. Open Security → Telegram Biometry, confirm your password/2FA and retry.'
      );
      return;
    }

    // Telegram Desktop / Web (PC version): BiometricManager недоступен,
    // WebAuthn/Passkey в TG WebView не работает. По ТЗ — просим ТОЛЬКО 2FA,
    // независимо от того, зарегистрирован ли у пользователя passkey.
    const inTelegramDesktop = isTelegramMiniApp() && !isBiometryPlatformSupported();

    // If the user has any Passkey registered, the backend requires a fresh
    // passkey assertion BEFORE accepting the TOTP code. Prompt the platform
    // authenticator first; on success, attach the one-shot token to the
    // withdrawal data and continue to the 2FA step.
    if (hasPasskey && !inTelegramDesktop) {
      try {
        const wpkToken = await obtainWithdrawPasskeyToken();
        if (!wpkToken) {
          toast.error(language === 'ru' ? 'Не удалось получить токен Passkey' : 'Failed to obtain Passkey token');
          return;
        }
        withdrawalData.withdraw_pk_token = wpkToken;
      } catch (e) {
        if (e?.name === 'NotAllowedError') {
          toast.error(language === 'ru' ? 'Подтверждение Passkey отменено' : 'Passkey confirmation cancelled');
        } else {
          toast.error(e?.message || (language === 'ru' ? 'Ошибка Passkey' : 'Passkey error'));
        }
        return;
      }
    }

    // Show 2FA verification dialog
    setPendingWithdrawal(withdrawalData);
    setShow2FADialog(true);
  };
  
  const platformFee = amount ? (parseFloat(amount) * WITHDRAWAL_FEE_PERCENT) / 100 : 0;
  const bankFee = withdrawType === 'instant' && amount ? (parseFloat(amount) * INSTANT_FEE_PERCENT) / 100 : 0;
  const totalFees = platformFee + bankFee;
  const receivedAmount = amount ? parseFloat(amount) - totalFees : 0;

  const hasWallet = userWallet || userDisplayAddress;

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="bg-void border-white/10 text-white max-w-lg" data-testid="withdraw-modal">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-xl">
            <ArrowUpFromLine className="w-5 h-5 text-orange-500" />
            {t('withdrawFunds')}
          </DialogTitle>
          {!withdrawalBlocked?.blocked && (
            <DialogDescription className="text-text-muted">
              {t('selectWithdrawMethod')}
            </DialogDescription>
          )}
        </DialogHeader>

        {withdrawalBlocked?.blocked ? (
          /* Show ONLY withdrawal blocked message when blocked */
          <div className="p-6 bg-red-500/10 rounded-xl border border-red-500/30 text-center space-y-4 my-4">
            <Lock className="w-12 h-12 text-red-400 mx-auto" />
            <div>
              <h3 className="text-xl font-bold text-red-400 mb-2">{t('withdrawalBlocked')}</h3>
              <p className="text-red-300">
                {t('until')} {new Date(withdrawalBlocked.unblock_at).toLocaleString(language === 'ru' ? 'ru-RU' : 'en-US', {
                  day: '2-digit',
                  month: '2-digit', 
                  year: 'numeric',
                  hour: '2-digit',
                  minute: '2-digit',
                  second: '2-digit'
                })}
              </p>
              <p className="text-sm text-red-300/70 mt-2">
                {t('blockAfter2FA')}
              </p>
              <p className="text-sm text-amber-300/90 mt-3 px-2">
                {t('withdrawContactSupport')}
              </p>
            </div>
            <Button
              onClick={() => setShowSupport(true)}
              data-testid="withdraw-blocked-support-btn"
              className="w-full bg-gradient-to-r from-blue-600/40 to-cyan-600/40 hover:from-blue-600/60 hover:to-cyan-600/60 border border-blue-400/40 text-white"
            >
              <MessageCircle className="w-4 h-4 mr-2" />
              {t('supportContactTitle') || 'Связаться с поддержкой'}
            </Button>
            <Button
              variant="outline"
              onClick={onClose}
              className="w-full border-red-500/30 text-red-300 hover:bg-red-500/10"
            >
              {t('close')}
            </Button>
          </div>
        ) : (
          /* Show normal withdrawal form when NOT blocked */
          <div className="space-y-4 mt-2">
            {!hasWallet ? (
              <Alert className="bg-red-500/10 border-red-500/30">
                <AlertCircle className="h-4 w-4 text-red-400" />
                <AlertDescription className="text-sm text-red-300">
                  {t('connectWalletForWithdraw')}
                </AlertDescription>
              </Alert>
            ) : (
              <div className="p-3 bg-white/5 rounded-lg space-y-1.5">
                <div className="flex justify-between items-center">
                  <span className="text-text-muted">{t('availableLabel')}:</span>
                  <div className="text-right">
                    <div className="text-2xl font-bold text-yellow-400">{formatCity(tonToCity(availableForWithdraw))} $CITY</div>
                    <div className="text-xs text-text-muted">≈ {formatTon(availableForWithdraw)} TON</div>
                  </div>
                </div>
                <div className="flex justify-between items-center text-[11px] text-text-muted">
                  <span>{t('balance') || 'Баланс'}:</span>
                  <span className="text-zinc-300">{formatTon(balanceFromAPI)} TON</span>
                </div>
                {frozenTon > 0 && (
                  <div className="flex justify-between items-center text-[11px] text-amber-300">
                    <span>{t('frozenForContracts') || 'Заморожено в контрактах'}:</span>
                    <span>−{formatTon(frozenTon)} TON</span>
                  </div>
                )}
                {totalDebt > 0 && (
                  <div className="flex justify-between items-center text-[11px] text-red-300">
                    <span>{t('creditDebt') || 'Долг по кредиту'}:</span>
                    <span>−{formatTon(totalDebt)} TON</span>
                  </div>
                )}
              </div>
            )}

            {hasWallet && (
            <>
              {/* Withdrawal Type Tabs */}
              <Tabs value={withdrawType} onValueChange={setWithdrawType} className="w-full">
                <TabsList className="grid w-full grid-cols-2 bg-white/5">
                  <TabsTrigger value="standard" className="data-[state=active]:bg-white/10">
                    <Clock className="w-4 h-4 mr-2" />
                    {t('standardWithdraw')}
                  </TabsTrigger>
                  <TabsTrigger value="instant" className="data-[state=active]:bg-yellow-500/20">
                    <Zap className="w-4 h-4 mr-2" />
                    {t('instantWithdraw')}
                  </TabsTrigger>
                </TabsList>
                
                <TabsContent value="standard" className="mt-4">
                  {/* Standard withdrawal content */}
                </TabsContent>
                
                <TabsContent value="instant" className="mt-4 space-y-3">
                  {banks.length === 0 ? (
                    <div className="p-4 bg-white/5 rounded-lg text-center text-text-muted">
                      <Building2 className="w-8 h-8 mx-auto mb-2 opacity-50" />
                      <p>{t('noAvailableBanks')}</p>
                    </div>
                  ) : (
                    <div className="space-y-2">
                      <Label>{t('selectBank')}</Label>
                      {banks.map(bank => (
                        <div
                          key={bank.id}
                          onClick={() => setSelectedBank(bank)}
                          className={`p-3 rounded-lg border cursor-pointer transition-all ${
                            selectedBank?.id === bank.id
                              ? 'border-yellow-500 bg-yellow-500/10'
                              : 'border-white/10 hover:border-white/30 bg-white/5'
                          }`}
                        >
                          <div className="flex justify-between items-center">
                            <div>
                              <div className="text-white font-medium">🏦 Gram Bank</div>
                              <div className="text-xs text-text-muted">
                                {t('owner')}: {bank.owner_username || 'Unknown'} • {t('level')} {bank.level}
                              </div>
                            </div>
                            <Badge variant="outline" className="border-yellow-500/30 text-yellow-400">
                              -{bank.fee_rate * 100}%
                            </Badge>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </TabsContent>
              </Tabs>

              <div>
                <Label>{t('withdrawAmountLabel')}</Label>
                <Input
                  type="number"
                  step="0.01"
                  min="1"
                  max={Math.min(MAX_PRICE_VALUE, availableForWithdraw)}
                  value={amount}
                  onChange={(e) => setAmount(clampPriceValue(e.target.value))}
                  placeholder={t('minWithdraw')}
                  className="bg-white/5 border-white/10 text-white"
                />
                <div className="flex justify-between mt-2 text-xs">
                  <span className="text-text-muted">{t('balance')}: {formatCity(tonToCity(balanceFromAPI))} $CITY</span>
                  <span className="text-green-400 font-medium">{t('availableForWithdrawal')}: {formatTon(availableForWithdraw)} TON</span>
                </div>
                {amount && parseFloat(amount) > 0 && (
                  <div className="mt-2 text-xs text-yellow-400">
                    {t('willBeDeducted')} {formatCity(tonToCity(parseFloat(amount)))} $CITY
                  </div>
                )}
                {totalDebt > 0 && (
                  <div className="mt-2 p-2 bg-red-500/10 border border-red-500/20 rounded-lg">
                    <div className="flex items-center gap-2 text-red-400 text-xs">
                      <AlertCircle className="w-4 h-4" />
                      <span>{t('creditDebt')} {formatCity(tonToCity(totalDebt))} $CITY {t('unavailableForWithdrawal')}</span>
                    </div>
                  </div>
                )}
              </div>

              {amount && parseFloat(amount) > 0 && (
                <div className="p-4 bg-white/5 rounded-lg space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-gray-400">{t('sumLabel')}</span>
                    <span className="font-bold text-white">{parseFloat(amount).toFixed(2)} TON</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-400">{t('deductedLabel')}</span>
                    <span className="font-bold text-yellow-400">{formatCity(tonToCity(parseFloat(amount)))} $CITY</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-400">{t('platformFee')} ({WITHDRAWAL_FEE_PERCENT}%):</span>
                    <span className="text-red-400">-{platformFee.toFixed(2)} TON</span>
                  </div>
                  {withdrawType === 'instant' && (
                    <div className="flex justify-between">
                      <span className="text-gray-400">{t('bankFee')} ({INSTANT_FEE_PERCENT}%):</span>
                      <span className="text-yellow-400">-{bankFee.toFixed(2)} TON</span>
                    </div>
                  )}
                  <div className="h-px bg-white/10 my-2"></div>
                  <div className="flex justify-between text-base">
                    <span className="text-gray-300">{t('youWillReceive')}</span>
                    <span className="font-bold text-green-400">
                      {receivedAmount > 0 ? receivedAmount.toFixed(2) : '0.00'} TON
                    </span>
                  </div>
                  <div className="flex justify-between text-xs text-gray-500 mt-2">
                    <span>{t('toWallet')}</span>
                    <span className="font-mono text-right break-all max-w-[200px] truncate">
                      {userDisplayAddress || userWallet}
                    </span>
                  </div>
                </div>
              )}

              <div className="flex gap-3">
                <Button
                  variant="outline"
                  onClick={onClose}
                  className="flex-1"
                  disabled={isProcessing}
                >
                  {t('cancel')}
                </Button>
                <Button
                  onClick={handleWithdraw}
                  disabled={
                    !hasWallet ||
                    !amount ||
                    parseFloat(amount) <= 0 ||
                    parseFloat(amount) > availableForWithdraw ||
                    parseFloat(amount) < 1 ||
                    (withdrawType === 'instant' && !selectedBank) ||
                    isProcessing
                  }
                  className={`flex-1 ${withdrawType === 'instant' ? 'bg-yellow-600 hover:bg-yellow-700' : 'bg-orange-600 hover:bg-orange-700'}`}
                  data-testid="confirm-withdraw-btn"
                >
                  {isProcessing ? (
                    <>
                      <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></div>
                      {t('processing')}
                    </>
                  ) : (
                    <>
                      {withdrawType === 'instant' ? <Zap className="w-4 h-4 mr-2" /> : <ArrowUpFromLine className="w-4 h-4 mr-2" />}
                      {withdrawType === 'instant' ? t('instantWithdraw') : t('requestWithdraw')}
                    </>
                  )}
                </Button>
              </div>
              
              {/* 2FA Badge - only show when NOT blocked */}
              {requires2FA ? (
                <div className="flex items-center justify-center gap-2 p-2 bg-green-500/10 rounded-lg border border-green-500/20">
                  <Lock className="w-4 h-4 text-green-400" />
                  <span className="text-xs text-green-300">{t('twoFAEnabled')}</span>
                </div>
              ) : (
                <div className="flex items-center justify-center gap-2 p-2 bg-red-500/10 rounded-lg border border-red-500/20">
                  <AlertCircle className="w-4 h-4 text-red-400" />
                  <span className="text-xs text-red-300">{t('twoFARequired')}</span>
                </div>
              )}
            </>
            )}
          </div>
        )}
      </DialogContent>
      
      {/* 2FA Verification Dialog */}
      <Dialog open={show2FADialog} onOpenChange={(open) => {
        if (!open) {
          setShow2FADialog(false);
          setTotpCode('');
          setUseBackupCodeWithdraw(false);
          setPendingWithdrawal(null);
        }
      }}>
        <DialogContent className="bg-void border-white/10 text-white max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-xl">
              <Lock className="w-5 h-5 text-purple-400" />
              {t('twoFAConfirmation')}
            </DialogTitle>
            <DialogDescription className="text-text-muted">
              {useBackupCodeWithdraw 
                ? t('enter8DigitCode')
                : t('enter6DigitCode')
              }
            </DialogDescription>
          </DialogHeader>
          
          <div className="space-y-4">
            <div className="p-4 bg-purple-500/10 rounded-lg border border-purple-500/20">
              <div className="flex justify-between mb-1">
                <span className="text-text-muted">{t('withdrawAmount')}</span>
                <span className="text-white font-bold">{pendingWithdrawal?.amount?.toFixed(2)} TON</span>
              </div>
              <div className="flex justify-between">
                <span className="text-text-muted">{t('type')}</span>
                <span className="text-white">{pendingWithdrawal?.type === 'instant' ? t('instant') : t('standard')}</span>
              </div>
            </div>
            
            <div>
              <Label className="text-text-muted">{useBackupCodeWithdraw ? t('backupCode') : t('twoFACode')}</Label>
              <Input
                type="text"
                maxLength={useBackupCodeWithdraw ? 8 : 6}
                value={totpCode}
                onChange={(e) => {
                  if (useBackupCodeWithdraw) {
                    setTotpCode(e.target.value.slice(0, 8).toUpperCase());
                  } else {
                    setTotpCode(e.target.value.replace(/\D/g, ''));
                  }
                }}
                placeholder={useBackupCodeWithdraw ? "XXXXXXXX" : "000000"}
                autoFocus
                className={`mt-2 text-center text-2xl font-mono bg-white/5 border-white/10 ${useBackupCodeWithdraw ? 'tracking-[0.3em]' : 'tracking-[0.5em]'}`}
              />
            </div>
            
            {/* Toggle for backup code */}
            <button 
              onClick={() => {
                setUseBackupCodeWithdraw(!useBackupCodeWithdraw);
                setTotpCode('');
              }}
              className="text-purple-400 text-xs hover:text-purple-300 transition-colors underline w-full text-center"
            >
              {useBackupCodeWithdraw 
                ? t('useAppCode')
                : t('useBackupCode')
              }
            </button>
            
            <div className="flex gap-3">
              <Button
                variant="outline"
                onClick={() => {
                  setShow2FADialog(false);
                  setTotpCode('');
                  setUseBackupCodeWithdraw(false);
                  setPendingWithdrawal(null);
                }}
                className="flex-1"
              >
                {t('cancel')}
              </Button>
              <Button
                onClick={verify2FAAndWithdraw}
                disabled={totpCode.length !== (useBackupCodeWithdraw ? 8 : 6) || is2FAChecking}
                className="flex-1 bg-purple-600 hover:bg-purple-700"
              >
                {is2FAChecking ? t('checking') : t('confirmWithdraw')}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
      <SupportModal
        open={showSupport}
        onOpenChange={setShowSupport}
        supportTelegram={supportTelegram}
        language={language}
      />
    </Dialog>
  );
}
