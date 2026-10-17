import React, { useEffect, useState, useMemo } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate } from 'react-router-dom';
import { useLanguage } from '@/context/LanguageContext';
import { useTutorial } from '@/context/TutorialContext';
import { getUiText } from '@/lib/tutorialTranslations';
import { useTranslation } from '@/lib/translations';
import { getResourceName } from '@/lib/resourceConfig';
import { T3_REWARD_OPTIONS, getT3BonusDescription, getT3Icon } from '@/lib/t3RewardInfo';
import { enterRealMode } from '@/lib/gameMode';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { CheckCircle2, Gift, Sparkles, AlertTriangle } from 'lucide-react';
import { toast } from 'sonner';
import confetti from 'canvas-confetti';

/**
 * Fires a celebratory confetti burst tinted with the legendary palette.
 * Bound to the T3 reward claim button so picking up the once-per-account
 * tutorial reward feels like an actual win.
 */
const fireRewardConfetti = () => {
  try {
    const colors = ['#a855f7', '#ec4899', '#22d3ee', '#facc15', '#f97316'];
    const defaults = { startVelocity: 35, spread: 360, ticks: 70, zIndex: 100050, colors };
    confetti({ ...defaults, particleCount: 80, origin: { x: 0.5, y: 0.4 } });
    setTimeout(() => confetti({ ...defaults, particleCount: 50, origin: { x: 0.2, y: 0.55 } }), 180);
    setTimeout(() => confetti({ ...defaults, particleCount: 50, origin: { x: 0.8, y: 0.55 } }), 360);
  } catch (e) { /* canvas-confetti is best-effort, never block flow */ }
};

/**
 * Plain-portal overlay used by both T3 picker and the "Tutorial completed"
 * confirmation. Replaces the previous Radix Dialog implementation because:
 *   • Radix DialogContent had z-index 50, which on /maps got stacked under
 *     other portalled overlays (the "Скоро доступно" island lock modal).
 *   • The "legendary-gradient" class used by the T3 picker had an infinite
 *     8s shimmer animation that the user perceived as a flicker.
 *   • Radix's onOpenChange + focus management created re-entrant close
 *     calls when stacked above another open Dialog.
 *
 * This version is a dumb full-screen overlay rendered into document.body
 * via createPortal, with a solid (non-animated) backdrop, z-index 100000
 * (well above sonner toasts and any in-app modal), and locks body scroll
 * while it's open.
 */
function TutorialOverlay({ open, children, testId, dismissOnBackdrop = false, onDismiss }) {
  useEffect(() => {
    if (!open) return undefined;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    // Defensive cleanup for a bug seen on mobile: leftover
    // canvas-confetti canvases (or any stray fixed-positioned
    // element) sometimes stayed in the DOM with a very high z-index
    // after a previous reward-claim animation, silently absorbing
    // taps on top of the abandon-confirm buttons. Sweep them the
    // moment this overlay opens so touches always land on our
    // buttons.
    try {
      document.querySelectorAll('canvas.confetti-canvas, canvas[data-confetti], canvas[style*="pointer-events"]').forEach((el) => {
        try { el.remove(); } catch (_) { /* noop */ }
      });
    } catch (_) { /* noop */ }
    return () => { document.body.style.overflow = prev; };
  }, [open]);

  if (!open || typeof document === 'undefined') return null;

  const handleBackdrop = (e) => {
    if (!dismissOnBackdrop) return;
    if (e.target === e.currentTarget) onDismiss?.();
  };

  return createPortal(
    <div
      data-testid={testId}
      onClick={handleBackdrop}
      style={{
        position: 'fixed',
        inset: 0,
        // High enough to clear sidebar (50), Radix Dialogs (50), sonner
        // toasts (commonly 99999) and the tutorial spotlight overlay (300).
        zIndex: 100000,
        background: 'rgba(2, 4, 12, 0.86)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '16px',
        // Stable presentation — no fade animation that could read as
        // flicker when the tutorial chain reopens this overlay back-to-back.
        backdropFilter: 'blur(2px)',
        WebkitBackdropFilter: 'blur(2px)',
        // Force pointer/touch capture on the overlay so mobile taps never
        // fall through to a stale layer underneath (bug: sometimes the
        // abandon-confirm buttons wouldn't respond to taps at all).
        pointerEvents: 'auto',
        touchAction: 'manipulation',
      }}
    >
      {children}
    </div>,
    document.body,
  );
}

/**
 * One-shot T3 reward picker, used by BOTH the tutorial-finish flow and
 * the "skip tutorial" flow.
 */
function T3RewardPicker({ value, onChange, lang, disabled }) {
  const { t } = useTranslation(lang);
  const bonus = useMemo(() => (value ? getT3BonusDescription(value, lang) : ''), [value, lang]);
  // Helper: react-i18next returns the key string when missing. Treat that as
  // empty so the OR-fallback chain can land on the hardcoded Russian copy.
  const tSafe = (key) => {
    const v = t(key, { defaultValue: '' });
    return v && v !== key ? v : '';
  };

  return (
    <div className="space-y-3">
      <Select value={value} onValueChange={onChange} disabled={disabled}>
        <SelectTrigger
          className="bg-[#0d0e1c] border-purple-500/30 text-white"
          data-testid="tutorial-t3-choice-trigger"
        >
          <SelectValue placeholder={tSafe('tutorial_t3_choose_label') || 'Выберите T3-ресурс…'} />
        </SelectTrigger>
        <SelectContent
          className="bg-[#0d0e1c] border-purple-500/30 text-white"
          style={{ zIndex: 100010 }}
        >
          {T3_REWARD_OPTIONS.map((rid) => (
            <SelectItem key={rid} value={rid} data-testid={`tutorial-t3-option-${rid}`}>
              <span className="inline-flex items-center gap-2">
                <span aria-hidden>{getT3Icon(rid)}</span>
                <span>{getResourceName(rid, lang)}</span>
              </span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {value && (
        <div
          className="rounded-xl border border-purple-400/30 bg-purple-500/10 p-3 sm:p-4 flex items-start gap-3"
          data-testid="tutorial-t3-bonus-preview"
        >
          <div className="w-9 h-9 rounded-lg bg-purple-500/20 flex items-center justify-center flex-shrink-0 text-lg" aria-hidden>
            {getT3Icon(value)}
          </div>
          <div className="min-w-0">
            <div className="text-[11px] uppercase tracking-wider text-purple-200 mb-0.5 flex items-center gap-1">
              <Sparkles className="w-3 h-3" />
              {tSafe('tutorial_t3_bonus_label') || 'Бонус'}
            </div>
            <div className="text-sm font-semibold text-white leading-tight">
              {getResourceName(value, lang)}
            </div>
            <p className="text-xs text-gray-300 mt-1 leading-snug">
              {bonus}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

export function TutorialFinishConfirm() {
  const { language } = useLanguage();
  const lang = language || 'ru';
  const navigate = useNavigate();
  const {
    showFinishConfirm, setShowFinishConfirm, finish, dismissStart, refreshStatus,
    loading, t3RewardClaimed, active,
  } = useTutorial();
  const { t } = useTranslation(lang);
  const T = (k) => getUiText(lang, k);
  const [t3Choice, setT3Choice] = useState('');
  const [submitting, setSubmitting] = useState(false);

  // Defensive backstop — never show the picker if reward was already claimed.
  useEffect(() => {
    if (showFinishConfirm && t3RewardClaimed) {
      setShowFinishConfirm(false);
    }
  }, [showFinishConfirm, t3RewardClaimed, setShowFinishConfirm]);

  const handleConfirm = async () => {
    if (submitting || loading) return;
    if (t3RewardClaimed) {
      setShowFinishConfirm(false);
      return;
    }
    if (!t3Choice) {
      const tSafe = (key) => {
        const v = t(key, { defaultValue: '' });
        return v && v !== key ? v : '';
      };
      toast.error(
        tSafe('tutorial_t3_choose_required') ||
          T('finish_confirm_choose_reward') ||
          'Выберите T3-ресурс награды'
      );
      return;
    }
    setSubmitting(true);
    const isTutorialActive = !!active;
    const choice = t3Choice;
    let res;
    try {
      if (isTutorialActive) {
        res = await finish(choice);
      } else {
        res = await dismissStart(choice);
        if (refreshStatus) await refreshStatus();
        setShowFinishConfirm(false);
      }
    } catch (e) {
      res = { ok: false, error: e?.message };
    }

    if (choice && res && res.ok !== false) {
      fireRewardConfetti();
      const resourceName = getResourceName(choice, lang) || choice;
      // NOTE: `t(key)` from react-i18next returns the key itself when the
      // key is missing — making the legacy `t(...) || T(...) || 'fallback'`
      // chain short-circuit on the (truthy) raw key. We pass an empty
      // defaultValue so missing keys become '' (falsy) and the chain falls
      // through to the hardcoded Russian copy.
      const tSafe = (key) => {
        const v = t(key, { defaultValue: '' });
        return v && v !== key ? v : '';
      };
      const toastTitle = (
        tSafe('tutorial_t3_toast_title') ||
        T('tutorial_t3_toast_title') ||
        `Награда ${resourceName} получена!`
      ).replace('{resource}', resourceName);
      const toastDesc =
        (tSafe('tutorial_t3_toast_desc') ||
          T('tutorial_t3_toast_desc') ||
          'Активируйте баф в разделе «Мои бизнесы» → клик по карточке ресурса.').replace('{resource}', resourceName);
      toast.success(toastTitle, { description: toastDesc, duration: 6000 });
      // Tutorial finished + graduation reward granted. No welcome-bonus modal
      // (the +1 TON/GRAM onboarding bonus was removed) — go straight to the map.
      setShowFinishConfirm(false);
      setTimeout(() => { try { enterRealMode('/ton-island'); } catch (e) { /* noop */ } }, 300);
    }
    if (res && res.ok === false) {
      toast.error(res?.error || 'Failed to finish tutorial');
    }
    setSubmitting(false);
  };

  if (t3RewardClaimed) return null;

  return (
    <TutorialOverlay open={showFinishConfirm} testId="tutorial-finish-confirm-modal">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="tutorial-t3-title"
        className="w-full max-w-md rounded-2xl overflow-hidden shadow-2xl"
        style={{
          background: '#14162a',
          border: '1px solid rgba(168, 85, 247, 0.55)',
          color: '#ffffff',
          boxShadow: '0 25px 60px -10px rgba(168, 85, 247, 0.45), 0 0 0 1px rgba(168, 85, 247, 0.2)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header — solid background, no shimmer. */}
        <div
          className="p-5 sm:p-6 flex items-center gap-3 sm:gap-4"
          style={{ background: 'linear-gradient(135deg, rgba(168,85,247,0.22), rgba(236,72,153,0.10))', borderBottom: '1px solid rgba(168,85,247,0.25)' }}
        >
          <div className="w-11 h-11 sm:w-12 sm:h-12 rounded-xl flex items-center justify-center flex-shrink-0" style={{ background: 'rgba(168,85,247,0.25)' }}>
            <Gift className="w-5 h-5 sm:w-6 sm:h-6 text-purple-200" />
          </div>
          <h2 id="tutorial-t3-title" className="text-base sm:text-lg font-bold leading-tight break-words">
            {t('tutorial_t3_reward_title') || 'Награда за обучение'}
          </h2>
        </div>

        <div className="p-5 sm:p-6 space-y-4">
          <p className="text-sm break-words leading-snug" style={{ color: 'rgba(255,255,255,0.78)' }}>
            {t('tutorial_t3_reward_desc') ||
              'Поздравляем! Обучение завершено. Вы получаете элитный ресурс 3-го эшелона. Выберите один из списка — он сразу попадёт в инвентарь.'}
          </p>

          <T3RewardPicker value={t3Choice} onChange={setT3Choice} lang={lang} disabled={submitting} />
        </div>

        <div className="p-4 sm:p-5 bg-black/30" style={{ borderTop: '1px solid rgba(255,255,255,0.10)' }}>
          <Button
            onClick={handleConfirm}
            disabled={loading || submitting || !t3Choice}
            className="bg-gradient-to-r from-purple-500 via-pink-500 to-cyan-400 hover:from-purple-600 hover:via-pink-600 hover:to-cyan-500 text-white font-bold w-full disabled:opacity-40 shadow-lg shadow-purple-500/40"
            data-testid="tutorial-finish-confirm-btn"
          >
            {submitting ? (T('claiming') || 'Получаем…') : (T('claim_reward') || 'Получить')}
          </Button>
        </div>
      </div>
    </TutorialOverlay>
  );
}

export function TutorialCompletedModal() {
  const { language } = useLanguage();
  const lang = language || 'ru';
  const navigate = useNavigate();
  const {
    showCompletedModal, setShowCompletedModal,
    setShowFinishConfirm, t3RewardClaimed,
    active, finish,
  } = useTutorial();
  const T = (k) => getUiText(lang, k);
  const [busy, setBusy] = useState(false);

  const t3Claimed = !!t3RewardClaimed;

  const handleClose = async () => {
    if (busy) return;
    setBusy(true);
    setShowCompletedModal(false);
    try {
      if (!t3Claimed) {
        setTimeout(() => setShowFinishConfirm(true), 220);
        return;
      }
      if (active) {
        try { await finish(null); } catch (e) { /* noop */ }
      }
      // Completed tutorial (reward already claimed in a prior run) → land on
      // the GRAM Island map in real mode.
      try { await enterRealMode('/ton-island'); } catch (e) { /* noop */ }
    } finally {
      setBusy(false);
    }
  };

  return (
    <TutorialOverlay open={showCompletedModal} testId="tutorial-completed-modal-overlay">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="tutorial-completed-title"
        data-testid="tutorial-completed-modal"
        className="w-full max-w-md rounded-2xl overflow-hidden shadow-2xl"
        style={{
          background: '#14162a',
          border: '1px solid rgba(34, 197, 94, 0.55)',
          color: '#ffffff',
          boxShadow: '0 25px 60px -10px rgba(34, 197, 94, 0.4), 0 0 0 1px rgba(34, 197, 94, 0.2)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="p-6 sm:p-8 text-center">
          <div className="w-16 h-16 sm:w-20 sm:h-20 mx-auto rounded-full flex items-center justify-center mb-4 sm:mb-6" style={{ background: 'rgba(34,197,94,0.20)' }}>
            <CheckCircle2 className="w-8 h-8 sm:w-10 sm:h-10 text-green-400" />
          </div>
          <h2 id="tutorial-completed-title" className="text-xl sm:text-2xl font-bold mb-3 break-words">
            {T('finish_done_title')}
          </h2>
          <p className="text-sm break-words" style={{ color: 'rgba(255,255,255,0.72)' }}>
            {T('finish_done_message')}
          </p>
        </div>
        <div className="p-4 sm:p-5 flex justify-center bg-black/30" style={{ borderTop: '1px solid rgba(255,255,255,0.10)' }}>
          <Button
            onClick={handleClose}
            disabled={busy}
            className="bg-green-500 text-white hover:bg-green-600 font-bold px-6 sm:px-8 w-full"
            data-testid="tutorial-completed-close-btn"
          >
            {T('got_it')}
          </Button>
        </div>
      </div>
    </TutorialOverlay>
  );
}

// Re-exportable picker so the skip-modal can use the same UX.
export { T3RewardPicker };

/**
 * "You received a bonus 1 GRAM" celebration modal. Shown right after the
 * tutorial is finished and the graduation reward is granted. The 1 GRAM
 * amount is the visual hero of the card. Closing it takes the player to
 * the GRAM Island map in real mode.
 */
export function TutorialGramBonusModal() {
  const { language } = useLanguage();
  const lang = language || 'ru';
  const { showGramBonusModal, setShowGramBonusModal } = useTutorial();
  const { t } = useTranslation(lang);
  const [busy, setBusy] = useState(false);

  const tSafe = (key) => {
    const v = t(key, { defaultValue: '' });
    return v && v !== key ? v : '';
  };

  // Fire a golden confetti burst the moment the modal appears.
  useEffect(() => {
    if (!showGramBonusModal) return;
    try {
      const colors = ['#22d3ee', '#38bdf8', '#a855f7', '#facc15', '#ffffff'];
      const defaults = { spread: 360, ticks: 90, zIndex: 100050, colors };
      confetti({ ...defaults, particleCount: 90, startVelocity: 38, origin: { x: 0.5, y: 0.35 } });
      setTimeout(() => confetti({ ...defaults, particleCount: 55, startVelocity: 30, origin: { x: 0.25, y: 0.5 } }), 200);
      setTimeout(() => confetti({ ...defaults, particleCount: 55, startVelocity: 30, origin: { x: 0.75, y: 0.5 } }), 400);
    } catch (e) { /* best-effort */ }
  }, [showGramBonusModal]);

  const handleClose = async () => {
    if (busy) return;
    setBusy(true);
    setShowGramBonusModal(false);
    try { await enterRealMode('/ton-island'); } catch (e) { /* noop */ }
    setBusy(false);
  };

  const title = tSafe('tutorial_gram_bonus_title') || 'Бонус получен!';
  const subtitle =
    tSafe('tutorial_gram_bonus_desc') ||
    'Поздравляем с завершением обучения! Мы начислили вам приветственный бонус на игровой баланс.';
  const cta = tSafe('tutorial_gram_bonus_cta') || 'Перейти на остров GRAM';

  return (
    <TutorialOverlay open={showGramBonusModal} testId="tutorial-gram-bonus-overlay">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="tutorial-gram-bonus-title"
        data-testid="tutorial-gram-bonus-modal"
        className="w-[92vw] max-w-md max-h-[90vh] overflow-y-auto rounded-3xl overflow-x-hidden shadow-2xl relative"
        style={{
          background: 'linear-gradient(160deg, #0b1830 0%, #0e1526 55%, #140f2c 100%)',
          border: '1px solid rgba(34, 211, 238, 0.45)',
          color: '#ffffff',
          boxShadow: '0 30px 70px -12px rgba(34, 211, 238, 0.45), 0 0 0 1px rgba(168,85,247,0.18)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Decorative glows */}
        <div aria-hidden style={{ position: 'absolute', top: -60, left: '50%', transform: 'translateX(-50%)', width: 220, height: 220, background: 'radial-gradient(closest-side, rgba(34,211,238,0.30), transparent 70%)', pointerEvents: 'none' }} />
        <div aria-hidden style={{ position: 'absolute', bottom: -70, right: -50, width: 180, height: 180, background: 'radial-gradient(closest-side, rgba(168,85,247,0.28), transparent 70%)', pointerEvents: 'none' }} />

        <div className="relative p-6 sm:p-8 text-center">
          {/* Gift badge */}
          <div
            className="w-16 h-16 sm:w-20 sm:h-20 mx-auto rounded-2xl flex items-center justify-center mb-4"
            style={{
              background: 'linear-gradient(135deg, rgba(34,211,238,0.28), rgba(168,85,247,0.22))',
              border: '1px solid rgba(34,211,238,0.5)',
              boxShadow: '0 10px 30px -8px rgba(34,211,238,0.6)',
            }}
          >
            <Gift className="w-8 h-8 sm:w-9 sm:h-9 text-cyan-200" />
          </div>

          <div className="text-[11px] uppercase tracking-[0.25em] text-cyan-300/80 mb-2 flex items-center justify-center gap-1.5">
            <Sparkles className="w-3.5 h-3.5" /> {tSafe('tutorial_gram_bonus_kicker') || 'Награда за обучение'}
          </div>
          <h2 id="tutorial-gram-bonus-title" className="text-xl sm:text-2xl font-bold mb-4 break-words">
            {title}
          </h2>

          {/* HERO: the 1 GRAM amount */}
          <div
            className="mx-auto mb-5 w-full rounded-2xl px-5 py-6 flex flex-col items-center justify-center"
            style={{
              background: 'linear-gradient(135deg, rgba(34,211,238,0.12), rgba(168,85,247,0.10))',
              border: '1px solid rgba(34,211,238,0.35)',
            }}
            data-testid="tutorial-gram-bonus-amount"
          >
            <div className="flex items-end justify-center gap-2 leading-none">
              <span
                className="font-extrabold tracking-tight"
                style={{
                  fontSize: 'clamp(2.75rem, 14vw, 4rem)',
                  background: 'linear-gradient(90deg, #22d3ee 0%, #38bdf8 40%, #a855f7 100%)',
                  WebkitBackgroundClip: 'text',
                  backgroundClip: 'text',
                  color: 'transparent',
                  textShadow: '0 0 40px rgba(34,211,238,0.35)',
                  filter: 'drop-shadow(0 4px 18px rgba(34,211,238,0.45))',
                }}
              >
                +1
              </span>
              <span
                className="font-extrabold pb-2"
                style={{
                  fontSize: 'clamp(1.5rem, 8vw, 2rem)',
                  background: 'linear-gradient(90deg, #38bdf8, #a855f7)',
                  WebkitBackgroundClip: 'text',
                  backgroundClip: 'text',
                  color: 'transparent',
                }}
              >
                GRAM
              </span>
            </div>
            <div className="mt-2 text-xs text-cyan-100/70">
              {tSafe('tutorial_gram_bonus_hint') || '≈ 1 TON на игровом (бонусном) балансе'}
            </div>
          </div>

          <p className="text-sm break-words leading-snug" style={{ color: 'rgba(255,255,255,0.75)' }}>
            {subtitle}
          </p>
        </div>

        <div className="relative p-4 sm:p-5 bg-black/30" style={{ borderTop: '1px solid rgba(255,255,255,0.10)' }}>
          <Button
            onClick={handleClose}
            disabled={busy}
            className="w-full font-bold text-white shadow-lg disabled:opacity-40"
            style={{
              background: 'linear-gradient(90deg, #22d3ee 0%, #38bdf8 45%, #a855f7 100%)',
              boxShadow: '0 12px 28px -8px rgba(34,211,238,0.6)',
            }}
            data-testid="tutorial-gram-bonus-close-btn"
          >
            {busy ? '…' : cta}
          </Button>
        </div>
      </div>
    </TutorialOverlay>
  );
}


/**
 * Confirmation dialog shown when the user clicks the X icon on the tutorial
 * card to bail out mid-tour. Renamed to a TutorialOverlay-based portal so
 * the same z-index (100000) treatment as the other tutorial-finish modals
 * keeps it above every island/lock modal in the app.
 *
 * On confirm: calls `/api/tutorial/abandon` (which rolls back the sandbox
 * snapshot, removes tutorial businesses + listings on the backend, marks
 * `tutorial_completed=true skipped=true`), then HARD-REDIRECTS to
 * `/ton-island`. The hard reload is intentional — it guarantees every
 * piece of in-memory tutorial state (TutorialContext, Tour overlay,
 * spotlight, seed lot caches) is dropped cleanly without us having to
 * unwire each individual subscriber.
 */
export function TutorialAbandonConfirm() {
  const { language } = useLanguage();
  const lang = language || 'ru';
  const {
    showAbandonConfirm, setShowAbandonConfirm,
    abandon, setShowCompletedModal,
  } = useTutorial();
  const T = (k) => getUiText(lang, k);
  const { t } = useTranslation(lang);
  const tSafe = (key) => {
    const v = t(key, { defaultValue: '' });
    return v && v !== key ? v : '';
  };
  const [busy, setBusy] = useState(false);

  // Guarantee `busy` is reset every time the modal (re)opens — protects
  // against a rare state race where the previous invocation set busy=true
  // but the trailing setBusy(false) didn't run before the modal was
  // dismissed, leaving the buttons stuck as `disabled` on the next open.
  useEffect(() => {
    if (showAbandonConfirm) setBusy(false);
  }, [showAbandonConfirm]);

  const onContinue = () => {
    if (busy) return;
    setShowAbandonConfirm(false);
  };

  const onConfirmEnd = async () => {
    if (busy) return;
    setBusy(true);
    try {
      // Roll back the tutorial sandbox on the backend and flip `active`→false.
      await abandon();
    } catch (e) {
      /* swallow — still surface the completion modal */
    }
    // Same UX as the start-screen "Skip" flow: close this confirm and show the
    // green "Tutorial completed" modal. From there the user can still claim the
    // one-shot T3 reward (CompletedModal → reward picker chain) or just dismiss.
    setShowAbandonConfirm(false);
    setShowCompletedModal(true);
    setBusy(false);
  };

  return (
    <TutorialOverlay
      open={showAbandonConfirm}
      testId="tutorial-abandon-confirm-overlay"
      dismissOnBackdrop={false}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="tutorial-abandon-title"
        data-testid="tutorial-abandon-confirm-modal"
        className="w-full max-w-md rounded-2xl overflow-hidden shadow-2xl relative"
        style={{
          background: 'linear-gradient(155deg, #1a1430 0%, #14162a 55%, #0e1424 100%)',
          border: '1px solid rgba(244, 114, 182, 0.45)',
          color: '#ffffff',
          boxShadow:
            '0 25px 65px -10px rgba(244, 114, 182, 0.45), 0 0 0 1px rgba(244, 114, 182, 0.18), inset 0 1px 0 rgba(255,255,255,0.05)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Decorative corner glows — pure CSS, no animation that can read
            as flicker. */}
        <div
          aria-hidden
          style={{
            position: 'absolute', top: -40, right: -40, width: 140, height: 140,
            background: 'radial-gradient(closest-side, rgba(244,114,182,0.35), transparent 70%)',
            pointerEvents: 'none',
          }}
        />
        <div
          aria-hidden
          style={{
            position: 'absolute', bottom: -40, left: -40, width: 140, height: 140,
            background: 'radial-gradient(closest-side, rgba(168,85,247,0.28), transparent 70%)',
            pointerEvents: 'none',
          }}
        />

        {/* Header */}
        <div className="relative p-6 sm:p-7 flex items-start gap-4 border-b border-white/10">
          <div
            className="w-12 h-12 sm:w-14 sm:h-14 rounded-2xl flex items-center justify-center flex-shrink-0"
            style={{
              background: 'linear-gradient(135deg, rgba(244,114,182,0.28), rgba(168,85,247,0.18))',
              border: '1px solid rgba(244,114,182,0.40)',
              boxShadow: '0 8px 20px -6px rgba(244,114,182,0.45)',
            }}
          >
            <AlertTriangle className="w-6 h-6 sm:w-7 sm:h-7 text-pink-200" />
          </div>
          <div className="min-w-0">
            <h2
              id="tutorial-abandon-title"
              className="text-lg sm:text-xl font-bold leading-tight break-words"
              style={{
                background: 'linear-gradient(90deg, #f472b6 0%, #a855f7 60%, #22d3ee 100%)',
                WebkitBackgroundClip: 'text',
                backgroundClip: 'text',
                color: 'transparent',
              }}
            >
              {tSafe('abandon_confirm_title')
                || T('abandon_confirm_title')
                || 'Завершить обучение?'}
            </h2>
            <p
              className="text-xs sm:text-sm mt-1.5 break-words leading-snug"
              style={{ color: 'rgba(255,255,255,0.72)' }}
            >
              {tSafe('abandon_confirm_message')
                || T('abandon_confirm_message')
                || 'Прогресс будет сброшен. Снова получить награду за обучение нельзя.'}
            </p>
          </div>
        </div>

        {/* Bullet list with "what happens next" */}
        <div className="relative p-5 sm:p-6 space-y-2.5">
          {[
            tSafe('abandon_bullet_progress')
              || 'Прогресс обучения и временные ресурсы будут удалены.',
            tSafe('abandon_bullet_reward')
              || 'Вы сможете получить награду за обучение (T3-ресурс) сразу после завершения.',
            tSafe('abandon_bullet_redirect')
              || 'Вы будете перенаправлены на карту GRAM Island.',
          ].map((line, i) => (
            <div key={i} className="flex items-start gap-2.5">
              <div
                className="mt-1.5 w-1.5 h-1.5 rounded-full flex-shrink-0"
                style={{ background: 'linear-gradient(135deg, #f472b6, #a855f7)' }}
              />
              <p className="text-xs sm:text-sm leading-snug" style={{ color: 'rgba(255,255,255,0.85)' }}>
                {line}
              </p>
            </div>
          ))}
        </div>

        {/* Actions */}
        <div
          className="relative p-4 sm:p-5 flex flex-col sm:flex-row items-stretch sm:items-center gap-2.5"
          style={{
            borderTop: '1px solid rgba(255,255,255,0.10)',
            background: 'rgba(0,0,0,0.30)',
            // Explicit pointer/touch enablement — safety net against the
            // "sometimes the buttons don't respond to taps" bug on mobile.
            pointerEvents: 'auto',
            touchAction: 'manipulation',
            position: 'relative',
            zIndex: 1,
          }}
        >
          <Button
            onClick={onContinue}
            disabled={busy}
            variant="outline"
            className="flex-1 border-white/15 text-white/80 hover:text-white hover:bg-white/10 disabled:opacity-40"
            data-testid="tutorial-abandon-continue-btn"
          >
            {tSafe('continue_tutorial_button')
              || T('continue_tutorial_button')
              || 'Продолжить обучение'}
          </Button>
          <Button
            onClick={onConfirmEnd}
            disabled={busy}
            className="flex-1 text-white font-bold shadow-lg disabled:opacity-40"
            style={{
              background: busy
                ? 'linear-gradient(90deg, rgba(244,114,182,0.55), rgba(168,85,247,0.55))'
                : 'linear-gradient(90deg, #f472b6 0%, #a855f7 100%)',
              boxShadow: '0 10px 25px -8px rgba(244,114,182,0.55)',
            }}
            data-testid="tutorial-abandon-confirm-btn"
          >
            {busy
              ? (tSafe('finishing') || 'Завершаем…')
              : (tSafe('finish_button') || T('finish_button') || 'Завершить обучение')}
          </Button>
        </div>
      </div>
    </TutorialOverlay>
  );
}

export default { TutorialFinishConfirm, TutorialCompletedModal, TutorialAbandonConfirm, TutorialGramBonusModal };
