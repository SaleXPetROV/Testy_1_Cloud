import React, { createContext, useContext, useEffect, useState, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api`;

const TutorialContext = createContext(null);

export function TutorialProvider({ children, user }) {
  const [active, setActive] = useState(false);
  const [completed, setCompleted] = useState(false);
  const [currentStepId, setCurrentStepId] = useState(null);
  const [currentStep, setCurrentStep] = useState(null);
  const [steps, setSteps] = useState([]);
  const [state, setState] = useState({ fake_plots: [], fake_resources: {}, fake_lot_id: null });
  const [loading, setLoading] = useState(false);
  const [showStartModal, setShowStartModal] = useState(false);
  const [showFinishConfirm, setShowFinishConfirm] = useState(false);
  const [showCompletedModal, setShowCompletedModal] = useState(false);
  // Beautiful "you received a bonus 1 GRAM" modal, shown right after the
  // tutorial is finished and the graduation reward is granted.
  const [showGramBonusModal, setShowGramBonusModal] = useState(false);
  // v2.2.1: confirmation modal shown when the user clicks the X icon on the
  // tutorial card. Lets them either "Continue" the tutorial or "End" it.
  // When they confirm End, the existing /abandon → CompletedModal → T3 reward
  // chain takes over.
  const [showAbandonConfirm, setShowAbandonConfirm] = useState(false);
  // Has the user already claimed the one-shot T3 reward (any prior run)?
  // Polled on mount via /tutorial/t3-reward-status. When true, both Skip and
  // Finish close silently without forcing the user to pick again.
  const [t3RewardClaimed, setT3RewardClaimed] = useState(false);
  const [statusLoaded, setStatusLoaded] = useState(false);
  const lastStatusRef = useRef(null);

  const getToken = () => localStorage.getItem('token');

  const refreshT3Status = useCallback(async () => {
    const token = getToken();
    if (!token) return;
    try {
      const res = await fetch(`${API}/tutorial/t3-reward-status`, { headers: { Authorization: `Bearer ${token}` } });
      if (!res.ok) return;
      const data = await res.json();
      setT3RewardClaimed(!!data.claimed);
    } catch (e) { /* noop */ }
  }, []);

  const refreshStatus = useCallback(async () => {
    const token = getToken();
    if (!token) return null;
    try {
      const res = await fetch(`${API}/tutorial/status`, { headers: { Authorization: `Bearer ${token}` } });
      if (!res.ok) return null;
      const data = await res.json();
      setActive(!!data.active);
      setCompleted(!!data.completed);
      setCurrentStepId(data.current_step_id);
      setCurrentStep(data.current_step);
      setSteps(data.steps || []);
      setState(data.state || { fake_plots: [], fake_resources: {}, fake_lot_id: null });
      lastStatusRef.current = data;
      setStatusLoaded(true);
      return data;
    } catch (e) {
      console.warn('[tutorial] status failed', e);
      return null;
    }
  }, []);

  // Initial fetch when user is available
  useEffect(() => {
    if (user?.id) {
      refreshStatus();
      refreshT3Status();
    }
  }, [user?.id, refreshStatus]);

  // Auto-show start modal for fresh users (not completed, not active).
  // Source of truth: DB (`completed` / `active` fields on user). We do NOT
  // rely on sessionStorage — so that clearing `tutorial_completed` in the DB
  // (e.g. admin `reset`) immediately re-enables the welcome prompt.
  //
  // v2.3.x — if the user has already claimed the one-shot T3 reward in a
  // previous run, we NEVER auto-prompt again (even if `tutorial_completed`
  // was flipped back to false by /reset). Prevents "tutorial keeps
  // reopening after each login" cases reported for TON-wallet-registered
  // users. Replay is still possible via the explicit sidebar/menu button.
  useEffect(() => {
    if (!user?.id) return;
    if (!statusLoaded) return;
    if (active || completed) return; // already in tutorial or already done
    if (t3RewardClaimed) return;      // already got reward — don't auto-prompt
    // Small delay so the UI settles before opening
    const timer = setTimeout(() => setShowStartModal(true), 800);
    return () => clearTimeout(timer);
  }, [active, completed, t3RewardClaimed, user?.id, statusLoaded]);

  // Manual launcher: used by sidebar/mobile-nav/landing-page tutorial buttons.
  // ALWAYS resets the backend state first so the user replays the tutorial
  // from step 1 with a fresh snapshot (no carry-over from previous attempts).
  const launch = useCallback(async () => {
    if (active) return; // already running — tour is on screen
    const token = getToken();
    if (token) {
      try {
        await fetch(`${API}/tutorial/reset`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
        });
        await refreshStatus();
      } catch (e) {
        console.warn('[tutorial] reset before launch failed', e);
      }
    }
    setShowStartModal(true);
  }, [active, refreshStatus]);

  // Server-side buy-lot during buy_lot step — wrapper used by TradingPage
  const buyTutorialLot = useCallback(async ({ amount = 5 } = {}) => {
    const token = getToken();
    if (!token) return { ok: false };
    const res = await fetch(`${API}/tutorial/buy-lot`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ amount }),
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok) {
      await refreshStatus();
      return { ok: true, data };
    }
    return { ok: false, error: data.detail || 'Buy lot failed' };
  }, [refreshStatus]);

  // Fetch the hidden tutorial bot lot visible only to current user
  const getSeedLot = useCallback(async () => {
    const token = getToken();
    if (!token) return null;
    try {
      const res = await fetch(`${API}/tutorial/seed-lot`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) return null;
      const d = await res.json();
      return d.lot || null;
    } catch {
      return null;
    }
  }, []);

  // Mark tutorial as completed/skipped on the backend without actually running it.
  // Used when the user presses "Skip (can start later)" on the welcome modal —
  // this persists the choice in DB so we don't prompt again on next login.
  // Now also accepts an optional `t3Choice` so the user can claim the one-shot
  // T3 reward without going through the full tutorial.
  const dismissStart = useCallback(async (t3Choice = null) => {
    const token = getToken();
    setShowStartModal(false);
    if (!token) return { ok: false };
    try {
      const res = await fetch(`${API}/tutorial/mark-skipped`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ t3_choice: t3Choice }),
      });
      const data = await res.json().catch(() => ({}));
      if (data?.t3_reward) {
        try {
          window.localStorage.setItem('tutorial_reward_banner', data.t3_reward);
        } catch (e) { /* noop */ }
      }
      // v2.3.x: on the FIRST time the tutorial is skipped with a T3 reward
      // granted, also queue the referral-invite popup on GRAM Island.
      if (data?.t3_reward) {
        try {
          window.localStorage.setItem('pending_referral_invite', '1');
          window.dispatchEvent(new Event('referral-invite-show'));
        } catch (e) { /* noop */ }
      }
      // Synchronously flip the local "claimed" flag so the CompletedModal
      // chain doesn't reopen the picker (see same note in `finish`).
      if (t3Choice || data?.t3_reward) {
        setT3RewardClaimed(true);
      }
      await refreshStatus();
      await refreshT3Status();
      return { ok: true, data };
    } catch (e) {
      console.warn('[tutorial] mark-skipped failed', e);
      return { ok: false, error: e?.message };
    }
  }, [refreshStatus, refreshT3Status]);

  const start = useCallback(async () => {
    const token = getToken();
    if (!token) return;
    setLoading(true);
    try {
      const res = await fetch(`${API}/tutorial/start`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        setShowStartModal(false);
        await refreshStatus();
        // Tutorial grants +50 TON (= 50,000 $CITY) practice balance on the
        // backend. Re-fetch /auth/me so the global App state (sidebar header
        // balance, etc.) picks up the new balance immediately — otherwise the
        // user thinks nothing was added.
        try {
          const meRes = await fetch(`${API}/auth/me`, { headers: { Authorization: `Bearer ${token}` } });
          if (meRes.ok) {
            const me = await meRes.json();
            window.dispatchEvent(new CustomEvent('balanceUpdate', { detail: { balance: me.balance_ton } }));
          }
        } catch (_) { /* best-effort */ }
      }
    } finally {
      setLoading(false);
    }
  }, [refreshStatus]);

  // Abandon the tutorial early (the X button mid-tour). Rolls back the
  // tutorial sandbox on the backend, then refreshes status so `active`
  // becomes false. Used by TutorialAbandonConfirm — after this resolves the
  // caller shows the "Tutorial completed" modal (same UX as Skip-at-start),
  // from which the user can still claim the one-shot T3 reward.
  const abandon = useCallback(async () => {
    const token = getToken();
    if (!token) return { ok: false };
    try {
      await fetch(`${API}/tutorial/abandon`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
    } catch (e) {
      /* swallow — we still want to advance the UX even if cleanup failed */
    }
    await refreshStatus();
    await refreshT3Status();
    // Balance is rolled back to pre-tutorial value — propagate to App state.
    try {
      const meRes = await fetch(`${API}/auth/me`, { headers: { Authorization: `Bearer ${token}` } });
      if (meRes.ok) {
        const me = await meRes.json();
        window.dispatchEvent(new CustomEvent('balanceUpdate', { detail: { balance: me.balance_ton } }));
      }
    } catch (_) { /* best-effort */ }
    return { ok: true };
  }, [refreshStatus, refreshT3Status]);

  const advance = useCallback(async (stepId) => {
    const token = getToken();
    if (!token) return { ok: false };
    try {
      const res = await fetch(`${API}/tutorial/advance`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ step_id: stepId }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        await refreshStatus();
        return { ok: true, data };
      }
      return { ok: false, error: data.detail || 'Advance failed' };
    } catch (e) {
      return { ok: false, error: e.message };
    }
  }, [refreshStatus]);

  const skip = useCallback(async (stepId) => {
    const token = getToken();
    if (!token) return { ok: false };
    const res = await fetch(`${API}/tutorial/skip`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ step_id: stepId }),
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok) {
      await refreshStatus();
      return { ok: true, data };
    }
    return { ok: false, error: data.detail || 'Skip failed' };
  }, [refreshStatus]);

  const fakeBuyPlot = useCallback(async ({ x, y, zone, business_icon, business_name }) => {
    const token = getToken();
    if (!token) return { ok: false };
    const res = await fetch(`${API}/tutorial/fake-buy-plot`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ x, y, zone, business_icon, business_name }),
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok) {
      await refreshStatus();
      return { ok: true, data };
    }
    return { ok: false, error: data.detail || 'Fake buy plot failed' };
  }, [refreshStatus]);

  const fakeGrantResource = useCallback(async ({ resource_type = 'neuro_core', amount = 10 } = {}) => {
    const token = getToken();
    if (!token) return { ok: false };
    const res = await fetch(`${API}/tutorial/fake-grant-resource`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ resource_type, amount }),
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok) {
      await refreshStatus();
      return { ok: true, data };
    }
    return { ok: false, error: data.detail || 'Fake grant failed' };
  }, [refreshStatus]);

  const createTutorialLot = useCallback(async ({ resource_type = 'neuro_core', amount = 5, price_per_unit = 1.0 }) => {
    const token = getToken();
    if (!token) return { ok: false };
    const res = await fetch(`${API}/tutorial/create-lot`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ resource_type, amount, price_per_unit }),
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok) {
      await refreshStatus();
      return { ok: true, data };
    }
    return { ok: false, error: data.detail || 'Create tutorial lot failed' };
  }, [refreshStatus]);

  // Finish now accepts an optional T3 choice. If the user has already
  // claimed the one-shot reward in a previous run, the choice can be omitted
  // and the backend won't enforce it.
  const finish = useCallback(async (t3Choice) => {
    const token = getToken();
    if (!token) return { ok: false, error: 'no-token' };
    if (!t3Choice && !t3RewardClaimed) {
      return { ok: false, error: 'tutorial_t3_choice_required' };
    }
    setLoading(true);
    try {
      const res = await fetch(`${API}/tutorial/finish`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirm: true, t3_choice: t3Choice || null }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        // Stash the reward so the destination page (GRAM Island) can show the
        // dismissible welcome banner. Only when we actually granted something.
        if (data?.t3_reward) {
          try {
            window.localStorage.setItem('tutorial_reward_banner', data.t3_reward);
          } catch (e) { /* noop */ }
        }
        // v2.3.x: on the FIRST time the tutorial is finished (reward actually
        // granted), also queue the referral-invite popup on GRAM Island.
        if (data?.t3_reward) {
          try {
            window.localStorage.setItem('pending_referral_invite', '1');
            window.dispatchEvent(new Event('referral-invite-show'));
          } catch (e) { /* noop */ }
        }
        // Synchronously flip the local "claimed" flag BEFORE closing the
        // modals so subsequent re-opens (e.g. legacy auto-open paths) read
        // the fresh value and don't loop.
        if (t3Choice || data?.t3_reward) {
          setT3RewardClaimed(true);
        }
        // v2.2.X: previously this opened `CompletedModal` AFTER the T3 picker
        // — but per UX the completion screen must come FIRST and the picker
        // is rendered from inside it. The caller (TutorialTour.onClickPrimary)
        // now opens `CompletedModal` before this fires. So here we only close
        // the picker, refresh status, and leave navigation/UX to the picker
        // component itself.
        setShowFinishConfirm(false);
        setShowCompletedModal(false);
        await refreshStatus();
        await refreshT3Status();
        // Tutorial restores pre-tutorial balance — propagate to App state.
        try {
          const meRes = await fetch(`${API}/auth/me`, { headers: { Authorization: `Bearer ${token}` } });
          if (meRes.ok) {
            const me = await meRes.json();
            window.dispatchEvent(new CustomEvent('balanceUpdate', { detail: { balance: me.balance_ton, bonus_balance: me.bonus_balance } }));
          }
        } catch (_) { /* best-effort */ }
        return { ok: true, data };
      }
      return { ok: false, error: data.detail || 'finish-failed' };
    } finally {
      setLoading(false);
    }
  }, [refreshStatus, refreshT3Status, t3RewardClaimed]);

  // Derived helpers
  const isRouteAllowed = useCallback((path) => {
    if (!active) return true;
    if (!currentStep) return true;
    const target = currentStep.target_route;
    if (!target) return true;
    // Always allow settings/auth/tutorial itself
    if (path.startsWith('/auth') || path.startsWith('/forgot-password')) return true;
    // Allow the target route
    if (target === '/island' && (path === '/ton-island' || path === '/map' || path === '/island' || path === '/game')) return true;
    return path === target;
  }, [active, currentStep]);

  const getAllowedRoute = useCallback(() => {
    if (!active || !currentStep) return null;
    return currentStep.target_route;
  }, [active, currentStep]);

  const value = {
    active, completed, currentStepId, currentStep, steps, state, loading,
    statusLoaded,
    showStartModal, setShowStartModal,
    showFinishConfirm, setShowFinishConfirm,
    showCompletedModal, setShowCompletedModal,
    showGramBonusModal, setShowGramBonusModal,
    showAbandonConfirm, setShowAbandonConfirm,
    t3RewardClaimed, refreshT3Status,
    refreshStatus, start, advance, skip,
    fakeBuyPlot, fakeGrantResource, createTutorialLot, finish,
    buyTutorialLot, getSeedLot,
    isRouteAllowed, getAllowedRoute,
    launch, dismissStart, abandon,
  };

  return <TutorialContext.Provider value={value}>{children}</TutorialContext.Provider>;
}

export function useTutorial() {
  const ctx = useContext(TutorialContext);
  if (!ctx) {
    return {
      active: false,
      completed: false,
      currentStepId: null,
      currentStep: null,
      steps: [],
      state: { fake_plots: [], fake_resources: {}, fake_lot_id: null },
      statusLoaded: true,
      showStartModal: false, setShowStartModal: () => {},
      showFinishConfirm: false, setShowFinishConfirm: () => {},
      showCompletedModal: false, setShowCompletedModal: () => {},
      showGramBonusModal: false, setShowGramBonusModal: () => {},
      showAbandonConfirm: false, setShowAbandonConfirm: () => {},
      t3RewardClaimed: false, refreshT3Status: async () => {},
      refreshStatus: async () => {}, start: async () => {}, advance: async () => ({ ok: false }),
      skip: async () => ({ ok: false }), fakeBuyPlot: async () => ({ ok: false }),
      fakeGrantResource: async () => ({ ok: false }), createTutorialLot: async () => ({ ok: false }),
      finish: async () => {}, isRouteAllowed: () => true, getAllowedRoute: () => null,
      launch: () => {}, dismissStart: async () => {}, abandon: async () => ({ ok: false }),
    };
  }
  return ctx;
}

export default TutorialContext;
