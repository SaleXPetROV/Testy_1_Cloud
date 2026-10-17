// Demo/Real game-mode helpers + global request tagging.
// The current mode is persisted in localStorage. While in demo mode every
// request to the backend carries the `X-Game-Mode: demo` header so the backend
// guard can block real endpoints.

export const GAME_MODE_KEY = 'ton_city_game_mode';

export function getGameMode() {
  try {
    return localStorage.getItem(GAME_MODE_KEY) === 'demo' ? 'demo' : 'real';
  } catch (e) {
    return 'real';
  }
}

export function setGameMode(mode) {
  try {
    localStorage.setItem(GAME_MODE_KEY, mode === 'demo' ? 'demo' : 'real');
  } catch (e) { /* ignore */ }
}

export function isDemo() {
  return getGameMode() === 'demo';
}

// Switch the app into DEMO mode and hard-redirect into the demo hub. Mirrors
// the DemoModeToggle "enter demo" behavior. Used e.g. right after the tutorial
// is completed/skipped so new players land straight in the sandbox.
export async function enterDemoMode(redirectTo = '/my-businesses') {
  const backend = process.env.REACT_APP_BACKEND_URL || '';
  try {
    const token = localStorage.getItem('token');
    await fetch(`${backend}/api/demo/enter`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
  } catch (e) { /* ignore network errors — mode still flips locally */ }
  setGameMode('demo');
  try { localStorage.setItem('ton_city_mode_toast', 'demo'); } catch (e) { /* ignore */ }
  if (typeof window !== 'undefined') window.location.href = redirectTo;
}

// Switch the app into REAL mode and hard-redirect. Used right after the
// tutorial finishes/abandons so the player lands on the real "My Businesses"
// page (NOT the demo sandbox). Mirrors the DemoModeToggle "exit demo" call.
export async function enterRealMode(redirectTo = '/my-businesses') {
  const backend = process.env.REACT_APP_BACKEND_URL || '';
  try {
    const token = localStorage.getItem('token');
    await fetch(`${backend}/api/demo/exit`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
  } catch (e) { /* ignore network errors — mode still flips locally */ }
  setGameMode('real');
  if (typeof window !== 'undefined') window.location.href = redirectTo;
}

// Show the localized "not available in demo mode" toast. Imported lazily so
// this module has no hard dependency cycle with the toast/translations libs.
let _lastDemoToast = 0;
export function showDemoBlockedToast() {
  const now = Date.now();
  if (now - _lastDemoToast < 1500) return; // throttle bursts of blocked calls
  _lastDemoToast = now;
  Promise.all([
    import('@/components/ui/sonner'),
    import('@/lib/translations'),
  ]).then(([{ toast }, { translations }]) => {
    let lang = 'en';
    try { lang = localStorage.getItem('ton_city_lang') || 'en'; } catch (e) { /* ignore */ }
    const dict = translations[lang] || translations.en;
    toast.error(dict.demoBlockedToast || translations.en.demoBlockedToast);
  }).catch(() => { /* ignore */ });
}

export function isDemoBlockedResponse(status, detail) {
  return status === 403 && detail === 'demo_mode_blocked';
}

let _fetchPatched = false;

// Monkey-patch window.fetch once so raw fetch() calls to the backend also carry
// the X-Game-Mode header (many pages use fetch directly, not the axios client).
export function installGameModeFetch() {
  if (_fetchPatched || typeof window === 'undefined' || !window.fetch) return;
  _fetchPatched = true;
  const original = window.fetch.bind(window);
  const backend = process.env.REACT_APP_BACKEND_URL || '';
  window.fetch = function (input, init) {
    try {
      const url = typeof input === 'string' ? input : (input && input.url) || '';
      const isApi = url.includes('/api/') || url.startsWith('/api') || (backend && url.startsWith(backend));
      if (isApi) {
        init = init ? { ...init } : {};
        const headers = new Headers(
          init.headers || (typeof input !== 'string' && input && input.headers) || {}
        );
        headers.set('X-Game-Mode', isDemo() ? 'demo' : 'real');
        init.headers = headers;
      }
    } catch (e) { /* ignore */ }
    const _p = original(input, init);
    // Surface the localized "blocked in demo" toast for raw fetch() callers.
    _p.then((res) => {
      try {
        if (res && res.status === 403) {
          res.clone().json().then((body) => {
            if (isDemoBlockedResponse(403, body && body.detail)) showDemoBlockedToast();
          }).catch(() => { /* non-json */ });
        }
      } catch (e) { /* ignore */ }
    }).catch(() => { /* ignore */ });
    return _p;
  };
}
