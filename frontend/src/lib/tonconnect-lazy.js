/**
 * Lazy TonConnect layer.
 *
 * WHY: `TonConnectUIProvider` initialises the TON SDK the moment it mounts —
 * it fetches the wallets-list and tries to restore a bridge session, hitting
 * tonapi.io / toncenter.com. Rendered at the app root, that means every cold
 * page load (incl. Safari's fraud scanner) fires crypto/RPC traffic BEFORE the
 * user does anything. Safari's Google-Safe-Browsing heuristic reads that
 * "wallet activity with no interaction" as drainer-like and blocks the domain.
 *
 * FIX: the real provider is NOT in the React tree for a guest. This shim keeps
 * `useTonWallet` / `useTonConnectUI` / `TonConnectButton` working everywhere
 * (no crashes) by serving inert stubs until activation. Activation happens on
 * the first user gesture (or when already authenticated / inside Telegram),
 * at which point the real provider mounts and a bridge publishes live values.
 *
 * Result: 0 TON RPC on cold start; identical behaviour after the first tap.
 */

import React, {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
} from 'react';
import {
  TonConnectUIProvider,
  TonConnectButton as RealTonConnectButton,
  useTonConnectUI as useRealTonConnectUI,
  useTonWallet as useRealTonWallet,
} from '@tonconnect/ui-react';

const LazyCtx = createContext(null);

function computeManifestUrl() {
  try {
    // Always the dynamic backend manifest — origin/icon derived from the
    // request host, so it is correct & reachable on any domain (no hardcoded
    // gramcity.games that 404s the icon on gramcity.app).
    return `${window.location.origin}/api/tonconnect-manifest-v6.json`;
  } catch (_) {
    return '/api/tonconnect-manifest-v6.json';
  }
}

function isTelegramEnv() {
  try {
    const sdk = window.Telegram?.WebApp?.initData;
    if (sdk && typeof sdk === 'string' && sdk.length > 0) return true;
    return /tgWebAppData|tgWebAppPlatform/i.test(
      (window.location.hash || '') + (window.location.search || '')
    );
  } catch (_) { return false; }
}

function shouldStartActive() {
  try {
    if (window.Telegram?.WebApp?.initData && window.Telegram?.WebApp?.initDataUnsafe?.user) return true;
    // Authenticated browser session: activate on LOAD (not on the first gesture)
    // so the provider mount/remount never lands mid-click and drops a button
    // press (fixes the "first tap after load is dropped" bug on the map).
    return !!(localStorage.getItem('token') || localStorage.getItem('ton_city_token'));
  } catch (_) {
    return false;
  }
}

// Should the provider auto-activate on the first gesture? Only for a session
// that will need the wallet anyway (Telegram or an already-authenticated
// browser user whose wallet session we want to restore). A PURE GUEST is
// deliberately excluded: activating the provider inserts a wrapper above the
// app tree and REMOUNTS it, which — if it happened on the same click that
// submitted the /auth login form — would reset the inputs and abort the
// submit. For guests the provider mounts only via an explicit wallet action
// (TonConnectButton / stub.openModal), which never coincides with login.
function shouldActivateOnGesture() {
  try {
    if (window.Telegram?.WebApp?.initData && window.Telegram?.WebApp?.initDataUnsafe?.user) return true;
    return !!(localStorage.getItem('token') || localStorage.getItem('ton_city_token'));
  } catch (_) {
    return false;
  }
}

// A promise that never settles, so effects doing `await tonConnectUI.connectionRestored`
// simply PARK (no network / no proof-payload fetch) while the provider is inactive.
const PARKED_PROMISE = new Promise(() => {});

function makeStub(activate, pendingRef) {
  const arm = () => { pendingRef.current = 'openModal'; activate(); };
  return {
    connected: false,
    connectionRestored: PARKED_PROMISE,
    account: null,
    wallet: null,
    openModal: async () => { arm(); },
    openSingleWalletModal: async () => { arm(); },
    closeModal: () => {},
    closeSingleWalletModal: () => {},
    disconnect: async () => {},
    connectWallet: async () => { arm(); },
    sendTransaction: async () => { activate(); throw new Error('TonConnect is initialising — please tap again'); },
    setConnectRequestParameters: () => {},
    onModalStateChange: () => () => {},
    onStatusChange: () => () => {},
    onSingleWalletModalStateChange: () => () => {},
  };
}

export function LazyTonProvider({ children, manifestUrl }) {
  const [active, setActive] = useState(shouldStartActive);
  const activate = useCallback(() => setActive(true), []);
  const pendingRef = useRef(null);
  const [live, setLive] = useState({ wallet: null, tonConnectUI: null });
  // Callers awaiting the REAL tonConnectUI (see ensureUI). Resolved the moment
  // TonBridge publishes the live SDK instance.
  const uiResolversRef = useRef([]);

  // Return a promise that resolves with the REAL tonConnectUI. If the provider
  // is inactive (guest cold start → stub), this activates it and parks the
  // caller until the SDK is mounted & published. This is the fix for the
  // "wallet connects only on the second click" bug: the first click used to
  // merely activate the provider (arming the tonProof nonce on the inert stub,
  // which is a no-op), so the modal opened without a proof; the second click
  // finally hit the real UI. Now the click handler awaits the real UI and runs
  // the whole arm-nonce + openModal sequence against it on the FIRST click.
  const ensureUI = useCallback(() => {
    if (live.tonConnectUI) return Promise.resolve(live.tonConnectUI);
    activate();
    return new Promise((resolve, reject) => {
      const entry = { resolve, reject };
      uiResolversRef.current.push(entry);
      // Safety timeout so a caller never hangs forever if the SDK fails to load.
      entry.timer = setTimeout(() => {
        uiResolversRef.current = uiResolversRef.current.filter((e) => e !== entry);
        reject(new Error('TonConnect UI failed to initialise'));
      }, 12000);
    });
  }, [live.tonConnectUI, activate]);

  // Flush parked ensureUI() callers as soon as the real UI is published.
  useEffect(() => {
    if (live.tonConnectUI && uiResolversRef.current.length) {
      const rs = uiResolversRef.current;
      uiResolversRef.current = [];
      rs.forEach((e) => { try { clearTimeout(e.timer); e.resolve(live.tonConnectUI); } catch (_) { /* noop */ } });
    }
  }, [live.tonConnectUI]);

  // Activate on a user gesture ONCE the session is eligible. This path is for
  // NON-Telegram sessions only: a browser user who just logged in (token
  // present) gets the wallet session restored on their next gesture. Inside
  // Telegram we deliberately DO NOT use gesture activation — the load-time
  // poller below activates before any tap, so the provider remount never
  // coincides with (and swallows) the user's first tap.
  //   • pure guest  → never eligible via gesture → provider stays OFF (silence
  //     preserved; the /auth login click therefore never remounts the tree).
  // A guest can still open the wallet explicitly (TonConnectButton / stub.openModal).
  useEffect(() => {
    if (active) return undefined;
    if (isTelegramEnv()) return undefined; // Telegram handled by the load poller
    const EV = ['pointerdown', 'touchstart', 'keydown', 'scroll'];
    const opts = { passive: true, capture: true };
    const onGesture = () => {
      if (shouldActivateOnGesture()) {
        EV.forEach((e) => { try { window.removeEventListener(e, onGesture, opts); } catch (_) { /* noop */ } });
        setActive(true);
      }
    };
    EV.forEach((e) => { try { window.addEventListener(e, onGesture, opts); } catch (_) { /* noop */ } });
    return () => EV.forEach((e) => { try { window.removeEventListener(e, onGesture, opts); } catch (_) { /* noop */ } });
  }, [active]);

  const stub = useMemo(() => makeStub(activate, pendingRef), [activate]);

  // Inside a Telegram Mini App, activate the real provider PROGRAMMATICALLY as
  // soon as initData is available (it can arrive a beat after mount on slow
  // devices), WITHOUT waiting for a user gesture. This matters because
  // activating mounts TonConnectUIProvider above the app and REMOUNTS the tree;
  // if that remount happened on the user's FIRST tap (the old gesture-driven
  // path for late initData) it swallowed that tap's click (DOM node replaced
  // between pointerdown and mouseup). Doing it on load — before any tap —
  // keeps the very first interaction (e.g. the Telegram create/link choice
  // buttons) working. Plain-browser guests are unaffected: isTelegramEnv() is
  // false, so cold-start TON silence is preserved.
  useEffect(() => {
    if (active) return undefined;
    if (!isTelegramEnv()) return undefined;
    let tries = 0;
    const iv = setInterval(() => {
      tries += 1;
      let ready = false;
      try {
        ready = !!(window.Telegram?.WebApp?.initData) ||
          !!(localStorage.getItem('token') || localStorage.getItem('ton_city_token'));
      } catch (_) { ready = false; }
      if (ready) { clearInterval(iv); setActive(true); }
      else if (tries > 60) { clearInterval(iv); } // ~9s safety cap
    }, 150);
    return () => clearInterval(iv);
  }, [active]);

  const ctxValue = useMemo(() => ({
    active,
    activate,
    ensureUI,
    pendingRef,
    stub,
    wallet: live.wallet,
    tonConnectUI: live.tonConnectUI,
    setLive,
  }), [active, activate, ensureUI, stub, live]);

  if (!active) {
    return <LazyCtx.Provider value={ctxValue}>{children}</LazyCtx.Provider>;
  }

  return (
    <LazyCtx.Provider value={ctxValue}>
      <TonConnectUIProvider
        manifestUrl={manifestUrl || computeManifestUrl()}
        uiPreferences={{ theme: 'DARK' }}
        actionsConfiguration={{ twaReturnUrl: window.location.origin }}
      >
        <TonBridge />
        {children}
      </TonConnectUIProvider>
    </LazyCtx.Provider>
  );
}

// Mounted ONLY inside the real provider: reads the real hooks and publishes
// their values up into the lazy context so shim consumers stay in sync.
function TonBridge() {
  const [ui] = useRealTonConnectUI();
  const wallet = useRealTonWallet();
  const ctx = useContext(LazyCtx);

  useEffect(() => {
    if (ctx) ctx.setLive({ wallet, tonConnectUI: ui });
  }, [wallet, ui]); // eslint-disable-line react-hooks/exhaustive-deps

  // Flush an action queued before the provider was ready (e.g. openModal from a
  // guest's very first tap on the wallet button).
  useEffect(() => {
    if (ui && ctx && ctx.pendingRef.current === 'openModal') {
      ctx.pendingRef.current = null;
      try { ui.openModal(); } catch (_) { /* noop */ }
    }
  }, [ui]); // eslint-disable-line react-hooks/exhaustive-deps

  return null;
}

export function useTonWallet() {
  const ctx = useContext(LazyCtx);
  return ctx ? ctx.wallet : null;
}

export function useTonConnectUI() {
  const ctx = useContext(LazyCtx);
  const ui = (ctx && ctx.tonConnectUI) || (ctx && ctx.stub) || null;
  const setOptions = useCallback(() => {}, []);
  return [ui, setOptions];
}

// Returns a function that resolves with the REAL tonConnectUI, activating the
// lazy provider if needed. Use this in explicit wallet-connect handlers so the
// nonce/proof + openModal run against the live SDK on the very first click.
export function useEnsureTonConnectUI() {
  const ctx = useContext(LazyCtx);
  return useCallback(
    () => (ctx && ctx.ensureUI ? ctx.ensureUI() : Promise.reject(new Error('no provider'))),
    [ctx],
  );
}

export function TonConnectButton(props = {}) {
  const ctx = useContext(LazyCtx);
  const ready = !!(ctx && ctx.active && ctx.tonConnectUI);
  if (ready) {
    return <RealTonConnectButton {...props} />;
  }
  const onClick = () => {
    if (ctx) { ctx.pendingRef.current = 'openModal'; ctx.activate(); }
  };
  return (
    <button
      type="button"
      className={props.className}
      style={props.style}
      onClick={onClick}
      data-testid="ton-connect-button-lazy"
    >
      Connect Wallet
    </button>
  );
}
