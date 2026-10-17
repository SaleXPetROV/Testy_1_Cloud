import React, { useState, useEffect, useRef } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { AlertCircle, Wallet, Loader2, ArrowDownToLine } from 'lucide-react';
import { toast } from 'sonner';
import { useTonConnectUI, useTonWallet } from '@/lib/tonconnect-lazy';
import { useLanguage } from '@/context/LanguageContext';
import { useTranslation } from '@/lib/translations';
import { tonToCity, formatCity, formatTon } from '@/lib/currency';
import { normalizeAddressForTonConnect, isSameTonAddress } from '@/lib/tonAddress';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api`;

/**
 * Modal shown ONLY when the user tries to buy a plot but has an insufficient
 * balance. Flow:
 *   1. If no wallet is linked to the account → show "Link Wallet" (TonConnect).
 *      Linking is persisted to the account via /api/auth/link-wallet.
 *   2. Once linked → show the recommended top-up amount + Cancel / Confirm.
 *      Confirm sends a TON transaction (the shortfall) to the deposit address,
 *      polls the balance until credited, then buys the plot (balance deducted).
 *      A rejected payment aborts the purchase.
 */
export default function LandPurchaseTopUpModal({ isOpen, onClose, cell, userBalanceTon, token, onConfirmPurchase }) {
  const [tonConnectUI] = useTonConnectUI();
  const wallet = useTonWallet();
  const { language } = useLanguage();
  const { t } = useTranslation(language);

  const [linkedWallet, setLinkedWallet] = useState(null); // wallet_address stored on the account (DB)
  const [loadingUser, setLoadingUser] = useState(false);
  const [linking, setLinking] = useState(false);
  const [processing, setProcessing] = useState(false);

  // Freeze the plot price and the user's balance at the moment the modal opens.
  // The parent resets `selectedCell` (→ price 0) after linking a wallet and after
  // a purchase, which used to zero the displayed shortfall. Snapshotting on open
  // keeps the amounts stable for the whole top-up flow.
  const [snap, setSnap] = useState({ priceTon: 0, balanceTon: 0, cell: null });
  const prevOpen = useRef(false);
  useEffect(() => {
    if (isOpen && !prevOpen.current && cell) {
      const p = cell.priceTon || cell.price_ton || cell.price || 0;
      setSnap({ priceTon: p, balanceTon: userBalanceTon || 0, cell });
    }
    prevOpen.current = isOpen;
  }, [isOpen, cell, userBalanceTon]);

  const priceTon = snap.priceTon;
  const shortfallTonRaw = Math.max(0, snap.priceTon - snap.balanceTon);
  // Round the shortfall up to 2 decimals so the credited amount definitely
  // covers the plot price after conversion dust.
  const neededTon = Math.ceil(shortfallTonRaw * 100) / 100;
  const neededCity = tonToCity(neededTon);

  const isLinked = !!linkedWallet;

  // Load the account's linked wallet whenever the modal opens.
  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    (async () => {
      setLoadingUser(true);
      try {
        const res = await fetch(`${API}/auth/me`, { headers: { Authorization: `Bearer ${token}` } });
        if (res.ok) {
          const data = await res.json();
          if (!cancelled) setLinkedWallet(data.wallet_address || null);
        }
      } catch (_) { /* noop */ }
      finally { if (!cancelled) setLoadingUser(false); }
    })();
    return () => { cancelled = true; };
  }, [isOpen, token]);

  // When a wallet connects via TonConnect AND the account has none linked yet,
  // persist the link to the account. Guard with a ref to avoid double-fire.
  const linkInFlight = useRef(false);
  useEffect(() => {
    if (!isOpen || !wallet || linkedWallet || linkInFlight.current) return;
    linkInFlight.current = true;
    (async () => {
      try {
        const addr = wallet.account?.address;
        const res = await fetch(`${API}/auth/link-wallet`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
          body: JSON.stringify({ wallet_address: addr }),
        });
        const data = await res.json();
        if (!res.ok) {
          try { await tonConnectUI.disconnect(); } catch (_) { /* noop */ }
          throw new Error(
            data.detail === 'wallet_already_linked'
              ? (t('walletBusy') || 'This wallet is already linked to another account')
              : data.detail
          );
        }
        setLinkedWallet(addr);
        toast.success(t('toastWalletLinked'));
      } catch (e) {
        toast.error(e.message);
      } finally {
        setLinking(false);
        setTimeout(() => { linkInFlight.current = false; }, 1500);
      }
    })();
  }, [wallet, linkedWallet, isOpen, token, tonConnectUI, t]);

  // Detect the TonConnect modal being closed without a connection → cancel toast.
  useEffect(() => {
    if (!tonConnectUI) return;
    const unsub = tonConnectUI.onModalStateChange((state) => {
      if (state?.status === 'closed' && !tonConnectUI.connected && linking) {
        setLinking(false);
        toast.info(t('toastWalletLinkCancelled'));
      }
    });
    return () => { try { unsub && unsub(); } catch (_) { /* noop */ } };
  }, [tonConnectUI, linking, t]);

  const handleLink = async () => {
    if (wallet) return; // already connected — the effect will link it
    setLinking(true);
    try {
      await tonConnectUI.openModal();
    } catch (e) {
      setLinking(false);
      toast.error(t('walletConnectionError') || 'Wallet connection error');
    }
  };

  const handleConfirm = async () => {
    // A live TonConnect session is required to send the payment.
    if (!wallet) {
      try { await tonConnectUI.openModal(); } catch (_) { /* noop */ }
      return;
    }
    // The connected wallet must match the one linked to the account.
    if (linkedWallet && wallet.account?.address && !isSameTonAddress(wallet.account.address, linkedWallet)) {
      toast.error(t('toastWalletMismatch'));
      return;
    }

    setProcessing(true);
    try {
      let depositAddress = '';
      try {
        const cfg = await fetch(`${API}/config`).then((r) => r.json());
        depositAddress = cfg?.deposit_address || '';
      } catch (_) { /* noop */ }

      if (!depositAddress) {
        toast.error(t('recipientNotConfigured') || 'Recipient wallet is not configured');
        setProcessing(false);
        return;
      }

      const targetAddress = normalizeAddressForTonConnect(depositAddress);
      const amountNano = Math.floor(neededTon * 1e9);
      const transaction = {
        validUntil: Math.floor(Date.now() / 1000) + 600,
        messages: [{ address: targetAddress, amount: amountNano.toString() }],
      };

      // Throws if the user rejects/cancels in their wallet.
      await tonConnectUI.sendTransaction(transaction);
      toast.success(t('toastPaymentSent'));

      // Poll the balance until the deposit is credited (payment_monitor).
      let attempts = 0;
      const maxAttempts = 24; // ~2 minutes at 5s interval
      let credited = false;
      while (attempts < maxAttempts) {
        attempts += 1;
        await new Promise((r) => setTimeout(r, 5000));
        try {
          const meRes = await fetch(`${API}/auth/me`, { headers: { Authorization: `Bearer ${token}` } });
          if (meRes.ok) {
            const me = await meRes.json();
            window.dispatchEvent(new CustomEvent('balanceUpdate', { detail: { balance: me.balance_ton } }));
            if ((me.balance_ton || 0) >= priceTon) { credited = true; break; }
          }
        } catch (_) { /* noop */ }
      }

      if (!credited) {
        toast.info(t('toastPaymentPending'));
        setProcessing(false);
        onClose();
        return;
      }

      // Funds credited → buy the plot (balance is deducted server-side).
      await onConfirmPurchase(snap.cell);
      setProcessing(false);
      onClose();
    } catch (error) {
      const msg = error?.message || String(error);
      if (/reject|cancel/i.test(msg)) {
        toast.error(t('toastPaymentCancelled'));
      } else {
        toast.error(`${t('depositError') || 'Deposit error'} ${msg.slice(0, 100)}`);
      }
      setProcessing(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={(o) => { if (!o && !processing) onClose(); }} modal={false}>
      <DialogContent
        className="bg-void border-white/10 text-white w-[calc(100%-1.5rem)] max-w-md max-h-[90vh] overflow-y-auto p-4 sm:p-6"
        data-testid="land-topup-modal"
        onInteractOutside={(e) => e.preventDefault()}
        onPointerDownOutside={(e) => e.preventDefault()}
        onFocusOutside={(e) => e.preventDefault()}
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-lg sm:text-xl">
            <AlertCircle className="w-5 h-5 text-amber-400 shrink-0" />
            {t('topUpTitle')}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4 mt-2">
          <div className="p-3 sm:p-4 bg-white/5 rounded-lg space-y-1.5 sm:space-y-2" data-testid="land-topup-summary">
            <div className="text-amber-300 font-semibold text-sm sm:text-base break-words" data-testid="land-topup-shortfall">
              {t('topUpShortfall').replace('{city}', formatCity(neededCity))}
            </div>
            <div className="text-xs sm:text-sm text-gray-300 break-words" data-testid="land-topup-recommend">
              {t('topUpRecommend')
                .replace('{ton}', formatTon(neededTon))
                .replace('{city}', formatCity(neededCity))}
            </div>
          </div>

          {!isLinked ? (
            <>
              <Alert className="bg-yellow-500/10 border-yellow-500/30">
                <Wallet className="h-4 w-4 text-yellow-400" />
                <AlertDescription className="text-xs sm:text-sm text-yellow-300">
                  {t('topUpLinkPrompt')}
                </AlertDescription>
              </Alert>
              <Button
                onClick={handleLink}
                disabled={linking || loadingUser}
                className="w-full bg-blue-600 hover:bg-blue-700 text-sm sm:text-base"
                data-testid="land-topup-link-wallet-btn"
              >
                {linking ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Wallet className="w-4 h-4 mr-2" />}
                {t('topUpLinkWalletBtn')}
              </Button>
            </>
          ) : (
            <div className="flex items-stretch gap-2 sm:gap-3">
              <Button
                variant="outline"
                onClick={onClose}
                disabled={processing}
                className="flex-1 text-sm sm:text-base whitespace-nowrap"
                data-testid="land-topup-cancel-btn"
              >
                {t('cancel')}
              </Button>
              <Button
                onClick={handleConfirm}
                disabled={processing}
                className="flex-1 bg-green-600 hover:bg-green-700 text-sm sm:text-base whitespace-nowrap"
                data-testid="land-topup-confirm-btn"
              >
                {processing ? <Loader2 className="w-4 h-4 mr-2 animate-spin shrink-0" /> : <ArrowDownToLine className="w-4 h-4 mr-2 shrink-0" />}
                {t('topUpConfirm')}
              </Button>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
