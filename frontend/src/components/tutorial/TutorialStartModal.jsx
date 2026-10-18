import React, { useCallback, useRef } from 'react';
import { useLanguage } from '@/context/LanguageContext';
import { useTutorial } from '@/context/TutorialContext';
import { getUiText } from '@/lib/tutorialTranslations';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { VisuallyHidden } from '@radix-ui/react-visually-hidden';
import { GraduationCap, Play } from 'lucide-react';

// Style applied to both buttons in the start modal. `touchAction:'manipulation'`
// disables iOS/Chrome's 300ms double-tap-zoom delay and prevents the browser
// from hijacking the first tap on the button. `WebkitTapHighlightColor` +
// `userSelect` clean up the visual feedback so the button feels native.
const TOUCH_SAFE_STYLE = {
  touchAction: 'manipulation',
  WebkitTapHighlightColor: 'transparent',
  userSelect: 'none',
};

export default function TutorialStartModal() {
  const { language } = useLanguage();
  const lang = language || 'ru';
  const {
    showStartModal, setShowStartModal,
    start, dismissStart,
    setShowCompletedModal,
    loading,
  } = useTutorial();
  const T = (k) => getUiText(lang, k);

  // Guard against a single tap firing both `onPointerUp` (our mobile
  // fallback) and the synthetic `click` — that would call `start` twice
  // and race the second call against `loading:true`. The ref resets after
  // a short window so subsequent legitimate re-taps still work.
  const firedRef = useRef(false);
  const fireOnce = useCallback((fn) => (e) => {
    if (firedRef.current) return;
    firedRef.current = true;
    // Reset the guard on the next tick — long enough to swallow the
    // paired pointerup+click that mobile browsers may emit, short enough
    // that the button becomes tappable again if the async op resolves fast.
    setTimeout(() => { firedRef.current = false; }, 600);
    try { fn(e); } catch (_) { firedRef.current = false; }
  }, []);

  // v2.2: clicking "Пропустить" closes the start modal and opens the same
  // "Tutorial completed" modal that shows after a normal finish. From there
  // the user can claim the T3 reward (via TutorialCompletedModal → reward
  // picker chain) or just dismiss it. No inline reward picker on this modal.
  const onSkipClick = useCallback(async () => {
    try { await dismissStart(null); } catch (e) { /* noop */ }
    setShowStartModal(false);
    setShowCompletedModal(true);
  }, [dismissStart, setShowStartModal, setShowCompletedModal]);

  const handleStart = useCallback(() => { start(); }, [start]);
  const handleSkip = useCallback(() => { onSkipClick(); }, [onSkipClick]);

  return (
    <Dialog open={showStartModal}>
      <DialogContent
        className="bg-[#14162a] border border-cyber-cyan/30 text-white p-0 overflow-hidden w-[94vw] sm:w-[520px] max-w-[520px] max-h-[92vh] overflow-y-auto !rounded-2xl z-[81]"
        overlayClassName="z-[80]"
        data-testid="tutorial-start-modal"
        hideCloseButton
        onPointerDownOutside={(e) => e.preventDefault()}
        onInteractOutside={(e) => e.preventDefault()}
        onEscapeKeyDown={(e) => e.preventDefault()}
      >
        <VisuallyHidden asChild><DialogTitle>{T('start_title')}</DialogTitle></VisuallyHidden>
        <VisuallyHidden asChild><DialogDescription>{T('start_message')}</DialogDescription></VisuallyHidden>

        {/* Header */}
        <div className="bg-gradient-to-br from-cyber-cyan/15 to-purple-500/10 p-4 sm:p-5 border-b border-cyber-cyan/20 flex items-start gap-3 sm:gap-4">
          <div className="w-11 h-11 sm:w-12 sm:h-12 rounded-2xl bg-cyber-cyan/20 flex items-center justify-center flex-shrink-0">
            <GraduationCap className="w-6 h-6 text-cyber-cyan" />
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="text-base sm:text-xl font-bold leading-tight break-words hyphens-auto" style={{ wordBreak: 'break-word' }}>
              {T('start_title')}
            </h2>
            <p className="text-[11px] sm:text-xs text-text-muted mt-1">Interactive sandbox • 15 steps</p>
          </div>
        </div>

        {/* Body */}
        <div className="p-4 sm:p-5 space-y-3 sm:space-y-4">
          <p className="text-xs sm:text-sm text-text-muted leading-relaxed break-words" style={{ wordBreak: 'break-word' }}>
            {T('start_message')}
          </p>
          <div className="grid grid-cols-3 gap-2 text-[10px] sm:text-[11px] text-text-muted">
            <div className="p-2 rounded-lg bg-white/5 border border-white/10 text-center">
              <div className="text-cyber-cyan font-bold text-sm sm:text-base">15</div>
              <div className="leading-tight">steps</div>
            </div>
            <div className="p-2 rounded-lg bg-white/5 border border-white/10 text-center">
              <div className="text-cyber-cyan font-bold text-sm sm:text-base">~5</div>
              <div className="leading-tight">min</div>
            </div>
            <div className="p-2 rounded-lg bg-white/5 border border-white/10 text-center">
              <div className="text-cyber-cyan font-bold text-sm sm:text-base">100%</div>
              <div className="leading-tight">reversible</div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="p-3 sm:p-4 border-t border-white/10 flex flex-col sm:flex-row items-stretch sm:items-center justify-end gap-2 bg-void/40">
          <Button
            type="button"
            onClick={fireOnce(handleStart)}
            onPointerUp={fireOnce(handleStart)}
            disabled={loading}
            style={TOUCH_SAFE_STYLE}
            className="bg-cyber-cyan text-black hover:bg-cyber-cyan/80 font-bold w-full sm:w-auto whitespace-normal break-words h-auto min-h-[40px] px-3 py-2"
            data-testid="tutorial-start-btn"
          >
            <Play className="w-4 h-4 mr-2 flex-shrink-0" />
            <span className="break-words">{T('start_button')}</span>
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
