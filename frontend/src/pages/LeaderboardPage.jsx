import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Trophy, Coins, Building2, MapPin, TrendingUp, Medal, Crown, RefreshCw, Store, Users } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import PageHeader from '@/components/PageHeader';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import Sidebar from '@/components/Sidebar';
import PartnersTab from '@/components/PartnersTab';
import { useLanguage } from '@/context/LanguageContext';
import { useTranslation } from '@/lib/translations';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api`;

export default function LeaderboardPage({ user }) {
  const [players, setPlayers] = useState([]);
  const [me, setMe] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [sortBy, setSortBy] = useState('balance');
  const [promoActive, setPromoActive] = useState(false);
  const { language } = useLanguage();
  const { t } = useTranslation(language);

  const fetchLeaderboard = async () => {
    setIsLoading(true);
    try {
      const meParam = user?.id ? `&me_id=${encodeURIComponent(user.id)}` : '';
      const res = await fetch(`${API}/leaderboard?sort_by=${sortBy}&limit=50${meParam}`);
      const data = await res.json();
      setPlayers(data.players || []);
      setMe(data.me || null);
    } catch (error) {
      console.error('Failed to fetch leaderboard:', error);
    } finally {
      setIsLoading(false);
    }
  };

  // Check whether partners tab should be visible
  useEffect(() => {
    const check = async () => {
      try {
        const token = localStorage.getItem('token');
        if (!token) return;
        const res = await fetch(`${API}/promo/active`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        const data = await res.json();
        const isActive = !!(data?.campaign);
        setPromoActive(isActive);
        // Auto-select partners tab on initial load if campaign is active
        if (isActive && sortBy === 'balance') {
          setSortBy('partners');
        }
      } catch (_) {}
    };
    check();
    const iv = setInterval(check, 60 * 1000);
    return () => clearInterval(iv);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (sortBy !== 'partners') fetchLeaderboard();
  }, [sortBy]);

  const getRankIcon = (rank) => {
    if (rank === 1) return <Crown className="w-6 h-6 text-yellow-400" />;
    if (rank === 2) return <Medal className="w-6 h-6 text-gray-300" />;
    if (rank === 3) return <Medal className="w-6 h-6 text-amber-600" />;
    return <span className="w-6 h-6 flex items-center justify-center text-text-muted font-mono">#{rank}</span>;
  };

  const getRankBg = (rank) => {
    if (rank === 1) return 'bg-yellow-500/10 border-yellow-500/30';
    if (rank === 2) return 'bg-gray-400/10 border-gray-400/30';
    if (rank === 3) return 'bg-amber-600/10 border-amber-600/30';
    return 'bg-white/5 border-white/10';
  };

  const metricValue = (p) => {
    if (!p) return '';
    if (sortBy === 'balance') return `${(p.balance_ton || 0).toFixed(1)} TON`;
    if (sortBy === 'income') return `${(p.total_income || 0).toFixed(1)} TON`;
    if (sortBy === 'businesses') return `${p.businesses_count || 0}`;
    if (sortBy === 'plots') return `${p.plots_count || 0}`;
    if (sortBy === 'trading') return `${(p.trading_volume || 0).toFixed(1)} TON`;
    return '';
  };

  // Show the pinned "your position" bar when the current user isn't already
  // visible in the top slice above.
  const meVisible = me && players.some((p) => p.id === me.id);
  const showMeBar = me && !meVisible;

  return (
    <div className="flex h-screen bg-void">
      <Sidebar user={user} />
      
      <div className="flex-1 overflow-hidden lg:ml-16">
        <ScrollArea className="h-full">
          <div className="p-4 lg:px-6 lg:pt-2 lg:pb-6 pt-0 space-y-4 lg:space-y-6">
            {/* Header - Mobile Optimized */}
            <PageHeader
              icon={<Trophy className="w-6 h-6 lg:w-8 lg:h-8 text-yellow-400" />}
              title={t('ratingTitle')}
              actionButtons={
                <Button onClick={fetchLeaderboard} variant="outline" size="icon" className="border-white/10 h-8 w-8 sm:h-10 sm:w-10" disabled={isLoading}>
                  <RefreshCw className={`w-3.5 h-3.5 sm:w-4 sm:h-4 ${isLoading ? 'animate-spin' : ''}`} />
                </Button>
              }
            />

            {/* Tabs for different rankings - Mobile Scrollable */}
            <Tabs value={sortBy} onValueChange={setSortBy}>
              <div className="overflow-x-auto -mx-4 px-4">
                <TabsList className="bg-white/5 border border-white/10 inline-flex min-w-max">
                  {promoActive && (
                    <TabsTrigger value="partners" className="data-[state=active]:bg-pink-500 data-[state=active]:text-white text-xs sm:text-sm px-2 sm:px-4" data-testid="leaderboard-tab-partners">
                      <Users className="w-4 h-4 sm:mr-2" />
                      <span className="hidden sm:inline">{t('partnersTabTitle') || 'Партнёры'}</span>
                    </TabsTrigger>
                  )}
                  <TabsTrigger value="balance" className="data-[state=active]:bg-cyber-cyan data-[state=active]:text-black text-xs sm:text-sm px-2 sm:px-4">
                    <Coins className="w-4 h-4 sm:mr-2" />
                    <span className="hidden sm:inline">{t('byBalance')}</span>
                  </TabsTrigger>
                  <TabsTrigger value="income" className="data-[state=active]:bg-green-500 data-[state=active]:text-black text-xs sm:text-sm px-2 sm:px-4">
                    <TrendingUp className="w-4 h-4 sm:mr-2" />
                    <span className="hidden sm:inline">{t('byIncome')}</span>
                  </TabsTrigger>
                  <TabsTrigger value="trading" className="data-[state=active]:bg-amber-500 data-[state=active]:text-black text-xs sm:text-sm px-2 sm:px-4" data-testid="leaderboard-tab-trading">
                    <Store className="w-4 h-4 sm:mr-2" />
                    <span className="hidden sm:inline">{t('byTrading')}</span>
                  </TabsTrigger>
                </TabsList>
              </div>
            </Tabs>

            {sortBy === 'partners' ? (
              <PartnersTab user={user} />
            ) : (
              <>
            {/* Top 3 - Mobile Optimized */}
            {players.length >= 3 && (
              <div className="grid grid-cols-3 gap-2 lg:gap-4">
                {[players[1], players[0], players[2]].map((player, idx) => {
                  const actualRank = idx === 0 ? 2 : idx === 1 ? 1 : 3;
                  const isFirst = actualRank === 1;
                  
                  return (
                    <motion.div
                      key={player?.id || idx}
                      initial={{ opacity: 0, y: 20 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: idx * 0.1 }}
                      className={`${isFirst ? 'transform lg:-translate-y-4' : ''}`}
                    >
                      <Card className={`glass-panel ${getRankBg(actualRank)} ${isFirst ? 'ring-2 ring-yellow-500/50' : ''}`}>
                        <CardContent className="p-3 lg:p-6 text-center">
                          <div className="mb-2 lg:mb-3 text-lg lg:text-2xl">{getRankIcon(actualRank)}</div>
                          <div className="w-10 h-10 lg:w-16 lg:h-16 mx-auto mb-2 lg:mb-3 bg-gradient-to-br from-cyber-cyan to-neon-purple rounded-full flex items-center justify-center text-lg lg:text-2xl font-bold text-black">
                            {(player?.username || 'U')[0].toUpperCase()}
                          </div>
                          <div className="font-bold text-white text-sm lg:text-lg mb-1 truncate">{player?.username || t('anonymous')}</div>
                          <div className="text-cyber-cyan font-mono text-xs lg:text-lg">
                            {sortBy === 'balance' && `${(player?.balance_ton || 0).toFixed(1)} TON`}
                            {sortBy === 'income' && `${(player?.total_income || 0).toFixed(1)} TON`}
                            {sortBy === 'businesses' && `${player?.businesses_count || 0}`}
                            {sortBy === 'plots' && `${player?.plots_count || 0}`}
                            {sortBy === 'trading' && `${(player?.trading_volume || 0).toFixed(1)} TON`}
                          </div>
                        </CardContent>
                      </Card>
                    </motion.div>
                  );
                })}
              </div>
            )}

            {/* Full Leaderboard - Mobile Optimized */}
            <Card className="glass-panel border-white/10">
              <CardContent className="p-0">
                <div className="divide-y divide-white/5">
                  {players.map((player, idx) => {
                    const isCurrentUser = player.id === user?.id;
                    
                    return (
                      <motion.div
                        key={player.id}
                        initial={{ opacity: 0, x: -20 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: idx * 0.03 }}
                        className={`flex items-center justify-between p-3 lg:p-4 hover:bg-white/5 transition-colors ${isCurrentUser ? 'bg-cyber-cyan/10' : ''}`}
                      >
                        <div className="flex items-center gap-2 lg:gap-4 min-w-0 flex-1">
                          <div className="w-8 lg:w-10 flex justify-center flex-shrink-0 text-sm lg:text-base">{getRankIcon(idx + 1)}</div>
                          <div className="w-8 h-8 lg:w-10 lg:h-10 bg-gradient-to-br from-cyber-cyan/50 to-neon-purple/50 rounded-full flex items-center justify-center font-bold text-white text-sm lg:text-base flex-shrink-0">
                            {(player.username || 'U')[0].toUpperCase()}
                          </div>
                          <div className="min-w-0 flex-1">
                            <div className="font-bold text-white text-sm lg:text-base flex items-center gap-1 lg:gap-2 truncate">
                              <span className="truncate">{player.username || t('anonymous')}</span>
                              {isCurrentUser && <Badge className="bg-cyber-cyan/20 text-cyber-cyan text-[10px] lg:text-xs flex-shrink-0">{t('youLabel')}</Badge>}
                            </div>
                            <div className="text-[10px] lg:text-xs text-text-muted">
                              {player.businesses_count || 0} {t('businessesCount')}
                            </div>
                          </div>
                        </div>
                        
                        <div className="text-right flex-shrink-0">
                          <div className="font-mono text-sm lg:text-lg text-white">
                            {sortBy === 'balance' && `${(player.balance_ton || 0).toFixed(1)} TON`}
                            {sortBy === 'income' && `${(player.total_income || 0).toFixed(1)} TON`}
                            {sortBy === 'businesses' && `${player.businesses_count || 0}`}
                            {sortBy === 'plots' && `${player.plots_count || 0}`}
                            {sortBy === 'trading' && `${(player.trading_volume || 0).toFixed(1)} TON`}
                          </div>
                          <div className="text-[10px] lg:text-xs text-text-muted hidden sm:block">
                            {sortBy === 'balance' && t('balanceSortLabel')}
                            {sortBy === 'income' && t('totalIncomeSortLabel')}
                            {sortBy === 'businesses' && t('bizSortLabel')}
                            {sortBy === 'plots' && t('plotsSortLabel')}
                            {sortBy === 'trading' && `${player.trades_count || 0} ${t('tradesCountLabel') || 'trades'}`}
                          </div>
                        </div>
                      </motion.div>
                    );
                  })}
                </div>
                
                {players.length === 0 && !isLoading && (
                  <div className="text-center py-12 text-text-muted">
                    <Trophy className="w-12 h-12 mx-auto mb-4 opacity-50" />
                    <p>{t('emptyRating')}</p>
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Pinned "your position" bar — shown when the current user is not
                in the visible top slice above. Present on every ranking tab. */}
            {showMeBar && (
              <div className="sticky bottom-2 z-10" data-testid="leaderboard-me-bar">
                <Card className="glass-panel border-cyber-cyan/50 bg-cyber-cyan/10 shadow-lg shadow-cyber-cyan/20 backdrop-blur-xl">
                  <CardContent className="p-3 lg:p-4">
                    <div className="flex items-center justify-between gap-2 lg:gap-4">
                      <div className="flex items-center gap-2 lg:gap-4 min-w-0 flex-1">
                        <div className="w-8 lg:w-10 flex justify-center flex-shrink-0 text-sm lg:text-base font-mono text-cyber-cyan">#{me.rank}</div>
                        <div className="w-8 h-8 lg:w-10 lg:h-10 bg-gradient-to-br from-cyber-cyan to-neon-purple rounded-full flex items-center justify-center font-bold text-black text-sm lg:text-base flex-shrink-0">
                          {(me.username || 'U')[0].toUpperCase()}
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="font-bold text-white text-sm lg:text-base flex items-center gap-2 truncate">
                            <span className="truncate">{me.username || t('anonymous')}</span>
                            <Badge className="bg-cyber-cyan/20 text-cyber-cyan text-[10px] lg:text-xs flex-shrink-0">{t('youLabel')}</Badge>
                          </div>
                          <div className="text-[10px] lg:text-xs text-text-muted">
                            {me.businesses_count || 0} {t('businessesCount')}
                          </div>
                        </div>
                      </div>
                      <div className="text-right flex-shrink-0">
                        <div className="font-mono text-sm lg:text-lg text-white">{metricValue(me)}</div>
                        <div className="text-[10px] lg:text-xs text-text-muted hidden sm:block">
                          {sortBy === 'trading' ? `${me.trades_count || 0} ${t('tradesCountLabel') || 'trades'}` : (
                            sortBy === 'balance' ? t('balanceSortLabel')
                            : sortBy === 'income' ? t('totalIncomeSortLabel')
                            : sortBy === 'businesses' ? t('bizSortLabel')
                            : t('plotsSortLabel')
                          )}
                        </div>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              </div>
            )}
              </>
            )}
          </div>
        </ScrollArea>
      </div>
    </div>
  );
}
