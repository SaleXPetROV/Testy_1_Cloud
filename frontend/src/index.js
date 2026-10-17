import './lib/i18nAuto'; // fill missing translations (LibreTranslate, see scripts/i18n-autofill.cjs)
import React from "react";
import ReactDOM from "react-dom/client";
import "@/index.css";
import App from "@/App";
import ErrorBoundary from "@/components/ErrorBoundary";
import { bootstrapLanguage } from "@/lib/languageBootstrap";
import axios from "axios";
import { installGameModeFetch, isDemo, showDemoBlockedToast, isDemoBlockedResponse } from "@/lib/gameMode";
import { installProgressBus } from '@/lib/progressBus';
installProgressBus(axios);   // instant XP / progress refresh after the player's actions

// Demo mode: tag every backend request with X-Game-Mode so the backend guard
// can block real endpoints. Covers both raw fetch() and axios.
installGameModeFetch();
axios.interceptors.request.use((config) => {
  try {
    config.headers = config.headers || {};
    config.headers['X-Game-Mode'] = isDemo() ? 'demo' : 'real';
  } catch (e) { /* ignore */ }
  return config;
});

// When the backend guard rejects a real action while in demo mode it returns
// 403 { detail: "demo_mode_blocked" }. Surface the localized toast globally.
axios.interceptors.response.use(
  (r) => r,
  (error) => {
    try {
      const status = error?.response?.status;
      const detail = error?.response?.data?.detail;
      if (isDemoBlockedResponse(status, detail)) showDemoBlockedToast();
    } catch (e) { /* ignore */ }
    return Promise.reject(error);
  }
);

// F7 + F16: send the httpOnly session cookie on every request and attach the
// CSRF double-submit header on mutating requests. The Authorization: Bearer
// header (from localStorage) is kept as a fallback for Telegram Mini App /
// mobile clients, so nothing breaks during the cookie rollout.
axios.defaults.withCredentials = true;
axios.interceptors.request.use((config) => {
  try {
    const method = (config.method || 'get').toLowerCase();
    if (['post', 'put', 'patch', 'delete'].includes(method)) {
      const m = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
      if (m) {
        config.headers = config.headers || {};
        config.headers['X-CSRF-Token'] = decodeURIComponent(m[1]);
      }
    }
  } catch (e) { /* ignore */ }
  return config;
});


// Language coming from the Telegram bot (?lang=xx): persist BEFORE React mounts
// so LanguageProvider initializes in that language (e.g. the support window).
try {
  const _p = new URLSearchParams(window.location.search);
  const _lang = _p.get('lang');
  const _SUPPORTED = ['ru', 'en', 'es', 'zh', 'fr', 'de', 'ja', 'ko'];
  if (_lang && _SUPPORTED.includes(_lang)) {
    localStorage.setItem('ton_city_lang', _lang);
  }
} catch (e) { /* ignore */ }

// Completely disable React Error Overlay for cross-origin Script errors
// This runs before React loads.
// F4 hardening: use `textContent` instead of `innerHTML` to comply with a
// strict CSP without `unsafe-eval`. Behavior is identical (no JS/DOM parsing).
const hideErrorOverlay = () => {
  const style = document.createElement('style');
  style.textContent = `
    iframe#webpack-dev-server-client-overlay { display: none !important; }
    body > iframe[style*="position: fixed"] { display: none !important; }
  `;
  document.head.appendChild(style);
};

// Run immediately
hideErrorOverlay();

// Override error handling globally
const originalOnError = window.onerror;
window.onerror = (message, source, lineno, colno, error) => {
  // Suppress cross-origin Script errors
  if (message === 'Script error.' || message?.toString?.().includes?.('Script error')) {
    return true; // Prevent default handling
  }
  if (originalOnError) {
    return originalOnError(message, source, lineno, colno, error);
  }
  return false;
};

// Suppress wallet extension errors in console
const originalError = console.error;
console.error = (...args) => {
  const msg = args[0]?.toString() || '';
  // Suppress known extension conflicts and cross-origin errors
  if (msg.includes('Cannot redefine property: ethereum') ||
      msg.includes('evmAsk.js') ||
      msg.includes('chrome-extension://') ||
      msg.includes('Script error') ||
      msg.includes('handleError') ||
      msg.includes('at handleError')) {
    return; // Silently ignore
  }
  originalError.apply(console, args);
};

// Global error handler for uncaught extension errors and cross-origin script errors
window.addEventListener('error', (event) => {
  if (event.filename?.includes('chrome-extension://') ||
      event.message?.includes('Cannot redefine property') ||
      event.message === 'Script error.' ||
      event.message?.includes('Script error') ||
      event.message?.includes('handleError') ||
      !event.filename) { // No filename means cross-origin
    event.preventDefault();
    event.stopImmediatePropagation();
    return true;
  }
}, true); // Use capture phase

// Suppress unhandled promise rejections from external sources
window.addEventListener('unhandledrejection', (event) => {
  const reason = event.reason?.toString() || '';
  if (reason.includes('Script error') || 
      reason.includes('chrome-extension://') ||
      reason.includes('ResizeObserver')) {
    event.preventDefault();
    event.stopImmediatePropagation();
  }
});

const root = ReactDOM.createRoot(document.getElementById("root"));

// Render immediately; bootstrapLanguage runs in background.
// (Awaiting bootstrapLanguage().finally() before render caused React to never mount
// behind the preview proxy due to a hung module-init pattern.)
root.render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>,
);
bootstrapLanguage().catch(() => {});
