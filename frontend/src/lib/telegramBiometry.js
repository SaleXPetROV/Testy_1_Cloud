// Telegram Mini App biometric helper.
//
// Wraps `window.Telegram.WebApp.BiometricManager` with a simple, promise-based
// API that always resolves — never rejects — so the caller can branch on the
// boolean result. Also handles the case where the API is unavailable (regular
// browser, Telegram Desktop, older Telegram versions).
//
// Reference: https://core.telegram.org/bots/webapps#biometricmanager

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
export const API = `${BACKEND_URL}/api`;

/** True if the page is running inside the Telegram Mini App WebView. */
export const isTelegramMiniApp = () => {
  try {
    return !!(window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.initData);
  } catch (_) {
    return false;
  }
};

/** True if biometry is supported on the current Telegram platform (mobile). */
export const isBiometryPlatformSupported = () => {
  try {
    if (!isTelegramMiniApp()) return false;
    const platform = (window.Telegram.WebApp.platform || '').toLowerCase();
    // Telegram Desktop / macOS / Linux / Windows Telegram Desktop and Web
    // versions never expose a fingerprint reader.
    const desktopPlatforms = ['tdesktop', 'macos', 'linux', 'windows', 'web', 'weba', 'webk'];
    if (desktopPlatforms.includes(platform)) return false;
    return !!window.Telegram.WebApp.BiometricManager;
  } catch (_) {
    return false;
  }
};

/** Wrap the callback-style Telegram API in a Promise. */
const promisify = (fn, ...args) => new Promise((resolve) => {
  try {
    fn(...args, (result, extra) => resolve({ result, extra }));
  } catch (e) {
    resolve({ result: false, extra: null, error: String(e && e.message || e) });
  }
});

/** Return the raw initData string (or empty string). */
export const getInitData = () => {
  try {
    return window.Telegram?.WebApp?.initData || '';
  } catch (_) {
    return '';
  }
};

/**
 * Initialize BiometricManager. Idempotent — safe to call many times.
 * Resolves with the manager object (or null if unsupported).
 */
export const initBiometry = async () => {
  if (!isBiometryPlatformSupported()) return null;
  const bio = window.Telegram.WebApp.BiometricManager;
  if (bio.isInited) return bio;
  await promisify(bio.init.bind(bio));
  return bio;
};

/**
 * @returns {Promise<{
 *   supported: boolean,       // running in TG mobile with BiometricManager
 *   available: boolean,       // device has enrolled fingerprint / Face ID
 *   accessRequested: boolean, // user has been asked for permission at least once
 *   accessGranted: boolean,   // user has allowed biometry for this bot
 *   tokenSaved: boolean,      // a secret is currently persisted in the enclave
 *   biometricType: string,    // 'finger' | 'face' | 'unknown'
 *   deviceId: string,         // stable per-user-per-app id
 * }>}
 */
export const getBiometryState = async () => {
  const base = {
    supported: false,
    available: false,
    accessRequested: false,
    accessGranted: false,
    tokenSaved: false,
    biometricType: 'unknown',
    deviceId: '',
  };
  const bio = await initBiometry();
  if (!bio) return base;
  return {
    supported: true,
    available: !!bio.isBiometricAvailable,
    accessRequested: !!bio.isAccessRequested,
    accessGranted: !!bio.isAccessGranted,
    tokenSaved: !!bio.isBiometricTokenSaved,
    biometricType: bio.biometricType || 'unknown',
    deviceId: bio.deviceId || '',
  };
};

/** Request permission to use biometry for this bot. Returns true on grant. */
export const requestBiometryAccess = async (reason = 'Confirm sensitive operations') => {
  const bio = await initBiometry();
  if (!bio) return false;
  if (bio.isAccessGranted) return true;
  const { result } = await promisify(bio.requestAccess.bind(bio), { reason });
  return !!result;
};

/**
 * Prompt for a fingerprint / Face ID scan.
 * @returns {Promise<{authenticated: boolean, token: string}>}
 *   `token` will be the secret previously saved via saveBiometryToken(); may
 *   be empty if no token was ever saved.
 */
export const authenticateBiometry = async (reason = 'Confirm withdrawal') => {
  const bio = await initBiometry();
  if (!bio) return { authenticated: false, token: '' };
  if (!bio.isAccessGranted) {
    const granted = await requestBiometryAccess(reason);
    if (!granted) return { authenticated: false, token: '' };
  }
  const { result, extra } = await promisify(bio.authenticate.bind(bio), { reason });
  const token = (extra && (extra.token || extra)) || bio.biometricToken || '';
  return { authenticated: !!result, token: token || '' };
};

/** Persist a secret inside the device secure enclave. Returns true on success. */
export const saveBiometryToken = async (secret) => {
  const bio = await initBiometry();
  if (!bio) return false;
  if (!bio.isAccessGranted) {
    const granted = await requestBiometryAccess('Enable biometric confirmations');
    if (!granted) return false;
  }
  const { result } = await promisify(bio.updateBiometricToken.bind(bio), String(secret || ''));
  return !!result;
};

/** Clear the persisted secret. Returns true on success. */
export const clearBiometryToken = async () => {
  const bio = await initBiometry();
  if (!bio) return false;
  const { result } = await promisify(bio.updateBiometricToken.bind(bio), '');
  return !!result;
};

/** Open Telegram's biometry settings screen for this bot. */
export const openBiometrySettings = async () => {
  const bio = await initBiometry();
  if (!bio || typeof bio.openSettings !== 'function') return false;
  try { bio.openSettings(); return true; } catch (_) { return false; }
};

// ---------------------------------------------------------------------------
// Backend-integrated helpers.
// ---------------------------------------------------------------------------

const authHeaders = () => {
  const token = localStorage.getItem('token') || localStorage.getItem('ton_city_token');
  return token ? { Authorization: `Bearer ${token}` } : {};
};

/** GET /api/security/telegram-biometry/status. */
export const fetchBiometryStatus = async () => {
  const res = await fetch(`${API}/security/telegram-biometry/status`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`status ${res.status}`);
  return res.json();
};

/** POST verify-identity → returns setup_challenge (short-lived). */
export const verifyIdentity = async ({ password, totpCode }) => {
  const res = await fetch(`${API}/security/telegram-biometry/register/verify-identity`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ password: password || null, totp_code: totpCode || null }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data?.detail || 'verify failed');
  return data;
};

/** POST register/finish — server mints the secret we then save to the enclave. */
export const registerBiometry = async ({ setupChallenge, deviceName }) => {
  const bio = await initBiometry();
  if (!bio) throw new Error('Biometry not available on this device');
  const deviceId = bio.deviceId || `${(window.Telegram?.WebApp?.initDataUnsafe?.user?.id) || 'unknown'}-${Date.now()}`;
  const res = await fetch(`${API}/security/telegram-biometry/register/finish`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({
      setup_challenge: setupChallenge,
      init_data: getInitData(),
      device_id: deviceId,
      device_name: deviceName || (bio.biometricType === 'face' ? 'Face ID' : 'Fingerprint'),
    }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data?.detail || 'register failed');
  const ok = await saveBiometryToken(data.biometric_token);
  if (!ok) throw new Error('Failed to save biometric token on device');
  return { deviceId, deviceName: data.device_name };
};

/**
 * Authenticate with biometry AND exchange the returned token for a
 * short-lived withdraw token. Returns the withdraw token or throws.
 */
export const biometryConfirmWithdrawal = async () => {
  const { authenticated, token } = await authenticateBiometry('Confirm withdrawal');
  if (!authenticated) throw new Error('Не удалось подтвердить биометрию');
  if (!token) throw new Error('Токен подтверждения не найден в защищённом хранилище устройства');
  const res = await fetch(`${API}/security/telegram-biometry/authenticate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ token, init_data: getInitData(), purpose: 'withdraw' }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data?.detail || 'authenticate failed');
  return data.withdraw_tg_biometry_token;
};

/** Delete a device's biometry from server + clear local enclave. */
export const removeBiometryDevice = async (deviceId) => {
  await fetch(`${API}/security/telegram-biometry/delete`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ device_id: deviceId }),
  });
  await clearBiometryToken();
  return true;
};
