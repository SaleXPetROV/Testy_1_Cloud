import { useState, useEffect, useMemo, useRef } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { TonConnectButton, useTonWallet, useTonConnectUI, useEnsureTonConnectUI } from '@/lib/tonconnect-lazy';
import { motion, AnimatePresence } from 'framer-motion';
import { Building2, ArrowLeft, Globe, UserCircle, Mail, Lock, Chrome, CheckCircle2, Eye, EyeOff, Wallet, Send } from 'lucide-react';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useTranslation, languages } from '@/lib/translations';
import { useLanguage } from '@/context/LanguageContext';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { toast } from 'sonner';
import { useMouseParallax } from '@/hooks/useMouseParallax';
import { formatErrorDetail } from '@/lib/apiErrors';
import { isPasswordStrong, PASSWORD_REQUIREMENTS_MSG } from '@/lib/passwordPolicy';
import { getFbCookies } from '@/lib/fbTracking';
import TelegramChoiceModal from '@/components/TelegramChoiceModal';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND_URL}/api`;

// Load Google Identity Services
const loadGoogleScript = () => {
  return new Promise((resolve) => {
    if (window.google) {
      resolve(window.google);
      return;
    }
    const script = document.createElement('script');
    script.src = 'https://accounts.google.com/gsi/client';
    script.async = true;
    script.defer = true;
    script.onload = () => resolve(window.google);
    document.head.appendChild(script);
  });
};

export default function AuthPage({ setUser, onAuthSuccess }) {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const wallet = useTonWallet();
  const [tonConnectUI] = useTonConnectUI();
  const ensureTonConnectUI = useEnsureTonConnectUI();
  const mode = searchParams.get('mode');
  const isRegister = mode === 'register';
  // When the user arrived here via the Telegram "Link to existing account"
  // choice, they must log in with another method (email/Google/wallet) so that
  // Telegram auto-links to that account. Hide the Telegram login button here.
  const tgLinkIntent = (() => {
    try {
      return searchParams.get('tglink') === '1' || sessionStorage.getItem('tg_link_intent') === '1';
    } catch (_) { return false; }
  })();
  const tiltRef = useMouseParallax({ max: 14, shift: 12, damp: 0.10 });

  // Mode-driven theme: cyan for login, purple for register.
  // Accent hex matches the crystal hologram exactly (--holo-1 in index.css),
  // so icons/buttons/links share the same hue as the 3D crystal.
  const accentHex = isRegister ? '#C29BFF' : '#22E2FF';
  const accentDeep = isRegister ? '#7A2EFF' : '#0098EA';
  
  const { language: lang, setLang } = useLanguage();
  const { t } = useTranslation(lang);
  const [isVerifying, setIsVerifying] = useState(false);
  // v2.2.X: once `finishAuth` has fired (token written to localStorage,
  // success toast shown, navigate('/ton-island') queued) — we must keep ALL
  // auth-trigger buttons (Войти / Зарегистрироваться / Google / Wallet /
  // verify-code) disabled forever for this render. Several handlers have
  // a `finally { setIsVerifying(false) }` that re-enables the button just
  // after the success toast appears but before navigation has actually
  // navigated, allowing the user to double-tap and trigger a second login.
  // Tracking this in a separate flag avoids touching every handler.
  const [authCompleted, setAuthCompleted] = useState(false);
  // Synchronous re-entrancy guard. React state-based `disabled` is async
  // (batched re-render on next tick), so a synchronous burst of clicks in
  // the same JS tick (e.g. `for (let i=0;i<5;i++) btn.click()`) can fire
  // multiple network requests before `isVerifying` ever reaches the DOM.
  // A `useRef` is updated synchronously and read at the very top of each
  // auth handler, hard-stopping duplicate work.
  const authBusyRef = useRef(false);
  // Synchronous guard specifically for the wallet-verify effect. React state
  // (`walletProcessed`) updates asynchronously, so two rapid effect runs (dep
  // change / StrictMode double-invoke / fast reconnect) can BOTH pass the
  // `if (walletProcessed) return` check and fire /auth/verify-wallet twice.
  // Each call rotates the server session → the token from the 1st call goes
  // stale → next request 401s with session_invalidated and kicks the user out
  // right after a successful login. A ref is updated synchronously and blocks
  // the duplicate immediately.
  const walletVerifyRef = useRef(false);

  // Auto-redirect already-authenticated visitors away from /auth straight
  // to GRAM Island — per UX request, the login screen should never be the
  // first thing a logged-in player sees.
  //
  // EXCEPTION (account switching on one device): if the URL explicitly asks
  // for the auth screen (?mode=login / ?mode=register / ?switch=1), the visit
  // is a DELIBERATE attempt to sign in with another method/wallet. In that
  // case we must NOT bounce them back to their current account — otherwise
  // connecting a different wallet is impossible without logging out first.
  useEffect(() => {
    try {
      let explicit = false;
      try {
        const p = new URLSearchParams(window.location.search);
        explicit = p.has('mode') || p.get('switch') === '1' ||
                   p.get('reason') === 'session_invalidated';
      } catch (_) { /* noop */ }
      if (explicit) return;
      const token = localStorage.getItem('token') || localStorage.getItem('ton_city_token');
      if (token) {
        navigate('/ton-island', { replace: true });
      }
    } catch (e) { /* noop */ }
  }, [navigate]);

  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  // Agreement checkbox removed — consent is implicit via the text below the Create Account button.
  
  // Email verification states
  const [showVerificationStep, setShowVerificationStep] = useState(false);
  const [verificationCode, setVerificationCode] = useState('');
  const [pendingEmail, setPendingEmail] = useState('');

  // Email-based login 2FA states (separate from TOTP show2FAStep below).
  // After password is verified, backend sends a code to the user's email; the
  // user enters it here to complete sign-in.
  const [showLoginCodeStep, setShowLoginCodeStep] = useState(false);
  const [loginCode, setLoginCode] = useState('');
  
  // 2FA states
  const [show2FAStep, setShow2FAStep] = useState(false);
  const [totpCode, setTotpCode] = useState('');
  const [pending2FAEmail, setPending2FAEmail] = useState('');
  const [pending2FAPassword, setPending2FAPassword] = useState('');
  const [useBackupCode, setUseBackupCode] = useState(false); // Toggle for backup code input
  // When TRUE, the 2FA prompt was triggered by a wallet-connect flow, so
  // `handle2FALogin` must re-submit to /auth/verify-wallet with `totp_code`
  // instead of the email/password path.
  const [walletPending2FA, setWalletPending2FA] = useState(false);
  
  const [showUsernameStep, setShowUsernameStep] = useState(false);
  // Wallet address PINNED at the moment the server returned need_username.
  // We use this snapshot for the final /auth/verify-wallet submission (with
  // the nickname) instead of re-reading `wallet.account.address` — the
  // TonConnect wallet can silently re-attach to a DIFFERENT session between
  // the two calls (browser auto-reconnect on tab focus, user switching
  // wallets in the wallet app mid-flow, etc.), which would otherwise cause
  // the second call to hit a completely different account.
  const [pendingWalletAddress, setPendingWalletAddress] = useState('');
  const [googleLoaded, setGoogleLoaded] = useState(false);

  // Memoise the heavy crystal hologram SVG: it only depends on `mode` (cyan
  // vs purple theme + register-only forging beams). Without this, every
  // keystroke in the email/password inputs re-rendered the entire SVG tree
  // (~100 nodes with filters/gradients), which made the hologram visibly
  // judder. Memoising drops re-renders to zero during typing.
  const crystalSvg = useMemo(() => (
    <svg viewBox="0 0 400 400" className="holo-svg" aria-hidden>
      <defs>
        <linearGradient id="crystalFront" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%"  stopColor="var(--holo-1)" stopOpacity="0.90" />
          <stop offset="55%" stopColor="var(--holo-1)" stopOpacity="0.45" />
          <stop offset="100%" stopColor="var(--holo-2)" stopOpacity="0.20" />
        </linearGradient>
        <linearGradient id="crystalSide" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%"  stopColor="var(--holo-2)" stopOpacity="0.85" />
          <stop offset="100%" stopColor="var(--holo-1)" stopOpacity="0.15" />
        </linearGradient>
        <linearGradient id="crystalGlow" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%"  stopColor="#FFFFFF" stopOpacity="0.6" />
          <stop offset="100%" stopColor="var(--holo-1)" stopOpacity="0.0" />
        </linearGradient>
        <radialGradient id="crystalCore" cx="50%" cy="50%" r="50%">
          <stop offset="0%"  stopColor="#FFFFFF" stopOpacity="0.95" />
          <stop offset="40%" stopColor="var(--holo-1)" stopOpacity="0.7" />
          <stop offset="100%" stopColor="var(--holo-1)" stopOpacity="0.0" />
        </radialGradient>
        <filter id="cryGlow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="2.4" result="b"/>
          <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>
      </defs>

      <g fill="none" stroke="var(--holo-1)" strokeWidth="1" opacity="0.8">
        <path d="M20 20 L20 40 M20 20 L40 20" />
        <path d="M380 20 L380 40 M380 20 L360 20" />
        <path d="M20 380 L20 360 M20 380 L40 380" />
        <path d="M380 380 L380 360 M380 380 L360 380" />
      </g>
      <g fontFamily="JetBrains Mono, monospace" fontSize="8" fill="var(--holo-1)" opacity="0.75" letterSpacing="1.5">
        <text x="48" y="32">{mode === 'register' ? 'TON.CRYSTAL' : 'TON.CORE'}</text>
        <text x="318" y="32">{mode === 'register' ? 'FORGING' : 'ACTIVE'}</text>
        <text x="48"  y="376">FREQ 432.0 HZ</text>
        <text x="298" y="376">∆ STABLE</text>
      </g>

      <g style={{ transformOrigin: '200px 200px' }} className="globe-orbit-slow">
        <ellipse cx="200" cy="200" rx="155" ry="40" fill="none" stroke="var(--holo-1)" strokeWidth="0.8" opacity="0.55" strokeDasharray="6 5" />
      </g>
      <g style={{ transformOrigin: '200px 200px' }} className="globe-orbit-rev">
        <ellipse cx="200" cy="200" rx="170" ry="50" fill="none" stroke="var(--holo-2)" strokeWidth="0.7" opacity="0.5" strokeDasharray="3 6" transform="rotate(35 200 200)" />
      </g>
      <g style={{ transformOrigin: '200px 200px' }} className="globe-orbit-slow">
        <circle cx="200" cy="200" r="180" fill="none" stroke="var(--holo-1)" strokeWidth="0.5" opacity="0.25" strokeDasharray="2 8" />
      </g>

      <circle cx="200" cy="200" r="135" fill="url(#crystalCore)" opacity="0.4" className="crystal-breathe" />

      <g className="crystal-float" style={{ transformOrigin: '200px 200px' }}>
        <g className="crystal-spin" style={{ transformOrigin: '200px 200px' }}>
          <polygon points="200,100 130,200 200,300 270,200" fill="none" stroke="var(--holo-1)" strokeWidth="0.6" opacity="0.25" />
        </g>

        <polygon points="200,100 130,180 270,180" fill="url(#crystalFront)" stroke="var(--holo-1)" strokeWidth="1.2" filter="url(#cryGlow)" />
        <polygon points="200,100 165,180 235,180" fill="url(#crystalSide)" stroke="var(--holo-1)" strokeWidth="0.6" opacity="0.7" />

        <polygon points="130,180 270,180 245,210 155,210" fill="url(#crystalSide)" stroke="var(--holo-1)" strokeWidth="1" />
        <line x1="200" y1="180" x2="200" y2="210" stroke="var(--holo-1)" strokeWidth="0.6" opacity="0.5" />

        <polygon points="155,210 245,210 200,310" fill="url(#crystalFront)" stroke="var(--holo-1)" strokeWidth="1.2" filter="url(#cryGlow)" />
        <polygon points="178,210 222,210 200,310" fill="url(#crystalSide)" stroke="var(--holo-1)" strokeWidth="0.6" opacity="0.7" />

        <line x1="130" y1="180" x2="155" y2="210" stroke="var(--holo-1)" strokeWidth="0.8" opacity="0.7" />
        <line x1="270" y1="180" x2="245" y2="210" stroke="var(--holo-1)" strokeWidth="0.8" opacity="0.7" />

        <polygon points="200,108 142,178 198,178" fill="url(#crystalGlow)" opacity="0.35" />

        <g filter="url(#cryGlow)">
          <circle cx="180" cy="160" r="2" fill="#FFFFFF" className="crystal-sparkle" />
          <circle cx="220" cy="170" r="1.5" fill="#FFFFFF" className="crystal-sparkle" style={{ animationDelay: '0.6s' }} />
          <circle cx="200" cy="245" r="1.8" fill="#FFFFFF" className="crystal-sparkle" style={{ animationDelay: '1.2s' }} />
        </g>

        <circle cx="200" cy="195" r="14" fill="url(#crystalCore)" className="crystal-core-pulse" />
      </g>

      <line x1="80" y1="200" x2="320" y2="200" stroke="var(--holo-1)" strokeWidth="1.2" className="holo-scan" opacity="0.85" />

      <g className="sat-orbit" style={{ transformOrigin: '200px 200px' }}>
        <g transform="translate(200, 56)">
          <circle r="4" fill="var(--holo-1)" className="holo-dot" filter="url(#cryGlow)" />
          <circle r="9" fill="none" stroke="var(--holo-1)" strokeWidth="0.6" opacity="0.6" />
        </g>
      </g>
      <g className="sat-orbit-rev" style={{ transformOrigin: '200px 200px' }}>
        <g transform="translate(60, 200)">
          <circle r="3" fill="var(--holo-2)" className="holo-dot" filter="url(#cryGlow)" />
        </g>
      </g>

      {mode === 'register' && (
        <g filter="url(#cryGlow)">
          <line x1="200" y1="100" x2="200" y2="60"  stroke="var(--holo-1)" strokeWidth="1" className="forge-beam" />
          <line x1="170" y1="115" x2="155" y2="80" stroke="var(--holo-1)" strokeWidth="0.8" className="forge-beam" style={{ animationDelay: '0.4s' }} />
          <line x1="230" y1="115" x2="245" y2="80" stroke="var(--holo-1)" strokeWidth="0.8" className="forge-beam" style={{ animationDelay: '0.8s' }} />
        </g>
      )}
    </svg>
  ), [mode]);

  // ───────────────────────────────────────────────────────────────────
  // Passkey login flow — strong auth that bypasses 2FA. Email is NOT
  // required: when omitted the backend returns an empty allowCredentials
  // list and the browser/OS shows the system passkey picker.
  // ───────────────────────────────────────────────────────────────────
  const handlePasskeyLogin = async () => {
    if (authBusyRef.current || authCompleted) return;

    // Detect Telegram WebView / unsupported browsers up front.
    if (!window.PublicKeyCredential || !navigator.credentials || typeof navigator.credentials.get !== 'function') {
      const isTelegram = /Telegram/i.test(navigator.userAgent) || !!window.Telegram?.WebApp;
      toast.error(
        isTelegram
          ? (lang === 'ru'
              ? 'Telegram WebView не поддерживает Passkey. Откройте сайт в обычном браузере (Safari/Chrome).'
              : 'Telegram in-app browser does not support Passkey. Open the site in Safari/Chrome.')
          : (lang === 'ru' ? 'Этот браузер не поддерживает Passkey.' : 'This browser does not support Passkey.'),
        { duration: 6000 }
      );
      return;
    }

    authBusyRef.current = true;
    setIsVerifying(true);
    try {
      // Step 1: ask backend for assertion options. Email is optional —
      // we only send it as a hint if the user has typed something.
      const hintEmail = email.trim();
      const startRes = await fetch(`${API}/security/passkey/login/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(hintEmail ? { email: hintEmail } : {}),
      });
      const startData = await startRes.json();
      if (!startRes.ok) {
        if (startData?.detail === 'passkey_not_available') {
          toast.error(lang === 'ru' ? 'У этого аккаунта нет привязанного Passkey' : 'No passkey registered for this account');
        } else {
          toast.error(formatErrorDetail(startData?.detail) || (lang === 'ru' ? 'Ошибка Passkey' : 'Passkey error'));
        }
        return;
      }
      const { challenge_id, options } = startData;

      // Step 2: prompt the platform authenticator
      const b64urlToBuf = (s) => {
        const pad = '='.repeat((4 - s.length % 4) % 4);
        const b64 = (s + pad).replace(/-/g, '+').replace(/_/g, '/');
        const raw = window.atob(b64);
        const arr = new Uint8Array(raw.length);
        for (let i = 0; i < raw.length; ++i) arr[i] = raw.charCodeAt(i);
        return arr.buffer;
      };
      const bufToB64url = (buf) => {
        const bytes = new Uint8Array(buf);
        let bin = '';
        for (let i = 0; i < bytes.byteLength; i++) bin += String.fromCharCode(bytes[i]);
        return window.btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
      };

      const assertion = await navigator.credentials.get({
        publicKey: {
          ...options,
          challenge: b64urlToBuf(options.challenge),
          allowCredentials: (options.allowCredentials || []).map((c) => ({
            ...c,
            id: b64urlToBuf(c.id),
          })),
        },
      });

      // Step 3: send back to backend → receive JWT
      const credentialJSON = {
        id: assertion.id,
        rawId: bufToB64url(assertion.rawId),
        type: assertion.type,
        response: {
          authenticatorData: bufToB64url(assertion.response.authenticatorData),
          clientDataJSON: bufToB64url(assertion.response.clientDataJSON),
          signature: bufToB64url(assertion.response.signature),
          userHandle: assertion.response.userHandle ? bufToB64url(assertion.response.userHandle) : null,
        },
      };

      const finishRes = await fetch(`${API}/security/passkey/login/finish`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          challenge_id,
          // Email omitted on purpose — backend identifies the user from the
          // credential id returned by the authenticator (discoverable flow).
          credential: credentialJSON,
        }),
      });
      const finishData = await finishRes.json();
      if (!finishRes.ok) {
        toast.error(formatErrorDetail(finishData?.detail) || (lang === 'ru' ? 'Не удалось войти через Passkey' : 'Passkey login failed'));
        return;
      }
      await finishAuth(finishData);
    } catch (e) {
      if (e?.name === 'NotAllowedError') {
        toast.error(lang === 'ru' ? 'Вход отменён' : 'Login cancelled');
      } else {
        toast.error(e?.message || (lang === 'ru' ? 'Ошибка Passkey' : 'Passkey error'));
      }
    } finally {
      setIsVerifying(false);
      if (!authCompleted) authBusyRef.current = false;
    }
  };

  const finishAuth = async (data) => {
    // Lock all auth-trigger buttons immediately — BEFORE the success toast
    // / setUser / navigate happen, so the user cannot fire a second login
    // request in the window between toast and route change.
    setAuthCompleted(true);
    // Telegram "link to existing" intent is now consumed — clear it so future
    // opens auto-login normally.
    try { sessionStorage.removeItem('tg_link_intent'); } catch (_) {}
    // Referral invite popup: show ONLY on login (not registration). Registration
    // paths set `just_registered` right before calling finishAuth.
    const wasRegistration = localStorage.getItem('just_registered') === '1';
    localStorage.removeItem('just_registered');
    if (!wasRegistration) {
      localStorage.setItem('pending_referral_invite', '1');
    }
    localStorage.setItem('token', data.token);
    localStorage.setItem('ton_city_token', data.token);
    // If the user arrived via the Telegram browser deep-link "Link to existing
    // account" choice, attach that Telegram identity to the account they just
    // logged into.
    try {
      const pendingJti = sessionStorage.getItem('tg_pending_link_jti');
      if (pendingJti) {
        sessionStorage.removeItem('tg_pending_link_jti');
        const lr = await fetch(`${API}/auth/telegram/login-link/link/${pendingJti}`, {
          method: 'POST',
          headers: { 'Authorization': `Bearer ${data.token}` },
        });
        if (lr.ok) {
          toast.success(lang === 'ru' ? 'Telegram привязан к аккаунту' : 'Telegram linked to your account');
        }
      }
    } catch (_) { /* non-fatal */ }
    // Suppress session_invalidated kick UX for the next ~6s. In-flight
    // requests fired with the OLD token before this moment will 401 with
    // session_invalidated, but they are NOT real kicks — the user just
    // successfully logged in. Also clear any previous "kick fired" latch so
    // legitimate future kicks (real other-device login) still work.
    try {
      window.__ton_city_kick_fired = false;
      window.__ton_city_just_logged_in_at = Date.now();
    } catch (_) { /* noop */ }
    // Dispatch event for MaintenanceOverlay
    window.dispatchEvent(new Event('ton-city-auth'));
    if (data.user) {
      setUser(data.user);
    }
    toast.success(t('loggedIn'));
    
    // Вызываем checkAuth из App.js для обновления глобального состояния
    if (onAuthSuccess) {
      await onAuthSuccess();
    }
    
    // Переходим на /ton-island после успешного входа
    navigate('/ton-island');
  };

  // --- Telegram authentication -------------------------------------------
  const [tgLoggingIn, setTgLoggingIn] = useState(false);
  const [tg2faToken, setTg2faToken] = useState(null);
  const [tgChoice, setTgChoice] = useState(null); // {telegram, mode, payload}
  const [tg2faCode, setTg2faCode] = useState('');
  const [tg2faVerifying, setTg2faVerifying] = useState(false);
  // Universal login-link modal state
  const [tgLinkModal, setTgLinkModal] = useState(null); // { deeplink, jti, expiresAt }
  const tgPollRef = useRef({ timer: null, aborted: false });

  const loginWithMiniAppInitData = async (initData) => {
    const res = await fetch(`${API}/auth/telegram/miniapp`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ init_data: initData }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(formatErrorDetail(data.detail));
    if (data.status === 'choice_required') {
      setTgChoice({ telegram: data.telegram || {}, mode: 'miniapp', payload: initData });
      return;
    }
    if (data.require_2fa && data.pre_auth_token) { setTg2faToken(data.pre_auth_token); return; }
    if (data.is_new_signup) localStorage.setItem('just_registered', '1');
    finishAuth(data);
  };

  const loginWithWidget = async (widgetData) => {
    const res = await fetch(`${API}/auth/telegram/widget`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ data: widgetData }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(formatErrorDetail(data.detail));
    if (data.status === 'choice_required') {
      setTgChoice({ telegram: data.telegram || {}, mode: 'widget', payload: widgetData });
      return;
    }
    if (data.require_2fa && data.pre_auth_token) { setTg2faToken(data.pre_auth_token); return; }
    if (data.is_new_signup) localStorage.setItem('just_registered', '1');
    finishAuth(data);
  };

  // Create a brand-new account for an unlinked Telegram identity (chosen in
  // the TelegramChoiceModal).
  const tgCreateNew = async () => {
    if (!tgChoice) return;
    try {
      let res, data;
      if (tgChoice.mode === 'login-link') {
        res = await fetch(`${API}/auth/telegram/login-link/create/${tgChoice.payload}`, { method: 'POST' });
      } else {
        const url = tgChoice.mode === 'widget'
          ? `${API}/auth/telegram/widget/create`
          : `${API}/auth/telegram/miniapp/create`;
        const body = tgChoice.mode === 'widget'
          ? { data: tgChoice.payload }
          : { init_data: tgChoice.payload };
        res = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
      }
      data = await res.json();
      if (!res.ok) throw new Error(formatErrorDetail(data.detail));
      setTgChoice(null);
      if (data.is_new_signup) localStorage.setItem('just_registered', '1');
      finishAuth(data);
    } catch (e) {
      toast.error(e.message || t('tgLoginFailed'));
    }
  };

  // "Link to existing": immediately open the LOGIN page (Telegram button
  // hidden there) so the user signs in with another method. For the browser
  // deep-link flow we remember the jti so finishAuth() attaches this Telegram
  // identity right after login. For the Mini App flow, useTelegramAutoLink
  // handles the link automatically.
  const tgLinkExisting = () => {
    if (tgChoice?.mode === 'login-link' && tgChoice?.payload) {
      try { sessionStorage.setItem('tg_pending_link_jti', tgChoice.payload); } catch (_) {}
    }
    try { sessionStorage.setItem('tg_link_intent', '1'); } catch (_) {}
    setTgChoice(null);
    toast.info(lang === 'ru'
      ? 'Войдите в свой аккаунт — Telegram привяжется автоматически'
      : 'Log in to your account — Telegram will link automatically');
    // Open the login page (drops any ?mode=register, sets the tglink flag that
    // hides the Telegram button).
    navigate('/auth?tglink=1');
  };

  const submitTelegram2FA = async () => {
    if (!tg2faToken || !tg2faCode.trim()) return;
    try {
      setTg2faVerifying(true);
      const res = await fetch(`${API}/auth/telegram/verify-2fa`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pre_auth_token: tg2faToken, totp_code: tg2faCode.trim() }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(formatErrorDetail(data.detail));
      try { sessionStorage.removeItem('tg_preauth_token'); } catch (_) {}
      setTg2faToken(null);
      setTg2faCode('');
      finishAuth(data);
    } catch (e) {
      toast.error(e.message || 'Invalid 2FA code');
    } finally {
      setTg2faVerifying(false);
    }
  };

  // Pick up a pending Telegram 2FA challenge handed over from App.js (Mini App).
  useEffect(() => {
    try {
      const pending = sessionStorage.getItem('tg_preauth_token');
      if (pending) setTg2faToken(pending);
    } catch (_) { /* noop */ }
  }, []);

  const handleTelegramLogin = async () => {
    if (tgLoggingIn || authCompleted) return;
    try {
      setTgLoggingIn(true);
      // Inside a Telegram Mini App → seamless login via initData.
      const wa = window?.Telegram?.WebApp;
      if (wa?.initData && wa.initData.length > 0) {
        await loginWithMiniAppInitData(wa.initData);
        return;
      }
      // Browser (desktop & mobile web): universal deep-link flow — open the
      // bot with a one-time payload, poll for confirmation. No BotFather
      // /setdomain needed; works everywhere Telegram works.
      const startRes = await fetch(`${API}/auth/telegram/login-link/start`, { method: 'POST' });
      const startData = await startRes.json().catch(() => ({}));
      if (!startRes.ok) {
        toast.error(formatErrorDetail(startData?.detail) || t('tgBotNotConfigured'));
        return;
      }
      const expiresAt = Date.now() + (startData.expires_in || 300) * 1000;
      // Open the deeplink in a new tab / native Telegram
      try { window.open(startData.deeplink, '_blank', 'noopener,noreferrer'); } catch (_) {}
      setTgLinkModal({ deeplink: startData.deeplink, jti: startData.jti, expiresAt });
      // Start polling
      tgPollRef.current.aborted = false;
      const poll = async () => {
        if (tgPollRef.current.aborted) return;
        try {
          const r = await fetch(`${API}/auth/telegram/login-link/status/${startData.jti}`);
          const d = await r.json().catch(() => ({}));
          if (d?.status === 'choice_required') {
            // Unlinked Telegram identity → ask the user to create or link.
            tgPollRef.current.aborted = true;
            setTgLinkModal(null);
            setTgChoice({ telegram: d.telegram || {}, mode: 'login-link', payload: d.jti || startData.jti });
            return;
          }
          if (d?.status === 'confirmed' && d?.token) {
            tgPollRef.current.aborted = true;
            setTgLinkModal(null);
            if (d?.is_new_signup) localStorage.setItem('just_registered', '1');
            finishAuth({ token: d.token, user: d.user });
            return;
          }
          if (d?.status === 'expired' || d?.status === 'not_found') {
            tgPollRef.current.aborted = true;
            setTgLinkModal(null);
            toast.error(t('tgLoginLinkExpired'));
            return;
          }
          if (Date.now() > expiresAt) {
            tgPollRef.current.aborted = true;
            setTgLinkModal(null);
            toast.error(t('tgLoginLinkExpired'));
            return;
          }
        } catch (_) { /* transient */ }
        tgPollRef.current.timer = setTimeout(poll, 2000);
      };
      tgPollRef.current.timer = setTimeout(poll, 1500);
    } catch (e) {
      toast.error(e.message || t('tgLoginFailed'));
    } finally {
      setTgLoggingIn(false);
    }
  };

  // Cleanup polling on unmount / when the modal closes.
  useEffect(() => () => {
    tgPollRef.current.aborted = true;
    if (tgPollRef.current.timer) { clearTimeout(tgPollRef.current.timer); tgPollRef.current.timer = null; }
  }, []);

  const closeTgLinkModal = () => {
    tgPollRef.current.aborted = true;
    if (tgPollRef.current.timer) { clearTimeout(tgPollRef.current.timer); tgPollRef.current.timer = null; }
    setTgLinkModal(null);
  };


  // NOTE: neither Google GSI nor the Telegram Login Widget are loaded on mount
  // anymore. To keep the auth page network-silent until the user interacts,
  // third-party SDKs load ONLY inside their button click handlers:
  //   • Google → handleGoogleSignIn() builds the OAuth URL and redirects (no GSI SDK needed).
  //   • Telegram → handleTelegramLogin() uses the deep-link flow on click.


  // Initialize Google Sign In button
  useEffect(() => {
    if (googleLoaded && window.google && !showUsernameStep) {
      try {
        window.google.accounts.id.initialize({
          client_id: process.env.REACT_APP_GOOGLE_CLIENT_ID,
          callback: handleGoogleCallback,
        });
      } catch (e) {
        console.error('Google Sign In init error:', e);
      }
    }
  }, [googleLoaded, showUsernameStep]);

  const handleGoogleCallback = async (response) => {
    try {
      setIsVerifying(true);
      const res = await fetch(`${API}/auth/google`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ credential: response.credential, ...getFbCookies(), referral_code: localStorage.getItem('ref_code') || undefined })
      });
  
      const data = await res.json();
      if (!res.ok) throw new Error(formatErrorDetail(data.detail));
  
      // === ТРИГГЕР ФЕЙСБУКА (регистрация через Google) ===
      if (data.is_new_user) {
        localStorage.setItem('just_registered', '1');
        if (window.fbq) {
          window.fbq('track', 'CompleteRegistration');
          console.log('Фейсбук поймал регистрацию!');
        }
      }

      finishAuth(data);
    } catch (e) {
      toast.error(e.message || 'Google auth failed');
    } finally {
      setIsVerifying(false);
    }
  };

  // Google OAuth using redirect method (works on mobile)
  const handleGoogleSignIn = async () => {
    if (authBusyRef.current || authCompleted) return;
    authBusyRef.current = true;
    const clientId = process.env.REACT_APP_GOOGLE_CLIENT_ID;
    if (!clientId) {
      toast.error('Google Client ID not configured');
      authBusyRef.current = false;
      return;
    }
    const redirectUri = window.location.origin + '/auth/google/callback';
    const scope = 'email profile openid';
    const responseType = 'code';

    // F26: fetch a one-time state + PKCE challenge from the backend.
    let state = null, codeChallenge = null;
    try {
      const initRes = await fetch(`${API}/auth/google/init`, { method: 'POST' });
      if (initRes.ok) {
        const initData = await initRes.json();
        state = initData.state;
        codeChallenge = initData.code_challenge;
      }
    } catch (e) {
      // Non-fatal: fall back to legacy flow without state/PKCE.
      console.warn('OAuth init failed, continuing without PKCE:', e);
    }

    // Build Google OAuth URL
    const googleAuthUrl = new URL('https://accounts.google.com/o/oauth2/v2/auth');
    googleAuthUrl.searchParams.set('client_id', clientId);
    googleAuthUrl.searchParams.set('redirect_uri', redirectUri);
    googleAuthUrl.searchParams.set('response_type', responseType);
    googleAuthUrl.searchParams.set('scope', scope);
    googleAuthUrl.searchParams.set('access_type', 'offline');
    googleAuthUrl.searchParams.set('prompt', 'select_account');
    if (state && codeChallenge) {
      googleAuthUrl.searchParams.set('state', state);
      googleAuthUrl.searchParams.set('code_challenge', codeChallenge);
      googleAuthUrl.searchParams.set('code_challenge_method', 'S256');
      sessionStorage.setItem('google_oauth_state', state);
    }

    // Store current mode for after redirect
    localStorage.setItem('google_auth_mode', mode || 'login');

    // Redirect to Google
    window.location.href = googleAuthUrl.toString();
  };

  // Emergent Google OAuth (REMOVED). Use the regular /auth/google flow above.

  // Handle Emergent OAuth callback (REMOVED — keeps the URL clean if a stale
  // session_id fragment lingers from before, just strip it).
  useEffect(() => {
    const hash = window.location.hash;
    if (hash && hash.includes('session_id=')) {
      window.history.replaceState(null, '', window.location.pathname + window.location.search);
    }
  }, []);

  const handleEmailAuth = async () => {
    // Synchronous guard — see `authBusyRef` declaration for rationale.
    if (authBusyRef.current || authCompleted) return;
    authBusyRef.current = true;
    try {
      setIsVerifying(true);
      
      // Validation
      if (mode === 'register' && !username.trim()) {
        toast.error(lang === 'ru' ? 'Введите username' : 'Enter username');
        setIsVerifying(false);
        return;
      }
      if (mode === 'register' && username.trim().length > 20) {
        toast.error(lang === 'ru' ? 'Никнейм не должен превышать 20 символов' : 'Nickname must not exceed 20 characters');
        setIsVerifying(false);
        return;
      }
      if (!email.trim()) {
        toast.error(lang === 'ru' ? 'Введите email или username' : 'Enter email or username');
        setIsVerifying(false);
        return;
      }
      if (!password.trim()) {
        toast.error(lang === 'ru' ? 'Введите пароль' : 'Enter password');
        setIsVerifying(false);
        return;
      }
      // Unified password requirements check on register (single message)
      if (mode === 'register' && !isPasswordStrong(password)) {
        toast.error(PASSWORD_REQUIREMENTS_MSG[lang] || PASSWORD_REQUIREMENTS_MSG.en);
        setIsVerifying(false);
        return;
      }

      // Для регистрации используем новый endpoint с верификацией email
      const endpoint = mode === 'register' ? `${API}/auth/register/initiate` : `${API}/auth/login`;

      // FingerprintJS OSS — visitor_id (для проверки мульти-аккаунтинга)
      // Turnstile — анти-бот проверка (невидимая)
      let visitorId = '';
      let turnstileToken = '';
      try {
        const [fp, ts] = await Promise.all([
          import('@/lib/fingerprint').then(m => m.getVisitorId()).catch(() => ''),
          import('@/lib/turnstile').then(m => m.getTurnstileToken(mode === 'register' ? 'register' : 'login')).catch(() => ''),
        ]);
        visitorId = fp || '';
        turnstileToken = ts || '';
      } catch { /* noop */ }

      const res = await fetch(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email, password, username, visitor_id: visitorId, turnstile_token: turnstileToken, ...getFbCookies(), ...(mode === 'register' ? { referral_code: localStorage.getItem('ref_code') || undefined } : {}) })
        }
      );
  
      // Читаем текст ответа и парсим как JSON
      const responseText = await res.text();
      let data = null;
      try {
        data = JSON.parse(responseText);
      } catch (jsonErr) {
        console.error("JSON parse error:", jsonErr, "Response:", responseText);
      }
      
      if (!res.ok) {
        // Показываем ошибку от сервера
        const errorMsg = formatErrorDetail(data?.detail) || data?.message || (lang === 'ru' ? 'Неверные данные для входа' : 'Invalid credentials');
        toast.error(errorMsg);
        setIsVerifying(false);
        return;
      }
  
      if (!data) {
        toast.error(lang === 'ru' ? 'Ошибка сервера' : 'Server error');
        setIsVerifying(false);
        return;
      }

      // Проверяем статус ответа для регистрации
      if (mode === 'register') {
        if (data.status === 'verification_sent') {
          // Нужно ввести код верификации
          setPendingEmail(email);
          setShowVerificationStep(true);
          toast.success(lang === 'ru' ? 'Код отправлен на email' : 'Code sent to email');
          setIsVerifying(false);
          return;
        } else if (data.status === 'registered' && data.token) {
          // SMTP не настроен - регистрация прошла сразу
          localStorage.setItem('just_registered', '1');
          // === ТРИГГЕР ФЕЙСБУКА (регистрация через Email) ===
          if (window.fbq) {
            window.fbq('track', 'CompleteRegistration');
            console.log('Фейсбук поймал регистрацию!');
          }
          await finishAuth(data);
          return;
        }
      }
      
      // Проверяем требуется ли email-код (новый flow для логина)
      if (data.requires_email_code) {
        setPendingEmail(data.email || email);
        setShowLoginCodeStep(true);
        toast.info(lang === 'ru' ? 'Код подтверждения входа отправлен на email' : 'Login code sent to your email');
        setIsVerifying(false);
        return;
      }

      // Проверяем требуется ли 2FA
      if (data.requires_2fa) {
        setPending2FAEmail(email);
        setPending2FAPassword(password);
        setShow2FAStep(true);
        toast.info(lang === 'ru' ? 'Введите код из приложения аутентификации' : 'Enter code from authenticator app');
        setIsVerifying(false);
        return;
      }

      await finishAuth(data);
    } catch (e) {
      console.error("Email auth error:", e);
      // Показываем понятное сообщение об ошибке
      if (e.message === 'Failed to fetch') {
        toast.error(lang === 'ru' ? 'Ошибка соединения с сервером' : 'Server connection error');
      } else if (e.message?.includes('body stream') || e.message?.includes('already read')) {
        // Техническая ошибка - показываем общее сообщение
        toast.error(lang === 'ru' ? 'Неверные данные для входа' : 'Invalid credentials');
      } else {
        toast.error(lang === 'ru' ? 'Ошибка авторизации' : 'Auth failed');
      }
    } finally {
      setIsVerifying(false);
      // Release the synchronous guard ONLY on the error/early-exit path —
      // when `authCompleted` is true (set inside finishAuth) we leave the
      // ref locked so even a single late spam-click can't fire a second
      // request.
      if (!authCompleted) authBusyRef.current = false;
    }
  };

  // Подтверждение email кода
  const handleVerifyEmail = async () => {
    if (!verificationCode.trim()) {
      toast.error(t('enterCode'));
      return;
    }
    if (authBusyRef.current || authCompleted) return;
    authBusyRef.current = true;
    setIsVerifying(true);
    try {
      let visitorId = '';
      try {
        const mod = await import('@/lib/fingerprint');
        visitorId = await mod.getVisitorId();
      } catch { /* noop */ }

      const res = await fetch(`${API}/auth/register/verify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: pendingEmail, code: verificationCode.trim(), visitor_id: visitorId, ...getFbCookies(), referral_code: localStorage.getItem('ref_code') || undefined })
      });
      
      const responseText = await res.text();
      let data = null;
      try {
        data = JSON.parse(responseText);
      } catch (jsonErr) {
        console.error("JSON parse error:", jsonErr);
        toast.error(t('serverError'));
        return;
      }
      
      if (!res.ok) {
        toast.error(formatErrorDetail(data?.detail) || t('invalidCode'));
        return;
      }
      
      if (data.token) {
        // finishAuth shows its own success toast — avoid double notification
        localStorage.setItem('just_registered', '1');
        // === ТРИГГЕР ФЕЙСБУКА (завершение регистрации через Email) ===
        if (window.fbq) {
          window.fbq('track', 'CompleteRegistration');
          console.log('Фейсбук поймал регистрацию!');
        }
        await finishAuth(data);
      }
    } catch (e) {
      console.error("Verify error:", e);
      toast.error(t('verificationFailed'));
    } finally {
      setIsVerifying(false);
      if (!authCompleted) authBusyRef.current = false;
    }
  };

  // Verify the email-2FA code received during /auth/login (step 2 of login)
  const handleVerifyLoginEmailCode = async () => {
    if (!loginCode.trim()) {
      toast.error(t('enterCode'));
      return;
    }
    if (authBusyRef.current || authCompleted) return;
    authBusyRef.current = true;
    setIsVerifying(true);
    try {
      let visitorId = '';
      let turnstileToken = '';
      try {
        const [fp, ts] = await Promise.all([
          import('@/lib/fingerprint').then((m) => m.getVisitorId()).catch(() => ''),
          import('@/lib/turnstile').then((m) => m.getTurnstileToken('login')).catch(() => ''),
        ]);
        visitorId = fp || '';
        turnstileToken = ts || '';
      } catch { /* noop */ }

      const res = await fetch(`${API}/auth/login-verify-email`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email: pendingEmail,
          code: loginCode.trim(),
          visitor_id: visitorId,
          turnstile_token: turnstileToken,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        toast.error(formatErrorDetail(data?.detail) || t('invalidCode'));
        return;
      }
      if (data.token) {
        // finishAuth shows its own success toast — avoid double notification
        await finishAuth(data);
      }
    } catch (e) {
      console.error('Login email verify error:', e);
      toast.error(t('verificationFailed'));
    } finally {
      setIsVerifying(false);
      if (!authCompleted) authBusyRef.current = false;
    }
  };
  
  // Обработка входа с 2FA кодом
  const handle2FALogin = async () => {
    const codeToCheck = totpCode.trim();
    const minLength = useBackupCode ? 8 : 6;
    
    if (!codeToCheck || codeToCheck.length < minLength) {
      toast.error(useBackupCode ? t('enter8CharBackupCode') : t('enter6DigitCode'));
      return;
    }
    if (authBusyRef.current || authCompleted) return;
    authBusyRef.current = true;
    setIsVerifying(true);
    try {
      // ── Wallet-triggered 2FA: re-submit /auth/verify-wallet with totp_code
      if (walletPending2FA) {
        try {
          const res = await fetch(`${API}/auth/verify-wallet`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              address: wallet?.account?.address,
              language: lang,
              totp_code: codeToCheck,
              ...getFbCookies(),
              referral_code: localStorage.getItem('ref_code') || undefined,
              ...(extractProof() || {}),
            }),
          });
          const data = await res.json();
          if (!res.ok) {
            toast.error(formatErrorDetail(data?.detail) || t('invalid2FACode'));
            return;
          }
          if (data.token) {
            setWalletPending2FA(false);
            await finishAuth(data);
          }
        } catch (e) {
          console.error("Wallet 2FA error:", e);
          toast.error(t('authFailed'));
        }
        return;
      }

      let visitorId = '';
      let turnstileToken = '';
      try {
        const [fp, ts] = await Promise.all([
          import('@/lib/fingerprint').then(m => m.getVisitorId()).catch(() => ''),
          import('@/lib/turnstile').then(m => m.getTurnstileToken('login')).catch(() => ''),
        ]);
        visitorId = fp || '';
        turnstileToken = ts || '';
      } catch { /* noop */ }

      const res = await fetch(`${API}/auth/login-2fa`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          email: pending2FAEmail, 
          password: pending2FAPassword, 
          totp_code: codeToCheck,
          visitor_id: visitorId,
          turnstile_token: turnstileToken
        })
      });
      
      const data = await res.json();
      
      if (!res.ok) {
        toast.error(formatErrorDetail(data?.detail) || t('invalid2FACode'));
        return;
      }
      
      if (data.token) {
        await finishAuth(data);
      }
    } catch (e) {
      console.error("2FA login error:", e);
      toast.error(t('authFailed'));
    } finally {
      setIsVerifying(false);
      // Reset the re-entrancy guard on any non-success outcome so the user can
      // retry with a fresh TOTP code (codes rotate every 30s) without reloading.
      if (!authCompleted) authBusyRef.current = false;
    }
  };


  const changeLang = (newLang) => {
    setLang(newLang);
    localStorage.setItem('ton_city_lang', newLang);
  };

  const title = showUsernameStep 
    ? t('completeRegistration')
    : (mode === 'register' ? t('registerTitle') : t('loginTitle'));

  // Используем ref чтобы отслеживать уже обработанные кошельки и избежать двойных уведомлений
  const [walletProcessed, setWalletProcessed] = useState(false);

  // ── ton_proof nonce ─────────────────────────────────────────────────
  // Fetch a single-use nonce from the backend BEFORE the user connects a
  // wallet and register it as `tonProof` parameter with TonConnect. The
  // wallet will then sign our nonce and we send that signature (bound to
  // this exact session) to /api/auth/verify-wallet. This is what makes
  // the wallet login cryptographically safe — merely knowing the address
  // is no longer enough, the user must control the private key.
  useEffect(() => {
    if (!tonConnectUI) return;
    let cancelled = false;
    (async () => {
      try {
        // Bag2/Bag3 ROOT FIX: on the login screen NEVER keep an auto-restored
        // wallet session. TonConnect reconnects the previous wallet on refresh
        // and that restored session carries a STALE proof (old nonce) which
        // triggers "payload invalid or expired" / "ton_proof required". We wait
        // for the restore to settle and, if there is no auth token, drop it so
        // a wallet connects ONLY through the explicit "Wallet" button.
        try {
          await tonConnectUI.connectionRestored;
          const hasToken = localStorage.getItem('token') || localStorage.getItem('ton_city_token');
          if (!hasToken && tonConnectUI.connected) {
            try { await tonConnectUI.disconnect(); } catch (_) { /* noop */ }
          }
        } catch (_) { /* noop */ }
        try { sessionStorage.removeItem('ton_wallet_auth_intent'); } catch (_) { /* noop */ }

        if (cancelled) return;
        // Pre-arm a fresh single-use nonce for the upcoming connect.
        tonConnectUI.setConnectRequestParameters({ state: 'loading' });
        const res = await fetch(`${API}/auth/wallet/proof-payload`);
        const data = await res.json();
        if (cancelled) return;
        if (data?.payload) {
          tonConnectUI.setConnectRequestParameters({
            state: 'ready',
            value: { tonProof: data.payload },
          });
        } else {
          tonConnectUI.setConnectRequestParameters(null);
        }
      } catch (e) {
        console.warn('ton_proof nonce fetch failed:', e);
        try { tonConnectUI.setConnectRequestParameters(null); } catch (_) { /* noop */ }
      }
    })();
    return () => { cancelled = true; };
  }, [tonConnectUI]);

  // Extract ton_proof envelope from the connected wallet (present only
  // when the wallet supports the proof capability and the nonce was set
  // before connection). Falls back gracefully when absent.
  const extractProof = () => {
    try {
      const tp = wallet?.connectItems?.tonProof;
      if (!tp) return null;
      // Success shape: { proof: { timestamp, domain, signature, payload } }
      if (tp.proof) {
        return {
          proof: {
            timestamp: tp.proof.timestamp,
            domain: tp.proof.domain,
            signature: tp.proof.signature,
            payload: tp.proof.payload,
            state_init: wallet?.account?.walletStateInit || undefined,
          },
          public_key: wallet?.account?.publicKey || undefined,
        };
      }
    } catch (e) { /* noop */ }
    return null;
  };
  
  useEffect(() => {
    const verifyWallet = async () => {
      // Guard against double-processing the same connected wallet within one
      // mount. We intentionally DO NOT skip when a (possibly stale) token
      // exists — on the /auth page the connected wallet is the source of truth
      // for WHICH account to enter, so we always resolve ownership on the
      // backend (fixes "logged into the wrong account").
      if (walletProcessed) return;
      // Synchronous re-entrancy guard — hard-stops a duplicate verify fired in
      // the same tick before `walletProcessed` state has propagated.
      if (walletVerifyRef.current) return;

      // Bag #2/#3: wallet auth must start ONLY on an explicit user action.
      // When TonConnect auto-restores a previous session (page load, refresh
      // after an error, or right after logout) there is NO intent flag set, so
      // we DO NOT auto-verify and DO NOT redirect to the username screen. The
      // flag is written in the "Wallet" button click and survives the mobile
      // deep-link round-trip via sessionStorage (persists across reload).
      let _intent = false;
      try { _intent = sessionStorage.getItem('ton_wallet_auth_intent') === '1'; } catch (_) { /* noop */ }
      if (!_intent) return;

      if (wallet?.account?.address && !isVerifying && !showUsernameStep) {
        walletVerifyRef.current = true; // lock synchronously
        setIsVerifying(true);
        setWalletProcessed(true); // Отмечаем что начали обработку
        // Consume the intent now — a later refresh must NOT re-trigger verify.
        try { sessionStorage.removeItem('ton_wallet_auth_intent'); } catch (_) { /* noop */ }
        try {
          // Drop any stale token so the wallet-verify response becomes the
          // single source of truth for the session.
          try { localStorage.removeItem('token'); } catch (_) {}
          const response = await fetch(`${API}/auth/verify-wallet`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                address: wallet.account.address,
                language: lang,
                username: username,
                email: email,      
                password: password,
                ...getFbCookies(),
                referral_code: localStorage.getItem('ref_code') || undefined,
                ...(extractProof() || {}),
              })
          });

          const responseText = await response.text();
          let data = null;
          
          try {
            data = JSON.parse(responseText);
          } catch (jsonErr) {
            console.error("JSON parse error in verifyWallet:", jsonErr, "Response:", responseText);
            toast.error(lang === 'ru' ? 'Ошибка соединения с сервером' : 'Server connection error');
            return;
          }

          if (!response.ok) {
            throw new Error(formatErrorDetail(data?.detail) || 'Auth failed');
          }

          if (data.status === 'need_username') {
            // Pin the exact wallet address the SERVER just told us is
            // unclaimed. handleFinalRegister must use THIS value, not the
            // (potentially stale) React state from useTonWallet(), so the
            // second /auth/verify-wallet call cannot silently target a
            // different account.
            setPendingWalletAddress(data.wallet_address || wallet.account.address);
            setShowUsernameStep(true);
            toast.info(t('createNickname'));
          } else if (data.status === 'requires_2fa' || data.requires_2fa) {
            // Wallet-owner has TOTP — ask for the code, then re-submit
            // /auth/verify-wallet with `totp_code`.
            setWalletPending2FA(true);
            setShow2FAStep(true);
            setTotpCode('');
            setUseBackupCode(false);
            toast.info(t('enter2FACode'));
          } else if (data.token) {
            // === ТРИГГЕР ФЕЙСБУКА (регистрация через TON Connect) ===
            if (data.is_new_user) {
              localStorage.setItem('just_registered', '1');
              if (window.fbq) {
                window.fbq('track', 'CompleteRegistration');
                console.log('Фейсбук поймал регистрацию!');
              }
            }
            // Используем finishAuth для правильной обработки
            finishAuth(data);
          }
        } catch (error) {
          console.error("Auth error:", error);
          setWalletProcessed(false); // Сбрасываем при ошибке
          walletVerifyRef.current = false; // allow an explicit retry
          if (error.message === 'Failed to fetch') {
            toast.error(t('serverConnectionError'));
          } else {
            toast.error(error.message);
          }
        } finally {
          setIsVerifying(false);
        }
      }
    };

    verifyWallet();
  }, [wallet?.account?.address, lang, navigate, walletProcessed]);

  const handleFinalRegister = async () => {
    if (!username.trim()) {
      toast.error(t('enterUsername'));
      return;
    }
    if (authBusyRef.current || authCompleted) return;
    authBusyRef.current = true;
    setIsVerifying(true);
    try {
      // Use the pinned wallet address from the initial need_username response
      // — it's the ONLY address we know the server saw as unclaimed. Falling
      // back to `wallet.account.address` handles the (rare) case where the
      // state got dropped, but the normal path should always have it set.
      const targetWallet = pendingWalletAddress || wallet?.account?.address;
      if (!targetWallet) {
        toast.error(t('serverConnectionError'));
        authBusyRef.current = false;
        setIsVerifying(false);
        return;
      }
      // NOTE: We intentionally do NOT compare `targetWallet` (server-returned
      // UQ-form like "UQB69…") against `wallet.account.address` (TonConnect
      // raw form like "0:7af7…") — these are the SAME wallet in two
      // notations, so any string-level comparison would false-positive as
      // "wallet changed". The server-side race-guard in verify-wallet
      // (dup check on both raw_address AND wallet_address before insert)
      // already covers the real "user swapped wallets mid-flow" case.
      const response = await fetch(`${API}/auth/verify-wallet`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          address: targetWallet,
          language: lang,
          username: username.trim(),
          // NEVER leak the login-form email/password into a wallet-only
          // registration — the wallet flow creates a NEW account tied to the
          // wallet, and using leftover fields from the sign-in form has
          // caused users to accidentally try to attach someone else's email
          // (which the server would reject with 400 "Email already taken")
          // or, worse, pass a real password into an empty-email new account.
          ...getFbCookies(),
          referral_code: localStorage.getItem('ref_code') || undefined,
          ...(extractProof() || {}),
        })
      });

      const responseText = await response.text();
      let data = null;
      try {
        data = JSON.parse(responseText);
      } catch (jsonErr) {
        console.error("JSON parse error:", jsonErr, "Response:", responseText);
        toast.error(t('serverError'));
        return;
      }

      if (response.ok && data.token) {
        // === ТРИГГЕР ФЕЙСБУКА (регистрация через TON Connect) ===
        if (data.is_new_user) {
          localStorage.setItem('just_registered', '1');
          if (window.fbq) {
            window.fbq('track', 'CompleteRegistration');
            console.log('Фейсбук поймал регистрацию!');
          }
        }
        // Используем finishAuth для корректной обработки
        finishAuth(data);
      } else {
        toast.error(formatErrorDetail(data?.detail) || "Error");
      }
    } catch (e) {
      console.error("Registration error:", e);
      toast.error(t('serverConnectionError'));
    } finally {
      setIsVerifying(false);
    }
  };

  return (
    <div className="min-h-screen bg-void p-4 relative font-rajdhani overflow-hidden">
      {/* Telegram create/link choice modal */}
      <TelegramChoiceModal
        open={!!tgChoice}
        telegram={tgChoice?.telegram || {}}
        onCreateNew={tgCreateNew}
        onLinkExisting={tgLinkExisting}
        lang={lang}
      />

      {/* Telegram deep-link login modal (browser flow) */}
      {tgLinkModal && (        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4" data-testid="tg-link-modal">
          <div className="w-full max-w-sm rounded-2xl border border-white/10 bg-[#0f1420] p-6 text-center shadow-2xl">
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-xl" style={{ background: 'linear-gradient(135deg,#2AABEE,#229ED9)' }}>
              <Send className="h-6 w-6 text-white" />
            </div>
            <h3 className="font-unbounded text-base font-bold uppercase tracking-wide text-white">
              {t('tgLoginModalTitle')}
            </h3>
            <p className="mt-3 text-sm text-white/70 leading-relaxed">
              {t('tgLoginModalDesc')}
            </p>
            <a
              data-testid="tg-link-open"
              href={tgLinkModal.deeplink}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-5 inline-flex w-full items-center justify-center gap-2 rounded-xl py-3 text-xs font-bold uppercase tracking-widest text-white"
              style={{ background: 'linear-gradient(135deg,#2AABEE,#229ED9)' }}
            >
              <Send className="w-4 h-4" />
              {t('tgLoginModalOpen')}
            </a>
            <div className="mt-4 flex items-center justify-center gap-2 text-xs text-white/40">
              <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-cyan-400" />
              {t('tgLoginModalWaiting')}
            </div>
            <button
              data-testid="tg-link-cancel"
              onClick={closeTgLinkModal}
              className="mt-3 text-xs text-white/40 hover:text-white/70"
            >
              {t('tgLoginModalCancel')}
            </button>
          </div>
        </div>
      )}

      {/* Telegram 2FA challenge overlay */}
      {tg2faToken && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4" data-testid="tg-2fa-modal">
          <div className="w-full max-w-sm rounded-2xl border border-white/10 bg-[#0f1420] p-6 text-center shadow-2xl">
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-xl" style={{ background: 'linear-gradient(135deg,#2AABEE,#229ED9)' }}>
              <Lock className="h-6 w-6 text-white" />
            </div>
            <h3 className="font-unbounded text-base font-bold uppercase tracking-wide text-white">
              {t('tg2faTitle')}
            </h3>
            <p className="mt-1 mb-4 text-xs text-white/50">
              {t('tg2faDesc')}
            </p>
            <input
              data-testid="tg-2fa-input"
              value={tg2faCode}
              onChange={(e) => setTg2faCode(e.target.value.replace(/[^0-9a-zA-Z]/g, '').slice(0, 8))}
              onKeyDown={(e) => e.key === 'Enter' && submitTelegram2FA()}
              placeholder="000000"
              inputMode="numeric"
              className="mb-4 w-full rounded-xl border border-white/10 bg-panel px-4 py-3 text-center font-mono text-2xl tracking-[0.4em] text-white outline-none focus:border-cyber-cyan"
            />
            <button
              data-testid="tg-2fa-submit"
              onClick={submitTelegram2FA}
              disabled={tg2faVerifying || !tg2faCode.trim()}
              className="w-full rounded-xl py-3 text-xs font-bold uppercase tracking-widest text-white disabled:opacity-50"
              style={{ background: 'linear-gradient(135deg,#2AABEE,#229ED9)' }}
            >
              {tg2faVerifying ? '...' : t('tg2faVerify')}
            </button>
            <button
              onClick={() => { setTg2faToken(null); setTg2faCode(''); try { sessionStorage.removeItem('tg_preauth_token'); } catch (_) {} }}
              className="mt-3 text-xs text-white/40 hover:text-white/70"
            >
              {t('tg2faCancel')}
            </button>
          </div>
        </div>
      )}

      {/* Hi-Tech Futurism background (same as landing) */}
      <div className="hero-futurism tg-bleed-top" aria-hidden />
      <div className="hero-grid" aria-hidden />
      <div className="hero-glow-orb" style={{ top: '-100px', left: '-80px', width: 360, height: 360, background: 'rgba(122, 46, 255, 0.45)' }} aria-hidden />
      <div className="hero-glow-orb" style={{ bottom: '-120px', right: '-100px', width: 380, height: 380, background: 'rgba(34, 226, 255, 0.35)' }} aria-hidden />

      <div className="relative z-10 min-h-screen flex items-center justify-center">
        <div className="grid lg:grid-cols-[minmax(0,520px)_minmax(0,1fr)] gap-10 lg:gap-16 items-center w-full max-w-6xl mx-auto">
          {/* LEFT — auth form */}
          <motion.div 
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className={`glass-panel p-5 sm:p-8 rounded-3xl w-full max-w-md mx-auto lg:mx-0 border border-white/10 text-center relative shadow-2xl ${mode === 'register' ? 'pb-2 sm:pb-3' : ''}`}
            style={{ '--auth-acc': accentHex, '--auth-acc-deep': accentDeep }}
          >
        <button 
          onClick={() => {
            if (showVerificationStep) {
              setShowVerificationStep(false);
            } else if (showLoginCodeStep) {
              setShowLoginCodeStep(false);
              setLoginCode('');
            } else if (show2FAStep) {
              setShow2FAStep(false);
              setTotpCode('');
            } else if (showUsernameStep) {
              setShowUsernameStep(false);
            } else {
              navigate('/');
            }
          }} 
          className="absolute top-6 left-6 text-text-muted hover:text-white transition-colors"
        >
          <ArrowLeft className="w-6 h-6" />
        </button>
        
        <div className="w-16 h-16 rounded-2xl flex items-center justify-center mx-auto mb-6 auth-acc-shadow"
             style={{ background: `linear-gradient(135deg, ${accentDeep} 0%, ${accentHex} 100%)` }}>
          <Building2 className="text-black w-10 h-10" />
        </div>

        <h1 className="font-unbounded text-xl font-bold text-white mb-8 tracking-tighter uppercase" data-testid="auth-subtitle">
          {showVerificationStep 
            ? t('verifyEmail')
            : showLoginCodeStep
            ? (lang === 'ru' ? 'Подтверждение входа' : 'Login Verification')
            : show2FAStep
            ? t('twoFactorAuth')
            : title
          }
        </h1>

        <div className="space-y-3">
          <AnimatePresence mode="wait">
            {/* Email Verification Step */}
            {showVerificationStep ? (
              <motion.div 
                key="verification-step"
                initial={{ opacity: 0, x: 20 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -20 }}
                className="space-y-4"
              >
                <div className="p-4 bg-cyber-cyan/10 border border-cyber-cyan/20 rounded-xl mb-4">
                  <p className="text-cyber-cyan text-sm">
                    {t('codeSentToEmail')} {pendingEmail}
                  </p>
                </div>

                <div className="relative text-left max-w-[280px] mx-auto">
                  <Input
                    type="text"
                    inputMode="numeric"
                    value={verificationCode}
                    onChange={(e) => setVerificationCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                    placeholder="– – – – – –"
                    className="w-full px-4 py-4 bg-panel border border-white/10 rounded-xl text-white placeholder-white/25 focus:border-cyber-cyan focus:ring-1 focus:ring-cyber-cyan/50 text-center text-3xl tracking-[0.5em] font-mono"
                    maxLength={6}
                  />
                </div>

                <Button 
                  data-testid="verify-email-btn"
                  onClick={handleVerifyEmail}
                  disabled={isVerifying || authCompleted || verificationCode.length !== 6}
                  className="w-full bg-cyber-cyan text-black font-bold py-4 rounded-xl uppercase tracking-widest hover:bg-cyber-cyan/90 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isVerifying ? t('verifyingCode') : t('verify')}
                </Button>

                <p className="text-text-muted text-xs mt-4">
                  {t('checkSpamFolder')}
                </p>
              </motion.div>
            ) : showLoginCodeStep ? (
              /* Email-2FA Login Step — code sent after successful password check */
              <motion.div
                key="login-code-step"
                initial={{ opacity: 0, x: 20 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -20 }}
                className="space-y-4"
              >
                <div className="p-4 bg-cyber-cyan/10 border border-cyber-cyan/20 rounded-xl mb-4">
                  <p className="text-cyber-cyan text-sm">
                    {lang === 'ru'
                      ? `Код подтверждения входа отправлен на ${pendingEmail}`
                      : `Login code sent to ${pendingEmail}`}
                  </p>
                </div>

                <div className="relative text-left max-w-[280px] mx-auto">
                  <Input
                    data-testid="login-code-input"
                    type="text"
                    inputMode="numeric"
                    value={loginCode}
                    onChange={(e) => setLoginCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                    placeholder="– – – – – –"
                    className="w-full px-4 py-4 bg-panel border border-white/10 rounded-xl text-white placeholder-white/25 focus:border-cyber-cyan focus:ring-1 focus:ring-cyber-cyan/50 text-center text-3xl tracking-[0.5em] font-mono"
                    maxLength={6}
                  />
                </div>

                <Button
                  data-testid="verify-login-code-btn"
                  onClick={handleVerifyLoginEmailCode}
                  disabled={isVerifying || authCompleted || loginCode.length !== 6}
                  className="w-full bg-cyber-cyan text-black font-bold py-4 rounded-xl uppercase tracking-widest hover:bg-cyber-cyan/90 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isVerifying ? t('verifyingCode') : (lang === 'ru' ? 'Подтвердить вход' : 'Confirm login')}
                </Button>

                <p className="text-text-muted text-xs mt-4">
                  {t('checkSpamFolder')}
                </p>
              </motion.div>
            ) : show2FAStep ? (
              /* 2FA Verification Step */
              <motion.div 
                key="2fa-step"
                initial={{ opacity: 0, x: 20 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -20 }}
                className="space-y-4"
              >
                <div className="p-4 bg-neon-purple/10 border border-neon-purple/20 rounded-xl mb-4">
                  <div className="flex items-center justify-center gap-2 mb-2">
                    <Lock className="w-5 h-5 text-neon-purple" />
                    <span className="text-neon-purple text-sm font-bold">
                      {t('twoFactorAuthentication')}
                    </span>
                  </div>
                  <p className="text-white/60 text-xs">
                    {useBackupCode ? t('enter8CharBackupCode') : t('enter6DigitCode')}
                  </p>
                </div>

                <div className="relative text-left max-w-[280px] mx-auto">
                  <Input
                    type="text"
                    data-testid="totp-code-input"
                    inputMode={useBackupCode ? "text" : "numeric"}
                    value={totpCode}
                    onChange={(e) => {
                      if (useBackupCode) {
                        setTotpCode(e.target.value.slice(0, 8).toUpperCase());
                      } else {
                        setTotpCode(e.target.value.replace(/\D/g, '').slice(0, 6));
                      }
                    }}
                    placeholder={useBackupCode ? "––––––––" : "––––––"}
                    autoFocus
                    className={`w-full px-3 sm:px-4 py-4 bg-panel border border-white/10 rounded-xl text-white placeholder-white/25 focus:border-neon-purple focus:ring-1 focus:ring-neon-purple/50 text-center text-2xl sm:text-3xl font-mono ${useBackupCode ? 'tracking-[0.15em] sm:tracking-[0.3em]' : 'tracking-[0.25em] sm:tracking-[0.5em]'}`}
                    maxLength={useBackupCode ? 8 : 6}
                  />
                </div>

                {/* Toggle for backup code */}
                <button 
                  onClick={() => {
                    setUseBackupCode(!useBackupCode);
                    setTotpCode('');
                  }}
                  className="text-neon-purple text-xs hover:text-neon-purple/80 transition-colors underline"
                >
                  {useBackupCode ? t('useAppCode') : t('useBackupCode')}
                </button>

                <Button 
                  data-testid="verify-2fa-btn"
                  onClick={handle2FALogin}
                  disabled={isVerifying || authCompleted || totpCode.length !== (useBackupCode ? 8 : 6)}
                  className="w-full bg-neon-purple text-white font-bold py-4 rounded-xl uppercase tracking-widest hover:bg-neon-purple/90 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isVerifying ? t('verifyingCode') : t('signIn')}
                </Button>

                <button 
                  onClick={() => {
                    setShow2FAStep(false);
                    setTotpCode('');
                    setUseBackupCode(false);
                    setWalletPending2FA(false);
                    setWalletProcessed(false);
                  }}
                  className="text-text-muted text-xs hover:text-white transition-colors"
                >
                  {t('backToLogin')}
                </button>
              </motion.div>
            ) : showUsernameStep ? (
              <motion.div 
                key="username-step"
                initial={{ opacity: 0, x: 20 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -20 }}
                className="space-y-4"
              >
                <div className="p-4 bg-cyber-cyan/10 border border-cyber-cyan/20 rounded-xl mb-4 max-w-full overflow-hidden">
                  <p className="text-cyber-cyan text-xs uppercase tracking-widest flex items-center justify-center">
                    <CheckCircle2 className="w-4 h-4 mr-2" /> 
                    {t('walletConnected')}
                  </p>
                  <p className="text-white/40 text-[10px] mt-1 break-all leading-relaxed">
                    {wallet?.account?.address}
                  </p>
                </div>

                <div className="relative text-left max-w-[260px] mx-auto">
                  <UserCircle className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-cyber-cyan" />
                  <input 
                    placeholder={t('chooseUsername')}
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    autoFocus
                    maxLength={20}
                    className="w-full bg-white/5 border border-cyber-cyan/50 p-3 pl-10 rounded-xl text-white outline-none shadow-[0_0_15px_rgba(0,255,243,0.05)] focus:border-cyber-cyan transition-all text-sm"
                  />
                </div>

                <Button 
                  onClick={handleFinalRegister}
                  disabled={isVerifying || authCompleted}
                  className="w-full bg-cyber-cyan text-black font-bold py-6 hover:brightness-110 transition-all uppercase tracking-widest shadow-lg shadow-cyber-cyan/20"
                >
                  {isVerifying ? t('creating') : t('startGame')}
                </Button>
              </motion.div>
            ) : (
              <motion.div 
                key="login-step"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="space-y-4"
              >
                {mode === 'register' && (
                  <div className="relative text-left">
                    <UserCircle className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 auth-acc" />
                    <input 
                      placeholder={t('chooseUsername')}
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      maxLength={20}
                      data-testid="register-username-input"
                      className="auth-input w-full bg-white/5 border border-white/10 p-3 pl-10 rounded-xl text-white outline-none placeholder:text-white/20"
                    />
                  </div>
                )}

                <div className="relative text-left">
                  <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 auth-acc-soft" />
                  <input 
                    type="text"
                    data-testid="email-input"
                    placeholder={mode === 'register' ? 'Email' : t('emailOrUsername')}
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    onKeyPress={(e) => e.key === 'Enter' && handleEmailAuth()}
                    className="auth-input w-full bg-white/5 border border-white/10 p-3 pl-10 rounded-xl text-white outline-none placeholder:text-white/20"
                  />
                </div>

                <div className="relative text-left">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 auth-acc-soft" />
                  <input 
                    type={showPassword ? "text" : "password"}
                    placeholder={t('password')}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    onKeyPress={(e) => e.key === 'Enter' && handleEmailAuth()}
                    className="auth-input w-full bg-white/5 border border-white/10 p-3 pl-10 pr-10 rounded-xl text-white outline-none placeholder:text-white/20"
                    data-testid="password-input"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-text-muted hover:text-white transition-colors"
                    data-testid="toggle-password-visibility"
                    tabIndex={-1}
                  >
                    {showPassword ? <Eye className="w-5 h-5" /> : <EyeOff className="w-5 h-5" />}
                  </button>
                </div>

                {/* Submit button — agreement checkbox removed; consent line is at the very bottom of the modal */}
                <Button 
                  onClick={handleEmailAuth}
                  disabled={isVerifying || authCompleted}
                  data-testid="auth-submit-btn"
                  className="w-full auth-acc-bg auth-acc-shadow text-black font-bold py-6 hover:brightness-110 transition-all uppercase tracking-widest disabled:opacity-50 disabled:cursor-not-allowed">
                  {authCompleted ? '✓' : (isVerifying ? '...' : (mode === 'register' ? t('createAccount') : t('signIn')))}
                </Button>

                {/* Passkey login — appears only in LOGIN mode. The handler prompts
                    the platform authenticator and skips the 2FA step on success. */}
                {mode !== 'register' && (
                  <Button
                    onClick={handlePasskeyLogin}
                    disabled={isVerifying || authCompleted}
                    type="button"
                    variant="outline"
                    data-testid="passkey-login-btn"
                    className="w-full bg-transparent border border-white/15 hover:bg-white/5 text-white font-medium py-5 uppercase tracking-widest text-xs flex items-center justify-center gap-2 disabled:opacity-40"
                  >
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                      <circle cx="10" cy="8" r="4"/>
                      <path d="M10.85 12.15 19 4l1 1-2 2 2 2-3 3-2-2-3.15 3.15"/>
                      <circle cx="10" cy="14" r="6"/>
                    </svg>
                    {lang === 'ru' ? 'Войти с Passkey' : (lang === 'id' ? 'Masuk dengan Passkey' : 'Sign in with Passkey')}
                  </Button>
                )}

                {/* Кнопки переключения между входом и регистрацией */}
                <div className="flex items-center justify-center gap-4 text-sm">
                  {mode !== 'register' ? (
                    <>
                      <button 
                        onClick={() => navigate('/forgot-password')}
                        disabled={authCompleted}
                        className="text-text-muted hover:text-white transition-colors disabled:opacity-40 disabled:pointer-events-none"
                      >
                        {t('forgotPassword')}
                      </button>
                      <span className="text-white/20">|</span>
                      <button 
                        onClick={() => navigate('/auth?mode=register')}
                        disabled={authCompleted}
                        className="auth-acc hover:opacity-80 transition-opacity font-medium disabled:opacity-40 disabled:pointer-events-none"
                      >
                        {t('register')}
                      </button>
                    </>
                  ) : (
                    <button 
                      onClick={() => navigate('/auth?mode=login')}
                      disabled={authCompleted}
                      className="auth-acc hover:opacity-80 transition-opacity font-medium disabled:opacity-40 disabled:pointer-events-none"
                    >
                      {t('alreadyHaveAccount')}
                    </button>
                  )}
                </div>

                <div className="relative flex py-1 items-center !mt-1.5">
                  <div className="flex-grow border-t border-white/5"></div>
                  <span className="mx-4 text-text-muted text-[10px] uppercase tracking-[0.2em]">{t('orVia')}</span>
                  <div className="flex-grow border-t border-white/5"></div>
                </div>

                <div className="grid grid-cols-2 gap-3 !mt-1.5">
                  <Button 
                    data-testid="google-login-btn"
                    onClick={handleGoogleSignIn}
                    disabled={isVerifying || authCompleted}
                    variant="outline" 
                    className="border-white/10 hover:bg-white/5 h-12 text-xs uppercase tracking-widest disabled:opacity-50 whitespace-nowrap">
                    <Chrome className="w-4 h-4 mr-2" /> {t('google')}
                  </Button>

                  {/* Custom themed Connect-Wallet trigger — same dimensions
                      as the shadcn `<Button variant="outline">` Google CTA:
                      `h-10` (40 px) hard-cap so it never grows taller than
                      sibling buttons even with `py-6` padding utilities. */}
                  <button
                    type="button"
                    data-testid="ton-connect-btn"
                    disabled={isVerifying || authCompleted}
                    onClick={async () => {
                      if (authCompleted) return;
                      // Explicit, user-initiated intent — this is the ONLY thing
                      // that allows the verify effect to run. Set it FIRST so it
                      // survives the provider activation / tree remount below.
                      setWalletProcessed(false);
                      walletVerifyRef.current = false; // fresh attempt
                      try { sessionStorage.setItem('ton_wallet_auth_intent', '1'); } catch (_) { /* noop */ }
                      try {
                        // FIRST-CLICK FIX: get the REAL tonConnectUI. On a guest
                        // cold start the provider is inactive and `tonConnectUI`
                        // is an inert stub, so arming the nonce on it was a no-op
                        // and the modal opened without a proof — forcing a second
                        // click. ensureTonConnectUI() activates the provider and
                        // resolves with the live SDK, so the whole sequence below
                        // runs against the real UI on the very first click.
                        const ui = await ensureTonConnectUI();
                        // Always start from a clean slate so the wallet returns
                        // a FRESH proof bound to a FRESH nonce. A restored / prior
                        // connection carries a stale proof → "payload expired".
                        if (ui.connected) {
                          try { await ui.disconnect(); } catch (_) { /* noop */ }
                        }
                        // Fetch a fresh single-use nonce and register it BEFORE
                        // opening the connect modal.
                        try {
                          ui.setConnectRequestParameters({ state: 'loading' });
                          const res = await fetch(`${API}/auth/wallet/proof-payload`);
                          const data = await res.json();
                          if (data?.payload) {
                            ui.setConnectRequestParameters({ state: 'ready', value: { tonProof: data.payload } });
                          } else {
                            ui.setConnectRequestParameters(null);
                          }
                        } catch (_) {
                          try { ui.setConnectRequestParameters(null); } catch (_) { /* noop */ }
                        }
                        await ui.openModal();
                      } catch (e) {
                        console.error('TonConnect open failed:', e);
                      }
                    }}
                    className="group relative inline-flex items-center justify-center gap-2 rounded-md
                               h-12 px-4 py-2
                               text-[10px] font-bold uppercase tracking-widest text-white whitespace-nowrap
                               overflow-hidden transition-transform duration-200 hover:-translate-y-0.5 active:translate-y-0
                               disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:translate-y-0
                               border border-white/10"
                    style={{
                      background: 'linear-gradient(135deg, #0098EA 0%, #0079C0 60%, #005F9E 100%)',
                      boxShadow:  '0 6px 16px -8px rgba(0,152,234,0.55), inset 0 1px 0 rgba(255,255,255,0.18)',
                    }}
                  >
                    {/* gloss highlight */}
                    <span aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-1/2 bg-gradient-to-b from-white/20 to-transparent" />
                    {/* hover sweep */}
                    <span aria-hidden className="pointer-events-none absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-white/20 to-transparent transition-transform duration-700 group-hover:translate-x-full" />
                    <Wallet className="relative w-4 h-4 shrink-0" />
                    <span className="relative truncate">{lang === 'ru' ? 'Кошелёк' : 'Wallet'}</span>
                  </button>

                  {/* Hidden real TonConnectButton — kept so the SDK still tracks
                      wallet connection events / address via useTonWallet().
                      The element is invisible and removed from layout. */}
                  <div className="absolute w-0 h-0 overflow-hidden opacity-0 pointer-events-none" aria-hidden>
                    <TonConnectButton />
                  </div>
                </div>

                {/* Telegram login — placed under Google + Wallet.
                    Hidden when the user came here to LINK Telegram to an
                    existing account (they must log in another way first). */}
                {!tgLinkIntent && (
                <button
                  type="button"
                  data-testid="telegram-login-btn"
                  disabled={tgLoggingIn || isVerifying || authCompleted}
                  onClick={handleTelegramLogin}
                  className="group relative w-full inline-flex items-center justify-center gap-2 rounded-md
                             h-12 px-4 text-xs font-bold uppercase tracking-widest text-white whitespace-nowrap
                             overflow-hidden transition-transform duration-200 hover:-translate-y-0.5 active:translate-y-0
                             disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:translate-y-0 border border-white/10"
                  style={{
                    background: 'linear-gradient(135deg, #2AABEE 0%, #229ED9 100%)',
                    boxShadow: '0 6px 16px -8px rgba(42,171,238,0.6), inset 0 1px 0 rgba(255,255,255,0.2)',
                  }}
                >
                  <span aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-1/2 bg-gradient-to-b from-white/20 to-transparent" />
                  <span aria-hidden className="pointer-events-none absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-white/25 to-transparent transition-transform duration-700 group-hover:translate-x-full" />
                  <Send className="relative w-4 h-4 shrink-0" />
                  <span className="relative truncate">
                    {tgLoggingIn ? '...' : t('tgContinueButton')}
                  </span>
                </button>
                )}

                {tgLinkIntent && (
                  <p className="text-xs text-cyber-cyan/90 text-center leading-relaxed" data-testid="tg-link-hint">
                    {lang === 'ru'
                      ? 'Войдите в свой аккаунт — Telegram привяжется автоматически'
                      : 'Log in to your account — Telegram will link automatically'}
                  </p>
                )}

                {/* Implicit consent line — pinned to the very bottom of the registration modal,
                    underneath the social buttons. Same Terms/Privacy links as before. */}
                {mode === 'register' && (
                  <p className="text-xs text-gray-400 text-center leading-relaxed mt-1" data-testid="auth-implicit-consent">
                    {lang === 'ru'
                      ? 'При создании аккаунта вы соглашаетесь с '
                      : 'By creating an account you agree to the '}
                    <a href="/terms" className="auth-link" data-testid="auth-terms-link">{t('termsOfService')}</a>
                    {' '}{t('and')}{' '}
                    <a href="/privacy" className="auth-link" data-testid="auth-privacy-link">{t('privacyPolicy')}</a>.
                  </p>
                )}
              </motion.div>
            )}
          </AnimatePresence>

          <div className={mode === 'register' ? 'h-0' : 'h-2 mt-1'}>
            {isVerifying && (
              <p className="text-cyber-cyan text-[10px] animate-pulse font-mono uppercase tracking-[0.3em]">
                {t('verifying')}
              </p>
            )}
          </div>
        </div>
      </motion.div>

          {/* RIGHT — animated TON Crystal hologram (lg+ only) */}
          <motion.div
            initial={{ opacity: 0, scale: 0.92 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.7, delay: 0.15 }}
            className="hidden lg:flex flex-col items-center justify-center"
          >
            <div ref={tiltRef} className={`holo-frame holo-frame-xl holo-tilt ${mode === 'register' ? 'holo-theme-purple' : 'holo-theme-cyan'}`}>
              {crystalSvg}
            </div>

            <div className="mt-6 text-center font-orbitron text-[10px] tracking-[0.35em] uppercase" style={{ color: mode === 'register' ? 'rgba(167, 139, 250, 0.85)' : 'rgba(34, 226, 255, 0.7)' }}>
              <span className="inline-block w-1.5 h-1.5 rounded-full mr-2 holo-dot align-middle" style={{ background: mode === 'register' ? '#A78BFA' : '#22E2FF' }} />
              {mode === 'register' ? 'FORGING IDENTITY // Citizen Init' : 'CRYSTAL LINK // Secure Channel'}
            </div>
          </motion.div>
        </div>
      </div>
    </div>
  );
}
