import { useState, useEffect, useCallback, useRef } from 'react';
import { motion } from 'framer-motion';
import { Trophy, Users, ChevronRight } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { useLanguage } from '@/context/LanguageContext';
import { useTranslation } from '@/lib/translations';
import '@/styles/promo.css';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api`;

/**
 * PartnersTab — leaderboard section for the Referral Rally promo.
 * Only rendered when a campaign is active OR finished within 7 days.
 * Features:
 *  - Full list (infinite scroll)
 *  - Sticky "you" row at bottom while user's row is out of viewport
 *  - Silent auto-refresh every 60s
 */
export default function PartnersTab({ user }) {
  const { language } = useLanguage();
  const { t } = useTranslation(language);

  const [rows, setRows] = useState([]);
  const [totalCount, setTotalCount] = useState(0);
  const [myStats, setMyStats] = useState(null);
  const [campaignActive, setCampaignActive] = useState(false);
  const [campaignFinished, setCampaignFinished] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [myRowVisible, setMyRowVisible] = useState(true);

  const sentinelRef = useRef(null);
  const myRowRef = useRef(null);
  const offsetRef = useRef(0);
  const doneRef = useRef(false);

  const fetchPage = useCallback(async (offset = 0, replace = false) => {
    const token = localStorage.getItem('token');
    if (!token) return;
    try {
      if (replace) setLoading(true);
      else setLoadingMore(true);
      const res = await fetch(`${API}/promo/referral-rally/leaderboard?offset=${offset}&limit=100`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) return;
      const data = await res.json();
      const newRows = data.rows || [];
      setTotalCount(data.total_count || 0);
      setMyStats(data.my_stats || null);
      setCampaignActive(!!data.campaign_active);
      setCampaignFinished(!!data.campaign_finished);
      if (replace) {
        setRows(newRows);
        offsetRef.current = newRows.length;
      } else {
        setRows(prev => [...prev, ...newRows]);
        offsetRef.current = offset + newRows.length;
      }
      doneRef.current = offsetRef.current >= (data.total_count || 0);
    } catch (_) {
      // silent
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, []);

  // Initial load + 60s auto-refresh (replace, not append)
  useEffect(() => {
    fetchPage(0, true);
    const iv = setInterval(() => {
      // Only auto-refresh the visible chunk (first page)
      fetchPage(0, true);
    }, 60 * 1000);
    return () => clearInterval(iv);
  }, [fetchPage]);

  // Infinite scroll: load next page when sentinel enters viewport
  useEffect(() => {
    if (!sentinelRef.current) return;
    const io = new IntersectionObserver((entries) => {
      const first = entries[0];
      if (first.isIntersecting && !loadingMore && !doneRef.current) {
        fetchPage(offsetRef.current, false);
      }
    }, { rootMargin: '200px' });
    io.observe(sentinelRef.current);
    return () => io.disconnect();
  }, [fetchPage, loadingMore]);

  // Watch "my row" visibility
  useEffect(() => {
    if (!myRowRef.current) {
      setMyRowVisible(false);
      return;
    }
    const io = new IntersectionObserver((entries) => {
      setMyRowVisible(!!entries[0]?.isIntersecting);
    }, { threshold: 0.5 });
    io.observe(myRowRef.current);
    return () => io.disconnect();
  }, [rows, myStats?.rank]);

  const medal = (rank) => {
    if (rank === 1) return <span className="rally-medal-1 text-xl">🥇</span>;
    if (rank === 2) return <span className="rally-medal-2 text-xl">🥈</span>;
    if (rank === 3) return <span className="rally-medal-3 text-xl">🥉</span>;
    return <span className="font-mono text-text-muted">#{rank}</span>;
  };

  if (loading && rows.length === 0) {
    return (
      <div className="flex items-center justify-center py-16">
        <div className="w-8 h-8 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="relative pb-16">
      {/* Header info */}
      <Card className="glass-panel border-white/10 mb-3">
        <CardContent className="p-3 sm:p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-white">
              <Trophy className="w-5 h-5 text-yellow-400" />
              <span className="font-bold text-sm sm:text-base">
                {campaignFinished
                  ? (t('promoFinishedLabel') || 'АКЦИЯ ЗАВЕРШЕНА')
                  : (t('partnersTabTitle') || 'Партнёры')}
              </span>
            </div>
            <div className="text-xs sm:text-sm text-text-muted">
              {totalCount} {t('partnersTotalRefs') || 'рефоводов'}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Column header (desktop only) */}
      <div className="hidden sm:grid grid-cols-[60px_1fr_100px_100px] gap-2 px-3 py-2 text-[11px] uppercase tracking-wider text-text-muted">
        <div>#</div>
        <div>{t('partnersColumnUser') || 'Пользователь'}</div>
        <div className="text-right">{t('partnersColumnActive') || 'Активные'}</div>
        <div className="text-right">{t('partnersColumnTotal') || 'Всего'}</div>
      </div>

      <Card className="glass-panel border-white/10">
        <CardContent className="p-0">
          <div className="divide-y divide-white/5">
            {rows.length === 0 && (
              <div className="text-center py-12 text-text-muted text-sm">
                {t('partnersEmpty') || 'Пока никто не пригласил рефералов'}
              </div>
            )}
            {rows.map((r, idx) => {
              const isMe = r.user_id === user?.id;
              const rank = r.rank || (idx + 1);
              return (
                <motion.div
                  key={r.user_id || idx}
                  ref={isMe ? myRowRef : null}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ duration: 0.15 }}
                  className={`grid grid-cols-[60px_1fr_60px_60px] sm:grid-cols-[60px_1fr_100px_100px] gap-2 items-center px-3 py-2.5 sm:py-3 hover:bg-white/5 ${isMe ? 'bg-cyan-500/10' : ''}`}
                  data-testid={`partners-row-${rank}`}
                >
                  <div className="flex items-center justify-start">{medal(rank)}</div>
                  <div className="min-w-0 flex items-center gap-2">
                    <div className="w-7 h-7 sm:w-8 sm:h-8 rounded-full bg-gradient-to-br from-cyan-400 to-purple-500 flex items-center justify-center text-black text-xs sm:text-sm font-bold flex-shrink-0">
                      {(r.username || 'U')[0].toUpperCase()}
                    </div>
                    <div className="min-w-0 text-white font-medium truncate text-xs sm:text-sm">
                      @{r.username || '—'}
                      {isMe && (
                        <span className="ml-1 text-[10px] text-cyan-300 font-bold uppercase">
                          ({t('youLabel') || 'вы'})
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="text-right text-green-300 font-mono font-bold text-xs sm:text-sm">
                    {r.active || 0}
                  </div>
                  <div className="text-right text-text-muted font-mono text-xs sm:text-sm">
                    {r.total || 0}
                  </div>
                </motion.div>
              );
            })}
          </div>

          {/* Infinite scroll sentinel */}
          {!doneRef.current && rows.length > 0 && (
            <div ref={sentinelRef} className="flex items-center justify-center py-4">
              {loadingMore ? (
                <div className="w-5 h-5 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin" />
              ) : (
                <div className="text-text-muted text-xs flex items-center gap-1">
                  <ChevronRight className="w-3 h-3" />
                  {t('partnersLoadMore') || 'Прокрутите для загрузки'}
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Sticky "you" row at bottom */}
      {myStats?.rank && !myRowVisible && (
        <div
          className="leaderboard-sticky-you fixed left-0 right-0 bottom-0 lg:left-16 px-3 py-2.5"
          data-testid="partners-sticky-you"
        >
          <div className="grid grid-cols-[50px_1fr_50px_50px] sm:grid-cols-[60px_1fr_100px_100px] gap-2 items-center max-w-4xl mx-auto">
            <div className="flex items-center">
              <span className="font-mono text-cyan-300 font-bold text-sm">#{myStats.rank}</span>
            </div>
            <div className="min-w-0 flex items-center gap-2">
              <div className="w-7 h-7 rounded-full bg-cyan-500 flex items-center justify-center text-black text-xs font-bold flex-shrink-0">
                {(user?.username || 'U')[0].toUpperCase()}
              </div>
              <div className="text-white font-medium text-xs sm:text-sm truncate">
                @{user?.username || '—'}
                <span className="ml-1 text-[10px] text-cyan-300 font-bold uppercase">
                  ({t('youLabel') || 'вы'})
                </span>
              </div>
            </div>
            <div className="text-right text-green-300 font-mono font-bold text-xs sm:text-sm">
              {myStats.active}
            </div>
            <div className="text-right text-text-muted font-mono text-xs sm:text-sm">
              {myStats.total}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
