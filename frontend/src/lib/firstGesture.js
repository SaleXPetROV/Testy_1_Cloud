/**
 * First user-gesture gate.
 *
 * Purpose: keep the COLD START of the app absolutely silent on the network for
 * plain-browser visitors and Safari's fraud scanner (which never interacts).
 * Any deferred work (session hydration, TonConnect init, analytics pixel) is
 * registered here and fires ONLY after the very first real interaction
 * (pointerdown / touch / key / scroll / wheel / mousedown).
 *
 * Inside a Telegram Mini App we do NOT rely on this — the app hydrates
 * immediately via the single allowed /api/auth/telegram/miniapp request.
 */

let fired = false;
const callbacks = [];
const EVENTS = ['pointerdown', 'touchstart', 'keydown', 'scroll', 'wheel', 'mousedown'];
const OPTS = { passive: true, capture: true };

function fire() {
  if (fired) return;
  fired = true;
  EVENTS.forEach((e) => {
    try { window.removeEventListener(e, fire, OPTS); } catch (_) { /* noop */ }
  });
  const pending = callbacks.splice(0);
  pending.forEach((cb) => { try { cb(); } catch (_) { /* noop */ } });
}

function ensureListening() {
  EVENTS.forEach((e) => {
    try { window.addEventListener(e, fire, OPTS); } catch (_) { /* noop */ }
  });
}

/** Run `cb` on the first user gesture (or immediately if one already happened). */
export function onFirstGesture(cb) {
  if (typeof cb !== 'function') return;
  if (fired) { try { cb(); } catch (_) { /* noop */ } return; }
  callbacks.push(cb);
  ensureListening();
}

/** True once the first user gesture has occurred. */
export function hasFiredGesture() {
  return fired;
}

/** Local, network-free check for the Telegram Mini App environment. */
export function isInsideTelegram() {
  try {
    return !!(window.Telegram?.WebApp?.initData && window.Telegram?.WebApp?.initDataUnsafe?.user);
  } catch (_) {
    return false;
  }
}

/**
 * Run `cb` immediately inside Telegram (real session, seamless), otherwise
 * defer it to the first user gesture. Use this to wrap any mount-time network
 * call so plain-browser cold start stays completely silent.
 */
export function runAfterFirstInteraction(cb) {
  if (typeof cb !== 'function') return;
  if (isInsideTelegram()) { try { cb(); } catch (_) { /* noop */ } return; }
  onFirstGesture(cb);
}
