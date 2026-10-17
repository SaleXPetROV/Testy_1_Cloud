/**
 * TransactionHistoryPage - User transaction history
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  History, ArrowUpRight, ArrowDownRight, ChevronLeft, ChevronRight,
  Filter, Calendar, X, ExternalLink, Wallet, Building2,
  Package, Users, ShieldCheck, Truck, Copy, Check
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { toast } from 'sonner';
import Sidebar from '@/components/Sidebar';
import { useTranslation } from '@/lib/translations';
import { useLanguage } from '@/context/LanguageContext';
import { getResourceName } from '@/lib/resourceConfig';
import { getBusinessName } from '@/lib/businessNames';
import { tTransactionType, tTransactionStatus } from '@/lib/translationsExtra';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

const TYPE_ICONS = {
  deposit: <ArrowDownRight className="w-5 h-5 text-green-400" />,
  withdrawal: <ArrowUpRight className="w-5 h-5 text-red-400" />,
  land_purchase: <Building2 className="w-5 h-5 text-blue-400" />,
  business_build: <Building2 className="w-5 h-5 text-purple-400" />,
  resource_sale: <Package className="w-5 h-5 text-green-400" />,
  resource_purchase: <Package className="w-5 h-5 text-orange-400" />,
  patron_fee: <Users className="w-5 h-5 text-yellow-400" />,
  warehouse_purchase: <Truck className="w-5 h-5 text-blue-400" />,
  default: <Wallet className="w-5 h-5 text-text-muted" />,
};

export default function TransactionHistoryPage({ user }) {
  const navigate = useNavigate();
  const { language: lang } = useLanguage();
  const { t } = useTranslation(lang);
  const [loading, setLoading] = useState(true);
  const [transactions, setTransactions] = useState([]);
  const [pagination, setPagination] = useState({ page: 1, pages: 1, total: 0 });
  const [typeFilter, setTypeFilter] = useState('all');
  const [types, setTypes] = useState({});
  const [summary, setSummary] = useState(null);
  const [copiedId, setCopiedId] = useState(null);
  
  const [selectedTx, setSelectedTx] = useState(null);
  const [showDetails, setShowDetails] = useState(false);
  
  const token = localStorage.getItem('token');

  const copyToClipboard = async (text) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedId(text);
      toast.success(t('idCopied'));
      setTimeout(() => setCopiedId(null), 2000);
    } catch (e) {
      toast.error(t('copyError'));
    }
  };

  const fetchTransactions = useCallback(async (page = 1) => {
    if (!token) {
      navigate('/auth?mode=login');
      return;
    }
    
    setLoading(true);
    try {
      const params = new URLSearchParams({ page, limit: 20 });
      if (typeFilter !== 'all') params.append('type_filter', typeFilter);
      
      const res = await fetch(`${BACKEND_URL}/api/history/transactions?${params}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      
      if (res.ok) {
        const data = await res.json();
        setTransactions(data.transactions);
        setPagination(data.pagination);
      }
    } catch (e) {
      console.error('Fetch transactions error:', e);
    } finally {
      setLoading(false);
    }
  }, [token, navigate, typeFilter]);

  const fetchTypes = useCallback(async () => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/history/types`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setTypes(data.types);
      }
    } catch (e) {
      console.error('Fetch types error:', e);
    }
  }, [token]);

  const fetchSummary = useCallback(async () => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/history/summary`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setSummary(data);
      }
    } catch (e) {
      console.error('Fetch summary error:', e);
    }
  }, [token]);

  useEffect(() => {
    fetchTypes();
    fetchSummary();
  }, [fetchTypes, fetchSummary]);

  useEffect(() => {
    fetchTransactions(1);
  }, [fetchTransactions, typeFilter]);

  const openDetails = async (txId) => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/history/transactions/${txId}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setSelectedTx(data);
        setShowDetails(true);
      }
    } catch (e) {
      toast.error('Ошибка загрузки деталей');
    }
  };

  const formatDate = (dateStr) => {
    const date = new Date(dateStr);
    return date.toLocaleDateString('ru-RU', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  const formatAmount = (amount) => {
    if (amount === undefined || amount === null || isNaN(amount)) {
      return <span className="text-text-muted">0.00 TON</span>;
    }
    const numAmount = Number(amount);
    const isPositive = numAmount > 0;
    const absAmount = Math.abs(numAmount);
    return (
      <span className={isPositive ? 'text-green-400' : 'text-red-400'}>
        {isPositive ? '+' : '-'}{absAmount.toFixed(2)} TON
      </span>
    );
  };

  return (
    <div className="flex h-screen bg-void">
      <Sidebar user={user} />
      
      <div className="flex-1 overflow-auto lg:ml-16">
        <div className="relative min-h-screen font-rajdhani pb-20 lg:pb-0">
          {/* Background grid */}
          <div className="absolute inset-0 opacity-10 pointer-events-none">
            <div 
              className="absolute inset-0"
              style={{
                backgroundImage: `
                  linear-gradient(rgba(0, 240, 255, 0.1) 1px, transparent 1px),
                  linear-gradient(90deg, rgba(0, 240, 255, 0.1) 1px, transparent 1px)
                `,
                backgroundSize: '50px 50px',
              }}
            />
          </div>

          {/* Main Content */}
          <div className="relative z-10 container mx-auto px-4 sm:px-6 tg-header-pad sm:py-12 max-w-4xl">
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              className="space-y-6"
            >
              {/* Header */}
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex items-center gap-2 min-h-[40px]">
                  <History className="w-5 h-5 sm:w-8 sm:h-8 text-cyber-cyan flex-shrink-0" />
                  <div className="flex flex-col justify-center">
                    <h1 className="font-unbounded text-base sm:text-2xl font-bold text-white uppercase tracking-tight leading-tight">
                      {t('transactionHistory')}
                    </h1>
                    <p className="text-text-muted text-[10px] sm:text-sm leading-tight">
                      {t('allTransactions')}
                    </p>
                  </div>
                </div>
                
                {/* Filter - full width on mobile with small side paddings, inline on desktop */}
                <Select value={typeFilter} onValueChange={setTypeFilter}>
                  <SelectTrigger
                    data-testid="tx-type-filter"
                    className="w-full sm:w-40 bg-panel border-white/10 text-white px-2 sm:px-3"
                  >
                    <Filter className="w-4 h-4 mr-2 flex-shrink-0" />
                    <SelectValue placeholder={t('filterLabel')} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">{t('allOperations')}</SelectItem>
                    {Object.entries(types).map(([key, info]) => (
                      <SelectItem key={key} value={key}>
                        {info.icon} {tTransactionType(key, lang) || info.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {/* Transaction List */}
              <div className="glass-panel rounded-2xl border border-white/10 overflow-hidden">
                {loading ? (
                  <div className="p-8 text-center text-text-muted">
                    {t('loading')}
                  </div>
                ) : transactions.length === 0 ? (
                  <div className="p-8 text-center text-text-muted">
                    <History className="w-12 h-12 mx-auto mb-3 opacity-30" />
                    <p>{t('noTransactions')}</p>
                  </div>
                ) : (
                  <div className="divide-y divide-white/5">
                    {transactions.map((tx) => {
                      const amount = tx.amount ?? tx.amount_ton ?? 0;
                      // Always derive $CITY from the corrected `amount` so it
                      // matches the detail modal exactly (handles tax + credit).
                      const amountCity = Math.abs(amount) > 0 ? (amount * 1000) : (tx.amount_city ?? 0);
                      const isPositive = amount > 0;
                      const isNegative = amount < 0;
                      const sign = isPositive ? '+' : isNegative ? '-' : '';
                      const colorClass = isPositive ? 'text-green-400' : isNegative ? 'text-red-400' : 'text-white';
                      
                      return (
                        <button
                          key={tx.id}
                          onClick={() => openDetails(tx.id)}
                          data-testid={`tx-${tx.id}`}
                          className="w-full p-3 sm:p-4 flex items-center gap-3 sm:gap-4 hover:bg-white/5 transition-colors text-left"
                        >
                          {/* Icon */}
                          <div className="w-9 h-9 sm:w-10 sm:h-10 rounded-xl bg-white/5 flex items-center justify-center flex-shrink-0">
                            {TYPE_ICONS[tx.type] || TYPE_ICONS.default}
                          </div>
                          
                          {/* Left side: Operation name + Date */}
                          <div className="flex-1 min-w-0">
                            <p className="text-white font-medium text-sm sm:text-base truncate">
                              {tx.type_icon} {tTransactionType(tx.tx_type, lang) || tx.type_name}
                            </p>
                            <p className="text-text-muted text-xs mt-0.5">
                              {formatDate(tx.created_at)}
                              <span className="ml-2 opacity-50">ID: {tx.id?.slice(0, 8)}...</span>
                            </p>
                          </div>
                          
                          {/* Right side: Status on top, Amount in $CITY below */}
                          <div className="flex flex-col items-end gap-1 flex-shrink-0">
                            {tx.status_display && (
                              <span className={`text-[10px] sm:text-xs px-2 py-0.5 rounded-full whitespace-nowrap ${
                                tx.status_color === 'green' ? 'bg-green-500/20 text-green-400' :
                                tx.status_color === 'yellow' ? 'bg-yellow-500/20 text-yellow-400' :
                                tx.status_color === 'blue' ? 'bg-blue-500/20 text-blue-400' :
                                tx.status_color === 'red' ? 'bg-red-500/20 text-red-400' :
                                'bg-gray-500/20 text-gray-400'
                              }`}>
                                {tTransactionStatus(tx.status_key, lang) || tx.status_display}
                              </span>
                            )}
                            <p className={`text-sm sm:text-base font-medium ${colorClass}`}>
                              {sign}{Math.round(Math.abs(amountCity)).toLocaleString('en-US')} $CITY
                            </p>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                )}
                
                {/* Pagination */}
                {pagination.pages > 1 && (
                  <div className="p-4 border-t border-white/5 flex items-center justify-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => fetchTransactions(pagination.page - 1)}
                      disabled={pagination.page <= 1}
                      className="border-white/10"
                    >
                      <ChevronLeft className="w-4 h-4" />
                    </Button>
                    <span className="text-text-muted text-sm px-4">
                      {pagination.page} / {pagination.pages}
                    </span>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => fetchTransactions(pagination.page + 1)}
                      disabled={pagination.page >= pagination.pages}
                      className="border-white/10"
                    >
                      <ChevronRight className="w-4 h-4" />
                    </Button>
                  </div>
                )}
              </div>
            </motion.div>
          </div>
        </div>
      </div>

      {/* Transaction Details Dialog */}
      <Dialog open={showDetails} onOpenChange={setShowDetails}>
        <DialogContent className="bg-panel border-white/10 max-w-md">
          <DialogHeader>
            <DialogTitle className="text-white font-unbounded">
              {t('transactionDetails')}
            </DialogTitle>
          </DialogHeader>
          
          {selectedTx && (
            <div className="space-y-4">
              {/* Amount in $CITY (main) */}
              <div className="text-center p-4 bg-white/5 rounded-xl">
                {(() => {
                  const amount = selectedTx.amount ?? selectedTx.amount_ton ?? 0;
                  // Always derive $CITY from the corrected `amount` (handles
                  // tax/credit adjustments). Falls back to amount_city only if
                  // `amount` is exactly 0 from a legacy zero-amount tx.
                  const amountCity = Math.abs(amount) > 0 ? (amount * 1000) : (selectedTx.amount_city ?? 0);
                  const isPositive = amount > 0;
                  const isNegative = amount < 0;
                  const displayAmount = Math.abs(amount).toFixed(4);
                  // $CITY must always be an integer — round half-up.
                  const displayCity = Math.round(Math.abs(amountCity)).toLocaleString('en-US');
                  const sign = isPositive ? '+' : isNegative ? '-' : '';
                  const colorClass = isPositive ? 'text-green-400' : isNegative ? 'text-red-400' : 'text-white';
                  return (
                    <>
                      {/* Amount in $CITY - main */}
                      <p className={`text-3xl font-bold ${colorClass}`}>
                        {sign}{displayCity} $CITY
                      </p>
                      {/* Amount in TON - below */}
                      <p className={`text-lg ${colorClass} opacity-70 mt-1`}>
                        {sign}{displayAmount} TON
                      </p>
                    </>
                  );
                })()}
              </div>
              
              {/* Date and Time */}
              <div className="flex justify-between p-3 bg-white/5 rounded-lg">
                <span className="text-text-muted">{t('transactionDate') || 'Дата и время'}</span>
                <span className="text-white">{formatDate(selectedTx.created_at)}</span>
              </div>
              
              {/* Transaction ID */}
              <div className="flex items-center justify-between p-3 bg-white/5 rounded-lg gap-2">
                <span className="text-text-muted flex-shrink-0">ID</span>
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-white font-mono text-xs break-all">
                    {selectedTx.id}
                  </span>
                  <Button 
                    variant="ghost" 
                    size="sm" 
                    className="flex-shrink-0 h-7 w-7 p-0"
                    onClick={() => copyToClipboard(selectedTx.id)}
                  >
                    {copiedId === selectedTx.id ? (
                      <Check className="w-3.5 h-3.5 text-green-400" />
                    ) : (
                      <Copy className="w-3.5 h-3.5 text-text-muted" />
                    )}
                  </Button>
                </div>
              </div>
              
              {/* Operation Type */}
              <div className="flex justify-between items-center p-3 bg-white/5 rounded-lg">
                <span className="text-text-muted">{t('operationType') || 'Тип операции'}</span>
                <span className="text-white">
                  {selectedTx.type_icon} {tTransactionType(selectedTx.tx_type, lang) || selectedTx.type_name}
                </span>
              </div>
              
              {/* Status */}
              {selectedTx.status_display && (
                <div className="flex justify-between items-center p-3 bg-white/5 rounded-lg">
                  <span className="text-text-muted">{t('status') || 'Статус'}</span>
                  <span className={`px-3 py-1 rounded-full text-sm ${
                    selectedTx.status_color === 'green' ? 'bg-green-500/20 text-green-400' :
                    selectedTx.status_color === 'yellow' ? 'bg-yellow-500/20 text-yellow-400' :
                    selectedTx.status_color === 'blue' ? 'bg-blue-500/20 text-blue-400' :
                    selectedTx.status_color === 'red' ? 'bg-red-500/20 text-red-400' :
                    'bg-gray-500/20 text-gray-400'
                  }`}>
                    {tTransactionStatus(selectedTx.status_key, lang) || selectedTx.status_display}
                  </span>
                </div>
              )}
              
              {/* Дополнительные детали скрыты для операций ремонта по запросу */}
              {selectedTx.details &&
                Object.keys(selectedTx.details).length > 0 &&
                !['repair', 'business_repair'].includes(selectedTx.tx_type) && (
                <div className="space-y-2">
                  <p className="text-text-muted text-xs uppercase">{t('transactionDetailsLabel') || 'Детали'}</p>
                  <div className="p-3 bg-white/5 rounded-lg" data-testid="tx-details-block">
                    {(() => {
                      const details = selectedTx.details || {};
                      // Hide raw helper fields and (separate x / y — they are
                      // merged into one "Coordinates: [x; y]" row instead).
                      // For resource sale via contract (and direct resource
                      // sale) we also hide buyer / seller / net / tax: the
                      // user already sees how much they received in the
                      // green +N $CITY header, and the "Сумма ($CITY)" row
                      // below now reflects the NET (post-tax) value to
                      // avoid duplication.
                      const isResourceSale = (
                        selectedTx.tx_type === 'contract_payment_in' ||
                        selectedTx.tx_type === 'resource_sale' ||
                        selectedTx.tx_type === 'contract_payout' ||
                        details.net_city !== undefined
                      );
                      const HIDDEN_KEYS = new Set([
                        'plot_id', 'city_id', 'price', 'x', 'y',
                        ...(isResourceSale ? ['buyer', 'seller', 'net_city', 'tax_city', 'gross_city'] : []),
                      ]);
                      const entries = Object.entries(details).filter(([key]) => !HIDDEN_KEYS.has(key));
                      const hasX = details.x !== undefined && details.x !== null;
                      const hasY = details.y !== undefined && details.y !== null;

                      const labelMap = {
                        resource: t('resourceLabel'),
                        amount_units: t('tx_quantity'),          // units of the resource — not money
                        city: t('city') || 'Карта',
                        business_type: t('businessTypeLabel') || t('business') || 'Бизнес',
                        business_name: t('businessNameLabel') || 'Название бизнеса',
                        business_level: t('level') || 'Уровень',
                        contract_id: t('contract'),
                        buyer: t('buyer'),
                        seller: t('seller'),
                        gross_city: `${t('amount')} ($CITY)`,
                        net_city: `${t('youReceiveLabel')} ($CITY)`,
                        tax_city: `${t('taxLabel')} ($CITY)`,
                        // Credit payment details (only these 3 keys are kept)
                        lender_type: t('creditLenderTypeLabel') || (lang === 'en' ? 'Lender type' : 'Тип кредитора'),
                        lender_name: t('creditLenderNameLabel') || (lang === 'en' ? 'Lender' : 'Кредитор'),
                        credit_remaining_after: t('creditRemainingAfterLabel') || (lang === 'en' ? 'Debt remaining' : 'Остаток долга'),
                      };

                      const renderRow = (label, value, key) => (
                        <div key={key} className="flex justify-between py-2 first:pt-0 last:pb-0 gap-2">
                          <span className="text-text-muted flex-shrink-0">{label}</span>
                          <span className="text-white text-sm text-right truncate max-w-[60%]" title={String(value)}>
                            {value}
                          </span>
                        </div>
                      );

                      const rows = [];

                      // Combined Coordinates row: "x;y - [12;14]"
                      if (hasX || hasY) {
                        const xv = hasX ? Number(details.x).toLocaleString() : '?';
                        const yv = hasY ? Number(details.y).toLocaleString() : '?';
                        rows.push(renderRow(
                          `${t('coordinatesLabel') || 'Координаты'} (x;y)`,
                          `[${xv}; ${yv}]`,
                          '__coords__'
                        ));
                      }

                      for (const [key, rawValue] of entries) {
                        const label = labelMap[key] || key.replace(/_/g, ' ');
                        let displayValue;
                        if (key === 'business_type') {
                          displayValue = getBusinessName(rawValue, lang);
                        } else if (key === 'business_name') {
                          // value may be either an i18n object {en,ru,...} or a plain string
                          displayValue = getBusinessName(rawValue, lang);
                        } else if (key === 'amount_units' || key === 'business_level') {
                          displayValue = typeof rawValue === 'number'
                            ? rawValue.toLocaleString()
                            : String(rawValue);
                        } else if (key === 'gross_city' || key === 'net_city' || key === 'tax_city') {
                          // For resource sales we display NET (post-tax)
                          // under the "Сумма ($CITY)" row to avoid showing
                          // separate gross/net/tax. For other tx types we
                          // keep the raw value.
                          if (key === 'gross_city' && isResourceSale && details.net_city !== undefined) {
                            displayValue = `${Math.round(Number(details.net_city))} $CITY`;
                          } else {
                            displayValue = `${Math.round(Number(rawValue))} $CITY`;
                          }
                        } else if (key === 'lender_type') {
                          // Translate enum values government / bank
                          const v = String(rawValue || '').toLowerCase();
                          if (v === 'government') {
                            displayValue = lang === 'en' ? 'Government' : 'Государство';
                          } else if (v === 'bank') {
                            displayValue = lang === 'en' ? 'Bank' : 'Банк';
                          } else {
                            displayValue = String(rawValue);
                          }
                        } else if (key === 'credit_remaining_after') {
                          // value is TON — show $CITY equivalent (integer)
                          const cityVal = Math.round(Number(rawValue) * 1000);
                          displayValue = `${cityVal.toLocaleString('en-US')} $CITY`;
                        } else if (key === 'contract_id' && typeof rawValue === 'string') {
                          displayValue = rawValue.slice(0, 8) + '…';
                        } else if (key === 'resource' && typeof rawValue === 'string') {
                          displayValue = getResourceName(rawValue, lang);
                        } else if (rawValue && typeof rawValue === 'object') {
                          // Generic i18n object: { en: "...", ru: "..." }
                          if (rawValue[lang] || rawValue.en || rawValue.ru) {
                            displayValue = rawValue[lang] || rawValue.en || rawValue.ru;
                          } else {
                            displayValue = Object.values(rawValue).filter(v => typeof v === 'string')[0] || JSON.stringify(rawValue);
                          }
                        } else {
                          displayValue = String(rawValue);
                        }
                        rows.push(renderRow(label, displayValue, key));
                      }

                      // resource deals: total in $CITY + price of ONE unit (the seller sees it after tax)
                      const units = Number(details.amount_units || 0);
                      if (units > 0 && details.resource !== undefined) {
                        const fromHeader = Math.abs(Number(selectedTx.amount ?? selectedTx.amount_ton ?? 0)) * 1000;
                        const total = isResourceSale
                          ? Number(details.net_city ?? fromHeader)
                          : Number(details.gross_city ?? fromHeader);
                        if (details.gross_city === undefined || isResourceSale) {
                          rows.push(renderRow(`${t('tx_total')} ($CITY)`, total.toLocaleString(undefined, { maximumFractionDigits: 2 }), '__total__'));
                        }
                        rows.push(renderRow(isResourceSale ? t('tx_price_per_unit_net') : t('tx_price_per_unit'),
                          `${(total / units).toLocaleString(undefined, { maximumFractionDigits: 4 })} $CITY`, '__unit__'));
                      }
                      return rows;
                    })()}
                  </div>
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
