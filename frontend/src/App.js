import { useState, useEffect, useCallback, useRef, lazy, Suspense } from "react";
import axios from "axios";
import { BrowserRouter, Routes, Route, useLocation, useNavigate, Navigate } from "react-router-dom";
import { LazyTonProvider } from "@/lib/tonconnect-lazy";
import { onFirstGesture } from "@/lib/firstGesture";
import { setupDeferredPixel } from "@/lib/loadPixel";
import { Toaster, toast } from "@/components/ui/sonner";
import CityBackground from "@/components/CityBackground";
import QuestHighlighter from "@/components/QuestHighlighter";
import { LanguageProvider } from "@/context/LanguageContext";
import { translations } from "@/lib/translations";
import LandingPage from "@/pages/LandingPage";
import AuthPage from '@/pages/AuthPage';
import GoogleCallback from '@/pages/GoogleCallback';

// Heavy pages are code-split — loaded only when the user visits them.
// LandingPage stays eager so the first paint is instant.
const MapPage = lazy(() => import("@/pages/MapPage"));
const TonIslandPage = lazy(() => import("@/pages/TonIslandPage"));
const DashboardPage = lazy(() => import("@/pages/DashboardPage"));
const AdminPage = lazy(() => import("@/pages/AdminPage"));
import { ADMIN_PATH } from "@/lib/adminPath";
const IncomeTablePage = lazy(() => import("@/pages/IncomeTablePage"));
const TradingPage = lazy(() => import("@/pages/TradingPageNew"));
const SorterGamePage = lazy(() => import("@/pages/SorterGamePage"));   // the first mini-game (promotion)
const MinigameRewardsPage = lazy(() => import("@/pages/MinigameRewardsPage"));   // its rewards: chests, puzzles, boosters, leaders
const TasksPage = lazy(() => import("@/pages/TasksPage"));
const MarketplacePage = lazy(() => import("@/pages/MarketplacePage"));
const MyBusinessesPage = lazy(() => import("@/pages/MyBusinessesPage"));
const ResourcesPage = lazy(() => import("@/pages/ResourcesPage"));
const LeaderboardPage = lazy(() => import("@/pages/LeaderboardPage"));
const TutorialPage = lazy(() => import("@/pages/TutorialPage"));
const ChatPage = lazy(() => import("@/pages/ChatPage"));
const CommunityPage = lazy(() => import("@/pages/CommunityPage"));
const CityPassPage = lazy(() => import("@/pages/CityPassPage"));
const SettingsPage = lazy(() => import('@/pages/SettingsPage'));
const ForgotPasswordPage = lazy(() => import('@/pages/ForgotPasswordPage'));
const SecurityPage = lazy(() => import('@/pages/SecurityPage'));
const TransactionHistoryPage = lazy(() => import('@/pages/TransactionHistoryPage'));
const CreditPage = lazy(() => import('@/pages/CreditPage'));
const TermsPage = lazy(() => import('@/pages/TermsPage'));
const PrivacyPage = lazy(() => import('@/pages/PrivacyPage'));
const SupportAgentPage = lazy(() => import('@/pages/SupportAgentPage'));
const SupportOnlyPage = lazy(() => import('@/pages/SupportOnlyPage'));
const MorePage = lazy(() => import('@/pages/MorePage'));
const RulesPage = lazy(() => import('@/pages/RulesPage'));
const RoadmapPage = lazy(() => import('@/pages/RoadmapPage'));

import GramCityLoader from '@/components/GramCityLoader';
import BottomNav from '@/components/BottomNav';
import MaintenanceOverlay from '@/components/MaintenanceOverlay';
import BlockedOverlay from '@/components/BlockedOverlay';
import DurabilityBanner from '@/components/DurabilityBanner';
import TelegramBridge from '@/components/TelegramBridge';
import ReferralRallyModal from '@/components/ReferralRallyModal';
import TelegramChoiceModal from '@/components/TelegramChoiceModal';
import { TutorialProvider } from '@/context/TutorialContext';
import TutorialTour from '@/components/tutorial/TutorialTour';
import TutorialStartModal from '@/components/tutorial/TutorialStartModal';
import { TutorialFinishConfirm, TutorialCompletedModal, TutorialAbandonConfirm } from '@/components/tutorial/TutorialFinishModal';
import "@/App.css";

// TON Connect manifest URL.
//
// ВАЖНО: Wallet (Telegram-бот) ходит за манифестом со СВОИХ серверов, а не с
// устройства пользователя. Любая динамика на бэкенде (нестабильный
// gramcity-backend, перезапуск gunicorn, лимит rate-limit на /api/*) → Wallet
// видит 5xx/таймаут и показывает "Ошибка манифеста". Поэтому на production
// мы отдаём СТАТИЧЕСКИЙ файл прямо из nginx (`frontend/public/...`), который
// 100% доступен и не зависит от состояния бэкенда.
//
// На preview-стенде статический файл бесполезен (там захардкожен gramcity.games,
// origin не совпадает с preview-доменом → Wallet откажет). Поэтому в preview
// используем динамический /api/-эндпоинт, который подставляет правильный origin.
//
// При смене иконки/имени приложения бампайте имя файла (v4 → v5) — Wallet
// КЭШИРУЕТ манифест по URL агрессивно и игнорирует Cache-Control.
// Always use the dynamic backend manifest: it derives `url`/`iconUrl` from the
// REQUEST host (X-Forwarded-Host aware), so the wallet always sees the correct
// origin and a reachable icon on ANY domain (gramcity.app, preview, future
// domains). The old static file hardcoded gramcity.games, so the icon 404'd on
// gramcity.app and the wallet showed a broken placeholder image.
const manifestUrl = `${typeof window !== 'undefined' ? window.location.origin : ''}/api/tonconnect-manifest-v6.json`;
const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

// ─── Single-session enforcement + Admin 2FA re-auth prompt ─────────────────
// Backend rotates `user.session_id` on every successful login. Old tokens carry
// a stale `sid` claim and the server returns 401 + `{detail: "session_invalidated"}`
// for them. This interceptor catches that, clears local state, and redirects
// to /auth so the kicked tab snaps to the login screen instantly.
//
// Additionally: when an admin action requires a fresh TOTP (2FA gate), the
// backend returns 401 with `detail === "TOTP required for this admin action"`.
// We prompt the admin for their 6-digit code once and transparently retry the
// original request with the `X-Admin-TOTP` header set. On "Invalid TOTP code"
// we prompt again (up to 2 retries) so a mistyped digit doesn't require the
// user to redo the whole action.
let _sessionKickInFlight = false;
// Global de-dup guard for the kick UX. Fetch-based checkAuth() AND the axios
// interceptor can both observe a 401 session_invalidated for the same tab
// (they run in parallel because different components use different HTTP
// clients). Firing the toast + redirect from BOTH results in "двойное
// уведомление о выходе" right after the user successfully logged in with a
// stale in-flight request still bouncing. This flag ensures only ONE place
// fires the kick UX per tab lifetime.
window.__ton_city_kick_fired = window.__ton_city_kick_fired || false;
// Suppression window after a successful login: any in-flight request that
// was armed with the OLD token before finishAuth() overwrote localStorage
// will 401 with session_invalidated. Those are NOT real kicks — the user
// just logged in. Skip the kick UX for ~6 seconds after the login toast so
// the residual 401s die silently.
window.__ton_city_just_logged_in_at = window.__ton_city_just_logged_in_at || 0;

// Guard against duplicate/parallel Telegram auto-login requests fired from
// concurrently-mounting components (the Race Condition source). Concurrent
// callers AWAIT the same in-flight promise instead of getting `null` (which
// used to make the 2nd caller fall through to the "no token" branch and render
// an unauthenticated state while the 1st call was still resolving).
let _tgAuthPromise = null;

// Details of the most recent auth-loading failure, surfaced in the "could not
// load your account" notification so the user (and the logs) know WHAT failed
// and WHY — instead of a generic message. Shape: { where, status, detail }.
let _lastAuthError = null;

// Read the Telegram Mini App initData string. Prefer the value parsed by the
// official SDK (window.Telegram.WebApp.initData); if the SDK failed to load or
// hasn't parsed it yet, fall back to reading the raw `tgWebAppData` launch
// param straight from the URL (Telegram always puts it in the location hash on
// launch). URLSearchParams decodes it once, yielding the exact query-string
// the backend expects (user=...&auth_date=...&hash=...).
// Once we have positively confirmed a genuine Telegram launch (non-empty
// initData or launch params in the URL) we remember it for the tab's lifetime.
// This keeps the Telegram-env signal stable across client-side navigations that
// drop the location hash (e.g. history.pushState('/maps') after account
// creation), so telemetry/behaviour don't downgrade to "web" mid-session.
let _tgEnvConfirmed = false;

function readTelegramInitData() {
  try {
    const sdk = window?.Telegram?.WebApp?.initData;
    if (sdk && typeof sdk === 'string' && sdk.length > 0) { _tgEnvConfirmed = true; return sdk; }
    const raw =
      (window.location.hash || '').replace(/^#/, '') +
      '&' +
      (window.location.search || '').replace(/^\?/, '');
    const d = new URLSearchParams(raw).get('tgWebAppData');
    if (d) { _tgEnvConfirmed = true; return d; }
    return '';
  } catch (_) { return ''; }
}

// Are we ACTUALLY launched inside a Telegram Mini App? NOTE: telegram-web-app.js
// is loaded on EVERY page and defines window.Telegram.WebApp even in a normal
// browser (with an EMPTY initData) — so presence of the WebApp object is NOT a
// valid signal. The real signal is a genuine launch payload: a non-empty
// initData, OR the Telegram launch params in the URL (tgWebAppData /
// tgWebAppPlatform). This stays true in real Telegram even when the SDK is slow
// or fails to load (initData is recoverable from the URL), yet correctly false
// in a plain browser so the guest landing renders instantly.
function looksLikeTelegramEnv() {
  try {
    if (_tgEnvConfirmed) return true;
    if (readTelegramInitData()) return true;
    if (/tgWebAppData|tgWebAppPlatform/i.test(
      (window.location.hash || '') + (window.location.search || '')
    )) { _tgEnvConfirmed = true; return true; }
    return false;
  } catch (_) { return false; }
}

/**
 * Attempt seamless Telegram Mini App login. Runs at most once at a time.
 * Returns:
 *   { status:'ok', token }             — logged into the linked account
 *   { status:'choice_required', telegram } — this Telegram is not linked yet
 *   null                                — not in Telegram / no initData / error
 * Auto-login (linked account) is instant; unlinked identities are NEVER
 * auto-created — the caller shows a create/link choice instead.
 */
// Wait (bounded) for initData to become available. The SDK usually parses it
// synchronously, but on slow devices / flaky in-app networks it can be a beat
// late; we also accept the URL fallback (readTelegramInitData). If we are
// clearly NOT in Telegram we bail out immediately so a plain browser never
// blocks.
async function waitForTelegramInitData(timeoutMs = 4000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const initData = readTelegramInitData();
    if (initData && initData.length > 0) return initData;
    if (!looksLikeTelegramEnv()) return '';
    await new Promise((r) => setTimeout(r, 100));
  }
  return readTelegramInitData();
}

function telegramMiniAppLogin() {
  // Coalesce concurrent callers onto a single request.
  if (_tgAuthPromise) return _tgAuthPromise;
  _tgAuthPromise = _runTelegramMiniAppLogin().finally(() => { _tgAuthPromise = null; });
  return _tgAuthPromise;
}

async function _runTelegramMiniAppLogin() {
  const initData = await waitForTelegramInitData();
  if (!initData || typeof initData !== 'string' || initData.length === 0) return null;
  // A single transient failure (Cloudflare 429/5xx, a network blip, or the
  // in-app browser dropping the very first request) must NOT leave the user
  // unauthenticated with no recovery — that is the exact "not every user gets
  // logged in" symptom. Retry transient errors with exponential backoff; only
  // a genuine terminal response (2xx, 400, 401) stops the loop.
  const isTransient = (status) => status === 429 || (status >= 500 && status <= 599);
  for (let attempt = 0; attempt < 4; attempt += 1) {
    let r = null;
    try {
      r = await fetch(`${BACKEND_URL}/api/auth/telegram/miniapp`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ init_data: initData }),
      });
    } catch (e) {
      r = null; // network error → transient
      
    }
    

    if (r && r.ok) {
      const d = await r.json();
      if (d?.status === 'choice_required') {
        return { status: 'choice_required', telegram: d.telegram || {} };
      }
      if (d?.require_2fa && d?.pre_auth_token) {
        try { sessionStorage.setItem('tg_preauth_token', d.pre_auth_token); } catch (_) {}
        window.location.assign('/auth?tg2fa=1');
        return null;
      }
      if (d?.token) {
        localStorage.setItem('token', d.token);
        localStorage.setItem('ton_city_token', d.token);
        if (d?.user?.language) {
          try { localStorage.setItem('ton_city_lang', d.user.language); } catch (_) {}
        }
        window.__ton_city_just_logged_in_at = Date.now();
        try { window?.Telegram?.WebApp?.requestWriteAccess?.(); } catch (_) {}
        return { status: 'ok', token: d.token, isNewSignup: !!d.is_new_signup };
      }
      return null;
    }

    // Terminal (non-transient) HTTP error → stop, don't spin.
    if (r && !isTransient(r.status)) {
      let _detail = '';
      try { _detail = JSON.stringify(await r.clone().json()); } catch (_) {}
      
      _lastAuthError = { where: 'POST /api/auth/telegram/miniapp', status: r.status, detail: _detail };
      return null;
    }

    // Transient (network / 429 / 5xx) → back off and retry.
    
    _lastAuthError = { where: 'POST /api/auth/telegram/miniapp', status: r ? r.status : 'network-error', detail: '' };
    const delay = 500 * Math.pow(2, attempt) + Math.floor(Math.random() * 250);
    await new Promise((res) => setTimeout(res, delay));
  }
  
  return null;
}

/** Create a brand-new Telegram account after the user chose "create new". */
async function telegramMiniAppCreate() {
  const initData = await waitForTelegramInitData();
  if (!initData) return null;
  try {
    const r = await fetch(`${BACKEND_URL}/api/auth/telegram/miniapp/create`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ init_data: initData }),
    });
    if (!r.ok) return null;
    const d = await r.json();
    if (d?.token) {
      localStorage.setItem('token', d.token);
      localStorage.setItem('ton_city_token', d.token);
      if (d?.user?.language) {
        try { localStorage.setItem('ton_city_lang', d.user.language); } catch (_) {}
      }
      window.__ton_city_just_logged_in_at = Date.now();
      try { window?.Telegram?.WebApp?.requestWriteAccess?.(); } catch (_) {}
      return d.token;
    }
    return null;
  } catch (_) {
    return null;
  }
}
function _isKickSuppressed() {
  try {
    if (window.__ton_city_kick_fired) return true;
    const t = Number(window.__ton_city_just_logged_in_at || 0);
    if (t && (Date.now() - t) < 6000) return true;
    // On the /auth page the user is DELIBERATELY logging in / switching
    // accounts. A leftover stale token from a previous session that 401s
    // with session_invalidated must not spam a "you were logged out" toast
    // here — the user is not being kicked, they're mid-login.
    if (typeof window !== 'undefined' && window.location.pathname === '/auth') return true;
  } catch (_) { /* noop */ }
  return false;
}
function _fireKickUXOnce() {
  try {
    if (window.__ton_city_kick_fired) return;
    window.__ton_city_kick_fired = true;
  } catch (_) { /* noop */ }
  try { localStorage.removeItem('token'); } catch (_) {}
  try { localStorage.removeItem('ton_city_token'); } catch (_) {}
  // Session was overridden by a login on another device. We simply drop the
  // local session and let the app fall back to the guest/landing view. We DO
  // NOT reload, redirect or auto re-authenticate here — that is exactly what
  // created the infinite kick loop between two devices. The user can re-open
  // (Telegram auto-logs back in on the next open, "last device wins").
  try {
    toast.error('Вы вошли с другого устройства — сессия здесь закрыта', { duration: 5000 });
  } catch (_) {}
  try { window.dispatchEvent(new CustomEvent('ton-city-session-overridden')); } catch (_) {}
}

// Detect a Cloudflare "Checking your browser" / managed-challenge response.
// Our API always answers JSON; an HTML body (or the `cf-mitigated: challenge`
// header) on a 403/429/503 means Cloudflare intercepted the XHR — the session
// is NOT dead. Treat it as "need to re-verify the browser", never as a logout.
function isCloudflareChallenge(res) {
  try {
    if (!res) return false;
    // ТОЛЬКО явный заголовок настоящего CF-челленджа. Раньше сюда попадали
    // любые 403/429/503 c text/html (например, страницы ошибок прокси при
    // плохой связи), из-за чего приложение делало window.location.reload() и
    // выбрасывало пользователя на карту. Теперь перезагрузка только на реальный
    // CF-challenge — на плохой связи checkAuth просто тихо повторит запрос.
    if ((res.headers.get('cf-mitigated') || '').toLowerCase() === 'challenge') return true;
  } catch (_) { /* noop */ }
  return false;
}
axios.interceptors.response.use(
  (r) => r,
  async (error) => {
    try {
      const status = error?.response?.status;
      const detail = error?.response?.data?.detail;

      // Admin 2FA gate — prompt for TOTP and retry with header
      if (status === 401 && typeof detail === 'string' &&
          (detail === 'TOTP required for this admin action' || detail === 'Invalid TOTP code')) {
        const cfg = error.config || {};
        cfg._totpAttempts = (cfg._totpAttempts || 0) + 1;
        if (cfg._totpAttempts <= 2) {
          const promptMsg = detail === 'Invalid TOTP code'
            ? 'Неверный код 2FA. Введите 6-значный код из приложения TOTP:'
            : 'Требуется код 2FA. Введите 6-значный код из приложения TOTP:';
          // eslint-disable-next-line no-alert
          const code = typeof window !== 'undefined' ? window.prompt(promptMsg) : null;
          if (code && /^\d{4,10}$/.test(code.trim())) {
            cfg.headers = { ...(cfg.headers || {}), 'X-Admin-TOTP': code.trim() };
            return axios(cfg);
          }
          // If the user cancelled or entered garbage, fall through to error.
        }
      }

      if (status === 401 && (detail === 'SESSION_OVERRIDDEN' || detail === 'session_invalidated') && !_sessionKickInFlight) {
        // Suppress residual 401s from in-flight requests right after a
        // successful login (they carry the OLD token/sid) and skip if we
        // already fired the kick UX from any other spot.
        if (_isKickSuppressed()) {
          return Promise.reject(error);
        }
        _sessionKickInFlight = true;
        // Guard against FALSE kicks: a request that was already in-flight with
        // an OLD token during a login transition can 401 even though the token
        // now in localStorage is perfectly valid. Re-validate the CURRENT token
        // before nuking the session — only kick if it too is invalid.
        (async () => {
          try {
            const curTok = localStorage.getItem('token');
            if (curTok) {
              const check = await fetch(`${BACKEND_URL}/api/auth/me`, {
                headers: { Authorization: `Bearer ${curTok}` },
                cache: 'no-store',
              });
              if (check.ok) {
                // Current token is valid → it was a stale in-flight request.
                _sessionKickInFlight = false;
                return;
              }
            }
          } catch (_) { /* fall through to kick */ }
          // Re-check suppression before firing (another call may have logged
          // in during the async re-validation above).
          if (!_isKickSuppressed()) {
            _fireKickUXOnce();
          }
          _sessionKickInFlight = false;
        })();
      }
    } catch (_) {}
    return Promise.reject(error);
  }
);

// ─── WalletSync ──────────────────────────────────────────────────────────────
// Источник правды для статуса привязки кошелька — это активная TonConnect-сессия
// в этом браузере. Если пользователь отозвал доступ через свой Wallet-app, в БД
// `wallet_address` остаётся, но `useTonWallet()` возвращает null. Чтобы UI на
// каждой странице (модалка депозита, настройки) показывал одно и то же
// состояние "никаких кошельков не привязано" — мы автоматически дёргаем
// /api/auth/unlink-wallet, как только убедились, что TonConnect восстановил
// своё состояние из localStorage и кошелька там действительно нет.
function WalletSync({ user, setUser }) {
  // v2.3.x (wallet-auth fix): AUTO-UNLINK DISABLED.
  // Previously this component auto-called /api/auth/unlink-wallet whenever the
  // TonConnect session wasn't restored on page load. That spontaneously freed
  // wallets from accounts, which caused duplicate users and "logged into the
  // wrong account" bugs. Unlinking is now ONLY an explicit user action
  // (Settings → «Отвязать кошелёк»).
  return null;
}

// v2.3.x — guest access guard for authenticated-only pages.
// Prevents anyone who has NOT signed in from opening deep-link URLs like
// /ton-island directly (previously guests could see the whole map + the
// list of players on it just by pasting the URL). We wait until the
// initial /auth/me revalidation resolves (`authResolving===false`) so we
// don't briefly flash the redirect on a page refresh with a valid session.
function RequireAuth({ user, authResolving, children }) {
  if (authResolving) return null;
  if (!user) return <Navigate to="/" replace />;
  return children;
}

/** A logged-in player opening the app lands on «Мои бизнесы» right away — the redirect
 *  happens UNDER the preloader, so the loader fades straight into the businesses page.
 *  Not for guests and not when the link carries something to handle (referral, Telegram start param). */
function BootToBusinesses({ user }) {
  const navigate = useNavigate();
  const location = useLocation();
  const done = useRef(false);
  useEffect(() => {
    if (done.current) return;
    done.current = true;
    const q = new URLSearchParams(location.search);
    const deepLink = q.has('ref') || q.has('startapp') || q.has('start') || /tgWebAppStartParam=[^&]+/.test(location.hash || '');
    if (user && location.pathname === '/' && !deepLink) navigate('/my-businesses', { replace: true });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}

function App() {
  const [user, setUser] = useState(null);
  // When a Telegram identity opens the app but isn't linked to any account,
  // we show a "create new / link existing" choice. null = hidden.
  const [tgChoice, setTgChoice] = useState(null);

  // Keep the unified GRAM CITY preloader mounted until it has finished its
  // fade-out (set by GramCityLoader.onDone), independently of authResolving.
  const [bootDone, setBootDone] = useState(false);

  // Latest values as refs so the cold-start retry loop can read them without
  // being re-created on every render.
  const userRef = useRef(null);
  const tgChoiceRef = useRef(null);
  useEffect(() => { userRef.current = user; }, [user]);
  useEffect(() => { tgChoiceRef.current = tgChoice; }, [tgChoice]);

  // After a demo/real switch the page reloads; show the queued localized toast.
  useEffect(() => {
    try {
      const pending = localStorage.getItem('ton_city_mode_toast');
      if (pending) {
        localStorage.removeItem('ton_city_mode_toast');
        const lang = localStorage.getItem('ton_city_lang') || 'en';
        const dict = translations[lang] || translations.en;
        const key = pending === 'demo' ? 'demoModeSwitchToast' : 'realModeSwitchToast';
        const msg = dict[key] || translations.en[key];
        setTimeout(() => toast.info(msg), 300);
      }
    } catch (e) { /* ignore */ }
  }, []);

  // Meta Pixel loads lazily on the first user gesture (see loadPixel.js) so the
  // cold start has zero third-party requests before the user interacts.
  useEffect(() => {
    setupDeferredPixel();
  }, []);

  // Presence heartbeat — powers the admin "Online now" counter. Sends every
  // 60s while logged in, tagging the source so web vs Telegram mini-app users
  // are counted separately. Telegram mini app is detected via WebApp.initData.
  useEffect(() => {
    if (!user) return;
    const isTelegram = looksLikeTelegramEnv();
    const source = isTelegram ? 'telegram' : 'web';
    const beat = () => {
      try {
        const token = localStorage.getItem('token') || localStorage.getItem('ton_city_token');
        if (!token) return;
        axios.post(`${BACKEND_URL}/api/stats/heartbeat`, { source },
          { headers: { Authorization: `Bearer ${token}` } }).catch(() => {});
      } catch (_) { /* ignore */ }
    };
    beat();
    const iv = setInterval(beat, 60000);
    return () => clearInterval(iv);
  }, [user]);

  // Show a preloader (instead of flashing the guest landing) while the FIRST
  // session re-validation is in flight — when a token exists OR we're inside a
  // Telegram Mini App (seamless auto-login is about to run).
  const [authResolving, setAuthResolving] = useState(() => {
    try {
      // Show the preloader (instead of the guest landing) when a seamless
      // auto-login / session re-validation is about to run:
      //   • Telegram Mini App (auto-login), OR
      //   • plain browser that already holds a token (hard-refresh of a
      //     protected route). A guest / fraud scanner has NO token, so it
      //     still renders the landing instantly with zero network.
      const hasToken = !!(localStorage.getItem('token') || localStorage.getItem('ton_city_token'));
      return looksLikeTelegramEnv() || hasToken;
    } catch (_) { return false; }
  });

  // Capture the referral code from the URL (?ref=USER_ID) exactly once and
  // persist it until registration. It is bound to the account permanently on
  // the backend and never re-read/overwritten afterwards.
  useEffect(() => {
    try {
      const params = new URLSearchParams(window.location.search);
      // Web referral: ?ref=USER_ID
      let ref = params.get('ref');
      // Telegram Mini App referral: link is t.me/Bot/app?startapp=USER_ID, which
      // Telegram passes to the app as initDataUnsafe.start_param (also mirrored
      // to the ?tgWebAppStartParam= query on web launches).
      if (!ref || !ref.trim()) {
        const tgStart = window.Telegram?.WebApp?.initDataUnsafe?.start_param
          || params.get('tgWebAppStartParam')
          || params.get('startapp');
        if (tgStart && String(tgStart).trim()) ref = String(tgStart).trim();
      }
      if (ref && ref.trim()) {
        ref = ref.trim();
        if (!localStorage.getItem('ref_code')) localStorage.setItem('ref_code', ref);
        // Count a RAW click/open of the partner link (anonymous + repeat opens).
        // Deferred to the first gesture in a plain browser so cold start stays
        // silent; fired immediately inside Telegram (real session, no gesture).
        const firePartnerClick = () => {
          fetch(`${BACKEND_URL}/api/partner/click`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ref }),
          }).catch(() => {});
        };
        const inTg = looksLikeTelegramEnv();
        if (inTg) firePartnerClick();
        else onFirstGesture(firePartnerClick);
      }
    } catch (_) { /* noop */ }
  }, []);

  // Once authenticated, bind an EXISTING user to the partner (if not bound yet).
  // New users are already bound at registration; this covers users who were
  // already in the project and opened the app via a partner link.
  useEffect(() => {
    if (!user) return;
    const ref = localStorage.getItem('ref_code');
    if (!ref || localStorage.getItem('partner_bind_done') === '1') return;
    const token = localStorage.getItem('token');
    if (!token) return;
    localStorage.setItem('partner_bind_done', '1');
    fetch(`${BACKEND_URL}/api/partner/bind`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ ref }),
    }).catch(() => { localStorage.removeItem('partner_bind_done'); });
  }, [user]);
  
  // Function to refresh user balance from server (called only after user actions)
  const refreshBalance = useCallback(async () => {
    const token = localStorage.getItem('token');
    if (!token) return;
    
    try {
      const res = await fetch(`${BACKEND_URL}/api/auth/me`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      
      if (res.ok) {
        const data = await res.json();
        setUser(prev => prev ? { 
          ...prev, 
          balance_ton: data.balance_ton, 
          bonus_balance: data.bonus_balance,
          plots_owned: data.plots_owned,
          businesses_owned: data.businesses_owned,
          // the alliance shown in the header / chat (changes on the «Альянс» tab)
          alliance_id: data.alliance_id, alliance_name: data.alliance_name,
          alliance_tag: data.alliance_tag, alliance_emblem: data.alliance_emblem,
          avatar: data.avatar,                                // e.g. the Telegram photo set in the background
        } : data);
      }
    } catch (e) {
      // refreshBalance is a background poll — swallow silently
    }
  }, []);
  
  // Function to update balance directly (for immediate optimistic updates)
  const updateBalance = useCallback((newBalance, newBonusBalance) => {
    setUser(prev => prev ? {
      ...prev,
      balance_ton: newBalance,
      ...(newBonusBalance !== undefined && newBonusBalance !== null ? { bonus_balance: newBonusBalance } : {}),
    } : prev);
    // Бонусный баланс мог измениться (сплит-оплата) — досинхронизируем с сервером.
    if (newBonusBalance === undefined || newBonusBalance === null) refreshBalance();
  }, [refreshBalance]);

  // Listen for global balance updates (from WithdrawModal, DepositModal, etc.)
  useEffect(() => {
    const handleBalanceUpdate = (e) => {
      if (e.detail?.balance !== undefined) {
        setUser(prev => prev ? { ...prev, balance_ton: e.detail.balance, ...(e.detail.bonus_balance !== undefined ? { bonus_balance: e.detail.bonus_balance } : {}) } : prev);
      }
    };
    window.addEventListener('balanceUpdate', handleBalanceUpdate);
    return () => window.removeEventListener('balanceUpdate', handleBalanceUpdate);
  }, []);

  const checkAuth = async () => {
    let token = localStorage.getItem('token');
    // Set to a route ('/maps' or '/tutorial') when THIS load performed a
    // seamless Telegram Mini App auto-login, so we can jump into the game.
    let _tgAutoLoginRedirect = null;

    // Seamless Telegram Mini App auth. Inside Telegram the CURRENT Telegram
    // identity is authoritative — we validate it FIRST, even if a stale token
    // from a previous/other account is still in localStorage. Otherwise a
    // leftover token would hijack the session and a brand-new Telegram account
    // would never be offered the create/link choice.
    //   • linked account   → fresh token, log in.
    //   • unlinked Telegram → backend returns choice_required → show the
    //     "create new / link existing" modal (NEVER auto-create).
    const inTgMiniApp = looksLikeTelegramEnv();

    // Support-agent panel guard: the agent opens `/sys-ops-panel-...` (optionally
    // with a one-time `?login_token=`) sometimes from inside Telegram. The
    // seamless Telegram Mini App auto-login below would otherwise log the AGENT
    // in as their own PLAYER account and redirect into the game. On the agent
    // panel (or whenever a login_token is present) we skip the player auto-login
    // entirely and let SupportAgentPage's own login gate handle agent auth.
    let suppressTgLogin = false;
    try {
      const _p = (typeof window !== 'undefined' && window.location.pathname) || '';
      const _hasLoginToken = new URLSearchParams(window.location.search).has('login_token');
      suppressTgLogin = _p.startsWith('/sys-ops-panel') || _hasLoginToken;
    } catch (_) { suppressTgLogin = false; }


    // If it's left over anywhere else (abandoned link flow), it would wrongly
    // suppress the choice modal forever — so treat it as one-shot there.
    let linkIntent = false;
    try { linkIntent = sessionStorage.getItem('tg_link_intent') === '1'; } catch (_) {}
    const onAuthPage = (typeof window !== 'undefined' && window.location.pathname === '/auth');
    if (linkIntent && !onAuthPage) {
      try { sessionStorage.removeItem('tg_link_intent'); } catch (_) {}
      linkIntent = false;
    }

    if (inTgMiniApp && !linkIntent && !suppressTgLogin) {
      const r = await telegramMiniAppLogin();
      if (r?.status === 'choice_required') {
        // Unlinked Telegram identity is authoritative here — drop any stale
        // leftover token so it can't hijack the session, and offer the choice.
        try { localStorage.removeItem('token'); localStorage.removeItem('ton_city_token'); } catch (_) {}
        setTgChoice(r.telegram || {});
        setUser(null);
        return;
      }
      if (r?.status === 'ok' && r.token) {
        token = r.token;
        // Remember that THIS load is a seamless Telegram auto-login so we can
        // redirect straight into the game once the user is hydrated below.
        // New signups start the tutorial; existing users go to the GRAM island.
        _tgAutoLoginRedirect = r.isNewSignup ? '/tutorial' : '/ton-island';
      }
      // r === null → fall through and try the stored token (resilient).
    }

    if (!token) {
      setUser(null);
      return;
    }

    // Resilience: behind Cloudflare with aggressive rate-limit rules the
    // /api/auth/me call on a hard refresh can transiently return 429 or 5xx.
    // The OLD code immediately wiped the token in that case → on the second
    // refresh the user got kicked back to the landing page (issue #2).
    // We retry up to 3× on transient errors and ONLY clear the token on a
    // genuine 401/403 from the server.
    const isTransient = (status) => status === 429 || (status >= 500 && status <= 599);

    let res = null;
    let networkError = false;
    for (let attempt = 0; attempt < 3; attempt += 1) {
      networkError = false;
      try {
        res = await fetch(`${BACKEND_URL}/api/auth/me`, {
          headers: { 'Authorization': `Bearer ${token}` },
          cache: 'no-store',
        });
        
        if (res.ok) break;
        if (!isTransient(res.status)) break;
      } catch (e) {
        networkError = true;
        
      }      // exponential backoff with jitter
      const delay = 400 * Math.pow(2, attempt) + Math.floor(Math.random() * 200);
      await new Promise(r => setTimeout(r, delay));
    }

    if (res && res.ok) {
      try {
        const data = await res.json();
        window.__ton_city_kick_fired = false;
        
        setUser(data);
        // Seamless Telegram auto-login → jump straight into the game. New
        // signups start the tutorial; returning users open the GRAM island.
        // We push BEFORE the router mounts (authResolving flips to false right
        // after checkAuth resolves), so BrowserRouter reads the new path on
        // its first render and renders the game instead of the landing page.
        if (_tgAutoLoginRedirect && typeof window !== 'undefined') {
          const p = window.location.pathname;
          if (p === '/' || p === '' || p === '/auth') {
            try {
              window.history.replaceState({}, '', _tgAutoLoginRedirect);
              window.dispatchEvent(new PopStateEvent('popstate'));
            } catch (_) { /* noop */ }
          }
        }
      } catch (_) {
        // Keep the previous user — don't crash the app on a parsing glitch.
      }
      return 'ok';
    }

    // Cloudflare browser-challenge — DON'T treat it as a logout. Reload once
    // so CF can verify the browser and refresh its clearance cookie; we come
    // back with the SAME (still-valid, 365-day) token and stay logged in.
    if (res && isCloudflareChallenge(res)) {
      try {
        const now = Date.now();
        const last = Number(sessionStorage.getItem('cf_reload_at') || 0);
        if (now - last > 20000) {
          sessionStorage.setItem('cf_reload_at', String(now));
          window.location.reload();
          return 'reloading';
        }
      } catch (_) { /* noop */ }
      // Reloaded very recently and still challenged — keep the token, bail
      // quietly; the next interaction/poll retries once CF settles.
      return;
    }

    // Genuine auth failure: clear the token.
    if (res && (res.status === 401 || res.status === 403)) {
      let kicked = false;
      let _detail = '';
      try { const j = await res.clone().json(); _detail = j?.detail; kicked = (j?.detail === 'SESSION_OVERRIDDEN' || j?.detail === 'session_invalidated'); } catch (_) {}
      
      if (kicked && !_isKickSuppressed()) {
        // Route the kick through the shared one-shot handler so we don't
        // fire duplicate toasts when the axios interceptor also observes
        // session_invalidated for a parallel request.
        _fireKickUXOnce();
        setUser(null);
        return;
      }
      localStorage.removeItem('token');
      localStorage.removeItem('ton_city_token');
      setUser(null);
      return;
    }

    // Transient failure (429 / 5xx / network) — do NOT clear the token.
    // We keep `user` at its current value (null on first load, populated on
    // re-renders). The next user interaction or scheduled refresh will retry.
    if (networkError) {
      
      _lastAuthError = { where: 'GET /api/auth/me', status: 'network-error', detail: '' };
    } else if (res) {
      let _detail = '';
      try { const j = await res.clone().json(); _detail = (j && (j.detail || j.message)) || ''; } catch (_) {}
      
      _lastAuthError = { where: 'GET /api/auth/me', status: res.status, detail: _detail };
    }
  };

  const handleLogout = () => {
    localStorage.removeItem('token');
    localStorage.removeItem('ton_city_token');
    // Bag #2: fully drop the TonConnect session so the wallet does NOT
    // auto-reconnect on the next visit to /auth. Clear the SDK's own storage
    // keys + our explicit-intent flag.
    try {
      Object.keys(localStorage)
        .filter((k) => k.startsWith('ton-connect') || k.startsWith('tonconnect'))
        .forEach((k) => localStorage.removeItem(k));
    } catch (_) { /* noop */ }
    try { sessionStorage.removeItem('ton_wallet_auth_intent'); } catch (_) { /* noop */ }
    setUser(null);
  };

  // A Telegram button flow (AuthPage) can request the choice modal too.
  useEffect(() => {
    const onChoice = (e) => setTgChoice((e && e.detail && e.detail.telegram) || {});
    window.addEventListener('tg-choice-required', onChoice);
    return () => window.removeEventListener('tg-choice-required', onChoice);
  }, []);

  // User chose "Create new account" in the Telegram choice modal.
  const handleTgCreateNew = useCallback(async () => {
    const tok = await telegramMiniAppCreate();
    if (tok) {
      setTgChoice(null);
      window.__ton_city_kick_fired = false;
      setAuthResolving(true);
      await checkAuth();
      setAuthResolving(false);
      if (typeof window !== 'undefined' && window.location.pathname === '/') {
        window.history.pushState({}, '', '/tutorial');
        window.dispatchEvent(new PopStateEvent('popstate'));
      }
      return;
    }
    toast.error('Не удалось создать аккаунт. Попробуйте ещё раз.');
  }, []);

  // User chose "Link to existing account" → go to the login screen. Set an
  // intent flag so the Telegram auto-login/choice does NOT re-fire on that page
  // load; the user logs in first, then useTelegramAutoLink attaches Telegram.
  const handleTgLinkExisting = useCallback(() => {
    setTgChoice(null);
    try { sessionStorage.setItem('tg_link_intent', '1'); } catch (_) {}
    if (typeof window !== 'undefined') window.location.assign('/auth?tglink=1');
  }, []);

  useEffect(() => {
    // Magic-link from Telegram bot: ?auth=<jwt> → save token then strip from URL
    try {
      const params = new URLSearchParams(window.location.search);
      const authT = params.get('auth');
      if (authT) {
        localStorage.setItem('token', authT);
        params.delete('auth');
      }
      // Persist support open flag across redirects
      if (params.get('support') === 'open') {
        sessionStorage.setItem('open_support_modal', '1');
        params.delete('support');
      }
      // Language coming from the Telegram bot (?lang=xx) — set the app language
      // so the support window (and the whole UI) is shown in that language.
      const langParam = params.get('lang');
      const SUPPORTED_LANGS = ['ru', 'en', 'es', 'zh', 'fr', 'de', 'ja', 'ko'];
      if (langParam && SUPPORTED_LANGS.includes(langParam)) {
        try { localStorage.setItem('ton_city_lang', langParam); } catch (e) { /* ignore */ }
        params.delete('lang');
      }
      const qs = params.toString();
      const newUrl = window.location.pathname + (qs ? `?${qs}` : '') + window.location.hash;
      window.history.replaceState({}, '', newUrl);
    } catch (e) { /* ignore */ }

    // ── COLD-START NETWORK POLICY ──────────────────────────────────────────
    // Determine the environment LOCALLY (zero network). Optimistic Telegram
    // detection: presence of the WebApp object (initData may still be filling
    // in). checkAuth() → telegramMiniAppLogin() awaits waitForTelegramInitData()
    // before firing, so a late-arriving initData is handled instead of the user
    // being wrongly treated as a plain-browser visitor.
    const isInsideTelegram = looksLikeTelegramEnv();

    const hasTokenNow = () => {
      try {
        return !!(localStorage.getItem('token') || localStorage.getItem('ton_city_token'));
      } catch (_) { return false; }
    };

    // Resolve the session while KEEPING the preloader up on flaky networks.
    // Instead of giving up (which used to bounce the user to the guest landing
    // and surface "loading error" toasts), we keep retrying in the background.
    // checkAuth() only clears the token on a genuine 401/403, so
    // "token still present + user still null" reliably means a transient
    // network / 429 / 5xx blip → keep loading until it succeeds.
    const resolveSessionWithRetries = async () => {
      
      // i18n helper for the "still loading / failed" notifications.
      const _lang = (() => { try { return localStorage.getItem('ton_city_lang') || 'en'; } catch (_) { return 'en'; } })();
      const _msg = (ru, en) => (_lang === 'ru' ? ru : en);
      let transientFails = 0;
      let warnedSlow = false;
      for (let attempt = 0; attempt < 40; attempt += 1) {
        let r;
        try {
          r = await checkAuth();
        } catch (e) {
          r = undefined; // network error inside checkAuth → treat as transient
          
        }
        
        // CF browser-challenge → checkAuth() triggered a one-shot reload.
        if (r === 'reloading') return;
        // Success: the user is hydrated.
        if (r === 'ok' || userRef.current) {  break; }
        // A Telegram "create / link" choice is being shown → stop, wait on user.
        if (tgChoiceRef.current) {  break; }
        // No token left → guest, or a genuine auth failure cleared it → stop.
        if (!hasTokenNow()) {  break; }
        // Transient failure — wait (capped backoff) and keep the loader up.
        transientFails += 1;
        // After a few consecutive transient failures the loader would appear to
        // "hang" at 99%. Surface a one-time notification so the user knows the
        // app is still trying (instead of silently spinning forever).
        if (transientFails >= 4 && !warnedSlow) {
          warnedSlow = true;
          const _e = _lastAuthError || {};
          const _detailStr = `${_e.where || ''}${_e.status ? ` — ${_msg('код', 'status')} ${_e.status}` : ''}${_e.detail ? `: ${_e.detail}` : ''}`;
          try {
            toast.error(
              _msg(
                `Не удаётся загрузить данные аккаунта (${_detailStr}). Продолжаем попытки…`,
                `Trouble loading your account data (${_detailStr}). Still retrying…`
              ),
              { duration: 7000 }
            );
          } catch (_) { /* noop */ }
        }
        const delay = Math.min(6000, 1000 + attempt * 800);
        
        await new Promise((res) => setTimeout(res, delay));
      }
      // If we exhausted every retry and the user is STILL not hydrated while a
      // token is present, the backend kept failing (persistent 5xx). Stop the
      // endless "99%" spinner and tell the user clearly WHAT failed + retry hint.
      if (!userRef.current && hasTokenNow()) {
        
      }
      
      setAuthResolving(false);
    };

    if (isInsideTelegram) {
      // Telegram Mini App: the ONE allowed automatic request runs inside
      // checkAuth() → POST /api/auth/telegram/miniapp. Seamless auto-login.
      resolveSessionWithRetries();
    } else {
      // Plain browser / Safari fraud scanner.
      // • GUEST (no token): ABSOLUTELY NO network on cold start. Render the
      //   landing immediately — a scanner never interacts, so it stays silent.
      // • AUTHENTICATED (token present): a real user hard-refreshing a page.
      //   Hydrate the session NOW (not on a deferred gesture) so protected
      //   routes don't flash the guest landing and bounce the user to "/".
      //   Fraud scanners never carry a token, so this keeps them network-free.
      if (hasTokenNow()) {
        resolveSessionWithRetries();
      } else {
        setAuthResolving(false);
      }
    }
    // ───────────────────────────────────────────────────────────────────────

    // Слушатель на изменение localStorage
    const handleStorageChange = (e) => {
      if (e.key === 'token') {
        checkAuth();
      }
    };
    
    window.addEventListener('storage', handleStorageChange);
    
    return () => {
      window.removeEventListener('storage', handleStorageChange);
    };
  }, []);

  // Suppress script errors that come from external sources (CORS issues)
  useEffect(() => {
    const handleError = (event) => {
      // Suppress "Script error." which comes from cross-origin scripts.
      // We do NOT log anything here — the original warn was developer-only
      // noise that ended up visible in the user's DevTools.
      if (event.message === 'Script error.' || event.message?.includes('Script error')) {
        event.preventDefault();
        return true;
      }
    };

    window.addEventListener('error', handleError);
    return () => window.removeEventListener('error', handleError);
  }, []);

  return (
    <LazyTonProvider manifestUrl={manifestUrl}>
      <WalletSync user={user} setUser={setUser} />
      <LanguageProvider user={user}>
        <div className="App min-h-screen bg-void">
          <div className="noise-overlay" />
          
          {/* Maintenance Overlay - shows for all users except admins (checked inside component) */}
          <MaintenanceOverlay />
          
          {/* Blocked User Overlay */}
          <BlockedOverlay user={user} />
          
          {/* Unified GRAM CITY preloader — stays until the app is 100% ready.
              It sits ON TOP of the router (which mounts underneath once auth
              resolves), so there is never a "loader on top of a loader" and no
              page reload / "loading error" flash on flaky connections. */}
          {!bootDone && (
            <GramCityLoader resolving={authResolving} onDone={() => setBootDone(true)} />
          )}

          {!authResolving && (
          <BrowserRouter>
            {/* Living background (inside the router: softer, more blurred on some pages) */}
            <CityBackground />
            <BootToBusinesses user={user} />
            <QuestHighlighter />
            <TelegramBridge />
            <TutorialProvider user={user}>
              {/* Global low-durability alert banner (<20%) */}
              <DurabilityBanner user={user} />

              {/* Referral Rally promo modal (shows once/day when campaign active) */}
              {user && <ReferralRallyModal user={user} />}

              {/* Mobile Bottom Navigation */}
              <BottomNav user={user} />

              {/* Tutorial overlays */}
              <TutorialStartModal />
              <TutorialTour />
              <TutorialFinishConfirm />
              <TutorialCompletedModal />
              <TutorialAbandonConfirm />

              <Suspense fallback={<div className="min-h-screen flex items-center justify-center"><div className="w-10 h-10 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin" /></div>}>
              <Routes>
                <Route path="/" element={<LandingPage user={user} setUser={setUser} />} />
                <Route path="/auth" element={<AuthPage setUser={setUser} onAuthSuccess={checkAuth} />} />
                <Route path="/auth/google/callback" element={<GoogleCallback setUser={setUser} onAuthSuccess={checkAuth} />} />
                <Route path="/forgot-password" element={<ForgotPasswordPage />} />
                <Route path="/ton-island" element={<RequireAuth user={user} authResolving={authResolving}><TonIslandPage user={user} refreshBalance={refreshBalance} updateBalance={updateBalance} /></RequireAuth>} />
                {/* Список городов */}
                <Route path="/maps" element={<RequireAuth user={user} authResolving={authResolving}><MapPage user={user} /></RequireAuth>} />
                {/* Legacy aliases */}
                <Route path="/map" element={<Navigate to="/maps" replace />} />
                <Route path="/island" element={<Navigate to="/ton-island" replace />} />
                <Route path="/game" element={<Navigate to="/maps" replace />} />
                {/* Старая «другая карта» удалена — любой /game/:cityId уходит в список */}
                <Route path="/game/:cityId" element={<Navigate to="/maps" replace />} />
                <Route path="/dashboard" element={<RequireAuth user={user} authResolving={authResolving}><DashboardPage user={user} refreshBalance={refreshBalance} /></RequireAuth>} />
                <Route path={ADMIN_PATH} element={<RequireAuth user={user} authResolving={authResolving}><AdminPage user={user} /></RequireAuth>} />
                {/* Old predictable admin URL is dead — bounce to home */}
                <Route path="/admin" element={<Navigate to="/" replace />} />
                <Route path="/income-table" element={<RequireAuth user={user} authResolving={authResolving}><IncomeTablePage user={user} /></RequireAuth>} />
                <Route path="/calculator" element={<RequireAuth user={user} authResolving={authResolving}><IncomeTablePage user={user} /></RequireAuth>} />
                <Route path="/minigames/sorter" element={<RequireAuth user={user} authResolving={authResolving}><SorterGamePage user={user} /></RequireAuth>} />
                <Route path="/minigames/rewards" element={<RequireAuth user={user} authResolving={authResolving}><MinigameRewardsPage user={user} /></RequireAuth>} />
                <Route path="/trading" element={<RequireAuth user={user} authResolving={authResolving}><TradingPage user={user} refreshBalance={refreshBalance} updateBalance={updateBalance} /></RequireAuth>} />
                <Route path="/tasks" element={<RequireAuth user={user} authResolving={authResolving}><TasksPage user={user} refreshBalance={refreshBalance} /></RequireAuth>} />
                <Route path="/credit" element={<RequireAuth user={user} authResolving={authResolving}><CreditPage user={user} refreshBalance={refreshBalance} updateBalance={updateBalance} /></RequireAuth>} />
                <Route path="/marketplace" element={<RequireAuth user={user} authResolving={authResolving}><MarketplacePage user={user} refreshBalance={refreshBalance} updateBalance={updateBalance} /></RequireAuth>} />
                <Route path="/my-businesses" element={<RequireAuth user={user} authResolving={authResolving}><MyBusinessesPage user={user} refreshBalance={refreshBalance} updateBalance={updateBalance} /></RequireAuth>} />
                <Route path="/resources" element={<RequireAuth user={user} authResolving={authResolving}><ResourcesPage user={user} /></RequireAuth>} />
                <Route path="/leaderboard" element={<RequireAuth user={user} authResolving={authResolving}><LeaderboardPage user={user} /></RequireAuth>} />
                <Route path="/tutorial" element={<RequireAuth user={user} authResolving={authResolving}><TutorialPage user={user} /></RequireAuth>} />
                <Route path="/chat" element={<RequireAuth user={user} authResolving={authResolving}><ChatPage user={user} /></RequireAuth>} />
                <Route path="/community" element={<RequireAuth user={user} authResolving={authResolving}><CommunityPage user={user} refreshBalance={refreshBalance} /></RequireAuth>} />
                <Route path="/alliance" element={<RequireAuth user={user} authResolving={authResolving}><CommunityPage user={user} refreshBalance={refreshBalance} initialTab="alliance" /></RequireAuth>} />
                <Route path="/city-pass" element={<RequireAuth user={user} authResolving={authResolving}><CityPassPage user={user} refreshBalance={refreshBalance} /></RequireAuth>} />
                <Route path="/settings" element={<RequireAuth user={user} authResolving={authResolving}><SettingsPage user={user} setUser={setUser} onLogout={handleLogout} refreshBalance={refreshBalance} /></RequireAuth>} />
                <Route path="/security" element={<RequireAuth user={user} authResolving={authResolving}><SecurityPage user={user} /></RequireAuth>} />
                <Route path="/history" element={<RequireAuth user={user} authResolving={authResolving}><TransactionHistoryPage user={user} /></RequireAuth>} />
                <Route path="/terms" element={<TermsPage />} />
                <Route path="/privacy" element={<PrivacyPage />} />
                <Route path="/sys-ops-panel-x9k2m7q" element={<SupportAgentPage />} />
                <Route path="/support-only" element={<SupportOnlyPage />} />
                <Route path="/more" element={<RequireAuth user={user} authResolving={authResolving}><MorePage user={user} refreshBalance={refreshBalance} /></RequireAuth>} />
                <Route path="/roadmap" element={<RequireAuth user={user} authResolving={authResolving}><RoadmapPage user={user} /></RequireAuth>} />
                <Route path="/rules" element={<RequireAuth user={user} authResolving={authResolving}><RulesPage /></RequireAuth>} />
              </Routes>
              </Suspense>
            </TutorialProvider>
          </BrowserRouter>
          )}
          
          <Toaster position="bottom-right" theme="dark" closeButton richColors />
          <TelegramChoiceModal
            open={!!tgChoice}
            telegram={tgChoice || {}}
            onCreateNew={handleTgCreateNew}
            onLinkExisting={handleTgLinkExisting}
            lang={(typeof localStorage !== 'undefined' && localStorage.getItem('ton_city_lang')) || 'ru'}
          />
        </div>
      </LanguageProvider>
    </LazyTonProvider>
  );
}

export default App;
