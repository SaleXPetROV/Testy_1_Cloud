import React, { useState, useEffect } from 'react';
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog';
import { VisuallyHidden } from '@radix-ui/react-visually-hidden';
import { Wallet, ArrowDownToLine, ArrowUpFromLine } from 'lucide-react';
import { DepositModal, WithdrawModal } from './BalanceModals';
import { useLanguage } from '@/context/LanguageContext';
import { tonToCity, formatCity, formatTon } from '@/lib/currency';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api`;

const T = {
  balance: { ru: 'БАЛАНС', en: 'BALANCE', es: 'SALDO', zh: '余额', fr: 'SOLDE', de: 'GUTHABEN', ja: '残高', ko: '잔액', id: 'SALDO' },
  main: { ru: 'Основной', en: 'Main', es: 'Principal', zh: '主要', fr: 'Principal', de: 'Haupt', ja: 'メイン', ko: '기본', id: 'Utama' },
  bonus: { ru: 'Бонусы', en: 'Bonus', es: 'Bono', zh: '奖励', fr: 'Bonus', de: 'Bonus', ja: 'ボーナス', ko: '보너스', id: 'Bonus' },
  deposit: { ru: 'Пополнить', en: 'Deposit', es: 'Depositar', zh: '充值', fr: 'Déposer', de: 'Einzahlen', ja: '入金', ko: '입금', id: 'Deposit' },
  withdraw: { ru: 'Вывести', en: 'Withdraw', es: 'Retirar', zh: '提现', fr: 'Retirer', de: 'Abheben', ja: '出金', ko: '출금', id: 'Tarik' },
};

// Модалка обзора баланса (как на референсе): общий баланс ($CITY + TON),
// разбивка Основной/Бонусы и кнопки «Пополнить» / «Вывести».
// Открывается по клику на элемент баланса в шапке страницы «Бизнесы».
export default function BalanceOverviewModal({ open, onClose, user, onBalanceUpdate }) {
  const { language: lang } = useLanguage();
  const tr = (k) => (T[k][lang] || T[k].ru);

  const [showDeposit, setShowDeposit] = useState(false);
  const [showWithdraw, setShowWithdraw] = useState(false);
  const [depositAddress, setDepositAddress] = useState('');
  const [balanceTon, setBalanceTon] = useState(Number(user?.balance_ton || 0));

  // Адрес для пополнения — из публичного конфига (как в Sidebar).
  useEffect(() => {
    if (!open) return;
    fetch(`${API}/config`)
      .then((r) => r.json())
      .then((data) => { if (data.deposit_address) setDepositAddress(data.deposit_address); })
      .catch(() => {});
  }, [open]);

  useEffect(() => {
    if (user?.balance_ton !== undefined) setBalanceTon(Number(user.balance_ton || 0));
  }, [user?.balance_ton]);

  const bonusTon = Number(user?.bonus_balance || 0);
  const totalTon = balanceTon + bonusTon;
  const totalCity = tonToCity(totalTon);

  const openDeposit = () => { onClose(); setShowDeposit(true); };
  const openWithdraw = () => { onClose(); setShowWithdraw(true); };
  const handleUpdated = (newBal) => {
    setBalanceTon(newBal);
    if (onBalanceUpdate) onBalanceUpdate(newBal);
  };

  return (
    <>
      <Dialog open={open} onOpenChange={(v) => { if (!v) onClose(); }}>
        <DialogContent
          className="bg-[#0d1526] border-white/10 rounded-2xl p-5 sm:max-w-md gap-1.5"
          data-testid="balance-overview-modal"
        >
          <VisuallyHidden><DialogTitle>{tr('balance')}</DialogTitle></VisuallyHidden>

          {/* Заголовок: иконка кошелька + БАЛАНС */}
          <div className="flex items-center gap-2">
            <Wallet className="w-6 h-6 text-cyan-400" />
            <span className="text-gray-400 font-bold tracking-wide text-sm uppercase">{tr('balance')}</span>
          </div>

          {/* Общий баланс */}
          <div className="mt-1.5" data-testid="balance-overview-total">
            <span className="text-4xl font-extrabold text-white leading-none">{formatCity(totalCity)}</span>
            <span className="text-yellow-400 font-bold text-lg ml-2 align-baseline">$CITY</span>
          </div>
          <div className="text-gray-400 text-sm mt-1">≈ {formatTon(totalTon)} TON</div>

          {/* Разбивка */}
          <div className="mt-2.5 space-y-0.5">
            <div className="text-gray-400 text-sm" data-testid="balance-overview-main">
              {tr('main')}: {formatCity(tonToCity(balanceTon))} $CITY ({formatTon(balanceTon)} TON)
            </div>
            <div className="text-gray-400 text-sm" data-testid="balance-overview-bonus">
              {tr('bonus')}: {formatCity(tonToCity(bonusTon))} $CITY ({formatTon(bonusTon)} TON)
            </div>
          </div>

          {/* Кнопки Пополнить / Вывести */}
          <div className="grid grid-cols-2 gap-3 mt-3.5">
            <button
              type="button"
              onClick={openDeposit}
              data-testid="balance-overview-deposit-btn"
              className="flex items-center justify-center gap-2 rounded-xl bg-green-500 hover:bg-green-600 active:scale-[0.98] transition-all text-black font-bold text-base py-3.5"
            >
              <ArrowDownToLine className="w-5 h-5" />
              {tr('deposit')}
            </button>
            <button
              type="button"
              onClick={openWithdraw}
              data-testid="balance-overview-withdraw-btn"
              className="flex items-center justify-center gap-2 rounded-xl bg-orange-500 hover:bg-orange-600 active:scale-[0.98] transition-all text-black font-bold text-base py-3.5"
            >
              <ArrowUpFromLine className="w-5 h-5" />
              {tr('withdraw')}
            </button>
          </div>
        </DialogContent>
      </Dialog>

      <DepositModal
        isOpen={showDeposit}
        onClose={() => setShowDeposit(false)}
        onSuccess={() => { setShowDeposit(false); if (onBalanceUpdate) onBalanceUpdate(balanceTon); }}
        receiverAddress={depositAddress}
        updateBalance={handleUpdated}
      />
      <WithdrawModal
        isOpen={showWithdraw}
        onClose={() => setShowWithdraw(false)}
        onSuccess={() => { setShowWithdraw(false); if (onBalanceUpdate) onBalanceUpdate(balanceTon); }}
        currentBalance={balanceTon}
        userWallet={user?.wallet_address}
        updateBalance={handleUpdated}
      />
    </>
  );
}
