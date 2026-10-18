import React, { useEffect, useState, useRef, useCallback } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useLanguage } from '@/context/LanguageContext';
import { useTutorial } from '@/context/TutorialContext';
import { getUiText, getStepText } from '@/lib/tutorialTranslations';
import { Button } from '@/components/ui/button';
import {
  ChevronRight, MapPin, Target, SkipForward,
  Minus, Maximize2,
} from 'lucide-react';

/**
 * TutorialTour
 * ------------
 * - Blocks clicks on page except the spotlighted target (unless the step sets
 *   `allow_interaction`, then clicks pass through freely for user to use the
 *   real UI).
 * - Tracks the pathname at step-activation so auto-advance on `page_visit`
 *   fires only when the user actually navigates to the target route (prevents
 *   instant auto-skip of step 2 when the user is already on the home page).
 * - Shows a brief "step complete" transition between steps.
 * - Finish step primary button opens the T3 reward picker (`finish` runs
 *   inside the picker with the chosen resource). If the user has already
 *   claimed the one-shot reward, the picker is skipped and `finish()` is
 *   called silently.
 * - On mobile for `allow_interaction` steps the card is placed at the TOP
 *   of the screen (not bottom) and can be minimized so it never covers the
 *   element the user needs to click.
 */
export default function TutorialTour() {
  const { language } = useLanguage();
  const lang = language || 'ru';
  const {
    active, currentStep, currentStepId,
    advance, skip, fakeGrantResource,
    showFinishConfirm, setShowFinishConfirm,
    showCompletedModal, setShowCompletedModal,
    setShowAbandonConfirm,
    refreshStatus,
  } = useTutorial();
  const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

  const location = useLocation();
  const navigate = useNavigate();
  const [rect, setRect] = useState(null);
  const [viewport, setViewport] = useState({
    width: typeof window !== 'undefined' ? window.innerWidth : 1200,
    height: typeof window !== 'undefined' ? window.innerHeight : 800,
  });
  const rafRef = useRef(null);

  // --- Fade transition between steps ---
  // Soft cross-fade: card never fully disappears (min opacity 0.35) and the
  // breathing pause is short so the user does NOT feel a sudden "jump".
  // 1) Old card fades to ~0.35 opacity (200ms)
  // 2) Brief breathing pause (350ms) — keeps the dim card visible while the
  //    spotlight settles on the next target.
  // 3) Card fades back to full opacity (250ms) with the new step content.
  // Finish step keeps the longer ceremonial pause.
  const [cardPhase, setCardPhase] = useState('idle'); // 'idle' | 'fading-out' | 'breathing' | 'fading-in'
  const prevStepIdRef = useRef(currentStepId);
  useEffect(() => {
    if (prevStepIdRef.current && currentStepId && prevStepIdRef.current !== currentStepId) {
      const isFinal = currentStepId === 'finish';
      const breathDelay = isFinal ? 1400 : 350;
      setCardPhase('fading-out');
      const t1 = setTimeout(() => setCardPhase('breathing'), 200);
      const t2 = setTimeout(() => setCardPhase('fading-in'), 200 + breathDelay);
      const t3 = setTimeout(() => setCardPhase('idle'), 200 + breathDelay + 250);
      prevStepIdRef.current = currentStepId;
      return () => {
        clearTimeout(t1); clearTimeout(t2); clearTimeout(t3);
      };
    }
    prevStepIdRef.current = currentStepId;
  }, [currentStepId]);

  // --- Minimized state on mobile (for steps where the card could overlap the UI) ---
  // Только мобильное поведение — на десктопе карточка никогда не сворачивается,
  // вместо этого она кратко прячется через `cardPhase` (fade-out → breath → fade-in)
  // когда пользователь "достиг" целевой страницы или кликнул по подсветке.
  const [minimized, setMinimized] = useState(false);
  useEffect(() => { setMinimized(false); }, [currentStepId]);

  // --- Pathname snapshot when step activates (prevents instant page_visit auto-advance) ---
  const stepStartPathRef = useRef(location.pathname);
  useEffect(() => {
    stepStartPathRef.current = location.pathname;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentStepId]);

  const T = (k) => getUiText(lang, k);
  const ST = (k) => getStepText(lang, currentStepId, k);

  const isMobile = viewport.width < 640;

  useEffect(() => {
    const onResize = () => setViewport({ width: window.innerWidth, height: window.innerHeight });
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  // NO auto-advance on page_visit anymore.
  // When the user arrives on the target route (pathname changes to match),
  // we briefly hide the spotlight + tutorial card, let the user see the
  // page they just opened for ~1.5s, then fade the card back in with the
  // page description and a "Got it" button. They click it to advance.
  const [targetReached, setTargetReached] = useState(false);
  useEffect(() => {
    setTargetReached(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentStepId]);
  useEffect(() => {
    if (!active || !currentStep) return;
    if (currentStep.gate !== 'page_visit') return;
    const target = currentStep.target_route;
    if (!target) return;
    const matches = (p) => p === target
      || (target === '/island' && ['/ton-island', '/island', '/map', '/game'].includes(p));
    if (!matches(location.pathname)) return;
    // For auto-advance steps we accept ANY arrival (even if the user is
    // already on the target page when the step activates) — the step's only
    // job is to chain navigation, no UI to show.
    if (!currentStep.auto_advance_on_arrival && matches(stepStartPathRef.current)) return;
    setTargetReached(true);
    // Auto-advance immediately if step has the flag (used to chain
    // navigation steps without an intermediate "Got it" click).
    if (currentStep.auto_advance_on_arrival) {
      // small delay so the URL change settles in router state before advance
      setTimeout(() => { advance(currentStepId); }, 50);
      return;
    }
    // Не сворачиваем карточку даже на мобиле: после короткой паузы
    // (`cardPhase` цикл fade-out → breath → fade-in) описание шага должно
    // быть полностью открыто, чтобы пользователь сразу видел контекст
    // страницы (особенно важно на карте).
    setMinimized(false);
  }, [location.pathname, active, currentStep, isMobile]);

  // Также: когда пользователь кликает прямо по подсвеченному target-элементу
  // (page_visit-шаг, где целевой роут совпадает с текущим — например, клик
  // по "GRAM CITY" на главной), прячем рамку + карточку, делаем "вдох" и
  // показываем карточку снова с описанием и кнопкой "Далее". Так шаг не
  // залипает: сначала пользователь видит чистую страницу, затем подсказку.
  useEffect(() => {
    if (!active || !currentStep || !rect) return;
    if (currentStep.gate !== 'page_visit') return;
    const onDocClick = (e) => {
      const x = e.clientX, y = e.clientY;
      if (x >= rect.left && x <= rect.left + rect.width
          && y >= rect.top && y <= rect.top + rect.height) {
        setTargetReached(true);
        setMinimized(false);
      }
    };
    document.addEventListener('mousedown', onDocClick, true);
    document.addEventListener('touchstart', onDocClick, true);
    return () => {
      document.removeEventListener('mousedown', onDocClick, true);
      document.removeEventListener('touchstart', onDocClick, true);
    };
  }, [active, currentStep, rect, isMobile]);

  // Re-run the fade-out → breath → fade-in cycle when the user "reaches" the
  // target — so even on PC (where we never minimize) the card disappears for
  // ~1.5s, the user sees the page, then the description+Next-button card
  // gracefully fades back in.
  useEffect(() => {
    if (!targetReached) return;
    setCardPhase('fading-out');
    const t1 = setTimeout(() => setCardPhase('breathing'), 200);
    const t2 = setTimeout(() => setCardPhase('fading-in'), 200 + 350);
    const t3 = setTimeout(() => setCardPhase('idle'), 200 + 350 + 250);
    return () => {
      clearTimeout(t1); clearTimeout(t2); clearTimeout(t3);
    };
  }, [targetReached]);

  // `go_businesses_check`: as soon as the user navigates to /my-businesses,
  // auto-advance to `explain_t3_buff` — we don't want to show an intermediate
  // "you arrived, click Got it" prompt. The next step has its own description.
  useEffect(() => {
    if (!active) return;
    if (currentStepId !== 'go_businesses_check') return;
    if (!targetReached) return;
    const t = setTimeout(() => advance('go_businesses_check'), 600);
    return () => clearTimeout(t);
  }, [active, currentStepId, targetReached, advance]);

  // Auto-scroll the target into view on step activation — so when the step
  // points at a sidebar nav item or a resource card deep on the page, the
  // user can always see it without manually scrolling.
  useEffect(() => {
    if (!active || !currentStep) return;
    const sel = (isMobile && currentStep.mobile_target_selector)
      ? currentStep.mobile_target_selector
      : currentStep.target_selector;
    if (!sel) return;
    const t = setTimeout(() => {
      const el = document.querySelector(`[data-testid="${sel}"]`);
      if (el && typeof el.scrollIntoView === 'function') {
        try { el.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch (e) { /* noop */ }
      }
    }, 350);
    return () => clearTimeout(t);
  }, [active, currentStepId, currentStep, isMobile]);

  const computeRect = useCallback(() => {
    if (!active || !currentStep) { setRect(null); return; }
    // For create_lot we may override the target selector dynamically based on
    // the Sell modal sub-state — pick whichever effective id is live.
    // Detection is DOM-based (presence of conditionally rendered nodes) — far
    // more reliable than scraping `textContent` of a Radix Select trigger.
    const overrideSel = (() => {
      if (currentStep.id === 'create_lot') {
        const modalOpen = !!document.querySelector('[data-testid="sell-resource-modal"]');
        if (!modalOpen) return null;
        const ai = document.querySelector('[data-testid="sell-amount-input"]');
        const pi = document.querySelector('[data-testid="sell-price-input"]');
        const picked = !!ai;
        if (!picked) {
          // If the resource dropdown is open, point spotlight at the Neuro-Core
          // option specifically so the user knows which one to pick.
          const lb = document.querySelector('[role="listbox"]');
          if (lb && document.querySelector('[data-testid="sell-resource-option-neuro_core"]')) {
            return 'sell-resource-option-neuro_core';
          }
          return 'sell-resource-select-trigger';
        }
        const hasAmount = ai && ai.value && parseInt(ai.value, 10) > 0;
        const hasPrice  = pi && pi.value && parseFloat(pi.value) > 0;
        if (!hasAmount) return 'sell-amount-wrap';
        if (!hasPrice)  return 'sell-price-wrap';
        return 'sell-confirm-btn';
      }
      if (currentStep.id === 'buy_lot') {
        const modal = document.querySelector('[data-testid="buy-resource-modal"]');
        if (!modal) return null; // no override — spotlight stays on lot card
        const input = modal.querySelector('input[type="number"]');
        const cur = input ? parseInt(input.value || '0', 10) : 0;
        return cur > 1 ? 'tutorial-buy-confirm-btn' : 'tutorial-buy-all-btn';
      }
      if (currentStep.id === 'explain_t3_buff') {
        const buffModal = document.querySelector('[data-testid="resource-buff-modal"]');
        if (buffModal) return 'resource-buff-modal';
        return null; // default → resource-card-neuro_core
      }
      return null;
    })();
    const sel = overrideSel || ((isMobile && currentStep.mobile_target_selector)
      ? currentStep.mobile_target_selector
      : currentStep.target_selector);
    if (!sel) { setRect(null); return; }
    const el = document.querySelector(`[data-testid="${sel}"]`);
    if (!el) { setRect(null); return; }
    const r = el.getBoundingClientRect();
    // Spotlight = target box + 8px padding, then shrunk ~15% by area
    // (≈0.922 per side, kept centered) per UX request — a slightly tighter
    // highlight around the button.
    const bx = r.left - 8, by = r.top - 8, bw = r.width + 16, bh = r.height + 16;
    const s = 0.922;
    const nw = bw * s, nh = bh * s;
    setRect({ top: by + (bh - nh) / 2, left: bx + (bw - nw) / 2, width: nw, height: nh });
  }, [active, currentStep, isMobile]);

  useEffect(() => {
    if (!active) { setRect(null); return; }
    computeRect();
    const onResize = () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(computeRect);
    };
    window.addEventListener('resize', onResize);
    window.addEventListener('scroll', onResize, true);
    const poll = setInterval(computeRect, 120);
    // For create_lot/buy_lot we keep polling alive throughout the whole step —
    // the spotlight target moves dynamically as the user fills the modal.
    const stop = (currentStepId === 'create_lot' || currentStepId === 'buy_lot' || currentStepId === 'explain_t3_buff')
      ? null
      : setTimeout(() => clearInterval(poll), 8000);
    return () => {
      window.removeEventListener('resize', onResize);
      window.removeEventListener('scroll', onResize, true);
      clearInterval(poll);
      if (stop) clearTimeout(stop);
    };
  }, [active, currentStepId, computeRect]);

  // --- create_lot: multi-step spotlight inside the Sell Resource modal ---
  // As the user fills the form, the highlighted element changes:
  //   1) «Sell Resource» button (before modal opens)
  //   2) Resource dropdown trigger (modal open, no resource yet)
  //   3) Amount input (resource picked, amount empty)
  //   4) Price input (amount filled, price empty)
  //   5) «List» button (everything filled)
  // Detection is DOM-based (presence of conditionally rendered inputs).
  const [createLotFormHint, setCreateLotFormHint] = useState(null);
  useEffect(() => {
    if (!active || currentStepId !== 'create_lot') { setCreateLotFormHint(null); return; }
    const tick = () => {
      const modalOpen = !!document.querySelector('[data-testid="sell-resource-modal"]');
      if (!modalOpen) { setCreateLotFormHint(null); return; }
      const amountInput = document.querySelector('[data-testid="sell-amount-input"]');
      const priceInput  = document.querySelector('[data-testid="sell-price-input"]');
      const pickedResource = !!amountInput;          // amount input is rendered only after picking
      const hasAmount = amountInput && amountInput.value && parseInt(amountInput.value, 10) > 0;
      const hasPrice  = priceInput  && priceInput.value  && parseFloat(priceInput.value) > 0;
      if (!pickedResource) setCreateLotFormHint('resource');
      else if (!hasAmount) setCreateLotFormHint('amount');
      else if (!hasPrice)  setCreateLotFormHint('price');
      else setCreateLotFormHint('confirm');
    };
    tick();
    const id = setInterval(tick, 120);
    return () => clearInterval(id);
  }, [active, currentStepId]);

  // --- Detect Buff modal open for `explain_t3_buff` step ---
  //   Phase A: modal closed                           → spotlight resource-card-neuro_core
  //   Phase B: modal opened (resource-buff-modal)     → spotlight the modal, show phase2 text
  //   Phase C: modal closed AFTER having been opened  → auto-advance the step
  const [t3BuffModalOpen, setT3BuffModalOpen] = useState(false);
  const t3BuffWasOpenRef = useRef(false);
  const t3BuffPrevOpenRef = useRef(false);
  useEffect(() => {
    if (!active || currentStepId !== 'explain_t3_buff') {
      setT3BuffModalOpen(false);
      t3BuffWasOpenRef.current = false;
      t3BuffPrevOpenRef.current = false;
      return;
    }
    const tick = () => {
      const open = !!document.querySelector('[data-testid="resource-buff-modal"]');
      if (open) t3BuffWasOpenRef.current = true;
      // Modal CLOSED after being open → auto-advance
      if (!open && t3BuffPrevOpenRef.current && t3BuffWasOpenRef.current) {
        // Reset the latch so we don't advance twice
        t3BuffWasOpenRef.current = false;
        setTimeout(() => advance('explain_t3_buff'), 250);
      }
      t3BuffPrevOpenRef.current = open;
      setT3BuffModalOpen(open);
    };
    tick();
    const id = setInterval(tick, 150);
    return () => clearInterval(id);
  }, [active, currentStepId, advance]);

  // --- Detect Buy modal open for `buy_lot` step + multi-step spotlight ---
  //   1) lot card  (modal NOT open)            → tutorial-buy-bot-lot-btn
  //   2) «Всё» button (modal open, amount ≤ 1) → tutorial-buy-all-btn
  //   3) «Купить» button (amount > 1)          → tutorial-buy-confirm-btn
  // Declared BEFORE effectiveTargetSelector/createLotInstructionOverride below
  // because those consts reference buyLotFormHint during the render pass.
  const [buyModalOpen, setBuyModalOpen] = useState(false);
  const [buyLotFormHint, setBuyLotFormHint] = useState(null);
  useEffect(() => {
    if (!active || currentStepId !== 'buy_lot') {
      setBuyModalOpen(false);
      setBuyLotFormHint(null);
      return;
    }
    const tick = () => {
      let open = !!document.querySelector('[data-testid="buy-resource-modal"]');
      if (!open) {
        const dlgs = document.querySelectorAll('[role="dialog"]');
        for (const d of dlgs) {
          const t = (d.textContent || '').toLowerCase();
          if (t.includes('купить ресурс') || t.includes('buy resource') || t.includes('comprar recurso') || t.includes('购买资源')) { open = true; break; }
        }
      }
      setBuyModalOpen(open);
      if (!open) { setBuyLotFormHint(null); return; }
      const modal = document.querySelector('[data-testid="buy-resource-modal"]');
      const input = modal?.querySelector('input[type="number"]');
      const cur = input ? parseInt(input.value || '0', 10) : 0;
      setBuyLotFormHint(cur > 1 ? 'confirm' : 'amount');
    };
    tick();
    const id = setInterval(tick, 200);
    return () => clearInterval(id);
  }, [active, currentStepId]);

  // Override target selector for create_lot based on the current sub-step
  const effectiveTargetSelector = (() => {
    // explain_t3_buff: when buff modal is open, spotlight the modal
    if (currentStepId === 'explain_t3_buff' && t3BuffModalOpen) return 'resource-buff-modal';
    // buy_lot: modal-driven multi-step spotlight
    if (currentStepId === 'buy_lot' && buyLotFormHint === 'amount') return 'tutorial-buy-all-btn';
    if (currentStepId === 'buy_lot' && buyLotFormHint === 'confirm') return 'tutorial-buy-confirm-btn';
    if (currentStepId !== 'create_lot' || !createLotFormHint) {
      return (isMobile && currentStep?.mobile_target_selector)
        ? currentStep?.mobile_target_selector
        : currentStep?.target_selector;
    }
    if (createLotFormHint === 'resource') {
      // If listbox is open, highlight the Neuro-Core option directly.
      if (typeof document !== 'undefined') {
        const lb = document.querySelector('[role="listbox"]');
        if (lb && document.querySelector('[data-testid="sell-resource-option-neuro_core"]')) {
          return 'sell-resource-option-neuro_core';
        }
      }
      return 'sell-resource-select-trigger';
    }
    if (createLotFormHint === 'amount') return 'sell-amount-wrap';
    if (createLotFormHint === 'price') return 'sell-price-wrap';
    if (createLotFormHint === 'confirm') return 'sell-confirm-btn';
    return currentStep?.target_selector;
  })();

  const createLotInstructionOverride = (() => {
    if (currentStepId !== 'create_lot' || !createLotFormHint) return null;
    if (createLotFormHint === 'resource') return ST('hint_resource');
    if (createLotFormHint === 'amount') return ST('hint_amount');
    if (createLotFormHint === 'price') return ST('hint_price');
    if (createLotFormHint === 'confirm') return ST('hint_confirm');
    return null;
  })();

  const buyLotInstructionOverride = (() => {
    if (currentStepId !== 'buy_lot' || !buyLotFormHint) return null;
    if (buyLotFormHint === 'amount')  return ST('hint_buy_all');
    if (buyLotFormHint === 'confirm') return ST('hint_buy_confirm');
    return null;
  })();

  // Recompute spotlight rect immediately when the create_lot/buy_lot/explain_t3_buff sub-step
  // changes (modal opens, resource picked, amount filled, price filled).
  useEffect(() => {
    if (active && (currentStepId === 'create_lot' || currentStepId === 'buy_lot' || currentStepId === 'explain_t3_buff')) {
      computeRect();
    }
  }, [createLotFormHint, buyLotFormHint, buyModalOpen, t3BuffModalOpen, active, currentStepId, computeRect]);

  // --- Detect an open Radix Select listbox while a modal-step is active ---
  // Polled so the SVG cutout overlay re-renders with an extra hole over the
  // dropdown options, letting users actually click them. Placed BEFORE any
  // early return below so React Hooks order stays consistent across renders.
  // eslint-disable-next-line no-unused-vars
  const [listboxOpen, setListboxOpen] = useState(false);
  useEffect(() => {
    if (!active) { setListboxOpen(false); return; }
    if (currentStepId !== 'create_lot' && currentStepId !== 'buy_lot') {
      setListboxOpen(false); return;
    }
    const tick = () => {
      setListboxOpen(!!document.querySelector('[role="listbox"]'));
    };
    tick();
    const id = setInterval(tick, 120);
    return () => clearInterval(id);
  }, [active, currentStepId]);

  // Auto-advance go_trading_buy as soon as the user navigates to /trading
  // (no extra "arrived" description card — go straight to the next step).
  useEffect(() => {
    if (!targetReached) return;
    if (currentStepId !== 'go_trading_buy') return;
    const t = setTimeout(() => { advance(currentStepId); }, 600);
    return () => clearTimeout(t);
  }, [targetReached, currentStepId, advance]);

  if (!active || !currentStep) return null;
  if (showFinishConfirm || showCompletedModal) return null;

  const stepIndex = (currentStep.index || 0) + 1;
  const totalSteps = 15;
  const isClientAck = currentStep.gate === 'client_ack';
  const isOptional = currentStep.optional;
  const isServerAction = currentStep.gate === 'server_action';
  const isDbCheck = currentStep.gate === 'db_check';
  const targetRoute = currentStep.target_route;
  const isOnTargetRoute = !targetRoute || location.pathname === targetRoute
    || (targetRoute === '/island' && ['/ton-island', '/island', '/map', '/game'].includes(location.pathname));

  const isFinalStep = currentStepId === 'finish';

  const onClickPrimary = async () => {
    // v2.2.X: the FINAL step now opens the green "Tutorial completed" modal
    // FIRST (so the user sees confirmation that they finished), and the T3
    // reward picker is chained from inside it (only when the one-shot reward
    // hasn't been claimed yet). This fixes:
    //   - "награда показывается раньше финального сообщения" (UX bug #3)
    //   - "после получения ресурса снова показывает уже получал" (UX bug #2)
    //     — because if `t3RewardClaimed` is true the CompletedModal will NOT
    //     reopen the picker.
    //   - "вечное мигание модалки получения T3" (UX bug #1) — closing the
    //     picker no longer reopens CompletedModal in a loop.
    if (isFinalStep) {
      setShowCompletedModal(true);
      return;
    }
    if (currentStepId === 'fake_add_resources') {
      await fakeGrantResource({ resource_type: 'neuro_core', amount: 10 });
      return;
    }
    // Navigate to target route ONLY on page_visit steps — client_ack steps
    // just advance (e.g. go_credit highlights a button but we don't actually
    // want the user to leave the current page).
    if (currentStep?.gate === 'page_visit' && !isOnTargetRoute && targetRoute) {
      navigate(targetRoute);
      return;
    }
    // Otherwise — client_ack, or page_visit with user already on target —
    // just advance the tutorial.
    await advance(currentStepId);
  };

  const primaryLabel = () => {
    if (isFinalStep) return T('finish_button');
    if (currentStepId === 'fake_add_resources') return T('i_understand');
    if (isClientAck) return T('next_button');
    if (!isOnTargetRoute && targetRoute) return T('back_to_route');
    return T('got_it');
  };

  const primaryDisabled = (isDbCheck && currentStepId === 'create_lot')
    || (isServerAction && currentStepId === 'fake_buy_plot')
    // For buy_lot — Далее always disabled. Step auto-advances via
    // server_action when the actual purchase succeeds.
    || (isServerAction && currentStepId === 'buy_lot');

  // Hide the "Next" primary button for steps that require the user to
  // interact with a highlighted UI element themselves (no shortcut via the
  // tutorial card). Per UX request, no Next button on these steps:
  //   - fake_buy_plot   (must click the pulsating HELIOS cell)
  //   - buy_lot         (must click the bot lot and confirm)
  //   - create_lot      (must list the resource via the sell modal)
  //   - go_trading_my   (must switch to the «My» tab in Trading)
  //   - observe_listing (must look at the «My» tab)
  //   - explain_t3_buff (advances by clicking the Neuro Core card)
  const hidePrimary = (!isFinalStep
    && currentStep?.gate === 'page_visit'
    && !!targetRoute
    && !isOnTargetRoute)
    || currentStepId === 'explain_t3_buff'
    || currentStepId === 'fake_buy_plot'
    || currentStepId === 'buy_lot'
    || currentStepId === 'create_lot'
    || currentStepId === 'go_trading_my';

  // Hide the bottom "Завершить обучение" / "Skip tutorial" button on
  // explain_t3_buff per UX request — flow advances purely by interaction.
  // Bottom "skip tutorial" button removed per design — closing the tutorial
  // is still available via the X icon in the header. `hideBottomFinishBtn`
  // is no longer used but kept around as a marker for future reintroduction.

  const allowInteraction = !!currentStep?.allow_interaction;
  // BEFORE the relevant Sell/Buy modal is open, we override allow_interaction:
  // we want a cutout backdrop locking the user onto the highlighted button so
  // they can't roam the sidebar / navigate away. Once the modal opens, the
  // dynamic spotlight inside the form takes over, but we STILL block clicks
  // outside the modal — see `isModalOpenStep` rendering below.
  const isModalOpenStep = (currentStepId === 'create_lot' && !!createLotFormHint)
                       || (currentStepId === 'buy_lot' && buyModalOpen)
                       || (currentStepId === 'explain_t3_buff');
  const effectiveAllowInteraction = allowInteraction
    && !(currentStepId === 'create_lot' && !createLotFormHint)
    && !(currentStepId === 'buy_lot' && !buyModalOpen)
    && !(currentStepId === 'explain_t3_buff');
  const blockTargetClicks = currentStep?.block_target_clicks === true;

  // --- Click-blocking overlay ---
  const BACKDROP_COLOR = 'rgba(5, 8, 20, 0.55)';
  const BACKDROP_Z = 55;
  const SPOT_RING_Z = 60;
  // Card z-index: bumped to 300 so it stays above the modal-step SVG cutout
  // overlay (z-200) and its spotlight ring (z-210) — users must always be able
  // to click tutorial controls even when the Sell/Buy modal is open.
  const CARD_Z = 300;

  const renderOverlay = () => {
    // After the user reached the target page on a page_visit step — hide
    // the whole overlay so the user can browse the page freely.
    if (targetReached) return null;

    // SPECIAL CASE: a Sell/Buy modal is open during the tutorial. Render a
    // cutout backdrop ABOVE the Dialog (z-200) with a hole only for the
    // current spotlight target. If a Radix Select listbox is also open,
    // we expand the hole to the BOUNDING RECT of (target + listbox) so the
    // dropdown options stay clickable too.
    if (isModalOpenStep) {
      if (!rect) {
        // No target yet — full-screen blocker (no holes) so the user can't
        // accidentally click anything outside the tutorial card.
        return (
          <div
            style={{
              position: 'fixed', inset: 0, background: BACKDROP_COLOR,
              zIndex: 200, pointerEvents: 'auto',
            }}
            data-testid="tutorial-backdrop-modal"
            onClick={(e) => e.stopPropagation()}
          />
        );
      }
      // Compute hole.
      // Default: hole = target rect.
      // When a Radix Select listbox is open during the tutorial, we want to
      // restrict interaction to ONLY the listbox + the tutorial card. So we
      // collapse the hole to the listbox rect alone (ignoring the trigger /
      // anything else around it).
      let holeLeft = rect.left, holeTop = rect.top;
      let holeRight = rect.left + rect.width, holeBottom = rect.top + rect.height;
      if (listboxOpen && typeof document !== 'undefined') {
        const lb = document.querySelector('[role="listbox"]');
        if (lb) {
          const lr = lb.getBoundingClientRect();
          if (lr.width > 0 && lr.height > 0) {
            holeLeft   = lr.left - 4;
            holeTop    = lr.top - 4;
            holeRight  = lr.left + lr.width + 4;
            holeBottom = lr.top + lr.height + 4;
          }
        }
      }
      // explain_t3_buff: when the buff modal is open, expand hole to the
      // FULL Radix Dialog content so the user can read & close it.
      if (currentStepId === 'explain_t3_buff' && t3BuffModalOpen && typeof document !== 'undefined') {
        const dlg = document.querySelector('[data-testid="resource-buff-modal"]')
                 || document.querySelector('[role="dialog"]');
        if (dlg) {
          const dr = dlg.getBoundingClientRect();
          if (dr.width > 0 && dr.height > 0) {
            holeLeft   = dr.left - 4;
            holeTop    = dr.top - 4;
            holeRight  = dr.left + dr.width + 4;
            holeBottom = dr.top + dr.height + 4;
          }
        }
      }
      const holeW = Math.max(0, holeRight - holeLeft);
      const holeH = Math.max(0, holeBottom - holeTop);
      const p = {
        position: 'fixed', background: BACKDROP_COLOR,
        zIndex: 200, pointerEvents: 'auto',
      };
      return (
        <>
          {/* 4 strips that together form a backdrop with a hole. Clicks on
              dark strips are swallowed (stopPropagation); clicks inside the
              hole pass through to the modal element underneath. */}
          <div style={{ ...p, top: 0, left: 0, right: 0, height: Math.max(0, holeTop) }}                onClick={(e) => e.stopPropagation()} data-testid="tutorial-backdrop-top" />
          <div style={{ ...p, top: holeTop + holeH, left: 0, right: 0, bottom: 0 }}                  onClick={(e) => e.stopPropagation()} data-testid="tutorial-backdrop-bottom" />
          <div style={{ ...p, top: holeTop, left: 0, width: Math.max(0, holeLeft), height: holeH }}  onClick={(e) => e.stopPropagation()} data-testid="tutorial-backdrop-left" />
          <div style={{ ...p, top: holeTop, left: holeLeft + holeW, right: 0, height: holeH }}       onClick={(e) => e.stopPropagation()} data-testid="tutorial-backdrop-right" />
          {/* Spotlight ring around the actual target (NOT the union) so the
              user always sees what to click next. */}
          <div
            style={{
              position: 'fixed', top: rect.top, left: rect.left,
              width: rect.width, height: rect.height,
              borderRadius: 14,
              boxShadow: '0 0 0 3px rgba(0, 229, 255, 0.85), 0 0 24px rgba(0, 229, 255, 0.35)',
              pointerEvents: 'none', zIndex: 210,
              transition: 'top 0.2s ease, left 0.2s ease, width 0.2s ease, height 0.2s ease',
              animation: 'tutorial-pulse 1.6s ease-in-out infinite',
            }}
            data-testid="tutorial-spotlight"
          />
        </>
      );
    }

    if (effectiveAllowInteraction) {
      if (!rect) return null;
      const { top, left, width, height } = rect;
      return (
        <div
          style={{
            position: 'fixed', top, left, width, height,
            borderRadius: 14,
            boxShadow: '0 0 0 3px rgba(0, 229, 255, 0.85), 0 0 24px rgba(0, 229, 255, 0.35)',
            pointerEvents: 'none', zIndex: SPOT_RING_Z,
            transition: 'top 0.2s ease, left 0.2s ease, width 0.2s ease, height 0.2s ease',
            animation: 'tutorial-pulse 1.6s ease-in-out infinite',
          }}
          data-testid="tutorial-spotlight"
        />
      );
    }
    if (!rect || blockTargetClicks) {
      // Full-screen backdrop (no hole) — use for welcome/finish and for
      // steps like go_credit where we highlight a nav button but don't
      // actually let the user navigate.
      return (
        <>
          <div
            style={{
              position: 'fixed', inset: 0, background: BACKDROP_COLOR,
              zIndex: BACKDROP_Z, pointerEvents: 'auto',
            }}
            data-testid="tutorial-backdrop"
            onClick={(e) => e.stopPropagation()}
          />
          {rect && (
            <div
              style={{
                position: 'fixed', top: rect.top, left: rect.left,
                width: rect.width, height: rect.height,
                borderRadius: 14,
                boxShadow: '0 0 0 3px rgba(0, 229, 255, 0.85), 0 0 24px rgba(0, 229, 255, 0.35)',
                pointerEvents: 'none', zIndex: SPOT_RING_Z,
                animation: 'tutorial-pulse 1.6s ease-in-out infinite',
              }}
              data-testid="tutorial-spotlight"
            />
          )}
        </>
      );
    }
    const { top, left, width, height } = rect;
    const right = left + width;
    const bottom = top + height;
    // `go_island` / `go_businesses` highlight items that live in the mobile
    // BottomNav (z-70) — above the default backdrop (z-55). Raise the backdrop
    // above the nav so every OTHER nav item is non-clickable, while the cutout
    // hole keeps only the highlighted button tappable.
    const raiseAboveNav = currentStepId === 'go_island' || currentStepId === 'go_businesses' || currentStepId === 'go_trading_buy' || currentStepId === 'go_businesses_check';
    const stripZ = raiseAboveNav ? 80 : BACKDROP_Z;
    const ringZ = raiseAboveNav ? 81 : SPOT_RING_Z;
    const p = { position: 'fixed', background: BACKDROP_COLOR, zIndex: stripZ, pointerEvents: 'auto' };
    return (
      <>
        <div style={{ ...p, top: 0, left: 0, right: 0, height: Math.max(0, top) }} onClick={(e) => e.stopPropagation()} />
        <div style={{ ...p, top: bottom, left: 0, right: 0, bottom: 0 }} onClick={(e) => e.stopPropagation()} />
        <div style={{ ...p, top, left: 0, width: Math.max(0, left), height }} onClick={(e) => e.stopPropagation()} />
        <div style={{ ...p, top, left: right, right: 0, height }} onClick={(e) => e.stopPropagation()} />
        <div
          style={{
            position: 'fixed', top, left, width, height,
            borderRadius: 14,
            boxShadow: '0 0 0 3px rgba(0, 229, 255, 0.85), 0 0 24px rgba(0, 229, 255, 0.35)',
            pointerEvents: 'none', zIndex: ringZ,
            transition: 'top 0.2s ease, left 0.2s ease, width 0.2s ease, height 0.2s ease',
            animation: 'tutorial-pulse 1.6s ease-in-out infinite',
          }}
          data-testid="tutorial-spotlight"
        />
      </>
    );
  };

  // --- Top progress ribbon (thin bar at the very top of the screen) ---
  const renderTopProgress = () => {
    const pct = Math.min(100, Math.round((stepIndex / totalSteps) * 100));
    return (
      <div
        style={{
          position: 'fixed', top: 0, left: 0, right: 0, height: 3,
          background: 'rgba(5, 8, 20, 0.35)', zIndex: CARD_Z + 10,
          pointerEvents: 'none',
        }}
        data-testid="tutorial-top-progress"
      >
        <div
          style={{
            height: '100%', width: `${pct}%`,
            background: 'linear-gradient(90deg, #00e5ff, #7c5cff)',
            boxShadow: '0 0 8px rgba(0, 229, 255, 0.7)',
            transition: 'width 500ms cubic-bezier(.2,.8,.2,1)',
          }}
        />
      </div>
    );
  };

  // --- Card fade opacity driven by `cardPhase` ---
  //  idle        → fully visible
  //  fading-out  → 0.35 (dimmed, still readable)
  //  breathing   → 0.35 (still visible while spotlight settles)
  //  fading-in   → 1
  const cardOpacity =
    cardPhase === 'fading-out' ? 0.35 :
    cardPhase === 'breathing'  ? 0.35 :
    1;
  const cardTransition =
    cardPhase === 'fading-out' ? 'opacity 200ms ease-in' :
    cardPhase === 'fading-in'  ? 'opacity 250ms ease-out' :
    cardPhase === 'breathing'  ? 'opacity 0ms' :
    'opacity 200ms ease-out';
  // The card stays visible during transitions, but we lock pointer events
  // briefly to prevent double-clicks while the step is re-rendering.
  const cardPointerEvents = (cardPhase === 'breathing' || cardPhase === 'fading-out') ? 'none' : 'auto';

  // --- Card position ---
  // Desktop & mobile: ALWAYS bottom-docked banner (centered horizontally)
  // — never near the highlighted element, so re-opening the sidebar or
  // pulling up a modal can never double-cover the tutorial text.
  // On mobile the banner is a bit more compact (smaller text, tighter padding).
  // EXCEPTION: `go_businesses_check` — desktop pins the card to the RIGHT
  // side, mobile pins it to the TOP, because the user is asked to look at
  // the warehouse panel which lives in the centre of the screen.
  // `isCheckStorageStep` — desktop layout puts the card on the right side
  // (and on mobile pins it to the top). Used when the user must read/click
  // something on the LEFT half of the screen.
  const isCheckStorageStep = currentStepId === 'go_businesses_check'
    || currentStepId === 'explain_t3_buff'
    || currentStepId === 'buy_lot';
  // `isMobileTopStep` — mobile-only top pin. On desktop the card stays at
  // its default bottom-center position. Used for the plot-purchase step,
  // where on mobile the bottom card overlaps the central «Buy» confirmation
  // button — UX requested it be moved to the top. Also used for the bottom-nav
  // steps `go_island` («Открой список карт») and `go_businesses` («БИЗНЕСЫ»):
  // their targets live in the bottom nav, so a bottom-docked card would cover
  // the very button the user must tap.
  const isMobileTopStep = currentStepId === 'fake_buy_plot'
    || currentStepId === 'go_island'
    || currentStepId === 'go_businesses'
    || currentStepId === 'go_trading_buy'
    || currentStepId === 'go_businesses_check';
  // Compact card: hide description+instruction blocks when modal is open
  // → make the card visibly shorter (less padding/maxHeight).
  // Per UX request the empty space at the bottom of the card was halved.
  const isCompactCard = isModalOpenStep;
  let cardStyle;
  if (isMobile) {
    // v2.3.x: `explain_t3_buff` card position depends on the buff modal:
    //   • modal CLOSED (user must click the highlighted Neuro-Core card) →
    //     card pinned at the TOP so it doesn't cover the resource cards below.
    //   • modal OPEN («Разгон системы») → card pinned at the BOTTOM so it
    //     doesn't overlap the modal that opens in the upper/central area.
    const forceMobileBottom = currentStepId === 'explain_t3_buff' && t3BuffModalOpen;
    if ((isCheckStorageStep || isMobileTopStep) && !forceMobileBottom) {
      // Telegram WebApp has a fixed top bar that can cover the very top of
      // the page. We add a generous safe-area offset so the tutorial card
      // is never hidden behind it.
      cardStyle = {
        position: 'fixed',
        left: 6,
        right: 6,
        top: 'max(env(safe-area-inset-top, 0px), 56px)',
        maxHeight: minimized ? 56 : '32vh',
        zIndex: CARD_Z,
        overflowY: 'auto',
      };
    } else {
      cardStyle = {
        position: 'fixed',
        left: 6,
        right: 6,
        bottom: 8,
        maxHeight: minimized ? 56 : (isCompactCard ? '20vh' : '30vh'),
        zIndex: CARD_Z,
        overflowY: 'auto',
      };
    }
  } else if (isCheckStorageStep) {
    const w = Math.min(420, viewport.width - 32);
    cardStyle = {
      position: 'fixed',
      right: 16,
      top: '50%',
      transform: 'translateY(-50%)',
      width: w,
      maxHeight: '60vh',
      zIndex: CARD_Z,
      overflowY: 'auto',
    };
  } else {
    const maxW = Math.min(720, viewport.width - 32);
    cardStyle = {
      position: 'fixed',
      left: '50%',
      transform: 'translateX(-50%)',
      bottom: 16,
      width: maxW,
      maxWidth: 'calc(100vw - 32px)',
      zIndex: CARD_Z,
      maxHeight: isCompactCard ? '18vh' : '26vh',
      overflowY: 'auto',
    };
  }

  return (
    <>
      {/* Spotlight / click blocker */}
      {renderOverlay()}

      {/* Info card */}
      <div
        data-testid="tutorial-card"
        className="bg-[#101227] border border-cyber-cyan/50 rounded-2xl shadow-2xl shadow-cyber-cyan/20 text-white overflow-hidden"
        style={{ ...cardStyle, opacity: cardOpacity, transition: cardTransition, pointerEvents: cardPointerEvents }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-4 sm:px-5 py-2 sm:py-3 border-b border-white/10 flex items-center gap-3">
          <div className="w-9 h-9 sm:w-10 sm:h-10 rounded-lg bg-cyber-cyan/20 flex items-center justify-center flex-shrink-0">
            <Target className="w-4 h-4 sm:w-5 sm:h-5 text-cyber-cyan" />
          </div>
          <div className="flex-1 min-w-0 flex items-center">
            <h3 className="text-[13px] sm:text-base font-bold leading-snug break-words" data-testid="tutorial-step-title">{ST('title')}</h3>
          </div>
          {isMobile && (
            <button
              type="button"
              onClick={() => setMinimized((m) => !m)}
              className="text-text-muted hover:text-cyber-cyan transition-colors flex-shrink-0"
              title={minimized ? 'Развернуть' : 'Свернуть'}
              data-testid="tutorial-minimize-btn"
            >
              {minimized ? <Maximize2 className="w-5 h-5" /> : <Minus className="w-5 h-5" />}
            </button>
          )}
        </div>

        {!minimized && (
          <>
            {/* Body */}
            <div className="px-4 sm:px-5 py-2 sm:py-3 space-y-2">
              {/* Hide verbose description on buy_lot once the Buy modal is open
                  and on create_lot once the Sell modal is open — the modal
                  itself takes over the UI, so we keep just the instruction
                  pill + action buttons. */}
              {!((currentStepId === 'buy_lot' && buyModalOpen) || (currentStepId === 'create_lot' && !!createLotFormHint)) && (
                <p
                  className="text-[11px] sm:text-sm text-text-muted whitespace-pre-line break-words"
                  data-testid="tutorial-step-description"
                >
                  {(currentStepId === 'explain_t3_buff' && t3BuffModalOpen && ST('description_phase2'))
                    ? ST('description_phase2')
                    : (targetReached && ST('description_arrived')) ? ST('description_arrived') : ST('description')}
                </p>
              )}
              {/* Instruction pill + inline Далее (same row when there's space).
                  Per UX request: the "Next" button must sit on the same level
                  as the instruction text, not in a separate footer below. */}
              <div className="px-3 py-2 bg-cyber-cyan/10 border border-cyber-cyan/20 rounded-lg text-[11px] sm:text-sm text-white flex items-start gap-2">
                <MapPin className="w-4 h-4 text-cyber-cyan flex-shrink-0 mt-0.5" />
                <span className="break-words flex-1 min-w-0" data-testid="tutorial-step-instruction">
                  {buyLotInstructionOverride
                    || createLotInstructionOverride
                    || ((currentStepId === 'explain_t3_buff' && t3BuffModalOpen && ST('instruction_phase2')) ? ST('instruction_phase2') : null)
                    || ((targetReached && ST('instruction_arrived')) ? ST('instruction_arrived') : ST('instruction'))}
                </span>
                {!hidePrimary && (
                  <Button
                    size="sm"
                    onClick={onClickPrimary}
                    disabled={primaryDisabled}
                    className="bg-cyber-cyan text-black hover:bg-cyber-cyan/80 font-bold whitespace-normal break-words h-auto min-h-[28px] px-2 py-1 inline-flex items-center justify-center gap-1 flex-shrink-0 ml-auto"
                    data-testid="tutorial-primary-action-btn"
                  >
                    <span className="break-words text-[11px] sm:text-xs">{primaryLabel()}</span>
                    <ChevronRight className="w-4 h-4 flex-shrink-0" />
                  </Button>
                )}
              </div>
              {/* Optional skip-step button — rendered separately ONLY for
                  steps marked `optional` (currently none in v2). Kept here
                  so the layout stays clean even with no Next button. */}
              {isOptional && (
                <div className="flex justify-end">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => skip(currentStepId)}
                    className="border-white/20 text-text-muted hover:text-white text-xs"
                    data-testid="tutorial-skip-step-btn"
                  >
                    <SkipForward className="w-4 h-4 mr-0.5" /> {T('skip_optional')}
                  </Button>
                </div>
              )}
            </div>
          </>
        )}
      </div>

      {/* Top progress ribbon */}
      {renderTopProgress()}

      {/* Keyframes for pulse */}
      <style>{`
        @keyframes tutorial-pulse {
          0%, 100% { box-shadow: 0 0 0 3px rgba(0, 229, 255, 0.85), 0 0 24px rgba(0, 229, 255, 0.35); }
          50%     { box-shadow: 0 0 0 5px rgba(0, 229, 255, 1),    0 0 36px rgba(0, 229, 255, 0.6); }
        }
      `}</style>
    </>
  );
}
