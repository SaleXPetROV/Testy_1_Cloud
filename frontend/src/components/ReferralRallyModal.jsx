import { useState, useEffect, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate } from 'react-router-dom';
import { Trophy, Users, Clock } from 'lucide-react';
import { useLanguage } from '@/context/LanguageContext';
import { useTranslation } from '@/lib/translations';
import '@/styles/promo.css';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api`;
const STORAGE_KEY = 'promo_last_seen_date_msk';

// ── MSK date helpers (used for daily cooldown) ────────────────
function todayMsk() {
  // Get today's date in MSK (UTC+3) as YYYY-MM-DD
  const now = new Date();
  const msk = new Date(now.getTime() + (3 * 60 - now.getTimezoneOffset()) * 60000);
  const y = msk.getUTCFullYear();
  const m = String(msk.getUTCMonth() + 1).padStart(2, '0');
  const d = String(msk.getUTCDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

function formatCountdown(endsAtIso, lang = 'ru') {
  try {
    const ends = new Date(endsAtIso);
    const diff = ends - new Date();
    if (diff <= 0) return null;
    const total = Math.floor(diff / 1000);
    const days = Math.floor(total / 86400);
    const hours = Math.floor((total % 86400) / 3600);
    const mins = Math.floor((total % 3600) / 60);
    const secs = total % 60;
    const suffix = {
      ru: { d: 'д', h: 'ч', m: 'м', s: 'с' },
      en: { d: 'd', h: 'h', m: 'm', s: 's' },
    };
    const s = suffix[lang] || suffix.en;
    return {
      d: String(days).padStart(2, '0'),
      h: String(hours).padStart(2, '0'),
      m: String(mins).padStart(2, '0'),
      s: String(secs).padStart(2, '0'),
      ds: s.d, hs: s.h, ms: s.m, ss: s.s,
    };
  } catch (_) {
    return null;
  }
}

export default function ReferralRallyModal({ user }) {
  const [data, setData] = useState(null);
  const [visible, setVisible] = useState(false);
  const [countdown, setCountdown] = useState(null);
  const { language } = useLanguage();
  const { t } = useTranslation(language);
  const timerRef = useRef(null);
  const navigate = useNavigate();

  const fetchPromo = useCallback(async () => {
    if (!user) return;
    try {
      const token = localStorage.getItem('token');
      const res = await fetch(`${API}/promo/active`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) return;
      const json = await res.json();
      setData(json);

      // Backend is the source of truth for `show_modal` (per-user, per-day in
      // MSK). We used to also gate on a local-storage last-seen flag, but that
      // broke the flow for freshly-registered users when the same browser had
      // previously dismissed the modal under a different account. Trust the
      // server response instead.
      if (json?.campaign && json?.show_modal) {
        setVisible(true);
      }
    } catch (e) {
      // silently ignore
    }
  }, [user]);

  useEffect(() => {
    if (!user) return;
    fetchPromo();
    // Also re-poll every 5 min in case admin turned it on/off
    const iv = setInterval(fetchPromo, 5 * 60 * 1000);
    return () => clearInterval(iv);
  }, [user, fetchPromo]);

  // Countdown ticker (1Hz while visible or campaign active)
  useEffect(() => {
    if (!data?.campaign?.ends_at) return;
    const tick = () => setCountdown(formatCountdown(data.campaign.ends_at, language));
    tick();
    timerRef.current = setInterval(tick, 1000);
    return () => timerRef.current && clearInterval(timerRef.current);
  }, [data?.campaign?.ends_at, language]);

  const handleClose = async () => {
    setVisible(false);
    try {
      localStorage.setItem(STORAGE_KEY, todayMsk());
    } catch (_) {}
    try {
      const token = localStorage.getItem('token');
      if (token) {
        await fetch(`${API}/promo/dismiss`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
        });
      }
    } catch (_) {}
  };

  // CTA "Открыть GRAM CITY" — dismiss the modal AND take the user straight
  // into the city MAP (the active GRAM ISLAND map), not the cities list.
  // Previously this only closed the modal, so on production/Telegram it
  // looked like the button "did nothing" (it just revealed the page behind).
  const handleOpenApp = () => {
    setVisible(false);
    // Fire-and-forget the daily-dismiss so the poll doesn't reopen it.
    handleClose();
    try {
      navigate('/ton-island');
    } catch (_) {
      window.location.assign('/ton-island');
    }
  };

  if (!visible || !data?.campaign) return null;

  const isFinished = data.mode === 'finished';
  const prizes = data.campaign?.config?.prizes_ton || [100, 50, 20];
  const perActive = data.campaign?.config?.per_active_ton || 1.5;
  const top3 = data.top3 || [];
  const medals = ['🥇', '🥈', '🥉'];

  // Backdrop click dismisses (since there's no X button)
  const handleBackdropClick = (e) => {
    if (e.target === e.currentTarget) {
      handleClose();
    }
  };

  return createPortal(
    <div
      className="fixed inset-0 flex items-center justify-center p-3 sm:p-6 rally-rainbow-bg"
      style={{ zIndex: 2147483000, pointerEvents: 'auto' }}
      data-testid="referral-rally-modal"
      role="dialog"
      aria-modal="true"
      onClick={handleBackdropClick}
    >
      {/* Card */}
      <div className="rally-glass rounded-3xl w-full max-w-lg max-h-[92vh] flex flex-col text-white relative">
        <div className="overflow-y-auto p-5 sm:p-7 pb-3 sm:pb-4 flex-1">
        {/* Header */}
        <div className="text-center mb-4 sm:mb-6">
          <h2 className="text-2xl sm:text-3xl font-black rally-shine-text mb-2 leading-tight" data-testid="referral-rally-title">
            <span className="align-middle mr-1 sm:mr-2">🔥</span>
            <span className="align-middle">{t('promoReferralTitle') || 'МЕГА-РАЛЛИ РЕФЕРАЛОВ!'}</span>
          </h2>
          <p className="text-sm sm:text-base text-white/90 max-w-md mx-auto leading-snug">
            {(t('promoReferralSubtitle') || 'Приглашай друзей, получай {n} TON за каждого активного игрока и забери главный куш!').replace('{n}', perActive)}
          </p>
        </div>

        {/* Prize fund */}
        {!isFinished && (
          <div className="mb-4 sm:mb-5">
            <div className="text-center text-sm sm:text-base font-bold uppercase tracking-wider text-yellow-300 mb-2 flex items-center justify-center gap-2">
              <Trophy className="w-4 h-4" />
              {t('promoPrizeFund') || 'ПРИЗОВОЙ ФОНД ТОП-3'}
            </div>
            <div className="grid grid-cols-3 gap-2 sm:gap-3">
              {[0, 1, 2].map((i) => (
                <div
                  key={i}
                  className="bg-black/40 border border-white/20 rounded-xl p-2 sm:p-3 text-center"
                  data-testid={`promo-prize-${i + 1}`}
                >
                  <div className={`text-xl sm:text-2xl mb-1 rally-medal-${i + 1}`}>{medals[i]}</div>
                  <div className="font-mono text-sm sm:text-lg font-bold text-white">
                    {prizes[i] || 0} TON
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Current leaders — unified single card */}
        <div className="mb-4 sm:mb-5">
          <div className="text-center text-sm sm:text-base font-bold uppercase tracking-wider text-cyan-300 mb-2 flex items-center justify-center gap-2">
            <Users className="w-4 h-4" />
            {isFinished
              ? (t('promoFinalWinners') || 'ПОБЕДИТЕЛИ АКЦИИ')
              : (t('promoCurrentLeaders') || 'ТЕКУЩИЕ ЛИДЕРЫ')}
          </div>
          <div className="bg-black/40 border border-white/15 rounded-xl overflow-hidden" data-testid="promo-leaders-card">
            {(() => {
              // Only show placings for users with at least one ACTIVE
              // referral. If nobody is active yet (or the campaign has
              // just started), fall back to a clear localized notice
              // instead of misleading "0 / N" rows. During the finished
              // stage we still show the actual winners regardless of
              // whether their `active` count is > 0.
              const activeLeaders = isFinished
                ? top3
                : (top3 || []).filter(r => Number(r.active || 0) > 0);
              if (activeLeaders.length === 0) {
                return (
                  <div
                    className="text-center text-white/70 text-sm py-4 px-3"
                    data-testid="promo-no-active-refs"
                  >
                    {t('promoNoActiveRefs') || 'Unfortunately, there are no active referrals at the moment!'}
                  </div>
                );
              }
              return activeLeaders.map((row, i) => (
                <div
                  key={row.user_id || i}
                  className="flex items-center justify-between px-3 py-2.5 sm:px-4 sm:py-3"
                  data-testid={`promo-leader-${i + 1}`}
                >
                  <div className="flex items-center gap-2 sm:gap-3 min-w-0">
                    <div className={`text-xl sm:text-2xl rally-medal-${i + 1} flex-shrink-0`}>{medals[i]}</div>
                    <div className="min-w-0">
                      <div className="font-bold text-white truncate text-sm sm:text-base">
                        @{row.username || '—'}
                      </div>
                      <div className="text-[11px] sm:text-xs text-white/70 font-mono">
                        {row.active || 0} / {row.total || 0} {t('promoRefsShort') || 'реф.'}
                      </div>
                    </div>
                  </div>
                  <div className="text-yellow-300 font-mono text-xs sm:text-sm font-bold flex-shrink-0">
                    {prizes[i] || 0} TON
                  </div>
                </div>
              ));
            })()}
          </div>
        </div>

        {/* Countdown or finished label */}
        {!isFinished && countdown && (
          <div className="mb-4">
            <div className="text-center text-xs sm:text-sm uppercase tracking-wider text-white/80 mb-2 flex items-center justify-center gap-1">
              <Clock className="w-3.5 h-3.5" />
              {t('promoCountdown') || 'До фиксации результатов осталось'}:
            </div>
            <div className="flex items-center justify-center gap-1 sm:gap-2 font-mono font-black" data-testid="referral-rally-countdown">
              {[
                { v: countdown.d, s: countdown.ds },
                { v: countdown.h, s: countdown.hs },
                { v: countdown.m, s: countdown.ms },
                { v: countdown.s, s: countdown.ss },
              ].map((cell, i) => (
                <div key={i} className="flex items-baseline gap-0.5">
                  <div className="bg-black/60 border border-white/25 rounded-lg px-2 py-1 sm:px-3 sm:py-2 text-lg sm:text-2xl text-white min-w-[38px] sm:min-w-[54px] text-center">
                    {cell.v}
                  </div>
                  <span className="text-white/80 text-[10px] sm:text-xs">{cell.s}</span>
                  {i < 3 && <span className="text-white/60 text-lg sm:text-2xl mx-0.5">:</span>}
                </div>
              ))}
            </div>
          </div>
        )}

        {isFinished && (
          <div className="mb-4 text-center bg-black/50 border border-yellow-400/40 rounded-xl py-3 px-4">
            <div className="text-yellow-300 font-bold text-sm sm:text-base uppercase tracking-wider">
              {t('promoFinishedLabel') || 'АКЦИЯ ЗАВЕРШЕНА'}
            </div>
          </div>
        )}

        {/* My stats block removed per requirement */}
        </div>

        {/* CTA — sticky footer */}
        <div
          className="p-5 sm:p-7 pt-3 sm:pt-4 border-t border-white/10 bg-black/20 rounded-b-3xl"
          style={{ paddingBottom: 'max(1.25rem, env(safe-area-inset-bottom))' }}
          onClick={(e) => e.stopPropagation()}
        >
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); handleOpenApp(); }}
            data-testid="referral-rally-cta"
            style={{ touchAction: 'manipulation', WebkitTapHighlightColor: 'transparent' }}
            className="block w-full text-center py-3 rounded-xl bg-yellow-400 hover:bg-yellow-300 active:bg-yellow-500 text-black font-bold text-sm sm:text-base transition-colors touch-manipulation select-none cursor-pointer"
          >
            {t('promoOpenApp') || 'ОТКРЫТЬ GRAM CITY'}
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}
